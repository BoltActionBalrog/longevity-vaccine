// objecthd.cpp -- drop-in HD map objects: the monolith, pods, resource specials, terraforming (mines, solar, condensers,
// boreholes, farms, ...), landmarks -- everything load_terrain cuts out of TER1.PCX -- and the Unity wreck / canyon
// pieces it cuts out of TER1WRECK.PCX, on every screen that draws them.
//
// A pack is <game>\terrain\ter1_x8.pcx and/or ter1wreck_x8.pcx: the sheet redrawn at 8x (8192x6144), 8-bit, in the
// STOCK file's palette indices and with its palette (background 253 and the tile slab 252 stay see-through, as in the
// stock file). Either sheet may be absent, and any cell of a sheet may be left blank.
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike; symbols in work/symbols/terranx.h):
//  * load_terrain 0x451C50 loads TER1.PCX into the loading canvas 0x798668 with Buffer_load_pcx(name, 0, 10, 236)
//    (loaded index = file index + 10 mod 256: 252 -> 6, 253 -> 7, 255 -> 9) and cuts 71 sprites of 100x62 with 36
//    Sprite_extract_2 0x5E39A0 calls (0x452C07..0x4536A8, key 0x109), each after Buffer_change_color 0x5DE580
//    (0x107 -> 0x109, 0x106 -> 0x109): the background and the slab become the key. TER1WRECK.PCX is loaded and
//    recoloured the same way; its 25 sprites are 25 single Sprite_extract_2 calls (0x4524A8..0x452B8C), 100x62.
//    The sprites live at fixed addresses and fixed rects -- objecthd_table.h, read off those calls and their loops.
//  * Every draw of those sprites (a census of every reference to them in the exe, pinned by
//    work/tests/test_objecthd_sites.py): MapWin_gen_terrain_poly 0x4632D0 -- 18 Sprite_blit_scaled_core 0x5E4B9A and
//    3 Sprite_draw_dest 0x5E5833 calls, scaled by SCALE_NUM_G / SCALE_DEN_G (0x696D18 / 0x696D1C); it is also the
//    terrain pass of the base screen's resource view, the HUD tile pane and the tutorial terrain view. The Datalinks
//    terraforming page DatalinkWin_draw_terraform 0x431180 -- 13 Sprite_draw_2 0x5E4B4A calls (num / den on the
//    stack). The tutorial and hint popups (action_terraform, Console_give_hints -> TutWin_tut_map -> tut_win) hand
//    TER1 sprites to the popup: as its picture, drawn by BasePop_on_redraw's Sprite_draw_2 @0x604C72 (on the
//    patched exe the mod's thunk_art_draw, the same contract), or as a SpriteBox item, drawn @0x610E7B. Each engine
//    draw scales by a truncated size and nearest-neighbour SKIPPING, so an 8x sprite must never be shrunk by it; each
//    takes an unscaled branch when num == den.
//
// So, as basehd.cpp, and by the same laws (basehd_law.h, scaling_laws.py): each object is made from its 8x cell at the
// size the engine gives the stock cell (CellSize) with PaletteBoxShrink, cut through the engine's own Sprite_extract_2
// with the stock key, and drawn with num == den, top-left at the same (x, y); the drawn object is usually within a
// pixel of the stock one. Above 8x the same law enlarges the cell. A draw of a sprite this module does not own, or
// of one the pack does not supply, is the original call with the original arguments.
//
// Art that is not provided, or cannot be used, is drawn exactly as the game draws it without this module, decided once:
//  * per sheet: the pack file is proven at Init (hdpack::Load: bounded scan of the whole file, the stock sheet's
//    palette); a file that fails is logged once and its sheet stays stock;
//  * per object: a cell that is all background / slab is stock for good (found at Init, one debug line);
//  * per object and size: a cut that fails (an empty rect, no memory) is remembered and never retried.
// Nothing is allocated through the engine except the one scratch Buffer the cut goes through (grow-only, at most
// kMaxCut x the cell, its address room probed first); everything else is plain memory and its failure is stock.
//
// Memory budget: each usable sheet is its file bytes (~3.5 MB) for the session -- read and scanned once; an object at
// a new size expands only its own cell's scanlines. Cut objects cost about w x h bytes each and are kept for every
// size drawn (kSizes per object), up to kBudget in all, least recently drawn first out. Switching the row off keeps
// them, so switching it on again costs nothing.
//
// Levers: the 21 draw calls in MapWin_gen_terrain_poly, the 13 in DatalinkWin_draw_terraform and the two popup draws,
// byte-checked E8 retargets, cave-free. The extract calls are left alone: the table is static.
// Installed only where the Longevity Preferences tab is and only when a sheet on disk is usable and has art: otherwise
// nothing is patched and no row is built. "HD Map Objects" ([UIMod] ObjectHD) switches it live.

