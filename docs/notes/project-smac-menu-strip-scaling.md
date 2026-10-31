---
name: project-smac-menu-strip-scaling
description: SetupWin menu-strip scaling patch group: applied state (visually mostly-working at 4K, text remaining), field-coupling map from openitem.flc through 6 consumer sites, lessons for future FLC-driven menu patches
type: project
---

State as of 2026-05-30: the main menu AND titled submenus are **visually complete** at any resolution — strips scaled & stacked, text legible/font-scaled/centered, full-strip hit box, scaled title + separator on submenus, bottom green-sliver gap fixed, AND the **planet-customization decoration (ocean-coverage preview) is now scaled, aligned, and fully refreshing** (see section below). Current full-patch MD5: `1451ceee7e3e36b6d54c710aa6e60bd9` (includes [[project-smac-win11-24h2-fix]] too). `--restore` reverts cleanly. Cave `menu_strip_thunks` now 0x440 reserved (was 0x300); `_SELFMOD` VirtualSize bumps to 0x4640.

**Vertical seam on every menu bar = BASE-GAME art, NOT our regression** (settled 2026-05-30). The bevel/segment seams in the green `openitem.flc` bars exist in the unpatched binary (user-confirmed via unpatched screenshot). Our strip patch is a single continuous `Buffer_copy_3` stretch per bar — it cannot introduce a new vertical seam, only magnify the existing source-art ones ~2.8×. Disregarded by decision.

**Bottom-gap fix (the ~6px green sliver):** it was the per-element-vs-lump rounding mismatch — window height was `scale_uniform(menu_total_height)` (e.g. `scale(525)=1476`) while the strips paint `count×scale(75)=1470`. Fixed by rewriting the dual-purpose height thunk (`thunk_load_strip_w_into_edi`, relocated to cave +0x250) to output the PAINTED extent instead: `EAX = count×scale(75) [+ scale(20) if BL!=0 separator]`, reading count from `[ESI+0xfcc]` and the BL flag from `[EBP-0x1b0]`. Window now == strip extent (menu sits ~6px lower at top, still bottom-anchored). The earlier BL!=0 separator scaling (fill_3 W/H + EDI advance folded into `thunk_fill3_scaled`, spot offset via `thunk_scale20_into_edx`) is applied and working.

**Gotcha learned (caused a hard crash):** do NOT overwrite a byte that is a live JZ/JNZ branch target. The `separator_advance` site at 0x4ADF55 was reverted because 0x4ADF58 is the target of the BL-gate jumps; clobbering it jumped into the middle of a CALL and crashed the main menu. The EDI advance was folded into the fill thunk instead (which preserves EDI, as vanilla relies on).

