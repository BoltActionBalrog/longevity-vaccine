// terrainhd.cpp -- drop-in HD terrain textures (GitHub issue #1: "the ability to drop-in their own custom terrain
// packs", like the custom portrait files). First written by Nidhogg-chew-root (terrain-hd-hook); reworked for the
// reviews of 2026-11-12 and 2026-11-16.
//
// The pack: <game>\terrain\texture_x8.pcx, TEXTURE.PCX redrawn at 8x (8192 x 6144), 8-bit, in the STOCK file's
// palette and indices -- the rasterizer shades by adding to the index (Texture_draw's `add al, ch`), so a pack in
// another palette layout shades into the wrong colours. hdpack::Load proves it (bounded scan, size, the stock
// TEXTURE.PCX palette) and keeps only its RLE stream. Optional beside it: terrain\rainfall_x8.pcx, RAINFALL.PCX at
// 8x (5120 x 3840) in RAINFALL.PCX's own palette, for the coast composites and the territory border (below).
//
// One level for the session (terrainhd::Level): the smallest of 2x / 4x / 8x that keeps a texel per pixel across a
// tile (8i px wide) at the screen's deepest PRACX zoom -- 2x at 1024 x 768, 4x from 1280 x 1024 to 1920 x 1080, 8x
// from 2560 x 1440 up. PRACX + Thinker reaches the same deepest zoom (measured in game at 3840 x 1080: a 448 px tile
// by wheel and by key). Every terrain texture is cut at that level, so the main map at any zoom, the base screen, the
// HUD tile view and the Datalinks page all sample the same art; nothing changes level as the map zooms.
//
// Engine (the stock and PRACX exes alike):
//  * load_terrain 0x451C50 (every game_init) loads TEXTURE.PCX into the loading canvas 0x798668 with
//    Buffer_load_pcx(name, 0, 10, 236) -- loaded index = file index + 10, 255 -> 9 -- and cuts 160 terrain Textures
//    with Texture_extract_2 0x619710 from 19 call sites (0x451D0B..0x452171), 56x56, TexHeap 0: each Texture owns a
//    w*h copy whose row stride is its width. Three more are code maps drawn from RAINFALL.PCX into a local Buffer
//    through a remap table (0x452195..0x4523A6): the two coast composites (0x4522CA / 0x4522E5, 56x56: a texel is the
//    index of its colour in the 53 at 0x6846F8) and the territory border (0x4523A6, 60x60, 9 colours, background 9).
//    They are pictures as well as masks: the coast draw writes a flat shore colour for most codes, the border draw
//    blends each code's layer over the map.
//  * Every textured draw goes through one of ten rasterizers. Each sets the drawn texture's bits pointer (0x9BB544)
//    at its start and steps rows by the texture's own width; per span it captures the left edge's u, v (0x9BB4F8,
//    0x9BB53C, from the edge walkers 0x61FC90 / 0x624D80) and stores the per-pixel steps du, dv (0x9BB4E4,
//    0x9BB4C8, by fistp, from a floating-point divide). Those four stores are the only writes of a span's texture
//    coordinates besides the clipping pre-step, which adds du * clip to them. There are 25 span setups, 4 stores
//    each: kSpanSites.
//  * The texture coordinates themselves (two UV tables, eight 0x37 immediates, the composites' UVs, PRACX's Alt+T
//    images swapped into 0x464215 / 0x464353) stay stock.
//
// Placement, exact: a texture at level k is the stock picture with each texel a k x k block (or the pack's redraw of
// it). Each of the 100 span stores runs as stock and is then multiplied by k (shl log2 k) when the bits being drawn
// are ours; the pre-step then adds k du * clip to k u. So every coordinate the rasterizer samples is exactly k times
// the stock one -- the same integer texel at stock, the k x k block it became at the level -- and with the same
// picture, switching the row changes no pixel (test_terrainhd_exact.py: the real rasterizers under emulation, every
// span setup the exe can reach; 13 of the 25 are in functions nothing calls). A texture's own corner coordinates
// (+0x0C..+0x68: Texture_draw_trans_2's and the coast's UVs) stay a stock cut's for the same reason. Everything not
// ours (PRACX's overlays, the border without RAINFALL art, every non-terrain texture) is multiplied by 1: drawn
// natively.
//
// Levers, all byte-checked, all-or-nothing:
//  * the 22 extract calls -> ExtractRecorder: which Texture is which TEXTURE.PCX rect, coast composite or the border.
//  * the 8 calls of MapWin_gen_terrain_poly 0x4632D0 -> GenTerrainPolyHook: the level is cut (if the textures are
//    stock and the row is on) before any texture is read, on the game thread.
//  * the 100 span stores -> a call into a stub (the store as it was, then the multiply; registers and flags kept):
//    SpanStubs. A stub decides by the bits pointer: the last one is cached; a new one is looked up in the list of
//    ours (repne scasd, no C, no FPU, so the rasterizer's floating-point stack is untouched).
//  * a level is installed by giving every recorded Texture new bits at nk x nk. The bits are allocated the way
//    Texture_extract_2 allocates them (mem_alloc 0x5D4510; the old ones freed with free 0x644EF2, as Texture_close
//    does) and filled directly: no Buffer, so no quiet failure in between. TEXTURE.PCX's textures come from the pack
//    (each 8x cell shrunk to the level by basehd_law::PaletteBoxShrink, used as painted at 8x). The code maps come
//    from rainfall_x8.pcx by the engine's own rule (terrainhd::Code: each texel the centre of its 8/k block, as a
//    code is a class, not a colour), piece by piece: a piece the art leaves empty falls back -- a coast composite to
//    terrainhd::Nearest of its stock pixels (it shares its UVs with the enlarged ocean), the border to stock (not
//    ours). Back to stock the same way, texture by texture from the stock copy: a step that cannot fail quietly, so
//    the textures are always all stock or all at the level, and every recorded texture always has bits.
//  * anything that stops a level (the pack unreadable or changed since startup, no address room for the level) is
//    decided once: logged, stock for the session, no further work on later passes; switching the row off and on tries
//    again once.
//
// Native no-op: no usable pack, no Longevity Preferences tab, or any unexpected byte -> nothing patched, no row.
// "HD Terrain" in Longevity Mod Preferences ([UIMod] TerrainHD) switches it live. On, the hook holds the cut
// textures (160 + 2 at 56k x 56k and the border at 60k x 60k: 32.7 MB at 8x, 8.2 MB at 4x) and the stock pixels to
// restore (0.5 MB);
// the pack's bytes are read for a cut and freed right after. Off, the stock textures are back, the list of ours is
// empty (every stub multiplies by 1) and nothing is held. The engine's fatal exit on an allocation failure is
// bounded, not gone: each texture's bits are a mem_alloc (at most 448 x 448), as in Texture_extract_2, and the
// address room for the whole level is probed before the first one.

