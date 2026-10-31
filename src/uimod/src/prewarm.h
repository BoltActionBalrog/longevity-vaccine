// Background pre-bake of the replacement leader portraits (see prewarm.cpp).
//
// The game thread snapshots everything a bake reads (palette, scale, scan mode) at the first faction load and
// starts ONE worker.  The worker decodes every replacement image, predicts each faction's scanline parameters
// from its vanilla sheet (<faction>.pcx, cut exactly as load_faction_art cuts it) and fills a cache of FINISHED
// portrait_law::FromRgb results -- the native bakes and the enlarges at every stripe phase of the current scale.
// The game thread's own law calls look the cache up through ResampleCache::GetFit: a hit is the law's own output
// for the same inputs (bit-identical by construction), a job still running is waited for, anything else is a
// miss and the synchronous path runs as before.  The worker never reads engine memory and never calls the engine.
#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

#include "portrait_law.h"

namespace prewarm {

constexpr int kSlots = 4;
struct SlotDef { int w, h; bool framed; };
extern const SlotDef kSlotDefs[kSlots];       // small council, big council, diplomacy, datalink (= portrait.cpp kSlots)

// Everything a bake reads from the engine, copied on the game thread.
struct Snapshot {
    uint8_t pal[1024];                        // RGBQUAD (b,g,r,x): the laws' table
    int g = 16;                               // g_popup_scale_num; enlarges are pre-baked only above 16
    int scan = 0;                             // portrait_law::kScan*
    int hot[kSlots] = { -1, -1, -1, -1 };     // the stripe phase each slot's draw site used last time (-1 unknown): first
};
// The stripe phase a draw site has used per slot this session (-1 = none yet): the caller persists it for the next
// launch's Snapshot.  True only when something changed since the last call (a lock-free check otherwise).  Game thread.
bool HotPhases(int out[kSlots]);

// The ini form of the phases ("a,b,c,d", -1 = unknown): pure, so the harness can hold them to the format.
inline void ParseHotPhases(const char* v, int out[kSlots])
{
    for (int s = 0; s < kSlots; ++s) out[s] = -1;
    if (!v) return;
    const char* p = v;
    for (int s = 0; s < kSlots && *p; ++s) {
        while (*p == ' ') ++p;
        bool neg = false;
        if (*p == '-') { neg = true; ++p; }
        if (*p < '0' || *p > '9') break;
        int x = 0;
        while (*p >= '0' && *p <= '9') { x = x * 10 + (*p - '0'); if (x > 1000) x = 1000; ++p; }
        if (!neg && x < 64) out[s] = x;
        while (*p == ' ') ++p;
        if (*p != ',') break;
        ++p;
    }
}
inline void FormatHotPhases(const int hot[kSlots], char* out, size_t n)
{
    size_t at = 0;
    out[0] = 0;
    for (int s = 0; s < kSlots && at + 8 < n; ++s) {
        int v = hot[s] < 0 || hot[s] >= 64 ? -1 : hot[s];
        const char* sign = v < 0 ? "-" : "";
        if (v < 0) v = 1;
        const char d0 = static_cast<char>('0' + v / 10), d1 = static_cast<char>('0' + v % 10);
        if (s) out[at++] = ',';
        if (sign[0]) out[at++] = '-';
        if (v >= 10) out[at++] = d0;
        out[at++] = d1;
        out[at] = 0;
    }
}

// Start the worker (game thread, once; later calls are ignored).  False if it could not be started.
bool Start(const Snapshot& s);
bool Started();
int  SnapshotG();

// The hook's MEASURED scanline parameters of a faction file's slot (game thread).  They replace the prediction:
// queued jobs are re-keyed, finished results under a wrong prediction are dropped.
void ReportMeasured(const char* name, int slot, int bright, int ratio);

// A setting changed (user portraits / HD pack / scanlines: another image set or scan mode; or the scale): run the
// worker again under the new snapshot.  Results still valid under it are kept (native bakes of every mode, images
// that did not change), the rest are dropped and rebuilt in the background.  Game thread.
void Restart(const Snapshot& s);

// Lookup reasons (GetFit's `why`), for the debug log.
enum Why { kHit = 0, kNotStarted, kAbsent, kQueuedTaken, kRunningTimeout, kFailed, kDropped };

// The cache side of a portrait_law::ResampleCache: a finished FromRgb result for these inputs.  A job the worker
// is on right now is waited for (bounded); a queued one is taken over by the caller (false: compute it, then
// PutFit).  `fit` is filled on true.  Game thread.
bool GetFit(uint64_t imgId, portrait_law::Rect crop, int tw, int th, const uint8_t* pal, int scan, int bright,
            int ratio, int y0, int rows, std::vector<int>* fit, int* why = nullptr);
// The caller's own synchronous result for these inputs: stored so the worker never repeats it.
void PutFit(uint64_t imgId, portrait_law::Rect crop, int tw, int th, const uint8_t* pal, int scan, int bright,
            int ratio, int y0, int rows, const std::vector<int>& fit);

// One pending log line from the worker (progress, the end-of-run summary), if any.  Game thread.
bool TakeLog(char* out, size_t n);

// ---- test / diagnostics (the harness; the DLL calls none of these) ----
void Cancel();
bool Finished();
bool Running();
void WaitIdle();
void TestFailEvery(int n);                    // every n-th job fails (0 = never)
void TestThrowEvery(int n);                   // every n-th job throws bad_alloc (0 = never)
void TestFaultEvery(int n);                   // every n-th job raises an access violation inside the law (0 = never)
void TestDieLocked();                         // the worker exits inside its next locked region: the lock is orphaned
void TestFaultOutsideJob();                   // the worker raises an access violation outside any job guard (thunk level)
void TestDieInJob(int n);                     // the n-th job: the worker exits mid-job, holding nothing (a death during a wait)
bool Dead();                                  // the game-thread entries have given the worker up (synchronous path)
struct EntryInfo {
    uint64_t imgId, palHash; portrait_law::Rect crop; int tw, th, scan, bright, ratio, y0, rows, slot, kind, state;
    size_t bytes;
};
void DebugEntries(std::vector<EntryInfo>* out);
// The sheet reader on its own: (bright, ratio) of slot `slot` of <game>\<name>.pcx cut the engine's way, and the
// FNV-1a 32 hash of the cut (the Phase-0 probe's measure of the engine's sprite).  False if unreadable / trimmed.
bool DebugSheetSlot(const char* name, int slot, const uint8_t* pal, int* bright, int* ratio, uint32_t* hash);

} // namespace prewarm
