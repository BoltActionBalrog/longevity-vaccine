---
name: project-smac-loadsave-filedialog
description: Load/Save file-picker scaling workstream — root cause + builder chain + trace
type: project
---

Started 2026-06-28: scaling the LOAD/SAVE file-picker (folder icon, save-file list, filename
edit field, OK/CANCEL). Appears from main-menu "Load game", in-game save/load, scenarios.

**RE-OPENED 2026-07-01 (post-7d9ba26c lock) → FIXED in build `803cadac`, USER-CONFIRMED at ALL
resolutions 2026-07-01 ("perfect") → re-locked + CHANGELOG'd. NEW ISSUE found during sign-off (IN-GAME
only): rails missing below ~54% — ROOT-CAUSED 2026-07-02: the in-game rails are the slide-window CHROME
(`slide_show` 0x45D440, Thinker name), 4 FIXED 15×529/8×529 strip sprites (0x7CFFC4..0x7D0048) drawn 1/1
at sites 0x45D82C/51/75/A9 — fixed 529px art that vanilla windows never outgrow but our P1-scaled window
(984 @4K) does; rails end at exactly 529 device px (pixel-measured). Main menu unaffected (Path A ornate
6846b0 via our frame thunk; in-game Path B outer = d690 dither + chrome rails). FIX PART 1 build
`a8c02e57` (2026-07-02): group filedlg_chrome_rails — 4 sites → thunk_filedlg_railscale (freed pcave2
0x2560, 106B): gate g_filedlg_active && dest==g_fd_winbuf (stashed by setflag, grown 26→37B, ecx+0x444
at layout entry) && g>16; num/den→g,16 (engine multiplies dest x,y internally → left strips' native
0/15 args self-scale, the icons precedent); right strips re-anchor x'=winW*16/g−(winW−x); tail →
thunk_sprite_scale_nn (clips the 1322px strip — NEVER the engine expand path, the 1-row-OOB trap).
FIX PART 2 build `1a38279f` → v2 `d030c3d4` (2026-07-02; confirmed with the PART 3 combined sign-off 2026-07-03): user report on a8c02e57 "both
frames horizontally mis-positioned" (vs refs\pristine\Save.png). The scaled rails were CORRECT —
vanilla anchors the right pair at bufW−artW−0x20 (a 32px SCROLLBAR GAP sits outside them; backdrop-edge
2354 vs rail-edge 2330 @4K matched the model to the pixel, bufW=979). Real bug = the d690 dither
BACKDROP still used NATIVE rect deltas (FileDlg_layout Path B 0x407527..41: L+=0x17/R−=0x37/B+=0xa;
vanilla LAW: L 23 = rail width, R 55 = rails 23 + gap 32 → backdrop ABUTS the rails) → green border
25px past the right rails / buried under the left. Fix = thunk_filedlg_insets (detour_inplace of the
27B delta block @0x407527, src assemble_filedlg_insets.py): deltas ×g/16, LEFT delta COMPOSED
(15g>>4)+(8g>>4) = the rails' exact device extent at ANY g (floor(23g/16) opens a 1px gap at e.g.
g=17). v2 (d030c3d4, user-caught @1600x1200): v1's RIGHT delta floor(55g/16) is a DIFFERENT floor
cascade than the rails' floor((floor(bufW·16/g)−55)·g/16) — at g=25 the backdrop edge landed 2px past
the rail start and the rails (painted after layout) swallowed the ~2px green stroke. v2 RELOCATED the
thunk 0x26D0→0x3200 (75→112B, pcave2 length→0x3280) and computes R' = L + the IDENTICAL railscale
double-floor with bufW from [g_fd_winbuf]+0x80 → backdrop-R == rail-start at ANY g by construction.
LESSON: two patched artifacts that must ABUT must derive from ONE floor cascade. Inner
d528 + title band + caption self-correct via thunk_filedlg_frame's outer-rect derivation; content
layout untouched (rect vars dead/reused after frame draws); Path A never runs the block. GOTCHA: the
patcher's {rel32:} placeholder only follows E8 — thunk tails/detours use push {abs32:}/ret.
FIX PART 3 build `ae8f92e5` (2026-07-03, **USER-CONFIRMED at ALL resolutions same day → VERIFIED
RELEASE LOCK, CHANGELOG'd; whole workstream CLOSED**): user report on d030c3d4 "border
misplaced WHILE the dialog animates up, correct settled". The recorded y-double-scale suspicion was
WRONG — slide_show 0x45D440 AND slide_hide 0x45D970 (close animation) each have a SECOND set of 4 rail
sites inside their animation loops (show 0x45D6BA/DD/FF/0x45D728, hide 0x45DC86/A9/CE/F9) drawing the
strips 1/1 to the SCREEN buffer 0x9b7490 in SCREEN coords each frame — railscale never fires there
(different sites, dest≠g_fd_winbuf) → mid-slide rails native-size at native offsets (right pair ~80px
off @4K). FIX: 8 sites → thunk_filedlg_railslide (pcave2 0x3280, 306B, src assemble_railslide.py):
gate g>16 && (g_fd_winbuf−0x444 == [ebp+8] || == esi) — window ptr is [ebp+8] in slide_show but ESI in
slide_hide ([ebp+8] = step counter there); the FLAG is unusable (modal wrappers clear it before the
close animation). num/den=g,16 with CEIL re-anchor Ln=ceil(L·16/g)/y'=ceil(y·16/g): these draws
vanilla-rely on the screen buffer's engine CLIP RECT (Buffer_set_clip 0x5D8000, set to the window
rect) but thunk_sprite_scale_nn clips only to dest BOUNDS, and spill outside the rect is NEVER
restored (the loop's bg restore is engine-clipped) → CEIL keeps left/top inside; right strips reuse
railscale's floor cascade (Ln+floor(bufW·16/g)−offR); BOTTOM CLAMP shrinks the sprite blit-H
[ecx+0x14] around a scale_nn CALL (re-pushed arg copies, restore, ret 0x18) so the 1322px strip stops
at rect B like vanilla's clip stops the 529px one. Accepted transient: ≤2px anchor shift + possible
1px inter-strip hairline mid-slide (5 fast frames; the settled repaint from the stamped buffer is
exact). PLUS thunk_filedlg_slidehide_disarm (0x33C0, detour @0x45DE5A slide_hide common exit): zero
g_fd_winbuf when the closing window matches — FileDlg is a STACK object ([ebp-0x6884] in the 0x5a9xxx
callers), a later stack dialog reusing the address would false-positive the identity gate. LESSON
(generalizes [[feedback-frida-dedup-popup-reuse]]): an identity gate on a STACK/heap object pointer
needs a DISARM at the object's end-of-life, not just a fresh stash at setup. pcave2 length→0x3400.
172 sites, capstone-verified, pytest 143 green.**
Two user reports: (1) FUNCTIONAL — entering a folder redrew the list with a native-height selection
highlight + vertically-clipped row text; backing out ("..") left the modal severely impaired (buttons
missing, icons undrawn). (2) COSMETIC — the "LOAD" caption sat jammed on the TOP frame stroke with the
scaled 50px title band EMPTY below it.
- **Root cause 1 (nav corruption):** `[+0x68]` is a DERIVED field — `ListBox_calculate_dimensions`
  (0x60A1E0) re-derives `[+0x68] = [+0x48](stride 22, single store @0x40777A in FileDlg_layout) −
  [+0x44](gap)` on EVERY populate, and directory navigation re-populates via the inline
  `FileDlg_populate_list` 0x614360 path (cmd 3 = up-dir / activate-entry 0x6146A0 via handler 0x614B90;
  the [[feedback-scaling-inline-rebuild-paths]] class). listpitch v1 scaled the derived field and gated
  on it: after nav, calc produced 22−15=7 (unscaled source − scaled gap), the ≤16 gate re-fired, the gap
  double-scaled to 37, and back-out derived 22−37=**−15** rowH → inverted clip rects/negative-height
  fills = both symptoms. **FIX = listpitch v2** (RELOCATED pcave2 0x26C0→0x3160, 90→99B): key the
  one-shot scale on the SOURCE `0<[+0x48]≤0x16` (nothing rewrites it; 22·17/16=23>0x16 closes the gate
  at any g>16), scale [+0x48]/[+0x44]/[+0x34] ×g/16, then ALWAYS re-canonicalize `[+0x68]=[+0x48]−[+0x44]`
  → every calc_dims rebuild self-heals. (Layout-time scaling of the source was considered and REJECTED:
  no static proof of when +0x44/+0x34 get their native values relative to FileDlg_layout.)
- **Root cause 2 (title):** vanilla centres the caption in the SAME stack rect the d618 band draws with;
  P3c's thunk_filedlg_frame re-derives the scaled band into g_fd_scratch repointing only the FRAME draw
  → text centred in the stale native 20px band at y≈15. **FIX = new group `filedlg_titlerect`**:
  thunk_filedlg_titlerect (pcave2 0x31D0, 23B) call-redirects both Buffer_write_cent_l_7 sites
  (0x407B9A load / 0x407A3A save), gate g>16 (same as frame thunk → scratch guaranteed fresh), repoint
  [esp+8]→g_fd_scratch. Exact mirror of the shipped thunk_faction_titlerect; no ink nudge (faction
  precedent verified centred at g40+g25). If it reads ~3px low in-game: planned (g−16)/8 nudge variant.
- 158 sites/2 caves; thunks + redirects capstone-verified in the applied exe; old 0x26C0 slot zeroed;
  pytest green (locks updated: group set + 158 count). Nav-path symbols recorded in terranx.h + Ghidra.
- VERIFY protocol: open LOAD → enter folder → back out ×3 (state stable) at 4K + non-4K + 1024 no-op,
  plus caption centred in its band. Then re-lock + CHANGELOG.

**P3c CONTINUATION (2026-06-29, live MD5 `e7195da0` — INTERMEDIATE; margins user-confirmed, ONE open
artifacting item):** after the `64a13505` lock, two non-4K defects surfaced + were fixed:
- **LIST-ROW DOUBLE-SCALE** (rows ~1.5× too tall below 4K): `thunk_filedlg_listpitch` mutates the SHARED
  `Dialog[+0x68]/[+0x44]/[+0x34]` IN PLACE and `ListBox_draw_item` runs per-row, so the old `cmp lh,0x20;
  jge skip` guard let row#2+ re-scale what row#1 left (16→25→39 at g25). 2-byte fix → `cmp lh,0x10; jg skip`
  (scale only while native ≤16). Rows now uniform + proportionate. See [[feedback-shared-field-per-row-doublescale]].
- **INNER-FRAME right-stroke collision** (OK/CANCEL + rows hit the inner-right stroke at 1600×1200; left
  margin fine): the NN frame-enlarge floor-quantize insets right/bottom strokes, LARGE at low g, ~0 at 4K.
  A v9 `popup_scale(3)` right-push (3170eacb) was WRONG (scales backwards, crushed the 4K inner/outer
  channel — user 4K shot). v10 fix = route the inner frame through `hollow_flat + g_fc_exact` (exact-fill,
  like outer/title) so all 4 strokes render flush at any g. Margins now balanced (user-confirmed).
  See [[feedback-floor-inset-resolution-inverse]]. `thunk_filedlg_frame` now 435B (keystone src
  `scripts\assemble_filedlg_frame.py`).
- **OPEN action item:** the modal's background blit artifacting is slightly WORSE after the v10 inner
  exact-fill (StretchBlt resample of the inner frame region). Deferred by user — tracked in the maintainer's work log.
  NOT re-locked as a clean release until that's addressed.
- **v11 devfill ATTEMPT — FAILED, REVERTED (2026-07-01, tried c5a785a1, reverted to e7195da0).** Tried
  routing do_outer/inner/title tails `HOLLOW_FLAT → thunk_box_thick_devfill`. **RESULT = strictly worse
  (user-confirmed):** the ornate metallic outer bevel went BLACK + interior flat near-black. devfill was doomed
  because it assumes {thin stroke + a tileable dither SPRITE in params[8]}; the file-dialog frames have NEITHER.
- **RUNTIME TRACE CORRECTIONS (2026-07-01) — supersede earlier guesses:**
  1. **The frames are genuinely HOLLOW.** `Buffer_box_sprite` params[8] (+0x20, "fill") is a pointer to an
     EMPTY sprite (data=0,w=0,h=0) → NO interior fill drawn. params[9] (+0x24)=7 is a **color KEY** (arg to
     Buffer_tile_mask), NOT a "fill mode." The earlier pass "mode-7 translucent fill" reading was a MISREAD.
     (frida_filedlg_boxparams.log.) So the backdrop is NOT in the frames.
  2. **The file dialog is NOT on a unique rendering scheme** (my "native buffer whole-scaled" theory was WRONG;
     user's intuition was right). frida_modal_bufsize.log @4K: file-dialog window = `GraphicWin_init w=835 h=982`
     (=334×2.5, DEVICE-res) composited via `Buffer_draw_2` **key=9 scale 1:1** to screen. Faction picker =
     `GraphicWin_init w=1975 h=750` (=790×2.5) composited **1:1** too. SAME scheme: device-res buffer, 1:1
     composite. The 333×392 buffer seen in the boxparams trace was the frame thunk's `g_frame_buf` scratch
     (`0x8537f18`), an intermediate — NOT the window.
  3. **So the banding is NOT a whole-buffer upscale.** The only sub-device-res step left is OUR frame thunk:
     it renders the frame SMALL into g_frame_buf then `thunk_frame_enlarge` StretchBlt's ×g/16 into the 835
     window. PRIME SUSPECT = that enlarge stretching g_frame_buf's INTERIOR into the window backdrop (matches
     the action-item wording "the StretchBlt resamples the inner-frame REGION"). NEXT = dump the 835 WINDOW
     buffer interior (and g_frame_buf interior) to confirm exactly what's banded; fix likely = enlarge blits
     strokes-only / keys out the interior (see [[project-smac-frame-strip-key]]: hollow frame → key 9), so the
     window's own device-res backdrop shows through un-stretched. **v10 (e7195da0) remains the shipped state.**
  (Stale earlier lines below about "mode-7 fill" / "reproduce a translucent fill at device density" are the
  pre-trace guess, kept only for history — the trace above supersedes them.)
  (color/pattern/over-what) first. See [[feedback-dither-no-resample-on-upscale]], [[project-smac-faction-dither-layer]].

Build progression this pass: 64a13505 → (P3c frames v1..v6 title concentric, bilinear outer) → 7ced3dea →
df81e1b3 (row double-scale) → 3170eacb (v9 bad right-push) → **e7195da0 (v10 inner exact-fill)**.

**STATUS: DONE + LOCKED 2026-06-29 — RELEASE MD5 `64a13505` (user-confirmed in-game @4K; non-4K
1600/1920 + 1024 native no-op spot-check still RECOMMENDED but design is g-derived so it should hold).**
All 4 phases shipped: P1 filedlg_geometry, P2a filedlg_fonts, P3a filedlg_buttons, P3b filedlg_rows.
CHANGELOG'd, 148 sites/2 caves, all pytest green, symbols in terranx.h + applied to Ghidra.
**P3b (rows/icons/text) final fix:** the file list is the GENERIC engine `ListBox_draw_item` (0x60b530);
row rowH = Dialog[+0x68](line-height=16), pitch = [+0x68]+[+0x44](gap=6), text-x indent = Dialog[+0x34].
The engine sets these from the NATIVE font at init, BEFORE FileDlg_layout swaps in the scaled font, so
they stayed native while text/icons scaled (rows bunched, icons clipped, "auto" drawn under the icon).
The Dialog sub-object sits at ListBox + the vtable adjustor [[ecx]+8] (=0xA60). FIX = `thunk_filedlg_listpitch`
(pcave2 0x26C0, 90B; entry-detour @0x60b530 via push/ret): gate `g_filedlg_active` (file dialog only —
every other list byte-identical) + g>16; idempotent (skip once [+0x68]>=0x20); scale [+0x68]/[+0x44]/[+0x34]
x g/16; replay displaced prologue (mov eax,[esp+4]; sub esp,0x28); push 0x60b537; ret. ICONS (16x16 jackal.pcx,
file/drive/folder) REUSE `thunk_checkbox_scale` on FileDlg_draw_row_icon (0x614c50)'s 3 Sprite_draw_2 calls
(0x614cc8/d24/d7e) -> num/den 1,1 -> g,16 + 16px-based Y nudge (icons are 16px so the nudge is exact).
GOTCHA proven: the build_widgets [+0x28a0] store (my first row-pitch guess, thunk_filedlg_rowh) is a DEAD
field — scaling it did nothing; the visible pitch is the Dialog[+0x68]/[+0x44] path above. Verify-first
discipline (Frida live-write experiment hook_loaddlg_rowexp.js confirmed the exact fields before baking).
Everything below is the chronological build log.


**Root cause (static RE, two static passes):** the picker is a BESPOKE custom modal — it does NOT use
the BasePop/Dialog_dims_dispatch pipeline. Its widget builder `FileDlg_build_widgets`
(0x6139b0) HARD-SETS the engine scale globals `SCALE_NUM_G`/`SCALE_DEN_G` (0x696d18/0x696d1c,
PRACX piDestScale/piSourceScale) to **1:1**, forcing native scale on every sprite/list/button
blit (those go through Sprite_blit_scaled_core which reads those globals). That 1:1 clamp is the
primary lever.

**Builder chain (symbols recorded in terranx.h):** load_game 0x5AAAB0 / save_game 0x5A9EB0 →
FileDlg_ctor 0x407350 → **FileDlg_layout 0x407410** (all hardcoded geometry; builds a 17-dword
rect array) → **FileDlg_build_widgets 0x6139b0** (copies rects→0x9b8fd0; the SCALE 1:1 clamp;
OK/CANCEL/edit/Dialog_init_3 list) → FileDlg_{load,save}_title 0x407a80/0x407920 (find_font(0xE,1)
14px caption) → FileDlg_{load,save}_modal 0x613f60/0x613d50 (FindFirstFile populate; result @+0x638,
300=cancelled). Two geometry paths in FileDlg_layout: A=main-menu, B=in-game (branch on
FUN_005f7e90 window-visible test) — confirm which via trace. Static Path-A vanilla rects
(window-local): list {14,42,319,330}, edit {17,332,317,352}, OK {19,358,165,380}, CANCEL
{168,358,315,380}; window w=0x14e(334) h=393. File-list row pitch = (DAT_009b9030*3)/2.

**Fix candidates (per proportionate-scaling rule):** (a) feed `vanilla × g/16` rects into the
17-dword array in FileDlg_layout (keeps all constants in one fn — preferred), and/or (b) change
the 1:1 clamp in build_widgets to g/16. MUST confirm whether widgets honor SCALE at build time
(so flipping it scales sprites) vs needing rect math too. See [[feedback-proportionate-scaling]],
[[feedback-smac-all-resolutions]].

**Census trace RUN + confirmed (2026-06-29, 4K g=40 + 1600x1200 g=25 + in-game SAVE):** entire
chain fires as predicted. Rect array = build_widgets 3rd stack arg ([esp+c]); build_widgets is
thiscall ecx=Dialog, window=[esp+8]. Rect-array layout/values now in terranx.h (runtime-confirmed):
[0]=flags [1..4]=list [5..8]=edit [9..12]=OK [13..16]=CANCEL. Path A (main-menu LOAD)
list{14,42,319,330}; Path B (in-game SAVE) list{28,32,333,320}; element SIZES identical across
paths + across resolutions (NATIVE, no g/16). SCALE_NUM_G/DEN_G read 1/1 before AND after build at
both res — the dialog never enters our popup-scale system; it's a self-contained native window
buffer like FactionPickWin. (DAT_009b9030=0 at layout time; set later — re-read at draw if needed.)

**Fix = scale it ourselves (no popup-scale hookup).** Levers, all proportionate ×g/16:
window buffer (GraphicWin_init w/h in FileDlg_layout) + the 17-dword rect array + body/title fonts
+ list row pitch + OK/CANCEL label font + jackal.pcx folder icons + frame/title sprites.

**Prototype RUN + user-observed (2026-06-29):** window-buffer + rect-array ×g/16 levers fire
cleanly (g read LIVE per-call — g_popup_scale_num is 0 until a screen inits; gw_init gated on
caller in [0x407410,0x407a80)). BUT necessary-not-sufficient: at 4K everything else stays NATIVE —
frame images/border strokes, title text, file text, folder icons, edit caret width all tiny; and
OK/CANCEL text grew vertically OFF-SCREEN (rect scaled but button font/buffer did NOT → distortion).
Confirms the all-elements-same-factor rule: rect-scaling MUST land together with font+sprite scaling.
Same problem class as FactionPickWin (bespoke native window already scaled — mirror that mechanism).
work\scripts\hook_loaddlg_scaleproto.js.

**Draw primitives (terranx.h):** frame = Buffer_box_sprite 0x5E2DD3 (corners Sprite_draw_2 @1,1
native + native-thickness edges → needs sprite-scale). Sprite_draw_2 0x5E4B4A takes scaleNum/Den as
ARGS. title text = Buffer_write_cent_l_7 0x5DD130; list/other text = Buffer_write_multi_font_raw_l
0x5DCAE0; fonts via find_font 0x5882F0 (title find_font(0xE,1)=14px). BaseButton_init 0x607210,
BaseButton_set_def_font 0x6074B0.

**Draw-path census RUN + analyzed (2026-06-29, 4K g=40 + 1600 g=25 + in-game SAVE).** EVERY dialog
element draws at scale 1/1 with native magnitudes (each is its own lever; nothing reads a global).
Inventory (window-local; all via load_game): window buffer 334x393 composited via Buffer_draw_2
@0x5d8636 at 1/1; OUTER frame Buffer_box_sprite @0x40756c set=0x6846b0 corners 61x44; INNER frame
@0x4075ca set=0x78d528 inset12 corners 6x6; TITLE bar @0x407b19 set=0x78d618 [15,15,319,35] 20px;
title font find_font(14,1)@0x407b3a cell_h17; title text Buffer_write_cent_l_7 @0x407b9f; FOLDER
ICONS Sprite_draw_2 @0x614ccd/d83/d29 16x16(real15x13) x=4 ROW PITCH 22; FILE TEXT Buffer_write
@0x5dd000 x=25 pitch22 (body font = static, NOT find_font); OK/CANCEL bg Sprite_draw_2 @0x607f98/fcc
(3x20 caps)+@0x5dab4a(67x20 mid) 20px; OK/CANCEL text Buffer_write @0x5dd0c1; buttons are SEPARATE
child GraphicWins composited independently (146x22/147x22) via @0x5d8636. PROOF engine scales here:
background faction portrait drew scale=40/16 (4K) / 25/16 via Sprite_draw_2 @0x6688e8 — per-sprite
g/16 IS the mechanism. log = work\frida_loaddlg_drawcensus.log.

**Faction picker STUDIED (user chose this) → concrete plan written = work\filedlg_scaling_design.md.**
Faction picker is the proven template (same bespoke-native-window problem, solved crisp/per-element,
SHIPPED + MD5-locked). KEY: all hard infra already exists + reusable — scale_uniform, scale_x/y,
g_pf0/1/2 (+thunk_build_scaled_fonts/thunk_ensure_scale), thunk_keyed_stretch_blit, thunk_box_thick
family, thunk_frame_enlarge. And the file dialog goes through the SAME BaseButton_init (0x607210) and
Dialog_init_3 (0x609470) the faction thunks already hook → buttons/list scale by extending those
gates with a new g_filedlg_build_active flag. Plan = mirror faction P1(geometry: window @0x4074f6 +
buttons + list+pitch + edit) → P2(fonts→g_pf0) → P3(frames via box_thick @0x40756c/0x4075ca/0x407b19
+ icons @0x614ccd/d83/d29 via keyed_stretch_blit + caret) → P4(verify all res + native no-op). Scale
at CONSUMERS not the 17-dword array (avoid double-scale). ~8 new thunks, most faction clones.
Chosen method = B per-element crisp (A composite-zoom rejected: blocky + separate child composites).

**PHASE 1 (geometry) BUILT + APPLIED + statically verified (2026-06-29) — PENDING in-game sign-off.**
group `filedlg_geometry` in patches.yaml (2 sites, pcave2 gap 0x2320). Two thunks (asm ports of the
validated Frida prototype): thunk_filedlg_graphicwin (pcave2 0x2320, 64B) call-redirect @0x4074f1 —
scales window GraphicWin_init w/h x popup_scale + recenters x/y on original center; thunk_filedlg_rects
(pcave2 0x2360, 48B) call-redirect @0x40771b — scales the 17-dword rect array [1..16] in place (skip
[0]=flags) so Dialog_init_3 list + edit GraphicWin + OK/CANCEL BaseButtons get scaled rects (no shared-
thunk edit, no build flag needed — file dialog has its own builder, unlike faction). Scale at consumers/
array, NOT both → no double-scale. Gate SW>0x400 (1024 = native no-op). Dry-run clean; applied to FULL
set → live MD5 now **fae4080e** (was 0b81d7a8; INTERMEDIATE, NOT locked). Capstone-verified: jle native
tail-jmps land exactly, loop esi=1..16, popup_scale@0x668750. EXPECTED P1 look: big centered window +
big buttons/list/edit, hit-test aligned; but NATIVE frame in top-left corner + tiny text/icons + rows
bunched (P2 fonts / P3 frames+icons+pitch+caret fix those). Regression tests will MD5-fail until re-lock
(do NOT re-lock / CHANGELOG until user confirms in-game @4K + non-4K + 1024 no-op). Pristine base =
terranx_PRACX.exe.bak (2d0b1438); restore+apply via apply_patches.py --restore then --apply.

**P1 POSITION FIX + 4K VERIFIED (2026-06-29):** first 4K test = dialog off-screen bottom — recenter-on-
original-center pushed it off (native window sits LOW y~1545/2160). Fixed: graphicwin now SCREEN-centers
(x=(ScreenWidth-new_w)/2, y=(ScreenHeight-new_h)/2; ScreenHeight=0x9b7b20). graphicwin grew 64->72B,
rects moved 0x2360->0x2370. Re-applied, live MD5 now **3a6025ef** (intermediate). Capstone re-verified.
4K screenshot CONFIRMED: window 835x982 centered (exact vanilla x2.5), buttons/list/edit scaled, frame+
title bar SPAN the full window (frame rect derives from scaled buffer dims -> scaled free; P3 only needs
stroke THICKNESS). Expected-pending: tiny text (P2), hairline frame strokes + tiny icons + bunched rows/
native pitch (P3). STILL TODO before lock: 1024x768 native no-op spot-check + one non-4K res. P2 fonts.

**PHASE 2a (fonts) BUILT + APPLIED + capstone-verified (2026-06-29) — PENDING in-game test.** Native
font cells Frida-measured (hook_loaddlg_fonts.js): body DAT_007cfeb4 cell15(nom12), title find_font(14)
cell17, g_popup_title_font cell16, button *DAT_009b8e34 cell15 (NULL at main-menu LOAD, 15 in-game).
group `filedlg_fonts` (4 sites), pcave2 grown 0x2600->0x2700. 3 thunks: thunk_filedlg_titlefont (0x2600,
31B) call-redirect @find_font in load/save title (0x407b35/0x4079d5) scales size arg x popup_scale;
thunk_filedlg_dlgfont (0x2620, 49B) @0x407737 Dialog_set_dialog_font(&DAT_007cfeb4)->swap to
find_font(popup_scale(12),0) [push ecx/find_font/pop ecx/swap esp+4]; thunk_filedlg_editfont (0x2660,
49B) @0x407813 Buffer_set_font(&DAT_007cfeb4) same. DAT_007cfeb4 has ONLY these 2 consumers (file-dlg-
exclusive body font). live MD5 now **624f9e9a** (intermediate). EXPECTED after 2a: title + file-list
rows + edit text scaled ~g/16. STILL tiny -> Phase 2b: OK/CANCEL labels (DAT_009b8e34 global btnfont,
needs save/restore + handle null@main-menu) + 2 sub-widget labels (g_popup_title_font, the Host/Local
ID @0x407893+). P3: frame stroke thickness, folder icons (Sprite_draw_2 @0x614ccd/d83/d29 -> keyed_
stretch_blit), list row pitch (rows bunched), edit caret. Font sites: dlgfont/editfont/titlefont VAs +
original bytes in patches.yaml group filedlg_fonts.

**PHASE 3a (BUTTON BARS) BUILT + APPLIED + capstone-verified (2026-06-29) — PENDING in-game test.**
User 4K test after 2a: "buttons all getting cut off" + folder/drive icon (top-left) not scaled. Frida
buttongeo trace (hook_loaddlg_buttongeo.js) PROVED geometry is CORRECT: OK pos(47,895) size 365x55,
CANCEL pos(420,895) 367x55, both well inside the 982-tall window → NOT clipped. The "cut off" = the
FlatButton 9-slice BAR art rendered NATIVE-tiny (sliver at top of the scaled 55px slot), same as the
faction buttons before commit 3a. Root: file dialog is bespoke (not BasePop) so the existing FlatButton
bar 2D-zoom (popup_button_2dzoom thunks) never fired. FIX = mirror faction's g_faction_active: new
`g_filedlg_active` flag (pcave2 0x23A0) bracketed around the modal loop via 2 call-redirect wrappers
thunk_filedlg_modal_load (0x23B0, @0x407bbf→FileDlg_load_modal 0x613f60) / thunk_filedlg_modal_save
(0x23E0, @0x407a5f→FileDlg_save_modal 0x613d50), each: mov[flag]1;call modal;mov[flag]0;ret (preserves
ecx/eax). Then thunk_btn_gate (pcave2 0x12E0) REWRITTEN to OR in g_filedlg_active (label-gated like
faction; popup/faction outcomes byte-identical; fits 48B slot). group `filedlg_buttons` (2 sites). live
MD5 now **2fa8e855** (intermediate). EXPECTED after 3a: OK/CANCEL bars fill their 365x55 slots (proper
big buttons); LABELS still native-tiny (Phase 2b). Folder/drive icon still tiny (Phase 3 icons).
DEFERRED 2b: OK/CANCEL label font (DAT_009b8e34, NULL@main-menu) + 2 sub-widget labels. P3: folder icons
(Sprite_draw_2 @0x614ccd/d83/d29 → keyed_stretch_blit), frame stroke thickness, list row pitch, caret.

**3a BUG #1 (boot crash) = the FRIDA PROBE, not the patch.** First btnzoom hook attached at 0x607e85 (a
MID-function resume point on FlatButton_content_draw, the hottest draw path) → Frida crash on boot.
Patched binary boots + runs fine (user-confirmed normal launch). LESSON: diagnostic hooks on hot draw
paths MUST attach at a clean function ENTRY (0x607e50), never a mid-function jump-target.