#include "terrainhd.h"
#include "terrainhd_law.h"
#include "basehd_law.h"
#include "hdpack.h"

#include <windows.h>
#include <psapi.h>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

void UimodLog(const char* msg);
void UimodDbg(const char* msg);
bool PrefsTabInstalled();

namespace {

constexpr uintptr_t kVA_Extract2       = 0x619710;   // Texture_extract_2: thiscall (Texture*, Buffer*, x, y, w, h, TexHeap*) RET 0x18
constexpr uintptr_t kVA_GenTerrainPoly = 0x4632D0;   // MapWin_gen_terrain_poly: cdecl, 10 args
constexpr uintptr_t kVA_MemAlloc       = 0x5D4510;   // mem_alloc: cdecl (size) -- malloc; on null a message box + exit
constexpr uintptr_t kVA_Free           = 0x644EF2;   // free: cdecl (p) -- what Texture_close frees a Texture's bits with
constexpr uintptr_t kVA_LoadingCanvas  = 0x798668;   // the Buffer TEXTURE.PCX is loaded into
constexpr uintptr_t kVA_ScreenW        = 0x9B7B1C;   // ScreenWidth
constexpr uintptr_t kVA_ScreenH        = 0x9B7B20;   // ScreenHeight
constexpr uintptr_t kVA_DrawMap        = 0x46B190;   // draw_map: cdecl(int) -- full map repaint
constexpr uintptr_t kVA_StatusWinRedraw = 0x4B9EA0; // StatusWin_redraw: thiscall (StatusWin*)
constexpr uintptr_t kVA_StatusWin      = 0x8C5568;   // StatusWin_g
constexpr uintptr_t kVA_GraphicWinRedraw = 0x5D5A70; // GraphicWin_redraw: thiscall (GraphicWin*)
constexpr uintptr_t kVA_BaseWin        = 0x6A7628;   // BaseWin_g (+0x9C bit 0: on screen)
constexpr uintptr_t kVA_TexBits        = 0x9BB544;   // the drawn texture's bits (each rasterizer sets it first)

const uint32_t kExtractSites[] = {
    0x451D0B, 0x451D27, 0x451D50, 0x451D8F, 0x451DB6, 0x451DE0, 0x451E24, 0x451E86, 0x451EBF, 0x451EE9,
    0x451F32, 0x451F76, 0x451FBF, 0x452000, 0x452030, 0x452081, 0x4520E1, 0x452128, 0x452171,   // TEXTURE.PCX
    0x4522CA, 0x4522E5,                                                                         // RAINFALL composites
    0x4523A6,                                                                                   // the territory border
};

// RAINFALL.PCX's code maps (load_terrain 0x452195..0x4523A6): the coast composites are its region at (2, 333), 56 x 56
// each, 57 apart, through the 53 colours at 0x6846F8; the territory border its region at (2, 254), 60 x 60, through 9
// colours load_terrain writes with `mov byte [ebp-0x1C+i], c` (0x452307), on a Buffer filled with 9. A texel is the
// index of its colour, the background for the see-through 255, 0 for any other colour (terrainhd::Code).
constexpr uintptr_t kVA_CompColours = 0x6846F8, kVA_BorderMovs = 0x452307;
const uint8_t kCompColours[53] = { 5, 148, 67, 131, 180, 201, 7, 9, 11, 13, 39, 41, 43, 45, 193, 194, 195, 196, 58, 59,
                                   60, 62, 146, 147, 149, 151, 23, 25, 27, 29, 71, 73, 75, 77, 103, 105, 107, 109, 136,
                                   137, 139, 140, 116, 118, 119, 121, 88, 89, 90, 165, 166, 96, 144 };
const uint8_t kBorderColours[9] = { 0xD3, 0xD0, 0x29, 0x8F, 0x74, 0x97, 0xCE, 0x5F, 0xC0 };
constexpr int kRainW = 640, kRainH = 480;
constexpr int kCompX = 2, kCompX2 = 59, kCompY = 333, kBorderX = 2, kBorderY = 254, kBorder = 60;
const uint32_t kGenSites[] = { 0x40F35F, 0x468C73, 0x46927C, 0x469308, 0x469E47, 0x47130C, 0x4B6B9C, 0x4BDF5C };

// The 25 span setups' four coordinate stores: u (mov [0x9BB4F8], eax) and v (mov [0x9BB53C], edx / ecx) -- v first in
// two setups -- then du (fistp dword [0x9BB4E4]) and dv (fistp dword [0x9BB4C8]). test_terrainhd_sites.py: the exe's
// complete census.
const uint32_t kSpanSites[] = {
    0x619AF0, 0x619AF5, 0x619BC5, 0x619BD1, 0x619FB0, 0x619FB5, 0x61A085, 0x61A091, 0x61A465, 0x61A46A,
    0x61A53A, 0x61A546, 0x61A965, 0x61A96A, 0x61AA3A, 0x61AA46, 0x61AE8B, 0x61AE90, 0x61AF78, 0x61AF84,
    0x61B432, 0x61B437, 0x61B51F, 0x61B52B, 0x61B9BA, 0x61B9C9, 0x61BABC, 0x61BAC8, 0x61C2D2, 0x61C2D7,
    0x61C3BF, 0x61C3CB, 0x61C8A6, 0x61C8AB, 0x61C97B, 0x61C987, 0x61CDE7, 0x61CDEC, 0x61CEBC, 0x61CEC8,
    0x61D2C0, 0x61D2CF, 0x61D3C2, 0x61D3CE, 0x61DC32, 0x61DC41, 0x61DD34, 0x61DD40, 0x61E1FD, 0x61E20C,
    0x61E2FF, 0x61E30B, 0x61E775, 0x61E784, 0x61E877, 0x61E883, 0x61ED2E, 0x61ED3D, 0x61EE30, 0x61EE3C,
    0x620C6B, 0x620C7D, 0x620D52, 0x620D5E, 0x621552, 0x621557, 0x621649, 0x621655, 0x621B02, 0x621B11,
    0x621C0C, 0x621C18, 0x6224D4, 0x6224E6, 0x6225D3, 0x6225DF, 0x622A88, 0x622A97, 0x622B92, 0x622B9E,
    0x62302D, 0x623032, 0x62311A, 0x623126, 0x62363D, 0x623642, 0x62372A, 0x623736, 0x623C15, 0x623C1A,
    0x623CEA, 0x623CF6, 0x624225, 0x624234, 0x624327, 0x624333, 0x6248DB, 0x6248E0, 0x6249C8, 0x6249D4,
};
static_assert(sizeof kSpanSites / sizeof kSpanSites[0] == 100, "25 span setups x 4 stores");
constexpr uint32_t kSpanU = 0x9BB4F8, kSpanV = 0x9BB53C, kSpanDu = 0x9BB4E4, kSpanDv = 0x9BB4C8;

// The entry bytes of every engine function the hook calls itself (the call sites prove the rest).
struct Entry8 { uintptr_t va; BYTE b[6]; };
const Entry8 kEntries[] = {
    { kVA_Extract2,   { 0x53, 0x55, 0x56, 0x57, 0x8B, 0x7C } },
    { kVA_MemAlloc,   { 0x8B, 0x44, 0x24, 0x04, 0x50, 0xE8 } },
    { kVA_Free,       { 0x56, 0x8B, 0x74, 0x24, 0x08, 0x85 } },
    { kVA_GenTerrainPoly, { 0x55, 0x8B, 0xEC, 0x6A, 0xFF, 0x68 } },
};

// Texture (0x70 bytes): bits +0, width +4, height +8 (the row stride), +0x0C..+0x68 the corner and half-way texel
// coordinates Texture_extract_2 sets from the size (TexCorners), +0x6C 1 = bits from a TexHeap (not freed).
constexpr int kTexSize = 0x70, kTexHeap = 0x6C;

// What Texture_extract_2 writes to +0x0C..+0x68 after a cut of w x h (0x61985F..0x6198C6), slot by slot.
void TexCorners(int32_t* f, int w, int h)              // f = the Texture as dwords
{
    const int w1 = w - 1, h1 = h - 1, w2 = w / 2 - 1, h2 = h / 2 - 1;
    // +0x0C, +0x10, ... +0x68: test_terrainhd_cache.py compares them with the engine's own code run under emulation
    const int32_t v[24] = { 0, 0, w1, 0, w1, h1, 0, h1, 0, 0, w2, 0, w1, 0, w1, h2, w1, h1, w2, h1, 0, h1, 0, h2 };
    for (int i = 0; i < 24; ++i) f[0x0C / 4 + i] = v[i];
}
constexpr int kTex = terrainhd::kTile, kCell = kTex * terrainhd::kMaster;   // 56, 448
constexpr int kMaxEntries = 192;                       // 162 in the stock load_terrain
constexpr size_t kStockBytes = static_cast<size_t>(kTex) * kTex;

struct Texture { uint8_t* data; int w; int h; };

enum Kind { kSheet, kComposite, kBorderTex };

struct Entry {
    Texture* tex;
    int x, y;                                          // its rect in TEXTURE.PCX (sheet) / the composite's buffer
    Kind kind;
    int n;                                             // its stock size: 56, the border 60
    bool atLevel;                                      // cut at the level (the border only with RAINFALL art)
    size_t stock;                                      // its pixels' offset in g_stock
};

// What the span stubs read: the bits pointers that are ours and the shift for them. Written only on the game thread,
// between draws; `last` is reset whenever the list changes, so a freed pointer the allocator hands out again is
// looked up afresh.
struct SpanData {
    const void* last;                                  // the bits pointer last looked up (1: none)
    uint32_t shift;                                    // ... its shift: log2 k if ours, else 0
    uint32_t count;                                    // entries in ptrs
    uint32_t levelShift;                               // log2 of the installed level (0 at stock)
    const void* ptrs[kMaxEntries];
};

// The stubs: a lookup routine, then one stub per span store. Pure x86, generated from addresses only, so the test
// can generate the same bytes for an emulated image (terrainhd_cache_selftest "stubs").
constexpr size_t kLookupBytes = 64, kStubBytes = 48, kStubArea = kLookupBytes + kStubBytes * 100;   // 51 and 42 used

void Put32(uint8_t*& p, uint32_t v) { memcpy(p, &v, 4); p += 4; }

// The length of a span store: mov [g], eax is 5 bytes; mov [g], edx / ecx and fistp dword [g] are 6.
size_t SpanStoreBytes(const uint8_t* o) { return o[0] == 0xA3 ? 5 : 6; }

// Writes the lookup routine and the 100 stubs at out (which runs at outVa), reading `site` bytes from `orig` (the 5 or
// 6 original bytes of each site, back to back as in kSpanSites order: the caller copies them from the image).
// patch[i] receives the 6 bytes to write over site i (E8 rel32 to its stub, then a nop if the store was 6 bytes).
// Returns false if a site's bytes are not one of the four known stores.
bool BuildSpanStubs(uint8_t* out, uint32_t outVa, uint32_t dataVa, const uint8_t (*orig)[6], uint8_t (*patch)[6])
{
    const uint32_t last = dataVa + offsetof(SpanData, last), shift = dataVa + offsetof(SpanData, shift),
                   count = dataVa + offsetof(SpanData, count), level = dataVa + offsetof(SpanData, levelShift),
                   ptrs = dataVa + offsetof(SpanData, ptrs);
    // lookup: ecx = bits. last = ecx; shift = (ecx in ptrs[0..count)) ? levelShift : 0. Keeps every register.
    uint8_t* p = out;
    *p++ = 0x50; *p++ = 0x57; *p++ = 0x51;                         // push eax; push edi; push ecx
    *p++ = 0x89; *p++ = 0x0D; Put32(p, last);                      // mov [last], ecx
    *p++ = 0x8B; *p++ = 0xC1;                                      // mov eax, ecx
    *p++ = 0xBF; Put32(p, ptrs);                                   // mov edi, ptrs
    *p++ = 0x8B; *p++ = 0x0D; Put32(p, count);                     // mov ecx, [count]
    *p++ = 0xFC;                                                   // cld
    *p++ = 0x85; *p++ = 0xC9;                                      // test ecx, ecx
    *p++ = 0x74; *p++ = 0x0C;                                      // jz notfound
    *p++ = 0xF2; *p++ = 0xAF;                                      // repne scasd
    *p++ = 0x75; *p++ = 0x08;                                      // jne notfound
    *p++ = 0x8B; *p++ = 0x0D; Put32(p, level);                     // mov ecx, [levelShift]
    *p++ = 0xEB; *p++ = 0x02;                                      // jmp store
    *p++ = 0x33; *p++ = 0xC9;                                      // notfound: xor ecx, ecx
    *p++ = 0x89; *p++ = 0x0D; Put32(p, shift);                     // store: mov [shift], ecx
    *p++ = 0x59; *p++ = 0x5F; *p++ = 0x58;                         // pop ecx; pop edi; pop eax
    *p++ = 0xC3;                                                   // ret
    if (static_cast<size_t>(p - out) > kLookupBytes) return false;
    const uint32_t lookupVa = outVa;
    for (int i = 0; i < 100; ++i) {
        const uint8_t* o = orig[i];
        int n = 0;
        uint32_t g = 0;
        bool fistp = false;
        if (o[0] == 0xA3) { n = 5; memcpy(&g, o + 1, 4); }                                  // mov [g], eax
        else if (o[0] == 0x89 && (o[1] == 0x15 || o[1] == 0x0D)) { n = 6; memcpy(&g, o + 2, 4); }   // mov [g], edx/ecx
        else if (o[0] == 0xDB && o[1] == 0x1D) { n = 6; memcpy(&g, o + 2, 4); fistp = true; }   // fistp dword [g]
        else return false;
        // u and v are moved from the edge, du and dv come from the divide (two setups store v before u)
        if (fistp ? (g != kSpanDu && g != kSpanDv) : (g != kSpanU && g != kSpanV)) return false;
        uint8_t* s = out + kLookupBytes + kStubBytes * i;
        const uint32_t sVa = outVa + static_cast<uint32_t>(kLookupBytes + kStubBytes * i);
        uint8_t* q = s;
        memcpy(q, o, n); q += n;                                    // the store, as it was
        *q++ = 0x9C;                                               // pushfd
        *q++ = 0x51;                                               // push ecx
        *q++ = 0x8B; *q++ = 0x0D; Put32(q, kVA_TexBits);           // mov ecx, [0x9BB544]
        *q++ = 0x3B; *q++ = 0x0D; Put32(q, last);                  // cmp ecx, [last]
        *q++ = 0x74; *q++ = 0x05;                                  // je +5
        *q++ = 0xE8; Put32(q, lookupVa - (sVa + static_cast<uint32_t>(q - s) + 4));   // call lookup
        *q++ = 0x8B; *q++ = 0x0D; Put32(q, shift);                 // mov ecx, [shift]
        *q++ = 0xD3; *q++ = 0x25; Put32(q, g);                     // shl dword [g], cl
        *q++ = 0x59;                                               // pop ecx
        *q++ = 0x9D;                                               // popfd
        *q++ = 0xC3;                                               // ret
        if (static_cast<size_t>(q - s) > kStubBytes) return false;
        uint8_t* w = patch[i];
        const uint32_t siteVa = kSpanSites[i];
        w[0] = 0xE8;
        const uint32_t rel = sVa - (siteVa + 5);
        memcpy(w + 1, &rel, 4);
        w[5] = n == 6 ? 0x90 : o[5];                                // (a 5-byte store: only 5 are written)
    }
    return true;
}

// The engine functions the module calls (bound from the exe at install; a fake engine under TERRAINHD_SELFTEST).
struct Engine {
    int (__thiscall* extract)(void*, void*, int, int, int, int, void*);
    int (__cdecl* gen)(void*, void*, int, int, int, int, int, int, int, int);
    void* (__cdecl* alloc)(size_t);                   // mem_alloc: never returns null (the engine exits instead)
    void (__cdecl* free)(void*);
    void (__cdecl* drawMap)(int);
    int (__thiscall* statusRedraw)(void*);
    void (__thiscall* graphicRedraw)(void*);
};

Engine g_eng = {};
Entry g_entries[kMaxEntries];
int g_count = 0;
uint8_t* g_stock = nullptr;                            // the entries' stock pixels while a level is installed
int g_level = 1;                                       // installed level; 1 = stock
bool g_dirty = false;                                  // load_terrain cut stock textures since the last install
bool g_failed = false;                                 // a level could not be made: stock until the row is switched
bool g_installed = false;
int g_on = kTerrainHdDefault;
uint8_t g_pal[768];                                    // TEXTURE.PCX's palette (the pack must match it)
uint8_t g_rainPal[768];                                // RAINFALL.PCX's (rainfall_x8.pcx must match it)
bool g_rainOk = false;                                 // the exe's RAINFALL colour lists are the ones above
SpanData g_span = { reinterpret_cast<const void*>(1), 0, 0, 0, {} };
char g_dir[MAX_PATH];

#ifdef TERRAINHD_SELFTEST
BYTE* g_testImage = nullptr;                           // the fake exe image (0x400000-based)
char g_testDir[MAX_PATH];
bool g_testNoRoom = false;                             // the address-room probe fails
int g_testPackLoads = 0;                               // LoadPack calls
BYTE* ImageBase() { return g_testImage; }
#else
BYTE* ImageBase() { return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)); }
#endif

