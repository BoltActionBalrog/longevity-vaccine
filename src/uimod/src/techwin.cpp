// uimod tech breakthrough window: text boxes open at the TOP (vanilla bug).
//
// "OUR RESEARCHERS HAVE MADE A BREAKTHROUGH" (NetTechWin 0x811E40) shows its quote / description and
// its four unlock lists in TextScroll widgets. TextScroll is the engine's chat-log widget: whenever
// TextScroll_finish (0x629490) finds the text overflowing (scrollbar shown) it walks back from the
// LAST line to fill one page, parks the bar there and starts drawing from that line. Right for a
// chat log; wrong for an article -- the long tech description opens on its final page with the
// thumb at the bottom, and an overflowing unlock list would open on its last entries.
//
// Fix: after the engine lays the text out, put the bar back at its first position and redraw, using
// the engine's own calls in the engine's own order (ScrollBar_set_pos, first_line := bar pos,
// vtbl+0xF8). Only when the bar is shown; a box that fits is untouched.
//
//   0x48454D  NetTechWin_exec              call TextScroll_finish   (quote, at open)
//   0x483F7F  NetTechWin_on_group_changed  call TextScroll_finish   (quote <-> description toggle)
//   0x484447  NetTechWin_exec              call help_tech_info      (fills unlock list `idx`; every
//                                                                    added line re-runs finish)
//
// Three E8 retargets, byte-checked, no cave and no patcher artifact referenced: the code is
// identical in the PRACX-patched and the unpatched exe, so this installs on both.

#include "techwin.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kImageBase       = 0x400000;
constexpr uintptr_t kTextScrollFinish = 0x629490;   // thiscall(ecx = TextScroll)
constexpr uintptr_t kScrollBarSetPos  = 0x605D20;   // thiscall(ecx = ScrollBar, pos) RET 4
constexpr uintptr_t kHelpTechInfo     = 0x44B9E0;   // cdecl(cb, tech, faction, idx)
constexpr uintptr_t kNetTechWin       = 0x811E40;
constexpr size_t    kListTs0          = 0x2DA4;     // NetTechWin +0x2DA4 TextScroll list_ts[4]
constexpr size_t    kListTsStride     = 0x2BA0;

constexpr size_t kTsBar       = 0xA20;    // TextScroll +0xA20  embedded ScrollBar
constexpr size_t kTsFirstLine = 0xA1C;    // TextScroll +0xA1C  first drawn line
constexpr size_t kBarShown    = 0x9C;     // Win +0x9C bit0     (TextScroll +0xABC: the bit finish/draw test)
constexpr size_t kBarPos      = 0xA2C;    // ScrollBar +0xA2C   (TextScroll +0x144C)
constexpr size_t kVtRedraw    = 0xF8;

constexpr uint32_t kFinishSites[] = { 0x48454D, 0x483F7F };
constexpr uint32_t kFillSite      = 0x484447;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}

using ThisFn0 = void(__fastcall*)(void* self, void* edx);
using ThisFn1 = void(__fastcall*)(void* self, void* edx, int a1);
using FillFn  = int(__cdecl*)(void* cb, int tech, int faction, int idx);

void TopAnchor(BYTE* ts)
{
    BYTE* bar = ts + kTsBar;
    if (!(bar[kBarShown] & 1)) return;                       // text fits: nothing was scrolled
    reinterpret_cast<ThisFn1>(At(kScrollBarSetPos))(bar, nullptr, 0);   // clamps to the bar's min, redraws the bar
    int32_t pos;
    memcpy(&pos, bar + kBarPos, sizeof pos);
    memcpy(ts + kTsFirstLine, &pos, sizeof pos);             // what TextScroll_finish does after its own set_pos
    void** vtbl;
    memcpy(&vtbl, ts, sizeof vtbl);
    reinterpret_cast<ThisFn0>(vtbl[kVtRedraw / sizeof(void*)])(ts, nullptr);
}

// drop-in for `call TextScroll_finish` (thiscall, no stack args)
void __fastcall FinishAtTop(void* ts, void* /*edx*/)
{
    reinterpret_cast<ThisFn0>(At(kTextScrollFinish))(ts, nullptr);
    TopAnchor(static_cast<BYTE*>(ts));
}

// drop-in for `call help_tech_info` (cdecl; the caller pops the 4 args)
int __cdecl FillListAtTop(void* cb, int tech, int faction, int idx)
{
    const int r = reinterpret_cast<FillFn>(At(kHelpTechInfo))(cb, tech, faction, idx);
    if (idx >= 0 && idx < 4)
        TopAnchor(At(kNetTechWin) + kListTs0 + static_cast<size_t>(idx) * kListTsStride);
    return r;
}

bool IsCallTo(uintptr_t site, uintptr_t target)
{
    const BYTE* p = At(site);
    if (p[0] != 0xE8) return false;
    int32_t rel;
    memcpy(&rel, p + 1, 4);
    return reinterpret_cast<uintptr_t>(p) + 5 + rel == reinterpret_cast<uintptr_t>(At(target));
}

void Retarget(uintptr_t site, void* fn)
{
    BYTE* p = At(site);
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(fn) - (reinterpret_cast<uintptr_t>(p) + 5));
    DWORD old;
    VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &old);
    memcpy(p + 1, &rel, 4);
    VirtualProtect(p, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 5);
}

} // namespace

void InstallTechWinTopAnchor()
{
    bool ok = IsCallTo(kFillSite, kHelpTechInfo);
    for (uint32_t s : kFinishSites) ok = ok && IsCallTo(s, kTextScrollFinish);
    if (!ok) {
        UimodLog("[uimod] techwin: unexpected bytes at the breakthrough-window sites -> top-anchor disabled\n");
        return;
    }
    for (uint32_t s : kFinishSites) Retarget(s, FinishAtTop);
    Retarget(kFillSite, FillListAtTop);
    UimodLog("[uimod] techwin: breakthrough text boxes open at the top (3 sites)\n");
}
