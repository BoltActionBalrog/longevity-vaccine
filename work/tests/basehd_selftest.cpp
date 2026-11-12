// Self-test harness for basehd_law.h (tests\test_basehd_law.py builds and runs it).
// stdin-free: basehd_selftest <in.bin> <out.bin>
//   in : int32 sw, sh, spitch, dw, dh, num, den ; 1024 B RGBQUAD table ; spitch*sh B indices
//   out: int32 size_w, size_h (SpriteSize(sw, sh, num, den)) ; dw*dh B indices (PaletteBoxShrink to dw x dh)
#include <cstdio>
#include <vector>
#include "../../src/uimod/src/basehd_law.h"

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) return 3;
    int32_t hdr[7];
    if (std::fread(hdr, 4, 7, f) != 7) return 4;
    const int sw = hdr[0], sh = hdr[1], spitch = hdr[2], dw = hdr[3], dh = hdr[4];
    std::vector<uint8_t> pal(1024), src(static_cast<size_t>(spitch) * sh), dst(static_cast<size_t>(dw) * dh);
    if (std::fread(pal.data(), 1, 1024, f) != 1024) return 5;
    if (std::fread(src.data(), 1, src.size(), f) != src.size()) return 6;
    std::fclose(f);
    int ow = 0, oh = 0;
    basehd_law::SpriteSize(sw, sh, hdr[5], hdr[6], &ow, &oh);
    basehd_law::PaletteBoxShrink(src.data(), sw, sh, spitch, dst.data(), dw, dh, dw, pal.data());
    FILE* o = std::fopen(argv[2], "wb");
    if (!o) return 7;
    const int32_t head[2] = { ow, oh };
    std::fwrite(head, 4, 2, o);
    std::fwrite(dst.data(), 1, dst.size(), o);
    std::fclose(o);
    return 0;
}
