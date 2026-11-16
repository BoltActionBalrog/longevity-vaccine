// Self-test harness for menuhd_law.h (tests\test_menuhd_law.py builds it once and runs every case of a test through
// ONE process).
//   menuhd_selftest layout   stdin: "w h" per line  ->  "num den x0 y0 coreW coreH stripW stripX mx my mw mh"
//   menuhd_selftest axis     stdin: "nDst sn sd nSrc" per line  ->  "1 n k:w k:w ..." per screen pixel ("0" if not ok)
//   menuhd_selftest lanczos  ->  the 64 x 6 weight table, one row per line
//   menuhd_selftest resample <in.bin> <out.bin>
//     in : int32 n ; n x { int32 sw, sh, key, sn, sd, dw, dh, lo, hi ; 768 B pal ; 1024 B canvas ; sw*sh B indices }
//     out: n x { int32 ok ; dw*dh B }
#include <cstdio>
#include <cstring>
#include <vector>
#include "../../src/uimod/src/menuhd_law.h"

using namespace menuhd_law;

static int LayoutMode()
{
    int w, h;
    while (std::scanf("%d %d", &w, &h) == 2) {
        const Layout l = MenuLayout(w, h);
        const Rect m = MoonRect(l);
        std::printf("%d %d %d %d %d %d %d %d %d %d %d %d\n", l.num, l.den, l.x0, l.y0, l.coreW, l.coreH, l.stripW,
                    l.stripX, m.x, m.y, m.w, m.h);
    }
    return 0;
}

static int AxisMode()
{
    long long n, sn, sd, src;
    while (std::scanf("%lld %lld %lld %lld", &n, &sn, &sd, &src) == 4) {
        std::vector<AxisPx> px(static_cast<size_t>(n));
        if (!Axis(static_cast<int>(n), sn, sd, static_cast<int>(src), px.data())) { std::printf("0\n"); continue; }
        for (const AxisPx& p : px) {
            std::printf("1 %d", p.n);
            for (int t = 0; t < p.n; ++t) std::printf(" %d:%d", p.t[t].k, p.t[t].w);
            std::printf("\n");
        }
    }
    return 0;
}

struct Src { const uint8_t* px; int w; };
static const uint8_t* RowOf(void* ctx, int r)
{
    const Src* s = static_cast<const Src*>(ctx);
    return s->px + static_cast<size_t>(r) * s->w;
}

static int ResampleMode(const char* in, const char* out)
{
    FILE* f = std::fopen(in, "rb");
    FILE* o = std::fopen(out, "wb");
    if (!f || !o) return 3;
    int32_t n = 0;
    if (std::fread(&n, 4, 1, f) != 1) return 4;
    for (int c = 0; c < n; ++c) {
        int32_t hd[9];
        if (std::fread(hd, 4, 9, f) != 9) return 4;
        const int sw = hd[0], sh = hd[1], dw = hd[5], dh = hd[6];
        std::vector<uint8_t> pal(768), canvas(1024), src(static_cast<size_t>(sw) * sh), dst(static_cast<size_t>(dw) * dh);
        std::vector<uint8_t> lut(32768);
        if (std::fread(pal.data(), 1, 768, f) != 768 || std::fread(canvas.data(), 1, 1024, f) != 1024 ||
            std::fread(src.data(), 1, src.size(), f) != src.size()) return 5;
        NearestLut(canvas.data(), hd[7], hd[8], lut.data());
        Src s{src.data(), sw};
        const int32_t ok = Resample(&RowOf, &s, sw, sh, pal.data(), hd[2], hd[3], hd[4], dw, dh, dst.data(), dw,
                                    canvas.data(), hd[7], hd[8], lut.data()) ? 1 : 0;
        std::fwrite(&ok, 4, 1, o);
        std::fwrite(dst.data(), 1, dst.size(), o);
    }
    std::fclose(f);
    std::fclose(o);
    return 0;
}

int main(int argc, char** argv)
{
    if (argc >= 2 && std::strcmp(argv[1], "layout") == 0) return LayoutMode();
    if (argc >= 2 && std::strcmp(argv[1], "axis") == 0) return AxisMode();
    if (argc >= 2 && std::strcmp(argv[1], "lanczos") == 0) {
        for (const auto& row : kLanczos) {
            for (int t = 0; t < kTaps; ++t) std::printf(t ? " %d" : "%d", row[t]);
            std::printf("\n");
        }
        return 0;
    }
    if (argc == 4 && std::strcmp(argv[1], "resample") == 0) return ResampleMode(argv[2], argv[3]);
    return 2;
}
