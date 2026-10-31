---
name: feedback-symmetry-over-1px-scaling
description: User rule 2026-10-17 -- symmetric channels/pairs beat 1-px-exact vanilla x g/16 placement; never ship a fix that trades symmetry for exactness
type: feedback
---

When exact `vanilla x g/16` placement of one edge would make a symmetric channel uneven (a double frame's L/T vs R/B,
a ring-to-rows gap L vs R, two flanks of one anchor), keep the symmetry. The maintainer's words: "Symmetry is more important
than 1px perfect scaling."

**Why:** 2026-10-17, fix 3 (ornate title inner step, left only) put the SELECT A FACTION title inner / list ring on
s(16) exactly but made the title double-frame channel 6/5 at 4K and the rows->ring gap 5/7; the maintainer rejected it.
The held patch is work\briefs\held\fix3-ornate-delta.patch -- do NOT re-propose it.

**How to apply:** before shipping any per-edge correction, check every concentric channel and every mirrored pair the
edge belongs to at 4K, 1920x1080 and 1600x1200; if one side moves alone, either move its mirror by the same law or
leave both. Extends [[feedback-match-opposite-edge-margin]] (symmetric satellite pairs) and refines
[[feedback-proportionate-scaling]].

2026-10-18: fix 14 scaled a popup's type-1 list to exact vanilla x g/16 but left the box it fills at s(xs), so the row
bars stopped 8 px short on the right only at 4K -- caught by the reviewer. When correcting one of two coupled widths
(list vs its box), move both by the same law.

Same day the maintainer ACCEPTED (do not reopen): the FlatButton family's ceil(g/16) hover ring / corner notches vs the
frame family's half_down (Hall of Fame CLOSE hover 2 px at 1080/1600x900; row notches 2x2 vs OK 3x3 at 4K), and the
stack picker's vanilla label clip (3 native px).
