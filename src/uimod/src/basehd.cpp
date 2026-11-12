// basehd.cpp -- drop-in HD base sprites: the faction cities on the map, every faction.
//
// A pack is <game>\bases\<faction>_x8.pcx: the base block of <faction>.pcx -- its top-left 404x456 pixels, 6 rows
// (land, land defence 1/2, water, water defence 1/2) x 4 sizes of 100x75 sprites on a 101x76 grid -- redrawn at 8x
// (3232x3648), 8-bit, in the faction file's own palette indices. A pack may cover any subset of the factions; a
// faction without one keeps its stock sprites.
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike; symbols in work/symbols/terranx.h):
//  * load_faction_art 0x453710 loads "<MFactions[f].filename>.pcx" with Buffer_load_pcx(name, 0, 10, 236) and cuts
//    the 24 base sprites with ONE Sprite_extract_2 0x5E39A0 call (@0x453836, 100x75, key 9) into g_faction_sprites
//    0x78E978 (+f*0x65C, index water*12 + size*3 + defence).
//  * base_draw 0x55AF20 sets SCALE_NUM_G / SCALE_DEN_G (0x696D18 / 0x696D1C) and draws the base with ONE
//    Sprite_draw_dest 0x5E5833 call (@0x55B32B). Every caller of base_draw goes through that one call -- the map,
//    the HUD, the base screen, the F-reports, the tutorial -- so the HD art shows wherever the game draws a base,
//    the way a drop-in pack does. Sprite_draw_dest truncates the scaled size (_ftol(w * num/den)) and shrinks by
//    SKIPPING rows and columns: an 8x sprite drawn at 1.5x looked jagged in game.
//
// So the engine never resizes the HD art. For each scale actually drawn, each base sprite is made at exactly the size
// the engine gives the stock sprite (basehd_law::SpriteSize) from the 8x master with basehd_law::PaletteBoxShrink
// (never leaves the palette; keys stay keys), cut through the engine's own Sprite_extract_2 and drawn with
// SCALE_NUM_G = SCALE_DEN_G (Sprite_draw_dest's unscaled branch; SCALE_DEN_G itself is left alone), top-left at the
// same (x, y). Above 8x the same law enlarges the master, so the look never switches back to stock.
// Memory: ONE master buffer for all factions (~12 MB), reloaded only to cut sprites -- every base sprite of that
// faction at the size asked for, in one pass. It is never destroyed: Buffer_dtor -> Buffer_close DeleteObject's the
// GDI objects the buffer holds, and a buffer Buffer_load_pcx filled with no Palette of its own is not known to own
// them; load_faction_art likewise reuses one loading canvas and never destroys it. What else stays is the cut
// sprites, kSlots sizes per sprite.
//
// Levers, both byte-checked E8 retargets, cave-free (work/tests/test_basehd_sites.py pins them):
//  * @0x453836 -> ExtractRecorder: records each base sprite and its rect. The faction comes from the sprite's slot in
//    g_faction_sprites, its file from MFactions[f].filename -- never a scratch string. Sprites cut before this module
//    was installed are placed by their slot at their first draw (Adopt).
//  * @0x55B32B -> DrawHook: a recorded sprite whose faction has a pack is drawn from its exact-size HD copy.
// Nothing is patched without a pack on disk. "HD Base Sprites" in Longevity Mod Preferences ([UIMod] BaseHD) switches
// it live; off draws stock and frees every HD sprite.

#include "basehd.h"
#include "basehd_law.h"

#include <windows.h>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

void UimodLog(const char* msg);

