// objecthd.cpp's own bookkeeping, run against a fake engine (tests\test_objecthd_cache.py builds it once and runs one
// scenario per process):
//   objecthd_cache_selftest <game dir> <scenario>
// Prints "ok <check>" / "FAIL <check>: <detail>" lines; exit code 0 only when every check passed.
//
// objecthd.cpp is compiled in this file with OBJECTHD_SELFTEST: its image base is a fake exe image (the 96 table
// sprites, SCALE_NUM_G / SCALE_DEN_G and every call site the install checks live in it), its game folder is the
// test's, and its engine functions are the fakes below. The sheets are real PCX files on disk, written here, read by
// the real hdpack reader. Built with OBJECTHD_BUDGET = 60,000 bytes so the budget trim is reached with a few objects.
#define OBJECTHD_SELFTEST
#ifndef OBJECTHD_BUDGET
#define OBJECTHD_BUDGET (size_t(60000))
#endif
#include "../../src/uimod/src/objecthd.cpp"

#include <string>
#include <vector>

// ---- what objecthd.cpp links against ------------------------------------------------------------------------------

static std::vector<std::string> g_log;
void UimodLog(const char* msg) { g_log.push_back(std::string("LOG ") + msg); }
void UimodDbg(const char* msg) { g_log.push_back(std::string("DBG ") + msg); }
bool PrefsTabInstalled() { return true; }
bool UimodPcave2Range(uintptr_t*, uintptr_t*) { return false; }   // the unpatched exe: the popup draws Sprite_draw_2

// ---- the fake engine -------------------------------------------------------------------------------------------

static int g_hdCuts = 0;
static int g_failW = -1, g_failH = -1;   // an HD cut at this size fails
static int g_liveSprites = 0;            // HD sprite pixel blocks held
static void* g_lastDrawn = nullptr;
static int g_lastNum = 0, g_lastDen = 0; // the num / den the drawn sprite got (args for Sprite_draw_2, globals otherwise)
static int g_bufW = 0, g_bufH = 0;

static void*& SprData(void* spr) { return *reinterpret_cast<void**>(static_cast<uint8_t*>(spr) + 4); }

static int __fastcall FakeExtract(void* spr, void*, void*, int, int, int, int w, int h, void*)
{
    ++g_hdCuts;
    if (w == g_failW && h == g_failH) return 1;
    SprData(spr) = malloc(static_cast<size_t>(w) * h);
    ++g_liveSprites;
    return 0;
}

static void __fastcall FakeClose(void* spr, void*)
{
    if (SprData(spr)) { free(SprData(spr)); SprData(spr) = nullptr; --g_liveSprites; }
}

static int Global(uintptr_t va) { return *reinterpret_cast<int32_t*>(At(va)); }

static int __fastcall FakeDraw2(void* spr, void*, void*, int, int, int, int num, int den)
{
    g_lastDrawn = spr; g_lastNum = num; g_lastDen = den;
    return 0;
}

static int __fastcall FakeBlitCore(void* spr, void*, void*, int, int, int)
{
    g_lastDrawn = spr; g_lastNum = Global(kVA_ScaleNum); g_lastDen = Global(kVA_ScaleDen);
    return 0;
}

static int __fastcall FakeDrawDest(void* spr, void*, void*, int, int, int, void*)
{
    g_lastDrawn = spr; g_lastNum = Global(kVA_ScaleNum); g_lastDen = Global(kVA_ScaleDen);
    return 0;
}

static void __fastcall FakeBufferCtor(void* buf, void*) { memset(buf, 0, kBufSize); }

