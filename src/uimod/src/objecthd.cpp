// objecthd.cpp -- drop-in HD map objects: the monolith, pods, resource specials, terraforming (mines, solar, condensers,
// boreholes, farms, ...), everything load_terrain cuts out of TER1.PCX, the Unity wreck / canyon pieces it cuts out of
// TER1WRECK.PCX, and the native life / artifact sprites load_units cuts out of UNITS.PCX.
//
// A pack is <game>\terrain\ter1_x8.pcx, ter1wreck_x8.pcx and/or units_x8.pcx: the sheet redrawn at 8x (8192x6144),
// 8-bit, in the STOCK file's palette indices (background 253 and the tile slab 252 stay see-through, as in the stock
// file). Any subset may be present; a sheet without a pack stays stock.
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike; symbols in work/symbols/terranx.h):
//  * load_terrain 0x451C50 loads TER1.PCX into the loading canvas 0x798668 with Buffer_load_pcx(name, 0, 10, 236)
//    (loaded index = file index + 10 mod 256: 252 -> 6, 253 -> 7, 255 -> 9) and cuts 71 sprites of 100x62 with 36
//    Sprite_extract_2 0x5E39A0 calls (0x452C07..0x4536A8, key 0x109), each after Buffer_change_color 0x5DE580
//    (0x107 -> 0x109, 0x106 -> 0x109): the background and the slab become the key. TER1WRECK.PCX is loaded and
//    recoloured the same way; its 25 sprites are 25 single Sprite_extract_2 calls (0x4524A8..0x452B8C), 100x62.
//    The sprites live at fixed addresses and fixed rects -- BuildTable below, read off those calls and their loops.
//  * load_units 0x454270 loads UNITS.PCX the same way and cuts 36 sprites of 100x75 with ONE Sprite_extract_2 call
//    (@0x454568) in a loop: row r = 0..9 at y = 2 + 77r, x = 2 + 102c, columns per row {1,7,1,7,7,7,3,1,1} (row 9 is
//    (0x2CC, 0xE9)), into 0x7777A0 + 0x2C * ((r + 9) * 8 + c). Faction units are voxel models and never touch this.
//  * MapWin_gen_terrain_poly 0x4632D0 draws the TER1 / TER1WRECK sprites with Sprite_blit_scaled_core 0x5E4B9A (18 calls) and
//    Sprite_draw_dest 0x5E5833 (3 calls); the unit drawer draws the native ones with ONE Sprite_draw_dest @0x5598F9.
//    Both scale by SCALE_NUM_G / SCALE_DEN_G (0x696D18 / 0x696D1C): truncated size, nearest-neighbour SKIPPING, so
//    an 8x sprite must never be shrunk by the engine. Both take an unscaled branch when num == den.
//
// So, as basehd.cpp, and by the same laws (basehd_law.h, scaling_laws.py): each object is made at exactly the size the
// engine gives the stock sprite (SpriteSize), shrunk -- or above 8x enlarged -- from the 8x master with
// PaletteBoxShrink, cut through the engine's own Sprite_extract_2 with the stock key, and drawn with SCALE_NUM_G =
// SCALE_DEN_G (SCALE_DEN_G untouched), top-left at the same (x, y). Each object keeps its last kSlots sizes.
// The master is NOT loaded through Buffer_load_pcx: a pcx-loaded Buffer must never be destroyed (basehd.cpp), and
// three 8x sheets kept for the session would be ~150 MB in a 32-bit process. So a sheet's pack is decoded here into
// plain memory with load_terrain's own index map (+10 mod 256, then 7 and 6 -> 9), every object of that sheet is cut
// at the size asked for in one pass, and the memory is freed. One decode per sheet per new size.
// Levers: the 21 draw calls in MapWin_gen_terrain_poly and the native-unit draw, byte-checked E8 retargets,
// cave-free (work/tests/test_objecthd_sites.py pins them). The extract calls are left alone: the table is static.
// Sprites drawn on other screens (the Datalink terraform page) stay stock.
// Nothing is patched without a pack on disk. "HD Map Objects" in Longevity Mod Preferences ([UIMod] ObjectHD)
// switches it live; off draws stock and frees every HD sprite.

