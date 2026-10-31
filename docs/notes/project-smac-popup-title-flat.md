---
name: project-smac-popup-title-flat
description: CLOSED all-res cfb8f532 (2026-09-18): backdrop R-1 for the inclusive band-map + popup TITLE draws FLAT (title_grow_delta == 0, every (g-16)>>3 compensation zeroed); leftover 1px inclusive R/B footprint
type: project
---

**State 2026-09-18: live `cfb8f532`, USER-SHOT + pixel-measured at 4K/1600/1920 (31 shots 1329xx-1334xx), COMMITTED + pushed.** Measured: title strokes frame+10/6/5 on L+T, ring 81/51/44, field 88/55/48 (faithful 80/87.5 @4K); container rings ON the title inner stroke; diplomacy speech box + faction select pixel-identical to pre-change. LEFTOVER (systemic, not requested): the band-map's INCLUSIVE footprint puts every thick frame's R/B stroke 1px out (title R -9..10 vs L +10..11 @4K; title ~2 rows tall).

**Defect 1 — backdrop right border K-1 px (9b644722; verified all three res).** NOT the rail /
anchor cascade I first suspected. `thunk_popup_d690insets` lands R on the rail's first column = right for vanilla's
HALF-OPEN `Buffer_box_sprite`; `thunk_box_thick_devfill` band-maps INCLUSIVE (fe_bandmap W = R-L+1, law
`bandmap_rect_from_halfopen`), so the stroke's outer column is col R, under the rail. Fix `thunk_backdrop_railtrim`
(pcave2 0x2E820) in front of `thunk_tutwin_backdrop` @0x405F77: g>16 && draw-copy R != window R (ebx) -> dec the DRAW
copy's R only. Menu popups never showed it (nothing covers col R). Law `popup_backdrop_draw_right`.

**Defect 2 — title box + ring frame_grow_delta too close to the border.** User chose the FULL fix over the cheap
rect-inset lever. `thunk_box_thick_flat` (pcave2 0x2E840) = clone with Delta -> `33 DB 90*6`; `thunk_pf_title_stash` +
`thunk_inner_margin` tail into it. `thunk_box_thick` STAYS: the diplomacy talk title (`t_dp_title_*`, HARDCODED rel32
callers) pre-insets its rects +D and was already right. Every popup-chain delta zeroed IN PLACE by changing the shift
count 3 -> 31 (same length, no relocation); fieldpads' keyed flat T arm -> 22 NOPs = engine arm `t_src - ps3`.
src `splice_title_flat.py`; guards `tests\test_title_flat.py` (incl. a CENSUS: no stray `(g-16)>>3` outside an allow-list).

**Why:** vanilla ground truth, pristine `QuitWithComMenu.png` (native rows from the frame top): title strokes 4 / 27,
ring top 32, field top 35, title 4 from the border L/R, art 1 native px right of the title stroke. My 2026-09-17
"vanilla band->ring gap = 3 rows" was WRONG (it is 4) -- it came from the downscaled `Quit.png` (892 px wide).

**How to apply:**
- Measure vanilla from the 3840-wide pristine refs or an engine trace, never from a downscaled crop.
- A shared thunk with one correct consumer and one wrong one: CLONE for the wrong one, do not edit in place; census the
  BUILT exe for hardcoded rel32/push callers first (placeholder grep missed the diplo pair).
- An in-place "make this term zero" is cheapest as a shift-count change when the instruction stays the same length.
- `(g-16)>>3` is ALSO the scaled-text ink nudge (`thunk_title_textnudge`, `thunk_comm_cent5`) -- not every hit is a frame grow.

Related: [[project-smac-untitled-popup]], [[project-smac-popup-chrome]], [[feedback-half-open-draw-rects]],
[[project-smac-diplo-talk-screen]], [[feedback-wrap-dont-relocate-helper]].
