// Leader and native-life portraits: smooth enlarge of the game's art, and REPLACEMENT portraits from image files.
//
// 1. Smooth enlarge (since 2026-09-21).  The 8-bit leader portraits (1-px frame, a photo scanlined through the
//    whole image) read blocky under the patcher's scanline re-blits (thunk_parity_reblit / thunk_art_reblit:
//    nearest-neighbour content with even 1-px scanlines).  Here: take the scanlines out, enlarge with a Lanczos-3
//    filter, sharpen lightly, put the scanlines back at DEVICE density and fit to the live palette with error
//    diffusion -- the law is work\scripts\scaling_laws.py `portrait_enlarge`, ported in portrait_law.h (bit-exact,
//    tests\test_portrait_port.py).  [UIMod] SmoothPortraits=0 opts out.
//
//    Both re-blits share one contract (ecx = Sprite-shaped source: data +4, pitch +0xC, w +0x10, h +0x14 (may be
//    negative), draw offsets +0x20/+0x24; stack dest, key, x, y, num, den; RET 0x18) and every portrait draw on
//    the patched exe ends in one of them (diplomacy popup, council, combat console, faction picker, Datalinks).
//    Their entries are detoured; the hook draws PORTRAIT-shaped art (h > w, a real key) itself and hands
//    everything else -- event pictures, the opaque flic path, any guard failure -- back to the original thunk,
//    so the fallback is exactly today's picture.  Results are cached per (pixels, size, ratio, palette).
//
// 2. Replacement portraits (2026-09-30; files and decode: portrait_files.cpp; laws: scaling_laws.py
//    portrait_bake / portrait_enlarge_rgb, ported in portrait_law.h).  A player image in <game>\portraits\ (or
//    the portraits-hd pack in portraits\hd\) replaces a faction's leader portrait or a native-life picture:
//    - LEADERS: load_faction_art (0x453710, cdecl void(int)) cuts each faction's portraits into its 37-sprite
//      block (g_faction_sprites 0x78E978 + f*0x65C; slots +0x478 small council 96x115, +0x4A4 big council
//      118x144, +0x4D0 diplomacy 131x157, +0x554 datalink 164x198; diplomacy / datalink with a 1-px frame, the
//      two council slots unframed).  Its entry is
//      detoured: after the original, each slot's vanilla pixels + scanline parameters are captured (the sprite
//      owns a fresh allocation after every load) and the interior is overwritten with the replacement at native
//      size, dithered into g_main_palette (Phase-0 measured: every portrait dest's table == g_main_palette).
//      That covers every consumer at g <= 16.  At g > 16 PortraitDraw recognises the slot by address and
//      redraws it from the RGB image (EnlargeRgb) -- never from the dithered bake (dither is never resampled).
//    - NATIVE LIFE (BT*.pcx, combat console): filename-backed sprites.  Every draw loads the file into
//      g_sprite_load_scratch and CALLs thunk_art_core (pcave2+0x1CAB0) from the blit core (0x5E4C01).  Its entry
//      is detoured: at num == den the scratch interior is overwritten with the native bake; at num > den the
//      draw is marked, and thunk_art_core's own re-blit through g_art_spr reaches PortraitDraw, which redraws it
//      from the RGB image.  A face with no replacement (or an edit of the game art) is marked too and redrawn
//      with the leaders' Enlarge, so it matches the leader beside it in the combat console (SmoothPortraits).
//    - EVENT PICTURES (*_sm.pcx, the popup art; 2026-10-03) take the same blit-core path with no replacement:
//      thunk_art_core's entry marks the draw and the g_art_spr re-blit redraws it with the field-separated smooth
//      enlarge (law scaling_laws.py art_field_enlarge, port portrait_law::FieldEnlarge) -- portrait_enlarge's
//      one-ratio scanline model bands their flat scanline fields.  [UIMod] SmoothPortraits=0 opts out here too.
//    - An image exactly the slot's size is a player's edit of the game art: kept as is (nearest colour), and
//      enlarged like vanilla art.
//    - Scanlines on replacements: Preferences "Add Scanlines" (PortraitScanMode; always brightness-keeping), with
//      the VANILLA art's own (bright row parity, dark:bright ratio) captured before the first bake.
//
// Every engine entry is byte-checked before it is detoured; a mismatch logs and leaves that path vanilla.
#include "portrait.h"
#include "portrait_files.h"
#include "portrait_law.h"
#include "prefs.h"          // UimodPcave2Range
#include "prewarm.h"

#include <windows.h>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

void UimodLog(const char* msg);
void UimodDbg(const char* msg);   // init.cpp: only with [UIMod] DebugLog=1
bool UimodDebugLogOn();

