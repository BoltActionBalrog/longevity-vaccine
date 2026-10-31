"""keystone 0.9.2 hex-misread guard -- import it next to `from keystone import ...` in every assembler.

keystone 0.9.2 sometimes opens an X86 engine that reads every unprefixed number as HEX for that engine's whole
life: `mov eax, 10` assembles to b8 10 00 00 00 (measured: 1 in ~255 engines opened in a pytest-xdist worker,
never seen serially; the bad bytes reached assemble_dw's import-time self-check as `cmp eax, 0x6979652`). It is
the engine, not the text -- a new engine assembles the same text correctly -- so importing this module patches
keystone.Ks.__init__ once per process: every X86 engine is checked when it opens and, if it misreads a decimal
or a hex immediate, reopened. The bad engine is left open, so the allocator cannot hand back the same memory.
Every `Ks(...)` in the process, whatever name it was imported under, then returns a correct assembler.

tests/conftest.py imports this module too (one implementation); tests/test_ks_guard.py fails when a script
under work/scripts imports keystone without importing ks_guard.
"""
from __future__ import annotations

import sys

import keystone

#: Engines opened in a row before giving up; one bad engine in ~255 makes two in a row already ~1 in 65,000.
MAX_OPENS = 16


def reads_numbers_right(ks) -> bool:
    """True when `ks` reads `10` as ten and `0x10` as sixteen (the imm32 is the last 4 bytes in every X86 mode)."""
    return (bytes(ks.asm("mov eax, 10")[0])[-4:] == b"\x0a\x00\x00\x00"
            and bytes(ks.asm("mov eax, 0x10")[0])[-4:] == b"\x10\x00\x00\x00")


def checked_init(init):
    """Wrap a Ks.__init__ so an X86 engine that misreads immediates is replaced by a fresh one."""
    def __init__(self, arch, mode):
        for n in range(MAX_OPENS):
            init(self, arch, mode)                     # a reopen overwrites the handle: the bad engine stays open
            if arch != keystone.KS_ARCH_X86 or reads_numbers_right(self):
                return
            print(f"ks_guard: keystone engine #{n + 1} misreads immediates (10 -> hex); reopening",
                  file=sys.stderr)
        raise RuntimeError(f"keystone: {MAX_OPENS} engines in a row misread immediates")
    __init__.ks_guard = True
    return __init__


if not getattr(keystone.Ks.__init__, "ks_guard", False):
    keystone.Ks.__init__ = checked_init(keystone.Ks.__init__)
