// terrainhd.cpp's own bookkeeping, run against a fake engine (tests\test_terrainhd_cache.py builds it once and runs
// one scenario per process):
//   terrainhd_cache_selftest <game dir> <scenario>
// Prints "ok <check>" / "FAIL <check>: <detail>" lines; exit code 0 only when every check passed.
//
// terrainhd.cpp is compiled in this file with TERRAINHD_SELFTEST: its image base is a fake exe image (the call sites,
// the UV tables and immediates, the engine functions' entry bytes, the loading canvas and the screen size live in
// it), its game folder is the test's, and its engine functions are the fakes below. texture.pcx and
// terrain\texture_x8.pcx are real PCX files on disk, written here, read by the real hdpack reader.
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

static int g_failSide = -1;              // an extract at this size fails (and leaves the texture without bits)
static int g_failAfter = 0;              // ... after this many successful ones at that size
static bool g_failBufInit = false;       // Buffer_init fails the way the engine's does (closed, returns 1)
static int g_bufW = 0, g_bufH = 0;
static int g_liveTex = 0;                // texture bit blocks held (all textures)
static const Texture* g_drawn = nullptr; // what the last Texture_draw_2 drew
static int g_draws = 0;
static void (*g_inGen)() = nullptr;      // what a terrain pass draws

static Texture* T(void* t) { return static_cast<Texture*>(t); }

static int __fastcall FakeExtract(void* tex, void*, void* src, int x, int y, int w, int h, void*)
{
    Texture* t = T(tex);
    if (t->data) { free(t->data); t->data = nullptr; --g_liveTex; }
    if (w == g_failSide && g_failAfter-- <= 0) return 1;
    const uint8_t* p = Pixels(src);
    const int pitch = Field(src, kBufPitch);
    if (!p) return 1;
    t->data = static_cast<uint8_t*>(malloc(static_cast<size_t>(w) * h));
    ++g_liveTex;
    for (int r = 0; r < h; ++r) memcpy(t->data + r * w, p + (y + r) * pitch + x, w);
    t->w = w;
    t->h = h;
    return 0;
}

static void __fastcall FakeTexCtor(void* tex, void*) { memset(tex, 0, kTexSize); }
static void __fastcall FakeTexClose(void* tex, void*)
{
    if (T(tex)->data) { free(T(tex)->data); T(tex)->data = nullptr; --g_liveTex; }
}

static void __fastcall FakeBufferCtor(void* buf, void*) { memset(buf, 0, kBufSize); }

static int __fastcall FakeBufferInit(void* buf, void*, int w, int h, int, void*)
{
    uint8_t* b = static_cast<uint8_t*>(buf);
    if (g_failBufInit && (w != g_bufW || h != g_bufH)) {
        free(*reinterpret_cast<void**>(b + kBufData));
        *reinterpret_cast<void**>(b + kBufData) = nullptr;
        *reinterpret_cast<int*>(b + kBufW) = 0;
        *reinterpret_cast<int*>(b + kBufPitch) = 0;
        g_bufW = g_bufH = 0;
        return 1;
    }
    free(*reinterpret_cast<void**>(b + kBufData));
    const int pitch = (w + 3) & ~3;
    *reinterpret_cast<void**>(b + kBufData) = malloc(static_cast<size_t>(pitch) * h);
    *reinterpret_cast<int*>(b + kBufW) = w;
    *reinterpret_cast<int*>(b + kBufPitch) = pitch;
    g_bufW = w;
    g_bufH = h;
    return 0;
}

static void __fastcall FakeDraw2(void* tex, void*, void*, void*, void*, int, void*, int)
{
    g_drawn = T(tex);
    ++g_draws;
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
static uint8_t g_rainBuf[kBufSize + 0x80];              // the local buffer the RAINFALL composites come from
static uint8_t g_stockSheet[768][1024];                 // TEXTURE.PCX as loaded (file + 10)
static uint8_t g_rainPx[56][112];

static int CellX(int i) { return 1 + 57 * (i % 3); }
static int CellY(int i) { return 1 + 57 * (i / 3) + (i >= 3 ? 57 * 4 : 0); }   // two bands
static uint8_t FileIndex(int i) { return static_cast<uint8_t>(40 + 11 * i); } // the pack's colour for texture i

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

static void WriteStock()
{
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "texture.pcx").c_str(), "wb");
    Header(f, 1, 1);
    fputc(0, f);
    Trailer(f);
    fclose(f);
}

