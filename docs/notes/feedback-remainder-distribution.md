---
name: feedback-remainder-distribution
description: n×floor(scale·v) ≠ floor(n·scale·v) — any repeated stride or multi-cell span at scale must distribute the fractional remainder via cum(i)=halfDown(i·total,n), not floor each cell
type: feedback
---

`n * floor(scale*v)` is NOT `floor(n * scale * v)`. Every per-cell floor is discarded, and the loss
ACCUMULATES to the far end of the run. This is one defect class wearing many costumes:

- **Faction list rows** (2026-07-09): pitch floors `19*1.5625 = 29.69 -> 29`; over 7 rows that
  discards 4.8px, so the last row stops ~5px above the list frame => "too much empty space below
  the Peacekeepers button." Vanilla is flush by construction: `134 + 7*19 = 267 = nativeB+3`.
- **9-slice band widths** (same day): the corner band's per-cell widths came out `2,1,2,1..` at
  g=25 and `1,2,..` at g=22 — the bevel diagonal got half (then double) the stroke's weight, read
  by the maintainer as "corners too small at 1600 / too large at 1920".
- Same shape as the NetWin `slack -10 / gap +3` additive-constant law and the wrap-width step
  ([[feedback-wrap-width-desync-line-step]]): a CONSTANT per-unit error becomes a VARIABLE,
  visible total.

**The primitive.** Position cell `i` at `cum(i) = halfDown(i*total, n)` (= `round(i*total/n)`, .5
down) and take differences for the per-cell size. Sum is exactly `total` by construction; no cell
is off by more than 1; monotone. `halfDown(a,b) = (2a + b - 1) / (2b)` in integer math.

**Pin the chrome cells first.** When some cells are chrome (a stroke, a bevel) and the rest are
inert (interior fill, padding), give the chrome cells their canonical size (the stroke width K,
derived from the LEVER — never from that element's own ratio) and distribute the remainder over the
inert cells only. Distributing uniformly makes the stroke wobble; that is the disease, not the cure.

## Corollary: an additive constant's COMPENSATIONS die with it (2026-07-09, frame_bandmap_enlarge)

Removing a hack invalidates every correction written against it, and each removal unmasks the next.
The frame bake went: band map -> **exact fill** exposed the vestigial outward-grow `D=(g-16)>>3`
(0 in vanilla) -> **zeroing D** exposed `thunk_pf_frame_align`'s `D2 = ps3 - Delta`, which existed
purely to cancel that grow. Three user reports, one root. Under-filling had been hiding all of it.

**How to apply.** Before removing an additive constant, grep the whole patch set for its ASM
signature (`83 E8 10 C1 E8 03` = `(g-16)>>3`) AND for its name in comments, and list every
compensation. Fix or re-verify them in the same change. A compensation whose subject still has the
constant (here: `thunk_box_thick` keeps D, so the title pair and the faction d5a0 inward-shift remain
valid) must NOT be touched — decide per-subject, never globally.

**How to apply.**
1. Grep any scaling change for `n *` applied to an already-floored scaled value, or a stride used
   `n` times. That is the smell.
2. Prefer deriving the far edge from the CONTENT's own quantities rather than scaling the chrome
   rect independently (`ringBottom = rowsTop + 7*pitch`, not `su*(B+3)`). Then the g=16 identity is
   ALGEBRAIC — a proof of the native no-op, not a test of it. See [[project-smac-frame9-enlarge]].
3. Sweep the law in Python over `g in [16,40]` x plausible spans BEFORE running in-game, asserting:
   sum == total, no negative cells, chrome cells == K, and F(j)=j at g=16. This caught a K-tipping
   bug (2 -> 3 at 4K, span-dependent) pre-flight. See [[feedback-proportionate-scaling]].
