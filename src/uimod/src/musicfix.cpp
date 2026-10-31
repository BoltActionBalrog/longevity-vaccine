// musicfix.cpp -- the base game leaves the in-game music playing after a game ends.
//
// The in-game music is one object (g_music 0x74DAA0, an .amb player made by load_music 0x4457E0). The
// engine destroys it in two places only: at the top of load_music (the NEXT game's desktop_init) and on
// the Music preference toggle (0x491ACF). The quit-to-menu path -- control_turn returns, control_game
// calls desktop_close 0x58EFF0, then top_menu -- never touches it, and soundx.dll plays on its own
// threads, so the faction's music runs on under the main menu (and under "opening menu.wav", which
// top_menu starts on top of it).
// Fix: desktop_close's first call (`call DesignWin_reset` at 0x58EFF5) is redirected to a stub that
// destroys the music object the way load_music and the preference toggle do (vtbl+8 with 1, then
// g_music = 0), and tail-jumps to DesignWin_reset with ecx intact. Every reader of g_music null-checks
// it; the next desktop_init -> load_music makes a new one. desktop_close has one caller in the exe and
// Thinker's control_game replacement calls the same function, so the entry covers both.

#include "musicfix.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_ResetCall     = 0x58EFF5;   // desktop_close: call DesignWin_reset
constexpr uintptr_t kVA_DesignReset   = 0x43C1A0;   // DesignWin_reset (fastcall, ecx = DesignWin)
constexpr uintptr_t kVA_Music         = 0x74DAA0;   // g_music
const BYTE kExpectCall[5] = { 0xE8, 0xA6, 0xD1, 0xEA, 0xFF };

BYTE* g_design_reset = nullptr;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

void __cdecl StopGameMusic()
{
    void** slot = reinterpret_cast<void**>(At(kVA_Music));
    void* music = *slot;
    if (!music) return;
    typedef void* (__thiscall* FScalarDtor)(void* self, int flags);
    const FScalarDtor dtor = (*reinterpret_cast<FScalarDtor**>(music))[2];   // vtbl+8
    dtor(music, 1);
    *slot = nullptr;
}

__declspec(naked) void StubDesktopClose()
{
    __asm {
        push ecx                            // DesignWin_reset's this
        call StopGameMusic
        pop  ecx
        jmp  dword ptr [g_design_reset]     // the displaced call's target; returns to desktop_close
    }
}

} // namespace

void InstallMusicFix()
{
    BYTE* site = At(kVA_ResetCall);
    if (memcmp(site, kExpectCall, sizeof kExpectCall) != 0) {
        UimodLog("[uimod] musicfix: unexpected bytes in desktop_close -> main-menu music fix NOT installed\n");
        return;
    }
    g_design_reset = At(kVA_DesignReset);
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubDesktopClose) -
                                             (reinterpret_cast<uintptr_t>(site) + 5));
    DWORD old;
    if (!VirtualProtect(site, sizeof kExpectCall, PAGE_EXECUTE_READWRITE, &old)) {
        UimodLog("[uimod] musicfix: VirtualProtect failed -> main-menu music fix NOT installed\n");
        return;
    }
    memcpy(site + 1, &rel, 4);
    VirtualProtect(site, sizeof kExpectCall, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, sizeof kExpectCall);
    UimodLog("[uimod] musicfix: the in-game music stops when a game ends\n");
}
