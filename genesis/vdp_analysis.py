"""
Analyzes VDP-related code and annotates instructions with human-readable comments
describing what each VDP control port write does.

Two-pass analysis:
  Pass 1 — Individual register writes: each VDP control port write gets a comment
           explaining the register name and decoded value.
  Pass 2 — Grouped DMA sequences: consecutive register writes that form a complete
           DMA transfer get a meta-comment summarizing the full operation with
           source/dest addresses that the user can click on in Binary Ninja.

Handles:
  - VDP register writes  (control word bits 15-13 == 0b100)
  - VRAM/CRAM/VSRAM address setup commands (32-bit writes to 0xC00004)
  - Bit-level decoding for Mode registers, Plane Size, DMA registers
  - DMA transfer grouping (R19-R23 + address command = one DMA operation)
"""

import binaryninja
from binaryninja import log

# ---------------------------------------------------------------------------
# VDP register name table (indices 0-23)
# ---------------------------------------------------------------------------
_VDP_REG_NAMES = [
    'Mode1',                            # R0
    'Mode2',                            # R1
    'PlaneA_NameTable_Addr',            # R2
    'Window_NameTable_Addr',            # R3
    'PlaneB_NameTable_Addr',            # R4
    'Sprite_Table_Addr',                # R5
    'Sprite_Pattern_Base_Addr',         # R6  (unused on MD)
    'Background_Color',                 # R7
    'Reg8_Unused',                      # R8
    'Reg9_Unused',                      # R9
    'HBlank_Counter',                   # R10
    'Mode3',                            # R11
    'Mode4',                            # R12
    'HScroll_Data_Addr',                # R13
    'Nametable_Pattern_Base_Addr',      # R14 (unused on MD)
    'Auto_Increment',                   # R15
    'Plane_Size',                       # R16
    'Window_HPos',                      # R17
    'Window_VPos',                      # R18
    'DMA_Length_Low',                   # R19
    'DMA_Length_High',                  # R20
    'DMA_Source_Low',                   # R21
    'DMA_Source_Mid',                   # R22
    'DMA_Source_High',                  # R23
]

# ---------------------------------------------------------------------------
# CD (code) field -> memory type + direction
# ---------------------------------------------------------------------------
_VDP_CD_NAMES = {
    0b000000: 'VRAM read',
    0b000001: 'VRAM write',
    0b000011: 'CRAM write',
    0b000100: 'VSRAM read',
    0b000101: 'VSRAM write',
    0b001000: 'CRAM read',
    0b100001: 'VRAM DMA write',
    0b100011: 'CRAM DMA write',
    0b100101: 'VSRAM DMA write',
}


def _vdp_reg_name(reg_num):
    if 0 <= reg_num < len(_VDP_REG_NAMES):
        return _VDP_REG_NAMES[reg_num]
    return 'REG_{}_INVALID'.format(reg_num)


# ---------------------------------------------------------------------------
# Bit-level decoders for individual VDP registers
# ---------------------------------------------------------------------------

def _decode_mode1(val):
    """Decode Mode Set Register 1 (R0) bitfield into a readable string."""
    bits = []
    if val & 0x10:
        bits.append('HInt=ON')
    else:
        bits.append('HInt=off')
    if val & 0x08:
        bits.append('left8blank')
    if val & 0x02:
        bits.append('HVlatch')
    return 'Mode1={:#04x} [{}]'.format(val, ', '.join(bits))


def _decode_mode2(val):
    """Decode Mode Set Register 2 (R1) bitfield into a readable string."""
    bits = []
    bits.append('display={}'.format('ON' if val & 0x40 else 'BLANK'))
    if val & 0x20:
        bits.append('VInt=ON')
    else:
        bits.append('VInt=off')
    if val & 0x10:
        bits.append('DMA=ON')
    if val & 0x08:
        bits.append('V30')
    if not (val & 0x04):
        bits.append('(mode5 off!)')
    return 'Mode2={:#04x} [{}]'.format(val, ', '.join(bits))


