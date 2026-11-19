// rowarrowfix.cpp -- the base screen's unit-row scroll arrows no longer stay up over the screen that replaces it.
//
// BASE-GAME BUG (user 2026-11-11, reproduced on the unmodded exe at 1024x768; traced 2026-11-13 with
// work\scripts\hook_dw_arrows.js at 4K and 1920x1080): base screen -> production picker -> WORKSHOP opened the Design
// Workshop with a stray LEFT scroll arrow in the middle of its unit row, and clicking it did nothing.
// The unit-row arrows are three console (MainWin) FlatButtons, [8] 0x7B5080 / [9] 0x7B5BCC / [10] 0x7B6718, and
// only the two row painters ever show them: BaseWin_draw_garrison 0x4103B0 hides [8] and shows [9]+[10] when the
// garrison overflows; StatusWin_draw_status 0x4B6570 shows [8]+[10] for an overflowing HUD stack. When the HUD hands
// the console to another screen its leave handler hides every console button (the 0x2A-button loop @0x45CAB5), but
// the base screen's leave handler BaseWin_on_status(enter = 0) 0x41DAD0 hides only its own buttons -- [9]/[10] stayed
// up over whatever came next. The workshop's own right arrow (DesignWin button 0x18) sits on [10]'s exact rect, so
// only [9] showed; a click on it sent id 0x3F1 to DesignWin_on_button_clicked, which has no case for it.
// While another screen holds the console the base screen does not repaint its row (BaseWin_on_redraw tests the
// iface mode), and when the base screen comes back its redraw re-runs BaseWin_draw_garrison, which re-shows the
// arrows the garrison needs (both measured in the trace).
//
// THE FIX: the base screen's interface vtable slot 0x66A3B8 (BaseWin_on_status) goes through a wrapper that, on
// leave, hides the three row arrows through their own hide (FlatButton vtbl+8 0x406860 -> Win_hide), then runs the
// engine's handler unchanged. Byte-checked (slot value, handler prologue, FlatButton hide slot); each button's vtable
// is checked before the call. Works on the unpatched and the PRACX exe alike (no cave, no patcher artifact).

#include "rowarrowfix.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);   // init.cpp

namespace {

constexpr uintptr_t kVA_BaseIfaceOnStatusSlot = 0x0066A3B8;   // BaseWin iface vtbl +0: on_status(enter)
constexpr uintptr_t kVA_BaseWinOnStatus       = 0x0041DAD0;   // thiscall RET 4
constexpr uintptr_t kVA_FlatButtonVtbl        = 0x00669754;
constexpr uintptr_t kVA_FlatButtonHide        = 0x00406860;   // vtbl+8: tail-jmp Win_hide
constexpr uintptr_t kVA_RowArrows[3]          = { 0x007B5080, 0x007B5BCC, 0x007B6718 };   // MainWin buttons [8] [9] [10]
constexpr uint32_t  kWinVisibleOff            = 0x9C;         // Win +0x9C bit 0 = visible (Win_is_visible)

// push ebp; mov ebp,esp; mov eax,[ebp+8]; push esi; push edi; mov edi,ecx; test eax,eax; je (leave branch)
const BYTE kOnStatusPrologue[14] = { 0x55, 0x8B, 0xEC, 0x8B, 0x45, 0x08, 0x56, 0x57, 0x8B, 0xF9, 0x85, 0xC0, 0x0F, 0x84 };

using FOnStatus = void(__thiscall*)(void* iface, int enter);
using FHide = void(__thiscall*)(void* win);

FOnStatus g_origOnStatus = nullptr;
bool g_loggedHide = false;

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000); }

void HideRowArrows()
{
    const uintptr_t flatVtbl = reinterpret_cast<uintptr_t>(At(kVA_FlatButtonVtbl));
    int hidden = 0;
    for (uintptr_t va : kVA_RowArrows) {
        BYTE* btn = At(va);
        const uintptr_t vtbl = *reinterpret_cast<const uintptr_t*>(btn);
        if (vtbl != flatVtbl) continue;                       // not constructed (or not a FlatButton): leave it alone
        if (*reinterpret_cast<const uint32_t*>(btn + kWinVisibleOff) & 1) ++hidden;
        reinterpret_cast<FHide>(*reinterpret_cast<const uintptr_t*>(vtbl + 8))(btn);
    }
    if (hidden && !g_loggedHide) {
        g_loggedHide = true;
        UimodLog("[uimod] rowarrowfix: hid the base screen's unit-row scroll arrows as it handed the console to another "
                 "screen (base-game bug: they stayed over the Design Workshop's unit row)\n");
    }
}

// thiscall(iface, enter) RET 4 == fastcall(ecx, edx, 1 stack arg)
void __fastcall BaseOnStatus(void* iface, void* /*edx*/, int enter)
{
    if (enter == 0) HideRowArrows();
    g_origOnStatus(iface, enter);
}

} // namespace

void InstallRowArrowFix()
{
    uintptr_t* slot = reinterpret_cast<uintptr_t*>(At(kVA_BaseIfaceOnStatusSlot));
    const uintptr_t flatHide = *reinterpret_cast<const uintptr_t*>(At(kVA_FlatButtonVtbl + 8));
    if (*slot != reinterpret_cast<uintptr_t>(At(kVA_BaseWinOnStatus)) ||
        memcmp(At(kVA_BaseWinOnStatus), kOnStatusPrologue, sizeof kOnStatusPrologue) != 0 ||
        flatHide != reinterpret_cast<uintptr_t>(At(kVA_FlatButtonHide))) {
        UimodLog("[uimod] rowarrowfix: base screen handler bytes differ -> the unit-row arrow fix is not installed\n");
        return;
    }
    DWORD old;
    if (!VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &old)) {
        UimodLog("[uimod] rowarrowfix: VirtualProtect failed -> the unit-row arrow fix is not installed\n");
        return;
    }
    g_origOnStatus = reinterpret_cast<FOnStatus>(*slot);
    *slot = reinterpret_cast<uintptr_t>(&BaseOnStatus);
    VirtualProtect(slot, sizeof *slot, old, &old);
    UimodLog("[uimod] rowarrowfix: installed (the base screen's unit-row arrows are hidden when it hands over the console)\n");
}
