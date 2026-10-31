"""Differential: the BAKED thunk_popup_min_boxh must agree with the Python law.

`scaling_laws.py::ingame_popup_min_boxh` is the source of truth; the x86 that
ships is checked against it here by emulating the REAL assembled bytes (from
scripts/assemble_popup_minboxh.py) under Unicorn.

Per g in [16,40] and a sweep of box heights:
  * [popup+0x30c0] on return == law box_h' (own-window and embedded arms)
  * [popup+0x30ec] grows by exactly the law's footer_delta
  * g <= 16 is bit-for-bit the displaced vanilla block (M = 300)
  * boxes at/above the target pass through untouched (footer unchanged)
  * esi (the popup this) is preserved — the caller still owns it

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import (  # noqa: E402
    NATIVE_G,
    ingame_popup_min_boxh,
    ingame_popup_window_h,
)

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

CODE = 0x00A0C3B0          # the thunk's real VA (pcave2 0xA0C000 + 0x3B0)
G_ADDR = 0xDEADBE00        # the sentinel the assembler leaves for g_popup_scale_num
POPUP = 0x00300000         # scratch popup base (esi at the site)
STACK = 0x00200000
RETADDR = 0x00404EC2       # the byte after the site's E8 (mid NOP sled)

FOOTER_SEED = 125          # a plausible scaled [+0x30ec] before the clamp

PAGE = 0x1000
BOX_SWEEP = (0, 1, 100, 136, 299, 300, 301, 349, 468, 749, 750, 751, 2000)


def _assemble() -> bytes:
    """Assemble the SAME source the bake uses, with the sentinel left in place."""
    src = (SCRIPTS / "assemble_popup_minboxh.py").read_text(encoding="utf-8")
    asm = src.split('ASM = r"""')[1].split('"""')[0]
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    code, _ = ks.asm(asm, addr=CODE)
    return bytes(code)


@pytest.fixture(scope="module")
def uc():
    """One Uc for the whole module (fresh instances leak maps — see bandmap)."""
    blob = _assemble()
    assert len(blob) <= 0x50, "thunk_popup_min_boxh overruns its slot (thunk_btn_shrink @0x400)"
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in (
        (CODE & ~(PAGE - 1), PAGE),
        (G_ADDR & ~(PAGE - 1), PAGE),
        (POPUP, 4 * PAGE),          # the fields sit at +0xA3C/+0x30C0/+0x30D0/+0x30EC
        (STACK, PAGE),
    ):
        mu.mem_map(base, size)
    mu.mem_write(CODE, blob)
    return mu, blob


def _run(uc, g: int, box_in: int, footer_in: int = FOOTER_SEED, btn: int = 20, own: bool = True):
    mu, blob = uc
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little", signed=True))
    mu.mem_write(POPUP + 0x30C0, int(box_in).to_bytes(4, "little", signed=True))
    mu.mem_write(POPUP + 0x30EC, int(footer_in).to_bytes(4, "little", signed=True))
    mu.mem_write(POPUP + 0x30D0, int(btn).to_bytes(4, "little", signed=True))
    # [+0xa3c] attach parent: the popup itself (own window) or a host window
    mu.mem_write(POPUP + 0xA3C, (POPUP if own else 0x007AE820).to_bytes(4, "little"))

    sp = STACK + PAGE - 8
    mu.mem_write(sp, RETADDR.to_bytes(4, "little"))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ESI, POPUP)

    mu.emu_start(CODE, RETADDR, count=64)      # runs until the RET pops RETADDR

    esi = mu.reg_read(UC_X86_REG_ESI)
    box_out = int.from_bytes(mu.mem_read(POPUP + 0x30C0, 4), "little", signed=True)
    footer_out = int.from_bytes(mu.mem_read(POPUP + 0x30EC, 4), "little", signed=True)
    return box_out, footer_out, esi


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("own", (True, False))
@pytest.mark.parametrize("btn", (0, 20, 35))
@pytest.mark.parametrize("box_in", BOX_SWEEP)
def test_asm_matches_the_reference(uc, g: int, own: bool, btn: int, box_in: int):
    box_out, footer_out, esi = _run(uc, g, box_in, btn=btn, own=own)
    assert esi == POPUP, "thunk clobbered esi — the caller's popup this"

    want_box, want_delta = ingame_popup_min_boxh(box_in, g, btn, own)
    assert box_out == want_box, f"g={g} box={box_in}: asm {box_out} != law {want_box}"
    assert footer_out == FOOTER_SEED + want_delta, (
        f"g={g} box={box_in}: footer {footer_out} != {FOOTER_SEED}+{want_delta}")


@pytest.mark.parametrize("box_in", BOX_SWEEP)
def test_asm_is_the_displaced_vanilla_block_at_native(uc, box_in: int):
    """g=16: bit-for-bit vanilla — M is the engine's own 300."""
    box_out, footer_out, _ = _run(uc, NATIVE_G, box_in, footer_in=50)
    want_box = max(box_in, 300)
    assert (box_out, footer_out) == (want_box, 50 + want_box - box_in)


@pytest.mark.parametrize("g", (22, 25, 40))
def test_asm_pins_the_shipped_resolutions(uc, g: int):
    """Window height M at the three shipping non-native resolutions: the box
    target is M - D (D = the 20-px button row's growth, added by exec_3), incl.
    the namebase repro (box 349 @4K -> 720, window 750, footer +371)."""
    m = {22: 412, 25: 468, 40: 750}[g]
    d = {22: 7, 25: 11, 40: 30}[g]
    box_out, footer_out, _ = _run(uc, g, 0, footer_in=0)
    assert (box_out, footer_out) == (m - d, m - d)
    assert ingame_popup_window_h(0, g) == box_out + d == m
    if g == 40:
        box_out, footer_out, _ = _run(uc, g, 349, footer_in=0)
        assert (box_out, footer_out) == (720, 371)


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
def test_asm_leaves_tall_popups_untouched(uc, g: int):
    """box >= target: no write anywhere (quit/customize keep their verified laws)."""
    box_out, footer_out, _ = _run(uc, g, 3000)
    assert (box_out, footer_out) == (3000, FOOTER_SEED)


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("own", (True, False))
def test_asm_target_boundary(uc, g: int, own: bool):
    """The jge boundary at every g: target-1 is lifted by exactly 1, target and
    target+1 are untouched. Own window: target = M - D and the created window
    (box + D) is M; embedded ([+0xa3c] != popup, never grown): target = M."""
    m = (300 * g) >> 4
    d = ((20 * g) >> 4) - 20
    t = m - d if own else m
    assert _run(uc, g, t - 1, own=own)[:2] == (t, FOOTER_SEED + 1)
    assert _run(uc, g, t, own=own)[:2] == (t, FOOTER_SEED)
    assert _run(uc, g, t + 1, own=own)[:2] == (t + 1, FOOTER_SEED)
    if own:
        assert ingame_popup_window_h(t - 1, g) == m
