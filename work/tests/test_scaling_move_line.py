"""Sweep: the map unit-move / Go-To path line and its "Move to" label (group map_move_line_scale).

Laws (scripts/scaling_laws.py): move_line_offsets, move_line_calls, move_label_shadow, and the label font
through font_face_law(12, 1, g).  Pure call-list arithmetic -- the PIXEL consequences (exact thickness K,
notch-free joints, the plug's bounded cap) are measured on the real engine primitives under Unicorn in
tests/test_move_line_asm_parity.py, not modelled here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scaling_laws import (  # noqa: E402
    G_MAX,
    G_MIN,
    MOVE_LABEL_FONT,
    MOVE_LABEL_SHADOW,
    NATIVE_G,
    font_face_law,
    font_face_law_font,
    font_law_slot_index,
    move_label_shadow,
    move_line_calls,
    move_line_offsets,
    scale_px,
    stroke_width,
)

ALL_G = range(G_MIN, G_MAX + 1)
# hop vectors of every slope class: axis-aligned, 45 degrees, shallow/steep, the iso tile diagonals, both signs
VECTORS = [(0, 0), (9, 0), (-9, 0), (0, 9), (0, -9), (7, 7), (-7, 7), (7, -7), (-7, -7),
           (28, 14), (-28, 14), (28, -14), (-28, -14), (56, 0), (0, 28), (3, 11), (-11, 3), (1, 2), (2, 1)]


@pytest.mark.parametrize("dx,dy", VECTORS)
def test_native_g_is_the_one_vanilla_call(dx, dy):
    """g == 16 (1024x768): the thunk must reproduce vanilla's single Buffer_line_2 call exactly."""
    x1, y1 = 100, 60
    assert move_line_calls(x1, y1, x1 + dx, y1 + dy, NATIVE_G) == [("line", x1, y1, x1 + dx, y1 + dy)]


@pytest.mark.parametrize("g", ALL_G)
def test_offsets_are_k_consecutive_and_contain_the_vanilla_line(g):
    """K = stroke_width(g) from the LEVER; offsets consecutive (no gap inside the stroke) and include 0 (the
    vanilla pixels stay drawn).  Even K puts the extra pixel on the + side."""
    k = stroke_width(g)
    offs = move_line_offsets(g)
    assert len(offs) == k
    assert offs == list(range(offs[0], offs[0] + k))
    assert 0 in offs
    assert offs[0] == -((k - 1) >> 1)
    assert offs[-1] - 0 >= 0 - offs[0]


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("dx,dy", VECTORS)
def test_calls_structure(g, dx, dy):
    x1, y1 = 200, 150
    x2, y2 = x1 + dx, y1 + dy
    calls = move_line_calls(x1, y1, x2, y2, g)
    k = stroke_width(g)
    if k <= 1 or (dx == 0 and dy == 0):
        # g <= 24 rounds 1px x g/16 to 1px; a zero-length line draws nothing in vanilla -> nothing to thicken
        assert calls == [("line", x1, y1, x2, y2)]
        return
    offs = move_line_offsets(g)
    lines = [c for c in calls if c[0] == "line"]
    plugs = [c for c in calls if c[0] == "hline"]
    assert calls == lines + plugs                       # the port's order: every copy, then the plugs
    assert len(lines) == k and len(plugs) == 2 * k
    x_major = abs(dx) >= abs(dy)                        # Buffer_line_2's own split (ties iterate x)
    for o, (_, a, b, c, d) in zip(offs, lines):
        assert (c - a, d - b) == (dx, dy)               # every copy is a pure translate of the vanilla line
        assert (a - x1, b - y1) == ((0, o) if x_major else (o, 0))
    for i, (px, py) in enumerate(((x1, y1), (x2, y2))):
        rows = plugs[i * k:(i + 1) * k]
        for r, (_, h0, h1, hy) in zip(offs, rows):
            assert (h0, h1, hy) == (px + offs[0], px + offs[-1], py + r)
            assert h1 > h0                              # never the hline zero-span no-op


def test_line_4k_and_nonfour_k_values():
    """The values the user will see: 1px at 1920x1080 (g=22) and g=24, 2px at 1600x1200 (g=25) and 4K (g=40)."""
    assert [stroke_width(g) for g in (16, 22, 24, 25, 28, 40)] == [1, 1, 1, 2, 2, 2]
    assert move_line_offsets(40) == [0, 1]
    assert move_line_offsets(22) == [0]


@pytest.mark.parametrize("g", ALL_G)
def test_label_shadow_is_vanilla_times_scale(g):
    dx, dy = MOVE_LABEL_SHADOW
    sx, sy = move_label_shadow(dx, dy, g)
    assert (sx, sy) == (scale_px(dx, g), scale_px(dy, g))
    assert sx == sy == stroke_width(g)                  # a 1px offset IS a stroke
    if g <= NATIVE_G:
        assert (sx, sy) == (dx, dy)


def test_label_shadow_identity_below_native():
    assert move_label_shadow(1, 1, NATIVE_G) == (1, 1)
    assert move_label_shadow(2, -1, NATIVE_G) == (2, -1)


@pytest.mark.parametrize("g", ALL_G)
def test_label_font_keeps_arial_bold(g):
    """find_font(12, 1) = Arial 12 BOLD natively; scaled it must stay Arial bold (never the pool's Arial
    Narrow above 12 px) at fl(12g/16), with a cave slot for the (12, 1) key."""
    size, variant = MOVE_LABEL_FONT
    law = font_face_law(size, variant, g)
    if g <= NATIVE_G:
        assert law == ("pool", 12, 1)
        return
    assert law == ("init", "Arial", (12 * g) // 16, 1)
    assert font_face_law_font(size, variant, g) == ("Arial", (12 * g) // 16, 1)
    assert font_law_slot_index(size, variant) is not None
