// basehd.cpp's own bookkeeping, run against a fake engine (tests\test_basehd_cache.py builds it once and runs one
// scenario per process):
//   basehd_cache_selftest <game dir> <scenario>
// Prints "ok <check>" / "FAIL <check>: <detail>" lines; exit code 0 only when every check passed.
//
// basehd.cpp is compiled in this file with BASEHD_SELFTEST: its image base is a fake exe image (the faction sprite
// slots, MFactions' filenames, SCALE_NUM_G / SCALE_DEN_G and the two call sites live in it), its game folder is the
// test's, and its engine functions are the fakes below. The packs are real PCX files on disk, written here, read by
// the real hdpack reader. Built with BASEHD_BUDGET = kTestBudget so the budget trim is reached with a few sprites.
#define BASEHD_SELFTEST
#ifndef BASEHD_BUDGET
#define BASEHD_BUDGET (size_t(60000))
#endif
#include "../../src/uimod/src/basehd.cpp"

#include <string>
#include <vector>

// ---- what basehd.cpp links against -------------------------------------------------------------------------------

static std::vector<std::string> g_log;
void UimodLog(const char* msg) { g_log.push_back(std::string("LOG ") + msg); }
void UimodDbg(const char* msg) { g_log.push_back(std::string("DBG ") + msg); }
bool PrefsTabInstalled() { return true; }

// ---- the fake engine -------------------------------------------------------------------------------------------

static int g_extractCalls = 0;       // every Sprite_extract_2 call (stock cuts and HD cuts)
static int g_hdCuts = 0;             // the HD cuts (from the scratch Buffer)
static bool g_failStock = false;     // the next stock cuts fail (rc 1, no data)
static int g_failW = -1, g_failH = -1;   // an HD cut at this size fails
static int g_liveSprites = 0;        // sprite pixel blocks held
static void* g_lastDrawn = nullptr;
static int g_lastNum = 0, g_lastDen = 0;
static int g_bufW = 0, g_bufH = 0;   // the scratch Buffer's size as the fake Buffer_init last made it

static int& SprField(void* spr, int off) { return *reinterpret_cast<int*>(static_cast<uint8_t*>(spr) + off); }
static void*& SprData(void* spr) { return *reinterpret_cast<void**>(static_cast<uint8_t*>(spr) + 4); }

static int __fastcall FakeExtract(void* spr, void*, void* src, int, int, int, int w, int h, void*)
{
    ++g_extractCalls;
    const bool hd = src == g_scratch;
    if (hd) ++g_hdCuts;
    if ((!hd && g_failStock) || (hd && w == g_failW && h == g_failH)) {
        if (SprData(spr)) { free(SprData(spr)); SprData(spr) = nullptr; --g_liveSprites; }
        return 1;
    }
    if (SprData(spr)) { free(SprData(spr)); --g_liveSprites; }
    SprData(spr) = malloc(static_cast<size_t>(w) * h);
    ++g_liveSprites;
    SprField(spr, 0x10) = w;
    SprField(spr, 0x14) = h;
    return 0;
}

static int __fastcall FakeDraw(void* spr, void*, void*, int, int, int, void*)
{
    g_lastDrawn = spr;
    g_lastNum = *reinterpret_cast<int32_t*>(At(kVA_ScaleNum));
    g_lastDen = *reinterpret_cast<int32_t*>(At(kVA_ScaleDen));
    return 0;
}

static void __fastcall FakeClose(void* spr, void*)
{
    if (SprData(spr)) { free(SprData(spr)); SprData(spr) = nullptr; --g_liveSprites; }
}

static void __fastcall FakeBufferCtor(void* buf, void*) { memset(buf, 0, kBufSize); }

