#pragma once
// photo_resample.h -- the one photographic resampler the HD picture hooks share (menuhd.cpp, monumenthd.cpp): each
// destination pixel is the area-weighted average colour of the source pixels it covers, Floyd-Steinberg-dithered
// into the colours of the canvas it is drawn on. Uniform: one source-pixels-per-destination-pixel factor f for both
// axes. Photographic art is enlarged smoothly and error-diffused, as the mod's own picture scaling does.

#include <cstdint>
#include <cstring>
#include <vector>

namespace photo {

// The canvas colours a picture is drawn into, and a 5-bit RGB -> nearest canvas index lookup restricted to them.
struct Target {
    uint8_t rgb[256][3];
    std::vector<uint8_t> lut;
    int lo = 0, hi = 255;                     // the canvas indices the dither may use
};

// A canvas holding art loaded with Buffer_load_pcx(name, 0, base, count): canvas index base + i shows file colour i.
inline void Build(Target& t, const uint8_t* filePal, int base, int count)
{
    memset(t.rgb, 0, sizeof t.rgb);
    for (int i = 0; i < count; ++i)
        for (int c = 0; c < 3; ++c) t.rgb[(base + i) & 255][c] = filePal[i * 3 + c];
    t.lo = base;
    t.hi = base + count - 1;
    t.lut.assign(32 * 32 * 32, 0);
    for (int i = 0; i < 32 * 32 * 32; ++i) {
        const int r = (i >> 10) * 255 / 31, g = (i >> 5 & 31) * 255 / 31, b = (i & 31) * 255 / 31;
        int best = t.lo, bestD = 1 << 30;
        for (int v = t.lo; v <= t.hi; ++v) {
            const int dr = r - t.rgb[v][0], dg = g - t.rgb[v][1], db = b - t.rgb[v][2];
            const int d = 2 * dr * dr + 4 * dg * dg + 3 * db * db;
            if (d < bestD) { bestD = d; best = v; }
        }
        t.lut[i] = static_cast<uint8_t>(best);
    }
}

// What a source coordinate outside the picture reads as.
enum class Edge { Black, Mirror };

inline int Reflect(int v, int n)
{
    if (n <= 1) return 0;
    while (v < 0 || v >= n) v = v < 0 ? -v - 1 : 2 * n - v - 1;
    return v;
}

// Source rect from (sx, sy), f source px per destination px on both axes, into dst (dw x dh, row pitch dp).
// src: sw x sh index pixels (row pitch spitch), pal: its 768-byte palette. key >= 0: that source index is see-through;
// a destination pixel more than half see-through becomes keyOut. Outside the picture reads as the mirrored picture
// (Edge::Mirror), else as see-through (key >= 0) or black.
inline void Resample(const uint8_t* src, int sw, int sh, int spitch, const uint8_t* pal, int key, double sx, double sy,
                     double f, uint8_t* dst, int dw, int dh, int dp, const Target& t, uint8_t keyOut,
                     Edge edge = Edge::Black)
{
    std::vector<float> err(static_cast<size_t>(dw + 2) * 3 * 2, 0.0f);
    float* cur = err.data();
    float* nxt = cur + (dw + 2) * 3;
    for (int y = 0; y < dh; ++y) {
        const double y0 = sy + y * f, y1 = y0 + f;
        for (int x = 0; x < dw; ++x) {
            const double x0 = sx + x * f, x1 = x0 + f;
            double acc[3] = {0, 0, 0}, wsum = 0, keyw = 0;
            for (int yy = static_cast<int>(y0 < 0 ? y0 - 1 : y0); yy < y1; ++yy) {
                const double wy = (yy + 1 < y1 ? yy + 1 : y1) - (yy > y0 ? yy : y0);
                if (wy <= 0) continue;
                for (int xx = static_cast<int>(x0 < 0 ? x0 - 1 : x0); xx < x1; ++xx) {
                    const double wx = (xx + 1 < x1 ? xx + 1 : x1) - (xx > x0 ? xx : x0);
                    if (wx <= 0) continue;
                    const double wgt = wx * wy;
                    int px = xx, py = yy;
                    if (px < 0 || py < 0 || px >= sw || py >= sh) {
                        if (edge == Edge::Mirror) {          // mirroring wins: the picture continues past its edge
                            px = Reflect(px, sw);
                            py = Reflect(py, sh);
                        } else if (key >= 0) {
                            keyw += wgt;
                            continue;
                        } else {
                            wsum += wgt;                     // black
                            continue;
                        }
                    }
                    const int v = src[static_cast<size_t>(py) * spitch + px];
                    if (v == key) { keyw += wgt; continue; }
                    acc[0] += wgt * pal[v * 3];
                    acc[1] += wgt * pal[v * 3 + 1];
                    acc[2] += wgt * pal[v * 3 + 2];
                    wsum += wgt;
                }
            }
            uint8_t& out = dst[static_cast<size_t>(y) * dp + x];
            if (key >= 0 && keyw > wsum) {
                out = keyOut;
                continue;
            }
            float c[3];
            for (int i = 0; i < 3; ++i) {
                const float v = static_cast<float>(wsum > 0 ? acc[i] / wsum : 0) + cur[(x + 1) * 3 + i];
                c[i] = v < 0 ? 0 : v > 255 ? 255 : v;
            }
            const int r = static_cast<int>(c[0] + 0.5f), g = static_cast<int>(c[1] + 0.5f), b = static_cast<int>(c[2] + 0.5f);
            const uint8_t idx = t.lut[(r >> 3) << 10 | (g >> 3) << 5 | (b >> 3)];
            out = idx;
            for (int i = 0; i < 3; ++i) {
                const float e = c[i] - t.rgb[idx][i];
                cur[(x + 2) * 3 + i] += e * 7 / 16;
                nxt[x * 3 + i] += e * 3 / 16;
                nxt[(x + 1) * 3 + i] += e * 5 / 16;
                nxt[(x + 2) * 3 + i] += e * 1 / 16;
            }
        }
        float* tmp = cur;
        cur = nxt;
        nxt = tmp;
        memset(nxt, 0, sizeof(float) * (dw + 2) * 3);
    }
}

} // namespace photo
