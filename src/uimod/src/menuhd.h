#pragma once

// The HD main menu and planet setup: <game>\menu\hd\ (a panorama, the 27 custom_planet strips and the 3 moons at 3x)
// composed at any resolution by one uniform scale (scaling_laws.menu_hd_layout). Byte-checked, cave-free, both exes.
// See menuhd.cpp.

constexpr int kMenuHdDefault = 1;   // [UIMod] MenuHD

void InstallMenuHd();
bool MenuHdAvailable();             // installed: menu\hd\space_x3.pcx is on disk and every site passed its byte check
int  MenuHdGet();
void MenuHdSet(int on);             // takes effect the next time the menu or a planet preview is drawn
void MenuHdSave();
