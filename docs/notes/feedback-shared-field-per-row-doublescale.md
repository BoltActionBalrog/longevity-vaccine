---
name: feedback-shared-field-per-row-doublescale
description: An entry-detour that scales a SHARED struct field IN PLACE re-scales it on every per-row call — gate idempotency on the NATIVE value, not a magnitude threshold
type: feedback
---

`thunk_filedlg_listpitch` (entry-detour on the generic `ListBox_draw_item` @0x60b530) scales the file list's `Dialog[+0x68]`(line-height)/`[+0x44]`(gap)/`[+0x34]`(indent) by g/16 **in place**. `ListBox_draw_item` runs **once per row**, and all rows read the SAME shared Dialog field — so the field gets re-scaled on every row.

**The bug:** the idempotency guard was `cmp lh,0x20; jge skip` ("already scaled if ≥32"). That only stops re-entry at 4K, where row#1's `16→40` clears 32 on the first pass. At g=25 row#1 scaled `16→25`, but `25 < 32` so row#2 re-scaled `25→39`, compounding to ~(g/16)² (~1.5× too tall). Result: the first row (`..`) drew faithful, every row below it (incl. the highlighted `auto`) drew over-tall. Screenshot-measured: highlighted row 6.5% of modal vs pristine 4.2%. Frida-confirmed (`frida_filedlg_listpitch.log`, g=22): call#1 read 16, call#2 read the 22 that call#1 left behind.

**Why a magnitude threshold fails:** for g in 17..31 the once-scaled value stays below the "already scaled" threshold, so it's indistinguishable from native and gets scaled again.

**How to apply:** when an entry-detour mutates a SHARED field in place and the function runs multiple times per paint, gate idempotency on the field being **exactly (or ≤) its NATIVE value**, not on a "looks already-scaled" magnitude. Fix here was a 2-byte change: `cmp lh,0x20; jge skip` → `cmp lh,0x10; jg skip` (scale only while still native ≤16). Single scale at any g; 4K byte-identical. Also: a uniform per-row scale is a clean side-benefit — all rows now equal height. See [[project-smac-loadsave-filedialog]], [[feedback-proportionate-scaling]] ("never scale relative to the already-patched state").

**PART 2 (2026-07-01) — a native-value gate is STILL unsafe on a DERIVED field.** `[+0x68]` turned out to be re-derived by the engine (`ListBox_calculate_dimensions`: `[+0x68] = [+0x48]stride − [+0x44]gap`) on EVERY list populate — and directory navigation re-populates. After one nav the derivation mixed unscaled source with the scaled gap (22−15=7), which passed the "native ≤16" gate → re-scale → gap double-scaled → next derivation went NEGATIVE (22−37=−15) → inverted clip rects, missing buttons/icons. **The full law: key one-shot idempotency on the SOURCE field of any derivation chain (the value with a single write site the engine never regenerates), and re-canonicalize the derived field from its sources on every call.** listpitch v2 gates on `0<[+0x48]≤0x16` and recomputes `[+0x68]=[+0x48]−[+0x44]` per call — every engine rebuild then self-heals. Before gating on ANY field, check whether calc/attach/update-style engine code re-derives it ([[feedback-scaling-inline-rebuild-paths]]).
