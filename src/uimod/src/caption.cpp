// Post-movie caption -- a port of vanilla's movie caption (terranx 0x4BEF00 + Buffer_write_strings
// 0x5DB040 + the typewriter callback 0x4BEE60), which lives inside the amovie body our entry hook
// replaces. Reference implementation + measured vanilla numbers: work\tests\movie_caption\
// caption_layout.py (keep the two in step).
//
// Scaling law: vanilla lays the caption out on a 640x480 surface with the clip 1:1 in its centre.
// We lay it out in that NATIVE space with the NATIVE fonts (so line breaks and positions are
// vanilla's, exactly), then map every position through the movie's own uniform scale
// k = dstWidth / nativeClipWidth and draw with fonts of size*k: caption = vanilla x k at any
// resolution, on both exes, for .wve and HD sources alike.

#include "caption.h"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

constexpr uintptr_t kImageBase     = 0x00400000;
constexpr uintptr_t kVA_GamePal    = 0x009B8174;  // *(Palette*) current game palette (PALETTEENTRY[256] at +0)
constexpr int       kSurfW = 640, kSurfH = 480;   // vanilla movie-mode surface

std::string g_testMovlist;   // non-empty = offline harness (see CaptionTestOverride)

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}

struct FontSpec { std::string face; int style = 0, size = 10; int fg = 0, shadow = 0, sdx = 1, sdy = 1; };

struct Section {
    FontSpec font[3];
    int x = 160, y = 150, w = 320, h = 180;
    int delayMs = 10, holdMs = 4000;
    std::vector<std::string> lines;
};

// ---- movlist.txt ------------------------------------------------------------------------------

std::string Trim(const std::string& s)
{
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t' || s[a] == '\r')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r')) --b;
    return s.substr(a, b - a);
}

std::vector<std::string> Items(const std::string& line)
{
    std::vector<std::string> out;
    size_t p = 0;
    while (p <= line.size()) {
        size_t c = line.find(',', p);
        if (c == std::string::npos) c = line.size();
        out.push_back(Trim(line.substr(p, c - p)));
        p = c + 1;
    }
    return out;
}

int Num(const std::vector<std::string>& it, size_t i, int def)
{
    return (i < it.size() && !it[i].empty()) ? atoi(it[i].c_str()) : def;
}

bool LoadSection(const char* name, Section* sec)
{
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    if (char* slash = strrchr(path, '\\')) slash[1] = '\0';
    lstrcatA(path, "movlist.txt");
    if (!g_testMovlist.empty()) lstrcpynA(path, g_testMovlist.c_str(), MAX_PATH);

    char key[MAX_PATH]; lstrcpynA(key, name ? name : "", MAX_PATH);
    if (char* dot = strrchr(key, '.'); dot && lstrlenA(dot) <= 4) *dot = '\0';
    if (!*key) return false;

    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return false;
    std::vector<std::string> all;
    char buf[1024];
    while (fgets(buf, sizeof buf, f)) {
        std::string s(buf);
        while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
        all.push_back(s);
    }
    fclose(f);

    size_t i = 0;
    for (; i < all.size(); ++i)
        if (all[i].size() > 1 && all[i][0] == '#' && lstrcmpiA(Trim(all[i].substr(1)).c_str(), key) == 0) break;
    if (i >= all.size()) return false;
    ++i;

    // Header: the engine's text_get skips nothing here -- 8 consecutive item lines.
    auto next = [&](std::vector<std::string>* it) {
        if (i >= all.size() || (!all[i].empty() && all[i][0] == '#')) return false;
        *it = Items(all[i++]);
        return true;
    };
    std::vector<std::string> it;
    for (int n = 0; n < 3; ++n) {
        if (!next(&it) || it.empty() || it[0].empty()) return false;
        sec->font[n].face = it[0];
        sec->font[n].style = Num(it, 1, 0);
        sec->font[n].size = Num(it, 2, 10);
        if (!next(&it)) return false;
        sec->font[n].fg = Num(it, 0, 56) + 10;       // the engine adds 10 to both indices
        sec->font[n].shadow = Num(it, 1, 55) + 10;
        sec->font[n].sdx = Num(it, 2, 1);
        sec->font[n].sdy = Num(it, 3, 1);
    }
    if (!next(&it)) return false;
    sec->x = Num(it, 0, 160); sec->y = Num(it, 1, 150); sec->w = Num(it, 2, 320); sec->h = Num(it, 3, 180);
    if (!next(&it)) return false;
    sec->delayMs = Num(it, 0, 10); sec->holdMs = Num(it, 1, 4000);

    if (i < all.size() && Trim(all[i]).empty()) ++i;   // the blank separator line
    for (; i < all.size(); ++i) {
        const std::string t = Trim(all[i]);
        if (t.empty() || t[0] == '#') break;
        if (t[0] == '@') continue;                     // section include: unused by any caption
        sec->lines.push_back(t);
    }
    return !sec->lines.empty() && sec->w > 0 && sec->h > 0;
}

