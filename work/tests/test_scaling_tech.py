"""SELECT RESEARCH GOAL (tech_pick / TechWin) laws — g=16 identity vs the three
trace runs, option-(a) proportionality, imm8 fit for the prototype's patch sites,
and a full g sweep.

Goldens = work\\frida_tech_census.log (2026-08-27, PRACX build 6f8267d6, vanilla
behaviour for this window at all three resolutions — the cluster carries no patch):
  1024x768  g=16: cw 236 ch 344 W 949  H 720  screenRect (37,24,986,744)
  1600x1200 g=25: cw 380 ch 560 W 1525 H 1152 screenRect (37,24,1562,1176)
  3840x2160 g=40: cw 940 ch 1040 W 3765 H 2112 screenRect (37,24,3802,2136)
  (the g=25/g=40 rows are VANILLA = the law at g=16 with that screen: identity)
  cell 0 (hilite) rect (3,30,234,371); cell 1 (238,30,471,371); pad 10
  icon: SCALE 6/16 -> 215*6/16 = 80, drawn at x=78 = 3 + (231-80)/2, y=90
  quote Buffer_write_strings x=7 y=180 w=223 (= L+4, W-8); unlock wrapW 229 (= W-2)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scaling_laws as SL  # noqa: E402

GS = list(range(16, 41))
RES = [(1024, 768, 16), (1920, 1080, 22), (1600, 1200, 25), (3840, 2160, 40)]


# ---- g=16 identity: the three traced windows verbatim ------------------------

@pytest.mark.parametrize("sw,sh,cw,ch,w,h", [
    (1024, 768, 236, 344, 949, 720),
    (1600, 1200, 380, 560, 1525, 1152),
    (3840, 2160, 940, 1040, 3765, 2112),
    (1920, 1080, 460, 500, 1845, 1032),   # static-map reference value
    (800, 600, 180, 260, 725, 552),       # static-map reference value
])
def test_layout_identity_matches_the_traces(sw, sh, cw, ch, w, h):
    lay = SL.tech_layout(sw, sh, 7, 16)
    assert (lay["cols"], lay["rows"]) == (4, 2)
    assert (lay["cw"], lay["ch"], lay["W"], lay["H"]) == (cw, ch, w, h)
    assert (lay["x"], lay["y"]) == ((sw - w) // 2, (sh - h) // 2)
    assert (lay["pad"], lay["caption"], lay["grid_top"]) == (10, 0x1D, 0x1E)


def test_window_position_identity():
    for sw, sh in [(1024, 768), (1600, 1200), (3840, 2160)]:
        lay = SL.tech_layout(sw, sh, 7, 16)
        assert (lay["x"], lay["y"]) == (37, 24)          # screenRect+13C in every run


def test_cell_rect_identity():
    lay = SL.tech_layout(1024, 768, 7, 16)
    assert SL.tech_cell_rect(0, lay, 16) == (3, 30, 234, 371)    # L clamped 1 -> 3
    assert SL.tech_cell_rect(1, lay, 16) == (238, 30, 471, 371)
    assert SL.tech_cell_rect(4, lay, 16) == (3, 375, 234, 716)   # row 1: 345 + 30
    assert SL.tech_cell_rect(3, lay, 16) == (712, 30, 945, 371)  # R clamp 949-3 = 946 > 945 (no clamp)
    lay40 = SL.tech_layout(3840, 2160, 7, 16)
    assert SL.tech_cell_rect(0, lay40, 16) == (3, 30, 938, 1067)
    assert SL.tech_caption_rects(lay, 16) == {"strip": (3, 3, 946, 26), "text": (6, 6, 943, 23),
                                              "backdrop": (0, 0, 949, 720)}


def test_icon_identity():
    lay = SL.tech_layout(1024, 768, 7, 16)
    s = SL.tech_icon_class(lay["cw"], 16)
    assert s == -10
    assert SL.tech_icon_ratio(s, 16) == (6, 16)
    assert SL.tech_icon_w(s, 16) == 80
    assert 3 + (231 - 80) // 2 == 78                             # traced x
    assert SL.tech_icon_imms(16) == {"den": 16, "s10": -10, "mask": 2, "add": -14, "shift": 4}
    assert SL.tech_icon_class(0x8C, 16) == -14 and SL.tech_icon_class(0x8D, 16) == -12
    assert SL.tech_icon_class(0xB3, 16) == -12 and SL.tech_icon_class(0xB4, 16) == -10
    assert SL.tech_icon_w(-14, 16) == 26 and SL.tech_icon_w(-12, 16) == 53   # 215*2/16, 215*4/16


def test_hit_identity():
    lay = SL.tech_layout(1024, 768, 7, 16)
    assert SL.tech_hit_index(78, 90, lay, 16) == 0
    assert SL.tech_hit_index(237, 30, lay, 16) == 1             # pitch boundary 237 = cw+1
    assert SL.tech_hit_index(236, 30, lay, 16) == 0
    assert SL.tech_hit_index(0, 28, lay, 16) == -1              # above the grid (y-0x1D < 0)
    assert SL.tech_hit_index(0, 29, lay, 16) == 0
    assert SL.tech_hit_index(4 * 237, 100, lay, 16) == -1       # right of the last column
    assert SL.tech_hit_index(0, 29 + 2 * 345, lay, 16) == -1    # below the last row


def test_cols_table():
    assert [SL.tech_cols(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 16, 21)] == \
        [1, 2, 3, 4, 5, 3, 4, 4, 5, 4, 4, 7]
    assert SL.tech_cols(39) == 8 and SL.tech_cols(40) == 10 and SL.tech_cols(90) == 10
    with pytest.raises(ValueError):
        SL.tech_layout(1024, 768, 0, 16)


# ---- option (a): vanilla's screen-fit law at device density ------------------

@pytest.mark.parametrize("sw,sh,g", RES)
def test_layout_is_vanilla_on_the_virtual_screen_within_rounding(sw, sh, g):
    """Scaling the constants == running vanilla on the (SW*16/g, SH*16/g) virtual
    screen then x g/16, to within the rounding of each scaled constant."""
    lay = SL.tech_layout(sw, sh, 7, g)
    virt = SL.tech_layout(sw * 16 // g, sh * 16 // g, 7, 16)
    assert abs(lay["cw"] - virt["cw"] * g / 16) <= 2
    assert abs(lay["ch"] - virt["ch"] * g / 16) <= 2
    assert abs(lay["W"] - virt["W"] * g / 16) <= 2 + 5 * (g / 16)   # 5 native gutters stay 1
    assert abs(lay["H"] - virt["H"] * g / 16) <= 2 + 3 * (g / 16)


@pytest.mark.parametrize("sw,sh,g", RES)
def test_window_fits_the_screen_and_fills_like_vanilla(sw, sh, g):
    lay = SL.tech_layout(sw, sh, 7, g)
    assert 0 < lay["W"] <= sw and 0 < lay["H"] <= sh
    assert lay["x"] >= 0 and lay["y"] >= 0
    van = SL.tech_layout(sw, sh, 7, 16)
    assert lay["W"] >= van["W"] * 0.9 and lay["H"] >= van["H"] * 0.9   # never a 62%-width picker
    # every cell sits inside the canvas and clears the caption band
    for i in range(7):
        l, t, r, b = SL.tech_cell_rect(i, lay, g)
        assert 0 <= l < r <= lay["W"] and lay["caption"] <= t < b <= lay["H"]


def test_4k_targets_share_one_scale_factor():
    """The pixel-geometry check rule: every element x2.5 at g=40, no axis lagging."""
    g = 40
    lay = SL.tech_layout(3840, 2160, 7, g)
    assert lay["pad"] == 25 and lay["caption"] == 72 and lay["grid_top"] == 75
    assert SL.tech_font_size(14, g) == 35 and SL.tech_font_size(18, g) == 45 and SL.tech_font_size(20, g) == 50
    assert SL.tech_icon_w(-10, g) == 201                      # 80 x 2.5 = 201 (vanilla floor 80.6)
    assert SL.tech_icon_ratio(-10, g) == (240, 256)
    assert SL.tech_icon_imms(g) == {"den": 256, "s10": 224, "mask": 80, "add": 64, "shift": 8}
    assert SL.tech_imm(3, g) == 7 and SL.tech_imm(0x17, g) == 57 and SL.tech_imm(8, g) == 20
    l, t, r, b = SL.tech_cell_rect(1, lay, g)
    assert SL.tech_cell_inset_rb(g) == 9 and SL.tech_strip_h_imm(g) == 58
    assert (l, t) == (912, 75) and r - l == lay["cw"] - 9 and b - t == lay["ch"] - 9
    assert SL.tech_caption_rects(lay, g)["strip"] == (7, 7, 3638, 65)
    assert SL.tech_channels(g) == {"left": 5, "top": 10, "gap": 10, "right": 8, "bottom": 8}
    assert SL.tech_font_cell(16, g) == 40 and SL.tech_font_cell(24, g) == 60 and SL.tech_font_cell(22, g) == 55


@pytest.mark.parametrize("g", GS)
def test_icon_ratio_is_vanilla_times_g_over_16(g):
    for sc in SL.TECH_ICON_CLASSES:
        num, den = SL.tech_icon_ratio(sc, g)
        assert abs(num / den - (16 + sc) / 16 * g / 16) < 1e-12
        assert num / den < 4                                   # engine blit cap (g_sprite_scale_max)
        assert SL.tech_icon_w(sc, g) == (215 * num) // den
        # in-place imm realisation: the two ebx paths + the -10 literal give 16+s = (16+s)*g
        im = SL.tech_icon_imms(g)
        if g > 16:
            assert im["s10"] + 16 == 6 * g
            assert (0 & im["mask"]) + im["add"] + 16 == 2 * g       # bl=1 path (cw <= s(0x8C))
            assert (-1 & im["mask"]) + im["add"] + 16 == 4 * g      # bl=0 path
            assert 2 ** im["shift"] == im["den"]


@pytest.mark.parametrize("g", GS)
def test_prototype_imm8_sites_fit(g):
    """Every imm8 the proto patches must fit a signed byte at every g (the SE proto
    logged SKIPs for overflow; here only the n>8 overflow margin s(0x45) overflows,
    which the proto reports and the bake re-encodes)."""
    for v in (2, 3, 4, 6, 8, 12, 18, 20, 23, 0x1D, 0x1E, 0x28):
        assert -128 <= SL.tech_imm(v, g) <= 127
    im = SL.tech_icon_imms(g)
    assert -128 <= im["mask"] <= 127 and -128 <= im["add"] <= 127
    if g >= 30:
        assert SL.tech_imm(0x45, g) > 127      # documented proto limitation (n>8 only)


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("n", [1, 2, 4, 7, 8, 9, 12, 16, 25, 40])
def test_sweep_every_n_every_g(g, n):
    for sw, sh in [(1024, 768), (1920, 1080), (1600, 1200), (3840, 2160)]:
        lay = SL.tech_layout(sw, sh, n, g)
        assert lay["cols"] * lay["rows"] >= n > lay["cols"] * (lay["rows"] - 1)
        assert lay["W"] == (lay["cw"] + 1) * lay["cols"] + 1
        assert lay["H"] == (lay["ch"] + 1) * lay["rows"] + lay["grid_top"]
        assert lay["cw"] > 0 and lay["ch"] > 0
        for i in (0, n - 1):
            l, t, r, b = SL.tech_cell_rect(i, lay, g)
            assert r > l and b > t
            cx, cy = (l + r) // 2, (t + b) // 2
            assert SL.tech_hit_index(cx, cy, lay, g) == i     # hit-test agrees with the painter
        assert SL.tech_hit_index(-1, 0, lay, g) == -1
        cap = SL.tech_caption_rects(lay, g)
        assert cap["strip"][3] < lay["grid_top"] + lay["ch"]   # caption above the first row


@pytest.mark.parametrize("g", GS)
def test_monotone_in_g(g):
    if g == 16:
        return
    a, b = SL.tech_layout(3840, 2160, 7, g - 1), SL.tech_layout(3840, 2160, 7, g)
    assert b["W"] <= a["W"] and b["H"] <= a["H"]              # more scale -> more margin, never less
    assert SL.tech_font_size(14, g) >= SL.tech_font_size(14, g - 1)


# ---- v2 laws: channels proportionate, one-cascade strip, cell-calibrated fonts ---

@pytest.mark.parametrize("g", GS)
def test_v2_channels_are_vanilla_times_g_over_16(g):
    """proto v1 measured @4K: right/bottom 5 (vanilla 3 -> 7.5), gap 7 (4 -> 10) because the
    native +1 gutter cannot scale and the devfill stroke spilled 1 px.  The v2 inset law
    puts every drawn channel within 1 px of vanilla x g/16 at EVERY g."""
    ch = SL.tech_channels(g)
    van = {"left": 2, "top": 4, "gap": 4, "right": 3, "bottom": 3}
    for k, v in van.items():
        assert abs(ch[k] - v * g / 16) <= 1.0, f"{k} @g={g}: {ch[k]} vs {v * g / 16}"
    assert ch["gap"] == SL.scale_px(4, g)                 # L' - R exactly s(4)
    assert SL.tech_cell_inset_rb(g) >= 3 and SL.tech_cell_inset_rb(g) >= SL.scale_px(3, g) - 1


@pytest.mark.parametrize("g", GS)
def test_v2_strip_bottom_is_one_cascade(g):
    lay = SL.tech_layout(1600, 1200, 7, g)
    cap = SL.tech_caption_rects(lay, g)
    assert cap["strip"][3] == SL.scale_px(26, g)
    assert cap["strip"][1] + SL.tech_strip_h_imm(g) == cap["strip"][3]
    assert -128 <= SL.tech_strip_h_imm(g) <= 127          # imm8 @0x487DBD
    assert lay["grid_top"] - cap["strip"][3] == SL.tech_channels(g)["top"]


def test_v2_identity_at_native():
    assert SL.tech_cell_inset_rb(16) == 3 and SL.tech_strip_h_imm(16) == 0x17
    assert SL.tech_channels(16) == {"left": 2, "top": 4, "gap": 4, "right": 3, "bottom": 3}
    for c in (16, 20, 22, 24):
        assert SL.tech_font_cell(c, 16) == c


@pytest.mark.parametrize("g", GS)
def test_v2_font_cell_law(g):
    """target cell = fl(native_cell*g/16): monotone, identity at 16, never above the
    nominal-scaled cell of a linear font (the calibration loop searches upward from
    s(native)-8 and must find it within +16)."""
    for c in (16, 20, 22, 24):
        tc = SL.tech_font_cell(c, g)
        assert tc == (c * g) // 16
        assert tc >= SL.tech_font_cell(c, g - 1) if g > 16 else True
    assert SL.tech_font_cell(24, 40) == 60 and SL.tech_font_cell(22, 40) == 55


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("n", [1, 4, 7, 8, 9, 16])
def test_v2_cells_still_agree_with_hit_test_and_fit(g, n):
    for sw, sh in [(1024, 768), (1920, 1080), (1600, 1200), (3840, 2160)]:
        lay = SL.tech_layout(sw, sh, n, g)
        for i in range(n):
            l, t, r, b = SL.tech_cell_rect(i, lay, g)
            assert r - l > 0 and b - t > 0
            assert SL.tech_hit_index((l + r) // 2, (t + b) // 2, lay, g) == i
            if (i + 1) % lay["cols"] and i + 1 < n:                     # right neighbour
                l2 = SL.tech_cell_rect(i + 1, lay, g)[0]
                assert l2 - r == SL.scale_px(4, g)                       # the gap law
        # last column's right channel = W - R = s(4) (unless the canvas clamp bites)
        r_last = SL.tech_cell_rect(min(n, lay["cols"]) - 1, lay, g)[2]
        assert lay["W"] - r_last == SL.scale_px(4, g)