static int __fastcall FakeBufferInit(void* buf, void*, int w, int h, int, void*)
{
    uint8_t* b = static_cast<uint8_t*>(buf);
    free(*reinterpret_cast<void**>(b + kBufData));
    const int pitch = (w + 3) & ~3;
    *reinterpret_cast<void**>(b + kBufData) = malloc(static_cast<size_t>(pitch) * h);
    *reinterpret_cast<int*>(b + kBufW) = w;
    *reinterpret_cast<int*>(b + kBufPitch) = pitch;
    g_bufW = w;
    g_bufH = h;
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

static void SetScale(int num, int den)
{
    *reinterpret_cast<int32_t*>(At(kVA_ScaleNum)) = num;
    *reinterpret_cast<int32_t*>(At(kVA_ScaleDen)) = den;
}

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
    for (int i = 0; i < 768; ++i) fputc((i * 5) & 255, f);
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

// <sheet>.pcx (its palette) and terrain\<sheet>_x8.pcx: background 253 everywhere, art (file 90) inside every table
// cell of that sheet except the rows listed in `blank`.
static void WriteSheet(int sheet, const std::vector<int>& blank = {})
{
    FILE* f = nullptr;
    fopen_s(&f, (g_root + kSheetName[sheet] + ".pcx").c_str(), "wb");
    Header(f, 1, 1);
    fputc(0, f);
    Trailer(f);
    fclose(f);
    const int W = kSheetW * kMaster, H = kSheetH * kMaster;
    fopen_s(&f, (g_root + "terrain\\" + kSheetName[sheet] + "_x8.pcx").c_str(), "wb");
    Header(f, W, H);
    std::vector<uint8_t> row(W);
    for (int y = 0; y < H; ++y) {
        memset(row.data(), 253, W);
        const int sy = y / kMaster;
        for (int i = 0; i < g_count; ++i) {
            const Entry& e = g_entries[i];
            bool isBlank = false;
            for (int b : blank) isBlank = isBlank || b == i;
            if (e.sheet != sheet || isBlank || sy < e.y + 10 || sy >= e.y + kH - 10) continue;
            memset(row.data() + (e.x + 10) * kMaster, 90, (kW - 20) * kMaster);
        }
        WriteRle(f, row.data(), W);
    }
    Trailer(f);
    fclose(f);
}

static void WriteIni(int on)
{
    WritePrivateProfileStringA("UIMod", "ObjectHD", on ? "1" : "0", (g_root + "Alpha Centauri.ini").c_str());
}

static void* Spr(int row) { return At(g_entries[row].va); }

// A Datalinks draw (Sprite_draw_2 with num / den as handed); true when the HD copy was drawn.
static bool Draw2(int row, int num, int den)
{
    g_lastDrawn = nullptr;
    Draw2Hook(Spr(row), nullptr, nullptr, kKey, 5, 5, num, den);
    return g_lastDrawn && g_lastDrawn != Spr(row);
}

// A terrain-pass draw (Sprite_blit_scaled_core with the scale globals).
static bool Blit(int row)
{
    g_lastDrawn = nullptr;
    BlitCoreHook(Spr(row), nullptr, nullptr, kKey, 5, 5);
    return g_lastDrawn && g_lastDrawn != Spr(row);
}

static int Logged(const char* needle)
{
    int n = 0;
    for (const std::string& l : g_log) if (l.find(needle) != std::string::npos) ++n;
    return n;
}

static int FirstRow(int sheet)
{
    for (int i = 0; i < g_count; ++i) if (g_entries[i].sheet == sheet) return i;
    return -1;
}

static void Install()
{
    g_eng.extract = reinterpret_cast<decltype(g_eng.extract)>(&FakeExtract);
    g_eng.draw2 = reinterpret_cast<FDraw2>(&FakeDraw2);
    g_eng.popupArt = reinterpret_cast<FDraw2>(&FakeDraw2);
    g_eng.blitCore = reinterpret_cast<decltype(g_eng.blitCore)>(&FakeBlitCore);
    g_eng.drawDest = reinterpret_cast<decltype(g_eng.drawDest)>(&FakeDrawDest);
    g_eng.spriteClose = reinterpret_cast<decltype(g_eng.spriteClose)>(&FakeClose);
    g_eng.bufferCtor = reinterpret_cast<decltype(g_eng.bufferCtor)>(&FakeBufferCtor);
    g_eng.bufferInit = reinterpret_cast<decltype(g_eng.bufferInit)>(&FakeBufferInit);
    g_eng.drawMap = &FakeDrawMap;
    g_eng.statusRedraw = reinterpret_cast<decltype(g_eng.statusRedraw)>(&FakeStatusRedraw);
    g_eng.graphicRedraw = reinterpret_cast<decltype(g_eng.graphicRedraw)>(&FakeGraphicRedraw);
    InstallObjectHd();
}

// Every call site InstallObjectHd checks, as the unpatched exe has them.
static void MakeImage()
{
    g_testImage = static_cast<BYTE*>(VirtualAlloc(nullptr, 0x600000, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    const auto call = [](uint32_t site, uintptr_t target) {
        BYTE* p = At(site);
        p[0] = 0xE8;
        const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(At(target)) - (reinterpret_cast<uintptr_t>(p) + 5));
        memcpy(p + 1, &rel, 4);
    };
    for (uint32_t site : kExtractSites) call(site, kVA_Extract2);
    for (int i = 0; i < kBlitCoreCalls; ++i) call(kTerrainLo + 0x10 + i * 0x40, kVA_BlitCore);
    for (int i = 0; i < kDrawDestCalls; ++i) call(kTerrainLo + 0x1000 + i * 0x40, kVA_DrawDest);
    for (uint32_t site : kDatalinkSites) call(site, kVA_Draw2);
    call(kSpriteBoxSite, kVA_Draw2);
    call(kPopupArtSite, kVA_Draw2);
    BuildTable();                                       // the rows WriteSheet draws (InstallObjectHd builds them again)
}

// ---- scenarios ---------------------------------------------------------------------------------------------------

static bool HoldsNothing()
{
    return g_bytes == 0 && g_liveSprites == 0 && !g_pack[0].bytes && !g_pack[1].bytes && !g_cell;
}

// ObjectHD=0 in the ini: proven at install, then nothing held; on proves again; off frees everything.
static void OffHoldsNothing()
{
    WriteSheet(0);
    WriteSheet(1);
    WriteIni(0);
    Install();
    Check(g_installed && g_on == 0, "installed, off from the ini");
    Check(HoldsNothing(), "off at Init: no sheet bytes, no cell buffer");
    SetScale(16, 16);
    Check(!Blit(0) && !Draw2(0, 3, 2) && HoldsNothing(), "off: stock, nothing read");
    ObjectHdSet(1);
    Check(g_pack[0].bytes && g_pack[1].bytes, "on: both sheets proven again");
    Check(Blit(0) && g_lastNum == g_lastDen, "on: HD, drawn unscaled");
    Check(Draw2(FirstRow(1), 5, 2), "a TER1WRECK object HD too");
    ObjectHdSet(0);
    Check(HoldsNothing(), "off: no cut object, no sheet, no cell buffer",
          Num(g_bytes) + " " + Num(g_liveSprites));
    Check(g_bufW <= 4 && g_bufH <= 4, "off: the scratch Buffer is 4x4", Num(g_bufW) + "x" + Num(g_bufH));
    Check(!Blit(0), "off: stock again");
    ObjectHdSet(1);
    Check(Blit(0), "on again: HD");
}

// Switched on after its file went bad: that sheet stays stock, the other is HD.
static void OnAgainFailsStock()
{
    WriteSheet(0);
    WriteSheet(1);
    WriteIni(1);
    Install();
    SetScale(16, 16);
    Check(Blit(0), "TER1 HD");
    ObjectHdSet(0);
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "terrain\\ter1_x8.pcx").c_str(), "wb");
    fputs("damaged", f);
    fclose(f);
    ObjectHdSet(1);
    Check(!Blit(0) && !g_pack[0].bytes, "the damaged TER1 sheet stays stock");
    Check(Logged("ter1_x8.pcx is not") >= 1, "and is logged");
    Check(Blit(FirstRow(1)), "TER1WRECK still HD");
}

