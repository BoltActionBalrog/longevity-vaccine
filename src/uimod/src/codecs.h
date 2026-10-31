#pragma once
// The cinematics' codec DLLs (ffmpeg: avutil, swresample, swscale, avcodec, avformat), probed at Init.
//
// WHY. They used to be HARD imports of uimod.dll: one of them missing or quarantined (nothing we ship is
// Authenticode-signed; an antivirus deleting an "unknown DLL" is the expected trigger) and Windows refused
// uimod.dll itself -- the whole mod gone, the exe-side boot guard naming uimod.dll (the wrong file) and
// leaving the game. Now they are DELAY-LOADED (uimod.vcxproj DelayLoadDLLs): uimod.dll always loads, and
// before the movie hook goes in this probe opens each DLL by its full path next to uimod.dll and asks it
// its version. Anything wrong -> the movie hook is NOT installed (movies take the engine's / PRACX's own
// path), uimod.log names the file and the Windows error, and the player gets ONE in-game notice saying
// which file and what to do; every other feature keeps working.
//
// Header-only so the harness (work\tests\codecs) drives it against the real DLLs with one removed, one
// swapped for another build, one of the wrong major.

#include <windows.h>
#include <cstdio>
#include <cstring>

namespace codecs {

struct Lib {
    const wchar_t* name;            // "avcodec-62.dll"
    const char*    versionExport;   // "avcodec_version": every libav DLL exports one, returning the packed version
    unsigned       major;           // LIBAVCODEC_VERSION_MAJOR this DLL was built against
    unsigned       minor;           // LIBAVCODEC_VERSION_MINOR: ffmpeg adds exports within a major, so a DLL of the
                                    // right major but an OLDER minor can lack one we bind to (ffmpeg's own ABI rule)
};

enum Fault { kOk = 0, kNotLoaded, kNoVersionExport, kWrongMajor, kOldMinor, kFolderUnknown };

struct Problem {
    wchar_t  name[40];
    Fault    fault;
    DWORD    error;      // GetLastError for kNotLoaded / kNoVersionExport
    unsigned found;      // the major actually reported, for kWrongMajor / kOldMinor
    unsigned wanted;
    unsigned foundMinor;
    unsigned wantedMinor;
};

constexpr int kMaxLibs = 8;

struct Report {
    int     nLibs = 0;
    int     nProblems = 0;
    Problem problems[kMaxLibs];
    HMODULE handles[kMaxLibs] = {};   // kept for the process: the delay-load binds to these
    bool Ok() const { return nProblems == 0; }
};

// `dir` = the folder uimod.dll (and the codec DLLs) live in, no trailing backslash required.
// The DLLs depend on each other (avcodec -> avutil ...); `libs` lists them in dependency order so the
// root cause is reported first. LOAD_WITH_ALTERED_SEARCH_PATH: a dependency resolves from the DLL's own
// folder, not the process's current directory.
inline void Probe(const wchar_t* dir, const Lib* libs, int n, Report& r)
{
    r = Report();
    typedef unsigned (*VersionFn)();
    for (int i = 0; i < n && i < kMaxLibs; ++i) {
        ++r.nLibs;
        wchar_t path[MAX_PATH + 64];
        _snwprintf_s(path, _countof(path), _TRUNCATE, L"%ls%ls%ls", dir,
                     (dir[0] && dir[wcslen(dir) - 1] == L'\\') ? L"" : L"\\", libs[i].name);
        Problem p = {};
        wcsncpy_s(p.name, libs[i].name, _TRUNCATE);
        p.wanted = libs[i].major;
        p.wantedMinor = libs[i].minor;
        HMODULE h = LoadLibraryExW(path, nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
        if (!h) {
            p.fault = kNotLoaded; p.error = GetLastError();
            r.problems[r.nProblems++] = p;
            continue;
        }
        r.handles[i] = h;
        const VersionFn fn = reinterpret_cast<VersionFn>(reinterpret_cast<void*>(GetProcAddress(h, libs[i].versionExport)));
        if (!fn) {
            p.fault = kNoVersionExport; p.error = GetLastError();
            r.problems[r.nProblems++] = p;
            continue;
        }
        const unsigned v = fn();
        p.found = v >> 16;
        p.foundMinor = (v >> 8) & 0xFF;
        if (p.found != libs[i].major) {
            p.fault = kWrongMajor;
            r.problems[r.nProblems++] = p;
        } else if (p.foundMinor < libs[i].minor) {
            p.fault = kOldMinor;
            r.problems[r.nProblems++] = p;
        }
    }
}

// The caller could not even find the folder uimod.dll lives in (a path past MAX_PATH): one problem, not
// five bogus "could not be loaded" ones.
inline void ReportFolderUnknown(Report& r)
{
    r = Report();
    Problem p = {};
    wcsncpy_s(p.name, L"uimod.dll", _TRUNCATE);
    p.fault = kFolderUnknown;
    r.problems[r.nProblems++] = p;
}

// One problem, for the log and for the player: "avcodec-62.dll is missing (Windows error 126)".
inline void DescribeProblem(const Problem& p, char* out, size_t cap)
{
    switch (p.fault) {
    case kNotLoaded:
        if (p.error == ERROR_MOD_NOT_FOUND)
            _snprintf_s(out, cap, _TRUNCATE, "%ls is missing (Windows error %lu)", p.name, p.error);
        else
            _snprintf_s(out, cap, _TRUNCATE, "%ls could not be loaded (Windows error %lu)", p.name, p.error);
        break;
    case kNoVersionExport:
        _snprintf_s(out, cap, _TRUNCATE, "%ls is not the file the mod shipped (no version entry, Windows error %lu)", p.name, p.error);
        break;
    case kWrongMajor:
        _snprintf_s(out, cap, _TRUNCATE, "%ls is version %u, the mod needs %u", p.name, p.found, p.wanted);
        break;
    case kOldMinor:
        _snprintf_s(out, cap, _TRUNCATE, "%ls is version %u.%u, the mod needs %u.%u or newer", p.name, p.found, p.foundMinor,
                    p.wanted, p.wantedMinor);
        break;
    case kFolderUnknown:
        _snprintf_s(out, cap, _TRUNCATE, "the folder %ls is in could not be determined (path too long?)", p.name);
        break;
    default:
        _snprintf_s(out, cap, _TRUNCATE, "%ls ok", p.name);
    }
}

// The uimod.log line(s): every problem, one per line, each prefixed.
inline void DescribeForLog(const Report& r, const char* prefix, char* out, size_t cap)
{
    size_t o = 0;
    out[0] = 0;
    for (int i = 0; i < r.nProblems && o + 1 < cap; ++i) {
        char one[256];
        DescribeProblem(r.problems[i], one, sizeof one);
        const int w = _snprintf_s(out + o, cap - o, _TRUNCATE, "%s%s\n", prefix, one);
        if (w < 0) break;
        o += static_cast<size_t>(w);
    }
}

// A signature of the problem set ("avcodec-62.dll:1;avutil-60.dll:3;"): the notice is shown once per
// distinct set, so a player who fixed one file and broke another hears about the new one.
inline void Signature(const Report& r, char* out, size_t cap)
{
    size_t o = 0;
    out[0] = 0;
    for (int i = 0; i < r.nProblems; ++i) {
        const int w = _snprintf_s(out + o, cap - o, _TRUNCATE, "%ls:%d;", r.problems[i].name, static_cast<int>(r.problems[i].fault));
        if (w < 0) break;
        o += static_cast<size_t>(w);
    }
}

// The in-game notice. Plain words, the file names, the remedy; the label writer wraps it.
inline void NoticeBody(const Report& r, char* out, size_t cap)
{
    size_t o = 0;
    int w = _snprintf_s(out, cap, _TRUNCATE,
                        "The Longevity Vaccine's in-game movie player is off: ");
    o = w > 0 ? static_cast<size_t>(w) : 0;
    for (int i = 0; i < r.nProblems && o + 1 < cap; ++i) {
        char one[256];
        DescribeProblem(r.problems[i], one, sizeof one);
        w = _snprintf_s(out + o, cap - o, _TRUNCATE, "%s%s", i ? "; " : "", one);
        if (w < 0) break;
        o += static_cast<size_t>(w);
    }
    _snprintf_s(out + o, cap - o, _TRUNCATE,
                ". These files belong in the game's folder and came with the mod; an antivirus, an incomplete copy or "
                "another program's copy of the same library is the usual cause. Cinematics play the original way "
                "meanwhile, and everything else in the mod works. To get the movie player back, re-run the Longevity "
                "Vaccine installer (it restores the files).");
}

} // namespace codecs
