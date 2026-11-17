// terrainhd_law.h's laws, one case per stdin line (tests\test_terrainhd_law.py batches every case through one process):
//   zoom <w> <h>       -> MaxZoom(w, h)
//   level <w> <h>      -> Level(w, h)
//   tile <z> 0         -> TilePx(z)
//   span <c> <k>       -> Span(c, k)
//   nearest <n> <k> <hex of n*n bytes>  -> hex of the (nk)^2 result
//   code <n> <k> <hex: ncols, cols, bg, the 8n x 8n region>  -> hex of the (nk)^2 code map, then "<listed> <unlisted>"
// One output line per input line.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "../../src/uimod/src/terrainhd_law.h"

int main()
{
    char line[1 << 16];
    while (std::fgets(line, sizeof line, stdin)) {
        char mode[16] = {};
        int a = 0, b = 0;
        char hex[1 << 15] = {};
        const int got = std::sscanf(line, "%15s %d %d %32767s", mode, &a, &b, hex);
        if (got < 3) { std::printf("?\n"); continue; }
        if (!std::strcmp(mode, "zoom")) std::printf("%d\n", terrainhd::MaxZoom(a, b));
        else if (!std::strcmp(mode, "level")) std::printf("%d\n", terrainhd::Level(a, b));
        else if (!std::strcmp(mode, "tile")) std::printf("%d\n", terrainhd::TilePx(a));
        else if (!std::strcmp(mode, "span")) std::printf("%d\n", terrainhd::Span(a, b));
        else if (!std::strcmp(mode, "nearest") && got == 4) {
            const int n = a, k = b;
            std::vector<uint8_t> src(n * n), dst(n * k * n * k);
            for (int i = 0; i < n * n; ++i) {
                unsigned v = 0;
                std::sscanf(hex + 2 * i, "%2x", &v);
                src[i] = static_cast<uint8_t>(v);
            }
            terrainhd::Nearest(src.data(), n, k, dst.data());
            for (uint8_t v : dst) std::printf("%02x", v);
            std::printf("\n");
        } else if (!std::strcmp(mode, "code") && got == 4) {   // hex: ncols, cols, bg, the 8n x 8n region
            const int n = a, k = b;
            std::vector<uint8_t> in(std::strlen(hex) / 2);
            for (size_t i = 0; i < in.size(); ++i) {
                unsigned v = 0;
                std::sscanf(hex + 2 * i, "%2x", &v);
                in[i] = static_cast<uint8_t>(v);
            }
            const int ncols = in[0];
            const uint8_t* cols = in.data() + 1;
            const uint8_t bg = in[1 + ncols];
            const uint8_t* region = in.data() + 2 + ncols;
            std::vector<uint8_t> dst(n * k * n * k);
            int listed = 0, unlisted = 0;
            terrainhd::Code(region, n * terrainhd::kMaster, n, cols, ncols, bg, k, dst.data(), &listed, &unlisted);
            for (uint8_t v : dst) std::printf("%02x", v);
            std::printf(" %d %d\n", listed, unlisted);
        } else std::printf("?\n");
        std::fflush(stdout);
    }
    return 0;
}
