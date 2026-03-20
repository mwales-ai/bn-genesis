"""
Sprite Viewer sidebar widget for Binary Ninja.

Renders Genesis/Megadrive 4bpp tile data from ROM as images, allowing
visual inspection of sprite graphics directly in the disassembly view.

Genesis tile format:
  - Each tile is 8x8 pixels, 4 bits per pixel, 32 bytes per tile
  - Pixels are stored MSB-first within each byte (2 pixels per byte)
  - Sprite tiles use column-major order: tile(col, row) = col * H + row

CRAM palette format:
  - 16 colors per palette line, 2 bytes per color (32 bytes total)
  - Bit layout: ---- bbb- ggg- rrr-
  - Each channel is 3 bits (0-7), mapped to 0-252 for display
"""

import json
import os

from binaryninja import (
    BinaryView,
    interaction,
    log_info, log_warn, log_error
)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QComboBox, QPushButton, QGroupBox,
    QScrollArea, QSizePolicy, QGridLayout
)
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt, QRect

import binaryninjaui
from binaryninjaui import (
    SidebarWidget, SidebarWidgetType,
    UIActionHandler, ViewFrame
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TILE_WIDTH_PX = 8
TILE_HEIGHT_PX = 8
BYTES_PER_TILE = 32       # 8 rows * 4 bytes per row (8 pixels * 4bpp / 8)
DEFAULT_ZOOM = 4
MAX_ZOOM = 16
MIN_ZOOM = 1
DEFAULT_GRID_W = 2        # tiles wide
DEFAULT_GRID_H = 4        # tiles tall

# Default grayscale palette (used when no palette is loaded)
_GRAYSCALE_PALETTE = [
    QColor(0, 0, 0),           # 0: black (transparent)
    QColor(17, 17, 17),
    QColor(34, 34, 34),
    QColor(51, 51, 51),
    QColor(68, 68, 68),
    QColor(85, 85, 85),
    QColor(102, 102, 102),
    QColor(119, 119, 119),
    QColor(136, 136, 136),
    QColor(153, 153, 153),
    QColor(170, 170, 170),
    QColor(187, 187, 187),
    QColor(204, 204, 204),
    QColor(221, 221, 221),
    QColor(238, 238, 238),
    QColor(252, 252, 252),     # 15: near-white
]


# ---------------------------------------------------------------------------
# CRAM color decoding
# ---------------------------------------------------------------------------

def decode_cram_color(cram_word):
    """
    Decode a 16-bit Genesis CRAM color word to a QColor.

    CRAM format: ---- bbb- ggg- rrr-
    Each channel is 3 bits (values 0-7), scaled to 0-252.
    """
    r_raw = (cram_word >> 1) & 0x07
    g_raw = (cram_word >> 5) & 0x07
    b_raw = (cram_word >> 9) & 0x07

    # Scale 0-7 to 0-252 (multiply by 36)
    r = r_raw * 36
    g = g_raw * 36
    b = b_raw * 36

    return QColor(r, g, b)


def decode_cram_palette(palette_bytes):
    """
    Decode 32 bytes of CRAM palette data into a list of 16 QColors.

    Palette data is big-endian (M68K byte order).
    """
    if len(palette_bytes) < 32:
        log_warn(f"Palette data too short: {len(palette_bytes)} bytes (need 32)")
        return list(_GRAYSCALE_PALETTE)

    colors = []
    for i in range(16):
        hi = palette_bytes[i * 2]
        lo = palette_bytes[i * 2 + 1]
        cram_word = (hi << 8) | lo
        colors.append(decode_cram_color(cram_word))

    return colors


# ---------------------------------------------------------------------------
# Tile decoding
# ---------------------------------------------------------------------------

def decode_tile_to_image(tile_bytes, palette):
    """
    Decode a single 8x8 Genesis tile (32 bytes, 4bpp) into a QImage.

    Each byte contains two pixels (MSB = left pixel, LSB = right pixel).
    Each row is 4 bytes (8 pixels).

    Returns a QImage in ARGB32 format with dimensions 8x8.
    """
    img = QImage(TILE_WIDTH_PX, TILE_HEIGHT_PX, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    if len(tile_bytes) < BYTES_PER_TILE:
        return img

    for row in range(TILE_HEIGHT_PX):
        row_offset = row * 4
        for col_pair in range(4):
            byte_val = tile_bytes[row_offset + col_pair]
            # High nybble = left pixel, low nybble = right pixel
            left_idx = (byte_val >> 4) & 0x0F
            right_idx = byte_val & 0x0F

            x = col_pair * 2

            # Index 0 is typically transparent, but we render it anyway
            # so the user can see the full tile content
            color_left = palette[left_idx] if left_idx < len(palette) else QColor(255, 0, 255)
            color_right = palette[right_idx] if right_idx < len(palette) else QColor(255, 0, 255)

            img.setPixelColor(x, row, color_left)
            img.setPixelColor(x + 1, row, color_right)

    return img


def render_sprite_grid(tile_data, width_tiles, height_tiles, palette, zoom):
    """
    Render a grid of tiles as a single QPixmap.

    Tiles are in column-major order: the tile at grid position (col, row) is
    at index col * height_tiles + row in the data. This matches the Genesis
    hardware sprite layout.

    Args:
        tile_data:     Raw bytes containing all tile data
        width_tiles:   Number of tile columns
        height_tiles:  Number of tile rows
        palette:       List of 16 QColors
        zoom:          Integer zoom factor

    Returns:
        QPixmap of the rendered sprite, or None if data is insufficient
    """
    total_tiles = width_tiles * height_tiles
    needed_bytes = total_tiles * BYTES_PER_TILE

    if len(tile_data) < needed_bytes:
        return None

    pixel_w = width_tiles * TILE_WIDTH_PX * zoom
    pixel_h = height_tiles * TILE_HEIGHT_PX * zoom

    result = QPixmap(pixel_w, pixel_h)
    result.fill(QColor(32, 32, 32))  # Dark background for transparency

    painter = QPainter(result)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

    for col in range(width_tiles):
        for row in range(height_tiles):
            # Column-major indexing
            tile_index = col * height_tiles + row
            tile_offset = tile_index * BYTES_PER_TILE
            tile_bytes = tile_data[tile_offset:tile_offset + BYTES_PER_TILE]

            tile_img = decode_tile_to_image(tile_bytes, palette)

            dest_x = col * TILE_WIDTH_PX * zoom
            dest_y = row * TILE_HEIGHT_PX * zoom
            dest_rect = QRect(dest_x, dest_y,
                              TILE_WIDTH_PX * zoom, TILE_HEIGHT_PX * zoom)

            painter.drawImage(dest_rect, tile_img)

    painter.end()
    return result


# ---------------------------------------------------------------------------
# Game definition palette loader
# ---------------------------------------------------------------------------

def load_palettes_from_json(json_path, bv):
    """
    Load palette data from a game definition JSON file.

    Supports both normalized format (palettes dict) and legacy format
    (sprite_groups with embedded palettes).

    Returns a dict of {display_name: [16 QColors]}.
    """
    palettes = {}

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        log_error(f"SpriteViewer: failed to load JSON: {e}")
        return palettes

    # Normalized format
    if 'palettes' in data and isinstance(data['palettes'], dict):
        for pal_id, pal_data in data['palettes'].items():
            rom_offset = pal_data.get('rom_offset', 0)
            if isinstance(rom_offset, str):
                rom_offset = int(rom_offset, 0) if rom_offset else 0

            name = pal_data.get('name', pal_id)

            # Try reading palette from the CRAM values in JSON first
            # Field is 'cram_values' in our format, but check 'colors' too
            cram_values = pal_data.get('cram_values', pal_data.get('colors', []))
            if len(cram_values) >= 16:
                colors = []
                for cv in cram_values[:16]:
                    if isinstance(cv, str):
                        cv = int(cv, 0)
                    colors.append(decode_cram_color(cv))
                palettes[name] = colors
            elif rom_offset and rom_offset < 0xFF0000 and bv is not None:
                # Fall back to reading from ROM
                raw = bv.read(rom_offset, 32)
                if raw and len(raw) == 32:
                    palettes[name] = decode_cram_palette(raw)

    # Legacy format
    elif 'sprite_groups' in data:
        for group in data.get('sprite_groups', []):
            group_name = group.get('name', 'unnamed')
            for pal in group.get('palettes', []):
                rom_str = pal.get('rom_offset', '')
                if not rom_str:
                    continue
                rom_offset = int(rom_str, 0) if rom_str else 0
                pal_name = pal.get('name', 'palette')
                display_name = f"{group_name}/{pal_name}"

                if rom_offset and rom_offset < 0xFF0000 and bv is not None:
                    raw = bv.read(rom_offset, 32)
                    if raw and len(raw) == 32:
                        palettes[display_name] = decode_cram_palette(raw)

    log_info(f"SpriteViewer: loaded {len(palettes)} palettes from {os.path.basename(json_path)}")
    return palettes


# ---------------------------------------------------------------------------
# Palette swatch widget
# ---------------------------------------------------------------------------

class PaletteSwatchWidget(QWidget):
    """Small widget that draws the 16 colors of the active palette."""

    SWATCH_SIZE = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette = list(_GRAYSCALE_PALETTE)
        self.setFixedHeight(self.SWATCH_SIZE + 4)
        self.setMinimumWidth(self.SWATCH_SIZE * 16 + 2)

    def set_palette(self, palette):
        self._palette = palette
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        s = self.SWATCH_SIZE
        for i, color in enumerate(self._palette[:16]):
            painter.fillRect(i * s + 1, 2, s - 1, s, color)
        # Draw a thin border around the whole swatch row
        painter.setPen(QColor(100, 100, 100))
        painter.drawRect(0, 1, 16 * s + 1, s + 1)
        painter.end()


# ---------------------------------------------------------------------------
# Sprite render display widget
# ---------------------------------------------------------------------------

class SpriteDisplayWidget(QLabel):
    """QLabel subclass that displays the rendered sprite pixmap, centered."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(64, 64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #202020; border: 1px solid #444;")
        self.setText("No tile data")


# ---------------------------------------------------------------------------
# Main sidebar widget
# ---------------------------------------------------------------------------

class SpriteViewerWidget(SidebarWidget):
    """
    Binary Ninja sidebar widget that renders Genesis sprite tiles from ROM.

    Features:
      - Reads tile data at the current cursor address
      - Renders 4bpp tiles using a selectable palette
      - Configurable grid dimensions (W x H tiles)
      - Adjustable zoom level
      - Loads palettes from game definition JSON files
      - Updates when the cursor moves in the hex/disassembly view
    """

    def __init__(self, name, frame, data):
        SidebarWidget.__init__(self, name)

        self._view = None           # Current BinaryView
        self._frame = frame         # Current ViewFrame
        self._current_offset = 0    # Address to read tile data from
        self._zoom = DEFAULT_ZOOM
        self._grid_w = DEFAULT_GRID_W
        self._grid_h = DEFAULT_GRID_H
        self._column_major = True   # Genesis sprite tile ordering

        # Palette storage
        self._active_palette = list(_GRAYSCALE_PALETTE)
        self._loaded_palettes = {}  # name -> [16 QColors]
        self._json_path = None

        self._build_ui()

        # Connect to the BinaryView if we already have one
        if data is not None:
            self.notifyViewChanged(data)

    # -------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------

    def _build_ui(self):
        """Build the sidebar widget layout."""
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Address display --
        addr_layout = QHBoxLayout()
        addr_layout.addWidget(QLabel("Address:"))
        self._addr_label = QLabel("0x00000000")
        self._addr_label.setStyleSheet("font-family: monospace; font-weight: bold;")
        addr_layout.addWidget(self._addr_label)
        addr_layout.addStretch()
        layout.addLayout(addr_layout)

        # -- Grid dimensions --
        grid_group = QGroupBox("Sprite Grid")
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(4, 4, 4, 4)

        grid_layout.addWidget(QLabel("Width (tiles):"), 0, 0)
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 32)
        self._width_spin.setValue(self._grid_w)
        self._width_spin.valueChanged.connect(self._on_grid_changed)
        grid_layout.addWidget(self._width_spin, 0, 1)

        grid_layout.addWidget(QLabel("Height (tiles):"), 1, 0)
        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 32)
        self._height_spin.setValue(self._grid_h)
        self._height_spin.valueChanged.connect(self._on_grid_changed)
        grid_layout.addWidget(self._height_spin, 1, 1)

        grid_layout.addWidget(QLabel("Zoom:"), 2, 0)
        self._zoom_spin = QSpinBox()
        self._zoom_spin.setRange(MIN_ZOOM, MAX_ZOOM)
        self._zoom_spin.setValue(self._zoom)
        self._zoom_spin.valueChanged.connect(self._on_zoom_changed)
        grid_layout.addWidget(self._zoom_spin, 2, 1)

        grid_group.setLayout(grid_layout)
        layout.addWidget(grid_group)

        # -- Tile order toggle --
        order_layout = QHBoxLayout()
        order_layout.addWidget(QLabel("Tile order:"))
        self._order_combo = QComboBox()
        self._order_combo.addItems(["Column-major (sprites)", "Row-major (screen)"])
        self._order_combo.currentIndexChanged.connect(self._on_order_changed)
        order_layout.addWidget(self._order_combo)
        layout.addLayout(order_layout)

        # -- Palette controls --
        pal_group = QGroupBox("Palette")
        pal_layout = QVBoxLayout()
        pal_layout.setContentsMargins(4, 4, 4, 4)

        # Palette selector
        sel_layout = QHBoxLayout()
        self._pal_combo = QComboBox()
        self._pal_combo.addItem("Grayscale (default)")
        self._pal_combo.currentIndexChanged.connect(self._on_palette_selected)
        sel_layout.addWidget(self._pal_combo)

        self._load_json_btn = QPushButton("Load JSON...")
        self._load_json_btn.clicked.connect(self._on_load_json)
        sel_layout.addWidget(self._load_json_btn)
        pal_layout.addLayout(sel_layout)

        # Read palette from ROM at address
        rom_pal_layout = QHBoxLayout()
        self._read_pal_btn = QPushButton("Read palette at cursor")
        self._read_pal_btn.clicked.connect(self._on_read_palette_at_cursor)
        rom_pal_layout.addWidget(self._read_pal_btn)
        pal_layout.addLayout(rom_pal_layout)

        # Palette swatch preview
        self._swatch = PaletteSwatchWidget()
        pal_layout.addWidget(self._swatch)

        pal_group.setLayout(pal_layout)
        layout.addWidget(pal_group)

        # -- Sprite display area (scrollable) --
        self._sprite_display = SpriteDisplayWidget()
        scroll = QScrollArea()
        scroll.setWidget(self._sprite_display)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(128)
        layout.addWidget(scroll, stretch=1)

        # -- Data size info --
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._info_label)

        self.setLayout(layout)

    # -------------------------------------------------------------------
    # Binary Ninja sidebar interface
    # -------------------------------------------------------------------

    def notifyViewChanged(self, view):
        """Called by Binary Ninja when the active BinaryView changes."""
        if view is not None:
            self._view = view
            log_info("SpriteViewer: view changed, attached to BinaryView")
        self._refresh_display()

    def notifyOffsetChanged(self, offset):
        """Called by Binary Ninja when the cursor address changes."""
        if offset != self._current_offset:
            self._current_offset = offset
            self._addr_label.setText(f"0x{offset:08X}")
            self._refresh_display()

    # -------------------------------------------------------------------
    # Event handlers
    # -------------------------------------------------------------------

    def _on_grid_changed(self, _value):
        self._grid_w = self._width_spin.value()
        self._grid_h = self._height_spin.value()
        self._refresh_display()

    def _on_zoom_changed(self, value):
        self._zoom = value
        self._refresh_display()

    def _on_order_changed(self, index):
        self._column_major = (index == 0)
        self._refresh_display()

    def _on_palette_selected(self, index):
        if index == 0:
            # Grayscale default
            self._active_palette = list(_GRAYSCALE_PALETTE)
        else:
            # Look up loaded palette by name
            pal_name = self._pal_combo.itemText(index)
            if pal_name in self._loaded_palettes:
                self._active_palette = self._loaded_palettes[pal_name]

        self._swatch.set_palette(self._active_palette)
        self._refresh_display()

    def _on_load_json(self):
        """Prompt user to select a game definition JSON and load palettes."""
        path = interaction.get_open_filename_input(
            "Open Game Definition JSON", "JSON Files (*.json)")
        if not path:
            return

        # Binary Ninja may return bytes on some platforms
        if isinstance(path, bytes):
            path = path.decode('utf-8')

        self._json_path = path
        self._loaded_palettes = load_palettes_from_json(path, self._view)

        # Update the combo box
        self._pal_combo.blockSignals(True)
        self._pal_combo.clear()
        self._pal_combo.addItem("Grayscale (default)")
        for name in sorted(self._loaded_palettes.keys()):
            self._pal_combo.addItem(name)
        self._pal_combo.blockSignals(False)

        # Select the first loaded palette if any were found
        if self._loaded_palettes:
            self._pal_combo.setCurrentIndex(1)
        else:
            self._on_palette_selected(0)

    def _on_read_palette_at_cursor(self):
        """Read 32 bytes at the current cursor as CRAM palette data."""
        if self._view is None:
            return

        raw = self._view.read(self._current_offset, 32)
        if raw is None or len(raw) < 32:
            log_warn("SpriteViewer: not enough data at cursor for palette (need 32 bytes)")
            return

        pal_name = f"ROM@0x{self._current_offset:06X}"
        colors = decode_cram_palette(raw)
        self._loaded_palettes[pal_name] = colors

        # Add to combo and select it
        self._pal_combo.blockSignals(True)
        self._pal_combo.addItem(pal_name)
        self._pal_combo.blockSignals(False)
        self._pal_combo.setCurrentIndex(self._pal_combo.count() - 1)

    # -------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------

    def _refresh_display(self):
        """Re-read tile data from ROM and update the sprite display."""
        if self._view is None:
            self._sprite_display.setPixmap(QPixmap())
            self._sprite_display.setText("No BinaryView attached")
            self._info_label.setText("")
            return

        total_tiles = self._grid_w * self._grid_h
        needed_bytes = total_tiles * BYTES_PER_TILE

        raw = self._view.read(self._current_offset, needed_bytes)
        if raw is None or len(raw) < needed_bytes:
            avail = len(raw) if raw else 0
            self._sprite_display.setPixmap(QPixmap())
            self._sprite_display.setText(
                f"Not enough data\n"
                f"Need {needed_bytes} bytes, got {avail}\n"
                f"at 0x{self._current_offset:08X}")
            self._info_label.setText("")
            return

        # If row-major order is selected, rearrange data to column-major
        # so render_sprite_grid always works in column-major
        if not self._column_major:
            tile_data = self._rearrange_row_to_col_major(
                raw, self._grid_w, self._grid_h)
        else:
            tile_data = raw

        pixmap = render_sprite_grid(
            tile_data, self._grid_w, self._grid_h,
            self._active_palette, self._zoom)

        if pixmap is not None:
            self._sprite_display.setText("")
            self._sprite_display.setPixmap(pixmap)
        else:
            self._sprite_display.setPixmap(QPixmap())
            self._sprite_display.setText("Render failed")

        # Update info label
        pixel_w = self._grid_w * TILE_WIDTH_PX
        pixel_h = self._grid_h * TILE_HEIGHT_PX
        self._info_label.setText(
            f"{self._grid_w}x{self._grid_h} tiles = "
            f"{pixel_w}x{pixel_h} px | "
            f"{needed_bytes} bytes (0x{needed_bytes:X})")

    def _rearrange_row_to_col_major(self, data, w, h):
        """
        Convert row-major tile data to column-major ordering.

        Row-major:    tile(col, row) = row * W + col
        Column-major: tile(col, row) = col * H + row
        """
        result = bytearray(len(data))
        for col in range(w):
            for row in range(h):
                src_idx = (row * w + col) * BYTES_PER_TILE
                dst_idx = (col * h + row) * BYTES_PER_TILE
                result[dst_idx:dst_idx + BYTES_PER_TILE] = \
                    data[src_idx:src_idx + BYTES_PER_TILE]
        return bytes(result)


# ---------------------------------------------------------------------------
# Sidebar widget type registration
# ---------------------------------------------------------------------------

class SpriteViewerSidebarWidgetType(SidebarWidgetType):
    """
    Registers the Sprite Viewer as a Binary Ninja sidebar widget.

    Usage in __init__.py:
        from .genesis.sprite_viewer import SpriteViewerSidebarWidgetType
        SpriteViewerSidebarWidgetType()
    """

    def __init__(self):
        # Icon is a simple 8x8 grid icon encoded as a QImage
        icon = QImage(16, 16, QImage.Format_ARGB32)
        icon.fill(Qt.transparent)

        # Draw a small grid pattern to represent tiles
        painter = QPainter(icon)
        painter.setPen(QColor(200, 200, 200))

        # Draw a 2x2 grid of squares to suggest tile layout
        for gx in range(2):
            for gy in range(2):
                x = 1 + gx * 7
                y = 1 + gy * 7
                # Alternate fill to look like a checkerboard sprite
                if (gx + gy) % 2 == 0:
                    painter.fillRect(x, y, 6, 6, QColor(180, 180, 220))
                else:
                    painter.fillRect(x, y, 6, 6, QColor(100, 100, 160))
                painter.drawRect(x, y, 6, 6)

        painter.end()

        SidebarWidgetType.__init__(self, icon, "Sprite Viewer")

    def createWidget(self, frame, data):
        return SpriteViewerWidget("Sprite Viewer", frame, data)
