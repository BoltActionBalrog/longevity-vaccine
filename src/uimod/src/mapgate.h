// The Modern Control Set's map-pointer gate (modernctl.cpp): is a mouse event the engine handed to the MAP window
// really over the map? Header-only, no Windows types: work\tests\winline_selftest.cpp drives it.
//
// Win_get_mouse_window 0x5F6F10 walks the top-level window list g_top_windows 0x9B6E48 (count 0x9B7B34) and takes the
// first window whose hit-test (get_mouse_window_recurse 0x5F6AB0) claims the point; a window with flag 0x10000000
// declines a see-through pixel and the walk goes on, so the event can fall through to the map. Which coordinates
// arrive with it depends on the declining window (a top-level one restores the caller's, a parent-relative child does
// not), so the gate never reads them as evidence. It reads the RAW screen point instead:
//   * inside a shown top-level window the walk tried BEFORE the map (the tutorial box TutWin, a heap tutorial popup
//     such as #COMMERCE on the talk screen, the NetMsg ticker): the player is pointing at that window -- not the map's;
//   * inside the HUD strip window (its see-through top band between the MENU / COMMLINK wings: the strip declined it,
//     the player sees the map there) or on no window at all: the map's, its coordinates rebuilt from the raw point
//     whenever they are not already map-local.
#pragma once

namespace mapgate {

struct Pt { int x, y; };
struct Rect { int l, t, r, b; };               // half-open, screen (backbuffer) pixels

inline bool In(Pt p, const Rect& r) { return p.x >= r.l && p.x < r.r && p.y >= r.t && p.y < r.b; }

enum Verdict { kNotMap = 0, kMapAsIs = 1, kMapRebuilt = 2 };

// local: the event's x/y as handed to the map. raw: the event's screen point (0x9B6628 / 0x9B662C). mapOrg: the map
// window's origin. blockers: the screen rects of the shown top-level windows over the map (the strip and the map's own
// overlay excluded). *hit: index of the blocker containing raw, -1 none.
inline Verdict Gate(Pt local, Pt raw, Pt mapOrg, const Rect* blockers, int nBlockers, int* hit = nullptr)
{
    if (hit) *hit = -1;
    for (int i = 0; i < nBlockers; ++i)
        if (In(raw, blockers[i])) {
            if (hit) *hit = i;
            return kNotMap;
        }
    if (local.x == raw.x - mapOrg.x && local.y == raw.y - mapOrg.y) return kMapAsIs;
    return kMapRebuilt;
}

// ---- the blockers: the engine's top-level walk ----------------------------------------------------------------
// What the walk needs of a window (modernctl.cpp reads the engine's Win fields; the selftest feeds synthetic ones).
struct WinAccess {
    const void* (*delegate)(const void* w);           // +0xA8: the window the walk returns for w
    int (*childCount)(const void* w);                 // +0x3FC
    const void* (*child)(const void* w, int i);       // +0x1A4[i]
    bool (*screenRect)(const void* w, Rect* r);       // shown, top-level (not parent-relative): its screen rect
};
constexpr int kMaxChildren = (0x3FC - 0x1A4) / 4;     // the child array's capacity
constexpr int kHoldDepth = 3;

// Bit i set: w is targets[i], delegates to it, or holds it among its children (depth-limited, as the hit-test recurses).
inline unsigned HoldsMask(const WinAccess& a, const void* w, const void* const* targets, int nt, int depth)
{
    if (!w) return 0;
    unsigned m = 0;
    const void* d = a.delegate(w);
    for (int i = 0; i < nt; ++i)
        if (targets[i] && (w == targets[i] || d == targets[i])) m |= 1u << i;
    if (depth <= 0 || m == (1u << nt) - 1) return m;
    const int n = a.childCount(w);
    if (n <= 0 || n > kMaxChildren) return m;
    for (int c = 0; c < n; ++c) m |= HoldsMask(a, a.child(w, c), targets, nt, depth - 1);
    return m;
}

// The shown top-level windows the walk (list[0..count), first claimant wins) tries BEFORE the window holding the map,
// minus any holding the strip or the map's overlay; then the tutorial box (tut) always. *mapIdx = the map's list index,
// -1 = not found: then only the tutorial box -- a walk we do not understand must never block the whole map.
// Returns the number written to out / who (at most maxOut).
inline int Blockers(const WinAccess& a, const void* const* list, int count, const void* map, const void* strip,
                    const void* overlay, const void* tut, Rect* out, const void** who, int maxOut, int* mapIdx)
{
    *mapIdx = -1;
    int nb = 0;
    const void* targets[3] = { map, strip, overlay };
    Rect r;
    for (int i = 0; i < count; ++i) {
        const void* w = list[i];
        if (!w) continue;
        const unsigned m = HoldsMask(a, w, targets, 3, kHoldDepth);
        if (m & 1u) { *mapIdx = i; break; }
        if (m) continue;                                  // the strip (its band IS the map) or the map's overlay
        if (nb < maxOut - 1 && a.screenRect(w, &r)) { out[nb] = r; who[nb] = w; ++nb; }
    }
    if (*mapIdx < 0) nb = 0;
    if (tut && nb < maxOut && a.screenRect(tut, &r)) { out[nb] = r; who[nb] = tut; ++nb; }
    return nb;
}

} // namespace mapgate
