"""Differential (Unicorn): group basewin_facsb -- the BASE FACILITIES overflow
scrollbar (2026-09-21f).

Four cave edits are pinned here against their laws / contracts, all resolved
from patches.yaml with the real symbol table (yaml/spec desync fails here;
on-disk drift fails test_apply_md5):

  * thunk_bw_facsb_attach  -- call-redirect @0x41002C: rewrites the NATIVE
    attach rect in place to scaling_laws.basewin_facsb_rect, then tail-jmps
    ScrollBar_attach_rect; g<=16 leaves the rect untouched; while the bar
    holds the press capture (g_pressed_win_l/r == ecx) it SKIPS the attach
    with the callee's RET 0x10 contract (the vanilla drag-loss fix).
  * thunk_basewin_gwinit v5 -- the facilities bar (0x6E8A7C) is EXEMPT from
    the child arm; every other arm unchanged (window law, generic child,
    ProdPicker exemption, g<=16 chain).
  * thunk_btn_gate v9      -- statics 4+5 became the RANGE [0x6E9528,
    0x6EC1C0] (both BaseWin ScrollBars' arrow pairs); the range ends and
    every other prefix static keep their verdicts.
  * thunk_pref_sbzoom v7   -- the bar's static arms the zoom bracket.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent - asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
from scaling_laws import (basewin_facsb_rect, basewin_window_rect, basewin_child_rect,  # noqa: E402
                          basewin_child_w, basewin_pt)

BASEWIN = 0x6A7628
FACSB = BASEWIN + 0x41454          # 0x6E8A7C
SUPSB = BASEWIN + 0x435A0          # 0x6EABC8
PRODPICKER = 0x6A8044
ATTACH = 0x605840
SB_DRAW = 0x6066F0
PRESSED_L, PRESSED_R = 0x9B7ACC, 0x9B7AD0
SW, SH, STRIP = 0x9B7B1C, 0x9B7B20, 0x7AF59C
SITE_RET = 0x00410031              # the real return address after the call @0x41002C
STACK = 0x00200000


def _load():
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    thunks = {}
    for cave in doc["code_caves"]:
        base = cave["virtual_addr"]
        base = int(base, 16) if isinstance(base, str) else base
        for c in cave.get("contents", []) or []:
            off = c["offset"]
            off = int(off, 16) if isinstance(off, str) else off
            va = base + off
            thunks[c["id"]] = (va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab))
    return symtab, thunks


SYMTAB, THUNKS = _load()
G_VA = SYMTAB["g_popup_scale_num"]
PREF_GWINIT = SYMTAB["thunk_pref_gwinit"]
G_SB_CUR = SYMTAB["g_sb_cur"]
G_NETWIN = SYMTAB["g_netwin_active"]
CAVE_LO, CAVE_HI = 0xA0C000, 0xA1E000
W5A_PAGE = 0xA48000                         # pcave2 + 0x3C000: the W5A helper region (mapped on its own)
W5A_HELPERS = ("t_bw_railsum", "t_bw_rimcore", "t_bw_rimx")   # 2026-10-25 W5A, pcave2 0x3C000..
W8B_PAGE = 0xA4B000                         # pcave2 + 0x3F000: W8B's t_bw_rowfix / g_bw_rows_tbl / g_bw_kid (gwinit v8)
W8B_PARTS = ("g_bw_rows_tbl", "g_bw_rspv_tbl", "t_bw_rowfix")   # W8R: + the RESOURCE / SUPPORT / PSYCH top table


def _canvas(uc, g, art=529):
    """The BaseWin canvas width / height fields t_bw_railsum reads live ([+0x80] = W, [+0x84] = -H) at the slice-1
    window law, and the rail art height railscale's arm-B gate compares against."""
    uc.mem_write(BASEWIN + 0x444 + 0x80, struct.pack("<2i", (758 * g) >> 4 if g > 16 else 758,
                                                     -((490 * g) >> 4 if g > 16 else 490)))
    uc.mem_write(0x7CFFE0, struct.pack("<i", art))


