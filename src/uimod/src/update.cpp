// uimod update checker -- the Win32 / engine shell around update_core.h.
//
// The DLL decides nothing and trusts nothing from the network. At Init it starts ONE worker
// thread that runs the resident installer as a hidden child:
//   <game>\LongevityMods\updater\tools\python\python.exe <...>\scripts\install.py --check --game-dir <game> [--manifest <v>]
// with stdout on an anonymous pipe, and reads back the installer's tiny `key=value` answer (the
// installer fetched the manifest, verified its Ed25519 signature and applied the ONE update rule).
// The main thread never waits: the message hook's UpdatePoll() picks the answer up whenever it is
// ready, logs it, and waits for a moment the player may be interrupted:
//   * the TOP of the main menu (the TOPMENU strip is the one modal, nothing stacked on it), or
//   * the START of the human player's turn (Console_human_turn entered, its input pump idle, no
//     engine popup up, the player has not clicked or typed yet).
// Then it posts a private message and, when THAT message comes off the queue (so the engine
// resumes on our WM_NULL, never on a stale input message), shows the engine's own art-styled
// popup (X_pops_18 on a label file we write, picture longevity_sm.pcx) -- the same way
// aivis.cpp shows the GETOUT reply and Thinker shows its Alt+H menu inside the TOPMENU loop.
//
// Replies: "Quit and update" (in-game: with or without a save first), "Not now" (nothing written,
// next launch asks again) and "Don't ask me again" ([Longevity] DeclinedUpdates: `<item>:<ver>`
// for an update offer, `new:<id>:*` for a pack the player does not have). The installer's check
// applies them under the maintainer's rule of 2026-10-31 (install.py check_report): while anything
// installed has an UNDECLINED update, every offer is listed again, declined ones included; while the
// CORE is declined, nothing is offered, new packs included (the updater would bring the core along);
// a declined stale pack hides only itself; otherwise new packs show, minus the declined ones.
// "Reset Skipped Updates" clears the key.
// New optional packs get their own popup each. "Yes" spawns run-install.bat --update --game-dir <dir> --wait-pid <pid> --only-listed [--modules ...] (exactly the packs the popups named) in a
// visible console and leaves the game the way the engine itself does: at the menu by making
// TOPMENU return EXIT GAME, in a game by the Quit menu's own steps (ControlTurnA = 1).
//
// Threading: the worker touches no engine memory and never logs (UimodLog is fopen-per-call);
// it fills g_result and publishes with InterlockedExchange(&g_ready, 1); the main thread copies
// it once. Any fault in the worker is caught by SEH and read as "could not check".
//
// Offline / broken network = VANILLA: exit 12 (or 0 with no lines) is one log line and nothing
// else. No console flashes (CREATE_NO_WINDOW), no popup, no delay.
//
// Engine facts (work\_upd_disasm.md, 2026-09-27): TOPMENU = top_menu 0x58E360 -> Popup_start
// ("TOPMENU") + SetupWin_do_menu_2 0x4ADB20 (ret 0x58E722) -> Win_set_modal on a stack SetupWin
// (vtbl 0x66D8E8; +0x1014 = the popup, +0xFD0 = highlighted reply, -1 = ESC/EXIT). Win_set_modal
// keeps g_modal_top 0x9B7AE0 / depth 0x9B7AE4 / stack 0x9B6EF8. Console_human_turn 0x514050
// (thiscall, this = MapWin_g 0x9156B0) is called from 4 E8 sites, none touched by Thinker 5.5;
// its input pump sets MapWin_g+0x23BE4 = 1 while waiting and exits on ControlTurnA 0x9B2068.
// Quit = Console_menu_proc case 0x5D: (single player) if GameRules 0x9A649C & 0x400 (IRONMAN)
// auto_save 0x5ABD20; ControlTurnA = 1. Save Game = case 0x59 -> save_game(0) 0x5A9EB0, cdecl,
// 0 = saved. X_pops_18 returns the highlighted reply on ESC unless flags & 0x40 -> -1.
#include "modernctl.h"
#include "update.h"
#include "update_core.h"
#include "version.h"

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kImageBase = 0x400000;

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase); }
template <typename T> T Rd(uintptr_t va) { return *reinterpret_cast<T*>(At(va)); }
template <typename T> void Wr(uintptr_t va, T v) { *reinterpret_cast<T*>(At(va)) = v; }

// ---- engine addresses (all byte-checked or read-only; none in a patcher cave) ----
constexpr uintptr_t kVA_phWnd         = 0x009B7B28;   // HWND g_main_hwnd
constexpr uintptr_t kVA_GameHalted    = 0x0068F21C;   // 1 = main menu / setup, 0 = game running
constexpr uintptr_t kVA_ModalTop      = 0x009B7AE0;   // Win* g_modal_top
constexpr uintptr_t kVA_ModalDepth    = 0x009B7AE4;   // Win_set_modal nesting depth
constexpr uintptr_t kVA_BasePopCur    = 0x009B8D7C;   // Win* g_current_basepop
constexpr uintptr_t kVA_SetupWinVtbl  = 0x0066D8E8;   // the TOPMENU strip's window class
constexpr uintptr_t kVA_TopMenuRet    = 0x0058E722;   // return address of top_menu's call SetupWin_do_menu_2
constexpr size_t    kOfsSetupPopup    = 0x1014;       // SetupWin: the driving popup (non-null only in do_menu_2)
constexpr size_t    kOfsSetupSel      = 0xFD0;        // SetupWin: highlighted reply; -1 = ESC -> top_menu returns 1 (exit)
constexpr uintptr_t kVA_MapWin        = 0x009156B0;   // Console MapWin_g
constexpr size_t    kOfsInputPump     = 0x23BE4;      // Console: 1 while Console_human_turn waits for input
constexpr uintptr_t kVA_ControlTurnA  = 0x009B2068;   // 1 = leave the turn loop (quit)
constexpr uintptr_t kVA_Multiplayer   = 0x0093F660;
constexpr uintptr_t kVA_PbemActive    = 0x0093A95C;
constexpr uintptr_t kVA_GameRules     = 0x009A649C;   // 0x400 = RULES_IRONMAN
constexpr uintptr_t kVA_BaseWin       = 0x006A7628;   // BaseWin_g; +0x9C bit0 = shown (not modal)
constexpr uintptr_t kVA_TutWin        = 0x008C6E68;   // TutWin (tutorial / hint popup): NON-modal, +0x9C bit0 = shown
constexpr size_t    kOfsWinShown      = 0x9C;         // Win +0x9C bit0 = shown (Win_is_visible 0x5F7E90)
constexpr uintptr_t kVA_ConsoleHumanTurn = 0x00514050;
// E8 call sites in control_turn (single player). net_control_turn's 0x52A765 is deliberately NOT
// hooked: the gate refuses multiplayer anyway, so a token there was dead weight -- and a mod that
// patched only that site would have switched the single-player prompt off (MP audit 2026-09-27).
const uint32_t kHumanTurnSites[] = { 0x527661, 0x52826E, 0x5282C9 };
constexpr uintptr_t kVA_XPops18       = 0x005BF930;
constexpr uintptr_t kVA_SaveGame      = 0x005A9EB0;   // int __cdecl save_game(int mode): 0 = saved
constexpr uintptr_t kVA_AutoSave      = 0x005ABD20;   // void __cdecl auto_save()
constexpr uintptr_t kVA_WinReleaseModal = 0x005EE280; // void __fastcall Win_release_modal(ecx = this)

