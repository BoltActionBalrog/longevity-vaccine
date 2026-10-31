---
name: feedback-gate-flag-refcount
description: A shared gate/depth global (g_popup_active and kin) must only ever be INC'd / clamped-DEC'd; an absolute := 1 / := 0 writer anywhere silently disarms every scaled draw nested inside it (quit-modal OK hover after Preferences, 2026-09-13)
type: feedback
---

Never write a shared gate global with an absolute value (`mov [g_x], 1` / `mov [g_x], 0`). Bracket with `inc` / `cmp 0; jle; dec` (the thunk_basewin_btnzoom / thunk_set_popup_active v2 pattern), even when an "audit" says the draw cannot nest inside the other bracket.

**Why:** thunk_pref_btnzoom v2 wrote g_popup_active := 1 / := 0 around the PrefWin + uimod-widget FlatButton draws ("a vtable draw cannot nest inside exec_3's own bracket"). After Preferences had been opened, some PrefWin/DLL-range button draw landed after the quit modal's exec_3 INC and zeroed the depth, so the OK hover redraw missed thunk_btn_shrink's gate and drew the native 20-px bar at the top of its 50-px window (user 4K shot 20260913), the identical symptom the exec_3 v2 refcount note had already described for nested quote boxes. The "cannot nest" premise is unprovable against the engine's global window-list walks.

**How to apply:** (1) Every reader tests nonzero, every writer is INC / clamped DEC. (2) Before trusting a gate, byte-scan the live `.pcave2` for `C7 05 <abs32 of the gate> imm32` (absolute writers) and `89 0D` / `A3 <abs32>` (register stores): `re.finditer` over the section, classify by the opcode bytes before the disp32. (3) A "resolution-independent, only after opening window X" regression on a popup element = look for an absolute gate writer reachable from window X first. Related: [[feedback-animation-loop-draw-sites]] (end-of-life DISARM), [[project-smac-prefwin-scaling]].
