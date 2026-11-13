// basehd.cpp -- drop-in HD base sprites: the faction cities, every faction, on every screen that draws a base.
//
// A pack is <game>\bases\<faction>_x8.pcx: the base block of <faction>.pcx -- its top-left 404x456 pixels, 6 rows
// (land, land defence 1/2, water, water defence 1/2) x 4 sizes of 100x75 sprites on a 101x76 grid -- redrawn at 8x
// (3232x3648), 8-bit, in the faction file's own palette indices and with its palette. A pack may cover any subset of
// the factions, and any subset of a faction's 24 cells.
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike; symbols in work/symbols/terranx.h):
//  * load_faction_art 0x453710 loads "<MFactions[f].filename>.pcx" with Buffer_load_pcx(name, 0, 10, 236) (loaded
//    index = file index + 10 mod 256) and cuts the 24 base sprites with ONE Sprite_extract_2 0x5E39A0 call (@0x453836,
//    100x75, key 9) into g_faction_sprites 0x78E978 (+f*0x65C, index water*12 + size*3 + defence).
//  * base_draw 0x55AF20 sets SCALE_NUM_G / SCALE_DEN_G (0x696D18 / 0x696D1C) and draws the base with ONE
//    Sprite_draw_dest 0x5E5833 call (@0x55B32B). Every caller of base_draw goes through that one call -- the map,
//    the HUD, the base screen, the F-reports, the tutorial -- so the HD art shows wherever the game draws a base.
//    Sprite_draw_dest truncates the scaled size and shrinks by SKIPPING rows and columns: an 8x sprite drawn at 1.5x
//    looked jagged in game.
//
// So the engine never resizes the HD art. For each scale actually drawn, each base sprite is made from its 8x cell
// at the size the engine gives the stock cell (basehd_law::CellSize) with basehd_law::PaletteBoxShrink (never leaves
// the palette; keys stay keys), cut through the engine's own Sprite_extract_2 and drawn with SCALE_NUM_G =
// SCALE_DEN_G (Sprite_draw_dest's unscaled branch; SCALE_DEN_G itself is left alone), top-left at the same (x, y). The
// drawn base is usually within a pixel of the stock one. Above 8x the same law enlarges the cell.
//
// Art that is not provided, or cannot be used, is drawn exactly as the game draws it without this module: the
// original call with the original arguments, decided once and then free.
//  * per faction: the pack file is proven once (hdpack::Load: bounded scan of the whole file, the faction file's
//    palette) when load_faction_art loads that faction; a file that fails is logged once and that faction stays stock;
//  * per sprite: a cell that is all key is stock for good (one debug line);
//  * per sprite and size: a cut that fails (an empty rect, no memory) is remembered and never retried.
// Nothing is allocated through the engine except the one scratch Buffer the cut goes through (grow-only, at most
// kMaxCut x the stock cell, its address room probed first); everything else is plain memory and its failure is stock.
//
// Memory budget: a faction's pack is its file bytes (~3 to 4 MB) while that faction is in the game -- the file is
// read and scanned once, and a sprite at a new size expands only its own cell's scanlines from them. Cut sprites cost
// about w x h bytes each and are kept for every size drawn (kSizes per sprite), up to kBudget in all, least recently
// drawn first out. Switching the row off keeps them, so switching it on again costs nothing.
//
// Levers, both byte-checked E8 retargets, cave-free (work/tests/test_basehd_sites.py pins them):
//  * @0x453836 -> ExtractRecorder: records each base sprite and its rect. The faction comes from the sprite's slot in
//    g_faction_sprites, its file from MFactions[f].filename -- never a scratch string. Sprites cut before this module
//    was installed are placed by their slot at their first draw (Adopt).
//  * @0x55B32B -> DrawHook: a recorded sprite whose faction has a usable pack is drawn from its HD copy.
// Installed only where the Longevity Preferences tab is, and only when at least one pack on disk is usable: otherwise
// nothing is patched and no row is built. "HD Base Sprites" ([UIMod] BaseHD) switches it live.

