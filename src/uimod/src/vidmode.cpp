// uimod display mode: Fullscreen / Borderless / Windowed.
//
// The game is hard to record: vanilla takes the display exclusively and PRACX, which replaces that
// with a GDI-presented desktop-size popup, only offers an unpersisted Alt+Enter window. This module
// adds a persisted three-way mode on top of PRACX's own window code:
//
//   Fullscreen  the game owns the screen: topmost, minimised when the app loses focus, the pointer
//               held inside the window (PRACX never clips it: on a second monitor the game's screen
//               edge is open, so the pointer walks off the game and edge scrolling stops there;
//               [UIMod] ConstrainMouse=0 / the Preferences row "Constrain Mouse to Window" lets it). When
//               [PRACX] ScreenWidth x ScreenHeight is the monitor's own size this is PRACX's default
//               (m_fWindowed = 0, WS_POPUP). When it is not, the monitor STAYS in its own mode and
//               the game is our scaled popup (below) made topmost --
//               PRACX's display-mode switch (ChangeDisplaySettings to the game's resolution) is
//               suppressed: the driver has to invent an output timing for a resolution the monitor
//               does not list, and some monitors run that timing badly (black-outs, pixel judder);
//               it also blanked the monitor after every cinematic and on every minimise/restore.
//               [UIMod] FullscreenModeSwitch=1 keeps PRACX's real switch (the developer capture
//               scripts set it: a screen capture at the game's own resolution needs the desktop in
//               that mode).
//   Windowed    PRACX's SetWindowed(true): a captioned window; PRACX StretchBlts the backbuffer into
//               the client area and maps the mouse back (both gated on m_fWindowed).
//   Borderless  ours: m_fWindowed = 1 (so that stretch + mouse mapping stay in force) with a
//               WS_POPUP window, not topmost, no display mode change, no minimise on focus loss.
//               The window is the largest backbuffer-aspect rect centred on its monitor (uniform
//               scale only); when that leaves bars, a black backdrop window fills the monitor.
//
// The backbuffer (ScreenWidth x ScreenHeight) never changes, so the UI scale and every scaled
// layout are untouched by a mode switch -- it is safe to apply live.
//
// PRACX keeps its state private, so we bind to prax.dll by offset behind a byte check (the
// SetWindowed prologue, its two window-style immediates and its relocated m_fWindowed reference).
// A prax.dll that does not match disables the feature; without PRACX there is no windowed present
// path at all and the feature is off.
//
// The mode the Preferences page shows is always DETECTED from the live window (m_fWindowed + the
// window style + which popup we applied), so Alt+Enter, PRACX's menu item and a hand-edited ini all
// show correctly. [UIMod] VideoMode is only what the next boot applies.
//
// Display-topology safety (vidsafety.h has the rules and their history; vidwatch.cpp the watchdog thread):
// a monitor appearing, vanishing, changing mode or scaling releases the pointer clip, the topmost band and
// the backdrop at once, and the game's state is restored on the user's monitor only once the display has
// been quiet for 1.5 s and the game is the foreground window. Only PRACX's own SetWindowed(false)
// converges; a system reposition never does.

#include "vidmode.h"
#include "gpuscale.h"
#include "movie.h"
#include "vidsafety.h"
#include "vidwatch.h"
#include "winlines.h"

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <dbt.h>
#include <vector>

void UimodLog(const char* msg);

static_assert(vidsafety::kWM_SETTINGCHANGE == WM_SETTINGCHANGE && vidsafety::kWM_DISPLAYCHANGE == WM_DISPLAYCHANGE &&
              vidsafety::kWM_DEVICECHANGE == WM_DEVICECHANGE && vidsafety::kWM_DPICHANGED == 0x02E0 &&
              vidsafety::kDBT_DEVNODES_CHANGED == DBT_DEVNODES_CHANGED && vidsafety::kSPI_SETWORKAREA == SPI_SETWORKAREA,
              "vidsafety.h's message numbers are the SDK's");
static_assert(vidsafety::kMOD_ALT == MOD_ALT && vidsafety::kMOD_CONTROL == MOD_CONTROL && vidsafety::kMOD_SHIFT == MOD_SHIFT &&
              vidsafety::kMOD_WIN == MOD_WIN, "vidsafety.h's hotkey modifiers are the SDK's");
static_assert(static_cast<int>(vidsafety::kFullscreen) == kVidFullscreen && static_cast<int>(vidsafety::kBorderless) == kVidBorderless &&
              static_cast<int>(vidsafety::kWindowed) == kVidWindowed, "vidsafety::Mode is VidMode");

namespace {

constexpr uintptr_t kImageBase  = 0x400000;
constexpr uintptr_t kVA_phWnd   = 0x009B7B28;   // HWND  g_main_hwnd
constexpr uintptr_t kVA_ScreenW = 0x009B7B1C;   // int   ScreenWidth  (backbuffer)
constexpr uintptr_t kVA_ScreenH = 0x009B7B20;   // int   ScreenHeight
constexpr uintptr_t kVA_ScreenBufH = 0x009B7514; // int   screen Buffer height, NEGATIVE = top-down DIB
constexpr uintptr_t kVA_FlipBlt = 0x005F018B;   // Win_flip_rect's display BitBlt: PRACX makes it `E8 rel32; nop` -> PRACXWindowBitBlt

// prax.dll offsets (image base 0x10000000; PRACX 1.11, md5 89a0037b stock / 0f189a32 with our patch)
constexpr uintptr_t kPx_SetWindowed   = 0x09F60;   // void __cdecl SetWindowed(bool)
constexpr uintptr_t kPx_fWindowedRef  = 0x09F81;   // abs32 of m_fWindowed inside its first movzx
constexpr uintptr_t kPx_PushWindowed  = 0x0A0AA;   // push 0x02CF0000 (AC_WS_WINDOWED)
constexpr uintptr_t kPx_PushFull      = 0x0A143;   // push 0x82000000 (AC_WS_FULLSCREEN)
constexpr uintptr_t kPx_fWindowed     = 0x4809C;   // bool m_fWindowed
constexpr uintptr_t kPx_rWindowedRect = 0x480A0;   // RECT m_rWindowedRect (WINDOWPLACEMENT.rcNormalPosition)
constexpr uintptr_t kPx_CdsSlot       = 0x341BC;   // IAT slot: user32!ChangeDisplaySettingsA (PRACX's only mode-switch call)
constexpr uintptr_t kPx_RestoreVideo  = 0x09940;   // void RestoreVideoMode(): push ebp; mov ebp,esp; push 0; push 0; call [kPx_CdsSlot]
constexpr uintptr_t kPx_SetVideo      = 0x09ED0;   // void SetVideoMode(): push ebp; mov ebp,esp; sub esp,0x9C

constexpr DWORD kStyleWindowed   = WS_OVERLAPPED | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_CAPTION |
                                   WS_THICKFRAME | WS_SYSMENU | WS_CLIPCHILDREN;   // PRACX AC_WS_WINDOWED
constexpr DWORD kStyleBorderless = WS_POPUP | WS_CLIPCHILDREN;
constexpr UINT  kWM_PracxWindowed = WM_USER + 3;   // PRACX: place the window at m_rWindowedRect
constexpr UINT  kWM_Converge = WM_APP + 0x51;      // ours: PRACX dropped m_fWindowed under a scaled Fullscreen -> re-apply
constexpr int   kMinClientW = 320;

using FSetWindowed = void(__cdecl*)(int);
using FChangeDisplaySettings = LONG(WINAPI*)(DEVMODEA*, DWORD);

FSetWindowed g_setWindowed = nullptr;
BYTE*   g_fWindowed = nullptr;
RECT*   g_rWindowed = nullptr;
WNDPROC g_prevProc = nullptr;
HWND    g_hwnd = nullptr;
bool    g_booted = false;
bool    g_preHooked = false;         // the switch was suppressed in VidModePreInit, before PRACX's init
bool    g_closing = false;             // the window is going away: style churn from here on is not a mode choice
int     g_pendingPopup = -1;           // kVidBorderless / kVidFullscreen: the popup mode being applied (SetWindowed(true)
                                       // issued and PRACX's WM_USER+3 not yet handled, or ApplyPopup in progress)
bool    g_switchAllowed = false;       // [UIMod] FullscreenModeSwitch: PRACX's real display-mode switch
volatile LONG g_clipped = 0;           // ClipCursor is ours (the watchdog thread releases it too)
bool    g_clipWanted = true;           // [UIMod] ConstrainMouse: Fullscreen holds the pointer inside the window
int     g_popupKind = -1;              // kVidFullscreen / kVidBorderless: the popup ApplyPopup made (-1 = none); what
                                       // VidModeDetect reports for a captionless m_fWindowed=1 window (never WS_EX_TOPMOST,
                                       // which the safety layer drops whenever the game is not the foreground window)
bool    g_ownSetWindowed = false;      // our own call into PRACX's SetWindowed is running
bool    g_inRestore = false;           // the display-topology restore is placing the window (not the user's choice)
bool    g_haveTarget = false;          // the next ApplyPopup goes onto g_target, not the window's nearest monitor
RECT    g_target = {};
vidsafety::Controller g_safe;
volatile LONG g_resyncOwed = 0;        // the watchdog released something: re-state it when the game thread answers
LONG    g_dispSeqSeen = 0;             // VidWatchDisplaySeq() as this thread last accounted for it
bool    g_timerOn = false;
constexpr UINT_PTR kSafetyTimer = 0x55AFE;   // our WM_TIMER on the game window (handled in the subclass, never forwarded)
HWND    g_ownBackdrop = nullptr;       // the fallback backdrop on this thread, when the watchdog is not running
RECT    g_bdRect = {};                 // where the backdrop was last shown, and in which band
bool    g_bdTop = false;
void  (*g_onChange)() = nullptr;      // the Preferences page's "mode changed" notification
int     g_lastMode = kVidFullscreen;
RECT    g_winRect = {};                // the last good windowed placement
int     g_borderW = 0, g_borderH = 0;  // the borderless window size (to recognise it in m_rWindowedRect)

template <typename T> T Rd(uintptr_t va)
{
    return *reinterpret_cast<T*>(reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase));
}

