// uimod display-topology safety: the decisions under vidmode.cpp's window handling, kept free of the Windows API so
// a self-test can drive them through recorded message sequences (work\tests\test_vidsafety.py).
//
// Why it exists (2026-10-24): a monitor that changed its identity mid-game dropped off the bus during driver resets.
// Windows moved the native-4K Fullscreen window onto the remaining monitor, and the old code read that system
// reposition as "PRACX left its windowed state", converted the game to the scaled popup there and made it
// topmost, put a topmost black backdrop over that monitor and clipped the pointer to the small window. Nothing
// undid it, and the first scaled flip created the D3D device on the game thread in the middle of the reset. The
// user had to power the PC off. The rules here:
//
//   * Converge (re-apply the scaled Fullscreen) ONLY when PRACX's own SetWindowed(false) ran: m_fWindowed seen
//     going 1 -> 0 and not by our own call. PRACX writes m_fWindowed before its SetWindowLong / SetWindowPos
//     (prax.dll 0x1000A094), so the window messages those send already see the 0. A system reposition never
//     touches m_fWindowed and never converges.
//   * A topology event releases at once: pointer clip off, backdrop hidden, nothing topmost. WM_DISPLAYCHANGE and
//     the DPI messages always are one; a device notification (DBT_DEVNODES_CHANGED: any USB / Bluetooth / audio
//     device) or a work-area broadcast only when the monitor set (device paths, names, rects) changed -- checked
//     again on the timer for kRecheckMs after one, since the list can change after the notice arrives -- and a
//     change of the set seen on any placement is one too. PRACX's own display-mode switch ([UIMod]
//     FullscreenModeSwitch=1, a developer setting) is not one.
//   * After the last event the window is left alone for kQuietMs (a latch that EXPIRES, polled by a timer: never a
//     dequeue-and-repost loop). Then the state is restored on the monitor the user had the game on -- native
//     Fullscreen where it is the backbuffer's size, else the scaled popup -- only while the game is the foreground
//     window (otherwise at its next activation). The game is NEVER moved to another monitor on its own: while its
//     monitor is gone nothing is held (no topmost, clip or backdrop) until it returns, or until the user acts --
//     picks a mode, drags the window, or comes back to the game after leaving it -- which makes the monitor the
//     game is on its monitor.
//   * Topmost and the clip are held only while the game is the foreground window, not minimised, not in a quiet
//     period, not waiting for a restore or for its monitor, and not after the escape hotkey (until the game is
//     activated again).
//   * The backdrop follows the window's monitor; one thread owns it, decided once.
//   * The watchdog thread (vidwatch.cpp) releases on a display event and on the escape hotkey, never on a stall: it
//     only measures and logs the game thread's stalls (a long AI turn is one). It cannot drop a hung window out of
//     the topmost band: SWP_ASYNCWINDOWPOS and ShowWindowAsync are queued to the hung thread itself. Against a game
//     thread that truly hangs the user has the escape hotkey (clip and backdrop released at once) and Ctrl+Alt+Del
//     (Task Manager -> End task).
//   * The GPU present (gpuscale.cpp) creates no device, resizes nothing and presents nothing within kGpuQuietMs of
//     a counted event, and after a device loss makes a new one after a growing back-off (2 s, 10 s, then 60 s).
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstring>

