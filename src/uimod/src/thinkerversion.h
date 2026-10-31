// thinkerversion.h -- the "this release was built for Thinker Mod X" warning. See thinkerversion.cpp.
#pragma once

// Call once from Init(), right after InstallThinkerCompat() (needs ThinkerLoaded()/ThinkerRange()) and before any
// game window exists. A no-op without thinker.dll, or when its build is the supported one.
void ThinkerVersionWarning();
