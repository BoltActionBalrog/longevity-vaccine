// thinkercompat.cpp -- the "apply after Thinker" pass for the PRACX + Thinker target (user decisions 2026-10-28,
// ACTION_ITEMS "THINKER" block; the table is GENERATED into thinker_sites.h by work\scripts\gen_thinker_sites.py).
//
// Thinker (thinker.dll, injected by thinker.exe) patches terranx.exe IN MEMORY before the game's first instruction
// and verifies every write of its own against the bytes it expects; a failed guard is exit_fail and the game never
// starts. uimod.dll initialises later (the CRT-initterm / PRACX startup chain), so anything of ours that Thinker's
// guards would reject is left clean on disk by the patcher (target pracx_thinker, `exclude_sites`) and written HERE,
// after Thinker has verified and patched. Last writer wins:
//   kExcluded  the four sites whose bytes would fail Thinker's guard: Thinker's call / Scient byte is now inside the
//              span; we overwrite the whole span with ours (decisions 1-3: dw_scale, menu strip, credits subwin).
//   kRestore   our E8 passed Thinker's guard and Thinker's call replaced its rel32; ours goes back (decision 2).
//   Chain      both: our call-redirect thunk + the core it jumps to are copied into a trampoline whose one entry into
//              the engine function now enters Thinker's function instead (read from the E8 Thinker left at the site),
//              and the site's E8 is re-pointed at the trampoline (decision 4: base-screen set_font / eco-damage line).
// The kExcluded sites are written WITHOUT Thinker too: a player who starts terranx.exe directly in a Thinker folder
// runs the Thinker overlay with the rest of each group on disk, and e.g. the Design Workshop's 54 other sites assume
// the 2 MB depth buffer this pass sets.
#include "thinkercompat.h"
#include "thinker_sites.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

using namespace thinker_sites;

HMODULE g_thinker = nullptr;
uintptr_t g_thLo = 0, g_thHi = 0;

