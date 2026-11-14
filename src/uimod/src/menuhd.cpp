// menuhd.cpp -- the HD main menu and planet setup at any resolution, by one uniform scale.
//
// A pack is <game>\menu\hd\ (layout: scaling_laws.menu_hd_layout; all 8-bit PCX, each in its own palette):
//   space_x3.pcx            the panorama, 2400 x 768 stock units at 3x (7200 x 2304): the stock opening's left part
//                           (logo, suns, copyright) at its stock positions, then starfield
//   S#L#C#_x3.pcx (27)      custom_planet's planet strips (404 x 768) at 3x (1212 x 2304)
//   moon1..3_x3.pcx         custom_planet's erosive-forces moons (450 x 450) at 3x (1350 x 1350), file index 255 the
//                           key, as in the stock files
// space_x3.pcx is required. A pack may leave out any strip or moon: a piece with no file, or one that cannot be used,
// is NOT shown -- its place is left empty (black where a planet belongs, the bare panorama where a moon belongs) --
// and the game's own picture is never drawn into this layout (off 4:3 it does not fit the slot).
//
// Engine (PRACX 2d0b1438 and the vanilla exe alike; symbols in work/symbols/terranx.h):
//  * The opening is loaded into a local Buffer with Buffer_load_pcx(name, 0, 10, 236) and stretched over the whole
//    TopMenuWin (0x945824, canvas +0x444) with Buffer_copy_3 0x5D9610 = GDI StretchBlt (anamorphic on a wide screen;
//    shrinking ANDs the indices of the dropped rows). It has two copies: change_opening 0x589A30 (load @0x589AA1,
//    stretch @0x589AE8; the stock top_menu's) and init_opening 0x589B60 (load @0x589C84, stretch @0x589CCB; no caller
//    in the exe -- Thinker's own top_menu calls it).
//  * custom_planet 0x58C2A0 (Start Game > Customize) loads its previews (S#L#C#.PCX, MOON1..3.PCX) with
//    Buffer_load_pcx into SetupWin deco[3] (+0xA1C; x +0xA28, y +0xA34). Under Thinker its custom_planet replaces the
//    exe's and loads them from thinker.dll, through the same Buffer_load_pcx. SetupWin_draw_item 0x4AE4D0 (5 callers,
//    all in the exe) draws the highlighted item's preview into the TopMenuWin canvas and GraphicWin_soft_update's it;
//    with deco[k] null it skips all three draws (0x4AE694), Thinker's re-pointed ones included.
//
// So the menu is composed, not stretched: the panorama left-aligned and the strip right-aligned, both at one scale
// num/den (menuhd_law::MenuLayout), resampled by menuhd_law::Resample (integer box shrink / Lanczos enlarge +
// Floyd-Steinberg into the canvas colours, read from the destination Buffer's own synced table +0xA4). The main menu
// shows S3L2C2; custom_planet's previews are drawn at the same place by the same law.
//
// Levers, all byte-checked:
//  * Buffer_load_pcx's entry (0x5D7DE0, a 7-byte detour, entry bytes checked) -> LoadPcxHook: records which picture
//    each Buffer now holds (the opening, a strip, a moon), then the stock load. One lever for both paths: the exe's
//    callers and Thinker's.
//  * the two opening stretches (@0x589AE8, @0x589CCB) -> CopyHook: for xopeninga.pcx, the composed menu copied 1:1.
//  * the 5 SetupWin_draw_item calls -> DrawItemHook: on a composed menu, the highlighted item's preview slot is
//    emptied for the stock draw and the HD preview is drawn and soft-updated here instead.
// SMAC's own opening (openinga.pcx) and 800-wide screens (the b pictures, another layout) stay stock.
//
// Native no-op, decided once: space_x3.pcx is proven (hdpack::Load: the bounded scan of the whole file, the exact
// size) at install -- it fails: logged, nothing patched, no Preferences row. Every strip and moon file is checked at
// install (header, size, file length); its full proof is at its first use; a file that fails either is logged once
// and stays unshown for the session. An allocation failure anywhere is that picture not shown (plain malloc, no
// exceptions). The engine's fatal exit is bounded, not gone: the scratch Buffer the pictures go through (Buffer_init;
// its address room probed first) is the one engine allocation.
//
// Memory: the composed menu (w x h bytes, 8.3 MB at 4K) and up to kCache previews at their drawn size (about 17 MB
// at 4K for a step's three, the previous step's three and one spare), least recently drawn first out, a good entry
// replaced only once its successor is made. A pack file is read for the one picture being made and released
// straight after. "HD Main Menu" ([UIMod] MenuHD) switches it; it takes effect the next time the menu is drawn.

