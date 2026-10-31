---
name: project-smac-scenario-editor
description: Scenario-editor arc — diplomacy editor modal + editor HUD middle panel; pds-leak fix USER-VERIFIED; EDITORWHO picker CLOSED user-verified cb35ac87 (q16 v4 pds gate @0x11000 + thunk_s54_restripe hatch, pcave2 grown 0x12000) awaiting user verify; residual +4 child-x (orn_childx probe armed)
type: project
---

# Scenario editor arc (opened 2026-08-11)

Two defects from user 4K screenshot vs refs\pristine\DiploEditor.png. Analysis complete
(two static passes + hook_scenedit_census.js + hook_editorpanel_pin.js, 4K g=40 and
1600×1200 g=25 both captured, static == runtime everywhere). Symbols recorded in terranx.h.
Fixes NOT started; laws NOT yet stated in scaling_laws.py (mandatory before patching).

## Target 1 — Diplomacy editor modal (SCENARIO menu → diplomacy)

- `Console_editor_diplomacy` 0x4DB870 (thiscall) runs EDITORWHO faction picker, then
  **`DiploEditWin_exec` 0x4DB080 (thiscall RET 4, vtbl 0x66E964)** builds+runs the modal.
  Bespoke GraphicWin — NOT Popup/BasePop. `DiploEditWin_update` 0x4DADA0, loop 0x4DA990.
- All geometry native immediates, verified byte-for-byte in pristine .bak AND live trace
  (identical 758×398 at g=40 and g=25): window 0x2F6×0x18E (pushes @0x4DB0B0/B5, field
  dupes [esi+0xa14/0xa18] @0x4DB0C6/D0), dialog font 14pt @0x4DB092, title find_font 16pt
  @0x4DB200, title band +4/+0x14 (@0x4DB1AC/CB, text inset 3), faction list rect
  (4,0x1F,w/3−4,0x172) + content inset 3, CheckList rect (w/2+4,0x1F,w−4,0x172)
  (bottoms 0x172 @0x4DB27F/0x4DB41F), button strip: h 0x14 @0x4DB6A0, bottom −4,
  w=(span+2)/4, gap +2; BaseButton_init @0x4DB6E6/74D/7B4/81B (Atrocity/Integrity/Clear/OK).
- Checkbox rows scale TODAY because the right column is the shared **CheckList widget**
  (ctor 0x60E670; row-measure call @0x60E835 → FUN_0060ED10; draw FUN_0060F030) covered
  class-wide by popup_list_rowheight/rowgap/checkbox_scale/checkbox_indent. Trace: column
  width 927@g40 (=371×2.5) / 579@g25 (=371×1.5625) but container h stays native 339 → only
  ~6 of 13 rows visible. Checkbox sprites overridden to 0x779504/0x779530 @0x4DB457/5E.
- **Fix shape:** scale the 0x4DB080 immediates ×g/16 with g≤16 no-op; w/3, w/2, (span+2)/4
  divide the scaled [esi+0xa14/0xa18] so panels/buttons follow. No double-scale risk with
  popup_list_* (they scale row internals, not the container).

## Target 2 — Editor HUD middle panel (map/scenario edit mode)

- Built in **MainWin_build tail 0x45AF62–0x45B4A0**, runs AFTER thunk_hud_seedscale →
  composes SCALED rcConsoleCenter (+0xDA0) with NATIVE dims/pads. Trace-proven: 4K
  paletteSeed[0]=(662,250,705,268) = scaled left 655 + native 7, native 43×18 cells,
  pitch 44/19; brush x0 = palette[24].right+9, native 24×24, pitch 25; vertical centering
  (bottom−7 − 5·cellH − top+7 − 4)/2.
- Art: interface.pcx sheet (350,245) 25×3 cells 43×18 → MainWin+0x21E00 (extract loop
  0x45A6FD–0x45A78C); sheet (465,438) 6×3 cells 24×24 → +0x22AE4 (0x45A78E–0x45A801).
  Engraved-icon sprites will need enlargement (btn_gate path or regeneration).
- Buttons: palette FlatButtons MainWin+0x8A44 =0x7B7264 ids 0x3F3..0x40B (BaseButton_init
  @0x45B154, group +0x1E9A0); red brush +0x1A4B0 =0x7C8CD0 ids 0x40C..0x411 (@0x45B373,
  group +0x1EA34). NEITHER in thunk_btn_gate allowlist → native face draw (this is exactly
  why M/T/I scale — their seeds +0xA2C/3C/4C are in the seedscale table + strip fonts).
  Red-button build SKIPPED at SW==800 (je @0x45B30B) — keep that behavior when scaling.
