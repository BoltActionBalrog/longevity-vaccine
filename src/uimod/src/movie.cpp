// uimod in-process cinematic player.
//
// Plays movies inside the game process/window -- no external player (playuv15) and no display-mode
// change. Decodes with libav (the SAME path reads the original movies\*.wve [EA container / tqi /
// adpcm_ea] AND our AI-upscaled movies\hd\*.mp4 [h264]); presents each frame aspect-fit to the
// runtime screen via GDI to the game window. PRACX and pristine share this one path.
//
// This is the VIDEO milestone: video + 15fps timing + skip + WM_MOVIEOVER. Audio (XAudio2) + A/V
// sync land next. Flicker-free (compose one back buffer, single BitBlt per tick) and alt-tab-safe
// (pump+dispatch messages, but eat WM_PAINT/WM_ERASEBKGND so the game can't repaint over us).

#define __STDC_CONSTANT_MACROS
#include <windows.h>
#include <ddraw.h>
#include <mmsystem.h>
#pragma comment(lib, "winmm.lib")
#include <delayimp.h>
#include "movie.h"
#include "movieaudio.h"
#include "moviepace.h"
#include "codecs.h"
#include "caption.h"
#include "vidmode.h"
#include "gpuscale.h"

void UimodLog(const char* msg);   // init.cpp: uimod.log + debugger

#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <deque>
#include <vector>

extern "C" {
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
#include <libavutil/imgutils.h>
#include <libavutil/channel_layout.h>
}

namespace {

// terranx.exe absolute VAs (image base 0x00400000), resolved off the real module base.
constexpr uintptr_t kImageBase  = 0x00400000;
constexpr uintptr_t kVA_amovie  = 0x00403BE0;  // amovie_project_2 entry (PRACX stamps E9 here)
constexpr uintptr_t kVA_phWnd   = 0x009B7B28;  // *(HWND*) main game window
constexpr uintptr_t kVA_screenW = 0x009B7B1C;  // *(int*)  render-area width
constexpr uintptr_t kVA_screenH = 0x009B7B20;  // *(int*)  render-area height

constexpr UINT kWM_MOVIEOVER = WM_USER + 6;    // PRACX's signal; its WndProc clears m_fPlayingMovie

bool g_pracx = false;
movieaudio::Mode g_audioMode = movieaudio::kAuto;   // [UIMod] MovieAudio=, read once at InstallMovieHook

// Which backend the movies' sound took and why: uimod.log gets it the first time and again whenever
// the answer changes (XAudio2 at Init, waveOut at the movie = the engine failed on this device).
void ReportAudioVerdict(const movieaudio::Verdict& v)
{
    static int last = -1;
    char line[224];
    _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] movie audio: %s\n", v.why);
    if (last != static_cast<int>(v.backend)) { UimodLog(line); last = static_cast<int>(v.backend); }
    else OutputDebugStringA(line);
}

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}

void Dbg(const char* s) { OutputDebugStringA(s); }

// Aspect-fit: uniform scale, centered, black bars. One formula valid at every resolution.
RECT FitRect(int srcW, int srcH, int scrW, int scrH)
{
    double s = static_cast<double>(scrW) / srcW;
    const double sy = static_cast<double>(scrH) / srcH;
    if (sy < s) s = sy;
    const int dw = static_cast<int>(srcW * s + 0.5);
    const int dh = static_cast<int>(srcH * s + 0.5);
    const int dx = (scrW - dw) / 2;
    const int dy = (scrH - dh) / 2;
    return RECT{ dx, dy, dx + dw, dy + dh };
}

// Game directory (with trailing backslash), derived from the running exe's path.
void GameDir(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
}

