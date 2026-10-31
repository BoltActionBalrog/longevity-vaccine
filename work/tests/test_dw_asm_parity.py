"""Unicorn parity for the Design Workshop bake (assemble_dw.py).

Oracle = scaling_laws (scale_px / popup_scale_floor / stroke_width / stripe_top / line_axis_map / dw_fit_plan /
listbox_bar_reserve / bandmap_rect_from_halfopen) + Python ports of the prototype's JS (renderBackdrop, the
CModule ssaa composite, restripeHoverCell, the footprint plotter model).  Every thunk is emulated from its REAL
assembled bytes at its REAL cave VA; engine callees are tiny recording stubs or landing pads.
"""
from __future__ import annotations

import contextlib
import io
import math
import pathlib
import random
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
pytest.importorskip("pefile")

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_dw as AD  # noqa: E402
    import assemble_se as SE  # noqa: E402
    import assemble_list_face_phase as LF  # noqa: E402
SE_LAYOUT, _ = SE.assemble_all()

LAYOUT, _END = AD.assemble_all()
VA = {n: AD.PCAVE2 + LAYOUT[n][0] for n in LAYOUT}
R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
     "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}
STACK, SP0 = 0x00300000, 0x00310000
RET_SITE = 0x00700100
CALLER_RET = 0x00700600
STUBS = 0x00700000
TEXT_LO, TEXT_HI = 0x432000, 0x43F000
BUF = 0x02000000          # generic Buffer objects / pixel areas
OBJ = 0x21000000          # DesignWin / PartPicker / popup objects
CTXOBJ = 0x009BC000
TN = AD.TN
GS = (17, 19, 22, 25, 32, 40)
_ks = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(src, va=0):
    enc, _ = _ks.asm(src, va)
    return bytes(enc)


_BASE_TEXT = None


def base_text():
    global _BASE_TEXT
    if _BASE_TEXT is None:
        _BASE_TEXT = AD.base_exe_bytes(TEXT_LO, TEXT_HI - TEXT_LO)
    return _BASE_TEXT


def pages(*addrs, size=0x1000):
    out = set()
    for a in addrs:
        out.add(a & ~0xFFF)
        out.add((a + size - 1) & ~0xFFF)
    return out


G_FILEDLG_ACTIVE = AD.PCAVE2 + 0x23A0


def _rail_helpers():
    """thunk_list_gate / thunk_fd_wheelbar from assemble_rail_scrollbar.py with its data sentinels
    bound to the real cells; pinned to the VAs assemble_dw calls."""
    import assemble_rail_scrollbar as RS
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    sent = {RS.G_POPUP_ACT: AD.G_POPUP_ACTIVE, RS.G_FILEDLG_ACT: G_FILEDLG_ACTIVE}
    out = []
    for off, fn, pinned in ((RS.LIST_GATE_OFF, RS.asm_list_gate, AD.T_LIST_GATE),
                            (RS.FD_WHEELBAR_OFF, RS.asm_fd_wheelbar, AD.T_FD_WHEELBAR)):
        assert RS.PCAVE2 + off == pinned
        blob = bytearray(Ks(KS_ARCH_X86, KS_MODE_32).asm(fn(), RS.PCAVE2 + off)[0])
        for s, v in sent.items():
            k = bytes(blob).find(s.to_bytes(4, "little"))
            while k >= 0:
                blob[k:k + 4] = v.to_bytes(4, "little")
                k = bytes(blob).find(s.to_bytes(4, "little"))
        out.append((off, bytes(blob)))
    return out


_RAIL_HELPERS = _rail_helpers()


class Emu:
    def __init__(self, g=22, text=False):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(AD.PCAVE2, 0x22000)
        uc.mem_map(STACK, 0x20000)
        uc.mem_map(STUBS, 0x2000)
        uc.mem_map(BUF, 0x400000)
        uc.mem_map(OBJ, 0x20000)
        uc.mem_map(0x668000, 0x1000)     # g_popup_scale_num + KSB trampoline
        uc.mem_map(0x669000, 0x4000)     # IAT + vtables
        uc.mem_map(0x94C000, 0x1000)     # palette
        uc.mem_map(0x9B7000, 0x7000)     # modal top / basepop / g_scrollbar_w / Caviar target + dirty rect / ctx ptr / CTXOBJ
        uc.mem_map(0x9BE000, 0x3000)     # bound target pitches / part matrix
        uc.mem_map(0x6A8000, 0x1000)     # ProdPicker (symbolic only)
        uc.mem_map(0x71F000, 0x16000)    # DesignWin (canvas Buffer +0x444, pcx Buffer +0x13C6C)
        uc.mem_map(0x5F0000, 0x1000)     # WinProc wheel sites
        for p in sorted(pages(AD.BOX_SPRITE, AD.BUFFER_TILE_2, AD.BUFFER_DRAW_2, AD.BUFFER_RESIZE, AD.BUFFER_FILL_2, AD.HIDE_TARGET,
                              AD.GET_TARGET, AD.CAVIAR_DRAW, AD.CAVIAR_RESET, AD.CAVIAR_RASTERIZE, AD.RUNTAB, AD.CHEVRON,
                              AD.OVL_TARGET, AD.FP_RESUME, AD.FP2_RESUME, 0x617328, 0x6171EF, 0x6175A4, 0x6175EC, AD.SLIDESHOW)):
            if not (0x668000 <= p < 0x66D000 or 0x9B7000 <= p < 0x9BF000):
                try:
                    uc.mem_map(p, 0x1000)
                except Exception:  # noqa: BLE001
                    pass
        if text:
            uc.mem_map(TEXT_LO, TEXT_HI - TEXT_LO)
            uc.mem_write(TEXT_LO, base_text())
        else:
            uc.mem_map(0x432000, 0xD000)   # landing pads only
        for name, (off, blob) in LAYOUT.items():
            uc.mem_write(AD.PCAVE2 + off, blob)
        for cid, off, fn, _m in AD.INPLACE:
            uc.mem_write(AD.PCAVE2 + off, fn())
        for off, blob in _RAIL_HELPERS:                   # 2026-09-26q: thunk_list_gate / thunk_fd_wheelbar
            uc.mem_write(AD.PCAVE2 + off, blob)
        for n in ("thunk_se_stripe_top", "thunk_se_stripe_px", "thunk_se_rr_row", "thunk_se_rr_col", "thunk_se_rowdraw"):
            off, blob = SE_LAYOUT[n]
            assert AD.PCAVE2 + off == AD.SE_HELPERS.get(n, AD.SE_ROWDRAW)
            uc.mem_write(AD.PCAVE2 + off, blob)
        # 2026-10-11: the SE body (phased) calls thunk_se_stripe_px_ph -> g_se_yph (0 here = phase 0, so
        # thunk_se_rowdraw entered directly still equals DesignWin's unphased copy)
        uc.mem_map(AD.PCAVE2 + 0x2F000, 0x1000)
        off, blob = SE_LAYOUT["thunk_se_stripe_px_ph"]
        uc.mem_write(AD.PCAVE2 + off, blob)
        # 2026-10-14: thunk_dw_btndraw -> t_dw_face_ph (stages g_se_yph from the button's parent-local top) ->
        # thunk_dw_btnface, now the PHASED SE body; thunk_se_rowdraw_ph is SE's own staging entry (the reference)
        off, blob = LF.build()["t_dw_face_ph"]
        assert AD.PCAVE2 + off == AD.T_DW_FACE_PH
        uc.mem_write(AD.PCAVE2 + off, blob)
        off, blob = SE_LAYOUT["thunk_se_rowdraw_ph"]
        uc.mem_write(AD.PCAVE2 + off, blob)
        import assemble_face_own as FO          # 2026-10-27 W9A: thunk_se_rowdraw_ph v2 CALLs t_face_own first
        va, code, _t = FO.build()["t_face_own"]
        try:
            uc.mem_map(va & ~0xFFF, 0x1000)
        except Exception:                       # noqa: BLE001  (already mapped)
            pass
        uc.mem_write(va, code)
        uc.mem_map(0x4B1000, 0x1000)     # SocialWin_draw_society_row (landing for the SE thunk's tail)
        self.set_g(g)
        self.landings = set()
        self.records = {}
        self.stopped_at = None
        self.trace = []
        uc.hook_add(UC_HOOK_CODE, self._hook)

    def set_g(self, g):
        self.w32(AD.G, g)

    def land(self, *addrs):
        for a in addrs:
            self.landings.add(a)
            self.uc.mem_write(a, b"\xf4")

    def stub(self, addr, code, record=None):
        """Engine callee: `code` executes (usually `ret N`); `record(emu)` runs at entry."""
        self.uc.mem_write(addr, code)
        if record:
            self.records[addr] = record

    def _hook(self, uc, addr, size, ud):
        if addr in self.records:
            self.records[addr](self)
        if addr in self.landings:
            self.stopped_at = addr
            uc.emu_stop()

    def w32(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def w16(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFF).to_bytes(2, "little"))

    def w8(self, addr, v):
        self.uc.mem_write(addr, bytes([v & 0xFF]))

    def r32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "little", signed=True)

    def ru32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "little")

    def r8(self, addr):
        return self.uc.mem_read(addr, 1)[0]

    def reg(self, name):
        return self.uc.reg_read(R[name])

    def sreg(self, name):
        v = self.reg(name)
        return v - (1 << 32) if v & 0x80000000 else v

    def run(self, va, regs=None, stack=None, count=5_000_000, sp=SP0):
        uc = self.uc
        stack = list(stack if stack is not None else [RET_SITE])
        for i, v in enumerate(stack):
            self.w32(sp + 4 * i, v)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_EBP, 0x5A5A5A5A)
        for r in ("eax", "ebx", "ecx", "edx", "esi", "edi"):
            uc.reg_write(R[r], 0)
        for r, v in (regs or {}).items():
            uc.reg_write(R[r], v & 0xFFFFFFFF)
        self.stopped_at = None
        uc.emu_start(va, 0, count=count)
        assert self.stopped_at is not None, f"no landing reached (eip={uc.reg_read(UC_X86_REG_EIP):#x})"
        return self.stopped_at

    # ---- Buffer objects (engine layout: +0x20 clip L,T,R,B, +0x54 data, +0x80 w, +0x84 -h, +0x4A8 pitch) ----
    def buffer(self, at, data, w, h, pitch=None, clip=None):
        pitch = pitch if pitch is not None else (w + 3) & ~3
        self.w32(at + 0x54, data)
        self.w32(at + 0x80, w)
        self.w32(at + 0x84, -h)
        self.w32(at + 0x4A8, pitch)
        L, T, Rr, B = clip or (0, 0, w, h)
        for i, v in enumerate((L, T, Rr, B)):
            self.w32(at + 0x20 + 4 * i, v)
        return {"data": data, "w": w, "h": h, "pitch": pitch}


def sx(v):
    return v - (1 << 32) if v & 0x80000000 else v


# =====================================================================================
# immediates
# =====================================================================================
LL_STUB, GP_STUB, VP_STUB = STUBS + 0x200, STUBS + 0x220, STUBS + 0x240


def _immfix_emu(g):
    e = Emu(g, text=True)
    e.stub(LL_STUB, asm("mov eax, 1; ret 4"))
    e.stub(GP_STUB, asm(f"mov eax, {VP_STUB:#x}; ret 8"))
    e.stub(VP_STUB, asm("mov eax, 1; ret 0x10"))
    e.w32(AD.IAT_LOADLIB, LL_STUB)
    e.w32(AD.IAT_GETPROC, GP_STUB)
    e.land(RET_SITE)
    return e