namespace {

void IniFile(char* ini, size_t n);

// The stripe phase each slot's draw site used ([UIMod] PortraitPrewarmPhases "a,b,c,d", -1 unknown): the next
// launch pre-bakes that phase first.  A measured value remembered, never a setting; a wrong one only costs order.
void ReadHotPhases(int out[prewarm::kSlots])
{
    char ini[MAX_PATH], v[64] = {};
    IniFile(ini, sizeof ini);
    GetPrivateProfileStringA("UIMod", "PortraitPrewarmPhases", "", v, sizeof v, ini);
    prewarm::ParseHotPhases(v, out);
}

void PersistHotPhases()
{
    static int written[prewarm::kSlots] = { -2, -2, -2, -2 };
    int hot[prewarm::kSlots];
    if (!prewarm::HotPhases(hot)) return;     // nothing changed since the last read (lock-free)
    if (written[0] == -2) ReadHotPhases(written);          // what the ini holds now: write only on a real change
    for (int s = 0; s < prewarm::kSlots; ++s) if (hot[s] < 0) hot[s] = written[s];
    bool same = true;
    for (int s = 0; s < prewarm::kSlots; ++s) same = same && hot[s] == written[s];
    memcpy(written, hot, sizeof written);
    if (same) return;
    char ini[MAX_PATH], v[64];
    IniFile(ini, sizeof ini);
    prewarm::FormatHotPhases(hot, v, sizeof v);
    WritePrivateProfileStringA("UIMod", "PortraitPrewarmPhases", v, ini);
}

// The worker's queued log lines, written by the game thread (never by the worker); the remembered draw phases.
void FlushPrewarmLog()
{
    char line[240];
    while (prewarm::TakeLog(line, sizeof line)) UimodLog(line);
    PersistHotPhases();
}


constexpr uintptr_t kOffParityReblit = 0x13360;   // thunk_parity_reblit (council_scale)
constexpr uintptr_t kOffArtReblit    = 0x29C80;   // thunk_art_reblit   (popup_art_reblit)
constexpr uintptr_t kOffArtSpr       = 0x29FC0;   // g_art_spr: the flic / popup-picture scratch VIEW handed to thunk_art_reblit
constexpr uintptr_t kOffArtCore      = 0x1CAB0;   // thunk_art_core: the blit core's filename-backed draw (CALLed @0x5E4C01)
const BYTE kEntry[6] = { 0x55, 0x89, 0xE5, 0x83, 0xEC, 0x50 };   // push ebp / mov ebp,esp / sub esp,0x50
const BYTE kArtCoreEntry[7] = { 0x56, 0x89, 0xCE, 0xFF, 0x74, 0x24, 0x1C };   // push esi / mov esi,ecx / push [esp+1C]
const BYTE kLfaEntry[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x10 };   // load_faction_art: push ebp / mov ebp,esp / sub esp,10
constexpr uintptr_t kVA_LoadFactionArt = 0x00453710;
constexpr uintptr_t kVA_FactionSprites = 0x0078E978;   // g_faction_sprites[8][37]
constexpr int kFactionStride = 0x65C;
constexpr uintptr_t kVA_MFactions = 0x00946A50;        // MFactions[8], stride 0x59C, char filename[24] at +4
constexpr int kMFactionStride = 0x59C, kMFactionFilename = 4;
constexpr uintptr_t kVA_MainPalette = 0x0094C590;      // g_main_palette: PALETTEENTRY[256] (r, g, b, flags)
constexpr uintptr_t kVA_Scratch = 0x009B6080;          // g_sprite_load_scratch (Buffer)
constexpr uintptr_t kVA_ArtCoreRet = 0x005E4C06;       // the blit core's return address after CALL thunk_art_core
constexpr uintptr_t kVA_PopupScaleNum = 0x00668740;    // g_popup_scale_num (16..): the enlarge scale, num/16
constexpr int kBlitCoreNameOfs = -0x40;                // blit core frame: [ebp-0x40] = the sprite's file name
constexpr int kMaxDim = 400;                           // the thunks' own size guard
constexpr size_t kCacheSlots = 24;

BYTE g_trampParity[16], g_trampArt[16], g_trampArtCore[16], g_trampLfa[16];
void* g_trampParityPtr = g_trampParity;
void* g_trampArtPtr = g_trampArt;
void* g_trampArtCorePtr = g_trampArtCore;

struct Entry {
    uint64_t hash = 0;
    int sw = 0, sh = 0, num = 0, den = 0, key = 0, dw = 0, dh = 0;
    unsigned stamp = 0;
    std::vector<int> px;
};
Entry g_cache[kCacheSlots];
const void* g_artSprView = nullptr;               // never a leader portrait (BIOSCAN figure is h > w with key 9)
unsigned g_clock = 0;
bool g_smooth = true;                             // [UIMod] SmoothPortraits (vanilla art only; replacements always draw)
// A native bake may exist only where its enlargement is ours: on a patched exe (cave present) the re-blit hooks
// must be armed, or the patcher's NN / parity re-blit would enlarge the dithered bake (dither is never resampled).
// (g_hasCave / g_b2Armed are defined above, beside MakeSnapshot.)

int g_custom = kPortraitCustomDefault;            // "Enable Custom Portraits" (the group's parent)
int g_hd = kPortraitHdDefault;                    // "Use Turovetsky's HD Portrait Pack" (the portraits\hd\ pack)
int g_scan = kPortraitScanDefault;                // "Add Scanlines"

uint64_t Fnv(uint64_t h, const BYTE* p, size_t n)
{
    for (size_t i = 0; i < n; ++i) { h ^= p[i]; h *= 1099511628211ull; }
    return h;
}

template <typename T> T Rd(const void* base, size_t off)
{
    T v; memcpy(&v, static_cast<const BYTE*>(base) + off, sizeof v); return v;
}

void Logf(const char* fmt, ...)
{
    char msg[400];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(msg, sizeof msg, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(msg);
}

// g_main_palette (PALETTEENTRY r,g,b,f) as the RGBQUAD (b,g,r,x) table the laws read
void GamePalRgbquad(BYTE out[1024])
{
    const BYTE* pe = reinterpret_cast<const BYTE*>(kVA_MainPalette);
    for (int i = 0; i < 256; ++i) {
        out[i * 4] = pe[i * 4 + 2]; out[i * 4 + 1] = pe[i * 4 + 1]; out[i * 4 + 2] = pe[i * 4]; out[i * 4 + 3] = 0;
    }
}

bool g_hasCave = false, g_b2Armed = false;   // (defined below with the hook state; declared here for the snapshot)
int PortraitScanModeInternal();

// Everything the pre-bake reads from the engine, copied on the game thread: the palette (RGBQUAD), g (only with
// our re-blit hooks armed: no enlarges otherwise) and the scan mode.
prewarm::Snapshot MakeSnapshot(const BYTE* pal)
{
    prewarm::Snapshot snap;
    memcpy(snap.pal, pal, sizeof snap.pal);
    snap.g = (g_hasCave && g_b2Armed) ? Rd<int>(reinterpret_cast<const void*>(kVA_PopupScaleNum), 0) : 16;
    if (snap.g < 16 || snap.g > 256) snap.g = 16;   // no enlarges without our re-blit hooks, or on a nonsense value
    snap.scan = PortraitScanModeInternal();
    ReadHotPhases(snap.hot);
    return snap;
}

// ---- replacement state -------------------------------------------------------------------------------------------

struct Replacement {                              // what an enlarged draw needs
    std::shared_ptr<const portrait_files::Image> img;
    int bright = 0, ratio = 256;
    bool framed = true;
};

// framed: a 1-px frame around the picture.  The two COUNCIL slots have none -- their edges are picture (measured on
// the sheets 2026-10-03; keeping them left a ring of the vanilla painting around a replacement).
struct SlotDef { int off, w, h; bool framed; const char* name; };
const SlotDef kSlots[4] = { { 0x478, 96, 115, false, "small council" }, { 0x4A4, 118, 144, false, "big council" },
                            { 0x4D0, 131, 157, true, "diplomacy" }, { 0x554, 164, 198, true, "datalink" } };

// An image exactly the size of ANOTHER slot is an edit of that slot's art (already scanlined and dithered): it is
// used there only, never resampled into the other slots (dither / scanlines are never resampled).
bool NativeArtOfAnotherSlot(int w, int h, int self)
{
    for (int s = 0; s < 4; ++s)
        if (s != self && portrait_law::IsNativeArt(w, h, kSlots[s].w, kSlots[s].h, kSlots[s].framed) &&
            !portrait_law::IsNativeArt(w, h, kSlots[self].w, kSlots[self].h, kSlots[self].framed))
            return true;
    return false;
}

struct SlotState {
    bool valid = false;                           // vanilla captured for the sprite's CURRENT allocation
    const BYTE* data = nullptr;
    int pitch = 0;
    std::vector<BYTE> vanilla;                    // the vanilla pixels, sw*sh packed
    int bright = 0, ratio = 256;
    bool replaced = false;                        // the interior holds a bake
    bool nativeArt = false;                       // the replacement is an edit of the game art (enlarged like vanilla)
    uint64_t bakedHash = 0;                       // the sprite's pixels right after the bake (a failed reload keeps them)
    std::shared_ptr<const portrait_files::Image> img;
};
SlotState g_slots[8][4];
char g_factionName[8][24];

// Native-size bakes, keyed on everything Bake reads: a faction re-load (the picker loads all eight on every open)
// or a Preferences toggle back to an earlier mode costs a lookup, not a Lanczos pass over the source.
struct BakeEntry {
    uint64_t key = 0;
    int w = 0, h = 0;
    std::vector<int> interior;
    unsigned stamp = 0;
};
BakeEntry g_bakes[96];                            // >= 2 modes x 32 slots: toggling back is a hit

// Lanczos results per (image, crop, target size): a scan-mode toggle or a re-bake re-runs only the scanline +
// dither stage (portrait_law::Finish), not the resample of a ~1100x1350 source -- the Preferences click that
// re-bakes 28 slots would otherwise stall the game for about a second (audit 2026-10-03).  Stored as bytes (the
// resampled values are 0..255): 48 entries are ~30 MB even at 4K enlargement sizes.
struct ResampleEntry {
    uint64_t id = 0;
    portrait_law::Rect crop{};
    int tw = 0, th = 0;
    std::vector<uint8_t> px;
    unsigned stamp = 0;
};
ResampleEntry g_resamples[48];

// The DLL's caches behind one law call: the Lanczos pass (g_resamples, this thread's) and, through prewarm, the
// finished result the background pre-bake may hold for the same inputs (a hit is the law's own output; a job
// still running is waited for; a miss runs the stages here and hands the result back so the worker skips it).
struct ImageResampleCache : portrait_law::ResampleCache {
    uint64_t id;
    std::vector<int> scratch;
    explicit ImageResampleCache(uint64_t i) : id(i) {}
    bool GetFit(portrait_law::Rect crop, int tw, int th, const uint8_t* pal, int scan, int bright, int ratio, int y0,
                int rows, std::vector<int>* fit) override
    {
        int why = prewarm::kNotStarted;
        const bool hit = prewarm::GetFit(id, crop, tw, th, pal, scan, bright, ratio, y0, rows, fit, &why);
        if (why != prewarm::kNotStarted && UimodDebugLogOn()) {
            static const char* const kWhy[] = { "hit", "not started", "absent", "queued (taken over)", "running (timed out)", "failed", "discarded" };
            char msg[160];
            _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] portrait: prewarm %s: %dx%d phase %d rows %d scan %d (%d/%d)\n",
                        kWhy[why], tw, th, y0, rows, scan, bright, ratio);
            UimodDbg(msg);
        }
        return hit;
    }
    void PutFit(portrait_law::Rect crop, int tw, int th, const uint8_t* pal, int scan, int bright, int ratio, int y0,
                int rows, const std::vector<int>& fit) override
    {
        prewarm::PutFit(id, crop, tw, th, pal, scan, bright, ratio, y0, rows, fit);
    }
    static bool Same(const ResampleEntry& e, uint64_t id, portrait_law::Rect c, int tw, int th)
    {
        return e.stamp && e.id == id && e.tw == tw && e.th == th && e.crop.x == c.x && e.crop.y == c.y &&
               e.crop.w == c.w && e.crop.h == c.h;
    }
    const std::vector<int>* Get(portrait_law::Rect crop, int tw, int th) override
    {
        for (ResampleEntry& e : g_resamples)
            if (Same(e, id, crop, tw, th)) {
                e.stamp = ++g_clock;
                scratch.assign(e.px.begin(), e.px.end());
                return &scratch;
            }
        return nullptr;
    }
    void Put(portrait_law::Rect crop, int tw, int th, const std::vector<int>& big) override
    {
        ResampleEntry* lru = &g_resamples[0];
        for (ResampleEntry& e : g_resamples) if (e.stamp < lru->stamp) lru = &e;
        lru->id = id; lru->crop = crop; lru->tw = tw; lru->th = th;
        lru->px.assign(big.size(), 0);
        for (size_t i = 0; i < big.size(); ++i) lru->px[i] = static_cast<uint8_t>(big[i]);
        lru->stamp = ++g_clock;
    }
};

