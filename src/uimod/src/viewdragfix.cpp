// viewdragfix.cpp -- in view mode a drag drew the move line but the release only selected (base-game bug).
//
// go_timer 0x50F170 (the hold timer MapWin_on_left_down starts) arms the drag line. Its plain-drag branch in VIEW
// mode (edi == 1, MoveMode 0x939288 == 0, DAT_009393CC == 0) @0x50F21C..0x50F2B4 still looks for a unit: the
// current one if it stands on the cursor tile, selectable, order-less and unflagged, else veh_find at the cursor
// tile; any hit selects it (CurVeh := found) and arms the line (overlay shown, Console+0x1DD80 = 1). But the
// release path in view mode selects instead of committing the go-to, so the line promised a move that never
// came (user 2026-10-10, confirmed vanilla; the same state the game loaded into before hudsync). In move mode
// (MoveMode != 0) the branch is bypassed at 0x50F20E and the drag works as designed.
// Fix: the first instruction of the view-mode search @0x50F21C (mov eax,[CurVeh], 5 B) becomes a jmp to the
// branch's own cancel exit @0x50F3B8 (call go_reset; epilogue): a view-mode drag arms nothing, so a press and
// release there is the plain click that selects the unit -- which is what the release did anyway. Ctrl drags
// (edi == 9, the rally line) and DAT_009393CC paths are untouched; modernctl's anchors at 0x50F296/0x50F2A9 stay.
#include "viewdragfix.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_Check  = 0x50F203;   // cmp edi,1; jne arm; test eax,eax; jne arm; test ecx,ecx; jne arm; mov eax,[CurVeh]; test eax,eax; jl
constexpr uintptr_t kVA_Site   = 0x50F21C;   // mov eax, dword ptr [0x93928C]
constexpr uintptr_t kVA_Cancel = 0x50F3B8;   // call go_reset; pop edi; pop esi; pop ebx; mov esp,ebp; pop ebp; ret
const BYTE kExpect[34] = { 0x83, 0xFF, 0x01, 0x0F, 0x85, 0xE5, 0x00, 0x00, 0x00, 0x85, 0xC0, 0x0F, 0x85, 0xDD, 0x00, 0x00, 0x00,
                           0x85, 0xC9, 0x0F, 0x85, 0xD5, 0x00, 0x00, 0x00, 0xA1, 0x8C, 0x92, 0x93, 0x00, 0x85, 0xC0, 0x7C, 0x53 };
const BYTE kCancelBytes[12] = { 0xE8, 0x93, 0xFB, 0xFF, 0xFF, 0x5F, 0x5E, 0x5B, 0x8B, 0xE5, 0x5D, 0xC3 };
constexpr size_t kSiteLen = 5;

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000); }

} // namespace

void InstallViewDragFix()
{
    if (memcmp(At(kVA_Check), kExpect, sizeof kExpect) != 0 || memcmp(At(kVA_Cancel), kCancelBytes, sizeof kCancelBytes) != 0) {
        UimodLog("[uimod] viewdragfix: unexpected bytes in go_timer -> view-mode drag fix NOT installed\n");
        return;
    }
    BYTE* site = At(kVA_Site);
    BYTE patch[kSiteLen] = { 0xE9, 0, 0, 0, 0 };
    const int32_t rel = static_cast<int32_t>(kVA_Cancel - (kVA_Site + 5));      // same image: no rebasing needed
    memcpy(patch + 1, &rel, 4);
    DWORD old;
    if (!VirtualProtect(site, kSiteLen, PAGE_EXECUTE_READWRITE, &old)) {
        UimodLog("[uimod] viewdragfix: VirtualProtect failed -> view-mode drag fix NOT installed\n");
        return;
    }
    memcpy(site, patch, kSiteLen);
    VirtualProtect(site, kSiteLen, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, kSiteLen);
    UimodLog("[uimod] viewdragfix: a view-mode drag arms no move line (press and release select, as before)\n");
}
