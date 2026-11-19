// thinkerversion.cpp -- the Thinker Mod startup check.
//
// Longevity Vaccine is built against ONE exact build of Thinker Mod: everything of ours that calls into, chains into
// or patches thinker.dll is pinned to it by its PE TimeDateStamp and SizeOfImage (version.h UIMOD_THINKER_SUPPORTED_*).
// This module answers two questions, once, before any game window exists (user 2026-11-13: "We just needed to detect
// if any Thinker is present and whether or not it is the one we expect"):
//     is thinker.dll in the process, and is it that build.
// There are no build categories and no archive of Thinker builds; the label thinker.dll reports about itself is read
// only to word the message.
//
// On any other build the player gets our own dialog (thinkerdialog.h), every word of it user-approved
// (thinkercheck_core.h holds the sentences; work\briefs\thinker-runtime-error-design.md the rulings):
//     [Update now] [Not now] [Don't ask me again]
//   Update now          starts the resident installer in a console (`run-install.bat --fix-thinker`) and ENDS THE
//                       PROCESS. The installer offers the latest Longevity Vaccine and the Thinker Mod that goes with
//                       it; the click itself changes nothing. If the installer cannot be started the game is NOT
//                       closed: a box says so and the game starts.
//   Not now             starts the game; asked again next launch.
//   Don't ask me again  stores our own version in [UIMod] ThinkerMismatchDontAsk and starts the game. The question
//                       returns when that value stops matching: the installer deletes the key on every install of
//                       Longevity Vaccine, Preferences "Reset Skipped Updates" deletes it, and a new version no longer
//                       equals it. Switching Thinker builds does NOT bring it back.
//   close box / Alt+F4  ENDS THE PROCESS: no game, no installer, nothing written (user 2026-11-14). Esc does nothing.
// When the game starts on another build, the rest of the DLL runs in reduced mode: ThinkerOnPin() is false and
// nothing of ours touches thinker.dll.
//
// Where it runs: PreInit (init.cpp), on the main thread, outside the loader lock, before PRACX's own init. Thinker's
// DllMain has always returned by then -- the bootstrap's own LoadLibrary calls serialise behind the loader lock, even
// when Thinker's launcher resumed the game on its 5 s timeout -- so there is nothing to wait for. Ending the process
// from here is TerminateProcess, never ExitProcess: we are inside the exe's _initterm, and no atexit handler, no
// PRACX / DDrawCompat detach may run. No uimod thread exists yet and the log is written line by line.
//
// The developer exe (one-phase bootstrap, no PRACX; never an update target) reaches this from Init() instead and
// gets a plain box only.
//
// Test switch: [UIMod] ThinkerMismatchTest = older | newer | same | dev | unknown treats the loaded Thinker as
// another build with that kind of label, so the whole flow can be exercised on the supported build. It can only
// reduce function. Never set by the mod itself.
#include "thinkerversion.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "thinkercheck_core.h"   // the decision, the label grammar, every sentence
#include "thinkerdialog.h"       // the three-button dialog and its loop
#include "thinkerlive.h"         // the readers of memory and files we do not own (each run by a self-test)
#include "update.h"              // kThinkerDontAskKey, the ini / game-dir / spawn helpers, kUpdateCheckDefault
#include "update_core.h"         // kDownloadUrlShown (ours), kThinkerReleasePagePrefix, BuildFixThinkerCommandLine
#include "version.h"             // UIMOD_VERSION_STRING, UIMOD_THINKER_SUPPORTED_*

void UimodLog(const char* msg);   // init.cpp