uint64_t BakeKey(const portrait_files::Image& img, int w, int h, int mode, int bright, int ratio, bool framed,
                 const BYTE* pal)
{
    uint64_t k = Fnv(1469598103934665603ull, reinterpret_cast<const BYTE*>(&img.id), sizeof img.id);
    const int v[6] = { w, h, mode, bright, ratio, framed ? 1 : 0 };
    k = Fnv(k, reinterpret_cast<const BYTE*>(v), sizeof v);
    return Fnv(k, pal, 1024);
}

// The (cached) native bake -- the interior of framed art, the whole sprite of unframed art -- or null.
const std::vector<int>* CachedBake(const portrait_files::Image& img, int w, int h, int mode, int bright, int ratio,
                                   bool framed, const BYTE* pal)
{
    const uint64_t key = BakeKey(img, w, h, mode, bright, ratio, framed, pal);
    BakeEntry* lru = &g_bakes[0];
    for (BakeEntry& b : g_bakes) {
        if (b.stamp && b.key == key && b.w == w && b.h == h) { b.stamp = ++g_clock; return &b.interior; }
        if (b.stamp < lru->stamp) lru = &b;
    }
    std::vector<int> interior;
    ImageResampleCache rc(img.id);
    if (!portrait_law::Bake(w, h, pal, img.rgb.data(), img.rgb.size(), img.w, img.h, mode, bright, ratio, &interior,
                            framed, &rc))
        return nullptr;
    lru->key = key; lru->w = w; lru->h = h; lru->interior.swap(interior);
    lru->stamp = ++g_clock;
    return &lru->interior;
}

uint64_t PixHash(const BYTE* data, int pitch, int w, int h)
{
    uint64_t hh = 1469598103934665603ull;
    for (int y = 0; y < h; ++y) hh = Fnv(hh, data + static_cast<size_t>(y) * pitch, static_cast<size_t>(w));
    return hh;
}