def _decode_mode3(val):
    """Decode Mode Set Register 3 (R11) - interlace and scroll modes."""
    hscroll = val & 0x03
    hscroll_modes = {0: 'HScroll=full', 1: 'HScroll=invalid',
                     2: 'HScroll=row', 3: 'HScroll=cell'}
    vscroll = 'VScroll=col' if val & 0x04 else 'VScroll=full'
    return 'Mode3={:#04x} [{}, {}]'.format(val, hscroll_modes[hscroll], vscroll)


def _decode_mode4(val):
    """Decode Mode Set Register 4 (R12) - resolution and interlace."""
    bits = []
    bits.append('H40' if val & 0x81 else 'H32')
    interlace = (val >> 1) & 0x03
    if interlace == 0:
        bits.append('no-interlace')
    elif interlace == 1:
        bits.append('interlace-normal')
    elif interlace == 3:
        bits.append('interlace-double')
    if val & 0x08:
        bits.append('shadow/highlight')
    return 'Mode4={:#04x} [{}]'.format(val, ', '.join(bits))


def _decode_plane_size(val):
    """Decode Plane Size register (R16)."""
    w_codes = {0: '32', 1: '64', 3: '128'}
    h_codes = {0: '32', 1: '64', 3: '128'}
    w = w_codes.get(val & 0x03, '?')
    h = h_codes.get((val >> 4) & 0x03, '?')
    return 'PlaneSize={:#04x} [{}x{}]'.format(val, w, h)


def _decode_auto_inc(val):
    """Decode Auto Increment register (R15)."""
    return 'AutoInc={:#04x} [+{} bytes]'.format(val, val)


def _decode_dma_len_low(val):
    """Decode DMA Length Low register (R19)."""
    return 'DMA_Len_Lo={:#04x} [low byte of DMA length]'.format(val)


def _decode_dma_len_high(val):
    """Decode DMA Length High register (R20)."""
    return 'DMA_Len_Hi={:#04x} [high byte of DMA length]'.format(val)


def _decode_dma_src_low(val):
    """Decode DMA Source Low register (R21)."""
    return 'DMA_Src_Lo={:#04x} [bits 1-8 of 68K source >> 1]'.format(val)


def _decode_dma_src_mid(val):
    """Decode DMA Source Mid register (R22)."""
    return 'DMA_Src_Mid={:#04x} [bits 9-16 of 68K source >> 1]'.format(val)


def _decode_dma_src_high(val):
    """Decode DMA Source High register (R23)."""
    dma_type = (val >> 6) & 0x03
    types = {0: '68K->VDP', 1: '68K->VDP', 2: 'VRAM fill', 3: 'VRAM copy'}
    src_bits = val & 0x3F
    return 'DMA_Src_Hi={:#04x} [bits 17-22={:#04x}, type={}]'.format(
        val, src_bits, types.get(dma_type, '?'))


_REG_DECODERS = {
    0: _decode_mode1,
    1: _decode_mode2,
    11: _decode_mode3,
    12: _decode_mode4,
    15: _decode_auto_inc,
    16: _decode_plane_size,
    19: _decode_dma_len_low,
    20: _decode_dma_len_high,
    21: _decode_dma_src_low,
    22: _decode_dma_src_mid,
    23: _decode_dma_src_high,
}


# ---------------------------------------------------------------------------
# Core comment generators
# ---------------------------------------------------------------------------

def _comment_reg_write(word):
    """
    Decode a 16-bit VDP register write command word.
    Returns (comment_string, reg_num, reg_val) or (None, None, None).
    Bits 15-13 must be 0b100 for a register write.
    """
    if (word & 0xe000) != 0x8000:
        return None, None, None
    reg_num = (word >> 8) & 0x1f
    reg_val = word & 0xff

    decoder = _REG_DECODERS.get(reg_num)
    if decoder:
        return 'VDP R{}: {}'.format(reg_num, decoder(reg_val)), reg_num, reg_val
    return 'VDP R{}: {}={:#04x}'.format(reg_num, _vdp_reg_name(reg_num), reg_val), reg_num, reg_val