// texture_x8.pcx: each test texture's 448 x 448 cell one colour (FileIndex), everything else index 3.
static void WritePack()
{
    const int W = 1024 * 8, H = 768 * 8;
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "terrain\\texture_x8.pcx").c_str(), "wb");
    Header(f, W, H);
    std::vector<uint8_t> row(W);
    for (int y = 0; y < H; ++y) {
        memset(row.data(), 3, W);
        for (int i = 0; i < kSheetTex; ++i)
            if (y >= CellY(i) * 8 && y < (CellY(i) + 56) * 8) memset(row.data() + CellX(i) * 8, FileIndex(i), 56 * 8);
        WriteRle(f, row.data(), W);
    }
    Trailer(f);
    fclose(f);
}

static void WriteJunkPack()
{
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "terrain\\texture_x8.pcx").c_str(), "wb");
    fputs("damaged", f);
    fclose(f);
}

static void WriteIni(int on)
{
    WritePrivateProfileStringA("UIMod", "TerrainHD", on ? "1" : "0", (g_root + "Alpha Centauri.ini").c_str());
}

static void SetBuffer(void* b, void* px, int w, int pitch)
{
    *reinterpret_cast<void**>(static_cast<uint8_t*>(b) + kBufData) = px;
    *reinterpret_cast<int*>(static_cast<uint8_t*>(b) + kBufW) = w;
    *reinterpret_cast<int*>(static_cast<uint8_t*>(b) + kBufPitch) = pitch;
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

static int Uv0() { return reinterpret_cast<int32_t*>(At(0x685CA8))[1]; }          // stock 27
static int Imm() { int32_t v; memcpy(&v, At(0x46485D) + 1, 4); return v; }       // stock 55

static bool AllAt(int side)
{
    for (int i = 0; i < kAll; ++i) if (T(g_tex[i])->w != side || !T(g_tex[i])->data) return false;
    return true;
}

static bool StockPixels()
{
    for (int i = 0; i < kSheetTex; ++i) {
        const Texture* t = T(g_tex[i]);
        if (t->w != 56 || !t->data) return false;
        for (int y = 0; y < 56; ++y)
            if (memcmp(t->data + y * 56, &g_stockSheet[CellY(i) + y][CellX(i)], 56) != 0) return false;
    }
    for (int i = 0; i < kRainTex; ++i) {
        const Texture* t = T(g_tex[kSheetTex + i]);
        if (t->w != 56 || !t->data) return false;
        for (int y = 0; y < 56; ++y) if (memcmp(t->data + y * 56, &g_rainPx[y][56 * i], 56) != 0) return false;
    }
    return true;
}

static bool HoldsNothing() { return !g_stock && g_level == 1 && !g_foreign[0].src && g_bufW <= 4 && g_bufH <= 4; }

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
    *reinterpret_cast<int*>(At(kVA_ScreenW)) = 1920;
    *reinterpret_cast<int*>(At(kVA_ScreenH)) = 1080;
    for (int y = 0; y < 768; ++y)
        for (int x = 0; x < 1024; ++x) g_stockSheet[y][x] = static_cast<uint8_t>(10 + (x * 3 + y * 5) % 200);
    SetBuffer(At(kVA_LoadingCanvas), g_stockSheet, 1024, 1024);
    for (int y = 0; y < 56; ++y)
        for (int x = 0; x < 112; ++x) g_rainPx[y][x] = static_cast<uint8_t>(100 + (x + y) % 50);
    SetBuffer(g_rainBuf, g_rainPx, 112, 112);
}