BYTE* SlotSprite(int f, int s)
{
    return reinterpret_cast<BYTE*>(kVA_FactionSprites + static_cast<uintptr_t>(f) * kFactionStride + kSlots[s].off);
}

// Write the replacement (or the vanilla pixels back) into slot (f, s).  The sprite must still be the captured one.
void BakeSlot(int f, int s)
{
    SlotState& st = g_slots[f][s];
    const SlotDef& d = kSlots[s];
    BYTE* spr = SlotSprite(f, s);
    if (!st.valid || Rd<const BYTE*>(spr, 4) != st.data) { st.valid = false; return; }
    BYTE* px = const_cast<BYTE*>(st.data);
    auto restore = [&]() {
        for (int y = 0; y < d.h; ++y) memcpy(px + static_cast<size_t>(y) * st.pitch, &st.vanilla[static_cast<size_t>(y) * d.w], d.w);
        st.replaced = false; st.nativeArt = false; st.img.reset();
    };
    std::shared_ptr<const portrait_files::Image> img = portrait_files::Find(g_factionName[f]);
    if (!img || NativeArtOfAnotherSlot(img->w, img->h, s)) { restore(); return; }
    BYTE pal[1024];
    GamePalRgbquad(pal);
    const std::vector<int>* interior = CachedBake(*img, d.w, d.h, PortraitScanMode(), st.bright, st.ratio, d.framed, pal);
    if (!interior) { restore(); return; }
    restore();                                    // the frame (and a clean base) from the vanilla capture
    const int o = d.framed ? 1 : 0, iw = d.w - 2 * o, ih = d.h - 2 * o;
    for (int y = 0; y < ih; ++y) {
        BYTE* row = px + static_cast<size_t>(y + o) * st.pitch + o;
        const int* src = &(*interior)[static_cast<size_t>(y) * iw];
        for (int x = 0; x < iw; ++x) row[x] = static_cast<BYTE>(src[x]);
    }
    st.replaced = true;
    st.nativeArt = portrait_law::IsNativeArt(img->w, img->h, d.w, d.h, d.framed);
    st.img = img;
    st.bakedHash = PixHash(st.data, st.pitch, d.w, d.h);
}

void OnFactionArtLoadedInner(int f)
{
    try {
        if (f < 0 || f > 7) return;
        const char* fn = reinterpret_cast<const char*>(kVA_MFactions + static_cast<uintptr_t>(f) * kMFactionStride + kMFactionFilename);
        memcpy(g_factionName[f], fn, 23);
        g_factionName[f][23] = 0;
        BYTE pal[1024];
        GamePalRgbquad(pal);
        // On a patched exe the bake needs our enlargement (g_b2Armed); without it no replacement at all.
        if (g_hasCave && !g_b2Armed) return;
        int baked = 0;
        for (int s = 0; s < 4; ++s) {
            SlotState& st = g_slots[f][s];
            const SlotDef& d = kSlots[s];
            BYTE* spr = SlotSprite(f, s);
            const BYTE* data = Rd<const BYTE*>(spr, 4);
            const int pitch = Rd<int>(spr, 0xC), w = Rd<int>(spr, 0x10);
            int h = Rd<int>(spr, 0x14); if (h < 0) h = -h;
            const int cw = Rd<int>(spr, 0x18), ch = Rd<int>(spr, 0x1C);
            // the expected, untrimmed slot only (a custom sheet's trimmed sprite would make a write an overrun)
            if (!data || w != d.w || h != d.h || cw != d.w || ch != d.h || pitch < w) {
                st.valid = false; st.replaced = false; st.nativeArt = false; st.img.reset();
                continue;
            }
            // A failed sheet load leaves the old allocation and pixels in place (Sprite_init bails before freeing):
            // then those pixels are OUR bake, not vanilla -- keep the earlier capture.
            const bool same = st.valid && st.replaced && data == st.data && pitch == st.pitch &&
                              PixHash(data, pitch, d.w, d.h) == st.bakedHash;
            if (!same) {
                st.vanilla.resize(static_cast<size_t>(d.w) * d.h);
                for (int y = 0; y < d.h; ++y) memcpy(&st.vanilla[static_cast<size_t>(y) * d.w], data + static_cast<size_t>(y) * pitch, d.w);
                portrait_law::ScanlineParams(st.vanilla.data(), d.w, d.w, d.h, pal, &st.bright, &st.ratio);
            }
            st.replaced = false; st.nativeArt = false; st.img.reset();
            st.data = data; st.pitch = pitch; st.valid = true;
            // the measured scanline parameters: the pre-bake's prediction for this file is checked against them
            // (a wrong one re-keys its jobs) BEFORE the bake looks the result up
            if (prewarm::Started()) prewarm::ReportMeasured(g_factionName[f], s, st.bright, st.ratio);
        }
        // The four native bakes, shared with the pre-bake's workers: they go to the front of the queue and idle
        // workers start on them from slot 0 while this thread bakes from slot 3 (a lookup takes over a still-queued
        // job and waits, bounded, on a running one).  Before the pre-bake has the file resolved: all four here.
        if (prewarm::Started()) prewarm::Expedite(g_factionName[f]);
        for (int s = 3; s >= 0; --s) {
            if (!g_slots[f][s].valid) continue;
            BakeSlot(f, s);
            baked += g_slots[f][s].replaced ? 1 : 0;
        }
        static int lastBaked[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };
        if (baked != lastBaked[f]) {
            lastBaked[f] = baked;
            Logf("[uimod] portrait: faction %d (%s): %d of 4 portrait slots replaced\n", f, g_factionName[f], baked);
        }
        // The first faction load is where the palette and g exist (not at Init): snapshot them and start the
        // background pre-bake of every replacement image, this faction's measured parameters first.
        if (!prewarm::Started()) {
            const prewarm::Snapshot snap = MakeSnapshot(pal);
            for (int s = 0; s < 4; ++s)
                if (g_slots[f][s].valid) prewarm::ReportMeasured(g_factionName[f], s, g_slots[f][s].bright, g_slots[f][s].ratio);
            if (prewarm::Start(snap))
                Logf("[uimod] portrait: prewarm started (g=%d, scan mode %d, %d worker%s, %d usable core%s): decode + bake every replacement portrait in the background\n",
                     snap.g, snap.scan, prewarm::Workers(), prewarm::Workers() == 1 ? "" : "s",
                     prewarm::UsableCoreCount(), prewarm::UsableCoreCount() == 1 ? "" : "s");
        }
        FlushPrewarmLog();
    } catch (...) {
    }
}

void OnFactionArtLoaded(int f)
{
    __try { OnFactionArtLoadedInner(f); } __except (EXCEPTION_EXECUTE_HANDLER) { }
}