void IniPath(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    if (char* slash = strrchr(out, '\\')) slash[1] = '\0';
    lstrcatA(out, "Alpha Centauri.ini");
}

int LoadMode()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    const int m = static_cast<int>(GetPrivateProfileIntA("UIMod", "VideoMode", kVidModeDefault, ini));
    return m >= kVidFullscreen && m <= kVidWindowed ? m : kVidModeDefault;
}

const char* ModeName(int m)
{
    return m == kVidWindowed ? "windowed" : m == kVidBorderless ? "borderless" : "fullscreen";
}

// Fullscreen has to be the scaled popup when the backbuffer is not the size of the monitor the window
// is on (there PRACX would switch the display mode) and the switch is not allowed.
bool NeedsScaledFullscreen(HWND hwnd)
{
    if (g_switchAllowed) return false;
    const int sw = Rd<int>(kVA_ScreenW), sh = Rd<int>(kVA_ScreenH);
    if (sw <= 0 || sh <= 0) return false;
    const POINT origin = { 0, 0 };
    const HMONITOR mon = hwnd ? MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                              : MonitorFromPoint(origin, MONITOR_DEFAULTTOPRIMARY);
    MONITORINFO mi = { sizeof mi };
    if (!GetMonitorInfoA(mon, &mi)) return false;
    const vidsafety::Rect r = { mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right, mi.rcMonitor.bottom };
    return vidsafety::NeedsScaled(r, sw, sh, false);
}

void Logf(const char* fmt, ...)
{
    char body[256];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(body, sizeof body, _TRUNCATE, fmt, ap);
    va_end(ap);
    char line[300];
    _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] vidmode: %s\n", body);
    UimodLog(line);
}

// ---- display-mode switch suppression -----------------------------------------------------------
// PRACX's only route to a display-mode switch is user32!ChangeDisplaySettingsA through one IAT slot
// (SetVideoMode: CDS_FULLSCREEN to ScreenWidth x ScreenHeight; RestoreVideoMode: back to the desktop).
// It is called at PRACX's hook time (before this DLL loads), after every cinematic, on minimise /
// restore and on every windowed -> fullscreen switch. With the switch suppressed the slot points at a
// no-op; PRACX never reads the result. Byte-checked like the rest of the binding.
LONG WINAPI NoDisplaySwitch(DEVMODEA*, DWORD)
{
    return DISP_CHANGE_SUCCESSFUL;
}

// [UIMod] FullscreenModeSwitch=1 (developer captures): PRACX's real switch goes through, but marked, so the display
// messages it causes (on every minimise / restore) are not taken for a monitor topology change. ChangeDisplaySettings
// broadcasts WM_DISPLAYCHANGE before it returns; kOwnSwitchGraceMs covers the stragglers.
FChangeDisplaySettings g_realCds = nullptr;
volatile LONG g_ownCdsDepth = 0;
volatile LONG g_ownCdsAt = 0;
volatile LONG g_ownCdsEver = 0;
constexpr DWORD kOwnSwitchGraceMs = 1000;

LONG WINAPI MarkedDisplaySwitch(DEVMODEA* dm, DWORD flags)
{
    InterlockedIncrement(&g_ownCdsDepth);
    const LONG r = g_realCds ? g_realCds(dm, flags) : DISP_CHANGE_FAILED;
    InterlockedExchange(&g_ownCdsAt, static_cast<LONG>(GetTickCount()));
    InterlockedExchange(&g_ownCdsEver, 1);
    InterlockedDecrement(&g_ownCdsDepth);
    return r;
}

bool HookDisplaySwitch(const BYTE* px, FChangeDisplaySettings with = &NoDisplaySwitch)
{
    static const BYTE restorePro[9] = { 0x55, 0x8B, 0xEC, 0x6A, 0x00, 0x6A, 0x00, 0xFF, 0x15 };
    static const BYTE setPro[9]     = { 0x55, 0x8B, 0xEC, 0x81, 0xEC, 0x9C, 0x00, 0x00, 0x00 };
    FARPROC* slot = reinterpret_cast<FARPROC*>(const_cast<BYTE*>(px) + kPx_CdsSlot);
    DWORD ref;
    memcpy(&ref, px + kPx_RestoreVideo + 9, sizeof ref);     // the call's abs32 operand = the slot
    const HMODULE user32 = GetModuleHandleA("user32.dll");
    const FARPROC real = user32 ? GetProcAddress(user32, "ChangeDisplaySettingsA") : nullptr;
    if (memcmp(px + kPx_RestoreVideo, restorePro, 9) != 0 || memcmp(px + kPx_SetVideo, setPro, 9) != 0 ||
        ref != reinterpret_cast<DWORD>(slot) || !real || *slot != real)
        return false;
    DWORD prot;
    if (!VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &prot)) return false;
    g_realCds = reinterpret_cast<FChangeDisplaySettings>(real);
    *slot = reinterpret_cast<FARPROC>(with);
    VirtualProtect(slot, sizeof *slot, prot, &prot);
    return true;
}

// Fullscreen holds the pointer inside the game window (the screen edge of a real fullscreen: edge
// scrolling works at pillarbox bars too). Released whenever the window is not the active one.
void ClipToWindow(HWND hwnd, bool on)
{
    static RECT last = {};
    RECT r;
    if (on && GetWindowRect(hwnd, &r) && ClipCursor(&r)) {
        if (!InterlockedExchange(&g_clipped, 1) || !EqualRect(&r, &last))
            Logf("clip: pointer held in %ld,%ld %ldx%ld", r.left, r.top, r.right - r.left, r.bottom - r.top);
        last = r;
        return;
    }
    if (InterlockedExchange(&g_clipped, 0)) {
        ClipCursor(nullptr);
        SetRectEmpty(&last);
        Logf("clip: released");
    }
}

bool FullscreenRunning();
void SafetySync(HWND hwnd);

// PRACX switched the desktop at its hook time iff the current mode is the ini's ScreenWidth x ScreenHeight
// and differs from the registry mode. (Not every current != registry: another program's temporary mode
// is not ours to undo.)
bool PracxSwitchedDesktop(const char* ini)
{
    DEVMODEA cur = {}, reg = {};
    cur.dmSize = reg.dmSize = sizeof(DEVMODEA);
    if (!EnumDisplaySettingsA(nullptr, ENUM_CURRENT_SETTINGS, &cur) || !EnumDisplaySettingsA(nullptr, ENUM_REGISTRY_SETTINGS, &reg))
        return false;
    if (cur.dmPelsWidth == reg.dmPelsWidth && cur.dmPelsHeight == reg.dmPelsHeight) return false;
    const UINT w = GetPrivateProfileIntA("PRACX", "ScreenWidth", 0, ini);    // "<DEFAULT>" reads as 0: no switch then
    const UINT h = GetPrivateProfileIntA("PRACX", "ScreenHeight", 0, ini);
    return w == cur.dmPelsWidth && h == cur.dmPelsHeight;
}

// PRACX saves the window's placement into m_rWindowedRect whenever it leaves its windowed state --
// including when that state was our borderless window. Put the real windowed placement back.
void FixWindowedRect()
{
    if (!g_borderW) return;
    if (g_rWindowed->right - g_rWindowed->left == g_borderW && g_rWindowed->bottom - g_rWindowed->top == g_borderH)
        *g_rWindowed = g_winRect;
}

