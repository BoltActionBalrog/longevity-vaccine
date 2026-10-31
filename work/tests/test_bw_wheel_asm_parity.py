"""Differential (Unicorn): t_bw_wheel_down / t_bw_wheel_up -- mouse wheel over the
base screen's two scrollable lists (2026-09-21g, group wheel_scroll head).

Contract at the WinProc sites (they replace `call Win_get_active_target`;
[esp+0x68] = wParam, [esp+0x6C] = lParam at entry):

  * base screen not up (BaseWin_g Win+0x9C bit0 clear -- it is NOT modal,
    g_modal_top stays 0 while it is open), or a modal / basepop on top ->
    chain to t_ntw_wheel_down/up with the stack untouched (push+ret);
  * no key target / a real key (lParam != 0) / not an arrow -> return the
    target untouched (eax = Win_get_active_target's result);
  * synthetic arrow over the BASE FACILITIES panel (rcFacilities NATIVE
    fields x g/16, BaseWin-local) with its bar engaged -> ScrollBar_on_chevron
    (bar 0x6E8A7C, 1 up / 2 down), eax = 0 (eaten), g_bw_wheel_ate = 1;
  * else over the FORCES SUPPORTED strip panel (+0x40B7C, MainWin-local
    DEVICE rect) with its bar engaged -> the same on bar 0x6EABC8;
  * else (off both lists, or the list's bar closed / range empty) -> the
    target untouched, nothing scrolled;
  * the KEYUP twin swallows exactly the key-up whose key-down was eaten.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent - asm parity unverified")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
from scaling_laws import basewin_left_x, basewin_pt, basewin_rim_x  # noqa: E402
import wheel_stc_stub  # noqa: E402

BASEWIN = 0x6A7628
FACSB, SUPSB = BASEWIN + 0x41454, BASEWIN + 0x435A0
MAINWIN = 0x7AE820
MODAL_TOP, BASEPOP = 0x9B7AE0, 0x9B8D7C
GET_TARGET, CHEVRON = 0x5F6A50, 0x606B20
IAT_GCP, IAT_S2C, G_HWND = 0x669284, 0x6692D4, 0x9B7B28
SITE_RET = 0x005F07B5
STACK = 0x00200000
TARGET = 0x1234
BW_ORG = (1012, 403)          # BaseWin window origin (4K-ish; any value works)
MW_ORG = (0, 1520)            # MainWin (console strip) origin
RC_FAC = (569, 39, 733, 473)  # rcFacilities NATIVE design rect (representative)
RC_SUP = (1380, 30, 1660, 300)  # supported strip panel, MainWin-local DEVICE rect


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
ATE = SYMTAB["g_bw_wheel_ate"]
NTW_DOWN, NTW_UP = SYMTAB["t_ntw_wheel_down"], SYMTAB["t_ntw_wheel_up"]


def _mk(g, modal_top, basepop, cursor, fac_engaged=True, sup_engaged=True, ate=0, shown=True, rc_fac=None):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0xA0C000, 0x40000)               # pcave2 (both heads + the ntw heads' slots)
    uc.mem_map(0x5F0000, 0x20000)               # WinProc site ret, Win_get_active_target, ScrollBar_on_chevron
    uc.mem_map(0x660000, 0x10000)               # IAT slots + g_popup_scale_num
    uc.mem_map(0x6A0000, 0x50000)               # BaseWin_g + its ScrollBars
    uc.mem_map(0x7A0000, 0x10000)               # MainWin_g
    uc.mem_map(0x7CF000, 0x1000)                # the rail art height t_bw_railsum reads (W5A)
    uc.mem_map(0x9B7000, 0x2000)                # modal/basepop/hwnd globals
    uc.mem_map(STACK, 0x10000)
    for tid in ("t_bw_wheel_down", "t_bw_wheel_up", "t_bw_railsum", "t_bw_rimcore", "t_bw_rimx", "t_bw_lmir"):
        va, code = THUNKS[tid]
        uc.mem_write(va, code)
    uc.mem_write(NTW_DOWN, b"\xF4")
    uc.mem_write(NTW_UP, b"\xF4")
    uc.mem_write(SITE_RET, b"\xF4")
    uc.mem_write(GET_TARGET, b"\xB8" + struct.pack("<I", TARGET) + b"\xC3")   # mov eax,TARGET; ret
    uc.mem_write(CHEVRON, b"\xC2\x04\x00")                                     # ret 4
    # GetCursorPos(p): p->x = cx; p->y = cy; ret 4     ScreenToClient(hwnd, p): ret 8 (identity)
    gcp, s2c = 0x5F8000, 0x5F8040
    uc.mem_write(IAT_GCP, struct.pack("<I", gcp))
    uc.mem_write(IAT_S2C, struct.pack("<I", s2c))
    uc.mem_write(gcp, bytes.fromhex("8B442404C700") + struct.pack("<i", cursor[0])
                 + bytes.fromhex("C74004") + struct.pack("<i", cursor[1]) + bytes.fromhex("C20400"))
    uc.mem_write(s2c, bytes.fromhex("C20800"))
    wheel_stc_stub.install(uc)        # the head calls t_wheel_stc (cell 0 = no uimod.dll -> the IAT stub above)
    uc.mem_write(G_HWND, struct.pack("<I", 0xBEEF))
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(MODAL_TOP, struct.pack("<I", modal_top))
    uc.mem_write(BASEPOP, struct.pack("<I", basepop))
    uc.mem_write(ATE, struct.pack("<I", ate))
    uc.mem_write(BASEWIN + 0x13C, struct.pack("<2i", *BW_ORG))
    uc.mem_write(BASEWIN + 0x9C, b"\x05" if shown else b"\x04")   # Win_is_visible bit0 (bit2 set as measured live)
    uc.mem_write(MAINWIN + 0x13C, struct.pack("<2i", *MW_ORG))
    uc.mem_write(BASEWIN + 0x40BAC, struct.pack("<4i", *(rc_fac or RC_FAC)))
    uc.mem_write(BASEWIN + 0x444 + 0x80, struct.pack("<2i", (758 * g) >> 4, -((490 * g) >> 4)))   # canvas W / -H
    uc.mem_write(0x7CFFE0, struct.pack("<i", 529))                                             # rail art h
    uc.mem_write(BASEWIN + 0x40B7C, struct.pack("<4i", *RC_SUP))
    for bar, eng in ((FACSB, fac_engaged), (SUPSB, sup_engaged)):
        uc.mem_write(bar + 0xC4, struct.pack("<I", 1 if eng != "closed" else 0))
        uc.mem_write(bar + 0xA20, struct.pack("<2i", 0, 7 if eng is True else 0))
    calls = []

    def hook(u, addr, size, _):
        if addr == CHEVRON:
            sp = u.reg_read(UC_X86_REG_ESP)
            calls.append((u.reg_read(UC_X86_REG_ECX), struct.unpack("<I", bytes(u.mem_read(sp + 4, 4)))[0]))

    uc.hook_add(UC_HOOK_CODE, hook)
    return uc, calls


def _run(uc, tid, key, lparam):
    va, _ = THUNKS[tid]
    esp = STACK + 0x8000
    frame = bytearray(0x80)
    frame[0:4] = struct.pack("<I", SITE_RET)
    frame[0x68:0x6C] = struct.pack("<I", key)
    frame[0x6C:0x70] = struct.pack("<I", lparam)
    uc.mem_write(esp, bytes(frame))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EAX, 0x77)
    try:
        uc.emu_start(va, 0, count=400)
    except unicorn.UcError:
        pass
    eip = uc.reg_read(UC_X86_REG_EIP)
    return eip, uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_ESP) - esp


def _at(eip, t):
    return eip in (t, t + 1)


def _ate(uc):
    return struct.unpack("<I", uc.mem_read(ATE, 4))[0]


def fac_mid(g):
    l, t, r, b = (basewin_pt(v, g) for v in RC_FAC)
    return (BW_ORG[0] + (l + r) // 2, BW_ORG[1] + (t + b) // 2)


def sup_mid():
    l, t, r, b = RC_SUP
    return (MW_ORG[0] + (l + r) // 2, MW_ORG[1] + (t + b) // 2)


VK_UP, VK_DOWN = 0x26, 0x28


# ---------------------------------------------------------------- routing
@pytest.mark.parametrize("g", (16, 22, 25, 40))
@pytest.mark.parametrize("key,want_dir", ((VK_UP, 1), (VK_DOWN, 2)))
def test_wheel_scrolls_the_facilities_list_under_the_cursor(g, key, want_dir):
    uc, calls = _mk(g, 0, 0, fac_mid(g))
    eip, eax, dsp = _run(uc, "t_bw_wheel_down", key, 0)
    assert _at(eip, SITE_RET) and dsp == 4          # returned to the site
    assert eax == 0                                  # eaten: no key target
    assert calls == [(FACSB, want_dir)]
    assert _ate(uc) == 1
    # the KEYUP twin swallows the matching key-up and clears the flag
    eip, eax, dsp = _run(uc, "t_bw_wheel_up", key, 0)
    assert _at(eip, SITE_RET) and dsp == 4 and eax == 0
    assert _ate(uc) == 0


@pytest.mark.parametrize("g", (16, 25, 40))
def test_wheel_scrolls_the_supported_list_under_the_cursor(g):
    uc, calls = _mk(g, 0, 0, sup_mid())
    eip, eax, dsp = _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
    assert _at(eip, SITE_RET) and eax == 0 and calls == [(SUPSB, 2)]
    assert _ate(uc) == 1


@pytest.mark.parametrize("g", (16, 25, 40))
def test_facilities_edges_follow_the_boxsprite_scaling(g):
    """The panel test uses thunk_bw_boxsprite's half-open draw extent per edge
    ((v*g)>>4; v4: a right-column left edge >= 563 through basewin_left_x, a rim
    right edge through basewin_rim_x): the last device pixel inside scrolls, the
    first outside does not."""
    l, t, r, b = (basewin_left_x(RC_FAC[0], g), basewin_pt(RC_FAC[1], g), basewin_rim_x(RC_FAC[2], g),
                  basewin_pt(RC_FAC[3], g))
    inside = [(BW_ORG[0] + l, BW_ORG[1] + t), (BW_ORG[0] + r - 1, BW_ORG[1] + b - 1)]
    outside = [(BW_ORG[0] + l - 1, BW_ORG[1] + t), (BW_ORG[0] + r, BW_ORG[1] + t),
               (BW_ORG[0] + l, BW_ORG[1] + t - 1), (BW_ORG[0] + l, BW_ORG[1] + b)]
    for cur in inside:
        uc, calls = _mk(g, 0, 0, cur, sup_engaged=False)
        _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
        assert calls == [(FACSB, 2)], cur
    for cur in outside:
        uc, calls = _mk(g, 0, 0, cur, sup_engaged=False)
        eip, eax, dsp = _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
        assert calls == [] and eax == TARGET and _at(eip, SITE_RET), cur


def test_wheel_off_both_lists_passes_the_target_through():
    uc, calls = _mk(25, 0, 0, (5, 5))
    eip, eax, dsp = _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
    assert _at(eip, SITE_RET) and dsp == 4 and eax == TARGET and calls == []
    assert _ate(uc) == 0
    # ... and its key-up chains (nothing was eaten)
    eip, eax, dsp = _run(uc, "t_bw_wheel_up", VK_DOWN, 0)
    assert _at(eip, NTW_UP) and dsp == 0


@pytest.mark.parametrize("state", ("closed", "empty"))
def test_disengaged_bar_is_not_scrolled(state):
    """A closed bar window ([bar+0xC4] == 0, the fits-list reset) or an empty
    range (max <= min) must not be poked; the facilities test does NOT fall
    through to the supported list either (the cursor is over the facilities)."""
    uc, calls = _mk(25, 0, 0, fac_mid(25), fac_engaged=state)
    eip, eax, dsp = _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
    assert calls == [] and eax == TARGET and _at(eip, SITE_RET) and _ate(uc) == 0
    uc, calls = _mk(25, 0, 0, sup_mid(), sup_engaged=state)
    eip, eax, dsp = _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
    assert calls == [] and eax == TARGET


# ---------------------------------------------------------------- gating
def test_not_our_screen_chains_with_the_stack_intact():
    for modal, pop, shown in ((0x811E40, 0, True), (0, 0x999, True), (0, 0, False), (BASEWIN, 0, True)):
        uc, calls = _mk(25, modal, pop, fac_mid(25), shown=shown)
        eip, eax, dsp = _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
        assert _at(eip, NTW_DOWN) and dsp == 0 and calls == []
        eip, eax, dsp = _run(uc, "t_bw_wheel_up", VK_DOWN, 0)
        assert _at(eip, NTW_UP) and dsp == 0


def test_real_keys_and_non_arrows_return_the_target():
    for key, lparam in ((VK_DOWN, 0x1500001), (VK_UP, 0x1480001), (0x41, 0), (0x0D, 0)):
        uc, calls = _mk(25, 0, 0, fac_mid(25))
        eip, eax, dsp = _run(uc, "t_bw_wheel_down", key, lparam)
        assert _at(eip, SITE_RET) and dsp == 4 and eax == TARGET and calls == []
        uc, calls = _mk(25, 0, 0, fac_mid(25), ate=1)
        eip, eax, dsp = _run(uc, "t_bw_wheel_up", key, lparam)
        assert _at(eip, SITE_RET) and dsp == 4 and eax == TARGET


def test_no_key_target_returns_zero_untouched():
    uc, calls = _mk(25, 0, 0, fac_mid(25))
    uc.mem_write(GET_TARGET, b"\x31\xC0\xC3")       # xor eax,eax; ret
    eip, eax, dsp = _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
    assert _at(eip, SITE_RET) and eax == 0 and calls == [] and _ate(uc) == 0


@pytest.mark.parametrize("mode,origin,space,hits", wheel_stc_stub.MODES)
def test_wheel_pracx_cursor_modes_facilities_corner(mode, origin, space, hits):
    """t_bw_wheel_down through PRACX's hooked GetCursorPos + t_wheel_stc: the facilities list's top-left corner
    is hit in every display setup; the no-DLL control misses it by the window origin."""
    g = 25
    b = (BW_ORG[0] + basewin_pt(RC_FAC[0], g), BW_ORG[1] + basewin_pt(RC_FAC[1], g))
    with wheel_stc_stub.mode(mode, *origin):
        uc, calls = _mk(g, 0, 0, wheel_stc_stub.pracx_cursor(b, origin, space))
    _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
    assert ((FACSB, 2) in calls) == hits



def basewin_draw_extent(rc, g):
    """The half-open extent the panel box is DRAWN on (basewin_box_draw_rect's inclusive footprint + 1)."""
    import scaling_laws as SL
    L, T, R, B = SL.basewin_box_draw_rect(*rc, g)
    return (L, T, R + 1, B + 1) if g > 16 else (L, T, R, B)


@pytest.mark.parametrize("g", (16, 17, 22, 25, 33, 40))
def test_facilities_rim_edge_follows_the_mirrored_panel(g):
    """W5A: the real rcFacilities right edge (699, the right column's rim) is placed through the rail axis exactly as
    the panel box is drawn (basewin_rim_x = its last column + 1): the last device pixel inside scrolls, the next
    does not.  v4: its LEFT edge (563) is the drawn half-open panel's first column too (basewin_left_x, the mirror of
    the left panel's last column); T / B stay (v*g)>>4."""
    rc = (563, 33, 699, 257)
    l, t, b = basewin_left_x(rc[0], g), basewin_pt(rc[1], g), basewin_pt(rc[3], g)
    assert (l, t, basewin_rim_x(rc[2], g), b) == basewin_draw_extent(rc, g)
    r = basewin_rim_x(rc[2], g)
    for cur, hit in (((BW_ORG[0] + r - 1, BW_ORG[1] + t), True), ((BW_ORG[0] + r, BW_ORG[1] + t), False),
                     ((BW_ORG[0] + l, BW_ORG[1] + b - 1), True), ((BW_ORG[0] + l - 1, BW_ORG[1] + t), False)):
        uc, calls = _mk(g, 0, 0, cur, sup_engaged=False, rc_fac=rc)
        _run(uc, "t_bw_wheel_down", VK_DOWN, 0)
        assert (calls == [(FACSB, 2)]) == hit, (g, cur)
