// Offline render of the uimod post-movie caption (src\uimod\src\caption.cpp) -- no game.
// Usage: caption_harness <movlist.txt> <movie> <scrW> <scrH> <nativeW> <nativeH> <out.bmp>
// Fills the aspect-fit movie rect with a flat dark frame, runs the caption, writes a 32-bit BMP,
// and prints the dst rect + k so the checker can map back to native 640x480 space.
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../../../src/uimod/src/caption.h"

int main(int argc, char** argv)
{
    if (argc < 8) { fprintf(stderr, "args\n"); return 2; }
    const int W = atoi(argv[3]), H = atoi(argv[4]), nw = atoi(argv[5]), nh = atoi(argv[6]);
    CaptionTestOverride(argv[1]);

    double s = (double)W / nw; if ((double)H / nh < s) s = (double)H / nh;   // movie.cpp FitRect
    const int dw = (int)(nw * s + 0.5), dh = (int)(nh * s + 0.5);
    RECT dst{ (W - dw) / 2, (H - dh) / 2, (W - dw) / 2 + dw, (H - dh) / 2 + dh };

    HDC dc = CreateCompatibleDC(nullptr);
    BITMAPINFO bi{}; bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = W; bi.bmiHeader.biHeight = -H; bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HBITMAP bm = CreateDIBSection(nullptr, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    SelectObject(dc, bm);
    memset(bits, 0, (size_t)W * H * 4);
    for (int y = dst.top; y < dst.bottom; ++y) {
        unsigned* row = (unsigned*)bits + (size_t)y * W;
        for (int x = dst.left; x < dst.right; ++x) row[x] = 0x000A1E1E;   // dark teal "last frame"
    }

    int presents = 0;
    CaptionTarget t{ dc, W, H, dst, nw, nh };
    RunMovieCaption(argv[2], t, [&]() { ++presents; }, []() { return false; });
    GdiFlush();

    BITMAPFILEHEADER fh{}; fh.bfType = 0x4D42; fh.bfOffBits = sizeof fh + sizeof(BITMAPINFOHEADER);
    fh.bfSize = fh.bfOffBits + (DWORD)((size_t)W * H * 4);
    FILE* f = nullptr; fopen_s(&f, argv[7], "wb");
    if (!f) return 3;
    fwrite(&fh, sizeof fh, 1, f); fwrite(&bi.bmiHeader, sizeof(BITMAPINFOHEADER), 1, f);
    fwrite(bits, 1, (size_t)W * H * 4, f); fclose(f);

    printf("dst=%ld,%ld,%ld,%ld k=%.6f presents=%d\n", dst.left, dst.top, dst.right, dst.bottom,
           (double)dw / nw, presents);
    return 0;
}
