from binaryninja import PluginCommand
from binaryninja import ChoiceField
from .genesis import GenesisChecksum, GenesisAssemble, GenesisCallTableEnum, VdpAnalysis, GenesisGameDefinition


def checksum(view):
    checksum = GenesisChecksum(view)
    checksum.start()


def assemble(view):
    assemble = GenesisAssemble(view)
    assemble.start()


def call_table_enum(view):
    cte = GenesisCallTableEnum(view)
    cte.start()

def comment_vdp_instructions(view, mlif):
    va = VdpAnalysis(view)
    va.comment_vdp_instructions(mlif)

PluginCommand.register(
    'genesis: fixup ROM checksum',
    'Fixup the SEGA Genesis ROM checksum',
    checksum
)

PluginCommand.register(
    'genesis: assemble and patch',
    'Assemble M68K code and apply blob as patch',
    assemble
)
PluginCommand.register(
    'genesis: enumerate call tables',
    'Locate and disassemble call tables',
    call_table_enum
)

PluginCommand.register_for_medium_level_il_function(
    'genesis: comment VDP inst for current function',
    'Iterate through selected function and comment VDP access instructions',
    comment_vdp_instructions
)

def load_game_definition(view):
    gd = GenesisGameDefinition(view)
    gd.start()

PluginCommand.register(
    'genesis: load game definition',
    'Load a game definition JSON and label sprites/palettes in ROM',
    load_game_definition
)

