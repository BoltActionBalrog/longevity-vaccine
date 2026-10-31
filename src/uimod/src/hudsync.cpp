// hudsync.cpp -- the HUD unit panel and the map's pending-unit cursor can disagree (base game).
//
// StatusWin_draw_status 0x4B6570 shows the active unit only while CurVeh 0x93928C stands on the panel's INFO
// TILE (StatusWin+0x15B4/+0x15B8); otherwise it shows that tile's own contents. The only runtime setter of the
// tile is StatusWin_set_loc 0x4B9F90 (unit cycling, Console_set_move, the tile click / menu, "Info on this
// square"). Two engine paths leave the panel behind the map:
//   1. A game loaded with MoveMode == 0 in the save (game_data 0x5A6AC0 stores and restores MoveMode and
//      CurVeh; a turn-start autosave or a save made in view mode carries 0). Console_human_turn 0x514050 then
//      sees ControlTurnMove != 0 (load_daemon sets it to the player's faction) and MoveMode == 0 and takes its
//      view-mode refresh block instead of `Console_set_move(1)` @0x5140E1 -- the unit is pending in the order
//      loop, the cursor sits on it, a drag draws its move line, but the release only selects it (the base
//      game's half-selected state after a load; user 2026-10-10, confirmed vanilla). Thinker's own loader
//      (mod_load_daemon) ends in the same human_turn, so the fix lives there, not in load_daemon.
//   2. A unit made current by the engine itself without a set_loc (the panel keeps the previous square).
// Fix: (a) Console_human_turn's `cmp [MoveMode], edi; je view-block` @0x5140D6 is displaced into a stub that
// first sets MoveMode := 1 when a single-player game resumes a turn with a pending unit (not in the scenario
// editor, not multiplayer), so the engine's own Console_set_move(1) path runs; (b) Console_veh_turn 0x513B90's
// entry syncs the info tile to the unit the loop waits on (move mode: the unit's square; view mode: the map
// cursor the player walked there) and repaints when it differs -- what Console_set_move does.
// The unit array is taken from modernctl's resolver (Thinker's modify_unit_limit relocates it).
#include "hudsync.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

#include "modernctl.h"

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_StatusWin       = 0x8C5568;
constexpr uintptr_t kVA_StatusWinRedraw = 0x4B9EA0;
constexpr uintptr_t kVA_StatusWinSetLoc = 0x4B9F90;
constexpr uintptr_t kVA_CurVeh          = 0x93928C;   // Console+0x23BDC
constexpr uintptr_t kVA_MoveMode        = 0x939288;   // Console+0x23BD8 fUnitNotViewMode
constexpr uintptr_t kVA_CurIdx          = 0x9392B8;   // map cursor history index; the cursor tile = [0x9392C0 + 4*idx], [0x939340 + 4*idx]
constexpr uintptr_t kVA_CurXs           = 0x9392C0, kVA_CurYs = 0x939340;
constexpr size_t kInfoTileX = 0x15B4, kInfoTileY = 0x15B8, kVehOrder = 0x11, kVehStride = 0x34;
const BYTE kRedrawPro[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x10 };
const BYTE kSetLocPro[15] = { 0x55, 0x8B, 0xEC, 0x8B, 0x45, 0x08, 0x8B, 0x55, 0x0C, 0x89, 0x81, 0xB4, 0x15, 0x00, 0x00 };

// (b) Console_veh_turn entry: push ebp; mov ebp,esp; sub esp,0x14; push ebx; mov ebx,ecx; push esi; push edi;
// mov dword ptr [ebx+0x23BE4], 1
constexpr uintptr_t kVA_VehTurn       = 0x513B90;
constexpr uintptr_t kVA_VehTurnResume = 0x513B96;
const BYTE kVehTurnPro[21] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x14, 0x53, 0x8B, 0xD9, 0x56, 0x57,
                               0xC7, 0x83, 0xE4, 0x3B, 0x02, 0x00, 0x01, 0x00, 0x00, 0x00 };
constexpr size_t kVehTurnLen = 6;

// (a) Console_human_turn: cmp [ControlTurnMove],edi; jne +0x17; push edi; mov ecx,esi; mov [esi+0x23BDC],-1;
// call Console_set_move; jmp; cmp [MoveMode],edi; je view-block; push ebx; mov ecx,esi; call Console_set_move; jmp
// (esi = Console, edi = 0, ebx = 1)
constexpr uintptr_t kVA_HtCheck      = 0x5140B7;
constexpr uintptr_t kVA_HtSite       = 0x5140D6;   // cmp dword ptr [0x939288], edi; je 0x5140E8 (8 B)
constexpr uintptr_t kVA_HtResumeMove = 0x5140DE;   // push ebx; mov ecx,esi; call Console_set_move(1)
constexpr uintptr_t kVA_HtResumeView = 0x5140E8;   // the view-mode refresh block
const BYTE kHtExpect[49] = { 0x39, 0x3D, 0x70, 0x20, 0x9B, 0x00, 0x75, 0x17, 0x57, 0x8B, 0xCE,
                             0xC7, 0x86, 0xDC, 0x3B, 0x02, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xE8, 0x4F, 0xD4, 0xFF, 0xFF,
                             0xE9, 0x81, 0x00, 0x00, 0x00, 0x39, 0x3D, 0x88, 0x92, 0x93, 0x00, 0x74, 0x0A, 0x53, 0x8B, 0xCE,
                             0xE8, 0x3A, 0xD4, 0xFF, 0xFF, 0xEB, 0x6F };
