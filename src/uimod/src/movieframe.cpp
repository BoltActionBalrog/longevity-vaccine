// Movie frame: the cinematics play inside a picture instead of filling the screen with black bars.
//
// The movies are small (400x192 project clips, 320x240 faction clips, 592x288 opening); a frame picture -- e.g. the
// Planetary Monument's near view with the movie on its screen -- gives the rest of the screen something to show. The
// picture marks its screen with pure magenta; the movie is fitted into that area (movie.cpp), and the post-movie
// caption follows it (its layout is relative to the movie's rectangle). The movie's size therefore comes from the
// frame picture, not from the screen: a player who installs a frame chooses that look, and "Movie Frame" in
// Longevity Mod Preferences switches it back to the full-screen fit.
//
// Files: <game>\movies\frame\*.png / *.jpg / *.bmp, any size. The one closest to the screen's shape is used, scaled
// to cover the screen (centred crop of at most kMaxCrop; a shape further off is fitted whole, black around) with
// WIC's high-quality scaler. True colour: the movie player composes 32-bit, so the frame is not bound to the game's
// palette. Decoded once per screen size and kept (w * h * 4 bytes) so later movies start without the decode.

#include "movieframe.h"

#include <wincodec.h>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <new>

void UimodLog(const char* msg);

namespace {

constexpr double kMaxCrop = 0.12;              // the most of the picture's width or height cut away to cover

int g_on = -1;                                 // -1: not read from the ini yet
MovieFrame g_frame;                            // the kept frame, for g_frame.w x g_frame.h (empty: none yet)
bool g_failed = false;                         // the last attempt at this size failed: don't retry every movie
int g_failW = 0, g_failH = 0;

void GameDir(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
}

void IniPath(char* out, size_t n)
{
    GameDir(out, n);
    strcat_s(out, n, "Alpha Centauri.ini");
}

struct ComInit {
    bool undo = false;
    ComInit() { const HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED); undo = SUCCEEDED(hr); }
    ~ComInit() { if (undo) CoUninitialize(); }
};

template <class T> struct Com {
    T* p = nullptr;
    ~Com() { if (p) p->Release(); }
    T** operator&() { return &p; }
    T* operator->() const { return p; }
};

// WIC's factory: the current one, else the Windows 7 one (CLSID_WICImagingFactory names the Windows 8 factory when
// built for Windows 8+; Windows 7 SP1 without the platform update has only the first).
bool Factory(Com<IWICImagingFactory>& f)
{
    return SUCCEEDED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&f))) ||
           SUCCEEDED(CoCreateInstance(CLSID_WICImagingFactory1, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&f)));
}

// The image file's size (frame 0), or false.
bool ImageSize(IWICImagingFactory* f, const wchar_t* path, UINT* w, UINT* h)
{
    Com<IWICBitmapDecoder> dec;
    Com<IWICBitmapFrameDecode> fr;
    return SUCCEEDED(f->CreateDecoderFromFilename(path, nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &dec)) &&
           SUCCEEDED(dec->GetFrame(0, &fr)) && SUCCEEDED(fr->GetSize(w, h)) && *w > 0 && *h > 0;
}

// movies\frame\* closest to w:h in shape (ties: the larger). name: the file name alone, for the log.
bool PickFrame(IWICImagingFactory* f, int w, int h, wchar_t* out, size_t n, wchar_t* name, size_t nn)
{
    char dir[MAX_PATH];
    GameDir(dir, sizeof dir);
    wchar_t wdir[MAX_PATH];
    MultiByteToWideChar(CP_ACP, 0, dir, -1, wdir, MAX_PATH);
    bool found = false;
    double best = 1e9;
    unsigned long long bestArea = 0;
    for (const wchar_t* ext : { L"png", L"jpg", L"bmp" }) {
        wchar_t pattern[MAX_PATH];
        _snwprintf_s(pattern, MAX_PATH, _TRUNCATE, L"%lsmovies\\frame\\*.%ls", wdir, ext);
        WIN32_FIND_DATAW fd;
        const HANDLE hf = FindFirstFileW(pattern, &fd);
        if (hf == INVALID_HANDLE_VALUE) continue;
        do {
            wchar_t path[MAX_PATH];
            UINT iw = 0, ih = 0;
            _snwprintf_s(path, MAX_PATH, _TRUNCATE, L"%lsmovies\\frame\\%ls", wdir, fd.cFileName);
            if (!ImageSize(f, path, &iw, &ih)) continue;
            const double d = std::fabs(std::log(static_cast<double>(iw) / ih * h / w));
            const unsigned long long area = static_cast<unsigned long long>(iw) * ih;
            if (d < best - 1e-6 || (d < best + 1e-6 && area > bestArea)) {
                best = d;
                bestArea = area;
                wcsncpy_s(out, n, path, _TRUNCATE);
                wcsncpy_s(name, nn, fd.cFileName, _TRUNCATE);
                found = true;
            }
        } while (FindNextFileW(hf, &fd));
        FindClose(hf);
    }
    return found;
}