#include "objecthd.h"
#include "basehd_law.h"

#include <windows.h>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

void UimodLog(const char* msg);

namespace {

// work/symbols/terranx.h
constexpr uintptr_t kVA_Extract2     = 0x5E39A0;   // Sprite_extract_2: thiscall (Sprite*, Buffer* src, key, x, y, w, h, a8) RET 0x1C
constexpr uintptr_t kVA_Draw3        = 0x5E4B9A;   // Sprite_blit_scaled_core: thiscall (Sprite*, Buffer* dst, key, x, y) RET 0x10
constexpr uintptr_t kVA_DrawDest     = 0x5E5833;   // Sprite_draw_dest: thiscall (Sprite*, Buffer* dst, key, x, y, table) RET 0x14
constexpr uintptr_t kVA_SpriteClose  = 0x5E3820;   // Sprite_close
constexpr uintptr_t kVA_BufferCtor   = 0x5D7210;
constexpr uintptr_t kVA_BufferResize = 0x5D7670;
constexpr uintptr_t kVA_ScaleNum     = 0x696D18;   // SCALE_NUM_G
constexpr uintptr_t kVA_ScaleDen     = 0x696D1C;   // SCALE_DEN_G
constexpr uintptr_t kVA_MainPalette  = 0x94C590;   // g_main_palette: PALETTEENTRY[256] (fallback colours)
constexpr uintptr_t kVA_DrawMap      = 0x46B190;   // draw_map: cdecl(int) -- full map repaint
constexpr uintptr_t kFnLo = 0x4632D0, kFnHi = 0x466CA0;   // MapWin_gen_terrain_poly

// load_terrain's / load_units' cuts: one byte-checked site per pattern, proof that the table below is this exe's.
constexpr uint32_t kExtractSites[] = {0x452C07, 0x452D97, 0x453087, 0x453508, 0x453656, 0x4536A8, 0x4524A8, 0x452B8C,
                                      0x454568};
constexpr uint32_t kUnitDrawSite = 0x5598F9;             // the native-unit Sprite_draw_dest
constexpr int kDraw3Calls = 18, kDrawDestCalls = 3;      // in MapWin_gen_terrain_poly
constexpr int kSheets = 3;
const char* const kSheetName[kSheets] = {"ter1", "ter1wreck", "units"};
constexpr int kSprH[kSheets] = {62, 62, 75};

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufColors = 0xA4, kBufPitch = 0x4A8, kBufSize = 0x588;
constexpr int kSheetW = 1024, kSheetH = 768, kMaster = 8, kW = 100, kKey = 0x109, kSlots = 4;
constexpr int kMaxScale = 32;                           // sanity cap: never cut an object above 32x its stock size
constexpr int kLoadShift = 10;                          // Buffer_load_pcx(name, 0, 10, 236): loaded = file + 10 mod 256
constexpr int kKeyIndex = 9, kBgIndex = 7, kSlabIndex = 6;   // load_terrain's Buffer_change_color(0x107/0x106 -> 0x109)

struct Sprite { uint8_t raw[0x2C]; };
struct Slot { int w, h; unsigned used; Sprite spr; };
struct Entry { uintptr_t va; int sheet, x, y; Slot slots[kSlots]; };   // sheet: 0 TER1, 1 TER1WRECK, 2 UNITS

constexpr int kMaxEntries = 140;
Entry g_entries[kMaxEntries];
int g_count = 0;

int g_sheet = 0;
void Add(uintptr_t va, int x, int y) { if (g_count < kMaxEntries) g_entries[g_count++] = Entry{va, g_sheet, x, y, {}}; }

void BuildTable()
{
    g_count = 0;
    g_sheet = 0;
    for (int i = 0; i < 3; ++i) {                               // 0x452BC6: esi 0x791C84 += 0x58, x 1 += 0x65
        const uintptr_t esi = 0x791C84 + i * 0x58;
        const int x = 1 + i * 0x65;
        Add(esi - 0x2C, x, 0x1BF);
        Add(esi, x, 0x243);
    }
    for (int i = 0; i < 3; ++i) {                               // 0x452C6D: esi 0x7A99CC += 0x84
        const uintptr_t esi = 0x7A99CC + i * 0x84;
        const int x = 1 + i * 0x65;
        Add(esi - 0x2C, x, 0x1FE);
        Add(esi, x, 0x282);
        Add(esi + 0x2C, x, 0x2C1);
    }
    const struct { uintptr_t va; int x, y; } singles[] = {
        {0x77944C, 0x1FA, 0x001}, {0x776A50, 0x25F, 0x040}, {0x789B68, 0x1FA, 0x040}, {0x7991F8, 0x25F, 0x07F},
        {0x78A5B0, 0x1FA, 0x07F}, {0x798C40, 0x1FA, 0x0BE}, {0x7A6860, 0x25F, 0x0BE}, {0x7AD010, 0x1FA, 0x13C},
        {0x7ACC60, 0x25F, 0x13C}, {0x7A6830, 0x2C4, 0x13C}, {0x779390, 0x1FA, 0x0FD}, {0x7ABF60, 0x25F, 0x0FD},
        {0x78DD20, 0x2C4, 0x0FD}, {0x7ACB88, 0x2C4, 0x0BE}, {0x78A700, 0x336, 0x0FD}, {0x78A72C, 0x336, 0x0BE},
        {0x7AC11C, 0x1DE, 0x278}, {0x7AC0F0, 0x1DE, 0x2B7}, {0x7AC148, 0x243, 0x278}, {0x7AC098, 0x243, 0x2B7},
        {0x7AC174, 0x2A8, 0x278}, {0x7AC0C4, 0x2A8, 0x2B7}, {0x75B098, 0x130, 0x001},
    };
    for (const auto& s : singles) Add(s.va, s.x, s.y);
    for (int i = 0; i < 5; ++i) {                               // 0x453043: esi 0 += 0x2C, y 0x1C5 += 0x3F
        const int y = 0x1C5 + i * 0x3F;
        Add(0x7792B0 + i * 0x2C, 0x26C, y);
        Add(0x79A710 + i * 0x2C, 0x336, y);
        Add(0x791FC8 + i * 0x2C, 0x39B, y);
    }
    for (int i = 0; i < 3; ++i) {                               // 0x4534CA: esi 0x75B2B4 += 0xB0, y 0xFD += 0x3F
        const uintptr_t esi = 0x75B2B4 + i * 0xB0;
        const int y = 0xFD + i * 0x3F;
        Add(esi - 0x2C, 1, y);
        Add(esi, 0x66, y);
        Add(esi - 0x84, 0xCB, y);
        Add(esi - 0x58, 0x130, y);
    }
    for (int i = 0; i < 6; ++i) {                               // 0x4535FA: pods, x 0x1A2 += 0x65, slot (~i & 1) + i/2*2
        const int idx = ((~i) & 1) + (i / 2) * 2;
        Add(0x77AFF8 + idx * 44, 0x1A2 + i * 0x65, 0x17B);
    }
    g_sheet = 1;                                                // TER1WRECK.PCX, 0x4524A8..0x452B8C
    const struct { uintptr_t va; int x, y; } wreck[] = {
        {0x776994, 0x01A, 0x015}, {0x776910, 0x07F, 0x015}, {0x7769C0, 0x0E4, 0x015}, {0x776860, 0x01A, 0x054},
        {0x77688C, 0x07F, 0x054}, {0x7768B8, 0x0E4, 0x054}, {0x776834, 0x01A, 0x093}, {0x776758, 0x07F, 0x093},
        {0x776784, 0x0E4, 0x093}, {0x776808, 0x01A, 0x0D2}, {0x7767DC, 0x07F, 0x0D2}, {0x7767B0, 0x0E4, 0x0D2},
        {0x776968, 0x01A, 0x111}, {0x7768E4, 0x07F, 0x111}, {0x77693C, 0x0E4, 0x111}, {0x799658, 0x149, 0x093},
        {0x799684, 0x1AE, 0x093}, {0x7996B0, 0x149, 0x0D2}, {0x7996DC, 0x1AE, 0x0D2}, {0x7ACE4C, 0x149, 0x015},
        {0x7ACD70, 0x1AE, 0x015}, {0x7ACD9C, 0x213, 0x015}, {0x7ACE20, 0x149, 0x054}, {0x7ACDF4, 0x1AE, 0x054},
        {0x7ACDC8, 0x213, 0x054},
    };
    for (const auto& w : wreck) Add(w.va, w.x, w.y);
    g_sheet = 2;                                                // UNITS.PCX, load_units 0x45446C..0x4546B4
    const int cols[10] = {1, 7, 1, 7, 7, 7, 3, 1, 1, 1};
    for (int r = 0; r < 10; ++r)
        for (int c = 0; c < cols[r]; ++c)
            Add(0x7777A0 + 0x2C * ((r + 9) * 8 + c), r == 9 ? 0x2CC : 2 + 0x66 * c, r == 9 ? 0xE9 : 2 + 0x4D * r);
}

typedef int (__thiscall* FExtract2)(void*, void*, int, int, int, int, int, void*);
typedef int (__thiscall* FDraw3)(void*, void*, int, int, int);
typedef int (__thiscall* FDrawDest)(void*, void*, int, int, int, void*);
typedef void (__thiscall* FSpriteClose)(void*);
typedef void (__thiscall* FBufferCtor)(void*);
typedef int (__thiscall* FBufferResize)(void*, int, int, int, int);

FExtract2 g_extract = nullptr;
FDraw3 g_draw3 = nullptr;
FDrawDest g_drawDest = nullptr;
int g_state[kSheets] = {};                              // 0 = not looked for, 1 = a valid pack file, -1 = none / bad
alignas(16) uint8_t g_scratch[kBufSize + 0x80];
bool g_scratchReady = false;
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

// "terrain\ter1_x8.pcx" (relative to the game folder: how the log names it) and its full path
void PackRel(int sheet, char* out, size_t n) { _snprintf_s(out, n, _TRUNCATE, "terrain\\%s_x%d.pcx", kSheetName[sheet], kMaster); }

bool PackPath(int sheet, char* out, size_t n)
{
    char rel[64];
    PackRel(sheet, rel, sizeof rel);
    return _snprintf_s(out, n, _TRUNCATE, "%s%s", g_dir, rel) > 0;
}

// Decode an 8-bit one-plane PCX into a malloc'd w x h index image (free() it). Null on any mismatch.
uint8_t* DecodePcx(const char* path, int wantW, int wantH)
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return nullptr;
    uint8_t hdr[128];
    uint8_t* img = nullptr;
    if (fread(hdr, 1, sizeof hdr, f) == sizeof hdr && hdr[0] == 10 && hdr[2] == 1 && hdr[3] == 8 && hdr[65] == 1) {
        const int w = (hdr[8] | hdr[9] << 8) - (hdr[4] | hdr[5] << 8) + 1;
        const int h = (hdr[10] | hdr[11] << 8) - (hdr[6] | hdr[7] << 8) + 1;
        const int bpl = hdr[66] | hdr[67] << 8;
        if (w == wantW && h == wantH && bpl >= w) {
            img = static_cast<uint8_t*>(malloc(static_cast<size_t>(w) * h));
            uint8_t* line = static_cast<uint8_t*>(malloc(bpl));
            bool ok = img && line;
            for (int y = 0; ok && y < h; ++y) {
                for (int x = 0; ok && x < bpl;) {
                    int c = fgetc(f);
                    if (c == EOF) { ok = false; break; }
                    int run = 1;
                    if ((c & 0xC0) == 0xC0) {
                        run = c & 0x3F;
                        c = fgetc(f);
                        if (c == EOF) { ok = false; break; }
                    }
                    for (; run > 0 && x < bpl; --run) line[x++] = static_cast<uint8_t>(c);
                }
                if (ok) memcpy(img + static_cast<size_t>(y) * w, line, w);
            }
            free(line);
            if (!ok) { free(img); img = nullptr; }
        }
    }
    fclose(f);
    return img;
}

