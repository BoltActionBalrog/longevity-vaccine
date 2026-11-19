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
//   kMinImm32  the Design Workshop's z-plane allocation size: an imm32 that must be AT LEAST ours (a baked sibling
//              site fills 2 MB of it). Read, and raised only when smaller -- whatever value was there.
//   Chain      both: our call-redirect thunk + the core it jumps to are copied into a trampoline whose one entry into
//              the engine function now enters Thinker's function instead (read from the E8 Thinker left at the site),
//              and the site's E8 is re-pointed at the trampoline (decision 4: base-screen set_font / eco-damage line).
// The kExcluded sites are written WITHOUT Thinker too: a player who starts terranx.exe directly in a Thinker folder
// runs the Thinker overlay with the rest of each group on disk, and e.g. the Design Workshop's 54 other sites assume
// the 2 MB depth buffer this pass sets.
//
// WHICH sites are written is decided by thinkersites_core.h (pure; tests\test_thinker_sites.py drives it through
// every state an exe can be in): a site only when it matches AND our code is at the other end of every call it
// makes, the sites of one patches.yaml group together or not at all. This file performs the plan and reads it back.
// On a Thinker that is not the pinned build (reduced mode) the chains and undos stay out; the engine-byte sites
// above still follow the same structural rule, which does not depend on the build.
#include "thinkercompat.h"
#include "thinker_sites.h"
#include "thinkersites_core.h"   // SiteMatches / DestsPresent / MinImm32 / Plan
#include "thinkerversion.h"   // the ONE detection: ThinkerPresent / ThinkerOnPin / ThinkerImageRange

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

using namespace thinker_sites;

// thinker.dll's image, from the startup check's detection (thinkerversion.cpp). Zero when Thinker is absent or its
// header is unreadable: then no address is "inside thinker.dll" and a site that Thinker rewrote does not match.
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

bool InThinker(uintptr_t a)
{
    return g_thHi != 0 && g_thLo <= a && a < g_thHi;
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

// The live image as thinkersites_core.h reads it: `len` bytes at `va`, or null when they are not committed, readable
// memory (a destination beyond an exe that carries no code cave must not fault).
const uint8_t* ReadLive(void*, uint32_t va, uint32_t len)
{
    const BYTE* p = At(va);
    const uintptr_t end = reinterpret_cast<uintptr_t>(p) + len;
    for (uintptr_t a = reinterpret_cast<uintptr_t>(p); a < end;) {      // every region the span touches
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<LPCVOID>(a), &mbi, sizeof mbi) != sizeof mbi || mbi.State != MEM_COMMIT ||
            mbi.Protect == 0 || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
            return nullptr;
        const uintptr_t next = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        if (next <= a) return nullptr;
        a = next;
    }
    return p;
}

