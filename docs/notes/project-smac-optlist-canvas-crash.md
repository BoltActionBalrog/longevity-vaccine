---
name: project-smac-optlist-canvas-crash
description: type-8 stack picker: FULLY CLOSED USER-VERIFIED 2026-08-01 + COMMITTED at 4b540840 (union v10 ornate edges = stash∓(ps3−Δ) [ornate titles draw Δ-GROWN via box_thick, container draws flat] + title inset/bottom + child-x fl(19g/16) + geometry v9 + banding v2 + spritezoom); crash CLOSED 07-27 (qdlg disarm; NEVER re-arm 0x602bf3); ring cutoff = next item's back-erase wiping the gapS-3 spill; MENU/COMMLINK are MultiWin
type: project
---

# Type-8 OptionList (unit-stack picker) — full arc

**CRASH CLOSED — USER-VERIFIED 2026-07-27** (picker opens crash-free; qdlg_font disarm
4f51cde9). ⚠ **NEVER re-arm site 0x602bf3** — that load is Dialog_set_type arg2 = the
element-attach PARENT WINDOW (stored → row Win+0x38, background-capture source
parent+0x444 in OptionList_on_redraw @0x6113d6); swapping it poisons the capture
(cave bytes read as a Buffer → AV @0x5e0122).

## RE-FIX BUILT 2026-07-31 — live **6e1daed4** (649 sites, suite green, clean apply == live), PENDING USER VERIFY

**The 07-27 handoff's premise was WRONG (twice).** Measured against
refs\pristine\StackPicker.png (1024 capture NN-stretched to 4K: x/3.75, y/2.8125)
vs 4K shot 20260731:

1. **Not a font mismatch.** Measure AND draw both `Buffer_set_font(Dialog[+0x70..0x78])`
   (calc @0x6109c0, draw_item @0x610f3a) — text was correctly scaled and measured all
   along. Dialog_set_type is a pure dispatcher; it never writes +0x70.
