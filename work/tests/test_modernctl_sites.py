"""uimod's Modern Control Set (src/uimod/src/modernctl.cpp, praxdrag.cpp) against the pristine binaries.

modernctl: two 5-byte detours inside MapWin_click (the right-click menu gate 0x46E529 and the left/right
split 0x46E36D), five Console-vtable slot wrappers, the Shift-branch neutralisation at 0x46EF9B, and a port
of go_timer's view-mode unit rule.  praxdrag: six immediates in prax.dll that key PRACX's drag scroll on the
right button.  The addresses and bytes in the sources must be the ones the pristine binaries carry, and the
prax sites must stay clear of patches_prax.yaml's own.
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pefile  # noqa: E402
import yaml  # noqa: E402

import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
CTL = (SRC_DIR / "modernctl.cpp").read_text(encoding="utf-8")
PRAX = (SRC_DIR / "praxdrag.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")
WHEEL = (SRC_DIR / "wheel.cpp").read_text(encoding="utf-8")
PREFS = (SRC_DIR / "prefs.cpp").read_text(encoding="utf-8")

CONSOLE, CONSOLE_VTBL, GW_OFS = 0x9156B0, 0x66EC18, 0x23D94
GATE, GATE_RESUME, INLINE_GOTO = 0x46E529, 0x46E52E, 0x46DF0E
SPLIT, SPLIT_RIGHT, SPLIT_LEFT, SPLIT_MENU = 0x46E36D, 0x46E378, 0x46E5E6, 0x46E544
RIGHT_MENU, SHIFT_SITE, PUSH3 = 0x46C0D0, 0x46EF8A, 0x46EF9B
SLOTS = {0x44: 0x51DE70, 0x48: 0x404260, 0x4C: 0x51DE80, 0x50: 0x51DE90, 0x58: 0x51DEB0, 0x5C: 0x51DEC0}
HANDLERS = {0x51DE70: 0x46F000, 0x51DE80: 0x46EBA0, 0x51DE90: 0x46ED30, 0x51DEB0: 0x46EBE0, 0x51DEC0: 0x46EC10}
VEH_FIND, VEH_SELECTABLE, TIME_STOP, WIN_SHOW, WIN_HIDE, GWIN_CLEAR, CON_SELECTED = (
    0x5C0CB0, 0x5C1A20, 0x616780, 0x5ED9D0, 0x5EDCD0, 0x5D5250, 0x5107E0)

PRAX_SITES = {   # module-relative offset -> clean bytes
    0x08D1E: "81 7D 0C 04 02 00 00 75 1F",
    0x08D46: "81 7D 0C 05 02 00 00 75 72",
    0x08D90: "68 04 02 00 00",
    0x08DAC: "68 05 02 00 00",
    0x05161: "6A 02 FF 15 E8 41 03 10",
    0x05595: "6A 02 FF 15 E8 41 03 10",
}
PRAX_BASE = 0x10000000


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def u32(pe, va):
    return struct.unpack("<I", rd(pe, va, 4))[0]


def call_target(pe, va):
    b = rd(pe, va, 5)
    assert b[0] == 0xE8, f"no call at {va:#x}"
    return va + 5 + struct.unpack("<i", b[1:])[0]


def jmp_target(pe, va):
    b = rd(pe, va, 5)
    assert b[0] == 0xE9, f"no jmp at {va:#x}"
    return va + 5 + struct.unpack("<i", b[1:])[0]


def cpp_bytes(src: str, name: str) -> bytes:
    m = re.search(name + r"\[[^\]]*\]\s*=\s*\{([^}]*)\}", src)
    assert m, name
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


# ---- modernctl.cpp vs the pristine exe --------------------------------------------------------------

def test_sources_carry_the_sites():
    for name, va in (("kVA_Console", CONSOLE), ("kVA_ConsoleVtbl", CONSOLE_VTBL), ("kVA_Gate", GATE),
                     ("kVA_GateResume", GATE_RESUME), ("kVA_InlineGoto", INLINE_GOTO), ("kVA_Split", SPLIT),
                     ("kVA_SplitRight", SPLIT_RIGHT), ("kVA_SplitLeft", SPLIT_LEFT), ("kVA_SplitMenu", SPLIT_MENU),
                     ("kVA_ShiftSite", SHIFT_SITE), ("kVA_VehFind", VEH_FIND), ("kVA_VehSelectable", VEH_SELECTABLE),
                     ("kVA_TimeStop", TIME_STOP), ("kVA_WinShow", WIN_SHOW), ("kVA_WinHide", WIN_HIDE),
                     ("kVA_GWinClear", GWIN_CLEAR), ("kVA_SetCenter", 0x46B1F0), ("kVA_BaseExitCenter", 0x41A600),
                     ("kVA_ConsoleCenter", 0x515400), ("kVA_StatusDrawDest", 0x4B5D95), ("kVA_StatusHide", 0x4B5DC2)):
        assert re.search(name + r"\s*=\s*0x%X\b" % va, CTL), name
    assert "kConGWin       = 0x23D94" in CTL
    assert "InstallPraxDrag(pracx);" in INIT and "InstallModernControls();" in INIT
    assert INIT.index("InstallPraxDrag(pracx);") < INIT.index("InstallModernControls();") < INIT.index("InstallPrefsTab();")
    assert "ModernCtlFilterKey(m);" in WHEEL and "ModernCtlPoll(m);" in WHEEL
    assert "gotokeys" not in INIT and "gotokeys" not in WHEEL and "gotokeys" not in PREFS
    assert "ShiftInstantMove" not in PREFS


def test_gate_site_and_its_targets(pe):
    assert rd(pe, GATE, 27) == cpp_bytes(CTL, "kGateBytes")
    assert rd(pe, GATE, 5) == b"\xA1" + struct.pack("<I", 0x9A6494)          # mov eax,[GameMorePreferences]
    assert rd(pe, GATE_RESUME, 5) == bytes.fromhex("BF01000000")             # mov edi,1
    assert rd(pe, INLINE_GOTO, 9) == cpp_bytes(CTL, "kInlineBytes")
    assert call_target(pe, 0x46DF2F) == 0x531020                             # NetDaemon_lock_veh inside the inline go-to
    assert rd(pe, 0x46DF1D, 3) == bytes.fromhex("8945E8")                    # mov [ebp-0x18], eax : the unit id EAX carries


def test_split_site_and_its_targets(pe):
    assert rd(pe, SPLIT, 11) == cpp_bytes(CTL, "kSplitBytes")
    # jz rel32 at +5 lands on the plain-click path, the right path falls through to the Shift test
    assert SPLIT + 11 + struct.unpack("<i", rd(pe, SPLIT + 7, 4))[0] == SPLIT_LEFT
    assert SPLIT + 11 == SPLIT_RIGHT
    assert rd(pe, SPLIT_RIGHT, 8) == cpp_bytes(CTL, "kSplitRightBytes")
    assert rd(pe, SPLIT_LEFT, 5) == cpp_bytes(CTL, "kSplitLeftBytes")
    assert rd(pe, SPLIT_MENU, 13) == cpp_bytes(CTL, "kSplitMenuBytes")
    assert call_target(pe, 0x46E560) == RIGHT_MENU                           # ... push ebx; push [ebp+8]; push ty; push tx; call MapWin_right_menu
    assert rd(pe, 0x46E551, 15) == bytes.fromhex("8B45088B4DEC8B55F05350515288BCE".replace("88BCE","8BCE"))


def test_shift_branch_site(pe):
    assert rd(pe, SHIFT_SITE, 27) == cpp_bytes(CTL, "kShiftBytes")
    assert rd(pe, PUSH3, 2) == bytes.fromhex("6A03")
    assert call_target(pe, PUSH3 + 2) == 0x50F170                            # go_timer(3)
    assert PUSH3 + 2 + 0x3B == 0x46EFD8 and rd(pe, 0x46EFD8, 3) == bytes.fromhex("5F5E5B")   # pop edi/esi/ebx


def test_console_vtable_slots_and_thunks(pe):
    prologue = cpp_bytes(CTL, "kThunkPrologue")
    for slot, entry in SLOTS.items():
        assert u32(pe, CONSOLE_VTBL + slot) == entry, hex(slot)
        if entry in HANDLERS:
            assert rd(pe, entry, 10) == prologue
            assert jmp_target(pe, entry + 9) == HANDLERS[entry]
    assert rd(pe, 0x404260, 3) == bytes.fromhex("C20800")                    # the mouse-leave stub: ret 8
    # the Console's GraphicWin subobject is the vtable's host: descriptor [+4] names its offset
    assert u32(pe, 0x66EF08) == GW_OFS                                         # Console descriptor 0x66EF04: [+4] = the GraphicWin member offset


def test_go_timer_view_mode_rule_is_the_one_ported(pe):
    assert rd(pe, 0x50F296, 5) == cpp_bytes(CTL, "kGoTimerFind") and call_target(pe, 0x50F296) == VEH_FIND
    assert rd(pe, 0x50F2A9, 5) == cpp_bytes(CTL, "kGoTimerSel") and call_target(pe, 0x50F2A9) == VEH_SELECTABLE
    assert call_target(pe, 0x50F257) == VEH_SELECTABLE
    assert rd(pe, 0x50F273, 3) == bytes.fromhex("F6C442")                    # test ah,0x42 : flags 0x4200 on the selected unit
    assert rd(pe, 0x50F2D6, 3) == bytes.fromhex("F6C402")                    # test ah,2    : flag 0x200 on the found unit
    assert rd(pe, 0x50F2DF, 3) == bytes.fromhex("F6C440")                    # test ah,0x40 : flag 0x4000 required
    assert rd(pe, 0x50F2E8, 6) == bytes.fromhex("8935") + struct.pack("<I", 0x93928C)   # mov [selected_veh], esi
    # the view-mode arm of that rule is no longer ported (2026-10-10): in view mode the DLL selects nothing for
    # movement (PickUnit returns -1 unless MoveMode is set) and viewdragfix.cpp cuts the engine's own arm at
    # 0x50F21C; the anchors above still prove the function is the one the port was written against
    assert "if (Rd<int>(kVA_MoveMode) != 0) return VehOk(cur) ? cur : -1;" in CTL and "(void)allowFind;" in CTL
    assert "VehFind(cx, cy)" not in CTL


def test_set_center_overlay_calls(pe):
    """MapWin_set_center clears the overlay (push 9; mov ecx,overlay; call GraphicWin_clear @0x46B2A5) and redraws
    the route (call draw_my_dest @0x46B2F2); both stand aside while the hover owns the overlay (2026-10-10)."""
    assert rd(pe, 0x46B29E, 12) == cpp_bytes(CTL, "kCenterClearBytes")
    assert call_target(pe, 0x46B2A5) == 0x5D5250                              # GraphicWin_clear
    assert rd(pe, 0x46B2F2, 5) == cpp_bytes(CTL, "kCenterDestBytes") and call_target(pe, 0x46B2F2) == 0x4B4BF0   # draw_my_dest
    assert rd(pe, 0x46B2F7, 3) == bytes.fromhex("83C404")                     # cdecl: the caller pops (the stub may `ret`)
    assert re.search(r"kVA_CenterClear\s*=\s*0x46B2A5\b", CTL) and re.search(r"kVA_CenterDest\s*=\s*0x46B2F2\b", CTL)
    assert "ret  4" in CTL                                                     # the clear stub pops GraphicWin_clear's colour when it skips


def test_status_window_overlay_calls_and_camera_sites(pe):
    # StatusWin refresh: `call draw_my_dest` @0x4B5D95 and `mov ecx,overlay; call Win_hide` @0x4B5DBD/0x4B5DC2
    assert call_target(pe, 0x4B5D95) == 0x4B4BF0
    assert rd(pe, 0x4B5DBD, 5) == b"\xB9" + struct.pack("<I", 0x937118) and call_target(pe, 0x4B5DC2) == WIN_HIDE
    assert rd(pe, 0x4B5D7C, 7) == bytes.fromhex("80BE392895") + bytes.fromhex("0018")   # cmp byte [esi+Vehs.order], 0x18
    # the camera options: MapWin_set_center's prologue, BaseWin_exit's call to Console_center, Console_center itself
    assert rd(pe, 0x46B1F0, 5) == cpp_bytes(CTL, "kSetCenterBytes") and rd(pe, 0x46B300, 3) == bytes.fromhex("C20C00")
    assert rd(pe, 0x41A600, 5) == cpp_bytes(CTL, "kBaseExitCenterBytes") and call_target(pe, 0x41A600) == 0x515400
    assert rd(pe, 0x515400, 7) == cpp_bytes(CTL, "kConsoleCenterBytes")
    assert call_target(pe, 0x51541D) == 0x46B1F0 and rd(pe, 0x515422, 1) == b"\xC3"   # set_center(cursor, 1); ret
    assert rd(pe, 0x5FA7E0, 1) in (b"\x55", b"\x8B", b"\x83")                            # in_box_2 is code
    # veh_selectable's array operand: the live unit base + 2 (Thinker repoints it)
    assert rd(pe, 0x5C1A39, 7) == bytes.fromhex("0FBF90") + struct.pack("<I", 0x95282A)
    assert "ClickKeepsView" in PREFS and "BaseCloseKeepsView" in PREFS


def test_go_reset_swallows_while_armed(pe):
    # go_reset: Win_hide(overlay); Time_stop(&g_go_timer); ... mov [eax+0x1DD88],1 on the armed window
    assert rd(pe, 0x50EF57, 5) == b"\xB9" + struct.pack("<I", 0x937118) and call_target(pe, 0x50EF5C) == WIN_HIDE
    assert rd(pe, 0x50EF61, 5) == b"\xB9" + struct.pack("<I", 0x939E60) and call_target(pe, 0x50EF66) == TIME_STOP
    assert rd(pe, 0x50F0DC, 10) == bytes.fromhex("C78088DD010001000000")


def test_right_release_with_goto_cursor_is_dropped_by_the_engine(pe):
    # MapWin_click 0x46D7E1: is_right? -> [ebp-0x28] (go-to cursor) -> 0x46EAC4 = the bare cleanup
    assert rd(pe, 0x46D7E1, 12) == bytes.fromhex("8B451085C07509A138A9930085C0")[:12]
    assert rd(pe, 0x46D7F1, 5) == bytes.fromhex("8B45D885C0")
    assert 0x46D7F6 + 6 + struct.unpack("<i", rd(pe, 0x46D7F8, 4))[0] == 0x46EAC4
    assert "g_origLeftClick(gw, edx, x, y);" in CTL


# ---- praxdrag.cpp vs prax.dll --------------------------------------------------------------------------

def test_prax_sources_carry_the_sites():
    for off in PRAX_SITES:
        assert re.search(r"= 0x%05X;" % off, PRAX), hex(off)
    assert "kMsgNever = 0x3FFF" in PRAX


@pytest.mark.parametrize("which", ["clean", "live"])
def test_prax_sites_match(which, prax_bak_path):
    p = prax_bak_path if which == "clean" else prax_bak_path.with_name("prax.dll")
    if not p.exists():
        pytest.skip(f"{p.name} not present")
    px = pefile.PE(str(p), fast_load=True)
    assert px.OPTIONAL_HEADER.ImageBase == PRAX_BASE
    for off, clean in PRAX_SITES.items():
        assert px.get_data(off, len(clean.split())) == bytes.fromhex(clean), hex(off)


def test_prax_sites_stay_clear_of_the_patcher_sites():
    doc = yaml.safe_load((ROOT / "patches" / "patches_prax.yaml").read_text(encoding="utf-8"))
    spans = []
    for sect in ("code_caves", "sites"):
        for item in doc.get(sect, []) or []:
            va, ln = item.get("virtual_addr"), item.get("length")
            if va is not None and ln:
                spans.append((int(va) - PRAX_BASE, int(va) - PRAX_BASE + int(ln)))
    assert spans, "no prax patch sites parsed"
    for off, clean in PRAX_SITES.items():
        end = off + len(clean.split())
        for lo, hi in spans:
            assert end <= lo or off >= hi, f"prax site {off:#x} overlaps patcher span {lo:#x}-{hi:#x}"


def test_unit_array_base_is_rebased_once(pe):
    """veh_selectable's operand is an absolute VA (array base + 2). The DLL must rebase it through At() ONCE:
    subtracting the image base as well pointed the hover's waypoint save/restore into the exe's code
    (0x552828) and crashed on a left click (2026-10-07)."""
    assert u32(pe, 0x5C1A39 + 3) - 2 == 0x952828
    assert "g_vehs = At(RdP<uint32_t>(At(kVA_VehSelOperand) + 3) - 2);" in CTL
    assert "- 2 - kImageBase" not in CTL
    assert "VirtualQuery(g_vehs" in CTL, "the live unit pointer must be checked as writable data before use"


def test_base_close_button_center_site(pe):
    """The base screen's close button recentres through its own Console_center call (move mode, selected unit 2+
    tiles off screen); 'Closing a Base Never Recenters Map' stubs it as well as BaseWin_exit's."""
    assert rd(pe, 0x41D6A3, 5) == cpp_bytes(CTL, "kBaseButtonCenterBytes") and call_target(pe, 0x41D6A3) == 0x515400
    assert rd(pe, 0x41D69E, 5) == bytes.fromhex("B9B0569100")      # mov ecx, Console
    assert "kVA_BaseButtonCenter = 0x41D6A3" in CTL
    assert "WriteBranch(kVA_BaseButtonCenter, 0xE8" in CTL