static int __fastcall FakeBufferInit(void* buf, void*, int w, int h, int, void*)
{
    uint8_t* b = static_cast<uint8_t*>(buf);
    free(*reinterpret_cast<void**>(b + kBufData));
    const int pitch = (w + 3) & ~3;
    *reinterpret_cast<void**>(b + kBufData) = malloc(static_cast<size_t>(pitch) * h);
    *reinterpret_cast<int*>(b + kBufW) = w;
    *reinterpret_cast<int*>(b + kBufH) = -h;
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

static void* SpriteAt(int f, int idx) { return At(kVA_FactionSprites + f * kFactionStride + idx * kSpriteSize); }

static void SetScale(int num, int den)
{
    *reinterpret_cast<int32_t*>(At(kVA_ScaleNum)) = num;
    *reinterpret_cast<int32_t*>(At(kVA_ScaleDen)) = den;
}

// A palette file and (blank: cells left all key) a pack for <stem>.
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

static void WritePalette(const char* stem)
{
    FILE* f = nullptr;
    fopen_s(&f, (g_root + stem + ".pcx").c_str(), "wb");
    Header(f, 1, 1);
    fputc(0, f);
    Trailer(f);
    fclose(f);
}

// cells: 24 flags (load_faction_art's index), true = art (file index 90 -> loaded 100), false = all key (file 255).
static void WritePack(const char* stem, const bool cells[24])
{
    WritePalette(stem);
    const int W = kBlockW * kMaster, H = kBlockH * kMaster;
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "bases\\" + stem + "_x8.pcx").c_str(), "wb");
    Header(f, W, H);
    std::vector<uint8_t> row(W);
    for (int y = 0; y < H; ++y) {
        memset(row.data(), 255, W);
        const int sy = y / kMaster;
        for (int idx = 0; idx < 24; ++idx) {
            if (!cells[idx]) continue;
            const int water = idx / 12, size = idx % 12 / 3, def = idx % 3;
            const int cx = 1 + size * 101, cy = 1 + (water * 3 + def) * 76;
            if (sy >= cy + 10 && sy < cy + kCellH - 10)
                memset(row.data() + (cx + 10) * kMaster, 90, (kCellW - 20) * kMaster);
        }
        WriteRle(f, row.data(), W);
    }
    Trailer(f);
    fclose(f);
}

static void WriteJunk(const char* stem)
{
    FILE* f = nullptr;
    fopen_s(&f, (g_root + "bases\\" + stem + "_x8.pcx").c_str(), "wb");
    fputs("not a pcx", f);
    fclose(f);
}

static void SetFactionFile(int f, const char* stem)
{
    char* name = reinterpret_cast<char*>(At(kVA_MFactions + f * kMFactionStride + kMFactionFilename));
    strcpy_s(name, 24, stem);
}

// load_faction_art for slot f: its 24 base sprites through the (retargeted) extract site, as the loop cuts them.
static void LoadFaction(int f, const char* stem, int failIdx = -1)
{
    SetFactionFile(f, stem);
    for (int idx = 0; idx < 24; ++idx) {
        const int water = idx / 12, size = idx % 12 / 3, def = idx % 3;
        g_failStock = idx == failIdx;
        ExtractRecorder(SpriteAt(f, idx), nullptr, At(0x798668), kKey, 1 + size * 101, 1 + (water * 3 + def) * 76,
                        kCellW, kCellH, nullptr);
    }
    g_failStock = false;
}

// base_draw: the draw site with the current scale. True when the HD copy (not the stock sprite) was drawn.
static bool Draw(int f, int idx)
{
    g_lastDrawn = nullptr;
    DrawHook(SpriteAt(f, idx), nullptr, nullptr, kKey, 10, 10, nullptr);
    return g_lastDrawn && g_lastDrawn != SpriteAt(f, idx);
}

static int LoadedPacks()
{
    int n = 0;
    for (const FactionPack& p : g_packs) if (p.px.bytes) ++n;
    return n;
}

static int Logged(const char* needle)
{
    int n = 0;
    for (const std::string& l : g_log) if (l.find(needle) != std::string::npos) ++n;
    return n;
}

static void WriteIni(int on)
{
    WritePrivateProfileStringA("UIMod", "BaseHD", on ? "1" : "0", (g_root + "Alpha Centauri.ini").c_str());
}

static void Install()
{
    g_eng.extract = reinterpret_cast<decltype(g_eng.extract)>(&FakeExtract);
    g_eng.draw = reinterpret_cast<decltype(g_eng.draw)>(&FakeDraw);
    g_eng.spriteClose = reinterpret_cast<decltype(g_eng.spriteClose)>(&FakeClose);
    g_eng.bufferCtor = reinterpret_cast<decltype(g_eng.bufferCtor)>(&FakeBufferCtor);
    g_eng.bufferInit = reinterpret_cast<decltype(g_eng.bufferInit)>(&FakeBufferInit);
    g_eng.drawMap = &FakeDrawMap;
    g_eng.statusRedraw = reinterpret_cast<decltype(g_eng.statusRedraw)>(&FakeStatusRedraw);
    g_eng.graphicRedraw = reinterpret_cast<decltype(g_eng.graphicRedraw)>(&FakeGraphicRedraw);
    InstallBaseHd();
}

