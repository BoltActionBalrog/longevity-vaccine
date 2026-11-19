// pracxfocus.h -- the game window keeps keyboard focus after PRACX's Preferences panel closes (PRACX bug on Wine),
// and Esc closes that panel after one of its buttons was clicked. See pracxfocus.cpp.
#pragma once

// A thread-local message hook; installed only when prax.dll is loaded. Call once from Init() on the game's UI thread.
void InstallPracxFocusFix(bool pracx);
