// terrainhd.cpp's own bookkeeping, run against a fake engine (tests\test_terrainhd_cache.py builds it once, writes the
// pack once for the module, and runs one scenario per process):
//   terrainhd_cache_selftest <game dir> make_pack      -- writes <game dir>\terrain\texture_x8.pcx
//   terrainhd_cache_selftest <game dir> <scenario>     -- the pack is already there (copied by the test)
// Prints "ok <check>" / "FAIL <check>: <detail>" lines; exit code 0 only when every check passed.
//
// terrainhd.cpp is compiled in this file with TERRAINHD_SELFTEST: its image base is a fake exe image (the call sites,
// the UV tables and immediates, the engine functions' entry bytes, the loading canvas and the screen size live in
// it), its game folder is the test's, and its engine functions are the fakes below. texture.pcx and
// terrain\texture_x8.pcx are real PCX files on disk, read by the real hdpack reader.
//
// The fakes follow the engine where the hook depends on it: mem_alloc never returns null (the engine exits instead;
// the fake aborts, so a test that reached it fails); a Buffer keeps its pixels at +0x54 with the lock pointer +0x50
// null outside a lock; Texture_extract_2 returns 0x10 without a Buffer and 3 for a rect outside it, the only quiet
// failures it has, and allocates its bits through mem_alloc.
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
static const Texture* g_drawn = nullptr; // what the last Texture_draw_2 drew
static void (*g_inGen)() = nullptr;      // what a terrain pass draws

static Texture* T(void* t) { return static_cast<Texture*>(t); }
static int& Heap(void* t) { return *reinterpret_cast<int*>(static_cast<uint8_t*>(t) + kTexHeap); }

static void* __cdecl FakeAlloc(size_t n)
{
    void* p = malloc(n);
    if (!p) { std::printf("FAIL mem_alloc returned null (the engine would exit)\n"); std::exit(3); }
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

static void __fastcall FakeTexCtor(void* tex, void*)
{
    T(tex)->data = nullptr; T(tex)->w = 0; T(tex)->h = 0; Heap(tex) = 0;
}

static void __fastcall FakeTexClose(void* tex, void*)
{
    if (T(tex)->data && Heap(tex) == 0) FakeFree(T(tex)->data);
    T(tex)->data = nullptr; T(tex)->w = 0; T(tex)->h = 0; Heap(tex) = 0;
}

static void __fastcall FakeDraw2(void* tex, void*, void*, void*, void*, int, void*, int) { g_drawn = T(tex); }

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
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "texture.pcx").c_str(), "wb");
    Header(f, 1, 1);
    fputc(0, f);
    Trailer(f);
    fclose(f);
}

// texture_x8.pcx: each test texture's 448 x 448 cell one colour (FileIndex) with the mark at (1, 2), the rest index 3.
static void WritePack()
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
}

static void Pass() { GenTerrainPolyHook(nullptr, nullptr, 0, 0, 0, 0, 0, 0, 0, 0); }
static void Passes(int n) { for (int i = 0; i < n; ++i) Pass(); }

static void Screen(int w, int h)
{
    *reinterpret_cast<int*>(At(kVA_ScreenW)) = w;
    *reinterpret_cast<int*>(At(kVA_ScreenH)) = h;
}

static int Uv0() { return reinterpret_cast<int32_t*>(At(0x685CA8))[1]; }          // stock 27
static int Imm() { int32_t v; memcpy(&v, At(0x46485D) + 1, 4); return v; }       // stock 55

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

static bool NoOverlayCopies()
{
    for (const Foreign& f : g_foreign) if (f.src) return false;
    return true;
}