### Text + font + hit-box fixes added 2026-05-29 (all runtime `scale_uniform`, resolution-independent)
- **Font size**: `Font_init @ 0x618F40` builds the menu font with `PUSH 0x12` (18) at `0x4ADC8E`, bound to the strip buffer via `Buffer_set_font @ 0x4ADE9F`. `thunk_push_scaled_font` (site `0x4ADC8E`) replaces it with `scale_uniform(18)`=50 (register-only: stashes retaddr in ECX across the call, rebuilds the `[resource][size][1]` arg frame, RETs into the `Font_init` CALL). Frida-confirmed `fontH` field `[font+0x10]` = 38 at size 50.
- **Spot/hit-box height** (THE key gotcha): `SetupWin_do_menu_rightside` has two spot-rect paths gated by a per-item-text flag `BL` (`[EBP+0xfffffe50]`). At `0x4ADFBC` a `JZ 0x4AE063` **skips the `0x4AE042` init for the main menu (BL==0)**. So the main-menu spot height comes from **`0x4ADF95` `MOV ECX,[ESI+0x119C]`** (→ `-75` → NEG → 75 → `Y_bottom`), NOT `0x4AE042`. `thunk_spot_h_into_ecx` (site `0x4ADF95`) returns `-scale_uniform(75)=-210` → full-strip hit box. `spot_init_h_scaled @ 0x4AE042` (thunk_spot_h_into_edi) handles the BL!=0 branch other menus use. Y-step is scaled separately by `spot_step_h_scaled @ 0x4AE08D`. Spot WIDTH scales via the rect-width thunk `0x4ADFA5` (300→843). Verified by hooking `Spot_add @ 0x5FA960`: `Spot_add(X=15 Y=0/210/420… W=828 H=…)`.
- **Text centering**: `Buffer_write_cent_l_7 @ 0x5DD130` centers BOTH axes in the passed rect (`text_Y = top + (rect_h − fontH)/2`, disasm `0x5DD204–0x5DD219`). `draw_item`'s text rect derives from **spot.top only** (rect.top = spot.top+0x21, rect.bottom = spot.top+0x39 — independent of spot height). `thunk_text_fullrect` (site `0x4AE642`, call-redirect) rewrites the rect to the **scaled vanilla band** `{spot.top+scale(0x21), spot.top+scale(0x37)}` (~59% down = vanilla look; full-strip centering at 50% read as "too high"), then abs-`JMP`s into write_cent (rel32 only follows E8). Requires the clip widening below.
- **Clip**: `draw_item` sets a vanilla 26px clip band before drawing; it would hide the re-centered text. `thunk_clip_fullstrip` (site `0x4AE51A`, redirect of `Buffer_set_clip @ 0x5D8000`) widens the clip bottom to `spot.top+scale(75)`. Leaves rect.top intact (feeds strip-blit dst Y at `0x4AE554`).
- **New thunk symbols/offsets** in cave `menu_strip_thunks` (base `0x668200`): push_scaled_font@0x140, spot_h_into_edi@0x160, spot_h_into_eax@0x180, spot_h_into_ecx@0x190, text_fullrect@0x1A4 (51B), clip_fullstrip@0x1D8. New engine symbols: `Buffer_write_cent_l_7=0x5DD130`, `Buffer_set_clip=0x5D8000`, `Spot_add=0x5FA960`.

### Earlier state (2026-05-28, superseded above)
Strips scaled but text vanilla-size/too-high; spots at vanilla 75 spacing causing label pile-up on the first three strips. The decoration block is dead on the main menu (deco slots NULL) — NOT the mangle cause; the gate patch `0x4AE66E` is inert there.

## The coupling map (load-bearing for any FLC-driven UI patch)

SetupWin's main-menu code at `SetupWin_do_menu_rightside @ 0x4ADB70` and `SetupWin_draw_item @ 0x4AE4D0` derives a **fan-out of six display dimensions** from a single asset source: the `openitem.flc` file's header. Patching the strip to scale required patching every fan-out point because the binary conflates "source pixel count" with "display dimension":

```
openitem.flc header
  ├─ width (354)  ───► FUN_00629e50 stores in [SetupWin+0x1198]
  └─ height (75) ───► FUN_00629e50 stores in [SetupWin+0x119C]
                      (height stored as -75 — negative is the engine's
                       "top-down" convention; consumers negate as needed)

[SetupWin+0x1198] (strip_W = 354) consumers:
  1. 0x4ADE25  MOV EDI, [+0x1198]    — feeds SUB EDX, EDI for menu X-position
                                       (X = ScreenWidth - strip_W)
  2. 0x4ADE4B  MOV EAX, [+0x1198]    — feeds GraphicWin_init's `width` arg
  3. 0x4ADF10  MOV ECX, [+0x1198]    — feeds Buffer_copy_4's `srcW` (loop1)
  4. 0x4ADF41  (similar)              — also in loop1 path
  5. 0x4AE159  MOV ECX, [+0x1198]    — feeds Buffer_copy_4's `srcW` (loop2)
  6. 0x4AE18A  (similar)              — also in loop2 path

[SetupWin+0x119C] (strip_H = -75) consumers:
  1. 0x4ADEFC  MOV EDX, [+0x119C]    — used as -strip_H for Buffer_copy_4 srcH (loop1)
  2. 0x4ADF2D  SUB EDI, [+0x119C]    — loop1 vertical step (EDI += 75)
  3. 0x4ADF95  MOV ECX, [+0x119C]    — feeds another draw call
  4. 0x4AE042  MOV EDI, [+0x119C]    — height-related computation
  5. 0x4AE08D  MOV EAX, [+0x119C]    — height-related computation
  6. 0x4AE145  MOV EDX, [+0x119C]    — Buffer_copy_4 srcH (loop2)
  7. 0x4AE176  SUB EDI, [+0x119C]    — loop2 vertical step

AND a derived value lives in EAX from 0x4ADE1C (`ADD EAX, EDI`):
  EAX = menu_total_height = strip_H × num_items + adjustment
  Consumed at:
    - 0x4ADE48  SUB ECX, EAX         — Y position (ScreenHeight - menu_total_height)
    - 0x4ADE4A  PUSH EAX             — GraphicWin_init's `height` arg
```