using FXPops18 = int(__cdecl*)(const char* file, const char* label, int a3, char* a4, int flags, void* sprite,
                               int x, int y, void* fn);
using FSaveGame = int(__cdecl*)(int mode);
using FAutoSave = void(__cdecl*)();
using FReleaseModal = void(__fastcall*)(void* self, void* edx);

// Plain reply-button popup, the REALLYQUIT shape. NOT 0x40: that flag turns the replies into a
// selection list with OK / CANCEL buttons (seen in-game 2026-09-27). Esc therefore returns the
// highlighted reply, 0 unless the player moved -- so reply 0 is always the safe "no".
constexpr int   kPopFlags       = 0;
constexpr UINT  kMsgPresent     = WM_APP + 0x55;
constexpr DWORD kDeadlineMs     = 30000;       // installer: 8 s socket, 20 s wall for the fetch
constexpr DWORD kRepostMs       = 3000;        // our trigger never came off the queue: arm again
constexpr size_t kCapBytes      = 64 * 1024;   // a real answer is < 1 KB

const char kLabelFile[]  = "uimod_update";     // <exe dir>\uimod_update.txt (the engine appends .txt)
const char kLabelName[]  = "UPDATE";
const char kArtFile[]    = "longevity_sm.pcx";

struct Job {
    wchar_t gameDir[MAX_PATH];
    wchar_t python[MAX_PATH + 64];
    wchar_t script[MAX_PATH + 64];
    wchar_t bat[MAX_PATH + 64];
    wchar_t logDir[MAX_PATH + 64];
    wchar_t checkLog[MAX_PATH + 64];
    wchar_t manifest[1024];
    wchar_t cmd[4096];
    DWORD   pid;
    DWORD   delayMs;            // tester's --lv-delay: the worker sleeps this long before checking
};

struct Result {
    lvupd::UpdateInfo info;
    int   exitCode;
    bool  started, timedOut, overflow;
    DWORD bytes, elapsedMs, lastErr;
    int   parseStatus, badLine;
    char  note[160];
};

Job    g_job;
Result g_result;
volatile LONG g_ready = 0;          // 0 pending, 1 published by the worker, 2 consumed by the main thread
int    g_enabled = kUpdateCheckDefault;

// Presentation state (main thread only).
enum Phase { kPhaseIdle, kPhaseWaiting, kPhaseArmed, kPhasePosted, kPhasePresenting, kPhaseDone };
Phase g_phase = kPhaseIdle;

// A startup notice queued by another module (init.cpp: a codec DLL missing -> cinematics off), shown ONCE per
// distinct problem set at the same safe moment as the update prompts and before them. It rides the same
// phases: a pending notice is "something to show" even when the check itself is off or not applicable.
char g_noticeBody[2048] = {};
char g_noticeSig[256] = {};
bool g_noticePending = false;
bool g_lastPopupShown = false;   // Popup(): did the engine draw the last prompt? (-1 is ESC as well as "not shown")
const wchar_t kNoticeKey[] = L"CinematicsNotice";     // [UIMod]: the signature of the set last shown
lvupd::UpdateInfo g_info;           // the main thread's copy of the answer
ULONGLONG g_postedAt = 0;
bool  g_turnHookArmed = false;
volatile LONG g_turnBegan = 0;      // set by the Console_human_turn call-site stub; cleared by the player's first input
void* g_humanTurn = nullptr;        // Console_human_turn's address, for the stub's jmp

void Log(const char* fmt, ...)
{
    char msg[1024];
    memcpy(msg, "[uimod] update: ", 16);
    va_list ap; va_start(ap, fmt);
    _vsnprintf_s(msg + 16, sizeof msg - 18, _TRUNCATE, fmt, ap);
    va_end(ap);
    const size_t n = strlen(msg);
    msg[n] = '\n'; msg[n + 1] = 0;
    UimodLog(msg);
}