// Whether a sheet has a usable pack (checked once; only the header is read).
bool HasPack(int sheet)
{
    if (g_state[sheet] == 0) {
        g_state[sheet] = -1;
        char path[MAX_PATH], rel[64];
        PackRel(sheet, rel, sizeof rel);
        FILE* f = nullptr;
        if (PackPath(sheet, path, sizeof path) && fopen_s(&f, path, "rb") == 0 && f) {
            uint8_t hdr[128];
            const bool ok = fread(hdr, 1, sizeof hdr, f) == sizeof hdr;
            fclose(f);
            const int w = ok ? (hdr[8] | hdr[9] << 8) - (hdr[4] | hdr[5] << 8) + 1 : 0;
            const int h = ok ? (hdr[10] | hdr[11] << 8) - (hdr[6] | hdr[7] << 8) + 1 : 0;
            if (ok && hdr[0] == 10 && hdr[3] == 8 && hdr[65] == 1 && w == kSheetW * kMaster && h == kSheetH * kMaster)
                g_state[sheet] = 1;
            else
                Log("[objecthd] %s is %dx%d, not an 8-bit %dx%d PCX -> ignored\n", rel, w, h, kSheetW * kMaster,
                    kSheetH * kMaster);
        }
    }
    return g_state[sheet] == 1;
}

