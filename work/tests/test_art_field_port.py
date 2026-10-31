"""uimod portrait_law.h FieldEnlarge (C++) vs scaling_laws.art_field_enlarge (the source of truth), bit for bit.

Builds tests/art_field_selftest.cpp with the VS x86 toolchain (skipped when VS is absent)."""
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
from test_scaling_art_field import load_picture  # noqa: E402

pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")


@pytest.fixture(scope="module")
def exe():
    return cpp_harness.build(ROOT / "tests" / "art_field_selftest.cpp", "art_field_selftest_", "/Oi /GL")   # the DLL's codegen


def run_port(exe, src, pitch, sw, sh, key, pal, num, den=16, y0=0):
    with tempfile.TemporaryDirectory(prefix="af_") as t:
        d = pathlib.Path(t)
        (d / "in.bin").write_bytes(struct.pack("<7i", sw, sh, pitch, key, num, den, y0) + bytes(pal) + bytes(src))
        subprocess.run([str(exe), str(d / "in.bin"), str(d / "out.bin")], check=True)
        raw = (d / "out.bin").read_bytes()
    ok, dw, dh = struct.unpack_from("<3i", raw)
    if not ok:
        return None
    vals = struct.unpack_from(f"<{dw * dh}i", raw, 12)
    return dw, dh, [[None if v < 0 else v for v in vals[j * dw:(j + 1) * dw]] for j in range(dh)]


def synth(sw, sh, pitch, seed, key=9):
    rnd = random.Random(seed)
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2] = rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)
    src = bytearray(pitch * sh)
    for y in range(sh):
        for x in range(sw):
            if y in (0, sh - 1) and x in (0, sw - 1):
                v = key
            elif y in (0, sh - 1) or x in (0, sw - 1):
                v = 25
            elif x < sw // 3:
                v = 60 if y & 1 else 61                 # a flat scanlined band: the exact-texel path
            else:
                v = 10 + (x * 7 + (y // 2) * 13 + (y & 1) * 90 + rnd.randrange(6)) % 236
            src[y * pitch + x] = v
    return src, pal


@pytest.mark.parametrize("g", [17, 22, 25, 40])
@pytest.mark.parametrize("sw,sh,pitch", [(32, 40, 32), (40, 61, 44), (53, 32, 53), (64, 33, 70)])
@pytest.mark.parametrize("key", [9, 0x100])
def test_port_matches_law_synthetic(exe, g, sw, sh, pitch, key):
    src, pal = synth(sw, sh, pitch, seed=g * 1000 + sw)
    want = SL.art_field_enlarge(bytes(src), pitch, sw, sh, key, bytes(pal), g)
    assert want is not None
    assert run_port(exe, src, pitch, sw, sh, key, pal, g) == want


@pytest.mark.parametrize("g", [22, 25, 40])
@pytest.mark.parametrize("y0", [1, 2, 3, -3])                           # 2: an odd phase at g = 22 (jt = 1)
def test_port_phase_follows_the_dest_row(exe, g, y0):
    """The fields sit on the dest buffer's stripe grid (ScanPhase): the port at dest row y0, bit for bit."""
    sw, sh, pitch = 40, 61, 44
    src, pal = synth(sw, sh, pitch, seed=g + y0)
    want = SL.art_field_enlarge(bytes(src), pitch, sw, sh, 9, bytes(pal), g, 16, y0)
    assert want is not None and want != SL.art_field_enlarge(bytes(src), pitch, sw, sh, 9, bytes(pal), g, 16, y0 + SL.art_scan_rows(g))
    assert run_port(exe, src, pitch, sw, sh, 9, pal, g, y0=y0) == want


@pytest.mark.parametrize("args", [(40, 60, 9, 16), (31, 60, 9, 25), (60, 31, 9, 25), (9, 147, 9, 25)])
def test_port_declines_like_the_law(exe, args):
    sw, sh, key, g = args
    src, pal = synth(sw, sh, sw, seed=1)
    assert SL.art_field_enlarge(bytes(src), sw, sw, sh, key, bytes(pal), g) is None
    assert run_port(exe, src, sw, sw, sh, key, pal, g) is None


def test_port_declines_a_keyed_hole(exe):
    src, pal = synth(48, 40, 48, seed=3)
    src[20 * 48 + 30] = 9
    assert SL.art_field_enlarge(bytes(src), 48, 48, 40, 9, bytes(pal), 25) is None
    assert run_port(exe, src, 48, 48, 40, 9, pal, 25) is None


@pytest.mark.parametrize("name,g", [("drone", 25), ("facblt", 22), ("mindworm", 25), ("council", 40)])
def test_port_matches_law_real_pictures(exe, name, g):
    src, sw, sh, pal = load_picture(name)
    want = SL.art_field_enlarge(src, sw, sw, sh, 9, pal, g)
    assert want is not None
    assert run_port(exe, src, sw, sw, sh, 9, pal, g) == want
