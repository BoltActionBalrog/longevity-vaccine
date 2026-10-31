---
name: project-smac-map-goto-drag
description: Map drag-to-move (goto drag) — path line + "Move to" label scaling, Shift+click vanilla bug, hold-time slider; engine state machine and the DLL runtime-rewrite sites
type: project
---

CLOSED 2026-09-25 (exe 2f2ceb79 + uimod.dll 5b8a4213, user-verified 4K + non-4K).

**Engine state machine (Frida hook_holdmove.js + static):**
- Press anywhere on the map arms go_timer 0x50F170 via Time_start on g_go_timer 0x939E60: **333 ms in move mode** ([0x939288] != 0, unit awaiting orders), **1000 ms in view mode** (view mode only drags if the MAP CURSOR is on an own selectable unit). Delay imm32s at 0x46EFC1/0x46EFC7. Shift = instant go_timer(3) at 0x46EF9B. The maintainer's "must start the drag on the unit" premise was WRONG — a quick drag just releases before the timer.
- Timer is NOT starved by continuous mouse motion (~340 ms measured).
- Drag active = Console+0x1DD80; swallow_click +0x1DD88; g_go_win_idx 0x68A5CC; Console 0x9156B0 (MapWinPtr[0]); handler `this` = Console+0x21A6C.
- **Vanilla Shift bug:** Shift auto-repeat WM_KEYDOWN -> Console_on_key_click 0x5178C0 (only Alt filtered) -> go_reset @0x517ED6 cancels the drag + swallows the release.

**Fixes:**
- Exe group `map_move_line_scale`: t_ml_line @0x4673DC (K=stroke_width(g) minor-axis copies + KxK joint plugs; law scaling_laws.move_line_calls), t_ml_textcolor shadow @0x46F586, t_ffn @0x46F595 (label at FULL g/16 — user: NOT tied to the map-label font slider). Overlay 0x937118 is fully cleared per redraw (no dirty rect). At g=22 the line stays 1 px (the law).
- DLL gotokeys.cpp `[UIMod] ShiftInstantMove` (default OFF — user: pristine never had working Shift drag): ON drops bare Shift/Ctrl keydown during a drag (WH_GETMESSAGE in wheel.cpp); OFF live-rewrites 0x46EF9B `6A 03`->`EB 3B` so Shift+press starts NO drag (user rejected vanilla's one-tick flash).
- DLL dragdelay.cpp `[UIMod] DragMoveHoldMs` slider (accessibility; 20 positions, 25 ms steps to 333 then ~20% steps to 2000 — user wanted fine low end); move = V, view = max(1000,V); >=50 ms floor (Time_start uses timeSetEvent below 50). Value readout = the ENGINE tooltip (Win_set_bubble_text) while a slider is held — see skill prefwin-settings.

**Why:** accessibility research (XAG 107, Android touch&hold delay, ClickLock) — longer hold prevents slow/tremor clicks becoming accidental move orders; shorter helps fatigue. Possible follow-up offered, not requested: in-game click-lock drag toggle.

**How to apply:** runtime byte rewrites from the DLL (byte-check first, identical in all exes) are the pattern for small opt-in behaviour toggles on engine code — no bake. Related: [[project-smac-wheel-over-map]], [[project-smac-prefwin-scaling]], [[feedback-proportionate-scaling]].