#include "objecthd.h"
#include "basehd_law.h"
#include "hdpack.h"
#include "objecthd_table.h"

#include <windows.h>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

void UimodLog(const char* msg);
void UimodDbg(const char* msg);
bool PrefsTabInstalled();
bool UimodPcave2Range(uintptr_t* lo, uintptr_t* hi);

namespace {

// work/symbols/terranx.h
constexpr uintptr_t kVA_Extract2     = 0x5E39A0;   // Sprite_extract_2: thiscall (Sprite*, Buffer* src, key, x, y, w, h, a8) RET 0x1C
constexpr uintptr_t kVA_Draw2        = 0x5E4B4A;   // Sprite_draw_2: thiscall (Sprite*, Buffer* dst, key, x, y, num, den) RET 0x18
constexpr uintptr_t kVA_BlitCore     = 0x5E4B9A;   // Sprite_blit_scaled_core: thiscall (Sprite*, Buffer* dst, key, x, y) RET 0x10
constexpr uintptr_t kVA_DrawDest     = 0x5E5833;   // Sprite_draw_dest: thiscall (Sprite*, Buffer* dst, key, x, y, table) RET 0x14
constexpr uintptr_t kVA_SpriteClose  = 0x5E3820;   // Sprite_close: thiscall (Sprite*)
constexpr uintptr_t kVA_BufferCtor   = 0x5D7210;   // Buffer_ctor: thiscall (Buffer*)
constexpr uintptr_t kVA_BufferInit   = 0x5D7670;   // Buffer_init: thiscall (Buffer*, w, h, flags, surf) RET 0x10
constexpr uintptr_t kVA_ScaleNum     = 0x696D18;   // SCALE_NUM_G
constexpr uintptr_t kVA_ScaleDen     = 0x696D1C;   // SCALE_DEN_G
constexpr uintptr_t kVA_MainPalette  = 0x94C590;   // g_main_palette: PALETTEENTRY[256] (fallback colours)
constexpr uintptr_t kVA_DrawMap      = 0x46B190;   // draw_map: cdecl(int) -- full map repaint
constexpr uintptr_t kVA_StatusWinRedraw = 0x4B9EA0; // StatusWin_redraw: thiscall (StatusWin*) -- the HUD panels
constexpr uintptr_t kVA_StatusWin    = 0x8C5568;   // StatusWin_g
constexpr uintptr_t kVA_GraphicWinRedraw = 0x5D5A70; // GraphicWin_redraw: thiscall (GraphicWin*)
constexpr uintptr_t kVA_BaseWin      = 0x6A7628;   // BaseWin_g (+0x9C bit 0: on screen)
constexpr uintptr_t kVA_ArtDraw      = 0xA35EB0;   // thunk_art_draw (pcave2+0x29EB0): Sprite_draw_2's contract
constexpr uintptr_t kTerrainLo = 0x4632D0, kTerrainHi = 0x466CA0;   // MapWin_gen_terrain_poly

// load_terrain's cuts: one byte-checked site per pattern, proof that the table below is this exe's.
constexpr uint32_t kExtractSites[] = {0x452C07, 0x452D97, 0x453087, 0x453508, 0x453656, 0x4536A8, 0x4524A8, 0x452B8C};
// DatalinkWin_draw_terraform's Sprite_draw_2 calls, each on one TER1 sprite (ecx = its address, num / den pushed)
constexpr uint32_t kDatalinkSites[] = {0x431321, 0x431355, 0x43138E, 0x4313C2, 0x4313FB, 0x43142F, 0x4314E7, 0x43151B,
                                       0x43154F, 0x4315E0, 0x431614, 0x431648, 0x4316A2};
constexpr uint32_t kPopupArtSite = 0x604C72;            // BasePop_on_redraw: the popup's picture
constexpr uint32_t kSpriteBoxSite = 0x610E7B;           // a SpriteBox item
constexpr int kBlitCoreCalls = 18, kDrawDestCalls = 3;  // in MapWin_gen_terrain_poly
constexpr int kSheets = 2;
const char* const kSheetName[kSheets] = {"ter1", "ter1wreck"};

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufColors = 0xA4, kBufPitch = 0x4A8, kBufSize = 0x588;
constexpr int kSheetW = 1024, kSheetH = 768, kMaster = 8, kW = 100, kH = 62, kKey = 0x109;
constexpr int kMaxCut = 12;                             // never cut above 12x the stock cell: the scratch stays <= ~1 MB
constexpr int kLoadShift = 10;                          // Buffer_load_pcx(name, 0, 10, 236): loaded = file + 10 mod 256
constexpr int kKeyIndex = 9, kBgIndex = 7, kSlabIndex = 6;   // load_terrain's Buffer_change_color(0x107/0x106 -> 0x109)
constexpr int kSizes = 24;                              // sizes kept per object (PRACX: up to 20 zoom levels + the rest)
constexpr size_t kBudget = size_t(24) << 20;            // all cut objects together (w x h bytes each)

struct Sprite { uint8_t raw[0x2C]; };
struct Slot { int w, h, state; unsigned used; Sprite spr; };   // state 1 = HD sprite, -1 = this size fails: stock
struct Entry { uintptr_t va; int sheet, x, y, blank; Slot slots[kSizes]; };   // blank 1: the cell is all key: stock

constexpr int kMaxEntries = objecthd_table::kRows;
Entry g_entries[kMaxEntries];
int g_count = 0;

// The objects and their cells (objecthd_table.h, pinned against load_terrain's own cuts).
void BuildTable()
{
    objecthd_table::Row rows[objecthd_table::kRows];
    const int n = objecthd_table::Build(rows);
    g_count = 0;
    for (int i = 0; i < n; ++i) g_entries[g_count++] = Entry{rows[i].va, rows[i].sheet, rows[i].x, rows[i].y, -1, {}};
}

typedef int (__thiscall* FExtract2)(void*, void*, int, int, int, int, int, void*);
typedef int (__thiscall* FDraw2)(void*, void*, int, int, int, int, int);
typedef int (__thiscall* FBlitCore)(void*, void*, int, int, int);
typedef int (__thiscall* FDrawDest)(void*, void*, int, int, int, void*);
typedef void (__thiscall* FSpriteClose)(void*);
typedef void (__thiscall* FBufferCtor)(void*);
typedef int (__thiscall* FBufferInit)(void*, int, int, int, void*);

FExtract2 g_extract = nullptr;
FDraw2 g_draw2 = nullptr;                               // the Datalinks / SpriteBox sites' target: Sprite_draw_2
FDraw2 g_popupArt = nullptr;                            // the popup picture site's target (Sprite_draw_2 or the mod's thunk)
FBlitCore g_blitCore = nullptr;
FDrawDest g_drawDest = nullptr;
hdpack::Pack g_pack[kSheets];
int g_state[kSheets] = {};                              // 1 = usable, -1 = none / unusable
uint8_t g_map[256];                                     // file index -> load_terrain's (+10, then background / slab -> key)
alignas(16) uint8_t g_scratch[kBufSize + 0x80];         // the one scratch Buffer every cut goes through (grow-only)
bool g_scratchReady = false;
int g_scratchW = 0, g_scratchH = 0;
uint8_t* g_cell = nullptr;                              // one 8x cell, expanded (800 x 496)
size_t g_bytes = 0;                                     // cut objects held, w x h each
bool g_installed = false;
int g_on = kObjectHdDefault;
unsigned g_clock = 0;
char g_dir[MAX_PATH];

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000); }

