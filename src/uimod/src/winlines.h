// uimod: the engine's window lines (tutorial pointer, console crosshair) while the frame is stretched to the client.
// See winlines.cpp / lineoverlay.h.
#pragma once

#include <windows.h>

// Detours Win_window_line_raw 0x5F2AC0 (byte-checked). PRACX exe only (called from InstallVidMode once bound).
bool InstallWinLines();

// From the present path, per flip of frame rect [l,r) x [t,b): `stretched` = this flip is presented through the
// scaler (the frame stretched to a client of another size). Not stretched: the record is dropped (the engine's
// lines are on the window itself again); stretched: the lines' pixels under the rect are repainted away.
void WinLinesOnFlip(bool stretched, int l, int t, int r, int b);

// From the WH_GETMESSAGE hook (the game thread, between dispatches): the GPU re-present a batch of line draws owes.
void WinLinesPoll();
