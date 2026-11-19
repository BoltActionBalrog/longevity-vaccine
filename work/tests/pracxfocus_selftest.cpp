// Harness for src\uimod\src\pracxfocus_core.h (built by test_pracxfocus.py). Real Win32 windows on this thread, laid out
// like PRACX's: a top-level "game" window, a WS_CHILD panel of class PRACXSettingsWnd whose WM_KEYDOWN Esc destroys it
// (pracxsettings.cpp WndProc), and buttons inside the panel. Windows sit off-screen. Prints one `<case>=ok` or
// `<case>=FAIL <detail>` line per case; `wine` emulates Wine by clearing focus after the panel is destroyed, which is
// what wineserver's thread_input_cleanup_window leaves when the focused button is freed.
#include "../../src/uimod/src/pracxfocus_core.h"

#include <cstdio>

#pragma comment(lib, "user32.lib")

using namespace pracxfocus;

static HWND g_game = nullptr;

static LRESULT CALLBACK PanelProc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_KEYDOWN && wp == VK_ESCAPE) { DestroyWindow(h); return 0; }
    return DefWindowProcA(h, msg, wp, lp);
}

static HWND Make(const char* cls, DWORD style, HWND parent, int x, int y, int w, int h)
{
    return CreateWindowExA(0, cls, "", style, x, y, w, h, parent, nullptr, GetModuleHandleA(nullptr), nullptr);
}

static HWND OpenPanel(HWND* button, HWND* button2 = nullptr)
{
    HWND panel = Make(kPanelClass, WS_CHILD | WS_VISIBLE, g_game, 10, 10, 640, 280);
    *button = Make("BUTTON", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, panel, 10, 10, 80, 24);
    if (button2) *button2 = Make("BUTTON", WS_CHILD | WS_VISIBLE | BS_CHECKBOX, panel, 100, 10, 80, 24);
    return panel;
}

static MSG Msg(HWND h, UINT message, WPARAM wp)
{
    MSG m = {};
    m.hwnd = h; m.message = message; m.wParam = wp;
    return m;
}

static void Report(const char* name, bool ok, const char* detail)
{
    printf("%s=%s%s%s\n", name, ok ? "ok" : "FAIL", ok ? "" : " ", ok ? "" : detail);
}

// Every case starts clean: no panel a previous (failed) case left behind, the game window active and focused.
static void ResetGameFocus()
{
    while (HWND left = FindWindowExA(g_game, nullptr, kPanelClass, nullptr)) DestroyWindow(left);
    SetActiveWindow(g_game);
    SetFocus(g_game);
}

