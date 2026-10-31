---
name: feedback-parity-nn-single-row-art
description: The parity-preserving NN (t_rwk_parity_nn) drops or doubles single-row art (1-px strokes, chamfers, separator lines) at 22/16 and 25/16; for chrome art use the edge-safe NN + pair-only restripe (t_hof_pairnn / scaling_laws.hof_pair_enlarge), brighter member wide
type: feedback
---

**Rule:** use `t_rwk_parity_nn` only for art that is row-pair dither through and through (the report tab icons, the row-dithered faction pictures). For chrome art that mixes a scanline field with 1-px strokes, chamfers and glyph outlines (hof.pcx, hoficons.pcx, any 9-slice-like pcx), enlarge with the edge-safe centre-sampled NN and regenerate ONLY the row-pair texels at the P law: `scaling_laws.hof_pair_enlarge` (cave port `t_hof_pairnn`). A texel is a pair member when its column reads a/b/a/b outward on either side; a lone stroke never qualifies and survives as NN. The wide (hN of P) member is the BRIGHTER one — the popups' navy-wide duty; `mon_face_top` now agrees.

**Why:** Hall of Fame v2..v5 (2026-09-14): at 1920x1080 (22/16, P=3, one parity gets 1 device row in 3) the world-map box's bottom stroke vanished, header chamfers came out malformed and the separator line disappeared, because `parity_nn_row` replaces a native row of the minority parity with its neighbour of the demanded parity. The same law made two-purple glyphs and the red/dark CLOSE bevel two-thirds dark ("black specks", "top red rows missing"). Offline render + Unicorn parity proved the replacement at 22/25/45; user-verified 2026-09-17 at 3 res.

**How to apply:** before choosing an enlarge for a pcx, census its single-row features (rows where one index dominates but neither neighbour row shares it); any such row means parity NN is the wrong primitive. Pass key 9 to every pair blit ([[feedback-parity-blit-key-exclusion]]).
Related: [[project-smac-hall-of-fame]], [[feedback-dither-no-resample-on-upscale]].