#include "menuhd.h"
#include "menuhd_law.h"
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
constexpr uintptr_t kVA_LoadPcx      = 0x5D7DE0;   // Buffer_load_pcx: thiscall (Buffer*, name, pal, a4, a5) RET 0x10
constexpr uintptr_t kVA_Copy3        = 0x5D9610;   // Buffer_copy_3: thiscall (src, dst, sx, sy, sw, sh, dx, dy, dw, dh) RET 0x24
constexpr uintptr_t kVA_DrawItem     = 0x4AE4D0;   // SetupWin_draw_item: thiscall (SetupWin*, item, highlighted) RET 8
constexpr uintptr_t kVA_SoftUpdate   = 0x5D5720;   // GraphicWin_soft_update: thiscall (win, x, y, w, h) RET 0x10
constexpr uintptr_t kVA_BufferCtor   = 0x5D7210;   // Buffer_ctor: thiscall (Buffer*)
constexpr uintptr_t kVA_BufferInit   = 0x5D7670;   // Buffer_init: thiscall (Buffer*, w, h, flags, surf) RET 0x10
constexpr uintptr_t kVA_TopMenuWin   = 0x945824;   // TopMenuWin* (GraphicWin; canvas Buffer at +0x444)
constexpr uintptr_t kVA_ScreenWidth  = 0x9B7B1C;
constexpr uint32_t kCopySites[] = {0x589AE8, 0x589CCB};   // change_opening's and init_opening's stretch
constexpr uint32_t kDrawItemSites[] = {0x4AE0D7, 0x4AE3B6, 0x4AE3C9, 0x4AE43A, 0x4AE44A};
// Buffer_load_pcx's first two instructions: push -1; push 0x662BC7 (its SEH frame) -- moved to the trampoline as is
const BYTE kLoadPcxEntry[] = {0x6A, 0xFF, 0x68, 0xC7, 0x2B, 0x66, 0x00};
constexpr int kDecoOfs = 0xA1C;                     // SetupWin +0xA1C struct Buffer* deco[3]
constexpr int kItemCountOfs = 0xFCC;                // SetupWin +0xFCC: item count (draw_item returns at item >= it)
constexpr int kCanvasOfs = 0x444;

constexpr int kBufData = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufH = 0x84, kBufColors = 0xA4, kBufPitch = 0x4A8;
constexpr int kBufSize = 0x588;
constexpr int kLo = 10, kHi = 246;                  // the opening's colours: Buffer_load_pcx(name, 0, 10, 236)
constexpr int kArt = 3;                             // the pack's scale: one stock pixel = 3 x 3
constexpr int kKeyFile = 255;                       // a moon's see-through file index
constexpr int kNarrowWidth = 800;                   // ScreenWidth 800: the b pictures and another layout -> stock
constexpr int kCache = 7;

typedef int (__thiscall* FLoadPcx)(void*, const char*, void*, int, int);
typedef int (__thiscall* FCopy3)(void*, void*, int, int, int, int, int, int, int, int);
typedef int (__thiscall* FDrawItem)(void*, int, int);
typedef int (__thiscall* FSoftUpdate)(void*, int, int, int, int);
typedef void (__thiscall* FBufferCtor)(void*);
typedef int (__thiscall* FBufferInit)(void*, int, int, int, void*);

