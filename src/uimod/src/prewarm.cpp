// Background pre-bake of the replacement leader portraits.  See prewarm.h for the contract.
//
// WHY (measured 2026-10-14, bench %TEMP%\claude\pbench, HIVE.png 1103x1335, the live palette): a faction's first
// display costs, on the game thread, the PNG decode (36 ms), four native bakes (resample ~25 ms + dither 13..39 ms
// each, ~200 ms) and, above native scale, one enlarge per draw site (the picker shows the DIPLOMACY slot: resample
// 34 ms + dither 150 ms at 4K; Datalinks the datalink slot: 41 + 237 ms).  Every stage is a pure function of
// inputs the game thread can copy, so all of it moves to a worker that runs during the intro and the main menu.
//
// WHAT THE WORKER NEEDS, AND WHERE IT COMES FROM
//  - The palette, g and the scan mode: a Snapshot taken on the game thread at the FIRST load_faction_art (Phase-0
//    probe 2026-09-30: g_main_palette is loaded by then -- NOT at Init -- and identical at every later load and
//    draw; the dest table of every portrait draw is that palette).  Keyed anyway: a change is a miss, never a
//    stale hit.
//  - The image: portrait_files::Find, now under its own lock (the decode runs once, whoever asks first).
//  - The vanilla slot's (bright, ratio): ScanlineParams over the VANILLA sprite, which the engine cuts from
//    <faction>.pcx -- Buffer_load_pcx stores (raw + 10) & 0xFF, Sprite_extract_2 copies the rect (decompiled
//    2026-10-14; the rects are load_faction_art's literals).  ReadSheet does the same and the result reproduces
//    the engine's sprites bit for bit (tests\test_portrait_prewarm.py: all 28 Phase-0 sprite hashes).  Still a
//    PREDICTION as far as the cache is concerned: the hook reports the measured values (ReportMeasured) and a
//    disagreement re-keys or drops the affected jobs; a wrong prediction can only cost a miss.
//  - The stripe phase of an enlarge (the dest row the picture lands on): unknown until the draw, so every phase
//    of the current scale is a job (2T of them, 4 at g = 22..47); the first draw at a site makes its phase "hot"
//    and the remaining factions' jobs at that phase go first.
//
// LOGGING: the worker's own lines go through a small ring the game thread drains (TakeLog); portrait_files'
// decode lines are written by whichever thread decodes (UimodLog is one fopen / append / close per line).
//
// THREADING (the user's rules, 2026-10-14): one SRWLOCK over every shared structure, one condition variable for
// waiters; the worker holds the lock only to pick / publish, never while computing; it never takes another lock
// while holding this one (portrait_files has its own, taken outside ours).  A waiter waits only on a job the
// worker is RUNNING (bounded, kWaitMs); a queued job is taken over by the waiter (state sTaken) so nothing is
// ever built twice, and a failed or cancelled job is a plain miss.  The worker body is under SEH and C++ catch:
// a fault marks the job failed and wakes the waiter.  COM is initialised on the worker for WIC.  Shutdown: the
// state is heap-allocated and never freed, no static destructor touches it, nothing joins the thread -- ExitProcess
// ends it, and the loader lock never waits on it.  Memory: results are bytes, capped at kBudgetBytes.
#include "prewarm.h"
#include "portrait_files.h"
#include "portrait_law.h"

#include <windows.h>
#include <objbase.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <memory>
#include <new>
#include <vector>

void UimodLog(const char* msg);

