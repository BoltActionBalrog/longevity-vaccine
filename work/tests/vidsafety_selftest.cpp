// Harness for src\uimod\src\vidsafety.h (built by test_vidsafety.py; no Windows API).
//
//   t script            stdin = a scenario (below); stdout = one "dump" line per `dump`, plus every controller log line
//   t hotkey <text>     -> "ok mods=<n> vk=<n> name=<formatted>" | "off"
//   t watch             stdin = lines "<t> <danger> <answered> <hung>"; stdout = one action per line
//   t gpu               stdin = GpuLife commands; stdout = the state after each
//   t owner <claims>    claims = a sequence of "watchdog" / "game" (who claims the backdrop, in order) -> the owner after each
//
// The scenario world models what the game window does in vidmode.cpp (SubclassProc, ApplyPopup, VidModeSet, the
// restore effects, the probe answer), what PRACX does (refs\pracx\shared\pracx.cpp: SetWindowed / WM_USER+3 /
// SC_MAXIMIZE, SetMinimised on WM_ACTIVATEAPP) and what the watchdog thread does to the window (vidwatch.cpp
// Release), with the same Controller calls in the same places. Window moves made by Windows itself are commands.
//
// Script commands (one per line, # comments):
//   mon <name> <l> <t> <r> <b> [primary] [path=<p>]   add or replace a monitor
//   unmon <name>                           the monitor is gone
//   bb <w> <h>                             backbuffer (ScreenWidth x ScreenHeight)
//   clipwanted 0|1   switch 0|1            [UIMod] ConstrainMouse / FullscreenModeSwitch
//   ownswitch 0|1                          PRACX's own ChangeDisplaySettings is running / just ran (FullscreenModeSwitch=1)
//   boot                                   PRACX's native Fullscreen on the primary, then VidModePoll (boot mode Fullscreen)
//   win <l> <t> <r> <b>                    Windows moves the window (WM_WINDOWPOSCHANGED follows)
//   display <kind>                         displaychange | devnodes | workarea | dpi | dpioverride | other
//   watchdog-display                       a topology event only the watchdog thread's window received
//   fg 0|1                                 the game stops / starts being the foreground window (WM_ACTIVATEAPP, with
//                                          the minimise on leaving Fullscreen and the restore on coming back)
//   iconic 0|1    movie 0|1
//   escape                                 the escape hotkey (watchdog thread: clip off, backdrop hidden, queued leave-topmost)
//   hang                                   the game thread stops running (it handles no message until `resume`)
//   hang-release                           the watchdog releases a HUNG game thread: clip off, backdrop hidden; the
//                                          leave-topmost request stays queued (not applied) until `resume`
//   resume                                 the game thread runs again: the queued requests apply
//   probe                                  a watchdog probe (possibly a stale one) reaches the subclass
//   drag <l> <t> <r> <b>                   the user drags the window there (WM_EXITSIZEMOVE -> NoteHome)
//   order                                  print what the last display message did first ("release" / "enum")
//   trace 0|1                              print each change of the window effects as it happens: "fx clip <0|1>",
//                                          "fx topmost <0|1>" (= one SetWindowPos), "fx backdrop <0|1>"
//   mark <label>                           "fx mark <label>" in that trace
//   pracx-toggle                           PRACX's menu item: SetWindowed(!m_fWindowed), not ours
//   user <fullscreen|borderless|windowed>  the Preferences page picks a mode (VidModeSet)
//   pump                                   dispatch posted messages
//   lose-posted                            the next posted message is eaten by a nested engine pump
//   wait <ms>                              time passes; the safety timer ticks every kTimerMs while armed; pump after each
//   dump <label>
#include "../../src/uimod/src/vidsafety.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

using namespace vidsafety;