FLoadPcx g_load = nullptr;                          // the trampoline: Buffer_load_pcx's first 7 bytes, then a jmp back
FCopy3 g_copy = nullptr;
FDrawItem g_drawItem = nullptr;
bool g_installed = false;
int g_on = kMenuHdDefault;
char g_dir[MAX_PATH];
bool g_composed = false;                            // the opening on screen is our composition

// What each Buffer was last loaded with (only the pictures this module draws; another load clears its record).
struct Loaded { void* buf; char stem[12]; };
Loaded g_loaded[16];
int g_loadedNext = 0;

// The pack's pieces: 27 strips, 3 moons. state 0 = no file, 1 = header checked (proven at first use), 2 = proven,
// -1 = unusable (logged once).
struct Piece { char stem[8]; int state; };
Piece g_pieces[30];

uint8_t g_canvas[1024];                             // the canvas colours the LUT below was built for
uint8_t g_lut[32768];
bool g_lutReady = false;

uint8_t* g_menu = nullptr;                          // the composed main menu (canvas indices), g_menuW x g_menuH
int g_menuW = 0, g_menuH = 0;
bool g_menuFailed = false;                          // composing failed at this size: stock menu, not retried
struct Cached { char stem[8]; int w, h; uint8_t* px; unsigned used; };
Cached g_cache[kCache];
unsigned g_clock = 0;
alignas(16) uint8_t g_scratch[kBufSize + 0x80];
bool g_scratchReady = false;
int g_scratchW = 0, g_scratchH = 0;

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

void HdPath(const char* stem, char* out, size_t n)
{
    char lower[16];
    strncpy_s(lower, stem, _TRUNCATE);
    for (char* p = lower; *p; ++p) if (*p >= 'A' && *p <= 'Z') *p = static_cast<char>(*p - 'A' + 'a');
    _snprintf_s(out, n, _TRUNCATE, "%smenu\\hd\\%s_x%d.pcx", g_dir, IsStrip(stem) ? stem : lower, kArt);
}

void PieceSize(const char* stem, int* w, int* h)
{
    const bool moon = IsMoon(stem);
    *w = (moon ? menuhd_law::kMoonW : menuhd_law::kStripW) * kArt;
    *h = (moon ? menuhd_law::kMoonW : menuhd_law::kMenuH) * kArt;
}

Piece* PieceOf(const char* stem)
{
    for (Piece& p : g_pieces) if (strcmp(p.stem, stem) == 0) return &p;
    return nullptr;
}

// The header of a pack file, read without the body: 8-bit, one plane, RLE, BytesPerLine = width, the size wanted,
// and the file no longer than any honest file of that size (hdpack::MaxFile). 1 usable so far, 0 no file, -1 not.
int CheckHeader(const char* path, int wantW, int wantH)
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES ? 0 : -1;
    uint8_t b[hdpack::kHeader];
    const bool read = fread(b, 1, sizeof b, f) == sizeof b;
    long len = 0;
    if (fseek(f, 0, SEEK_END) == 0) len = ftell(f);
    fclose(f);
    if (!read || b[0] != 10 || b[2] != 1 || b[3] != 8 || b[65] != 1) return -1;
    const int w = (b[8] | b[9] << 8) - (b[4] | b[5] << 8) + 1, h = (b[10] | b[11] << 8) - (b[6] | b[7] << 8) + 1;
    if (w != wantW || h != wantH || (b[66] | b[67] << 8) != w) return -1;
    const size_t max = hdpack::MaxFile(wantW, wantH);
    return len > hdpack::kHeader + hdpack::kTrailer && static_cast<unsigned long>(len) <= max ? 1 : -1;
}

// --- colours, pictures --------------------------------------------------------------------------------------------