bool FileExists(const char* p)
{
    const DWORD a = GetFileAttributesA(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

bool UpscaledVideosEnabled()
{
    char ini[MAX_PATH]; GameDir(ini, sizeof ini);
    lstrcatA(ini, "Alpha Centauri.ini");
    return GetPrivateProfileIntA("UIMod", "UpscaledVideos", 0, ini) != 0;
}

// Resolve the bare movie name (e.g. "openingx") to a source file: the AI mp4 if enabled and
// present, else the original .wve. Returns false if nothing is found.
bool BuildSourcePath(const char* name, char* out, size_t n)
{
    if (!name || !*name) return false;

    char base[MAX_PATH]; lstrcpynA(base, name, MAX_PATH);
    if (char* dot = strrchr(base, '.'); dot && lstrlenA(dot) <= 4) *dot = '\0'; // strip any ext

    char dir[MAX_PATH]; GameDir(dir, sizeof dir);

    if (UpscaledVideosEnabled()) {
        _snprintf_s(out, n, _TRUNCATE, "%smovies\\hd\\%s.mp4", dir, base);
        if (FileExists(out)) return true;
    }
    _snprintf_s(out, n, _TRUNCATE, "%smovies\\%s.wve", dir, base);
    return FileExists(out);
}

// While we own the screen the game must not present: Pump() dispatches its WM_TIMERs (event-log
// scroll, unit blink, ...) and those flip their dirty rects over our frames. Vanilla never sees this
// because its movie runs on a separate exclusive DirectDraw primary. Every game present funnels
// through Win_flip_rect (cdecl), so stub its entry with RET for the duration; on release mirror the
// native movie exit (Win_update_screen(0,0) + Win_flip_rect(0)) to repaint what was dropped.
constexpr uintptr_t kVA_WinFlipRect      = 0x005EFD20;
constexpr uintptr_t kVA_WinUpdateScreen  = 0x005F7320;

struct FlipBlock {
    BYTE* entry = At(kVA_WinFlipRect);
    BYTE  saved = 0;
    bool  armed = false;

    bool Poke(BYTE v)
    {
        DWORD old = 0;
        if (!VirtualProtect(entry, 1, PAGE_EXECUTE_READWRITE, &old)) return false;
        *entry = v;
        VirtualProtect(entry, 1, old, &old);
        FlushInstructionCache(GetCurrentProcess(), entry, 1);
        return true;
    }
    FlipBlock()
    {
        saved = *entry;
        if (saved != 0xA1) { Dbg("[uimod] Win_flip_rect entry unexpected -- not blocking flips\n"); return; }
        armed = Poke(0xC3);
    }
    ~FlipBlock()
    {
        if (!armed || !Poke(saved)) return;
        using UpdateScreen = int(__cdecl*)(RECT*, void*);
        using FlipRect     = void(__cdecl*)(RECT*);
        reinterpret_cast<UpdateScreen>(At(kVA_WinUpdateScreen))(nullptr, nullptr);
        reinterpret_cast<FlipRect>(At(kVA_WinFlipRect))(nullptr);
    }
};

// The game's own sound (music, effects) must be silent while a movie plays. The native player does it
// inside the routine we replace (set_video_mode 0x4BEA50): before the movie it suspends the sound
// manager's device (0x4C4FC0), or pauses it (0x4C51D0) when the "8BitMovieSound" preference is set, and
// undoes that after the caption. soundx.dll plays on its own threads, so without this the in-game music
// runs on under the movie. Same calls, same preference, same order. Our audio is XAudio2, not the
// game's device.
constexpr uintptr_t kVA_SoundMgr     = 0x0090D978;  // sound manager object (device at +0x14)
constexpr uintptr_t kVA_SndSuspend   = 0x004C4FC0;  // thiscall, device vtbl+0x48
constexpr uintptr_t kVA_SndResume    = 0x004C4FD0;  // thiscall, device vtbl+0x4C
constexpr uintptr_t kVA_SndPause     = 0x004C51D0;  // thiscall, device vtbl+0x64
constexpr uintptr_t kVA_SndUnpause   = 0x004C51C0;  // thiscall, device vtbl+0x60
constexpr uintptr_t kVA_PrefsGet2    = 0x0059DB40;  // cdecl prefs_get_2(name, default, 0)

struct GameSoundHold {
    bool paused = false;

    static void Call(uintptr_t va)
    {
        using Fn = int(__thiscall*)(void* self);
        reinterpret_cast<Fn>(At(va))(At(kVA_SoundMgr));
    }
    GameSoundHold()
    {
        using PrefsGet2 = int(__cdecl*)(const char*, int, int);
        paused = reinterpret_cast<PrefsGet2>(At(kVA_PrefsGet2))("8BitMovieSound", 0, 0) != 0;
        Call(paused ? kVA_SndPause : kVA_SndSuspend);
        // Suspending stops soundx.dll's multimedia timer, which was what kept the process timer
        // resolution raised; the frame loop's Sleep(<= 10) needs it.
        timeBeginPeriod(1);
    }
    ~GameSoundHold()
    {
        timeEndPeriod(1);
        Call(paused ? kVA_SndUnpause : kVA_SndResume);
    }
};

// Dimensions of the ORIGINAL clip (movies\<name>.wve) -- the caption's 640x480 layout space is
// anchored to it, whatever source actually played (the HD pack is a multiple of it). Falls back to
// the played size if that IS the .wve-sized stream, else to the 400-wide project-clip shape.
void NativeClipSize(const char* name, int playedW, int playedH, int* w, int* h)
{
    char base[MAX_PATH]; lstrcpynA(base, name ? name : "", MAX_PATH);
    if (char* dot = strrchr(base, '.'); dot && lstrlenA(dot) <= 4) *dot = '\0';
    char dir[MAX_PATH]; GameDir(dir, sizeof dir);
    char wve[MAX_PATH];
    _snprintf_s(wve, sizeof wve, _TRUNCATE, "%smovies\\%s.wve", dir, base);

    AVFormatContext* f = nullptr;
    if (FileExists(wve) && avformat_open_input(&f, wve, nullptr, nullptr) == 0) {
        if (avformat_find_stream_info(f, nullptr) >= 0) {
            const int v = av_find_best_stream(f, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
            if (v >= 0 && f->streams[v]->codecpar->width > 0) {
                *w = f->streams[v]->codecpar->width;
                *h = f->streams[v]->codecpar->height;
                avformat_close_input(&f);
                return;
            }
        }
        avformat_close_input(&f);
    }
    if (playedW <= 640) { *w = playedW; *h = playedH; return; }
    *w = 400; *h = (400 * playedH + playedW / 2) / playedW;
}

// Pump the queue: dispatch activation/alt-tab/etc, but eat paints (so the game can't repaint over
// us) and consume skip input. Sets *skip on ESC/click/Space/Enter.
void Pump(bool* skip)
{
    MSG m;
    while (PeekMessageA(&m, nullptr, 0, 0, PM_REMOVE)) {
        if (m.message == WM_PAINT || m.message == WM_ERASEBKGND) {
            if (m.hwnd) ValidateRect(m.hwnd, nullptr);
            continue;
        }
        if ((m.message == WM_KEYDOWN &&
             (m.wParam == VK_ESCAPE || m.wParam == VK_RETURN || m.wParam == VK_SPACE)) ||
            m.message == WM_LBUTTONDOWN) {
            *skip = true;
            continue;
        }
        TranslateMessage(&m);
        DispatchMessageA(&m);
    }
}

// Pristine true-colour present via DirectDraw. The game's DirectDraw primary is an 8-bit paletted
// surface and DDrawCompat hooks process-wide GDI to route blits onto it, so any BitBlt-to-screen
// gets quantized to 256 colours + dithered, and UpdateLayeredWindow at 4K is far too slow. The
// game's OWN movie player avoids both by taking a true-colour DirectDraw mode (DDrawCompat absorbs
// it with no real desktop change) -- we mirror that: take exclusive, set a 32-bit display mode, and
// write frames straight into the locked primary surface. No GDI, no palette, hardware-paced.
enum PresentMode { PRESENT_BITBLT, PRESENT_DDRAW };

struct DDrawPresenter {
    IDirectDraw7*        dd = nullptr;
    IDirectDrawSurface7* primary = nullptr;
    int  w = 0, h = 0, bpp = 0;
    bool ok = false;

    bool Begin(HWND hwnd, int W, int H)
    {
        if (FAILED(DirectDrawCreateEx(nullptr, reinterpret_cast<void**>(&dd),
                                      IID_IDirectDraw7, nullptr))) return false;
        w = W; h = H;
        if (FAILED(dd->SetCooperativeLevel(hwnd, DDSCL_EXCLUSIVE | DDSCL_FULLSCREEN))) return Fail();
        if (FAILED(dd->SetDisplayMode(W, H, 32, 0, 0))) return Fail();
        restored = true;  // mode changed -> teardown must re-run the game's video-mode init
        DDSURFACEDESC2 d{}; d.dwSize = sizeof d;
        d.dwFlags = DDSD_CAPS; d.ddsCaps.dwCaps = DDSCAPS_PRIMARYSURFACE;
        if (FAILED(dd->CreateSurface(&d, &primary, nullptr))) return Fail();
        ok = true;
        Dbg("[uimod] DirectDraw present: 32-bit primary ready\n");
        return true;
    }

    // Copy the composed 32-bit BGRA back buffer straight into the primary surface.
    void Present(const void* bb, int stride)
    {
        if (!ok) return;
        DDSURFACEDESC2 d{}; d.dwSize = sizeof d;
        HRESULT hr = primary->Lock(nullptr, &d, DDLOCK_WAIT | DDLOCK_WRITEONLY, nullptr);
        if (hr == DDERR_SURFACELOST) { primary->Restore(); return; }
        if (FAILED(hr)) return;
        if (d.ddpfPixelFormat.dwRGBBitCount == 32) {
            const int rows = (h < static_cast<int>(d.dwHeight)) ? h : static_cast<int>(d.dwHeight);
            const int rb = (stride < static_cast<int>(d.lPitch)) ? stride : static_cast<int>(d.lPitch);
            auto* dstp = static_cast<uint8_t*>(d.lpSurface);
            auto* srcp = static_cast<const uint8_t*>(bb);
            for (int y = 0; y < rows; ++y)
                memcpy(dstp + static_cast<size_t>(y) * d.lPitch, srcp + static_cast<size_t>(y) * stride, rb);
        }
        primary->Unlock(nullptr);
    }

    bool Fail() { End(); return false; }
    void End()
    {
        // Mirror the game's own movie teardown (movie_ddraw_fs_init's partner @0x4bf400):
        // RestoreDisplayMode -> release -> and crucially RE-RUN the game's video-mode init, because
        // the game never re-sets its mode after a movie. Without that last call DDrawCompat stays out
        // of its scale-to-desktop mode and the game shows 1:1 in a corner, whatever we do on release.
        if (primary) { primary->Release(); primary = nullptr; }
        if (dd) { dd->RestoreDisplayMode(); dd->Release(); dd = nullptr; }
        if (restored) { // re-establish the game's mode exactly as the native teardown does
            using GameSetVideoMode = void(__cdecl*)(int w, int h, int bpp, int flags);
            reinterpret_cast<GameSetVideoMode>(At(0x005F2C40))(w, h, 8, 0);
        }
        ok = false;
    }
    bool restored = false;
};

// path -> decode -> aspect-fit scale -> present until EOF/skip. `mode` selects the present path:
// PRESENT_BITBLT = BitBlt to the window DC (PRACX: true-colour desktop-res window); PRESENT_DDRAW =
// lock+copy into a 32-bit DirectDraw primary (pristine true colour). `swsFlags` picks the scaler.
// The sink of the movie in progress, for PlayGuarded's handler: under /EHsc an SEH exception unwinds no C++
// frame, so the one object whose leak would outlive the movie (an XAudio2 engine still playing, our COM
// init on the game thread) is reachable from file scope and closed there.
movieaudio::Sink* g_activeSink = nullptr;

// One clock for the schedule: the performance counter, because GetTickCount moves in ~15.6 ms steps
// (a frame is 33 ms; that is half a frame of false lateness) whatever timeBeginPeriod says.
double NowMs()
{
    LARGE_INTEGER f, c;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return static_cast<double>(c.QuadPart) * 1000.0 / static_cast<double>(f.QuadPart);
}

// ---- CPU affinity, widened for one movie --------------------------------------------------------
// DDrawCompat pins the game to one CPU and that stays outside movies (the maintainer's decision), but an
// HD clip wants several for its decoder threads. NOT kernel32's SetProcessAffinityMask: DDrawCompat hooks
// it and returns TRUE without doing anything; ntdll's call is not hooked and every result is read back
// (docs\notes\feedback-ddrawcompat-affinity.md, the same route as update.cpp's WidenAffinity).
//
// DDrawCompat's CpuAffinityRotation (on by default) moves the pin to the next core ten times a second from its
// own update thread, through the original SetProcessAffinityMask, which pins the decoder threads again. A small
// watchdog thread undoes it: the player thread cannot, it spends its time inside the decoder and the scaler.
// File scope for the same reason as g_activeSink: under /EHsc an SEH exception unwinds no C++ frame, and
// PlayGuarded has to be able to give the pin back on its own.
moviepace::AffinityState g_affinity;   // the watchdog alone writes it between the widen and StopWatchdog
int    g_playDepth = 0;                // a message dispatched by Pump could in principle start a movie
HANDLE g_watchdog = nullptr, g_watchdogStop = nullptr;

constexpr DWORD kAffinityPollMs = 5;

bool SetProcessMaskNt(DWORD_PTR mask)
{
    typedef LONG (NTAPI* FSetInfo)(HANDLE, ULONG, PVOID, ULONG);
    const HMODULE nt = GetModuleHandleW(L"ntdll.dll");
    const FSetInfo setInfo = nt ? reinterpret_cast<FSetInfo>(GetProcAddress(nt, "NtSetInformationProcess")) : nullptr;
    if (!setInfo) return false;
    constexpr ULONG kProcessAffinityMask = 21;   // PROCESSINFOCLASS ProcessAffinityMask (a KAFFINITY)
    DWORD_PTR want = mask;
    return setInfo(GetCurrentProcess(), kProcessAffinityMask, &want, sizeof want) >= 0;
}

DWORD_PTR CurrentProcessMask(DWORD_PTR* system = nullptr)
{
    DWORD_PTR proc = 0, sys = 0;
    if (!GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys)) return 0;
    if (system) *system = sys;
    return proc;
}

void LogAffinity(const char* what, DWORD_PTR a, DWORD_PTR b, unsigned n = 0)
{
    char l[200];
    _snprintf_s(l, sizeof l, _TRUNCATE, "[uimod] movie affinity: %s 0x%lX -> 0x%lX (re-pinned %u time(s))\n",
                what, static_cast<unsigned long>(a), static_cast<unsigned long>(b), n);
    UimodLog(l);
}

// A re-pin is corrected within one poll, and the poll is two cheap system calls.
void PollAffinity()
{
    if (!g_affinity.active || g_affinity.gaveUp) return;
    const DWORD_PTR cur = CurrentProcessMask();
    if (!moviepace::OnPoll(g_affinity, cur)) return;
    SetProcessMaskNt(g_affinity.wide);
    const DWORD_PTR back = CurrentProcessMask();
    moviepace::OnRewidenResult(g_affinity, back);
    if (g_affinity.repins == 1) LogAffinity("re-pinned during the movie, widening again:", cur, back, 1);   // the rest are counted
    if (g_affinity.gaveUp) LogAffinity("gave up widening again", cur, back, g_affinity.repins);
}

// Its own stop event comes as the parameter: a thread that outlived a join (below) never waits on the next one's.
DWORD WINAPI AffinityWatchdog(LPVOID stop)
{
    while (WaitForSingleObject(static_cast<HANDLE>(stop), kAffinityPollMs) == WAIT_TIMEOUT) PollAffinity();
    return 0;
}

void StartWatchdog()
{
    g_watchdogStop = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (g_watchdogStop) g_watchdog = CreateThread(nullptr, 64 * 1024, AffinityWatchdog, g_watchdogStop, STACK_SIZE_PARAM_IS_A_RESERVATION, nullptr);
    if (g_watchdog) { SetThreadPriority(g_watchdog, THREAD_PRIORITY_HIGHEST); return; }   // it must run on the one CPU
    if (g_watchdogStop) { CloseHandle(g_watchdogStop); g_watchdogStop = nullptr; }
    LogAffinity("no watchdog thread, a re-pin will stay", 0, 0);
}

// Before the restore, so that nothing widens again behind it. It only ever makes system calls, so the wait is
// short; if it somehow is not, the stop event is left for it rather than closed under it.
void StopWatchdog()
{
    if (!g_watchdog) return;
    SetEvent(g_watchdogStop);
    if (WaitForSingleObject(g_watchdog, 2000) == WAIT_OBJECT_0) CloseHandle(g_watchdogStop);
    CloseHandle(g_watchdog);
    g_watchdog = g_watchdogStop = nullptr;
}

void WidenAffinity()
{
    if (g_affinity.active) return;
    DWORD_PTR sys = 0;
    const DWORD_PTR before = CurrentProcessMask(&sys);
    if (!moviepace::IsPinned(before, sys)) { LogAffinity("not pinned, left alone", before, sys); return; }
    DWORD_PTR after = before;
    for (int attempt = 0; attempt < 3; ++attempt) {
        SetProcessMaskNt(sys);
        after = CurrentProcessMask();
        if (moviepace::WidenTook(before, after)) {
            moviepace::OnWidened(g_affinity, before, after);
            LogAffinity("widened", before, after);
            StartWatchdog();
            return;
        }
    }
    LogAffinity("could NOT be widened", before, after);   // playback carries on pinned, as it always did
}

void RestoreAffinity()
{
    StopWatchdog();
    if (!g_affinity.active) return;
    const DWORD_PTR cur = CurrentProcessMask();
    if (moviepace::ShouldRestore(g_affinity, cur)) {
        DWORD_PTR back = cur;
        for (int attempt = 0; attempt < 3 && !moviepace::RestoreTook(g_affinity, back); ++attempt) {
            SetProcessMaskNt(g_affinity.pinned);
            back = CurrentProcessMask();
        }
        LogAffinity(moviepace::RestoreTook(g_affinity, back) ? "restored" : "could NOT be restored", cur, back, g_affinity.repins);
    } else {
        LogAffinity("already re-pinned, left alone", g_affinity.wide, cur, g_affinity.repins);
    }
    g_affinity = moviepace::AffinityState();
}

// Decoder threads for the mask the movie will run on: the widened one, or as things stand if there is none.
int DecoderThreadCount()
{
    const DWORD_PTR proc = g_affinity.active ? g_affinity.wide : CurrentProcessMask();
    if (!proc) return 1;
    int cores = 0;
    DWORD len = 0;
    GetLogicalProcessorInformation(nullptr, &len);
    if (GetLastError() == ERROR_INSUFFICIENT_BUFFER && len >= sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION)) {
        std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION> info(len / sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION));
        if (GetLogicalProcessorInformation(info.data(), &len)) {
            std::vector<uintptr_t> masks;
            for (const auto& i : info) if (i.Relationship == RelationProcessorCore) masks.push_back(i.ProcessorMask);
            cores = moviepace::CountCores(masks.data(), static_cast<int>(masks.size()), proc);
        }
    }
    if (cores <= 0) cores = moviepace::CoresFromCpus(moviepace::BitCount(proc));
    return moviepace::DecoderThreads(cores);
}

