"""Differential: thunk_drawmap_fullguard must implement the post-calc redraw guard.

Group map_recentre_fullredraw: the `cmp [esi+0x21A44],edi` @0x46A5AE in
MapWin_draw_map (right after the MapWin_calculate_dimensions call) is
detoured here.  The thunk clears drawOnlyCursor (+0x21A44) when the pixel
offset (+0x1DDAC/+0x1DDB0) is nonzero or the visible span covers the map on
either axis (OddX+EvenX >= mapW, OddY+EvenY >= mapH), replays the cmp and
resumes at the je @0x46A5B4 -- ZF set = full redraw, clear = scroll-blit.

The site detour itself (push imm32; ret) is run too, so a yaml/site desync or
a wrong thunk VA fails here.  Bytes come from patches.yaml resolved with the
real symbol table; the assembler script must reproduce them exactly.
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
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402

MAPWIN = 0x9156B0
SITE = 0x46A5AE
RESUME = 0x46A5B4
MAP_W, MAP_H = 0x949870, 0x949874
STACK = 0x00200000
F_FLAG, F_PXL, F_PXT = 0x21A44, 0x1DDAC, 0x1DDB0
F_ODDX, F_ODDY, F_EVENX, F_EVENY = 0x1DDCC, 0x1DDD0, 0x1DDD4, 0x1DDD8


def _int(v):
    return int(v, 16) if isinstance(v, str) else v


def _load():
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    thunk = None
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == "thunk_drawmap_fullguard":
                va = _int(cave["virtual_addr"]) + _int(c["offset"])
                thunk = (va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab))
    assert thunk, "thunk_drawmap_fullguard content entry not found"
    site = next(s for s in doc["sites"] if s["id"] == "MapWin_draw_map.postcalc_guard")
    assert _int(site["virtual_addr"]) == SITE
    return thunk[0], thunk[1], ap.ByteTemplate(site["new_bytes"]).resolve(SITE, symtab)


THUNK_VA, THUNK_CODE, SITE_CODE = _load()


def _run(flag=1, pxl=0, pxt=0, oddx=20, evenx=21, oddy=30, eveny=31, mapw=80, maph=160):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(THUNK_VA & ~0xFFF, 0x2000)
    uc.mem_map(SITE & ~0xFFF, 0x1000)
    uc.mem_map(MAPWIN & ~0xFFF, 0x26000)   # Console fields through +0x21A44
    uc.mem_map(MAP_W & ~0xFFF, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(THUNK_VA, THUNK_CODE)
    uc.mem_write(SITE, SITE_CODE)
    uc.mem_write(RESUME, b"\xF4")          # hlt sentinel
    for off, v in ((F_FLAG, flag), (F_PXL, pxl), (F_PXT, pxt), (F_ODDX, oddx),
                   (F_EVENX, evenx), (F_ODDY, oddy), (F_EVENY, eveny)):
        uc.mem_write(MAPWIN + off, struct.pack("<i", v))
    uc.mem_write(MAP_W, struct.pack("<2i", mapw, maph))
    esp = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, MAPWIN)
    uc.reg_write(UC_X86_REG_EDI, 0)
    uc.reg_write(UC_X86_REG_EBX, 0xB0B0B0B0)
    uc.reg_write(UC_X86_REG_ECX, 0xC1C1C1C1)
    uc.reg_write(UC_X86_REG_EDX, 0xD2D2D2D2)
    uc.reg_write(UC_X86_REG_EAX, 0xDEAD)
    try:
        uc.emu_start(SITE, 0, count=40)
    except unicorn.UcError:
        pass
    assert uc.reg_read(UC_X86_REG_EIP) in (RESUME, RESUME + 1)
    assert uc.reg_read(UC_X86_REG_ESP) == esp
    assert uc.reg_read(UC_X86_REG_ESI) == MAPWIN
    assert uc.reg_read(UC_X86_REG_EDI) == 0
    assert uc.reg_read(UC_X86_REG_EBX) == 0xB0B0B0B0
    assert uc.reg_read(UC_X86_REG_ECX) == 0xC1C1C1C1
    assert uc.reg_read(UC_X86_REG_EDX) == 0xD2D2D2D2
    out = struct.unpack("<i", uc.mem_read(MAPWIN + F_FLAG, 4))[0]
    zf = bool(uc.reg_read(UC_X86_REG_EFLAGS) & 0x40)
    assert zf == (out == 0)                # the replayed cmp describes the stored flag
    return out


def test_assembler_matches_yaml():
    import assemble_mapguard as am
    assert am.VA == THUNK_VA
    assert am.assemble() == THUNK_CODE


def test_normal_zoom_keeps_scroll_blit():
    assert _run() == 1


def test_flag_already_clear_stays_clear():
    assert _run(flag=0) == 0


@pytest.mark.parametrize("pxl,pxt", [(5, 0), (0, -7), (-3, 12)])
def test_pixel_offset_forces_full_redraw(pxl, pxt):
    assert _run(pxl=pxl, pxt=pxt) == 0


@pytest.mark.parametrize("oddx,evenx,expect", [(39, 40, 1), (40, 40, 0), (40, 41, 0)])
def test_view_spans_map_width(oddx, evenx, expect):
    assert _run(oddx=oddx, evenx=evenx, mapw=80) == expect


@pytest.mark.parametrize("oddy,eveny,expect", [(79, 80, 1), (80, 80, 0), (80, 81, 0)])
def test_view_spans_map_height(oddy, eveny, expect):
    assert _run(oddy=oddy, eveny=eveny, maph=160) == expect
