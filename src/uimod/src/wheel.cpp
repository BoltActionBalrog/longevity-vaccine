// uimod mouse wheel over modal lists.
//
// The game has no wheel support of its own. PRACX's WndProc turns a notch into posted
// VK_UP/VK_DOWN pairs with lParam 0 (which the patcher's wheel_scroll thunks at WinProc's
// `call Win_get_active_target` sites convert into a chevron press on the modal's scrollbar) --
// but ONLY while the world map is not showing; with the map up it zooms the map instead, even
// when a list popup (scenario editor pickers, etc.) sits on top of it and the cursor is over it.
//
// Fix: a thread-local WH_GETMESSAGE hook sees WM_MOUSEWHEEL before any WndProc. When the top
// modal is one of the scrollable classes and the cursor is inside its window rect, the notch is
// consumed (message -> WM_NULL) and the same synthetic arrow pairs PRACX would have posted are
// posted instead. Everything else (cursor off the popup, no modal) reaches PRACX untouched, so
// map zoom keeps working around the popup.
//
// No code is patched and only always-mapped .data globals are read, so this is identical on the
// PRACX-patched and the unpatched exe (there the arrows are plain selection moves).

#include "wheel.h"
#include "debugdump.h"
#include "vidmode.h"
#include "winlines.h"
#include "modernctl.h"
#include "prefs.h"
#include "update.h"

#include <windows.h>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>

void UimodLog(const char* msg);
void UimodDbg(const char* msg);