// The magenta screen: the bounding box of the pure-magenta pixels (which are painted black). False if none.
bool FindScreen(std::vector<uint32_t>& px, int w, int h, RECT* r)
{
    int x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (int y = 0; y < h; ++y) {
        uint32_t* row = &px[static_cast<size_t>(y) * w];
        for (int x = 0; x < w; ++x) {
            const uint32_t c = row[x];                  // BGRA in memory: 0xAARRGGBB
            const int R = c >> 16 & 0xFF, G = c >> 8 & 0xFF, B = c & 0xFF;
            if (R >= 200 && B >= 200 && G <= 60) {
                row[x] = 0xFF000000;
                if (x < x0) x0 = x;
                if (x > x1) x1 = x;
                if (y < y0) y0 = y;
                if (y > y1) y1 = y;
            }
        }
    }
    if (x1 < x0 || y1 < y0 || (x1 - x0) < 16 || (y1 - y0) < 16) return false;
    *r = RECT{ x0, y0, x1 + 1, y1 + 1 };
    // A scaled picture blends the magenta into the bezel: a few pixels around the screen that are still magenta-
    // tinted (red and blue well above green) go black too, so no pink line rims the screen.
    constexpr int kBand = 4;
    for (int y = (y0 - kBand < 0 ? 0 : y0 - kBand); y <= y1 + kBand && y < h; ++y) {
        uint32_t* row = &px[static_cast<size_t>(y) * w];
        for (int x = (x0 - kBand < 0 ? 0 : x0 - kBand); x <= x1 + kBand && x < w; ++x) {
            const int R = row[x] >> 16 & 0xFF, G = row[x] >> 8 & 0xFF, B = row[x] & 0xFF;
            if (R - G > 40 && B - G > 40) row[x] = 0xFF000000;
        }
    }
    return true;
}

void Fail(const char* why, int w, int h)
{
    char line[256];
    _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] movie frame: %s -> black bars\n", why);
    UimodLog(line);
    g_failed = true;
    g_failW = w;
    g_failH = h;
}

