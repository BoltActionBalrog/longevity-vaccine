---
name: feedback-dither-no-resample-on-upscale
description: scaling a 1px-scanline dither sprite — NN AND bilinear both band on upscale; reproduce the pattern at native density instead
type: feedback
---

SMAC UI "dither" is a high-frequency 2-row horizontal scanline pattern (alternating 1px rows of two
palette indices, e.g. `ae` even / `ee` odd — same family across the faction bars, list rows, button
caps/body, and the dropdown-arrow background). To scale such a sprite WITHOUT coarse banding you must
NOT resample it.

**Why:** resampling preserves the source's spatial frequency on UPSCALE. A 1px-period scanline blown up
×2.5 becomes a ~2.5px-period band no matter the filter — NN gives hard bands, **bilinear gives soft-edged
bands (still banded)**. Bilinear only anti-aliases the band edges; it cannot remove the banding. (Tried
bilinear on the dropdown via the portrait resampler — failed, still banded, reverted.) Box-averaging over
≥1 scanline period would flatten it to a solid mid-tone (an option if a flat face is acceptable), but that
loses the dither texture.

**How to apply:** REPRODUCE the dither at output (device) resolution so it stays 1px-dense, matching the
rest of the UI:
- Pure tileable dither region (the button bars): shrink→render native→StretchBlt the frame, then
  **re-tile** the dither sprite at device res over the full width (`thunk_btn_devfill`). Re-punch any
  baked corner-chamfer key pixels afterward (`thunk_corner_punch`, s=ceil(g/16)).
- Dither fused with a glyph in ONE opaque sprite (the dropdown arrow, `0x41` glyph on `ae/ee` bg +
  `0x09` corner keys): a custom per-output-pixel thunk (`thunk_faction_dropimg` v2,
  `scripts\assemble_dropdither.py`) — NN-sample the source for the glyph SHAPE, but when the sampled
  texel is a bg dither color, write the FINE scanline color picked by **output-row parity** (`ae` even /
  `ee` odd); passthrough glyph/key texels. = crisp glyph + native-density dither.

- Scanline-dithered ART with an arbitrary/per-image palette (council faction portraits + logos,
  2026-08-22 v22): **parity-forced re-blit** — redraw the dest rect from the SOURCE with the
  centre-aligned NN col map, but pick rows via centre-NN at PAIR granularity then let dest-row
  parity choose bright/dark within the pair (`r = 2p + (j&1)`, `p = floor((2j+1)*den/(4*num))`).
  Palette-free (no pair LUT needed), parity-strict, pair-monotone, ≤1 native-pair error. The
  "obvious" variant — nudge the centre-NN row to the nearest parity-matching neighbour — alternates
  correctly but steps the image row BACKWARD at run boundaries (comb jitter); reject it. Skip
  src==key pixels so the keyed background survives. Use the fixed pair-mate LUT restripe instead
  only when the pair indices are few, known, and measured in DEST index space.

Confirmed in-game (build e920df04). Related: [[feedback-smac-all-resolutions]],
[[feedback-proportionate-scaling]], [[project-smac-frame-strip-key]], (a private note).

**Faction portraits carry a 1-row scanline dither (2026-09-18, combat console).** Any Sprite_draw_2 of a 0x78EDF0+fac*0x65C portrait scaled g/16 through a plain scaler (t_dp_sd2_bezel) BANDS: measured 72x1+42x2-row runs at g=22, 51x1+63x2 at g=25 (invisible-ish at 4K). Use thunk_cw_portrait (g/16 + thunk_parity_reblit) from the first build. Eyeballing missed it in the first bake; the row-luminance alternation run-length histogram (work/tests/combat_measure/banding.py) catches it in seconds, and parity_sim.py proves a cure offline via the byte-proven py_parity_reblit port before any game launch.
