---
name: feedback-menu-strip-coupling
description: FLC-driven menu dimensions fan out to 6+ consumers in the binary. Don't try to patch the loader's writes — solve via per-consumer thunks that scale at the point of read.
type: feedback
---

When a UI element's dimensions come from a data file (`openitem.flc` → fields at `[SetupWin+0x1198]` / `[+0x119C]`), the value gets read at 6+ DIFFERENT consumer sites: GraphicWin_init width/height args, X/Y position math, strip-blit srcW/srcH, loop-advance steps, and derived menu_total_height. **The same field has to read as TWO DIFFERENT VALUES** at different sites: the strip-blit `srcW` must equal the actual pixel count in the source Buffer (354, matches FLC), while GraphicWin_init's `width` arg should be the desired display width (995, scaled).

**Therefore: do NOT patch the writes to those fields (e.g., inside FUN_00629e50, the FLC loader)** — that would over-scale at the srcW reads and crash. Instead, patch each consumer that needs a scaled value with its OWN tiny thunk.

This was learned the hard way on 2026-05-28. First attempt (stretch the strip blit only) crashed because the dest Buffer was 354 wide. Second attempt (add Buffer_resize) also failed — see [[feedback-buffer-resize-per-blit]]. The breakthrough was patching GraphicWin_init's width/height args directly, which causes GraphicWin_init to internally call Buffer_init with the right dimensions, so no per-frame resize is needed.

**The complete working approach (8 patch sites for one menu, see [[project-smac-menu-strip-scaling]]):**
1. Rect-width literal at the inner `MOV EAX, 300` site (the only true binary literal — replace with scaled literal via a CALL).
2. Three strip-blit `CALL Buffer_copy_4` redirects → a thunk calling Buffer_copy_3 with scaled `dst` dims (srcW/H pass through unchanged so the source pixel data is read correctly).
3. Two loop-advance `SUB EDI, [+0x119C]` patches → CALL a thunk that advances EDI by `scaled_strip_H` not vanilla 75.
4. The `MOV EAX, [+0x1198]` that pushes `width` to GraphicWin_init.
5. The `MOV EDI, [+0x1198]` that's used for X-position math — but DUAL-PURPOSED to also scale EAX in-place (which carries `menu_total_height` into both Y-position math and the height arg push). See [[feedback-dual-purpose-thunk]].

**The conceptual move:**
- WRONG mental model: "Change the data source so all consumers see the right value." Crashes because consumers expect different values.
- RIGHT mental model: "Each consumer site that needs a scaled value gets a 5-6 byte CALL replacement. Same source field, different transformed views at different reads."

**How to apply:** When evaluating future FLC-driven UI patches, expect a similar 6-8 consumer fan-out. Use a Ghidra-script equivalent of `investigate_destbuf_sizing.py` to map every read of the relevant fields BEFORE designing thunks. Then patch the consumers — not the field. The [[project-smac-menu-strip-scaling]] thunk patterns are reusable for other SetupWin/GraphicWin instances (`config_game`, `custom_planet`, etc.) with minimal modification.

**Earlier note (superseded by this one but kept for context):** I previously concluded this couldn't be cracked without pixel-upscale at FLC load time. That was wrong — the surgical-patches approach works, it just required identifying the right SIX sites. The wrong conclusion came from underestimating the fan-out.

Related: [[project-smac-menu-strip-scaling]], [[project-smac-openitem-strip]], [[feedback-buffer-resize-per-blit]], [[feedback-dual-purpose-thunk]], [[feedback-smac-aspect-ratio]], [[project-smac-patcher-v02]]
