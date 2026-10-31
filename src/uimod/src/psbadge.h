// Punishment Sphere drone badge: the size law and the procedural rasteriser. Pure C++ (no Windows, no
// engine), so work\tests\ps_badge\badge_harness.cpp can compile it and compare it bit for bit with its
// source of truth, work\scripts\scaling_laws.py (ps_badge / ps_badge_raster / ps_badge_ramp). This file is
// a PORT of those laws: change them there first.
#pragma once

#include <cstdint>

namespace psbadge {

constexpr int kBadgeNum = 15, kBadgeDen = 38;          // diameter : face width (the 38 px face's design)
constexpr int kDark[3] = { 12, 20, 32 };
constexpr int kGold[3] = { 228, 208, 132 };
constexpr int kRingLoPct = 70, kRingHiPct = 92;        // gold ring   0.70R < r <= 0.92R
constexpr int kCorePct = 38;                           // gold core   r <= 0.38R
constexpr int kStrapLoPct = 30, kStrapHiPct = 80;      // gold straps on both diagonals, 0.30R..0.80R ...
constexpr int kStrapHalfPermille = 85;                 // ... of full width 0.17R
constexpr int kMaxDiameter = 64;
// Nerve-staple badge (scaling_laws PS_STAPLE_*): a black disc with a white X and a thin white rim -- the X of
// the game's nerve-staple button. Same disc and size law. Tones: 0 black (disc), 1 edge grey, 2 white (X, rim).
constexpr int kStapleTones[5][3] = { { 12, 10, 10 }, { 120, 118, 118 }, { 246, 246, 246 }, { 246, 246, 246 }, { 246, 246, 246 } };
constexpr int kStapleXHalfPct = 46;                               // the X spans +-0.46R, centred on the disc
constexpr int kStapleXHalfWidthPermille = 130, kStapleXMinHalfWidth = 12;   // stroke 0.26R wide, never under 1.5 px
constexpr int kStapleRimPct = 88;                                 // r > 0.88R is white

// d = half_down(15 * faceW, 38); inset = max(1, faceW / 38)
inline int Diameter(int faceW) { return (2 * kBadgeNum * faceW + kBadgeDen - 1) / (2 * kBadgeDen); }
inline int Inset(int faceW) { const int i = faceW / kBadgeDen; return i < 1 ? 1 : i; }
// scaling_laws.ps_badge_origin_x: upper-left on the base screen (rows overlap rightwards), upper-right on F4.
inline int OriginX(int faceX, int faceW, bool right) { return right ? faceX + faceW - Inset(faceW) - Diameter(faceW) : faceX + Inset(faceW); }

// Tone t's colour: DARK + (GOLD - DARK) * t / 4, rounded half-up.
inline int RampChannel(int t, int k) { return (8 * kDark[k] + 2 * (kGold[k] - kDark[k]) * t + 4) / 8; }
// The staple badge's tone colours (scaling_laws.ps_staple_ramp = PS_STAPLE_TONES).
inline int RampChannelStaple(int t, int k) { return kStapleTones[t][k]; }

// Colour class at 1/16 px position (u, v) about the centre, R = 8d: -1 outside, 2 white (rim or X), 0 black.
inline int StapleClass(int64_t u, int64_t v, int64_t R)
{
    const int64_t r2 = u * u + v * v;
    if (r2 > R * R) return -1;
    if (10000 * r2 > int64_t(kStapleRimPct) * kStapleRimPct * R * R) return 2;   // the rim
    const int64_t half = kStapleXHalfPct * R / 100;
    int64_t hw = kStapleXHalfWidthPermille * R / 1000;
    if (hw < kStapleXMinHalfWidth) hw = kStapleXMinHalfWidth;
    const int64_t au = u < 0 ? -u : u, av = v < 0 ? -v : v;
    const int64_t d1 = u - v < 0 ? v - u : u - v, d2 = u + v < 0 ? -(u + v) : u + v;
    if (au <= half && av <= half && (d1 <= hw || d2 <= hw)) return 2;         // the X
    return 0;
}

// The staple badge at device diameter d (scaling_laws.ps_staple_raster): 4x4 subsamples, the majority class
// wins; a white pixel with fewer than 8 of its 16 samples white is the edge tone 1.
inline void RasterStaple(int d, int8_t* tones)
{
    const int64_t R = 8 * d, R2 = R * R;
    for (int py = 0; py < d; ++py) {
        for (int px = 0; px < d; ++px) {
            const int64_t cu = 16 * px + 8 - 8 * d, cv = 16 * py + 8 - 8 * d;
            if (cu * cu + cv * cv > R2) { tones[py * d + px] = -1; continue; }
            int nBlack = 0, nWhite = 0;
            for (int sy = 0; sy < 4; ++sy)
                for (int sx = 0; sx < 4; ++sx) {
                    const int c = StapleClass(16 * px + 4 * sx + 2 - 8 * d, 16 * py + 4 * sy + 2 - 8 * d, R);
                    if (c == 0) ++nBlack; else if (c == 2) ++nWhite;
                }
            tones[py * d + px] = nWhite > nBlack ? (nWhite >= 8 ? 2 : 1) : 0;
        }
    }
}

// Positions are in 1/16 px about the badge centre; R = 8d.
inline bool Gold(int64_t u, int64_t v, int64_t R2)
{
    const int64_t r2 = u * u + v * v;
    if (r2 > R2) return false;
    if (10000 * r2 <= int64_t(kCorePct) * kCorePct * R2) return true;
    if (10000 * r2 > int64_t(kRingLoPct) * kRingLoPct * R2 && 10000 * r2 <= int64_t(kRingHiPct) * kRingHiPct * R2)
        return true;
    const int64_t ab[2][2] = { { u + v, u - v }, { u - v, u + v } };        // along / across, both x sqrt(2)
    for (const auto& s : ab) {
        const int64_t a2 = 10000 * s[0] * s[0], b2 = 1000000 * s[1] * s[1];
        if (b2 <= 2 * int64_t(kStrapHalfPermille) * kStrapHalfPermille * R2 &&
            a2 >= 2 * int64_t(kStrapLoPct) * kStrapLoPct * R2 && a2 <= 2 * int64_t(kStrapHiPct) * kStrapHiPct * R2)
            return true;
    }
    return false;
}

// tones[y * d + x] = 0..4 on the DARK->GOLD ramp, -1 = not drawn (pixel centre outside the disc).
// 4x4 subsamples per pixel, tone = (gold samples + 2) >> 2. Rasterised AT device size: never resampled.
inline void Raster(int d, int8_t* tones)
{
    const int64_t R2 = int64_t(8 * d) * (8 * d);
    for (int py = 0; py < d; ++py) {
        for (int px = 0; px < d; ++px) {
            const int64_t cu = 16 * px + 8 - 8 * d, cv = 16 * py + 8 - 8 * d;
            if (cu * cu + cv * cv > R2) { tones[py * d + px] = -1; continue; }
            int n = 0;
            for (int sy = 0; sy < 4; ++sy)
                for (int sx = 0; sx < 4; ++sx)
                    n += Gold(16 * px + 4 * sx + 2 - 8 * d, 16 * py + 4 * sy + 2 - 8 * d, R2) ? 1 : 0;
            tones[py * d + px] = static_cast<int8_t>((n + 2) >> 2);
        }
    }
}

} // namespace psbadge
