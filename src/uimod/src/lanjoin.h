// lanjoin.h -- two PCs behind the same router find each other's multiplayer games (DirectPlay TCP/IP) on routers
// without NAT loopback. See lanjoin.cpp / lanjoin_core.h.
#pragma once

// Hooks DirectPlay's TCP/IP provider (dpwsockx.dll) when it loads; changes nothing until DirectPlay's NAT helper
// fails to recognise a machine behind this PC's own router. [UIMod] DirectPlayLanFix=0 turns it off.
// Call once from Init(); both exes.
void InstallLanJoinFix();