// A span can be made writable (and is put back as it was). Asked for EVERY site of a group before the first byte of
// the group is written: "all or nothing" must hold when a write is refused, not only when a site does not match.
bool CanWrite(BYTE* p, size_t n)
{
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    VirtualProtect(p, n, old, &old);
    return true;
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
    const uint8_t* thunk = ReadLive(nullptr, c.thunk_va, c.thunk_len);
    const uint8_t* core = ReadLive(nullptr, c.core_va, c.core_len);
    if (!thunk || !core) {                                   // an exe without our code cave: nothing to chain
        Log("[uimod] thinker: %s: the cave thunk/core is not mapped (an exe without our code) -> not chained\n", c.id);
        return -1;
    }
    if (memcmp(thunk, c.thunk_bytes, c.thunk_len) != 0 || memcmp(core, c.core_bytes, c.core_len) != 0) {
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

// Both answers come from the startup check's one detection (thinkerversion.cpp). A thinker.dll that attaches later
// than that is not looked for: it would meet our bytes at its own guards and stop itself.
bool ThinkerLoaded()
{
    return ThinkerPresent();
}

bool ThinkerRange(uintptr_t* lo, uintptr_t* hi)
{
    return ThinkerImageRange(lo, hi);
}

void InstallThinkerCompat()
{
    const bool present = ThinkerPresent();
    // Chains enter Thinker's functions and undos replace its calls: both are measured on the pinned build only.
    // On any other build they are not installed (reduced mode: nothing of ours calls into or chains into thinker.dll).
    const bool onPin = ThinkerOnPin();
    if (!ThinkerImageRange(&g_thLo, &g_thHi)) g_thLo = g_thHi = 0;
    if (present) {
        Log("[uimod] thinker: PRACX + Thinker compatibility pass (%u sites, %u chains)%s\n", kNumSites, kNumChains,
            onPin ? "" : " -- not the supported build: chains and undos are NOT installed");
    }

    thinkersites::View view;
    view.read = &ReadLive;
    view.thinkerLo = static_cast<uint32_t>(g_thLo);
    view.thinkerHi = static_cast<uint32_t>(g_thHi);
    thinkersites::Action plan[thinkersites::kMaxSites];
    char why[thinkersites::kMaxSites][thinkersites::kWhyLen];
    thinkersites::Plan(kSites, kNumSites, view, plan, why);
    // A site the plan writes but Windows will not let us write takes its whole group out BEFORE anything is written.
    for (uint32_t i = 0; i < kNumSites; ++i) {
        if (plan[i] != thinkersites::Action::Write || CanWrite(At(kSites[i].va), kSites[i].len)) continue;
        for (uint32_t j = 0; j < kNumSites; ++j) {
            if (kSites[j].mode == kMinImm32 || strcmp(kSites[j].group, kSites[i].group) != 0) continue;
            if (plan[j] != thinkersites::Action::Write) continue;
            plan[j] = thinkersites::Action::SkipGroup;
            _snprintf_s(why[j], thinkersites::kWhyLen, _TRUNCATE, "its group %s is not applied: %s cannot be made writable",
                        kSites[i].group, kSites[i].id);
        }
    }

    int applied = 0, already = 0, failed = 0;
    bool cannotStart = false;
    for (uint32_t i = 0; i < kNumSites; ++i) {
        const Site& s = kSites[i];
        BYTE* p = At(s.va);
        switch (plan[i]) {
        case thinkersites::Action::AlreadyOurs:
            Log("[uimod] thinker: %s @ 0x%08X already carries our bytes\n", s.id, s.va);
            ++already;
            break;
        case thinkersites::Action::MinEnough:
            Log("[uimod] thinker: %s @ 0x%08X already holds 0x%08X, at least the 0x%08X we need -> left as it is\n", s.id, s.va,
                thinkersites::Imm32(p), thinkersites::Imm32(s.ours));
            ++already;
            break;
        case thinkersites::Action::Write:
        case thinkersites::Action::MinWrite: {
            // Judged over the whole window: Thinker's write_call rewrites only the rel32 of a call the clean base already has.
            bool hadThinker = false;
            for (uint32_t k = 0; k < s.nwindows; ++k)
                hadThinker |= memcmp(p + s.windows[k].off, s.clean + s.windows[k].off, s.windows[k].len) != 0;
            if (!WriteCode(p, s.ours, s.len)) {
                Log("[uimod] thinker: %s @ 0x%08X NOT applied: the write did not land\n", s.id, s.va);
                ++failed;
                cannotStart |= s.mode == kMinImm32;
                break;
            }
            Log("[uimod] thinker: %s @ 0x%08X applied (%u bytes%s)\n", s.id, s.va, s.len,
                hadThinker ? ", over Thinker's write" : s.mode == kExcluded ? ", clean on disk, no Thinker write there" : "");
            ++applied;
            break;
        }
        case thinkersites::Action::SkipGroup:
            Log("[uimod] thinker: %s @ 0x%08X NOT applied: %s\n", s.id, s.va, why[i]);
            ++failed;
            break;
        case thinkersites::Action::Fatal:
            Log("[uimod] thinker: %s @ 0x%08X cannot be applied: %s\n", s.id, s.va, why[i]);
            ++failed;
            cannotStart = true;
            break;
        }
    }
    int chained = 0, chainFailed = 0;
    if (onPin) {
        for (uint32_t i = 0; i < kNumChains; ++i) {
            const int r = InstallChain(kChains[i]);
            if (r > 0) ++chained;
            else if (r < 0) ++chainFailed;
        }
    }
    int undone = 0, undoFailed = 0;
    if (onPin) {
        for (const Undo& u : kUndo) {
            const int r = UndoThinkerCall(u);
            if (r > 0) ++undone; else if (r < 0) ++undoFailed;
        }
    }
    Log("[uimod] thinker: %d site(s) applied, %d already ours, %d failed; %d chain(s) installed, %d failed; %d Thinker call(s) undone, %d failed\n",
        applied, already, failed, chained, chainFailed, undone, undoFailed);

    // The one failure the game cannot run with: a baked sibling site fills 2 MB of the buffer this size allocates, so
    // a smaller size is a heap overrun whenever that code runs -- not something a player avoids by staying out of one
    // screen (user 2026-11-14). Say so and stop.
    if (cannotStart) ThinkerCannotStart();
}
