// Harness for uimod prewarm.cpp (tests\test_portrait_prewarm.py): the REAL worker thread, lock, cache and sheet
// reader, run from a throwaway folder laid out like a game directory (the exe's own folder is the "game dir").
//   sheet <name> <slot> <pal.bin>     -> "<bright> <ratio> <fnv32 of the cut>" or "none"
//   names                             -> ListNames, one per line
//   run <g> <scan> <pal.bin>          -> start, wait, verify every result against the plain law (no cache)
//   race <g> <scan> <pal.bin>         -> start, then look every job up from THIS thread while the worker runs
//                                        (waits on running jobs, takes queued ones over), verify everything
//   cancel <g> <scan> <pal.bin>       -> start, cancel at once, look everything up: must return promptly
//   fail <n> <g> <scan> <pal.bin>     -> every n-th job fails: those keys miss, the rest verify
//   sehfault <n> <g> <scan> <pal.bin> -> every n-th job raises an access violation inside the law: caught per job,
//                                        the worker stops after kMaxFailures, the rest stay queued (sync path)
//   orphan <g> <scan> <pal.bin>       -> the worker exits inside a locked region: every game-thread entry must
//                                        return promptly for good (the dead state), never hang
//   thunkfault <g> <scan> <pal.bin>   -> an access violation outside any job guard (WorkerThunk's handler): the
//                                        worker reports, stops, the lock is free, lookups are plain misses
//   diewait <g> <scan> <pal.bin>      -> the worker dies mid-job while this thread waits on that job: the wait
//                                        ends by the reaper, not by the 4 s bound
//   fileslock <ms> <die> <name>       -> a thread holds the files-cache lock `ms` ms and then releases (die=0) or
//                                        exits holding it (die=1): Find returns, and the bypass latches only for 1;
//                                        die=2: THIS thread orphans the lock (a caught fault skipped the release):
//                                        the next Find latches at once
//   phases <text>                     -> ParseHotPhases / FormatHotPhases round trip
//   rekey <g> <scan> <pal.bin>        -> the measured params of slot 2 differ from the prediction: old key misses,
//                                        new key hits and verifies
//   restartscan <g> <scan> <pal.bin>  -> Restart in another scan mode: natives of every mode kept, old-mode enlarges
//                                        dropped, new-mode enlarges built and verified
//   restartimg <g> <scan> <pal.bin>   -> Restart with the pack off (no images): everything dropped; then on again:
//                                        everything rebuilt and verified
//   stress <g> <scan> <pal.bin> <ms> [throwevery]
//                                     -> a second thread Restarts every ~400 ms (scan mode cycling, the palette
//                                        perturbed every third time, sometimes twice back to back) while this thread
//                                        looks random jobs up, verifying every hit against the plain law under the
//                                        palette that keyed it; then everything is verified once more at rest.  It
//                                        runs at least <ms> AND until kStressRestarts restarts, kStressLookups lookups
//                                        and one hit have happened (capped=1 if kStressCapMs ran out first): the
//                                        churn a run sees is fixed, not whatever a loaded machine fits into <ms>
// Counters print as "k=v" pairs on one line.
//
// No mode synchronises by sleeping: a machine running several suites at once starves a below-normal thread for whole
// seconds, so every "the worker / the holder has got there" is waited for (WaitIdle, the worker thread's exit, the
// holder's ownership of the lock).  Elapsed times still print, for the log; the tests assert outcomes.
#include "../../src/uimod/src/prewarm.cpp"
#include "../../src/uimod/src/portrait_files.cpp"
#include <cstdio>
#include <cstring>
#include <map>
#include <string>

#pragma comment(lib, "windowscodecs.lib")
#pragma comment(lib, "ole32.lib")

void UimodLog(const char* msg) { std::fputs(msg, stderr); }

namespace {

bool ReadPal(const char* path, uint8_t pal[1024])
{
    FILE* f = std::fopen(path, "rb");
    if (!f) return false;
    const bool ok = std::fread(pal, 1, 1024, f) == 1024;
    std::fclose(f);
    return ok;
}

uint64_t FnvPal(const uint8_t* pal)
{
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < 1024; ++i) { h ^= pal[i]; h *= 1099511628211ull; }
    return h;
}