namespace {

constexpr uintptr_t kImageBase = 0x400000;
constexpr uintptr_t kModalTop  = 0x9B7AE0;   // Win* top modal
constexpr uintptr_t kBasePop   = 0x9B8D7C;   // Win* g_current_basepop (overrides the modal top)
constexpr size_t    kWinRect   = 0x13C;      // Win +0x13C RECT, screen (= game client) coords on top-levels

// The classes the wheel_scroll thunks know how to scroll (assemble_dw.py asm_wheel) + the two
// remaining Popup-family vtables (thunk_rail_gate's set).
const uint32_t kScrollable[] = {
    0x6695C8, 0x66A8A8, 0x66CB60, 0x66DD84,   // Popup family
    0x66B2B8,                                 // PartPicker
    0x66A250,                                 // ProdPicker
    0x669EC8,                                 // FileDlg
    0x66ADC8,                                 // TextScroll
    0x66C3D8,                                 // PrefSub
    0x66CE5C,                                 // NetTechWin (tech breakthrough; t_ntw_wheel_down picks the TextScroll)
    0x66A40C,                                 // BaseWin (base screen; t_bw_wheel_down picks the facilities / supported list)
    0x66B634,                                 // DiploWin (multiplayer negotiation; t_dw_wheel_down scrolls the chat log)
};
// The negotiation window is modal, and its one scrollable (the chat log) sits in the console strip OUTSIDE the
// window's own rect (the chat TextScroll is parented to MainWin): no rect test, like the base screen.
constexpr uint32_t kDiploWinVtbl = 0x66B634;
constexpr uint32_t kBaseWinVtbl = 0x66A40C;   // the base screen is full-screen (window + console strip): no rect test
constexpr uintptr_t kBaseWin   = 0x6A7628;   // BaseWin_g static instance
constexpr uintptr_t kMainWin   = 0x7AE820;   // MainWin_g (the console strip's parent; strip rects are MainWin-local)
constexpr size_t    kWinShown  = 0x9C;       // Win +0x9C bit0 = shown (Win_is_visible 0x5F7E90)
constexpr uintptr_t kGetActiveTarget = 0x5F6A50;   // Win_get_active_target: cdecl, no args; the Win* WinProc hands a key to
                                                   // (modal top / basepop, else the focus [0x9B7AC4] / default focus [0x9B7AEC],
                                                   // then its +0xA8 focus child when visible); 0 = the key goes nowhere
constexpr uint32_t  kConsoleWinVtbl = 0x66EC18;   // the Console's own main window (Console+0x23D94): its key handler moves units
// The full-screen interfaces the map hides behind: the Design Workshop, the HQ reports and the Datalinks. PRACX zooms
// the map on a notch whenever its IsMapShowing() is true: map timers running, base screen hidden, SocialWin / TutWin
// hidden -- it never looks for these screens. Opened from the map, the HUD's leave stops the map timers (call 0x50F440
// @0x45CA78), so PRACX posts arrows and the screen scrolls; opened from a BASE (the workshop, or the Datalinks through
// a picker's HELP), the HUD skipped that stop (next mode 3 = base) and the base's leave never stops them, so the notch
// zoomed the map behind the screen (PRACX bug, user 2026-11-13). While one of them is the live interface, a notch no
// list under the cursor takes is posted as the same arrow pairs PRACX posts on the map path.
// The live interface is the top of the engine's mode stack (SubInterface_set_iface_mode 0x45D310 pushes the entering
// interface's mode id, iface+4, before the leaving one's on_mode(0); SubInterface_release_iface_mode pops it).
constexpr uintptr_t kIfaceModeTable = 0x7AE778;   // int[] mode stack; [g_iface_mode_idx] = the live interface's mode id
constexpr uintptr_t kIfaceModeIdx   = 0x7D392C;   // g_iface_mode_idx
constexpr uintptr_t kIfacePtrTable  = 0x7AE7F0;   // SubInterface* per mode id (each screen's build stores itself there)
constexpr int32_t   kIfaceModeSlots = static_cast<int32_t>((kIfacePtrTable - kIfaceModeTable) / 4);   // the stack's room
constexpr int32_t   kMapHidingModes[] = {
    1,   // Design Workshop (DesignWin_g 0x71F2B0 + 0xA14)
    5,   // HQ reports (ReportIf)
    8,   // Datalinks (DatalinkWin_g 0x703EA0 + 0xA14)
};
// Captured ONLY when PRACX would otherwise zoom: its m_fGlobalTimersEnabled is set by its thunk on the map blink
// timer's start (call @0x50F3E6, the only start of Time 0x915688) and cleared on the stop function 0x50F440 (which
// stops 0x939EB0 then 0x915688, the only stop), and its wheel handler acts only while GetFocus() is the game window.
// Opened from the map (timers stopped), PRACX keeps posting the arrows itself, with its live Wheel Scroll setting.
constexpr uintptr_t kMapBlinkTimer = 0x915688;   // Time; +4 = the SetTimer / timeSetEvent id, nonzero while running
// The game's main window. A notch addressed to any other window (a control of PRACX's Preferences panel, a WS_CHILD of
// it, that holds focus or sits under the cursor) is that window's own: never captured or turned into arrows.
constexpr uintptr_t kGameHwnd = 0x9B7B28;
// The workshop's unit row: DesignWin_on_key 0x439A20 scrolls it on VK_LEFT / VK_RIGHT (its arrow buttons 0x17 / 0x18)
// and has no case for VK_UP / VK_DOWN, so PRACX's posted up / down arrows never moved it. While the workshop itself is
// the key target (Win_get_active_target() == DesignWin_g, Thinker's own GW_Design test, gui.cpp current_window), a
// notch is posted as left / right pairs: up = left, down = right, Thinker's mapping (gui.cpp, WM_MOUSEWHEEL).
constexpr uintptr_t kDesignWin = 0x71F2B0;
// Thinker registers the game window's class proc first (its ModRegisterClassA; PRACX's wrapper then hands Thinker the
// class), so ModWinProc sees every notch before PRACX and, while the key target is not the map, posts the arrows
// itself (left / right in the workshop, up / down elsewhere) and never zooms. When the class proc lives in thinker.dll,
// the workshop and map-hiding fallbacks stand aside and Thinker keeps the wheel (user 2026-11-14: never override it).
constexpr char kThinkerDll[] = "thinker.dll";

HHOOK g_hook = nullptr;
int   g_lines = 1;      // PRACX ListScrollLines. PRACX's OWN default is 1 (pracxsettings.h
                        // DEFAULT_LIST_SCROLL_DELTA; `<DEFAULT>` in the ini keeps it) -- the
                        // earlier "3" here was a wrong assumption, so DLL-captured notches
                        // (popups, pickers, the base screen) scrolled three rows while the
                        // PRACX-posted ones (Datalinks, report screens) scrolled one (user
                        // 2026-09-22: one row per notch everywhere).
int   g_accum = 0;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}
template <typename T> T Rd(uintptr_t va) { return *reinterpret_cast<T*>(At(va)); }

// The live interface when it is one the map hides behind (its SubInterface) AND PRACX would zoom the map on this notch
// (see kMapBlinkTimer), or null.
const BYTE* MapHidingIfaceUp(HWND game)
{
    if (Rd<uint32_t>(kMapBlinkTimer + 4) == 0 || GetFocus() != game) return nullptr;
    const int32_t idx = Rd<int32_t>(kIfaceModeIdx);
    if (idx < 0 || idx >= kIfaceModeSlots) return nullptr;
    const int32_t mode = Rd<int32_t>(kIfaceModeTable + static_cast<uintptr_t>(idx) * 4);
    for (int32_t m : kMapHidingModes)
        if (m == mode) return Rd<const BYTE*>(kIfacePtrTable + static_cast<uintptr_t>(mode) * 4);
    return nullptr;
}

