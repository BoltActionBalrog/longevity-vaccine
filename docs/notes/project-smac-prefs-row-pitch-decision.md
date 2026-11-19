---
name: project-smac-prefs-row-pitch-decision
description: SUPERSEDED 2026-11-14: Longevity Preferences rows now use vanilla's 22-native pitch on the two-page tab (owner's choice); history of the earlier 20-native decision
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

**RE-OPENED by the maintainer, 2026-11-13:** "The sizes between the buttons are not faithful right now. Did that deliberately before because we had too many buttons to display on screen, otherwise." With the tab's two pages ([[project-smac-prefs-two-page-split]], page 1 = 12 rows) the reason for 20 is gone, and he asked for an action item: a faithfulness pass over the WHOLE Preferences menu (in the maintainer's work log, KNOWN BUGS / OPEN WORK). So once the two-page layout is in our tree, proposing vanilla's spacings again is wanted, not forbidden. He also chose not to ask the PR's author to fix the frame-to-More gap: it belongs to that pass.

Related: [[project-smac-prefwin-scaling]], (a private note), [[feedback-symmetry-over-1px-scaling]].

**SUPERSEDED 2026-11-14 (owner, in the Goto-path session):** with the tab split over two pages (contributor PR #2's mechanism, ported on branch `claude/hide-move-line`), the owner chose "Vanilla x g/16": `kChkRowPitch` = 22 native (scaling_laws.PREF_LONGEVITY_ROW_PITCH), page 1 = 13 lines ending at native 298 above the slider frame (now (256,302,713,350), 10 native above More). The stock tabs still draw 56/37/33 (scaled font + unscaled 3), so ours differs by ~3 px at 1600/1920 until the whole-menu faithfulness pass. He declined "match the stock tabs now" (overflows page 1) and "fix stock too" (larger) for now.