namespace {

enum Posted { kConverge = 1, kUser3, kSysMax };

struct Fake final : Effects {
    std::vector<Monitor> mons;
    int sw = 3840, sh = 2160;
    bool switchAllowed = false, clipWanted = true, ownSwitch = false;
    Rect win;
    bool topmost = false, fWindowed = false, caption = false;
    int popupKind = -1, pending = -1;
    bool foreground = true, iconic = false, movie = false, closing = false, booted = false;
    bool clipOn = false;
    Rect clip;
    bool bdVisible = false, bdTop = false;
    Rect bdRect;
    bool timerOn = false;
    uint32_t now = 100000, escapeGen = 0;
    bool ownSW = false, haveTarget = false;
    Rect target, savedWindowed = { 200, 200, 1224, 968 };
    std::deque<int> queue;
    bool loseNext = false;
    bool hung = false, queuedNoTopmost = false, resyncOwed = false;
    bool trace = false;           // `trace 1`: print every clip call and every topmost / backdrop change ("fx ...")
    Controller ctl;
    int converges = 0, setWindowedCalls = 0, depth = 0, timerTicks = 0, gpuEvents = 0, restores = 0;
    mutable int pathReads = 0;    // worlds built WITH device paths (vidmode.cpp MakeWorld(hwnd, true): EnumDisplayDevices)
    mutable std::vector<std::string> order;   // "release" / "enum" as the glue does them on a display message

    // ---- the window's view ----
    int Nearest(const Rect& r) const
    {
        const double cx = (r.l + r.r) / 2.0, cy = (r.t + r.b) / 2.0;
        int best = -1; double bd = 0;
        for (int i = 0; i < static_cast<int>(mons.size()); ++i) {
            const Rect& m = mons[i].rc;
            const double dx = cx >= m.l && cx < m.r ? 0 : (cx < m.l ? m.l - cx : cx - m.r);
            const double dy = cy >= m.t && cy < m.b ? 0 : (cy < m.t ? m.t - cy : cy - m.b);
            const double d = dx * dx + dy * dy;
            if (best < 0 || d < bd) { best = i; bd = d; }
        }
        return best;
    }
    int Detect() const
    {
        if (!fWindowed) return kFullscreen;
        if (pending >= 0) return pending;
        if (caption) return kWindowed;
        return popupKind == kFullscreen ? kFullscreen : kBorderless;
    }
    // vidmode.cpp MakeWorld: the monitor list always, the device paths only when asked
    World W(bool paths = false) const
    {
        if (paths) ++pathReads;
        order.push_back("enum");
        World w;
        w.now = now; w.booted = booted; w.closing = closing; w.fWindowed = fWindowed; w.mode = Detect();
        w.applying = pending >= 0; w.foreground = foreground; w.iconic = iconic; w.movie = movie;
        w.switchAllowed = switchAllowed; w.clipWanted = clipWanted; w.ownSwitch = ownSwitch; w.sw = sw; w.sh = sh;
        w.win = win;
        w.nMons = static_cast<int>(mons.size());
        for (int i = 0; i < w.nMons; ++i) {
            w.mons[i] = mons[i];
            if (!paths) w.mons[i].path[0] = '\0';
        }
        w.cur = Nearest(win);
        w.escapeGen = escapeGen;
        return w;
    }

    // ---- message deliveries: each samples m_fWindowed first, as SubclassProc does; a hung thread handles none ----
    void Msg() { if (booted) ctl.Observe(fWindowed, ownSW); }
    void Placement()
    {
        if (hung) return;
        if (depth > 16) { std::printf("RECURSION\n"); std::exit(9); }
        ++depth;
        Msg();
        if (booted) ctl.OnPlacement(W(), *this);
        --depth;
    }
    void Sync() { if (booted && !hung) ctl.Sync(W(), *this); }
    void Post(int m)
    {
        if (loseNext) { loseNext = false; return; }
        queue.push_back(m);
    }
    void Pump()
    {
        if (hung) return;
        for (int guard = 0; !queue.empty(); ++guard) {
            if (guard > 64) { std::printf("STORM\n"); std::exit(8); }
            const int m = queue.front();
            queue.pop_front();
            Msg();
            if (m == kConverge) {
                if (ctl.OnConverge(W(), *this)) VidModeSet(kFullscreen);
            } else if (m == kUser3) {             // PRACX: SetWindowPlacement(m_rWindowedRect) + HWND_NOTOPMOST
                win = savedWindowed;
                topmost = false;
                Placement();
                if (pending >= 0) ApplyPopup(pending == kFullscreen, nullptr);   // our subclass, after PRACX
            } else if (m == kSysMax) {            // swallowed by our subclass while m_fWindowed = 1
                if (!fWindowed) {
                    const int i = Nearest(win);
                    if (i >= 0) win = mons[i].rc;
                    Placement();
                }
            }
        }
    }

