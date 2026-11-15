#pragma once
// menuhd_law.h -- the HD main menu's laws, ported exactly from work/scripts/scaling_laws.py:
//   MenuLayout  <- menu_hd_layout (with the stock opening's 1024 x 768, the 404-wide planet strip and the 2400-wide
//                  panorama as its picture arguments)
//   MoonRect    <- menu_hd_moon_rect          Step <- menu_hd_step
//   Axis        <- menu_hd_axis               Resample <- menu_hd_resample
//   NearestLut  <- mon_nearest_lut
// tests/test_menuhd_law.py pins every one against the Python. Plain memory only: every allocation failure is a false
// return, never an exception; nothing here calls the engine.

#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace menuhd_law {

constexpr int kMenuW = 1024, kMenuH = 768, kStripW = 404, kPanoW = 2400, kMoonW = 450;
constexpr int kOne = 256;                           // MENU_HD_ONE: an axis' weights sum to this
constexpr int kKey = 9;                             // MENU_HD_KEY: the engine's transparency key (loaded)
constexpr int kMaxTaps = 16;                        // a shrink by up to 15x; MenuLayout's screens need at most ~6

struct Layout { int num, den, x0, y0, coreW, coreH, stripW, stripX; };

inline Layout MenuLayout(int w, int h)
{
    Layout l;
    if (static_cast<long long>(w) * kMenuH >= static_cast<long long>(h) * kMenuW) { l.num = h; l.den = kMenuH; }
    else { l.num = w; l.den = kMenuW; }
    l.coreH = static_cast<int>(static_cast<long long>(kMenuH) * l.num / l.den);
    const long long widest = static_cast<long long>(kPanoW + kStripW) * l.num / l.den;
    l.coreW = widest < w ? static_cast<int>(widest) : w;
    l.x0 = w - l.coreW;                             // past 2804:768 right-aligned: the menu bars stay on the planet
    l.y0 = h - l.coreH;
    l.stripW = static_cast<int>(static_cast<long long>(kStripW) * l.num / l.den);
    l.stripX = l.x0 + l.coreW - l.stripW;
    return l;
}

struct Rect { int x, y, w, h; };

inline Rect MoonRect(const Layout& l)
{
    const int s = static_cast<int>(static_cast<long long>(kMoonW) * l.num / l.den);
    return Rect{l.x0, l.y0, s, s};
}

// sn / sd source pixels per screen pixel for art drawn `art` x the native size at num / den.
inline void Step(int art, int num, int den, long long* sn, long long* sd) { *sn = static_cast<long long>(art) * den; *sd = num; }