void Log(const char* fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(buf, sizeof buf, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(buf);
}

void Dbg(const char* fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(buf, sizeof buf, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodDbg(buf);
}

uintptr_t CallTarget(uint32_t site)
{
    const BYTE* p = At(site);
    if (p[0] != 0xE8) return 0;
    int32_t rel;
    memcpy(&rel, p + 1, 4);
    return reinterpret_cast<uintptr_t>(p) + 5 + rel;
}

bool CallsTo(uint32_t site, uintptr_t target) { return CallTarget(site) == reinterpret_cast<uintptr_t>(At(target)); }

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

uint8_t* Pixels(void* buf)
{
    uint8_t* d = *reinterpret_cast<uint8_t**>(static_cast<uint8_t*>(buf) + kBufData);
    return d ? d : *reinterpret_cast<uint8_t**>(static_cast<uint8_t*>(buf) + kBufBits);
}

int Field(void* buf, int off) { return *reinterpret_cast<int*>(static_cast<uint8_t*>(buf) + off); }

bool HasData(const Sprite& s) { return *reinterpret_cast<void* const*>(s.raw + 4) != nullptr; }

// "terrain\ter1_x8.pcx" (relative to the game folder: how the log names it)
void PackRel(int sheet, char* out, size_t n) { _snprintf_s(out, n, _TRUNCATE, "terrain\\%s_x%d.pcx", kSheetName[sheet], kMaster); }

// --- packs ------------------------------------------------------------------------------------------------------

// Prove a sheet's pack once (the bounded scan, against the stock sheet's palette), then find the cells it leaves
// blank. True when the sheet has at least one object to draw HD.
bool LoadSheet(int sheet)
{
    char rel[64], path[MAX_PATH], stock[MAX_PATH];
    PackRel(sheet, rel, sizeof rel);
    _snprintf_s(path, sizeof path, _TRUNCATE, "%s%s", g_dir, rel);
    g_state[sheet] = -1;
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return false;   // no pack for this sheet: stock, quietly
    uint8_t pal[768];
    _snprintf_s(stock, sizeof stock, _TRUNCATE, "%s%s.pcx", g_dir, kSheetName[sheet]);
    if (!hdpack::ReadPalette(stock, pal)) {
        Log("[objecthd] %s: the stock %s.pcx has no readable palette -> stock objects for it\n", rel, kSheetName[sheet]);
        return false;
    }
    const DWORD t0 = GetTickCount();
    const hdpack::Result r = hdpack::Load(&g_pack[sheet], path, kSheetW * kMaster, kSheetH * kMaster, pal);
    if (r != hdpack::kOk) {
        Log("[objecthd] %s %s (want an 8-bit %dx%d PCX in %s.pcx's palette) -> stock objects for it\n", rel,
            hdpack::Why(r), kSheetW * kMaster, kSheetH * kMaster, kSheetName[sheet]);
        return false;
    }
    if (!g_cell) g_cell = static_cast<uint8_t*>(malloc(static_cast<size_t>(kW) * kMaster * kH * kMaster));
    if (!g_cell) {
        Log("[objecthd] %s could not be loaded (no memory) -> stock objects for it\n", rel);
        hdpack::Free(&g_pack[sheet]);
        return false;
    }
    int art = 0, blank = 0;
    const size_t n = static_cast<size_t>(kW) * kMaster * kH * kMaster;
    for (int i = 0; i < g_count; ++i) {
        Entry& e = g_entries[i];
        if (e.sheet != sheet) continue;
        e.blank = 1;
        if (hdpack::Expand(g_pack[sheet], e.x * kMaster, e.y * kMaster, kW * kMaster, kH * kMaster, g_map, g_cell))
            for (size_t k = 0; k < n && e.blank; ++k) if (g_cell[k] != kKeyIndex) e.blank = 0;
        if (e.blank) { ++blank; Dbg("[objecthd] %s: the cell at (%d,%d) is blank -> that object stays stock\n", rel, e.x, e.y); }
        else ++art;
    }
    if (!art) {
        Log("[objecthd] %s has no art in any object cell -> stock objects for it\n", rel);
        hdpack::Free(&g_pack[sheet]);
        return false;
    }
    g_state[sheet] = 1;
    Dbg("[objecthd] %s proven in %lu ms: %d objects HD, %d blank (%zu bytes kept)\n", rel, GetTickCount() - t0, art,
        blank, g_pack[sheet].size);
    return true;
}

// --- the cache --------------------------------------------------------------------------------------------------

void CloseSlot(Slot& s)
{
    if (s.state == 1) {
        if (HasData(s.spr)) reinterpret_cast<FSpriteClose>(At(kVA_SpriteClose))(&s.spr);
        g_bytes -= static_cast<size_t>(s.w) * s.h;
    }
    s = Slot{};
}

// Over budget: drop the least recently drawn HD objects (never `keep`).
void Trim(const Slot* keep)
{
    while (g_bytes > kBudget) {
        Slot* lru = nullptr;
        for (int i = 0; i < g_count; ++i)
            for (Slot& s : g_entries[i].slots)
                if (s.state == 1 && &s != keep && (!lru || s.used < lru->used)) lru = &s;
        if (!lru) return;
        CloseSlot(*lru);
    }
}

Slot* Find(Entry& e, int w, int h)
{
    for (Slot& s : e.slots) if (s.state != 0 && s.w == w && s.h == h) return &s;
    return nullptr;
}

// The scratch Buffer at least w x h. Grow-only, at most kMaxCut x the cell; the address room for its DIB section is
// probed first, because Buffer_init's own failure is the engine's fatal exit.
bool Scratch(int w, int h)
{
    if (g_scratchReady && w <= g_scratchW && h <= g_scratchH) return true;
    const int nw = w > g_scratchW ? w : g_scratchW, nh = h > g_scratchH ? h : g_scratchH;
    const size_t need = static_cast<size_t>((nw + 3) & ~3) * nh;
    void* probe = VirtualAlloc(nullptr, need * 2 + (1 << 20), MEM_RESERVE, PAGE_READWRITE);
    if (!probe) return false;
    VirtualFree(probe, 0, MEM_RELEASE);
    if (!g_scratchReady) {
        reinterpret_cast<FBufferCtor>(At(kVA_BufferCtor))(g_scratch);
        g_scratchReady = true;
    }
    reinterpret_cast<FBufferInit>(At(kVA_BufferInit))(g_scratch, nw, nh, 0, nullptr);
    if (!Pixels(g_scratch) || Field(g_scratch, kBufW) != nw || Field(g_scratch, kBufPitch) < nw) return false;
    g_scratchW = nw;
    g_scratchH = nh;
    return true;
}

// The colours the art is shown with: the destination's synced table, else the main palette.
void Colours(void* dst, uint8_t rgbq[1024])
{
    const uint8_t* dc = dst ? static_cast<const uint8_t*>(dst) + kBufColors : nullptr;
    bool ok = false;
    if (dc) for (int i = 0; i < 1024 && !ok; ++i) ok = dc[i] != 0;
    if (ok) { memcpy(rgbq, dc, 1024); return; }
    const uint8_t* pe = At(kVA_MainPalette);            // PALETTEENTRY (r,g,b,f) -> RGBQUAD (b,g,r,0)
    for (int i = 0; i < 256; ++i) {
        rgbq[i * 4] = pe[i * 4 + 2]; rgbq[i * 4 + 1] = pe[i * 4 + 1]; rgbq[i * 4 + 2] = pe[i * 4]; rgbq[i * 4 + 3] = 0;
    }
}

// Make e's HD object at w x h. Returns its slot: state 1 (drawn HD) or -1 (this size is stock for good).
Slot* Cut(Entry& e, int w, int h, void* dst)
{
    Slot* s = nullptr;
    for (Slot& it : e.slots) if (it.state == 0) { s = &it; break; }
    if (!s) {                                            // every size slot used: the least recently drawn one goes
        s = &e.slots[0];
        for (Slot& it : e.slots) if (it.used < s->used) s = &it;
        CloseSlot(*s);
    }
    s->w = w;
    s->h = h;
    s->state = -1;                                       // until it is proven: a failure below stays remembered
    s->used = ++g_clock;
    char rel[64];
    PackRel(e.sheet, rel, sizeof rel);
    const DWORD t0 = GetTickCount();
    const int cw = kW * kMaster, ch = kH * kMaster;
    if (!hdpack::Expand(g_pack[e.sheet], e.x * kMaster, e.y * kMaster, cw, ch, g_map, g_cell)) return s;
    if (!Scratch(w, h)) {
        Log("[objecthd] no room for a %dx%d scratch -> stock at that size\n", w, h);
        return s;
    }
    uint8_t rgbq[1024];
    Colours(dst, rgbq);
    basehd_law::PaletteBoxShrink(g_cell, cw, ch, cw, Pixels(g_scratch), w, h, Field(g_scratch, kBufPitch), rgbq);
    // cut in place: an engine Sprite is never copied to another address
    if (g_extract(&s->spr, g_scratch, kKey, 0, 0, w, h, nullptr) != 0 || !HasData(s->spr)) {
        Dbg("[objecthd] %s (%d,%d) at %dx%d cuts empty -> stock at that size\n", rel, e.x, e.y, w, h);
        if (HasData(s->spr)) reinterpret_cast<FSpriteClose>(At(kVA_SpriteClose))(&s->spr);
        s->spr = Sprite{};
        return s;
    }
    s->state = 1;
    g_bytes += static_cast<size_t>(w) * h;
    Trim(s);
    Dbg("[objecthd] %s (%d,%d) cut at %dx%d in %lu ms (%zu KB held)\n", rel, e.x, e.y, w, h, GetTickCount() - t0,
        g_bytes >> 10);
    return s;
}

Entry* EntryFor(const void* spr)
{
    const uintptr_t va = reinterpret_cast<uintptr_t>(spr);
    const uintptr_t base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr)) - 0x400000;
    for (int i = 0; i < g_count; ++i) if (g_entries[i].va + base == va) return &g_entries[i];
    return nullptr;
}

