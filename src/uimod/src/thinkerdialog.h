// thinkerdialog.h -- the three-button dialog of the Thinker Mod startup check (thinkerversion.cpp): an in-memory
// dialog template, its procedure, and OUR OWN modal loop. Windows-only, no detection, no ini, no spawn, so
// work\tests\thinkerdialog_selftest.cpp can create the real dialog (never shown) and drive the production loop
// body with synthetic messages.
//
// Why not MessageBox: it cannot label its buttons, and the player needs three that say what they do.
// Why not DialogBoxIndirectParam: the dialog appears before the first game window, while the player may still be
// mashing Enter or Space through the intro. The loop here ignores all input for `guardMs`, and after that still
// drops auto-repeat key-downs (lParam bit 30) until a fresh press, so a held key can never answer. The buttons stay
// enabled throughout: disabled buttons would leave the dialog without a focused control (audit 2026-11-14).
//
// The close box (and Alt+F4, and Close on the system menu: all one SC_CLOSE -> WM_CLOSE path) is a fourth answer,
// kClosed: the caller ends the process, starting neither the game nor the installer (user 2026-11-14). Esc stays a
// no-op (user 2026-11-14): players press it repeatedly to skip the intro, and it must never quit the game. Esc reaches
// the procedure as IDCANCEL, never as WM_CLOSE, so the two cannot be confused.
#pragma once

#include <windows.h>
#include <string>
#include <vector>

