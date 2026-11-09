// uimod display-mode watchdog (see vidwatch.h, vidsafety.h).
//
// The game thread is the only one that can place the game window, and it can stall: inside a driver call during a
// GPU reset, or in a long engine loop. While it holds the pointer clip, a topmost window or the letterbox backdrop,
// a stall leaves the user unable to reach anything else. This thread:
//
//   * owns the backdrop window when it came up in time (decided once, vidsafety::ClaimOwner), so it can always hide
//     it: a window can only be shown / hidden / destroyed promptly by its own thread;
//   * receives the display broadcasts on a hidden top-level window of its own (a stalled game thread may never see
//     them) and releases at once on a real topology change -- a device / work-area notice only when the monitor set
//     changed, never PRACX's own display-mode switch;
//   * probes the game thread every kWatchPeriodMs (a WM_NULL our subclass answers, never PRACX's or the engine's
//     code) and logs every stall of kWatchStallLogMs or more with its length. A stall releases NOTHING: AI turns, map
//     generation and loads stop the game thread pumping for seconds while it keeps drawing, and Windows' own hung
//     test calls a 5 s AI turn "not responding" (vidsafety.h, the watchdog section);
//   * owns the escape hotkey ([UIMod] EscapeHotkey, default Ctrl+Alt+Shift+End): release + minimise -- the user's
//     way out of a game thread that truly hangs.
//
// "Release" = ClipCursor(nullptr) when the clip is ours (works from any thread) and the backdrop hidden -- both for
// real, at once. The game window is also asked to leave the topmost band and (hotkey) to minimise, but those
// requests (SWP_ASYNCWINDOWPOS, ShowWindowAsync) are queued to the game thread: under a real hang they only happen
// when it runs again. Against a hung topmost game window the user has Ctrl+Alt+Del -> Task Manager -> End task
// (Windows' ghost window is off for this process: init.cpp, so a busy game is never swapped for a frozen copy). The
// game thread re-states its own state when it answers again. Nothing here calls engine or PRACX code.

#include "vidwatch.h"
#include "gpuscale.h"
#include "vidmode.h"

#include <cstdarg>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

HWND g_game = nullptr;
HWND g_ctl = nullptr;                  // hidden top-level window: display broadcasts + WM_HOTKEY
HWND g_backdrop = nullptr;             // made by this thread; given out only when g_owner == kOwnerWatchdog
volatile LONG g_owner = vidsafety::kOwnerUndecided;
HANDLE g_stop = nullptr, g_ready = nullptr;
volatile LONG* g_clipped = nullptr;
volatile LONG* g_resync = nullptr;
volatile LONG g_escapeGen = 0;
volatile LONG g_displaySeq = 0;
unsigned g_hotMods = 0, g_hotVk = 0;
char g_hotName[48] = {};
constexpr int kHotkeyId = 0x5AFE;
vidsafety::Monitor g_known[vidsafety::kMaxMonitors];   // the monitor set as this thread last accepted it
int g_nKnown = -1;

void Log(const char* fmt, ...)
{
    char body[256];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(body, sizeof body, _TRUNCATE, fmt, ap);
    va_end(ap);
    char line[300];
    _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] vidwatch: %s\n", body);
    UimodLog(line);
}

bool Topmost(HWND h)
{
    return h && (GetWindowLongA(h, GWL_EXSTYLE) & WS_EX_TOPMOST) != 0;
}

HWND OwnedBackdrop()
{
    return g_owner == vidsafety::kOwnerWatchdog ? g_backdrop : nullptr;
}

// Something that can keep the user from the rest of the desktop: the clip, a topmost game window, a topmost backdrop.
// (A Borderless backdrop sits in the normal band: other windows come over it.)
bool Danger()
{
    const HWND bd = OwnedBackdrop();
    return (g_clipped && *g_clipped) || Topmost(g_game) || (bd && IsWindowVisible(bd) && Topmost(bd));
}

