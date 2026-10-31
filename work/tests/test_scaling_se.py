"""Social Engineering screen laws — g=16 identity, run goldens, g sweep.

Goldens = the hook_se_scale_proto.js v23 runs (frida_se_proto.log 2026-08-25,
user-verified 4K/1600/1920, pixel-measured): the transform's logged tables at
g=22/25/40.  Identity = the SocialWin_build seed table (work\\_se_static_map.md).
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scaling_laws as SL  # noqa: E402

GS = list(range(16, 41))


# ---- g=16 identity: the builder seed table verbatim ----------------------------

def test_modal_identity():
    m = SL.se_modal_rects(16)
    assert m["society_outer"] == (0x271, 4, 0x306, 0xFA)
    assert m["society_rows"][0] == (0x274, 0x1D, 0x303, 0x31)
    assert m["society_rows"][9] == (0x274, 0x1D + 9 * 22, 0x303, 0x1D + 9 * 22 + 20)
    assert m["bands"] == [(0x1A, 0x04, 0x26E, 0x4A), (0x1A, 0x4D, 0x26E, 0x93),
                          (0x1A, 0x96, 0x26E, 0xDC), (0x1A, 0xDF, 0x26E, 0x125)]
    assert m["options"][0] == (0x1D, 0x1D, 0x1D + 0x92, 0x1D + 0x14)
    assert m["options"][15] == (0x1D9, 0xF8, 0x1D9 + 0x92, 0xF8 + 0x14)
    assert m["faction"] == (0x271, 0xFD, 0x306, 0x12D)
    assert m["ok"] == (0x1E4, 0x13A, 0x286, 0x14E)
    assert m["reset"] == (0x13F, 0x13A, 0x1E1, 0x14E)
    assert m["cancel"] == (0x9A, 0x13A, 0x13C, 0x14E)


def test_console_identity():
    regions = [12, 100, 300, 250, 400, 100, 700, 250, 720, 100, 1000, 250, 12, 299, 1194, 387]
    c = SL.se_console_rects(regions, 16)
    assert c["fx_box"] == (404, 104, 696, 246)
    assert c["center_box"] == (724, 104, 996, 246)
    L, T, R, B = 12 + 7, 299 + 7, 1194 - 7, 387 - 7
    col_w = (R - L - 4) // 3 - 3
    assert c["slider_econ"] == (L, T, L + col_w, B)
    assert c["slider_psych"] == (L + col_w + 3, T, L + 2 * col_w + 3, B)
    assert c["slider_labs"] == (L + 2 * col_w + 6, T, R, B)
    assert c["hover_box"] == (16, 104, 296, T - 6)
    assert c["arrows"][0] == (L + 3, T + 3, L + 0x17, T + 0x17)
    assert c["arrows"][1] == (L + col_w - 0x17, T + 3, L + col_w - 3, T + 0x17)
    assert c["locks"][0] == (L + 3, B - 0x11, L + 0x1B, B - 3)
    assert c["lock_phase_y"] == B - 0x11


def test_imm_and_font_identity():
    for a, b in ((3, 0), (0x17, 3), (0, 0x14), (0xF, 0x14), (0x162, 0), (0, 0x321)):
        assert SL.se_imm(a, b, 16) == a - b
    assert [SL.se_font_size(v, 16) for v in SL.SE_FONT_SIZES] == list(SL.SE_FONT_SIZES)
    assert SL.se_sprite_canvas(26, 26, 16) == (26, 26)
    assert SL.se_lock_plane_dims(16) == (24, 14)


# ---- run goldens (frida_se_proto.log v23) --------------------------------------

@pytest.mark.parametrize("g, panel, faction, band0, opt0", [
    (25, (977, 6, 1209, 385), (977, 391, 1209, 466), (41, 6, 972, 116), (46, 45, 274, 76)),   # opt0 L 45 -> 46: run centred in the band (2026-10-11)
    (22, (859, 5, 1064, 339), (859, 344, 1064, 410), (36, 5, 855, 102), (41, 40, 241, 67)),   # opt0 L 40 -> 41: even channels
    (40, (1562, 10, 1935, 622), (1562, 630, 1935, 750), (65, 10, 1555, 185), (72, 72, 437, 122)),
])
def test_modal_goldens(g, panel, faction, band0, opt0):
    m = SL.se_modal_rects(g)
    assert m["society_outer"] == panel
    assert m["faction"] == faction
    assert m["bands"][0] == band0
    assert m["options"][0] == opt0


@pytest.mark.parametrize("g, pitch, h, t0, last_b", [(25, 34, 31, 45, 382), (22, 30, 27, 40, 337), (40, 55, 50, 72, 617)])
def test_society_row_goldens(g, pitch, h, t0, last_b):
    rows = SL.se_society_rows(g)
    assert rows[0][1] == t0 and rows[9][3] == last_b
    assert all(rows[i + 1][1] - rows[i][1] == pitch for i in range(9))
    assert all(r[3] - r[1] == h for r in rows)


def test_console_golden_g25():
    # v23 g=25 log: sldE=17,304,400,382 arrows0=22,309,53,340 (regions reconstructed from the
    # derivation: L = r0.x + s(7)=11 -> r0.x 6; T = rs.T + 11 -> 293; B = rs.B - 11 -> 393; R -> 1198)
    regions = [6, 100, 300, 250, 400, 100, 700, 250, 720, 100, 1000, 250, 6, 293, 1198, 393]
    c = SL.se_console_rects(regions, 25)
    assert c["slider_econ"] == (17, 304, 400, 382)
    assert c["arrows"][0] == (22, 309, 53, 340)
    assert c["locks"][0] == (17 + 5, 382 - 27, 17 + 42, 382 - 5)
    assert c["lock_phase_y"] == 355   # "lock plane restriped ... phaseY=355" @g25


def test_sprite_alias_goldens():
    assert SL.se_sprite_canvas(26, 26, 40) == (65, 65)      # log: iconGap/rowH=65/65
    assert SL.se_lock_plane_dims(40) == (60, 35)            # log: sldInset/H=60/35
    assert SL.se_tile_height(40) == 8 and SL.se_tile_height(25) == 8 and SL.se_tile_height(22) == 8     # 2P, P = 4


# ---- g sweep ----------------------------------------------------------------------

@pytest.mark.parametrize("g", GS)
def test_modal_sweep(g):
    m = SL.se_modal_rects(g)
    W, H = SL.scale_px(SL.SE_MODAL_W, g), SL.scale_px(SL.SE_MODAL_H, g)
    rows = m["society_rows"]
    pitch, h = SL.scale_px(22, g), SL.popup_scale_floor(20, g)
    # uniform pitch, floor height, exact shrink round-trip (ceil inverse)
    assert all(rows[i + 1][1] - rows[i][1] == pitch for i in range(9))
    for r in rows + m["options"] + [m["ok"], m["reset"], m["cancel"]]:
        assert r[3] - r[1] == h
        assert math.ceil((r[3] - r[1]) * 16 / g) == 20
    for r in rows:
        assert math.ceil((r[2] - r[0]) * 16 / g) == 143
    for r in m["options"]:
        assert math.ceil((r[2] - r[0]) * 16 / g) == 146
    for r in (m["ok"], m["reset"], m["cancel"]):
        assert math.ceil((r[2] - r[0]) * 16 / g) == 162
    # rows inside the panel, panel + faction inside the modal, faction below the panel
    P, F = m["society_outer"], m["faction"]
    assert P[0] < rows[0][0] and rows[0][2] < P[2]
    assert P[1] < rows[0][1] and rows[-1][3] < P[3]
    assert 0 <= P[1] and F[3] <= H and P[2] <= W and F[2] <= W
    assert F[1] > P[3]
    assert F[3] - F[1] == SL.scale_px(0x12D, g) - SL.scale_px(0xFD, g)
    if g > 16:
        K = SL.stroke_width(g)
        band_b = P[1] + SL.scale_px(23, g)
        top_free = rows[0][1] - band_b - 1
        bottom_free = (P[3] - K + 1) - rows[-1][3]
        assert top_free == bottom_free >= 1
        assert F[1] - P[3] - 1 == SL.scale_px(3, g)
    # options: 4 per band, inside their band, non-overlapping columns
    for b in range(4):
        band = m["bands"][b]
        cols = m["options"][b * 4:(b + 1) * 4]
        for c in cols:
            assert band[0] <= c[0] and c[2] <= band[2] and band[1] <= c[1] and c[3] <= band[3]
        assert all(cols[i][2] <= cols[i + 1][0] for i in range(3))
    # the three command buttons on one row, non-overlapping, inside the modal
    ok, rs, ca = m["ok"], m["reset"], m["cancel"]
    assert ok[1] == rs[1] == ca[1] and ca[2] <= rs[0] and rs[2] <= ok[0] and ok[2] <= W and ok[3] <= H


@pytest.mark.parametrize("g", GS)
def test_console_sweep(g):
    # the region globals are HUD-scaled device rects: scale the 1024 seeds with g
    regions = [SL.scale_px(v, g) for v in (12, 100, 300, 250, 400, 100, 700, 250, 720, 100, 1000, 250, 12, 299, 1194, 387)]
    c = SL.se_console_rects(regions, g)
    e, p, l = c["slider_econ"], c["slider_psych"], c["slider_labs"]
    s3 = SL.scale_px(3, g)
    assert e[2] - e[0] == p[2] - p[0]                  # ECON/PSYCH share the pinned column width
    assert p[0] - e[2] == s3 and l[0] - p[2] == s3     # scaled gaps
    assert l[2] == regions[14] - SL.scale_px(7, g)     # LABS absorbs the remainder to the strip edge
    assert 0 <= (l[2] - l[0]) - (e[2] - e[0]) <= SL.scale_px(4, g) + s3 + 2   # LABS = colW + remainder (< s4 + 3)
    for a in c["arrows"]:
        assert a[2] - a[0] == a[3] - a[1] == SL.scale_px(0x17, g) - s3
    for k in c["locks"]:
        assert k[2] - k[0] == SL.scale_px(0x1B, g) - s3 and k[3] - k[1] == SL.scale_px(0x11, g) - s3
    assert c["hover_box"][3] == e[1] - SL.scale_px(6, g)


@pytest.mark.parametrize("g", GS)
def test_imm_sweep(g):
    for a, b in ((3, 0), (0x17, 3), (0, 0x14), (0xF, 0x14), (0x162, 0), (0, 0x321), (7, 0), (1, 0)):
        assert SL.se_imm(a, b, g) == SL.scale_px(a, g) - SL.scale_px(b, g)
        assert -128 <= SL.se_imm(a, b, g) or a >= 0x100 or b >= 0x100
    for v in SL.SE_FONT_SIZES:
        assert 0 < SL.se_font_size(v, g) < 128
    assert SL.se_tile_height(g) % SL.stripe_period(g) == 0
    dst, src = SL.se_lock_plane_dims(g)[1], 14
    cm = SL.se_centre_map(dst, src)
    assert cm[0] == 0 and cm[-1] == src - 1 and all(cm[i] <= cm[i + 1] for i in range(dst - 1))


# ---- backdrop / slide rails (se_scale v2) ------------------------------------------

def test_backdrop_identity():
    assert SL.se_backdrop_rect(16) == (0x17, 0, 0x30A, 0x162)
    assert SL.se_window_w(16) == 0x341
    assert SL.rail_left_extent(16) == 0x17
    assert SL.se_modal_rects(16)["backdrop"] == (0x17, 0, 0x30A, 0x162)


@pytest.mark.parametrize("g, w, rect", [(22, 1146, (31, 0, 1069, 487)), (25, 1302, (35, 0, 1215, 553)),
                                        (40, 2083, (57, 0, 1945, 885))])
def test_backdrop_goldens(g, w, rect):
    # W = ceil(833g/16); L = fl(15g/16)+fl(8g/16); R = fl((fl(W*16/g) - 55)*g/16) = fl(778g/16); B = s(354)
    assert SL.se_window_w(g) == w
    assert SL.se_backdrop_rect(g) == rect
    assert SL.se_modal_rects(g)["backdrop"] == rect


@pytest.mark.parametrize("g", GS)
def test_backdrop_sweep(g):
    L, T, R, B = SL.se_backdrop_rect(g)
    w = SL.se_window_w(g)
    # the window width descales to EXACTLY 833 through railscale's floor (the round-trip law)
    assert (w << 4) // g == 0x341 and 0 <= w - SL.scale_px(0x341, g) <= 1
    # abutment: L == the left rails' composed device extent; R == the right rails' start
    assert L == SL.popup_scale_floor(15, g) + SL.popup_scale_floor(8, g)
    assert R == SL.popup_scale_floor(SL.rail_right_anchor(w, w - 55, g), g) == SL.popup_scale_floor(0x30A, g)
    assert T == 0 and B == SL.scale_px(SL.SE_MODAL_H, g)
    # the rails' floor cascades never stray more than 1px from the plain half-down of the seeds
    assert 0 <= SL.scale_px(0x17, g) - L <= 1
    assert 0 <= SL.scale_px(0x30A, g) - R <= 1
    # the panels stay inside the backdrop; the right rails start past the window's 32px margin
    m = SL.se_modal_rects(g)
    assert L < m["bands"][0][0] and m["society_outer"][2] < R and m["faction"][2] < R
    assert R + SL.popup_scale_floor(15, g) + SL.popup_scale_floor(8, g) <= w


# ---- button runs: one channel width (2026-10-11, user 1920x1080 shot 215846) -------------------------------------

@pytest.mark.parametrize("g", list(range(16, 97)))
def test_button_runs_have_one_channel_width(g):
    """Every option row's 3 channels are one width, CANCEL/RESET/OK's 2 likewise; widths stay the floor
    (shrink inverse); the option run sits in its band frame with outer margins within 1 of each other;
    g=16 is vanilla verbatim (law se_button_run_lefts)."""
    m = SL.se_modal_rects(g)
    o, b = m["options"], [m["cancel"], m["reset"], m["ok"]]
    W, BW = SL.popup_scale_floor(146, g), SL.popup_scale_floor(162, g)
    for k in range(4):
        row = o[4 * k:4 * k + 4]
        assert {row[i + 1][0] - row[i][2] for i in range(3)} == {SL.scale_px(2, g)}
        assert all(r[2] - r[0] == W for r in row)
        assert [r[0] for r in row] == [r[0] for r in o[:4]]
        band = m["bands"][k]
        lm, rm = row[0][0] - band[0], band[2] - row[3][2]
        assert lm >= 1 and abs(lm - rm) <= 1
    assert {b[i + 1][0] - b[i][2] for i in range(2)} == {SL.scale_px(3, g)}
    assert all(r[2] - r[0] == BW for r in b)
    lo, hi = SL.scale_px(0x9A, g), SL.scale_px(0x286, g)
    assert abs((b[0][0] - lo) - (hi - b[2][2])) <= 1
    if g == 16:
        assert [r[0] for r in o[:4]] == list(SL.SE_OPTION_X)
        assert (b[0][0], b[1][0], b[2][0]) == (SL.SE_BTN_CANCEL[0], SL.SE_BTN_RESET[0], SL.SE_BTN_OK[0])
