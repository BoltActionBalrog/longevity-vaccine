"""uimod basehd_law.h (C++) vs scaling_laws.base_hd_sprite_size / palette_box_shrink (the source of truth), exactly.

Builds tests/basehd_selftest.cpp with the VS x86 toolchain (skipped when VS is absent). The law-only tests run anyway.
"""
from __future__ import annotations

import pathlib
import random
import struct
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402
import scaling_laws as SL  # noqa: E402

KEY, SHADOW = 9, 246   # load_faction_art's transparency key; the base sheets' shadow / marker index


def synth(sw, sh, seed):
    """A base-like index image: key background, a shadow blob, a dithered body (two near colours alternating) with
    scattered dark outliers -- the case the most-frequent-index rule got wrong."""
    rnd = random.Random(seed)
    rgb = [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(256)]
    src = []
    for y in range(sh):
        row = []
        for x in range(sw):
            cx, cy = (x - sw / 2) / (sw / 2), (y - sh / 2) / (sh / 2)
            if cx * cx + cy * cy > 0.8:
                v = KEY
            elif cx > 0.5 and cy > 0.3:
                v = SHADOW
            elif rnd.random() < 0.08:
                v = 10 + rnd.randrange(5)               # dark outliers
            else:
                v = 100 + ((x + y) & 1) + (x * 3 // sw) * 4   # dithered bands
            row.append(v)
        src.append(row)
    return src, rgb


def rgbq(rgb):
    out = bytearray(1024)
    for i, (r, g, b) in enumerate(rgb):
        out[i * 4], out[i * 4 + 1], out[i * 4 + 2] = b, g, r
    return bytes(out)


# ---- the law itself ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("num,den", [(16, 16), (22, 16), (25, 16), (40, 16), (3, 2), (5, 7), (1, 1)])
def test_size_is_the_engines_truncation(num, den):
    w, h = SL.base_hd_sprite_size(100, 75, num, den)
    assert (w, h) == (int(100 * (num / den) + 1e-9), int(75 * (num / den) + 1e-9))
    if num == den:
        assert (w, h) == (100, 75)                        # identity at the unscaled draw


def test_shrink_keeps_keys_and_never_invents_an_index():
    src, rgb = synth(80, 60, 1)
    out = SL.palette_box_shrink(src, 21, 17, rgb)
    present = {v for row in src for v in row}
    assert all(v in present for row in out for v in row)
    assert out[0][0] == KEY and out[-1][0] == KEY         # corners are background


def test_shrink_beats_the_dark_outliers():
    """A footprint that is mostly a dithered colour with a dark speck must not pick the speck."""
    rgb = [(i, i, i) for i in range(256)]
    src = [[200, 202, 200, 202], [202, 200, 202, 12], [200, 202, 200, 202], [202, 200, 202, 200]]
    assert SL.palette_box_shrink(src, 1, 1, rgb) in ([[200]], [[202]])


def test_special_wins_only_over_all_colour_together():
    rgb = [(i, i, i) for i in range(256)]
    assert SL.palette_box_shrink([[KEY, KEY, 50, 60]], 1, 1, rgb) == [[50]] or \
        SL.palette_box_shrink([[KEY, KEY, 50, 60]], 1, 1, rgb) == [[60]]   # tie: colours win
    assert SL.palette_box_shrink([[KEY, KEY, KEY, 60]], 1, 1, rgb) == [[KEY]]


def test_enlarge_is_nearest():
    rgb = [(i, i, i) for i in range(256)]
    assert SL.palette_box_shrink([[50, 60]], 4, 1, rgb) == [[50, 50, 60, 60]]


# ---- the C++ port, exactly ---------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "basehd_selftest.cpp", "basehd_selftest_", "/Oi /GL")   # the DLL's codegen


def run_port(exe, src, rgb, dw, dh, num, den):
    sh, sw = len(src), len(src[0])
    pitch = sw + 3                                        # a pitch wider than the row, like the engine's buffers
    body = bytearray(pitch * sh)
    for y, row in enumerate(src):
        body[y * pitch:y * pitch + sw] = bytes(row)
    with tempfile.TemporaryDirectory(prefix="bhd_") as t:
        d = pathlib.Path(t)
        (d / "in.bin").write_bytes(struct.pack("<7i", sw, sh, pitch, dw, dh, num, den) + rgbq(rgb) + bytes(body))
        subprocess.run([str(exe), str(d / "in.bin"), str(d / "out.bin")], check=True)
        raw = (d / "out.bin").read_bytes()
    ow, oh = struct.unpack_from("<2i", raw)
    px = raw[8:]
    return (ow, oh), [list(px[j * dw:(j + 1) * dw]) for j in range(dh)]


@pytest.mark.parametrize("sw,sh", [(80, 60), (160, 120), (37, 29)])
@pytest.mark.parametrize("num,den", [(16, 16), (22, 16), (25, 16), (40, 16), (7, 64), (90, 16)])
def test_port_matches_law(exe, sw, sh, num, den):
    src, rgb = synth(sw, sh, seed=sw * 100 + num)
    dw, dh = SL.base_hd_sprite_size(sw, sh, num, 128)     # shrink AND enlarge targets from one table
    dw, dh = max(dw, 1), max(dh, 1)
    size, out = run_port(exe, src, rgb, dw, dh, num, den)
    assert size == SL.base_hd_sprite_size(sw, sh, num, den)
    assert out == SL.palette_box_shrink(src, dw, dh, rgb)
