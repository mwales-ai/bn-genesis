from binaryninja import (binaryview, Architecture, SegmentFlag,
                         SectionSemantics, Symbol, SymbolType, log,
                         StructureBuilder, Type)
import struct
import traceback


# ---------------------------------------------------------------------------
# Interrupt vector table: (byte_offset, symbol_name, description)
# ---------------------------------------------------------------------------
_VECTOR_TABLE = [
    # M68K exception vectors
    (0x08, 'exc_bus_error',          'Bus Error'),
    (0x0c, 'exc_address_error',      'Address Error'),
    (0x10, 'exc_illegal_inst',       'Illegal Instruction'),
    (0x14, 'exc_div_zero',           'Division by Zero'),
    (0x18, 'exc_chk',                'CHK Instruction'),
    (0x1c, 'exc_trapv',              'TRAPV Instruction'),
    (0x20, 'exc_privilege',          'Privilege Violation'),
    (0x24, 'exc_trace',              'Trace Exception'),
    (0x28, 'exc_line_a',             'Line-A Emulator (1010)'),
    (0x2c, 'exc_line_f',             'Line-F Emulator (1111)'),
    (0x30, 'exc_unused_0b',          'Reserved'),
    (0x34, 'exc_unused_0c',          'Reserved'),
    (0x38, 'exc_unused_0d',          'Reserved'),
    (0x3c, 'exc_unused_0e',          'Reserved'),
    (0x40, 'exc_unused_0f',          'Reserved'),
    (0x44, 'exc_unused_10',          'Reserved'),
    (0x48, 'exc_unused_11',          'Reserved'),
    (0x4c, 'exc_unused_12',          'Reserved'),
    (0x50, 'exc_unused_13',          'Reserved'),
    (0x54, 'exc_unused_14',          'Reserved'),
    (0x58, 'exc_unused_15',          'Reserved'),
    (0x5c, 'exc_unused_16',          'Reserved'),
    # IRQs
    (0x60, 'irq_spurious',           'Spurious Interrupt'),
    (0x64, 'irq_level1',             'IRQ Level 1 (ext)'),
    (0x68, 'irq_level2_ext',         'IRQ Level 2 (ext — EXT connector)'),
    (0x6c, 'irq_level3',             'IRQ Level 3 (ext)'),
    (0x70, 'hblank',                 'IRQ Level 4 — Horizontal Blank'),
    (0x74, 'irq_level5',             'IRQ Level 5'),
    (0x78, 'vblank',                 'IRQ Level 6 — Vertical Blank'),
    (0x7c, 'irq_level7_nmi',         'IRQ Level 7 (NMI)'),
    # TRAP vectors
    (0x80, 'trap_00',                'TRAP #0'),
    (0x84, 'trap_01',                'TRAP #1'),
    (0x88, 'trap_02',                'TRAP #2'),
    (0x8c, 'trap_03',                'TRAP #3'),
    (0x90, 'trap_04',                'TRAP #4'),
    (0x94, 'trap_05',                'TRAP #5'),
    (0x98, 'trap_06',                'TRAP #6'),
    (0x9c, 'trap_07',                'TRAP #7'),
    (0xa0, 'trap_08',                'TRAP #8'),
    (0xa4, 'trap_09',                'TRAP #9'),
    (0xa8, 'trap_10',                'TRAP #10'),
    (0xac, 'trap_11',                'TRAP #11'),
    (0xb0, 'trap_12',                'TRAP #12'),
    (0xb4, 'trap_13',                'TRAP #13'),
    (0xb8, 'trap_14',                'TRAP #14'),
    (0xbc, 'trap_15',                'TRAP #15'),
    # Remaining reserved vectors
    (0xc0, 'exc_unused_30',          'Reserved'),
    (0xc4, 'exc_unused_31',          'Reserved'),
    (0xc8, 'exc_unused_32',          'Reserved'),
    (0xcc, 'exc_unused_33',          'Reserved'),
    (0xd0, 'exc_unused_34',          'Reserved'),
    (0xd4, 'exc_unused_35',          'Reserved'),
    (0xd8, 'exc_unused_36',          'Reserved'),
    (0xdc, 'exc_unused_37',          'Reserved'),
    (0xe0, 'exc_unused_38',          'Reserved'),
    (0xe4, 'exc_unused_39',          'Reserved'),
    (0xe8, 'exc_unused_3a',          'Reserved'),
    (0xec, 'exc_unused_3b',          'Reserved'),
    (0xf0, 'exc_unused_3c',          'Reserved'),
    (0xf4, 'exc_unused_3d',          'Reserved'),
    (0xf8, 'exc_unused_3e',          'Reserved'),
    (0xfc, 'exc_unused_3f',          'Reserved'),
]


