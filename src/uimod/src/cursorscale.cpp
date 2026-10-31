// cursorscale.cpp -- the engine's map cursors at vanilla x g/16 (patched exe only).
//
// load_cursors 0x454FC0 cuts 12 sprites from CURSOR.PCX (32x32 cells at x = 1 + 33i, y = 1) into 0x93AA70 (stride
// 0x2C) with Sprite_init 0x5E39A0 (trimmed: content +0x10/+0x14 at +0x20/+0x24 in the +0x18/+0x1C canvas, pixels
// +0x04 pitch +0x0C, malloc'd: +0x28 = 0), and their hotspots (palette-5 marker pixels) into 0x93AA10[i] (x) /
// 0x93AA40[i] (y).  Console_cursor_on 0x510400 (and its siblings) pass sprite i + those hotspots to Win_set_cursor
// 0x5EC740 (Win +0x188/+0x18C/+0x190); Win_update_cursor 0x5F1820 sizes the save-under 0x9B6F08 from the sprite's
// +0x18/+0x1C whenever the sprite differs from the cached one [0x9B7A2C], and PaintMain 0x5EFF0E blits it 1:1.  So
// every consumer reads the sprite struct and the two arrays: scaling those in place scales the cursor everywhere
// (user 2026-10-14: the patrol cursor was 29x27 at 4K and at 1600x1200).
//
// Law (scaling_laws.cursor_*, ported in cursor_law.h): the 32-cell enlarged by centre-sampled NN to scale_px(32, g);
// content rect and hotspot follow the same map.  g <= 16 (and the unpatched exe, where 0x668740 is zeroed .data):
// nothing changes.
//
// Ownership: the engine's native pixel buffer is KEPT (it is our pristine copy, never freed by us); +0x04 points at a
// DLL-owned enlargement and +0x28 is set to 1 -- the engine's own "pixels not mine" flag (Sprite_init's pool path),
// so neither the atexit vector destructor 0x52DAF0 -> 0x5E3820 nor a Sprite_init re-cut ever frees our buffer (both
// skip the free and the 0x9B6618 byte counter when +0x28 != 0).  A re-cut (load_cursors again: Console_init 0x51D9A9
// and load_fixed_sprites 0x455F05 call it whenever [0x9BC494] is 0) is seen as a fresh native sprite (Sprite_init
// writes +0x28 = 0 at 0x5E3A22): it is re-captured at once -- the cached g cleared, so the hook never hands a scaled
// hotspot to native pixels, and map windows holding the old scaled hotspot get the native one back -- and re-enlarged
// when it is off screen.  The re-cut leaks the previous native buffer (<= 12 KB per cut; engine-heap memory we never
// free) -- the engine's own malloc, not ours to release.
//
// When: lazily, at Win_set_cursor's entry -- g is 0 until thunk_ensure_scale runs, and load_cursors may run first.
// Never while the software cursor on screen [0x9B7A2C] is one of these sprites (Win_update_cursor's cached size and
// save-under would go stale): deferred to the next call.  A caller that passes the NATIVE hotspot of a scaled sprite
// (read from the arrays before the enlargement) gets the scaled one; map windows already holding a native hotspot
// for a sprite are corrected once.
#include "cursorscale.h"

#include <windows.h>
#include <cstdint>
#include <cstring>
#include <vector>

#include "cursor_law.h"

void UimodLog(const char* msg);
bool UimodPcave2Range(uintptr_t* lo, uintptr_t* hi);