// A cut that fails at one size is never retried; other sizes are HD; each size is cut once.
static void FailureMemoryAndSizeCache()
{
    WriteSheet(0);
    WriteIni(1);
    Install();
    int w = 0, h = 0;
    basehd_law::CellSize(kW, kH, 22, 16, &w, &h);
    g_failW = w; g_failH = h;
    const int before = g_hdCuts;
    Check(!Draw2(3, 22, 16) && !Draw2(3, 22, 16) && !Draw2(3, 22, 16), "the failed size draws stock");
    Check(g_hdCuts - before == 1, "the failed size was cut once", Num(g_hdCuts - before));
    Check(Draw2(3, 16, 16) && Draw2(3, 25, 16), "other sizes are HD");
    const int cuts = g_hdCuts;
    Draw2(3, 16, 16); Draw2(3, 25, 16); Draw2(3, 22, 16);
    Check(g_hdCuts == cuts, "revisits cut nothing", Num(g_hdCuts - cuts));
}

// A blank cell is found when the sheet is proven: stock everywhere, never cut, one line.
static void BlankCell()
{
    WriteSheet(0, {2, 7});
    WriteIni(1);
    Install();
    SetScale(16, 16);
    const int before = g_hdCuts;
    Check(!Blit(2) && !Draw2(2, 5, 2) && !Blit(7), "blank cells draw stock everywhere");
    Check(g_hdCuts == before, "and are never cut");
    Check(Logged("is blank") == 2, "one line each, at Init", Num(Logged("is blank")));
    Check(Blit(3), "a neighbour is HD");
}

