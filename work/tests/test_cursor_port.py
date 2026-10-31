"""Map-cursor scaling (uimod cursorscale.cpp + cursor_law.h) vs scaling_laws.cursor_* (the source of truth).

1. The law: g <= 16 identity; the enlarged cell is scale_px(32, g); every native pixel owns a non-empty, contiguous
   dest run; the runs tile the canvas; the hotspot sits inside its pixel's run; the content rect is the union of runs.
2. The C++ port, bit for bit (tests/cursor_selftest.cpp via cpp_harness), on the 12 real CURSOR.PCX cells (cut with
   load_cursors' geometry and trimmed like Sprite_init) and on random cells, g = 8..48.
3. The engine facts the DLL module relies on, read from the pristine exe: Win_set_cursor's entry, Console_cursor_on's
   sprite / hotspot reads, the +0x28 "not mine" skip in the sprite destructor and in Sprite_init, PaintMain's 1:1
   blit of [0x9B7A2C], Win_update_cursor's save-under sizing from +0x18/+0x1C, and the cursor file name.
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
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

SRC = ROOT / "tests" / "cursor_selftest.cpp"
MODULE = ROOT.parent / "src" / "uimod" / "src" / "cursorscale.cpp"
GS = list(range(8, 49))
KEY = 255                                           # CURSOR.PCX's transparent index (the cell corner)


# ---- the law -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("g", GS)
def test_runs_tile_the_canvas(g):
    s = SL.cursor_canvas_px(g)
    assert s == (32 if g <= 16 else SL.scale_px(32, g))
    runs = [SL.cursor_nn_run(c, g) for c in range(32)]
    assert runs[0][0] == 0 and runs[-1][1] == s - 1
    for (a0, b0), (a1, b1) in zip(runs, runs[1:]):
        assert a0 <= b0 and a1 == b0 + 1                # non-empty, contiguous, in order
    if g <= 16:
        assert runs == [(c, c) for c in range(32)]


@pytest.mark.parametrize("g", GS)
def test_hotspot_inside_its_pixel_run(g):
    for h in range(32):
        a, b = SL.cursor_nn_run(h, g)
        assert a <= SL.cursor_hotspot(h, g) <= b
        if g <= 16:
            assert SL.cursor_hotspot(h, g) == h


def test_4k_and_1600_numbers():
    assert SL.cursor_canvas_px(40) == 80 and SL.cursor_canvas_px(25) == 50 and SL.cursor_canvas_px(22) == 44
    assert SL.cursor_hotspot(7, 40) == 18 and SL.cursor_hotspot(16, 40) == 40 and SL.cursor_hotspot(16, 25) == 25


# ---- the real cells ------------------------------------------------------------------------------------------------

def _cells():
    """load_cursors 0x454FC0 geometry: cell i at (1 + 33i, 1), 32x32; hotspot markers (runtime index 5 = PCX 251)
    on row 0 (x) and in the column left of the cell (y); 0 when absent.  Trimmed like Sprite_init (key rows / columns
    off every side).  None for an all-key cell."""
    from PIL import Image
    p = config.game_dir(required=False) / "Cursor.pcx"
    if not p.is_file():
        pytest.skip(f"{p} not found")
    px = Image.open(p).load()
    out = []
    for i in range(12):
        x0 = 1 + 0x21 * i
        hx = next((d for d in range(32) if px[x0 + d, 0] == 251), 0)
        hy = next((d for d in range(32) if px[x0 - 1, d + 1] == 251), 0)
        cell = [[px[x0 + x, 1 + y] for x in range(32)] for y in range(32)]
        rows = [y for y in range(32) if any(v != KEY for v in cell[y])]
        cols = [x for x in range(32) if any(cell[y][x] != KEY for y in range(32))]
        if not rows:
            out.append(None)
            continue
        t, b, l, r = rows[0], rows[-1], cols[0], cols[-1]
        content = bytes(cell[y][x] for y in range(t, b + 1) for x in range(l, r + 1))
        out.append((l, t, r - l + 1, b - t + 1, content, hx, hy))
    return out


def _law_enlarge(l, t, w, h, content, g):
    dl, dt, dw, dh = SL.cursor_content_rect(l, t, w, h, g)
    s = SL.cursor_canvas_px(g)
    px = bytearray(dw * dh)
    for y in range(dh):
        sy = SL.nn_center_index(dt + y, s, 32) - t
        for x in range(dw):
            sx = SL.nn_center_index(dl + x, s, 32) - l
            assert 0 <= sx < w and 0 <= sy < h          # never reads outside the native content
            px[y * dw + x] = content[sy * w + sx]
    return (dl, dt, dw, dh), bytes(px)


@pytest.fixture(scope="module")
def exe():
    import cpp_harness
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(SRC, "cursor_selftest_", "/Oi /GL")


def _run(exe, g, l, t, w, h, content, hx, hy):
    with tempfile.TemporaryDirectory(prefix="cur_") as td:
        d = pathlib.Path(td)
        (d / "in.bin").write_bytes(struct.pack("<8i", g, l, t, w, h, w, hx, hy) + content)
        subprocess.run([str(exe), str(d / "in.bin"), str(d / "out.bin")], check=True)
        raw = (d / "out.bin").read_bytes()
    canvas, dl, dt, dw, dh, shx, shy = struct.unpack_from("<7i", raw)
    return canvas, (dl, dt, dw, dh), raw[28:], (shx, shy)


@pytest.mark.parametrize("g", [8, 16, 17, 18, 20, 22, 25, 27, 32, 40, 48])
def test_port_matches_law_on_the_real_cursors(exe, g):
    cells = _cells()
    assert sum(c is not None for c in cells) == 9      # cells 0, 6, 7 are empty in CURSOR.PCX
    for c in cells:
        if c is None:
            continue
        l, t, w, h, content, hx, hy = c
        rect, px = _law_enlarge(l, t, w, h, content, g)
        canvas, prect, ppx, phot = _run(exe, g, l, t, w, h, content, hx, hy)
        assert canvas == SL.cursor_canvas_px(g)
        assert prect == rect and ppx == px
        assert phot == (SL.cursor_hotspot(hx, g), SL.cursor_hotspot(hy, g))
        if g <= 16:
            assert rect == (l, t, w, h) and px == content


def test_port_matches_law_on_random_cells(exe):
    rnd = random.Random(7)
    for _ in range(60):
        g = rnd.choice(GS)
        w, h = rnd.randint(1, 32), rnd.randint(1, 32)
        l, t = rnd.randint(0, 32 - w), rnd.randint(0, 32 - h)
        content = bytes(rnd.randrange(256) for _ in range(w * h))
        hx, hy = rnd.randrange(32), rnd.randrange(32)
        rect, px = _law_enlarge(l, t, w, h, content, g)
        canvas, prect, ppx, phot = _run(exe, g, l, t, w, h, content, hx, hy)
        assert (canvas, prect, ppx, phot) == (SL.cursor_canvas_px(g), rect, px,
                                              (SL.cursor_hotspot(hx, g), SL.cursor_hotspot(hy, g)))


def test_patrol_cursor_at_4k_is_scaled():
    """User 2026-10-14: the patrol cursor (cell 8: 29x29 content, lit box 29x27) drew native at 4K and 1600x1200."""
    l, t, w, h, content, hx, hy = _cells()[8]
    assert (w, h) == (29, 29) and (hx, hy) == (18, 17)
    for g in (22, 25, 40):
        _l, _t, dw, dh = SL.cursor_content_rect(l, t, w, h, g)
        assert abs(dw - 29 * g / 16) <= 1 and abs(dh - 29 * g / 16) <= 1     # vanilla x g/16, within the NN run


# ---- the engine facts the module relies on -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pe():
    import pefile
    p = config.terranx_bak(required=False)
    if not p.exists():
        pytest.skip(f"{p} not found")
    return pefile.PE(str(p), fast_load=True)


def rd(pe, va, n):
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    return pe.__data__[off:off + n]


def test_engine_facts(pe):
    # load_cursors: CURSOR.PCX, 12 sprites at 0x93AA70 stride 0x2C (until 0x93AC80), hotspots 0x93AA10 / 0x93AA40
    assert rd(pe, 0x68511C, 11) == b"CURSOR.PCX\0"
    assert rd(pe, 0x454FF4, 5) == bytes.fromhex("BB70AA9300")
    assert rd(pe, 0x455096, 3) == bytes.fromhex("83C32C") and rd(pe, 0x4550AB, 6) == bytes.fromhex("81FB80AC9300")
    assert rd(pe, 0x455099, 12) == bytes.fromhex("898810AA9300" "899040AA9300")
    assert rd(pe, 0x455073, 2) == bytes.fromhex("6A00")                 # Sprite_init's own-pixels flag = 0 (malloc)
    # Win_set_cursor entry (the detour's 6 stolen bytes + the jz it keeps) and Console_cursor_on's reads
    assert rd(pe, 0x5EC740, 8) == bytes.fromhex("8B44240485C0741A")
    assert rd(pe, 0x510435, 25) == bytes.fromhex("8D3C9570AA9300" "3BCF7426" "8B049D40AA9300" "8B0C9D10AA9300")
    # the +0x28 skip: the sprite destructor 0x5E3820 and Sprite_init 0x5E39C4 free +0x04 only when +0x28 == 0
    assert rd(pe, 0x5E3826, 5) == bytes.fromhex("397E28752D")
    assert rd(pe, 0x5E39C4, 5) == bytes.fromhex("396E28752D")
    # the static array's atexit destructor is that sprite destructor (vector dtor over 12 x 0x2C at 0x93AA70)
    assert rd(pe, 0x52DAF0, 14) == bytes.fromhex("6850684000" "6A0C" "6A2C" "6870AA9300")
    assert rd(pe, 0x406850, 5) == bytes.fromhex("E9CBCF1D00")             # jmp 0x5E3820
    # Win_update_cursor sizes the cursor from the sprite's +0x18 / +0x1C on a sprite change
    assert rd(pe, 0x5F1986, 3) == bytes.fromhex("8B4018") and rd(pe, 0x5F1994, 3) == bytes.fromhex("8B491C")
    # ... and re-sizes the save-under 0x9B6F08 to that canvas whenever it differs (Buffer +0x80 w, -[+0x84] h):
    # `mov edx,[0x9B6F88]; cmp edx,eax; jne; mov edx,[0x9B6F8C]; neg edx; cmp edx,ecx; je` then Buffer_init 0x5D7670
    assert rd(pe, 0x5F19B5, 0x16) == bytes.fromhex("8B15886F9B00" "3BD0" "750C" "8B158C6F9B00" "F7DA" "3BD1" "7419")
    assert rd(pe, 0x5F19CF, 10) == bytes.fromhex("B9086F9B00" "E8975CFEFF")      # mov ecx,0x9B6F08; call 0x5D7670
    # Sprite_init resets +0x28 to 0 (`mov [esi+0x28],ebp`, ebp = 0) and sets 1 only on its pool path (0x6353C0)
    assert rd(pe, 0x5E3A22, 3) == bytes.fromhex("896E28")
    assert rd(pe, 0x5E3CEC, 5) == bytes.fromhex("E8CF160500") and rd(pe, 0x5E3CF8, 7) == bytes.fromhex("C7462801000000")
    # the re-cut paths: load_cursors runs again from load_fixed_sprites and Console_init (it bails only while
    # [0x9BC494] is set: `mov eax,[0x9BC494]; ...; cmp eax,edi; jne`)
    assert rd(pe, 0x455F05, 5) == bytes.fromhex("E8B6F0FFFF") and rd(pe, 0x51D9A9, 5) == bytes.fromhex("E81276F3FF")
    assert rd(pe, 0x454FC6, 5) == bytes.fromhex("A194C49B00") and rd(pe, 0x454FD0, 2) == bytes.fromhex("0F85")
    # PaintMain blits [0x9B7A2C] 1:1 (push 1; push 1)
    assert rd(pe, 0x5EFEE8, 6) == bytes.fromhex("8B0D2C7A9B00") and rd(pe, 0x5EFEFD, 4) == bytes.fromhex("6A016A01")


def test_module_constants_match_the_facts():
    src = MODULE.read_text(encoding="utf-8")
    for needle in ("kVA_Sprites = 0x93AA70, kSpriteStride = 0x2C", "kCount = 12", "kVA_HotX = 0x93AA10",
                   "kVA_HotY = 0x93AA40", "kVA_G = 0x668740", "kVA_CurSprite = 0x9B7A2C",
                   "kVA_MapWins = 0x7D3C3C, kMapWinCount = 8", "kVA_SetCursor = 0x5EC740", "kSteal = 6",
                   "0x8B, 0x44, 0x24, 0x04, 0x85, 0xC0, 0x74, 0x1A", "kNotMine = 0x28"):
        assert needle in src, needle
    # every engine field write happens in Apply, after the deferral check; the module never frees engine memory
    assert "free(" not in src and "delete" not in src and "HeapFree" not in src
    # deferral is per sprite: only the sprite on screen waits (an empty or done sprite on screen never blocks the
    # others -- a blanket "one of ours is on screen" return would never scale while the map shows cursor 0)
    assert "if (sp == onScreen) continue;" in src and "IsOurSprite(Ref<uintptr_t>(kVA_CurSprite))" not in src
    loop = src[src.index("void EnsureScaledInner()"):]
    loop = loop[:loop.index("\n}\n")]
    i_recut, i_done, i_defer, i_apply = (loop.index("if (!Capture(i, sp))"), loop.index("bits == s.scaled.data()) {"),
                                         loop.index("if (sp == onScreen) continue;"), loop.index("Apply(i, sp, g);"))
    assert i_recut < i_done < i_defer < i_apply


def test_recut_recaptures_before_the_deferral():
    """Audit 2026-10-15: a re-cut sprite still on screen kept its cached g, so the hook swapped a SCALED hotspot onto
    NATIVE pixels and map windows kept the old scaled hotspot. The re-cut (+0x28 back to 0) is re-captured at once --
    s.g cleared, held scaled hotspots restored -- and only the enlargement waits for the sprite to leave the screen."""
    src = MODULE.read_text(encoding="utf-8")
    loop = src[src.index("void EnsureScaledInner()"):]
    loop = loop[:loop.index("\n}\n")]
    recut = loop[loop.index("if (Fld<int>(sp, kNotMine) == 0) {"):loop.index("} else if (s.g == g")]
    assert "const bool wasScaled = s.g != 0;" in recut and "RestoreHeldHotspots(i, oldShx, oldShy);" in recut
    assert "s.g = 0;" in recut                                   # a cut we cannot capture never keeps a stale g
    assert "s.g = 0;" in src[src.index("bool Capture("):src.index("void Apply(")]
    hook = src[src.index("int __fastcall HookSetCursor("):]
    assert "if (s.g && hx == s.hx && hy == s.hy)" in hook[:hook.index("\n}\n")]   # no swap while s.g == 0
    restore = src[src.index("void RestoreHeldHotspots("):src.index("void FixHeldHotspots()")]
    for term in ("kVA_MapWins", "0x188) != sp", "== oldShx", "== oldShy", "= s.hx;", "= s.hy;"):
        assert term in restore, term

