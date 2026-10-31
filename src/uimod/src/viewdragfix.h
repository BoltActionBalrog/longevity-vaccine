#pragma once

// In view mode (V) a left drag on a unit's square still armed the move line, and the release only selected
// the unit (base-game bug: the line promised a move that never happened). The view-mode arm now cancels like a
// plain click. Byte-checked, cave-free, both exes, every control scheme. See viewdragfix.cpp.
void InstallViewDragFix();