BYTE* At(uintptr_t va) { return ImageBase() + (va - 0x400000); }

void Log(const char* fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(buf, sizeof buf, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(buf);
}

bool CallsTo(uint32_t site, uintptr_t target)
{
    const BYTE* p = At(site);
    if (p[0] != 0xE8) return false;
    int32_t rel;
    memcpy(&rel, p + 1, 4);
    return reinterpret_cast<uintptr_t>(p) + 5 + rel == reinterpret_cast<uintptr_t>(At(target));
}

void Retarget(uint32_t site, const void* fn)
{
    BYTE* p = At(site);
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(fn) - (reinterpret_cast<uintptr_t>(p) + 5));
    DWORD old;
    VirtualProtect(p + 1, 4, PAGE_EXECUTE_READWRITE, &old);
    memcpy(p + 1, &rel, 4);
    VirtualProtect(p + 1, 4, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 5);
}

// The list of ours for the span stubs: the recorded textures' bits at level k (count 0 at stock). The cached pointer
// is dropped, so the next span looks its bits up again.
void SetSpanList(int k)
{
    g_span.count = 0;
    g_span.levelShift = k == 8 ? 3 : k == 4 ? 2 : k == 2 ? 1 : 0;
    if (k != 1)
        for (int i = 0; i < g_count; ++i)
            if (g_entries[i].atLevel) g_span.ptrs[g_span.count++] = g_entries[i].tex->data;
    g_span.last = reinterpret_cast<const void*>(1);
}

