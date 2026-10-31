---
name: project-smac-hud-moves-fix
description: HUD unit panel vs map selection desync (hudsync.cpp: info-tile sync at veh_turn entry + PRACX hover gate) and HUD 'Moves' readout stale after the engine gives up a no-route go-to (VANILLA bug, user-confirmed 2026-10-10): Console_veh_turn's 100-failed-steps cancel skips the unit-panel repaint; fixed in uimod hudmovesfix.cpp; plus the engine's no-route go-to mechanics (greedy crawl)
type: project
---

**Engine mechanics of a go-to (decompiled 2026-10-10):** Console_veh_turn 0x513B90 loops NetDaemon_action
0x532570 -> action 0x4CF740 -> action_go_to 0x4CB310 -> Path_move 0x59BC10 (target = waypoint slot 0; on
arrival with state 0x2000200 the slots rotate down) -> order_veh 0x5947C0. No route (Path_find -1): Path_move
takes the greedy neighbour (hex_cost + 32*dist, enterable tiles only) each step -- never stops by itself; a step
that order_veh refuses is counted and after 100 the loop cancels the order @0x513E27 (no veh_skip) and waits
for input. The drawn line (MapWin_dest_line 0x467430) beelines when the two tiles' REGION bytes differ, when
Path_find fails, or when the walk meets an unexplored tile (keep: no information leak -- user).

**Traced (hook_hudmoves.js, deferred attaches):** each no-route order = ONE greedy step (spent +3), then the
next Path_move finds no neighbour, clears the order and returns -1; action_go_to's `< 0` arm @0x4CB550 stores
order 0 again and the loop waits for input with no repaint. The 100-attempt cancel never fired; a first build
that patched only it changed nothing (lesson: trace the exit before patching one).
**Bug:** both order-clearing exits skip the loop's redraw block (draw_cursor + StatusWin_redraw 0x4B9EA0 @0x513D2B),
so the HUD kept the pre-crawl "Moves" until the unit was re-selected. **Fix (uimod.dll b88b9c3c,
`hudmovesfix.cpp`, test_hudmovesfix_sites.py):** both stores (0x4CB550 8 B, 0x513E27 7 B) become jmps to
stubs = store + RepaintIfAwaiting(veh) [StatusWin_redraw(this = 0x8C5568) only when veh == CurVeh && MoveMode]
+ resume; pushfd/pushad kept (a je after site A reads earlier flags). A bare StatusWin_redraw showed the unit
DESELECTED: StatusWin_draw_status 0x4B6570 shows the active unit only while CurVeh stands on the panel's INFO TILE
(StatusWin+0x15B4/+0x15B8, StatusWin_set_loc 0x4B9F90), else that tile's veh_at/base_at -- so the repaint first
set_loc(veh.x, veh.y) as Console_set_move does @0x5117CC. That rule IS the vanilla/PRACX 'panel vs map selection' desync: the engine never sets the tile when it makes the
next unit current by itself (turn start, load), and PRACX's MouseOver (view mode) writes the pointer's tile into
it. Fixed in `hudsync.cpp` (uimod.dll 62733a9e, 2026-10-10): Console_veh_turn 0x513B90 entry detour = set_loc(unit)
+ redraw when the tile differs; prax.dll +0x4EFB hover gate `cmp [ecx+0x23BD8],0` -> `cmp [g_hoverBlock],0`
(MoveMode || CurVeh>=0 && pump-live 0x939294, refreshed per message) so hover tile info waits while a unit is
pending. In-game verification pending.

**ROOT CAUSE of the load 'half-selected' state (user: the pending unit does not blink after a load; a drag draws
its line but the release only selects it):** game_data 0x5A6AC0 stores/restores MoveMode 0x939288 (push @0x5A8455)
and CurVeh; a save written outside move mode (turn-start autosave, a V-mode save) reloads with MoveMode 0, and
Console_human_turn 0x514050 -- ControlTurnMove != 0 after any load -- takes its view-mode block @0x5140E8 instead
of Console_set_move(1) @0x5140E1. Two wrong fixes first: load_daemon's `mov [MoveMode],0` @0x5A9A64 is gated by
strstr(name, "multi") (never runs for a normal save), and the join @0x5A9AA2 is inside load_daemon, which Thinker
replaces wholesale (mod_load_daemon). FINAL (hudsync.cpp, uimod.dll 6b0e060e): detour human_turn's
`cmp [MoveMode],edi; je` @0x5140D6 -> MoveMode := 1 when !MultiplayerActive && !(GameState&0x80) && CurVeh >= 0,
then the engine's own set_move(1). The PRACX hover gate (prax +0x4EFB) was withdrawn after the audit (it blocked
hover tile info for the whole turn in deliberate V mode). Lessons: a `test eax; je` before a block is a GATE --
read what the call returns; prefer the common engine path (human_turn) over a loader Thinker may replace; and
never hard-code Vehs 0x952828 -- Thinker's default modify_unit_limit relocates it (use ModernCtlVehs()).