// Undo what the game thread holds. `why` for the log; `minimise` = the escape hotkey.
void Release(const char* why, bool minimise)
{
    char done[200] = {};
    if (g_clipped && InterlockedExchange(g_clipped, 0)) { ClipCursor(nullptr); strncat_s(done, " clip released;", _TRUNCATE); }
    else if (minimise) ClipCursor(nullptr);                  // the user asked: whoever set it
    const HWND bd = OwnedBackdrop();
    if (bd && IsWindowVisible(bd)) {
        ShowWindow(bd, SW_HIDE);                             // ours: synchronous, never waits on the game thread
        strncat_s(done, " backdrop hidden;", _TRUNCATE);
    }
    if (Topmost(g_game)) {
        // queued to the game thread: takes effect only when it runs again
        SetWindowPos(g_game, HWND_NOTOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_ASYNCWINDOWPOS);
        strncat_s(done, " leave-topmost queued to the game thread;", _TRUNCATE);
    }
    if (minimise && g_game) {
        ShowWindowAsync(g_game, SW_MINIMIZE);
        strncat_s(done, " minimise queued to the game thread;", _TRUNCATE);
    }
    if (g_resync) InterlockedExchange(g_resync, 1);
    Log("%s ->%s", why, done[0] ? done : " nothing was held");
}

// Take the monitor set as it is now (rects, names; no device paths). True = it differs from the last one taken.
bool Resnapshot()
{
    vidsafety::Monitor now[vidsafety::kMaxMonitors];
    const int n = VidEnumMonitors(now, nullptr, vidsafety::kMaxMonitors, false);
    const bool same = g_nKnown >= 0 && vidsafety::SameMonitorSet(now, n, g_known, g_nKnown);
    for (int i = 0; i < n; ++i) g_known[i] = now[i];
    g_nKnown = n;
    return !same;
}

LRESULT CALLBACK CtlProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_HOTKEY && wp == kHotkeyId) {
        InterlockedIncrement(&g_escapeGen);
        Release("escape hotkey", true);
        return 0;
    }
    if (vidsafety::IsDisplayEvent(msg, wp)) {
        // WM_DISPLAYCHANGE / the DPI messages always count (unless PRACX's own switch caused them) and release BEFORE
        // the monitor list is read; a device / work-area notice counts only when the set changed (vidsafety.h)
        const bool always = !vidsafety::NeedsMonitorCheck(msg, wp);
        const bool counts = always ? !VidModeOwnDisplaySwitch() : Resnapshot() && !VidModeOwnDisplaySwitch();
        if (counts) {
            InterlockedIncrement(&g_displaySeq);
            // only when something is held: a burst of notices must not fill the log
            if (Danger()) Release(vidsafety::EventName(msg, wp), false);
            GpuDisplayEvent();
        }
        if (always) Resnapshot();
    }
    return DefWindowProcA(hwnd, msg, wp, lp);
}

