// uimod developer diagnostic: dump popup geometry to uimod.log when Pause is pressed.
//
// OFF unless the file `uimod_debug.flag` exists next to the exe (checked once at Init). Read-only: no code is
// patched, no engine function is called; every address is probed with VirtualQuery before it is read, so it is
// safe on the PRACX-patched and the unpatched exe (the cave cells simply read as "n/a" there).
//
// Why: the patcher's thunks are Frida-hostile (baked detours), so an attach-based probe of a live popup is a crash
// risk. The screenshot hotkey is Pause, so a shot and its numbers land together.
//
// Also (same flag): Scroll Lock toggles the engine's developer bit GameState 0x1000 (one dword write, no engine
// call). With it set, Ctrl/Shift + opening a COMMLINK to ANY faction opens the multiplayer negotiation window
// (DiploWin) in single player: commlink_attempter 0x5589E0 tests Ctrl|Shift && GameState&0x1000 before every
// MP / human check and calls diplo(me, target) @0x558AFC. While DiploWin is live, Pause dumps its geometry.

#include "debugdump.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kImageBase = 0x400000;
constexpr uintptr_t kTutWin    = 0x8C6E68;
constexpr uintptr_t kModalTop  = 0x9B7AE0;
constexpr uintptr_t kBasePop   = 0x9B8D7C;
constexpr uintptr_t kScaleNum  = 0x668740;   // g_popup_scale_num (patcher global; plain .data on the unpatched exe)
constexpr uintptr_t kTitleLeft = 0xA0CF00;   // pcave2 g_title_left / g_title_right (patched exe only)
constexpr uintptr_t kGameState = 0x9A64C0;   // GameState; bit 0x1000 = developer (debug) mode
constexpr uintptr_t kDiploWin  = 0x73ACD8;   // DiploWin, the multiplayer negotiation window
constexpr uintptr_t kStrip     = 0x7AF59C;   // g_console_strip_height

bool g_enabled = false;
bool g_down = false;
bool g_scrollDown = false;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}

bool Readable(const void* p, size_t n)
{
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(p, &mbi, sizeof mbi)) return false;
    if (mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    return static_cast<const BYTE*>(p) + n <= static_cast<const BYTE*>(mbi.BaseAddress) + mbi.RegionSize;
}

bool Rd32(const BYTE* p, int32_t* out)
{
    if (!Readable(p, 4)) return false;
    memcpy(out, p, 4);
    return true;
}

void DumpPopup(const char* tag, const BYTE* w)
{
    char line[512];
    if (!w || !Readable(w, 0x3200)) {
        _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] dump %s: n/a (%p)\n", tag, w);
        UimodLog(line);
        return;
    }
    auto v = [&](size_t off) { int32_t x = 0; Rd32(w + off, &x); return x; };
    _snprintf_s(line, sizeof line, _TRUNCATE,
                "[uimod] dump %s @%p vtbl=%08X shown(+9C)=%02X screen(+13C)=[%d,%d,%d,%d] local(+474)=[%d,%d,%d,%d] "
                "canvasWH(+4C4)=%dx%d bufWH(+444+80)=%dx%d\n",
                tag, w, static_cast<uint32_t>(v(0)), static_cast<unsigned>(w[0x9C]),
                v(0x13C), v(0x140), v(0x144), v(0x148), v(0x474), v(0x478), v(0x47C), v(0x480),
                v(0x4C4), v(0x4C8), v(0x444 + 0x80), v(0x444 + 0x84));
    UimodLog(line);
    _snprintf_s(line, sizeof line, _TRUNCATE,
                "[uimod] dump %s   type(+30AC)=%d boxWH(+30BC)=%dx%d margins L/R/T/B(+21B0..)=%d/%d/%d/%d "
                "+30E8=%d +30F0=%d +30F4=%d +30E0=%d +A48(title)=%08X +30D4=%d\n",
                tag, v(0x30AC), v(0x30BC), v(0x30C0), v(0x21B0), v(0x21B4), v(0x21B8), v(0x21BC),
                v(0x30E8), v(0x30F0), v(0x30F4), v(0x30E0), static_cast<uint32_t>(v(0xA48)), v(0x30D4));
    UimodLog(line);
}

