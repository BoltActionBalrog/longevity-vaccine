#pragma once
// hdpack.h -- what the drop-in HD sprite hooks share (basehd.cpp, objecthd.cpp): an 8-bit PCX pack proven usable
// ONCE, kept as its own file bytes, and any rect of it expanded on demand.
//
// Pack files come from strangers, so nothing here trusts the file. Load reads the whole file in one call and scans it
// before anything else sees it: 8-bit, one plane, RLE (encoding byte 1), BytesPerLine == width, exactly the size the
// caller asks for, every scanline exactly `width` pixels with no run crossing its end and no zero-length run, the
// stream ending inside the file before the 769-byte palette trailer, the trailer's 0x0C marker, and (when the caller
// passes one) the trailer's palette equal to the stock file's. A file that fails any of these is art that was not
// provided. The engine's PCX decoder (0x5E2690, behind Buffer_load_pcx) is never handed a pack.
//
// Memory: a loaded pack is its file bytes (the PCX RLE, ~3 to 4 MB for the packs made so far) plus one offset per
// scanline. Expand walks only the scanlines of the rect it is asked for, from their recorded offsets, so cutting one
// sprite never decodes the sheet. Nothing here allocates through the engine; every allocation failure is a false
// return, never an exception.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace hdpack {

constexpr int kHeader = 128, kTrailer = 769;

enum Result { kOk = 0, kNoFile, kNotPcx, kWrongSize, kBadBody, kNoPalette, kWrongPalette, kNoMemory };

inline const char* Why(Result r)
{
    switch (r) {
    case kOk:           return "ok";
    case kNoFile:       return "cannot be read";
    case kNotPcx:       return "is not an 8-bit one-plane RLE PCX with BytesPerLine = width";
    case kWrongSize:    return "has the wrong size";
    case kBadBody:      return "has a damaged or truncated body";
    case kNoPalette:    return "has no palette trailer";
    case kWrongPalette: return "has a palette that differs from the stock file's";
    case kNoMemory:     return "could not be loaded (no memory)";
    }
    return "?";
}

struct Pack {
    uint8_t* bytes = nullptr;    // the whole file (malloc)
    uint32_t* row = nullptr;     // h offsets into bytes: where each scanline's RLE starts
    int w = 0, h = 0;
    size_t size = 0;
};

inline void Free(Pack* p)
{
    free(p->bytes);
    free(p->row);
    *p = Pack{};
}

// The whole file in one malloc'd block, or null.
inline uint8_t* ReadAll(const char* path, size_t* n, bool* noMem)
{
    *noMem = false;
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return nullptr;
    uint8_t* buf = nullptr;
    if (fseek(f, 0, SEEK_END) == 0) {
        const long len = ftell(f);
        if (len > 0 && fseek(f, 0, SEEK_SET) == 0) {
            buf = static_cast<uint8_t*>(malloc(static_cast<size_t>(len)));
            if (!buf) *noMem = true;
            else if (fread(buf, 1, static_cast<size_t>(len), f) != static_cast<size_t>(len)) { free(buf); buf = nullptr; }
            else *n = static_cast<size_t>(len);
        }
    }
    fclose(f);
    return buf;
}

// The 768-byte palette of a PCX on disk (its trailer), e.g. the stock file a pack must match.
inline bool ReadPalette(const char* path, uint8_t pal[768])
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return false;
    const bool ok = fseek(f, -kTrailer, SEEK_END) == 0 && fgetc(f) == 0x0C && fread(pal, 1, 768, f) == 768;
    fclose(f);
    return ok;
}

// Prove bytes[0..n) is a usable wantW x wantH pack and record each scanline's offset into row[] (wantH entries).
inline Result Scan(const uint8_t* b, size_t n, int wantW, int wantH, uint32_t* row)
{
    if (n < static_cast<size_t>(kHeader + kTrailer)) return kNotPcx;
    if (b[0] != 10 || b[2] != 1 || b[3] != 8 || b[65] != 1) return kNotPcx;
    const int w = (b[8] | b[9] << 8) - (b[4] | b[5] << 8) + 1;
    const int h = (b[10] | b[11] << 8) - (b[6] | b[7] << 8) + 1;
    const int bpl = b[66] | b[67] << 8;
    if (bpl != w) return kNotPcx;
    if (w != wantW || h != wantH) return kWrongSize;
    const size_t end = n - kTrailer;                      // the RLE stream must end before the palette trailer
    size_t i = kHeader;
    for (int y = 0; y < h; ++y) {
        row[y] = static_cast<uint32_t>(i);
        int x = 0;
        while (x < w) {
            if (i >= end) return kBadBody;
            int run = 1;
            if ((b[i] & 0xC0) == 0xC0) {
                run = b[i] & 0x3F;
                if (run == 0 || i + 1 >= end) return kBadBody;
                ++i;
            }
            ++i;
            if (x + run > w) return kBadBody;             // a run never crosses the end of a line
            x += run;
        }
    }
    if (b[end] != 0x0C) return kNoPalette;
    return kOk;
}

// Load and prove a pack. stockPal (768 bytes, optional): the pack's palette must equal it.
inline Result Load(Pack* p, const char* path, int wantW, int wantH, const uint8_t* stockPal)
{
    Free(p);
    bool noMem = false;
    size_t n = 0;
    uint8_t* b = ReadAll(path, &n, &noMem);
    if (!b) return noMem ? kNoMemory : kNoFile;
    uint32_t* row = wantH > 0 ? static_cast<uint32_t*>(malloc(sizeof(uint32_t) * static_cast<size_t>(wantH))) : nullptr;
    if (!row) { free(b); return wantH > 0 ? kNoMemory : kWrongSize; }
    Result r = Scan(b, n, wantW, wantH, row);
    if (r == kOk && stockPal && memcmp(b + n - kTrailer + 1, stockPal, 768) != 0) r = kWrongPalette;
    if (r != kOk) { free(b); free(row); return r; }
    p->bytes = b;
    p->row = row;
    p->w = wantW;
    p->h = wantH;
    p->size = n;
    return kOk;
}

// Expand the rect (x0, y0, cw, ch) of a loaded pack into out (cw * ch bytes, row-major), each file index v written
// as map[v]. The rect must lie inside the pack (false otherwise). Only the rect's scanlines are walked, each from its
// recorded start to the rect's right edge; Scan proved every one of them, so the walk needs no checks of its own.
inline bool Expand(const Pack& p, int x0, int y0, int cw, int ch, const uint8_t map[256], uint8_t* out)
{
    if (!p.bytes || x0 < 0 || y0 < 0 || cw <= 0 || ch <= 0 || x0 + cw > p.w || y0 + ch > p.h) return false;
    const int x1 = x0 + cw;
    for (int y = 0; y < ch; ++y) {
        const uint8_t* s = p.bytes + p.row[y0 + y];
        uint8_t* d = out + static_cast<size_t>(y) * cw;
        int x = 0;
        while (x < x1) {
            int run = 1;
            if ((*s & 0xC0) == 0xC0) run = *s++ & 0x3F;
            const uint8_t v = map[*s++];
            const int a = x > x0 ? x : x0, e = x + run < x1 ? x + run : x1;
            if (e > a) memset(d + (a - x0), v, static_cast<size_t>(e - a));
            x += run;
        }
    }
    return true;
}

} // namespace hdpack
