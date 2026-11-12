// objecthd.cpp -- drop-in HD map objects: the monolith, pods, resource specials, terraforming (mines, solar, condensers,
// boreholes, farms, ...), everything load_terrain cuts out of TER1.PCX, and the Unity wreck / canyon pieces it cuts
// out of TER1WRECK.PCX, and the native life / artifact sprites load_units cuts out of UNITS.PCX.
//
// A pack is <game>\terrain\ter1_x8.pcx and/or ter1wreck_x8.pcx: the sheet redrawn at 8x (8192x6144), 8-bit, in the
// STOCK file's palette indices (background 253 and the tile slab 252 stay see-through, as in the stock file).
// TER1WRECK.PCX is loaded and recoloured the same way; its 25 sprites are 25 single Sprite_extract_2 calls
// (0x4524A8..0x452B8C), 100x62, key 0x109.
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike):
//  * load_terrain 0x451C50 loads TER1.PCX into the loading canvas 0x798668 with Buffer_load_pcx(name, 0, 10, 236)
//    (loaded index = file index + 10 mod 256: 252 -> 6, 253 -> 7, 255 -> 9) and cuts 71 sprites of 100x62 with 36
//    Sprite_extract_2 0x5E39A0 calls (0x452C07..0x4536A8, key 0x109), each after Buffer_change_color 0x5DE580
//    (0x107 -> 0x109, 0x106 -> 0x109): the background and the slab become the key. The sprites live at fixed
//    addresses and fixed rects -- kSprites below, read off those calls and their loops.
//  * MapWin_gen_terrain_poly 0x4632D0 draws them with Sprite_draw_3 0x5E4B9A (18 calls) and Sprite_draw_dest
//    0x5E5833 (3 calls), scaled by SCALE_NUM_G / SCALE_DEN_G (0x696D18 / 0x696D1C) like the bases (basehd.cpp):
//    nearest-neighbour skipping, so an 8x sprite must never be shrunk by the engine.
//
// So, as basehd: each object is made at exactly its on-screen size (100*num/den x 62*num/den) from the 8x master
// (DownscaleModeTo: most frequent index per footprint, never blends), cut through the engine's own Sprite_extract_2
// with the stock key, and drawn 1:1, top-left at the same (x, y). Each object keeps its last 4 sizes.
// Levers: the 21 draw calls in MapWin_gen_terrain_poly, byte-checked E8 retargets, cave-free. The extract calls are
// left alone: the table is static, so sprites cut before this module was installed need no adopting. Sprites drawn
// anywhere else (datalink, other screens) stay stock.
// UNITS.PCX (pack terrain\units_x8.pcx): load_units 0x454270 loads it the same way (Buffer_load_pcx(.., 10, 236),
// the same two recolourings) and cuts 36 sprites of 100x75 with ONE Sprite_extract_2 call (@0x454568) in a loop:
// row r = 0..9 at y = 2 + 77r, x = 2 + 102c, columns per row {1,7,1,7,7,7,3,1,1} (row 9 is (0x2CC, 0xE9)), into
// 0x7777A0 + 0x2C * ((r + 9) * 8 + c). The unit drawer draws them (index >= 72) with ONE Sprite_draw_dest @0x5598F9.
// Faction units are voxel models and never touch this.
// Nothing changes without a pack on disk; [UIMod] ObjectHD=0 turns it off with one.

#include "objecthd.h"

#include <windows.h>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <malloc.h>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_Extract2     = 0x5E39A0;   // thiscall (Sprite*, Buffer* src, key, x, y, w, h, a8) RET 0x1C
constexpr uintptr_t kVA_Draw3        = 0x5E4B9A;   // thiscall (Sprite*, Buffer* dst, key, x, y) RET 0x10
constexpr uintptr_t kVA_DrawDest     = 0x5E5833;   // thiscall (Sprite*, Buffer* dst, key, x, y, table) RET 0x14
constexpr uintptr_t kVA_SpriteClose  = 0x5E3820;
constexpr uintptr_t kVA_BufferCtor   = 0x5D7210;
constexpr uintptr_t kVA_BufferDtor   = 0x5D7410;
constexpr uintptr_t kVA_BufferResize = 0x5D7670;
constexpr uintptr_t kVA_LoadPcx      = 0x5D7DE0;
constexpr uintptr_t kVA_ChangeColor  = 0x5DE580;   // thiscall (Buffer*, from, to) RET 8
constexpr uintptr_t kVA_ScaleNum     = 0x696D18;
constexpr uintptr_t kVA_ScaleDen     = 0x696D1C;
constexpr uintptr_t kFnLo = 0x4632D0, kFnHi = 0x466CA0;   // MapWin_gen_terrain_poly

