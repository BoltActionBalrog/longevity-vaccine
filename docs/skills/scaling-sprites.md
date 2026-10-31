---
name: scaling-sprites
description: Use when scaling, enlarging, or upscaling any sprite, image, icon, or keyed bitmap to high resolution in the SMACX patcher (not just 9-slice frames).
---

# Scaling sprites/images at hi-res in the SMACX UI (bounds-safe)

The engine has **two** ways to scale a `Buffer` up, and one of them crashes off-4K. Pick the safe one.

## The trap: the engine NN-EXPAND path is NOT bounds-safe

`Buffer_draw_2(0x5d84c0)` / `Sprite_draw_2(0x5e4b4a)` / `Sprite_blit_scaled_core(0x5e4b9a)` scale a
sprite by `num/den`. When `num>den` (enlarge) at a **fractional** ratio (e.g. 22/16 @1080p, not the
clean 40/16=2.5 @4K) the expand path's unrolled inner loop writes **one row past the dest buffer** — a
partner-row `+stride` store with no per-write bottom clip. 4K's buffer headroom hid it; lower
resolutions page-fault. So **never enlarge into a tight or caller-owned dest with `Buffer_draw_2`'s
`num>den` mode.** (The `num==den` 1:1 keyed blit IS safe — it clips normally. Only EXPAND is the hazard.)

## The fix: scale through GDI StretchBlt instead

`Buffer_copy_3(0x5d9610)` is literally `GDI StretchBlt(SRCCOPY)`. GDI **clips the blit to the dest
bitmap**, so it can never write OOB at any resolution, and on an 8-bit palettized DIB it scales
**non-averaging** → the key/palette index survives (clean keying). This is recorded on `Buffer_copy_3`
in `terranx.h`. Confirmed by decompile (`decomp_copy3.txt`): no pixel loop, just `StretchBlt`.

Use the reusable primitive **`thunk_keyed_stretch_blit`** (menu_strip_thunks +0x470, `__cdecl` RET 0x2C):
```
keyed_stretch_blit(srcBuf, destBuf, srcX,srcY,srcW,srcH, dstX,dstY,dstW,dstH, key)
```
It `Buffer_resize`s a dedicated scratch (`g_scratch_buf`) to **exactly** `dstW×dstH`, `Buffer_copy_3`
(StretchBlt) stretches src→scratch at that size, then `Buffer_draw_2` keyed-blits scratch→dest **1:1**
(the safe `num==den` path). Two distinct scratch buffers exist on purpose — `g_scratch_buf` (this
primitive) vs `g_frame_buf` (the small-frame render) — so a multi-blit thunk never resizes a buffer it's
mid-blit on. See [[feedback_buffer_resize_per_blit]], [[project_smac_erosive_moons]] (first user).

## The OTHER trap: ALL nearest-neighbour scaling (incl. StretchBlt) DROPS thin baked-in borders at fractional scale

