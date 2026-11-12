#pragma once

// Drop-in HD map objects: <game>\terrain\ter1_x8.pcx, ter1wreck_x8.pcx and units_x8.pcx (TER1, TER1WRECK and UNITS.PCX
// at 8x, stock palette indices) replace the monolith, pods, resource specials, terraforming, the Unity wreck and the
// native life / artifact sprites on the main map, each made at exactly the size the engine draws the stock one.
// Byte-checked, cave-free, both exes. See objecthd.cpp.

constexpr int kObjectHdDefault = 1;   // [UIMod] ObjectHD

void InstallObjectHd();
bool ObjectHdAvailable();             // installed: a pack is on disk and every site passed its byte check
int  ObjectHdGet();
void ObjectHdSet(int on);             // live: the map repaints; off frees every HD sprite
void ObjectHdSave();
