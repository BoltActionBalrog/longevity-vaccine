"""uimod basehd_law.h / hdpack.h (C++) vs scaling_laws.base_hd_cell_size / palette_box_shrink (the source of truth),
exactly, and hdpack's pack reader against well-formed and hostile PCX files.

Builds tests/basehd_selftest.cpp once with the VS x86 toolchain (skipped when VS is absent) and runs every case of
a test through one process. The law-only tests run anyway.
"""
from __future__ import annotations

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

KEY = 9        # load_faction_art's transparency key (file 255 + 10)
SHADOW = 0     # file 246 after Buffer_load_pcx(.., 10, 236): the shadow / black-ink index
OK, NO_FILE, NOT_PCX, WRONG_SIZE, BAD_BODY, NO_PALETTE, WRONG_PALETTE = 0, 1, 2, 3, 4, 5, 6   # hdpack::Result


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

@pytest.mark.parametrize("num,den", [(16, 16), (22, 16), (25, 16), (40, 16), (3, 2), (5, 7), (1, 1), (64, 100),
                                     (87, 100), (31, 100)])
def test_cell_size_is_the_engines_float_truncation(num, den):
    w, h = SL.base_hd_cell_size(100, 75, num, den)
    f = SL.engine_scale_f(num, den)                      # the engine's float32 ratio, not a second model of it
    assert (w, h) == (SL._ftol(100 * f), SL._ftol(75 * f))
    if num == den:
        assert (w, h) == (100, 75)                        # identity at the unscaled draw