def _uc(thunk_id):
    va, code = THUNKS[thunk_id]
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE_LO, CAVE_HI - CAVE_LO)      # pcave2: thunks + cells (zeroed)
    uc.mem_map(W5A_PAGE, 0x1000)
    uc.mem_map(W8B_PAGE, 0x1000)
    uc.mem_map(0x600000, 0x10000)               # engine ScrollBar_* (hlt sentinels)
    uc.mem_map(0x660000, 0x10000)               # g_popup_scale_num page
    uc.mem_map(0x6A0000, 0x50000)               # BaseWin_g + its two ScrollBars
    uc.mem_map(0x7A0000, 0x30000)               # MainWin / strip globals, editor-range objects
    uc.mem_map(0x9B7000, 0x1000)                # pressed-window globals, SW/SH
    uc.mem_map(0x410000, 0x1000)                # site return
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(va, code)
    for tid in W5A_HELPERS:                     # the rim / rail-axis CALL helpers
        uc.mem_write(*THUNKS[tid])
    uc.mem_write(*THUNKS["g_bw_tabrow_tbl"])     # W7H v2: the tab row's (t, T) table gwinit v7 reads
    for tid in W8B_PARTS:                       # W8B: gwinit v8 CALLs t_bw_rowfix (the rows' table)
        uc.mem_write(*THUNKS[tid])
    uc.mem_write(ATTACH, b"\xF4")
    uc.mem_write(SB_DRAW, b"\xF4")
    uc.mem_write(PREF_GWINIT, b"\xF4")
    uc.mem_write(SITE_RET, b"\xF4")
    assert G_VA >> 12 == 0x668740 >> 12 or 0x660000 <= G_VA < 0x670000
    return uc, va


def _run(uc, va, count=200):
    try:
        uc.emu_start(va, 0, count=count)
    except unicorn.UcError:
        pass
    return uc.reg_read(UC_X86_REG_EIP)


def _at(eip, target):
    return eip in (target, target + 1)       # hlt sentinel advances EIP by one


# ---------------------------------------------------------------- facsb_attach
RECTS = [(572, 42, 730, 470), (572, 42, 730, 300), (100, 20, 112, 40)]


def _attach(g, rect, pressed_l=0, pressed_r=0):
    uc, va = _uc("thunk_bw_facsb_attach")
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(PRESSED_L, struct.pack("<I", pressed_l))
    uc.mem_write(PRESSED_R, struct.pack("<I", pressed_r))
    rect_va = STACK + 0x100
    uc.mem_write(rect_va, struct.pack("<4i", *rect))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<5I", SITE_RET, rect_va, BASEWIN, 1, 0))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, FACSB)
    uc.reg_write(UC_X86_REG_ESI, FACSB)
    uc.reg_write(UC_X86_REG_EAX, 0xDEAD)
    eip = _run(uc, va)
    got = struct.unpack("<4i", uc.mem_read(rect_va, 16))
    return uc, esp, eip, got


@pytest.mark.parametrize("g", (17, 22, 25, 40, 45))
@pytest.mark.parametrize("rect", RECTS)
def test_attach_scales_rect_to_law_and_tail_jumps(g, rect):
    uc, esp, eip, got = _attach(g, rect)
    assert _at(eip, ATTACH)                                  # tail-jmp, no call
    assert uc.reg_read(UC_X86_REG_ESP) == esp                # site ret + 4 args intact
    assert uc.reg_read(UC_X86_REG_ECX) == FACSB              # this preserved
    assert got == basewin_facsb_rect(*rect, g)
    assert struct.unpack("<5I", uc.mem_read(esp, 20)) == (SITE_RET, STACK + 0x100, BASEWIN, 1, 0)


@pytest.mark.parametrize("g", (16, 10))
def test_attach_native_leaves_rect_untouched(g):
    rect = RECTS[0]
    uc, esp, eip, got = _attach(g, rect)
    assert _at(eip, ATTACH)
    assert got == rect
    assert uc.reg_read(UC_X86_REG_ESP) == esp


@pytest.mark.parametrize("which", ("l", "r"))
def test_attach_skipped_while_bar_holds_press(which):
    """VANILLA drag-loss fix: press capture on the bar -> skip with the
    callee's exact contract (RET 0x10 pops the 4 args, eax=0, rect untouched)."""
    rect = RECTS[0]
    uc, esp, eip, got = _attach(25, rect, pressed_l=FACSB if which == "l" else 0,
                                pressed_r=FACSB if which == "r" else 0)
    assert _at(eip, SITE_RET)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 0x14
    assert uc.reg_read(UC_X86_REG_EAX) == 0
    assert uc.reg_read(UC_X86_REG_ECX) == FACSB
    assert got == rect                                        # nothing rewritten


