"""Differential: thunk_sb_dragfree (scrollbar thumb-drag capture freedom).

Site 0x605E18 replaced ScrollBar_on_mouse_move's `je 0x6061d1` (the
point-in-rect bail) with `E8 thunk + 90`.  CALL preserves EFLAGS, so the
thunk sees the hit test's ZF (ZF=1 = point OUTSIDE the bar rect):

  * inside  (ZF=0)               -> RET to 0x605E1E (vanilla proceed);
  * outside + thumb ([esi+0xA44]==0) -> RET to 0x605E1E (the plus-up);
  * outside + page zone (!=0)    -> consume ret addr, jump 0x6061D1 (vanilla
                                    bail; esp exactly as the je would leave it).

Bytes come from patches.yaml resolved with the real symbol table.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import yaml  # noqa: E402

SB = 0x006EABC8            # a real ScrollBar instance VA (supported list bar)
RESUME = 0x00605E1E        # instruction after the replaced je
BAIL = 0x006061D1          # the function epilogue the je targeted
STACK = 0x00200000
ZF = 1 << 6


def _load_thunk():
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == "thunk_sb_dragfree":
                base = cave["virtual_addr"]
                base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]
                off = int(off, 16) if isinstance(off, str) else off
                va = base + off
                return va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab)
    raise AssertionError("thunk_sb_dragfree content entry not found")


THUNK_VA, THUNK_CODE = _load_thunk()


def _run(zf, zone):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(THUNK_VA & ~0xFFF, 0x2000)
    uc.mem_map(0x605000, 0x2000)           # RESUME + BAIL sentinels
    uc.mem_map(SB & ~0xFFF, 0x2000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(THUNK_VA, THUNK_CODE)
    uc.mem_write(RESUME, b"\xF4")
    uc.mem_write(BAIL, b"\xF4")
    uc.mem_write(SB + 0xA44, struct.pack("<i", zone))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I", RESUME))   # E8's pushed return address
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, SB)
    flags = uc.reg_read(UC_X86_REG_EFLAGS)
    uc.reg_write(UC_X86_REG_EFLAGS, (flags | ZF) if zf else (flags & ~ZF))
    try:
        uc.emu_start(THUNK_VA, 0, count=10)
    except unicorn.UcError:
        pass
    return uc, esp


def test_inside_rect_proceeds():
    uc, esp = _run(zf=0, zone=5)           # inside: zone must not matter
    assert uc.reg_read(UC_X86_REG_EIP) in (RESUME, RESUME + 1)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4


def test_outside_thumb_drag_proceeds():
    uc, esp = _run(zf=1, zone=0)           # the plus-up
    assert uc.reg_read(UC_X86_REG_EIP) in (RESUME, RESUME + 1)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4
    assert uc.reg_read(UC_X86_REG_ESI) == SB


@pytest.mark.parametrize("zone", [-1, 1])
def test_outside_page_zone_bails_vanilla(zone):
    uc, esp = _run(zf=1, zone=zone)
    assert uc.reg_read(UC_X86_REG_EIP) in (BAIL, BAIL + 1)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4   # ret addr consumed = je-equivalent stack
