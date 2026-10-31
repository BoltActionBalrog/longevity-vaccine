---
name: feedback-parity-blit-key-exclusion
description: A keyless (0x100) t_rwk_parity_nn / any palette-nearest blend blit lets index 9 (the transparency key, RGB 9,0,0) win dark blends and punches holes to the layer beneath; always pass key 9 and pre-remap literal 9s in runtime dumps
type: feedback
---

**Rule:** every blit that goes through a palette-nearest blend (t_rwk_parity_nn's h-blend, thunk_sprite_bilinear, thunk_portrait_avg) must pass key 9 even for opaque art, because the nearest search excludes ONLY the blit's key; with a "no key" value the transparency index 9 (RGB 9,0,0, visually black) wins every near-black blend and those pixels composite as HOLES. Art that contains no pcx index 255 (runtime 9) loses nothing; a runtime canvas dump (the HOF world-map pcx) may hold literal 9s, so remap them to black (index 65) in the private source first (`scaling_laws.hof_map_source_fix`).

**Why:** Hall of Fame v1..v3 (2026-09-14): a 1-px column of "phantom pixels" on the world-map box's left edge, black stripe rows only, only in the unpopulated view — the orange frame line blending into the black field snapped to index 9 and the game map behind the modal window showed through. Same class as the A5 portrait "junk speckle" (key excluded from the resampler's search) — the exclusion has to be per blit, not just in the resampler.

**How to apply:** when reusing t_rwk_parity_nn or the bilinear class from a new site, the key arg = 9 unless the source genuinely has key texels to keep (then it is 9 anyway). Diagnostic signature: stray pixels of the layer BENEATH on exactly one stripe parity along colour edges.
Related: [[feedback-dither-no-resample-on-upscale]], [[project-smac-hall-of-fame]], [[project-smac-a5-native-frame-thickness]].