// New engine bits of side x side for t, filled by fill(bits), then the old bits freed: what Texture_extract_2 does
// (mem_alloc, its rows at stride side, the size, the heap flag 0), without a Buffer in between; the corner
// coordinates are an n x n cut's, as for every coordinate of ours (stock, scaled by the span stubs). mem_alloc does
// not return null (the engine exits instead), so this cannot fail quietly and t never holds a texture without bits.
template <class Fill>
void GiveBits(Texture* t, int side, int n, Fill fill)   // n: the texture's stock size (56, the border 60)
{
    uint8_t* bits = static_cast<uint8_t*>(g_eng.alloc(static_cast<size_t>(side) * side));
    fill(bits);
    uint8_t* old = t->data;
    int* heap = reinterpret_cast<int*>(reinterpret_cast<uint8_t*>(t) + kTexHeap);
    const bool ours = *heap == 0;
    t->data = bits;
    t->w = side;
    t->h = side;
    // the corner coordinates stay the STOCK texture's: Texture_draw_trans_2 (0x61A240) draws from them as its UVs,
    // and the span stubs multiply every coordinate of our textures by k
    TexCorners(reinterpret_cast<int32_t*>(t), n, n);
    *heap = 0;
    if (old && ours) g_eng.free(old);
}

// Room for `bytes` of engine allocations (each one a mem_alloc that exits the process when it fails): reserved and
// released, so a level that would not fit is refused before its first allocation.
bool RoomFor(size_t bytes)
{
#ifdef TERRAINHD_SELFTEST
    if (g_testNoRoom) return false;
#endif
    void* probe = VirtualAlloc(nullptr, bytes + (8u << 20), MEM_RESERVE, PAGE_READWRITE);
    if (!probe) return false;
    VirtualFree(probe, 0, MEM_RELEASE);
    return true;
}

