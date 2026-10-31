"""Unicorn parity + law sweep for group basewin_pipbar (assemble_pipbar.py): the base screen's intake bars are
laid out at ONE device pitch per bar (scaling_laws.pipbar_pip)."""
from __future__ import annotations

import contextlib
import io

import pytest

import test_council_asm_parity as TC
from test_council_asm_parity import RET_SITE, SL, SP0

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_pipbar as PB

LAY = PB.assemble_all()
VA = {n: PB.PCAVE2 + off for n, (off, _b) in LAY.items()}
FRAME = TC.HEAP + 0x1000
RECT = TC.HEAP + 0x2000


def emu(g, canvas_w):
    e = TC.Emu(g)
    for page in (PB.PCAVE2 + 0x1C000, 0x6A7000, 0x5D5000, 0x5DA000):
        try:
            e.uc.mem_map(page, 0x1000)
        except Exception:  # noqa: BLE001  (already mapped by the council harness)
            pass
    for _n, (off, b) in LAY.items():
        e.uc.mem_write(PB.PCAVE2 + off, b)
    for a in (PB.FILL_2, PB.TILE_2, PB.T_SB_TILE2):
        e.uc.mem_write(a, b"\xf4")
        e.landings.add(a)
    e.w32(PB.CANVAS_W, canvas_w)
    return e


CASES = [(437, 2), (437, 3), (512, 6), (300, 20), (437, 1)]


