---
name: feedback-parity-reblit-combs-diagonals
description: Pair-granular parity re-blit (thunk_cw_portrait) combs crisp 1-col-per-row diagonals in scanline-dithered ICONS; use centre-NN shape + dest-row-parity shade via the art's own pair LUT
type: feedback
---

For a scanline-dithered sprite with a CRISP shape (icon, arrow), do not reuse thunk_cw_portrait / thunk_parity_reblit. Take the SHAPE from centre-aligned NN on both axes and the SHADE from dest-row parity through a light<->dark pair LUT read from the sprite's own pixels at runtime (runtime palette may be remapped vs the PCX, e.g. HUD fill 186/55 -> 196/65).

**Why:** the parity re-blit picks each dest pair's light and dark rows from DIFFERENT source rows; a diagonal stepping one column per source row then alternates extents row by row = comb teeth (HUD event-log arrow, 2026-09-18, user called it "blocky"). Invisible on portraits (soft content). Fixed by t_msg_icon own blit, law scaling_laws.msglog_icon_pixels, exe a7741790: 0 px off the law at 4K/1600/1920. Same family as [[feedback-parity-nn-single-row-art]] and [[feedback-dither-no-resample-on-upscale]].

**How to apply:** portraits/photos -> parity re-blit is fine; 2-class pixel art under a scanline overlay -> NN shape + parity shade. Acceptance check that worked: place the law's pixel grid on the screenshot and count mismatches per colour class (scratch ev_meas3.py pattern) — exact, no eyeballing. Event-log facts: [[project-smac-combat-console]] sibling; MessageWin 0x7F67F8, row stride (B-T)/5 and text indent (B-T)/4 are rect-derived (already scale), font = direct Font_init site 0x471DA7 -> thunk_hud_font.
