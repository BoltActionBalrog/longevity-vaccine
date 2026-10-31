---
name: feedback-frida-trace-rect-and-sprite-capture
description: Frida tracing for menu/frame scaling — read the engine's computed rect GLOBAL instead of pixel-inferring; capture a sprite by FIXED SOURCE dims so you also get the g16 vanilla baseline
type: feedback
---

Two reusable Frida techniques for SMAC modal/menu frame-placement RE (both cost several wasted trace iterations before they clicked):

1. **Read the engine's computed rect GLOBAL — don't pixel-infer frame positions.** When a thunk fills a known global RECT (e.g. `g_frame_inset_rect` = the d528 inner box rect, pcave2+0x5D0 = VA 0xA0C5D0; `g_faction_quote` flag at pcave2+0x550 = 0xA0C550), read that global in the hook's `onLeave` to get the exact box-coord L/T/R/B the engine will render. Pixel row/column scans are AMBIGUOUS when a stroke and its channel-fill share a palette index (the faction frame is green-on-green: stroke 198/34/31 and fill also greens) — you can't tell stroke from gap. The rect global is unambiguous and instantly reconciles the placement math (e.g. "left inset 17 = right inset 17, symmetric").

2. **Capture a target sprite by its FIXED SOURCE dimensions — not "largest blit" and not "num!=den only".** A sprite's SOURCE size is constant across resolutions (only the dest scale changes); the faction leader portrait source is 131×157 at every g. Filter `Sprite_draw_2` on source w/h (read at [ecx+0x18]/[ecx+0x1c], ~131×157) plus the dest buffer. Two pitfalls this avoids: (a) "largest dest blit" grabs a near-full-box COMPOSITE blit, not your sprite; (b) "num!=den only" SKIPS the g16 native 1:1 blit, so you never capture the VANILLA baseline — filter by source-dims to capture all scales INCLUDING g16.

**Why:** Both generalize to any frame/sprite scaling investigation. They turn "guess from pixels across N runs" into one definitive read.

**How to apply:** Hook the TARGET function entry, never our patched call-sites (push imm32;ret tail-jump collision → "Unable to allocate draw buffer"; see (a private note)). For rect placement, read the global the thunk fills. For sprites, gate on source-dim identity + dest buffer. Run at 1024×768 / 1600×1200 / 3840×2160 to get vanilla(g16) + two scales in one pass. Reusable artifacts: `work\scripts\hook_faction_a1.js` (rect-global read + full-width horizontal row-scan + RAW per-pixel edge windows), `hook_faction_boxheight.js` (vertical column scan). Pairs with [[feedback-match-opposite-edge-margin]].
