#pragma once

// The base screen's unit-row scroll arrows stayed up over the screen that replaced it (base-game bug: a stray arrow
// in the Design Workshop's unit row when opened from a base). Byte-checked vtable-slot wrapper, cave-free, both exes.
// See rowarrowfix.cpp.
void InstallRowArrowFix();