// noinline: PlayGuarded's __try frame must stay free of C++ objects (its contract); inlining this into it
// would move every destructor-bearing local there.
__declspec(noinline)
void DecodeAndPlay(const char* name, const char* path, HWND hwnd, int scrW, int scrH,
                   PresentMode mode, DDrawPresenter* dp, int swsFlags)
{
    AVFormatContext* fmt = nullptr;
    if (avformat_open_input(&fmt, path, nullptr, nullptr) < 0) { Dbg("[uimod] movie open fail\n"); return; }
    if (avformat_find_stream_info(fmt, nullptr) < 0) { avformat_close_input(&fmt); return; }

    const int vId = av_find_best_stream(fmt, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    if (vId < 0) { avformat_close_input(&fmt); return; }
    AVStream* vs = fmt->streams[vId];
    const AVCodec* dec = avcodec_find_decoder(vs->codecpar->codec_id);
    AVCodecContext* ctx = avcodec_alloc_context3(dec);
    avcodec_parameters_to_context(ctx, vs->codecpar);
    // Threaded decode: the HD pack is 1280x960..2368x1152 H.264 and single-threaded decode can't hold
    // its frame rate at 4K. The count is fixed here at open, so the widening comes first (a restore is
    // PlayGuarded's job, on every way out). Harmless for the tiny .wve streams: tqi has no threading.
    if (moviepace::WantsMoreCores(vs->codecpar->width, vs->codecpar->height)) WidenAffinity();
    const int decoderThreads = DecoderThreadCount();
    ctx->thread_count = decoderThreads;
    ctx->thread_type  = FF_THREAD_FRAME | FF_THREAD_SLICE;
    if (!dec || avcodec_open2(ctx, dec, nullptr) < 0) {
        avcodec_free_context(&ctx); avformat_close_input(&fmt); return;
    }

    double fps = av_q2d(vs->avg_frame_rate);
    if (!(fps >= 1.0 && fps <= 120.0)) fps = 15.0;
    const double frameMs = 1000.0 / fps;
    const double tbMs = av_q2d(vs->time_base) * 1000.0;
    const double lengthMs = vs->duration > 0 ? static_cast<double>(vs->duration) * tbMs
                          : fmt->duration > 0 ? static_cast<double>(fmt->duration) / 1000.0 : 0.0;

    // ---- audio (optional; video plays silently if any of this fails) ----
    int aId = av_find_best_stream(fmt, AVMEDIA_TYPE_AUDIO, -1, -1, nullptr, 0);
    AVCodecContext* actx = nullptr;
    SwrContext* swr = nullptr;
    movieaudio::Sink* sink = nullptr;   // XAudio2, or waveOut where Windows has no xaudio2_9.dll (movieaudio.h)
    std::vector<uint8_t*> audioBufs;
    int rate = 22050;
    if (aId >= 0) {
        AVStream* as = fmt->streams[aId];
        const AVCodec* ad = avcodec_find_decoder(as->codecpar->codec_id);
        actx = avcodec_alloc_context3(ad);
        avcodec_parameters_to_context(actx, as->codecpar);
        if (as->codecpar->sample_rate > 0) rate = as->codecpar->sample_rate;
        AVChannelLayout outcl = AV_CHANNEL_LAYOUT_STEREO;
        bool ok = ad && avcodec_open2(actx, ad, nullptr) == 0;
        if (ok) ok = swr_alloc_set_opts2(&swr, &outcl, AV_SAMPLE_FMT_S16, rate,
                                         &actx->ch_layout, actx->sample_fmt, actx->sample_rate,
                                         0, nullptr) == 0 && swr_init(swr) == 0;
        if (ok) {
            movieaudio::Verdict v;
            sink = movieaudio::Open(g_audioMode, rate, v);
            g_activeSink = sink;
            ReportAudioVerdict(v);
            ok = sink != nullptr;
        }
        if (!ok) { // partial failure -> fall back to video-only
            if (swr) swr_free(&swr);
            if (actx) avcodec_free_context(&actx);
            swr = nullptr; actx = nullptr; aId = -1;
        }
    }

    // Full-screen back buffer (black bars stay; only the dst region is overwritten per frame).
    HDC memDC = CreateCompatibleDC(nullptr);
    BITMAPINFO bbi{};
    bbi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bbi.bmiHeader.biWidth = scrW; bbi.bmiHeader.biHeight = -scrH;
    bbi.bmiHeader.biPlanes = 1; bbi.bmiHeader.biBitCount = 32; bbi.bmiHeader.biCompression = BI_RGB;
    void* bb = nullptr;
    HBITMAP hbb = CreateDIBSection(nullptr, &bbi, DIB_RGB_COLORS, &bb, nullptr, 0);
    HGDIOBJ oldbm = (hbb && memDC) ? SelectObject(memDC, hbb) : nullptr;
    const int bbStride = scrW * 4;
    if (bb) memset(bb, 0, static_cast<size_t>(bbStride) * scrH);

    SwsContext* sws = nullptr;
    RECT dst{}; int curW = 0, curH = 0, curFmt = -1;

    AVPacket* pkt = av_packet_alloc();
    AVFrame*  frm = av_frame_alloc();
    AVFrame*  afrm = av_frame_alloc();
    AVFrame*  held = av_frame_alloc();     // the newest frame that was NOT drawn: the end may need it
    bool skip = false, started = false, haveBasePts = false, haveHeld = false;
    int64_t basePts = 0;
    double t0 = 0, lastRelMs = -frameMs, lastTargetMs = 0;
    moviepace::Pacer pacer(frameMs);
    moviepace::AudioTimeline audioClock;
    std::vector<uint8_t> pendingPcm;       // sound not yet with the device: held for the first picture, then one buffer per read
    unsigned droppedPackets = 0;

    // Push the composed back buffer to the screen (shared by the frame loop and the caption stage).
    auto present = [&]() {
        if (mode == PRESENT_DDRAW) {
            if (dp) dp->Present(bb, bbStride);
        } else if (!IsIconic(hwnd)) {
            if (HDC w = GetDC(hwnd)) {
                RECT cr;
                if (VidModeStretched() && GetClientRect(hwnd, &cr) && cr.right > 0 && cr.bottom > 0 &&
                    (cr.right != scrW || cr.bottom != scrH)) {
                    // the window was resized mid-movie (we compose at the client size it started with):
                    // a cheap stretch keeps the picture filling it
                    SetStretchBltMode(w, COLORONCOLOR);
                    StretchBlt(w, 0, 0, cr.right, cr.bottom, memDC, 0, 0, scrW, scrH, SRCCOPY);
                } else {
                    BitBlt(w, 0, 0, scrW, scrH, memDC, 0, 0, SRCCOPY);
                }
                ReleaseDC(hwnd, w);
                ValidateRect(hwnd, nullptr);
                GpuInvalidate();   // the window shows the movie: a GPU re-present (window lines) must not paint over it
            }
        }
    };

    auto scaleToBack = [&](AVFrame* f) {
        if (!sws || f->width != curW || f->height != curH || f->format != curFmt) {
            curW = f->width; curH = f->height; curFmt = f->format;
            dst = FitRect(curW, curH, scrW, scrH);
            if (sws) sws_freeContext(sws);
            sws = sws_getContext(curW, curH, static_cast<AVPixelFormat>(curFmt),
                                 dst.right - dst.left, dst.bottom - dst.top, AV_PIX_FMT_BGRA,
                                 swsFlags, nullptr, nullptr, nullptr);
            memset(bb, 0, static_cast<size_t>(bbStride) * scrH); // refresh bars on size change
        }
        if (sws) {
            uint8_t* d0 = static_cast<uint8_t*>(bb)
                        + static_cast<size_t>(dst.top) * bbStride + static_cast<size_t>(dst.left) * 4;
            uint8_t* dd[4] = { d0, nullptr, nullptr, nullptr };
            int      dl[4] = { bbStride, 0, 0, 0 };
            sws_scale(sws, f->data, f->linesize, 0, curH, dd, dl);
        }
    };

    // Wait for a time on the clock, pumping for skip/alt-tab and watching the affinity. At least one pump
    // always happens, so Esc works however late we are.
    auto holdUntil = [&](double targetMs) {
        while (!skip) {
            Pump(&skip);
            if (skip) break;
            const double now = NowMs();
            if (now >= targetMs) break;
            const double rem = targetMs - now;
            Sleep(rem > 10.0 ? 10 : static_cast<DWORD>(rem) + 1);
        }
    };

    // What has been read goes to the device as ONE buffer: XAudio2 refuses past 64 queued, and a clip can end in
    // a few seconds of nothing but sound (the Cloudbase movie, 81 packets at once).
    auto submitAudio = [&]() {
        if (!sink || !started || pendingPcm.empty()) return;
        bool taken = false;
        if (uint8_t* p = static_cast<uint8_t*>(malloc(pendingPcm.size()))) {
            memcpy(p, pendingPcm.data(), pendingPcm.size());
            taken = sink->Submit(p, static_cast<uint32_t>(pendingPcm.size()));
            if (taken) audioBufs.push_back(p);
            else free(p);
        }
        if (!taken) audioClock.OnRefused();
        pendingPcm.clear();
    };

    // The first picture is on the screen: the movie's clock and its sound start now, together. Frame-threaded
    // decoding delivers that picture several packets after the first sound packet has been read.
    auto startClock = [&]() {
        t0 = NowMs();
        started = true;
        audioClock.Start(t0);
        submitAudio();
    };

    // Receive every frame the decoder has ready and show the ones that are in time. Also used to DRAIN
    // the (frame-threaded) decoder at EOF. Returns how many frames came out.
    auto showFrames = [&]() -> int {
        int delivered = 0;
        while (!skip && avcodec_receive_frame(ctx, frm) == 0) {
            ++delivered;
            // The schedule comes from the frame's own timestamp: when frames are discarded a counter
            // would run early. No timestamp at all = one frame after the last, the old rule.
            const int64_t ts = frm->best_effort_timestamp;
            double relMs;
            if (ts != AV_NOPTS_VALUE) {
                if (!haveBasePts) {
                    haveBasePts = true; basePts = ts;
                    pacer.AllowDiscard(ctx->codec_id == AV_CODEC_ID_H264 && lengthMs > 0);
                }
                relMs = static_cast<double>(ts - basePts) * tbMs;
            } else {
                relMs = lastRelMs + frameMs;
            }
            lastRelMs = relMs;
            lastTargetMs = t0 + relMs + audioClock.ShiftMs();

            const double now = NowMs();
            if (started && pacer.OnFrame(now, lastTargetMs) == moviepace::kSkip) {
                // Late: nothing is scaled or drawn. It is kept in case it turns out to be the last.
                av_frame_unref(held);
                av_frame_move_ref(held, frm);
                haveHeld = true;
                Pump(&skip);
                continue;
            }
            scaleToBack(frm);
            haveHeld = false;
            if (started) {
                holdUntil(lastTargetMs);
                if (skip) break;
                present();
            } else {
                present();
                startClock();
                lastTargetMs = t0;
            }
            pacer.OnShown(NowMs());
        }
        return delivered;
    };

    // Decode audio -> S16 stereo -> append to what waits for the device.
    auto feedAudio = [&]() {
        while (avcodec_receive_frame(actx, afrm) == 0) {
            const int maxOut = swr_get_out_samples(swr, afrm->nb_samples);
            if (maxOut <= 0) continue;
            const size_t have = pendingPcm.size();
            pendingPcm.resize(have + static_cast<size_t>(maxOut) * 4);   // s16 stereo
            uint8_t* outp[1] = { pendingPcm.data() + have };
            const int got = swr_convert(swr, outp, maxOut,
                                        const_cast<const uint8_t**>(afrm->data), afrm->nb_samples);
            pendingPcm.resize(have + (got > 0 ? static_cast<size_t>(got) * 4 : 0));
            if (got <= 0) continue;
            const double durMs = got * 1000.0 / rate;
            if (started) { audioClock.OnSubmit(NowMs(), durMs); continue; }
            audioClock.Queue(durMs);
            const double dropMs = audioClock.TrimPending(moviepace::kPreRollKeepMs);
            if (dropMs > 0) {   // whole stereo frames, the oldest first
                size_t drop = static_cast<size_t>(dropMs * rate / 1000.0) * 4;
                if (drop > pendingPcm.size()) drop = pendingPcm.size();
                pendingPcm.erase(pendingPcm.begin(), pendingPcm.begin() + static_cast<std::ptrdiff_t>(drop));
            }
        }
    };

    // Video packets wait here while the file is read further ahead, because the sound has to be read in
    // the same order: it is what keeps the sound queue topped up while a picture is slow.
    std::deque<AVPacket*> queue;
    size_t queuedBytes = 0;
    bool demuxEof = false;
    size_t videoSinceAudio = 0;       // a track that has ended must not be waited for
    double lastPacketMs = 0;

    auto takePacket = [&](size_t i) {
        AVPacket* q = queue[i];
        queuedBytes -= static_cast<size_t>(q->size);
        queue.erase(queue.begin() + static_cast<std::ptrdiff_t>(i));
        return q;
    };

    while (!skip && hbb && bb) {
        const auto audioLive = [&]() { return sink && videoSinceAudio < moviepace::kAudioEndedPackets; };
        while (!demuxEof && moviepace::WantDemux(audioLive(), audioClock.LeadMs(NowMs()), queue.size(), queuedBytes)) {
            if (av_read_frame(fmt, pkt) < 0) { demuxEof = true; break; }
            if (pkt->stream_index == vId) {
                ++videoSinceAudio;
                if (pkt->pts != AV_NOPTS_VALUE) lastPacketMs = static_cast<double>(pkt->pts) * tbMs;
                if (AVPacket* q = av_packet_alloc()) {
                    av_packet_move_ref(q, pkt);
                    queuedBytes += static_cast<size_t>(q->size);
                    queue.push_back(q);
                }
            } else if (sink && pkt->stream_index == aId) {
                videoSinceAudio = 0;
                if (avcodec_send_packet(actx, pkt) == 0) feedAudio();
            }
            av_packet_unref(pkt);
        }
        submitAudio();
        if (queue.empty()) { if (demuxEof) break; continue; }

        const bool nearEnd = moviepace::NearEnd(demuxEof, lengthMs, lastPacketMs);

        // Last resort: drawing nothing was not enough, the picture is falling behind the sound. The jump lands on
        // the newest keyframe that is already due, and needs timestamps to know which one that is.
        if (started && haveBasePts && moviepace::ShouldDropToKeyframe(pacer.LateMs())) {
            const double now = NowMs();
            for (size_t i = queue.size(); i-- > 1; ) {
                const AVPacket* k = queue[i];
                if (!(k->flags & AV_PKT_FLAG_KEY) || k->pts == AV_NOPTS_VALUE) continue;
                if (t0 + static_cast<double>(k->pts - basePts) * tbMs + audioClock.ShiftMs() > now) continue;
                for (size_t n = 0; n < i; ++n) { AVPacket* q = takePacket(0); av_packet_free(&q); ++droppedPackets; }
                break;
            }
        }

        AVPacket* q = takePacket(0);
        ctx->skip_frame = pacer.DiscardNonRef(nearEnd) ? AVDISCARD_NONREF : AVDISCARD_DEFAULT;
        pacer.OnPacketSent();
        const int delivered = avcodec_send_packet(ctx, q) == 0 ? showFrames() : 0;
        av_packet_free(&q);
        if (!delivered) Pump(&skip);   // a discarded or delayed picture: the keyboard still gets its turn
    }
    const bool eof = demuxEof && queue.empty();
    for (AVPacket* q : queue) av_packet_free(&q);
    queue.clear();

    if (eof && !skip && hbb && bb) {
        ctx->skip_frame = AVDISCARD_DEFAULT;
        avcodec_send_packet(ctx, nullptr);   // flush: the threaded decoder still holds the tail frames
        showFrames();
        // The true last frame ends up in `bb` for the caption, even if it was too late to be drawn.
        if (!skip && haveHeld) { scaleToBack(held); present(); haveHeld = false; }
        if (started && !skip) holdUntil(lastTargetMs + frameMs);
    }
    {
        char l[260];
        _snprintf_s(l, sizeof l, _TRUNCATE,
                    "[uimod] movie pacing: %s threads=%d shown=%u skipped=%u discard_entries=%u dropped_packets=%u max_late=%.0fms "
                    "sound_underruns=%u sound_shift=%.0fms\n",
                    name ? name : "(movie)", decoderThreads, pacer.Shown(), pacer.Skipped(), pacer.DiscardEntries(), droppedPackets,
                    pacer.MaxLateMs(), audioClock.Underruns(), audioClock.ShiftMs());
        UimodLog(l);
    }

    // Vanilla's post-movie caption (title + typewriter benefit text over the held last frame). Like
    // vanilla, a skipped movie gets none. Laid out in the ORIGINAL clip's 640x480 movie-mode space.
    if (eof && !skip && sws && curW > 0) {
        int natW = 0, natH = 0;
        NativeClipSize(name, curW, curH, &natW, &natH);
        CaptionTarget ct{ memDC, scrW, scrH, dst, natW, natH };
        RunMovieCaption(name, ct, present, [&]() { Pump(&skip); return skip; });
    }

    if (sink) {
        if (sink->Dropped()) {                 // a device yanked mid-movie, a queue limit: dropouts, said once
            char l[160];
            _snprintf_s(l, sizeof l, _TRUNCATE, "[uimod] movie audio: %s refused %u buffer(s) during %s\n",
                        movieaudio::BackendName(sink->Kind()), sink->Dropped(), name ? name : "(movie)");
            UimodLog(l);
        }
        sink->Stop(); delete sink;             // before the buffers it still reads are freed
        g_activeSink = nullptr;
    }
    if (swr) swr_free(&swr);
    if (actx) avcodec_free_context(&actx);
    for (uint8_t* p : audioBufs) free(p);
    if (sws) sws_freeContext(sws);
    av_frame_free(&frm);
    av_frame_free(&afrm);
    av_frame_free(&held);
    av_packet_free(&pkt);
    avcodec_free_context(&ctx);
    avformat_close_input(&fmt);
    if (oldbm) SelectObject(memDC, oldbm);
    if (hbb) DeleteObject(hbb);
    if (memDC) DeleteDC(memDC);
}

// A codec DLL bind that fails INSIDE the player -- the probe passed, the file changed under us, or an export
// the probe did not ask for -- raises the delay-load helper's exception (0xC06D007E: module, 0xC06D007F:
// procedure). Caught here it ends the MOVIE, not the game: this frame holds no C++ objects, so the
// caller's GameSoundHold / FlipBlock / DDrawPresenter still unwind normally. (The player's own decoder
// objects leak once; the delay-load hook has already logged which DLL and symbol.) Anything else is left
// to the system: a real crash must stay a crash.
DWORD DelayLoadFilter(DWORD code)
{
    return (code == 0xC06D007Eu || code == 0xC06D007Fu) ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH;
}

void PlayGuarded(const char* name, const char* path, HWND hwnd, int scrW, int scrH, PresentMode mode,
                 DDrawPresenter* dp, int swsFlags)
{
    ++g_playDepth;
    __try {
        __try {
            DecodeAndPlay(name, path, hwnd, scrW, scrH, mode, dp, swsFlags);
        } __except (DelayLoadFilter(GetExceptionCode())) {
            char l[200];
            _snprintf_s(l, sizeof l, _TRUNCATE, "[uimod] movie aborted: a codec DLL bind failed inside the player (exception 0x%08lX); "
                                                "see the delay-load line above\n", static_cast<unsigned long>(GetExceptionCode()));
            UimodLog(l);
            if (g_activeSink) { g_activeSink->Stop(); delete g_activeSink; g_activeSink = nullptr; }   // no exception in flight here
        }
    } __finally {
        // Every way out of the movie comes through here: the end, a skip, an open or decoder failure, the handler
        // above, and any exception something further up the stack goes on to catch.
        if (--g_playDepth == 0) RestoreAffinity();
    }
}

} // namespace

