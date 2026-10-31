"""W1A asm parity (assemble_type1_gaps.py): t_btn_vgap (fix 25a), t_band_bdraw + thunk_title_height v2 (fix 25b),
t_rowbox_trim (F35) -- Unicorn on the patches.yaml bytes resolved at their real cave VAs, against the laws in
scaling_laws.py (popup_box_h_btn_pad, title_band_draw_rect, popup_title_band_rows, option_row_frame_site_rect).

Each thunk's callee is a stub that records what it was handed (and RETs with the callee's contract), so the tests
see exactly the rect / ecx / args the real callee would get, every register the contract keeps, the stack balance,
and that nothing else in memory was written.  The wiring tests check that the sites and the two title-band tails
reach these thunks and that each thunk tails into the callee its contract names.  Pure Unicorn on a few hundred
bytes: no bake, no boot (~1 s for the module).
"""
from __future__ import annotations

import pathlib
import struct
import sys
from functools import lru_cache

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_patches as ap  # noqa: E402
import assemble_pf_align as PF  # noqa: E402
import assemble_type1_gaps as A  # noqa: E402
import scaling_laws as SL  # noqa: E402

YAML = ROOT / "patches" / "patches.yaml"
GS = range(16, 41)
STACK, SP0 = 0x00300000, 0x00308000
POPUP = 0x00500000
HEAP = 0x00600000
RET_VA = 0x00401000               # a return address in .text, mapped as `hlt`
REGS0 = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: POPUP, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x00307000,
         UC_X86_REG_EDX: 0x5555, UC_X86_REG_EAX: 0x6666, UC_X86_REG_ECX: 0x7777}


@lru_cache(maxsize=1)
def _yaml():
    sites, _g, caves, syms = ap.load_patches(YAML)
    st = dict(ap.build_symbol_table(syms, caves))
    ents = {c["id"]: c for cave in caves for c in cave.get("contents") or []}
    return sites, st, ents


def _bytes(name: str) -> bytes:
    _s, st, ents = _yaml()
    return bytes(ap.ByteTemplate(ents[name]["bytes"]).resolve(st[name], st))


def _site(sid: str) -> dict:
    sites, _st, _e = _yaml()
    return next(s for s in sites if s["id"] == sid)


class Rig:
    """A Unicorn with the thunk at its VA, g, a popup page, a stack, and stubs at the callee VAs."""

    def __init__(self, g: int):
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((0x00400000, 0x2000), (0x00668000, 0x1000), (A.PCAVE2, 0x34000), (STACK, 0x10000),
                           (POPUP, 0x4000), (HEAP, 0x1000), (0x00700000, 0x1000)):
            uc.mem_map(base, size)
        uc.mem_write(RET_VA, b"\xF4")
        uc.mem_write(A.POPUP_SCALE, _bytes("popup_scale"))          # the real helper t_btn_vgap calls
        uc.mem_write(A.G, struct.pack("<i", g))
        self.writes = []
        self.calls = []

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def stub(self, va: int, ret_n: int, eax=None, read_rect=True):
        """A stub at va: records (ecx, [esp+4], [esp+8], *rect at [esp+4]) and RETs ret_n."""
        def cb(u, addr, size, _):
            esp = u.reg_read(UC_X86_REG_ESP)
            a1, a2 = self.r32(esp + 4), self.r32(esp + 8)
            rect = struct.unpack("<4i", bytes(u.mem_read(a1 & 0xFFFFFFFF, 16))) if read_rect else None
            self.calls.append(dict(va=va, ecx=u.reg_read(UC_X86_REG_ECX), a1=a1 & 0xFFFFFFFF, a2=a2 & 0xFFFFFFFF,
                                   rect=rect, esp=esp, regs={r: u.reg_read(r) for r in (UC_X86_REG_EBX,
                                   UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)}))
            ret = self.r32(esp)
            u.reg_write(UC_X86_REG_ESP, esp + 4 + ret_n)
            if eax is not None:
                u.reg_write(UC_X86_REG_EAX, eax)
            u.reg_write(UC_X86_REG_EIP, ret & 0xFFFFFFFF)
        self.uc.hook_add(UC_HOOK_CODE, cb, begin=va, end=va)

    def run(self, va: int, code: bytes, regs: dict, stack: list, watch=None):
        uc = self.uc
        uc.mem_write(va, code)
        sp = SP0
        for i, v in enumerate([RET_VA] + stack):
            self.w32(sp + 4 * i, v)
        for r, v in {**REGS0, **regs}.items():
            uc.reg_write(r, v & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, sp)
        if watch:
            lo, hi = watch
            uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size, val, _: self.writes.append(addr),
                        begin=lo, end=hi)
        uc.emu_start(va, RET_VA, count=20_000)
        return uc