int main()
{
    WNDCLASSA wc = {};
    wc.lpfnWndProc = PanelProc;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.lpszClassName = kPanelClass;
    if (!RegisterClassA(&wc)) { printf("setup=FAIL RegisterClass %lu\n", GetLastError()); return 1; }
    g_game = Make("STATIC", WS_OVERLAPPEDWINDOW | WS_VISIBLE, nullptr, -20000, -20000, 800, 600);
    HWND other = Make("STATIC", WS_OVERLAPPEDWINDOW | WS_VISIBLE, nullptr, -20000, -19000, 300, 200);
    ResetGameFocus();
    if (GetActiveWindow() != g_game || GetFocus() != g_game) {
        printf("setup=FAIL the game window could not be made active/focused (active %p focus %p)\n",
               static_cast<void*>(GetActiveWindow()), static_cast<void*>(GetFocus()));
        return 1;
    }
    printf("setup=ok\n");
    char d[200];

    {   // focus cleared while the game window is active -> given back, reported
        ResetGameFocus();
        SetFocus(nullptr);
        MSG m = Msg(g_game, WM_MOUSEWHEEL, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "did %d focus %p", did, static_cast<void*>(GetFocus()));
        Report("restore", did == kFocusRestored && GetFocus() == g_game, d);
    }
    {   // focus already on the game window -> nothing
        ResetGameFocus();
        MSG m = Msg(g_game, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "did %d", did);
        Report("focused_noop", did == kNone && GetFocus() == g_game, d);
    }
    {   // focus on some other child of the game window -> left alone
        ResetGameFocus();
        HWND child = Make("BUTTON", WS_CHILD | WS_VISIBLE, g_game, 0, 0, 20, 20);
        SetFocus(child);
        MSG m = Msg(child, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "did %d focus %p", did, static_cast<void*>(GetFocus()));
        Report("other_child_untouched", did == kNone && GetFocus() == child, d);
        DestroyWindow(child);
    }
    {   // a panel is open and focus is empty -> not ours to change
        ResetGameFocus();
        HWND button;
        HWND panel = OpenPanel(&button);
        SetFocus(nullptr);
        MSG m = Msg(g_game, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "did %d focus %p", did, static_cast<void*>(GetFocus()));
        Report("panel_open_noop", did == kNone && GetFocus() == nullptr, d);
        DestroyWindow(panel);
    }
    {   // another top-level window is active -> the game window is not, nothing to restore
        SetActiveWindow(other);
        SetFocus(nullptr);
        MSG m = Msg(other, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "did %d active %p focus %p", did, static_cast<void*>(GetActiveWindow()), static_cast<void*>(GetFocus()));
        Report("other_active_noop", did == kNone && GetActiveWindow() == other && GetFocus() == nullptr, d);
    }
    {   // no game window yet (before the engine created it) -> nothing, no crash
        ResetGameFocus();
        SetFocus(nullptr);
        MSG m = Msg(g_game, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, nullptr);
        sprintf(d, "did %d", did);
        Report("no_game_noop", did == kNone && GetFocus() == nullptr, d);
    }
    {   // Esc on a focused panel button -> readdressed to the panel; dispatching it closes the panel (Windows then
        // hands focus to the game window by itself)
        ResetGameFocus();
        HWND button, check;
        HWND panel = OpenPanel(&button, &check);
        SetFocus(check);
        MSG m = Msg(check, WM_KEYDOWN, VK_ESCAPE);
        const int did = OnMessage(&m, g_game);
        const bool routed = m.hwnd == panel;
        DispatchMessageA(&m);
        sprintf(d, "did %d routed %d panel alive %d focus %p", did, routed, IsWindow(panel), static_cast<void*>(GetFocus()));
        Report("esc_routed", did == kEscRouted && routed && !IsWindow(panel) && GetFocus() == g_game, d);
    }
    {   // Esc addressed to the panel itself, or to the game window -> unchanged
        ResetGameFocus();
        HWND button;
        HWND panel = OpenPanel(&button);
        MSG a = Msg(panel, WM_KEYDOWN, VK_ESCAPE);
        MSG b = Msg(g_game, WM_KEYDOWN, VK_ESCAPE);
        const int da = OnMessage(&a, g_game), db = OnMessage(&b, g_game);
        sprintf(d, "did %d/%d hwnd %p/%p", da, db, static_cast<void*>(a.hwnd), static_cast<void*>(b.hwnd));
        Report("esc_elsewhere_unchanged", da == kNone && db == kNone && a.hwnd == panel && b.hwnd == g_game, d);
        DestroyWindow(panel);
    }
    {   // other keys on a panel button -> unchanged (Space still presses it)
        ResetGameFocus();
        HWND button;
        HWND panel = OpenPanel(&button);
        SetFocus(button);
        MSG m = Msg(button, WM_KEYDOWN, VK_SPACE);
        MSG u = Msg(button, WM_KEYUP, VK_ESCAPE);
        const int dm = OnMessage(&m, g_game), du = OnMessage(&u, g_game);
        sprintf(d, "did %d/%d", dm, du);
        Report("other_keys_unchanged", dm == kNone && du == kNone && m.hwnd == button && u.hwnd == button, d);
        DestroyWindow(panel);
    }
    {   // Wine, EMULATED: Windows destroys the panel and hands focus to the game window; then focus is cleared by hand to
        // reach the state Wine leaves (wineserver thread_input_cleanup_window). Not evidence about Wine itself.
        ResetGameFocus();
        HWND button;
        HWND panel = OpenPanel(&button);
        SetFocus(button);
        DestroyWindow(panel);
        SetFocus(nullptr);
        const bool emulated = GetFocus() == nullptr && GetActiveWindow() == g_game;
        MSG m = Msg(g_game, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "emulated %d did %d focus %p", emulated, did, static_cast<void*>(GetFocus()));
        Report("wine_close_restored", emulated && did == kFocusRestored && GetFocus() == g_game, d);
    }
    // The minimised and disabled guards are asserted on FocusLost itself: Windows' SetFocus refuses an iconic or a
    // disabled window anyway, so OnMessage's outcome alone would pass with the guard removed (audit 2026-11-14).
    {   // minimised game window, still the active window with no focus -> not "lost"
        ResetGameFocus();
        ShowWindow(g_game, SW_SHOWMINNOACTIVE);
        SetActiveWindow(g_game);
        SetFocus(nullptr);
        const bool pre = IsIconic(g_game) && GetActiveWindow() == g_game && GetFocus() == nullptr;
        const bool lost = FocusLost(g_game);
        MSG m = Msg(g_game, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "pre %d lost %d did %d", pre, lost, did);
        Report("minimised_noop", pre && !lost && did == kNone, d);
        ShowWindow(g_game, SW_RESTORE);
    }
    {   // disabled game window (a modal owner), active with no focus -> not "lost"
        ResetGameFocus();
        SetFocus(nullptr);
        EnableWindow(g_game, FALSE);
        SetActiveWindow(g_game);
        const bool pre = !IsWindowEnabled(g_game) && GetActiveWindow() == g_game && GetFocus() == nullptr;
        const bool lost = FocusLost(g_game);
        MSG m = Msg(g_game, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, g_game);
        sprintf(d, "pre %d lost %d did %d", pre, lost, did);
        Report("disabled_noop", pre && !lost && did == kNone, d);
        EnableWindow(g_game, TRUE);
    }
    {   // a stale handle (the window is gone) -> not "lost", no crash
        ResetGameFocus();
        HWND gone = Make("STATIC", WS_OVERLAPPEDWINDOW, nullptr, -20000, -20000, 50, 50);
        DestroyWindow(gone);
        SetFocus(nullptr);
        const bool lost = FocusLost(gone);
        MSG m = Msg(g_game, WM_MOUSEMOVE, 0);
        const int did = OnMessage(&m, gone);
        sprintf(d, "lost %d did %d", lost, did);
        Report("stale_hwnd_noop", !lost && did == kNone, d);
    }
    DestroyWindow(other);
    DestroyWindow(g_game);
    return 0;
}