// load_terrain's TER1 cuts: one byte-checked site per pattern, proof that the table below is this exe's.
constexpr uint32_t kExtractSites[] = {0x452C07, 0x452D97, 0x453087, 0x453508, 0x453656, 0x4536A8, 0x4524A8, 0x452B8C,
                                      0x454568};
constexpr uint32_t kUnitDrawSite = 0x5598F9;             // the native-unit Sprite_draw_dest
constexpr int kSheets = 3;
const char* const kSheetName[kSheets] = {"ter1", "ter1wreck", "units"};
constexpr int kSprH[kSheets] = {62, 62, 75};

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufH = 0x84, kBufPitch = 0x4A8, kBufSize = 0x588;
constexpr int kSheetW = 1024, kSheetH = 768, kMaster = 8, kW = 100, kH = 62, kKey = 0x109, kSlots = 4;

struct Sprite { uint8_t raw[0x2C]; };
struct Slot { int w, h; unsigned used; Sprite spr; };
struct Entry { uintptr_t va; int sheet, x, y; Slot slots[kSlots]; };   // sheet: 0 TER1, 1 TER1WRECK, 2 UNITS

Entry g_entries[140];
int g_count = 0;

int g_sheet = 0;
void Add(uintptr_t va, int x, int y) { if (g_count < 140) g_entries[g_count++] = Entry{va, g_sheet, x, y, {}}; }

void BuildTable()
{
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
typedef void (__thiscall* FBufferDtor)(void*);
typedef int (__thiscall* FBufferResize)(void*, int, int, int, int);
typedef int (__thiscall* FLoadPcx)(void*, const char*, void*, int, int);
typedef int (__thiscall* FChangeColor)(void*, int, int);

FExtract2 g_extract = nullptr;
FDraw3 g_draw3 = nullptr;
FDrawDest g_drawDest = nullptr;
uint8_t* g_master[kSheets] = {};                      // Buffers holding ter1_x8.pcx / ter1wreck_x8.pcx / units_x8.pcx
int g_state[kSheets] = {};                                  // 0 = not tried, 1 = loaded, -1 = no / bad file
alignas(16) uint8_t g_scratch[kBufSize + 0x80];
bool g_scratchReady = false;
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

// As basehd: each destination pixel takes the most frequent index under its footprint; never blends.
void DownscaleModeTo(const uint8_t* src, int sw, int sh, int spitch, uint8_t* dst, int dw, int dh, int dpitch)
{
    unsigned count[256] = {};
    uint8_t seen[256];
    for (int ty = 0; ty < dh; ++ty) {
        const int y0 = ty * sh / dh, y1 = (ty + 1) * sh / dh > y0 ? (ty + 1) * sh / dh : y0 + 1;
        for (int tx = 0; tx < dw; ++tx) {
            const int x0 = tx * sw / dw, x1 = (tx + 1) * sw / dw > x0 ? (tx + 1) * sw / dw : x0 + 1;
            int nseen = 0, best = 0;
            unsigned bestCount = 0;
            for (int y = y0; y < y1; ++y) {
                const uint8_t* row = src + y * spitch;
                for (int x = x0; x < x1; ++x) if (count[row[x]]++ == 0) seen[nseen++] = row[x];
            }
            for (int i = 0; i < nseen; ++i) if (count[seen[i]] > bestCount) { bestCount = count[seen[i]]; best = seen[i]; }
            for (int i = 0; i < nseen; ++i) count[seen[i]] = 0;
            dst[ty * dpitch + tx] = static_cast<uint8_t>(best);
        }
    }
}

bool PcxSize(const char* path, int* w, int* h)
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return false;
    uint8_t hdr[128];
    const bool ok = fread(hdr, 1, sizeof hdr, f) == sizeof hdr;
    fclose(f);
    if (!ok || hdr[0] != 10 || hdr[3] != 8 || hdr[65] != 1) return false;
    *w = (hdr[8] | hdr[9] << 8) - (hdr[4] | hdr[5] << 8) + 1;
    *h = (hdr[10] | hdr[11] << 8) - (hdr[6] | hdr[7] << 8) + 1;
    return true;
}