namespace vidsafety {

// kQuietMs: an OLED / high-refresh DisplayPort monitor re-trains its link and re-syncs its panel after a mode or
// identity change, and Windows delivers the resulting topology notices over a couple of seconds, not at once. The
// 1.5 s first used settled inside such a burst (audit 2026-10-25, scenarios C / D: the game was re-placed while the
// monitor was still coming back). 3 s outlasts it. Waiting is free: until the restore the game only holds nothing,
// which is the safe state.
constexpr uint32_t kQuietMs = 3000;
constexpr uint32_t kRecheckMs = 3000;          // after a device / work-area notice: re-compare the monitor set this long
constexpr uint32_t kTimerMs = 100;             // the quiet / restore poll while something is pending
constexpr uint32_t kConvergeLatchMs = 500;     // a posted converge that never arrived (a nested pump ate it) expires
constexpr uint32_t kGpuQuietMs = 2000;         // no D3D device creation / resize / present this soon after an event
constexpr uint32_t kGpuStableMs = 60000;       // a device that ran this long resets the loss back-off
constexpr uint32_t kGpuCreateWarnMs = 10000;   // a device creation still running after this is logged
constexpr uint32_t kWatchPeriodMs = 500;       // watchdog probe period
constexpr uint32_t kWatchProbeMs = 500;        // SendMessageTimeout on the probe
constexpr uint32_t kWatchStallLogMs = 1000;    // a shorter stall is only logged, with its length
constexpr int      kEventsLoggedPerBurst = 8;  // display events logged one by one per quiet period; the rest counted
constexpr uint32_t kIgnoredLogMs = 60000;      // "device notice, monitors unchanged" logged at most once per minute

// Message numbers (vidmode.cpp static_asserts them against <windows.h>).
constexpr unsigned kWM_SETTINGCHANGE = 0x001A, kWM_DISPLAYCHANGE = 0x007E, kWM_DEVICECHANGE = 0x0219,
                   kWM_DPICHANGED = 0x02E0;
constexpr unsigned kDBT_DEVNODES_CHANGED = 0x0007, kSPI_SETWORKAREA = 0x002F, kSPI_SETLOGICALDPIOVERRIDE = 0x009F;
constexpr unsigned kEventFromWatchdog = 0;          // a display message only the watchdog thread's window received
constexpr unsigned kEventMonitorSet = 0xFFFF;       // the monitor set changed (seen on a placement / the timer)

// A message worth looking at (the controller still decides whether it counts).
inline bool IsDisplayEvent(unsigned msg, uintptr_t wp)
{
    switch (msg) {
    case kWM_DISPLAYCHANGE:
    case kWM_DPICHANGED:    return true;
    case kWM_DEVICECHANGE:  return wp == kDBT_DEVNODES_CHANGED;
    case kWM_SETTINGCHANGE: return wp == kSPI_SETWORKAREA || wp == kSPI_SETLOGICALDPIOVERRIDE;
    default:                return false;
    }
}

// A notice that is a topology event only when the monitor set changed (it also fires for every USB / Bluetooth /
// audio device and for taskbar / app-bar work-area changes).
inline bool NeedsMonitorCheck(unsigned msg, uintptr_t wp)
{
    return (msg == kWM_DEVICECHANGE && wp == kDBT_DEVNODES_CHANGED) || (msg == kWM_SETTINGCHANGE && wp == kSPI_SETWORKAREA);
}

inline const char* EventName(unsigned msg, uintptr_t wp = 0)
{
    switch (msg) {
    case kWM_DISPLAYCHANGE: return "WM_DISPLAYCHANGE";
    case kWM_DPICHANGED:    return "WM_DPICHANGED";
    case kWM_DEVICECHANGE:  return "WM_DEVICECHANGE(DBT_DEVNODES_CHANGED)";
    case kWM_SETTINGCHANGE: return wp == kSPI_SETWORKAREA ? "WM_SETTINGCHANGE(SPI_SETWORKAREA)" : "WM_SETTINGCHANGE(SPI_SETLOGICALDPIOVERRIDE)";
    case kEventFromWatchdog: return "a display message only the watchdog thread received";
    case kEventMonitorSet:  return "the monitor set changed";
    default:                return "?";
    }
}

// GetTickCount wraps every 49.7 days: compare by difference only.
inline uint32_t Since(uint32_t now, uint32_t then) { return now - then; }

struct Rect {
    int l = 0, t = 0, r = 0, b = 0;
    int W() const { return r - l; }
    int H() const { return b - t; }
};
inline bool operator==(const Rect& a, const Rect& b) { return a.l == b.l && a.t == b.t && a.r == b.r && a.b == b.b; }
inline bool operator!=(const Rect& a, const Rect& b) { return !(a == b); }

// The largest sw:sh rect centred in `mon` (uniform scale only).
inline Rect FitRect(const Rect& mon, int sw, int sh)
{
    const int mw = mon.W(), mh = mon.H();
    int w = mw, h = mh;
    if (sw > 0 && sh > 0) {
        if (static_cast<long long>(mw) * sh <= static_cast<long long>(mh) * sw)
            h = static_cast<int>(static_cast<long long>(mw) * sh / sw);
        else
            w = static_cast<int>(static_cast<long long>(mh) * sw / sh);
    }
    Rect r;
    r.l = mon.l + (mw - w) / 2;
    r.t = mon.t + (mh - h) / 2;
    r.r = r.l + w;
    r.b = r.t + h;
    return r;
}

// Fullscreen has to be the scaled popup on a monitor that is not the backbuffer's size (PRACX would switch the
// display mode there), unless that switch is allowed ([UIMod] FullscreenModeSwitch=1).
inline bool NeedsScaled(const Rect& mon, int sw, int sh, bool switchAllowed)
{
    if (switchAllowed || sw <= 0 || sh <= 0) return false;
    return mon.W() != sw || mon.H() != sh;
}

constexpr int kMaxMonitors = 16;

struct Monitor {
    // Desktop coordinates as this (system-DPI-aware) process sees them: after Windows changes a monitor's scaling
    // mid-session the rect is the DPI-virtualised one (a 4K monitor taken from 150% to 100% reads 5760x3240), so
    // the game no longer counts it as native and Fullscreen there is the scaled popup until a restart.
    Rect rc;
    bool primary = false;
    char name[32] = {};       // GDI device name (\\.\DISPLAYn): an adapter output, reused across reconnects -- never an identity
    char path[160] = {};      // the monitor's device interface path (= CCD monitorDevicePath; "" = unknown)
};

// The topology the game is placed in: rect, primary flag and GDI name. The device path is left out on purpose -- it is
// read only when the game's monitor has to be recognised (noting home, a restore: vidmode.cpp MakeWorld), never on
// the hot paths, and a transient empty read of it (EnumDisplayDevices failing once) must not look like a change
// (re-audit N-C). An identity change at the same rect and name changes nothing the game is placed by.
inline bool SameMonitor(const Monitor& a, const Monitor& b)
{
    return a.rc == b.rc && a.primary == b.primary && !strcmp(a.name, b.name);
}

// Same set (order-insensitive).
inline bool SameMonitorSet(const Monitor* a, int na, const Monitor* b, int nb)
{
    if (na != nb) return false;
    for (int i = 0; i < na; ++i) {
        bool found = false;
        for (int j = 0; j < nb && !found; ++j) found = SameMonitor(a[i], b[j]);
        if (!found) return false;
    }
    return true;
}

// Where the user's monitor is now: by device path (survives a re-scaling and a renumbering), else by rect and primary
// flag (survives an identity change that re-enumerates the same panel), else by rect alone. Never by GDI name: after
// a reconnect \\.\DISPLAY1 can be the other monitor (audit scenario F).
inline int FindMonitor(const Monitor& want, const Monitor* mons, int n)
{
    if (want.path[0])
        for (int i = 0; i < n; ++i)
            if (!strcmp(mons[i].path, want.path)) return i;
    for (int i = 0; i < n; ++i)
        if (mons[i].rc == want.rc && mons[i].primary == want.primary) return i;
    for (int i = 0; i < n; ++i)
        if (mons[i].rc == want.rc) return i;
    return -1;
}

enum Mode { kFullscreen = 0, kBorderless = 1, kWindowed = 2 };   // = vidmode.h VidMode

// One call's view of the world, filled by the caller (vidmode.cpp from Win32; the self-test from its model).
struct World {
    uint32_t now = 0;
    bool booted = false, closing = false;
    bool fWindowed = false;       // PRACX m_fWindowed
    int  mode = kFullscreen;      // the detected mode
    bool applying = false;        // a popup placement is in progress (the backdrop waits for it)
    bool foreground = false, iconic = false;
    bool movie = false;           // our cinematic player owns the window
    bool switchAllowed = false, clipWanted = true;
    bool ownSwitch = false;       // PRACX's own ChangeDisplaySettings is running / just ran (FullscreenModeSwitch=1)
    int  sw = 0, sh = 0;          // backbuffer
    Rect win;
    Monitor mons[kMaxMonitors];
    int  nMons = 0;
    int  cur = -1;                // the monitor nearest the window
    uint32_t escapeGen = 0;       // bumped by the escape hotkey (watchdog thread)
};

// What the controller asks of the world. Every call must be idempotent: the controller re-states the whole wanted
// state on each sync and the implementation does nothing when the window already is that way.
struct Effects {
    virtual void Clip(bool on) = 0;                             // on = ClipCursor(window rect), off = release ours
    virtual void Topmost(bool on) = 0;                          // the game window's band
    virtual void Backdrop(bool show, const Rect& mon, bool topmost) = 0;
    virtual void PostConverge() = 0;
    virtual void Timer(bool on) = 0;                            // OnTimer every kTimerMs while on
    virtual void Native(const Monitor& m) = 0;                  // Fullscreen = PRACX's own, on m
    virtual void Scaled(const Monitor& m) = 0;                  // Fullscreen = the scaled popup, on m
    virtual void Refit(const Monitor& m, bool full) = 0;        // the running popup re-placed on m
    virtual void EventCounted() = 0;                            // a topology event counted (the GPU's quiet starts)
    virtual void Log(const char* line) = 0;                     // one line, no newline
};

enum RestoreKind { kRestoreNone = 0, kRestoreNative, kRestoreScaled, kRestoreRefit, kRestoreUndecided, kRestoreAwaitHome };

struct Restore {
    RestoreKind kind = kRestoreNone;
    int mon = -1;
    enum Target { kHome = 0, kAdopted, kAdoptNow } target = kHome;   // the user's monitor / a provisional one / adopt `mon` now
};

inline const char* RestoreName(RestoreKind k)
{
    return k == kRestoreNative ? "native Fullscreen" : k == kRestoreScaled ? "scaled Fullscreen"
         : k == kRestoreRefit ? "popup re-fit" : k == kRestoreUndecided ? "undecided"
         : k == kRestoreAwaitHome ? "wait for the game's monitor" : "nothing to change";
}

// A latch that expires on its own: what a self-posted message is throttled by.
struct TimeLatch {
    bool on = false;
    uint32_t at = 0;
    void Set(uint32_t now) { on = true; at = now; }
    void Clear() { on = false; }
    bool Live(uint32_t now, uint32_t ms) const { return on && Since(now, at) < ms; }
};

class Controller {
public:
    // ---- inputs (vidmode.cpp SubclassProc) --------------------------------------------------------------------