# ================================================================ the bytes are the assembler's
def test_yaml_bytes_are_the_assembler_output():
    _s, st, _e = _yaml()
    for name, (va, blob, _t) in A.build().items():
        assert st[name] == va, (name, hex(st[name]), hex(va))
        assert _bytes(name) == blob, name
    # the fixed VAs the assembler tails into are the symbols' own
    assert st["thunk_box_thick_flat"] == A.THUNK_BOX_THICK_FLAT and st["t_rowbox_ph"] == A.T_ROWBOX_PH
    assert st["g_popup_scale_num"] == A.G and st["popup_scale"] == A.POPUP_SCALE


def test_wiring_sites_and_tails():
    _s, st, ents = _yaml()
    s = _site("BasePop_calculate_dimensions.dialog_btn_span")
    assert s["virtual_addr"] == A.SITE_BTN_VGAP and s["original_bytes"] == A.SITE_BTN_VGAP_ORIG
    assert s["new_bytes"] == "E8 {rel32:t_btn_vgap} 90"
    # 2026-10-25 W7R v2: -> t_rowbox_solid, which CALLs t_rowbox_trim (test_thin_rings_asm_parity.py)
    # 2026-10-27 W9B: -> t1c_bar, which CALLs or tail-jumps t_rowbox_solid (test_type1_bar_asm_parity.py)
    assert _site("FUN_00405b20.option_frame")["new_bytes"] == "E8 {rel32:t1c_bar}"
    # the title band pair draws through t_band_bdraw (pf_align's ASM_TITLE is thunk_pf_title_stash's source)
    assert ents["thunk_inner_margin"]["bytes"].endswith("68 {abs32:t_band_bdraw} C3")
    assert ents["thunk_pf_title_stash"]["bytes"] == PF.template(PF.ASM_TITLE)[1]
    assert ents["thunk_pf_title_stash"]["bytes"].endswith("68 {abs32:t_band_bdraw} C3")
    users = {i for i, e in ents.items() if "{abs32:t_band_bdraw}" in str(e.get("bytes", ""))}
    assert users == {"thunk_inner_margin", "thunk_pf_title_stash"}
    # t_rowbox_trim tails t_rowbox_ph; t_band_bdraw calls / tails thunk_box_thick_flat
    assert _bytes("t_rowbox_trim")[-6:] == b"\x68" + struct.pack("<I", st["t_rowbox_ph"]) + b"\xC3"
    assert _bytes("t_band_bdraw")[-6:] == b"\x68" + struct.pack("<I", st["thunk_box_thick_flat"]) + b"\xC3"


# ================================================================ t_btn_vgap (fix 25a)
@pytest.mark.parametrize("g", GS)
def test_btn_vgap_is_the_law(g):
    code = _bytes("t_btn_vgap")
    for src in (4, 3, 5, 6, 0):
        for flags in (0, 0x40, 0x400, 0x441, 0x10100):
            pad = SL.popup_pad_y(src, g) if not flags & 0x400 else src       # the engine's [+0x30E4] per branch
            for body in (0, 15, -1):
                for dialog in (0, 418, 1):
                    rig = Rig(g)
                    for off, v in ((0x30E4, pad), (0x30D4, body), (0x30C4, dialog), (0x30A8, flags), (0x21C4, src)):
                        rig.w32(POPUP + off, v)
                    uc = rig.run(A.T_BTN_VGAP, code, {}, [], watch=(STACK, STACK + 0x10000 - 1))
                    want = SL.popup_box_h_btn_pad(pad, src, body, dialog, flags, g)
                    assert uc.reg_read(UC_X86_REG_ECX) == want & 0xFFFFFFFF, (g, src, flags, body, dialog)
                    if g > 16 and body == 0 and dialog and not flags & 0x400:
                        assert pad + want == SL.popup_dialog_btn_span(src, g) == ((2 * ((3 * src) >> 1) * g) >> 4)
                    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4                    # bare ret
                    for r, v in REGS0.items():
                        if r != UC_X86_REG_ECX:
                            assert uc.reg_read(r) == v & 0xFFFFFFFF, (g, r)
                    # the only writes: its own push / call frame below the entry esp (no popup field written)
                    assert all(a < SP0 for a in rig.writes), [hex(a) for a in rig.writes]


def test_btn_vgap_closes_the_measured_shortfall():
    """The pair 2 fl(6g/16) was up to 1.75 px short of 12 x g/16 (g = 21 / 29 / 37); the law is fl(12g/16)."""
    worst_old = max(12 * g / 16 - 2 * SL.popup_pad_y(4, g) for g in GS)
    assert worst_old == 1.75
    for g in GS:
        span = SL.popup_dialog_btn_span(4, g)
        assert span == (12 * g) >> 4 and 0 <= 12 * g / 16 - span < 1
        assert SL.popup_box_h_btn_pad(SL.popup_pad_y(4, g), 4, 0, 1, 0, g) - SL.popup_pad_y(4, g) in (0, 1)


# ================================================================ t_band_bdraw (fix 25b)
RECT = (13, 32, 1708, 92)


