"""The base-screen mirror law (2026-10-25 W5A v2): the base screen mirrored about ONE axis, S = pt(726).

The defect (measured by W4C, reproduced column for column against the user's 4K / 1080 base-screen shots):
  * the console frame's right stroke was drawn ON the right rail's first column (thunk_bw_boxsprite_console v3 handed
    the inclusive band renderer the rail anchor itself), so the rails ate it: visible right border K - 1 (none at
    g 17..24 = 1080, 1 px of 2 at 1600x1200 and 4K);
  * at odd g 17 / 19 / 21 / 23 / 33 / 35 / 37 / 39 the console's left pt(23) sat 1 px right of the left rails'
    composed extent fl(15g/16) + fl(8g/16): a key-9 (see-through) column; at g = 17 the rails did not scale at all
    (canvas 520 rows < the 529-row art) and the right side had a 4-px gap;
  * the content is placed by basewin_pt while the rails carried railscale's double floor fl((fl(W*16/g)-55)*g/16),
    0..4 px left of the content's mirror, so every right-side channel drifted (console -> panel 5 | 3 at 1080,
    5 | 2 at 1600x1200, panel -> inner box 6 | 5 at 4K; the audit-w5A pair census: 700..3000 asymmetric pairs per g).
The law (v2 = design (c) of audit-w5A): ONLY the base screen's right rails move -- onto the left rails' mirror through
the content axis, A* = pt(726) - Lx (t_bw_railscale on the 4 settled slide_show sites, t_bw_railanchor in railslide's
animation frames; every other slide window untouched) -- so S = pt(726), the axis basewin_pt already places the left
half on.  Then every edge with a mirror twin about 363 is placed by its twin's mirror (basewin_mirror_rect: the right
column's both edges, the self-mirrored middle panel, the rims; basewin_child_rect: the tab row and the
RESOURCE / SUPPORT / PSYCH row, GOVERNOR / SUPPORT centred; the console frame spans the rails' gap), and every element
stays within ~1 px of vanilla x g/16.
v4 (F42, "fix overreach first"): every centre box is drawn on its native HALF-OPEN extent (basewin_box_draw_rect: the
half-open basewin_mirror_rect through the shared trim helpers t_bm_ho_hf / t_bm_ho_df), on both columns -- v2 / v3 drew
them inclusive (+1 px right and down) and mirrored that overreach onto the right column's left edges.

Proof layers:
  1. the laws, g 16..40 (the game's clamp): K | K borders, no see-through column, every channel pair equal, the
     twin columns equal, every element's width against vanilla x g/16, the rails inside the canvas;
  2. END TO END on the real image (basewin_mirror_emu.py): the real MainWin_build, BaseWin_init, slide_show's settled
     rails through t_bw_railscale and the centre painters in BaseWin_on_redraw's order, measured on the final canvas
     -- the walk from each rail inward (K | K, no key-9 column, equal channels, NO stroke colour inside a channel),
     the twin rows' gaps palindromic, and the audit's full pair census against the pristine 1024 canvas: every
     vanilla-mirrored colour transition sums to S on the device row (rows within 1 of a box's first / last row
     reported apart -- a corner's chamfer is vertical structure); every centre box's drawn strokes on its law
     footprint (basewin_box_draw_rect); g = 16 is the pristine image's canvas pixel for pixel and its child
     windows arg for arg.  4K (g = 40) is left to the Unicorn parity sweeps (test_bw_mirror_asm_parity.py: every thunk at
     every g 16..40); the image items are the phase classes, g = 33 the worst case.
  (Unit parity: test_bw_mirror_asm_parity.py, test_facsb_asm_parity.py, test_bw_wheel_asm_parity.py.)

COST: one boot per image per worker (~2 s); a screen re-runs MainWin_build + BaseWin_init + slide_show + the painters
(~1.6 s at 1024 .. ~22 s at g = 33, BaseWin_init's console devfill at device size) plus a ~1 s census.  Items are per
screen so the module splits across xdist by measured cost; the serial total (~70 s) buys the engine's own call order
(the rails are drawn by slide_show AFTER BaseWin_init's frame and BEFORE the painters -- invisible to a slice).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402

LAW_G = range(16, 41)
#: the phase classes on the real image: native-rails g (17), the see-through column (17 / 19 / 33), K = 1 / 2, the
#: user's 1080 / 1600x1200, and g = 33 -- the worst case of audit-w5A
E2E_G = (17, 19, 22, 25, 33)
SCREENS = {22: (1920, 1080), 25: (1600, 1200), 33: (2560, 1600)}
#: W8B v2 (audit-w8B I2): the user's other resolutions, for the button rows only (test_e2e_rows)
ROWS_SCREENS = {18: (1600, 900), 20: (1280, 1024), 30: (2560, 1440), 40: (3840, 2160)}
#: every centre box rect the pristine image draws (BaseWin_init + the centre painters; census W5A), the console aside
BOXES = [(27, 4, 699, 30), (128, 446, 622, 472), (166, 33, 560, 257), (563, 33, 699, 257), (566, 36, 696, 56),
         (566, 57, 696, 254), (27, 190, 163, 384), (30, 193, 160, 213), (30, 214, 160, 381), (27, 33, 163, 187),
         (30, 36, 160, 56), (30, 57, 160, 184), (166, 352, 699, 441), (346, 376, 696, 438), (169, 355, 696, 375),
         (169, 376, 297, 396), (299, 376, 344, 396), (169, 397, 297, 417), (299, 397, 344, 417), (169, 418, 297, 438),
         (299, 418, 344, 438), (166, 260, 699, 349), (298, 263, 697, 325), (169, 263, 296, 283), (169, 284, 296, 304),
         (169, 305, 296, 325), (169, 326, 696, 346), (27, 387, 163, 443), (30, 390, 160, 440)]


#: boxes whose outer stroke colour is unique at their left / right footprint on the middle row (pristine 1024 canvas):
#: the column panels (31), their inner boxes (34)
OK_FRAME = (128, 446, 622, 472)     # W8B: drawn by thunk_bw_boxsprite_okrow (basewin_okrow_box_draw_rect)
FOOTPRINT_BOXES = [((27, 33, 163, 187), 31), ((563, 33, 699, 257), 31), ((30, 57, 160, 184), 34),
                   ((566, 57, 696, 254), 34), ((27, 190, 163, 384), 31), ((30, 214, 160, 381), 34)]


def pt(v, g):
    return SL.basewin_pt(v, g)


def K(g):
    return SL.stroke_width(g) if g > 16 else 1


# ============================================================================== 1. laws
@pytest.mark.parametrize("g", LAW_G)
def test_law_console_spans_the_rails_gap(g):
    """K | K visible borders, no see-through column, the rails' gap exactly, inside the canvas."""
    l, t, r, b = SL.basewin_console_frame_rect(g)
    if g <= 16:
        assert (l, r) == (23, 703)            # vanilla, drawn half-open by the engine (cols 23 and 702)
        return
    S, lx, a = SL.basewin_rail_axis_sum(g), SL.basewin_rail_left_extent(g), SL.basewin_rail_anchor(g)
    assert S == pt(726, g) and lx == SL.rail_left_extent(g) and a == S - lx
    assert (l, r) == (lx, a - 1) and l + r == S - 1
    w = (758 * g) >> 4
    assert SL.basewin_rail_strip_x(w, w - 47, g) + ((15 * g) >> 4) == S <= w - ((32 * g) >> 4)
    assert abs(a - 703 * g / 16) < 1.5, "the moved rail stays within ~1 px of vanilla x g/16"