struct Ctx {
    prewarm::Snapshot snap;
    std::map<uint64_t, std::shared_ptr<const portrait_files::Image>> images;   // id -> image, for the direct law
    std::map<uint64_t, std::vector<uint8_t>> pals;                             // palette hash -> palette (stress)
    SRWLOCK palLock = SRWLOCK_INIT;
    void RememberPal(const uint8_t* pal)
    {
        AcquireSRWLockExclusive(&palLock);
        pals[FnvPal(pal)] = std::vector<uint8_t>(pal, pal + 1024);
        ReleaseSRWLockExclusive(&palLock);
    }
    bool PalFor(uint64_t h, uint8_t* out)
    {
        AcquireSRWLockExclusive(&palLock);
        auto it = pals.find(h);
        const bool ok = it != pals.end();
        if (ok) memcpy(out, it->second.data(), 1024);
        ReleaseSRWLockExclusive(&palLock);
        return ok;
    }
    void LoadImages()
    {
        char names[32][24];
        const size_t n = portrait_files::ListNames(names, 32);
        for (size_t i = 0; i < n; ++i)
            if (auto img = portrait_files::Find(names[i])) images[img->id] = img;
    }
    // the plain law for an entry's inputs (no cache of any kind), under the palette that keyed the entry
    bool Direct(const prewarm::EntryInfo& e, int bright, int ratio, std::vector<int>* fit)
    {
        auto it = images.find(e.imgId);
        if (it == images.end()) return false;
        uint8_t pal[1024];
        if (!PalFor(e.palHash, pal)) return false;
        const auto& im = *it->second;
        return portrait_law::FromRgb(im.rgb.data(), im.rgb.size(), im.w, im.h, e.crop, e.tw, e.th, pal, e.scan,
                                     bright, ratio, e.y0, e.rows, fit, nullptr);
    }
    bool Lookup(const prewarm::EntryInfo& e, int bright, int ratio, std::vector<int>* fit, int* why)
    {
        uint8_t pal[1024];
        if (!PalFor(e.palHash, pal)) { *why = -2; return false; }
        return prewarm::GetFit(e.imgId, e.crop, e.tw, e.th, pal, e.scan, bright, ratio, e.y0, e.rows, fit, why);
    }
};

constexpr int kStressRestarts = 8, kStressLookups = 30;
constexpr DWORD kStressCapMs = 300000;        // a hang bound only: the targets take ~6 s alone

struct Stress {                               // the restarting thread of the stress mode
    Ctx* c;
    volatile LONG stop = 0;
    volatile LONG restarts = 0;
    static DWORD WINAPI Run(LPVOID p)
    {
        Stress* s = static_cast<Stress*>(p);
        prewarm::Snapshot snap = s->c->snap;
        for (int i = 0; !s->stop; ++i) {
            Sleep(400);                       // long enough for jobs to finish between restarts (waits and hits happen)
            snap.scan = (snap.scan + 1) % 3;
            if (i % 3 == 2) { snap.pal[(i * 37) % 1024 / 4 * 4 + 1] ^= 1; s->c->RememberPal(snap.pal); }
            prewarm::Restart(snap);
            InterlockedIncrement(&s->restarts);
            if (i % 4 == 3) { prewarm::Restart(snap); InterlockedIncrement(&s->restarts); }   // two back to back
        }
        return 0;
    }
};

int Verify(Ctx& c, int* hits, int* mismatch, int* missing)
{
    std::vector<prewarm::EntryInfo> es;
    prewarm::DebugEntries(&es);
    *hits = *mismatch = *missing = 0;
    for (const auto& e : es) {
        if (e.state != 2) continue;           // kDone
        std::vector<int> got, want;
        int why = -1;
        if (!c.Lookup(e, e.bright, e.ratio, &got, &why)) { ++*missing; continue; }
        ++*hits;
        if (!c.Direct(e, e.bright, e.ratio, &want) || want != got) ++*mismatch;
    }
    return static_cast<int>(es.size());
}