2. **Real defect #1 — the elem SPRITE RATIO.** OptList elem (Dialog+0xb14) carries
   num/den at +0x1c/+0x20 (native 1/1) feeding BOTH measure maxima ([+0x54]/[+0x58] →
   pitch [+0x68] = gapS + max(lineH, sprH·num/den) → total [+0x60]) AND draw
   (Sprite_draw_2 args, SCALE_NUM/DEN_G for the custom unit-draw fn elem+0x64,
   centering, selection Buffer_box). Never scaled → native 37px icons; pitch went
   text-dominated: measured 57 dev @4K = fl(3·40/16)+max(lineH 50, 37) vs faithful
   ~100 = vanilla 40×2.5 (vanilla is icon-dominated: 3+37).
   **FIX = group `popup_optionlist8_spritezoom`**: one fraction law (num·g, den·16)
   at all FIVE read sites — calc 0x610AE1 (one ecx/edi pair serves W and H divs),
   draw_item 0x610DF1 (ebp/ecx → everything downstream), selection box 0x610FC7,
   row-origin gap/stride 0x610C84 (edx=gapS → engine's own sar edx,1), label-x +4 pad
   0x610D98 (thunk ends `test esi,esi` — flags live across the RET, jne @0x610DA2).
   Thunks thunk_ol8_* @pcave2 0xF560..0xF62C, src scripts\assemble_optlist8.py; laws
   scaling_laws.optionlist8_sprite_ratio/row_pitch/text_x/row_origin_gap; parity
   tests\test_optlist8_asm_parity.py (52 green). Census: attach Spot rects, on_redraw,
   select (FUN_00611060), keyboard (FUN_00611400) all inherit via fields/draw_item —
   no inline ratio copies.
3. **Real defect #2 — the missing metal border.** The picker is a **type-2/6 ornate
   popup**: Popup_on_draw_background ([+0x30ac]/10000 ∈ {6,2}) draws def **&0x6846b0**
   (console-style segmented metal 9-slice w/ corner caps) at the full window rect —
   NOT the flat d690, NOT slide rails (type-2/6 never slides; Popup_show's rail branch
   needs type 0/5). Site 0x405f77 routes through thunk_tutwin_backdrop, whose v1
   ornate arm was gated `params==0x6846B0 && ecx==TutWin+0x444` → every OTHER ornate
   popup fell to thunk_box_thick_devfill, which ZEROES the def's border-sprite
   pointers (its synth-stroke treatment for flat defs) → whole frame gone at g>16
   (pixel-proven: zero metal rows, devfill's striped band in their place).
   **FIX = tutwin_backdrop v2** (in-place @0xA920, 110B): ornate arm for ANY dest —
   devfill synth + ornate 9-slice band-map over via thunk_box_thick_hollow (the
   TutWin-verified recipe); the synthetic title stash (g_title_left/right) stays
   TutWin-ecx-gated (titled popups get their real stash from band_stash).

**LESSON (dither-pair-ambiguity class, def edition): a def-family treatment gated on
ONE consumer window silently rewrites the def's OTHER consumers.** Census the DEF's
consumers (all sites drawing params==X), not just the window you were fixing. Also:
"missing" chrome at 4K may be a treatment EATING art, not an unscaled draw — profile
the pixels for the art's texture before assuming absence.

## Residual defects (user report 2026-07-31 on 6e1daed4, shot) — DIAGNOSED, awaiting trace
Pixel-measured vs pristine (rows pitch 100 dev = faithful; ring H = pitch−2 ✓; the
"92/108 pitch" reading was ink-top jitter, sum = exactly 200):
1. **Union frame l/r wrong for this popup.** Both quit modal AND picker have
   +0x2350==8 (0x602658: ANY nopts>1 && [+0xa14]==0 → 8), so the picker takes
   thunk_pf_union_align's quitlaw arm (l/r = title outer ± Δ) → overlaps the title.
   But the picker is popup-type 6/2 (ornate): vanilla union d5a0 sits at the CONTENT
   MARGINS (win+~8), NOT the title ring — title-anchored laws only coincide with
   margins for type-0/5 popups (what quitlaw was verified on). Union rect (vanilla,
   list-only path): l/r = iVar4/[+0x21cc]±, t = iVar5−6, b = t+[+0x2230]+6 where
   [+0x2230] = pitch×nopts+gap (pristine: 242 = 6×40+2 exact). t/b pass through our
   thunk ✓ — the "errant frame" is this frame with wrong l/r, vanilla-legit shape.
2. **Rows/back-frames x unscaled.** Dialog child x = [+0x21cc] if ≥0 else global
   0x9b8cec (written @0x604292 = [0x30f0]+[0x30d8]+[0x21c8]+[0x30e0] margin sum,
   same sum popupbg uses for iVar4); child y = g_popup_body_bottom. Margins stay
   native-ish at 4K → rows + union frame crowd left onto the title ring (pristine:
   rows land on the title INNER ring, = the maintainer's expected relation). ONE lever
   (scale the margin sum / 0x9b8cec) fixes rows AND union l.
3. **Ring 125 dev wide vs faithful ~93.** Ring W = sprW·num/den; suspect the veh
   mini-sprite is ALREADY res-scaled before our (num·g,den·16) multiplies it
   (shared-field double-scale class). Need runtime sprW/num/den at 4K + 1024.
4. Row back-frames (d960) are thickened IN PLACE (thunk_rowbox_guard, Delta=0) —
   "grew outward" perception = placement, not stroke growth.
**Trace ready: scripts\hook_stackpicker_trace.js** (attach entries 0x405c80/0x610970/
0x610c50/0x405b20/0x5e4b4a — audited clean vs patches+PRACX; Frida 17: use
NativePointer#readS32, Memory.readS32 is GONE — first run failed on it). Run at
4K + 1024 (launcher "SMACX Frida Trace" shortcuts repointed), open a stack
picker; log → work\trace_stackpicker.log. Then: state laws in scaling_laws.py,
split the pf_union arm by popup-type (6/2 vs 0/5), scale the margin sum, fix
the ratio law if double-scaled.

## Ornate-interior banding — FIX v2 BUILT 2026-08-01, live 39ad8f56, PENDING VERIFY
User report (1600×1200): interior color banding, "same as many popups before."
Root cause MEASURED (4K interior RLE: (2,3)-run period-5 blocks = a 2px native
stripe NN ×2.5): the v2 arm called devfill (correct device-density interior)
then hollow, whose FULL band-map blit overpainted the interior with the def
fill's NN-duplicated native stripes — at fractional g (25/16) rows quantize
3/3/3/4 = banding. Engine facts: box-sprite def = 10 dwords, params[8]=fill
sprite null-checked at EVERY use (0x5e2dd3); fill also Buffer_tile_mask's over
the edges (zeroing it changes the metal look — the d690 white-bevel trap);
fill's interior region = rect inset by params[6].w/[4].h/[7].w/[5].h (null→0).
FIX: **thunk_tutwin_backdrop v3** routes the over-draw through NEW
**thunk_hollow_keyint** (pcave2 0xF630, 310B, src assemble_optlist8.py): hollow
clone (Delta=0) + ONE step after the small render — erase the fill region back
to key 9 (law `hollow_interior_erase`; frame grown 0x20→0x30 so the erase rect
clears the saved regs) → keyed band-map skips the interior, devfill's STEP2/3
P-stripe product survives; erase boundary meets the bands exactly where the
vanilla fill met them (same blit, same native region — no parallel band
formula). Edge masks untouched. Family-wide for every 0x405f77 ornate popup;
TutWin's interior changes NN-blocks → P-language (intended). Parity 60 green
(test_keyint_*), suite 8859. NOT a changelog item (our own unreleased
regression). LESSON: keystone parses labels `K1`..`K7` as AVX-512 mask regs —
prefix labels.

Tooling: crash watcher work\run-frida-optlist-crashwatch.bat still available.
Related: [[project-smac-base-screen]], [[feedback-menu-strip-coupling]],
[[feedback-draw-state-multiplicity]], [[feedback-dither-pair-ambiguity]].

**v2 (same day, user re-graded v1: banding still ON THE SIDES).** v1's erase used
the engine fill-region insets (61/44) — correct for the interior (1600 pixel-
verified clean 1/1) but the ornate EDGE CELLS are 61x44 slices of interface.pcx
(3x3 grid @296,711; init @0x453d66, all cells 61x44, fill = center cell) shaped
metal-band + transparent filler, and Buffer_box_sprite's per-cell
Buffer_tile_mask paints the FILL's stripes into the keyed holes → the 61-wide
edge margins still rode the band-map NN. v2: erase to the ART-MEASURED metal
cores **(l,t,r,b) = (8,8,9,6) native** (crisp 1.00/0.00 profiles; corner inner
quadrants pure key; law `ornate_interior_erase` + art-guard test re-deriving
the constants from interface.pcx, skips if absent). Vanilla shows the same
masked-fill stripes in those margins and devfill reproduces them at device
density → content preserved, metal untouched. NOTE: fe_pair_remap can NEVER
fix this family — the near-black pair (0x41/0xC6) is deliberately outside its
remap families (pair-ambiguity design).

## Trace results (trace_stackpicker.log, g=40 + g=25) — geometry plan
- **Ring/pitch FAITHFUL, no fix**: elem ratio natively **1/2**, unit sprites
  100px wide → ring 100·(1·g)/(2·16) = 125 dev @g40 ✓; pitch 100/62, total =
  pitch·4+gap exact. The "faithful ~93" estimate compared different unit types.
- **Margin sum already scales**: [0x30f0] = 47@g40 / 29@g25 ≈ 19 native×g/16
  ([0x30d8]=[0x21c8]=[0x30e0]=0 for the picker; [0x30e8]=117@g40 = list top).
  Vanilla union arithmetic is near-correct at scale; pf_union quitlaw override
  (l = titleL−Δ) is the breaker. **Quit modal = popup TYPE 0 (dlgreq=16),
  picker = TYPE 6 (dlgreq=8)** — +0x2350 CANNOT distinguish them, popup type
  [0x30ac]/10000 CAN. Fix = v8 gate: rewrite only for type ∈ {0,5}.
- **⚠ 6/2 title insets (+9/+3/+1 dev) are UNSCALED** (stash titleL=10@g40) →
  title inner (16 dev) ≠ margin (44 dev) at 4K; the vanilla "frame == title
  inner" coincidence needs the 6/2 title chain scaled, which may be shared
  with the LOCKED menus/commlink (fad779d8) — census consumers first.

## GEOMETRY TRIO BUILT 2026-08-01b — live **2d308c84** (650 sites, suite 9,017, clean apply == live), PENDING USER VERIFY
User re-graded on shots (4K) / 222653 (1600): frame flush with title
OUTER (should be INNER) + ring still cut at the bottom. Three fixes, one build:
1. **pf-align v8 popup-type gate** (both thunks RELOCATED: union 0xB000→0xF7A0
   314B, frame 0xA800→0xF8F0 163B; old slots dead): raw [esi+0x30ac] unsigned
   band test after the concentric check; only FLAT(0)/SLIDE(5) take the
   rewrite, type 6/2/1000/future pass through. Law
   `popup_frame_rewrite_applies` (+JS port); parity 405. g<=16 native-fix arm
   deliberately NOT popup-type-gated (unchanged).
2. **thunk_pf_title_stash v2** (IN-PLACE @0xF18, 172B, absorbs the dead 0xF48
   slot): CENSUS RESOLVED THE COUPLING — MENU/COMMLINK are MultiWin draws, NOT
   Popup_on_draw_background; the 6/2 "+9 quad" is family-exclusive but the
   +1/+4/0x1c/+3 steps are SHARED with locked 0/5 titles → constants
   untouchable. Fix rewrites the title-OUTER rect l/r (type 6/2 & dlg!=-1 &
   bodyh[0x30d4]==0) from the frame's own quantities: l'=base−6,
   r'=base+listw+6 (base = margin sum or [0x21cc]>=0 override; listw =
   [esi+[[0x21d0]+8]+0x222c]) → the SHARED native +3 d618 step lands the
   title INNER exactly on the frame columns (frame = base∓3) at every g.
   Law `ornate_title_flush_outer`; **native identity: base=19 → 13 == the
   engine's own +9+3+1** (the law IS vanilla's geometry). Stash records the
   rewritten rect (pf-align never reads it for 6/2 under the gate). Title
   VERTICAL insets/height/font stay native — deliberate residual.
3. **Ring-bottom cutoff root cause**: ring = Buffer_box(x, y+1, x+sprWs−1,
   y+1+pitch−3) at the RECENTERED y (y += (pitch−sprHs)/2); the −3 is the
   NATIVE row gap (pitch = gapS + max(lineH, sprHs)), so at g>16 the ring ran
   gapS−3 rows past its cell and the NEXT item's back-erase (Buffer_copy_4,
   exactly pitch tall) wiped the bottom stroke + vertical tails. Measured
   proof: verticals end exactly at the cell boundary (cy+99 @g40, cy+61 @g25,
   both = prediction). Vanilla is safe only because gapS==3 (off=1 ≤ 1). Fix:
   NEW site `OptionList_draw.selbox_bottom` @0x610FBC (11B cluster) →
   thunk_ol8_selbottom @0xF9A0 (36B): bottom = y+1+pitch−fl(3g/16) (law
   `optionlist8_ring_bottom`; in-cell at every g since off=gapS>>1 ≤ gapS−2;
   (3·16)>>4=3 = branchless native identity). Pushes the 3 Buffer_box args on
   the caller's stack → ret addr parked in g_ol8_ret @0xF9E0 (pop-to-mem +
   jmp-[mem] pattern; single synchronous UI draw). ecx = elem sprite ptr LIVE
   across the thunk (feeds the 0x610FC7 cut) — untouched.
