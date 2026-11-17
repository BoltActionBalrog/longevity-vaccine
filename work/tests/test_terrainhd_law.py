"""uimod terrainhd_law.h (C++) vs scaling_laws.terrain_hd_* (the source of truth), exactly, and the facts the laws
rest on: PRACX's deepest zoom per screen, the one session level, the UV law.

The port runs as one process (tests/terrainhd_law_selftest.cpp, every case over stdin; skipped when VS is absent).
The span law is checked on the real rasterizers, and the code-map rule against load_terrain's own code on the
stock RAINFALL.PCX, in test_terrainhd_exact.py.
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


def test_code_map_follows_the_engine_rule_and_samples_block_centres():
    cols = [7, 9, 11]
    x8 = [[(7 if (x // 8 + y // 8) % 2 else 255) for x in range(16)] for y in range(16)]
    x8[4][12] = 11                                                # the centre of 1x block (0, 1)
    assert SL.terrain_hd_code(x8, cols, 9, 8)[0][0] == 9          # 8x: the region as painted; 255 -> background
    assert SL.terrain_hd_code(x8, cols, 9, 1) == [[9, 2], [0, 9]]  # 1x: block centres; 11 -> 2, 7 -> 0
    two = SL.terrain_hd_code(x8, cols, 9, 2)                      # 2x samples (2 + 4j): (4, 12) is not one
    assert two[1][3] == 0 and two[0][0] == 9 and len(two) == 4
    assert SL.terrain_hd_code([[3] * 8] * 8, cols, 9, 1) == [[0]]  # a colour not in the list -> 0


def test_code_map_treats_252_and_253_as_see_through_and_counts_what_it_sampled():
    """load_terrain makes 252 and 253 see-through as well before it builds the maps (Buffer_change_color 0x4521B4):
    they take the background. The census counts the sampled texels of a listed colour and of any other (code 0 without
    a trace in the engine); a piece is supplied only when it has a listed texel."""
    cols = [7, 9, 11]
    for v in (252, 253, 255):
        assert SL.terrain_hd_code([[v] * 8] * 8, cols, 9, 1) == [[9]]
        assert SL.terrain_hd_code_census([[v] * 8] * 8, cols, 1) == (0, 0)
    x8 = [[11 if x < 8 else 3 for x in range(16)] for y in range(16)]
    assert SL.terrain_hd_code_census(x8, cols, 1) == (2, 2)
    assert SL.terrain_hd_code_census(x8, cols, 2) == (8, 8)
    assert SL.terrain_hd_code_census([[254] * 8] * 8, cols, 1) == (0, 1)   # blanked with the frame: not supplied


def test_code_map_samples_pixel_half_s_of_each_block():
    """The sampled pixel of each s x s block (s = 8 / k) is (s // 2, s // 2): (1, 1) of a 2 x 2 block at 4x, (2, 2)
    of a 4 x 4 block at 2x, (4, 4) of the 8 x 8 block at 1x -- half a pack pixel down and right of the true centre."""
    cols = [7, 9, 11]
    for k, s in ((4, 2), (2, 4), (1, 8)):
        for y in range(s):
            for x in range(s):
                x8 = [[3] * 8 for _ in range(8)]
                x8[y][x] = 9
                want = 1 if (x, y) == (s // 2, s // 2) else 0
                assert SL.terrain_hd_code(x8, cols, 0, k)[0][0] == want, (k, x, y)


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
        region = [[rnd.choice(cols + [255, 254, 253, 252, 3]) for _ in range(8 * n)] for _ in range(8 * n)]
        blob = bytes([len(cols)] + cols + [bg] + [v for row in region for v in row])
        cases.append(f"code {n} {k} " + blob.hex())
        listed, unlisted = SL.terrain_hd_code_census(region, cols, k)
        want.append("".join(f"{v:02x}" for row in SL.terrain_hd_code(region, cols, bg, k) for v in row)
                    + f" {listed} {unlisted}")
    got = run(port, cases)
    bad = [(c[:40], g[:40], w[:40]) for c, g, w in zip(cases, got, want) if g != w]
    assert not bad, bad[:5]
