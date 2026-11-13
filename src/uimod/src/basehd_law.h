#pragma once
// basehd_law.h -- the two laws the HD sprite hooks draw by, ported from work/scripts/scaling_laws.py
// (base_hd_cell_size, palette_box_shrink). tests/test_basehd_law.py pins the port against the Python.

#include <cstdint>

namespace basehd_law {

// The colour range of art loaded with Buffer_load_pcx(name, 0, 10, 236) (the faction and terrain loaders' arguments:
// loaded index = file index + 10 mod 256): indices 10..245 are the art's colours; every other index is a key or
// special index (9 = the transparency key, file 255; 0 = file 246, the shadow / black-ink index; 1..8 and 246..255
// the other markers) and is never averaged.
constexpr int kColourLo = 10, kColourHi = 245;

// The engine's ratio float: fild num; fidiv den; fstp dword (scaling_laws.engine_scale_f).
inline float EngineScale(int num, int den) { return static_cast<float>(static_cast<double>(num) / den); }

// The size an HD copy of a w x h cell is made at for SCALE_NUM_G / SCALE_DEN_G = num / den: the size the engine's
// scaled draw gives the stock CELL, _ftol(w * f) x _ftol(h * f) with f the engine's float32 ratio. num == den: w x h.
// The engine trims each stock sprite to its content box and truncates that box's size and offsets separately, so the
// HD sprite drawn from this cell lands within about a pixel of the stock one, not always on it.
inline void CellSize(int w, int h, int num, int den, int* ow, int* oh)
{
    const double f = EngineScale(num, den);
    *ow = static_cast<int>(w * f);
    *oh = static_cast<int>(h * f);
}

// Shrink (or enlarge) an index image to dw x dh without leaving the palette. Each destination pixel covers the
// source footprint [x0, x1) x [y0, y1), x0 = tx*sw/dw, x1 = max((tx+1)*sw/dw, x0+1) (likewise y):
//   * when the special pixels (outside kColourLo..kColourHi) together outnumber the colour pixels, the special index
//     met most often wins (ties to the one met first) -- the key stays the key, a shadow stays a shadow;
//   * else (ties go to the colours) the colour index present in the footprint whose colour is nearest (squared RGB
//     distance) to the mean colour of the footprint's colour pixels; a tie goes to the index met first (row-major).
// rgbq: the RGBQUAD[256] (b,g,r,0) the art is shown with. Never blends, never invents an index.
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
            unsigned colourN = 0, specialN = 0, specialTotal = 0;
            int special = -1;
            long long sum[3] = {};
            for (int i = 0; i < nseen; ++i) {
                const int v = seen[i];
                const unsigned c = count[v];
                if (v < kColourLo || v > kColourHi) {
                    specialTotal += c;
                    if (c > specialN) { specialN = c; special = v; }
                } else {
                    colourN += c;
                    for (int ch = 0; ch < 3; ++ch) sum[ch] += static_cast<long long>(c) * rgbq[v * 4 + ch];
                }
            }
            int best = special;
            if (colourN > 0 && colourN >= specialTotal) {
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