class GenesisView(binaryview.BinaryView):
    name = 'SG/SMD'
    long_name = 'SEGA Genesis/Megadrive ROM'

    def __init__(self, data):
        binaryview.BinaryView.__init__(self, parent_view=data,
                                       file_metadata=data.file)
        self.platform = Architecture['M68000'].standalone_platform
        self.raw = data

    @classmethod
    def is_valid_for_data(self, data):
        log.log_debug("Genesis is_valid_for_data running")
        console_name = data[0x100:0x110].decode('utf-8', errors='replace')
        if ('SEGA MEGA DRIVE' not in console_name.upper()) and \
                ('SEGA GENESIS' not in console_name.upper()):
            return False

        rom_start = struct.unpack('>I', data[0x1a0:0x1a4])[0]
        if rom_start != 0:
            return False

        software_type = data[0x180:0x182].decode('utf-8', errors='replace')
        if software_type != 'GM':
            return False

        return True

    # ------------------------------------------------------------------
    # Memory map
    # ------------------------------------------------------------------

    def create_segments(self):
        # ROM
        self.add_auto_segment(
            0, self.raw.length, 0, self.raw.length,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentExecutable
        )
        # Work RAM (64 KB)
        self.add_auto_segment(
            0xff0000, 0x10000, 0, 0,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable
        )
        # Z80 RAM (64 KB)
        self.add_auto_segment(
            0xa00000, 0x10000, 0, 0,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable
        )
        # I/O port registers
        self.add_auto_segment(
            0xa10000, 0x20, 0, 0,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable
        )
        # Z80 bus / memory-mode control
        self.add_auto_segment(
            0xa11000, 0x300, 0, 0,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable
        )
        # TMSS / cartridge security
        self.add_auto_segment(
            0xa14000, 0x10, 0, 0,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable
        )
        # YM2612 FM sound chip
        self.add_auto_segment(
            0xa04000, 0x10, 0, 0,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable
        )
        # VDP registers + PSG
        self.add_auto_segment(
            0xc00000, 0x20, 0, 0,
            SegmentFlag.SegmentReadable | SegmentFlag.SegmentWritable
        )

    def create_sections(self):
        self.add_auto_section(
            'header', 0, 8,
            SectionSemantics.ReadOnlyDataSectionSemantics)
        self.add_auto_section(
            'ivt', 8, 248,
            SectionSemantics.ReadOnlyDataSectionSemantics)
        self.add_auto_section(
            'rom_header', 0x100, 0x100,
            SectionSemantics.ReadOnlyDataSectionSemantics)
        self.add_auto_section(
            'code', 0x200, self.raw.length - 0x200,
            SectionSemantics.ReadOnlyCodeSectionSemantics)
        self.add_auto_section(
            'work_ram', 0xff0000, 0x10000,
            SectionSemantics.ReadWriteDataSectionSemantics)
        self.add_auto_section(
            'z80_ram', 0xa00000, 0x10000,
            SectionSemantics.ReadWriteDataSectionSemantics)
        self.add_auto_section(
            'io_ports', 0xa10000, 0x20,
            SectionSemantics.ReadWriteDataSectionSemantics)
        self.add_auto_section(
            'z80_ctrl', 0xa11000, 0x300,
            SectionSemantics.ReadWriteDataSectionSemantics)
        self.add_auto_section(
            'ym2612', 0xa04000, 0x10,
            SectionSemantics.ReadWriteDataSectionSemantics)
        self.add_auto_section(
            'vdp', 0xc00000, 0x20,
            SectionSemantics.ReadWriteDataSectionSemantics)

    # ------------------------------------------------------------------
    # Functions & vector table
    # ------------------------------------------------------------------

    def create_functions(self):
        uint32 = self.parse_type_string('uint32_t')[0]
        named = {offset: name for offset, name, _ in _VECTOR_TABLE}

        # Initial SP (offset 0) is data, not a function
        self.define_user_data_var(0, uint32)
        self.define_auto_symbol(Symbol(SymbolType.DataSymbol, 0, 'InitialStackPointer'))

        # Entry point (offset 4)
        entry_addr = struct.unpack('>I', self.raw.read(4, 4))[0]
        self.add_entry_point(entry_addr)
        self.define_auto_symbol(Symbol(SymbolType.FunctionSymbol, entry_addr, '_start'))
        self.add_function(entry_addr)

        seen = {entry_addr}

        for offset, name, description in _VECTOR_TABLE:
            raw_addr = struct.unpack('>I', self.raw.read(offset, 4))[0]
            if raw_addr == 0 or raw_addr >= self.raw.length:
                continue
            if raw_addr not in seen:
                self.add_function(raw_addr)
                seen.add(raw_addr)
            self.define_auto_symbol(
                Symbol(SymbolType.FunctionSymbol, raw_addr, name)
            )

    def create_datatype_and_name(self, addr, name, _type):
        self.define_user_data_var(addr, _type)
        self.define_auto_symbol(Symbol(SymbolType.DataSymbol, addr, name))

    # ------------------------------------------------------------------
    # ROM header as a proper struct type
    # ------------------------------------------------------------------

    def create_rom_header_struct(self):
        """Define GenesisRomHeader as a named struct and apply it at 0x100."""
        sb = StructureBuilder.create()
        sb.append(Type.array(Type.char(), 16), 'console_name')       # 0x100
        sb.append(Type.array(Type.char(), 16), 'copyright')           # 0x110
        sb.append(Type.array(Type.char(), 48), 'domestic_title')      # 0x120
        sb.append(Type.array(Type.char(), 48), 'international_title') # 0x150
        sb.append(Type.array(Type.char(), 14), 'serial_revision')     # 0x180
        sb.append(Type.int(2, False), 'checksum')                      # 0x18E
        sb.append(Type.array(Type.char(), 16), 'io_support')          # 0x190
        sb.append(Type.int(4, False), 'rom_start')                    # 0x1A0
        sb.append(Type.int(4, False), 'rom_end')                      # 0x1A4
        sb.append(Type.int(4, False), 'ram_start')                    # 0x1A8
        sb.append(Type.int(4, False), 'ram_end')                      # 0x1AC
        sb.append(Type.array(Type.char(), 12), 'sram_info')           # 0x1B0
        sb.append(Type.array(Type.char(), 4),  'modem_info')          # 0x1BC
        sb.append(Type.array(Type.char(), 40), 'notes')               # 0x1C0
        sb.append(Type.array(Type.char(), 16), 'region')              # 0x1E8

        struct_type = Type.structure_type(sb)
        type_id = Type.generate_auto_type_id('genesis', 'GenesisRomHeader')
        self.define_type(type_id, 'GenesisRomHeader', struct_type)

        header_type = self.get_type_by_name('GenesisRomHeader')
        if header_type:
            self.define_user_data_var(0x100, header_type)
            self.define_auto_symbol(
                Symbol(SymbolType.DataSymbol, 0x100, 'rom_header')
            )

    # ------------------------------------------------------------------
    # Hardware register labels
    # ------------------------------------------------------------------

    def create_vector_table(self):
        uint32 = self.parse_type_string('uint32_t')[0]
        # Initial SP
        self.create_datatype_and_name(0, 'InitialStackPointer', uint32)
        self.create_datatype_and_name(4, 'InitialPC', uint32)
        for offset, name, _ in _VECTOR_TABLE:
            self.create_datatype_and_name(offset, 'vec_' + name, uint32)

    def create_hardware_registers(self):
        uint8  = self.parse_type_string('uint8_t')[0]
        uint16 = self.parse_type_string('uint16_t')[0]
        uint32 = self.parse_type_string('uint32_t')[0]

        # --- I/O port registers (0xA10000) ---
        self.create_datatype_and_name(0xa10000, 'IO_VersionReg',            uint16)
        self.create_datatype_and_name(0xa10002, 'IO_Ctrl1_Data',            uint16)
        self.create_datatype_and_name(0xa10004, 'IO_Ctrl2_Data',            uint16)
        self.create_datatype_and_name(0xa10006, 'IO_Exp_Data',              uint16)
        self.create_datatype_and_name(0xa10008, 'IO_Ctrl1_TxRxCtrl',       uint16)
        self.create_datatype_and_name(0xa1000a, 'IO_Ctrl2_TxRxCtrl',       uint16)
        self.create_datatype_and_name(0xa1000c, 'IO_Exp_TxRxCtrl',         uint16)
        self.create_datatype_and_name(0xa1000e, 'IO_Ctrl1_SerialTx',       uint16)
        self.create_datatype_and_name(0xa10010, 'IO_Ctrl1_SerialRx',       uint16)
        self.create_datatype_and_name(0xa10012, 'IO_Ctrl1_SerialCtrl',     uint16)
        self.create_datatype_and_name(0xa10014, 'IO_Ctrl2_SerialTx',       uint16)
        self.create_datatype_and_name(0xa10016, 'IO_Ctrl2_SerialRx',       uint16)
        self.create_datatype_and_name(0xa10018, 'IO_Ctrl2_SerialCtrl',     uint16)
        self.create_datatype_and_name(0xa1001a, 'IO_Exp_SerialTx',         uint16)
        self.create_datatype_and_name(0xa1001c, 'IO_Exp_SerialRx',         uint16)
        self.create_datatype_and_name(0xa1001e, 'IO_Exp_SerialCtrl',       uint16)

        # --- Z80 bus / memory control (0xA11000) ---
        self.create_datatype_and_name(0xa11000, 'Z80_MemoryMode',          uint16)
        self.create_datatype_and_name(0xa11100, 'Z80_BusReq',              uint16)
        self.create_datatype_and_name(0xa11200, 'Z80_Reset',               uint16)

        # --- TMSS / cartridge copy-protection (0xA14000) ---
        self.create_datatype_and_name(0xa14000, 'TMSS_Register',           uint32)

        # --- YM2612 FM sound (0xA04000) ---
        # Bank 0
        self.create_datatype_and_name(0xa04000, 'YM2612_Bank0_Addr',       uint8)
        self.create_datatype_and_name(0xa04001, 'YM2612_Bank0_Data',       uint8)
        # Bank 1
        self.create_datatype_and_name(0xa04002, 'YM2612_Bank1_Addr',       uint8)
        self.create_datatype_and_name(0xa04003, 'YM2612_Bank1_Data',       uint8)

        # --- VDP (0xC00000) ---
        self.create_datatype_and_name(0xc00000, 'VDP_Data',                uint16)
        self.create_datatype_and_name(0xc00002, 'VDP_Data_Mirror',         uint16)
        self.create_datatype_and_name(0xc00004, 'VDP_Control',             uint16)
        self.create_datatype_and_name(0xc00006, 'VDP_Control_Mirror',      uint16)
        self.create_datatype_and_name(0xc00008, 'VDP_HV_Counter',          uint16)
        self.create_datatype_and_name(0xc0000a, 'VDP_HV_Counter_Mirror1',  uint16)
        self.create_datatype_and_name(0xc0000c, 'VDP_HV_Counter_Mirror2',  uint16)
        self.create_datatype_and_name(0xc0000e, 'VDP_HV_Counter_Mirror3',  uint16)
        # PSG (SN76489 compatible, write-only byte registers mirrored every 2 bytes)
        self.create_datatype_and_name(0xc00011, 'PSG_Data',                uint8)
        self.create_datatype_and_name(0xc00013, 'PSG_Data_Mirror1',        uint8)
        self.create_datatype_and_name(0xc00015, 'PSG_Data_Mirror2',        uint8)
        self.create_datatype_and_name(0xc00017, 'PSG_Data_Mirror3',        uint8)
        # VDP debug register (undocumented)
        self.create_datatype_and_name(0xc0001c, 'VDP_Debug',               uint16)
        self.create_datatype_and_name(0xc0001e, 'VDP_Debug_Mirror',        uint16)

    # ------------------------------------------------------------------
    # ROM header data (initial SP + PC already handled by create_functions)
    # ------------------------------------------------------------------

    def create_header(self):
        uint32 = self.parse_type_string('uint32_t')[0]
        self.create_datatype_and_name(0, 'InitialStackPointer', uint32)
        self.create_datatype_and_name(4, 'InitialPC', uint32)

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------

    def init(self):
        try:
            self.create_segments()
            self.create_sections()
            self.create_header()
            self.create_vector_table()
            self.create_rom_header_struct()
            self.create_hardware_registers()
            self.create_functions()
            return True
        except Exception:
            log.log_error(traceback.format_exc())
            return False

    def perform_get_address_size(self):
        return 4  # M68K is 32-bit

    def perform_is_executable(self):
        return True

    def perform_get_entry_point(self):
        return struct.unpack('>I', self.raw.read(4, 4))[0]
