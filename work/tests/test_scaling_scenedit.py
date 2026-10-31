"""Scenario-editor arc laws (2026-08-11): editor_panel_seeds + diplo_editor_layout.

Evidence base (see memory project-smac-scenario-editor):
  - live traces at g=40 AND g=25 (frida_editorpanel_pin.log / frida_scenedit_census.log);
  - DiploEditWin_exec 0x4DB080 + MainWin_build tail disassembly, immediates
    byte-verified against the pristine .bak.

The g=16 identities below are the engine's own vanilla arithmetic re-derived,
so they are proofs of the native no-op, not coincidences.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scaling_laws import (  # noqa: E402
    DIPLO_CHK_NATIVE_PITCH,
    DIPLO_CHK_ROWS,
    EDITOR_BTN_HI,
    EDITOR_BTN_LO,
    EDITOR_FACE_PAIRS,
    diplo_editor_layout,
    editor_face_chain_credits,
    editor_face_enable,
    editor_face_maxrun,
    editor_face_remap_pixel,
    editor_face_threshold,
    editor_panel_seeds,
    pair_remap_pixel,
    scale_px,
    stripe_period,
    stripe_top,
)

G_RANGE = list(range(16, 41))


# ---------------------------------------------------------------- panel seeds

def test_scaling_scenedit_panel_g16_identity():
    """At g=16 the seeds ARE the vanilla engine values (derived from the
    live-confirmed formulas: x0=rcCC.left+7=269, y0=72; red 497/82)."""
    s = editor_panel_seeds(16)
    assert s["pal"][0] == (269, 72, 312, 90)
    assert s["pal"][4] == (269, 148, 312, 166)      # col 0, row 4
    assert s["pal"][24] == (445, 148, 488, 166)     # col 4, row 4
    # column-major pitch 44 / 19, uniform at native
    assert [r[0] for r in s["pal"][::5]] == [269 + 44 * c for c in range(5)]
    assert [r[1] for r in s["pal"][:5]] == [72 + 19 * r for r in range(5)]
    assert s["red"][0] == (497, 82, 521, 106)
    assert s["red"][5] == (522, 132, 546, 156)
    assert s["pal_union"] == (266, 69, 491, 169)
    assert s["red_union"] == (494, 79, 549, 159)
    assert s["info_left"] == 552
    assert s["info_pad"] == 4
    assert s["info_step"] == 13     # the live Buffer_text_line_height at g=16


def test_scaling_scenedit_panel_sweep_invariants():
    for g in G_RANGE:
        s = editor_panel_seeds(g)
        cw, ch = s["cell"]
        rs = s["red_cell"]
        assert len(s["pal"]) == 25 and len(s["red"]) == 6
        # cells PINNED uniform (content), gaps absorb the remainder
        assert all(r[2] - r[0] == cw and r[3] - r[1] == ch for r in s["pal"])
        assert all(r[2] - r[0] == rs and r[3] - r[1] == rs for r in s["red"])
        colx = [s["pal"][c * 5][0] for c in range(5)]
        rowy = [s["pal"][r][1] for r in range(5)]
        # no overlap anywhere in the grid
        assert all(colx[i + 1] - colx[i] >= cw for i in range(4)), f"g={g}"
        assert all(rowy[i + 1] - rowy[i] >= ch for i in range(4)), f"g={g}"
        rcolx = [s["red"][0][0], s["red"][3][0]]
        rrowy = [s["red"][i][1] for i in range(3)]
        assert rcolx[1] - rcolx[0] >= rs
        assert all(rrowy[i + 1] - rrowy[i] >= rs for i in range(2))
        # faithfulness: every position within 1px of the ideal line
        for i, x in enumerate(colx):
            assert abs(x - (269 + 44 * i) * g / 16) <= 1.0, f"g={g} col{i}"
        for i, y in enumerate(rowy):
            assert abs(y - (72 + 19 * i) * g / 16) <= 1.0, f"g={g} row{i}"
        # chrome follows content: unions hug the cells at +-p3 exactly
        p3 = scale_px(3, g)
        assert s["pal_union"] == (s["pal"][0][0] - p3, s["pal"][0][1] - p3,
                                  s["pal"][24][2] + p3, s["pal"][24][3] + p3)
        assert s["red_union"] == (s["red"][0][0] - p3, s["red"][0][1] - p3,
                                  s["red"][5][2] + p3, s["red"][5][3] + p3)
        # left-to-right ordering: palette | red | info text
        assert s["red"][0][0] > s["pal_union"][2], f"g={g}"
        assert s["info_left"] > s["red_union"][2], f"g={g}"
        # stays inside the scaled console center panel (left edge; the bottom
        # row may brush bottom-7 by 1px exactly as vanilla does)
        assert s["pal_union"][0] >= scale_px(262, g), f"g={g}"
        assert s["pal"][4][3] <= scale_px(166, g) + 1, f"g={g}"
        # info text: 6 lines at the substituted step stay snug like vanilla
        # (native: 4 + 5*13 + 11 == 80 == box height, EXACT).  Away from g=16
        # the four independent roundings (pad, step, glyph, box) scatter the
        # fit by at most +-4px (measured envelope over the full sweep) — the
        # v1 sublinear-metric bug was a 12px orphan margin at g=40.
        box_h = s["info_bottom"] - s["info_top"]
        blk = s["info_pad"] + 5 * s["info_step"] + scale_px(11, g)
        assert abs(blk - box_h) <= 4, f"g={g}: {blk} vs box {box_h}"
        assert abs(s["info_step"] - 13 * g / 16) <= 1.0, f"g={g}"


# ---------------------------------------------------------------- diplo modal

def test_scaling_scenedit_diplo_g16_identity():
    """Vanilla trace values, byte-verified in the pristine exe."""
    d = diplo_editor_layout(16)
    assert (d["W"], d["H"]) == (758, 398)
    assert d["title_band"] == (4, 4, 754, 24)
    assert d["list_rect"] == (4, 31, 248, 370)
    assert d["list_content"] == (7, 34, 245, 367)   # the traced child window
    assert d["chk_rect"] == (383, 31, 754, 370)
    assert d["btn_xs"] == [4, 192, 380, 568]
    assert (d["btn_w"], d["btn_y0"], d["btn_y1"]) == (186, 374, 394)
    assert (d["font_dlg"], d["font_title"]) == (14, 16)


def test_scaling_scenedit_diplo_sweep_invariants():
    prev_w = prev_h = 0
    for g in G_RANGE:
        d = diplo_editor_layout(g)
        W, H = d["W"], d["H"]
        assert W >= prev_w and H >= prev_h
        prev_w, prev_h = W, H
        # panels ordered and inside the window
        assert d["title_band"][3] <= d["list_rect"][1], f"g={g}"
        assert d["list_rect"][2] < d["chk_rect"][0], f"g={g}"
        assert d["chk_rect"][2] <= W, f"g={g}"
        assert d["list_rect"][3] <= d["btn_y0"], f"g={g}"
        # button row: 4 buttons pull IN by at most the /4 remainder (3px),
        # never overrun the right inset
        right = W - d["pad4"]
        last = d["btn_xs"][3] + d["btn_w"]
        assert 0 <= right - last <= 3, f"g={g}: shortfall {right - last}"
        assert d["btn_y1"] <= H, f"g={g}"
        # all 13 CheckList rows fit the scaled container (native pitch 22
        # measured: 6 rows in 339px at g=40)
        container_h = d["chk_rect"][3] - d["chk_rect"][1]
        rows_h = DIPLO_CHK_ROWS * scale_px(DIPLO_CHK_NATIVE_PITCH, g)
        assert rows_h <= container_h, f"g={g}: {rows_h} > {container_h}"
        # faithfulness of the main dims
        assert abs(W - 758 * g / 16) <= 1.0
        assert abs(H - 398 * g / 16) <= 1.0
        assert abs(d["btn_w"] - 186 * g / 16) <= 3.0, f"g={g}"


# ------------------------------------------------- icon-face pairs (FIX 2e)

FACE_G = [17, 22, 25, 32, 40]        # never 16: callers gate g > 16


def _stripe_cols(top, bot, w, h, g, region_top=0, region_h=None):
    """Synthetic NN-banded face: a TRUE NN enlarge (x g/16) of a native
    1px-alternating `top`/`bot` field, inside a key-9 face — exactly the
    artifact the detector sees pre-remap (run lengths fl/ceil(g/16))."""
    if region_h is None:
        region_h = h - region_top
    cols = []
    for _x in range(w):
        col = []
        for y in range(h):
            if region_top <= y < region_top + region_h:
                src = ((y - region_top) * 16) // g       # NN dest->src row
                col.append(top if src % 2 == 0 else bot)
            else:
                col.append(9)
        cols.append(col)
    return cols


def test_scaling_scenedit_face_detector_enables_stripes():
    """Every measured family enables on a banded field covering only ~40%
    of the face height (the weakest real face in the verified log; floor of
    12 device rows — below that a chain can't reach 6 runs at g~17, where
    the NN error is a single px every 16 rows and invisible anyway)."""
    for g in FACE_G:
        w, h = scale_px(43, g), scale_px(18, g)
        for top, bot in EDITOR_FACE_PAIRS.items():
            cols = _stripe_cols(top, bot, w, h,
                                g, region_top=2,
                                region_h=min(h - 2, max(12, (h * 2) // 5)))
            credits = editor_face_chain_credits(cols, g)
            key = (min(top, bot), max(top, bot))
            assert credits.get(key, 0) >= editor_face_threshold(w), \
                f"g={g} pair {top:02x}/{bot:02x}: {credits}"


def test_scaling_scenedit_face_detector_rejects_solid_art():
    """Two solid regions of the SAME pair (long runs at the boundary) never
    credit — the run-length gate is what excludes art, per the proto."""
    for g in FACE_G:
        w, h = scale_px(43, g), scale_px(18, g)
        for top, bot in EDITOR_FACE_PAIRS.items():
            cols = [[top] * (h // 2) + [bot] * (h - h // 2) for _ in range(w)]
            credits = editor_face_chain_credits(cols, g)
            flags = editor_face_enable(credits, w)
            assert not any(flags.values()), f"g={g} {top:02x}: {flags}"
        # thin 2px alternations that never chain 6 runs also stay off
        maxrun = editor_face_maxrun(g)
        assert maxrun == stripe_period(g) + 1


def test_scaling_scenedit_face_red_arbitration():
    """0x6D belongs to exactly one red family per blit; c9 wins ties."""
    for g in FACE_G:
        w, h = scale_px(24, g), scale_px(24, g)
        c9_cols = _stripe_cols(0xC9, 0x6D, w, h, g)
        m68_cols = _stripe_cols(0x6D, 0x68, w, h, g)
        f_c9 = editor_face_enable(editor_face_chain_credits(c9_cols, g), w)
        f_68 = editor_face_enable(editor_face_chain_credits(m68_cols, g), w)
        assert f_c9["c9"] and not f_c9["m68"], f"g={g}: {f_c9}"
        assert f_68["m68"] and not f_68["c9"], f"g={g}: {f_68}"
        # never both, whatever the credits say
        for credits in ({(0x6D, 0xC9): 10 * w, (0x68, 0x6D): 10 * w},
                        {(0x6D, 0xC9): 10 * w}, {(0x68, 0x6D): 10 * w}):
            fl = editor_face_enable(credits, w)
            assert not (fl["c9"] and fl["m68"])


def test_scaling_scenedit_face_remap_pixel_laws():
    """Pixel law: fixed canonical tops, phase = the ONE stripe grid; E1
    strays fold into the e0/e2 family; disabled families pass through."""
    for g in FACE_G:
        for y in range(3 * stripe_period(g)):
            top = stripe_top(y, g)
            assert editor_face_remap_pixel(0xF0, y, g, f0=True) == \
                (0xF0 if top else 0xB9)
            assert editor_face_remap_pixel(0xE1, y, g, e2=True) == \
                (0xE0 if top else 0xE2)
            assert editor_face_remap_pixel(0x6D, y, g, c9=True) == \
                (0xC9 if top else 0x6D)
            assert editor_face_remap_pixel(0x6D, y, g, m68=True) == \
                (0x6D if top else 0x68)
            # disabled -> untouched (incl. the shared 0x6D)
            for idx in (0xF0, 0xB9, 0xA2, 0xEF, 0xE0, 0xE2, 0xC9, 0x6D, 0x68):
                assert editor_face_remap_pixel(idx, y, g) == idx
            # non-members never touched even when all families are on
            for idx in (0x09, 0x41, 0xC4, 0xAE, 0xEE, 0x00, 0xFF):
                assert editor_face_remap_pixel(
                    idx, y, g, f0=True, a2=True, e2=True, c9=True) == idx


def test_scaling_scenedit_face_pass_composition_stable():
    """btn_stripes v5 order: thunk_ed_remap FIRST, thunk_fe_pair_remap after
    (unconditional families only on the button path).  For every enabled
    editor family the composition is a fixed point — the main remap never
    undoes an editor rewrite (both share the one phase grid)."""
    flag_sets = [{"f0": True}, {"a2": True}, {"e2": True},
                 {"c9": True}, {"m68": True}]
    for g in FACE_G:
        for y in range(4 * stripe_period(g)):
            for flags in flag_sets:
                for idx in range(256):
                    ed = editor_face_remap_pixel(idx, y, g, **flags)
                    if ed != idx:                      # an editor rewrite...
                        assert pair_remap_pixel(ed, y, g) == ed, \
                            f"g={g} y={y} idx={idx:02x} flags={flags}"


def test_scaling_scenedit_face_range_constants():
    assert EDITOR_BTN_HI - EDITOR_BTN_LO == 31 * 0xB4C   # measured census
    # the canonical tops are the measured ones — never re-vote
    assert EDITOR_FACE_PAIRS == {0xF0: 0xB9, 0xA2: 0xEF, 0xE0: 0xE2,
                                 0xC9: 0x6D, 0x6D: 0x68}
