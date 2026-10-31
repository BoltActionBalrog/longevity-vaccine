// GPU present for the stretched display modes: the 8-bit frame + palette go to the GPU, which scales. See gpuscale.cpp.
#pragma once

#include <windows.h>

// Present the game's 8-bit top-down frame (sw x sh at `bits`, `stride` bytes per row, colours `pal`) scaled into
// hwnd's cw x ch client area. [l,r) x [t,b) is the part of the frame that changed since the last call.
// False = not available / failed (the caller falls back to the CPU resampler); after a failure it stays off.
bool GpuPresent(HWND hwnd, const BYTE* bits, int stride, int sw, int sh, const RGBQUAD* pal,
                int l, int t, int r, int b, int cw, int ch);

// The frame texture no longer matches the backbuffer (the GPU path was skipped for a while): upload it whole next time.
void GpuInvalidate();

// A display event (monitor added / removed, mode, DPI, work area) just happened; callable from any thread. For
// vidsafety::kGpuQuietMs after it the GPU is not touched (no device creation, resize, upload or present): the
// callers' CPU path draws.
void GpuDisplayEvent();

// Lines the engine drew onto the window itself (lineoverlay.h), in frame coordinates: composited over every present
// from now on, scaled with the frame, coloured from the frame's palette. n = 0 clears them.
namespace lineoverlay { struct Line; }
void GpuSetLines(const lineoverlay::Line* lines, int n);

// Present the last uploaded frame again (with the current lines), no upload. False = nothing current to present
// from (no device, a stale frame texture, another window or client size): the caller draws another way.
bool GpuRepresent(HWND hwnd, int cw, int ch);
// GpuRepresent would present (the frame texture is current for this window and client size).
bool GpuCurrent(HWND hwnd, int cw, int ch);