// ---- layout (native 640x480 space) ------------------------------------------------------------

enum { PARA_CONT, PARA_LEFT, PARA_CENTRE, PARA_BLANK };
const int kSlotFont[4] = { 0, 1, 2, 0 };   // Buffer_set_font(f0, f1, f2, f0): 1 {..}, 2 [..], 3 $LINK

struct Ch { char c; int slot; };
struct Run { std::string text; int slot; };
struct Line { int kind; std::vector<Run> runs; int xNative; int yTextOut; int wNative; };

void ParseNode(const std::string& s, int* kind, std::string* text)
{
    if (s.empty() || s[0] != '^') { *kind = PARA_CONT; *text = s; return; }
    if (s.size() == 1) { *kind = PARA_BLANK; text->clear(); return; }
    if (s[1] != '^') { *kind = PARA_LEFT; *text = s.substr(1); return; }
    *kind = PARA_CENTRE;
    *text = (s.size() > 2 && s[2] == '^') ? s.substr(3) : s.substr(2);
}

std::vector<Ch> Tokenize(const std::string& t)
{
    std::vector<Ch> out;
    int slot = 0;
    size_t i = 0, n = t.size();
    while (i < n) {
        const char c = t[i];
        const bool special = c == '{' || c == '}' || c == '[' || c == ']' || c == '$' || (slot == 3 && c == '=');
        if (!special) { out.push_back({ c, slot }); ++i; continue; }
        if (c == '$') {
            if (t.compare(i, 6, "$LINK<") == 0) { slot = 3; i += 6; }
            else ++i;                                   // a lone '$' is dropped
        } else if (c == '=') {                          // inside a link: skip "=id>"
            const size_t j = t.find('>', i + 1);
            i = (j != std::string::npos) ? j + 1 : i + 1;
            slot = 0;
        } else if (i + 1 < n && t[i + 1] == c) {        // doubled bracket = literal
            out.push_back({ c, slot }); i += 2;
        } else {
            slot = (c == '{') ? 1 : (c == '[') ? 2 : 0; ++i;
        }
    }
    return out;
}

std::vector<Run> ToRuns(const std::vector<Ch>& chars)
{
    std::vector<Run> runs;
    for (const Ch& ch : chars) {
        if (!runs.empty() && runs.back().slot == ch.slot) runs.back().text += ch.c;
        else runs.push_back({ std::string(1, ch.c), ch.slot });
    }
    return runs;
}

int Extent(HDC dc, HFONT f, const char* s, int n)
{
    if (n <= 0) return 0;
    HGDIOBJ old = SelectObject(dc, f);
    SIZE sz{};
    GetTextExtentPoint32A(dc, s, n, &sz);
    SelectObject(dc, old);
    return sz.cx;
}

int RunsWidth(HDC dc, HFONT fonts[3], const std::vector<Run>& runs)
{
    int w = 0;
    for (const Run& r : runs) w += Extent(dc, fonts[kSlotFont[r.slot]], r.text.c_str(), static_cast<int>(r.text.size()));
    return w;
}

int TruncHalf(int d) { return d >= 0 ? d / 2 : -((-d) / 2); }

// Font_init 0x618F40: lfHeight = -size, weight 700 if style&1 else FW_DONTCARE, TT only, default quality.
HFONT MakeFont(const FontSpec& fs, int height)
{
    return CreateFontA(-height, 0, 0, 0, (fs.style & 1) ? 700 : 0, (fs.style & 2) ? TRUE : FALSE,
                       (fs.style & 4) ? TRUE : FALSE, FALSE, ANSI_CHARSET, OUT_TT_ONLY_PRECIS,
                       CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, fs.face.c_str());
}