def test_hover_gate_checks_map_local_coordinates(pe):
    """Win_get_mouse_window keeps the event's raw screen point (x 0x9B6628, y 0x9B662C) and makes it window-local by
    origin = +0x13C + +0x14C (x), +0x140 + +0x150 (y). The hover line draws only when the move's x/y equal the raw
    point made local to the MAP window: over the console window's top band the map receives console-local
    coordinates (traced 2026-10-10)."""
    assert rd(pe, 0x5F6F2A, 5) == bytes.fromhex("A328669B00")        # mov [0x9B6628], eax  (raw x)
    assert rd(pe, 0x5F6F38, 6) == bytes.fromhex("890D2C669B00")      # mov [0x9B662C], ecx  (raw y)
    assert rd(pe, 0x5F6FC3, 12) == bytes.fromhex("8B954C0100008B853C010000")   # +0x14C, +0x13C
    assert rd(pe, 0x5F6FD5, 12) == bytes.fromhex("8B85500100008B9540010000")   # +0x150, +0x140
    assert "kVA_MouseRawX      = 0x9B6628, kVA_MouseRawY = 0x9B662C" in CTL
    assert "kWinOrgX0 = 0x13C, kWinOrgX1 = 0x14C, kWinOrgY0 = 0x140, kWinOrgY1 = 0x150" in CTL
    assert rd(pe, 0x5F231C, 6) == bytes.fromhex("89357C7A9B00")      # mov [g_last_mouse_win], esi
    assert "kVA_LastMouseWin   = 0x9B7A7C" in CTL
    assert "FixMapPoint(gw, mx, my)" in CTL and "g_origMove(gw, edx, mx, my)" in CTL