// off / failed: the stock textures and UVs, no stock copy, no overlay copy, only the textures' own bits
static bool HoldsNothing()
{
    return !g_stock && g_level == 1 && NoOverlayCopies() && g_liveBits == kAll && Uv0() == 27 && Imm() == 55;
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
    for (uint32_t s : kUvImmediates) { At(s)[0] = 0xB8; const uint32_t v = 0x37; memcpy(At(s) + 1, &v, 4); }
    for (int t = 0; t < 2; ++t) memcpy(At(kUvTables[t].va), kUvStock[t], kUvTables[t].count * 4);
    for (const Entry8& f : kEntries) memcpy(At(f.va), f.b, sizeof f.b);
    memcpy(At(kVA_Draw2), kDraw2Entry, sizeof kDraw2Entry);
    Screen(1920, 1080);
    for (int y = 0; y < 768; ++y)
        for (int x = 0; x < 1024; ++x) g_stockSheet[y][x] = static_cast<uint8_t>(10 + (x * 3 + y * 5) % 200);
    SetBuffer(At(kVA_LoadingCanvas), g_stockSheet, 1024, 768, 1024);
    for (int y = 0; y < 56; ++y)
        for (int x = 0; x < 112; ++x) g_rainPx[y][x] = static_cast<uint8_t>(100 + (x + y) % 50);
    SetBuffer(g_rainBuf, g_rainPx, 112, 56, 112);
}

static void Install()
{
    g_eng.extract = reinterpret_cast<decltype(g_eng.extract)>(&FakeExtract);
    g_eng.gen = &FakeGen;
    g_eng.draw2 = reinterpret_cast<FDraw2>(&FakeDraw2);
    g_eng.texCtor = reinterpret_cast<decltype(g_eng.texCtor)>(&FakeTexCtor);
    g_eng.texClose = reinterpret_cast<decltype(g_eng.texClose)>(&FakeTexClose);
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
    Check(Logged("installed: terrain\\texture_x8.pcx (21") == 1 && Logged(" for 0x0") == 0,
          "the install line names no level (the screen is not known yet)");
    LoadTerrain();
    Pass();
    Check(AllAt(56) && StockPixels() && HoldsNothing(), "off: stock textures, stock UVs, nothing held");
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "on: every texture at 4x (1920x1080)", Num(g_level));
    Check(Uv0() == terrainhd::Uv(27, 4) && Imm() == terrainhd::Uv(55, 4), "on: the UVs at 4x", Num(Uv0()));
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
    Check(g_level == 1 && Uv0() == 27 && !g_stock && AllAt(56) && EveryTextureHasBits(),
          "load_terrain: stock textures, stock UVs");
    Pass();
    Check(g_level == 4 && AllAt(224), "game 2 at 4x");
    Screen(1024, 768);
    Pass();
    Check(g_level == 2 && AllAt(112) && Uv0() == terrainhd::Uv(27, 2), "1024x768: 2x", Num(g_level));
    Screen(1280, 1024);
    Pass();
    Check(g_level == 4 && AllAt(224), "1280x1024: 4x (the real tile is 184 px)", Num(g_level));
    Screen(2560, 1440);
    Pass();
    Check(g_level == 8 && AllAt(448) && Uv0() == terrainhd::Uv(27, 8), "2560x1440: 8x", Num(g_level));
    const Texture* t = T(g_tex[4]);
    const uint8_t c = static_cast<uint8_t>(FileIndex(4) + 10), m = static_cast<uint8_t>(kMark + 10);
    Check(t->data[2 * 448 + 1] == m && t->data[2 * 448 + 0] == c && t->data[2 * 448 + 2] == c && t->data[448 + 1] == c,
          "8x: the cell as painted (its 1-px mark kept where it is)");
    Check(g_liveBits == kAll, "one block of bits per texture", Num(g_liveBits));
}

// PRACX's Alt+T overlays: a 56x56 texture drawn in a pass at a level is drawn from a nearest copy; outside a pass, or
// at stock, the texture itself; one copy per (texture, bits); a reload of the bits makes a new copy.
alignas(16) static uint8_t g_overlay[kTexSize];
static uint8_t g_overlayBits[56 * 56], g_overlayBits2[56 * 56];
static void DrawOverlay() { Draw2Hook(T(g_overlay), nullptr, nullptr, nullptr, nullptr, 4, nullptr, 3); }

