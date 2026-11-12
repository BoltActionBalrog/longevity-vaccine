#pragma once
// basehd_law.h -- the two laws basehd.cpp draws by, ported from work/scripts/scaling_laws.py
// (base_hd_sprite_size, palette_box_shrink). tests/test_basehd_law.py pins the port against the Python.

#include <cstdint>

namespace basehd_law {

// The colour range of art loaded with Buffer_load_pcx(name, 0, 10, 236) (load_faction_art's arguments): indices
// 10..245 are the art's colours; every other index is a key or special index (9 = the transparency key, 246.. the
// shadow / marker indices) and is never averaged.
constexpr int kColourLo = 10, kColourHi = 245;

// The on-screen size of a w x h sprite drawn at num/den: what Sprite_draw_dest gives the stock sprite --
// _ftol(w * (float)(num/den)), i.e. truncation. Integer floor here (no float rounding noise). num == den: w x h.
inline void SpriteSize(int w, int h, int num, int den, int* ow, int* oh)
{
    *ow = static_cast<int>(static_cast<long long>(w) * num / den);
    *oh = static_cast<int>(static_cast<long long>(h) * num / den);
}

// Shrink (or enlarge) an index image to dw x dh without leaving the palette. Each destination pixel covers the
// source footprint [x0, x1) x [y0, y1), x0 = tx*sw/dw, x1 = max((tx+1)*sw/dw, x0+1) (likewise y):
//   * the special index (outside kColourLo..kColourHi) met most often wins when it covers MORE pixels than all the
//     colour pixels together (ties go to the colours) -- the key stays the key, a shadow stays a shadow;
//   * else the colour index present in the footprint whose colour is nearest (squared RGB distance) to the mean
//     colour of the footprint's colour pixels; a tie goes to the index met first (row-major).
// rgbq: the RGBQUAD[256] (b,g,r,0) the art is shown with. Never blends, never invents an index. The former
// most-frequent-index rule picked dithering outliers in shaded areas (the dark specks the maintainer saw).
inline void PaletteBoxShrink(const uint8_t* src, int sw, int sh, int spitch, uint8_t* dst, int dw, int dh, int dpitch,
                             const uint8_t* rgbq)
{
    unsigned count[256] = {};
    uint8_t seen[256];
    for (int ty = 0; ty < dh; ++ty) {
        const int y0 = ty * sh / dh, y1 = (ty + 1) * sh / dh > y0 ? (ty + 1) * sh / dh : y0 + 1;
        for (int tx = 0; tx < dw; ++tx) {
            const int x0 = tx * sw / dw, x1 = (tx + 1) * sw / dw > x0 ? (tx + 1) * sw / dw : x0 + 1;
            int nseen = 0;
            for (int y = y0; y < y1; ++y) {
                const uint8_t* row = src + y * spitch;
                for (int x = x0; x < x1; ++x) if (count[row[x]]++ == 0) seen[nseen++] = row[x];
            }
            unsigned colourN = 0, specialN = 0;
            int special = -1;
            long long sum[3] = {};
            for (int i = 0; i < nseen; ++i) {
                const int v = seen[i];
                const unsigned c = count[v];
                if (v < kColourLo || v > kColourHi) {
                    if (c > specialN) { specialN = c; special = v; }
                } else {
                    colourN += c;
                    for (int ch = 0; ch < 3; ++ch) sum[ch] += static_cast<long long>(c) * rgbq[v * 4 + ch];
                }
            }
            int best = special;
            if (colourN > 0 && colourN >= specialN) {
                long long bestD = -1;
                for (int i = 0; i < nseen; ++i) {
                    const int v = seen[i];
                    if (v < kColourLo || v > kColourHi) continue;
                    long long d = 0;
                    for (int ch = 0; ch < 3; ++ch) {
                        const long long e = sum[ch] - static_cast<long long>(colourN) * rgbq[v * 4 + ch];
                        d += e * e;
                    }
                    if (bestD < 0 || d < bestD) { bestD = d; best = v; }
                }
            }
            for (int i = 0; i < nseen; ++i) count[seen[i]] = 0;
            dst[ty * dpitch + tx] = static_cast<uint8_t>(best);
        }
    }
}

} // namespace basehd_law
