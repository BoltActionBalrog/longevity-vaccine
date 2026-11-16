// terrainhd_law.h -- the laws the HD terrain hook draws by, ported from work/scripts/scaling_laws.py (terrain_hd_*).
// tests/test_terrainhd_law.py pins the port against the Python. No Windows, no engine.
#pragma once
#include <cstdint>

namespace terrainhd {

constexpr int kTile = 56;                                // a stock terrain texture is 56 x 56 texels
constexpr int kMaster = 8;                               // the pack: TEXTURE.PCX at 8x (texture_x8.pcx)
constexpr int kStockSheetW = 1024, kStockSheetH = 768;   // TEXTURE.PCX
constexpr int kMaxLevel = 8;                             // the pack's own size (terrain_hd_level)

// scaling_laws.terrain_hd_span: a span coordinate (16.16 texels: u, v, du, dv) at level k -- exactly k times the stock
// one, so it samples the k x k block of the stock texel stock samples. The span stubs do it with a shift (k = 2^s).
inline int32_t Span(int32_t c, int k) { return c * k; }

// scaling_laws.terrain_hd_max_zoom: PRACX's deepest zoom for a w x h screen (ZoomInit's iZoomFactorMax loop).
inline int MaxZoom(int w, int h)
{
    const int mh = h - 213;
    int z = 0;
    for (;;) {
        z += 2;
        const int i = (50 * (z + 16) / 16 + 1) / 4;
        const int px = i * 8 > 1 ? i * 8 : 1, py = i * 4 > 1 ? i * 4 : 1;
        if (!(w / px > 6 && mh / py > 3) || z >= 400) return z;
    }
}

// scaling_laws.terrain_hd_tile_px: a map tile's width in pixels at zoom z (8i, ZoomFactorToPt).
inline int TilePx(int z) { return 8 * ((50 * (z + 16) / 16 + 1) / 4); }

// scaling_laws.terrain_hd_level: the one level the session draws at -- the smallest k in {2, 4, 8} that keeps a texel
// per pixel across a tile at the screen's deepest zoom (2 (55k)^2 >= tile_px^2), capped at kMaxLevel.
inline int Level(int w, int h)
{
    const int t = TilePx(MaxZoom(w, h));
    for (int k = 2; k < kMaxLevel; k *= 2)
        if (2 * (55 * k) * (55 * k) >= t * t) return k;
    return kMaxLevel;
}

// scaling_laws.terrain_hd_code: a RAINFALL code map (the coast composites, the territory border) at level k from the
// pack's 8x region of RAINFALL.PCX (file indices, row stride pitch): each texel samples the centre of its 8/k block and
// takes the engine's rule -- the index of its colour in cols, bg for the see-through 255, 0 for any other colour.
inline void Code(const uint8_t* x8, int pitch, int n, const uint8_t* cols, int ncols, uint8_t bg, int k, uint8_t* out)
{
    const int s = kMaster / k, m = n * k;
    for (int y = 0; y < m; ++y)
        for (int x = 0; x < m; ++x) {
            const uint8_t v = x8[(y * s + s / 2) * pitch + x * s + s / 2];
            uint8_t c = 0;
            if (v == 255) c = bg;
            else
                for (int i = 0; i < ncols; ++i)
                    if (cols[i] == v) { c = static_cast<uint8_t>(i); break; }
            out[y * m + x] = c;
        }
}

// scaling_laws.terrain_hd_nearest: an n x n index image at k x (each texel a k x k block).
inline void Nearest(const uint8_t* src, int n, int k, uint8_t* dst)
{
    const int m = n * k;
    for (int y = 0; y < m; ++y) {
        const uint8_t* s = src + (y / k) * n;
        uint8_t* d = dst + y * m;
        for (int x = 0; x < m; ++x) d[x] = s[x / k];
    }
}

} // namespace terrainhd
