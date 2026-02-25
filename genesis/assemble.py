"""Assembles M68K instructions and writes the opcode to the specified address
"""

from binaryninja import (BackgroundTaskThread, AddressField,
                         MultilineTextField, get_form_input, show_message_box,
                         log)
import tempfile
import shutil
import os
import subprocess


# Additional directories to search when the toolchain is not on PATH
_TOOLCHAIN_SEARCH_PATHS = [
    '/usr/bin',
    '/usr/local/bin',
    '/opt/homebrew/bin',
    '/opt/local/bin',
]


def _find_tool(name):
    """Locate a toolchain binary via PATH then common install locations."""
    path = shutil.which(name)
    if path:
        return path
    for directory in _TOOLCHAIN_SEARCH_PATHS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class GenesisAssemble(BackgroundTaskThread):
    def __init__(self, bv):
        BackgroundTaskThread.__init__(self, "", True)
        self.bv = bv
        self.as_path = None
        self.ld_path = None
        self.progress = 'genesis: Assembling code...'

    def _find_toolchain(self):
        """Locate assembler and linker; show a helpful error if either is missing."""
        self.as_path = _find_tool('m68k-linux-gnu-as')
        self.ld_path = _find_tool('m68k-linux-gnu-ld')

        missing = []
        if not self.as_path:
            missing.append('m68k-linux-gnu-as')
        if not self.ld_path:
            missing.append('m68k-linux-gnu-ld')

        if missing:
            show_message_box(
                'genesis',
                'M68K toolchain not found: {}\n\n'
                'Install with:\n  sudo apt install gcc-m68k-linux-gnu'.format(
                    ', '.join(missing))
            )
            return False
        return True

    def _get_params(self):
        params = {}
        start_offset_field = AddressField(
            'Start offset for patch (current offset: 0x{:08x})'.format(
                self.bv.offset),
            view=self.bv, current_address=self.bv.offset)
        code_field = MultilineTextField('Code')
        get_form_input([start_offset_field, code_field], 'Patch Parameters')
        params['start_offset'] = start_offset_field.result
        params['code'] = code_field.result
        return params

    def _run_tool(self, args):
        """Run a subprocess; log stdout and return (success, stderr_text)."""
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if out:
            log.log_debug('genesis: {}'.format(out.decode('utf-8', errors='replace')))
        return p.returncode == 0, err.decode('utf-8', errors='replace')

    def _assemble_code(self, dirpath):
        ok, err = self._run_tool([
            self.as_path, '-m68000', '-c',
            '-a={}/patch.lst'.format(dirpath),
            '{}/patch.S'.format(dirpath),
            '-o', '{}/patch.o'.format(dirpath)
        ])
        if not ok or not os.path.exists(os.path.join(dirpath, 'patch.o')):
            raise OSError('Assembler error:\n{}'.format(err))

    def _link_code(self, dirpath):
        ok, err = self._run_tool([
            self.ld_path, '-Ttext', '0', '--oformat', 'binary',
            '-o', '{}/patch.bin'.format(dirpath),
            '{}/patch.o'.format(dirpath)
        ])
        if not ok or not os.path.exists(os.path.join(dirpath, 'patch.bin')):
            raise OSError('Linker error:\n{}'.format(err))

    def _assemble_link_extract(self, code):
        template = (
            '.section .text\n'
            '.globl _start\n\n'
            '_start:\n'
            '{}\n'.format(code)
        )
        dirpath = tempfile.mkdtemp()
        try:
            with open(os.path.join(dirpath, 'patch.S'), 'w') as f:
                f.write(template)
            self._assemble_code(dirpath)
            self._link_code(dirpath)
            with open(os.path.join(dirpath, 'patch.bin'), 'rb') as f:
                return f.read()
        except Exception as err:
            show_message_box('genesis', 'Assembly failed: {}'.format(err))
            return None
        finally:
            shutil.rmtree(dirpath, ignore_errors=True)

    def run(self):
        if not self._find_toolchain():
            return

        params = self._get_params()
        if not params.get('code'):
            return

        blob = self._assemble_link_extract(params['code'])
        if blob is None:
            return

        if len(blob) > 0:
            self.bv.write(params['start_offset'], blob)
            show_message_box(
                'genesis',
                'Wrote {} bytes beginning at {:08x}'.format(
                    len(blob), params['start_offset'])
            )
        else:
            show_message_box('genesis', 'Patch is 0 bytes in size')


if __name__ == '__main__':
    print('! this plugin does not run headless')