static void Overlays()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    for (int i = 0; i < 56 * 56; ++i) { g_overlayBits[i] = static_cast<uint8_t>(i % 56); g_overlayBits2[i] = 77; }
    Texture* o = T(g_overlay);
    o->data = g_overlayBits; o->w = 56; o->h = 56; Heap(o) = 1;   // prax.dll's own bits: never ours to free
    g_inGen = &DrawOverlay;
    Pass();                                              // the level is cut first, then the pass draws
    Check(g_level == 4 && g_drawn && g_drawn != o && g_drawn->w == 224, "in a pass at 4x: a 224 copy is drawn");
    Check(g_drawn->data[0] == 0 && g_drawn->data[3] == 0 && g_drawn->data[4] == 1 && g_drawn->data[224 * 3 + 4] == 1,
          "the copy is the overlay at 4x nearest");
    const Texture* first = g_drawn;
    Pass();
    Check(g_drawn == first, "the copy is reused");
    o->data = g_overlayBits2;
    Pass();
    Check(g_drawn->w == 224 && g_drawn->data[0] == 77, "new bits: a new copy");
    g_inGen = nullptr;
    DrawOverlay();
    Check(g_drawn == o, "outside a pass: the overlay itself");
    Draw2Hook(T(g_tex[0]), nullptr, nullptr, nullptr, nullptr, 4, nullptr, 3);
    Check(g_drawn == T(g_tex[0]), "our own textures pass through");
    TerrainHdSet(0);
    Check(NoOverlayCopies() && HoldsNothing(), "off: the overlay copies are freed, nothing held", Num(g_liveBits));
    g_inGen = &DrawOverlay;
    Pass();
    Check(g_drawn == o, "at stock, in a pass: the overlay itself");
    g_inGen = nullptr;
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

// At a level with overlay copies, a new level that cannot be made (the screen changes, no room): everything back to
// stock, the copies freed, nothing held, no work on later passes; and off after it holds nothing.
static void FailedAfterALevel()
{
    WriteStock(); WriteIni(1);
    Install();
    LoadTerrain();
    for (int i = 0; i < 56 * 56; ++i) g_overlayBits[i] = 9;
    Texture* o = T(g_overlay);
    o->data = g_overlayBits; o->w = 56; o->h = 56; Heap(o) = 1;
    g_inGen = &DrawOverlay;
    Pass();
    g_inGen = nullptr;
    Check(g_level == 4 && !NoOverlayCopies(), "at 4x with an overlay copy");
    Screen(2560, 1440);
    g_testNoRoom = true;
    Passes(4);
    Check(g_failed && g_level == 1 && StockPixels() && HoldsNothing() && EveryTextureHasBits(),
          "the 8x level refused: every texture stock with bits, the copy freed, nothing held", Num(g_liveBits));
    Check(Logged("no address room for the 8x level") == 1, "logged once");
    TerrainHdSet(0);
    Check(HoldsNothing(), "off after the failure: nothing held");
    g_testNoRoom = false;
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

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    g_root = argv[1];
    if (g_root.back() != '\\') g_root += '\\';
    CreateDirectoryA((g_root + "terrain").c_str(), nullptr);
    strcpy_s(g_testDir, g_root.c_str());
    const std::string s = argv[2];
    if (s == "make_pack") { WritePack(); return 0; }
    if (s == "corners") {                                // GiveBits' Texture fields after a cut at each size
        g_eng.alloc = &FakeAlloc;
        g_eng.free = &FakeFree;
        for (int side : { 56, 112, 224, 448 }) {
            alignas(16) uint8_t t[kTexSize] = {};
            GiveBits(T(t), side, [](uint8_t*) {});
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
    else return 2;
    return g_fails ? 1 : 0;
}
