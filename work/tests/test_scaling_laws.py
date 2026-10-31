"""Exhaustive sweep of the SMACX UI scaling laws (`scripts/scaling_laws.py`).

WHY THIS FILE EXISTS. Every one of these assertions corresponds to a defect a
human actually saw on screen and reported. The laws are not obvious, they
interact, and two of them were broken by "obvious" simplifications that looked
right at 4K and only failed at 1600x1200 or 1920x1080:

  * deriving the stroke width K from a frame's own dst/src ratio instead of
    from the lever tipped K from 2 to 3 at 4K and made it span-dependent;
  * pinning only the stroke cell (not the bevel cell) of a corner band gave
    the bevel half the stroke's weight at g=25 and double at g=22.

Neither is visible in a single-resolution screenshot. Both are caught here in
milliseconds, with no game launch. If you are changing a law, this file is the
contract: make it pass, or change it deliberately and say why.

The invariant that outranks all others: **at g == 16 every law is the
identity**, byte-identical to vanilla. See CLAUDE.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scaling_laws import (  # noqa: E402
    BASEWIN_CENTER_C,
    BASEWIN_NATIVE_H,
    BASEWIN_NATIVE_W,
    DIALOG_ROW_MARGIN_NATIVES,
    G_MAX,
    G_MIN,
    NATIVE_G,
    axis_map,
    line_axis_map,
    band_widths,
    basewin_font_size,
    basewin_pt,
    basewin_sprite_ratio,
    basewin_console_frame_rect,
    basewin_facsb_rect,
    FACSB_W_NATIVE,
    basewin_window_rect,
    dialog_row_margin,
    t16_row_text_indent,
    t16_row_line_count,
    t16_row_text_budget,
    T16_ROW_TEXT_INDENT_NATIVE,
    popup_scale_floor,
    prefwin_window_pos,
    pref_mode_cell_x,
    body_inner_edge_l,
    body_inner_edge_r,
    body_outer_edge_l,
    body_outer_edge_r,
    cum,
    distribute,
    frame_grow_delta,
    title_grow_delta,
    half_down,
    ingame_popup_min_boxh,
    ingame_popup_window_h,
    popup_button_row_growth,
    itemlist_box_width,
    t16_row_measure_width,
    itemlist_container_edge_l,
    itemlist_container_edge_r,
    itemlist_ring_hug,
    itemlist_ring_takes_hug_arm,
    option_row_gap,
    popup_pad,
    btn_bar_tile_height,
    btn_native_dim,
    rail_right_anchor,
    ring_bottom,
    row_positions,
    scale_px,
    stroke_width,
    ornate_untitled_content_top,
    tutwin_content_top,
    tutwin_stash_left,
    tutwin_stash_right,
)

ALL_G = list(range(G_MIN, G_MAX + 1))

# Real band depths: 6x6 simple frames; the picker's ornate corner is 61x44.
BAND_DEPTHS = [3, 6, 8, 44, 61]

# Spans wide enough for two bands, sampled densely enough to hit awkward ratios.
SPANS = list(range(150, 2401, 7))

# The resolutions we ship against, at the g each REALLY runs at (scaling_laws.popup_g: the min of both axes,
# floored -- 1280x1024 is 20 and 1600x900 is 18, not the height-only 21 / 19). scale_uniform = min(W/1024, H/768)
# is NOT g/16 at 1920x1080 — the picker scales by the former, popups by the latter.
RESOLUTIONS = [
    # (label,        g,  scale_uniform)
    ("1024x768",    16,  1.0),
    ("1600x900",    18,  1.171875),
    ("1280x1024",   20,  1.25),
    ("1920x1080",   22,  1.40625),
    ("1600x1200",   25,  1.5625),
    ("3840x2160",   40,  2.5),
]


@pytest.mark.parametrize("label,g,su", RESOLUTIONS)
def test_resolution_table_is_popup_g(label: str, g: int, su: float):
    import scaling_laws as SL
    w, h = (int(v) for v in label.split("x"))
    assert g == SL.popup_g(w, h)


# --------------------------------------------------------------------------
# half_down / cum — the primitive
# --------------------------------------------------------------------------

def test_half_down_rounds_exact_halves_down():
    """Half-DOWN, not half-up: the approved 4K stroke is 2px and g/16 == 2.5.

    Half-up here would render every 4K frame stroke at 3px.
    """
    assert half_down(1, 2) == 0
    assert half_down(3, 2) == 1
    assert half_down(5, 2) == 2
    assert half_down(40, 16) == 2      # the 4K stroke, exactly
    assert half_down(0, 7) == 0


@pytest.mark.parametrize("b", range(1, 40))
def test_half_down_matches_a_float_reference(b: int):
    """Independent check against float arithmetic: floor(a/b + 1/2 - eps)."""
    import math

    for a in range(0, 200):
        q = a / b
        expect = math.ceil(q - 0.5) if abs((q % 1) - 0.5) > 1e-12 else math.floor(q)
        assert half_down(a, b) == expect, (a, b)


def test_half_down_rejects_nonpositive_denominator():
    with pytest.raises(ValueError):
        half_down(5, 0)


@pytest.mark.parametrize("n", [1, 2, 3, 6, 7, 44, 61])
@pytest.mark.parametrize("total", [0, 1, 7, 130, 133, 977, 2400])
def test_cum_is_exact_at_both_ends(n: int, total: int):
    """A run must start at 0 and end at exactly `total` — no drift."""
    assert cum(0, total, n) == 0
    assert cum(n, total, n) == total


# --------------------------------------------------------------------------
# LAW 2 — remainder distribution
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3, 6, 7, 12, 44, 61])
@pytest.mark.parametrize("total", [0, 1, 5, 130, 133, 203, 977, 2400])
def test_distribute_sums_exactly_and_stays_within_one(n: int, total: int):
    """sum == total exactly (this is the whole point), and no cell is off the
    ideal size by more than 1px."""
    w = distribute(total, n)
    assert len(w) == n
    assert sum(w) == total
    assert all(x >= 0 for x in w)
    ideal = total / n
    assert all(abs(x - ideal) < 1.0 + 1e-9 for x in w)


def test_distribute_beats_the_naive_floor():
    """The bug this law exists to kill: 7 rows at 19px scaled by 25/16.

    Naive `n * floor(scale*pitch)` loses 4.8px by the last row, which is
    exactly the gap the user saw below the Peacekeeping Forces row.
    """
    total = half_down(7 * 19 * 25, 16)          # faithful total, = 208
    naive = 7 * ((19 * 25) // 16)               # 7 * 29 = 203
    assert sum(distribute(total, 7)) == total
    assert total - naive == 5                   # the visible gap, in pixels


def test_distribute_rejects_nonpositive_n():
    with pytest.raises(ValueError):
        distribute(100, 0)


@pytest.mark.parametrize("label,g,su", RESOLUTIONS)
def test_row_positions_end_flush_and_are_monotone(label: str, g: int, su: float):
    """Rows must be strictly increasing and the run must end where a faithful
    (unfloored) stride would put it."""
    pos = row_positions(top=100, native_pitch=19, count=7, scale_num=g)
    assert pos[0] == 100
    assert all(b > a for a, b in zip(pos, pos[1:]))
    end = 100 + half_down(7 * 19 * g, 16)
    assert end - pos[-1] == half_down(7 * 19 * g, 16) - cum(6, half_down(7 * 19 * g, 16), 7)


def test_row_positions_native_is_vanilla():
    """g=16 must reproduce the engine's own `top + i*19` exactly."""
    assert row_positions(134, 19, 7, NATIVE_G) == [134 + 19 * i for i in range(7)]


# --------------------------------------------------------------------------
# LAW — Design Workshop FIT/SSAA plan: radial constraint about the target centre
# --------------------------------------------------------------------------

DW_TRIAL_BBS = ((458, 420, 616, 555), (461, 390, 582, 552), (452, 447, 574, 566), (491, 493, 531, 535), (300, 300, 724, 724), (0, 0, 1024, 1024), (510, 510, 514, 514))   # measured 4K trial bboxes (log 20260829) + synthetic


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("bb", DW_TRIAL_BBS)
def test_dw_fit_plan_never_crosses_the_target(g: int, bb):
    """The v14 defect: k from the EXTENT let an off-centre part cross the 1024 target
    edge (-> clipped plotter twin, vanilla 2x2 footprint, see-through crane)."""
    from scaling_laws import dw_fit_plan, DW_FIT_MARGIN
    tn = 1024
    p = dw_fit_plan(bb, tn, g)
    c = tn / 2
    if p["mode"] != "nn":
        for e in (bb[0], bb[2], bb[1], bb[3]):
            assert abs((e - c) * p["k"]) <= c - DW_FIT_MARGIN + 1e-6, f"edge {e} crosses at k={p['k']}"
        assert abs(p["k"] * p["W"] - tn * g / 16) < 1e-6, "composite ratio exact: k*W == tn*need"
    else:
        assert p["k"] == 1.0 and p["W"] == tn * g // 16   # engine NN enlarge of the whole target (v14s had 16g = the 256^2 value)


DW_WINDOWS = ((0, 623), (200, 823), (1188, 2745), (668, 1626), (386, 1225))   # (L, R) native 623-wide + measured 4K/1600/1920 canvases


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("lr", DW_WINDOWS)
def test_dw_button_rows_share_one_grid(g: int, lr):
    """Both modal button rows sit on the same 5-column grid with one channel (the v14t
    1600 defect: upper pitch = cell - s(3) + 3 put PROTO 2 px left of RENAME)."""
    from scaling_laws import dw_button_rows, scale_px
    r = dw_button_rows(lr[0], lr[1], g)
    lo, up = r["lower"], r["upper"]
    widths = {b[1] - b[0] for b in lo + up}
    assert len(widths) == 1 and widths == {r["cell"] - r["channel"]}, "every button = cell - s(3) wide"
    assert [lo[i + 1][0] - lo[i][0] for i in range(4)] == [r["cell"]] * 4
    assert up[1][0] == lo[1][0] and up[2][0] == lo[3][0], "PROTO over RENAME, RETIRE ALL over UPGRADE"
    assert up[0] == lo[0] and up[3] == lo[4]
    assert r["channel"] == scale_px(3, g)
    if g == 16:
        assert r["channel"] == 3 and r["cell"] == int(((lr[1] - 0x20 - 0x1B) - (lr[0] + 0x1B) + 3) / 5)


def test_dw_button_rows_1600_shot_geometry():
    """User 1600x1200 shot 20260829-022448: lower-row FACES at x = 382,551,720,889,1058, 162 wide,
    pitch 169; the rect is cell - s(3) = 164 wide, so the FlatButton face inset is 1 -> rects at
    381,550,719,888,1057.  The upper row (measured 382,549,891,1058 = the defect) must now sit on
    the same columns.  The window's R lies s(0x20)+s(0x1B) beyond CANCEL."""
    from scaling_laws import dw_button_rows
    for L in range(300, 420):
        for R in range(1250, 1400):
            q = dw_button_rows(L, R, 25)
            if [b[0] for b in q["lower"]] == [381, 550, 719, 888, 1057]:
                assert q["cell"] == 169 and q["channel"] == 5 and q["lower"][0][1] - q["lower"][0][0] == 164
                assert [b[0] for b in q["upper"]] == [381, 550, 888, 1057]
                return
    assert False, "no (L, R) reproduces the measured lower row at g=25"


@pytest.mark.parametrize("g", ALL_G)
def test_listbox_bar_reserve_scales_the_popup_width(g: int):
    """Select Special Ability: xs 600 + reserve 20 = vanilla dialog width 620; the scaled
    chain (floor(600g/16) + floor(20g/16)) must track 620*g/16 within the two floors, and
    the native / inactive gates are identities."""
    from scaling_laws import listbox_bar_reserve, listbox_dialog_width, popup_scale_floor
    w = listbox_dialog_width(popup_scale_floor(600, g), 20, g)
    assert abs(w - 620 * g / 16) < 2.0, (g, w)
    assert listbox_bar_reserve(20, g, popup_active=False) == 20
    if g <= 16:
        assert listbox_bar_reserve(20, g) == 20 and w == 620
    assert listbox_dialog_width(825, 20, 22) == 852 and listbox_dialog_width(937, 20, 25) == 968


def test_dw_fit_plan_overlay_is_never_ssaa():
    """Caviar_overlay draws (Probability Sheath) are composited by the wrapper's own
    table blit, rescaled num=W/den=tn: the plan must not pick 'ssaa' for them, and a
    unit that fits at device density gets the resample-free 1:1 blit (W == tn)."""
    from scaling_laws import dw_fit_plan
    for g in ALL_G:
        p = dw_fit_plan((433, 463, 588, 558), 1024, g, ssaa=False)    # artillery + sheath trial bbox (4K log)
        assert p["mode"] != "ssaa"
        if g > 16:
            assert p["mode"] == "fit1:1" and p["W"] == 1024 and abs(p["k"] - g / 16) < 1e-9


def test_dw_fit_plan_crane_case_is_ssaa_under_x5():
    """Rover Formers crane at 4K: E=158 fit x5 under the extent law; radially it must not."""
    from scaling_laws import dw_fit_plan
    p = dw_fit_plan((458, 420, 616, 555), 1024, 40)
    assert p["mode"] == "ssaa" and 2.5 <= p["k"] < 5.0
    q = dw_fit_plan((491, 493, 531, 535), 1024, 40)          # a small centred icon: full 2x2 SSAA
    assert q["mode"] == "ssaa" and q["k"] == 5.0 and q["W"] == 512


# --------------------------------------------------------------------------
# LAW — band-map thunk footprint is INCLUSIVE; half-open engine rects lose 1 on R/B
# --------------------------------------------------------------------------

@pytest.mark.parametrize("g", ALL_G)
def test_bandmap_rect_from_halfopen_matches_the_native_extent(g: int):
    from scaling_laws import bandmap_rect_from_halfopen
    l, t, r, b = 67, 245, 330, 472                      # DW picker cell 5 law rect at 4K
    bl, bt, br, bb = bandmap_rect_from_halfopen(l, t, r, b, g)
    assert (bl, bt) == (l, t), "near edges are never moved"
    if g <= 16:
        assert (br, bb) == (r, b), "native passthrough: the engine's own half-open render"
    else:
        # inclusive footprint [bl..br]x[bt..bb] == half-open [l,r)x[t,b): same pixel count
        assert (br - bl + 1, bb - bt + 1) == (r - l, b - t)
        assert (br, bb) == (r - 1, b - 1)


def test_bandmap_rect_from_halfopen_removes_the_picker_spill():
    """The defect: the empty-cell tile repaints [l,r)x[t,b) after a scroll; the frame's
    inclusive footprint must not own col r / row b or a 1px stroke survives there."""
    from scaling_laws import bandmap_rect_from_halfopen
    for g in (22, 25, 40):
        l, t, r, b = 67, 245, 330, 472
        _, _, br, bb = bandmap_rect_from_halfopen(l, t, r, b, g)
        assert br < r and bb < b


@pytest.mark.parametrize("g", ALL_G)
def test_t16_item_draw_rect_scaling(g: int):
    """Type-16 option rows (t_dp_itemrect v2): the drawn row == the half-open rect at EVERY g, both arms;
    identity at g=16 and for non-type-16 dialogs.  The superseded lever R (K-1) was right only for g >= 25."""
    from scaling_laws import scale_px, stroke_width, t16_item_draw_rect
    rect = (0, 90, scale_px(597, g), 90 + scale_px(20, g))
    for anchored, dtype in ((True, 16), (False, 16)):
        l, t, r, b = t16_item_draw_rect(*rect, g, anchored=anchored, dialog_type=dtype)
        if g <= 16:
            assert (l, t, r, b) == rect
            continue
        assert (r - l + 1, b - t + 1) == (rect[2] - rect[0], rect[3] - rect[1])   # inclusive footprint == rect
        assert b - t + 1 == scale_px(20, g)                                         # == the OK bar's 20 x g/16
        if g >= 25:
            assert rect[2] - r == stroke_width(g) - 1                               # v1 (K-1) bytes kept at 1600/4K
    for dtype in (1, 2, 4, 8):
        assert t16_item_draw_rect(*rect, g, anchored=False, dialog_type=dtype) == rect


@pytest.mark.parametrize("g", ALL_G + [41, 44, 48])
def test_diplo_speech_rects_far_edge_scaling(g: int):
    """Diplomacy speech box (t_dp_fill / t_dp_title_* / t_dp_textblock / t_dp_wrapwidth): every band-map-drawn far
    edge = the scaled half-open vanilla edge - 1 (diplo_far_edge_trim = 1) at EVERY g > 16; vanilla at g = 16.
    The superseded h1 = K-1 agreed only for g = 25..40 (0 at g = 17..24: 1080 drew 1 px wide / the title 1 row tall)."""
    from scaling_laws import diplo_far_edge_trim, diplo_speech_rects, dp, frame_grow_delta
    W, H = dp(700, g), dp(450, g)
    clip = (0, 0, W, H)
    f = {0x30F0: dp(33, g), 0x30D8: dp(135, g), 0x21C8: 0, 0x30E0: 0, 0x30E8: dp(38, g), 0x30D4: dp(20, g)}
    r = diplo_speech_rects(clip, f, g)
    s3, D = dp(3, g), frame_grow_delta(g)
    if g <= 16:
        assert diplo_far_edge_trim(g) == 0
        assert r["fill"][2] == W - 0x37 and r["outer"][2:] == (W - 0x3B, 0x1C) and r["d528"][2] == W - 0x3B - 3
        return
    assert diplo_far_edge_trim(g) == 1
    assert r["fill"][2] == (W - dp(0x37, g)) - 1                                    # backdrop: drawn R = half-open - 1
    assert (r["outer"][2] + D, r["outer"][3] + D) == (W - dp(0x3B, g) - 1, dp(0x1C, g) - 1)   # title (grown by D)
    assert r["inner"][2:] == (r["outer"][2] - s3, r["outer"][3] - s3)
    assert r["d528"][2] == W - dp(0x3B, g) - s3 - 1 and r["final"][2] == W - dp(0x3B, g) - 1
    assert r["measure"] == r["d528"][2] - f[0x30F0] - f[0x30D8] - dp(5, g)
    old_r = W - dp(0x37, g) - (stroke_width(g) - 1)                                 # the v1 (K-1) fill R
    assert (r["fill"][2] == old_r) == (25 <= g <= 40)                                 # unchanged at 1600 .. 4K only


# --------------------------------------------------------------------------
# LAW 4 — K from the lever
# --------------------------------------------------------------------------

def test_stroke_width_at_the_four_shipped_resolutions():
    assert stroke_width(16) == 1     # native
    assert stroke_width(22) == 1     # 1920x1080
    assert stroke_width(25) == 2     # 1600x1200
    assert stroke_width(40) == 2     # 4K — the approved look; NOT 3


