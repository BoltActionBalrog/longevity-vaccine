"""Unicorn parity for thunk_hud_boxframe v2 (assemble_hud_widgets.py; Buffer_box_sprite 0x5E2DD3
entry detour) against scaling_laws.hud_boxframe_rect.

The REAL bytes from patches.yaml run at the real cave VA. thunk_box_thick_hollow_flat is stubbed
with `ret 8`; the rect it receives (its [esp+4] -> g_hud_rect or the caller's own rect) is read
back after the run, along with FC_RECT and the g_fc_exact arm/disarm.

The regression this pins (frida_infowin_clear_20260918T213604/213713.log): the InfoWin typewriter
clears EITHER box-5 panel through the two shared painters (ret 0x45910D / 0x4564A7); the v1
site-only table cleared the LEFT panel for both, so the right panel never lost its old text.
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP,  # noqa: E402
                               UC_X86_REG_ESI, UC_X86_REG_ESP)

import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000
VA, TBL, RECT = PCAVE2 + 0x5740, PCAVE2 + 0x5600, PCAVE2 + 0x5720
HOLLOW_FLAT, FC_RECT, FC_EXACT = 0xA0C140, 0xA0D010, 0xA0E554
G = 0x668740
NATIVE_RESUME = 0x5E2DD8
HUD1, HUD2 = 0x7AEC64, 0x8C59AC
STACK = 0x2500000
SP0 = STACK + 0x8000
ENGINE_RECT = STACK + 0x9000
PARAMS = 0x78D7F8


def _entry(name: str, off: int) -> bytes:
    t = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r'- id: %s\r?\n\s*offset: 0x%04X\r?\n\s*bytes: "([^"]+)"' % (name, off), t)
    assert m, name
    return bytes(int(x, 16) for x in m.group(1).split())


CODE = _entry("thunk_hud_boxframe", 0x5740)
TABLE = _entry("g_hud_nat_table", 0x5600)
CODE_RUN = CODE                                                     # the bytes _run executes (a test may swap a mutant)


def _run(g: int, dest: int, site: int, rect):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(PCAVE2, 0x8000)
    uc.mem_map(G & ~0xFFF, 0x1000)
    uc.mem_map(NATIVE_RESUME & ~0xFFF, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(VA, CODE_RUN)
    uc.mem_write(TBL, TABLE)
    uc.mem_write(HOLLOW_FLAT, b"\xc2\x08\x00")                     # ret 8
    uc.mem_write(G, struct.pack("<I", g))
    uc.mem_write(NATIVE_RESUME, b"\xf4")
    uc.mem_write(ENGINE_RECT, struct.pack("<4i", *rect))
    # the 5-byte site is `call thunk`: [esp]=0x5E2DD8, then the caller's frame (ret, &rect, params)
    uc.mem_write(SP0, struct.pack("<4I", NATIVE_RESUME, site, ENGINE_RECT, PARAMS))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, dest)
    uc.reg_write(UC_X86_REG_ESI, 0x51515151)
    uc.reg_write(UC_X86_REG_EDI, 0xD1D1D1D1)
    seen = {}

    def on_code(u, addr, size, _):
        if addr == HOLLOW_FLAT:
            esp = u.reg_read(UC_X86_REG_ESP)
            prect, params = struct.unpack("<2I", bytes(u.mem_read(esp + 4, 8)))
            seen["rect"] = struct.unpack("<4i", bytes(u.mem_read(prect, 16)))
            seen["params"] = params
            seen["ecx"] = u.reg_read(UC_X86_REG_ECX)
            seen["exact"] = struct.unpack("<I", bytes(u.mem_read(FC_EXACT, 4)))[0]
            seen["fc"] = struct.unpack("<4i", bytes(u.mem_read(FC_RECT, 16)))

    from unicorn import UC_HOOK_CODE
    uc.hook_add(UC_HOOK_CODE, on_code, begin=HOLLOW_FLAT, end=HOLLOW_FLAT)
    try:
        uc.emu_start(VA, 0, count=400)
    except Exception:
        pass                                                        # stops on the hlt
    return uc, seen


def test_fits_its_slot_and_table_matches_the_law():
    assert len(CODE) <= 0xE0                                        # thunk_hud_cellring starts at 0x5820
    assert 0x45BF3E not in SL.HUD_BOXFRAME_NAT and SL.HUD_BOXFRAME_MIRROR_SITES == {0x45BF66}
    assert len(TABLE) == 20 * len(SL.HUD_BOXFRAME_NAT) <= 0x5720 - 0x5600
    rows = [struct.unpack("<I4i", TABLE[i:i + 20]) for i in range(0, len(TABLE), 20)]
    assert rows == [SL.hud_boxframe_table_row(site) for site in SL.HUD_BOXFRAME_NAT]   # F32: mirror rows negated
    assert {r[0]: tuple(abs(v) for v in r[1:]) for r in rows} == SL.HUD_BOXFRAME_NAT
    assert {r[0] for r in rows if r[1] < 0} == SL.HUD_BOXFRAME_MIRROR_SITES == {r[0] for r in rows if r[3] < 0}
    lefts = [r[0] for r in SL.HUD_BOXFRAME_NAT.values()]
    assert min(abs(v - SL.HUD_BOX5_SPLIT_NATIVE) for v in lefts) >= 100   # split margin


def _drifted(nat, g, d):
    return tuple(v * g // 16 + d for v in nat)


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("dest", [HUD1, HUD2])
def test_scaling_every_site_matches_the_law(g, dest):
    right = SL.HUD_BOXFRAME_NAT[SL.HUD_BOX5_RIGHT_PANEL_SITE]
    for site, nat in SL.HUD_BOXFRAME_NAT.items():
        for src in (nat, right) if site in (0x45910D, 0x4564A7) else (nat,):
            for d in (0, 1, 3):                                     # the engine's n*floor drift
                eng = _drifted(src, g, d)
                uc, seen = _run(g, dest, site, eng)
                want = SL.hud_boxframe_rect(site, eng, g)
                assert seen["rect"] == want == seen["fc"], (hex(site), g, d)
                assert seen["exact"] == 1 and seen["params"] == PARAMS and seen["ecx"] == dest
                assert struct.unpack("<I", bytes(uc.mem_read(FC_EXACT, 4)))[0] == 0
                assert uc.reg_read(UC_X86_REG_EIP) == site          # RET 8 back to the engine caller
                assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 16     # site ret + RET 8 consumed
                assert uc.reg_read(UC_X86_REG_ESI) == 0x51515151
                assert uc.reg_read(UC_X86_REG_EDI) == 0xD1D1D1D1


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_box9_frames_on_the_mirror_grid(g):
    """F32: the box-9 inner frame (the mission-year box, right console panel) draws its x edges on the mirror grid its
    seed uses -- ceil(x*g/16) = W' - fl((1024 - x)g/16) -- with the right edge EXCLUSIVE (ceil - 1: the renderer paints
    r inclusively, vanilla's r is one past the stroke) and its y edges on the floor; the unsigned split test never swaps
    it for the box-5 right panel even though its engine rect lies right of the split.  The outer frame 0x45BF3E is not
    a table site any more (t_box9_outer): it passes its engine rect through."""
    for site in sorted(SL.HUD_BOXFRAME_MIRROR_SITES):
        nat = SL.HUD_BOXFRAME_NAT[site]
        eng = _drifted(nat, g, 1)
        uc, seen = _run(g, HUD1, site, eng)
        if g <= 16:
            assert not seen
            continue
        want = (SL.hud_seed_x(nat[0], g, True), (nat[1] * g) >> 4, SL.hud_seed_x(nat[2], g, True) - 1, (nat[3] * g) >> 4)
        assert seen["rect"] == want == seen["fc"] == SL.hud_boxframe_rect(site, eng, g), (hex(site), g)
        assert want[0] == -((-nat[0] * g) >> 4) and want[2] == -((-nat[2] * g) >> 4) - 1
    if g > 16:
        eng = (1955, 527, 2542, 622)
        _uc, seen = _run(g, HUD1, 0x45BF3E, eng)
        assert seen["rect"] == eng == SL.hud_boxframe_rect(0x45BF3E, eng, g)


def test_scaling_mutant_jg_split_would_swap_box9():
    """The `ja` is load-bearing: with v2's signed `jg`, a negated box-9 l (<= 383) took the box-5 substitution."""
    i = CODE.index(bytes.fromhex("817E047F010000") + b"\x77")
    mutant = CODE[:i + 7] + b"\x7F" + CODE[i + 8:]
    global CODE_RUN
    site = 0x45BF66
    eng = _drifted(SL.HUD_BOXFRAME_NAT[site], 40, 0)
    good = _run(40, HUD1, site, eng)[1]["rect"]
    try:
        CODE_RUN = mutant
        bad = _run(40, HUD1, site, eng)[1]["rect"]
    finally:
        CODE_RUN = CODE
    assert good == SL.hud_boxframe_rect(site, eng, 40)
    assert bad == tuple((v * 40) >> 4 for v in SL.HUD_BOXFRAME_NAT[SL.HUD_BOX5_RIGHT_PANEL_SITE])


