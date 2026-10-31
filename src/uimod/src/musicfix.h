#pragma once

// In-game music kept playing over the main menu after leaving a game (base-game bug): nothing on the
// quit-to-menu path stops it. Byte-checked, cave-free, both exes. See musicfix.cpp.
void InstallMusicFix();