// The game directory (the exe's), no trailing backslash (a drive root keeps its one, with or
// without a \\?\ prefix: lvupd::GameDirFromExePath).
bool GameDirW(wchar_t* out, size_t cap)
{
    wchar_t exe[MAX_PATH];
    const DWORD n = GetModuleFileNameW(nullptr, exe, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return false;
    return lvupd::GameDirFromExePath(exe, out, cap);
}

bool Join(wchar_t* out, size_t cap, const wchar_t* dir, const wchar_t* rel)
{
    const size_t dn = wcslen(dir);
    return wcscpy_s(out, cap, dir) == 0 &&
           (dn && dir[dn - 1] == L'\\' ? true : wcscat_s(out, cap, L"\\") == 0) &&
           wcscat_s(out, cap, rel) == 0;
}

// Alpha Centauri.ini beside the exe. Wide on purpose: receipt.py reads the same file with the W
// API, and the shared prefs.cpp IniPath() is ANSI (lossy on a non-ANSI game directory).
bool IniPathW(wchar_t* out, size_t cap)
{
    wchar_t dir[MAX_PATH];
    return GameDirW(dir, MAX_PATH) && Join(out, cap, dir, L"Alpha Centauri.ini");
}

bool FileExistsW(const wchar_t* p)
{
    const DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

// The true kernel version. terranx.exe carries no supportedOS manifest, so GetVersionEx and
// VerifyVersionInfo report 6.2 on every Windows from 8.1 up; ntdll's RtlGetVersion does not lie.
// Unknown (no ntdll export?) reads as 10.0: the 3.12 interpreter, today's behaviour.
void OsVersion(unsigned long* major, unsigned long* minor)
{
    *major = 10; *minor = 0;
    typedef LONG (WINAPI* RtlGetVersionFn)(RTL_OSVERSIONINFOW*);
    const HMODULE nt = GetModuleHandleW(L"ntdll.dll");
    const RtlGetVersionFn fn = nt ? reinterpret_cast<RtlGetVersionFn>(reinterpret_cast<void*>(GetProcAddress(nt, "RtlGetVersion"))) : nullptr;
    if (!fn) return;
    RTL_OSVERSIONINFOW v; memset(&v, 0, sizeof v); v.dwOSVersionInfoSize = sizeof v;
    if (fn(&v) == 0 && v.dwMajorVersion) { *major = v.dwMajorVersion; *minor = v.dwMinorVersion; }
}

void Note(Result* r, const char* what, DWORD err)
{
    r->lastErr = err;
    _snprintf_s(r->note, sizeof r->note, _TRUNCATE, "%s (error %lu)", what, err);
}

// ---- the worker ------------------------------------------------------------------------------
// No C++ objects (SEH frame), no engine memory, no logging. Reads the pipe with Peek-then-Read
// so it can never block on a pipe the child stopped writing to, closes its own copy of the write
// end at once (else EOF never comes), and does not wait for EOF at all (a grandchild could hold
// the write end): when the child exits, whatever is in the pipe is the answer.
void WorkerBody(Job* j, Result* r)
{
    static char buf[kCapBytes + 1];
    if (j->delayMs) Sleep(j->delayMs);                          // tester's --lv-delay: land the answer mid-game
    const ULONGLONG t0 = GetTickCount64();
    r->exitCode = lvupd::kCodeFailed;

    SECURITY_ATTRIBUTES sa = { sizeof sa, nullptr, TRUE };
    HANDLE rd = nullptr, wr = nullptr;
    if (!CreatePipe(&rd, &wr, &sa, 0)) { Note(r, "CreatePipe failed", GetLastError()); return; }
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);            // the child must NOT hold a reader

    HANDLE hIn = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr);
    CreateDirectoryW(j->logDir, nullptr);                        // best effort
    HANDLE hErr = CreateFileW(j->checkLog, GENERIC_WRITE, FILE_SHARE_READ, &sa, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);   // overwritten per launch: bounded growth
    if (hErr == INVALID_HANDLE_VALUE)
        hErr = CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr);

    // The child inherits ONLY its three standard handles (PROC_THREAD_ATTRIBUTE_HANDLE_LIST): with
    // plain inheritance it also got every inheritable handle of the game -- Winsock sockets among
    // them, which would have delayed a peer's hang-up while the child lived (MP audit 2026-09-27).
    STARTUPINFOEXW six; memset(&six, 0, sizeof six);
    six.StartupInfo.cb = sizeof six;
    six.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    six.StartupInfo.wShowWindow = SW_HIDE;
    six.StartupInfo.hStdInput  = hIn;
    six.StartupInfo.hStdOutput = wr;
    six.StartupInfo.hStdError  = hErr;
    HANDLE inherit[3] = { hIn, wr, hErr };
    int nInherit = 0;
    for (HANDLE h : inherit) if (h && h != INVALID_HANDLE_VALUE) inherit[nInherit++] = h;
    SIZE_T attrSize = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attrSize);
    static BYTE attrBuf[256];
    LPPROC_THREAD_ATTRIBUTE_LIST attrs = nullptr;
    DWORD flags = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS;
    if (attrSize && attrSize <= sizeof attrBuf) {
        attrs = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attrBuf);
        if (InitializeProcThreadAttributeList(attrs, 1, 0, &attrSize) &&
            UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherit,
                                      nInherit * sizeof(HANDLE), nullptr, nullptr)) {
            six.lpAttributeList = attrs;
            flags |= EXTENDED_STARTUPINFO_PRESENT;
        } else {
            attrs = nullptr;                                     // fall back to plain inheritance
            six.StartupInfo.cb = sizeof six.StartupInfo;
        }
    } else {
        six.StartupInfo.cb = sizeof six.StartupInfo;
    }
    PROCESS_INFORMATION pi; memset(&pi, 0, sizeof pi);
    // The child inherits the process error mode: a resident runtime with a missing python3xx.dll
    // must die with exit 0xC0000135, not put a "System Error" box on the player's screen.
    const UINT prevMode = SetErrorMode(0);
    SetErrorMode(prevMode | SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX | SEM_NOGPFAULTERRORBOX);
    const BOOL ok = CreateProcessW(j->python, j->cmd, nullptr, nullptr, TRUE, flags, nullptr, nullptr,
                                   &six.StartupInfo, &pi);
    const DWORD spawnErr = ok ? 0 : GetLastError();
    SetErrorMode(prevMode);
    if (attrs) DeleteProcThreadAttributeList(attrs);
    CloseHandle(wr);                                             // ours, now: only the child writes
    if (hIn  != INVALID_HANDLE_VALUE) CloseHandle(hIn);
    if (hErr != INVALID_HANDLE_VALUE) CloseHandle(hErr);
    if (!ok) { CloseHandle(rd); Note(r, "CreateProcess failed", spawnErr); return; }
    r->started = true;
    CloseHandle(pi.hThread);

    // Kill-on-close job: if the game dies mid-check, the child dies with it. Best effort (fails
    // inside a nested job on old Windows; then the child simply finishes on its own).
    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    if (job) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION li; memset(&li, 0, sizeof li);
        li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &li, sizeof li) ||
            !AssignProcessToJobObject(job, pi.hProcess)) {
            // Windows 7 has no nested jobs: a game started by GOG Galaxy / a launcher already sits in one and the
            // assign fails with ERROR_ACCESS_DENIED. The check still runs; only "the child dies with the game" is
            // lost (it ends on the installer's own network timeouts) -- said once, so a lingering python.exe in a
            // bug report has its explanation.
            Log("kill-on-close job not available (error %lu; a launcher's job on Windows 7?) -> the check runs without it",
                GetLastError());
            CloseHandle(job); job = nullptr;
        }
    }

    size_t n = 0;
    bool overflow = false;
    for (;;) {
        const DWORD w = WaitForSingleObject(pi.hProcess, 50);
        DWORD avail = 0;
        while (PeekNamedPipe(rd, nullptr, 0, nullptr, &avail, nullptr) && avail) {
            char tmp[4096];
            DWORD got = 0;
            if (!ReadFile(rd, tmp, avail < sizeof tmp ? avail : sizeof tmp, &got, nullptr) || got == 0) break;
            if (n + got <= kCapBytes) { memcpy(buf + n, tmp, got); n += got; }
            else overflow = true;                                // keep draining so the child never blocks
            avail = 0;
        }
        if (w == WAIT_OBJECT_0) break;
        if (GetTickCount64() - t0 > kDeadlineMs) {
            TerminateProcess(pi.hProcess, lvupd::kCodeFailed);
            WaitForSingleObject(pi.hProcess, 2000);
            r->timedOut = true;
            break;
        }
    }
    DWORD code = lvupd::kCodeFailed;
    if (!GetExitCodeProcess(pi.hProcess, &code) || r->timedOut) code = lvupd::kCodeFailed;
    CloseHandle(rd);
    CloseHandle(pi.hProcess);
    if (job) CloseHandle(job);

    r->exitCode  = static_cast<int>(code);
    r->bytes     = static_cast<DWORD>(n);
    r->overflow  = overflow;
    r->elapsedMs = static_cast<DWORD>(GetTickCount64() - t0);
    r->parseStatus = lvupd::ParseCheckOutput(buf, n, r->exitCode, overflow, &r->info, &r->badLine);
}

DWORD WINAPI WorkerThunk(LPVOID)
{
    __try {
        WorkerBody(&g_job, &g_result);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        lvupd::ClearInfo(&g_result.info);
        g_result.exitCode = lvupd::kCodeFailed;
        g_result.parseStatus = lvupd::kOk;
        _snprintf_s(g_result.note, sizeof g_result.note, _TRUNCATE, "worker exception 0x%08lX",
                    static_cast<unsigned long>(GetExceptionCode()));
    }
    InterlockedExchange(&g_ready, 1);
    return 0;
}

// ---- main thread: the answer ----------------------------------------------------------------

