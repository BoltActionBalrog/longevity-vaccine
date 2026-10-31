"""Replacement portraits: scaling_laws portrait_prereduce / portrait_frame_rect / portrait_bake /
portrait_enlarge_rgb (the source of truth) -- their properties, and uimod portrait_law.h against them bit for bit.

Synthetic images only in the committed vectors.  The real-art checks use the user's HD pack source
(dist\\portraits-hd-src, gitignored) and the game's PCX; both skip when absent -- no art-derived fixture is ever
committed (work\\tests is published)."""
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
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

SRC = ROOT / "tests" / "portrait_rgb_selftest.cpp"
HD_SRC = ROOT.parent / "dist" / "portraits-hd-src"
#: the DLL's Release codegen (uimod.vcxproj: MaxSpeed + IntrinsicFunctions + WholeProgramOptimization): the Lanczos
#: taps go through sin(), so the self-test must be built the way the shipped port is
DLL_FLAGS = "/Oi /GL"
needs_vs = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")
OVERLAY, MEAN, OFF = SL.PORTRAIT_SCAN_OVERLAY, SL.PORTRAIT_SCAN_MEAN, SL.PORTRAIT_SCAN_OFF


# ---------------------------------------------------------------------------------------------- synthetic inputs

def synth_art(sw, sh, seed, key=9, bright=0):
    """Framed, scanlined 8-bit art (frame index 25, key corners) + a random RGBQUAD palette."""
    rnd = random.Random(seed)
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2] = rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)
    # make the scanline fields measurable: odd indices dark copies of even ones
    for i in range(10, 246, 2):
        for c in range(3):
            pal[(i + 1) * 4 + c] = pal[i * 4 + c] * 3 // 4
    src = bytearray(sw * sh)
    for y in range(sh):
        for x in range(sw):
            if y in (0, sh - 1) and x in (0, sw - 1):
                v = key
            elif y in (0, sh - 1) or x in (0, sw - 1):
                v = 25
            else:
                base = 10 + 2 * ((x * 3 + y * 5 + rnd.randrange(4)) % 118)
                v = base + (0 if ((y - 1) & 1) == bright else 1)
            src[y * sw + x] = v
    return bytes(src), bytes(pal)


