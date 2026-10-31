"""The W10S F56 armed non-rail scrollbar laws (scaling_laws.py: sb_nonrail_gate / sb_nonrail_grip_rect / sb_arrow_plate /
sb_nonrail_arrow, on rail_grip_span + mirror_nn_src; v5 = centring only), swept over g 17..64 and the bar classes --
the source of truth the t_nrs_* thunks port (tests/test_nonrail_sb_asm_parity.py) and the real bars draw
(tests/test_scaling_nonrail_sb_e2e.py).  No emulation; < 2 s.

Vanilla (1024x768): a 20-px bar's 18-px plates and grip, a 12-px bar's 10-px glyphs and grip, each at 1 | 1.  The law
keeps, at every g: plate span == grip span, centred (equal channels), both within 1 px of vanilla x g/16 (the bar's
parity forces the odd px: rail_grip_span's nearest same-parity value), the grip square in its square thumb, the down
arrow the mirror of the up arrow, the face a plain NN of the native plate at its new size (the deployed sampling
with the mirror-exact tie-break; user decision 2026-10-27: centring only; g = 32 the art doubled), and g <= 16
untouched."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

KEY = SL.SB_ARROW_KEY
CLASSES = ((20, 18), (12, 10))          # (vanilla bar, plate / grip sprite): the 20-px bars, the 12-px bars


#: vanilla's 20-px up-arrow triangle (F0 / B9) as [first, last) columns per plate row 0..17 -- measured on the pristine
#: Prefs slider's native render (transposed; the lobby's is the same within one column): rows 3..16, 4 | 14 | 2 in the
#: 20-px button, so the centre-NN tie lands on its first row exactly as on the real art (audit w10S v5)
TRI_SPANS = (None, None, None, (9, 10), (8, 11), (8, 9), (7, 12), (7, 10), (6, 13), (6, 13), (4, 14), (5, 14), (3, 15),
             (4, 15), (2, 16), (2, 16), (1, 17), None)


def _plate(f, axis):
    """An 18-px scanline plate shaped like the game's 20-px up arrow: ground C5 / C2 and vanilla's triangle (TRI_SPANS)
    in F0 / B9, alternating along `axis` ('y' rows, 'x' columns), a 29 outline, key corners."""
    assert f == len(TRI_SPANS)
    rows = []
    for y in range(f):
        row = []
        for x in range(f):
            u, v = (x, y) if axis == "y" else (y, x)          # v = the coordinate the stripes alternate along
            span = TRI_SPANS[v]
            if (x, y) in ((0, 0), (f - 1, 0), (0, f - 1), (f - 1, f - 1)):
                row.append(KEY)
            elif x in (0, f - 1) or y in (0, f - 1):
                row.append(0x29)
            elif span and span[0] <= u < span[1]:
                row.append(0xF0 if v % 2 == 0 else 0xB9)
            else:
                row.append(0xC5 if v % 2 == 0 else 0xC2)
        rows.append(row)
    return rows


def _glyph(f, up=True):
    """A 12-px bar's arrow glyph: a solid BF triangle with an E4 base line in an f x f sprite whose last (up) or first
    (down) row is key -- vanilla draws it 1 | 2 / 2 | 1 in the 12-px square."""
    rows = [[KEY] * f for _ in range(f)]
    for y in range(f - 2):
        for x in range(f):
            if abs(x - (f - 1) / 2) < (y + 2) / 2:
                rows[y][x] = 0xBF
    rows[f - 2] = [0xE4] * f                                  # the base line spans the sprite (the game's does)
    return rows if up else rows[::-1]


def _native(plate, wn):
    f = len(plate)
    c0 = (wn - f) // 2
    out = [[KEY] * wn for _ in range(wn)]
    for y in range(f):
        out[c0 + y][c0:c0 + f] = plate[y]
    return out


def _wn(aw, g):
    """The native render's side: the real renders are ceil(aw * 16 / g) -- vanilla's own 20 / 12 at every g (measured:
    audit-w10S v4 captures, g 17..40)."""
    return -(-aw * 16 // g)


def _flip(a, axis):
    return a[::-1] if axis == "y" else [r[::-1] for r in a]


@pytest.mark.parametrize("g", list(range(17, 65)))
def test_scaling_plate_grip_one_span_centred_and_proportionate(g):
    for nv, sv in CLASSES:
        n = (nv * g) >> 4
        off, w = SL.rail_grip_span(n, sv, g)
        assert off * 2 + w == n and off >= 1, (g, nv)
        assert abs(16 * w - sv * g) <= 16, (g, nv, w)                       # within 1 px of vanilla x g/16
        if g <= 40:                                                          # thunk_ensure_scale clamps g to 40
            assert abs(32 * off - (nv - sv) * g) <= 32, (g, nv, off)          # the channel within 1 px too
        # the grip, in its square thumb (the bar's b x b): the same span on both axes
        for t in (0, 3 * g, 7 * g + 5):
            x, y, gw, gh = SL.sb_nonrail_grip_rect((0, t, n, t + n), sv, sv, g)
            assert (x, y - t, gw, gh) == (off, off, w, w), (g, nv, t)
        # the arrows: the plate square on the same span, both axes, both arrows
        plate = _plate(sv, "y") if nv == 20 else _glyph(sv)
        out = SL.sb_nonrail_arrow(_native(plate, _wn(n, g)), _wn(n, g), _wn(n, g), n, n, g)
        assert out is not None, (g, nv)
        cols = [x for x in range(n) if any(out[y][x] != KEY for y in range(n))]
        assert (cols[0], cols[-1] + 1) == (off, off + w), (g, nv, cols)


def _extents(face, axis, keep):
    """(lead, size, trail) of the pixels `keep` selects, along `axis` ('y' rows / 'x' columns), and across it."""
    n = len(face)
    lines = [any(keep(face[i][j] if axis == "y" else face[j][i]) for j in range(n)) for i in range(n)]
    cross = [any(keep(face[j][i] if axis == "y" else face[i][j]) for j in range(n)) for i in range(n)]
    def run(v):
        idx = [i for i, b in enumerate(v) if b]
        return (idx[0], idx[-1] + 1 - idx[0], len(v) - idx[-1] - 1) if idx else None
    return run(lines), run(cross)


@pytest.mark.parametrize("g", list(range(17, 65)))
def test_scaling_down_arrow_is_the_mirror_of_the_up_arrow(g):
    """v5: the down arrow mirrors the up arrow along the bar at every g -- the whole face and the inner triangle (F0 /
    B9): the down arrow's (lead, size, trail) along the bar is the up arrow's (trail, size, lead), across it the same --
    on renders shaped like the real ones (the 20-px plates in their 20-px render, rows striped for the vertical bars and
    columns for the sliders; the 12-px glyph, 9 of its 10 rows drawn, in its 12-px render: vanilla 1 | 2 / 2 | 1).
    mirror_nn_src maps dest k and w - 1 - k to mirror sources and the plate sits centred, so the extents mirror; the
    deployed centre-NN (stretch_nn_src) breaks this at a tie (the 20-px triangles at g 19 / 30 / 35, the 12-px glyphs
    at g 23 / 39 -- audit w10S v4; with vanilla's triangle shape, TRI_SPANS, this test fails on stretch_nn_src at
    g 19 / 23 / 30 / 35 / 39 / 46 / 51 / 55 / 62: the only guard above g 40).  (Pixel for pixel cannot hold: an odd w puts one middle line on one of the two
    middle scanlines.)"""
    tri = lambda v: v in (0xF0, 0xB9)                                                # noqa: E731
    face = lambda v: v != KEY                                                        # noqa: E731
    for nv, sv, plate, axis in ((20, 18, _plate(18, "y"), "y"), (20, 18, _plate(18, "x"), "x"), (12, 10, _glyph(10), "y")):
        n = (nv * g) >> 4
        wn = _wn(n, g)
        assert wn == nv
        up = SL.sb_nonrail_arrow(_native(plate, wn), wn, wn, n, n, g)
        dn = SL.sb_nonrail_arrow(_native(_flip(plate, axis), wn), wn, wn, n, n, g)
        for keep in ((face, tri) if nv == 20 else (face,)):
            (ua, ux), (da, dx) = _extents(up, axis, keep), _extents(dn, axis, keep)
            assert da == ua[::-1] and dx == ux, (g, nv, axis, ua, da)


@pytest.mark.parametrize("g", list(range(17, 65)))
def test_scaling_face_is_a_plain_nn_of_the_plate(g):
    """v5 (centring only): the face is a plain NN of the native plate square, F -> w on both axes, on the plate's law
    square (mirror_nn_src), key everywhere else; it is the deployed keyed stretch's sampling (stretch_nn_src, GDI
    centre-NN) except at an exact tie, where it takes the mirror sample -- for the 20-px plates (both orientations)
    and the 12-px glyphs alike."""
    for nv, sv, plate in ((20, 18, _plate(18, "y")), (20, 18, _plate(18, "x")), (12, 10, _glyph(10))):
        n = (nv * g) >> 4
        wn = _wn(n, g)
        nat = _native(plate, wn)
        out = SL.sb_nonrail_arrow(nat, wn, wn, n, n, g)
        off, w = SL.rail_grip_span(n, sv, g)
        c0 = (wn - sv) // 2
        m = [c0 + SL.mirror_nn_src(k - off, sv, w) if off <= k < off + w else None for k in range(n)]
        assert out == [[KEY if m[y] is None or m[x] is None else nat[m[y]][m[x]] for x in range(n)]
                       for y in range(n)], (g, nv)
        for k in range(w):
            mm, st = SL.mirror_nn_src(k, sv, w), SL.stretch_nn_src(k, sv, w)
            if mm != st:                                  # only at a tie: the mirror column's centre sample is exact
                assert ((2 * (w - 1 - k) + 1) * sv) % (2 * w) == 0, (g, nv, k)


@pytest.mark.parametrize("axis", ["y", "x"])
def test_scaling_g32_is_the_art_doubled(axis):
    """g = 32: the plate is exactly 2x, so the face is the native art doubled, pixel for pixel."""
    n = (20 * 32) >> 4
    nat = _native(_plate(18, axis), 20)
    out = SL.sb_nonrail_arrow(nat, 20, 20, n, n, 32)
    assert out == [[nat[y // 2][x // 2] for x in range(n)] for y in range(n)]


def test_scaling_native_is_untouched():
    for g in (8, 12, 16):
        assert not SL.sb_nonrail_gate(g, True, False)
        for nv, sv in CLASSES:
            assert SL.rail_grip_span(nv, sv, g) == ((nv - sv) // 2, sv) == (1, sv)
            assert SL.sb_nonrail_grip_rect((0, 20, nv, 20 + nv), sv, sv, g) == (1, 21, sv, sv)    # vanilla's 1 | 1
            plate = _plate(sv, "y") if nv == 20 else _glyph(sv)
            assert SL.sb_nonrail_arrow(_native(plate, nv), nv, nv, nv, nv, g) is None
    assert SL.sb_nonrail_gate(17, True, False) and not SL.sb_nonrail_gate(17, True, True)
    assert not SL.sb_nonrail_gate(17, False, False)