def test_view_mode_right_click_enters_move_mode_first(pe):
    """In view mode the inline go-to calls Console_set_move(1) AFTER writing the order (0x46E083..0x46E093); a unit
    with orders is not selectable there, so set_move readies the next unit and the order is lost (traced
    2026-10-10). RightClickVeh enters move mode first."""
    assert rd(pe, 0x46E083, 21) == bytes.fromhex("A188929300" "85C0" "750C" "6A01" "B9B0569100" "E888340A00")
    assert call_target(pe, 0x46E093) == 0x511520
    assert rd(pe, 0x511520, 3) == bytes.fromhex("558BEC")
    assert "kVA_SetMove        = 0x511520" in CTL


def test_waypoint_layout_matches_the_engine(pe):
    """Ctrl+right waypoints mirror the engine's own G/Space branch and commit: flag 0x2000000 + count +0x12 + int16
    slots x +0x14 / y +0x1C; the go-to commit keeps the path when the flag is set; the painter writes slot[count]."""
    assert rd(pe, 0x517C74, 10) == bytes.fromhex("83FA67" "7409" "83FA20" "0F85")     # 'g' / space
    assert rd(pe, 0x517CCC, 6) == bytes.fromhex("81C900000002")                       # or ecx, 0x2000000
    assert rd(pe, 0x517CF7, 8) == bytes.fromhex("C6048D3A28950001")                   # count = 1
    assert rd(pe, 0x46DFC6, 6) == bytes.fromhex("F7C100000002")                       # commit: test flag
    assert rd(pe, 0x46DFF3, 8) == bytes.fromhex("66891C553C289500")                   # slot x[count] = tile x
    assert rd(pe, 0x46E009, 8) == bytes.fromhex("66890C5544289500")                   # slot y[count] = tile y
    assert rd(pe, 0x46F18C, 8) == bytes.fromhex("6689144D3C289500")                   # painter: x[count]
    assert rd(pe, 0x463040, 3) == bytes.fromhex("558BEC")                             # pixel_to_tile entry
    assert "kVehWaypointFlag = 0x2000000" in CTL
    assert "kVehWpCount = 0x12, kVehWpAux = 0x13, kVehWpX = 0x14, kVehWpY = 0x1C" in CTL
    assert "kVA_PixelToTile    = 0x463040" in CTL
    assert "if (AddWaypoint(gw, x, y)) return;" in CTL


