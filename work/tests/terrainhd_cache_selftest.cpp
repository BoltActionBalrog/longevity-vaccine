// terrainhd.cpp's own bookkeeping, run against a fake engine (tests\test_terrainhd_cache.py builds it once, writes the
// pack once for the module, and runs one scenario per process):
//   terrainhd_cache_selftest <game dir> make_pack      -- writes <game dir>\terrain\texture_x8.pcx
//   terrainhd_cache_selftest <game dir> <scenario>     -- the pack is already there (copied by the test)
// Prints "ok <check>" / "FAIL <check>: <detail>" lines; exit code 0 only when every check passed.
//
// terrainhd.cpp is compiled in this file with TERRAINHD_SELFTEST: its image base is a fake exe image (the call sites,
// the span stores, the RAINFALL colour lists, the engine functions' entry bytes, the loading canvas and the screen
// size live in it; the installer writes its 100 span sites there), its game folder is the test's, and its engine
// functions are the fakes below. texture.pcx and
// terrain\texture_x8.pcx are real PCX files on disk, read by the real hdpack reader.
//
// The fakes follow the engine where the hook depends on it: mem_get never returns null (the engine exits instead;
// the fake aborts, so a test that reached it fails); a Buffer keeps its pixels at +0x54 with the lock pointer +0x50
// null outside a lock; Texture_extract_2 returns 0x10 without a Buffer and 3 for a rect outside it, the only quiet
// failures it has, and allocates its bits through mem_get.
#define TERRAINHD_SELFTEST
#include "../../src/uimod/src/terrainhd.cpp"

#include <string>
#include <vector>

// ---- what terrainhd.cpp links against ------------------------------------------------------------------------------

static std::vector<std::string> g_log;
void UimodLog(const char* msg) { g_log.push_back(std::string("LOG ") + msg); }
void UimodDbg(const char* msg) { g_log.push_back(std::string("DBG ") + msg); }
bool PrefsTabInstalled() { return true; }

// ---- the fake engine -------------------------------------------------------------------------------------------

constexpr int kBufLock = 0x50, kBufBits = 0x54, kBufW = 0x80, kBufH = 0x84, kBufPitch = 0x4A8, kBufSize = 0x588;

static int g_liveBits = 0;               // engine bit blocks held (every Texture's)
static void (*g_inGen)() = nullptr;      // what a terrain pass draws

static Texture* T(void* t) { return static_cast<Texture*>(t); }
static int& Heap(void* t) { return *reinterpret_cast<int*>(static_cast<uint8_t*>(t) + kTexHeap); }

static void* __cdecl FakeAlloc(size_t n)
{
    void* p = malloc(n);
    if (!p) { std::printf("FAIL mem_get returned null (the engine would exit)\n"); std::exit(3); }
    ++g_liveBits;
    return p;
}

static void __cdecl FakeFree(void* p)
{
    if (p) { free(p); --g_liveBits; }
}

static int __fastcall FakeExtract(void* tex, void*, void* src, int x, int y, int w, int h, void*)
{
    Texture* t = T(tex);
    if (!src) return 0x10;
    if (t->data && Heap(tex) == 0) FakeFree(t->data);
    t->data = nullptr; t->w = 0; t->h = 0; Heap(tex) = 0;
    uint8_t* b = static_cast<uint8_t*>(src);
    if (x + w > *reinterpret_cast<int*>(b + kBufW) || y + h > -*reinterpret_cast<int*>(b + kBufH)) return 3;
    const uint8_t* p = *reinterpret_cast<uint8_t**>(b + kBufBits);   // the lock pointer +0x50 is null here
    const int pitch = *reinterpret_cast<int*>(b + kBufPitch);
    t->w = w; t->h = h;
    t->data = static_cast<uint8_t*>(FakeAlloc(static_cast<size_t>(w) * h));
    for (int r = 0; r < h; ++r) memcpy(t->data + r * w, p + (y + r) * pitch + x, w);
    return 0;
}

static int __cdecl FakeGen(void*, void*, int, int, int, int, int, int, int, int)
{
    if (g_inGen) g_inGen();
    return 0;
}

static void __cdecl FakeDrawMap(int) {}
static int __fastcall FakeStatusRedraw(void*, void*) { return 0; }
static void __fastcall FakeGraphicRedraw(void*, void*) {}

// ---- the world ---------------------------------------------------------------------------------------------------

static std::string g_root;
static int g_fails = 0;

static void Check(bool ok, const char* what, const std::string& detail = "")
{
    if (ok) std::printf("ok %s\n", what);
    else { std::printf("FAIL %s: %s\n", what, detail.c_str()); ++g_fails; }
}

static std::string Num(long long v) { return std::to_string(v); }

constexpr int kSheetTex = 6, kRainTex = 2, kAll = kSheetTex + kRainTex;
alignas(16) static uint8_t g_tex[kAll][kTexSize];      // the "static" Textures load_terrain cuts into
alignas(16) static uint8_t g_borderTex[kTexSize];       // the territory border (60x60, from its own Buffer)
alignas(16) static uint8_t g_borderBuf[kBufSize + 0x80];
static uint8_t g_borderPx[60][60];
alignas(16) static uint8_t g_rainBuf[kBufSize + 0x80];  // the local buffer the RAINFALL composites come from
static uint8_t g_stockSheet[768][1024];                 // TEXTURE.PCX as loaded (file + 10)
static uint8_t g_rainPx[56][112];

