// monumenthd.cpp -- the Planetary Monument across the whole screen instead of a 4:3 picture between black bars.
//
// A pack, in <game>\monument\:
//  * monzoom1_<W>x<H>.pcx, monzoom2_<W>x<H>.pcx -- the near view (one milestone large) before / from 5 milestones;
//  * farNN_<W>x<H>.pcx, NN = 00..12 -- the far view (the pyramid), one per stage of monument.flc.
// Any size and shape, 8-bit in the stock monzoom palette (= monument.flc's), the screen where the game draws the
// milestone picture painted index 255. Several shapes of one picture may be present; the one that covers the screen
// is used (a wider one is cropped, never stretched).
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike; symbols in work/symbols/terranx.h):
//  * load_monicons 0x472230 loads monzoom1.pcx (fewer than 5 milestones) or monzoom2.pcx with
//    Buffer_load_pcx(name, 0, 10, 236) @0x47244B, and advances monument.flc once per milestone ([0x7FD634], 14
//    counted as 13).
//  * MonumentWin_draw 0x4736E0 draws the near backdrop into the canvas (+0x444) @0x4737E9 and the far one @0x4760E2:
//    Buffer_copy_4 1:1 in the vanilla exe; in the patched exe the call goes to the mod's Monument resampler (in its
//    .pcave2 section), which draws the 1024x768 art letterboxed at one scale: num/16 = scaling_laws.mon_scale_num,
//    at (lx, ly) = mon_letterbox, every rect by mon_rect. The pictures, text, icons and buttons follow at that layout.
//
// So, after the stock draw, the pack picture is painted over the whole canvas except the milestone screen, scaled so
// its screen lands exactly on mon_rect(screen) -- the mod's own laws, ported here (no read of the mod's private state).
// One uniform scale for both axes; the picture is lined up on the screen's top-left and its width. Resampling is
// photographic (photo_resample.h) into the monzoom colours; the key (index 255, the screen) is never blended into the
// bezel. Where the picture does not reach the canvas edge (the scale is floored: 22/16 at 1080 px, so art made for
// 22.5/16 falls a few % short), a sliver of up to kMirrorMax of the canvas is filled by mirroring the picture's edge;
// a larger gap stays black. At native scale (num <= 16) and in the vanilla exe nothing is painted: the stock Monument
// (or a 1024x768 replacement of monzoom1/2.pcx) shows as it is.
// Levers, three byte-checked E8 retargets, cave-free (work/tests/test_monumenthd_sites.py pins them):
//  * @0x47244B -> LoadHook: remembers which monzoom was loaded (then the stock call).
//  * @0x4737E9 / @0x4760E2 -> NearHook / FarHook: the original call (Buffer_copy_4, or any call into the mod's
//    .pcave2 section), then the pack picture.
// Nothing is patched without a file in monument\. "HD Monument" in Longevity Mod Preferences ([UIMod] MonumentHD)
// switches it; it takes effect the next time the Monument is drawn.

#include "monumenthd.h"
#include "pcx_decode.h"
#include "photo_resample.h"

#include <windows.h>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

void UimodLog(const char* msg);
bool UimodPcave2Range(uintptr_t* lo, uintptr_t* hi);   // prefs.cpp: the patched exe's .pcave2 section

