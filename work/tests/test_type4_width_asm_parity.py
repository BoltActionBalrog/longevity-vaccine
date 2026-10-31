"""Differential: thunk_t4_winw / thunk_t4_colw must agree with the Python laws.

`scaling_laws.py::type4_dialog_width` / `type4_column_width` are the source of
truth for the type-4 (text-entry) dialog's window and column width; the x86
(scripts/assemble_type4_width.py) is emulated under Unicorn against them.

  * g <= 16 and fixed-width dialogs return the displaced load unchanged
  * the Dialog fields are never written ([+0x2c] is a shared native source)
  * winw preserves eax (the GraphicWin_init this); colw preserves eax/ecx/ebp
  * the measured screens: base rename (#xs 440 -> native 660) and first-base
    name entry (#xs 320 -> 480) reach floor(min_w*g/16)

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scaling_laws import NATIVE_G, type4_column_width, type4_dialog_width  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESP,
)

import assemble_type4_width as gen  # noqa: E402

CODE_WINW = 0x00A1BBE0         # pcave2 0xA0C000 + 0xFBE0
CODE_COLW = 0x00A1BC20         # pcave2 + 0xFC20
G_ADDR = 0xDEADBE00
BASE = 0x00301000              # the Dialog vbase pointer the sites hold (fields at BASE - 0xa..)
STACK = 0x00200000
RET = 0x00611B8A
PAGE = 0x1000

F_MIN, F_FLAGS, F_ITEMW, F_COLW, F_COLS = -0xA78, -0xA84, -0xA48, -0xA40, -0xA58


@pytest.fixture(scope="module")
def uc():
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in (CODE_WINW & ~(PAGE - 1), G_ADDR & ~(PAGE - 1), BASE - PAGE, STACK):
        mu.mem_map(base, PAGE)
    winw, colw = gen.assemble(gen.ASM_WINW, CODE_WINW), gen.assemble(gen.ASM_COLW, CODE_COLW)
    assert CODE_WINW + len(winw) <= CODE_COLW, "thunk_t4_winw overruns thunk_t4_colw"
    assert len(colw) <= 0xFDB0 - 0xFC20, "thunk_t4_colw overruns thunk_pp_layout"
    mu.mem_write(CODE_WINW, winw)
    mu.mem_write(CODE_COLW, colw)
    return mu


def _w4(mu, addr, v):
    mu.mem_write(addr, int(v).to_bytes(4, "little", signed=True))


def _r4(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little", signed=True)


def _run(mu, code, g, min_w, item_w, col_w, cols, flags=0):
    _w4(mu, G_ADDR, g)
    for off, v in ((F_MIN, min_w), (F_FLAGS, flags), (F_ITEMW, item_w), (F_COLW, col_w), (F_COLS, cols)):
        _w4(mu, BASE + off, v)
    sp = STACK + PAGE - 0x40
    _w4(mu, sp, RET)
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EAX, BASE if code == CODE_COLW else 0x00C0FFEE)
    mu.reg_write(UC_X86_REG_ECX, BASE if code == CODE_WINW else 0x00000BAD)
    mu.reg_write(UC_X86_REG_EDX, 0x5EED)
    mu.reg_write(UC_X86_REG_EBP, 0x00EB9EB9)
    mu.emu_start(code, RET, count=64)
    assert mu.reg_read(UC_X86_REG_ESP) == sp + 4, "unbalanced stack"
    assert mu.reg_read(UC_X86_REG_EBP) == 0x00EB9EB9
    # the Dialog fields are read-only for these helpers
    assert (_r4(mu, BASE + F_MIN), _r4(mu, BASE + F_ITEMW), _r4(mu, BASE + F_COLW)) == (min_w, item_w, col_w)
    return mu


CASES = [(660, 660, 1), (660, 700, 1), (480, 480, 1), (480, 1300, 1), (0, 10, 1), (660, 1650, 1),
         (480, 480, 2), (660, 661, 3)]


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("min_w,item_w,cols", CASES)
@pytest.mark.parametrize("flags", (0, 2, 1, 3))
def test_winw_matches_the_law(uc, g, min_w, item_w, cols, flags):
    mu = _run(uc, CODE_WINW, g, min_w, item_w, item_w // cols, cols, flags)
    assert mu.reg_read(UC_X86_REG_EAX) == 0x00C0FFEE, "clobbered eax (GraphicWin_init this)"
    assert mu.reg_read(UC_X86_REG_ECX) == type4_dialog_width(min_w, item_w, g, bool(flags & 2))


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("min_w,item_w,cols", CASES)
@pytest.mark.parametrize("flags", (0, 2, 1, 3))
def test_colw_matches_the_law(uc, g, min_w, item_w, cols, flags):
    col_w = item_w // cols
    mu = _run(uc, CODE_COLW, g, min_w, item_w, col_w, cols, flags)
    assert mu.reg_read(UC_X86_REG_EAX) == BASE and mu.reg_read(UC_X86_REG_ECX) == 0x00000BAD
    got = mu.reg_read(UC_X86_REG_EDX)
    assert got == type4_column_width(min_w, col_w, cols, g, bool(flags & 2))
    if cols == 1:
        assert got == type4_dialog_width(min_w, item_w, g, bool(flags & 2))


@pytest.mark.parametrize("min_w,item_w", [(660, 660), (480, 480), (660, 900)])
def test_native_is_the_displaced_load(uc, min_w, item_w):
    assert type4_dialog_width(min_w, item_w, NATIVE_G) == item_w
    assert type4_column_width(min_w, item_w, 1, NATIVE_G) == item_w


def test_the_measured_popups():
    """Base rename (#xs 440 -> 660 in the >1023 regime) and first-base name
    entry (#xs 320 -> 480): the dialog was ~native wide at every g; lawful
    width is the native #xs x g/16, the content width of the scaled box."""
    assert type4_dialog_width(660, 672, 40) == 1650       # 4K, was ~672
    assert type4_dialog_width(660, 666, 25) == 1031       # 1600x1200, was ~666
    assert type4_dialog_width(480, 485, 40) == 1200
    # device-measured content wider than the scaled minimum wins unchanged
    assert type4_dialog_width(480, 1300, 40) == 1300
