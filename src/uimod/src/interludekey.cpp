// interludekey.cpp -- the keystroke that closes a story interlude no longer leaks to the map.
//
// BASE-GAME BUG (user 2026-10-30, reproduced on the unmodded exe; traced with work\scripts\hook_interlude_esc.js,
// mechanism verified by the audit's disassembly): a story interlude (interlude 0x5230E0 -> load_credits_b 0x45F2E0)
// is a modal GraphicWin of the InterludeWin class (vtable 0x66C708, a stack object in interlude()). WinProc 0x5F0650
// hands WM_KEYDOWN to the active target's on_key_message (vtbl+0x138 Win_on_key 0x5F5D10); for a char-producing key
// the key dispatcher 0x5EEB90 skips Win_key_default and calls the window's raw on_keydown (vtbl+0x68) -- for an
// InterludeWin that is 0x45F6F0: `Win_release_modal; return 1` (ANY key closes it; so does a click, vtbl+0x50).
// Win_on_key's tail then calls 0x5FCFE0, which PeekMessages the keystroke's WM_CHAR and dispatches it SYNCHRONOUSLY,
// inside the key-down's own dispatch: by then the modal top is gone, Win_get_active_target() is the Console, and
// Console_on_key_click(Esc) opens the game menu over the interlude (the "menu flash"); the interlude's modal loop
// only ends once that menu is dismissed, so a second Esc was needed.
//
// THE FIX: a thread-local WH_GETMESSAGE hook (like wheel.cpp's) watches the pair. A WM_KEYDOWN delivered while the
// modal top is an InterludeWin arms the watch; the WM_CHAR that 0x5FCFE0 pulls for that keystroke is turned into
// WM_NULL when that interlude is no longer the modal top (the key-down closed it). Because the engine drains the
// character inside the key-down's dispatch, nothing can interleave (no key-up, timer, paint, mouse or posted message;
// dead keys / IME / auto-repeat cannot split a pair). Other classes, other keys and a nested modal pass through
// unchanged; a char-less closing key (Shift, an arrow, F-key) disarms at its key-up. Class-pinned by the ctor's vtable
// store (0x45F2C0 `mov [esi], 0x66C708`), the raw on_keydown slot and the key-message slot; the hook is not installed
// when those bytes differ. Works on the unpatched and the PRACX exe alike (no cave, no patcher artifact).

#include "interludekey.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>

void UimodLog(const char* msg);   // init.cpp

namespace {

constexpr uintptr_t kVA_InterludeVtbl   = 0x0066C708;
constexpr uintptr_t kVA_InterludeCtorVt = 0x0045F2C0;   // InterludeWin ctor: mov dword ptr [esi], 0x66C708
constexpr uintptr_t kVA_InterludeKeyDn  = 0x0045F6F0;   // vtbl+0x68 InterludeWin_on_keydown: Win_release_modal ; return 1
constexpr uintptr_t kVA_WinOnKey        = 0x005F5D10;   // vtbl+0x138 Win_on_key: the WM_KEYDOWN entry whose tail drains the WM_CHAR
constexpr uintptr_t kVA_WinOnChar       = 0x005F5FB0;   // vtbl+0x13C: the generic on_char dispatcher
constexpr uintptr_t kVA_g_modal_top     = 0x009B7AE0;

HHOOK g_hook = nullptr;
void* g_armedWin = nullptr;     // the interlude that received the last key-down while modal
HWND  g_armedHwnd = nullptr;
int   g_swallowed = 0;

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000); }
void* ModalTop() { return *reinterpret_cast<void**>(At(kVA_g_modal_top)); }
bool IsInterlude(const void* win)
{
    return win != nullptr && *reinterpret_cast<const uintptr_t*>(win) == reinterpret_cast<uintptr_t>(At(kVA_InterludeVtbl));
}

LRESULT CALLBACK GetMsgProc(int code, WPARAM wParam, LPARAM lParam)
{
    if (code == HC_ACTION && wParam == PM_REMOVE) {
        MSG* m = reinterpret_cast<MSG*>(lParam);
        // WM_SYSKEYDOWN is re-posted by the engine as a plain WM_KEYDOWN (vtbl+0x140) and WM_SYSCHAR never reaches
        // on_char, so only the plain pair matters.
        if (m->message == WM_KEYDOWN) {
            void* top = ModalTop();
            if (IsInterlude(top)) { g_armedWin = top; g_armedHwnd = m->hwnd; }
            else { g_armedWin = nullptr; g_armedHwnd = nullptr; }
        } else if (m->message == WM_CHAR) {
            if (g_armedWin && m->hwnd == g_armedHwnd && ModalTop() != g_armedWin) {
                // the key-down closed the interlude: its character must not reach whatever is active now
                m->message = WM_NULL;
                if (++g_swallowed == 1)
                    UimodLog("[uimod] interludekey: swallowed the character of the keystroke that closed an interlude "
                             "(base-game bug: it reached the map and opened the game menu)\n");
            }
            g_armedWin = nullptr; g_armedHwnd = nullptr;
        } else if (m->message == WM_KEYUP || m->message == WM_SYSKEYUP) {
            g_armedWin = nullptr; g_armedHwnd = nullptr;        // a char-less closing key: nothing to swallow
        }
    }
    return CallNextHookEx(g_hook, code, wParam, lParam);
}

} // namespace

void InstallInterludeKeyFix()
{
    static const BYTE ctorStore[6] = { 0xC7, 0x06, 0x08, 0xC7, 0x66, 0x00 };
    const uintptr_t keyDn = *reinterpret_cast<const uintptr_t*>(At(kVA_InterludeVtbl + 0x68));
    const uintptr_t onKeyMsg = *reinterpret_cast<const uintptr_t*>(At(kVA_InterludeVtbl + 0x138));
    const uintptr_t onChar = *reinterpret_cast<const uintptr_t*>(At(kVA_InterludeVtbl + 0x13C));
    if (memcmp(At(kVA_InterludeCtorVt), ctorStore, sizeof ctorStore) != 0 ||
        keyDn != reinterpret_cast<uintptr_t>(At(kVA_InterludeKeyDn)) || onKeyMsg != reinterpret_cast<uintptr_t>(At(kVA_WinOnKey)) ||
        onChar != reinterpret_cast<uintptr_t>(At(kVA_WinOnChar))) {
        UimodLog("[uimod] interludekey: InterludeWin class bytes differ -> the interlude Esc fix is not installed\n");
        return;
    }
    g_hook = SetWindowsHookExA(WH_GETMESSAGE, GetMsgProc, nullptr, GetCurrentThreadId());
    UimodLog(g_hook ? "[uimod] interludekey: installed (the keystroke that closes a story interlude no longer reaches the map)\n"
                    : "[uimod] interludekey: SetWindowsHookEx failed -> the interlude Esc fix is not installed\n");
}
