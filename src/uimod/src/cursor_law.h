#pragma once
// cursor_law.h -- the map-cursor enlargement, a bit-for-bit port of scaling_laws.cursor_* (the source of truth):
// the 32x32 CURSOR.PCX cell enlarged by output-driven, centre-sampled, edge-clamped NN (nn_center_index) to
// CanvasPx(g) = scale_px(32, g); the trimmed content rect and the hotspot follow the same map.  Header-only and
// engine-free, so work\tests\cursor_selftest.cpp compiles it on the host (test_cursor_port.py).
#include <cstdint>
#include <vector>

namespace cursor_law {

constexpr int kNativeG = 16;
constexpr int kCell = 32;

// scaling_laws.half_down(a, b): a / b rounded to nearest, halves DOWN (a, b > 0 here)
inline int HalfDown(int a, int b) { return (2 * a + b - 1) / (2 * b); }
inline int ScalePx(int v, int g) { return HalfDown(v * g, kNativeG); }

// scaling_laws.nn_center_index
inline int NnCenterIndex(int d, int dst, int src)
{
    if (dst <= 0 || src <= 0) return 0;
    int i = ((2 * d + 1) * src) / (2 * dst);
    if (i < 0) i = 0;
    if (i > src - 1) i = src - 1;
    return i;
}

inline int CanvasPx(int g) { return g <= kNativeG ? kCell : ScalePx(kCell, g); }

// scaling_laws.cursor_nn_run: the dest run [*a, *b] of native index c in the 32-cell at g (> 16)
inline void NnRun(int c, int g, int* a, int* b)
{
    const int s = CanvasPx(g);
    *a = -1; *b = -1;
    for (int d = 0; d < s; ++d)
        if (NnCenterIndex(d, s, kCell) == c) { if (*a < 0) *a = d; *b = d; }
}

inline int Hotspot(int h, int g)
{
    if (g <= kNativeG) return h;
    int a, b; NnRun(h, g, &a, &b);
    return a < 0 ? h : (a + b) / 2;
}

struct Rect { int left, top, w, h; };

inline Rect ContentRect(Rect r, int g)
{
    if (g <= kNativeG || r.w <= 0 || r.h <= 0) return r;
    int l0, l1, r0, r1, t0, t1, b0, b1;
    NnRun(r.left, g, &l0, &l1); NnRun(r.left + r.w - 1, g, &r0, &r1);
    NnRun(r.top, g, &t0, &t1); NnRun(r.top + r.h - 1, g, &b0, &b1);
    return { l0, t0, r1 - l0 + 1, b1 - t0 + 1 };
}

// Enlarge a trimmed native content block (pitch >= r.w, top-left at cell (r.left, r.top)) to the content rect of
// the enlarged cell.  Returns that rect; out = its pixels, row-major, pitch = rect.w.  Every dest pixel reads the
// native cell pixel nn_center_index picks, which lies inside the native content rect by construction.
inline Rect Enlarge(const uint8_t* src, int pitch, Rect r, int g, std::vector<uint8_t>* out)
{
    const Rect d = ContentRect(r, g);
    const int s = CanvasPx(g);
    out->assign(static_cast<size_t>(d.w > 0 ? d.w : 0) * static_cast<size_t>(d.h > 0 ? d.h : 0), 0);
    for (int y = 0; y < d.h; ++y) {
        int sy = NnCenterIndex(d.top + y, s, kCell) - r.top;
        if (sy < 0) sy = 0;
        if (sy > r.h - 1) sy = r.h - 1;
        for (int x = 0; x < d.w; ++x) {
            int sx = NnCenterIndex(d.left + x, s, kCell) - r.left;
            if (sx < 0) sx = 0;
            if (sx > r.w - 1) sx = r.w - 1;
            (*out)[static_cast<size_t>(y) * d.w + x] = src[static_cast<size_t>(sy) * pitch + sx];
        }
    }
    return d;
}

} // namespace cursor_law
