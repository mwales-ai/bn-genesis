from .loader import *
from .checksum import *
from .assemble import *
from .call_table_enum import *
from .vdp_analysis import *
from .game_definition import *
from .sprite_viewer import SpriteViewerSidebarWidgetType

GenesisView.register()

# Register the sprite viewer sidebar widget
SpriteViewerSidebarWidgetType()
