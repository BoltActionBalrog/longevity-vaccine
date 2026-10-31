"""Differential: the BAKED thunk_q16_rowgap must agree with the Python reference.

`scaling_laws.py` is the source of truth; `scaling_laws.js` is checked against it by
test_scaling_js_parity.py; and the x86 that actually ships is checked against it here,
by emulating the REAL assembled bytes of `thunk_q16_rowgap` (from
scripts/assemble_q16gap.py) under Unicorn.

What it verifies, per g in [16,40] and a sweep of row heights:
  * ecx on return == the faithful row PITCH (what the caller multiplies into content_h)
  * [D+0x44] == option_row_gap(...)     (what the DRAW loop re-reads at 0x60d8f3)
  * at g <= 16 NOTHING is written and ecx == rowH + native gap (the no-op invariant)
  * eax (the Dialog base) is preserved

Why emulate rather than read the source: the thunk does a signed `sar` on a value it
just built with `imul`+`add`, clamps a negative gap through a `jge`, and WRITES a field
the draw loop reads later. A sign error or a clobbered eax is invisible in a screenshot
and fatal in a code cave.

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import NATIVE_G, option_row_gap, scale_px  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_ESP,
)

CODE = 0x00A16740          # the thunk's real VA (pcave2 + 0xA740)
G_ADDR = 0xDEADBE00        # the sentinel the assembler leaves for g_popup_scale_num
DIALOG = 0x00300000        # scratch Dialog base (D)
STACK = 0x00200000
RETADDR = 0x0060D739       # where the CALL returns: `pop esi; imul ecx,[eax+0x58]`

VANILLA_PITCH = 22         # measured on the pristine exe
NATIVE_GAP = 3             # measured on the pristine exe ([D+0x44])

PAGE = 0x1000


def _assemble() -> bytes:
    """Assemble the SAME source the bake uses, with the sentinel left in place."""
    src = (SCRIPTS / "assemble_q16gap.py").read_text(encoding="utf-8")
    asm = src.split('ASM = r"""')[1].split('"""')[0]
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    code, _ = ks.asm(asm, addr=CODE)
    return bytes(code)


@pytest.fixture(scope="module")
def uc():
    """One Uc for the whole module: a fresh instance per case maps megabytes and
    hard-faults the process after ~1000 cases (learned the hard way on bandmap)."""
    blob = _assemble()
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in (CODE & ~(PAGE - 1), G_ADDR & ~(PAGE - 1), DIALOG, STACK):
        mu.mem_map(base, PAGE)
    mu.mem_write(CODE, blob)
    return mu, blob


def _run(uc, g: int, row_h: int, gap_in: int = NATIVE_GAP):
    mu, blob = uc
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little", signed=True))
    mu.mem_write(DIALOG + 0x68, int(row_h).to_bytes(4, "little", signed=True))
    mu.mem_write(DIALOG + 0x44, int(gap_in).to_bytes(4, "little", signed=True))

    sp = STACK + PAGE - 8
    mu.mem_write(sp, RETADDR.to_bytes(4, "little"))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EAX, DIALOG)
    mu.reg_write(UC_X86_REG_ECX, 0xCCCCCCCC)
    mu.reg_write(UC_X86_REG_EDX, 0xCCCCCCCC)

    mu.emu_start(CODE, RETADDR, count=64)      # runs until the RET pops RETADDR

    ecx = mu.reg_read(UC_X86_REG_ECX)
    eax = mu.reg_read(UC_X86_REG_EAX)
    gap_out = int.from_bytes(mu.mem_read(DIALOG + 0x44, 4), "little", signed=True)
    return ecx, gap_out, eax


def _drawn_row_h(g: int) -> int:
    """What the calc puts in [D+0x68]: Buffer_text_height (19) at native, and
    Buffer_text_line_height once thunk_quit_rowpitch engages."""
    return 19 if g == NATIVE_G else scale_px(20, g)


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
def test_asm_gap_matches_the_reference(uc, g: int):
    row_h = _drawn_row_h(g)
    ecx, gap_out, eax = _run(uc, g, row_h)

    assert eax == DIALOG, "thunk clobbered eax (the Dialog base) — caller reads [eax+0x58] next"

    if g <= NATIVE_G:
        # Native no-op: field untouched, pitch is exactly the bytes we replaced.
        assert gap_out == NATIVE_GAP, f"g={g} wrote the gap field on the native path"
        assert ecx == row_h + NATIVE_GAP
        return

    expect_gap = option_row_gap(VANILLA_PITCH, row_h, g)
    assert gap_out == expect_gap, f"g={g}: asm gap {gap_out} != law {expect_gap}"
    assert ecx == row_h + expect_gap, f"g={g}: asm pitch {ecx} != {row_h + expect_gap}"


@pytest.mark.parametrize("g", range(NATIVE_G + 1, 41))   # g = 16: the native path is gated off (engine's own pitch)
def test_asm_pitch_is_exactly_faithful(uc, g: int):
    """The whole point: ecx is the pitch the caller multiplies into content_h,
    and it must be vanilla * g/16 at every resolution."""
    ecx, _, _ = _run(uc, g, _drawn_row_h(g))
    assert ecx == scale_px(VANILLA_PITCH, g)


def test_asm_reproduces_the_measured_engine_values(uc):
    """The four in-game runs (frida_q16gap*.log), replayed against the bytes."""
    for g, row_h, want_gap, want_pitch in ((22, 27, 3, 30), (25, 31, 3, 34), (40, 50, 5, 55)):
        ecx, gap_out, _ = _run(uc, g, row_h)
        assert (gap_out, ecx) == (want_gap, want_pitch), g

    # 1024x768: no FIX line was logged, and the field must stay 3.
    ecx, gap_out, _ = _run(uc, 16, 19)
    assert (gap_out, ecx) == (3, 22)


@pytest.mark.parametrize("g", (29, 34, 40))
def test_asm_clamps_a_row_taller_than_the_pitch(uc, g: int):
    """A font whose line height exceeds the scaled pitch must not yield a NEGATIVE
    gap — that would drive rows backwards and the `imul` into a negative content_h."""
    tall = scale_px(VANILLA_PITCH, g) + 7
    ecx, gap_out, _ = _run(uc, g, tall)
    assert gap_out == 0
    assert ecx == tall


def test_asm_is_idempotent_across_the_calcs_two_passes(uc):
    """The calc runs twice per popup. The gap is derived from g and rowH, never from
    its own prior value, so pass two must be a fixed point (prototype: `gap 5 -> 5`)."""
    _, gap1, _ = _run(uc, 40, 50, gap_in=NATIVE_GAP)
    _, gap2, _ = _run(uc, 40, 50, gap_in=gap1)
    assert gap1 == gap2 == 5


def test_asm_ignores_an_unmeasured_row(uc):
    """rowH <= 0 means nothing was measured; fall through to the vanilla bytes
    rather than inventing a pitch."""
    ecx, gap_out, _ = _run(uc, 40, 0)
    assert gap_out == NATIVE_GAP
    assert ecx == NATIVE_GAP