@pytest.mark.parametrize("g", LAW_G)
def test_law_channels_and_twins_pair_up(g):
    """console -> panel / tab frame, panel -> inner box, tab frame -> outer buttons, the twin columns' widths, the
    middle panel's two gaps, the inner pair (left panel's last column + right panel's first) -- at every g."""
    if g <= 16:
        return
    k, S = K(g), SL.basewin_rail_axis_sum(g)
    l, _, r, _ = SL.basewin_console_frame_rect(g)
    box = lambda *rc: SL.basewin_box_draw_rect(*rc, g)  # noqa: E731
    lp, rp, li, ri, mid = box(27, 33, 163, 187), box(563, 33, 699, 257), box(30, 57, 160, 184), \
        box(566, 57, 696, 254), box(166, 33, 560, 257)
    tab_r = SL.basewin_tabframe_right(g)
    assert lp[0] - (l + k) == (r - k + 1) - rp[2] - 1, "console -> panel"
    assert lp[0] - (l + k) == (r - k + 1) - tab_r - 1, "console -> tab frame"
    assert li[0] - (lp[0] + k) == (rp[2] - k + 1) - ri[2] - 1, "panel -> inner box"
    assert lp[2] - lp[0] == rp[2] - rp[0] and li[2] - li[0] == ri[2] - ri[0], "twin widths"
    assert lp[2] + rp[0] == S - 1 and li[2] + ri[0] == S - 1, "the inner pairs"
    assert mid[0] - lp[2] == rp[0] - mid[2], "left column | middle == middle | right column"
    conquer_r = SL.basewin_tab_mirror_x(584, 112, g) + SL.popup_scale_floor(112, g)
    assert pt(30, g) - (pt(27, g) + k) == (tab_r - k + 1) - conquer_r, "tab frame -> EXPLORE | CONQUER"
    assert tab_r == rp[2], "the tab frame and the right panel share the rim (vanilla: both 698)"


