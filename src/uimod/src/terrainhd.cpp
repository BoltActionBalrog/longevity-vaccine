// terrainhd.cpp -- drop-in HD terrain textures (GitHub issue #1: "the ability to drop-in their own custom terrain
// packs", like the custom portrait files). First written by Nidhogg-chew-root (terrain-hd-hook); reworked for the
// review of 2026-11-12.
//
// The pack: <game>\terrain\texture_x8.pcx, TEXTURE.PCX redrawn at 8x (8192 x 6144), 8-bit, in the STOCK file's
// palette and indices -- the rasterizer shades by adding to the index (Texture_draw_2's `add al, ch`), so a pack in
// another palette layout shades into the wrong colours. hdpack::Load proves it (bounded scan, size, the stock
// TEXTURE.PCX palette) and keeps only its RLE stream.
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
//    w*h copy whose row stride is its width. Two more (0x4522CA / 0x4522E5) are composited from RAINFALL.PCX through
//    a local buffer.
//  * Every rasterizer steps rows by the texture's own width, so a 56k x 56k texture draws on the same polygon given
//    UVs that span 56k texels. The terrain pass's UVs come from two .data tables -- 0x685CA8 (32 dwords: quarter-tile
//    quads) and 0x686090 (56: triangles and quads) -- and eight `mov r32, 0x37` (seven in MapWin_gen_terrain_poly,
//    one in DatalinkWin_draw_terraform 0x431180). Law: terrainhd::Uv (measured on Texture_draw_2 itself).
//  * Some draws sample two textures through ONE UV array (the coast pass: a TEXTURE.PCX tile + a RAINFALL
//    composite), so every 56x56 terrain texture is at the level together. The 60x60 texture 0x78DD80 has its own UV
//    square (0x3B) and is left as it is.
//  * PRACX's Alt+T views (faction / elevation / rainfall / rockiness) swap their own 56x56 images (cut from ICONS.PCX
//    into prax.dll) into the call at 0x464215 / 0x464353 and draw them with the same UVs through Texture_draw_2.
//
// Levers, all byte-checked, all-or-nothing, cave-free:
//  * the 21 extract calls -> ExtractRecorder: which Texture is which TEXTURE.PCX rect (or a RAINFALL composite).
//  * the 8 calls of MapWin_gen_terrain_poly 0x4632D0 -> GenTerrainPolyHook: the level is cut (if the textures are
//    stock and the row is on) before any texture is read, on the game thread; and the pass is marked for the next.
//  * Texture_draw_2's entry (6 bytes, checked, moved to a trampoline) -> Draw2Hook: inside a terrain pass at a level,
//    a 56x56 texture is one we did not cut (PRACX's overlays): it is drawn from a k x nearest copy, so it is read
//    inside its bounds and looks exactly like stock.
//  * a level is installed by giving every recorded Texture new bits at 56k x 56k, then rewriting the UV tables and
//    immediates. The bits are allocated the way Texture_extract_2 allocates them (mem_alloc 0x5D4510; the old ones
//    freed with free 0x644EF2, as Texture_close does) and filled directly: no Buffer, so no quiet failure in between.
//    TEXTURE.PCX's textures come from the pack (each 8x cell shrunk to the level by basehd_law::PaletteBoxShrink, used
//    as painted at 8x); the RAINFALL composites, which the pack does not carry, are terrainhd::Nearest of their own
//    stock pixels. Back to stock the same way, texture by texture from the stock copy: a step that cannot fail
//    quietly, so the textures are always all stock or all at the level, and every recorded texture always has bits.
//  * anything that stops a level (the pack unreadable or changed since startup, no address room for the level) is
//    decided once: logged, stock for the session, no further work on later passes; switching the row off and on tries
//    again once.
//
// Native no-op: no usable pack, no Longevity Preferences tab, or any unexpected byte -> nothing patched, no row.
// "HD Terrain" in Longevity Mod Preferences ([UIMod] TerrainHD) switches it live. On, the hook holds the cut
// textures (160 + 2 at 56k x 56k: 32.5 MB at 8x, 8.1 MB at 4x, 2 MB at 2x), the stock pixels to restore (0.5 MB) and
// the overlay copies (at most kForeign); the pack's bytes are read for a cut and freed right after. Off, the stock
// textures are back and nothing is held. The engine's fatal exit on an allocation failure is bounded, not gone: each
// texture's bits are a mem_alloc (at most 448 x 448), as in Texture_extract_2, and the address room for the whole
// level is probed before the first one.

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
constexpr uintptr_t kVA_TexCtor        = 0x619650;   // Texture_ctor: thiscall (Texture*)
constexpr uintptr_t kVA_TexClose       = 0x619690;   // Texture_close: thiscall (Texture*) -- frees its bits
constexpr uintptr_t kVA_Draw2          = 0x6233C0;   // Texture_draw_2: thiscall (Texture*, Buffer*, Vert*, int*, n, Vert*, mode) RET 0x18
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