std::vector<Line> Layout(const Section& sec, HDC mdc, HFONT nat[3], const TEXTMETRICA tm[3])
{
    const int LH = tm[0].tmHeight + tm[0].tmExternalLeading;   // EVERY line advances by font0's
    int yShift = 0;                                             // max(ascent - internal leading), slots 0..2
    for (int n = 0; n < 3; ++n) {
        const int v = tm[n].tmAscent - tm[n].tmInternalLeading;
        if (v > yShift) yShift = v;
    }

    // A caret-less line continues the previous paragraph, joined with one space.
    std::vector<std::pair<int, std::string>> paras;
    for (const std::string& ln : sec.lines) {
        int kind; std::string text;
        ParseNode(ln, &kind, &text);
        if (kind == PARA_CONT && !paras.empty() && paras.back().first != PARA_BLANK && paras.back().first != PARA_CENTRE)
            paras.back().second += " " + text;
        else
            paras.push_back({ kind, text });
    }

    std::vector<Line> vis;
    for (auto& p : paras) {
        if (p.first == PARA_BLANK) { vis.push_back({ PARA_BLANK, {}, 0, 0, 0 }); continue; }
        const std::vector<Ch> chars = Tokenize(p.second);
        // Greedy wrap; a chunk is [space]word and the break goes AFTER the space (the wrapped line
        // keeps its trailing space, which counts in the centring width).
        std::vector<Ch> cur;
        size_t i = 0;
        while (i < chars.size()) {
            size_t j = i + 1;
            while (j < chars.size() && chars[j].c != ' ') ++j;
            std::vector<Ch> chunk(chars.begin() + i, chars.begin() + j);
            std::vector<Ch> trial(cur); trial.insert(trial.end(), chunk.begin(), chunk.end());
            if (!cur.empty() && RunsWidth(mdc, nat, ToRuns(trial)) > sec.w) {
                if (!chunk.empty() && chunk[0].c == ' ') { cur.push_back(chunk[0]); chunk.erase(chunk.begin()); }
                vis.push_back({ p.first, ToRuns(cur), 0, 0, 0 });
                cur.clear();
            }
            cur.insert(cur.end(), chunk.begin(), chunk.end());
            i = j;
        }
        vis.push_back({ p.first, ToRuns(cur), 0, 0, 0 });
    }

    const int H = LH * static_cast<int>(vis.size());
    const int y0 = sec.y + TruncHalf(sec.h - H);
    for (size_t k = 0; k < vis.size(); ++k) {
        Line& l = vis[k];
        l.wNative = RunsWidth(mdc, nat, l.runs);
        l.xNative = sec.x + (l.kind == PARA_CENTRE ? TruncHalf(sec.w - l.wNative) : 0);
        l.yTextOut = y0 + static_cast<int>(k) * LH + yShift;   // vanilla TextOutA's here with TA_TOP
    }
    return vis;
}

COLORREF PalColor(int idx, COLORREF fallback)
{
    if (!g_testMovlist.empty()) return fallback;
    const BYTE* pal = *reinterpret_cast<BYTE**>(At(kVA_GamePal));
    if (!pal || idx < 0 || idx > 255 || IsBadReadPtr(pal, 1024)) return fallback;
    return RGB(pal[idx * 4], pal[idx * 4 + 1], pal[idx * 4 + 2]);
}

int RoundI(double v) { return static_cast<int>(std::floor(v + 0.5)); }

} // namespace

void CaptionTestOverride(const char* movlistPath)
{
    g_testMovlist = movlistPath ? movlistPath : "";
}