static int CellX(int i) { return 1 + 57 * (i % 3); }
static int CellY(int i) { return 1 + 57 * (i / 3) + (i >= 3 ? 57 * 4 : 0); }   // two bands
// the pack's cell for texture i: one colour per texture, with a 1-px mark at the cell's own (1, 2) at 8x
static uint8_t FileIndex(int i) { return static_cast<uint8_t>(40 + 11 * i); }
static constexpr uint8_t kMark = 5;

static void Header(FILE* f, int w, int h)
{
    uint8_t hdr[128] = {};
    hdr[0] = 10; hdr[1] = 5; hdr[2] = 1; hdr[3] = 8;
    hdr[8] = static_cast<uint8_t>((w - 1) & 255); hdr[9] = static_cast<uint8_t>((w - 1) >> 8);
    hdr[10] = static_cast<uint8_t>((h - 1) & 255); hdr[11] = static_cast<uint8_t>((h - 1) >> 8);
    hdr[65] = 1;
    hdr[66] = static_cast<uint8_t>(w & 255); hdr[67] = static_cast<uint8_t>(w >> 8);
    fwrite(hdr, 1, 128, f);
}

static void Trailer(FILE* f)
{
    fputc(0x0C, f);
    for (int i = 0; i < 768; ++i) fputc((i * 7) & 255, f);
}

static void WriteRle(FILE* f, const uint8_t* row, int w)
{
    for (int x = 0; x < w;) {
        int n = 1;
        while (x + n < w && row[x + n] == row[x] && n < 63) ++n;
        if (n > 1 || row[x] >= 0xC0) { fputc(0xC0 | n, f); fputc(row[x], f); }
        else fputc(row[x], f);
        x += n;
    }
}

static std::string PackPathT() { return g_root + "terrain\\texture_x8.pcx"; }

static void WriteStock()
{
    for (const char* name : { "texture.pcx", "rainfall.pcx" }) {
        FILE* f = nullptr;
        fopen_s(&f, (g_root + name).c_str(), "wb");
        Header(f, 1, 1);
        fputc(0, f);
        Trailer(f);
        fclose(f);
    }
}

// terrain\rainfall_x8.pcx: see-through (255) but for the composite region (both cells: colour kCompColours[5]) and
// the border region (kBorderColours[3]), each when asked for. Variants: the composites' region filled with `compFill`
// instead (254: blanked with RAINFALL.PCX's frame colour); the border's first 8x row of 8 texels (64 pack pixels at
// 8x) in colour 252 (see-through to the engine as well) and its second texel row's first texel in colour 1 (unlisted).
static void WriteRainPack(bool comp, bool border, int compFill = -1, bool borderOdd = false)
{
    const int W = 640 * 8, H = 480 * 8;
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "terrain\\rainfall_x8.pcx").c_str(), "wb");
    Header(f, W, H);
    std::vector<uint8_t> row(W);
    for (int y = 0; y < H; ++y) {
        memset(row.data(), 255, W);
        if ((comp || compFill >= 0) && y >= 333 * 8 && y < 389 * 8)
            memset(row.data() + 2 * 8, compFill >= 0 ? compFill : kCompColours[5], 113 * 8);
        if (border && y >= 254 * 8 && y < 314 * 8) {
            memset(row.data() + 2 * 8, kBorderColours[3], 60 * 8);
            if (borderOdd && y < 255 * 8) memset(row.data() + 2 * 8, 252, 8 * 8);
            if (borderOdd && y >= 255 * 8 && y < 256 * 8) memset(row.data() + 2 * 8, 1, 8);
        }
        WriteRle(f, row.data(), W);
    }
    Trailer(f);
    fclose(f);
}

static void WriteJunkRainPack()
{
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "terrain\\rainfall_x8.pcx").c_str(), "wb");
    fputs("damaged", f);
    fclose(f);
}

// texture_x8.pcx: each test texture's 448 x 448 cell one colour (FileIndex) with the mark at (1, 2), the rest index 3;
// the cells at `blank` (stock x, y) all see-through 255 -- pieces the pack does not supply.
static void WritePack(const std::vector<std::pair<int, int>>& blank = {})
{
    const int W = 1024 * 8, H = 768 * 8;
    FILE* f = nullptr;
    fopen_s(&f, PackPathT().c_str(), "wb");
    Header(f, W, H);
    std::vector<uint8_t> row(W);
    for (int y = 0; y < H; ++y) {
        memset(row.data(), 3, W);
        for (int i = 0; i < kSheetTex; ++i)
            if (y >= CellY(i) * 8 && y < (CellY(i) + 56) * 8) {
                memset(row.data() + CellX(i) * 8, FileIndex(i), 56 * 8);
                if (y == CellY(i) * 8 + 2) row[CellX(i) * 8 + 1] = kMark;
            }
        for (const auto& b : blank)
            if (y >= b.second * 8 && y < (b.second + 56) * 8) memset(row.data() + b.first * 8, 255, 56 * 8);
        WriteRle(f, row.data(), W);
    }
    Trailer(f);
    fclose(f);
}

static std::vector<char> g_goodPack;
static void KeepPack()
{
    FILE* f = nullptr;
    fopen_s(&f, PackPathT().c_str(), "rb");
    fseek(f, 0, SEEK_END);
    g_goodPack.resize(ftell(f));
    fseek(f, 0, SEEK_SET);
    fread(g_goodPack.data(), 1, g_goodPack.size(), f);
    fclose(f);
}

static void PutPackBack()
{
    FILE* f = nullptr;
    fopen_s(&f, PackPathT().c_str(), "wb");
    fwrite(g_goodPack.data(), 1, g_goodPack.size(), f);
    fclose(f);
}

static void WriteJunkPack()
{
    FILE* f = nullptr;
    fopen_s(&f, PackPathT().c_str(), "wb");
    fputs("damaged", f);
    fclose(f);
}

