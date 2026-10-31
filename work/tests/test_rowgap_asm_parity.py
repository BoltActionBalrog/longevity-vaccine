"""Differential: the BAKED thunk_rowgap v2 must agree with the Python reference.

`scaling_laws.py` is the source of truth; the x86 that ships is checked against
it here by emulating the REAL assembled bytes of `thunk_rowgap` (from
scripts/assemble_rowgap.py) under Unicorn.

What it verifies, per g in [16,40] and a sweep of field values / row counts:
  * [D+0x44] on return == dialog_row_margin(field_in, g)   (render + hit-test
    re-read the field)
  * ecx on return == [D+0x68] + [D+0x44]_out (the pitch the caller multiplies
    into content_h)
  * at g <= 16 NOTHING is written — the no-op v1 (gated on ScreenWidth >
    0x3FF) violated at 1024x768
  * single-row dialogs ([D+0x58] <= 1) are untouched at every g
  * the transform is idempotent across the calc's two passes
  * eax (the data-region base) is preserved

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import NATIVE_G, dialog_row_margin  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_ECX,
    UC_X86_REG_ESP,
)

CODE = 0x00668C00          # the thunk's real VA (menu_strip_thunks + 0xA00)
G_ADDR = 0xDEADBE00        # the sentinel the assembler leaves for g_popup_scale_num
DIALOG = 0x00300000        # scratch data-region base (eax at the site)
STACK = 0x00200000
RETADDR = 0x0060F020       # where the CALL returns: `pop esi; imul ecx,[eax+0x58]`

SLOT_LIMIT = 0x30          # g_boxw_num sits at cave offset 0xA30

# line-height scratch value + the one measured native margin (struct-copy default)
PREF_LH = 23
NATIVE_MARGIN = 3

PAGE = 0x1000


def _assemble() -> bytes:
    """Assemble the SAME source the bake uses, with the sentinel left in place."""
    src = (SCRIPTS / "assemble_rowgap.py").read_text(encoding="utf-8")
    asm = src.split('ASM = r"""')[1].split('"""')[0]
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    code, _ = ks.asm(asm, addr=CODE)
    return bytes(code)


@pytest.fixture(scope="module")
def uc():
    """One Uc for the whole module (fresh instances leak maps — see bandmap)."""
    blob = _assemble()
    assert len(blob) <= SLOT_LIMIT, "thunk_rowgap no longer fits its cave slot"
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in (CODE & ~(PAGE - 1), G_ADDR & ~(PAGE - 1), DIALOG, STACK):
        mu.mem_map(base, PAGE)
    mu.mem_write(CODE, blob)
    return mu, blob


def _run(uc, g: int, margin_in: int, line_h: int = PREF_LH, rows: int = 8):
    mu, blob = uc
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little", signed=True))
    mu.mem_write(DIALOG + 0x44, int(margin_in).to_bytes(4, "little", signed=True))
    mu.mem_write(DIALOG + 0x58, int(rows).to_bytes(4, "little", signed=True))
    mu.mem_write(DIALOG + 0x68, int(line_h).to_bytes(4, "little", signed=True))

    sp = STACK + PAGE - 8
    mu.mem_write(sp, RETADDR.to_bytes(4, "little"))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EAX, DIALOG)
    mu.reg_write(UC_X86_REG_ECX, 0xCCCCCCCC)

    mu.emu_start(CODE, RETADDR, count=64)      # runs until the RET pops RETADDR

    ecx = mu.reg_read(UC_X86_REG_ECX)
    eax = mu.reg_read(UC_X86_REG_EAX)
    margin_out = int.from_bytes(mu.mem_read(DIALOG + 0x44, 4), "little", signed=True)
    return ecx, margin_out, eax


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("margin_in", range(0, 9))
def test_asm_margin_matches_the_reference(uc, g: int, margin_in: int):
    ecx, margin_out, eax = _run(uc, g, margin_in)
    assert eax == DIALOG, "thunk clobbered eax — caller reads [eax+0x58] next"

    expect = dialog_row_margin(margin_in, g)
    assert margin_out == expect, f"g={g} in={margin_in}: asm {margin_out} != law {expect}"
    assert ecx == PREF_LH + expect, f"g={g} in={margin_in}: pitch {ecx}"


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
def test_asm_is_a_noop_at_native_and_for_single_rows(uc, g: int):
    """The two gates. v1's ScreenWidth>0x3FF gate fired at 1024x768; the g-gate
    cannot (it never sees a width). Single-row dialogs stay native at every g."""
    if g <= NATIVE_G:
        ecx, margin_out, _ = _run(uc, g, NATIVE_MARGIN)
        assert (margin_out, ecx) == (NATIVE_MARGIN, PREF_LH + NATIVE_MARGIN)
    ecx, margin_out, _ = _run(uc, g, NATIVE_MARGIN, rows=1)
    assert (margin_out, ecx) == (NATIVE_MARGIN, PREF_LH + NATIVE_MARGIN)


@pytest.mark.parametrize("g", (22, 25, 40))
def test_asm_is_bit_identical_to_v1_above_native(uc, g: int):
    """v1's g>16 output (floor(3g/16)) is user-verified at these three
    resolutions; v2 must not move those screens."""
    _, margin_out, _ = _run(uc, g, NATIVE_MARGIN)
    assert margin_out == (3 * g) >> 4


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("margin_in", (0, 1, 2, 3))
def test_asm_is_idempotent_across_the_calcs_two_passes(uc, g: int, margin_in: int):
    """The calc runs twice per build and the field persists; pass two must be a
    fixed point (this is what the scale-only-the-measured-native map buys)."""
    _, m1, _ = _run(uc, g, margin_in)
    _, m2, _ = _run(uc, g, m1)
    assert m1 == m2, f"g={g} in={margin_in}: {margin_in} -> {m1} -> {m2}"