- Frames: MainWin_draw_center_mode 0x45BC50 (virtual, vtbl .rdata 0x66C5C8; mode
  [self+0x1E8FC]==0x3EA) draws palette/brush engraved frames via Buffer_box_sprite
  0x5E2DD3 @0x45BCCF (+0xD4C) and @0x45BCEE (+0xD5C) — both UNARMED for thickening.
- Info text: painter_editor_info 0x45B550 — rect +0xD6C (left=brushUnion.right+3,
  right=[+0xA3C].left−s(3) at g>16 (fix 24, 2026-10-23; was an unscaled 3) — both ends track scaled neighbors already). CORRECTION of the
  static claim "never sets a font": the painter DOES set one — **find_font(0xA)
  push @0x45B5D5 (imm8 @0x45B5D6) → Buffer_set_font(0x7AEC64)** = the native 13px line
  the trace saw. Fix = scale that imm (su10 lands on font_size_table entries: 25→24,
  15.6→16, 13.75→14). Insets ±4 = ONE register const `mov ecx,4` @0x45B606 (imm32
  @0x45B607) applied to all 4 edges. Painter also draws the info frame itself via
  Buffer_box_sprite @0x45B5F8 (set 0x78D528). Writer = Buffer_write_l_3 0x5DCEA0.
  Repaint callers: 0x45BD43/0x45CD50/0x4E0A76/0x4E0EED/0x4E1FAB/0x4E1FEF/0x5179E9.
- Seed-fix insertion point: **0x45B0ED** (xor eax,eax after the red-seed loop back-edge
  jl@0x45B0EB, before the union zeroing + BaseButton loops; no branch targets into the
  5-byte window) — rewrite +0xADC/+0xC6C there and the engine derives unions (+0xD4C/D5C
  via UnionRect import [0x669328] + inflate), info rect, buttons, hit rects all downstream.
- LAWS: scaling_laws.py editor_panel_seeds(g) + diplo_editor_layout(g) (JS ports in SL;
  parity + sweep green 2026-08-11; anchored-relative rounding compounds to 1.25px@g25 —
  use scale_px per ABSOLUTE position).

## Prototype progress (hook_scenedit_fixproto.js) — pre-bake

- WORKING at 4K: 27 diplo imm patches (window/panels/fonts/title/button strip), editor
  seed rewrite @0x45B0ED, 6 frame sites retargeted to thunk_pp_boxsprite (VA 0xA0F930)
  for K-wide strokes, diplo button BAR zoom via g_popup_active refcount bracket (0xA0C530)
  around DiploEditWin_exec.
- BUTTON LABEL font (fixed after 2 misfires): FlatButton_content_draw sets NO canvas font;
  label writer Buffer_wrap_cent_4 @0x608441 uses persistent font0 = button+0x970
  (=canvas+0x52C). The 4 diplo buttons draw ONCE at build (call [eax+0xf8] right after each
  BaseButton_init @0x4DB6EF/756/7BB/822); DiploEditWin_update 0x4DADA0 only touches the 13
  CheckList items (13x call 0x60eb80), never button fonts; the modal loop never redraws the
  buttons. So a post-build font stamp is never used. FIX = stamp font0=find_font(su(14),1)
  at those 4 BUILD-TIME redraw sites (edi=button), before the sole render. Bar zoom needs
  popup_active armed (bracket already does). find_font(su(14),1) matches thunk_bw_btnfont.
- ⚠ CRASH LESSON (cinematic): attaching Interceptor INSIDE FlatButton_content_draw
  (tried 0x60838C for a per-draw swap) crashes at STARTUP — content_draw is hot and draws
  menu buttons during the intro; instrumenting it there is fatal even with an early-return
  guard. NEVER attach inside content_draw. Use the cold, diplo-only redraw sites instead.
- CHECKBOX spacing is ALREADY proportionate to vanilla (measured live g=40: pitch 50,
  gap 6, 13 rows=650 in container 848 => 23% headroom; vanilla 27%). The row pitch is
  driven by the scaled dialog font (su(14)=35pt) line height via the shared popup_list_*
  patches. NOT a defect — do not tighten unless the maintainer explicitly wants a vanilla
  departure. The big gap below the last row exists in vanilla too.
