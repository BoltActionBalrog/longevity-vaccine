// thinkerversion.h -- the Thinker Mod startup check: is thinker.dll in the process, and is it the build this release
// is pinned to. See thinkerversion.cpp.
#pragma once

#include <cstdint>

// Call once, as early as a box can be shown:
//   preInit = true   from PreInit(), after the DPI / ghosting setup and BEFORE VidModePreInit: the shipped path.
//   preInit = false  from Init() when PreInit never ran (the one-phase developer exe): no dialog there, only a box.
// A second call is a no-op. On the pinned build, or without thinker.dll, it shows nothing. On any other build it
// shows the three-button dialog; "Update now" starts the resident installer and ENDS THE PROCESS.
void ThinkerStartupCheck(bool preInit);

// thinker.dll is in the process (decided once, by ThinkerStartupCheck).
bool ThinkerPresent();

// thinker.dll is in the process AND it is the pinned build. Everything of ours that calls into, chains into or
// patches thinker.dll is installed only when this is true ("reduced mode" otherwise).
bool ThinkerOnPin();

// thinker.dll's image range [lo, hi) when present; false otherwise.
bool ThinkerImageRange(uintptr_t* lo, uintptr_t* hi);

// How the loaded Thinker is named to the player, for the in-game update offer (update.cpp): {RUN} ("Thinker Mod 5.4",
// "a development build of Thinker Mod", ...) and {YOURS} ("your Thinker Mod 5.4", ...). `against` is the version it is
// being compared with (a dotted version; the same number reads "a different build of Thinker Mod X"), or null.
// False when thinker.dll is not in the process: the caller then has no label to build them from.
bool ThinkerWords(const char* against, char* run, size_t runCap, char* yours, size_t yoursCap);

// A memory patch the game cannot run safely without did not apply (thinkercompat.cpp): say so and end the process.
[[noreturn]] void ThinkerCannotStart();