void LogResult(const Result& r)
{
    Log("check done: exit %d, %lu bytes, %lu ms%s%s%s%s", r.exitCode, r.bytes, r.elapsedMs,
        r.timedOut ? ", timed out (killed)" : "", r.overflow ? ", output over the 64 KB cap" : "",
        r.note[0] ? ", " : "", r.note);
    if (r.parseStatus != lvupd::kOk) {
        Log("answer refused (%s at line %d) -> treated as could-not-check; nothing will be shown",
            lvupd::ParseStatusName(r.parseStatus), r.badLine);
        return;
    }
    const lvupd::UpdateInfo& u = r.info;
    switch (u.code) {
    case lvupd::kCodeFailed:
        Log("could not check (offline, untrusted manifest or installer error) -> nothing will be shown");
        return;
    case lvupd::kCodeManual:
        Log("manual install required (reason '%s') -> the player will be told to download the installer", u.manualKey);
        return;
    case lvupd::kCodeNothing:
        if (u.latest[0]) Log("nothing to offer (latest %s) -> nothing will be shown", u.latest);
        else Log("nothing to offer (latest release withheld) -> nothing will be shown");
        return;
    default: break;
    }
    if (!u.hasBase && u.nStale == 0 && u.nFresh == 0) {
        Log("result: latest %s, only packs this version does not know -> nothing will be shown", u.latest);
        return;
    }
    Log("result: latest %s -> the player will be asked at the main menu or when a turn begins", u.latest);
    if (u.hasBase) Log("  item base %s>%s", u.baseFrom, u.baseTo);
    for (int i = 0; i < u.nStale; ++i)
        Log("  item stale %s \"%s\" %s>%s %llu", u.stale[i].id, u.stale[i].label, u.stale[i].from, u.stale[i].to, u.stale[i].bytes);
    for (int i = 0; i < u.nFresh; ++i)
        Log("  item new %s \"%s\" %s %llu", u.fresh[i].id, u.fresh[i].label, u.fresh[i].to, u.fresh[i].bytes);
}

bool HasSomethingToShow(const lvupd::UpdateInfo& u)
{
    if (u.code == lvupd::kCodeManual) return true;
    return u.code == lvupd::kCodeUpdates && (u.hasBase || u.nStale > 0 || u.nFresh > 0);
}

// ---- the presentation gate --------------------------------------------------------------------

// Where on the current thread's stack (between here and its base) does the engine return
// address at image offset `off` sit? 0 = not found. Takes an OFFSET so the argument pushed for
// this call can never equal the value scanned for (the exe is never relocated).
uintptr_t StackFindReturn(uintptr_t off)
{
    const NT_TIB* tib = reinterpret_cast<const NT_TIB*>(__readfsdword(0x18));
    const uintptr_t* base = static_cast<const uintptr_t*>(tib->StackBase);
    uintptr_t here = 0;
    const uintptr_t* p = &here;                                 // a local: the scan starts at this frame
    const uintptr_t want = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr)) + off;
    for (size_t i = 0; p < base && i < 64 * 1024 / sizeof(uintptr_t); ++p, ++i)
        if (*p == want) return reinterpret_cast<uintptr_t>(p);
    return 0;
}

constexpr uintptr_t kVA_HotseatTopMenuRet = 0x0058DBAA;   // multiplayer_init's `call top_menu(1)`: the HOTSEAT strip, same code

// The TOPMENU strip and the later SCENARIO / MAPMENU / HOTSEAT strips share one window class.
// Only the TOPMENU runs under top_menu's `call SetupWin_do_menu_2` (returns to 0x58E722), and
// top_menu's SetupWin W is a local ABOVE that call slot: a live hit lies below W; a stale slot
// left by an earlier top_menu under a sub-menu's frame lies above the sub-menu's own W. The
// hotseat menu is top_menu(1) called from multiplayer_init: its return slot is a LIVE frame
// above W (a stale one from an earlier visit would be below).
bool MainMenuIdle()
{
    if (Rd<int>(kVA_GameHalted) != 1) return false;
    // Exact, before any stack reasoning: TOPMENU always has both flags 0, the HOTSEAT/EMAIL strip
    // is only ever entered with PbemActive set, the lobby with MultiplayerActive set.
    if (Rd<int>(kVA_Multiplayer) != 0 || Rd<int>(kVA_PbemActive) != 0) return false;
    if (Rd<int>(kVA_ModalDepth) != 1) return false;              // the strip is the ONE modal (Load Game = a Windows dialog; credits, sub-menus stack)
    const BYTE* top = Rd<BYTE*>(kVA_ModalTop);
    if (!top || *reinterpret_cast<void* const*>(top) != At(kVA_SetupWinVtbl)) return false;
    if (*reinterpret_cast<void* const*>(top + kOfsSetupPopup) == nullptr) return false;   // popup-driven strip
    const uintptr_t w = reinterpret_cast<uintptr_t>(top);
    const uintptr_t hit = StackFindReturn(kVA_TopMenuRet - kImageBase);
    if (hit == 0 || hit >= w) return false;
    const uintptr_t hotseat = StackFindReturn(kVA_HotseatTopMenuRet - kImageBase);
    if (hotseat != 0 && hotseat > w) return false;
    return true;
}

bool TurnBegan()
{
    if (!g_turnBegan) return false;
    if (Rd<int>(kVA_GameHalted) != 0) return false;
    if (Rd<int>(kVA_Multiplayer) != 0 || Rd<int>(kVA_PbemActive) != 0) return false;   // single player only
    if (Rd<void*>(kVA_ModalTop) != nullptr || Rd<int>(kVA_ModalDepth) != 0) return false;
    if (Rd<int>(kVA_MapWin + kOfsInputPump) != 1) return false;   // Console_human_turn is waiting for the player
    if (Rd<int>(kVA_ControlTurnA) != 0) return false;
    if (At(kVA_BaseWin)[kOfsWinShown] & 1) return false;         // the base screen is up (not modal)
    if (At(kVA_TutWin)[kOfsWinShown] & 1) return false;          // a tutorial hint is up (not modal either): let it go first
    return true;
}

// ctx: lvupd::Context. False = not now.
bool PresentationGate(lvupd::Context* ctx)
{
    const HWND hwnd = Rd<HWND>(kVA_phWnd);
    if (!hwnd || !IsWindowVisible(hwnd) || IsIconic(hwnd)) return false;
    if (!IsWindowEnabled(hwnd) || GetActiveWindow() != hwnd) return false;   // a Windows dialog owns the thread, or we are in the background
    if (Rd<void*>(kVA_BasePopCur) != nullptr) return false;
    if (MainMenuIdle()) { *ctx = lvupd::kCtxMainMenu; return true; }
    if (TurnBegan())    { *ctx = lvupd::kCtxInGame;   return true; }
    return false;
}

// ---- the popup ----------------------------------------------------------------------------------

