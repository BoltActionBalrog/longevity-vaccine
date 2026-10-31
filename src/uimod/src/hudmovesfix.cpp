// hudmovesfix.cpp -- the HUD "Moves" readout is not refreshed when the engine gives up a go-to.
//
// Console_veh_turn 0x513B90 runs the current unit's orders in a loop: NetDaemon_action -> action_go_to ->
// Path_move -> order_veh. A go-to with no route (a ship ordered across a continent) falls back to Path_move's
// greedy neighbour step. Traced 2026-10-10 (frida_hudmoves_20261010T220348.log): the first call takes one
// step (moves spent), the next Path_move finds no neighbour worth taking, clears the order itself and returns
// -1; action_go_to's `iVar2 < 0` branch @0x4CB550 stores order = 0 again and returns, and the loop drops into
// wait_loop for the player's next input WITHOUT the unit-panel repaint its redraw block does
// (StatusWin_redraw @0x513D2B) -- the HUD keeps the pre-move count until the unit is re-selected (vanilla,
// user-confirmed). The loop's other give-up, 100 refused steps -> `mov byte [veh.order], 0` @0x513E27, skips
// the repaint the same way.
// Fix: both order-clearing stores become jmps to stubs that do the store, repaint the unit panel when the
// unit is the one awaiting orders (StatusWin_redraw(StatusWin): the same call, from the same loop context),
// and resume. The stubs keep every register and EFLAGS (0x4CB558's je reads the flags of a test BEFORE the
// store).
#include "hudmovesfix.h"
#include "modernctl.h"
#include "thinkercompat.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_StatusWin       = 0x8C5568;   // the StatusWin object (thiscall this)
constexpr uintptr_t kVA_StatusWinRedraw = 0x4B9EA0;
constexpr uintptr_t kVA_StatusWinSetLoc = 0x4B9F90;   // StatusWin_set_loc(this; tx, ty) RET 8: the panel's info tile (+0x15B4/+0x15B8)
constexpr uintptr_t kVA_CurVeh          = 0x93928C;   // Console+0x23BDC: the unit awaiting orders, -1 none
constexpr uintptr_t kVA_MoveMode        = 0x939288;   // Console+0x23BD8: nonzero = a unit awaits orders
const BYTE kRedrawPro[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x10 };
const BYTE kSetLocPro[15] = { 0x55, 0x8B, 0xEC, 0x8B, 0x45, 0x08, 0x8B, 0x55, 0x0C, 0x89, 0x81, 0xB4, 0x15, 0x00, 0x00 };

// site A: action_go_to, the Path_move < 0 branch.  lea eax,[ecx+ecx*2]; test esi,esi; lea edx,[ecx+eax*4];
//         mov byte ptr [edx*4+0x952839], 0; je +0x21; test edi,edi; jne +0x1D   (ecx = veh id, live after)
constexpr uintptr_t kVA_CheckA  = 0x4CB548;
constexpr uintptr_t kVA_SiteA   = 0x4CB550;   // the 8-byte store
constexpr uintptr_t kVA_ResumeA = 0x4CB558;   // je 0x4CB57B
const BYTE kExpectA[22] = { 0x8D, 0x04, 0x49, 0x85, 0xF6, 0x8D, 0x14, 0x81, 0xC6, 0x04, 0x95, 0x39, 0x28, 0x95, 0x00, 0x00,
                            0x74, 0x21, 0x85, 0xFF, 0x75, 0x1D };
constexpr size_t kDispA = 11;                 // the store's disp32 inside kExpectA: VEH[] + 0x11 (order)
constexpr size_t kSiteALen = 8;

// site B: Console_veh_turn, 100 refused steps.  cmp dl,0x18; jne +9; mov byte ptr [eax+0x952839], 0; jmp +9
//         (eax = veh * 0x34; ecx = veh id)
constexpr uintptr_t kVA_CheckB  = 0x513E22;
constexpr uintptr_t kVA_SiteB   = 0x513E27;   // the 7-byte store
constexpr uintptr_t kVA_ResumeB = 0x513E39;   // mov eax, [MultiplayerActive] ...
const BYTE kExpectB[14] = { 0x80, 0xFA, 0x18, 0x75, 0x09, 0xC6, 0x80, 0x39, 0x28, 0x95, 0x00, 0x00, 0xEB, 0x09 };
constexpr size_t kDispB = 7;                  // the store's disp32 inside kExpectB
constexpr size_t kSiteBLen = 7;
constexpr uint32_t kOrderOff = 0x11;          // VEH.order: the byte both stores clear

BYTE* g_resumeA = nullptr;
BYTE* g_resumeB = nullptr;
uintptr_t g_vehOrder = 0;                     // live VEH[] base + 0x11 (Thinker's modify_unit_limit relocates the array)