VERIFY list: picker at 4K+1600+1024 (frame flush title-inner, ring closed);
non-regression: quit modal, story-choice type-8, #FACTION listbox, NameBase
field ring, Customize Game Rules (+ its 1024 native fix), TutWin, main menus,
MULTIPLAYER-SETUP lobby.

## GEOMETRY v9 2026-08-01c — live **6bb41faa** (650 sites, suite 9,301, clean apply == live), PENDING USER VERIFY
User re-graded 2d308c84 on shot: **the v2 title rewrite SHRUNK the
title box — WRONG.** Wanted: title stays at engine width; the FRAME comes in
so its verticals are collinear with the title's INNER stroke (annotated plan
approved before build: left +7px @g40 / right −3px, i.e. onto the inner
columns).
- **thunk_pf_title_stash v3** (45B, IN-PLACE @0xF18): rect rewrite REVERTED,
  == v1 stash-only (stash fires for EVERY titled family at the shared
  0x406048 site — the ornate arm below reads it).
- **thunk_pf_union_align v9** (414B, RELOCATED 0xF7A0→0xF9F0, old slot
  dead/zeros): ORNATE PICKER ARM — type 6/2 & dlg!=-1 & bodyh==0 & no art &
  titled ([0xa48]!=0, else stale-stash risk) → the SAME container rewrite as
  types 1/2/4: l/r = stash ± ps3 (`itemlist_container_edge_l/r`; law
  `ornate_picker_takes_container_arm`, +JS port). KEY GROUNDING (live-byte
  diff of Popup_on_draw_background vs .bak): banding v2 already scaled the
  title +3 inner step (0x406078 chain), the ring ±3 expansion (0x406211 →
  cave call), the ±0x17/0x37 vis quad (0x405f24) and the −10/−0x13 right
  margin (0x406116); the picker's final frame draw is the SAME 0x406238 →
  union-chain site as the verified 1/2/4 containers → identical draw
  pipelines, flush by construction. Screenshot check: required left shift
  +7 @g40 / +4 @g25 == ps3 EXACTLY (drawn title inner–outer gap also == ps3
  at both g). d528 frame thunk unchanged (v8 ornate pass-through).