namespace prewarm {

const SlotDef kSlotDefs[kSlots] = { { 96, 115, false }, { 118, 144, false }, { 131, 157, true }, { 164, 198, true } };

namespace {

constexpr int kKey = 9;                       // the engine's transparent index (Sprite_extract_2's key argument)
constexpr int kIndexShift = 10;               // Buffer_load_pcx: stored index = (raw + 10) & 0xFF
constexpr size_t kBudgetBytes = 32u << 20;    // all finished results together (bytes; ~2.2 MB per faction at 4K)
constexpr size_t kMaxNames = 14;              // = portrait_files' image cache: the working set never thrashes it
constexpr size_t kMaxSheetBytes = 4u << 20;
constexpr int kMaxSheetSide = 4096;
constexpr DWORD kWaitMs = 4000;               // a waiter's cap on ONE running job (the longest is ~280 ms at 4K)
constexpr int kMaxFailures = 3;               // after this many failed jobs the worker gives up (sync path only)
constexpr size_t kResampleKeep = 6;           // worker-local Lanczos results, shared by the phases of one enlarge
// The engine's rects in the sheet (load_faction_art @0x453710, Sprite_extract_2 literals), kSlotDefs order
struct SheetRect { int x, y; };
const SheetRect kSheetRects[kSlots] = { { 0x58, 0x1C9 }, { 0xB9, 0x1C9 }, { 0x130, 0x1C9 }, { 0x213, 1 } };
// Job order between slots: the picker shows the diplomacy slot, Datalinks the datalink, the council the two others
const int kSlotRank[kSlots] = { 3, 2, 0, 1 };

enum State { sQueued, sRunning, sDone, sFailed, sTaken, sDropped };
bool HasQueued();
void WorkerFault(const char* what, bool lockFree);
bool StartThread();
void ReapThread();
bool Stale(unsigned gen);                 // under the lock: cancelled, or a newer generation
enum Kind { kNative, kEnlarge };

struct Plan {                                 // one faction file (a replacement image + its vanilla sheet)
    char name[24] = {};
    int order = 0;
    uint64_t imgId = 0;                       // 0 = no replacement image (the worker looked, or has not yet)
    int w = 0, h = 0;
    bool resolved = false;                    // the worker looked the image up
    bool have[kSlots] = {}, measured[kSlots] = {};
    int bright[kSlots] = {}, ratio[kSlots] = { 256, 256, 256, 256 };
    bool built[kSlots] = {};                  // entries created for this slot
};

struct Entry {
    uint64_t key = 0;
    int plan = -1, slot = 0, kind = kNative, phase = 0;
    portrait_law::Rect crop{};
    int tw = 0, th = 0, scan = 0, bright = 0, ratio = 256, y0 = 0, rows = 1;
    int state = sQueued;
    std::vector<uint8_t> fit;                 // sDone: tw*th palette indices
    uint64_t imgId = 0, palHash = 0;
};

struct Shared {
    SRWLOCK lock = SRWLOCK_INIT;
    HANDLE done = nullptr;                    // auto-reset event: a job finished (a waiter needs no lock to be woken)
    volatile LONG dead = 0;                   // the worker died, or holds the lock for good: every entry is a no-op
    int failures = 0;                         // failed jobs since the last (re)start; kMaxFailures stops the worker
    Snapshot snap{};
    uint64_t palHash = 0;
    std::vector<std::unique_ptr<Plan>> plans;
    std::vector<std::unique_ptr<Entry>> entries;   // pointers stay valid: only ever appended
    int hot[kSlots] = { -1, -1, -1, -1 };
    bool started = false;
    bool running = false, restartPending = false;   // a worker thread is alive / one must follow it
    unsigned gen = 0;                         // bumped by Restart: an older worker winds down at its next check
    HANDLE thread = nullptr;                  // the worker (never joined; closed only when replaced); under the lock
    volatile LONG threadId = 0;               // its id: readable without the lock (WorkerAlive opens its own handle)
    volatile LONG cancel = 0;                 // test / fatal only: no worker ever again
    size_t doneBytes = 0;
    int nDone = 0, nFailed = 0, nDropped = 0, nTaken = 0, nHit = 0, nWait = 0;
    DWORD t0 = 0;
    char log[8][240];
    int logW = 0, logR = 0;
    int testFailEvery = 0, testThrowEvery = 0, testFaultEvery = 0, testDieInJob = 0, jobs = 0;
    volatile LONG testDieLocked = 0, testFaultOutside = 0;
    volatile LONG hotDirty = 0;               // a slot's draw phase changed since HotPhases last read them
};
constexpr DWORD kGameLockMs = 50;             // the game thread's bound on taking the lock (held for microseconds normally)
Shared* g = nullptr;                          // heap, never freed (see the header comment)
bool Stale(unsigned gen) { return g->cancel != 0 || g->gen != gen; }
Shared* Ensure()                              // the shared state (the event too), or null without memory
{
    if (!g) {
        g = new (std::nothrow) Shared();
        if (g) g->done = CreateEventW(nullptr, FALSE, FALSE, nullptr);   // null = waiters poll instead
    }
    return g;
}
void Wake() { if (g->done) SetEvent(g->done); }
bool WorkerAlive()                            // no lock: a handle of our own from the id (g->thread may be being replaced)
{
    const DWORD tid = static_cast<DWORD>(g->threadId);
    if (!tid) return false;
    const HANDLE h = OpenThread(SYNCHRONIZE | THREAD_QUERY_LIMITED_INFORMATION, FALSE, tid);
    if (!h) return false;
    const bool alive = WaitForSingleObject(h, 0) == WAIT_TIMEOUT && GetProcessIdOfThread(h) == GetCurrentProcessId();
    CloseHandle(h);
    return alive;
}
// The worker is gone or its lock is orphaned: remembered, so no later call pays the bounded wait again and no
// worker is ever started again (no lock needed: Interlocked).
void MarkDead()
{
    InterlockedExchange(&g->dead, 1);
    InterlockedExchange(&g->cancel, 1);
    if (g->done) SetEvent(g->done);           // a waiter in GetFit leaves at once
}
// A bounded try-acquire failed: a worker that is alive was merely starved (a loaded machine) -- this call misses and
// the next one tries again; a worker that is gone has orphaned the lock -- remembered.
void LockFailed() { if (!WorkerAlive()) MarkDead(); }

struct Lk {                                   // the worker: a plain acquire
    explicit Lk(Shared* s) : s_(s) { AcquireSRWLockExclusive(&s_->lock); }
    ~Lk() { ReleaseSRWLockExclusive(&s_->lock); }
    Shared* s_;
};
// The game thread: a bounded try-acquire.  A worker that died inside a locked region (a fault the SEH handler
// caught) would otherwise hang the game at its next lookup; here it costs kGameLockMs once per call and the
// synchronous path runs instead.
struct TryLk {
    TryLk(Shared* s, DWORD ms) : s_(s)
    {
        const DWORD t0 = GetTickCount();
        for (;;) {
            ok = TryAcquireSRWLockExclusive(&s_->lock) != 0;
            if (ok || GetTickCount() - t0 >= ms) break;
            Sleep(1);
        }
    }
    ~TryLk() { if (ok) ReleaseSRWLockExclusive(&s_->lock); }
    bool ok = false;
    Shared* s_;
};

uint64_t Fnv(uint64_t h, const void* p, size_t n)
{
    const uint8_t* b = static_cast<const uint8_t*>(p);
    for (size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 1099511628211ull; }
    return h;
}

uint64_t MakeKey(uint64_t imgId, portrait_law::Rect c, int tw, int th, uint64_t palHash, int scan, int bright,
                 int ratio, int y0, int rows)
{
    uint64_t k = Fnv(1469598103934665603ull, &imgId, sizeof imgId);
    const int v[11] = { c.x, c.y, c.w, c.h, tw, th, scan, bright, ratio, y0, rows };
    k = Fnv(k, v, sizeof v);
    return Fnv(k, &palHash, sizeof palHash);
}

// Queue a line for the game thread's log (under the lock).  Dropped when the ring is full.
void Say(const char* fmt, ...)
{
    if (g->logW - g->logR >= 8) return;
    char* dst = g->log[g->logW % 8];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(dst, 240, _TRUNCATE, fmt, ap);
    va_end(ap);
    ++g->logW;
}

bool SameName(const char* a, const char* b) { return _stricmp(a, b) == 0; }

Plan* FindPlan(const char* name)
{
    for (auto& p : g->plans) if (SameName(p->name, name)) return p.get();
    return nullptr;
}

Plan* AddPlan(const char* name)
{
    if (g->plans.size() >= kMaxNames) return nullptr;
    auto p = std::make_unique<Plan>();
    strncpy_s(p->name, name, _TRUNCATE);
    p->order = static_cast<int>(g->plans.size());
    g->plans.push_back(std::move(p));
    return g->plans.back().get();
}

Entry* FindEntry(uint64_t key)
{
    for (auto& e : g->entries) if (e->key == key) return e.get();
    return nullptr;
}

void Drop(Entry* e)
{
    if (e->state == sDone) { g->doneBytes -= e->fit.size(); --g->nDone; }
    std::vector<uint8_t>().swap(e->fit);
    e->state = sDropped;
    ++g->nDropped;
}

// The FromRgb inputs of slot `s` of plan `p` for kind / phase (what portrait.cpp's Bake / EnlargeRgb will ask for).
bool JobInputs(const Plan& p, int s, int kind, int phase, portrait_law::Rect* crop, int* tw, int* th, int* y0, int* rows)
{
    const SlotDef& d = kSlotDefs[s];
    const int m = d.framed ? 2 : 0;
    if (portrait_law::IsNativeArt(p.w, p.h, d.w, d.h, d.framed)) return false;   // BakeNative: no FromRgb, nothing to pre-bake
    if (kind == kNative) {
        *crop = portrait_law::FrameRect(p.w, p.h, d.w - m, d.h - m);
        *tw = d.w - m; *th = d.h - m; *y0 = d.framed ? 0 : -1; *rows = 1;
        return true;
    }
    const int num = g->snap.g, den = 16;
    int dw, dh, W1, H1, jt, il;
    if (!portrait_law::EnlargeGeometry(d.w, d.h, num, den, d.framed, &dw, &dh, &W1, &H1, &jt, &il)) return false;
    *crop = portrait_law::FrameRect(p.w, p.h, d.w - m, d.h - m);
    *tw = W1; *th = H1; *y0 = phase; *rows = portrait_law::ScanRows(num, den);
    return true;
}

// Under the lock: the entries of (plan, slot) -- a native bake and, above native scale, one enlarge per phase.
void BuildEntries(Plan& p, int s)
{
    if (p.built[s] || !p.resolved || !p.imgId || !p.have[s]) return;
    p.built[s] = true;
    const int phases = g->snap.g > 16 ? 2 * portrait_law::ScanRows(g->snap.g, 16) : 0;
    // native bakes in the current scan mode AND the other one the Preferences row can switch to (kScanOff <->
    // kScanMean; a toggle re-bakes all 28 slots on the game thread: cheap to pre-bake, ~20 KB each). The
    // darkening overlay mode is unreachable since the "Brighten Scanlines" row went (2026-10-30), so it is no
    // longer pre-baked -- a third of the native work for entries nothing could request. Enlarges in the current
    // mode only (twice the dither and the memory otherwise).
    constexpr int kNativeModes = 2;
    const int modes[kNativeModes] = { g->snap.scan, g->snap.scan == portrait_law::kScanOff ? portrait_law::kScanMean
                                                                                              : portrait_law::kScanOff };
    for (int kind = kNative; kind <= kEnlarge; ++kind)
        for (int mi = 0; mi < (kind == kNative ? kNativeModes : 1); ++mi)
            for (int phase = 0; phase < (kind == kNative ? 1 : phases); ++phase) {
                portrait_law::Rect crop; int tw, th, y0, rows;
                if (!JobInputs(p, s, kind, phase, &crop, &tw, &th, &y0, &rows)) continue;
                const int scan = modes[mi];
                const uint64_t key = MakeKey(p.imgId, crop, tw, th, g->palHash, scan, p.bright[s], p.ratio[s], y0, rows);
                if (Entry* old = FindEntry(key)) {    // stored already (PutFit, an earlier run), or dropped: queue it again
                    if (old->state == sDropped) { old->state = sQueued; old->plan = p.order; old->slot = s; old->kind = kind; old->phase = phase; old->palHash = g->palHash; --g->nDropped; }
                    continue;
                }
                auto e = std::make_unique<Entry>();
                e->key = key; e->plan = p.order; e->slot = s; e->kind = kind; e->phase = phase;
                e->crop = crop; e->tw = tw; e->th = th; e->scan = scan; e->bright = p.bright[s]; e->ratio = p.ratio[s];
                e->y0 = y0; e->rows = rows; e->imgId = p.imgId; e->palHash = g->palHash;
                g->entries.push_back(std::move(e));
            }
}

// ---- the vanilla sheet: <game>\<name>.pcx cut the engine's way -------------------------------------------------

bool ReadWhole(const wchar_t* path, std::vector<uint8_t>* out)
{
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    bool ok = false;
    BY_HANDLE_FILE_INFORMATION fi;
    if (GetFileInformationByHandle(f, &fi) && !(fi.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
        fi.nFileSizeHigh == 0 && fi.nFileSizeLow > 128 && fi.nFileSizeLow <= kMaxSheetBytes) {
        out->resize(fi.nFileSizeLow);
        DWORD got = 0;
        ok = ReadFile(f, out->data(), fi.nFileSizeLow, &got, nullptr) && got == fi.nFileSizeLow;
    }
    CloseHandle(f);
    return ok;
}

// 8-bit single-plane RLE PCX -> indices (w x h, pitch w).  Every read is bounds-checked; a run never crosses a
// scanline (a malformed file is clamped, not trusted).  False on anything unexpected.
bool DecodePcx8(const std::vector<uint8_t>& f, std::vector<uint8_t>* px, int* w, int* h)
{
    if (f.size() < 128 || f[0] != 0x0A || f[2] != 1 || f[3] != 8 || f[65] != 1) return false;
    auto u16 = [&](size_t o) { return static_cast<int>(f[o]) | (static_cast<int>(f[o + 1]) << 8); };
    const int xmin = u16(4), ymin = u16(6), xmax = u16(8), ymax = u16(10), bpl = u16(66);
    const int cw = xmax - xmin + 1, ch = ymax - ymin + 1;
    if (cw < 1 || ch < 1 || cw > kMaxSheetSide || ch > kMaxSheetSide || bpl < cw || bpl > 2 * kMaxSheetSide) return false;
    px->assign(static_cast<size_t>(cw) * ch, 0);
    size_t pos = 128;
    for (int y = 0; y < ch; ++y) {
        uint8_t* row = px->data() + static_cast<size_t>(y) * cw;
        int x = 0;
        while (x < bpl) {
            if (pos >= f.size()) return false;
            uint8_t c = f[pos++];
            int run = 1;
            if ((c & 0xC0) == 0xC0) {
                run = c & 0x3F;
                if (pos >= f.size()) return false;
                c = f[pos++];
            }
            if (run > bpl - x) run = bpl - x;  // never past the scanline
            for (int i = 0; i < run; ++i, ++x) if (x < cw) row[x] = c;
        }
    }
    *w = cw; *h = ch;
    return true;
}

// Slot `s` of a decoded sheet in the ENGINE's index space, pitch = slot width.  False when the rect is outside
// the sheet or the engine would trim it (a fully-keyed edge row / column; the hook refuses such a slot anyway).
bool CutSlot(const std::vector<uint8_t>& px, int w, int h, int s, std::vector<uint8_t>* out)
{
    const SlotDef& d = kSlotDefs[s];
    const SheetRect& r = kSheetRects[s];
    if (r.x < 0 || r.y < 0 || r.x + d.w > w || r.y + d.h > h) return false;
    out->resize(static_cast<size_t>(d.w) * d.h);
    for (int y = 0; y < d.h; ++y)
        for (int x = 0; x < d.w; ++x)
            (*out)[static_cast<size_t>(y) * d.w + x] = static_cast<uint8_t>((px[static_cast<size_t>(r.y + y) * w + r.x + x] + kIndexShift) & 0xFF);
    auto rowKeyed = [&](int y) { for (int x = 0; x < d.w; ++x) if ((*out)[static_cast<size_t>(y) * d.w + x] != kKey) return false; return true; };
    auto colKeyed = [&](int x) { for (int y = 0; y < d.h; ++y) if ((*out)[static_cast<size_t>(y) * d.w + x] != kKey) return false; return true; };
    return !rowKeyed(0) && !rowKeyed(d.h - 1) && !colKeyed(0) && !colKeyed(d.w - 1);
}

bool SheetPath(const char* name, wchar_t* out, size_t n)
{
    if (!portrait_files::SafeName(name) || !portrait_files::GameDir(out, n)) return false;
    const size_t have = wcslen(out);
    size_t i = 0;
    for (; name[i]; ++i) {
        if (have + i + 5 >= n) return false;
        out[have + i] = static_cast<wchar_t>(static_cast<unsigned char>(name[i]));
    }
    out[have + i] = 0;
    wcscat_s(out, n, L".pcx");
    return true;
}

// (bright, ratio) per slot from the faction's vanilla sheet; the engine falls back to faction.pcx when the
// faction's own sheet does not load, so does this.  ok[s] false = no prediction for that slot.
bool ReadSheet(const char* name, const uint8_t* pal, bool ok[kSlots], int bright[kSlots], int ratio[kSlots],
               uint32_t* hashes = nullptr)
{
    for (int s = 0; s < kSlots; ++s) ok[s] = false;
    std::vector<uint8_t> file, px;
    int w = 0, h = 0;
    wchar_t path[MAX_PATH];
    bool loaded = SheetPath(name, path, MAX_PATH) && ReadWhole(path, &file) && DecodePcx8(file, &px, &w, &h);
    if (!loaded) loaded = SheetPath("faction", path, MAX_PATH) && ReadWhole(path, &file) && DecodePcx8(file, &px, &w, &h);
    if (!loaded) return false;
    std::vector<uint8_t> cut;
    for (int s = 0; s < kSlots; ++s) {
        if (!CutSlot(px, w, h, s, &cut)) continue;
        portrait_law::ScanlineParams(cut.data(), kSlotDefs[s].w, kSlotDefs[s].w, kSlotDefs[s].h, pal, &bright[s], &ratio[s]);
        if (hashes) {
            uint32_t hh = 0x811C9DC5u;
            for (uint8_t b : cut) { hh ^= b; hh *= 0x01000193u; }
            hashes[s] = hh;
        }
        ok[s] = true;
    }
    return true;
}

// ---- the worker ------------------------------------------------------------------------------------------------

struct LocalResample : portrait_law::ResampleCache {    // the Lanczos pass, shared by the phases of one enlarge
    struct R { uint64_t id = 0; portrait_law::Rect c{}; int tw = 0, th = 0; unsigned stamp = 0; std::vector<uint8_t> px; };
    R keep[kResampleKeep];
    unsigned clock = 0;
    uint64_t id = 0;
    std::vector<int> scratch;
    const std::vector<int>* Get(portrait_law::Rect c, int tw, int th) override
    {
        for (R& r : keep)
            if (r.stamp && r.id == id && r.tw == tw && r.th == th && r.c.x == c.x && r.c.y == c.y && r.c.w == c.w && r.c.h == c.h) {
                if (r.px.size() != static_cast<size_t>(tw) * static_cast<size_t>(th) * 3) { r.stamp = 0; return nullptr; }
                r.stamp = ++clock;
                scratch.assign(r.px.begin(), r.px.end());
                return &scratch;
            }
        return nullptr;
    }
    void Put(portrait_law::Rect c, int tw, int th, const std::vector<int>& big) override
    {
        std::vector<uint8_t> px(big.size());      // built first: a bad_alloc here leaves every entry as it was
        for (size_t i = 0; i < big.size(); ++i) px[i] = static_cast<uint8_t>(big[i]);
        R* lru = &keep[0];
        for (R& r : keep) if (r.stamp < lru->stamp) lru = &r;
        lru->px.swap(px);
        lru->id = id; lru->c = c; lru->tw = tw; lru->th = th;
        lru->stamp = ++clock;
    }
};

struct JobCopy {                              // a running job's inputs, copied out under the lock
    Entry* e = nullptr;
    char name[24] = {};
    uint64_t imgId = 0;
    std::shared_ptr<const portrait_files::Image> img;   // fetched outside the lock, held for this job only
    portrait_law::Rect crop{};
    int tw = 0, th = 0, scan = 0, bright = 0, ratio = 256, y0 = 0, rows = 1;
    uint8_t pal[1024];                        // the snapshot's palette AS KEYED (a Restart may swap the snapshot meanwhile)
};

// Stage 1: the image and the predicted parameters of every plan; the entries.
void ResolvePlans(unsigned gen)
{
    std::vector<int> todo;
    {
        Lk l(g);
        for (auto& p : g->plans) todo.push_back(p->order);
    }
    char names[kMaxNames][24];
    const size_t n = portrait_files::ListNames(names, kMaxNames);
    {
        Lk l(g);
        for (size_t i = 0; i < n; ++i)
            if (!FindPlan(names[i]))
                if (Plan* p = AddPlan(names[i])) todo.push_back(p->order);
    }
    for (size_t i = 0; i < todo.size(); ++i) {
        char name[24];
        bool need[kSlots];
        uint8_t pal[1024];
        {
            Lk l(g);
            if (Stale(gen)) return;
            Plan& p = *g->plans[static_cast<size_t>(todo[i])];
            if (p.resolved) continue;
            memcpy(name, p.name, sizeof name);
            memcpy(pal, g->snap.pal, sizeof pal);     // a Restart may swap the snapshot meanwhile: read our copy
            for (int s = 0; s < kSlots; ++s) need[s] = !p.measured[s];
        }
        std::shared_ptr<const portrait_files::Image> img = portrait_files::Find(name);   // its own lock; not ours
        bool ok[kSlots] = {};
        int bright[kSlots] = {}, ratio[kSlots] = { 256, 256, 256, 256 };
        bool anyNeed = false;
        for (int s = 0; s < kSlots; ++s) anyNeed = anyNeed || need[s];
        if (img && anyNeed) ReadSheet(name, pal, ok, bright, ratio);
        Lk l(g);
        if (Stale(gen)) return;
        Plan& p = *g->plans[static_cast<size_t>(todo[i])];
        p.resolved = true;
        if (!img) continue;                   // the image itself stays in the files cache, not here (memory)
        p.imgId = img->id; p.w = img->w; p.h = img->h;
        for (int s = 0; s < kSlots; ++s)
            if (!p.measured[s] && ok[s]) { p.bright[s] = bright[s]; p.ratio[s] = ratio[s]; p.have[s] = true; }
        for (int s = 0; s < kSlots; ++s) BuildEntries(p, s);
    }
    // results no current image can reach (another image set after a Restart): freed, not kept for a toggle back
    Lk l(g);
    if (Stale(gen)) return;
    for (auto& e : g->entries) {
        if (e->state == sRunning || e->state == sDropped) continue;
        bool reachable = e->palHash == g->palHash;
        for (auto& p : g->plans) reachable = reachable && (p->imgId != 0 && p->imgId == e->imgId) ? true : reachable;
        if (reachable) {
            bool img = false;
            for (auto& p : g->plans) img = img || (p->imgId != 0 && p->imgId == e->imgId);
            reachable = img;
        }
        if (!reachable) Drop(e.get());
    }
}

// Under the lock: the next job -- the hot phase of a slot a draw has shown, then native bakes before enlarges,
// then the picker's slot before the others, then the factions in load order, then the phase.
Entry* Pick()
{
    Entry* best = nullptr;
    long bestRank = 0;
    for (auto& ue : g->entries) {
        Entry* e = ue.get();
        if (e->state != sQueued) continue;
        if (g->doneBytes + static_cast<size_t>(e->tw) * static_cast<size_t>(e->th) > kBudgetBytes) { Drop(e); continue; }
        // Tiers: a slot's known draw phase first; the loaded factions (the picker's rows) before the rest; the
        // current mode's native bakes, then the enlarges, then the other modes' natives (a toggle's, rare);
        // the picker's slot before the others; load order; phase.
        const Plan& p = *g->plans[static_cast<size_t>(e->plan)];
        bool loaded = false;
        for (int s = 0; s < kSlots; ++s) loaded = loaded || p.measured[s];
        const bool hot = e->kind == kEnlarge && g->hot[e->slot] >= 0 && e->phase == g->hot[e->slot];
        const long kindRank = e->kind == kNative ? (e->scan == g->snap.scan ? 0L : 2L) : 1L;
        const long rank = ((hot ? 0L : 1L) << 29) | ((loaded ? 0L : 1L) << 28) | (kindRank << 26) |
                          (static_cast<long>(kSlotRank[e->slot]) << 20) | (static_cast<long>(e->plan & 0xFFF) << 8) | (e->phase & 0xFF);
        if (!best || rank < bestRank) { best = e; bestRank = rank; }
    }
    return best;
}

bool ComputeJob(const JobCopy& j, LocalResample& rc, std::vector<int>* fit)
{
    if (g->testFaultEvery && g->jobs % g->testFaultEvery == 0) RaiseException(EXCEPTION_ACCESS_VIOLATION, 0, 0, nullptr);
    if (g->testDieInJob && g->jobs == g->testDieInJob) { Sleep(300); ExitThread(0); }   // (test) dies holding nothing
    rc.id = j.img->id;
    return portrait_law::FromRgb(j.img->rgb.data(), j.img->rgb.size(), j.img->w, j.img->h, j.crop, j.tw, j.th,
                                 j.pal, j.scan, j.bright, j.ratio, j.y0, j.rows, fit, &rc);
}

// SEH frame with nothing to unwind: a fault in the law is one failed job, not a dead process.
int ComputeGuarded(const JobCopy* j, LocalResample* rc, std::vector<int>* fit)
{
    __try { return ComputeJob(*j, *rc, fit) ? 1 : 0; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return -1; }
}

void Publish(Entry* e, int ok, const std::vector<int>& fit)
{
    Lk l(g);
    if (g->testDieLocked) ExitThread(0);      // (test) a worker that dies inside a locked region: the lock is orphaned
    if (e->state == sRunning) {
        if (ok == 1 && e->key != 0 && !g->cancel && g->doneBytes + fit.size() <= kBudgetBytes) {
            e->fit.resize(fit.size());
            for (size_t i = 0; i < fit.size(); ++i) e->fit[i] = static_cast<uint8_t>(fit[i]);
            e->state = sDone;
            g->doneBytes += e->fit.size();
            ++g->nDone;
        } else if (ok >= 0) {
            e->state = sDropped;
            ++g->nDropped;
        } else {
            e->state = sFailed;
            ++g->nFailed;
            ++g->failures;
        }
    }
    Wake();
}

// Stage 2: the jobs.
void RunJobs(unsigned gen)
{
    LocalResample rc;
    for (;;) {
        JobCopy j;
        {
            Lk l(g);
            if (Stale(gen) || g->failures >= kMaxFailures) return;
            j.e = Pick();
            if (!j.e) return;
            Plan& p = *g->plans[static_cast<size_t>(j.e->plan)];
            memcpy(j.name, p.name, sizeof j.name);
            j.imgId = p.imgId;
            j.crop = j.e->crop; j.tw = j.e->tw; j.th = j.e->th; j.scan = j.e->scan; j.bright = j.e->bright;
            j.ratio = j.e->ratio; j.y0 = j.e->y0; j.rows = j.e->rows;
            memcpy(j.pal, g->snap.pal, sizeof j.pal);
            if (j.e->palHash != g->palHash) { Drop(j.e); continue; }   // keyed on an older palette: not this snapshot's
            j.e->state = sRunning;
            ++g->jobs;
        }
        int ok = 0;
        std::vector<int> fit;
        if (g->testFaultOutside) RaiseException(EXCEPTION_ACCESS_VIOLATION, 0, 0, nullptr);   // (test) past every job guard
        j.img = portrait_files::Find(j.name);                 // the files cache's lock, never ours
        if (!j.img || j.img->id != j.imgId) ok = 0;          // gone (a setting switched), or edited: dropped, not a failure
        else if (g->testFailEvery && g->jobs % g->testFailEvery == 0) ok = -1;
        else {
            try {
                if (g->testThrowEvery && g->jobs % g->testThrowEvery == 0) throw std::bad_alloc();
                ok = ComputeGuarded(&j, &rc, &fit);
            }
            catch (...) { ok = -1; }          // bad_alloc and friends
            if (ok == 0) ok = -1;             // the law declined the inputs: a failure, not a drop
        }
        Publish(j.e, ok, fit);
        if (ok < 0) {
            Lk l(g);
            if (g->failures >= kMaxFailures) {
                Say("[uimod] portrait: prewarm stopped after %d failed jobs (synchronous path until the next settings change)\n", g->failures);
                return;
            }
        }
    }
}

void FinishRun(unsigned gen)
{
    Lk l(g);
    g->running = false;
    if (!Stale(gen))
        Say("[uimod] portrait: prewarm done in %lu ms: %d results (%u KB), %d failed, %d dropped, %d taken by the game thread\n",
            static_cast<unsigned long>(GetTickCount() - g->t0), g->nDone, static_cast<unsigned>(g->doneBytes >> 10),
            g->nFailed, g->nDropped, g->nTaken);
    if (g->restartPending && !g->cancel) { g->restartPending = false; StartThread(); }   // a Restart while we ran
    Wake();
}

void WorkerMain()
{
    unsigned gen;
    { Lk l(g); gen = g->gen; }
    const HRESULT ci = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    const bool own = ci == S_OK || ci == S_FALSE;
    try {
        // until nothing is queued, decided under the lock that also clears `running`: a job reported in between
        // (ReportMeasured) is either run here or restarts the thread, never stranded
        for (;;) {
            ResolvePlans(gen);
            RunJobs(gen);
            Lk l(g);
            if (Stale(gen) || g->failures >= kMaxFailures || !HasQueued()) break;
        }
    } catch (...) {
        WorkerFault("stopped by an exception", true);   // C++ unwinding released every Lk: a plain acquire is safe
    }
    FinishRun(gen);
    if (own) CoUninitialize();
}

// After an exception or a fault, which may have happened INSIDE a locked region: a try-lock, never a wait (an
// orphaned lock would hang this thread, and the game thread at its next lookup).  Without the lock the running
// job stays sRunning: a waiter times out (kWaitMs) and falls back; nothing hangs.
void WorkerFault(const char* what, bool lockFree)
{
    if (lockFree) AcquireSRWLockExclusive(&g->lock);
    else if (!TryAcquireSRWLockExclusive(&g->lock)) { MarkDead(); return; }   // the game thread holds it, or we did: over
    for (auto& e : g->entries) if (e->state == sRunning) { e->state = sFailed; ++g->nFailed; }
    g->running = false;
    InterlockedExchange(&g->cancel, 1);       // a faulted worker is never followed by another
    Say("[uimod] portrait: prewarm worker %s (synchronous path from here)\n", what);
    Wake();
    ReleaseSRWLockExclusive(&g->lock);
}

DWORD WINAPI WorkerThunk(LPVOID)
{
    __try { WorkerMain(); }
    __except (EXCEPTION_EXECUTE_HANDLER) { WorkerFault("faulted", false); }
    return 0;
}

// Under the lock: a worker that is gone without reporting (faulted while another thread held the lock) leaves
// `running` set and its job sRunning forever -- every lookup of that key would wait out kWaitMs.  The thread
// handle says whether it is alive.
void ReapThread()
{
    if (!g->running || !g->thread || WaitForSingleObject(g->thread, 0) != WAIT_OBJECT_0) return;
    g->running = false;
    InterlockedExchange(&g->cancel, 1);       // it died: never another one
    for (auto& e : g->entries) if (e->state == sRunning) { e->state = sFailed; ++g->nFailed; }
    Say("[uimod] portrait: prewarm worker ended without reporting (synchronous path from here)\n");
}

// Under the lock: start the worker thread, or, while one is still winding down, have it start the next one as it
// exits (never two at once).  False if it could not be created.
bool StartThread()
{
    if (g->cancel) return false;
    ReapThread();
    if (g->running) { g->restartPending = true; return true; }
    if (g->thread) { CloseHandle(g->thread); g->thread = nullptr; InterlockedExchange(&g->threadId, 0); }   // (a reusable id must not outlive its thread)
    DWORD tid = 0;
    const HANDLE h = CreateThread(nullptr, 256 * 1024, WorkerThunk, nullptr, CREATE_SUSPENDED, &tid);
    if (!h) {
        Say("[uimod] portrait: prewarm: CreateThread failed (%lu) -> synchronous bakes only\n", GetLastError());
        return false;
    }
    SetThreadPriority(h, THREAD_PRIORITY_BELOW_NORMAL);       // the intro movie decodes on the game thread meanwhile
    g->thread = h;
    InterlockedExchange(&g->threadId, static_cast<LONG>(tid));
    g->running = true;
    ResumeThread(h);
    return true;
}

bool HasQueued()
{
    for (auto& e : g->entries) if (e->state == sQueued) return true;
    return false;
}

} // namespace

// ---- game thread ----------------------------------------------------------------------------------------------

bool Start(const Snapshot& s)
{
    if (g && g->started) return false;
    if (!Ensure()) return false;
    Lk l(g);
    g->snap = s;
    g->palHash = Fnv(1469598103934665603ull, s.pal, sizeof s.pal);
    g->t0 = GetTickCount();
    for (int sl = 0; sl < kSlots; ++sl) if (g->hot[sl] < 0) g->hot[sl] = s.hot[sl];
    g->started = true;
    return StartThread();
}

bool HotPhases(int out[kSlots])
{
    for (int sl = 0; sl < kSlots; ++sl) out[sl] = -1;
    if (!g || g->dead || !g->hotDirty) return false;         // lock-free on the common path (every enlarged draw)
    TryLk l(g, 5);
    if (!l.ok) return false;                  // still dirty: read next time
    InterlockedExchange(&g->hotDirty, 0);
    for (int sl = 0; sl < kSlots; ++sl) out[sl] = g->hot[sl];
    return true;
}

bool Started() { return g && g->started; }
int  SnapshotG() { return g ? g->snap.g : 0; }

void ReportMeasured(const char* name, int slot, int bright, int ratio)
{
    if (slot < 0 || slot >= kSlots || !name || !name[0]) return;
    if (!Ensure() || g->dead) return;         // (reported before Start: kept for the worker; the loaded factions go first)
    TryLk l(g, kGameLockMs);
    if (!l.ok) { LockFailed(); return; }
    ReapThread();
    Plan* p = FindPlan(name);
    if (!p) p = AddPlan(name);
    if (!p) return;
    if (p->have[slot] && (p->bright[slot] != bright || p->ratio[slot] != ratio)) {
        // the prediction was wrong: queued jobs take the measured key, finished ones under the wrong key go
        for (auto& ue : g->entries) {
            Entry* e = ue.get();
            if (e->plan != p->order || e->slot != slot) continue;
            if (e->state == sQueued) {
                e->bright = bright; e->ratio = ratio;
                e->key = MakeKey(e->imgId, e->crop, e->tw, e->th, g->palHash, e->scan, bright, ratio, e->y0, e->rows);
            } else if (e->state == sRunning) {
                e->key = 0;                   // the worker is on it under the wrong key: its result is dropped (Publish)
            } else {
                Drop(e);
            }
        }
        Say("[uimod] portrait: prewarm: %s slot %d scanline params predicted %d/%d, measured %d/%d -> re-keyed\n",
            p->name, slot, p->bright[slot], p->ratio[slot], bright, ratio);
    }
    p->bright[slot] = bright; p->ratio[slot] = ratio;
    p->have[slot] = true; p->measured[slot] = true;
    p->built[slot] = false;                   // the slot's jobs again under the measured key (FindEntry dedups)
    if (p->resolved) BuildEntries(*p, slot);  // (a no-op without an image)
    // the worker may have finished already (a roster change long after start-up): run it again for the new jobs
    // (not after the failure stop: the next settings change resets that)
    if (!g->running && g->failures < kMaxFailures && HasQueued()) StartThread();
}

void Restart(const Snapshot& s)
{
    if (!g || !g->started || g->dead) return;
    TryLk l(g, kGameLockMs);
    if (!l.ok) { LockFailed(); return; }
    ReapThread();
    g->failures = 0;
    const bool scanChanged = s.scan != g->snap.scan, scaleChanged = s.g != g->snap.g;
    for (int sl = 0; sl < kSlots; ++sl) if (scaleChanged || g->hot[sl] < 0) g->hot[sl] = s.hot[sl];
    g->snap = s;
    g->palHash = Fnv(1469598103934665603ull, s.pal, sizeof s.pal);
    ++g->gen;
    g->t0 = GetTickCount();
    for (auto& p : g->plans) {                // every image looked up again (the set may have changed)
        p->resolved = false; p->imgId = 0;
        for (int sl = 0; sl < kSlots; ++sl) p->built[sl] = false;
    }
    for (auto& e : g->entries) {              // keep finished results the new snapshot can still reach
        if (e->state == sRunning || e->state == sDropped) continue;
        const bool stale = e->state != sDone || (e->kind == kEnlarge && (scanChanged && e->scan != s.scan || scaleChanged));
        if (stale) Drop(e.get());
    }
    Say("[uimod] portrait: prewarm restarted (settings changed: g=%d, scan mode %d)\n", s.g, s.scan);
    StartThread();
}

bool GetFit(uint64_t imgId, portrait_law::Rect crop, int tw, int th, const uint8_t* pal, int scan, int bright,
            int ratio, int y0, int rows, std::vector<int>* fit, int* why)
{
    int w = kNotStarted;
    bool ok = false;
    if (g && g->started && !g->dead) {
        const uint64_t palHash = Fnv(1469598103934665603ull, pal, 1024);
        const uint64_t key = MakeKey(imgId, crop, tw, th, palHash, scan, bright, ratio, y0, rows);
        TryLk l(g, kGameLockMs);
        if (!l.ok) { LockFailed(); if (why) *why = kAbsent; return false; }
        // the phase a draw site uses: the remaining factions' jobs at it go first
        for (auto& e : g->entries)
            if (e->kind == kEnlarge && e->slot >= 0 && e->tw == tw && e->th == th) {
                if (g->hot[e->slot] != y0) { g->hot[e->slot] = y0; InterlockedExchange(&g->hotDirty, 1); }
                break;
            }
        Entry* e = FindEntry(key);
        if (!e) {                             // ours to compute: a placeholder so the worker never builds it as well
            w = kAbsent;
            if (auto ne = std::make_unique<Entry>()) {
                ne->key = key; ne->crop = crop; ne->tw = tw; ne->th = th; ne->scan = scan; ne->bright = bright; ne->ratio = ratio;
                ne->y0 = y0; ne->rows = rows; ne->imgId = imgId; ne->palHash = palHash; ne->kind = rows > 1 ? kEnlarge : kNative;
                ne->slot = -1; ne->state = sTaken;
                g->entries.push_back(std::move(ne));
            }
        } else {
            if (e->state == sRunning) ReapThread();   // a worker that died on it: failed, not waited for
            if (e->state == sRunning) {
                ++g->nWait;
                if (g->thread) SetThreadPriority(g->thread, THREAD_PRIORITY_NORMAL);   // we are waiting on it
                const DWORD t0 = GetTickCount();
                // The lock is released around each sleep and re-taken with a bounded try: a worker that dies inside a
                // locked region while we wait can never hold this thread (SleepConditionVariableSRW would re-acquire
                // unbounded).  `e` stays valid: entries are only ever appended.
                // (g->thread is read only while the lock is held: StartThread may close and replace it meanwhile)
                while (e->state == sRunning && !g->dead && GetTickCount() - t0 < kWaitMs) {
                    ReleaseSRWLockExclusive(&g->lock);
                    l.ok = false;
                    if (g->done) WaitForSingleObject(g->done, 20); else Sleep(5);
                    const DWORD t1 = GetTickCount();
                    while (!(l.ok = TryAcquireSRWLockExclusive(&g->lock) != 0) && GetTickCount() - t1 < kGameLockMs) Sleep(1);
                    if (!l.ok) {              // (no handle to restore without the lock: a dead or starved worker)
                        LockFailed();
                        if (why) *why = kRunningTimeout;
                        return false;
                    }
                    ReapThread();             // died mid-job: the entry is failed now, not waited for
                }
                if (g->thread) SetThreadPriority(g->thread, THREAD_PRIORITY_BELOW_NORMAL);
            }
            switch (e->state) {
            case sDone:
                fit->resize(e->fit.size());
                for (size_t i = 0; i < e->fit.size(); ++i) (*fit)[i] = e->fit[i];
                ++g->nHit;
                ok = true; w = kHit;
                break;
            case sQueued: e->state = sTaken; ++g->nTaken; w = kQueuedTaken; break;
            case sRunning: w = kRunningTimeout; break;
            case sFailed: e->state = sTaken; w = kFailed; break;      // ours now: the worker never retries it
            case sDropped: e->state = sTaken; --g->nDropped; w = kDropped; break;
            default: w = kDropped; break;    // sTaken: an earlier sync run that never stored
            }
        }
    }
    if (why) *why = w;
    return ok;
}

void PutFit(uint64_t imgId, portrait_law::Rect crop, int tw, int th, const uint8_t* pal, int scan, int bright,
            int ratio, int y0, int rows, const std::vector<int>& fit)
{
    if (!g || !g->started || g->dead) return;
    const uint64_t palHash = Fnv(1469598103934665603ull, pal, 1024);
    const uint64_t key = MakeKey(imgId, crop, tw, th, palHash, scan, bright, ratio, y0, rows);
    TryLk l(g, kGameLockMs);
    if (!l.ok) { LockFailed(); return; }
    if (g->doneBytes + fit.size() > kBudgetBytes) return;
    Entry* e = FindEntry(key);
    if (!e) {
        auto ne = std::make_unique<Entry>();
        ne->key = key; ne->crop = crop; ne->tw = tw; ne->th = th; ne->scan = scan; ne->bright = bright; ne->ratio = ratio;
        ne->y0 = y0; ne->rows = rows; ne->imgId = imgId; ne->palHash = palHash; ne->kind = rows > 1 ? kEnlarge : kNative; ne->slot = -1;
        g->entries.push_back(std::move(ne));
        e = g->entries.back().get();
    } else if (e->state == sRunning || e->state == sDone) {
        return;                               // the worker is storing the same bytes, or has
    }
    e->fit.resize(fit.size());
    for (size_t i = 0; i < fit.size(); ++i) e->fit[i] = static_cast<uint8_t>(fit[i]);
    e->state = sDone;
    g->doneBytes += e->fit.size();
    ++g->nDone;
}

bool TakeLog(char* out, size_t n)
{
    if (!g || g->dead || g->logR == g->logW) return false;   // a racy read: a line seen late is seen next time
    TryLk l(g, 5);
    if (!l.ok) { LockFailed(); return false; }
    if (g->logR == g->logW) return false;
    strncpy_s(out, n, g->log[g->logR % 8], _TRUNCATE);
    ++g->logR;
    return true;
}

// ---- test / diagnostics ---------------------------------------------------------------------------------------

void Cancel() { if (g) InterlockedExchange(&g->cancel, 1); }
bool Finished() { if (!g || g->dead) return true; TryLk l(g, 200); if (!l.ok) return !WorkerAlive(); return !g->running && !g->restartPending; }
void WaitIdle() { while (!Finished()) Sleep(5); }
void TestFailEvery(int n) { if (Ensure()) { Lk l(g); g->testFailEvery = n; } }
void TestThrowEvery(int n) { if (Ensure()) { Lk l(g); g->testThrowEvery = n; } }
void TestFaultEvery(int n) { if (Ensure()) { Lk l(g); g->testFaultEvery = n; } }
void TestDieLocked() { if (Ensure()) InterlockedExchange(&g->testDieLocked, 1); }
void TestFaultOutsideJob() { if (Ensure()) InterlockedExchange(&g->testFaultOutside, 1); }
void TestDieInJob(int n) { if (Ensure()) { Lk l(g); g->testDieInJob = n; } }
bool Dead() { return g && g->dead; }
bool Running() { if (!g || g->dead) return false; TryLk l(g, 200); if (!l.ok) return WorkerAlive(); return g->running || g->restartPending; }

void DebugEntries(std::vector<EntryInfo>* out)
{
    out->clear();
    if (!g || g->dead) return;
    TryLk l(g, 200);
    if (!l.ok) return;
    for (auto& e : g->entries)
        out->push_back({ e->imgId, e->palHash, e->crop, e->tw, e->th, e->scan, e->bright, e->ratio, e->y0, e->rows, e->slot,
                         e->kind, e->state, e->fit.size() });
}

bool DebugSheetSlot(const char* name, int slot, const uint8_t* pal, int* bright, int* ratio, uint32_t* hash)
{
    if (slot < 0 || slot >= kSlots) return false;
    bool ok[kSlots]; int b[kSlots], r[kSlots]; uint32_t hh[kSlots] = {};
    if (!ReadSheet(name, pal, ok, b, r, hh) || !ok[slot]) return false;
    *bright = b[slot]; *ratio = r[slot]; *hash = hh[slot];
    return true;
}

} // namespace prewarm
