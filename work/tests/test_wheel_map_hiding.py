"""uimod's wheel capture over the full-screen interfaces the map hides behind (src/uimod/src/wheel.cpp), against the
pristine exe.

PRACX zooms the map on a notch while its IsMapShowing() holds (map timers running, base screen, SocialWin and TutWin
hidden). Opened from the map, the HUD's leave stops the map timers, so PRACX posts arrows and the screen scrolls;
opened from a base (the Design Workshop, or the Datalinks through a picker's HELP), nothing stops them and the notch
zoomed the map behind the screen. The DLL posts the arrows itself while the live interface (the top of the engine's
mode stack) is the workshop (1), the HQ reports (5) or the Datalinks (8), and only for a notch addressed to the game
window. The engine facts the source relies on must hold in the pristine exe.
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

import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

WHEEL = (ROOT.parent / "src" / "uimod" / "src" / "wheel.cpp").read_text(encoding="utf-8")

MODE_TABLE = 0x7AE778
MODE_IDX = 0x7D392C
IFACE_PTRS = 0x7AE7F0
SET_IFACE_MODE = 0x45D310
GAME_HWND = 0x9B7B28
MAP_TIMERS_STOP = 0x50F440
TIME_STOP = 0x616780


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def le(va: int) -> str:
    return struct.pack("<I", va).hex().upper()


def calls_to(body: bytes, base: int, target: int) -> list[int]:
    out = []
    for i in range(len(body) - 4):
        if body[i] == 0xE8 and base + i + 5 + struct.unpack("<i", body[i + 1:i + 5])[0] == target:
            out.append(base + i)
    return out


def test_source_constants():
    for name, va in (("kIfaceModeTable", MODE_TABLE), ("kIfaceModeIdx", MODE_IDX), ("kIfacePtrTable", IFACE_PTRS),
                     ("kGameHwnd", GAME_HWND)):
        assert re.search(rf"{name}\s*=\s*0x{va:X}\b", WHEEL), name
    body = re.search(r"kMapHidingModes\[\]\s*=\s*\{(.*?)\};", WHEEL, re.S).group(1)
    modes = [int(m) for m in re.findall(r"^\s*(\d+),", body, re.M)]
    assert modes == [1, 5, 8]
    assert "if (!under) under = MapHidingIfaceUp(m->hwnd);" in WHEEL
    assert re.search(r"kMapBlinkTimer\s*=\s*0x915688\b", WHEEL)
    assert "if (Rd<uint32_t>(kMapBlinkTimer + 4) == 0 || GetFocus() != game) return nullptr;" in WHEEL
    # the mode stack's room: the pointer table starts right after it
    assert (IFACE_PTRS - MODE_TABLE) // 4 == 30
    assert "idx < 0 || idx >= kIfaceModeSlots" in WHEEL


def test_capture_only_for_the_game_window():
    """A notch addressed to another window (a PRACX Preferences control) is never captured or turned into arrows."""
    assert "if (m->message == WM_MOUSEWHEEL && m->hwnd && m->hwnd == Rd<HWND>(kGameHwnd))" in WHEEL


# ---- the workshop's unit row (user 2026-11-14: up = left, down = right, as Thinker does; never override Thinker) ----

DESIGNWIN = 0x71F2B0
DW_ON_KEY = 0x439A20
GET_ACTIVE_TARGET = 0x5F6A50
THINKER_SRC = ROOT.parent / "refs" / "thinker" / "src"
PRACX_SRC = ROOT.parent / "refs" / "pracx" / "shared"


def test_unit_row_source():
    assert re.search(r"kDesignWin\s*=\s*0x71F2B0\b", WHEEL)
    assert re.search(r"kGetActiveTarget\s*=\s*0x5F6A50\b", WHEEL)
    assert 'kThinkerDll[] = "thinker.dll"' in WHEEL
    # the workshop is the key target exactly as Thinker tests it (its current_window: key window == DesignWin)
    assert "return (t && t == At(kDesignWin) && (t[kWinShown] & 1)) ? t : nullptr;" in WHEEL
    # up = left, down = right; everything else keeps up / down
    assert ("const WPARAM key = unitRow ? (delta >= 0 ? VK_LEFT : VK_RIGHT) : (delta >= 0 ? VK_UP : VK_DOWN);"
            in WHEEL)
    # order: modal under the cursor first; the workshop and map-hiding fallbacks only when Thinker does not own the wheel
    block = WHEEL[WHEEL.index("const BYTE* under = inClient ? ModalUnder(p) : nullptr;"):WHEEL.index("if (under) {")]
    assert "if (!under && inClient && !ThinkerOwnsWheel(m->hwnd)) {" in block
    assert block.index("WorkshopKeyTarget(m->hwnd)") < block.index("MapHidingIfaceUp(m->hwnd)")
    # Thinker is detected by the game window's class proc living in thinker.dll, not by the dll merely being loaded
    assert "GetClassLongPtrA(game, GCLP_WNDPROC)" in WHEEL and "owner == thinker" in WHEEL


def test_synthetic_left_right_get_the_map_guard():
    """A lParam-0 left / right reaching the map would move a unit west / east: same dequeue check as up / down, but
    only for ours -- under Thinker its own left / right are never touched."""
    assert "const bool leftRight = m->wParam == VK_LEFT || m->wParam == VK_RIGHT;" in WHEEL
    assert "(upDown || (leftRight && !ThinkerOwnsWheel(Rd<HWND>(kGameHwnd))))) {" in WHEEL


def _dw_key_target(pe, vk: int) -> int:
    # DesignWin_on_key: eax = vk - 0xD; ja default (> 0x5C); cl = byte [eax + 0x439B60]; jmp [ecx*4 + 0x439B3C]
    idx = rd(pe, 0x439B60, 0x5D)
    return struct.unpack("<I", rd(pe, 0x439B3C + 4 * idx[vk - 0xD], 4))[0]


def test_workshop_keys_scroll_the_unit_row_on_left_right_only(pe):
    want = bytes.fromhex("8B450C" "83C0F3" "83F85C" "0F87B6000000" "33C9" "8A88609B4300" "FF248D3C9B4300"
                                 "8B16" "6A17" "E996000000" "8B06" "6A18")
    assert rd(pe, DW_ON_KEY + 0x10, len(want)) == want
    default = 0x439AF5                                  # the ja target: no case
    assert _dw_key_target(pe, 0x25) == 0x439A4E         # VK_LEFT  -> on_button_clicked(0x17)
    assert _dw_key_target(pe, 0x27) == 0x439A57         # VK_RIGHT -> on_button_clicked(0x18)
    assert rd(pe, 0x439A57, 12) == bytes.fromhex("8B06" "6A18" "8BCE" "FF90B0000000")
    assert rd(pe, 0x439AED, 8) == bytes.fromhex("8BCE" "FF92B0000000")   # the 0x17 path's call [edx+0xB0]
    assert _dw_key_target(pe, 0x26) == default          # VK_UP: nothing (PRACX's up / down never moved the row)
    assert _dw_key_target(pe, 0x28) == default          # VK_DOWN
    # the 0x17 / 0x18 buttons are the workshop's own unit-row arrows (vtbl +0xB0 = DesignWin_on_button_clicked)
    assert struct.unpack("<I", rd(pe, 0x66B148 + 0xB0, 4))[0] == 0x438460


def test_thinker_maps_the_workshop_wheel_the_same_way():
    """Thinker's ModWinProc: GW_Design (key window == DesignWin 0x71F2B0, via 0x5F6A50) -> up = VK_LEFT, down =
    VK_RIGHT; its class proc is registered over PRACX's (ModRegisterClassA), so it sees the notch first."""
    if not THINKER_SRC.exists():
        pytest.skip("refs/thinker not present")
    gui = (THINKER_SRC / "gui.cpp").read_text(encoding="utf-8")
    eng = (THINKER_SRC / "engine.cpp").read_text(encoding="utf-8")
    patch = (THINKER_SRC / "patch.cpp").read_text(encoding="utf-8")
    assert "key = (zoom_in ? VK_LEFT : VK_RIGHT);" in gui
    assert "bool zoom_in = (wheel_delta >= 0);" in gui
    assert "} else if (state == (int)DesignWin) {\n            return GW_Design;" in gui
    assert re.search(r"Win_get_key_window = \(FWin_get_key_window\)0x5F6A50;", eng)
    assert re.search(r"DesignWin\s+= \(DesignWindow\*\s*\)0x71F2B0;", eng)
    assert "pstWndClass->lpfnWndProc = ModWinProc;" in patch
    if PRACX_SRC.exists():
        pracx = (PRACX_SRC / "pracx.cpp").read_text(encoding="utf-8")
        # PRACX wraps whatever RegisterClassA it found in the import table (Thinker's, when Thinker came first)
        assert "return pfncRegisterClassA(pstWndClass);" in pracx