void RunMovieCaption(const char* name, const CaptionTarget& t,
                     const std::function<void()>& present,
                     const std::function<bool()>& pumpSkip)
{
    Section sec;
    if (!t.memDC || t.nativeW <= 0 || t.nativeH <= 0 || !LoadSection(name, &sec)) return;

    if (!g_testMovlist.empty()) { sec.delayMs = 0; sec.holdMs = 0; }

    // The movie's own uniform scale; the 640x480 surface is centred on the clip.
    const double k  = static_cast<double>(t.dst.right - t.dst.left) / t.nativeW;
    const double ox = t.dst.left - (kSurfW - t.nativeW) / 2.0 * k;
    const double oy = t.dst.top  - (kSurfH - t.nativeH) / 2.0 * k;

    HDC mdc = CreateCompatibleDC(nullptr);             // the engine measures on one of these too
    HFONT nat[3]{}, big[3]{};
    TEXTMETRICA tm[3]{};
    bool ok = mdc != nullptr;
    for (int n = 0; ok && n < 3; ++n) {
        nat[n] = MakeFont(sec.font[n], sec.font[n].size);
        int bh = RoundI(sec.font[n].size * k);
        big[n] = MakeFont(sec.font[n], bh < 1 ? 1 : bh);
        ok = nat[n] && big[n];
        if (ok) { HGDIOBJ o = SelectObject(mdc, nat[n]); GetTextMetricsA(mdc, &tm[n]); SelectObject(mdc, o); }
    }

    if (ok) {
        const std::vector<Line> lines = Layout(sec, mdc, nat, tm);
        const int oldMode = SetBkMode(t.memDC, TRANSPARENT);
        const UINT oldAlign = SetTextAlign(t.memDC, TA_LEFT | TA_BASELINE);
        const COLORREF oldCol = GetTextColor(t.memDC);
        HGDIOBJ oldFont = GetCurrentObject(t.memDC, OBJ_FONT);

        bool skip = false;
        for (size_t li = 0; !skip && li < lines.size(); ++li) {
            const Line& l = lines[li];
            if (l.runs.empty()) continue;
            // Keep the line's CENTRE at vanilla x k (scaled glyph widths are not exactly k x native).
            const int wBig = RunsWidth(t.memDC, big, l.runs);
            double x = (l.kind == PARA_CENTRE)
                     ? ox + (l.xNative + l.wNative / 2.0) * k - wBig / 2.0
                     : ox + l.xNative * k;
            for (size_t ri = 0; !skip && ri < l.runs.size(); ++ri) {
                const Run& r = l.runs[ri];
                const int fi = kSlotFont[r.slot];
                const FontSpec& fs = sec.font[fi];
                // Baseline = vanilla baseline x k (vanilla: TA_TOP at yTextOut, so + the run font's ascent).
                const int yb = RoundI(oy + (l.yTextOut + tm[fi].tmAscent) * k);
                const int sdx = RoundI(fs.sdx * k), sdy = RoundI(fs.sdy * k);
                const COLORREF fg = PalColor(fs.fg, RGB(231, 235, 231));
                const COLORREF sh = PalColor(fs.shadow, RGB(0, 0, 0));
                const int xRun = RoundI(x);
                SelectObject(t.memDC, big[fi]);
                for (size_t ci = 0; !skip && ci < r.text.size(); ++ci) {
                    const DWORD t0 = GetTickCount();
                    const int xc = xRun + Extent(t.memDC, big[fi], r.text.c_str(), static_cast<int>(ci));
                    SelectObject(t.memDC, big[fi]);
                    SetTextColor(t.memDC, sh);
                    TextOutA(t.memDC, xc + sdx, yb + sdy, &r.text[ci], 1);
                    SetTextColor(t.memDC, fg);
                    TextOutA(t.memDC, xc, yb, &r.text[ci], 1);
                    GdiFlush();
                    present();
                    // Vanilla: period = max(delay, draw cost), busy-wait; we pump instead.
                    do {
                        skip = pumpSkip();
                        if (skip || GetTickCount() - t0 >= static_cast<DWORD>(sec.delayMs)) break;
                        Sleep(1);
                    } while (true);
                }
                x += Extent(t.memDC, big[fi], r.text.c_str(), static_cast<int>(r.text.size()));
            }
        }

        // Hold (the file's value, verbatim). Vanilla ignores input here; we let the skip keys end it.
        const DWORD h0 = GetTickCount();
        int tick = 0;
        while (!skip && GetTickCount() - h0 < static_cast<DWORD>(sec.holdMs)) {
            skip = pumpSkip();
            if (skip) break;
            if (++tick % 25 == 0) present();           // re-assert after alt-tab
            Sleep(10);
        }

        SelectObject(t.memDC, oldFont);
        SetTextColor(t.memDC, oldCol);
        SetTextAlign(t.memDC, oldAlign);
        SetBkMode(t.memDC, oldMode);
    }

    for (int n = 0; n < 3; ++n) { if (nat[n]) DeleteObject(nat[n]); if (big[n]) DeleteObject(big[n]); }
    if (mdc) DeleteDC(mdc);
}