def test_remaining_byte_tables_match_the_exe(pe):
    """Audit 2026-10-10: every memcmp'd table is tied to the exe, not just its call target."""
    assert rd(pe, 0x46E463, 14) == cpp_bytes(CTL, "kSplitCursorBytes")
    assert rd(pe, 0x4B5D95, 5) == cpp_bytes(CTL, "kStatusDrawDestBytes")
    assert rd(pe, 0x4B5DC2 - 5, 10) == cpp_bytes(CTL, "kStatusHideBytes")
    assert rd(pe, 0x46B1F5, 3) == bytes.fromhex("568BF1")    # set_center resume = an instruction boundary (push esi)


THINKER_SRC = ROOT.parent / "refs" / "thinker" / "src"


def test_thinker_patches_stay_clear_of_our_sites():
    """Thinker patches the exe IN MEMORY at startup; a write over one of our byte sites is fatal. Every
    write_call / write_jump / write_offset / write_bytes literal must sit outside each site's footprint."""
    if not THINKER_SRC.exists():
        pytest.skip("refs/thinker not present")
    sites = {0x46EF8A: 27, 0x46E529: 27, 0x46E36D: 11, 0x46DF0E: 9, 0x46E544: 13, 0x46E463: 14, 0x4B5D95: 5,
             0x4B5DBD: 10, 0x46B1F0: 5, 0x41A600: 5, 0x41D6A3: 5, 0x515400: 7,
             0x46D758: 10, 0x46E11F: 11, 0x46E1AF: 6, 0x46EC62: 12,   # + PickSitesOk (right-click pick, 2026-10-14)
             0x4E0A86: 4,   # + the palette highlight bound byte (0x4E0A88), patched at install
             0x5107E0: 12}  # + Console_selected head (PickCancelByLeft)
    hits = []
    for f in THINKER_SRC.glob("*.cpp"):
        for m in re.finditer(r"write_(?:call|jump|offset|bytes|byte)\s*\(\s*0x([0-9A-Fa-f]{6})", f.read_text(encoding="utf-8", errors="replace")):
            va = int(m.group(1), 16)
            for lo, ln in sites.items():
                if lo - 4 < va < lo + ln:
                    hits.append(f"{f.name}: {va:#x} inside site {lo:#x}+{ln}")
    assert not hits, hits


def test_keep_view_recentres_on_the_current_centre():
    """Audit 2026-10-10: skipping set_center outright also skipped TutWin_reset and the route-overlay repaint; the
    stub now passes this map's current centre (+0x1DD9C / +0x1DDA0), so only the redraw is skipped."""
    assert "mov  eax, dword ptr [ecx + 0x1DD9C]" in CTL and "mov  eax, dword ptr [ecx + 0x1DDA0]" in CTL
    assert "ret  0xC" not in CTL.split("void StubSetCenter()")[1].split("StubBaseCenter")[0]
    assert "const bool outer = g_inLeftClick;" in CTL and "g_inLeftClick = outer;" in CTL


