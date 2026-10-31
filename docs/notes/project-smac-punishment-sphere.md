---
name: project-smac-punishment-sphere
description: Punishment Sphere display feature (uimod pssphere.cpp) — would-be drones shown + badge on base row and F4; PENDING in-game verify; design decisions and engine facts
type: project
---

**Status 2026-09-20:** BUILT, DLL **7a509743** deployed (F4 badge = upper-RIGHT, base row = upper-left: the corner the row overlap leaves visible; 2b372b01 seen working at 4K by the maintainer) (prev 14ae5dae = uimod.dll.prev), live exe **25f38067** (citizen-face bilinear fix: t_pop_ratio tail + thunk_bw_sbc v2 -> thunk_sprite_bilinear; law scaling_laws.basewin_pop_face_enlarge). USER-VERIFIED 2026-09-20 in-game (4K + letterboxed non-4K modes); COMMITTED+PUSHED fc72282; current DLL e0bde654 (adds [[project-smac-riot-defection-fix]]). Checklist + Thinker compat sweep in the maintainer's work log.

**User's final design (do not re-litigate):** game logic keeps the real zeroed values; DISPLAY shows the base as it would be WITHOUT the sphere — PSYCH tab last row = would-be values (no badge there), base citizens row + F4 CITIZENS rows draw would-be talents/drones/superdrones with badge variant B (gold ring + straps + core) upper-left on every drone/superdrone face. No superdrone "fix"; under Thinker its superdrone NOPs (0x414D52/0x414EE2) get reverted. Rejected along the way: extra PSYCH line, relabel row 4, badge on PSYCH tab.

**Engine facts (verified from bytes):** base_psych 0x4EA540 zeroes drone_total+talent_total at 0x4EB299 for sphere (fac 23, byte base+0x8E bit 7) OR nerve staple, in the LAST stage -> PSYCH row 4 "Secret Projects" takes the credit (vanilla mislabel; "Stapled Base" label 971 sits on row 0). superdrone_total survives the zeroing unless the pop-overflow loop runs = vanilla red-face bug. base_research 0x4F4E80 halves a sphere base's labs on a working copy (stored labs_total stays full). draw_ops skips base_compute when ComputeBaseID 0x689374 == the row's base. Human citizen sprite sets = 4 classes x 2 variants (8), index = class + 4*variant.

**Mechanism:** PsychWrap = real pass, clear sphere bit, pass (capture would-be), set bit, pass (restore); skipped when BaseUpkeepState 0x90EA34 != 0. F4 lends would-be totals to the BASE record during draw_ops and restores on exit. Face sites chain over OUR cave thunks (live-target install). Badge law scaling_laws.ps_badge: d = half_down(15*face_w/38), inset = max(1, face_w//38); C++ port psbadge.h pinned bit-for-bit by work\tests\ps_badge.

**Thinker (TENTATIVE, untestable here):** Thinker write_jumps base_energy 0x4EB560 -> chain the wrapper on that E9 lazily; its BaseWin_draw_psych_strcat hook @0x408DBD relabels row 4 "Stapled Base" for sphere bases — now wrong, UNIMPLEMENTED.

Probe: work\scripts\hook_ps_badge_probe.js (launcher Frida shortcuts point at it). Related: [[feedback-dither-no-resample-on-upscale]], [[project-smac-report-screens]], [[project-smac-base-screen]].

**Other verified engine facts from this arc:** vanilla pacifism (stage 3) adds (count) or (count-1) drones then clamps drone_total to pop_size and never raises superdrone_total -> pacifism cannot create superdrones. Vanilla base_research 0x4F4E80 halves a sphere base's labs on a working copy. PSYCH row labels are chosen in BaseWin_draw_psych 0x408B20 (jump table 0x408E94; row 4 hard-wired to label 327). **Citizen-face banding is only PARTLY solved** (bilinear: drones 0.15 -> 0.03-0.07 low-freq share, other faces not measurably better; work\tests\face_banding_measure.py) — hybrid regenerate-the-background enlarge is the flagged OPEN item in the maintainer's work log.

**Citizen-face HYBRID enlarge (2026-09-20, user approved the offline render):** thunk_face_hybrid pcave2+0x21A00 (798B, Sprite_draw_2 contract) = CALL thunk_sprite_bilinear, then restripe only texels that are background pair members (scaling_laws.face_pair_mate: hof_pair_texel a/b/a/b column chain AND a horizontal run >= 3 of the same pair; stripe phase = dest-buffer absolute y, P = stripe_period(g), brighter member wide). Consumers: t_pop_ratio tail, thunk_bw_sbc v3, t_rwk_face_blit. Live exe **eed5e3e9** APPLIED, suite green, NOT committed, PENDING in-game verify at 1600/1920/4K. Metric on member columns: NN 0.14-0.15 / bilinear 0.08-0.09 / hybrid 0.007-0.009 at g=22/25. Gain is mostly on DRONES (20-41% member texels); talents/specialists/most aliens have gradient scanlines that are not an exact two-index alternation -> stay bilinear. Tools: work\tests\face_hybrid_preview.py, face_banding_measure.py (its old 'human small' cell origin and column pick were off by one; fixed).

**Hybrid v2 (2026-09-20, COMMITTED+PUSHED af9e91e, live exe 3b2cc5ed, user-verified 1600x1200 + 4K; 1920 unseen):** v1's one-sided chain test left the rows between the top border and the head unregenerated = a smudge above every drone head at 1600 (user-reported). Rule now: direct member = anywhere inside a vertical a/b run >= 4 (3 speckles foreheads, rejected); run >= 3; one-pass both-sided gap fill <= 12 texels (small faces). User chose to LEAVE the cap at 12 (the small superdrone's 13-texel head-top gap stays; not visible in shots). Lesson: a membership test that only accepts a texel at the END of a chain fails in pockets hemmed in on both sides — test 'anywhere inside the run'.