@pytest.mark.parametrize("g", [22, 25, 34, 40])
@pytest.mark.parametrize("x0,pitch", CASES)
def test_pipbar_tile(g, x0, pitch):
    width = max(1, pitch - 1)
    for k in (0, 1, 7, PB.SPAN // max(pitch, 1)):
        for off_grid in (0, 1):
            x = x0 + k * pitch + off_grid
            e = emu(g, (758 * g) >> 4)
            e.w32(FRAME - 0x20, x0)
            land = e.run(VA["thunk_bw_piptile"],
                         regs={"ecx": PB.CANVAS, "ebp": FRAME, "esi": pitch, "ebx": 0x61, "edi": 0x62},
                         stack=[RET_SITE, 0x7000, x, 90, x, 90, width, 11])
            assert land == PB.T_SB_TILE2 and e.reg("esp") == SP0 and e.r32(SP0) == RET_SITE
            assert (e.reg("ecx"), e.reg("ebp"), e.reg("esi"), e.reg("ebx"), e.reg("edi")) == (PB.CANVAS, FRAME, pitch, 0x61, 0x62)
            xs, ws = SL.pipbar_pip(x0, pitch, x, width, g)
            y, h = (90 * g) >> 4, ((101 * g) >> 4) - ((90 * g) >> 4)
            got = [e.r32(SP0 + 4 * i) for i in range(1, 8)]
            assert got == [0x7000, xs, y, xs, y, ws, h], (g, pitch, k, off_grid)


@pytest.mark.parametrize("g", [22, 25, 40])
@pytest.mark.parametrize("x0,pitch", CASES)
def test_pipbar_fill(g, x0, pitch):
    width = max(1, pitch - 1)
    for k in (0, 3, 40):
        x = x0 + k * pitch
        e = emu(g, (758 * g) >> 4)
        e.w32(FRAME - 0x20, x0)
        rect = (x, 90, x + width, 101)
        for i, v in enumerate(rect):
            e.w32(RECT + 4 * i, v)
        land = e.run(VA["thunk_bw_pipfill"],
                     regs={"ecx": PB.BASEWIN_G, "ebp": FRAME, "esi": pitch, "ebx": 0x61, "edi": 0x62},
                     stack=[RET_SITE, RECT, 0xF0])
        assert land == PB.FILL_2 and e.reg("esp") == SP0 and e.r32(SP0 + 4) == PB.G_BW_RECT
        assert (e.reg("ecx"), e.reg("ebp"), e.reg("esi"), e.reg("ebx"), e.reg("edi")) == (PB.BASEWIN_G, FRAME, pitch, 0x61, 0x62)
        xs, ws = SL.pipbar_pip(x0, pitch, x, width, g)
        assert tuple(e.r32(PB.G_BW_RECT + 4 * i) for i in range(4)) == (xs, (90 * g) >> 4, xs + ws, (101 * g) >> 4)
        assert [e.r32(RECT + 4 * i) for i in range(4)] == list(rect)          # the painter's local is never mutated


@pytest.mark.parametrize("which", ["tile", "fill"])
def test_pipbar_native_passthrough(which):
    e = emu(16, 758)
    e.w32(FRAME - 0x20, 437)
    e.w32(PB.G_BW_RECT, 0x7777)
    if which == "tile":
        stack = [RET_SITE, 0x7000, 441, 90, 441, 90, 1, 11]
        land = e.run(VA["thunk_bw_piptile"], regs={"ecx": PB.CANVAS, "ebp": FRAME, "esi": 2}, stack=stack)
        assert land == PB.T_SB_TILE2 and [e.r32(SP0 + 4 * i) for i in range(8)] == stack
    else:
        for i, v in enumerate((441, 90, 442, 101)):
            e.w32(RECT + 4 * i, v)
        land = e.run(VA["thunk_bw_pipfill"], regs={"ecx": PB.BASEWIN_G, "ebp": FRAME, "esi": 2}, stack=[RET_SITE, RECT, 0xF0])
        assert land == PB.FILL_2 and e.r32(SP0 + 4) == RECT
    assert e.r32(PB.G_BW_RECT) == 0x7777


@pytest.mark.parametrize("g", list(range(16, 65)))
def test_scaling_pipbar_law(g):
    for pitch in (2, 3, 4, 6, 9, 20):
        for x0 in (300, 437, 511):
            n = PB.SPAN // pitch + 1
            width = max(1, pitch - 1)
            pips = [SL.pipbar_pip(x0, pitch, x0 + k * pitch, width, g) for k in range(n)]
            if g == 16:
                assert pips == [(x0 + k * pitch, width) for k in range(n)]           # vanilla's own arithmetic
                continue
            assert len({w for _x, w in pips}) == 1                                   # every pip the same width
            assert len({pips[k + 1][0] - pips[k][0] for k in range(n - 1)}) == 1     # one pitch
            P = pips[1][0] - pips[0][0]
            assert 1 <= pips[0][1] < P or P == 1
            assert pips[0][0] == (x0 * g) >> 4                                       # the bar starts where the text ends
            assert pips[-1][0] + P <= ((x0 + n * pitch) * g) >> 4                    # never past the bar's native span
        # off the bar's grid -> the plain edge law
        assert SL.pipbar_pip(437, pitch, 436, 1, g) == ((436 * g) >> 4, ((437 * g) >> 4) - ((436 * g) >> 4))


@pytest.mark.parametrize("g", [22, 25, 40])
@pytest.mark.parametrize("delta", [-3, -2, -1, 0, 1, 2, 3, 9])
def test_pipbar_three_bars_share_one_start(g, delta):
    """x0 is a measured text end: two rows can differ by a device pixel or two.  A bar within pipbar_snap of the
    last bar's start reuses it (user 2026-09-21: MINERALS sat 2 px right of NUTRIENTS / ENERGY)."""
    x0, pitch = 505, 4
    top = (x0 * g) >> 4
    e = emu(g, (758 * g) >> 4)
    e.w32(FRAME - 0x20, x0)
    e.w32(PB.G_PIP_TOP, top + delta)
    x = x0 + 3 * pitch
    land = e.run(VA["thunk_bw_piptile"], regs={"ecx": PB.CANVAS, "ebp": FRAME, "esi": pitch},
                 stack=[RET_SITE, 0x7000, x, 90, x, 90, pitch - 1, 11])
    assert land == PB.T_SB_TILE2
    xs, ws = SL.pipbar_pip(x0, pitch, x, pitch - 1, g, prev_top=top + delta)
    assert (e.r32(SP0 + 0x10), e.r32(SP0 + 0x18)) == (xs, ws)
    want_top = top + delta if abs(delta) <= SL.pipbar_snap(g) else top
    assert e.r32(PB.G_PIP_TOP) == want_top and xs == want_top + 3 * (xs - want_top) // 3
