"""uimod terrainhd_law.h (C++) vs scaling_laws.terrain_hd_* (the source of truth), exactly, and the facts the laws
rest on: PRACX's deepest zoom per screen, the one session level, the UV law.

The port runs as one process (tests/terrainhd_law_selftest.cpp, every case over stdin; skipped when VS is absent).
The UV offset is measured on the real Texture_draw_2 in test_terrainhd_uv_measured.py.
"""
from __future__ import annotations

import pathlib
import random
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402
import scaling_laws as SL  # noqa: E402

SCREENS = [(640, 480), (800, 600), (1024, 768), (1280, 720), (1280, 1024), (1366, 768), (1600, 900), (1600, 1200),
           (1920, 1080), (1920, 1200), (2560, 1080), (2560, 1440), (2560, 1600), (3440, 1440), (3840, 1080),
           (3840, 1600), (3840, 2160), (5120, 1440), (5120, 2880), (7680, 4320)]


def test_pracx_zoom_tile_and_level_at_known_screens():
    assert SL.terrain_hd_max_zoom(3840, 2160) == 72          # the review's figure (PRACX stops at 72 at 4K)
    assert SL.terrain_hd_max_zoom(1920, 1080) == 30
    assert SL.terrain_hd_max_zoom(3840, 1080) == 56
    # the tile is 8i px wide: 96 at the default zoom; 448 at 3840x1080's deepest zoom, measured in game (PRACX +
    # Thinker, wheel and key alike); the review's table for the rest
    assert SL.terrain_hd_tile_px(0) == 96
    screens = ((1024, 768), (1280, 1024), (1600, 1200), (1920, 1080), (2560, 1440), (3440, 1440), (3840, 1080),
               (3840, 2160))
    assert [SL.terrain_hd_tile_px(SL.terrain_hd_max_zoom(w, h)) for w, h in screens] == \
        [152, 184, 232, 288, 376, 496, 448, 552]
    assert [SL.terrain_hd_level(w, h) for w, h in screens] == [2, 4, 4, 4, 8, 8, 8, 8]


def test_level_keeps_a_texel_per_pixel_across_the_real_tile_or_is_capped():
    for w, h in SCREENS:
        t = SL.terrain_hd_tile_px(SL.terrain_hd_max_zoom(w, h))
        k = SL.terrain_hd_level(w, h)
        assert k in (2, 4, 8)
        need = t / (55 * 2 ** 0.5)                            # texel steps across the tile's diagonal per pixel
        assert k >= need or k == SL.TERRAIN_HD_MAX_LEVEL, (w, h, t, k)
        if k > 2:
            assert need > k // 2, (w, h)                      # the smallest level that covers it


def test_span_law_samples_the_block_of_the_stock_texel():
    """k * (u0 + n du) lies in the k x k block of stock's texel for every sample, and fits 32 bits: the largest span
    coordinate at 8x is 56 * 8 << 16 (u, v) and |du| is at most a texture width per pixel."""
    rnd = random.Random(3)
    for k in (1, 2, 4, 8):
        for _ in range(20000):
            u0, du, n = rnd.randrange(0, 56 << 16), rnd.randrange(-(56 << 16), 56 << 16), rnd.randrange(0, 600)
            stock = u0 + n * du
            hd = SL.terrain_hd_span(u0, k) + n * SL.terrain_hd_span(du, k)
            assert hd >> 16 >> (k.bit_length() - 1) == stock >> 16
    assert SL.terrain_hd_span(56 << 16, 8) < 2 ** 31


def test_code_map_follows_the_engine_rule_and_samples_block_centres():
    cols = [7, 9, 11]
    x8 = [[(7 if (x // 8 + y // 8) % 2 else 255) for x in range(16)] for y in range(16)]
    x8[4][12] = 11                                                # the centre of 1x block (0, 1)
    assert SL.terrain_hd_code(x8, cols, 9, 8)[0][0] == 9          # 8x: the region as painted; 255 -> background
    assert SL.terrain_hd_code(x8, cols, 9, 1) == [[9, 2], [0, 9]]  # 1x: block centres; 11 -> 2, 7 -> 0
    two = SL.terrain_hd_code(x8, cols, 9, 2)                      # 2x samples (2 + 4j): (4, 12) is not one
    assert two[1][3] == 0 and two[0][0] == 9 and len(two) == 4
    assert SL.terrain_hd_code([[3] * 8] * 8, cols, 9, 1) == [[0]]  # a colour not in the list -> 0


def test_nearest_is_blocks_of_stock():
    src = [[1, 2], [3, 4]]
    assert SL.terrain_hd_nearest(src, 2) == [[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 4, 4], [3, 3, 4, 4]]


@pytest.fixture(scope="module")
def port():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "terrainhd_law_selftest.cpp", "terrainhd_law_")


def run(port, lines):
    r = subprocess.run([str(port)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    assert len(out) == len(lines)
    return out


def test_port_matches_the_python(port):
    cases, want = [], []
    for w, h in SCREENS + [(w, h) for w in range(320, 8000, 97) for h in (240, 600, 1080, 2160, 4320)]:
        cases += [f"zoom {w} {h}", f"level {w} {h}"]
        want += [str(SL.terrain_hd_max_zoom(w, h)), str(SL.terrain_hd_level(w, h))]
    for z in range(-14, 402, 2):
        cases.append(f"tile {z} 0")
        want.append(str(SL.terrain_hd_tile_px(z)))
    for k in (1, 2, 4, 8):
        for c in (0, 1, 0x8000, 27 << 16, (55 << 16) + 0x8000, -(3 << 16), 56 << 16):
            cases.append(f"span {c} {k}")
            want.append(str(SL.terrain_hd_span(c, k)))
    rnd = random.Random(7)
    for n, k in ((1, 2), (3, 4), (56, 2), (56, 4)):
        img = [[rnd.randrange(256) for _ in range(n)] for _ in range(n)]
        cases.append(f"nearest {n} {k} " + "".join(f"{v:02x}" for row in img for v in row))
        want.append("".join(f"{v:02x}" for row in SL.terrain_hd_nearest(img, k) for v in row))
    for n, k in ((2, 8), (3, 4), (5, 2), (6, 4)):
        cols = rnd.sample(range(255), 9)
        bg = rnd.choice((0, 9))
        region = [[rnd.choice(cols + [255, 254, 3]) for _ in range(8 * n)] for _ in range(8 * n)]
        blob = bytes([len(cols)] + cols + [bg] + [v for row in region for v in row])
        cases.append(f"code {n} {k} " + blob.hex())
        want.append("".join(f"{v:02x}" for row in SL.terrain_hd_code(region, cols, bg, k) for v in row))
    got = run(port, cases)
    bad = [(c[:40], g[:40], w[:40]) for c, g, w in zip(cases, got, want) if g != w]
    assert not bad, bad[:5]