bool Decode(int w, int h)
{
    ComInit com;
    Com<IWICImagingFactory> f;
    if (!Factory(f)) { Fail("no WIC imaging factory", w, h); return false; }
    wchar_t path[MAX_PATH], name[MAX_PATH];
    if (!PickFrame(f.p, w, h, path, MAX_PATH, name, MAX_PATH)) return false;

    const DWORD t0 = GetTickCount();
    Com<IWICBitmapDecoder> dec;
    Com<IWICBitmapFrameDecode> fr;
    Com<IWICFormatConverter> conv;
    Com<IWICBitmapScaler> sc;
    UINT iw = 0, ih = 0;
    if (FAILED(f->CreateDecoderFromFilename(path, nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &dec)) ||
        FAILED(dec->GetFrame(0, &fr)) || FAILED(fr->GetSize(&iw, &ih)) ||
        FAILED(f->CreateFormatConverter(&conv)) ||
        FAILED(conv->Initialize(fr.p, GUID_WICPixelFormat32bppBGRA, WICBitmapDitherTypeNone, nullptr, 0,
                                WICBitmapPaletteTypeCustom))) {
        Fail("could not decode the picture", w, h);
        return false;
    }
    // Cover the screen (centred crop) when that cuts at most kMaxCrop of the picture; else fit it whole, black around.
    const double cover = static_cast<double>(w) / iw > static_cast<double>(h) / ih ? static_cast<double>(w) / iw
                                                                                   : static_cast<double>(h) / ih;
    const double fit = static_cast<double>(w) / iw < static_cast<double>(h) / ih ? static_cast<double>(w) / iw
                                                                                 : static_cast<double>(h) / ih;
    const double cropShare = 1.0 - fit / cover;
    const double s = cropShare <= kMaxCrop ? cover : fit;
    const UINT sw = static_cast<UINT>(iw * s + 0.5), sh = static_cast<UINT>(ih * s + 0.5);
    if (sw == 0 || sh == 0 || FAILED(f->CreateBitmapScaler(&sc)) ||
        FAILED(sc->Initialize(conv.p, sw, sh, (sw == iw && sh == ih) ? WICBitmapInterpolationModeNearestNeighbor
                                                                       : WICBitmapInterpolationModeFant))) {
        Fail("could not scale the picture", w, h);
        return false;
    }
    MovieFrame fresh;
    try {
        fresh.px.assign(static_cast<size_t>(w) * h, 0xFF000000);
    } catch (const std::bad_alloc&) {               // the movie player's crash guard covers delay-load errors only
        Fail("not enough memory for the frame", w, h);
        return false;
    }
    fresh.w = w;
    fresh.h = h;
    // the scaled picture's overlap with the screen, centred both ways
    const int cw = static_cast<int>(sw) < w ? static_cast<int>(sw) : w;
    const int ch = static_cast<int>(sh) < h ? static_cast<int>(sh) : h;
    const WICRect crop{ static_cast<INT>((static_cast<int>(sw) - cw) / 2), static_cast<INT>((static_cast<int>(sh) - ch) / 2), cw, ch };
    uint32_t* dstTopLeft = fresh.px.data() + static_cast<size_t>((h - ch) / 2) * w + (w - cw) / 2;
    if (FAILED(sc->CopyPixels(&crop, static_cast<UINT>(w) * 4,
                              static_cast<UINT>((fresh.px.size() - (dstTopLeft - fresh.px.data())) * 4),
                              reinterpret_cast<BYTE*>(dstTopLeft)))) {
        Fail("could not read the picture", w, h);
        return false;
    }
    if (!FindScreen(fresh.px, w, h, &fresh.screen)) {
        Fail("the picture has no magenta (255,0,255) screen area", w, h);
        return false;
    }
    g_frame = std::move(fresh);
    char line[MAX_PATH + 160];
    _snprintf_s(line, sizeof line, _TRUNCATE,
                "[uimod] movie frame: movies\\frame\\%ls at %dx%d (%s), screen %ldx%ld at (%ld,%ld), %lu ms\n", name, w, h,
                s == cover ? "cover" : "fit", g_frame.screen.right - g_frame.screen.left,
                g_frame.screen.bottom - g_frame.screen.top, g_frame.screen.left, g_frame.screen.top, GetTickCount() - t0);
    UimodLog(line);
    return true;
}

} // namespace

bool MovieFrameAvailable()
{
    char dir[MAX_PATH], pattern[MAX_PATH];
    GameDir(dir, sizeof dir);
    for (const char* ext : { "png", "jpg", "bmp" }) {
        _snprintf_s(pattern, sizeof pattern, _TRUNCATE, "%smovies\\frame\\*.%s", dir, ext);
        WIN32_FIND_DATAA fd;
        const HANDLE h = FindFirstFileA(pattern, &fd);
        if (h != INVALID_HANDLE_VALUE) { FindClose(h); return true; }
    }
    return false;
}

int MovieFrameGet()
{
    if (g_on < 0) {
        char ini[MAX_PATH];
        IniPath(ini, sizeof ini);
        g_on = GetPrivateProfileIntA("UIMod", "MovieFrame", kMovieFrameDefault, ini) != 0 ? 1 : 0;
    }
    return g_on;
}

void MovieFrameSet(int on)
{
    g_on = on ? 1 : 0;
    if (!g_on) { g_frame = MovieFrame{}; g_failed = false; }   // the kept frame is not needed
}

void MovieFrameSave()
{
    char ini[MAX_PATH];
    IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "MovieFrame", MovieFrameGet() ? "1" : "0", ini);
}

const MovieFrame* LoadMovieFrame(int w, int h)
{
    if (w <= 0 || h <= 0 || !MovieFrameGet()) return nullptr;
    if (g_frame.w == w && g_frame.h == h && !g_frame.px.empty()) return &g_frame;
    if (g_failed && g_failW == w && g_failH == h) return nullptr;
    g_frame = MovieFrame{};
    return Decode(w, h) ? &g_frame : nullptr;
}

RECT MovieFrameFit(const MovieFrame& f, int clipW, int clipH)
{
    const int sw = f.screen.right - f.screen.left, sh = f.screen.bottom - f.screen.top;
    double s = static_cast<double>(sw) / clipW;
    if (static_cast<double>(sh) / clipH < s) s = static_cast<double>(sh) / clipH;
    const int dw = static_cast<int>(clipW * s), dh = static_cast<int>(clipH * s);
    const int dx = f.screen.left + (sw - dw) / 2, dy = f.screen.top + (sh - dh) / 2;
    return RECT{ dx, dy, dx + dw, dy + dh };
}
