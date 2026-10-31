// blinkfix.cpp -- the selected unit's blink leaves part of a wide sprite standing (base-game bug).
//
// blink_timer 0x50EA40 toggles the blink state and calls draw_cursor 0x46AE00, which redraws the selected
// tile with MapWin_draw_radius(x, y, RADIUS 0, 2) 0x46A2A0: MapWin_gen_radius regenerates that ONE tile (the
// unit hidden on the off tick), the cursor diamond goes on top, and the tile's rect is soft-updated. A unit
// sprite wider than its tile box (the big ship chassis, long rovers: a cruiser is ~1.3 tile widths) paints
// past the box on the on tick, and nothing repaints the overhang on the off tick -- a vertical sliver of the
// unit stays solid while the rest blinks (user shots 2026-10-10 14:34:41/42, confirmed on the vanilla exe).
// MapWin_draw_cursor 0x46AD60 (cursor moves, set_cursor, the keyboard cursor) draws the same way.
// Fix: both `push 0` radius operands become 1, so each redraw regenerates the tile and its ring of
// neighbours (the engine's own MapWin_draw_radius_2 draws with radius 1); nine tiles per 150 ms tick.
#include "blinkfix.h"

#include <windows.h>
#include <cstdint>
#include <cstring>

void UimodLog(const char* msg);

namespace {

struct Site { uintptr_t va; BYTE expect[11]; };
// push 2; push 0; push edi; push eax/edx; call MapWin_draw_radius -- the radius is the `6A 00` at +2
const Site kSites[2] = {
    { 0x46AEBC, { 0x6A, 0x02, 0x6A, 0x00, 0x57, 0x50, 0xE8, 0xD9, 0xF3, 0xFF, 0xFF } },   // draw_cursor (blink_timer)
    { 0x46ADE2, { 0x6A, 0x02, 0x6A, 0x00, 0x57, 0x52, 0xE8, 0xB3, 0xF4, 0xFF, 0xFF } },   // MapWin_draw_cursor
};
constexpr size_t kRadiusOff = 3;
constexpr BYTE kRadius = 1;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

} // namespace

void InstallBlinkFix()
{
    for (const Site& s : kSites) {
        if (memcmp(At(s.va), s.expect, sizeof s.expect) != 0) {
            UimodLog("[uimod] blinkfix: unexpected bytes at a cursor draw site -> unit blink fix NOT installed\n");
            return;
        }
    }
    for (const Site& s : kSites) {
        BYTE* p = At(s.va) + kRadiusOff;
        DWORD old;
        if (!VirtualProtect(p, 1, PAGE_EXECUTE_READWRITE, &old)) {
            UimodLog("[uimod] blinkfix: VirtualProtect failed -> unit blink fix NOT installed\n");
            return;
        }
        *p = kRadius;
        VirtualProtect(p, 1, old, &old);
        FlushInstructionCache(GetCurrentProcess(), p, 1);
    }
    UimodLog("[uimod] blinkfix: the selected unit's blink redraws its neighbours too (wide sprites erase cleanly)\n");
}
