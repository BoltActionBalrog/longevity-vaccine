// menuhd.cpp -- the HD main menu and planet setup at any resolution, by one uniform scale.
//
// A pack is <game>\menu\hd\ (layout: smac-hd art spec, scaling_laws.menu_hd_layout):
//   space_x3.pcx            the panorama, 2400 x 768 stock units at 3x: the stock opening's left part (logo, suns,
//                           copyright) at its stock positions, then starfield
//   S#L#C#_x3.pcx (27)      custom_planet's planet strips (404 x 768) at 3x
//   moon1..3_x3.pcx         custom_planet's erosive-forces moons (450 x 450) at 3x, key 255 as in the stock files
// All 8-bit; colours are read from each file's own palette. Only space_x3.pcx is required: a strip or moon without
// an HD file is drawn from the stock file by the same law.
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike; symbols in work/symbols/terranx.h):
//  * change_opening 0x589A30 (cdecl, the pcx name) loads the opening (xopeninga.pcx) into a local Buffer with
//    Buffer_load_pcx(name, 0, 10, 236) @0x589AA1 and stretches it over the whole TopMenuWin (0x945824, canvas +0x444)
//    with Buffer_copy_3 0x5D9610 @0x589AE8 = GDI StretchBlt: anamorphic on a wide screen, and shrinking ANDs the
//    indices of the dropped rows (dashes).
//  * custom_planet 0x58C2A0 (Start Game > Customize) loads its previews with Buffer_load_pcx (6 sites, 0x58C44F..
//    0x58C6B7) -- S#L#C#.PCX strips, MOON1..3.PCX -- into SetupWin deco[3] (+0xA1C; x +0xA28, y +0xA34), and
//    SetupWin_draw_item 0x4AE4D0 (5 callers) draws the highlighted item's one into the TopMenuWin canvas and
//    GraphicWin_soft_update's it. The stock strip IS the stock opening's planet (S3L2C2 ~= its columns 620..1023).
//
// So the menu is composed, not stretched: the panorama left-aligned and the strip right-aligned, both at one scale
// num/den (menuhd_law::MenuLayout: height-bound on screens at least 4:3 wide, else width-bound with the 4:3 core
// centred, black bands). The main menu shows S3L2C2; custom_planet's previews are drawn at the same place by the same
// law, so every step lines up at any size. Resampling is photographic: each pixel the area-weighted average colour
// of the source pixels it covers, Floyd-Steinberg-dithered into the opening's own colours (loaded indices 10..245);
// a moon pixel stays see-through when more than half its footprint is the key.
// Levers, all byte-checked E8 retargets, cave-free (work/tests/test_menuhd_sites.py pins them):
//  * @0x589AA1 -> LoadHook: records which opening is loading, then the stock load.
//  * @0x589AE8 -> CopyHook: for xopeninga.pcx with a pack, the composed menu is copied 1:1 instead of the stretch.
//  * the 6 custom_planet loads -> PlanetLoadHook: records which preview each Buffer holds.
//  * the 5 SetupWin_draw_item calls -> DrawItemHook: on a composed menu, the highlighted item's preview slot is
//    emptied for the stock draw (so neither the stock blit nor a patched one runs) and the HD preview is drawn and
//    soft-updated here instead.
// SMAC's own opening (openinga.pcx) and 800-wide screens (the b pictures, another layout) stay stock.
// Nothing is patched without menu\hd\space_x3.pcx. "HD Main Menu" in Longevity Mod Preferences ([UIMod] MenuHD)
// switches it; it takes effect the next time the menu is drawn.

#include "menuhd.h"
#include "menuhd_law.h"
#include "pcx_decode.h"

#include <windows.h>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

void UimodLog(const char* msg);