def test_waypoint_path_hygiene():
    """Audit 2026-10-10: the pending path is identified by unit id/faction/tile, not by index alone; stale
    collecting flags are dropped before hover / Ctrl+right / a plain right click; a non-path order strips it; Esc
    is eaten only on the live map; no Ctrl+right waypoints in a network game."""
    assert "bool WpVehIsOurs()" in CTL and "RememberWpVeh(veh);" in CTL
    assert CTL.count("DropStalePath(veh);") >= 3
    assert "kVehPathCommitted = 0x2000200" in CTL and "if (!committed) StripPath(v);" in CTL
    assert "Rd<int>(kVA_MultiplayerActive) != 0" in CTL
    esc = CTL.split("m->wParam == VK_ESCAPE")[1].split("{")[0]
    assert "MapTakesInput()" in esc and "kVA_SelMode" in esc and "kConDragActive" in esc
    assert "FixMapPoint(gw, x, y)" not in CTL.split("bool AddWaypoint(")[1].split("void __fastcall RightClickWrap")[0]


# ---- the tile context menu's hotkey column (RelabelMenu) ------------------------------------------------------

def test_strings_helpers_and_label_table(pe):
    """Strings_get only validates a pointer against the pool (mov eax,[ecx+4]; mov edx,[esp+4]; cmp edx,eax),
    Strings_put is alloc + copy, and the label-table read the engine does is a char* fetch (mov eax,[edx+0xD38])
    straight into Strings_get -- so the entries are pointers, not indices."""
    assert rd(pe, 0x6169A0, 9) == bytes.fromhex("8B4104" "8B542404" "3BD0")
    assert rd(pe, 0x616970, 6) == bytes.fromhex("5657" "8B7C240C")
    assert rd(pe, 0x420858, 12) == bytes.fromhex("8B82380D0000" "50" "E83C611F00")   # ... call Strings_get
    assert rd(pe, 0x5D468C, 5) == bytes.fromhex("397E10" "7D39")                     # alloc: cmp [this+0x10] (free), need
    for name, val in [("kVA_TextLabels", "0x9B90F8"), ("kVA_TextTable", "0x9B90D8"), ("kVA_StringsPut", "0x616970"),
                      ("kLblMoveUnit", "557"), ("kLblMoveCursor", "565"), ("kPoolFree", "0x10")]:
        assert re.search(name + r"\s*=\s*" + val + r"\b", CTL), name


def test_labels_txt_indices():
    """labels.txt line = label index + 11 (Thinker: label_get(403) 'North', 322 'Unmodified', 971 'Stapled Base');
    the two relabelled entries carry the vanilla text the DLL compares against before touching them."""
    p = config.game_dir(required=False) / "labels.txt"
    if not p.is_file():
        pytest.skip("no labels.txt in the game folder")
    lines = p.read_text(encoding="latin-1").split("\n")
    def label(idx): return lines[idx + 11 - 1].rstrip("\r")
    assert label(403) == "North" and label(322) == "Unmodified" and label(971) == "Stapled Base"
    assert label(557) == "Move unit to here"
    assert label(565) == "Move cursor to here|Shift+Right"
    assert re.search(r'kMoveUnitOrig\[\]\s*=\s*"Move unit to here"', CTL)
    assert re.search(r'kMoveCursorOrig\[\]\s*=\s*"Move cursor to here\|Shift\+Right"', CTL)