@pytest.mark.parametrize("g", [22, 25, 40])
def test_scaling_shared_painters_clear_the_panel_the_engine_asked_for(g):
    left = SL.HUD_BOXFRAME_NAT[0x45BD99]
    right = SL.HUD_BOXFRAME_NAT[0x45BDAA]
    for site in (0x45910D, 0x4564A7):
        _, a = _run(g, HUD1, site, _drifted(left, g, 1))
        _, b = _run(g, HUD1, site, _drifted(right, g, 1))
        assert a["rect"] == tuple(v * g // 16 for v in left)
        assert b["rect"] == tuple(v * g // 16 for v in right)


def test_scaling_unlisted_site_passes_the_engine_rect():
    eng = (1500, 182, 1813, 413)
    _, seen = _run(40, HUD1, 0x4588CF, eng)                         # InfoWin bare box: not in the table
    assert seen["rect"] == eng == SL.hud_boxframe_rect(0x4588CF, eng, 40)


@pytest.mark.parametrize("g,dest", [(16, HUD1), (12, HUD2), (40, 0x940824)])
def test_scaling_native_passthrough(g, dest):
    uc, seen = _run(g, dest, 0x45910D, (269, 73, 495, 165))
    assert not seen                                                 # hollow_flat never entered
    assert uc.reg_read(UC_X86_REG_EIP) in (NATIVE_RESUME, NATIVE_RESUME + 1)
    esp = uc.reg_read(UC_X86_REG_ESP)
    # displaced prologue replayed: push ecx/ebx/ebp/esi/edi below the caller's frame
    assert esp == SP0 + 4 - 20
    assert struct.unpack("<I", bytes(uc.mem_read(SP0, 4)))[0] == dest