bool GameDir(char* out, size_t n)
{
#ifdef TERRAINHD_SELFTEST
    return strcpy_s(out, n, g_testDir) == 0;
#else
    const DWORD len = GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    if (len == 0 || len >= n) return false;
    char* slash = strrchr(out, '\\');
    if (!slash) return false;
    slash[1] = 0;
    return true;
#endif
}

void PackPath(char* out, size_t n) { _snprintf_s(out, n, _TRUNCATE, "%sterrain\\texture_x8.pcx", g_dir); }
void IniPath(char* out, size_t n) { _snprintf_s(out, n, _TRUNCATE, "%sAlpha Centauri.ini", g_dir); }

// The pack, proven (size, bounded scan, TEXTURE.PCX's palette). Logged when it fails.
bool LoadPack(hdpack::Pack* p)
{
#ifdef TERRAINHD_SELFTEST
    ++g_testPackLoads;
#endif
    char path[MAX_PATH];
    PackPath(path, sizeof path);
    const hdpack::Result r = hdpack::Load(p, path, terrainhd::kStockSheetW * terrainhd::kMaster,
                                          terrainhd::kStockSheetH * terrainhd::kMaster, g_pal);
    if (r == hdpack::kOk) return true;
    Log("[terrainhd] terrain\\texture_x8.pcx is not usable (%s) -> stock terrain\n", hdpack::Why(r));
    return false;
}

// Every recorded texture back to its stock pixels, texture by texture from the stock copy, then the list of ours
// emptied (the span stubs multiply by 1 again); the stock copy freed. Nothing in it can fail quietly (GiveBits), so
// the result is all stock.
void RestoreStock()
{
    if (g_stock)
        for (int i = 0; i < g_count; ++i) {
            Entry& e = g_entries[i];
            if (!e.atLevel) continue;                    // never cut (the border without RAINFALL art)
            const uint8_t* px = g_stock + e.stock;
            const size_t bytes = static_cast<size_t>(e.n) * e.n;
            GiveBits(e.tex, e.n, e.n, [px, bytes](uint8_t* b) { memcpy(b, px, bytes); });
            e.atLevel = false;
        }
    g_level = 1;
    SetSpanList(1);
    free(g_stock);
    g_stock = nullptr;
}

// The colours of the loaded indices (loaded = file + 10): what PaletteBoxShrink compares.
void LoadedColours(uint8_t rgbq[1024])
{
    for (int i = 0; i < 256; ++i) {
        const int v = (i + 10) & 255;
        rgbq[v * 4 + 0] = g_pal[i * 3 + 2];
        rgbq[v * 4 + 1] = g_pal[i * 3 + 1];
        rgbq[v * 4 + 2] = g_pal[i * 3 + 0];
        rgbq[v * 4 + 3] = 0;
    }
}

// RAINFALL.PCX at 8x (terrain\rainfall_x8.pcx), optional: true and loaded when it is there and usable. Without it the
// coast composites are their own stock pixels at the level and the border stays stock. Logged when it is there but
// cannot be used.
bool LoadRainPack(hdpack::Pack* p)
{
    if (!g_rainOk) return false;
    char path[MAX_PATH];
    _snprintf_s(path, sizeof path, _TRUNCATE, "%sterrain\\rainfall_x8.pcx", g_dir);
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return false;
    const hdpack::Result r = hdpack::Load(p, path, kRainW * terrainhd::kMaster, kRainH * terrainhd::kMaster, g_rainPal);
    if (r == hdpack::kOk) return true;
    Log("[terrainhd] terrain\\rainfall_x8.pcx is not usable (%s) -> stock coast composites and border\n",
        hdpack::Why(r));
    return false;
}