const uint32_t kExtractSites[] = {
    0x451D0B, 0x451D27, 0x451D50, 0x451D8F, 0x451DB6, 0x451DE0, 0x451E24, 0x451E86, 0x451EBF, 0x451EE9,
    0x451F32, 0x451F76, 0x451FBF, 0x452000, 0x452030, 0x452081, 0x4520E1, 0x452128, 0x452171,   // TEXTURE.PCX
    0x4522CA, 0x4522E5,                                                                         // RAINFALL composites
};
const uint32_t kGenSites[] = { 0x40F35F, 0x468C73, 0x46927C, 0x469308, 0x469E47, 0x47130C, 0x4B6B9C, 0x4BDF5C };
const uint32_t kUvImmediates[] = { 0x46485D, 0x4649BB, 0x464AF8, 0x464FD8, 0x465561, 0x465C81, 0x465D43, 0x4311B2 };
struct UvTable { uint32_t va; int count; };
const UvTable kUvTables[] = { { 0x685CA8, 32 }, { 0x686090, 56 } };
// the stock tables, exactly (a table that differs is not the one this hook knows: not installed)
const int32_t kUvStock0[32] = { 27, 27, 27, 55, 0, 55, 0, 0, 27, 27, 27, 0, 55, 0, 55, 55,
                                27, 27, 55, 27, 55, 55, 27, 55, 27, 27, 0, 27, 0, 0, 27, 0 };
const int32_t kUvStock1[56] = { 27, 28, 0, 55, 0, 1, 27, 27, 0, 0, 54, 0, 28, 27, 55, 1, 55, 53, 28, 29, 55, 55,
                                2, 55, 27, 27, 0, 27, 0, 0, 27, 0, 28, 27, 28, 0, 55, 0, 55, 27, 28, 28, 55, 28,
                                55, 55, 28, 55, 27, 28, 27, 55, 0, 55, 0, 28 };
const int32_t* const kUvStock[2] = { kUvStock0, kUvStock1 };

// The entry bytes of every engine function the hook calls itself (the call sites prove the rest).
struct Entry8 { uintptr_t va; BYTE b[6]; };
const Entry8 kEntries[] = {
    { kVA_Extract2,   { 0x53, 0x55, 0x56, 0x57, 0x8B, 0x7C } },
    { kVA_TexCtor,    { 0x8B, 0xC1, 0x33, 0xC9, 0x89, 0x08 } },
    { kVA_TexClose,   { 0x56, 0x8B, 0xF1, 0x8B, 0x06, 0x85 } },
    { kVA_MemAlloc,   { 0x8B, 0x44, 0x24, 0x04, 0x50, 0xE8 } },
    { kVA_Free,       { 0x56, 0x8B, 0x74, 0x24, 0x08, 0x85 } },
    { kVA_GenTerrainPoly, { 0x55, 0x8B, 0xEC, 0x6A, 0xFF, 0x68 } },
};
// Texture_draw_2's first three instructions (push ebp; mov ebp, esp; sub esp, 0x78): moved to the trampoline as is
const BYTE kDraw2Entry[] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x78 };

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
constexpr int kForeign = 32;                           // overlay copies kept (PRACX uses 18)
constexpr size_t kStockBytes = static_cast<size_t>(kTex) * kTex;

struct Texture { uint8_t* data; int w; int h; };

struct Entry {
    Texture* tex;
    int x, y;                                          // its rect in TEXTURE.PCX (sheet)
    bool sheet;                                        // cut from TEXTURE.PCX (else a RAINFALL composite)
};