using FLoadFactionArt = void(__cdecl*)(int);

void __cdecl HookLoadFactionArt(int f)
{
    reinterpret_cast<FLoadFactionArt>(static_cast<void*>(g_trampLfa))(f);
    OnFactionArtLoaded(f);
}

// The slot a sprite address is, if it is a live replaced leader slot (not native-art).
// The replaced leader slot a draw's sprite IS -- matched on its pixel buffer, so a consumer drawing a COPY of the
// slot Sprite (same data, its own struct) is recognised too and never enlarges the dithered bake.
const SlotState* ReplacedSlot(const void* spr, int* sw, int* sh, bool* framed)
{
    const BYTE* data = Rd<const BYTE*>(spr, 4);
    if (!data) return nullptr;
    for (int f = 0; f < 8; ++f)
        for (int s = 0; s < 4; ++s) {
            const SlotState& st = g_slots[f][s];
            if (st.data != data || !st.valid || !st.replaced || st.nativeArt || !st.img) continue;
            if (Rd<int>(spr, 0x10) != kSlots[s].w || (Rd<int>(spr, 0x14) < 0 ? -Rd<int>(spr, 0x14) : Rd<int>(spr, 0x14)) != kSlots[s].h)
                return nullptr;
            *sw = kSlots[s].w; *sh = kSlots[s].h; *framed = kSlots[s].framed;
            return &st;
        }
    return nullptr;
}

// ---- native life ---------------------------------------------------------------------------------------------

struct NativeMark {                               // one marked enlarged draw, consumed by the g_art_spr re-blit
    bool active = false;
    const BYTE* data = nullptr;
    int w = 0, h = 0;
    uint64_t hash = 0;
    Replacement rep;
};
NativeMark g_nat;

struct EventMark {                                // one marked enlarged event-picture draw (*_sm.pcx), same life
    bool active = false;
    bool portrait = false;                        // a native-life face with no replacement: the leaders' Enlarge
    const BYTE* data = nullptr;
    int w = 0, h = 0;
    uint64_t hash = 0;
};
EventMark g_evt;

// Mark the scratch's current pixels for the g_art_spr re-blit (Draw): field enlarge or the portrait Enlarge.
void MarkEvent(const BYTE* scratch, const BYTE* esp, bool portrait)
{
    const BYTE* px = Rd<const BYTE*>(scratch, 0x54);
    const int pitch = Rd<int>(scratch, 0x4A8), w = Rd<int>(scratch, 0x80);
    int h = Rd<int>(scratch, 0x84); if (h < 0) h = -h;
    const int num = Rd<int>(esp, 0x14), den = Rd<int>(esp, 0x18);
    if (!px || w < 3 || h < 3 || w > kMaxDim || h > kMaxDim || pitch < w || den <= 0 || num <= den) return;
    g_evt.data = px; g_evt.w = w; g_evt.h = h; g_evt.hash = PixHash(px, pitch, w, h);
    g_evt.portrait = portrait;
    g_evt.active = true;
}

// "<anything>_sm": the popup event pictures (BaseName has already stripped the directory and .pcx)
bool IsEventPictureName(const char* base)
{
    const size_t n = strlen(base);
    return n > 3 && base[n - 3] == '_' && (base[n - 2] | 0x20) == 's' && (base[n - 1] | 0x20) == 'm';
}

void ArtCorePreInner(const BYTE* scratch, const BYTE* esp, const BYTE* ebp)
{
    try {
        g_nat.active = false;
        g_nat.rep.img.reset();
        g_evt.active = false;
        if (reinterpret_cast<uintptr_t>(scratch) != kVA_Scratch) return;
        if (Rd<uintptr_t>(esp, 0) != kVA_ArtCoreRet) return;           // only the blit core's call: its frame is known
        const char* file = Rd<const char*>(ebp, static_cast<size_t>(static_cast<ptrdiff_t>(kBlitCoreNameOfs)));
        char base[32];
        if (!portrait_files::BaseName(file, base, sizeof base)) return;
        if (IsEventPictureName(base)) {
            if (g_smooth) MarkEvent(scratch, esp, false);
            return;
        }
        if (!portrait_files::IsNativeLifeName(base)) {
            // [UIMod] DebugLog: each other filename-backed picture the blit core enlarges, once -- the census of
            // what still takes the patcher's re-blit (which names belong in IsEventPictureName is measured here)
            static char seen[24][32];
            static int nSeen = 0;
            if (Rd<int>(esp, 0x14) > Rd<int>(esp, 0x18) && nSeen < 24) {
                bool known = false;
                for (int i = 0; i < nSeen; ++i) known = known || _stricmp(seen[i], base) == 0;
                if (!known) {
                    strcpy_s(seen[nSeen++], base);
                    char msg[120];
                    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] portrait: blit core enlarges %s.pcx (patcher re-blit)\n", base);
                    UimodDbg(msg);
                }
            }
            return;
        }
        std::shared_ptr<const portrait_files::Image> img = portrait_files::Find(base);
        if (!img) {                               // the game's own face: smoothed like the leaders beside it
            if (g_smooth) MarkEvent(scratch, esp, true);
            return;
        }
        BYTE* data = Rd<BYTE*>(scratch, 0x54);
        const int pitch = Rd<int>(scratch, 0x4A8), w = Rd<int>(scratch, 0x80);
        int h = Rd<int>(scratch, 0x84); if (h < 0) h = -h;
        if (!data || w < 3 || h < 3 || w > kMaxDim || h > kMaxDim || pitch < w) return;
        const int num = Rd<int>(esp, 0x14), den = Rd<int>(esp, 0x18);
        if (den <= 0 || num < den) return;        // below native: never measured; leave the vanilla picture
        BYTE pal[1024];
        GamePalRgbquad(pal);
        int bright = 0, ratio = 256;
        portrait_law::ScanlineParams(data, pitch, w, h, pal, &bright, &ratio);   // the file is fresh: vanilla pixels
        // enlarged: mark the draw, and the re-blit through g_art_spr redraws it from the image (Draw).  An edit of
        // the game art (exactly its size) is instead baked into the scratch at every scale and enlarged like the
        // art itself.
        if (num > den && !portrait_law::IsNativeArt(img->w, img->h, w, h)) {
            g_nat.data = data; g_nat.w = w; g_nat.h = h; g_nat.hash = PixHash(data, pitch, w, h);
            g_nat.rep.img = img; g_nat.rep.bright = bright; g_nat.rep.ratio = ratio;
            g_nat.active = true;
            return;
        }
        const std::vector<int>* interior = CachedBake(*img, w, h, PortraitScanMode(), bright, ratio, true, pal);
        if (!interior) return;
        for (int y = 0; y < h - 2; ++y) {
            BYTE* row = data + static_cast<size_t>(y + 1) * pitch + 1;
            const int* src = &(*interior)[static_cast<size_t>(y) * (w - 2)];
            for (int x = 0; x < w - 2; ++x) row[x] = static_cast<BYTE>(src[x]);
        }
        if (g_smooth) MarkEvent(scratch, esp, true);   // an edit of the game art, enlarged like the art itself
    } catch (...) {
        g_nat.active = false;
        g_evt.active = false;
    }
}

