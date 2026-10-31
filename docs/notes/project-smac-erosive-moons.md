---
name: project-smac-erosive-moons
description: Erosive-forces screen moon-preview scaling: per-cluster anamorphic Buffer_copy_3 approach (applied, MD5 d14ecb4b, pending visual test); moon-art structure; deco keyed/opaque split; outstanding level-switch + soft_update issues
type: project
---

State 2026-05-30: **EROSIVE MOONS COMPLETE & visually confirmed.** Full-patch MD5 `3607f796fa2ce8addf0dc7adc4a4fbd3`. Level-switch (1/2/3 moons on hover) works, anamorphic placement correct, clean keying (no artifacts). Extends [[project-smac-menu-strip-scaling]] (same `menu_strip_scaling` group). `--restore` reverts; pristine `.bak` = `2d0b1438`.

**Two bugs fixed (in order):**
1. **Level-switch ("only STRONG showed")** = the ocean-tuned `thunk_deco_soft_update` computed a NEGATIVE refresh X' for the left-anchored moons (decoX=0: `0+450-scale_x(450)=-1237`), clipping the on-hover redraw to a thin sliver. Fix: one-line clamp `X'=max(0,X')` (`85 C0 79 02 33 C0`) — right-aligned ocean keeps its positive X', moons get X'=0 covering [0,scale_x(srcW)]. (Moons update on HOVER, not click — the engine redraws the hovered MOON# on top; MOON1/2/3 are CUMULATIVE images, opaque black squares cover the absent moons.)
2. **Black L-bar corner artifacts** = the per-cluster OPAQUE `Buffer_copy_3` drew the magenta-key corners (C2=18%) as black rectangles poking into the nebula glow. Fix: a proper **keyed-anamorphic two-step** through a reusable scratch Buffer (see below). Replaced the per-cluster approach entirely.

**REUSABLE PRIMITIVE built (architected for gameplay/UI/sprite reuse):**
- `thunk_keyed_stretch_blit` (cave +0x470) — `__cdecl(srcBuf,destBuf,srcX,srcY,srcW,srcH,dstX,dstY,dstW,dstH,key)` RET 0x2C. Does keyed + NON-uniform scaling that neither `Buffer_draw_2` (uniform only) nor `Buffer_copy_3` (opaque) can alone: `Buffer_copy_3` stretches src→scratch (nearest-neighbour, so the key INDEX survives — 8-bit indexed can't interpolate), then `Buffer_draw_2` keyed-blits scratch→dest 1:1. **Call this for any future keyed sprite/UI scaling.**
- `thunk_ensure_scratch` (cave +0x4D0) + `g_scratch_buf` (cave +0x510, 4-byte Buffer*) — lazily create ONE reusable offscreen scratch Buffer: `crt_malloc(0x588)` + `Buffer_ctor(0x5D7210)`. Plain **Buffer (0x588 bytes), NOT a GraphicWin** — a GraphicWin would spin up `Win_init`/a DDraw surface (`GraphicWin_init` gates buffer alloc on flag bit `0x40000000`). Buffer pixels alloc'd via `Buffer_resize` per use.
- New engine symbols (terranx.h): `Buffer_ctor=0x5D7210`, `crt_malloc=0x64558A`.

## The screen
"Adjust Erosive Forces" (a `custom_planet`-family screen) shows 1/2/3 moons (WEAK/AVERAGE/STRONG) as a top-left **preview grid**, drawn as a SetupWin per-item DECORATION (the same `[SetupWin+EBX*4+0xA1C/0xA28/0xA34]` deco arrays as ocean coverage; see [[project-smac-menu-strip-scaling]] and terranx.h).

## Moon art structure (decoded from MOON{1,2,3}.PCX, 450x450, all 3 identical layout)
- ~86% **magenta index-255** = transparent key (load_pcx remaps to engine key index 9).
- 3 fixed **clusters** = moon + **opaque index-55 PURE-BLACK backdrop square**, at canvas rects: C1 `(220,0,80x50)`, C2 `(340,90,60x60)`, C3 `(0,280,150x140)`. Moon body = dark indices (54/74/127/188...). The black square is NOT keyed — it draws solid; the moons are **dark-sphere-on-black**, designed to sit in the BLACK gaps of the background.

## Root cause of the artifacts (user's diagnosis, confirmed)
At 4K the background is stretched **anamorphically** (xopeninga 1024x768 -> screen, `Buffer_copy_3 @ 0x589aed`, x3.75 wide / x2.81 tall). Vanilla composes moons in the dark gaps relative to that background (verified by compositing vanilla 1024 — see `D:\SmacxUi\work\vanilla1024_*.png`). Scaling the moons **uniformly** (x2.81) from origin drifts slots C1/C2 (x≈618-1124) onto the suns (x≈562-1219) -> their black squares show as boxes; C3 (bottom-left) stays clear -> the one "correct" moon. The black squares aren't a bug — they're invisible on black, visible on the suns.

## The fix (applied)
Moons must scale ANAMORPHICALLY like the background (the ONE exception to [[feedback-smac-aspect-ratio]], same as the ocean planet). `Buffer_draw_2` (the keyed path, `0x4AE6D5`) only scales UNIFORMLY (`dest=src*a5/a6`, same ratio W&H — disasm-confirmed). `Buffer_copy_3` does anamorphic but is OPAQUE. **Solution: per-cluster `Buffer_copy_3`** — blit each cluster's sub-rect to its anamorphic dest, opaque, no key/scratch:
`Buffer_copy_3(moon, sx,sy,sw,sh, scale_x(sx),scale_y(sy),scale_x(sw),scale_y(sh))`. The cluster bbox ≈ the opaque moon+black-square (blends with the dark gap at its anamorphic position). Implemented as `thunk_deco_keyed_scaled` rewritten to 245 bytes @ cave `0x410` (site `0x4AE6BC`); cave now `0x540`, `_SELFMOD` VirtualSize `0x4740`.

**Dead-end considered & rejected:** the "proper" keyed-anamorphic two-step (`Buffer_copy_3` -> scratch buffer -> `Buffer_draw_2` keyed 1:1) would require ALLOCATING a scratch GraphicWin (`crt_malloc(0xA14)` + `GraphicWin_ctor 0x5D4CF0` + `GraphicWin_init 0x5D4EF0`) — no reusable scratch exists (0x945820 is a flag, backbuffer is the screen). Per-cluster `Buffer_copy_3` sidesteps all of it (user's insight: reuse the background's own anamorphic fn).

## Artifact decode tooling (reusable)
`D:\SmacxUi\work\` has a standalone PCX decoder/compositor (one-off scripts): decode_pcx (RLE + palette), cluster detection, and PNG render (magenta->cyan, opaque-black->red). Renders: `moon2_layout_*.png`, `vanilla1024_erosive_*.png`.

## DONE
1. ✅ Visual placement (anamorphic, dark gaps) — confirmed.
2. ✅ Level-switch — fixed via the `X'=max(0,X')` soft_update clamp.
3. ✅ soft_update under-refresh — same clamp.
4. ✅ Magenta-corner artifacts — fixed via the keyed-anamorphic two-step (reusable primitive).

## OUTSTANDING
- Spot-check other deco-bearing screens (tides/orbit/native-life/faction-select) share `0x4AE6BC`/`0x4AE710`/`0x4AE66E`/`0x4AE715` — verify not broken at 4K.

**User decision 2026-10-18:** the planet/moon preview stays ON at every width, including native-scale widescreens (1280x720, 1366x768) where vanilla shows nothing -- an accepted exception to 'g <= 16 = vanilla' (it registers on the anamorphically stretched backdrop). Fix 15 (same day) made 800x600 and 1024x768 exactly vanilla (backdrop 1:1) and follows the engine's own art choice (W == 800 -> openingb 800x600, else openinga 1024x768).
