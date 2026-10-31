// uimod "Longevity Mod Preferences" tab -- a new PrefWin tab with the map-label
// font-scale slider. See prefs.cpp.
#pragma once

// Install the PrefWin build hook + code patches. Call once from Init(), before the
// game reaches desktop_init (Init runs at loader time, so any time in Init is fine).
void InstallPrefsTab();

// Per retrieved message (wheel.cpp's message hook): drops the slider value bubble once the slider is released.
void PrefsBubblePoll();

#include <cstdint>
// The patcher's .pcave2 section as live addresses [lo, hi); false on an unpatched exe.
bool UimodPcave2Range(uintptr_t* lo, uintptr_t* hi);
