# bn-genesis

## Description

Suite of Binary Ninja plugins that assist with SEGA Genesis ROM hacking
* Load SEGA Genesis/Megadrive ROM's
    * Use .bin format roms. These are essentially raw memory dumps, data matches what you see in Genesis debugger
    * The other popular Genesis ROM format is SMD (Super Mega Drive). These have the data interleaved (probably
      some artifact of hardware limitations of the device that dumped the ROMs).  But this format sucks for
      reverse engineering or ROM hacking, so convert them to .bin
* Write m68k assembly and quickly apply a patch at a specified offset
* Fixup ROM checksums
* Enumerate call tables (deprecated)
    * Vector35 addressed issues with its core and now tables are recognized by auto-analysis 

![demo bn-genesis](screencap.gif)

* Provides simple readable comments about VDP registers writes

![vdp comment example](vdp_analysis.png)

## Features

### Python Plugin (core)
* **ROM Loader** — parses Genesis ROM header, maps memory segments (ROM, RAM, Z80, VDP, I/O)
* **`genesis: load game definition`** — imports a sprite editor JSON file, creates `SpriteTiles_WxH` struct types and `GenesisPalette` structs, labels all sprite patterns and palettes at their ROM addresses
* **`genesis: comment VDP inst`** — annotates VDP register writes with readable comments
* **`genesis: assemble and patch`** — compile M68K assembly and apply as a ROM patch
* **`genesis: fixup ROM checksum`** — recalculate and write the ROM checksum

### C++ Sprite Viewer Sidebar (`cpp_ui/`)
* Native Qt6 sidebar widget that renders Genesis 4bpp tile data as visual sprites
* Live preview at cursor address with configurable W x H tile grid
* Column-major tile ordering matching Genesis hardware sprites
* Palette loading from game definition JSON or directly from ROM
* Adjustable zoom (1-16x)

## Installation

### Python Plugin (required)

```bash
# Symlink the plugin into Binary Ninja's plugin directory
ln -s /path/to/bn-genesis ~/.binaryninja/plugins/genesis

# Install dependencies
sudo apt install gcc-m68k-linux-gnu
```

The loader also requires the third-party [binaryninja-m68k](https://github.com/wrigjl/binaryninja-m68k) processor module.

### C++ Sprite Viewer (optional)

The native sprite viewer sidebar requires building from source.

```bash
# 1. Clone the Binary Ninja API and initialize submodules
git clone https://github.com/Vector35/binaryninja-api.git bn-api
cd bn-api && git submodule update --init vendor/fmt && cd ..

# 2. Build the plugin
cd bn-genesis/cpp_ui
mkdir -p build && cd build
cmake .. \
    -DBN_API_PATH=/path/to/bn-api \
    -DBN_INSTALL_DIR=/path/to/binaryninja
make

# 3. Install
cp libgenesis_sprite_viewer.so ~/.binaryninja/plugins/
```

**Build requirements:**
* Qt6 development libraries (`qt6-base-dev`)
* CMake 3.13+
* Binary Ninja API headers (cloned above)
* Binary Ninja installation (for `libbinaryninjacore.so` and `libbinaryninjaui.so`)

## Usage

### Loading a ROM

If you have the dependencies installed, just load a Genesis ROM (.bin format). If successfully loaded, you'll see "Sega Genesis / Megadrive ROM" in the view type dropdown, with proper memory segments for ROM, RAM, Z80, VDP, and I/O.

### Labeling Sprites from a Game Definition

1. Open a Genesis ROM in Binary Ninja
2. Run **Plugins > genesis: load game definition**
3. Select your game definition JSON file (same format as the sprite editor)
4. All sprite patterns and palettes are labeled at their ROM addresses with proper struct types

### Using the Sprite Viewer Sidebar

After installing the C++ sidebar widget, a "Sprite Viewer" icon appears in the sidebar. Click it to open the viewer, then navigate to any ROM address containing tile data to see it rendered visually.

### Importing BlastEm Code Traces

BlastEm can record branch/jump targets during emulation. Import them to improve
Binary Ninja's analysis of indirect jumps and computed branches:

1. In BlastEm debugger: `codetrace output.json` → play game → `codetracestop`
2. In Binary Ninja: **Plugins > genesis: import code trace** → select the JSON
3. JSR/BSR targets become functions, JMP targets become functions, Bcc targets get labels
4. Binary Ninja re-analyzes with the new function entry points

This is especially valuable for jump tables and code reached through register-indirect jumps.

# Genesis Hacking

## Emulators / Debuggers

* [BlastEm](https://www.retrodev.com/blastem/): Genesis emulator with built in
  debugger. Page says it has GDB remote debugging support, I haven't tried that
  yet, but I have used the built in debugger.  Also has VDP introspection UI and
  debuggers.
* [Gens KMod](https://segaretro.org/Gens_KMod): Modified version of Gens
  emulator that supports some has some advance VDP and CPU introspection UIs.

## Useful sites / tutorials

* [Nameless Algorithm Blog](https://namelessalgorithm.com/genesis/): Has some
  really well written explanations of how to write code for the Genesis, and
  great explanations on how the VDP works
* [Chibi Akumas](https://www.chibiakumas.com/): Has a large site with assembly
  tutorials for many retro consoles and computers.  From generic non-system
  specific info about different CPUs, to platform specific tutorials.  Also
  has Youtube videos / explanations to go along with each of the lessons.
* [Genesis / MegaDrive Technical Overview](https://segaretro.org/images/1/18/GenesisTechnicalOverview.pdf):
  Very technical details about how the Genesis works.  Not easy to digest,
  but very thorough and complete.
* [MegaDrive Wiki](https://md.railgun.works/index.php?title=Main_Page): Lots
  of info here, nice concise [VDP Reference](https://md.railgun.works/index.php?title=VDP).

  ## Future Features / Todo List

  - [ ] When all 2/3 VDP DMA registers get set at once, provide a single clickable address
  - [ ] Other VDP accesses other than simple register writes