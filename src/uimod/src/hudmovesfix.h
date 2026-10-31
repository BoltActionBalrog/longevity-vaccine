#pragma once

// The HUD's "Moves" readout stays stale after a go-to the engine gave up on (base-game bug): the cancel
// path in Console_veh_turn never repaints the unit panel. Byte-checked, cave-free, both exes. See hudmovesfix.cpp.
void InstallHudMovesFix();
