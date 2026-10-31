"""Differential: the BAKED thunk_btn_bandstripe v8 + thunk_chev_coverage must
agree with the Python law (scaling_laws.chevron_coverage_filter) bit-exactly.

v8 (2026-07-24, user-approved candidate "coverage linear g2.2" from
work\\chev_candidates3.png): the GOVERNOR chevrons route to thunk_chev_coverage
INSTEAD of the KSB — a coverage(area)-weighted, linear-light (gamma 2.2 LUT)
zoom of the native 20x20 art, redmean-quantized to the live palette with the
key index excluded.  Raw NN was pixel-diff-proven faithful yet still read
wrong (the art is a 1px 50/50 stripe dither; fractional NN duplicates one
color's rows in phase-flipped clusters), and the palette rung ladder makes
plain bilinear blotch.  The bar buttons KEEP the v4 P-law restripe.

This test emulates the REAL assembled bytes (BTN + CHEV + the baked LUT data)
with the KSB stubbed to a bare RET 0x2C and the fixture palette written at the
real Palette address 0x94C590.  Verified:

  * chevron esi (btn18/btn19): canvas D x D == chevron_coverage_filter(...)
    (the thunk is a bit-exact port of the law) at a spread of g;
  * chevron at dw==20 (g<=16): falls through to the KSB tail-jmp -- canvas
    untouched (native no-op path);
  * bar-button esi in the BaseWin range, and MENU: v4's probe + P-law restripe
    unchanged from v7 (post-zoom canvas, KSB stub);
  * out-of-range esi: untouched;
  * stack balance: RET 0x2C, ebx/ebp/esi preserved.

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_band_restripe as ABR  # noqa: E402

PCAVE2 = ABR.PCAVE2_VA
CORE_VA = PCAVE2 + ABR.CORE_OFF
BTN_VA = PCAVE2 + ABR.BTN_OFF
CHEV_VA = PCAVE2 + ABR.CHEV_OFF
LUT_VA = PCAVE2 + ABR.LUT_OFF
SCRATCH_VA = PCAVE2 + ABR.SCRATCH_OFF
STAPLE_VA = PCAVE2 + ABR.STAPLE_OFF
SCRATCH48_VA = PCAVE2 + ABR.SCRATCH48_OFF
STAPLE_BTN = ABR.S["BTN_STAPLE"]
ARROW_VA = PCAVE2 + ABR.ARROW_OFF
SCRATCH_ARROW_VA = PCAVE2 + ABR.SCRATCH_ARROW_OFF
ARROW_BTNS = (ABR.S["BTN_ARROW1"], ABR.S["BTN_ARROW2"], ABR.S["BTN_ARROW3"])
G_ADDR = ABR.S["g_popup_scale_num"]
KSB_VA = ABR.S["KSB"]
PAL_VA = ABR.S["PALETTE"]
CHEV1 = ABR.S["BTN_CHEV1"]
CHEV2 = ABR.S["BTN_CHEV2"]
MENU = ABR.S["BTN_MENU"]
BAR_BTN = ABR.S["BASEWIN_BTN_LO"]          # btn0 — a bar-style button

BUF = 0x00300000
PIX = 0x00310000
STACK = 0x00200000
RETADDR = 0x00669900   # sentinel return inside a mapped page far from real code
PAGE = 0x1000

# The 4K-reconstructed chevron art.  Same fixture as test_scaling_laws.py:
# art colors at palette indices 0-8/10, 'a' = the key (9), blend rungs after,
# and index 9 carries a decoy color the nearest-search must never pick.
ART = [
    "abbbbbbbbbbbbbbbbbba",
    "bccccccccccccccccccb",
    "bddddddddddddddddedb",
    "bfccccccccccccccccgb",
    "bhgeddddddddddddehhb",
    "bggccccccccccccciggb",
    "bhhjeddddddddddejhhb",
    "bgggcccccccccccigggb",
    "bhhhheddddddddehhhhb",
    "bggggcccccccccgggggb",
    "bhhhhhedddddddhhhhhb",
    "bgggggkccccccggggggb",
    "bhhhhhheddddghhhhhhb",
    "bggggggiccccgggggggb",
    "bhhhhhhhedejhhhhhhhb",
    "bggggggggccggggggggb",
    "bhhhhhhhhghhhhhhhhhb",
    "bfgggggggggggggggggb",
    "bhhhhhhhhhhhhhhhhhhb",
    "abbbbbbbbbbbbbbbbbba",
]
CHEV_IDX = {"b": 0, "c": 1, "d": 2, "e": 3, "f": 4, "g": 5, "h": 6, "i": 7,
            "j": 8, "a": 9, "k": 10}
CHEV_PAL = [(176, 20, 20), (136, 69, 28), (136, 12, 12), (156, 16, 16),
            (92, 41, 13), (106, 31, 13), (68, 32, 12), (108, 52, 23),
            (76, 41, 13), (136, 40, 20), (122, 31, 29), (122, 53, 21),
            (75, 31, 15), (85, 43, 21)] + [(0, 255, 0)] * 242
SRC_IDX = [[CHEV_IDX[ch] for ch in row] for row in ART]
SW = SH = 20


def zoom(D: int) -> list[list[int]]:
    """Centre-aligned NN of the art INDICES (the engine blit law) — the
    post-zoom canvas state for the bar-button/KSB-stub cases."""
    return [
        [SRC_IDX[(2 * j + 1) * SH // (2 * D)][(2 * i + 1) * SW // (2 * D)]
         for i in range(D)]
        for j in range(D)
    ]


def model_v4(img, D, g):
    """v4's probe + P-law restripe on the post-zoom canvas; True if it fired."""
    a4, b4 = img[10][2], img[11][2]
    if a4 == b4 or a4 == 9 or b4 == 9:
        return False
    top = a4                       # ebx = (0 + 20//2) & 1 = 0 -> top = row-10 member
    P = SL.stripe_period(g)
    hN = (P + 1) >> 1
    bot = a4 ^ b4 ^ top
    for y in range(D):
        c = top if (y % P) < hN else bot
        for x in range(D):
            if img[y][x] in (a4, b4):
                img[y][x] = c
    return True


