#pragma once

// Drop-in HD map objects: <game>	errain	er1_x8.pcx (TER1.PCX at 8x, stock palette indices) replaces the monolith,
// pods, resource specials and terraforming sprites on the main map at every zoom.
// Byte-checked, cave-free; [UIMod] ObjectHD=0 turns it off. See objecthd.cpp.
void InstallObjectHd();