static void WriteIni(int on)
{
    WritePrivateProfileStringA("UIMod", "TerrainHD", on ? "1" : "0", (g_root + "Alpha Centauri.ini").c_str());
}

// a Buffer the engine's way: pixels at +0x54, the lock pointer +0x50 null, height stored negative at +0x84
static void SetBuffer(void* b, void* px, int w, int h, int pitch)
{
    uint8_t* p = static_cast<uint8_t*>(b);
    *reinterpret_cast<void**>(p + kBufLock) = nullptr;
    *reinterpret_cast<void**>(p + kBufBits) = px;
    *reinterpret_cast<int*>(p + kBufW) = w;
    *reinterpret_cast<int*>(p + kBufH) = -h;
    *reinterpret_cast<int*>(p + kBufPitch) = pitch;
}

// load_terrain: every texture cut at stock through the (retargeted) extract sites.
static void LoadTerrain()
{
    for (int i = 0; i < kSheetTex; ++i)
        ExtractRecorder(T(g_tex[i]), nullptr, At(kVA_LoadingCanvas), CellX(i), CellY(i), 56, 56, nullptr);
    for (int i = 0; i < kRainTex; ++i)
        ExtractRecorder(T(g_tex[kSheetTex + i]), nullptr, g_rainBuf, 56 * i, 0, 56, 56, nullptr);
    ExtractRecorder(T(g_borderTex), nullptr, g_borderBuf, 0, 0, 60, 60, nullptr);
}

static bool BorderStock()
{
    const Texture* t = T(g_borderTex);
    if (t->w != 60 || t->h != 60 || !t->data) return false;
    for (int y = 0; y < 60; ++y) if (memcmp(t->data + y * 60, g_borderPx[y], 60) != 0) return false;
    return true;
}

static bool BorderListed()
{
    for (uint32_t i = 0; i < g_span.count; ++i) if (g_span.ptrs[i] == T(g_borderTex)->data) return true;
    return false;
}

static void Pass() { GenTerrainPolyHook(nullptr, nullptr, 0, 0, 0, 0, 0, 0, 0, 0); }
static void Passes(int n) { for (int i = 0; i < n; ++i) Pass(); }

static void Screen(int w, int h)
{
    *reinterpret_cast<int*>(At(kVA_ScreenW)) = w;
    *reinterpret_cast<int*>(At(kVA_ScreenH)) = h;
}

// the span stubs' list of ours: the recorded textures' bits and log2 k at a level, empty at stock
static bool BorderListed();
static bool SpanListIs(int k)
{
    if (k == 1) return g_span.count == 0 && g_span.levelShift == 0;
    if (g_span.count != static_cast<uint32_t>(kAll + (BorderListed() ? 1 : 0)) || g_span.levelShift != static_cast<uint32_t>(k == 2 ? 1 : k == 4 ? 2 : 3))
        return false;
    for (int i = 0; i < kAll; ++i) if (g_span.ptrs[i] != T(g_tex[i])->data) return false;
    return true;
}

static bool AllAt(int side)
{
    for (int i = 0; i < kAll; ++i) if (T(g_tex[i])->w != side || T(g_tex[i])->h != side || !T(g_tex[i])->data) return false;
    return true;
}

static bool EveryTextureHasBits()
{
    for (int i = 0; i < kAll; ++i) if (!T(g_tex[i])->data || T(g_tex[i])->w <= 0) return false;
    return true;
}

static bool StockPixels()
{
    for (int i = 0; i < kSheetTex; ++i) {
        const Texture* t = T(g_tex[i]);
        if (t->w != 56 || t->h != 56 || !t->data) return false;
        for (int y = 0; y < 56; ++y)
            if (memcmp(t->data + y * 56, &g_stockSheet[CellY(i) + y][CellX(i)], 56) != 0) return false;
    }
    for (int i = 0; i < kRainTex; ++i) {
        const Texture* t = T(g_tex[kSheetTex + i]);
        if (t->w != 56 || t->h != 56 || !t->data) return false;
        for (int y = 0; y < 56; ++y) if (memcmp(t->data + y * 56, &g_rainPx[y][56 * i], 56) != 0) return false;
    }
    return true;
}

// off / failed: the stock textures and UVs, no stock copy, no overlay copy, only the textures' own bits
static bool HoldsNothing()
{
    return !g_stock && g_level == 1 && SpanListIs(1) && g_liveBits == kAll + 1 && BorderStock();
}

static int Logged(const char* needle)
{
    int n = 0;
    for (const std::string& l : g_log) if (l.find(needle) != std::string::npos) ++n;
    return n;
}