def test_attach_other_pressed_window_still_attaches():
    """A press held by ANOTHER window (an arrow FlatButton, the supported bar)
    must not skip: only the bar's own capture is the drag being protected."""
    rect = RECTS[0]
    for other in (FACSB + 0xAAC, SUPSB, 0x12345678):
        uc, esp, eip, got = _attach(25, rect, pressed_l=other)
        assert _at(eip, ATTACH)
        assert got == basewin_facsb_rect(*rect, 25)


# ---------------------------------------------------------------- gwinit v5
def _gwinit(g, ecx, parent, x, y, w, h):
    uc, va = _uc("thunk_basewin_gwinit")
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(SW, struct.pack("<i", 1600))
    uc.mem_write(SH, struct.pack("<i", 1200))
    uc.mem_write(STRIP, struct.pack("<i", 200))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I4i3I", 0xCAFE0000, x, y, w, h, 0, 0, parent))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, ecx)
    eip = _run(uc, va)
    args = struct.unpack("<4i", uc.mem_read(esp + 4, 16))
    return uc, esp, eip, args


def test_gwinit_exempts_facilities_bar():
    uc, esp, eip, args = _gwinit(25, FACSB, BASEWIN, 718, 42, 12, 428)
    assert _at(eip, PREF_GWINIT)
    assert args == (718, 42, 12, 428)                        # untouched: the site already scaled it
    assert uc.reg_read(UC_X86_REG_ESP) == esp


def test_gwinit_other_arms_unchanged():
    # generic child (a FlatButton) still x g/16
    uc, esp, eip, args = _gwinit(25, BASEWIN + 0xD7C0, BASEWIN, 100, 200, 50, 20)
    assert _at(eip, PREF_GWINIT)
    assert args == tuple((v * 25) >> 4 for v in (100, 200, 50, 20))
    # ProdPicker exemption (v4) still holds
    uc, esp, eip, args = _gwinit(25, PRODPICKER, BASEWIN, 0, 0, 1184, -766)
    assert args == (0, 0, 1184, -766)
    # the supported bar is NOT a BaseWin child (parent = MainWin) -> untouched
    uc, esp, eip, args = _gwinit(25, SUPSB, 0x7AE820, 1500, 900, 18, 200)
    assert args == (1500, 900, 18, 200)
    # BaseWin's own window law
    uc, esp, eip, args = _gwinit(25, BASEWIN, 0, 149, 65, 758, 490)
    assert args == basewin_window_rect(1600, 1200, 200, 25)
    # g<=16 -> straight chain, nothing touched (even for the exempt bar)
    for ecx in (FACSB, BASEWIN + 0xD7C0):
        uc, esp, eip, args = _gwinit(16, ecx, BASEWIN, 718, 42, 12, 428)
        assert _at(eip, PREF_GWINIT) and args == (718, 42, 12, 428)


# ---------------------------------------------------------------- btn_gate v9
def _gate(esi, rail_sb=0):
    uc, va = _uc("thunk_btn_gate")
    sva, scode = THUNKS["thunk_rail_sbarrows"]            # v10: the NO exit push/rets here
    uc.mem_write(sva, scode)
    uc.mem_write(SYMTAB["g_rail_sb"], struct.pack("<I", rail_sb))
    uc.mem_map(0x730000, 0x10000)               # diplo statics' objects
    uc.mem_map(0x8C6000, 0x1000)                # TutWin parent sentinel page
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I", SITE_RET))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.reg_write(UC_X86_REG_EAX, 0xDEAD)
    eip = _run(uc, va)
    assert _at(eip, SITE_RET), hex(eip)
    return uc.reg_read(UC_X86_REG_EAX)


@pytest.mark.parametrize("esi", [
    FACSB + 0xAAC, FACSB + 0x15F8,      # facilities bar arrows (NEW)
    SUPSB + 0xAAC, SUPSB + 0x15F8,      # supported bar arrows (kept)
    0x7B5080, 0x7B5BCC, 0x7B6718,       # MainWin unit-row arrows (v6 statics 1-3)
    0x6AFC10, 0x6B075C,                 # picker arrows (v6 statics 6-7)
    0x735AE8, 0x736634, 0x737180,       # diplo statics (v8)
    0x7B7264, 0x7CD097,                 # editor range (v7)
])
def test_gate_admits(esi):
    assert _gate(esi) == 1