void __cdecl ArtCorePre(const BYTE* scratch, const BYTE* esp, const BYTE* ebp)
{
    __try { ArtCorePreInner(scratch, esp, ebp); } __except (EXCEPTION_EXECUTE_HANDLER) { g_nat.active = false; g_evt.active = false; }
}

// thiscall(ecx = scratch Buffer; dest, key, x, y, num, den) RET 0x18, CALLed by the blit core: look, then run it.
__declspec(naked) void HookArtCore()
{
    __asm {
        push ecx
        lea eax, [esp + 4]                        // the entry esp: [eax] = return address, [eax+4..] = args
        push ebp
        push eax
        push ecx
        call ArtCorePre
        add esp, 0xC
        pop ecx
        jmp dword ptr [g_trampArtCorePtr]
    }
}

// The marked native-life draw, if `spr` (g_art_spr, the view of the scratch) is it.  One-shot.
bool TakeNativeMark(const void* spr, Replacement* out, int* sw, int* sh)
{
    if (!g_nat.active) return false;
    g_nat.active = false;
    const BYTE* data = Rd<const BYTE*>(spr, 4);
    const int pitch = Rd<int>(spr, 0xC), w = Rd<int>(spr, 0x10);
    int h = Rd<int>(spr, 0x14); if (h < 0) h = -h;
    if (data != g_nat.data || w != g_nat.w || h != g_nat.h || pitch < w) return false;
    if (PixHash(data, pitch, w, h) != g_nat.hash) return false;      // not the picture we looked at
    *out = g_nat.rep;
    g_nat.rep.img.reset();
    *sw = w; *sh = h;
    return true;
}

// The marked event-picture / vanilla native-life draw, if `spr` (g_art_spr) is it.  One-shot.
bool TakeEventMark(const void* spr, bool* portrait)
{
    if (!g_evt.active) return false;
    g_evt.active = false;
    const BYTE* data = Rd<const BYTE*>(spr, 4);
    const int pitch = Rd<int>(spr, 0xC), w = Rd<int>(spr, 0x10);
    int h = Rd<int>(spr, 0x14); if (h < 0) h = -h;
    if (data != g_evt.data || w != g_evt.w || h != g_evt.h || pitch < w) return false;
    if (PixHash(data, pitch, w, h) != g_evt.hash) return false;      // not the picture we looked at
    *portrait = g_evt.portrait;                                      // only for the picture we marked
    return true;
}

// ---- the enlarged draw -------------------------------------------------------------------------------------------

