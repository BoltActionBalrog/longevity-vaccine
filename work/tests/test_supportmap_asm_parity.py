"""Differential: the assembled SUPPORT-tab map-density thunks must agree with
scaling_laws bit-exactly.

thunk_bw_supprect (detour @0x470B2A over MapWin_init_2's mode-2 rect-load
block): replicate the four rcRspPanel loads into the ebp locals, device gate
-> scale each edge per scaling_laws.support_map_rect; g<=16 / gate-off ->
byte-identical native stores; pushfd/popfd EFLAGS-transparent; only
eax/ecx/edx clobbered (same as the original block); resumes at 0x470BFB.

thunk_bw_mapblit v3 (call-helper @0x409099 in place of Buffer_copy_4): device
gate -> rewrite dstX/dstY = scaled-panel centering l' + ((r'-l') - src)>>1
over the same per-edge law, then tail-jmp copy_4 (1:1, srcW/H pass through,
ecx/site-ret untouched); native/wrong-dest -> args untouched.

Emulated with the REAL assembled bytes (sentinel g page at 0xDEADB000, the
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

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import assemble_basewin as ASB  # noqa: E402
import scaling_laws as SL  # noqa: E402

SUPP_VA = ASB.PCAVE2 + ASB.SUPPRECT_OFF
BLIT_VA = ASB.PCAVE2 + ASB.MAPBLIT_OFF
SUPP_CODE = ASB.raw("supprect", ASB.SUPPRECT_OFF, ASB.asm_supprect())
BLIT_CODE = ASB.raw("mapblit", ASB.MAPBLIT_OFF, ASB.asm_mapblit())

G_SENT = 0xDEADBE00
NATIVE_RECT = SL.BASEWIN_RSP_PANEL_NATIVE          # (166, 33, 560, 257)
CANVAS = ASB.CANVAS                                 # 0x6A7A6C
CANVAS_W = ASB.CANVAS_W                             # 0x6A7AEC
RECT = ASB.RSP_RECT                                 # 0x6E81B4
RESUME = ASB.SUPP_RESUME                            # 0x470BFB
COPY_4 = ASB.COPY_4                                 # 0x5DFF00
ARITH_FLAGS = 0x8D5                                 # CF|PF|AF|ZF|SF|OF

STACK = 0x00200000
MARKS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x44444444,
         UC_X86_REG_EDI: 0x55555555}


def _mk_uc():
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for page in (ASB.PCAVE2 + 0xB000, ASB.PCAVE2 + 0xE000,  # both thunk pages
                 0x6A7000, 0x6E8000, 0xDEADB000,
                 0x470000, 0x5DF000):
        uc.mem_map(page, 0x1000)
    uc.mem_write(SUPP_VA, SUPP_CODE)
    uc.mem_write(BLIT_VA, BLIT_CODE)
    uc.mem_write(RESUME, b"\xC3")
    uc.mem_write(COPY_4, b"\xC3")
    uc.mem_map(STACK, 0x10000)
    for i, v in enumerate(NATIVE_RECT):
        uc.mem_write(RECT + 4 * i, v.to_bytes(4, "little"))
    return uc


def _w32(uc, addr, v):
    uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(uc, addr):
    return int.from_bytes(uc.mem_read(addr, 4), "little")


# ---------------------------------------------------------------------------
# thunk_bw_supprect
# ---------------------------------------------------------------------------

def _run_supprect(g, canvas_w):
    uc = _mk_uc()
    _w32(uc, G_SENT, g)
    _w32(uc, CANVAS_W, canvas_w)
    esp0 = STACK + 0x8000
    ebp0 = STACK + 0x9000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    uc.reg_write(UC_X86_REG_EBP, ebp0)
    for off in (0x10, 0xC, 8, 4):
        _w32(uc, ebp0 - off, 0xAAAAAAAA)
    for r, v in MARKS.items():
        uc.reg_write(r, v)
    flags0 = uc.reg_read(UC_X86_REG_EFLAGS)
    uc.emu_start(SUPP_VA, RESUME, count=10000)
    assert uc.reg_read(UC_X86_REG_EIP) == RESUME
    assert uc.reg_read(UC_X86_REG_ESP) == esp0, "esp must balance (pushfd/popfd)"
    assert uc.reg_read(UC_X86_REG_EBP) == ebp0
    for r, v in MARKS.items():
        assert uc.reg_read(r) == v, f"register {r} clobbered"
    assert (uc.reg_read(UC_X86_REG_EFLAGS) ^ flags0) & ARITH_FLAGS == 0, \
        "EFLAGS not transparent"
    return tuple(_r32(uc, ebp0 - off) for off in (0x10, 0xC, 8, 4))


@pytest.mark.parametrize("g", [17, 22, 25, 32, 40])
def test_supprect_scales_the_locals_per_law(g):
    canvas_w = SL.popup_scale_floor(758, g)
    got = _run_supprect(g, canvas_w)
    assert got == SL.support_map_rect(*NATIVE_RECT, g)


def test_supprect_native_and_gate_off_are_byte_identical():
    # g=16 (canvas native)
    assert _run_supprect(16, 758) == NATIVE_RECT
    # inconsistent states still fall to native: slice-1 inactive wins ...
    assert _run_supprect(40, 758) == NATIVE_RECT
    # ... and so does a native g even with a (stale) scaled canvas
    assert _run_supprect(16, 1895) == NATIVE_RECT


def test_supprect_fit_loop_consequence():
    """The device dims the fit loop will read (window W/H = the scaled rect's
    cum-position extents) pick a denser-or-equal index that still fits."""
    for g in (22, 25, 40):
        l, t, r, b = _run_supprect(g, SL.popup_scale_floor(758, g))
        nl, nt, nr, nb = NATIVE_RECT
        for half in (16, 32, 40, 64):
            idx_n = SL.support_map_fit(nr - nl, nb - nt, half, half)
            idx_d = SL.support_map_fit(r - l, b - t, half, half)
            assert idx_d >= idx_n, (g, half)


# ---------------------------------------------------------------------------
# thunk_bw_mapblit v3
# ---------------------------------------------------------------------------

def _run_mapblit(g, canvas_w, dst, dst_x, dst_y, src_w, src_h):
    uc = _mk_uc()
    _w32(uc, G_SENT, g)
    _w32(uc, CANVAS_W, canvas_w)
    esp0 = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0 + 0x00, 0x0040909E)    # site ret
    _w32(uc, esp0 + 0x04, dst)
    _w32(uc, esp0 + 0x08, 0)             # srcX
    _w32(uc, esp0 + 0x0C, 0)             # srcY
    _w32(uc, esp0 + 0x10, dst_x)
    _w32(uc, esp0 + 0x14, dst_y)
    _w32(uc, esp0 + 0x18, src_w)
    _w32(uc, esp0 + 0x1C, src_h)
    uc.reg_write(UC_X86_REG_ECX, 0x12345678)   # src Buffer (thiscall this)
    for r, v in MARKS.items():
        uc.reg_write(r, v)
    uc.emu_start(BLIT_VA, COPY_4, count=10000)
    assert uc.reg_read(UC_X86_REG_EIP) == COPY_4
    assert uc.reg_read(UC_X86_REG_ESP) == esp0, "tail-jmp must keep the stack"
    assert uc.reg_read(UC_X86_REG_ECX) == 0x12345678, "src Buffer clobbered"
    for r, v in MARKS.items():
        assert uc.reg_read(r) == v
    assert _r32(uc, esp0) == 0x0040909E, "site ret clobbered"
    assert _r32(uc, esp0 + 0x18) == src_w and _r32(uc, esp0 + 0x1C) == src_h
    return _r32(uc, esp0 + 0x10), _r32(uc, esp0 + 0x14)


def _law_center(g, src_w, src_h):
    l, t, r, b = SL.support_map_rect(*NATIVE_RECT, g)
    return l + ((r - l) - src_w) // 2, t + ((b - t) - src_h) // 2


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_mapblit_v3_centers_the_device_window_flush(g):
    l, t, r, b = SL.support_map_rect(*NATIVE_RECT, g)
    w, h = r - l, b - t
    # the real call: src == the device window -> dst == the scaled panel origin
    got = _run_mapblit(g, SL.popup_scale_floor(758, g), CANVAS, 99, 88, w, h)
    assert got == (l, t) == _law_center(g, w, h)


def test_mapblit_v3_centers_a_smaller_render():
    # armed-zoom / capped-index renders are smaller than the window: centered
    got = _run_mapblit(40, 1895, CANVAS, 99, 88, 500, 300)
    assert got == _law_center(40, 500, 300)


def test_mapblit_v3_native_and_wrong_dest_pass_through():
    assert _run_mapblit(16, 758, CANVAS, 99, 88, 394, 224) == (99, 88)
    assert _run_mapblit(40, 758, CANVAS, 99, 88, 394, 224) == (99, 88)
    assert _run_mapblit(40, 1895, 0x123456, 99, 88, 394, 224) == (99, 88)
