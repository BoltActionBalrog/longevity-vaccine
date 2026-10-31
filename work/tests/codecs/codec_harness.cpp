// Offline drive of the codec-DLL probe (src\uimod\src\codecs.h) -- no game.
// Usage: codec_harness probe <dir> <name>:<versionExport>:<major>[.<minor>] ...
// Prints: problems=<n> libs=<n>, one "problem <name> fault=<f> error=<e> found=<x> wanted=<y>" per problem,
// then LOG:/NOTICE:/SIG: lines with the texts the DLL would log, show and remember.
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "../../../src/uimod/src/codecs.h"

int main(int argc, char** argv)
{
    if (argc < 4 || strcmp(argv[1], "probe") != 0) { fprintf(stderr, "args\n"); return 2; }
    std::wstring dir;
    for (const char* p = argv[2]; *p; ++p) dir += static_cast<wchar_t>(static_cast<unsigned char>(*p));

    std::vector<std::wstring> names;
    std::vector<std::string> exports;
    std::vector<codecs::Lib> libs;
    for (int i = 3; i < argc; ++i) {
        std::string spec = argv[i];
        const size_t a = spec.find(':'), b = spec.rfind(':');
        if (a == std::string::npos || b == a) { fprintf(stderr, "bad spec %s\n", argv[i]); return 2; }
        std::wstring n;
        for (char c : spec.substr(0, a)) n += static_cast<wchar_t>(static_cast<unsigned char>(c));
        names.push_back(n);
        exports.push_back(spec.substr(a + 1, b - a - 1));
        char* end = nullptr;
        const unsigned major = static_cast<unsigned>(strtoul(spec.c_str() + b + 1, &end, 10));
        const unsigned minor = (end && *end == '.') ? static_cast<unsigned>(strtoul(end + 1, nullptr, 10)) : 0;
        codecs::Lib l{ nullptr, nullptr, major, minor };
        libs.push_back(l);
    }
    for (size_t i = 0; i < libs.size(); ++i) { libs[i].name = names[i].c_str(); libs[i].versionExport = exports[i].c_str(); }

    codecs::Report r;
    codecs::Probe(dir.c_str(), libs.data(), static_cast<int>(libs.size()), r);
    printf("problems=%d libs=%d\n", r.nProblems, r.nLibs);
    for (int i = 0; i < r.nProblems; ++i) {
        const codecs::Problem& p = r.problems[i];
        printf("problem %ls fault=%d error=%lu found=%u wanted=%u foundminor=%u wantedminor=%u\n", p.name,
               static_cast<int>(p.fault), p.error, p.found, p.wanted, p.foundMinor, p.wantedMinor);
    }
    char log[1024], notice[2048], sig[256];
    codecs::DescribeForLog(r, "[uimod] codecs: ", log, sizeof log);
    codecs::NoticeBody(r, notice, sizeof notice);
    codecs::Signature(r, sig, sizeof sig);
    for (char* p = log; *p; ++p) if (*p == '\n') *p = '|';
    printf("LOG:%s\nNOTICE:%s\nSIG:%s\n", log, notice, sig);
    return 0;
}