- ⚑ 2026-08-12 DIAG-TRACE (frida_scenedit_fixproto.js DIAG block) SETTLED the maintainer's two
  worries — BOTH unfounded, geometry is faithful to vanilla:
  * BUTTONS NOT too low: BaseButton_init args (leftX/topY/w/h, [esp+8..+0x14] — Interceptor
    fires BEFORE the call so args start at [esp], no ret pushed). g40 topY=935 H=su(398)=995
    -> 935/995=0.9397 == vanilla 374/398; g25 585/622=0.9405. x=10/480/950/1420 w=465 botGap=10.
  * BARS NOT banding: run-length of bar column (btn+0x498 data/+0x4c4 w/+0x4c8 h/+0x8ec stride;
    pal 0x94C590) = LAWFUL P-law device stripe ae/ee (0xAE teal/0xEE) — g40 period5 (P=(44)>>3=5,
    hN=3 -> 3+2), g25 period3 (P=3 -> 2+1). fe_pair_remap DOES cover them (heap objs, OUTSIDE
    btn_stripes early-out [0x6B4DE8,0x6C4670); ae/ee handled -> g_rm_col). Same language as rows.
  * CHECKBOX pitch proportionate: engine native rowH=Buffer_text_height([font+0x10])=17 -> at
    g>16 redirected to Buffer_text_line_height([font+0x10]+[font])=43 ~= scale_px(17,40)=42
    (Dialog +0x68 rowH, terranx.h:995). 13rows fill ~66% both native&scaled -> ~34% headroom is
    INHERENT to vanilla. Confirmed line_height fn @0x5DCAB0.
  * LESSON: Interceptor onLeave does NOT fire on a MID-FUNCTION call-site attach (no ret addr on
    stack yet) — sample persistent state at a real cold fn entry (used DiploEditWin_update 0x4DADA0
    ecx=win, buttons persist at win+0x4df8/+0x42ac/+0x3760/+0x20c8). find_font 0x5882F0 returns Font*.
- **Fix template: thunk_hud_arrowseeds** (182B block-cut @0x45A816) — the identical
  scaled-anchor+native-dims bug fixed for unit-row arrows. Also add palette/red statics
  (or array-range check) to btn_gate — explicit statics, NEVER a BaseWin range.
