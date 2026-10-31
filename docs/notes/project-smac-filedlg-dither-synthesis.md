---
name: project-smac-filedlg-dither-synthesis
description: File-picker dither — DONE+LOCKED (7d9ba26c): v6 list scanline SYNTHESIS + P3e frame-baked dither REMAP; solid flatten v1-v5 rejected; key laws (P=(g+4)>>3, remap-only-the-pair) reusable
type: project
---

File-picker LOAD/SAVE dither: **DONE + VERIFIED RELEASE LOCK, MD5 7d9ba26c, 2026-07-01** — user-confirmed
in-game at ALL resolutions (list + header/title-strip/margins one uniform stripe field). CHANGELOG'd.

**User verdict history:** banding rejected → solid flatten tried (v1-v5) → REJECTED ("pristine has a scanline
pattern") → v6 = synthesize uniform-run scanlines at device density → user then flagged the HEADER beat (the
v6 known limit) → P3e fixed it → all-res confirmed. (A "bright seam mid-dither" report was RETRACTED; the
list interior had scanned pixel-perfect — don't reopen.)

**Two-part fix (details in patches.yaml P3d/P3e comments):**
- **v6 (list):** `thunk_ensure_stripes` builds two 0x800×P scratch striped tile Buffers once per g
  (crt_malloc 0x588 + Buffer_ctor + Buffer_resize + Buffer_set_clip + 2× Buffer_fill_3); P=(g+4)>>3 device px
  (3 @g22/g25, 5 @g40 = the 4K title-strip look), navy 0xC4 top hN=ceil(P/2), black 0x41; selected 0xE0/0xE1.
  `thunk_filedlg_rowbg_v6` swaps FileDlg_draw_row's tile sprite (keeps vanilla srcOff==dest absolute anchor);
  `thunk_copy4_stripes` replaces the two Buffer_copy_4 backdrop captures (0x60BBBA/0x60C421) with Buffer_tile.
- **P3e (header/margins/frame rings):** the dither OUTSIDE the list is BAKED INTO the frame 9-slice ART
  (d618 title band = all dither; every stroke carries a dithered ring at the art-piece thickness) — NOT a
  panel fill. `thunk_frame_enlarge` (RELOCATED pcave2 0x2560→0x30A0) stashes the blit dest rect into
  g_fe_*, and on the NN path only, calls the dither remap after the blit: rewrites ONLY dither-pair pixels
  in the dest rect to the device-row stripe colour (y mod P < hN → navy; same law+same-buffer phase as v6
  → continuous field). Other indices (strokes/art) untouched. BILINEAR (ornate outer) path skipped: blend
  re-quantises dither to 197/198 + metallic art has legit darks.
  **SUPERSEDED MECHANISM NOTE (2026-07-03, build c592d318):** the original `thunk_fe_dither_remap`
  (0x2FD0, navy-only, g_filedlg_active-gated) is FREED — replaced by the UNGATED content-keyed
  `thunk_fe_pair_remap` (pcave2 +0x3860) that fires for EVERY menu (3 pairs; navy keyed on a src-C4
  pre-scan). Filedlg output unchanged by construction (its NN frames are all C4-rich). Never re-gate it
  on g_filedlg_active. See [[feedback-dither-pair-ambiguity]] + skill scaling-frames §7b.

**Reusable laws:** (1) never resample a 1px periodic dither — regenerate at device density (tile-swap for
tiled fills, colour-keyed remap for art-baked fills); (2) remap-only-the-pair preserves overlapping art with
zero masking; (3) anchor stripe phase per-buffer (y mod P from buffer origin) so independently drawn layers
in the same buffer fuse seamlessly. Also captured in skill scaling-frames.

**Pipeline facts (audit-corrected):** NO whole-UI stretch exists — window+list buffers are DEVICE-res,
present 1:1 (Buffer_draw_2 num=1/den=1); the ONLY stretch is our own frame-enlarge funnel. Buffer_tile's
"sprite" arg is just a Buffer (reads only W+0x80/H+0x84). Buffer data ptr +0x54, stride +0x4a8.
Colour facts: pristine interior blend (6.6,12.3,19.6); idx196 (13,23,36) = game's solid navy (filename box);
idx197 (11,18,24) nearest navy-hued solid; idx198 (12,12,16) reads BLACK. Stripe duty at P=3 is 2/1 = 67%
navy vs pristine 50% (slightly brighter field; user accepted — flip to 1/2 is a 2-byte change if ever asked).
Dead v5 thunks (thunk_filedlg_rowbg @0x2CB8, thunk_copy4_flatten @0x2D18) remain in the cave unreferenced.
See [[project-smac-loadsave-filedialog]], [[feedback-dither-no-resample-on-upscale]], (a private note).