// The canvas colours (a Buffer's synced RGBQUAD table) and their nearest-colour LUT, rebuilt when they change.
bool UseColours(void* buf)
{
    const uint8_t* q = static_cast<const uint8_t*>(buf) + kBufColors;
    bool any = false;
    for (int k = kLo * 4; k < kHi * 4 && !any; ++k) any = q[k] != 0;
    if (!any) return false;
    if (!g_lutReady || memcmp(g_canvas, q, sizeof g_canvas) != 0) {
        memcpy(g_canvas, q, sizeof g_canvas);
        const DWORD t0 = GetTickCount();
        menuhd_law::NearestLut(g_canvas, kLo, kHi, g_lut);
        g_lutReady = true;
        Dbg("[menuhd] canvas colours read, nearest-colour table built in %lu ms\n", GetTickCount() - t0);
    }
    return true;
}

struct RowCtx { const hdpack::Pack* pack; uint8_t* row; uint8_t ident[256]; };

const uint8_t* PackRow(void* ctx, int r)
{
    RowCtx* c = static_cast<RowCtx*>(ctx);
    return hdpack::Expand(*c->pack, 0, r, c->pack->w, 1, c->ident, c->row) ? c->row : nullptr;
}

// A pack file resampled to dw x dh at num/den into dst (pitch dp). False: not drawn (dst may be partly written).
bool DrawPack(const char* path, int wantW, int wantH, int key, int num, int den, uint8_t* dst, int dw, int dh, int dp,
              hdpack::Result* why)
{
    hdpack::Pack pack;
    uint8_t pal[768];
    *why = hdpack::Load(&pack, path, wantW, wantH, nullptr, pal);
    if (*why != hdpack::kOk) return false;
    RowCtx ctx;
    ctx.pack = &pack;
    ctx.row = static_cast<uint8_t*>(malloc(static_cast<size_t>(wantW)));
    for (int i = 0; i < 256; ++i) ctx.ident[i] = static_cast<uint8_t>(i);
    long long sn = 0, sd = 0;
    menuhd_law::Step(kArt, num, den, &sn, &sd);
    const bool ok = ctx.row && menuhd_law::Resample(&PackRow, &ctx, wantW, wantH, pal, key, sn, sd, dw, dh, dst, dp,
                                                     g_canvas, kLo, kHi, g_lut);
    if (!ok) *why = hdpack::kNoMemory;
    free(ctx.row);
    hdpack::Free(&pack);
    return ok;
}

// A strip or moon drawn at dw x dh into dst, or false (not shown). A piece that fails is remembered for the session.
bool DrawPiece(const char* stem, int num, int den, uint8_t* dst, int dw, int dh, int dp)
{
    Piece* p = PieceOf(stem);
    if (!p || p->state <= 0) return false;
    char path[MAX_PATH];
    HdPath(stem, path, sizeof path);
    int w = 0, h = 0;
    PieceSize(stem, &w, &h);
    hdpack::Result why = hdpack::kOk;
    if (DrawPack(path, w, h, IsMoon(stem) ? kKeyFile : -1, num, den, dst, dw, dh, dp, &why)) {
        p->state = 2;
        return true;
    }
    if (why == hdpack::kNoMemory) {                     // no memory now: not shown this time, may be tried again
        Log("[menuhd] no memory for menu\\hd\\%s -> not shown\n", strrchr(path, '\\') + 1);
        return false;
    }
    Log("[menuhd] menu\\hd\\%s %s (want an 8-bit %dx%d PCX) -> not shown\n", strrchr(path, '\\') + 1, hdpack::Why(why),
        w, h);
    p->state = -1;
    return false;
}

uint8_t Black()
{
    for (int k = kLo; k < kHi; ++k)
        if (!g_canvas[k * 4] && !g_canvas[k * 4 + 1] && !g_canvas[k * 4 + 2]) return static_cast<uint8_t>(k);
    return g_lut[0];
}

