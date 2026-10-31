---
name: project-smac-vehpick-single
description: veh_pick one-unit picker (scenario editor Select unit to edit) — VANILLA bug fixed by forcing type-8 list + clearing popup art; CLOSED: live 875a1c2e, user-shot correct at 4K/1600/1920, COMMITTED+PUSHED edf7106
type: project
---

# veh_pick single-unit picker (2026-09-19, group veh_pick_single_list)

VANILLA bug (refs\pristine\Editor\UnitSingleEdit.png vs UnitMultiEdit.png): with ONE unit the
picker drew a blue button bar, floating sprite, and an item frame off the modal's right edge.
TWO independent single-entry special cases, both must be undone:

1. `BasePop_exec_3` @0x60265e promotes dialog_type_req [+0x2350] to 8 only when option count
   [+0x2274] > 1 -> a lone option keeps Popup_start's default type 0x10 (button rows). That path
   is also NOT covered by our type-8 scaling (bar width + sprite stayed native at 4K).
2. veh_pick's add loop @0x48D1F0 sets popup ART [+0x2144] = its row sprite while count==0 and
   clears it on the 2nd add -> one unit = ART popup (extra native sprite top-left, frame laid
   out beside the art). v1 (type only, 6db46389) still looked wrong — user shot.

Fix: site veh_pick.force_list_type 0x48D2CE (10B `mov [0x6a721c],6` before the exec call) ->
thunk_vehpick_list1 (pcave2 0xB318, 31B): replays the store, [ebp-0x3064]:=8, [ebp-0x3270]:=0.
Popup base = ebp-0x53b4 in veh_pick's frame. One-row list then inherits the verified type-8
path ([[project-smac-optlist-canvas-crash]]); no q8_fill_width change was needed despite its
count>1 gate. Affects every veh_pick caller (shared picker), not just the editor.

**How to apply:** any "popup looks different with exactly one entry" report — check BOTH the
count>1 type promotion in BasePop_exec_3 AND caller-side art/first-entry special cases.