## Why this map matters

The same field [+0x1198] needs to read **two semantically different values** at different sites. At strip-blit sites it needs to be 354 (matches actual FLC pixel data; passing a larger value would read past allocated source pixels and crash). At GraphicWin_init it needs to be 995 (scaled, so the window is wide enough). **You cannot solve this by writing scaled values into the field after FLC load** — that breaks the srcW reads. The solution is per-site thunks: each consumer that needs a scaled value gets its OWN tiny thunk that scales at the point of read.

The MUL/ADD chain that computes `menu_total_height` happens BEFORE the field-read sites, so scaling EAX there requires either patching the multiplication itself OR scaling EAX in-place at a later (otherwise-unused) site. We chose the latter — see [[feedback-dual-purpose-thunk]].

## What's applied (8 sites + 6 thunks in a 512-byte code cave at 0x668200)

Sites (all in patches.yaml under group `menu_strip_scaling`):
- `0x4ADFA5` — rect-width literal `MOV EAX, 0x12C` → CALL thunk that returns scaled 300
- `0x4AE570 / 0x4ADF28 / 0x4AE171` — strip-blit `CALL Buffer_copy_4` → CALL stretching thunk that calls Buffer_copy_3 with scaled dst dims
- `0x4ADF2D / 0x4AE176` — loop `SUB EDI, [+0x119C]` → CALL thunk that adds scaled_H to EDI
- `0x4ADE4B` — `MOV EAX, [+0x1198]` (GraphicWin width) → CALL thunk returning scaled in EAX
- `0x4ADE25` — `MOV EDI, [+0x1198]` (X-position math) → **dual-purpose** CALL thunk: scales EAX in-place (menu_total_height) AND loads scaled strip_W into EDI

Thunks (all in `_SELFMOD` cave at 0x668200, total 240 bytes used of 512 reserved):
- `scale_uniform @ +0x00` — shared helper, EAX in / EAX out, computes `dim × min(W/1024, H/768)`
- `thunk_scale_rect_width @ +0x60` — for site 0x4ADFA5
- `thunk_strip_blit_stretched @ +0x80` — Buffer_copy_4 → Buffer_copy_3 with scaled dst (NO Buffer_resize)
- `thunk_advance_edi_by_scaled_h @ +0xF0` — for loop-advance sites
- `thunk_load_strip_w_into_eax @ +0x110` — for GraphicWin width arg
- `thunk_load_strip_w_into_edi @ +0x120` — dual-purpose, see above

The cave also requires bumping `_SELFMOD`'s VirtualSize from 0x415D to 0x4400 (patcher does this automatically via `extends_section_virtual_size: true`).

## Remaining work (next)

