---
name: project-smac-tutwin-tooltip
description: TutWin directional tooltips — CLOSED 2026-07-11 (86030421); 2026-09-17 drone-tour pointer x (thunk_tutwin_popx, VANILLA bug, awaiting user verify) + btn rounding made GLOBAL same day (1d1db63d): pointer line = GDI CreatePenIndirect (arg8 = PS_ STYLE, 5=PS_NULL invisible — scale only the width); the HUD-desync gate was hazard-#5 fallout, disproven; lever map in git history (the maintainer's work log item deleted)
type: project
---

# TutWin directional-tooltip scaling — CLOSED 2026-07-11 (build 86030421)

**EXTENSION CLOSED same day — build 1d1db63d (VERIFIED RELEASE LOCK, user "It's perfect!"):**
btn_shrink nativeH ROUNDING is now GLOBAL (thunk_tutbtn_post v2: rounded H = (|H|·16+g/2)/g for
EVERY bracketed button; the TutWin gate now guards only the canvas font; same 120B). The
"unGated rounding desyncs the HUD bracket-compose" constraint was DISPROVEN — hazard-#5 attach
fallout, see the corollary in [[feedback-frida-attach-branch-target]]; the static audit found no
consumer recomputing the floor, and the unGated tail-redirect prototype `hook_btnround.js`
(telemetry ring: HUD M/I 31→20 vs floor 19, MENU/COMMLINK 19→14 vs 13, TOOLBAR 59→38 vs 37,
popup bars 27/31→20) was user-verified at all 4 res incl. Quick Start + HUD hover before baking.
Fixes the clipped bottom outline row on every popup bar button at g=22/25. The maintainer's work log
item is deleted; full lever map lives in git history (commit d48abf4 era) + patches.yaml comments.

BAKED as group `tutwin_tooltip_scale` (6 sites + 6 cave thunks at pcave2 0xA890..0xAAD8 + gate v5
reloc + shrink/box_margin tail chains + d690 site v8); laws `scaling_laws.tutwin_stash_left/right`,
`tutwin_content_top`, `btn_native_dim`. Two bake crashes, both instructive:
(1) v1 allocated thunks inside g_bm_fx's 8KB runtime map scratch ([[feedback-cave-ledger-lengths]]
second escape); (2) the earlier Frida attach on the shrink tail re-confirmed hazard #5 and produced
the tail-target-redirect escape hatch ([[feedback-frida-attach-branch-target]]).
NOVEL: Win_window_line_raw is a GDI CreatePenIndirect wrapper — arg7 = pen WIDTH (scale it),
arg8 = pen STYLE (PS_DOT native; writing 5 = PS_NULL = invisible pen; NEVER scale). The blink
cadence hid the invisible line from every screenshot for six prototype versions.

The tooltips that point at map tiles over the HUD (crash-land "LANDFALL", terraform hints, ZOC msgs —
54 `TutWin_tut_map` callers incl. all of Console_give_hints) are ONE window: **TutWin @0x8C6E68**, a
Popup/BasePop subclass (Thinker's `typedef GraphicWin TutWindow` is a placeholder — ctor calls
Popup_ctor). Symbols recorded in terranx.h (TutWin_* block, popups_tutorial, Win_window_line_raw,
FlatButton_content_draw 0x607E50, arrow fields +0x5384..+0x53D4).

Flow (`TutWin_tut_win` 0x4BDFE0): `popups_tutorial()` 0x5888E0 → `Popup_start("TUTOR",label)` →
`BasePop_exec_3` → draws arrow lines → second Popup_start/exec_3 → `popups_normal()` → **returns with
the window still shown (NON-MODAL)**. Dismissal = TutWin_on_button_clicked 0x4BDCC0 (clears anchor
+0x53D4, arrow-armed +0x53A4).

Probe `work\scripts\hook_tutwin.js` (observer; log `work\tests\frida_tutwin.log`, 4 res 2026-07-10)
proved the three defects seen in the 4K screenshots:

1. **Wide+short box**: boxW = native 490 × g/16 exactly (1224/764/672/490 @ g=40/25/22/16) — the
   generic `thunk_scale_boxw` fires, but the body font stays native (cell 20 / glyph 12 at EVERY g)
   because `popups_tutorial` installs its OWN font set `g_text_font_v0/v1/v2` (0x945770/0x9457FC/
   0x9457F8) that no existing group scales. contentH 140→80 as the wrap budget widens.