// The HD copy of spr drawn at num / den, or null (off, not ours, no usable art, odd scale, this size failed).
Sprite* HdFor(void* spr, void* dst, int n, int d)
{
    if (!g_on || n <= 0 || d <= 0) return nullptr;
    Entry* e = EntryFor(spr);
    if (!e || g_state[e->sheet] != 1 || e->blank != 0) return nullptr;
    int w = 0, h = 0;
    basehd_law::CellSize(kW, kH, n, d, &w, &h);
    if (w < 1 || h < 1 || w > kW * kMaxCut || h > kH * kMaxCut) return nullptr;
    Slot* s = Find(*e, w, h);
    if (!s) s = Cut(*e, w, h, dst);
    if (s->state != 1) return nullptr;
    s->used = ++g_clock;
    return &s->spr;
}

int32_t ScaleNum() { return *reinterpret_cast<int32_t*>(At(kVA_ScaleNum)); }
int32_t ScaleDen() { return *reinterpret_cast<int32_t*>(At(kVA_ScaleDen)); }

struct Unscaled {                                     // SCALE_NUM_G = SCALE_DEN_G for one draw (SCALE_DEN_G untouched)
    int32_t* num;
    int32_t n;
    Unscaled() : num(reinterpret_cast<int32_t*>(At(kVA_ScaleNum))), n(*num) { *num = ScaleDen(); }
    ~Unscaled() { *num = n; }
};