#include "basehd.h"
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

// work/symbols/terranx.h
constexpr uintptr_t kVA_Extract2       = 0x5E39A0;   // Sprite_extract_2: thiscall (Sprite*, Buffer* src, key, x, y, w, h, a8) RET 0x1C
constexpr uintptr_t kVA_DrawDest       = 0x5E5833;   // Sprite_draw_dest: thiscall (Sprite*, Buffer* dst, key, x, y, table) RET 0x14
constexpr uintptr_t kVA_SpriteClose    = 0x5E3820;   // Sprite_close: thiscall (Sprite*)
constexpr uintptr_t kVA_BufferCtor     = 0x5D7210;   // Buffer_ctor: thiscall (Buffer*)
constexpr uintptr_t kVA_BufferInit     = 0x5D7670;   // Buffer_init: thiscall (Buffer*, w, h, flags, surf) RET 0x10
constexpr uintptr_t kVA_FactionSprites = 0x78E978;   // g_faction_sprites: 8 x 0x65C, 37 Sprites of 0x2C each
constexpr uintptr_t kVA_MFactions      = 0x946A50;   // MFactions[8], stride 0x59C
constexpr int       kMFactionFilename  = 0x04;       // MFaction +0x04 char filename[24] (the .pcx stem)
constexpr uintptr_t kVA_ScaleNum       = 0x696D18;   // SCALE_NUM_G
constexpr uintptr_t kVA_ScaleDen       = 0x696D1C;   // SCALE_DEN_G
constexpr uintptr_t kVA_MainPalette    = 0x94C590;   // g_main_palette: PALETTEENTRY[256] (fallback colours)
constexpr uintptr_t kVA_DrawMap        = 0x46B190;   // draw_map: cdecl(int) -- full map repaint
constexpr uintptr_t kVA_StatusWinRedraw = 0x4B9EA0;  // StatusWin_redraw: thiscall (StatusWin*) -- the HUD panels
constexpr uintptr_t kVA_StatusWin      = 0x8C5568;   // StatusWin_g
constexpr uintptr_t kVA_GraphicWinRedraw = 0x5D5A70; // GraphicWin_redraw: thiscall (GraphicWin*)
constexpr uintptr_t kVA_BaseWin        = 0x6A7628;   // BaseWin_g (+0x9C bit 0: on screen)
constexpr uint32_t kSiteExtract = 0x453836;
constexpr uint32_t kSiteDraw    = 0x55B32B;
constexpr int kFactionStride = 0x65C, kMFactionStride = 0x59C, kSpriteSize = 0x2C;

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufH = 0x84, kBufColors = 0xA4, kBufPitch = 0x4A8;
constexpr int kBufSize = 0x588;
constexpr int kBlockW = 404, kBlockH = 456;          // the base block of a faction pcx (6 rows x 4 sizes)
constexpr int kCellW = 100, kCellH = 75;             // one base sprite's cell (load_faction_art's cut)
constexpr int kMaster = 8;
constexpr int kMaxCut = 12;                           // never cut above 12x the stock cell: the scratch stays <= ~1 MB
constexpr int kKey = 9;                               // load_faction_art's key (file 255 -> loaded 9)
constexpr int kLoadShift = 10;                        // Buffer_load_pcx(name, 0, 10, 236): loaded = file + 10 mod 256
constexpr int kEntries = 8 * 24;                      // 8 faction slots x 24 base sprites
constexpr int kSizes = 24;                            // sizes kept per sprite (PRACX: up to 20 zoom levels, + HUD/base screen)
constexpr size_t kBudget = size_t(32) << 20;          // all cut base sprites together (w x h bytes each)
constexpr int kPacks = 32;                            // faction stems remembered (in play + seen this session)