// True when the game window's class proc is Thinker's ModWinProc: Thinker's wheel handling runs before PRACX's.
bool ThinkerOwnsWheel(HWND game)
{
    const HMODULE thinker = GetModuleHandleA(kThinkerDll);
    if (!thinker) return false;
    const ULONG_PTR proc = GetClassLongPtrA(game, GCLP_WNDPROC);
    HMODULE owner = nullptr;
    const bool owns = proc && GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                                 GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                                 reinterpret_cast<LPCSTR>(proc), &owner) && owner == thinker;
    static int logged = -1;
    if (logged != static_cast<int>(owns)) {
        logged = static_cast<int>(owns);
        UimodLog(owns ? "[uimod] wheel: Thinker's window procedure takes the wheel first -> its workshop / Datalinks / "
                        "report scrolling is left to it\n"
                      : "[uimod] wheel: thinker.dll is loaded but the game window's procedure is not Thinker's -> uimod "
                        "handles the workshop / Datalinks / report wheel\n");
    }
    return owns;
}

// The Design Workshop when it is the key target and the game window has focus (where PRACX and Thinker act), or null.
const BYTE* WorkshopKeyTarget(HWND game)
{
    if (GetFocus() != game) return nullptr;
    const BYTE* t = reinterpret_cast<const BYTE* (__cdecl*)()>(At(kGetActiveTarget))();
    return (t && t == At(kDesignWin) && (t[kWinShown] & 1)) ? t : nullptr;
}

// The scrollable modal under `client` (game client coords), or null.
const BYTE* ModalUnder(POINT client)
{
    const BYTE* win = Rd<const BYTE*>(kBasePop);
    if (!win) win = Rd<const BYTE*>(kModalTop);
    if (!win) {
        // The base screen is NOT modal (g_modal_top stays 0 while it is open -- Frida-measured
        // 2026-09-22); it is "up" when BaseWin_g's Win+0x9C bit0 (the Win_is_visible flag) is set.
        // It covers the whole screen (window + console strip), so the notch is captured anywhere.
        const BYTE* basewin = At(kBaseWin);
        return (basewin[kWinShown] & 1) ? basewin : nullptr;
    }

    uint32_t vtbl;
    memcpy(&vtbl, win, sizeof vtbl);
    bool known = false;
    for (uint32_t v : kScrollable) known = known || v == vtbl;
    if (!known) return nullptr;
    if (!(win[kWinShown] & 1)) return nullptr;   // a modal that is not (yet / any more) visible is not a wheel target: the
                                                 // synthetic arrows would fall through to the map (user 2026-10-10: a notch
                                                 // in a new game's first seconds moved the unit up)
    if (vtbl == kBaseWinVtbl || vtbl == kDiploWinVtbl) return win;   // the map underneath is never interactable

    RECT r;
    memcpy(&r, win + kWinRect, sizeof r);
    return PtInRect(&r, client) ? win : nullptr;
}

// Arrow pairs per notch for the window under the cursor. The FORCES SUPPORTED bar (base screen
// console strip) has at most three positions -- one per unit ROW (draw_supported clamps its range
// to 0..2) -- so the ini's 3 pairs jumped it end to end in one notch (user 2026-09-22): over that
// strip panel (BaseWin_g+0x40B7C, MainWin-local device rect) a notch is exactly one row. Every
// other list, the facilities list included, keeps ListScrollLines.
int LinesFor(const BYTE* win, POINT client)
{
    uint32_t vtbl;
    memcpy(&vtbl, win, sizeof vtbl);
    if (vtbl != kBaseWinVtbl) return g_lines;
    RECT r;
    memcpy(&r, At(kBaseWin + 0x40B7C), sizeof r);
    POINT p = client;
    p.x -= Rd<int32_t>(kMainWin + 0x13C);
    p.y -= Rd<int32_t>(kMainWin + 0x140);
    return PtInRect(&r, p) ? 1 : g_lines;
}