// The largest ScreenWidth:ScreenHeight rect centred in `mon`.
RECT FitMonitor(const RECT& mon)
{
    const vidsafety::Rect f = vidsafety::FitRect({ mon.left, mon.top, mon.right, mon.bottom }, Rd<int>(kVA_ScreenW),
                                                 Rd<int>(kVA_ScreenH));
    const RECT r = { f.l, f.t, f.r, f.b };
    return r;
}

// ---- the scaled present ------------------------------------------------------------------------
// GDI's HALFTONE StretchBlt is far too slow for a game frame (a full 4K flip per mouse move while the
// move-path line is drawn took the game to a crawl), and COLORONCOLOR drops rows and columns of text.
// So the stretched modes resample the 8-bit backbuffer themselves into a client-size 32-bit surface:
// separable, area-average when shrinking, bilinear when enlarging, palette looked up from the
// backbuffer DIB's own colour table (what GDI itself would blit with). Every dest pixel is computed
// from the WHOLE-FRAME tap table, so a dirty-rect update is bit-identical to a full-frame one -- no
// seams at update edges.

constexpr int kMaxTaps = 8;            // shrink ratios up to 6:1; beyond that GDI does it

struct Axis {
    int srcN = 0, dstN = 0;
    std::vector<int>      start;       // first source index per dest index
    std::vector<uint8_t>  count;       // taps per dest index
    std::vector<uint16_t> weight;      // kMaxTaps per dest index, summing to 256
    bool ok = false;

    void Build(int src, int dst)
    {
        if (src == srcN && dst == dstN) return;
        srcN = src; dstN = dst; ok = false;
        start.assign(dst, 0); count.assign(dst, 0); weight.assign(static_cast<size_t>(dst) * kMaxTaps, 0);
        for (int d = 0; d < dst; ++d) {
            uint16_t* w = &weight[static_cast<size_t>(d) * kMaxTaps];
            if (dst < src) {           // area average over [a, b) in 1/256 source pixels
                const long long a = static_cast<long long>(d) * src * 256 / dst;
                const long long b = static_cast<long long>(d + 1) * src * 256 / dst;
                const int first = static_cast<int>(a >> 8), last = static_cast<int>((b - 1) >> 8);
                const int n = last - first + 1;
                if (n > kMaxTaps) return;
                int sum = 0, big = 0;
                for (int k = 0; k < n; ++k) {
                    const long long lo = (first + k) * 256LL > a ? (first + k) * 256LL : a;
                    const long long hi = (first + k + 1) * 256LL < b ? (first + k + 1) * 256LL : b;
                    w[k] = static_cast<uint16_t>((hi - lo) * 256 / (b - a));
                    sum += w[k];
                    if (w[k] > w[big]) big = k;
                }
                w[big] = static_cast<uint16_t>(w[big] + 256 - sum);
                start[d] = first; count[d] = static_cast<uint8_t>(n);
            } else {                   // bilinear, pixel centres aligned
                long long pos = (2LL * d + 1) * src * 256 / (2LL * dst) - 128;
                if (pos < 0) pos = 0;
                int i0 = static_cast<int>(pos >> 8);
                const int f = static_cast<int>(pos & 255);
                if (i0 >= src - 1) { i0 = src - 1; w[0] = 256; count[d] = 1; }
                else { w[0] = static_cast<uint16_t>(256 - f); w[1] = static_cast<uint16_t>(f); count[d] = 2; }
                start[d] = i0;
            }
        }
        ok = true;
    }

    // dest range [lo, hi) whose taps touch source range [l, r)
    void Cover(int l, int r, int* lo, int* hi) const
    {
        int a = static_cast<int>(static_cast<long long>(l) * dstN / srcN) - 2;
        int b = static_cast<int>((static_cast<long long>(r) * dstN + srcN - 1) / srcN) + 2;
        if (a < 0) a = 0;
        if (b > dstN) b = dstN;
        while (a < b && start[a] + count[a] <= l) ++a;
        while (b > a && start[b - 1] >= r) --b;
        *lo = a; *hi = b;
    }
};

Axis g_ax, g_ay;
HDC     g_surfDC = nullptr;
HBITMAP g_surfBmp = nullptr, g_surfOld = nullptr;
uint32_t* g_surf = nullptr;
int g_surfW = 0, g_surfH = 0;
constexpr int kRowSlots = 16;
constexpr int kMaxWorkers = 7;         // + the game thread
constexpr int kParallelMinPixels = 200000;   // smaller updates are not worth waking the pool for

struct RowCache { std::vector<uint32_t> rb[kRowSlots], g[kRowSlots]; };

// One resample job, shared read-only by every thread working on it.
struct Job {
    const BYTE* bits; int stride, bmpH; bool bottomUp;
    const uint32_t* palRB; const uint32_t* palG;
    int dl, dr, dt, db, cw;
    int bands;
};
Job g_job;
volatile LONG g_nextBand = 0;
RowCache g_cache[kMaxWorkers + 1];     // [0] = the game thread
HANDLE g_start[kMaxWorkers], g_done[kMaxWorkers];
int    g_workers = -1;                 // -1 = pool not created yet
volatile LONG g_alive[kMaxWorkers] = {};   // the worker has run (only running workers are given a job)

// Dest rows [y0, y1) of the job: horizontal pass per source row (cached per thread), then vertical.
void ResampleRows(const Job& j, int y0, int y1, RowCache& c)
{
    const int dw = j.dr - j.dl;
    int slotY[kRowSlots];
    for (int& v : slotY) v = -1;
    for (int k = 0; k < kRowSlots; ++k)
        if (static_cast<int>(c.rb[k].size()) < dw) { c.rb[k].resize(dw); c.g[k].resize(dw); }

    auto hrow = [&](int y) -> int {    // 8-bit channels out: red | blue << 16, and green
        const int slot = y % kRowSlots;
        if (slotY[slot] == y) return slot;
        slotY[slot] = y;
        const BYTE* row = j.bits + static_cast<size_t>(j.bottomUp ? j.bmpH - 1 - y : y) * j.stride;
        uint32_t* oRB = c.rb[slot].data();
        uint32_t* oG = c.g[slot].data();
        for (int d = j.dl; d < j.dr; ++d) {
            const BYTE* sp = row + g_ax.start[d];
            const uint16_t* w = &g_ax.weight[static_cast<size_t>(d) * kMaxTaps];
            uint32_t rb = 0, g = 0;
            for (int k = 0, n = g_ax.count[d]; k < n; ++k) {
                rb += j.palRB[sp[k]] * w[k];
                g += j.palG[sp[k]] * w[k];
            }
            oRB[d - j.dl] = (rb >> 8) & 0x00FF00FF;
            oG[d - j.dl] = g >> 8;
        }
        return slot;
    };

    for (int y = y0; y < y1; ++y) {
        const uint16_t* wy = &g_ay.weight[static_cast<size_t>(y) * kMaxTaps];
        const int n = g_ay.count[y];
        const uint32_t* rRB[kMaxTaps];
        const uint32_t* rG[kMaxTaps];
        for (int k = 0; k < n; ++k) {
            const int slot = hrow(g_ay.start[y] + k);
            rRB[k] = c.rb[slot].data();
            rG[k] = c.g[slot].data();
        }
        uint32_t* out = g_surf + static_cast<size_t>(y) * j.cw + j.dl;
        for (int x = 0; x < dw; ++x) {
            uint32_t rb = 0, g = 0;
            for (int k = 0; k < n; ++k) {
                rb += rRB[k][x] * wy[k];
                g += rG[k][x] * wy[k];
            }
            out[x] = ((rb >> 8) & 0xFF) << 16 | ((g >> 8) & 0xFF) << 8 | ((rb >> 24) & 0xFF);
        }
    }
}

// Take bands of the current job until none are left.
void RunBands(RowCache& c)
{
    const Job& j = g_job;
    const int rows = j.db - j.dt;
    for (;;) {
        const int i = static_cast<int>(InterlockedIncrement(&g_nextBand)) - 1;
        if (i >= j.bands) return;
        ResampleRows(j, j.dt + static_cast<int>(static_cast<long long>(rows) * i / j.bands),
                     j.dt + static_cast<int>(static_cast<long long>(rows) * (i + 1) / j.bands), c);
    }
}

DWORD WINAPI WorkerProc(LPVOID arg)
{
    const int i = static_cast<int>(reinterpret_cast<INT_PTR>(arg));
    InterlockedExchange(&g_alive[i], 1);
    for (;;) {
        WaitForSingleObject(g_start[i], INFINITE);
        RunBands(g_cache[i + 1]);
        SetEvent(g_done[i]);
    }
}

