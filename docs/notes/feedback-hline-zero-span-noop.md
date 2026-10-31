---
name: feedback-hline-zero-span-noop
description: SMACX Buffer_hline_2/vline_2 silently draw NOTHING on a zero-length span (x0==x1 / y0==y1) — never plot a single pixel with them
type: feedback
---

`Buffer_hline_2` (0x5E1A80) and `Buffer_vline_2` (0x5E1BF0) **silently draw nothing when the span is zero-length** — `Buffer_hline_2` has `cmp ebx,edi; je <exit>` at 0x5e1ac4, so `hline(x0, x1)` with `x0==x1` paints zero pixels (not one). Spans are inclusive `[x0,x1]` otherwise.

**Why:** This bit the N2 faction connector for an entire session. The corner-bevel thunks drew each `t×t` block as `t` rows of `hline(bx, bx+t-1)`. At 1920×1080 the connector stroke thickness was `t=round(g/16)=round(22/16)=1`, so every bevel row was `hline(bx, bx)` → a no-op → the corners literally vanished (blank gap rows in the render), even though a Frida trace proved the thunk was *emitting* the correct connected Bresenham geometry. The long lines drew fine because their `x1≫x0`. The geometry was never the problem; the primitive ate single-pixel spans.

**How to apply:** When NN-scaling pixel-art strokes, `scale_uniform` tracks HEIGHT/768, so 1920×1080 gives `g=22 → round(g/16)=1` (1px). If you draw blocks/diagonals via `Buffer_hline_2`/`Buffer_vline_2`, a 1px block is a zero-length span = invisible. Two fixes: (1) use stroke thickness `ceil(g/16)=(g+15)>>4` (≥2 for any g>16, so spans are never zero-length AND lines/corners stay equal thickness — the chosen N2 fix); or (2) plot single pixels with `Buffer_put_pixel` (0x5E2330), which has no such guard. Don't bridge a 1px gap by *fattening* the block to 2px while leaving the lines 1px — that makes the corner a lump (a failed N2 attempt). Symbols + the no-op note are in `work\symbols\terranx.h`. Related: [[feedback-proportionate-scaling]], (a private note).
