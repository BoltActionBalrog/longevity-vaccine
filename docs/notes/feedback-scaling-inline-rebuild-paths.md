---
name: feedback-scaling-inline-rebuild-paths
description: When a select/refresh action regresses a scaled UI element, suspect a separate inline REBUILD path the build-time scaling hooks don't cover
type: feedback
---

Member of the [[feedback-draw-state-multiplicity]] class (one element, many draw variants — read that first).

A UI element scaled by hooking its **construction/build** can be silently re-created at NATIVE size by a SEPARATE inline rebuild path elsewhere — typically in the same window's command/event handler — that the build-time thunks never touch.

Concrete case (2026-06-23, N1 follow-up, build `dbf02fc6`): the faction name-list ListBox is scaled by thunks at the BUILD site (`thunk_factionwin_list`/`pitch`/`rowgap` @0x48921c/0x489250/0x489260 in `FactionPickWin_build`). But `FactionPickWin_on_command` (0x489ba0) **rebuilds the listbox in-place** in TWO inline blocks — the id>=0x3039 SELECTION case (@0x48a221/58/68) and the 0x100/0x101/0x102 init case (@0x489def/e26/e36) — each doing `ListBox_close → Dialog_init_3 → MOV [..+0x8704],0x13 (pitch) / MOV [..+0x8700],3 (gap)`. Selecting a faction ran those native → list collapsed tiny/top-left. Fixed by scaling all 6 rebuild leaf sites too (group `faction_listrebuild_scale`).

**Why:** the regression was NOT in the patch that "owns" the feature (the submenu font swap was clean per Frida) — it was a pre-existing latent native path newly exposed once the feature became usable. Hunting the wrong thunk wastes runs.

**How to apply:** when "open works but select/refresh breaks the scaling," (1) Frida-confirm the suspected thunk's globals are restored (rules out a leak), then (2) decompile the window's command handler and `grep` its callee list for DUPLICATE build calls (e.g. "2x Dialog_init_3", "2x ListBox_attach") — each duplicate is an inline rebuild block that needs the same leaf-site scaling as the build. See [[feedback-thunk-call-vs-detour]] for sharing one helper across the duplicate sites, and (a private note).

**Same law for sibling CREATION paths (2026-07-03, #DPLAYERROR):** a field-read detour on ONE creation path silently misses the sibling paths that read the same field. `popup_button_height_scaling` detoured the [0x30d0] height read on the standard-OK path (0x602d3b) — but custom `#button <label>` popups create buttons via a separate loop (read @0x6030bd) and CANCEL has a third read (@0x603404), so their buttons stayed native. The fix census: **byte-scan the whole function for every mod/rm read of the field** (`re.finditer(rb'\x8b[\x86\x8e\x96...]<disp32>')` found 4 reads in one shot — 2 unpatched creation reads + 1 layout read that must STAY native). Patch the creation reads with one shared CALL-helper gated on the native value ([[feedback-shared-field-per-row-doublescale]]); leave position/layout reads alone when the confirmed geometry depends on them staying native.