static void MakeImage()
{
    g_testImage = static_cast<BYTE*>(VirtualAlloc(nullptr, 0x700000, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    const auto call = [](uint32_t site, uintptr_t target) {
        BYTE* p = At(site);
        p[0] = 0xE8;
        const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(At(target)) - (reinterpret_cast<uintptr_t>(p) + 5));
        memcpy(p + 1, &rel, 4);
    };
    for (uint32_t s : kExtractSites) call(s, kVA_Extract2);
    for (uint32_t s : kGenSites) call(s, kVA_GenTerrainPoly);
    for (int i = 0; i < 100; ++i) {                         // the span stores: u, v, du, dv as in the exe
        static const uint8_t st[4][6] = { { 0xA3, 0xF8, 0xB4, 0x9B, 0x00, 0x00 }, { 0x89, 0x15, 0x3C, 0xB5, 0x9B, 0x00 },
                                          { 0xDB, 0x1D, 0xE4, 0xB4, 0x9B, 0x00 }, { 0xDB, 0x1D, 0xC8, 0xB4, 0x9B, 0x00 } };
        int kind = i % 4;
        if (i / 4 == 15 || i / 4 == 18) kind = kind < 2 ? 1 - kind : kind;    // v before u, as in the exe
        memcpy(At(kSpanSites[i]), st[kind], kind == 0 ? 5 : 6);
    }
    for (const Entry8& f : kEntries) memcpy(At(f.va), f.b, sizeof f.b);
    Screen(1920, 1080);
    for (int y = 0; y < 768; ++y)
        for (int x = 0; x < 1024; ++x) g_stockSheet[y][x] = static_cast<uint8_t>(10 + (x * 3 + y * 5) % 200);
    SetBuffer(At(kVA_LoadingCanvas), g_stockSheet, 1024, 768, 1024);
    for (int y = 0; y < 56; ++y)
        for (int x = 0; x < 112; ++x) g_rainPx[y][x] = static_cast<uint8_t>(100 + (x + y) % 50);
    SetBuffer(g_rainBuf, g_rainPx, 112, 56, 112);
    for (int y = 0; y < 60; ++y)
        for (int x = 0; x < 60; ++x) g_borderPx[y][x] = static_cast<uint8_t>((x + y) % 10);
    SetBuffer(g_borderBuf, g_borderPx, 60, 60, 60);
    memcpy(At(kVA_CompColours), kCompColours, sizeof kCompColours);
    for (int i = 0; i < 9; ++i) {
        BYTE* m = At(kVA_BorderMovs) + 4 * i;
        m[0] = 0xC6; m[1] = 0x45; m[2] = static_cast<BYTE>(0xE4 + i); m[3] = kBorderColours[i];
    }
}

static void Install()
{
    g_eng.extract = reinterpret_cast<decltype(g_eng.extract)>(&FakeExtract);
    g_eng.gen = &FakeGen;
    g_eng.alloc = &FakeAlloc;
    g_eng.free = &FakeFree;
    g_eng.drawMap = &FakeDrawMap;
    g_eng.statusRedraw = reinterpret_cast<decltype(g_eng.statusRedraw)>(&FakeStatusRedraw);
    g_eng.graphicRedraw = reinterpret_cast<decltype(g_eng.graphicRedraw)>(&FakeGraphicRedraw);
    InstallTerrainHd();
}

// ---- scenarios ---------------------------------------------------------------------------------------------------

// TerrainHD=0 at start: nothing cut; on cuts the level at the next pass; off puts the exact stock back, holds nothing.
static void OffHoldsNothing()
{
    WriteStock(); WriteIni(0);
    Install();
    Check(g_installed && g_on == 0, "installed, off from the ini");
    Check(Logged("installed: terrain\\texture_x8.pcx (22") == 1 && Logged(" for 0x0") == 0,
          "the install line names no level (the screen is not known yet)");
    LoadTerrain();
    Pass();
    Check(AllAt(56) && StockPixels() && HoldsNothing(), "off: stock textures, stock UVs, nothing held");
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "on: every texture at 4x (1920x1080)", Num(g_level));
    Check(SpanListIs(4), "on: the span stubs' list is the 8 textures' bits, shift 2");
    Check(T(g_tex[2])->data[0] == static_cast<uint8_t>(FileIndex(2) + 10), "a sheet texture is the pack's cell",
          Num(T(g_tex[2])->data[0]));
    Check(T(g_tex[kSheetTex])->data[0] == g_rainPx[0][0] && T(g_tex[kSheetTex])->data[3] == g_rainPx[0][0] &&
              T(g_tex[kSheetTex])->data[4] == g_rainPx[0][1], "a RAINFALL composite is its stock pixels at 4x");
    Check(Logged("8 textures at 4x (6 from texture_x8.pcx, ") == 1, "the log counts the textures from the pack");
    TerrainHdSet(0);
    Check(StockPixels() && HoldsNothing(), "off: the exact stock textures and UVs back, nothing held",
          Num(g_liveBits));
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "on again: 4x");
}

// A new game while at a level: load_terrain's stock cuts put the UVs back at once; the next pass cuts the level.
// The level follows the screen: 2x at 1024x768, 4x at 1280x1024, 8x at 2560x1440 (the cell as painted).
static void NewGameAndLevels()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    Pass();
    Check(g_level == 4, "game 1 at 4x");
    LoadTerrain();
    Check(g_level == 1 && SpanListIs(1) && !g_stock && AllAt(56) && EveryTextureHasBits(),
          "load_terrain: stock textures, stock UVs");
    Pass();
    Check(g_level == 4 && AllAt(224), "game 2 at 4x");
    Screen(1024, 768);
    Pass();
    Check(g_level == 2 && AllAt(112) && SpanListIs(2), "1024x768: 2x", Num(g_level));
    Screen(1280, 1024);
    Pass();
    Check(g_level == 4 && AllAt(224), "1280x1024: 4x (the real tile is 184 px)", Num(g_level));
    Screen(2560, 1440);
    Pass();
    Check(g_level == 8 && AllAt(448) && SpanListIs(8), "2560x1440: 8x", Num(g_level));
    const Texture* t = T(g_tex[4]);
    const uint8_t c = static_cast<uint8_t>(FileIndex(4) + 10), m = static_cast<uint8_t>(kMark + 10);
    Check(t->data[2 * 448 + 1] == m && t->data[2 * 448 + 0] == c && t->data[2 * 448 + 2] == c && t->data[448 + 1] == c,
          "8x: the cell as painted (its 1-px mark kept where it is)");
    Check(g_liveBits == kAll + 1, "one block of bits per texture", Num(g_liveBits));
}

