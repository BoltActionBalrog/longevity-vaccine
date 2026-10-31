"""Differential: the BAKED x86 band-map must agree with the Python reference, exactly.

This closes the last gap in the chain. `scaling_laws.py` is the source of truth;
`scaling_laws.js` is checked against it by test_scaling_js_parity.py; and the assembly
that actually ships is checked against it *here*, by emulating the real assembled bytes
of `bm_axis` (from scripts/assemble_bandmap.py) under Unicorn and comparing its output
buffer, index for index, with `scaling_laws.axis_map`.

No screenshots, no game, no "it looked right at 4K". If the asm computes a different
band width, a different stroke, or a different middle sample than the reference, this
fails with the exact (g, n, srcN, dstN) and the first divergent index.

Why emulate rather than trust the source: `bm_axis` is hand-written x86 with a nested
`bm_cum` that reads its parent's frame through the saved-ebp chain, two divisions, a
Bresenham accumulator, and a mirrored far band. Every one of those is a place to be
off by one, and none of them is visible in a screenshot at a single resolution.

Skips (does not fail) if keystone/unicorn are absent, so the suite still runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scaling_laws import axis_map, cum, stroke_width  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone not installed")
unicorn = pytest.importorskip("unicorn", reason="unicorn not installed")

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EBP,
)

import assemble_bandmap as ab  # noqa: E402

# ---- emulator layout -------------------------------------------------------
BASE = 0x00A0C000          # pcave2, where the thunk really lives
CODE = 0x00A00000          # mapped region containing BASE
STACK = 0x00B00000
DATA = 0x00C00000          # fbuf / outbuf / g_popup_scale_num
F_BUF = DATA + 0x1000      # 256 bytes
OUT_BUF = DATA + 0x2000    # dstN * 2 bytes
G_VAR = DATA + 0x0100

SPANS = [150, 199, 256, 400, 771, 898, 1234, 1600, 2400]
BAND_DEPTHS = [3, 6, 8, 44, 61]
G_RANGE = list(range(17, 41))       # g<=16 never reaches the enlarge (renderers early-out)


@pytest.fixture(scope="module")
def blob():
    """Assemble for real, map ONE emulator, and locate bm_axis inside the blob.

    One Uc for the whole module: a fresh instance per case maps 3MB and the sweep runs
    ~1,000 cases, which exhausts the process (a hard fault, not a test failure).
    """
    off, va, data = ab.build()["thunk_bandmap_blit"]
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for b in (CODE, STACK, DATA):
        mu.mem_map(b, 0x100000)
    mu.mem_write(va, data)
    return {"va": va, "data": data, "mu": mu, "bm_axis": _find_bm_axis(va, data)}


def _find_bm_axis(va: int, data: bytes) -> int:
    """bm_axis is the target of the first `call rel32` in thunk_bandmap_blit."""
    for i in range(len(data) - 5):
        if data[i] == 0xE8:
            rel = int.from_bytes(data[i + 1:i + 5], "little", signed=True)
            target = va + i + 5 + rel
            if va < target < va + len(data):
                return target
    raise AssertionError("no internal call found — bm_axis not located")


RET_MAGIC = 0x00A00010              # mapped, never written: emu_start stops here


def run_bm_axis(blob, n: int, dst_n: int, src_n: int, k: int) -> tuple[int, int, list[int]]:
    """Execute the real assembled bytes. Returns (eax, edx=B, outbuf[0:dst_n])."""
    mu = blob["mu"]
    sp = STACK + 0x80000
    # cdecl args pushed right-to-left: n, dstN, srcN, K, fbuf, outbuf
    for i, a in enumerate([n, dst_n, src_n, k, F_BUF, OUT_BUF]):
        mu.mem_write(sp + 4 + i * 4, int(a).to_bytes(4, "little", signed=True))
    mu.mem_write(sp, RET_MAGIC.to_bytes(4, "little"))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EBP, STACK + 0x90000)
    mu.mem_write(F_BUF, b"\x00" * 512)
    mu.mem_write(OUT_BUF, b"\x00" * (4096 * 2))

    mu.emu_start(blob["bm_axis"], RET_MAGIC, count=50_000_000)

    eax = mu.reg_read(UC_X86_REG_EAX)
    edx = mu.reg_read(UC_X86_REG_EDX)
    out = []
    if eax:
        raw = mu.mem_read(OUT_BUF, dst_n * 2)
        out = [int.from_bytes(raw[i * 2:i * 2 + 2], "little") for i in range(dst_n)]
    return eax, edx, out


def test_bm_axis_located(blob):
    assert blob["va"] < blob["bm_axis"] < blob["va"] + len(blob["data"])


@pytest.mark.parametrize("n", BAND_DEPTHS)
def test_asm_matches_reference_across_the_sweep(blob, n: int):
    """The whole map, every index, for every g and span. This is the ship gate."""
    bad = []
    checked = 0
    for g in G_RANGE:
        k = stroke_width(g)
        for span in SPANS:
            src = max(2 * n + 1, span * 16 // g)
            py = axis_map(src, span, n, g)
            eax, edx, out = run_bm_axis(blob, n, span, src, k)

            if py is None:
                # reference rejects -> asm must reject too (fall back to the shipped blit)
                if eax != 0:
                    bad.append(("asm accepted what python rejected", g, n, src, span))
                continue
            if eax == 0:
                # asm may additionally reject on B>255; that is a documented fallback
                b = cum(n, span, src)
                if b <= 255:
                    bad.append(("asm rejected what python accepted", g, n, src, span, b))
                continue
            checked += 1
            if edx != cum(n, span, src):
                bad.append(("B", g, n, src, span, edx, cum(n, span, src)))
                continue
            if out != list(py):
                i = next(j for j, (a, b2) in enumerate(zip(out, py)) if a != b2)
                bad.append(("map", g, n, src, span, f"idx {i}: asm={out[i]} py={py[i]}"))
    assert checked > 0, f"no cases actually exercised for n={n}"
    assert not bad, f"{len(bad)} divergences (checked {checked}), first 3: {bad[:3]}"


@pytest.mark.parametrize("g,n,span", [(40, 6, 898), (25, 6, 898), (22, 6, 790)])
def test_asm_opposite_strokes_are_equal(blob, g: int, n: int, span: int):
    """The defect this bake exists to kill, asserted on the SHIPPING bytes."""
    k = stroke_width(g)
    src = max(2 * n + 1, span * 16 // g)
    eax, _, out = run_bm_axis(blob, n, span, src, k)
    assert eax == 1
    near = sum(1 for s in out if s == 0)
    far = sum(1 for s in out if s == src - 1)
    assert near == far == k, f"g={g}: near={near} far={far} K={k}"


def test_asm_pins_stroke_and_bevel(blob):
    """Band cells 0 and 1 both render at K (the corner-bevel law), in the asm."""
    g, n, span = 25, 6, 898
    k = stroke_width(g)
    src = max(2 * n + 1, span * 16 // g)
    eax, b, out = run_bm_axis(blob, n, span, src, k)
    assert eax == 1
    assert out[:2 * k] == [0] * k + [1] * k, out[:8]