static void Install()
{
    g_eng.extract = reinterpret_cast<decltype(g_eng.extract)>(&FakeExtract);
    g_eng.gen = &FakeGen;
    g_eng.draw2 = reinterpret_cast<FDraw2>(&FakeDraw2);
    g_eng.texCtor = reinterpret_cast<decltype(g_eng.texCtor)>(&FakeTexCtor);
    g_eng.texClose = reinterpret_cast<decltype(g_eng.texClose)>(&FakeTexClose);
    g_eng.bufferCtor = reinterpret_cast<decltype(g_eng.bufferCtor)>(&FakeBufferCtor);
    g_eng.bufferInit = reinterpret_cast<decltype(g_eng.bufferInit)>(&FakeBufferInit);
    g_eng.drawMap = &FakeDrawMap;
    g_eng.statusRedraw = reinterpret_cast<decltype(g_eng.statusRedraw)>(&FakeStatusRedraw);
    g_eng.graphicRedraw = reinterpret_cast<decltype(g_eng.graphicRedraw)>(&FakeGraphicRedraw);
    InstallTerrainHd();
}

// ---- scenarios ---------------------------------------------------------------------------------------------------

// TerrainHD=0 at start: nothing cut; on cuts the level at the next pass; off puts the exact stock back, holds nothing.
static void OffHoldsNothing()
{
    WriteStock(); WritePack(); WriteIni(0);
    Install();
    Check(g_installed && g_on == 0, "installed, off from the ini");
    LoadTerrain();
    Pass();
    Check(AllAt(56) && StockPixels() && Uv0() == 27 && HoldsNothing(), "off: stock textures, stock UVs, nothing held");
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "on: every texture at 4x (1920x1080)", Num(g_level));
    Check(Uv0() == terrainhd::Uv(27, 4) && Imm() == terrainhd::Uv(55, 4), "on: the UVs at 4x", Num(Uv0()));
    Check(T(g_tex[2])->data[0] == static_cast<uint8_t>(FileIndex(2) + 10), "a sheet texture is the pack's cell",
          Num(T(g_tex[2])->data[0]));
    Check(T(g_tex[kSheetTex])->data[0] == g_rainPx[0][0] && T(g_tex[kSheetTex])->data[3] == g_rainPx[0][0] &&
              T(g_tex[kSheetTex])->data[4] == g_rainPx[0][1], "a RAINFALL composite is its stock pixels at 4x");
    TerrainHdSet(0);
    Check(StockPixels() && Uv0() == 27 && Imm() == 55, "off: the exact stock textures and UVs back");
    Check(HoldsNothing() && g_liveTex == kAll, "off: no stock copy, no overlay copy, scratch 4x4", Num(g_liveTex));
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "on again: 4x");
}

// A new game while at a level: load_terrain's stock cuts put the UVs back at once; the next pass cuts the level.
static void NewGame()
{
    WriteStock(); WritePack(); WriteIni(1);
    Install();
    LoadTerrain();
    Pass();
    Check(g_level == 4, "game 1 at 4x");
    LoadTerrain();
    Check(g_level == 1 && Uv0() == 27 && !g_stock && AllAt(56), "load_terrain: stock textures, stock UVs");
    Pass();
    Check(g_level == 4 && AllAt(224), "game 2 at 4x");
    *reinterpret_cast<int*>(At(kVA_ScreenW)) = 1280;
    *reinterpret_cast<int*>(At(kVA_ScreenH)) = 1024;
    Pass();
    Check(g_level == 2 && AllAt(112) && Uv0() == terrainhd::Uv(27, 2), "a new screen size: 2x", Num(g_level));
}

// PRACX's Alt+T overlays: a 56x56 texture drawn in a pass at a level is drawn from a 4x nearest copy; outside a pass,
// or at stock, the texture itself; one copy per (texture, bits); a reload of the bits makes a new copy.
alignas(16) static uint8_t g_overlay[kTexSize];
static uint8_t g_overlayBits[56 * 56], g_overlayBits2[56 * 56];
static void DrawOverlay() { Draw2Hook(T(g_overlay), nullptr, nullptr, nullptr, nullptr, 4, nullptr, 3); }

