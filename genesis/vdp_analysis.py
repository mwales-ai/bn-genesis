"""
Analyzes VDP-related code and annotates instructions with human-readable comments
describing what each VDP control port write does.

Handles:
  - VDP register writes  (control word bits 15-13 == 0b100)
  - VRAM/CRAM/VSRAM address setup commands (32-bit writes to 0xC00004)
  - Bit-level decoding for Mode1 (R0) and Mode2 (R1) registers
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
# Bit-level decoders for the most important VDP registers
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


_REG_DECODERS = {
    0: _decode_mode1,
    1: _decode_mode2,
    11: _decode_mode3,
    12: _decode_mode4,
    16: _decode_plane_size,
}


# ---------------------------------------------------------------------------
# Core comment generators
# ---------------------------------------------------------------------------

def _comment_reg_write(word):
    """
    Decode a 16-bit VDP register write command word.
    Returns a comment string, or None if this word is not a register write.
    Bits 15-13 must be 0b100 for a register write.
    """
    if (word & 0xe000) != 0x8000:
        return None
    reg_num = (word >> 8) & 0x1f
    reg_val = word & 0xff

    decoder = _REG_DECODERS.get(reg_num)
    if decoder:
        return 'VDP ' + decoder(reg_val)
    return 'VDP {}={:#04x}'.format(_vdp_reg_name(reg_num), reg_val)


def _comment_address_cmd(high_word, low_word):
    """
    Decode a 32-bit VDP address/command setup write.
    Returns a comment string describing the target memory and address.

    32-bit command word layout (big-endian, written to 0xC00004):
      high_word: [CD1][CD0][A13..A8][A7..A0]
      low_word:  [0  ][0  ][0  ][0  ][0][0][0][0] [CD5][CD4][CD3][CD2][A15][A14][0][0]
    """
    cd = ((high_word >> 14) & 0x03) | (((low_word >> 4) & 0x0f) << 2)
    addr = (high_word & 0x3fff) | (((low_word >> 2) & 0x03) << 14)
    target = _VDP_CD_NAMES.get(cd, 'unknown(CD={:#08b})'.format(cd))
    return 'VDP {} @ {:#06x}'.format(target, addr)


def _is_address_cmd(word):
    """Return True if this 16-bit word looks like part of a VDP address command."""
    return (word & 0xe000) != 0x8000


class VdpAnalysis:

    def __init__(self, view):
        self.view = view

    def _comment_for_word(self, word):
        """Return a comment string for a single 16-bit VDP control write."""
        c = _comment_reg_write(word)
        if c is not None:
            return c
        # Partial address command (16-bit only sets CD1:CD0 and A13:A0)
        cd_partial = (word >> 14) & 0x03
        addr_partial = word & 0x3fff
        target = _VDP_CD_NAMES.get(cd_partial, 'cd={:#04x}'.format(cd_partial))
        return 'VDP {} @ {:#06x} (partial — needs 2nd word)'.format(
            target, addr_partial)

    def comment_register_set(self, cur_inst, target_addr, value_written, value_size):
        if target_addr != 0xc00004:
            return

        if value_size == 2:
            c = self._comment_for_word(value_written & 0xffff)
            self.view.set_comment_at(cur_inst.address, c)

        elif value_size == 4:
            # Big-endian: high word written first (to 0xC00004), low word second (0xC00006)
            high_word = (value_written >> 16) & 0xffff
            low_word = value_written & 0xffff

            c_high = _comment_reg_write(high_word)
            c_low = _comment_reg_write(low_word)

            if c_high is not None and c_low is not None:
                # Both halves are register writes
                comment = '{} | {}'.format(c_high, c_low)
            elif c_high is None and c_low is None:
                # Both halves together form an address command
                comment = _comment_address_cmd(high_word, low_word)
            else:
                # Mixed — comment each half individually
                comment = '{} | {}'.format(
                    c_high or self._comment_for_word(high_word),
                    c_low or self._comment_for_word(low_word)
                )
            self.view.set_comment_at(cur_inst.address, comment)

        else:
            log.log_debug('genesis: VDP write with unexpected size {}'.format(value_size))

    def comment_vdp_instructions(self, mlil_func):
        for cur_inst in mlil_func:
            if cur_inst.operation != binaryninja.MediumLevelILOperation.MLIL_STORE:
                continue

            dest, src = cur_inst.operands[0], cur_inst.operands[1]
            if not (isinstance(dest, binaryninja.mediumlevelil.MediumLevelILConstPtr) and
                    isinstance(src, binaryninja.mediumlevelil.MediumLevelILConst)):
                continue

            self.comment_register_set(
                cur_inst,
                dest.constant,
                src.constant,
                src.size
            )