// PRACX's Alt+T overlays (and every texture not cut by load_terrain) are never in the list of ours: the span stubs
// multiply their coordinates by 1, so they draw natively at any level, with no copy made.
alignas(16) static uint8_t g_overlay[kTexSize];
static uint8_t g_overlayBits[56 * 56];

static void Overlays()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    Texture* o = T(g_overlay);
    o->data = g_overlayBits; o->w = 56; o->h = 56; Heap(o) = 1;   // prax.dll's own bits
    Pass();
    bool listed = false;
    for (uint32_t i = 0; i < g_span.count; ++i) listed |= g_span.ptrs[i] == o->data;
    Check(g_level == 4 && SpanListIs(4) && !listed && o->data == g_overlayBits && o->w == 56,
          "at 4x: the overlay is not ours, untouched, nothing copied");
    Check(g_liveBits == kAll + 1, "no copy allocated", Num(g_liveBits));
}

// The pack damaged after install: the level is refused once (one read, one log line), then every later pass does no
// work; off holds nothing; switching on tries once more; a good pack again and the row switched: the level.
static void PackDamagedLater()
{
    WriteStock(); WriteIni(0);
    Install();
    LoadTerrain();
    WriteJunkPack();
    const int loads = g_testPackLoads;
    TerrainHdSet(1);
    Passes(5);
    Check(g_installed && g_failed && g_level == 1 && StockPixels() && HoldsNothing(), "damaged later: stock, nothing held");
    Check(g_testPackLoads == loads + 1 && Logged("not usable") == 1, "five passes: the pack read once, logged once",
          Num(g_testPackLoads - loads));
    TerrainHdSet(0);
    Check(HoldsNothing(), "off: nothing held");
    TerrainHdSet(1);
    Passes(3);
    Check(g_testPackLoads == loads + 2 && Logged("not usable") == 2 && g_level == 1, "switched on again: tried once more");
    PutPackBack();
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224) && !g_failed, "the pack good again, the row switched: 4x");
}

// No address room for the level: refused before the first allocation and before the pack is read; decided once.
static void NoRoom()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    g_testNoRoom = true;
    const int loads = g_testPackLoads, bits = g_liveBits;
    Passes(5);
    Check(g_failed && g_level == 1 && StockPixels() && HoldsNothing(), "no room: stock, nothing held");
    Check(Logged("no address room") == 1 && g_testPackLoads == loads && g_liveBits == bits,
          "five passes: logged once, no pack read, no allocation");
    g_testNoRoom = false;
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "room again, the row switched: 4x");
}

// At a level, a new level that cannot be made (the screen changes, no room): everything back to stock, the list of
// ours empty, nothing held, no work on later passes; and off after it holds nothing.
static void FailedAfterALevel()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    Pass();
    Check(g_level == 4 && SpanListIs(4), "at 4x");
    Screen(2560, 1440);
    g_testNoRoom = true;
    Passes(4);
    Check(g_failed && g_level == 1 && StockPixels() && HoldsNothing() && EveryTextureHasBits(),
          "the 8x level refused: every texture stock with bits, the list empty, nothing held", Num(g_liveBits));
    Check(Logged("no address room for the 8x level") == 1, "logged once");
    TerrainHdSet(0);
    Check(HoldsNothing(), "off after the failure: nothing held");
    g_testNoRoom = false;
}

// RAINFALL art for both pieces: the composites and the border are code maps from it (the border 60k wide, in the list,
// with a 60x60 cut's corner coordinates); off puts the border's stock pixels back. Without the border's piece the
// border stays stock and is not ours; without rainfall_x8.pcx at all (every other scenario) the same.
static void RainArt()
{
    WriteStock(); WriteRainPack(true, true); WriteIni(1);
    Install();
    LoadTerrain();
    Pass();
    const Texture* c = T(g_tex[kSheetTex]);
    const Texture* b = T(g_borderTex);
    bool comp5 = c->w == 224, bord3 = b->w == 240;
    for (int i = 0; comp5 && i < 224 * 224; ++i) comp5 = c->data[i] == 5;
    for (int i = 0; bord3 && i < 240 * 240; ++i) bord3 = b->data[i] == 3;
    Check(g_level == 4 && comp5, "a composite is the art's code map (colour 5 of the list -> 5)");
    Check(bord3 && BorderListed() && SpanListIs(4), "the border is the art's code map at 4x, and ours");
    Check(reinterpret_cast<const int32_t*>(b)[0x14 / 4] == 59 && reinterpret_cast<const int32_t*>(b)[0x20 / 4] == 59,
          "the border keeps a 60x60 cut's corner coordinates");
    Check(Logged("2 from rainfall_x8.pcx") == 0 && Logged("3 from rainfall_x8.pcx") == 1, "logged: 3 from the art");
    TerrainHdSet(0);
    Check(BorderStock() && StockPixels() && HoldsNothing(), "off: the border's stock pixels back, nothing held");
}

static void RainCompositesOnly()
{
    WriteStock(); WriteRainPack(true, false); WriteIni(1);
    Install();
    LoadTerrain();
    Pass();
    Check(g_level == 4 && T(g_tex[kSheetTex])->data[0] == 5, "the composites from the art");
    Check(BorderStock() && !BorderListed() && SpanListIs(4), "no border in the art: the border stock, not ours");
}

// Back to stock from every level never leaves a texture without bits, and each texture holds one block.
static void RestoreFromEveryLevel()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    const int screens[3][2] = { { 1024, 768 }, { 1920, 1080 }, { 2560, 1440 } };
    for (const auto& s : screens) {
        Screen(s[0], s[1]);
        Pass();
        const int k = g_level;
        TerrainHdSet(0);
        Check(EveryTextureHasBits() && StockPixels() && HoldsNothing(), ("from " + Num(k) + "x: all stock").c_str(),
              Num(g_liveBits));
        TerrainHdSet(1);
    }
}