def test_editor_gate_is_the_paint_input_only(pe):
    """The scenario editor changes map input only through its paint keys and its armed paint drag; the editor bit
    GameState 0x40 is never cleared in a session and is saved with the game, so the set keys on EditorEngaged and
    never on the bit alone (the first build did: the set went dark for good once the editor had been activated)."""
    # Console_edit_lock 0x4E1F40: editor bit, then Scroll Lock (GetKeyState(0x91) & 1), then the Editor Only bit 0x8000000
    assert rd(pe, 0x4E1F40, 12) == bytes.fromhex("F605C0649A0040" "7503" "33C0" "C3")
    assert rd(pe, 0x4E1F4C, 7) == bytes.fromhex("6891000000" "FF15") and u32(pe, 0x4E1F53) == 0x66932C   # push 0x91; call [GetKeyState]
    assert rd(pe, 0x4E1F5B, 10) == bytes.fromhex("F705C0649A00" "00000008")
    # the press-paint rule, identical in MapWin_on_left_down 0x46EE18 and _right_down 0x46EC74: Shift && Ctrl, or
    # Scroll Lock && !Ctrl, then the editor bit -> paint drag armed (left: 0x46EE5D `mov [esi-0x3CE0],1`)
    key_rule = bytes.fromhex("6A10" "FFD7" "33C9" "8ACC" "84C9" "740C" "6A11" "FFD7" "33D2" "8AD4" "84D2")
    assert rd(pe, 0x46EE18, 22) == key_rule and rd(pe, 0x46EE2E, 2) == bytes.fromhex("751F")
    assert rd(pe, 0x46EE30, 5) == bytes.fromhex("6891000000") and rd(pe, 0x46EE43, 2) == bytes.fromhex("6A11")
    assert rd(pe, 0x46EE4F, 7) == bytes.fromhex("F605C0649A0040")
    assert rd(pe, 0x46EE5D, 10) == bytes.fromhex("C78620C3FFFF" "01000000")
    assert rd(pe, 0x46EC74, 22) == key_rule and rd(pe, 0x46EC8A, 2) == bytes.fromhex("751B")
    assert rd(pe, 0x46EC8C, 5) == bytes.fromhex("6891000000")
    # MapWin_click: an armed paint drag is consumed first (0x46D93D reads Console+0x1DD8C, 0x46D958 clears it);
    # then [ebp-0x20] = Ctrl (GetAsyncKeyState(0x11) high byte), replaced by !Ctrl when editor && Scroll Lock && !Shift;
    # the click-paint branch 0x46E299 needs the editor bit, that local and the human's turn
    assert rd(pe, 0x46D93D, 6) == bytes.fromhex("8B868CDD0100") and rd(pe, 0x46D958, 10) == bytes.fromhex("C7868CDD0100" "00000000")
    assert 0x46D93D < 0x46E299
    assert rd(pe, 0x46D6FB, 2) == bytes.fromhex("6A11") and rd(pe, 0x46D714, 3) == bytes.fromhex("895DE0")
    assert rd(pe, 0x46D719, 5) == bytes.fromhex("6891000000") and rd(pe, 0x46D728, 2) == bytes.fromhex("6A10")
    assert rd(pe, 0x46D738, 10) == bytes.fromhex("33D2" "85DB" "0F94C2" "8955E0")   # xor edx,edx; test ebx,ebx; sete dl; mov [ebp-0x20],edx
    assert rd(pe, 0x46E299, 24) == bytes.fromhex("F605C0649A0040" "0F84C7000000" "8B45E0" "85C0" "0F84BC000000")
    assert rd(pe, 0x46E2B1, 5) == bytes.fromhex("A1") + struct.pack("<I", 0x93A938)        # mov eax,[ControlTurnC]
    assert call_target(pe, 0x46E2EF) == 0x46B510                                # MapWin_editor
    # MapWin_on_mouse_move: an armed paint drag (Console+0x1DD8C = esi-0x3CE0, esi = Console+0x21A6C) paints and returns
    assert rd(pe, 0x46F0A0, 10) == bytes.fromhex("8B8620C3FFFF" "85C0" "741B")
    assert 0x21A6C - 0x3CE0 == 0x1DD8C and call_target(pe, 0x46F0B7) == 0x46B510
    # "Activate Scenario Editor" (menu id 0x61A -> Console_load_proc(1, 0)) sets the bit with `or [GameState], 0xE0`
    assert rd(pe, 0x51BC1B, 10) == bytes.fromhex("810DC0649A00" "E0000000")
    assert call_target(pe, 0x51BF6D) == 0x51BBA0 and call_target(pe, 0x51D066) == 0x51BBA0
    # the sources
    assert "kConPaintMode  = 0x1DD8C" in CTL and "kGameStateEditorOnly = 0x8000000" in CTL
    assert "bool  ScrollLockOn() { return (GetKeyState(VK_SCROLL) & 1) != 0; }" in CTL
    body = CTL[CTL.index("bool  EditorEngaged()"):]
    body = body[:body.index("}")]
    for term in ("CtrlHeld()", "ScrollLockOn()", "kConPaintMode", "kGameStateEditorOnly"):
        assert term in body, term
    bare = [m.start() for m in re.finditer(r"(?<![A-Za-z])Editor\(\)", CTL)]
    assert len(bare) == 3, bare          # the definition, its one use inside EditorEngaged, and ReleasePaintCapture's
                                         # (the paint capture is the editor's own state: keyed on the bit, not on the set's gate)
    assert CTL.count("EditorEngaged()") == 10  # definition + 9 gates (right click, Shift split, hover, left press, right press, waypoint, Esc, right-click pick, left-click cancel)


def test_right_click_completes_an_armed_pick(pe):
    """User 2026-10-14: in Modern mode P then RIGHT click sets the patrol target (vanilla: P then left; a right click
    drops the pick). A right release on the map while a key/menu pick is armed runs the engine's own LEFT click."""
    # Console_set_selecting 0x510490(mode, range): stores range +0x23D14 and mode +0x23D10
    assert rd(pe, 0x510493, 3) == bytes.fromhex("8B450C") and rd(pe, 0x51049A, 6) == bytes.fromhex("8981143D0200")
    assert rd(pe, 0x5104A7, 6) == bytes.fromhex("8999103D0200")
    # its callers push the pick modes: 8 patrol, 0xB, 0xA, 4 (computed range), and 2/3 (cmp esi,0x1C; sete dl; add edx,2)
    for va in (0x4D7CE3, 0x4D7F55, 0x4D89B9, 0x4D8CBD, 0x4D928D):
        assert call_target(pe, va) == 0x510490, hex(va)
    assert rd(pe, 0x4D7F55 - 9, 4) == bytes.fromhex("6AFF6A08")      # push -1; push 8 (patrol); mov ecx,Console
    assert rd(pe, 0x4D8CBD - 9, 4) == bytes.fromhex("6AFF6A0B") and rd(pe, 0x4D928D - 7, 2) == bytes.fromhex("6A0A")
    assert rd(pe, 0x4D89B9 - 2, 2) == bytes.fromhex("6A04")               # mov ecx,Console; push eax (range); push 4
    assert rd(pe, 0x4D7CD2, 12) == bytes.fromhex("83FE1C" "0F94C2" "83C202" "6AFF" "52")
    # go_timer's drags write the mode directly (1 / 9), never through the setter
    assert rd(pe, 0x50F359, 6) == bytes.fromhex("893DC0939300") and rd(pe, 0x50F5F3, 6) == bytes.fromhex("89BE103D0200")
    # MapWin_click: the mode is taken (0x5107E0 clears it) into [ebp-0x24]; a right release with a mode returns
    # (0x46D7E1 is_right -> 0x46D807 -> 0x46EAC4); the left path runs the pick from that local through the 2..11 table
    assert call_target(pe, 0x46D758) == CON_SELECTED and rd(pe, 0x5107F7, 10) == bytes.fromhex("C781103D0200" "00000000")
    assert rd(pe, 0x46D7E1, 5) == bytes.fromhex("8B451085C0") and rd(pe, 0x46D807, 11) == bytes.fromhex("8B45DC85C00F85B2120000")
    assert rd(pe, 0x46E1B5, 1) == bytes.fromhex("77") and rd(pe, 0x46E1B7, 3) == bytes.fromhex("FF24B5")
    assert u32(pe, 0x46E1BA) == 0x46EB68                               # jmp [esi*4 + 0x46EB68]
    # the source's byte tables are the exe's
    assert rd(pe, 0x46D758, 10) == cpp_bytes(CTL, "kPickTakeBytes")
    assert rd(pe, 0x46E11F, 11) == cpp_bytes(CTL, "kPickRunBytes")
    assert rd(pe, 0x46E1AF, 6) == cpp_bytes(CTL, "kPickTableBytes")
    assert rd(pe, 0x46EC62, 12) == cpp_bytes(CTL, "kPickRDownBytes")       # right press: a set mode arms nothing
    assert "kPickModeLo = 2, kPickModeHi = 11" in CTL and "kSelModeCtrlDrag = 9" in CTL
    # the wrapper: checked first in RightClickWrap, gated, forwards through the LEFT click wrapper
    body = CTL[CTL.index("bool PickByRight("):]
    body = body[:body.index("\n}\n")]
    for term in ("g_pickOk", "PickArmed()", "EditorEngaged()", "MapTakesInput()", "kConMapWinIdx",
                 "FixMapPoint(gw, x, y)", "LeftClickWrap(gw, edx, x, y)"):
        assert term in body, term
    wrap = CTL[CTL.index("void __fastcall RightClickWrap("):]
    assert wrap[wrap.index("{") + 1:].lstrip().startswith("if (PickByRight(gw, edx, x, y)) return;")
    assert "g_pickOk = PickSitesOk();" in CTL