void Release(Entry& e)
{
    for (Slot& s : e.slots) {
        if (*reinterpret_cast<void**>(s.spr.raw + 4)) reinterpret_cast<FSpriteClose>(At(kVA_SpriteClose))(&s.spr);
        s = Slot{};
    }
}

Slot* Find(Entry& e, int w, int h)
{
    for (Slot& s : e.slots) if (s.w == w && s.h == h && *reinterpret_cast<void**>(s.spr.raw + 4)) return &s;
    return nullptr;
}

// Cut one object at w x h from the decoded master into its least recently used slot.
bool Cut(Entry& e, const uint8_t* master, int w, int h, const uint8_t* rgbq)
{
    Slot* s = &e.slots[0];
    for (Slot& it : e.slots) if (it.used < s->used) s = &it;
    if (*reinterpret_cast<void**>(s->spr.raw + 4)) reinterpret_cast<FSpriteClose>(At(kVA_SpriteClose))(&s->spr);
    *s = Slot{};
    if (!g_scratchReady) {
        reinterpret_cast<FBufferCtor>(At(kVA_BufferCtor))(g_scratch);
        g_scratchReady = true;
    }
    reinterpret_cast<FBufferResize>(At(kVA_BufferResize))(g_scratch, w, h, 0, 0);
    uint8_t* d = Pixels(g_scratch);
    const int pitch = Field(g_scratch, kBufPitch);
    if (!d || Field(g_scratch, kBufW) != w || pitch < w) return false;
    const int mpitch = kSheetW * kMaster;
    basehd_law::PaletteBoxShrink(master + static_cast<size_t>(e.y) * kMaster * mpitch + e.x * kMaster, kW * kMaster,
                                 kSprH[e.sheet] * kMaster, mpitch, d, w, h, pitch, rgbq);
    if (g_extract(&s->spr, g_scratch, kKey, 0, 0, w, h, nullptr) != 0) return false;
    s->w = w;
    s->h = h;
    s->used = ++g_clock;
    return true;
}