// THINKER replaces the whole engine action_go_to (write_jump at its entry 0x4CB310 to its own C++, veh_action.cpp:
// the same logic, the same `order = ORDER_NONE` on a failed step, and the same missing repaint), so site A above is
// dead code there: the bytes stay intact and the check passes, but the stub never runs (audit 2026-10-28). Thinker
// ALSO replaces action() 0x4CF740, the dispatcher that calls action_go_to -- as a direct C++ call, so a chain at
// action_go_to's entry is never reached either (user test 2026-10-29, the same lesson as base_compute). The chain
// therefore sits at action()'s ENTRY: the E9 Thinker wrote there is re-pointed at a wrapper that calls Thinker's
// action and repaints when the unit's order was cleared short of its goal. Engine bytes only; the address comes
// from Thinker's own jump, so it follows any Thinker build.
constexpr uintptr_t kVA_Action = 0x4CF740;    // int __cdecl action(int veh_id): the order dispatcher
constexpr uint32_t  kOrderMoveTo = 0x18;      // ORDER_MOVE_TO (0x40 = the reset flag rides on top: 0x58)
using FAction = int(__cdecl*)(int);
FAction g_actionNext = nullptr;               // Thinker's action()
void __cdecl RepaintIfAwaiting(int veh);      // below

int __cdecl WrapAction(int veh)
{
    int16_t x0 = 0, y0 = 0, wx = 0, wy = 0;
    BYTE order0 = 0;
    const bool ok = ModernCtlVehOk(veh);
    if (ok) {
        const BYTE* u = ModernCtlVehs() + static_cast<size_t>(veh) * 0x34;
        memcpy(&x0, u, 2); memcpy(&y0, u + 2, 2);
        memcpy(&wx, u + 0x14, 2); memcpy(&wy, u + 0x1C, 2);               // waypoint_x[0] / waypoint_y[0]
        order0 = u[kOrderOff];
    }
    const int r = g_actionNext(veh);
    if (!ok || order0 == 0 || !ModernCtlVehOk(veh)) return r;
    const BYTE* u = ModernCtlVehs() + static_cast<size_t>(veh) * 0x34;
    if (u[kOrderOff] != 0) return r;                                         // the order is still running
    // The engine site fired for EVERY order the failed-step branch cleared (audit 2026-10-29). A go-to that ended
    // ON its waypoint completed normally and the loop's own redraw follows; any other cleared order was given up.
    const bool moveTo = (order0 & 0x3F) == kOrderMoveTo;
    int16_t x1, y1;
    memcpy(&x1, u, 2); memcpy(&y1, u + 2, 2);
    if (!moveTo || !(x1 == wx && y1 == wy)) RepaintIfAwaiting(veh);
    return r;
}

// The expected bytes with the array operand masked: Thinker's unit-array relocation rewrites that disp32 in
// both stores (the byte check used to fail there and the fix went inert under Thinker -- user decision 2026-10-28:
// follow the relocation, the way modernctl's resolver does).
bool MatchesExceptDisp(const BYTE* live, const BYTE* expect, size_t n, size_t dispOff)
{
    for (size_t i = 0; i < n; ++i) {
        if (i >= dispOff && i < dispOff + 4) continue;
        if (live[i] != expect[i]) return false;
    }
    return true;
}

uint32_t Disp32(const BYTE* p)
{
    uint32_t v;
    memcpy(&v, p, 4);
    return v;
}

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

// The repaint, gated on the unit being the one the player is giving orders to (action_go_to also runs for
// the AI's units and for automated ones; their panel is not showing stale moves). StatusWin_draw_status shows
// the active unit only while it stands on the panel's info tile (+0x15B4/+0x15B8, compared against the unit's
// x/y at 0x4B6xxx); the crawl moved the unit off that tile and a bare repaint showed the old square's info
// instead (user 2026-10-10: "deselected from the HUD"). So the tile follows the unit first, the way
// Console_set_move does (StatusWin_set_loc @0x5117CC before its StatusWin_redraw).
void __cdecl RepaintIfAwaiting(int veh)
{
    if (!ModernCtlVehOk(veh) || *reinterpret_cast<int*>(At(kVA_CurVeh)) != veh || *reinterpret_cast<int*>(At(kVA_MoveMode)) == 0) return;
    const BYTE* u = ModernCtlVehs() + static_cast<size_t>(veh) * 0x34;     // Thinker's modify_unit_limit relocates the array
    int16_t x, y;
    memcpy(&x, u, 2);
    memcpy(&y, u + 2, 2);
    reinterpret_cast<void(__fastcall*)(BYTE*, void*, int, int)>(At(kVA_StatusWinSetLoc))(At(kVA_StatusWin), nullptr, x, y);
    reinterpret_cast<void(__fastcall*)(BYTE*, void*)>(At(kVA_StatusWinRedraw))(At(kVA_StatusWin), nullptr);
}

__declspec(naked) void StubGoToGivenUp()          // site A: ecx = veh id
{
    __asm {
        push ebx                                   // push/mov/pop leave EFLAGS alone: the je at the resume reads the
        mov  ebx, dword ptr [g_vehOrder]           // flags of the earlier test
        mov  byte ptr [ebx + edx*4], 0             // the displaced store: veh.order = 0, through the LIVE array base
        pop  ebx
        pushfd
        pushad
        push ecx
        call RepaintIfAwaiting
        add  esp, 4
        popad
        popfd
        jmp  dword ptr [g_resumeA]                 // 0x4CB558
    }
}

