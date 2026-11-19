// pracxfocus.cpp -- PRACX's Preferences panel no longer leaves the map without its mouse wheel and right-drag (PRACX
// bug on Wine/Linux, issue longevity-vaccine #6), and Esc closes the panel after one of its buttons was clicked.
//
// The mechanism and the evidence are in pracxfocus_core.h. Reproduced on Windows by clearing the game thread's focus
// from outside (work\scripts\focus_probe.py drop): map wheel zoom and right-drag scroll died, right-click move,
// Datalinks wheel scrolling and hotkeys kept working, and giving the focus back restored everything.
//
// THE FIX: a thread-local WH_GETMESSAGE hook (like interludekey.cpp's) looks at each message the game thread
// dequeues. When the game window (g_game_hwnd 0x9B7B28) is active but nobody has focus and no PRACX panel is open,
// the game window gets focus back before the message is dispatched -- what Windows itself does when the panel
// closes. An Esc key-down addressed to a control inside the panel is readdressed to the panel. PRACX only: the panel
// that loses the focus is PRACX's, so without prax.dll nothing known leaves the game unfocused and the hook is not
// installed. No code bytes are patched.

#include "pracxfocus.h"
#include "pracxfocus_core.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>

void UimodLog(const char* msg);   // init.cpp

namespace {

constexpr uintptr_t kVA_g_game_hwnd = 0x009B7B28;   // HWND of the game's main window (exe .data, both exes)

HHOOK g_hook = nullptr;
int   g_restored = 0;
int   g_escRouted = 0;

HWND GameHwnd()
{
    return *reinterpret_cast<HWND*>(reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (kVA_g_game_hwnd - 0x400000));
}

LRESULT CALLBACK GetMsgProc(int code, WPARAM wParam, LPARAM lParam)
{
    if (code == HC_ACTION && wParam == PM_REMOVE) {
        const int did = pracxfocus::OnMessage(reinterpret_cast<MSG*>(lParam), GameHwnd());
        if ((did & pracxfocus::kFocusRestored) && ++g_restored <= 5) {
            char buf[200];
            _snprintf_s(buf, sizeof buf, _TRUNCATE,
                        "[uimod] pracxfocus: the game window had no keyboard focus -> given back (%d); PRACX's wheel "
                        "zoom and right-drag need it\n", g_restored);
            UimodLog(buf);
        }
        if ((did & pracxfocus::kEscRouted) && ++g_escRouted == 1)
            UimodLog("[uimod] pracxfocus: Esc on a PRACX Preferences button handed to the panel (it closes it)\n");
    }
    return CallNextHookEx(g_hook, code, wParam, lParam);
}

} // namespace

void InstallPracxFocusFix(bool pracx)
{
    if (!pracx) {
        UimodLog("[uimod] pracxfocus: no PRACX -> not needed\n");
        return;
    }
    g_hook = SetWindowsHookExA(WH_GETMESSAGE, GetMsgProc, nullptr, GetCurrentThreadId());
    UimodLog(g_hook ? "[uimod] pracxfocus: installed (the game window keeps keyboard focus after PRACX's Preferences "
                      "panel closes; Esc closes the panel)\n"
                    : "[uimod] pracxfocus: SetWindowsHookEx failed -> not installed\n");
}