def _check_imms(e, g):
    text = base_text()
    touched = set()
    for site, off, w, kind, a, b, label in AD.IMMS:
        want = AD.imm_value(site, off, g)
        if w == 4:
            have = e.r32(site + off)
            touched.update(range(site + off, site + off + 4))
        else:
            have = struct.unpack("<b", e.uc.mem_read(site + off, 1))[0]
            touched.add(site + off)
        assert have == want, (label, hex(site), g, have, want)
    cur = bytes(e.uc.mem_read(TEXT_LO, TEXT_HI - TEXT_LO))
    diff = [TEXT_LO + i for i in range(len(cur)) if cur[i] != text[i] and TEXT_LO + i not in touched and TEXT_LO + i not in e.landings]
    assert not diff, [hex(d) for d in diff[:8]]


@pytest.mark.parametrize("g", GS)
def test_immfix_writes_every_site_to_the_law(g):
    e = _immfix_emu(g)
    assert e.run(VA["thunk_dw_immfix"], regs={"esi": 0x1234}) == RET_SITE
    assert e.reg("esi") == 0x1234 and e.reg("esp") == SP0 + 4
    assert e.r32(AD.CELL["g_dw_vpdone"]) == 1
    _check_imms(e, g)


def test_immfix_restores_vanilla_on_downgrade_and_bails_without_vp():
    e = _immfix_emu(40)
    e.run(VA["thunk_dw_immfix"])
    _check_imms(e, 40)
    e.set_g(16)
    e.run(VA["thunk_dw_immfix"])
    _check_imms(e, 16)
    text = base_text()
    for site, off, w, kind, a, b, label in AD.IMMS:
        if site in AD.STATIC_REWRITES:
            continue
        n = 4 if w == 4 else 1
        assert bytes(e.uc.mem_read(site + off, n)) == text[site + off - TEXT_LO: site + off - TEXT_LO + n], label
    e2 = _immfix_emu(40)
    e2.stub(VP_STUB, asm("xor eax, eax; ret 0x10"))
    e2.run(VA["thunk_dw_immfix"])
    assert e2.r32(AD.CELL["g_dw_vpdone"]) == 0
    assert bytes(e2.uc.mem_read(TEXT_LO, TEXT_HI - TEXT_LO)) == text


def test_imm_table_matches_the_proto_value_functions():
    for g in range(16, 41):
        s = lambda v: SL.scale_px(v, g)   # noqa: E731
        assert AD.imm_value(0x43C900, 2, g) == -SL.popup_scale_floor(0x14, g)
        assert AD.imm_value(0x43C6CA, 1, g) == math.ceil(623 * g / 16)
        assert AD.imm_value(0x436274, 1, g) == min(48, (30 * g >> 4) - 16)
        assert AD.imm_value(0x43C49A, 1, g) == -s(3)
        assert AD.imm_value(0x43C52A, 2, g) == s(7) - s(4)
        assert AD.imm_value(0x43D726, 1, g) == s(2)
    rows = AD.dw_button_rows if hasattr(AD, "dw_button_rows") else None
    assert rows is None
    b = AD.immtab_bytes()
    assert len(b) == 114 * 16 + 4 and b[-4:] == b"\0\0\0\0"


def test_enter_replays_the_prologue_after_immfix_and_brackets_g_dw_active():
    e = _immfix_emu(25)
    e.land(AD.EXEC_RESUME, CALLER_RET)
    assert e.run(VA["thunk_dw_enter"], regs={"ecx": 0x1111, "edx": 0x2222, "ebp": 0x3333}, stack=[CALLER_RET, 5, 6]) == AD.EXEC_RESUME
    assert e.reg("ecx") == 0x1111 and e.reg("edx") == 0x2222
    assert e.r32(SP0) == VA["thunk_dw_leave"] and e.r32(SP0 - 4) == 0x3333 and e.r32(SP0 - 8) == -1 and e.reg("esp") == SP0 - 8 and e.reg("ebp") == SP0 - 4
    assert e.r32(SP0 + 4) == 5 and e.r32(SP0 + 8) == 6                       # the args stay in place for DesignWin_exec
    assert e.r32(AD.CELL["g_dw_vpdone"]) == 1 and e.r32(AD.CELL["g_dw_active"]) == 1 and e.ru32(AD.CELL["g_dw_exec_ret"]) == CALLER_RET
    _check_imms(e, 25)
    # DesignWin_exec's `ret 8` lands in thunk_dw_leave with the args popped: eax kept, g_dw_active cleared
    assert e.run(VA["thunk_dw_leave"], regs={"eax": 0x77}, stack=[], sp=SP0 + 0xC) == CALLER_RET
    assert e.reg("eax") == 0x77 and e.reg("esp") == SP0 + 0xC and e.r32(AD.CELL["g_dw_active"]) == 0


# =====================================================================================
# picker bracket + stubs
# =====================================================================================
PICKER = OBJ + 0x8000


def test_pk_bracket_targets_the_live_rail_gate_comparand():
    """RAIL_GATE_IMM must be the imm32 of `cmp eax, ProdPicker` in the rail-gate body the trampoline reaches
    (2026-09-27: a stale literal thunk_rail_gate+5 overwrote the v4 trampoline's `ret` -> DW picker crash)."""
    import assemble_rail_scrollbar as RS
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    va = RS.PCAVE2 + RS.RAIL_GATE4_OFF
    body = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(RS.asm_rail_gate4(), addr=va)[0])
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    hits = [i for i in md.disasm(body, va) if i.mnemonic == "cmp" and i.imm_size == 4
            and i.address + i.imm_offset == AD.RAIL_GATE_IMM]
    assert len(hits) == 1 and hits[0].operands[1].imm == AD.PRODPICKER


def test_pk_bracket_arms_and_disarms():
    e = Emu(22)
    e.land(AD.PK_RESUME, CALLER_RET)
    e.w32(AD.G_POPUP_ACTIVE, 1)
    e.w32(AD.RAIL_GATE_IMM, AD.PRODPICKER)
    assert e.run(VA["thunk_dw_pk_enter"], regs={"ecx": PICKER, "ebp": 0x77}, stack=[CALLER_RET]) == AD.PK_RESUME
    assert e.reg("ecx") == PICKER
    assert e.r32(SP0) == VA["thunk_dw_pk_leave"] and e.r32(SP0 - 4) == 0x77 and e.r32(SP0 - 8) == -1 and e.reg("esp") == SP0 - 8
    assert e.ru32(AD.CELL["g_dw_pickcanvas"]) == PICKER + 0x444 and e.ru32(AD.RAIL_GATE_IMM) == PICKER
    assert e.r32(AD.G_POPUP_ACTIVE) == 2 and e.r32(AD.CELL["g_dw_pk_armed"]) == 1 and e.ru32(AD.CELL["g_dw_pk_ret"]) == CALLER_RET
    assert e.run(VA["thunk_dw_pk_leave"], regs={"eax": 0x77}, stack=[]) == CALLER_RET
    assert e.reg("eax") == 0x77 and e.reg("esp") == SP0
    assert e.ru32(AD.CELL["g_dw_pickcanvas"]) == 0 and e.ru32(AD.RAIL_GATE_IMM) == AD.PRODPICKER
    assert e.r32(AD.G_POPUP_ACTIVE) == 1 and e.r32(AD.CELL["g_dw_pk_armed"]) == 0
    e.set_g(16)
    e.run(VA["thunk_dw_pk_enter"], regs={"ecx": PICKER}, stack=[CALLER_RET])
    assert e.ru32(AD.CELL["g_dw_pickcanvas"]) == 0 and e.r32(AD.G_POPUP_ACTIVE) == 1 and e.ru32(AD.RAIL_GATE_IMM) == AD.PRODPICKER
    e.run(VA["thunk_dw_pk_leave"], regs={"eax": 5}, stack=[])
    assert e.r32(AD.G_POPUP_ACTIVE) == 1


def cell_law(first, cols, idx, g):
    rel = idx - first
    row, col = rel // cols, rel % cols
    s = lambda v: SL.scale_px(v, g)   # noqa: E731
    return s(col * 108 + 27), s(row * 94 + 4), s(col * 108 + 132), s(row * 94 + 95)


@pytest.mark.parametrize("g", (16,) + GS)
def test_cell_rect_law(g):
    e = Emu(g)
    e.land(AD.CELL_RESUME, AD.CELL_SITE + 6)
    frame = SP0 - 0x100
    for first, cols, idx in ((0, 4, 0), (0, 4, 7), (8, 4, 13), (3, 5, 19)):
        e.w32(PICKER + 0x2B6C, cols)
        at = e.run(VA["thunk_dw_cell"], regs={"esi": PICKER, "eax": first, "ebx": idx, "ebp": frame})
        if g <= 16:
            assert at == AD.CELL_SITE + 6 and e.reg("ecx") == cols and e.reg("eax") == first and e.reg("ebx") == idx
            continue
        assert at == AD.CELL_RESUME
        x0, y0, x1, y1 = cell_law(first, cols, idx, g)
        assert (e.reg("edx"), e.reg("ecx"), e.reg("eax"), e.reg("edi")) == (x0, y0, x1, y1)
        assert e.r32(frame - 0xC) == y0 and e.r32(frame - 4) == y1 and e.reg("esi") == PICKER


@pytest.mark.parametrize("g", (16, 22, 40))
def test_click_descales(g):
    e = Emu(g)
    e.land(AD.PK_ONCLICK)
    assert e.run(VA["thunk_dw_click"], regs={"edx": 0x99}, stack=[RET_SITE, 1000, -37]) == AD.PK_ONCLICK
    assert e.reg("edx") == 0x99 and e.reg("esp") == SP0
    # x also loses the 0x17 frame at every g (vanilla hit grid (x-4)/108 vs cells drawn at col*108+27)
    ceil = lambda v: int((v * 16 + g - 1) / g)          # idiv truncates toward zero   # noqa: E731
    if g <= 16:
        assert (e.r32(SP0 + 4), e.r32(SP0 + 8)) == (1000 - 0x17, -37)
    else:
        assert (e.r32(SP0 + 4), e.r32(SP0 + 8)) == (ceil(1000) - 0x17, ceil(-37))
    # the drawn cell law and the corrected hit grid agree at every g: both edges of every cell stay in its column/row
    if g > 16:
        for col in range(5):
            for row in range(4):
                x0, y0, x1, y1 = cell_law(0, 5, row * 5 + col, g)
                for xd in (x0, x1 - 1):
                    assert (ceil(xd) - 0x17 - 4) // 108 == col, (g, col, xd)
                for yd in (y0, y1 - 1):
                    assert (ceil(yd) - 4) // 94 == row, (g, row, yd)


@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_frame_inset(g):
    e = Emu(g)
    e.land(AD.FRAME_RESUME)
    assert e.run(VA["thunk_dw_frame"], regs={"edi": 1000, "ecx": 0xC, "edx": 0xD}) == AD.FRAME_RESUME
    assert e.reg("edi") == 1000 - SL.scale_px(0x37, g) and e.r32(SP0 - 8) == 0xD and e.r32(SP0 - 4) == 0xC


