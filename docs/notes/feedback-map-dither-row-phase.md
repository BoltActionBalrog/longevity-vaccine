---
name: feedback-map-dither-row-phase
description: The map terrain's dither has a 2-row phase tied to the DESTINATION row -- a frame shifted by an odd number of rows mismatches a fresh render everywhere; vertical scroll-blits must be even (nudge the sub-tile offset)
type: feedback
---

Verify runs 2026-10-10 (mapscroll MapScrollVerify=1, 4K): every scroll step with an ODD dy mismatched ~80% of
the shifted frame against a full redraw; every EVEN dy matched to within a few hundred pixels (units/overlays).
The terrain painter's dither phase is keyed on the destination row parity, so moving existing content by an
odd row count flips its phase relative to freshly drawn strips -- seen in-game as alternating black rows after
scrolling. The engine's own scroll path never shows it: whole-tile shifts are 4z rows, always even.

**How to apply:** any frame shift we perform ourselves must keep dy even: pull an odd dy one pixel toward zero
by nudging the Console's sub-tile offset (+0x1DDB0) that the strips are drawn with (PRACX's own offset stays, so
no drift). Horizontal parity does not matter (row-only pattern). Related: [[project-smac-drag-scroll-perf]],
[[feedback-buffer-copy4-backward-remainder]].
