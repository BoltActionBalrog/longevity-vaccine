// Self-test harness for the pure helpers of portrait_files.h (tests\test_portrait_files.py builds and runs it).
//   portrait_files_selftest <mode> <arg>   mode: safe | native | base   -> prints "1"/"0" (base: the name or "-")
#include <cstdio>
#include <cstring>
#include "../../src/uimod/src/portrait_files.h"

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    const char* a = argv[2];
    if (std::strcmp(argv[1], "safe") == 0) { std::printf("%d", portrait_files::SafeName(a) ? 1 : 0); return 0; }
    if (std::strcmp(argv[1], "native") == 0) { std::printf("%d", portrait_files::IsNativeLifeName(a) ? 1 : 0); return 0; }
    if (std::strcmp(argv[1], "base") == 0) {
        char out[32];
        if (portrait_files::BaseName(a, out, sizeof out)) std::printf("%s", out); else std::printf("-");
        return 0;
    }
    return 3;
}
