#pragma once

// The selected unit's blink leaves a sliver of any sprite wider than its tile on the map (base-game bug):
// the blink erase regenerates only the selected tile. Byte-checked, cave-free, both exes. See blinkfix.cpp.
void InstallBlinkFix();
