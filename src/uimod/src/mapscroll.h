// uimod smooth map scrolling under PRACX ([UIMod] SmoothScroll, default on): PRACX's drag / edge scroll calls
// MapWin_draw_map (a FULL map render, 85-120 ms at 4K) on every scroll step because the engine's own
// shift-and-strip scroll path refuses sub-tile pixel offsets. This module takes over PRACX's per-step redraw entry
// (ACADDRESSES_T.pfncRedrawMap) and, while PRACX is scrolling, shifts the map canvas by the true pixel delta
// (whole-tile lattice delta + the change in sub-tile offset), fills the exposed strips, and re-renders only the
// tiles in those strips through the engine's own filtered MapWin_gen_map -- the same path the engine uses for a
// whole-tile recentre. Anything unusual (zoom change, view spanning or nearly spanning a round map, a shift as
// big as the window, an engine go-to drag, a canvas mid-draw with a narrowed clip) falls back to the full redraw,
// and the scroll's end (PRACX's pfncMoveMap) settles with one full draw. [UIMod] MapScrollVerify=1 (with
// DebugLog=1) redraws fully after every step and logs the number of pixels that differ. See mapscroll.cpp.
#pragma once

#include <windows.h>

constexpr int kSmoothScrollDefault = 1;

// Byte-checks prax.dll's address table + wrapper thunks and the engine sites, reads the ini keys, installs the
// table hook. Call after InstallPraxDrag (needs PRACX). Both exes load the DLL; without PRACX this is a no-op.
void InstallMapScroll(bool pracx);

bool SmoothScrollAvailable();
int  SmoothScrollGet();
void SmoothScrollSet(int on);    // live
void SmoothScrollSave();