@pytest.fixture(scope="module")
def uc():
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    core = bytes(ks.asm(ABR.CORE, CORE_VA)[0])
    btn = bytes(ks.asm(ABR.BTN, BTN_VA)[0])
    chev = bytes(ks.asm(ABR.CHEV, CHEV_VA)[0])
    staple = bytes(ks.asm(ABR.STAPLE, STAPLE_VA)[0])
    arrow = bytes(ks.asm(ABR.ARROW, ARROW_VA)[0])
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    lo = min(CORE_VA, BTN_VA) & ~(PAGE - 1)
    hi = (PCAVE2 + 0x10000 + PAGE - 1) & ~(PAGE - 1)  # cover CHEV+LUT+SCRATCH+STAPLE+ARROW
    mu.mem_map(lo, hi - lo)
    mu.mem_write(CORE_VA, core)
    mu.mem_write(BTN_VA, btn)
    mu.mem_write(CHEV_VA, chev)
    mu.mem_write(STAPLE_VA, staple)
    mu.mem_write(ARROW_VA, arrow)
    mu.mem_write(LUT_VA, ABR.lut_bytes())             # the BAKED gamma LUT data
    # one 2-page map covers the KSB stub, g_popup_scale_num AND the RETADDR
    # sentinel (0x668000..0x66A000 — they share the page neighbourhood)
    mu.mem_map(KSB_VA & ~(PAGE - 1), 0x2000)
    mu.mem_write(KSB_VA, bytes([0xC2, 0x2C, 0x00]))   # ret 0x2C stub
    assert (KSB_VA & ~(PAGE - 1)) <= G_ADDR < (KSB_VA & ~(PAGE - 1)) + 0x2000
    assert (KSB_VA & ~(PAGE - 1)) <= RETADDR < (KSB_VA & ~(PAGE - 1)) + 0x2000
    # the REAL palette address, filled with the fixture palette (r,g,b,flags)
    mu.mem_map(PAL_VA & ~(PAGE - 1), 0x1000)
    mu.mem_write(PAL_VA, b"".join(bytes((r, gg, b, 0)) for r, gg, b in CHEV_PAL))
    for base, size in ((BUF, PAGE), (PIX, 0x10000), (STACK, PAGE)):
        mu.mem_map(base, size)
    return mu