struct Sprite { uint8_t raw[0x2C]; };                 // +0x04 data, +0x10/+0x14 w/h, +0x28 owner flag

struct Slot { int w, h, state; unsigned used; Sprite spr; };   // state 1 = HD sprite, -1 = this size fails: stock

struct Entry {
    void* stock;                                      // null = free
    int pack;                                         // index into g_packs, -1 = none
    int x, y, w, h;                                   // stock rect in the faction pcx
    int blank;                                        // -1 not yet known, 1 = the pack's cell is all key: stock
    Slot slots[kSizes];
};

struct FactionPack {
    char stem[32];                                    // the faction file stem, e.g. "UNIV" ("" = free record)
    int state;                                        // 0 = not tried (or released), 1 = usable, -1 = unusable
    hdpack::Pack px;
};

typedef int (__thiscall* FExtract2)(void*, void*, int, int, int, int, int, void*);
typedef int (__thiscall* FDraw)(void*, void*, int, int, int, void*);
typedef void (__thiscall* FSpriteClose)(void*);
typedef void (__thiscall* FBufferCtor)(void*);
typedef int (__thiscall* FBufferInit)(void*, int, int, int, void*);

FExtract2 g_extract = nullptr;
FDraw g_draw = nullptr;
Entry g_entries[kEntries];
FactionPack g_packs[kPacks];
alignas(16) uint8_t g_scratch[kBufSize + 0x80];      // the one scratch Buffer every cut goes through (grow-only)
bool g_scratchReady = false;
int g_scratchW = 0, g_scratchH = 0;
uint8_t* g_cell = nullptr;                            // one 8x cell, expanded (800 x 600)
uint8_t g_map[256];                                   // file index -> loaded index (load_faction_art's)
size_t g_bytes = 0;                                   // cut sprites held, w x h each
bool g_installed = false;
int g_on = kBaseHdDefault;
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

uint8_t* Pixels(void* buf)
{
    uint8_t* d = *reinterpret_cast<uint8_t**>(static_cast<uint8_t*>(buf) + kBufData);
    return d ? d : *reinterpret_cast<uint8_t**>(static_cast<uint8_t*>(buf) + kBufBits);
}

int Field(void* buf, int off) { return *reinterpret_cast<int*>(static_cast<uint8_t*>(buf) + off); }

bool HasData(const Sprite& s) { return *reinterpret_cast<void* const*>(s.raw + 4) != nullptr; }

// The faction slot a sprite pointer lies in (0..7, its index 0..36 in *idx), or -1.
int FactionOf(const void* spr, int* idx)
{
    const uintptr_t lo = reinterpret_cast<uintptr_t>(At(kVA_FactionSprites));
    const uintptr_t p = reinterpret_cast<uintptr_t>(spr);
    if (p < lo || p >= lo + 8 * kFactionStride) return -1;
    const int off = static_cast<int>((p - lo) % kFactionStride);
    if (off % kSpriteSize != 0) return -1;
    *idx = off / kSpriteSize;
    return static_cast<int>((p - lo) / kFactionStride);
}

const char* FactionFile(int f)
{
    return reinterpret_cast<const char*>(At(kVA_MFactions + f * kMFactionStride + kMFactionFilename));
}

// "UNIV" -> "bases\UNIV_x8.pcx" (relative to the game folder: how the log names it)
void PackRel(const char* stem, char* out, size_t n) { _snprintf_s(out, n, _TRUNCATE, "bases\\%s_x%d.pcx", stem, kMaster); }

// --- packs ------------------------------------------------------------------------------------------------------