// A RAINFALL code map at level k from the pack's 8x region at (x, y), n x n stock texels, into out; false if the pack
// has nothing there (all see-through: that piece is not in the pack) or the region cannot be read.
bool RainCode(const hdpack::Pack& pack, int x, int y, int n, const uint8_t* cols, int ncols, uint8_t bg, int k,
              uint8_t* out)
{
    const int side = n * terrainhd::kMaster;
    uint8_t ident[256];
    for (int i = 0; i < 256; ++i) ident[i] = static_cast<uint8_t>(i);
    uint8_t* region = static_cast<uint8_t*>(malloc(static_cast<size_t>(side) * side));
    if (!region) return false;
    bool ok = hdpack::Expand(pack, x * terrainhd::kMaster, y * terrainhd::kMaster, side, side, ident, region);
    if (ok) {
        bool any = false;
        for (size_t i = 0; i < static_cast<size_t>(side) * side && !any; ++i) any = region[i] != 255;
        ok = any;
    }
    if (ok) terrainhd::Code(region, side, n, cols, ncols, bg, k, out);
    free(region);
    return ok;
}

// Every recorded texture at level k. The textures are stock when this runs (load_terrain's cut, or restored). False,
// logged once, when the level cannot be made; the textures are then all stock (the caller latches g_failed).
bool InstallLevel(int k)
{
    g_dirty = false;
    if (g_count == 0) return true;
    const DWORD t0 = GetTickCount();
    size_t level = 0, stockBytes = 0;
    for (int i = 0; i < g_count; ++i) {
        Entry& e = g_entries[i];
        const Texture* t = e.tex;
        if (!t->data || t->w != e.n || t->h != e.n) {
            Log("[terrainhd] texture %d is not a stock %dx%d texture -> stock terrain until the row is switched\n", i,
                e.n, e.n);
            return false;
        }
        e.stock = stockBytes;
        stockBytes += static_cast<size_t>(e.n) * e.n;
        level += static_cast<size_t>(e.n * k) * (e.n * k);
    }
    int x0 = 1 << 30, x1 = 0;                           // the widest band any texture row needs
    for (int i = 0; i < g_count; ++i)
        if (g_entries[i].kind == kSheet) {
            if (g_entries[i].x < x0) x0 = g_entries[i].x;
            if (g_entries[i].x + kTex > x1) x1 = g_entries[i].x + kTex;
        }
    const size_t bandMax = x1 > x0 ? static_cast<size_t>(x1 - x0) * terrainhd::kMaster * kCell : 0;
    const size_t rainMax = static_cast<size_t>(kBorder * terrainhd::kMaster) * (kBorder * terrainhd::kMaster);
    if (!RoomFor(level + bandMax + rainMax + stockBytes)) {
        Log("[terrainhd] no address room for the %dx level (%u MB) -> stock terrain until the row is switched\n", k,
            static_cast<unsigned>(level >> 20));
        return false;
    }
    hdpack::Pack pack = {};
    if (!LoadPack(&pack)) return false;                  // logged
    g_stock = static_cast<uint8_t*>(malloc(stockBytes));
    if (!g_stock) {
        hdpack::Free(&pack);
        Log("[terrainhd] no memory for the stock copy -> stock terrain until the row is switched\n");
        return false;
    }
    for (int i = 0; i < g_count; ++i)
        memcpy(g_stock + g_entries[i].stock, g_entries[i].tex->data,
               static_cast<size_t>(g_entries[i].n) * g_entries[i].n);
    hdpack::Pack rain = {};
    const bool haveRain = LoadRainPack(&rain);

    uint8_t map[256];
    for (int i = 0; i < 256; ++i) map[i] = static_cast<uint8_t>(i + 10);    // Buffer_load_pcx(.., 10, 236)
    uint8_t rgbq[1024];
    LoadedColours(rgbq);

    // one band of the sheet at a time (the rows of every texture cut from it), so each scanline is walked once
    bool ok = true;
    int fromPack = 0, fromRain = 0;
    bool done[kMaxEntries] = {};
    uint8_t* band = nullptr;
    uint8_t* code = static_cast<uint8_t*>(malloc(static_cast<size_t>(kBorder * k) * (kBorder * k)));
    if (!code) ok = false;
    for (int i = 0; i < g_count && ok; ++i) {
        if (done[i]) continue;
        Entry& e = g_entries[i];
        const int side = e.n * k;
        if (e.kind != kSheet) {
            // a RAINFALL code map: from rainfall_x8.pcx if it carries this piece, else the composite's own stock
            // pixels at the level and the border left stock (not ours: drawn natively)
            const bool comp = e.kind == kComposite;
            const bool art = haveRain &&
                (comp ? RainCode(rain, e.x == 0 ? kCompX : kCompX2, kCompY, e.n, kCompColours, 53, 0, k, code)
                      : RainCode(rain, kBorderX, kBorderY, e.n, kBorderColours, 9, 9, k, code));
            done[i] = true;
            if (art) {
                GiveBits(e.tex, side, e.n,
                         [code, side](uint8_t* b) { memcpy(b, code, static_cast<size_t>(side) * side); });
                ++fromRain;
            } else if (comp) {
                const uint8_t* px = g_stock + e.stock;
                GiveBits(e.tex, side, e.n, [px, k](uint8_t* b) { terrainhd::Nearest(px, kTex, k, b); });
            } else {
                continue;                                // the border without art: stock
            }
            e.atLevel = true;
            continue;
        }
        int bx0 = e.x, bx1 = e.x + kTex;
        for (int j = i + 1; j < g_count; ++j)
            if (!done[j] && g_entries[j].kind == kSheet && g_entries[j].y == e.y) {
                if (g_entries[j].x < bx0) bx0 = g_entries[j].x;
                if (g_entries[j].x + kTex > bx1) bx1 = g_entries[j].x + kTex;
            }
        const int bw = (bx1 - bx0) * terrainhd::kMaster;
        free(band);
        band = static_cast<uint8_t*>(malloc(static_cast<size_t>(bw) * kCell));
        if (!band || !hdpack::Expand(pack, bx0 * terrainhd::kMaster, e.y * terrainhd::kMaster, bw, kCell, map, band)) {
            Log("[terrainhd] could not read the band at row %d of texture_x8.pcx -> stock terrain until the row is "
                "switched\n", e.y);
            ok = false;
            break;
        }
        for (int j = i; j < g_count; ++j) {
            Entry& f = g_entries[j];
            if (done[j] || f.kind != kSheet || f.y != e.y) continue;
            const uint8_t* cell = band + (f.x - bx0) * terrainhd::kMaster;
            GiveBits(f.tex, side, f.n, [&](uint8_t* b) {
                if (side == kCell)                       // 8x: the cell as painted
                    for (int y = 0; y < kCell; ++y) memcpy(b + y * kCell, cell + static_cast<size_t>(y) * bw, kCell);
                else
                    basehd_law::PaletteBoxShrink(cell, kCell, kCell, bw, b, side, side, side, rgbq);
            });
            f.atLevel = true;
            ++fromPack;
            done[j] = true;
        }
    }
    free(band);
    free(code);
    hdpack::Free(&pack);
    hdpack::Free(&rain);
    if (!ok) {
        RestoreStock();                                  // the textures cut so far go back: all stock
        return false;
    }
    g_level = k;
    SetSpanList(k);
    unsigned privMb = 0, peakMb = 0;
#ifndef TERRAINHD_SELFTEST
    PROCESS_MEMORY_COUNTERS_EX pmc = {};
    pmc.cb = sizeof pmc;
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc), sizeof pmc)) {
        privMb = static_cast<unsigned>(pmc.PrivateUsage >> 20);
        peakMb = static_cast<unsigned>(pmc.PeakPagefileUsage >> 20);
    }