namespace {

// work/symbols/terranx.h
constexpr uintptr_t kVA_LoadPcx    = 0x5D7DE0;   // Buffer_load_pcx: thiscall (Buffer*, name, pal, a4, a5) RET 0x10
constexpr uintptr_t kVA_Copy4      = 0x5DFF00;   // Buffer_copy_4: thiscall (src, dst, sx, sy, dx, dy, w, h) RET 0x1C
constexpr uintptr_t kVA_Milestones = 0x7FD634;   // what load_monicons advances monument.flc by (14 counted as 13)
constexpr uintptr_t kVA_WideFlag   = 0x8A4168;   // g_report_wide_flag: 0 iff ScreenWidth == 800 (the 800x600 layout)
constexpr uint32_t kSiteLoad = 0x47244B;
constexpr uint32_t kSiteNear = 0x4737E9;
constexpr uint32_t kSiteFar  = 0x4760E2;
constexpr RECT kNearScreen{ 213, 202, 813, 562 };   // the milestone picture's rect in the 1024x768 layout
constexpr RECT kFarScreen{ 432, 287, 591, 380 };
constexpr int kFarFrames = 13;

// scaling_laws.py, the Monument laws (mon_scale_num, mon_s, mon_letterbox, mon_rect)
constexpr int kNativeW = 1024, kNativeH = 768, kOrgX = 112, kOrgY = 84, kDen = 16;
constexpr double kMirrorMax = 0.03;              // the largest gap (share of the canvas side) filled by mirroring

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufH = 0x84, kBufPitch = 0x4A8;
constexpr int kRemapBase = 10, kRemapCount = 236;   // Buffer_load_pcx(name, 0, 10, 236): loaded = file + 10
constexpr int kScreenIndex = 255;                // the art's screen (file index)
constexpr uint8_t kSkip = 255;                   // painted-canvas marker: leave the game's pixel (never a dither output)

typedef int (__thiscall* FLoadPcx)(void*, const char*, void*, int, int);
typedef int (__thiscall* FCopy)(void*, void*, int, int, int, int, int, int);

FLoadPcx g_load = nullptr;
FCopy g_near = nullptr, g_far = nullptr;         // what the draw sites called before us
bool g_installed = false;
int g_on = kMonumentHdDefault;
char g_dir[MAX_PATH];
char g_stem[32];                                 // "monzoom1" / "monzoom2": the last near backdrop loaded

struct ArtInfo { char file[64]; int w, h; RECT screen; };   // a pack file and its screen (index 255) box
std::vector<ArtInfo> g_files;                    // read once, at the first draw

struct Cache { char file[64]; int w = 0, h = 0; RECT screen{}; std::vector<uint8_t> px; };
Cache g_nearCache, g_farCache;

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

bool CallTarget(uint32_t site, uintptr_t* target)
{
    const BYTE* p = At(site);
    if (p[0] != 0xE8) return false;
    int32_t rel;
    memcpy(&rel, p + 1, 4);
    *target = reinterpret_cast<uintptr_t>(p) + 5 + rel;
    return true;
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
int Height(void* buf) { const int h = Field(buf, kBufH); return h < 0 ? -h : h; }

// --- the mod's Monument laws ---------------------------------------------------------------------------------------

int MonScaleNum(int w, int h)                    // mon_scale_num = scale_uniform(16, w, h)
{
    return static_cast<long long>(w) * kNativeH > static_cast<long long>(h) * kNativeW ? kDen * h / kNativeH
                                                                                       : kDen * w / kNativeW;
}
int MonS(int v, int num) { return (2 * v * num + kDen - 1) / (2 * kDen); }   // half_down(v * num, 16), v >= 0
RECT MonRect(const RECT& r, int num, int lx, int ly)                         // mon_rect: split rounding
{
    const int ox = lx + MonS(kOrgX, num), oy = ly + MonS(kOrgY, num);
    return RECT{ ox + MonS(r.left - kOrgX, num), oy + MonS(r.top - kOrgY, num), ox + MonS(r.right - kOrgX, num),
                 oy + MonS(r.bottom - kOrgY, num) };
}

// --- the pack ------------------------------------------------------------------------------------------------------

void ScanFiles()
{
    static bool done = false;
    if (done) return;
    done = true;
    char pattern[MAX_PATH];
    _snprintf_s(pattern, sizeof pattern, _TRUNCATE, "%smonument\\*.pcx", g_dir);
    WIN32_FIND_DATAA fd;
    const HANDLE hf = FindFirstFileA(pattern, &fd);
    if (hf == INVALID_HANDLE_VALUE) return;
    do {
        char path[MAX_PATH];
        _snprintf_s(path, sizeof path, _TRUNCATE, "%smonument\\%s", g_dir, fd.cFileName);
        int w = 0, h = 0;
        uint8_t* px = pcx::Decode(path, &w, &h);
        if (!px) {
            Log("[monumenthd] monument\\%s is not an 8-bit PCX -> ignored\n", fd.cFileName);
            continue;
        }
        int x0 = w, y0 = h, x1 = -1, y1 = -1;
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x)
                if (px[static_cast<size_t>(y) * w + x] == kScreenIndex) {
                    if (x < x0) x0 = x;
                    if (x > x1) x1 = x;
                    if (y < y0) y0 = y;
                    if (y > y1) y1 = y;
                }
        free(px);
        if (x1 - x0 < 16 || y1 - y0 < 16) {
            Log("[monumenthd] monument\\%s has no screen (index 255) -> ignored\n", fd.cFileName);
            continue;
        }
        ArtInfo a{};
        strncpy_s(a.file, fd.cFileName, _TRUNCATE);
        a.w = w;
        a.h = h;
        a.screen = RECT{ x0, y0, x1 + 1, y1 + 1 };
        g_files.push_back(a);
    } while (FindNextFileA(hf, &fd));
    FindClose(hf);
    Log("[monumenthd] %u pictures in monument\\\n", static_cast<unsigned>(g_files.size()));
}

// The scale (picture px per canvas px) and the gaps a picture leaves on a cw x ch canvas with its screen on rc.
double Fit(const ArtInfo& a, const RECT& rc, int cw, int ch, double* gapX, double* gapY)
{
    const double f = static_cast<double>(a.screen.right - a.screen.left) / (rc.right - rc.left);
    const double left = rc.left - a.screen.left / f, top = rc.top - a.screen.top / f;
    const double right = left + a.w / f, bottom = top + a.h / f;
    const double gl = left > 0 ? left : 0, gr = right < cw ? cw - right : 0;
    const double gt = top > 0 ? top : 0, gb = bottom < ch ? ch - bottom : 0;
    *gapX = (gl > gr ? gl : gr) / cw;
    *gapY = (gt > gb ? gt : gb) / ch;
    return f;
}

// monument\<stem>_*.pcx that best covers the canvas: the smallest largest gap; ties go to the larger picture.
const ArtInfo* Pick(const char* stem, const RECT& rc, int cw, int ch)
{
    const ArtInfo* best = nullptr;
    double bestGap = 1e9;
    const size_t n = strlen(stem);
    for (const ArtInfo& a : g_files) {
        if (_strnicmp(a.file, stem, n) != 0 || a.file[n] != '_') continue;
        double gx = 0, gy = 0;
        Fit(a, rc, cw, ch, &gx, &gy);
        const double gap = gx > gy ? gx : gy;
        if (!best || gap < bestGap - 1e-6 ||
            (gap < bestGap + 1e-6 && static_cast<long long>(a.w) * a.h > static_cast<long long>(best->w) * best->h)) {
            best = &a;
            bestGap = gap;
        }
    }
    return best;
}

// The picture over a cw x ch canvas, its screen on rc (canvas indices; kSkip = leave the game's pixel).
bool Paint(const ArtInfo& a, const RECT& rc, int cw, int ch, std::vector<uint8_t>& out)
{
    char path[MAX_PATH];
    _snprintf_s(path, sizeof path, _TRUNCATE, "%smonument\\%s", g_dir, a.file);
    int w = 0, h = 0;
    uint8_t pal[768];
    uint8_t* px = pcx::Decode(path, &w, &h, pal);
    if (!px) return false;
    photo::Target t;
    photo::Build(t, pal, kRemapBase, kRemapCount);
    double gx = 0, gy = 0;
    const double f = Fit(a, rc, cw, ch, &gx, &gy);
    const photo::Edge edge = gx <= kMirrorMax && gy <= kMirrorMax ? photo::Edge::Mirror : photo::Edge::Black;
    out.assign(static_cast<size_t>(cw) * ch, kSkip);
    photo::Resample(px, w, h, w, pal, kScreenIndex, a.screen.left - rc.left * f, a.screen.top - rc.top * f, f,
                    out.data(), cw, ch, cw, t, kSkip, edge);
    free(px);
    if (edge == photo::Edge::Black && (gx > 0 || gy > 0)) {
        // outside the picture reads as see-through (the key path) -- make those pixels black, not the game's
        const uint8_t black = t.lut[0];
        const double left = rc.left - a.screen.left / f, top = rc.top - a.screen.top / f;
        for (int y = 0; y < ch; ++y)
            for (int x = 0; x < cw; ++x) {
                const double sx = (x - left) * f, sy = (y - top) * f;
                if (sx < 0 || sy < 0 || sx >= w || sy >= h) out[static_cast<size_t>(y) * cw + x] = black;
            }
    }
    return true;
}

// After the original draw: the pack picture `stem` over the canvas, lined up on `native`'s screen.
void Overpaint(Cache& cache, const char* stem, const RECT& native, void* dst)
{
    if (!g_on || !dst || !stem[0] || *reinterpret_cast<int*>(At(kVA_WideFlag)) == 0) return;
    uint8_t* px = Pixels(dst);
    const int cw = Field(dst, kBufW), ch = Height(dst), pitch = Field(dst, kBufPitch);
    if (!px || cw <= 0 || ch <= 0) return;
    const int num = MonScaleNum(cw, ch);
    if (num <= kDen) return;                                       // native scale: the stock Monument as it is
    const int lx = (cw - MonS(kNativeW, num)) >> 1, ly = (ch - MonS(kNativeH, num)) >> 1;   // mon_letterbox
    const RECT rc = MonRect(native, num, lx, ly);
    if (rc.left < 0 || rc.top < 0 || rc.right > cw || rc.bottom > ch || rc.right - rc.left < 16) return;
    ScanFiles();
    const ArtInfo* a = Pick(stem, rc, cw, ch);
    if (!a) return;
    if (cache.w != cw || cache.h != ch || memcmp(&cache.screen, &rc, sizeof rc) != 0 || strcmp(cache.file, a->file) != 0) {
        const DWORD t0 = GetTickCount();
        if (!Paint(*a, rc, cw, ch, cache.px)) return;
        cache.w = cw;
        cache.h = ch;
        cache.screen = rc;
        strncpy_s(cache.file, a->file, _TRUNCATE);
        Log("[monumenthd] monument\\%s over the %dx%d canvas (scale %d/16), screen at (%ld,%ld)-(%ld,%ld), %lu ms\n",
            a->file, cw, ch, num, rc.left, rc.top, rc.right, rc.bottom, GetTickCount() - t0);
    }
    // everything but the screen itself, which stays as the game drew it (the milestone picture goes there next)
    for (int y = 0; y < ch; ++y) {
        uint8_t* row = px + static_cast<size_t>(y) * pitch;
        const uint8_t* art = &cache.px[static_cast<size_t>(y) * cw];
        const bool inScreenRows = y >= rc.top && y < rc.bottom;
        for (int x = 0; x < cw; ++x) {
            if (inScreenRows && x >= rc.left && x < rc.right) { x = rc.right - 1; continue; }
            if (art[x] != kSkip) row[x] = art[x];
        }
    }
}

// --- hooks ------------------------------------------------------------------------------------------------------

// Stands in for Buffer_load_pcx at load_monicons' monzoom site: same contract (thiscall, RET 0x10).
int __fastcall LoadHook(void* buf, void* /*edx*/, const char* name, void* pal, int a4, int a5)
{
    g_stem[0] = 0;
    if (name) {
        const char* base = name;
        for (const char* p = name; *p; ++p) if (*p == '\\' || *p == '/' || *p == ':') base = p + 1;
        strncpy_s(g_stem, base, _TRUNCATE);
        if (char* dot = strrchr(g_stem, '.')) *dot = 0;
    }
    return g_load(buf, name, pal, a4, a5);
}

// Stand in for the near / far backdrop draws in MonumentWin_draw: same contract (thiscall, RET 0x1C).
int __fastcall NearHook(void* src, void* /*edx*/, void* dst, int sx, int sy, int dx, int dy, int w, int h)
{
    const int rc = g_near(src, dst, sx, sy, dx, dy, w, h);
    Overpaint(g_nearCache, g_stem, kNearScreen, dst);
    return rc;
}

int __fastcall FarHook(void* src, void* /*edx*/, void* dst, int sx, int sy, int dx, int dy, int w, int h)
{
    const int rc = g_far(src, dst, sx, sy, dx, dy, w, h);
    // the stage on show: load_monicons advanced monument.flc once per milestone (14 counted as 13)
    int count = *reinterpret_cast<int*>(At(kVA_Milestones));
    if (count == 14) count = 13;
    int frame = count - 1;
    frame = frame < 0 ? 0 : (frame >= kFarFrames ? kFarFrames - 1 : frame);
    char stem[16];
    _snprintf_s(stem, sizeof stem, _TRUNCATE, "far%02d", frame);
    Overpaint(g_farCache, stem, kFarScreen, dst);
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

// A backdrop draw site's target: Buffer_copy_4 (vanilla) or a call into the mod's .pcave2 section (its resampler).
bool DrawTarget(uint32_t site, uintptr_t* target, bool* inCave)
{
    if (!CallTarget(site, target)) return false;
    uintptr_t lo = 0, hi = 0;
    *inCave = UimodPcave2Range(&lo, &hi) && *target >= lo && *target < hi;
    return *inCave || *target == reinterpret_cast<uintptr_t>(At(kVA_Copy4));
}

} // namespace

bool MonumentHdAvailable() { return g_installed; }
int  MonumentHdGet() { return g_on; }

void MonumentHdSet(int on)
{
    g_on = on ? 1 : 0;
    if (!g_on) {                                                   // the painted canvases are not needed
        g_nearCache = Cache{};
        g_farCache = Cache{};
    }
}

void MonumentHdSave()
{
    if (!g_installed) return;
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "MonumentHD", g_on ? "1" : "0", ini);
}