    // ---- PRACX (pracx.cpp SetWindowed) ----
    void PracxSetWindowed(bool v)
    {
        ++setWindowedCalls;
        if (fWindowed == v || movie) return;
        fWindowed = v;                            // written before any window call (prax.dll 0x1000A094)
        if (v) {
            caption = true;                       // SetWindowLong(AC_WS_WINDOWED): WM_STYLECHANGED
            Placement();
            Post(kUser3);
        } else {
            savedWindowed = win;                  // GetWindowPlacement -> m_rWindowedRect
            caption = false;                      // SetWindowLong(AC_WS_FULLSCREEN)
            Placement();
            topmost = true;                       // SetWindowPos(HWND_TOPMOST, NOMOVE | NOSIZE)
            Placement();
            Post(kSysMax);
        }
    }
    void OwnSetWindowed(bool v)
    {
        ownSW = true;
        PracxSetWindowed(v);
        ownSW = false;
        ctl.Observe(fWindowed, true);
    }

    // ---- vidmode.cpp ----
    void ApplyPopup(bool full, const Rect* t)
    {
        pending = full ? kFullscreen : kBorderless;
        Rect mon;
        if (t) mon = *t;
        else if (haveTarget) mon = target;
        else mon = mons[Nearest(win)].rc;
        haveTarget = false;
        win = FitRect(mon, sw, sh);
        caption = false;
        Placement();
        popupKind = pending;
        pending = -1;
        Sync();
    }
    void VidModeSet(int mode)
    {
        const int cur = Detect();
        const bool legacyFull = !fWindowed;
        const int ci = Nearest(win);
        const bool wantScaled = mode == kFullscreen && ci >= 0 && NeedsScaled(mons[ci].rc, sw, sh, switchAllowed);
        const bool wasAwaiting = ctl.AwaitHome();
        if (booted) ctl.UserPicked(W(true));
        if (mode == cur && !(legacyFull && wantScaled)) {
            if (wasAwaiting && fWindowed && mode != kWindowed) ApplyPopup(mode == kFullscreen, nullptr);
            else Sync();
            return;
        }
        pending = -1;
        haveTarget = false;
        if (mode == kFullscreen && !wantScaled) {
            clipOn = false; bdVisible = false; popupKind = -1;
            OwnSetWindowed(false);
        } else if (mode == kWindowed) {
            clipOn = false; bdVisible = false; popupKind = -1;
            if (legacyFull) OwnSetWindowed(true);
            else { caption = true; Placement(); Post(kUser3); }
        } else {
            if (legacyFull) {
                pending = mode;
                OwnSetWindowed(true);
                if (!fWindowed) pending = -1;
            } else {
                ApplyPopup(mode == kFullscreen, nullptr);
            }
        }
    }

    // ---- Effects ----
    void Clip(bool on) override
    {
        if (trace && on != clipOn) std::printf("fx clip %d\n", on ? 1 : 0);
        if (!on) order.push_back("release");
        clipOn = on;
        if (on) clip = win;
    }
    // WinFx::Topmost: a SetWindowPos only on a change, and that sends WM_WINDOWPOSCHANGED (the nested placement)
    void Topmost(bool on) override
    {
        if (topmost == on) return;
        if (trace) std::printf("fx topmost %d\n", on ? 1 : 0);
        topmost = on;
        Placement();
    }
    void Backdrop(bool show, const Rect& m, bool top) override
    {
        if (trace && show != bdVisible) std::printf("fx backdrop %d\n", show ? 1 : 0);
        bdVisible = show;
        if (show) { bdRect = m; bdTop = top; }
    }
    void PostConverge() override { ++converges; Post(kConverge); }
    void Timer(bool on) override { timerOn = on; }
    void Native(const Monitor& m) override
    {
        ++restores;
        if (fWindowed) {
            clipOn = false; bdVisible = false; pending = -1; popupKind = -1;
            OwnSetWindowed(false);
        }
        win = m.rc;
        Placement();
        Sync();
    }
    void Scaled(const Monitor& m) override
    {
        ++restores;
        if (fWindowed) { ApplyPopup(true, &m.rc); return; }
        clipOn = false; bdVisible = false;
        target = m.rc; haveTarget = true; pending = kFullscreen;
        OwnSetWindowed(true);
        if (!fWindowed) { pending = -1; haveTarget = false; }
    }
    void Refit(const Monitor& m, bool full) override { ++restores; ApplyPopup(full, &m.rc); }
    void EventCounted() override { ++gpuEvents; }
    void Log(const char* line) override { std::printf("log %s\n", line); }

