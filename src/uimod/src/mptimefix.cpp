// mptimefix.cpp -- the multiplayer time widget flashes black when it is redrawn between timer ticks.
//
// MultiWin_draw_time 0x478BE0 (thiscall; rect, tick) draws the COMMLINK / lobby time readout ("No Time Control",
// the turn timer). Two of its locals are written only on some tick != 0 paths:
//   [ebp-0x10] blink: 1 while the timer is held (0x478CB9), 0 on the countdown paths (0x478C6E / 0x478C97);
//              read at 0x479206: blink && (counter 0x7FFF7C & 1) -> text colour 0 (black), else 0xE4.
//   [ebp-0xC]  the timer was running before this tick: written on the two COUNTDOWN paths only (0x478C7D /
//              0x478CA6), not on the hold path; read at 0x478E11 (time-out event 0x2601 when the time reached 0)
//              and at 0x479008 (sound 0x21).
// The redraw path (tick == 0: `je 0x478CC8` at 0x478C34 -- a repaint of the window under the mouse) skips all
// three writes, so both are stack garbage there: the text drew black whenever the garbage was nonzero on an
// odd counter (user 2026-11-07, 1080p lobby: "No Time Control" flashes black while the mouse moves over it), and
// the time-out branch could read a stale "was running" flag -- on a HELD tick too. Vanilla bug; PRACX, Thinker and
// the patcher leave this code alone (the 500 ms timer 0x50EF10 is the only caller passing tick = 1).
// Fix: a detour at the prologue's `sub esp,0x60; mov edx,[ebp+8]` gives both locals their tick-path meaning
// before any path runs: [ebp-0xC] = 0 (a redraw or a held tick counts nothing down; the 0 -> time-out transition
// happens only on a countdown tick, which writes the local itself), [ebp-0x10] = the hold condition the tick
// path tests (0x478C40..0x478C5F: any of 0x93F664 / 0x93E8E0 / 0x93F668 nonzero), so a redraw shows the same
// blink phase the last tick drew (the counter only advances on a tick). Countdown ticks overwrite both and draw
// exactly as before; a held tick no longer reads garbage for [ebp-0xC] (no spurious time-out event / sound).
#include "mptimefix.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_DrawTime = 0x478BE0;
constexpr uintptr_t kVA_Site     = 0x478BE3;   // sub esp,0x60 (3) ; mov edx,[ebp+8] (3)
constexpr uintptr_t kVA_Resume   = 0x478BE9;   // push ebx
constexpr size_t    kSiteLen     = 6;
// push ebp; mov ebp,esp; sub esp,0x60; mov edx,[ebp+8]; push ebx; push esi; mov esi,ecx
const BYTE kExpectEntry[12] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x60, 0x8B, 0x55, 0x08, 0x53, 0x56, 0x8B };
// The tick path's hold test and the three writes this fix stands in for.
//   0x478C3A: mov ecx,[0x7FFF7C]; mov eax,[0x93F664]; inc ecx; cmp eax,edi; mov eax,[0x93F668];
//             mov [0x7FFF7C],ecx; jne 0x478CB7; cmp [0x93E8E0],edi; jne 0x478CB7; cmp eax,edi; jne 0x478CB7
constexpr uintptr_t kVA_HoldTest = 0x478C3A;
const BYTE kExpectHold[39] = { 0x8B, 0x0D, 0x7C, 0xFF, 0x7F, 0x00, 0xA1, 0x64, 0xF6, 0x93, 0x00, 0x41, 0x3B, 0xC7,
                               0xA1, 0x68, 0xF6, 0x93, 0x00, 0x89, 0x0D, 0x7C, 0xFF, 0x7F, 0x00, 0x75, 0x62,
                               0x39, 0x3D, 0xE0, 0xE8, 0x93, 0x00, 0x75, 0x5A, 0x3B, 0xC7, 0x75, 0x56 };
