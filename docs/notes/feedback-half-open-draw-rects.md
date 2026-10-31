---
name: feedback-half-open-draw-rects
description: Engine rect primitives draw/clip HALF-OPEN (bottom at B-1, right at R-1) — never assume inclusive edges; burned 3 ring iterations
type: feedback
---

Buffer_box_2 (0x5E3203) draws the 1px outline of the HALF-OPEN box [L,R)x[T,B):
bottom hline lands at row B-1, right vline at col R-1, while top (T) and left (L)
are inclusive. The clip (Buffer_set_clip = verbatim IntersectRect) culls the same
way: y == clip.B and x == clip.R are culled. Corner ownership: top+left = color_h
arg, bottom+right = color_v. A 2x2 rect draws nothing (zero-span law).

**Why:** three HUD-ring iterations (08-02e/f and the first flush attempt) computed
geometrically "flush" rect bottoms that painted one row higher than modeled — the
1px bottom channel the maintainer kept reporting at 4K. The same wrong assumption hid a
left/top stroke overlap at g=25/26. Meanwhile the frame band-map paints an
INCLUSIVE footprint — two different conventions in one composition.

**How to apply:** before writing any law that butts a Buffer_box_2/hline/vline draw
against another element, convert BOTH sides to DRAWN-pixel space first (drawn
bottom = rect.B-1; frame stroke band = [Y1-kS+1..Y1], kS = stroke_width(g)) and
assert adjacency there. Verify with Unicorn against the REAL primitive bytes with
pixel-write hooks — rect parity proves nothing about edges. Semantics recorded in
terranx.h (Buffer_box_2 / Buffer_set_clip lines) and the hud_cell_ring_rect
docstring. See [[project-smac-hud-scaling]], [[feedback-hline-zero-span-noop]].