static void Overlays()
{
    WriteStock(); WritePack(); WriteIni(1);
    Install();
    LoadTerrain();
    for (int i = 0; i < 56 * 56; ++i) { g_overlayBits[i] = static_cast<uint8_t>(i % 56); g_overlayBits2[i] = 77; }
    Texture* o = T(g_overlay);
    o->data = g_overlayBits; o->w = 56; o->h = 56;
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
    Check(!g_foreign[0].src && !g_foreign[1].src, "off: the overlay copies are freed");
    g_inGen = &DrawOverlay;
    Pass();
    Check(g_drawn == o, "at stock, in a pass: the overlay itself");
    g_inGen = nullptr;
}

// A cut that fails part way: every texture back to its stock pixels, stock UVs, stock for the session (no retry at
// the next pass); switching the row off and on tries again.
static void CutFails()
{
    WriteStock(); WritePack(); WriteIni(1);
    Install();
    LoadTerrain();
    g_failSide = 224; g_failAfter = 3;
    Pass();
    Check(g_level == 1 && g_failed && StockPixels() && Uv0() == 27, "a failed 4x cut: stock textures and UVs back");
    Check(!g_stock && Logged("HD terrain off for this session") == 1, "logged once, no stock copy held");
    const int cuts = g_liveTex;
    Pass();
    Check(g_level == 1 && g_liveTex == cuts && Logged("a 4x cut failed") == 1, "the next pass does not retry");
    g_failSide = -1;
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "off and on: tried again, 4x");
}

// No usable pack: not installed. A pack damaged after install: the cut is refused, stock, logged.
static void BadPack()
{
    WriteStock(); WriteJunkPack(); WriteIni(1);
    Install();
    Check(!g_installed && Logged("not usable") == 1, "a damaged pack at start: not installed");
    Check(At(kExtractSites[0])[0] == 0xE8 && CallsTo(kExtractSites[0], kVA_Extract2), "nothing patched");
}

static void PackDamagedLater()
{
    WriteStock(); WritePack(); WriteIni(0);
    Install();
    LoadTerrain();
    WriteJunkPack();
    TerrainHdSet(1);
    Pass();
    Check(g_installed && g_level == 1 && StockPixels() && Uv0() == 27 && !g_stock, "damaged later: stock, nothing held");
    Check(Logged("not usable") == 1, "logged");
}

// Buffer_init closes the scratch and fails without exiting: that cut fails (stock for the session, restored from the
// stock copy through a scratch that is resized again), and nothing writes through the closed Buffer.
static void ScratchResizeFails()
{
    WriteStock(); WritePack(); WriteIni(1);
    Install();
    LoadTerrain();
    g_failBufInit = true;
    Pass();
    Check(g_level == 1 && g_failed && Uv0() == 27, "the 4x scratch cannot be made: stock");
    Check(g_scratchW == 0 && g_scratchH == 0, "no size recorded for the closed Buffer");
    g_failBufInit = false;
    TerrainHdSet(0);
    TerrainHdSet(1);
    Pass();
    Check(g_level == 4 && AllAt(224), "Buffer_init works again: 4x");
}

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    g_root = argv[1];
    if (g_root.back() != '\\') g_root += '\\';
    CreateDirectoryA((g_root + "terrain").c_str(), nullptr);
    strcpy_s(g_testDir, g_root.c_str());
    MakeImage();
    const std::string s = argv[2];
    if (s == "off_holds_nothing") OffHoldsNothing();
    else if (s == "new_game") NewGame();
    else if (s == "overlays") Overlays();
    else if (s == "cut_fails") CutFails();
    else if (s == "bad_pack") BadPack();
    else if (s == "pack_damaged_later") PackDamagedLater();
    else if (s == "scratch_resize_fails") ScratchResizeFails();
    else return 2;
    return g_fails ? 1 : 0;
}