@pytest.mark.parametrize("g", LAW_G)
def test_law_farm_fill_inside_the_strokes(g):
    """v5 (audit-w5A v4 MEDIUM): draw_farm's interior fill (native (167, 34, 559, 256), its box's 1-px inset, painted
    AFTER the box) is the half-open box inset by K: it ends exactly where each K-wide stroke begins -- no overpaint
    of the right / bottom strokes (v4: 1 / 1 / 2 / 1 at g 25 / 27) and no backdrop gap inside them (v4: g 21 / 23 / 39
    sides, g 40 top).  The SUPPORT view's full-panel fill keeps the half-open panel."""
    k = K(g)
    if g <= 16:
        assert SL.basewin_fill_rect(167, 34, 559, 256, g) == (167, 34, 559, 256)     # the native call, untouched
        return
    L, T, R, B = SL.basewin_box_draw_rect(166, 33, 560, 257, g)        # inclusive footprint
    fl, ft, fr, fb = SL.basewin_fill_rect(167, 34, 559, 256, g)         # half-open fill
    assert (fl, ft, fr, fb) == (L + k, T + k, R + 1 - k, B + 1 - k), g
    assert SL.basewin_fill_rect(166, 33, 560, 257, g) == SL.basewin_mirror_rect(166, 33, 560, 257, g)
    if g > 16:
        S = SL.basewin_rail_axis_sum(g)
        assert fl + fr == S, "the fill is mirror-symmetric about the axis"


@pytest.mark.parametrize("g", LAW_G)
def test_law_children_and_the_facilities_bar(g):
    x0, y0, x1, y1 = SL.basewin_facsb_rect(681, 60, 693, 251, g)
    fb = SL.basewin_child_rect(569, 231, 124, 20, g)
    assert x1 == SL.basewin_rim_x(693, g) == fb[0] + fb[2], "the facilities button ends where the bar does"
    sub = [SL.basewin_child_rect(x, 234, 128, 20, g) for x in (169, 299, 429)]
    assert sub[1][0] - (sub[0][0] + sub[0][2]) == sub[2][0] - (sub[1][0] + sub[1][2])
    assert sub[0][0] + sub[2][0] + sub[2][2] == SL.basewin_rail_axis_sum(g)
    ren, ok = [SL.basewin_child_rect(x, 449, 238, 20, g) for x in (131, 381)]
    if g > 16:
        # W7H: RENAME on the edge law, OK its mirror through the row frame's own edge sum (box 128..622, plain pt)
        S2 = SL.basewin_okrow_axis_sum(g)
        assert S2 == pt(128, g) + pt(622, g)
        # W8B: y on basewin_okrow_v (the frame one channel above / below, the tab row's)
        assert ren == (pt(131, g), SL.basewin_okrow_v(g)[2], pt(369, g) - pt(131, g), SL.popup_scale_floor(20, g))
        assert ok == (S2 - pt(369, g), ren[1], ren[2], ren[3])
        assert ren[0] - pt(128, g) == pt(622, g) - (ok[0] + ok[2]), "box -> RENAME == OK -> box"
    else:
        assert (ren, ok) == ((131, 449, 238, 20), (381, 449, 238, 20))