bool WriteLabelFile(const lvupd::LabelSpec& spec)
{
    static char text[8192];
    if (!lvupd::BuildLabelFile(spec, text, sizeof text)) return false;
    wchar_t dir[MAX_PATH], path[MAX_PATH + 32];
    if (!GameDirW(dir, MAX_PATH) || !Join(path, MAX_PATH + 32, dir, L"uimod_update.txt")) return false;
    FILE* f = nullptr;
    if (_wfopen_s(&f, path, L"wb") != 0 || !f) return false;
    const size_t n = strlen(text);
    const bool ok = fwrite(text, 1, n, f) == n;
    fclose(f);
    return ok;
}

bool ArtPresent()
{
    wchar_t dir[MAX_PATH], path[MAX_PATH + 32];
    return GameDirW(dir, MAX_PATH) && Join(path, MAX_PATH + 32, dir, L"longevity_sm.pcx") && FileExistsW(path);
}

// Shows one popup; returns the reply index, -1 for ESC / could not show.
int Popup(const char* body, const lvupd::ReplySet& r)
{
    lvupd::LabelSpec s = {};
    s.label = kLabelName;
    s.caption = lvupd::kCaption;
    s.xs = lvupd::kPromptXs;
    s.sprite = ArtPresent() ? kArtFile : nullptr;
    s.body = body;
    s.nReplies = r.n;
    for (int i = 0; i < r.n; ++i) s.replies[i] = r.text[i];
    g_lastPopupShown = false;
    if (!WriteLabelFile(s)) { Log("could not write uimod_update.txt -> prompt not shown"); return -1; }
    const int reply = reinterpret_cast<FXPops18>(At(kVA_XPops18))(kLabelFile, kLabelName, -1, nullptr, kPopFlags,
                                                                  nullptr, 1, 1, nullptr);
    g_lastPopupShown = true;
    Log("prompt shown (%s) -> reply %d \"%s\"", s.sprite ? "with picture" : "text only", reply,
        r.n == 0 ? "OK" : reply >= 0 && reply < r.n ? r.text[reply] : "(escape)");
    return reply;
}

// A notice. With two choices (OK / "Don't show this again") they are reply rows; with only an
// acknowledgement there are NO reply lines and the engine draws its own OK button -- a lone
// reply row rendered as a one-item list under a second OK (seen in-game 2026-09-27).
int Notice(const char* body, const char* reply0, const char* reply1)
{
    lvupd::ReplySet r;
    r.n = 0;
    if (reply1) {
        r.text[r.n] = reply0; r.act[r.n++] = lvupd::kActNotNow;
        r.text[r.n] = reply1; r.act[r.n++] = lvupd::kActNever;
    }
    return Popup(body, r);
}

// The queued startup notice: an acknowledgement only (the engine draws its OK), then the problem set's
// signature goes to the ini so the same set is not announced again next launch.
void ShowStartupNotice()
{
    const int r = Notice(g_noticeBody, nullptr, nullptr);
    if (!g_lastPopupShown) {         // label file unwritable: say nothing to the ini, try again next launch
        Log("startup notice NOT shown (popup failed) -> nothing remembered; it is offered again next launch");
        return;
    }
    // Shown is shown: OK and ESC (reply -1) both count -- the player read it; the same set must not nag.
    wchar_t ini[MAX_PATH + 32], sig[256];
    size_t i = 0;
    for (; g_noticeSig[i] && i + 1 < _countof(sig); ++i) sig[i] = static_cast<wchar_t>(static_cast<unsigned char>(g_noticeSig[i]));
    sig[i] = 0;
    if (IniPathW(ini, MAX_PATH + 32)) WritePrivateProfileStringW(L"UIMod", kNoticeKey, sig, ini);
    Log("startup notice shown (reply %d) -> [UIMod] %ls=%ls", r, kNoticeKey, sig);
}

// ---- [Longevity] DeclinedUpdates -----------------------------------------------------------

bool ReadDeclines(lvupd::Declines* d)
{
    wchar_t ini[MAX_PATH + 32], raw[lvupd::kIniBuf];
    if (!IniPathW(ini, MAX_PATH + 32)) return false;
    const DWORD n = GetPrivateProfileStringW(L"Longevity", L"DeclinedUpdates", L"", raw, lvupd::kIniBuf, ini);
    char narrow[lvupd::kIniBuf];
    bool ascii = true;
    for (DWORD i = 0; i <= n && i < lvupd::kIniBuf; ++i) {
        if (raw[i] >= 0x80) ascii = false;
        narrow[i] = raw[i] < 0x80 ? static_cast<char>(raw[i]) : '?';
    }
    lvupd::DeclineParse(narrow, n, d);
    if (!ascii) d->overflow = true;      // a hand-edited non-ASCII entry: never rewrite what we could not read faithfully
    return true;
}

bool WriteDeclines(const lvupd::Declines& d)
{
    char value[lvupd::kIniBuf];
    if (!lvupd::DeclineFormat(d, value, sizeof value)) return false;
    wchar_t ini[MAX_PATH + 32], wide[lvupd::kIniBuf];
    if (!IniPathW(ini, MAX_PATH + 32)) return false;
    size_t i = 0;
    for (; value[i]; ++i) wide[i] = static_cast<wchar_t>(static_cast<unsigned char>(value[i]));
    wide[i] = 0;
    const BOOL ok = WritePrivateProfileStringW(L"Longevity", L"DeclinedUpdates", wide, ini);
    Log("declined -> DeclinedUpdates=%s%s", value, ok ? "" : " (WRITE FAILED)");
    return ok != 0;
}

// `ver` = the offered version (declined at that version only) or lvupd::kDeclineAny (for good).
void Decline(const char* item, const char* ver)
{
    if (!ver) { Log("declines: no version to decline '%s' at; nothing written", item); return; }
    lvupd::Declines d;
    if (!ReadDeclines(&d)) { Log("declines: ini path unknown; nothing written"); return; }
    if (d.overflow) { Log("declines: the DeclinedUpdates value could not be read faithfully (too long or non-ASCII); nothing written"); return; }
    if (!lvupd::DeclineSet(&d, item, ver)) { Log("declines: refused item '%s' at '%s'", item, ver); return; }
    WriteDeclines(d);
}

void FlushIni()
{
    wchar_t ini[MAX_PATH + 32];
    if (IniPathW(ini, MAX_PATH + 32)) WritePrivateProfileStringW(nullptr, nullptr, nullptr, ini);
}

// ---- hand-off and exit --------------------------------------------------------------------------