bool LoadMaster(int sheet)
{
    char path[MAX_PATH];
    int w = 0, h = 0;
    g_state[sheet] = -1;
    if (_snprintf_s(path, sizeof path, _TRUNCATE, "%sterrain\\%s_x%d.pcx", g_dir, kSheetName[sheet], kMaster) <= 0) return false;
    if (!PcxSize(path, &w, &h) || w != kSheetW * kMaster || h != kSheetH * kMaster) {
        Log("[objecthd] %s is %dx%d, not an 8-bit %dx%d PCX -> ignored\n", path, w, h, kSheetW * kMaster,
            kSheetH * kMaster);
        return false;
    }
    const DWORD t0 = GetTickCount();
    uint8_t*& m = g_master[sheet];
    m = static_cast<uint8_t*>(_aligned_malloc(kBufSize + 0x80, 16));
    if (!m) return false;
    memset(m, 0, kBufSize + 0x80);
    reinterpret_cast<FBufferCtor>(At(kVA_BufferCtor))(m);
    reinterpret_cast<FLoadPcx>(At(kVA_LoadPcx))(m, path, nullptr, 10, 0xEC);   // load_terrain's arguments
    const int bh = Field(m, kBufH);
    if (Field(m, kBufW) != kSheetW * kMaster || (bh != kSheetH * kMaster && bh != -kSheetH * kMaster) ||
        !Pixels(m)) {
        Log("[objecthd] %s did not load -> HD objects off\n", path);
        reinterpret_cast<FBufferDtor>(At(kVA_BufferDtor))(m);
        _aligned_free(m);
        m = nullptr;
        return false;
    }
    // load_terrain's own recolouring before its cuts: the background and the slab become the key.
    reinterpret_cast<FChangeColor>(At(kVA_ChangeColor))(m, 0x107, 0x109);
    reinterpret_cast<FChangeColor>(At(kVA_ChangeColor))(m, 0x106, 0x109);
    g_state[sheet] = 1;
    Log("[objecthd] loaded %s in %lu ms\n", path, GetTickCount() - t0);
    return true;
}

Entry* Find(void* spr)
{
    const uintptr_t va = reinterpret_cast<uintptr_t>(spr);
    const uintptr_t base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr)) - 0x400000;
    for (int i = 0; i < g_count; ++i) if (g_entries[i].va + base == va) return &g_entries[i];
    return nullptr;
}

Sprite* SpriteAt(Entry* e, int w, int h)
{
    for (Slot& s : e->slots) if (s.w == w && s.h == h) { s.used = ++g_clock; return &s.spr; }
    Slot* s = &e->slots[0];
    for (Slot& it : e->slots) if (it.used < s->used) s = &it;
    if (!g_scratchReady) {
        reinterpret_cast<FBufferCtor>(At(kVA_BufferCtor))(g_scratch);
        g_scratchReady = true;
    }
    reinterpret_cast<FBufferResize>(At(kVA_BufferResize))(g_scratch, w, h, 0, 0);
    uint8_t* d = Pixels(g_scratch);
    const int pitch = Field(g_scratch, kBufPitch);
    if (!d || Field(g_scratch, kBufW) != w || pitch < w) return nullptr;
    const int mpitch = Field(g_master[e->sheet], kBufPitch);
    DownscaleModeTo(Pixels(g_master[e->sheet]) + e->y * kMaster * mpitch + e->x * kMaster, kW * kMaster,
                    kSprH[e->sheet] * kMaster, mpitch,
                    d, w, h, pitch);
    if (*reinterpret_cast<void**>(s->spr.raw + 4)) reinterpret_cast<FSpriteClose>(At(kVA_SpriteClose))(&s->spr);
    *s = Slot{};
    if (g_extract(&s->spr, g_scratch, kKey, 0, 0, w, h, nullptr) != 0) return nullptr;
    s->w = w;
    s->h = h;
    s->used = ++g_clock;
    return &s->spr;
}