// Over the budget the least recently drawn objects go, the newest stay; a dropped one is cut again.
static void BudgetTrim()
{
    WriteSheet(0);
    WriteIni(1);
    Install();
    SetScale(16, 16);                                   // 100 x 62 = 6,200 bytes each
    for (int i = 0; i < 20; ++i) Blit(i);
    const size_t each = static_cast<size_t>(kW) * kH, keep = kBudget / each;
    Check(g_bytes <= kBudget && g_bytes == keep * each, "full up to the budget, never over", Num(g_bytes));
    Check(g_liveSprites == static_cast<int>(keep), "dropped objects are closed", Num(g_liveSprites));
    bool newest = true;
    for (int i = 20 - static_cast<int>(keep); i < 20; ++i) {
        const Slot* s = Find(g_entries[i], kW, kH);
        newest = newest && s && s->state == 1;
    }
    Check(newest, "the most recently drawn are kept");
    const int before = g_hdCuts;
    Check(Blit(0) && g_hdCuts == before + 1, "a dropped object is cut again");
}

// Datalinks: the HD copy is sized from the num / den handed in (the mod's run-time scale), drawn at 1 / 1.
static void DatalinksScale()
{
    WriteSheet(0);
    WriteIni(1);
    Install();
    Check(Draw2(4, 250, 100), "drawn HD at 250/100");
    Check(g_lastNum == 1 && g_lastDen == 1, "at 1 / 1", Num(g_lastNum) + "/" + Num(g_lastDen));
    int w = 0, h = 0;
    basehd_law::CellSize(kW, kH, 250, 100, &w, &h);
    Check(Find(g_entries[4], w, h) != nullptr, "cut at CellSize(100, 62, 250, 100)", Num(w) + "x" + Num(h));
    // a sprite that is not one of the table's passes through untouched
    uint8_t other[0x2C] = {};
    g_lastDrawn = nullptr;
    Draw2Hook(other, nullptr, nullptr, kKey, 1, 1, 7, 3);
    Check(g_lastDrawn == other && g_lastNum == 7 && g_lastDen == 3, "another sprite: the original call");
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
    else if (s == "on_again_fails_stock") OnAgainFailsStock();
    else if (s == "failure_memory_and_size_cache") FailureMemoryAndSizeCache();
    else if (s == "blank_cell") BlankCell();
    else if (s == "budget_trim") BudgetTrim();
    else if (s == "datalinks_scale") DatalinksScale();
    else return 2;
    return g_fails ? 1 : 0;
}
