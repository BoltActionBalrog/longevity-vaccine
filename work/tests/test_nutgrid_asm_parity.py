"""Unicorn parity + law sweep for group basewin_nutgrid (assemble_nutgrid.py): the NUTRIENTS storage grid with
sub-8-px rows is laid out at ONE device pitch (scaling_laws.nutgrid_layout)."""
from __future__ import annotations

import contextlib
import io

import pytest

import test_council_asm_parity as TC
from test_council_asm_parity import RET_SITE, SL, SP0

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_nutgrid as NG

LAY = NG.assemble_all()
VA = {n: NG.PCAVE2 + off for n, (off, _b) in LAY.items()}
FRAME = TC.HEAP + 0x1000          # the painter's ebp
RECT = TC.HEAP + 0x2000


def emu(g, canvas_w):
    e = TC.Emu(g)
    for page in (NG.PCAVE2 + 0x1C000, 0x6A7000, 0x5D5000, 0x5E3000):
        try:
            e.uc.mem_map(page, 0x1000)
        except Exception:  # noqa: BLE001  (already mapped by the council harness)
            pass
    for _n, (off, b) in LAY.items():
        e.uc.mem_write(NG.PCAVE2 + off, b)
    for a in (NG.FILL_2, NG.BOX_2, NG.BOX2RING):
        e.uc.mem_write(a, b"\xf4")
        e.landings.add(a)
    e.w32(NG.CANVAS_W, canvas_w)
    return e


def seed(e, top, bot, rows, pitch, row, L=40, R=52):
    for off, v in ((0x28, pitch), (0x2C, rows), (0x44, row), (0x50, top), (0x48, bot)):
        e.w32(FRAME - off, v)
    y0 = top + ((bot - top) - pitch * rows) // 2 + (1 if pitch >= 8 else 0)
    T = y0 + row * pitch
    rect = (L, T, R, T + pitch - 1 - (1 if pitch >= 8 else 0))
    for i, v in enumerate(rect):
        e.w32(RECT + 4 * i, v)
    return rect


CASES = [(100, 185, 40, 2), (100, 199, 40, 2), (100, 190, 28, 3), (100, 190, 14, 6), (100, 190, 12, 7), (100, 190, 9, 10)]


@pytest.mark.parametrize("g", [22, 25, 34, 40])
@pytest.mark.parametrize("top,bot,rows,pitch", CASES)
@pytest.mark.parametrize("site", ["fill", "ring"])
def test_nutgrid_rect(g, top, bot, rows, pitch, site):
    for row in (0, 1, rows // 2, rows - 1):
        e = emu(g, (758 * g) >> 4)
        rect = seed(e, top, bot, rows, pitch, row)
        this = NG.BASEWIN_G if site == "fill" else NG.CANVAS
        land = e.run(VA["thunk_bw_nutfill" if site == "fill" else "thunk_bw_nutring"],
                     regs={"ecx": this, "ebp": FRAME, "ebx": 0x61, "esi": 0x62, "edi": 0x63},
                     stack=[RET_SITE, RECT, 0x95, 0x95])
        assert land == (NG.FILL_2 if site == "fill" else NG.BOX2RING)
        assert e.reg("esp") == SP0 and e.r32(SP0) == RET_SITE and e.r32(SP0 + 4) == NG.G_BW_RECT
        assert (e.reg("ecx"), e.reg("ebp"), e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (this, FRAME, 0x61, 0x62, 0x63)
        got = tuple(e.r32(NG.G_BW_RECT + 4 * i) for i in range(4))
        if SL.nutgrid_applies(pitch, g):
            T, B = SL.nutgrid_row_rect(top, bot, rows, pitch, row, g)
        else:
            T, B = (rect[1] * g) >> 4, (rect[3] * g) >> 4
        assert got == ((rect[0] * g) >> 4, T, (rect[2] * g) >> 4, B), (g, pitch, row)
        assert [e.r32(RECT + 4 * i) for i in range(4)] == list(rect)          # the painter's local is never mutated


@pytest.mark.parametrize("site", ["fill", "ring"])
def test_nutgrid_native_passthrough(site):
    e = emu(16, 758)
    seed(e, 100, 185, 40, 2, 3)
    e.w32(NG.G_BW_RECT, 0x7777)
    this = NG.BASEWIN_G if site == "fill" else NG.CANVAS
    land = e.run(VA["thunk_bw_nutfill" if site == "fill" else "thunk_bw_nutring"],
                 regs={"ecx": this, "ebp": FRAME}, stack=[RET_SITE, RECT, 0x95, 0x95])
    assert land == (NG.FILL_2 if site == "fill" else NG.BOX_2)
    assert e.r32(SP0 + 4) == RECT and e.r32(NG.G_BW_RECT) == 0x7777           # untouched: bit-identical native draw


@pytest.mark.parametrize("g", list(range(16, 65)))
def test_scaling_nutgrid_law(g):
    for pitch in range(2, 8):
        for rows in (1, 5, 12, 40, 64):
            for slack in (0, 1, rows - 1):
                top, bot = 100, 100 + pitch * rows + slack
                y0, P, cell = SL.nutgrid_layout(top, bot, rows, pitch, g)
                if g == 16:
                    assert (y0, P, cell) == (top + slack // 2, pitch, pitch - 1)     # vanilla's own arithmetic
                    continue
                t, b = (top * g) >> 4, (bot * g) >> 4
                assert t <= y0 and y0 + rows * P <= b                                  # never outside the box
                assert 1 <= cell < P or P == 1
                assert P <= SL.half_down(pitch * g, 16)                                # never taller than vanilla x g/16 (rounded)
                rects = [SL.nutgrid_row_rect(top, bot, rows, pitch, r, g) for r in range(rows)]
                assert len({B - T for T, B in rects}) == 1                             # every cell the same height
                assert len({rects[i + 1][0] - rects[i][0] for i in range(rows - 1)}) <= 1   # one pitch
                lead, trail = y0 - t, b - (y0 + rows * P)
                assert abs(lead - trail) <= 1                                          # centred