@pytest.mark.parametrize("esi", [
    FACSB + 0xAAC - 1,                  # one below the new range start
    SUPSB + 0x15F8 + 1,                 # one past the range end
    FACSB,                              # the facilities bar object sits below the span
    BASEWIN + 0xD7C0,                   # a plain BaseWin FlatButton, no flags armed
    0x7B7263, 0x7CD098,                 # editor range ends (exclusive hi)
])
def test_gate_declines_neutral(esi):
    assert _gate(esi) == 0


def test_gate_span_covers_only_scrollbar_interiors():
    """The span [0x6E9528, 0x6EC1C0] lies inside BaseWin's two ScrollBar
    sub-objects (0x6E8A7C..0x6ECBC8). Besides the four arrows it contains the
    supported bar's OWN object address 0x6EABC8 -- admitted by the range, and
    harmless: btn_gate is only ever consulted with esi = a FlatButton `this`
    (thunk_btn_shrink), and a ScrollBar draws through thunk_pref_sbzoom (ecx).
    Pin that fact so a future ScrollBar-through-btn_gate path is noticed."""
    assert FACSB <= 0x6E9528 and 0x6EC1C0 < FACSB + 2 * 0x214C
    assert _gate(SUPSB) == 1


def test_gate_range_is_exactly_the_two_bars_arrow_span():
    """The range must start at the facilities bar's first arrow and end at the
    supported bar's last arrow -- nothing wider (a BaseWin FlatButton would be
    force-zoomed) and nothing narrower (an arrow would draw native on hover)."""
    lo, hi = FACSB + 0xAAC, SUPSB + 0x15F8
    assert (lo, hi) == (0x6E9528, 0x6EC1C0)
    assert _gate(lo) == 1 and _gate(hi) == 1
    assert _gate(lo - 1) == 0 and _gate(hi + 1) == 0


# ---------------------------------------------------------------- sbzoom v7
def _sbzoom(ecx, netwin0=0):
    uc, va = _uc("thunk_pref_sbzoom")
    uc.mem_map(0x850000, 0x30000)               # PrefWin sliders
    uc.mem_write(G_NETWIN, struct.pack("<I", netwin0))
    esp = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, ecx)
    eip = _run(uc, va)
    assert _at(eip, SB_DRAW), hex(eip)
    armed = struct.unpack("<I", uc.mem_read(G_NETWIN, 4))[0]
    cur = struct.unpack("<I", uc.mem_read(G_SB_CUR, 4))[0]
    return uc.reg_read(UC_X86_REG_ESP) - esp, armed, cur


def test_sbzoom_arms_facilities_bar():
    dsp, armed, cur = _sbzoom(FACSB)
    assert (dsp, armed, cur) == (-4, 1, FACSB)              # CALL SB_DRAW inside the bracket


@pytest.mark.parametrize("netwin0", (1, 2))
def test_sbzoom_v11_counts_into_an_open_bracket(netwin0):
    """fix 7: the arm is `inc` -- a bar drawn inside another holder's bracket (Datalinks / the tech-breakthrough
    modal hold 1) reaches ScrollBar_draw with the count one higher, so sb_restripe's clamped dec restores the
    holder's value instead of zeroing it.  A plain (unadmitted) bar leaves the count alone."""
    assert _sbzoom(FACSB, netwin0) == (-4, netwin0 + 1, FACSB)
    assert _sbzoom(0x12345678, netwin0) == (0, netwin0, 0)


# ---------------------------------------------------------------- sbzoom v8 (2026-09-26): the two HQ-report console list bars
_RW_MODAL, _RW_SBS, _RW_PARENTS = 0x9B7AE0, 0xA33564, 0xA3356C


def _sbzoom_rw(bar, slot, modal=0x876478, parent_ok=True):
    uc, va = _uc("thunk_pref_sbzoom")
    uc.mem_map(0x850000, 0x30000)
    uc.mem_map(0xA33000, 0x1000)                # the rw cells g_rw_sbs / g_rw_sbparents (above CAVE_HI)
    uc.mem_write(_RW_MODAL, struct.pack("<I", modal))
    par = 0x890250 if slot == 0 else 0x890DA4
    uc.mem_write(_RW_SBS + 4 * slot, struct.pack("<I", bar))
    uc.mem_write(_RW_PARENTS + 4 * slot, struct.pack("<I", par))
    uc.mem_write(bar + 0xC4, struct.pack("<I", par if parent_ok else 0x12345))
    esp = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, bar)
    eip = _run(uc, va)
    assert _at(eip, SB_DRAW), hex(eip)
    armed = struct.unpack("<I", uc.mem_read(G_NETWIN, 4))[0]
    cur = struct.unpack("<I", uc.mem_read(G_SB_CUR, 4))[0]
    return uc.reg_read(UC_X86_REG_ESP) - esp, armed, cur


