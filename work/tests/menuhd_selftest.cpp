// Self-test harness for menuhd_law.h (tests\test_menuhd_law.py builds and runs it).
// menuhd_selftest <w> <h>  ->  prints "num den coreH y0 stripW stripX"
#include <cstdio>
#include <cstdlib>
#include "../../src/uimod/src/menuhd_law.h"

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    const menuhd_law::Layout l = menuhd_law::MenuLayout(std::atoi(argv[1]), std::atoi(argv[2]));
    std::printf("%d %d %d %d %d %d\n", l.num, l.den, l.coreH, l.y0, l.stripW, l.stripX);
    return 0;
}