// --- hooks: each the drop-in of the call it replaces -------------------------------------------------------------

int __fastcall BlitCoreHook(void* spr, void* /*edx*/, void* dst, int key, int x, int y)
{
    if (Sprite* hd = HdFor(spr, dst, ScaleNum(), ScaleDen())) { Unscaled one; return g_blitCore(hd, dst, key, x, y); }
    return g_blitCore(spr, dst, key, x, y);
}

int __fastcall DrawDestHook(void* spr, void* /*edx*/, void* dst, int key, int x, int y, void* table)
{
    if (Sprite* hd = HdFor(spr, dst, ScaleNum(), ScaleDen())) { Unscaled one; return g_drawDest(hd, dst, key, x, y, table); }
    return g_drawDest(spr, dst, key, x, y, table);
}

// Sprite_draw_2 sets the scale globals from its own num / den: an HD copy at that ratio is drawn at 1 / 1.
int __fastcall Draw2Hook(void* spr, void* /*edx*/, void* dst, int key, int x, int y, int num, int den)
{
    if (Sprite* hd = HdFor(spr, dst, num, den)) return g_draw2(hd, dst, key, x, y, 1, 1);
    return g_draw2(spr, dst, key, x, y, num, den);
}

int __fastcall PopupArtHook(void* spr, void* /*edx*/, void* dst, int key, int x, int y, int num, int den)
{
    if (Sprite* hd = HdFor(spr, dst, num, den)) return g_popupArt(hd, dst, key, x, y, 1, 1);
    return g_popupArt(spr, dst, key, x, y, num, den);
}

