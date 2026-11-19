// thinkersites_core.h -- the DECISIONS of the "apply after Thinker" pass (thinkercompat.cpp), over any view of the
// image: the live process, or a test's buffer (work\tests\thinkersites_selftest.cpp drives the real generated table,
// thinker_sites.h, through every state an exe can be in). Pure: no windows.h, no writes, no globals.
//
// What it decides, per site of the table:
//   kExcluded / kRestore   our bytes over a span Thinker also writes. A site may be written only when (1) every byte
//                          outside Thinker's windows is the reference byte and every window holds the reference
//                          bytes or a call into thinker.dll, AND (2) every place our bytes transfer to holds the
//                          bytes our code has there -- an exe without our code caves gets none of these calls.
//                          The sites of one patches.yaml GROUP go together or not at all: the rest of the group is
//                          baked on disk and assumes all of them.
//   kMinImm32              an imm32 the engine needs to be at least ours. Never skipped with a group: read it, and
//                          write ours only when the live value is smaller, whatever was there. If the instruction
//                          around it is not the one we mean, the game cannot run safely (Fatal).
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstring>

#include "thinker_sites.h"

namespace thinkersites {

using namespace thinker_sites;

// How to read the image. `read` returns `len` readable bytes at `va`, or null when they are not mapped. Addresses
// are the exe's virtual addresses (the exe loads at its preferred base, so they are also process addresses).
struct View {
    const uint8_t* (*read)(void* ctx, uint32_t va, uint32_t len) = nullptr;
    void* ctx = nullptr;
    uint32_t thinkerLo = 0, thinkerHi = 0;      // thinker.dll's image; both 0 when it is absent or unreadable
};

enum class Action {
    AlreadyOurs,     // the site already holds our bytes
    Write,           // write `ours`
    SkipGroup,       // its group is not applied: this site or another one of the group did not qualify
    MinEnough,       // kMinImm32: the live value is already at least ours
    MinWrite,        // kMinImm32: write ours
    Fatal,           // kMinImm32: the instruction is not the one we mean -> the game cannot run safely
};

inline bool InThinker(const View& v, uint32_t a) { return v.thinkerHi != 0 && v.thinkerLo <= a && a < v.thinkerHi; }

inline uint32_t Rel32Target(const uint8_t* opcode, uint32_t va)      // E8 / E9 at `va`
{
    int32_t rel;
    memcpy(&rel, opcode + 1, 4);
    return va + 5 + static_cast<uint32_t>(rel);
}

inline const Window* WindowAt(const Site& s, uint32_t i)
{
    for (uint32_t k = 0; k < s.nwindows; ++k)
        if (s.windows[k].off <= i && i < s.windows[k].off + s.windows[k].len) return &s.windows[k];
    return nullptr;
}

inline bool AlreadyOurs(const Site& s, const View& v)
{
    const uint8_t* p = v.read(v.ctx, s.va, s.len);
    return p && memcmp(p, s.ours, s.len) == 0;
}

// The live bytes of a site must be exactly what the table predicts: outside Thinker's windows the reference bytes
// (the clean base for kExcluded, ours for kRestore); inside a write_call window either the reference bytes (Thinker
// not loaded, or this build of Thinker did not write there) or an E8 whose target lies in thinker.dll; inside the
// Scient window the clean byte or Scient's. Anything else is a build this table was not generated against.
inline bool SiteMatches(const Site& s, const View& v, char* why, size_t n)
{
    const uint8_t* p = v.read(v.ctx, s.va, s.len);
    if (!p) { snprintf(why, n, "the site is not mapped"); return false; }
    const uint8_t* ref = s.mode == kRestore ? s.ours : s.clean;
    for (uint32_t i = 0; i < s.len; ++i) {
        const Window* w = WindowAt(s, i);
        if (!w) {
            if (p[i] != ref[i]) { snprintf(why, n, "+%u reads %02X, expected %02X", i, p[i], ref[i]); return false; }
            continue;
        }
        if (i != w->off) continue;                         // a window is judged at its first byte
        if (w->kind == kCall) {
            if (memcmp(p + i, ref + i, w->len) == 0) continue;
            if (p[i] == 0xE8 && InThinker(v, Rel32Target(p + i, s.va + i))) continue;
            // Thinker's write_call over an FF15 site writes `90 E8 rel32` (patch.cpp write_call): a 6-byte window
            if (w->len == 6 && p[i] == 0x90 && p[i + 1] == 0xE8 && InThinker(v, Rel32Target(p + i + 1, s.va + i + 1))) continue;
            snprintf(why, n, "+%u reads %02X %02X %02X %02X %02X: neither the expected bytes nor a call into thinker.dll",
                     i, p[i], p[i + 1], p[i + 2], p[i + 3], p[i + 4]);
            return false;
        }
        if (p[i] == s.clean[i] || p[i] == w->scient_new) continue;
        snprintf(why, n, "+%u reads %02X, expected %02X (clean) or %02X (Scient)", i, p[i], s.clean[i], w->scient_new);
        return false;
    }
    return true;
}

// Our code is really at the other end of every call / jump our bytes make.
inline bool DestsPresent(const Site& s, const View& v, char* why, size_t n)
{
    for (uint32_t k = 0; k < s.ndests; ++k) {
        const Dest& d = s.dests[k];
        const uint8_t* p = v.read(v.ctx, d.va, static_cast<uint32_t>(sizeof d.bytes));
        if (!p) { snprintf(why, n, "its destination 0x%08X is not mapped (an exe without our code)", d.va); return false; }
        if (memcmp(p, d.bytes, sizeof d.bytes) != 0) {
            snprintf(why, n, "its destination 0x%08X does not hold our code (reads %02X %02X %02X %02X)", d.va, p[0], p[1], p[2], p[3]);
            return false;
        }
    }
    return true;
}

inline uint32_t Imm32(const uint8_t* p)
{
    uint32_t v;
    memcpy(&v, p, 4);
    return v;
}

// kMinImm32: `*live` receives the value found.
inline Action MinImm32(const Site& s, const View& v, uint32_t* live, char* why, size_t n)
{
    for (uint32_t k = 0; k < s.nguards; ++k) {
        const Guard& g = s.guards[k];
        const uint8_t* p = v.read(v.ctx, static_cast<uint32_t>(static_cast<int64_t>(s.va) + g.off), 1);
        if (!p || *p != g.byte) {
            snprintf(why, n, "the byte at %+d is %s%02X, expected %02X: not the instruction this patch is for", g.off,
                     p ? "" : "unmapped ", p ? *p : 0, g.byte);
            return Action::Fatal;
        }
    }
    const uint8_t* p = v.read(v.ctx, s.va, 4);
    if (!p) { snprintf(why, n, "the immediate is not mapped"); return Action::Fatal; }
    *live = Imm32(p);
    return *live >= Imm32(s.ours) ? Action::MinEnough : Action::MinWrite;      // unsigned: a larger foreign size is fine
}

// One Action per site of `sites`, and one short reason per site that is not written (empty otherwise).
constexpr size_t kWhyLen = 160;
constexpr uint32_t kMaxSites = 64;                          // the table holds a handful; callers size their arrays by this
static_assert(kNumSites <= kMaxSites, "thinker_sites.h grew past the plan's arrays: raise kMaxSites");
inline void Plan(const Site* sites, uint32_t n, const View& v, Action* out, char (*why)[kWhyLen])
{
    bool ok[kMaxSites] = {};
    if (n > kMaxSites) n = kMaxSites;                       // unreachable for the real table (static_assert above)
    for (uint32_t i = 0; i < n && i < 64; ++i) {
        why[i][0] = '\0';
        const Site& s = sites[i];
        if (s.mode == kMinImm32) {
            uint32_t live = 0;
            out[i] = MinImm32(s, v, &live, why[i], kWhyLen);
            continue;
        }
        if (AlreadyOurs(s, v)) { out[i] = Action::AlreadyOurs; ok[i] = true; continue; }
        ok[i] = SiteMatches(s, v, why[i], kWhyLen) && DestsPresent(s, v, why[i], kWhyLen);
        out[i] = ok[i] ? Action::Write : Action::SkipGroup;
    }
    // all or nothing per group
    for (uint32_t i = 0; i < n && i < 64; ++i) {
        const Site& s = sites[i];
        if (s.mode == kMinImm32 || ok[i]) continue;
        for (uint32_t j = 0; j < n && j < 64; ++j) {
            const Site& t = sites[j];
            if (j == i || t.mode == kMinImm32 || strcmp(t.group, s.group) != 0 || out[j] != Action::Write) continue;
            out[j] = Action::SkipGroup;
            snprintf(why[j], kWhyLen, "its group %s is not applied: %s did not qualify", s.group, s.id);
        }
    }
}

} // namespace thinkersites
