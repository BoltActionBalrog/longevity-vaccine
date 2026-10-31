// Leader-portrait composite enlarge -- a PORT of work\scripts\scaling_laws.py `portrait_enlarge`
// (the source of truth; tests\test_portrait_port.py runs this header against it, bit for bit).
// Pure C++: no Windows, no engine types, so the self-test harness can compile it alone.
//
// De-scanline -> Lanczos-3 (Q14 taps) -> light unsharp -> scanlines back at DEVICE density -> serpentine
// Floyd-Steinberg into palette indices 10..245.  Frame rows/cols = the edge-pinned NN of art_reblit.
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace portrait_law {

constexpr int kPalLo = 10, kPalHi = 245;
constexpr int kLanczosA = 3;
constexpr int kWeightQ = 14;
constexpr int kSharpenQ8 = 154;
constexpr int kSharpenThreshold = 2;
constexpr int kDitherQ8 = 218;
constexpr int kDistR = 2, kDistG = 4, kDistB = 3;
constexpr int kSkip = -1;                       // "leave the dest pixel alone" (key)
constexpr int kMinW = 32;                       // = scaling_laws.PORTRAIT_MIN_W: leader art only (>= 96 wide), never a bar / icon

// = scaling_laws.portrait_ring_opaque: no key texel on the outer ring except its 4 corners (a SHAPED sprite -- the
// Spartans' council logo -- is not a portrait: the enlarge would write its keyed surround opaque)
inline bool RingOpaque(const uint8_t* src, int sPitch, int sw, int sh, int key)
{
    for (int x = 1; x < sw - 1; ++x)
        if (src[x] == key || src[(sh - 1) * sPitch + x] == key) return false;
    for (int y = 1; y < sh - 1; ++y)
        if (src[y * sPitch] == key || src[y * sPitch + sw - 1] == key) return false;
    return true;
}

inline bool Applies(const uint8_t* src, int sPitch, int sw, int sh, int key, int num, int den)
{
    return num > den && den > 0 && sh > sw && sw >= kMinW && key >= 0 && key <= 0xFF &&
           RingOpaque(src, sPitch, sw, sh, key);
}

inline int NnCenterIndex(int d, int dst, int src)
{
    if (dst <= 0 || src <= 0) return 0;
    int v = ((2 * d + 1) * src) / (2 * dst);
    return v < 0 ? 0 : v > src - 1 ? src - 1 : v;
}

inline int Clamp8(int v) { return v < 0 ? 0 : v > 255 ? 255 : v; }

struct Taps { int lo; std::vector<int> q; };

inline std::vector<Taps> MakeTaps(int nIn, int nOut)
{
    const double kPi = 3.141592653589793;       // == Python's math.pi
    const double scale = static_cast<double>(nIn) / static_cast<double>(nOut);
    const double fs = scale > 1.0 ? scale : 1.0;
    const double support = kLanczosA * fs;
    std::vector<Taps> out(static_cast<size_t>(nOut));
    for (int o = 0; o < nOut; ++o) {
        const double c = (o + 0.5) * scale;
        int lo = static_cast<int>(std::floor(c - support));
        if (lo < 0) lo = 0;
        int hi = static_cast<int>(std::ceil(c + support));
        if (hi > nIn) hi = nIn;
        std::vector<double> ws;
        double tot = 0.0;
        for (int i = lo; i < hi; ++i) {
            const double x = (i + 0.5 - c) / fs;
            double w;
            if (x == 0.0) w = 1.0;
            else if (std::fabs(x) >= kLanczosA) w = 0.0;
            else {
                const double px = kPi * x;
                w = kLanczosA * std::sin(px) * std::sin(px / kLanczosA) / (px * px);
            }
            ws.push_back(w);
            tot += w;
        }
        Taps& t = out[static_cast<size_t>(o)];
        t.lo = lo;
        int sum = 0, best = 0;
        for (size_t k = 0; k < ws.size(); ++k) {
            const int q = static_cast<int>(std::floor(ws[k] / tot * (1 << kWeightQ) + 0.5));
            t.q.push_back(q);
            sum += q;
            if (q > t.q[static_cast<size_t>(best)]) best = static_cast<int>(k);   // FIRST largest, as Python's max()
        }
        t.q[static_cast<size_t>(best)] += (1 << kWeightQ) - sum;
    }
    return out;
}

inline int ScanRows(int num, int den);           // the chrome's scanline thickness (FieldEnlarge section)
inline int ScanPhase(int y0, int num, int den);  // the dest buffer's stripe-grid phase of a picture at row y0

// Python floor division (a // b) for b > 0, so a negative interior row keeps its field.
inline int FloorDiv(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

// src: palette indices, row pitch sPitch.  pal: RGBQUAD[256] (b,g,r,x).  out: dw*dh ints, kSkip = leave alone.
// Returns false when the law does not apply (the caller falls back to the scanline re-blit).
inline bool Enlarge(const uint8_t* src, int sPitch, int sw, int sh, int key, const uint8_t* pal, int num, int den,
                    int* outW, int* outH, std::vector<int>* out, int y0 = 0)
{
    if (!Applies(src, sPitch, sw, sh, key, num, den)) return false;
    const int dw = (sw * num) / den, dh = (sh * num) / den;
    std::vector<int> crow(static_cast<size_t>(dh)), ccol(static_cast<size_t>(dw));
    for (int j = 0; j < dh; ++j) crow[static_cast<size_t>(j)] = NnCenterIndex(j, dh, sh);
    for (int i = 0; i < dw; ++i) ccol[static_cast<size_t>(i)] = NnCenterIndex(i, dw, sw);
    int jt = 0, jb = dh, il = 0, ir = dw;
    while (jt < dh && crow[static_cast<size_t>(jt)] <= 0) ++jt;
    while (jb > 0 && crow[static_cast<size_t>(jb - 1)] >= sh - 1) --jb;
    while (il < dw && ccol[static_cast<size_t>(il)] <= 0) ++il;
    while (ir > 0 && ccol[static_cast<size_t>(ir - 1)] >= sw - 1) --ir;
    const int W0 = sw - 2, H0 = sh - 2, W1 = ir - il, H1 = jb - jt;
    if (W1 <= 0 || H1 <= 0 || W0 <= 0 || H0 <= 0) return false;

    auto at = [](std::vector<int>& v, int w, int x, int y) -> int* { return &v[(static_cast<size_t>(y) * w + x) * 3]; };

    // photo (r,g,b ints)
    std::vector<int> photo(static_cast<size_t>(W0) * H0 * 3);
    for (int y = 0; y < H0; ++y)
        for (int x = 0; x < W0; ++x) {
            const int idx = src[(y + 1) * sPitch + x + 1];
            int* p = at(photo, W0, x, y);
            p[0] = pal[idx * 4 + 2]; p[1] = pal[idx * 4 + 1]; p[2] = pal[idx * 4];
        }
    // 1. bright field + dark:bright ratio (Q8)
    long long ev = 0, od = 0;
    for (int y = 0; y < H0; ++y) {
        long long s = 0;
        for (int x = 0; x < W0; ++x) { const int* p = at(photo, W0, x, y); s += 77 * p[0] + 150 * p[1] + 29 * p[2]; }
        ((y & 1) ? od : ev) += s;
    }
    const long long nEv = (H0 + 1) / 2, nOd = H0 / 2;
    const int bright = (ev * nOd >= od * nEv) ? 0 : 1;
    const long long bSum = bright == 0 ? ev : od, bN = bright == 0 ? nEv : nOd;
    const long long dSum = bright == 0 ? od : ev, dN = bright == 0 ? nOd : nEv;
    long long den2 = bSum * dN; if (den2 < 1) den2 = 1;
    long long rq = (dSum * bN * 256) / den2; if (rq > 256) rq = 256;
    const int ratioQ8 = static_cast<int>(rq);
    // 2. de-scanline: the overlay only darkens alternate rows; their own detail is gained back up by 256/ratio
    //    (never rebuilt from the neighbours: that smears one-row accents -- pupils, nostrils -- into blotches)
    if (ratioQ8 > 0)
        for (int y = 0; y < H0; ++y) {
            if ((y & 1) == bright) continue;
            for (int x = 0; x < W0; ++x) {
                int* p = at(photo, W0, x, y);
                for (int c = 0; c < 3; ++c) p[c] = Clamp8((p[c] * 256 + (ratioQ8 >> 1)) / ratioQ8);
            }
        }
    // 3. Lanczos-3, horizontal then vertical
    const int half = 1 << (kWeightQ - 1);
    const std::vector<Taps> tx = MakeTaps(W0, W1), ty = MakeTaps(H0, H1);
    std::vector<int> hor(static_cast<size_t>(W1) * H0 * 3), big(static_cast<size_t>(W1) * H1 * 3);
    for (int y = 0; y < H0; ++y)
        for (int x = 0; x < W1; ++x) {
            const Taps& t = tx[static_cast<size_t>(x)];
            for (int c = 0; c < 3; ++c) {
                long long s = 0;
                for (size_t k = 0; k < t.q.size(); ++k) s += static_cast<long long>(t.q[k]) * at(photo, W0, t.lo + static_cast<int>(k), y)[c];
                at(hor, W1, x, y)[c] = Clamp8(static_cast<int>((s + half) >> kWeightQ));
            }
        }
    for (int y = 0; y < H1; ++y) {
        const Taps& t = ty[static_cast<size_t>(y)];
        for (int x = 0; x < W1; ++x)
            for (int c = 0; c < 3; ++c) {
                long long s = 0;
                for (size_t k = 0; k < t.q.size(); ++k) s += static_cast<long long>(t.q[k]) * at(hor, W1, x, t.lo + static_cast<int>(k))[c];
                at(big, W1, x, y)[c] = Clamp8(static_cast<int>((s + half) >> kWeightQ));
            }
    }
    // 4. light unsharp (3x3 binomial, edge-clamped)
    std::vector<int> tmp(big.size()), bl(big.size()), shp(big.size());
    for (int y = 0; y < H1; ++y)
        for (int x = 0; x < W1; ++x)
            for (int c = 0; c < 3; ++c) {
                const int xa = x > 0 ? x - 1 : 0, xb = x < W1 - 1 ? x + 1 : W1 - 1;
                at(tmp, W1, x, y)[c] = (at(big, W1, xa, y)[c] + 2 * at(big, W1, x, y)[c] + at(big, W1, xb, y)[c] + 2) >> 2;
            }
    for (int y = 0; y < H1; ++y)
        for (int x = 0; x < W1; ++x)
            for (int c = 0; c < 3; ++c) {
                const int ya = y > 0 ? y - 1 : 0, yb = y < H1 - 1 ? y + 1 : H1 - 1;
                at(bl, W1, x, y)[c] = (at(tmp, W1, x, ya)[c] + 2 * at(tmp, W1, x, y)[c] + at(tmp, W1, x, yb)[c] + 2) >> 2;
            }
    for (size_t k = 0; k < big.size(); ++k) {
        const int d = big[k] - bl[k];
        shp[k] = (std::abs(d) >= kSharpenThreshold) ? Clamp8(big[k] + ((d * kSharpenQ8) >> 8)) : big[k];
    }
    // 5. scanlines as thick as the chrome's (ScanRows), on the DEST BUFFER's stripe grid (ScanPhase: interior row y
    //    is grid row y + phase; the picture's stripes continue the panel's)
    const int scanT = ScanRows(num, den), phase = ScanPhase(y0 + jt, num, den);
    for (int y = 0; y < H1; ++y) {
        if ((((y + phase) / scanT) & 1) == bright) continue;
        for (int x = 0; x < W1; ++x)
            for (int c = 0; c < 3; ++c) at(shp, W1, x, y)[c] = (at(shp, W1, x, y)[c] * ratioQ8) >> 8;
    }
    // 6. serpentine Floyd-Steinberg
    std::vector<int> fit(static_cast<size_t>(W1) * H1);
    for (int y = 0; y < H1; ++y) {
        const int dx = (y & 1) == 0 ? 1 : -1;
        for (int n = 0; n < W1; ++n) {
            const int x = dx == 1 ? n : W1 - 1 - n;
            int* a = at(shp, W1, x, y);
            const int r = Clamp8(a[0]), g = Clamp8(a[1]), b = Clamp8(a[2]);
            int best = kPalLo; long long bd = -1; int pr = 0, pg = 0, pb = 0;
            for (int ci = kPalLo; ci <= kPalHi; ++ci) {
                const int cr = pal[ci * 4 + 2], cg = pal[ci * 4 + 1], cb = pal[ci * 4];
                const long long d = static_cast<long long>(kDistR) * (cr - r) * (cr - r) +
                                    static_cast<long long>(kDistG) * (cg - g) * (cg - g) +
                                    static_cast<long long>(kDistB) * (cb - b) * (cb - b);
                if (bd < 0 || d < bd) { bd = d; best = ci; pr = cr; pg = cg; pb = cb; }
            }
            fit[static_cast<size_t>(y) * W1 + x] = best;
            const int err[3] = { ((r - pr) * kDitherQ8) >> 8, ((g - pg) * kDitherQ8) >> 8, ((b - pb) * kDitherQ8) >> 8 };
            const int ox[4] = { dx, -dx, 0, dx }, oy[4] = { 0, 1, 1, 1 }, kk[4] = { 7, 3, 5, 1 };
            for (int m = 0; m < 4; ++m) {
                const int xx = x + ox[m], yy = y + oy[m];
                if (xx < 0 || xx >= W1 || yy >= H1) continue;
                int* t = at(shp, W1, xx, yy);
                for (int c = 0; c < 3; ++c) t[c] += (err[c] * kk[m]) >> 4;
            }
        }
    }
    // 7. assemble
    out->assign(static_cast<size_t>(dw) * dh, kSkip);
    for (int j = 0; j < dh; ++j)
        for (int i = 0; i < dw; ++i) {
            int v;
            if (j >= jt && j < jb && i >= il && i < ir) v = fit[static_cast<size_t>(j - jt) * W1 + (i - il)];
            else {
                v = src[crow[static_cast<size_t>(j)] * sPitch + ccol[static_cast<size_t>(i)]];
                if (v == key) v = kSkip;
            }
            (*out)[static_cast<size_t>(j) * dw + i] = v;
        }
    *outW = dw; *outH = dh;
    return true;
}

// ---- popup event pictures: field-separated smooth enlarge -- a PORT of scaling_laws.py art_field_enlarge
//      (tests\test_art_field_port.py, bit for bit).  No scanline model: the two scanline fields are enlarged
//      separately and re-interleaved at device density; a texel whose smooth colour equals the texel the parity
//      re-blit would draw keeps that texel's index, the rest is error-diffused inside its own field.  Each
//      Lanczos sample is clamped into the range of its two bracketing source samples (no overshoot halo).
//      Scanlines are EVEN, ScanRows(num, den) device rows thick (1 below 22/16, 2 up to x3; never an uneven duty),
//      on the DEST BUFFER's stripe grid: interior device row y shows field ScanField(y + ScanPhase(y0 + jt))
//      (option B stage 2, 2026-10-06; before, the first stripe was the picture's first interior row's).

constexpr int kFieldMin = 32;                   // = scaling_laws.ART_FIELD_MIN

// = scaling_laws.art_scan_rows / art_scan_field / art_scan_next / art_scan_ordinal (y = interior device row)
inline int ScanRows(int num, int den) { if (num * 16 < 22 * den) return 1; const int t = num / den; return t < 2 ? 2 : t; }
inline int ScanField(int y, int num, int den) { return (y / ScanRows(num, den)) & 1; }
inline int ScanNext(int y, int num, int den) { const int t = ScanRows(num, den); return (y + 1) % t ? y + 1 : y + t + 1; }
inline int ScanOrdinal(int y, int num, int den) { const int t = ScanRows(num, den); return (y / (2 * t)) * t + y % t; }
// scaling_laws.art_scan_phase: y0 mod 2T, never negative (a replaced portrait may be clipped above the buffer)
inline int ScanPhase(int y0, int num, int den) { const int p = 2 * ScanRows(num, den); const int m = y0 % p; return m < 0 ? m + p : m; }

inline bool FieldApplies(const uint8_t* src, int sPitch, int sw, int sh, int key, int num, int den)
{
    if (!(num > den && den > 0 && sw >= kFieldMin && sh >= kFieldMin)) return false;
    if (key >= 0 && key <= 0xFF)
        for (int y = 1; y < sh - 1; ++y)
            for (int x = 1; x < sw - 1; ++x)
                if (src[y * sPitch + x] == key) return false;
    return true;
}

inline int ClampIdx(int v, int n) { return v < 0 ? 0 : v > n - 1 ? n - 1 : v; }

// v clamped into [min(a, b), max(a, b)]
inline int Hull(int v, int a, int b)
{
    const int lo = a < b ? a : b, hi = a < b ? b : a;
    return v < lo ? lo : v > hi ? hi : v;
}

// centres: the device rows' centres in interior source rows; field row m is interior row 2m + k.
// bracket: per row, the two field rows that bracket the centre (edge-clamped), then the nearest one.
inline std::vector<Taps> MakeFieldTaps(int nField, int k, const std::vector<double>& centres, std::vector<int>* bracket)
{
    const double kPi = 3.141592653589793;
    std::vector<Taps> out(centres.size());
    bracket->assign(centres.size() * 3, 0);
    for (size_t o = 0; o < centres.size(); ++o) {
        const double cf = (centres[o] - k - 0.5) / 2.0;
        int lo = static_cast<int>(std::floor(cf - kLanczosA));
        if (lo < 0) lo = 0;
        int hi = static_cast<int>(std::ceil(cf + kLanczosA)) + 1;
        if (hi > nField) hi = nField;
        std::vector<double> ws;
        double tot = 0.0;
        for (int i = lo; i < hi; ++i) {
            const double x = i - cf;
            double w;
            if (x == 0.0) w = 1.0;
            else if (std::fabs(x) >= kLanczosA) w = 0.0;
            else {
                const double px = kPi * x;
                w = kLanczosA * std::sin(px) * std::sin(px / kLanczosA) / (px * px);
            }
            ws.push_back(w);
            tot += w;
        }
        Taps& t = out[o];
        t.lo = lo;
        int sum = 0, best = 0;
        for (size_t n = 0; n < ws.size(); ++n) {
            const int q = static_cast<int>(std::floor(ws[n] / tot * (1 << kWeightQ) + 0.5));
            t.q.push_back(q);
            sum += q;
            if (q > t.q[static_cast<size_t>(best)]) best = static_cast<int>(n);
        }
        t.q[static_cast<size_t>(best)] += (1 << kWeightQ) - sum;
        const int m0 = static_cast<int>(std::floor(cf));
        (*bracket)[o * 3] = ClampIdx(m0, nField);
        (*bracket)[o * 3 + 1] = ClampIdx(m0 + 1, nField);
        (*bracket)[o * 3 + 2] = ClampIdx(static_cast<int>(std::floor(cf + 0.5)), nField);
    }
    return out;
}

// Same contract as Enlarge.  False when the law does not apply (the caller falls back to the parity re-blit).
inline bool FieldEnlarge(const uint8_t* src, int sPitch, int sw, int sh, int key, const uint8_t* pal, int num, int den,
                         int* outW, int* outH, std::vector<int>* out, int y0 = 0)
{
    if (!FieldApplies(src, sPitch, sw, sh, key, num, den)) return false;
    const int dw = (sw * num) / den, dh = (sh * num) / den;
    std::vector<int> crow(static_cast<size_t>(dh)), ccol(static_cast<size_t>(dw));
    for (int j = 0; j < dh; ++j) crow[static_cast<size_t>(j)] = NnCenterIndex(j, dh, sh);
    for (int i = 0; i < dw; ++i) ccol[static_cast<size_t>(i)] = NnCenterIndex(i, dw, sw);
    int jt = 0, jb = dh, il = 0, ir = dw;
    while (jt < dh && crow[static_cast<size_t>(jt)] <= 0) ++jt;
    while (jb > 0 && crow[static_cast<size_t>(jb - 1)] >= sh - 1) --jb;
    while (il < dw && ccol[static_cast<size_t>(il)] <= 0) ++il;
    while (ir > 0 && ccol[static_cast<size_t>(ir - 1)] >= sw - 1) --ir;
    const int W0 = sw - 2, H0 = sh - 2, W1 = ir - il, H1 = jb - jt;
    if (W1 <= 0 || H1 <= 0) return false;
    const int phase = ScanPhase(y0 + jt, num, den);   // interior row y is dest-buffer grid row y + phase

    const int half = 1 << (kWeightQ - 1);
    const std::vector<Taps> tx = MakeTaps(W0, W1);
    std::vector<int> hor(static_cast<size_t>(W1) * H0 * 3), big(static_cast<size_t>(W1) * H1 * 3);
    std::vector<int> bx(static_cast<size_t>(W1) * 2);
    const double scale = static_cast<double>(W0) / static_cast<double>(W1);
    for (int o = 0; o < W1; ++o) {
        const int i0 = static_cast<int>(std::floor((o + 0.5) * scale - 0.5));
        bx[static_cast<size_t>(o) * 2] = ClampIdx(i0, W0);
        bx[static_cast<size_t>(o) * 2 + 1] = ClampIdx(i0 + 1, W0);
    }
    for (int y = 0; y < H0; ++y) {
        const uint8_t* row = src + static_cast<size_t>(y + 1) * sPitch + 1;
        for (int x = 0; x < W1; ++x) {
            const Taps& t = tx[static_cast<size_t>(x)];
            const uint8_t* pa = pal + row[bx[static_cast<size_t>(x) * 2]] * 4;
            const uint8_t* pb = pal + row[bx[static_cast<size_t>(x) * 2 + 1]] * 4;
            long long s[3] = { 0, 0, 0 };
            for (size_t n = 0; n < t.q.size(); ++n) {
                const uint8_t* p = pal + row[t.lo + static_cast<int>(n)] * 4;
                s[0] += static_cast<long long>(t.q[n]) * p[2];
                s[1] += static_cast<long long>(t.q[n]) * p[1];
                s[2] += static_cast<long long>(t.q[n]) * p[0];
            }
            int* h = &hor[(static_cast<size_t>(y) * W1 + x) * 3];
            for (int c = 0; c < 3; ++c)
                h[c] = Hull(Clamp8(static_cast<int>((s[c] + half) >> kWeightQ)), pa[2 - c], pb[2 - c]);
        }
    }
    std::vector<int> nearRow(static_cast<size_t>(H1));     // per interior device row: nearest source row of its field
    for (int k = 0; k < 2; ++k) {
        std::vector<int> ys;
        std::vector<double> centres;
        for (int y = 0; y < H1; ++y)
            if (ScanField(y + phase, num, den) == k) {
                ys.push_back(y);
                centres.push_back((y + 0.5) * static_cast<double>(H0) / static_cast<double>(H1));
            }
        std::vector<int> by;
        const std::vector<Taps> ty = MakeFieldTaps((H0 - k + 1) / 2, k, centres, &by);
        for (size_t o = 0; o < ys.size(); ++o) {
            const Taps& t = ty[o];
            const int* ha = &hor[static_cast<size_t>(2 * by[o * 3] + k) * W1 * 3];
            const int* hb = &hor[static_cast<size_t>(2 * by[o * 3 + 1] + k) * W1 * 3];
            nearRow[static_cast<size_t>(ys[o])] = 2 * by[o * 3 + 2] + k + 1;
            for (int x = 0; x < W1; ++x)
                for (int c = 0; c < 3; ++c) {
                    long long s = 0;
                    for (size_t n = 0; n < t.q.size(); ++n)
                        s += static_cast<long long>(t.q[n]) *
                             hor[(static_cast<size_t>(2 * (t.lo + static_cast<int>(n)) + k) * W1 + x) * 3 + c];
                    big[(static_cast<size_t>(ys[o]) * W1 + x) * 3 + c] =
                        Hull(Clamp8(static_cast<int>((s + half) >> kWeightQ)), ha[x * 3 + c], hb[x * 3 + c]);
                }
        }
    }
    std::vector<int> cands;                         // 10..245, then the other indices the interior itself uses
    for (int ci = kPalLo; ci <= kPalHi; ++ci) cands.push_back(ci);
    {
        bool used[256] = {};
        for (int y = 1; y < sh - 1; ++y)
            for (int x = 1; x < sw - 1; ++x) used[src[y * sPitch + x]] = true;
        for (int ci = 0; ci < 256; ++ci)
            if (used[ci] && (ci < kPalLo || ci > kPalHi) && ci != key) cands.push_back(ci);
    }
    std::vector<int> err(big.size(), 0), fit(static_cast<size_t>(W1) * H1);
    std::vector<int> scol(static_cast<size_t>(W1));
    for (int x = 0; x < W1; ++x) scol[static_cast<size_t>(x)] = NnCenterIndex(il + x, dw, sw);
    for (int y = 0; y < H1; ++y) {
        const int dx = (ScanOrdinal(y + phase, num, den) & 1) == 0 ? 1 : -1;
        const int oyN = ScanNext(y + phase, num, den) - (y + phase);
        const uint8_t* srow = src + static_cast<size_t>(nearRow[static_cast<size_t>(y)]) * sPitch;
        for (int n = 0; n < W1; ++n) {
            const int x = dx == 1 ? n : W1 - 1 - n;
            const size_t at = (static_cast<size_t>(y) * W1 + x) * 3;
            const int t = srow[scol[static_cast<size_t>(x)]];
            if (pal[t * 4 + 2] == big[at] && pal[t * 4 + 1] == big[at + 1] && pal[t * 4] == big[at + 2]) {
                fit[static_cast<size_t>(y) * W1 + x] = t;
                continue;
            }
            const int r = Clamp8(big[at] + err[at]), g = Clamp8(big[at + 1] + err[at + 1]), b = Clamp8(big[at + 2] + err[at + 2]);
            int pr = 0, pg = 0, pb = 0;
            int best = kPalLo; long long bd = -1;
            for (const int ci : cands) {
                const int cr = pal[ci * 4 + 2], cg = pal[ci * 4 + 1], cb = pal[ci * 4];
                const long long d = static_cast<long long>(kDistR) * (cr - r) * (cr - r) +
                                    static_cast<long long>(kDistG) * (cg - g) * (cg - g) +
                                    static_cast<long long>(kDistB) * (cb - b) * (cb - b);
                if (bd < 0 || d < bd) { bd = d; best = ci; pr = cr; pg = cg; pb = cb; }
            }
            fit[static_cast<size_t>(y) * W1 + x] = best;
            const int e3[3] = { ((r - pr) * kDitherQ8 + 128) >> 8, ((g - pg) * kDitherQ8 + 128) >> 8,
                                ((b - pb) * kDitherQ8 + 128) >> 8 };
            const int ox[4] = { dx, -dx, 0, dx }, oy[4] = { 0, oyN, oyN, oyN }, kk[4] = { 7, 3, 5, 1 };
            for (int m = 0; m < 4; ++m) {
                const int xx = x + ox[m], yy = y + oy[m];
                if (xx < 0 || xx >= W1 || yy >= H1) continue;
                int* e = &err[(static_cast<size_t>(yy) * W1 + xx) * 3];
                for (int c = 0; c < 3; ++c) e[c] += (e3[c] * kk[m] + 8) >> 4;
            }
        }
    }
    out->assign(static_cast<size_t>(dw) * dh, kSkip);
    for (int j = 0; j < dh; ++j)
        for (int i = 0; i < dw; ++i) {
            int v;
            if (j >= jt && j < jb && i >= il && i < ir) v = fit[static_cast<size_t>(j - jt) * W1 + (i - il)];
            else {                                  // the ring: pinned rows, or the row's own field beside the picture
                const int rr = (j >= jt && j < jb) ? nearRow[static_cast<size_t>(j - jt)] : crow[static_cast<size_t>(j)];
                v = src[static_cast<size_t>(rr) * sPitch + ccol[static_cast<size_t>(i)]];
                if (v == key) v = kSkip;
            }
            (*out)[static_cast<size_t>(j) * dw + i] = v;
        }
    *outW = dw; *outH = dh;
    return true;
}

// ---- replacement portraits from an RGB image: scaling_laws.py portrait_scanline_params / portrait_prereduce /
//      portrait_frame_rect / portrait_from_rgb / portrait_bake / portrait_enlarge_rgb, bit for bit.
//      rgb = r,g,b bytes, row pitch w*3.

constexpr int kSrcMaxLong = 1536;
constexpr int kFrameTopNum = 1, kFrameTopDen = 3;
constexpr int kScanOff = 0, kScanOverlay = 1, kScanMean = 2;   // pal everywhere below = RGBQUAD (b,g,r,x)

// v / 2^n rounded to nearest, halves away from zero (= scaling_laws.portrait_shr_round): the replacement path's
// error diffusion; Enlarge keeps its floor (the user-approved vanilla look)
inline int ShrRound(int v, int n)
{
    const int h = 1 << (n - 1);
    return v >= 0 ? (v + h) >> n : -((-v + h) >> n);
}

struct Rect { int x, y, w, h; };

// framed: the art has a 1-px frame (diplomacy / datalink / native life); the council slots do not
inline bool IsNativeArt(int w, int h, int sw, int sh, bool framed = true)
{
    return (w == sw && h == sh) || (framed && w == sw - 2 && h == sh - 2);
}

inline int Nearest(const uint8_t* pal, int r, int g, int b, int* pr, int* pg, int* pb)
{
    int best = kPalLo; long long bd = -1;
    for (int ci = kPalLo; ci <= kPalHi; ++ci) {
        const int cr = pal[ci * 4 + 2], cg = pal[ci * 4 + 1], cb = pal[ci * 4];
        const long long d = static_cast<long long>(kDistR) * (cr - r) * (cr - r) +
                            static_cast<long long>(kDistG) * (cg - g) * (cg - g) +
                            static_cast<long long>(kDistB) * (cb - b) * (cb - b);
        if (bd < 0 || d < bd) { bd = d; best = ci; *pr = cr; *pg = cg; *pb = cb; }
    }
    return best;
}

// Native-art replacement (a player's edit of the game art, exactly the slot's size): nearest colour, no dither,
// no scanlines.  Framed: the (sw-2)*(sh-2) interior (frame stripped from a full-size image); unframed: sw*sh.
inline bool BakeNative(const uint8_t* rgb, int w, int h, int sw, int sh, const uint8_t* pal, std::vector<int>* interior,
                       bool framed = true)
{
    if (!IsNativeArt(w, h, sw, sh, framed) || sw < 3 || sh < 3) return false;
    const int o = (framed && w == sw && h == sh) ? 1 : 0;
    const int m = framed ? 2 : 0;
    interior->assign(static_cast<size_t>(sw - m) * (sh - m), 0);
    for (int y = 0; y < sh - m; ++y)
        for (int x = 0; x < sw - m; ++x) {
            const uint8_t* p = rgb + (static_cast<size_t>(y + o) * w + x + o) * 3;
            int pr, pg, pb;
            (*interior)[static_cast<size_t>(y) * (sw - m) + x] = Nearest(pal, p[0], p[1], p[2], &pr, &pg, &pb);
        }
    return true;
}

inline void ScanlineParams(const uint8_t* src, int sPitch, int sw, int sh, const uint8_t* pal, int* bright, int* ratioQ8)
{
    const int W0 = sw - 2, H0 = sh - 2;
    long long ev = 0, od = 0;
    for (int y = 0; y < H0; ++y) {
        long long s = 0;
        for (int x = 0; x < W0; ++x) {
            const int i = src[(y + 1) * sPitch + x + 1];
            s += 77 * pal[i * 4 + 2] + 150 * pal[i * 4 + 1] + 29 * pal[i * 4];
        }
        ((y & 1) ? od : ev) += s;
    }
    const long long nEv = (H0 + 1) / 2, nOd = H0 / 2;
    const int b = (ev * nOd >= od * nEv) ? 0 : 1;
    const long long bSum = b == 0 ? ev : od, bN = b == 0 ? nEv : nOd;
    const long long dSum = b == 0 ? od : ev, dN = b == 0 ? nOd : nEv;
    long long den = bSum * dN; if (den < 1) den = 1;
    long long rq = (dSum * bN * 256) / den; if (rq > 256) rq = 256;
    *bright = b; *ratioQ8 = static_cast<int>(rq);
}

inline int PrereduceFactor(int w, int h)
{
    const int l = w > h ? w : h;
    const int k = (l + kSrcMaxLong - 1) / kSrcMaxLong;
    return k < 1 ? 1 : k;
}

// Box-average k x k blocks, rounding half up; trailing partial blocks dropped.  Returns false on k == 1 (use as is).
inline bool Prereduce(const uint8_t* rgb, int w, int h, std::vector<uint8_t>* out, int* ow, int* oh)
{
    const int k = PrereduceFactor(w, h);
    if (k == 1) return false;
    const int nw = w / k, nh = h / k, n = k * k;
    out->assign(static_cast<size_t>(nw) * nh * 3, 0);
    for (int y = 0; y < nh; ++y)
        for (int x = 0; x < nw; ++x)
            for (int c = 0; c < 3; ++c) {
                long long s = 0;
                for (int dy = 0; dy < k; ++dy) {
                    const uint8_t* row = rgb + (static_cast<size_t>(y * k + dy) * w + static_cast<size_t>(x) * k) * 3;
                    for (int dx = 0; dx < k; ++dx) s += row[dx * 3 + c];
                }
                (*out)[(static_cast<size_t>(y) * nw + x) * 3 + c] = static_cast<uint8_t>((s + n / 2) / n);
            }
    *ow = nw; *oh = nh;
    return true;
}

inline Rect FrameRect(int w, int h, int tw, int th)
{
    if (w < 1 || h < 1 || tw < 1 || th < 1) return { 0, 0, w > 0 ? w : 0, h > 0 ? h : 0 };   // FromRgb declines it
    if (static_cast<long long>(w) * th > static_cast<long long>(h) * tw) {
        int cw = static_cast<int>(static_cast<long long>(h) * tw / th); if (cw < 1) cw = 1;
        return { (w - cw) / 2, 0, cw, h };
    }
    int ch = static_cast<int>(static_cast<long long>(w) * th / tw); if (ch < 1) ch = 1;
    return { 0, ((h - ch) * kFrameTopNum) / kFrameTopDen, w, ch };
}

inline bool RgbArgsOk(const uint8_t* rgb, size_t rgbLen, int w, int h, Rect crop, int tw, int th)
{
    return rgb && w >= 1 && h >= 1 && tw >= 1 && th >= 1 && crop.w >= 1 && crop.h >= 1 && crop.x >= 0 && crop.y >= 0 &&
           crop.x <= w - crop.w && crop.y <= h - crop.h &&
           static_cast<unsigned long long>(rgbLen) >= static_cast<unsigned long long>(w) * static_cast<unsigned long long>(h) * 3ull;
}

// FromRgb's first stage: the crop Lanczos-resampled to tw x th, r,g,b ints (0..255).  It does not depend on the
// scan mode or the palette, so a caller may cache it (ResampleCache) and re-run only Finish -- the result is
// bit-identical to FromRgb by construction (FromRgb IS Resample + Finish).
inline void Resample(const uint8_t* rgb, int w, Rect crop, int tw, int th, std::vector<int>* big)
{
    const int half = 1 << (kWeightQ - 1);
    const std::vector<Taps> tx = MakeTaps(crop.w, tw), ty = MakeTaps(crop.h, th);
    std::vector<int> hor(static_cast<size_t>(tw) * crop.h * 3);
    big->assign(static_cast<size_t>(tw) * th * 3, 0);
    for (int y = 0; y < crop.h; ++y) {
        const uint8_t* row = rgb + (static_cast<size_t>(crop.y + y) * w + crop.x) * 3;
        for (int x = 0; x < tw; ++x) {
            const Taps& t = tx[static_cast<size_t>(x)];
            for (int c = 0; c < 3; ++c) {
                long long s = 0;
                for (size_t k = 0; k < t.q.size(); ++k) s += static_cast<long long>(t.q[k]) * row[(t.lo + k) * 3 + c];
                hor[(static_cast<size_t>(y) * tw + x) * 3 + c] = Clamp8(static_cast<int>((s + half) >> kWeightQ));
            }
        }
    }
    for (int y = 0; y < th; ++y) {
        const Taps& t = ty[static_cast<size_t>(y)];
        for (int x = 0; x < tw; ++x)
            for (int c = 0; c < 3; ++c) {
                long long s = 0;
                for (size_t k = 0; k < t.q.size(); ++k)
                    s += static_cast<long long>(t.q[k]) * hor[((static_cast<size_t>(t.lo) + k) * tw + x) * 3 + c];
                (*big)[(static_cast<size_t>(y) * tw + x) * 3 + c] = Clamp8(static_cast<int>((s + half) >> kWeightQ));
            }
    }
}

// FromRgb's second stage, in place on a resampled image: scanlines (scan mode), then the serpentine
// Floyd-Steinberg into the palette.  Scanlines are `rows` rows thick; y0 = the stripe-grid row of output row 0
// (a native bake: the interior row, 0 = first row inside the frame, -1 = an unframed sprite's top row; an enlarge:
// the dest buffer's phase, ScanPhase); grid row u is dark iff ((u // rows) & 1) != bright.
inline void Finish(std::vector<int>& big, int tw, int th, const uint8_t* pal, int scan, int bright, int ratioQ8,
                   int y0, int rows, std::vector<int>* fit)
{
    if (scan != kScanOff && ratioQ8 < 256 && rows > 0) {
        const int d = 256 + ratioQ8;
        for (int y = 0; y < th; ++y) {
            const bool dark = (FloorDiv(y0 + y, rows) & 1) != bright;
            if (scan == kScanOverlay && !dark) continue;
            for (int x = 0; x < tw * 3; ++x) {
                int& v = big[static_cast<size_t>(y) * tw * 3 + x];
                if (scan == kScanOverlay) v = (v * ratioQ8) >> 8;
                else if (dark) v = (v * 2 * ratioQ8 + d / 2) / d;
                else { v = (v * 512 + d / 2) / d; if (v > 255) v = 255; }
            }
        }
    }
    fit->assign(static_cast<size_t>(tw) * th, 0);
    for (int y = 0; y < th; ++y) {
        const int dx = (y & 1) == 0 ? 1 : -1;
        for (int n = 0; n < tw; ++n) {
            const int x = dx == 1 ? n : tw - 1 - n;
            int* a = &big[(static_cast<size_t>(y) * tw + x) * 3];
            const int r = Clamp8(a[0]), g = Clamp8(a[1]), b = Clamp8(a[2]);
            int pr = 0, pg = 0, pb = 0;
            (*fit)[static_cast<size_t>(y) * tw + x] = Nearest(pal, r, g, b, &pr, &pg, &pb);
            // symmetric rounding (ShrRound), not the floor of Enlarge: see scaling_laws.portrait_shr_round (F1)
            const int err[3] = { ShrRound((r - pr) * kDitherQ8, 8), ShrRound((g - pg) * kDitherQ8, 8),
                                 ShrRound((b - pb) * kDitherQ8, 8) };
            const int ox[4] = { dx, -dx, 0, dx }, oy[4] = { 0, 1, 1, 1 }, kk[4] = { 7, 3, 5, 1 };
            for (int m = 0; m < 4; ++m) {
                const int xx = x + ox[m], yy = y + oy[m];
                if (xx < 0 || xx >= tw || yy >= th) continue;
                int* t = &big[(static_cast<size_t>(yy) * tw + xx) * 3];
                for (int c = 0; c < 3; ++c) t[c] += ShrRound(err[c] * kk[m], 4);
            }
        }
    }
}

// A cache of Resample results the DLL may supply (keyed on whatever identifies the image).  Get returns null to
// mean "compute it".  GetFit / PutFit are the same for a FINISHED FromRgb result (Resample + Finish) under every
// input Finish reads: a hit skips both stages and is, by construction, the output of the same call (the DLL's
// background pre-bake, prewarm.cpp, fills it with FromRgb itself).  The defaults have none.
struct ResampleCache {
    virtual const std::vector<int>* Get(Rect crop, int tw, int th) = 0;
    virtual void Put(Rect crop, int tw, int th, const std::vector<int>& big) = 0;
    virtual bool GetFit(Rect, int, int, const uint8_t*, int, int, int, int, int, std::vector<int>*) { return false; }
    virtual void PutFit(Rect, int, int, const uint8_t*, int, int, int, int, int, const std::vector<int>&) {}
    virtual ~ResampleCache() {}
};

// tw x th palette indices (row-major) for a crop of an RGB image (rgbLen bytes).  y0 / rows = Finish's scanline
// phase / thickness.  False on degenerate input (empty image / target, crop outside the image, short buffer).
inline bool FromRgb(const uint8_t* rgb, size_t rgbLen, int w, int h, Rect crop, int tw, int th, const uint8_t* pal,
                    int scan, int bright, int ratioQ8, int y0, int rows, std::vector<int>* fit,
                    ResampleCache* cache = nullptr)
{
    if (!RgbArgsOk(rgb, rgbLen, w, h, crop, tw, th)) return false;
    if (cache && cache->GetFit(crop, tw, th, pal, scan, bright, ratioQ8, y0, rows, fit)) return true;
    std::vector<int> big;
    if (const std::vector<int>* hit = cache ? cache->Get(crop, tw, th) : nullptr) big = *hit;
    else {
        Resample(rgb, w, crop, tw, th, &big);
        if (cache) cache->Put(crop, tw, th, big);
    }
    Finish(big, tw, th, pal, scan, bright, ratioQ8, y0, rows, fit);
    if (cache) cache->PutFit(crop, tw, th, pal, scan, bright, ratioQ8, y0, rows, *fit);
    return true;
}

// EnlargeRgb's device geometry on its own: dw x dh = the whole device rect; the interior FromRgb target is
// W1 x H1 at device row jt / column il (framed), or dw x dh at 0 / 0 (unframed).  False when EnlargeRgb declines
// the sizes.  (The pre-bake asks the same question without a sprite.)
inline bool EnlargeGeometry(int sw, int sh, int num, int den, bool framed, int* dw, int* dh, int* W1, int* H1,
                            int* jt, int* il)
{
    if (!(num > den && den > 0 && sw >= 3 && sh >= 3)) return false;
    *dw = (sw * num) / den; *dh = (sh * num) / den;
    std::vector<int> crow(static_cast<size_t>(*dh)), ccol(static_cast<size_t>(*dw));
    for (int j = 0; j < *dh; ++j) crow[static_cast<size_t>(j)] = NnCenterIndex(j, *dh, sh);
    int t = 0, b = *dh, l = 0, r = *dw;
    while (t < *dh && crow[static_cast<size_t>(t)] <= 0) ++t;   // first device row of the interior source rows
    if (!framed) { *W1 = *dw; *H1 = *dh; *jt = t; *il = 0; return true; }
    for (int i = 0; i < *dw; ++i) ccol[static_cast<size_t>(i)] = NnCenterIndex(i, *dw, sw);
    while (b > 0 && crow[static_cast<size_t>(b - 1)] >= sh - 1) --b;
    while (l < *dw && ccol[static_cast<size_t>(l)] <= 0) ++l;
    while (r > 0 && ccol[static_cast<size_t>(r - 1)] >= sw - 1) --r;
    *W1 = r - l; *H1 = b - t; *jt = t; *il = l;
    return *W1 > 0 && *H1 > 0;
}

// Native-size replacement: the (sw-2) x (sh-2) interior.  (bright, ratioQ8) = the vanilla art's, measured by the
// caller with ScanlineParams BEFORE it overwrites anything (a re-bake must not re-measure).  A native-art image
// takes BakeNative.
inline bool Bake(int sw, int sh, const uint8_t* pal, const uint8_t* rgb, size_t rgbLen, int w, int h, int scan,
                 int bright, int ratioQ8, std::vector<int>* interior, bool framed = true,
                 ResampleCache* cache = nullptr)
{
    if (sw < 3 || sh < 3) return false;
    if (IsNativeArt(w, h, sw, sh, framed)) {
        if (static_cast<unsigned long long>(rgbLen) < static_cast<unsigned long long>(w) * h * 3ull) return false;
        return BakeNative(rgb, w, h, sw, sh, pal, interior, framed);
    }
    if (w < 1 || h < 1) return false;
    const int m = framed ? 2 : 0;
    return FromRgb(rgb, rgbLen, w, h, FrameRect(w, h, sw - m, sh - m), sw - m, sh - m, pal, scan, bright, ratioQ8,
                   framed ? 0 : -1, 1, interior, cache);
}

// Enlarge with the interior from the RGB image; the frame is the art's own edge-pinned NN.  Same output contract
// as Enlarge.  False for a native-art image (the caller enlarges its bake with Enlarge) and on degenerate input.
inline bool EnlargeRgb(const uint8_t* src, int sPitch, int sw, int sh, int key, const uint8_t* pal, int num, int den,
                       const uint8_t* rgb, size_t rgbLen, int w, int h, int scan, int bright, int ratioQ8,
                       int* outW, int* outH, std::vector<int>* out, bool framed = true,
                       ResampleCache* cache = nullptr, int y0 = 0)
{
    if (IsNativeArt(w, h, sw, sh, framed) || w < 1 || h < 1) return false;
    int dw, dh, W1, H1, jt, il;
    if (!EnlargeGeometry(sw, sh, num, den, framed, &dw, &dh, &W1, &H1, &jt, &il)) return false;
    const int scanT = ScanRows(num, den);
    if (!framed) {                                // the whole device rect is picture: no frame to keep
        if (!FromRgb(rgb, rgbLen, w, h, FrameRect(w, h, sw, sh), dw, dh, pal, scan, bright, ratioQ8,
                     ScanPhase(y0, num, den), scanT, out, cache))
            return false;
        *outW = dw; *outH = dh;
        return true;
    }
    const int jb = jt + H1, ir = il + W1;
    std::vector<int> crow(static_cast<size_t>(dh)), ccol(static_cast<size_t>(dw));
    for (int j = 0; j < dh; ++j) crow[static_cast<size_t>(j)] = NnCenterIndex(j, dh, sh);
    for (int i = 0; i < dw; ++i) ccol[static_cast<size_t>(i)] = NnCenterIndex(i, dw, sw);
    std::vector<int> fit;
    if (!FromRgb(rgb, rgbLen, w, h, FrameRect(w, h, sw - 2, sh - 2), W1, H1, pal, scan, bright, ratioQ8,
                 ScanPhase(y0 + jt, num, den), scanT, &fit, cache))
        return false;
    out->assign(static_cast<size_t>(dw) * dh, kSkip);
    for (int j = 0; j < dh; ++j)
        for (int i = 0; i < dw; ++i) {
            int v;
            if (j >= jt && j < jb && i >= il && i < ir) v = fit[static_cast<size_t>(j - jt) * W1 + (i - il)];
            else {
                v = src[crow[static_cast<size_t>(j)] * sPitch + ccol[static_cast<size_t>(i)]];
                if (v == key) v = kSkip;
            }
            (*out)[static_cast<size_t>(j) * dw + i] = v;
        }
    *outW = dw; *outH = dh;
    return true;
}

} // namespace portrait_law
