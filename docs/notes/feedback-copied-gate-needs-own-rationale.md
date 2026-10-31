---
name: feedback-copied-gate-needs-own-rationale
description: A guard copied from a sibling thunk (count > 1, type ==, etc.) is a bug unless the NEW site has its own vanilla reason for it
type: feedback
---

A gate copied from a sibling thunk or a prototype hook is not a law. `thunk_q16_fill_width` carried `count > 1` from the type-1 `thunk_list_fill_width`, where it protects single labels and wrapped body text; in a type-16 Dialog every row is a reply, so the gate only left one-row lists native-wide (council propose picker with a single motion, 2026-09-28, exe 9764b505).

**Why:** the defect was invisible for three months because every verified popup had 2+ rows; it was first blamed on the most recent feature work (the updater), which had not touched the exe at all.

**How to apply:** for every gate in a thunk, find the vanilla term it mirrors (here: Dialog_type16_calc 0x60D380 has no count term in the row width). If there is none, drop the gate or record why it exists. When a "regression" is reported, check whether the screen's INPUT differs from the verified case (row count, no body text, no art) before bisecting recent commits. Siblings that still carry count > 1: `thunk_q8_fill_width` (type 8), `thunk_list_fill_width` (type 1, deliberate). Related: [[feedback-draw-state-multiplicity]], [[project-smac-quit-type8-optionlist]], [[project-smac-council-popup]].
