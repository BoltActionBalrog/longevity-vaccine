---
name: feedback-proportionate-scaling
description: every scaled UI value must be a uniform multiple of the VANILLA value — always measure vanilla proportions and compare
type: feedback
---

ALL UI scaling must be proportionate to vanilla: every dimension we change (font size, margin, gap, frame
width/height, box width/height, stroke, padding) must come out as a clean uniform `scale = g/16` multiple of the
**vanilla (pristine, unpatched)** value. Never introduce a tuned/"comfortable"/eyeballed value that isn't
`vanilla_value * scale`. The patched UI at any resolution must look like a pixel-proportional zoom of vanilla — same
proportions, never distorted, never an invented gap/margin.

**Why:** the maintainer's hard requirement — "We should never break proportionality with vanilla." Picking ad-hoc values
(e.g. choosing a "~12px comfortable margin") breaks the faithful-zoom guarantee even if it looks fine in isolation.
The faction quote box regressions came exactly from one axis scaling (height/font ×2.5) while another stayed native
(width ~2.0×, margin 3px) — mixed scales = broken proportion.

**How to apply:**
- Before scaling anything, MEASURE the vanilla value (trace the pristine `.bak`, or read the literal in the
  unpatched decompile). Do NOT scale relative to the already-patched state — that compounds/hides errors.
- Compute the target as `vanilla * popup_scale` (i.e. `vanilla * g / 16`), with the `g<=16 -> native no-op` gate.
- After patching, VERIFY the patched value ≈ `vanilla * scale` for EACH element, and that all elements share the
  same scale factor (no axis lagging). If a Frida number isn't `vanilla * g/16`, it's wrong even if it "looks ok".
- When asked "how big should X be", the answer is never a preference — it is `vanilla_X * scale`. Don't offer
  arbitrary magnitudes as options.
See [[feedback-smac-aspect-ratio]] (uniform scale / no per-axis distortion) and [[feedback-smac-all-resolutions]].