**3a BUG #2 (bars still thin after first apply) = flag set TOO LATE.** Frida (hook_loaddlg_btngate.js,
by-dims+backtrace) PROVED: OK/CANCEL DO go through FlatButton_content_draw (0x607e50), the gate IS
called, label[+0xa7c]!=0, designW/H[+0x4c4/0x4c8]=365/-55 (scaled) — ALL gate inputs correct EXCEPT the
bars PAINT during build_widgets (bt 0x613ab1) + layout (bt 0x4078a3), which run BEFORE the modal call.
g_filedlg_active (set only around the modal) was 0 at paint → gate RET=0 → no zoom. FIX = also set the
flag at FileDlg_layout ENTRY (thunk_filedlg_setflag, pcave2 0x26A0; detour @0x407410 replaces the 10-byte
SEH prologue push ebp/mov ebp,esp/push -1/push 0x650c6b, sets flag=1, replays, jmp 0x40741a). Flag now
set layout-entry → modal-end (covers build paints + modal repaints); modal wrappers clear it. NOTE
buttons DON'T repaint during the modal unless hovered (gate hook saw 0 redraws idle). live MD5 now
**7578b5e6** (intermediate). LEAK edge: build-failure (no modal) leaves flag=1 until next dialog open —
accepted (near-impossible). PENDING in-game test: do the bars now fill their 365x55 slots?

