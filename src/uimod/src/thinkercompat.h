// thinkercompat.h -- the "apply after Thinker" pass (PRACX + Thinker target). See thinkercompat.cpp.
#pragma once
#include <cstdint>

// Writes the sites the patcher left for run time under Thinker, restores the ones Thinker clobbered where the
// decision is ours, chains our base-screen thunks into Thinker's functions where it is both. Logs one line per
// site. Safe (and needed) without Thinker too: a Thinker-folder exe started directly still gets its bytes.
void InstallThinkerCompat();

// True iff thinker.dll is loaded in this process (decided once, at InstallThinkerCompat).
bool ThinkerLoaded();

// thinker.dll's image range [lo, hi) when loaded; false otherwise.
bool ThinkerRange(uintptr_t* lo, uintptr_t* hi);