// Decode a sheet's pack, map it the way load_terrain / load_units see their sheet, cut every object of that sheet at
// w x h (the size each of them is drawn at for this scale), free the master.
void CutSheet(int sheet, int w, int h, const uint8_t* rgbq)
{
    char path[MAX_PATH], rel[64];
    if (!PackPath(sheet, path, sizeof path)) return;
    PackRel(sheet, rel, sizeof rel);
    const DWORD t0 = GetTickCount();
    uint8_t* m = DecodePcx(path, kSheetW * kMaster, kSheetH * kMaster);
    if (!m) {
        Log("[objecthd] %s could not be decoded (or no memory) -> stock objects for it\n", rel);
        g_state[sheet] = -1;
        return;
    }
    const size_t n = static_cast<size_t>(kSheetW) * kMaster * kSheetH * kMaster;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t v = static_cast<uint8_t>(m[i] + kLoadShift);              // Buffer_load_pcx(.., 10, 236)
        m[i] = v == kBgIndex || v == kSlabIndex ? static_cast<uint8_t>(kKeyIndex) : v;   // Buffer_change_color x2
    }
    int cut = 0;
    for (int i = 0; i < g_count; ++i)
        if (g_entries[i].sheet == sheet && !Find(g_entries[i], w, h) && Cut(g_entries[i], m, w, h, rgbq)) ++cut;
    free(m);
    Log("[objecthd] %s: %d sprites cut at %dx%d in %lu ms\n", rel, cut, w, h, GetTickCount() - t0);
}