def test_law_every_element_within_a_pixel_of_vanilla():
    """v4 (F42): every centre box's DRAWN footprint [L, R-1] x [T, B-1] (basewin_box_draw_rect) is its half-open
    extent: each edge (L, R, T, B) within 1 px of vanilla x g/16 over g 17..40; the width R - L within (-1, +1.75) --
    only an axis-spanning box (a non-twin left edge on plain pt, a rim right edge on the mirror) can exceed 1 px:
    the four listed below, at the g listed (audit-w5A v3's estimate; a left edge has no twin to mirror, so its pt
    stays, as every other consumer of that x does).  The two columns' twins are exactly equal.  Every child's x
    within 1 px of x g/16, its width within (-1, +2) (GOVERNOR / SUPPORT's centring parity)."""
    over = set()
    for g in range(17, 41):
        for rc in BOXES:
            L, T, R, B = SL.basewin_okrow_box_draw_rect(g) if rc == OK_FRAME else SL.basewin_box_draw_rect(*rc, g)
            l, t, r, b = rc
            for dev, nat in ((L, l), (R + 1, r), (T, t), (B + 1, b)):
                assert abs(dev - nat * g / 16) <= 1, (rc, g, dev, nat)
            ew = (R + 1 - L) - (r - l) * g / 16
            assert -1 < ew < 1.75, (rc, g, ew)
            if abs(ew) > 1:
                over.add((rc, g))
        for x, y, w, h in ((30, 7, 112, 20), (144, 7, 112, 20), (258, 7, 20, 20), (280, 7, 166, 20), (448, 7, 20, 20),
                           (470, 7, 112, 20), (584, 7, 112, 20), (169, 234, 128, 20), (299, 234, 128, 20),
                           (429, 234, 128, 20), (569, 231, 124, 20), (131, 449, 238, 20), (381, 449, 238, 20)):
            X, Y, W, H = SL.basewin_child_rect(x, y, w, h, g)
            # W7H: both horizontal edges within 1 px (v6: RENAME / OK / chevron 1 right edges up to 1.69 px short);
            # GOVERNOR / SUPPORT's width absorbs the centring parity (< 2).  Vertically the tab row (y 7) within
            # 1 px except its bottom at g 19 / 35 (-1.06, as v6); RENAME / OK (W8B) and RESOURCE / SUPPORT / PSYCH
            # (W8R) on their row laws; the facilities button keeps v6's pt(y) + fl(20g/16) (h stays fl(20g/16): a
            # taller window would leave key rows under the 20-row art)
            assert abs(X - x * g / 16) <= 1 and abs(X + W - (x + w) * g / 16) <= 1, ((x, y, w, h), g, X, W)
            # W8B: a button-row width may sit exactly 1 px short (the equal-gap layouts: 1600x900's tab buttons 125,
            # 1280x1024's SUPPORT 159) -- the user's threshold is MORE than 1 px
            assert -1 <= W - w * g / 16 < 2 and H == SL.popup_scale_floor(h, g), ((x, y, w, h), g, W, H)
            if y == 7:
                assert abs(Y - y * g / 16) <= 1, ((x, y), g, Y)
                assert abs(Y + H - (y + h) * g / 16) <= 1 or g in (19, 35), ((x, y), g, Y, H)
            elif y == 449:      # W8B: the RENAME / OK row within 1 px both edges (v7: bottom up to -1.69) but g 26
                assert Y == SL.basewin_okrow_v(g)[2] and abs(Y - y * g / 16) <= 1, ((x, y), g, Y)
                assert abs(Y + H - (y + h) * g / 16) <= 1 or g == 26, ((x, y), g, Y, H)   # v2: v7's -1.12 kept
            elif y == 234:      # W8R (F52): RESOURCE / SUPPORT / PSYCH within 1 px both edges (v8: bottom up to
                #                 -1.62) but g 31 (-1.12 kept: its side and bottom channels are already equal)
                assert Y == SL.basewin_rsp_row_v(g) and abs(Y - y * g / 16) <= 1, ((x, y), g, Y)
                assert abs(Y + H - (y + h) * g / 16) <= 1 or g == 31, ((x, y), g, Y, H)
            else:
                assert Y == pt(y, g), ((x, y), g, Y)
        twins = [((27, 33, 163, 187), (563, 33, 699, 257)), ((30, 36, 160, 56), (566, 36, 696, 56)),
                 ((30, 57, 160, 184), (566, 57, 696, 254))]
        S = SL.basewin_rail_axis_sum(g)
        for lt, rt in twins:
            lb, rb = SL.basewin_box_draw_rect(*lt, g), SL.basewin_box_draw_rect(*rt, g)
            assert lb[2] - lb[0] == rb[2] - rb[0] and lb[0] + rb[2] == lb[2] + rb[0] == S - 1, (lt, g)
        assert S == pt(726, g)
    assert {rc for rc, g in over} <= {(346, 376, 696, 438), (169, 355, 696, 375), (298, 263, 697, 325),
                                      (169, 326, 696, 346)}, over
    assert not {g for rc, g in over} & {18, 20, 21, 30, 40}, "1600x900 / 1280x1024 / 1680x1050 / 1440 / 4K: none"
    assert SL.basewin_rail_axis_sum(16) == 726 and SL.basewin_box_draw_rect(563, 33, 699, 257, 16) == \
        (563, 33, 699, 257)


# ============================================================================== 2. the real image
@pytest.fixture(scope="module")
def sym():
    import mirror_pairs_emu as MPE
    return MPE.symtab()


@pytest.fixture(scope="module")
def rig_new(baked_exe, sym):
    import basewin_mirror_emu as BME
    return BME.Rig(str(baked_exe), sym)


@pytest.fixture(scope="module")
def rig_pristine(bak_path, sym):
    import basewin_mirror_emu as BME
    return BME.Rig(str(bak_path), sym)


@pytest.fixture(scope="module")
def pristine16(rig_pristine):
    return rig_pristine.screen(1024, 768)