#endif
    Log("[terrainhd] %d textures at %dx (%d from texture_x8.pcx, %d from rainfall_x8.pcx, %u MB) in %lu ms; process %u "
        "MB private, peak %u MB\n", static_cast<int>(g_span.count), k, fromPack, fromRain,
        static_cast<unsigned>(level >> 20), GetTickCount() - t0, privMb, peakMb);
    return true;
}

int WantLevel()
{
    return terrainhd::Level(*reinterpret_cast<int*>(At(kVA_ScreenW)), *reinterpret_cast<int*>(At(kVA_ScreenH)));
}

// --- hooks ------------------------------------------------------------------------------------------------------

// Stands in for Texture_extract_2 at load_terrain's 22 sites: same contract (thiscall, RET 0x18). 56x56 from the
// loading canvas: a TEXTURE.PCX texture; 56x56 from load_terrain's local Buffer: a coast composite; 60x60: the border.
int __fastcall ExtractRecorder(Texture* tex, void* /*edx*/, void* src, int x, int y, int w, int h, void* heap)
{
    if (g_level != 1 || g_span.count) {                  // a new load_terrain: the textures are cut at stock again
        g_level = 1;
        SetSpanList(1);                                  // before the engine frees the level's bits
        free(g_stock);
        g_stock = nullptr;
    }
    const int rc = g_eng.extract(tex, src, x, y, w, h, heap);
    const bool tile = w == kTex && h == kTex, border = w == kBorder && h == kBorder;
    if (rc != 0 || !(tile || border) || !tex->data) return rc;
    int i = 0;
    while (i < g_count && g_entries[i].tex != tex) ++i;
    if (i == g_count) {
        if (g_count == kMaxEntries) return rc;
        g_entries[g_count++].tex = tex;
    }
    Entry& e = g_entries[i];
    e.x = x;
    e.y = y;
    e.n = w;
    e.kind = border ? kBorderTex : src == At(kVA_LoadingCanvas) ? kSheet : kComposite;
    e.atLevel = false;                                   // cut at stock by the engine just now
    g_dirty = true;
    return rc;
}

int __cdecl GenTerrainPolyHook(void* buf, void* win, int zoom, int a4, int a5, int a6, int a7, int a8, int a9, int a10)
{
    if (g_on && !g_failed && g_count) {
        const int want = WantLevel();
        if (g_dirty || want != g_level) {
            if (g_level != 1) RestoreStock();
            if (!InstallLevel(want)) g_failed = true;    // decided once: no more work until the row is switched
        }
    }
    return g_eng.gen(buf, win, zoom, a4, a5, a6, a7, a8, a9, a10);
}

void RepaintTerrainScreens()
{
    g_eng.drawMap(1);
    g_eng.statusRedraw(At(kVA_StatusWin));
    if (*reinterpret_cast<int*>(At(kVA_BaseWin + 0x9C)) & 1) g_eng.graphicRedraw(At(kVA_BaseWin));
}

// The 100 span stores -> calls into their stubs (generated into one execute-read page). False if a site's bytes are
// not the store this hook knows, or the page cannot be made.
bool InstallSpanScaling()
{
    uint8_t orig[100][6], patch[100][6];
    for (int i = 0; i < 100; ++i) memcpy(orig[i], At(kSpanSites[i]), 6);
#ifdef TERRAINHD_SELFTEST
    static uint8_t area[kStubArea];
    return BuildSpanStubs(area, 0x20000000, 0x20100000, orig, patch);
#else
    uint8_t* area = static_cast<uint8_t*>(VirtualAlloc(nullptr, kStubArea, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!area) return false;
    if (!BuildSpanStubs(area, static_cast<uint32_t>(reinterpret_cast<uintptr_t>(area)),
                        static_cast<uint32_t>(reinterpret_cast<uintptr_t>(&g_span)), orig, patch)) {
        VirtualFree(area, 0, MEM_RELEASE);
        return false;
    }
    DWORD old;
    if (!VirtualProtect(area, kStubArea, PAGE_EXECUTE_READ, &old)) {
        VirtualFree(area, 0, MEM_RELEASE);
        return false;
    }
    FlushInstructionCache(GetCurrentProcess(), area, kStubArea);
    for (int i = 0; i < 100; ++i) {
        BYTE* p = At(kSpanSites[i]);
        const size_t n = SpanStoreBytes(orig[i]);           // 5 for mov [g], eax: the next byte is another store's
        if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return false;   // (SpanPagesWritable checked first)
        memcpy(p, patch[i], n);
        VirtualProtect(p, n, old, &old);
        FlushInstructionCache(GetCurrentProcess(), p, n);
    }
    return true;
#endif
}

// Every page the span sites are on can be made writable (checked before the first one is written: all or nothing).
bool SpanPagesWritable()
{
#ifdef TERRAINHD_SELFTEST
    return true;
#else
    for (uint32_t s : kSpanSites) {
        DWORD old;
        if (!VirtualProtect(At(s), 6, PAGE_EXECUTE_READWRITE, &old)) return false;
        VirtualProtect(At(s), 6, old, &old);
    }
    return true;
#endif
}

void BindEngine()
{
    g_eng.extract = reinterpret_cast<decltype(g_eng.extract)>(At(kVA_Extract2));
    g_eng.gen = reinterpret_cast<decltype(g_eng.gen)>(At(kVA_GenTerrainPoly));
    g_eng.alloc = reinterpret_cast<decltype(g_eng.alloc)>(At(kVA_MemAlloc));
    g_eng.free = reinterpret_cast<decltype(g_eng.free)>(At(kVA_Free));
    g_eng.drawMap = reinterpret_cast<decltype(g_eng.drawMap)>(At(kVA_DrawMap));
    g_eng.statusRedraw = reinterpret_cast<decltype(g_eng.statusRedraw)>(At(kVA_StatusWinRedraw));
    g_eng.graphicRedraw = reinterpret_cast<decltype(g_eng.graphicRedraw)>(At(kVA_GraphicWinRedraw));
}

} // namespace

