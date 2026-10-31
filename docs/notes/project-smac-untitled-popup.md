---
name: project-smac-untitled-popup
description: Untitled popups ([popup+0xa48]==0) skip the engine title block -> stale title stash; untitled chrome set d27b4041 USER-VERIFIED; + Quit art-flush arm = live 8390e896 2026-09-18, UNCOMMITTED, CLOSED 1b2853f
type: project
---

**LIVE `8390e896` 2026-09-18 (d27b4041 user-verified + the Quit art-flush arm below), NOT committed; on Quit confirm commit BOTH as one.** Originally: baked `d27b4041`, awaiting verify (Help > version popup, one untitled
no-art popup, the Quit modal; 4K + one non-4K). Trigger: 4K shot 20260918 vs `refs\pristine\VersionNumber.png`.

**Root cause class — a popup with NO TITLE.** `Popup_on_draw_background` tests `[esi+0xa48]` @0x405f7c and `je 0x4060e7`
skips the WHOLE title block, so `thunk_pf_title_stash` / `thunk_band_stash` never run. Everything keyed off the title
stash then used the PREVIOUS popup's values or stayed native:
- pf-align pair (`thunk_pf_union_align` quitlaw + `thunk_pf_frame_align`) read stale `g_title_left/right` → text-box
  right edge 178px short of the OK bar. (Only the ORNATE arm ever checked `[0xa48]`.)
- `thunk_scale_header` v1 was titled-only → untitled header `[21b8]`=0x12 (18; titled 0x26) stayed native: ring top +6
  device px vs faithful +30 @g40. `[30e0]` = 3·`[21c0]`/2 = 0 for these popups.
- art unkeyed → engine x/y.
- SEPARATE regression found on the way: `thunk_popup_nestpads` v2 (2026-08-29 listbox bake, law `scale_px(2)`) applies to
  all three source-rect paths of 0x406211, incl. the BODY-ONLY path where the ring nests around the d528 STROKE → pitch 5
  on L/T/B vs 7 on the pf-aligned R @g40. This hit TITLED art popups (Quit) too.

**Fix** (src `scripts\assemble_untitled_popup.py` + `splice_untitled_popup.py`; pcave2 tail 0x2E6A0..0x2E900; parity
`tests\test_untitled_popup_asm_parity.py`): site `Popup_on_draw_background.untitled_stash` 0x405F7C → `thunk_untitled_stash`
(calls the titled path's OWN `thunk_popup_titleinsets`/`thunk_title_hmargin`, chosen by `Win_is_visible(MainWin_g)`, on the
dead locals `[ebp-0x14]/[ebp-0xc]` = one cascade; arms `g_band_popup`; virtual `g_title_bottom = content_top − 3·ps3 − 2Δ`
so fieldpads' keyed arm lands on the engine T; flag `g_band_untitled` rewritten EVERY else-branch draw; off paths disarm a
stale key == esi). `thunk_scale_header` v2 RELOCATED menu_strip 0xBB0 → pcave2 (untitled FLAT/SLIDE arm; faction-quote
singleton + ornate excluded — `thunk_d528_inset` / `thunk_tutwin_ctop` own those tops). `thunk_popup_nestpads` v3 RELOCATED
0x3770 → pcave2 (body-only = `[30d4]!=0 && ([2350]==-1 || art)` → `popup_pad(3)`; list + UnionRect paths keep v2; untitled
art-anchor pre-add `+Δ`, the fieldpads ornate+art technique). `assemble_dw.py` INPLACE no longer owns nestpads.

**Why:** the maintainer asked for the version modal's horizontal scaling + stroke channels to match pristine.

**How to apply:**
- Any lever that reads `g_title_*` must ask "what if this popup has no title?" — the stash is per-draw and the title
  block is conditional.
- SUSPECTED LATENT, deliberately NOT changed (no titled shot to measure): `thunk_popup_artalign`'s flat law still subtracts
  `frame_grow_delta`, calibrated 2026-07-03 against the GROWING hollow that [[project-smac-popup-chrome]] removed 07-09. If
  the Quit verify shot shows the art top Δ above its ring top (3px @4K, 1px @1600), extend nestpads v3's pre-add to every
  keyed flat/slide art popup.

Related: [[project-smac-popup-chrome]], [[project-smac-quit-type8-optionlist]], [[feedback-global-lever-all-writers]],
[[feedback-fragment-refresh-reverts-foreign-entries]].

**VERIFIED 2026-09-18 (user shots @4K, 012128/012134 @1600, 012154/012158 @1920; pixel-measured):** version
popup stroke pitch = ps3 on ALL FOUR sides at every res (7/4/4), ring top at border+31/20/16 (law hdr-2*ps3; vanilla 30/18.75/16.5),
art top ON the ring top row at all three, art-to-border identical to the titled Quit. Quit pitch 7/4/4 on all four sides.

**CLOSED 2026-09-18: commit 1b2853f (pushed), live 8390e896, user-verified + pixel-measured 4K/1600/1920 (Quit art top == ring row 931/438/411).**

**Quit art-flush.** Shots showed the art top frame_grow_delta ABOVE the ring top
(928 vs 931 @4K, 437 vs 438 @1600, flush @1920): artalign's flat law subtracts a delta calibrated against the pre-2026-07-09
GROWING hollow. DECISION BY MEASUREMENT: band-bottom -> ring-top gap = 9/4/3 vs vanilla 7.5/4.7/4.1; moving the ring up
(my first diagnosis, "the ring is low") would give 6/3/3 = worse at 1600 -> the RING stays, the ART drops delta. Mechanism:
nestpads v3's `g_field_anchor += delta` pre-add fires for EVERY keyed flat/slide body-only popup (key == esi &&
g_fp_ornart == 0); the interim `g_band_untitled` flag cell was removed. Law `flat_art_anchor`. fieldpads/artalign
(assemble_council.py) untouched. Drawn band bottom sits 1px lower than the model B+delta at every g (gap = ps3+delta-1).
Also noted, NOT changed: ring -> backdrop-border right margin 5 @4K vs faithful 7 on both popups (title thickener's grow).
LESSON: decide WHICH of two misaligned elements moves by measuring each against vanilla at 3 resolutions, not from the
history of who changed last.
