#pragma once

// Drop-in HD base sprites: <game>\bases\<faction>_x8.pcx (the base block of <faction>.pcx at 8x, in the faction file's
// palette) replaces that faction's base icons wherever the game draws a base, each made from its cell at the size the
// engine gives the stock cell (the drawn base is usually within a pixel of the stock one). Art a pack does not supply,
// or that cannot be used, is drawn exactly as stock. Byte-checked; installed only where the Longevity Preferences tab
// is. Switched off, it holds no memory. See basehd.cpp.

constexpr int kBaseHdDefault = 1;   // [UIMod] BaseHD

void InstallBaseHd();
bool BaseHdAvailable();             // installed: a usable pack is on disk, the Longevity tab is, both sites passed
int  BaseHdGet();
void BaseHdSet(int on);             // live: the map, the HUD and the base screen repaint; off frees everything
void BaseHdSave();
