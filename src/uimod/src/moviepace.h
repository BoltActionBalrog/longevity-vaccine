// uimod movie player -- the pure pacing logic, header-only so work\tests\moviepace_selftest.cpp can
// compile it without windows.h or libav: how many decoder threads, whether and how the process
// affinity is widened and given back, whether a late frame is drawn, when the decoder may discard,
// and where the sound stands. movie.cpp is the Win32 + libav shell around this file.
//
// Rules of this file: no heap, no exceptions, no Windows headers. Times are milliseconds on one
// monotonic clock; masks are this process's view (32 bits under WOW64).
#pragma once

#include <cstddef>
#include <cstdint>

namespace moviepace {

// ---- decoder threads ----------------------------------------------------------------------------

constexpr int kMaxDecoderThreads = 4;    // the maintainer's cap: a movie does not get every CPU

inline int BitCount(uintptr_t m) { int n = 0; for (; m; m &= m - 1) ++n; return n; }

// The physical cores among `n` core masks (RelationProcessorCore records) that the process mask `proc`
// reaches -- DISTINCT masks: a 32-bit process on a machine with more than 32 CPUs sees each core's mask
// folded onto the low 32 bits (WOW64), so two cores can report one mask. Never more than the CPUs in
// `proc`, the safety net for the same folding. Same rule as prewarm.cpp's CountCores.
inline int CountCores(const uintptr_t* masks, int n, uintptr_t proc)
{
    int distinct = 0;
    for (int i = 0; i < n; ++i) {
        if (!(masks[i] & proc)) continue;
        bool dup = false;
        for (int k = 0; k < i && !dup; ++k) dup = masks[k] == masks[i];
        if (!dup) ++distinct;
    }
    const int cpus = BitCount(proc);
    return distinct < cpus ? distinct : cpus;
}

// Unknown topology: `cpus` hardware threads, assumed two per core (one CPU is one core).
inline int CoresFromCpus(int cpus) { return cpus <= 1 ? 1 : cpus / 2; }

// Physical cores minus one (the player's own thread scales and presents), between 1 and the cap.
inline int DecoderThreads(int cores)
{
    const int t = cores - 1;
    return t < 1 ? 1 : t > kMaxDecoderThreads ? kMaxDecoderThreads : t;
}

// ---- process affinity ---------------------------------------------------------------------------

// The originals (at most 592x288 at 15 fps) play on the one CPU exactly as before; only a stream bigger
// than any of them asks for more.
inline bool WantsMoreCores(int width, int height) { return width > 640 || height > 480; }

// Pinned = on exactly one CPU of a machine with more. A wider partial mask is somebody's deliberate
// setting (Task Manager, a launcher) and is left alone; DDrawCompat's pin is always one CPU.
inline bool IsPinned(uintptr_t proc, uintptr_t sys)
{
    return proc && (proc & (proc - 1)) == 0 && (proc & sys) == proc && BitCount(sys) > 1;
}

// A read-back only counts as widened when it has MORE CPUs than before: DDrawCompat's rotation can land
// between the set and the read, and then the read shows its next one-CPU mask.
inline bool WidenTook(uintptr_t before, uintptr_t after) { return BitCount(after) > BitCount(before); }

constexpr int kRewidenFailLimit = 3;     // read-backs in a row that disagree before the player stops fighting

struct AffinityState {
    bool      active = false;            // we changed the mask and owe a restore
    bool      gaveUp = false;
    uintptr_t pinned = 0;                // the newest one-CPU mask seen: what the restore puts back
    uintptr_t wide   = 0;                // the mask we set, as read back
    int       failStreak = 0;
    unsigned  repins = 0;
};

inline void OnWidened(AffinityState& s, uintptr_t before, uintptr_t after)
{
    s = AffinityState();
    s.active = true;
    s.pinned = before;
    s.wide   = after;
}

// Polled during playback. true = somebody re-pinned the process: widen again.
inline bool OnPoll(AffinityState& s, uintptr_t cur)
{
    if (!s.active || s.gaveUp || !cur || cur == s.wide) return false;
    s.pinned = cur;
    ++s.repins;
    return true;
}

inline void OnRewidenResult(AffinityState& s, uintptr_t readBack)
{
    if (readBack == s.wide) { s.failStreak = 0; return; }
    if (++s.failStreak >= kRewidenFailLimit) s.gaveUp = true;
}

// Give the pin back only if the mask is still OURS. Anything else means DDrawCompat already re-pinned it
// (a newer mask than the one we saved), and writing the older one over it would be wrong.
inline bool ShouldRestore(const AffinityState& s, uintptr_t cur) { return s.active && s.pinned && cur == s.wide; }

// Took = no longer our mask (a rotation landing in between counts: the process is pinned again either way).
inline bool RestoreTook(const AffinityState& s, uintptr_t readBack) { return readBack != s.wide; }

// ---- when to draw ---------------------------------------------------------------------------------

constexpr double kMaxPictureGapMs = 250.0;   // a picture at least this often, however far behind
constexpr int    kDiscardFramesLate = 3;     // discard from this many frames behind ...
constexpr int    kDiscardStuckPackets = 32;  // ... and give it up if this many packets bring no picture

enum Verdict { kShow, kSkip };

class Pacer {
public:
    explicit Pacer(double frameMs) : frameMs_(frameMs) {}

    // H.264 with timestamps and a known length only: a discarded frame must not move the schedule, and
    // the end must be recognisable so the true last frame is decoded.
    void AllowDiscard(bool allow) { canDiscard_ = allow; if (!allow) discard_ = false; }

