---
name: project-smac-tech-breakthrough
description: TECH BREAKTHROUGH window ("OUR RESEARCHERS HAVE MADE A BREAKTHROUGH") scaling arc — BAKED 2026-09-19 as ntw_scale; v1 user-shot + MEASURED on law at 4K/1600/1920/1024; v3 user-confirmed (wheel/buttons/captions) on 5e677e32; LIVE exe 5c095931 + uimod.dll 367eb124 (adds the vanilla text-box top-anchor fix in the DLL + the shared ornate band map) AWAITING verify; window = Thinker NetTechWin 0x811E40 (NOT multiplayer-only; was mislabelled 'NetWin CHAT page')
type: project
---

**CLOSED 2026-09-19: commits 5b58698 (exe 7d407602) + ce1e5e3 (uimod.dll aab42857); USER-VERIFIED 4K + 1600 (measured: 44/44 inner-frame edges on the law, icon buttons clean, Datalinks round-trip keeps the scale, description opens at line 1); 1920 not seen on this build.** Earlier status: **2026-09-19e: LIVE exe 5c095931 + uimod.dll 367eb124, UNCOMMITTED.** User confirmed v3 ("you've solved the problem": wheel only with a shown bar). v1 (14d7284d) was shot at 4K/1600/1920/1024 and measured: every frame + the OK ring 0 px off `ntw_layout` with stroke K, name/icon within 1.5 px of vanilla x g/16, dither uniform.
No Frida proto was run for this arc (user asked to implement directly) — the first in-game look IS the bake. Verify list
lives in the maintainer's work log (Live state, top entry).

**Identity (cost a detour):** the single-player breakthrough popup is Thinker's `NetTechWin` 0x811E40 — `tech_achieved`
0x5BB000 calls `NetTechWin_exec` 0x483F90 @0x5BBA22 (the `[0x93F660]` branch picks the MP popup 0x805338 instead). Our
notes had 0x483F90/0x483950 as a deferred "NetWin CHAT page" (the maintainer's work log + terranx.h `NetWin_chat_draw` + a
patches.yaml comment) — all corrected. Symbols: terranx.h "TECH BREAKTHROUGH window" section. Decompile
`work\_ntw_dec_core.txt`. Pristine ref `refs\pristine\TechBreakthrough.png` (1024x768 pillarboxed at 2.8125x).

**Engine shape:** fixed 550x600 GraphicWin; the builder derives 17 RECTs (+0xA14..+0xB20) from the window rect by additive
immediates and stores ALL of them in the object BEFORE `GraphicWin_init_2` @0x4842E7; everything later (TextScroll_attach,
BaseButton_init, the painter) only READS the fields. So one call-site lever (`t_ntw_build` -> `t_ntw_rects`) re-runs
vanilla's cascade at device density — no imm table, no VirtualProtect, no imm8 overflow cuts (0x4C and -0x41 would
overflow at 4K). Law `scaling_laws.ntw_layout`: every constant s(c), compound immediates split into measured parts
(0x0F = 12+3, 0x2A = 12+3+20+3+4) so the 3 px frame pitch is one value; the quote box takes the remainder exactly where
vanilla's top-down and bottom-up cascades meet. The parity test emulates the PRISTINE builder prefix and asserts it equals
`ntw_layout(16)` — the g=16 identity is vanilla's bytes, not my transcription.

**Reusable findings:**
- Button dims that reach the 2D zoom must be FLOOR-scaled: `thunk_tutbtn_post` recovers native by CEIL
  ([[feedback-floor-descale-roundtrip]]); a half-down dim (s(28)=44 @g25) ceils to 29 and clips fixed art.
- The button gate chain head is whatever `thunk_btn_shrink`'s E8 points at: now `t_ntw_gate` -> `t_mon_gate` ->
  `thunk_btn_gate_pre` -> `thunk_btn_gate`. Unlabelled FlatButtons need a static admit; labelled ones pass under
  `g_netwin_active`.
- patches.yaml cave templates: `{rel32:}` is CALL-only; inter-thunk tail jumps must be `push abs32; ret` (`68 {abs32:x} C3`).
- An ORNATE 0x6846B0 backdrop must go through `thunk_tutwin_backdrop` (devfill + `thunk_hollow_keyint`), never plain
  devfill — devfill's STEP2 insets only the stroke width and would tile over the 8-9 px metal band.
