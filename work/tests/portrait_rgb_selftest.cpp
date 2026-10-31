// Self-test harness for the replacement-portrait half of portrait_law.h (tests\test_portrait_rgb_port.py builds
// and runs it).  stdin-free: portrait_rgb_selftest <in.bin> <out.bin>
//   in : int32 mode, sw, sh, pitch, key, num, den, w, h, scan (0 off / 1 overlay / 2 mean; | 0x100 = unframed),
//        y0 (modes 3 / 5: the dest-buffer row of device row 0)
//        1024 B RGBQUAD table ; pitch*sh B art indices ; w*h*3 B rgb
//   mode 0 = Prereduce       out: int32 ow, oh ; ow*oh*3 B
//   mode 1 = FrameRect(w,h,sw,sh)  out: int32 x, y, cw, ch
//   mode 2 = ScanlineParams + Bake  out: int32 ok, bright, ratio ; (sw-2)*(sh-2) int32
//   mode 3 = ScanlineParams + EnlargeRgb  out: int32 ok, dw, dh ; dw*dh int32 (index or -1)
#include <cstdio>
#include <vector>
#include "../../src/uimod/src/portrait_law.h"

// mode 4/5: Bake / EnlargeRgb run TWICE through a ResampleCache (the second run hits it, possibly in another scan
// mode -- the first run uses OVERLAY): its output must equal the uncached law
struct MemCache : portrait_law::ResampleCache {
    bool has = false; portrait_law::Rect c{}; int tw = 0, th = 0; std::vector<int> big;
    const std::vector<int>* Get(portrait_law::Rect cr, int w, int h) override
    { return has && cr.x == c.x && cr.y == c.y && cr.w == c.w && cr.h == c.h && w == tw && h == th ? &big : nullptr; }
    void Put(portrait_law::Rect cr, int w, int h, const std::vector<int>& b) override
    { has = true; c = cr; tw = w; th = h; big = b; }
};

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) return 3;
    int32_t hd[11];
    if (std::fread(hd, 4, 11, f) != 11) return 4;
    const int mode = hd[0], sw = hd[1], sh = hd[2], pitch = hd[3], key = hd[4], num = hd[5], den = hd[6];
    const int w = hd[7], h = hd[8], y0 = hd[10];
    const int scan = hd[9] & 0xFF;
    const bool framed = (hd[9] & 0x100) == 0;   // bit 8 set = unframed art (the council slots)
    // mode 0 carries rgb only, mode 1 neither plane (sw/sh/w/h are just the rect inputs)
    std::vector<uint8_t> pal(1024), src(mode >= 2 ? static_cast<size_t>(pitch) * (sh > 0 ? sh : 0) : 0);
    std::vector<uint8_t> rgb(mode != 1 && w > 0 && h > 0 ? static_cast<size_t>(w) * h * 3 : 0);
    if (std::fread(pal.data(), 1, 1024, f) != 1024) return 5;
    if (!src.empty() && std::fread(src.data(), 1, src.size(), f) != src.size()) return 6;
    if (!rgb.empty() && std::fread(rgb.data(), 1, rgb.size(), f) != rgb.size()) return 7;
    std::fclose(f);
    FILE* o = std::fopen(argv[2], "wb");
    if (!o) return 8;
    if (mode == 0) {
        std::vector<uint8_t> out; int ow = w, oh = h;
        if (!portrait_law::Prereduce(rgb.data(), w, h, &out, &ow, &oh)) out = rgb;
        const int32_t head[2] = { ow, oh };
        std::fwrite(head, 4, 2, o);
        std::fwrite(out.data(), 1, out.size(), o);
    } else if (mode == 1) {
        const portrait_law::Rect r = portrait_law::FrameRect(w, h, sw, sh);
        const int32_t v[4] = { r.x, r.y, r.w, r.h };
        std::fwrite(v, 4, 4, o);
    } else {
        int bright = 0, ratio = 0;
        portrait_law::ScanlineParams(src.data(), pitch, sw, sh, pal.data(), &bright, &ratio);
        std::vector<int> out; bool ok; int32_t head[3];
        MemCache cache;
        if (mode == 4) {
            std::vector<int> warm;
            portrait_law::Bake(sw, sh, pal.data(), rgb.data(), rgb.size(), w, h, portrait_law::kScanOverlay, bright, ratio,
                               &warm, framed, &cache);
            ok = portrait_law::Bake(sw, sh, pal.data(), rgb.data(), rgb.size(), w, h, scan, bright, ratio, &out, framed,
                                    &cache);
            head[0] = ok && cache.has ? 1 : 0; head[1] = bright; head[2] = ratio;
        } else if (mode == 5) {
            int dw = 0, dh = 0;
            std::vector<int> warm;
            portrait_law::EnlargeRgb(src.data(), pitch, sw, sh, key, pal.data(), num, den, rgb.data(), rgb.size(), w, h,
                                     portrait_law::kScanOverlay, bright, ratio, &dw, &dh, &warm, framed, &cache);
            ok = portrait_law::EnlargeRgb(src.data(), pitch, sw, sh, key, pal.data(), num, den, rgb.data(), rgb.size(),
                                          w, h, scan, bright, ratio, &dw, &dh, &out, framed, &cache, y0);
            head[0] = ok && cache.has ? 1 : 0; head[1] = dw; head[2] = dh;
        } else if (mode == 2) {
            ok = portrait_law::Bake(sw, sh, pal.data(), rgb.data(), rgb.size(), w, h, scan, bright, ratio, &out, framed);
            head[0] = ok ? 1 : 0; head[1] = bright; head[2] = ratio;
        } else {
            int dw = 0, dh = 0;
            ok = portrait_law::EnlargeRgb(src.data(), pitch, sw, sh, key, pal.data(), num, den, rgb.data(), rgb.size(), w, h,
                                          scan, bright, ratio, &dw, &dh, &out, framed, nullptr, y0);
            head[0] = ok ? 1 : 0; head[1] = dw; head[2] = dh;
        }
        std::fwrite(head, 4, 3, o);
        if (ok) std::fwrite(out.data(), 4, out.size(), o);
    }
    std::fclose(o);
    return 0;
}
