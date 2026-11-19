// pracxfocus_core.h -- the Win32 logic of pracxfocus.cpp, header-only so work\tests\pracxfocus_selftest.cpp can drive it
// against real windows without the game.
//
// PRACX gates its map wheel zoom, its wheel list-scrolling and its right-drag scroll on `GetFocus() == game hwnd`
// (refs\pracx\shared\pracx.cpp:1139, :1162, :1288), and never calls SetFocus itself; nor do the exes, prax.dll or
// ddraw.dll (none imports SetFocus). The engine's own edge-scroll (blink timer 0x50EB3D) and Thinker's wheel/drag
// (gui.cpp win_has_focus) read focus too, so they come back with it. Its Preferences panel
// (class "PRACXSettingsWnd", a WS_CHILD of the game window, pracxsettings.cpp:355) hands focus to whichever of its
// buttons is clicked, and closing it destroys that button. Windows then gives focus to the parent; Wine does not --
// its DestroyWindow reverts focus only when the hidden window IS the focus window (dlls\win32u\window.c show_window
// SW_HIDE), and wineserver clears focus to 0 when the focused button is freed (server\queue.c
// thread_input_cleanup_window). The game is left active with no focus, so the PRACX mouse features stay dead until a
// restart (issue longevity-vaccine #6). Separately, on every system Esc does nothing once a panel button has focus:
// the key goes to the button, which ignores it, and neither the panel's Esc handler nor PRACX's ever sees it.
#pragma once

#include <windows.h>
#include <cstring>

namespace pracxfocus {

constexpr char kPanelClass[] = "PRACXSettingsWnd";

// The PRACX Preferences panel `h` belongs to (the panel itself or one of its controls), or null.
inline HWND PanelOf(HWND h)
{
    for (int depth = 0; h && depth < 4; ++depth) {
        char cls[sizeof kPanelClass + 1] = {};
        if (GetClassNameA(h, cls, sizeof cls) && strcmp(cls, kPanelClass) == 0) return h;
        if (!(GetWindowLongA(h, GWL_STYLE) & WS_CHILD)) return nullptr;   // reached a top-level window
        h = GetParent(h);
    }
    return nullptr;
}

// True when the game window is the thread's active window, usable, and nobody has keyboard focus -- the state Wine
// leaves after the panel closes. Not while a panel is open (its controls own focus then), while minimised or disabled
// (Windows' SetFocus refuses both anyway; Wine's behaviour there is not measured, so they are excluded explicitly).
inline bool FocusLost(HWND game)
{
    return game && GetFocus() == nullptr && GetActiveWindow() == game && IsWindow(game) && !IsIconic(game) &&
           IsWindowEnabled(game) && !FindWindowExA(game, nullptr, kPanelClass, nullptr);
}

enum : int { kNone = 0, kEscRouted = 1, kFocusRestored = 2 };

// Runs on every message the game thread dequeues, before it is dispatched. Returns what it did.
inline int OnMessage(MSG* m, HWND game)
{
    int did = kNone;
    // Esc on a control inside the panel: hand the key to the panel, whose own handler closes it the way Cancel does
    // (pracxsettings.cpp WndProc, WM_KEYDOWN VK_ESCAPE -> DestroyWindow).
    if (m->message == WM_KEYDOWN && m->wParam == VK_ESCAPE && m->hwnd) {
        const HWND panel = PanelOf(m->hwnd);
        if (panel && panel != m->hwnd) {
            m->hwnd = panel;
            did |= kEscRouted;
        }
    }
    if (FocusLost(game)) {
        SetFocus(game);
        if (GetFocus() == game) did |= kFocusRestored;
    }
    return did;
}

} // namespace pracxfocus
