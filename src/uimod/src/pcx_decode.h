#pragma once
// pcx_decode.h -- the one 8-bit PCX decoder the HD art hooks share (objecthd.cpp, menuhd.cpp).
//
// They decode their packs here, into plain memory, instead of through Buffer_load_pcx: a pcx-loaded Buffer must never
// be destroyed (Buffer_close DeleteObject's the GDI objects it holds; basehd.cpp), and an 8x sheet kept for the
// session costs tens of MB in a 32-bit process. The caller frees the pixels with free().

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace pcx {

// Width / height of an 8-bit one-plane PCX from its header, or false.
inline bool Size(const char* path, int* w, int* h)
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return false;
    uint8_t hdr[128];
    const bool ok = fread(hdr, 1, sizeof hdr, f) == sizeof hdr;
    fclose(f);
    if (!ok || hdr[0] != 10 || hdr[3] != 8 || hdr[65] != 1) return false;
    *w = (hdr[8] | hdr[9] << 8) - (hdr[4] | hdr[5] << 8) + 1;
    *h = (hdr[10] | hdr[11] << 8) - (hdr[6] | hdr[7] << 8) + 1;
    return true;
}

// Decode an 8-bit one-plane RLE PCX into a malloc'd w x h index image (row 0 = top). wantW / wantH > 0 demand that
// size. pal (optional, 768 bytes) receives the file's 256-colour palette (the 0x0C-marked block at the end).
// Null on any mismatch, a short file or no memory.
inline uint8_t* Decode(const char* path, int* outW, int* outH, uint8_t* pal = nullptr, int wantW = 0, int wantH = 0)
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return nullptr;
    uint8_t hdr[128];
    uint8_t* img = nullptr;
    if (fread(hdr, 1, sizeof hdr, f) == sizeof hdr && hdr[0] == 10 && hdr[2] == 1 && hdr[3] == 8 && hdr[65] == 1) {
        const int w = (hdr[8] | hdr[9] << 8) - (hdr[4] | hdr[5] << 8) + 1;
        const int h = (hdr[10] | hdr[11] << 8) - (hdr[6] | hdr[7] << 8) + 1;
        const int bpl = hdr[66] | hdr[67] << 8;
        if (w > 0 && h > 0 && bpl >= w && (wantW <= 0 || w == wantW) && (wantH <= 0 || h == wantH)) {
            img = static_cast<uint8_t*>(malloc(static_cast<size_t>(w) * h));
            uint8_t* line = static_cast<uint8_t*>(malloc(bpl));
            bool ok = img && line;
            for (int y = 0; ok && y < h; ++y) {
                for (int x = 0; ok && x < bpl;) {
                    int c = fgetc(f);
                    if (c == EOF) { ok = false; break; }
                    int run = 1;
                    if ((c & 0xC0) == 0xC0) {
                        run = c & 0x3F;
                        c = fgetc(f);
                        if (c == EOF) { ok = false; break; }
                    }
                    for (; run > 0 && x < bpl; --run) line[x++] = static_cast<uint8_t>(c);
                }
                if (ok) memcpy(img + static_cast<size_t>(y) * w, line, w);
            }
            free(line);
            if (ok && pal) {
                ok = fseek(f, -769, SEEK_END) == 0 && fgetc(f) == 0x0C && fread(pal, 1, 768, f) == 768;
            }
            if (!ok) { free(img); img = nullptr; }
            else { *outW = w; *outH = h; }
        }
    }
    fclose(f);
    return img;
}

} // namespace pcx