Entry* EntryFor(void* spr)
{
    const uintptr_t va = reinterpret_cast<uintptr_t>(spr);
    const uintptr_t base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr)) - 0x400000;
    for (int i = 0; i < g_count; ++i) if (g_entries[i].va + base == va) return &g_entries[i];
    return nullptr;
}

// The HD copy of spr at the current scale, or null (off, not ours, no pack, odd scale).
Sprite* HdFor(void* spr, void* dst)
{
    if (!g_on) return nullptr;
    Entry* e = EntryFor(spr);
    if (!e || !HasPack(e->sheet)) return nullptr;
    const int32_t n = *reinterpret_cast<int32_t*>(At(kVA_ScaleNum)), d = *reinterpret_cast<int32_t*>(At(kVA_ScaleDen));
    if (n <= 0 || d <= 0) return nullptr;
    int w = 0, h = 0;
    basehd_law::SpriteSize(kW, kSprH[e->sheet], n, d, &w, &h);
    if (w < 1 || h < 1 || w > kW * kMaxScale || h > kSprH[e->sheet] * kMaxScale) return nullptr;
    Slot* s = Find(*e, w, h);
    if (!s) {
        // the colours the art is shown with: the destination's synced table, else the main palette
        uint8_t rgbq[1024];
        const uint8_t* dc = dst ? static_cast<const uint8_t*>(dst) + kBufColors : nullptr;
        bool ok = false;
        if (dc) for (int i = 0; i < 1024 && !ok; ++i) ok = dc[i] != 0;
        if (ok) memcpy(rgbq, dc, sizeof rgbq);
        else {
            const uint8_t* pe = At(kVA_MainPalette);   // PALETTEENTRY (r,g,b,f) -> RGBQUAD (b,g,r,0)
            for (int i = 0; i < 256; ++i) {
                rgbq[i * 4] = pe[i * 4 + 2]; rgbq[i * 4 + 1] = pe[i * 4 + 1]; rgbq[i * 4 + 2] = pe[i * 4]; rgbq[i * 4 + 3] = 0;
            }
        }
        CutSheet(e->sheet, w, h, rgbq);
        s = Find(*e, w, h);
    }
    if (!s) return nullptr;
    s->used = ++g_clock;
    return &s->spr;
}

struct Unscaled {                                     // SCALE_NUM_G = SCALE_DEN_G for one draw (SCALE_DEN_G untouched)
    int32_t* num;
    int32_t n;
    Unscaled() : num(reinterpret_cast<int32_t*>(At(kVA_ScaleNum))), n(*num)
    {
        *num = *reinterpret_cast<int32_t*>(At(kVA_ScaleDen));
    }
    ~Unscaled() { *num = n; }
};