namespace {

// work/symbols/terranx.h
constexpr uintptr_t kVA_Extract2       = 0x5E39A0;   // Sprite_extract_2: thiscall (Sprite*, Buffer* src, key, x, y, w, h, a8) RET 0x1C
constexpr uintptr_t kVA_DrawDest       = 0x5E5833;   // Sprite_draw_dest: thiscall (Sprite*, Buffer* dst, key, x, y, table) RET 0x14
constexpr uintptr_t kVA_SpriteClose    = 0x5E3820;   // Sprite_close: thiscall (Sprite*): frees +0x04 when +0x28 == 0
constexpr uintptr_t kVA_BufferCtor     = 0x5D7210;
constexpr uintptr_t kVA_BufferResize   = 0x5D7670;
constexpr uintptr_t kVA_LoadPcx        = 0x5D7DE0;   // Buffer_load_pcx
constexpr uintptr_t kVA_FactionSprites = 0x78E978;   // g_faction_sprites: 8 x 0x65C, 37 Sprites of 0x2C each
constexpr uintptr_t kVA_MFactions      = 0x946A50;   // MFactions[8], stride 0x59C
constexpr int       kMFactionFilename  = 0x04;       // MFaction +0x04 char filename[24] (the .pcx stem)
constexpr uintptr_t kVA_ScaleNum       = 0x696D18;   // SCALE_NUM_G
constexpr uintptr_t kVA_ScaleDen       = 0x696D1C;   // SCALE_DEN_G
constexpr uintptr_t kVA_MainPalette    = 0x94C590;   // g_main_palette: PALETTEENTRY[256] (fallback colours)
constexpr uintptr_t kVA_DrawMap        = 0x46B190;   // draw_map: cdecl(int) -- full map repaint
constexpr uint32_t kSiteExtract = 0x453836;
constexpr uint32_t kSiteDraw    = 0x55B32B;
constexpr int kFactionStride = 0x65C, kMFactionStride = 0x59C, kSpriteSize = 0x2C;

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufH = 0x84, kBufColors = 0xA4, kBufPitch = 0x4A8;
constexpr int kBufSize = 0x588;
constexpr int kBlockW = 404, kBlockH = 456;          // the base block of a faction pcx (6 rows x 4 sizes)
constexpr int kMaster = 8;
constexpr int kMaxScale = 32;                         // sanity cap: never cut a sprite above 32x its stock size
constexpr int kKey = 9;                               // load_faction_art's key (file 255 -> loaded 9)
constexpr int kSlots = 4;                             // sizes kept per base sprite

struct Sprite { uint8_t raw[0x2C]; };                 // +0x04 data, +0x10/+0x14 w/h, +0x28 owner flag

struct Slot { int w, h; unsigned used; Sprite spr; };

struct Entry {
    void* stock;
    char name[32];                                    // the faction file stem it was cut from, e.g. "UNIV"
    int x, y, w, h;                                   // stock rect in the faction pcx
    Slot slots[kSlots];
};

struct Pack {
    char name[32];
    int state;                                        // 0 = not looked for, 1 = a valid pack file, -1 = none / bad
};

typedef int (__thiscall* FExtract2)(void*, void*, int, int, int, int, int, void*);
typedef int (__thiscall* FDraw)(void*, void*, int, int, int, void*);
typedef void (__thiscall* FSpriteClose)(void*);
typedef void (__thiscall* FBufferCtor)(void*);
typedef int (__thiscall* FBufferResize)(void*, int, int, int, int);
typedef int (__thiscall* FLoadPcx)(void*, const char*, void*, int, int);

FExtract2 g_extract = nullptr;
FDraw g_draw = nullptr;
std::vector<Entry*> g_entries;
std::vector<Pack*> g_packs;
alignas(16) uint8_t g_scratch[kBufSize + 0x80];
bool g_scratchReady = false;
alignas(16) uint8_t g_master[kBufSize + 0x80];      // the one master buffer: constructed once, reloaded, never destroyed
bool g_masterReady = false;
char g_masterStem[32];                                // the faction whose pack g_master holds ("" = none)
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

bool PackPath(const char* stem, char* out, size_t n)
{
    char rel[64];
    PackRel(stem, rel, sizeof rel);
    return _snprintf_s(out, n, _TRUNCATE, "%s%s", g_dir, rel) > 0;
}

bool PcxSize(const char* path, int* w, int* h)
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return false;
    uint8_t hdr[128];
    const bool ok = fread(hdr, 1, sizeof hdr, f) == sizeof hdr;
    fclose(f);
    if (!ok || hdr[0] != 10 || hdr[3] != 8 || hdr[65] != 1) return false;   // 8-bit, one plane
    *w = (hdr[8] | hdr[9] << 8) - (hdr[4] | hdr[5] << 8) + 1;
    *h = (hdr[10] | hdr[11] << 8) - (hdr[6] | hdr[7] << 8) + 1;
    return true;
}

// Whether <stem> has a usable pack (checked once per stem; the file is opened only to read its header).
bool HasPack(const char* stem)
{
    Pack* p = nullptr;
    for (Pack* it : g_packs) if (_stricmp(it->name, stem) == 0) { p = it; break; }
    if (!p) {
        p = new Pack{};
        strncpy_s(p->name, stem, _TRUNCATE);
        g_packs.push_back(p);
    }
    if (p->state == 0) {
        char path[MAX_PATH], rel[64];
        int w = 0, h = 0;
        p->state = -1;
        PackRel(stem, rel, sizeof rel);
        if (PackPath(stem, path, sizeof path) && GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) {
            if (PcxSize(path, &w, &h) && w == kBlockW * kMaster && h == kBlockH * kMaster) p->state = 1;
            else Log("[basehd] %s is %dx%d, not an 8-bit %dx%d PCX -> ignored\n", rel, w, h, kBlockW * kMaster, kBlockH * kMaster);
        }
    }
    return p->state == 1;
}