    // ---- script ----
    Monitor* Find(const char* name)
    {
        for (Monitor& m : mons) if (!std::strcmp(m.name, name)) return &m;
        return nullptr;
    }
    void Dump(const char* label) const
    {
        const int ci = Nearest(win);
        std::printf("dump %s mode=%d fW=%d win=%d,%d,%d,%d on=%s topmost=%d clip=%d clipRect=%d,%d,%d,%d bd=%d bdRect=%d,%d,%d,%d "
                    "bdTop=%d quiet=%d owed=%d await=%d escaped=%d converges=%d setWindowed=%d restores=%d gpuEvents=%d "
                    "timer=%d fg=%d iconic=%d queue=%d home=%s adopted=%s pathReads=%d\n",
                    label, Detect(), fWindowed ? 1 : 0, win.l, win.t, win.r, win.b, ci >= 0 ? mons[ci].name : "-",
                    topmost ? 1 : 0, clipOn ? 1 : 0, clip.l, clip.t, clip.r, clip.b, bdVisible ? 1 : 0,
                    bdRect.l, bdRect.t, bdRect.r, bdRect.b, bdTop ? 1 : 0, ctl.Quiet() ? 1 : 0, ctl.RestoreOwed() ? 1 : 0,
                    ctl.AwaitHome() ? 1 : 0, ctl.Escaped() ? 1 : 0, converges, setWindowedCalls, restores, gpuEvents,
                    timerOn ? 1 : 0, foreground ? 1 : 0, iconic ? 1 : 0, static_cast<int>(queue.size()),
                    ctl.HomeSet() ? ctl.Home().name : "-", ctl.AdoptSet() ? ctl.Adopted().name : "-", pathReads);
    }
    // vidmode.cpp OnDisplayEvent: a message that always counts releases before the monitor list is read
    void DisplayMessage(unsigned msg, uintptr_t wp, intptr_t lp)
    {
        order.clear();
        ctl.PreRelease(now, ownSwitch, msg, wp, *this);
        ctl.OnDisplayEvent(W(), *this, msg, wp, lp);
    }
    void Activate(bool active)
    {
        foreground = active;
        if (hung) return;
        if (!active) {
            // leaving Fullscreen minimises: PRACX's SetMinimised (native) / our subclass (scaled popup)
            if (booted && Detect() == kFullscreen && !iconic) { iconic = true; Placement(); }
            Msg();
            ctl.OnActivate(W(), *this, false);
            return;
        }
        if (booted && iconic && !fWindowed) { iconic = false; Placement(); }   // PRACX's SetMinimised(false), inside the message
        Msg();
        ctl.OnActivate(W(), *this, true);
        if (booted && iconic) { iconic = false; Placement(); }                 // the shell restores the popup after activation
    }
    void Run(char* line)
    {
        char* p = std::strchr(line, '#');
        if (p) *p = '\0';
        char cmd[32] = {}, a[64] = {}, b[64] = {};
        int n[4] = {};
        if (std::sscanf(line, "%31s", cmd) != 1) return;
        const std::string c = cmd;
        if (c == "mon") {
            Monitor m;
            char r1[96] = {}, r2[96] = {};
            std::sscanf(line, "%*s %31s %d %d %d %d %95s %95s", m.name, &n[0], &n[1], &n[2], &n[3], r1, r2);
            m.rc = { n[0], n[1], n[2], n[3] };
            for (const char* r : { r1, r2 }) {
                if (!std::strcmp(r, "primary")) m.primary = true;
                else if (!std::strncmp(r, "path=", 5)) strncpy_s(m.path, r + 5, _TRUNCATE);
            }
            if (m.primary) for (Monitor& o : mons) o.primary = false;
            if (Monitor* old = Find(m.name)) *old = m; else mons.push_back(m);
        } else if (c == "unmon") {
            std::sscanf(line, "%*s %63s", a);
            for (size_t i = 0; i < mons.size(); ++i) if (!std::strcmp(mons[i].name, a)) { mons.erase(mons.begin() + i); break; }
        } else if (c == "bb") {
            std::sscanf(line, "%*s %d %d", &sw, &sh);
        } else if (c == "clipwanted") {
            std::sscanf(line, "%*s %d", &n[0]); clipWanted = n[0] != 0; Sync();
        } else if (c == "switch") {
            std::sscanf(line, "%*s %d", &n[0]); switchAllowed = n[0] != 0;
        } else if (c == "ownswitch") {
            std::sscanf(line, "%*s %d", &n[0]); ownSwitch = n[0] != 0;
        } else if (c == "boot") {
            for (const Monitor& m : mons) if (m.primary) win = m.rc;
            fWindowed = false; caption = false; topmost = true;
            booted = true;
            ctl.Observe(fWindowed, true);
            ctl.NoteHome(W(true));
            VidModeSet(kFullscreen);
            Pump();
            Sync();
        } else if (c == "win") {
            std::sscanf(line, "%*s %d %d %d %d", &n[0], &n[1], &n[2], &n[3]);
            win = { n[0], n[1], n[2], n[3] };
            Placement();
        } else if (c == "display") {
            std::sscanf(line, "%*s %63s", a);
            const std::string k = a;
            unsigned msg = kWM_DISPLAYCHANGE; uintptr_t wp = 32;
            if (k == "devnodes") { msg = kWM_DEVICECHANGE; wp = kDBT_DEVNODES_CHANGED; }
            else if (k == "workarea") { msg = kWM_SETTINGCHANGE; wp = kSPI_SETWORKAREA; }
            else if (k == "dpi") { msg = kWM_DPICHANGED; wp = 96 | (96 << 16); }
            else if (k == "dpioverride") { msg = kWM_SETTINGCHANGE; wp = kSPI_SETLOGICALDPIOVERRIDE; }
            else if (k == "other") { msg = kWM_SETTINGCHANGE; wp = 0x2A; }
            if (hung) return;
            Msg();
            if (IsDisplayEvent(msg, wp)) DisplayMessage(msg, wp, (2160 << 16) | 3840);
        } else if (c == "watchdog-display") {
            if (hung) return;
            Msg();
            DisplayMessage(kEventFromWatchdog, 0, 0);
        } else if (c == "fg") {
            std::sscanf(line, "%*s %d", &n[0]);
            Activate(n[0] != 0);
        } else if (c == "iconic") {
            std::sscanf(line, "%*s %d", &n[0]); iconic = n[0] != 0; Placement();
        } else if (c == "movie") {
            std::sscanf(line, "%*s %d", &n[0]); movie = n[0] != 0;
        } else if (c == "escape") {
            ++escapeGen;
            clipOn = false; bdVisible = false; resyncOwed = true;   // what the watchdog thread itself does
            if (hung) queuedNoTopmost = true;
            else { topmost = false; Placement(); }                   // its queued leave-topmost arriving
        } else if (c == "hang") {
            hung = true;
        } else if (c == "hang-release") {
            clipOn = false; bdVisible = false; resyncOwed = true;
            queuedNoTopmost = true;                                  // SWP_ASYNCWINDOWPOS: waits for the hung thread
        } else if (c == "resume") {
            hung = false;
            if (queuedNoTopmost) { queuedNoTopmost = false; topmost = false; Placement(); }
        } else if (c == "probe") {
            if (hung) return;
            Msg();
            if (resyncOwed) { resyncOwed = false; Timer(true); }     // SubclassProc's probe answer
        } else if (c == "pracx-toggle") {
            PracxSetWindowed(!fWindowed);
        } else if (c == "user") {
            std::sscanf(line, "%*s %63s", b);
            const std::string m = b;
            VidModeSet(m == "windowed" ? kWindowed : m == "borderless" ? kBorderless : kFullscreen);
        } else if (c == "pump") {
            Pump();
        } else if (c == "lose-posted") {
            loseNext = true;
        } else if (c == "wait") {
            std::sscanf(line, "%*s %d", &n[0]);
            for (int t = 0; t < n[0]; t += static_cast<int>(kTimerMs)) {
                now += kTimerMs;
                if (timerOn && !hung) { ++timerTicks; Msg(); ctl.OnTimer(W(ctl.NeedsPaths(now)), *this); }
                Pump();
            }
        } else if (c == "drag") {               // the user drags the window there (WM_EXITSIZEMOVE)
            std::sscanf(line, "%*s %d %d %d %d", &n[0], &n[1], &n[2], &n[3]);
            win = { n[0], n[1], n[2], n[3] };
            Placement();
            if (!hung) ctl.NoteHome(W(true));
        } else if (c == "trace") {
            std::sscanf(line, "%*s %d", &n[0]); trace = n[0] != 0;
        } else if (c == "mark") {               // a label in the fx trace
            std::sscanf(line, "%*s %63s", a);
            std::printf("fx mark %s\n", a);
        } else if (c == "order") {              // what the last display message did first
            std::printf("order");
            for (const std::string& o : order) std::printf(" %s", o.c_str());
            std::printf("\n");
        } else if (c == "dump") {
            std::sscanf(line, "%*s %63s", a);
            Dump(a);
        } else {
            std::printf("BAD %s\n", line);
            std::exit(7);
        }
    }
};

int Script()
{
    Fake f;
    char line[256];
    while (std::fgets(line, sizeof line, stdin)) {
        line[std::strcspn(line, "\r\n")] = '\0';
        f.Run(line);
    }
    return 0;
}

int Watchdog()
{
    Watch w;
    unsigned t;
    int d, a, h;
    while (std::scanf("%u %d %d %d", &t, &d, &a, &h) == 4) {
        const WatchAction act = w.Step(t, d != 0, a != 0, h != 0);
        std::printf("%s released=%d missing=%d stall=%u\n",
                    act == kWatchRelease ? "release" : act == kWatchResumed ? "resumed" : act == kWatchStall ? "stall" : "nothing",
                    w.released ? 1 : 0, w.missing ? 1 : 0, act == kWatchResumed || act == kWatchStall ? w.stallMs : 0u);
    }
    return 0;
}

int Gpu()
{
    GpuLife g;
    char cmd[32];
    while (std::scanf("%31s", cmd) == 1) {
        const std::string c = cmd;
        unsigned t = 0, hr = 0; int ok = 0;
        if (c == "event") { std::scanf("%u", &t); g.DisplayEvent(t); }
        else if (c == "start") g.Started();
        else if (c == "created") { std::scanf("%d %u", &ok, &t); g.Created(ok != 0, t); }
        else if (c == "lost") { std::scanf("%x %u", &hr, &t); std::printf("retry=%d ", g.Lost(static_cast<long>(hr), t) ? 1 : 0); }
        else if (c == "presented") { std::scanf("%u", &t); g.Presented(t); }
        else if (c == "failed") g.Failed();
        else if (c == "at") { std::scanf("%u", &t); }
        else { std::printf("BAD %s\n", cmd); return 7; }
        if (c == "at" || c == "event" || c == "created" || c == "lost" || c == "presented")
            std::printf("st=%d losses=%d maystart=%d mayuse=%d\n", static_cast<int>(g.st), g.losses, g.MayStart(t) ? 1 : 0, g.MayUse(t) ? 1 : 0);
        else
            std::printf("st=%d losses=%d\n", static_cast<int>(g.st), g.losses);
    }
    return 0;
}

} // namespace