namespace {

constexpr uintptr_t kVA_Sprites = 0x93AA70, kSpriteStride = 0x2C;
constexpr int kCount = 12;
constexpr uintptr_t kVA_HotX = 0x93AA10, kVA_HotY = 0x93AA40;
constexpr uintptr_t kVA_G = 0x668740;                 // g_popup_scale_num (patcher cell; zeroed .data unpatched)
constexpr uintptr_t kVA_CurSprite = 0x9B7A2C;         // Win_update_cursor: the sprite drawn now (0 = none)
constexpr uintptr_t kVA_MapWins = 0x7D3C3C, kMapWinCount = 8;   // Console_cursor_on's window table
constexpr uintptr_t kVA_SetCursor = 0x5EC740;
const BYTE kSetCursorEntry[8] = { 0x8B, 0x44, 0x24, 0x04, 0x85, 0xC0, 0x74, 0x1A };   // mov eax,[esp+4]; test; jz
constexpr size_t kSteal = 6;
// Console_cursor_on's sprite / hotspot reads: the layout this module assumes
const BYTE kCursorOnReads[] = { 0x8D, 0x3C, 0x95, 0x70, 0xAA, 0x93, 0x00,              // lea edi, [edx*4+0x93AA70]
                                0x3B, 0xCF, 0x74, 0x26,                                // cmp ecx, edi; je
                                0x8B, 0x04, 0x9D, 0x40, 0xAA, 0x93, 0x00,              // mov eax, [ebx*4+0x93AA40]
                                0x8B, 0x0C, 0x9D, 0x10, 0xAA, 0x93, 0x00 };            // mov ecx, [ebx*4+0x93AA10]
constexpr uintptr_t kVA_CursorOnReads = 0x510435;
// Sprite fields
constexpr size_t kBits = 0x04, kPitch = 0x0C, kW = 0x10, kH = 0x14, kCW = 0x18, kCH = 0x1C, kL = 0x20, kT = 0x24,
                 kNotMine = 0x28;

struct State {
    bool captured = false;
    BYTE* nativeBits = nullptr;                       // engine-owned, kept as the pristine copy
    int pitch = 0, w = 0, h = 0, cw = 0, ch = 0, left = 0, top = 0, hx = 0, hy = 0;
    int g = 0;                                        // the g the current enlargement is for (0 = none)
    std::vector<uint8_t> scaled;                      // DLL-owned pixels [+0x04] points at
    int shx = 0, shy = 0;                             // scaled hotspot
};
State g_st[kCount];
BYTE g_tramp[16];

template <class T> T& Ref(uintptr_t va) { return *reinterpret_cast<T*>(va); }
BYTE* Sprite(int i) { return reinterpret_cast<BYTE*>(kVA_Sprites + kSpriteStride * static_cast<uintptr_t>(i)); }
template <class T> T& Fld(BYTE* sp, size_t off) { return *reinterpret_cast<T*>(sp + off); }

bool IsOurSprite(uintptr_t p)
{
    return p >= kVA_Sprites && p < kVA_Sprites + kSpriteStride * kCount && (p - kVA_Sprites) % kSpriteStride == 0;
}

// A fresh engine sprite in slot i (load_cursors' cut): capture it as the native copy.  False = not a cut we know.
bool Capture(int i, BYTE* sp)
{
    State& s = g_st[i];
    const int w = Fld<int>(sp, kW), h = Fld<int>(sp, kH), cw = Fld<int>(sp, kCW), ch = Fld<int>(sp, kCH);
    const int l = Fld<int>(sp, kL), t = Fld<int>(sp, kT), pitch = Fld<int>(sp, kPitch);
    if (cw != cursor_law::kCell || ch != cursor_law::kCell || w <= 0 || h <= 0 || l < 0 || t < 0 ||
        l + w > cw || t + h > ch || pitch < w)
        return false;
    s.captured = true;
    s.nativeBits = Fld<BYTE*>(sp, kBits);
    s.pitch = pitch; s.w = w; s.h = h; s.cw = cw; s.ch = ch; s.left = l; s.top = t;
    s.hx = Ref<int>(kVA_HotX + 4u * i); s.hy = Ref<int>(kVA_HotY + 4u * i);   // load_cursors just wrote them
    s.g = 0;
    return true;
}

void Apply(int i, BYTE* sp, int g)
{
    State& s = g_st[i];
    std::vector<uint8_t> px;
    const cursor_law::Rect d = cursor_law::Enlarge(s.nativeBits, s.pitch, { s.left, s.top, s.w, s.h }, g, &px);
    if (d.w <= 0 || d.h <= 0) return;
    const int canvas = cursor_law::CanvasPx(g);
    s.scaled.swap(px);                                // the old enlargement (if any) is no longer referenced after
    Fld<BYTE*>(sp, kBits) = s.scaled.data();          // the field writes below: we only get here while no window
    Fld<int>(sp, kPitch) = d.w;                       // draws this sprite (deferral in EnsureScaled)
    Fld<int>(sp, kW) = d.w;
    Fld<int>(sp, kH) = d.h;
    Fld<int>(sp, kCW) = canvas;
    Fld<int>(sp, kCH) = canvas;
    Fld<int>(sp, kL) = d.left;
    Fld<int>(sp, kT) = d.top;
    Fld<int>(sp, kNotMine) = 1;
    s.shx = cursor_law::Hotspot(s.hx, g);
    s.shy = cursor_law::Hotspot(s.hy, g);
    Ref<int>(kVA_HotX + 4u * i) = s.shx;
    Ref<int>(kVA_HotY + 4u * i) = s.shy;
    s.g = g;
}

// A re-cut sprite i is native again: the map windows still holding it with the old SCALED hotspot get the native one.
void RestoreHeldHotspots(int i, int oldShx, int oldShy)
{
    const State& s = g_st[i];
    const uintptr_t sp = reinterpret_cast<uintptr_t>(Sprite(i));
    for (uintptr_t k = 0; k < kMapWinCount; ++k) {
        BYTE* con = Ref<BYTE*>(kVA_MapWins + 4 * k);
        if (!con) continue;
        BYTE* vt = Fld<BYTE*>(con, 0);
        if (!vt) continue;
        BYTE* win = con + Fld<int>(vt, 4);
        if (Fld<uintptr_t>(win, 0x188) != sp) continue;
        if (Fld<int>(win, 0x18C) == oldShx && Fld<int>(win, 0x190) == oldShy) {
            Fld<int>(win, 0x18C) = s.hx;
            Fld<int>(win, 0x190) = s.hy;
        }
    }
}

// The map windows that already hold sprite i with its native hotspot (set before the enlargement) get the scaled one.
void FixHeldHotspots()
{
    for (uintptr_t k = 0; k < kMapWinCount; ++k) {
        BYTE* con = Ref<BYTE*>(kVA_MapWins + 4 * k);
        if (!con) continue;
        BYTE* vt = Fld<BYTE*>(con, 0);
        if (!vt) continue;
        BYTE* win = con + Fld<int>(vt, 4);
        const uintptr_t held = Fld<uintptr_t>(win, 0x188);
        if (!IsOurSprite(held)) continue;
        const State& s = g_st[(held - kVA_Sprites) / kSpriteStride];
        if (s.g && Fld<int>(win, 0x18C) == s.hx && Fld<int>(win, 0x190) == s.hy) {
            Fld<int>(win, 0x18C) = s.shx;
            Fld<int>(win, 0x190) = s.shy;
        }
    }
}

void EnsureScaledInner()
{
    const int g = Ref<int>(kVA_G);
    if (g <= cursor_law::kNativeG || g > 64) return;  // native, not yet known, or not a plausible g
    // the sprite the software cursor draws now: never resized under Win_update_cursor's cached size / save-under
    // (it is done on a later call, once another sprite -- or none -- is on screen)
    BYTE* const onScreen = Ref<BYTE*>(kVA_CurSprite);
    bool changed = false;
    for (int i = 0; i < kCount; ++i) {
        BYTE* sp = Sprite(i);
        State& s = g_st[i];
        BYTE* bits = Fld<BYTE*>(sp, kBits);
        if (!bits) continue;                          // an empty cell (Sprite_init found no content)
        if (Fld<int>(sp, kNotMine) == 0) {
            // a fresh engine cut (first time, or load_cursors re-ran): native pixels, native hotspots in the arrays.
            // Re-capture NOW, even when it is on screen and its enlargement must wait: a stale s.g would make the
            // hook swap a scaled hotspot onto native pixels (audit 2026-10-15).
            const bool wasScaled = s.g != 0;
            const int oldShx = s.shx, oldShy = s.shy;
            if (!Capture(i, sp)) { s.captured = false; s.g = 0; continue; }
            if (wasScaled) RestoreHeldHotspots(i, oldShx, oldShy);
        } else if (s.g == g && !s.scaled.empty() && bits == s.scaled.data()) {
            continue;                                 // done
        } else if (!s.captured || s.scaled.empty() || bits != s.scaled.data()) {
            continue;                                 // flagged by someone else: not ours to touch
        }
        if (sp == onScreen) continue;                 // deferred: not resized under Win_update_cursor's cached size
        Apply(i, sp, g);
        changed = true;
    }
    if (changed) FixHeldHotspots();
}

void EnsureScaled()
{
    __try { EnsureScaledInner(); } __except (EXCEPTION_EXECUTE_HANDLER) { }
}

int CursorIndexOf(const BYTE* sprite)
{
    const uintptr_t p = reinterpret_cast<uintptr_t>(sprite);
    return IsOurSprite(p) ? static_cast<int>((p - kVA_Sprites) / kSpriteStride) : -1;
}

using FSetCursor = int(__fastcall*)(void* win, void* edx, BYTE* sprite, int hx, int hy);

// Win_set_cursor(this = Win, sprite, hx, hy), thiscall RET 0xC
int __fastcall HookSetCursor(void* win, void* edx, BYTE* sprite, int hx, int hy)
{
    EnsureScaled();
    const int i = CursorIndexOf(sprite);
    if (i >= 0) {
        const State& s = g_st[i];
        if (s.g && hx == s.hx && hy == s.hy) { hx = s.shx; hy = s.shy; }
    }
    return reinterpret_cast<FSetCursor>(static_cast<void*>(g_tramp))(win, edx, sprite, hx, hy);
}

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(va); }

} // namespace