void Release(Entry* e)
{
    for (Slot& s : e->slots) {
        if (*reinterpret_cast<void**>(s.spr.raw + 4)) reinterpret_cast<FSpriteClose>(At(kVA_SpriteClose))(&s.spr);
        s = Slot{};
    }
}

Slot* Find(Entry* e, int w, int h)
{
    for (Slot& s : e->slots) if (s.w == w && s.h == h && *reinterpret_cast<void**>(s.spr.raw + 4)) return &s;
    return nullptr;
}

// Cut entry e at w x h from the loaded master into its least recently used slot.
bool Cut(Entry* e, void* master, int w, int h, const uint8_t* rgbq)
{
    Slot* s = &e->slots[0];
    for (Slot& it : e->slots) if (it.used < s->used) s = &it;
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
    const int mpitch = Field(master, kBufPitch);
    basehd_law::PaletteBoxShrink(Pixels(master) + e->y * kMaster * mpitch + e->x * kMaster, e->w * kMaster,
                                 e->h * kMaster, mpitch, d, w, h, pitch, rgbq);
    if (g_extract(&s->spr, g_scratch, kKey, 0, 0, w, h, nullptr) != 0) return false;
    s->w = w;
    s->h = h;
    s->used = ++g_clock;
    return true;
}

// Cut every recorded base sprite of <stem> at w x h (the size every base of it is drawn at for this scale) from its
// master, loading the pack into g_master first unless it already holds it. One load per faction switch.
void CutFaction(const char* stem, int w, int h, const uint8_t* rgbq)
{
    char path[MAX_PATH], rel[64];
    if (!PackPath(stem, path, sizeof path)) return;
    PackRel(stem, rel, sizeof rel);
    const DWORD t0 = GetTickCount();
    if (!g_masterReady) {
        reinterpret_cast<FBufferCtor>(At(kVA_BufferCtor))(g_master);
        g_masterReady = true;
    }
    if (_stricmp(g_masterStem, stem) != 0) {
        g_masterStem[0] = 0;
        Log("[basehd] loading %s for %dx%d\n", rel, w, h);
        reinterpret_cast<FLoadPcx>(At(kVA_LoadPcx))(g_master, path, nullptr, 10, 236);   // load_faction_art's arguments
        const int bh = Field(g_master, kBufH);
        if (Field(g_master, kBufW) != kBlockW * kMaster || (bh != kBlockH * kMaster && bh != -kBlockH * kMaster) ||
            !Pixels(g_master)) {
            Log("[basehd] %s did not load as %dx%d -> stock bases for %s\n", rel, kBlockW * kMaster, kBlockH * kMaster, stem);
            for (Pack* p : g_packs) if (_stricmp(p->name, stem) == 0) p->state = -1;
            return;
        }
        strncpy_s(g_masterStem, stem, _TRUNCATE);
    }
    int cut = 0;
    for (Entry* e : g_entries)
        if (_stricmp(e->name, stem) == 0 && !Find(e, w, h) && Cut(e, g_master, w, h, rgbq)) ++cut;
    Log("[basehd] %s: %d sprites cut at %dx%d in %lu ms\n", rel, cut, w, h, GetTickCount() - t0);
}

void ReleaseAll()
{
    for (Entry* e : g_entries) Release(e);
}

// A base sprite load_faction_art cut BEFORE this module was installed (the first game_init can run before uimod's
// Init): placed by its slot -- load_faction_art's own layout (index water*12 + size*3 + defence, rect
// (1 + size*101, 1 + row*76, 100, 75)).
Entry* Adopt(void* spr)
{
    int idx = 0;
    const int f = FactionOf(spr, &idx);
    if (f < 0 || idx >= 24 || !FactionFile(f)[0]) return nullptr;
    const int water = idx / 12, size = idx % 12 / 3, def = idx % 3;
    Entry* e = new Entry{};
    e->stock = spr;
    strncpy_s(e->name, FactionFile(f), _TRUNCATE);
    e->x = 1 + size * 101;
    e->y = 1 + (water * 3 + def) * 76;
    e->w = 100;
    e->h = 75;
    g_entries.push_back(e);
    return e;
}

// --- hooks ------------------------------------------------------------------------------------------------------