2. **Buttons clip after hover**: footer buttons are created scaled (555×50 @4K) and first draw inside
   exec_3 with g_popup_active=1 (shrink+2Dzoom OK); hover redraws happen AFTER exec_3 returns →
   g_popup_active=0 → thunk_btn_shrink gated off → native-height draw into the scaled slot.
   [[feedback-draw-state-multiplicity]] class. Fix = a TutWin-alive arm ([[project-smac-hud-scaling]]
   g_faction_active pattern: arm in tut_win, disarm in on_button_clicked/dismiss).
3. **Pointer line native-thin**: `Win_window_line_raw` 0x5F2AC0 called with literal thickness args
   a7=a8=2 at every g (initial ret 0x4be3ff; blink redraws ret 0x4bdede in TutWin_draw_arrow
   0x4BDEA0). Scale 2×g/16.

**Fix cautions**: g_text_font_v0 is ALSO the interlude body-text pick ([[project-smac-credits-interlude]])
— do not blanket-repoint the globals; scale at the popups_tutorial install sites (bubble-font precedent
[[project-smac-tooltip-bubble-scaling]]: repoint to find_font(size×g/16), never mutate shared Font
objects, g≤16 no-op). Full lever detail + log excerpts in the maintainer's work log OPEN item.

## Prototype v6.2 findings (2026-07-10, hook_tutwin_fix.js — 8 levers, verified 4K+1600)

- **Button LABELS**: FlatButton_content_draw never calls Buffer_set_font — the label uses the font
  the button CANVAS already carries, and TutWin's buttons are persistent (fonted once at 12px).
  Lever = Buffer_set_font(btn+0x444, find_font(12×g/16,0)) at draw time. Draw-globals swap and
  BaseButton def-font install were both proven no-ops for this window.
- **Chrome root cause**: TutWin draws NO TITLE BAND → thunk_pf_title_stash never refreshes
  g_title_left/right (stale from the previous popup) and thunk_scale_header ([0xa48]!=0) never
  scales the content top ([+0x21b8]=0, [0x30e8] stays 27). Fix = feed the stash
  (scale_px(13,g)±Δ; ring native inset 13) at the backdrop draw and scale 30e8 (+boxH) post-
  BasePop_calc — the baked pf chain then computes field/ring/text correctly on its own.
- **Ornate backdrop art**: route the 0x6846B0 set through baked thunk_box_thick_hollow (frame9
  band-map, handles the 61×44 ornate cells) over the site rect UNCHANGED — the rect IS the full
  window; a Δ-expansion clipped off-canvas and produced a measured ±3px asymmetric channel.