// While a cinematic owns the window, the display-topology restore waits (vidmode.cpp): it would re-place the
// window under the movie's frames.
static volatile LONG g_movieDepth = 0;
bool MovieActive() { return g_movieDepth != 0; }

extern "C" void __cdecl uimod_PlayMovie(const char* name)
{
    struct Depth {
        Depth() { InterlockedIncrement(&g_movieDepth); }
        ~Depth() { InterlockedDecrement(&g_movieDepth); }
    } depth;
    Dbg("[uimod] uimod_PlayMovie name=");
    Dbg(name ? name : "(null)");
    Dbg("\n");

    HWND hwnd = *reinterpret_cast<HWND*>(At(kVA_phWnd));
    if (!hwnd) hwnd = GetActiveWindow();
    int scrW = *reinterpret_cast<int*>(At(kVA_screenW));
    int scrH = *reinterpret_cast<int*>(At(kVA_screenH));
    if (scrW <= 0 || scrH <= 0) {
        RECT rc{};
        if (hwnd) GetClientRect(hwnd, &rc);
        scrW = rc.right  ? rc.right  : GetSystemMetrics(SM_CXSCREEN);
        scrH = rc.bottom ? rc.bottom : GetSystemMetrics(SM_CYSCREEN);
    }

    // Borderless / Windowed: the window's client is not the backbuffer's size. Compose the movie at the
    // CLIENT size (the decoder's scaler fits it anyway) so every frame is a plain BitBlt -- stretching a
    // backbuffer-size frame through GDI per frame starved the decode loop (slow video, choppy audio).
    if (g_pracx && VidModeStretched() && hwnd) {
        RECT rc{};
        if (GetClientRect(hwnd, &rc) && rc.right > 0 && rc.bottom > 0) { scrW = rc.right; scrH = rc.bottom; }
    }

    char path[MAX_PATH];
    if (scrW > 0 && scrH > 0 && hwnd && BuildSourcePath(name, path, sizeof path)) {
        Dbg("[uimod] playing: "); Dbg(path); Dbg("\n");
        GameSoundHold noGameSound;   // undone last, after the repaint, as the native exit does
        FlipBlock noGameFlips;   // released at the end of this block, after any mode restore
        if (g_pracx) {
            // PRACX presents the game via GDI to a true-colour, desktop-res window -> BitBlt there.
            PlayGuarded(name, path, hwnd, scrW, scrH, PRESENT_BITBLT, nullptr, SWS_BILINEAR);
        } else {
            // Pristine: DDrawCompat palettizes screen GDI, so present true colour via DirectDraw.
            // Use the GAME'S resolution at 32-bit (only the colour depth changes, not the
            // resolution) so DDrawCompat keeps upscaling its surface to the screen exactly as
            // before -- changing the resolution here left the game showing 1:1 in a corner on exit.
            // Falls back to the game-window blit if DirectDraw setup fails (functional, palettized).
            DDrawPresenter dp;
            if (dp.Begin(hwnd, scrW, scrH)) {
                PlayGuarded(name, path, hwnd, scrW, scrH, PRESENT_DDRAW, &dp, SWS_BILINEAR);
                dp.End();
            } else {
                Dbg("[uimod] DirectDraw begin failed -> fallback to game-window blit\n");
                PlayGuarded(name, path, hwnd, scrW, scrH, PRESENT_BITBLT, nullptr, SWS_BILINEAR);
            }
        }
    } else {
        Dbg("[uimod] no playable source / no window -- skipping movie\n");
    }

    if (g_pracx && hwnd)
        PostMessageA(hwnd, kWM_MOVIEOVER, 0, 0);

    Dbg("[uimod] uimod_PlayMovie returning\n");
}

