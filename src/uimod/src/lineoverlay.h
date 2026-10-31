// Lines the engine draws straight onto the game WINDOW, not into the frame: Win_window_line_raw 0x5F2AC0 (GetDC of
// the main window, a PALETTEINDEX pen, MoveToEx / LineTo at FRAME coordinates) -- the tutorial box's pointer lines
// and the console crosshair. In Fullscreen the window is the frame, the line sits on it until a later flip repaints
// its pixels, and the tutorial redraws it on every cursor blink. In the stretched modes (Borderless / Windowed) the
// GPU present repaints the WHOLE client on every flip (a DISCARD swap chain), so vidmode.cpp keeps the lines here
// and gpuscale.cpp composites them over every present, in client space -- with the same lifetime as on a real
// window: a flip that covers part of a line erases that part (an erase rect), one that covers all of it removes it,
// a redraw of the same line restores it whole.
//
// Header-only, no Windows types: work\tests\winline_selftest.cpp drives it.
#pragma once

namespace lineoverlay {

constexpr int kMaxLines = 8;           // the tutorial's two pointer lines + the crosshair pair, with room to spare
constexpr int kMaxErase = 6;           // partial repaints remembered per line; one more drops the line until its redraw

// The tutorial's two pointer lines, by the call site's return address (TutWin_draw_arrow 0x4BDED9 / 0x4BDF0F,
// TutWin_tut_win 0x4BE3FA / 0x4BE432; the pen-width thunk in front of them tail-jumps, so the return address is
// the site's own).
constexpr unsigned kRetTutLine1[2] = { 0x4BDEDE, 0x4BE3FF };
constexpr unsigned kRetTutLine2[2] = { 0x4BDF14, 0x4BE437 };
enum Tag { kTagOther = 0, kTagTut1 = 1, kTagTut2 = 2 };

inline int TagOf(unsigned ret)
{
    if (ret == kRetTutLine1[0] || ret == kRetTutLine1[1]) return kTagTut1;
    if (ret == kRetTutLine2[0] || ret == kRetTutLine2[1]) return kTagTut2;
    return kTagOther;
}

struct Rect { int l, t, r, b; };       // half-open, frame pixels

struct Line {
    int x0, y0, x1, y1;                // MoveToEx point -> LineTo point, frame pixels
    int color;                         // palette index (the engine's pen is PALETTEINDEX(color & 0xFFFF))
    int width;                         // pen width, frame pixels (0 = a cosmetic one-pixel pen)
    int style;                         // PS_* (low nibble); dashes only on a one-pixel pen, as GDI draws them
    int tag;                           // Tag
    int nErase;
    Rect erase[kMaxErase];             // later flips that repainted part of the line away
};

struct List {
    Line line[kMaxLines];
    int n;
};

constexpr int kPsNull = 5;
inline int StyleOf(int style) { return style & 0xF; }
inline int PenWidth(const Line& l) { return l.width > 1 ? l.width : 1; }
// GDI draws a wider pen solid whatever its dash style; PS_INSIDEFRAME (6) and the rest draw solid too.
inline bool Dashed(const Line& l) { const int s = StyleOf(l.style); return PenWidth(l) == 1 && s >= 1 && s <= 4; }

// The pixels the stroke can cover, half-open. A one-pixel (cosmetic) pen is GDI's DDA line, which stops one pixel
// short of the LineTo point along the major axis (Console_on_nc_mouse_move draws MoveTo(0,y) -> LineTo(W,y) and
// erases it by flipping exactly [0,W) x [y,y+1), 0x5D55D0); a zero-length one draws nothing. A wider pen is a round
// geometric pen around the whole centre line.
inline bool Empty(const Line& l) { return PenWidth(l) == 1 && l.x0 == l.x1 && l.y0 == l.y1; }

inline Rect Bounds(const Line& l)
{
    int ex = l.x1, ey = l.y1;
    if (PenWidth(l) == 1) {
        const int dx = l.x1 - l.x0, dy = l.y1 - l.y0;
        const int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
        if (adx >= ady && adx) ex -= dx > 0 ? 1 : -1;
        else if (ady) ey -= dy > 0 ? 1 : -1;
    }
    const int h = PenWidth(l) / 2;
    const int lo_x = l.x0 < ex ? l.x0 : ex, hi_x = l.x0 < ex ? ex : l.x0;
    const int lo_y = l.y0 < ey ? l.y0 : ey, hi_y = l.y0 < ey ? ey : l.y0;
    return { lo_x - h, lo_y - h, hi_x + h + 1, hi_y + h + 1 };
}

inline bool Overlap(const Rect& a, const Rect& b) { return a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b; }
inline bool Contains(const Rect& outer, const Rect& in) { return outer.l <= in.l && outer.t <= in.t && outer.r >= in.r && outer.b >= in.b; }

// Does the centre line, thickened by the pen, reach into f? (Liang-Barsky clip against f grown by the pen radius.)
inline bool Touches(const Line& l, const Rect& f)
{
    const Rect bb = Bounds(l);
    if (!Overlap(bb, f)) return false;
    const double h = PenWidth(l) / 2.0 + 0.5;
    const double xl = f.l - h, xr = f.r - 1 + h, yt = f.t - h, yb = f.b - 1 + h;
    double t0 = 0.0, t1 = 1.0;
    const double dx = static_cast<double>(l.x1) - l.x0, dy = static_cast<double>(l.y1) - l.y0;
    const double p[4] = { -dx, dx, -dy, dy };
    const double q[4] = { l.x0 - xl, xr - l.x0, l.y0 - yt, yb - l.y0 };
    for (int i = 0; i < 4; ++i) {
        if (p[i] == 0.0) {
            if (q[i] < 0.0) return false;
            continue;
        }
        const double r = q[i] / p[i];
        if (p[i] < 0.0) { if (r > t1) return false; if (r > t0) t0 = r; }
        else            { if (r < t0) return false; if (r < t1) t1 = r; }
    }
    return t0 <= t1;
}

inline void Remove(List& s, int i)
{
    for (int k = i; k + 1 < s.n; ++k) s.line[k] = s.line[k + 1];
    --s.n;
}

inline void Clear(List& s) { s.n = 0; }

inline bool Same(const Line& a, const Line& b)
{
    return a.x0 == b.x0 && a.y0 == b.y0 && a.x1 == b.x1 && a.y1 == b.y1 && a.color == b.color && a.width == b.width &&
           StyleOf(a.style) == StyleOf(b.style);
}

// The engine drew a line. A redraw of a known line paints it whole again; a tutorial first line that differs is a
// new pointer: the old pointer's lines go. PS_NULL and a zero-length one-pixel line draw nothing and are not kept
// (returns false). When full, the oldest line goes -- never a tutorial pointer line.
inline bool Add(List& s, Line l)
{
    if (StyleOf(l.style) == kPsNull || Empty(l)) return false;
    l.nErase = 0;
    if (l.tag == kTagTut1) {               // a different first line = a new pointer: both old lines go (the second, if
        bool moved = false;                // any, is drawn right after this one)
        for (int i = 0; i < s.n; ++i) moved = moved || (s.line[i].tag == kTagTut1 && !Same(s.line[i], l));
        if (moved)
            for (int i = s.n - 1; i >= 0; --i)
                if (s.line[i].tag == kTagTut1 || s.line[i].tag == kTagTut2) Remove(s, i);
    }
    for (int i = 0; i < s.n; ++i)
        if (Same(s.line[i], l)) {
            s.line[i].nErase = 0;
            s.line[i].tag = l.tag;
            return true;
        }
    if (s.n == kMaxLines) {                // the oldest line that is not the tutorial pointer's (at most 2 are)
        int victim = 0;
        while (victim < s.n - 1 && s.line[victim].tag != kTagOther) ++victim;
        Remove(s, victim);
    }
    s.line[s.n++] = l;
    return true;
}

// The engine flipped frame rect f to the window: the part of each line under it is repainted away.
// Returns true when anything changed.
inline bool OnFlip(List& s, const Rect& f)
{
    bool changed = false;
    for (int i = s.n - 1; i >= 0; --i) {
        Line& l = s.line[i];
        if (!Touches(l, f)) continue;
        if (Contains(f, Bounds(l))) { Remove(s, i); changed = true; continue; }
        bool inside = false;               // already masked by a remembered repaint
        for (int k = 0; k < l.nErase && !inside; ++k) inside = Contains(l.erase[k], f);
        if (inside) continue;
        changed = true;
        for (int k = l.nErase - 1; k >= 0; --k)
            if (Contains(f, l.erase[k])) {   // the new repaint supersedes an older, smaller one
                for (int m = k; m + 1 < l.nErase; ++m) l.erase[m] = l.erase[m + 1];
                --l.nErase;
            }
        if (l.nErase == kMaxErase) { Remove(s, i); continue; }   // until its next redraw
        l.erase[l.nErase++] = f;
    }
    return changed;
}

// The tutorial pointer's own state (TutWin +0x53A4 armed, +0x539C second line's x, -1 = none): once disarmed (the box
// dismissed) its lines are gone, as the engine never draws them again. Returns true when anything changed.
inline bool PruneTutorial(List& s, bool armed, bool hasSecond)
{
    bool changed = false;
    for (int i = s.n - 1; i >= 0; --i)
        if ((s.line[i].tag == kTagTut1 && !armed) || (s.line[i].tag == kTagTut2 && (!armed || !hasSecond))) {
            Remove(s, i);
            changed = true;
        }
    return changed;
}

// Frame -> client for the GDI fallback (the CPU present keeps what is drawn on the window, as Fullscreen does): the
// client pixel holding the image of the frame pixel's centre, and the pen scaled with the frame (vanilla x scale).
inline int ToClient(int v, int client, int frame)
{
    const long long num = (2LL * v + 1) * client, den = 2LL * frame;
    return static_cast<int>(num >= 0 ? num / den : -((-num + den - 1) / den));   // floor: a line may start off-frame
}

inline int ClientPenWidth(int width, int style, int client, int frame)
{
    Line l = {};
    l.width = width; l.style = style;
    if (Dashed(l)) return width;           // a wider pen would draw the dashes solid
    const long long w = PenWidth(l);
    const int c = static_cast<int>((2LL * w * client + frame) / (2LL * frame));
    return c > 1 ? c : 1;
}

} // namespace lineoverlay