// `"<system>\cmd.exe" /D /S /C ""<bat>" --update --game-dir "<game>" --wait-pid <pid> --only-listed [--modules a,b] [--manifest "<v>"]"`
// in a VISIBLE console. Forwarded: the pid, compiled-in ids, and -- only when the GAME was started
// with --lv-manifest (a tester's switch) -- that manifest, so the updater exercises the same test
// release the prompt came from (LONGEVITY_TRUST_KEY reaches it through the inherited environment).
// A path or value with a character cmd.exe would interpret is refused (then F7 tells the player
// where to download).
bool SpawnUpdater(const char* const* mods, int nMods)
{
    if (!FileExistsW(g_job.bat)) { Log("hand-off: %ls not found", g_job.bat); return false; }
    wchar_t sys[MAX_PATH];
    if (!GetSystemDirectoryW(sys, MAX_PATH)) return false;
    wchar_t cmdExe[MAX_PATH + 16];
    if (!Join(cmdExe, MAX_PATH + 16, sys, L"cmd.exe")) return false;
    // --game-dir EXPLICIT: the resident updater derives it from its own location too, but a
    // bootstrap that ever fell through to autodetection wrote to a different install (2026-09-27).
    // --only-listed + --modules: exactly the packs the popups named (lvupd::BuildUpdateCommandLine).
    wchar_t cmd[4096];
    if (!lvupd::BuildUpdateCommandLine(cmdExe, g_job.bat, g_job.gameDir, g_job.pid, mods, nMods,
                                       g_job.manifest[0] ? g_job.manifest : nullptr, cmd, _countof(cmd))) {
        Log("hand-off: refused (a path, the manifest value or a module id is not clean): bat=%ls game=%ls manifest=%ls mods=%d first=%s",
            g_job.bat, g_job.gameDir, g_job.manifest[0] ? g_job.manifest : L"-", nMods, nMods > 0 ? mods[0] : "-");
        return false;
    }
    STARTUPINFOW si; memset(&si, 0, sizeof si);
    si.cb = sizeof si;
    PROCESS_INFORMATION pi; memset(&pi, 0, sizeof pi);
    const BOOL ok = CreateProcessW(cmdExe, cmd, nullptr, nullptr, FALSE, CREATE_NEW_CONSOLE, nullptr, g_job.gameDir, &si, &pi);
    if (!ok) { Log("hand-off failed (error %lu): %ls", GetLastError(), cmd); return false; }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    Log("hand-off: %ls", cmd);
    return true;
}

// The engine's own ways out. Main menu: make the TOPMENU strip return -1 (what ESC does; top_menu
// then returns 1 and control_game runs the normal shutdown). In a game: the Quit menu's confirmed
// branch minus the confirmation (single player: IRONMAN auto-save, then ControlTurnA = 1; the
// input pump we are nested in returns, control_turn ends, control_game shuts down).
bool RequestGameExit(lvupd::Context ctx, BYTE* menuWin)
{
    FlushIni();
    if (ctx == lvupd::kCtxMainMenu) {
        BYTE* top = Rd<BYTE*>(kVA_ModalTop);
        if (!top || top != menuWin || *reinterpret_cast<void**>(top) != At(kVA_SetupWinVtbl)) {
            Log("exit requested (main menu) -> the menu strip is no longer the modal; not forced");
            return false;
        }
        *reinterpret_cast<int*>(top + kOfsSetupSel) = -1;
        reinterpret_cast<FReleaseModal>(At(kVA_WinReleaseModal))(top, nullptr);
        Log("exit requested (main menu) -> TOPMENU returns EXIT");
        return true;
    }
    if (Rd<int>(kVA_GameHalted) != 0 || Rd<int>(kVA_Multiplayer) != 0 || Rd<int>(kVA_PbemActive) != 0) {
        Log("exit requested (in game) -> game state changed under the prompt; not forced");
        return false;
    }
    if (Rd<int>(kVA_ControlTurnA) != 0) {                        // an IRONMAN save already told the engine to leave
        Log("exit requested (in game) -> the engine is already leaving (ControlTurnA set by the save)");
        return true;
    }
    if (Rd<int>(kVA_GameRules) & 0x400) reinterpret_cast<FAutoSave>(At(kVA_AutoSave))();   // IRONMAN: as Quit does
    Wr<int>(kVA_ControlTurnA, 1);
    Log("exit requested (in game) -> ControlTurnA = 1 (the Quit menu's own path)");
    return true;
}

// The Game menu's Save Game (case 0x59): the engine's own save dialog. 0 = saved.
bool SaveGameDialog()
{
    const int r = reinterpret_cast<FSaveGame>(At(kVA_SaveGame))(0);
    Log("save game dialog -> %s", r == 0 ? "saved" : "cancelled or failed");
    return r == 0;
}

// ---- the prompt sequence ----------------------------------------------------------------------------

void Present(lvupd::Context ctx)
{
    const lvupd::UpdateInfo& u = g_info;
    BYTE* menuWin = Rd<BYTE*>(kVA_ModalTop);
    Log("presenting (%s)", ctx == lvupd::kCtxMainMenu ? "main menu" : "turn start");

    if (g_noticePending) {                                                // the codec notice, first
        g_noticePending = false;
        ShowStartupNotice();
    }
    if (!HasSomethingToShow(u)) return;                                   // only the notice was pending

    if (u.code == lvupd::kCodeManual) {                                   // F6
        const int r = Notice(lvupd::ManualNoticeBody(u.manualReason), "OK", "Don't show this again");
        if (r == 1) {
            char item[64];
            if (lvupd::ManualDeclineItem(u.manualKey, item, sizeof item)) Decline(item, lvupd::kDeclineAny);
        }
        return;
    }

    static char body[4096];
    bool quitPending = false, wantSave = false;
    const char* accepted[lvupd::kMaxItems];                               // new packs accepted in their own popups
    int nAccepted = 0;
    const bool hadUpdate = u.hasBase || u.nStale > 0;

    if (hadUpdate) {                                                      // F2
        lvupd::ReplySet r;
        lvupd::ReplySetFor(ctx, lvupd::kPromptUpdate, &r);
        if (!lvupd::BuildUpdateBody(u, ctx, body, sizeof body)) return;
        switch (lvupd::ActionFor(r, Popup(body, r))) {
        case lvupd::kActSaveQuitUpdate: wantSave = true; quitPending = true; break;
        case lvupd::kActQuitUpdate:     quitPending = true; break;
        case lvupd::kActNever:
            if (u.hasBase) Decline("base", lvupd::DeclineVersionFor(false, u.baseTo));
            for (int i = 0; i < u.nStale; ++i) Decline(u.stale[i].id, lvupd::DeclineVersionFor(false, u.stale[i].to));
            break;
        default: break;                                                  // Not now / ESC
        }
        // A "no" to the update is a "no" to more popups this launch (UX audit 2026-09-27):
        // optional packs come back next launch; nothing is written for them.
        if (!quitPending) { Log("update declined this launch -> pack offers deferred to the next launch"); return; }
    }
    const bool updateAccepted = quitPending;                              // the update popup's stale packs ride along

    // F3: one popup per pack the player does not have -- all of them when they ride along with an
    // accepted update (a cheap yes/no each), at most ONE per launch on their own. The hand-off
    // names exactly what was listed and accepted (--only-listed), so a standalone pack brings
    // nothing else: BuildPackBody's "also brings the core up to X" sentence (alsoCoreTo) is never
    // true here and is not shown (the installer lists the core first whenever it is stale and
    // undeclined, and offers nothing while it is declined). A stale line for a pack id this DLL
    // does not know (a newer installer's pack) cannot be named, so it is simply not handed off.
    if (u.nUnknownStale > 0)
        Log("%d stale pack(s) with ids this build does not know -> left alone (not named in the hand-off)", u.nUnknownStale);
    const int nOffer = quitPending ? u.nFresh : (u.nFresh > 0 ? 1 : 0);
    for (int i = 0; i < nOffer; ++i) {
        const lvupd::PromptKind kind = quitPending ? lvupd::kPromptPackQuitPending : lvupd::kPromptPackStandalone;
        lvupd::ReplySet r;
        lvupd::ReplySetFor(ctx, kind, &r);
        if (!lvupd::BuildPackBody(u.fresh[i], nullptr, ctx, kind, body, sizeof body)) continue;
        const lvupd::Action a = lvupd::ActionFor(r, Popup(body, r));
        if (a == lvupd::kActSaveQuitUpdate || a == lvupd::kActQuitUpdate || a == lvupd::kActInstallToo) {
            accepted[nAccepted++] = u.fresh[i].id;
            if (a != lvupd::kActInstallToo) quitPending = true;
            if (a == lvupd::kActSaveQuitUpdate) wantSave = true;
        } else if (a == lvupd::kActNever) {
            char item[lvupd::kIdCap + 4];
            _snprintf_s(item, sizeof item, _TRUNCATE, "new:%s", u.fresh[i].id);
            Decline(item, lvupd::DeclineVersionFor(true, u.fresh[i].to));
        }
    }

    if (!quitPending && nAccepted == 0) return;                           // nothing accepted this launch

    // The hand-off list: the update popup's stale packs (when accepted) + the new packs accepted.
    const char* mods[2 * lvupd::kMaxItems];
    const int nMods = lvupd::HandoffModules(u, updateAccepted, accepted, nAccepted, mods, _countof(mods));
    if (nMods < 0) { Log("hand-off: module list refused; nothing spawned"); return; }

    // Save FIRST, everywhere. A cancelled dialog aborts before anything is spawned. (Under IRONMAN
    // the engine's save is "save and quit": it shows the same dialog and, once saved, sets
    // ControlTurnA itself -- RequestGameExit then simply leaves that alone. Spawning the updater
    // before the dialog put a console over the game and quit it even after a cancel, 2026-09-27.)
    if (ctx == lvupd::kCtxInGame && wantSave && !SaveGameDialog()) {
        Log("save cancelled -> update aborted; nothing spawned, the game continues");
        Notice(lvupd::kSaveCancelledBody, "OK", nullptr);
        return;
    }
    if (!SpawnUpdater(mods, nMods)) {                                     // F7
        Notice(lvupd::kNoInstallerBody, "OK", nullptr);
        return;
    }
    if (!RequestGameExit(ctx, menuWin))                                   // F8
        Notice(lvupd::kQuitManuallyBody, "OK", nullptr);
}