- ⚑ 2026-08-12 FIX-2b MECHANISM (HUD icon FACES; static analysis + prototype):
  the palette (43×18) + red-brush (24×24) icons are NOT a separate painter blit. They are
  FlatButton **stateSprites (+0xAD4/+0xAD8/+0xADC = normal/hover/pressed)** painted through
  **FlatButton_content_draw 0x607E50** via ONE **Sprite_draw_2 @0x607F43 (num=den=1)**,
  centered native-size in the (seed-scaled) button buffer. STRUCTURAL TWIN of buttons[8..10]
  (unit-row arrows) — same draw site, same class; the ONLY reason those scale and these don't
  is btn_gate's esi allowlist. Painter MainWin_draw_center_mode 0x45BC50 editor arm
  ([+0x1E8FC]==0x3EA, 0x45BCBB) only draws the 2 engraved FRAMES (0x45BCCF/0x45BCEE) + a
  redraw loop (0x45BD10, vtbl[+4]=0x5ED9D0 -> content_draw); NO icon Sprite_draw there.
  **FIX = route the 31 editor FlatButtons through btn_gate HIT** so shrink(0x607E7F ->
  native)/2dscale(0x608365 StretchBlt x g/16)/stripes zooms the whole buffer, icon included.
  PREREQUISITE = the seed rewrite @0x45B0ED (already in proto) so buffers are device-sized
  (else nativeW≈origW, zoom is identity). Icons are 2-color ENGRAVED glyphs (interface.pcx),
  NOT the 1px-scanline dither family -> no fe_pair_remap/regen tail REQUIRED (stripes runs
  anyway; remap is a no-op on non-dither art). 3 states + hover/press all flow through the
  single 0x607F43 site -> one gate entry covers all (state-agnostic bar zoom). SW==800: red
  buttons never drawn (painter je @0x45BD2A) -> gate inert there. Do NOT detour 0x607F43
  (shared w/ MENU/COMMLINK + arrows -> would double-scale them).
  ⚠ RANGE-BOUND arithmetic: palette[0]=MainWin+0x8A44=0x7B7264, red[0]=MainWin+0x1A4B0=
  0x7C8CD0; 31 btns ids 0x3F3..0x411; BUT 25*0xB4C does NOT land exactly on red[0]
  (the static pass's "contiguous" claim is off by 0xB0 — palette/red not perfectly packed). Proto uses
  generous range [0x7B7264, 0x7CD0C8) (covers all 31; M/T/I + arrows are BELOW 0x7B7264, no
  alias) and LOGS the exact distinct in-range esi ([gate] lines) so the BAKED range is
  MEASURED not computed. Proto override = Interceptor onLeave retval.replace(1) on the gate
  (VA 0xA169E0 = pcave2 0xA0C000+0xA9E0; clean CALL from btn_shrink so onLeave fires).

## Trace/tooling notes

- hook_scenedit_census.js (Win_init/Popup_start/load_pcx/extract2/OptionList census) and
  hook_editorpanel_pin.js live in work\scripts; logs frida_scenedit_census.log /
  frida_editorpanel_pin.log hold the g=40+g=25 ground truth.
- NO-ATTACH additions learned: **Font_init 0x618F40 entry is baked-detoured
  (Font_init.hud_fontobj)** and **FlatButton_content_draw 0x607E50 entry is baked-patched**
  — never Interceptor.attach either now. Win_init 0x5EBD80 census shows caller 0x5d500c
  for ALL GraphicWin_init-routed creations — need Thread.backtrace or site hooks for
  builder identity.
- Engine "scale globals" 0x696D18/1C read 1/1 — not g_popup_scale_num mirrors; don't use.

## ⚑ 2026-08-12 FIX-2b VERIFIED IN TRACE + two user-flagged residuals → FIX 2c/2d (proto v4)

- **Gate census (bake range now MEASURED, not computed)**: at BOTH g=40 and g=25 exactly
  **31 distinct esi HITs, 0x7B7264 + n·0xB4C for n=0..30** (arrays ARE contiguous; earlier
  arithmetic doubt resolved — red[0]=0x7C8CD0 is hit #26). Bake the btn_gate v7 range as
  **[0x7B7264, 0x7CD098)** (= last+0xB4C). Icons visually scale correctly at 4K + 1600
  (user screenshots 20260812/2223); user did NOT flag icon quality — only the two below.
- **Residual 1 — "channels between buttons and frame strokes unscaled" (user)**: engine
  MainWin_build rebuilds unions +0xD4C/+0xD5C/+0xD6C from the (scaled) seeds with its own
  NATIVE ±3/±4 arithmetic → stroke sits at cell−3 with ~1px black channel at EVERY g
  (measured: 4K box h=190 vs lawful 200; stroke 2px both res). Proto FIX 2c = overwrite the
  3 rects with SL.editorPanelSeeds palUnion/redUnion/info(l,t,b) at PAINTER entry 0x45BC50
  (mode==0x3EA && g>16; after every engine rebuild, before frame draws @0x45BCCF/EE);
  info RIGHT edge kept engine-side (follows live M/T/I seed, already scaled).
- **Residual 2 — "info-box bottom margin inconsistent across res" (user)**: painter steps
  y by Buffer_text_line_height 0x5DCAB0; with fonts imm-scaled to su(10,g) the step became
  the scaled font's OWN metric — SUBLINEAR (29 @g=40 vs lawful 32.5; g=25 gave 20 ≈
  scale_px(13)=20 → snug by ACCIDENT, 4K showed 12px orphan margin). Vanilla is exact:
  4+5·13+11 == 80 == box h. Proto FIX 2d = retval.replace(su(13,g)) at 0x5DCAB0 gated
  inside painter_editor_info 0x45B550 only. LAW ADDED: `info_step` in editor_panel_seeds
  (py+js+scenedit test+parity test); sweep green; fit scatter across g sweep is ±4px pure
  rounding (envelope pinned in test).
- Bake note: 2d's bake = redirect the line-height CALL SITE(s) inside 0x45B550 to a cave
  helper returning su(13,g) — do NOT touch 0x5DCAB0 itself (global text hot path).

## ⚑ 2026-08-12b user-verified 2c/2d GOOD; residual = icon-face BANDING → FIX 2e (proto v5)

- User confirmed channels/margins landed; flagged "same old color banding on the stretched
  images", worst on the hovered "Cover Map" palette button (screenshots 20260812/2244).
  My FIX-2b claim "engraved glyphs need no dither tail" was WRONG about the FACES: the gate
  HIT NN-zooms the whole buffer incl. the striped console-art face → banding.
- Mechanism: thunk_btn_2dscale ALREADY calls thunk_btn_stripes (editor statics are outside
  the BaseWin early-out [0x6B4DE8,0x6C4670)) → devfill (no-op, no fillcap) + fe_pair_remap;
  but the remap only restripes its FAMILY SET (e0/e1, ae/ee unconditional; 41/c4, 41/c6,
  41/c5, 53/bf content-keyed force-path; f0/b9 only when g_rm_f0ovr armed — btn_stripes v4
  arms it solely for sb arrows 0x6AFC10/0x6B075C). Editor face pairs not covered = the
  EXACT pre-v4 sb-arrow story repeating.
- Proto FIX 2e (evidence-driven, no guessed indices): attach thunk_btn_stripes VA 0xA0EFD0
  (E8-called from 2dscale → onLeave fires). onEnter for editor esi: detect the face's
  alternating pair from the live pre-remap buffer (12-column run-chain vote, runs ≤ P+1,
  chain ≥ 6); pair f0/b9 → write g_rm_f0ovr=1 (VA 0xA1C634); baked family → no-op; NEW
  pair → stash. onLeave: JS restripe stashed pair, y%P<hN → top member (top = chain-start
  = art's own first band; logged with palette RGBs). [stripe] log lines = measured pair
  indices for the bake (btn_stripes v5 arm if f0/b9; fe_pair_remap v8 family if new).
- Bake caution: if palette faces ARE f0/b9, v5 arm = add editor esi RANGE to the two
  static compares. If red faces are a new pair, v8 must one-shot/content-key it per
  [[feedback-dither-pair-ambiguity]] — check whether either index is solid art elsewhere
  BEFORE keying (the 0xF0 lesson).

## ⚑ 2026-08-12c ALL FIXES USER-VERIFIED runtime ("both read good", 4K + 1600×1200)

Entire prototype v5 verified: diplo modal + icons (2b) + unions/channels (2c) + info
line-step (2d) + face stripes (2e). REMAINING = BAKE ONLY.

**Measured stripe pairs (from [stripe] log, both g=40 P=5 and g=25 P=3 — bake constants):**
- ae/ee — normal-state faces, ALL 31 buttons → baked family already covers (no work).
- f0/b9 — palette-button states → arm works; btn_stripes v5 = extend the arm to the
  editor esi range (today only sb arrows 0x6AFC10/0x6B075C arm it).
- NEW e0/e2 top=e0 (120,164,212)/(92,124,188) — palette selected/state faces.
  ⚠ 0xE0's mate here is E2, NOT the baked e0/e1 family — pair-mate ambiguity: the
  UNCONDITIONAL baked e0/e1 remap writes E1 onto bottom-phase rows of an e0/e2 face
  before any new family sees it (proto's JS pass left those E1s; user judged it good,
  E1≈E2 visually, but the v8 bake should content-key the E0-mate per blit: mate = E2
  iff #E2 dominates the buffer, else E1).
- NEW a2/ef top=a2 (81,136,140)/(84,78,153) — palette hover/state faces (one g=25 draw
  voted top=ef — chain-start vote flips; bake must FIX one canonical top per family).
- NEW 6d/c9 top=c9 (32,8,6)/(136,12,12) — red-brush normal faces.
- NEW 68/6d top=6d (136,12,12)/(224,44,20) — red-brush hover/pressed. ⚠ 0x6D is in BOTH
  red pairs — same-index-two-mates, content-key by mate presence.
- Some draws "no pair detected" = solid/keyed state faces — correctly left alone.

**BAKE PLAN (nothing baked yet):**
1. btn_gate v7: editor esi range [0x7B7264, 0x7CD098) → local HIT prefix (measured census).
2. Seed-rewrite cave thunk detour @0x45B0ED: port SL.editorPanelSeeds pal/red (block-cut
   pattern like thunk_hud_arrowseeds).
3. Union/info-rect writes: painter-entry detour @0x45BC50 (mode 0x3EA && g>16) writing
   palUnion/redUnion/+0xD6C l,t,b (keep engine right edge) — proto-proven placement.
4. Diplo 31 imms + 3 painter fonts + info inset: one-time imm rewrite under g (check how
   NetWin lobby baked its g-scaled constants — same pattern).
5. Line-step: redirect line-height call site(s) INSIDE 0x45B550 → cave helper su(13,g)
   (never touch 0x5DCAB0 global).
6. popup_active bracket around 0x4DB080 + 4 btnfont stamp sites (0x4DB6EF/756/7BB/822).
7. btn_stripes v5 (f0/b9 arm range) + fe_pair_remap v8 (families a2/ef, 6d/c9, 68/6d,
   e0-mate arbitration e1-vs-e2). For every new index: grep solid-art usage BEFORE
   content-keying (the 0xF0 lesson). Canonical tops: e0, a2, c9, 6d (majority votes).
8. After bake: terranx.h symbols, CHANGELOG line, pytest guards, user re-verify all-res.

## ⚑ 2026-08-13 BAKED — build 8a490ea2 (group scenedit_scale) — awaiting user re-verify

All 8 plan steps landed in one commit; clean apply == live; FULL suite green (incl. new
62-case Unicorn parity test_scenedit_asm_parity.py + the law tests in
test_scaling_scenedit.py). Src assemble_scenedit.py (concrete bytes, slot-asserted);
14 sites + tail block 0x10640..0x10FE5 (cave now FULL — 27B slack after thunk_ed_remap;
next allocation grows the section). Laws added: scaling_laws.EDITOR_FACE_PAIRS /
editor_face_maxrun/_threshold/_chain_credits/_enable/_remap_pixel (+ EDITOR_BTN_LO/HI).

**Plan deviations (all deliberate, law-clean):**
- Step 7 shape: face pairs live in a NEW editor-scoped `thunk_ed_remap` (901B) called by
  btn_stripes v5 for editor esi only, BEFORE fe_pair_remap — NOT a fe_pair_remap v8 and
  NOT a blanket f0/b9 range-arm. Rationale: the 932B remap v7 slot had only 92B headroom
  (relocation = re-verifying a hardcoded E8 in sb_restripe + 4 callers), and the proto's
  user-verified behavior was DETECTION-gated (5 palette faces are solid "no pair" — a
  blanket arm was never what was verified). Detection = the proto's run-chain law (runs
  > P+1 break chains -> solid art can't credit; chains >= 6 runs credit; enable at 2*w
  credits — the verified log's weakest face credited ~3.5/column vs the 2/column bar).
  Fixed canonical tops f0/a2/e0/c9/6d; red 0x6D arbitration c9-wins-ties; e0/e2 owns
  {E0,E1,E2} so the main remap's E1 strays fold in and the passes compose (fixed point,
  tested). Both passes share the one phase grid.
- Step 4 mechanism: NetWin's "pattern" turned out to be data-FIELD scaling — not usable
  for .text imms. `.text` is R-X and **VirtualProtect is NOT in the exe IAT** (census).
  thunk_ed_immfix bootstraps VP once via the LoadLibraryA/GetProcAddress IAT slots
  (0x669120/0x669124, the uimod-loader pair), RWX's pages 0x45B000+0x4DB000, then writes
  all 31 imms = su(native,g) on EVERY MainWin_build — su(v,16)==v, so a mid-session
  resolution change back to native byte-restores vanilla. Bootstrap failure = bail with
  zero writes (retried next build; UI stays native — safe degradation).
- Census corrections (fixed in terranx.h + here): DiploEditWin_exec has NO vtable ref —
  0x66E964 holds 0x4E23C0; its sole consumer is E8 @0x4DBB19 (bracket site). The 4
  btnfont CALL sites are 0x4DB6EF/0x4DB756/**0x4DB7BD/0x4DB824** — the proto's
  0x4DB7BB/0x4DB822 were the `mov ecx,edi` 2B before the FF90 call.
- btn_gate v7 = 22B range prefix [0x7B7264,0x7CD098) -> HIT + v6 (188B, measured) verbatim.
- thunk_ed_seeds detour @0x45B0ED displaces 8B (xor+lea; branch-target scan of all .text:
  zero hits inside all displaced windows); painter detour displaces the 6B prologue.
- g_ed_stamp freshness key: painter copies the union stash only when it was computed for
  the CURRENT g (resolution-change safe); seeds thunk refreshes it every editor build.

VERIFY CHECKLIST (user, baked exe, no Frida): editor panel grids/channels/info margin;
icon faces incl. hover Cover Map (banding) at g=25 AND ideally g=22; diplo modal; 1024
native no-op. On success: mark arc CLOSED here + the maintainer's work log + changelog stays.

## ⚑ 2026-08-13b user re-verify: bake GOOD, 2 adjacent-modal defects; #1 ROOT-CAUSED + FIXED (build 03627866)

User: editor panel + diplo editor read good; flagged (1) quit modal "corrupted" AFTER the
diplo editor (shot -223533) and (2) SELECT A FACTION picker "slightly misscaled" (-224030).
Both pre-existed the bake (proto flow was never quit-checked after diplo).

**#1 = VANILLA BUG, proven via hook_scenedit_popupdiag.js (work\scripts, attach-audited;
launcher "SMACX Frida Trace" shortcuts repointed to it — they had still carried the old
fixproto args, which is why the first re-trace ran the wrong script):**
- Trace: quit modal control = box 1886x680 margins 82/167/38/125 hdr 95 ftr 125 (pds=0);
  after picker-CANCEL → IDENTICAL (picker innocent — user's earlier "picker was the cause"
  attribution reversed by their own isolation run); after the diplo editor → pds STAYS 6
  ([diplo_bracket:enter] pds=0 → leave pds=6) and the quit modal rebuilds as 1736x622
  margins 47/52/47/45 hdr 117 ftr 45 = the pds=6 LIST-margin family. "Corruption" = margin
  family swap, box h 622 == the screenshot exactly.
- Census: all 57 code refs to PopupDialogState 0x6A721C are byte-identical live==pristine
  → OUR PATCHES TOUCH NO WRITER. Console_editor_diplomacy clears its own picker set
  (@0x4DB9CC) but the accept path (exec @0x4DBB19 → dtor @0x4DBB2B → ret) has NO clear;
  the setter that leaks fires inside DiploEditWin_exec's call tree. Vanilla leaks it at
  native too (mild box-size change nobody noticed at 1024).
- FIX: `thunk_diplo_pdsclear` 12B @pcave2 0x10FF0 (`xor eax,eax; mov [0x6A721C],eax;
  jmp DiploEditWin_dtor 0x4E2240`), call-redirect @0x4DBB2B (PRACX-clean, no inbound
  branch targets, flags/ecx safe, eax dead). Runs at EVERY g (vanilla's bug, native
  included — deliberate, mirrors vanilla's own picker-reset idiom). Site
  Console_editor_diplomacy.pdsclear in group scenedit_scale; Unicorn test_pdsclear;
  "Will write: 706"; **cave now TRULY FULL (4B tail past 0x10FFC)**. Build
  **036278669995624f2cdca0b2bc2b0638** deployed + clean-apply==live; suite green.
  CHANGELOG: vanilla-bug line added. **CLOSED — USER-VERIFIED 2026-08-14 ("Your fix
  landed correctly")**, commit 9940532.

**#2 DIAGNOSED 2026-08-14 — two horizontal/texture defects (vertical row geometry is
LAWFUL; the earlier "fill thin vs pitch" read was WRONG).** Measurement: patched 4K shot
-005031.png vs refs\pristine\DiplomancySelect.png. **That pristine ref is an HONEST
native baseline** — NOT the engine 1.5× bump: it's a 1024×768 render PRACX-smooth-
stretched ×2.8125 into a 2880×2160 pillarbox (blended stripe edges + pitch 62=22×2.8125
prove it; divide device px by 2.8125 for native). Lawful in both shots: row fill 20.3/
20.4 native, gap ~2, pitch 22, button-bar 20, header ≈43, outer box ≈631, left chrome
bevel4/green1/rail9/green1 exact.
- (a) **Row bars ~8 native px TOO WIDE**: draw loop 0x60d8f3 draws bar at x=[D+0x40]
  (+col*(gap44+barW64) multi-col; [D+0x58]=rows/col) with w=[D+0x64], CLIPPED at the
  rows child's right edge. Patched: child w=1502 dev, bar x=69 dev → visible 1433
  (=1502−69) = 573 native vs vanilla bar x 32, w 565, child 597 (also exactly flush
  right: 32+565=597). Overrun buries the right inner green line + ~2/3 of the 9-native
  black rail. thunk_q16_fill_width couples w-arg/[D+0x5c]/[D+0x64] but [D+0x40] and the
  child/bar relation were never legislated. Screenshot-derived numbers carry ±2 native
  slop — get exact values from the trace before writing the law.
- (b) **Header/footer hatch at native period**: patched draws 1px/1px grey/black
  scanlines at device res (2.5× too fine at g=40) vs vanilla period-2-native (pristine
  shows 3px/3px stretched). Same class as popup-interior-stripes Defect 1. Suspect pair
  0x41/0x54 — the backdrop pair fe_pair_remap DELIBERATELY skips ([[feedback-dither-pair-ambiguity]]: key on the mate). RLE dump will give the true indexes.
- **CLOSED USER-VERIFIED 2026-08-14 ("fix has landed"), build cb35ac874309d32f767b186466103f47, commit a2d872a; verify trace shows w=1489 box arm + 2×0x41/3×0x54 P=5 stripes.**
  Traces (4K + 1024) pinned both: (a') NOT a [D+0x40] issue — the q16 field-MIRROR arm
  fired (fieldpads stashed the picker's rows frame: L=40 R=1564 boxw=1591 match) giving
  child 1502 vs lawful 1492; NATIVE LAW (trace, g=16 run): type-16 rows child == popup
  content area (x = Lmargin 19, w = box 637 − L19 − R21 = 597; quit: 33/655/755 same).
  The bar indent decomposes lawfully (native 28 = 19+9 → 69 = fl(19g/16)+fl(9g/16); my
  "32" was numerology, pristine says 29±2). FIX = q16 v4 pds gate: stash-match && pds==6
  → box arm; right edge = box_w − x = vanilla×g/16 exactly at 4K. RELOCATED 0x4420→
  0x11000 (v3 was 139B, ledger said 109; slot had 5B slack — MEASURED). (b) hatch pair
  CONFIRMED 0x41/0x54 → thunk_s54_restripe @0x110A0 wrapping devfill's fe call
  (placeholder retarget; fe UNMOVED — its 4 callers include sb_restripe's HARDCODED E8,
  census before any fe move). pcave2 grown 0x11000→0x12000 (freed: 0x4420 slot).
  Laws q16_fill_width + s54_hatch_keyed/s54_row_color; tests test_scaling_editorwho (20)
  + test_editorwho_asm_parity (21 Unicorn); suite exit 0; clean apply == live.
  RESIDUAL ANSWERED+ACCEPTED: [orn_childx] fires (band 60000, x 47→51). Trace math:
  child-x global 0x9b8cec := [30b4]+[30f0]+[30e0]+[30d8] @0x604292 = 47 = fl(19g/16)
  ALREADY — same inputs for the stack picker (trace_stackpicker.log), so orn_childx's
  "engine x = s(16)+3 = 43" premise was a pixel misinference; its +4 is an effect-
  verified compensation (stack picker verified WITH it). EDITORWHO effect = symmetric
  51/51 gutter vs vanilla 47.5/52.5 (≤1.5 native/side, right edge lawful) → no gate.
  Docstring of ornate_dialog_child_x carries the correction. LEDGER LIES CAUGHT: q16 "109B" was 139B; "0x4127-0x429F free" was
  occupied by thunk_basewin_gwinit — measure + yaml-regex interval map, both, always.

Related: [[project-smac-hud-scaling]] (seedscale/btn_gate/arrowseeds mechanics),
[[feedback-draw-state-multiplicity]], [[feedback-font-metric-sublinearity]],
[[feedback-remainder-distribution]], [[project-scaling-laws-harness]],
[[feedback-dither-pair-ambiguity]] (the run-chain/mate-key detection law),
[[feedback-cave-ledger-lengths]] (2026-08-13 census: full interval map re-measured).

## 2026-10-12 map place-name label across the console top (shot terranx_pracx_3840x2160_20261012) = NOT a defect
"Sea of Mnesimache" at y 1598..1623 @4K sits in the console strip's see-through tube slot (rail dithered at
1598-1605, body starts 1627; black map edge at 1628). Geometry: map window h = SH - strip 213 x g/16 (2160-532=1628)
while the strip is 257 native tall -> the map underlies the strip's top 44 native px (110 @4K) in VANILLA too, and
the strip art is keyed there (the DLL's mapgate notes: "its see-through top band IS the map to the player"). The
label pass MapWin_draw_base_names 0x467DE0 clips to the map window's own +0x474 (whole buffer); the composite is
z-ordered (Win_update_screen 0x5F7320), partial redraws go through InvalidateRect (GraphicWin_soft_update_3), so
nothing paints OVER the strip -- the label is seen THROUGH it like any terrain/unit. Only a vanilla departure
(clip labels to the strip's top) would hide it; user's call. Related: [[project-smac-mouse-scheme-proposals]].
