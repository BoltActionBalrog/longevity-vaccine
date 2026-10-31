// praxdrag.cpp -- the map drag-scroll button under PRACX (see praxdrag.h).
//
// PRACXWinProc (refs\pracx\shared\pracx.cpp:1286-1318) swallows WM_RBUTTONDOWN while the map shows, scrolls on
// mouse moves while m_fRightButtonDown (PRACXCheckScroll, :991-1100, which re-reads GetAsyncKeyState(VK_RBUTTON)
// at :1014 and :1090), and on WM_RBUTTONUP either ends the drag or re-synthesises the DOWN+UP pair into the game
// WinProc. prax.dll 1.11 (md5 89a0037b stock, 0f189a32 with the patcher's scroll-zone fix -- identical bytes at
// these six sites, all disjoint from patches_prax.yaml's), module-relative offsets:
//   0x08D1E  cmp dword [ebp+0xC], 0x204 ; jne       the DOWN compare
//   0x08D46  cmp dword [ebp+0xC], 0x205 ; jne       the UP compare
//   0x08D90  push 0x204                             re-synthesised DOWN
//   0x08DAC  push 0x205                             re-synthesised UP
//   0x05161  push 2 (VK_RBUTTON) ; call [GetAsyncKeyState]   drag start (> 2.5 px)
//   0x05595  push 2 (VK_RBUTTON) ; call [GetAsyncKeyState]   drag keep-alive
// The two `call [abs32]` operands are RELOCATED (prax.dll has DYNAMIC_BASE; ASLR moves it), so they are checked
// against the live module base + 0x341E8, never against the on-disk 0x100341E8.
// middle = 0x207/0x208 and VK_MBUTTON (4) everywhere (a quick middle click then synthesises 0x207/0x208, which
// the game WinProc hands to DefWindowProc); none = the two compares test 0x3FFF, so PRACX never sets
// m_fRightButtonDown and every right message takes its pass-through branch (coordinates already rewritten).

#include "praxdrag.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kPx_CmpDown  = 0x08D1E;
constexpr uintptr_t kPx_CmpUp    = 0x08D46;
constexpr uintptr_t kPx_PushDown = 0x08D90;
constexpr uintptr_t kPx_PushUp   = 0x08DAC;
constexpr uintptr_t kPx_Vk1      = 0x05161;
constexpr uintptr_t kPx_Vk2      = 0x05595;
constexpr uintptr_t kPx_GetAsyncKeyStateIat = 0x341E8;   // the IAT slot both `call [abs32]`s read

const BYTE kCleanCmpDown[9]  = { 0x81, 0x7D, 0x0C, 0x04, 0x02, 0x00, 0x00, 0x75, 0x1F };
const BYTE kCleanCmpUp[9]    = { 0x81, 0x7D, 0x0C, 0x05, 0x02, 0x00, 0x00, 0x75, 0x72 };
const BYTE kCleanPushDown[5] = { 0x68, 0x04, 0x02, 0x00, 0x00 };
const BYTE kCleanPushUp[5]   = { 0x68, 0x05, 0x02, 0x00, 0x00 };
const BYTE kCleanVk[4]       = { 0x6A, 0x02, 0xFF, 0x15 };      // push 2; call [abs32 -> checked live]

constexpr uint32_t kMsgNever = 0x3FFF;        // no such message: the compare can never match

BYTE* g_px = nullptr;
bool  g_ok = false;
int   g_applied = -1;

bool VkSiteOk(uintptr_t off)
{
    if (memcmp(g_px + off, kCleanVk, sizeof kCleanVk) != 0) return false;
    uint32_t abs;
    memcpy(&abs, g_px + off + 4, 4);
    return abs == reinterpret_cast<uint32_t>(g_px + kPx_GetAsyncKeyStateIat);
}

bool Write(uintptr_t off, const void* bytes, size_t n)
{
    BYTE* p = g_px + off;
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return true;
}

} // namespace

void InstallPraxDrag(bool pracx)
{
    g_px = pracx ? reinterpret_cast<BYTE*>(GetModuleHandleA("prax.dll")) : nullptr;
    if (!g_px) {
        UimodLog("[uimod] praxdrag: no PRACX -> map drag button not configurable\n");
        return;
    }
    const bool ok = memcmp(g_px + kPx_CmpDown, kCleanCmpDown, sizeof kCleanCmpDown) == 0 &&
                    memcmp(g_px + kPx_CmpUp, kCleanCmpUp, sizeof kCleanCmpUp) == 0 &&
                    memcmp(g_px + kPx_PushDown, kCleanPushDown, sizeof kCleanPushDown) == 0 &&
                    memcmp(g_px + kPx_PushUp, kCleanPushUp, sizeof kCleanPushUp) == 0 &&
                    VkSiteOk(kPx_Vk1) && VkSiteOk(kPx_Vk2);
    if (!ok) {
        UimodLog("[uimod] praxdrag: prax.dll byte check FAILED -> map drag button not configurable\n");
        return;
    }
    g_ok = true;
    g_applied = 2;                            // the stock bytes = the right button
    UimodLog("[uimod] praxdrag: bound to PRACX's drag-scroll sites\n");
}

bool PraxDragAvailable() { return g_ok; }

void PraxDragApply(int button)
{
    if (!g_ok) return;
    if (button < 0 || button > 2) button = 2;
    if (button == g_applied) return;
    const uint32_t down = button == 2 ? 0x204u : button == 1 ? 0x207u : kMsgNever;
    const uint32_t up   = button == 2 ? 0x205u : button == 1 ? 0x208u : kMsgNever;
    const uint32_t pushDown = button == 1 ? 0x207u : 0x204u;     // 'none' never reaches the pushes
    const uint32_t pushUp   = button == 1 ? 0x208u : 0x205u;
    const BYTE vk = button == 1 ? 4 : 2;                           // VK_MBUTTON / VK_RBUTTON
    const bool ok = Write(kPx_CmpDown + 3, &down, 4) && Write(kPx_CmpUp + 3, &up, 4) &&
                    Write(kPx_PushDown + 1, &pushDown, 4) && Write(kPx_PushUp + 1, &pushUp, 4) &&
                    Write(kPx_Vk1 + 1, &vk, 1) && Write(kPx_Vk2 + 1, &vk, 1);
    if (!ok) { UimodLog("[uimod] praxdrag: VirtualProtect failed -> drag button left as it was\n"); return; }
    g_applied = button;
    char msg[96];
    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] praxdrag: map drag button = %s\n",
                button == 2 ? "right" : button == 1 ? "middle" : "none");
    UimodLog(msg);
}