def _comment_address_cmd(high_word, low_word):
    """
    Decode a 32-bit VDP address/command setup write.
    Returns (comment, cd_bits, address).
    """
    cd = ((high_word >> 14) & 0x03) | (((low_word >> 4) & 0x0f) << 2)
    addr = (high_word & 0x3fff) | (((low_word >> 2) & 0x03) << 14)
    target = _VDP_CD_NAMES.get(cd, 'unknown(CD={:#08b})'.format(cd))
    return 'VDP {} @ {:#06x}'.format(target, addr), cd, addr


def _is_dma_cd(cd):
    """Return True if this CD value indicates a DMA transfer."""
    return cd in (0b100001, 0b100011, 0b100101)


# ---------------------------------------------------------------------------
# DMA sequence reconstruction
# ---------------------------------------------------------------------------

def _build_dma_summary(reg_state, cd_bits, dest_addr, inst_addr):
    """
    Build a meta-comment describing a complete DMA transfer.

    reg_state: dict of {reg_num: (value, instruction_address)}
    cd_bits: CD field from the address command
    dest_addr: VDP destination address
    inst_addr: address of the triggering instruction
    """
    # Reconstruct DMA length (R19 + R20)
    len_lo = reg_state.get(19, (0, 0))[0]
    len_hi = reg_state.get(20, (0, 0))[0]
    dma_length = (len_hi << 8) | len_lo  # in words

    # Reconstruct DMA source (R21 + R22 + R23)
    src_lo = reg_state.get(21, (0, 0))[0]
    src_mid = reg_state.get(22, (0, 0))[0]
    src_hi = reg_state.get(23, (0, 0))[0]

    dma_type = (src_hi >> 6) & 0x03

    dest_type = _VDP_CD_NAMES.get(cd_bits, 'VDP')

    if dma_type <= 1:
        # 68K -> VDP DMA transfer
        source_addr = ((src_hi & 0x3F) << 17) | (src_mid << 9) | (src_lo << 1)
        byte_count = dma_length * 2

        return (
            '>>> [DMA] 68K->{}: {} bytes from 0x{:06X} to {} 0x{:04X}'.format(
                dest_type.split()[-1] if ' ' in dest_type else 'VDP',
                byte_count,
                source_addr,
                dest_type,
                dest_addr
            ),
            source_addr,
            byte_count
        )
    elif dma_type == 2:
        return (
            '>>> [DMA FILL] {} @ 0x{:04X}, length={} words'.format(
                dest_type, dest_addr, dma_length),
            None, None
        )
    elif dma_type == 3:
        source_vram = (src_mid << 8) | src_lo
        return (
            '>>> [DMA COPY] VRAM 0x{:04X} -> {} 0x{:04X}, length={} bytes'.format(
                source_vram, dest_type, dest_addr, dma_length),
            None, None
        )

    return None, None, None


# ---------------------------------------------------------------------------
# Main analysis class
# ---------------------------------------------------------------------------