void DumpFont(const char* tag, const BYTE* fontPtrSlot)
{
    char line[256];
    int32_t f = 0;
    if (!Rd32(fontPtrSlot, &f) || !f || !Readable(reinterpret_cast<const BYTE*>(static_cast<uintptr_t>(f)), 0x28)) {
        _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] dump DiploWin   font %s: n/a (%08X)\n", tag, static_cast<uint32_t>(f));
        UimodLog(line);
        return;
    }
    int32_t d[10];
    memcpy(d, reinterpret_cast<const BYTE*>(static_cast<uintptr_t>(f)), sizeof d);
    _snprintf_s(line, sizeof line, _TRUNCATE,
                "[uimod] dump DiploWin   font %s @%08X: %08X %08X %08X %08X %08X %08X %08X %08X %08X %08X\n",
                tag, static_cast<uint32_t>(f), d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7], d[8], d[9]);
    UimodLog(line);
}

// DiploWin (multiplayer negotiation window): window + canvas, then every stored layout rect (+0xEDC..+0x109C,
// 16-byte RECTs), caption size +0x16C, and the fonts of a button label / the chat TextScroll / the EditLine.
void DumpDiploWin()
{
    const BYTE* w = At(kDiploWin);
    if (!Readable(w, 0xE600) || !(w[0x9C] & 1)) return;
    DumpPopup("DiploWin", w);
    auto v = [&](size_t off) { int32_t x = 0; Rd32(w + off, &x); return x; };
    int32_t strip = 0;
    Rd32(At(kStrip), &strip);
    char line[256];
    _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] dump DiploWin   strip=%d caption(+16C)=%d\n", strip, v(0x16C));
    UimodLog(line);
    for (size_t off = 0xEDC; off <= 0x109C; off += 0x10) {
        _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] dump DiploWin   +%04X = [%d,%d,%d,%d]\n",
                    static_cast<unsigned>(off), v(off), v(off + 4), v(off + 8), v(off + 12));
        UimodLog(line);
    }
    DumpFont("button2(+2744+970)", w + 0x10AC + 2 * 0xB4C + 0x970);
    DumpFont("chat(+A388+970)", w + 0xA388 + 0x970);
    DumpFont("edit(+DA7C+970)", w + 0xDA7C + 0x970);
}

void Dump()
{
    char line[256];
    int32_t g = 0, tl = 0, tr = 0;
    const bool haveG = Rd32(At(kScaleNum), &g);
    const bool haveT = Rd32(At(kTitleLeft), &tl) && Rd32(At(kTitleLeft + 4), &tr);
    _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] dump ---- g=%d%s g_title_left/right=%d/%d%s screen=%dx%d\n",
                g, haveG ? "" : "(n/a)", tl, tr, haveT ? "" : "(n/a)", GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN));
    UimodLog(line);
    DumpPopup("TutWin", At(kTutWin));
    int32_t p = 0;
    if (Rd32(At(kBasePop), &p) && p) DumpPopup("basepop", reinterpret_cast<const BYTE*>(static_cast<uintptr_t>(p)));
    if (Rd32(At(kModalTop), &p) && p) DumpPopup("modaltop", reinterpret_cast<const BYTE*>(static_cast<uintptr_t>(p)));
    DumpDiploWin();
}

// Scroll Lock: toggle the engine's developer bit (see the header comment).
void ToggleDevMode()
{
    BYTE* p = At(kGameState);
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(p, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT ||
        !(mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_WRITECOPY))) {
        UimodLog("[uimod] debugdump: GameState not writable -- developer bit unchanged\n");
        return;
    }
    uint32_t gs;
    memcpy(&gs, p, 4);
    gs ^= 0x1000;
    memcpy(p, &gs, 4);
    char line[192];
    _snprintf_s(line, sizeof line, _TRUNCATE,
                "[uimod] debugdump: developer bit %s (GameState=%08X) -- Ctrl+COMMLINK a faction opens the negotiation window\n",
                (gs & 0x1000) ? "ON" : "OFF", gs);
    UimodLog(line);
}

} // namespace

void InstallDebugDump()
{
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    if (char* slash = strrchr(path, '\\')) slash[1] = '\0';
    lstrcatA(path, "uimod_debug.flag");
    g_enabled = GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
    if (g_enabled) UimodLog("[uimod] debugdump: ON (uimod_debug.flag present) -- Pause dumps popup geometry, Scroll Lock toggles developer mode\n");
}

void DebugDumpPoll()
{
    if (!g_enabled) return;
    const bool down = (GetAsyncKeyState(VK_PAUSE) & 0x8000) != 0;
    if (down && !g_down) Dump();
    g_down = down;
    const bool scroll = (GetAsyncKeyState(VK_SCROLL) & 0x8000) != 0;
    if (scroll && !g_scrollDown) ToggleDevMode();
    g_scrollDown = scroll;
}