- Ring-bottom fix carried over unchanged (thunk_ol8_selbottom).
- Measured stroke columns (39ad8f56 shots): 4K title outer [1136,1137] /
  inner [1143,1144] / frame [1136,1138] left, inner-R [2695,2696] / frame-R
  [2697,2699]; 1600 title outer [315,316] / inner [319,320], frame-R
  [1284,1285]. The 1600 LEFT frame column is ambiguous in pixels (modal art
  edge overlaps) — the ps3 law resolved it consistently on both axes.
- LESSON (annotate-first): the maintainer asked for an annotated screenshot of the
  intended move BEFORE the build — do that for geometry disputes; the
  annotation (zoomed insets, current vs target columns) got instant approval.
VERIFY list unchanged: picker 4K+1600+1024 (title full width again, frame
verticals on the title inner columns, ring closed); non-regression: quit
modal, story-choice type-8, #FACTION listbox, NameBase, Customize Game Rules
(+1024 native fix), TutWin, main menus, MULTIPLAYER-SETUP lobby.

## ORNATE TITLE INSET 2026-08-01d — live **cc418526** (650 sites, suite 9,303), PENDING USER VERIFY
User re-graded 6bb41faa on shot: improvement, but "the channels
between the title frame's upper and side edges and the edge of the modal
are wrong, along with the channel between the unit box and the edge of the
modal." Re-measured pristine (StackPicker.png is a pillarboxed 4:3 native
capture, S=2880/1024) vs patched:
- VANILLA: title outer inset 13 native px from the window edge on l/t/r
  (engine chain +9+3+1 sides, +9+4 top; pristine sides 12.1 / top ~14),
  frame at 16, art→outer channel ~5 native.