struct Foreign {
    const Texture* src;                                // the overlay texture it stands in for
    const uint8_t* bits;                               // ... with these stock bits (a reload makes a new copy)
    int k;                                             // ... at this level
    unsigned used;
    alignas(16) uint8_t tex[kTexSize];                 // our Texture (cut by Texture_extract_2)
};

typedef int (__thiscall* FDraw2)(void*, void*, void*, void*, int, void*, int);

// The engine functions the module calls (bound from the exe at install; a fake engine under TERRAINHD_SELFTEST).
struct Engine {
    int (__thiscall* extract)(void*, void*, int, int, int, int, void*);
    int (__cdecl* gen)(void*, void*, int, int, int, int, int, int, int, int);
    FDraw2 draw2;                                      // the trampoline (Texture_draw_2's moved entry + a jmp back)
    void (__thiscall* texCtor)(void*);
    void (__thiscall* texClose)(void*);
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
Foreign g_foreign[kForeign];
unsigned g_clock = 0;
int g_level = 1;                                       // installed level; 1 = stock
bool g_dirty = false;                                  // load_terrain cut stock textures since the last install
bool g_failed = false;                                 // a level could not be made: stock until the row is switched
bool g_inPass = false;                                 // inside a MapWin_gen_terrain_poly call
bool g_installed = false;
int g_on = kTerrainHdDefault;
uint8_t g_pal[768];                                    // TEXTURE.PCX's palette (the pack must match it)
BYTE* g_tramp = nullptr;                               // Texture_draw_2's trampoline
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

void WriteUv(int k)
{
    for (int t = 0; t < 2; ++t) {
        int32_t* p = reinterpret_cast<int32_t*>(At(kUvTables[t].va));
        DWORD old;
        VirtualProtect(p, kUvTables[t].count * 4, PAGE_READWRITE, &old);
        for (int i = 0; i < kUvTables[t].count; ++i) p[i] = terrainhd::Uv(kUvStock[t][i], k);
        VirtualProtect(p, kUvTables[t].count * 4, old, &old);
    }
    const uint32_t imm = static_cast<uint32_t>(terrainhd::Uv(55, k));
    for (uint32_t site : kUvImmediates) {
        BYTE* p = At(site);
        DWORD old;
        VirtualProtect(p + 1, 4, PAGE_EXECUTE_READWRITE, &old);
        memcpy(p + 1, &imm, 4);
        VirtualProtect(p + 1, 4, old, &old);
        FlushInstructionCache(GetCurrentProcess(), p, 5);
    }
}

// New engine bits of side x side for t, filled by fill(bits), then the old bits freed: what Texture_extract_2 does
// (mem_alloc, its rows at stride side, the size, the corner coordinates, the heap flag 0), without a Buffer in
// between. mem_alloc does not return null (the engine exits instead), so this cannot fail quietly and t never holds
// a texture without bits.
template <class Fill>
void GiveBits(Texture* t, int side, Fill fill)
{
    uint8_t* bits = static_cast<uint8_t*>(g_eng.alloc(static_cast<size_t>(side) * side));
    fill(bits);
    uint8_t* old = t->data;
    int* heap = reinterpret_cast<int*>(reinterpret_cast<uint8_t*>(t) + kTexHeap);
    const bool ours = *heap == 0;
    t->data = bits;
    t->w = side;
    t->h = side;
    TexCorners(reinterpret_cast<int32_t*>(t), side, side);
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

void FreeForeign()
{
    for (Foreign& f : g_foreign) {
        if (f.src) g_eng.texClose(f.tex);
        f.src = nullptr;
        f.bits = nullptr;
    }
}

// Every recorded texture back to its stock pixels (texture by texture, from the stock copy, while the level's UVs
// still stand), then the UVs back to stock; the stock copy and the overlays freed. Nothing in it can fail quietly
// (GiveBits), so the result is all stock.
void RestoreStock()
{
    if (g_stock)
        for (int i = 0; i < g_count; ++i) {
            const uint8_t* px = g_stock + i * kStockBytes;
            GiveBits(g_entries[i].tex, kTex, [px](uint8_t* b) { memcpy(b, px, kStockBytes); });
        }
    WriteUv(1);
    g_level = 1;
    free(g_stock);
    g_stock = nullptr;
    FreeForeign();
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

// Every recorded texture at level k. The textures are stock when this runs (load_terrain's cut, or restored). False,
// logged once, when the level cannot be made; the textures are then all stock (the caller latches g_failed).
bool InstallLevel(int k)
{
    g_dirty = false;
    if (g_count == 0) return true;
    const DWORD t0 = GetTickCount();
    for (int i = 0; i < g_count; ++i) {
        const Texture* t = g_entries[i].tex;
        if (!t->data || t->w != kTex || t->h != kTex) {
            Log("[terrainhd] texture %d is not a stock 56x56 texture -> stock terrain until the row is switched\n", i);
            return false;
        }
    }
    const int side = kTex * k;
    const size_t level = static_cast<size_t>(g_count) * side * side;
    int x0 = 1 << 30, x1 = 0;                           // the widest band any texture row needs
    for (int i = 0; i < g_count; ++i)
        if (g_entries[i].sheet) {
            if (g_entries[i].x < x0) x0 = g_entries[i].x;
            if (g_entries[i].x + kTex > x1) x1 = g_entries[i].x + kTex;
        }
    const size_t bandMax = x1 > x0 ? static_cast<size_t>(x1 - x0) * terrainhd::kMaster * kCell : 0;
    if (!RoomFor(level + bandMax + g_count * kStockBytes)) {
        Log("[terrainhd] no address room for the %dx level (%u MB) -> stock terrain until the row is switched\n", k,
            static_cast<unsigned>(level >> 20));
        return false;
    }
    hdpack::Pack pack = {};
    if (!LoadPack(&pack)) return false;                  // logged
    g_stock = static_cast<uint8_t*>(malloc(g_count * kStockBytes));
    if (!g_stock) {
        hdpack::Free(&pack);
        Log("[terrainhd] no memory for the stock copy -> stock terrain until the row is switched\n");
        return false;
    }
    for (int i = 0; i < g_count; ++i) memcpy(g_stock + i * kStockBytes, g_entries[i].tex->data, kStockBytes);

    uint8_t map[256];
    for (int i = 0; i < 256; ++i) map[i] = static_cast<uint8_t>(i + 10);    // Buffer_load_pcx(.., 10, 236)
    uint8_t rgbq[1024];
    LoadedColours(rgbq);

    // one band of the sheet at a time (the rows of every texture cut from it), so each scanline is walked once
    bool ok = true;
    int fromPack = 0;
    bool done[kMaxEntries] = {};
    uint8_t* band = nullptr;
    for (int i = 0; i < g_count && ok; ++i) {
        if (done[i]) continue;
        const Entry& e = g_entries[i];
        if (!e.sheet) {                                  // a RAINFALL composite: its own stock pixels at level k
            const uint8_t* px = g_stock + i * kStockBytes;
            GiveBits(e.tex, side, [px, k](uint8_t* b) { terrainhd::Nearest(px, kTex, k, b); });
            done[i] = true;
            continue;
        }
        int bx0 = e.x, bx1 = e.x + kTex;
        for (int j = i + 1; j < g_count; ++j)
            if (!done[j] && g_entries[j].sheet && g_entries[j].y == e.y) {
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
            const Entry& f = g_entries[j];
            if (done[j] || !f.sheet || f.y != e.y) continue;
            const uint8_t* cell = band + (f.x - bx0) * terrainhd::kMaster;
            GiveBits(f.tex, side, [&](uint8_t* b) {
                if (side == kCell)                       // 8x: the cell as painted
                    for (int y = 0; y < kCell; ++y) memcpy(b + y * kCell, cell + static_cast<size_t>(y) * bw, kCell);
                else
                    basehd_law::PaletteBoxShrink(cell, kCell, kCell, bw, b, side, side, side, rgbq);
            });
            ++fromPack;
            done[j] = true;
        }
    }
    free(band);
    hdpack::Free(&pack);
    if (!ok) {
        RestoreStock();                                  // the textures cut so far go back: all stock
        return false;
    }
    WriteUv(k);
    g_level = k;
    unsigned privMb = 0, peakMb = 0;
#ifndef TERRAINHD_SELFTEST
    PROCESS_MEMORY_COUNTERS_EX pmc = {};
    pmc.cb = sizeof pmc;
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc), sizeof pmc)) {
        privMb = static_cast<unsigned>(pmc.PrivateUsage >> 20);
        peakMb = static_cast<unsigned>(pmc.PeakPagefileUsage >> 20);
    }
#endif
    Log("[terrainhd] %d textures at %dx (%d from texture_x8.pcx, %u MB) in %lu ms; process %u MB private, peak %u MB\n",
        g_count, k, fromPack, static_cast<unsigned>(level >> 20), GetTickCount() - t0, privMb, peakMb);
    return true;
}