def test_left_click_cancels_an_armed_pick(pe):
    """User 2026-10-15: in Modern mode orders go with the RIGHT button only -- a left click on the map while a pick is
    armed (patrol 8, bomb run 0xB, airdrop 4, artillery 0xA, road/tube to 2/3) cancels it like a vanilla right
    release: Console_selected 0x5107E0 takes the mode and restores the arrow; the click goes no further."""
    # the bomb run is pick mode 0xB: Console::bomb_run's setter call (0x4D8CBD) pushes 0xB (asserted above too)
    assert call_target(pe, 0x4D8CBD) == 0x510490 and rd(pe, 0x4D8CBD - 9, 4) == bytes.fromhex("6AFF6A0B")
    # Console_selected: thiscall, no args, plain ret; reads +0x23D10, clears it, walks the map windows 0x7D3C3C..0x7D3C5C
    # restoring cursor id 0x7F00 (IDC_ARROW)
    assert rd(pe, 0x5107E0, 12) == cpp_bytes(CTL, "kPickCancelBytes")
    assert rd(pe, 0x5107F7, 10) == bytes.fromhex("C781103D0200" "00000000") and rd(pe, 0x510801, 5) == bytes.fromhex("BF3C3C7D00")
    assert rd(pe, 0x510836, 5) == bytes.fromhex("68007F0000") and rd(pe, 0x510887, 6) == bytes.fromhex("81FF5C3C7D00")
    assert rd(pe, 0x510898, 1) == bytes.fromhex("C3")
    assert "kVA_ConSelected  = 0x5107E0" in CTL
    assert "memcmp(At(kVA_ConSelected), kPickCancelBytes, sizeof kPickCancelBytes) == 0" in CTL
    # the cancel IS the engine's own right release (audit 2026-10-15): MapWin_click runs go_reset 0x50EF50 (undoes a
    # patrol press's drag / capture / line) BEFORE it takes the mode at 0x46D758, and a right release then drops it
    assert rd(pe, 0x46D6F6, 5) == bytes.fromhex("E855180A00") and 0x46D6F6 + 5 + 0x0A1855 == 0x50EF50
    assert call_target(pe, 0x46D758) == 0x5107E0
    assert rd(pe, 0x46D7E1, 6) == bytes.fromhex("8B451085C075") and rd(pe, 0x46D807, 3) == bytes.fromhex("8B45DC")
    # the cancel: gated, the engine's right release, runs first in LeftClickWrap
    body = CTL[CTL.index("bool PickCancelByLeft(BYTE* gw, void* edx, int x, int y)\n{"):]
    body = body[:body.index("\n}\n")]
    for term in ("g_pickByRight", "g_on", "g_pickOk", "MainGw()", "PickArmed()", "EditorEngaged()", "kConMapWinIdx",
                 "g_origRightClick(gw, edx, x, y)"):
        assert term in body, term
    assert "At(kVA_ConSelected)" not in body          # never the bare take-and-drop: it skipped go_reset
    left = CTL[CTL.index("void __fastcall LeftClickWrap"):]
    left = left[:left.index("\n}\n")]
    assert left.index("PickCancelByLeft(gw, edx, x, y)") < left.index("g_origLeftClick(gw, edx, x, y);\n    g_inLeftClick = outer;")
    # PickByRight's own left click is the one that EXECUTES: the bypass flag is set only around it
    pr = CTL[CTL.index("bool PickByRight("):]
    pr = pr[:pr.index("\n}\n")]
    assert pr.index("g_pickByRight = true;") < pr.index("LeftClickWrap(gw, edx, x, y);") < pr.index("g_pickByRight = outer;")