**2026-10-29: NERVE STAPLE joins the would-be display (user decision, reverses "a stapled base stays vanilla").**
CurrentSphereBase(id, kind) = sphere bit OR BASE+0x08 nerve_staple_turns_left > 0; the would-be pass zeroes the staple
byte too (the whole BASE record is snapshotted/restored since the Thinker audit: Thinker's mod_base_energy accumulates
energy_intake_2, so a third pass cannot restore). Badge glyph by kind: gold sphere badge (sphere wins when both), steel
STAPLE badge (laws ps_staple_raster/ps_staple_ramp: same disc/ring/size law, U-bracket; psbadge::RasterStaple; parity
tests). Glyph = candidate A "clamp" of work\art\staple_badge_candidates_preview.png, PROVISIONAL. Under Thinker the
superdrone-face NOPs are restored only inside the draw_pop would-be window, and Thinker's PSYCH relabel call at
0x408DBD is put back to the engine's 0x645470 (user: squash; our design never relabels). DLL b171eb03 in the workspace. Glyph CHANGED 2026-10-29 (user: the literal staple did not read): the nerve-staple BUTTON in miniature -- solid red disc,
black X on the upper half (centre -0.30R, +-0.34R, stroke 0.30R wide, min 1.5 px), white blindfold band 0.12R..0.40R;
3 colour classes + 2 edge tones (PS_STAPLE_TONES), majority-class 4x4 raster (ps_staple_class / ps_staple_raster).
DLL 3b0b80a9 in the workspace; GLYPH APPROVED by the maintainer 2026-10-29 (do not relitigate); previews work\_ps_badge_preview\law_staple_d*_x8.png; awaiting the maintainer's verdict. FINAL glyph 2026-10-29 (user, after the red button-with-blindfold vanished on the red drone face; ideation sheet A-D on the
real face, user chose "B minus the blindfold"): WHITE disc (246,246,246) + black X (+-0.46R, stroke 0.26R, min 1.5 px)
+ black rim (r > 0.88R); tones 0 black / 1 grey edge / 2 white. PopEnter now computes the would-be totals at draw time
when the cache is stale (Thinker's action_staple only redraws the tile; nothing recomputed the base). DLL d9d0088b. INVERTED 2026-10-29 (user): BLACK disc + white X + thin white rim (same geometry; tones 0 black disc / 1 grey edge / 2 white).
DLL 9bd8779a in the workspace. This is the glyph to keep unless the maintainer says otherwise.