LRESULT CALLBACK GetMsgProc(int code, WPARAM wParam, LPARAM lParam)
{
    if (code == HC_ACTION) DebugDumpPoll();   // developer diagnostic; a no-op unless enabled
    if (code == HC_ACTION) VidModePoll();
    if (code == HC_ACTION) WinLinesPoll();       // one GPU re-present per batch of engine window lines (winlines.cpp)
    if (code == HC_ACTION) UpdatePoll();        // one-shot: consume the update check's answer (update.cpp)
    if (code == HC_ACTION) PrefsBubblePoll();   // the Longevity sliders' value bubble ends with the press
    if (code == HC_ACTION && wParam == PM_REMOVE) {
        MSG* m = reinterpret_cast<MSG*>(lParam);
        UpdateOnMessage(m);                     // the update prompt's trigger message; a turn's first input
        ModernCtlFilterKey(m);                  // Shift/Ctrl auto-repeats (and any Shift/Ctrl while a map press is armed) are dropped
        ModernCtlPoll(m);                       // the hover move-to line goes when the map stops taking input
        // A synthetic arrow (lParam 0) that reaches the queue after its modal closed or stopped being the
        // engine's active target would be a REAL arrow to the map (a unit move): re-check at dequeue time.
        // The arrow is dropped only when WinProc would hand it to the Console's main window (the map: a
        // unit move) or to a window that is not shown; every visible UI screen keeps its arrows, whether
        // or not it is a modal wheel.cpp captures over the map (the exe's wheel thunks and PRACX's own
        // arrows serve the full-screen screens, which are not under ModalUnder: user 2026-10-10, wheel
        // scrolling on UI screens broke when the first version dropped everything without a modal).
        // Left / right (our workshop unit-row notches) get the same check: to the map they would move a unit west /
        // east. Only when Thinker does not own the wheel -- then every lParam-0 left / right is ours; Thinker's own are
        // left exactly as Thinker posts them.
        const bool upDown = m->wParam == VK_UP || m->wParam == VK_DOWN;
        const bool leftRight = m->wParam == VK_LEFT || m->wParam == VK_RIGHT;
        if ((m->message == WM_KEYDOWN || m->message == WM_KEYUP) && m->lParam == 0 && m->hwnd &&
            (upDown || (leftRight && !ThinkerOwnsWheel(Rd<HWND>(kGameHwnd))))) {
            POINT p;
            bool ok = false;
            if (GetCursorPos(&p) && ScreenToClient(m->hwnd, &p)) {
                VidModeClientToBackbuffer(m->hwnd, &p);
                ok = ModalUnder(p) != nullptr;
            }
            if (!ok) {
                const BYTE* t = reinterpret_cast<const BYTE* (__cdecl*)()>(At(kGetActiveTarget))();
                uint32_t vtbl = 0;
                if (t) memcpy(&vtbl, t, sizeof vtbl);
                ok = t && (t[kWinShown] & 1) && vtbl != kConsoleWinVtbl;
                if (!ok) {
                    char buf[160];
                    snprintf(buf, sizeof buf, "[uimod] wheel: synthetic arrow dropped: target %p vtbl %08X shown %d\n",
                             static_cast<const void*>(t), vtbl, t ? (t[kWinShown] & 1) : 0);
                    UimodDbg(buf);
                }
            }
            if (!ok) m->message = WM_NULL;
        }
        if (m->message == WM_MOUSEWHEEL && m->hwnd && m->hwnd == Rd<HWND>(kGameHwnd)) {   // see kGameHwnd
            POINT p = { static_cast<short>(LOWORD(m->lParam)), static_cast<short>(HIWORD(m->lParam)) };
            const bool inClient = ScreenToClient(m->hwnd, &p) != 0;
            VidModeClientToBackbuffer(m->hwnd, &p);   // window rects are backbuffer coords; the client is stretched when windowed
            const BYTE* under = inClient ? ModalUnder(p) : nullptr;
            bool unitRow = false;   // the workshop's unit row: left / right instead of up / down (see kDesignWin)
            if (!under && inClient && !ThinkerOwnsWheel(m->hwnd)) {   // under Thinker these screens are its own
                under = WorkshopKeyTarget(m->hwnd);
                unitRow = under != nullptr;
                if (!under) under = MapHidingIfaceUp(m->hwnd);   // never the map behind these screens (kMapHidingModes)
            }
            if (under) {
                int delta = GET_WHEEL_DELTA_WPARAM(m->wParam) + g_accum;
                g_accum = delta % WHEEL_DELTA;
                delta /= WHEEL_DELTA;
                const WPARAM key = unitRow ? (delta >= 0 ? VK_LEFT : VK_RIGHT) : (delta >= 0 ? VK_UP : VK_DOWN);
                for (int i = abs(delta) * LinesFor(under, p); i > 0; --i) {
                    PostMessageA(m->hwnd, WM_KEYDOWN, key, 0);   // lParam 0 = the synthetic-wheel signature
                    PostMessageA(m->hwnd, WM_KEYUP, key, 0);
                }
                m->message = WM_NULL;   // consumed: PRACX never sees it, the map does not zoom
            }
        }
    }
    return CallNextHookEx(g_hook, code, wParam, lParam);
}

