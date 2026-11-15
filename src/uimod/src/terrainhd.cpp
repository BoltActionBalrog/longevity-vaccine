// terrainhd.cpp -- drop-in HD terrain textures (GitHub issue #1: "the ability to drop-in their own custom terrain
// packs", like the custom portrait files). First written by Nidhogg-chew-root (terrain-hd-hook); reworked for the
// review of 2026-11-12.
//
// The pack: <game>\terrain\texture_x8.pcx, TEXTURE.PCX redrawn at 8x (8192 x 6144), 8-bit, in the STOCK file's
// palette and indices -- the rasterizer shades by adding to the index (Texture_draw_2's `add al, ch`), so a pack in
// another palette layout shades into the wrong colours. hdpack::Load proves it (bounded scan, size, the stock
// TEXTURE.PCX palette) and keeps only its RLE stream.
//
// One level for the session (terrainhd::Level): the smallest of 2x / 4x that keeps a texel per pixel at the screen's
// deepest PRACX zoom (4x from 1920 x 1080 up). Every terrain texture is cut at that level, so the main map at any
// zoom, the base screen, the HUD tile view and the Datalinks page all sample the same art; nothing changes level as
// the map zooms.
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
//  * a level is installed by re-cutting every recorded Texture through the engine's own Texture_extract_2 from the
//    scratch Buffer, then rewriting the UV tables and immediates. TEXTURE.PCX's textures come from the pack (each
//    8x cell shrunk to the level by basehd_law::PaletteBoxShrink); the RAINFALL composites, which the pack does not
//    carry, are terrainhd::Nearest of their own stock pixels. A failed cut puts every texture back to stock and
//    keeps the hook stock for the session.
//
// Native no-op: no usable pack, no Longevity Preferences tab, or any unexpected byte -> nothing patched, no row.
// "HD Terrain" in Longevity Mod Preferences ([UIMod] TerrainHD) switches it live. On, the hook holds the cut
// textures (160 + 2 at 56k x 56k: 8 MB at 4x, 2 MB at 2x), the stock pixels to restore (0.5 MB) and the overlay
// copies (at most kForeign); the pack's bytes are read for a cut and freed right after. Off, the stock textures are
// back and nothing is held. The engine's fatal exit on an allocation failure is bounded, not gone: the scratch
// Buffer (Buffer_init: only a failed CreateDIBSection exits; its address room is probed first) and each cut Texture
// (Texture_extract_2's allocation, at most 224 x 224) are engine allocations.

#include "terrainhd.h"
#include "terrainhd_law.h"
#include "basehd_law.h"
#include "hdpack.h"

#include <windows.h>
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
constexpr uintptr_t kVA_BufferCtor     = 0x5D7210;   // Buffer_ctor: thiscall (Buffer*)
constexpr uintptr_t kVA_BufferInit     = 0x5D7670;   // Buffer_init: thiscall (Buffer*, w, h, flags, surf) RET 0x10
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
    { kVA_BufferCtor, { 0x6A, 0xFF, 0x68, 0x5E, 0x2B, 0x66 } },
    { kVA_BufferInit, { 0x83, 0xEC, 0x74, 0x8B, 0x84, 0x24 } },
    { kVA_GenTerrainPoly, { 0x55, 0x8B, 0xEC, 0x6A, 0xFF, 0x68 } },
};
// Texture_draw_2's first three instructions (push ebp; mov ebp, esp; sub esp, 0x78): moved to the trampoline as is
const BYTE kDraw2Entry[] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x78 };

// Buffer fields (Thinker engine_win.h; Buffer is 0x588 bytes); Texture: bits, width, height (of 0x70 bytes)
constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufPitch = 0x4A8, kBufSize = 0x588;
constexpr int kTexSize = 0x70;
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
    void (__thiscall* bufferCtor)(void*);
    int (__thiscall* bufferInit)(void*, int, int, int, void*);
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
bool g_failed = false;                                 // a cut failed: stock for the rest of the session
bool g_inPass = false;                                 // inside a MapWin_gen_terrain_poly call
bool g_installed = false;
int g_on = kTerrainHdDefault;
uint8_t g_pal[768];                                    // TEXTURE.PCX's palette (the pack must match it)
alignas(16) uint8_t g_scratch[kBufSize + 0x80];        // the one scratch Buffer every cut goes through
bool g_scratchReady = false;
int g_scratchW = 0, g_scratchH = 0;
BYTE* g_tramp = nullptr;                               // Texture_draw_2's trampoline
char g_dir[MAX_PATH];

#ifdef TERRAINHD_SELFTEST
BYTE* g_testImage = nullptr;                           // the fake exe image (0x400000-based)
char g_testDir[MAX_PATH];
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

uint8_t* Pixels(void* buf)
{
    uint8_t* d = *reinterpret_cast<uint8_t**>(static_cast<uint8_t*>(buf) + kBufData);
    return d ? d : *reinterpret_cast<uint8_t**>(static_cast<uint8_t*>(buf) + kBufBits);
}