// Created at the boot apply (VidModePoll, never under the loader lock), long before any frame. A full-frame
// resample of a 4K backbuffer is ~25 ms on one core -- per mouse move while a move path is drawn; bands across
// cores bring it to a few ms. Each job is a strict barrier: every RUNNING worker is started and awaited, so no
// worker can be inside a job while the next one is being set up. A worker counts only once it has run (g_alive): a
// new thread needs the loader lock to start, and the GPU device worker holds it while d3d11 / the driver load
// (gpuscale.cpp) -- a job that waited on a thread not yet started would wait as long as the driver does.
void EnsurePool()
{
    if (g_workers >= 0) return;
    g_workers = 0;
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    int want = static_cast<int>(si.dwNumberOfProcessors) - 1;
    if (want > kMaxWorkers) want = kMaxWorkers;
    for (int i = 0; i < want; ++i) {
        g_start[i] = CreateEventA(nullptr, FALSE, FALSE, nullptr);
        g_done[i] = CreateEventA(nullptr, FALSE, FALSE, nullptr);
        HANDLE th = (g_start[i] && g_done[i])
                        ? CreateThread(nullptr, 0, WorkerProc, reinterpret_cast<LPVOID>(static_cast<INT_PTR>(i)), 0, nullptr)
                        : nullptr;
        if (!th) break;
        CloseHandle(th);
        g_workers = i + 1;
    }
}

void RunJob()
{
    Job& j = g_job;
    const long long pixels = static_cast<long long>(j.dr - j.dl) * (j.db - j.dt);
    HANDLE done[kMaxWorkers];
    int workers = 0;
    if (pixels >= kParallelMinPixels)
        for (int i = 0; i < g_workers; ++i)
            if (g_alive[i]) done[workers++] = g_done[i];
    j.bands = workers ? (workers + 1) * 2 : 1;
    if (j.bands > j.db - j.dt) j.bands = j.db - j.dt;
    g_nextBand = 0;
    for (int i = 0, k = 0; i < g_workers && k < workers; ++i)
        if (g_done[i] == done[k]) { SetEvent(g_start[i]); ++k; }
    RunBands(g_cache[0]);
    if (workers) WaitForMultipleObjects(static_cast<DWORD>(workers), done, TRUE, INFINITE);
}

bool EnsureSurface(int w, int h)
{
    if (g_surf && w == g_surfW && h == g_surfH) return true;
    if (g_surfDC) { SelectObject(g_surfDC, g_surfOld); DeleteObject(g_surfBmp); DeleteDC(g_surfDC); }
    g_surfDC = nullptr; g_surf = nullptr; g_surfW = g_surfH = 0;
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    g_surfDC = CreateCompatibleDC(nullptr);
    g_surfBmp = g_surfDC ? CreateDIBSection(g_surfDC, &bi, DIB_RGB_COLORS, &bits, nullptr, 0) : nullptr;
    if (!g_surfBmp || !bits) {
        if (g_surfDC) DeleteDC(g_surfDC);
        g_surfDC = nullptr;
        return false;
    }
    g_surfOld = static_cast<HBITMAP>(SelectObject(g_surfDC, g_surfBmp));
    g_surf = static_cast<uint32_t*>(bits);
    g_surfW = w; g_surfH = h;
    return true;
}

// Resample source rect [l,r)x[t,b) of the 8-bit backbuffer selected into `src` and blit what it covers.
bool ScaledFlip(HWND hwnd, HDC dst, HDC src, int sw, int sh, int cw, int ch, int l, int t, int r, int b)
{
    DIBSECTION ds;
    const HGDIOBJ bmp = GetCurrentObject(src, OBJ_BITMAP);
    if (!bmp || GetObjectA(bmp, sizeof ds, &ds) != sizeof ds || ds.dsBm.bmBitsPixel != 8 || !ds.dsBm.bmBits ||
        ds.dsBm.bmWidth < sw || ds.dsBm.bmHeight < sh)
        return false;
    RGBQUAD pal[256];
    if (GetDIBColorTable(src, 0, 256, pal) != 256) return false;
    // The GPU does it when it can (gpuscale.cpp: same resampling law, a fraction of the time); the code below
    // is the fallback. Row order from the engine: negative screen Buffer height = top-down, what the GPU path takes.
    if (Rd<int>(kVA_ScreenBufH) < 0 &&
        GpuPresent(hwnd, static_cast<const BYTE*>(ds.dsBm.bmBits), ds.dsBm.bmWidthBytes, sw, sh, pal, l, t, r, b, cw, ch))
        return true;
    GpuInvalidate();                   // this update reaches the window without the GPU: its frame copy is stale
    g_ax.Build(sw, cw);
    g_ay.Build(sh, ch);
    if (!g_ax.ok || !g_ay.ok || !EnsureSurface(cw, ch)) return false;

    uint32_t palRB[256], palG[256];    // red | blue << 16, and green: a tap is two 32-bit multiply-adds
    for (int i = 0; i < 256; ++i) {
        palRB[i] = pal[i].rgbRed | static_cast<uint32_t>(pal[i].rgbBlue) << 16;
        palG[i] = pal[i].rgbGreen;
    }
    int dl, dr, dt, db;
    g_ax.Cover(l, r, &dl, &dr);
    g_ay.Cover(t, b, &dt, &db);
    if (dl >= dr || dt >= db) return true;
    const int dw = dr - dl;

    Job& j = g_job;
    j.bits = static_cast<const BYTE*>(ds.dsBm.bmBits);
    j.stride = ds.dsBm.bmWidthBytes;
    j.bmpH = ds.dsBm.bmHeight;
    // Row order comes from the ENGINE, not from GetObject: the screen buffer is a top-down DIB (its height
    // global is negative -- Win_flip_rect negates it for this very blit) yet GetObject reports biHeight > 0,
    // which drew the frame upside down.
    j.bottomUp = Rd<int>(kVA_ScreenBufH) > 0;
    j.palRB = palRB; j.palG = palG;
    j.dl = dl; j.dr = dr; j.dt = dt; j.db = db; j.cw = cw;
    GdiFlush();                        // no batched blit may still be reading the surface we are about to rewrite
    RunJob();
    return BitBlt(dst, dl, dt, dw, db - dt, g_surfDC, dl, dt, SRCCOPY) != 0;
}

// The game's display blit (Win_flip_rect: the dirty rect of the backbuffer, same coords both sides).
// PRACX's version, when windowed, ignores the rect and HALFTONE-stretches the WHOLE backbuffer into the
// client on every flip -- at a 3840x2160 backbuffer that is tens of ms per cursor move, the reason the
// game crawled in Windowed and Borderless. Ours: 1:1 client (Borderless at desktop size) is a plain
// BitBlt of the dirty rect; otherwise ScaledFlip resamples just the dirty rect. GDI's stretch is only
// the fallback for a backbuffer we do not recognise.
BOOL WINAPI FlipBlt(HDC dst, int x, int y, int w, int h, HDC src, int sx, int sy, DWORD rop)
{
    RECT cr;
    const HWND hwnd = Rd<HWND>(kVA_phWnd);
    const int sw = Rd<int>(kVA_ScreenW), sh = Rd<int>(kVA_ScreenH);
    if (!VidModeStretched() || !hwnd || sw <= 0 || sh <= 0 || !GetClientRect(hwnd, &cr) ||
        cr.right <= 0 || cr.bottom <= 0 || (cr.right == sw && cr.bottom == sh)) {
        GpuInvalidate();               // the GPU's copy of the frame misses this update
        WinLinesOnFlip(false, 0, 0, 0, 0);   // the engine's window lines are on the window itself again
        return BitBlt(dst, x, y, w, h, src, sx, sy, rop);
    }
    WinLinesOnFlip(true, sx, sy, sx + w, sy + h);   // a flip repaints the window lines' pixels under it (winlines.cpp)

    int l = sx - 1, t = sy - 1, r = sx + w + 1, b = sy + h + 1;
    if (l < 0) l = 0;
    if (t < 0) t = 0;
    if (r > sw) r = sw;
    if (b > sh) b = sh;
    if (l >= r || t >= b) return TRUE;
    if (rop == SRCCOPY && ScaledFlip(hwnd, dst, src, sw, sh, cr.right, cr.bottom, sx < 0 ? 0 : sx, sy < 0 ? 0 : sy,
                                     sx + w < sw ? sx + w : sw, sy + h < sh ? sy + h : sh))
        return TRUE;
    GpuInvalidate();                   // GDI's stretch below: the GPU's copy of the frame misses this update
    auto edge = [](int v, int client, int screen) {
        return static_cast<int>((2LL * v * client + screen) / (2LL * screen));
    };
    const int dl = edge(l, cr.right, sw), dr = edge(r, cr.right, sw);
    const int dt = edge(t, cr.bottom, sh), db = edge(b, cr.bottom, sh);
    if (dl >= dr || dt >= db) return TRUE;
    const int old = SetStretchBltMode(dst, HALFTONE);
    SetBrushOrgEx(dst, 0, 0, nullptr);
    const BOOL ok = StretchBlt(dst, dl, dt, dr - dl, db - dt, src, l, t, r - l, b - t, rop);
    SetStretchBltMode(dst, old);
    return ok;
}