void InstallMonumentHd()
{
    if (!GameDir(g_dir, sizeof g_dir)) return;
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "MonumentHD", kMonumentHdDefault, ini) != 0 ? 1 : 0;
    char pattern[MAX_PATH];
    WIN32_FIND_DATAA fd;
    if (_snprintf_s(pattern, sizeof pattern, _TRUNCATE, "%smonument\\*.pcx", g_dir) <= 0) return;
    const HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return;           // no pack: nothing patched, no Preferences row
    FindClose(h);

    uintptr_t loadT = 0, nearT = 0, farT = 0;
    bool nearCave = false, farCave = false;
    if (!CallTarget(kSiteLoad, &loadT) || loadT != reinterpret_cast<uintptr_t>(At(kVA_LoadPcx))) {
        Log("[monumenthd] unexpected bytes at load call %X -> HD Monument NOT installed\n", kSiteLoad);
        return;
    }
    if (!DrawTarget(kSiteNear, &nearT, &nearCave) || !DrawTarget(kSiteFar, &farT, &farCave)) {
        Log("[monumenthd] unexpected bytes at a backdrop draw (%X / %X) -> HD Monument NOT installed\n", kSiteNear, kSiteFar);
        return;
    }
    if (!nearCave || !farCave) {                     // the vanilla exe: the Monument stays native; nothing to paint
        Log("[monumenthd] the Monument is not scaled in this exe -> HD Monument not installed (the stock one shows)\n");
        return;
    }
    g_load = reinterpret_cast<FLoadPcx>(At(kVA_LoadPcx));
    g_near = reinterpret_cast<FCopy>(nearT);
    g_far = reinterpret_cast<FCopy>(farT);
    Retarget(kSiteLoad, reinterpret_cast<const void*>(&LoadHook));
    Retarget(kSiteNear, reinterpret_cast<const void*>(&NearHook));
    Retarget(kSiteFar, reinterpret_cast<const void*>(&FarHook));
    g_installed = true;
    Log("[monumenthd] installed: near + far backdrops from monument\\ (3 sites), %s\n",
        g_on ? "on" : "off ([UIMod] MonumentHD=0)");
}