int Field(void* buf, int off) { return *reinterpret_cast<int*>(static_cast<uint8_t*>(buf) + off); }

// The scratch Buffer at exactly side x side holding px (row stride side). Its address room is probed first, because a
// failed CreateDIBSection in Buffer_init is the engine's fatal exit; its other failure (CreateCompatibleDC, after it
// closed the Buffer) records no size, so the next cut tries again.
bool FillScratch(const uint8_t* px, int side)
{
    if (!g_scratchReady || !Pixels(g_scratch) || side != g_scratchW || side != g_scratchH) {
        void* probe = VirtualAlloc(nullptr, static_cast<size_t>((side + 3) & ~3) * side * 2 + (1 << 20), MEM_RESERVE,
                                   PAGE_READWRITE);
        if (!probe) return false;
        VirtualFree(probe, 0, MEM_RELEASE);
        if (!g_scratchReady) {
            g_eng.bufferCtor(g_scratch);
            g_scratchReady = true;
        }
        g_eng.bufferInit(g_scratch, side, side, 0, nullptr);
        g_scratchW = g_scratchH = side;
    }
    uint8_t* d = Pixels(g_scratch);
    const int pitch = Field(g_scratch, kBufPitch);
    if (!d || Field(g_scratch, kBufW) != side || pitch < side) {
        g_scratchW = g_scratchH = 0;
        return false;
    }
    for (int y = 0; y < side; ++y) memcpy(d + static_cast<size_t>(y) * pitch, px + static_cast<size_t>(y) * side, side);
    return true;
}

