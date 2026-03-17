"""
Load a game definition JSON file and apply sprite/palette labels and
structures to a Genesis ROM in Binary Ninja.
"""

import json
import os
from binaryninja import (
    BackgroundTaskThread,
    Symbol, SymbolType,
    Type, StructureBuilder,
    interaction,
    log_info, log_warn, log_error
)


class GenesisGameDefinition(BackgroundTaskThread):
    """Background task that loads a game definition JSON and labels ROM."""

    def __init__(self, view):
        BackgroundTaskThread.__init__(self, "Loading game definition...", True)
        self.view = view

    def run(self):
        path = interaction.get_open_filename_input(
            "Open Game Definition JSON", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            log_error(f"Failed to load game definition: {e}")
            return

        game_name = data.get('game_name', 'Unknown')
        log_info(f"Loading game definition: {game_name}")

        # Detect format: normalized (has "palettes" dict + "patterns" dict)
        # or legacy (has "sprite_groups" array)
        if 'palettes' in data and isinstance(data['palettes'], dict):
            self._load_normalized(data)
        elif 'sprite_groups' in data:
            self._load_legacy(data)
        else:
            log_warn("Unrecognized game definition format")

        log_info(f"Game definition loaded: {game_name}")

    def _create_tile_struct(self, width_tiles, height_tiles):
        """Create or retrieve a struct type for sprite tile data."""
        total_bytes = width_tiles * height_tiles * 32
        name = f"SpriteTiles_{width_tiles}x{height_tiles}"

        existing = self.view.get_type_by_name(name)
        if existing:
            return existing

        sb = StructureBuilder.create()
        # Each tile is 32 bytes (8x8 pixels, 4bpp)
        for row in range(height_tiles):
            for col in range(width_tiles):
                tile_name = f"tile_c{col}_r{row}"
                sb.append(Type.array(Type.int(1, False), 32), tile_name)

        struct_type = Type.structure_type(sb)
        type_id = Type.generate_auto_type_id('genesis_sprites', name)
        self.view.define_type(type_id, name, struct_type)
        return self.view.get_type_by_name(name)

    def _create_palette_struct(self):
        """Create or retrieve a struct type for a 16-color CRAM palette."""
        name = "GenesisPalette"

        existing = self.view.get_type_by_name(name)
        if existing:
            return existing

        sb = StructureBuilder.create()
        for i in range(16):
            sb.append(Type.int(2, False), f"color_{i}")

        struct_type = Type.structure_type(sb)
        type_id = Type.generate_auto_type_id('genesis_sprites', name)
        self.view.define_type(type_id, name, struct_type)
        return self.view.get_type_by_name(name)

    def _label_at(self, addr, name, data_type=None):
        """Define a symbol and optionally a data variable at an address."""
        if addr == 0 or addr >= self.view.end:
            return
        # Clean name for Binary Ninja (no spaces, special chars)
        clean = name.replace(' ', '_').replace('-', '_').replace('/', '_')
        clean = ''.join(c for c in clean if c.isalnum() or c == '_')

        if data_type:
            self.view.define_user_data_var(addr, data_type)
        self.view.define_auto_symbol(
            Symbol(SymbolType.DataSymbol, addr, clean))

    def _load_normalized(self, data):
        """Load normalized format (palette pool + pattern pool + collections)."""
        palettes = data.get('palettes', {})
        patterns = data.get('patterns', {})
        collections = data.get('sprite_collections', {})

        pal_type = self._create_palette_struct()
        labeled_pats = 0
        labeled_pals = 0

        # Label palettes
        for pal_id, pal_data in palettes.items():
            rom_offset = pal_data.get('rom_offset', 0)
            if isinstance(rom_offset, str):
                rom_offset = int(rom_offset, 0) if rom_offset else 0
            if rom_offset and rom_offset < 0xFF0000:
                name = pal_data.get('name', pal_id)
                self._label_at(rom_offset, f"pal_{name}", pal_type)
                labeled_pals += 1

        # Label patterns
        for pat_id, pat_data in patterns.items():
            rom_offset = pat_data.get('rom_offset', 0)
            if isinstance(rom_offset, str):
                rom_offset = int(rom_offset, 0) if rom_offset else 0
            if not rom_offset or rom_offset >= 0xFF0000:
                continue

            w = pat_data.get('width_tiles', 1)
            h = pat_data.get('height_tiles', 1)
            frame_count = pat_data.get('frame_count', 1)
            name = pat_data.get('name', pat_id)
            tile_type = self._create_tile_struct(w, h)

            if not tile_type:
                continue

            bytes_per_frame = w * h * 32
            for frame in range(frame_count):
                addr = rom_offset + frame * bytes_per_frame
                if frame_count > 1:
                    frame_name = f"spr_{name}_f{frame}"
                else:
                    frame_name = f"spr_{name}"
                self._label_at(addr, frame_name, tile_type)
                labeled_pats += 1

        log_info(f"Labeled {labeled_pals} palettes, {labeled_pats} sprite patterns")

    def _load_legacy(self, data):
        """Load legacy format (sprite_groups array)."""
        groups = data.get('sprite_groups', [])
        pal_type = self._create_palette_struct()
        labeled_pats = 0
        labeled_pals = 0

        for group in groups:
            group_name = group.get('name', 'unnamed')

            # Label palettes
            for pal in group.get('palettes', []):
                rom_str = pal.get('rom_offset', '')
                if not rom_str:
                    continue
                rom_offset = int(rom_str, 0) if rom_str else 0
                if rom_offset and rom_offset < 0xFF0000:
                    pal_name = pal.get('name', 'palette')
                    self._label_at(rom_offset,
                                   f"pal_{group_name}_{pal_name}", pal_type)
                    labeled_pals += 1

            # Label sprites
            for sprite in group.get('sprites', []):
                rom_str = sprite.get('rom_offset', '')
                if not rom_str:
                    continue
                rom_offset = int(rom_str, 0) if rom_str else 0
                if not rom_offset or rom_offset >= 0xFF0000:
                    continue

                w = sprite.get('width_tiles', 1)
                h = sprite.get('height_tiles', 1)
                frame_count = sprite.get('frame_count', 1)
                name = sprite.get('name', 'sprite')
                tile_type = self._create_tile_struct(w, h)

                if not tile_type:
                    continue

                bytes_per_frame = w * h * 32
                for frame in range(frame_count):
                    addr = rom_offset + frame * bytes_per_frame
                    if frame_count > 1:
                        frame_name = f"spr_{group_name}_{name}_f{frame}"
                    else:
                        frame_name = f"spr_{group_name}_{name}"
                    self._label_at(addr, frame_name, tile_type)
                    labeled_pats += 1

        log_info(f"Labeled {labeled_pals} palettes, {labeled_pats} sprite patterns")