def _check(m, g):
    import basewin_mirror_emu as BME
    k = K(g)
    for row in ("tab", "fac", "nrg"):
        L, R = m[row]["L"], m[row]["R"]
        assert L["see"] == R["see"] == 0, (g, row, "see-through column")
        assert L["con_w"] == R["con_w"] == k, (g, row, "console borders K | K", L["con_w"], R["con_w"])
        assert L["ch0"] == R["ch0"], (g, row, "console -> tab frame / panel", L["ch0"], R["ch0"])
        assert L["w0"] == R["w0"] == k, (g, row)
        if row != "tab":
            assert L["ch1"] == R["ch1"], (g, row, "panel -> inner box", L["ch1"], R["ch1"])
            assert L["w1"] == R["w1"] == k, (g, row)
        for side in (L, R):
            assert not side["channel_colours"] & BME.STROKES, (g, row, "a stroke colour inside a channel",
                                                               side["channel_colours"])
    l, _, r, _ = SL.basewin_console_frame_rect(g)
    assert m["fac"]["L"]["con_at"] == l and m["fac"]["R"]["con_at"] == r
    gaps = m["tab_gaps"]
    assert gaps == gaps[::-1] and min(gaps) >= 1, (g, gaps)
    assert m["sub_gaps"][0] == m["sub_gaps"][1] and m["sub_sum"] == SL.basewin_rail_axis_sum(g)
    kids = m["kids"]
    fb, sb = kids[BME.FAC_BTN], kids[BME.FAC_SB]
    assert fb[0] + fb[2] == SL.basewin_rim_x(693, g) == sb[0] + sb[2], "facilities button / bar on the list rim"
    assert kids[0x6BA848][2] == SL.basewin_gov_w(g)


@pytest.mark.parametrize("g", E2E_G)
def test_e2e_every_g(rig_new, pristine16, g):
    import basewin_mirror_emu as BME
    w, h = SCREENS.get(g, (64 * g, 48 * g))
    gg, canvas, kids = rig_new.screen(w, h)
    assert gg == g
    _check(BME.measure(canvas, g, kids), g)
    # the console -> panel channels on EVERY row between the console's top and bottom strokes: no stroke colour
    # (audit-w5A's g = 17 finding: a console-coloured column inside the energy panels from a clip opened too wide)
    k, lx, a = K(g), SL.basewin_rail_left_extent(g), SL.basewin_rail_anchor(g)
    rp = SL.basewin_box_draw_rect(563, 33, 699, 257, g)[2]
    body = canvas[k:canvas.shape[0] - 2 * k]
    for cols in (body[:, lx + k:pt(27, g)], body[:, rp + 1:a - k]):
        assert cols.shape[1] > 0 and not np.isin(cols, sorted(BME.STROKES)).any(), (g, "stroke colour in a channel")
    res, off, corner, matched, unmatched = BME.mirror_census(pristine16[1], canvas, g)
    assert not off, (g, off[:8])
    assert matched > 1000, (g, matched)     # (unmatched: vanilla transitions inside the 1-px stripe textures whose device
    #                                         stripe phase differs -- not edges; the walk above pins the edges themselves)
    assert len(corner) <= 12, (g, corner)
    # F42: every hollow / fill centre box's outer strokes on its half-open law footprint (no +1 overreach): the
    # stroke colour at the drawn first / last column on the box's middle row, and not one column beyond it
    for rc, col in FOOTPRINT_BOXES:
        L, T, R, B = SL.basewin_box_draw_rect(*rc, g)
        y = (T + B) // 2
        assert canvas[y, L] == col and canvas[y, R] == col, (g, rc, int(canvas[y, L]), int(canvas[y, R]))
        assert canvas[y, L - 1] != col and canvas[y, R + 1] != col, (g, rc, "a stroke one column outside the footprint")
    # v5: the stroke-thickness census -- every census box, every side, exactly K px of its vanilla stroke colour
    res, bad = BME.stroke_census(pristine16[1], canvas, g)
    assert len(res) == 4 * len(BME.CENSUS_BOXES + [BME.TAB_FRAME]) and not bad, (g, bad)
    _check_w7h(rig_new, canvas, kids, g)
    _check_w8b(pristine16[1], canvas, kids, BME.measure(canvas, g, kids), g)


#: W8R (F52): the g where the RESOURCE / SUPPORT / PSYCH row's channel below == its side channel (basewin_rsp_row_v;
#: not 19 / 29 / 35 -- no equal layout within 1 px)
RSP_CHANNELS_EQUAL = set(range(17, 41)) - {19, 29, 35}
#: W7H: every BaseWin child BaseWin_init builds, native (x, y, w, h)
CHILDREN = {0x6B7B18: (30, 7, 112, 20), 0x6B8664: (144, 7, 112, 20), 0x6C1940: (258, 7, 20, 20),
            0x6BA848: (280, 7, 166, 20), 0x6C248C: (448, 7, 20, 20), 0x6B91B0: (470, 7, 112, 20),
            0x6B9CFC: (584, 7, 112, 20), 0x6BBEE0: (169, 234, 128, 20), 0x6BB394: (299, 234, 128, 20),
            0x6BCA2C: (429, 234, 128, 20), 0x6B5934: (131, 449, 238, 20), 0x6B4DE8: (381, 449, 238, 20),
            0x6C3B24: (569, 231, 124, 20)}