void ShrinkScratch()
{
    if (g_scratchReady && (g_scratchW > 4 || g_scratchH > 4)) {
        g_eng.bufferInit(g_scratch, 4, 4, 0, nullptr);   // closes the old surface first
        g_scratchW = g_scratchH = Pixels(g_scratch) ? 4 : 0;
    }
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

// Every recorded texture back to its stock pixels, the UVs back to stock; the stock copy and the overlays freed.
// False when a cut failed (that texture is left without bits by Texture_extract_2; the terrain pass then skips it).
bool RestoreStock()
{
    bool ok = true;
    if (g_stock) {
        for (int i = 0; i < g_count; ++i) {
            const uint8_t* px = g_stock + i * kStockBytes;
            if (!FillScratch(px, kTex) || g_eng.extract(g_entries[i].tex, g_scratch, 0, 0, kTex, kTex, nullptr) != 0)
                ok = false;
        }
    }
    WriteUv(1);
    g_level = 1;
    free(g_stock);
    g_stock = nullptr;
    FreeForeign();
    ShrinkScratch();
    return ok;
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

// Cut every recorded texture at level k. The textures are stock when this runs (load_terrain's cut, or restored).
void InstallLevel(int k)
{
    g_dirty = false;
    if (g_count == 0) return;
    const DWORD t0 = GetTickCount();
    for (int i = 0; i < g_count; ++i) {
        const Texture* t = g_entries[i].tex;
        if (!t->data || t->w != kTex || t->h != kTex) {
            Log("[terrainhd] texture %d is not a stock 56x56 texture -> stock terrain\n", i);
            return;
        }
    }
    g_stock = static_cast<uint8_t*>(malloc(g_count * kStockBytes));
    hdpack::Pack pack = {};
    const int side = kTex * k;
    uint8_t* hd = static_cast<uint8_t*>(malloc(static_cast<size_t>(side) * side));
    if (!g_stock || !hd || !LoadPack(&pack)) {
        if (!g_stock || !hd) Log("[terrainhd] no memory for the %dx level -> stock terrain\n", k);
        free(g_stock);
        g_stock = nullptr;
        free(hd);
        hdpack::Free(&pack);
        return;
    }
    for (int i = 0; i < g_count; ++i) memcpy(g_stock + i * kStockBytes, g_entries[i].tex->data, kStockBytes);

    uint8_t map[256];
    for (int i = 0; i < 256; ++i) map[i] = static_cast<uint8_t>(i + 10);    // Buffer_load_pcx(.., 10, 236)
    uint8_t rgbq[1024];
    LoadedColours(rgbq);

    // one band of the sheet at a time (the rows of every texture cut from it), so each scanline is walked once
    bool ok = true;
    bool done[kMaxEntries] = {};
    uint8_t* band = nullptr;
    for (int i = 0; i < g_count && ok; ++i) {
        if (done[i]) continue;
        const Entry& e = g_entries[i];
        if (!e.sheet) {                                  // a RAINFALL composite: its own stock pixels at level k
            terrainhd::Nearest(g_stock + i * kStockBytes, kTex, k, hd);
            ok = FillScratch(hd, side) && g_eng.extract(e.tex, g_scratch, 0, 0, side, side, nullptr) == 0;
            done[i] = true;
            continue;
        }
        int x0 = e.x, x1 = e.x + kTex;
        for (int j = i + 1; j < g_count; ++j)
            if (!done[j] && g_entries[j].sheet && g_entries[j].y == e.y) {
                if (g_entries[j].x < x0) x0 = g_entries[j].x;
                if (g_entries[j].x + kTex > x1) x1 = g_entries[j].x + kTex;
            }
        const int bw = (x1 - x0) * terrainhd::kMaster;
        free(band);
        band = static_cast<uint8_t*>(malloc(static_cast<size_t>(bw) * kCell));
        if (!band || !hdpack::Expand(pack, x0 * terrainhd::kMaster, e.y * terrainhd::kMaster, bw, kCell, map, band)) {
            Log("[terrainhd] could not read the band at row %d of texture_x8.pcx\n", e.y);
            ok = false;
            break;
        }
        for (int j = i; j < g_count && ok; ++j) {
            const Entry& f = g_entries[j];
            if (done[j] || !f.sheet || f.y != e.y) continue;
            basehd_law::PaletteBoxShrink(band + (f.x - x0) * terrainhd::kMaster, kCell, kCell, bw, hd, side, side, side,
                                         rgbq);
            ok = FillScratch(hd, side) && g_eng.extract(f.tex, g_scratch, 0, 0, side, side, nullptr) == 0;
            done[j] = true;
        }
    }
    free(band);
    free(hd);
    hdpack::Free(&pack);
    if (!ok) {
        const bool back = RestoreStock();
        g_failed = true;
        Log(back ? "[terrainhd] a %dx cut failed: stock textures restored, HD terrain off for this session\n"
                 : "[terrainhd] a %dx cut failed and a stock texture could not be restored; HD terrain off\n", k);
        return;
    }
    ShrinkScratch();
    WriteUv(k);
    g_level = k;
    Log("[terrainhd] %d textures at %dx (%d from texture_x8.pcx) in %lu ms\n", g_count, k, g_count - 2,
        GetTickCount() - t0);
}

int WantLevel()
{
    return terrainhd::Level(*reinterpret_cast<int*>(At(kVA_ScreenW)), *reinterpret_cast<int*>(At(kVA_ScreenH)));
}

// A level copy of an overlay texture the pack does not know (PRACX's Alt+T images), or null.
const void* ForeignFor(const Texture* t)
{
    Foreign* slot = nullptr;
    for (Foreign& f : g_foreign) {
        if (f.src == t && f.bits == t->data && f.k == g_level) { f.used = ++g_clock; return f.tex; }
        if (!slot || (slot->src && (!f.src || f.used < slot->used))) slot = &f;
    }
    const int side = kTex * g_level;
    uint8_t* hd = static_cast<uint8_t*>(malloc(static_cast<size_t>(side) * side));
    if (!hd) return nullptr;
    terrainhd::Nearest(t->data, kTex, g_level, hd);
    if (slot->src) g_eng.texClose(slot->tex);
    else {
        memset(slot->tex, 0, sizeof slot->tex);
        g_eng.texCtor(slot->tex);
    }
    slot->src = nullptr;
    const bool ok = FillScratch(hd, side) && g_eng.extract(slot->tex, g_scratch, 0, 0, side, side, nullptr) == 0;
    free(hd);
    if (!ok) return nullptr;
    slot->src = t;
    slot->bits = t->data;
    slot->k = g_level;
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
            if (g_level != 1 && !RestoreStock()) g_failed = true;
            if (!g_failed) InstallLevel(want);
        }
    }
    const bool outer = !g_inPass;
    g_inPass = true;
    const int r = g_eng.gen(buf, win, zoom, a4, a5, a6, a7, a8, a9, a10);
    if (outer) g_inPass = false;
    return r;
}

// Texture_draw_2's entry: inside a terrain pass at a level, every texture we cut is 56k wide, so a 56x56 one is an
// overlay the engine's UVs would read past -- drawn from its level copy instead (or not at all if none can be made).
void __fastcall Draw2Hook(Texture* tex, void* /*edx*/, void* dst, void* pts, void* light, int n, void* uvs, int mode)
{
    if (g_inPass && g_level != 1 && tex && tex->w == kTex && tex->h == kTex && tex->data) {
        const void* copy = ForeignFor(tex);
        if (!copy) return;
        g_eng.draw2(const_cast<void*>(copy), dst, pts, light, n, uvs, mode);
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
    g_eng.bufferCtor = reinterpret_cast<decltype(g_eng.bufferCtor)>(At(kVA_BufferCtor));
    g_eng.bufferInit = reinterpret_cast<decltype(g_eng.bufferInit)>(At(kVA_BufferInit));
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
        g_failed = false;                                // tried again; the next terrain pass cuts the level
        g_dirty = g_count != 0;
    } else if (g_level != 1) {
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
    Log("[terrainhd] installed: terrain\\texture_x8.pcx at %dx for %dx%d (21 texture cuts + 8 terrain-pass sites + "
        "Texture_draw_2's entry), %s\n", WantLevel(), *reinterpret_cast<int*>(At(kVA_ScreenW)),
        *reinterpret_cast<int*>(At(kVA_ScreenH)), g_on ? "on" : "off ([UIMod] TerrainHD=0)");
}