def test_game_hwnd_is_the_timer_and_invalidate_window(pe):
    # Time_start_3's SetTimer and the game WinProc's WM_ACTIVATE InvalidateRect both take the HWND at 0x9B7B28 (PRACX's
    # phWnd, which its wheel handler compares GetFocus() against, is the same address on SMACX)
    for site, n in ((0x616650, 0x80), (0x5F0650, 0x400)):
        assert bytes.fromhex(le(GAME_HWND)) in rd(pe, site, n), hex(site)


def test_set_iface_mode_pushes_the_entering_mode_before_the_leave(pe):
    """SubInterface_set_iface_mode: idx++ and table[idx] = this->mode, THEN the leaving interface's on_mode(0)."""
    b = rd(pe, SET_IFACE_MODE, 0x6D)
    assert b[3:9] == bytes.fromhex("8B0D" + le(MODE_IDX))                    # mov ecx, [idx]
    assert b[9:12] == bytes.fromhex("8B5604")                                # mov edx, [esi+4]   (this->mode)
    assert b[0x24:0x2B] == bytes.fromhex("8B0485" + le(IFACE_PTRS))          # mov eax, [eax*4 + ptr table] (leaving)
    assert b[0x2B:0x32] == bytes.fromhex("41" "890D" + le(MODE_IDX))         # inc ecx; mov [idx], ecx
    assert b[0x37:0x3E] == bytes.fromhex("89148D" + le(MODE_TABLE))          # mov [ecx*4 + table], edx
    assert b[0x40:0x48] == bytes.fromhex("8B10" "6A00" "8BC8" "FF12")        # leaving->on_mode(0)


