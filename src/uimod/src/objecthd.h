#pragma once

// Drop-in HD map objects: <game>\terrain\ter1_x8.pcx and ter1wreck_x8.pcx (TER1 and TER1WRECK.PCX at 8x, stock palette
// and indices) replace the monolith, pods, resource specials, terraforming, landmarks and the Unity wreck wherever the
// game draws them, each made from its cell at the size the engine gives the stock cell (usually within a pixel of the
// stock sprite). Art a pack does not supply, or that cannot be used, is drawn exactly as stock. Byte-checked;
// installed only where the Longevity Preferences tab is. Switched off, it holds no memory. See objecthd.cpp.

constexpr int kObjectHdDefault = 1;   // [UIMod] ObjectHD

void InstallObjectHd();
bool ObjectHdAvailable();             // installed: a usable sheet is on disk, the Longevity tab is, every site passed
int  ObjectHdGet();
void ObjectHdSet(int on);             // live: the map, the HUD and the base screen repaint; off frees everything, on re-proves
void ObjectHdSave();
