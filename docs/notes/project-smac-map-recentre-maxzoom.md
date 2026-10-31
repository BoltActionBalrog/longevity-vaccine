---
name: project-smac-map-recentre-maxzoom
description: Map mangled at PRACX whole-map zoom when the ENGINE recentres (AI turn); MapWin_draw_map scroll-blit path + post-calc guard fix
type: project
---

**CLOSED 2026-09-20: exe af282d88 (group map_recentre_fullredraw) USER-VERIFIED ("Fix landed, no regressions"), CHANGELOG line added, committed.** Cause came from static analysis (no runtime trace was needed). Thinker compat: no site overlap (Thinker write_calls 0x46A5A9 + the 4 gen_map calls; ours starts at 0x46A5AE) and its mod_MapWin_focus already covers the same bug.

Report: shot 20260920 @4K — after an AI turn pulled the camera at PRACX's max zoom-out: stale close-zoom rectangle, black area with labels only, one correct band. Mouse scrolling at that zoom is fine.

Mechanism: `MapWin_focus` 0x46B310 (every engine recentre; `Console_focus` 0x5108A0 <- enemy_move, battle_fight_2, alien_move...) sets Console+0x21A44 `drawOnlyCursor` = 1 around `MapWin_set_center` 0x46B1F0 -> `MapWin_draw_map` 0x46A550, which then SCROLL-BLITS: `Buffer_copy_4` self-copy (0x46A93B) by the old->new tile pixel delta, `GraphicWin_fill_3(..,0)` over the exposed strips, `MapWin_gen_map` 0x469CA0 for the strips only. Vanilla's guard (pixel offset +0x1DDAC/+0x1DDB0 != 0 -> flag 0 -> full redraw) sits at 0x46A55D, BEFORE `MapWin_calculate_dimensions`; when the view spans the map (OddX+EvenX >= mapW) the strip maths breaks (raw tile delta vs tile_to_pixel's wrap-normalised one; "delta > visible width" escape @0x46A98A unreachable) and the letterbox offset can be exactly 0. PRACX hooks only calculate_dimensions (5 sites) + gen_map (4 sites) + the zoom key; its own scroll always redraws fully + flips the whole screen. Thinker's equivalent fix: `mod_MapWin_focus` (gui.cpp:1344).

Fix: site `MapWin_draw_map.postcalc_guard` 0x46A5AE (the cmp right after the calc call; PRACX stomps only 0x46A5AA..AD) -> `thunk_drawmap_fullguard` pcave2 0x5CA8 (71 B): clear the flag when the post-calc pixel offset != 0 or the view spans the map on either axis, replay the cmp, resume 0x46A5B4. `scripts\assemble_mapguard.py`, `tests\test_mapguard_asm_parity.py`. Same width predicate as `WorldWin_draw_box.gate` ([[project-smac-hud-scaling]] minimap box).

If mangling survives the fix: the full-redraw branch / flip rect is implicated; observe at `MapWin_draw_map` ENTRY only (0x46A5AE is a call-return address, [[feedback-frida-attach-branch-target]]).
