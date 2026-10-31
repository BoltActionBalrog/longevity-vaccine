// thinkertext.h -- Thinker's own UI text, placed at our scale (PRACX + Thinker target). See thinkertext.cpp.
#pragma once

// Re-anchor the text Thinker draws itself into the scaled base screen (its satellite / stockpile / pop-size /
// nerve-staple lines sit at native coordinates otherwise). Call after InstallThinkerCompat(). A no-op without
// thinker.dll; self-disables with one log line on any other Thinker build or any unexpected byte.
void InstallThinkerText();