def test_cell_size_follows_float32_where_the_integer_floor_does_not():
    """den = 100 (set by the engine at four places): the float32 ratio and the integer floor part in places."""
    diff = [(w, n) for w in range(1, 41) for n in range(1, 41)
            if SL.base_hd_cell_size(w, 1, n, 100)[0] != w * n // 100]
    assert diff                                           # the law is the engine's float, not the integer floor


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
    assert SL.palette_box_shrink([[KEY, KEY, 50, 60]], 1, 1, rgb) in ([[50]], [[60]])   # tie: colours win
    assert SL.palette_box_shrink([[KEY, KEY, KEY, 60]], 1, 1, rgb) == [[KEY]]


def test_all_specials_together_outvote_the_colours():
    """Key 4 + shadow 3 against colour 4: 7 of the 11 pixels are not colour, so a special wins (the key, met most)."""
    rgb = [(i, i, i) for i in range(256)]
    src = [[KEY] * 4 + [SHADOW] * 3 + [100] * 4]
    assert SL.palette_box_shrink(src, 1, 1, rgb) == [[KEY]]


def test_enlarge_is_nearest():
    rgb = [(i, i, i) for i in range(256)]
    assert SL.palette_box_shrink([[50, 60]], 4, 1, rgb) == [[50, 50, 60, 60]]


# ---- the C++ port, exactly ---------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "basehd_selftest.cpp", "basehd_selftest_", "/Oi /GL")   # the DLL's codegen


#: (sw, sh) x (num, den): targets base_hd_cell_size(sw, sh, num, den) -- shrinks below 1 and enlargements above, as
#: the map's zoom gives them (SCALE = (zoom + 16) / 16)
PORT_CASES = [(sw, sh, num, den) for sw, sh in ((80, 60), (160, 120), (37, 29))
              for num, den in ((16, 16), (22, 16), (25, 16), (40, 16), (7, 64), (90, 16), (3, 16), (11, 16))]


def test_port_matches_law(exe, tmp_path):
    cases, blob = [], bytearray(struct.pack("<i", len(PORT_CASES)))
    for sw, sh, num, den in PORT_CASES:
        src, rgb = synth(sw, sh, seed=sw * 100 + num)
        dw, dh = SL.base_hd_cell_size(sw, sh, num, den)
        dw, dh = max(dw, 1), max(dh, 1)
        pitch = sw + 3                                    # a pitch wider than the row, like the engine's buffers
        body = bytearray(pitch * sh)
        for y, row in enumerate(src):
            body[y * pitch:y * pitch + sw] = bytes(row)
        blob += struct.pack("<7i", sw, sh, pitch, dw, dh, num, den) + rgbq(rgb) + bytes(body)
        cases.append((src, rgb, dw, dh, sw, sh, num, den))
    assert any(c[2] > c[4] for c in cases) and any(c[2] < c[4] for c in cases)   # both enlarge and shrink run
    (tmp_path / "in.bin").write_bytes(bytes(blob))
    subprocess.run([str(exe), "law", str(tmp_path / "in.bin"), str(tmp_path / "out.bin")], check=True)
    raw, at = (tmp_path / "out.bin").read_bytes(), 0
    for src, rgb, dw, dh, sw, sh, num, den in cases:
        size = struct.unpack_from("<2i", raw, at)
        at += 8
        out = [list(raw[at + j * dw:at + (j + 1) * dw]) for j in range(dh)]
        at += dw * dh
        assert size == SL.base_hd_cell_size(sw, sh, num, den), (sw, sh, num, den)
        assert out == SL.palette_box_shrink(src, dw, dh, rgb), (sw, sh, num, den)
    assert at == len(raw)


# ---- hdpack: the pack reader, on files a stranger could send ------------------------------------------------------

def rle_rows(img, run_limit=63):
    out = bytearray()
    for row in img:
        x = 0
        while x < len(row):
            v, n = row[x], 1
            while x + n < len(row) and row[x + n] == v and n < run_limit:
                n += 1
            if n > 1 or v >= 0xC0:
                out += bytes([0xC0 | n, v])
            else:
                out.append(v)
            x += n
    return out


def pcx(img, pal=None, *, enc=1, bpl=None, body=None, trailer=True):
    h, w = len(img), len(img[0])
    hdr = bytearray(128)
    hdr[0], hdr[1], hdr[2], hdr[3] = 10, 5, enc, 8
    struct.pack_into("<4H", hdr, 4, 0, 0, w - 1, h - 1)
    hdr[65] = 1
    struct.pack_into("<H", hdr, 66, w if bpl is None else bpl)
    pal = pal if pal is not None else bytes((i * 7 + c) & 255 for i in range(256) for c in range(3))
    return bytes(hdr) + bytes(rle_rows(img) if body is None else body) + ((b"\x0c" + pal) if trailer else b"")


def image(w, h, seed):
    rnd = random.Random(seed)
    return [[(rnd.randrange(4) * 60 + (x // 7)) & 255 for x in range(w)] for _ in range(h)]


def run_pack(exe, tmp_path, cases):
    """cases: (name, file bytes, wantW, wantH, palette bytes or None, rect) -> [(result, expanded bytes or None)]"""
    lines = []
    for i, (name, data, w, h, pal, rect) in enumerate(cases):
        p = tmp_path / f"{i}_{name}.pcx"
        p.write_bytes(data)
        palpath = "-"
        if pal is not None:
            pp = tmp_path / f"{i}_{name}_stock.pcx"
            pp.write_bytes(b"\0" * 128 + b"\x0c" + pal)
            palpath = str(pp)
        lines.append(f"{p} {w} {h} {palpath} {rect[0]} {rect[1]} {rect[2]} {rect[3]}")
    (tmp_path / "list.txt").write_text("\n".join(lines) + "\n")
    subprocess.run([str(exe), "pack", str(tmp_path / "list.txt"), str(tmp_path / "out.bin")], check=True)
    raw, at, res = (tmp_path / "out.bin").read_bytes(), 0, []
    for case in cases:
        rect = case[5]
        (r,) = struct.unpack_from("<i", raw, at)
        at += 4
        px = None
        if r == OK:
            (ok,) = struct.unpack_from("<i", raw, at)
            at += 4
            n = rect[2] * rect[3]
            px = raw[at:at + n] if ok else None
            at += n
        res.append((r, px))
    assert at == len(raw)
    return res


def test_pack_reader(exe, tmp_path):
    img = image(64, 40, 3)
    pal = bytes((i * 3 + c) & 255 for i in range(256) for c in range(3))
    good = pcx(img, pal)
    body = rle_rows(img)
    crossing = bytearray(rle_rows([row[:60] for row in img]))   # 60-px rows ...
    crossing[0:0] = bytes([0xC0 | 8, 1])                        # ... and 8 px in front: a run crosses the 64-px line
    cases = [
        ("good", good, 64, 40, pal, (5, 7, 20, 13)),
        ("good_full", good, 64, 40, None, (0, 0, 64, 40)),
        ("wrong_palette", good, 64, 40, bytes(768), (0, 0, 1, 1)),
        ("wrong_size", good, 64, 41, None, (0, 0, 1, 1)),
        ("truncated_half", good[:128 + len(body) // 2], 64, 40, None, (0, 0, 1, 1)),
        ("no_trailer", pcx(img, trailer=False), 64, 40, None, (0, 0, 1, 1)),
        ("trailer_marker", good[:-769] + b"\x0b" + good[-768:], 64, 40, None, (0, 0, 1, 1)),
        ("uncompressed", pcx(img, enc=0), 64, 40, None, (0, 0, 1, 1)),
        ("bpl_65535", pcx(img, bpl=65535), 64, 40, None, (0, 0, 1, 1)),
        ("bpl_66", pcx(img, bpl=66), 64, 40, None, (0, 0, 1, 1)),
        ("run_crosses_line", pcx(img, body=bytes(crossing)), 64, 40, None, (0, 0, 1, 1)),
        ("zero_run", pcx(img, body=b"\xc0\x05" + bytes(body)), 64, 40, None, (0, 0, 1, 1)),
        ("short_file", good[:200], 64, 40, None, (0, 0, 1, 1)),
        ("empty", b"", 64, 40, None, (0, 0, 1, 1)),
        ("rect_outside", good, 64, 40, None, (60, 0, 8, 1)),
    ]
    want = {"good": OK, "good_full": OK, "wrong_palette": WRONG_PALETTE, "wrong_size": WRONG_SIZE,
            "truncated_half": BAD_BODY, "no_trailer": BAD_BODY, "trailer_marker": NO_PALETTE,
            "uncompressed": NOT_PCX, "bpl_65535": NOT_PCX, "bpl_66": NOT_PCX, "run_crosses_line": BAD_BODY,
            "zero_run": BAD_BODY, "short_file": NOT_PCX, "empty": NO_FILE, "rect_outside": OK}
    for case, (r, px) in zip(cases, run_pack(exe, tmp_path, cases)):
        name, rect = case[0], case[5]
        assert r == want[name], name
        if name.startswith("good"):
            x0, y0, cw, ch = rect
            assert px == bytes(v for row in img[y0:y0 + ch] for v in row[x0:x0 + cw]), name
        if name == "rect_outside":
            assert px is None                              # Expand refuses a rect outside the pack


def test_pack_reader_survives_random_damage(exe, tmp_path):
    """Random byte flips and cuts of a good file: every one either loads and expands to its own size, or is refused
    (the reader never reads or writes out of bounds -- the selftest would crash)."""
    img = image(48, 30, 9)
    good = pcx(img)
    rnd = random.Random(1)
    cases = []
    for i in range(300):
        d = bytearray(good)
        for _ in range(rnd.randrange(1, 6)):
            d[rnd.randrange(128, len(d))] = rnd.randrange(256)
        if rnd.random() < 0.3:
            d = d[:rnd.randrange(128, len(d))]
        cases.append((f"r{i}", bytes(d), 48, 30, None, (0, 0, 48, 30)))
    for r, px in run_pack(exe, tmp_path, cases):
        assert r in (OK, NOT_PCX, BAD_BODY, NO_PALETTE)
        if r == OK:
            assert px is not None and len(px) == 48 * 30