namespace thinkerdialog {

constexpr int kIconId = 200;
constexpr int kTextId = 201;
constexpr int kButtons = 3;
constexpr int kQuit = -1;                // WM_QUIT arrived while the dialog was up: nothing was chosen
constexpr int kClosed = -2;              // the player closed the dialog (close box, Alt+F4, system menu Close)

struct Spec {
    const wchar_t* title = L"";
    const wchar_t* text = L"";
    const wchar_t* captions[kButtons] = { L"", L"", L"" };
    int ids[kButtons] = { 0, 0, 0 };
    int defaultId = 0;
    DWORD guardMs = 400;                 // all input is ignored for this long after creation
    bool foreground = true;              // DS_SETFOREGROUND + WS_EX_TOPMOST (off under test: no focus theft)
    bool visible = true;
    bool systemDpi = true;               // create under a system-DPI-aware thread context when the API exists
    ULONGLONG (*clock)() = nullptr;      // null = GetTickCount64 (a test supplies its own)
};

struct Ctx {
    const Spec* spec = nullptr;
    HWND dlg = nullptr;
    ULONGLONG guardUntil = 0;
    int result = 0;
    bool done = false;
};

inline ULONGLONG Now(const Ctx& c) { return c.spec->clock ? c.spec->clock() : GetTickCount64(); }

inline bool IsButtonId(const Spec& s, int id)
{
    for (int i = 0; i < kButtons; ++i) if (s.ids[i] == id) return true;
    return false;
}

// ---- template ------------------------------------------------------------------------------------------------

namespace detail {

inline void Align4(std::vector<BYTE>& b) { while (b.size() % 4) b.push_back(0); }
inline void PutW(std::vector<BYTE>& b, WORD v) { b.push_back(static_cast<BYTE>(v & 0xFF)); b.push_back(static_cast<BYTE>(v >> 8)); }
inline void PutD(std::vector<BYTE>& b, DWORD v) { PutW(b, static_cast<WORD>(v & 0xFFFF)); PutW(b, static_cast<WORD>(v >> 16)); }
inline void PutS(std::vector<BYTE>& b, const wchar_t* s) { for (; *s; ++s) PutW(b, static_cast<WORD>(*s)); PutW(b, 0); }

// One DLGITEMTEMPLATE: `atom` is the predefined class (0x0080 button, 0x0082 static).
inline void Item(std::vector<BYTE>& b, DWORD style, WORD id, WORD atom, const wchar_t* text)
{
    Align4(b);
    PutD(b, style);
    PutD(b, 0);                                   // extended style
    PutW(b, 0); PutW(b, 0); PutW(b, 10); PutW(b, 10);   // x, y, cx, cy: laid out in WM_INITDIALOG
    PutW(b, id);
    PutW(b, 0xFFFF); PutW(b, atom);
    PutS(b, text);
    PutW(b, 0);                                   // no creation data
}

} // namespace detail

// The DLGTEMPLATE for `spec`: an icon, the text and three buttons. WS_SYSMENU gives the close box (DS_MODALFRAME
// keeps the caption free of an icon).
inline std::vector<BYTE> BuildTemplate(const Spec& spec)
{
    using namespace detail;
    std::vector<BYTE> b;
    DWORD style = WS_POPUP | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME | DS_SETFONT;
    if (spec.foreground) style |= DS_SETFOREGROUND;
    if (spec.visible) style |= WS_VISIBLE;
    PutD(b, style);
    PutD(b, spec.foreground ? WS_EX_TOPMOST : 0);
    PutW(b, 2 + kButtons);                        // cdit
    PutW(b, 0); PutW(b, 0); PutW(b, 100); PutW(b, 50);
    PutW(b, 0);                                   // no menu
    PutW(b, 0);                                   // the dialog class
    PutS(b, spec.title);
    PutW(b, 9);                                   // DS_SETFONT: point size, face
    PutS(b, L"Segoe UI");
    // WS_GROUP on the first static as well as on the first button: the buttons are then a closed group, so the arrow
    // keys wrap from the last button to the first (and back) as in a message box, instead of stopping at the statics.
    Item(b, WS_CHILD | WS_VISIBLE | SS_ICON | WS_GROUP, static_cast<WORD>(kIconId), 0x0082, L"");
    Item(b, WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX, static_cast<WORD>(kTextId), 0x0082, spec.text);
    for (int i = 0; i < kButtons; ++i) {
        DWORD s = WS_CHILD | WS_VISIBLE | WS_TABSTOP | (spec.ids[i] == spec.defaultId ? BS_DEFPUSHBUTTON : BS_PUSHBUTTON);
        if (i == 0) s |= WS_GROUP;
        Item(b, s, static_cast<WORD>(spec.ids[i]), 0x0080, spec.captions[i]);
    }
    Align4(b);
    return b;
}

// ---- layout (pixels, from the dialog's own font) --------------------------------------------------------------

inline void Layout(HWND dlg, const Spec& spec)
{
    RECT du = { 0, 0, 4, 8 };
    MapDialogRect(dlg, &du);
    const int bx = du.right ? du.right : 6, by = du.bottom ? du.bottom : 13;
    const int margin = MulDiv(7, bx, 4), gap = MulDiv(7, bx, 4), btnGap = MulDiv(4, bx, 4);
    const int icon = GetSystemMetrics(SM_CXICON);
    const int textW = MulDiv(300, bx, 4);
    const int btnH = MulDiv(14, by, 8);
    int btnW = MulDiv(50, bx, 4), textH = by;

    HFONT font = reinterpret_cast<HFONT>(SendMessageW(dlg, WM_GETFONT, 0, 0));
    if (HDC dc = GetDC(dlg)) {
        HGDIOBJ old = font ? SelectObject(dc, font) : nullptr;
        RECT r = { 0, 0, textW, 0 };
        DrawTextW(dc, spec.text, -1, &r, DT_CALCRECT | DT_WORDBREAK | DT_NOPREFIX | DT_EXPANDTABS);
        textH = r.bottom + 2;                     // the static's own wrap may differ by a pixel row
        for (int i = 0; i < kButtons; ++i) {
            SIZE sz = { 0, 0 };
            GetTextExtentPoint32W(dc, spec.captions[i], lstrlenW(spec.captions[i]), &sz);
            const int w = sz.cx + MulDiv(12, bx, 4);
            if (w > btnW) btnW = w;
        }
        if (old) SelectObject(dc, old);
        ReleaseDC(dlg, dc);
    }

    const int buttonsW = kButtons * btnW + (kButtons - 1) * btnGap;
    int contentW = icon + gap + textW;
    if (buttonsW > contentW) contentW = buttonsW;
    const int bodyH = textH > icon ? textH : icon;
    const int clientW = 2 * margin + contentW;
    const int clientH = margin + bodyH + gap + btnH + margin;

    SetWindowPos(GetDlgItem(dlg, kIconId), nullptr, margin, margin, icon, icon, SWP_NOZORDER | SWP_NOACTIVATE);
    SetWindowPos(GetDlgItem(dlg, kTextId), nullptr, margin + icon + gap, margin, contentW - icon - gap, textH,
                 SWP_NOZORDER | SWP_NOACTIVATE);
    int x = clientW - margin - buttonsW;
    for (int i = 0; i < kButtons; ++i, x += btnW + btnGap)
        SetWindowPos(GetDlgItem(dlg, spec.ids[i]), nullptr, x, margin + bodyH + gap, btnW, btnH, SWP_NOZORDER | SWP_NOACTIVATE);

    RECT wr = { 0, 0, clientW, clientH };
    AdjustWindowRectEx(&wr, static_cast<DWORD>(GetWindowLongPtrW(dlg, GWL_STYLE)), FALSE,
                       static_cast<DWORD>(GetWindowLongPtrW(dlg, GWL_EXSTYLE)));
    const int w = wr.right - wr.left, h = wr.bottom - wr.top;
    RECT work = { 0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN) };
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);          // the PRIMARY monitor: DDrawCompat makes the process
    int px = work.left + ((work.right - work.left) - w) / 2;      // per-monitor aware, and that does not rescale a
    int py = work.top + ((work.bottom - work.top) - h) / 2;       // dialog on a monitor at another scale
    if (px < work.left) px = work.left;
    if (py < work.top) py = work.top;
    SetWindowPos(dlg, nullptr, px, py, w, h, SWP_NOZORDER | SWP_NOACTIVATE);
}