@pytest.mark.parametrize("slot", (0, 1))
def test_sbzoom_v8_arms_both_console_bars(slot):
    bar = 0x860000 + 0x3000 * slot
    assert _sbzoom_rw(bar, slot) == (-4, 1, bar)                              # armed: CALL inside the bracket
    assert _sbzoom_rw(bar, slot, modal=0) == (0, 0, 0)                        # report not modal -> plain tail
    assert _sbzoom_rw(bar, slot, parent_ok=False) == (0, 0, 0)                # stale pointer (parent mismatch) -> plain tail


def test_sbzoom_other_bars_unchanged():
    assert _sbzoom(SUPSB) == (-4, 1, SUPSB)
    assert _sbzoom(0x6AF164) == (-4, 1, 0x6AF164)           # picker bar
    assert _sbzoom(0x862064) == (-4, 1, 0x862064)           # a PrefWin slider
    assert _sbzoom(0x12345678) == (0, 0, 0)                 # plain jmp, no bracket


# ---------------------------------------------------------------- sbzoom v9 (2026-09-27): the negotiation window's chat bar
_DW_CHAT_SB = 0x745A80                          # DiploWin 0x73ACD8 + 0xA388 (chat TextScroll) + 0xA20 (its ScrollBar)


def test_sbzoom_v9_arms_the_diplowin_chat_bar():
    assert _sbzoom(_DW_CHAT_SB) == (-4, 1, _DW_CHAT_SB)     # static object: armed, CALL inside the bracket
    assert _sbzoom(_DW_CHAT_SB + 4) == (0, 0, 0)            # a neighbour: plain tail
    assert _sbzoom(FACSB) == (-4, 1, FACSB)                 # the v7 member still armed after the insert


# ---------------------------------------------------------------- btn_gate v10
def test_gate_no_exit_admits_the_rail_fitted_bars_arrows():
    """v10 (2026-09-26p): the NO exit asks thunk_rail_sbarrows -> the two arrows of
    [g_rail_sb] (the in-game LOAD/SAVE bar FileDlg+0x3DD8, a stack address) are
    admitted on hover repaints; the bar object itself, its neighbours and every
    esi while the stash is 0 stay NO."""
    sb = STACK + 0x100                                   # a stack-like bar address (mapped: btn_gate reads [esi+0xC4])
    assert _gate(sb + 0xAAC, rail_sb=sb) == 1
    assert _gate(sb + 0x15F8, rail_sb=sb) == 1
    for esi in (sb, sb + 0xAAC - 1, sb + 0x15F8 + 1, BASEWIN + 0xD7C0):
        assert _gate(esi, rail_sb=sb) == 0
    assert _gate(sb + 0xAAC, rail_sb=0) == 0



# ---------------------------------------------------------------- W5A: the base-screen mirror law (2026-10-25)
@pytest.mark.parametrize("g", range(16, 41))
def test_attach_real_rect_rim_mirrors_through_the_rails(g):
    """The real attach rect (681, 60, 693, 251): its right edge 693 is the list's inner rim, placed through the rail
    axis (basewin_rim_x via t_bw_rimx -> t_bw_rimcore -> t_bw_railsum over the live canvas fields)."""
    uc, va = _uc("thunk_bw_facsb_attach")
    _canvas(uc, g)
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(PRESSED_L, struct.pack("<2I", 0, 0))
    rect_va = STACK + 0x100
    uc.mem_write(rect_va, struct.pack("<4i", 681, 60, 693, 251))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<5I", SITE_RET, rect_va, BASEWIN, 1, 0))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, FACSB)
    eip = _run(uc, va, count=400)
    assert _at(eip, ATTACH) and uc.reg_read(UC_X86_REG_ESP) == esp and uc.reg_read(UC_X86_REG_ECX) == FACSB
    assert struct.unpack("<4i", uc.mem_read(rect_va, 16)) == basewin_facsb_rect(681, 60, 693, 251, g)


