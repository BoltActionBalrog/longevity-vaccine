---
name: feedback-engine-nn-column-map
description: The engine's scaled sprite blit maps native column k to sum(runs[0:k]) from Sprite_fill_scaling_table, NOT k*g/16 -- model it from the run table, never as a multiple of g
type: feedback
---

The engine NN blit (Buffer_draw_2 -> Sprite_draw_2, runs from Sprite_fill_scaling_table 0x5EB20F, table at 0x9B3AD8)
places native column k at R(k) = sum(runs[0:k]). It is NOT fl(k*g/16) and NOT k*g/16 exactly: for the 47-wide rail
scrollbar strip, column 32 lands at 2g+1 for g=25..31 (and 48), at 2g elsewhere.

**Why:** 2026-10-17 fix 4f assumed "wall = strip x + 2g" in both the asm and its tests; the reviewer ran the REAL
engine blit under Unicorn and found a 1-px dark seam between the right rails after the Load/Save list bar slides out
at 1600x1200 / 1440p, plus a scrollbar bar off-centre between the art's cyan lines at 13 of 24 g values. The tests
passed because they modelled the blit instead of measuring it.

**How to apply:** any position derived from where the engine put a native column (art edges, lines inside sprite
art, anything that must abut an engine-blitted sprite) uses a law ported from Sprite_fill_scaling_table and checked
by emulating the real engine path; tests must run the real Buffer_draw_2 (a throwaway emulation harness did; it was
not kept). Same lesson as the "measure the engine" invariant (the centre-aligned NN stretch blit).
Related: [[feedback-symmetry-over-1px-scaling]].