// The main menu at w x h: the panorama left-aligned, S3L2C2 right-aligned, black outside the picture.
bool ComposeMenu(int w, int h)
{
    if (g_menu && g_menuW == w && g_menuH == h) return true;
    if (g_menuFailed && g_menuW == w && g_menuH == h) return false;
    const DWORD t0 = GetTickCount();
    free(g_menu);
    g_menu = static_cast<uint8_t*>(malloc(static_cast<size_t>(w) * h));
    g_menuW = w;
    g_menuH = h;
    g_menuFailed = !g_menu;
    if (!g_menu) {
        Log("[menuhd] no memory for a %dx%d menu -> stock menu\n", w, h);
        return false;
    }
    const menuhd_law::Layout L = menuhd_law::MenuLayout(w, h);
    memset(g_menu, Black(), static_cast<size_t>(w) * h);
    uint8_t* core = g_menu + static_cast<size_t>(L.y0) * w + L.x0;
    char path[MAX_PATH];
    _snprintf_s(path, sizeof path, _TRUNCATE, "%smenu\\hd\\space_x%d.pcx", g_dir, kArt);
    hdpack::Result why = hdpack::kOk;
    if (!DrawPack(path, menuhd_law::kPanoW * kArt, menuhd_law::kMenuH * kArt, -1, L.num, L.den, core,
                  L.stripX - L.x0, L.coreH, w, &why)) {
        Log("[menuhd] menu\\hd\\space_x%d.pcx %s -> stock menu\n", kArt, hdpack::Why(why));
        free(g_menu);
        g_menu = nullptr;
        g_menuFailed = true;
        return false;
    }
    if (!DrawPiece("S3L2C2", L.num, L.den, core + (L.stripX - L.x0), L.stripW, L.coreH, w))
        Dbg("[menuhd] no usable planet strip S3L2C2 -> the menu's planet slot is left empty\n");
    Dbg("[menuhd] main menu composed at %dx%d (scale %d/%d) in %lu ms\n", w, h, L.num, L.den, GetTickCount() - t0);
    return true;
}

// The scratch Buffer at w x h. Its address room is probed first: Buffer_init's own failure is the engine's fatal exit.
void* Scratch(int w, int h)
{
    if (!g_scratchReady || w != g_scratchW || h != g_scratchH) {
        void* probe = VirtualAlloc(nullptr, static_cast<size_t>((w + 3) & ~3) * h * 2 + (1 << 20), MEM_RESERVE,
                                   PAGE_READWRITE);
        if (!probe) return nullptr;
        VirtualFree(probe, 0, MEM_RELEASE);
        if (!g_scratchReady) {
            reinterpret_cast<FBufferCtor>(At(kVA_BufferCtor))(g_scratch);
            g_scratchReady = true;
        }
        reinterpret_cast<FBufferInit>(At(kVA_BufferInit))(g_scratch, w, h, 0, nullptr);
        g_scratchW = w;
        g_scratchH = h;
    }
    if (Field(g_scratch, kBufW) != w || !Pixels(g_scratch) || Field(g_scratch, kBufPitch) < w) return nullptr;
    return g_scratch;
}

void ToScratch(const uint8_t* px, int w, int h, int pitch)
{
    uint8_t* d = Pixels(g_scratch);
    const int dp = Field(g_scratch, kBufPitch);
    for (int y = 0; y < h; ++y) memcpy(d + static_cast<size_t>(y) * dp, px + static_cast<size_t>(y) * pitch, w);
}

bool Active() { return g_installed && g_on && *reinterpret_cast<int*>(At(kVA_ScreenWidth)) != kNarrowWidth; }

// --- hooks ------------------------------------------------------------------------------------------------------