// The codec DLLs, in dependency order, with the majors this translation unit was compiled against. The
// probe asks each DLL its version so a stray DLL of the right NAME but another build (a different ffmpeg
// in the game folder) is caught before the first delay-load bind would crash on a missing export.
static const codecs::Lib kCodecLibs[] = {
    { L"avutil-60.dll",     "avutil_version",     LIBAVUTIL_VERSION_MAJOR,     LIBAVUTIL_VERSION_MINOR },
    { L"swresample-6.dll",  "swresample_version", LIBSWRESAMPLE_VERSION_MAJOR, LIBSWRESAMPLE_VERSION_MINOR },
    { L"swscale-9.dll",     "swscale_version",    LIBSWSCALE_VERSION_MAJOR,    LIBSWSCALE_VERSION_MINOR },
    { L"avcodec-62.dll",    "avcodec_version",    LIBAVCODEC_VERSION_MAJOR,    LIBAVCODEC_VERSION_MINOR },
    { L"avformat-62.dll",   "avformat_version",   LIBAVFORMAT_VERSION_MAJOR,   LIBAVFORMAT_VERSION_MINOR },
};

// The folder `module` lives in, or false when the path does not fit (GetModuleFileNameW truncates silently
// and returns the capacity).
static bool ModuleFolder(HMODULE module, wchar_t* dir, DWORD cap)
{
    const DWORD n = GetModuleFileNameW(module, dir, cap);
    if (n == 0 || n >= cap) return false;
    wchar_t* slash = wcsrchr(dir, L'\\');
    if (!slash) return false;
    *slash = 0;
    return true;
}

