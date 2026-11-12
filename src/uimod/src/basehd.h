#pragma once

// Drop-in HD base sprites: <game>\bases\<faction>_x8.pcx (the base block of <faction>.pcx at 8x, in the faction file's
// palette) replaces the 24 base icons of that faction wherever the game draws a base, each made at exactly the size
// the engine draws the stock one. Byte-checked, cave-free, both exes. See basehd.cpp.

constexpr int kBaseHdDefault = 1;   // [UIMod] BaseHD

void InstallBaseHd();
bool BaseHdAvailable();             // installed: a pack is on disk and both sites passed their byte checks
int  BaseHdGet();
void BaseHdSet(int on);             // live: the map repaints; off frees every HD sprite
void BaseHdSave();