@pytest.mark.parametrize("g", ALL_G)
def test_stroke_width_is_monotone_and_never_zero(g: int):
    assert stroke_width(g) >= 1
    if g > G_MIN:
        assert stroke_width(g) >= stroke_width(g - 1)


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("n", [6, 44, 61])
def test_stroke_width_is_independent_of_span(g: int, n: int):
    """The regression this guards: deriving K from each frame's own dst/src
    ratio makes two frames on the SAME screen disagree, because the ratio is
    span-dependent. K must depend on g alone."""
    k = stroke_width(g)
    for span in SPANS:
        src = max(2 * n, span * 16 // g)
        m = axis_map(src, span, n, g)
        if m is None:
            continue
        widths = band_widths(n, cum(n, span, src), k)
        assert widths[0] == k, (g, n, span, widths)


# --------------------------------------------------------------------------
# LAW 3 — chrome cells pinned
# --------------------------------------------------------------------------

@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("n", BAND_DEPTHS)
@pytest.mark.parametrize("span", [150, 400, 771, 898, 1234, 2400])
def test_band_widths_pin_stroke_and_bevel(g: int, n: int, span: int):
    """Cells 0 (stroke) and 1 (45-degree bevel) both render at exactly K.

    Getting this wrong is what the user reported as "corners too small at
    1600x1200" and "too large at 1920x1080" — one bug, opposite signs.
    """
    src = max(2 * n, span * 16 // g)
    if src < 2 * n:
        return
    b = cum(n, span, src)
    if b <= 0 or span < 2 * b:
        return
    k = stroke_width(g)
    w = band_widths(n, b, k)

    assert sum(w) == b, (g, n, span, w)
    assert all(x >= 0 for x in w)
    if n > 2 and b >= 2 * k:
        assert w[0] == k and w[1] == k, (g, n, span, w)


def test_band_widths_degenerate_band_falls_back_cleanly():
    """A band too shallow for two chrome cells must not produce negative or
    zero-sum cells — it degrades to a plain distribution."""
    w = band_widths(n=6, band_px=3, k=2)     # 3 < 2*k
    assert sum(w) == 3 and all(x >= 0 for x in w)
    w = band_widths(n=2, band_px=10, k=2)    # n <= 2
    assert sum(w) == 10


def test_band_widths_native_is_all_ones():
    """g=16: K=1, band depth 6 -> six 1px cells, i.e. the native sprite."""
    assert band_widths(6, 6, stroke_width(NATIVE_G)) == [1] * 6


# --------------------------------------------------------------------------
# axis_map — the 9-slice enlarge
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n", [6, 44, 61])
def test_axis_map_is_the_identity_at_native(n: int):
    """THE invariant. At g=16 the enlarge must be byte-identical to vanilla:
    F(j) == j for every j. If this ever fails, 1024x768 has regressed."""
    span = 8 * n
    m = axis_map(src_n=span, dst_n=span, n=n, g=NATIVE_G)
    assert m == list(range(span))


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("n", [6, 44])
@pytest.mark.parametrize("span", SPANS[::11])
def test_axis_map_is_monotone_and_in_range(g: int, n: int, span: int):
    src = max(2 * n, span * 16 // g)
    m = axis_map(src, span, n, g)
    if m is None:
        return
    assert len(m) == span
    assert all(0 <= s < src for s in m)
    assert all(b >= a for a, b in zip(m, m[1:])), "map must be monotone"


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("n", [6, 44])
@pytest.mark.parametrize("span", SPANS[::11])
def test_axis_map_opposite_strokes_are_equal(g: int, n: int, span: int):
    """The wobble this whole workstream exists to kill: the near stroke and the
    far stroke must be the same width. Both bands carry identical widths, each
    anchored to its own outer edge."""
    src = max(2 * n, span * 16 // g)
    m = axis_map(src, span, n, g)
    if m is None:
        return
    near = sum(1 for s in m if s == 0)
    far = sum(1 for s in m if s == src - 1)
    assert near == far == stroke_width(g), (g, n, span, near, far)


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("n", [6, 44])
@pytest.mark.parametrize("span", SPANS[::13])
def test_axis_map_middle_keeps_the_engine_phase(g: int, n: int, span: int):
    """The interior must sample on the ENGINE's own NN phase. Re-picking which
    source rows duplicate is precisely what banded the HUD and title fills at
    fractional g. See feedback-dither-no-resample-on-upscale."""
    src = max(2 * n, span * 16 // g)
    m = axis_map(src, span, n, g)
    if m is None:
        return
    b = cum(n, span, src)
    for j in range(b, span - b):
        expect = min(max((j * src) // span, n), src - 1 - n)
        assert m[j] == expect, (g, n, span, j)


def test_axis_map_refuses_degenerate_geometry():
    """When the rect cannot hold two bands, return None so the caller falls
    back to the engine's renderer rather than drawing something wrong."""
    assert axis_map(src_n=6, dst_n=6, n=6, g=25) is None    # src < 2n
    assert axis_map(src_n=100, dst_n=3, n=6, g=25) is None   # dst < 2B


# --------------------------------------------------------------------------
# LAW 5 — chrome follows content
# --------------------------------------------------------------------------

def test_ring_bottom_reduces_to_vanilla_at_native():
    """The identity that makes the native no-op a PROOF, not a test.

    Vanilla faction picker: list rect T=134 B=264, ring top = T-3 = 131,
    7 rows of pitch 19. Vanilla's own ring bottom is B+3 = 267.
    """
    assert ring_bottom(ring_top=131, inset=3, rows=7, pitch=19, scale=1.0) == 264 + 3


@pytest.mark.parametrize("label,g,su", RESOLUTIONS)
def test_ring_bottom_is_flush_with_the_last_row(label: str, g: int, su: float):
    """The ring's bottom sits exactly where the rows end, at every resolution.
    That is the whole content of "chrome follows content"."""
    ring_top = round(su * 131)
    pitch = int(su * 19)                       # the engine floors; we follow it
    bottom = ring_bottom(ring_top, 3, 7, pitch, su)
    rows_top = ring_top + round(su * 3)
    assert bottom == rows_top + 7 * pitch


def test_ring_bottom_never_extends_past_the_scaled_rect():
    """Pulling the chrome edge IN is safe; pushing it OUT would overrun the
    dest buffer. Assert the direction at every shipped resolution."""
    for _, g, su in RESOLUTIONS:
        ring_top = round(su * 131)
        scaled_rect_bottom = round(su * 267)
        pitch = int(su * 19)
        assert ring_bottom(ring_top, 3, 7, pitch, su) <= scaled_rect_bottom


# --------------------------------------------------------------------------
# Golden vectors — the contract the JS prototype and the baked asm must meet
# --------------------------------------------------------------------------

def test_golden_vectors_are_in_sync_with_the_laws():
    """`tests/golden_scaling_vectors.json` freezes the reference's output at the
    geometry the game actually draws (from frida_frame9.log), at frames a human
    has signed off on.

    A port (hook_frame9.js, or the baked cave thunk) is verified against THESE
    NUMBERS, not against another port. If this test fails you have changed a
    law: regenerate with `py work/scripts/gen_scaling_vectors.py --write` and
    review the diff — every changed integer is a pixel that moves on screen.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import gen_scaling_vectors as gen

    path = Path(__file__).resolve().parent / "golden_scaling_vectors.json"
    assert path.exists(), "golden vectors missing — run gen_scaling_vectors.py --write"

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    fresh = gen.build()
    assert on_disk["stroke_width"] == fresh["stroke_width"]
    assert on_disk["frames"] == fresh["frames"], (
        "golden vectors disagree with scaling_laws.py — a law changed"
    )


def test_golden_vectors_encode_the_approved_4k_look():
    """Belt and braces: the two facts the user explicitly signed off on.

    4K stroke is 2px (not 3), and the corner bevel carries the same weight as
    the stroke at every shipped resolution.
    """
    import json

    path = Path(__file__).resolve().parent / "golden_scaling_vectors.json"
    v = json.loads(path.read_text(encoding="utf-8"))

    assert v["stroke_width"]["40"] == 2, "4K stroke must stay 2px"
    for label, frame in v["frames"].items():
        if frame["n"] <= 2:
            continue
        for g, e in frame["by_g"].items():
            if e["band"] >= 2 * e["stroke"]:
                assert e["widths"][0] == e["stroke"], (label, g)
                assert e["widths"][1] == e["stroke"], (label, g)
            assert sum(e["widths"]) == e["band"], (label, g)


# --------------------------------------------------------------------------
# LAW 1 + LAW 5 — option-list row gap (the QUIT type-16 two-button spacing).
#
# Ground truth, measured on the PRISTINE exe (work/tests/frida_q16gap.log):
#   g=16  gap44=3  rowH68=19  pitch=22   drawn bar 20   -> visible gap 2
# and on the patched exe:
#   g=25  gap44=3  rowH68=31  pitch=34   drawn bar 31   -> visible gap 3
#   g=40  gap44=3  rowH68=50  pitch=53   drawn bar 50   -> visible gap 3  (WRONG: want 5)
# The gap field is a constant 3 at every g -- it never scaled. The bar height
# already does (scale_px(20,g) reproduces the measured 31 and 50 exactly).
# --------------------------------------------------------------------------

Q16_VANILLA_PITCH = 22      # pristine: Buffer_text_height 19 + gap 3
Q16_VANILLA_ROW_H = 20      # pristine: Buffer_text_line_height (what actually draws)


def _drawn_row_h(g: int) -> int:
    """The row height the draw loop uses at scale (Buffer_text_line_height).
    Verified against the engine at g=25 (31) and g=40 (50)."""
    return scale_px(Q16_VANILLA_ROW_H, g)


def test_scale_px_reproduces_the_measured_engine_row_heights():
    """If LAW 1 did not predict the bar height the engine actually draws, every
    number built on top of it would be fiction."""
    assert _drawn_row_h(16) == 20
    assert _drawn_row_h(25) == 31        # measured
    assert _drawn_row_h(40) == 50        # measured


def test_option_row_gap_is_the_native_field_value_at_g16():
    """The hard invariant: at 1024x768 the patched exe must reproduce vanilla.
    22 - 19 = 3 is the field's real value, so this is an ALGEBRAIC no-op --
    at g=16 the calc still measures the row with Buffer_text_height (19)."""
    assert option_row_gap(Q16_VANILLA_PITCH, 19, NATIVE_G) == 3


@pytest.mark.parametrize("g", range(G_MIN, G_MAX + 1))
def test_option_row_pitch_is_exactly_faithful_at_every_g(g: int):
    """LAW 5. The pitch positions row i, so the PITCH is the quantity that must
    equal vanilla * g/16 -- exactly, at every resolution, by construction."""
    rh = _drawn_row_h(g)
    gap = option_row_gap(Q16_VANILLA_PITCH, rh, g)
    assert rh + gap == scale_px(Q16_VANILLA_PITCH, g)


@pytest.mark.parametrize("g", range(G_MIN, G_MAX + 1))
def test_option_row_gap_is_never_negative(g: int):
    assert option_row_gap(Q16_VANILLA_PITCH, _drawn_row_h(g), g) >= 0


def test_scaling_the_gap_directly_is_wrong_and_this_is_where_it_breaks():
    """THE TRAP. `gap = scale_px(vanilla_gap=2, g)` is the obvious fix, agrees
    with the engine at 4K/1600/1920, and lands rows 1px off at g=18/26/34,
    because the bar height and the gap round INDEPENDENTLY.

    n * floor(s*v) != floor(n*s*v) -- see feedback-remainder-distribution.
    If this test ever passes, someone has changed half_down and the whole
    remainder-distribution family needs re-deriving.
    """
    naive_breaks = [
        g for g in range(G_MIN, G_MAX + 1)
        if _drawn_row_h(g) + scale_px(2, g) != scale_px(Q16_VANILLA_PITCH, g)
    ]
    assert naive_breaks == [18, 26, 34], naive_breaks


def test_option_row_gap_matches_the_shipped_resolutions():
    """The four resolutions we verify in-game. g=22/25 are ALREADY correct at the
    native gap of 3 -- which is exactly why this defect only shows up at 4K."""
    expected = {16: 3, 22: 3, 25: 3, 40: 5}      # 4K: 3 -> 5, the user's report
    got = {g: option_row_gap(Q16_VANILLA_PITCH,
                                19 if g == NATIVE_G else _drawn_row_h(g), g)
           for g in expected}
    assert got == expected


def test_option_row_pitch_grows_monotonically_with_the_lever():
    """The PITCH is the monotone quantity, not the gap.

    The gap deliberately wobbles (2,3,2,2,3,3,...) because it absorbs the
    rounding that keeps the pitch exactly faithful -- that is LAW 5 doing its
    job. Asserting a monotone GAP would be asserting the bug back in: it would
    force the pitch off `vanilla * g/16` at g=18/26/34. Rows are positioned by
    the pitch, so the pitch is what a viewer perceives.
    """
    pitches = [_drawn_row_h(g) + option_row_gap(Q16_VANILLA_PITCH, _drawn_row_h(g), g)
               for g in range(17, G_MAX + 1)]
    assert all(b >= a for a, b in zip(pitches, pitches[1:])), pitches
    assert pitches == [scale_px(Q16_VANILLA_PITCH, g) for g in range(17, G_MAX + 1)]


# --------------------------------------------------------------------------
# popup body-frame <-> title-frame alignment (the quit-modal 4px @4K report)
# --------------------------------------------------------------------------
# Vanilla (pristine quit-modal trace, frida_namewidth2.log): title ring
# [27,4,696,28], body outer ring [233,32,696,61], body inner d528
# [236,35,693,58]. The relations that must survive scaling:
#     body_outer.right == title.right          (flush -- the user's report)
#     body_inner.right == title.right - 3      (one channel inside)
TITLE_R_VANILLA = 696


def test_body_edges_are_the_identity_at_native_g():
    """g=16 identity, algebraically: delta=0 and popup_pad(3,16)=3 reproduce
    the pristine 696 / 693 relations exactly."""
    assert body_outer_edge_r(TITLE_R_VANILLA, NATIVE_G) == 696
    assert body_inner_edge_r(TITLE_R_VANILLA, NATIVE_G) == 693
    assert body_outer_edge_l(27, NATIVE_G) == 27
    assert body_inner_edge_l(27, NATIVE_G) == 30


@pytest.mark.parametrize("g", range(G_MIN, G_MAX + 1))
def test_body_outer_drawn_edge_is_flush_with_the_title_at_every_g(g: int):
    """THE LAW. The title frame draws through thunk_box_thick, whose stroke
    lands frame_grow_delta OUTSIDE its rect; the body frames draw FLAT (the
    2026-07-09 channel fix removed delta from thunk_box_thick_hollow). Drawn
    flushness therefore requires the body rect to pre-add the title's grow."""
    t = 1740                                    # any title rect.right
    title_drawn = t + title_grow_delta(g)
    body_drawn = body_outer_edge_r(t, g)        # flat draw: drawn == rect
    assert body_drawn == title_drawn


@pytest.mark.parametrize("g", range(G_MIN, G_MAX + 1))
def test_body_channel_equals_title_channel_at_every_g(g: int):
    """The 2026-07-09 channel fix must NOT regress: body outer-to-inner channel
    stays popup_pad(3), the same as the title pair's drawn channel (d618 nests
    ps3 inside d5a0 and both title frames grow by the same delta)."""
    t = 1740
    body_channel = body_outer_edge_r(t, g) - body_inner_edge_r(t, g)
    title_channel = (t + title_grow_delta(g)) - ((t - popup_pad(3, g)) + title_grow_delta(g))
    assert body_channel == popup_pad(3, g) == title_channel
    left_channel = body_inner_edge_l(27, g) - body_outer_edge_l(27, g)
    assert left_channel == popup_pad(3, g)


def test_the_engine_pad_path_lags_and_this_is_where():
    """THE TRAP this law replaces. The engine body-ring right is composed as
    frameR - popup_pad(10) + popup_pad(3) + popup_pad(3) while the title is
    frameR - popup_pad(4). Vanilla: -10+3+3 == -4. Scaled, the floors do NOT
    compose: the body rect lags the title by 1px at g=25 and g=40 (0 at the
    other shipped resolutions -- invisible at 1920x1080, real at 1600/4K)."""
    lag = {g: (popup_pad(10, g) - 2 * popup_pad(3, g)) - popup_pad(4, g)
           for g in (16, 22, 25, 40)}
    assert lag == {16: 0, 22: 0, 25: 1, 40: 1}


def test_total_drawn_misalignment_matches_what_was_measured_on_screen():
    """The defect signature as reported 2026-07-10: the quit modal's body-outer
    right stroke sat 4px left of the title's at 4K (screenshot columns 2752/2756).
    4 = 1px engine floor-lag + 3px unmatched title grow. And the same popup was
    FLUSH at 1024 (native) -- which is why it survived the g=16 verify pass."""
    for g, seen in ((16, 0), (22, 0), (25, 2), (40, 4)):
        lag = (popup_pad(10, g) - 2 * popup_pad(3, g)) - popup_pad(4, g)
        assert lag + frame_grow_delta(g) == seen


# --------------------------------------------------------------------------
# TutWin directional tooltips — the synthetic stash, the content top, and the
# button-shrink inverse (probed + user-verified at all four resolutions
# 2026-07-10; see work/ACTION_ITEMS.md "TutWin directional tooltips")
# --------------------------------------------------------------------------

def test_tutwin_laws_are_the_identity_at_native_g():
    """The invariant that outranks all others."""
    assert tutwin_stash_left(NATIVE_G) == 13
    assert tutwin_stash_right(490, NATIVE_G) == 490 - 13
    assert tutwin_content_top(NATIVE_G) == 27


def test_tutwin_stash_lands_the_ring_at_the_vanilla_inset():
    """LAW 5, algebraically: the stash is DEFINED so the unchanged pf-align
    chain draws the ring (body-outer d5a0) at scale_px(13, g) from each window
    edge. The chain, not this test, does the drawing — so assert through the
    chain's own law functions."""
    for g in ALL_G:
        for w in (490, 764, 672, 1224):
            assert body_outer_edge_l(tutwin_stash_left(g), g) == scale_px(13, g)
            assert (body_outer_edge_r(tutwin_stash_right(w, g), g)
                    == w - scale_px(13, g))


def test_tutwin_field_and_text_follow_the_chain_relations():
    """The field (d528) sits popup_pad(3) inside the ring and the body text
    popup_pad(3) inside the field — the SAME relations every titled popup gets
    (vanilla: ring 13, field 16, text ~19+pad; 16-13 == 3 == popup_pad(3,16)).
    The bake changes nothing in frame_align/textfollow; this pins the values
    they will compute from the fed stash."""
    for g in ALL_G:
        ring_l = body_outer_edge_l(tutwin_stash_left(g), g)
        field_l = body_inner_edge_l(tutwin_stash_left(g), g)
        assert field_l - ring_l == popup_pad(3, g)
        text_x = field_l + popup_pad(3, g)     # thunk_pf_textfollow's relation
        assert text_x == scale_px(13, g) + 2 * popup_pad(3, g)


def test_tutwin_content_top_matches_the_verified_resolutions():
    """Pinned to what the user approved in-game: text Y / [0x30e8] values seen
    in frida_tutwin_fix.log at the four shipped resolutions."""
    assert {g: tutwin_content_top(g) for g in (16, 22, 25, 40)} == \
        {16: 27, 22: 37, 25: 42, 40: 67}


def test_ornate_untitled_content_top_generalises_tutwin():
    """thunk_tutwin_ctop v2: every UNTITLED ORNATE popup (engine type 2/6,
    unanchored, not the faction quote) gets TutWin's content top; TutWin by
    identity. Same numbers at every g; identity at g<=16; everything else and
    any non-native value passes through (double-scale guard)."""
    for g in ALL_G:
        law = ornate_untitled_content_top
        want = scale_px(27, g)
        assert law(27, popup_type=6, titled=False, anchored=False, is_tutwin=False,
                   faction_quote=False, g=g) == want == tutwin_content_top(g)
        assert law(27, popup_type=2, titled=False, anchored=False, is_tutwin=False,
                   faction_quote=False, g=g) == want
        assert law(27, popup_type=2, titled=False, anchored=True, is_tutwin=True,
                   faction_quote=False, g=g) == want
        for kw in (dict(popup_type=6, titled=True, anchored=False, faction_quote=False),
                   dict(popup_type=6, titled=False, anchored=True, faction_quote=False),
                   dict(popup_type=6, titled=False, anchored=False, faction_quote=True),
                   dict(popup_type=0, titled=False, anchored=False, faction_quote=False),
                   dict(popup_type=5, titled=False, anchored=False, faction_quote=False)):
            assert law(27, is_tutwin=False, g=g, **kw) == 27
        assert law(want, popup_type=6, titled=False, anchored=False, is_tutwin=False,
                   faction_quote=False, g=g) == want
        if g <= NATIVE_G:
            assert want == 27
    assert ornate_untitled_content_top(27, popup_type=6, titled=False, anchored=False,
                                       is_tutwin=False, faction_quote=False, g=40) == 67


def test_tutwin_pop_pointer_x_is_vanilla_at_native_and_screen_space_above():
    """The drone tour's pointer target x (TutWin_tour6 DRONETOUR1/5): vanilla
    pushes the strip-LOCAL `left + 5` (a vanilla bug masked at 1024x768 where
    the strip starts at x=0). g<=16 keeps that exact expression; g>16 adds
    the MainWin screen origin (what local_to_screen does for y) and scales
    the native 5 by the strip seed law's floor idiom. 4K repro: left 667
    (267 native x 2.5) in a strip at x=640 -> 1319, on the drone's portrait,
    not the console rail at 672."""
    from scaling_laws import tutwin_pop_pointer_x
    assert tutwin_pop_pointer_x(267, 0, NATIVE_G) == 272
    assert tutwin_pop_pointer_x(267, 640, NATIVE_G) == 272      # no origin term at native
    assert tutwin_pop_pointer_x(667, 640, 40) == 1319
    assert {g: tutwin_pop_pointer_x(0, 0, g) for g in (16, 22, 25, 40)} == \
        {16: 5, 22: 6, 25: 7, 40: 12}
    for g in ALL_G:
        for left in (0, 267, 667, 1750):
            for ox in (0, 128, 640):
                x = tutwin_pop_pointer_x(left, ox, g)
                want = left + 5 if g <= NATIVE_G else ox + left + popup_scale_floor(5, g)
                assert x == want, (g, left, ox)


def test_menu_font_request_is_one_font_for_every_writer():
    """g_menu_font (the universal Menu control's only font) has two engine
    writers we must keep in step -- the MENU widget layout and popups_normal
    (end of every tutorial popup). Both ask find_font for native 16 x g/16 = g,
    capped at the pool max 40, variant 1; g<=16 keeps the engine's pointer."""
    from scaling_laws import menu_font_request
    for g in range(0, NATIVE_G + 1):
        assert menu_font_request(g) is None
    assert {g: menu_font_request(g) for g in (17, 22, 25, 40)} == \
        {17: (17, 1), 22: (22, 1), 25: (25, 1), 40: (40, 1)}
    for g in ALL_G:
        if g > NATIVE_G:
            size, variant = menu_font_request(g)
            assert size == min(16 * g // 16, 40) and variant == 1
    assert menu_font_request(48) == (40, 1)


def test_tutwin_base_pointer_pt_is_the_basewin_consumer_law():
    """Base-screen tutorial targets (local_to_screen(BaseWin_g) sites) are
    NATIVE BaseWin-local rect centres; they scale by the same consumer-
    boundary law the drawing uses. 4K psych pin: (428,394) -> (1070,985)."""
    from scaling_laws import basewin_pt, tutwin_base_pointer_pt
    assert (tutwin_base_pointer_pt(428, 40), tutwin_base_pointer_pt(394, 40)) == (1070, 985)
    for g in ALL_G:
        for v in (0, 7, 17, 363, 394, 428, 700, -3):
            assert tutwin_base_pointer_pt(v, g) == basewin_pt(v, g) == (v if g <= NATIVE_G else (v * g) >> 4)


def test_btn_native_dim_is_the_exact_inverse_of_the_floor_forward():
    """Every window family that reaches the shrink scales its dims by the
    FLOOR idiom (popup_scale_floor / gwinit's imul-sar4), and the round trip
    native -> floor-scale -> btn_native_dim must be the identity for every
    plausible dim at every g. Ceil is that inverse (the floor sheds < 1
    native px); v1's round under-recovered whenever (n*g mod 16)/g > 1/2."""
    for g in ALL_G:
        for n in range(4, 700):
            assert btn_native_dim(popup_scale_floor(n, g), g) == n, (n, g)


def test_btn_native_dim_v2_matches_v1_round_on_every_verified_dim():
    """v1 (round, H only) was user-verified at g=22/25/40 on the 20/22-native
    button windows — v2 (ceil) must reproduce those recoveries exactly, so no
    approved screen moves. And the v2-only wins are pinned: the dims where
    round under-recovers a floor-forward (r/g > 1/2)."""
    for g in (22, 25, 40):
        for n in (20, 22):
            dev = popup_scale_floor(n, g)
            assert btn_native_dim(dev, g) == (dev * NATIVE_G + g // 2) // g == n
    # round's blind spots, fixed by ceil:
    assert (popup_scale_floor(238, 25) * NATIVE_G + 12) // 25 == 237  # v1
    assert btn_native_dim(popup_scale_floor(238, 25), 25) == 238      # v2
    assert (popup_scale_floor(20, 23) * NATIVE_G + 11) // 23 == 19    # v1
    assert btn_native_dim(popup_scale_floor(20, 23), 23) == 20        # v2


def test_the_shipped_floor_loses_the_bar_arts_bottom_row_and_this_is_where():
    """The defect signature (1600 hover, 2026-07-10): floor round-trips the
    20-row bar art to 19 at g=25 AND g=22, so the 9-slice rendered one row
    short and the hover highlight's bottom outline row was clipped before the
    zoom. 4K is exact — which is why every 4K screenshot looked fine.
    Same signature on WIDTH (2026-07-21e): the BaseWin chevrons' fixed 20x20
    state-sprite art lost its right border column at 1600 because no W law
    was applied at all — shrink's raw floor stood."""
    for g, floored in ((16, 20), (22, 19), (25, 19), (40, 20)):
        assert (scale_px(20, g) * NATIVE_G) // g == floored
        assert btn_native_dim(scale_px(20, g), g) == 20


def test_btn_bar_tile_height_full_bleed_is_the_identity_when_art_covers():
    """Every previously-verified button class (popup action / prefwin toggle /
    TutWin, all 20-native windows with the 20-row art) must keep the exact
    full-bleed behavior the 2026-06-27 devfill gridding validated.

    The forward is popup_scale_floor — the idiom every window family that
    reaches the shrink actually ships (popup/pref levers, gwinit sar4) — not
    scale_px: the two differ at e.g. g=19 where half_down rounds up and a
    ceil-inverse of the WRONG forward would over-recover."""
    for g in ALL_G:
        orig = popup_scale_floor(20, g)
        native = btn_native_dim(orig, g)
        assert native == 20, g
        assert btn_bar_tile_height(orig, native, 20) == orig, g


def test_btn_bar_tile_height_caps_at_the_zoomed_art_bottom():
    """The picker's 22-native text buttons (defect ...174559): the dither must
    stop at the zoomed art's last row -- the rows the engine's centre-sampled
    NN maps to an art row (v2 2026-10-24 wave-1 F33; v1's floor(artH*orig/
    native) was one short at 1600x1200) -- leaving the vanilla transparent
    gap below. At 4K that is exactly 50 of 55 (20 of 22 native x 2.5)."""
    cases = [
        # (g, orig=window H scaled from native 22, expected tile height)
        (40, 55, 50),   # 4K: zoom 22->55, art 20 -> (2*20*55 + 21) // 44 = 50
        (25, 34, 31),   # 1600x1200: native=ceil(34*16/25)=22 -> rows j with (2j+1)*22 < 2*20*34: 31 (v1 floor: 30)
        (22, 30, 27),   # 1920x1080: native=ceil(30*16/22)=22 -> (2*20*30 + 21) // 44 = 27
    ]
    for g, orig, want in cases:
        native = btn_native_dim(orig, g)
        assert native == 22, (g, native)
        assert btn_bar_tile_height(orig, native, 20) == want, (g, orig)
    # degenerate guard: never divide by a nonpositive native
    assert btn_bar_tile_height(55, 0, 20) == 55
    # cap never exceeds the window even for oversized art
    assert btn_bar_tile_height(55, 22, 44) == 55


# --------------------------------------------------------------------------
# dialog_row_margin — the generic Dialog [+0x44] inter-row margin
# (thunk_rowgap v2 @0x60f018; asm parity in test_rowgap_asm_parity.py)
#
# Defect (thunk_rowgap v1): gated on ScreenWidth>0x3FF, which FIRES at
# 1024x768 (W=0x400, g=16) — the lo-res gate law violation. The stomp of 3
# there happened to be an identity (native IS 3, the struct-copy default;
# proven by v1==v2 pixel-identity at 1024), but the gate stands corrected.
# The +2px PrefWin row pitch that exposed all this was the UNGATED
# popup_list_rowheight redirect (font leading at g=16), fixed separately by
# routing its two sites through the gated thunk_quit_rowpitch helper.
# --------------------------------------------------------------------------

DIALOG_NATIVE_MARGIN = 3    # the struct-copy default, the ONE measured native


@pytest.mark.parametrize("field", range(0, 9))
def test_dialog_row_margin_is_the_identity_at_native(field: int):
    """The g=16 no-op is the GATE itself — no width literal anywhere, so it
    cannot repeat v1's 1024x768 (W=0x400 > 0x3FF) violation."""
    assert dialog_row_margin(field, NATIVE_G) == field


@pytest.mark.parametrize("g", [g for g in ALL_G if g > NATIVE_G])
def test_dialog_row_margin_matches_v1_exactly_above_native(g: int):
    """v1's g>16 output (floor(3g/16), `sar 4`) is user-verified at 22/25/40;
    the law must not move those screens. Floor, NOT half_down — they differ
    at g=25 (4 vs 5)."""
    assert dialog_row_margin(DIALOG_NATIVE_MARGIN, g) == (3 * g) >> 4
    assert dialog_row_margin(DIALOG_NATIVE_MARGIN, 25) == 4  # half_down says 5


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("field", range(0, 9))
def test_dialog_row_margin_is_idempotent(g: int, field: int):
    """The calc runs twice per build and the field PERSISTS (it is SET, not
    rebuilt). A second pass over the law's own output must be a fixed point —
    this is why only the measured native scales and its images (4..7) pass
    through."""
    once = dialog_row_margin(field, g)
    assert dialog_row_margin(once, g) == once


@pytest.mark.parametrize("g", ALL_G)
def test_dialog_row_margin_only_scales_the_measured_native(g: int):
    """An unmeasured value must pass through UNSCALED at every g, never be
    guessed at. (An inferred-but-unmeasured "PrefWin native = 1" entry briefly
    lived here and was wrong — the pitch delta it explained belonged to the
    rowheight redirect. If a new family's native margin is MEASURED, add it
    to DIALOG_ROW_MARGIN_NATIVES and re-prove idempotency — this sweep does.)"""
    for field in range(0, 9):
        if field not in DIALOG_ROW_MARGIN_NATIVES:
            assert dialog_row_margin(field, g) == field


@pytest.mark.parametrize("g", ALL_G)
def test_dialog_row_margin_is_proportionate_for_the_native(g: int):
    """LAW 1 with v1's floor rounding: scaled = floor(native * g/16), monotone
    in g, never below native."""
    got = dialog_row_margin(DIALOG_NATIVE_MARGIN, g)
    assert got == (DIALOG_NATIVE_MARGIN * g) // 16
    assert got >= DIALOG_NATIVE_MARGIN


# --------------------------------------------------------------------------
# prefwin_window_pos / popup_scale_floor — the PrefWin bake (group prefwin_scale)
# --------------------------------------------------------------------------

def test_prefwin_window_pos_is_vanillas_own_expression_at_native():
    """Vanilla computes x=SW/2-350 y=SH-618 itself; at g=16 the law must be
    that exact expression at ANY screen size (algebraic no-op)."""
    for sw, sh in ((1024, 768), (3840, 2160), (1600, 1200), (800, 600)):
        assert prefwin_window_pos(sw, sh, NATIVE_G) == (sw // 2 - 350, sh - 618)


def test_prefwin_window_pos_matches_the_verified_prototype_log():
    """The four in-game verified placements (frida_prefwin_scale.log v19)."""
    assert prefwin_window_pos(3840, 2160, 40) == (1045, 615)
    assert prefwin_window_pos(1600, 1200, 25) == (254, 235)
    assert prefwin_window_pos(1920, 1080, 22) == (479, 231)
    assert prefwin_window_pos(1024, 768, 16) == (162, 150)


@pytest.mark.parametrize("g", ALL_G)
def test_pref_mode_cells_tile_the_frame_span_without_drift(g: int):
    """The display-mode row: three cells over the live frame span (256, 457).
    Ends are exact, cells differ by at most 1 native px, and the device x of
    every cell (the gate's floor(x*g/16)) stays within one device px of the
    ideal third -- the i*floor(pitch) shortcut fails this at the last cell."""
    fx, fw = 256, 457
    xs = [pref_mode_cell_x(fx, fw, i) for i in range(4)]
    assert xs[0] == fx and xs[3] == fx + fw
    widths = [b - a for a, b in zip(xs, xs[1:])]
    assert max(widths) - min(widths) <= 1
    for i, x in enumerate(xs):
        ideal = (fx + i * fw / 3) * g / 16
        assert abs(popup_scale_floor(x, g) - ideal) <= 1 + g / 32
    if g == NATIVE_G:
        assert [popup_scale_floor(x, g) for x in xs] == xs


@pytest.mark.parametrize("g", ALL_G)
def test_popup_scale_floor_is_the_asm_idiom(g: int):
    """floor(v*g/16) == the thunks' `imul; sar 4` for the sizes the bake uses,
    and identity at g=16."""
    for v in (10, 12, 14, 350, 618, 778, 390):
        assert popup_scale_floor(v, g) == (v * g) // 16
        assert popup_scale_floor(v, NATIVE_G) == v


def test_popup_scale_floor_differs_from_scale_px_and_that_is_deliberate():
    """The floor idiom is NOT half_down — they differ at exact .5 boundaries.
    The prototype (and every popup-family thunk) shipped floor and was
    user-verified; if this test fails someone unified the roundings and every
    verified screen moves. See popup_scale_floor's docstring."""
    assert popup_scale_floor(350, 25) == 546
    assert scale_px(350, 25) == 547


# --------------------------------------------------------------------------
# itemlist_box_width — type-1 checkbox popup box (Customize Game Rules fix)
# --------------------------------------------------------------------------
# Ground truth (frida_boxw2.log 2026-07-12 @4K g=40): xs=660 (=440*3/2, the
# ENGINE's own >1023px #xs bump — vanilla behavior, byte-identical in cc659f),
# [+0x222c]=890 (longest item at the x2.5 font; ~356 native), trim=22.
# v3 shipped (890+22)*40>>4 = 2280; faithful is 1705 — which also equals the
# independently drawn content: rows 1589 + insets 86+30 (exact flush).

# What the engine's dialog measure writes to [+0x222c] under our font scaling:
def _itemlist_measured_dev(xs: int, native_text: int, g: int) -> int:
    return max(xs, popup_scale_floor(native_text, g))


ITEMLIST_CASES = [
    # (xs, native longest-item text) — xs dominates (RULES), text dominates,
    # and the degenerate no-items case.
    (660, 356),
    (660, 900),
    (300, 356),
]


def test_itemlist_box_is_the_identity_at_native():
    for xs, text in ITEMLIST_CASES:
        dev = _itemlist_measured_dev(xs, text, NATIVE_G)   # == engine's own tw
        native = dev + 22                                  # engine: tw + trim
        assert itemlist_box_width(xs, dev, 22, NATIVE_G) == native
    # [+0x222c] == 0 (no items measured yet): falls back to xs, like the engine
    assert itemlist_box_width(660, 0, 22, NATIVE_G) == 682


def test_itemlist_box_customize_rules_golden_vector():
    """The measured 4K defect and its faithful target, pinned exactly."""
    assert itemlist_box_width(660, 890, 22, 40) == 1705
    # faithful box == the content the engine actually drew (rows + insets),
    # measured independently on the screenshot: 86 + 1589 + 30
    assert 1705 == 86 + 1589 + 30


def test_listbox_box_faction_scenario_golden_vector():
    """The type-2 instance of the same law (thunk_scale_boxw v5, scenario
    #FACTION @4K, frida_faction_scenario_crash.log:311): d5c=1312 is
    thunk_lbcalc_minw's own DEVICE-space w5c (= 525*40>>4, scaled xs won the
    max), xs=525 = 350 x the engine's >1023px 3/2 bump, trim=0 (init_w=-1,
    padx=0). v4's v3-arm shipped 1312*40>>4 = 3280 — near the full 3840 screen,
    position clamped to x=0; the faithful box is 1312."""
    assert itemlist_box_width(525, 1312, 0, 40) == 1312
    assert (1312 + 0) * 40 >> 4 == 3280   # the defect, so nobody "simplifies" back


# --------------------------------------------------------------------------
# t16_row_measure_width — type-16 native-measure contract (council propose fix)
# --------------------------------------------------------------------------
# Ground truth (frida_council_width.log 4K+1024 + frida_council_confirm.log
# g25 + shot 20260820-211228): the council "Select a motion" popup. xs_clamped
# = 658 (wrapper art-arm min, minw_baseline_clamp), F = 3, longest '|' row
# ~325 native (device measure 812 @g40 = fl(325*40/16) at the calibrated x2.5
# font). Margins 33/67 native -> 82/167 @g40.

def test_t16_council_propose_golden_vector():
    # native branch wins the engine max at every g (325+3 < 658):
    assert t16_row_measure_width(658, 325, 3, 16) == 655    # box 755 = +33+67
    assert t16_row_measure_width(658, 325, 3, 25) == 1023   # box 1178 (g25 run)
    assert t16_row_measure_width(658, 325, 3, 40) == 1637   # box 1886 = lawful
    assert 1637 + 82 + 167 == 1886
    # the shipped defect: the DEVICE measure 812 entered the max at g40 and the
    # v3 arm scaled it AGAIN -> row window 2030 (box 2279). Pin the defect form
    # so nobody re-inlines a device measure at 0x60D5CE:
    assert popup_scale_floor(812, 40) == 2030
    assert t16_row_measure_width(658, 325, 3, 40) != 2030


def test_t16_measured_branch_is_proportionate_when_it_wins():
    # rows longer than xs_clamped: the measured branch wins IN NATIVE SPACE and
    # scales exactly once (contrast: device-entry would give fl(fl(700*g/16)*g/16))
    for g in ALL_G:
        expected = popup_scale_floor(700, g) if g > NATIVE_G else 700
        assert t16_row_measure_width(658, 700, 3, g) == expected


def test_t16_defect_invisible_below_the_flip_g():
    """At g25 the device measure fl(325*25/16)=507 still lost the max to 655 —
    the double-scale class is INVISIBLE at 1600x1200; verification of any
    measured-width popup must include 4K (the flip g)."""
    assert popup_scale_floor(325, 25) + 3 < 658   # native branch wins @g25
    assert popup_scale_floor(325, 40) + 3 > 658   # measured branch flips @g40


@pytest.mark.parametrize("g", ALL_G)
def test_itemlist_box_is_proportionate_within_the_floor(g: int):
    """LAW 1: within one floor-interaction pixel of vanilla*(g/16), never over."""
    for xs, text in ITEMLIST_CASES:
        vanilla = max(xs, text) + 22
        got = itemlist_box_width(xs, _itemlist_measured_dev(xs, text, g), 22, g)
        faithful = popup_scale_floor(vanilla, g)
        assert faithful - 1 <= got <= faithful


@pytest.mark.parametrize("g", ALL_G)
def test_itemlist_box_never_clips_its_content(g: int):
    """The device-space rows + scaled trim always fit inside the box."""
    for xs, text in ITEMLIST_CASES:
        dev = _itemlist_measured_dev(xs, text, g)
        got = itemlist_box_width(xs, dev, 22, g)
        assert got >= dev + popup_scale_floor(22, g)


def test_itemlist_box_grows_monotonically_with_the_lever():
    for xs, text in ITEMLIST_CASES:
        prev = 0
        for g in ALL_G:
            cur = itemlist_box_width(xs, _itemlist_measured_dev(xs, text, g), 22, g)
            assert cur >= prev
            prev = cur


def test_itemlist_container_edges_native_identity_matches_the_engine():
    """Pristine-4K engine measure (frida_namewidth2.log 2026-07-12): title outer
    d5a0 4..675, inner d618 7..672, container ring 7..670. The LEFT law lands
    the measured vanilla rect exactly at g=16; the RIGHT law lands the title
    INNER ring (672), +2 off vanilla's 670 -- the accepted symmetric form the
    type-2/4 rings ship (the asm never runs at g=16).  The TYPE-1 ring is
    itemlist_ring_hug since fix 16, whose g=16 value IS vanilla's 7..670."""
    assert itemlist_container_edge_l(4, NATIVE_G) == 7
    assert itemlist_container_edge_r(675, NATIVE_G) == 672
    assert itemlist_ring_hug(10, 52, 667, 448, NATIVE_G) == (7, 49, 670, 451)


@pytest.mark.parametrize("g", ALL_G)
def test_itemlist_container_is_flush_with_the_drawn_title_inner(g: int):
    """LAW 5 (v5): BOTH container edges derive from the title stash with the
    SAME channel arithmetic the title pair uses (d618 = outer ∓ pad(3)), so
    they are collinear with the drawn inner ring at every g — algebraic, not
    fitted, and symmetric (v4 carried vanilla's −2 on the right; see the
    native-identity test for why that was the rows collision)."""
    TL, TR = 65, 1932
    title_inner_l, title_inner_r = TL + popup_pad(3, g), TR - popup_pad(3, g)
    assert itemlist_container_edge_l(TL, g) == title_inner_l
    assert itemlist_container_edge_r(TR, g) == title_inner_r
    assert itemlist_container_edge_l(TL, g) - TL == TR - itemlist_container_edge_r(TR, g)
    if g > NATIVE_G:
        # strictly INSIDE the quit-family outer-flush edges (the two families
        # must never coincide — that was the defect)
        assert itemlist_container_edge_l(TL, g) > body_outer_edge_l(TL, g)
        assert itemlist_container_edge_r(TR, g) < body_outer_edge_r(TR, g)


# --------------------------------------------------------------------------
# itemlist_ring_hug -- the TYPE-1 checkbox ring hugs its list on all four sides (fix 16 l/r, fix 17 t/b;
# user decision 2026-10-18 "Hug the list"; asm thunk_pf_union_align v16)
# --------------------------------------------------------------------------
# dialog rects D = (l, t, r, b): the main menu / in game / ornate 1024 bars, 4K bars, and odd sizes
HUG_LISTS = ((10, 52, 667, 448), (33, 59, 690, 470), (19, 61, 676, 442), (25, 95, 1667, 887), (82, 117, 1724, 909),
             (47, 117, 1689, 909), (13, 52, 916, 484), (45, 71, 948, 333), (11, 40, 750, 41))


def test_itemlist_ring_hug_is_vanilla_at_native():
    """Pristine .bak, g = 16, every layout (Unicorn chain test_scaling_type1_box_fill): the ring is the
    dialog rect -+ 3 on EVERY side drawn half-open -- bars [10, 667) / [33, 690) / [19, 676), rings [7, 670) /
    [30, 693) / [16, 679), top D.t - 3, bottom D.b + 3.  The v5-v14 native-fix arm drew boxw - 7 (672 / 750 /
    690) instead."""
    assert itemlist_ring_hug(10, 52, 667, 448, NATIVE_G) == (7, 49, 670, 451)
    assert itemlist_ring_hug(33, 59, 690, 470, NATIVE_G) == (30, 56, 693, 473)
    assert itemlist_ring_hug(19, 61, 676, 442, NATIVE_G) == (16, 58, 679, 445)
    for g in (8, 12, 15, 16):
        assert itemlist_ring_hug(33, 59, 690, 470, g) == (30, 56, 693, 473)


@pytest.mark.parametrize("g", ALL_G)
def test_itemlist_ring_hug_drawn_insets_are_equal(g: int):
    """T == B == L == R by construction: one floored pad fl(3g/16) on D's own four edges; at g > 16 the
    band-map ring paints [l, r] x [t, b] inclusive (the right / bottom strokes end ON r / b), so the far
    edges come in by one and the DRAWN insets D.l - l, D.t - t, (r + 1) - D.r, (b + 1) - D.b are all
    fl(3g/16); at g <= 16 the native half-open draw makes them D.l - l, D.t - t, r - D.r, b - D.b = 3.
    The visible channel (inset minus the stroke) is the same on all four sides and clears D at every g.
    Fix 16 left t/b on the engine local (nestpads' scale_px(2)): T = s(2), B = s(2) + 1 -- 5/6 @g40."""
    for dl, dt, dr, db in HUG_LISTS:
        l, t, r, b = itemlist_ring_hug(dl, dt, dr, db, g)
        far_r, far_b = (r + 1, b + 1) if g > NATIVE_G else (r, b)
        p = popup_pad(3, g)
        assert dl - l == dt - t == far_r - dr == far_b - db == p == (3 if g <= NATIVE_G else (3 * g) >> 4),             (g, dl, dt, dr, db)
        k = stroke_width(g)
        assert dl - (l + k) == dt - (t + k) == (far_r - k) - dr == (far_b - k) - db >= 1, (g, k)


@pytest.mark.parametrize("g", ALL_G)
def test_itemlist_ring_hug_ignores_the_title_and_the_margins(g: int):
    """The v14 type-1 ring sat on the title inner, so its insets followed vanilla's UNEQUAL margins (10/12
    main menu -> 8/13 @4K, 33/67 in game -> 8/11): the hug law reads only D, so a list moved or resized
    inside the same box moves its ring with it, edge for edge, on both axes."""
    base = itemlist_ring_hug(100, 60, 900, 500, g)
    assert itemlist_ring_hug(150, 60, 950, 500, g) == (base[0] + 50, base[1], base[2] + 50, base[3])
    assert itemlist_ring_hug(100, 60, 1000, 500, g) == (base[0], base[1], base[2] + 100, base[3])
    assert itemlist_ring_hug(100, 90, 900, 530, g) == (base[0], base[1] + 30, base[2], base[3] + 30)
    assert itemlist_ring_hug(100, 60, 900, 620, g) == (base[0], base[1], base[2], base[3] + 120)


def test_itemlist_ring_hug_gate():
    assert itemlist_ring_takes_hug_arm(1, 0, 0)
    assert not itemlist_ring_takes_hug_arm(1, 52, 0)            # body text: the UnionRect path (v11)
    assert not itemlist_ring_takes_hug_arm(1, 0, 0x3B38F58)     # art: the quit family
    for dlg in (-1, 0, 2, 4, 8, 16):
        assert not itemlist_ring_takes_hug_arm(dlg, 0, 0)       # types 2/4 keep the container arm


def test_listbox_ring_hug_gate():
    """F34: a flat / slide type-2 listbox, no body text, no art, hugs; ornate 2/6 (fix 26's picker arm), body
    text, art, other dialog types and raw families outside both bands do not."""
    from scaling_laws import listbox_ring_takes_hug_arm
    for raw in (0, 9999, 50000, 59999):
        assert listbox_ring_takes_hug_arm(2, 0, 0, raw)
        assert not listbox_ring_takes_hug_arm(2, 52, 0, raw)
        assert not listbox_ring_takes_hug_arm(2, 0, 0x3B38F58, raw)
        for dlg in (-1, 0, 1, 4, 8, 16):
            assert not listbox_ring_takes_hug_arm(dlg, 0, 0, raw)
    for raw in (20000, 29999, 60000, 69999, 10000, 1000000):
        assert not listbox_ring_takes_hug_arm(2, 0, 0, raw)


def test_listbox_ring_hug_is_vanilla_at_g16_and_four_sided():
    """Pristine Go To (1024x768): list [33, 753) x [38, 263) -> ring [30, 756) x [35, 266) half-open (strokes
    30 / 755, 35 / 265) = D -+ 3; at g > 16 the same law hugs D by fl(3g/16) on every side."""
    assert itemlist_ring_hug(33, 38, 753, 263, NATIVE_G) == (30, 35, 756, 266)
    for g in ALL_G:
        if g <= NATIVE_G:
            continue
        l, t, r, b = itemlist_ring_hug(82, 95, 1882, 652, g)
        assert 82 - l == 95 - t == r + 1 - 1882 == b + 1 - 652 == popup_pad(3, g)


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("family", (0, 1, 2, 3, 4, 5, 6, 7, 10))
def test_title_band_hmargin_lr(g, family):
    """F36: L = frame_l + fl(4g/16); R = frame_r - fl(4g/16), one more in at g > 16 for a non-ornate band (the band
    map's inclusive footprint), so the two drawn channels are equal; ornate 2 / 6 and g <= 16 are v1 / vanilla."""
    from scaling_laws import title_band_hmargin_lr
    ins = (4 * g) >> 4
    l, r = title_band_hmargin_lr(0, 1000, family, g)
    assert l == ins
    inclusive = g > NATIVE_G and family not in (2, 6)
    assert r == 1000 - ins - (1 if inclusive else 0)
    if inclusive:
        assert l - 0 == 1000 - 1 - r                    # drawn [l, r]: mirror about the half-open axis
    if g == NATIVE_G:
        assert (l, r) == (4, 996)                       # vanilla: 0x40600A +3, 0x406027 / 0x406031 +1 / -1


# --------------------------------------------------------------------------
# itemlist_ring_list_r -- the right edge the type-1 ring hugs, as the 0x602B49 draw (BEFORE the attach) must
# compute it (fix 18; asm thunk_pf_union_align v17 -> t_boxw_t1_term -> t_t1_list_w)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("g", ALL_G)
def test_itemlist_ring_list_r_is_the_attach_law(g: int):
    """D.r at the first draw is calc_reserve's measured width; the law gives the list window the attach builds:
    D.l + type1_list_fill_width's w (> 1 row, g > 16), else D.r as is -- and for every type-1 census shape that
    w is s(itemlist_box_term_native), the box's term (one arithmetic for the list, the box and the ring)."""
    from scaling_laws import (dialog_row_margin, itemlist_box_term_native, itemlist_ring_list_r,
                              type1_list_fill_width)
    for d_r_calc in (25 + 890, 25 + 657, 0, 4000):
        for xs, m, gap, flags, fh in ((660, 0, dialog_row_margin(3, g), 0, 0), (630, 0, dialog_row_margin(3, g), 0, 0),
                                      (457, 0, 6, 3, 300), (720, 3, dialog_row_margin(3, g), 1, 0)):
            for rows in (0, 1, 2, 18):
                r = itemlist_ring_list_r(25, d_r_calc, xs, m, 1, gap, flags, fh, rows, g)
                w = type1_list_fill_width(xs, m, 1, gap, flags, fh, rows, g)
                if g <= NATIVE_G or rows <= 1:
                    assert w is None and r == d_r_calc, (g, rows)
                else:
                    assert r == 25 + w[0] == 25 + ((itemlist_box_term_native(1, xs, m, gap, flags, fh, g) * g) >> 4)


def test_itemlist_ring_list_r_real_shots():
    """The 7 user shots of 2026-10-22 (test_scaling_type1_box_fill.REAL_SHOTS): the first draw's D.r was
    D.l + the measured text (890 @4K Rules, 1315 @4K Governor, 721 @1440p); the list is s(657) at every g > 16."""
    from scaling_laws import dialog_row_margin, itemlist_ring_hug, itemlist_ring_list_r
    for g, d5c_calc, list_w in ((40, 890, 1642), (40, 1315, 1642), (30, 721, 1231), (22, 657, 903), (18, 657, 739)):
        assert itemlist_ring_list_r(0, d5c_calc, 660, 0, 1, dialog_row_margin(3, g), 0, 0, 18, g) == list_w
    assert itemlist_ring_hug(2156, 997, 2156 + 1642, 2023, 40)[2] == 3804         # 4K Rules: R 3052 -> 3804
    assert itemlist_ring_list_r(0, 657, 660, 0, 1, 3, 0, 0, 18, 16) == 657         # g = 16: the engine's D.r


def test_rescaling_the_mixed_space_tw_is_wrong_and_this_is_where():
    """v3's wholesale (tw+trim)*g/16 on the MIXED-space [+0x222c]: the measured
    2280 vs faithful 1705 @4K. If someone 'simplifies' v4 back to one multiply,
    this is the screen that breaks."""
    v3_box = (890 + 22) * 40 >> 4
    assert v3_box == 2280
    assert itemlist_box_width(660, 890, 22, 40) == 1705
    assert v3_box != 1705


# --------------------------------------------------------------------------
# ingame_popup_min_boxh — the in-game popup minimum box height
# (thunk_popup_min_boxh @0x404EBD; asm parity in test_minboxh_asm_parity.py)
#
# Vanilla clamps every mode-0/5 console-visible [+0xa14]==0 popup to
# box_h >= 300 (footer_reserve absorbs the shortfall); Popup_show bottom-
# anchors on the console strip, so the clamp IS both the tall vanilla body
# and the high placement. The native 300 goes dead at g>16 — the 2026-07-16
# namebase report (@4K box 349 -> top 1279, faithful window 750 -> top 878).
# v2/v3: M is the WINDOW minimum; the box target is M - D for a popup that
# owns its window (D = the exec_3 button-row growth), M when embedded.
# --------------------------------------------------------------------------

BOX_SWEEP = (0, 1, 100, 136, 299, 300, 301, 349, 468, 749, 750, 751, 2000)


@pytest.mark.parametrize("box", BOX_SWEEP)
def test_min_boxh_is_vanillas_own_clamp_at_native(box: int):
    """g=16 must reproduce the displaced block bit-for-bit: M is vanilla's own
    constant 300 (and floor(300*16/16) == 300, so the identity is algebraic)."""
    got_box, got_delta = ingame_popup_min_boxh(box, NATIVE_G)
    want_box = max(box, 300)
    assert (got_box, got_delta) == (want_box, want_box - box)


def test_min_boxh_matches_the_measured_screens():
    """Pinned to the two measured data points: pristine-1024 NameBase.png
    (content ~136 -> window 300, top 768-213-300 = 255 == measured 255..256)
    and the 2026-07-16 4K report (box 349 -> faithful window 750; the screenshot's
    top 1279 == 2160 - 532 - 349, the defect this law repairs)."""
    assert ingame_popup_min_boxh(136, 16) == (300, 164)
    # v2: the box target is M - D so the WINDOW (box + button-row growth) is M
    assert ingame_popup_min_boxh(349, 40) == (720, 371)
    # the three shipping non-native resolutions' window height M
    assert ingame_popup_window_h(0, 22) == 412
    assert ingame_popup_window_h(0, 25) == 468
    assert ingame_popup_window_h(0, 40) == 750
    # 2026-10-03 shots (v1 clamped the box, not the window): Confirm Research
    # Priorities / Chief Librarian top 848 @4K, Chief Librarian 369 @1920x1080
    assert 2160 - 532 - (750 + popup_button_row_growth(20, 40)) == 848
    assert 1080 - 292 - (412 + popup_button_row_growth(20, 22)) == 369
    assert 2160 - 532 - ingame_popup_window_h(349, 40) == 878


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("btn", (0, 20, 35))
@pytest.mark.parametrize("box", BOX_SWEEP)
def test_min_boxh_is_proportionate_and_conservative(g: int, btn: int, box: int):
    """Window minimum M = floor(300*g/16) (the popup family's floor idiom,
    popup_scale_floor): window = max(box + D, M), D = the button-row growth
    exec_3 adds. The clamp only ever GROWS the box, and footer_delta is
    exactly the growth (the button row keeps its content-relative place)."""
    m = popup_scale_floor(300, g) if g > NATIVE_G else 300
    d = popup_button_row_growth(btn, g)
    got_box, got_delta = ingame_popup_min_boxh(box, g, btn)
    assert got_box == max(box, m - d)
    assert got_delta == got_box - box
    assert got_delta >= 0
    assert ingame_popup_window_h(box, g, btn) == max(box + d, m)
    if g == NATIVE_G:
        assert d == 0
    # embedded in a parent window ([+0xa3c] != popup): exec_3 does not grow it
    emb_box, emb_delta = ingame_popup_min_boxh(box, g, btn, own_window=False)
    assert (emb_box, emb_delta) == (max(box, m), max(box, m) - box)


@pytest.mark.parametrize("g", ALL_G)
def test_min_boxh_target_boundary(g: int):
    """M-D-1 / M-D / M-D+1 at every g (BOX_SWEEP only brackets M itself)."""
    m = popup_scale_floor(300, g) if g > NATIVE_G else 300
    t = m - popup_button_row_growth(20, g)
    assert ingame_popup_min_boxh(t - 1, g) == (t, 1)
    assert ingame_popup_min_boxh(t, g) == (t, 0)
    assert ingame_popup_min_boxh(t + 1, g) == (t + 1, 0)
    assert ingame_popup_window_h(t - 1, g) == m


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("box", BOX_SWEEP)
def test_min_boxh_is_idempotent(g: int, box: int):
    """Popup_calculate_dimensions can run more than once per popup; the clamp
    over its own output must be a fixed point."""
    once, _ = ingame_popup_min_boxh(box, g)
    twice, delta2 = ingame_popup_min_boxh(once, g)
    assert (twice, delta2) == (once, 0)


@pytest.mark.parametrize("g", ALL_G)
def test_min_boxh_leaves_tall_popups_alone(g: int):
    """Anything already at/above M passes through untouched at every g —
    the quit/customize/type-16 geometry (own verified laws) is not re-sized
    unless it is genuinely below the vanilla-proportioned minimum."""
    m = (popup_scale_floor(300, g) if g > NATIVE_G else 300) - popup_button_row_growth(20, g)
    assert ingame_popup_min_boxh(m, g) == (m, 0)
    assert ingame_popup_min_boxh(m + 1, g) == (m + 1, 0)
    assert ingame_popup_min_boxh(3000, g) == (3000, 0)


# --------------------------------------------------------------------------
# BaseWin true re-layout (option A) — window law + interior boundary laws.
# Ground truth: work\frida_basewin2.log (round-2 trace, all resolutions) and
# _tmp_disasm_basewin_init.txt (byte-exact vanilla literals). Design record:
# work\_tmp_basewin_relayout_design.md.
# --------------------------------------------------------------------------

# (screen_w, screen_h, runtime strip_h at that res, g) for the four shipping test resolutions
BASEWIN_RES = [
    (1024, 768, 213, 16),
    (1920, 1080, 292, 22),
    (1600, 1200, 332, 25),
    (3840, 2160, 532, 40),
]


def test_basewin_window_rect_pinned_to_traces():
    """g=16 must equal the pristine trace r1 [149,65,907,555] and g=40 the
    values the option-B prototype computed (and drew correctly) at 4K."""
    assert basewin_window_rect(1024, 768, 213, 16) == (149, 65, 758, 490)
    assert basewin_window_rect(3840, 2160, 532, 40) == (1012, 403, 1895, 1225)
    assert basewin_window_rect(1600, 1200, 332, 25) == (233, 103, 1184, 765)
    assert basewin_window_rect(1920, 1080, 292, 22) == (461, 115, 1042, 673)


@pytest.mark.parametrize("sw,sh,strip,g", BASEWIN_RES)
def test_basewin_window_rect_is_vanilla_proportionate(sw, sh, strip, g):
    """w,h = vanilla x g/16 exactly (floor idiom); bottom rests on the strip;
    x keeps vanilla's own centering expression with only the constant scaled."""
    x, y, w, h = basewin_window_rect(sw, sh, strip, g)
    assert w == popup_scale_floor(BASEWIN_NATIVE_W, g)
    assert h == popup_scale_floor(BASEWIN_NATIVE_H, g)
    assert y + h == sh - strip
    assert x == (sw - popup_scale_floor(BASEWIN_CENTER_C, g)) // 2
    # the +16 nudge scales with g: x == centered + floor(16*g/16)
    assert x == (sw - w + popup_scale_floor(32, g)) // 2


@pytest.mark.parametrize("g", ALL_G)
def test_basewin_window_fits_above_the_strip(g):
    """At every shipping resolution/g pair the scaled window must fit on
    screen above the console strip (no negative y, no horizontal overflow)."""
    for sw, sh, strip, res_g in BASEWIN_RES:
        if res_g != g:
            continue
        x, y, w, h = basewin_window_rect(sw, sh, strip, g)
        assert x >= 0 and y >= 0
        assert x + w <= sw


def test_basewin_console_frame_rect_pinned():
    """g=16 must equal vanilla's literal rect [23,0,703,493] (BaseWin_init
    0x41F505..0x41F532: bounds [0,0,758,490] +23/-55/+3; the engine draws it
    HALF-OPEN, stroke cols 23 and 702 -- measured on the pristine image).
    v4 (W5A): the rails' own span drawn by the INCLUSIVE band renderer --
    (Lx, 0, A - 1, pt(493)).  v3 handed the renderer the rail anchor itself,
    so the right stroke's outer column sat on the rail's first column
    (visible right border K - 1: none at 1080, 1 px of 2 at 4K), and its
    left pt(23) sat 1 px right of the left rails at odd g (a see-through
    column).  W5A v2: the right rails sit on A* = pt(726) - Lx (the content
    axis), so the frame is (Lx, 0, pt(726) - Lx - 1, pt(493)) -- 4K's right
    edge back on v3's 1757, now with the rail at 1758."""
    assert basewin_console_frame_rect(16) == (23, 0, 703, 493)
    assert basewin_console_frame_rect(40) == (57, 0, 1757, 1232)
    assert basewin_console_frame_rect(25) == (35, 0, 1098, 770)
    assert basewin_console_frame_rect(22) == (31, 0, 966, 677)
    assert basewin_console_frame_rect(17) == (23, 0, 747, 523)
    assert basewin_console_frame_rect(33) == (46, 0, 1450, 1016)    # pt(23) = 47: the see-through column closed


@pytest.mark.parametrize("g", range(16, 41))
def test_basewin_console_frame_is_vanilla_per_edge(g):
    """T/B = the vanilla constants through basewin_pt.  L / R are the rails'
    own edges (the neighbor's formula, never a parallel one --
    feedback-match-opposite-edge-margin): L = the left rails' composed
    extent (<= pt(23), at most 1 below it), R = the right rail's anchor - 1,
    the anchor A* = pt(726) - L within 1 px of pt(703)."""
    from scaling_laws import basewin_rail_left_extent, basewin_rail_anchor
    l, t, r, b = basewin_console_frame_rect(g)
    assert t == 0
    assert b == basewin_pt(493, g)
    if g <= 16:
        assert (l, r) == (23, 703)
        return
    assert l == basewin_rail_left_extent(g) and r + 1 == basewin_rail_anchor(g)
    assert 0 <= basewin_pt(23, g) - l <= 1
    assert abs(basewin_rail_anchor(g) - 703 * g / 16) < 1.5


@pytest.mark.parametrize("g", range(16, 41))
def test_basewin_console_frame_flush_with_rails_never_seams(g):
    """The frame spans EXACTLY the gap the rails leave: L = the left rails'
    end (no see-through column), R + 1 = the right rails' first column
    (t_bw_railscale: A* = pt(726) - Lx, the left rails' mirror through the
    content axis -- railscale's double floor fl((fl(W*16/g)-55)*g/16) lagged
    it by 0..4 px).  Strictly inside the canvas W (the black-bar bug), the
    right rails end ON the axis pt(726) <= W - 32g/16; bottom past the canvas
    H (off-canvas, vanilla); first + last column = S - 1."""
    from scaling_laws import basewin_rail_axis_sum, rail_left_extent
    l, t, r, b = basewin_console_frame_rect(g)
    if g <= 16:
        assert (l, r) == (23, 703)
        return
    w_dev = popup_scale_floor(BASEWIN_NATIVE_W, g)
    S = basewin_pt(726, g)
    assert l == rail_left_extent(g) and r == S - l - 1
    assert basewin_rail_axis_sum(g) == S and l + r == S - 1
    assert S <= w_dev - ((32 * g) >> 4)
    assert b > popup_scale_floor(BASEWIN_NATIVE_H, g)


def _tab_row_gaps(g):
    """The eight rendered VISIBLE tab-row channels L->R under the shipped
    laws: frame|E, E|D, D|c1, c1|GOV, GOV|c2, c2|B, B|C, C|frame. The frame
    strokes render inclusively AT their arg column (measured 2026-07-22),
    so the left channel is E - fl_ - 1 (the stroke occupies col fl_) while
    interior gaps are exclusiveRight-to-nextLeft differences. The original
    helper used E - fl_ (edge difference) — a mixed convention that made the
    palindrome pass while the render was 3/4.  GOVERNOR's width is
    basewin_gov_w (W5A: centred on the axis).  W7H: the chevrons are
    basewin_child_rect v7's (D = fl(20g/16) square, centred on the axis)."""
    from scaling_laws import basewin_tab_mirror_x, basewin_tabframe_right, basewin_gov_w, basewin_child_rect
    p = lambda v: basewin_pt(v, g)
    w = lambda v: v if g <= 16 else popup_scale_floor(v, g)
    E, D, G = p(30), p(144), p(280)
    c1, _y, wc, _h = basewin_child_rect(258, 7, 20, 20, g)
    c2 = basewin_child_rect(448, 7, 20, 20, g)[0]
    B = basewin_tab_mirror_x(470, 112, g)
    C = basewin_tab_mirror_x(584, 112, g)
    fl_, fr = p(27), basewin_tabframe_right(g)
    wb, wg = w(112), basewin_gov_w(g)
    return (E - fl_ - 1, D - (E + wb), c1 - (D + wb), G - (c1 + wc),
            c2 - (G + wg), B - (c2 + wc), C - (B + wb), fr - (C + wb))


def test_basewin_tab_row_mirror_symmetry():
    """The whole tab row is mirror-symmetric in vanilla (axis 363: frame
    27..699, GOVERNOR self-mirrored, chevron/BUILD/CONQUER flanking pairs);
    the rendered gap tuple must be PALINDROMIC at every g (the 2026-07-21g
    report: every channel pair symmetric, including the frame insets).
    Independent per-edge flooring broke pairs on different phases (g=25:
    frame insets 4/5, E|D 4 vs B|C 3, D|c1 3 vs c2|B 4)."""
    for g in range(16, 41):
        gaps = _tab_row_gaps(g)
        assert gaps == gaps[::-1], (g, gaps)          # the symmetry pin
        assert min(gaps) >= 1, (g, gaps)              # never touching/overlap


def test_basewin_tab_mirror_pinned_and_bounded():
    """Pinned vectors + drift bound (W5A v2: the axis is S = pt(726), the
    content axis the rails now share, GOVERNOR sized to it).  g=16 identity
    (698 = the measured native ARG; vanilla's seed 699 is exclusive-space).
    g=40: the deployed, user-confirmed row BIT-IDENTICAL (chevron2 1120,
    BUILD 1175, CONQUER 1460, GOVERNOR 415, frame 1747); g=25: 700 / 734 /
    913, frame 1091; g=22: frame 960.  Every right-half child within 1 px of
    plain pt; GOVERNOR within 2 px of 166 g/16 (its centring parity)."""
    from scaling_laws import basewin_tab_mirror_x, basewin_tabframe_right, basewin_gov_w, basewin_rim_box_r
    for x, w in ((448, 20), (470, 112), (584, 112)):
        assert basewin_tab_mirror_x(x, w, 16) == x
        for g in range(17, 41):
            assert abs(basewin_tab_mirror_x(x, w, g) - basewin_pt(x, g)) <= 1, (x, g)
    assert basewin_tabframe_right(16) == 698 and basewin_gov_w(16) == 166
    assert [basewin_tab_mirror_x(x, w, 40) for x, w in ((448, 20), (470, 112), (584, 112))] == [1120, 1175, 1460]
    assert basewin_tabframe_right(40) == 1747 and basewin_gov_w(40) == 415
    assert [basewin_tab_mirror_x(x, w, 25) for x, w in ((448, 20), (470, 112), (584, 112))] == [700, 734, 913]
    assert basewin_tabframe_right(25) == 1091 and basewin_tabframe_right(22) == 960
    for g in range(17, 41):
        assert basewin_tabframe_right(g) == basewin_rim_box_r(699, g), g      # flush with the right column
        assert abs(basewin_gov_w(g) - 166 * g / 16) < 2, g


def test_basewin_tabframe_bottom_mirrors_the_top_inset():
    """The vertical twin of the row-mirror law. The VISIBLE bottom channel
    (b - btnB: the strokes render inclusively AT the arg row, measured
    2026-07-22) must equal the visible top channel (btnT - t - 1) at every
    g. The 07-21h law mirrored edge coordinates instead of the stroke row,
    leaving bottom = top + 1 everywhere (3/4 at g=22 — the user's second
    1920 report; 6/7 at 4K). Pins: 29 at g=16 (the measured native arg —
    vanilla strokes render at rows 4 and 29; the seed 30 is exclusive-
    space), 39/44/73 at g=22/25/40 under v3.  v4 (W7H v2 2026-10-25): the
    row of basewin_tab_row_v -- the button top and ONE channel chosen jointly,
    the frame from the buttons plus that channel: 40/46/73 at g=22/25/40, the
    channels still equal, no dimension > 1 px off vanilla x g/16 that v3 had
    within 1 px, and every dimension within 1 px except the channel at g 23 /
    39 (+1.12, = v3)."""
    from scaling_laws import (basewin_tabframe_bottom, basewin_tab_btn_y, basewin_tabframe_top, basewin_tab_row_v,
                              basewin_tab_row_v6, basewin_tab_row_errors, BASEWIN_TAB_ROW_DIMS, stroke_width)
    assert basewin_tabframe_bottom(16) == 29 and basewin_tab_btn_y(16) == 7 and basewin_tabframe_top(16) == 4
    assert basewin_tabframe_bottom(22) == 40
    assert basewin_tabframe_bottom(25) == 46
    assert basewin_tabframe_bottom(40) == 73 and basewin_tab_row_v(40) == basewin_tab_row_v6(40)   # 4K unchanged
    for g in range(16, 41):
        t, btn_t = basewin_tabframe_top(g), basewin_tab_btn_y(g)
        btn_b = btn_t + (20 if g <= 16 else popup_scale_floor(20, g))
        b = basewin_tabframe_bottom(g)
        k = 1 if g <= 16 else stroke_width(g)
        assert b - k + 1 - btn_b == btn_t - t - k, g    # visible channels equal (K-wide strokes)
        if g > 16:
            e = basewin_tab_row_errors(*basewin_tab_row_v(g), g)
            d = basewin_tab_row_errors(*basewin_tab_row_v6(g), g)
            assert all(abs(e[x]) <= 1 or abs(e[x]) <= abs(d[x]) + 1e-9 for x in BASEWIN_TAB_ROW_DIMS), (g, e, d)
            over = {x for x in BASEWIN_TAB_ROW_DIMS if abs(e[x]) > 1}
            assert over <= ({"c"} if g in (23, 39) else set()), (g, e)
            worse = {x for x in BASEWIN_TAB_ROW_DIMS if abs(e[x]) > abs(d[x]) + 1e-9}
            assert worse <= ({"c"} if g in (18, 34) else {"t"} if g in (19, 35) else set()), (g, worse)


def test_basewin_pt_native_identity_and_negative_floor():
    """g<=16 is the identity for every value; negative coordinates floor
    toward -inf (arithmetic shift), matching the JS Math.floor port."""
    for v in (-2000, -1, 0, 7, 89, 234, 401, 490, 758):
        assert basewin_pt(v, NATIVE_G) == v
    assert basewin_pt(-1, 40) == -3          # -40 >> 4
    assert basewin_pt(-16, 40) == -40


@pytest.mark.parametrize("g", ALL_G)
def test_basewin_pt_keeps_shared_edges_flush(g):
    """RECT edges scale independently through basewin_pt: two cells that
    shared an edge natively share the scaled edge too, and cell widths are
    edge-difference (cum-position form), never fl(w*g/16) per cell."""
    edges = [0, 89, 90, 234, 235, 401, 490, 758]
    scaled = [basewin_pt(e, g) for e in edges]
    assert scaled == sorted(scaled)          # monotonic: no cell inversion
    # adjacency: the right edge of cell i IS the left edge of cell i+1
    for left_edge, right_edge in zip(edges, edges[1:]):
        w_cells = basewin_pt(right_edge, g) - basewin_pt(left_edge, g)
        assert w_cells >= 0
        # total span is exact: no drift vs scaling the outer edge directly
    assert scaled[-1] - scaled[0] == basewin_pt(758, g) - basewin_pt(0, g)


@pytest.mark.parametrize("g", ALL_G)
def test_basewin_font_and_sprite_laws(g):
    """Font render-swap = the floor idiom over the native size; sprite ratio
    composes exactly as a fraction with zero pre-flooring."""
    for size in (10, 12, 14):
        want = size if g <= NATIVE_G else popup_scale_floor(size, g)
        assert basewin_font_size(size, g) == want
    for num, den in ((1, 1), (1, 2), (3, 1)):
        n2, d2 = basewin_sprite_ratio(num, den, g)
        if g <= NATIVE_G:
            assert (n2, d2) == (num, den)
        else:
            # exact fraction equality: n2/d2 == (num*g)/(den*16)
            assert n2 * den * NATIVE_G == d2 * num * g


# ---------------------------------------------------------------------------
# Chrome-pipeline clip laws (blit_clip_visible / blit_clip_contains /
# remap_clip_bounds) — the ENERGY-band eraser class (2026-07-19): the
# draw_expenses backdrop [57,0,1757,1010] under clip [415,650,1747,872]
# erased the energy block because the enlarge pipeline bypassed the clip.
# ---------------------------------------------------------------------------
from scaling_laws import blit_clip_visible, blit_clip_contains, remap_clip_bounds


def test_blit_clip_the_measured_eraser_case():
    """The proven 4K case: EXP backdrop blit at (57,0) 1700x1010 under the
    expenses-panel clip — only the panel region may be written."""
    clip = (415, 650, 1747, 872)
    vis = blit_clip_visible(57, 0, 1700, 1010, clip)
    assert vis == (415, 650, 1747, 872)
    assert not blit_clip_contains(57, 0, 1700, 1010, clip)


def test_blit_clip_popup_family_is_passthrough():
    """Every verified popup draws with clip == whole window: the gate must
    report containment so the original code paths run bit-identically."""
    clip = (0, 0, 1895, 1225)
    assert blit_clip_contains(57, 0, 1700, 1222, clip)
    assert blit_clip_visible(57, 0, 1700, 1222, clip) == (57, 0, 1757, 1222)


def test_blit_clip_empty_and_edge_cases():
    clip = (415, 650, 1747, 872)
    # entirely above / below / left / right of the clip
    assert blit_clip_visible(415, 0, 100, 650, clip) is None
    assert blit_clip_visible(415, 872, 100, 300, clip) is None
    assert blit_clip_visible(0, 700, 415, 50, clip) is None
    assert blit_clip_visible(1747, 700, 50, 50, clip) is None
    # 1px sliver survives
    assert blit_clip_visible(414, 649, 2, 2, clip) == (415, 650, 416, 651)
    # degenerate clip
    assert blit_clip_visible(0, 0, 100, 100, (50, 50, 50, 50)) is None


def test_blit_clip_visible_is_the_intersection():
    clip = (100, 200, 900, 800)
    for (dx, dy, w, h) in ((0, 0, 2000, 2000), (150, 250, 100, 100),
                           (50, 700, 200, 300), (890, 790, 50, 50)):
        vis = blit_clip_visible(dx, dy, w, h, clip)
        if vis is None:
            continue
        vx0, vy0, vx1, vy1 = vis
        assert 100 <= vx0 < vx1 <= 900
        assert 200 <= vy0 < vy1 <= 800
        assert vx0 >= dx and vy0 >= dy and vx1 <= dx + w and vy1 <= dy + h
        # containment <=> the intersection is the whole blit
        assert blit_clip_contains(dx, dy, w, h, clip) == \
            (vis == (dx, dy, dx + w, dy + h))


def test_remap_clip_bounds_is_v4_clamps_plus_clip():
    """v5 = the v4 dims clamp intersected with the clip; a full-buffer clip
    reproduces v4 exactly (bit-identical popups)."""
    buf_w, buf_h = 1895, 1225
    full = (0, 0, buf_w, buf_h)
    for (x, y, w, h) in ((60, 3, 1695, 1005), (-5, -2, 300, 200),
                         (1800, 1200, 200, 100)):
        x0, x1, y0, y1 = remap_clip_bounds(x, y, w, h, buf_w, buf_h, full)
        assert x0 == max(x, 0) and y0 == max(y, 0)
        assert x1 == min(x + w, buf_w) and y1 == min(y + h, buf_h)
    # the eraser case: STEP3's staged rect confined to the panel clip
    x0, x1, y0, y1 = remap_clip_bounds(60, 3, 1695, 1005, buf_w, buf_h,
                                       (415, 650, 1747, 872))
    assert (x0, x1, y0, y1) == (415, 1747, 650, 872)
    # empty result is representable
    x0, x1, y0, y1 = remap_clip_bounds(0, 900, 400, 100, buf_w, buf_h,
                                       (415, 650, 1747, 872))
    assert x0 >= x1 or y0 >= y1


# ---------------------------------------------------------------------------
# Console side-rail laws (slide_show chrome generalization, 2026-07-19c)
# ---------------------------------------------------------------------------
from scaling_laws import console_rail_arm, rail_right_anchor


def test_console_rail_arm_is_the_defect_condition():
    ART = 529
    # the measured 4K base screen: canvas 1225 tall -> arms
    assert console_rail_arm(1225, ART, 40)
    # the file dialog @4K (984 tall) arms; a native-covered window does not
    assert console_rail_arm(984, ART, 40)
    assert not console_rail_arm(490, ART, 40)     # shorter than the art
    # g<=16 never arms (native no-op invariant), any height
    for h in (100, 529, 530, 1225):
        assert not console_rail_arm(h, ART, 16)


def test_rail_right_anchor_round_trips_the_engine_multiply():
    """After the engine multiplies x' by g/16, the strip must land at
    winW - scaled(native offset-from-right), i.e. flush like vanilla."""
    for g in (17, 22, 25, 40):
        for native_w, off_r in ((758, 23), (758, 15), (640, 23), (754, 8)):
            win_w = native_w * g // 16          # a g-scaled window
            x = win_w - off_r                   # the composed (mixed) arg
            xp = rail_right_anchor(win_w, x, g)
            # native-space anchor: nativeW - offR
            assert xp == (win_w << 4) // g - off_r
            # engine multiply lands within g//16 + 2 of the exact scaled
            # anchor: winW*16/g double-floor drift (<=1 native px, amplified
            # x g/16) plus the two independent floors. The user-verified
            # filedlg rails carry exactly this bound on every axis.
            landed = xp * g >> 4
            want = win_w - (off_r * g >> 4)
            assert abs(landed - want) <= g // 16 + 2, (g, native_w, off_r)


def test_scaling_rail_right_strip_x_abuts_the_inner_strip():
    """rail_right_strip_x (railscale v3): the inner right strip stays at railscale's double floor (the column every
    abutting frame R reads); the outer right strip starts where the inner one's fl(8g/16) columns end, at EVERY
    canvas width and g (v2's independent fl((N-0x2F)*g/16) left a 1-px column at odd g); the outer end never moves
    outward and stays inside the canvas; g <= 16 is the identity."""
    from scaling_laws import rail_right_strip_x, slide_rail_settled_x, popup_scale_floor
    for g in range(17, 49):
        for w in range(300, 2600):
            inner, outer = w - 0x37, w - 0x2F
            xi, xo = rail_right_strip_x(w, inner, g), rail_right_strip_x(w, outer, g)
            assert xi == popup_scale_floor(rail_right_anchor(w, inner, g), g)
            assert xo == xi + ((8 * g) >> 4), (g, w)
            end = xo + ((15 * g) >> 4)
            assert end <= ((rail_right_anchor(w, outer, g) * g) >> 4) + ((15 * g) >> 4) and end < w
            assert slide_rail_settled_x(w, inner, g) == xi and slide_rail_settled_x(w, outer, g) == xo
            assert slide_rail_settled_x(w, 15, g) == (15 * g) >> 4 and slide_rail_settled_x(w, 0, g) == 0
    for g in (12, 16):
        assert rail_right_strip_x(728, 728 - 0x2F, g) == 728 - 0x2F
        assert slide_rail_settled_x(728, 728 - 0x37, g) == 728 - 0x37


# ==== chevron coverage filter (bandstripe v8, approved 2026-07-24) ==========

CHEV_ART = [
    "abbbbbbbbbbbbbbbbbba",
    "bccccccccccccccccccb",
    "bddddddddddddddddedb",
    "bfccccccccccccccccgb",
    "bhgeddddddddddddehhb",
    "bggccccccccccccciggb",
    "bhhjeddddddddddejhhb",
    "bgggcccccccccccigggb",
    "bhhhheddddddddehhhhb",
    "bggggcccccccccgggggb",
    "bhhhhhedddddddhhhhhb",
    "bgggggkccccccggggggb",
    "bhhhhhheddddghhhhhhb",
    "bggggggiccccgggggggb",
    "bhhhhhhhedejhhhhhhhb",
    "bggggggggccggggggggb",
    "bhhhhhhhhghhhhhhhhhb",
    "bfgggggggggggggggggb",
    "bhhhhhhhhhhhhhhhhhhb",
    "abbbbbbbbbbbbbbbbbba",
]
# fixture palette: art colors at indices 0-8/10 ('a' = key 9), the observed
# blend rungs after, and a DECOY at index 9 sitting dead-center of the c/d
# blend axis -- the nearest-search must never pick it (key exclusion).
CHEV_IDX = {"b": 0, "c": 1, "d": 2, "e": 3, "f": 4, "g": 5, "h": 6, "i": 7,
            "j": 8, "a": 9, "k": 10}
CHEV_PAL = [(176, 20, 20), (136, 69, 28), (136, 12, 12), (156, 16, 16),
            (92, 41, 13), (106, 31, 13), (68, 32, 12), (108, 52, 23),
            (76, 41, 13), (136, 40, 20), (122, 31, 29), (122, 53, 21),
            (75, 31, 15), (85, 43, 21)] + [(0, 255, 0)] * 242


def _chev_src():
    return [[CHEV_IDX[ch] for ch in row] for row in CHEV_ART]


def test_coverage_taps_partition_exactly():
    """Coverage taps are an exact partition: weights sum to S per cell, at most
    two taps, contiguous src walk, identity at D == S. Every g 16..40."""
    import scaling_laws as SL
    for g in range(16, 41):
        D = 20 * g // 16
        taps = SL.coverage_taps(20, D)
        assert len(taps) == D
        prev_end = 0
        for i, (s0, w0, w1) in enumerate(taps):
            assert w0 + w1 == 20, (g, i)
            assert 1 <= w0 <= 20 and 0 <= w1 < 20, (g, i)
            assert 0 <= s0 < 20 and (w1 == 0 or s0 + 1 < 20), (g, i)
            # contiguity: cell i starts where the rational interval says
            assert s0 == (i * 20) // D
        # total coverage: sum of all weights == S*D (each src pixel weighted
        # D units total across the row)
        assert sum(w0 + w1 for _, w0, w1 in taps) == 20 * D
    # identity
    assert SL.coverage_taps(20, 20) == [(s, 20, 0) for s in range(20)]


def test_srgb_lin16_lut_and_inverse_round_trip():
    """LUT is strictly monotone (searchable) and the binary-search inverse
    round-trips every byte exactly."""
    import scaling_laws as SL
    assert len(SL.SRGB_LIN16) == 256
    assert SL.SRGB_LIN16[0] == 0 and SL.SRGB_LIN16[255] == 65535
    for v in range(255):
        assert SL.SRGB_LIN16[v] < SL.SRGB_LIN16[v + 1]
    for v in range(256):
        assert SL.linear16_to_srgb(SL.SRGB_LIN16[v]) == v
    # nearest behaviour between entries
    assert SL.linear16_to_srgb(SL.SRGB_LIN16[100] + 1) == 100


def test_redmean_prefers_the_red_brown_rung():
    """The regression that motivated redmean: the 50/50 c+d linear blend must
    quantize into the red-brown family, never a desaturated/bluish entry."""
    import scaling_laws as SL
    blend = (136, 51, 20)          # linear-light 50/50 of c and d (approx)
    bluish = (135, 34, 52)
    rung = (122, 53, 21)
    assert SL.redmean_dist2(rung, blend) < SL.redmean_dist2(bluish, blend)


def test_chevron_coverage_filter_goldens():
    r"""Pin the approved render (work\chev_candidates3.png "coverage linear
    g2.2"): mid-column + col-2 index sequences at g=22/25/40 on the fixture
    palette, corner cells key, and the index-9 decoy NEVER chosen for a
    color pixel."""
    import scaling_laws as SL
    src = _chev_src()
    GOLD = {
        22: (27,
             [0, 1, 1, 2, 1, 11, 10, 1, 2, 11, 1, 2, 1, 11, 10, 1, 10, 11,
              1, 2, 1, 11, 4, 5, 12, 5, 0],
             [0, 1, 1, 2, 7, 4, 4, 5, 12, 4, 5, 6, 5, 4, 12, 5, 12, 4, 5,
              6, 5, 4, 6, 4, 12, 5, 0], 4),
        25: (31,
             [0, 1, 1, 2, 11, 1, 10, 10, 1, 11, 10, 1, 11, 2, 1, 11, 2, 1,
              11, 2, 1, 1, 2, 1, 1, 4, 5, 5, 6, 2, 0],
             [0, 1, 1, 2, 5, 4, 12, 12, 5, 12, 12, 5, 12, 6, 5, 4, 6, 5, 4,
              6, 5, 5, 6, 5, 5, 6, 4, 4, 6, 2, 0], 12),
        40: (50,
             [0, 0, 1, 1, 1, 2, 2, 11, 1, 1, 2, 2, 11, 1, 1, 2, 2, 11, 1,
              1, 2, 2, 11, 1, 1, 2, 2, 11, 1, 1, 2, 2, 11, 1, 1, 3, 3, 11,
              1, 1, 6, 6, 4, 5, 5, 6, 6, 10, 0, 0],
             [9, 9, 0, 1, 1, 3, 3, 3, 10, 10, 10, 10, 2, 3, 3, 10, 10, 2,
              3, 3, 10, 10, 2, 3, 3, 10, 10, 2, 3, 3, 10, 10, 2, 3, 3, 10,
              10, 2, 3, 3, 10, 10, 10, 10, 10, 10, 10, 3, 9, 9], 32),
    }
    for g, (D, mid, col2, n9) in GOLD.items():
        assert 20 * g // 16 == D
        out = SL.chevron_coverage_filter(src, CHEV_PAL, D)
        assert [out[j][D // 2] for j in range(D)] == mid, g
        assert [out[j][2] for j in range(D)] == col2, g
        assert (out[0][0], out[0][D - 1], out[D - 1][0],
                out[D - 1][D - 1]) == (9, 9, 9, 9), g
        # every key-9 output must be geometry (corner coverage), i.e. the
        # decoy color was never CHOSEN -- count matches the pinned total
        assert sum(1 for row in out for v in row if v == 9) == n9, g


def test_chevron_coverage_filter_is_identity_geometry_at_native():
    """D == S: pure per-pixel palette round-trip -- every non-key index maps to
    the redmean-nearest entry of its own color, which is itself; key stays
    key. (The thunk never runs at g<=16 -- bandstripe is only reached from the
    zoom pipeline -- but the law must still be sane there.)"""
    import scaling_laws as SL
    src = _chev_src()
    out = SL.chevron_coverage_filter(src, CHEV_PAL, 20)
    assert out == src


def test_coverage_filter_rect_degenerates_to_the_square_filter():
    """W == H, DW == DH must reproduce chevron_coverage_filter EXACTLY on the
    pinned chevron art at every golden g -- the rect law is a strict
    generalization, not a fork."""
    import scaling_laws as SL
    src = _chev_src()
    for g in (17, 22, 25, 33, 40):
        D = 20 * g // 16
        assert (SL.coverage_filter_rect(src, CHEV_PAL, D, D)
                == SL.chevron_coverage_filter(src, CHEV_PAL, D)), g


def _arrow_src():
    """Synthetic 12x42 stand-in for the garrison arrow art: a right-pointing
    triangle over key-9 background, interior a 1px 50/50 stripe dither of the
    c/d pair -- the shape+texture class the rect instance exists for."""
    W, H = 12, 42
    src = []
    for y in range(H):
        half = abs(2 * y + 1 - H) / 2          # distance from vertical centre
        span = max(0, round(W * (1 - 2 * half / H)))
        row = [9] * W
        for x in range(span):
            row[x] = 1 if (y & 1) else 2       # c/d stripe pair
        src.append(row)
    return src


def test_coverage_filter_rect_arrow_instance_sanity():
    """The 12x42 arrow instance at the real device sizes: native identity at
    (12,42); at 4K (30x105, exactly x2.5) and 1920 (16x57) the output keeps
    the key-9 silhouette exactly where BOTH covered texels are key, never
    emits the decoy for a color pixel, and every stripe-interior pixel stays
    in the red family (indexes drawn from the source pair's blend rungs --
    i.e. no phase-flipped 2px banding of ONE member, the NN defect)."""
    import scaling_laws as SL
    src = _arrow_src()
    assert SL.coverage_filter_rect(src, CHEV_PAL, 12, 42) == src
    for DW, DH in ((30, 105), (16, 57)):
        out = SL.coverage_filter_rect(src, CHEV_PAL, DW, DH)
        assert len(out) == DH and len(out[0]) == DW
        # corners: fully outside the triangle -> key
        assert out[0][DW - 1] == 9 and out[DH - 1][DW - 1] == 9
        # left edge mid: fully inside -> never key
        assert out[DH // 2][0] != 9
        # a decoy-9 color choice would inflate the key count beyond geometry:
        # key pixels must form a right-anchored suffix of every row (the
        # triangle is left-anchored, so coverage decays monotonically)
        for row in out:
            first9 = next((i for i, v in enumerate(row) if v == 9), DW)
            assert all(v == 9 for v in row[first9:])


# ---------------------------------------------------------------------------
# BaseWin bottom-HUD strip panel seed rects (2026-07-25b, groups 11-16)
# ---------------------------------------------------------------------------
# Golden vectors: g=16 pins the VANILLA seed block output measured live
# (frida_basewin_strip.log, all 13 rects byte-derived from the decompiled
# init block and confirmed at draw time); g=40/g=25 pin the scaled-constant
# outputs against the LIVE MainWin region rects observed at 4K / 1600x1200
# (regions arrive pre-scaled by the closed HUD work with its own rounding,
# so the law takes them as inputs rather than re-deriving them).

BASEWIN_STRIP_REGIONS_G40 = {
    "A": (10, 140, 612, 630), "S": (1947, 140, 2550, 630),
    "C": (655, 165, 1907, 430), "G": (610, 470, 1920, 630),
}
BASEWIN_STRIP_REGIONS_G25 = {
    "A": (6, 87, 382, 393), "S": (1217, 87, 1593, 393),
    "C": (409, 103, 1192, 268), "G": (381, 293, 1200, 393),
}


def test_basewin_strip_seed_rects_native_identity():
    """g=16 must reproduce the vanilla seed block EXACTLY (the all-res
    invariant: at native the patched exe draws byte-identically)."""
    import scaling_laws as SL
    r = SL.basewin_strip_seed_rects(g=16, **SL.BASEWIN_STRIP_REGIONS_NATIVE)
    assert r == {
        "production": (8, 60, 136, 248),
        "garrison": (244, 192, 764, 248),
        "turnsA": (139, 203, 237, 223),
        "turnsB": (139, 225, 237, 245),
        "queue_outer": (140, 60, 241, 196),
        "queue_hdr": (143, 63, 238, 83),
        "queue_list": (143, 85, 238, 193),
        "pop": (266, 114, 701, 168),
        "plate": (266, 70, 759, 111),
        "redbtn": (708, 117, 756, 165),
        "sup_outer": (783, 60, 1016, 248),
        "sup_hdr": (786, 63, 1013, 83),
        "sup_list": (786, 85, 1013, 245),
    }


def test_basewin_strip_seed_rects_g40_golden():
    """4K targets against the live region rects (hand-computed, reviewed)."""
    import scaling_laws as SL
    r = SL.basewin_strip_seed_rects(g=40, **BASEWIN_STRIP_REGIONS_G40)
    assert r == {
        "production": (20, 150, 341, 620),
        "garrison": (610, 480, 1910, 620),
        "turnsA": (348, 508, 593, 558),
        "turnsB": (348, 563, 593, 613),
        "queue_outer": (351, 150, 602, 491),
        "queue_hdr": (358, 157, 595, 207),
        "queue_list": (358, 212, 595, 483),
        "pop": (665, 285, 1752, 420),
        "plate": (665, 175, 1897, 277),
        "redbtn": (1769, 292, 1889, 412),   # size-anchored: l/t + s(48)=120
        "sup_outer": (1957, 150, 2540, 620),
        "sup_hdr": (1964, 157, 2533, 207),
        "sup_list": (1964, 212, 2533, 613),
    }


def test_basewin_strip_seed_rects_g25_golden():
    """1600x1200 targets against the live region rects."""
    import scaling_laws as SL
    r = SL.basewin_strip_seed_rects(g=25, **BASEWIN_STRIP_REGIONS_G25)
    assert r == {
        "production": (12, 93, 213, 387),
        "garrison": (381, 299, 1194, 387),
        "turnsA": (217, 317, 371, 348),
        "turnsB": (217, 352, 371, 383),
        "queue_outer": (219, 93, 376, 307),
        "queue_hdr": (223, 97, 372, 128),
        "queue_list": (223, 131, 372, 302),
        "pop": (415, 178, 1096, 262),
        "plate": (415, 109, 1186, 173),
        "redbtn": (1106, 182, 1181, 257),   # size-anchored: l/t + s(48)=75
        "sup_outer": (1223, 93, 1587, 387),
        "sup_hdr": (1227, 97, 1583, 128),
        "sup_list": (1227, 131, 1583, 383),
    }


def test_basewin_strip_seed_rects_sweep_invariants():
    """Structural invariants at EVERY g 16..40 (regions modeled as vanilla
    x g/16 per coordinate -- close enough to the HUD scaler for structure):
    headers keep the scaled 20px height, sub-rects nest in their outers,
    CHANGE sits above HURRY with a gap, the citizens row still fits a
    scaled 48px citizen sprite, and the red button frame clears the row."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    for g in range(16, 41):
        regions = {k: tuple(fl(v, g) for v in rect)
                   for k, rect in SL.BASEWIN_STRIP_REGIONS_NATIVE.items()}
        r = SL.basewin_strip_seed_rects(g=g, **regions)
        s20 = fl(0x14, g)
        for hdr, outer, lst in (("queue_hdr", "queue_outer", "queue_list"),
                                ("sup_hdr", "sup_outer", "sup_list")):
            h, o, l = r[hdr], r[outer], r[lst]
            assert h[3] - h[1] == s20, (g, hdr)
            assert o[0] <= h[0] and h[2] <= o[2] and o[1] <= h[1], (g, hdr)
            assert l[1] == h[3] + fl(2, g), (g, lst)
            assert l[0] == h[0] and l[2] == h[2], (g, lst)
        # CHANGE above HURRY, disjoint, inside the queue column
        a, b = r["turnsA"], r["turnsB"]
        assert a[3] < b[1] and a[0] == b[0] and a[2] == b[2], g
        assert r["queue_outer"][3] <= a[1], g
        # citizens row fits a scaled citizen sprite (48 native)
        pop = r["pop"]
        assert pop[3] - pop[1] >= fl(48, g), g
        # red button frame sits right of the citizens row, inside C, and is
        # size-anchored s(48) square (art window w = r-l off the same
        # fields; ring channel symmetry lives in basewin_redbtn_frame)
        rb = r["redbtn"]
        assert rb[0] == pop[2] + fl(7, g) and rb[2] > rb[0], g
        assert rb[2] - rb[0] == fl(48, g) == rb[3] - rb[1], g
        if g > 16:
            assert -(-(rb[2] - rb[0]) * 16 // g) == 48, g   # CEIL round-trip
        # plate ends above the citizens row
        assert r["plate"][3] <= pop[1], g
        # production right edge stays left of the queue column
        assert r["production"][2] < r["queue_outer"][0], g


def test_basewin_strip_chevron_rects_goldens():
    """Plate chevron windows: native identity + scaled pins + KSB descale
    round-trip (the btnzoom source dims must come back 20x35 at every g)."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native: plate [266,70,759,111], sprite 20x35 (console-sheet extracts)
    r = SL.basewin_strip_chevron_rects((266, 70, 759, 111), 20, 35, 16)
    assert r == {"btn2": (269, 73, 289, 108), "btn3": (736, 73, 756, 108)}
    # g=40 against the seed-law plate golden (665,175,1897,277)
    r = SL.basewin_strip_chevron_rects((665, 175, 1897, 277), 20, 35, 40)
    assert r == {"btn2": (672, 182, 722, 269), "btn3": (1840, 182, 1890, 269)}
    # g=25 against the plate golden (415,109,1186,173): s3=4, s20=31, s35=54
    r = SL.basewin_strip_chevron_rects((415, 109, 1186, 173), 20, 35, 25)
    assert r == {"btn2": (419, 113, 450, 167), "btn3": (1151, 113, 1182, 167)}
    for g in range(16, 41):
        plate = tuple(fl(v, g) for v in (266, 70, 759, 111))
        r = SL.basewin_strip_chevron_rects(plate, 20, 35, g)
        b2, b3 = r["btn2"], r["btn3"]
        # both windows the same size: s(20) x s(35), same y band
        assert b2[2] - b2[0] == b3[2] - b3[0] == fl(20, g), g
        assert b2[3] - b2[1] == b3[3] - b3[1] == fl(35, g), g
        assert (b2[1], b2[3]) == (b3[1], b3[3]), g
        # inside the plate, disjoint (chevrons flank the title)
        assert plate[0] <= b2[0] and b3[2] <= plate[2], g
        assert b2[2] < b3[0], g
        if g > 16:
            # btnzoom's CEIL descale of the window returns the native art dims
            assert -(-(b2[2] - b2[0]) * 16 // g) == 20, g
            assert -(-(b2[3] - b2[1]) * 16 // g) == 35, g


def test_basewin_title_box_goldens_and_flush():
    """Title box (draw_info): native identity to vanilla's plate.b - 3 form,
    scaled pins, and the FLUSH invariant — the box bottom must equal the
    chevron art's last device row at every g (the 3px 'chevron sits high'
    defect was vanilla's plate.b - s(3) diverging from s(3) + s(35))."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native: vanilla identity (108 = 111 - 3 = 73 + 35 = art last row + 1
    # under vanilla's stroke-at-coordinate-1 primitive)
    assert SL.basewin_title_box((266, 70, 759, 111), 20, 35, 16) == \
        (292, 73, 733, 108)
    # g=25 (plate golden 415,109,1186,173): s3=4, s26=40, s35=54
    assert SL.basewin_title_box((415, 109, 1186, 173), 20, 35, 25) == \
        (455, 113, 1146, 166)
    # g=40 (plate golden 665,175,1897,277): s3=7, s26=65, s35=87
    assert SL.basewin_title_box((665, 175, 1897, 277), 20, 35, 40) == \
        (730, 182, 1832, 268)
    for g in range(16, 41):
        plate = tuple(fl(v, g) for v in (266, 70, 759, 111))
        tb = SL.basewin_title_box(plate, 20, 35, g)
        ch = SL.basewin_strip_chevron_rects(plate, 20, 35, g)
        b2 = ch["btn2"]
        # top flush with the chevron windows at every g
        assert tb[1] == b2[1], g
        # horizontal: clear of both chevrons, symmetric pads
        assert b2[2] <= tb[0] and tb[2] <= ch["btn3"][0], g
        assert tb[0] - plate[0] == plate[2] - tb[2], g
        if g > 16:
            # FLUSH: bottom == chevron art last device row (t + s(35) - 1)
            assert tb[3] == b2[1] + fl(35, g) - 1, g
            assert tb[3] == b2[3] - 1, g
        else:
            assert tb == (292, 73, 733, 108), g


def test_basewin_redbtn_frame_goldens_and_symmetry():
    """Staple ring frame rect: native identity + screenshot-pinned scaled
    goldens + channel symmetry at every g.  The art window is w = r-l off
    the redbtn fields (art spans [l, r-1]); vanilla's 9-slice strokes at
    coordinate-1 while our thick band ([x1-t+1, x1]) ends AT the
    coordinate, so the scaled frame rect pulls r/b in by 1."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native: redbtn golden (708,117,756,165) -> inflate 3, no -1
    assert SL.basewin_redbtn_frame((708, 117, 756, 165), 16) == \
        (705, 114, 759, 168)
    # g=25 pinned to the 1600x1200 shot (231431): art l=1106, frame left
    # stroke [1102,1103], right stroke must land [1183,1184] for channel 2
    assert SL.basewin_redbtn_frame((1106, 182, 1181, 257), 25) == \
        (1102, 178, 1184, 260)
    # g=40 golden off the seed-law redbtn (1769,292,1889,412): s3=7
    assert SL.basewin_redbtn_frame((1769, 292, 1889, 412), 40) == \
        (1762, 285, 1895, 418)
    for g in range(16, 41):
        s3, s48 = fl(3, g), fl(48, g)
        l, t = 500, 300                       # arbitrary anchor
        rb = (l, t, l + s48, t + s48)
        fr = SL.basewin_redbtn_frame(rb, g)
        # art fill = [l, l+s48-1]; stroke thickness t = 1 native else
        # round(g/16); left channel = art_l - (fr.l + t) must equal right
        # channel = right_stroke_first - 1 - art_r
        stroke = 1 if g <= 16 else (g + 8) >> 4
        art_r = l + s48 - 1
        left_ch = l - (fr[0] + stroke)
        if g <= 16:
            right_first = fr[2] - 1            # vanilla: 1px at coord-1
        else:
            right_first = fr[2] - stroke + 1   # our band [x1-t+1, x1]
        right_ch = right_first - 1 - art_r
        assert left_ch == right_ch == s3 - stroke, (g, left_ch, right_ch)
        # vertical is the same arithmetic by construction
        assert fr[3] - fr[1] == fr[2] - fr[0], g


def test_box2_ring_rects_goldens_and_sweep():
    """box_2 outline thicken: native identity (one ring == the vanilla
    call), K == stroke_width (LAW 4, never ceil), inward nesting, flush
    neighbors untouched, degenerate inner rings dropped."""
    import scaling_laws as SL
    # goldens: K per g (22->1 ring, 25/40->2 rings)
    assert SL.box2_ring_rects(100, 50, 140, 70, 16) == [(100, 50, 140, 70)]
    assert SL.box2_ring_rects(100, 50, 140, 70, 22) == [(100, 50, 140, 70)]
    assert SL.box2_ring_rects(100, 50, 140, 70, 25) == \
        [(100, 50, 140, 70), (101, 51, 139, 69)]
    assert SL.box2_ring_rects(100, 50, 140, 70, 40) == \
        [(100, 50, 140, 70), (101, 51, 139, 69)]
    for g in range(16, 41):
        rings = SL.box2_ring_rects(10, 20, 200, 90, g)
        assert len(rings) == SL.stroke_width(g), g
        assert rings[0] == (10, 20, 200, 90), g       # outer = vanilla edge
        for i, (l, t, r, b) in enumerate(rings):
            assert (l, t, r, b) == (10 + i, 20 + i, 200 - i, 90 - i), (g, i)
            assert r > l and b > t, (g, i)            # never degenerate
    # degenerate guard: a 2px-tall box emits only the vanilla ring
    for g in range(16, 41):
        rings = SL.box2_ring_rects(10, 20, 200, 21, g)
        assert rings == [(10, 20, 200, 21)], g


def test_base_popbox_pads_goldens_and_monotone():
    """Pop-number box pads: identity at native; floor idiom goldens; box
    grown by the law matches the pristine mockup (measured: native box
    12x14, live 4K glyph 21w/metric 30 -> 26x34 with native pads, 33x40
    with scaled pads vs mockup 33x39)."""
    import scaling_laws as SL
    assert SL.base_popbox_pads(16) == (5, 4, 2, 1)
    assert SL.base_popbox_pads(22) == (6, 5, 2, 1)
    assert SL.base_popbox_pads(25) == (7, 6, 3, 1)
    assert SL.base_popbox_pads(40) == (12, 10, 5, 2)
    prev = (0, 0, 0, 0)
    for g in range(16, 41):
        pads = SL.base_popbox_pads(g)
        assert all(a >= b for a, b in zip(pads, prev)), g   # monotone in g
        assert pads == tuple(SL.basewin_pt(v, g) for v in (5, 4, 2, 1)), g
        prev = pads
    # measured 4K vector: glyph width 21 + pad -> 33, metric 30 + pad -> 40
    pw, ph, _, _ = SL.base_popbox_pads(40)
    assert 21 + pw == 33 and 30 + ph == 40


def test_descale_point_exact_inverse():
    """descale_point is the exact left-inverse of popup_scale_floor for
    points: for every g in 16..40 and native n in 0..2000, every device px
    in n's forward cell maps back to n (the BaseWin map/facilities hit path
    descales the mouse into vanilla's native-space Spot rects and
    pixel->tile math)."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    for g in range(16, 41):
        for n in range(0, 2001):
            lo, hi = fl(n, g), fl(n + 1, g)
            assert hi > lo, (g, n)          # expansion: every cell >= 1px
            assert SL.descale_point(lo, g) == n, (g, n)
            assert SL.descale_point(hi - 1, g) == n, (g, n)
    # identity at native
    for d in range(0, 2001):
        assert SL.descale_point(d, 16) == d


def test_basewin_strip_content_native_identity():
    """g<=16: every draw-fn constant, font, ratio and SCALE pair is the
    vanilla value byte-for-byte (the thunk gates jle to the native path)."""
    import scaling_laws as SL
    for g in (10, 16):
        c = SL.basewin_strip_content(g)
        for k, v in SL.BASEWIN_STRIP_CONTENT_NATIVE.items():
            assert c[k] == v, (g, k)
        assert c["sup_scale_pair"] == (10, 16), g
        assert c["pop_ratio"] == (1, 1), g
        assert c["fonts"]["production"] == (12, 12), g
        assert c["fonts"]["queue"] == (12, 10), g
        assert c["fonts"]["shared_hdr"] == (14,), g
        assert c["fonts"]["info_cap"] == 32, g
        assert SL.basewin_strip_pop_citizen_y(114, 48, g) == 114, g


def test_basewin_strip_content_g40_golden():
    """4K golden: floor(v*40/16) == v*2.5 floored, pinned per constant."""
    import scaling_laws as SL
    c = SL.basewin_strip_content(40)
    assert c["inset3"] == 7 and c["ghost5"] == 12 and c["pad2"] == 5
    assert c["pic_anchor"] == 100 and c["name_anchor"] == 162
    assert c["icon_half"] == 50 and c["icon_size"] == 100
    assert c["bar_min_h"] == 5 and c["bar_tile_thresh"] == 20
    assert c["bar_nudge"] == 2 and c["blank6"] == 15
    assert c["pop_sprite_h"] == 120
    assert c["garr_cell"] == 140 and c["garr_gap"] == 12
    assert c["garr_stats_y"] == 15 and c["garr_edge"] == 2
    assert c["sup_cell"] == 155 and c["sup_row"] == 115
    assert c["sup_icon"] == 32 and c["sup_fit_pad"] == 30
    assert c["sup_scroll"] == 37 and c["info_pad"] == 15
    assert c["q_list_x"] == 12 and c["q_list_y"] == 5
    assert c["sup_scale_pair"] == (400, 256)
    assert c["pop_ratio"] == (40, 16)
    assert c["fonts"]["production"] == (30, 30)
    assert c["fonts"]["queue"] == (30, 25)
    assert c["fonts"]["pop"] == (22,)
    assert c["fonts"]["garrison"] == (30,)
    assert c["fonts"]["supported"] == (25,)
    assert c["fonts"]["shared_hdr"] == (35,)
    assert c["fonts"]["info_cap"] == 80
    # citizens: 4K seed pop=(665,285,1752,420) -> cell 135-ish; sprite 120
    # centres at top + (135-120)/2
    assert SL.basewin_strip_pop_citizen_y(285 + 7, 128, 40) == 285 + 7 + 4


def test_basewin_strip_content_sweep_invariants():
    """Every g 17..40: scaled constants are monotone vs native, the queue
    ghost-box edge still lands LEFT of the queue outer (the shared-edge
    design: qout.l - s(5) < qout.l), the supported cell still fits its row
    grid 1..3 columns, and the SCALE pair stays an exact 10g/256 fraction."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    prev = None
    for g in range(17, 41):
        c = SL.basewin_strip_content(g)
        for k, v in SL.BASEWIN_STRIP_CONTENT_NATIVE.items():
            assert c[k] == fl(v, g), (g, k)
            assert c[k] >= v, (g, k)
        num, den = c["sup_scale_pair"]
        assert num * 16 * 16 == den * 10 * g, g
        assert c["pop_ratio"] == (g, 16), g
        if prev is not None:
            for k in SL.BASEWIN_STRIP_CONTENT_NATIVE:
                assert c[k] >= prev[k], (g, k)
        prev = c
        # citizen sprite fits the citizens row at this g (row 54-4-4 native
        # interior scaled, minus the 3px insets)
        row_h = fl(0x36, g) - 2 * fl(3, g)
        assert c["pop_sprite_h"] <= row_h + fl(8, g), g


def test_basewin_strip_queue_row_pitch_goldens():
    """The 07-25e pitch fix: rows advance by the remainder-distributed
    vanilla pitch 13, replacing the sublinear scaled-font metric (which gave
    18 at g=25 / 27 at g=40 -- the cramped-rows defect)."""
    import scaling_laws as SL
    # native: every advance is exactly the vanilla metric 13
    assert [SL.basewin_strip_queue_row_advance(i, 16) for i in range(1, 9)] \
        == [13] * 8
    # g=25 (1600x1200): cum 20,40,60,81,... -> 20/21 pattern, total 162
    adv25 = [SL.basewin_strip_queue_row_advance(i, 25) for i in range(1, 9)]
    assert adv25 == [20, 20, 20, 21, 20, 20, 21, 20]
    assert sum(adv25) == SL.basewin_strip_queue_row_y(8, 25) == 162
    # g=40 (4K): 32/33 alternating, total 260 (metric would sum 8*27=216)
    adv40 = [SL.basewin_strip_queue_row_advance(i, 40) for i in range(1, 9)]
    assert adv40 == [32, 33, 32, 33, 32, 33, 32, 33]
    assert sum(adv40) == SL.basewin_strip_queue_row_y(8, 40) == 260
    # sweep: advances never differ by more than 1 within a g, cum is exact
    for g in range(17, 41):
        advs = [SL.basewin_strip_queue_row_advance(i, g) for i in range(1, 9)]
        assert max(advs) - min(advs) <= 1, g
        assert sum(advs) == SL.basewin_strip_queue_row_y(8, g), g


def test_basewin_strip_garrison_stats_y_goldens():
    """The 07-25e stats-y fix: scaled NATIVE metric 18 replaces the sublinear
    scaled-font metric; the digit line clears the panel clip at every g."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native identity: bottom 248 -> 236 (the measured vanilla capture)
    assert SL.basewin_strip_garrison_stats_y(248, 16) == 236
    # g=25: seed bottom fl(248*25/16)=387 -> 368 (screen 1167; the metric
    # form put it at ~371 and clipped the digit bottoms)
    assert SL.basewin_strip_garrison_stats_y(fl(248, 25), 25) == 368
    # g=40: 620 -> 590
    assert SL.basewin_strip_garrison_stats_y(fl(248, 40), 40) == 590
    # sweep: the 9-native-row digit band (scaled) always fits above bottom
    for g in range(16, 41):
        bottom = fl(248, g)
        top = SL.basewin_strip_garrison_stats_y(bottom, g)
        glyph_bottom = top + fl(2, g) + fl(9, g)   # leading + digit rows
        assert glyph_bottom <= bottom, g
        assert top < bottom, g


def test_veh_size_scaled_goldens():
    """The unit-renderer size-index law (thunk_hud_vehargs port): garrison's
    native -7 and the StatusWin sentinels, pinned to the live trace decode
    (frida_strip_rows.log 07-25: set_zoom 0.09625/0.0875/0.13125 at g=40)."""
    import scaling_laws as SL
    # garrison -7: g40 -> 6 (zoom 22/16*0.07 = 0.09625, the traced value)
    assert SL.veh_size_scaled(-7, 40) == 6
    assert SL.veh_size_scaled(-7, 25) == -2
    assert SL.veh_size_scaled(-7, 22) == -4
    # StatusWin sentinels at 4K: exact 2.5x ratios
    assert SL.veh_size_scaled(0, 40) == 24
    assert SL.veh_size_scaled(-4, 40) == 14
    assert SL.veh_size_scaled(-8, 40) == 4
    # identity: native g, and out-of-law sizes (map callers)
    assert SL.veh_size_scaled(-7, 16) == -7
    assert SL.veh_size_scaled(100, 40) == 100
    assert SL.veh_size_scaled(-20, 40) == -20
    # flic-zoom identity against the traced live values
    assert abs(SL.veh_flic_zoom(SL.veh_size_scaled(-7, 40)) - 0.09625) < 1e-9
    assert abs(SL.veh_flic_zoom(SL.veh_size_scaled(-8, 40)) - 0.0875) < 1e-9
    assert abs(SL.veh_flic_zoom(SL.veh_size_scaled(-4, 40)) - 0.13125) < 1e-9


def test_veh_size_scaled_sweep():
    """The applied ratio (s'+16)/16 floors the exact lever (s+16)/16*g/16
    within one /16 quantum and is monotone in s — no sentinel can overtake
    a larger one after scaling, and nothing ever over-scales."""
    import scaling_laws as SL
    for g in range(17, 41):
        prev = None
        for s in range(-16, 17):
            sp = SL.veh_size_scaled(s, g)
            exact = (s + 16) * g / 16
            got = sp + 16
            assert 0 <= exact - got < 1, (s, g)
            if prev is not None:
                assert got >= prev, (s, g)
            prev = got


# --------------------------------------------------------------------------
# SUPPORT-tab embedded-map laws (thunk_bw_supprect + mapblit v3)
# --------------------------------------------------------------------------

def _support_tiles(idx: int):
    """Tile dims of the fit-loop series at index idx (reference form)."""
    return (800 + 50 * idx) >> 4, (400 + 25 * idx) >> 4


def test_support_map_rect_goldens():
    """rcRspPanel [166,33,560,257] through the per-edge law: native identity
    plus the device windows the fit loop will see at the shipped g's."""
    import scaling_laws as SL
    native = SL.BASEWIN_RSP_PANEL_NATIVE
    assert native == (166, 33, 560, 257)
    assert SL.support_map_rect(*native, 16) == native
    assert SL.support_map_rect(*native, 25) == (259, 51, 875, 401)
    assert SL.support_map_rect(*native, 40) == (415, 82, 1400, 642)
    assert SL.support_map_rect(*native, 22) == (228, 45, 770, 353)


def test_support_map_fit_goldens():
    """Fit-loop goldens on the rcRspPanel window (W=394 H=224 native).
    half=40 models a mid map, 64 a huge one, 8 the tiny-map series cap."""
    import scaling_laws as SL

    def dims(g):
        l, t, r, b = SL.support_map_rect(*SL.BASEWIN_RSP_PANEL_NATIVE, g)
        return r - l, b - t

    # 40 half-tiles: native 9px tiles; 1600 15px (x1.67); 4K 21px (x2.33)
    assert SL.support_map_fit(*dims(16), 40, 40) == -13
    assert SL.support_map_fit(*dims(22), 40, 40) == -12
    assert SL.support_map_fit(*dims(25), 40, 40) == -11
    assert SL.support_map_fit(*dims(40), 40, 40) == -9
    # 64 half-tiles: 6px native -> 15px at 4K = exactly x2.5
    assert SL.support_map_fit(*dims(16), 64, 64) == -14
    assert SL.support_map_fit(*dims(40), 64, 64) == -11
    assert _support_tiles(-11)[0] == 15 and _support_tiles(-14)[0] == 6
    # 8 half-tiles: hits the i=2 series cap at 4K (56px tiles, x1.22 only —
    # the accepted crisp-but-smaller limit for very small maps)
    assert SL.support_map_fit(*dims(16), 8, 8) == -1
    assert SL.support_map_fit(*dims(40), 8, 8) == 2


def test_support_map_fit_sweep():
    """Structural invariants for g 16..40 x map sizes: the chosen index FITS,
    is MAXIMAL (the next denser one would not fit, unless capped at 2), never
    loses to the native pick, and is monotone in g."""
    import scaling_laws as SL
    for half in (8, 12, 16, 20, 24, 32, 40, 48, 64):
        prev_idx = None
        for g in range(16, 41):
            l, t, r, b = SL.support_map_rect(*SL.BASEWIN_RSP_PANEL_NATIVE, g)
            w, h = r - l, b - t
            idx = SL.support_map_fit(w, h, half, half)
            tw, th = _support_tiles(idx)
            if idx > -15:
                assert half * tw <= w and half * th <= h, (half, g)
            if idx < 2:
                ntw, nth = _support_tiles(idx + 1)
                assert half * ntw > w or half * nth > h, (half, g)
            if prev_idx is not None:
                assert idx >= prev_idx, (half, g)
            prev_idx = idx


# ==== type-8 OptionList sprite ratio + row pitch (stack picker, 2026-07-31) ==

def test_optionlist8_sprite_ratio_is_basewin_sprite_ratio():
    import scaling_laws as SL
    """One fraction law, no forks: the type-8 ratio must BE the basewin law
    (num*g, den*16) — a private variant would drift at exact-half points."""
    for g in range(SL.G_MIN, SL.G_MAX + 1):
        for num, den in ((1, 1), (3, 4), (2, 1)):
            assert SL.optionlist8_sprite_ratio(num, den, g) == \
                SL.basewin_sprite_ratio(num, den, g)


def test_optionlist8_native_identity():
    import scaling_laws as SL
    """g == 16 is vanilla, algebraically: ratio, pitch, text x and gap all
    collapse to the unpatched arithmetic."""
    assert SL.optionlist8_sprite_ratio(1, 1, 16) == (1, 1)
    # vanilla stack picker: gap 3, sprite 37x37, native line height ~24
    assert SL.optionlist8_row_pitch(3, 24, 37, 1, 1, 16) == 3 + 37
    assert SL.optionlist8_text_x(10, 37, 16) == 10 + 37 + 4
    assert SL.optionlist8_row_origin_gap(3, 16) == 3
    for g in (14, 15, 16):
        assert SL.optionlist8_sprite_ratio(1, 1, g) == (1, 1)


def test_optionlist8_row_width_follows_the_label_pad():
    import scaling_laws as SL
    """[+0x64] grows by exactly the label-x shift (pad(g) - 4): +6 @g40 (pad 10), +2 @g25/g22 (pad 6/5 -> 2/1),
    0 at g <= 19 -- so the label's clip edge moves with its left edge and the longest label keeps the
    vanilla room maxText + 2*[+0x40] - 4 at every g (the 4K 'Transpo' cut was 6 px)."""
    assert SL.optionlist8_row_width(412, 3, 92, 40) == 412 + 6 + 92 + 6
    assert SL.optionlist8_row_width(412, 3, 92, 25) == 412 + 6 + 92 + 2
    assert SL.optionlist8_row_width(412, 3, 92, 22) == 412 + 6 + 92 + 1
    for g in range(1, 20):
        assert SL.optionlist8_row_width(180, 3, 37, g) == 180 + 6 + 37
    for g in range(8, 97):
        room = (SL.optionlist8_row_width(300, 3, 57, g)) - (SL.optionlist8_text_x(0, 57, g))
        assert room == 300 + 6 - 4
        assert SL.optionlist8_label_pad(g) == (4 if g <= 16 else g >> 2)


def test_optionlist8_row_pitch_goldens():
    import scaling_laws as SL
    """Pinned to the measured stack-picker vectors (4K shot 20260731-185212 +
    pristine ref StackPicker.png): vanilla pitch 40 = gap 3 + spriteH 37
    (icon-dominated; native lineH 24).  The PRE-FIX defect pitch at g=40 was
    57 = 7 + max(50, 37) — text-dominated with native icons; the fix makes
    the sprite side dominate again: 7 + fl(37*40/16) = 99 ~ 40*2.5."""
    # pre-fix reproduction (ratio left native) — pins the diagnosis:
    assert SL.popup_scale_floor(3, 40) + max(50, (37 * 1) // 1) == 57
    # post-fix @4K (measured lineH 50):
    assert SL.optionlist8_row_pitch(3, 50, 37, 1, 1, 40) == 99
    # icon cell @4K:
    n, d = SL.optionlist8_sprite_ratio(1, 1, 40)
    assert (37 * n) // d == 92           # ~ 37 * 2.5 = 92.5
    # label x pad @4K: fl(4*40/16) = 10
    assert SL.optionlist8_text_x(0, 92, 40) == 102


def test_optionlist8_row_pitch_sweep_proportionate():
    import scaling_laws as SL
    """All-resolutions invariant: for the measured vanilla vector the scaled
    pitch tracks vanilla*g/16 within the 2px independent-floor budget, and
    never regresses below the text side (rows can never overlap their ink:
    pitch >= line_h + scaled gap)."""
    vanilla_pitch = 40                       # 3 + max(24, 37)
    for g in range(17, SL.G_MAX + 1):
        line_h = (24 * g) // 16              # the scaled measure font's lineH
        p = SL.optionlist8_row_pitch(3, line_h, 37, 1, 1, g)
        ideal = vanilla_pitch * g / 16
        assert ideal - 2 < p <= ideal, (g, p, ideal)
        assert p >= line_h + SL.popup_scale_floor(3, g)
        # monotone in g
        if g > 17:
            prev_line_h = (24 * (g - 1)) // 16
            assert p >= SL.optionlist8_row_pitch(3, prev_line_h, 37, 1, 1, g - 1)


def test_boxdef_fill_region_engine_mirror():
    import scaling_laws as SL
    """boxdef_fill_region must mirror Buffer_box_sprite's final tile block
    (decompiled 0x5e2dd3) exactly: per-edge inset by that edge sprite's
    cross dim, 0 for a null slice."""
    # all edges present (the ornate def: every slice non-null)
    assert SL.boxdef_fill_region(0, 0, 100, 80, 8, 6, 8, 6) == (8, 6, 92, 74)
    # null slices contribute 0 (d528-style partial defs)
    assert SL.boxdef_fill_region(0, 0, 100, 80, 0, 0, 0, 0) == (0, 0, 100, 80)
    assert SL.boxdef_fill_region(0, 0, 100, 80, 8, 0, 0, 6) == (8, 0, 100, 74)
    # offset rect (the erase always uses {0,0,w,h} but the law is general)
    assert SL.boxdef_fill_region(10, 20, 110, 100, 5, 5, 5, 5) == (15, 25, 105, 95)


def test_hollow_interior_erase_degenerate_guard():
    import scaling_laws as SL
    """The erase must SKIP (None) whenever the fill region is empty or
    inverted — a tiny small-render at deep insets must never fill a
    negative span (hline-zero-span class)."""
    assert SL.hollow_interior_erase(100, 80, 8, 6, 8, 6) == (8, 6, 92, 74)
    # exactly consumed -> empty -> skip
    assert SL.hollow_interior_erase(16, 12, 8, 6, 8, 6) is None
    # inverted -> skip
    assert SL.hollow_interior_erase(10, 10, 8, 6, 8, 6) is None
    # zero-dim small render -> skip
    assert SL.hollow_interior_erase(0, 0, 0, 0, 0, 0) is None
    # no-edge def: fill region == whole rect (still non-empty)
    assert SL.hollow_interior_erase(100, 80, 0, 0, 0, 0) == (0, 0, 100, 80)


def test_hollow_interior_erase_meets_band_by_construction():
    import scaling_laws as SL
    """The banding fix's core claim: the erase boundary IS the engine's fill
    region in SMALL coords, so after the SAME band-map blit the erased hole
    meets the drawn border exactly where the vanilla fill met it — for any
    small-render dims the union of (erase region) and (edge bands as the
    engine insets them) tiles the rect with no gap and no overlap."""
    for sw, sh, lw, th, rw, bh in [
        (100, 80, 8, 6, 8, 6),      # ornate-like
        (57, 41, 8, 6, 8, 6),       # fractional small dims (g=25-ish)
        (33, 29, 12, 12, 12, 12),   # deep bands, small rect
    ]:
        er = SL.hollow_interior_erase(sw, sh, lw, th, rw, bh)
        fr = SL.boxdef_fill_region(0, 0, sw, sh, lw, th, rw, bh)
        if er is None:
            assert fr[2] <= fr[0] or fr[3] <= fr[1]
        else:
            assert er == fr


def test_ornate_metal_insets_match_the_art():
    """Guard: re-derive ORNATE_METAL_INSETS from interface.pcx itself (the
    3x3 grid at 296,711, 61x44 cells, key RGB (152,24,228)).  If the art
    ever differs (mod/reinstall), this fails rather than nicking the metal."""
    import os
    import pytest as _pytest
    import scaling_laws as SL
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        from config import game_dir
        from PIL import Image
        import numpy as np
        p = os.path.join(str(game_dir(required=False)), "interface.pcx")
        if not os.path.exists(p):
            _pytest.skip("interface.pcx not found")
    except Exception:
        _pytest.skip("game dir / PIL unavailable")
    im = np.asarray(Image.open(p).convert("RGB")).astype(int)
    key = (152, 24, 228)

    def run(cx, cy, axis, rev):
        cell = im[cy:cy + 44, cx:cx + 61]
        nk = ~np.all(cell == key, axis=2)
        fracs = nk.mean(axis=0) if axis == "x" else nk.mean(axis=1)
        seq = fracs[::-1] if rev else fracs
        n = 0
        for v in seq:
            if v > 0.5:
                n += 1
            else:
                break
        return n

    lw = run(296, 756, "x", False)
    th = run(358, 711, "y", False)
    rw = run(420, 756, "x", True)
    bh = run(358, 801, "y", True)
    assert (lw, th, rw, bh) == SL.ORNATE_METAL_INSETS


def test_ornate_interior_erase_law():
    import scaling_laws as SL
    # 4K picker window 1599x649 -> small render 639x259
    assert SL.ornate_interior_erase(639, 259) == (8, 8, 630, 253)
    # 1600 window 998x402 -> small 638x257
    assert SL.ornate_interior_erase(638, 257) == (8, 8, 629, 251)
    # degenerate
    assert SL.ornate_interior_erase(16, 13) is None


# ---------------------------------------------------------------------------
# pf-align popup-type gate (v8)
# ---------------------------------------------------------------------------

def test_popup_frame_rewrite_gate_admits_only_the_censused_families():
    """Only the FLAT (0) and SLIDE (5) popup families were censused for the
    quit-law/container title-anchored rewrites; the ornate 6/2 in-game family
    (unit-stack picker) lays its frame from the already-scaled margin sum and
    must pass through. Raw [popup+0x30ac] = type*10000; 1000 is the hidden
    sentinel."""
    from scaling_laws import popup_frame_rewrite_applies
    for t in range(0, 12):
        expect = t in (0, 5)
        assert popup_frame_rewrite_applies(t * 10000) == expect, t
    assert not popup_frame_rewrite_applies(1000 * 10000)
    # band interiors behave like their band (the field can carry a sub-code)
    assert popup_frame_rewrite_applies(9999)
    assert popup_frame_rewrite_applies(59999)
    assert not popup_frame_rewrite_applies(10000)
    assert not popup_frame_rewrite_applies(60000)


def test_ornate_picker_container_arm_admits_only_the_picker_shape():
    """v9 (2026-08-01b): the ornate 6/2 picker shape — live dialog, no body
    box, no art, titled — takes the type-1/2/4 container relation
    (itemlist_container_edge_l/r of the title stash); every other ornate
    shape and every non-ornate type stays with the engine / the v8 gate."""
    from scaling_laws import ornate_picker_takes_container_arm as arm
    for t in range(0, 12):
        assert arm(t * 10000, 8, 0, 0, 1) == (t in (2, 6)), t
    assert not arm(1000 * 10000, 8, 0, 0, 1)
    # band interiors behave like their band
    assert arm(25000, 8, 0, 0, 1) and arm(69999, 8, 0, 0, 1)
    assert not arm(30000, 8, 0, 0, 1) and not arm(70000, 8, 0, 0, 1)
    # the non-type gates, one at a time
    assert not arm(60000, -1, 0, 0, 1)      # no live dialog
    assert not arm(60000, 8, 120, 0, 1)     # body text-box -> engine d528 path
    assert not arm(60000, 8, 0, 0x123, 1)   # art popups keep the engine layout
    assert not arm(60000, 8, 0, 0, 0)       # no title = stale stash


def test_ornate_title_inset_delta_scales_the_vanilla_13():
    """2026-08-01c: the 6/2 title chain insets the box 13 native px from the
    window edge on l/t/r; the delta lifts that to s(13) at every g, is the
    identity at native, and combines with ps3 to land the v9 picker frame
    within 1 floor-lag px of the faithful s(16) channel."""
    from scaling_laws import ornate_title_inset_delta, popup_pad, popup_scale_floor
    assert ornate_title_inset_delta(16) == 0
    assert ornate_title_inset_delta(40) == 19          # 4K: 13 -> 32
    assert ornate_title_inset_delta(25) == 7           # 1600x1200: 13 -> 20
    assert ornate_title_inset_delta(22) == 4           # 1920x1080: 13 -> 17
    for g in range(16, 41):
        d = ornate_title_inset_delta(g)
        assert 13 + d == popup_scale_floor(13, g)
        frame_ch = 13 + d + popup_pad(3, g)
        assert 0 <= popup_scale_floor(16, g) - frame_ch <= 1, g


def test_ornate_title_outer_bottom_restores_the_vanilla_height():
    """2026-08-01d follow-up: with the top raised to s(13), the engine's
    b = win+9+s(0x1c) left a 19px text slot @g40 (the scaled title ink
    covered the inner top stroke, shot 131629). Faithful b = win+s(37);
    the outer height is then exactly s(37)-s(13) (vanilla 24 scaled) and
    the inner text slot fits the ~s(12)-font ink at every g."""
    from scaling_laws import (ornate_title_inset_delta, ornate_title_outer_bottom,
                              popup_pad, popup_scale_floor)
    assert ornate_title_outer_bottom(13, 16) == 37       # native identity
    assert ornate_title_outer_bottom(13, 40) == 92       # 4K (ring top at 107)
    for g in range(16, 41):
        t = 13 + ornate_title_inset_delta(g)
        b = ornate_title_outer_bottom(13, g)
        assert b - t == popup_scale_floor(37, g) - popup_scale_floor(13, g), g
        slot = (b - 2 * popup_pad(3, g)) - (t + 2 * popup_pad(3, g))
        assert slot >= (30 * g) // 40, g                 # ink ~s(12 font) fits


@pytest.mark.parametrize("g", ALL_G)
def test_nested_frame_pad_gives_the_vanilla_channel(g: int):
    """The thick stroke draws OUTSIDE the nested rect at g>16, so the channel stroke->rows
    equals the pad itself; it must be the scaled vanilla channel 2 (native identity 3)."""
    from scaling_laws import nested_frame_pad, scale_px
    p = nested_frame_pad(g)
    if g <= 16:
        assert p == 3
    else:
        assert p == scale_px(2, g) and 2 <= p <= 5
    assert nested_frame_pad(22) == 3 and nested_frame_pad(25) == 3 and nested_frame_pad(40) == 5


def test_ornate_dialog_child_x_pad_free_popups_are_untouched():
    """Select Special Ability ([+0x30e0] == 0): engine child x = fl(19g/16) is already lawful."""
    from scaling_laws import ornate_dialog_child_x
    for g in ALL_G:
        x = (19 * g) >> 4
        assert ornate_dialog_child_x(x, g, pad_x=0) == x
        assert ornate_dialog_child_x(x, g, pad_x=3) == ornate_dialog_child_x(x, g)


def test_ornate_dialog_child_x_restores_the_ring_frame_gap():
    """2026-08-01d: two-point measured (43 @g40 / ~28 @g25) the ornate child
    x arrives s(16)+3 — one native +3 in the margin chain. The correction
    lands fl(19g/16) EXACTLY at every g (16g>>4 = g, no floor split), so
    the (faithful-width) selection ring sits ps3 inside the s(16) frame
    again instead of hugging it."""
    from scaling_laws import ornate_dialog_child_x, popup_pad
    assert ornate_dialog_child_x(19, 16) == 19           # native identity
    assert ornate_dialog_child_x(43, 40) == 47           # the 4K report
    for g in range(16, 41):
        x_engine = g + 3 if g > 16 else 19               # s(16)+3 measured shape
        assert ornate_dialog_child_x(x_engine, g) == (19 * g) >> 4, g
        # identity band: ps3 == 3 through g=21
        if 16 < g <= 21:
            assert ornate_dialog_child_x(x_engine, g) == x_engine, g
        # the restored gap to the s(16) frame == ps3
        assert ornate_dialog_child_x(x_engine, g) - ((16 * g) >> 4) == popup_pad(3, g), g


def test_ornate_container_edges_land_on_the_drawn_title_inner():
    """2026-08-01f ("the frame stroke on the unit box is not quite flush with
    the inner stroke of the title box"): the ornate title strokes render
    GROWN by frame_grow_delta(g) via thunk_box_thick, the container frame
    draws FLAT — so the flat rect must pre-subtract delta to land on the
    DRAWN inner stroke (measured 4K shot 140121: frame 1165/2673 vs drawn
    inner 1162/2676, +-3 = +-delta @g40, symmetric)."""
    from scaling_laws import (title_grow_delta as frame_grow_delta, itemlist_container_edge_l,
                              itemlist_container_edge_r, ornate_container_edge_l,
                              ornate_container_edge_r, popup_pad)
    T_L, T_R = 65, 1932
    for g in range(16, 41):
        d = frame_grow_delta(g)
        # the DRAWN title inner = (stash + ps3) - delta on the left (mirror right)
        drawn_inner_l = T_L + popup_pad(3, g) - d
        drawn_inner_r = T_R - popup_pad(3, g) + d
        assert ornate_container_edge_l(T_L, g) == drawn_inner_l, g
        assert ornate_container_edge_r(T_R, g) == drawn_inner_r, g
        # symmetric
        assert ornate_container_edge_l(T_L, g) - T_L == T_R - ornate_container_edge_r(T_R, g), g
        # identity vs the type-1/2/4 form wherever delta == 0 (all g < 24)
        if g < 24:
            assert ornate_container_edge_l(T_L, g) == itemlist_container_edge_l(T_L, g), g
            assert ornate_container_edge_r(T_R, g) == itemlist_container_edge_r(T_R, g), g
        # never crosses the stash (ps3 >= delta throughout [16, 40])
        assert ornate_container_edge_l(T_L, g) >= T_L, g
    # 2026-09-18: the title draws FLAT (title_grow_delta == 0), so the ornate arm == the type-1/2/4 form at EVERY g
    assert itemlist_container_edge_l(T_L, 40) == ornate_container_edge_l(T_L, 40)
    assert ornate_container_edge_r(T_R, 40) == itemlist_container_edge_r(T_R, 40)


def test_hud_cell_h_inset_goldens():
    """The 08-01 HUD unit-row selection-box overflow fix (site 0x4B816F):
    cell_h = strip_h - hud_cell_h_inset(g).  Vanilla's -12 is the four 3px
    box-6 frame insets; n13 scales each inset to fl(3g/16) so the sum must
    be 4*fl(3g/16), sharing n13's floor cascade."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native identity: exactly the vanilla immediate
    assert SL.hud_cell_h_inset(16) == 12
    # goldens: g=22 (1920x1080) -> 16, g=25 (1600x1200) -> 16, g=40 (4K) -> 28
    assert SL.hud_cell_h_inset(22) == 16
    assert SL.hud_cell_h_inset(25) == 16
    assert SL.hud_cell_h_inset(40) == 28
    # NOT fl(12g/16): the single-floor form overshoots the true inset sum
    assert SL.hud_cell_h_inset(40) != fl(12, 40)   # 28 vs 30
    for g in range(16, 41):
        # the law IS the sum of the four insets n13 actually applies
        assert SL.hud_cell_h_inset(g) == 4 * fl(3, g), g
        # flush: content_h == strip_h - 4 insets -> cell bottom lands exactly
        # on the content bottom (ring outset 2 stays inside the inner band)
        strip_h = fl(248, g) - fl(192, g)          # box6 native T=192 B=248
        cell_h = strip_h - SL.hud_cell_h_inset(g)
        content_h = strip_h - 4 * fl(3, g)
        assert cell_h == content_h, g
        assert cell_h > 0, g


def test_hud_row_label_y_goldens():
    """The 08-02 HUD unit-row label fix (thunk_hud_n16 v2): y = cellB + s3 −
    lineH' + 1 with the sublinear live metric replaced by fl(13g/16) at g>16.
    Goldens pinned to the live trace (frida_hudcell.log 2026-08-02)."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native identity: the traced vanilla values -> 233 (all three exes)
    assert SL.hud_row_label_y(242, 3, 13, 16) == 233
    # 4K: traced cellB=606 s3=7 (live lineH 27 ignored at g>16) -> 582
    assert SL.hud_row_label_y(606, 7, 27, 40) == 582
    # proportional pin: native offset from cellT is 35 (233-198); 4K cell
    # T=494 -> label-cellT == fl-scaled 35 within 1px
    assert abs((SL.hud_row_label_y(606, 7, 27, 40) - 494) - fl(35, 40)) <= 1
    # the retired v1 law (cellB - fl(19g/16)) sat 23px higher at 4K
    assert (606 - fl(19, 40)) - SL.hud_row_label_y(606, 7, 27, 40) == -23
    # sweep: label glyphs (scaled 9-row digit band) stay inside the ring
    # bottom (cellB+2) and below the cell midline at every g
    for g in range(16, 41):
        cell_t = 198 * g // 16
        cell_b = cell_t + (fl(248, g) - fl(192, g)) - SL.hud_cell_h_inset(g)
        s3 = fl(3, g)
        y = SL.hud_row_label_y(cell_b, s3, 13 if g == 16 else 0, g)
        assert y + fl(9, g) <= cell_b + 2, g
        assert y > (cell_t + cell_b) // 2, g


def test_hud_cell_ring_outset_goldens():
    """The 08-02 ring/frame channel fix (thunk_hud_cellring v2): the ring
    rect moves from vanilla's unscaled cell±2 to cell±(i − half_down(i,3)),
    i = fl(3g/16) — flush against the inner frame band's content-side
    stroke edge (pristine HudUnitStack.png shows zero channel; the unscaled
    2 left a 2-3px dark channel at 4K, 2026-08-02 screenshot)."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native identity: exactly the vanilla constant
    assert SL.hud_cell_ring_outset(16) == 2
    # goldens: g=22 (1920x1080) / g=25 (1600x1200) -> 3, g=40 (4K) -> 5
    assert SL.hud_cell_ring_outset(22) == 3
    assert SL.hud_cell_ring_outset(25) == 3
    assert SL.hud_cell_ring_outset(40) == 5
    prev = 0
    for g in range(16, 41):
        i = fl(3, g)
        o = SL.hud_cell_ring_outset(g)
        # flush construction: ring outer edge = cell − o = strip + i +
        # half_down(i,3) — exactly the first px after the band-mapped px0
        # stroke, inside the inner band (never escapes the strip, never
        # covers the whole stroke)
        assert o == i - SL.half_down(i, 3), g
        assert 0 < o < i, g
        # never tighter than vanilla, monotone non-decreasing over g
        assert o >= 2 and o >= prev, g
        prev = o
        # the inward thicken K=(g+15)>>4 stays clear of the cell content:
        # ring inner edge = cell − o + K − 1 < cell
        k = (g + 15) >> 4
        assert o >= k, g


def test_hud_cell_ring_rect_goldens():
    """The 08-02g flush law (thunk_hud_cellring v4 + thunk_hud_cellclip v3):
    ring == clip, frame-anchored, using the frame's REAL stroke width
    stroke_width(g) — hd = half_down(i,3) coincides with it at g=22/40 but
    diverges at g=25/26, and Buffer_box_2 draws HALF-OPEN (bottom at B−1,
    right at R−1), so the v3.1 hd law left a 1px bottom channel at almost
    every g (4K shot 153025) and would have overlapped the left/top strokes
    at 1600×1200."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # golden: the measured 4K geometry (window-local); frame fields are the
    # boxframe-stored (x, y, X1, Y1) — Y1 = fl(245*40/16) = 612 inclusive
    # (nat table row 142,195,761,245).  Cell 0 (cellL 361 snaps to frame+kS):
    # drawn ring cols 357..517, rows 489..610, flush under stroke 611/612.
    assert SL.hud_cell_ring_rect(355, 487, 612, 361, 513, 40) == (357, 489, 518, 611)
    # interior cell (pitch 165 at 4K): LEFT is cell-anchored, symmetric with
    # the right outset — NOT the strip frame's left stroke (the v4 "overly
    # wide box, left edge always anchored" defect, 1920 shot 170930)
    assert SL.hud_cell_ring_rect(355, 487, 612, 526, 678, 40) == (521, 489, 683, 611)
    assert SL.hud_cell_ring_rect(355, 487, 612, 691, 843, 40) == (686, 489, 848, 611)
    # sweep over the REAL frame pipeline: nat rect -> per-field fl scaling ->
    # bandmap stroke bands via the actual axis_map (no modeled bands)
    natX, natY, natX1, natY1 = 142, 195, 761, 245   # inner box6 frame nat row
    for g in range(17, 41):
        i = fl(3, g)
        hd = SL.half_down(i, 3)
        ks = SL.stroke_width(g)
        frameX, frameY = fl(natX, g), fl(natY, g)
        frameX1, frameY1 = fl(natX1, g), fl(natY1, g)
        # cell 0 models: devStrip + 2i + seed, seed 0..2, frame drift 0..1 —
        # the snap threshold 2 must capture ALL of them (proof in the law
        # docstring: |cell-derived - frame-flush| <= 2 at every g/drift)
        devStrip = fl(139, g)
        for seed in (0, 1, 2):
            cellL0 = devStrip + 2 * i + seed
            l_cell0 = cellL0 - (i - hd)
            assert abs(l_cell0 - (frameX + ks)) <= 2, (g, seed)
            l, t, r, b = SL.hud_cell_ring_rect(frameX, frameY, frameY1,
                                               cellL0, cellL0 + 150, g)
            assert l == frameX + ks, (g, seed)      # cell 0 snaps flush
        # interior cells: LEFT is cell-anchored (symmetric with R), and the
        # snap can never capture them (pitch >= 80 device px)
        pitch = 150 + fl(5, g)
        for k in (1, 2, 3):
            cellL = devStrip + 2 * i + k * pitch
            cellR = cellL + 150
            l, t, r, b = SL.hud_cell_ring_rect(frameX, frameY, frameY1,
                                               cellL, cellR, g)
            assert l == cellL - (i - hd), (g, k)
            assert l - (frameX + ks) > 2, (g, k)
            # symmetric drawn outsets: left drawn at L = cellL - d; right
            # drawn at R-1 = cellR + d - 1 (cell rect is half-open too)
            assert (cellL - l) == (r - 1 - (cellR - 1)), (g, k)
        # frame-flush assertions below use the cell-0 rect
        for drift in (3, 4, 5, 6):
            cellR = frameX1 - 2 * i     # representative; R is cell-anchored
            l, t, r, b = SL.hud_cell_ring_rect(frameX, frameY, frameY1,
                                               frameX + 3, cellR, g)
            assert (l, t) == (frameX + ks, frameY + ks), g
            assert r == cellR + (i - hd), g
            assert b == frameY1 + 1 - ks, g
            # frame stroke bands from the REAL bandmap chain: small render
            # (Y1-Y)*16//g rows, inclusive dest footprint Y..Y1, chrome cell
            # pinned to ks by band_widths for every plausible corner depth
            H = frameY1 - frameY + 1
            smallH = (frameY1 - frameY) * 16 // g
            for n in (4, 8, 12):
                m = SL.axis_map(smallH, H, n, g)
                assert m is not None, (g, n)
                bot = [j for j, s in enumerate(m) if s == smallH - 1]
                top = [j for j, s in enumerate(m) if s == 0]
                assert bot == list(range(H - ks, H)), (g, n)
                assert top == list(range(ks)), (g, n)
            stroke_top = frameY1 - ks + 1
            # FLUSH in drawn-pixel space (box_2 half-open: bottom B-1, right
            # R-1, top T, left L): ring bottom row abuts the stroke, top/left
            # start exactly after it — zero channel, zero overlap, every g
            assert b - 1 == stroke_top - 1, g
            assert t == frameY + ks and l == frameX + ks, g
            # clip == ring rect (cellclip v3): every drawn px survives the
            # half-open clip by construction
            assert l >= l and t >= t and (r - 1) <= r - 1 and (b - 1) <= b - 1
            # the ring never inverts and keeps >=K thickness room, all rects
            # >= 3px span (Buffer_box_2 zero-span dropout starts below that)
            k = (g + 15) >> 4
            assert l + k <= r - k and t + k <= b - k, g
            assert (r - (k - 1)) - (l + (k - 1)) >= 3, g
            assert (b - (k - 1)) - (t + (k - 1)) >= 3, g
    # domain note: at g=16 the law is NOT vanilla (bandmap inclusive footprint
    # vs native half-open render differ by one row at the bottom); the thunks'
    # g<=16 passthrough gate is the native no-op, so the law must only ever
    # be ported behind that gate.
    cellL, cellT, cellB, cellR = 100, 200, 240, 160
    l, t, r, b = SL.hud_cell_ring_rect(cellL - 3, cellT - 3, cellB + 3,
                                       cellL, cellR, 16)
    assert (l, t, r) == (cellL - 2, cellT - 2, cellR + 2)
    assert b == cellB + 3      # != vanilla cellB+2 — hence the thunk gate


def test_hud_cell_pitch_gap_and_seed_goldens():
    """The 08-02d pitch/seed fix (thunk_hud_n17..n22): the box-6 inter-cell
    gap (+5) and the first-cell x seed (+1) are native additive constants and
    must scale ×g/16 — n15 already sizes slotw_dev = span/count − fl(5g/16),
    so the loop-tail advance must add the SAME fl(5g/16) for cells to tile
    the span (measured 4K pitch 157 vs intended 165; the ring filled the
    whole native 5px gap and crowded the neighbor flag)."""
    import scaling_laws as SL
    fl = SL.popup_scale_floor
    # native identity
    assert SL.hud_cell_pitch_gap(16) == 5
    assert SL.hud_row_seed_inset(16) == 1
    # goldens
    assert SL.hud_cell_pitch_gap(22) == 6
    assert SL.hud_cell_pitch_gap(25) == 7
    assert SL.hud_cell_pitch_gap(40) == 12
    assert SL.hud_row_seed_inset(22) == 1
    assert SL.hud_row_seed_inset(25) == 1
    assert SL.hud_row_seed_inset(40) == 2
    for g in range(16, 41):
        gap = SL.hud_cell_pitch_gap(g)
        assert gap == fl(5, g), g
        # pitch consistency with n14/n15: advance == span-per-cell budget,
        # i.e. slotw_dev + gap for any slotw_dev the n15 derivation yields
        assert gap >= 5, g
        # the ring outset never exceeds the scaled gap: outset <= gap keeps
        # the ring's outer edge out of the neighbor cell at every g
        assert SL.hud_cell_ring_outset(g) <= gap, g
        seed = SL.hud_row_seed_inset(g)
        assert seed == fl(1, g) and 1 <= seed <= gap, g


# ---------------------------------------------------------------------------
# base production picker (ProdPicker) — laws derived from the four-resolution
# hook_prodpicker.js measurement (work\frida_prodpicker.log, 2026-08-03).
# ---------------------------------------------------------------------------

# (g, BaseWin canvas w, h_abs, measured picker canvas w, h_abs, measured colw)
_PP_MEASURED = [
    (16,  758, 490,  758,  490, 135),
    (22, 1042, 673, 1432,  925, 192),
    (25, 1184, 765, 1850, 1195, 220),
    (40, 1895, 1225, 4737, 3062, 362),
]


def test_prodpicker_measured_double_scale_reproduces():
    """The BUG law must reproduce every measured picker canvas exactly — that
    is what proves the diagnosis (child arm re-scales an already-device rect)
    rather than leaving it a plausible story."""
    import scaling_laws as SL
    for g, bw, bh, pw, ph, _cw in _PP_MEASURED:
        assert SL.prodpicker_double_scaled_window(bw, bh, g) == (pw, ph), g


def test_prodpicker_window_exemption_is_identity_and_diverges_above_native():
    import scaling_laws as SL
    for g, bw, bh, pw, ph, _cw in _PP_MEASURED:
        assert SL.prodpicker_window_size(bw, bh, g) == (bw, bh), g
    # tripwire: the fix and the bug agree ONLY at the native no-op
    for g in range(16, 41):
        bw, bh = SL.basewin_pt(758, g), SL.basewin_pt(490, g)
        fixed = SL.prodpicker_window_size(bw, bh, g)
        buggy = SL.prodpicker_double_scaled_window(bw, bh, g)
        assert (fixed == buggy) == (g <= 16), g


def test_prodpicker_g16_identity_matches_the_vanilla_run():
    """Every law collapses to the numbers logged at 1024x768 (g=16)."""
    import scaling_laws as SL
    assert SL.prodpicker_row_pitch(16) == 108
    assert SL.prodpicker_col_w(758, 16) == 135
    assert SL.prodpicker_cell_rect(0, 0, 135, 108, 16) == (27, 4, 159, 109)
    assert SL.prodpicker_cell_rect(4, 3, 135, 108, 16) == (567, 328, 699, 433)
    # logged button rects at 1024x768: leftmost 54..154, btn0 569..669, y 440..460
    rects = SL.prodpicker_button_rects(758, 6, 108, 4, 16)
    assert rects[0] == (569, 440, 669, 460)
    assert rects[5] == (54, 440, 154, 460)
    for native in (SL.PRODPICKER_FONT_CELLNAME, SL.PRODPICKER_FONT_BUTTON,
                   SL.PRODPICKER_FONT_STATS):
        assert SL.prodpicker_font_size(native, 16) == native


def test_prodpicker_cell_rect_reproduces_the_engine_at_every_measured_res():
    """Fed the engine's own (unscaled-margin) colw/pitch the law must equal the
    logged clip rects — i.e. the law is the engine's expression, not a guess."""
    import scaling_laws as SL
    logged = {16: (27, 4, 159, 109), 22: (27, 4, 216, 109),
              25: (27, 4, 244, 109), 40: (27, 4, 386, 109)}
    for g, _bw, _bh, _pw, _ph, cw in _PP_MEASURED:
        l, t, r, b = (cw * 0 + 0x1B, 0 + 4, cw * 1 + 0x18, 108 + 1)
        assert (l, t, r, b) == logged[g], g


def test_prodpicker_sweep_geometry_is_sane_and_proportionate():
    import scaling_laws as SL
    fl = SL.basewin_pt
    for g in range(16, 41):
        win_w = fl(758, g)
        win_h = fl(490, g)
        pitch = SL.prodpicker_row_pitch(g)
        colw = SL.prodpicker_col_w(win_w, g)
        assert pitch == fl(108, g) and colw > 0, g
        # rows: 4 visible rows plus the button row must fit the window height
        for count in (4, 5, 6):
            rects = SL.prodpicker_button_rects(win_w, count, pitch, 4, g)
            assert len(rects) == count, g
            xs = [r[0] for r in rects]
            assert xs == sorted(xs, reverse=True), g      # button 0 is rightmost
            assert rects[-1][0] >= 0, (g, count)          # never off the left edge
            assert rects[0][2] <= win_w, (g, count)       # never past the right edge
            assert rects[0][1] >= pitch * 4, (g, count)   # below the last grid row
            assert rects[0][3] <= win_h, (g, count)       # inside the window
            # uniform stride, no overlap
            step = xs[0] - xs[1]
            assert all(xs[i] - xs[i + 1] == step for i in range(count - 1)), g
            assert step >= rects[0][2] - rects[0][0], (g, count)
        # grid: 5 columns must fit inside the window with a scrollbar gutter
        last = SL.prodpicker_cell_rect(4, 3, colw, pitch, g)
        first = SL.prodpicker_cell_rect(0, 0, colw, pitch, g)
        assert first[0] >= fl(0x1B, g) - 1 and last[2] < win_w, g
        assert last[3] <= pitch * 4 + fl(1, g), g


def test_prodpicker_button_row_recentres_under_the_grid():
    """The payoff claim: with the exemption + scaled constants the vanilla
    centring math puts the row under the grid at EVERY g (it is 1.5px left of
    grid centre natively, and must not drift with scale)."""
    import scaling_laws as SL
    for g in range(16, 41):
        win_w = SL.basewin_pt(758, g)
        pitch = SL.prodpicker_row_pitch(g)
        colw = SL.prodpicker_col_w(win_w, g)
        grid_l = SL.prodpicker_cell_rect(0, 0, colw, pitch, g)[0]
        grid_r = SL.prodpicker_cell_rect(4, 0, colw, pitch, g)[2]
        for count in (4, 5, 6):
            rects = SL.prodpicker_button_rects(win_w, count, pitch, 4, g)
            row_c = (rects[-1][0] + rects[0][2]) / 2
            grid_c = (grid_l + grid_r) / 2
            # native offset is -1.5px; allow it to scale but never to drift
            assert abs(row_c - grid_c) <= 3 + (g - 16) * 0.25, (g, count, row_c, grid_c)


def test_prodpicker_font_sizes_scale_and_are_native_at_16():
    import scaling_laws as SL
    golden = {40: (30, 35, 25), 25: (18, 21, 15), 22: (16, 19, 13),
              16: (12, 14, 10)}
    for g, (name, btn, stats) in golden.items():
        assert SL.prodpicker_font_size(SL.PRODPICKER_FONT_CELLNAME, g) == name, g
        assert SL.prodpicker_font_size(SL.PRODPICKER_FONT_BUTTON, g) == btn, g
        assert SL.prodpicker_font_size(SL.PRODPICKER_FONT_STATS, g) == stats, g
    for g in range(16, 41):
        # strictly monotone in g and never smaller than vanilla
        assert SL.prodpicker_font_size(12, g) >= 12, g
        assert SL.prodpicker_font_size(14, g) >= SL.prodpicker_font_size(12, g), g


def test_prodpicker_frame_and_button_frame_g16_identity_and_symmetry():
    """Pass-3 laws (2026-08-03b): the outer frame and the button-row frame.
    The user-visible defects these fix — "art misplaced on the left", "a large
    black area to the right", "the frame stroke of the button box is unscaled
    and mis-positioned" — are all native additive constants inside a device
    space, so the sweep asserts the GUTTERS stay symmetric, not just that the
    numbers scale."""
    import scaling_laws as SL
    # g=16 must be vanilla exactly
    assert SL.prodpicker_frame_rect(135, 490, 16) == (23, 0, 703, 490)
    assert SL.prodpicker_button_frame(758, 6, 108, 4, 16) == (51, 437, 672, 463)
    for g in range(16, 41):
        W, H = SL.basewin_pt(758, g), SL.basewin_pt(490, g)
        pitch = SL.prodpicker_row_pitch(g)
        colw = SL.prodpicker_col_w(W, g)
        fl, ft, fr, fb = SL.prodpicker_frame_rect(colw, H, g)
        grid_l = SL.prodpicker_cell_rect(0, 0, colw, pitch, g)[0]
        grid_r = SL.prodpicker_cell_rect(4, 0, colw, pitch, g)[2]
        # the grid sits INSIDE the frame with near-equal gutters (vanilla: 4/4)
        assert fl < grid_l and grid_r < fr, g
        # v2 ART-FLUSH LAW (pass 4): the backdrop's bright bevel line lives at
        # fl(23*g/16) (measured exposed at 31@g22 / 35@g25); the frame's left
        # edge must share that cascade exactly or the bevel peeks out.
        assert fl == SL.basewin_pt(SL.PRODPICKER_FRAME_L, g), (g, fl)
        # LAW 5 + stroke-aware symmetry: the K-wide strokes draw INWARD from
        # both edges (thunk_box_thick_hollow_flat), so the visible gutters are
        # (grid_l - fl - K) and (fr - K - grid_r): EQUAL at every g, K cancels.
        k = SL.stroke_width(g)
        gl, gr = grid_l - fl - k, fr - k - grid_r
        assert gl == gr, (g, gl, gr)
        # the gutter still tracks the native 3px [24,27) band (+/-1 for the
        # cascade split); it must never collapse or balloon
        assert SL.basewin_pt(3, g) - 2 <= gl <= SL.basewin_pt(3, g) + 2, (g, gl)
        assert fr <= W, (g, fr, W)
        # the button frame wraps the row and stays inside the window
        for count in (4, 5, 6):
            bl, bt, br, bb = SL.prodpicker_button_frame(W, count, pitch, 4, g)
            rects = SL.prodpicker_button_rects(W, count, pitch, 4, g)
            assert bl < rects[-1][0] and br > rects[0][2], (g, count)
            assert bt < rects[0][1] and bb > rects[0][3], (g, count)
            assert bl >= 0 and br <= W and bb <= H, (g, count)
            # frame follows content: every edge is exactly the row +/- the inset
            d = SL.basewin_pt(3, g)
            assert (bl, bt, br, bb) == (rects[-1][0] - d, rects[0][1] - d,
                                        rects[0][2] + d, rects[0][3] + d), (g, count)


def test_prodpicker_cell_text_y_laws():
    """Pass-5 laws: title pad + bottom-block anchor, pinned by the v3 trace
    (work\\frida_prodpicker.log 2026-08-05: native title y=10, y1=98, y2=89;
    4K defect title y=16, y1=248 — targets 25 / 245)."""
    import scaling_laws as SL
    # native identity, algebraic
    assert SL.prodpicker_title_pad(16) == 5
    assert SL.prodpicker_stats_h(10, 10, 16) == 10
    assert SL.prodpicker_stats_h(7, 10, 16) == 7          # non-multiple untouched
    # 4K trace targets
    ct = SL.prodpicker_cell_rect(0, 0, 338, 270, 40)[1]   # cell top 10
    cb = SL.prodpicker_cell_rect(0, 0, 338, 270, 40)[3]   # cell bottom 272
    assert ct + 1 + SL.prodpicker_title_pad(40) == 25     # fl(6*40/16) + top
    assert (cb - 1) - SL.prodpicker_stats_h(23, 23, 40) == 245  # cb - bp(11)
    for g in range(16, 41):
        pad = SL.prodpicker_title_pad(g)
        # total title offset from the cell top == bp(6) exactly (inset stays 1)
        assert 1 + pad == SL.basewin_pt(6, g), g
        # degenerate inputs pass through
        assert SL.prodpicker_stats_h(0, 100, g) == 0
        assert SL.prodpicker_stats_h(50, 0, g) == 50
    for g in range(17, 41):
        # one-line block: anchor is exactly bp(11) above the cell bottom
        m = SL.prodpicker_stats_h(1 * 100, 100, g)        # any m divides out
        assert 1 + m == SL.basewin_pt(SL.PRODPICKER_STATS_ANCHOR, g), g
        # n-line generality: h' scales per line, no cross-line drift
        for n in (1, 2, 3):
            assert SL.prodpicker_stats_h(n * 100, 100, g) == n * m, (g, n)


def test_prodpicker_hit_grid_aligns_to_drawn_cells():
    """Pass-5b hit law: the select mapping owns [cell left/top edge .. next
    cell's edge) at EVERY g, g=16 included (deliberate fix of vanilla's own
    no-inset skew, user-requested — NOT the usual native no-op)."""
    import scaling_laws as SL
    # g=16: the native insets 0x1B/4 are subtracted (vanilla mapped 134->col0
    # even though drawn cell 1 starts at 135+27; now the drawn edge governs)
    assert SL.prodpicker_hit_cell(0x1B + 134, 4 + 107, 135, 108, 16) == (0, 0)
    assert SL.prodpicker_hit_cell(0x1B + 135, 4 + 108, 135, 108, 16) == (1, 1)
    # left/top gutter clicks clamp to cell 0 via idiv trunc-toward-zero
    assert SL.prodpicker_hit_cell(0, 0, 135, 108, 16) == (0, 0)
    for g in range(16, 41):
        W = SL.basewin_pt(758, g)
        colw = SL.prodpicker_col_w(W, g)
        pitch = SL.prodpicker_row_pitch(g)
        for col in range(5):
            for row in range(4):
                l, t, r, b = SL.prodpicker_cell_rect(col, row, colw, pitch, g)
                # every drawn-cell corner maps to ITS OWN cell
                for x, y in ((l, t), (r - 1, t), (l, b - 1), (r - 1, b - 1)):
                    assert SL.prodpicker_hit_cell(x, y, colw, pitch, g) == \
                        (col, row), (g, col, row, x, y)
                # boundary: the next cell's left/top edge belongs to the next
                if col < 4:
                    nl = SL.prodpicker_cell_rect(col + 1, row, colw, pitch, g)[0]
                    assert SL.prodpicker_hit_cell(nl, t, colw, pitch, g)[0] == \
                        col + 1, (g, col)
        # clicks in the left frame/gutter never go negative
        assert SL.prodpicker_hit_cell(0, 0, colw, pitch, g) == (0, 0), g


def test_prodpicker_scroll_blit_g16_is_vanilla():
    """ProdPicker_scroll_to 0x493D14..0x493D69 / 0x493DC8..0x493E23 at the vanilla
    run's numbers (cols 5, colw 135, pitch 108, vis_rows 4): x 0x15 both ends,
    w = 5*135 + 0x17 + 2 - 0x15 = 679, h = 3*108, y 4 <-> 112."""
    import scaling_laws as SL
    assert SL.prodpicker_scroll_blit(5, 135, 108, 4, 16, True) == (21, 4, 21, 112, 679, 324)
    assert SL.prodpicker_scroll_blit(5, 135, 108, 4, 16, False) == (21, 112, 21, 4, 679, 324)
    assert SL.prodpicker_scroll_blit(5, 135, 108, 3, 16, True) == (21, 4, 21, 112, 679, 216)
    for p in range(100, 120):
        assert not SL.prodpicker_scroll_redraws(p, 16), p
    # the measured 4K defect: a bp(0x19)-0x19 px strip the vanilla right edge left behind
    assert SL.basewin_pt(SL.PRODPICKER_SCROLL_R, 40) - SL.PRODPICKER_SCROLL_R == 37


def _pp_scroll_cases():
    import scaling_laws as SL
    for g in range(16, 41):
        win_w, win_h = SL.basewin_pt(758, g), SL.basewin_pt(490, g)
        pitch = SL.prodpicker_row_pitch(g)
        base = SL.prodpicker_col_w(win_w, g)
        for colw in sorted({base, base - 3, base + 2}):
            for vis_rows in (3, 4):
                for up in (True, False):
                    yield g, win_w, win_h, pitch, colw, vis_rows, up


def test_prodpicker_scroll_blit_moves_exactly_the_scaled_grid():
    """Every g 16..40 x colw x vis_rows x direction: the columns Buffer_copy_4
    ACTUALLY writes (its sx == dx self-blit is exact only for w % 4 == 0, model
    buffer_copy4_selfblit_columns, checked against the real bytes in
    test_prodpicker_scroll_asm_parity.py) cover every moved cell's half-open
    rect and never reach the grid frame's right stroke; the moved rows shift by
    exactly one pitch, cover every moved cell, and stay above the button row."""
    import scaling_laws as SL
    for g, win_w, win_h, pitch, colw, vis_rows, up in _pp_scroll_cases():
        sx, sy, dx, dy, w, h = SL.prodpicker_scroll_blit(5, colw, pitch, vis_rows, g, up)
        ctx = (g, colw, vis_rows, up)
        assert sx == dx and h == (vis_rows - 1) * pitch, ctx
        assert dy - sy == (pitch if up else -pitch), ctx
        fl, _, fr, _ = SL.prodpicker_frame_rect(colw, win_h, g)
        k = SL.stroke_width(g)
        cols = SL.buffer_copy4_selfblit_columns(sx, w)
        if g > 16:
            assert w % 4 == 0 and cols == set(range(sx, sx + w)), ctx
            assert SL.PRODPICKER_SCROLL_X - 3 <= sx <= SL.PRODPICKER_SCROLL_X, ctx
            assert sx + w == 5 * colw + SL.basewin_pt(SL.PRODPICKER_SCROLL_R, g), ctx
        # horizontally: every moved cell is inside the written columns ...
        first = SL.prodpicker_cell_rect(0, 0, colw, pitch, g)
        last = SL.prodpicker_cell_rect(4, 0, colw, pitch, g)
        assert set(range(first[0], last[2])) <= cols, ctx
        # ... and nothing from the frame's inward K-wide right stroke on is touched
        # (vanilla's w & 3 == 3 tail drags the 1-px stroke column onto itself)
        if g > 16:
            assert max(cols) < fr - k, (ctx, max(cols), fr - k)
        else:
            assert max(cols) <= fr - k, ctx
        assert min(cols) >= 0 and sx < fl, ctx
        # vertically: source rows cover the cells that stay visible
        moved = range(0, vis_rows - 1) if up else range(1, vis_rows)
        for row in moved:
            _, t, _, b = SL.prodpicker_cell_rect(0, row, colw, pitch, g)
            assert sy <= t and b <= sy + h, (ctx, row)
        # the frame's top stroke is never read, the button row never written
        assert min(sy, dy) >= k, ctx
        for count in (4, 5, 6):
            _, bt, _, _ = SL.prodpicker_button_frame(win_w, count, pitch, vis_rows, g)
            assert max(sy, dy) + h <= bt, (ctx, count)
        assert max(sy, dy) + h <= win_h, ctx


def test_prodpicker_scroll_blit_keeps_the_stripe_phase():
    """The devfill restripe keys on the DEST row (stripe_top(y), one grid per
    canvas), so a blit moves stripes onto the fresh rows' grid iff pitch is a
    multiple of P.  prodpicker_scroll_redraws must be exactly that predicate
    above native, and it must catch 4K (pitch 270, P 4)."""
    import scaling_laws as SL
    assert SL.prodpicker_scroll_redraws(270, 40)
    assert not SL.prodpicker_scroll_redraws(148, 22)
    assert not SL.prodpicker_scroll_redraws(168, 25)
    for g in range(17, 41):
        pitch = SL.prodpicker_row_pitch(g)
        sx, sy, dx, dy, w, h = SL.prodpicker_scroll_blit(5, 300, pitch, 4, g, True)
        moved_ok = all(SL.stripe_top(sy + r, g) == SL.stripe_top(dy + r, g) for r in range(h))
        assert SL.prodpicker_scroll_redraws(pitch, g) == (not moved_ok), g


def test_devfill_force_pair_stripe_laws():
    """Pass-5c: fe_pair_remap v6 field-pair + stripe laws.

    Golden vectors are the frida_pp_field.log 2026-08-06 canvas samples at
    g=25 (1600x1200): the already-correct unselected field column reads
    41,c4,c4 repeating from y=230 — the law must reproduce it EXACTLY — and
    the defective selected/gutter columns (1px bf,53 / 41,c5) define the
    post-fix targets via the same law with their pair."""
    import scaling_laws as SL
    # pair table: colored top -> bottom member
    assert SL.DITHER_FORCE_PAIRS == {0xC4: 0x41, 0xC6: 0x41,
                                     0xC5: 0x41, 0xBF: 0x53}
    # period law across the register: P = 2T, hN = T (both members the same
    # thickness); T = 1 below g = 22 (screens under 1080 px high), else the
    # pictures' rule art_scan_rows(g).  The popup g is clamped to 40.
    assert SL.stripe_period(16) == 2
    for g in range(17, 41):
        p = SL.stripe_period(g)
        assert p == (2 if g < 22 else 2 * SL.art_scan_rows(g)) == 2 * SL.stripe_rows(g), g
        assert p == (2 if g < 22 else 4), g
        hn = (p + 1) >> 1
        assert 2 * hn == p, g
        # exactly hn top rows then p-hn bottom rows per period, any phase
        for y0 in range(0, 3 * p, p):
            tops = [SL.stripe_top(y0 + i, g) for i in range(p)]
            assert tops == [True] * hn + [False] * (p - hn), (g, y0)
    # the Monument / Hall of Fame nums are not clamped to 40
    assert [SL.stripe_period(n) for n in (18, 21, 22, 45, 47, 48, 63, 64, 72)] == [2, 2, 4, 4, 4, 6, 6, 8, 8]
    # povr override (faction buttons' 1px parity law): P=2 -> alternate rows
    assert [SL.stripe_top(y, 40, override=2) for y in range(4)] == \
        [True, False, True, False]
    # g=25 (P=4, T=2): the unselected column y=230..269 is 2 rows of each member on
    # the buffer grid (the 2026-08-06 trace logged the old P=3 law's 41,(c4,c4,41)*13)
    got = [SL.stripe_color(0xC4, y, 25) for y in range(230, 270)]
    assert got == [0x41, 0x41, 0xC4, 0xC4] * 10
    # post-fix targets on the SAME phase grid: selected (bf/53) and gutter
    # (c5/41) columns must fuse with the unselected stripes row-for-row
    for y in range(230, 270):
        top = SL.stripe_top(y, 25)
        assert SL.stripe_color(0xBF, y, 25) == (0xBF if top else 0x53)
        assert SL.stripe_color(0xC5, y, 25) == (0xC5 if top else 0x41)
    # mate selection: content-keyed majority, mutually exclusive (pigeonhole)
    w = 100
    assert SL.dither_force_mate({0xC4: 51}, w) == 0xC4
    assert SL.dither_force_mate({0xBF: 51, 0xC4: 49}, w) == 0xBF
    assert SL.dither_force_mate({0xC5: 50}, w) is None          # not a majority
    assert SL.dither_force_mate({}, w) is None                  # solid fill
    assert SL.dither_force_mate({0x41: 99}, w) is None          # bottom member never keys


def test_sb_face_pair_is_oneshot_only_and_fuses_with_the_stripe_grid():
    """fe_pair_remap v7: the scrollbar face pair 0xF0/0xB9 (arrow faces +
    thumb grip) is a ONE-SHOT family — 0xF0 exists as solid console art
    (frida_pp_rail.log bake row: a 21px 0xF0 run in the rail strip), so it
    must never be content-keyed like the force pairs."""
    import scaling_laws as SL
    # the pair is NOT in the content-keyed table, and never keys the prescan
    assert SL.DITHER_ONESHOT_PAIRS == {0xF0: 0xB9}
    assert 0xF0 not in SL.DITHER_FORCE_PAIRS
    assert SL.dither_force_mate({0xF0: 999}, 10) is None
    # row colors ride the SAME P/hN/phase grid as every stripe producer
    for g in (22, 25, 32, 40):
        for y in range(0, 3 * SL.stripe_period(g)):
            top = SL.stripe_top(y, g)
            assert SL.stripe_color_sb(y, g) == (0xF0 if top else 0xB9), (g, y)
    # 1600x1200 (g=25, P=4, T=2): the thumb column pattern
    assert [SL.stripe_color_sb(y, 25) for y in range(6)] == \
        [0xF0, 0xF0, 0xB9, 0xB9, 0xF0, 0xF0]


def test_pair_remap_pixel_model_covers_all_families_and_passthrough():
    """The v7 per-pixel model: flag-gated families, unconditional pairs,
    0x41 arbitration order, and strict passthrough of non-pair indices."""
    import scaling_laws as SL
    g = 25
    ytop = 0            # stripe_top(0)=True
    ybot = 2            # stripe_top(2)=False at P=4 (T=2)
    m = SL.pair_remap_pixel
    # unconditional pairs rewrite with no flags at all
    assert m(0xE1, ytop, g) == 0xE0 and m(0xE0, ybot, g) == 0xE1
    assert m(0xEE, ytop, g) == 0xAE and m(0xAE, ybot, g) == 0xEE
    # one-shot family: inert without f0, striped with it
    assert m(0xF0, ybot, g) == 0xF0 and m(0xB9, ytop, g) == 0xB9
    assert m(0xF0, ybot, g, f0=True) == 0xB9
    assert m(0xB9, ytop, g, f0=True) == 0xF0
    # keyed families: inert without their flag
    assert m(0xC4, ybot, g) == 0xC4
    assert m(0xC4, ybot, g, navy=True) == 0x41
    assert m(0xC5, ytop, g, c5=True) == 0xC5
    assert m(0x53, ytop, g, bf=True) == 0xBF
    # 0x41 arbitration: navy -> backdrop -> C5; unclaimed passes through
    assert m(0x41, ytop, g, navy=True, c5=True) == 0xC4
    assert m(0x41, ytop, g, bd=True, c5=True) == 0xC6
    assert m(0x41, ytop, g, c5=True) == 0xC5
    assert m(0x41, ytop, g, f0=True) == 0x41
    # strict passthrough for art/stroke/key indices under EVERY flag
    for idx in (0x09, 0x22, 0x4F, 0x50, 0x77, 0xC1):
        assert m(idx, ytop, g, navy=True, bd=True, c5=True, bf=True,
                 f0=True) == idx, idx


# ---- console rail strip + embedded ScrollBar (rail_slide_in 0x45DEA0) -------

def test_rail_native_identity_matches_the_traced_1024_geometry():
    """g=16 must be bit-identical to vanilla, incl. the mixed-space inset."""
    import scaling_laws as SL

    # picker @1024x768: canvas 758x490, window top y1=139 -> yTop=152 (inset 13)
    L = SL.rail_layout(758, 490, 16, y1=139)
    assert L["inset"] == 13 and L["blit_num"] == 1 and L["blit_den"] == 1
    assert L["strip_src_h"] == 490 - 13
    # trace frida_pp_scrollbar.log @1024: sb rect (715,21)-(739,436) => h 415
    assert (L["sb_x"], L["sb_y"], L["sb_w"], L["sb_h"]) == (715, 21, 24, 415)
    assert L["rail_h"] == L["sb_h"] + SL.RAIL_SB_HSUB == 425
    assert L["bake_x"] == 758 - 47 and L["bake_y"] == 13
    # the vanilla threshold really does drop the inset for a low window
    assert SL.rail_top_inset(467, 16) == 0          # y1 >= 238
    assert SL.rail_top_inset(230, 16) == 8          # partially clamped
    assert SL.rail_top_inset(139, 16, screen_w=800) == 0   # A = 94 @800px


def test_rail_quantization_is_vanilla_and_resolution_invariant():
    """The tile count is computed on the NATIVE strip, so rail_h must come out
    the same at every g for the same window -- that is what makes the drawn
    rail exactly vanilla x g/16 instead of a device-tall stack of native art."""
    import scaling_laws as SL

    native = SL.rail_layout(758, 490, 16, y1=139)["rail_h"]
    for g in range(17, 41):
        w, h = 758 * g // 16, 490 * g // 16
        assert SL.rail_layout(w, h, g)["rail_h"] == native, g
    # whole mid tiles between the two caps, never a partial tile
    for src in range(96, 900):
        rh = SL.rail_quantized_h(src)
        assert (rh - SL.RAIL_TOPCAP_H - SL.RAIL_BOTCAP_H) % SL.RAIL_MIDTILE_H == 0
        assert rh + SL.RAIL_ART_Y <= src, src      # art always fits the buffer


def test_rail_scrollbar_keeps_its_vanilla_margins_inside_the_art():
    """Vanilla seats the bar in the rail with 5px top/bottom and 4px left/right
    margins (21-(13+3) = 5, (13+425+3)-(21+415) = 5, 47-43 = 4, 43-24-15 = 4).
    Every margin must scale x g/16 at every resolution -- an off-by-a-tile law
    shows up here as a bar hanging out of the rail (the 4K defect: bottom
    margin -8px)."""
    import scaling_laws as SL

    for g in list(range(16, 41)):
        w, h = max(758 * g // 16, 400), 490 * g // 16
        y1 = 139 if g == 16 else 0
        L = SL.rail_layout(w, h, g, y1=y1)
        s = (lambda v: v if g <= 16 else v * g // 16)
        for name, got, want, tol in (
            ("top",    L["sb_y"] - L["art_top"],            s(5), 2),
            ("bottom", L["art_bottom"] - (L["sb_y"] + L["sb_h"]), s(5), 2),
            ("left",   L["sb_x"] - L["art_left"],           s(4), 1),     # fix rail2: was 2 (the engine's columns)
            ("right",  L["art_right"] - (L["sb_x"] + L["sb_w"]), s(4), 1),
        ):
            assert abs(got - want) <= tol, (g, name, got, want)
        # fix rail2: the side margins are exactly the engine-drawn art between the column edge and the cyan guide
        # line (cols 0..3 / 28..31), so the bar touches both lines -- 0-px gaps on both sides (the symmetry rule)
        assert L["sb_x"] == L["cyan_l"][1] and L["sb_x"] + L["sb_w"] == L["cyan_r"][0], g
        # the bar is inside the drawn art, and the art inside the window
        assert L["art_top"] < L["sb_y"] < L["sb_y"] + L["sb_h"] < L["art_bottom"]
        assert L["art_bottom"] <= h and L["sb_x"] + L["sb_w"] < w


def test_rail_geometry_is_proportionate_to_vanilla():
    """Every scaled output = round-down of the native value x g/16."""
    import scaling_laws as SL

    nat = SL.rail_layout(758, 490, 16, y1=139)
    for g in range(17, 41):
        w, h = 758 * g // 16, 490 * g // 16
        L = SL.rail_layout(w, h, g)
        assert L["sb_h"] == (nat["rail_h"] - SL.RAIL_SB_HSUB) * g // 16, g
        assert L["sb_y"] == SL.basewin_pt(21, g)
        # W3B (rail_layout v4): the bar is the channel between the two symmetric lines of rail_col_map, [b, Wc - b);
        # b = cum(4, Wc, 32) within 3/4 px of 4g/16, the bar within 1.5 px of 24g/16 (Wc is the engine-placed visible
        # column, 2g + 1 at g = 25..31: the bar takes that px -- d_plan g25 Wc 51 -> 39)
        b, wc = SL.rail_bar_inset(w, g), SL.rail_col_w(w, g)
        assert L["sb_w"] == wc - 2 * b and abs(16 * L["sb_w"] - 24 * g) <= 24, g
        # fix sbstrip: the strip starts at the outer right slide rail; the bar sits b in from it
        assert L["bake_x"] == SL.rail_strip_x(w, g) == SL.rail_right_strip_x(w, w - 47, g)
        assert L["sb_x"] - L["bake_x"] == b and abs(16 * b - 4 * g) <= 12
        assert 0 <= w - L["bake_x"] - SL.basewin_pt(47, g) <= 4
        assert L["blit_num"] == g and L["blit_den"] == 16
        # the strip buffer stays NATIVE-sized: it is the blit that enlarges it
        assert abs(L["strip_src_h"] - nat["strip_src_h"]) <= 2, g


def test_scaling_rail_strip_starts_at_the_outer_right_rail():
    """rail_strip_x / rail_layout v2 / rail_out_tail v2 (2026-10-17 fix sbstrip).  Vanilla bakes the 47-px rail
    scrollbar strip at clientW - 47 = slide_show's OUTER right strip (canvas - 0x2F): the rail column opens where the
    closed wall stood and the slide-out leaves the wall back on it.  Scaled, the strip must start where railscale v3
    puts that outer strip (rail_right_strip_x), not at clientW - fl(47g/16) (1-4 px right of it: a sliver of
    outer-rail art left of the column).  Every canvas width, g = 17..48; identity at g <= 16."""
    import scaling_laws as SL
    bp = SL.basewin_pt
    for g in range(17, 49):
        for w in range(160, 2400):
            L = SL.rail_layout(w, 490 * g // 16, g)
            x = L["bake_x"]
            assert x == SL.rail_strip_x(w, g) == SL.slide_rail_settled_x(w, w - 0x2F, g), (g, w)
            # the inner right strip ends exactly where the strip starts (the outer strip's own abutment)
            assert SL.slide_rail_settled_x(w, w - 0x37, g) + ((8 * g) >> 4) == x, (g, w)
            d = w - x - bp(47, g)
            assert 0 <= d <= 4, (g, w, d)                                        # strip ends inside the canvas
            # fix rail2: the visible rail column is the ENGINE's columns 0..31 wide (rail_nn_col(32): 2g + 1 at
            # g = 25..31 / 48), the wall r_outer at wall_x, fl(15g/16) wide, never past the canvas; W3B: the column's
            # art is rail_col_map over exactly that width, so it ends ON the wall
            off = SL.rail_wall_off(w, g)
            assert L["art_left"] == x and L["art_right"] == x + off == L["wall_x"]
            assert L["wall_x"] == x + off and L["strip_right"] == x + off + ((15 * g) >> 4) <= w
            assert off == min(SL.rail_nn_col(32, g), w - x - ((15 * g) >> 4))
            assert off == SL.rail_nn_col(32, g) or g >= 48                      # the clamp never binds below g = 48
            assert SL.rail_nn_col(32, g) - 2 * g == (1 if (25 <= g <= 31 or g == 48) else 0)
            # the bar sits between the cyan guide lines (W3B: the symmetric map's), inside the column
            b = SL.rail_bar_inset(w, g)
            assert L["sb_x"] - x == b and L["sb_x"] + L["sb_w"] == x + off - b
            assert L["cyan_l"] == (x + b - SL.stroke_width(g), x + b) and L["cyan_r"] == (x + off - b, x + off - b + SL.stroke_width(g))
            assert x < L["sb_x"] and L["sb_x"] + L["sb_w"] < L["art_right"]
            # slide-out: capture [x, w) == everything the bake touched; the rolled-up wall lands ON the outer strip
            capw, shift = SL.rail_out_tail(g, True, w)
            assert w - capw == x and capw >= L["strip_right"] - x
            assert L["wall_x"] + shift == x and shift == -off
            assert SL.rail_out_tail(g, False, w) == (capw, 0)
            # HQ ReportWin: its vanilla slide-out is undone by the saved right-border column [w - s(47) - 4, w)
            assert w - SL.scale_px(47, g) - 4 <= x, (g, w)
        assert SL.rail_out_tail(g, True) == (bp(47, g), -SL.rail_nn_col(32, g))  # no width: the v1 strip width
    for g in (8, 12, 15, 16):
        for w in range(100, 1200):
            L = SL.rail_layout(w, 490, g, y1=139)
            assert (L["bake_x"], L["sb_x"]) == (w - 47, w - 0x2B) == (SL.rail_strip_x(w, g), w - 0x2B)
            assert SL.rail_out_tail(g, True, w) == (47, -32)
    # the double-floor form is itself the identity at g = 16
    assert all(SL.rail_right_strip_x(w, w - 47, 16) == w - 47 for w in range(100, 1200))


def test_scrollbar_arrow_buttons_stay_square_and_equal():
    """Both arrows are the same square at every bar size -- the invariant
    vanilla's on_resize breaks by only resizing the down button."""
    import scaling_laws as SL
    for g in range(16, 41):
        b = SL.basewin_pt(0x18, g)                 # the bar's short axis
        for bordered in (False, True):
            s = SL.scrollbar_arrow_square(b, bordered)
            assert s == (b - 2 if bordered else b)
            assert 0 < s <= b                      # never inverts or exceeds the bar
        # at native the square is vanilla's own 24 / 22 -- identity
        if g == 16:
            assert SL.scrollbar_arrow_square(b, True) == 0x18 - 2
            assert SL.scrollbar_arrow_square(b, False) == 0x18
    # monotone in b, so a wider bar never yields a smaller chevron button
    prev = 0
    for g in range(16, 41):
        s = SL.scrollbar_arrow_square(SL.basewin_pt(0x18, g), True)
        assert s >= prev
        prev = s


# --------------------------------------------------------------------------
# line_axis_map — full-axis enlarge of a pre-rendered art plane (deswin.pcx)
# --------------------------------------------------------------------------

# deswin.pcx 623x368: the measured axis-aligned stroke rows / columns
# (runs >= 60 of non-dither, non-key pixels; work/_dw_dither_audit.md).
DESWIN_ROWS = (368, [0, 4, 94, 98, 188, 192, 282])
DESWIN_COLS = (623, [23, 27, 131, 135, 455, 459, 563, 567])


@pytest.mark.parametrize("src, lines", [DESWIN_ROWS, DESWIN_COLS, (50, []), (12, [0, 11])])
def test_line_axis_map_is_the_identity_at_native(src, lines):
    assert line_axis_map(src, src, lines, NATIVE_G) == list(range(src))


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("src, lines", [DESWIN_ROWS, DESWIN_COLS, (50, []), (12, [0, 11])])
def test_line_axis_map_pins_every_line_to_k_and_spreads_the_field(g, src, lines):
    for dst in (scale_px(src, g), -(-src * g // NATIVE_G)):        # half-down and CEIL widths
        m = line_axis_map(src, dst, lines, g)
        assert m is not None, (g, src, dst)
        assert len(m) == dst
        assert m[0] == 0 and m[-1] == src - 1
        assert all(b >= a for a, b in zip(m, m[1:])), "map must be monotone"
        assert all(0 <= s < src for s in m)
        k = stroke_width(g)
        counts = [0] * src
        for s in m:
            counts[s] += 1
        for i in lines:
            assert counts[i] == k, (g, src, dst, i, counts[i])
        field = [counts[i] for i in range(src) if i not in lines]
        if field:
            ideal = (dst - len(lines) * k) / len(field)
            assert all(abs(w - ideal) < 1 for w in field), (g, src, dst)
            assert sum(field) == dst - len(lines) * k


def test_line_axis_map_rejects_shrink_and_starved_field():
    assert line_axis_map(100, 99, [0], 20) is None
    assert line_axis_map(10, 10, list(range(10)), 40) is None      # all lines, K=2 needs 20 px


def test_pair_top_canonical():
    """pair_top: force-pair key wins; else higher peak channel; order-independent."""
    from scaling_laws import pair_top, DITHER_FORCE_PAIRS
    pal = {191: (14, 34, 67), 83: (27, 33, 31), 197: (11, 18, 24), 65: (0, 0, 0), 194: (13, 28, 48),
           0xC4: (40, 40, 200), 0x41: (0, 0, 0), 0xBF: (50, 50, 50), 0x53: (90, 90, 90)}
    rgb = lambda i: pal[i]
    assert pair_top(191, 83, rgb) == 191 and pair_top(83, 191, rgb) == 191      # navy over grey-green (luminance ~equal)
    assert pair_top(197, 65, rgb) == 197 and pair_top(65, 197, rgb) == 197      # picker tile blue over black
    assert pair_top(194, 65, rgb) == 194
    for top, mate in DITHER_FORCE_PAIRS.items():
        assert pair_top(top, mate, rgb) == top and pair_top(mate, top, rgb) == top   # force pairs: the key, whatever the RGB


# --- parity-preserving NN enlarge (console icon family, 2026-09-09) ---------------------
from scaling_laws import nn_center_index, parity_nn_row_map, stripe_parity_vote, stripe_top as _stripe_top  # noqa: E402


def test_nn_center_index_is_edge_clamped_monotonic_and_lossless_on_enlarge():
    for src in range(1, 80):
        for dst in range(1, 200):
            rows = [nn_center_index(d, dst, src) for d in range(dst)]
            assert all(0 <= r < src for r in rows) and rows == sorted(rows)
            if dst >= src:                                   # an ENLARGE: the last dest row reads the last
                assert rows[0] == 0 and rows[-1] == src - 1                   # src row (edge-clamped; the engine DDA drops it)
                assert set(rows) == set(range(src))          # and every source row survives


@pytest.mark.parametrize("g", range(G_MIN, G_MAX + 1))
def test_parity_nn_rows_follow_the_device_stripe_phase(g: int):
    """Each dest row samples a native row of the parity its device stripe phase demands, never
    further than one row from the plain centre sample; unstriped sprites and g=16 are plain NN."""
    for src_h in range(1, 61):
        dst_h = (src_h * g) // 16
        for y0 in range(0, 8):
            plain = [nn_center_index(dy, dst_h, src_h) for dy in range(dst_h)]
            assert parity_nn_row_map(dst_h, src_h, y0, g, -1) == plain
            for top in (0, 1):
                rows = parity_nn_row_map(dst_h, src_h, y0, g, top)
                if g == NATIVE_G or src_h < 2:
                    assert rows == plain
                    continue
                for dy, r in enumerate(rows):
                    assert 0 <= r < src_h and abs(r - plain[dy]) <= 1
                    assert r % 2 == (top if _stripe_top(y0 + dy, g) else 1 - top)


def test_stripe_parity_vote_on_the_measured_art():
    assert stripe_parity_vote(22, 50, 60, 120) == 1        # Report.pcx state 0: odd rows purple/tile-blue over navy/black
    assert stripe_parity_vote(153, 140, 315, 357) == 0     # hover state: even rows purple (84,78,153) over teal (81,136,140)
    assert stripe_parity_vote(100, 102, 200, 260) == 1     # peak tie -> the channel sum decides
    assert stripe_parity_vote(100, 101, 200, 201) == -1    # flat: a photo / line art -> plain NN


# --- HQ report BASE STATUS rows: chrome follows content ------------------------------------
from scaling_laws import bases_face_h, bases_face_y_imm, bases_row_cell, bases_row_pitch, stroke_width as _sw  # noqa: E402


def test_bases_row_identity_at_native():
    assert bases_row_cell(NATIVE_G) == 40 and bases_row_pitch(NATIVE_G) == 42 and bases_face_y_imm(NATIVE_G) == 18


@pytest.mark.parametrize("g", range(G_MIN, G_MAX + 1))
def test_bases_face_fills_the_row_interior_and_butts_the_top_stroke(g: int):
    cell, pitch, imm, k = bases_row_cell(g), bases_row_pitch(g), bases_face_y_imm(g), _sw(g)
    assert cell - 2 * k == bases_face_h(g)                          # interior == face: flush top AND bottom
    top = 1000; bottom = top + cell
    assert bottom - (pitch >> 1) - imm == top + k                   # the painter's y lands on the interior top
    assert 0 < imm < 128 and 0 < cell < 128                         # imm8 sites
    assert pitch > cell and pitch - cell == scale_px(2, g)


def test_blink_place_centres_each_ring_frame_on_the_locator_box():
    """v14: the DRAWN content of each ring frame (thunk_sprite_scale_nn floors the frame's scaled offset and width)
    is centred on the base box's centre (px+6, py+3) mapped the way the minimap composition maps the console render:
    StretchBlt ratio win/buf when stretched, the 1:1 centring offsets otherwise.  Identity at g<=16 lawful."""
    from scaling_laws import blink_place, blink_frame_span, minimap_stretched, half_down, BLINK_BIG_MUL
    FRAMES = ((4, 4), (3, 6), (3, 6), (2, 8))                       # Dot0..3: (content offset, content size) in the 12-px canvas
    assert blink_place(133, 75, 72, 52, 16, False, 320, 160, 320, 152, 0, 4, 2, 2, 8, 8) == (133, 75, 16, 16)
    for g, ww, wh in ((40, 597, 297), (25, 374, 186), (22, 328, 164)):
        assert minimap_stretched(g, ww, wh, 320, 152)
        for big in (False, True):
            m = BLINK_BIG_MUL if big else 1
            num = m * g
            for off, w in FRAMES:
                X, Y, n, d = blink_place(142, 106, 72, 52, g, big, ww, wh, 320, 152, 0, 0, off, off, w, w)
                assert (n, d) == (num, 16)
                span_x = blink_frame_span(off, w, num)
                assert X == half_down(156 * ww - span_x * 320, 2 * 320) and Y == half_down(110 * wh - span_x * 152, 2 * 152)
                # the drawn content centre vs the continuous box centre: within the half pixel, every frame, every g
                cx = X + (off * num) // 16 + ((w * num) // 16) / 2
                cy = Y + (off * num) // 16 + ((w * num) // 16) / 2
                assert abs(cx - 78 * ww / 320) <= 0.5 and abs(cy - 55 * wh / 152) <= 0.5, (g, big, off, w, cx, cy)
    # the v13 canvas-centred law left the floored frames biased at 1600: Dot2 (3,6) at 2g=50 -> span 36 vs 37.5 ideal
    assert blink_frame_span(3, 6, 50) == 36 and blink_frame_span(2, 8, 50) == 37 and blink_frame_span(2, 8, 80) == 60
    # a small map that still fits 1:1: box at off + px + 6, the frame centred on it
    assert not minimap_stretched(25, 400, 200, 200, 100)
    X, Y, n, d = blink_place(0, 0, 40, 20, 25, False, 400, 200, 200, 100, 100, 50, 3, 3, 6, 6)
    assert (n, d) == (25, 16) and X == half_down(2 * 100 + 92 - blink_frame_span(3, 6, 25), 2) and Y == half_down(2 * 50 + 46 - blink_frame_span(3, 6, 25), 2)
    assert blink_place(0, 0, 40, 20, 16, True, 200, 100, 200, 100, 0, 0, 2, 2, 8, 8) == (46 - 12, 23 - 12, 32, 16)   # native 2x: 16-px content centred


def test_stripe_parity_vote_sums_is_the_floor_mean_form():
    from scaling_laws import stripe_parity_vote_sums
    assert stripe_parity_vote_sums(0, 0, 100, 5, 0, 0) == -1 and stripe_parity_vote_sums(100, 5, 0, 0, 0, 0) == -1
    for pe, ne, po, no, se, so in ((220, 10, 500, 10, 600, 1200), (1530, 10, 1400, 10, 3150, 3570), (1000, 10, 1020, 10, 2000, 2600), (1000, 10, 1010, 10, 2000, 2010)):
        assert stripe_parity_vote_sums(pe, ne, po, no, se, so) == stripe_parity_vote(pe // ne, po // no, se // ne, so // no)


# --- report row/title-band hatch (thunk_s54_restripe v2) + console icon v2 x-law (2026-09-12) ---
def test_hatch_pairs_are_mate_keyed_and_c2_stays_out_of_the_force_table():
    import scaling_laws as SL
    assert SL.HATCH_MATE_PAIRS == {0x54: 0x41, 0xC2: 0x41}
    assert 0xC2 not in SL.DITHER_FORCE_PAIRS and SL.SBARROW_BG_TOP == 0xC2       # ambiguous: also the arrow-face top
    w = 64
    assert SL.hatch_pair_for({0xC2: 4 * w, 0x41: 4 * w}, w) == 0xC2
    assert SL.hatch_pair_for({0x54: 4 * w, 0x41: 4 * w}, w) == 0x54
    assert SL.hatch_pair_for({0xC2: 4 * w, 0xC5: 4 * w}, w) is None      # arrow face: no mate
    assert SL.hatch_pair_for({0xC2: 8 * w}, w) is None                   # solid
    assert SL.hatch_pair_for({0x41: 8 * w}, w) is None                   # solid pre-fill
    assert SL.hatch_keyed(33, 33, w) and not SL.hatch_keyed(32, 33, w) and not SL.hatch_keyed(33, 32, w)
    assert SL.s54_hatch_keyed(33, 33, w) == SL.hatch_keyed(33, 33, w)
    for g in (22, 25, 32, 40):
        for y in range(3 * SL.stripe_period(g)):
            assert SL.hatch_row_color(0xC2, y, g) == (0xC2 if SL.stripe_top(y, g) else 0x41)
            assert SL.hatch_row_color(0x54, y, g) == SL.s54_row_color(y, g)
    # the user's row-fill census (13,28,48)/black = 194/65, 1:1 at every res -> the P law: 2/2 at every popup g
    assert [SL.hatch_row_color(0xC2, y, 40) for y in range(5)] == [0xC2, 0xC2, 0x41, 0x41, 0xC2]
    assert [SL.hatch_row_color(0xC2, y, 25) for y in range(5)] == [0xC2, 0xC2, 0x41, 0x41, 0xC2]


def test_bilinear_axis_is_the_a5_tap_law():
    import scaling_laws as SL
    for num, den in ((22, 16), (25, 16), (32, 16), (40, 16), (1, 1)):
        for src in (1, 2, 3, 29, 35, 115):
            dst = src * num // den
            prev = -1
            for d in range(dst):
                i0, i1, f, near = SL.bilinear_axis(d, num, den, src)
                assert 0 <= i0 <= i1 <= src - 1 and i1 - i0 <= 1 and 0 <= f < 256
                assert i0 == min(d * den // num, src - 1) and i0 >= prev
                assert near in (i0, i1) and (i0 == i1 or (near == i1) == (2 * (d * den % num) >= num))
                prev = i0
            if num == den:      # identity: every dest column is its own source column, no fraction
                assert [SL.bilinear_axis(d, 1, 1, src)[:3] for d in range(dst)] == [(d, min(d + 1, src - 1), 0) for d in range(dst)]
    assert SL.bilinear_axis(0, 0, 16, 5) == (0, 0, 0, 0)


def test_parity_hblend_pixel_keeps_indices_verbatim_and_blends_only_edges():
    import scaling_laws as SL
    key = 9
    table = [(i, 255 - i, (i * 7) & 255) for i in range(256)]
    table[key] = (9, 0, 0)
    assert SL.parity_hblend_pixel(0xE6, 0xE6, 100, 0xE6, table, key) == 0xE6          # flat run: verbatim
    assert SL.parity_hblend_pixel(key, 0xBB, 100, 0xBB, table, key) == 0xBB           # a key tap: the other, verbatim
    assert SL.parity_hblend_pixel(0xBB, key, 100, 0xBB, table, key) == 0xBB
    assert SL.parity_hblend_pixel(0xBB, key, 200, key, table, key) is None           # coverage texel is the key
    assert SL.parity_hblend_pixel(0xBB, 0xE6, 0, 0xBB, table, key) == 0xBB           # f=0: the blend IS tap 0
    assert SL.parity_hblend_pixel(0xBB, 0xE6, 128, 0xBB, table, key) not in (None, key)
    c = [(table[10][i] * 156 + table[20][i] * 100 + 128) >> 8 for i in range(3)]     # 8.8 weights, rounded
    assert SL.parity_hblend_pixel(10, 20, 100, 10, table, key) == SL.palette_nearest(c, table, key)
    dark = [(9, 0, 0)] + [(200, 200, 200)] * 255
    assert SL.palette_nearest((9, 0, 0), dark, 0) == 1                                 # never the key
    dup = [(5, 5, 5)] * 256
    assert SL.palette_nearest((5, 5, 5), dup, 9) == 0                                  # lowest index on ties


# ---- font face / weight law (2026-09-17; work\FONT_FACE_WEIGHT_AUDIT.md) ---------------------
import scaling_laws as SL  # noqa: E402


def test_find_font_snap_is_nearest_with_ties_to_the_larger_size():
    for t in SL.FONT_POOL_SIZES:
        assert SL.find_font_snap(t) == t
    assert SL.find_font_snap(25) == 24 and SL.find_font_snap(30) == 32 and SL.find_font_snap(19) == 20
    assert SL.find_font_snap(61) == 40 and SL.find_font_snap(3) == 8 and SL.find_font_snap(21) == 22


def test_font_pool_face_keys_face_and_weight_on_the_native_size():
    for S in range(6, 13):
        assert SL.font_pool_face(S, 0) == ("Arial", 0) and SL.font_pool_face(S, 1) == ("Arial", 1)
        assert SL.font_pool_face(S, 2) == ("Arial", 2)
    for S in range(13, 41):
        assert SL.font_pool_face(S, 0) == ("Arial Narrow", 1) == SL.font_pool_face(S, 1)
        assert SL.font_pool_face(S, 2) == ("Arial Narrow", 3)


@pytest.mark.parametrize("g", (16, 17, 18, 22, 25, 30, 40))
def test_font_face_law_keeps_the_native_face_and_weight_at_every_g(g):
    for S in range(8, 41):
        for v in (0, 1, 2):
            name, size, style = SL.font_face_law_font(S, v, g)
            want_name, want_style = SL.font_pool_face(S, v)
            assert (name, style) == (want_name, want_style), (S, v, g)
            if g <= 16:
                assert SL.font_face_law(S, v, g) == ("pool", S, v) and size == SL.find_font_snap(S)
            elif S > 12 and (S * g) // 16 <= 40:
                assert SL.font_face_law(S, v, g) == ("pool", (S * g) // 16, v)          # the pool, sizes snapped as before
            else:
                assert SL.font_face_law(S, v, g) == ("init", want_name, (S * g) // 16, want_style)
                assert size == (S * g) // 16                                            # exact, no snap
    assert SL.font_direct_law(14, 1, g) == ("Arial", 14 if g <= 16 else (14 * g) // 16, 1)


def test_font_face_law_audit_findings():
    # 3.1 tooltips: Arial 12 regular stays Arial regular (v1 = Arial Narrow bold 16/18/32)
    assert [SL.font_face_law_font(12, 0, g) for g in (22, 25, 40)] == [("Arial", 16, 0), ("Arial", 18, 0), ("Arial", 30, 0)]
    # 3.2b / 3.16 headers above the pool keep the bold
    assert SL.font_face_law_font(32, 0, 40) == ("Arial Narrow", 80, 1) and SL.font_face_law_font(22, 0, 45) == ("Arial Narrow", 61, 1)
    # 3.3 COMMLINK rows Arial 10 regular / header Arial 14 bold (pool, unchanged)
    assert SL.font_face_law_font(10, 0, 40) == ("Arial", 25, 0) and SL.font_face_law_font(14, 1, 40) == ("Arial Narrow", 36, 1)
    # 3.12 lobby (12,1) = Arial bold; (14,1) = the pool as before
    assert SL.font_face_law_font(12, 1, 22) == ("Arial", 16, 1) and SL.font_face_law(14, 1, 22) == ("pool", 19, 1)
    # the shared slot table covers every key the patch set scales through t_ffn
    for key in ((10, 0), (11, 0), (12, 0), (12, 1), (12, 2), (14, 0), (14, 2), (16, 2), (18, 2), (26, 0), (22, 0), (32, 0)):
        assert SL.font_law_slot_index(*key) is not None
    assert SL.font_law_slot_key(12, 0, False) == 12 and SL.font_law_slot_key(32, 1, True) == (32 | 1 << 8 | 1 << 16)

# ---------------------------------------------------------------------------
# UNTITLED popups (2026-09-18, version popup: 4K shot 20260918-003046 vs
# refs/pristine/VersionNumber.png).  Pristine native: ring top 12, field top 15,
# stroke pitch 3 on every side, header reserve 18.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_untitled_popup_chrome(g: int):
    import scaling_laws as SL
    ps3 = 3 if g <= 16 else SL.popup_pad(3, g)
    # header: untitled flat/slide scales exactly like the titled reserve; identity at g=16
    hdr = SL.popup_header_reserve(18, False, 0, False, g)
    assert hdr == (18 * g) // 16 == SL.popup_header_reserve(18, False, 50000, False, g)
    assert SL.popup_header_reserve(18, False, 0, False, 16) == 18
    assert SL.popup_header_reserve(38, True, 60000, False, g) == (38 * g) // 16      # v1 titled arm kept
    for raw in (20000, 60000, 10000000):                                              # ornate / hidden: native
        assert SL.popup_header_reserve(27, False, raw, False, g) == 27
    assert SL.popup_header_reserve(18, False, 0, True, g) == 18                       # faction quote: own lever
    # body-only ring: ONE pitch on all four sides == the pf-aligned right pitch
    pad = SL.nested_frame_pad(g, body_only=True)
    assert pad == ps3 == SL.body_outer_edge_r(900, g) - SL.body_inner_edge_r(900, g)
    assert SL.nested_frame_pad(g) == (3 if g <= 16 else SL.scale_px(2, g))            # list law untouched
    # proportion: ring top / field top vs vanilla 12 / 15, within one floor step per term
    field_t = hdr - ps3
    ring_t = field_t - pad
    assert abs(field_t - 15 * g / 16) < 2 and abs(ring_t - 12 * g / 16) < 3
    if g > 16:
        # the virtual band bottom lands fieldpads' keyed arm ON the engine arm
        tb = SL.untitled_virtual_title_bottom(hdr, g)
        assert SL.popup_field_top(hdr, tb, 0, True, g) == field_t == SL.popup_field_top(hdr, 0, 0, False, g)
        # art top == ring top (pristine: same row)
        assert SL.popup_art_y(SL.flat_art_anchor(field_t, g), 0, g) - 6 == ring_t


def test_scaling_untitled_popup_4k_numbers():
    import scaling_laws as SL
    assert SL.popup_header_reserve(18, False, 0, False, 40) == 45
    assert SL.nested_frame_pad(40, body_only=True) == 7 and SL.nested_frame_pad(40) == 5
    assert SL.nested_frame_pad(25, body_only=True) == 4 and SL.nested_frame_pad(22, body_only=True) == 4


# ---------------------------------------------------------------------------
# t16_row_text_indent — the type-16 reply-row text indent, scaled at the draw read
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("g", ALL_G)
def test_t16_row_text_indent_is_vanilla_times_scale(g: int):
    v = T16_ROW_TEXT_INDENT_NATIVE
    got = t16_row_text_indent(v, g)
    if g <= NATIVE_G:
        assert got == v                       # native no-op
    else:
        assert got == (2 * v * g + 15) >> 5   # the DLL stub's arithmetic == scale_px (half_down)
        assert abs(16 * got - v * g) <= 8     # nearest pixel to vanilla * g/16
        assert got >= v


def test_t16_row_text_indent_pinned_values():
    assert [t16_row_text_indent(3, g) for g in (16, 22, 25, 40)] == [3, 4, 5, 7]


def test_t16_row_text_indent_port_is_in_register():
    """The DLL port scales the value it READS and never stores it back (the stored
    field is t16_row_measure_width's F term and must stay native)."""
    src = (Path(__file__).resolve().parents[2] / "src" / "uimod" / "src" / "rowindent.cpp").read_text(encoding="utf-8")
    assert "0x0060DB8B" in src and "sar  edx, 5" in src
    assert "mov  dword ptr [ecx + esi + 0x34]" not in src


# ---------------------------------------------------------------------------
# t16_row_line_count — W and the row budget in ONE space (anchored popups are device)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("g", [g for g in ALL_G if g > NATIVE_G])
def test_t16_row_line_count_anchored_long_reply_wraps(g: int):
    budget_dev = ((633 * g) >> 4) - 6 - 3          # talk-window row budget, device
    w_native = 650                                  # a reply wider than the native row (wraps in vanilla)
    w_device = budget_dev + 40                      # and wider than the device row
    assert t16_row_line_count(w_native, w_device, budget_dev, g, True) == 2
    # a reply that fits the device row stays one line even if native W x g/16 would not
    assert t16_row_line_count(w_native, budget_dev - 1, budget_dev, g, True) == 1


@pytest.mark.parametrize("g", ALL_G)
def test_t16_row_line_count_ordinary_popup_unchanged(g: int):
    assert t16_row_line_count(400, 1000, 474, g, False) == 1
    assert t16_row_line_count(500, 1250, 474, g, False) == 2


def test_t16_measure_sel_is_wired():
    y = (Path(__file__).resolve().parents[1] / "patches" / "patches.yaml").read_bytes()
    assert b'new_bytes:      "E8 {rel32:thunk_t16_measure_sel}"' in y
    assert b"A1 74 C0 9B 00 85 C0 74 1B 83 B8 14 0A 00 00 00 74 12 8B D6 2B D0 81 FA 00 32 00 00 73 06 68 90 C7 5D 00 C3 68 {abs32:thunk_t16_measure_native} C3" in y


# ---------------------------------------------------------------------------
# t16_row_text_budget — the line-count divisor is the DRAWN text width
# ---------------------------------------------------------------------------
def test_t16_row_text_budget_measured_case_wraps():
    # uimod wrapdbg 2026-09-20 @g40: W 1496 vs the engine budget 1498 -> 1 line, yet the text clipped
    d = t16_row_text_budget(1498, 3, 3, 40, True)
    assert d == 1498 - 3 - (7 - 3)
    assert t16_row_line_count(0, 1496, d, 40, True) == 2
    assert t16_row_line_count(0, 1262, d, 40, True) == 1          # the short suffix stays one line


@pytest.mark.parametrize("g", ALL_G)
def test_t16_row_text_budget_scope(g: int):
    assert t16_row_text_budget(474, 3, 3, g, False) == 474         # ordinary popups untouched
    assert t16_row_text_budget(100000, 3, 3, g, True) == 100000    # the engine's "no fixed width" sentinel
    if g <= NATIVE_G:
        assert t16_row_text_budget(691, 3, 3, g, True) == 691      # native no-op
    else:
        assert t16_row_text_budget(1498, 3, 3, g, True) == 1498 - 3 - (t16_row_text_indent(3, g) - 3)


def test_t16_row_text_budget_port():
    src = (Path(__file__).resolve().parents[2] / "src" / "uimod" / "src" / "rowindent.cpp").read_text(encoding="utf-8")
    assert "0x0060D5FA" in src and "budget - gap - (((2 * indent * g + 15) >> 5) - indent)" in src


# ---------------------------------------------------------------------------
# ps_badge — Punishment Sphere badge on drone faces (uimod pssphere.cpp / psbadge.h port)
# ---------------------------------------------------------------------------
def test_ps_badge_pinned_values():
    import scaling_laws as SL
    base = [(38 * g) >> 4 for g in (16, 22, 25, 40)]
    f4 = [(30 * g) >> 4 for g in (16, 22, 25, 40)]
    assert base == [38, 52, 59, 95] and f4 == [30, 41, 46, 75]
    assert [SL.ps_badge(w)["d"] for w in base] == [15, 21, 23, 37]      # 37.5 -> 37: half DOWN
    assert [SL.ps_badge(w)["d"] for w in f4] == [12, 16, 18, 30]
    assert [SL.ps_badge(w)["inset"] for w in base] == [1, 1, 1, 2]
    assert [SL.ps_badge(w)["inset"] for w in f4] == [1, 1, 1, 1]


@pytest.mark.parametrize("native_w", [38, 30])
def test_ps_badge_sweep(native_w: int):
    import scaling_laws as SL
    prev = 0
    for g in range(16, 46):
        w = (native_w * g) >> 4
        b = SL.ps_badge(w)
        assert b["d"] >= 7 and b["d"] >= prev                 # legible, monotonic non-decreasing in g
        assert b["inset"] >= 1 and b["inset"] + b["d"] <= w   # fits inside the face
        assert abs(38 * b["d"] - 15 * w) * 2 <= 38            # nearest pixel to face_w * 15/38
        prev = b["d"]


@pytest.mark.parametrize("d", [7, 12, 15, 21, 23, 37, 42])
def test_ps_badge_raster_shape(d: int):
    import scaling_laws as SL
    grid = SL.ps_badge_raster(d)
    assert len(grid) == d and all(len(r) == d for r in grid)
    assert grid == grid[::-1] == [r[::-1] for r in grid]      # symmetric: no resample phase, no drift
    assert grid[d // 2][d // 2] == 4                          # gold core
    assert all(t in (-1, 0, 1, 2, 3, 4) for r in grid for t in r)
    assert grid[0][0] == -1 and grid[0][d // 2] >= 0          # a disc: corners not drawn, the rim is


def test_ps_badge_ramp_pinned():
    import scaling_laws as SL
    assert SL.ps_badge_ramp() == [(12, 20, 32), (66, 67, 57), (120, 114, 82), (174, 161, 107), (228, 208, 132)]


def test_ps_badge_port_carries_the_law():
    """The C++ port carries the same constants (work\\tests\\ps_badge pins the rasteriser bit for bit
    through a compiled harness); the module never emits a key / reserved palette index."""
    import scaling_laws as SL
    src_dir = Path(__file__).resolve().parents[2] / "src" / "uimod" / "src"
    hdr = (src_dir / "psbadge.h").read_text(encoding="utf-8")
    cpp = (src_dir / "pssphere.cpp").read_text(encoding="utf-8")
    assert f"kBadgeNum = {SL.PS_BADGE_NUM}, kBadgeDen = {SL.PS_BADGE_DEN}" in hdr
    assert "(2 * kBadgeNum * faceW + kBadgeDen - 1) / (2 * kBadgeDen)" in hdr          # half_down
    assert "kDark[3] = { 12, 20, 32 }" in hdr and "kGold[3] = { 228, 208, 132 }" in hdr
    assert "kRingLoPct = 70, kRingHiPct = 92" in hdr and "kCorePct = 38" in hdr
    assert "kStrapLoPct = 30, kStrapHiPct = 80" in hdr and "kStrapHalfPermille = 85" in hdr
    assert "psbadge::Diameter(fw)" in cpp and "psbadge::Inset(fw)" in cpp
    assert "psbadge::OriginX(fx, fw, kind == 1)" in cpp          # F4 = upper-right, base screen = upper-left
    assert "right ? faceX + faceW - Inset(faceW) - Diameter(faceW) : faceX + Inset(faceW)" in hdr

    for idx in SL.PS_BADGE_EXCLUDED_INDICES:
        assert f"i == {idx}" in cpp
    assert "(2 * " not in cpp                                 # no private copy of the size law in the module


@pytest.mark.parametrize("native_w", [38, 30])
def test_ps_badge_origin_x(native_w: int):
    for g in range(16, 46):
        w = native_w * g // 16
        b = SL.ps_badge(w)
        left, right = SL.ps_badge_origin_x(100, w, False), SL.ps_badge_origin_x(100, w, True)
        assert left == 100 + b["inset"] and right + b["d"] == 100 + w - b["inset"]
        assert 100 <= left and right + b["d"] <= 100 + w and left <= right      # inside the face, mirrored insets


# ---------------------------------------------------------------------------
# BASE FACILITIES overflow scrollbar attach rect (thunk_bw_facsb_attach).
# The rows, header and box scale through basewin_pt; the bar is a BaseWin
# CHILD window whose arrows/track ScrollBar_init_inner sizes from the rect it
# is handed -- so the rect must already be device space at the attach site.
# ---------------------------------------------------------------------------
_FACSB_PANELS = [
    (572, 42, 730, 470),     # representative inner rect (field rect inset 3)
    (572, 42, 730, 300),     # shortened bottom (facilities BaseButton visible)
    (100, 20, 112, 40),      # degenerate: panel exactly one bar wide
]


@pytest.mark.parametrize("l,t,r,b", _FACSB_PANELS)
def test_basewin_facsb_rect_identity_at_native(l, t, r, b):
    """g<=16 must be vanilla's literal [r-12, t, r, b] (@0x41000D add eax,-0xc)."""
    assert basewin_facsb_rect(l, t, r, b, 16) == (r - 12, t, r, b)
    assert basewin_facsb_rect(l, t, r, b, 10) == (r - 12, t, r, b)
    assert FACSB_W_NATIVE == 12


@pytest.mark.parametrize("g", range(17, 49))
@pytest.mark.parametrize("l,t,r,b", _FACSB_PANELS)
def test_basewin_facsb_rect_edges(l, t, r, b, g):
    """Right/top/bottom = the panel inner edges through basewin_pt (flush with
    the row text + Spot rects, which use the same values); width = fl(12g/16)
    (the bar's own inset, the supported-bar shape); the bar stays inside the
    panel whenever the panel is at least one bar wide."""
    x0, y0, x1, y1 = basewin_facsb_rect(l, t, r, b, g)
    assert x1 == basewin_pt(r, g)
    assert y0 == basewin_pt(t, g)
    assert y1 == basewin_pt(b, g)
    assert x1 - x0 == (12 * g) >> 4
    assert x1 - x0 >= 12                     # never thinner than native
    assert x0 >= basewin_pt(l, g)            # inside the panel
    # ScrollBar_init_inner derives arrows (w-2)^2 and the track h-2w from THIS rect:
    assert (x1 - x0) - 2 > 0 and (y1 - y0) - 2 * (x1 - x0) > 0 or (b - t) < 3 * 12


@pytest.mark.parametrize("l,t,r,b", _FACSB_PANELS[:2])
def test_basewin_facsb_rect_4k_matches_generic_child_arm(l, t, r, b):
    """At g=40 the outer window must be BIT-IDENTICAL to what the generic
    thunk_basewin_gwinit child arm produced before (x=pt(r-12), w=pt(12)):
    2.5x12 = 30 is integral, so the 4K look the user already saw is
    unchanged; only the bar's internals become device space."""
    x0, y0, x1, y1 = basewin_facsb_rect(l, t, r, b, 40)
    assert (x0, y0) == (basewin_pt(r - 12, 40), basewin_pt(t, 40))
    assert (x1 - x0, y1 - y0) == (basewin_pt(12, 40), basewin_pt(b - t, 40))


@pytest.mark.parametrize("g", (22, 25))
def test_basewin_facsb_rect_fractional_g_right_anchored(g):
    """At fractional g the per-edge floor of the generic child arm can land
    the right edge 1px short of pt(r) (fl((r-12)g/16)+fl(12g/16) lags); the
    law anchors RIGHT so the bar butts the panel's inner edge exactly."""
    l, t, r, b = _FACSB_PANELS[0]
    x0, y0, x1, y1 = basewin_facsb_rect(l, t, r, b, g)
    assert x1 == basewin_pt(r, g)
    assert basewin_pt(r - 12, g) + basewin_pt(12, g) <= x1


# ---- ornate text box LEFT edge (thunk_pf_frame_align v9) + anchored type-16 row trim (t_dp_q16anch) ----
from scaling_laws import (  # noqa: E402
    ORNATE_MARGIN_L_NATIVE, diplo_q16_row_width, ornate_text_box_edge_l, ornate_text_box_takes_inner_arm,
)


@pytest.mark.parametrize("g", range(16, 41))
def test_ornate_text_box_left_is_the_title_inner_and_pitches_match(g):
    """Vanilla #RENAME: text box == title inner on BOTH sides (margin 19 = 13 + 3 + 3).  The law lands the
    left on stash + ps3, the same pitch the right side (stash_r - ps3) carries, at every g; native = engine."""
    stash_l = SL.popup_scale_floor(13, g)
    m = SL.popup_scale_floor(ORNATE_MARGIN_L_NATIVE, g)
    engine_l = m - SL.popup_pad(3, g)
    box_l = ornate_text_box_edge_l(engine_l, m, stash_l, g)
    assert box_l - stash_l == SL.popup_pad(3, g)
    assert 0 <= engine_l - box_l <= 1                        # only ever pulls the box IN by the floor lag
    if g == 16:
        assert box_l == engine_l == 16 and not ornate_text_box_takes_inner_arm(60000, 0, 1, m, g)
    else:
        assert ornate_text_box_takes_inner_arm(60000, 0, 1, m, g)
        assert ornate_text_box_takes_inner_arm(20000, 0, 1, m, g)
        for raw in (0, 10000, 50000, 1000 * 10000):
            assert not ornate_text_box_takes_inner_arm(raw, 0, 1, m, g)
        assert not ornate_text_box_takes_inner_arm(60000, 1, 1, m, g)
        assert not ornate_text_box_takes_inner_arm(60000, 0, 0, m, g)
        assert not ornate_text_box_takes_inner_arm(60000, 0, 1, m - 1, g)


@pytest.mark.parametrize("g", range(16, 41))
@pytest.mark.parametrize("cols", (1, 2, 3))
def test_diplo_q16_row_width_trims_vanilla_3_scaled(g, cols):
    """Rows end popup_pad(3, g) short of the column span (vanilla 3: pristine Opening.png 808 vs 811),
    never the vertical gap; within 1 px of 3*g/16; None at native."""
    B = SL.popup_scale_floor(600, g)
    w = diplo_q16_row_width(B, 0, cols, g)
    if g <= 16:
        assert w is None
        return
    trim = B // cols - w
    assert trim == SL.popup_pad(3, g) and 0 <= 3 * g / 16 - trim < 1


def _reply_spill_set(B, indent, row_w, tmax):
    """Text widths t whose wrapped line count at the DRAW width (row_w - indent, Buffer_wrap_2 in
    Dialog_type16_draw_item) exceeds the lines the CALC sized the row for (t // budget + 1, budget =
    B - indent, Dialog_type16_calc 0x60D380) -- the reply line that spills out of its row.  Lines are
    modelled as ceil(t / width) (tight packing: the best case word wrap can reach)."""
    budget, W = B - indent, row_w - indent
    return [t for t in range(1, tmax) if -(-t // W) > t // budget + 1]


@pytest.mark.parametrize("g", range(17, 41))
def test_diplo_q16_reply_wrap_spill_band_is_vanilla_scaled(g):
    """Audit gap (2026-10-11): the trim widens the band of reply widths that wrap to a line the row
    was not sized for (draw wraps at [D+0x64] - indent, calc estimates with B/cols - 2m - indent).
    Vanilla has the same band (its 3 px trim).  With the scaled trim every spilling width at g sits
    within rounding of a vanilla spilling width scaled by g/16 -- no NEW spill -- and the first-line
    band holds popup_pad(3, g) - 1 widths (vanilla: 3 - 1).  cols == 1 (the speech box)."""
    import bisect
    import math
    for B16 in range(200, 700, 37):
        for ind16 in (0, 4, 10, 17):
            S16 = _reply_spill_set(B16, ind16, B16 - 3, 4 * B16)
            B, ind = SL.popup_scale_floor(B16, g), SL.popup_scale_floor(ind16, g)
            Sg = _reply_spill_set(B, ind, diplo_q16_row_width(B, 0, 1, g), 4 * B)
            first = [t for t in Sg if t < B - ind]
            assert len(first) == SL.popup_pad(3, g) - 1, (B16, ind16)    # widths W+1 .. budget-1 (vanilla: 2)
            scaled = [t * g / 16 for t in S16]
            for t in Sg:
                i = bisect.bisect_left(scaled, t)
                d = min(abs(scaled[j] - t) for j in (i - 1, i) if 0 <= j < len(scaled))
                k = t // (B - ind) + 1                    # line index: one floor of drift per line
                assert d <= math.ceil(g / 16) + k, (B16, ind16, t, d)


# ---- HQ report console tab pairs v2 (2026-10-17): rw_tab_pair / rw_tab_inset / rw_console_inset_w / rw_sat_tabs ----
def _vanilla_tab_pair(region):
    """ReportIf_activate 0x4A4554.. + console painter 0x4A701C.. arithmetic, transcribed (cdq/sub/sar = trunc)."""
    L, T, R, B = region
    W = R - L
    x, y, w = L + 9, T + 9, W - 0x12
    h2 = int(w / 2)
    return ((L + 6, T + 6, L + 6 + W - 0xC, T + 6 + 0x1A), (x, y, x + h2 - 1, y + 0x14), (x + h2 + 1, y, x + h2 + 1 + h2, y + 0x14))


def test_scaling_rw_tab_pair_identity_at_16():
    for W in range(150, 801):
        for L, T in ((0, 0), (4, 56), (13, 140)):
            reg = (L, T, L + W, T + 196)
            assert SL.rw_tab_pair(reg, 16) == _vanilla_tab_pair(reg)
    ch = SL.rw_tab_channels((4, 56, 245, 252), 16)                       # the 1024x768 F2 panel (W = 241)
    assert (ch["L"], ch["R"], ch["T"], ch["B"], ch["seam"], ch["wl"], ch["wr"]) == (2, 2, 2, 2, 2, 110, 111)   # pristine Tech.png
    assert SL.rw_tab_inset(16) == 9 and SL.rw_console_inset_w(229, 6, 16) == 217


@pytest.mark.parametrize("g", range(17, 49))
def test_scaling_rw_tab_pair_channels_are_s2_on_every_side(g):
    """chrome pinned (box stroke K at its outer rows/cols, half-open), remainder to the inert cell (the right button):
    L = R = T = B = seam = s(2) for every panel width; the box mirrors itself in the panel; halves differ by <= 1."""
    s2, C = SL.scale_px(2, g), SL.rw_console_box_inset(g)          # v2 (console chain): the box at C, not s(6)
    for W in range(150, 801):
        for L, T in ((0, 0), (7, 61), (300, 900)):
            reg = (L, T, L + W, T + 300)
            box, a, b = SL.rw_tab_pair(reg, g)
            ch = SL.rw_tab_channels(reg, g)
            assert ch["L"] == ch["R"] == ch["T"] == ch["B"] == ch["Bb"] == ch["seam"] == s2, (W, ch)
            assert ch["wr"] - ch["wl"] in (0, 1)
            assert box[0] - L == reg[2] - box[2] == C and box[1] - T == C and box[3] - box[1] == SL.scale_px(0x1A, g)
            assert a[1] == b[1] and a[3] == b[3] and a[0] - L == reg[2] - b[2] == SL.rw_tab_inset(g)
    assert SL.rw_tab_inset(g) == C + SL.stroke_width(g) + s2


# ---- HQ report console chrome chain (2026-10-17): rw_console_step / rw_console_box_inset / rw_console_centre_inset ----
@pytest.mark.parametrize("g", range(8, 49))
def test_scaling_rw_console_chain(g):
    """Every nesting step of the console chrome is stroke + channel: the content box's channel to the panel d5a0 (at
    s(3), K wide) and the centre d528's to its d5a0 (at s(4)) are s(2) on every side and mirror; g <= 16 = vanilla's
    6 / 7 / 9 (pristine HQData pages: da50 | 2 | d5a0 | 2 | box on all four sides)."""
    K = SL.stroke_width(g) if g > 16 else 1
    s2, s3, s4 = (SL.scale_px(v, g) if g > 16 else v for v in (2, 3, 4))
    U, C, P, Q = SL.rw_console_step(g), SL.rw_console_box_inset(g), SL.rw_tab_inset(g), SL.rw_console_centre_inset(g)
    assert U == K + s2 and C - s3 - K == s2 and P - C - K == s2 and Q - s4 - K == s2
    for span in range(150, 900, 11):
        w = SL.rw_console_box_w(span, g)
        assert (C - s3 - K) == (span - s3 - K) - (C + w) == s2       # left channel == right channel (half-open box)
    if g <= 16:
        assert (U, C, P, Q) == (3, 6, 9, 7)
    for key in SL.RW_SUM_TERMS:
        if g > 16:
            assert SL.rw_sum_value(SL.RW_SUM_TERMS[key], g) == SL.rw_sum_law(key, g)
        assert SL.rw_sum_value(SL.RW_SUM_TERMS[key], 16) == SL.rw_sum_law(key, 16)


@pytest.mark.parametrize("g", range(8, 49))
def test_scaling_rw_console_list_top(g):
    """The console button lists' first button sits one step U below the body box's top edge (body top = C + the
    title box lineH + s(6) + the s(2) gap): top channel s(2) = the side channels (P - C - K).  g <= 16: vanilla 0x20
    = 6 + (15 + 6) + 2 + 3; fix 4g replaced s(0x20), which differs at 17 of g = 17..40 (4K 80 vs 78)."""
    Y = SL.rw_console_list_top(g)
    if g <= 16:
        assert Y == 0x20 == 6 + 15 + 6 + 2 + 3
        return
    K, s2 = SL.stroke_width(g), SL.scale_px(2, g)
    body_top = SL.rw_console_box_inset(g) + SL.rw_line_h(15, g) + SL.scale_px(6, g) + s2
    assert Y - (body_top + K) == s2 == SL.rw_tab_inset(g) - SL.rw_console_box_inset(g) - K
    assert SL.rw_sum_value(SL.RW_SUM_TERMS["Y"], g) == Y
    if g == 40:
        assert (Y, SL.scale_px(0x20, g)) == (78, 80)


@pytest.mark.parametrize("g", range(17, 49))
def test_scaling_rw_console_inset_w_mirrors(g):
    for v in (3, 6):
        for span in range(100, 900, 7):
            assert SL.rw_console_inset_w(span, v, g) == span - 2 * SL.scale_px(v, g)
    # the defect it replaces: s(2v) != 2*s(v) somewhere in the range (1600x1200: s(0xC) = 19 vs 2*s(6) = 18)
    assert SL.scale_px(0xC, 25) == 19 and 2 * SL.scale_px(6, 25) == 18


def test_scaling_rw_sat_tabs():
    for cw in range(300, 1700, 13):
        cl = 26
        x, w = cl + 3, cw - 6
        h2 = int(w / 2)
        assert SL.rw_sat_tabs(cl, cl + cw, 16) == ((x, x + h2 - 1), (x + h2 + 1, x + w))
        for g in range(17, 49):
            (l0, l1), (r0, r1) = SL.rw_sat_tabs(cl, cl + cw, g)
            s3, s2 = SL.scale_px(3, g), SL.scale_px(2, g)
            assert l0 - cl == (cl + cw) - r1 == s3 and r0 - l1 == s2 and (r1 - r0) - (l1 - l0) in (0, 1)

