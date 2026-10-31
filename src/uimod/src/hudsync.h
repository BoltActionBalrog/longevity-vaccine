#pragma once

// The HUD unit panel follows the unit the map shows as pending orders, and a resumed turn (a loaded game)
// with a pending unit enters move mode instead of the base game's half-selected view mode. Byte-checked,
// cave-free, both exes. See hudsync.cpp.
void InstallHudSync();
