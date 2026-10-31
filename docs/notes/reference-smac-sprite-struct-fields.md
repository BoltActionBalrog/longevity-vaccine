---
name: reference-smac-sprite-struct-fields
description: SMACX Sprite struct field offsets for scaling/blitting — the engine uses +0xC/+0x10/+0x14 + offsets, NOT +0x18/+0x1c
type: reference
---

SMACX `Sprite` struct (terranx.exe), confirmed via the `Sprite_blit_scaled_core` (0x5E4B9A) decompile + a live Frida dump of the faction leader-preview sprites:

- `+0x00` ppszFileName
- `+0x04` pcBits — pixel data (palette indices)
- `+0x08` cTransparentIndex (BYTE) — the key
- `+0x0C` iSpriteWidth2 — **ROW PITCH** of pcBits (this is what the blit uses to step rows; stored in DAT_009b6070)
- `+0x10` iSpriteWidth — **blit WIDTH** (the opaque content width)
- `+0x14` iSpriteHeight — **blit HEIGHT**
- `+0x18` iWidth — logical CANVAS width incl. transparent margins (do NOT use as blit width)
- `+0x1C` iHeight — logical canvas height
- `+0x20` iLeftOffset — draw x offset (content's left within the canvas)
- `+0x24` iTopOffset — draw y offset
- `+0x28` fObj1Exists

The blit core does: `dest.left = x + iLeftOffset`, `right = left + iSpriteWidth`, `bottom = top + iSpriteHeight`, and addresses source as `pcBits + dx + dy*iSpriteWidth2`. So a scaled draw places the content at `((x+iLeftOffset)*num/den, (y+iTopOffset)*num/den)`, size `iSpriteWidth*num/den × iSpriteHeight*num/den`.

**GOTCHA that bit item #1:** the faction preview sprite is a 245×70 image (`+0x10`/`+0x14`) at offset (6,10) (`+0x20`/`+0x24`) inside a 258×90 canvas (`+0x18`/`+0x1C`), pitch 245 (`+0xC`). A naive scaler that reads stride=`+0x10`, w=`+0x18`, h=`+0x1c` (the offsets [[project-smac-a5-native-frame-thickness]]'s `thunk_portrait_avg` happens to use) loops 258 wide over a 245-pitch buffer → every row drifts 13px → the whole portrait atlas smears in. `thunk_portrait_avg` only works because its square quote portrait has `+0xC==+0x10==+0x18` and zero offsets — it is correct ONLY for that sprite; do NOT reuse it as a general scaler.

The general edge-safe scaler `thunk_sprite_scale_nn` reads the engine fields above; see [[reference-faction-picker-component-map]] and the scaling-sprites skill. Verify any new sprite scaler's field choices against this list (or Frida-dump the actual sprite) before trusting +0x18/+0x1c.

**TWO BACKING VARIANTS (2026-08-22, council v14 crash):** `pcBits` is only populated for memory-backed sprites (like the faction previews above). Popup ART sprites are **filename-backed**: `pcBits` stays **NULL forever**, and the sd2 blit core (0x5E4B9A) gates on `[sprite+0]` (ppszFileName) and resolves the pixels through the canvas manager @0x9B6080 (`call 0x5D7DE0(namePtr,0,0xA,0xEC)` — nonzero return short-circuits, else falls through to the 0x5D84C0 blit). Additionally the `[popup+0x3168]` draw fn fires **before** the art is loaded (draw-state multiplicity). NEVER dereference `pcBits` without a null check / knowing which variant you hold — v14's council restripe AV'd exactly there. See [[project-smac-council-popup]], [[feedback-draw-state-multiplicity]].

**PALETTE INDEX REMAP ON LOAD (2026-08-22, council v15 no-op):** the canvas manager shifts **every PCX palette index +10 mod 256** when loading art (the 10 reserved Windows system-palette slots). Consequence: a restripe/remap key measured from a PCX file's OWN palette will match NOTHING in a dest buffer (council v15: PCX 250/230 → dest 0x04/0xF0). **Fixed-content-index keys must be measured in the DEST buffer's index space** — either dump the live dest rect, or map PCX idx → (idx+10)&0xFF. Ground truth for the runtime palette on disk: the `hof_*.pcx` files (in-game screen dumps) carry it verbatim.
