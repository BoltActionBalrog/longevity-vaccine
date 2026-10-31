"""The ornate text-box fix on the REAL patched bytes (engine + every thunk in the chain).

thunk_pf_frame_align v9 moves an ornate popup's d528 text box onto the title inner by mutating the
engine LOCAL; the engine's body-only ring (0x4061FA -> thunk_popup_nestpads @0x406211) and the body
text (BasePop_on_redraw 0x604DF5 -> thunk_faction_textmargin -> thunk_pf_textfollow v3) must follow.
test_pfalign_asm_parity checks each thunk against its law in isolation; this module applies the whole
patch set to a copy of the pristine .bak, maps the result into Unicorn and runs the ENGINE code of
Popup_on_draw_background from 0x4060E7 (content-origin sums -> thunk_popup_fieldR -> fieldpads ->
the d528 draw chain -> the body-only ring path -> nestpads) to the ring draw at 0x406238, then
BasePop_on_redraw's body-text block 0x604DAB..0x604DF5 through the text thunks to Buffer_write_strings.

Asserted per g in 16..40 (ornate type 6, no dialog, no art, titled, margin fl(19g/16)):
  * text box L  == title stash + ps3            (law ornate_text_box_edge_l / body_inner_edge_l)
  * ring L      == title stash                   (vanilla: ring on the title OUTER column)
  * text X      == text box L + ps3             (law ornate_text_x: the same pitch as the right side)
  * text WIDTH  == the engine's own width        (line breaks unchanged)
and g == 16 is the engine's arithmetic untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn")
pefile = pytest.importorskip("pefile")

import apply_patches as ap  # noqa: E402
from scaling_laws import popup_pad, popup_scale_floor  # noqa: E402
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

G_ADDR = 0x668740                 # g_popup_scale_num
BUF_WRITE_STRINGS = 0x5DB040
RING_DRAW = 0x406238              # call thunk_content_frame (the ring), [esp+4] = &local_24
POPUP = 0x03000000
STACK = 0x02000000
STASH_L, STASH_R = 32, 1717       # popup-local title stash (4K #RENAME Pause dump); scaled per g below


@pytest.fixture(scope="module")
def image(baked_exe):
    pe = pefile.PE(str(baked_exe))
    doc = ap._yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    sym = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    return pe, sym


def _emu(pe):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    base = pe.OPTIONAL_HEADER.ImageBase
    size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
    uc.mem_map(base, size)
    uc.mem_write(base, pe.header[:0x1000])
    for s in pe.sections:
        uc.mem_write(base + s.VirtualAddress, s.get_data()[:max(s.Misc_VirtualSize, s.SizeOfRawData)])
    uc.mem_map(POPUP, 0x4000)
    uc.mem_map(STACK, 0x10000)
    return uc


def w32(uc, a, v):
    uc.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))


def r32(uc, a):
    return int.from_bytes(uc.mem_read(a, 4), "little", signed=True)


def _setup(uc, sym, g):
    m = popup_scale_floor(19, g) if g > 16 else 19
    stash_l = popup_scale_floor(13, g)
    w32(uc, G_ADDR, g)
    w32(uc, sym["g_title_left"], stash_l)
    w32(uc, sym["g_title_right"], 1000)
    w32(uc, sym["g_band_popup"], 0)                     # band key unarmed (the unkeyed ornate path)
    f = {0xA14: 0, 0x2144: 0, 0x2350: -1, 0xA48: 0x1234, 0x30AC: 60000, 0x30F0: m, 0x30D8: 0, 0x21C8: 0,
         0x30E0: 0, 0x30E8: popup_scale_floor(40, g), 0x30D4: popup_scale_floor(50, g), 0x30E4: 0, 0x21CC: -1,
         0x30BC: popup_scale_floor(700, g), 0x30F4: popup_scale_floor(21, g), 0x3168: 0}
    for k, v in f.items():
        w32(uc, POPUP + k, v)
    return m, stash_l


def _run_bg(uc, sym, g):
    """Popup_on_draw_background 0x4060E7 -> 0x406238; returns (d528 rect at its draw, ring rect)."""
    devfill = sym["thunk_box_thick_devfill"]
    got = {}

    def hook(u, addr, size, _):
        if addr == devfill:                              # the d528 draw: capture, then RET 8 to the engine
            esp = u.reg_read(UC_X86_REG_ESP)
            rp = r32(u, esp + 4)
            got["d528"] = tuple(r32(u, rp + 4 * i) for i in range(4))
            ret = r32(u, esp) & 0xFFFFFFFF
            u.reg_write(UC_X86_REG_ESP, esp + 12)
            u.reg_write(UC_X86_REG_EIP, ret)
        elif addr == RING_DRAW:
            esp = u.reg_read(UC_X86_REG_ESP)
            rp = r32(u, esp)                             # pushes: eax(&rect) last -> [esp]
            got["ring"] = tuple(r32(u, rp + 4 * i) for i in range(4))
            u.emu_stop()
    h = uc.hook_add(UC_HOOK_CODE, hook)
    ebp = STACK + 0x8000
    w32(uc, ebp - 4, 6)                                  # [ebp-4] = popup type (the ornate `sub ecx,9`)
    w32(uc, ebp - 0x1C, popup_scale_floor(700, g))       # [ebp-0x1c] = the title rect right (frame R source)
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_ESP, ebp - 0x200)
    uc.reg_write(UC_X86_REG_ESI, POPUP)
    uc.reg_write(UC_X86_REG_EDI, 0x5150)
    uc.emu_start(0x4060E7, 0, count=20000)
    uc.hook_del(h)
    assert "d528" in got and "ring" in got, got
    return got["d528"], got["ring"]


def _run_text(uc, g, x_engine):
    """BasePop_on_redraw 0x604DAB -> 0x604DF5 -> text thunks -> Buffer_write_strings; returns (X, width)."""
    got = {}

    def hook(u, addr, size, _):
        if addr == BUF_WRITE_STRINGS:
            esp = u.reg_read(UC_X86_REG_ESP)
            got["x"], got["w"] = r32(u, esp + 8), r32(u, esp + 16)
            u.emu_stop()
    h = uc.hook_add(UC_HOOK_CODE, hook)
    ebp_y = 99
    uc.reg_write(UC_X86_REG_ESP, STACK + 0x6000)
    uc.reg_write(UC_X86_REG_ESI, POPUP)
    uc.reg_write(UC_X86_REG_EDI, x_engine)
    uc.reg_write(UC_X86_REG_EBP, ebp_y)
    w32(uc, POPUP + 0xA3C, POPUP + 0x1000)               # [popup+0xa3c] window (only its +0x444 is passed)
    uc.emu_start(0x604DAB, 0, count=5000)
    uc.hook_del(h)
    assert "x" in got
    return got["x"], got["w"]


@pytest.mark.parametrize("g", range(16, 41))
def test_v9_chain_real_bytes_box_ring_and_text(image, g):
    pe, sym = image
    uc = _emu(pe)
    m, stash_l = _setup(uc, sym, g)
    ps3 = popup_pad(3, g)
    d528, ring = _run_bg(uc, sym, g)
    x_engine = m                                         # 30f0 + 30d8 + 21c8 + 30e0
    x, width = _run_text(uc, g, x_engine)
    width_engine = (popup_scale_floor(700, g) - popup_scale_floor(21, g)) - m
    if g == 16:
        assert d528[0] == m - 3 and ring[0] == m - 6 and x == x_engine and width == width_engine
        return
    assert d528[0] == stash_l + ps3, "text box L must sit on the title inner"
    assert ring[0] == stash_l, "body-only ring L must sit on the title outer"
    assert x == d528[0] + ps3, "body text X must keep one ps3 pitch inside the moved box"
    assert width == width_engine, "the draw width (= every line break) must not change"
    assert x - (x_engine) == -(m - 2 * ps3 - stash_l)    # the text moved exactly the box's shift


@pytest.mark.parametrize("g", (22, 25, 40))
def test_v9_chain_real_bytes_other_margin_passes_through(image, g):
    """A popup whose margin is NOT the canonical fl(19g/16) keeps the engine's box AND text X."""
    pe, sym = image
    uc = _emu(pe)
    m, _ = _setup(uc, sym, g)
    w32(uc, POPUP + 0x30F0, m + 5)
    d528, ring = _run_bg(uc, sym, g)
    x, _w = _run_text(uc, g, m + 5)
    assert d528[0] == m + 5 - popup_pad(3, g) and x == m + 5


@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_v9_chain_real_bytes_stale_key_second_popup(image, g):
    """Popup A draws (background + text: its box and text move).  Popup B -- another type 6 popup at the SAME
    address, with its own content offset -- then draws body text WITHOUT a background pass (no frame_align in
    between): the text must land at B's own engine X, not at A's g_d528_left + ps3."""
    pe, sym = image
    uc = _emu(pe)
    m, stash_l = _setup(uc, sym, g)
    d528, _ring = _run_bg(uc, sym, g)
    xa, _ = _run_text(uc, g, m)
    assert xa == d528[0] + popup_pad(3, g) != m                       # A followed its box
    assert r32(uc, sym["g_d528_popup"]) == POPUP
    w32(uc, POPUP + 0x30D8, 9)                                       # B: content_off_x 9 -> engine X m + 9
    xb, _ = _run_text(uc, g, m + 9)
    assert xb == m + 9, "B took the earlier popup's moved X"