int __fastcall Draw3Hook(void* spr, void* /*edx*/, void* dst, int key, int x, int y)
{
    if (Sprite* hd = HdFor(spr, dst)) { Unscaled one; return g_draw3(hd, dst, key, x, y); }
    return g_draw3(spr, dst, key, x, y);
}

int __fastcall DrawDestHook(void* spr, void* /*edx*/, void* dst, int key, int x, int y, void* table)
{
    if (Sprite* hd = HdFor(spr, dst)) { Unscaled one; return g_drawDest(hd, dst, key, x, y, table); }
    return g_drawDest(spr, dst, key, x, y, table);
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

} // namespace

bool ObjectHdAvailable() { return g_installed; }
int  ObjectHdGet() { return g_on; }

void ObjectHdSet(int on)
{
    on = on ? 1 : 0;
    if (!g_installed || on == g_on) return;
    g_on = on;
    if (!on) for (int i = 0; i < g_count; ++i) Release(g_entries[i]);   // stock again: the HD sprites are not needed
    reinterpret_cast<void(__cdecl*)(int)>(At(kVA_DrawMap))(1);
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
    char ini[MAX_PATH], pack[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "ObjectHD", kObjectHdDefault, ini) != 0 ? 1 : 0;
    bool any = false;
    for (int s = 0; s < kSheets; ++s)
        any = any || (PackPath(s, pack, sizeof pack) && GetFileAttributesA(pack) != INVALID_FILE_ATTRIBUTES);
    if (!any) return;                                  // no pack: nothing patched, no Preferences row

    for (uint32_t site : kExtractSites) {
        if (!CallsTo(site, kVA_Extract2)) {
            Log("[objecthd] unexpected bytes at sprite cut %X -> HD objects NOT installed\n", site);
            return;
        }
    }
    // Every Sprite_blit_scaled_core / Sprite_draw_dest call in MapWin_gen_terrain_poly, found by scanning for E8 rel32.
    uint32_t d3[32], dd[8];
    int n3 = 0, nd = 0;
    for (uint32_t va = kFnLo; va + 5 <= kFnHi; ++va) {
        if (At(va)[0] != 0xE8) continue;
        if (CallsTo(va, kVA_Draw3) && n3 < 32) d3[n3++] = va;
        else if (CallsTo(va, kVA_DrawDest) && nd < 8) dd[nd++] = va;
    }
    if (n3 != kDraw3Calls || nd != kDrawDestCalls) {
        Log("[objecthd] found %d + %d draw calls in the terrain pass, expected %d + %d -> HD objects NOT installed\n",
            n3, nd, kDraw3Calls, kDrawDestCalls);
        return;
    }
    BuildTable();
    g_extract = reinterpret_cast<FExtract2>(At(kVA_Extract2));
    g_draw3 = reinterpret_cast<FDraw3>(At(kVA_Draw3));
    g_drawDest = reinterpret_cast<FDrawDest>(At(kVA_DrawDest));
    for (int i = 0; i < n3; ++i) Retarget(d3[i], reinterpret_cast<const void*>(&Draw3Hook));
    for (int i = 0; i < nd; ++i) Retarget(dd[i], reinterpret_cast<const void*>(&DrawDestHook));
    if (CallsTo(kUnitDrawSite, kVA_DrawDest)) Retarget(kUnitDrawSite, reinterpret_cast<const void*>(&DrawDestHook));
    else Log("[objecthd] unexpected bytes at native-unit draw %X -> HD native units off\n", kUnitDrawSite);
    g_installed = true;
    Log("[objecthd] installed: %d TER1 / TER1WRECK / UNITS sprites from terrain\\*_x%d.pcx (%d + %d draw sites), %s\n",
        g_count, kMaster, n3, nd, g_on ? "on" : "off ([UIMod] ObjectHD=0)");
}