// ---- procedure and loop ---------------------------------------------------------------------------------------

inline INT_PTR CALLBACK Proc(HWND dlg, UINT msg, WPARAM wp, LPARAM lp)
{
    Ctx* c = reinterpret_cast<Ctx*>(GetWindowLongPtrW(dlg, DWLP_USER));
    switch (msg) {
    case WM_INITDIALOG:
        c = reinterpret_cast<Ctx*>(lp);
        SetWindowLongPtrW(dlg, DWLP_USER, lp);
        c->dlg = dlg;
        Layout(dlg, *c->spec);
        // MAKEINTRESOURCEW(32515) is IDI_WARNING, spelled wide so the header builds with or without UNICODE
        SendDlgItemMessageW(dlg, kIconId, STM_SETICON, reinterpret_cast<WPARAM>(LoadIconW(nullptr, MAKEINTRESOURCEW(32515))), 0);
        SendMessageW(dlg, DM_SETDEFID, static_cast<WPARAM>(c->spec->defaultId), 0);
        SetFocus(GetDlgItem(dlg, c->spec->defaultId));
        return FALSE;                             // focus is set: the default button has it from the first frame
    case WM_COMMAND:
        // !done: the first answer wins (two SENT answers can be handled inside one GetMessage)
        if (c && !c->done && HIWORD(wp) == BN_CLICKED && IsButtonId(*c->spec, LOWORD(wp)) && Now(*c) >= c->guardUntil) {
            c->result = LOWORD(wp);
            c->done = true;
            // The answer may arrive by a SENT message (an assistive or automation tool's BM_CLICK), which is handled
            // inside GetMessage without returning from it: wake the loop, as EndDialog does.
            PostMessageW(dlg, WM_NULL, 0, 0);
        }
        return TRUE;                              // IDOK / IDCANCEL (Enter with no default, Esc) are swallowed too
    case WM_CLOSE:
        // The close box, Alt+F4, system menu Close (DefWindowProc turns their SC_CLOSE into this). Inside the guard
        // it is ignored like any other answer (the loop also drops non-client presses then, so a press on the close
        // box inside the guard cannot complete after it).
        if (c && !c->done && Now(*c) >= c->guardUntil) {
            c->result = kClosed;
            c->done = true;
            PostMessageW(dlg, WM_NULL, 0, 0);
        }
        return TRUE;                              // never DefDlgProc's: it would turn this into IDCANCEL
    }
    return FALSE;
}