//   0x478C29: mov eax,[ebp+0xC]; mov ebx,[0x703DE0]; cmp eax,edi; je 0x478CC8   (the redraw skip)
constexpr uintptr_t kVA_TickSkip = 0x478C29;
const BYTE kExpectSkip[17] = { 0x8B, 0x45, 0x0C, 0x8B, 0x1D, 0xE0, 0x3D, 0x70, 0x00, 0x3B, 0xC7, 0x0F, 0x84, 0x8E, 0x00,
                               0x00, 0x00 };
//   0x478CB7: cmp eax,edi; mov dword ptr [ebp-0x10],1   (the hold path's blink write)
constexpr uintptr_t kVA_HoldWrite = 0x478CB7;
const BYTE kExpectHoldWrite[9] = { 0x3B, 0xC7, 0xC7, 0x45, 0xF0, 0x01, 0x00, 0x00, 0x00 };
//   0x479206: mov eax,[ebp-0x10]; test eax,eax; je; test byte ptr [0x7FFF7C],1   (the colour read)
constexpr uintptr_t kVA_ColourRead = 0x479206;
const BYTE kExpectColour[14] = { 0x8B, 0x45, 0xF0, 0x85, 0xC0, 0x74, 0x13, 0xF6, 0x05, 0x7C, 0xFF, 0x7F, 0x00, 0x01 };

const int* g_hold1 = nullptr;     // 0x93F664
const int* g_hold2 = nullptr;     // 0x93E8E0
const int* g_hold3 = nullptr;     // 0x93F668
BYTE* g_resume = nullptr;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

// Entered by jmp in place of `sub esp,0x60; mov edx,[ebp+8]`; ebp is the engine frame. The code after the
// resume sets every flag it reads (sub edi,eax at 0x478BF9) and writes eax before reading it.
__declspec(naked) void StubTimeLocals()
{
    __asm {
        sub  esp, 0x60
        mov  dword ptr [ebp - 0x0C], 0
        mov  dword ptr [ebp - 0x10], 0
        push eax
        mov  eax, dword ptr [g_hold1]
        cmp  dword ptr [eax], 0
        jne  held
        mov  eax, dword ptr [g_hold2]
        cmp  dword ptr [eax], 0
        jne  held
        mov  eax, dword ptr [g_hold3]
        cmp  dword ptr [eax], 0
        je   done
    held:
        mov  dword ptr [ebp - 0x10], 1
    done:
        pop  eax
        mov  edx, dword ptr [ebp + 8]
        jmp  dword ptr [g_resume]
    }
}

} // namespace

void InstallMpTimeFix()
{
    if (memcmp(At(kVA_DrawTime), kExpectEntry, sizeof kExpectEntry) != 0 ||
        memcmp(At(kVA_TickSkip), kExpectSkip, sizeof kExpectSkip) != 0 ||
        memcmp(At(kVA_HoldTest), kExpectHold, sizeof kExpectHold) != 0 ||
        memcmp(At(kVA_HoldWrite), kExpectHoldWrite, sizeof kExpectHoldWrite) != 0 ||
        memcmp(At(kVA_ColourRead), kExpectColour, sizeof kExpectColour) != 0) {
        UimodLog("[uimod] mptimefix: unexpected bytes in MultiWin_draw_time -> time widget fix NOT installed\n");
        return;
    }
    g_hold1 = reinterpret_cast<const int*>(At(0x93F664));
    g_hold2 = reinterpret_cast<const int*>(At(0x93E8E0));
    g_hold3 = reinterpret_cast<const int*>(At(0x93F668));
    g_resume = At(kVA_Resume);
    BYTE* site = At(kVA_Site);
    BYTE patch[kSiteLen] = { 0xE9, 0, 0, 0, 0, 0x90 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubTimeLocals) - (reinterpret_cast<uintptr_t>(site) + 5));
    memcpy(patch + 1, &rel, 4);
    DWORD old;
    if (!VirtualProtect(site, kSiteLen, PAGE_EXECUTE_READWRITE, &old)) {
        UimodLog("[uimod] mptimefix: VirtualProtect failed -> time widget fix NOT installed\n");
        return;
    }
    memcpy(site, patch, kSiteLen);
    VirtualProtect(site, kSiteLen, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, kSiteLen);
    UimodLog("[uimod] mptimefix: the multiplayer time widget no longer flashes black on a redraw\n");
}