constexpr size_t kHtLen = 8;

BYTE* g_resume = nullptr;
BYTE* g_htMove = nullptr;
BYTE* g_htView = nullptr;

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000); }
int   Rd(uintptr_t va) { return *reinterpret_cast<int*>(At(va)); }

// At Console_veh_turn's entry: the square the panel must show for the unit this loop is about to wait on. A
// unit with a standing order (go-to, automation) is executed, not waited on: no repaint for those.
void __cdecl SyncOnVehTurn()
{
    const int veh = Rd(kVA_CurVeh);
    if (!ModernCtlVehOk(veh)) return;
    const BYTE* u = ModernCtlVehs() + static_cast<size_t>(veh) * kVehStride;
    if (u[kVehOrder] != 0) return;
    int x, y;
    if (Rd(kVA_MoveMode) != 0) {
        int16_t sx, sy;
        memcpy(&sx, u, 2);
        memcpy(&sy, u + 2, 2);
        x = sx; y = sy;
    } else {
        const int idx = Rd(kVA_CurIdx);
        if (idx < 0 || idx > 31) return;
        x = Rd(kVA_CurXs + idx * 4); y = Rd(kVA_CurYs + idx * 4);
    }
    BYTE* sw = At(kVA_StatusWin);
    if (*reinterpret_cast<int*>(sw + kInfoTileX) == x && *reinterpret_cast<int*>(sw + kInfoTileY) == y) return;
    reinterpret_cast<void(__fastcall*)(BYTE*, void*, int, int)>(At(kVA_StatusWinSetLoc))(sw, nullptr, x, y);
    reinterpret_cast<void(__fastcall*)(BYTE*, void*)>(At(kVA_StatusWinRedraw))(sw, nullptr);
}

__declspec(naked) void StubVehTurn()
{
    __asm {
        push ecx                       // this = Console
        call SyncOnVehTurn
        pop  ecx
        push ebp                       // the displaced prologue
        mov  ebp, esp
        sub  esp, 0x14
        jmp  dword ptr [g_resume]      // 0x513B96
    }
}

// Console_human_turn, a turn in progress (ControlTurnMove != 0): a single-player game with a pending unit
// resumes in move mode. esi = Console; edi = 0; eax is free (set_move's argument is ebx).
__declspec(naked) void StubHumanTurnMode()
{
    __asm {
        push eax
        mov  eax, dword ptr ds:[0x93F660]       // MultiplayerActive: a network game keeps the engine's state
        test eax, eax
        jne  keep
        mov  eax, dword ptr ds:[0x9A64C0]       // GameState & 0x80: the scenario editor
        test al, 0x80
        jne  keep
        mov  eax, dword ptr [esi + 0x23BDC]     // CurVeh: a pending unit to resume on
        test eax, eax
        js   keep
        mov  dword ptr ds:[0x939288], 1         // MoveMode
    keep:
        pop  eax
        cmp  dword ptr ds:[0x939288], edi       // the displaced test
        je   view
        jmp  dword ptr [g_htMove]               // 0x5140DE: Console_set_move(1)
    view:
        jmp  dword ptr [g_htView]               // 0x5140E8: the view-mode block
    }
}

bool WriteJmp(BYTE* site, size_t len, const void* target)
{
    BYTE patch[16];
    memset(patch, 0x90, sizeof patch);
    patch[0] = 0xE9;
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

void InstallHudSync()
{
    if (memcmp(At(kVA_VehTurn), kVehTurnPro, sizeof kVehTurnPro) != 0 ||
        memcmp(At(kVA_StatusWinRedraw), kRedrawPro, sizeof kRedrawPro) != 0 ||
        memcmp(At(kVA_StatusWinSetLoc), kSetLocPro, sizeof kSetLocPro) != 0) {
        UimodLog("[uimod] hudsync: unexpected bytes in Console_veh_turn / StatusWin -> HUD unit-panel sync NOT installed\n");
    } else {
        g_resume = At(kVA_VehTurnResume);
        if (WriteJmp(At(kVA_VehTurn), kVehTurnLen, &StubVehTurn))
            UimodLog("[uimod] hudsync: the HUD unit panel follows the unit awaiting orders\n");
        else
            UimodLog("[uimod] hudsync: VirtualProtect failed -> HUD unit-panel sync NOT installed\n");
    }

    if (memcmp(At(kVA_HtCheck), kHtExpect, sizeof kHtExpect) != 0) {
        UimodLog("[uimod] hudsync: unexpected bytes in Console_human_turn -> a loaded game may still resume half-selected\n");
        return;
    }
    g_htMove = At(kVA_HtResumeMove);
    g_htView = At(kVA_HtResumeView);
    if (WriteJmp(At(kVA_HtSite), kHtLen, &StubHumanTurnMode))
        UimodLog("[uimod] hudsync: a resumed turn with a pending unit enters move mode (the unit is selected for real)\n");
    else
        UimodLog("[uimod] hudsync: VirtualProtect failed on Console_human_turn -> a loaded game may still resume half-selected\n");
}
