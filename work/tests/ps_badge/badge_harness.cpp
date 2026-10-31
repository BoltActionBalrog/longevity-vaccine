// Offline dump of the uimod Punishment Sphere / nerve-staple badge rasterisers (src\uimod\src\psbadge.h): no
// game, no Windows. Usage: badge_harness <faceW>...  (a width prefixed with 's', e.g. s38, dumps the STAPLE
// glyph)  ->  per face width one line "faceW d inset r0 g0 b0 ... r4 g4 b4" then d rows of d tone characters
// ('.' = not drawn, '0'..'4').
#include <cstdio>
#include <cstdlib>

#include "psbadge.h"

int main(int argc, char** argv)
{
    static int8_t tones[psbadge::kMaxDiameter * psbadge::kMaxDiameter];
    for (int a = 1; a < argc; ++a) {
        const bool staple = argv[a][0] == 's';
        const int faceW = std::atoi(staple ? argv[a] + 1 : argv[a]);
        const int d = psbadge::Diameter(faceW);
        if (d < 1 || d > psbadge::kMaxDiameter) return 2;
        std::printf("%d %d %d", faceW, d, psbadge::Inset(faceW));
        for (int t = 0; t < 5; ++t)
            for (int k = 0; k < 3; ++k) std::printf(" %d", staple ? psbadge::RampChannelStaple(t, k) : psbadge::RampChannel(t, k));
        std::printf("\n");
        if (staple) psbadge::RasterStaple(d, tones); else psbadge::Raster(d, tones);
        for (int y = 0; y < d; ++y) {
            for (int x = 0; x < d; ++x) std::putchar(tones[y * d + x] < 0 ? '.' : '0' + tones[y * d + x]);
            std::putchar('\n');
        }
    }
    return 0;
}