    // m_fWindowed as every message sees it. `ours` = our own SetWindowed is running (its transitions are no signal).
    void Observe(bool fWindowed, bool ours)
    {
        const int now = fWindowed ? 1 : 0;
        if (seen_ == 1 && now == 0 && !ours) pracxLeft_ = true;
        if (now == 1) pracxLeft_ = false;
        seen_ = now;
    }

    // WM_WINDOWPOSCHANGED / WM_STYLECHANGED, after PRACX handled it.
    void OnPlacement(const World& w, Effects& fx)
    {
        if (CheckMonitorSet(w, fx)) return;   // the set changed under the window (a move can precede the notice)
        Sync(w, fx);
        MaybeConverge(w, fx);
    }

    // Our posted converge arrived: true = re-apply Fullscreen (VidModeSet) now.
    bool OnConverge(const World& w, Effects& fx)
    {
        converge_.Clear();
        if (!pracxLeft_ || !w.booted || w.closing || w.fWindowed || !CurNeedsScaled(w)) {
            pracxLeft_ = false;
            Say(fx, "converge: dropped (nothing of PRACX's to undo any more)");
            return false;
        }
        if (quiet_.on || restoreOwed_ || awaitHome_) { Say(fx, "converge: deferred to the display restore"); return false; }
        pracxLeft_ = false;
        Say(fx, "converge: -> scaled Fullscreen");
        return true;
    }

    // A display message, BEFORE the monitor list is read (vidmode.cpp OnDisplayEvent; OnDisplayEvent follows with the
    // world). One that always counts -- not a device / work-area notice, not PRACX's own mode switch -- releases here
    // at once. The quiet period starts FIRST: dropping the topmost band is a SetWindowPos, which sends the window a
    // WM_WINDOWPOSCHANGED, and the placement sync that runs inside it must already see nothing holdable -- else it
    // re-asserts topmost, the clip and the backdrop between the release's own steps (a backdrop flash and three more
    // SetWindowPos, audit 2026-10-25 R1). The timer polls the latch, so it expires even if no event follows.
    // True = released.
    bool PreRelease(uint32_t now, bool ownSwitch, unsigned msg, uintptr_t wp, Effects& fx)
    {
        if (ownSwitch || NeedsMonitorCheck(msg, wp)) return false;
        if (!quiet_.on) burstOpen_ = true;    // the event that follows is still the burst's first (its log, its counts)
        quiet_.Set(now);
        fx.Clip(false);
        fx.Backdrop(false, Rect(), false);
        fx.Topmost(false);
        fx.Timer(true);
        return true;
    }

