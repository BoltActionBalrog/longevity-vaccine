"""Differential (Unicorn): scaling_laws.popup_g(W, H) == the g the REAL patches.yaml bytes store on a W x H screen.

    thunk_ensure_scale (menu_strip_thunks +0x560 @0x668760): g == 0 -> raw = scale_uniform(16) (@0x668200),
    g_popup_scale_num = clamp(raw, 16, 40)  ==  SL.popup_g(W, H) = clamp(floor(16 * min(W/1024, H/768)), 16, 40)

and scale_uniform(dim) itself == SL.scale_uniform(dim, W, H) for several dims.  popup_g is THE table of "the g each
resolution runs at": it is the min of both axes, FLOORED -- not height-only, not rounded (the old height-only
models gave 1280x1024 = 21 and 1600x900 = 19; the bytes give 20 and 18), and every 16:9 screen up to 1366 wide runs
at g = 16 although W > 1024 (why a lo-res gate keys on g, never on ScreenWidth).

Skips (does not fail) if unicorn is absent.
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP  # noqa: E402


def _load():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    code = {}
    for c in caves:
        for e in c.get("contents") or []:
            if e["id"] in ("scale_uniform", "thunk_ensure_scale"):
                va = int(c["virtual_addr"]) + int(e["offset"])
                code[e["id"]] = (va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, sym)))
    assert set(code) == {"scale_uniform", "thunk_ensure_scale"}
    return sym, code


SYM, CODE = _load()
G, SW, SH = SYM["g_popup_scale_num"], SYM["ScreenWidth"], SYM["ScreenHeight"]
STACK, MARKER = 0x00200000, 0x00300000


def _machine():
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {G & ~0xFFF, SW & ~0xFFF, SH & ~0xFFF}
    for va, b in CODE.values():
        pages |= {p & ~0xFFF for p in range(va, va + len(b), 0x1000)} | {(va + len(b)) & ~0xFFF}
    for p in sorted(pages):
        mu.mem_map(p, 0x1000)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(MARKER, 0x1000)
    for va, b in CODE.values():
        mu.mem_write(va, b)
    return mu


MU = _machine()


def _screen(w: int, h: int):
    MU.mem_write(SW, struct.pack("<I", w & 0xFFFFFFFF))
    MU.mem_write(SH, struct.pack("<I", h & 0xFFFFFFFF))


def ensure_g(w: int, h: int) -> int:
    """g_popup_scale_num the real thunk_ensure_scale stores on a w x h screen (g zeroed: it computes only once)."""
    _screen(w, h)
    MU.mem_write(G, bytes(8))                          # g and the period cell after it
    MU.mem_write(STACK, struct.pack("<I", MARKER))
    MU.reg_write(UC_X86_REG_ESP, STACK)
    MU.emu_start(CODE["thunk_ensure_scale"][0], MARKER, count=10_000)
    return struct.unpack("<i", bytes(MU.mem_read(G, 4)))[0]


def uniform(dim: int, w: int, h: int) -> int:
    """The real scale_uniform(dim) (eax in, eax out)."""
    _screen(w, h)
    MU.mem_write(STACK, struct.pack("<I", MARKER))
    MU.reg_write(UC_X86_REG_ESP, STACK)
    MU.reg_write(UC_X86_REG_EAX, dim)
    MU.emu_start(CODE["scale_uniform"][0], MARKER, count=10_000)
    return MU.reg_read(UC_X86_REG_EAX)


# the g each resolution REALLY runs at (bytes-verified 2026-10-18, scratchpad verify8\gtable.out)
NAMED = {(640, 480): 16, (800, 600): 16, (1024, 768): 16, (1088, 816): 17, (1152, 864): 18, (1280, 720): 16,
         (1280, 768): 16, (1280, 800): 16, (1280, 960): 20, (1280, 1024): 20, (1360, 768): 16, (1366, 768): 16,
         (1440, 900): 18, (1600, 900): 18, (1600, 1200): 25, (1680, 1050): 21, (1920, 1080): 22, (1920, 1200): 25,
         (2048, 1536): 32, (2560, 1080): 22, (2560, 1440): 30, (2560, 1600): 33, (2560, 2048): 40, (3440, 1440): 30,
         (3840, 1600): 33, (3840, 2160): 40, (5120, 2880): 40, (768, 1024): 16, (1080, 1920): 16}


@pytest.mark.parametrize("w,h", list(NAMED))
def test_named_resolutions(w, h):
    assert ensure_g(w, h) == SL.popup_g(w, h) == NAMED[(w, h)]


def _grid():
    pts = [(w, h) for w in range(320, 7681, 40) for h in range(240, 4321, 30)]
    # around the axis switch (W*768 == H*1024: 4:3 exactly, and one off either side) and the g = 17 threshold
    pts += [(4 * k + d, 3 * k) for k in range(80, 1921, 7) for d in (-1, 0, 1)]
    pts += [(w, h) for w in range(1080, 1100) for h in range(808, 824)]
    rnd = random.Random(10)
    pts += [(rnd.randrange(1, 9000), rnd.randrange(1, 6000)) for _ in range(3000)]
    return pts


def test_popup_g_is_the_bytes_over_a_sweep():
    bad = [(w, h, ensure_g(w, h), SL.popup_g(w, h)) for w, h in _grid() if ensure_g(w, h) != SL.popup_g(w, h)]
    assert not bad, bad[:10]


@pytest.mark.parametrize("dim", [1, 16, 19, 213, 600, 1000])
def test_scale_uniform_is_the_bytes(dim):
    pts = [(w, h) for w in range(320, 7681, 160) for h in range(240, 4321, 120)] + [(1024, 768), (1366, 768)]
    bad = [(w, h, uniform(dim, w, h), SL.scale_uniform(dim, w, h)) for w, h in pts
           if uniform(dim, w, h) != SL.scale_uniform(dim, w, h)]
    assert not bad, bad[:10]


def test_g_above_16_needs_both_axes():
    """g > 16 iff W >= 1088 AND H >= 816: the 16:9 screens up to 1366 wide (W > 1024) are g = 16."""
    for w in range(1024, 1400, 8):
        for h in range(600, 1300, 8):
            assert (SL.popup_g(w, h) > 16) == (w >= 1088 and h >= 816), (w, h)


# ---- the retired models: each must be caught by the named table ----------------------------------------------------
RETIRED = {
    "height-only, floored": lambda w, h: min(40, max(16, 16 * h // 768)),
    "height-only, rounded": lambda w, h: min(40, max(16, (16 * h + 384) // 768)),
    "min, rounded": lambda w, h: min(40, max(16, min((16 * w * 2 + 1024) // 2048, (16 * h * 2 + 768) // 1536))),
    "width-only": lambda w, h: min(40, max(16, 16 * w // 1024)),
}


@pytest.mark.parametrize("name", list(RETIRED))
def test_retired_models_disagree_with_the_bytes(name):
    f = RETIRED[name]
    assert any(f(w, h) != g for (w, h), g in NAMED.items()), name