namespace {

using namespace thinkercheck;

constexpr uint32_t kVA_EngineVersion = 0x691870;   // const char*: "RELEASE 2.0" in the exe; Thinker stores its MOD_VERSION here
constexpr wchar_t kSection[] = L"UIMod";
constexpr wchar_t kKeyTest[] = L"ThinkerMismatchTest";
constexpr wchar_t kKeyChecks[] = L"CheckForUpdates";
constexpr wchar_t kJournalRel[] = L"LongevityMods\\thinker-journal.json";   // exists exactly while a Thinker change is unfinished
constexpr wchar_t kBatRel[] = L"LongevityMods\\updater\\scripts\\run-install.bat";
constexpr wchar_t kScriptRel[] = L"LongevityMods\\updater\\scripts\\install.py";
constexpr wchar_t kVersionRel[] = L"LongevityMods\\updater\\VERSION";
constexpr DWORD kGuardMs = 400;
constexpr char kFixThinkerFlag[] = "--fix-thinker";   // what "Update now" passes; the installer copy must know it

struct Detected {
    bool decided = false;
    bool found = false, readable = false, test = false;
    uint32_t stamp = 0, size = 0;
    uintptr_t lo = 0, hi = 0;
    State state = State::None;
    Label label;
} g;

void Log(const char* fmt, ...)
{
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(buf, sizeof buf, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(buf);
}

using thinkerlive::Utf8;                            // wide paths in log lines: %ls drops the whole line on a non-ANSI name

std::wstring Wide(const std::string& s)             // every text here is ASCII
{
    return std::wstring(s.begin(), s.end());
}

std::wstring Join(const wchar_t* dir, const wchar_t* rel)
{
    std::wstring p(dir);
    if (!p.empty() && p.back() != L'\\') p += L'\\';
    return p + rel;
}

bool FileExists(const std::wstring& p)
{
    const DWORD a = GetFileAttributesW(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

// ---- detection -------------------------------------------------------------------------------------------------

// What thinker.dll calls itself: the string its DllMain leaves at 0x691870 (thinkerlive::ReadLabel follows the pointer
// only into thinker.dll's own readable memory, and never past it).
Label LoadedLabel(uintptr_t lo, uintptr_t hi)
{
    const BYTE* exe = reinterpret_cast<const BYTE*>(GetModuleHandleW(nullptr));
    const char* p = nullptr;
    memcpy(&p, exe + (kVA_EngineVersion - 0x400000), sizeof p);
    const char* why = nullptr;
    const Label l = thinkerlive::ReadLabel(p, lo, hi, &why);
    if (why) Log("[uimod] thinker: the version string at %p (from 0x%08X): %s -> the build has no label\n",
                 static_cast<const void*>(p), kVA_EngineVersion, why);
    return l;
}

void Detect()
{
    if (g.decided) return;
    g.decided = true;
    const HMODULE m = GetModuleHandleA("thinker.dll");
    g.found = m != nullptr;
    if (m) {
        // Guarded: a module handle is not a promise that its header pages are readable.
        const BYTE* base = reinterpret_cast<const BYTE*>(m);
        auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
        if (thinkerlive::Readable(base, sizeof(IMAGE_DOS_HEADER)) && dos->e_magic == IMAGE_DOS_SIGNATURE &&
            dos->e_lfanew > 0 && dos->e_lfanew < 0x1000 &&
            thinkerlive::Readable(base + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS32))) {
            auto nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(base + dos->e_lfanew);
            if (nt->Signature == IMAGE_NT_SIGNATURE && nt->OptionalHeader.SizeOfImage) {
                g.readable = true;
                g.stamp = nt->FileHeader.TimeDateStamp;
                g.size = nt->OptionalHeader.SizeOfImage;
                g.lo = reinterpret_cast<uintptr_t>(base);
                g.hi = g.lo + g.size;
            }
        }
    }
    g.state = Decide(g.found, g.readable, g.stamp, g.size, UIMOD_THINKER_SUPPORTED_STAMP, UIMOD_THINKER_SUPPORTED_IMAGE_SIZE);
    if (g.found && g.readable) g.label = LoadedLabel(g.lo, g.hi);

    if (g.found) {                                   // the test switch: only ever on a loaded Thinker
        wchar_t ini[MAX_PATH + 32], v[16] = L"";
        if (UpdateIniPathW(ini, MAX_PATH + 32)) GetPrivateProfileStringW(kSection, kKeyTest, L"", v, _countof(v), ini);
        char narrow[16] = "";
        for (size_t i = 0; i + 1 < sizeof narrow && v[i]; ++i) narrow[i] = v[i] < 128 ? static_cast<char>(v[i]) : '?';
        Label forced;
        if (TestLabel(narrow, UIMOD_THINKER_SUPPORTED_VERSION, &forced)) {
            g.test = true;
            g.state = State::OffPin;
            g.label = forced;
        }
    }

    const std::string run = RunText(g.label, nullptr);
    switch (g.state) {
    case State::None:
        UimodLog("[uimod] thinker: not loaded\n");
        break;
    case State::Pin:
        Log("[uimod] thinker: loaded at %p (%u KB), \"%s\": the supported %s build (stamp 0x%08X, image 0x%X)\n",
            reinterpret_cast<void*>(g.lo), static_cast<unsigned>(g.size >> 10), run.c_str(), UIMOD_THINKER_SUPPORTED_VERSION,
            static_cast<unsigned>(g.stamp), static_cast<unsigned>(g.size));
        break;
    case State::OffPin:
        Log("[uimod] thinker: \"%s\" (stamp 0x%08X, image 0x%X%s) is not the supported %s build%s -> reduced mode\n",
            run.c_str(), static_cast<unsigned>(g.stamp), static_cast<unsigned>(g.size), g.readable ? "" : ", header unreadable",
            UIMOD_THINKER_SUPPORTED_VERSION, g.test ? " (ThinkerMismatchTest)" : "");
        break;
    }
}

// ---- boxes -----------------------------------------------------------------------------------------------------

std::string ThinkerDownloadPage()
{
    return ThinkerPage(lvupd::kThinkerReleasePagePrefix, UIMOD_THINKER_SUPPORTED_TAG, UIMOD_THINKER_DEV_PAGE);
}

void Box(const std::string& text)
{
    MessageBoxW(nullptr, Wide(text).c_str(), Wide(kTitle).c_str(), MB_OK | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST);
}

void BoxF()
{
    Box(BuildBoxF(UIMOD_THINKER_SUPPORTED_VERSION, lvupd::kDownloadUrlShown, ThinkerDownloadPage().c_str()));
}

void BoxG()
{
    Box(BuildBoxG(UIMOD_VERSION_STRING, UIMOD_THINKER_SUPPORTED_VERSION, g.label, lvupd::kDownloadUrlShown,
                  ThinkerDownloadPage().c_str()));
}

// ---- "Update now" ----------------------------------------------------------------------------------------------

// Starts `run-install.bat --fix-thinker` in a console of its own. True ONLY when that console is really running:
// the caller then ends the game. Every way this can fail is checked BEFORE anything is closed -- the files and the
// interpreter exist, the copy is not older than this DLL, its install.py really knows `--fix-thinker` (a capability,
// not a version number: the one shipped release without it would answer with a raw argument error), the command line
// is clean -- and each is logged.
bool StartInstaller()
{
    wchar_t game[MAX_PATH];
    if (!UpdateGameDirW(game, MAX_PATH)) { UimodLog("[uimod] thinker: Update now: the game directory is unknown\n"); return false; }
    const std::wstring bat = Join(game, kBatRel), script = Join(game, kScriptRel), python = Join(game, UpdateRuntimeExeRel());
    for (const std::wstring* p : { &bat, &script, &python }) {
        if (!FileExists(*p)) { Log("[uimod] thinker: Update now: %s is missing\n", Utf8(p->c_str()).c_str()); return false; }
    }
    const std::string have = thinkerlive::ReadVersionFile(Join(game, kVersionRel).c_str());
    if (VersionOlder(have.c_str(), UIMOD_VERSION_STRING)) {
        Log("[uimod] thinker: Update now: the installer copy is \"%s\", older than this mod (%s) or unreadable\n", have.c_str(),
            UIMOD_VERSION_STRING);
        return false;
    }
    if (!thinkerlive::FileMentions(script.c_str(), kFixThinkerFlag)) {
        Log("[uimod] thinker: Update now: the installer copy (%s) does not know %s\n", have.c_str(), kFixThinkerFlag);
        return false;
    }
    wchar_t sys[MAX_PATH];
    if (!GetSystemDirectoryW(sys, MAX_PATH)) { UimodLog("[uimod] thinker: Update now: the system directory is unknown\n"); return false; }
    const std::wstring cmdExe = Join(sys, L"cmd.exe");
    wchar_t manifest[1024];
    if (!lvupd::ExtractLvManifest(GetCommandLineW(), manifest, _countof(manifest))) manifest[0] = 0;   // a tester's switch
    wchar_t cmd[4096];
    if (!lvupd::BuildFixThinkerCommandLine(cmdExe.c_str(), bat.c_str(), game, GetCurrentProcessId(),
                                           manifest[0] ? manifest : nullptr, cmd, _countof(cmd))) {
        Log("[uimod] thinker: Update now: refused (a path or the manifest value is not clean): bat=%s game=%s\n",
            Utf8(bat.c_str()).c_str(), Utf8(game).c_str());
        return false;
    }
    // Without a scrubbed block the console would inherit whatever an installer run left in OUR environment -- a
    // pre-granted consent among it. That is not a console to start: no block, no spawn.
    wchar_t* block = GetEnvironmentStringsW();
    if (!block) { UimodLog("[uimod] thinker: Update now: the environment could not be read -> not started\n"); return false; }
    const std::wstring env = ScrubEnvironment(block);
    FreeEnvironmentStringsW(block);
    return UpdateSpawnVisible(cmdExe.c_str(), cmd, game, env.c_str());
}

// ---- the dialog ------------------------------------------------------------------------------------------------

// One log line that answers "could this dialog use themed buttons here": a button is drawn themed only when the
// process is themed AND common controls 6 is the one loaded. The dialog uses classic buttons until that has been read
// from a real run under every loader we support. -1 = the question could not be asked.
void LogThemes()
{
    using FBool = BOOL(WINAPI*)();
    const HMODULE ux = GetModuleHandleW(L"uxtheme.dll");
    const FBool app = ux ? reinterpret_cast<FBool>(reinterpret_cast<void*>(GetProcAddress(ux, "IsAppThemed"))) : nullptr;
    const FBool active = ux ? reinterpret_cast<FBool>(reinterpret_cast<void*>(GetProcAddress(ux, "IsThemeActive"))) : nullptr;
    struct Info { DWORD cb, major, minor, build, platform; } info = { sizeof(Info), 0, 0, 0, 0 };   // DLLVERSIONINFO
    using FVer = HRESULT(WINAPI*)(Info*);
    const HMODULE cc = GetModuleHandleW(L"comctl32.dll");
    const FVer ver = cc ? reinterpret_cast<FVer>(reinterpret_cast<void*>(GetProcAddress(cc, "DllGetVersion"))) : nullptr;
    const bool known = ver && SUCCEEDED(ver(&info));
    Log("[uimod] thinker: dialog: app themed %d, theme active %d, common controls %s %lu.%lu\n",
        app ? (app() ? 1 : 0) : -1, active ? (active() ? 1 : 0) : -1, cc ? (known ? "loaded" : "loaded, version unknown") : "not loaded",
        known ? info.major : 0UL, known ? info.minor : 0UL);
}

int AskPlayer(bool checksOn, DWORD* error)
{
    LogThemes();
    const std::wstring title = Wide(kTitle);
    const std::wstring body = Wide(BuildBody(UIMOD_VERSION_STRING, UIMOD_THINKER_SUPPORTED_VERSION, g.label));
    const std::wstring update = Wide(kBtnUpdate), notNow = Wide(kBtnNotNow), dontAsk = Wide(kBtnDontAsk);
    thinkerdialog::Spec spec;
    spec.title = title.c_str();
    spec.text = body.c_str();
    spec.captions[0] = update.c_str();  spec.ids[0] = kUpdate;
    spec.captions[1] = notNow.c_str();  spec.ids[1] = kNotNow;
    spec.captions[2] = dontAsk.c_str(); spec.ids[2] = kDontAsk;
    spec.defaultId = DefaultButton(checksOn);
    spec.guardMs = kGuardMs;
    MessageBeep(MB_ICONWARNING);
    return thinkerdialog::Run(spec, GetModuleHandleW(nullptr), error);
}

void RememberDontAsk(const wchar_t* ini)
{
    const std::wstring lv = Wide(UIMOD_VERSION_STRING);
    wchar_t back[32] = L"";
    const BOOL wrote = WritePrivateProfileStringW(kSection, kThinkerDontAskKey, lv.c_str(), ini);
    const DWORD writeError = wrote ? 0 : GetLastError();           // before the read-back overwrites it
    GetPrivateProfileStringW(kSection, kThinkerDontAskKey, L"", back, _countof(back), ini);
    if (wrote && lv == back) {
        Log("[uimod] thinker: the player chose Don't ask me again -> [UIMod] %s = %s\n", Utf8(kThinkerDontAskKey).c_str(),
            UIMOD_VERSION_STRING);
        return;
    }
    Log("[uimod] thinker: the player chose Don't ask me again but %s could not be written (error %lu%s) -> asked again next start\n",
        Utf8(ini).c_str(), writeError, wrote ? ", the value did not read back" : "");
    Box(kNotSaved);                                  // never tell the player something that did not happen
}

} // namespace

bool ThinkerPresent()
{
    Detect();
    return g.found;
}

bool ThinkerOnPin()
{
    Detect();
    return g.state == State::Pin;
}

bool ThinkerImageRange(uintptr_t* lo, uintptr_t* hi)
{
    Detect();
    if (!g.found || !g.readable) return false;
    *lo = g.lo;
    *hi = g.hi;
    return true;
}

bool ThinkerWords(const char* against, char* run, size_t runCap, char* yours, size_t yoursCap)
{
    Detect();
    Label label = g.label;
    if (!g.found) {
        // The game was started without Thinker (terranx.exe run directly in a Thinker folder), but the offer is about
        // the FOLDER's build: read what the file calls itself, by the installer's own rule. Unreadable: no words.
        wchar_t game[MAX_PATH];
        bool read = false;
        if (!UpdateGameDirW(game, MAX_PATH)) return false;
        label = thinkerlive::LabelFromFile(Join(game, L"thinker.dll").c_str(), &read);
        if (!read) return false;
    }
    const std::string r = RunText(label, against), y = YoursText(label, against);
    if (r.size() >= runCap || y.size() >= yoursCap) return false;
    memcpy(run, r.c_str(), r.size() + 1);
    memcpy(yours, y.c_str(), y.size() + 1);
    return true;
}

void ThinkerCannotStart()
{
    UimodLog("[uimod] thinker: a required memory patch could not be applied -> the game is stopped\n");
    Box(kCannotStart);
    TerminateProcess(GetCurrentProcess(), 1);
    for (;;) Sleep(INFINITE);                        // TerminateProcess on ourselves does not return
}

void ThinkerStartupCheck(bool preInit)
{
    static bool ran = false;
    if (ran) return;
    ran = true;
    Detect();
    if (g.state != State::OffPin) return;

    if (!preInit) {
        // The developer exe: one-phase bootstrap, no PRACX, never an update target. Tell, do not offer.
        UimodLog("[uimod] thinker: one-phase bootstrap -> a box only (no Update now on an exe that is not an update target)\n");
        BoxG();
        return;
    }

    wchar_t ini[MAX_PATH + 32] = L"", game[MAX_PATH] = L"";
    const bool haveIni = UpdateIniPathW(ini, MAX_PATH + 32);
    wchar_t stored[32] = L"";
    if (haveIni) GetPrivateProfileStringW(kSection, kThinkerDontAskKey, L"", stored, _countof(stored), ini);
    char storedA[32] = "";
    for (size_t i = 0; i + 1 < sizeof storedA && stored[i]; ++i) storedA[i] = stored[i] < 128 ? static_cast<char>(stored[i]) : '?';
    const bool journal = UpdateGameDirW(game, MAX_PATH) && FileExists(Join(game, kJournalRel));
    if (DontAskMatches(storedA, UIMOD_VERSION_STRING)) {
        if (!journal) {
            Log("[uimod] thinker: not asked (\"Don't ask me again\" for %s)\n", UIMOD_VERSION_STRING);
            return;
        }
        // An interrupted Thinker replacement leaves mixed files; "Update now" is the way back into the installer,
        // which finishes or undoes it. The dismissal does not hide that.
        UimodLog("[uimod] thinker: a Thinker Mod change is unfinished -> asked although \"Don't ask me again\" is set\n");
    }

    // Read straight from the ini: the update checker has not loaded its setting yet (InstallUpdateCheck runs in Init).
    const bool checksOn = !haveIni || GetPrivateProfileIntW(kSection, kKeyChecks, kUpdateCheckDefault, ini) != 0;
    DWORD dialogError = 0;
    const int answer = AskPlayer(checksOn, &dialogError);
    switch (answer) {
    case kUpdate:
        UimodLog("[uimod] thinker: the player chose Update now\n");
        if (StartInstaller()) {
            UimodLog("[uimod] thinker: the installer is running -> the game ends here\n");
            TerminateProcess(GetCurrentProcess(), 0);    // 0: a launcher must not read this as a crash
            for (;;) Sleep(INFINITE);
        }
        BoxF();                                          // nothing was closed; the game starts
        break;
    case kDontAsk:
        if (haveIni) RememberDontAsk(ini);
        else { UimodLog("[uimod] thinker: Don't ask me again: the ini path is unknown -> asked again next start\n"); Box(kNotSaved); }
        break;
    case kNotNow:
        UimodLog("[uimod] thinker: the player chose Not now (asked again next start)\n");
        break;
    case thinkerdialog::kClosed:
        // Nothing to undo, as for Update now: what has run (the DllMains of DDrawCompat, prax.dll and Thinker, our DPI
        // awareness and ghosting switch) is process-local; no display mode has been touched (VidModePreInit runs
        // after this), no uimod thread exists, no byte of ours is written, the ini is not, and the log is written
        // line by line. Thinker's launcher does not wait on the game.
        UimodLog("[uimod] thinker: the player closed the dialog -> the game ends here (no game, no installer)\n");
        TerminateProcess(GetCurrentProcess(), 0);        // 0: the player's own choice, not a crash
        for (;;) Sleep(INFINITE);
    case thinkerdialog::kQuit:
        UimodLog("[uimod] thinker: the process is quitting -> no answer\n");
        break;
    default:
        Log("[uimod] thinker: the dialog could not be created (error %lu) -> a plain box\n", dialogError);
        BoxG();
        break;
    }
}
