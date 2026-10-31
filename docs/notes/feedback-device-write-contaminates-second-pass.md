---
name: feedback-device-write-contaminates-second-pass
description: A thunk that stores a DEVICE value in a field the engine re-reads in a later NATIVE-space pass corrupts that pass; key chrome on the content's own anchor instead of correcting the measure
type: feedback
---

When a thunk writes a device-space value into an engine field, census every LATER read of that field, including a second run of the same function. Dialog_type16_calc runs twice per popup (BasePop_calc, then the attach): thunk_q16_rowgap stored the device row gap in [D+0x44] at the end of pass 1, and pass 2 subtracted it from the native width budget (658 - 5 = 653 instead of 655 at g=40), so option rows came out 5 px short of the OK bar at 4K and flush at 1920/1600, where the device gap happens to equal the native 3.

**Why:** the defect was invisible at both non-4K verification resolutions and the "obvious" repair (add the gap back in the consumer) is only right when the #xs budget wins the engine's max; when the measured row wins, the gap cancels and the correction over-widens. The information needed to tell the two apart is destroyed by the max.

**How to apply:** do not repair a contaminated measure downstream. Find what the neighbouring element is anchored on and anchor on the same thing (q16 v6: row width = box_w - right margin - x, the OK bar's own right edge, exe 9e6fd0a3). At g=16 such an expression collapses to vanilla's arithmetic, which proves the native no-op. Prove a suspected two-pass contamination by emulating the real bytes twice in Unicorn with the field carried over, across g = 16/22/25/30/40. Related: [[feedback-shared-field-one-owner]], [[feedback-scaling-inline-rebuild-paths]], [[feedback-copied-gate-needs-own-rationale]], [[project-smac-quit-type8-optionlist]].
