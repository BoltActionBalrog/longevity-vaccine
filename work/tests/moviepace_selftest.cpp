// Drives src\uimod\src\moviepace.h (the movie player's pure pacing logic) for test_moviepace.py.
// Built with cpp_harness; no windows.h, no libav. One command per run, results on stdout.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "../../src/uimod/src/moviepace.h"

using namespace moviepace;

static uintptr_t Hex(const char* s) { return static_cast<uintptr_t>(strtoull(s, nullptr, 16)); }
static double Num(const char* s) { return atof(s); }

// affinity <event>...  widen:<before>:<after> poll:<cur> back:<mask> restore:<cur>
static int Affinity(int argc, char** argv)
{
    AffinityState s;
    for (int i = 0; i < argc; ++i) {
        char ev[32]; unsigned long a = 0, b = 0;
        if (sscanf(argv[i], "%31[^:]:%lx:%lx", ev, &a, &b) < 2) return 2;
        if (!strcmp(ev, "widen")) { OnWidened(s, a, b); printf("widened pinned=%lx wide=%lx\n", (unsigned long)s.pinned, (unsigned long)s.wide); }
        else if (!strcmp(ev, "poll")) printf("poll=%d pinned=%lx repins=%u\n", OnPoll(s, a) ? 1 : 0, (unsigned long)s.pinned, s.repins);
        else if (!strcmp(ev, "back")) { OnRewidenResult(s, a); printf("gaveup=%d\n", s.gaveUp ? 1 : 0); }
        else if (!strcmp(ev, "restore")) printf("restore=%d to=%lx\n", ShouldRestore(s, a) ? 1 : 0, (unsigned long)s.pinned);
        else if (!strcmp(ev, "took")) printf("took=%d\n", RestoreTook(s, a) ? 1 : 0);
        else return 2;
    }
    return 0;
}

// audio <event>...  q:<dur> start:<now> sub:<now>:<dur> lead:<now>
static int Audio(int argc, char** argv)
{
    AudioTimeline t;
    for (int i = 0; i < argc; ++i) {
        char ev[32]; double a = 0, b = 0;
        if (sscanf(argv[i], "%31[^:]:%lf:%lf", ev, &a, &b) < 2) return 2;
        if (!strcmp(ev, "q")) t.Queue(a);
        else if (!strcmp(ev, "start")) t.Start(a);
        else if (!strcmp(ev, "sub")) t.OnSubmit(a, b);
        else if (!strcmp(ev, "lead")) printf("lead=%.1f shift=%.1f under=%u\n", t.LeadMs(a), t.ShiftMs(), t.Underruns());
        else if (!strcmp(ev, "trim")) printf("drop=%.1f\n", t.TrimPending(a));
        else if (!strcmp(ev, "refused")) t.OnRefused();
        else return 2;
    }
    return 0;
}

// sim <frames> <frameMs> <decodeMs> <drawMs> [discardable] [stallAtFrame stallMs]
//
// The frame loop on a virtual clock, in movie.cpp's order: decode, verdict, then draw + hold + present or
// skip. Prints what came of it, so the rules are checked as behaviour, not as branches.
static int Sim(int argc, char** argv)
{
    if (argc < 4) return 2;
    const int frames = atoi(argv[0]);
    const double frameMs = Num(argv[1]), decodeMs = Num(argv[2]), drawMs = Num(argv[3]);
    const bool discardable = argc > 4 && atoi(argv[4]) != 0;
    const int stallAt = argc > 5 ? atoi(argv[5]) : -1;
    const double stallMs = argc > 6 ? Num(argv[6]) : 0;

    Pacer p(frameMs);
    p.AllowDiscard(discardable);
    double now = 0, t0 = 0, lastShown = 0, worstGap = 0, finalLate = 0;
    bool started = false, lastDrawn = false;
    int run = 0, worstRun = 0, discardAtEnd = 0;
    for (int i = 0; i < frames; ++i) {
        p.OnPacketSent();
        now += decodeMs;
        if (i == stallAt) now += stallMs;
        const double target = t0 + i * frameMs;
        if (started && p.OnFrame(now, target) == kSkip) {
            lastDrawn = false;
            finalLate = now - target;
            if (++run > worstRun) worstRun = run;
            continue;
        }
        run = 0;
        now += drawMs;
        if (started && now < target) now = target;
        if (!started) { started = true; t0 = now; }
        if (now - lastShown > worstGap && i) worstGap = now - lastShown;
        lastShown = now;
        p.OnShown(now);
        lastDrawn = true;
        finalLate = now - (t0 + i * frameMs);
    }
    discardAtEnd = p.DiscardNonRef(false) ? 1 : 0;
    printf("shown=%u skipped=%u entries=%u worstrun=%d worstgap=%.0f finallate=%.0f discard_end=%d last_drawn=%d\n",
           p.Shown(), p.Skipped(), p.DiscardEntries(), worstRun, worstGap, finalLate, discardAtEnd, lastDrawn ? 1 : 0);
    return 0;
}

