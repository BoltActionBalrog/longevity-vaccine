"""Differential: the slice-10 box_2-polish thunks must agree with scaling_laws
bit-exactly.

thunk_bw_box2ring (Buffer_box_2 replacement callee; production current-turn
site 0x40ED80 + thunk_bw_box2's scaled tail): draws the vanilla outline then
K-1 nested INWARD rings, K = stroke_width(g) (law box2_ring_rects).  Ring 0
unconditional -> g<=16 is exactly one vanilla-rect call; degenerate inner
rings stop the loop; callee-saved regs preserved; RET 0xC.

thunk_bw_box2 v2 (nutrients site 0x4116A5): gate ecx==canvas && canvasW>758
-> rect scaled into g_bw_rect, tail-jmp the ring thunk; gate off -> plain
BOX_2 with the caller's rect ptr untouched.

thunk_bw_popbox_pads / thunk_bw_popbox_text (base_draw cuts @0x55B3CF /
0x55B605+0x55B675): pop-number box pads +5/+4 and glyph pen +2/+1 scale per
base_popbox_pads, gated esi == BaseWin canvas (farm view); native path
byte-equivalent; popbox_text is pushfd/popfd EFLAGS-transparent (its cuts sit
between a live `test` and the consuming `je`).

Emulated with the REAL assembled bytes (sentinel g page at 0xDEADB000; the
yaml resolves the placeholder to 0x668740 at apply time).

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_HOOK_CODE, UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import assemble_basewin as ASB  # noqa: E402
import scaling_laws as SL  # noqa: E402

RING_VA = ASB.PCAVE2 + ASB.BOX2RING_OFF
BOX2_VA = ASB.PCAVE2 + ASB.BOX2_OFF
PADS_VA = ASB.PCAVE2 + ASB.POPBOX_PADS_OFF
TEXT_VA = ASB.PCAVE2 + ASB.POPBOX_TEXT_OFF
RING_CODE = ASB.raw("box2ring", ASB.BOX2RING_OFF, ASB.asm_box2ring())
BOX2_CODE = ASB.raw("box2", ASB.BOX2_OFF, ASB.asm_box2())
PADS_CODE = ASB.raw("popbox_pads", ASB.POPBOX_PADS_OFF, ASB.asm_popbox_pads())
TEXT_CODE = ASB.raw("popbox_text", ASB.POPBOX_TEXT_OFF, ASB.asm_popbox_text())

G_SENT = 0xDEADBE00
CANVAS = ASB.CANVAS                      # 0x6A7A6C
CANVAS_W = ASB.CANVAS_W                  # 0x6A7AEC
BOX_2 = ASB.BOX_2                        # 0x5E3203
G_RING_RECT = ASB.G_RING_RECT
G_BW_RECT = ASB.G_BW_RECT
SITE_RET = 0x0040ED85                    # any mapped stop address
ARITH_FLAGS = 0x8D5                      # CF|PF|AF|ZF|SF|OF

STACK = 0x00200000
MARKS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x44444444,
         UC_X86_REG_EDI: 0x55555555, UC_X86_REG_EBP: 0x66666666}


def _w32(uc, addr, v):
    uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(uc, addr):
    return int.from_bytes(uc.mem_read(addr, 4), "little")


def _mk_uc(calls):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for page in (ASB.PCAVE2 + 0xE000, ASB.PCAVE2 + 0xB000,   # thunks + g_bw_rect
                 0x6A7000, 0xDEADB000, 0x5E3000, 0x40E000):
        uc.mem_map(page, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(RING_VA, RING_CODE)
    uc.mem_write(BOX2_VA, BOX2_CODE)
    uc.mem_write(BOX_2, b"\xC2\x0C\x00")            # ret 0xC stub

    def on_box2(u, addr, size, _):
        esp = u.reg_read(UC_X86_REG_ESP)
        rect_ptr = _r32(u, esp + 4)
        rect = tuple(_r32(u, rect_ptr + 4 * i) for i in range(4))
        calls.append((rect_ptr, rect, _r32(u, esp + 8), _r32(u, esp + 0xC),
                      u.reg_read(UC_X86_REG_ECX)))

    uc.hook_add(UC_HOOK_CODE, on_box2, begin=BOX_2, end=BOX_2)
    return uc


# ---------------------------------------------------------------------------
# thunk_bw_box2ring (the replacement callee)
# ---------------------------------------------------------------------------

def _run_ring(g, rect, colors=(0x42, 0x6C), buf=0x00777777):
    calls = []
    uc = _mk_uc(calls)
    _w32(uc, G_SENT, g)
    esp0 = STACK + 0x8000
    rect_ptr = STACK + 0x9000
    for i, v in enumerate(rect):
        _w32(uc, rect_ptr + 4 * i, v)
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0 + 0x0, SITE_RET)
    _w32(uc, esp0 + 0x4, rect_ptr)
    _w32(uc, esp0 + 0x8, colors[0])
    _w32(uc, esp0 + 0xC, colors[1])
    uc.reg_write(UC_X86_REG_ECX, buf)
    for r, v in MARKS.items():
        uc.reg_write(r, v)
    uc.emu_start(RING_VA, SITE_RET, count=100000)
    assert uc.reg_read(UC_X86_REG_EIP) == SITE_RET
    assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 0x10, "RET 0xC contract"
    for r, v in MARKS.items():
        assert uc.reg_read(r) == v, f"callee-saved register {r} clobbered"
    # the caller's rect memory must be untouched (scratch-only insets)
    assert tuple(_r32(uc, rect_ptr + 4 * i) for i in range(4)) == tuple(rect)
    return calls


@pytest.mark.parametrize("g", [16, 17, 22, 25, 32, 40])
def test_ring_calls_match_the_law(g):
    rect = (100, 50, 140, 70)
    calls = _run_ring(g, rect)
    law = SL.box2_ring_rects(*rect, g)
    assert len(calls) == len(law) == SL.stroke_width(g)
    for (ptr, got_rect, ch, cv, ecx), want in zip(calls, law):
        assert got_rect == want
        assert (ch, cv) == (0x42, 0x6C), "colors must pass through every ring"
        assert ecx == 0x00777777, "dest buffer must reach BOX_2 in ecx"


def test_ring_native_is_the_single_vanilla_call():
    calls = _run_ring(16, (7, 8, 9, 10))
    assert len(calls) == 1
    assert calls[0][1] == (7, 8, 9, 10)


@pytest.mark.parametrize("rect", [(10, 20, 200, 21), (10, 20, 11, 90)])
def test_ring_degenerate_inner_rings_stop(rect):
    calls = _run_ring(40, rect)
    law = SL.box2_ring_rects(*rect, 40)
    assert len(calls) == len(law) == 1
    assert calls[0][1] == rect


# ---------------------------------------------------------------------------
# thunk_bw_box2 v2 (nutrients gate + scale + ring tail)
# ---------------------------------------------------------------------------

def _run_box2(g, canvas_w, ecx, rect):
    calls = []
    uc = _mk_uc(calls)
    _w32(uc, G_SENT, g)
    _w32(uc, CANVAS_W, canvas_w)
    esp0 = STACK + 0x8000
    rect_ptr = STACK + 0x9000
    for i, v in enumerate(rect):
        _w32(uc, rect_ptr + 4 * i, v)
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0 + 0x0, SITE_RET)
    _w32(uc, esp0 + 0x4, rect_ptr)
    _w32(uc, esp0 + 0x8, 0x6C)
    _w32(uc, esp0 + 0xC, 0x95)
    uc.reg_write(UC_X86_REG_ECX, ecx)
    uc.emu_start(BOX2_VA, SITE_RET, count=100000)
    assert uc.reg_read(UC_X86_REG_EIP) == SITE_RET
    assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 0x10
    return calls, rect_ptr


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_box2_v2_scaled_path_rings_the_scaled_rect(g):
    rect = (23, 200, 703, 260)
    calls, _ = _run_box2(g, SL.popup_scale_floor(758, g), CANVAS, rect)
    scaled = tuple(SL.basewin_pt(v, g) for v in rect)
    law = SL.box2_ring_rects(*scaled, g)
    assert [c[1] for c in calls] == law
    assert all(c[0] == G_BW_RECT or c[0] == G_RING_RECT for c in calls)


def test_box2_v2_native_and_gate_off_pass_through():
    for g, cw, ecx in ((16, 758, CANVAS), (40, 758, CANVAS),
                       (40, 1895, 0x123456)):
        calls, rect_ptr = _run_box2(g, cw, ecx, (23, 200, 703, 260))
        assert len(calls) == 1
        assert calls[0][0] == rect_ptr, "native path must keep the caller's ptr"
        assert calls[0][1] == (23, 200, 703, 260)


# ---------------------------------------------------------------------------
# thunk_bw_popbox_pads (base_draw cut @0x55B3CF)
# ---------------------------------------------------------------------------

def _run_pads(g, esi, textw, metric, x):
    uc = _mk_uc([])
    uc.mem_write(PADS_VA, PADS_CODE)
    _w32(uc, G_SENT, g)
    esp0 = STACK + 0x8000
    ebp0 = STACK + 0x9000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    uc.reg_write(UC_X86_REG_EBP, ebp0)
    _w32(uc, ebp0 + 0x10, x)                 # param_3
    _w32(uc, esp0, SITE_RET)                 # cut-site return
    uc.reg_write(UC_X86_REG_EAX, textw)
    uc.reg_write(UC_X86_REG_EDI, metric)
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.reg_write(UC_X86_REG_EBX, 0x11111111)
    uc.emu_start(PADS_VA, SITE_RET, count=1000)
    assert uc.reg_read(UC_X86_REG_EIP) == SITE_RET
    assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 4, "plain RET consumes the E8 ret"
    assert uc.reg_read(UC_X86_REG_EBX) == 0x11111111, "ebx is LIVE — untouched"
    assert uc.reg_read(UC_X86_REG_EDI) == metric, "edi (metric) reused downstream"
    assert uc.reg_read(UC_X86_REG_ESI) == esi
    assert uc.reg_read(UC_X86_REG_EBP) == ebp0
    return (uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_ECX),
            uc.reg_read(UC_X86_REG_EDX))


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_pads_scale_per_law_in_the_farm_view(g):
    textw, metric, x = 21, 30, 350
    eax, ecx, edx = _run_pads(g, CANVAS, textw, metric, x)
    pad_w, pad_h, _, _ = SL.base_popbox_pads(g)
    assert eax == x + textw + pad_w, "right-edge accumulator"
    assert ecx == metric + pad_h, "bottom-edge accumulator"
    assert edx == x, "exit contract: edx = param_3 (stored to rect.left)"


def test_pads_other_callers_stay_native():
    # main map / StatusWin / TutWin: esi != BaseWin canvas -> vanilla +5/+4
    eax, ecx, edx = _run_pads(40, 0x7AEC64, 7, 10, 100)
    assert (eax, ecx, edx) == (100 + 7 + 5, 10 + 4, 100)


# ---------------------------------------------------------------------------
# thunk_bw_popbox_text (base_draw cuts @0x55B605 + 0x55B675)
# ---------------------------------------------------------------------------

def _run_text(g, esi, left, top, flags0):
    uc = _mk_uc([])
    uc.mem_write(TEXT_VA, TEXT_CODE)
    _w32(uc, G_SENT, g)
    esp0 = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0, SITE_RET)
    uc.reg_write(UC_X86_REG_EAX, left)
    uc.reg_write(UC_X86_REG_EDX, top)
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.reg_write(UC_X86_REG_EFLAGS, flags0)
    uc.emu_start(TEXT_VA, SITE_RET, count=1000)
    assert uc.reg_read(UC_X86_REG_EIP) == SITE_RET
    assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 4
    assert uc.reg_read(UC_X86_REG_EAX) == left and \
        uc.reg_read(UC_X86_REG_EDX) == top, "eax/edx pass through"
    assert (uc.reg_read(UC_X86_REG_EFLAGS) ^ flags0) & ARITH_FLAGS == 0, (
        "EFLAGS not transparent — the cut sits between a live test and its je")
    return uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_EDI)


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("flags0", [0x2, 0x46, 0x8D7])   # incl. ZF/SF patterns
def test_text_pen_offsets_scale_and_flags_survive(g, flags0):
    left, top = 351, 136
    ebx, edi = _run_text(g, CANVAS, left, top, flags0)
    _, _, dx, dy = SL.base_popbox_pads(g)
    assert ebx == left + dx, "pen x"
    assert edi == top + dy, "pen y"


def test_text_other_callers_stay_native():
    ebx, edi = _run_text(40, 0x7AEC64, 351, 136, 0x46)
    assert (ebx, edi) == (351 + 2, 136 + 1)