bool TerrainHdAvailable() { return g_installed; }
int  TerrainHdGet() { return g_on; }

void TerrainHdSet(int on)
{
    on = on ? 1 : 0;
    if (!g_installed || on == g_on) return;
    g_on = on;
    if (on) {
        g_failed = false;                                // tried again, once; the next terrain pass cuts the level
        g_dirty = g_count != 0;
    } else {
        RestoreStock();                                  // off holds nothing
    }
    RepaintTerrainScreens();
}

void TerrainHdSave()
{
    if (!g_installed) return;
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "TerrainHD", g_on ? "1" : "0", ini);
}

void InstallTerrainHd()
{
    if (!GameDir(g_dir, sizeof g_dir)) return;
    char path[MAX_PATH];
    PackPath(path, sizeof path);
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return;   // no pack: nothing patched, no row
    if (!PrefsTabInstalled()) {
        Log("[terrainhd] no Longevity Preferences tab on this exe -> HD terrain NOT installed\n");
        return;
    }
    for (uint32_t s : kExtractSites) if (!CallsTo(s, kVA_Extract2)) {
        Log("[terrainhd] unexpected bytes at texture cut %X -> HD terrain NOT installed\n", s);
        return;
    }
    for (uint32_t s : kGenSites) if (!CallsTo(s, kVA_GenTerrainPoly)) {
        Log("[terrainhd] unexpected bytes at terrain pass call %X -> HD terrain NOT installed\n", s);
        return;
    }
    for (const Entry8& f : kEntries)
        if (memcmp(At(f.va), f.b, sizeof f.b) != 0) {
            Log("[terrainhd] unexpected bytes at engine function %X -> HD terrain NOT installed\n",
                static_cast<unsigned>(f.va));
            return;
        }
    {
        uint8_t orig[100][6], patch[100][6];
        static uint8_t probe[kStubArea];
        for (int i = 0; i < 100; ++i) memcpy(orig[i], At(kSpanSites[i]), 6);
        if (!BuildSpanStubs(probe, 0x20000000, 0x20100000, orig, patch)) {
            Log("[terrainhd] unexpected bytes at a span store -> HD terrain NOT installed\n");
            return;
        }
    }

    // usable art decides it: prove the pack against TEXTURE.PCX's palette, then let its bytes go
    char stock[MAX_PATH];
    _snprintf_s(stock, sizeof stock, _TRUNCATE, "%stexture.pcx", g_dir);
    if (!hdpack::ReadPalette(stock, g_pal)) {
        Log("[terrainhd] no palette in texture.pcx -> HD terrain NOT installed\n");
        return;
    }
    {
        hdpack::Pack pack = {};
        if (!LoadPack(&pack)) return;
        hdpack::Free(&pack);
    }
    // RAINFALL art (optional): the exe's two colour lists must be the ones the code maps are built with
    {
        bool movs = true;
        for (int i = 0; i < 9; ++i) {
            const BYTE* m = At(kVA_BorderMovs) + 4 * i;          // mov byte ptr [ebp - 0x1C + i], colour
            movs &= m[0] == 0xC6 && m[1] == 0x45 && m[2] == static_cast<BYTE>(0xE4 + i) && m[3] == kBorderColours[i];
        }
        char rain[MAX_PATH];
        _snprintf_s(rain, sizeof rain, _TRUNCATE, "%srainfall.pcx", g_dir);
        g_rainOk = movs && memcmp(At(kVA_CompColours), kCompColours, sizeof kCompColours) == 0 &&
                   hdpack::ReadPalette(rain, g_rainPal);
        char art[MAX_PATH];
        _snprintf_s(art, sizeof art, _TRUNCATE, "%sterrain\\rainfall_x8.pcx", g_dir);
        if (!g_rainOk && GetFileAttributesA(art) != INVALID_FILE_ATTRIBUTES)
            Log("[terrainhd] RAINFALL's colour lists or palette are not the known ones -> rainfall_x8.pcx not used\n");
    }

    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "TerrainHD", kTerrainHdDefault, ini) != 0 ? 1 : 0;
#ifndef TERRAINHD_SELFTEST
    BindEngine();
#endif
    if (!SpanPagesWritable() || !InstallSpanScaling()) {
        Log("[terrainhd] could not patch the span stores -> HD terrain NOT installed\n");
        return;
    }
    for (uint32_t s : kExtractSites) Retarget(s, reinterpret_cast<const void*>(&ExtractRecorder));
    for (uint32_t s : kGenSites) Retarget(s, reinterpret_cast<const void*>(&GenTerrainPolyHook));
    g_installed = true;
    // the level is logged when it is cut (the screen size is not known yet here)
    Log("[terrainhd] installed: terrain\\texture_x8.pcx (22 texture cuts + 8 terrain-pass sites + 100 span stores), "
        "%s\n", g_on ? "on" : "off ([UIMod] TerrainHD=0)");
}

#ifdef TERRAINHD_SELFTEST
// for the emulation test: the stub area and the 6 patch bytes per site, for stubs at stubVa and SpanData at dataVa
bool TerrainHdTestStubs(uint32_t stubVa, uint32_t dataVa, uint8_t* area, uint8_t (*patch)[6])
{
    uint8_t orig[100][6];
    for (int i = 0; i < 100; ++i) memcpy(orig[i], At(kSpanSites[i]), 6);
    return BuildSpanStubs(area, stubVa, dataVa, orig, patch);
}
#endif