// Stands in for Buffer_load_pcx (entry detour, same contract): records what the Buffer now holds, then the stock load.
int __fastcall LoadPcxHook(void* buf, void* /*edx*/, const char* name, void* pal, int a4, int a5)
{
    char stem[16];
    Stem(name ? name : "", stem, sizeof stem);
    const bool ours = strcmp(stem, "XOPENINGA") == 0 || IsStrip(stem) || IsMoon(stem);
    Loaded* slot = nullptr;
    for (Loaded& l : g_loaded) if (l.buf == buf) slot = &l;
    if (ours) {
        if (!slot) {
            slot = &g_loaded[g_loadedNext];
            g_loadedNext = (g_loadedNext + 1) % static_cast<int>(sizeof g_loaded / sizeof g_loaded[0]);
        }
        slot->buf = buf;
        strncpy_s(slot->stem, stem, _TRUNCATE);
    } else if (slot) {
        *slot = Loaded{};                               // that Buffer holds something else now
    }
    return g_load(buf, name, pal, a4, a5);
}

const char* HeldBy(const void* buf)
{
    for (const Loaded& l : g_loaded) if (buf && l.buf == buf) return l.stem;
    return nullptr;
}

// Stands in for Buffer_copy_3 at the opening's stretch (both copies): the composed menu, copied 1:1, for xopeninga.
int __fastcall CopyHook(void* src, void* /*edx*/, void* dst, int sx, int sy, int sw, int sh, int dx, int dy, int dw,
                        int dh)
{
    const char* held = HeldBy(src);
    g_composed = false;
    if (Active() && held && strcmp(held, "XOPENINGA") == 0 && dw > 0 && dh > 0 &&
        (UseColours(dst) || UseColours(src)) && ComposeMenu(dw, dh) && Scratch(dw, dh)) {
        ToScratch(g_menu, dw, dh, dw);
        g_composed = true;
        return g_copy(g_scratch, dst, 0, 0, dw, dh, dx, dy, dw, dh);
    }
    return g_copy(src, dst, sx, sy, sw, sh, dx, dy, dw, dh);
}

// A preview at its drawn size: from the cache, else made now (the oldest entry replaced only once it is made).
const Cached* Preview(const char* stem, const menuhd_law::Layout& L, int rw, int rh)
{
    for (Cached& it : g_cache)
        if (it.px && strcmp(it.stem, stem) == 0 && it.w == rw && it.h == rh) { it.used = ++g_clock; return &it; }
    uint8_t* px = static_cast<uint8_t*>(malloc(static_cast<size_t>(rw) * rh));
    if (!px) return nullptr;
    const DWORD t0 = GetTickCount();
    if (!DrawPiece(stem, L.num, L.den, px, rw, rh, rw)) { free(px); return nullptr; }
    Cached* c = &g_cache[0];
    for (Cached& it : g_cache) if (!it.px || (c->px && it.used < c->used)) c = &it;
    free(c->px);
    strncpy_s(c->stem, stem, _TRUNCATE);
    c->w = rw;
    c->h = rh;
    c->px = px;
    c->used = ++g_clock;
    Dbg("[menuhd] preview %s made at %dx%d in %lu ms\n", stem, rw, rh, GetTickCount() - t0);
    return c;
}

// Draw one preview into the TopMenuWin canvas where the law puts it, and present that rect. A piece that is not
// shown leaves its place empty: black for a strip, the composed menu's own pixels for a moon.
void PaintPreview(const char* stem)
{
    uint8_t* win = *reinterpret_cast<uint8_t**>(At(kVA_TopMenuWin));
    if (!win || !g_menu) return;
    void* canvas = win + kCanvasOfs;
    const int w = Field(canvas, kBufW), h = Field(canvas, kBufH) < 0 ? -Field(canvas, kBufH) : Field(canvas, kBufH);
    if (w != g_menuW || h != g_menuH || !UseColours(canvas)) return;
    const menuhd_law::Layout L = menuhd_law::MenuLayout(w, h);
    const bool moon = IsMoon(stem);
    const menuhd_law::Rect m = menuhd_law::MoonRect(L);
    const int rx = moon ? m.x : L.stripX, ry = L.y0, rw = moon ? m.w : L.stripW, rh = moon ? m.h : L.coreH;
    if (rw <= 0 || rh <= 0 || !Scratch(rw, rh)) return;
    const Cached* c = Preview(stem, L, rw, rh);
    uint8_t* d = Pixels(g_scratch);
    const int dp = Field(g_scratch, kBufPitch);
    for (int y = 0; y < rh; ++y) {
        const uint8_t* under = g_menu + static_cast<size_t>(ry + y) * w + rx;
        uint8_t* o = d + static_cast<size_t>(y) * dp;
        if (!c) { if (moon) memcpy(o, under, rw); else memset(o, Black(), rw); continue; }
        const uint8_t* s = c->px + static_cast<size_t>(y) * rw;
        if (!moon) { memcpy(o, s, rw); continue; }
        for (int x = 0; x < rw; ++x) o[x] = s[x] == menuhd_law::kKey ? under[x] : s[x];   // the moon over the sky
    }
    g_copy(g_scratch, canvas, 0, 0, rw, rh, rx, ry, rw, rh);
    reinterpret_cast<FSoftUpdate>(At(kVA_SoftUpdate))(win, rx, ry, rw, rh);
}

