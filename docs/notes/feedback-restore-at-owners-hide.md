---
name: feedback-restore-at-owners-hide
description: A save-under restore keyed on the interface-mode stack breaks on every new nesting; restore at the OWNER's own hide, whatever mode is on top
type: feedback
---

The console save-under (t_cr_snap / t_cr_tile / t_cr_tile_exit) produced a new "variant" of the same stomp three times (base->Datalinks 2026-09-23, base snapshot under the HUD 2026-09-23b, talk->DATALINKS/PROFILE 2026-09-26) because each restore was gated on WHICH mode is on the iface-mode stack top, and set_iface_mode pushes the NEW mode before the old iface's hide runs, so every nested push is a mode the gate had never seen.

**Why:** the stack top identifies the screen being ENTERED, not the one being LEFT. The snapshot belongs to the leaving iface; its own hide (the slide_hide exit site) is the one moment its restore is always right, and restoring there keeps the canvas clean for the next snapshot, so a single snapshot cell survives nesting.

**How to apply:** key a restore on the owner's own exit event (ecx == MainWin, big-centre down, armed, unconsumed), never on the mode stack. Keep mode gates only where the restore runs on a foreign redraw (the base-screen guard in t_cr_tile). Before adding a new mode value to a gate, ask what nesting produced it and fix the ownership instead. See [[project-smac-combat-console]], [[feedback-screen-state-is-not-an-object-key]].

Second half of the same lesson (2026-09-26e): the restore must not OUT-RANK the engine's own re-tile. Copying the snapshot back AFTER the native tile_panels put snapshot pixels over its flat fill of the panel interiors, and any text the snapshot happened to hold (the column is re-snapshotted on every re-show) stayed in the 7-px channel between the HUD readout panels that no painter covers. Copy back FIRST, then let the native fill win; the snapshot only has to supply what the engine never re-tiles.