BYTE* At(uint32_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

void Log(const char* fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(buf, sizeof buf, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(buf);
}

bool ModuleRange(HMODULE m, uintptr_t* lo, uintptr_t* hi)
{
    const BYTE* base = reinterpret_cast<const BYTE*>(m);
    auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (!m || dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    auto nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    *lo = reinterpret_cast<uintptr_t>(base);
    *hi = *lo + nt->OptionalHeader.SizeOfImage;
    return true;
}

bool InThinker(uintptr_t a)
{
    return g_thinker && g_thLo <= a && a < g_thHi;
}

uintptr_t CallTarget(const BYTE* e8)
{
    int32_t rel;
    memcpy(&rel, e8 + 1, 4);
    return reinterpret_cast<uintptr_t>(e8) + 5 + rel;
}

// Write and READ BACK: a write that did not land is reported, never assumed (the rest of a group is on disk and
// assumes these bytes).
bool WriteCode(BYTE* p, const BYTE* bytes, size_t n)
{
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return memcmp(p, bytes, n) == 0;
}

const Window* WindowAt(const Site& s, uint32_t i)
{
    for (uint32_t k = 0; k < s.nwindows; ++k)
        if (s.windows[k].off <= i && i < s.windows[k].off + s.windows[k].len) return &s.windows[k];
    return nullptr;
}

// The live bytes of a site must be exactly what the table predicts: outside Thinker's windows the reference bytes
// (the clean base for kExcluded, ours for kRestore); inside a write_call window either the reference bytes (Thinker
// not loaded, or this build of Thinker did not write there) or an E8 whose target lies in thinker.dll; inside the
// Scient window the clean byte or Scient's. Anything else is a Thinker build this table was not generated against.
bool SiteMatches(const Site& s, char* why, size_t n)
{
    const BYTE* p = At(s.va);
    const BYTE* ref = s.mode == kExcluded ? s.clean : s.ours;
    for (uint32_t i = 0; i < s.len; ++i) {
        const Window* w = WindowAt(s, i);
        if (!w) {
            if (p[i] != ref[i]) {
                _snprintf_s(why, n, _TRUNCATE, "+%u reads %02X, expected %02X", i, p[i], ref[i]);
                return false;
            }
            continue;
        }
        if (i != w->off) continue;                         // a window is judged at its first byte
        if (w->kind == kCall) {
            if (memcmp(p + i, ref + i, w->len) == 0) continue;
            if (p[i] == 0xE8 && InThinker(CallTarget(p + i))) continue;
            // Thinker's write_call over an FF15 site writes `90 E8 rel32` (patch.cpp write_call): a 6-byte window
            if (w->len == 6 && p[i] == 0x90 && p[i + 1] == 0xE8 && InThinker(CallTarget(p + i + 1))) continue;
            _snprintf_s(why, n, _TRUNCATE, "+%u reads %02X %02X %02X %02X %02X: neither the expected bytes nor a call into thinker.dll",
                        i, p[i], p[i + 1], p[i + 2], p[i + 3], p[i + 4]);
            return false;
        }
        if (p[i] == s.clean[i] || p[i] == w->scient_new) continue;
        _snprintf_s(why, n, _TRUNCATE, "+%u reads %02X, expected %02X (clean) or %02X (Scient)", i, p[i], s.clean[i], w->scient_new);
        return false;
    }
    return true;
}

// Returns 1 applied, 0 already ours, -1 failed.
int ApplySite(const Site& s)
{
    BYTE* p = At(s.va);
    if (memcmp(p, s.ours, s.len) == 0) {
        Log("[uimod] thinker: %s @ 0x%08X already carries our bytes\n", s.id, s.va);
        return 0;
    }
    char why[200];
    if (!SiteMatches(s, why, sizeof why)) {
        Log("[uimod] thinker: %s @ 0x%08X NOT applied: %s\n", s.id, s.va, why);
        return -1;
    }
    // Judged over the whole window: Thinker's write_call rewrites only the rel32 of a call the clean base already has.
    bool hadThinker = false;
    for (uint32_t k = 0; k < s.nwindows; ++k)
        hadThinker |= memcmp(p + s.windows[k].off, s.clean + s.windows[k].off, s.windows[k].len) != 0;
    if (!WriteCode(p, s.ours, s.len)) {
        Log("[uimod] thinker: %s @ 0x%08X NOT applied: the write did not land\n", s.id, s.va);
        return -1;
    }
    Log("[uimod] thinker: %s @ 0x%08X applied (%u bytes%s)\n", s.id, s.va, s.len,
        hadThinker ? ", over Thinker's write" : s.mode == kExcluded ? ", clean on disk, no Thinker write there" : "");
    return 1;
}

// Returns 1 chained, 0 nothing to do (Thinker left the site alone), -1 failed.
int InstallChain(const Chain& c)
{
    BYTE* site = At(c.site_va);
    if (site[0] != 0xE8) {
        Log("[uimod] thinker: %s @ 0x%08X is not a call (%02X) -> not chained\n", c.id, c.site_va, site[0]);
        return -1;
    }
    const uintptr_t tgt = CallTarget(site);
    if (tgt == c.thunk_va) {
        Log("[uimod] thinker: %s @ 0x%08X untouched by Thinker -> our thunk stands\n", c.id, c.site_va);
        return 0;
    }
    if (!InThinker(tgt)) {
        Log("[uimod] thinker: %s @ 0x%08X calls 0x%08X, neither our thunk nor thinker.dll -> not chained\n", c.id, c.site_va,
            static_cast<unsigned>(tgt));
        return -1;
    }
    if (memcmp(At(c.thunk_va), c.thunk_bytes, c.thunk_len) != 0 || memcmp(At(c.core_va), c.core_bytes, c.core_len) != 0) {
        Log("[uimod] thinker: %s: the cave thunk/core bytes differ from the generated table (regenerate thinker_sites.h) -> not chained\n", c.id);
        return -1;
    }
    bool tailSeen = false;
    for (uint32_t k = 0; k < c.nfixups; ++k) tailSeen |= c.fixups[k].off == c.tail_off;
    if (!tailSeen) {
        Log("[uimod] thinker: %s: table has no tail fixup -> not chained\n", c.id);
        return -1;
    }
    const size_t sz = c.prelude_len + c.core_len;
    BYTE* tr = static_cast<BYTE*>(VirtualAlloc(nullptr, sz, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!tr) {
        Log("[uimod] thinker: %s: VirtualAlloc failed -> not chained\n", c.id);
        return -1;
    }
    memcpy(tr, c.thunk_bytes, c.prelude_len);
    memcpy(tr + c.prelude_len, c.core_bytes, c.core_len);
    for (uint32_t k = 0; k < c.nfixups; ++k) {
        const Fixup& f = c.fixups[k];
        const uintptr_t target = f.off == c.tail_off ? tgt : f.target;
        const int32_t rel = static_cast<int32_t>(target - (reinterpret_cast<uintptr_t>(tr) + f.off + 4));
        memcpy(tr + f.off, &rel, 4);
    }
    FlushInstructionCache(GetCurrentProcess(), tr, sz);
    BYTE patch[5] = { 0xE8, 0, 0, 0, 0 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(tr) - (reinterpret_cast<uintptr_t>(site) + 5));
    memcpy(patch + 1, &rel, 4);
    if (!WriteCode(site, patch, 5)) {
        Log("[uimod] thinker: %s @ 0x%08X: re-pointing the site failed -> Thinker's call stands alone\n", c.id, c.site_va);
        return -1;
    }
    Log("[uimod] thinker: %s @ 0x%08X -> our thunk, then Thinker's 0x%08X instead of 0x%08X (trampoline %p, %u bytes)\n",
        c.id, c.site_va, static_cast<unsigned>(tgt), c.native_va, tr, static_cast<unsigned>(sz));
    return 1;
}

// ---- Thinker calls we UNDO (user decisions; engine bytes only) ----------------------------------------------
// A Thinker write_call that replaces an engine function we scale: the site goes back to the engine's own callee
// (the clean exe's E8 target), so our scaling applies and Thinker's replacement never runs. Only when the site
// holds an E8 into thinker.dll; anything else (engine, ours, unknown) is left alone and reported.
struct Undo { uint32_t site_va; uint32_t engine_va; const char* why; };
const Undo kUndo[] = {
    // SUPPORT tab (user 2026-10-29): Thinker's render_high_detail replaces draw_farm's two calls to the engine's
    // support-view draw 0x408EB0 with its own zoomable BaseWin_draw_support, drawn at Thinker's zoom and
    // bypassing our scaled support map (basewin_support_mapzoom) -> a tiny unit in an empty panel at 4K.
    // Thinker's support zoom (wheel / Ctrl+Up/Down) then only redraws.
    { 0x40F1C3, 0x408EB0, "SUPPORT tab: the engine's support view (ours scales it), not Thinker's zoomable one" },
    { 0x40F1EB, 0x408EB0, "SUPPORT tab: the engine's support view (ours scales it), not Thinker's zoomable one" },
};

int UndoThinkerCall(const Undo& u)
{
    BYTE* p = At(u.site_va);
    if (p[0] != 0xE8) { Log("[uimod] thinker: undo @ 0x%08X: not a call (%02X) -> left alone\n", u.site_va, p[0]); return 0; }
    const uintptr_t tgt = CallTarget(p);
    if (!InThinker(tgt)) return 0;                                   // the engine's (or ours) already
    BYTE call[5] = { 0xE8 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(At(u.engine_va)) - reinterpret_cast<uintptr_t>(p + 5));
    memcpy(call + 1, &rel, 4);
    if (!WriteCode(p, call, 5)) { Log("[uimod] thinker: undo @ 0x%08X: write failed -> Thinker's call stands\n", u.site_va); return -1; }
    Log("[uimod] thinker: undo @ 0x%08X: Thinker's 0x%08X -> the engine's 0x%08X (%s)\n", u.site_va,
        static_cast<unsigned>(tgt), u.engine_va, u.why);
    return 1;
}

} // namespace

bool ThinkerLoaded()
{
    return g_thinker != nullptr;
}

bool ThinkerRange(uintptr_t* lo, uintptr_t* hi)
{
    if (!g_thinker) {
        // Decided at InstallThinkerCompat, but a first-use check (pssphere's ThinkerCheck) may run after a thinker.dll
        // that attached later than Init: look once more before answering "absent" (audit 2026-10-30).
        HMODULE m = GetModuleHandleA("thinker.dll");
        if (m && ModuleRange(m, &g_thLo, &g_thHi)) g_thinker = m;
        if (!g_thinker) return false;
    }
    *lo = g_thLo;
    *hi = g_thHi;
    return true;
}

void InstallThinkerCompat()
{
    g_thinker = GetModuleHandleA("thinker.dll");
    if (g_thinker && !ModuleRange(g_thinker, &g_thLo, &g_thHi)) {
        UimodLog("[uimod] thinker: thinker.dll is loaded but its PE headers are unreadable -> treated as absent\n");
        g_thinker = nullptr;
    }
    if (g_thinker) {
        Log("[uimod] thinker: thinker.dll loaded at %p (%u KB) -> PRACX + Thinker compatibility pass (%u sites, %u chains)\n",
            g_thinker, static_cast<unsigned>((g_thHi - g_thLo) >> 10), kNumSites, kNumChains);
    } else {
        UimodLog("[uimod] thinker: not loaded\n");
    }

    int applied = 0, already = 0, failed = 0;
    bool dwFailed = false;
    for (uint32_t i = 0; i < kNumSites; ++i) {
        const int r = ApplySite(kSites[i]);
        if (r > 0) ++applied;
        else if (r == 0) ++already;
        else {
            ++failed;
            if (strncmp(kSites[i].id, "Caviar.", 7) == 0) dwFailed = true;
        }
    }
    int chained = 0, chainFailed = 0;
    if (g_thinker) {
        for (uint32_t i = 0; i < kNumChains; ++i) {
            const int r = InstallChain(kChains[i]);
            if (r > 0) ++chained;
            else if (r < 0) ++chainFailed;
        }
    }
    int undone = 0, undoFailed = 0;
    if (g_thinker) {
        for (const Undo& u : kUndo) {
            const int r = UndoThinkerCall(u);
            if (r > 0) ++undone; else if (r < 0) ++undoFailed;
        }
    }
    Log("[uimod] thinker: %d site(s) applied, %d already ours, %d failed; %d chain(s) installed, %d failed; %d Thinker call(s) undone, %d failed\n",
        applied, already, failed, chained, chainFailed, undone, undoFailed);

    if (dwFailed) {
        // The one failure that is not cosmetic: the Design Workshop's other 54 sites assume the 2 MB depth buffer
        // this byte allocates. Say so once, before any window exists.
        MessageBoxA(nullptr,
                    "Longevity Vaccine could not apply its Design Workshop memory patch (details in uimod.log).\n\n"
                    "Avoid the Design Workshop until the mod is updated.",
                    "Longevity Vaccine", MB_OK | MB_ICONWARNING);
    }
}