bool Draw(const void* spr, void* dest, int key, int x, int y, int num, int den)
{
    if (!spr || !dest || num <= den || den <= 0) return false;
    FlushPrewarmLog();
    Replacement rep;
    int rw = 0, rh = 0;
    bool replaced = false;
    bool event = false;                           // a vanilla event picture: the field-separated enlarge
    bool nativeFace = false;                      // a vanilla (or game-art-sized) native-life face: Enlarge
    const BYTE* vanilla = nullptr;                // a replaced draw's vanilla pixels (pitch = width): the fallback
    if (spr == g_artSprView) {
        // (a replaced scratch is not baked at num > den: its pixels ARE vanilla)
        if (TakeNativeMark(spr, &rep, &rw, &rh)) replaced = true;
        else {
            if (TakeEventMark(spr, &nativeFace)) event = !nativeFace;
            if (!event && !nativeFace) return false;   // flics, unmarked pictures: the patcher's re-blit
        }
    } else if (const SlotState* st = ReplacedSlot(spr, &rw, &rh, &rep.framed)) {
        rep.img = st->img; rep.bright = st->bright; rep.ratio = st->ratio;
        vanilla = st->vanilla.data();
        replaced = true;
        // a leader slot drawn at another scale than the one pre-baked (Preferences display modes): the enlarges
        // are rebuilt for this scale.  (Only a leader-slot draw says so: other art has scales of its own.)
        // At most once per 10 s: a second site at another ratio must not restart it on every draw.
        static DWORD lastScaleRestart = 0;
        const int ng = (num * 16) % den == 0 ? (num * 16) / den : 0;
        if (prewarm::Started() && ng >= 16 && ng <= 256 && ng != prewarm::SnapshotG() &&
            (lastScaleRestart == 0 || GetTickCount() - lastScaleRestart > 10000)) {
            lastScaleRestart = GetTickCount();
            prewarm::Snapshot snap = MakeSnapshot(static_cast<const BYTE*>(dest) + 0xA4);
            snap.g = ng;
            prewarm::Restart(snap);
        }
    }
    if (!replaced && !g_smooth) return false;

    const BYTE* sData = Rd<const BYTE*>(spr, 4);
    const int sPitch = Rd<int>(spr, 0xC), sw = Rd<int>(spr, 0x10);
    int sh = Rd<int>(spr, 0x14); if (sh < 0) sh = -sh;
    if (!sData || sw <= 0 || sh <= 0 || sw > kMaxDim || sh > kMaxDim || sPitch < sw) return false;
    if (replaced ? (sw != rw || sh != rh) : !event && !portrait_law::Applies(sData, sPitch, sw, sh, key, num, den)) return false;

    BYTE* dData = Rd<BYTE*>(dest, 0x54);
    const int dPitch = Rd<int>(dest, 0x4A8), dW = Rd<int>(dest, 0x80);
    int dH = Rd<int>(dest, 0x84); if (dH < 0) dH = -dH;
    if (!dData || dPitch <= 0) return replaced;   // replaced: draw nothing rather than hand the bake to the patcher
    const int x0 = x + (Rd<int>(spr, 0x20) * num) / den, y0 = y + (Rd<int>(spr, 0x24) * num) / den;
    // a replaced draw never hands back to the patcher: its re-blit would enlarge the dithered bake (clip instead)
    if (!replaced && (x0 < 0 || y0 < 0)) return false;
    const BYTE* pal = static_cast<const BYTE*>(dest) + 0xA4;          // the dest's synced RGBQUAD[256]

    uint64_t h = 1469598103934665603ull;
    for (int r = 0; r < sh; ++r) h = Fnv(h, sData + static_cast<size_t>(r) * sPitch, static_cast<size_t>(sw));
    h = Fnv(h, pal, 1024);
    // the dest buffer's stripe-grid phase (portrait_law::ScanPhase): a picture's scanlines continue the panel's,
    // so the same art drawn at another row is another enlarge
    const int phase = portrait_law::ScanPhase(y0, num, den);
    h = Fnv(h, reinterpret_cast<const BYTE*>(&phase), sizeof phase);
    const int mode = replaced ? PortraitScanMode() : event ? -2 : -1;
    if (event) h = Fnv(h, reinterpret_cast<const BYTE*>(&mode), sizeof mode);   // never a portrait Enlarge result
    if (replaced) {
        h = Fnv(h, reinterpret_cast<const BYTE*>(&rep.img->id), sizeof rep.img->id);
        h = Fnv(h, reinterpret_cast<const BYTE*>(&mode), sizeof mode);
        h = Fnv(h, reinterpret_cast<const BYTE*>(&rep.bright), sizeof rep.bright);
        h = Fnv(h, reinterpret_cast<const BYTE*>(&rep.ratio), sizeof rep.ratio);
        h = Fnv(h, reinterpret_cast<const BYTE*>(&rep.framed), sizeof rep.framed);
    }

    Entry* hit = nullptr; Entry* lru = &g_cache[0];
    for (Entry& e : g_cache) {
        if (e.hash == h && e.sw == sw && e.sh == sh && e.num == num && e.den == den && e.key == key && !e.px.empty()) { hit = &e; break; }
        if (e.stamp < lru->stamp) lru = &e;
    }
    if (!hit) {
        int dw = 0, dh = 0;
        std::vector<int> px;
        ImageResampleCache rc(replaced ? rep.img->id : 0);
        bool ok = replaced
            ? portrait_law::EnlargeRgb(sData, sPitch, sw, sh, key, pal, num, den, rep.img->rgb.data(),
                                       rep.img->rgb.size(), rep.img->w, rep.img->h, mode, rep.bright, rep.ratio,
                                       &dw, &dh, &px, rep.framed, &rc, y0)
            : event ? portrait_law::FieldEnlarge(sData, sPitch, sw, sh, key, pal, num, den, &dw, &dh, &px, y0)
            : portrait_law::Enlarge(sData, sPitch, sw, sh, key, pal, num, den, &dw, &dh, &px, y0);
        if (!ok && replaced)                      // the vanilla art, smooth: never the bake through the patcher
            ok = vanilla ? portrait_law::Enlarge(vanilla, sw, sw, sh, key, pal, num, den, &dw, &dh, &px, y0)
                         : portrait_law::Enlarge(sData, sPitch, sw, sh, key, pal, num, den, &dw, &dh, &px, y0);
        if (!ok) return replaced;
        lru->hash = h; lru->sw = sw; lru->sh = sh; lru->num = num; lru->den = den; lru->key = key;
        lru->dw = dw; lru->dh = dh; lru->px.swap(px);
        hit = lru;
    }
    hit->stamp = ++g_clock;

    const int i0 = x0 < 0 ? -x0 : 0, j0 = y0 < 0 ? -y0 : 0;   // clipped left / top (replaced draws only)
    int iw = hit->dw; if (iw > dW - x0) iw = dW - x0;
    if (iw <= i0) return true;
    for (int j = j0; j < hit->dh; ++j) {
        const int dy = y0 + j;
        if (dy >= dH) break;
        BYTE* row = dData + static_cast<size_t>(dy) * dPitch + x0;
        const int* srcRow = &hit->px[static_cast<size_t>(j) * hit->dw];
        for (int i = i0; i < iw; ++i)
            if (srcRow[i] >= 0) row[i] = static_cast<BYTE>(srcRow[i]);
    }
    return true;
}

bool DrawCatching(const void* spr, void* dest, int key, int x, int y, int num, int den)
{
    try { return Draw(spr, dest, key, x, y, num, den); } catch (...) { return false; }
}