// The two call sites, as the exe has them (E8 rel32 to Sprite_extract_2 / Sprite_draw_dest), so InstallBaseHd's byte
// checks pass and its retargets land in the fake image.
static void MakeImage()
{
    g_testImage = static_cast<BYTE*>(VirtualAlloc(nullptr, 0x600000, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    const auto call = [](uint32_t site, uintptr_t target) {
        BYTE* p = At(site);
        p[0] = 0xE8;
        const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(At(target)) - (reinterpret_cast<uintptr_t>(p) + 5));
        memcpy(p + 1, &rel, 4);
    };
    call(kSiteExtract, kVA_Extract2);
    call(kSiteDraw, kVA_DrawDest);
}

static const bool kAll[24] = {true, true, true, true, true, true, true, true, true, true, true, true,
                              true, true, true, true, true, true, true, true, true, true, true, true};

// ---- scenarios ---------------------------------------------------------------------------------------------------

// A game started with BaseHD=0 reads nothing; on proves at the first draw; off frees everything.
static void OffHoldsNothing()
{
    WritePack("FACA", kAll);
    WriteIni(0);
    Install();
    Check(g_installed && g_on == 0, "installed, off from the ini");
    Check(LoadedPacks() == 0 && !g_cell, "install proved a pack and released it", Num(LoadedPacks()));
    LoadFaction(0, "FACA");
    SetScale(16, 16);
    Check(!Draw(0, 0) && LoadedPacks() == 0, "off: stock, and nothing is read at load or draw");
    BaseHdSet(1);
    Check(Draw(0, 0), "on: the first draw proves the pack and draws HD");
    Check(g_lastNum == g_lastDen, "the HD copy is drawn unscaled (num == den)");
    for (int i = 1; i < 6; ++i) Draw(0, i);
    SetScale(25, 16);
    Draw(0, 0);
    Check(LoadedPacks() == 1 && g_bytes > 0 && g_cell, "on: one pack and some cut sprites held");
    const int stockLive = 24;
    BaseHdSet(0);
    Check(g_bytes == 0, "off: no cut sprite held", Num(g_bytes));
    Check(g_liveSprites == stockLive, "off: every HD sprite closed", Num(g_liveSprites));
    Check(LoadedPacks() == 0 && !g_cell, "off: no pack bytes, no cell buffer");
    Check(g_bufW <= 4 && g_bufH <= 4, "off: the scratch Buffer is 4x4", Num(g_bufW) + "x" + Num(g_bufH));
    Check(!Draw(0, 0) && LoadedPacks() == 0, "off: stock again, nothing read");
    BaseHdSet(1);
    Check(Draw(0, 0) && LoadedPacks() == 1, "on again: proven again at the first draw, HD");
}

// A failed HD cut at one size is remembered: never retried, stock each time; other sizes still HD.
static void FailureMemory()
{
    WritePack("FACA", kAll);
    WriteIni(1);
    Install();
    LoadFaction(0, "FACA");
    int w = 0, h = 0;
    basehd_law::CellSize(kCellW, kCellH, 22, 16, &w, &h);
    g_failW = w; g_failH = h;
    SetScale(22, 16);
    const int before = g_hdCuts;
    const bool a = Draw(0, 2), b = Draw(0, 2), c = Draw(0, 2);
    Check(!a && !b && !c, "the failed size draws stock");
    Check(g_hdCuts - before == 1, "the failed size was cut once, never retried", Num(g_hdCuts - before));
    Check(Logged("cuts empty") == 1, "one line for the failure", Num(Logged("cuts empty")));
    SetScale(16, 16);
    Check(Draw(0, 2), "another size of the same sprite is HD");
    const int cuts = g_hdCuts;
    Draw(0, 2);
    SetScale(22, 16);
    Draw(0, 2);
    Check(g_hdCuts == cuts, "revisiting both sizes cuts nothing");
}

// A blank cell is found at its first cut and stays stock for good, without another expand or cut.
static void BlankCell()
{
    bool cells[24];
    for (bool& c : cells) c = true;
    cells[5] = false;
    WritePack("FACA", cells);
    WriteIni(1);
    Install();
    LoadFaction(0, "FACA");
    SetScale(16, 16);
    const int before = g_hdCuts;
    Check(!Draw(0, 5) && !Draw(0, 5), "a blank cell draws stock");
    SetScale(25, 16);
    Check(!Draw(0, 5), "at every size");
    Check(g_hdCuts == before, "and is never cut", Num(g_hdCuts - before));
    Check(Logged("is blank") == 1, "one line for it", Num(Logged("is blank")));
    Check(Draw(0, 4), "its neighbour is HD");
}

// Over the budget the least recently drawn sprites go; what stays is the most recent; a dropped one is cut again.
static void BudgetTrim()
{
    WritePack("FACA", kAll);
    WriteIni(1);
    Install();
    LoadFaction(0, "FACA");
    SetScale(16, 16);                                   // 100 x 75 = 7,500 bytes each
    for (int i = 0; i < 24; ++i) Draw(0, i);
    const size_t each = static_cast<size_t>(kCellW) * kCellH, keep = kBudget / each;
    Check(g_bytes <= kBudget, "never over the budget", Num(g_bytes));
    Check(g_bytes == keep * each, "full up to the budget", Num(g_bytes));
    Check(g_liveSprites == 24 + static_cast<int>(keep), "dropped sprites are closed", Num(g_liveSprites));
    int held = 0;
    bool newest = true;
    for (int i = 0; i < 24; ++i) {
        Entry* e = EntryOf(SpriteAt(0, i));
        const bool has = e && Find(*e, kCellW, kCellH) && Find(*e, kCellW, kCellH)->state == 1;
        held += has;
        if (i >= 24 - static_cast<int>(keep) && !has) newest = false;
    }
    Check(held == static_cast<int>(keep) && newest, "the most recently drawn are the ones kept", Num(held));
    const int before = g_hdCuts;
    Check(Draw(0, 0) && g_hdCuts == before + 1, "a dropped sprite is cut again on its next draw");
}

// A new game puts a faction whose stock cut fails in a slot an HD faction used: drawn as the game draws it.
static void StaleEntry()
{
    WritePack("FACA", kAll);
    WritePack("FACB", kAll);
    WriteIni(1);
    Install();
    LoadFaction(0, "FACA");
    SetScale(16, 16);
    Check(Draw(0, 3), "game 1: FACA's sprite is HD");
    LoadFaction(0, "FACC", 3);                          // no pack; its sprite 3 cut fails
    Check(!Draw(0, 3) && g_lastDrawn == SpriteAt(0, 3), "game 2: no FACA art where FACC has no sprite");
    Check(!EntryOf(SpriteAt(0, 3)), "the entry is forgotten");
    Check(LoadedPacks() == 0, "FACA's pack is released", Num(LoadedPacks()));
    LoadFaction(0, "FACB", 7);                          // a pack, but its own sprite 7 cut fails
    Check(!Draw(0, 7), "a faction with a pack: the sprite whose stock cut failed stays stock");
    Check(Draw(0, 6), "its other sprites are HD");
}

// A sprite cut before install with no data is never adopted; one with data is.
static void AdoptSkipsEmpty()
{
    WritePack("FACA", kAll);
    WriteIni(1);
    SetFactionFile(1, "FACA");
    SprData(SpriteAt(1, 0)) = malloc(16);               // cut before install (has data)
    ++g_liveSprites;
    Install();
    SetScale(16, 16);
    Check(!Draw(1, 1) && !EntryOf(SpriteAt(1, 1)), "a sprite with no data is not adopted");
    Check(Draw(1, 0), "a sprite with data is adopted and HD");
}

// More factions in a session than the table has records: a record nothing uses is reused.
static void TableReuse()
{
    WritePack("FACA", kAll);
    WriteIni(1);
    Install();
    SetScale(16, 16);
    char stem[16];
    for (int i = 0; i < kPacks + 8; ++i) {
        _snprintf_s(stem, sizeof stem, _TRUNCATE, "S%02d", i);
        LoadFaction(0, stem);
        Draw(0, 0);
    }
    LoadFaction(0, "FACA");
    Check(Draw(0, 0), "after 40 factions in slot 0, FACA still gets a record and draws HD");
    Check(Logged("pack records are in use") == 0, "the table never filled");
}

// Junk ahead of a usable pack in directory order: the hook still installs, and the junk takes no record.
static void JunkFirst()
{
    char stem[16];
    for (int i = 0; i < kPacks + 8; ++i) {
        _snprintf_s(stem, sizeof stem, _TRUNCATE, "AAA%02d", i);
        WriteJunk(stem);
        WritePalette(stem);
    }
    WritePack("FACA", kAll);
    WriteIni(1);
    Install();
    Check(g_installed, "installed despite 40 unusable packs first");
    int used = 0;
    for (const FactionPack& p : g_packs) used += p.stem[0] != 0;
    Check(used == 0 && LoadedPacks() == 0 && !g_cell, "install holds no record and no bytes", Num(used));
}

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    g_root = argv[1];
    if (g_root.back() != '\\') g_root += '\\';
    CreateDirectoryA((g_root + "bases").c_str(), nullptr);
    strcpy_s(g_testDir, g_root.c_str());
    MakeImage();
    const std::string s = argv[2];
    if (s == "off_holds_nothing") OffHoldsNothing();
    else if (s == "failure_memory") FailureMemory();
    else if (s == "blank_cell") BlankCell();
    else if (s == "budget_trim") BudgetTrim();
    else if (s == "stale_entry") StaleEntry();
    else if (s == "adopt_skips_empty") AdoptSkipsEmpty();
    else if (s == "table_reuse") TableReuse();
    else if (s == "junk_first") JunkFirst();
    else return 2;
    return g_fails ? 1 : 0;
}