int WantLevel()
{
    return terrainhd::Level(*reinterpret_cast<int*>(At(kVA_ScreenW)), *reinterpret_cast<int*>(At(kVA_ScreenH)));
}

// A level copy of an overlay texture the pack does not know (PRACX's Alt+T images): its stock pixels at level k
// (terrainhd::Nearest) in engine bits (GiveBits), so it is always made. The least recently used slot is reused.
const void* ForeignFor(const Texture* t)
{
    Foreign* slot = nullptr;
    for (Foreign& f : g_foreign) {
        if (f.src == t && f.bits == t->data && f.k == g_level) { f.used = ++g_clock; return f.tex; }
        if (!slot || (slot->src && (!f.src || f.used < slot->used))) slot = &f;
    }
    if (!slot->src) {
        memset(slot->tex, 0, sizeof slot->tex);
        g_eng.texCtor(slot->tex);
    }
    const int k = g_level;
    const uint8_t* px = t->data;
    GiveBits(reinterpret_cast<Texture*>(slot->tex), kTex * k, [px, k](uint8_t* b) { terrainhd::Nearest(px, kTex, k, b); });
    slot->src = t;
    slot->bits = t->data;
    slot->k = k;
    slot->used = ++g_clock;
    return slot->tex;
}

// --- hooks ------------------------------------------------------------------------------------------------------