    // A display message (IsDisplayEvent). True = it counted as a topology event (released, quiet started).
    bool OnDisplayEvent(const World& w, Effects& fx, unsigned msg, uintptr_t wp, intptr_t lp)
    {
        if (w.ownSwitch) {                        // PRACX's own mode switch: the new layout is the expected one
            Accept(w);
            Rate(fx, "display: PRACX's own display-mode switch -> not a topology event", w.now);
            return false;
        }
        if (NeedsMonitorCheck(msg, wp) && knownSet_ && SameMonitorSet(w.mons, w.nMons, known_, nKnown_)) {
            recheck_.Set(w.now);                  // the list may change after the notice: compare again for a while
            fx.Timer(true);
            char line[160];
            _snprintf_s(line, sizeof line, _TRUNCATE, "display: %s, monitors unchanged -> ignored", EventName(msg, wp));
            Rate(fx, line, w.now);
            return false;
        }
        Event(w, fx, msg, wp, lp);
        return true;
    }

    void OnTimer(const World& w, Effects& fx)
    {
        if (CheckMonitorSet(w, fx)) return;
        if (recheck_.on && !recheck_.Live(w.now, kRecheckMs)) recheck_.Clear();
        if (quiet_.on && Since(w.now, quiet_.at) >= kQuietMs) {
            quiet_.Clear();
            burstOpen_ = false;
            restoreOwed_ = true;
            char line[160];
            _snprintf_s(line, sizeof line, _TRUNCATE, "display: settled (%d event%s over %u ms, none for %u ms) -> restore owed",
                        burstEvents_, burstEvents_ == 1 ? "" : "s", static_cast<unsigned>(Since(quiet_.at, burstFrom_)),
                        static_cast<unsigned>(kQuietMs));
            Say(fx, line);
            LogMonitors(w, fx);
        }
        // a restore that re-placed the window re-synced from the window as it is now (this `w` is the old one)
        if (!(restoreOwed_ && CanRestore(w) && RunRestore(w, fx))) {
            Sync(w, fx);
            MaybeConverge(w, fx);          // a converge a nested pump ate: posted again once its latch expired
        }
        // keep polling while the quiet or a monitor re-check runs, while a restore waits on something that ends by
        // itself (a movie, a placement in progress) or while PRACX's state waits for its converge; a restore waiting
        // for the user to bring the game back resumes on activation
        fx.Timer(quiet_.on || recheck_.on || (restoreOwed_ && w.foreground && !w.closing) || pracxLeft_);
    }

    void OnActivate(const World& w, Effects& fx, bool active)
    {
        if (!active) deact_ = true;
        if (active && escaped_) { escaped_ = false; Say(fx, "escape: the game is active again -> clip / topmost allowed"); }
        if (active && awaitHome_ && deact_) {
            // the user left the game while its monitor was gone and came back to it: play where it is now, until its
            // own monitor returns (a provisional monitor, never its home)
            awaitHome_ = false;
            restoreOwed_ = true;
            Say(fx, "display: the game was re-activated -> it plays where it is until its own monitor returns");
        }
        Sync(w, fx);
        if (active && (restoreOwed_ || quiet_.on)) fx.Timer(true);
    }

    // The user PUT the game where it is (the boot, the end of a drag): that monitor is its home from now on -- what
    // every restore returns to. Any provisional monitor and any wait for a vanished one are over.
    void NoteHome(const World& w)
    {
        if (w.cur < 0 || w.cur >= w.nMons) return;
        homeSet_ = true;
        home_ = w.mons[w.cur];
        adoptSet_ = false;
        EndWait();
        if (!knownSet_) Accept(w);
    }

    // The user picked a mode (Preferences, Alt+Enter, PRACX's menu item). With its home monitor present that monitor is
    // where the game now is (a pick made there -- or after moving the game elsewhere -- is the user's placement). With
    // home gone it is only where the game plays until home returns (provisional): picking a mode is not choosing to
    // leave a monitor that vanished under the game (re-audit N-B).
    void UserPicked(const World& w)
    {
        if (w.cur < 0 || w.cur >= w.nMons) return;
        if (!homeSet_ || FindMonitor(home_, w.mons, w.nMons) >= 0) {
            homeSet_ = true;
            home_ = w.mons[w.cur];
            adoptSet_ = false;
        } else {
            adoptSet_ = true;
            adopted_ = w.mons[w.cur];
        }
        EndWait();
        if (!knownSet_) Accept(w);
    }

    // The next timer tick may run a restore, which has to recognise monitors by device path: vidmode.cpp reads the
    // paths (EnumDisplayDevices) only then, and for NoteHome / UserPicked -- never on a release, a placement, an
    // activation or an idle tick (re-audit N-A).
    bool NeedsPaths(uint32_t now) const
    {
        return restoreOwed_ || (quiet_.on && Since(now, quiet_.at) >= kQuietMs);
    }

    // Clip / topmost / backdrop from the state.
    void Sync(const World& w, Effects& fx)
    {
        if (!knownSet_) Accept(w);
        if (w.escapeGen != escapeGen_) {
            escapeGen_ = w.escapeGen;
            escaped_ = true;
            Say(fx, "escape: hotkey -> clip, topmost and backdrop held off until the game is activated again");
        }
        const bool top = WantTopmost(w);
        fx.Topmost(top);
        if (!w.applying) {
            Rect mon;
            const bool bd = WantBackdrop(w, &mon);
            fx.Backdrop(bd, mon, top);
        }
        fx.Clip(WantClip(w));
    }