def run_bandstripe(mu, g: int, esi: int, img, D: int, stride: int | None = None,
                   count: int = 500_000, sw: int = 20, sh: int | None = None,
                   dw: int | None = None, dh: int | None = None):
    """Call thunk_btn_bandstripe exactly as thunk_btn_2dscale does (11 args).

    `img` is the canvas CONTENT (list of rows, row pitch = stride, default D):
    post-zoom for bar cases, the native art for coverage cases.  Square cases
    pass D alone (sw x sw -> D x D); rect cases (the 12x42 arrows) pass
    sw/sh/dw/dh explicitly and D is only the default for stride/out width."""
    sh = sw if sh is None else sh
    dw = D if dw is None else dw
    dh = D if dh is None else dh
    stride = max(D, dw) if stride is None else stride
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little"))
    mu.mem_write(BUF + 0x54, PIX.to_bytes(4, "little"))
    mu.mem_write(BUF + 0x4A8, int(stride).to_bytes(4, "little", signed=True))
    mu.mem_write(PIX, b"\x00" * 0x10000)
    for j, row in enumerate(img):
        mu.mem_write(PIX + j * stride, bytes(row))
    mu.mem_write(SCRATCH_VA, b"\x00" * 400)
    mu.mem_write(SCRATCH48_VA, b"\x00" * 2304)
    mu.mem_write(SCRATCH_ARROW_VA, b"\x00" * 504)

    sp = STACK + 0x800
    args = [BUF, BUF, 0, 0, sw, sh, 0, 0, dw, dh, -1 & 0xFFFFFFFF]
    mu.mem_write(sp, RETADDR.to_bytes(4, "little"))
    for i, v in enumerate(args):
        mu.mem_write(sp + 4 + 4 * i, int(v).to_bytes(4, "little", signed=False))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ESI, esi)

    mu.emu_start(BTN_VA, RETADDR, count=count)

    assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C, "RET 0x2C contract broken"
    assert mu.reg_read(UC_X86_REG_ESI) == esi, "esi clobbered"
    out = mu.mem_read(PIX, stride * max(dh, sh))
    return [list(out[j * stride:j * stride + dw]) for j in range(dh)]


@pytest.mark.parametrize("g", (17, 20, 22, 25, 33, 40))
def test_chevron_coverage_is_a_bit_exact_port_of_the_law(uc, g: int):
    """The whole point of v8: the chevron canvas comes back EXACTLY
    scaling_laws.chevron_coverage_filter of the native art."""
    D = 20 * g // 16
    got = run_bandstripe(uc, g, CHEV1, SRC_IDX, D, count=60_000_000)
    want = SL.chevron_coverage_filter(SRC_IDX, CHEV_PAL, D)
    assert got == want, f"g={g}"


@pytest.mark.parametrize("g", (22, 40))
def test_second_chevron_takes_the_same_path(uc, g: int):
    D = 20 * g // 16
    got = run_bandstripe(uc, g, CHEV2, SRC_IDX, D, count=60_000_000)
    want = SL.chevron_coverage_filter(SRC_IDX, CHEV_PAL, D)
    assert got == want, f"g={g}"


