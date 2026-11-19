// thinkerlive.h -- the Thinker startup check's readers of things OUTSIDE our control: process memory another module
// owns, and small files on disk. Windows-only, no globals, no logging: each returns what it found and, where it
// matters, why not -- so work\tests\thinkerlive_selftest.cpp can run every one of them against real pages and real
// files (a committed page followed by a reserved one; a file with a BOM; a file that is not there).
#pragma once

#include <windows.h>
#include <string>

#include "thinkercheck_core.h"

namespace thinkerlive {

using thinkercheck::Label;

// A wide string as UTF-8 for the log. The CRT's %ls gives up on a character outside the ANSI code page and leaves
// the WHOLE line empty -- exactly the lines that explain a failure in a game folder with such a name.
inline std::string Utf8(const wchar_t* w)
{
    if (!w) return std::string();
    const int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    if (n <= 1) return std::string();
    std::string s(static_cast<size_t>(n - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w, -1, &s[0], n, nullptr, nullptr);
    return s;
}

// `len` bytes at `p` are committed, readable memory inside ONE region.
inline bool Readable(const void* p, size_t len)
{
    MEMORY_BASIC_INFORMATION mbi;
    if (!p || VirtualQuery(p, &mbi, sizeof mbi) != sizeof mbi) return false;
    if (mbi.State != MEM_COMMIT || mbi.Protect == 0 || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    const uintptr_t end = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    return reinterpret_cast<uintptr_t>(p) + len <= end;
}

// What a module calls itself, from the string `p` points at. Only a pointer INTO the image [lo, hi), to committed
// readable memory, is followed; the read stops at the end of that region and of the image, and at 64 bytes; a string
// with no terminator inside that span is not a label. `*why` (optional) names the reason when there is none.
inline Label ReadLabel(const char* p, uintptr_t lo, uintptr_t hi, const char** why = nullptr)
{
    auto no = [&](const char* w) { if (why) *why = w; return Label(); };
    if (why) *why = nullptr;
    const uintptr_t a = reinterpret_cast<uintptr_t>(p);
    if (a < lo || a >= hi) return no("the pointer is not inside the image");
    MEMORY_BASIC_INFORMATION mbi;
    if (VirtualQuery(p, &mbi, sizeof mbi) != sizeof mbi || mbi.State != MEM_COMMIT || mbi.Protect == 0 ||
        (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return no("the string is not readable memory");
    uintptr_t end = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    if (end > hi) end = hi;
    size_t n = end - a;
    if (n > 64) n = 64;
    size_t len = 0;
    while (len < n && p[len]) ++len;
    if (len == n) return no("the string has no terminator inside the readable span");
    const Label l = thinkercheck::ParseLabel(p, n);
    if (l.kind == thinkercheck::LabelKind::Unrecognised && why) *why = "the string is not a Thinker Mod label";
    return l;
}

// The first `cap` bytes of a small file; false when it cannot be opened or read. Shared read: the file may be open
// elsewhere.
inline bool ReadHead(const wchar_t* path, std::string* out, size_t cap)
{
    out->clear();
    const HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                 OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    out->resize(cap);
    DWORD got = 0;
    const BOOL ok = ReadFile(h, &(*out)[0], static_cast<DWORD>(cap), &got, nullptr);
    CloseHandle(h);
    out->resize(ok ? got : 0);
    return ok != 0;
}

// The resident installer copy's VERSION file: one short line ("1.2.0\n"). A UTF-8 BOM and trailing white space are
// dropped; anything else is returned as it is (thinkercheck::VersionOlder then decides it is not a version).
inline std::string ReadVersionFile(const wchar_t* path)
{
    std::string v;
    if (!ReadHead(path, &v, 40)) return std::string();
    if (v.size() >= 3 && static_cast<unsigned char>(v[0]) == 0xEF && static_cast<unsigned char>(v[1]) == 0xBB &&
        static_cast<unsigned char>(v[2]) == 0xBF)
        v.erase(0, 3);
    while (!v.empty() && (v.back() == '\n' || v.back() == '\r' || v.back() == ' ' || v.back() == '\t')) v.pop_back();
    return v;
}

// True when the file holds `token` (plain bytes). The pre-flight of "Update now" asks the resident installer's own
// install.py whether it knows `--fix-thinker`: a capability, not a version number -- the one shipped release that
// lacks it would otherwise close the game and answer with an argument error.
inline bool FileMentions(const wchar_t* path, const char* token)
{
    const HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                 OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    const size_t tn = strlen(token);
    std::string buf, carry;
    bool found = false;
    buf.resize(64 * 1024);
    for (;;) {
        DWORD got = 0;
        if (!ReadFile(h, &buf[0], static_cast<DWORD>(buf.size()), &got, nullptr) || got == 0) break;
        const std::string chunk = carry + buf.substr(0, got);          // a token may straddle two reads
        if (tn && chunk.find(token, 0, tn) != std::string::npos) { found = true; break; }
        carry = chunk.size() >= tn ? chunk.substr(chunk.size() - (tn ? tn - 1 : 0)) : chunk;
    }
    CloseHandle(h);
    return found;
}

// What a thinker.dll FILE calls itself, by the installer's rule (thinker_state.dll_label): every NUL-terminated
// "Thinker Mod v<version>" / "Thinker Mod develop build" string in the file must agree; if they do, that is the
// label, otherwise (none, or two different ones) it is unrecognised. Used only when Thinker is not loaded in the
// process and the in-game offer still has to name the folder's build. `*readOk` says the file could be read at all.
inline Label LabelFromFile(const wchar_t* path, bool* readOk = nullptr)
{
    if (readOk) *readOk = false;
    const HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                 OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (h == INVALID_HANDLE_VALUE) return Label();
    LARGE_INTEGER size;
    if (!GetFileSizeEx(h, &size) || size.QuadPart <= 0 || size.QuadPart > 64 * 1024 * 1024) { CloseHandle(h); return Label(); }
    std::string data(static_cast<size_t>(size.QuadPart), '\0');
    DWORD got = 0;
    const BOOL ok = ReadFile(h, &data[0], static_cast<DWORD>(data.size()), &got, nullptr);
    CloseHandle(h);
    if (!ok || got != data.size()) return Label();
    if (readOk) *readOk = true;

    constexpr char kKey[] = "Thinker Mod ";
    const size_t kn = sizeof kKey - 1;
    Label found;
    bool any = false;
    for (size_t at = data.find(kKey, 0, kn); at != std::string::npos; at = data.find(kKey, at + 1, kn)) {
        size_t end = at + kn;                                           // at most 40 characters after the key, then NUL
        while (end < data.size() && end - (at + kn) < 40 && data[end]) ++end;
        if (end == data.size() || data[end]) continue;                 // not terminated in time: not a label
        const Label l = thinkercheck::ParseLabel(data.data() + at, end - at + 1);
        if (l.kind == thinkercheck::LabelKind::Unrecognised) continue; // "Thinker Mod " followed by other text
        if (any && (l.kind != found.kind || strcmp(l.version, found.version) != 0)) return Label();   // they disagree
        found = l;
        any = true;
    }
    return any ? found : Label();
}

} // namespace thinkerlive
