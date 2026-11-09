// uimod display-mode watchdog: a thread of its own that undoes what the game thread holds (the pointer clip, the
// letterbox backdrop) on a display topology change and on the escape hotkey; it only measures the game thread's
// stalls and releases nothing on one. While the game thread is stalled it cannot take the game window out of the
// topmost band (that request is queued to the stalled thread). It never calls engine or PRACX code. See
// vidwatch.cpp, vidsafety.h.
#pragma once

#include <windows.h>

#include "vidsafety.h"

// The probe the watchdog sends to the game window: our subclass answers it before PRACX sees it.
constexpr WPARAM  kWatchProbeW = 0x55A1F00D;
constexpr LPARAM  kWatchProbeL = 0x0D15C0DE;
constexpr LRESULT kWatchProbeAnswer = 0x5AFE;

// Start the thread (once; from the game thread, outside the loader lock). `clipped` is the game thread's "the
// ClipCursor is ours" flag, `resyncOwed` is set when the game thread should re-state its own state after a release.
// True = the thread came up in time and owns the backdrop window (decided once: a late thread never takes it over).
bool VidWatchStart(HWND game, volatile LONG* clipped, volatile LONG* resyncOwed, const char* hotkey);
void VidWatchStop();                 // the game window is going away (WM_NCDESTROY)
bool VidWatchOwnsBackdrop();         // the watchdog thread owns the backdrop: the game thread never makes its own
HWND VidWatchBackdrop();             // that backdrop, nullptr = none
LONG VidWatchEscapeGen();            // bumped by every escape hotkey press
LONG VidWatchDisplaySeq();           // bumped by every topology event either thread counted
LONG VidWatchBumpDisplaySeq();       // the game thread saw one itself (returns the new value)
HWND CreateBackdropWindow();         // on the calling thread (the watchdog's, or the game's as a fallback)

// The monitors as user32 has them (EnumDisplayMonitors + GetMonitorInfo), from either thread; with `withPaths` also
// each monitor's device interface path (EnumDisplayDevices -- only where a monitor has to be recognised, never on a
// release). `handles` may be null. Returns the count.
int VidEnumMonitors(vidsafety::Monitor* out, HMONITOR* handles, int max, bool withPaths);