- PATCHED @g40: title outer at win+12/13 ALL THREE edges (native constants
  — the strokes hug the border art, channel ≈ 0); this was the former
  "deliberate residual", now user-rejected.
FIX: thunk_pf_title_stash v4 (100B @0xF18) — ornate 2/6 arm shifts the
engine rect's l/t/r by `ornate_title_inset_delta(g)` = fl(13g/16)−13
BEFORE stashing (title outer → win+s(13); the banding-scaled +3 d618 steps
and the v9 frame stash+ps3 → ~s(16) follow automatically; ≤1px floor lag,
law-asserted). Applies to ALL ornate 6/2 titled popups, not just the
picker shape (inset is a window property). BOTTOM stays engine: measured
b = win+9+s(0x1c) @g40 (banding already scales the 0x1c) and the ring
top/list fill start immediately beneath (title b s(37) would CROSS them —
measured collision). CONSEQUENCE: title bar interior shrinks to ~33px @4K
(29px text + 2px margins) — faithful bar height needs the vertical
margin/list chain ([0x30e8] header reserve tracks title b; ring top at
win+78 = title_b−1-ish, rows at win+111 ≈ s(44.4)) — SEPARATE ITEM if
user wants it. Also noted: ornate border art draws ~native-thin (~14px
@4K vs faithful ~25) — separate banding item, NOT part of this fix.

