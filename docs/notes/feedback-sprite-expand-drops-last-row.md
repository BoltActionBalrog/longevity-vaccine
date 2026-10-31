---
name: feedback-sprite-expand-drops-last-row
description: Engine Sprite scaled-expand leaves the LAST dest row unwritten at fractional num/den — key-9 gap row lets the map bleed through (red streak lines); invisible at 4K because the gap lands on the dark stripe phase
type: feedback
---

At fractional scale (num/den not integer, e.g. 25/18 or 22/16), the engine's Sprite expand path (Sprite_fill_scaling_table Bresenham @0x5EB20F + Sprite_get_clipped_y_table_expand @0x5EABBF, shared by Sprite_blit_scaled_core/Sprite_draw_2 and 6 other Sprite_draw_* wrappers) covers one dest row SHORT of the true scaled height. The dropped row keeps the buffer's key-9 fill, so on a keyed window the MAP bleeds through as a 1px streak per blit (red where the map is red, invisible where dark).

**Why 4K hides it:** at exact 2.5x (18→45) the gap row lands on the dark phase of the strip pattern every time (local row 44 ≡ dark) — user-approved 4K screenshots had the gap all along. Never conclude "no gap" from one background.

**Why:** proven 2026-07-07 on the COMMLINK/MENU dropdown strips: red rows at exactly every strip's last dest row (panel y 57/107/157/207 at g=22), partial x-coverage (map-colored only), color idx 50 absent from the strip art (multi.pcx ground truth).

**How to apply:** any thunk/hook that relies on an engine scaled Sprite blit to fill a region must overdraw the final dest row/col itself (or fully re-synthesize the dest rect, as hook_hudmenu_scale.js synthStrip does). When a 1px background-colored streak appears per blit at non-4K, check this FIRST. See [[feedback-dither-no-resample-on-upscale]], [[project-smac-commlink-panel]].