    // ---- decisions ----------------------------------------------------------------------------------------------

    bool Quiet() const { return quiet_.on; }
    bool RestoreOwed() const { return restoreOwed_; }
    bool AwaitHome() const { return awaitHome_; }
    bool Escaped() const { return escaped_; }
    bool PracxLeft() const { return pracxLeft_; }
    bool HomeSet() const { return homeSet_; }
    const Monitor& Home() const { return home_; }
    bool AdoptSet() const { return adoptSet_; }
    const Monitor& Adopted() const { return adopted_; }

    static bool FullscreenRunning(const World& w) { return !w.fWindowed || w.mode == kFullscreen; }

    // Anything may be held at all: not in a quiet period, not with a restore still owed or the game's monitor gone
    // (what is held comes back with the restore, on the right monitor), not after the escape hotkey, not minimised.
    bool Holdable(const World& w) const
    {
        return w.booted && !w.closing && !quiet_.on && !restoreOwed_ && !awaitHome_ && !escaped_ && !w.iconic;
    }
    bool WantTopmost(const World& w) const { return Holdable(w) && FullscreenRunning(w) && w.foreground; }
    bool WantClip(const World& w) const { return w.clipWanted && WantTopmost(w); }
    bool WantBackdrop(const World& w, Rect* mon) const
    {
        if (!Holdable(w) || !w.fWindowed || w.mode == kWindowed || w.cur < 0 || w.cur >= w.nMons) return false;
        *mon = w.mons[w.cur].rc;
        return w.win != *mon;
    }

    bool CanRestore(const World& w) const
    {
        return w.booted && !w.closing && !quiet_.on && !escaped_ && w.foreground && !w.iconic && !w.movie && !w.applying;
    }

    // Which form, on which monitor: the user's own (home) whenever it is there -- also after the game played on a
    // provisional one meanwhile. The game is never moved to another monitor on its own: with home gone it waits, unless
    // the user came back to the game after leaving it or picked a mode there (then it plays where it is, provisionally).
    Restore PickRestore(const World& w) const
    {
        Restore out;
        if (w.nMons <= 0 || w.cur < 0 || w.cur >= w.nMons) { out.kind = kRestoreUndecided; return out; }
        if (w.fWindowed && w.mode == kWindowed) return out;              // a captioned window: Windows placed it
        int t = homeSet_ ? FindMonitor(home_, w.mons, w.nMons) : w.cur;
        if (t < 0 && adoptSet_) {
            t = FindMonitor(adopted_, w.mons, w.nMons);
            out.target = Restore::kAdopted;
        }
        if (t < 0) {
            if (!deact_) { out.kind = kRestoreAwaitHome; return out; }
            t = w.cur;
            out.target = Restore::kAdoptNow;
        }
        out.mon = t;
        const Monitor& m = w.mons[t];
        if (w.fWindowed && w.mode == kBorderless) {
            if (w.win != FitRect(m.rc, w.sw, w.sh)) out.kind = kRestoreRefit;
            return out;
        }
        if (!NeedsScaled(m.rc, w.sw, w.sh, w.switchAllowed)) {
            if (w.fWindowed || w.win != m.rc) out.kind = kRestoreNative;
        } else {
            if (!(w.fWindowed && w.mode == kFullscreen && w.win == FitRect(m.rc, w.sw, w.sh))) out.kind = kRestoreScaled;
        }
        return out;
    }

private:
    void EndWait()
    {
        if (awaitHome_ || (restoreOwed_ && !quiet_.on)) { awaitHome_ = false; restoreOwed_ = false; }
    }

    // The set changed without a message that counted (a placement or a timer tick saw it): an event of its own.
    bool CheckMonitorSet(const World& w, Effects& fx)
    {
        if (!knownSet_ || !w.booted || w.closing || SameMonitorSet(w.mons, w.nMons, known_, nKnown_)) return false;
        if (w.ownSwitch) { Accept(w); return false; }
        Event(w, fx, kEventMonitorSet, 0, 0);
        return true;
    }

    void Accept(const World& w)
    {
        nKnown_ = w.nMons < kMaxMonitors ? w.nMons : kMaxMonitors;
        for (int i = 0; i < nKnown_; ++i) known_[i] = w.mons[i];
        knownSet_ = true;
    }

    void Event(const World& w, Effects& fx, unsigned msg, uintptr_t wp, intptr_t lp)
    {
        const bool first = !quiet_.on || burstOpen_;
        burstOpen_ = false;
        quiet_.Set(w.now);
        Accept(w);
        restoreOwed_ = false;
        awaitHome_ = false;
        if (first) {
            burstEvents_ = 0;
            burstFrom_ = w.now;
            undecidedLogged_ = false;
            deact_ = !w.foreground;           // left the game before this burst: coming back to it is the user's choice
        }
        ++burstEvents_;
        if (burstEvents_ <= kEventsLoggedPerBurst) {
            const char* tail = first ? " -> clip released, topmost dropped, backdrop hidden" : "";
            char line[200];
            if (msg == kWM_DISPLAYCHANGE)
                _snprintf_s(line, sizeof line, _TRUNCATE, "display: %s %ux%u %u bpp%s", EventName(msg),
                            static_cast<unsigned>(lp & 0xFFFF), static_cast<unsigned>((lp >> 16) & 0xFFFF),
                            static_cast<unsigned>(wp), tail);
            else if (msg == kWM_DPICHANGED)
                _snprintf_s(line, sizeof line, _TRUNCATE, "display: %s %u dpi%s", EventName(msg),
                            static_cast<unsigned>(wp & 0xFFFF), tail);
            else
                _snprintf_s(line, sizeof line, _TRUNCATE, "display: %s%s", EventName(msg, wp), tail);
            Say(fx, line);
            if (first) LogMonitors(w, fx);
        }
        // release first, decide later: nothing may hold the pointer or the z-order while the topology is moving
        fx.Clip(false);
        fx.Backdrop(false, Rect(), false);
        fx.Topmost(false);
        fx.EventCounted();
        fx.Timer(true);
    }

