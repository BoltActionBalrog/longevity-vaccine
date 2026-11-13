// Self-test harness for basehd_law.h and hdpack.h (tests\test_basehd_law.py builds it once and runs every case
// through ONE process per mode).
//   basehd_selftest law <in.bin> <out.bin>
//     in : int32 n ; n x { int32 sw, sh, spitch, dw, dh, num, den ; 1024 B RGBQUAD table ; spitch*sh B indices }
//     out: n x { int32 cell_w, cell_h (CellSize(sw, sh, num, den)) ; dw*dh B indices (PaletteBoxShrink to dw x dh) }
//   basehd_selftest pack <list.txt> <out.bin>
//     list: one case per line: <pcx path> <wantW> <wantH> <palette path or -> <x0> <y0> <cw> <ch>
//     out : per case int32 hdpack::Result ; when kOk, int32 expand_ok and cw*ch B (Expand through the identity map)
#include <cstdio>
#include <cstring>
#include <vector>
#include "../../src/uimod/src/basehd_law.h"
#include "../../src/uimod/src/hdpack.h"

static int Law(const char* in, const char* out)
{
    FILE* f = std::fopen(in, "rb");
    if (!f) return 3;
    FILE* o = std::fopen(out, "wb");
    if (!o) return 7;
    int32_t n = 0;
    if (std::fread(&n, 4, 1, f) != 1) return 4;
    for (int c = 0; c < n; ++c) {
        int32_t hdr[7];
        if (std::fread(hdr, 4, 7, f) != 7) return 4;
        const int sw = hdr[0], sh = hdr[1], spitch = hdr[2], dw = hdr[3], dh = hdr[4];
        std::vector<uint8_t> pal(1024), src(static_cast<size_t>(spitch) * sh), dst(static_cast<size_t>(dw) * dh);
        if (std::fread(pal.data(), 1, 1024, f) != 1024) return 5;
        if (std::fread(src.data(), 1, src.size(), f) != src.size()) return 6;
        int ow = 0, oh = 0;
        basehd_law::CellSize(sw, sh, hdr[5], hdr[6], &ow, &oh);
        basehd_law::PaletteBoxShrink(src.data(), sw, sh, spitch, dst.data(), dw, dh, dw, pal.data());
        const int32_t head[2] = { ow, oh };
        std::fwrite(head, 4, 2, o);
        std::fwrite(dst.data(), 1, dst.size(), o);
    }
    std::fclose(f);
    std::fclose(o);
    return 0;
}

static int Pack(const char* list, const char* out)
{
    FILE* f = std::fopen(list, "r");
    if (!f) return 3;
    FILE* o = std::fopen(out, "wb");
    if (!o) return 7;
    uint8_t ident[256];
    for (int i = 0; i < 256; ++i) ident[i] = static_cast<uint8_t>(i);
    char path[1024], palPath[1024];
    int w, h, x0, y0, cw, ch;
    while (std::fscanf(f, "%1023s %d %d %1023s %d %d %d %d", path, &w, &h, palPath, &x0, &y0, &cw, &ch) == 8) {
        uint8_t pal[768];
        const bool havePal = std::strcmp(palPath, "-") != 0 && hdpack::ReadPalette(palPath, pal);
        hdpack::Pack p;
        const int32_t r = hdpack::Load(&p, path, w, h, havePal ? pal : nullptr);
        std::fwrite(&r, 4, 1, o);
        if (r == hdpack::kOk) {
            std::vector<uint8_t> px(static_cast<size_t>(cw) * ch);
            const int32_t ok = hdpack::Expand(p, x0, y0, cw, ch, ident, px.data()) ? 1 : 0;
            std::fwrite(&ok, 4, 1, o);
            std::fwrite(px.data(), 1, px.size(), o);
        }
        hdpack::Free(&p);
    }
    std::fclose(f);
    std::fclose(o);
    return 0;
}

int main(int argc, char** argv)
{
    if (argc != 4) return 2;
    if (std::strcmp(argv[1], "law") == 0) return Law(argv[2], argv[3]);
    if (std::strcmp(argv[1], "pack") == 0) return Pack(argv[2], argv[3]);
    return 2;
}