## TITLE BOTTOM + CHILD-X 2026-08-01e — live **0d2c4953** (651 sites, suite 9,367), PENDING USER VERIFY
User re-graded cc418526 on shot: (a) "inner frame stroke partially
overlapping the title font" — measured: ink rows 797-825 COVERED the inner
top stroke at 797-798; the engine b (win+9+s(28)=79) left a 19px text rect
under the raised s(13) top for the 29px ink. KEY re-measure: the ring/frame
top actually sits at win+107 @g40 (the earlier "b=92 would cross the ring
at 78" collision was a mis-attribution — the 836-green was the title outer
bottom itself). FIX: title-stash v5 arm also sets b' = t_engine +
fl(37g/16)−13 (law `ornate_title_outer_bottom`; faithful 24-native outer
height; 15px clear of the ring; purely visual — b feeds only title draws +
text centering; header/list layout comes from fields computed earlier).
(b) "selection box left edge overlapping the left frame stroke... suspect
too wide" — ring WIDTH is FAITHFUL (pristine 50 native × 2.5 = measured
125; the old "faithful ~93" note assumed a 37px sprite, wrong). The real
defect: dialog child-area x arrives win+s(16)+3 at BOTH g40 (43) and g25
(~28) — one native +3 in the margin chain — so the ring (x = child x)
hugged the s(16) frame at 1-2px instead of s(3)=7. FIX: NEW site
BasePop_exec3.childx @0x602B88 (the 7B cmp after the [0x21cc]-override /
g_popup_dialog_x@0x9B8CEC merge into [esp+0x10]) → thunk_orn_childx @0xFB90:
ornate 2/6 & g>16 → x += ps3−3 = fl(19g/16) EXACT (16g>>4=g); rows/slot
frames/ring inherit via the one child-window shift; eax dead at site
(both onward paths overwrite), edx push-preserved, trailing cmp restores
ZF for the 0x602b8f je; 0x602b82 jmp lands on the cut's first byte (no
mid-cut targets); PRACX grep clean. Laws + JS ports + parity (childx
sweeps type/dlg/g incl. ZF/edx/identity) + laws tests all green.

## FRAME FLUSH 2026-08-01f -- live **4b540840** (651 sites, suite 9,368), PENDING USER VERIFY
User re-graded 0d2c4953 on shot: "Great improvements, but the frame
stroke on the unit box is not quite flush with the inner stroke of the
title box." MEASURED (both sides symmetric): title outer 1155 / inner 1162
(ps3 apart), frame 1165/2673 vs inner 1162/2676 -- the frame sat exactly
+-3 = +-frame_grow_delta(40) INSIDE the drawn inner. ROOT CAUSE: the
ornate title strokes render through thunk_box_thick, whose 9-slice draws
the stroke Delta=(g-16)>>3 OUTSIDE its rect (BOTH title strokes grown, so
their gap stays ps3 -- the tell), while the container frame draws FLAT.
The v9 borrowed type-1/2/4 container tail (whose titles draw FLAT --
that's why those verified flush) misses the compensation the quit family
carries (body_outer_edge_r = title_r + Delta). FIX: thunk_pf_union_align
v10 (460B, RELOCATED 0xF9F0->0xFBE0, old slot dead/zeros) -- the ornate
arm gets its OWN tail: edges = stash -+ (ps3 - Delta), laws
`ornate_container_edge_l/r`. Identity vs v9 for all g<24 (Delta=0);
types 1/2/4 UNCHANGED. Ring check: childx landed measured-exact (ring
left 1171 = child fl(19g/16)); after v10 the ring sits a clear gap
inside the flush frame. LESSON (repeat of the 2026-07-10 quit-modal 4px
bug, now as a family-arm variant): whenever a FLAT-drawn rect must align
with a title stroke, first ask WHICH thickener draws that title --
box_thick grows Delta outward, hollow draws flat -- and compensate
per-family, not by copying a verified arm across families.

## USER-VERIFIED CLOSED 2026-08-01 ("Everything is good") — COMMITTED
The whole arc is CLOSED at 4b540840: spritezoom + ornate banding v2 + geometry v9
+ title inset/bottom + child-x + union v10 frame-flush. The maintainer's final 1600x1200
"selection box overlaps unit graphics" report was RETRACTED after pixel measurement
showed the picker bit-faithful to pristine at 1600 (ring 50x37.8 native, even 62px
pitch, icon nub over ring-top stroke = vanilla-identical; zero stroke/art
crossings). Residual left OPEN in the maintainer's work log: ornate border art draws
native-thin (~14px @4K vs faithful ~25) — separate banding-family item.

## 2026-08-14 CORRECTION to thunk_orn_childx's premise (arm UNCHANGED, still user-verified)
Trace on the EDITORWHO picker (same ornate band 60000, same margins) shows the engine child-x
global 0x9b8cec is written @0x604292 as [30b4]+[30f0]+[30e0]+[30d8] = 47 @g40 = fl(19g/16)
ALREADY; trace_stackpicker.log has identical inputs ([30f0]=47, [30d8]=0, [21cc]=-1). So the
"engine delivers s(16)+3 = 43" premise (two-point PIXEL inference) was wrong; the +ps3-3 is an
effect-verified compensation for the ornate frame relation, not a chain-derived one. Keep it
(stack picker verified WITH it; EDITORWHO tolerates it at <=1.5 native/side) but never cite its
docstring as engine truth — measure the frame arm if the ornate child-x ever comes up again.
