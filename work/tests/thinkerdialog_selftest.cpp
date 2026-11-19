// Self-test harness for thinkerdialog.h (tests\test_thinker_dialog.py builds and runs it once per module).
// Creates the REAL dialog template through CreateDialogIndirectParamW -- never visible, never foreground, a fake
// clock instead of a real 400 ms wait -- and drives the production loop body (thinkerdialog::Step) with synthetic
// messages. Prints one "PASS <name>" or "FAIL <name> <detail>" line per check; exit code 0 either way (pytest reads
// the lines).
#include <cstdio>
#include <string>

#include "../../src/uimod/src/thinkerdialog.h"

namespace {

using namespace thinkerdialog;

ULONGLONG g_now = 1000;
ULONGLONG FakeClock() { return g_now; }

void Check(const char* name, bool ok, const char* detail = "")
{
    std::printf("%s %s %s\n", ok ? "PASS" : "FAIL", name, ok ? "" : detail);
}

Spec MakeSpec(int defaultId)
{
    Spec s;
    s.title = L"Longevity Vaccine";
    s.text = L"Longevity Vaccine 9.9.9 was built for Thinker Mod 5.5. This game is running Thinker Mod 5.6 & more. "
             L"This combination has not been tested, and the game may not work correctly.\n\n"
             L"Choose 'Update now' to open the Longevity Vaccine installer and download the latest compatible versions "
             L"of Longevity Vaccine and Thinker.\n\n"
             L"Choose 'Not now' to start the game and be asked again next time.\n\n"
             L"Choose 'Don't ask me again' to start the game and stop this question until you next update Longevity Vaccine "
             L"(undo in Preferences).\n\n"
             L"If you start the game anyway, parts of Longevity Vaccine stay inactive.";
    s.captions[0] = L"Update now"; s.captions[1] = L"Not now"; s.captions[2] = L"Don't ask me again";
    s.ids[0] = 100; s.ids[1] = 101; s.ids[2] = 102;
    s.defaultId = defaultId;
    s.guardMs = 400;
    s.foreground = false;
    s.visible = false;
    s.systemDpi = false;
    s.clock = FakeClock;
    return s;
}

MSG Key(HWND dlg, UINT msg, WPARAM vk, bool repeat = false)
{
    MSG m = {};
    m.hwnd = dlg;
    m.message = msg;
    m.wParam = vk;
    m.lParam = 1 | (repeat ? (1L << 30) : 0);
    return m;
}

bool Inside(const RECT& outer, const RECT& in)
{
    return in.left >= outer.left && in.top >= outer.top && in.right <= outer.right && in.bottom <= outer.bottom;
}

void Structure()
{
    const Spec spec = MakeSpec(100);
    Ctx c;
    g_now = 1000;
    const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
    Check("created", dlg != nullptr);
    if (!dlg) return;
    Check("ctx_bound", c.dlg == dlg);
    wchar_t buf[128];
    GetWindowTextW(dlg, buf, 128);
    Check("title", std::wstring(buf) == L"Longevity Vaccine");
    const LONG_PTR style = GetWindowLongPtrW(dlg, GWL_STYLE);
    Check("close_box", (style & WS_SYSMENU) != 0);
    {
        const HMENU sys = GetSystemMenu(dlg, FALSE);
        const UINT st = sys ? GetMenuState(sys, SC_CLOSE, MF_BYCOMMAND) : static_cast<UINT>(-1);
        Check("close_box_enabled", sys && st != static_cast<UINT>(-1) && !(st & (MF_GRAYED | MF_DISABLED)));
    }
    Check("not_visible_under_test", !IsWindowVisible(dlg));
    Check("not_topmost_under_test", (GetWindowLongPtrW(dlg, GWL_EXSTYLE) & WS_EX_TOPMOST) == 0);

    const wchar_t* captions[3] = { L"Update now", L"Not now", L"Don't ask me again" };
    bool buttons = true, noAmp = true, tabstops = true;
    for (int i = 0; i < 3; ++i) {
        const HWND b = GetDlgItem(dlg, 100 + i);
        wchar_t cls[32] = L"";
        if (b) GetClassNameW(b, cls, 32);
        GetWindowTextW(b, buf, 128);
        buttons = buttons && b && lstrcmpiW(cls, L"Button") == 0 && std::wstring(buf) == captions[i];
        noAmp = noAmp && std::wstring(buf).find(L'&') == std::wstring::npos;
        tabstops = tabstops && (GetWindowLongPtrW(b, GWL_STYLE) & WS_TABSTOP);
    }
    Check("three_buttons_ids_100_101_102", buttons);
    Check("no_ampersand_in_captions", noAmp);
    Check("every_button_is_a_tab_stop", tabstops);
    Check("group_on_first_button_only", (GetWindowLongPtrW(GetDlgItem(dlg, 100), GWL_STYLE) & WS_GROUP) &&
                                        !(GetWindowLongPtrW(GetDlgItem(dlg, 101), GWL_STYLE) & WS_GROUP) &&
                                        !(GetWindowLongPtrW(GetDlgItem(dlg, 102), GWL_STYLE) & WS_GROUP));
    Check("no_reserved_ids", !GetDlgItem(dlg, IDOK) && !GetDlgItem(dlg, IDCANCEL));

    const HWND text = GetDlgItem(dlg, kTextId);
    Check("text_static_noprefix", text && (GetWindowLongPtrW(text, GWL_STYLE) & SS_NOPREFIX));
    static wchar_t big[4096];
    GetWindowTextW(text, big, 4096);
    Check("text_carried_verbatim", std::wstring(big) == spec.text);
    Check("icon_set", SendDlgItemMessageW(dlg, kIconId, STM_GETICON, 0, 0) != 0);

    // layout: every control inside the client area, the buttons in a row below the text, none overlapping
    RECT client; GetClientRect(dlg, &client);
    RECT rt, rb[3];
    GetWindowRect(text, &rt); MapWindowPoints(nullptr, dlg, reinterpret_cast<POINT*>(&rt), 2);
    bool inside = Inside(client, rt), row = true, apart = true;
    for (int i = 0; i < 3; ++i) {
        GetWindowRect(GetDlgItem(dlg, 100 + i), &rb[i]);
        MapWindowPoints(nullptr, dlg, reinterpret_cast<POINT*>(&rb[i]), 2);
        inside = inside && Inside(client, rb[i]);
        row = row && rb[i].top >= rt.bottom && rb[i].top == rb[0].top && (rb[i].right - rb[i].left) == (rb[0].right - rb[0].left);
        if (i) apart = apart && rb[i].left > rb[i - 1].right;
    }
    Check("controls_inside_client", inside);
    Check("buttons_in_a_row_below_text_equal_width", row);
    Check("buttons_do_not_overlap", apart);
    // the text static is tall enough for its own wrapped text
    if (HDC dc = GetDC(text)) {
        HFONT f = reinterpret_cast<HFONT>(SendMessageW(text, WM_GETFONT, 0, 0));
        HGDIOBJ old = f ? SelectObject(dc, f) : nullptr;
        RECT need = { 0, 0, rt.right - rt.left, 0 };
        DrawTextW(dc, spec.text, -1, &need, DT_CALCRECT | DT_WORDBREAK | DT_NOPREFIX | DT_EXPANDTABS);
        if (old) SelectObject(dc, old);
        ReleaseDC(text, dc);
        Check("text_fits_its_static", need.bottom <= rt.bottom - rt.top);
    }
    DestroyWindow(dlg);
}

void DefaultId(int id, const char* name)
{
    const Spec spec = MakeSpec(id);
    Ctx c;
    g_now = 1000;
    const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
    if (!dlg) { Check(name, false, "not created"); return; }
    const LRESULT def = SendMessageW(dlg, DM_GETDEFID, 0, 0);
    bool ok = HIWORD(def) == DC_HASDEFID && LOWORD(def) == id;
    g_now = 2000;                                              // past the guard
    MSG m = Key(dlg, WM_KEYDOWN, VK_RETURN);
    Step(c, m);
    ok = ok && c.done && c.result == id;
    Check(name, ok);
    DestroyWindow(dlg);
}

void Guard()
{
    const Spec spec = MakeSpec(100);
    Ctx c;
    g_now = 1000;
    const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
    if (!dlg) { Check("guard", false, "not created"); return; }

    // inside the guard even the close box is not an answer (a non-client click the loop's guard does not see)
    SendMessageW(dlg, WM_CLOSE, 0, 0);
    SendMessageW(dlg, WM_SYSCOMMAND, SC_CLOSE, 0);
    SendMessageW(dlg, WM_COMMAND, IDCANCEL, 0);
    SendMessageW(dlg, WM_COMMAND, IDOK, 0);
    Check("close_requests_inside_guard_do_not_end_it", IsWindow(dlg) && !c.done);

    // inside the guard: keys, clicks and even a direct command are ignored
    g_now = 1399;
    MSG m = Key(dlg, WM_KEYDOWN, VK_RETURN); Step(c, m);
    m = Key(dlg, WM_KEYDOWN, VK_SPACE); Step(c, m);
    m = Key(dlg, WM_KEYUP, VK_SPACE); Step(c, m);
    Check("keys_inside_guard_ignored", !c.done);
    Check("drop_click_inside_guard", [&] { MSG k = Key(GetDlgItem(dlg, 100), WM_LBUTTONDOWN, 0); return DropMessage(c, k); }());
    SendMessageW(dlg, WM_COMMAND, 100, 0);
    Check("command_inside_guard_ignored", !c.done);
    // a press on the close box (or the caption's system menu) inside the guard is dropped: its tracking loop would
    // otherwise deliver the close after the guard
    Check("drop_close_box_press_inside_guard", [&] {
        for (UINT msg : { static_cast<UINT>(WM_NCLBUTTONDOWN), static_cast<UINT>(WM_NCLBUTTONDBLCLK),
                          static_cast<UINT>(WM_NCRBUTTONDOWN), static_cast<UINT>(WM_NCRBUTTONUP) }) {
            MSG k = Key(dlg, msg, HTCLOSE);
            if (!DropMessage(c, k)) return false;
        }
        return true;
    }());

    // after the guard: a key held since before only auto-repeats, and auto-repeat never answers
    g_now = 1400;
    m = Key(dlg, WM_KEYDOWN, VK_RETURN, true); Step(c, m);
    m = Key(dlg, WM_KEYDOWN, VK_SPACE, true); Step(c, m);
    Check("auto_repeat_after_guard_ignored", !c.done);
    Check("click_after_guard_not_dropped", [&] { MSG k = Key(GetDlgItem(dlg, 100), WM_LBUTTONDOWN, 0); return !DropMessage(c, k); }());
    Check("close_box_press_after_guard_not_dropped", [&] { MSG k = Key(dlg, WM_NCLBUTTONDOWN, HTCLOSE); return !DropMessage(c, k); }());

    // Esc and letters do nothing
    m = Key(dlg, WM_KEYDOWN, VK_ESCAPE); Step(c, m);
    m = Key(dlg, WM_KEYDOWN, 'U'); Step(c, m);
    m = Key(dlg, WM_CHAR, 'u'); Step(c, m);
    m = Key(dlg, WM_CHAR, 'n'); Step(c, m);
    m = Key(dlg, WM_SYSCHAR, 'd'); Step(c, m);
    Check("esc_and_letters_do_nothing", IsWindow(dlg) && !c.done);
    SendMessageW(dlg, WM_COMMAND, IDCANCEL, 0);                 // what Esc becomes inside IsDialogMessage
    SendMessageW(dlg, WM_COMMAND, IDOK, 0);
    Check("idcancel_and_idok_after_guard_do_nothing", IsWindow(dlg) && !c.done);

    // a fresh Enter presses the default
    m = Key(dlg, WM_KEYDOWN, VK_RETURN); Step(c, m);
    Check("fresh_enter_presses_default", c.done && c.result == 100);
    DestroyWindow(dlg);
}

void EachButton()
{
    for (int id = 100; id <= 102; ++id) {
        const Spec spec = MakeSpec(100);
        Ctx c;
        g_now = 1000;
        const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
        if (!dlg) { Check("each_button", false, "not created"); return; }
        g_now = 5000;
        SendMessageW(dlg, WM_COMMAND, MAKEWPARAM(id, BN_CLICKED), reinterpret_cast<LPARAM>(GetDlgItem(dlg, id)));
        char name[32];
        std::snprintf(name, sizeof name, "button_%d_answers", id);
        Check(name, c.done && c.result == id);
        DestroyWindow(dlg);
    }
    // the first answer wins: a second one handled before the loop wakes does not overwrite it
    for (int closeFirst = 0; closeFirst <= 1; ++closeFirst) {
        const Spec s = MakeSpec(100);
        Ctx cx;
        g_now = 1000;
        const HWND d = Create(s, &cx, GetModuleHandleW(nullptr));
        if (!d) { Check("first_answer_wins", false, "not created"); return; }
        g_now = 5000;
        if (closeFirst) SendMessageW(d, WM_CLOSE, 0, 0);
        SendMessageW(d, WM_COMMAND, MAKEWPARAM(101, BN_CLICKED), reinterpret_cast<LPARAM>(GetDlgItem(d, 101)));
        if (!closeFirst) SendMessageW(d, WM_CLOSE, 0, 0);
        Check(closeFirst ? "first_answer_wins_close_then_button" : "first_answer_wins_button_then_close",
              cx.done && cx.result == (closeFirst ? kClosed : 101));
        DestroyWindow(d);
    }
    // an id that is not one of ours never answers
    const Spec spec = MakeSpec(100);
    Ctx c;
    g_now = 1000;
    const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
    if (dlg) {
        g_now = 5000;
        SendMessageW(dlg, WM_COMMAND, 103, 0);
        SendMessageW(dlg, WM_COMMAND, 0, 0);
        Check("foreign_command_ids_ignored", !c.done);
        DestroyWindow(dlg);
    }
}

// ---- the close box, Alt+F4, system menu Close: the fourth answer, kClosed ----------------------------------------
// Pumps what Step's dispatch posted (DefWindowProc POSTS the SC_CLOSE of Alt+F4) through the production loop body.
void Pump(Ctx& c)
{
    MSG p;
    for (int i = 0; i < 64 && !c.done && PeekMessageW(&p, nullptr, 0, 0, PM_REMOVE); ++i) Step(c, p);
}

void CloseBox()
{
    struct Way { const char* name; int kind; } ways[] = {
        { "close_box_answers_closed", 0 },        // the close box and system menu Close: WM_SYSCOMMAND SC_CLOSE
        { "wm_close_answers_closed", 1 },
        { "alt_f4_answers_closed", 2 },           // a real Alt+F4 key-down through the loop body
        { "alt_f4_auto_repeat_ignored", 3 },
        { "esc_never_answers_closed", 4 },
    };
    for (const Way& w : ways) {
        const Spec spec = MakeSpec(100);
        Ctx c;
        g_now = 1000;
        const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
        if (!dlg) { Check(w.name, false, "not created"); return; }
        g_now = 5000;                                           // past the guard
        const HWND b = GetDlgItem(dlg, 100);
        MSG m = {};
        switch (w.kind) {
        case 0: SendMessageW(dlg, WM_SYSCOMMAND, SC_CLOSE, 0); break;
        case 1: SendMessageW(dlg, WM_CLOSE, 0, 0); break;
        case 2: case 3:
            m.hwnd = b; m.message = WM_SYSKEYDOWN; m.wParam = VK_F4;
            m.lParam = 1 | (1L << 29) | (w.kind == 3 ? (1L << 30) : 0);   // KF_ALTDOWN; bit 30 = auto-repeat
            Step(c, m);
            Pump(c);
            break;
        case 4:
            m = Key(b, WM_KEYDOWN, VK_ESCAPE); Step(c, m); Pump(c);
            m = Key(b, WM_KEYUP, VK_ESCAPE); Step(c, m); Pump(c);
            break;
        }
        const bool closed = c.done && c.result == kClosed;
        Check(w.name, (w.kind <= 2) ? closed : (!c.done && IsWindow(dlg)));
        DestroyWindow(dlg);
        Pump(c);
    }
}

// ---- focus and the keys that move it (the dialog is hidden, but its controls take focus like any other) ----------
void FocusAndKeys()
{
    for (int def = 100; def <= 101; ++def) {
        const Spec spec = MakeSpec(def);
        Ctx c;
        g_now = 1000;
        const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
        if (!dlg) { Check("focus", false, "not created"); return; }
        const HWND f = GetFocus();
        // a session without keyboard focus at all (no desktop) cannot show it either way: only a WRONG control fails
        Check(def == 100 ? "focus_starts_on_update_now" : "focus_starts_on_not_now_when_checks_off",
              f == nullptr || f == GetDlgItem(dlg, def));
        DestroyWindow(dlg);
    }
    const Spec spec = MakeSpec(100);
    Ctx c;
    g_now = 1000;
    const HWND dlg = Create(spec, &c, GetModuleHandleW(nullptr));
    if (!dlg) { Check("keys", false, "not created"); return; }
    g_now = 5000;                                               // past the guard
    const HWND b100 = GetDlgItem(dlg, 100), b101 = GetDlgItem(dlg, 101), b102 = GetDlgItem(dlg, 102);
    if (!SetFocus(b102) && GetFocus() != b102) {                // no focus in this session: nothing to test
        for (const char* n : { "arrow_right_wraps_last_to_first", "arrow_left_wraps_first_to_last", "tab_moves_to_the_next_button",
                               "space_key_up_alone_does_nothing", "fresh_space_presses_the_focused_button" })
            Check(n, true);
        DestroyWindow(dlg);
        return;
    }
    MSG m = Key(b102, WM_KEYDOWN, VK_RIGHT); Step(c, m);
    Check("arrow_right_wraps_last_to_first", GetFocus() == b100 && !c.done);
    SetFocus(b100);
    m = Key(b100, WM_KEYDOWN, VK_LEFT); Step(c, m);
    Check("arrow_left_wraps_first_to_last", GetFocus() == b102 && !c.done);
    SetFocus(b100);
    m = Key(b100, WM_KEYDOWN, VK_TAB); Step(c, m);
    Check("tab_moves_to_the_next_button", GetFocus() == b101 && !c.done);
    // a key-up whose key-down the guard swallowed (a key held through it) presses nothing
    m = Key(b101, WM_KEYUP, VK_SPACE); Step(c, m);
    Check("space_key_up_alone_does_nothing", !c.done);
    m = Key(b101, WM_KEYDOWN, VK_SPACE); Step(c, m);
    m = Key(b101, WM_KEYUP, VK_SPACE); Step(c, m);
    Check("fresh_space_presses_the_focused_button", c.done && c.result == 101);
    DestroyWindow(dlg);
}

// ---- Run(): the real loop --------------------------------------------------------------------------------------
wchar_t g_title[64];

DWORD WINAPI ClickFromAnotherThread(LPVOID close)
{
    for (int i = 0; i < 3000; ++i) {                            // up to ~3 s; normally the first few iterations
        if (const HWND h = FindWindowW(L"#32770", g_title)) {
            if (close) SendMessageW(h, WM_SYSCOMMAND, SC_CLOSE, 0);         // the close box
            else SendMessageW(h, WM_COMMAND, MAKEWPARAM(101, BN_CLICKED), 0);   // handled INSIDE the other thread's GetMessage
            return 0;
        }
        Sleep(1);
    }
    return 1;
}

void RunLoop()
{
    // a title no other process can have: parallel test workers run this same self-test
    wsprintfW(g_title, L"LV dialog selftest %lu", GetCurrentProcessId());
    Spec spec = MakeSpec(100);
    spec.title = g_title;
    spec.clock = nullptr;                                       // the real clock ...
    spec.guardMs = 0;                                           // ... and no guard: nothing here waits

    // an answer that arrives by a SENT message from another thread must end the loop (it would wait forever for a
    // posted message otherwise: the test then dies on the caller's timeout)
    const HANDLE t = CreateThread(nullptr, 0, ClickFromAnotherThread, nullptr, 0, nullptr);
    const int answer = Run(spec, GetModuleHandleW(nullptr));
    WaitForSingleObject(t, 5000);
    DWORD threadExit = 2;
    GetExitCodeThread(t, &threadExit);
    CloseHandle(t);
    Check("run_ends_on_an_answer_sent_from_another_thread", answer == 101 && threadExit == 0);
    Check("run_destroys_its_window", FindWindowW(L"#32770", g_title) == nullptr);

    const HANDLE t2 = CreateThread(nullptr, 0, ClickFromAnotherThread, reinterpret_cast<LPVOID>(1), 0, nullptr);
    const int closed = Run(spec, GetModuleHandleW(nullptr));
    WaitForSingleObject(t2, 5000);
    threadExit = 2;
    GetExitCodeThread(t2, &threadExit);
    CloseHandle(t2);
    Check("run_ends_closed_on_a_close_sent_from_another_thread", closed == kClosed && threadExit == 0);

    // WM_QUIT while the dialog is up: no answer, and the quit is handed on to whoever pumps next
    typedef HANDLE (WINAPI* FGetCtx)();
    typedef BOOL (WINAPI* FEqual)(HANDLE, HANDLE);
    const HMODULE user32 = GetModuleHandleW(L"user32.dll");
    const FGetCtx getCtx = reinterpret_cast<FGetCtx>(reinterpret_cast<void*>(GetProcAddress(user32, "GetThreadDpiAwarenessContext")));
    const FEqual equal = reinterpret_cast<FEqual>(reinterpret_cast<void*>(GetProcAddress(user32, "AreDpiAwarenessContextsEqual")));
    const HANDLE before = getCtx ? getCtx() : nullptr;
    spec.systemDpi = true;                                      // the production path: set, then restore
    PostQuitMessage(7);
    const int quit = Run(spec, GetModuleHandleW(nullptr));
    MSG m = {};
    const bool reposted = PeekMessageW(&m, nullptr, WM_QUIT, WM_QUIT, PM_REMOVE) && m.message == WM_QUIT && m.wParam == 7;
    Check("run_returns_no_answer_on_quit", quit == kQuit);
    Check("run_hands_the_quit_on", reposted);
    Check("run_restores_the_thread_dpi_context", !getCtx || !equal || equal(before, getCtx()));
}

void Template()
{
    const Spec spec = MakeSpec(101);
    const std::vector<BYTE> t = BuildTemplate(spec);
    DWORD style = 0, ex = 0;
    memcpy(&style, t.data(), 4);
    memcpy(&ex, t.data() + 4, 4);
    WORD cdit = 0;
    memcpy(&cdit, t.data() + 8, 2);
    Check("template_dword_aligned", t.size() % 4 == 0);
    Check("template_five_items", cdit == 5);
    Check("template_style", (style & DS_SETFONT) && (style & WS_CAPTION) == WS_CAPTION && (style & WS_SYSMENU) &&
                            !(style & DS_SETFOREGROUND) && !(style & WS_VISIBLE) && ex == 0);
    Spec prod = spec;
    prod.foreground = true;
    prod.visible = true;
    const std::vector<BYTE> p = BuildTemplate(prod);
    memcpy(&style, p.data(), 4);
    memcpy(&ex, p.data() + 4, 4);
    Check("template_production_is_foreground_topmost_visible",
          (style & DS_SETFOREGROUND) && (style & WS_VISIBLE) && (ex & WS_EX_TOPMOST) && (style & WS_SYSMENU));
}

} // namespace

int main()
{
    Template();
    Structure();
    DefaultId(100, "default_update_now_when_checks_on");
    DefaultId(101, "default_not_now_when_checks_off");
    Guard();
    EachButton();
    CloseBox();
    FocusAndKeys();
    RunLoop();
    return 0;
}