// cdecl, called from the naked hooks.  Any fault (a pointer the thunk's own guards would also have met) ->
// false -> the original thunk runs.
bool __cdecl PortraitDraw(const void* spr, void* dest, int key, int x, int y, int num, int den)
{
    __try {
        return DrawCatching(spr, dest, key, x, y, num, den);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

// Entry state: ecx = sprite; [esp] ret, +4 dest, +8 key, +C x, +10 y, +14 num, +18 den.  RET 0x18.
// eax is the caller's to lose (every caller saves it around the re-blit); ebx/esi/edi/ebp survive the C call.
__declspec(naked) void HookParityReblit()
{
    __asm {
        push ecx
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push ecx
        call PortraitDraw
        add esp, 0x1C
        pop ecx
        test al, al
        jz fallback
        ret 0x18
    fallback:
        jmp dword ptr [g_trampParityPtr]
    }
}

__declspec(naked) void HookArtReblit()
{
    __asm {
        push ecx
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push ecx
        call PortraitDraw
        add esp, 0x1C
        pop ecx
        test al, al
        jz fallback
        ret 0x18
    fallback:
        jmp dword ptr [g_trampArtPtr]
    }
}

// Copy `len` (>= 5, position-independent) entry bytes to `tramp` + a jmp back; jmp the entry to `hook`.
void Detour(BYTE* fn, BYTE* tramp, void* hook, size_t len)
{
    DWORD old;
    VirtualProtect(tramp, 16, PAGE_EXECUTE_READWRITE, &old);
    memcpy(tramp, fn, len);
    tramp[len] = 0xE9;
    const int32_t back = static_cast<int32_t>((fn + len) - (tramp + len + 5));
    memcpy(tramp + len + 1, &back, 4);

    VirtualProtect(fn, len, PAGE_EXECUTE_READWRITE, &old);
    fn[0] = 0xE9;
    const int32_t fwd = static_cast<int32_t>(static_cast<BYTE*>(hook) - (fn + 5));
    memcpy(fn + 1, &fwd, 4);
    for (size_t i = 5; i < len; ++i) fn[i] = 0xCC;
    VirtualProtect(fn, len, old, &old);
    FlushInstructionCache(GetCurrentProcess(), fn, len);
}

void IniFile(char* ini, size_t n)
{
    GetModuleFileNameA(nullptr, ini, static_cast<DWORD>(n));
    char* slash = strrchr(ini, '\\');
    if (slash) slash[1] = '\0';
    strcat_s(ini, n, "Alpha Centauri.ini");
}

} // namespace

int  PortraitCustomGet() { return g_custom; }
// [DebugLog] the portrait settings behind the next screenshots
void LogOptions(const char* why)
{
    char msg[160];
    _snprintf_s(msg, sizeof msg, _TRUNCATE,
                "[uimod] portrait: settings (%s): user portraits %d, HD pack %d (installed %d), scanlines %d (brightness kept)\n",
                why, g_custom, g_hd, portrait_files::PackInstalled() ? 1 : 0, g_scan);
    UimodDbg(msg);
}

// The pack is used only while it is INSTALLED (its manifest present): files dropped into portraits\hd\ by hand,
// or a half-copied pack, never take priority with no Preferences row to turn them off.
void ApplyOptions()
{
    portrait_files::SetOptions(g_custom != 0, g_hd != 0 && portrait_files::PackInstalled());
}

void PortraitSetAll(int custom, int hd, int scan)
{
    g_custom = custom ? 1 : 0;
    g_hd = hd ? 1 : 0;
    g_scan = scan ? 1 : 0;
    ApplyOptions();
    PortraitRebake();
}

void PortraitCustomSet(int on)
{
    g_custom = on ? 1 : 0;
    ApplyOptions();
    PortraitRebake();
}
void PortraitCustomSave()
{
    char ini[MAX_PATH]; IniFile(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "CustomPortraits", g_custom ? "1" : "0", ini);
}
int  PortraitHdGet() { return g_hd; }
void PortraitHdSet(int on)
{
    g_hd = on ? 1 : 0;
    ApplyOptions();
    PortraitRebake();
}
void PortraitHdSave()
{
    char ini[MAX_PATH]; IniFile(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "HdPortraits", g_hd ? "1" : "0", ini);
}
bool PortraitPackInstalled() { return portrait_files::PackInstalled(); }

int  PortraitScanGet() { return g_scan; }
void PortraitScanSet(int on) { g_scan = on ? 1 : 0; }
void PortraitScanSave()
{
    char ini[MAX_PATH]; IniFile(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "PortraitScanlines", g_scan ? "1" : "0", ini);
}
// The scanlines on replacements are always the brightness-keeping kind (user 2026-10-30: the former "Brighten
// Scanlines" row and its PortraitScanlinesBright key are gone; the darkening overlay mode is never selected).
int PortraitScanMode()
{
    return !g_scan ? portrait_law::kScanOff : portrait_law::kScanMean;
}
namespace { int PortraitScanModeInternal() { return PortraitScanMode(); } }

// A settings change (the pre-bake runs again for the new image set / scan mode; SEH frame: no C++ objects here)
void RestartPrewarm()
{
    __try {
        if (prewarm::Started()) {
            BYTE pal[1024];
            GamePalRgbquad(pal);
            prewarm::Restart(MakeSnapshot(pal));
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

void PortraitRebake()
{
    RestartPrewarm();                         // first: the re-bakes below then hit the new snapshot's cache
    __try {
        for (int f = 0; f < 8; ++f)
            for (int s = 0; s < 4; ++s)
                if (g_slots[f][s].valid) BakeSlot(f, s);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
    // the enlarged results are keyed on the scan mode already; the native-life bakes too
    LogOptions("changed");                        // every settings change ends in a re-bake: one line per change
}

void InstallSmoothPortraits()
{
    char ini[MAX_PATH]; IniFile(ini, sizeof ini);
    // the replacement-portrait scanline settings load whatever happens below (the Preferences rows read them)
    g_custom = GetPrivateProfileIntA("UIMod", "CustomPortraits", kPortraitCustomDefault, ini) != 0 ? 1 : 0;
    g_hd = GetPrivateProfileIntA("UIMod", "HdPortraits", kPortraitHdDefault, ini) != 0 ? 1 : 0;
    g_scan = GetPrivateProfileIntA("UIMod", "PortraitScanlines", kPortraitScanDefault, ini) != 0 ? 1 : 0;
    if (!g_custom) g_hd = g_scan = 0;             // nested under CustomPortraits (prefs page)
    ApplyOptions();
    g_smooth = GetPrivateProfileIntA("UIMod", "SmoothPortraits", 1, ini) != 0;

    // replacement leader portraits at native size: any exe (no cave needed)
    BYTE* lfa = reinterpret_cast<BYTE*>(kVA_LoadFactionArt);
    if (memcmp(lfa, kLfaEntry, sizeof kLfaEntry) == 0) {
        Detour(lfa, g_trampLfa, reinterpret_cast<void*>(&HookLoadFactionArt), sizeof kLfaEntry);
        UimodLog("[uimod] portrait: replacement leader portraits armed (load_faction_art; <game>\\portraits\\, then portraits\\hd\\)\n");
    } else {
        UimodLog("[uimod] portrait: unexpected bytes at load_faction_art -> no replacement leader portraits\n");
    }

    uintptr_t lo = 0, hi = 0;
    g_hasCave = UimodPcave2Range(&lo, &hi) != 0;
    if (!g_hasCave || lo + kOffArtReblit + sizeof kEntry > hi) {
        UimodLog("[uimod] portrait: no patcher cave (unscaled exe) -> nothing to enlarge, re-blit hooks not installed\n");
        return;
    }
    g_artSprView = reinterpret_cast<const void*>(lo + kOffArtSpr);
    BYTE* parity = reinterpret_cast<BYTE*>(lo + kOffParityReblit);
    BYTE* art = reinterpret_cast<BYTE*>(lo + kOffArtReblit);
    if (memcmp(parity, kEntry, sizeof kEntry) != 0 || memcmp(art, kEntry, sizeof kEntry) != 0) {
        UimodLog("[uimod] portrait: unexpected bytes at thunk_parity_reblit / thunk_art_reblit -> NOT installed "
                 "(portraits keep the patcher's re-blit)\n");
        return;
    }
    Detour(parity, g_trampParity, HookParityReblit, sizeof kEntry);
    Detour(art, g_trampArt, HookArtReblit, sizeof kEntry);
    g_b2Armed = true;
    Logf("[uimod] portrait: re-blit hooks installed (smooth vanilla portraits %s; replacements enlarge from their image)\n",
         g_smooth ? "on" : "OFF by [UIMod] SmoothPortraits=0");

    BYTE* core = reinterpret_cast<BYTE*>(lo + kOffArtCore);
    if (lo + kOffArtCore + sizeof kArtCoreEntry <= hi && memcmp(core, kArtCoreEntry, sizeof kArtCoreEntry) == 0) {
        Detour(core, g_trampArtCore, HookArtCore, sizeof kArtCoreEntry);
        UimodLog("[uimod] portrait: replacement native-life portraits armed (thunk_art_core)\n");
    } else {
        UimodLog("[uimod] portrait: unexpected bytes at thunk_art_core -> no replacement native-life portraits\n");
    }
}
