"""
Import BlastEm code trace files into Binary Ninja.

Reads a .json file produced by BlastEm's `codetrace` debugger command
and creates functions/labels at the recorded branch targets.
"""

import json
from binaryninja import (
    BackgroundTaskThread,
    Symbol, SymbolType,
    interaction,
    log_info, log_warn, log_error
)


class GenesisImportCodeTrace(BackgroundTaskThread):
    """Background task that imports a code trace JSON file."""

    def __init__(self, view):
        BackgroundTaskThread.__init__(self, "Importing code trace...", True)
        self.view = view

    def run(self):
        path = interaction.get_open_filename_input(
            "Import Code Trace JSON", "JSON Files (*.json)")
        if not path:
            return

        if isinstance(path, bytes):
            path = path.decode('utf-8')

        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            log_error(f"Failed to load code trace: {e}")
            return

        targets = data.get('code_targets', [])
        if not targets:
            log_warn("Code trace file contains no targets")
            return

        game_name = data.get('game_name', 'Unknown')
        log_info(f"Importing code trace for: {game_name} ({len(targets)} targets)")

        functions_added = 0
        labels_added = 0

        for entry in targets:
            target_str = entry.get('target', '0')
            target_type = entry.get('type', 'unknown')

            addr = int(target_str, 0) if isinstance(target_str, str) else target_str
            if addr == 0 or addr >= self.view.end:
                continue

            if target_type in ('jsr', 'bsr'):
                # Subroutine call targets — create functions
                if self.view.get_function_at(addr) is None:
                    self.view.add_function(addr)
                    functions_added += 1
            elif target_type == 'jmp':
                # Jump targets — might be functions or code blocks
                if self.view.get_function_at(addr) is None:
                    self.view.add_function(addr)
                    functions_added += 1
            elif target_type == 'bcc':
                # Conditional branch targets — label only
                existing = self.view.get_symbol_at(addr)
                if existing is None:
                    name = f"branch_{addr:06X}"
                    self.view.define_auto_symbol(
                        Symbol(SymbolType.DataSymbol, addr, name))
                    labels_added += 1

        self.view.update_analysis_and_wait()
        log_info(f"Code trace import complete: {functions_added} functions, "
                 f"{labels_added} branch labels added")
