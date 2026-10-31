"""The W3B rail scrollbar laws (scaling_laws.py: rail_col_map / rail_bar_inset / rail_line_spans / rail_grip_span /
mirror_nn_src / rail_arrow_col_map / rail_blit_rows / rail_layout v4), swept over g and canvas widths -- the source of
truth the t_rsb_* thunks port (tests/test_rail_sym_asm_parity.py) and the real image draws
(tests/test_scaling_rail_sym_e2e.py).  No emulation; < 2 s."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

WIDTHS = list(range(160, 3200, 13))


@pytest.mark.parametrize("g", list(range(17, 97)))
def test_scaling_rail_column_is_one_mirror_map(g):
    k = SL.stroke_width(g)
    for cw in WIDTHS:
        m = SL.rail_col_map(cw, g)
        wc, b = len(m), SL.rail_bar_inset(cw, g)
        assert wc == SL.rail_col_w(cw, g) == SL.rail_wall_off(cw, g)
        assert m == sorted(m) and m[0] == 0 and m[-1] == 31 and set(m) == set(range(32)), (g, cw)
        assert all(m[wc - 1 - j] == 31 - m[j] for j in range(wc) if 2 * j != wc - 1), (g, cw)
        # the bands: the cyan line = the chrome cell 3, K wide; cells 0..2 share b - K (axis_map_chrome's band layout
        # at the min-max band depth)
        cells = [sum(1 for j in range(b) if m[j] == c) for c in range(4)]
        assert cells == SL.distribute(b - k, 3) + [k] and b == SL.rail_layout_zones(wc, g)[0]
        (l0, l1), (r0, r1) = SL.rail_line_spans(cw, g)
        assert [j for j in range(wc) if m[j] == SL.RAIL_CYAN_L] == list(range(l0, l1)) and l1 - l0 == k
        assert [j for j in range(wc) if m[j] == SL.RAIL_CYAN_R] == list(range(r0, r1)) and r1 - r0 == k
        assert l0 == wc - r1 and l1 == b and r0 == wc - b
        # the plate cells 7..24 sit exactly on the grip span (so the caps' ornament lies under the arrow plates)
        off, w = SL.rail_grip_span(wc - 2 * b, SL.RAIL_GRIP_W, g)
        assert [j for j in range(wc) if 7 <= m[j] <= 24] == list(range(b + off, b + off + w)), (g, cw)
        # proportionate (rail_layout_zones): every laid zone within 1 px of vanilla x g/16 up to g 52; <= 1.5 px above
        # (the engine's visible column is 2g + 2..3 wide there, 8K and up)
        devs = SL.rail_layout_zone_devs(wc, b, g)
        assert max(devs) <= (16 if g <= 52 else 24), (g, cw, devs)


def test_scaling_rail_column_native_is_vanilla():
    for g in (8, 12, 16):
        for cw in WIDTHS:
            assert SL.rail_col_map(cw, g) == list(range(32))
            assert SL.rail_bar_inset(cw, g) == 4 and SL.rail_line_spans(cw, g) == ((3, 4), (28, 29))
            assert SL.rail_grip_span(24, 18, g) == (3, 18)
            lay = SL.rail_layout(cw, 490, g, y1=139)
            assert (lay["sb_x"], lay["sb_w"]) == (cw - 0x2B, 0x18)


@pytest.mark.parametrize("g", list(range(17, 97)))
def test_scaling_rail_grip_span_is_centred_and_vanilla_less_the_odd_px(g):
    for inner in range(g // 2, 4 * g):
        off, w = SL.rail_grip_span(inner, 18, g)
        fl = (18 * g) >> 4
        assert (inner - w) % 2 == 0 and off == (inner - w) // 2 and off + w + off == inner
        # the inner-parity value NEAREST 18g/16; an exact tie (18g/16 an integer of the wrong parity) rounds down
        same = [v for v in range(fl - 3, fl + 4) if (inner - v) % 2 == 0]
        best = min(abs(16 * v - 18 * g) for v in same)
        assert abs(16 * w - 18 * g) == best and (w == min(v for v in same if abs(16 * v - 18 * g) == best))


def test_scaling_mirror_nn_is_mirror_exact_and_centre_sampled_on_the_left():
    for src in range(1, 40):
        for dst in range(1, 120):
            v = [SL.mirror_nn_src(k, src, dst) for k in range(dst)]
            assert v == sorted(v) and 0 <= v[0] and v[-1] <= src - 1
            for k in range(dst):
                if k <= dst - 1 - k:
                    assert v[k] == ((2 * k + 1) * src) // (2 * dst)
                if 2 * k != dst - 1:
                    assert v[dst - 1 - k] == src - 1 - v[k], (src, dst, k)
            if dst >= src:
                assert set(v) == set(range(src))          # an enlarge shows every source column
            if dst == src:
                assert v == list(range(src))


@pytest.mark.parametrize("g", list(range(17, 49)))
def test_scaling_rail_arrow_plate_lands_on_the_grip_span(g):
    for aw in range((22 * g) >> 4, (28 * g) >> 4):            # the bar widths the law produces, +- a margin
        wn = -(-aw * 16 // g)                                  # thunk_tutbtn_post's ceil native width
        for f_w in (18, 16, 19):
            f0 = (wn - f_w) // 2
            m = SL.rail_arrow_col_map(aw, wn, f0, f0 + f_w, g)
            off, w = SL.rail_grip_span(aw, f_w, g)
            if off < 0:
                continue                                       # t_rsb_zoom bails (KSB) -- never a rail bar's art
            drawn = [j for j, c in enumerate(m) if c is not None]
            assert drawn == list(range(off, off + w)) and off == aw - off - w
            assert all(m[aw - 1 - j] - f0 == f_w - 1 - (m[j] - f0) for j in drawn if 2 * j != aw - 1)


@pytest.mark.parametrize("g", list(range(17, 97, 3)))
def test_scaling_rail_blit_rows_are_the_engine_run_table(g):
    for hn in (4, 37, 333, 480):
        runs = SL.engine_scale_runs(g, 16, hn)
        for y0, ch in ((0, 10 ** 6), (17, 10 ** 6), (5, 100)):
            rows = SL.rail_blit_rows(hn, g, y0, ch)
            assert len(rows) == min((hn * g) >> 4, ch - y0)
            want = [s for s, r in enumerate(runs) for _ in range(r)][:len(rows)]
            assert rows == want


@pytest.mark.parametrize("g", list(range(17, 65)))
def test_scaling_rail_layout_minimises_the_worst_zone(g):
    """rail_layout_zones is the argmin over EVERY symmetric layout (band depth b in [K, Wc/2], the grip span centred
    in the bar by rail_grip_span) of the worst zone deviation from vanilla x g/16, ties to the smaller sum, then to b
    nearest 4 Wc / 32, then to the smaller b -- brute force, every visible column width the law can produce."""
    k = SL.stroke_width(g)
    for wc in sorted({SL.rail_col_w(cw, g) for cw in WIDTHS} | {2 * g - 1, 2 * g, 2 * g + 1, 2 * g + 2}):
        cands = []
        for b in range(0, wc):
            bw = wc - 2 * b
            if b < k or bw < 0:
                continue
            off, w = SL.rail_grip_span(bw, 18, g)
            if off < 0:
                continue
            d = [abs(16 * (b - k) - 3 * g), abs(16 * bw - 24 * g), abs(16 * w - 18 * g), abs(16 * off - 3 * g)]
            cands.append(((max(d), sum(d), abs(32 * b - 4 * wc), b), (b, w, off)))
        assert SL.rail_layout_zones(wc, g) == min(cands)[1], (g, wc)
        if wc == SL.rail_nn_col(32, g) and g <= 52:
            assert min(cands)[0][0] <= 16, (g, wc)                      # every zone within 1 px of vanilla x g/16
