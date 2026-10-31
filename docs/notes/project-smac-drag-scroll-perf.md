---
name: project-smac-drag-scroll-perf
description: PRACX drag/edge scroll latency arc (2026-10-10): why (full MapWin_draw_map per step; units pass = per-unit Caviar voxel render + whole-1024^2 composites), the engine's own shift-and-strip scroll path and why PRACX never gets it, fix 1 (caviar_dirty_rect, baked 62d84688 after audit) and fix 2 (DLL mapscroll.cpp: canvas memmove + strip gen_map; audited + COMMITTED 2aba397, user: very smooth, 38-45 steps/s vs 10-14; audit + commit pending)
type: project
---

**Measured (hook_dragscroll.js v4, 4K):** every PRACX drag / edge-scroll step is ONE full MapWin_draw_map 0x46A550:
terrain pass ~30 ms (per-tile Texture_draw* + 18 Sprite_draw_3, no cache), units+bases pass 8-100 ms scaling
with units on screen (over a crowded front ~100 ms pristine / 120+ ours), base names 2-8 ms, Win_update_screen
1.5-4 ms, present 5.5 ms => 6-20 steps/s, the map trails the pointer by 300-600 px. Per-redraw cost is the
SAME for keyboard scroll / recentre (one jump reads as instant); the drag just needs 10+ redraws/s. PRACX's loop
already uses the newest pointer (lag = exactly one render). Thinker's smooth_scrolling is a port of the same loop.

**Why units cost that much (vanilla):** MapWin_draw_vehicles 0x466CA0 runs per TILE (veh_at/base_at exit early on
the MapSquare +8 'unit here'/'base here' bits: scans ~0.1 ms); the cost is veh_draw 0x5594F0 -> vehdraw_draw
0x4C12A0 = a fresh Caviar VOXEL render per unit per redraw (construct_vehicle + Caviar_draw 0x617230; no cache):
whole-target keyed Buffer_draw_2 @0x6175F4, whole-target2 software table composite Buffer_draw_dest_source_2
@0x6175AC (map draws pass flag ((state&0x2000)|0x1000)>>12 -> bit 2 clear -> Caviar +0xA4 = 1 -> always), and
Caviar_reset's whole-target2 Buffer_fill_2 @0x6184BF. OUR +20-40 ms: dw_scale option E grew both targets
256^2 -> 1024^2 GLOBALLY (0x6188B2 imm 0x100 -> 0x400) = 16x the pixel traffic per map unit.

**Engine facts:** PRACX removes DirectDraw ("Die DDraw Die!", pracx.cpp:2463) -> every Buffer primitive takes
its software path: Buffer_draw_2 0x5D855D.. (-> Sprite_draw_2 0x5E4B4A, not Sprite_draw_4) builds the sprite view g_buffer_blit_sprite 0x9B3A50 from the
SOURCE's +0x54 data / +0x4A8 stride / +0x80 w / +0x84 -h only (+0x58 surface == 0, +0x50/+0x6C lock
bookkeeping) and calls Sprite_draw_4 0x5E9D44; Buffer_draw_dest_source_2 0x5D8EE0 (RET 0x1C) the same with a
table. The engine tracks each target's drawn extent: 0x9B9690..9C (target) and 0x9BB438..44 (target2),
UnionRect (import 0x669328) per rasterised object, EXCLUSIVE right/bottom, zeroed by Caviar_reset 0x6184E6..
0x618510 AFTER its fills; outside the rects the targets hold the background (key 9 / 0). Buffer_draw_2's ENTRY
0x5D84C0 is our t_mon_restripe detour (keyed on the two Monument canvases; pass-through for everything else) --
NOT a Frida host. Caviar_overlay 0x6171A0 (armor type 5) fills the WHOLE target with bg, draws with flag|8
(which skips the composite + reset inside Caviar_draw), table-draws it, refills 9, resets -- untouched by fix 1.

**Fix 1 = caviar_dirty_rect (BAKED 2026-10-10, exe 62d84688 after the independent review; src scripts/assemble_cavdirty.py; Unicorn parity
test_cavdirty_asm_parity.py; pcave2 0x30000 -> 0x31000):** t_cav_blit / t_cav_table / t_cav_fill2 rewrite the
source Buffer's +0x54/+0x80/+0x84 (+0x50 latch) to the clamped rect (target2: dilated +1 r/b, raw-empty check) around the ENGINE's own call and restore; null data -> engine path; NB the new sites live in their OWN yaml block (the dw_bake splice would drop them) (pixel-identical
by construction; 1:1 only -- a scaled sub-rect moves the stretch phase; DW/picker dst hand off to
thunk_dw_shim). In-game A/B + the 'pixels outside bbox == background' check: hook_cavdirty.js. Expect the units
pass below pristine (46 ms) in dense views.

