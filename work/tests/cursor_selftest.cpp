// Self-test harness for cursor_law.h (tests\test_cursor_port.py builds and runs it).
// cursor_selftest <in.bin> <out.bin>
//   in : int32 g, left, top, w, h, pitch, hx, hy ; pitch*h B content indices
//   out: int32 canvas, dl, dt, dw, dh, shx, shy ; dw*dh B indices
#include <cstdio>
#include <vector>
#include "../../src/uimod/src/cursor_law.h"

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) return 3;
    int32_t hdr[8];
    if (std::fread(hdr, 4, 8, f) != 8) return 4;
    std::vector<uint8_t> src(static_cast<size_t>(hdr[5]) * hdr[4]);
    if (!src.empty() && std::fread(src.data(), 1, src.size(), f) != src.size()) return 5;
    std::fclose(f);
    const int g = hdr[0];
    std::vector<uint8_t> out;
    const cursor_law::Rect d = cursor_law::Enlarge(src.data(), hdr[5], { hdr[1], hdr[2], hdr[3], hdr[4] }, g, &out);
    const int32_t o[7] = { cursor_law::CanvasPx(g), d.left, d.top, d.w, d.h,
                           cursor_law::Hotspot(hdr[6], g), cursor_law::Hotspot(hdr[7], g) };
    FILE* w = std::fopen(argv[2], "wb");
    if (!w) return 6;
    std::fwrite(o, 4, 7, w);
    if (!out.empty()) std::fwrite(out.data(), 1, out.size(), w);
    std::fclose(w);
    return 0;
}