- The builder is MODAL and loops through Datalinks (`call [edx+0xE4]` @0x48478D); DL's leave writes
  `g_netwin_active := 0` (absolute writer), so `t_ntw_modal` re-arms around every modal pass
  ([[feedback-modal-builder-hook-before-set-modal]], [[feedback-gate-flag-refcount]]).
- Icon: `Sprite_draw_mono_scaled(…, num 160, den 215)`; scaled num = 10g; an enlarge (num > den) emits idx 0x0F not the
  mono colour (the DL `t_dl_mono` finding) -> `t_ntw_icon` recolours 0x0F -> the `col` arg inside the icon area. It reads
  the painter's own locals through the caller's ebp.

**v1 -> v2 lessons (measured, 2026-09-19):**
- The window's vtbl is **0x66CE5C** (found by searching .rdata for the painter pointer). 0x66ADC8, which sits in the
  window's dtor, is the embedded TextScroll's vtbl — I mis-recorded it once; uimod wheel.cpp and the dw wheel thunk key
  on these values.
- Caption nudge: WRONG here. `(g-16)>>3` put the 5 slot-centred captions 3-4 px high at 4K; un-nudged ink is within
  1.5 px of vanilla x g/16. The popup-title nudge ([[feedback-scaled-text-centering]]) is not a property of
  `Buffer_write_cent_l_7` — measure each screen (law comment `NTW_CAPTION_NUDGE`).
- "Garbled colours" on the quote / description icon buttons = `thunk_fe_pair_remap` (reached through
  `thunk_btn_2dscale` -> ringfix -> stripes) restriping APERIODIC pixel art whose purple members collide with the
  E0/E1 family ([[feedback-dither-pair-ambiguity]]). Fix = a chain head on 2dscale's post-zoom E8 (`t_ntw_nostripe`)
  that returns for those two statics. Fixed-art sprite buttons admitted to the 2D zoom need this bypass.
- Wheel: three pieces must agree — uimod `kScrollable` (posts the arrows while the map shows), the WinProc wheel chain
  head (`t_ntw_wheel_*` -> `t_rw_*` -> `t_dl_*` -> dw), and the window's TextScroll offsets (quote +0xDC24, lists
  +0x2DA4 stride 0x2BA0, bar at TS+0xA20, visible = TS+0x9C bit0).
- Wheel v2 -> v3 (user report): a ScrollBar's range (`bar+0xA24 > bar+0xA20`) and `bar+0xC4` stay live while the bar is
  HIDDEN, so v2 scrolled the quote box with no bar on screen. The shown test is the BAR Win's own `+0x9C` bit0
  (= TextScroll+0xABC, the bit TextScroll_draw 0x629BA1 / TextScroll_finish 0x62963C read to reserve the bar width).
  The DL wheel arm tests the TextScroll's +0x9C only — same latent gap there if a DL page ever hides its bar.
- VANILLA BUG fixed in uimod (techwin.cpp, DLL 367eb124, both exes): TextScroll is the engine's CHAT-LOG widget —
  TextScroll_finish 0x629490 parks an overflowing text on its LAST page (walks back from the end, ScrollBar_set_pos,
  first_line := bar pos). The long tech description opened half-way down (user report, also on pristine). Fix = 3
  byte-checked E8 retargets (finish @0x48454D + @0x483F7F, help_tech_info @0x484447 for the 4 unlock lists): run the
  original, then set_pos(0) / first_line := pos / vtbl+0xF8 when the bar is shown. UNVERIFIED in-game as of writing.
- The ornate-border findings became their own arc: [[project-smac-ornate-bandmap]].
- Screenshot tool quirk: the 1600x1200 shortcut produced a 1600x2160 PNG (game in the top 1200 rows) — use the game
  height, not the image height, when locating a centred window.
- Measure scripts: scratch files only (measure.py / measure2.py: green-dominance stroke runs per edge, ink bbox vs
  the native shot x g/16, run-length histogram for the dither).
