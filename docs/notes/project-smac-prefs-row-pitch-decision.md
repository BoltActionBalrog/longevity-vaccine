---
name: project-smac-prefs-row-pitch-decision
description: Longevity Preferences option rows stay on kChkRowPitch 20 native (user accepted 2026-11-07); vanilla's own option rows are 22 native and the stock pages measure 56/37/33 px at 4K/1600/1920 -- 22 fits only 14 of our 15 rows, do not re-propose
type: project
---

**Decision (user 2026-11-07, "I can accept our current scaling if that's the trade-off"):** the Longevity tab's
option rows keep `kChkRowPitch = 20` native (device 50 / 31 / 35 px at 4K / 1600x1200 / 1920x1080, per-row floors
through the baked PrefWin gate, so 1600 alternates 31/32).

**Measured reference (user shots 2026-11-06, 4K + 1600x1200):** the stock Map Preferences rows sit 56 / 37 px
apart (33 at 1920 per the earlier trace) -- their pitch is the scaled font's device line height + an UNSCALED 3, not
vanilla x g/16. Vanilla's own option rows are 19-row bar + 3 gap = 22 native (`scaling_laws.type1_row_pitch`,
`pref_tab_pitch`: P = half_down(22 g, 16) = 55 / 34 / 38).

**Why 22 was not taken:** the room from our first row's top to the slider frame's top is ~314 native at both
aspect ratios; at 22 native 14 rows fit (13 x 22 + 20 = 306) and the 15th (the HD-pack row, built only with the
pack) overflows by 15 native. The ways out were offered -- fold "Add Scanlines" onto the HD row's line (fits:
~660 of 725 px at 1600), merge the camera rows with shorter labels, make one setting ini-only, or stretch 15 rows
into the slack (52 / 32 px, barely visible) -- and the maintainer chose to keep 20. Only re-open if a row is removed for
another reason (then 22 fits and the gate's floors give 55 / 34-35 / 38-39).

Related: [[project-smac-prefwin-scaling]], (a private note), [[feedback-symmetry-over-1px-scaling]].
