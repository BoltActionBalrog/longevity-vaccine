// uimod reply-row text indent: the channel between a reply button's left edge and its text scales.
//
// Type-16 dialog rows (the diplomacy replies, the Quit menu, ...) are painted by FUN_0060d750. The
// text rect's left edge is row.x + Dialog[+0x34], the text indent: a native 3 set at 0x404D3F. Row
// height, font and vertical centring all follow g_popup_scale_num; this one constant stayed a literal
// 3 px, so at 4K the text hugs the button edge (4 px measured against vanilla x 2.5 = 10).
//
// Port of scaling_laws.t16_row_text_indent: scale the value IN-REGISTER at the painter's read
//
//   0x0060DB8B  8B 54 31 34   mov edx,[ecx+esi+0x34]
//   0x0060DB8F  03 FA         add edi,edx              ; 6 bytes -> jmp stub + nop
//
// and never store it back: the stored field is also the F term of the type-16 width calc
// (scaling_laws.t16_row_measure_width), which works in native space.
//
// g lives at 0x668740: the patcher's g_popup_scale_num, plain zeroed .data on the unpatched exe, where
// g <= 16 makes the stub the engine's own two instructions. No cave VA is referenced.

#include "rowindent.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kImageBase     = 0x400000;
constexpr uintptr_t kVA_IndentSite = 0x0060DB8B;
constexpr uintptr_t kVA_PopupScaleNum = 0x00668740;
const BYTE kExpect[6] = { 0x8B, 0x54, 0x31, 0x34, 0x03, 0xFA };

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}

const int* g_scaleNum = nullptr;
void*      g_resume   = nullptr;

__declspec(naked) void StubRowIndent()
{
    __asm {
        mov  edx, dword ptr [ecx + esi + 0x34]
        push eax
        mov  eax, dword ptr [g_scaleNum]
        mov  eax, dword ptr [eax]
        cmp  eax, 16
        jle  ri_native
        imul edx, eax                       // scale_px: (2*v*g + 15) >> 5  (half_down)
        lea  edx, [edx + edx + 15]
        sar  edx, 5
    ri_native:
        pop  eax
        add  edi, edx                       // last: the engine's own flags
        jmp  dword ptr [g_resume]
    }
}

// ---- the line-count divisor must be the width the text is DRAWN in -------------------------------------
// Dialog_type16_calc 0x60D380 gives each row  lines = W / budget + 1  at
//
//   0x0060D5FA  99 F7 FD 40 47   cdq ; idiv ebp ; inc eax ; inc edi        (ebp = budget, eax = W)
//
// with budget = [+0x2C]/cols - 2*[+0x40] - [+0x34]. The painter draws the text in [+0x64] - indent, and
// [+0x64] = budget + [+0x34] - gap[+0x44]: the engine's budget is `gap` px wider than the drawn width (a
// vanilla slip, 3 px), and our scaled indent above widens that to gap + (indent_dev - indent). A reply whose
// width lands in that window counts as one line and is clipped at the button's right edge (measured
// 2026-09-20: W 1496 vs budget 1498 @g40, drawn width ~1488). Port of scaling_laws.t16_row_text_budget.
// Anchored popups only (pops_18's BasePop [0x9BC074] with +0xA14 set = the diplomacy talk window): that is
// where W and the budget are both DEVICE; ordinary popups divide native by native and stay as verified.
constexpr uintptr_t kVA_LineCountSite = 0x0060D5FA;
constexpr uintptr_t kVA_AnchoredPop   = 0x009BC074;
const BYTE kExpectDiv[5] = { 0x99, 0xF7, 0xFD, 0x40, 0x47 };
void* g_divResume = nullptr;

int __cdecl T16Divisor(const BYTE* self, int budget)
{
    const int g = *g_scaleNum;
    if (g <= 16 || budget <= 0 || budget >= 100000) return budget;
    const BYTE* pop = *reinterpret_cast<BYTE* const*>(At(kVA_AnchoredPop));
    if (!pop || *reinterpret_cast<const uint32_t*>(pop + 0xA14) == 0) return budget;
    if (static_cast<uintptr_t>(self - pop) >= 0x3200) return budget;
    const BYTE* dlg = self + *reinterpret_cast<const int32_t*>(*reinterpret_cast<BYTE* const*>(self) + 8);
    const int indent = *reinterpret_cast<const int32_t*>(dlg + 0x34);
    const int gap    = *reinterpret_cast<const int32_t*>(dlg + 0x44);
    const int drawn  = budget - gap - (((2 * indent * g + 15) >> 5) - indent);
    return drawn > 0 ? drawn : budget;
}

__declspec(naked) void StubLineCount()
{
    __asm {
        push eax
        push ecx
        push ebp
        push esi
        call T16Divisor
        add  esp, 8
        mov  edx, eax                       // the divisor; edx is dead (cdq next)
        pop  ecx
        pop  eax
        push ebp
        mov  ebp, edx
        cdq
        idiv ebp
        pop  ebp                            // the loop reuses the engine's budget for the next row
        inc  eax
        inc  edi
        jmp  dword ptr [g_divResume]
    }
}

} // namespace

void InstallRowIndent()
{
    BYTE* p = At(kVA_IndentSite);
    if (memcmp(p, kExpect, sizeof kExpect) != 0) {
        UimodLog("[uimod] rowindent: unexpected bytes at 0x60DB8B -> reply-row text indent stays native\n");
        return;
    }
    g_scaleNum = reinterpret_cast<const int*>(At(kVA_PopupScaleNum));
    g_resume   = p + sizeof kExpect;
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubRowIndent) -
                                             (reinterpret_cast<uintptr_t>(p) + 5));
    DWORD old;
    VirtualProtect(p, sizeof kExpect, PAGE_EXECUTE_READWRITE, &old);
    p[0] = 0xE9;
    memcpy(p + 1, &rel, 4);
    p[5] = 0x90;
    VirtualProtect(p, sizeof kExpect, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, sizeof kExpect);
    UimodLog("[uimod] rowindent: reply-row text indent scales with the UI (1 site)\n");

    BYTE* d = At(kVA_LineCountSite);
    if (memcmp(d, kExpectDiv, sizeof kExpectDiv) != 0) {
        UimodLog("[uimod] rowindent: unexpected bytes at 0x60D5FA -> reply line count keeps the engine's budget\n");
        return;
    }
    g_divResume = d + sizeof kExpectDiv;
    const int32_t rel2 = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubLineCount) -
                                              (reinterpret_cast<uintptr_t>(d) + 5));
    VirtualProtect(d, sizeof kExpectDiv, PAGE_EXECUTE_READWRITE, &old);
    d[0] = 0xE9;
    memcpy(d + 1, &rel2, 4);
    VirtualProtect(d, sizeof kExpectDiv, old, &old);
    FlushInstructionCache(GetCurrentProcess(), d, sizeof kExpectDiv);
    UimodLog("[uimod] rowindent: reply line count divides by the drawn text width (1 site)\n");
}