#: every BaseWin child BaseWin_init builds (native x, y, w, h; the census of GraphicWin_init on the pristine image) --
#: the tab row (y 7), the RESOURCE / SUPPORT / PSYCH row (y 234), the RENAME / OK row (y 449, centred on 375: NOT a
#: twin row), the facilities BaseButton (a rim child)
CHILDREN = ((0x6B7B18, (30, 7, 112, 20)), (0x6B8664, (144, 7, 112, 20)), (0x6C1940, (258, 7, 20, 20)),
            (0x6BA848, (280, 7, 166, 20)), (0x6C248C, (448, 7, 20, 20)), (0x6B91B0, (470, 7, 112, 20)),
            (0x6B9CFC, (584, 7, 112, 20)), (0x6BBEE0, (169, 234, 128, 20)), (0x6BB394, (299, 234, 128, 20)),
            (0x6BCA2C, (429, 234, 128, 20)), (0x6B5934, (131, 449, 238, 20)), (0x6B4DE8, (381, 449, 238, 20)),
            (0x6C3B24, (569, 231, 124, 20)))


@pytest.mark.parametrize("g", range(17, 41))
def test_gwinit_v6_children_on_the_mirror(g):
    """thunk_basewin_gwinit v6 == scaling_laws.basewin_child_rect for every BaseWin child: on the twin rows (the tab
    row, the RESOURCE / SUPPORT / PSYCH row) a right-half child mirrors its twin through S = pt(726) and the
    self-mirrored one (GOVERNOR, SUPPORT) is centred (w = S - 2 pt(x)); RENAME on the edge law, OK its mirror through pt(128) + pt(622) (W7H v7); the facilities
    BaseButton (569 + 124 = 693, a rim) ends on basewin_rim_x.  The twin rows' gaps are palindromic."""
    rows = {}
    for ecx, (x, y, w, h) in CHILDREN:
        uc, va = _uc("thunk_basewin_gwinit")
        _canvas(uc, g)
        uc.mem_write(G_VA, struct.pack("<i", g))
        esp = STACK + 0x8000
        uc.mem_write(esp, struct.pack("<I4i3I", 0xCAFE0000, x, y, w, h, 0, 0, BASEWIN))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_ECX, ecx)
        eip = _run(uc, va, count=600)
        args = struct.unpack("<4i", uc.mem_read(esp + 4, 16))
        assert _at(eip, PREF_GWINIT) and uc.reg_read(UC_X86_REG_ESP) == esp and uc.reg_read(UC_X86_REG_ECX) == ecx
        assert args == basewin_child_rect(x, y, w, h, g), (hex(ecx), g, args)
        rows.setdefault(y, []).append(args)
    for y in (7, 234):
        r = sorted(rows[y])
        gaps = [r[i + 1][0] - (r[i][0] + r[i][2]) for i in range(len(r) - 1)]
        assert gaps == gaps[::-1], (g, y, gaps)
        assert r[0][0] + r[-1][0] + r[-1][2] == (726 * g) >> 4, (g, y)       # the outer pair mirrors through S


def test_gwinit_v6_native_and_unrelated_children_unchanged():
    """g <= 16 chains untouched; a child whose x + w is NOT a rim and y != 7 is the generic x g/16 (v5's arm)."""
    for g in (16,):
        uc, va = _uc("thunk_basewin_gwinit")
        _canvas(uc, g)
        uc.mem_write(G_VA, struct.pack("<i", g))
        esp = STACK + 0x8000
        uc.mem_write(esp, struct.pack("<I4i3I", 0xCAFE0000, 569, 231, 124, 20, 0, 0, BASEWIN))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_ECX, 0x6C3B24)
        assert _at(_run(uc, va), PREF_GWINIT)
        assert struct.unpack("<4i", uc.mem_read(esp + 4, 16)) == (569, 231, 124, 20)
    for x, w in ((566, 123), (566, 134), (131, 238)):          # right edges 689 / 700 / 369: not rims
        uc, esp, eip, args = _gwinit(25, BASEWIN + 0xD7C0, BASEWIN, x, 231, w, 20)
        assert args == tuple((v * 25) >> 4 for v in (x, 231, w, 20)) == basewin_child_rect(x, 231, w, 20, 25)