int main(int argc, char** argv)
{
    if (argc < 2) return 2;
    const std::string mode = argv[1];
    if (mode == "script") return Script();
    if (mode == "watch") return Watchdog();
    if (mode == "gpu") return Gpu();
    if (mode == "owner") {                     // vidwatch.cpp: both sides claim with a compare-exchange from "undecided"
        int owner = kOwnerUndecided;
        for (int i = 2; i < argc; ++i) {
            const int claimant = !std::strcmp(argv[i], "watchdog") ? kOwnerWatchdog : kOwnerGame;
            const int prev = owner;
            if (owner == kOwnerUndecided) owner = claimant;   // InterlockedCompareExchange(&g_owner, claimant, undecided)
            std::printf("%s -> owner=%s\n", argv[i], ClaimOwner(prev, claimant) == kOwnerWatchdog ? "watchdog" : "game");
        }
        return 0;
    }
    if (mode == "hotkey") {
        unsigned m = 0, v = 0;
        if (!ParseHotkey(argc > 2 ? argv[2] : "", &m, &v)) { std::printf("off\n"); return 0; }
        char name[48];
        FormatHotkey(m, v, name, sizeof name);
        std::printf("ok mods=%u vk=%u name=%s\n", m, v, name);
        return 0;
    }
    return 2;
}