// mon_phase_weights(): 64 phases x 6 Lanczos-3 taps, each row summing to 256 (generated from the law; pinned).
constexpr int kTaps = 6;
constexpr int16_t kLanczos[64][kTaps] = {
    {0, -2, 256, 2, 0, 0},
    {1, -5, 256, 5, -1, 0},
    {2, -8, 255, 9, -2, 0},
    {3, -11, 255, 12, -3, 0},
    {3, -13, 254, 16, -4, 0},
    {4, -16, 253, 20, -5, 0},
    {4, -18, 252, 24, -6, 0},
    {5, -21, 250, 29, -7, 0},
    {5, -23, 248, 33, -8, 1},
    {6, -25, 246, 38, -10, 1},
    {6, -27, 245, 42, -11, 1},
    {7, -28, 241, 47, -12, 1},
    {7, -30, 239, 52, -13, 1},
    {7, -31, 236, 57, -14, 1},
    {7, -32, 233, 62, -16, 2},
    {8, -34, 230, 67, -17, 2},
    {8, -35, 227, 72, -18, 2},
    {8, -35, 223, 77, -19, 2},
    {8, -36, 220, 83, -21, 2},
    {8, -37, 216, 88, -22, 3},
    {8, -37, 212, 93, -23, 3},
    {8, -38, 208, 99, -24, 3},
    {8, -38, 203, 104, -25, 4},
    {8, -38, 199, 110, -27, 4},
    {8, -38, 195, 115, -28, 4},
    {8, -38, 190, 121, -29, 4},
    {7, -38, 186, 126, -30, 5},
    {7, -37, 180, 132, -31, 5},
    {7, -37, 175, 138, -32, 5},
    {7, -36, 169, 143, -33, 6},
    {7, -36, 165, 148, -34, 6},
    {6, -35, 159, 154, -34, 6},
    {6, -34, 154, 159, -35, 6},
    {6, -34, 148, 165, -36, 7},
    {6, -33, 143, 169, -36, 7},
    {5, -32, 138, 175, -37, 7},
    {5, -31, 132, 180, -37, 7},
    {5, -30, 126, 186, -38, 7},
    {4, -29, 121, 190, -38, 8},
    {4, -28, 115, 195, -38, 8},
    {4, -27, 110, 199, -38, 8},
    {4, -25, 104, 203, -38, 8},
    {3, -24, 99, 208, -38, 8},
    {3, -23, 93, 212, -37, 8},
    {3, -22, 88, 216, -37, 8},
    {2, -21, 83, 220, -36, 8},
    {2, -19, 77, 223, -35, 8},
    {2, -18, 72, 227, -35, 8},
    {2, -17, 67, 230, -34, 8},
    {2, -16, 62, 233, -32, 7},
    {1, -14, 57, 236, -31, 7},
    {1, -13, 52, 239, -30, 7},
    {1, -12, 47, 241, -28, 7},
    {1, -11, 42, 245, -27, 6},
    {1, -10, 38, 246, -25, 6},
    {1, -8, 33, 248, -23, 5},
    {0, -7, 29, 250, -21, 5},
    {0, -6, 24, 252, -18, 4},
    {0, -5, 20, 253, -16, 4},
    {0, -4, 16, 254, -13, 3},
    {0, -3, 12, 255, -11, 3},
    {0, -2, 9, 255, -8, 2},
    {0, -1, 5, 256, -5, 1},
    {0, 0, 2, 256, -2, 0}
};

struct Tap { int k, w; };                           // source index (-1: outside the picture) and weight
struct AxisPx { int n; Tap t[kMaxTaps]; };

// menu_hd_axis for screen pixels 0..n_dst-1. False (nothing written) if a footprint needs more than kMaxTaps taps.
inline bool Axis(int nDst, long long sn, long long sd, int nSrc, AxisPx* out)
{
    if (nDst <= 0 || sn <= 0 || sd <= 0 || nSrc <= 0) return false;
    if (sn >= sd) {
        if ((sn + sd - 1) / sd + 1 > kMaxTaps) return false;
        for (int i = 0; i < nDst; ++i) {
            const long long a = i * sn, b = a + sn;
            AxisPx& p = out[i];
            p.n = 0;
            int sum = 0, big = 0;
            for (long long k = a / sd; k <= (b - 1) / sd; ++k) {
                const long long hi = b < (k + 1) * sd ? b : (k + 1) * sd, lo = a > k * sd ? a : k * sd;
                const int wt = static_cast<int>((2 * kOne * (hi - lo) + sn) / (2 * sn));
                p.t[p.n] = Tap{k < nSrc ? static_cast<int>(k) : -1, wt};
                if (wt > p.t[big].w) big = p.n;
                sum += wt;
                ++p.n;
            }
            p.t[big].w += kOne - sum;
        }
    } else {
        for (int i = 0; i < nDst; ++i) {
            const long long c64 = ((2LL * i + 1) * 32 * sn + 32 * sd) / sd - 64;
            const int ci = static_cast<int>(c64 >> 6), q = static_cast<int>(c64 & 63);
            AxisPx& p = out[i];
            p.n = kTaps;
            for (int t = 0; t < kTaps; ++t) {
                int k = ci - 2 + t;
                k = k < 0 ? 0 : k > nSrc - 1 ? nSrc - 1 : k;
                p.t[t] = Tap{k, kLanczos[q][t]};
            }
        }
    }
    return true;
}

