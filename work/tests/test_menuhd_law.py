"""uimod menuhd_law.h (C++) vs scaling_laws (the source of truth), exactly: menu_hd_layout, menu_hd_moon_rect,
menu_hd_axis, mon_phase_weights and menu_hd_resample; and the laws' own promises.

Builds tests/menuhd_selftest.cpp once with the VS x86 toolchain (skipped when VS is absent) and runs every case of a
test through one process. The law-only tests run anyway.
"""
from __future__ import annotations

import functools
import pathlib
import random
import struct
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402
import scaling_laws as SL  # noqa: E402

PIC = (1024, 768, 404, 2400)        # the stock opening, custom_planet's strip width, the panorama (menuhd_law.h's)
MOON = 450
ART = 3


def layout(w, h):
    return SL.menu_hd_layout(w, h, *PIC)


SCREENS = [(800, 600), (1024, 768), (1280, 1024), (1600, 1200), (1366, 768), (1600, 900), (1920, 1080), (1920, 1200),
           (2560, 1080), (2560, 1440), (3440, 1440), (3840, 1080), (3840, 2160), (5120, 1440), (1440, 1080),
           (5760, 1080), (7680, 1080), (1080, 1920)]


# ---- the layout ---------------------------------------------------------------------------------------------------

def test_identity_at_the_stock_size():
    num, den, *rest = layout(1024, 768)
    assert num == den and tuple(rest) == (0, 0, 1024, 768, 404, 620)


@pytest.mark.parametrize("w,h", SCREENS)
def test_uniform_and_inside_the_screen(w, h):
    num, den, x0, y0, core_w, core_h, strip_w, strip_x = layout(w, h)
    assert core_h == 768 * num // den and strip_w == 404 * num // den        # one scale for both axes
    assert 0 <= x0 and x0 + core_w <= w and 0 <= y0 and y0 + core_h == h        # bottom-anchored, inside
    assert strip_x + strip_w == x0 + core_w                                     # the strip ends the picture
    assert (strip_x - x0) * den <= 2400 * num                                   # the panorama covers its span
    if w * 3 >= h * 4:
        assert (core_h, y0) == (h, 0)                                           # wide: full height, no bands


def test_a_narrow_screen_puts_the_band_above_so_the_menu_meets_the_picture():
    num, den, x0, y0, core_w, core_h, *_ = layout(1280, 1024)
    assert (x0, core_w, core_h) == (0, 1280, 960) and y0 + core_h == 1024 and y0 == 64


def test_past_the_widest_shape_the_picture_is_right_aligned_with_a_plain_bar():
    """The panorama covers (2400 + 404) : 768, about 32.9:9; a wider screen gets that shape right-aligned, so the
    menu bars (anchored to the screen's right edge) stay on the planet strip."""
    for w, h in ((3840, 1080), (5120, 1440)):
        lay = layout(w, h)
        assert (lay[2], lay[4]) == (0, w)                                       # 32:9 fills the screen
    num, den, x0, y0, core_w, *_ = layout(5760, 1080)
    assert core_w == (2400 + 404) * num // den and x0 == 5760 - core_w and x0 > 0
    assert x0 + core_w == 5760                                                  # the strip ends at the right edge


