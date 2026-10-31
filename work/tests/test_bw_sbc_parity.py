"""Unicorn parity for thunk_bw_sbc v3 (assemble_basewin.asm_sbc, pcave2+0xB9F0): the 8 BaseWin_psych_row
citizen-face sites.  CALL helper with Sprite_blit_scaled_core's contract (thiscall ecx=Sprite; dest, key,
x, y; RET 0x10).  On the scaled center canvas: x,y -> basewin_pt, then ONE call of thunk_face_hybrid
(Sprite_draw_2 contract) with num/den = g/16 (scaling_laws.basewin_pop_face_enlarge == 'hybrid') and a
clean RET 0x10 to the site; off-gate -> the engine core with the entry stack intact.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn", reason="unicorn absent -- asm parity unverified")
from keystone import Ks, KS_ARCH_X86, KS_MODE_32  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP,  # noqa: E402
                               UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_basewin as AB  # noqa: E402
    import assemble_rw_kinds as RK  # noqa: E402

VA = AB.PCAVE2 + AB.SBC_OFF
G_ADDR = 0xDEADBE00
STACK = 0x00200000
RET_PAD = 0x00400100
REC = 0x00400800                 # bilinear recorder: ecx, dest, key, x, y, num, den
SPRITE = 0x00C0FFEE
KS = Ks(KS_ARCH_X86, KS_MODE_32)
CODE = bytes(KS.asm(AB.asm_sbc(), addr=VA)[0])


def test_fits_its_slot_and_targets_the_pinned_face_hybrid():
    assert AB.SBC_OFF + len(CODE) <= AB.G_BW_RET_OFF
    assert AB.SPRITE_BILINEAR == RK.SPRITE_BILINEAR
    assert AB.FACE_HYBRID == RK.FACE_HYBRID
    assert AB.FACE_HYBRID.to_bytes(4, "little") in CODE and AB.SPRITE_BILINEAR.to_bytes(4, "little") not in CODE


def mk(g, canvas_w):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in (VA & ~0xFFF, AB.FACE_HYBRID & ~0xFFF, AB.SPRITE_BLIT_CORE & ~0xFFF,
                 G_ADDR & ~0xFFF, AB.CANVAS_W & ~0xFFF, 0x400000):
        try:
            uc.mem_map(base, 0x1000)
        except Exception:
            pass
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(VA, CODE)
    uc.mem_write(G_ADDR, g.to_bytes(4, "little"))
    uc.mem_write(AB.CANVAS_W, canvas_w.to_bytes(4, "little"))
    rec = "".join(f"mov eax, [esp+{4 + 4 * i:#x}]; mov [{REC + 4 + 4 * i:#x}], eax;" for i in range(6))
    uc.mem_write(AB.FACE_HYBRID, bytes(KS.asm(f"mov [{REC:#x}], ecx;" + rec + "ret 0x18",
                                              AB.FACE_HYBRID)[0]))
    return uc


def call(uc, args, until):
    esp = STACK + 0x8000
    for v in reversed([RET_PAD] + args):
        esp -= 4
        uc.mem_write(esp, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, SPRITE)
    for r, v in ((UC_X86_REG_EBX, 0xB1), (UC_X86_REG_ESI, 0x51), (UC_X86_REG_EDI, 0xD1), (UC_X86_REG_EBP, 0xB9)):
        uc.reg_write(r, v)
    uc.emu_start(VA, until, count=10_000)
    return esp


def rm(uc, a):
    return int.from_bytes(uc.mem_read(a, 4), "little")


@pytest.mark.parametrize("g", (17, 22, 25, 40, 45))
@pytest.mark.parametrize("x,y", [(0, 0), (37, 211), (700, 5)])
def test_scaled_canvas_goes_through_the_bilinear(g, x, y):
    uc = mk(g, SL.basewin_pt(AB.W_NATIVE, g) + 1 if SL.basewin_pt(AB.W_NATIVE, g) <= AB.W_NATIVE else
            SL.basewin_pt(AB.W_NATIVE, g))
    esp = call(uc, [AB.CANVAS, 9, x, y], RET_PAD)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4 + 0x10               # RET 0x10, site ret consumed
    assert [rm(uc, REC + 4 * i) for i in range(7)] == [
        SPRITE, AB.CANVAS, 9, SL.basewin_pt(x, g), SL.basewin_pt(y, g), g, 16]
    assert (g, 16) == SL.basewin_sprite_ratio(1, 1, g) and SL.basewin_pop_face_enlarge(g) == "hybrid"
    assert [uc.reg_read(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)] == \
        [0xB1, 0x51, 0xD1, 0xB9]


@pytest.mark.parametrize("dest,canvas_w", [(AB.CANVAS, AB.W_NATIVE), (0x123456, 1895)])
def test_off_gate_is_the_engine_core_untouched(dest, canvas_w):
    uc = mk(16 if dest == AB.CANVAS else 40, canvas_w)
    esp = call(uc, [dest, 9, 37, 211], AB.SPRITE_BLIT_CORE)
    assert uc.reg_read(UC_X86_REG_ESP) == esp and uc.reg_read(UC_X86_REG_ECX) == SPRITE
    assert [rm(uc, esp + 4 * i) for i in range(5)] == [RET_PAD, dest, 9, 37, 211]
    assert rm(uc, REC) == 0                                            # the bilinear never ran