**Fix 2 = BUILT as option (2) below, `src\uimod\src\mapscroll.cpp` (2026-10-10, audited, COMMITTED+PUSHED 2aba397 as DLL ec67341a,
SmoothScroll stays ini-only by user decision; verify runs clean -- residual = the selected-unit cursor diamond PRACX's full redraw omits + flag
blink phase; profile 38-45 steps/s, gen_map 8-14 ms/step vs 80-95).** Lessons that cost a day: (a) the terrain
dither has a 2-ROW phase on the dest row -> an odd dy is nudged 1 px toward zero via Console+0x1DDB0
([[feedback-map-dither-row-phase]]); (b) Buffer_copy_4 self-blit crashes on odd widths (backward byte remainder
reads data-1, [[feedback-buffer-copy4-backward-remainder]]) -> row-wise memmove; (c) exposed strips fill with 0x41
(engine clear colour), not 0; (d) ONE strip per gen_map call with the other rect zeroed (the engine's corner dance
keeps the y rect live during the x pass -> whole-band cost); (e) the profiler's gen_map attach must be DEFERRED
past the DLL's init-time Bind() memcmp of the 0x469CA0 prologue, or the feature disables itself under the trace and
you profile PRACX's full redraw twice over (hook_dragscroll.js attaches from the first Win_update_screen call).
Ini: `[UIMod] SmoothScroll` (default 1), `MapScrollVerify` (debug full-redraw diff; leaves it SLOW -- check the
`installed ... verify=` log line first). The original analysis follows.

**Fix 2 design notes: extend the engine's scroll path to sub-tile offsets.** MapWin_draw_map has a shift-and-
strip mode gated on Console+0x21A44 ('drawOnlyCursor'): compares the new tile origin (+0x1DDA4/+0x1DDA8, written
by calculate_dimensions 0x462980) with the pre-call copy, self-blits the window-sized canvas (vbase+0x444) with
Buffer_copy_4 @0x46A93B by tile_to_pixel(old)-tile_to_pixel(new) (+ a 4-corner get_alt average on y), fills the
exposed strips (GraphicWin_fill_3 x3), writes tile rects +0x21A48..54 / +0x21A58..64, then gen_map 0x469CA0 once
or twice under Buffer_set_clip (0x46ABD1 / 0x46AC56+0x46ACC5) whose terrain (0x469D88) and units (0x469F34, rects
+-2 tiles) loops skip tiles outside the rects (base names / overlays / legend / wars still full, clipped); also
shifts 4 cached (x,y) pairs 0x7D3BE8..0x7D3C0C. WHY PRACX NEVER GETS IT: the entry gate 0x46A55D-0x46A587 clears
+0x21A44 whenever iMapPixelLeft/Top (+0x1DDAC/+0x1DDB0) != 0 (PRACX's ZoomProcessing wrapper writes
m_dScrollOffset there every step, and its final recentre lands off-tile too); the shift delta ignores the
sub-tile offset (the old offset is never saved); 'origin unchanged' (0x46A5C6) = draw nothing. NB our
thunk_drawmap_fullguard (group map_recentre_fullredraw) already replays that gate after calculate_dimensions.
Options: (1) exe patch of draw_map (drop the gate, save the old offset, add its delta to dx/dy, make the
unchanged test compare offsets, force a leading column/row into the strip rects); (2) DLL-driven: memmove the
canvas, fill the sliver, write the rects, set the flag, set_clip, gen_map via PRACX's wrapper (adds the extra
column for the sub-tile offset), restore; then set +0x21A44 around PRACX's per-step pfncRedrawMap. Verify by
pixel diff vs a full redraw (altitude term on y; names/overlays translation-invariance). Rejected: oversize cached
canvas (window-sized canvas, every pass places via tile_to_pixel), pan-last-frame (black edges, hitches),
terrain-only drag (30 ms floor, units vanish). Related: [[project-smac-mouse-scheme-proposals]],
[[project-smac-design-workshop]], [[feedback-frida-hook-vs-dll-bytecheck]].