// stuck <packets>: a stream of nothing but non-reference pictures -- discarding is entered, then no frame ever comes.
static int Stuck(int argc, char** argv)
{
    if (argc < 1) return 2;
    Pacer p(33.0);
    p.AllowDiscard(true);
    p.OnShown(0);
    p.OnFrame(500, 100);
    printf("before=%d\n", p.DiscardNonRef(false) ? 1 : 0);
    for (int i = 0; i < atoi(argv[0]); ++i) p.OnPacketSent();
    printf("after=%d\n", p.DiscardNonRef(false) ? 1 : 0);
    p.OnFrame(1500, 1000);
    printf("again=%d\n", p.DiscardNonRef(false) ? 1 : 0);
    return 0;
}

int main(int argc, char** argv)
{
    if (argc < 2) return 2;
    const char* c = argv[1];
    if (!strcmp(c, "threads") && argc == 3) { printf("%d\n", DecoderThreads(atoi(argv[2]))); return 0; }
    if (!strcmp(c, "cpus") && argc == 3) { printf("%d\n", CoresFromCpus(atoi(argv[2]))); return 0; }
    if (!strcmp(c, "cores") && argc >= 3) {
        std::vector<uintptr_t> m;
        for (int i = 3; i < argc; ++i) m.push_back(Hex(argv[i]));
        printf("%d\n", CountCores(m.data(), static_cast<int>(m.size()), Hex(argv[2])));
        return 0;
    }
    if (!strcmp(c, "pinned") && argc == 4) { printf("%d\n", IsPinned(Hex(argv[2]), Hex(argv[3])) ? 1 : 0); return 0; }
    if (!strcmp(c, "took") && argc == 4) { printf("%d\n", WidenTook(Hex(argv[2]), Hex(argv[3])) ? 1 : 0); return 0; }
    if (!strcmp(c, "wants") && argc == 4) { printf("%d\n", WantsMoreCores(atoi(argv[2]), atoi(argv[3])) ? 1 : 0); return 0; }
    if (!strcmp(c, "nearend") && argc == 5) { printf("%d\n", NearEnd(atoi(argv[2]) != 0, Num(argv[3]), Num(argv[4])) ? 1 : 0); return 0; }
    if (!strcmp(c, "demux") && argc == 6) {
        printf("%d\n", WantDemux(atoi(argv[2]) != 0, Num(argv[3]), static_cast<size_t>(atoi(argv[4])), static_cast<size_t>(atoi(argv[5]))) ? 1 : 0);
        return 0;
    }
    if (!strcmp(c, "drop") && argc == 3) { printf("%d\n", ShouldDropToKeyframe(Num(argv[2])) ? 1 : 0); return 0; }
    if (!strcmp(c, "affinity")) return Affinity(argc - 2, argv + 2);
    if (!strcmp(c, "audio")) return Audio(argc - 2, argv + 2);
    if (!strcmp(c, "sim")) return Sim(argc - 2, argv + 2);
    if (!strcmp(c, "stuck")) return Stuck(argc - 2, argv + 2);
    return 2;
}