namespace {

// work/symbols/terranx.h
constexpr uintptr_t kVA_LoadPcx      = 0x5D7DE0;   // Buffer_load_pcx: thiscall (Buffer*, name, pal, a4, a5) RET 0x10
constexpr uintptr_t kVA_Copy3        = 0x5D9610;   // Buffer_copy_3: thiscall (src, dst, sx, sy, sw, sh, dx, dy, dw, dh) RET 0x24
constexpr uintptr_t kVA_Draw2        = 0x5D84C0;   // Buffer_draw_2: thiscall (src, dst, key, x, y, num, den) RET 0x18 (keyed)
constexpr uintptr_t kVA_DrawItem     = 0x4AE4D0;   // SetupWin_draw_item: thiscall (SetupWin*, item, highlighted) RET 8
constexpr uintptr_t kVA_SoftUpdate   = 0x5D5720;   // GraphicWin_soft_update: thiscall (win, x, y, w, h) RET 0x10
constexpr uintptr_t kVA_BufferCtor   = 0x5D7210;
constexpr uintptr_t kVA_BufferResize = 0x5D7670;
constexpr uintptr_t kVA_TopMenuWin   = 0x945824;   // TopMenuWin* (GraphicWin; canvas Buffer at +0x444)
constexpr uintptr_t kVA_ScreenWidth  = 0x9B7B1C;
constexpr uint32_t kSiteLoad = 0x589AA1;
constexpr uint32_t kSiteCopy = 0x589AE8;
constexpr uint32_t kDrawItemSites[] = {0x4AE0D7, 0x4AE3B6, 0x4AE3C9, 0x4AE43A, 0x4AE44A};
constexpr uint32_t kPlanetLoadSites[] = {0x58C44F, 0x58C4D1, 0x58C4F8, 0x58C51F, 0x58C5DB, 0x58C6B7};
constexpr int kDecoOfs = 0xA1C;                     // SetupWin +0xA1C struct Buffer* deco[3]
constexpr int kCanvasOfs = 0x444;

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufH = 0x84, kBufPitch = 0x4A8, kBufSize = 0x588;
constexpr int kRemapBase = 10, kRemapCount = 236;   // Buffer_load_pcx(name, 0, 10, 236): loaded = file + 10
constexpr int kKeyLoaded = 9;                       // the engine's transparency key (file 255 -> 9)
constexpr int kArt = 3;                             // the pack's scale: one stock pixel = 3 x 3
constexpr int kPanoUnits = 2400, kMoonUnits = 450;
constexpr int kNarrowWidth = 800;                   // ScreenWidth 800: the b pictures and another layout -> stock

typedef int (__thiscall* FLoadPcx)(void*, const char*, void*, int, int);
typedef int (__thiscall* FCopy3)(void*, void*, int, int, int, int, int, int, int, int);
typedef int (__thiscall* FDraw2)(void*, void*, int, int, int, int, int);
typedef int (__thiscall* FDrawItem)(void*, int, int);
typedef int (__thiscall* FSoftUpdate)(void*, int, int, int, int);
typedef void (__thiscall* FBufferCtor)(void*);
typedef int (__thiscall* FBufferResize)(void*, int, int, int, int);

FLoadPcx g_load = nullptr;
FCopy3 g_copy = nullptr;
FDrawItem g_drawItem = nullptr;
bool g_installed = false;
int g_on = kMenuHdDefault;
char g_dir[MAX_PATH];
char g_opening[MAX_PATH];                            // the opening change_opening is loading (as passed)
bool g_composed = false;                             // the opening on screen is our composition

struct Loaded { void* buf; char stem[16]; };        // custom_planet's preview Buffers and what they hold
Loaded g_loaded[12];
int g_loadedNext = 0;

uint8_t g_rgb[256][3];                               // canvas index -> colour (the opening's palette, loaded)
char g_rgbFrom[MAX_PATH];
std::vector<uint8_t> g_lut;                          // 5-bit RGB -> nearest canvas index in 10..245
uint8_t g_black = kRemapBase;

std::vector<uint8_t> g_menu;                         // the composed main menu (canvas indices), for g_menuW x g_menuH
int g_menuW = 0, g_menuH = 0;
struct Cached { char stem[16]; int w, h; std::vector<uint8_t> px; unsigned used; };
Cached g_cache[4];                                   // previews at their drawn size (LRU)
unsigned g_clock = 0;
alignas(16) uint8_t g_scratch[kBufSize + 0x80];
bool g_scratchReady = false;

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

// "C:\...\S1L2C3.PCX" -> "S1L2C3" (upper case)
void Stem(const char* name, char* out, size_t n)
{
    const char* base = name;
    for (const char* p = name; *p; ++p) if (*p == '\\' || *p == '/' || *p == ':') base = p + 1;
    strncpy_s(out, n, base, _TRUNCATE);
    if (char* dot = strrchr(out, '.')) *dot = 0;
    for (char* p = out; *p; ++p) if (*p >= 'a' && *p <= 'z') *p = static_cast<char>(*p - 'a' + 'A');
}

bool IsStrip(const char* s)
{
    return strlen(s) == 6 && s[0] == 'S' && s[2] == 'L' && s[4] == 'C' && s[1] >= '1' && s[1] <= '3' &&
           s[3] >= '1' && s[3] <= '3' && s[5] >= '1' && s[5] <= '3';
}

bool IsMoon(const char* s) { return strlen(s) == 5 && strncmp(s, "MOON", 4) == 0 && s[4] >= '1' && s[4] <= '3'; }

void HdPath(const char* file, char* out, size_t n) { _snprintf_s(out, n, _TRUNCATE, "%smenu\\hd\\%s", g_dir, file); }

bool Exists(const char* path) { return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES; }

// The canvas colours: the opening's own palette as Buffer_load_pcx(.., 10, 236) maps it, and the 5-bit lookup.
bool LoadColours()
{
    char path[MAX_PATH];
    _snprintf_s(path, sizeof path, _TRUNCATE, "%s%s", g_dir, "xopeninga.pcx");
    if (!g_lut.empty() && strcmp(g_rgbFrom, path) == 0) return true;
    int w = 0, h = 0;
    uint8_t pal[768];
    uint8_t* px = pcx::Decode(path, &w, &h, pal);
    if (!px) return false;
    free(px);
    memset(g_rgb, 0, sizeof g_rgb);
    for (int i = 0; i < kRemapCount; ++i)
        for (int c = 0; c < 3; ++c) g_rgb[kRemapBase + i][c] = pal[i * 3 + c];
    g_lut.assign(32 * 32 * 32, 0);
    for (int i = 0; i < 32 * 32 * 32; ++i) {
        const int r = (i >> 10) * 255 / 31, g = (i >> 5 & 31) * 255 / 31, b = (i & 31) * 255 / 31;
        int best = kRemapBase, bestD = 1 << 30;
        for (int v = kRemapBase; v < kRemapBase + kRemapCount; ++v) {
            const int dr = r - g_rgb[v][0], dg = g - g_rgb[v][1], db = b - g_rgb[v][2];
            const int d = 2 * dr * dr + 4 * dg * dg + 3 * db * db;
            if (d < bestD) { bestD = d; best = v; }
        }
        g_lut[i] = static_cast<uint8_t>(best);
    }
    g_black = g_lut[0];
    strncpy_s(g_rgbFrom, path, _TRUNCATE);
    return true;
}

// Resample the source rect starting at (sx, sy) -- f source pixels per destination pixel on both axes (uniform) --
// into dst (dw x dh, row pitch dp, canvas indices): area-weighted average colour + Floyd-Steinberg into the canvas
// colours. key >= 0: source pixels of that index are see-through; a destination pixel more than half see-through
// becomes kKeyLoaded. Source pixels outside the image count as see-through when key >= 0, else as black.
void Resample(const uint8_t* src, int sw, int sh, const uint8_t* pal, int key, double sx, double sy, double f,
              uint8_t* dst, int dw, int dh, int dp)
{
    std::vector<float> err(static_cast<size_t>(dw + 2) * 3 * 2, 0.0f);
    float* cur = err.data();
    float* nxt = cur + (dw + 2) * 3;
    for (int y = 0; y < dh; ++y) {
        const double y0 = sy + y * f, y1 = y0 + f;
        for (int x = 0; x < dw; ++x) {
            const double x0 = sx + x * f, x1 = x0 + f;
            double acc[3] = {0, 0, 0}, wsum = 0, keyw = 0;
            for (int yy = static_cast<int>(y0); yy < y1; ++yy) {
                const double wy = (yy + 1 < y1 ? yy + 1 : y1) - (yy > y0 ? yy : y0);
                if (wy <= 0) continue;
                for (int xx = static_cast<int>(x0); xx < x1; ++xx) {
                    const double wx = (xx + 1 < x1 ? xx + 1 : x1) - (xx > x0 ? xx : x0);
                    if (wx <= 0) continue;
                    const double wgt = wx * wy;
                    if (xx < 0 || yy < 0 || xx >= sw || yy >= sh) {
                        if (key >= 0) keyw += wgt;
                        else wsum += wgt;                         // black
                        continue;
                    }
                    const int v = src[static_cast<size_t>(yy) * sw + xx];
                    if (v == key) { keyw += wgt; continue; }
                    acc[0] += wgt * pal[v * 3];
                    acc[1] += wgt * pal[v * 3 + 1];
                    acc[2] += wgt * pal[v * 3 + 2];
                    wsum += wgt;
                }
            }
            uint8_t& out = dst[static_cast<size_t>(y) * dp + x];
            if (key >= 0 && keyw > wsum) {
                out = kKeyLoaded;
                continue;
            }
            float c[3];
            for (int i = 0; i < 3; ++i) {
                float v = static_cast<float>(wsum > 0 ? acc[i] / wsum : 0) + cur[(x + 1) * 3 + i];
                c[i] = v < 0 ? 0 : v > 255 ? 255 : v;
            }
            const int r = static_cast<int>(c[0] + 0.5f), g = static_cast<int>(c[1] + 0.5f), b = static_cast<int>(c[2] + 0.5f);
            const uint8_t idx = g_lut[(r >> 3) << 10 | (g >> 3) << 5 | (b >> 3)];
            out = idx;
            for (int i = 0; i < 3; ++i) {
                const float e = c[i] - g_rgb[idx][i];
                cur[(x + 2) * 3 + i] += e * 7 / 16;
                nxt[x * 3 + i] += e * 3 / 16;
                nxt[(x + 1) * 3 + i] += e * 5 / 16;
                nxt[(x + 2) * 3 + i] += e * 1 / 16;
            }
        }
        float* t = cur;
        cur = nxt;
        nxt = t;
        memset(nxt, 0, sizeof(float) * (dw + 2) * 3);
    }
}

// A preview (S#L#C# strip or MOON#) at dw x dh into dst: the HD file at 3x, else the stock file at 1x, by the law's
// scale num/den. False if neither decodes.
bool DrawPreview(const char* stem, int num, int den, uint8_t* dst, int dw, int dh, int dp)
{
    const bool moon = IsMoon(stem);
    char file[64], path[MAX_PATH];
    _snprintf_s(file, sizeof file, _TRUNCATE, "%s_x%d.pcx", stem, kArt);
    HdPath(file, path, sizeof path);
    int scale = kArt;
    if (!Exists(path)) {
        _snprintf_s(path, sizeof path, _TRUNCATE, "%s%s.pcx", g_dir, stem);
        scale = 1;
    }
    int w = 0, h = 0;
    uint8_t pal[768];
    uint8_t* px = pcx::Decode(path, &w, &h, pal);
    if (!px) return false;
    Resample(px, w, h, pal, moon ? 255 : -1, 0, 0, static_cast<double>(scale) * den / num, dst, dw, dh, dp);
    free(px);
    return true;
}

// The main menu at w x h: the panorama left-aligned, S3L2C2 right-aligned, black bands on narrow screens.
bool ComposeMenu(int w, int h)
{
    if (g_menuW == w && g_menuH == h && !g_menu.empty()) return true;
    const DWORD t0 = GetTickCount();
    const menuhd_law::Layout L = menuhd_law::MenuLayout(w, h);
    char path[MAX_PATH];
    HdPath("space_x3.pcx", path, sizeof path);
    int pw = 0, ph = 0;
    uint8_t pal[768];
    uint8_t* pano = pcx::Decode(path, &pw, &ph, pal);
    if (!pano) {
        Log("[menuhd] menu\\hd\\space_x3.pcx could not be decoded -> stock menu\n");
        return false;
    }
    g_menu.assign(static_cast<size_t>(w) * h, g_black);
    uint8_t* core = g_menu.data() + static_cast<size_t>(L.y0) * w;
    Resample(pano, pw, ph, pal, -1, 0, 0, static_cast<double>(kArt) * L.den / L.num, core, L.stripX, L.coreH, w);
    free(pano);
    if (!DrawPreview("S3L2C2", L.num, L.den, core + L.stripX, L.stripW, L.coreH, w))
        Log("[menuhd] no planet strip S3L2C2 -> the menu shows the panorama only\n");
    g_menuW = w;
    g_menuH = h;
    Log("[menuhd] main menu composed at %dx%d (scale %d/%d) in %lu ms\n", w, h, L.num, L.den, GetTickCount() - t0);
    return true;
}

void* Scratch(int w, int h)
{
    if (!g_scratchReady) {
        reinterpret_cast<FBufferCtor>(At(kVA_BufferCtor))(g_scratch);
        g_scratchReady = true;
    }
    reinterpret_cast<FBufferResize>(At(kVA_BufferResize))(g_scratch, w, h, 0, 0);
    if (Field(g_scratch, kBufW) != w || !Pixels(g_scratch) || Field(g_scratch, kBufPitch) < w) return nullptr;
    return g_scratch;
}

void ToScratch(const uint8_t* px, int w, int h)
{
    uint8_t* d = Pixels(g_scratch);
    const int pitch = Field(g_scratch, kBufPitch);
    for (int y = 0; y < h; ++y) memcpy(d + static_cast<size_t>(y) * pitch, px + static_cast<size_t>(y) * w, w);
}

bool Active() { return g_installed && g_on && *reinterpret_cast<int*>(At(kVA_ScreenWidth)) != kNarrowWidth; }

// --- hooks ------------------------------------------------------------------------------------------------------

// Stands in for Buffer_load_pcx at change_opening's site: records the opening's name, then the stock load.
int __fastcall LoadHook(void* buf, void* /*edx*/, const char* name, void* pal, int a4, int a5)
{
    strncpy_s(g_opening, name ? name : "", _TRUNCATE);
    return g_load(buf, name, pal, a4, a5);
}

// Stands in for Buffer_copy_3 at change_opening's stretch: the composed menu, copied 1:1, for xopeninga.pcx.
int __fastcall CopyHook(void* src, void* /*edx*/, void* dst, int sx, int sy, int sw, int sh, int dx, int dy, int dw,
                        int dh)
{
    char stem[64];
    Stem(g_opening, stem, sizeof stem);
    g_composed = false;
    if (Active() && strcmp(stem, "XOPENINGA") == 0 && dw > 0 && dh > 0 && LoadColours() && ComposeMenu(dw, dh) &&
        Scratch(dw, dh)) {
        ToScratch(g_menu.data(), dw, dh);
        g_composed = true;
        return g_copy(g_scratch, dst, 0, 0, dw, dh, dx, dy, dw, dh);
    }
    return g_copy(src, dst, sx, sy, sw, sh, dx, dy, dw, dh);
}

// Stands in for Buffer_load_pcx at custom_planet's preview loads: the stock load, then which preview the Buffer holds.
int __fastcall PlanetLoadHook(void* buf, void* /*edx*/, const char* name, void* pal, int a4, int a5)
{
    const int rc = g_load(buf, name, pal, a4, a5);
    Loaded* slot = nullptr;
    for (Loaded& l : g_loaded) if (l.buf == buf) slot = &l;
    if (!slot) {
        slot = &g_loaded[g_loadedNext];
        g_loadedNext = (g_loadedNext + 1) % static_cast<int>(sizeof g_loaded / sizeof g_loaded[0]);
    }
    slot->buf = buf;
    Stem(name ? name : "", slot->stem, sizeof slot->stem);
    return rc;
}

const char* PreviewOf(void* buf)
{
    for (const Loaded& l : g_loaded) if (l.buf == buf && (IsStrip(l.stem) || IsMoon(l.stem))) return l.stem;
    return nullptr;
}

// Draw one preview into the TopMenuWin canvas where the law puts it, and present that rect.
void PaintPreview(const char* stem)
{
    uint8_t* win = *reinterpret_cast<uint8_t**>(At(kVA_TopMenuWin));
    if (!win || !LoadColours()) return;
    void* canvas = win + kCanvasOfs;
    const int w = Field(canvas, kBufW), h = Field(canvas, kBufH) < 0 ? -Field(canvas, kBufH) : Field(canvas, kBufH);
    if (w <= 0 || h <= 0) return;
    const menuhd_law::Layout L = menuhd_law::MenuLayout(w, h);
    const bool moon = IsMoon(stem);
    const int rw = moon ? kMoonUnits * L.num / L.den : L.stripW;
    const int rh = moon ? kMoonUnits * L.num / L.den : L.coreH;
    const int rx = moon ? 0 : L.stripX, ry = L.y0;
    Cached* c = nullptr;
    for (Cached& it : g_cache) if (strcmp(it.stem, stem) == 0 && it.w == rw && it.h == rh) c = &it;
    if (!c) {
        c = &g_cache[0];
        for (Cached& it : g_cache) if (it.used < c->used) c = &it;
        c->px.assign(static_cast<size_t>(rw) * rh, kKeyLoaded);
        if (!DrawPreview(stem, L.num, L.den, c->px.data(), rw, rh, rw)) { c->stem[0] = 0; return; }
        strncpy_s(c->stem, stem, _TRUNCATE);
        c->w = rw;
        c->h = rh;
    }
    c->used = ++g_clock;
    if (!Scratch(rw, rh)) return;
    ToScratch(c->px.data(), rw, rh);
    if (moon) reinterpret_cast<FDraw2>(At(kVA_Draw2))(g_scratch, canvas, kKeyLoaded, rx, ry, 1, 1);
    else g_copy(g_scratch, canvas, 0, 0, rw, rh, rx, ry, rw, rh);
    reinterpret_cast<FSoftUpdate>(At(kVA_SoftUpdate))(win, rx, ry, rw, rh);
}

// Stands in for SetupWin_draw_item at its 5 callers: same contract (thiscall, RET 8).
int __fastcall DrawItemHook(void* self, void* /*edx*/, int item, int highlighted)
{
    if (!g_composed || !Active() || !highlighted) return g_drawItem(self, item, highlighted);
    const int k = item < 0 ? 0 : item > 2 ? 2 : item;               // the engine's own clamp
    void** slot = reinterpret_cast<void**>(static_cast<uint8_t*>(self) + kDecoOfs) + k;
    void* deco = *slot;
    const char* stem = deco ? PreviewOf(deco) : nullptr;
    if (!stem) return g_drawItem(self, item, highlighted);
    *slot = nullptr;                                                 // no stock (or patched) preview blit
    const int rc = g_drawItem(self, item, highlighted);
    *slot = deco;
    PaintPreview(stem);
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

} // namespace

bool MenuHdAvailable() { return g_installed; }
int  MenuHdGet() { return g_on; }
void MenuHdSet(int on) { g_on = on ? 1 : 0; }     // the next change_opening / preview draw follows it

void MenuHdSave()
{
    if (!g_installed) return;
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "MenuHD", g_on ? "1" : "0", ini);
}