// Re-stamp PRACX's call at the flip site to FlipBlt. PRACX wrote it before our Init ran.
bool HookFlipBlt(const BYTE* px)
{
    BYTE* site = reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (kVA_FlipBlt - kImageBase);
    if (site[0] != 0xE8 || site[5] != 0x90) return false;
    DWORD rel;
    memcpy(&rel, site + 1, 4);
    const BYTE* target = site + 5 + static_cast<LONG>(rel);
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(target, &mbi, sizeof mbi) || mbi.AllocationBase != px) return false;   // not PRACX's -> leave it
    rel = reinterpret_cast<DWORD>(&FlipBlt) - reinterpret_cast<DWORD>(site + 5);
    DWORD prot;
    VirtualProtect(site, 6, PAGE_EXECUTE_READWRITE, &prot);
    memcpy(site + 1, &rel, 4);
    VirtualProtect(site, 6, prot, &prot);
    FlushInstructionCache(GetCurrentProcess(), site, 6);
    return true;
}

// Tell the Preferences page when the running mode changed behind its back (Alt+Enter, PRACX's menu item).
void NotifyIfChanged()
{
    const int m = VidModeDetect();
    if (m == g_lastMode) return;
    g_lastMode = m;
    // the mode is window STATE, like the window's position: whatever changed it (the page, Alt+Enter,
    // PRACX's menu item), the next boot comes back in it
    if (g_booted && !g_closing) VidModeSave(m);
    if (g_onChange) g_onChange();
}

// The backdrop window belongs to the watchdog thread (vidwatch.cpp) when it came up in time, so it can be hidden
// even while this thread is stalled; otherwise it is made here. Decided once (vidsafety::ClaimOwner): this thread
// never makes one while the watchdog owns the backdrop, and a watchdog that comes up late never takes it over.
HWND BackdropWnd(bool create)
{
    if (VidWatchOwnsBackdrop()) return VidWatchBackdrop();
    if (!g_ownBackdrop && create) g_ownBackdrop = CreateBackdropWindow();
    return g_ownBackdrop;
}

// Every backdrop that exists, whoever made it (belt and braces: one stranded topmost backdrop was the audit's H1).
void HideBackdrop()
{
    const HWND both[2] = { VidWatchBackdrop(), g_ownBackdrop };
    for (const HWND b : both)
        if (b && IsWindowVisible(b)) {
            ShowWindow(b, SW_HIDE);
            Logf("backdrop: hidden");
        }
    SetRectEmpty(&g_bdRect);
}