// Stands in for Texture_extract_2 at load_terrain's 21 sites: same contract (thiscall, RET 0x18).
int __fastcall ExtractRecorder(Texture* tex, void* /*edx*/, void* src, int x, int y, int w, int h, void* heap)
{
    const int rc = g_eng.extract(tex, src, x, y, w, h, heap);
    if (rc != 0 || w != kTex || h != kTex || !tex->data) return rc;
    if (g_level != 1) {                                  // a new load_terrain: the textures are cut at stock again
        WriteUv(1);
        g_level = 1;
        free(g_stock);
        g_stock = nullptr;
    }
    int i = 0;
    while (i < g_count && g_entries[i].tex != tex) ++i;
    if (i == g_count) {
        if (g_count == kMaxEntries) return rc;
        g_entries[g_count++].tex = tex;
    }
    g_entries[i].x = x;
    g_entries[i].y = y;
    g_entries[i].sheet = src == At(kVA_LoadingCanvas);
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
    const bool outer = !g_inPass;
    g_inPass = true;
    const int r = g_eng.gen(buf, win, zoom, a4, a5, a6, a7, a8, a9, a10);
    if (outer) g_inPass = false;
    return r;
}

// Texture_draw_2's entry: inside a terrain pass at a level, every texture we cut is 56k wide, so a 56x56 one is an
// overlay the engine's UVs would read past -- drawn from its level copy instead (always made: ForeignFor).
void __fastcall Draw2Hook(Texture* tex, void* /*edx*/, void* dst, void* pts, void* light, int n, void* uvs, int mode)
{
    if (g_inPass && g_level != 1 && tex && tex->w == kTex && tex->h == kTex && tex->data) {
        g_eng.draw2(const_cast<void*>(ForeignFor(tex)), dst, pts, light, n, uvs, mode);
        return;
    }
    g_eng.draw2(tex, dst, pts, light, n, uvs, mode);
}

void RepaintTerrainScreens()
{
    g_eng.drawMap(1);
    g_eng.statusRedraw(At(kVA_StatusWin));
    if (*reinterpret_cast<int*>(At(kVA_BaseWin + 0x9C)) & 1) g_eng.graphicRedraw(At(kVA_BaseWin));
}

