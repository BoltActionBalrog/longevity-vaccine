"""Law sweep for the startup splash (scaling_laws "STARTUP SPLASH"; group splash_scale).

logo.pcx (800x600) was authored inside the 1024x768 screen.  Above native scale it is drawn at
vanilla x num/16 on both axes from ONE num (4:3 kept), num = min(floor(16H/768), floor(16W/1024)) (the
full-screen menus' unclamped height law, capped so the 1024x768 frame fits a narrow screen), centred;
num <= 16 is the vanilla 1:1 blit.  The smooth filter is the Monument resampler (mon_resample), whose
own laws are swept in test_scaling_mon.py; the asm port is checked in test_splash_asm_parity.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

KNOWN = {   # (W, H): (num, rect)
    (3840, 2160): (45, (795, 236, 2250, 1687)),
    (1600, 1200): (25, (175, 131, 1250, 937)),
    (1920, 1080): (22, (410, 127, 1100, 825)),
    (2560, 1440): (30, (530, 157, 1500, 1125)),
    (1280, 1024): (20, (140, 137, 1000, 750)),
    (1024, 768): (16, (112, 84, 800, 600)),
    (1366, 768): (16, (283, 84, 800, 600)),
    (800, 600): (12, (0, 0, 800, 600)),
}


@pytest.mark.parametrize("res", list(KNOWN))
def test_known_resolutions(res):
    num, rect = KNOWN[res]
    assert SL.splash_scale_num(*res) == num
    assert SL.splash_rect(*res, 800, 600) == rect
    assert SL.splash_armed(*res) == (num > 16)


def test_height_law_is_the_full_screen_menus_one():
    """Exactly mon_scale_num (unclamped: 90 at 8K) -- the full-screen menus share the splash's min law since fix 11;
    4:3 and wider it is the height term alone."""
    for h in range(600, 4321, 7):
        w = (h * 4 + 2) // 3 + 1
        assert SL.splash_scale_num(w, h) == SL.mon_scale_num(w, h) == (16 * h) // 768
        assert SL.splash_scale_num(w * 3, h) == SL.mon_scale_num(w * 3, h) == (16 * h) // 768
        assert SL.splash_scale_num(w // 2, h) == SL.mon_scale_num(w // 2, h)
    assert SL.splash_scale_num(7680, 4320) == 90


def test_narrow_screen_caps_on_width():
    assert SL.splash_scale_num(1024, 1280) == 16 and not SL.splash_armed(1024, 1280)
    assert SL.splash_scale_num(1200, 1920) == 18


def test_native_is_the_vanilla_blit():
    """num <= 16: the engine's own centring ((screen - src)/2 truncated toward zero), 1:1."""
    for (w, h) in ((1024, 768), (800, 600), (1280, 768), (640, 480), (1366, 768), (1024, 1280)):
        assert not SL.splash_armed(w, h)
        x, y, rw, rh = SL.splash_rect(w, h, 800, 600)
        assert (rw, rh) == (800, 600)
        assert x == int((w - 800) / 2) and y == int((h - 600) / 2)
    assert SL.splash_scale_num(0, 0) == 0 and not SL.splash_armed(0, 768)


SWEEP = [(w, h) for h in range(600, 4400, 37) for w in (h * 4 // 3, h * 16 // 9, h * 16 // 10, h * 5 // 4, h * 21 // 9, h)]


@pytest.mark.parametrize("w,h", SWEEP)
def test_proportionate_centred_and_on_screen(w, h):
    num = SL.splash_scale_num(w, h)
    x, y, rw, rh = SL.splash_rect(w, h, 800, 600)
    if num <= 16:
        assert (rw, rh) == (800, 600)
        return
    # vanilla x num/16 on each axis, from one num (half_down: within half a pixel of exact)
    assert rw == SL.mon_s(800, num) and rh == SL.mon_s(600, num)
    assert abs(2 * 16 * rw - 2 * 800 * num) <= 16 and abs(2 * 16 * rh - 2 * 600 * num) <= 16
    # 4:3 kept: the drawn aspect is within one pixel of 4:3
    assert abs(rw * 3 - rh * 4) <= 4
    # on screen and centred (the remainders differ by at most one pixel)
    assert 0 <= x and 0 <= y and x + rw <= w and y + rh <= h
    assert abs((w - x - rw) - x) <= 1 and abs((h - y - rh) - y) <= 1
    # the 1024x768 frame it was composed in fits too (the width cap)
    assert SL.mon_s(1024, num) <= w and SL.mon_s(768, num) <= h


def test_monotone_in_screen_size():
    prev = 0
    for h in range(600, 4400):
        n = SL.splash_scale_num(h * 4 // 3 + 1, h)
        assert n >= prev
        prev = n


def test_compose_native_copies_verbatim():
    src = bytes((i * 7 + j) & 0xFF for i in range(600) for j in range(800))
    out = SL.splash_compose(src, 800, 800, 600, bytes(1024), 1024, 768)
    for r in (0, 299, 599):
        assert out[(84 + r) * 1024 + 112:(84 + r) * 1024 + 912] == src[r * 800:(r + 1) * 800]
    assert out[83 * 1024 + 500] == 0 and out[(84 + 600) * 1024 + 500] == 0 and out[100 * 1024 + 111] == 0


def test_compose_armed_fills_exactly_the_rect():
    """A flat source (one exactly-representable colour) resamples to that index over exactly splash_rect;
    everything else stays the black fill.  (A tiny source keeps the pure-Python reference fast.)"""
    pal = bytearray(1024)
    pal[200 * 4:200 * 4 + 3] = bytes((0x84, 0x42, 0xC6))       # 15-bit-exact b, g, r
    lut = [200] * 32768
    sw, sh = 16, 12
    src = bytes([200]) * (sw * sh)
    W, H = 1100, 825                                            # num 17
    out = SL.splash_compose(src, sw, sw, sh, bytes(pal), W, H, lut=lut)
    x, y, w, h = SL.splash_rect(W, H, sw, sh)
    assert (w, h) == (SL.mon_s(sw, 17), SL.mon_s(sh, 17))
    for yy in range(H):
        row = out[yy * W:(yy + 1) * W]
        if y <= yy < y + h:
            assert row[x:x + w] == bytes([200]) * w and not any(row[:x]) and not any(row[x + w:])
        else:
            assert not any(row)


def test_logo_art_has_no_scanline_dither():
    """The dither invariant gate: logo.pcx must be photographic (no 1-px row/column dither) for a smooth
    resample to be lawful.  A scanline-dithered replacement would need regeneration instead."""
    import config
    p = config.game_dir(required=False)
    p = p / "logo.pcx" if p else None
    if not p or not p.exists():
        pytest.skip("logo.pcx not found in the game folder")
    Image = pytest.importorskip("PIL.Image")
    im = Image.open(p)
    assert im.size == (800, 600) and im.mode == "P"
    a = im.tobytes()
    w, h = im.size
    rows = cols = 0
    for y in range(0, h - 2, 3):
        o = y * w
        for x in range(0, w - 2, 3):
            v = a[o + x]
            rows += a[o + 2 * w + x] == v and a[o + w + x] != v
            cols += a[o + x + 2] == v and a[o + x + 1] != v
    n = ((h - 2 + 2) // 3) * ((w - 2 + 2) // 3)
    assert rows / n < 0.05 and cols / n < 0.05