// The backdrop sits directly under the game window, in the game's z-order band, over the game window's monitor.
void ShowBackdrop(HWND game, const RECT& mon, bool topmost)
{
    const HWND b = BackdropWnd(true);
    if (!b) return;
    if (IsWindowVisible(b) && EqualRect(&mon, &g_bdRect) && topmost == g_bdTop) return;
    SetWindowPos(b, topmost ? HWND_TOPMOST : HWND_NOTOPMOST, mon.left, mon.top, mon.right - mon.left, mon.bottom - mon.top,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
    SetWindowPos(b, game, 0, 0, 0, 0, SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE);
    Logf("backdrop: over %ld,%ld %ldx%ld%s", mon.left, mon.top, mon.right - mon.left, mon.bottom - mon.top,
         topmost ? " (topmost band)" : "");
    g_bdRect = mon;
    g_bdTop = topmost;
}

bool ScaledFullscreen()
{
    return g_fWindowed && *g_fWindowed && VidModeDetect() == kVidFullscreen;
}

// Fullscreen is running, in either form: PRACX's own (m_fWindowed = 0, the display's whole screen -- with
// or without its mode switch) or our scaled popup. Both hold the pointer.
bool FullscreenRunning()
{
    return g_fWindowed && (!*g_fWindowed || VidModeDetect() == kVidFullscreen);
}

// Our own calls into PRACX's SetWindowed: their m_fWindowed transitions are no "PRACX left windowed" signal.
void OwnSetWindowed(int on)
{
    g_ownSetWindowed = true;
    g_setWindowed(on);
    g_ownSetWindowed = false;
    g_safe.Observe(*g_fWindowed != 0, true);
}

// m_fWindowed is already 1 and PRACX's own placement has run: make the window ours. `full` = Fullscreen
// without the display-mode switch, else Borderless. On `target` (a monitor rect) when given, else on the
// monitor a pending restore chose, else on the window's nearest monitor. The z-order band, the backdrop and the
// pointer clip are the safety layer's (SafetySync): topmost and the clip only while the game is the foreground
// window and the display is quiet.
void ApplyPopup(HWND hwnd, bool full, const RECT* target = nullptr)
{
    g_pendingPopup = full ? kVidFullscreen : kVidBorderless;   // what VidModeDetect reports until the window is done
    FixWindowedRect();
    g_winRect = *g_rWindowed;

    RECT mon;
    if (target) {
        mon = *target;
    } else if (g_haveTarget) {
        mon = g_target;
    } else {
        MONITORINFO mi = { sizeof mi };
        GetMonitorInfoA(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &mi);
        mon = mi.rcMonitor;
    }
    g_haveTarget = false;
    const RECT fit = FitMonitor(mon);
    g_borderW = fit.right - fit.left;
    g_borderH = fit.bottom - fit.top;

    SetWindowLongA(hwnd, GWL_STYLE, kStyleBorderless | WS_VISIBLE);
    SetWindowPos(hwnd, nullptr, fit.left, fit.top, g_borderW, g_borderH, SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW);
    InvalidateRect(hwnd, nullptr, FALSE);
    g_popupKind = g_pendingPopup;
    g_pendingPopup = -1;
    Logf("popup: %s at %ld,%ld %ldx%ld on the monitor %ld,%ld %ldx%ld", full ? "scaled Fullscreen" : "Borderless",
         fit.left, fit.top, g_borderW, g_borderH, mon.left, mon.top, mon.right - mon.left, mon.bottom - mon.top);
    SafetySync(hwnd);
}

// ---- the safety layer's view of the window, and its effects (vidsafety.h) -----------------------------------------

// user32's own monitor list (EnumDisplayMonitors + GetMonitorInfo), from VidEnumMonitors (vidwatch.cpp, shared with
// the watchdog). The device paths (one EnumDisplayDevices per monitor) only `withPaths`: when the game's monitor has
// to be recognised (NoteHome / UserPicked, a restore that is due) -- never for a release, a placement, an activation
// or an idle tick: EnumDisplayDevices can stall while the display reconfigures (re-audit N-A).
vidsafety::World MakeWorld(HWND hwnd, bool withPaths = false)
{
    vidsafety::World w;
    w.now = GetTickCount();
    w.booted = g_booted;
    w.closing = g_closing;
    w.fWindowed = g_fWindowed && *g_fWindowed;
    w.mode = VidModeDetect();
    w.applying = g_pendingPopup >= 0;
    w.foreground = GetForegroundWindow() == hwnd;
    w.iconic = IsIconic(hwnd) != FALSE;
    w.movie = MovieActive();
    w.switchAllowed = g_switchAllowed;
    w.clipWanted = g_clipWanted;
    w.sw = Rd<int>(kVA_ScreenW);
    w.sh = Rd<int>(kVA_ScreenH);
    RECT wr = {};
    GetWindowRect(hwnd, &wr);
    w.win = { wr.left, wr.top, wr.right, wr.bottom };
    HMONITOR handles[vidsafety::kMaxMonitors];
    w.nMons = VidEnumMonitors(w.mons, handles, vidsafety::kMaxMonitors, withPaths);
    const HMONITOR nearest = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
    for (int i = 0; i < w.nMons; ++i)
        if (handles[i] == nearest) w.cur = i;
    w.escapeGen = static_cast<uint32_t>(VidWatchEscapeGen());
    w.ownSwitch = VidModeOwnDisplaySwitch();
    return w;
}

void RestoreNative(HWND hwnd, const vidsafety::Monitor& m);
void RestoreScaled(HWND hwnd, const vidsafety::Monitor& m);

struct WinFx final : vidsafety::Effects {
    HWND hwnd;
    explicit WinFx(HWND h) : hwnd(h) {}
    void Clip(bool on) override { ClipToWindow(hwnd, on); }
    void Topmost(bool on) override
    {
        const bool cur = (GetWindowLongA(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST) != 0;
        if (cur == on) return;
        SetWindowPos(hwnd, on ? HWND_TOPMOST : HWND_NOTOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
        Logf("topmost: %s", on ? "on" : "off");
    }
    void Backdrop(bool show, const vidsafety::Rect& m, bool topmost) override
    {
        if (!show) { HideBackdrop(); return; }
        const RECT r = { m.l, m.t, m.r, m.b };
        ShowBackdrop(hwnd, r, topmost);
    }
    void PostConverge() override { PostMessageA(hwnd, kWM_Converge, 0, 0); }
    void Timer(bool on) override
    {
        if (on && !g_timerOn) g_timerOn = SetTimer(hwnd, kSafetyTimer, vidsafety::kTimerMs, nullptr) != 0;
        else if (!on && g_timerOn) { KillTimer(hwnd, kSafetyTimer); g_timerOn = false; }
    }
    void Native(const vidsafety::Monitor& m) override { RestoreNative(hwnd, m); }
    void Scaled(const vidsafety::Monitor& m) override { RestoreScaled(hwnd, m); }
    void Refit(const vidsafety::Monitor& m, bool full) override
    {
        const RECT r = { m.rc.l, m.rc.t, m.rc.r, m.rc.b };
        g_inRestore = true;
        ApplyPopup(hwnd, full, &r);
        g_inRestore = false;
    }
    void EventCounted() override { GpuDisplayEvent(); }
    void Log(const char* line) override { Logf("%s", line); }
};

void SafetySync(HWND hwnd)
{
    if (!g_booted || !hwnd || hwnd != g_hwnd) return;
    WinFx fx(hwnd);
    const vidsafety::World w = MakeWorld(hwnd);
    g_safe.Sync(w, fx);
}

// Restore: Fullscreen = PRACX's own on the monitor `m` (the backbuffer's size there).
void RestoreNative(HWND hwnd, const vidsafety::Monitor& m)
{
    g_inRestore = true;
    if (*g_fWindowed) {
        // from the scaled popup: PRACX's SetWindowed(false) posts SC_MAXIMIZE, which maximises the window on the
        // monitor it is on when that arrives -- so move it there right after the call
        ClipToWindow(hwnd, false);
        HideBackdrop();
        g_pendingPopup = -1;
        g_popupKind = -1;
        OwnSetWindowed(0);
        FixWindowedRect();
    }
    SetWindowPos(hwnd, nullptr, m.rc.l, m.rc.t, m.rc.W(), m.rc.H(), SWP_NOZORDER | SWP_NOACTIVATE);
    g_inRestore = false;
    SafetySync(hwnd);
}

// Restore: Fullscreen = the scaled popup on `m`.
void RestoreScaled(HWND hwnd, const vidsafety::Monitor& m)
{
    const RECT r = { m.rc.l, m.rc.t, m.rc.r, m.rc.b };
    g_inRestore = true;
    if (*g_fWindowed) {
        ApplyPopup(hwnd, true, &r);
    } else {
        // PRACX's own Fullscreen on a monitor of another size: its SetWindowed(true) posts WM_USER+3, after which
        // the subclass applies the pending popup -- onto g_target
        ClipToWindow(hwnd, false);
        HideBackdrop();
        g_target = r;
        g_haveTarget = true;
        g_pendingPopup = kVidFullscreen;
        OwnSetWindowed(1);
        if (!*g_fWindowed) { g_pendingPopup = -1; g_haveTarget = false; Logf("restore: PRACX refused SetWindowed (movie)"); }
    }
    g_inRestore = false;
}

// A display message this thread saw (msg), or an event only the watchdog thread saw (msg 0). The controller decides
// whether it counts (a device / work-area notice only with a changed monitor set, never PRACX's own mode switch);
// a counted one starts the GPU's quiet (WinFx::EventCounted). A message that always counts releases FIRST, before
// anything reads the monitor list (re-audit N-A), with the quiet period already set so the WM_WINDOWPOSCHANGED its
// leave-topmost sends re-asserts nothing (PreRelease); the controller's own release after it is then a no-op. The own
// mode switch is read once, for both calls.
void OnDisplayEvent(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (!g_booted || g_closing) return;
    WinFx fx(hwnd);
    const bool own = VidModeOwnDisplaySwitch();
    g_safe.PreRelease(GetTickCount(), own, msg, wp, fx);
    vidsafety::World w = MakeWorld(hwnd);
    w.ownSwitch = own;
    g_safe.OnDisplayEvent(w, fx, msg, wp, lp);
}

// PRACX places the windowed WINDOW at WindowWidth x WindowHeight, so the client (what the backbuffer is
// stretched into) is off-aspect by the frame. Keep the width, set the height the aspect needs.
void SnapWindowedAspect(HWND hwnd)
{
    const int sw = Rd<int>(kVA_ScreenW), sh = Rd<int>(kVA_ScreenH);
    RECT wr, cr;
    if (sw <= 0 || sh <= 0 || !GetWindowRect(hwnd, &wr) || !GetClientRect(hwnd, &cr) || cr.right <= 0) return;
    const int ncH = (wr.bottom - wr.top) - cr.bottom;
    const int ch = static_cast<int>((static_cast<long long>(cr.right) * sh + sw / 2) / sw);
    if (ch != cr.bottom)
        SetWindowPos(hwnd, nullptr, 0, 0, wr.right - wr.left, ch + ncH,
                     SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
}

// WM_SIZING: hold the client area at the backbuffer's aspect while the user drags the frame.
void SizingAspect(HWND hwnd, WPARAM edge, RECT* r)
{
    const int sw = Rd<int>(kVA_ScreenW), sh = Rd<int>(kVA_ScreenH);
    if (sw <= 0 || sh <= 0) return;
    RECT nc = {};
    AdjustWindowRectEx(&nc, static_cast<DWORD>(GetWindowLongA(hwnd, GWL_STYLE)), FALSE,
                       static_cast<DWORD>(GetWindowLongA(hwnd, GWL_EXSTYLE)));
    const int ncW = nc.right - nc.left, ncH = nc.bottom - nc.top;
    int cw = (r->right - r->left) - ncW, ch = (r->bottom - r->top) - ncH;
    const bool byHeight = edge == WMSZ_TOP || edge == WMSZ_BOTTOM;
    if (byHeight) cw = static_cast<int>((static_cast<long long>(ch) * sw + sh / 2) / sh);
    if (cw < kMinClientW) cw = kMinClientW;
    ch = static_cast<int>((static_cast<long long>(cw) * sh + sw / 2) / sw);
    if (edge == WMSZ_LEFT || edge == WMSZ_TOPLEFT || edge == WMSZ_BOTTOMLEFT) r->left = r->right - (cw + ncW);
    else r->right = r->left + cw + ncW;
    if (edge == WMSZ_TOP || edge == WMSZ_TOPLEFT || edge == WMSZ_TOPRIGHT) r->top = r->bottom - (ch + ncH);
    else r->bottom = r->top + ch + ncH;
}

LRESULT CALLBACK SubclassProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    // PRACX's SetWindowed(false) writes m_fWindowed before the window calls that send us messages: every message
    // samples it, so a 1 -> 0 that is not ours is PRACX's own path out of a windowed state (vidsafety.h)
    if (g_booted && g_fWindowed) g_safe.Observe(*g_fWindowed != 0, g_ownSetWindowed);

    // the watchdog's probe: answered here, never PRACX's or the engine's
    if (msg == WM_NULL && wp == kWatchProbeW && lp == kWatchProbeL) {
        if (InterlockedExchange(&g_resyncOwed, 0) && g_booted) WinFx(hwnd).Timer(true);   // re-state from the timer
        return kWatchProbeAnswer;
    }
    const bool displayEvent = vidsafety::IsDisplayEvent(msg, wp);
    if (displayEvent) {
        g_dispSeqSeen = VidWatchBumpDisplaySeq();
        OnDisplayEvent(hwnd, msg, wp, lp);        // releases now; PRACX still gets the message below
    } else if (g_booted && VidWatchDisplaySeq() != g_dispSeqSeen) {
        g_dispSeqSeen = VidWatchDisplaySeq();     // one only the watchdog's window received (this thread was busy)
        OnDisplayEvent(hwnd, 0, 0, 0);
    }
    if (msg == WM_TIMER && wp == kSafetyTimer) {
        if (g_booted) {
            WinFx fx(hwnd);
            const vidsafety::World w = MakeWorld(hwnd, g_safe.NeedsPaths(GetTickCount()));   // paths only for a due restore
            g_safe.OnTimer(w, fx);
        }
        return 0;
    }

    if (msg == kWM_PracxWindowed) {
        FixWindowedRect();
        const LRESULT r = CallWindowProcA(g_prevProc, hwnd, msg, wp, lp);
        if (g_pendingPopup >= 0) {
            ApplyPopup(hwnd, g_pendingPopup == kVidFullscreen);
        } else {
            SnapWindowedAspect(hwnd);
        }
        NotifyIfChanged();
        return r;
    }
    // stretched modes repaint the whole client from the backbuffer: a background erase first is only a
    // black flash (dragging / sizing the window)
    if (msg == WM_ERASEBKGND && VidModeStretched()) return 1;
    if (msg == WM_WINDOWPOSCHANGED || msg == WM_STYLECHANGED) {
        const LRESULT r = CallWindowProcA(g_prevProc, hwnd, msg, wp, lp);
        if (g_booted) {
            // clip / topmost / backdrop follow the window; PRACX's own SetWindowed(false) on a monitor of another
            // size (its menu item) lands in m_fWindowed = 0 = the mode switch we suppress: the controller posts the
            // converge back to our Fullscreen, outside this message. A system reposition never converges.
            WinFx fx(hwnd);
            const vidsafety::World w = MakeWorld(hwnd);
            g_safe.OnPlacement(w, fx);
        }
        NotifyIfChanged();
        return r;
    }
    if (msg == kWM_Converge) {
        WinFx fx(hwnd);
        const vidsafety::World w = MakeWorld(hwnd);
        if (g_safe.OnConverge(w, fx)) VidModeSet(kVidFullscreen);
        return 0;
    }
    if (msg == WM_EXITSIZEMOVE && g_booted) g_safe.NoteHome(MakeWorld(hwnd, true));   // the user moved the game: its monitor
    if (!g_switchAllowed && g_booted && !g_closing) {
        // PRACX's own toggles go through SetWindowed(false) = the display-mode switch: take them over.
        // Alt+Enter (PRACX keys on it with the Alt flag; both the sys and the plain key message, once per press):
        if ((msg == WM_SYSKEYDOWN || msg == WM_KEYDOWN) && wp == VK_RETURN &&
            ((lp & (1u << 29)) || GetKeyState(VK_MENU) < 0)) {
            if (!(lp & (1u << 30))) VidModeSet(VidModeDetect() == kVidFullscreen ? kVidWindowed : kVidFullscreen);
            return 0;
        }
        if (msg == WM_SYSCHAR && wp == VK_RETURN) return 0;
        // SC_MAXIMIZE while m_fWindowed is 1: PRACX's handler makes it SetWindowed(false) = the switch. From
        // the Windowed frame (maximize button, title double-click) it means Fullscreen; in a popup mode,
        // or while one is being applied, it is PRACX's own SC_MAXIMIZE posted by the SetWindowed(false) we
        // are converging away from -- swallowed, or the two would ping-pong forever.
        if (msg == WM_SYSCOMMAND && (wp & 0xFFF0) == SC_MAXIMIZE && *g_fWindowed) {
            if (VidModeDetect() == kVidWindowed) VidModeSet(kVidFullscreen);
            return 0;
        }
    }
    // Fullscreen without the switch: the app losing focus minimises the game, as PRACX's fullscreen does
    // (its handler is gated on m_fWindowed == 0). The shell restores it on the way back.
    if (msg == WM_ACTIVATEAPP && !wp && g_booted && !g_closing && ScaledFullscreen() && !IsIconic(hwnd)) {
        ClipToWindow(hwnd, false);
        HideBackdrop();
        ShowWindow(hwnd, SW_MINIMIZE);
    }
    if ((msg == WM_ACTIVATE || msg == WM_ACTIVATEAPP) && g_booted) {
        const LRESULT r = CallWindowProcA(g_prevProc, hwnd, msg, wp, lp);
        const bool active = msg == WM_ACTIVATEAPP ? wp != 0 : LOWORD(wp) != WA_INACTIVE;
        WinFx fx(hwnd);
        const vidsafety::World w = MakeWorld(hwnd);
        g_safe.OnActivate(w, fx, active);
        return r;
    }
    if (msg == WM_DESTROY) {
        g_closing = true;
        ClipToWindow(hwnd, false);
        if (g_timerOn) { KillTimer(hwnd, kSafetyTimer); g_timerOn = false; }
    }
    if (msg == WM_SIZING && VidModeDetect() == kVidWindowed)
        SizingAspect(hwnd, wp, reinterpret_cast<RECT*>(lp));
    else if (msg == WM_NCDESTROY) {
        const WNDPROC prev = g_prevProc;
        SetWindowLongA(hwnd, GWL_WNDPROC, reinterpret_cast<LONG>(prev));
        ClipToWindow(hwnd, false);
        VidWatchStop();                      // the watchdog thread destroys its own windows (the backdrop among them)
        if (g_ownBackdrop) DestroyWindow(g_ownBackdrop);
        g_ownBackdrop = nullptr;
        g_hwnd = nullptr;
        return CallWindowProcA(prev, hwnd, msg, wp, lp);
    }
    return CallWindowProcA(g_prevProc, hwnd, msg, wp, lp);
}

} // namespace

bool VidModeAvailable() { return g_setWindowed != nullptr; }

bool VidModeOwnDisplaySwitch()
{
    return g_ownCdsDepth > 0 ||
           (g_ownCdsEver && GetTickCount() - static_cast<DWORD>(g_ownCdsAt) < kOwnSwitchGraceMs);
}

void VidModeOnChange(void (*fn)()) { g_onChange = fn; }

bool VidModeStretched() { return g_fWindowed && *g_fWindowed; }

bool VidModeFullscreenRunning() { return VidModeAvailable() && FullscreenRunning(); }
int  VidModeClipGet() { return g_clipWanted ? 1 : 0; }
void VidModeClipSet(int on)
{
    g_clipWanted = on != 0;
    if (g_hwnd) SafetySync(g_hwnd);    // takes effect at once, in Fullscreen; a no-op elsewhere
}
void VidModeClipSave()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "ConstrainMouse", g_clipWanted ? "1" : "0", ini);
}

