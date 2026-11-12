#pragma once

// Drop-in widescreen Planetary Monument backdrops: <game>\monument\monzoom1/2_<W>x<H>.pcx (near view) and
// farNN_<W>x<H>.pcx (the pyramid stages), in the stock palette, the screen area index 255 like the stock art, painted
// over the whole Monument canvas by the mod's own Monument laws (scaling_laws.mon_*), lined up on the screen the
// milestone picture is drawn in. Above native scale only. Byte-checked, cave-free. See monumenthd.cpp.

constexpr int kMonumentHdDefault = 1;   // [UIMod] MonumentHD

void InstallMonumentHd();
bool MonumentHdAvailable();             // installed: a pack is on disk and the sites passed their byte checks
int  MonumentHdGet();
void MonumentHdSet(int on);             // takes effect the next time the Monument is drawn
void MonumentHdSave();