bool GameDir(char* out, size_t n)
{
    const DWORD len = GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    if (len == 0 || len >= n) return false;
    char* slash = strrchr(out, '\\');
    if (!slash) return false;
    slash[1] = 0;
    return true;
}

void IniPath(char* out, size_t n) { _snprintf_s(out, n, _TRUNCATE, "%sAlpha Centauri.ini", g_dir); }

// Every screen behind the Preferences window that can show an object: the map, the HUD panels, the base screen.
void RepaintObjectScreens()
{
    reinterpret_cast<void(__cdecl*)(int)>(At(kVA_DrawMap))(1);
    reinterpret_cast<int(__thiscall*)(void*)>(At(kVA_StatusWinRedraw))(At(kVA_StatusWin));
    if (*reinterpret_cast<int*>(At(kVA_BaseWin + 0x9C)) & 1)
        reinterpret_cast<void(__thiscall*)(void*)>(At(kVA_GraphicWinRedraw))(At(kVA_BaseWin));
}

} // namespace

bool ObjectHdAvailable() { return g_installed; }
int  ObjectHdGet() { return g_on; }

void ObjectHdSet(int on)
{
    on = on ? 1 : 0;
    if (!g_installed || on == g_on) return;
    g_on = on;                                           // the HD objects stay cut: switching back on costs nothing
    RepaintObjectScreens();
}

