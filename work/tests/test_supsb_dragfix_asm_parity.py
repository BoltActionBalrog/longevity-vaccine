"""Differential: thunk_supsb_dragfix must implement the exact skip contract.

The vanilla drag-loss fix (group supported_sb_dragfix): the @0x40CC1A
re-attach call is redirected here.  [BaseWin+0x40B20]==1 (bar already
engaged) -> skip: mimic ScrollBar_attach_rect's RET 0x10 (pop the 4 args,
eax=0 status, ecx/edi untouched).  Else -> tail-jmp ScrollBar_attach_rect
with args + site return address intact.

Bytes come from patches.yaml resolved with the real symbol table (yaml/spec
desync fails here; on-disk drift fails test_apply_md5).
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
    UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402

BASEWIN = 0x6A7628
ATTACH = 0x605840
SITE_RET = 0x0045CC1F  # arbitrary sentinel in a mapped page
STACK = 0x00200000


def _load_thunk():
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == "thunk_supsb_dragfix":
                base = cave["virtual_addr"]
                base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]
                off = int(off, 16) if isinstance(off, str) else off
                va = base + off
                return va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab)
    raise AssertionError("thunk_supsb_dragfix content entry not found")


THUNK_VA, THUNK_CODE = _load_thunk()


def _run(engaged):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(THUNK_VA & ~0xFFF, 0x2000)
    uc.mem_map(0x6A7000, 0x45000)          # BaseWin fields
    uc.mem_map(ATTACH & ~0xFFF, 0x1000)
    uc.mem_map(SITE_RET & ~0xFFF, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(THUNK_VA, THUNK_CODE)
    uc.mem_write(ATTACH, b"\xF4")          # hlt sentinels
    uc.mem_write(SITE_RET, b"\xF4")
    uc.mem_write(BASEWIN + 0x40B20, struct.pack("<I", engaged))
    esp = STACK + 0x8000
    # [esp]=site ret, then the 4 attach args
    uc.mem_write(esp, struct.pack("<5I", SITE_RET, 0x1234, 0x7AE820, 2, 0))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, BASEWIN)
    uc.reg_write(UC_X86_REG_ECX, 0x6EABC8)
    uc.reg_write(UC_X86_REG_EAX, 0xDEAD)
    try:
        uc.emu_start(THUNK_VA, 0, count=20)
    except unicorn.UcError:
        pass
    return uc, esp


def test_engaged_skips_with_callee_contract():
    uc, esp = _run(1)
    assert uc.reg_read(UC_X86_REG_EIP) in (SITE_RET, SITE_RET + 1)  # at the site ret (hlt sentinel advances EIP)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 0x14        # ret 0x10 popped args too
    assert uc.reg_read(UC_X86_REG_EAX) == 0                 # benign status
    assert uc.reg_read(UC_X86_REG_ECX) == 0x6EABC8          # this untouched


def test_not_engaged_tail_jumps_to_attach():
    uc, esp = _run(0)
    assert uc.reg_read(UC_X86_REG_EIP) in (ATTACH, ATTACH + 1)  # tail-jmp, no call
    assert uc.reg_read(UC_X86_REG_ESP) == esp               # stack untouched
    assert uc.reg_read(UC_X86_REG_ECX) == 0x6EABC8


def test_other_values_also_attach():
    uc, esp = _run(2)                                       # only ==1 skips
    assert uc.reg_read(UC_X86_REG_EIP) in (ATTACH, ATTACH + 1)
