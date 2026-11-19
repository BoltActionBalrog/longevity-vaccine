---
name: project-smac-replay-map-law
description: End-game Replay window map size = option A (engine fit on the scaled window), user-chosen 2026-11-15 after a preview; its deviation from vanilla x g/16 is accepted, not a defect
type: project
---

The end-game Replay window (show_replay 0x5ADBF0, plan `work\_replay_static_map.md`) scales as a popup-family window
(popup g). For its map the maintainer chose **option A** on 2026-11-15, after the A/B/C preview sheet
(`work\_replay_preview\replay_map_options_sheet.png`): scale only the window's local rect, and the builder's own zoom
fit (0x5AD77E) picks the denser zoom by itself. The map tile is 8u px (u integer, MapWin_calculate_dimensions), so A is
off vanilla x g/16 by the fit's quantization: standard map +20 % at 4K (u 6 vs 5), large map up to +118 % at 1080.

**Why:** the maintainer preferred the engine's own crisp fit (the SUPPORT-tab precedent, [[project-smac-base-screen]]) over
B (nearest zoom step, exact at 4K for standard maps) and C (vanilla map enlarged x g/16, exact size, ragged edges).

**How to apply:** do not "fix" the replay map toward vanilla x g/16 or re-propose B/C. Overflow cases (user
2026-11-15, after a rendered comparison): GROW THE WINDOW (4:3 kept) just enough that no map row is clipped, instead
of stepping the zoom down. The engine centres the tile grid with alternate rows 4u further left, so the map child
needs width >= 4u(X+2); e.g. +22 px (1.7%) standard world at g 26, +62 px (4.0%) tiny world at g 31. g <= 16 stays
vanilla (vanilla itself clips ~3 px of the tiny world at 1024x768). The first build's t_rp_zoom step-down (e6adbb3)
is superseded. Still verify in game that z >= -8 (4K standard map) draws no unit/base sprites.
In-game check (user, 2026-11-15) -> two more decisions: (1) vanilla's replay-map row bug fixed at ALL resolutions
(t_rp_rows after MapWin_calculate_dimensions: the top row clamps to -2..+4 from the faction's view centre; at -2
the last row lands half a world left = "tiles in the air", at +1..+4 the top rows are dropped); (2) "keep zoom,
centre map": option A's zoom stays, the map is centred in its child above g 16 (the engine sits it 2u left), so
the clip-free growth is 4u(X+1) (+6 px standard g 26, +30 tiny g 31). The map's share of the window still varies
with the zoom step (72..100%); only option C would make it constant -- the maintainer chose not to.
See (a private note).
