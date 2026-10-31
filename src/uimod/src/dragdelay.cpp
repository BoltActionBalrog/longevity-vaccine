// uimod drag-move hold delay (accessibility setting).
//
// A left press on the map arms the goto timer: MapWin_on_left_down 0x46ED30 calls
// Time_start(&g_go_timer 0x939E60, go_timer 0x50F170, 3, delay, 5). The delay is built at 0x46EFAE:
//
//   8B 15 88 92 93 00   mov  edx, [0x939288]        ; nonzero = a unit awaiting orders (move mode)
//   6A 05               push 5
//   F7 DA               neg  edx
//   1B D2               sbb  edx, edx               ; edx = -(move_mode != 0): all-ones or zero
//   B9 60 9E 93 00      mov  ecx, 0x939E60
//   81 E2 65 FD FF FF   and  edx, 0xFFFFFD65        ; imm_and @0x46EFC1 (= 333 - 1000)
//   81 C2 E8 03 00 00   add  edx, 0x3E8             ; imm_add @0x46EFC7 (= 1000)
//   52 6A 03 68 70 F1 50 00 E8 78 73 1A 00           ; push edx; push 3; push go_timer; call Time_start
//
// so move mode waits 333 ms and view mode 1000 ms (identical bytes in terranx.exe, terranx_PRACX.exe
// and their .bak's; no patch set touches 0x46EF90..0x46EFD8). Frida (hook_holdmove) measured the timer
// firing on schedule under continuous mouse motion.
//
// The setting V (ms) rewrites the two imm32s: imm_add = view = max(1000, V), imm_and = V - view (two's
// complement), so move mode waits V and view mode max(1000, V) -- a hold delay longer than vanilla's view
// delay also lengthens view mode's, so view mode never starts its drag sooner than move mode. V is clamped to
// [100, 2000]: Time_start switches to timeSetEvent (callback on another thread) below 50 ms. V = 333
// writes the vanilla bytes back exactly.
//
// Cave-free and byte-checked, so it installs on both exes (the Longevity page's slider exists only on the
// patched one; the ini key works on both). Persisted as [UIMod] DragMoveHoldMs in "Alpha Centauri.ini".

#include "dragdelay.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kImageBase = 0x400000;
constexpr uintptr_t kVA_Site   = 0x0046EFAE;   // mov edx,[0x939288] .. call Time_start (42 bytes)
constexpr size_t    kSiteLen   = 42;
constexpr size_t    kOffAnd    = 0x46EFC1 - kVA_Site;   // imm32 of `and edx, imm`
constexpr size_t    kOffAdd    = 0x46EFC7 - kVA_Site;   // imm32 of `add edx, imm`
constexpr int       kViewVanilla = 1000;

const BYTE kSiteBytes[kSiteLen] = {
    0x8B, 0x15, 0x88, 0x92, 0x93, 0x00,         // mov  edx, [0x939288]
    0x6A, 0x05,                                 // push 5
    0xF7, 0xDA,                                 // neg  edx
    0x1B, 0xD2,                                 // sbb  edx, edx
    0xB9, 0x60, 0x9E, 0x93, 0x00,               // mov  ecx, 0x939E60 (g_go_timer)
    0x81, 0xE2, 0x65, 0xFD, 0xFF, 0xFF,         // and  edx, 0xFFFFFD65
    0x81, 0xC2, 0xE8, 0x03, 0x00, 0x00,         // add  edx, 0x3E8
    0x52,                                       // push edx
    0x6A, 0x03,                                 // push 3
    0x68, 0x70, 0xF1, 0x50, 0x00,               // push 0x50F170 (go_timer)
    0xE8, 0x78, 0x73, 0x1A, 0x00,               // call 0x616350 (Time_start)
};

bool g_ok = false;
int  g_ms = kDragDelayDefault;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}

void IniPath(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
    lstrcatA(out, "Alpha Centauri.ini");
}

int Clamp(int ms)
{
    return ms < kDragDelayMin ? kDragDelayMin : ms > kDragDelayMax ? kDragDelayMax : ms;
}

// Write the two imm32s for delay `ms` (already clamped).
void Apply(int ms)
{
    const int view = ms > kViewVanilla ? ms : kViewVanilla;
    const uint32_t immAnd = static_cast<uint32_t>(ms - view);
    const uint32_t immAdd = static_cast<uint32_t>(view);
    BYTE* p = At(kVA_Site);
    DWORD old;
    if (!VirtualProtect(p, kSiteLen, PAGE_EXECUTE_READWRITE, &old)) return;
    memcpy(p + kOffAnd, &immAnd, 4);
    memcpy(p + kOffAdd, &immAdd, 4);
    VirtualProtect(p, kSiteLen, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, kSiteLen);
}

} // namespace

void InstallDragDelay()
{
    if (memcmp(At(kVA_Site), kSiteBytes, kSiteLen) != 0) {
        UimodLog("[uimod] dragdelay: site byte check FAILED @0x46EFAE -> drag-move hold delay disabled\n");
        return;
    }
    g_ok = true;

    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    g_ms = Clamp(static_cast<int>(GetPrivateProfileIntA("UIMod", "DragMoveHoldMs", kDragDelayDefault, ini)));
    Apply(g_ms);

    char msg[128];
    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] dragdelay: installed, hold %d ms (view mode %d ms)\n",
                g_ms, g_ms > kViewVanilla ? g_ms : kViewVanilla);
    UimodLog(msg);
}

bool DragDelayAvailable() { return g_ok; }
int  DragDelayGet() { return g_ms; }

void DragDelaySet(int ms)
{
    if (!g_ok) return;
    ms = Clamp(ms);
    if (ms == g_ms) return;
    g_ms = ms;
    Apply(ms);
}

void DragDelaySave()
{
    if (!g_ok) return;
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    char val[16];
    _snprintf_s(val, sizeof val, _TRUNCATE, "%d", g_ms);
    WritePrivateProfileStringA("UIMod", "DragMoveHoldMs", val, ini);
}

// Fine steps below the vanilla default (25 ms), then ~20% growth per step up to 2000 ms.
static const int kDragDelayTable[kDragDelayPositions] = {
    100, 125, 150, 175, 200, 225, 250, 275, 300, 333,   // 333 = vanilla (position 9)
    375, 425, 500, 600, 750, 900, 1100, 1350, 1650, 2000,
};

int DragDelayMsFromPos(int pos)
{
    if (pos < 0) pos = 0;
    if (pos > kDragDelayPositions - 1) pos = kDragDelayPositions - 1;
    return kDragDelayTable[pos];
}

int DragDelayPosFromMs(int ms)
{
    int best = 0, bestD = 0x7FFFFFFF;
    for (int p = 0; p < kDragDelayPositions; ++p) {
        int d = DragDelayMsFromPos(p) - ms;
        if (d < 0) d = -d;
        if (d < bestD) { bestD = d; best = p; }
    }
    return best;
}
