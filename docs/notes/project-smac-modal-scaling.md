---
name: project-smac-modal-scaling
description: Modal/dialog (popup) scaling, the first arc: checkbox sprite scale, the row indentation problem and what failed on the way
type: project
---

## >>> UPDATE 2026-06-07 — POPUP BUTTON 2D NN ZOOM **DONE** (build 339edc01, user-confirmed in-game) <<<
The button bar now does a TRUE uniform 2D nearest-neighbour zoom (caps + edges + body, both axes), replacing the
retired vertical-only post_fill_vscale (which stamped 3px caps at native size + tiled native dither -> anisotropic
corners/streaks). Closes the maintainer's work log thread (2) / tasks #18+#19. Group **`popup_button_2dzoom`** (4 thunks, all
capstone-verified via `scripts/_verify_btn2d.py`; pristine `.bak`=2d0b1438):
- KEY (from decomp_flatbtn.txt + 4K Frida): a popup option bar is a 3-piece 9-slice (TL cap x=0, TR cap
  x=[0x4c4]-3, body fill 0x608118) and EVERY piece is positioned from [button+0x4c4](W)/[+0x4c8](H). So shrinking
  those two fields before the caps makes the whole bar render NATIVE into the buffer top-left; one StretchBlt then
  upscales it uniformly. (Earlier "render-small-then-enlarge" worry was moot — the 9-slice already self-positions.)
- `thunk_btn_shrink` (pcave2 +0x400) @ FlatButton_content_draw **0x607e7f** (after both draw guards; esi=button):
  gate g_popup_active && g_popup_scale_num>16; save [0x4c4]/[0x4c8]; set native (W*16/g, -(|H|*16/g)); pending=1.
- `thunk_btn_2dscale` (pcave2 +0x480) @ **0x608365** (the `if[0xa7c]` text-block head — the convergence ALL
  9-slice branches reach, so the shrink is always matched by a restore): if pending,
  `thunk_keyed_stretch_blit(buf,buf, 0,0,nativeW,nativeH -> 0,0,origW,|origH|, key -1)` (the bounds-safe StretchBlt
  path = off-4K-safe; see skill scaling-sprites / [[project-smac-erosive-moons]]); restore [0x4c4]/[0x4c8] (text
  lays out full-size from the UNTOUCHED clip rect [0x474..0x480]); clear pending.
- `thunk_set/clr_popup_active` (pcave2 +0x4F0/+0x510) @ exec_3 prologue **0x602600** / epilogue **0x6037E0** —
  standalone detours reusing the hook points the PAUSED btnfont_enter/leave (status:skip) left free; bracket the
  modal loop so ONLY popup buttons zoom (a non-popup FlatButton drawn with a stale g is never touched).
- globals g_popup_active / g_btn_pending / g_btn_origW/origH/nativeW/nativeH (pcave2 +0x530..+0x544).
- RETIRED: `bar_fill_h` (status:skip) + thunk_fix_bar_h / post_fill_vscale / g_native_barh (dead cave bytes,
  delete on next cleanup). The skipped bar_fill_h leaves 0x608118 the pristine `CALL fill_5da9f0`, which now draws
  the native bar because [0x4c8] is native at that point.