// ---- the turn-begin hook -------------------------------------------------------------------------
// Four `call Console_human_turn` sites are retargeted at a stub that raises the token and jumps
// on (ecx = MapWin_g preserved, the return address stays the call site's). Byte-checked: any
// site that is not the plain E8 to 0x514050 (another mod) leaves the hook off, and the prompt
// then shows at the main menu only.

__declspec(naked) void StubHumanTurn()
{
    __asm {
        mov  dword ptr [g_turnBegan], 1
        jmp  dword ptr [g_humanTurn]
    }
}

bool IsCallTo(uintptr_t site, uintptr_t target)
{
    const BYTE* p = At(site);
    if (p[0] != 0xE8) return false;
    int32_t rel; memcpy(&rel, p + 1, 4);
    return reinterpret_cast<uintptr_t>(p) + 5 + rel == reinterpret_cast<uintptr_t>(At(target));
}

void Retarget(uintptr_t site, void* fn)
{
    BYTE* p = At(site);
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(fn) - (reinterpret_cast<uintptr_t>(p) + 5));
    DWORD old;
    VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &old);
    memcpy(p + 1, &rel, 4);
    VirtualProtect(p, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 5);
}

void ArmTurnHook()
{
    for (uint32_t s : kHumanTurnSites)
        if (!IsCallTo(s, kVA_ConsoleHumanTurn)) {
            Log("turn-begin hook: site 0x%X is not the expected call -> in-game prompts off (main menu only)", s);
            return;
        }
    g_humanTurn = At(kVA_ConsoleHumanTurn);
    for (uint32_t s : kHumanTurnSites) Retarget(s, reinterpret_cast<void*>(&StubHumanTurn));
    g_turnHookArmed = true;
    Log("turn-begin hook armed (3 sites)");
}

} // namespace

// ---- public ------------------------------------------------------------------------------------------

void InstallUpdateCheck()
{
    // The mod ships for the PRACX build only. The pristine terranx.exe carries the DLL as a
    // developer tool (crash fix, clean baseline) and is never a public update target, so it
    // gets no check and no prompt (user decision 2026-09-27).
    if (GetModuleHandleA("prax.dll") == nullptr) {
        Log("PRACX not loaded: this build is not a supported update target -> no update check");
        g_phase = kPhaseDone;
        return;
    }
    wchar_t ini[MAX_PATH + 32];
    g_enabled = IniPathW(ini, MAX_PATH + 32)
        ? (GetPrivateProfileIntW(L"UIMod", L"CheckForUpdates", kUpdateCheckDefault, ini) != 0 ? 1 : 0)
        : kUpdateCheckDefault;
    if (!g_enabled) {
        Log("check disabled ([UIMod] CheckForUpdates=0) -> no update check this launch");
        g_phase = kPhaseDone;
        return;
    }
    memset(&g_job, 0, sizeof g_job);
    memset(&g_result, 0, sizeof g_result);
    Job& j = g_job;
    if (!GameDirW(j.gameDir, MAX_PATH)) { Log("game directory unknown -> no update check"); g_phase = kPhaseDone; return; }
    unsigned long osMajor = 0, osMinor = 0;
    OsVersion(&osMajor, &osMinor);
    const bool paths =
        Join(j.python,   MAX_PATH + 64, j.gameDir, lvupd::RuntimeExeRel(osMajor, osMinor)) &&
        Join(j.script,   MAX_PATH + 64, j.gameDir, L"LongevityMods\\updater\\scripts\\install.py") &&
        Join(j.bat,      MAX_PATH + 64, j.gameDir, L"LongevityMods\\updater\\scripts\\run-install.bat") &&
        Join(j.logDir,   MAX_PATH + 64, j.gameDir, L"LongevityMods\\logs") &&
        Join(j.checkLog, MAX_PATH + 64, j.gameDir, L"LongevityMods\\logs\\check.log");
    if (!paths) { Log("game path too long -> no update check"); g_phase = kPhaseDone; return; }
    if (!FileExistsW(j.python) || !FileExistsW(j.script)) {
        Log("resident updater not found (%ls missing) -> no update check (reinstall the mod to restore it)",
            FileExistsW(j.python) ? j.script : j.python);
        g_phase = kPhaseDone;
        return;
    }
    if (!lvupd::ExtractLvManifest(GetCommandLineW(), j.manifest, sizeof j.manifest / sizeof *j.manifest))
        j.manifest[0] = 0;
    if (!lvupd::BuildCheckCommandLine(j.python, j.script, j.gameDir, j.manifest[0] ? j.manifest : nullptr,
                                      j.cmd, sizeof j.cmd / sizeof *j.cmd)) {
        Log("could not build the check command line (a quote in a path?) -> no update check");
        g_phase = kPhaseDone;
        return;
    }
    j.pid = GetCurrentProcessId();
    j.delayMs = static_cast<DWORD>(lvupd::ExtractLvDelaySeconds(GetCommandLineW())) * 1000u;
    g_ready = 0;
    const HANDLE h = CreateThread(nullptr, 64 * 1024, WorkerThunk, nullptr, 0, nullptr);
    if (!h) { Log("CreateThread failed (%lu) -> no update check", GetLastError()); g_phase = kPhaseDone; return; }
    CloseHandle(h);
    g_phase = kPhaseWaiting;
    if (j.manifest[0]) Log("check started (test manifest from --lv-manifest: %ls)", j.manifest);
    else Log("check started");
    if (j.delayMs) Log("check held back %lu s (--lv-delay)", j.delayMs / 1000u);
    ArmTurnHook();
}

