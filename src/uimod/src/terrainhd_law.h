// terrainhd_law.h -- the laws the HD terrain hook draws by, ported from work/scripts/scaling_laws.py (terrain_hd_*).
// tests/test_terrainhd_law.py pins the port against the Python. No Windows, no engine.
#pragma once
#include <cstdint>

namespace terrainhd {

constexpr int kTile = 56;                                // a stock terrain texture is 56 x 56 texels
constexpr int kMaster = 8;                               // the pack: TEXTURE.PCX at 8x (texture_x8.pcx)
constexpr int kStockSheetW = 1024, kStockSheetH = 768;   // TEXTURE.PCX
constexpr int kMaxLevel = 8;                             // the pack's own size (terrain_hd_level)

// scaling_laws.terrain_hd_uv_offset: c(k) = round((k - 1) / 4), measured on the engine's own Texture_draw_2.
inline int UvOffset(int k) { return (k - 1 + 2) / 4; }

// scaling_laws.terrain_hd_uv: a stock UV (0..55, the tables' and immediates' unit) at level k.
inline int Uv(int u, int k) { return k == 1 ? u : k * u + UvOffset(k); }

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