def _check_w7h(rig, canvas, kids, g):
    """W7H items 1 and 2 on the real image:
      1. the tab frame's top / bottom strokes (palette 99) in GOVERNOR's column: K rows each, on basewin_tabframe_top /
         basewin_tabframe_bottom (law basewin_tab_row_v), the visible channels above and below the buttons equal;
      2. every child on basewin_child_rect; RENAME / OK mirrored in the row frame (box -> RENAME == OK -> box);
         the chevrons square D = fl(20g/16), every chevron edge within 1 px of vanilla x g/16."""
    import basewin_mirror_emu as BME
    k = K(g)
    for o, n in CHILDREN.items():
        assert kids[o] == SL.basewin_child_rect(*n, g), (g, hex(o), kids[o])
    gx, gy, gw, gh = kids[0x6BA848]
    col = canvas[:, gx + gw // 2]
    st = [y for y in range(0, gy + gh + 4 * k + 4) if col[y] == BME.TAB]
    top, bot = [y for y in st if y < gy], [y for y in st if y >= gy + gh]
    assert top == list(range(SL.basewin_tabframe_top(g), SL.basewin_tabframe_top(g) + k)), (g, top)
    assert len(bot) == k and bot[-1] == SL.basewin_tabframe_bottom(g), (g, bot)
    assert gy - (top[-1] + 1) == bot[0] - (gy + gh), (g, "tab frame channels above / below the buttons")
    ren, ok = kids[0x6B5934], kids[0x6B4DE8]
    L, _, R, _ = SL.basewin_okrow_box_draw_rect(g)
    assert ren[0] - (L + k) == (R - k + 1) - (ok[0] + ok[2]) and ren[2] == ok[2], (g, ren, ok, L, R)
    for o, (x, _y, w, _h) in ((0x6C1940, CHILDREN[0x6C1940]), (0x6C248C, CHILDREN[0x6C248C])):
        X, _Y, W, H = kids[o]
        assert W == H == SL.popup_scale_floor(20, g)
        assert abs(X - x * g / 16) <= 1 and abs(X + W - (x + w) * g / 16) <= 1, (g, hex(o), X, W)


def _law_gaps(kids_xw, left, right):
    edges = [left] + sum(([x, x + w] for x, w in kids_xw), []) + [right]
    return [edges[i + 1] - edges[i] for i in range(0, len(edges), 2)]


def _check_w8b(c16, canvas, kids, m, g):
    """W8B (the user's F48 / F49 / F50) on the real image -- the gaps a player sees, between the real child windows
    and the strokes walked on the final canvas:
      F49  the tab row's eight gaps (measure: the frame strokes walked on the tab row, the real windows) == the law's
           (basewin_tab_row_h through basewin_child_rect v8); equal / remainder in one mirrored pair as the law says;
      F50  panel stroke -> RESOURCE -> SUPPORT -> PSYCH -> panel stroke, the panel's stroke colour walked on the
           buttons' middle row: == the law, a == b (no E2E g is 18 / 34);
      F48  the RENAME / OK frame's stroke rows walked in RENAME's middle column: the channels above and below the
           buttons equal, == the tab row's channel, the frame on basewin_okrow_box_draw_rect;
      F52  (W8R) the middle panel's bottom stroke walked down each RESOURCE / SUPPORT / PSYCH column: K rows from
           basewin_rsp_panel_stroke_b, the channel above it == the law's (basewin_rsp_row_v) and == the row's side
           channel wherever the law equalises them, one value for all three buttons."""
    k = K(g)
    tab = [kids[o] for o in (0x6B7B18, 0x6B8664, 0x6C1940, 0x6BA848, 0x6C248C, 0x6B91B0, 0x6B9CFC)]
    law_tab = _law_gaps([(SL.basewin_child_rect(x, 7, w, 20, g)[0], SL.basewin_child_rect(x, 7, w, 20, g)[2])
                         for x, w in ((30, 112), (144, 112), (258, 20), (280, 166), (448, 20), (470, 112), (584, 112))],
                        pt(27, g) + k, SL.basewin_tabframe_right(g) - k + 1)
    assert m["tab_gaps"] == law_tab, (g, m["tab_gaps"], law_tab)
    half = law_tab[:4]
    assert max(law_tab) - min(law_tab) <= 1 and law_tab == law_tab[::-1], (g, law_tab)
    assert len(set(half)) == 1 or half[1] == half[2] == half[3] or half[0] == half[1] == half[2] or \
        SL.basewin_tab_row_h(g) == SL.basewin_tab_row_h_v7(g), (g, law_tab)
    # F50: the panel's stroke colour (the pristine middle panel's left stroke on the RSP row) walked on the device row
    rsp = [kids[o] for o in (0x6BBEE0, 0x6BB394, 0x6BCA2C)]
    col = int(c16[244, 166])
    y = rsp[0][1] + rsp[0][3] // 2
    row = canvas[y]
    lstroke = max(x for x in range(pt(150, g), rsp[0][0]) if row[x] == col)
    rstroke = min(x for x in range(rsp[2][0] + rsp[2][2], pt(575, g)) if row[x] == col)
    gaps = _law_gaps([(x, w) for x, _y, w, _h in rsp], lstroke + 1, rstroke)
    p = SL.basewin_box_draw_rect(166, 33, 560, 257, g)
    assert (lstroke, rstroke) == (p[0] + k - 1, p[2] - k + 1), (g, lstroke, rstroke, p)
    assert gaps == gaps[::-1] and (gaps[0] == gaps[1] or g in (18, 34)), (g, gaps)   # 18 / 34: no equal layout <= 1 px
    law = _law_gaps([(x, w) for x, _y, w, _h in (SL.basewin_child_rect(x, 234, 128, 20, g) for x in (169, 299, 429))],
                    p[0] + k, p[2] - k + 1)
    assert gaps == law, (g, gaps, law)
    # F52 (W8R): the channel below the row to the panel's bottom stroke, walked down each button's middle column
    sb, hb = SL.basewin_rsp_panel_stroke_b(g), SL.popup_scale_floor(20, g)
    below = set()
    for x, yb, w, hh in rsp:
        cc = canvas[:, x + w // 2]
        st = [yy for yy in range(yb + hh, sb + 2 * k + 2) if cc[yy] == col]
        assert st[:k] == list(range(sb, sb + k)) and yb == SL.basewin_rsp_row_v(g) and hh == hb, (g, x, st[:4], yb)
        below.add(st[0] - (yb + hh))
    assert below == {sb - SL.basewin_rsp_row_v(g) - hb}, (g, below)
    if g in RSP_CHANNELS_EQUAL:
        assert below == {gaps[0]}, (g, below, gaps)
    # F48: the RENAME / OK frame's stroke colour walked in RENAME's middle column
    ren = kids[0x6B5934]
    fcol = int(c16[446, 200])
    colm = canvas[:, ren[0] + ren[2] // 2]
    L, T, R, B = SL.basewin_okrow_box_draw_rect(g)
    top = [yy for yy in range(T - 3, ren[1]) if colm[yy] == fcol]
    bot = [yy for yy in range(ren[1] + ren[3], B + 4) if colm[yy] == fcol]
    assert top == list(range(T, T + k)) and bot == list(range(B - k + 1, B + 1)), (g, top, bot, T, B)
    ct, cb = ren[1] - (top[-1] + 1), bot[0] - (ren[1] + ren[3])
    tT, _tB, tt = SL.basewin_tab_row_v(g)
    assert ct == cb == tt - tT - k, (g, ct, cb)
    # v2 (audit-w8B C1): the frame's neighbour gaps on the canvas -- the energy-allocation panel's bottom stroke above
    # (its stroke colour walked up the RENAME | OK gap's column) and the window bottom below -- == the law's
    ok = kids[0x6B4DE8]
    gcol = canvas[:, (ren[0] + ren[2] + ok[0]) // 2]
    pcol = int(c16[440, 400])
    last = max(yy for yy in range(T - 12 * k - 12, T) if gcol[yy] == pcol)
    assert last + 1 == pt(441, g) and canvas.shape[0] == pt(490, g), (g, last, canvas.shape)
    e = SL.basewin_okrow_v_errors(T, B + 1, ren[1], g)
    assert all(abs(e[n]) <= 1 for n in ("above", "aboveL", "below")), (g, e)


@pytest.mark.parametrize("g", sorted(ROWS_SCREENS))
def test_e2e_rows(rig_new, pristine16, g):
    """W8B v2 (audit-w8B I2): the button rows on the real image at the user's other resolutions -- 1600x900,
    1280x1024, 2560x1440, 4K: every child on basewin_child_rect, the three rows' gaps / channels / neighbour gaps
    (_check_w8b) and the RENAME / OK frame's strokes K on its footprint.  COST: one screen each (~10 s; 4K ~25 s)."""
    import basewin_mirror_emu as BME
    w, h = ROWS_SCREENS[g]
    gg, canvas, kids = rig_new.screen(w, h)
    assert gg == g
    for o, n in CHILDREN.items():
        assert kids[o] == SL.basewin_child_rect(*n, g), (g, hex(o), kids[o])
    _check_w8b(pristine16[1], canvas, kids, BME.measure(canvas, g, kids), g)
    res, bad = BME.stroke_census(pristine16[1], canvas, g, boxes=[BME.OK_FRAME, BME.TAB_FRAME])
    assert len(res) == 8 and not bad, (g, bad)


@pytest.fixture(scope="module")
def faces16(rig_pristine):
    """The pristine 1024 button faces, every BaseWin FlatButton, states 0 / 1 / 2 (the native strokes)."""
    import basewin_mirror_emu as BME
    rig_pristine.screen(1024, 768)
    return rig_pristine.buttons(BME.BTNS)


@pytest.mark.parametrize("g", (24, 40))
def test_e2e_button_strokes_in_every_state(rig_new, faces16, g):
    """W7H item 3 (the F39 class on the base screen): every BaseWin 9-slice face (the tab row, GOVERNOR,
    RESOURCE / SUPPORT / PSYCH, RENAME / OK, the facilities button) in states 0 / 1 / 2 through the real draw chain
    (thunk_basewin_btnzoom .. t_sbt_zoom): each 1-px vanilla stroke comes out the same width on the left and the
    right and on the top and the bottom, within 1 px of g/16, and no face leaves a key row / column under its art
    (the child heights stay fl(20g/16)).  g 24 / 40 are the centre map's ties (v6: 1 | 2 and 2 | 3 every state).
    The chevrons keep their coverage filter (user-approved; not a 1-px NN stroke) -- only the key margins apply.
    COST: one screen per g (~10 s at g 24, ~25 s at 4K) + 39 faces."""
    import basewin_mirror_emu as BME
    w, h = SCREENS.get(g, (64 * g, 48 * g))
    gg, _canvas, _kids = rig_new.screen(w, h)
    assert gg == g
    faces = rig_new.buttons(BME.BTNS)
    for (b, s), p in faces.items():
        st, margins = BME.face_strokes(p, faces16[(b, s)])
        assert margins == (0, 0), (g, hex(b), s, margins)
        if b in BME.CHEVRONS:
            continue
        for a, c in (("L", "R"), ("T", "B")):
            if a in st or c in st:
                assert st.get(a) == st.get(c) and len(st[a]) == 1, (g, hex(b), s, st)
                assert abs(st[a][0] - g / 16) < 1, (g, hex(b), s, st)


@pytest.fixture(scope="module")
def support16(rig_pristine):
    return rig_pristine.screen(1024, 768, farm_mode=3)[1]


@pytest.mark.parametrize("g", (16, 25))
def test_e2e_support_view(rig_new, pristine16, support16, g):
    """The SUPPORT view (draw_farm -> BaseWin_draw_support, whose full-panel fill @0x408EF2 shares thunk_bw_fill2):
    the stroke census against the pristine image's own SUPPORT view (vanilla paints the farm panel's frame over --
    want 0 there, K everywhere else); g = 16 pixel-identical to it.  (g = 25: K = 2, the case audit-w5A v4 found.)"""
    import basewin_mirror_emu as BME
    w, h = SCREENS.get(g, (64 * g, 48 * g))
    gg, canvas, kids = rig_new.screen(w, h, farm_mode=3)
    assert gg == g
    if g == 16:
        assert np.array_equal(canvas, support16)
    res, bad = BME.stroke_census(pristine16[1], canvas, g, ref16=support16)
    assert not bad, (g, bad)
    panel = [v for (box, side), v in res.items() if box == (166, 33, 560, 257)]
    assert panel and all(want == 0 for want, runs in panel), panel


def test_e2e_g16_is_pristine(rig_new, rig_pristine, pristine16):
    """1024x768: the bake's base screen is the pristine image's, pixel for pixel, child window for child window."""
    import basewin_mirror_emu as BME
    g1, c1, k1 = rig_new.screen(1024, 768)
    g0, c0, k0 = pristine16
    assert g1 == g0 == 16 and np.array_equal(c1, c0)
    assert k1 == k0
    m = BME.measure(c0, 16, k0)
    assert m["tab_gaps"] == [2] * 8
    assert (m["fac"]["L"]["ch0"], m["fac"]["R"]["ch0"], m["fac"]["L"]["ch1"], m["fac"]["R"]["ch1"]) == (3, 3, 2, 2)
    res, off, corner, matched, unmatched = BME.mirror_census(c0, c0, 16)
    assert not off and not corner and matched > 2000 and not unmatched
    # W7H: the button faces, byte for byte
    f1 = rig_new.buttons(BME.BTNS)
    rig_pristine.screen(1024, 768)
    f0 = rig_pristine.buttons(BME.BTNS)
    assert all(np.array_equal(f1[key], f0[key]) for key in f0)
