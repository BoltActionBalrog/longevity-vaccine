---
name: feedback-buffer-box2-is-outline
description: Buffer_box_2 (0x5E3203) draws a 1px OUTLINE, not a fill — thicken a box border by fill-outer-then-inset-fill-inner
type: feedback
---

`Buffer_box_2` (0x5E3203) draws a **1px box OUTLINE** (2x `Buffer_hline_2` + 2x `Buffer_vline_2`; top/left =
color_h, bottom/right = color_v), **NOT a filled rect** — despite thinker/terranx.h having once labelled it
"fills rect (gradient)". The common SMAC border idiom is: `Buffer_box_2(rect, color)` (1px outline) → inset rect
1px → `Buffer_fill_3(rect, fillColor)` (interior), so the interior sits flush against the outline = a 1px border.

**Why:** I assumed box_2 *filled*, so to thicken the tooltip border I just inset `Buffer_fill_3` by N. That left
box_2's 1px outline at the outer edge and pulled the fill N-1 px inward → a 1px **transparent background gap** below
the outline (user caught it in-game @4K). A Frida mid-edge pixel scan could NOT distinguish outline-vs-fill (a single
non-corner row/column reads identically either way) — only the in-game render exposed it.

**How to apply:** To thicken a border drawn by `Buffer_box_2`, do NOT just inset the interior fill. Instead **fill the
OUTER rect solid with the border color first**, THEN inset by N and fill the interior with the fill color → a solid
N-px ring, no gap (the leftover box_2 outline underneath is harmless). Grow the border INWARD (keep the outer rect
fixed) so any stored rect still bounds the box for a clean clear. At N=1 this is pixel-identical to the native
outline+fill. Done this way for the tooltip border — see [[project-smac-tooltip-bubble-scaling]]. Corollary: to tell
an outline from a fill via Frida, scan a CORNER or compare interior pixels, not a mid-edge row. See
[[feedback-frida-trace-rect-and-sprite-capture]] and the scaling-frames skill.