// The HD copy of spr at the current scale, or null (not ours, no pack, odd scale).
Sprite* HdFor(void* spr)
{
    Entry* e = Find(spr);
    if (!e) return nullptr;
    if (g_state[e->sheet] == 0) LoadMaster(e->sheet);
    if (g_state[e->sheet] != 1) return nullptr;
    const int32_t n = *reinterpret_cast<int32_t*>(At(kVA_ScaleNum)), d = *reinterpret_cast<int32_t*>(At(kVA_ScaleDen));
    if (n <= 0 || d <= 0) return nullptr;
    const int w = static_cast<int>((static_cast<long long>(kW) * n + d / 2) / d);
    const int sh = kSprH[e->sheet];
    const int h = static_cast<int>((static_cast<long long>(sh) * n + d / 2) / d);
    if (w < 1 || h < 1 || w > kW * kMaster || h > sh * kMaster) return nullptr;
    return SpriteAt(e, w, h);
}

struct OneToOne {                                     // SCALE_NUM_G = SCALE_DEN_G for one draw
    int32_t *num, *den, n, d;
    OneToOne() : num(reinterpret_cast<int32_t*>(At(kVA_ScaleNum))), den(reinterpret_cast<int32_t*>(At(kVA_ScaleDen))),
                 n(*num), d(*den) { *num = *den = 1; }
    ~OneToOne() { *num = n; *den = d; }
};

int __fastcall Draw3Hook(void* spr, void* /*edx*/, void* dst, int key, int x, int y)
{
    if (Sprite* hd = HdFor(spr)) { OneToOne one; return g_draw3(hd, dst, key, x, y); }
    return g_draw3(spr, dst, key, x, y);
}

int __fastcall DrawDestHook(void* spr, void* /*edx*/, void* dst, int key, int x, int y, void* table)
{
    if (Sprite* hd = HdFor(spr)) { OneToOne one; return g_drawDest(hd, dst, key, x, y, table); }
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

} // namespace

void InstallObjectHd()
{
    if (!GameDir(g_dir, sizeof g_dir)) return;
    char ini[MAX_PATH], pack[MAX_PATH];
    if (_snprintf_s(ini, sizeof ini, _TRUNCATE, "%sAlpha Centauri.ini", g_dir) > 0 &&
        GetPrivateProfileIntA("UIMod", "ObjectHD", 1, ini) == 0) {
        UimodLog("[objecthd] off ([UIMod] ObjectHD=0)\n");
        return;
    }
    bool any = false;
    for (const char* name : kSheetName)
        any |= _snprintf_s(pack, sizeof pack, _TRUNCATE, "%sterrain\\%s_x%d.pcx", g_dir, name, kMaster) > 0 &&
               GetFileAttributesA(pack) != INVALID_FILE_ATTRIBUTES;
    if (!any) return;                                  // no pack: nothing patched

    for (uint32_t site : kExtractSites) {
        if (!CallsTo(site, kVA_Extract2)) {
            Log("[objecthd] unexpected bytes at TER1 cut %X -> HD objects NOT installed\n", site);
            return;
        }
    }
    // Every Sprite_draw_3 / Sprite_draw_dest call in MapWin_gen_terrain_poly, found by scanning for E8 rel32.
    uint32_t d3[32], dd[8];
    int n3 = 0, nd = 0;
    for (uint32_t va = kFnLo; va + 5 <= kFnHi; ++va) {
        if (At(va)[0] != 0xE8) continue;
        if (CallsTo(va, kVA_Draw3) && n3 < 32) d3[n3++] = va;
        else if (CallsTo(va, kVA_DrawDest) && nd < 8) dd[nd++] = va;
    }
    if (n3 != 18 || nd != 3) {
        Log("[objecthd] found %d + %d draw calls in the terrain pass, expected 18 + 3 -> HD objects NOT installed\n",
            n3, nd);
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
    Log("[objecthd] installed: %d TER1 / TER1WRECK / UNITS sprites from terrain\\*_x%d.pcx (%d + %d draw sites)\n", g_count,
        kMaster, n3, nd);
}