- **GLOBAL BUG (affects all popups)**: thunk_btn_shrink nativeH = floor(|H|·16/g) round-trips the
  20-row bar art to 19 rows at g=25/22 (4K exact) → the state-sprite's bottom outline row (hover
  highlight) is CLIPPED at render. Idle draws are masked by thunk_btn_devfill's full-bleed re-tile.
  Fix = rounding before the idiv (round is half_down's inverse; floor is not). Prototype = rewrite
  g_btn_nativeW/H + shrunk dims at the thunk's tail push (pcave2+0x46E, live-bytes verified).
  ⚠ **DO NOT ROUND GLOBALLY**: v6.4 unGated crashed (AV @0x45ab2c, MainWin init) — the HUD
  FlatButtons (32x31/32x59 MainWin widgets) ride the same pipeline when drawn with a popup active
  and the hud_widgets bracket-compose sizes its scratch with the SAME floor; changing the dims
  desyncs it. Gate to popup BAR buttons (or co-fix the HUD consumers), then re-verify quit-modal
  buttons at 1600/1920. [[feedback-remainder-distribution]] [[feedback-shared-field-per-row-doublescale]]


## 2026-09-17 addendum — drone tour pointer x (exe a7ebdb86, NOT committed, awaiting verify)

DRONERIOTS -> DETAILS opens TutWin_tour6 0x4BAA70 (tour_kind +0x53C0 == 6; DRONETOUR1..6 labels).
Every step converts its target rect's CENTRE through GraphicWin_local_to_screen(MainWin_g) — EXCEPT
steps 1 and 5 (0x4BAB5B / 0x4BAD49), which push `citizens_rect.left + 5` (BaseWin+0x40C5C, raw
MainWin-LOCAL) as the target x and only use the converted y. A VANILLA bug masked at 1024x768
(strip origin x=0); with our centred 2.5x strip the 4K line ended on the console's left rail
(x=672 instead of ~1319). Fix = thunk_tutwin_popx @pcave2 0x4240 (+ g_tw_ret 0x4290) over both
5-byte `add edx,5; push ecx; push edx` blocks (CALL-entered, ret consumed to g_tw_ret, pushes
re-issued, jmp [g_tw_ret]): x = local_to_screen(MainWin_g, left_dev + fl(5g/16)); g<=16 = the
displaced insn. Law scaling_laws.tutwin_pop_pointer_x; src assemble_tutwin_popx.py; parity
tests\test_tutwin_popx_asm_parity.py. LESSON: a tour step that converts y but not x is the
"mixed-space by omission" class — grep every tut_win caller for a push of a raw rect edge.
Also: refs\pristine\DroneDetails.png is NOT a 4K-pristine capture (4:3 letterboxed, strip at 2.5x) —
use it only for the pointer's relation to the row, never for absolute coordinates.

**Second class, same day (exe cc3bd6b0, NOT committed):** every TutWin site that converts a target
through GraphicWin_local_to_screen(BaseWin_g) — TutWin_do_base 0x4BA8AB, TutWin_base_rect 0x4BC628,
tour6 0x4BADB8/0x4BAE34/0x4BAEC6 (psych steps + TOUR1PSYCHBUTTON), tour1 x14 (TOUR1*) — passes a
NATIVE BaseWin-local rect centre (the base screen scales at the primitive boundary via basewin_pt;
the rect fields +0x40D0C psych row / +0x40DDC / +0x40E3C / tab seeds stay native), so at 4K the
psych line ended in the map view (origin + (428,394) instead of + (1070,985)). Fix =
thunk_tutwin_basel2s @pcave2 0x5E0 as the call target of all 19 E8s: ecx==BaseWin_g && g>16 ->
*x,*y = basewin_pt in place, push/ret into the helper (byte-neutral for MainWin-relative device
rects). Law tutwin_base_pointer_pt (= basewin_pt); parity test_tutwin_basel2s_asm_parity.py.
RULE for any future tour/hint: the WINDOW passed to local_to_screen tells you the rect's space —
MainWin (strip) rects are device (strip seed law writes them scaled), BaseWin rects are native.

## 2026-09-19 field + ring right of centre (exe 7d407602, t_orn_fieldsub; USER-VERIFIED + measured 4K ring 33/32, 1600 ring 21/20; committed 5b58698)
User 4K shots ("there should be a bigger channel on the right edge"); same in 20260917.
FIRST FIX WAS WRONG (exe 0d37a34f, t_tw_right re-anchoring g_title_right to the draw rect): I inferred a stale canvas
width from pixels; the shot did not change. LIVE GEOMETRY (uimod debugdump, see below) then showed W 1599 == canvas,
anchors 32/1567 symmetric -> the anchors were never the problem: TutWin is ornate type 2, UNTITLED, WITH a body box, and
since pf-align v8 (2026-08-01 popup-type gate) such popups `pass` to the ENGINE arithmetic — the stash is not read. The
ring = UnionRect(field, dialog) + nest pad, so it follows the text FIELD, whose R = winR - 10 - 9 + 3 where the `sub ecx,9`
@0x40612C (ornate types only) was the one constant nobody scaled (fieldR scales the 10; titled ornate popups never see it
because fieldpads' KEYED ornate arm replaces ecx; thunk_untitled_stash DISARMS the key for ornate types, so the key cannot
be borrowed). Measured field insets L/R 40/26 @g40, 25/20 @g25 (vanilla 16/16).
FIX: law `ornate_field_right_sub(g) = fl(19g/16) - fl(10g/16)` (the LEFT margin's own cascade; bare fl(9g/16) is 1 px short
at g22), thunk t_orn_fieldsub heading the 0x40612F fieldpads site (unkeyed ornate, g>16), src assemble_ornate_fieldr.py,
parity tests\test_ornate_fieldr_asm_parity.py runs the REAL fieldpads bytes: right inset == left inset for g 16..40.
t_tw_right + its files were removed. LESSON: two symmetric-looking pixel axes do not tell you WHICH rule placed them —
read the live struct before writing a fix ([[feedback-pristine-baseline-trace]] spirit); the debugdump took 10 minutes and
falsified an hour of inference.

**uimod debugdump (reusable, src\uimod\src\debugdump.cpp):** OFF unless `uimod_debug.flag` sits next to the exe; Pause
(= the screenshot key) appends the TutWin / g_current_basepop / modal-top geometry (screen + local rects, canvas, box, margins,
+30E8/+30F0/+30F4, type, title ptr, +30D4) and g / g_title_left/right to uimod.log. Read-only, VirtualQuery-guarded, no hooks
-> safe where Frida attach is not ([[feedback-frida-attach-branch-target]]). The flag file was REMOVED from the game dir 2026-09-19 (user request); create an empty `uimod_debug.flag` next to the exe to re-enable.
