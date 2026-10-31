// Smoke test for src\uimod\src\gpuscale.cpp: a real window, a synthetic 3840x2160 8-bit frame, a few presents
// (full, dirty-rect, resized). Verifies the D3D11 path comes up and keeps presenting on this machine, then
// captures the window's centre pixel to check the palette lookup end to end. Build + run: run_smoke.bat
#include <windows.h>
#include <cstdio>
#include <vector>

#include "../../../src/uimod/src/gpuscale.h"
#include "../../../src/uimod/src/lineoverlay.h"

void UimodLog(const char* msg) { std::fputs(msg, stdout); }

int main()
{
    SetProcessDPIAware();
    WNDCLASSA wc = {};
    wc.lpfnWndProc = DefWindowProcA;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.lpszClassName = "gpuscaleSmoke";
    RegisterClassA(&wc);
    HWND hwnd = CreateWindowExA(WS_EX_TOPMOST, wc.lpszClassName, "gpuscale smoke", WS_POPUP | WS_VISIBLE, 40, 40, 1431, 828,
                                nullptr, nullptr, wc.hInstance, nullptr);
    if (!hwnd) { std::puts("FAIL: no window"); return 1; }

    const int sw = 3840, sh = 2160;
    std::vector<BYTE> frame(static_cast<size_t>(sw) * sh, 7);      // index 7 everywhere
    RGBQUAD pal[256] = {};
    pal[7].rgbRed = 200; pal[7].rgbGreen = 100; pal[7].rgbBlue = 50;
    pal[9].rgbRed = 10; pal[9].rgbGreen = 20; pal[9].rgbBlue = 250;

    bool ok = GpuPresent(hwnd, frame.data(), sw, sw, sh, pal, 0, 0, sw, sh, 1431, 828);
    std::printf("full present: %d\n", ok);
    for (int y = 900; y < 1300 && ok; ++y)                          // a dirty block of index 9 around the centre
        for (int x = 1700; x < 2200; ++x) frame[static_cast<size_t>(y) * sw + x] = 9;
    ok = ok && GpuPresent(hwnd, frame.data(), sw, sw, sh, pal, 1700, 900, 2200, 1300, 1431, 828);
    std::printf("dirty present: %d\n", ok);
    SetWindowPos(hwnd, nullptr, 0, 0, 2880, 1620, SWP_NOMOVE | SWP_NOZORDER);
    ok = ok && GpuPresent(hwnd, frame.data(), sw, sw, sh, pal, 0, 0, 0, 0, 2880, 1620);
    std::printf("resized present: %d\n", ok);

    for (int i = 0; i < 5 && ok; ++i) { ok = GpuPresent(hwnd, frame.data(), sw, sw, sh, pal, 0, 0, 0, 0, 2880, 1620); Sleep(50); }
    {   // the case that crawled: a FULL 4K frame re-presented per mouse move
        const DWORD t0 = GetTickCount();
        for (int i = 0; i < 100 && ok; ++i) ok = GpuPresent(hwnd, frame.data(), sw, sw, sh, pal, 0, 0, sw, sh, 2880, 1620);
        std::printf("100 full-frame uploads + presents: %lu ms\n", static_cast<unsigned long>(GetTickCount() - t0));
    }
    Sleep(300);                                                       // let DWM compose
    MSG m;
    while (PeekMessageA(&m, nullptr, 0, 0, PM_REMOVE)) DispatchMessageA(&m);
    RECT wr; GetWindowRect(hwnd, &wr);
    HDC scr = GetDC(nullptr);
    const COLORREF mid = GetPixel(scr, wr.left + 1440, wr.top + 810);  // inside the index-9 block
    const COLORREF edge = GetPixel(scr, wr.left + 100, wr.top + 100);  // index 7
    ReleaseDC(nullptr, scr);
    std::printf("centre rgb=%d,%d,%d (want 10,20,250)  corner rgb=%d,%d,%d (want 200,100,50)\n",
                GetRValue(mid), GetGValue(mid), GetBValue(mid), GetRValue(edge), GetGValue(edge), GetBValue(edge));
    const bool colours = mid == RGB(10, 20, 250) && edge == RGB(200, 100, 50);

    // The window-line overlay (lineoverlay.h): a 3-px index-9 line along frame row 100 lands on client row 75 (x 0.75),
    // an erase rect over its left part repaints that part away, and clearing the lines restores the frame.
    auto pixel = [&](int x, int y) {
        Sleep(200);
        while (PeekMessageA(&m, nullptr, 0, 0, PM_REMOVE)) DispatchMessageA(&m);
        HDC s = GetDC(nullptr);
        const COLORREF c = GetPixel(s, wr.left + x, wr.top + y);
        ReleaseDC(nullptr, s);
        return c;
    };
    lineoverlay::Line ln = {};
    ln.x0 = 0; ln.y0 = 100; ln.x1 = sw - 1; ln.y1 = 100; ln.color = 9; ln.width = 3; ln.style = 2;   // PS_DOT, drawn solid at 3 px
    GpuSetLines(&ln, 1);
    ok = ok && GpuRepresent(hwnd, 2880, 1620);
    const COLORREF onLine = pixel(100, 75), offLine = pixel(100, 85);
    ln.nErase = 1; ln.erase[0] = { 0, 0, 400, sh };          // frame x [0,400) -> client x [0,300)
    GpuSetLines(&ln, 1);
    ok = ok && GpuRepresent(hwnd, 2880, 1620);
    const COLORREF erased = pixel(100, 75), kept = pixel(1000, 75);
    GpuSetLines(nullptr, 0);
    ok = ok && GpuRepresent(hwnd, 2880, 1620);
    const COLORREF cleared = pixel(1000, 75);
    std::printf("line: on=%06lX (want FA140A) off=%06lX erased=%06lX kept=%06lX cleared=%06lX (want 3264C8)\n",
                static_cast<unsigned long>(onLine), static_cast<unsigned long>(offLine), static_cast<unsigned long>(erased),
                static_cast<unsigned long>(kept), static_cast<unsigned long>(cleared));
    const COLORREF blue = RGB(10, 20, 250), base = RGB(200, 100, 50);
    // A present that bypassed the GPU leaves its frame copy stale: no re-present from it until a full upload.
    const bool current = GpuCurrent(hwnd, 2880, 1620);
    GpuInvalidate();
    const bool staleRefused = !GpuCurrent(hwnd, 2880, 1620) && !GpuRepresent(hwnd, 2880, 1620);
    ok = ok && GpuPresent(hwnd, frame.data(), sw, sw, sh, pal, 0, 0, 0, 0, 2880, 1620);   // stale -> uploads it whole
    const bool recovered = GpuCurrent(hwnd, 2880, 1620) && !GpuCurrent(hwnd, 2000, 1620);
    std::printf("stale: current=%d refused=%d recovered=%d\n", current, staleRefused, recovered);
    const bool lines = onLine == blue && offLine == base && erased == base && kept == blue && cleared == base &&
                       current && staleRefused && recovered;
    std::puts(ok && colours && lines ? "PASS" : "FAIL");
    DestroyWindow(hwnd);
    return ok && colours && lines ? 0 : 1;
}
