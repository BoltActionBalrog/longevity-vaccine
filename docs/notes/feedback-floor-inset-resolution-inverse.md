---
name: feedback-floor-inset-resolution-inverse
description: The NN frame-enlarge floor-quantize inset is LARGE at low g and ~0 at 4K — never compensate it with a popup_scale push (scales backwards); use exact-fill
type: feedback
---

The `thunk_frame_enlarge` floor-quantize that insets the right/bottom strokes (skill `scaling-frames` §5) has a **resolution-INVERSE** magnitude: it is the floor loss `H − floor(floor(H·16/g)·g/16)`, which is **large at low g (~10px at 1600×1200 g25) and ~0 at 4K g40** (4K's headroom hides it). Top/left render flush (top-left anchored); right/bottom pull IN.

**Why:** at high g the round-trip `H·16/g` then `·g/16` loses little; at low g (g just above 16) the two floors compound into a multi-px shortfall on a wide/tall frame.

**The trap (cost a build):** when the file-dialog inner frame's right stroke ate the content's right margin at 1600×1200 (OK/CANCEL + rows collided; left margin fine ~10px), I "mirrored the bottom edge's `popup_scale(3)` push" onto the right. WRONG — `popup_scale(3)` scales UP with g, so it compensated **backwards**: nothing to fix at 4K, where it then shoved the inner stroke into the outer frame and **crushed the right inner/outer channel** (user 4K shot). A scaled-constant push can never track an inverse-scaling defect.

**How to apply:** fix the floor-inset at its SOURCE with **exact-fill** (`g_fc_exact` → `thunk_frame_enlarge` overrides dstW/dstH to the exact rect W×H), which renders flush at ANY g by construction (4K = the already-good flush result; low-res = inset removed). Route the frame through `hollow_flat + g_fc_exact` (copy its rect → `g_faction_scratch_rect`, set `g_fc_exact=1`), the same path the outer/title frames use. Do NOT reach for a `popup_scale(N)` push to hide a render-floor defect. (The bottom edge's push survives only because it's a genuine EXTRA button gap with the whole window margin below it — not floor-compensation.) See [[project-smac-loadsave-filedialog]], skill `scaling-frames` §5, [[feedback-proportionate-scaling]].
