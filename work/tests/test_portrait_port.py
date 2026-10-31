"""uimod portrait_law.h (C++) vs scaling_laws.portrait_enlarge (the source of truth), bit for bit.

Builds tests/portrait_selftest.cpp with the VS x86 toolchain (skipped when VS is absent) and feeds it
synthetic framed/scanlined art and the real leader portraits at g = 17/22/25/40."""
from __future__ import annotations

import os
import pathlib
import random
import struct
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

VCVARS = pathlib.Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat")
SRC = ROOT / "tests" / "portrait_selftest.cpp"
pytestmark = pytest.mark.skipif(not VCVARS.exists(), reason="Visual Studio x86 toolchain not available")


@pytest.fixture(scope="module")
def exe():
    # the DLL's Release codegen (/Oi /GL): the Lanczos taps go through sin(), so test the port as it ships
    sys.path.insert(0, str(ROOT / "tests"))
    import cpp_harness
    return cpp_harness.build(SRC, "portrait_selftest_", "/Oi /GL")


def run_port(exe, src, pitch, sw, sh, key, pal, num, den=16, y0=0):
    d = pathlib.Path(tempfile.mkdtemp(prefix="pp_"))
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
            else:
                v = 10 + (x * 7 + (y // 2) * 13 + (y & 1) * 90 + rnd.randrange(6)) % 236
            src[y * pitch + x] = v
    return src, pal


@pytest.mark.parametrize("g", [17, 22, 25, 40])
@pytest.mark.parametrize("sw,sh,pitch", [(32, 40, 32), (40, 61, 44), (37, 40, 37)])   # widths >= PORTRAIT_MIN_W
@pytest.mark.parametrize("y0", [0, 2, -3])                             # on / off the grid; -3 = clipped replaced draw
def test_port_matches_law_synthetic(exe, g, sw, sh, pitch, y0):
    src, pal = synth(sw, sh, pitch, seed=g * 1000 + sw)
    want = SL.portrait_enlarge(bytes(src), pitch, sw, sh, 9, bytes(pal), g, 16, y0)
    assert want is not None
    assert run_port(exe, src, pitch, sw, sh, 9, pal, g, y0=y0) == want


@pytest.mark.parametrize("args", [(40, 20, 9, 25), (40, 60, 0x100, 25), (40, 60, 9, 16), (31, 60, 9, 25), (9, 147, 9, 25)])   # last = the diplomacy colour bar
def test_port_declines_like_the_law(exe, args):
    sw, sh, key, g = args
    src, pal = synth(sw, sh, sw, seed=1)
    assert SL.portrait_enlarge(bytes(src), sw, sw, sh, key, bytes(pal), g) is None
    assert run_port(exe, src, sw, sw, sh, key, pal, g) is None


@pytest.mark.parametrize("fac", ["gaians", "morgan", "usurper"])
@pytest.mark.parametrize("g", [22, 25])
def test_port_matches_law_real_portraits(exe, fac, g):
    from PIL import Image
    pcx = config.game_dir(required=False)
    if not pcx or not (pcx / f"{fac}.pcx").exists():
        pytest.skip("game art not available")
    im = Image.open(pcx / f"{fac}.pcx")
    p = im.getpalette()[:768]
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2] = p[i * 3 + 2], p[i * 3 + 1], p[i * 3]
    cell = im.crop((304, 457, 435, 614))
    src = cell.tobytes()
    want = SL.portrait_enlarge(src, 131, 131, 157, 255, bytes(pal), g)
    got = run_port(exe, src, 131, 131, 157, 255, pal, g)
    assert got == want
    # the look's hard requirement: strictly alternating scanlines art_scan_rows(g) device rows thick (the chrome's
    # thickness), on the dest buffer's stripe grid (y0 = 0: stripes open at device rows that are multiples of T;
    # mean luma by stripe)
    dw, dh, rows = want
    t = SL.art_scan_rows(g)
    crow = [SL.nn_center_index(j, dh, 157) for j in range(dh)]
    jt = next(j for j in range(dh) if crow[j] > 0)
    jb = next(j for j in range(dh - 1, -1, -1) if crow[j] < 156) + 1
    j0 = jt + (-jt) % t                                               # the first interior row opening a grid stripe
    lum = []
    for k in range((jb - j0) // t):
        vals = [pal[v * 4 + 2] * 77 + pal[v * 4 + 1] * 150 + pal[v * 4] * 29
                for r in rows[j0 + k * t:j0 + (k + 1) * t] for v in r[4:-4] if v is not None]
        lum.append(sum(vals) / len(vals))
    up = [lum[i] > (lum[i - 1] + lum[i + 1]) / 2 for i in range(1, len(lum) - 1)]
    assert all(up[i] != up[i + 1] for i in range(len(up) - 1))


def _pcx_cell(fac, box):
    from PIL import Image
    pcx = config.game_dir(required=False)
    if not pcx or not (pcx / f"{fac}.pcx").exists():
        pytest.skip("game art not available")
    im = Image.open(pcx / f"{fac}.pcx")
    p = im.getpalette()[:768]
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2] = p[i * 3 + 2], p[i * 3 + 1], p[i * 3]
    cell = im.crop(box)
    return cell.tobytes(), cell.size[0], cell.size[1], pal


@pytest.mark.parametrize("g", [22, 25, 40])
def test_one_row_accents_are_not_smeared(exe, g):
    """spartans.pcx small council portrait (the combat console's Santiago): pupils / nostrils / mouth corners are
    single black texels, often one row tall.  The de-scanline must keep both fields' own detail -- rebuilding the
    dark rows from the bright ones turned every such accent into a three-row blotch (user 2026-09-21)."""
    src, sw, sh, pal = _pcx_cell("spartans", (89, 458, 184, 571))
    want = SL.portrait_enlarge(src, sw, sw, sh, 255, bytes(pal), g)
    assert run_port(exe, src, sw, sw, sh, 255, pal, g) == want
    dw, dh, rows = want
    lum = lambda v: (77 * pal[v * 4 + 2] + 150 * pal[v * 4 + 1] + 29 * pal[v * 4]) >> 8
    # face box (native 25..70 x 30..75): black device pixels must not outgrow the native black texel share
    native = sum(1 for y in range(30, 75) for x in range(25, 70) if lum(src[y * sw + x]) < 16)
    dev = sum(1 for j in range(30 * g // 16, 75 * g // 16) for i in range(25 * g // 16, 70 * g // 16)
              if rows[j][i] is not None and lum(rows[j][i]) < 16)
    assert dev <= native * (g * g) // 256 * 3 // 2 + 8, (native, dev)


sys.path.insert(0, str(ROOT / "tests"))
import test_scaling_portrait_gate as GATE  # noqa: E402  (the real-art cell tables)


def _ring_keyed(sw, sh, x, y):
    src, pal = synth(sw, sh, sw, seed=7, key=255)
    src[y * sw + x] = 255
    return src, pal


@pytest.mark.parametrize("xy", [(5, 0), (38, 59), (0, 1), (39, 58)])   # top / bottom / left / right, off the corners
def test_port_declines_a_keyed_ring_like_the_law(exe, xy):
    src, pal = _ring_keyed(40, 60, *xy)
    assert SL.portrait_enlarge(bytes(src), 40, 40, 60, 255, bytes(pal), 40) is None
    assert run_port(exe, src, 40, 40, 60, 255, pal, 40) is None


def test_port_takes_interior_key_like_the_law(exe):
    src, pal = synth(40, 60, 40, seed=8, key=255)
    src[30 * 40 + 20] = 255                                           # angels.pcx carries such stray key texels
    want = SL.portrait_enlarge(bytes(src), 40, 40, 60, 255, bytes(pal), 25)
    assert want is not None and run_port(exe, src, 40, 40, 60, 255, pal, 25) == want


@pytest.mark.parametrize("fac,kind,which", [(f, "slot", s) for f in GATE.FACTIONS for s in GATE.SLOTS] +
                         [(f, "logo", c) for f in GATE.FACTIONS for c in (0, 1)])
def test_port_gate_matches_law_on_real_art(exe, fac, kind, which):
    """Every leader slot and both council logo cells (normal / hover) of every faction sheet: the C++ gate takes
    exactly what the law takes -- every portrait, no logo (the Spartans' 62-wide hexagon is the one logo the shape
    gate alone would take)."""
    im = GATE._sheet(fac)
    if kind == "slot":
        x, y, w, h = GATE.SLOTS[which]
        src = im.crop((x, y, x + w, y + h)).tobytes()
    else:
        src, w, h = GATE.trimmed(im, GATE.LOGO_CELLS[which])
    p = im.getpalette()[:768]
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2] = p[i * 3 + 2], p[i * 3 + 1], p[i * 3]
    law = SL.portrait_applies(src, w, w, h, 255, 17)
    assert law == (kind == "slot")
    assert (run_port(exe, src, w, w, h, 255, pal, 17) is not None) == law
