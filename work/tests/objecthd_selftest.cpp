// Self-test harness for objecthd_table.h (tests\test_objecthd_sites.py builds and runs it): prints the table the hook
// draws by, one row per line: <va hex> <sheet> <x> <y>.
#include <cstdio>
#include "../../src/uimod/src/objecthd_table.h"

int main()
{
    objecthd_table::Row rows[objecthd_table::kRows];
    const int n = objecthd_table::Build(rows);
    for (int i = 0; i < n; ++i)
        std::printf("%08X %d %d %d\n", static_cast<unsigned>(rows[i].va), rows[i].sheet, rows[i].x, rows[i].y);
    return 0;
}
