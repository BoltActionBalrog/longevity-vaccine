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
        if ((m->message == WM_KEYDOWN || m->message == WM_KEYUP) && (m->wParam == VK_UP || m->wParam == VK_DOWN) &&
            m->lParam == 0 && m->hwnd) {
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
        if (m->message == WM_MOUSEWHEEL && m->hwnd) {
            POINT p = { static_cast<short>(LOWORD(m->lParam)), static_cast<short>(HIWORD(m->lParam)) };
            const bool inClient = ScreenToClient(m->hwnd, &p) != 0;
            VidModeClientToBackbuffer(m->hwnd, &p);   // window rects are backbuffer coords; the client is stretched when windowed
            const BYTE* under = inClient ? ModalUnder(p) : nullptr;
            if (under) {
                int delta = GET_WHEEL_DELTA_WPARAM(m->wParam) + g_accum;
                g_accum = delta % WHEEL_DELTA;
                delta /= WHEEL_DELTA;
                const WPARAM key = delta >= 0 ? VK_UP : VK_DOWN;
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
