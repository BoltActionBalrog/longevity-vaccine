// interludekey.h -- the keystroke that closes a story interlude no longer leaks to the map (base-game bug). See
// interludekey.cpp.
#pragma once

// Byte-checked (the InterludeWin class), a thread-local message hook; works on the unpatched and the PRACX exe.
// Call once from Init() on the game's UI thread.
void InstallInterludeKeyFix();