1. **Text rendering** — visible text inside each strip is drawn at vanilla font size (small) and positioned ~vertically too high. Likely a Buffer_write_cent_l_7 / font call in SetupWin_draw_item line ~209 of the decomp (`Buffer_write_cent_l_7(pcVar2, &local_14, sVar3)`). The text-position math uses `local_14 + 0xc` and `local_10 + 4` (per the decomp) plus the rect from `Spot_get_rect`. Investigate: what's in `local_14`/`local_10`? Probably from Spot_get_rect which was already patched (rect-width = 843), so text X-centering should track... but text font size is separate. SMAC probably has a font scale somewhere. Start from the Buffer_set_font / Buffer_write_cent_l_7 call sites.
2. **The conditional adjustment** for `local_1b4[0] != '\0'` in SetupWin_do_menu_rightside (the +95 vs +0 to menu_total_height) — confirm we handle both code paths. Currently scaling appears to fire only on the `false` branch (525→1476 in the log). If a `true` branch ever fires, scaling might still apply correctly because our thunk scales whatever EAX value comes in, but verify.
3. **Other menus that use SetupWin** — `config_game`, `custom_planet`, `size_of_planet`, `map_menu` all share the SetupWin code path. Patches should apply identically to them. Test at least one to confirm.
4. **Buffer_copy_3 verification** — does `GraphicWin_init` actually size the dest Buffer based on its width/height args (a4, a5)? We assumed yes after removing the per-iteration Buffer_resize, and the visual got dramatically better. But the Frida log was added (read `[dest+0x80]` and `+0x84`) to confirm — capture that next launch.

## Planet-preview background = the SetupWin DECORATION (Frida-confirmed 2026-05-29)

The "mangled planet" on the planet-customization screens (e.g. Select Ocean Coverage) is the SetupWin **per-item decoration** — the same `[ESI+EBX*4+0xa1c]` slot array whose gate (`0x4AE66E`, our `CMP 0x400→0xF00` patch) we already opened. On those screens the deco slots ARE populated (NULL on main menu). Ocean screen loads `S{1,2,3}L1C1.PCX` (404x768 each; negative-H top-down) and draws each via **`CALL Buffer_copy_4 @ 0x4AE710`** — a **1:1 native blit** into the 3840x2160 backbuffer at right-aligned `dstXY=(3436,0)` (3436 = 3840−404). So it's undersized/top-right, not scaled. Frida `frida_custom_planet.log` (hook_custom_planet.js): `Buffer_copy_4 [S1L1C1] from 0x4ae715 dstXY=(3436,0) WxH=404x768`, ScreenWidth=3840.

Draw code (from dump_text_deco.out): two paths gated by `Buffer_get_pixel(deco,0,0)==9` (transparency key): opaque → `Buffer_copy_4 @ 0x4AE710`; keyed → `Buffer_draw_2 @ 0x4AE6D5` (the ocean planets take the opaque path). After the blit, `GraphicWin_soft_update @ 0x4AE73B` is called with the SAME native decoX/Y/W/H (0x4AE715–0x4AE73B) — marks the dirty region.

**APPLIED & WORKING (2026-05-30).** Three sites in group `menu_strip_scaling`, all resolution-independent:
1. `decoration_gate @ 0x4AE66E` (renamed `...cmp_1024_to_always`): `CMP EAX,0x400` → `CMP EAX,EAX` (`3B C0 90 90 90`) so the deco renders at ANY width, not just 800/1024.
2. `decoration_blit_redirect @ 0x4AE710`: `CALL Buffer_copy_4` → `thunk_deco_blit_stretched` (cave +0x300).
3. `decoration_soft_update_scaled @ 0x4AE715` (43 bytes): the `GraphicWin_soft_update` arg-setup → `thunk_deco_soft_update` (cave +0x3B0).

**KEY INSIGHT — the deco uses ANAMORPHIC (per-axis) scaling, NOT `scale_uniform`.** This is the ONE documented exception to [[feedback-smac-aspect-ratio]]. Frida (`hook_custom_planet.js`) proved the ocean background `xopeninga.pcx` is blitted `1024x768 → ScreenWxScreenH` anamorphically (`Buffer_copy_3 @ 0x589aed`, ×3.75 wide / ×2.8125 tall at 4K). The S{1,2,3}L1C1 planet is an **overlay on that stretched background**, so to register with the background's planet slot it must match the SAME stretch. Two new helpers: `scale_x(v)=v×ScreenWidth/1024` (cave +0x370), `scale_y(v)=v×ScreenHeight/768` (cave +0x390). Deco width via scale_x, height via scale_y; X repositioned to hold the right edge `newDstX = dstX + srcW − scaleX(srcW) = ScreenWidth − scaleX(srcW)` (=2325 at 4K, exactly the background slot `620×3.75`). Uniform scale gave a flush-right but mis-left-aligned seam — wrong because the background is anamorphic.

