"""Differential: thunk_hud_arrowseeds must agree with scaling_laws bit-exactly.

The 182B MainWin_build block @0x45A816 derives the unit-row scroll-arrow
button window rects (buttons[8..10], seeds +0xAAC/+0xABC/+0xACC) from
already-device-scaled anchors (+0xCEC..+0xCF8, +0xDB0) composed with NATIVE
sprite dims (+0x22E40/44) and native +/-4 pads.  The cut thunk substitutes
s(w)/s(h)/s(4) per scaling_laws.hud_unit_arrow_rects; g=16 must be
bit-identical to vanilla.  Exit contract (the vanilla trailing store
`mov [edx+0xC],edi` @0x45A8D3 stays live): edx=&MainWin+0xACC, edi=bottom,
ebx=ycen, [ebp-0x20]=[anchor+8], [ebp-0x28]=[anchor].

Bytes are taken from patches.yaml (the shipped template, resolved with the
real symbol table) — a yaml/spec desync fails here, byte drift on disk fails
test_apply_md5.

Skips (does not fail) if unicorn is absent.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

MAINWIN = 0x7AE820
ANCHOR = MAINWIN + 0xCEC
STACK = 0x00200000
RET_SENTINEL = 0x0045A81B          # site+5, any executable sentinel works


def _load_thunk():
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == "thunk_hud_arrowseeds":
                base = int(cave["virtual_addr"], 16) if isinstance(cave["virtual_addr"], str) \
                    else cave["virtual_addr"]
                va = base + int(c["offset"], 16) if isinstance(c["offset"], str) \
                    else base + c["offset"]
                tmpl = ap.ByteTemplate(c["bytes"])
                return va, tmpl.resolve(va, symtab), symtab["g_popup_scale_num"]
    raise AssertionError("thunk_hud_arrowseeds content entry not found")


THUNK_VA, THUNK_CODE, G_VA = _load_thunk()


def _run(g, anchor, x9, sprw, sprh, flags_in=0x246):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(THUNK_VA & ~0xFFF, 0x2000)
    uc.mem_map(G_VA & ~0xFFF, 0x1000)
    uc.mem_map(0x7AE000, 0x24000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(RET_SENTINEL & ~0xFFF, 0x1000)
    uc.mem_write(THUNK_VA, THUNK_CODE)
    uc.mem_write(RET_SENTINEL, b"\xF4")  # hlt = stop
    uc.mem_write(G_VA, struct.pack("<I", g))
    uc.mem_write(ANCHOR, struct.pack("<4i", *anchor))
    uc.mem_write(MAINWIN + 0xDB0, struct.pack("<i", x9))
    uc.mem_write(MAINWIN + 0x22E40, struct.pack("<2i", sprw, sprh))
    esp, ebp = STACK + 0x8000, STACK + 0x7000
    uc.mem_write(esp, struct.pack("<I", RET_SENTINEL))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_ESI, MAINWIN)
    uc.reg_write(UC_X86_REG_EDI, ANCHOR)
    uc.reg_write(UC_X86_REG_EAX, ANCHOR)
    uc.reg_write(UC_X86_REG_EFLAGS, flags_in)
    try:
        uc.emu_start(THUNK_VA, RET_SENTINEL, count=300)
    except unicorn.UcError:
        assert uc.reg_read(unicorn.x86_const.UC_X86_REG_EIP) == RET_SENTINEL
    rd = lambda a: struct.unpack("<i", bytes(uc.mem_read(a, 4)))[0]  # noqa: E731
    sgn = lambda v: struct.unpack("<i", struct.pack("<I", v))[0]  # noqa: E731
    edi = sgn(uc.reg_read(UC_X86_REG_EDI))
    out = {
        "btn8": tuple(rd(MAINWIN + 0xAAC + 4 * i) for i in range(4)),
        "btn9": tuple(rd(MAINWIN + 0xABC + 4 * i) for i in range(4)),
        # +0xAD8 is written by the vanilla trailing store [edx+0xC]=edi
        "btn10": tuple(rd(MAINWIN + 0xACC + 4 * i) for i in range(3)) + (edi,),
        "edx": uc.reg_read(UC_X86_REG_EDX),
        "ebx": sgn(uc.reg_read(UC_X86_REG_EBX)),
        "esp": uc.reg_read(UC_X86_REG_ESP),
        "slot20": rd(ebp - 0x20),
        "slot28": rd(ebp - 0x28),
        "eflags": uc.reg_read(UC_X86_REG_EFLAGS),
        "esp0": esp,
    }
    return out


CASES = [
    ((779, 56, 1020, 252), 900, 12, 42),      # native-1024-ish anchors
    ((100, 200, 900, 260), 300, 12, 42),
    ((1948, 140, 2550, 630), 2250, 12, 42),   # 4K-scaled anchors
    ((10, 5, 50, 40), 20, 7, 9),              # odd dims
]


@pytest.mark.parametrize("g", [16, 17, 20, 22, 25, 33, 40])
@pytest.mark.parametrize("case", CASES)
def test_rects_match_the_law(g, case):
    anchor, x9, sprw, sprh = case
    want = SL.hud_unit_arrow_rects(anchor, x9, sprw, sprh, g)
    got = _run(g, anchor, x9, sprw, sprh)
    assert got["btn8"] == want["btn8"]
    assert got["btn9"] == want["btn9"]
    assert got["btn10"] == want["btn10"]


@pytest.mark.parametrize("g", [16, 25, 40])
def test_exit_contract(g):
    anchor, x9, sprw, sprh = CASES[0]
    want = SL.hud_unit_arrow_rects(anchor, x9, sprw, sprh, g)
    got = _run(g, anchor, x9, sprw, sprh)
    assert got["edx"] == MAINWIN + 0xACC          # trailing store target
    assert got["ebx"] == want["btn9"][1]          # vanilla left ebx = y9
    assert got["slot20"] == anchor[2]             # [ebp-0x20] = [anchor+8]
    assert got["slot28"] == anchor[0]             # [ebp-0x28] = [anchor]
    assert got["esp"] == got["esp0"] + 4          # bare-RET stack balance


@pytest.mark.parametrize("flags", [0x202, 0x8D7])
def test_eflags_transparent(flags):
    anchor, x9, sprw, sprh = CASES[0]
    got = _run(40, anchor, x9, sprw, sprh, flags_in=flags)
    assert got["eflags"] & 0x8D5 == flags & 0x8D5


def test_g16_identity_is_vanilla_math():
    """At g=16 the law (and thus the thunk) must equal vanilla's own formula."""
    for anchor, x9, sprw, sprh in CASES:
        cec, cf0, cf4, cf8 = anchor
        span = (cf8 - sprh) - cf0
        ycen = cf0 + (span // 2 if span >= 0 else -((-span) // 2))
        want = {
            "btn8": (cec + 4, ycen, cec + 4 + sprw, ycen + sprh),
            "btn9": (x9, ycen, x9 + sprw, ycen + sprh),
            "btn10": (cf4 - sprw - 4, ycen, cf4 - 4, ycen + sprh),
        }
        assert SL.hud_unit_arrow_rects(anchor, x9, sprw, sprh, 16) == want