// Prove <stem>'s pack (once per stem until released): the bounded scan, against the faction file's palette.
void LoadPack(FactionPack& p)
{
    char rel[64], path[MAX_PATH], stock[MAX_PATH];
    PackRel(p.stem, rel, sizeof rel);
    _snprintf_s(path, sizeof path, _TRUNCATE, "%s%s", g_dir, rel);
    p.state = -1;
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return;   // no pack for this faction: stock, quietly
    uint8_t pal[768];
    _snprintf_s(stock, sizeof stock, _TRUNCATE, "%s%s.pcx", g_dir, p.stem);
    if (!hdpack::ReadPalette(stock, pal)) {
        Log("[basehd] %s: the faction file %s.pcx has no readable palette -> stock bases for %s\n", rel, p.stem, p.stem);
        return;
    }
    const DWORD t0 = GetTickCount();
    const hdpack::Result r = hdpack::Load(&p.px, path, kBlockW * kMaster, kBlockH * kMaster, pal);
    if (r != hdpack::kOk) {
        Log("[basehd] %s %s (want an 8-bit %dx%d PCX in %s.pcx's palette) -> stock bases for %s\n", rel,
            hdpack::Why(r), kBlockW * kMaster, kBlockH * kMaster, p.stem, p.stem);
        return;
    }
    p.state = 1;
    Dbg("[basehd] %s proven in %lu ms (%zu bytes kept)\n", rel, GetTickCount() - t0, p.px.size);
}

// The record for <stem>, loading it if it was never tried; -1 when the table is full (then that faction stays stock).
int PackFor(const char* stem)
{
    int freeRec = -1;
    for (int i = 0; i < kPacks; ++i) {
        if (g_packs[i].stem[0] && _stricmp(g_packs[i].stem, stem) == 0) {
            if (g_packs[i].state == 0) LoadPack(g_packs[i]);
            return i;
        }
        if (!g_packs[i].stem[0] && freeRec < 0) freeRec = i;
    }
    if (freeRec < 0) return -1;
    FactionPack& p = g_packs[freeRec];
    strncpy_s(p.stem, stem, _TRUNCATE);
    LoadPack(p);
    return freeRec;
}

// Whether a proven pack has art in at least one of its 24 cells (load_faction_art's grid): a pack of blank cells draws
// nothing HD, so it does not make the row worth installing.
bool HasArt(const FactionPack& p)
{
    if (!g_cell) g_cell = static_cast<uint8_t*>(malloc(static_cast<size_t>(kCellW) * kMaster * kCellH * kMaster));
    if (!g_cell) return false;
    const size_t n = static_cast<size_t>(kCellW) * kMaster * kCellH * kMaster;
    for (int row = 0; row < 6; ++row)
        for (int size = 0; size < 4; ++size) {
            if (!hdpack::Expand(p.px, (1 + size * 101) * kMaster, (1 + row * 76) * kMaster, kCellW * kMaster,
                                kCellH * kMaster, g_map, g_cell)) continue;
            for (size_t k = 0; k < n; ++k) if (g_cell[k] != kKey) return true;
        }
    return false;
}

