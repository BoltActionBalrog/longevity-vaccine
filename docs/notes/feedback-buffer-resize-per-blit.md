---
name: feedback-buffer-resize-per-blit
description: Calling Buffer_resize inside a per-blit thunk truncates the dest Buffer's allocated DIB each iteration, dropping all prior content. Only resize once (at GraphicWin_init time, via patches there).
type: feedback
---

**Rule:** never call `Buffer_resize(dest, W, H)` inside a strip-blit thunk that runs in a multi-blit loop. Buffer_resize is **destructive** — it reallocates the DIB to exactly `W × H`, throwing away any prior pixels and any extra rows/columns. If you call it in a loop with one strip's dims, every iteration truncates the multi-strip canvas back to one strip's size.

**Why:** This was the second-iteration failure mode for the `menu_strip_scaling` patch (2026-05-28). The first design crashed because the dest Buffer was 354 wide (vanilla GraphicWin_init) but Buffer_copy_3 was asked to write a 995-wide stretched output. Adding `Buffer_resize(dest, 995, 210)` to the strip-blit thunk stopped the crash — but each of the 7 strip blits in the open-animation loop resized the dest back to 995×210. The first strip drew correctly into rows 0–209. The second strip blit asked Buffer_copy_3 to write into rows 210–419 of a buffer that was now only 210 rows tall. Result: only the first strip visible on screen; others silently overflow/get clipped. The Frida trace showed each `Buffer_resize(this=0x1aeb60, w=995, h=210)` call but it took comparing the screenshot to the log to see the truncation pattern.

**The correct architecture:** size the dest Buffer correctly **once**, at GraphicWin_init time. SMAC's GraphicWin_init takes width/height args (positions 4 and 5). Patching the binary instructions that load those args with thunks that return scaled values causes GraphicWin_init to internally call Buffer_init with the right dimensions — no per-frame resize needed, no truncation, no HDC-staleness concerns.

**Concretely for SetupWin's main menu (verified working 2026-05-28):**
- Patch `0x4ADE4B MOV EAX, [+0x1198]` (GraphicWin width arg push source) → CALL thunk returning scaled_W.
- Patch `0x4ADE25 MOV EDI, [+0x1198]` (X-position math AND, via a dual-purpose thunk, scales the in-flight EAX which holds menu_total_height) → CALL thunk that sets both.
- Remove Buffer_resize from the strip-blit thunk.

**How to apply:** for any future patch that involves stretching blits across a multi-blit loop, audit whether the destination Buffer needs to be larger than vanilla. If yes, look for a `GraphicWin_init`/`Buffer_init` call earlier in the same function and patch ITS dimension args. Don't reach for `Buffer_resize` in the per-frame path. If for some structural reason Buffer_resize is truly the only option, only call it on the FIRST iteration (gate via a "current_W < target_W" check on the Buffer's own metadata field at +0x80).

Related: [[project-smac-menu-strip-scaling]], [[feedback-menu-strip-coupling]], [[feedback-dual-purpose-thunk]]
