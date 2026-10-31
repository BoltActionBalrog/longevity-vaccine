---
name: project-smac-blink-fix
description: Selected-unit blink leaves a solid sliver of any sprite wider than its tile (VANILLA bug, user-confirmed 2026-10-10): the blink erase regenerates only the unit's own tile; fixed in uimod blinkfix.cpp by drawing radius 1
type: project
---

**Symptom:** on the blink's off tick a wide unit sprite (cruiser chassis ~1.3 tile widths, long rovers)
keeps a vertical strip drawn solid; the strip's edge is exactly the tile's left diamond corner (shots
`screenshots\terranx_pracx_3840x2160_20261010/42.png`). Confirmed on the vanilla exe by the maintainer.

**Mechanism:** blink_timer 0x50EA40 toggles g_blink_state 0x9392A8 and calls draw_cursor 0x46AE00 ->
MapWin_draw_radius(x, y, RADIUS 0, mode 2) 0x46A2A0: MapWin_gen_radius regenerates ONE tile (the selected
unit hidden on the off tick), the cursor diamond 0x7D3BE8 goes on top, compute_clip + soft update of that
tile's rect. Pixels the sprite painted outside the tile box on the on tick are never repainted. Same call
shape in MapWin_draw_cursor 0x46AD60 (cursor moves).

**Fix (uimod.dll 3b16c398, `src\uimod\src\blinkfix.cpp`, test `test_blinkfix_sites.py`):** the two
`push 0` radius operands (0x46AEBE, 0x46ADE4) become 1 -- the engine's own MapWin_draw_radius_2 value --
so the tile and its ring are regenerated per tick (9 tiles / 150 ms, negligible). Byte-checked, both exes.
CHANGELOG line added (vanilla bug). Related: [[project-smac-drag-scroll-perf]] (the drag loop's blink
phase is the residual in verify mode), [[project-smac-mouse-scheme-proposals]].
