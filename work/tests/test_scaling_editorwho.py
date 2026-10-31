"""Type-16 option-row width law (q16 v6: content-anchored, no count term) + the
0x54/0x41 list-family hatch pass.  Trace vectors are the LIVE values from
frida_scenedit_popupdiag.log (4K g=40 + 1024x768 g=16 runs, 2026-08-14); pixel vectors
are measured on the named screenshots / pristine references."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from scaling_laws import (q16_fill_width, s54_hatch_keyed, s54_row_color,
                          stripe_period, stripe_top)

G_SWEEP = list(range(16, 41)) + [45, 50, 60, 64]


# ---- q16 v6: W = box_w - right margin - x ---------------------------------

def test_q16_native_is_vanillas_own_arithmetic():
    # g=16: the gate returns w, and the law's expression equals it anyway (trace, 1024x768):
    # quit box 755, margins 33 / 67, x 33, w 655; picker box 637, margins 19 / 21, x 19, w 597.
    assert q16_fill_width(16, 655, 33, 755, 67, 2) == 655 == 755 - 67 - 33
    assert q16_fill_width(16, 597, 19, 637, 21, 7) == 597 == 637 - 21 - 19


def test_q16_quit_4k_meets_the_ok_bar():
    # Quit / council / update popups @4K (trace): box 1886, margins 82 / 167, x 82, and the
    # attach's w = 653 (contaminated by the device row gap 5; the first calc pass gave 655).
    # The OK..CANCEL pair spans 82..1719 = 1637 = (655*40)>>4 (shot 20260928-235853: bars
    # 1099..2735 with the popup at 1017); v5 drew the rows 1632 wide, 5 px short.
    W = q16_fill_width(40, 653, 82, 1886, 167, 2)
    assert W == 1637 == (655 * 40) >> 4
    assert 82 + W == 1886 - 167                   # right edge == the OK bar's anchor
    assert (653 * 40) >> 4 == 1632                # the v5 width, for the record


def test_q16_width_does_not_depend_on_the_contaminated_w():
    # the attach's w differs by the device gap (655 -> 654 @g30, 653 @g40); the row span must not
    for w in (650, 653, 654, 655):
        assert q16_fill_width(40, w, 82, 1886, 167, 2) == 1637


def test_q16_picker_4k_ends_on_the_content_edge():
    # SELECT A FACTION @4K (trace, pds 6): box 1591, margins 47 / 52, x 51, w 595.
    # v4/v5 took the box arm 1591 - 2*51 = 1489 (1 px past the content edge), v3 the field
    # mirror 1502 (over the right frame line + rail).
    W = q16_fill_width(40, 595, 51, 1591, 52, 7)
    assert W == 1488
    assert 51 + W == 1591 - 52


def test_q16_text_popup_meets_the_ok_bar():
    # "Operations Director" tech-trade prompt (text, no art).  MEASURED: the OK bar spans 1026
    # game px at 1600x1200 (shot 20260926-143546, rows 285..1314 vs OK 285..1310: the v5 field
    # mirror overshot by 4) and 1642 at 4K (shot 20260926-143402, rows 1096..2743 vs OK
    # 1096..2737: +6).  CONSTRUCTED: this popup's box / x / right margin were never traced; the
    # in-game margins 33 / 67 native are assumed, so the vector only pins "rows span == bar span
    # when x is the left margin".  OUTCOME on the v6 build (pixels): rows == OK bar at 4K (shot
    # 20260929-010222, both 1096..2737) and at 1600x1200 (shot 20260929-010656, both 285.6..1310.6).
    for g, bar_w in ((25, 1026), (40, 1642)):
        x, mrg_r = (33 * g) >> 4, (67 * g) >> 4
        assert q16_fill_width(g, 600, x, x + bar_w + mrg_r, mrg_r, 2) == bar_w


def test_q16_host_join_no_longer_assumes_symmetric_margins():
    # HOST OR JOIN SESSION @4K.  The v2..v5 box arm was box_w - 2x, which assumes the right margin
    # equals the left; the main-menu family's margins are 25 / 30 (Difficulty popup,
    # frida_council_width.log mrgR30f4=30).  ARITHMETIC EXAMPLE on the 2026-07-03 trace values
    # (x 25, w 477, box 1255; the right margin is that sibling's, not this popup's own): 1205 ->
    # 1200.  OUTCOME on the v6 build (pixels, shot 20260929-011010): rows 1321..2512 = 1192 =
    # (477*40)>>4, OK..CANCEL 1322..2512 -- flush; today's box is no longer the July 1255.
    assert q16_fill_width(40, 477, 25, 1255, 30, 3) == 1200
    assert (477 * 40) >> 4 == 1192


def test_q16_pad_and_offset_x_still_end_on_the_bar_anchor():
    # x need not be the left margin (the picker's is 4 px inside it at 4K; a pad_x [popup+0x30E0]
    # or an art column would move it further): the right edge is box_w - right margin regardless
    for x in (82, 86, 120, 600):
        assert x + q16_fill_width(40, 300, x, 1886, 167, 2) == 1886 - 167


def test_q16_count_gate_and_only_widen():
    # ONE row widens exactly like seven; only an empty list (never reaches the site) is native
    assert q16_fill_width(40, 653, 82, 1886, 167, 1) == 1637
    assert q16_fill_width(40, 653, 82, 1886, 167, 0) == 653
    # ONLY-WIDEN: a content span not wider than the measured w keeps w
    assert q16_fill_width(40, 2000, 82, 1886, 167, 7) == 2000
    assert q16_fill_width(40, 1637, 82, 1886, 167, 7) == 1637
    assert q16_fill_width(17, 100, 49, 120, 60, 7) == 100


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("count", [1, 2, 3, 7, 16])
@pytest.mark.parametrize("margins", [(33, 67), (19, 21), (10, 12), (0, 0)])
def test_q16_rows_end_where_the_ok_bar_ends(g, count, margins):
    """The popup machinery builds box = mrgL + content + mrgR with content = fl(w_native*g/16)
    (thunk_scale_boxw from the FIRST calc pass) and anchors the OK bar at box - mrgR.  For every g
    the row window (x == mrgL) must span exactly that content, whatever w the attach measured."""
    nl, nr = margins
    w_native = 655
    ml, mr = (nl * g) >> 4, (nr * g) >> 4
    content = (w_native * g) >> 4
    box = ml + content + mr
    for w_attach in (w_native, w_native - 1, w_native - 2):
        got = q16_fill_width(g, w_attach, ml, box, mr, count)
        if g <= 16:
            assert got == w_attach
        else:
            assert got == content
            assert ml + got == box - mr


# ---- s54 hatch pass ---------------------------------------------------------

def test_s54_keyed_by_hatch_only():
    w = 1585
    # 8 scanned rows of 1px alternation: ~4 rows each member.
    assert s54_hatch_keyed(4 * w, 4 * w, w)
    # solid 0x54 (art/fill): no 0x41 mate -> never fires.
    assert not s54_hatch_keyed(8 * w, 0, w)
    # solid black (title pre-fill): no 0x54 mate -> never fires.
    assert not s54_hatch_keyed(0, 8 * w, w)


@pytest.mark.parametrize("g", [22, 25, 32, 40])
def test_s54_row_color_grid(g):
    P = stripe_period(g)
    hN = (P + 1) >> 1
    for y in range(3 * P):
        expect = 0x54 if (y % P) < hN else 0x41
        assert s54_row_color(y, g) == expect
        assert stripe_top(y, g) == ((y % P) < hN)


def test_s54_native_pattern_is_vanilla():
    # At native the pass never runs (g<=16 guard); vanilla's own 1px
    # alternation IS P=2/hN=1 — the law degenerates to the vanilla look.
    assert stripe_period(16) == 2
    assert s54_row_color(0, 16) == 0x54 and s54_row_color(1, 16) == 0x41


# ==== t16_row_window_anchored (2026-09-26): the skip keys on the popup's +0xA14, not the talk key ====

def test_t16_row_window_anchored_is_the_engine_ext_test():
    from scaling_laws import t16_row_window_anchored
    assert t16_row_window_anchored(0) is False          # ordinary popup (also mid-talk: #ASKSEEDESIGN)
    assert t16_row_window_anchored(0x733990) is True    # the diplomacy speech box
    assert t16_row_window_anchored(0x12345678) is True  # any external window, as the engine branch


@pytest.mark.parametrize("g", range(16, 41))
def test_t16_ordinary_popup_mid_talk_takes_the_fill_law(g):
    """An ordinary type-16 popup raised while the talk screen is open must widen exactly as it does
    outside a talk: the ASKSEEDESIGN vector (d5c 655 native, in-game margins 33 / 67 native)."""
    from scaling_laws import t16_row_window_anchored
    if t16_row_window_anchored(0):
        pytest.fail("ordinary popup must not be treated as anchored")
    ml, mr, content = (33 * g) >> 4, (67 * g) >> 4, (655 * g) >> 4
    W = q16_fill_width(g, 655, ml, ml + content + mr, mr, 2)
    assert W == (655 if g <= 16 else content)
