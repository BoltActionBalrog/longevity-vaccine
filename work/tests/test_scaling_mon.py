"""Law sweep for the Planetary Monument screen (scaling_laws "PLANETARY MONUMENT" section).

The screen's scale is the UNCLAMPED popup numerator num = min(floor(16*ScreenH/768), floor(16*ScreenW/1024)) over
16 (= scale_uniform(16), fix 11: the width term keeps the art inside a narrower-than-4:3 screen); every geometry
value is vanilla x num/16 through half_down and the identity at num == 16 (1024x768); the letterbox is the
centred remainder, and the sweep checks the art + content + CLOSE/BACK stay inside the screen.  The resampler / panel / face laws are the prototype's (hook_monument_proto.js v7d,
measured-correct at 4K / 1600x1200 / 1920x1080) and are checked here for their structural properties;
their bit-exact asm ports are checked in test_mon_asm_parity.py.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

RES = {(3840, 2160): (45, (480, 0)), (1600, 1200): (25, (0, 0)), (1920, 1080): (22, (256, 12)), (1024, 768): (16, (0, 0))}
# narrower than 4:3 (fix 11, user shots 2026-10-18 at 1280x1024: the height-only num 21 put the art 32 px past each
# side and BACK off-screen): the width term rules -> art as wide as the screen, centred vertically; num <= 16 -> native
NARROW = {(1280, 1024): (20, (0, 32)), (1152, 960): (18, (0, 48)), (2560, 2048): (40, (0, 64)), (1600, 1280): (25, (0, 40)),
          (1350, 1080): (21, (3, 36)), (1200, 1600): (18, (24, 368)),
          (1024, 1024): (16, None), (1080, 1350): (16, None), (768, 1024): (12, None)}
NUMS = list(range(16, 91))


def test_scale_num_is_the_unclamped_min_law():
    for (sw, sh), (num, box) in RES.items():
        assert SL.mon_scale_num(sw, sh) == num
        assert SL.mon_letterbox(sw, sh, num) == box                 # the proto's measured letterbox at the 3 res + native
    assert SL.mon_scale_num(7680, 4320) == 90                        # 8K: no 40 clamp
    assert SL.mon_armed(3840, 2160, 1) and not SL.mon_armed(1024, 768, 1) and not SL.mon_armed(3840, 2160, 0)
    assert not SL.mon_armed(800, 600, 1)


@pytest.mark.parametrize("sw,sh", sorted(NARROW))
def test_narrow_screen_takes_the_width_term_and_keeps_the_art_on_screen(sw, sh):
    num, box = NARROW[(sw, sh)]
    assert SL.mon_scale_num(sw, sh) == num == min((16 * sh) // 768, (16 * sw) // 1024)
    assert SL.mon_armed(sw, sh, 1) == (box is not None)
    if box is None:
        return                                                          # num <= 16: the engine's own 1024x768 layout
    lx, ly = SL.mon_letterbox(sw, sh, num)
    assert (lx, ly) == box
    l, t, r, b = SL.mon_art_rect(sw, sh, num)
    assert 0 <= l and 0 <= t and r <= sw and b <= sh
    assert l == (sw - (r - l)) >> 1 and t == (sh - (b - t)) >> 1        # centred (>> 1 floors)
    x, y, w, h = SL.mon_button_rect(num, lx, ly)
    assert 0 <= x and x + w <= sw and 0 <= y and y + h <= sh            # CLOSE / BACK on screen


def test_scale_num_is_scale_uniform_and_the_splash_law():
    """mon_scale_num = scale_uniform(16) unclamped = splash_scale_num; 4:3 and wider = the height term alone (the
    first bake's law, so every 4:3-and-wider screen is unchanged)."""
    for sw in range(640, 7681, 37):
        for sh in range(480, 4321, 29):
            n = SL.mon_scale_num(sw, sh)
            assert n == SL.scale_uniform(16, sw, sh) == SL.splash_scale_num(sw, sh)
            assert n == min((16 * sh) // 768, (16 * sw) // 1024)
            if sw * 768 >= sh * 1024:
                assert n == (16 * sh) // 768
            assert min(n, SL.G_MAX) == SL.popup_g(sw, sh) or n < SL.G_MIN       # the popup g before its clamp


H_BANDS = [(h0, min(h0 + 120, 4321)) for h0 in range(480, 4321, 120)]


def _art_inside(sw, sh):
    """[] or the reasons the Monument's armed layout leaves the screen at sw x sh."""
    num = SL.mon_scale_num(sw, sh)
    if not SL.mon_armed(sw, sh, 1):
        return []
    bad = []
    l, t, r, b = SL.mon_art_rect(sw, sh, num)
    if l < 0 or t < 0 or r > sw or b > sh:
        bad.append(("art", (l, t, r, b)))
    lx, ly = l, t
    cl, ct, cr, cb = SL.mon_content_rect(num, lx, ly)
    if not (l <= cl < cr <= r and t <= ct < cb <= b):
        bad.append(("content", (cl, ct, cr, cb)))
    x, y, w, h = SL.mon_button_rect(num, lx, ly)
    if x < 0 or y < 0 or x + w > sw or y + h > sh:
        bad.append(("button", (x, y, w, h)))
    return bad


@pytest.mark.parametrize("h0,h1", H_BANDS)
def test_sweep_art_and_buttons_inside_the_screen(h0, h1):
    """The 'art inside the screen' invariant over every height and a dense width grid: every 4th width, plus the
    4:3 boundary (+-3) and each num step of the width term (multiples of 64, +-1) for that height."""
    bad = []
    for sh in range(h0, h1):
        ws = set(range(640, 7681, 4))
        q = (sh * 1024 + 767) // 768
        ws |= {q + d for d in range(-3, 4)}
        ws |= {64 * k + d for k in range(10, 121) for d in (-1, 0, 1)}
        for sw in ws:
            if sw < 640:
                continue
            for why in _art_inside(sw, sh):
                bad.append((sw, sh, why))
                if len(bad) > 5:
                    pytest.fail(f"art leaves the screen: {bad}")
    assert not bad


def test_identity_at_native():
    n, lx, ly = 16, 0, 0
    assert SL.mon_content_rect(n, lx, ly) == SL.MON_CONTENT_NATIVE
    assert SL.mon_button_rect(n, lx, ly) == SL.MON_BTN_NATIVE
    for r in ((319, 202, 479, 299), (256, 131, 771, 175), (213, 202, 813, 562), (364 + 112, 111 + 84, 435 + 112, 175 + 84)):
        assert SL.mon_rect(r, n, lx, ly) == r
    assert SL.mon_font_size(12, 16) == 12 and SL.mon_font_size(14, 16) == 14
    for v in range(0, 1100):
        assert SL.mon_s(v, 16) == v


@pytest.mark.parametrize("num", NUMS)
def test_geometry_is_proportionate_and_nested(num):
    """Every edge = vanilla x num/16 (half_down); the content rect stays inside the letterboxed art, the
    buttons stay inside the content rect's bottom band, the tables' rects keep their vanilla order."""
    sw, sh = SL.mon_s(1024, num) + 100, SL.mon_s(768, num)
    lx, ly = SL.mon_letterbox(sw, sh, num)
    assert (lx, ly) == (50, 0)
    L, T, R, B = SL.mon_content_rect(num, lx, ly)
    assert (L - lx, T - ly, R - lx, B - ly) == tuple(SL.mon_s(v, num) for v in SL.MON_CONTENT_NATIVE)
    assert lx <= L < R <= lx + SL.mon_s(1024, num) and ly <= T < B <= ly + SL.mon_s(768, num)
    x, y, w, h = SL.mon_button_rect(num, lx, ly)
    assert (x - lx, y - ly, w, h) == (SL.mon_s(824, num), SL.mon_s(747, num), SL.mon_s(200, num), SL.mon_s(21, num))
    assert x + w <= lx + SL.mon_s(1024, num) and y + h <= ly + SL.mon_s(768, num)
    for r in ((319, 202, 479, 299), (256, 131, 771, 175), (213, 202, 813, 562)):
        l, t, rr, b = SL.mon_rect(r, num, lx, ly)
        assert l < rr and t < b and L <= l and rr <= R + 1 and T <= t and b <= B + 1
        # each literal scaled independently: the origin term is s(112|84), the offset term s(v - 112|84)
        assert l == lx + SL.mon_s(112, num) + SL.mon_s(r[0] - 112, num)
        assert t == ly + SL.mon_s(84, num) + SL.mon_s(r[1] - 84, num)
    P, hN = SL.mon_stripe(num)
    assert P == SL.stripe_period(num) and hN == (P + 1) >> 1
    assert SL.mon_font_size(12, num) == (12 * num) // 16 <= SL.mon_s(12, num)


def test_phase_weights_are_normalised_symmetric_and_identity_at_phase_zero():
    W = SL.mon_phase_weights()
    assert len(W) == SL.MON_PHASES and all(len(w) == SL.MON_TAPS and sum(w) == 256 for w in W)
    assert W[0][2] == 256 and all(abs(v) <= 2 for t, v in enumerate(W[0]) if t != 2)      # phase 0 = the sample on a texel
    for q in range(SL.MON_PHASES):
        assert W[q] == tuple(reversed(W[SL.MON_PHASES - 1 - q]))                            # mirror symmetry
    assert W[32][2] == W[32][3] or abs(W[32][2] - W[32][3]) <= 5                             # the half-way phase is (near) even


@pytest.mark.parametrize("n_src,n_dst", [(1024, 2880), (768, 2160), (160, 450), (97, 273), (600, 1688), (1024, 1600), (10, 10), (3, 12)])
def test_axis_taps_are_centre_aligned_clamped_and_monotonic(n_src, n_dst):
    import math
    taps = SL.mon_axis_taps(n_src, n_dst)
    assert len(taps) == n_dst
    prev = -1
    for i, (idx, q) in enumerate(taps):
        c = (i + 0.5) * n_src / n_dst - 0.5
        c64 = math.floor(c * 64)
        assert q == (c64 & 63) and 0 <= q < 64
        assert idx[2] == min(n_src - 1, max(0, c64 >> 6))
        assert all(0 <= v < n_src for v in idx) and list(idx) == sorted(idx)
        assert idx[2] >= prev
        prev = idx[2]
    if n_src == n_dst:
        assert all(q == 0 and idx[2] == i for i, (idx, q) in enumerate(taps))


def test_nearest_lut_never_emits_the_key_and_maps_palette_colours_to_themselves():
    rnd = random.Random(11)
    pal = bytearray()
    seen = set()
    for i in range(256):
        while True:
            c = (rnd.randrange(0, 256, 8), rnd.randrange(0, 256, 8), rnd.randrange(0, 256, 8))   # 15-bit-exact colours
            if c not in seen:
                break
        seen.add(c)
        pal += bytes((c[0] | (c[0] >> 5), c[1] | (c[1] >> 5), c[2] | (c[2] >> 5), 0))
    lut = SL.mon_nearest_lut(bytes(pal))
    assert len(lut) == 32768 and SL.MON_KEY not in lut
    for k in range(256):
        if k == SL.MON_KEY:
            continue
        b, g, r = pal[k * 4], pal[k * 4 + 1], pal[k * 4 + 2]
        assert lut[((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)] == k


def _exact_pal():
    """256 distinct 15-bit-exact colours (the LUT keys expand 5-bit channels to v<<3 | v>>2): index i's colour
    maps back to i, so a flat field of i resamples to i with zero diffusion error."""
    ex = lambda v: (v << 3) | (v >> 2)
    return bytes(sum(([ex(i & 31), ex((i >> 3) & 31), ex(i >> 5), 0] for i in range(256)), []))


def test_resampler_keeps_a_flat_field_flat_and_stays_inside_the_dest():
    pal = _exact_pal()
    lut = SL.mon_nearest_lut(pal)
    src = bytearray([77] * (30 * 20))
    dst = bytearray([0xEE] * (50 * 40))
    SL.mon_resample(src, 30, 0, 0, 30, 20, pal, dst, 50, 50, 40, -5, -3, 60, 45, lut, True)
    for y in range(40):
        for x in range(50):
            assert dst[y * 50 + x] == 77, (x, y)          # zero error everywhere: a flat source stays that index
    dst = bytearray([0xEE] * (50 * 40))
    SL.mon_resample(src, 30, 0, 0, 30, 20, pal, dst, 50, 50, 40, 10, 10, 20, 15, lut, True)
    for y in range(40):
        for x in range(50):
            inside = 10 <= x < 30 and 10 <= y < 25
            assert dst[y * 50 + x] == (77 if inside else 0xEE), (x, y)


def test_resampler_dither_spreads_a_two_level_ramp_over_more_palette_entries_than_nearest():
    """The whole point of option C/D: error diffusion at device density uses the palette's in-between
    entries instead of snapping the enlarged gradient back to the few source indices (the banding)."""
    pal = bytearray(256 * 4)
    for i in range(256):
        pal[i * 4:i * 4 + 4] = bytes((i, i, i, 0))          # grey ramp: index == grey level
    pal = bytes(pal)
    lut = SL.mon_nearest_lut(pal)
    src = bytearray(40 * 4)
    for y in range(4):
        for x in range(40):
            src[y * 40 + x] = 60 if x < 20 else 100           # neither level is 15-bit-exact: the LUT alone is biased
    out_nn = bytearray(120 * 12)
    out_fs = bytearray(120 * 12)
    SL.mon_resample(src, 40, 0, 0, 40, 4, pal, out_nn, 120, 120, 12, 0, 0, 120, 12, lut, False)
    SL.mon_resample(src, 40, 0, 0, 40, 4, pal, out_fs, 120, 120, 12, 0, 0, 120, 12, lut, True)
    assert len(set(out_fs)) >= len(set(out_nn))
    assert all(40 <= v <= 120 for v in out_fs)               # no ringing beyond the Lanczos overshoot band (+-11 on a 40 step)
    # the flat interiors: nearest-index alone snaps to the 15-bit grid (a constant bias), diffusion averages
    # back to the source level (what makes the enlarged gradients smooth instead of banded)
    left_nn = [out_nn[y * 120 + x] for y in range(12) for x in range(10, 45)]
    left_fs = [out_fs[y * 120 + x] for y in range(12) for x in range(10, 45)]
    assert len(set(left_nn)) == 1 and left_nn[0] != 60
    assert abs(left_nn[0] - 60) >= 2 and abs(sum(left_fs) / len(left_fs) - 60) < 1.5 and len(set(left_fs)) >= 2


def test_panel_detection_needs_alternation_and_the_minimum_run():
    sw = 400
    src = bytearray(random.Random(4).randrange(30, 34) for _ in range(sw * 30))
    for y in range(6, 14, 2):                                 # 4 light rows 240 over 320 px, dark 100 between
        for x in range(40, 360):
            src[y * sw + x] = 240
            src[(y + 1) * sw + x] = 100
    assert SL.mon_panel_rows(src, sw, sw, 30) == (240, 6, 4)
    assert SL.mon_row_extent(src, sw, sw, 6, 240) == (40, 359)
    for x in range(40, 360):                                  # fill one gap row with the light index: the chain breaks at 1 + 1
        src[9 * sw + x] = 240
    assert SL.mon_panel_rows(src, sw, sw, 30) is None
    solid = bytearray([240] * (sw * 30))                      # every row uniform: no alternation -> no panel
    assert SL.mon_panel_rows(solid, sw, sw, 30) is None


@pytest.mark.parametrize("num", (22, 25, 32, 40, 45))
def test_panel_synthesis_lays_hn_light_rows_per_p(num):
    sw, sh = 400, 30
    src = bytearray(random.Random(4).randrange(30, 34) for _ in range(sw * sh))
    for k in range(6):
        y = 6 + 2 * k
        for x in range(40 - k, 360 + k):
            src[y * sw + x] = 240
            src[(y + 1) * sw + x] = 100 + (x & 1)
    dw, dh = SL.mon_s(sw, num), SL.mon_s(sh, num)
    dst = bytearray([7] * (dw * dh))
    Y0, Y1, P, hN = SL.mon_panel_synth(src, sw, sw, sh, dst, dw, dw, dh, 0, 0, num)
    assert (Y0, Y1) == (SL.mon_s(6, num), SL.mon_s(18, num)) and (P, hN) == SL.mon_stripe(num)
    for y in range(Y0, Y1):
        row = dst[y * dw:(y + 1) * dw]
        light = (y - Y0) % P < hN
        assert (240 in row) == light
        if not light:
            assert {100, 101} >= set(v for v in row if v != 7) and 240 not in row
    assert all(v == 7 for v in dst[:Y0 * dw]) and all(v == 7 for v in dst[Y1 * dw:])


@pytest.mark.parametrize("num", (22, 25, 45))
def test_face_restripe_law(num):
    P, hN = SL.mon_stripe(num)
    pal = bytearray(256 * 4)
    pal[201 * 4:201 * 4 + 4] = bytes((6, 8, 32, 0))
    pal[109 * 4:109 * 4 + 4] = bytes((12, 12, 136, 0))
    pal = bytes(pal)
    w, h = SL.mon_s(200, num), SL.mon_s(21, num)
    buf = bytearray(w * h)
    for y in range(h):
        v = 201 if ((y * 16) // num) % 2 == 0 else 109
        for x in range(w):
            buf[y * w + x] = v
    buf[(h // 2) * w + 5] = 0                                  # a label pixel
    res = SL.mon_face_restripe(buf, w, w, h, pal, num)
    assert res == (201, 109, 109)                              # v2: the BRIGHTER member (red 109) on the wide/top rows
    for y in range(h):
        assert set(buf[y * w:(y + 1) * w]) - {0} == ({109} if (y % P) < hN else {201})
    assert buf[(h // 2) * w + 5] == 0
    # no pair: solid, and runs longer than P+1
    assert SL.mon_face_restripe(bytearray([109] * (w * h)), w, w, h, pal, num) is None
    long = bytearray((201 if (y // (P + 2)) % 2 == 0 else 109) for y in range(h) for _ in range(w))
    assert SL.mon_face_restripe(long, w, w, h, pal, num) is None
    assert SL.mon_face_restripe(bytearray(buf), w, w, h, pal, 16) is None          # P <= 2 -> untouched