def test_paint_press_capture_and_its_release(pe):
    """A scenario-editor paint press captures the mouse to the map through g_sb_track_win 0x9B7ABC, and no engine
    release path clears it for a paint stroke, so the HUD (and its palette) stayed dead afterwards; the DLL
    releases it after the map's click, the way go_reset releases a drag's (traced 2026-10-14, hook_editorhud.js)."""
    # Win_get_mouse_window 0x5F6F74: a shown g_sb_track_win is the event's window before the list walk
    assert rd(pe, 0x5F6F74, 0x17) == bytes.fromhex("8B1DBC7A9B00" "85DB" "741E" "F6839C00000001" "0F85ED000000")
    # the paint presses capture (right 0x46ECC9, left 0x46EE73): if g_sb_track_win == 0 -> phase := 0, win := the map's GraphicWin
    assert rd(pe, 0x46ECC9, 0x24) == bytes.fromhex("391DBC7A9B00" "751C" "8B9694E5FDFF" "8B4204" "891DC07A9B00" "8D8C3094E5FDFF" "890DBC7A9B00")
    assert rd(pe, 0x46EE73, 0x29) == bytes.fromhex("A1BC7A9B00" "85C0" "7520" "8B9694E5FDFF" "8B4204" "C705C07A9B0000000000" "8D8C3094E5FDFF" "890DBC7A9B00")
    # go_reset releases a map's capture only when it is the armed one (g_go_win_idx 0x68A5CC) or dragging (+0x1DD80):
    # `mov ecx,[ebp-4]; mov edx,[go_win_idx]; cmp ecx,edx; je skip; cmp [eax+0x1DD80],ebx; je skip`
    assert rd(pe, 0x50EF93, 0x19) == bytes.fromhex("8B4DFC" "8B15CCA56800" "3BCA" "0F8481000000" "399880DD0100" "7479")
    # ... and releases it as: clear g_sb_track_win, call the window's vtbl+0x10, clear g_sb_track_phase when it names the window
    assert rd(pe, 0x50EFE3, 0x24) == bytes.fromhex("A1BC7A9B00" "3BC7" "750D" "891DBC7A9B00" "8B17" "8BCF" "FF5210" "393DC07A9B00" "7506" "891DC07A9B00")
    # the same shape in FlatButton's release 0x607A20 and Win_set_modal 0x5EE1C8 (the two accidental vanilla releases)
    assert rd(pe, 0x607A20, 0x2D) == bytes.fromhex("A1BC7A9B00" "56" "8BF1" "3BC6" "750F" "C705BC7A9B0000000000" "8B06" "FF5010" "3935C07A9B00" "750A" "C705C07A9B0000000000")
    assert rd(pe, 0x5EE1C8, 0x23) == bytes.fromhex("8935E07A9B00" "891DCC7A9B00" "891DD07A9B00" "740F" "3BCE" "740B" "8B01" "FF5010" "891DBC7A9B00")
    # MapWin_click's paint consumption clears only the paint mode (0x46D958), never the capture
    assert rd(pe, 0x46D958, 10) == bytes.fromhex("C7868CDD0100" "00000000")
    # the map's vtbl+0x10 is go_reset itself: adjustor 0x51DE30 -> 0x46EB90 -> jmp go_reset
    assert u32(pe, 0x66EC18 + 0x10) == 0x51DE30
    assert rd(pe, 0x51DE30, 0xE) == bytes.fromhex("2B49FC" "81E928230000" "E9520DF5FF") and 0x51DE39 + 5 + 0xFFF50D52 - 0x100000000 == 0x46EB90
    assert rd(pe, 0x46EB90, 5) == bytes.fromhex("E9BB030A00") and 0x46EB90 + 5 + 0xA03BB == 0x50EF50
    # the sources: the release runs after BOTH map release wrappers, and only with nothing armed or dragging
    assert "kVA_TrackWin   = 0x9B7ABC" in CTL and "kVA_TrackPhase = 0x9B7AC0" in CTL and "kSlotTrackEnd  = 0x10" in CTL
    body = CTL[CTL.index("void ReleasePaintCapture(BYTE* gw)"):]
    body = body[:body.index("\n}\n")]
    for term in ("Editor()", "kVA_TrackWin", "kConPaintMode", "kConDragActive", "kVA_GoWinIdx", "kSlotTrackEnd", "kVA_TrackPhase"):
        assert term in body, term
    assert CTL.count("ReleasePaintCapture(gw)") == 3       # LeftClickWrap (its pick-cancel return and its end) and RightClickWrap
    left = CTL[CTL.index("void __fastcall LeftClickWrap"):]
    left = left[:left.index("\n}\n")]
    assert left.index("g_origLeftClick(gw, edx, x, y);\n    g_inLeftClick = outer;") < left.rindex("ReleasePaintCapture(gw)")
    right = CTL[CTL.index("void __fastcall RightClickWrap"):]
    right = right[:right.index("\n}\n")]
    assert right.index("RightClickInner(gw, edx, x, y);") < right.index("ReleasePaintCapture(gw)")


def test_palette_highlight_bound_covers_every_mode(pe):
    """Console_editor_paints 0x4E0A50 maps a mode to its palette button id through the mode table only for modes
    6..25; modes 26..29 (right column rows 2..5) got an id no button carries, so vanilla never highlighted them.
    The DLL raises the bound to 0x1E; the id->mode expansion in MainWinIface_on_event has no bound to match."""
    # cmp esi,6; lea eax,[esi+0x3F3]; jl direct; cmp esi,0x1A; jge direct; sub esi,6; mov ecx,0x13; mov eax,0x691AE8; loop
    assert rd(pe, 0x4E0A7B, 0x38) == bytes.fromhex(
        "83FE06" "8D86F3030000" "7C2D" "83FE1A" "7D28" "83EE06" "B913000000" "B8E81A6900"
        "833800" "7505" "3BF1" "7C01" "4E" "83E820" "49" "3D88186900" "7DEB" "8D86F9030000")
    # MainWinIface_on_event 0x45CCF6: ids past the 0x11th expand over the absent entries (`cmp edx,ecx; jl; inc edx`), unbounded
    assert rd(pe, 0x45CCF6, 0x30) == bytes.fromhex(
        "83F811" "7C31" "8D50EF" "33C9" "B888186900" "833800" "7505" "3BD1" "7C01" "42" "83C020" "41" "3D081B6900" "7CEB"
        "83C206" "52" "B9B0569100" "E8283D")
    # the mode table: 19 entries of 0x20 B from 0x691888; entries 10, 15..18 (modes 16, 21..24) are absent in this game
    absent = [i for i in range(19) if u32(pe, 0x691888 + 0x20 * i) == 0]
    assert absent == [10, 15, 16, 17, 18]
    def compressed_id(mode):              # the engine's loop with the bound lifted: entry index+1 is the loop's ecx
        esi = mode - 6
        for i in range(18, -1, -1):
            if i in absent and esi >= i + 1:
                esi -= 1
        return 0x3F9 + esi
    assert [compressed_id(m) for m in (6, 17, 25)] == [0x3F9, 0x403, 0x407]     # the buttons seen pressed in the trace
    assert [compressed_id(m) for m in (26, 27, 28, 29)] == [0x408, 0x409, 0x40A, 0x40B]
    assert compressed_id(29) == 0x3F3 + 24                                       # the last palette button (ids 0x3F3..0x40B)
    assert "kVA_PaintsBound = 0x4E0A86" in CTL and "kPaintsBoundNew = 0x1E" in CTL
    assert "kPaintsBoundBytes[5] = { 0x83, 0xFE, 0x1A, 0x7D, 0x28 }" in CTL
    assert "WriteCode(At(kVA_PaintsBound) + 2, &kPaintsBoundNew, 1)" in CTL