    // A decoded frame due at `targetMs`. The first always shows. Late by less than a frame still shows
    // (the next one is not due yet); from a whole frame on it is skipped unless the picture has been
    // still for kMaxPictureGapMs.
    Verdict OnFrame(double nowMs, double targetMs)
    {
        const double late = nowMs - targetMs;
        stuck_ = 0;
        lateMs_ = late;
        if (late > maxLateMs_) maxLateMs_ = late;
        if (canDiscard_ && !blocked_) {
            if (!discard_ && late >= kDiscardFramesLate * frameMs_) { discard_ = true; ++discardEntries_; }
            else if (discard_ && late < frameMs_) discard_ = false;
        }
        if (!shownAny_ || late < frameMs_ || nowMs - lastShownMs_ >= kMaxPictureGapMs) return kShow;
        ++skipped_;
        return kSkip;
    }

    void OnShown(double nowMs) { shownAny_ = true; lastShownMs_ = nowMs; ++shown_; }

    // Before each packet goes to the decoder. A stream of nothing but non-reference pictures would give
    // no frames, so no lateness to end the discard with: then it is switched off for the rest of the movie.
    void OnPacketSent()
    {
        if (discard_ && ++stuck_ > kDiscardStuckPackets) { discard_ = false; blocked_ = true; }
    }

    bool DiscardNonRef(bool nearEnd) const { return discard_ && !nearEnd; }

    unsigned Shown() const { return shown_; }
    unsigned Skipped() const { return skipped_; }
    unsigned DiscardEntries() const { return discardEntries_; }
    double   MaxLateMs() const { return maxLateMs_; }
    double   LateMs() const { return lateMs_; }      // of the newest frame out of the decoder

private:
    double   frameMs_;
    double   lateMs_ = 0;
    bool     canDiscard_ = false;
    bool     discard_ = false;
    bool     blocked_ = false;
    bool     shownAny_ = false;
    double   lastShownMs_ = 0;
    double   maxLateMs_ = 0;
    int      stuck_ = 0;
    unsigned shown_ = 0, skipped_ = 0, discardEntries_ = 0;
};

// Within this much of the end nothing is discarded: the frame the caption is drawn over is one of them.
constexpr double kEndGuardMs = 2000.0;
inline bool NearEnd(bool demuxEof, double lengthMs, double packetMs)
{
    return demuxEof || lengthMs <= 0 || packetMs + kEndGuardMs >= lengthMs;
}

// ---- the sound ------------------------------------------------------------------------------------

// Sound leads the picture by this much so a slow frame or a blocked message pump cannot empty the queue.
// Each read goes to the device as one buffer, far under XAudio2's 64 queued buffers.
constexpr double kAudioLeadMs  = 500.0;
constexpr double kPreRollKeepMs = 1000.0;   // sound kept while no picture has come yet
// Queued video: room for a whole GOP of the 15 fps pack (250 frames between keyframes), bounded by size.
constexpr size_t kMaxQueuedPackets = 400;
constexpr size_t kMaxQueuedBytes   = 24u << 20;
constexpr size_t kAudioEndedPackets = 64;   // this many video packets with no sound: the sound track has ended
constexpr double kDropLateMs   = 1000.0;

// Read another packet from the file? Always with no video to decode; beyond that only to keep the sound ahead.
inline bool WantDemux(bool audioLive, double leadMs, size_t queued, size_t bytes)
{
    if (queued == 0) return true;
    return audioLive && leadMs < kAudioLeadMs && queued < kMaxQueuedPackets && bytes < kMaxQueuedBytes;
}

// The last resort: the picture is a second behind the sound with nothing being drawn, so decoding itself
// cannot keep up. Jump to the newest keyframe in the queue. Only packets BEFORE that keyframe go, so the end
// of the file is always decoded and the caption still lands on the true last frame.
inline bool ShouldDropToKeyframe(double lateMs) { return lateMs >= kDropLateMs; }

// Where the queued sound ends on the clock. Sound is the master: when the queue ran dry the sound restarts
// later than the picture's schedule, so the schedule moves by exactly the gap (ShiftMs) and the two stay
// together. Until the first picture nothing plays; the sound queued so far starts with it.
class AudioTimeline {
public:
    void Queue(double durMs) { pendingMs_ += durMs; }
    // Sound read before the first picture is kept only this far back: a file whose first picture never comes
    // (or comes late) must not pile its whole track up in memory, nor start its sound seconds early.
    // Returns how much to drop from the front.
    double TrimPending(double keepMs)
    {
        if (pendingMs_ <= keepMs) return 0;
        const double drop = pendingMs_ - keepMs;
        pendingMs_ = keepMs;
        return drop;
    }
    void Start(double nowMs) { running_ = true; endMs_ = nowMs + pendingMs_; pendingMs_ = 0; }
    bool Running() const { return running_; }

    void OnSubmit(double nowMs, double durMs)
    {
        if (nowMs > endMs_) {
            if (master_) { shiftMs_ += nowMs - endMs_; ++underruns_; }
            endMs_ = nowMs;
        }
        endMs_ += durMs;
    }

    // The device refused sound (it went away, or a queue limit): what plays from now on no longer tells where
    // the movie is, so the picture keeps the schedule it has and stops following the sound.
    void OnRefused() { master_ = false; }

    double LeadMs(double nowMs) const { return running_ ? endMs_ - nowMs : pendingMs_; }
    double ShiftMs() const { return shiftMs_; }
    unsigned Underruns() const { return underruns_; }

private:
    bool     running_ = false, master_ = true;
    double   pendingMs_ = 0, endMs_ = 0, shiftMs_ = 0;
    unsigned underruns_ = 0;
};

} // namespace moviepace