GOTCHA (cost me the pristine .bak briefly): NEVER run `apply_patches.py --apply --target <the .bak>` — it WRITES
the target (the .bak is just a path to it) and clobbers pristine; the auto-`.bak.bak` saved it. For a re-list use
a DRY run (no --apply) or a throwaway --target copy. Normal apply flow = `cp .bak <exe>` then `--apply` (no target).
TRACE NOTE: hook_btn_2dzoom multi-res run yielded only ONE usable 4K log — frida_common `log()` caches its file
handle at the default path on the first call (the base-addr print) BEFORE any per-res rename, so all 3 res clobber
one file; and the cave-routed body fill fell outside the tap's caller filter. The decompile gave the structural
certainty instead; non-4K was covered by the in-game verify. (If reviving that hook: use a local append-mode logger
named after ScreenWidth, and don't caller-filter the cave-rerouted fill.)

## >>> UPDATE 2026-06-06 — NON-4K CRASH root-caused; frame thickening GATED to 4K as a STOPGAP (build bc827fb3) <<<
Customize Game Rules CRASHES at non-4K (tested 1920x1080 g=22 and 1600x1200 g=25). ROOT CAUSE (Frida
work/scripts/hook_crash_av.js -> work/frida_crash_av.log): the 3 frame-thickening thunks (thunk_box_thick /
_hollow / _hollow_flat) render the 9-slice frame SMALL then NN-ENLARGE-blit it back via Buffer_draw_2 ->
Sprite_draw_2 -> FUN_005e4b9a. That ENLARGE path writes ONE ROW PAST the popup dest buffer (W=1260 H=653,
alloc 822780) -> AV @ **0x5e56ef** write, fault_off=823296 => row 653 (valid 0..652). Off-by-one/rounding in
the enlarge-table walk at the non-2.5x scale (22/16=1.375); at 4K (40/16=2.5) the headroom absorbs it -> 4K-only.
The thunk_clamp_frame_rect helper (pcave2 +0x260) did NOT fix it (output extent is decoupled from the frame rect)
and remains a harmless no-op to delete on cleanup. [[feedback-buffer-resize-per-blit]]
STOPGAP applied: gated all 3 thunks to engage only at g>=40 (CMP [g_popup_scale_num],0x27; JG +6; else native
frame) — gate byte 0x10->0x27. No crash anywhere, but below 4K the frames are native hairline strokes.
*** REQUIREMENT: visual parity at all resolutions. *** Real fix (next, see
(a private note) #1): replace render-small-then-enlarge with a MULTI-PASS OVERDRAW (draw native 9-slice a
few times at +/-1px offsets to fatten strokes by (g-16)/8) -> robust at any res, never touches the enlarge OOB;
then revert the gate (0x27->0x10) and verify 4K/1080p/1600x1200. Also open: (a private note) #2 = the
Customize Rules box is too WIDE at non-4K (box_w=1260 ~66% of a 1920 screen) — g_boxw_num constant (x1.875)
holds box:text proportion only at 4K; content scales by g while box scales by the constant, so they drift off-4K.

## >>> UPDATE 2026-06-07 — bottom button ROW vertical-centering DONE (build f8da5b24) <<<
The 3 bottom buttons (Standard Rules / OK / Cancel) pinned to the TOP of their strip (gap_above~=0).
Root cause: button-row top-Y at BasePop_exec_3 0x602c1b is computed from the NATIVE band[0x30d0], but
band is re-read SCALED for the button HEIGHT at 0x602d3b -> row sits high. FIX = group `popup_btnrow_center`:
detour 0x602c49 (the `MOV [ESP+0x14],EAX` storing Y) to `thunk_btn_vcenter` (pcave2 +0x220) which adds
**botmrg/4** (`[ESI+0x30ec]>>2`) to Y at hi-res, splitting the slack above/below. Preserves ECX(rmrg)/EDX(vtable)
via PUSH/POP. Lo-res g<=16 -> JLE past the add (native no-op). NOTE: botmrg field (45@4K) OVERSTATES the real
slack — botmrg/2 OVERSHOT (too low), botmrg/4 is centered (CONFIRMED in-game 2026-06-07). Tune via the SAR
divisor (`C1 FA 02`=/4). GLOBAL: applies to every BasePop popup that lays buttons out this way, hi-res gated.

## >>> UPDATE 2026-06-06 — g_boxw_num CORRECTED 26 -> 30 (box was ~14% too narrow) <<<
The 2026-06-02 claim below ("g_boxw_num=26 matches pristine, DO NOT bump") was WRONG — it rested on a
flawed pixel measurement (60.7% vs 62.9% text-fill). The engine **boxw trace** (hook_boxw_trace.js,
run-frida-boxw-trace.bat; logs box_w composition at BasePop_calc 0x603D82, before/after the x-multiply)
settled it with no pixel guessing, native base vs patched both at 3840:
- NATIVE final box_w = **679** (657 + margins 10+12), content scale [0x3104]/[0x3108] = **1/1**.
- PATCHED box_w before our multiply = **863** (content scale 40/16 = x2.5), x g_boxw_num/16 + margins(25+30).
- Body/fonts scale x2.5, so FAITHFUL box = 679*2.5 = **1697**. At g_boxw_num=26 box was 1457 (=x2.15, ~14%
  too narrow -> less trailing space per row, the maintainer's "not wide enough"). **g_boxw_num=30** -> 863*1.875+55
  = 1673 (~x2.46, faithful). CONFIRMED in-game 2026-06-06 ("Perfect"), build 8682b37a.
WHY 40 over-widens (the old note's "~38%"): box_w BEFORE the multiply (863) is ALREADY partly x2.5-scaled
(native 657 -> 863), so g_boxw_num=40 (x2.5) DOUBLE-scales to ~2157 (x3.2). 26 under, 40 over, 30 right.
g_boxw_num is GLOBAL: used by boxw_scale (0x603D82, ALL [0x285]==0 popups at hi-res) + thunk_list_fill_width
(list popups). So this change applies to EVERY BasePop popup, not just Customize Rules. See (a private note).
LESSON (again): trust the engine trace over screenshot forensics for width — pixel detection on these shots
repeatedly misled (frame counted as ink, rows merged, capture-res != render-res). [[feedback-buffer-resize-per-blit]]

## >>> UPDATE 2026-06-02 — binary f298b30c; checkbox sprite scales, indentation pending <<<
Checkbox × sprite now scales ×2.5 at hi-res via group `popup_list_checkbox_scale`:
- **Real draw site**: `FUN_00405b20 @ 0x405bd4` (custom-draw vtable handler). NOT FUN_0060f030 — those sites
  (0x60f41c / 0x60f457) are dead (custom-draw vtable returns non-zero, skipping the FUN_0060f030 branches).
  Confirmed via Frida: 91 calls per session from 0x405bd9, x=3, y=17/70/123... (pitch=53). status:skip.
- **thunk_checkbox_scale** (cave 0xA40, 42B): rewrites `FUN_005e4b4a` num/den 1,1→g/16; re-centers y by (16−g)/2.
  The sprite draw cap at `DAT_0066fdc8` = double 4.0 (not 0.0 as first guessed from a 4-byte read) → safely
  passes 2.5x (no cap issue).

**Indentation problem (unsolved, paused):**
- Checkbox sprite (40px) now overlaps the text start — text/frame starts at native x=3+21=24, icon extends to 43.
- **Failed attempt**: `FUN_00405b20.checkbox_textx` (site 0x405bdf, thunk_checkbox_textx @ cave 0xA70, status:skip).
  Patched `add eax,0x15; mov [ebp-0x14],eax` to scale the advance by popup_scale(21)=52. This moved the
  **9-slice frame** (Buffer_box_sprite @ 0x405bf6 reads &[ebp-0x14]) to x=55 — but the TEXT (drawn by
  `call 0x5dacb0` @ 0x405c24) did NOT move. Its args come from TABLE lookups at 0x8c6e60/0x8c6ca0 (indexed
  by row_index×8), NOT from [ebp-0x14]. So the failed lever only moved the frame box, not the label text.
- **User direction (2026-06-02)**: "the buttons need to move to the left and the box needs to expand" — the
  correct fix is to shift the WHOLE ITEM LEFT (start it at x=3, the checkbox x) and widen the box by
  popup_scale(16)−16=24px to keep the text area the same. The lever is the INITIAL base_x (= ecx at
  0x405b95, saved to [ebp-0x14] before the +3 checkbox offset). Additionally, the text table objects at
  0x8c6e60/0x8c6ca0 probably store the text x-offset and need separate scaling.
- **NEXT**: Frida-trace `call 0x5dacb0` args + the table values at 0x8c6e60 to find the text-x source, then
  patch the right lever. Also patch base_x scaling so frame starts at checkbox position. Then widen box.

**Additional user-requested tasks (action items):**
- NN-scale button bar image (task #18) + button corners (task #19) — explicitly requested 2026-06-02.

## >>> UPDATE 2026-06-02 — binary f964581c; Customize Game Rules row-gutter + box-width DONE <<<
Two more confirmed fixes (Customize Game Rules polish), both in patches.yaml:
1. **popup_list_rowgap** — the inter-row gutter was the row-margin field `[+0x44]` (row pitch = `[+0x68]`
   line-height + `[+0x44]`), a native ~3px that never scaled -> rows packed too tight (~6% of pitch vs pristine
   ~14%). The setter isn't a findable literal (struct-copy default), so `thunk_rowgap` (cave 0xA00) SETs the field
   = `popup_scale(3)` (=3*num/16 ≈ 7px @4K) at the FUN_0060ed10 else-path pitch calc **0x60f018** (`mov ecx,[eax+
   0x68]; mov edx,[eax+0x44]; add` -> call thunk; returns ecx=pitch), gated `[+0x58]rows>1` + hi-res. Setting the
   field once (not accumulating) -> no compounding on re-layout, and it propagates to the box-height reserve, the
   render row-advance, AND the hit-test (FUN_0060f030 @ 0x60f1b8 reads the same `[+0x44]`). One lever, consistent.
2. **BOX WIDTH** — `boxw_scale` (BasePop_calc 0x603d82) and `thunk_list_fill_width` were both scaling by
   `g_popup_scale_num` (x2.5) -> box over-widened, longest text filled only ~38%. ROOT CAUSE: the box:text ratio
   is a PROPORTION (about margins), resolution-INDEPENDENT — it should NOT use the x2.5 screen/font scale. Added a
   constant **`g_boxw_num=26` (=x1.625, cave 0xA30)** and repointed BOTH thunks' width-scale `imul`s onto it.
   *** VERIFIED PIXEL-PERFECT vs pristine: longest list text fills 60.7% (ours) vs 62.9% (pristine
   CustomizeRules.png) — within rounding. DO NOT bump g_boxw_num; it matches pristine. *** The pristine PNG
   includes background (greyish-blue ~(117,145,152), b-r≈35) — distinguish the real row highlight (b-r>55) or the
   bg gets misread as content (earlier measurement bug). The "box feels slightly too narrow" the maintainer noted is
   NOT the box width — it's the unscaled CHECKBOXES (next item): in the list render FUN_0060f030 the × is drawn by
   `FUN_005e4b4a(dest,sprite,X,Y,num,denom)` with a HARDCODED `1,1` (native ~16px) while text is 40px -> ~2.5x too
   small RELATIVE to text (pristine has both native). TWO call sites (checked/unchecked, decomp ~lines 188-201).
   FIX (next): change `1,1` -> `(g_popup_scale_num,16)`; confirm FUN_005e4b4a's scale-arg order first.
   This will NOT widen the box (icon column [0xc36] already << text width in calc_dims' `max()`).
NEXT after checkboxes: (B) TITLE/content HEADER font ("CUSTOMIZE GAME RULES" still small); (C) re-verify button
vertical band margins vs pristine (may be fine post box-grow); (D) gate thunk_content_frame to lists. See below.

## >>> UPDATE 2026-06-01 — binary a380d88c; Customize Game Rules SCALES CORRECTLY <<<
Three confirmed fixes (all in patches.yaml, group names noted):
1. **popup_list_rowheight** — `FUN_0060ed10` row height was sized from `Buffer_text_height` (glyph height) so
   40px option text was clipped at the bottom; redirected the 2 calls @0x60ef29/0x60ef40 to
   `Buffer_text_line_height` (full line height). Fixes clipped descenders in list popups.
2. **popup_box_grow FIX** — `thunk_grow_box` grew boxH by `[0x30b0](button COUNT) * (scaledBtnH-btnH)`, so a
   3-button row over-grew the box by 3x -> big empty band below the buttons. Changed to `1 * (scaledBtnH-btnH)`
   (one row's worth). Even bottom margin now. (This — NOT button-vertical-centering — was the real bug; the
   btn_vpad_scale [0x30e4] x2.5 attempt OVER-corrected and is left status:skip / group popup_button_vcenter.)
3. **popup_list_fill_width** — multi-row LIST popups (Customize Game Rules' 18 checkbox "buttons") were sized to
   the TEXT width (~880) inside the boxw_scale'd box (2222), so rows filled only ~40%. Vanilla intent = full-
   width selectable rows (text left-justified, lots of empty space after). Fix has TWO patches, both gated to
   multi-row lists (element row count [+0xcc] > 1) at hi-res:
     • `thunk_list_fill_width` (replaces `call GraphicWin_init` @ FUN_0060e800:0x60e8a1) scales the list's
       GraphicWin width ARG + the fields [+0x5c] (buffer) and [+0x64] (Buffer_copy_4 row-bg width) x popup_scale,
       then tail-jumps GraphicWin_init. Widens the buffer + per-row highlight/box.
     • `thunk_content_frame` (replaces `call Buffer_box_sprite` @ Popup_on_draw_background:0x406238) forces the
       popup content-frame rect.right = boxW([esi+0x30bc]) - left, so the green list frame fills the box instead
       of drawing at the old ~880 logical bounds (a vertical green line cutting across the rows). NOTE: the frame
       width came through a branch that discarded earlier field-scaling — overriding at the draw call was the
       robust fix. KEY LESSON: list elements have TWO widths — a drawing buffer (scaled at init) and a stored
       logical-bounds width (set at layout); the frame/bounds use the latter, so scale at the DRAW call site.
*** KNOWN REGRESSION (2026-06-01): thunk_content_frame is UNGATED — it forces rect.right=boxW-left for EVERY
popup. User saw it FIX some modals but REGRESS others (green frame/bg clips vertically). TODO before shipping:
gate it to multi-row lists (content elem [+0xcc]>1; esi=popup, elem=[esi+0x21d0], DR=esi+[[esi+0x21d0]+8],
count=[DR+0xcc]), AFTER enumerating which modals the ungated change helped vs broke. See the maintainer's work log (C). ***
NEXT (user priority, 2026-06-02): (A) MARGINS on this screen — button-to-button gaps + button-to-frame inset,
suspected all unscaled (native px); levers = pad literals [0x21b0]/[0x21b4]/[0x21b8]/[0x21bc] + [0x30e0]/[0x30e4]
(*3/2 leftover) + [0xc38]; scale per-use (global scale of [0x21b0]/[0x21b4] broke layout before). (B) title font.
(C) content-frame regression on other modals (gate thunk_content_frame).

## >>> EARLIER STATE (2026-05-31) — binary c1b03876; resume via the maintainer's work log <<<
Body FONT (40px, modal_scaling) + ART (popup_art_scaling, both paths) scaled & confirmed.
added option-BUTTON scaling (confirmed to 50px) and a body WRAP-WIDTH patch (untested). The old
"single-source rectangle resize" plan below was SUPERSEDED — Win_init-H scaling crashed; instead we
scaled the button at the layout/draw level. Two threads remain (see the maintainer's work log): (1) confirm the
wrap-width patch in-game; (2) the button 2D NN zoom for crisp corners.

### POPUP BUTTONS — scaled to 50px, CONFIRMED (corners/edges still need the 2D zoom)
Achieved via 4 patches (full bytes/sites in patches.yaml; map in terranx.h "Popup option-BUTTON SCALING"):
  1. btnh_at_create @ 0x602d3b: scale [popup+0x30d0] (button height) at the LAST read before creation
     (layout writes @0x404D0B/0x603FF5 don't reach creation -> dead, status:skip).
  2. box_grow @ 0x602861: grow boxH by count*(scaled-native) so the taller buttons aren't clipped.
  3. bar_fill_h @ 0x608118: the bar is THE fill at 0x608118 (caller 0x60811d), fill_5da9f0==Buffer_tile_2
     (tiles sprite -> dest rect, IntersectRect w/ buffer clip). For scaled btns the thunk stashes native
     bar H (g_native_barh) + redirects the fill's RETURN to post_fill_vscale.
  4. post_fill_vscale: in-place NEAREST-NEIGHBOR VERTICAL upscale of the rendered bar (row R<-src
     floor(R*nativeH/targetH)). Vertical-only -> corners/dither anisotropic. FINAL fix = 2D NN zoom
     from a 1x render (deferred until the popup WIDTH is right; design in the maintainer's work log thread 2).
Button buffer format (embedded Buffer @ button+0x444, locked only mid-draw): data=[buf+0x54],
stride=[buf+0x4a8], clip=[buf+0x20..0x2c], pixel(x,y)=data+x+y*stride (8-bit palette).
Bar art (hook_btn_dump.js): 600x20 = 3px caps + h-tiled dither middle; HOVER = 1px green border (idx 224)
at rows 0/19; corners = single dark (idx 9) pixels; NOT a resizable 9-slice -> naive tiling repeats borders.

### KEY INSIGHT from the long button hunt (still true; informs the 2D zoom):
Button = GraphicWin, redraw vtable[0xf8]=0x5D5A70 -> content draw [0x30]=0x607E50 (bar+text). Text fit-test
@0x607E50 tail: availW=rect.right-left-6; text<=availW CENTERS (0x5DD920) else LEFT-JUSTIFIES+"..."
(0x60844E) — the "misjustified left" symptom is just the doesn't-fit fallback (size doesn't drive
justification; fixing the height so 40px text fits = it centers). compute_min_size (0x5D7030) early-returns
for buttons (NULL frame corner sprites) — sizes only the box, never the button.

### (SUPERSEDED PLAN — kept for history) SINGLE-SOURCE RECTANGLE RESIZE:
Scale the button's CREATION rect (Win_init W/H via BaseButton_init param_7). ABANDONED — Win_init-H scaling
threw an AV (buffer-alloc/composition mismatch). Replaced by the layout/draw-level approach above.

FAILED levers (status:skip; don't retry): [+0x21b0/b4] padding · [+0x30d0]=20 @0x404D0B · compute_min_size ·
Win_init H alone (pads text + crashes) · [+0x4c8] alone (clipped) · [+0x480]+[+0x4c8] (text centered, bar
clipped) · fill_5da9f0 H arg (clipped + justification break) · *3/2 Stage A2 (no effect) · grow-fill-UP
(disproved popup-bottom-clip). Dead artifacts (skip) to delete: groups popup_button_box/height/font_scaling,
Stage A2 pad/content sites, thunk_scale_btnheight, btnheight_resume, g_btnfont_save0-2.
Lesson: never Python open()/write() patches.yaml (UTF-8 corruption crashed apply -> pristine). See
[[feedback-yaml-utf8-encoding]].

---
(historical resume note, superseded by the block above:)
Read the maintainer's work log for the resume checklist.
APPROACH PIVOTED to (A): scale COMPONENTS at layout time, NOT the window (per user: a fit-to-text
window sized by calculate_dimensions is correct once components scale; never blanket-scale the window).
The GraphicWin_init blanket-scale detour was REVERTED (status:skip) because it can't re-flow wrapping
text (Planetfall narrow-column failure). Metric-de-scale also abandoned (only needed for the blanket scale).

DONE & user-confirmed:
- FONT (modal_scaling group, 40px) — body/dialog text + content auto-sizing. ✓
- ART SPRITE scaling (popup_art_scaling group): BasePop_close sets the sprite ratio [+0x3104]/[+0x3108]
  = g_popup_scale_num/16 (drives layout reservation + Path-B draw); AND Popup_calculate_dimensions
  repoints the Path-A custom sprite draw [+0x3168] to thunk_sprite_draw (cave 0x6B0) which passes
  num/16 instead of sprite_draw_func's hardcoded 1/1. Both Quit (Path A) + Planetfall (Path B) art
  confirmed scaling. ✓ (BasePop_on_redraw 0x604AB0 has the two draw paths; sprite_draw_func=0x404860;
  sprite blit=FUN_005E4B4A=0x5E4B4A __stdcall(dest,sprite,x,y,num,den)).

REMAINING COMPONENTS (per user's v1 font-only review — all confirmed needed):
- [ ] WRAP-COLUMN WIDTH (Planetfall text column too narrow) — scale the declared/wrap width at layout.
- [ ] BUTTON BOX (thin OK bar) — scale [popup+0x21b0]/[+0x21b4]/[+0x21b8] before BasePop_calculate_dimensions.
- [ ] BUTTON FONT (small button text) — FlatButton font global DAT_009B8E34 (set by BaseButton_set_def_font
      0x6074B0; popups_normal calls it (0,0,0) = NO-OP, so it's unscaled). Find its real setter or set it.
- [ ] CAPTION/TITLE font ("SID MEIER'S..." small) — used by def_caption_draw 0x4554C0; find + scale.
- [ ] then faction coverage (config_game uses a non-BasePop_exec_3 path) + multi-res + V2 font table.

**v1 RESULTS (screenshots, the GraphicWin_init build):** MIXED.
- Quit, CreateBase = CORRECT (~2.5x). Fixed-layout popups scale exactly once via GraphicWin_init.
- CustomizeRules, Planetfall = OVER-SCALED (~6x) = DOUBLE-SCALE: they auto-size to text, so the 40px
  font ALREADY scales their content 2.5x, then GraphicWin_init scales the box AGAIN.
- Faction = box unscaled + 40px font = overlap. COVERAGE GAP: config_game shows its dialog via a path
  OTHER than BasePop_exec_3 (the fn I bracketed for the gate), so geometry never fired.

**THE GraphicWin_init LEVER (the breakthrough, validated + applied):** every popup element (box,
buttons, listbox, headers, text fields) is created via GraphicWin_init(this,x,y,w,h) @ 0x5D4EF0.
Detour it (push/ret trampoline preserving regs) to scale x/y/w/h by popup_scale when g_popup_building>0
(counter inc at BasePop_exec_3 0x602600 entry / dec at its single epilogue 0x6037E0). One lever scales
all element types; hit-rects scale with visuals so INPUT WORKS; text stays crisp (40px in scaled windows).
Group `popup_geometry_scaling` (3 sites: GraphicWin_init.popup_geometry_detour, BasePop_exec_3.popup_flag_enter/leave).

**DOUBLE-SCALE FIX (designed, prototype ready, NOT yet ported):** de-scale the 7 font-metric fns
(Buffer_wrap_height/text_width/text_height/text_line_height/wrap_height_flying{,_2,_flush}) by 16/num
WHILE BasePop_calculate_dimensions (0x603800) is on the stack -> layout computes native, GraphicWin_init
does the one-and-only 2.5x, 40px font fills it. Font inflation is at MULTIPLE levels (popup [0xc35]/[0xc36]
AND dialog-intrinsic [+0x21fc]/[+0x222c] from per-type dialog calcs), so de-scale at the metric SOURCE.
Port = g_popup_layout counter (bracket 0x603800) + popup_unscale (eax*16/num) + 7 metric epilogue detours.

## ORIGINAL (history): STARTING modal scaling. Target: dialog pop-ups ("modals") on the Start Menu, first the **Faction Select** screen ("CHOOSE YOUR FACTIONS"). At 4K the whole modal renders at native ~420x270 parked in the top-left corner, fully unscaled.

**Faction Select = a `SetupWin`** (-> `GraphicWin` -> `Win`) — the SAME class we already patch for ocean/erosive deco (`SetupWin_draw_item` @ 0x4AE6BC). Renders into its own offscreen `oCanvas` Buffer, composited to screen at native size+pos. Input via `SetupWin_on_left_click(x,y)` / `on_mouse_move(x,y)`. Geometry from `Win_init(x,y,w,h,...)` / `Win_resize`.

`Win` base (engine_win.h:1059) has `iVertScaleDenom`/`iVertScaleNum` (vertical-only, UNREFERENCED in thinker) = leftover 800x600<->1024x768 vertical stretch, NOT a general 2-axis scaler. Don't rely on it.

**APPROACH DECIDED (user, option 2 of 3):** CRISP per-dialog relayout — grow the window + re-render text at scaled font + scale each control's position/size, NOT the cheap upscale-blit (rejected: blocky text). BUT user's explicit constraint: "a lot of gameplay windows likely use the same paradigm. We want to identify REUSABLE functions and methods that will minimize the per-modal work in the future." So: extract shared scaling primitives (central screen-scale, scaled-font, scaled control-placement chokepoints) so future modals cost only "supply this dialog's layout constants." Mirrors the [[project-smac-erosive-moons]] reusable-primitive ethos.

Rejected options: (1) uniform upscale-blit + input remap (reusable but blocky text); (3) hybrid upscale-art + crisp-text.

## ARCHITECTURE MAPPED (2026-05-30) — the modal pipeline is FULLY SHARED
Faction Select is built by `config_game` (0x589d30) but the modal itself is a **Popup/BasePop**
(GraphicWin subclass w/ FlatButtons + Sprite + Dialogs listbox). The whole game's modals funnel
through **`Popup_start` (0x406380, 133 callers)** -> `BasePop_start` (0x601bf0) -> dimension calc.
The dropdown strips inside (openitem.flc) are a SEPARATE SetupWin path ALREADY scaled by
[[project-smac-menu-strip-scaling]]. So modal scaling = patch the shared BasePop/Popup pipeline ONCE.

**Popups size themselves PARAMETRICALLY** in `BasePop_calculate_dimensions` (0x603800) +
`Popup_calculate_dimensions` (0x404b10) + `BasePop_init` (0x6015b0): width/height derive from
live font metrics (`Buffer_text_line_height`, `Buffer_wrap_height`) + content + pixel paddings.

**ENGINE ALREADY HAS a high-res popup mode, hardcoded 1.5x:** at `ScreenWidth>0x3ff` it does
`padding/content * 3 / 2` (sites: 0x603800 lines ~38/39/85/328; 0x6015b0 ~607). That 1.5x cap is
WHY modals are tiny at 4K. The reusable lever = replace `*3/2` with `*S` (S = resolution scale).

**FONTS — the crisp lever is `config_popups` (0x588aa0, called once by system_init):** it assigns
ALL popup/dialog/button default fonts at FIXED size 0x10=16 (`find_font(0x10,variant)`; 800-mode=0xc)
plus MainFontSize/InterludeFontSize(0x10 default)-derived. `find_font(size,variant)` (0x5882f0)
nearest-matches a FIXED 12-size table @ 0x68f220 = **{40,36,32,24,22,20,18,16,14,12,10,8}** into the
Font object table @ 0x93fc58 (row stride 0xa0 = 4 variants x 0x28). Variants @ 0x68f250 = {0,1,2,4}.
Fonts are Arial(<=12)/Arial-Narrow(>12) TrueType -> CRISP at any table size. Scaling the requested
size by S gives crisp larger text with NO new assets; cap = 40 -> 2.5x max (16->40).
  - 1280x1024 (1.25x): 16->20 exact;  1920x1080 (1.40x): 16->22 exact;  4K (2.8x): 16->40 (capped 2.5x, still crisp ~89%).

**SPRITES/portraits** scale via a built-in num/denom ratio `[0xc41]/[0xc42]` (== `[0x897]/[0x898]`,
case 8 in calc_dimensions) applied to sprite w/h (0x603800 lines ~70/71, 410/411). Drive it to S to
scale the faction leader portrait / orbital thumbnail / portrait strip.

**POSITION:** calc writes computed pos to DAT_009b8cec/009b8ce8; centering likely auto-picks the
larger dims (verify during impl). ScreenWidth=0x9B7B1C, ScreenHeight=0x9B7B20 (== BasePop [0x285]/[0x286] fullscreen, [0x288]/[0x289] dims).

## REUSABLE PLAN (option-2 crisp relayout, done ONCE in shared code)
S = scale_uniform = min(ScreenWidth/1024, ScreenHeight/768) via int num/denom (engine already uses num/denom).
1. config_popups (0x588aa0): scale requested font sizes (the find_font(0x10/MainFontSize,..) calls) by S.
2. calc_dimensions x3 (0x603800/0x404b10/0x6015b0): replace `*3/2` with `*S`; scale pixel paddings/margins/
   button-size literals by S; DON'T double-scale font-derived content height.
3. Sprite num/denom -> S.
4. Verify centering; adjust if hardcoded.
RISK: shared high-traffic funcs -> a bug breaks EVERY dialog. Test simplest yes/no popup first, then faction select.

## EMPIRICAL FINDINGS (2026-05-30, two test iterations) — READ BEFORE MORE PATCHING
Patcher base now `2d0b1438`; full patched MD5 after Stage A2 = `fa4f1262`. INFRA WORKS:
- Stage A1 (font): popups_normal hook + 9 font repoints applied. CONFIRMED g_popup_scale_num
  computes to 40 at 4K (the listbox/dialog font visibly grew -> find_font(40) returned).
- Stage A2 (geometry): the 5 `(x*3)/2`->popup_scale patches (8-byte `8D 04 40 99 2B C2 D1 F8`
  -> `E8 {popup_scale} 90 90 90`) at BasePop_calculate_dimensions 0x603955/0x603969/0x603AD7/
  0x60412C + BasePop_init 0x60171E applied & verify-clean.
**BUT: NO dialog box grew.** On Faction Select ONLY the Dialog/listbox default font ballooned
(overlapping fixed rows); title/buttons/quote unchanged; box fixed. Load Game / Custom Rules also
unchanged. So:
1. The complex SETUP dialogs (faction/load/custom-rules) do NOT size their box via the
   BasePop_calculate_dimensions path I patched. My `(x*3)/2` sites are ALL in the `[0x285]==0`
   (non-external-window) branch; these dialogs likely take the `[0x285]!=0` external-window branch
   (field_A14 = BasePop_set_external_window), so my patches are dead for them.
2. UNTESTED: whether a SIMPLE message/yes-no popup (the auto-sizing class) DOES grow with Stage A2.
   The maintainer only tested complex setup dialogs.
## A/B TRACE RESULT (2026-05-30, DEFINITIVE) — vanilla vs patched, both at 4K, via hook_modal_dims.js
All popups are `[0x285]==0` (NOT external-window — that theory was wrong). Logs (frida_modal_dims.log
= vanilla+crashfix; frida_modal_dims.PATCHED.log = full modal build):
  QUIT popup: boxW 777->777 (IDENTICAL), boxH 284->316, contentH 20->46, padY 6->10, font 0x9400b8(16)->0x93fc58(40)
  MENU popup: boxW 622->622 (IDENTICAL), boxH 182->684 (3.75x!), contentH 100->598, font 16->40
**MODEL: SMAC popups have a FIXED WIDTH + AUTO-SCALING HEIGHT.** Font + padding(my patches) + height
all scale; WIDTH and listbox ROW-HEIGHT are HARDCODED (not font-driven). So:
- Short-item popups (in-game menu, BasePop strings) scale fine (height grows w/ font: 182->684).
- Long-line popups (quit options, faction listbox = a Dialog) OVERFLOW the fixed width + fixed row
  height -> the "mangle". The Dialog LISTBOX rows stay ~22px under 40px text (vertical overlap).
My font(Stage A1) + *3/2(Stage A2) patches ARE applied & work but don't touch width/row-height.
boxW=777 traced: calculate_dimensions [0x873]==-1 branch -> boxW = dialog intrinsic width field
[~0x21fc] + 2*padX; that field is FIXED ~677(listbox)+margins, NOT measured from the 40px text.
Listbox created in FUN_0060d1f0 @ ~0x60d299 GraphicWin_init(x,y,w=677,h=68) reading computed dims.

## APPROACH PIVOT (2026-05-30): GraphicWin_init geometry scaling (VALIDATED via Frida prototype)
After proving per-field crisp scaling is a deep per-type swamp, found the clean reusable lever:
EVERY popup element (box, buttons, listbox, headers, text fields) is created via
`GraphicWin_init(this, x, y, w, h, ...)` @ 0x5D4EF0. Frida prototype (scripts/hook_popup_upscale.js,
gated by BasePop_exec_3 @ 0x602600 depth, scaling x/y/w/h by g_popup_scale_num/16) -> the WHOLE
quit popup scaled uniformly 2.5x, fills the screen, crisp text, clicks still land (hit-rects scale
with visuals since we scale real window geometry, not pixels). USER CONFIRMED "this is correct,
2.5x at my res". So the plan:
- KEEP the font scaling (modal_scaling group, 40px) — needed for crisp text in scaled windows.
- GEOMETRY via a NEW group: wrap GraphicWin_init in a cave thunk, gated by a "popup building" flag,
  scale x/y/w/h by popup_scale. One lever, all dialog types, input works.
- BLITTED art (the planet image in quit; portraits in faction) does NOT scale via GraphicWin_init
  (it's blitted, not a child window) -> needs companion blit-scale (deco/thunk_keyed_stretch_blit).

## DOUBLE-SCALE FINDING (user asked to verify, 2026-05-30) — RESOLVED
The earlier Stage A1 font + Stage A2 *3/2 geometry patches PRE-inflate the box before GraphicWin_init
re-scales it: A2 (*3/2 padding, redundant ~+3%) + A1 (40px font inflates content-DERIVED height
~2.5x, ~+9%). Quit popup total ~+11% over-tall (tolerable, fixed-layout). REVERTED Stage A2 (5 sites
now status:skip, removed from group) — redundant with GraphicWin_init. KEPT A1 font (needed). CAVEAT:
A1's content-height inflation will double-scale TEXT-HEAVY popups (multi-line messages) ~2.5x too tall
under GraphicWin_init -> must verify on a text-heavy popup when porting (may need to exclude
content-derived height from the GraphicWin_init scale, or compute layout w/ native font + render at 40px).
popup_scale + g_popup_scale_num cave infra RETAINED (the GraphicWin_init thunk will use it).

## (SUPERSEDED) earlier per-type crisp plan:
1. Dialog/popup INTRINSIC WIDTH (the ~677/777 field) -> scale by popup_scale.
2. Dialog LISTBOX ROW HEIGHT (~22px) -> scale to track the 40px font.
NEXT: decompile Dialog_init(0x609150)/Dialogs_item(0x612A70)/FUN_0060d1f0(0x60d1f0) to find where the
dialog width + row height are SET, then patch those. Tooling: scripts/disasm_range.py, decompile_funcs.py.
CURRENT BINARY STATE: live terranx.exe = VANILLA+crashfix (78df4f63, via --groups win11_24h2_filelock_fix);
.bak=pristine 2d0b1438. To resume modal dev: --restore then --apply (full). patcher now has --groups/--target.
Tooling: generic decompiler `work/scripts/decompile_funcs.py` (run via env in run-decompile.bat) +
`work/scripts/dump_data.py`; dumps saved: work/decomp_faction.out, decomp_basepop.out, decomp_font.out, decomp_configpopups.out.