    // PRACX's SetWindowed(false) left m_fWindowed = 0 on a monitor of another size: post the converge, at most once
    // per kConvergeLatchMs (the latch expires on its own; a posted message that never arrives is a normal case), and
    // let the timer retry while it is outstanding.
    void MaybeConverge(const World& w, Effects& fx)
    {
        if (!pracxLeft_ || w.fWindowed) return;
        if (!w.booted || w.closing || !CurNeedsScaled(w)) { pracxLeft_ = false; return; }   // PRACX's own Fullscreen fits here
        if (quiet_.on || restoreOwed_ || awaitHome_) return;               // the restore takes it from here
        fx.Timer(true);
        if (converge_.Live(w.now, kConvergeLatchMs)) return;              // in flight
        const bool again = converge_.on;
        converge_.Set(w.now);
        Say(fx, again ? "converge: the last one never arrived -> posted again"
                      : "converge: PRACX's SetWindowed(false) left its windowed state on a monitor of another size -> posted");
        fx.PostConverge();
    }

    bool CurNeedsScaled(const World& w) const
    {
        return w.cur >= 0 && w.cur < w.nMons && NeedsScaled(w.mons[w.cur].rc, w.sw, w.sh, w.switchAllowed);
    }

    // true = the window was re-placed (the effect synced it)
    bool RunRestore(const World& w, Effects& fx)
    {
        const Restore r = PickRestore(w);
        if (r.kind == kRestoreUndecided) {
            if (!undecidedLogged_) { undecidedLogged_ = true; Say(fx, "display: restore undecided (no monitor) -> waiting"); }
            return false;
        }
        restoreOwed_ = false;
        if (r.kind == kRestoreAwaitHome) {
            awaitHome_ = true;
            Say(fx, "display: the game's monitor is gone -> nothing held until it returns, a mode is picked, or the game "
                    "is left and activated again (it is never moved to another monitor on its own)");
            return false;
        }
        pracxLeft_ = false;
        deact_ = false;
        // the record of the monitor it goes to, as it is now (name, rect, path): home stays home; a provisional one
        // stays provisional, and ends once home is back
        if (r.mon >= 0) {
            if (r.target == Restore::kHome) {
                if (homeSet_) home_ = w.mons[r.mon];
                adoptSet_ = false;
            } else {
                adoptSet_ = true;
                adopted_ = w.mons[r.mon];
            }
        }
        char line[220];
        if (r.mon >= 0) {
            const Monitor& m = w.mons[r.mon];
            _snprintf_s(line, sizeof line, _TRUNCATE, "display: restore -> %s on %s (%d,%d %dx%d)%s", RestoreName(r.kind), m.name,
                        m.rc.l, m.rc.t, m.rc.W(), m.rc.H(),
                        r.target == Restore::kHome ? " = the game's monitor"
                        : " (provisional: the game's own monitor is gone; it goes back there when it returns)");
        } else {
            _snprintf_s(line, sizeof line, _TRUNCATE, "display: restore -> %s", RestoreName(r.kind));
        }
        Say(fx, line);
        if (r.kind == kRestoreNative) fx.Native(w.mons[r.mon]);
        else if (r.kind == kRestoreScaled) fx.Scaled(w.mons[r.mon]);
        else if (r.kind == kRestoreRefit) fx.Refit(w.mons[r.mon], w.mode == kFullscreen);
        return r.kind != kRestoreNone;
    }

    void LogMonitors(const World& w, Effects& fx) const
    {
        for (int i = 0; i < w.nMons; ++i) {
            const Monitor& m = w.mons[i];
            char line[300];
            _snprintf_s(line, sizeof line, _TRUNCATE, "display:   monitor %s %d,%d %dx%d%s%s %s", m.name, m.rc.l, m.rc.t, m.rc.W(),
                        m.rc.H(), m.primary ? " primary" : "", i == w.cur ? " <- game window" : "", m.path);
            Say(fx, line);
        }
        if (w.nMons == 0) Say(fx, "display:   no monitor");
        char line[96];
        _snprintf_s(line, sizeof line, _TRUNCATE, "display:   game window %d,%d %dx%d", w.win.l, w.win.t, w.win.W(), w.win.H());
        Say(fx, line);
    }

    void Rate(Effects& fx, const char* line, uint32_t now)
    {
        if (ignoredLogged_ && Since(now, ignoredAt_) < kIgnoredLogMs) return;
        ignoredLogged_ = true;
        ignoredAt_ = now;
        Say(fx, line);
    }

    static void Say(Effects& fx, const char* line) { fx.Log(line); }

