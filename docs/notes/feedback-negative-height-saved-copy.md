---
name: feedback-negative-height-saved-copy
description: Buffer h (+0x84) is stored NEGATIVE (top-down DIB) — and so are its SAVED COPIES (globals, button +0x4c8); NEG before using as a dimension or a *stride offset or it crashes
type: feedback
---

The engine's `Buffer` height field `[buf+0x84]` is stored **NEGATIVE** (top-down DIB); width `[buf+0x80]` is positive. The trap that's easy to miss: **saved/cached copies of that field carry the negative sign too** — e.g. a FlatButton's `[esi+0x4c8]` (= buffer+0x84) and the global `g_btn_origH` (which 2dscale fills from `[esi+0x4c8]`). They are NOT positive "origH" despite the name.

**Why:** using a negative height as a multiplied byte offset is catastrophic, not just "garbage": `(origH − s)·stride` with origH negative → a large-negative offset → wild OOB write → **crash**. A negative `destH` passed to a blit/tile is similarly broken. This bit a faction-button full-bleed fix (build 2d2fa7c4): `[esi+0x4c8]` used un-negated as destH AND as the bottom-corner offset → **crash entering the menu at 4K**.

**How to apply:** before using any height field OR a saved copy of it as a positive dimension (`destH`, `srcH`) or to derive a row offset, **NEG it first** (`mov eax,[…]; neg eax`). This is exactly what `thunk_btn_2dscale` does to feed the StretchBlt `dstH`. The fix that worked: `destH = NEG([g_btn_origH])`, bottom corners at `NEG(origH)−s` (build cb53e04f, confirmed). When a name says "origH/height", verify its SIGN at the source before reusing it. Also in skill scaling-sprites ("sharp edges"). See [[project-smac-faction-button-corners]], [[feedback-thunk-frame-aliasing]].