def test_chevron_native_g_falls_through_to_the_ksb(uc):
    """dw == 20 (g<=16): the guard unwinds and tail-jmps the (stubbed) KSB —
    canvas byte-identical, the native no-op invariant."""
    D = 20
    got = run_bandstripe(uc, 16, CHEV1, SRC_IDX, D)
    assert got == SRC_IDX


# ---- v9: the nerve-staple button (btn16) coverage instance -----------------
# Deterministic 48x48 art exercising the same features as the real staple KSB
# fill: horizontal 1px stripe pair, a contiguous "face" blob sharing the
# stripe colors (the dither-pair-ambiguity that broke the restripe), isolated
# dark feature pixels, and a few key-9 texels.
def _staple_art():
    rows = []
    for y in range(48):
        row = []
        for x in range(48):
            if (x + y) % 23 == 0 and x > 40:
                row.append(9)                     # sparse key texels
            elif 12 <= x <= 34 and 10 <= y <= 40:
                if (x * 7 + y * 3) % 11 == 0:
                    row.append(6)                 # dark feature speckle
                elif x < 24:
                    row.append(2)                 # face flat red == stripe pair member
                else:
                    row.append(11 + (x + y) % 3)  # skin rungs
            else:
                row.append(2 if y % 2 == 0 else 0)  # bg stripe pair
        rows.append(row)
    return rows


STAPLE_SRC = _staple_art()


@pytest.mark.parametrize("g", (22, 25, 40))
def test_staple_coverage_is_a_bit_exact_port_of_the_law(uc, g: int):
    """btn16 routes to the N=48 coverage instance: canvas D x D comes back
    EXACTLY chevron_coverage_filter(48x48 art) — no restripe through the
    face, black feature pixels blended, key texels preserved."""
    D = 48 * g // 16
    got = run_bandstripe(uc, g, STAPLE_BTN, STAPLE_SRC, D, sw=48,
                         count=300_000_000)
    want = SL.chevron_coverage_filter(STAPLE_SRC, CHEV_PAL, D)
    assert got == want, f"g={g}"


def test_staple_native_g_falls_through_to_the_ksb(uc):
    """dw == 48 (g<=16): guard unwinds, tail-jmps the (stubbed) KSB —
    canvas byte-identical (native no-op)."""
    got = run_bandstripe(uc, 16, STAPLE_BTN, STAPLE_SRC, 48, sw=48)
    assert got == STAPLE_SRC


def test_staple_esi_no_longer_takes_the_restripe(uc):
    """The pre-v9 defect: btn16 fell into the BASEWIN range arm and the
    P-law restripe remapped the bg stripe pair THROUGH the face art.  v9
    must not restripe: the canvas equals the law output, which never equals
    the v4 restripe of the zoomed art (the fixture face guarantees a
    difference)."""
    g = 25
    D = 48 * g // 16
    got = run_bandstripe(uc, g, STAPLE_BTN, STAPLE_SRC, D, sw=48,
                         count=300_000_000)
    zoomed = [
        [STAPLE_SRC[(2 * j + 1) * 48 // (2 * D)][(2 * i + 1) * 48 // (2 * D)]
         for i in range(D)]
        for j in range(D)
    ]
    restriped = [r[:] for r in zoomed]
    model_v4(restriped, D, g)
    assert got != restriped


# ---------------------------------------------------------------------------
# v10: the garrison/HUD unit-row arrow buttons (12x42 RECT coverage instance)
# ---------------------------------------------------------------------------
def _arrow_art():
    """Synthetic 12x42 arrow: right-pointing triangle over key-9, interior a
    1px c/d stripe dither (the texture class the instance exists for), ring
    pixel at the flat edge for asymmetry."""
    W, H = 12, 42
    src = []
    for y in range(H):
        half = abs(2 * y + 1 - H) / 2
        span = max(0, round(W * (1 - 2 * half / H)))
        row = [9] * W
        for x in range(span):
            row[x] = 1 if (y & 1) else 2
        if span:
            row[0] = 0
        src.append(row)
    return src


ARROW_SRC = _arrow_art()