DWORD WINAPI WatchThread(LPVOID)
{
    WNDCLASSA wc = {};
    wc.lpfnWndProc = CtlProc;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.lpszClassName = "uimodWatch";
    RegisterClassA(&wc);
    // top-level (not HWND_MESSAGE): only top-level windows receive the display broadcasts
    g_ctl = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, wc.lpszClassName, "", WS_POPUP, 0, 0, 0, 0,
                            nullptr, nullptr, wc.hInstance, nullptr);
    HWND bd = g_ctl ? CreateBackdropWindow() : nullptr;
    // the one decision on who owns the backdrop: a game thread that already gave up on us keeps its own. Published
    // before the claim, so a game thread that sees kOwnerWatchdog always finds the window.
    g_backdrop = bd;
    const LONG prev = InterlockedCompareExchange(&g_owner, bd ? vidsafety::kOwnerWatchdog : vidsafety::kOwnerGame,
                                                 vidsafety::kOwnerUndecided);
    const bool mine = vidsafety::ClaimOwner(prev, bd ? vidsafety::kOwnerWatchdog : vidsafety::kOwnerGame) == vidsafety::kOwnerWatchdog;
    if (!mine && bd) { g_backdrop = nullptr; DestroyWindow(bd); bd = nullptr; }
    bool hot = false;
    if (g_ctl && g_hotVk) hot = RegisterHotKey(g_ctl, kHotkeyId, g_hotMods | MOD_NOREPEAT, g_hotVk) != 0;
    const DWORD hotErr = GetLastError();
    g_nKnown = VidEnumMonitors(g_known, nullptr, vidsafety::kMaxMonitors, false);
    SetEvent(g_ready);
    if (!g_ctl) return 1;
    if (!mine) Log("came up after the game thread made its own backdrop -> watchdog and hotkey only");
    if (g_hotVk)
        Log(hot ? "escape hotkey %s registered (releases the pointer and the backdrop, minimises the game)"
                : "escape hotkey %s NOT registered (error %lu: another program holds it) -- set [UIMod] EscapeHotkey",
            g_hotName, hotErr);
    else
        Log("escape hotkey off ([UIMod] EscapeHotkey)");

    vidsafety::Watch watch;
    DWORD lastProbe = GetTickCount();
    for (;;) {
        const DWORD r = MsgWaitForMultipleObjects(1, &g_stop, FALSE, vidsafety::kWatchPeriodMs, QS_ALLINPUT);
        if (r == WAIT_OBJECT_0) break;
        MSG m;
        while (PeekMessageA(&m, nullptr, 0, 0, PM_REMOVE)) DispatchMessageA(&m);
        const DWORD now = GetTickCount();
        if (now - lastProbe < vidsafety::kWatchPeriodMs) continue;
        lastProbe = now;
        const HWND game = g_game;
        if (!game || !IsWindow(game)) continue;
        DWORD_PTR res = 0;
        // no SMTO_BLOCK: while it waits this thread still answers the game thread's calls on the backdrop. A probe
        // that timed out is still delivered when the game thread runs again (a stale probe): the subclass answers it
        // without side effects beyond arming its own timer once, and only after a release (hotkey / display event).
        const bool answered = SendMessageTimeoutA(game, WM_NULL, kWatchProbeW, kWatchProbeL, SMTO_ABORTIFHUNG,
                                                  vidsafety::kWatchProbeMs, &res) != 0;
        // measured only: a stall releases nothing (vidsafety.h, the watchdog section)
        if (watch.Step(GetTickCount(), answered) == vidsafety::kWatchStall)
            Log("the game thread did not answer for %lu ms (nothing released)", static_cast<unsigned long>(watch.stallMs));
    }
    if (g_hotVk) UnregisterHotKey(g_ctl, kHotkeyId);
    if (mine && g_backdrop) {
        const HWND b = g_backdrop;
        g_backdrop = nullptr;
        DestroyWindow(b);
    }
    DestroyWindow(g_ctl);
    g_ctl = nullptr;
    return 0;
}

LRESULT CALLBACK BackdropProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
    return DefWindowProcA(hwnd, msg, wp, lp);
}

struct EnumState {
    vidsafety::Monitor* out;
    HMONITOR* handles;
    int max, n;
    bool paths;
};

BOOL CALLBACK AddMonitor(HMONITOR h, HDC, LPRECT, LPARAM lp)
{
    EnumState& s = *reinterpret_cast<EnumState*>(lp);
    if (s.n >= s.max) return FALSE;
    MONITORINFOEXA mi;
    mi.cbSize = sizeof mi;
    if (!GetMonitorInfoA(h, &mi)) return TRUE;
    vidsafety::Monitor& m = s.out[s.n];
    m = vidsafety::Monitor();
    m.rc = { mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right, mi.rcMonitor.bottom };
    m.primary = (mi.dwFlags & MONITORINFOF_PRIMARY) != 0;
    strncpy_s(m.name, mi.szDevice, _TRUNCATE);
    // the monitor on this output: its device interface path (what CCD calls monitorDevicePath) -- asked for only
    DISPLAY_DEVICEA dd;
    for (DWORD i = 0; s.paths; ++i) {
        dd.cb = sizeof dd;
        if (!EnumDisplayDevicesA(mi.szDevice, i, &dd, EDD_GET_DEVICE_INTERFACE_NAME)) break;
        if (dd.StateFlags & DISPLAY_DEVICE_ACTIVE) { strncpy_s(m.path, dd.DeviceID, _TRUNCATE); break; }
    }
    if (s.handles) s.handles[s.n] = h;
    ++s.n;
    return TRUE;
}

} // namespace