// No usable pack: not installed, nothing patched.
static void BadPack()
{
    WriteStock(); WriteJunkPack(); WriteIni(1);
    Install();
    Check(!g_installed && Logged("not usable") == 1, "a damaged pack at start: not installed");
    Check(At(kExtractSites[0])[0] == 0xE8 && CallsTo(kExtractSites[0], kVA_Extract2), "nothing patched");
}

// A span store that is not the one the hook knows: not installed, nothing patched, no row, logged once.
static void BadSpanBytes()
{
    WriteStock(); WriteIni(1);
    At(kSpanSites[57])[0] = 0x90;
    Install();
    Check(!g_installed && Logged("unexpected bytes at a span store") == 1, "a changed span store: not installed");
    Check(CallsTo(kExtractSites[0], kVA_Extract2) && CallsTo(kGenSites[0], kVA_GenTerrainPoly),
          "nothing patched");
}

// ---- the installer's own writes, and refused installs --------------------------------------------------------------

static std::vector<uint8_t> SpanBytes()
{
    std::vector<uint8_t> v;
    for (uint32_t s : kSpanSites) v.insert(v.end(), At(s), At(s) + 6);
    return v;
}

// Installed: each of the 100 span sites is a call into its own stub in the stubs' page (6-byte stores: then a nop),
// the byte after a 5-byte store untouched, and the page holds exactly what BuildSpanStubs generates for it.
static void InstallWritesSites()
{
    WriteStock(); WriteIni(1);
    const std::vector<uint8_t> before = SpanBytes();
    uint8_t orig[100][6], patch[100][6];
    for (int i = 0; i < 100; ++i) memcpy(orig[i], At(kSpanSites[i]), 6);
    Install();
    Check(g_installed && g_spanArea != nullptr, "installed, with a stubs page");
    int good = 0;
    for (int i = 0; i < 100; ++i) {
        const BYTE* p = At(kSpanSites[i]);
        int32_t rel;
        memcpy(&rel, p + 1, 4);
        const uintptr_t to = kSpanSites[i] + 5 + rel;          // rel32 is for the site's VA (the real image's address)
        const size_t n = SpanStoreBytes(orig[i]);
        // after a 5-byte store: the next store's first byte -- itself a patched site (E8) when it is one
        bool nextSite = false;
        for (uint32_t s : kSpanSites) nextSite |= s == kSpanSites[i] + 5;
        good += p[0] == 0xE8 && to == reinterpret_cast<uintptr_t>(g_spanArea) + kLookupBytes + kStubBytes * i &&
                (n == 6 ? p[5] == 0x90 : nextSite ? p[5] == 0xE8 : p[5] == before[6 * i + 5]);
    }
    Check(good == 100, "the 100 span sites call their own stubs (a nop after a 6-byte store)", Num(good));
    static uint8_t want[kStubArea];
    const bool built = BuildSpanStubs(want, static_cast<uint32_t>(reinterpret_cast<uintptr_t>(g_spanArea)),
                                      static_cast<uint32_t>(reinterpret_cast<uintptr_t>(&g_span)), orig, patch);
    Check(built && memcmp(want, g_spanArea, kStubArea) == 0, "the stubs page is the generated stubs");
    MEMORY_BASIC_INFORMATION mi = {};
    VirtualQuery(g_spanArea, &mi, sizeof mi);
    Check(mi.Protect == PAGE_EXECUTE_READ, "the stubs page is execute-read", Num(mi.Protect));
}

// Refused installs write nothing: a damaged pack, a span store with other bytes, a span page that cannot be made
// writable. The span sites, the extract and terrain-pass calls all as they were.
static void RefusedInstallsWriteNothing()
{
    WriteStock(); WriteIni(1);
    std::vector<uint8_t> sites = SpanBytes();
    WriteJunkPack();
    Install();
    Check(!g_installed && SpanBytes() == sites && CallsTo(kExtractSites[0], kVA_Extract2),
          "a damaged pack: nothing written");
    PutPackBack();
    g_log.clear();
    g_testSpanLocked = true;
    Install();
    Check(!g_installed && Logged("could not patch the span stores") == 1, "a span page not writable: not installed");
    Check(SpanBytes() == sites && CallsTo(kExtractSites[0], kVA_Extract2) && CallsTo(kGenSites[0], kVA_GenTerrainPoly),
          "... and nothing written");
    g_testSpanLocked = false;
    At(kSpanSites[57])[0] = 0x90;
    sites = SpanBytes();
    Install();
    Check(!g_installed && SpanBytes() == sites, "a changed span store: the 100 sites as they were");
}

// ---- blank cells -------------------------------------------------------------------------------------------------

alignas(16) static uint8_t g_ocean[kTexSize];          // the ocean texture (TEXTURE.PCX 280, 79)