def test_moon_rect_is_the_pictures_top_left():
    lay = layout(1920, 1080)
    assert SL.menu_hd_moon_rect(lay, MOON) == (lay[2], lay[3], MOON * lay[0] // lay[1], MOON * lay[0] // lay[1])
    assert SL.menu_hd_moon_rect(layout(1024, 768), MOON) == (0, 0, 450, 450)


def test_step_is_exact():
    assert SL.menu_hd_step(ART, 2160, 768) == (2304, 2160)                      # no float


# ---- the axis weights ---------------------------------------------------------------------------------------------

AXES = [(n, ART * den, num, src) for (w, h) in SCREENS for (num, den, *_r) in [layout(w, h)]
        for n, src in ((min(60, 404 * num // den), 404 * ART), (40, 450 * ART))] + \
       [(7, 3, 1, 21), (5, 7, 3, 12), (9, 5, 5, 9), (4, 2, 7, 3), (6, 1, 4, 2)]


def test_axis_weights_sum_to_one_and_cover_the_footprint():
    for n, sn, sd, src in AXES:
        for i, taps in enumerate(SL.menu_hd_axis(n, sn, sd, src)):
            assert sum(w for _k, w in taps) == SL.MENU_HD_ONE, (n, sn, sd, i)
            if sn >= sd:
                ks = [k for k, _w in taps if k >= 0]
                assert all(i * sn // sd <= k < src for k in ks)
                assert all(w >= 0 for _k, w in taps)                            # a shrink never rings


def test_enlarging_uses_the_mods_lanczos_rule():
    W = SL.mon_phase_weights()
    for taps in SL.menu_hd_axis(10, 2, 3, 7):
        assert len(taps) == SL.MON_TAPS and tuple(w for _k, w in taps) in W


# ---- the C++ port -------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "menuhd_selftest.cpp", "menuhd_selftest_", "/Oi /GL")


def run(exe, *args, stdin=""):
    return subprocess.run([str(exe), *args], input=stdin, capture_output=True, text=True, check=True).stdout


def test_layout_port_matches_law(exe):
    sizes = SCREENS + [(1, 1), (7, 5), (12345, 678), (1023, 769), (2804, 768), (2805, 768)]
    out = run(exe, "layout", stdin="".join(f"{w} {h}\n" for w, h in sizes)).splitlines()
    assert len(out) == len(sizes)
    for (w, h), line in zip(sizes, out):
        lay = layout(w, h)
        assert tuple(int(v) for v in line.split()) == lay + SL.menu_hd_moon_rect(lay, MOON), (w, h)


def test_lanczos_table_is_the_law(exe):
    rows = [tuple(int(v) for v in ln.split()) for ln in run(exe, "lanczos").splitlines()]
    assert rows == SL.mon_phase_weights()


def test_axis_port_matches_law(exe):
    out = run(exe, "axis", stdin="".join(f"{n} {sn} {sd} {src}\n" for n, sn, sd, src in AXES)).splitlines()
    at = 0
    for n, sn, sd, src in AXES:
        for taps in SL.menu_hd_axis(n, sn, sd, src):
            f = out[at].split()
            at += 1
            assert f[0] == "1" and int(f[1]) == len(taps)
            assert tuple(tuple(int(v) for v in t.split(":")) for t in f[2:]) == taps, (n, sn, sd, src)
    assert at == len(out)


#: the canvas range the port tests use: 40 colours (the law's cost is per colour; the game's 10..246 takes the same
#: code path, and a 236-colour table took ~2.4 s in Python per table and per xdist worker)
LO, HI = 10, 50


def canvas_table(seed):
    """An RGBQUAD canvas: LO..HI-1 random colours, the rest zero."""
    rnd = random.Random(seed)
    q = bytearray(1024)
    for k in range(LO, HI):
        q[k * 4:k * 4 + 3] = bytes(rnd.randrange(256) for _ in range(3))
    return bytes(q)


@functools.lru_cache(maxsize=None)
def lut_for(seed, lo, hi):
    return SL.mon_nearest_lut(canvas_table(seed), lo, hi)


def picture(sw, sh, seed, key):
    rnd = random.Random(seed)
    rows = []
    for y in range(sh):
        row = bytearray()
        for x in range(sw):
            if key >= 0 and (x - sw / 2) ** 2 + (y - sh / 2) ** 2 > (min(sw, sh) / 2.2) ** 2:
                row.append(key)
            else:
                row.append((x * 7 // sw + y * 5 // sh * 8 + rnd.randrange(3)) & 255)
        rows.append(bytes(row))
    return rows


#: (sw, sh, key, sn, sd, dw, dh): shrinks (whole and fractional), 1:1, enlargements, keyed and not, wider than the
#: source (OUTSIDE pixels)
CASES = [(30, 24, -1, 3, 1, 10, 8), (30, 24, -1, 2304, 2160, 28, 22), (30, 24, 255, 2304, 1080, 15, 11),
         (21, 21, 255, 3, 1, 7, 7), (12, 10, -1, 1, 1, 12, 10), (12, 10, -1, 2, 3, 18, 15), (9, 9, 255, 2, 5, 22, 22),
         (16, 12, -1, 3, 1, 8, 6), (40, 30, -1, 7, 3, 17, 12)]


def test_resample_port_matches_law(exe, tmp_path):
    blob = bytearray(struct.pack("<i", len(CASES)))
    want = []
    for n, (sw, sh, key, sn, sd, dw, dh) in enumerate(CASES):
        seed = n % 2
        canvas = canvas_table(seed)
        pal = bytes(random.Random(100 + n).randrange(256) for _ in range(768))
        rows = picture(sw, sh, n, key)
        blob += struct.pack("<9i", sw, sh, key, sn, sd, dw, dh, LO, HI) + pal + canvas + b"".join(rows)
        want.append(SL.menu_hd_resample(rows, sw, sh, pal, key, sn, sd, dw, dh, canvas, LO, HI,
                                        lut_for(seed, LO, HI)))
    (tmp_path / "in.bin").write_bytes(bytes(blob))
    run(exe, "resample", str(tmp_path / "in.bin"), str(tmp_path / "out.bin"))
    raw, at = (tmp_path / "out.bin").read_bytes(), 0
    for case, rows in zip(CASES, want):
        dw, dh = case[5], case[6]
        (ok,) = struct.unpack_from("<i", raw, at)
        at += 4
        got = [raw[at + j * dw:at + (j + 1) * dw] for j in range(dh)]
        at += dw * dh
        assert ok == 1 and got == [bytes(r) for r in rows], case
    assert at == len(raw)


def test_art_already_in_the_canvas_colours_is_reproduced_exactly():
    """A pack that is the stock picture's colours, 3x: shrunk by exactly 3 every screen pixel is its own colour."""
    canvas = canvas_table(0)
    pal = bytearray(768)
    for k in range(256):
        pal[k * 3:k * 3 + 3] = bytes((canvas[k * 4 + 2], canvas[k * 4 + 1], canvas[k * 4]))
    rnd = random.Random(5)
    small = [bytes(rnd.randrange(LO, HI) for _ in range(8)) for _ in range(6)]
    big = [bytes(v for v in row for _ in range(3)) for row in small for _ in range(3)]
    out = SL.menu_hd_resample(big, 24, 18, bytes(pal), -1, 3, 1, 8, 6, canvas, LO, HI, lut_for(0, LO, HI))
    assert [bytes(r) for r in out] == small