// Stands in for Sprite_extract_2 at load_faction_art's base-sprite site: same contract (thiscall, RET 0x1C).
int __fastcall ExtractRecorder(void* spr, void* /*edx*/, void* src, int key, int x, int y, int w, int h, void* a8)
{
    const int rc = g_extract(spr, src, key, x, y, w, h, a8);
    int idx = 0;
    const int f = FactionOf(spr, &idx);
    if (rc != 0 || f < 0 || x < 0 || y < 0 || x + w > kBlockW || y + h > kBlockH) return rc;
    const char* stem = FactionFile(f);
    Entry* e = nullptr;
    for (Entry* it : g_entries) if (it->stock == spr) { e = it; break; }
    if (!e) {
        e = new Entry{};
        e->stock = spr;
        g_entries.push_back(e);
    }
    if (_stricmp(e->name, stem) != 0 || e->x != x || e->y != y || e->w != w || e->h != h) {
        Release(e);                                    // another faction in this slot (a new game)
        strncpy_s(e->name, stem, _TRUNCATE);
        e->x = x; e->y = y; e->w = w; e->h = h;
    }
    return rc;
}

// Stands in for Sprite_draw_dest at base_draw's site: same contract (thiscall, RET 0x14).
int __fastcall DrawHook(void* spr, void* /*edx*/, void* dst, int key, int x, int y, void* table)
{
    if (!g_on) return g_draw(spr, dst, key, x, y, table);
    static bool logged = false;
    if (!logged) {
        logged = true;
        Log("[basehd] first base draw (%zu sprites recorded)\n", g_entries.size());
    }
    Entry* e = nullptr;
    for (Entry* it : g_entries) if (it->stock == spr) { e = it; break; }
    if (!e) e = Adopt(spr);
    int32_t* num = reinterpret_cast<int32_t*>(At(kVA_ScaleNum));
    const int32_t n = *num, d = *reinterpret_cast<int32_t*>(At(kVA_ScaleDen));
    if (e && n > 0 && d > 0 && HasPack(e->name)) {
        int w = 0, h = 0;
        basehd_law::SpriteSize(e->w, e->h, n, d, &w, &h);
        if (w >= 1 && h >= 1 && w <= e->w * kMaxScale && h <= e->h * kMaxScale) {
            Slot* s = Find(e, w, h);
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
                CutFaction(e->name, w, h, rgbq);
                s = Find(e, w, h);
            }
            if (s) {
                s->used = ++g_clock;
                *num = d;                              // Sprite_draw_dest's unscaled branch (num == den): drawn 1:1
                const int rc = g_draw(&s->spr, dst, key, x, y, table);
                *num = n;
                return rc;
            }
        }
    }
    return g_draw(spr, dst, key, x, y, table);
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

bool BaseHdAvailable() { return g_installed; }
int  BaseHdGet() { return g_on; }

void BaseHdSet(int on)
{
    on = on ? 1 : 0;
    if (!g_installed || on == g_on) return;
    g_on = on;
    if (!on) ReleaseAll();                             // stock again: the HD sprites are not needed
    reinterpret_cast<void(__cdecl*)(int)>(At(kVA_DrawMap))(1);
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
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "BaseHD", kBaseHdDefault, ini) != 0 ? 1 : 0;
    char pattern[MAX_PATH];
    WIN32_FIND_DATAA fd;
    if (_snprintf_s(pattern, sizeof pattern, _TRUNCATE, "%sbases\\*_x%d.pcx", g_dir, kMaster) <= 0) return;
    const HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return;             // no pack: nothing patched, no Preferences row
    FindClose(h);

    if (!CallsTo(kSiteExtract, kVA_Extract2)) {
        Log("[basehd] unexpected bytes at extract call %X -> HD bases NOT installed\n", kSiteExtract);
        return;
    }
    if (!CallsTo(kSiteDraw, kVA_DrawDest)) {
        Log("[basehd] unexpected bytes at draw call %X -> HD bases NOT installed\n", kSiteDraw);
        return;
    }
    g_extract = reinterpret_cast<FExtract2>(At(kVA_Extract2));
    g_draw = reinterpret_cast<FDraw>(At(kVA_DrawDest));
    g_entries.reserve(8 * 24);
    Retarget(kSiteExtract, reinterpret_cast<const void*>(&ExtractRecorder));
    Retarget(kSiteDraw, reinterpret_cast<const void*>(&DrawHook));
    g_installed = true;
    Log("[basehd] installed: base sprites from bases\\*_x%d.pcx (extract + draw sites), %s\n", kMaster,
        g_on ? "on" : "off ([UIMod] BaseHD=0)");
}