// A cell the pack leaves blank stays stock: its bits, its size, not in the list (multiplied by 1), the rest at the
// level. A blank ocean cell is the exception (the coast composites share its UVs): its stock pixels at the level.
static void BlankCells()
{
    WriteStock(); WriteIni(1);
    WritePack({ { CellX(1), CellY(1) }, { 280, 79 } });
    Install();
    LoadTerrain();
    ExtractRecorder(T(g_ocean), nullptr, At(kVA_LoadingCanvas), 280, 79, 56, 56, nullptr);
    uint8_t* const blankBits = T(g_tex[1])->data;
    Pass();
    const Texture* b = T(g_tex[1]);
    bool stockPx = b->w == 56 && b->h == 56 && b->data == blankBits;
    for (int y = 0; stockPx && y < 56; ++y)
        stockPx = memcmp(b->data + y * 56, &g_stockSheet[CellY(1) + y][CellX(1)], 56) == 0;
    bool listed = false, oceanListed = false;
    for (uint32_t i = 0; i < g_span.count; ++i) {
        listed |= g_span.ptrs[i] == b->data;
        oceanListed |= g_span.ptrs[i] == T(g_ocean)->data;
    }
    Check(g_level == 4 && stockPx && !listed, "the blank cell: its stock bits and size, not in the list");
    bool others = true;
    for (int i = 0; i < kAll; ++i) if (i != 1) others &= T(g_tex[i])->w == 224;
    Check(others && g_span.count == kAll - 1 + 1, "the other textures at 4x and listed", Num(g_span.count));
    const Texture* o = T(g_ocean);
    bool oceanStock4 = o->w == 224;
    for (int y = 0; oceanStock4 && y < 224; ++y)
        for (int x = 0; oceanStock4 && x < 224; ++x)
            oceanStock4 = o->data[y * 224 + x] == g_stockSheet[79 + y / 4][280 + x / 4];
    Check(oceanStock4 && oceanListed, "a blank ocean cell: its own stock pixels at 4x, listed");
    Check(Logged("2 cells are blank in texture_x8.pcx") == 1, "logged: 2 blank cells");
    TerrainHdSet(0);
    Check(T(g_tex[1])->data == blankBits && T(g_tex[1])->w == 56 && T(g_ocean)->w == 56 && StockPixels(),
          "off: all stock, the blank one never touched");
    PutPackBack();
}

// ---- the rain pack, decided once -----------------------------------------------------------------------------------

// A damaged rainfall_x8.pcx: proven at install (read once, logged once), not opened at the cuts after it (two loads, a
// level change); switching the row on tries it once more. The map: stock coast composites at the level, stock border.
static void RainPackDamaged()
{
    WriteStock(); WriteJunkRainPack(); WriteIni(1);
    Install();
    Check(g_installed && g_testRainLoads == 1 && Logged("rainfall_x8.pcx is not usable") == 1,
          "install: read once, logged once", Num(g_testRainLoads));
    LoadTerrain();
    Pass();
    LoadTerrain();
    Passes(3);
    Screen(2560, 1440);
    Pass();
    Check(g_level == 8 && g_testRainLoads == 1 && Logged("rainfall_x8.pcx is not usable") == 1,
          "three cuts: not opened again, not logged again", Num(g_testRainLoads));
    Check(BorderStock() && !BorderListed() && T(g_tex[kSheetTex])->w == 448, "stock border, composites at the level");
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_testRainLoads == 2 && Logged("rainfall_x8.pcx is not usable") == 2, "the row switched: tried once more");
    WriteRainPack(true, true);
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_testRainLoads == 3 && BorderListed() && T(g_borderTex)->data[0] == 3, "good again, the row switched: used");
}

// The exe's colour lists are not the known ones: rainfall_x8.pcx is never opened (not at install, not at a cut).
static void RainListsDiffer()
{
    WriteStock(); WriteRainPack(true, true); WriteIni(1);
    At(kVA_CompColours)[3] ^= 1;
    Install();
    LoadTerrain();
    Passes(2);
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_installed && g_level == 4 && g_testRainLoads == 0, "never opened", Num(g_testRainLoads));
    Check(Logged("colour lists or palette are not the known ones") == 1 && BorderStock() && !BorderListed(),
          "logged once at install; the border stock");
}

// What counts as supplied: composites blanked with the frame colour 254 (no listed colour) fall back to their stock
// pixels; in the border, 252 is see-through (the background 9) and an unlisted colour is code 0, counted in the log.
static void RainPieces()
{
    WriteStock(); WriteRainPack(false, true, 254, true); WriteIni(1);
    Install();
    LoadTerrain();
    Pass();
    const Texture* c = T(g_tex[kSheetTex]);
    Check(g_level == 4 && c->w == 224 && c->data[0] == g_rainPx[0][0] && c->data[4] == g_rainPx[0][1],
          "composites blanked with 254: not supplied, their stock pixels at 4x");
    const Texture* b = T(g_borderTex);
    Check(b->w == 240 && b->data[0] == 9 && b->data[31] == 9 && b->data[32] == 3 && b->data[4 * 240] == 0 &&
              b->data[4 * 240 + 3] == 0 && b->data[4 * 240 + 4] == 3 && b->data[8 * 240] == 3,
          "the border: 252 -> the background 9, an unlisted colour -> 0, the rest its code");
    Check(Logged("16 texels of the territory border are not one of its colours") == 1 &&
              Logged("composite are not") == 0, "the unlisted texels counted in the log");
    Check(Logged("1 from rainfall_x8.pcx") == 1, "1 piece from the art (the border)");
}

// ---- cuts that fail halfway ----------------------------------------------------------------------------------------

// The second band of a cut cannot be read: the textures the first band cut go back -- all stock, nothing held, decided
// once.
static void BandFailsMidway()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    g_testBandFailsAt = 1;
    Passes(4);
    Check(g_failed && g_level == 1 && StockPixels() && HoldsNothing() && EveryTextureHasBits(),
          "a band unreadable halfway: all stock, nothing held", Num(g_liveBits));
    Check(Logged("could not read the band") == 1, "logged once");
    g_testBandFailsAt = -1;
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "readable again, the row switched: 4x");
}

