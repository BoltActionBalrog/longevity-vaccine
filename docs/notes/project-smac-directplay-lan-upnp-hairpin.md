---
name: project-smac-directplay-lan-upnp-hairpin
description: SMAC TCP/IP Join "Game Not Found" on a LAN = Windows' DirectPlay NAT helper only resolves its OWN machine's UPnP mappings; fix = uimod lanjoin (QueryAddress completion, loopback-gated); USER-VERIFIED on two PCs 2026-11-08, ships in 1.0.0
type: project
---

2026-11-07, desktop (192.168.0.183, Ethernet, hosting) + laptop (192.168.0.143, Wi-Fi, joining):
Join always ended in #NETCONNECT_SESSION_NOT_FOUND (jackal.txt; netconnect_join 0x4E2E50 -> AlphaNet_enum_sessions
0x62E420 = IDirectPlay::EnumSessions vtbl+0x34, flags AVAILABLE, app GUID {02D1B480-D680-11D0-821E-444553540000}).
No central server is involved (DirectPlay TCP/IP = LAN broadcast or a typed address in Windows' own DirectPlay box).

**Root cause (pktmon on both PCs, router UPnP queries, NAT-helper calls from Python):** dpwsockx.dll asks the router
(UPnP, dpnathlp.dll) for a mapping and advertises the router's PUBLIC address; before replying / connecting it calls
IDirectPlayNATHelp::QueryAddress (vtable slot 9) to map a public address back to a LAN machine -- but the helper
resolves only mappings to its OWN machine (another PC's -> 0x8015F050 NOMAPPING), so the host replies to the public
address and a router without NAT loopback (this consumer router's miniupnpd refuses hairpin) drops it.
dpwsockx QueryAddress sites (26100): reply 0x5df06b9f (in place in the request header), connect 0x5df02c11,
player SP data 0x5df053e8/0x5df05410 (stored DPSET_LOCAL), DPSP_Open 0x5df0817a, enum-to-address 0x5df0952f
(port 47624; S_OK -> BROADCAST).

**Fix (user asked "build the mod-level solution"; six independent audits incl. player compatibility; USER-VERIFIED connecting both directions on two PCs, release gate passed 2026-11-08; ships in 1.0.0):** uimod
src\lanjoin.cpp / lanjoin_core.h (Resolve) / lanjoin.h, Init after InstallInterludeKeyFix. Hooks dplayx IAT
LoadLibraryA/W -> dpwsockx IAT GetProcAddress -> wraps DirectPlayNATHelpCreate -> patches vtable slot 9 in place.
Translates only when: helper said NOMAPPING/SERVERNOTAVAILABLE, port != 47624, query == the router's public address
(own UPnP client, gateway-only), router maps it to a machine on this PC's subnets, that machine's game ACCEPTS on its
private address, and the same connect through the public address FAILS -- for TCP all three measured live in that query (only "loops back" is served from cache; UDP reuses a TCP-measured verdict for the same machine, 60 s). So it
only engages where two LAN PCs cannot play today. [UIMod] DirectPlayLanFix=0 turns it off. Tests:
work\tests\test_lanjoin_core.py (C++ harness lanjoin_selftest.cpp, scripted Env); live harness work\tests\lanjoin_livetest.cpp and
test_lanjoin_live.py. CHANGELOG lines under 1.0.0 / Multiplayer. Both PCs need the same uimod.dll.
uimod.log never shows a non-LAN address (players attach it to public issues): LogIPv4 / IsLanAddress in lanjoin_core.h,
the router's public address is "<router-public>" (source-release audit 2026-11-08; guard test_no_log_line_formats_an_unmasked_address).
Compatibility: ws2_32/iphlpapi DELAY-loaded and WSAStartup only in HookDpwsockx (single player never loads Winsock; guard test_winsock_is_not_loaded_at_game_start); vtable patched only for IIDs 3B743591-... / 154940B7-...; Win7 DirectPlay unverified.
For a remote friend: type the router's public IP in Windows' address box (UPnP makes that work).
Related: [[project-smac-netwin-lobby]].