void UpdatePoll()
{
    switch (g_phase) {
    case kPhaseWaiting:
        if (InterlockedCompareExchange(&g_ready, 2, 1) != 1) return;
        g_info = g_result.info;
        LogResult(g_result);
        g_phase = (HasSomethingToShow(g_info) || g_noticePending) ? kPhaseArmed : kPhaseDone;
        return;
    case kPhaseIdle:
    case kPhaseDone:
        // No check this launch (PRACX absent, CheckForUpdates=0) or it is over: a notice queued by Init
        // still gets its moment. Present() consumes it, so Done stays Done afterwards.
        if (g_noticePending) g_phase = kPhaseArmed;
        return;
    case kPhaseArmed: {
        lvupd::Context ctx;
        if (!PresentationGate(&ctx)) return;
        if (PostMessageW(Rd<HWND>(kVA_phWnd), kMsgPresent, static_cast<WPARAM>(ctx), 0)) {
            g_phase = kPhasePosted;
            g_postedAt = GetTickCount64();
        }
        return;
    }
    case kPhasePosted:
        if (GetTickCount64() - g_postedAt > kRepostMs) g_phase = kPhaseArmed;   // the pump never handed it to us: try again
        return;
    default:
        return;
    }
}

void UpdateOnMessage(MSG* m)
{
    if (!m) return;
    if (m->message == kMsgPresent) {
        if (m->hwnd != Rd<HWND>(kVA_phWnd)) return;
        if (ModernCtlBusy()) {                                   // the hover line is inside the engine's drag painter
            PostMessageW(m->hwnd, m->message, m->wParam, m->lParam);   // (do_all_non_input pumps): present later
            m->message = WM_NULL;
            return;
        }
        m->message = WM_NULL;                                    // the engine resumes on nothing, never on stale input
        if (g_phase != kPhasePosted) return;
        lvupd::Context ctx;
        if (!PresentationGate(&ctx)) { g_phase = kPhaseArmed; return; }   // the moment passed between post and dispatch
        g_phase = kPhasePresenting;
        InterlockedExchange(&g_turnBegan, 0);
        Present(ctx);
        g_phase = kPhaseDone;                                    // one sequence per launch, whatever the replies
        return;
    }
    // The player's first click or key of a turn, taken at the map with no popup up: the turn is
    // no longer "beginning". Clicks that dismiss an engine popup -- modal, or the non-modal
    // tutorial hint -- do not count.
    const bool input = m->message == WM_LBUTTONDOWN || m->message == WM_RBUTTONDOWN || m->message == WM_MBUTTONDOWN ||
                       m->message == WM_LBUTTONDBLCLK || m->message == WM_RBUTTONDBLCLK ||
                       m->message == WM_KEYDOWN || m->message == WM_SYSKEYDOWN;
    if (g_turnBegan && input && Rd<int>(kVA_GameHalted) == 0 &&
        Rd<void*>(kVA_ModalTop) == nullptr && Rd<void*>(kVA_BasePopCur) == nullptr &&
        !(At(kVA_TutWin)[kOfsWinShown] & 1))
        InterlockedExchange(&g_turnBegan, 0);
}

bool UpdateSubscribeAll()
{
    lvupd::ReplySet r;
    r.n = 2;
    r.text[0] = "Cancel";            r.act[0] = lvupd::kActNotNow;       // reply 0 = the safe one (Esc)
    r.text[1] = "Yes, ask me again"; r.act[1] = lvupd::kActQuitUpdate;
    if (Popup(lvupd::kSubscribeBody, r) != 1) return false;
    wchar_t ini[MAX_PATH + 32];
    if (!IniPathW(ini, MAX_PATH + 32)) return false;
    const BOOL ok = WritePrivateProfileStringW(L"Longevity", L"DeclinedUpdates", L"", ini);
    UpdateCheckSet(1);
    UpdateCheckSave();                                          // an action, not a setting: persists at once, like the clear
    Log("subscribe-all: declines cleared%s; CheckForUpdates=1 saved", ok ? "" : " (WRITE FAILED)");
    return ok != 0;
}

int  UpdateCheckGet() { return g_enabled; }
void UpdateClearStartupNotice()
{
    wchar_t ini[MAX_PATH + 32], shown[256] = {};
    if (!IniPathW(ini, MAX_PATH + 32)) return;
    GetPrivateProfileStringW(L"UIMod", kNoticeKey, L"", shown, _countof(shown), ini);
    if (!shown[0]) return;
    WritePrivateProfileStringW(L"UIMod", kNoticeKey, nullptr, ini);     // delete the key
    Log("startup notice: problem set %ls is gone -> [UIMod] %ls cleared (a recurrence is announced again)", shown, kNoticeKey);
}

void UpdateQueueStartupNotice(const char* body, const char* sig)
{
    if (!body || !body[0] || !sig || !sig[0]) return;
    wchar_t ini[MAX_PATH + 32], shown[256] = {};
    if (IniPathW(ini, MAX_PATH + 32))
        GetPrivateProfileStringW(L"UIMod", kNoticeKey, L"", shown, _countof(shown), ini);
    bool same = true;
    for (size_t i = 0; ; ++i) {
        const wchar_t w = static_cast<wchar_t>(static_cast<unsigned char>(sig[i]));
        if (i >= _countof(shown) || shown[i] != w) { same = false; break; }
        if (!w) break;
    }
    if (same) { Log("startup notice already shown for this problem set ([UIMod] %ls) -> not queued", kNoticeKey); return; }
    strncpy_s(g_noticeBody, body, _TRUNCATE);
    strncpy_s(g_noticeSig, sig, _TRUNCATE);
    g_noticePending = true;
    Log("startup notice queued (shown at the main menu / turn start)");
}

void UpdateCheckSet(int on) { g_enabled = on ? 1 : 0; }
void UpdateCheckSave()
{
    wchar_t ini[MAX_PATH + 32];
    if (IniPathW(ini, MAX_PATH + 32))
        WritePrivateProfileStringW(L"UIMod", L"CheckForUpdates", g_enabled ? L"1" : L"0", ini);
}