// Texture_draw_2's first 6 bytes -> a trampoline (those bytes, then jmp 0x6233C6); the entry -> jmp Draw2Hook.
bool DetourDraw2()
{
#ifdef TERRAINHD_SELFTEST
    return true;
#else
    BYTE* e = At(kVA_Draw2);
    g_tramp = static_cast<BYTE*>(VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!g_tramp) return false;
    memcpy(g_tramp, e, sizeof kDraw2Entry);
    g_tramp[sizeof kDraw2Entry] = 0xE9;
    const int32_t back = static_cast<int32_t>(reinterpret_cast<uintptr_t>(e + sizeof kDraw2Entry) -
                                              reinterpret_cast<uintptr_t>(g_tramp + sizeof kDraw2Entry + 5));
    memcpy(g_tramp + sizeof kDraw2Entry + 1, &back, 4);
    FlushInstructionCache(GetCurrentProcess(), g_tramp, 32);
    g_eng.draw2 = reinterpret_cast<FDraw2>(g_tramp);
    DWORD old;
    VirtualProtect(e, sizeof kDraw2Entry, PAGE_EXECUTE_READWRITE, &old);
    e[0] = 0xE9;
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&Draw2Hook) - reinterpret_cast<uintptr_t>(e + 5));
    memcpy(e + 1, &rel, 4);
    e[5] = 0x90;
    VirtualProtect(e, sizeof kDraw2Entry, old, &old);
    FlushInstructionCache(GetCurrentProcess(), e, sizeof kDraw2Entry);
    return true;
#endif
}

void BindEngine()
{
    g_eng.extract = reinterpret_cast<decltype(g_eng.extract)>(At(kVA_Extract2));
    g_eng.gen = reinterpret_cast<decltype(g_eng.gen)>(At(kVA_GenTerrainPoly));
    g_eng.texCtor = reinterpret_cast<decltype(g_eng.texCtor)>(At(kVA_TexCtor));
    g_eng.texClose = reinterpret_cast<decltype(g_eng.texClose)>(At(kVA_TexClose));
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
        RestoreStock();                                  // off holds nothing (overlay copies included, at any level)
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
    for (uint32_t s : kUvImmediates) {
        const BYTE* p = At(s);
        uint32_t imm;
        memcpy(&imm, p + 1, 4);
        if ((p[0] != 0xB8 && p[0] != 0xB9) || imm != 0x37) {
            Log("[terrainhd] unexpected bytes at UV immediate %X -> HD terrain NOT installed\n", s);
            return;
        }
    }
    for (int t = 0; t < 2; ++t)
        if (memcmp(At(kUvTables[t].va), kUvStock[t], kUvTables[t].count * 4) != 0) {
            Log("[terrainhd] UV table %X is not the stock one -> HD terrain NOT installed\n", kUvTables[t].va);
            return;
        }
    for (const Entry8& f : kEntries)
        if (memcmp(At(f.va), f.b, sizeof f.b) != 0) {
            Log("[terrainhd] unexpected bytes at engine function %X -> HD terrain NOT installed\n",
                static_cast<unsigned>(f.va));
            return;
        }
    if (memcmp(At(kVA_Draw2), kDraw2Entry, sizeof kDraw2Entry) != 0) {
        Log("[terrainhd] unexpected bytes at Texture_draw_2's entry -> HD terrain NOT installed\n");
        return;
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

    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "TerrainHD", kTerrainHdDefault, ini) != 0 ? 1 : 0;
#ifndef TERRAINHD_SELFTEST
    BindEngine();
#endif
    if (!DetourDraw2()) {
        Log("[terrainhd] could not detour Texture_draw_2 -> HD terrain NOT installed\n");
        return;
    }
    for (uint32_t s : kExtractSites) Retarget(s, reinterpret_cast<const void*>(&ExtractRecorder));
    for (uint32_t s : kGenSites) Retarget(s, reinterpret_cast<const void*>(&GenTerrainPolyHook));
    g_installed = true;
    // the level is logged when it is cut (the screen size is not known yet here)
    Log("[terrainhd] installed: terrain\\texture_x8.pcx (21 texture cuts + 8 terrain-pass sites + Texture_draw_2's "
        "entry), %s\n", g_on ? "on" : "off ([UIMod] TerrainHD=0)");
}