int VidEnumMonitors(vidsafety::Monitor* out, HMONITOR* handles, int max, bool withPaths)
{
    EnumState s = { out, handles, max, 0, withPaths };
    EnumDisplayMonitors(nullptr, nullptr, AddMonitor, reinterpret_cast<LPARAM>(&s));
    return s.n;
}

HWND CreateBackdropWindow()
{
    WNDCLASSA wc = {};
    wc.lpfnWndProc = BackdropProc;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.hbrBackground = static_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
    wc.lpszClassName = "uimodBackdrop";
    RegisterClassA(&wc);                 // a second call fails harmlessly: the class exists
    return CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, wc.lpszClassName, "", WS_POPUP, 0, 0, 0, 0,
                           nullptr, nullptr, wc.hInstance, nullptr);
}

bool VidWatchStart(HWND game, volatile LONG* clipped, volatile LONG* resyncOwed, const char* hotkey)
{
    if (g_stop) return g_owner == vidsafety::kOwnerWatchdog;
    g_game = game;
    g_clipped = clipped;
    g_resync = resyncOwed;
    if (vidsafety::ParseHotkey(hotkey, &g_hotMods, &g_hotVk)) {
        vidsafety::FormatHotkey(g_hotMods, g_hotVk, g_hotName, sizeof g_hotName);
    } else {
        g_hotMods = g_hotVk = 0;
        const bool off = !hotkey || !hotkey[0] || !_stricmp(hotkey, "off") || !_stricmp(hotkey, "none") || !strcmp(hotkey, "0");
        if (!off) Log("[UIMod] EscapeHotkey=%s not understood (e.g. Ctrl+Alt+Shift+End; a key needs a modifier) -> off", hotkey);
    }
    g_stop = CreateEventA(nullptr, TRUE, FALSE, nullptr);
    g_ready = CreateEventA(nullptr, TRUE, FALSE, nullptr);
    const HANDLE th = g_stop && g_ready ? CreateThread(nullptr, 64 * 1024, WatchThread, nullptr, 0, nullptr) : nullptr;
    if (!th) {
        InterlockedExchange(&g_owner, vidsafety::kOwnerGame);
        Log("could not start (%lu) -> backdrop on the game thread, no watchdog, no escape hotkey", GetLastError());
        return false;
    }
    CloseHandle(th);
    // the thread only creates two windows; a game thread that waited longer would be the stall this guards against
    WaitForSingleObject(g_ready, 2000);
    // decided once: whoever claims first. If the thread has not claimed by now, the game thread owns the backdrop and
    // a late thread destroys its own.
    const LONG prev = InterlockedCompareExchange(&g_owner, vidsafety::kOwnerGame, vidsafety::kOwnerUndecided);
    if (vidsafety::ClaimOwner(prev, vidsafety::kOwnerGame) != vidsafety::kOwnerWatchdog) {
        Log("did not come up in 2 s -> the backdrop stays on the game thread");
        return false;
    }
    Log("up (releases on a display change or the escape hotkey; probes the game thread every %u ms and logs its "
        "stalls, releasing nothing on one)", static_cast<unsigned>(vidsafety::kWatchPeriodMs));
    return true;
}

void VidWatchStop()
{
    if (g_stop) SetEvent(g_stop);       // the thread destroys its own windows; never waited on from the game thread
    g_game = nullptr;
}

HWND VidWatchBackdrop() { return OwnedBackdrop(); }
bool VidWatchOwnsBackdrop() { return g_owner == vidsafety::kOwnerWatchdog; }
LONG VidWatchEscapeGen() { return g_escapeGen; }
LONG VidWatchDisplaySeq() { return g_displaySeq; }
LONG VidWatchBumpDisplaySeq() { return InterlockedIncrement(&g_displaySeq); }