void VidModeClientToBackbuffer(HWND hwnd, POINT* p)
{
    RECT r;
    if (!VidModeStretched() || !GetClientRect(hwnd, &r) || r.right <= 0 || r.bottom <= 0) return;
    p->x = p->x * Rd<int>(kVA_ScreenW) / r.right;      // PRACX ClientToBackbuffer
    p->y = p->y * Rd<int>(kVA_ScreenH) / r.bottom;
}

int VidModeDetect()
{
    if (!VidModeAvailable() || !*g_fWindowed) return kVidFullscreen;
    if (g_pendingPopup >= 0) return g_pendingPopup;
    const HWND hwnd = Rd<HWND>(kVA_phWnd);
    if (!hwnd) return kVidBorderless;
    if ((GetWindowLongA(hwnd, GWL_STYLE) & WS_CAPTION) == WS_CAPTION) return kVidWindowed;
    return g_popupKind == kVidFullscreen ? kVidFullscreen : kVidBorderless;   // which popup we made, not the z-order band
}

void VidModeSet(int mode)
{
    const HWND hwnd = Rd<HWND>(kVA_phWnd);
    if (!VidModeAvailable() || !hwnd) return;
    const int cur = VidModeDetect();
    const bool legacyFull = !*g_fWindowed;    // PRACX's own fullscreen state (m_fWindowed = 0)
    const bool wantScaled = mode == kVidFullscreen && NeedsScaledFullscreen(hwnd);
    // a mode the user chose (Preferences, Alt+Enter, the boot mode, PRACX's menu item): its monitor is where a
    // display-topology restore brings the game back to, and a wait for a vanished monitor is over -- even when the
    // mode is the one running (then the popup is re-fitted where the window is)
    const bool wasAwaiting = g_safe.AwaitHome();
    if (g_booted && !g_inRestore && g_hwnd == hwnd) g_safe.UserPicked(MakeWorld(hwnd, true));
    // the one same-mode re-apply: PRACX's fullscreen state where ours has to be the scaled popup
    if (mode == cur && !(legacyFull && wantScaled)) {
        if (wasAwaiting && *g_fWindowed && mode != kVidWindowed) ApplyPopup(hwnd, mode == kVidFullscreen);
        else if (g_booted) SafetySync(hwnd);
        return;
    }

    if (cur == kVidWindowed) {           // remember where the user put the window
        WINDOWPLACEMENT wp = { sizeof wp };
        if (GetWindowPlacement(hwnd, &wp)) *g_rWindowed = wp.rcNormalPosition;
    }

    g_pendingPopup = -1;
    g_haveTarget = false;
    if (mode == kVidFullscreen && !wantScaled) {
        ClipToWindow(hwnd, false);
        HideBackdrop();
        g_popupKind = -1;
        OwnSetWindowed(0);
        FixWindowedRect();
    } else if (mode == kVidWindowed) {
        ClipToWindow(hwnd, false);
        HideBackdrop();
        FixWindowedRect();
        g_popupKind = -1;
        if (legacyFull) {
            OwnSetWindowed(1);
        } else {                         // a popup mode: m_fWindowed is already 1, SetWindowed would no-op
            SetWindowLongA(hwnd, GWL_STYLE, kStyleWindowed);
            PostMessageA(hwnd, kWM_PracxWindowed, 0, 0);
        }
    } else {                             // Borderless, or Fullscreen without the display-mode switch
        if (legacyFull) {
            // PRACX posts WM_USER+3 to place the window; restyle only after that has run, or its
            // SetWindowPlacement lands last and re-frames the window (SubclassProc)
            g_pendingPopup = mode;
            OwnSetWindowed(1);
            if (!*g_fWindowed) g_pendingPopup = -1;   // PRACX refused (its movie guard)
        } else {
            ApplyPopup(hwnd, mode == kVidFullscreen);
        }
    }

    char msg[128];
    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] vidmode: %s -> %s%s\n", ModeName(cur), ModeName(mode),
                wantScaled ? " (monitor stays in its own mode)" : "");
    UimodLog(msg);
}