@pytest.mark.parametrize("g", GS)
def test_band_bdraw_hands_the_flat_thickener_a_trimmed_copy(g):
    rig = Rig(g)
    rect_va, params = HEAP + 0x100, 0x78D5A0
    rig.uc.mem_write(rect_va, struct.pack("<4i", *RECT))
    rig.stub(A.THUNK_BOX_THICK_FLAT, 8, eax=0x0BADF00D)
    uc = rig.run(A.T_BAND_BDRAW, _bytes("t_band_bdraw"), {UC_X86_REG_ECX: 0x00940824}, [rect_va, params],
                 watch=(HEAP, HEAP + 0xFFF))
    assert len(rig.calls) == 1
    c = rig.calls[0]
    assert c["rect"] == SL.title_band_draw_rect(*RECT, g)
    assert c["ecx"] == 0x00940824 and c["a2"] == params
    assert (c["a1"] == rect_va) == (g <= 16)                     # g > 16: a stack copy; g <= 16: the engine's rect
    assert c["regs"] == {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: POPUP, UC_X86_REG_EDI: 0x3333,
                         UC_X86_REG_EBP: 0x00307000}
    assert struct.unpack("<4i", bytes(uc.mem_read(rect_va, 16))) == RECT and not rig.writes   # never written
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 12                                            # RET 8
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert uc.reg_read(r) == REGS0[r]


# ================================================================ thunk_title_height v2 (fix 25b)
@pytest.mark.parametrize("g", GS)
def test_title_height_v2_is_the_band_rows_law(g):
    code = _bytes("thunk_title_height")
    for frame_t in (0, 5, -3, 117):
        rig = Rig(g)
        uc = rig.run(A.THUNK_TITLE_HEIGHT, code, {UC_X86_REG_EAX: frame_t + 3, UC_X86_REG_EDX: 900}, [])
        t, b = SL.popup_title_band_rows(frame_t, g)
        eax, ecx = uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_ECX)
        assert eax == t & 0xFFFFFFFF and (ecx - 1) & 0xFFFFFFFF == b & 0xFFFFFFFF, (g, frame_t)   # caller's dec
        assert uc.reg_read(UC_X86_REG_EDX) == 899                                                 # the replayed dec
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert uc.reg_read(r) == REGS0[r]
        if g == 16:
            assert (t, b) == (frame_t + 4, frame_t + 28)                                          # vanilla


def test_title_band_rows_each_edge_one_floor():
    for g in GS:
        t, b = SL.popup_title_band_rows(0, g)
        assert 0 <= 4 * g / 16 - t < 1 and 0 <= 28 * g / 16 - b < 1
        old_b = ((4 * g) >> 4) + ((24 * g) >> 4)
        assert b - old_b == (1 if g % 4 == 3 else 0), g                  # v1 lost a row at g = 3 mod 4


# ================================================================ t_rowbox_trim (F35)
ROW = (59, 3, 1642, 53)


@pytest.mark.parametrize("g", GS)
def test_rowbox_trim_is_the_law(g):
    code = _bytes("t_rowbox_trim")
    for dtype in (1, 2, 16, 8, 0, 4):
        for anchor in (0, SL.DIPLO_TALK_ANCHOR, 0x12345):
            rig = Rig(g)
            ebp = 0x00307000
            local = ebp - 0x14
            rig.uc.mem_write(local, struct.pack("<4i", *ROW))
            rig.w32(ebp - 4, POPUP)
            rig.w32(POPUP + 0x2350, dtype)
            rig.w32(POPUP + 0xA14, anchor)
            rig.stub(A.T_ROWBOX_PH, 8, eax=0x0BADF00D)
            uc = rig.run(A.T_ROWBOX_TRIM, code, {UC_X86_REG_ECX: 0x00512444, UC_X86_REG_EBP: ebp},
                         [local, 0x78D960], watch=(STACK, STACK + 0xFFFF))
            assert len(rig.calls) == 1
            c = rig.calls[0]
            want = SL.option_row_frame_site_rect(*ROW, g, dtype, anchor == SL.DIPLO_TALK_ANCHOR)
            assert c["rect"] == want and c["a1"] == local and c["a2"] == 0x78D960, (g, dtype, hex(anchor))
            assert c["ecx"] == 0x00512444 and c["esp"] == SP0                  # a tail jump: the site's frame
            assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 12                   # t_rowbox_ph's RET 8
            assert set(rig.writes) <= set(range(local + 8, local + 16)) | set(range(SP0 - 4, SP0)), \
                [hex(a) for a in rig.writes]                                 # only the local's r / b (+ push)


def test_option_row_frames_are_trimmed_exactly_once():
    """Composed with t_dp_itemrect's law (the type-16 / anchored rows' input copy), every row frame the band map
    paints is bandmap_rect_from_halfopen of the engine's rect, once, for every dialog type and anchor."""
    for g in GS:
        for dtype in (0, 1, 2, 4, 8, 16):
            for anchored in (False, True):
                first = SL.t16_item_draw_rect(*ROW, g, anchored=anchored, dialog_type=dtype)
                drawn = SL.option_row_frame_site_rect(*first, g, dtype, anchored)
                assert drawn == SL.bandmap_rect_from_halfopen(*ROW, g), (g, dtype, anchored)