// A recorded texture that is not a stock cut when the level is made (here: the engine's cut failed for it): no level,
// logged once, nothing changed.
static void NotAStockTexture()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    // a later load_terrain whose cut of texture 2 fails (a rect outside the canvas: Texture_extract_2's quiet 3)
    const int rc = ExtractRecorder(T(g_tex[2]), nullptr, At(kVA_LoadingCanvas), 1000, 1, 56, 56, nullptr);
    Check(rc == 3, "the engine's failed cut is returned as it was", Num(rc));
    const int bits = g_liveBits;
    Passes(3);
    Check(g_failed && g_level == 1 && g_liveBits == bits && !g_stock && SpanListIs(1),
          "a texture that is not a stock cut: no level, nothing allocated");
    Check(Logged("texture 2 is not a stock 56x56 texture") == 1, "logged once");
    // the next load_terrain cuts it again: switched on again, the level
    LoadTerrain();
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "cut again, the row switched: 4x");
}

// A failed cut inside ExtractRecorder while at a level: every texture is back to stock before the engine runs (the
// list of ours empty first), so with the cut failing nothing is left at the level; the cut's result is the engine's.
static void ExtractFailsAtALevel()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    Pass();
    Check(g_level == 4 && SpanListIs(4), "at 4x");
    const int rc = ExtractRecorder(T(g_tex[0]), nullptr, nullptr, 0, 0, 56, 56, nullptr);   // no Buffer: 0x10
    Check(rc == 0x10, "the engine's result returned", Num(rc));
    Check(g_level == 1 && StockPixels() && HoldsNothing() && EveryTextureHasBits(),
          "a failed cut at a level: every texture stock with bits, the list empty, nothing held", Num(g_liveBits));
}

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    g_root = argv[1];
    if (g_root.back() != '\\') g_root += '\\';
    CreateDirectoryA((g_root + "terrain").c_str(), nullptr);
    strcpy_s(g_testDir, g_root.c_str());
    const std::string s = argv[2];
    if (s == "make_pack") { WritePack(); return 0; }
    if (s.rfind("stubs ", 0) == 0) {                     // stubs <stubVa hex> <dataVa hex>: the generated bytes
        MakeImage();
        for (int i = 0; i < 100; ++i) {                  // the real exe's bytes at each site, one hex line each (stdin)
            char line[64] = {};
            if (!fgets(line, sizeof line, stdin)) return 2;
            for (int j = 0; j < 6 && line[2 * j] && line[2 * j] != '\n'; ++j) {
                unsigned v = 0;
                sscanf_s(line + 2 * j, "%2x", &v);
                At(kSpanSites[i])[j] = static_cast<uint8_t>(v);
            }
        }
        unsigned stubVa = 0, dataVa = 0;
        if (sscanf_s(s.c_str() + 6, "%x %x", &stubVa, &dataVa) != 2) return 2;
        static uint8_t area[kStubArea];
        uint8_t patch[100][6];
        if (!TerrainHdTestStubs(stubVa, dataVa, area, patch)) return 1;
        std::printf("area ");
        for (size_t i = 0; i < kStubArea; ++i) std::printf("%02x", area[i]);
        std::printf("\n");
        for (int i = 0; i < 100; ++i) {
            std::printf("site %x ", kSpanSites[i]);
            for (size_t j = 0; j < SpanStoreBytes(At(kSpanSites[i])); ++j) std::printf("%02x", patch[i][j]);
            std::printf("\n");
        }
        std::printf("data last %u shift %u count %u level %u ptrs %u\n", static_cast<unsigned>(offsetof(SpanData, last)),
                    static_cast<unsigned>(offsetof(SpanData, shift)), static_cast<unsigned>(offsetof(SpanData, count)),
                    static_cast<unsigned>(offsetof(SpanData, levelShift)), static_cast<unsigned>(offsetof(SpanData, ptrs)));
        return 0;
    }
    if (s == "corners") {                                // GiveBits' Texture fields after a cut at each size
        g_eng.alloc = &FakeAlloc;
        g_eng.free = &FakeFree;
        for (int side : { 56, 112, 224, 448 }) {
            alignas(16) uint8_t t[kTexSize] = {};
            GiveBits(T(t), side, 56, [](uint8_t*) {});
            std::printf("%d", side);
            for (int off = 0; off < kTexSize; off += 4) if (off) std::printf(" %d", *reinterpret_cast<int32_t*>(t + off));
            std::printf("\n");
        }
        return 0;
    }
    KeepPack();
    MakeImage();
    if (s == "off_holds_nothing") OffHoldsNothing();
    else if (s == "new_game_and_levels") NewGameAndLevels();
    else if (s == "overlays") Overlays();
    else if (s == "pack_damaged_later") PackDamagedLater();
    else if (s == "no_room") NoRoom();
    else if (s == "failed_after_a_level") FailedAfterALevel();
    else if (s == "restore_from_every_level") RestoreFromEveryLevel();
    else if (s == "bad_pack") BadPack();
    else if (s == "bad_span_bytes") BadSpanBytes();
    else if (s == "rain_art") RainArt();
    else if (s == "rain_composites_only") RainCompositesOnly();
    else if (s == "install_writes_sites") InstallWritesSites();
    else if (s == "refused_installs_write_nothing") RefusedInstallsWriteNothing();
    else if (s == "blank_cells") BlankCells();
    else if (s == "rain_pack_damaged") RainPackDamaged();
    else if (s == "rain_lists_differ") RainListsDiffer();
    else if (s == "rain_pieces") RainPieces();
    else if (s == "band_fails_midway") BandFailsMidway();
    else if (s == "not_a_stock_texture") NotAStockTexture();
    else if (s == "extract_fails_at_a_level") ExtractFailsAtALevel();
    else return 2;
    return g_fails ? 1 : 0;
}
