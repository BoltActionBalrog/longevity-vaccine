#pragma once

// Drop-in HD terrain textures: <game>\terrain\texture_x8.pcx (TEXTURE.PCX at 8x, stock palette and indices) replaces
// the map's ground textures wherever the terrain is drawn (the main map, the base screen, the HUD tile view, the
// Datalinks terraforming page), all at one level for the session (2x, 4x or 8x, from the screen's deepest zoom).
// A piece the pack leaves blank draws as stock. Byte-checked; installed only where the Longevity Preferences tab is.
// Switched off, it holds no memory. See terrainhd.cpp.

constexpr int kTerrainHdDefault = 1;   // [UIMod] TerrainHD

void InstallTerrainHd();
bool TerrainHdAvailable();             // installed: a usable texture_x8.pcx, the Longevity tab, every site passed
int  TerrainHdGet();
void TerrainHdSet(int on);             // live: the map, the HUD and the base screen repaint; off puts the stock textures back
void TerrainHdSave();
