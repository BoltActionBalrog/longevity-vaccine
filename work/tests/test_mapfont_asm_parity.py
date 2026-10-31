"""Differential: the BAKED thunk_map_font must agree with the Python reference.

`scaling_laws.map_label_font_size` is the source of truth; the x86 that ships (from
scripts/assemble_prefwin.py::asm_mapfont) is emulated here under Unicorn against it.

What it verifies, per g in [16,40] x pct in {0..100} x native size in [1,12]:
  * [esp+8] (the Font_init height arg) == map_label_font_size(native, g, pct)
  * ecx (the Font this-ptr) is preserved -- Font_init is thiscall
  * the name/style args and the site return address are untouched
  * pct=100 is bit-identical to the old thunk_hud_font law (native*g>>4)
  * pct=0 and g<=16 leave the height NATIVE (pristine)

Also pins the law itself: endpoint identities and monotonicity in pct (a rounding
slip in the (g-16)*pct/100 term would show as a non-monotonic size ladder).

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import map_label_font_size, popup_scale_floor  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_ECX,
    UC_X86_REG_ESP,
)

import assemble_prefwin as ap  # noqa: E402

CODE = ap.PCAVE2 + ap.MAP_FONT_OFF        # 0xA17130
PCT_ADDR = ap.PCAVE2 + ap.MAP_FONT_PCT_OFF
G_ADDR = ap.G                             # 0x668740 (real global)
ENSURE = ap.ENSURE_SCALE                  # 0x668760 -> stub RET in the harness
FONT_INIT = ap.FONT_INIT                  # 0x618F40 -> emulation stop point
STACK = 0x00200000
SITE_RET = 0x00462E72                     # the real site's return address
NAME_PTR = 0x00691B2C
PAGE = 0x1000


@pytest.fixture(scope="module")
def uc():
    blob = ap.assemble(ap.asm_mapfont(), CODE)
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in (CODE & ~(PAGE - 1), G_ADDR & ~(PAGE - 1), STACK, FONT_INIT & ~(PAGE - 1)):
        mu.mem_map(base, PAGE)
    mu.mem_write(CODE, blob)
    mu.mem_write(ENSURE, b"\xC3")          # ensure_scale: harness stub (idempotent no-op)
    return mu


def _run(uc, g: int, pct: int, native: int):
    mu = uc
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little", signed=True))
    mu.mem_write(PCT_ADDR, int(pct).to_bytes(4, "little", signed=True))

    sp = STACK + PAGE - 0x40
    mu.mem_write(sp, SITE_RET.to_bytes(4, "little"))
    mu.mem_write(sp + 4, NAME_PTR.to_bytes(4, "little"))
    mu.mem_write(sp + 8, int(native).to_bytes(4, "little", signed=True))
    mu.mem_write(sp + 12, (0).to_bytes(4, "little"))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ECX, 0x00934578)   # the base-name Font object

    mu.emu_start(CODE, FONT_INIT, count=64)

    esp = mu.reg_read(UC_X86_REG_ESP)
    assert esp == sp, "stack imbalance at the Font_init tail"
    height = int.from_bytes(mu.mem_read(sp + 8, 4), "little", signed=True)
    name = int.from_bytes(mu.mem_read(sp + 4, 4), "little")
    style = int.from_bytes(mu.mem_read(sp + 12, 4), "little")
    ret = int.from_bytes(mu.mem_read(sp, 4), "little")
    ecx = mu.reg_read(UC_X86_REG_ECX)
    return height, name, style, ret, ecx


@pytest.mark.parametrize("g", range(16, 41))
@pytest.mark.parametrize("pct", (0, 1, 25, 50, 75, 99, 100))
def test_asm_matches_the_law(uc, g: int, pct: int):
    for native in (1, 3, 7, 9, 12):
        height, name, style, ret, ecx = _run(uc, g, pct, native)
        assert height == map_label_font_size(native, g, pct), (g, pct, native)
        assert (name, style, ret) == (NAME_PTR, 0, SITE_RET), "clobbered a neighbor arg"
        assert ecx == 0x00934578, "clobbered ecx (the Font this-ptr)"


@pytest.mark.parametrize("g", range(16, 41))
def test_pct_100_is_the_pre_slider_bake(uc, g: int):
    """The slider's right endpoint must be BIT-IDENTICAL to the thunk_hud_font
    redirect this thunk replaced (native*g>>4) -- the verified 2026-07-12i look."""
    for native in range(1, 13):
        height, *_ = _run(uc, g, 100, native)
        want = native if g <= 16 else popup_scale_floor(native, g)
        assert height == want, (g, native)


@pytest.mark.parametrize("g", range(16, 41))
def test_pct_0_is_pristine(uc, g: int):
    for native in range(1, 13):
        height, *_ = _run(uc, g, 0, native)
        assert height == native, (g, native)


def test_g16_is_native_at_every_pct(uc):
    for pct in range(0, 101, 10):
        height, *_ = _run(uc, 16, pct, 12)
        assert height == 12


def test_law_monotonic_in_pct():
    """Law-level: the size ladder never steps DOWN as the slider moves right."""
    for g in range(17, 41):
        for native in range(1, 13):
            sizes = [map_label_font_size(native, g, pct) for pct in range(0, 101)]
            assert sizes == sorted(sizes), (g, native)
            assert sizes[0] == native
            assert sizes[-1] == popup_scale_floor(native, g)