class VdpAnalysis:

    def __init__(self, view):
        self.view = view

    def _comment_for_word(self, word):
        """Return a comment string for a single 16-bit VDP control write."""
        c, _, _ = _comment_reg_write(word)
        if c is not None:
            return c
        # Partial address command (16-bit only sets CD1:CD0 and A13:A0)
        cd_partial = (word >> 14) & 0x03
        addr_partial = word & 0x3fff
        target = _VDP_CD_NAMES.get(cd_partial, 'cd={:#04x}'.format(cd_partial))
        return 'VDP {} @ {:#06x} (partial — needs 2nd word)'.format(
            target, addr_partial)

    def comment_register_set(self, cur_inst, target_addr, value_written,
                             value_size, reg_state):
        """
        Decode a VDP control port write and add a Pass 1 comment.
        Also updates reg_state with any register values set.

        Returns (is_dma_trigger, cd_bits, dest_addr) if this write
        triggers a DMA transfer.
        """
        if target_addr != 0xc00004:
            return False, 0, 0

        if value_size == 2:
            word = value_written & 0xffff
            c, reg_num, reg_val = _comment_reg_write(word)
            if c is not None:
                self.view.set_comment_at(cur_inst.address, c)
                if reg_num is not None:
                    reg_state[reg_num] = (reg_val, cur_inst.address)
                return False, 0, 0
            else:
                c = self._comment_for_word(word)
                self.view.set_comment_at(cur_inst.address, c)
                return False, 0, 0

        elif value_size == 4:
            high_word = (value_written >> 16) & 0xffff
            low_word = value_written & 0xffff

            c_high, reg_hi, val_hi = _comment_reg_write(high_word)
            c_low, reg_lo, val_lo = _comment_reg_write(low_word)

            if c_high is not None and c_low is not None:
                # Both halves are register writes
                comment = '{} | {}'.format(c_high, c_low)
                self.view.set_comment_at(cur_inst.address, comment)
                if reg_hi is not None:
                    reg_state[reg_hi] = (val_hi, cur_inst.address)
                if reg_lo is not None:
                    reg_state[reg_lo] = (val_lo, cur_inst.address)
                return False, 0, 0

            elif c_high is None and c_low is None:
                # Both halves form an address/DMA command
                comment, cd_bits, dest_addr = _comment_address_cmd(high_word, low_word)
                self.view.set_comment_at(cur_inst.address, comment)
                if _is_dma_cd(cd_bits):
                    return True, cd_bits, dest_addr
                return False, 0, 0

            else:
                # Mixed
                comment = '{} | {}'.format(
                    c_high or self._comment_for_word(high_word),
                    c_low or self._comment_for_word(low_word)
                )
                self.view.set_comment_at(cur_inst.address, comment)
                if reg_hi is not None:
                    reg_state[reg_hi] = (val_hi, cur_inst.address)
                if reg_lo is not None:
                    reg_state[reg_lo] = (val_lo, cur_inst.address)
                return False, 0, 0

        return False, 0, 0

    def comment_vdp_instructions(self, mlil_func):
        """
        Two-pass VDP analysis on a single MLIL function.

        Pass 1: Walk each instruction, decode VDP writes, track register state.
        Pass 2: When a DMA trigger is found, build a meta-comment summarizing
                 the complete DMA operation with source/dest addresses.
        """
        # Shadow register state: {reg_num: (value, instruction_address)}
        reg_state = {}

        # Collect DMA triggers for pass 2
        dma_triggers = []

        # Pass 1: individual instruction comments + state tracking
        for cur_inst in mlil_func.instructions:
            if cur_inst.operation != binaryninja.MediumLevelILOperation.MLIL_STORE:
                continue

            dest, src = cur_inst.operands[0], cur_inst.operands[1]
            if not (isinstance(dest, binaryninja.mediumlevelil.MediumLevelILConstPtr) and
                    isinstance(src, binaryninja.mediumlevelil.MediumLevelILConst)):
                continue

            is_dma, cd_bits, dest_addr = self.comment_register_set(
                cur_inst, dest.constant, src.constant, src.size, reg_state)

            if is_dma:
                dma_triggers.append((cur_inst.address, cd_bits, dest_addr,
                                     dict(reg_state)))

        # Pass 2: add DMA meta-comments
        for inst_addr, cd_bits, dest_addr, state_snapshot in dma_triggers:
            summary, source_addr, byte_count = _build_dma_summary(
                state_snapshot, cd_bits, dest_addr, inst_addr)

            if summary:
                # Prepend the meta-comment to the existing instruction comment
                existing = self.view.get_comment_at(inst_addr) or ''
                if existing:
                    new_comment = summary + '\n' + existing
                else:
                    new_comment = summary
                self.view.set_comment_at(inst_addr, new_comment)

        log.log_info('genesis VDP: annotated {} instructions, {} DMA transfers'.format(
            len([1 for r in reg_state.values()]), len(dma_triggers)))