void VidModeSave(int mode)
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    char val[8];
    _snprintf_s(val, sizeof val, _TRUNCATE, "%d", mode);
    WritePrivateProfileStringA("UIMod", "VideoMode", val, ini);
}

// Init runs before the game window exists; the message hook calls this until the window is up.
void VidModePoll()
{
    if (g_booted || !VidModeAvailable()) return;
    const HWND hwnd = Rd<HWND>(kVA_phWnd);
    if (!hwnd || !IsWindowVisible(hwnd)) return;
    g_booted = true;
    g_hwnd = hwnd;
    g_prevProc = reinterpret_cast<WNDPROC>(
        SetWindowLongA(hwnd, GWL_WNDPROC, reinterpret_cast<LONG>(&SubclassProc)));
    g_safe.Observe(*g_fWindowed != 0, true);   // the state PRACX booted in is no transition

    // the watchdog thread (and the backdrop it owns) before anything can be held
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    char hotkey[64];
    GetPrivateProfileStringA("UIMod", "EscapeHotkey", vidsafety::kDefaultHotkey, hotkey, sizeof hotkey, ini);
    VidWatchStart(hwnd, &g_clipped, &g_resyncOwed, hotkey);
    g_dispSeqSeen = VidWatchDisplaySeq();
    // the CPU scaler's threads now, while nothing holds the loader lock (RunJob only uses workers that run)
    EnsurePool();

    // PRACX seeds the windowed placement at the desktop's top-left corner: centre it in the work area
    RECT wa;
    if (g_rWindowed->left == 0 && g_rWindowed->top == 0 && SystemParametersInfoA(SPI_GETWORKAREA, 0, &wa, 0)) {
        const int w = g_rWindowed->right, h = g_rWindowed->bottom;
        const int x = ((wa.right - wa.left) - w) / 2, y = ((wa.bottom - wa.top) - h) / 2;
        if (w > 0 && h > 0 && x > 0 && y > 0) SetRect(g_rWindowed, x, y, x + w, y + h);
    }
    g_winRect = *g_rWindowed;

    const int want = LoadMode();
    char msg[96];
    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] vidmode: boot, [UIMod] VideoMode=%d (%s)\n", want, ModeName(want));
    UimodLog(msg);
    g_safe.NoteHome(MakeWorld(hwnd, true));   // the boot monitor, also when VidModeSet below has nothing to change
    VidModeSet(want);
    SafetySync(hwnd);                    // PRACX's own Fullscreen is already running: nothing above re-placed the window
}

// prax.dll's window code is the one this module was written against (static bytes: valid before its init).
static bool PraxWindowCodeOk(const BYTE* px)
{
    static const BYTE prologue[5] = { 0x55, 0x8B, 0xEC, 0x6A, 0xFF };
    static const BYTE pushWin[5]  = { 0x68, 0x00, 0x00, 0xCF, 0x02 };
    static const BYTE pushFull[5] = { 0x68, 0x00, 0x00, 0x00, 0x82 };
    DWORD ref;
    memcpy(&ref, px + kPx_fWindowedRef, sizeof ref);
    return memcmp(px + kPx_SetWindowed, prologue, 5) == 0 && memcmp(px + kPx_PushWindowed, pushWin, 5) == 0 &&
           memcmp(px + kPx_PushFull, pushFull, 5) == 0 && ref == reinterpret_cast<DWORD>(px + kPx_fWindowed);
}

// Bootstrap phase one (init.cpp PreInit): prax.dll is loaded, PRACXHook has NOT run. Redirect its
// ChangeDisplaySettingsA import now, so the SetVideoMode inside PRACXHook never switches the monitor at
// a non-native ScreenWidth x ScreenHeight (the switch-then-restore blank at boot). Same checks as
// InstallVidMode, which still logs the outcome; a failed check leaves everything to it.
void VidModePreInit(HMODULE prax)
{
    const BYTE* px = reinterpret_cast<const BYTE*>(prax);
    if (!px || !PraxWindowCodeOk(px)) return;
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    if (GetPrivateProfileIntA("UIMod", "FullscreenModeSwitch", 0, ini) != 0) return;
    g_preHooked = HookDisplaySwitch(px);
    if (g_preHooked) UimodLog("[uimod] vidmode: display-mode switch suppressed before PRACX init (no switch at boot)\n");
}

void InstallVidMode(bool pracx)
{
    const BYTE* px = pracx ? reinterpret_cast<const BYTE*>(GetModuleHandleA("prax.dll")) : nullptr;
    if (!px) {
        UimodLog("[uimod] vidmode: no PRACX -> display modes disabled\n");
        return;
    }
    if (!PraxWindowCodeOk(px)) {
        UimodLog("[uimod] vidmode: prax.dll byte check FAILED -> display modes disabled\n");
        return;
    }
    g_fWindowed = const_cast<BYTE*>(px) + kPx_fWindowed;
    g_rWindowed = reinterpret_cast<RECT*>(const_cast<BYTE*>(px) + kPx_rWindowedRect);
    g_setWindowed = reinterpret_cast<FSetWindowed>(const_cast<BYTE*>(px) + kPx_SetWindowed);
    UimodLog("[uimod] vidmode: bound to PRACX window code\n");
    const bool flipOk = HookFlipBlt(px);
    UimodLog(flipOk ? "[uimod] vidmode: dirty-rect present installed\n"
                    : "[uimod] vidmode: flip site not PRACX's -> PRACX's full-frame present kept\n");
    // the window-line overlay rides on our present (its flips erase the lines, the GPU composites them)
    if (flipOk)
        UimodLog(InstallWinLines() ? "[uimod] vidmode: window-line overlay installed (Win_window_line_raw 0x5F2AC0)\n"
                                   : "[uimod] vidmode: Win_window_line_raw 0x5F2AC0 byte check FAILED -> tutorial pointer lines unmapped when stretched\n");

    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    g_switchAllowed = GetPrivateProfileIntA("UIMod", "FullscreenModeSwitch", 0, ini) != 0;
    g_clipWanted = GetPrivateProfileIntA("UIMod", "ConstrainMouse", 1, ini) != 0;
    if (g_switchAllowed) {
        UimodLog(HookDisplaySwitch(px, &MarkedDisplaySwitch)
                     ? "[uimod] vidmode: [UIMod] FullscreenModeSwitch=1 -> PRACX switches the display mode in Fullscreen "
                       "(its own switches are not taken for a monitor change)\n"
                     : "[uimod] vidmode: [UIMod] FullscreenModeSwitch=1 -> PRACX switches the display mode in Fullscreen "
                       "(slot not recognised: its switches count as display events)\n");
    } else if (g_preHooked) {
        UimodLog("[uimod] vidmode: display-mode switch suppressed (the monitor stays in its own mode; done before PRACX init)\n");
    } else {
        UimodLog(HookDisplaySwitch(px)
                     ? "[uimod] vidmode: display-mode switch suppressed (the monitor stays in its own mode)\n"
                     : "[uimod] vidmode: prax.dll ChangeDisplaySettings slot not recognised -> PRACX's switch not suppressed\n");
    }
    // One-phase chain (an exe without thunk_uimod_preload): PRACX switched the display at its hook time,
    // before this DLL loaded, when ScreenWidth x ScreenHeight differs from the desktop. Put the desktop
    // back now, before the window exists, unless Fullscreen is to keep the real switch. With PreInit the
    // switch was a no-op and there is nothing to restore.
    if (!g_preHooked && (!g_switchAllowed || LoadMode() != kVidFullscreen) && PracxSwitchedDesktop(ini)) {
        ChangeDisplaySettingsA(nullptr, 0);
        UimodLog("[uimod] vidmode: desktop mode restored (PRACX switched it before uimod loaded)\n");
    }
}
