"""Law sweep for the citizen-face HYBRID enlarge (scaling_laws.face_pair_mate / face_hybrid_enlarge): the photo goes
through thunk_sprite_bilinear's law, the face's baked period-2 scanline background is REGENERATED at device density
on the dest buffer's row phase.  g = 16..45, both citizen cell sizes (large 38x48, small 30x38), synthetic sprites.
The asm port is checked byte for byte in test_face_hybrid_parity.py.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

GS = list(range(16, 46))
CELLS = [(38, 48), (30, 38)]
KEY = 9
A, B = 0x60, 0x20            # stripe pair: A brighter
S1, S2, PHOTO = 0x90, 0x91, 0x40


def _pal():
    """RGBQUAD[256] (b,g,r,x): index i = grey i, so luma orders by index; index 9 (the key) exists like any other."""
    return bytes(v for i in range(256) for v in (i, i, i, 0))


def _draw(src, w, h, g, x=3, y=5, d_w=None, d_h=None, num=None, den=16, off=(0, 0), fill=0xCC):
    num = g if num is None else num
    W = d_w if d_w is not None else x + (w * num) // den + 4
    H = d_h if d_h is not None else y + (h * num) // den + 4
    dst = bytearray([fill]) * (W * H)
    r = SL.face_hybrid_enlarge(src, w, w, h, off[0], off[1], _pal(), num, den, g, dst, W, W, H, x, y, KEY)
    return r, dst, W, H


def _stripes(w, h, phase=0):
    return [A if ((yy + phase) & 1) == 0 else B for yy in range(h) for _ in range(w)]


@pytest.mark.parametrize("w,h", CELLS)
def test_identity_at_native_and_on_the_bilinear_guards(w, h):
    src = _stripes(w, h)
    for g in (8, 15, 16):
        r, dst, _W, _H = _draw(src, w, h, g, num=25)
        assert r is None and set(dst) == {0xCC}                       # the engine draws: nothing of ours
    for num, den in ((16, 16), (12, 16), (25, 0), (25, -1)):
        r, dst, _W, _H = _draw(src, w, h, 25, num=num, den=den, d_w=200, d_h=200)
        assert r is None and set(dst) == {0xCC}
    assert SL.basewin_pop_face_enlarge(16) == "engine" and SL.basewin_pop_face_enlarge(17) == "hybrid"


@pytest.mark.parametrize("w,h", CELLS)
@pytest.mark.parametrize("phase", [0, 1])
def test_pure_stripes_follow_stripe_top_on_the_dest_rows(w, h, phase):
    """Every dest row of a pure striped sprite is one solid row: the BRIGHTER member iff stripe_top(dest y, g) --
    whatever the sprite's own stripe phase and wherever it is drawn (the dest buffer's phase grid)."""
    src = _stripes(w, h, phase)
    for g in GS[1:]:
        for y0 in (0, 1, 5):
            r, dst, W, H = _draw(src, w, h, g, x=2, y=y0)
            dw, dh = (w * g) // 16, (h * g) // 16
            assert r == (dw, dh)
            for yy in range(H):
                row = dst[yy * W:(yy + 1) * W]
                if y0 <= yy < y0 + dh:
                    want = A if SL.stripe_top(yy, g) else B
                    assert set(row[2:2 + dw]) == {want}, (g, y0, yy)
                    assert set(row[:2]) | set(row[2 + dw:]) == {0xCC}
                else:
                    assert set(row) == {0xCC}
            P = SL.stripe_period(g)
            assert P == 2 * SL.stripe_rows(g) and SL.hof_pair_top(A, B, _pal()) == A == SL.hof_pair_top(B, A, _pal())


@pytest.mark.parametrize("w,h", CELLS)
def test_membership_needs_the_vertical_chain_and_the_horizontal_run(w, h):
    src = [PHOTO] * (w * h)

    def put(x, y, v):
        src[y * w + x] = v

    for yy in range(8, 20):                       # a 1-wide and a 2-wide a/b/a/b coincidence: NOT background
        put(5, yy, S1 if yy & 1 else S2)
        put(10, yy, S1 if yy & 1 else S2)
        put(11, yy, S1 if yy & 1 else S2)
        for xx in range(15, 18):                  # 3 wide: background
            put(xx, yy, S1 if yy & 1 else S2)
        for xx in range(20, 24):                  # 4 wide but two DIFFERENT pairs side by side (2 + 2): not background
            put(xx, yy, (S1 if yy & 1 else S2) if xx < 22 else (A if yy & 1 else B))
    for xx in range(3, 27):
        put(xx, 30, S1)                           # a lone 1-px stroke
    mate = lambda x, y: SL.face_pair_mate(src, w, w, h, x, y, KEY)   # noqa: E731
    for yy in range(8, 20):
        assert mate(5, yy) is None and mate(10, yy) is None and mate(11, yy) is None
        assert all(mate(xx, yy) is None for xx in range(20, 24))
        for xx in range(15, 18):
            assert mate(xx, yy) == (S2 if yy & 1 else S1)
    assert all(mate(xx, yy) is None for xx in range(w) for yy in (29, 30, 31))
    assert SL.hof_pair_texel(src, w, 5, 12, 0, h, KEY)[1] is not None          # the chain alone WOULD have fired
    assert sum(mate(xx, yy) is not None for yy in range(h) for xx in range(w)) == 3 * 12
    # non-members are EXACTLY the bilinear's pixels
    for g in (17, 22, 25, 40, 45):
        _r, dst, W, _H = _draw(src, w, h, g, x=0, y=0)
        for dyi in range((h * g) // 16):
            ny = SL.bilinear_axis(dyi, g, 16, h)[3]
            for dxi in range((w * g) // 16):
                nx = SL.bilinear_axis(dxi, g, 16, w)[3]
                got = dst[dyi * W + dxi]
                m = mate(nx, ny)
                if m is None:
                    assert got == SL.sprite_bilinear_pixel(src, w, w, h, dxi, dyi, g, 16, _pal(), KEY)
                else:
                    a = src[ny * w + nx]
                    assert got == (max(a, m) if SL.stripe_top(dyi, g) else min(a, m))


# ---- membership v2 (2026-09-20): the head-top pocket --------------------------------------------------------------
def _pocket_sprite(w, h, blob_top, blob=(12, 22)):
    """Border row 0 / row h-1, a/b stripes everywhere else, a photo blob (the head) in columns [blob) from row
    blob_top down: the stripe rows 1..blob_top-1 above it are hemmed in between the border and the blob."""
    src = _stripes(w, h)
    for xx in range(w):
        src[xx] = src[(h - 1) * w + xx] = 0xE0
    for yy in range(blob_top, h - 6):
        for xx in range(*blob):
            src[yy * w + xx] = PHOTO
    return src


@pytest.mark.parametrize("w,h", CELLS)
def test_a_three_row_pocket_above_the_head_is_gap_filled(w, h):
    """v1's defect (user, 1600x1200: a dark smudge above every drone's head): the 3 stripe rows between the top
    border and the head are no >= 4-row alternation, so rules 1+2 leave them out; rule 3 fills them from the
    full-height stripes either side (same index, same mate, gap 10 <= FACE_PAIR_MAX_GAP)."""
    src = _pocket_sprite(w, h, 4)
    for yy in (1, 2, 3):
        a, b = (B, A) if yy & 1 else (A, B)
        for xx in range(12, 22):
            assert SL.face_pair_vrun(src, w, h, xx, yy, b, KEY) is False
            assert SL.face_pair_run_mate(src, w, w, h, xx, yy, KEY) == (a, None)
            assert SL.face_pair_mate(src, w, w, h, xx, yy, KEY) == b
        for xx in (11, 22):
            assert SL.face_pair_run_mate(src, w, w, h, xx, yy, KEY) == (a, b)       # the flanks: rules 1+2
    assert all(SL.face_pair_mate(src, w, w, h, xx, yy, KEY) is None for yy in range(4, h - 6) for xx in range(12, 22))
    assert all(SL.face_pair_mate(src, w, w, h, xx, 0, KEY) is None for xx in range(w))   # the border row
    for g in (22, 25):                                 # the regenerated pocket is one even texture with its flanks
        _r, dst, W, _H = _draw(src, w, h, g, x=0, y=0)
        for dyi in range((h * g) // 16):
            if SL.bilinear_axis(dyi, g, 16, h)[3] in (1, 2, 3):
                assert set(dst[dyi * W:dyi * W + (w * g) // 16]) == {A if SL.stripe_top(dyi, g) else B}


@pytest.mark.parametrize("w,h", CELLS)
def test_a_four_row_pocket_is_direct(w, h):
    src = _pocket_sprite(w, h, 5)
    for yy in (1, 2, 3, 4):
        a, b = (B, A) if yy & 1 else (A, B)
        for xx in range(12, 22):
            assert SL.face_pair_vrun(src, w, h, xx, yy, b, KEY) is True
            assert SL.face_pair_run_mate(src, w, w, h, xx, yy, KEY) == (a, b)
    assert SL.FACE_PAIR_MIN_VRUN == 4 and SL.FACE_PAIR_MIN_RUN == 3 and SL.FACE_PAIR_MAX_GAP == 12


@pytest.mark.parametrize("bar,member", [(12, True), (13, False)])
def test_gap_fill_is_capped(bar, member):
    """A same-index art row crossing the photo (the small superdrone's shoulder line) is flanked by stripe members
    of its own index and mate: up to FACE_PAIR_MAX_GAP texels it is a gap, beyond it is art."""
    w, h = 38, 48
    src = _pocket_sprite(w, h, 8, blob=(10, 10 + bar))
    row = 20
    assert src[row * w + 9] == A
    for xx in range(10, 10 + bar):
        src[row * w + xx] = A
    for xx in range(10, 10 + bar):
        assert SL.face_pair_run_mate(src, w, w, h, xx, row, KEY) == (A, None)
        assert (SL.face_pair_mate(src, w, w, h, xx, row, KEY) == B) is member
    # a bar of ANOTHER index, or one flanked on one side only, never fills
    src2 = list(src)
    for xx in range(10, 14):
        src2[row * w + xx] = S1
    assert all(SL.face_pair_mate(src2, w, w, h, xx, row, KEY) is None for xx in range(10, 14))
    src3 = _pocket_sprite(w, h, 8, blob=(30, w))          # the blob runs to the right edge: no right flank
    for xx in range(30, w):
        src3[row * w + xx] = A
    assert all(SL.face_pair_mate(src3, w, w, h, xx, row, KEY) is None for xx in range(30, w))


@pytest.mark.parametrize("w,h", CELLS)
def test_strokes_and_forehead_coincidences_are_not_members(w, h):
    src = [PHOTO] * (w * h)
    for xx in range(4, 24):
        src[30 * w + xx] = S1                          # a lone stroke in a flat field: run 1
    stripes = _stripes(w, h)
    lone = list(stripes)
    for xx in range(w):
        lone[11 * w + xx] = S1                         # a lone stroke BETWEEN field rows: b/S1/b reaches 3 rows only
    for yy in range(6, 10):
        src[yy * w + 8] = S1 if yy & 1 else S2         # 1-wide 4-row alternation
        src[yy * w + 12] = src[yy * w + 13] = S1 if yy & 1 else S2      # 2-wide
    for yy in range(14, 17):
        for xx in range(6, 14):
            src[yy * w + xx] = S1 if yy & 1 else S2    # 8 wide but only 3 rows (the rejected VRUN = 3 speckle)
    assert all(SL.face_pair_mate(src, w, w, h, xx, yy, KEY) is None for yy in range(h) for xx in range(w))
    assert all(SL.face_pair_mate(lone, w, w, h, xx, 11, KEY) is None for xx in range(w))
    assert all(SL.face_pair_mate(lone, w, w, h, xx, yy, KEY) is not None for xx in range(w) for yy in (5, 6, 7, 8, 14, 15, 16, 17))


def test_a_band_junction_texel_is_direct_for_both_pairs():
    """Where two stripe bands meet (a/b above, a/c below) the shared row is direct for both mates; the run rule
    takes the candidate its row neighbours carry (above first)."""
    w, h = 12, 14
    src = []
    for yy in range(h):
        for xx in range(w):
            v = A if (yy & 1) == 0 else (B if yy < 7 else S1)
            if xx >= 6 and yy == 5:
                v = S1                                  # right half: the lower band starts two rows earlier
            src.append(v)
    assert SL.face_pair_vrun(src, w, h, 2, 6, B, KEY) and SL.face_pair_vrun(src, w, h, 2, 6, S1, KEY)
    assert SL.face_pair_run_mate(src, w, w, h, 2, 6, KEY) == (A, B)
    assert SL.face_pair_run_mate(src, w, w, h, 8, 6, KEY) == (A, S1)
    assert all(SL.face_pair_mate(src, w, w, h, xx, 6, KEY) is not None for xx in range(w))


@pytest.mark.parametrize("w,h", CELLS)
def test_key_texels_are_untouched_never_members_and_break_the_chain(w, h):
    src = _stripes(w, h)
    holes = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (7, 9), (8, 9)]
    for xx, yy in holes:
        src[yy * w + xx] = KEY
    for xx, yy in holes:
        assert SL.face_pair_mate(src, w, w, h, xx, yy, KEY) is None
    for g in GS[1:]:
        _r, dst, W, _H = _draw(src, w, h, g, x=0, y=0)
        assert KEY not in dst
        for dyi in range((h * g) // 16):
            ny = SL.bilinear_axis(dyi, g, 16, h)[3]
            for dxi in range((w * g) // 16):
                nx = SL.bilinear_axis(dxi, g, 16, w)[3]
                assert (dst[dyi * W + dxi] == 0xCC) == ((nx, ny) in holes)


@pytest.mark.parametrize("w,h", CELLS)
def test_the_last_source_row_and_column_are_covered(w, h):
    """The engine core's dropped-edge defect (rw kinds v4) must not come back: the full fl(w*g/16) x fl(h*g/16)
    rect is written at every g, and from g = 19 up the COVERAGE texel reaches the last native row / column (the
    border carries at least half the weight of the last device row / column).  At g = 17 / 18 thunk_sprite_bilinear's top-left-aligned tap law never makes the
    last 30- or 38-texel index the nearest one (it only blends in as the i1 tap): inherited from the bilinear,
    pinned here so a change shows."""
    src = [PHOTO] * (w * h)
    for yy in range(h):
        src[yy * w + w - 1] = 0xE0
    for xx in range(w):
        src[(h - 1) * w + xx] = 0xE0
    short = {30: (17, 18), 38: (18,), 48: ()}
    for g in GS[1:]:
        dw, dh = (w * g) // 16, (h * g) // 16
        assert (SL.bilinear_axis(dw - 1, g, 16, w)[3] == w - 1) == (g not in short[w])
        assert (SL.bilinear_axis(dh - 1, g, 16, h)[3] == h - 1) == (g not in short[h])
        _r, dst, W, _H = _draw(src, w, h, g, x=0, y=0, fill=0x05)          # 0x05: below every blend of PHOTO..0xE0
        assert all(dst[yy * W + xx] != 0x05 for yy in range(dh) for xx in range(dw))
        mid = (PHOTO + 0xE0) // 2                   # grey table: the blend's index IS its weight
        col = [dst[yy * W + dw - 1] for yy in range(dh - 2 * g // 16 - 2)]      # clear of the other border's blend
        row = [dst[(dh - 1) * W + xx] for xx in range(dw - 2 * g // 16 - 2)]
        assert all(v >= mid for v in col) if g not in short[w] else all(PHOTO < v < mid for v in col)
        assert all(v >= mid for v in row) if g not in short[h] else all(PHOTO < v < mid for v in row)


def test_clipping_and_scaled_draw_offsets():
    w, h = 30, 38
    src = _stripes(w, h)
    full = _draw(src, w, h, 25, x=4, y=6, d_w=80, d_h=90)[1]
    r, clip, W, H = _draw(src, w, h, 25, x=4, y=6, d_w=30, d_h=40)
    assert r == (46, 59)
    assert all(clip[yy * 30 + xx] == full[yy * 80 + xx] for yy in range(40) for xx in range(30))
    # negative origin: the visible part is the same picture, the phase still the DEST row's
    r, neg, W, H = _draw(src, w, h, 25, x=-7, y=-5, d_w=60, d_h=70)
    assert all(neg[yy * 60 + xx] == (A if SL.stripe_top(yy, 25) else B) for yy in range(54) for xx in range(39))
    # the sprite's own draw offsets scale (fl(off*num/den)); the origin args do not
    r, offd, W, H = _draw(src, w, h, 25, x=1, y=2, d_w=80, d_h=90, off=(3, 5))
    px, py = 1 + (3 * 25) // 16, 2 + (5 * 25) // 16
    assert offd[py * 80 + px] != 0xCC and offd[py * 80 + px - 1] == 0xCC and offd[(py - 1) * 80 + px] == 0xCC


def test_period_is_the_screens_not_the_ratios():
    w, h = 30, 38
    src = _stripes(w, h)
    _r, dst, W, _H = _draw(src, w, h, 40, x=0, y=0, num=50, den=32)
    assert all(dst[yy * W] == (A if SL.stripe_top(yy, 40) else B) for yy in range((h * 50) // 32))


def test_goldens():
    """Pinned digests of one mixed sprite (stripes + photo ramp + stroke + key corners) per cell size."""
    got = {}
    for w, h in CELLS:
        src = []
        for yy in range(h):
            for xx in range(w):
                v = (A if yy & 1 else B) if xx < w // 3 else (0x30 + ((xx * 7 + yy * 3) % 0x50))
                if yy == h // 2 and xx >= w // 3:
                    v = 0xE0
                src.append(v)
        for xx, yy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            src[yy * w + xx] = KEY
        for g in (17, 22, 25, 32, 40, 45):
            _r, dst, _W, _H = _draw(src, w, h, g, x=2, y=3)
            got[(w, h, g)] = hashlib.md5(bytes(dst)).hexdigest()[:12]
    assert got == GOLDEN, got


GOLDEN = {
    (38, 48, 17): '3c0a746edc17',
    (38, 48, 22): '4ae56bab0334',
    (38, 48, 25): '9c3d64999008',
    (38, 48, 32): 'af8490c5d391',
    (38, 48, 40): 'a7cc7cdd8b5a',
    (38, 48, 45): '49e5ce6efae5',
    (30, 38, 17): '05b4e74ce8a7',
    (30, 38, 22): '0d3621324f8f',
    (30, 38, 25): '8499e5730e82',
    (30, 38, 32): '7fbb28aee12d',
    (30, 38, 40): 'd7921c83af6a',
    (30, 38, 45): '05e8bb1e0d41',
}