@pytest.mark.parametrize("name, store_mode, mode_bytes, store_ptr, ptr_bytes", [
    # Design Workshop build: lea eax,[esi+0xA14] @0x43C2AA; [eax+4] = 1; [0x7AE7F4] = eax
    ("workshop", 0x43C2B9, "C7400401000000", 0x43C2C0, "A3" + le(IFACE_PTRS + 1 * 4)),
    # HQ reports (ReportIf): [esi+4] = 5; [0x7AE804] = esi
    ("reports", 0x4A34A4, "C7460405000000", 0x4A34B4, "8935" + le(IFACE_PTRS + 5 * 4)),
    # Datalinks build: lea eax,[esi+0xA14] @0x429330; [eax+4] = 8; [0x7AE810] = eax
    ("datalinks", 0x429348, "C7400408000000", 0x42934F, "A3" + le(IFACE_PTRS + 8 * 4)),
])
def test_each_screen_registers_its_mode(pe, name, store_mode, mode_bytes, store_ptr, ptr_bytes):
    assert rd(pe, store_mode, len(mode_bytes) // 2) == bytes.fromhex(mode_bytes), name
    assert rd(pe, store_ptr, len(ptr_bytes) // 2) == bytes.fromhex(ptr_bytes), name


def test_iface_is_window_plus_a14(pe):
    assert rd(pe, 0x43C2AA, 6) == bytes.fromhex("8D86140A0000")   # workshop: lea eax, [esi+0xA14]
    assert rd(pe, 0x429330, 6) == bytes.fromhex("8D86140A0000")   # Datalinks: lea eax, [esi+0xA14]


@pytest.mark.parametrize("show, lea", [(0x43D0C0, 0x43D0D9), (0x42BD40, 0x42BD4C)])
def test_workshop_and_datalinks_show_push_their_iface(pe, show, lea):
    """DesignWin_show / DatalinkWin_show: lea ecx,[esi+0xA14]; call SubInterface_set_iface_mode."""
    assert rd(pe, lea, 6) == bytes.fromhex("8D8E140A0000")
    assert calls_to(rd(pe, lea + 6, 5), lea + 6, SET_IFACE_MODE) == [lea + 6]
    assert show < lea < show + 0x30


def test_blink_timer_has_one_start_and_one_stop(pe):
    """kMapBlinkTimer tracks PRACX's m_fGlobalTimersEnabled: Time 0x915688 is started only @0x50F3E6 (PRACX's start
    thunk site 0x50F3E7) and stopped only inside 0x50F440 (after 0x939EB0, PRACX's stop thunk site 0x50F446); its other
    two references are the static ctor / dtor. Time_stop zeroes +4, the running id."""
    text = next(s for s in pe.sections if s.Name.startswith(b".text"))
    d = text.get_data()
    va0 = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
    refs = [va0 + i for i in range(len(d) - 3) if d[i:i + 4] == struct.pack("<I", 0x915688)]
    assert refs == [0x50E9B1, 0x50EA19, 0x50F3E2, 0x50F44B]
    assert calls_to(rd(pe, 0x50F3E6, 5), 0x50F3E6, 0x616350) == [0x50F3E6]     # Time_start
    assert calls_to(rd(pe, 0x50F44F, 5), 0x50F44F, TIME_STOP) == [0x50F44F]    # Time_stop
    assert calls_to(rd(pe, 0x50E9B5, 5), 0x50E9B5, 0x6161D0) == [0x50E9B5]     # ctor
    assert rd(pe, 0x50EA1D, 5) == bytes.fromhex("E9DE771000")                 # jmp dtor 0x616200
    assert rd(pe, 0x6167B2, 3) == bytes.fromhex("895E04")                     # Time_stop: [esi+4] = 0


def test_map_timers_stop_is_the_pracx_stop_site(pe):
    """0x50F440 stops the map's blink timer: PRACX's PRACXStopGlobalTimers_Thunk wraps its call @0x50F446."""
    b = rd(pe, MAP_TIMERS_STOP, 10)
    assert b[:5] == bytes.fromhex("B9B09E9300")
    assert calls_to(b, MAP_TIMERS_STOP, TIME_STOP) == [0x50F445]


def test_hud_leave_stops_the_map_timers_except_for_the_base(pe):
    """The HUD's leave reads the ENTERING mode (already pushed) and skips the stop for 0xA, 3 (the base screen) or 2."""
    b = rd(pe, 0x45CA62, 0x1B)
    assert b[:7] == bytes.fromhex("8B0485" + le(MODE_TABLE))                 # mov eax, [mode table + idx*4]
    assert b[7:22] == bytes.fromhex("83F80A7419" "83F8037414" "83F802740F")  # cmp 0xA / 3 / 2 -> skip
    assert calls_to(b, 0x45CA62, MAP_TIMERS_STOP) == [0x45CA78]


def test_base_leave_never_stops_the_map_timers(pe):
    body = rd(pe, 0x41DAD0, 0x41DC7F - 0x41DAD0)
    assert calls_to(body, 0x41DAD0, MAP_TIMERS_STOP) == []