bool MovieCodecsOk(char* log, size_t logCap, char* notice, size_t noticeCap, char* sig, size_t sigCap)
{
    static codecs::Report report;
    HMODULE self = nullptr;
    wchar_t dir[MAX_PATH];
    bool haveDir = GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                      reinterpret_cast<LPCWSTR>(&MovieCodecsOk), &self) &&
                   ModuleFolder(self, dir, MAX_PATH);                    // uimod.dll's folder ...
    if (!haveDir) haveDir = ModuleFolder(nullptr, dir, MAX_PATH);      // ... else the exe's (the same folder today)
    if (haveDir) codecs::Probe(dir, kCodecLibs, static_cast<int>(sizeof kCodecLibs / sizeof *kCodecLibs), report);
    else { codecs::ReportFolderUnknown(report); dir[0] = L'?'; dir[1] = 0; }
    if (report.Ok()) {
        _snprintf_s(log, logCap, _TRUNCATE, "[uimod] codecs: all %d DLLs present and the shipped builds (%ls)\n", report.nLibs, dir);
        notice[0] = 0; sig[0] = 0;
        return true;
    }
    codecs::DescribeForLog(report, "[uimod] codecs: ", log, logCap);
    codecs::NoticeBody(report, notice, noticeCap);
    codecs::Signature(report, sig, sigCap);
    return false;
}