Bounds-safe ≠ border-safe. `Buffer_copy_3` is `StretchBlt(SRCCOPY)` = **nearest-neighbour**, and so are
`Sprite_draw_2` / `Sprite_blit_scaled_core`. NN at a **fractional** factor exhibits the named defect
**"thin-line disappearance"** (USPTO US5,539,534; W3C CSS WG; OpenRCT2 #6568): a 1px source edge survives
or vanishes depending on the sampling **phase** of each output column/row, and because a whole vertical
edge shares one phase, the entire edge can drop. At **integer** factors the phase is aligned so the line
always survives — which is why a sprite with a 1px baked-in frame looks fine at ×2/×2.5 (4K, g40) but its
right/bottom edge **blacks out at ×1.5625** (1600×1200, g25). This is independent of the OOB crash above;
`thunk_keyed_stretch_blit` fixes the crash but NOT this.

**When it bites:** any sprite/icon with a hard 1px border, outline, or dithered edge **baked into the
source bitmap**, scaled by a non-integer `g/16`. (e.g. the faction leader portrait's green picture-frame.)

**The fix is AVERAGING, not NN.** Resample the source with a palette-aware bilinear average so a sub-pixel
edge **blends into** the output instead of being dropped. 8-bit indexed art can't be averaged in the index
domain (indices aren't linear) — average in **RGB** then map back to the nearest palette index:

1. For each dest pixel, map back to source `(sx,sy) = dxi*den/num`; take the 2×2 source neighbourhood.
2. **Coverage = the NEAREST source texel**: if it's the key, leave the dest pixel (transparency identical
   to NN — never average across the key edge or you smear the silhouette).
3. Otherwise bilinear-blend the **non-key** neighbours' RGB (weights `(1∓fx)(1∓fy)`), `round`, then
   nearest-palette-index — **SKIPPING the key index** — and write. The key's stored RGB is a LIE
   (key 9 = (9,0,0) ~ pure black): a dark blend that wins at the key becomes TRANSPARENT in the
   window composite and the background punches through (the Morgan-portrait map-speckle bug,
   2026-09-01). Exclude every reserved/special index from a quantizer's candidate set.

Palette: use **the dest Buffer's own synced DIB color table at `dest+0xA4`** (`RGBQUAD[256]`, filled
by `Buffer_sync_to_palette` 0x5DE8F0 on every GraphicWin+0x444 draw-context setup, gen-stamped +0x4a4
vs Palette +0x400) — the per-context display truth; channel order cancels when blend + search share
one table. The global `Palette` at **`0x94c590`** (==GDI HPALETTE `0x9b8178`, `PALETTEENTRY
colors[256]` at +0) is NOT guaranteed live in every screen context — a table validated on the menu
screens can be stale in-game, and identity-maps-to-itself hides it until the first real blend.
(Live-capture: hook `Buffer_sync_to_palette` 0x5DE8F0, `[esp+4]`=Palette*.
NOTE corrected identities: **65=(0,0,0) black, 198≈black, greens are 31/34** — an earlier "65=green" note
was wrong and misdirected the whole analysis. Verify palette indices live, never assume.)

This averaging primitive is reusable for **any** scaled sprite with baked-in fine detail — see
[[project_smac_a5_native_frame_thickness]]. Prototype it in Frida first (compute the blend in JS, write
over the dest in `onLeave`) so you can SEE it in-game before committing asm — that's how A5 was validated.

### Crisp alternative when averaging is unwanted: output-driven edge-clamped NN

Averaging blurs — sometimes the user wants the result to stay **crisp/pixelated** (the faction leader-
preview: a bilinear variant was tried and **rejected as "worse"**). There's a second cure for the edge-drop
that keeps NN sharpness: the drop only happens because the engine's NN is **source-driven** (a DDA that
walks the source and can drop the last src col/row's output run at a fractional ratio). Flip it to
**output-driven**: iterate every *dest* pixel and inverse-map a **center-sampled, EDGE-CLAMPED** source
index (`sx = ((2·dxi+1)·sw)/(2·dstW)`, clamp `[0,sw−1]`) so the last dest col/row **always** reads the last
src col/row → the baked edge survives, palette index copied verbatim (crisp, full-strength thin lines).
Reusable primitive **`thunk_sprite_scale_nn`** (pcave2 +0x2150) — a literal drop-in for `Sprite_draw_2`
(`__thiscall ecx=Sprite*`, stack `dest,key,x,y,num,den`, RET 0x18; computes `dstW/H=srcW/H·num/den`). Reads
ENGINE Sprite fields (pitch `+0xC`, blit w `+0x10`, blit h `+0x14`, offsets `+0x20/+0x24` — **NOT**
canvas `+0x18/+0x1c`, see [[reference_smac_sprite_struct_fields]]). Full contract in `patches.yaml`. To
reuse: set `num/den`+`x/y` on a `Sprite_draw_2`-style stack then `push {abs32:thunk_sprite_scale_nn}; ret`.
Used by the faction top-3 preview buttons (`thunk_faction_portrait`).

### The faction-portrait draw path (confirmed live — don't trust the static sig)
`Sprite_draw_2` (0x5E4B4A) is **`__thiscall`**: `ecx`=Sprite*, stack = `dest, key, x, y, num, den` (its
arg2 is the KEY, not a spriteId — terranx.h's old C sig was wrong). The **source is a `Sprite` struct, not
a `Buffer`**: `data@+0x4` (tightly-packed 8-bit, stride==width), `stride@+0x10`, `width@+0x18`,
`height@+0x1c`, `mask@+0x30`. The faction portrait draws into the faction box `0x940824` at `(10,12)`,
scale `25/16` at g25. Correct gate for a sprite-path fix = `dest==0x940824 && num>den` (g≤16 → native).

## The THIRD trap: a dithered face BANDS under ANY enlarge filter — mandatory regeneration tail

If the source carries the UI's 1px scanline dither (`ae/ee`, `E0/E1`, the navy family), enlarging it
bands — NN hard, bilinear soft — because resampling preserves the source period: a 1px pattern becomes
a `g/16`-px pattern regardless of filter. No filter choice fixes this. Always REGENERATE the dither at
device density after the enlarge: `thunk_fe_pair_remap` over the dest rect, tile swap, or stripe
synthesis (`scaling_laws.stripe_period`: 1-row stripes below g = 22, 2-row from 1080 px high) — mechanisms + the pair-ambiguity rule in [[scaling-frames]] §7. This tail is
MANDATORY on every enlarge path that can touch a dithered surface (cf. `thunk_btn_stripes` /
`thunk_btn_devfill`), in the FIRST build — not a polish pass, never a taste question. Integer 2.5×
(4K) is phase-aligned and often looks clean — that is not evidence; verify at g=22/25.

## Scaling a hardcoded `Sprite_draw_2(…, num=1, den=1)` call — redirect + placement law

Many small UI sprites (toggles, arrows, the chat-scrollbar grip) are drawn by a plain
`call Sprite_draw_2` with `push 1 / push 1` — permanently native. The proven fix is a
**call_target_redirect to a tiny thunk that rewrites the already-pushed args in place** then
tail-jumps (`push {abs32:Sprite_draw_2}; ret`): inside the thunk the args sit at `[esp+4]=dest,
+8=key, +0xC=x, +0x10=y, +0x14=num, +0x18=den`; set `num=g, den=16` (gate `g>16`; `ecx`=Sprite must
survive for the thiscall — `eax/edx` are free). **Changing num/den alone mispositions the sprite** —
the engine computed x,y for the NATIVE size, so also apply the site's placement law:

| The native x,y encodes… | Adjustment in the thunk |
|---|---|
| **centered** in a (scaled) rect | `x -= sprW·(g−16)/32`, `y -= sprH·(g−16)/32` (`sprW/H = [ecx+0x18]/[ecx+0x1C]`) — chat-scrollbar grip `thunk_sb_thumb` |
| **right-edge anchored** (`x = rectR − K`) | keep the right edge: `x += K − K·g/16` — roster arrows `thunk_nw_blit_right` |
| **gap after text** (`x = text_end + K`) | scale the additive constant: `x += K·g/16 − K` — settings arrows `thunk_nw_blit_gap` |

That third row is an instance of a recurring project law: **a native ADDITIVE constant inside
otherwise-scaled geometry reads as a defect at hi-res** (arrows glued to text, un-wrapping lines,
button rows riding low — the +3 arrow gap, the −10 wrap slack, the OK-gap 9 were all this). Scale
the constant `×g/16`; everything is identity at g=16 by arithmetic, no extra gate needed for pure
multiplies.

### Centre the DRAWN content, not the sprite canvas (2026-09-13, BASE LOCATOR ring)

A sprite's content usually sits inside a larger canvas at its own draw offsets (`+0x20/+0x24`) with a
blit size (`+0x10/+0x14`) smaller than the logical `+0x18/+0x1C` dims — the four blink ring frames are
(off,w) = (4,4) (3,6) (3,6) (2,8) inside 12×12. `thunk_sprite_scale_nn` draws that content at
`x + floor(off·num/den)` with width `floor(w·num/den)`, so centring the CANVAS (`x = C − 6r`) leaves the
drawn content biased by the two floors: −0.75 px at 2g/16 = 3.125 (1600), −0.5 at 2.75 (1920), 0 at
5.0 (4K) — visible as "slightly off at non-4K". Law (`scaling_laws.blink_place` / `blink_frame_span`):
per stamp, read the frame sprite's own fields and place `x = half_down(2C − (2P + W), 2)` with
`P = floor(off·num/den)`, `W = floor(w·num/den)`, so `x + P + W/2 == C` within the half pixel for every
frame. When the target C is itself a stretched rect, keep the denominator: `x = hd(cx2·win − (2P+W)·buf,
2·buf)`. Also route the "lawful" and the "big" variants through the SAME scaler — the engine core's
frame rounding under its SCALE globals is not ours to know.

## Drop-in pattern: replace a crashing enlarge call in place

If existing code already does `Buffer_draw_2(src; dest, key, X, Y, num, den)` to enlarge, you don't have
to restructure it — write a thunk with the **same `__thiscall` contract and `RET 0x18`** that forwards to
`thunk_keyed_stretch_blit`, and just retarget the `CALL`. Worked example **`thunk_frame_enlarge`**
(pcave2 +0x2A0): `ecx=src`, stack `dest,key,X,Y,num,den`; computes `dstW=srcW*num/den`,
`dstH=srcH*num/den`; calls the primitive; `ret 0x18`. Identical geometry to the old enlarge, zero blast
radius (the shared engine blit is untouched — 105 callers stay on the original).

## The sharp edges

- **Height field `[buf+0x84]` is stored NEGATIVE** (top-down). NEG it for `srcH`/`dstH`. Width
  `[buf+0x80]` is positive. **This sign propagates to SAVED COPIES** — e.g. a FlatButton's `[esi+0x4c8]`
  and the global `g_btn_origH` (filled from it) are negative despite the name "origH". Always NEG before
  using one as a positive dimension **or to derive a row offset** `(h−s)·stride`: a negative height there
  becomes a large-negative offset → **wild OOB write → crash** (it crashed entering the faction menu at 4K;
  this is what 2dscale already does — `mov eax,[g_btn_origH]; neg eax` — to feed the StretchBlt `dstH`).
  See [[feedback-negative-height-saved-copy]]. When a name says "height/origH", verify its SIGN at the source.
- **Size the dest to the EXACT scaled height.** "Losing the bottom row" is real but avoidable: NN
  *up*scale **duplicates** rows (never drops one), so the only way to lose a meaningful row is to
  under-size/clip the dest. `keyed_stretch_blit` resizes its scratch to `dstW×dstH` exactly, so nothing
  is clipped. If a result looks ~1px short at the bottom/right, something upstream under-sized or
  clamped the dest — fix the size, don't accept the truncation. (Second cause when a *separate clean
  fill overlays* a StretchBlt'd frame: StretchBlt rounds the right/bottom strokes 1px toward the edge,
  so a symmetric inset clips them — use an **asymmetric N / N+1 inset**, see [[scaling-frames]] §4.)
- **Carry the key through.** The final composite uses the `key` you pass: real index / `-1` = copy-all
  (opaque); transparent index (`9`) = keyed out. Same rule as [[project_smac_frame_strip_key]].
- **Anamorphic vs uniform.** Per-axis (overlay on a stretched bg, e.g. moons) → compute `dstW`/`dstH`
  with `scale_x`/`scale_y` and call the primitive directly (`thunk_deco_keyed_scaled`). Uniform → derive
  both dims from one `num/den` (`thunk_frame_enlarge`). Either way the primitive is the same.

## Decision rule

| Need | Use |
|---|---|
| Enlarge a **flat / no-thin-detail** sprite into ANY dest, any resolution | `thunk_keyed_stretch_blit` (StretchBlt path) — bounds-safe NN |
| Enlarge a sprite with a **1px baked-in border/outline/dither** by a fractional factor, blur OK | **palette-aware bilinear AVERAGING** resampler (NN drops the edge) |
| Same, but must stay **crisp/pixelated** (averaging rejected) | **`thunk_sprite_scale_nn`** — output-driven edge-clamped NN (keeps the last row/col) |
| Enlarge anything whose face carries the **scanline dither** | the chosen enlarge above **+ the mandatory §THIRD-trap regeneration tail** (`fe_pair_remap` / re-tile — [[scaling-frames]] §7) |
| Swap a crashing `Buffer_draw_2` enlarge call with minimal edits | a `thunk_frame_enlarge`-style drop-in → the primitive |
| 1:1 keyed composite (no scaling) | `Buffer_draw_2` directly (1:1 is safe) |
| Thicken a 9-slice frame stroke | render small into `g_frame_buf`, then enlarge via the above — see [[scaling-frames]] |

Never reach for `Sprite_blit_scaled_core`'s expand path or `Buffer_draw_2 num>den` into a fixed buffer.
**Two independent NN hazards: OOB crash (use StretchBlt) AND thin-border drop (use averaging). StretchBlt
cures only the first.**

## Sites in this repo (all confirmed in-game)

- `thunk_keyed_stretch_blit` / `thunk_ensure_scratch` / `g_scratch_buf` — the primitive (menu_strip_thunks +0x470/+0x4D0/+0x510).
- `thunk_frame_enlarge` (pcave2 +0x2A0) — drop-in enlarge for the 3 frame-thickening thunks; build 100e9356, 2026-06-07.
- `thunk_deco_keyed_scaled` (menu_strip_thunks +0x410) — erosive moons, anamorphic.
- `thunk_sprite_scale_nn` (pcave2 +0x2150) — reusable edge-safe **crisp** NN (output-driven, edge-clamped);
  faction top-3 preview buttons via `thunk_faction_portrait` (+0x2100). Full contract in `patches.yaml`.
- `thunk_nw_toggle` / `thunk_sb_thumb` / `thunk_nw_blit_right` / `thunk_nw_blit_gap` (pcave2
  +0x4960/+0x4BB0/+0x48F0/+0x4C00) — the `Sprite_draw_2(1,1)` redirect + placement-law family (NetWin lobby).