// mon_nearest_lut(canvas, lo, hi): 15-bit RGB -> the nearest canvas index in lo..hi-1 (first wins ties, never 9).
inline void NearestLut(const uint8_t canvas[1024], int lo, int hi, uint8_t lut[32768])
{
    for (int i = 0; i < 32768; ++i) {
        const int r5 = i >> 10 & 31, g5 = i >> 5 & 31, b5 = i & 31;
        const int r = r5 << 3 | r5 >> 2, g = g5 << 3 | g5 >> 2, b = b5 << 3 | b5 >> 2;
        int best = lo, bd = 1 << 30;
        for (int k = lo; k < hi; ++k) {
            if (k == kKey) continue;
            const int db = canvas[k * 4] - b, dg = canvas[k * 4 + 1] - g, dr = canvas[k * 4 + 2] - r;
            const int d = dr * dr + dg * dg + db * db;
            if (d < bd) { bd = d; best = k; }
        }
        lut[i] = static_cast<uint8_t>(best);
    }
}

// A source row, sw indices, or null when it cannot be had (Resample then fails).
typedef const uint8_t* (*RowFn)(void* ctx, int row);

// menu_hd_resample: the source (sw x sh indices through row(ctx, r), colours pal = 768 RGB bytes, key = see-through
// index or -1) drawn dw x dh at sn / sd source pixels per screen pixel into dst (row pitch dp), canvas colours lo..hi-1
// of the RGBQUAD table `canvas`, with `lut` = NearestLut(canvas, lo, hi). False on no memory or a missing row; dst
// may then be partly written.
inline bool Resample(RowFn row, void* ctx, int sw, int sh, const uint8_t pal[768], int key, long long sn, long long sd,
                     int dw, int dh, uint8_t* dst, int dp, const uint8_t canvas[1024], int lo, int hi,
                     const uint8_t lut[32768])
{
    if (sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) return false;
    constexpr int kRing = kMaxTaps + 2;
    AxisPx* cols = static_cast<AxisPx*>(malloc(sizeof(AxisPx) * static_cast<size_t>(dw)));
    AxisPx* rows = static_cast<AxisPx*>(malloc(sizeof(AxisPx) * static_cast<size_t>(dh)));
    // 32-bit sums are exact: a horizontal sum is at most 396 x 255 per channel (256 x 255 for a shrink),
    // a vertical one at most 396 (the largest Lanczos row's absolute sum) times that -- under 2^26
    int32_t* ring = static_cast<int32_t*>(malloc(sizeof(int32_t) * 4 * static_cast<size_t>(dw) * kRing));
    int32_t* acc = static_cast<int32_t*>(malloc(sizeof(int32_t) * 4 * static_cast<size_t>(dw)));
    int* e0 = static_cast<int*>(calloc(static_cast<size_t>(dw + 2) * 3, sizeof(int)));
    int* e1 = static_cast<int*>(calloc(static_cast<size_t>(dw + 2) * 3, sizeof(int)));
    bool ok = cols && rows && ring && acc && e0 && e1 && Axis(dw, sn, sd, sw, cols) && Axis(dh, sn, sd, sh, rows);
    int ringRow[kRing];
    for (int& r : ringRow) r = -2;                    // -2 = empty (-1 is the OUTSIDE row)
    // the exact colours: canvas index per (r, g, b), the lowest index first (open addressing, 512 slots)
    uint32_t exKey[512];
    uint8_t exIdx[512];
    for (uint32_t& k : exKey) k = 0xFFFFFFFFu;
    for (int k = lo; ok && k < hi; ++k) {
        const uint32_t c = static_cast<uint32_t>(canvas[k * 4 + 2]) << 16 | canvas[k * 4 + 1] << 8 | canvas[k * 4];
        uint32_t s = (c * 2654435761u) >> 23;
        while (exKey[s] != 0xFFFFFFFFu && exKey[s] != c) s = (s + 1) & 511;
        if (exKey[s] == 0xFFFFFFFFu) { exKey[s] = c; exIdx[s] = static_cast<uint8_t>(k); }
    }
    const int32_t full = kOne * kOne;
    for (int j = 0; ok && j < dh; ++j) {
        memset(acc, 0, sizeof(int32_t) * 4 * static_cast<size_t>(dw));
        for (int t = 0; ok && t < rows[j].n; ++t) {
            const int r = rows[j].t[t].k;
            int slot = -1;
            for (int s = 0; s < kRing; ++s) if (ringRow[s] == r) slot = s;
            if (slot < 0) {                             // the horizontal pass of source row r
                slot = 0;
                for (int s = 1; s < kRing; ++s) if (ringRow[s] < ringRow[slot]) slot = s;   // rows come in order
                const uint8_t* src = r >= 0 ? row(ctx, r) : nullptr;
                if (r >= 0 && !src) { ok = false; break; }
                int32_t* h = ring + 4 * static_cast<size_t>(dw) * slot;
                for (int x = 0; x < dw; ++x) {
                    int32_t R = 0, G = 0, B = 0, A = 0;
                    for (int u = 0; u < cols[x].n; ++u) {
                        const int k = cols[x].t[u].k, wt = cols[x].t[u].w;
                        if (!src || k < 0) { if (key < 0) A += wt; continue; }
                        const int v = src[k];
                        if (v == key) continue;
                        R += wt * pal[v * 3];
                        G += wt * pal[v * 3 + 1];
                        B += wt * pal[v * 3 + 2];
                        A += wt;
                    }
                    h[x * 4] = R; h[x * 4 + 1] = G; h[x * 4 + 2] = B; h[x * 4 + 3] = A;
                }
                ringRow[slot] = r;
                // keep the ring's order meaningful: a row older than every tap of this screen row is the one to go
                // (rows[j] ascends, so the smallest index is the oldest)
            }
            const int32_t* h = ring + 4 * static_cast<size_t>(dw) * slot;
            const int wt = rows[j].t[t].w;
            for (int i = 0; i < 4 * dw; ++i) acc[i] += wt * h[i];
        }
        if (!ok) break;
        memset(e1, 0, sizeof(int) * static_cast<size_t>(dw + 2) * 3);
        uint8_t* line = dst + static_cast<size_t>(j) * dp;
        for (int i = 0; i < dw; ++i) {
            const int32_t A = acc[i * 4 + 3];
            if (key >= 0 && 2 * A < full) { line[i] = kKey; continue; }
            int v[3];
            for (int ch = 0; ch < 3; ++ch) {
                const int32_t C = acc[i * 4 + ch];
                // (C + A/2) / A; A is exactly 256 x 256 on every opaque pixel, where that is a shift
                int32_t c = C <= 0 || A <= 0 ? 0 : A == full ? (C + full / 2) >> 16 : (C + A / 2) / A;
                if (c > 255) c = 255;
                c += e0[(i + 1) * 3 + ch] >> 4;
                v[ch] = c < 0 ? 0 : c > 255 ? 255 : static_cast<int>(c);
            }
            const uint32_t c = static_cast<uint32_t>(v[0]) << 16 | v[1] << 8 | v[2];
            uint32_t s = (c * 2654435761u) >> 23;
            while (exKey[s] != 0xFFFFFFFFu && exKey[s] != c) s = (s + 1) & 511;
            const uint8_t idx = exKey[s] == c ? exIdx[s] : lut[(v[0] >> 3) << 10 | (v[1] >> 3) << 5 | (v[2] >> 3)];
            line[i] = idx;
            const int q[3] = {canvas[idx * 4 + 2], canvas[idx * 4 + 1], canvas[idx * 4]};
            for (int ch = 0; ch < 3; ++ch) {
                const int d = v[ch] - q[ch];
                e0[(i + 2) * 3 + ch] += d * 7;
                e1[i * 3 + ch] += d * 3;
                e1[(i + 1) * 3 + ch] += d * 5;
                e1[(i + 2) * 3 + ch] += d;
            }
        }
        int* t = e0; e0 = e1; e1 = t;
    }
    free(cols); free(rows); free(ring); free(acc); free(e0); free(e1);
    return ok;
}

} // namespace menuhd_law