// The exe's asm wheel heads (t_rw / t_dl / t_bw / t_ntw _wheel_down) hit-test the cursor against
// backbuffer rects. They read the cursor through the exe's GetCursorPos import, which PRACX hooks
// (pracx.cpp PRACXGetCursorPos): while m_fWindowed (Windowed / Borderless / Fullscreen without the mode
// switch) it ALREADY returns backbuffer coords (ScreenToClient + ClientToBackbuffer), so the heads' own
// ScreenToClient would subtract the window origin a second time. The heads call t_wheel_stc (a
// ScreenToClient drop-in) instead of the API; it calls through the cell g_wheel_stc when non-zero. Ours
// leaves an already-mapped point untouched and is the plain API otherwise (real-mode-switch Fullscreen:
// PRACX hands back raw screen coords).
constexpr uintptr_t kVA_WheelStc     = 0xA1E92C;   // pcave2+0x1292C t_wheel_stc (assemble_rw.WHEEL_STC)
constexpr uintptr_t kVA_WheelStcCell = 0xA1E93C;   // pcave2+0x1293C g_wheel_stc (assemble_rw.G_WHEEL_STC)
const BYTE kWheelStcBytes[] = {
    0xA1, 0x3C, 0xE9, 0xA1, 0x00,   // mov eax, [g_wheel_stc]
    0x85, 0xC0, 0x75, 0x05,         // test eax, eax / jnz go
    0xA1, 0xD4, 0x92, 0x66, 0x00,   // mov eax, [ScreenToClient IAT]
    0xFF, 0xE0,                     // go: jmp eax
};

BOOL WINAPI WheelScreenToClient(HWND hwnd, POINT* p)
{
    if (VidModeStretched()) return TRUE;   // = PRACX m_fWindowed: its GetCursorPos hook already mapped the point
    return ScreenToClient(hwnd, p);
}

void InstallWheelBackbufferCursor()
{
    uintptr_t lo, hi;
    const uintptr_t stc = reinterpret_cast<uintptr_t>(At(kVA_WheelStc));
    const uintptr_t cell = reinterpret_cast<uintptr_t>(At(kVA_WheelStcCell));
    if (!UimodPcave2Range(&lo, &hi) || stc < lo || cell + 4 > hi ||
        memcmp(At(kVA_WheelStc), kWheelStcBytes, sizeof kWheelStcBytes) != 0 || Rd<uint32_t>(kVA_WheelStcCell) != 0) {
        UimodLog("[uimod] wheel: t_wheel_stc not found -> exe wheel heads use plain client coords\n");
        return;
    }
    void* fn = reinterpret_cast<void*>(&WheelScreenToClient);
    memcpy(At(kVA_WheelStcCell), &fn, sizeof fn);   // .pcave2 is RWX; one aligned 4-byte store
    UimodLog("[uimod] wheel: exe wheel heads take PRACX's mapped cursor as-is when windowed\n");
}

} // namespace

void InstallWheelCapture()
{
    InstallWheelBackbufferCursor();

    char ini[MAX_PATH];
    GetModuleFileNameA(nullptr, ini, MAX_PATH);
    if (char* slash = strrchr(ini, '\\')) slash[1] = '\0';
    lstrcatA(ini, "Alpha Centauri.ini");
    const int lines = static_cast<int>(GetPrivateProfileIntA("PRACX", "ListScrollLines", 0, ini));
    if (lines >= 1 && lines <= 20) g_lines = lines;   // "<DEFAULT>" parses as 0 -> keep PRACX's default

    // Init() runs on the game's main thread (CRT startup table), which owns the game window.
    g_hook = SetWindowsHookExA(WH_GETMESSAGE, GetMsgProc, nullptr, GetCurrentThreadId());
    UimodLog(g_hook ? "[uimod] wheel: modal wheel capture installed\n"
                    : "[uimod] wheel: SetWindowsHookEx failed -> disabled\n");
}