def synth_rgb(w, h, seed):
    rnd = random.Random(seed)
    out = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * 3
            out[o] = (x * 255 // max(w - 1, 1) + rnd.randrange(24)) & 255
            out[o + 1] = (y * 255 // max(h - 1, 1)) & 255
            out[o + 2] = ((x ^ y) * 7 + rnd.randrange(16)) & 255
    return bytes(out)


def dark_rows(rows, pal):
    """Device rows (inside a 3-px margin) whose mean luma is below both neighbours'."""
    lum = []
    for r in rows:
        vals = [77 * pal[v * 4 + 2] + 150 * pal[v * 4 + 1] + 29 * pal[v * 4] for v in r[3:-3] if v is not None]
        lum.append(sum(vals) / max(len(vals), 1))
    return {j for j in range(4, len(lum) - 4) if lum[j] < lum[j - 1] and lum[j] < lum[j + 1]}


# ---------------------------------------------------------------------------------------------- law properties

@pytest.mark.parametrize("w,h", [(1121, 1353), (1086, 1448), (1191, 1321), (1600, 900), (500, 500), (94, 113)])
@pytest.mark.parametrize("tw,th", [(94, 113), (116, 142), (129, 155), (162, 196)])
def test_frame_rect_is_a_uniform_cover_crop(w, h, tw, th):
    x, y, cw, ch = SL.portrait_frame_rect(w, h, tw, th)
    assert 0 <= x and 0 <= y and x + cw <= w and y + ch <= h
    assert cw == w or ch == h                                    # cover: one axis uses the whole image
    assert abs(cw * th - ch * tw) <= max(tw, th)                 # aspect within one pixel: never per-axis stretch
    if cw < w:
        assert x == (w - cw) // 2                                # too wide: centred
    if ch < h:
        assert y == (h - ch) // 3                                # too tall: a third of the excess above


def test_prereduce_factor_and_box_average():
    assert SL.portrait_prereduce_factor(1121, 1353) == 1
    assert SL.portrait_prereduce_factor(4096, 4096) == 3
    assert SL.portrait_prereduce_factor(1537, 10) == 2
    img = synth_rgb(3100, 40, 7)
    out, nw, nh = SL.portrait_prereduce(img, 3100, 40)
    assert (nw, nh) == (3100 // 3, 40 // 3)
    # first pixel = rounded mean of the top-left 3x3 block
    blk = [img[(yy * 3100 + xx) * 3] for yy in range(3) for xx in range(3)]
    assert out[0] == (sum(blk) + 4) // 9


@pytest.mark.parametrize("bright", [0, 1])
def test_bake_keeps_the_vanilla_scanline_phase(bright):
    sw, sh = 96, 115
    src, pal = synth_art(sw, sh, seed=3 + bright, bright=bright)
    b, _ = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    assert b == bright
    rgb = bytes([150, 150, 150]) * (300 * 360)
    on = SL.portrait_bake(sw, sh, pal, rgb, 300, 360, OVERLAY, b, _)
    off = SL.portrait_bake(sw, sh, pal, rgb, 300, 360, OFF, b, _)
    assert len(on) == sh - 2 and len(on[0]) == sw - 2
    assert all(SL.PORTRAIT_PAL_LO <= v <= SL.PORTRAIT_PAL_HI for r in on for v in r)
    lum = lambda row: sum(77 * pal[v * 4 + 2] + 150 * pal[v * 4 + 1] + 29 * pal[v * 4] for v in row) / len(row)
    # interior row y is art row y+1; vanilla bright rows are (y & 1) == bright
    ev = sum(lum(on[y]) for y in range(0, sh - 2, 2)) / ((sh - 1) // 2)
    od = sum(lum(on[y]) for y in range(1, sh - 2, 2)) / ((sh - 2) // 2)
    assert (ev > od) == (bright == 0)
    ev0 = sum(lum(off[y]) for y in range(0, sh - 2, 2)) / ((sh - 1) // 2)
    od0 = sum(lum(off[y]) for y in range(1, sh - 2, 2)) / ((sh - 2) // 2)
    assert abs(ev0 - od0) < abs(ev - od) / 4                      # off = no fields


@pytest.mark.parametrize("g", [22, 25, 40])
def test_enlarge_rgb_matches_portrait_enlarge_frame_and_phase(g):
    sw, sh = 96, 115
    src, pal = synth_art(sw, sh, seed=11)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    want = SL.portrait_enlarge(src, sw, sw, sh, 9, pal, g)
    rgb = synth_rgb(200, 240, 5)
    got = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, rgb, 200, 240, OVERLAY, b, r)
    assert got[:2] == want[:2]
    dw, dh, wr = want
    _, _, gr = got
    # frame + key identical (edge-pinned NN of the art), interior replaced
    for j in range(dh):
        for i in range(dw):
            if wr[j][i] is None or gr[j][i] is None or not (0 < SL.nn_center_index(j, dh, sh) < sh - 1
                                                             and 0 < SL.nn_center_index(i, dw, sw) < sw - 1):
                assert wr[j][i] == gr[j][i], (j, i)
    # the scanlines land on the same device rows as the vanilla smooth enlarge
    flat = bytes([150, 150, 150]) * (200 * 240)
    gf = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, flat, 200, 240, OVERLAY, b, r)[2]
    crow = [SL.nn_center_index(j, dh, sh) for j in range(dh)]
    jb = next(j for j in range(dh - 1, -1, -1) if crow[j] < sh - 1) + 1
    # the local-minimum heuristic is unreliable in the last few stripes (dark_rows' own 4-row margin meets the grid's
    # partial bottom stripe); the exact row classes are pinned by test_enlarge_rgb_scanlines_sit_on_the_dest_grid
    cut = jb - 3 * SL.art_scan_rows(g)
    dg, dwr = {j for j in dark_rows(gf, pal) if j < cut}, dark_rows(wr, pal)
    assert dg and dg <= dwr | {j + 1 for j in dwr} | {j - 1 for j in dwr}
    assert dg & dwr


@pytest.mark.parametrize("g", [17, 22, 25, 40])
@pytest.mark.parametrize("framed", [True, False])
@pytest.mark.parametrize("y0", [0, 1, 3, -2])
def test_enlarge_rgb_scanlines_sit_on_the_dest_grid(g, framed, y0):
    """Option B stage 2 (2026-10-06): a replacement portrait drawn at dest-buffer row y0 is dark on device row j
    iff grid stripe ((y0 + j) // T) & 1 is not the vanilla art's bright parity -- the chrome's grid, so the
    picture's scanlines continue the panel's."""
    sw, sh = (96, 115) if framed else (118, 144)
    src, pal = synth_art(sw, sh, seed=5 + g)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    flat = bytes([150, 150, 150]) * (200 * 240)
    dw, dh, rows = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, flat, 200, 240, OVERLAY, b, r,
                                           framed=framed, y0=y0)
    t = SL.art_scan_rows(g)
    crow = [SL.nn_center_index(j, dh, sh) for j in range(dh)]
    jt = next(j for j in range(dh) if crow[j] > 0)
    jb = next(j for j in range(dh - 1, -1, -1) if crow[j] < sh - 1) + 1
    lum = lambda row: sum(77 * pal[v * 4 + 2] + 150 * pal[v * 4 + 1] + 29 * pal[v * 4] for v in row[6:-6]) / (len(row) - 12)
    inner = range(jt, jb) if framed else range(dh)
    vals = {j: lum(rows[j]) for j in inner}
    mid = (max(vals.values()) + min(vals.values())) / 2
    assert max(vals.values()) - min(vals.values()) > 40 * 256
    for j in inner:
        assert (vals[j] < mid) == ((((y0 + j) // t) & 1) != b), (j, vals[j], mid)


def test_enlarge_rgb_declines_at_native_below_and_degenerate():
    src, pal = synth_art(40, 50, seed=1)
    rgb = synth_rgb(60, 70, 1)
    assert SL.portrait_enlarge_rgb(src, 40, 40, 50, 9, pal, 16, 16, rgb, 60, 70, OVERLAY, 0, 200) is None
    assert SL.portrait_enlarge_rgb(src, 40, 40, 50, 9, pal, 12, 16, rgb, 60, 70, OVERLAY, 0, 200) is None
    assert SL.portrait_bake(2, 50, pal, rgb, 60, 70, OVERLAY, 0, 200) is None
    assert SL.portrait_bake(40, 50, pal, b"", 0, 70, OVERLAY, 0, 200) is None
    assert SL.portrait_from_rgb(rgb, 60, 70, (0, 0, 0, 70), 10, 10, pal, OVERLAY, 0, 200, 1) is None     # empty crop
    assert SL.portrait_from_rgb(rgb, 60, 70, (30, 0, 40, 70), 10, 10, pal, OVERLAY, 0, 200, 1) is None   # outside
    assert SL.portrait_from_rgb(rgb[:100], 60, 70, (0, 0, 60, 70), 10, 10, pal, OVERLAY, 0, 200, 1) is None  # short
    assert SL.portrait_from_rgb(rgb, 60, 70, (0, 0, 60, 70), 0, 10, pal, OVERLAY, 0, 200, 1) is None     # no target
    assert SL.portrait_frame_rect(100, 0, 94, 113) == (0, 0, 100, 0)


@pytest.mark.parametrize("full", [True, False])
def test_native_art_image_is_mapped_not_resampled(full):
    """A player's edit of the game art (exactly the slot size, with or without the frame) keeps its own pixels:
    nearest colour, no dither, no added scanlines; above native the caller enlarges it like vanilla art."""
    sw, sh = 96, 115
    src, pal = synth_art(sw, sh, seed=4)
    w, h, o = (sw, sh, 1) if full else (sw - 2, sh - 2, 0)
    rgb = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            v = src[(y + 1 - o) * sw + x + 1 - o]
            rgb[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes((pal[v * 4 + 2], pal[v * 4 + 1], pal[v * 4]))
    assert SL.portrait_is_native_art(w, h, sw, sh)
    baked = SL.portrait_bake(sw, sh, pal, bytes(rgb), w, h, OVERLAY, 0, 200)
    want = [[src[(y + 1) * sw + x + 1] for x in range(sw - 2)] for y in range(sh - 2)]
    col = lambda i: (pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2])      # the palette may repeat a colour
    assert [[col(v) for v in r] for r in baked] == [[col(v) for v in r] for r in want]
    assert SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, 40, 16, bytes(rgb), w, h, OVERLAY, 0, 200) is None


def test_mean_mode_keeps_the_mean_and_the_phase():
    import numpy as np
    sw, sh = 96, 115
    src, pal = synth_art(sw, sh, seed=6)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    big = np.full((20, 5, 3), 120, dtype=np.int64)
    SL.portrait_scan_rows(big, 20, MEAN, b, r, 0)
    m = big[:, 0, 0]
    assert abs(m.mean() - 120) <= 1
    dark = [y for y in range(20) if (y & 1) != b]                  # native: the vanilla art's own field
    assert all(m[y] < 120 for y in dark) and all(m[y] > 120 for y in range(20) if y not in dark)


@pytest.mark.parametrize("g", [17, 21, 22, 25, 32, 40, 48])
def test_enlarged_scanlines_are_the_popup_thickness(g):
    """Above native, every scanline is art_scan_rows(g) device rows thick, bright and dark alike, the first
    interior row showing the vanilla bright field (user 2026-10-03: portraits match the popup pictures)."""
    import numpy as np
    t = SL.art_scan_rows(g)
    for b in (0, 1):
        big = np.full((6 * t, 3, 3), 120, dtype=np.int64)
        SL.portrait_scan_rows(big, 6 * t, OVERLAY, b, 128, 0, t)
        dark = [bool(big[y, 0, 0] < 120) for y in range(6 * t)]
        assert dark == [((y // t) & 1) != b for y in range(6 * t)]
        assert all(len(set(dark[k:k + t])) == 1 for k in range(0, 6 * t, t))
    # an unframed device rect starts -jt rows above the interior: the stripes stay on the interior grid
    big = np.full((4 * t + 3, 3, 3), 120, dtype=np.int64)
    SL.portrait_scan_rows(big, 4 * t + 3, OVERLAY, 0, 128, -3, t)
    assert [bool(big[y, 0, 0] < 120) for y in range(4 * t + 3)] == [(((y - 3) // t) & 1) != 0
                                                                    for y in range(4 * t + 3)]


def test_paletteentry_conversion_is_the_rgbquad_the_law_reads():
    rnd = random.Random(2)
    pe = bytes(rnd.randrange(256) for _ in range(1024))
    q = SL.portrait_rgbquad_from_paletteentry(pe)
    for i in range(256):
        assert (q[i * 4 + 2], q[i * 4 + 1], q[i * 4]) == (pe[i * 4], pe[i * 4 + 1], pe[i * 4 + 2])


# ---------------------------------------------------------------------------------------------- C++ port, bit for bit

@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(SRC, "portrait_rgb_selftest_", DLL_FLAGS)


def run(exe, mode, pal=bytes(1024), src=b"", sw=0, sh=0, key=9, num=16, den=16, rgb=b"", w=0, h=0, scan=None,
        y0=0):
    scan = SL.PORTRAIT_SCAN_OVERLAY if scan is None else scan
    with tempfile.TemporaryDirectory(prefix="prgb_") as t:     # inputs may hold art pixels: never leave them behind
        d = pathlib.Path(t)
        (d / "in.bin").write_bytes(struct.pack("<11i", mode, sw, sh, sw, key, num, den, w, h, scan, y0)
                                   + bytes(pal) + bytes(src) + bytes(rgb))
        subprocess.run([str(exe), str(d / "in.bin"), str(d / "out.bin")], check=True)
        return (d / "out.bin").read_bytes()


@needs_vs
@pytest.mark.parametrize("w,h", [(3100, 40), (1600, 1700), (1536, 20), (40, 30)])
def test_port_prereduce(exe, w, h):
    img = synth_rgb(w, h, w + h)
    raw = run(exe, 0, rgb=img, w=w, h=h)
    ow, oh = struct.unpack_from("<2i", raw)
    want, nw, nh = SL.portrait_prereduce(img, w, h)
    assert (ow, oh) == (nw, nh) and raw[8:] == want


@needs_vs
@pytest.mark.parametrize("w,h,tw,th", [(1121, 1353, 162, 196), (1086, 1448, 94, 113), (1191, 1321, 129, 155),
                                       (1600, 900, 116, 142), (500, 500, 94, 113), (7, 3000, 94, 113)])
def test_port_frame_rect(exe, w, h, tw, th):
    raw = run(exe, 1, sw=tw, sh=th, w=w, h=h)
    assert struct.unpack("<4i", raw) == SL.portrait_frame_rect(w, h, tw, th)


@needs_vs
@pytest.mark.parametrize("scan", [1, 2, 0])
@pytest.mark.parametrize("sw,sh,bright,iw,ih", [(96, 115, 0, 300, 360), (118, 144, 1, 250, 170),
                                                  (131, 157, 1, 131, 157), (40, 50, 0, 900, 1100)])
def test_port_bake(exe, sw, sh, bright, iw, ih, scan):
    src, pal = synth_art(sw, sh, seed=sw + bright, bright=bright)
    rgb = synth_rgb(iw, ih, sw)
    raw = run(exe, 2, pal=pal, src=src, sw=sw, sh=sh, rgb=rgb, w=iw, h=ih, scan=scan)
    ok, b, r = struct.unpack_from("<3i", raw)
    assert ok and (b, r) == SL.portrait_scanline_params(src, sw, sw, sh, pal)
    vals = struct.unpack_from(f"<{(sw - 2) * (sh - 2)}i", raw, 12)
    want = SL.portrait_bake(sw, sh, pal, rgb, iw, ih, scan, b, r)
    assert [list(vals[y * (sw - 2):(y + 1) * (sw - 2)]) for y in range(sh - 2)] == want


@needs_vs
@pytest.mark.parametrize("scan", [1, 2])
@pytest.mark.parametrize("g", [17, 22, 25, 40, 45])
@pytest.mark.parametrize("sw,sh,iw,ih", [(96, 115, 300, 360), (164, 198, 700, 520), (96, 115, 40, 50)])  # last: upscale
def test_port_enlarge_rgb(exe, g, sw, sh, iw, ih, scan):
    src, pal = synth_art(sw, sh, seed=g + sw)
    rgb = synth_rgb(iw, ih, g)
    raw = run(exe, 3, pal=pal, src=src, sw=sw, sh=sh, num=g, rgb=rgb, w=iw, h=ih, scan=scan)
    ok, dw, dh = struct.unpack_from("<3i", raw)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    want = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, rgb, iw, ih, scan, b, r)
    assert ok and (dw, dh) == want[:2]
    vals = struct.unpack_from(f"<{dw * dh}i", raw, 12)
    assert [[None if v < 0 else v for v in vals[j * dw:(j + 1) * dw]] for j in range(dh)] == want[2]


@needs_vs
@pytest.mark.parametrize("g", [22, 40])
@pytest.mark.parametrize("framed", [True, False])
@pytest.mark.parametrize("y0", [2, 3, -5])                             # 2: an odd phase at g = 22 (jt = 1)
def test_port_enlarge_rgb_phase_follows_the_dest_row(exe, g, framed, y0):
    """The scanlines sit on the dest buffer's stripe grid (ScanPhase): the port at dest row y0, bit for bit."""
    sw, sh = (96, 115) if framed else (118, 144)
    src, pal = synth_art(sw, sh, seed=g + y0)
    rgb = synth_rgb(300, 360, g)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    flag = 0 if framed else UNFRAMED
    raw = run(exe, 3, pal=pal, src=src, sw=sw, sh=sh, num=g, rgb=rgb, w=300, h=360, scan=OVERLAY | flag, y0=y0)
    ok, dw, dh = struct.unpack_from("<3i", raw)
    want = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, rgb, 300, 360, OVERLAY, b, r, framed=framed, y0=y0)
    assert want != SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, rgb, 300, 360, OVERLAY, b, r, framed=framed,
                                           y0=y0 + SL.art_scan_rows(g))
    vals = struct.unpack_from(f"<{dw * dh}i", raw, 12)
    assert ok and (dw, dh) == want[:2]
    assert [[None if v < 0 else v for v in vals[j * dw:(j + 1) * dw]] for j in range(dh)] == want[2]


@needs_vs
@pytest.mark.parametrize("mode,num,w,h", [(3, 16, 60, 70), (3, 40, 40, 50), (3, 40, 38, 48), (2, 16, 0, 70),
                                          (3, 40, 0, 70)])
def test_port_declines_like_the_law(exe, mode, num, w, h):
    src, pal = synth_art(40, 50, seed=1)
    rgb = synth_rgb(w, h, 1) if w > 0 else b""
    raw = run(exe, mode, pal=pal, src=src, sw=40, sh=50, num=num, rgb=rgb, w=w, h=h)
    ok = struct.unpack_from("<i", raw)[0]
    b, r = SL.portrait_scanline_params(src, 40, 40, 50, pal)
    law = (SL.portrait_bake(40, 50, pal, rgb, w, h, OVERLAY, b, r) if mode == 2 else
           SL.portrait_enlarge_rgb(src, 40, 40, 50, 9, pal, num, 16, rgb, w, h, OVERLAY, b, r))
    assert bool(ok) == (law is not None)
    if mode == 3:
        assert law is None                                       # native, native-art or empty: all decline


@needs_vs
@pytest.mark.parametrize("full", [True, False])
def test_port_native_art_bake(exe, full):
    sw, sh = 96, 115
    src, pal = synth_art(sw, sh, seed=8)
    w, h = (sw, sh) if full else (sw - 2, sh - 2)
    rgb = synth_rgb(w, h, 3)
    raw = run(exe, 2, pal=pal, src=src, sw=sw, sh=sh, rgb=rgb, w=w, h=h)
    vals = struct.unpack_from(f"<{(sw - 2) * (sh - 2)}i", raw, 12)
    assert [list(vals[y * (sw - 2):(y + 1) * (sw - 2)]) for y in range(sh - 2)] == \
        SL.portrait_bake(sw, sh, pal, rgb, w, h, OVERLAY, 0, 200)


# ---------------------------------------------------------------------------------------------- real art (skips)

def _hd(n):
    p = HD_SRC / f"alpha centauri ({n}).png"
    if not p.exists():
        pytest.skip("HD portrait source not present (dist\\portraits-hd-src)")
    from PIL import Image
    im = Image.open(p).convert("RGB")
    return im.tobytes(), im.size[0], im.size[1]


def _slot(fac, box):
    """A slot in the ENGINE's index space (Buffer_load_pcx stores (raw + 10) & 0xFF; key 9) with the sheet's
    palette shifted the same way, so candidates 10..245 are the colours the engine offers."""
    from PIL import Image
    gd = config.game_dir(required=False)
    if not gd or not (gd / f"{fac}.pcx").exists():
        pytest.skip("game art not available")
    im = Image.open(gd / f"{fac}.pcx")
    p = im.getpalette()[:768]
    pal = bytearray(1024)
    for i in range(236):
        k = i + 10
        pal[k * 4], pal[k * 4 + 1], pal[k * 4 + 2] = p[i * 3 + 2], p[i * 3 + 1], p[i * 3]
    cell = im.crop(box)
    return bytes((v + 10) & 0xFF for v in cell.tobytes()), cell.size[0], cell.size[1], bytes(pal)


@needs_vs
@pytest.mark.parametrize("n,fac", [(14, "gaians"), (10, "morgan")])
def test_port_real_hd_bake_and_enlarge(exe, n, fac):
    rgb, w, h = _hd(n)
    rgb, w, h = SL.portrait_prereduce(rgb, w, h)
    src, sw, sh, pal = _slot(fac, (88, 457, 184, 572))          # small council slot incl. its 1-px frame (96x115)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    raw = run(exe, 2, pal=pal, src=src, sw=sw, sh=sh, key=9, rgb=rgb, w=w, h=h)
    vals = struct.unpack_from(f"<{(sw - 2) * (sh - 2)}i", raw, 12)
    assert [list(vals[y * (sw - 2):(y + 1) * (sw - 2)]) for y in range(sh - 2)] == \
        SL.portrait_bake(sw, sh, pal, rgb, w, h, OVERLAY, b, r)
    raw = run(exe, 3, pal=pal, src=src, sw=sw, sh=sh, key=9, num=25, rgb=rgb, w=w, h=h)
    ok, dw, dh = struct.unpack_from("<3i", raw)
    want = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, 25, 16, rgb, w, h, OVERLAY, b, r)
    vals = struct.unpack_from(f"<{dw * dh}i", raw, 12)
    assert [[None if v < 0 else v for v in vals[j * dw:(j + 1) * dw]] for j in range(dh)] == want[2]


# ---------------------------------------------------------------------------------------------- unframed (council)

UNFRAMED = 0x100      # harness flag: the council slots have no 1-px frame (measured on the sheets 2026-10-03)


def test_unframed_bake_replaces_the_whole_sprite():
    """The council slots' edge rows/cols are picture: a replacement covers them too, so no ring of the vanilla
    painting survives around it (user's 4K council shot 2026-10-03)."""
    sw, sh = 96, 115
    src, pal = synth_art(sw, sh, seed=21)
    rgb = bytes([200, 30, 30]) * (300 * 360)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    out = SL.portrait_bake(sw, sh, pal, rgb, 300, 360, OFF, b, r, framed=False)
    assert len(out) == sh and len(out[0]) == sw
    vals = {v for row in out for v in row}
    assert vals and all(SL.PORTRAIT_PAL_LO <= v <= SL.PORTRAIT_PAL_HI for v in vals)
    edge = out[0] + out[-1] + [row[0] for row in out] + [row[-1] for row in out]
    centre = out[sh // 2][sw // 2]
    col = lambda i: (pal[i * 4 + 2], pal[i * 4 + 1], pal[i * 4])
    assert all(abs(col(v)[0] - col(centre)[0]) < 60 for v in edge)        # edges are the image, like the centre


@pytest.mark.parametrize("g", [17, 25, 40])
def test_unframed_enlarge_fills_every_device_pixel(g):
    sw, sh = 118, 144
    src, pal = synth_art(sw, sh, seed=22)
    rgb = synth_rgb(400, 480, 3)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    dw, dh, rows = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, rgb, 400, 480, OVERLAY, b, r, framed=False)
    assert (dw, dh) == (sw * g // 16, sh * g // 16)
    assert all(v is not None for row in rows for v in row)


@needs_vs
@pytest.mark.parametrize("scan", [OFF, OVERLAY, MEAN])
@pytest.mark.parametrize("sw,sh", [(96, 115), (118, 144)])
def test_port_unframed_bake(exe, sw, sh, scan):
    src, pal = synth_art(sw, sh, seed=sw + scan)
    rgb = synth_rgb(300, 360, sw)
    raw = run(exe, 2, pal=pal, src=src, sw=sw, sh=sh, rgb=rgb, w=300, h=360, scan=scan | UNFRAMED)
    ok, b, r = struct.unpack_from("<3i", raw)
    vals = struct.unpack_from(f"<{sw * sh}i", raw, 12)
    assert ok and [list(vals[y * sw:(y + 1) * sw]) for y in range(sh)] == \
        SL.portrait_bake(sw, sh, pal, rgb, 300, 360, scan, b, r, framed=False)


@needs_vs
@pytest.mark.parametrize("g", [17, 22, 25, 40, 45])
@pytest.mark.parametrize("sw,sh", [(96, 115), (118, 144)])
def test_port_unframed_enlarge(exe, g, sw, sh):
    src, pal = synth_art(sw, sh, seed=g + sw)
    rgb = synth_rgb(320, 380, g)
    raw = run(exe, 3, pal=pal, src=src, sw=sw, sh=sh, num=g, rgb=rgb, w=320, h=380, scan=OVERLAY | UNFRAMED)
    ok, dw, dh = struct.unpack_from("<3i", raw)
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    want = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, g, 16, rgb, 320, 380, OVERLAY, b, r, framed=False)
    vals = struct.unpack_from(f"<{dw * dh}i", raw, 12)
    assert ok and (dw, dh) == want[:2]
    assert [list(vals[j * dw:(j + 1) * dw]) for j in range(dh)] == want[2]


@needs_vs
def test_port_unframed_native_art(exe):
    sw, sh = 96, 115
    src, pal = synth_art(sw, sh, seed=31)
    rgb = synth_rgb(sw, sh, 4)
    raw = run(exe, 2, pal=pal, src=src, sw=sw, sh=sh, rgb=rgb, w=sw, h=sh, scan=OVERLAY | UNFRAMED)
    vals = struct.unpack_from(f"<{sw * sh}i", raw, 12)
    assert [list(vals[y * sw:(y + 1) * sw]) for y in range(sh)] == \
        SL.portrait_bake(sw, sh, pal, rgb, sw, sh, OVERLAY, 0, 200, framed=False)
    assert not SL.portrait_is_native_art(sw - 2, sh - 2, sw, sh, framed=False)


@needs_vs
@pytest.mark.parametrize("scan", [OFF, OVERLAY, MEAN])
@pytest.mark.parametrize("framed", [True, False])
def test_port_resample_cache_is_bit_identical(exe, scan, framed):
    """The DLL caches the Lanczos stage across scan modes (a Preferences toggle re-runs only Finish): a cached second
    run, in another mode, must equal the law exactly."""
    sw, sh = (131, 157) if framed else (96, 115)
    src, pal = synth_art(sw, sh, seed=41 + scan)
    rgb = synth_rgb(300, 360, 7)
    flag = 0 if framed else UNFRAMED
    b, r = SL.portrait_scanline_params(src, sw, sw, sh, pal)
    raw = run(exe, 4, pal=pal, src=src, sw=sw, sh=sh, rgb=rgb, w=300, h=360, scan=scan | flag)
    ok, _, _ = struct.unpack_from("<3i", raw)
    n = (sw - 2) * (sh - 2) if framed else sw * sh
    vals = struct.unpack_from(f"<{n}i", raw, 12)
    iw = sw - 2 if framed else sw
    assert ok and [list(vals[y * iw:(y + 1) * iw]) for y in range(n // iw)] ==         SL.portrait_bake(sw, sh, pal, rgb, 300, 360, scan, b, r, framed=framed)
    raw = run(exe, 5, pal=pal, src=src, sw=sw, sh=sh, num=40, rgb=rgb, w=300, h=360, scan=scan | flag)
    ok, dw, dh = struct.unpack_from("<3i", raw)
    want = SL.portrait_enlarge_rgb(src, sw, sw, sh, 9, pal, 40, 16, rgb, 300, 360, scan, b, r, framed=framed)
    vals = struct.unpack_from(f"<{dw * dh}i", raw, 12)
    assert ok and [[None if v < 0 else v for v in vals[j * dw:(j + 1) * dw]] for j in range(dh)] == want[2]


# ---------------------------------------------------------------------------------------------- F1 rounding (option B)

def test_shr_round_is_symmetric():
    for v in range(-1000, 1001):
        for n in (4, 8):
            assert SL.portrait_shr_round(-v, n) == -SL.portrait_shr_round(v, n)
            assert abs(SL.portrait_shr_round(v, n) - v / (1 << n)) <= 0.5


def test_replacement_dither_keeps_flat_grey_brightness():
    """Audit F1: the floor-shifted error terms drifted every replacement ~2/255 dark.  Symmetric rounding removes the
    bias over the grey range (measured 2026-10-03, flat 48x48 fields 20..230: floor mean -1.96 / mean|e| 1.96 /
    max 3.34 -> rounded +0.37 / 0.66 / 1.36).  Brightness = luma; the channel split is F2 (the palette's
    green-leaning light greys under the 85% damping), kept by the user's choice of option B, so not asserted.
    A single grey can still miss by about a level where the palette has no grey near it (e.g. 160)."""
    pal = ROOT / "_portrait_preview" / "hd" / "game_palette_rgbquad.bin"
    if not pal.is_file():
        pytest.skip("game palette dump not present (Phase-0 probe output, gitignored)")
    pal = pal.read_bytes()
    w = h = 32
    luma = lambda grid: sum(77 * pal[v * 4 + 2] + 150 * pal[v * 4 + 1] + 29 * pal[v * 4]
                            for row in grid for v in row) / (256 * w * h)
    errs = []
    for grey in range(20, 236, 15):
        out = SL.portrait_from_rgb(bytes([grey]) * (w * h * 3), w, h, (0, 0, w, h), w, h, pal, OFF, 0, 256, 0)
        errs.append(luma(out) - grey)
    mean_bias = sum(errs) / len(errs)
    assert abs(mean_bias) < 0.8, errs                        # no systematic drift (was about -2)
    assert sum(abs(e) for e in errs) / len(errs) < 1.0, errs
    assert max(abs(e) for e in errs) < 2.0, errs