@pytest.mark.parametrize("g", (16, 22, 40))
def test_bm_rect_copy(g):
    e = Emu(g)
    e.land(AD.HOLLOWFLAT, AD.BOX_SPRITE)
    rect = BUF + 0x1000
    for i, v in enumerate((10, 20, 273, 247)):
        e.w32(rect + 4 * i, v)
    at = e.run(VA["thunk_dw_bm"], regs={"ecx": BUF}, stack=[RET_SITE, rect, 0x78D528])
    if g <= 16:
        assert at == AD.BOX_SPRITE and e.ru32(SP0 + 4) == rect
    else:
        assert at == AD.HOLLOWFLAT and e.ru32(SP0 + 4) == AD.CELL["g_dw_bmrect"]
        assert [e.r32(AD.CELL["g_dw_bmrect"] + 4 * i) for i in range(4)] == list(SL.bandmap_rect_from_halfopen(10, 20, 273, 247, g))
    assert e.reg("ecx") == BUF and e.reg("esp") == SP0


# =====================================================================================
# restripe family (Python port of restripeHoverCell / thunk_dw_restripe)
# =====================================================================================
def py_restripe(pix, w, h, pitch, rect, inset, top, mate, g):
    K = SL.stroke_width(g)
    ins = K + 2 if inset < 0 else inset
    x0, y0 = max(0, rect[0] + ins), max(0, rect[1] + ins)
    x1, y1 = min(rect[2] - ins, w), min(rect[3] - ins, h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return pix
    out = bytearray(pix)
    for y in range(y0, y1):
        c = top if SL.stripe_top(y, g) else mate
        for x in range(x0, x1):
            v = out[y * pitch + x]
            if v in (top, mate):
                out[y * pitch + x] = c
    return bytes(out)


def make_pixels(w, h, pitch, top, mate, seed=1):
    rnd = random.Random(seed)
    pix = bytearray(pitch * h)
    for y in range(h):
        for x in range(w):
            r = rnd.random()
            pix[y * pitch + x] = (top if (y & 1) == 0 else mate) if r < 0.7 else rnd.choice((9, 33, 0x41, 120))
    return bytes(pix)


@pytest.mark.parametrize("g", (16, 22, 25, 40))
@pytest.mark.parametrize("inset", (-1, 0, 3))
def test_restripe_helper(g, inset):
    e = Emu(g)
    e.land(RET_SITE)
    w, h, pitch = 100, 60, 104
    pix = make_pixels(w, h, pitch, 194, 65)
    e.buffer(BUF, BUF + 0x1000, w, h, pitch)
    e.uc.mem_write(BUF + 0x1000, pix)
    rect = BUF + 0x800
    for i, v in enumerate((-3, 5, 90, 70)):
        e.w32(rect + 4 * i, v)
    assert e.run(VA["thunk_dw_restripe"], regs={"ecx": BUF, "esi": 7, "edi": 8, "ebx": 9, "ebp": 10}, stack=[RET_SITE, rect, inset, 194, 65]) == RET_SITE
    assert e.reg("esp") == SP0 + 0x14 and (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (7, 8, 9, 10)
    got = bytes(e.uc.mem_read(BUF + 0x1000, pitch * h))
    want = pix if g <= 16 else py_restripe(pix, w, h, pitch, (-3, 5, 90, 70), inset, 194, 65, g)
    assert got == want
    if g > 16:
        assert got != pix


def _site_emu(g, top, mate, w=120, h=90):
    e = Emu(g)
    pitch = (w + 3) & ~3
    pix = make_pixels(w, h, pitch, top, mate)
    e.buffer(BUF, BUF + 0x1000, w, h, pitch)
    e.uc.mem_write(BUF + 0x1000, pix)
    e.land(RET_SITE)
    return e, pix, pitch


@pytest.mark.parametrize("g", (16, 22, 40))
@pytest.mark.parametrize("params", (0x78D528, 0x78D550, 0x78D578))
def test_pickcell_site(g, params):
    top, mate = {0x78D550: (194, 65), 0x78D578: (191, 83)}.get(params, (196, 65))
    e, pix, pitch = _site_emu(g, top, mate)
    e.stub(AD.HOLLOWFLAT, asm("ret 8"))
    e.stub(AD.BOX_SPRITE, asm("ret 8"))
    seen = []
    e.records[AD.HOLLOWFLAT] = lambda em: seen.append((em.reg("ecx"), em.ru32(em.reg("esp") + 4), em.ru32(em.reg("esp") + 8)))
    e.records[AD.BOX_SPRITE] = lambda em: seen.append(("native", em.ru32(em.reg("esp") + 4)))
    rect = BUF + 0x800
    for i, v in enumerate((4, 6, 100, 80)):
        e.w32(rect + 4 * i, v)
    assert e.run(VA["thunk_dw_pickcell"], regs={"ecx": BUF}, stack=[RET_SITE, rect, params]) == RET_SITE
    assert e.reg("esp") == SP0 + 0xC
    got = bytes(e.uc.mem_read(BUF + 0x1000, pitch * 90))
    if g <= 16:
        assert seen == [("native", rect)] and got == pix
        return
    assert seen == [(BUF, AD.CELL["g_dw_bmrect"], params)]
    assert [e.r32(AD.CELL["g_dw_bmrect"] + 4 * i) for i in range(4)] == [4, 6, 99, 79]
    assert got == py_restripe(pix, 120, 90, pitch, (4, 6, 100, 80), -1, top, mate, g) and got != pix


@pytest.mark.parametrize("g", (16, 22, 40))
def test_container_site(g):
    e, pix, pitch = _site_emu(g, 197, 65)
    e.stub(AD.HOLLOWFLAT, asm("ret 8"))
    e.stub(AD.BOX_SPRITE, asm("ret 8"))
    seen = []
    e.records[AD.HOLLOWFLAT] = lambda em: seen.append((em.reg("ecx"), em.ru32(em.reg("esp") + 4), em.ru32(em.reg("esp") + 8)))
    e.records[AD.BOX_SPRITE] = lambda em: seen.append(("native", em.ru32(em.reg("esp") + 4)))
    rect = BUF + 0x800
    for i, v in enumerate((2, 2, 118, 88)):
        e.w32(rect + 4 * i, v)
    assert e.run(VA["thunk_dw_container"], regs={"ecx": BUF}, stack=[RET_SITE, rect, 0x78D5A0]) == RET_SITE
    assert e.reg("esp") == SP0 + 0xC and e.reg("ecx") == BUF
    got = bytes(e.uc.mem_read(BUF + 0x1000, pitch * 90))
    if g <= 16:
        assert seen == [("native", rect)] and got == pix
        return
    assert seen == [(BUF, AD.CELL["g_dw_bmrect"], 0x78D5A0)]
    assert [e.r32(AD.CELL["g_dw_bmrect"] + 4 * i) for i in range(4)] == [2, 2, 117, 87]
    assert got == py_restripe(pix, 120, 90, pitch, (2, 2, 118, 88), -1, 197, 65, g) and got != pix


@pytest.mark.parametrize("g", (16, 25))
def test_tilecell_site(g):
    e, pix, pitch = _site_emu(g, 197, 65)
    seen = []
    e.stub(AD.BUFFER_TILE_2, asm("ret 0x1C"), lambda em: seen.append([em.reg("ecx")] + [em.r32(em.reg("esp") + 4 * i) for i in range(1, 8)]))
    args = [0x6B33F8, 10, 12, 10, 12, 100, 70]
    assert e.run(VA["thunk_dw_tilecell"], regs={"ecx": BUF}, stack=[RET_SITE] + args) == RET_SITE
    assert e.reg("esp") == SP0 + 0x20 and seen == [[BUF] + args]
    got = bytes(e.uc.mem_read(BUF + 0x1000, pitch * 90))
    assert got == (pix if g <= 16 else py_restripe(pix, 120, 90, pitch, (10, 12, 110, 82), 0, 197, 65, g))


@pytest.mark.parametrize("g", (16, 22, 40))
@pytest.mark.parametrize("params", (0x78D528, 0x78D550, 0x78D578))
def test_slotcell_site(g, params):
    top, mate = {0x78D550: (194, 65), 0x78D578: (191, 83)}.get(params, (194, 65))
    e, pix, pitch = _site_emu(g, top, mate)
    seen = []
    e.stub(AD.BOX_SPRITE, asm("ret 8"), lambda em: seen.append((em.reg("ecx"), em.ru32(em.reg("esp") + 4), em.ru32(em.reg("esp") + 8))))
    rect = BUF + 0x800
    for i, v in enumerate((2, 3, 110, 85)):
        e.w32(rect + 4 * i, v)
    assert e.run(VA["thunk_dw_slotcell"], regs={"ecx": BUF}, stack=[RET_SITE, rect, params]) == RET_SITE
    assert e.reg("esp") == SP0 + 0xC and seen == [(BUF, rect, params)] and e.reg("ecx") == BUF
    got = bytes(e.uc.mem_read(BUF + 0x1000, pitch * 90))
    if g <= 16 or params == 0x78D528:
        assert got == pix
    else:
        assert got == py_restripe(pix, 120, 90, pitch, (2, 3, 110, 85), -1, top, mate, g)


def test_btndraw_filters_and_returns():
    e = Emu(25)
    e.land(RET_SITE)
    btn = AD.DW_LO + 3 * 0xB4C                     # a DW button with NO canvas data (btnface bails at once)
    # workshop NOT open (game init/load draws the MainWin-parented presets): the plain stub, always
    assert e.run(VA["thunk_dw_btndraw"], stack=[RET_SITE, btn, 0, 7]) == RET_SITE and e.reg("eax") == 0 and e.reg("esp") == SP0 + 0x10
    e.w32(AD.CELL["g_dw_active"], 1)
    assert e.run(VA["thunk_dw_btndraw"], regs={"ebx": 1, "esi": 2, "edi": 3, "ebp": 4}, stack=[RET_SITE, btn, 0, 7]) == RET_SITE
    assert e.reg("esp") == SP0 + 0x10 and e.reg("eax") == 0 and (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (1, 2, 3, 4)
    for other in (AD.DW_LO - 4, AD.DW_HI, 0x8AC290, 0x7AF620 + 3 * 0xB4C):
        assert e.run(VA["thunk_dw_btndraw"], stack=[RET_SITE, other, 0, 7]) == RET_SITE and e.reg("eax") == 0 and e.reg("esp") == SP0 + 0x10
    e.set_g(16)
    assert e.run(VA["thunk_dw_btndraw"], stack=[RET_SITE, btn, 0, 7]) == RET_SITE and e.reg("esp") == SP0 + 0x10


def _face_canvas(e, btn, w, h, seed):
    rnd = random.Random(seed)
    pitch = (w + 3) & ~3
    pix = bytearray(pitch * h)
    for y in range(h):
        for x in range(w):
            ring = x < 2 or y < 2 or x >= w - 2 or y >= h - 2
            pix[y * pitch + x] = 41 if ring else ((238 if (y & 1) == 0 else 174) if rnd.random() < 0.85 else rnd.choice((9, 33, 120)))
    for x in range(w):
        pix[(h - 1) * pitch + x] = 9                              # a trailing key row (blit spill) to overdraw
    e.buffer(btn + 0x444, BUF + 0x20000, w, h, pitch)
    e.uc.mem_write(BUF + 0x20000, bytes(pix))
    return bytes(pix), pitch


@pytest.mark.parametrize("g", (22, 25, 40))
@pytest.mark.parametrize("top", (0, 479, 444, 7, 1))
def test_btnface_equals_the_se_restripe_and_returns(g, top):
    """thunk_dw_btnface must produce EXACTLY thunk_se_rowdraw's pixels (same body) and then RETURN
    (the SE thunk's tail jumps into SocialWin_draw_society_row -- the v1/v1b crash).  2026-10-14: entered
    through thunk_dw_btndraw -> t_dw_face_ph it must equal SE entered through ITS phase entry
    (thunk_se_rowdraw_ph) for the same parent-local top -- law dw_button_face_stripe_phase."""
    btn = AD.DW_LO + 24 * 0xB4C                    # the right ARROW button (the crashing one)
    w, h = 60, 52
    e1 = Emu(g); e1.land(RET_SITE)
    pix, pitch = _face_canvas(e1, btn, w, h, g)
    e1.w32(btn + 0x140, top)
    assert e1.run(VA["thunk_dw_btndraw"], regs={"ebx": 1, "esi": 2, "edi": 3, "ebp": 4}, stack=[RET_SITE, btn, 0, 24]) == RET_SITE
    e1.w32(AD.CELL["g_dw_active"], 1)
    e1.uc.mem_write(BUF + 0x20000, pix)
    assert e1.run(VA["thunk_dw_btndraw"], regs={"ebx": 1, "esi": 2, "edi": 3, "ebp": 4}, stack=[RET_SITE, btn, 0, 24], count=50_000_000) == RET_SITE
    assert e1.reg("esp") == SP0 + 0x10 and e1.reg("eax") == 0 and (e1.reg("ebx"), e1.reg("esi"), e1.reg("edi"), e1.reg("ebp")) == (1, 2, 3, 4)
    mine = bytes(e1.uc.mem_read(BUF + 0x20000, pitch * h))
    assert e1.r32(LF.G_SE_YPH) == SL.dw_button_face_stripe_phase(top, 0, g)
    e2 = Emu(g); e2.land(SE.ROWDRAW)
    _face_canvas(e2, btn, w, h, g)
    e2.w32(btn + 0x140, top)
    assert e2.run(AD.PCAVE2 + SE_LAYOUT["thunk_se_rowdraw_ph"][0], stack=[RET_SITE, btn, 0, 24], count=50_000_000) == SE.ROWDRAW
    theirs = bytes(e2.uc.mem_read(BUF + 0x20000, pitch * h))
    assert mine == theirs and mine != pix
    if top % SL.stripe_period(g):                   # a non-zero phase really moves the stripes
        e3 = Emu(g); e3.land(RET_SITE)
        _face_canvas(e3, btn, w, h, g)
        e3.w32(AD.CELL["g_dw_active"], 1)
        assert e3.run(VA["thunk_dw_btndraw"], stack=[RET_SITE, btn, 0, 24], count=50_000_000) == RET_SITE
        assert bytes(e3.uc.mem_read(BUF + 0x20000, pitch * h)) != mine
    assert all(mine[(h - 1) * pitch + x] != 9 for x in range(w))            # trailing key row overdrawn


def test_btn_gate_pre_v4_prefixes():
    e = Emu(25)
    e.land(RET_SITE, AD.BTN_GATE)
    va = AD.PCAVE2 + AD.BTN_GATE_PRE_OFF
    # 2026-09-04: the live thunk is v5 (assemble_rw.py = rw report prefix + this v4 VERBATIM, relocated);
    # the old slot is padding, so emulate the v4 body assembled here at its historical VA.
    e.uc.mem_write(va, AD.assemble(AD.asm_btn_gate_pre_v4(), va))
    for active in (0, 1):
        e.w32(AD.CELL["g_dw_active"], active)
        dw = 1 if active else "gate"
        for esi, want in ((AD.DW_LO, dw), (AD.DW_HI - 1, dw), (AD.DW_HI, "gate"), (AD.SE_LO, 1), (AD.SE_HI - 1, 1), (0x6FEC80 + 0xD94, 1),
                          (0x7FE80C, 0), (0x7FF358, 0), (0x123456, "gate")):
            at = e.run(va, regs={"esi": esi})
            if want == "gate":
                assert at == AD.BTN_GATE and e.reg("esp") == SP0, (active, hex(esi))
            else:
                assert at == RET_SITE and e.reg("eax") == want, (active, hex(esi))


# =====================================================================================
# composite shim + SSAA (Python port of the CModule)
# =====================================================================================
def py_ssaa(src, sp, tn, dst, dp, L, T, Rr, B, left, top, W, pal, key, sx0, sy0, sx1, sy1):
    present = set()
    for y in range(sy0, sy1 + 1):
        for x in range(sx0, sx1 + 1):
            present.add(src[y * sp + x])
    present.discard(key)
    cand = sorted(present)
    if not cand:
        return dst, 0
    out = bytearray(dst)
    cache = {}
    dy0, dy1 = (sy0 * W) // tn, min(W, ((sy1 + 1) * W + tn - 1) // tn)
    dx0, dx1 = (sx0 * W) // tn, min(W, ((sx1 + 1) * W + tn - 1) // tn)
    wrote = 0
    for dy in range(dy0, dy1):
        Y = top + dy
        if Y < T or Y >= B:
            continue
        s0, s1 = (dy * tn) // W, ((dy + 1) * tn) // W
        s1 = min(tn, max(s1, s0 + 1))
        for dx in range(dx0, dx1):
            X = left + dx
            if X < L or X >= Rr:
                continue
            t0, t1 = (dx * tn) // W, ((dx + 1) * tn) // W
            t1 = min(tn, max(t1, t0 + 1))
            n = tot = rs = gs = bs = 0
            for sy in range(s0, s1):
                for sxx in range(t0, t1):
                    v = src[sy * sp + sxx]
                    tot += 1
                    if v == key:
                        continue
                    n += 1
                    rs += pal[v * 4]
                    gs += pal[v * 4 + 1]
                    bs += pal[v * 4 + 2]
            if n == 0 or 2 * n < tot:
                continue
            rr, gg, bb = rs // n, gs // n, bs // n
            k = ((rr >> 2) << 12) | ((gg >> 2) << 6) | (bb >> 2)
            slot = k & 0xFFF
            if slot in cache and cache[slot][0] == k:
                best = cache[slot][1]
            else:
                bd, best = 0x7FFFFFFF, cand[0]
                for c in cand:
                    d = (pal[c * 4] - rr) ** 2 + (pal[c * 4 + 1] - gg) ** 2 + (pal[c * 4 + 2] - bb) ** 2
                    if d < bd:
                        bd, best = d, c
                cache[slot] = (k, best)
            out[Y * dp + X] = best
            wrote += 1
    return bytes(out), wrote


def _ssaa_setup(e, seed, W, bbox, left, top, dw=200, dh=160, clip=None):
    rnd = random.Random(seed)
    pal = bytearray(1024)
    for i in range(256):
        pal[4 * i:4 * i + 3] = bytes(rnd.randrange(256) for _ in range(3))
    e.uc.mem_write(AD.PALETTE, bytes(pal))
    sp = TN
    src = bytearray(b"\x09" * (sp * TN))
    colours = [rnd.randrange(256) for _ in range(6)]
    sx0, sy0, sx1, sy1 = bbox
    for y in range(sy0, sy1 + 1):
        for x in range(sx0, sx1 + 1):
            src[y * sp + x] = 9 if rnd.random() < 0.3 else rnd.choice(colours)
    SRCDATA, DSTDATA = BUF + 0x10000, BUF + 0x200000
    e.uc.mem_write(SRCDATA, bytes(src))
    e.buffer(AD.CV_TARGET, SRCDATA, TN, TN, sp)
    dp = (dw + 3) & ~3
    dst = bytes(rnd.randrange(256) for _ in range(dp * dh))
    e.uc.mem_write(DSTDATA, dst)
    e.buffer(AD.DW_CANVAS, DSTDATA, dw, dh, dp, clip)
    e.w32(AD.CV_CTX, CTXOBJ)
    for i, v in enumerate((sx0, sy0, sx1, sy1)):
        e.w32(CTXOBJ + 8 + 4 * i, v)
    e.w32(AD.CELL["g_dw_ssaaw"], W)
    L, T, Rr, B = clip or (0, 0, dw, dh)
    want, wrote = py_ssaa(bytes(src), sp, TN, dst, dp, max(0, L), max(0, T), min(dw, Rr), min(dh, B), left, top, W, bytes(pal), 9, sx0, sy0, sx1, sy1)
    return dst, want, wrote, dp, dh, DSTDATA


@pytest.mark.parametrize("seed,W,bbox,left,top,clip", [
    (1, 100, (400, 380, 560, 600), 10, 20, None),
    (2, 300, (300, 300, 700, 720), -40, -30, (5, 5, 190, 150)),
    (3, 512, (0, 0, 1023, 1023), -200, -300, None),
    (4, 64, (500, 500, 520, 530), 100, 100, None),
])
def test_ssaa_composite_matches_the_c_port(seed, W, bbox, left, top, clip):
    e = Emu(25)
    e.land(RET_SITE)
    dst, want, wrote, dp, dh, DSTDATA = _ssaa_setup(e, seed, W, bbox, left, top, clip=clip)
    assert e.run(VA["thunk_dw_ssaa"], regs={"ecx": AD.CV_TARGET, "ebx": 1, "esi": 2, "edi": 3, "ebp": 4}, stack=[RET_SITE, AD.DW_CANVAS, left, top], count=200_000_000) == RET_SITE
    assert e.reg("esp") == SP0 + 0x10 and (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (1, 2, 3, 4)
    got = bytes(e.uc.mem_read(DSTDATA, dp * dh))
    assert got == want
    assert wrote > 0 and got != dst


def test_shim_nn_path_and_gate():
    e = Emu(22)
    e.land(AD.KSB, AD.BUFFER_DRAW_2, RET_SITE)
    e.w32(AD.CELL["g_dw_fitw"], 700)
    e.w32(AD.CELL["g_dw_fitoff"], 350 - 512)
    stack = [RET_SITE, AD.DW_CANVAS, 9, 1000 - 512, 800 - 512, 1, 1]
    assert e.run(VA["thunk_dw_shim"], regs={"ecx": AD.CV_TARGET}, stack=stack) == AD.KSB
    args = [e.r32(e.reg("esp") + 4 * i) for i in range(1, 12)]
    assert args == [AD.CV_TARGET, AD.DW_CANVAS, 0, 0, TN, TN, 1000 - 350, 800 - 350, 700, 700, 9]
    # half mode (den == 2: the engine's flag-0x20 render x2 + composite 1/2)
    stack[6] = 2
    assert e.run(VA["thunk_dw_shim"], regs={"ecx": AD.CV_TARGET}, stack=stack) == AD.KSB
    args = [e.r32(e.reg("esp") + 4 * i) for i in range(1, 12)]
    assert args[6:10] == [1000 - 512 - (350 - 512) // 2, 800 - 512 - (350 - 512) // 2, 350, 350]
    # suppressed (trial)
    e.w32(AD.CELL["g_dw_fitw"], 0)
    stack[6] = 1
    assert e.run(VA["thunk_dw_shim"], regs={"ecx": AD.CV_TARGET}, stack=stack) == RET_SITE and e.reg("esp") == SP0 + 0x1C
    # ungated dst / g<=16 -> Buffer_draw_2 with the stack untouched
    e.w32(AD.CELL["g_dw_fitw"], 700)
    assert e.run(VA["thunk_dw_shim"], regs={"ecx": AD.CV_TARGET}, stack=[RET_SITE, BUF, 9, 1, 2, 1, 1]) == AD.BUFFER_DRAW_2 and e.reg("esp") == SP0
    e.w32(AD.CELL["g_dw_pickcanvas"], BUF)
    assert e.run(VA["thunk_dw_shim"], regs={"ecx": AD.CV_TARGET}, stack=[RET_SITE, BUF, 9, 1, 2, 1, 1]) == AD.KSB
    e.set_g(16)
    assert e.run(VA["thunk_dw_shim"], regs={"ecx": AD.CV_TARGET}, stack=stack) == AD.BUFFER_DRAW_2


def test_shim_ssaa_path_composites():
    e = Emu(25)
    e.land(RET_SITE, AD.KSB, AD.BUFFER_DRAW_2)
    W = 128
    dst, want, wrote, dp, dh, DSTDATA = _ssaa_setup(e, 7, W, (480, 470, 560, 560), 30 - W // 2, 40 - W // 2)
    assert e.run(VA["thunk_dw_shim"], regs={"ecx": AD.CV_TARGET}, stack=[RET_SITE, AD.DW_CANVAS, 9, 30 - 512, 40 - 512, 1, 1], count=100_000_000) == RET_SITE
    assert e.reg("esp") == SP0 + 0x1C and e.reg("ecx") == AD.CV_TARGET
    assert bytes(e.uc.mem_read(DSTDATA, dp * dh)) == want and wrote > 0


# =====================================================================================
# the FIT thunk (law dw_fit_plan)
# =====================================================================================
CVOBJ = OBJ + 0x4000


def _fit_emu(g, bboxes, dst=AD.DW_CANVAS, flag=23, zoom=0.14, target_px0=0x18):
    e = Emu(g)
    e.land(RET_SITE, AD.CAVIAR_DRAW)
    e.w32(AD.CV_CTX, CTXOBJ)
    calls = {"draw": [], "reset": [], "fill": []}
    e.uc.mem_write(CVOBJ, bytes(range(256)) * 8)                  # a recognisable header to snapshot/restore
    e.uc.mem_write(CVOBJ + 0xD5, struct.pack("<f", zoom))
    e.uc.mem_write(BUF + 0x3000, bytes([target_px0]) * 16)
    e.buffer(AD.CV_TARGET, BUF + 0x3000, TN, TN, TN)

    def on_draw(em):
        n = len(calls["draw"])
        bb = bboxes[min(n, len(bboxes) - 1)]
        for i, v in enumerate(bb):
            em.w32(CTXOBJ + 8 + 4 * i, v)
        sp = em.reg("esp")
        calls["draw"].append({
            "this": em.reg("ecx"), "args": [em.r32(sp + 4 * i) for i in range(1, 5)],
            "zoom": struct.unpack("<f", em.uc.mem_read(em.reg("ecx") + 0xD5, 4))[0],
            "fitw": em.r32(AD.CELL["g_dw_fitw"]), "fitoff": em.r32(AD.CELL["g_dw_fitoff"]), "ssaaw": em.r32(AD.CELL["g_dw_ssaaw"]),
            "gated": em.r32(AD.CELL["g_dw_gated"]), "fpgated": em.r32(AD.CELL["g_dw_fpgated"]),
            "ovl": [em.r32(AD.OVL[k]) for k in ("ON", "OFF", "NUM", "DEN")],
            "hdr": bytes(em.uc.mem_read(em.reg("ecx") + 0x14, 0x100)),
        })
        # the engine mutates the header during a draw
        em.uc.mem_write(em.reg("ecx") + 0x20, b"\xEE" * 8)

    e.stub(AD.CAVIAR_DRAW + 0x800, asm("mov eax, 0; ret 0x10"))   # not used: CAVIAR_DRAW itself must return
    e.landings.discard(AD.CAVIAR_DRAW)
    e.stub(AD.CAVIAR_DRAW, asm("mov eax, 0x2A; ret 0x10"), on_draw)
    e.stub(AD.CAVIAR_RESET, asm("ret 4"), lambda em: calls["reset"].append((em.reg("ecx"), em.r32(em.reg("esp") + 4))))
    e.stub(AD.BUFFER_FILL_2, asm("ret 4"), lambda em: calls["fill"].append((em.reg("ecx"), em.r32(em.reg("esp") + 4))))
    return e, calls


def _plan_expect(bb, g, ovl):
    """bb as the ctx holds it (INCLUSIVE R/B); the thunk (like the proto's ctxBBox) plans on R+1/B+1."""
    return SL.dw_fit_plan((bb[0], bb[1], bb[2] + 1, bb[3] + 1), TN, g, ssaa=not ovl, fit=True)


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("bb", [(457, 394, 596, 554), (476, 440, 547, 577), (473, 474, 553, 549), (200, 100, 900, 1000), (0, 0, 1024, 1024),
                                (500, 500, 520, 520), (100, 500, 600, 520), (511, 511, 513, 513)])
def test_fit_plan_and_sequence(g, bb):
    for ovl in (False, True):
        flag = (6 if bb[0] & 1 else 23) | (8 if ovl else 0)     # part-box/picker icons pass 6, the preview 0x17
        e, calls = _fit_emu(g, [bb, (bb[0] - 10, bb[1] - 10, bb[2] + 10, bb[3] + 10)], flag=flag)
        hdr0 = bytes(e.uc.mem_read(CVOBJ + 0x14, 0x100))
        at = e.run(VA["thunk_dw_fit"], regs={"ecx": CVOBJ, "ebx": 5, "esi": 6, "edi": 7, "ebp": 8}, stack=[RET_SITE, AD.DW_CANVAS, 462, 257, flag])
        assert at == RET_SITE and e.reg("esp") == SP0 + 0x14 and e.reg("eax") == 0x2A
        assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (5, 6, 7, 8)
        assert len(calls["draw"]) == 2 and calls["reset"] == [(CVOBJ, 0)]
        trial, real = calls["draw"]
        assert trial["args"] == real["args"] == [AD.DW_CANVAS, 462, 257, flag] and trial["this"] == real["this"] == CVOBJ
        assert trial["fitw"] == 0 and trial["ssaaw"] == 0 and trial["gated"] == 1 and trial["fpgated"] == 0 and abs(trial["zoom"] - 0.14) < 1e-7
        zo = 0xD5 - 0x14
        assert real["hdr"][:zo] == hdr0[:zo] and real["hdr"][zo + 4:] == hdr0[zo + 4:], "header not restored after the trial"
        plan = _plan_expect(bb, g, ovl)
        W = plan["W"]
        if plan["mode"] == "ssaa":
            assert real["ssaaw"] == W and real["fitw"] == 0
        else:
            assert real["ssaaw"] == 0 and real["fitw"] == W and real["fitoff"] == W // 2 - TN // 2
        assert real["gated"] == 1 and real["fpgated"] == (1 if plan["mode"] != "nn" else 0)
        assert abs(real["zoom"] - 0.14 * plan["k"]) <= 1e-6 * max(1.0, 0.14 * plan["k"]), (real["zoom"], 0.14 * plan["k"], plan)
        if ovl:
            assert calls["fill"] == [(AD.CV_TARGET, 0x18)]
            d = math.gcd(W, TN)
            assert real["ovl"] == [1, W // 2 - TN // 2, W // d, TN // d]
            assert e.r32(AD.OVL["ON"]) == 0
        else:
            assert calls["fill"] == [] and real["ovl"][0] == 0
        # after: zoom restored, cells cleared, header back
        assert abs(struct.unpack("<f", e.uc.mem_read(CVOBJ + 0xD5, 4))[0] - 0.14) < 1e-7
        for c in ("g_dw_gated", "g_dw_fpgated", "g_dw_ssaaw", "g_dw_fitw"):
            assert e.r32(AD.CELL[c]) == 0, c
        hdr1 = bytes(e.uc.mem_read(CVOBJ + 0x14, 0x100))        # the REAL draw's own mutation (+0x20..+0x28) persists as in vanilla
        assert hdr1[:12] == hdr0[:12] and hdr1[20:] == hdr0[20:] and hdr1[12:20] == bytes([0xEE]) * 8


def test_fit_ungated_paths():
    e, calls = _fit_emu(22, [(400, 400, 600, 600)])
    e.land(AD.CAVIAR_DRAW)
    assert e.run(VA["thunk_dw_fit"], regs={"ecx": CVOBJ}, stack=[RET_SITE, BUF, 1, 2, 23]) == AD.CAVIAR_DRAW and e.reg("esp") == SP0   # other dst
    e.uc.mem_write(CVOBJ + 0xD5, struct.pack("<f", 0.0))
    assert e.run(VA["thunk_dw_fit"], regs={"ecx": CVOBJ}, stack=[RET_SITE, AD.DW_CANVAS, 1, 2, 23]) == AD.CAVIAR_DRAW
    e.uc.mem_write(CVOBJ + 0xD5, struct.pack("<f", 0.14))
    e.set_g(16)
    assert e.run(VA["thunk_dw_fit"], regs={"ecx": CVOBJ}, stack=[RET_SITE, AD.DW_CANVAS, 1, 2, 23]) == AD.CAVIAR_DRAW
    e2, calls2 = _fit_emu(22, [(400, 400, 600, 600)])
    e2.w32(AD.CELL["g_dw_pickcanvas"], BUF)
    assert e2.run(VA["thunk_dw_fit"], regs={"ecx": CVOBJ}, stack=[RET_SITE, BUF, 1, 2, 23]) == RET_SITE
    assert len(calls2["draw"]) == 2 and calls2["draw"][0]["fitw"] == 0 and calls2["draw"][1]["gated"] == 1
    assert len(calls["draw"]) == 3       # the three ungated runs reached the (landing) Caviar_draw entry directly


def test_fit_plan_integer_form_equals_the_law():
    """The thunk's integer plan (see asm_dw_fit) == dw_fit_plan for every g and radius."""
    for g in range(17, 41):
        for r in range(5, 600):
            for ovl in (False, True):
                bb = (512 - (r - 4), 512, 512 + 1, 513)     # radius r-4 left of centre (+ slack 4 = r)
                plan = SL.dw_fit_plan(bb, TN, g, ssaa=not ovl, fit=True)
                gr = g * r
                if not ovl and gr <= 8064:
                    mode, W = "ssaa", (512 if 2 * gr <= 8064 else (128 * gr + 504) // 1008)
                elif r <= 494:
                    mode, W = "fit", (1024 if gr <= 8064 else (128 * gr + 504) // 1008)
                else:
                    mode, W = "nn", 64 * g
                assert (plan["mode"].startswith(mode), plan["W"]) == (True, W), (g, r, ovl, plan, mode, W)


# =====================================================================================
# footprint: fpset + the two plotter caves (model from _dw_crops/v14/emu_fp.py)
# =====================================================================================
def fp_law(rows):
    def n_of(a, b, c):
        return min(8, max(2, (abs(a) + abs(b) + abs(c) + 255) >> 8))
    return n_of(*rows[0:3]), n_of(*rows[3:6])


@pytest.mark.parametrize("gated", (0, 1))
def test_fpset_cells(gated):
    e = Emu(25)
    e.land(AD.RUNTAB)
    rnd = random.Random(3)
    e.w32(AD.CV_PITCH, 1024)
    e.w32(AD.CV_ZPITCH, 1024)
    e.w32(AD.CV_DATA_BASE, 0x3000000)
    for _ in range(40):
        rows = [rnd.randrange(-1200, 1200) for _ in range(6)]
        for i, v in enumerate(rows):
            e.w16(AD.CV_MTX + 2 * i, v)
        e.w32(AD.CELL["g_dw_fpgated"], gated)
        regs = {"eax": 1, "ebx": 2, "ecx": 3, "edx": 4, "esi": 5, "edi": 6, "ebp": 7}
        assert e.run(VA["thunk_dw_fpset"], regs=regs) == AD.RUNTAB and e.reg("esp") == SP0
        assert all(e.reg(r) == v for r, v in regs.items())
        nx, ny = fp_law(rows) if gated else (2, 2)
        F = AD.FPC
        assert (e.r32(F["N"]), e.r32(F["NY"])) == (nx, ny)
        assert e.r32(F["ZROW"]) == 2 * 1024 - 2 * nx and e.r32(F["DROW"]) == 1024 - nx
        assert e.r32(F["SPAN"]) == (ny - 1) * 1024 + nx - 1 and e.ru32(F["DEND"]) == 0x3000000 + 1024 * TN


DBUF, ZBUF, TBL, PALB = 0x02100000, 0x02300000, 0x02000000, 0x02080000


def _fp_run(cave, n, idx, z, zinit, shade, cbase):
    nx, ny = n if isinstance(n, tuple) else (n, n)
    e = Emu(25)
    PITCH, H = 1024, 512
    e.land(AD.FP_RESUME, AD.FP2_RESUME)
    e.w32(AD.CV_Z_BASE, ZBUF)
    e.w32(AD.CV_DATA_BASE, DBUF)
    e.w32(AD.CV_SHADE_TBL, PALB)
    F = AD.FPC
    e.w32(F["N"], nx)
    e.w32(F["NY"], ny)
    e.w32(F["ZROW"], 2 * PITCH - 2 * nx)
    e.w32(F["DROW"], PITCH - nx)
    e.w32(F["SPAN"], (ny - 1) * PITCH + nx - 1)
    e.w32(F["DEND"], DBUF + PITCH * H)
    e.uc.mem_write(ZBUF, struct.pack("<H", zinit) * (PITCH * H))
    e.w8(TBL + shade, 0x07)
    e.w8(PALB + 0x700 + cbase, 0xAB)
    voxel = OBJ + 0x100
    e.uc.mem_write(voxel, bytes([0xC8, 0x11, cbase]))
    if cave == 1:
        regs = {"eax": shade, "ebx": cbase, "edi": voxel, "ebp": idx, "edx": 0xAA000000 | z, "ecx": 0x12345678}
        at = e.run(VA["thunk_dw_fp"], regs=regs, sp=TBL, stack=[])
        assert at == AD.FP_RESUME
        assert e.reg("ecx") == 0x12345678 and e.reg("ebp") == idx and e.reg("edi") == voxel + 3 and e.reg("edx") == (0xAA000000 | z) and e.reg("esp") == TBL
        assert (e.reg("ebx") & 0xFF) == 0xC8
    else:
        regs = {"eax": 0xAB, "ebx": idx - 100, "ecx": 100, "edx": 0xAA000000 | z, "esi": 5, "edi": 6, "ebp": 7}
        at = e.run(VA["thunk_dw_fp2"], regs=regs, sp=TBL, stack=[])
        assert at == AD.FP2_RESUME
        assert (e.reg("esi"), e.reg("edi"), e.reg("ebp"), e.reg("edx"), e.reg("esp")) == (5, 6, 7, 0xAA000000 | z, TBL)
    D = e.uc.mem_read(DBUF, PITCH * H)
    Z = e.uc.mem_read(ZBUF, PITCH * H * 2)
    px = {(i % PITCH, i // PITCH) for i in range(PITCH * H) if D[i] == 0xAB}
    zw = {i for i in range(PITCH * H) if struct.unpack_from("<H", Z, 2 * i)[0] != zinit}
    return px, zw


@pytest.mark.parametrize("cave", (1, 2))
@pytest.mark.parametrize("n", (2, 3, (2, 3), 5, 8))
def test_footprint_caves(cave, n):
    PITCH, H = 1024, 512
    nx, ny = n if isinstance(n, tuple) else (n, n)
    idx = 300 * PITCH + 200
    px, zw = _fp_run(cave, n, idx, 0x1234, 0xFFFF, 0x123, 0x30)
    exp = {(200 + i, 300 + j) for j in range(ny) for i in range(nx)}
    assert px == exp and zw == {(300 + j) * PITCH + 200 + i for j in range(ny) for i in range(nx)}
    px2, zw2 = _fp_run(cave, n, idx, 0x1234, 0x1000, 0x123, 0x30)
    assert not px2 and not zw2
    px3, _ = _fp_run(cave, n, (H - 1) * PITCH + 200, 0x1234, 0xFFFF, 0x123, 0x30)
    assert not px3


def test_clip_override_and_reset_guard():
    e = Emu(25)
    e.land(AD.CAVIAR_RASTERIZE, AD.CAVIAR_RESET)
    e.w32(AD.CV_CTX, CTXOBJ)
    for i in range(6):
        e.w32(CTXOBJ + 0x38 + 4 * i, 77 + i)
    e.w32(AD.CELL["g_dw_gated"], 0)
    assert e.run(VA["thunk_dw_clip"]) == AD.CAVIAR_RASTERIZE and [e.r32(CTXOBJ + 0x38 + 4 * i) for i in range(6)] == [77 + i for i in range(6)]
    e.w32(AD.CELL["g_dw_gated"], 1)
    assert e.run(VA["thunk_dw_clip"]) == AD.CAVIAR_RASTERIZE and [e.r32(CTXOBJ + 0x38 + 4 * i) for i in range(6)] == [0, 0, TN, TN, TN, TN]
    for rect, want in (((-5, 3, 1030, 2000), (0, 3, TN, TN)), ((3, -1, 100, 100), (3, 0, 100, 100)), ((0, 0, TN, TN), (0, 0, TN, TN))):
        for i, v in enumerate(rect):
            e.w32(AD.CV_MINX + 4 * i, v)
        assert e.run(VA["thunk_dw_resetguard"], stack=[RET_SITE, 1]) == AD.CAVIAR_RESET and e.reg("esp") == SP0
        assert tuple(e.r32(AD.CV_MINX + 4 * i) for i in range(4)) == want


# =====================================================================================
# E stubs + overlay one-shot
# =====================================================================================
def test_e_stubs_register_effects():
    e = Emu(25)
    e.land(0x617328, 0x6171EF, 0x6175A4, 0x6175EC)
    assert e.run(VA["thunk_dw_ewin"], regs={"ecx": 1000, "eax": 2000, "edx": 0x77}) == 0x617328
    assert e.reg("edi") == 1000 - 512 and e.reg("esi") == 2000 - 512 and e.reg("edx") == 1000 + 512 and e.reg("eax") == 2000 + 512
    assert e.r32(SP0 + 0x4C) == 0x77 and e.reg("ecx") == SP0 + 0x40 and e.r32(SP0 - 4) == SP0 + 0x40
    assert e.run(VA["thunk_dw_eovl"], regs={"ecx": 300, "edx": 400}) == 0x6171EF
    assert e.reg("ecx") == 300 - 512 + (1 << 32) and e.sreg("edx") == 400 - 512 and e.r32(SP0 - 4) == 1
    e.w32(SP0 + 0x8C, 900)
    e.w32(OBJ + 0x54, 0xABCD)
    assert e.run(VA["thunk_dw_ehalfa"], regs={"eax": 700, "ecx": OBJ}) == 0x6175A4
    assert e.sreg("eax") == 700 - 256 and e.reg("edx") == 0xABCD and e.sreg("ecx") == 900 - 256
    assert [e.r32(SP0 - 4 * i) for i in range(1, 6)] == [0xABCD, 2, 1, 700 - 256, 900 - 256]
    assert e.run(VA["thunk_dw_ehalfb"], regs={"ecx": 50, "edx": 60}) == 0x6175EC
    assert [e.r32(SP0 - 4 * i) for i in range(1, 4)] == [1, 50 - 256, 60 - 256]


def test_e_imms_are_the_option_e_set():
    assert len(AD.E_IMMS) == 17 and {n for n, *_ in AD.E_STUB_SITES} == {"thunk_dw_ewin", "thunk_dw_eovl", "thunk_dw_ehalfa", "thunk_dw_ehalfb"}
    for va, w, nat, new, _ in AD.E_IMMS:
        assert AD.base_exe_bytes(va, w) == (struct.pack("<I", nat) if w == 4 else bytes([nat]))


def test_ovl_one_shot():
    e = Emu(25)
    e.land(AD.OVL_TARGET)
    e.w32(AD.OVL["ON"], 1)
    e.w32(AD.OVL["OFF"], 100)
    e.w32(AD.OVL["NUM"], 563)
    e.w32(AD.OVL["DEN"], 1024)
    stack = [RET_SITE, AD.DW_CANVAS, 0x18, 226, -101, 1, 1, 0x6EEF7C]
    assert e.run(VA["thunk_dw_ovl"], regs={"ecx": AD.CV_TARGET}, stack=stack) == AD.OVL_TARGET
    assert [e.r32(SP0 + 4 * i) for i in range(1, 8)] == [AD.DW_CANVAS, 0x18, 126, -201, 563, 1024, 0x6EEF7C]
    assert e.r32(AD.OVL["ON"]) == 0 and e.reg("ecx") == AD.CV_TARGET and e.reg("esp") == SP0
    assert e.run(VA["thunk_dw_ovl"], regs={"ecx": AD.CV_TARGET}, stack=stack) == AD.OVL_TARGET
    assert [e.r32(SP0 + 4 * i) for i in range(1, 8)] == stack[1:]


# =====================================================================================
# backdrop (Python port of the proto's renderBackdrop) on the REAL deswin.pcx
# =====================================================================================
def load_pcx(path):
    b = path.read_bytes()
    xmin, ymin, xmax, ymax = struct.unpack_from("<4H", b, 4)
    bpl = struct.unpack_from("<H", b, 0x42)[0]
    w, h = xmax - xmin + 1, ymax - ymin + 1
    out = bytearray(bpl * h)
    i, o = 128, 0
    end = len(b) - 769 if b[-769] == 0x0C else len(b)
    while o < bpl * h and i < end:
        v = b[i]
        i += 1
        if (v & 0xC0) == 0xC0:
            n, v = v & 0x3F, b[i]
            i += 1
        else:
            n = 1
        out[o:o + n] = bytes([v]) * n
        o += n
    # ENGINE FACT: the canvas manager remaps PCX indices +10 mod 256 at load (the runtime palette);
    # the Buffer the thunk reads holds the remapped plane (census families 65/196/198, key 9 = file 255).
    return bytes((b + 10) & 0xFF for b in out), w, h, bpl


def py_backdrop(src, sw, sh, sp, g):
    """renderBackdrop port: returns (W, H, image rows bytes W*H, census dict)."""
    W, H = -((-sw * g) // 16), SL.scale_px(sh, g)
    cnt, vrun = [0] * 256, [0] * 256
    for x in range(sw):
        prev, run = -1, 0
        for y in range(sh):
            v = src[y * sp + x]
            cnt[v] += 1
            run = run + 1 if v == prev else 1
            prev = v
            if run > vrun[v]:
                vrun[v] = run
    FAM = [v != 9 and cnt[v] >= 0.02 * sw * sh and vrun[v] <= 2 for v in range(256)]
    cntE, cntS = [0] * 256, [0] * 256
    for y in range(sh):
        for x in range(sw):
            v = src[y * sp + x]
            if v == 9 or FAM[v]:
                continue
            if (y & 1) == 0:
                cntE[v] += 1
            if 0 < y < sh - 1:
                u, d = src[(y - 1) * sp + x], src[(y + 1) * sp + x]
                if u == d and FAM[u]:
                    cntS[v] += 1
    VAR = [v != 9 and not FAM[v] and cnt[v] >= 40 and max(cntE[v], cnt[v] - cntE[v]) >= 0.95 * cnt[v] and cntS[v] >= 0.8 * cnt[v] for v in range(256)]
    FL = lambda v: v >= 0 and (FAM[v] or VAR[v])   # noqa: E731
    ink = lambda v: v != 9 and not FAM[v] and not VAR[v]   # noqa: E731
    rows, cols = [], []
    for y in range(sh):
        run = best = 0
        for x in range(sw):
            run = run + 1 if ink(src[y * sp + x]) else 0
            best = max(best, run)
        if best >= 60:
            rows.append(y)
    for x in range(sw):
        run = best = 0
        for y in range(sh):
            run = run + 1 if ink(src[y * sp + x]) else 0
            best = max(best, run)
        if best >= 60:
            cols.append(x)
    xm = SL.line_axis_map(sw, W, cols, g)
    ym = SL.line_axis_map(sh, H, rows, g)
    assert xm is not None and ym is not None
    out = bytearray(W * H)
    for yd in range(H):
        ys, top = ym[yd], SL.stripe_top(yd, g)
        for xd in range(W):
            xs = xm[xd]
            v = src[ys * sp + xs]
            o = v
            if FL(v):
                up = src[(ys - 1) * sp + xs] if ys > 0 else -1
                dn = src[(ys + 1) * sp + xs] if ys < sh - 1 else -1
                mate = up if (FL(up) and up != v) else (dn if (FL(dn) and dn != v) else -1)
                if mate >= 0:
                    evc, odc = (v, mate) if (ys & 1) == 0 else (mate, v)
                    o = evc if top else odc
            out[yd * W + xd] = o
    census = {"fam": [v for v in range(256) if FAM[v]], "var": [v for v in range(256) if VAR[v]], "rows": rows, "cols": cols}
    return W, H, bytes(out), census


_PCX = None


def pcx():
    global _PCX
    if _PCX is None:
        p = config.game_dir(required=True) / "deswin.pcx"
        if not p.exists():
            pytest.skip("deswin.pcx not found in the game dir")
        _PCX = load_pcx(p)
    return _PCX


def test_pcx_census_matches_the_engine_measurement():
    src, sw, sh, bpl = pcx()
    assert (sw, sh) == (623, 368)
    W, H, out, census = py_backdrop(src, sw, sh, bpl, 22)
    assert census["fam"] == [65, 196, 198] and census["var"] == [197]
    assert census["rows"] == [0, 4, 94, 98, 188, 192, 282] and census["cols"] == [23, 27, 131, 135, 455, 459, 563, 567]


def _backdrop_emu(g, src, sw, sh, sp, ch_extra=48):
    e = Emu(g)
    e.land(RET_SITE)
    W = -((-sw * g) // 16)
    H = SL.scale_px(sh, g)
    ch = H + ch_extra
    cw = W
    cp = (cw + 3) & ~3
    SRC, CAN, NEWPCX = BUF + 0x10000, BUF + 0x80000, BUF + 0x280000
    e.uc.mem_write(SRC, src)
    e.buffer(OBJ + 0x13C6C, SRC, sw, sh, sp)
    fill = bytes([0]) * (cp * ch)
    e.uc.mem_write(CAN, fill)
    e.buffer(OBJ + 0x444, CAN, cw, ch, cp)
    calls = []

    def on_resize(em):
        w, h = em.r32(em.reg("esp") + 4), em.r32(em.reg("esp") + 8)
        calls.append((em.reg("ecx"), w, h))
        em.buffer(OBJ + 0x13C6C, NEWPCX, w, h, (w + 3) & ~3)
        em.uc.mem_write(NEWPCX, b"\xEE" * (((w + 3) & ~3) * h))
    e.stub(AD.BUFFER_RESIZE, asm("mov eax, 0; ret 8"), on_resize)
    return e, W, H, ch, cw, cp, CAN, NEWPCX, calls


@pytest.mark.parametrize("g", (22, 25, 40))
def test_backdrop_renders_the_pcx_at_device_density(g):
    src, sw, sh, bpl = pcx()
    W, H, want, census = py_backdrop(src, sw, sh, bpl, g)
    e, Wc, Hc, ch, cw, cp, CAN, NEWPCX, calls = _backdrop_emu(g, src, sw, sh, bpl)
    assert (Wc, Hc) == (W, H)
    assert e.run(VA["thunk_dw_backdrop"], regs={"ecx": OBJ, "ebx": 1, "esi": 2, "edi": 3, "ebp": 4}, count=400_000_000) == RET_SITE
    assert e.reg("esp") == SP0 + 4 and (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (1, 2, 3, 4)
    can = bytes(e.uc.mem_read(CAN, cp * ch))
    for y in range(H):
        assert can[y * cp: y * cp + W] == want[y * W:(y + 1) * W], f"canvas row {y} differs at g={g}"
    for y in range(H, ch):
        assert can[y * cp: y * cp + W] == bytes(W), "rows below the image must stay the engine fill"
    assert calls == [(OBJ + 0x13C6C, W, ch)]
    pp = (W + 3) & ~3
    npcx = bytes(e.uc.mem_read(NEWPCX, pp * ch))
    for y in range(ch):
        assert npcx[y * pp: y * pp + W] == can[y * cp: y * cp + W], f"pcx row {y}"
    # the lrow/lcol cells now hold the axis widths (line_axis_map)
    xm, ym = SL.line_axis_map(sw, W, census["cols"], g), SL.line_axis_map(sh, H, census["rows"], g)
    assert [e.r8(AD.BD["lcol"] + i) for i in range(sw)] == [xm.count(i) for i in range(sw)]
    assert [e.r8(AD.BD["lrow"] + i) for i in range(sh)] == [ym.count(i) for i in range(sh)]


def test_backdrop_skips_a_non_native_pcx():
    src, sw, sh, bpl = pcx()
    e, *_rest = _backdrop_emu(22, src, sw, sh, bpl)
    calls = _rest[-1]
    e.w32(OBJ + 0x13C6C + 0x80, 600)
    assert e.run(VA["thunk_dw_backdrop"], regs={"ecx": OBJ}) == RET_SITE and calls == []


@pytest.mark.parametrize("g", GS)
def test_axismap_helper_equals_line_axis_map(g):
    e = Emu(g)
    e.land(RET_SITE)
    rnd = random.Random(g)
    for src_n, dst_n, lines in ((368, SL.scale_px(368, g), [0, 4, 94, 98, 188, 192, 282]), (623, -((-623 * g) // 16), [23, 27, 131, 135, 455, 459, 563, 567]),
                                (50, SL.scale_px(50, g), sorted(rnd.sample(range(50), 6))), (10, SL.scale_px(10, g), []), (7, 7 * SL.stroke_width(g), list(range(7)))):
        flags = bytes(1 if i in lines else 0 for i in range(src_n))
        e.uc.mem_write(BUF, flags)
        assert e.run(VA["thunk_dw_axismap"], regs={"ebx": 1, "esi": 2, "edi": 3, "ebp": 4}, stack=[RET_SITE, src_n, dst_n, BUF]) == RET_SITE
        assert e.reg("esp") == SP0 + 0x10 and (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (1, 2, 3, 4)
        m = SL.line_axis_map(src_n, dst_n, lines, g)
        assert m is not None and e.reg("eax") == 1
        assert list(e.uc.mem_read(BUF, src_n)) == [m.count(i) for i in range(src_n)]
    e.uc.mem_write(BUF, bytes(20))
    assert e.run(VA["thunk_dw_axismap"], stack=[RET_SITE, 20, 10, BUF]) == RET_SITE and e.reg("eax") == 0   # dst < src: impossible


def test_build_wrapper_calls_backdrop_after_build():
    e = Emu(22)
    e.land(AD.BUILD, RET_SITE)
    assert e.run(VA["thunk_dw_build"], regs={"esi": OBJ, "ecx": OBJ}, stack=[0x43E9E4]) == AD.BUILD
    assert e.r32(SP0) == VA["thunk_dw_build2"] and e.reg("esp") == SP0 and e.ru32(AD.CELL["g_dw_ret2"]) == 0x43E9E4
    e.land(0x43E9E4)
    e.w32(OBJ + 0x13C6C + 0x80, 600)                 # non-native pcx -> the backdrop bails
    assert e.run(VA["thunk_dw_build2"], regs={"esi": OBJ}, stack=[]) == 0x43E9E4 and e.reg("esp") == SP0


# =====================================================================================
# picker_grid_leave_present / popup_listbox_reserve / wheel_scroll
# =====================================================================================
def test_gridleave_draws_then_presents():
    e = Emu(25)
    e.land(0x433919)
    seen = []
    e.stub(AD.PK_DRAWCELL, asm("ret 8"), lambda em: seen.append(("draw", em.reg("ecx"), em.r32(em.reg("esp") + 4), em.r32(em.reg("esp") + 8))))
    PRESENT = STUBS + 0x300
    e.stub(PRESENT, asm("ret"), lambda em: seen.append(("present", em.reg("ecx"))))
    e.w32(PICKER, 0x66B2B8)
    e.w32(0x66B2B8 + 0xFC, PRESENT)
    assert e.run(VA["thunk_dw_gridleave"], regs={"esi": PICKER, "ecx": PICKER}, stack=[0x433919, 5, 0]) == 0x433919
    assert seen == [("draw", PICKER, 5, 0), ("present", PICKER)] and e.reg("esp") == SP0 + 0xC and e.reg("esi") == PICKER


def test_sbv_registers_the_heap_bar_under_the_popup_gate():
    e = Emu(22)
    e.land(RET_SITE)
    WIN, SB = OBJ + 0x9000, OBJ + 0xA000
    e.w32(WIN + 0x43C, SB)
    e.w32(SB, AD.SB_VTBL)
    for popup, g, vt, want, fd in ((1, 22, AD.SB_VTBL, SB, 0), (0, 22, AD.SB_VTBL, 0, 0), (1, 16, AD.SB_VTBL, 0, 0), (1, 22, 0x669D00, 0, 0),
                                   (0, 22, AD.SB_VTBL, SB, 1), (0, 16, AD.SB_VTBL, 0, 1), (0, 40, 0x669D00, 0, 1)):   # 2026-09-26q: file dialog
        e.w32(AD.G_POPUP_ACTIVE, popup)
        e.w32(G_FILEDLG_ACTIVE, fd)
        e.set_g(g)
        e.w32(SB, vt)
        e.w32(AD.G_RAIL_SB, 0)
        assert e.run(VA["thunk_dw_sbv"], regs={"esi": WIN}) == RET_SITE and e.reg("ecx") == SB and e.reg("esp") == SP0 + 4
        assert e.ru32(AD.G_RAIL_SB) == want, (popup, g, hex(vt))
    e.w32(WIN + 0x43C, 0)
    e.w32(AD.G_POPUP_ACTIVE, 1)
    e.set_g(22)
    assert e.run(VA["thunk_dw_sbv"], regs={"esi": WIN}) == RET_SITE and e.ru32(AD.G_RAIL_SB) == 0 and e.reg("ecx") == 0


def test_hide_clears_only_this_popups_bar():
    e = Emu(22)
    e.land(AD.HIDE_TARGET)
    POP, SB = OBJ + 0x9000, OBJ + 0xA000
    e.w32(POP + 0x2794, SB)
    for cur, want in ((SB, 0), (SB + 8, SB + 8), (0, 0)):
        e.w32(AD.G_RAIL_SB, cur)
        assert e.run(VA["thunk_dw_hide"], regs={"esi": POP}) == AD.HIDE_TARGET and e.ru32(AD.G_RAIL_SB) == want and e.reg("esp") == SP0
    e.w32(POP + 0x2794, 0)
    e.w32(AD.G_RAIL_SB, SB)
    assert e.run(VA["thunk_dw_hide"], regs={"esi": POP}) == AD.HIDE_TARGET and e.ru32(AD.G_RAIL_SB) == SB


@pytest.mark.parametrize("reg", ("ecx", "eax", "ebp", "edx"))
def test_lbres_helpers(reg):
    e = Emu(22)
    e.land(RET_SITE)
    e.w32(AD.G_SBW, 20)
    try:
        e.uc.mem_map(AD.G_RW_INLIST & ~0xFFF, 0x1000)
    except Exception:  # noqa: BLE001  (already mapped)
        pass
    for active, g, inlist, want, fd in ((1, 22, 0, 27, 0), (1, 25, 0, 31, 0), (1, 40, 0, 50, 0), (1, 16, 0, 20, 0), (0, 40, 0, 20, 0), (1, 12, 0, 20, 0),
                                        (1, 40, 1, 20, 0), (1, 22, 1, 20, 0), (0, 40, 1, 20, 0), (1, 16, 1, 20, 0),   # v2: rw console bracket -> raw
                                        (0, 22, 0, 27, 1), (0, 25, 0, 31, 1), (0, 40, 0, 50, 1), (0, 16, 0, 20, 1),   # v3: file dialog gate
                                        (0, 40, 1, 20, 1), (1, 40, 0, 50, 1)):
        e.w32(AD.G_POPUP_ACTIVE, active)
        e.w32(G_FILEDLG_ACTIVE, fd)
        e.w32(AD.G_RW_INLIST, inlist)
        e.set_g(g)
        regs = {"eax": 0x1111, "ecx": 0x2222, "edx": 0x3333, "esi": 0x4444, "edi": 0x5555, "ebx": 0x6666, "ebp": 0x7777}
        assert e.run(VA[f"thunk_lbres_{reg}"], regs=regs) == RET_SITE and e.reg("esp") == SP0 + 4
        assert e.reg(reg) == want == SL.listbox_bar_reserve(20, g, bool(active), bool(inlist), filedlg_active=bool(fd))
        for r, v in regs.items():
            if r != reg:
                assert e.reg(r) == v
    assert len(AD.LBRES_SITES) == 20 and len({s[1] for s in AD.LBRES_SITES}) == 20


VT_PART, VT_PROD, VT_POPUP, VT_POPUP2, VT_FILEDLG, VT_TEXTSCROLL, VT_PREFSUB = AD.VT_PART, AD.VT_PROD, AD.VT_POPUP, AD.VT_POPUP2, AD.VT_FILEDLG, AD.VT_TEXTSCROLL, AD.VT_PREFSUB
REC = STUBS + 0x400


def _wheel_run(press, lparam, wparam, vt, engaged=True, rng=(0, 5), basepop=False, modal=True, target=0x12345678, railptr=True):
    e = Emu(22)
    e.land(0x5F07B5)
    e.stub(AD.GET_TARGET, asm(f"mov eax, {target:#x}; ret"))
    e.stub(AD.CHEVRON, asm(f"mov dword ptr [{REC:#x}], ecx; mov eax, dword ptr [esp+4]; mov dword ptr [{REC + 4:#x}], eax; ret 4"))
    PRESENT = STUBS + 0x500
    e.stub(PRESENT, asm(f"mov dword ptr [{REC + 8:#x}], ecx; ret"))
    obj = OBJ + 0x1000
    e.w32(AD.BASEPOP, obj if basepop else 0)
    e.w32(AD.MODAL_TOP, obj if modal else 0)
    e.w32(obj, vt)
    sboff = {VT_PART: 0xA14, VT_PROD: 0x7120, VT_FILEDLG: 0x3DD8, VT_TEXTSCROLL: 0xA20, VT_PREFSUB: 0xEF0}.get(vt)
    if vt in (VT_POPUP, VT_POPUP2):
        sb = OBJ + 0xC000
        e.w32(obj + 0x2794, sb if railptr else 0)
    elif sboff is not None:
        sb = obj + sboff
    else:
        sb = obj + 0x100
    e.w32(sb + 0xC4, 1 if engaged else 0)
    e.w32(sb + 0xA20, rng[0])
    e.w32(sb + 0xA24, rng[1])
    if 0x669000 <= vt < 0x66D000:
        e.w32(vt + 0xFC, PRESENT)
    for i in range(3):
        e.w32(REC + 4 * i, 0)
    e.w32(SP0 + 0x68, wparam)
    e.w32(SP0 + 0x6C, lparam)
    regs = {"ebx": 0x1111, "esi": 0x2222, "edi": 0x3333, "ebp": 0x4444}
    assert e.run(VA["thunk_wheel_down" if press else "thunk_wheel_up"], regs=regs, stack=[0x5F07B5]) == 0x5F07B5
    assert e.reg("esp") == SP0 + 4 and all(e.reg(r) == v for r, v in regs.items())
    return e.reg("eax"), tuple(e.ru32(REC + 4 * i) for i in range(3)), sb, obj


def test_wheel_thunks_class_table():
    T = 0x12345678
    for vt in (VT_PART, VT_PROD, VT_FILEDLG, VT_TEXTSCROLL, VT_PREFSUB):
        eax, rec, sb, o = _wheel_run(True, 0, 0x26, vt)
        assert eax == 0 and rec == (sb, 1, o), hex(vt)
        eax, rec, sb, o = _wheel_run(True, 0, 0x28, vt, basepop=True, modal=False)
        assert eax == 0 and rec == (sb, 2, o)
    for vt in (VT_POPUP, VT_POPUP2):
        eax, rec, sb, o = _wheel_run(True, 0, 0x28, vt, basepop=True, modal=False)
        assert eax == 0 and rec == (sb, 2, o)
        eax, rec, sb, o = _wheel_run(True, 0, 0x28, vt, basepop=True, railptr=False)
        assert eax == T and rec == (0, 0, 0)
        eax, rec, sb, o = _wheel_run(True, 0, 0x28, vt, basepop=True, engaged=False)
        assert eax == T and rec == (0, 0, 0)
    assert _wheel_run(True, 0x00480001, 0x28, VT_PART)[0] == T          # real key
    assert _wheel_run(True, 0, 0x25, VT_PART)[0] == T                   # other key
    assert _wheel_run(True, 0, 0x28, VT_PART, rng=(0, 0))[0] == T
    assert _wheel_run(True, 0, 0x28, 0x66A100)[0] == T                  # unknown class
    assert _wheel_run(True, 0, 0x28, VT_PART, modal=False)[0] == T
    eax, rec, _, _ = _wheel_run(True, 0, 0x28, VT_PART, target=0)
    assert eax == 0 and rec == (0, 0, 0)
    eax, rec, _, _ = _wheel_run(False, 0, 0x28, VT_POPUP, basepop=True)
    assert eax == 0 and rec == (0, 0, 0)
    assert _wheel_run(False, 0x00480001, 0x28, VT_POPUP, basepop=True)[0] == T


# =====================================================================================
# in-place upgrades + layout facts
# =====================================================================================
def test_inplace_upgrades_fit_their_slots_and_keep_the_v1_prefix_shape():
    for cid, off, fn, maxsz in AD.INPLACE:
        b = fn()
        assert len(b) <= maxsz, cid
    assert AD.NESTPADS_V2[:18] == AD.NESTPADS_V1[:18] and AD.CHILDX_V2[:10] == AD.CHILDX_V1[:10]


def test_layout_fits_and_sites_are_unique():
    layout, end = AD.assemble_all()
    assert end <= AD.OFF_CELLS
    sites = AD.site_list()
    ids = [s["id"] for s in sites]
    assert len(ids) == len(set(ids)) == 80   # 2026-09-26q2 +2 g_scrollbar_w.CD1/CD2 (calc_dims fixed-box reserve subtract)
    vas = sorted((s["va"], s["va"] + len(s["orig"])) for s in sites)
    for (a0, a1), (b0, b1) in zip(vas, vas[1:]):
        assert a1 <= b0, (hex(a0), hex(b0))
    assert AD.verify_live(sites) == []
    assert AD.roundtrip_problems(layout) == []


def test_wheel_filedlg_falls_back_to_the_list_heap_bar():
    """2026-09-26q (thunk_fd_wheelbar): the MAIN-MENU picker has no rail bar (+0x3DD8 parent 0);
    its list window's heap V bar [FileDlg+0x3704] takes the chevron press.  v1 passed the key
    through, and the list's arrow-key handler moved the SELECTION instead of scrolling."""
    T = 0x12345678
    for press, wparam, btn in ((True, 0x26, 1), (True, 0x28, 2)):
        e = Emu(22)
        e.land(0x5F07B5)
        e.stub(AD.GET_TARGET, asm(f"mov eax, {T:#x}; ret"))
        e.stub(AD.CHEVRON, asm(f"mov dword ptr [{REC:#x}], ecx; mov eax, dword ptr [esp+4]; mov dword ptr [{REC + 4:#x}], eax; ret 4"))
        PRESENT = STUBS + 0x500
        e.stub(PRESENT, asm(f"mov dword ptr [{REC + 8:#x}], ecx; ret"))
        obj, heap = OBJ + 0x1000, OBJ + 0x8000
        e.w32(AD.BASEPOP, 0)
        e.w32(AD.MODAL_TOP, obj)
        e.w32(obj, VT_FILEDLG)
        e.w32(VT_FILEDLG + 0xFC, PRESENT)
        e.w32(obj + 0x3DD8 + 0xC4, 0)                      # rail bar never created (main menu)
        e.w32(obj + 0x3704, heap)
        e.w32(heap, AD.SB_VTBL)
        e.w32(heap + 0xC4, 1)
        e.w32(heap + 0xA20, 0)
        e.w32(heap + 0xA24, 5)
        for i in range(3):
            e.w32(REC + 4 * i, 0)
        e.w32(SP0 + 0x68, wparam)
        e.w32(SP0 + 0x6C, 0)
        regs = {"ebx": 0x1111, "esi": 0x2222, "edi": 0x3333, "ebp": 0x4444}
        assert e.run(VA["thunk_wheel_down"], regs=regs, stack=[0x5F07B5]) == 0x5F07B5
        assert e.reg("esp") == SP0 + 4 and all(e.reg(r) == v for r, v in regs.items())
        assert e.reg("eax") == 0 and tuple(e.ru32(REC + 4 * i) for i in range(3)) == (heap, btn, obj)
        # not a ScrollBar at +0x3704 -> the key passes through untouched (v1 behaviour)
        e.w32(heap, 0x669D00)
        for i in range(3):
            e.w32(REC + 4 * i, 0)
        assert e.run(VA["thunk_wheel_down"], regs=regs, stack=[0x5F07B5]) == 0x5F07B5
        assert e.reg("eax") == T and tuple(e.ru32(REC + 4 * i) for i in range(3)) == (0, 0, 0)