// A delay-load bind that still fails (a DLL that passed the probe and vanished since, an export the probe
// did not ask for) raises the linker's exception next; this logs WHICH DLL and symbol first, so the crash
// in uimod.log explains itself. Returning 0 keeps the default behaviour.
static FARPROC WINAPI DelayLoadFailure(unsigned reason, PDelayLoadInfo info)
{
    char line[320];
    if (reason == dliFailLoadLib)
        _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] delay-load FAILED: %s could not be loaded (error %lu)\n",
                    info && info->szDll ? info->szDll : "?", info ? info->dwLastError : 0ul);
    else
        _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] delay-load FAILED: %s has no %s (error %lu)\n",
                    info && info->szDll ? info->szDll : "?",
                    info && info->dlp.fImportByName && info->dlp.szProcName ? info->dlp.szProcName : "(ordinal)",
                    info ? info->dwLastError : 0ul);
    UimodLog(line);
    return nullptr;
}
extern "C" const PfnDliHook __pfnDliFailureHook2 = DelayLoadFailure;

void InstallMovieHook(bool pracx)
{
    g_pracx = pracx;

    // The sound backend, decided from the ini and probed now so uimod.log says before the first
    // movie whether this Windows has XAudio2 (Windows 7 / 8.1 do not -> waveOut) or nothing.
    {
        char ini[MAX_PATH + 24];
        const DWORD n = GetModuleFileNameA(nullptr, ini, MAX_PATH);
        char* slash = nullptr;
        for (char* p = ini; n && n < MAX_PATH && *p; ++p)
            if (*p == '\\' || *p == '/') slash = p;
        if (slash && (slash + 1 - ini) + sizeof "Alpha Centauri.ini" <= sizeof ini) {
            lstrcpyA(slash + 1, "Alpha Centauri.ini");
            g_audioMode = movieaudio::ModeFromIni(ini);
        }
        char probe[320], line[352];
        movieaudio::Probe(g_audioMode, probe, sizeof probe);
        _snprintf_s(line, sizeof line, _TRUNCATE, "[uimod] %s\n", probe);
        UimodLog(line);
    }

    BYTE* entry = At(kVA_amovie);
    BYTE* fn = reinterpret_cast<BYTE*>(&uimod_PlayMovie);
    DWORD oldProt = 0;

    if (pracx) {
        if (entry[0] != 0xE9)
            Dbg("[uimod] WARN: amovie entry not E9 (PRACX movie hook missing?)\n");

        BYTE* rel = entry + 1;  // rel32 of PRACX's JMP -> currently PRACXShowMovie
        if (VirtualProtect(rel, 4, PAGE_EXECUTE_READWRITE, &oldProt)) {
            *reinterpret_cast<int32_t*>(rel) = static_cast<int32_t>(fn - (rel + 4));
            VirtualProtect(rel, 4, oldProt, &oldProt);
            FlushInstructionCache(GetCurrentProcess(), entry, 5);
            Dbg("[uimod] movie hook re-pointed to uimod_PlayMovie (PRACX)\n");
        } else {
            Dbg("[uimod] ERROR: VirtualProtect failed (PRACX rel32)\n");
        }
    } else {
        // Pristine (no PRACX): install our own E9 hook at the movie entry. We present via a layered
        // window (true colour, see uimod_PlayMovie) so we control decode + scaling quality for the
        // original .wve too (better-than-native upscaling), not just AI videos.
        if (VirtualProtect(entry, 5, PAGE_EXECUTE_READWRITE, &oldProt)) {
            entry[0] = 0xE9;
            *reinterpret_cast<int32_t*>(entry + 1) = static_cast<int32_t>(fn - (entry + 5));
            VirtualProtect(entry, 5, oldProt, &oldProt);
            FlushInstructionCache(GetCurrentProcess(), entry, 5);
            Dbg("[uimod] movie hook installed (native E9)\n");
        } else {
            Dbg("[uimod] ERROR: VirtualProtect failed (native entry)\n");
        }
    }
}