**(earlier fork, now resolved → B):** A=uniform composite zoom (intercept the window+child
composites @0x5d8636, upscale g/16 + reposition; fewest levers but NN-blocky text, must coordinate
separate child composites); B=per-element crisp (mirror FactionPickWin: scale window buffer+rects +
re-render fonts at g/16 + scale frame/icon/button sprites g/16 + row pitch + caret; ~10-13 levers,
crisp, matches project standards). Recommend B.

**(superseded) NEXT (user chose: trace draw paths first):** draw-path census built =
work\scripts\hook_loaddlg_drawcensus.js (gated to picker via load_game/save_game anchor; logs every
sprite blit + its scale arg, box-sprite frames, title/list text, find_font sizes). Pure diagnostic
(no mutation). Shortcuts point here (append mode). Run 4K + 1600 + in-game SAVE; read
work\frida_loaddlg_drawcensus.log. Census hook at work\scripts\hook_loaddlg_census.js. Scratch
decompiles: work\scratch_filedlg.txt / scratch_filebox.txt / scratch_builder.txt / scratch_modal.txt.

**2026-09-26o/p (live 7d70796b, AWAITING verify):** (o) window placement: vanilla FileDlg_layout in-game y = SH - g_console_strip_height - 0x191 (bottom ON the console top), x = (SW-0x13c)/2 - 0x17 (visible part centred); graphicwin v2 scales those offsets (law filedlg_window_origin) -- v1 screen-centring hid OK/CANCEL under the HUD below 4K. (p) list SCROLLBAR never appeared at g>16: the populate's calc_dims counted rows with the native stride (listpitch scales at first DRAW); thunk_lbcalc_scale v4 now also fires under g_filedlg_active. The bar is FileDlg+0x3DD8, created by FileDlg_sb_create 0x407E80 (vtbl+0x20) and placed by rail_slide_in exactly like popup_sb_create -> FileDlg admitted to the rail family (rail_gate v4, railout_hstep v3), btn_gate v10 NO exit -> thunk_rail_sbarrows for hover. List style 0x40 skips calc_dims' g_scrollbar_w reserve (bar lives in the rail, not the list).