void InstallMenuHd()
{
    if (!GameDir(g_dir, sizeof g_dir)) return;
    char ini[MAX_PATH], pano[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "MenuHD", kMenuHdDefault, ini) != 0 ? 1 : 0;
    HdPath("space_x3.pcx", pano, sizeof pano);
    int w = 0, h = 0;
    if (!Exists(pano)) return;                                       // no pack: nothing patched, no Preferences row
    if (!pcx::Size(pano, &w, &h) || w != kPanoUnits * kArt || h != menuhd_law::kMenuH * kArt) {
        Log("[menuhd] menu\\hd\\space_x3.pcx is %dx%d, not an 8-bit %dx%d PCX -> HD menu NOT installed\n", w, h,
            kPanoUnits * kArt, menuhd_law::kMenuH * kArt);
        return;
    }
    if (!CallsTo(kSiteLoad, kVA_LoadPcx) || !CallsTo(kSiteCopy, kVA_Copy3)) {
        Log("[menuhd] unexpected bytes at change_opening %X / %X -> HD menu NOT installed\n", kSiteLoad, kSiteCopy);
        return;
    }
    for (uint32_t site : kDrawItemSites)
        if (!CallsTo(site, kVA_DrawItem)) {
            Log("[menuhd] unexpected bytes at SetupWin_draw_item call %X -> HD menu NOT installed\n", site);
            return;
        }
    for (uint32_t site : kPlanetLoadSites)
        if (!CallsTo(site, kVA_LoadPcx)) {
            Log("[menuhd] unexpected bytes at custom_planet load %X -> HD menu NOT installed\n", site);
            return;
        }
    g_load = reinterpret_cast<FLoadPcx>(At(kVA_LoadPcx));
    g_copy = reinterpret_cast<FCopy3>(At(kVA_Copy3));
    g_drawItem = reinterpret_cast<FDrawItem>(At(kVA_DrawItem));
    Retarget(kSiteLoad, reinterpret_cast<const void*>(&LoadHook));
    Retarget(kSiteCopy, reinterpret_cast<const void*>(&CopyHook));
    for (uint32_t site : kDrawItemSites) Retarget(site, reinterpret_cast<const void*>(&DrawItemHook));
    for (uint32_t site : kPlanetLoadSites) Retarget(site, reinterpret_cast<const void*>(&PlanetLoadHook));
    g_installed = true;
    Log("[menuhd] installed: HD main menu + planet setup from menu\\hd\\ (13 sites), %s\n",
        g_on ? "on" : "off ([UIMod] MenuHD=0)");
}
