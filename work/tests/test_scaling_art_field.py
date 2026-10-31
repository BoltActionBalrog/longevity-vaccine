"""scaling_laws.art_field_enlarge (popup event pictures): the properties the law promises.

The dither rule: a scanline field is never resampled into new colours.  A flat scanlined field must come out as
its own two source indices on EVEN scanlines art_scan_rows(g) device rows thick, at every scale; no stripe is
ever a different thickness from its neighbours (banding)."""
from __future__ import annotations

import pathlib
import random
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

OPAQUE = 0x100
GS = [17, 20, 22, 25, 27, 32, 40, 48, 64]


def random_pal(seed):
    rnd = random.Random(seed)
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2] = rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)
    return bytes(pal)


def grey_pal():
    """Index i -> grey i: colours are comparable by index."""
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4] = pal[i * 4 + 1] = pal[i * 4 + 2] = i
    return bytes(pal)


def geometry(sw, sh, g):
    dw, dh = (sw * g) // 16, (sh * g) // 16
    jt = next(j for j in range(dh) if SL.nn_center_index(j, dh, sh) > 0)
    jb = next(j for j in range(dh - 1, -1, -1) if SL.nn_center_index(j, dh, sh) < sh - 1) + 1
    return dw, dh, jt, jb


def nearest(src, pitch, sw, sh, key, g, y0=0):
    """The unsmoothed picture the law is anchored on, derived independently of its tap code: frame rows pinned;
    device row j (dest-buffer row y0 + j) shows field ((y0 + j) // T) & 1 -- the dest buffer's stripe grid -- and
    takes the source row of that field nearest its centre."""
    dw, dh, jt, jb = geometry(sw, sh, g)
    t = 1 if g < 22 else max(2, g // 16)
    rows = []
    for j in range(dh):
        if jt <= j < jb:
            k = ((y0 + j) // t) & 1
            c = (j - jt + 0.5) * (sh - 2) / (jb - jt)                      # centre in interior rows
            r = 1 + min(range(k, sh - 2, 2), key=lambda q: (abs(q + 0.5 - c), -q))
        else:
            r = SL.nn_center_index(j, dh, sh)
        line = [src[r * pitch + SL.nn_center_index(i, dw, sw)] for i in range(dw)]
        rows.append([None if v == key else v for v in line])
    return dw, dh, rows


def flat_scanlined(sw, sh, pitch, a=109, b=201, frame=35, key=9):
    src = bytearray(pitch * sh)
    for y in range(sh):
        for x in range(sw):
            edge = y in (0, sh - 1) or x in (0, sw - 1)
            corner = y in (0, sh - 1) and x in (0, sw - 1)
            src[y * pitch + x] = key if corner else frame if edge else (a if y & 1 else b)
    return bytes(src)


def picture(sw, sh, fn, frame=35, key=9):
    src = bytearray(flat_scanlined(sw, sh, sw, frame=frame, key=key))
    for y in range(1, sh - 1):
        for x in range(1, sw - 1):
            src[y * sw + x] = fn(x, y)
    return bytes(src)


@pytest.mark.parametrize("g", range(17, 65))
def test_scanlines_are_even_one_row_below_1080_then_at_least_two(g):
    """Bright and dark stripes are the same whole number of rows; 1 below g = 22, 2 up to x3, then fl(g / 16)."""
    t = SL.art_scan_rows(g)
    assert t == (1 if g < 22 else max(2, g // 16)) and t <= max(2, (g + 15) // 16)
    assert t == SL.stripe_rows(g)
    fields = [SL.art_scan_field(y, g) for y in range(40 * t)]
    assert fields == [(y // t) & 1 for y in range(40 * t)]                 # runs of exactly t, alternating
    for y in range(30 * t):
        n = SL.art_scan_next(y, g)
        assert n > y and fields[n] == fields[y] and all(fields[q] != fields[y] for q in range(y + 1, n))
        assert SL.art_scan_ordinal(n, g) == SL.art_scan_ordinal(y, g) + 1


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("sw,sh,pitch", [(200, 120, 200), (158, 196, 160), (33, 32, 33), (32, 47, 40)])
def test_flat_scanline_field_keeps_its_two_indices_on_even_stripes(g, sw, sh, pitch):
    """Two flat colours on alternate source rows: no third colour, every stripe art_scan_rows thick."""
    src = flat_scanlined(sw, sh, pitch)
    for key in (9, OPAQUE):
        got = SL.art_field_enlarge(src, pitch, sw, sh, key, random_pal(g), g)
        assert got == nearest(src, pitch, sw, sh, key, g)
    dw, dh, jt, jb = geometry(sw, sh, g)
    j0 = jt + (-jt) % SL.art_scan_rows(g)              # the first interior row that opens a grid stripe (y0 = 0)
    col = [r[dw // 2] for r in got[2][j0:jb]]
    assert set(col) == {109, 201}
    runs, n = [], 1
    for a, b in zip(col, col[1:]):
        if a == b:
            n += 1
        else:
            runs.append(n)
            n = 1
    assert runs and set(runs) == {SL.art_scan_rows(g)}                     # the last (partial) stripe is not counted


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("y0", [0, 1, 2, 3, 5, 7, -3])
def test_fields_sit_on_the_dest_buffer_grid(g, y0):
    """Option B stage 2 (2026-10-06): a picture drawn at dest-buffer row y0 shows field ((y0 + j) // T) & 1 on
    device row j -- the chrome's grid (stripe_top) -- so its stripes continue the panel's.  The same picture 2T
    rows lower is identical; T rows lower, every interior row swaps fields."""
    sw, sh, pitch = 48, 41, 48
    src = flat_scanlined(sw, sh, pitch)
    t = SL.art_scan_rows(g)
    pal = random_pal(g)
    got = SL.art_field_enlarge(src, pitch, sw, sh, 9, pal, g, 16, y0)
    assert got == nearest(src, pitch, sw, sh, 9, g, y0)
    dw, dh, jt, jb = geometry(sw, sh, g)
    for j in range(jt, jb):
        v = got[2][j][dw // 2]                          # field 0 = odd source rows = 109, field 1 = even = 201
        assert (v == 109) == SL.stripe_top(y0 + j, g), (j, v)
    assert SL.art_field_enlarge(src, pitch, sw, sh, 9, pal, g, 16, y0 + 2 * t) == got
    swapped = SL.art_field_enlarge(src, pitch, sw, sh, 9, pal, g, 16, y0 + t)[2]
    assert all(swapped[j][dw // 2] != got[2][j][dw // 2] for j in range(jt, jb))
    assert SL.art_scan_phase(y0, g) == y0 % (2 * t) >= 0


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_a_flat_field_is_untouched_by_the_other_field(g):
    """Random picture in one field, flat in the other: the flat field's rows stay flat."""
    sw, sh = 48, 41
    rnd = random.Random(g)
    src = bytearray(flat_scanlined(sw, sh, sw))
    for y in range(1, sh - 1):
        if y & 1:                                       # source rows of interior parity 0 random; parity 1 flat 201
            for x in range(1, sw - 1):
                src[y * sw + x] = 10 + rnd.randrange(236)
    dw, dh, rows = SL.art_field_enlarge(bytes(src), sw, sw, sh, 9, random_pal(7), g)
    _, _, jt, jb = geometry(sw, sh, g)
    flat = [j for j in range(jt, jb) if SL.art_scan_field(j, g) == 1]       # y0 = 0: device row j is grid row j
    assert flat
    for j in flat:
        assert set(rows[j][3:-3]) == {201}, j


@pytest.mark.parametrize("args", [(200, 120, 9, 16), (200, 120, 9, 12), (31, 120, 9, 25), (200, 31, 9, 25)])
def test_declines(args):
    sw, sh, key, g = args
    assert SL.art_field_enlarge(flat_scanlined(sw, sh, sw), sw, sw, sh, key, random_pal(1), g) is None


def test_declines_a_keyed_hole_but_not_an_opaque_one():
    src = bytearray(flat_scanlined(64, 48, 64))
    src[20 * 64 + 30] = 9
    assert SL.art_field_enlarge(bytes(src), 64, 64, 48, 9, random_pal(1), 25) is None
    assert SL.art_field_enlarge(bytes(src), 64, 64, 48, OPAQUE, random_pal(1), 25) is not None


@pytest.mark.parametrize("g", GS)
def test_field_taps_sum_to_one_and_stay_inside_the_field(g):
    for h0 in (30, 45, 118, 194):
        h1 = (h0 * g) // 16
        for k in (0, 1):
            n = (h0 - k + 1) // 2
            taps = SL._art_field_taps(n, k, [(y + 0.5) * h0 / h1 for y in range(h1)])
            for lo, q, m0, m1, mn in taps:
                assert sum(q) == 1 << SL.PORTRAIT_WEIGHT_Q and q and 0 <= lo and lo + len(q) <= n
                assert 0 <= m0 <= m1 <= n - 1 and m1 - m0 <= 1 and mn in (m0, m1)


def load_picture(name):
    """(src in the engine's index space, w, h, RGBQUAD table in that space) or skip."""
    from PIL import Image
    game = config.game_dir(required=False)
    if not game or not (game / f"{name}_sm.pcx").exists():
        pytest.skip("game art not available")
    im = Image.open(game / f"{name}_sm.pcx")
    p = im.getpalette()[:768]
    pal = bytearray(1024)
    for i in range(256):                                # Buffer_load_pcx stores (raw + 10) & 0xFF
        e = ((i + 10) & 0xFF) * 4
        pal[e], pal[e + 1], pal[e + 2] = p[i * 3 + 2], p[i * 3 + 1], p[i * 3]
    w, h = im.size
    return bytes((v + 10) & 0xFF for v in im.tobytes()), w, h, bytes(pal)


@pytest.mark.parametrize("g", [22, 25, 40])
def test_drone_background_keeps_its_two_colours(g):
    """drone_sm.pcx (the user's banding report): the flat red backdrop left of the head is two palette indices on
    alternate rows; the enlarge must add none, and every scanline there is exactly art_scan_rows thick."""
    src, sw, sh, pal = load_picture("drone")
    dw, dh, rows = SL.art_field_enlarge(src, sw, sw, sh, 9, pal, g)
    native = {src[y * sw + x] for y in range(4, sh - 4) for x in range(4, 40)}
    assert len(native) == 2
    x0, x1 = (4 * g) // 16 + 3, (36 * g) // 16
    col = []
    for j in range((4 * g) // 16 + 3, ((sh - 4) * g) // 16 - 3):
        seg = set(rows[j][x0:x1])
        assert len(seg) == 1 and seg <= native, (j, seg)
        col.append(rows[j][x0])
    runs, n = [], 1
    for a, b in zip(col, col[1:]):
        if a == b:
            n += 1
        else:
            runs.append(n)
            n = 1
    assert set(runs[1:]) == {SL.art_scan_rows(g)}                          # first / last runs are cut by the window


@pytest.mark.parametrize("g", [22, 25, 40])
def test_it_smooths_a_horizontal_ramp_where_nearest_steps(g):
    """Texel pairs 2 greys apart: nearest-neighbour can only show those greys, the law fills the odd ones in."""
    sw, sh = 64, 40
    src = picture(sw, sh, lambda x, y: 20 + 2 * (x // 2))
    dw, dh, rows = SL.art_field_enlarge(src, sw, sw, sh, 9, grey_pal(), g)
    ref = nearest(src, sw, sw, sh, 9, g)[2]
    mid = rows[dh // 2][6:dw - 6]
    assert rows != ref and mid == sorted(mid)                       # monotone: no ringing, no step back
    assert len(set(mid)) >= len(set(ref[dh // 2][6:dw - 6])) * 5 // 4


@pytest.mark.parametrize("g", [22, 25, 27, 40, 48])
def test_each_field_sits_at_its_own_rows(g):
    """A vertical ramp over SOURCE rows, both fields on one line (v = 20 + 3 * source row): every device row must
    show the ramp's value at its own centre, whichever field it shows -- a field sampled half a row off shows up
    as a step at every stripe boundary."""
    sw, sh = 40, 64
    src = picture(sw, sh, lambda x, y: 20 + 3 * y)
    dw, dh, rows = SL.art_field_enlarge(src, sw, sw, sh, 9, grey_pal(), g)
    _, _, jt, jb = geometry(sw, sh, g)
    margin = (6 * g) // 16
    seen = set()
    for j in range(jt + margin, jb - margin):
        centre = 1 + (j - jt + 0.5) * (sh - 2) / (jb - jt)          # in source rows (row r spans [r, r + 1))
        want = 20 + 3 * (centre - 0.5)
        assert abs(rows[j][dw // 2] - want) <= 1.5, (j, rows[j][dw // 2], want)
        seen.add(SL.art_scan_field(j, g))
    assert seen == {0, 1}


@pytest.mark.parametrize("g", [22, 25, 40])
def test_dither_error_stays_inside_its_field(g):
    """One field is a two-colour pattern whose blends the palette has no exact entry for, the other is random:
    re-randomising the second must not change one texel of the first."""
    sw, sh = 48, 40
    outs = []
    for seed in (1, 2):
        rnd = random.Random(seed)
        noise = [[10 + rnd.randrange(236) for _ in range(sw)] for _ in range(sh)]
        src = picture(sw, sh, lambda x, y: noise[y][x] if y & 1 else 40 + 37 * (x // 9 % 2))
        outs.append(SL.art_field_enlarge(src, sw, sw, sh, 9, random_pal(9), g))
    dw, dh, a = outs[0]
    b = outs[1][2]
    _, _, jt, jb = geometry(sw, sh, g)
    steady = [j for j in range(jt, jb) if SL.art_scan_field(j, g) == 1]   # interior parity 1 = even source rows
    assert steady and all(a[j][3:-3] == b[j][3:-3] for j in steady)
    assert any(a[j] != b[j] for j in range(dh))


@pytest.mark.parametrize("g", [22, 25, 40])
def test_flat_field_stays_flat_up_to_a_hard_edge(g):
    """A black block on a flat scanlined field: two texels clear of the block every texel is the field's own
    (no overshoot halo)."""
    sw, sh = 64, 48
    src = picture(sw, sh, lambda x, y: 65 if 24 <= x < 40 and 16 <= y < 32 else (109 if y & 1 else 201))
    dw, dh, rows = SL.art_field_enlarge(src, sw, sw, sh, 9, random_pal(5), g)
    ref = nearest(src, sw, sw, sh, 9, g)[2]
    for j in range(dh):
        r = SL.nn_center_index(j, dh, sh)
        for i in range(dw):
            c = SL.nn_center_index(i, dw, sw)
            if c < 22 or c >= 42 or r < 12 or r >= 36:
                assert rows[j][i] == ref[j][i], (j, i)


@pytest.mark.parametrize("g", [22, 25, 40])
def test_frame_ring_with_a_scanlined_edge_column_follows_the_fields(g):
    """Unframed pictures (al_infil_sm, stars_sm): the outer column is scanlined picture and must show the same
    even stripes as the interior beside it, never the centre-mapped row (uneven runs)."""
    sw, sh = 48, 40
    src = bytearray(picture(sw, sh, lambda x, y: 100 + (y & 1) * 50 + x % 7))
    for y in range(sh):
        src[y * sw] = src[y * sw + sw - 1] = 60 + (y & 1) * 90
    dw, dh, rows = SL.art_field_enlarge(bytes(src), sw, sw, sh, OPAQUE, random_pal(3), g)
    ref = nearest(src, sw, sw, sh, OPAQUE, g)[2]
    for j in range(dh):
        for i in range(dw):
            if SL.nn_center_index(j, dh, sh) in (0, sh - 1) or SL.nn_center_index(i, dw, sw) in (0, sw - 1):
                assert rows[j][i] == ref[j][i], (j, i)


@pytest.mark.parametrize("g", [22, 25])
def test_static_colours_the_picture_uses_stay_reachable(g):
    """council_sm is a third index 4 (navy); break_sm / hasty_sm use 249 (red).  A picture that uses an index
    outside 10..245 may be fitted to it; one that does not never receives it."""
    sw, sh = 48, 40
    pal = bytearray(random_pal(11))
    pal[4 * 4: 4 * 4 + 3] = bytes((128, 0, 0))                      # index 4 = navy (b, g, r)
    pal[249 * 4: 249 * 4 + 3] = bytes((120, 0, 0))                  # index 249 = a second navy, 8 levels off
    src = picture(sw, sh, lambda x, y: 4 if (x // 6 + y // 6) % 2 else 249)
    dw, dh, rows = SL.art_field_enlarge(src, sw, sw, sh, 9, bytes(pal), g)
    inner = [v for r in rows[4:-4] for v in r[4:-4]]
    assert set(inner) == {4, 249}                                   # every blend lands on one of the two
    plain = picture(sw, sh, lambda x, y: 20 + (x * 5 + y * 3) % 200)
    rows2 = SL.art_field_enlarge(plain, sw, sw, sh, 9, bytes(pal), g)[2]
    assert all(v is None or 10 <= v <= 245 for r in rows2 for v in r)


@pytest.mark.parametrize("name", ["facblt", "council", "hasty", "drone"])
@pytest.mark.parametrize("g", [22, 25])
def test_real_pictures_keep_their_brightness(name, g):
    """Mean r, g, b within 1 level of the unsmoothed picture's: even stripes and round-to-nearest error terms
    (an uneven 3 + 2 duty brightened drone_sm 9-16%; floor-rounded error terms cost ~2 levels)."""
    src, sw, sh, pal = load_picture(name)
    dw, dh, rows = SL.art_field_enlarge(src, sw, sw, sh, 9, pal, g)
    ref = nearest(src, sw, sw, sh, 9, g)[2]
    for c in (2, 1, 0):
        a = [pal[v * 4 + c] for r in rows for v in r if v is not None]
        b = [pal[v * 4 + c] for r in ref for v in r if v is not None]
        assert abs(sum(a) / len(a) - sum(b) / len(b)) <= 1.0, (name, c)