void Counts(const std::vector<prewarm::EntryInfo>& es, int* done, int* failed, int* taken, int* dropped, size_t* bytes)
{
    *done = *failed = *taken = *dropped = 0; *bytes = 0;
    for (const auto& e : es) {
        if (e.state == 2) ++*done;
        if (e.state == 3) ++*failed;
        if (e.state == 4) ++*taken;
        if (e.state == 5) ++*dropped;
        *bytes += e.bytes;
    }
}

void WaitWorkerGone()                         // the worker thread has exited (however it ended)
{
    while (prewarm::WorkerAlive()) Sleep(5);
}

} // namespace

int main(int argc, char** argv)
{
    if (argc < 2) return 2;
    const std::string mode = argv[1];
    if (mode == "sheet") {
        if (argc != 5) return 2;
        uint8_t pal[1024];
        if (!ReadPal(argv[4], pal)) return 3;
        int b = 0, r = 0; uint32_t h = 0;
        if (!prewarm::DebugSheetSlot(argv[2], std::atoi(argv[3]), pal, &b, &r, &h)) { std::printf("none"); return 0; }
        std::printf("%d %d %08x", b, r, h);
        return 0;
    }
    if (mode == "phases") {
        if (argc != 3) return 2;
        int hot[4];
        prewarm::ParseHotPhases(argv[2], hot);
        char v[64];
        prewarm::FormatHotPhases(hot, v, sizeof v);
        std::printf("%d %d %d %d |%s|", hot[0], hot[1], hot[2], hot[3], v);
        return 0;
    }
    if (mode == "fileslock") {
        if (argc != 5) return 2;
        const int ms = std::atoi(argv[2]);
        const int dieMode = std::atoi(argv[3]);
        const bool die = dieMode == 1;
        LONG holder = 0;
        if (dieMode == 2) portrait_files::TestOrphanLockHere();
        else {
            portrait_files::TestHoldLock(ms, die);
            // TestHoldLock gives its below-normal holder 20 ms to take the lock; a loaded machine may not run it for
            // seconds, and Find then found the lock free.  Wait until the holder owns it.
            while (!(holder = portrait_files::g_lockOwner)) Sleep(1);
        }
        const bool contended = dieMode == 2 || portrait_files::g_lockOwner == holder;   // still held as Find starts
        const DWORD t = GetTickCount();
        auto a = portrait_files::Find(argv[4]);
        const DWORD first = GetTickCount() - t;
        const bool heldAtReturn = holder && portrait_files::g_lockOwner == holder;      // Find left the holder holding
        const DWORD t2 = GetTickCount();
        auto b = portrait_files::Find(argv[4]);
        const DWORD second = GetTickCount() - t2;
        std::printf("first=%d firstms=%lu second=%d secondms=%lu same=%d dead=%d contended=%d heldatreturn=%d\n", a ? 1 : 0,
                    static_cast<unsigned long>(first), b ? 1 : 0, static_cast<unsigned long>(second), (a && a.get() == b.get()) ? 1 : 0,
                    portrait_files::DebugLockDead() ? 1 : 0, contended ? 1 : 0, heldAtReturn ? 1 : 0);
        return 0;
    }
    if (mode == "names") {
        char names[32][24];
        const size_t n = portrait_files::ListNames(names, 32);
        for (size_t i = 0; i < n; ++i) std::printf("%s\n", names[i]);
        return 0;
    }
    int ai = 2, failEvery = 0, stressMs = 0, throwEvery = 0, faultEvery = 0;
    if (mode == "fail") { failEvery = std::atoi(argv[ai++]); }
    if (mode == "sehfault") { faultEvery = std::atoi(argv[ai++]); }
    if (mode == "stress") {
        if (argc < ai + 4) return 2;
        stressMs = std::atoi(argv[ai + 3]);
        if (argc > ai + 4) throwEvery = std::atoi(argv[ai + 4]);
    } else if (argc != ai + 3) return 2;
    Ctx c;
    c.snap.g = std::atoi(argv[ai]);
    c.snap.scan = std::atoi(argv[ai + 1]);
    if (!ReadPal(argv[ai + 2], c.snap.pal)) return 3;
    c.RememberPal(c.snap.pal);
    c.LoadImages();                           // decoded here first: the worker's Find then hits the files cache
    if (failEvery) prewarm::TestFailEvery(failEvery);
    if (throwEvery) prewarm::TestThrowEvery(throwEvery);
    if (faultEvery) prewarm::TestFaultEvery(faultEvery);
    const DWORD t0 = GetTickCount();

    if (mode == "thunkfault") {
        prewarm::TestFaultOutsideJob();
        if (!prewarm::Start(c.snap)) return 4;
        prewarm::WaitIdle();                  // the worker has faulted and reported (WorkerFault clears `running`)
        std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
        const DWORD t1 = GetTickCount();
        int hits = 0, misses = 0;
        for (const auto& e : es) { std::vector<int> f; int why = -1; if (c.Lookup(e, e.bright, e.ratio, &f, &why)) ++hits; else ++misses; }
        std::printf("entries=%d hits=%d misses=%d ms=%lu running=%d dead=%d\n", static_cast<int>(es.size()), hits, misses,
                    static_cast<unsigned long>(GetTickCount() - t1), prewarm::Running() ? 1 : 0, prewarm::Dead() ? 1 : 0);
        char line[240];
        while (prewarm::TakeLog(line, sizeof line)) std::fputs(line, stderr);   // the worker's ring: its own report
        return 0;
    }
    if (mode == "diewait") {
        prewarm::TestDieInJob(1);             // the first job sleeps 300 ms, then the thread exits holding nothing
        if (!prewarm::Start(c.snap)) return 4;
        prewarm::EntryInfo running{};
        bool found = false;
        while (!found && prewarm::WorkerAlive()) {   // catch the running job (running until the thread exits)
            std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
            for (const auto& e : es) if (e.state == 1) { running = e; found = true; break; }
            if (!found) Sleep(1);
        }
        if (!found) { std::printf("found=0\n"); return 0; }
        std::vector<int> f; int why = -1;
        const DWORD t1 = GetTickCount();
        const bool hit = c.Lookup(running, running.bright, running.ratio, &f, &why);
        std::printf("found=1 hit=%d why=%d waitms=%lu running=%d\n", hit ? 1 : 0, why, static_cast<unsigned long>(GetTickCount() - t1),
                    prewarm::Running() ? 1 : 0);
        return 0;
    }
    if (mode == "orphan") {
        if (!prewarm::Start(c.snap)) return 4;
        prewarm::TestDieLocked();
        WaitWorkerGone();                     // the worker publishes its first job and dies holding the lock
        std::vector<int> f; int why = -1;
        uint8_t pal[1024]; memcpy(pal, c.snap.pal, 1024);
        portrait_law::Rect crop{ 0, 0, 10, 10 };
        const DWORD t1 = GetTickCount();
        int calls = 0, deadAfterFirst = -1;
        for (int i = 0; i < 20; ++i) {        // GetFit, PutFit, ReportMeasured, Restart, TakeLog: all bounded, then free
            prewarm::GetFit(1, crop, 8, 8, pal, 1, 0, 200, 0, 1, &f, &why); ++calls;
            if (deadAfterFirst < 0) deadAfterFirst = prewarm::Dead() ? 1 : 0;   // the one bounded wait latched it
            prewarm::PutFit(1, crop, 8, 8, pal, 1, 0, 200, 0, 1, std::vector<int>(64, 10)); ++calls;
            prewarm::ReportMeasured("gaians", 2, 0, 200); ++calls;
            prewarm::Restart(c.snap); ++calls;
            char line[240]; prewarm::TakeLog(line, sizeof line); ++calls;
        }
        std::printf("calls=%d ms=%lu dead=%d deadafterfirst=%d\n", calls, static_cast<unsigned long>(GetTickCount() - t1),
                    prewarm::Dead() ? 1 : 0, deadAfterFirst);
        return 0;
    }

    if (mode == "stress") {
        if (!prewarm::Start(c.snap)) return 4;
        Stress st; st.c = &c;
        const HANDLE th = CreateThread(nullptr, 0, Stress::Run, &st, 0, nullptr);
        if (!th) return 7;
        int hits = 0, mismatch = 0, taken = 0, waits = 0, other = 0, lookups = 0;
        unsigned seed = 12345;
        bool capped = false;
        for (;;) {
            const DWORD el = GetTickCount() - t0;
            if (el >= static_cast<DWORD>(stressMs) && st.restarts >= kStressRestarts && lookups >= kStressLookups && hits >= 1) break;
            if (el >= kStressCapMs) { capped = true; break; }
            std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
            if (es.empty()) { Sleep(1); continue; }
            seed = seed * 1103515245u + 12345u;
            const prewarm::EntryInfo e = es[(seed >> 8) % es.size()];
            std::vector<int> got, want;
            int why = -1;
            const DWORD t = GetTickCount();
            const bool hit = c.Lookup(e, e.bright, e.ratio, &got, &why);
            if (GetTickCount() - t > 50) ++waits;
            ++lookups;
            if (why == -2) { ++other; continue; }
            if (hit) {
                ++hits;
                if (!c.Direct(e, e.bright, e.ratio, &want) || want != got) ++mismatch;
            } else if (why == prewarm::kQueuedTaken || why == prewarm::kAbsent || why == prewarm::kDropped || why == prewarm::kFailed) {
                ++taken;
                uint8_t pal[1024];
                if (c.Direct(e, e.bright, e.ratio, &want) && c.PalFor(e.palHash, pal))
                    prewarm::PutFit(e.imgId, e.crop, e.tw, e.th, pal, e.scan, e.bright, e.ratio, e.y0, e.rows, want);
            } else ++other;                   // running (timed out): the sync path
        }
        InterlockedExchange(&st.stop, 1);
        WaitForSingleObject(th, INFINITE);    // it looks at `stop` after every ~400 ms nap
        CloseHandle(th);
        prewarm::WaitIdle();
        int h2, m2, miss2;
        const int n = Verify(c, &h2, &m2, &miss2);
        std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
        int done, failed, tk, dropped; size_t bytes; Counts(es, &done, &failed, &tk, &dropped, &bytes);
        int stuckRunning = 0;
        for (const auto& e : es) if (e.state == 1) ++stuckRunning;
        std::printf("entries=%d restarts=%d lookups=%d hits=%d waits=%d taken=%d other=%d mismatch=%d final_hits=%d final_mismatch=%d final_missing=%d done=%d failed=%d running=%d capped=%d ms=%lu\n",
                    n, static_cast<int>(st.restarts), lookups, hits, waits, taken, other, mismatch, h2, m2, miss2, done, failed,
                    stuckRunning, capped ? 1 : 0, static_cast<unsigned long>(GetTickCount() - t0));
        return 0;
    }

    if (mode == "run" || mode == "fail" || mode == "sehfault") {
        if (!prewarm::Start(c.snap)) return 4;
        prewarm::WaitIdle();
        int hits, mismatch, missing;
        const int n = Verify(c, &hits, &mismatch, &missing);
        std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
        int done, failed, taken, dropped; size_t bytes;
        Counts(es, &done, &failed, &taken, &dropped, &bytes);
        // failed keys must be plain misses (why = kFailed), never a hang or a wrong result
        int failedMiss = 0;
        for (const auto& e : es)
            if (e.state == 3) { std::vector<int> f; int why = -1; if (!c.Lookup(e, e.bright, e.ratio, &f, &why) && why == prewarm::kFailed) ++failedMiss; }
        int queued = 0;
        for (const auto& e : es) if (e.state == 0) ++queued;
        std::printf("entries=%d done=%d failed=%d failedmiss=%d taken=%d dropped=%d queued=%d bytes=%u hits=%d mismatch=%d missing=%d ms=%lu\n",
                    n, done, failed, failedMiss, taken, dropped, queued, static_cast<unsigned>(bytes), hits, mismatch, missing,
                    static_cast<unsigned long>(GetTickCount() - t0));
        return 0;
    }
    if (mode == "race") {
        if (!prewarm::Start(c.snap)) return 4;
        std::map<uint64_t, int> seen;         // key (imgId ^ geometry) -> checked
        int hits = 0, waits = 0, taken = 0, mismatch = 0, other = 0;
        for (int round = 0; ; ++round) {
            const bool finished = prewarm::Finished();
            std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
            for (const auto& e : es) {
                const uint64_t k = e.imgId ^ (static_cast<uint64_t>(e.tw) << 40) ^ (static_cast<uint64_t>(e.th) << 20) ^
                                   (static_cast<uint64_t>(e.y0 + 8) << 8) ^ static_cast<uint64_t>(e.slot) ^ (static_cast<uint64_t>(e.kind) << 4) ^
                                   (static_cast<uint64_t>(e.scan) << 6);
                if (seen.count(k)) continue;
                if (e.state == 0 && !finished && round < 3) continue;   // let the worker have some of them first
                seen[k] = 1;
                std::vector<int> got, want;
                int why = -1;
                const DWORD t = GetTickCount();
                const bool hit = c.Lookup(e, e.bright, e.ratio, &got, &why);
                if (GetTickCount() - t > 50) ++waits;
                if (!c.Direct(e, e.bright, e.ratio, &want)) { ++other; continue; }
                if (hit) { ++hits; if (want != got) ++mismatch; }
                else if (why == prewarm::kQueuedTaken) {
                    ++taken;                  // the game thread's own result goes back so the worker skips it
                    prewarm::PutFit(e.imgId, e.crop, e.tw, e.th, c.snap.pal, e.scan, e.bright, e.ratio, e.y0, e.rows, want);
                } else ++other;
            }
            if (finished) break;
            Sleep(1);
        }
        int h2, m2, miss2;
        const int n = Verify(c, &h2, &m2, &miss2);
        std::printf("entries=%d hits=%d waits=%d taken=%d other=%d mismatch=%d final_hits=%d final_mismatch=%d final_missing=%d ms=%lu\n",
                    n, hits, waits, taken, other, mismatch, h2, m2, miss2, static_cast<unsigned long>(GetTickCount() - t0));
        return 0;
    }
    if (mode == "cancel") {
        if (!prewarm::Start(c.snap)) return 4;
        Sleep(30);                            // let it get going (any progress will do: none at all is a valid case too)
        prewarm::Cancel();
        std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
        // After Cancel the worker starts no further job (Stale is checked under the lock before every Pick), so the
        // snapshot holds every job that will ever run: a lookup may wait on those (<= 1, one worker) and on nothing
        // else -- each still-queued job comes back at once, taken over, never baked by the worker first.
        int runningAtCancel = 0;
        for (const auto& e : es) if (e.state == 1) ++runningAtCancel;
        const DWORD t = GetTickCount();
        int hits = 0, misses = 0, queuedHit = 0, queuedTaken = 0, queuedAtCancel = 0;
        for (const auto& e : es) {
            std::vector<int> f; int why = -1;
            const bool hit = c.Lookup(e, e.bright, e.ratio, &f, &why);
            if (hit) ++hits; else ++misses;
            if (e.state == 0) { ++queuedAtCancel; if (hit) ++queuedHit; if (why == prewarm::kQueuedTaken) ++queuedTaken; }
        }
        const DWORD lookupMs = GetTickCount() - t;
        prewarm::WaitIdle();
        int h2, m2, miss2;
        Verify(c, &h2, &m2, &miss2);
        std::printf("entries=%d hits=%d misses=%d lookupms=%lu mismatch=%d running=%d queued=%d queuedhit=%d queuedtaken=%d ms=%lu\n",
                    static_cast<int>(es.size()), hits, misses, static_cast<unsigned long>(lookupMs), m2, runningAtCancel,
                    queuedAtCancel, queuedHit, queuedTaken, static_cast<unsigned long>(GetTickCount() - t0));
        return 0;
    }
    if (mode == "restartscan" || mode == "restartimg") {
        if (!prewarm::Start(c.snap)) return 4;
        prewarm::WaitIdle();
        std::vector<prewarm::EntryInfo> es0; prewarm::DebugEntries(&es0);
        int d0, f0, t0_, dr0; size_t b0; Counts(es0, &d0, &f0, &t0_, &dr0, &b0);
        int dMid = -1;
        if (mode == "restartscan") {
            c.snap.scan = (c.snap.scan + 1) % 3;
            prewarm::Restart(c.snap);
            prewarm::WaitIdle();
        } else {
            portrait_files::SetOptions(true, false);          // "Use Turovetsky's HD Portrait Pack" off: no images at all
            prewarm::Restart(c.snap);
            prewarm::WaitIdle();
            std::vector<prewarm::EntryInfo> esm; prewarm::DebugEntries(&esm);
            int fm, tm, drm; size_t bm; Counts(esm, &dMid, &fm, &tm, &drm, &bm);
            portrait_files::SetOptions(true, true);
            prewarm::Restart(c.snap);
            prewarm::WaitIdle();
        }
        int hits, mismatch, missing;
        Verify(c, &hits, &mismatch, &missing);
        std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
        int done, failed, taken, dropped; size_t bytes; Counts(es, &done, &failed, &taken, &dropped, &bytes);
        int doneNewScan = 0, doneEnlOld = 0;
        for (const auto& e : es) {
            if (e.state != 2) continue;
            if (e.scan == c.snap.scan) ++doneNewScan;
            if (e.kind == 1 && e.scan != c.snap.scan) ++doneEnlOld;
        }
        std::printf("done0=%d done=%d donemid=%d dropped=%d failed=%d donenewscan=%d doneenlold=%d hits=%d mismatch=%d missing=%d\n",
                    d0, done, dMid, dropped, failed, doneNewScan, doneEnlOld, hits, mismatch, missing);
        return 0;
    }
    if (mode == "rekey" || mode == "rekeylate") {
        char names[32][24];
        if (portrait_files::ListNames(names, 32) < 1) return 5;
        int b = 0, r = 0; uint32_t h = 0;
        if (!prewarm::DebugSheetSlot(names[0], 2, c.snap.pal, &b, &r, &h)) return 6;
        if (!prewarm::Start(c.snap)) return 4;
        if (mode == "rekey") prewarm::ReportMeasured(names[0], 2, 1 - b, r);   // the "engine" disagrees with the sheet
        prewarm::WaitIdle();
        if (mode == "rekeylate") {            // ... but only says so after the worker finished: it runs again
            prewarm::ReportMeasured(names[0], 2, 1 - b, r);
            if (!prewarm::Running()) { std::printf("slot2=0 oldhit=0 newhit=0 newmiss=0 mismatch=0 notrestarted=1\n"); return 0; }
            prewarm::WaitIdle();
        }
        std::vector<prewarm::EntryInfo> es; prewarm::DebugEntries(&es);
        int oldHit = 0, newHit = 0, newMiss = 0, mismatch = 0, slot2 = 0;
        for (const auto& e : es) {
            std::vector<int> got, want;
            int why = -1;
            if (e.slot != 2 || e.state == 5) continue;   // the dropped (wrong-key) ones are gone
            ++slot2;
            if (c.Lookup(e, b, r, &got, &why)) ++oldHit;                 // the prediction's key: must be gone
            if (c.Lookup(e, 1 - b, r, &got, &why)) {
                ++newHit;
                if (!c.Direct(e, 1 - b, r, &want) || want != got) ++mismatch;
            } else ++newMiss;
        }
        std::printf("slot2=%d oldhit=%d newhit=%d newmiss=%d mismatch=%d\n", slot2, oldHit, newHit, newMiss, mismatch);
        return 0;
    }
    return 2;
}