__declspec(naked) void StubCancelAfterRetries()   // site B: eax = veh * 0x34, ecx = veh id
{
    __asm {
        push ebx
        mov  ebx, dword ptr [g_vehOrder]
        mov  byte ptr [ebx + eax], 0               // the displaced store: veh.order = 0, through the LIVE array base
        pop  ebx
        pushfd
        pushad
        push ecx
        call RepaintIfAwaiting
        add  esp, 4
        popad
        popfd
        jmp  dword ptr [g_resumeB]                 // 0x513E39
    }
}

bool WriteJmp(BYTE* site, size_t len, const void* target)
{
    BYTE patch[8] = { 0xE9, 0, 0, 0, 0, 0x90, 0x90, 0x90 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(target) - (reinterpret_cast<uintptr_t>(site) + 5));
    memcpy(patch + 1, &rel, 4);
    DWORD old;
    if (!VirtualProtect(site, len, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(site, patch, len);
    VirtualProtect(site, len, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, len);
    return true;
}

} // namespace

void InstallHudMovesFix()
{
    if (!MatchesExceptDisp(At(kVA_CheckA), kExpectA, sizeof kExpectA, kDispA) ||
        !MatchesExceptDisp(At(kVA_CheckB), kExpectB, sizeof kExpectB, kDispB) ||
        memcmp(At(kVA_StatusWinRedraw), kRedrawPro, sizeof kRedrawPro) != 0 ||
        memcmp(At(kVA_StatusWinSetLoc), kSetLocPro, sizeof kSetLocPro) != 0) {
        UimodLog("[uimod] hudmovesfix: unexpected bytes in action_go_to / Console_veh_turn / StatusWin_redraw -> HUD moves fix NOT installed\n");
        return;
    }
    // Both stores must address the SAME array the resolver finds (VEH[] + 0x11): stock 0x952839, or Thinker's
    // relocated array. A disagreement means an operand rewrite this module does not understand.
    const uint32_t dispA = Disp32(At(kVA_CheckA) + kDispA);
    const uint32_t dispB = Disp32(At(kVA_CheckB) + kDispB);
    const uintptr_t live = reinterpret_cast<uintptr_t>(ModernCtlVehs()) + kOrderOff;
    if (dispA != dispB || dispA != live) {
        char buf[200];
        _snprintf_s(buf, sizeof buf, _TRUNCATE,
                    "[uimod] hudmovesfix: the order stores address 0x%08X / 0x%08X but the unit array resolves to 0x%08X -> HUD moves fix NOT installed\n",
                    dispA, dispB, static_cast<unsigned>(live));
        UimodLog(buf);
        return;
    }
    g_vehOrder = live;
    g_resumeA = At(kVA_ResumeA);
    g_resumeB = At(kVA_ResumeB);
    // Site A lives inside the engine's action_go_to. Under Thinker that function is never entered (its entry is
    // Thinker's E9), so the give-up repaint is chained at the entry instead and the dead site is left alone.
    BYTE* entry = At(kVA_Action);
    uintptr_t tlo = 0, thi = 0;
    bool thinkerAction = false;
    if (entry[0] == 0xE9 && ThinkerRange(&tlo, &thi)) {
        int32_t rel; memcpy(&rel, entry + 1, 4);
        const uintptr_t target = reinterpret_cast<uintptr_t>(entry + 5 + rel);
        thinkerAction = target >= tlo && target < thi;
        if (thinkerAction) g_actionNext = reinterpret_cast<FAction>(target);
    }
    const bool siteA = thinkerAction ? WriteJmp(entry, 5, &WrapAction)
                                     : WriteJmp(At(kVA_SiteA), kSiteALen, &StubGoToGivenUp);
    if (!siteA || !WriteJmp(At(kVA_SiteB), kSiteBLen, &StubCancelAfterRetries)) {
        UimodLog("[uimod] hudmovesfix: VirtualProtect failed -> HUD moves fix NOT installed\n");
        return;
    }
    if (thinkerAction) {
        char buf[200];
        _snprintf_s(buf, sizeof buf, _TRUNCATE,
                    "[uimod] hudmovesfix: Thinker replaces action() and action_go_to (entry 0x4CF740 -> 0x%08X) -> the give-up "
                    "repaint is chained at action()'s entry; the in-function site is left to Thinker\n",
                    static_cast<unsigned>(reinterpret_cast<uintptr_t>(g_actionNext)));
        UimodLog(buf);
    }
    if (live != 0x952828 + kOrderOff) {
        char buf[160];
        _snprintf_s(buf, sizeof buf, _TRUNCATE,
                    "[uimod] hudmovesfix: unit array relocated to 0x%08X (Thinker) -> the stores follow it\n",
                    static_cast<unsigned>(live - kOrderOff));
        UimodLog(buf);
    }
    UimodLog("[uimod] hudmovesfix: the HUD unit panel repaints when a go-to is given up\n");
}
