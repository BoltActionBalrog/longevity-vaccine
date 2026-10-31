// Self-test harness for portrait_law.h FieldEnlarge (tests\test_art_field_port.py builds and runs it).
// stdin-free: art_field_selftest <in.bin> <out.bin>
//   in : int32 sw, sh, pitch, key, num, den, y0 (dest-buffer row of device row 0) ; 1024 B RGBQUAD table ;
//        pitch*sh B indices
//   out: int32 applies, dw, dh ; dw*dh int32 (index or -1)
#include <cstdio>
#include <vector>
#include "../../src/uimod/src/portrait_law.h"

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) return 3;
    int32_t hdr[7];
    if (std::fread(hdr, 4, 7, f) != 7) return 4;
    std::vector<uint8_t> pal(1024), src(static_cast<size_t>(hdr[2]) * hdr[1]);
    if (std::fread(pal.data(), 1, 1024, f) != 1024) return 5;
    if (std::fread(src.data(), 1, src.size(), f) != src.size()) return 6;
    std::fclose(f);
    int dw = 0, dh = 0;
    std::vector<int> out;
    const bool ok = portrait_law::FieldEnlarge(src.data(), hdr[2], hdr[0], hdr[1], hdr[3], pal.data(), hdr[4], hdr[5], &dw, &dh, &out,
                                                  hdr[6]);
    FILE* o = std::fopen(argv[2], "wb");
    if (!o) return 7;
    const int32_t head[3] = { ok ? 1 : 0, dw, dh };
    std::fwrite(head, 4, 3, o);
    if (ok) std::fwrite(out.data(), 4, out.size(), o);
    std::fclose(o);
    return 0;
}