void InstallCursorScale()
{
    uintptr_t lo = 0, hi = 0;
    if (!UimodPcave2Range(&lo, &hi)) {
        UimodLog("[uimod] cursorscale: no patcher cave (unscaled exe) -> map cursors stay native\n");
        return;
    }
    if (memcmp(At(kVA_SetCursor), kSetCursorEntry, sizeof kSetCursorEntry) != 0 ||
        memcmp(At(kVA_CursorOnReads), kCursorOnReads, sizeof kCursorOnReads) != 0) {
        UimodLog("[uimod] cursorscale: unexpected bytes at Win_set_cursor / Console_cursor_on -> map cursors stay native\n");
        return;
    }
    DWORD old;
    if (!VirtualProtect(g_tramp, sizeof g_tramp, PAGE_EXECUTE_READWRITE, &old)) return;
    BYTE* fn = At(kVA_SetCursor);
    memcpy(g_tramp, fn, kSteal);
    g_tramp[kSteal] = 0xE9;
    const int32_t back = static_cast<int32_t>((fn + kSteal) - (g_tramp + kSteal + 5));
    memcpy(g_tramp + kSteal + 1, &back, 4);
    if (!VirtualProtect(fn, kSteal, PAGE_EXECUTE_READWRITE, &old)) return;
    fn[0] = 0xE9;
    const int32_t fwd = static_cast<int32_t>(reinterpret_cast<BYTE*>(&HookSetCursor) - (fn + 5));
    memcpy(fn + 1, &fwd, 4);
    fn[5] = 0xCC;
    VirtualProtect(fn, kSteal, old, &old);
    FlushInstructionCache(GetCurrentProcess(), fn, kSteal);
    UimodLog("[uimod] cursorscale: map cursors scale with the UI (Win_set_cursor; CURSOR.PCX, 12 sprites)\n");
}
