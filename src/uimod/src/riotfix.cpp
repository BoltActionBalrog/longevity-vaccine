// riotfix.cpp -- the base game's drone-riot DEFECTION block (drone_riot 0x4F4FB0, from 0x4F5553).
//
// When a long-rioting base defects, the engine builds seven per-faction weights from the REVOLT faction
// bonus (stock game: only the Free Drones, REVOLT 75), P = 100 * product(1 - w/100) = the chance that NO
// faction poaches the base, rolls r = timeGetTime() % 100, and either keeps the default target (owner of
// the nearest foreign base) or picks a REVOLT faction by weight: (timeGetTime()/100) % sum(weights).
// Two base-game defects:
//   1. The weight slots [ebp-0x58 .. ebp-0x40] are never initialised: the loop's "slot = -1" store is
//      `mov [ebp-0x3c], -1`, one fixed address past the array, once per faction. Both consumers skip a
//      slot that holds -1, so every faction without REVOLT feeds leftover stack into P. With no REVOLT
//      faction in the game sum == 0, and whenever the garbage P landed >= r the weighted pick ran
//      idiv 0 (0xC0000094 at 0x4F5633, end of turn).
//   2. The roll is inverted: the weighted pick runs when r <= P, i.e. with the NO-poach chance, so
//      REVOLT 75 gave the Drones ~26%. alphax.txt: "Additional % chance that other revolting bases will
//      defect to this faction".
// Fix: (1) a 6-byte site detour on the block's first instruction (every entry targets 0x4F5553) sets the
// seven slots to -1; (2) `jl` -> `jg` at 0x4F561D makes the pick run when r >= P (REVOLT 75 -> 75%). With
// both, a game without a REVOLT faction has P == 100 > r always: the weighted pick and its division are
// unreachable.
//   3. Both "random" numbers are one raw timeGetTime() reading (r = t % 100, pick = (t / 100) % sum):
//      not reproducible, machine-local, and read as SIGNED -- past 24.8 days of uptime t is negative, r is
//      in -99..0 <= P and the (inverted) test ALWAYS took the weighted pick -- a certain idiv 0 without a
//      REVOLT faction. Fix: the 6-byte `call [timeGetTime]` at 0x4F55F9 becomes
//      a call of RiotRoll(), which draws both numbers from the C runtime rand() 0x64601D that drone_riot
//      already uses for its police and facility rolls: t' = rand() % 100 + 100 * rand()  (>= 0, so
//      t' % 100 is the roll and t' / 100 = rand() feeds the pick; sum <= 700 << 32767).
// All-or-nothing; all three sites byte-checked.

#include "riotfix.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_WeightsInit = 0x4F5553;     // fld qword ptr [0x66D8D8]
constexpr uintptr_t kVA_RollBranch  = 0x4F561B;     // cmp ecx, edx / jl 0x4F565C
constexpr uintptr_t kVA_ClockCall   = 0x4F55F9;     // call dword ptr [0x669368] (timeGetTime)
constexpr uintptr_t kVA_Rand        = 0x64601D;     // C runtime rand(), 0..32767
const BYTE kExpectInit[6] = { 0xDD, 0x05, 0xD8, 0xD8, 0x66, 0x00 };
const BYTE kExpectRoll[4] = { 0x3B, 0xCA, 0x7C, 0x3D };
const BYTE kExpectClock[6] = { 0xFF, 0x15, 0x68, 0x93, 0x66, 0x00 };

BYTE* g_resume = nullptr;
const double* g_one = nullptr;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

// Stands in for timeGetTime() at the defection roll: same contract (no args, value in eax).
int __cdecl RiotRoll()
{
    typedef int (__cdecl* FRand)();
    const FRand rnd = reinterpret_cast<FRand>(At(kVA_Rand));
    const int roll = rnd() % 100;
    return roll + 100 * rnd();
}

__declspec(naked) void StubWeightsInit()
{
    __asm {
        mov  dword ptr [ebp - 0x58], -1
        mov  dword ptr [ebp - 0x54], -1
        mov  dword ptr [ebp - 0x50], -1
        mov  dword ptr [ebp - 0x4C], -1
        mov  dword ptr [ebp - 0x48], -1
        mov  dword ptr [ebp - 0x44], -1
        mov  dword ptr [ebp - 0x40], -1
        push eax
        mov  eax, dword ptr [g_one]
        fld  qword ptr [eax]                // the displaced instruction
        pop  eax
        jmp  dword ptr [g_resume]
    }
}

} // namespace

void InstallRiotFix()
{
    BYTE* a = At(kVA_WeightsInit);
    BYTE* b = At(kVA_RollBranch);
    BYTE* c = At(kVA_ClockCall);
    if (memcmp(a, kExpectInit, sizeof kExpectInit) != 0 || memcmp(b, kExpectRoll, sizeof kExpectRoll) != 0 ||
        memcmp(c, kExpectClock, sizeof kExpectClock) != 0) {
        UimodLog("[uimod] riotfix: unexpected bytes in drone_riot -> base-defection fix NOT installed\n");
        return;
    }
    g_one    = reinterpret_cast<const double*>(At(0x66D8D8));
    g_resume = a + sizeof kExpectInit;
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubWeightsInit) -
                                             (reinterpret_cast<uintptr_t>(a) + 5));
    DWORD old;
    VirtualProtect(a, sizeof kExpectInit, PAGE_EXECUTE_READWRITE, &old);
    a[0] = 0xE9;
    memcpy(a + 1, &rel, 4);
    a[5] = 0x90;
    VirtualProtect(a, sizeof kExpectInit, old, &old);
    FlushInstructionCache(GetCurrentProcess(), a, sizeof kExpectInit);

    VirtualProtect(b, sizeof kExpectRoll, PAGE_EXECUTE_READWRITE, &old);
    b[2] = 0x7F;                                                // jl -> jg: weighted pick when r >= P
    VirtualProtect(b, sizeof kExpectRoll, old, &old);
    FlushInstructionCache(GetCurrentProcess(), b, sizeof kExpectRoll);
    const int32_t relC = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&RiotRoll) -
                                              (reinterpret_cast<uintptr_t>(c) + 5));
    VirtualProtect(c, sizeof kExpectClock, PAGE_EXECUTE_READWRITE, &old);
    c[0] = 0xE8;                                                // call RiotRoll; nop
    memcpy(c + 1, &relC, 4);
    c[5] = 0x90;
    VirtualProtect(c, sizeof kExpectClock, old, &old);
    FlushInstructionCache(GetCurrentProcess(), c, sizeof kExpectClock);
    UimodLog("[uimod] riotfix: drone-riot base defection fixed (weights initialised, REVOLT roll un-inverted, "
             "rolls from rand())\n");
}
