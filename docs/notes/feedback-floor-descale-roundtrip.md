---
name: feedback-floor-descale-roundtrip
description: Descaling a floor-scaled device value back to native MUST use CEIL — fl(dev·16/g) loses a native pixel whenever n·g/16 is fractional; and two elements that must stay flush must share ONE floor cascade, never two parallel formulas that only agree at exact multiples (g=40)
type: feedback
---

Two laws about round-tripping the floor scale `dev = fl(n·g/16)`:

1. **The exact inverse is CEIL, not floor and not round.** `dev·16/g ∈ (n−1, n]`, so `ceil(dev·16/g) = (dev·16+g−1)//g` recovers n at EVERY g. A raw floor loses a pixel whenever n·g/16 is fractional; round loses one whenever `(n·g mod 16)/g > 1/2` (fails at g=23 for n=20, g=25 for n=238 — cases a 22/25/40 verification sweep never sees). At exact multiples (g=40) all three agree — which is why these bugs pass every 4K check and surface only in non-4K reports.
2. **Flushness = the neighbor's own formula.** When element A must butt element B and B's position comes through its own floor cascade (descale→offset→rescale), A must compute its edge with B's IDENTICAL cascade — a mathematically "equivalent" direct formula (pt(703) vs fl((fl(W·16/g)−55)·g/16)) diverges by 1–2px at fractional g and the later-drawn element eats the earlier one's stroke. This is [[feedback-match-opposite-edge-margin]] extended to computed anchors: the filedlg railscale/d690-insets pair did it right; the BaseWin console frame v2 did not.

**Why:** 2026-07-21e, two independent 1600×1200 defects, one disease: (a) the BaseWin console-frame right stroke vanished under the rails (frame used pt(703), rails used the double-floor → 1098 vs 1096 at g=25); (b) the GOVERNOR chevrons' right border column vanished (fixed-art 20×20 state-sprite buttons: thunk_btn_shrink floor-descaled the window 31→19, so the KSB source rect excluded the art's last column). A third instance predates them: the 2026-07-10 hover-highlight bottom-row clip (H floor 31→19), patched then with ROUND — which is itself inexact (case 2 above); now ceil (law btn_native_dim v2).

**How to apply:**
- Any thunk that recovers a native magnitude from a device one (`dev·16/g`) uses `(dev·16+g−1)/g`. Grep candidates: `C1 E0 04` + `F7 F1`/`F7 F9` (shl 4; div) sequences in cave thunks.
- Fixed-art widgets (window sized FROM sprite dims, no re-render) are the sensitive consumers — a lost pixel there clips art; 9-slice widgets self-heal and hide the bug.
- Before pinning a "flush" law to a closed-form constant, write out the NEIGHBOR's actual runtime arithmetic and use that expression verbatim (and test equality across g 17..40, not just 22/25/40).

Related: [[feedback-remainder-distribution]] (the sibling forward-direction law), [[project-smac-base-screen]] (both instances), [[feedback-match-opposite-edge-margin]].