// Stands in for SetupWin_draw_item at its 5 callers: same contract (thiscall, RET 8).
int __fastcall DrawItemHook(void* self, void* /*edx*/, int item, int highlighted)
{
    if (!g_composed || !Active() || !highlighted) return g_drawItem(self, item, highlighted);
    if (item >= *reinterpret_cast<int*>(static_cast<uint8_t*>(self) + kItemCountOfs))
        return g_drawItem(self, item, highlighted);                  // the stock function's own early-out
    const int k = item < 0 ? 0 : item > 2 ? 2 : item;               // the engine's own clamp
    void** slot = reinterpret_cast<void**>(static_cast<uint8_t*>(self) + kDecoOfs) + k;
    void* deco = *slot;
    const char* held = HeldBy(deco);
    if (!held || !(IsStrip(held) || IsMoon(held))) return g_drawItem(self, item, highlighted);
    char stem[12];
    strncpy_s(stem, held, _TRUNCATE);
    *slot = nullptr;                                                 // no stock (or patched) preview blit
    const int rc = g_drawItem(self, item, highlighted);
    *slot = deco;
    PaintPreview(stem);
    return rc;
}

// Buffer_load_pcx's entry -> LoadPcxHook; the 7 moved bytes run from the trampoline, then back to 0x5D7DE7.
bool DetourLoadPcx()
{
    BYTE* e = At(kVA_LoadPcx);
    if (memcmp(e, kLoadPcxEntry, sizeof kLoadPcxEntry) != 0) return false;
    BYTE* t = static_cast<BYTE*>(VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!t) return false;
    memcpy(t, e, sizeof kLoadPcxEntry);
    t[7] = 0xE9;
    const int32_t back = static_cast<int32_t>(reinterpret_cast<uintptr_t>(e + 7) - reinterpret_cast<uintptr_t>(t + 12));
    memcpy(t + 8, &back, 4);
    FlushInstructionCache(GetCurrentProcess(), t, 12);
    g_load = reinterpret_cast<FLoadPcx>(t);
    DWORD old;
    VirtualProtect(e, sizeof kLoadPcxEntry, PAGE_EXECUTE_READWRITE, &old);
    const int32_t to = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&LoadPcxHook) - reinterpret_cast<uintptr_t>(e + 5));
    e[0] = 0xE9;
    memcpy(e + 1, &to, 4);
    e[5] = e[6] = 0x90;
    VirtualProtect(e, sizeof kLoadPcxEntry, old, &old);
    FlushInstructionCache(GetCurrentProcess(), e, sizeof kLoadPcxEntry);
    return true;
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
void MenuHdSet(int on) { g_on = on ? 1 : 0; }     // the next opening / preview draw follows it

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
    _snprintf_s(pano, sizeof pano, _TRUNCATE, "%smenu\\hd\\space_x%d.pcx", g_dir, kArt);
    if (GetFileAttributesA(pano) == INVALID_FILE_ATTRIBUTES) return;   // no pack: nothing patched, no row
    if (!PrefsTabInstalled()) {
        Log("[menuhd] no Longevity Preferences tab on this exe -> HD menu NOT installed\n");
        return;
    }
    // the panorama decides it: proven in full now, released straight after (it is read again to compose the menu)
    {
        hdpack::Pack p;
        const DWORD t0 = GetTickCount();
        const hdpack::Result r = hdpack::Load(&p, pano, menuhd_law::kPanoW * kArt, menuhd_law::kMenuH * kArt, nullptr);
        hdpack::Free(&p);
        if (r != hdpack::kOk) {
            Log("[menuhd] menu\\hd\\space_x%d.pcx %s (want an 8-bit %dx%d PCX) -> HD menu NOT installed\n", kArt,
                hdpack::Why(r), menuhd_law::kPanoW * kArt, menuhd_law::kMenuH * kArt);
            return;
        }
        Dbg("[menuhd] menu\\hd\\space_x%d.pcx proven in %lu ms\n", kArt, GetTickCount() - t0);
    }
    for (uint32_t site : kCopySites)
        if (!CallsTo(site, kVA_Copy3)) {
            Log("[menuhd] unexpected bytes at the opening's stretch %X -> HD menu NOT installed\n", site);
            return;
        }
    for (uint32_t site : kDrawItemSites)
        if (!CallsTo(site, kVA_DrawItem)) {
            Log("[menuhd] unexpected bytes at SetupWin_draw_item call %X -> HD menu NOT installed\n", site);
            return;
        }
    if (memcmp(At(kVA_LoadPcx), kLoadPcxEntry, sizeof kLoadPcxEntry) != 0) {
        Log("[menuhd] unexpected bytes at Buffer_load_pcx's entry -> HD menu NOT installed\n");
        return;
    }
    // every strip and moon: its header and size now, its full proof at its first use
    int have = 0, bad = 0, n = 0;
    for (int s = 1; s <= 3; ++s)
        for (int l = 1; l <= 3; ++l)
            for (int c = 1; c <= 3; ++c)
                _snprintf_s(g_pieces[n++].stem, sizeof g_pieces[0].stem, _TRUNCATE, "S%dL%dC%d", s, l, c);
    for (int m = 1; m <= 3; ++m) _snprintf_s(g_pieces[n++].stem, sizeof g_pieces[0].stem, _TRUNCATE, "MOON%d", m);
    for (Piece& p : g_pieces) {
        char path[MAX_PATH];
        HdPath(p.stem, path, sizeof path);
        int w = 0, h = 0;
        PieceSize(p.stem, &w, &h);
        p.state = CheckHeader(path, w, h);
        if (p.state < 0) {
            ++bad;
            Log("[menuhd] menu\\hd\\%s is not an 8-bit %dx%d RLE PCX -> not shown\n", strrchr(path, '\\') + 1, w, h);
        }
        have += p.state > 0;
    }
    g_on = GetPrivateProfileIntA("UIMod", "MenuHD", kMenuHdDefault, ini) != 0 ? 1 : 0;
    if (!DetourLoadPcx()) {
        Log("[menuhd] could not detour Buffer_load_pcx -> HD menu NOT installed\n");
        return;
    }
    g_copy = reinterpret_cast<FCopy3>(At(kVA_Copy3));
    g_drawItem = reinterpret_cast<FDrawItem>(At(kVA_DrawItem));
    for (uint32_t site : kCopySites) Retarget(site, reinterpret_cast<const void*>(&CopyHook));
    for (uint32_t site : kDrawItemSites) Retarget(site, reinterpret_cast<const void*>(&DrawItemHook));
    g_installed = true;
    Log("[menuhd] installed: HD main menu + planet setup from menu\\hd\\ (%d of 30 pieces, %d unusable; Buffer_load_pcx "
        "entry + 2 stretches + 5 draw_item calls), %s\n", have, bad, g_on ? "on" : "off ([UIMod] MenuHD=0)");
}