// A pack no recorded sprite uses any more (that faction left the game) gives its bytes back; it is proven again if
// a later game brings the faction back.
void ReleaseUnusedPacks()
{
    for (int i = 0; i < kPacks; ++i) {
        FactionPack& p = g_packs[i];
        if (p.state != 1) continue;
        bool used = false;
        for (const Entry& e : g_entries) if (e.stock && e.pack == i) { used = true; break; }
        if (!used) {
            hdpack::Free(&p.px);
            p.state = 0;
            Dbg("[basehd] %s left the game: its pack is released\n", p.stem);
        }
    }
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

void Release(Entry& e)
{
    for (Slot& s : e.slots) CloseSlot(s);
    e.blank = -1;
}

// Over budget: drop the least recently drawn HD sprites (never `keep`).
void Trim(const Slot* keep)
{
    while (g_bytes > kBudget) {
        Slot* lru = nullptr;
        for (Entry& e : g_entries)
            for (Slot& s : e.slots)
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
    const uint8_t* pe = At(kVA_MainPalette);          // PALETTEENTRY (r,g,b,f) -> RGBQUAD (b,g,r,0)
    for (int i = 0; i < 256; ++i) {
        rgbq[i * 4] = pe[i * 4 + 2]; rgbq[i * 4 + 1] = pe[i * 4 + 1]; rgbq[i * 4 + 2] = pe[i * 4]; rgbq[i * 4 + 3] = 0;
    }
}

// Make e's HD sprite at w x h. Returns its slot: state 1 (drawn HD) or -1 (this size is stock for good); null when
// e's cell turned out blank (e->blank = 1: every size stock).
Slot* Cut(Entry& e, int w, int h, void* dst)
{
    Slot* s = nullptr;
    for (Slot& it : e.slots) if (it.state == 0) { s = &it; break; }
    if (!s) {                                          // every size slot used: the least recently drawn one goes
        s = &e.slots[0];
        for (Slot& it : e.slots) if (it.used < s->used) s = &it;
        CloseSlot(*s);
    }
    s->w = w;
    s->h = h;
    s->state = -1;                                     // until it is proven: a failure below stays remembered
    s->used = ++g_clock;
    const DWORD t0 = GetTickCount();
    const int cw = e.w * kMaster, ch = e.h * kMaster;
    if (!g_cell) g_cell = static_cast<uint8_t*>(malloc(static_cast<size_t>(kCellW) * kMaster * kCellH * kMaster));
    if (!g_cell || cw > kCellW * kMaster || ch > kCellH * kMaster ||
        !hdpack::Expand(g_packs[e.pack].px, e.x * kMaster, e.y * kMaster, cw, ch, g_map, g_cell)) {
        Log("[basehd] %s: no memory to cut a base sprite -> stock at %dx%d\n", g_packs[e.pack].stem, w, h);
        return s;
    }
    if (e.blank < 0) {
        e.blank = 1;
        for (size_t i = 0, n = static_cast<size_t>(cw) * ch; i < n && e.blank; ++i) if (g_cell[i] != kKey) e.blank = 0;
        if (e.blank) {
            Dbg("[basehd] %s: the cell at (%d,%d) is blank -> that base sprite stays stock\n", g_packs[e.pack].stem, e.x, e.y);
            *s = Slot{};
            return nullptr;
        }
    }
    if (!Scratch(w, h)) {
        Log("[basehd] no room for a %dx%d scratch -> stock at that size\n", w, h);
        return s;
    }
    uint8_t rgbq[1024];
    Colours(dst, rgbq);
    basehd_law::PaletteBoxShrink(g_cell, cw, ch, cw, Pixels(g_scratch), w, h, Field(g_scratch, kBufPitch), rgbq);
    // cut in place: an engine Sprite is never copied to another address
    if (g_extract(&s->spr, g_scratch, kKey, 0, 0, w, h, nullptr) != 0 || !HasData(s->spr)) {
        Dbg("[basehd] %s (%d,%d) at %dx%d cuts empty -> stock at that size\n", g_packs[e.pack].stem, e.x, e.y, w, h);
        if (HasData(s->spr)) reinterpret_cast<FSpriteClose>(At(kVA_SpriteClose))(&s->spr);
        s->spr = Sprite{};
        return s;
    }
    s->state = 1;
    g_bytes += static_cast<size_t>(w) * h;
    Trim(s);
    Dbg("[basehd] %s (%d,%d) cut at %dx%d in %lu ms (%zu KB held)\n", g_packs[e.pack].stem, e.x, e.y, w, h,
        GetTickCount() - t0, g_bytes >> 10);
    return s;
}

Entry* EntryOf(const void* spr)
{
    for (Entry& e : g_entries) if (e.stock == spr) return &e;
    return nullptr;
}

Entry* NewEntry(void* spr)
{
    for (Entry& e : g_entries)
        if (!e.stock) { e = Entry{}; e.stock = spr; e.pack = -1; e.blank = -1; return &e; }
    return nullptr;
}

// Point e at <stem>'s rect (x, y, w, h); a change (a new game put another faction in this slot) drops its HD copies.
void Assign(Entry& e, const char* stem, int x, int y, int w, int h)
{
    const int pack = PackFor(stem);
    if (pack == e.pack && e.x == x && e.y == y && e.w == w && e.h == h) return;
    Release(e);
    e.pack = pack;
    e.x = x; e.y = y; e.w = w; e.h = h;
}

// A base sprite load_faction_art cut BEFORE this module was installed (the first game_init can run before uimod's
// Init): placed by its slot -- load_faction_art's own layout (index water*12 + size*3 + defence, rect
// (1 + size*101, 1 + row*76, 100, 75)).
Entry* Adopt(void* spr)
{
    int idx = 0;
    const int f = FactionOf(spr, &idx);
    if (f < 0 || idx >= 24 || !FactionFile(f)[0]) return nullptr;
    Entry* e = NewEntry(spr);
    if (!e) return nullptr;
    const int water = idx / 12, size = idx % 12 / 3, def = idx % 3;
    Assign(*e, FactionFile(f), 1 + size * 101, 1 + (water * 3 + def) * 76, kCellW, kCellH);
    return e;
}

// --- hooks ------------------------------------------------------------------------------------------------------

// Stands in for Sprite_extract_2 at load_faction_art's base-sprite site: same contract (thiscall, RET 0x1C).
int __fastcall ExtractRecorder(void* spr, void* /*edx*/, void* src, int key, int x, int y, int w, int h, void* a8)
{
    const int rc = g_extract(spr, src, key, x, y, w, h, a8);
    int idx = 0;
    const int f = FactionOf(spr, &idx);
    if (rc != 0 || f < 0 || x < 0 || y < 0 || w != kCellW || h != kCellH || x + w > kBlockW || y + h > kBlockH)
        return rc;
    Entry* e = EntryOf(spr);
    if (!e) e = NewEntry(spr);
    if (!e) return rc;
    Assign(*e, FactionFile(f), x, y, w, h);
    if (idx == 23) ReleaseUnusedPacks();               // the faction's last base sprite: drop packs no slot uses
    return rc;
}

// Stands in for Sprite_draw_dest at base_draw's site: same contract (thiscall, RET 0x14).
int __fastcall DrawHook(void* spr, void* /*edx*/, void* dst, int key, int x, int y, void* table)
{
    if (!g_on) return g_draw(spr, dst, key, x, y, table);
    Entry* e = EntryOf(spr);
    if (!e) e = Adopt(spr);
    int32_t* num = reinterpret_cast<int32_t*>(At(kVA_ScaleNum));
    const int32_t n = *num, d = *reinterpret_cast<int32_t*>(At(kVA_ScaleDen));
    if (!e || e->pack < 0 || g_packs[e->pack].state != 1 || e->blank == 1 || n <= 0 || d <= 0)
        return g_draw(spr, dst, key, x, y, table);
    int w = 0, h = 0;
    basehd_law::CellSize(e->w, e->h, n, d, &w, &h);
    if (w < 1 || h < 1 || w > e->w * kMaxCut || h > e->h * kMaxCut) return g_draw(spr, dst, key, x, y, table);
    Slot* s = Find(*e, w, h);
    if (!s) s = Cut(*e, w, h, dst);
    if (!s || s->state != 1) return g_draw(spr, dst, key, x, y, table);
    s->used = ++g_clock;
    *num = d;                                          // Sprite_draw_dest's unscaled branch (num == den): drawn 1:1
    const int rc = g_draw(&s->spr, dst, key, x, y, table);
    *num = n;
    return rc;
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

// Every screen behind the Preferences window that can show a base: the map, the HUD panels, the base screen.
void RepaintBaseScreens()
{
    reinterpret_cast<void(__cdecl*)(int)>(At(kVA_DrawMap))(1);
    reinterpret_cast<int(__thiscall*)(void*)>(At(kVA_StatusWinRedraw))(At(kVA_StatusWin));
    if (*reinterpret_cast<int*>(At(kVA_BaseWin + 0x9C)) & 1)
        reinterpret_cast<void(__thiscall*)(void*)>(At(kVA_GraphicWinRedraw))(At(kVA_BaseWin));
}

} // namespace

bool BaseHdAvailable() { return g_installed; }
int  BaseHdGet() { return g_on; }

void BaseHdSet(int on)
{
    on = on ? 1 : 0;
    if (!g_installed || on == g_on) return;
    g_on = on;                                         // the HD sprites stay cut: switching back on costs nothing
    RepaintBaseScreens();
}

void BaseHdSave()
{
    if (!g_installed) return;
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "BaseHD", g_on ? "1" : "0", ini);
}

void InstallBaseHd()
{
    if (!GameDir(g_dir, sizeof g_dir)) return;
    char pattern[MAX_PATH];
    WIN32_FIND_DATAA fd;
    if (_snprintf_s(pattern, sizeof pattern, _TRUNCATE, "%sbases\\*_x%d.pcx", g_dir, kMaster) <= 0) return;
    const HANDLE fh = FindFirstFileA(pattern, &fd);
    if (fh == INVALID_HANDLE_VALUE) return;            // no pack: nothing patched, no Preferences row
    if (!PrefsTabInstalled()) {                        // no row to switch it with (an exe without the mod's cave)
        FindClose(fh);
        Log("[basehd] no Longevity Preferences tab on this exe -> HD bases NOT installed\n");
        return;
    }
    for (int i = 0; i < 256; ++i) g_map[i] = static_cast<uint8_t>(i + kLoadShift);
    // Usable art decides it: prove packs until one passes (the rest are proven when their faction is loaded).
    bool usable = false;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        char stem[MAX_PATH];
        strncpy_s(stem, fd.cFileName, _TRUNCATE);
        char* suffix = strrchr(stem, '_');
        if (!suffix || _stricmp(suffix, "_x8.pcx") != 0 || suffix == stem || suffix - stem >= 24) continue;
        *suffix = 0;
        const int p = PackFor(stem);
        usable = p >= 0 && g_packs[p].state == 1 && HasArt(g_packs[p]);
        if (p >= 0 && g_packs[p].state == 1 && !usable) {
            Log("[basehd] bases\\%s_x%d.pcx has no art in any base cell -> stock bases for %s\n", stem, kMaster, stem);
            hdpack::Free(&g_packs[p].px);
            g_packs[p].state = -1;
        }
    } while (!usable && FindNextFileA(fh, &fd));
    FindClose(fh);
    if (!usable) {
        Log("[basehd] no usable pack in bases\\ -> HD bases NOT installed\n");
        return;
    }

    if (!CallsTo(kSiteExtract, kVA_Extract2)) {
        Log("[basehd] unexpected bytes at extract call %X -> HD bases NOT installed\n", kSiteExtract);
        return;
    }
    if (!CallsTo(kSiteDraw, kVA_DrawDest)) {
        Log("[basehd] unexpected bytes at draw call %X -> HD bases NOT installed\n", kSiteDraw);
        return;
    }
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "BaseHD", kBaseHdDefault, ini) != 0 ? 1 : 0;
    g_extract = reinterpret_cast<FExtract2>(At(kVA_Extract2));
    g_draw = reinterpret_cast<FDraw>(At(kVA_DrawDest));
    Retarget(kSiteExtract, reinterpret_cast<const void*>(&ExtractRecorder));
    Retarget(kSiteDraw, reinterpret_cast<const void*>(&DrawHook));
    g_installed = true;
    Log("[basehd] installed: base sprites from bases\\*_x%d.pcx (extract + draw sites), %s\n", kMaster,
        g_on ? "on" : "off ([UIMod] BaseHD=0)");
}
