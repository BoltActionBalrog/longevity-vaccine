// Stand-in for the installer's interpreter in test_thinker_startup.py: run-install.bat (the REAL file) starts it as
// "<python.exe> <install.py> <arguments>", and it writes what it was handed beside itself, one item per line (UTF-8):
// every argument after its own name, then "NOWAIT=<value or ->" (the batch file's own "do not pause" variable, which
// a child inherits). It creates the batch file's guard marker, as the real installer does, and exits 7.
#include <windows.h>
#include <cstdio>
#include <string>

static std::string Utf8(const wchar_t* w)
{
    const int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    std::string s(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, w, -1, &s[0], n, nullptr, nullptr);
    return s;
}

int wmain(int argc, wchar_t** argv)
{
    wchar_t self[MAX_PATH * 4];
    const DWORD n = GetModuleFileNameW(nullptr, self, ARRAYSIZE(self));
    if (!n || n >= ARRAYSIZE(self)) return 2;
    std::wstring out(self);
    out.resize(out.find_last_of(L'\\') + 1);
    out += L"argv.txt";

    FILE* f = _wfopen(out.c_str(), L"wb");
    if (!f) return 3;
    for (int i = 1; i < argc; ++i) fprintf(f, "%s\n", Utf8(argv[i]).c_str());
    wchar_t v[64];
    const DWORD got = GetEnvironmentVariableW(L"NOWAIT", v, ARRAYSIZE(v));
    fprintf(f, "NOWAIT=%s\n", got && got < ARRAYSIZE(v) ? Utf8(v).c_str() : "-");
    fclose(f);

    wchar_t marker[MAX_PATH * 4];
    const DWORD m = GetEnvironmentVariableW(L"LONGEVITY_GUARD_MARKER", marker, ARRAYSIZE(marker));
    if (m && m < ARRAYSIZE(marker)) {
        const HANDLE h = CreateFileW(marker, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
    }
    return 7;
}