**The soft_update IS required (not cosmetic).** `GraphicWin_soft_update @ 0x4AE73B` (sole caller) refreshes only the region it's passed; vanilla passes the NATIVE 404×768 rect, so on option-hover only that corner re-presented → stale "rectangles" of the previous planet. `thunk_deco_soft_update` refreshes the SCALED rect (`X'=ScreenWidth−scaleX(srcW), W'=scaleX(srcW), H'=scaleY(srcH)`). Frida-confirmed the soft_update window is the **full-screen backbuffer GraphicWin** (`this`+0x444=Buffer 3840×2160, clip `{0,0,3840,2160}`) so the widened rect is bounds-safe.

**GOTCHA that cost a hard crash:** hand-assembled `MOV EAX,[EDI+0x80]` as `8B 47 80` (disp8) — but 0x80 sign-extends to −128, reading `[EDI−0x80]` = garbage → junk soft_update region → fault. Offsets ≥0x80 MUST use disp32 (`8B 87 80 00 00 00`). See [[feedback-thunk-disp32-offsets]]. (The deco-blit thunk was unaffected — its offsets are small `[EBP+..]` values that fit disp8.)

New engine symbol: `GraphicWin_soft_update=0x5D5720` (__thiscall(this,X,Y,W,H), RET 0x10; clips region to `this+0x474` rect then GDI-blits via `[0x669304]`). New cave thunks: `thunk_deco_blit_stretched@0x300`, `scale_x@0x370`, `scale_y@0x390`, `thunk_deco_soft_update@0x3B0`. CAUTION: 0x4AE710/0x4AE66E are generic SetupWin deco code; the EBX deco-index `<0` check naturally skips non-preview menus (main menu deco slots NULL → no draw, confirmed). `Buffer_draw_2` keyed path (0x4AE6D5) still unscaled.

## Canonical artifacts

- `D:\SmacxUi\work\patches\patches.yaml` — the patch database
- `D:\SmacxUi\work\scripts\assemble_thunks.py` — thunk source + asm comments + byte emission
- `D:\SmacxUi\work\scripts\apply_patches.py` — patcher with group/cave/symbol/PE-extension support
- `D:\SmacxUi\work\scripts\hook_setupwin.js` — Frida instrumentation (including ACCESS_VIOLATION handler, dest Buffer W/H dump)
- `D:\SmacxUi\work\find_call_sites.out` — precondition dump (Buffer_copy_3/4 RET-imm convention, ECX semantics at strip-blit sites)
- `D:\SmacxUi\work\investigate_destbuf.out` — full disasm context for all SetupWin_do_menu_rightside calls + every [+0x1198]/[+0x119C]/[+0x444] reference
- Related notes: [[project-smac-ui-scaling]], [[project-smac-openitem-strip]], [[feedback-menu-strip-coupling]], [[feedback-buffer-resize-per-blit]], [[feedback-dual-purpose-thunk]], [[feedback-smac-aspect-ratio]], [[project-smac-patcher-v02]]

## Why this approach works as a template for other menus

The coupling pattern (one asset → six display-dim consumers) is almost certainly how SMAC built every FLC-driven menu element. For each future FLC-driven menu the recipe is:
1. Run `investigate_destbuf_sizing.py`-style script on the new SetupWin/GraphicWin function to map all reads of the equivalent fields.
2. Identify the GraphicWin_init call site and the loop-advance sites.
3. Replicate the 5 thunk patterns (rect-width, strip-blit-stretched, loop-advance, width-into-EAX, dual-purpose-EAX-scale+width-into-EDI). Most can be reused unchanged — they're parameterized by the field offsets which are the same convention across SetupWin instances.
4. Add to a new `*_scaling` patch group, share the same code cave.

How to apply: when the maintainer describes a new menu-scaling task, search for [SetupWin+0x1198] / [SetupWin+0x119C] reads in the target function via Ghidra and apply the coupling-map template. Don't re-investigate from scratch.