// True when the loop must not let this message through.
inline bool DropMessage(const Ctx& c, const MSG& m)
{
    const bool key = m.message == WM_KEYDOWN || m.message == WM_KEYUP || m.message == WM_CHAR ||
                     m.message == WM_SYSKEYDOWN || m.message == WM_SYSKEYUP || m.message == WM_SYSCHAR;
    const bool click = m.message == WM_LBUTTONDOWN || m.message == WM_LBUTTONUP || m.message == WM_LBUTTONDBLCLK;
    // non-client presses: the close box (its press starts DefWindowProc's own tracking loop, which would deliver the
    // close after the guard) and the caption's system menu (right click)
    const bool ncPress = m.message == WM_NCLBUTTONDOWN || m.message == WM_NCLBUTTONDBLCLK ||
                         m.message == WM_NCRBUTTONDOWN || m.message == WM_NCRBUTTONUP;
    if (Now(c) < c.guardUntil) return key || click || ncPress;
    if ((m.message == WM_KEYDOWN || m.message == WM_SYSKEYDOWN) && (m.lParam & (1L << 30))) return true;   // auto-repeat
    return false;
}

// The loop body: the production path, also driven by the self-test with synthetic messages.
inline void Step(Ctx& c, MSG& m)
{
    if (DropMessage(c, m)) return;
    if (!IsDialogMessageW(c.dlg, &m)) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
}

// Creates the dialog; null on failure. `c` must outlive the window.
inline HWND Create(const Spec& spec, Ctx* c, HINSTANCE inst)
{
    c->spec = &spec;
    c->result = 0;
    c->done = false;
    c->guardUntil = ~0ull;                        // nothing answers while the window is being built
    const std::vector<BYTE> tmpl = BuildTemplate(spec);
    const HWND dlg = CreateDialogIndirectParamW(inst, reinterpret_cast<LPCDLGTEMPLATEW>(tmpl.data()), nullptr, Proc,
                                                reinterpret_cast<LPARAM>(c));
    c->guardUntil = Now(*c) + spec.guardMs;       // the guard runs from the moment the dialog EXISTS, not from before
    return dlg;
}

// Shows the dialog and returns the chosen button id, kClosed when the player closed it, 0 when it could not be
// created (`*error` then holds the creation's GetLastError), kQuit on WM_QUIT.
inline int Run(const Spec& spec, HINSTANCE inst, DWORD* error = nullptr)
{
    if (error) *error = 0;
    // DDrawCompat has made the process per-monitor aware; a system-aware thread context lets Windows scale the
    // dialog. Resolved at run time (Windows 10 1607+); absent, the dialog is simply created as it is.
    typedef HANDLE (WINAPI* FSetCtx)(HANDLE);
    FSetCtx setCtx = nullptr;
    HANDLE oldCtx = nullptr;
    if (spec.systemDpi) {
        const HMODULE user32 = GetModuleHandleW(L"user32.dll");
        setCtx = user32 ? reinterpret_cast<FSetCtx>(reinterpret_cast<void*>(GetProcAddress(user32, "SetThreadDpiAwarenessContext"))) : nullptr;
        if (setCtx) oldCtx = setCtx(reinterpret_cast<HANDLE>(static_cast<LONG_PTR>(-2)));   // DPI_AWARENESS_CONTEXT_SYSTEM_AWARE
    }
    Ctx c;
    const HWND dlg = Create(spec, &c, inst);
    if (!dlg && error) *error = GetLastError();   // before anything else can overwrite it
    int result = 0;
    if (dlg) {
        MSG m;
        while (!c.done) {
            const BOOL r = GetMessageW(&m, nullptr, 0, 0);
            if (r <= 0) {
                if (r == 0) PostQuitMessage(static_cast<int>(m.wParam));   // hand the quit on to the game's loop
                c.result = kQuit;
                break;
            }
            Step(c, m);
        }
        result = c.result;
        DestroyWindow(dlg);
    }
    if (setCtx && oldCtx) setCtx(oldCtx);
    return result;
}

} // namespace thinkerdialog