    TimeLatch quiet_;              // counted events: Set on each, the restore once kQuietMs passed without one
    bool burstOpen_ = false;       // PreRelease began a burst that no Event has counted yet
    TimeLatch recheck_;            // an ignored device / work-area notice: the monitor set is compared on the timer
    TimeLatch converge_;           // the posted converge in flight
    int  seen_ = -1;               // m_fWindowed at the last message (-1 = none yet)
    bool pracxLeft_ = false;       // PRACX's SetWindowed(false) ran and nothing answered it yet
    bool restoreOwed_ = false;
    bool awaitHome_ = false;       // the game's monitor is gone: nothing held, no re-placement
    bool deact_ = false;           // the game was not the foreground window at some point since the burst began
    bool escaped_ = false;
    uint32_t escapeGen_ = 0;
    bool homeSet_ = false;
    Monitor home_;                 // the user's monitor: changed only by the boot, a drag, or a mode picked with it present
    bool adoptSet_ = false;
    Monitor adopted_;              // where the game plays while home is gone (the user came back to it there)
    bool knownSet_ = false;        // the monitor set as last accepted
    Monitor known_[kMaxMonitors];
    int  nKnown_ = 0;
    int  burstEvents_ = 0;
    uint32_t burstFrom_ = 0;
    bool undecidedLogged_ = false;
    bool ignoredLogged_ = false;
    uint32_t ignoredAt_ = 0;
};

// ---- watchdog (vidwatch.cpp) ---------------------------------------------------------------------------------------
// Probes the game thread (a WM_NULL our subclass answers) and MEASURES its stalls: every one of kWatchStallLogMs or
// more is reported with its length once it ends. It never releases anything on a stall. A long AI turn stops the game
// thread pumping messages for 5-10 s on a late-game map while it keeps drawing, Windows' own hung test
// (IsHungAppWindow) calls that "not responding", and a release then dropped a working game out of the topmost band:
// a black flash and a flicker when the turn ended (2026-11-08, measured: no portrait work, vanilla PRACX clean). A game
// thread that truly hangs is left to the user: the escape hotkey and Ctrl+Alt+Del.
enum WatchAction { kWatchNothing = 0, kWatchStall };

struct Watch {
    bool missing = false;          // a probe went unanswered and none has been answered since
    uint32_t missSince = 0;        // when the game thread was last known to answer (the failed probe's send time)
    uint32_t stallMs = 0;          // the length of the stall that just ended (kWatchStall)
    // `now` = after the probe returned (an unanswered one waited kWatchProbeMs)
    WatchAction Step(uint32_t now, bool answered)
    {
        if (answered) {
            WatchAction a = kWatchNothing;
            if (missing) {
                stallMs = Since(now, missSince);
                if (stallMs >= kWatchStallLogMs) a = kWatchStall;
            }
            missing = false;
            return a;
        }
        if (!missing) { missing = true; missSince = now - kWatchProbeMs; }
        return kWatchNothing;
    }
};

// ---- who owns the backdrop window ----------------------------------------------------------------------------------
// Decided once, by whichever side claims first (an interlocked compare-exchange in vidwatch.cpp): the watchdog thread
// when it came up in time, else the game thread. A watchdog that comes up after the game thread gave up on it never
// gets the backdrop (it destroys the one it made) -- two backdrops, one of them hidden by nobody, stayed on screen
// topmost (audit 2026-10-25, H1).
enum BackdropOwner { kOwnerUndecided = 0, kOwnerWatchdog = 1, kOwnerGame = 2 };
inline int ClaimOwner(int current, int claimant) { return current == kOwnerUndecided ? claimant : current; }

// ---- the escape hotkey ([UIMod] EscapeHotkey) ----------------------------------------------------------------------
constexpr unsigned kMOD_ALT = 0x1, kMOD_CONTROL = 0x2, kMOD_SHIFT = 0x4, kMOD_WIN = 0x8;
constexpr const char* kDefaultHotkey = "Ctrl+Alt+Shift+End";

struct KeyName { const char* name; unsigned vk; };
inline const KeyName* KeyNames(int* n)
{
    static const KeyName k[] = {
        { "End", 0x23 }, { "Home", 0x24 }, { "Insert", 0x2D }, { "Delete", 0x2E }, { "PageUp", 0x21 },
        { "PageDown", 0x22 }, { "Pause", 0x13 }, { "ScrollLock", 0x91 }, { "Backspace", 0x08 }, { "Escape", 0x1B },
        { "Space", 0x20 }, { "Tab", 0x09 },
    };
    *n = static_cast<int>(sizeof k / sizeof k[0]);
    return k;
}

inline bool EqNoCase(const char* a, size_t n, const char* b)
{
    if (strlen(b) != n) return false;
    for (size_t i = 0; i < n; ++i) {
        char x = a[i], y = b[i];
        if (x >= 'a' && x <= 'z') x = static_cast<char>(x - 32);
        if (y >= 'a' && y <= 'z') y = static_cast<char>(y - 32);
        if (x != y) return false;
    }
    return true;
}

// "Ctrl+Alt+Shift+End" -> MOD_* | key. False = off ("", "off", "none", "0") or not understood; a key needs at least
// one modifier (a bare key would be taken from every program while the game runs).
inline bool ParseHotkey(const char* s, unsigned* mods, unsigned* vk)
{
    *mods = 0; *vk = 0;
    if (!s) return false;
    unsigned m = 0, key = 0;
    int keys = 0;
    const char* p = s;
    for (;;) {
        while (*p == ' ') ++p;
        const char* e = p;
        while (*e && *e != '+') ++e;
        size_t n = static_cast<size_t>(e - p);
        while (n && p[n - 1] == ' ') --n;
        if (n == 0) return false;
        if (EqNoCase(p, n, "Ctrl") || EqNoCase(p, n, "Control")) m |= kMOD_CONTROL;
        else if (EqNoCase(p, n, "Alt")) m |= kMOD_ALT;
        else if (EqNoCase(p, n, "Shift")) m |= kMOD_SHIFT;
        else if (EqNoCase(p, n, "Win")) m |= kMOD_WIN;
        else {
            unsigned v = 0;
            int nk; const KeyName* names = KeyNames(&nk);
            for (int i = 0; i < nk && !v; ++i) if (EqNoCase(p, n, names[i].name)) v = names[i].vk;
            if (!v && n == 1 && ((p[0] >= 'A' && p[0] <= 'Z') || (p[0] >= '0' && p[0] <= '9'))) v = static_cast<unsigned char>(p[0]);
            if (!v && n == 1 && p[0] >= 'a' && p[0] <= 'z') v = static_cast<unsigned>(p[0] - 32);
            if (!v && (p[0] == 'F' || p[0] == 'f') && n >= 2 && n <= 3) {
                int f = 0;
                for (size_t i = 1; i < n; ++i) { if (p[i] < '0' || p[i] > '9') { f = 0; break; } f = f * 10 + (p[i] - '0'); }
                if (f >= 1 && f <= 24) v = 0x70 + static_cast<unsigned>(f - 1);
            }
            if (!v) return false;
            key = v; ++keys;
        }
        if (!*e) break;
        p = e + 1;
    }
    if (keys != 1 || m == 0) return false;
    *mods = m; *vk = key;
    return true;
}

inline void FormatHotkey(unsigned mods, unsigned vk, char* out, size_t n)
{
    out[0] = '\0';
    if (mods & kMOD_CONTROL) strncat_s(out, n, "Ctrl+", _TRUNCATE);
    if (mods & kMOD_ALT) strncat_s(out, n, "Alt+", _TRUNCATE);
    if (mods & kMOD_SHIFT) strncat_s(out, n, "Shift+", _TRUNCATE);
    if (mods & kMOD_WIN) strncat_s(out, n, "Win+", _TRUNCATE);
    char k[16] = {};
    int nk; const KeyName* names = KeyNames(&nk);
    for (int i = 0; i < nk && !k[0]; ++i) if (names[i].vk == vk) strncpy_s(k, names[i].name, _TRUNCATE);
    if (!k[0] && vk >= 0x70 && vk <= 0x87) _snprintf_s(k, sizeof k, _TRUNCATE, "F%u", vk - 0x70 + 1);
    if (!k[0] && ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9'))) { k[0] = static_cast<char>(vk); k[1] = '\0'; }
    if (!k[0]) _snprintf_s(k, sizeof k, _TRUNCATE, "0x%02X", vk);
    strncat_s(out, n, k, _TRUNCATE);
}

// ---- GPU device life (gpuscale.cpp) --------------------------------------------------------------------------------
constexpr long kDXGI_ERROR_DEVICE_REMOVED = static_cast<long>(0x887A0005), kDXGI_ERROR_DEVICE_HUNG = static_cast<long>(0x887A0006),
               kDXGI_ERROR_DEVICE_RESET = static_cast<long>(0x887A0007), kDXGI_ERROR_DRIVER_INTERNAL_ERROR = static_cast<long>(0x887A0020);

// A lost device (driver reset / removal): worth another device once the display settles. Anything else: off.
inline bool DeviceLost(long hr)
{
    return hr == kDXGI_ERROR_DEVICE_REMOVED || hr == kDXGI_ERROR_DEVICE_HUNG || hr == kDXGI_ERROR_DEVICE_RESET ||
           hr == kDXGI_ERROR_DRIVER_INTERNAL_ERROR;
}

// The wait before the n-th new device in a row (n >= 1): 2 s, 10 s, then 60 s each, for the whole session. A device
// that runs kGpuStableMs starts the count again.
inline uint32_t GpuBackoffMs(int n) { return n <= 1 ? 2000u : n == 2 ? 10000u : 60000u; }

struct GpuLife {
    enum State { kIdle = 0, kCreating, kLive, kOff };
    State st = kIdle;
    int losses = 0;                // devices lost in a row (reset by kGpuStableMs of running)
    uint32_t retryAt = 0;          // no new device before this (valid while losses > 0)
    uint32_t liveSince = 0;
    bool haveEvent = false;
    uint32_t lastEvent = 0;

    // only ever later (the display tick is fed in again on every call)
    void DisplayEvent(uint32_t at)
    {
        if (!haveEvent || static_cast<int32_t>(at - lastEvent) > 0) lastEvent = at;
        haveEvent = true;
    }
    bool Settled(uint32_t now) const { return !haveEvent || Since(now, lastEvent) >= kGpuQuietMs; }
    // the GPU may be touched at all now (create, resize, upload, present)
    bool MayUse(uint32_t now) const { return st != kOff && Settled(now); }
    bool MayStart(uint32_t now) const
    {
        return st == kIdle && Settled(now) && (losses == 0 || static_cast<int32_t>(now - retryAt) >= 0);
    }
    void Started() { st = kCreating; }
    // the worker finished: a first device that cannot be made means no GPU on this machine (off); after a loss the
    // driver may still be recovering, so that is one more loss
    void Created(bool ok, uint32_t now)
    {
        if (ok) { st = kLive; liveSince = now; return; }
        if (losses > 0) { Backoff(now); return; }
        st = kOff;
    }
    void Failed() { st = kOff; }
    // the live device was lost: true = released, a new one after the back-off
    bool Lost(long hr, uint32_t now)
    {
        if (!DeviceLost(hr)) { st = kOff; return false; }
        Backoff(now);
        return true;
    }
    void Presented(uint32_t now)
    {
        if (st == kLive && losses > 0 && Since(now, liveSince) >= kGpuStableMs) losses = 0;
    }

private:
    void Backoff(uint32_t now)
    {
        ++losses;
        st = kIdle;
        retryAt = now + GpuBackoffMs(losses);
        DisplayEvent(now);             // a removal is a display event of its own
    }
};

} // namespace vidsafety