void ObjectHdSave()
{
    if (!g_installed) return;
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "ObjectHD", g_on ? "1" : "0", ini);
}

void InstallObjectHd()
{
    if (!GameDir(g_dir, sizeof g_dir)) return;
    bool any = false;
    for (int s = 0; s < kSheets; ++s) {
        char rel[64], path[MAX_PATH];
        PackRel(s, rel, sizeof rel);
        _snprintf_s(path, sizeof path, _TRUNCATE, "%s%s", g_dir, rel);
        any = any || GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
    }
    if (!any) return;                                    // no pack: nothing patched, no Preferences row
    if (!PrefsTabInstalled()) {                          // no row to switch it with (an exe without the mod's cave)
        Log("[objecthd] no Longevity Preferences tab on this exe -> HD objects NOT installed\n");
        return;
    }

    // every site first: all of them or none, so a supplied object looks the same on every screen
    for (uint32_t site : kExtractSites) {
        if (!CallsTo(site, kVA_Extract2)) {
            Log("[objecthd] unexpected bytes at sprite cut %X -> HD objects NOT installed\n", site);
            return;
        }
    }
    uint32_t bc[32], dd[8];                              // every core / draw_dest call in the terrain pass (E8 rel32)
    int nbc = 0, ndd = 0;
    for (uint32_t va = kTerrainLo; va + 5 <= kTerrainHi; ++va) {
        if (At(va)[0] != 0xE8) continue;
        if (CallsTo(va, kVA_BlitCore) && nbc < 32) bc[nbc++] = va;
        else if (CallsTo(va, kVA_DrawDest) && ndd < 8) dd[ndd++] = va;
    }
    if (nbc != kBlitCoreCalls || ndd != kDrawDestCalls) {
        Log("[objecthd] found %d + %d draw calls in the terrain pass, expected %d + %d -> HD objects NOT installed\n",
            nbc, ndd, kBlitCoreCalls, kDrawDestCalls);
        return;
    }
    for (uint32_t site : kDatalinkSites) {
        if (!CallsTo(site, kVA_Draw2)) {
            Log("[objecthd] unexpected bytes at Datalinks draw %X -> HD objects NOT installed\n", site);
            return;
        }
    }
    if (!CallsTo(kSpriteBoxSite, kVA_Draw2)) {
        Log("[objecthd] unexpected bytes at SpriteBox draw %X -> HD objects NOT installed\n", kSpriteBoxSite);
        return;
    }
    uintptr_t lo = 0, hi = 0;                            // the popup picture: Sprite_draw_2, or the mod's thunk_art_draw
    const uintptr_t art = CallTarget(kPopupArtSite);
    const bool artThunk = art == reinterpret_cast<uintptr_t>(At(kVA_ArtDraw)) && UimodPcave2Range(&lo, &hi) &&
                          art >= lo && art < hi;
    if (art != reinterpret_cast<uintptr_t>(At(kVA_Draw2)) && !artThunk) {
        Log("[objecthd] unexpected bytes at popup picture draw %X -> HD objects NOT installed\n", kPopupArtSite);
        return;
    }

    // usable art decides it: prove the packs (and find their blank cells) before patching anything
    BuildTable();
    for (int i = 0; i < 256; ++i) {
        const uint8_t v = static_cast<uint8_t>(i + kLoadShift);                    // Buffer_load_pcx(.., 10, 236)
        g_map[i] = v == kBgIndex || v == kSlabIndex ? static_cast<uint8_t>(kKeyIndex) : v;   // Buffer_change_color x2
    }
    bool usable = false;
    for (int s = 0; s < kSheets; ++s) usable = LoadSheet(s) || usable;
    if (!usable) {
        Log("[objecthd] no usable pack in terrain\\ -> HD objects NOT installed\n");
        return;
    }

    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "ObjectHD", kObjectHdDefault, ini) != 0 ? 1 : 0;
    g_extract = reinterpret_cast<FExtract2>(At(kVA_Extract2));
    g_draw2 = reinterpret_cast<FDraw2>(At(kVA_Draw2));
    g_popupArt = reinterpret_cast<FDraw2>(art);
    g_blitCore = reinterpret_cast<FBlitCore>(At(kVA_BlitCore));
    g_drawDest = reinterpret_cast<FDrawDest>(At(kVA_DrawDest));
    for (int i = 0; i < nbc; ++i) Retarget(bc[i], reinterpret_cast<const void*>(&BlitCoreHook));
    for (int i = 0; i < ndd; ++i) Retarget(dd[i], reinterpret_cast<const void*>(&DrawDestHook));
    for (uint32_t site : kDatalinkSites) Retarget(site, reinterpret_cast<const void*>(&Draw2Hook));
    Retarget(kSpriteBoxSite, reinterpret_cast<const void*>(&Draw2Hook));
    Retarget(kPopupArtSite, reinterpret_cast<const void*>(&PopupArtHook));
    g_installed = true;
    Log("[objecthd] installed: %d TER1 / TER1WRECK objects from terrain\\*_x%d.pcx (%d terrain-pass + %d Datalinks + 2 "
        "popup draw sites%s), %s\n", g_count, kMaster, nbc + ndd, static_cast<int>(sizeof kDatalinkSites / sizeof kDatalinkSites[0]),
        artThunk ? ", picture via thunk_art_draw" : "", g_on ? "on" : "off ([UIMod] ObjectHD=0)");
}
