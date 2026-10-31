---
name: project-smac-scaling-baseline-1024
description: SMAC UI scaling reference resolution is 1024x768 (not 800x600); faithful = value_at_1024 x g/16
type: project
---

The SMAC UI-scaling project's BASELINE reference resolution is **1024x768**, decided by the maintainer 2026-06-13.
Rationale: most players boot on a modern monitor where the game scales up from 1024x768, so we preserve the
PROPORTIONS of the pristine 1024x768 UI scaled uniformly to the player's resolution. Faithful value at any
resolution = `value_measured_at_1024x768 x (g/16)`.

Consequences:
- The game ENGINE already applies its own ~x1.5 to SOME fields going 800->1024 (e.g. box_w [0x30bc], pad_x
  [0x30e0]) and NOT to others (e.g. content_top [0x30e8] = 18 at both 800 and 1024 -> the faction quote-box
  top margin is one of these "unscaled" fields). That x1.5 is fine -- 1024 is our reference, not 800.
- The faction quote box = vanilla(1024) 722 x 2.5 = 1805 @4K follows from this baseline and IS faithful -- KEEP IT.

A3 RESOLVED 2026-06-13 (build 3217a242, measured via [[project-smac-font-calibration]] + unified trace): pristine
1024x768 = FOUR lines (user screenshot; the old "3 lines" frida_faction_vanilla.log was a bad capture that dropped
L4). The patched quote shows THREE lines. Root cause is NOT a scaling error -- EVERYTHING is geometrically faithful:
box 1805 (=722x2.5), text column 1405 (~=562x2.5, right margin 27~=11x2.5), font cell 50 (=20x2.5, line pitch 50
measured). The 3-vs-4 difference is a **GDI font-width nonlinearity**: Arial Narrow's CELL height scales 2.5x cleanly
(20->50) but its GLYPH ADVANCE scales only ~2.27x (px/char 7.2->16.3) -- small-size hinting rounds the 20px advances
relatively WIDER, so pristine fits 78 chars/line (4 lines) while the faithful 2.5x scale-up fits 86 (3 lines). This
is inherent to rendering the font at different sizes and CANNOT be removed by scaling. USER DECISION: **ACCEPT 3
lines** (the geometrically-faithful, less-hinting-distorted rendering). The font fix (47->50, true 2.5x) is KEPT as
a proportionality correction (the 47px was a 6% invariant violation); it is GLOBAL (all popup fonts). A3 closed.

OPEN consistency check (still live): for the engine-UNSCALED fields, our patch thunks must scale them up from the
**1024** value, NOT the lower-res 800 value -- mixing baselines drifts proportions. Verify via the unified trace
`work\scripts\hook_faction_unified.js`: patched_value / (g/16) must equal the 1024 measurement for every field.
See (a private note) and [[feedback-proportionate-scaling]].
