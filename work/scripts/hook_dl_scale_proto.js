// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// Datalinks (DatalinkWin 0x703EA0) scaling PROTOTYPE v12 — Frida.
// Facts: work\_dl_static_map.md, _dl_source_map.md, _dl_pixel_geometry.md, frida_dl_geom.log (4K run
// 2026-08-30: window born 832x206 @ (1520,1422) = h 738-532 starved, every seed native).
//
// MILESTONE 1 (this file): the OUTER MODAL scaled + centred so the whole screen is reachable —
// window, every rect seed, the 18 button rects, the 11 font sizes, the TextScroll insets.
// Chrome weight / dither density / art / scrollbar width are NOT addressed yet (frames compose
// native 1px at scaled rects; that is the next step, DW-frame port).
//
// LEVER: one-time Memory.patchCode of the builder's immediates at DatalinkWin_build ENTRY
// (0x429300 runs ONCE at system_init, g is already known there: log line 7). The builder then
// produces scaled tables itself, so GraphicWin_init / BaseButton_init / Dialog_init_6 /
// TextScroll_attach all receive scaled geometry — no post-hoc rect surgery, no calls into
// baked-detour families. Law per site = SL.scalePx(v, g) (= vanilla x g/16; scaling_laws.js):
//   W  window: h imm 0x2E2 -> s(738) (h = s(738) - strip_dev, DW's `600 - strip` law, 1024 twin);
//      w 0x340 -> s(832); x: (SW - s(800))/2 (imm -800 -> -s(800)); ofs base 0x8A -> s(138).
//   R  seeds: list_title/list_box/art_box/title_rect/text_upper/text_lower literals, +9 title L,
//      ±3 container insets, d690 backdrop {0x17,0,0x309,h}, BACK/EXIT {0x98,0x14E,0x18E}/{0x192,0x288}
//      h 0x14, gap via 0x192-0x18E.
//   B  wing rows: x ±4 -> s(4); bottom inset (B-4)+1 = B-3 -> B-(s(3)+1)+1; top = bottom - 21
//      -> -(s(25)-s(3)-1) so face h = s(25)-s(3) = s(22) exactly; pitch 0x18 -> s(24) (8-row
//      remainder drift at g=25 is a known follow-up: cum(i)=halfDown(i*total,n), bake-time).
//   F  fonts: the 11 Font_init size pushes of the 1024 branch (14/18/12) -> s(size).
//   T  TextScroll attach insets 3/3/6 -> s(). Console centre seed is already scaled (HUD arc).
//   v2: BACK/EXIT faces — the popup "default chrome" FlatButton painter paints a FIXED 20-row native
//      face (1600 shot 214607: 20 face rows inside the 31-row rect, rest = backdrop), while the 16 wing
//      buttons stretch a box-sprite face set (+0xAC8/+0xACC/+0xAD0 = 0x78D960/88/B0) and render right.
//      Lever: give BACK/EXIT the same set after build (same face colours in the pristine refs).
//   v2: scrollbars — arm g_netwin_active (pcave2+0x4800) around build (TextScroll_attach ->
//      thunk_sb_xinset / ScrollBar_attach -> thunk_sb_width: bar = s(20)) and around exec
//      (ScrollBar_draw -> thunk_sb_thumb). The ListBox bar reads g_scrollbar_w unthunked -> still 20 (follow-up).
//   v3: PAGE PAINTERS + TECH PAGE — the per-painter immediate table from work\_dl_painter_imms.js
//      (Agent D 2026-08-29, 250 sites verified vs .bak; semantics/laws in _dl_painter_imms.md): stats-block
//      offsets, art-box centring, Caviar zoom floats (FLOAT), veh_draw size (VEH law), facility/project/terraform
//      blit num/den (g:16), society tables, the 16 builders' title-band inset, ReportWin_tech_page Datalinks
//      branch + hover + connector helper. 6 imm8 sites overflow at g=40 (terraform +75/+100/+103 x2, tech
//      52/58) — the guard SKIPS them (stay native; bake needs a cave). Faction portrait kept 1:1 (its text x
//      adds the native sprite width — cave lever). RAW patches: render_topic restore rect disp32 0x103C4->0x474
//      (canvas space; the mixed-space vanilla accident), tech card fonts A1 [0x8A40D4]/[0x8A40C8] -> B8 &DL.F0/&DL.F4.
//   v4: the 6 imm8-overflow sites (terraform diamond +75/+100, stats/lower text +103 x2; tech icon centring
//      52, y-advance 58) are fixed by REGISTER fix-ups at the instruction (Interceptor.attach with a 5-byte
//      window audited for branch targets vs the terraform jump table 0x431D54 and every jcc in the two painters:
//      none inside), removed from the imm table so they apply identically at every g.
//   v4: tech page buttons — ReportWin_tech_page centres its prerequisite/leads-to button column on ReportWin's
//      OWN text-area bottom [RW+0x5980] and its font line height [RW+0xE268] (both native, non-immediate):
//      at 4K the column spread over the whole panel (shots 221832). Bracket at 0x498B30: while DatalinkWin
//      is executing, save both, write s(native), restore on leave; values logged for the exact law.
//   v5 (user shots 222736/222748/222946): (a) tech prereq/leads-to button LABELS used BaseWin's shared native
//      font 0x6E84B4 (6x `push 0x6E84B4` before Buffer_set_font) -> DL F3 (0x714094, 14b scaled; v5-v8 pushed 0x7140F4 = garbage). (b) connector
//      CHEVRONS = arrow sprites (table 0x75AFD8) via Sprite_blit_scaled_core, which scales by SCALE_NUM_G/DEN_G
//      (0x696D18/1C, normally 1:1): set (g,16) at each of the 5 call sites in FUN_0049B450 and restore at call+5
//      (windows audited: no branch targets inside). (c) tech ICON colour: FUN_005E3E00 = SCALE swap +
//      Sprite_draw_mono_2; its SCALED path is not mono (draws the sprite's own colours: tan DNA) -> snapshot the
//      dest rect before, and after the draw set every changed pixel to the mono colour arg ([esp+0x14]).
//      (d) hover: instrument ReportWin_tech_hover(id, flag) + every FUN_0049B450 call (args + RW column/row
//      fields) to pin why hovering a leads-to button drew the prereq bracket.
//   v6 (CRASH opening Datalinks straight onto a tech, 4K log 05:41): the first draw_page runs inside
//      DatalinkWin_exec BEFORE the iface mode is registered (mode 8 is set at show), so ReportWin_tech_page took
//      its REPORTWIN branch (card 0xBE wide, buttons parented to 0x876478) with the shared-tail immediates live
//      -> AV in BaseButton_init. Two fixes: (1) while DatalinkWin executes, force g_iface_mode_table[idx] = 8
//      around every ReportWin_tech_page call (restored after) — the DL branch is the only correct one inside the
//      modal, vanilla's pre-show paint was a harmless glitch; (2) every patch in the ReportWin range
//      (0x496BB0..0x49BD00 + the 8 raw font swaps) is now EXEC-SCOPED: applied at DatalinkWin_exec enter,
//      reverted to the native bytes at exec leave, so the real F-key report screen is never touched. The two
//      tech REGFIX sites, the arrow SCALE bracket and the mono recolour are gated on inExec as well.
//   v7: CRASH #2 (v6 log, DL branch): same AV in BaseButton_init right after the first connector arrow blit —
//      v4 ran the identical sequence at 1:1 without fault. The arrow SCALE bracket (SCALE_NUM/DEN=(g,16) into
//      Sprite_blit_scaled_core = the HUD-arc push;ret chain head) is DISABLED; chevrons stay 1:1 until they go
//      through the proven keyed-stretch primitive (thunk_keyed_stretch_blit) at bake.
//   v8 (v7 log + shots 224835/224938): (a) ICON colour = VANILLA BUG: the colour arg is
//      mandate_color(tech_category(tech)) = a packed RGB (0x02EF1A0F = Discover blue) but Sprite_draw_mono_2
//      takes the low byte as a PALETTE INDEX -> palette[15] (tan in-game, grey-cyan in the pristine capture).
//      The draw IS mono (one colour in the shot). v8 recolours the icon with the palette index nearest the
//      intended mandate RGB; the snapshot is sized from num (the sprite dims are lazy-loaded inside the draw:
//      w/h read 0 at entry, den=215 = source width, vanilla always draws it shrunk 50/215).
//      (b) chevron sprites are still 1:1 (arrow SCALE bracket disabled) -> their anchor offsets (-10/-6/-7)
//      go back to NATIVE so the native arrow sits on the bar end; scale both together at bake.
//      (c) hover: the engine passes (cardL, y, btnL, btnT) for a leads-to hover = reversed vs the page paint ->
//      the helper takes its prereq branch (left bracket). Same at native; verify on the 1024x768 shortcut.
//   v9 (shots 225653/225732 + 1024 vanilla run): (a) HOVER flip was MINE: 0x49B299 `mov eax,3` is the
//      button-INDEX compare (`cmp ecx,eax; jge` = k<3 -> prereq branch), not a frame inset; S(3) made k=3,4 take
//      the prereq branch (args reversed -> left bracket). Row removed. Vanilla 1024 passes (btn, card) correctly.
//      (b) LABEL FONT: F3 = 0x71401C + 3*0x28 = 0x714094, NOT 0x7140F4 (= F5+0x10: a garbage "font" whose +8
//      HFONT is F5.ascent -> SelectObject fails -> GDI default face, cap 12 at BOTH 1600 and 4K; pristine cap 10
//      @1024). Wing buttons use +0x101F4 == F3 (0x714094) and scale correctly at 4K. Fixed the 6 push sites.
//      (c) CHEVRONS: JS scaled draw at the 5 Sprite_blit_scaled_core sites — snapshot the dest rect at the call,
//      restore it at call+5 (erases the engine's 1:1 arrow), then NN-enlarge the sprite (pcBits +4, key +8,
//      pitch +0xC, w/h +0x10/+0x14, L/T +0x20/+0x24) to s(w) x s(h) at (x+s(L), y+s(T)); centre-aligned NN.
//      The 16 anchor-offset rows are scaled again. Bake = thunk_keyed_stretch_blit.
//      (d) ICON: target colour = the index the engine just drew "DISCOVER 1"/category text in (sampled from the
//      canvas above the icon, most common non-backdrop index); pristine icon == that text colour (173,196,192).
//      Fallback nearest-palette to (173,196,192). Palette dumped once + histogram of the native-drawn indices.
//   v10 (v9 CRASH, same AV as v5/v6: BaseButton_init `call [eax+0x168]` with this=edi right after the
//      connector returned, first arrow draw at 4K): the common factor of every crashing build is the ATTACH on the
//      Sprite_blit_scaled_core `call` (relocated call -> trampoline return address into the HUD-chain push;ret
//      detour) and on the call+5 slot (= the connector's `pop edi; pop esi; pop ebx` epilogue). Both gone:
//      snapshot at the `xor r,r; mov rl,[sprite+8]` pair before the pushes (5-byte window, no branch target
//      inside; the alt paths of sites 3-5 hook their `lea eax,[eax*4+0x75AFD0]`), redraw in FUN_0049B450's
//      onLeave (function-entry attach, already proven clean).
//   v11 FRAME PASS (user shots 231809/231841 measured vs prinat_Tech): every frame stroke on the screen was
//      1px at 1600 and 4K (pristine 1px @1024 -> K = strokeWidth(g) = 2 @g25/g40); the d690 ring's 3px bevel
//      collapsed to 1px; positions were already exact. (a) 25 DL + 11 tech/hover Buffer_box_sprite E8s ->
//      the baked band-map renderers (SE v18 / DW D4 recipe): hollow d5a0/d528/d5f0 -> thunk_box_thick_hollow_flat
//      through DW's R-1/B-1 rect stub (the thunk band-maps an INCLUSIVE footprint, the DL rects are half-open),
//      filled d618 title bands + the builder's d690 backdrop -> thunk_box_thick_devfill. The draw_page d690
//      @0x42C020 (mixed-space rect, clip = content_union -> only its fill shows) and the 10 CLIP-gated bracket
//      draws (tech page 0x4991C8/0x499253/0x499328/0x4993EC, connector x6) stay native: the enlarge is not
//      clip-aware. RW-range sites are exec-scoped like every other ReportWin patch.
//      (b) The canvas backdrop dither (pair 196 (13,23,36) / 65 black, NOT in the baked remap table) is
//      restriped at the P law: whole canvas at BUILD leave, content_union at 0x42C05C (after the three
//      draw_page frames, before the page painter -> art/text never touched). Per-draw pair detection.
//      (c) Hover doubled bottom/right frame line: `mov eax,3` @0x49B299 feeds BOTH the k<3 compare and the
//      frame's R/B +3 (`add edx,eax` / `add ebx,eax` @0x49B2F1/F6) -> REGFIX eax = s(3) at the 0x49B2DE join
//      (after the compare). The v9 row removal stays.
//   v12 — ROOT CAUSE of the v11 "opening Datalinks" crash (12 diagnostic runs, hardware watchpoints on the tech
//      page's saved-register slots): frida-agent code wrote a TRAMPOLINE ADDRESS (0x2eexxxx) into the tech page's
//      saved-EDI stack slot the moment a hook fired with esp == &saved_edi (no outstanding pushes), so the
//      epilogue's `pop edi` handed the caller a bogus `this` -> draw_page #3 with ecx = garbage -> Spot_init
//      free(garbage) -> ntdll AV. Two v11 attaches sat exactly at such points: 0x42C05C (draw_page, right after
//      the three frames) and 0x49B2DE (hover join). The frame thunks were never guilty (the bisect kept the
//      0x42C05C attach in every run). NEW HAZARD CLASS for feedback-frida-attach-branch-target: never attach at an
//      instruction where [esp] is a live callee-saved register (function frame top with no pushes outstanding).
//      Fixes: content restripe moved to the page PAINTERS' entries (14 DL painters + the tech page entry — clean
//      function entries); hover R/B +3 done with a byte patch: `add edx,eax; add ecx,-3; add ebx,eax` (7 B
//      @0x49B2F1) -> `call stub; nop; nop`, stub = add edx,s3 / add ecx,-s3 / add ebx,s3 / ret (P row 0x49B2F3
//      folded in). Frames (hollow_flat + devfill) and both restripes back ON.
//   v12i — (1) HUD CLOSE RESIDUE (user 1600 shot 115026: the DL console quote box's 65/198 dither survives over
//      the console ledge, x 916..1195 y 1066..1093): the DIPLO EXIT-RESIDUE class exactly — MainWin_tile_panels
//      0x45C290 restores console art positionally from the NATIVE 1024-wide art object, so at g>16 its output is
//      wrong AND clamped; the baked save-under (t_cr_snap/t_cr_tile, diplo_talk_scale) arms only on the DIPLO
//      iface vtbl. Fix (proto): the same JS save-under as hook_tile_restore_proto v5 — snapshot the inter-panel
//      gap band of the MainWin strip canvas at DatalinkIface_on_mode(enter=1) BEFORE the DL console paints,
//      restore it after every big==0 tile_panels + soft_update. Bake will be a t_cr_snap twin on iface vtbl
//      0x66AF30 slot 0.
//      (2) HOVER BRIGHT-SPINE OVERSHOOT (user 1600 shot 114911, Gene Splicing: hovering the bottom leads-to
//      button leaves a d5f0 spine at canvas x935 down to the BUTTON BOTTOM y443, 31px past the bracket's B=412;
//      un-hover repaints only clip-deep -> residue): no static candidate draws there — TRACE it: [HC] cap 10->80
//      with the params-set VA per draw, TECH_HOVER cap 12->40 + the hovered button's rect, CONNECTOR cap 16->48,
//      ARROW cap 10->48.
//   v12j — CHEVRON TIP vs STEM (user 1600 shot 121417, confirmed by pixel map: bracket bottom-edge stem at
//      screen 409-410, chevron tip at 412-413): the arrow anchors at the rect's true B (tip = B_incl-1..B_incl,
//      canvas 365-366 = vanilla law) but the thick render is TL-anchored and floor-quantizes its output SHORT
//      (~3 px at g=25: 1 from the R-1/B-1 inclusive conversion + 2 from the small*16/g -> *g/16 double floor),
//      so every BOTTOM edge lands high; top edges are flush — why only lower chevrons misalign. This is the
//      skill scaling-frames §5 exact-fill case, and the bake already carries the lever: thunk_frame_enlarge
//      reads g_fc_exact (0xA0E554) + g_faction_scratch_rect (0xA0D010) and stretches to the EXACT rect W/H,
//      self-clearing. Fix: the 10 "HC" sites route through bmStubX = bmStub + (stash the ORIGINAL half-open
//      rect into g_faction_scratch_rect; g_fc_exact=1) -> bottom stroke at B-2..B-1 flush, tip-aligned.
//      Stub Unicorn-verified (emu_bmstubx.py): SR=(935,193,961,367) S=(935,193,960,366) fc=1, ecx/esp preserved.
//   v12k — CRASH on the 3rd tech at 4K (user report; log tail: [REGS] tech_page leave edi=0x2ee2a0f = a Frida
//      trampoline popped into EDI at the page epilogue, then 169 spurious [WP] hits inside trampoline code): the
//      v11/v12 CRASH-HUNT DIAGNOSTICS were still armed — hardware watchpoints re-armed on every tech_page's
//      saved-reg stack slots (never disarmed, firing on ordinary stack reuse, each hit running a JS exception
//      handler inside frida transitions), HeapValidate sweeps + CRT __sbh/free attaches on hot paths. The bug
//      they hunted was fixed in v12; now they ARE the hazard. All gated OFF (DIAG_* = false). v12j's exact-fill
//      is arithmetically a NO-OP at g=40 (2.5x exact) so it is not the 4K trigger; belt-and-braces anyway: the
//      HC wrapper now clears g_fc_exact after every hollow_flat return so the flag can never leak from a path
//      that skipped the enlarge.
// Gate: g > 16 only (1024x768 = native no-op). Self-verifying: every site's NATIVE byte(s) are
// checked before writing; a mismatch is logged and skipped, never written.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_dl_scale_proto.log";
log("=== hook_dl_scale_proto.js v12l started " + new Date().toISOString() + " ===");
installAVHandler("dl_scale_proto");
// v11g: symbolizing AV handler (replaces the generic one): registers + a 0x300-byte stack scan naming every
// code address (exe .text, menu_strip_thunks, pcave2) by nearest symbol, so the log shows WHO called ntdll.
(function () {
  const SYMS = [[4206400,"load_menu"],[4207264,"MenuWidget_layout_show"],[4209392,"g_menu_hilite_draw"],[4209520,"g_menu_border_draw"],[4209568,"amovie_project"],[4209632,"amovie_project_2"],[4210800,"Movie_player"],[4211232,"Win_itemdraw_default"],[4211344,"GraphicWin_present_default"],[4212832,"sprite_draw_func"],[4212896,"Popup_ctor"],[4212992,"Popup_close"],[4213024,"Popup_show"],[4213376,"Popup_hide"],[4213520,"Popup_calculate_dimensions"],[4214704,"Popup_alloc"],[4214864,"Popup_on_adjust_button_placement"],[4217632,"Popup_on_dialog_item_back_draw"],[4217984,"Popup_on_draw_background"],[4219488,"popup_sb_create"],[4219696,"popup_sb_remove"],[4219776,"Popup_start"],[4221808,"Popup_on_scroll"],[4221856,"Popup_on_scroll_drag"],[4223696,"FileDlg_draw_row"],[4223824,"FileDlg_ctor"],[4224016,"FileDlg_layout"],[4225312,"FileDlg_save_title"],[4225664,"FileDlg_load_title"],[4228240,"BaseWin_ctor"],[4229920,"BaseWin_draw_psych"],[4230832,"BaseWin_draw_support"],[4231424,"BaseWin_map_pixel_to_tile"],[4245584,"BaseWin_draw_supported"],[4248144,"BaseWin_draw_flash"],[4252512,"BaseWin_draw_production"],[4255984,"BaseWin_draw_farm"],[4259008,"BaseWin_draw_facilities"],[4260784,"BaseWin_draw_garrison"],[4262000,"BaseWin_draw_commerce"],[4264512,"BaseWin_draw_nutrients"],[4266368,"BaseWin_draw_energy_alloc"],[4270752,"BaseWin_draw_expenses"],[4279104,"BaseWin_draw_pop"],[4280448,"BaseWin_draw_queue"],[4282160,"BaseWin_draw_misc"],[4283168,"BaseWin_draw_info"],[4288576,"BaseWin_production"],[4303136,"BaseWin_zoom"],[4315856,"BaseWin_on_status"],[4319120,"BaseWin_on_redraw"],[4319376,"BaseWin_show"],[4319408,"BaseWin_hide"],[4319440,"BaseWin_init"],[4337088,"BattleWin_on_iface_button_clicked"],[4337120,"BattleWin_on_iface_group_clicked"],[4342800,"CouncilWin_tally"],[4343584,"CouncilWin_vote_result"],[4349360,"CouncilWin_draw_column"],[4351088,"CouncilWin_draw_proposal"],[4352672,"CouncilWin_repaint"],[4353760,"CouncilWin_on_hover"],[4353952,"CouncilWin_show_hide"],[4354608,"CouncilWin_exec"],[4359504,"CouncilWin_dtor"],[4359712,"CouncilWin_ctor"],[4360064,"CreditsWin_ctor"],[4360320,"credits_load_text"],[4360688,"load_credits_a"],[4361216,"credits_draw"],[4361680,"credits_tick"],[4361712,"show_credits"],[4362176,"DatalinkWin_ctor"],[4362624,"DatalinkWin_open"],[4363008,"DatalinkWin_build"],[4366592,"DatalinkWin_list_bg_fill"],[4366672,"DatalinkWin_list_row_bg"],[4366944,"DatalinkWin_goto"],[4367040,"DatalinkWin_set_category"],[4367600,"DatalinkWin_list_all"],[4367920,"DatalinkWin_list_units"],[4368272,"DatalinkWin_list_chassis"],[4368640,"DatalinkWin_list_reactors"],[4368992,"DatalinkWin_list_weapons"],[4369344,"DatalinkWin_list_armor"],[4369696,"DatalinkWin_list_abilities"],[4370048,"DatalinkWin_list_facilities"],[4370400,"DatalinkWin_list_projects"],[4370832,"DatalinkWin_list_techs"],[4371200,"DatalinkWin_list_concepts"],[4371600,"DatalinkWin_list_adv_concepts"],[4372016,"DatalinkWin_list_social_models"],[4372448,"DatalinkWin_list_social_effects"],[4372800,"DatalinkWin_list_factions"],[4373168,"DatalinkWin_list_terraform"],[4373696,"DatalinkWin_select_item"],[4373824,"DatalinkWin_show"],[4373856,"DatalinkWin_hide"],[4373888,"DatalinkWin_push_history"],[4374016,"DatalinkWin_go_back"],[4374192,"DatalinkWin_show_console_text"],[4374288,"DatalinkWin_render_topic"],[4375264,"DatalinkWin_draw_concept"],[4376144,"DatalinkWin_draw_adv_concept"],[4377024,"DatalinkWin_draw_unit"],[4380176,"DatalinkWin_draw_chassis"],[4382448,"DatalinkWin_draw_reactor"],[4383456,"DatalinkWin_draw_weapon"],[4384992,"DatalinkWin_draw_armor"],[4386352,"DatalinkWin_draw_ability"],[4387984,"DatalinkWin_draw_facility"],[4389584,"DatalinkWin_draw_project"],[4391056,"DatalinkWin_draw_social_model"],[4392816,"DatalinkWin_draw_social_effect"],[4393776,"DatalinkWin_draw_tech_title"],[4394112,"DatalinkWin_draw_faction"],[4395392,"DatalinkWin_draw_terraform"],[4398528,"DatalinkWin_on_link_click"],[4398704,"DatalinkWin_repaint"],[4398784,"DatalinkWin_on_button_clicked"],[4399040,"DatalinkWin_on_key"],[4399120,"DatalinkWin_on_mouse_move"],[4399168,"DatalinkWin_on_list_select"],[4399200,"DatalinkIface_on_mode"],[4399632,"DatalinkIface_on_button"],[4399760,"DatalinkWin_dtor"],[4400576,"TextScroll_dtor"],[4400928,"TextScroll_on_link_click"],[4401328,"PartPicker_ctor"],[4401584,"PartPicker_cell_chassis"],[4402368,"PartPicker_cell_weapon"],[4403568,"PartPicker_cell_armor"],[4404512,"PartPicker_cell_reactor"],[4405280,"PartPicker_on_click"],[4405696,"PartPicker_repaint"],[4405776,"PartPicker_on_key"],[4406624,"PartPicker_draw_cell"],[4407088,"PartPicker_on_scroll"],[4407120,"PartPicker_on_scroll_drag"],[4407152,"PartPicker_exec"],[4408448,"DesignWin_ctor"],[4408992,"DesignWin_draw_title_box"],[4410304,"DesignWin_draw_chassis_box"],[4411200,"DesignWin_draw_weapon_box"],[4412416,"DesignWin_draw_armor_box"],[4413440,"DesignWin_draw_reactor_box"],[4414256,"DesignWin_draw_abil1_box"],[4414944,"DesignWin_draw_abil2_box"],[4415632,"DesignWin_draw_unit_preview"],[4422048,"DesignWin_repaint"],[4422560,"DesignWin_on_mouse_move"],[4422640,"DesignWin_design_it"],[4424800,"DesignWin_on_button_clicked"],[4429568,"DesignWin_on_hover"],[4430176,"DesignWin_on_click"],[4430368,"DesignWin_on_key"],[4430848,"DesignWin_abil_validate"],[4431152,"DesignWin_abil_add"],[4431536,"DesignWin_abil_remove"],[4431648,"DesignWin_pick_chassis"],[4432640,"DesignWin_pick_weapon"],[4433760,"DesignWin_pick_armor"],[4434432,"DesignWin_pick_reactor"],[4435056,"DesignWin_pick_ability"],[4439600,"DesignWin_select_name"],[4439888,"DesignWin_construct_model"],[4440432,"DesignWin_timer_tick"],[4440480,"DesignWin_reset"],[4440688,"DesignWin_build"],[4444352,"DesignWin_show"],[4444400,"DesignWin_hide"],[4444448,"DesignWinIface_on_mode"],[4444704,"DesignWinIface_on_slot_click"],[4444816,"DesignWinIface_on_slot_hover"],[4445008,"DesignWinIface_on_mouse_move"],[4445120,"DesignWinIface_on_mouse_leave"],[4445328,"DesignWin_scroll_to_unit"],[4445456,"DesignWin_draw_slot_strip"],[4447568,"DesignWin_draw_flash"],[4449424,"DesignWin_setup_veh"],[4450656,"DesignWin_close_external"],[4450720,"DesignWin_exec"],[4451504,"DesignWin_dtor"],[4451856,"PartPicker_dtor"],[4452336,"DiploTalkWin_ctor"],[4452672,"DiploTalkWin_show"],[4452720,"DiploTalkWin_hide"],[4452864,"DiploTalkWin_bioscan_tick"],[4452944,"DiploTalkWin_news_tick"],[4453008,"DiploTalkWin_on_command_forward"],[4453040,"DiploTalkWin_open"],[4453824,"DiploTalkWin_close"],[4453872,"DiploTalkWin_draw_bioscan_panel"],[4454288,"DiploTalkWin_draw_news_panel"],[4455056,"DiploTalkWin_draw_status_panels"],[4456576,"DiploTalkWin_draw_hq_panel"],[4457120,"DiploTalkWin_draw_strip"],[4457344,"DiploTalkIface_on_mode"],[4457808,"DiploTalkIface_on_button_clicked"],[4458016,"DiploTalkIface_on_event"],[4458192,"DiploTalkWin_set_modal"],[4458240,"DiploTalkWin_init"],[4459856,"DiploTalkWin_dtor"],[4490240,"load_hoficons"],[4508224,"help_social"],[4540384,"load_icons"],[4542400,"load_cursors"],[4543680,"def_caption_draw"],[4544016,"load_interface"],[4546176,"load_fixed_sprites"],[4560512,"MainWin_build"],[4568400,"painter_editor_info"],[4570192,"MainWin_draw_center_mode"],[4571792,"MainWin_tile_panels"],[4572064,"MainWin_turn_banner_refresh"],[4574384,"MainWinIface_on_event"],[4576128,"SubInterface_release_iface_mode"],[4576320,"slide_show"],[4577648,"slide_hide"],[4578976,"rail_slide_in"],[4580672,"rail_slide_out"],[4584160,"load_credits_b"],[4597472,"MapWin_ctor"],[4598144,"MapWin_calculate_dimensions"],[4619744,"MapWin_draw_base_names"],[4629840,"MapWin_draw_map"],[4632976,"draw_map"],[4633040,"MapWin_on_redraw"],[4655392,"MapWin_init"],[4655760,"MapWin_init_2"],[4661808,"load_monicons"],[4685424,"commlink_on_mouse_move"],[4685616,"commlink_on_lclick"],[4686160,"commlink_on_rclick"],[4687408,"commlink_draw_faction_row"],[4688864,"commlink_draw_mp_header"],[4690736,"commlink_redraw"],[4692336,"commlink_show"],[4692992,"commlink_hide"],[4693904,"commlink_win_build"],[4695440,"commlink_ctor"],[4696016,"NetMsg_close"],[4696064,"NetMsg_timer_daemon"],[4696208,"NetMsg_pop"],[4697328,"NetMsg_ctor"],[4699008,"NetWin_player_color"],[4699216,"NetWin_on_command"],[4716896,"NetWin_draw_options"],[4718288,"NetWin_draw_factions"],[4718976,"NetWin_draw_handicaps"],[4719472,"NetWin_draw_players"],[4720896,"NetWin_draw_settings"],[4725456,"NetWin_draw"],[4725840,"NetWin_ctor"],[4726416,"mp_defaults_init"],[4727952,"NetWin_setup_lobby"],[4731456,"NetWin_modal_proc"],[4733264,"NetWin_chat_draw"],[4737728,"TechWin_ctor"],[4737888,"TechWin_close"],[4737920,"TechWin_write_unlock_line"],[4738144,"TechWin_draw_cell_content"],[4743104,"TechWin_on_mouse_move"],[4743344,"TechWin_on_lclick"],[4743440,"TechWin_on_rclick"],[4743536,"TechWin_on_key"],[4744176,"TechWin_draw_cell"],[4744464,"TechWin_exec"],[4753312,"FactionPickWin_build"],[4757088,"FactionPickWin_redraw"],[4758432,"FactionPickWin_on_command"],[4761616,"FactionPickWin_exec"],[4773952,"PrefWin_build"],[4782592,"PrefWin_show"],[4783312,"PrefWin_on_key"],[4783568,"PrefWin_commit_close"],[4783968,"PrefWin_group_sel_changed"],[4784048,"PrefWin_hide_prev_page"],[4784448,"PrefWin_show_cur_page"],[4789120,"PrefWin_on_slider_changed"],[4789248,"PrefWin_on_command"],[4790288,"PrefWin_repaint_right"],[4790368,"PrefWin_repaint_gamma"],[4791296,"PrefWin_refresh"],[4792800,"PrefWin_ctor"],[4793376,"ProdPicker_ctor"],[4794304,"ProdPicker_draw_cell"],[4796320,"ProdPicker_build_items"],[4799600,"ProdPicker_draw_visible"],[4799664,"ProdPicker_scroll_to"],[4800112,"ProdPicker_on_scroll_drag"],[4800160,"ProdPicker_right_menu"],[4800960,"ProdPicker_select_from_xy"],[4801152,"ProdPicker_page_nav"],[4802000,"ProdPicker_on_button_clicked"],[4802256,"ProdPicker_anim_tick"],[4802304,"ProdPicker_exec"],[4805024,"Holobook_gwinit"],[4806352,"Holobook_draw"],[4810256,"Holobook_open_item"],[4810352,"Holobook_open_unit"],[4810768,"Holobook_ctor"],[4811696,"ReportWin_tech_reset"],[4818640,"ReportWin_tech_button"],[4819760,"ReportWin_tech_page"],[4829728,"ReportWin_tech_hover"],[4863072,"init_report_screen"],[4875056,"ReportIf_on_button_clicked"],[4877680,"ReportIf_on_event"],[4905088,"SetupWin_ctor"],[4905840,"SetupWin_do_menu_rightside"],[4908240,"SetupWin_draw_item"],[4909536,"SocialWin_ctor"],[4910304,"SocialWin_model_reset"],[4911584,"SocialWin_draw_society_panel"],[4911888,"SocialWin_draw_band"],[4913344,"SocialWin_draw_faction_box"],[4914016,"SocialWin_draw_center_console"],[4916240,"SocialWin_draw_effects_text"],[4917408,"SocialWin_draw_slider_econ"],[4918016,"SocialWin_draw_slider_labs"],[4918608,"SocialWin_draw_slider_psych"],[4919424,"SocialWin_draw_hover_panel"],[4921248,"SocialWin_draw_society_row"],[4921760,"SocialWin_repaint"],[4922592,"SocialWin_on_option_click"],[4922736,"SocialWin_hover_refresh"],[4922880,"SocialWin_on_command"],[4923072,"SocialWin_on_mouse_move"],[4923328,"SocialWin_on_mouse_leave"],[4923376,"SocialWin_redistribute"],[4923680,"SocialWin_show_hide"],[4924528,"SocialWin_on_arrow"],[4925136,"SocialWin_close"],[4925248,"SocialWin_build"],[4934896,"StatusWin_draw_active"],[4941168,"StatusWin_draw_status"],[4950064,"StatusWin_draw"],[4950160,"StatusWin_on_redraw"],[4956096,"StatusWin_init"],[4956576,"StatusWin_ctor"],[4957872,"TutWin_ctor"],[4971712,"TutWin_on_button_clicked"],[4972192,"TutWin_draw_arrow"],[4972512,"TutWin_tut_win"],[4974160,"TutWin_tut_map"],[4975184,"set_video_mode"],[4977664,"movie_ddraw_fs_teardown"],[4977840,"movie_ddraw_fs_init"],[4995408,"WorldWin_set_detail_map"],[4995472,"WorldWin_set_world_map"],[4995536,"WorldWin_show_all"],[4996800,"WorldWin_on_redraw"],[4998704,"WorldWin_draw_box"],[5007072,"Wave_ctor"],[5007296,"Wave_dtor"],[5007648,"Wave_play_2"],[5008144,"Wave_is_playing"],[5008416,"Wave_load"],[5008816,"Wave_load_3"],[5009056,"Wave_unload"],[5089680,"DiploEditWin_loop"],[5090720,"DiploEditWin_update"],[5091456,"DiploEditWin_exec"],[5093488,"Console_editor_diplomacy"],[5114448,"Console_editor_paints"],[5115552,"Console_editor_set_brush"],[5120576,"DiploEditWin_dtor"],[5290464,"NetMsg_pop_2"],[5305440,"Console_ctor"],[5305984,"Console_on_nc_hittest"],[5306720,"Console_on_post_redraw_nc_buffer"],[5307152,"Console_on_nc_left_down"],[5308016,"Console_on_nc_left_up"],[5308688,"Console_on_nc_mouse_move"],[5326976,"Console_update_data"],[5330800,"Console_chat"],[5331200,"Console_time_controls"],[5356656,"Console_menu_proc"],[5363488,"Console_menu_daemon"],[5363856,"Console_init"],[5386464,"interlude"],[5389408,"set_time_controls"],[5605856,"commlink_attempter"],[5606496,"commlink_attempt"],[5608144,"FontCache_get"],[5608688,"veh_draw"],[5615392,"base_draw"],[5800688,"find_font"],[5801056,"popups_normal"],[5802208,"popups_tutorial"],[5802656,"config_popups"],[5804848,"time_controls_dialog"],[5806240,"thumb_routine"],[5806640,"change_opening"],[5806880,"close_opening"],[5806944,"init_opening"],[5807408,"config_game"],[5816992,"custom_planet"],[5823280,"multiplayer_init"],[5825376,"top_menu"],[5886544,"Menu_run"],[5886880,"Menu_begin"],[5888832,"prefs_get_2"],[5891376,"prefs_put_2"],[5891536,"prefs_save"],[5892432,"prefs_use"],[5938864,"save_game"],[5941936,"load_game"],[5981696,"social_set"],[5985824,"social_select"],[6024048,"tech_pick"],[6069952,"uv_decode_frame"],[6073984,"movie_play_open"],[6074448,"uv_container_open"],[6074912,"uv_decode_thread"],[6075920,"uv_is_playing"],[6078000,"uv_ddraw_surfaces"],[6080832,"uv_present_frame"],[6087488,"uv_dsound_init"],[6114544,"GraphicWin_ctor"],[6115056,"GraphicWin_init"],[6115488,"GraphicWin_init_2"],[6115920,"GraphicWin_clear"],[6116416,"GraphicWin_fill_3"],[6116608,"GraphicWin_load_pcx"],[6116672,"GraphicWin_resize"],[6116912,"GraphicWin_update_2"],[6117040,"GraphicWin_present"],[6117152,"GraphicWin_soft_update"],[6117680,"GraphicWin_soft_update_3"],[6118000,"GraphicWin_redraw"],[6118640,"GraphicWin_on_paint"],[6123568,"GraphicWin_compute_min_size"],[6124048,"Buffer_ctor"],[6125168,"Buffer_init"],[6126016,"Buffer_resize"],[6127072,"Buffer_load_pcx"],[6127616,"Buffer_set_clip"],[6128128,"Buffer_set_clip_2"],[6128192,"Buffer_fill"],[6128832,"Buffer_draw_2"],[6131424,"Buffer_draw_dest_source_2"],[6132912,"Buffer_draw_table"],[6133264,"Buffer_copy_3"],[6137536,"Buffer_tile_mask"],[6137952,"Buffer_tile"],[6138352,"Buffer_tile_2"],[6138992,"Buffer_set_font"],[6139056,"Buffer_set_text_color"],[6139968,"Buffer_write_strings"],[6141312,"Buffer_write_l"],[6141728,"Buffer_write_cent_l_2"],[6142512,"Buffer_wrap_cent"],[6142976,"Buffer_wrap_cent_3"],[6143232,"Buffer_write_raw_l"],[6144864,"Buffer_wrap_height"],[6145040,"Buffer_find_line_break_l"],[6145936,"Buffer_text_width"],[6145984,"Buffer_text_width_2"],[6146688,"Buffer_text_height"],[6146736,"Buffer_text_line_height"],[6146784,"Buffer_write_multi_font_raw_l"],[6147744,"Buffer_write_l_3"],[6147904,"Buffer_write_l_4"],[6148128,"Buffer_write_cent_l_5"],[6148400,"Buffer_write_cent_l_7"],[6148688,"Buffer_write_cent_l_8"],[6148864,"Buffer_write_right_l_4"],[6149040,"Buffer_write_right_l_5"],[6149200,"Buffer_write_right_l_6"],[6149424,"Buffer_wrap_2"],[6149936,"Buffer_wrap_3"],[6150432,"Buffer_wrap_cent_4"],[6150832,"Buffer_wrap_cent_6"],[6151584,"Buffer_wrap_height_flying"],[6151648,"Buffer_wrap_height_flying_2"],[6151920,"Buffer_wrap_height_flying_flush"],[6153600,"Buffer_change_color"],[6154032,"Buffer_change_color_2"],[6154480,"Buffer_sync_to_palette"],[6159184,"Buffer_fill_2"],[6159568,"Buffer_fill_3"],[6160128,"Buffer_copy_4"],[6167168,"Buffer_hline_2"],[6167536,"Buffer_vline_2"],[6168688,"Buffer_change_color_3"],[6169104,"Buffer_get_pixel"],[6169392,"Buffer_put_pixel"],[6170256,"Buffer_load_pcx_2"],[6172115,"Buffer_box_sprite"],[6173075,"Buffer_box"],[6173187,"Buffer_box_2"],[6173555,"Buffer_get_data"],[6173859,"Buffer_free_data"],[6175072,"Sprite_extract"],[6175136,"Sprite_extract_2"],[6176336,"Sprite_draw_mono_2"],[6179658,"Sprite_draw_2"],[6179738,"Sprite_blit_scaled_core"],[6197157,"Sprite_draw_table_scaled"],[6197237,"Sprite_draw_table"],[6204175,"Sprite_get_clipped_x_table_expand"],[6204351,"Sprite_get_clipped_y_table_expand"],[6204527,"Sprite_get_clipped_x_table_shrink"],[6204671,"Sprite_get_clipped_y_table_shrink"],[6205967,"Sprite_fill_scaling_table"],[6208896,"Win_init"],[6213600,"Win_flip_rect_2"],[6214208,"GraphicWin_local_to_screen"],[6214352,"Win_screen_to_client_2"],[6215104,"Win_center"],[6215632,"Win_move"],[6216144,"Win_show"],[6216912,"Win_hide"],[6218128,"Win_set_modal"],[6218960,"Win_forward_mouse_move"],[6219600,"Win_left_down_event"],[6225184,"Win_flip_rect"],[6226416,"Win_init_class"],[6227536,"WinProc"],[6232096,"Win_update_cursor"],[6234768,"Win_OnMouseMove"],[6234928,"Win_OnLButtonDown"],[6235504,"Win_OnLButtonUp"],[6235584,"Win_OnRButtonDown"],[6235680,"Win_OnRButtonUp"],[6236864,"Win_window_line_raw"],[6237248,"Win_set_display_mode"],[6246080,"recurse_zorder"],[6246912,"Win_add_child"],[6249168,"Win_on_nc_hittest"],[6249744,"App_on_key_message"],[6251296,"Win_on_mouse_move"],[6251456,"Win_on_l_button_down"],[6251856,"Win_on_l_button_up"],[6252672,"Win_on_r_button_up"],[6253136,"Win_get_active_target"],[6254352,"Win_get_mouse_window"],[6255392,"Win_update_screen"],[6255776,"Win_draw_rect"],[6256000,"Win_do_tracking"],[6258320,"Win_is_visible"],[6259664,"Win_set_bubble_text"],[6259968,"Win_clear_bubble_text"],[6261024,"Menu_init"],[6261200,"Menu_add_item"],[6261728,"Menu_add_separator"],[6263152,"Menu_show"],[6264208,"Menu_draw_dispatch"],[6266160,"Menu_measure_width"],[6266720,"Menu_draw"],[6268896,"in_box_2"],[6268976,"Spot_shutdown"],[6269088,"Spot_init"],[6269280,"Spot_add"],[6269584,"Spot_kill_type"],[6269696,"Spot_check"],[6269952,"Spot_get_rect"],[6273072,"Menu_on_select"],[6290864,"Movie_mci_stop_close"],[6291344,"Movie_mci_open"],[6291936,"Movie_mci_play"],[6293600,"BasePop_ctor"],[6297008,"BasePop_init"],[6298496,"BasePop_set_loc"],[6298608,"BasePop_start"],[6301184,"BasePop_exec_3"],[6305792,"BasePop_calculate_dimensions"],[6310576,"BasePop_on_redraw"],[6312176,"BasePop_set_def_external_window"],[6312400,"ScrollBar_ctor"],[6312816,"ScrollBar_subctor"],[6313168,"ScrollBar_init_inner"],[6314048,"ScrollBar_attach_rect"],[6314128,"ScrollBar_attach"],[6314192,"ScrollBar_init"],[6314256,"ScrollBar_init_v"],[6314416,"ScrollBar_set_range"],[6315296,"ScrollBar_set_pos"],[6315408,"ScrollBar_on_mouse_move"],[6316512,"ScrollBar_on_press"],[6316816,"ScrollBar_on_release"],[6317408,"ScrollBar_on_key"],[6317808,"ScrollBar_draw"],[6318176,"ScrollBar_on_resize"],[6318496,"ScrollBar_on_chevron_repeat"],[6318880,"ScrollBar_on_chevron"],[6319184,"ScrollBar_thumb_rect"],[6320656,"BaseButton_init"],[6321376,"BaseButton_set_name"],[6321488,"BaseButton_set_bubble_text"],[6323440,"FlatButton_ctor"],[6323792,"FlatButton_content_draw"],[6325504,"FlatButton_on_mouse_move"],[6325856,"FlatButton_on_mouse_move_2"],[6326656,"TextList_load"],[6328656,"Dialog_init"],[6329088,"Dialog_init_2"],[6331680,"Dialog_set_def_dialog_font"],[6332448,"ListBox_set_selected_pos"],[6332896,"ListBox_calculate_dimensions"],[6334064,"ListBox_attach"],[6337840,"ListBox_draw_item"],[6342096,"ListBox_on_scrolling"],[6342944,"Dialog_item"],[6343088,"ListBox_update_changes"],[6344480,"ListBox_scroll_delete_cb"],[6345200,"Dialog_type16_attach"],[6345600,"Dialog_type16_calc_dimensions"],[6350448,"CheckList_ctor"],[6350784,"CheckList_init"],[6350848,"FUN_0060e800_type1_attach"],[6351232,"CheckList_add_item"],[6358336,"OptionList_attach"],[6359408,"OptionList_calculate_dimensions"],[6360144,"OptionList_draw_item"],[6361984,"OptionList_on_redraw"],[6363888,"Dialog_type4_attach"],[6365520,"Dialog_type4_calc_dimensions"],[6367600,"Dialog_set_type"],[6367856,"Dialogs_item"],[6368768,"Dialog_on_redraw_dispatch"],[6369824,"ListBox_scroll_create_cb"],[6369952,"Dialog_dims_dispatch"],[6371760,"FileDlg_build_widgets"],[6372688,"FileDlg_save_modal"],[6373216,"FileDlg_load_modal"],[6373824,"FileDlg_set_filename"],[6374240,"FileDlg_populate_list"],[6375072,"FileDlg_activate_entry"],[6376336,"FileDlg_on_nav"],[6376528,"FileDlg_draw_row_icon"],[6377040,"EditLine_ctor"],[6377440,"EditLine_attach"],[6386080,"Caviar_overlay"],[6386224,"Caviar_draw"],[6387232,"Caviar_draw_silhouette"],[6387312,"Caviar_draw_flag10"],[6390704,"Caviar_set_zoom"],[6390720,"Caviar_get_zoom"],[6390896,"Caviar_reset"],[6393504,"Font_ctor"],[6393664,"Font_init"],[6394496,"Font_width"],[6394736,"Font_find_line_break_l"],[6459664,"TextScroll_ctor"],[6460112,"TextScroll_attach"],[6460560,"TextScroll_finish"],[6461312,"TextScroll_clear"],[6462320,"TextScroll_draw"],[6462752,"TextScroll_set_first_line"],[6462816,"Flic_ctor"],[6462960,"Flic_dtor"],[6463056,"Flic_init"],[6463600,"Flic_draw_frame"],[6463776,"Flic_draw_frame_once"],[6464016,"Flic_advance"],[6464128,"Flic_rewind"],[6464768,"Flic_decode_brun"],[6465312,"Flic_decode_ss2"],[6466432,"Flic_decode_copy"],[6466768,"Flic_decode_chunk"],[6467392,"Flic_decode_brun_keyed"],[6467984,"Flic_decode_ss2_keyed"],[6469232,"Flic_decode_keyed_frame"],[6469648,"ButtonGroup_init"],[6469712,"ButtonGroup_add"],[6469744,"ButtonGroup_set_by_id"],[6469792,"ButtonGroup_select"],[6471456,"BorderButton_ctor"],[6471728,"BorderButton_ctor_2"],[6471952,"BorderButton_content_draw"],[6509840,"GraphicsMgr_set_mode"],[6528608,"Caviar_rasterize"],[6530800,"Caviar_model_extents"],[6532448,"Caviar_ctx_select_plotters"],[6532864,"Caviar_plot8_setup"],[6547792,"Caviar_rasterize_part"],[6552192,"Caviar_part_matrix_fixed"],[6552736,"Caviar_part_light_setup"],[6554864,"Caviar_cube_axes"],[6573784,"_initterm"],[6575498,"crt_malloc"],[6585399,"_lock_file"],[6585481,"_unlock_file"],[6592376,"_getstream"],[6701056,"Caviar_plot8_clip"],[6703088,"Caviar_plot8_full"],[6704465,"Caviar_plot8_bind_target"],[6704720,"Caviar_plot8_clip_alt"],[6706752,"Caviar_plot8_full_alt"],[6710336,"Caviar_plot16_full"],[6716192,"Caviar_plot16_full_alt"],[6717792,"PRACX_load_stub"],[6718464,"scale_uniform"],[6718560,"thunk_scale_rect_width"],[6718592,"thunk_strip_blit_stretched"],[6718704,"thunk_advance_edi_by_scaled_h"],[6718736,"thunk_load_strip_w_into_eax"],[6718784,"thunk_push_scaled_font"],[6718816,"thunk_spot_h_into_edi"],[6718848,"thunk_spot_h_into_eax"],[6718864,"thunk_spot_h_into_ecx"],[6718884,"thunk_text_fullrect"],[6718936,"thunk_clip_fullstrip"],[6718976,"thunk_fill3_scaled"],[6719040,"thunk_scale20_into_edx"],[6719056,"thunk_load_strip_w_into_edi"],[6719120,"filelock_lock"],[6719152,"filelock_unlock"],[6719168,"filelock_var"],[6719232,"thunk_deco_blit_stretched"],[6719344,"scale_x"],[6719376,"scale_y"],[6719408,"thunk_deco_soft_update"],[6719504,"thunk_deco_keyed_scaled"],[6719600,"thunk_keyed_stretch_blit"],[6719696,"thunk_ensure_scratch"],[6719760,"g_scratch_buf"],[6719808,"g_popup_scale_num"],[6719812,"g_pf0"],[6719816,"g_pf1"],[6719820,"g_pf2"],[6719824,"popup_scale"],[6719840,"thunk_ensure_scale"],[6719904,"thunk_popup_setup_fonts"],[6720176,"thunk_sprite_draw"],[6720256,"thunk_scale_btnheight"],[6720304,"thunk_btnfont_enter"],[6720384,"thunk_btnfont_leave"],[6720432,"g_btnfont_save0"],[6720436,"g_btnfont_save1"],[6720440,"g_btnfont_save2"],[6720448,"thunk_scale_btnh_compute"],[6720480,"thunk_btnh_create"],[6720512,"thunk_grow_box"],[6720560,"thunk_fix_bar_h"],[6720596,"g_native_barh"],[6720608,"post_fill_vscale"],[6720720,"thunk_wrap_budget"],[6720768,"thunk_zero_init_cs"],[6720864,"thunk_list_fill_width"],[6720976,"thunk_content_frame"],[6721024,"thunk_rowgap"],[6721072,"g_boxw_num"],[6721088,"thunk_checkbox_scale"],[6721136,"thunk_checkbox_textx"],[6721168,"thunk_checkbox_indent"],[6721216,"thunk_checkbox_margin"],[6721248,"thunk_inner_margin"],[6721296,"g_frame_buf"],[6721312,"thunk_title_textnudge"],[6721344,"thunk_bubble_font"],[6721384,"thunk_title_hmargin"],[6721392,"thunk_bubble_inset_fill"],[6721424,"thunk_title_font"],[6721456,"thunk_scale_header"],[6721488,"thunk_title_height"],[10189384,"void"],[10534912,"thunk_box_thick_hollow"],[10535136,"thunk_scale_box_margin"],[10535232,"thunk_box_thick_hollow_flat"],[10535456,"thunk_btn_vcenter"],[10535504,"popup_scale_3half"],[10535520,"thunk_clamp_frame_rect"],[10535584,"thunk_faction_titlerect"],[10535840,"thunk_popup_center_x"],[10535936,"thunk_btn_shrink"],[10536064,"thunk_btn_2dscale"],[10536176,"thunk_set_popup_active"],[10536208,"thunk_clr_popup_active"],[10536240,"g_popup_active"],[10536244,"g_btn_pending"],[10536248,"g_btn_origW"],[10536252,"g_btn_origH"],[10536256,"g_btn_nativeW"],[10536260,"g_btn_nativeH"],[10536264,"g_btn_tileH"],[10536272,"g_faction_quote"],[10536400,"g_frame_inset_rect"],[10536480,"thunk_d528_inset"],[10536640,"thunk_faction_textmargin"],[10536736,"thunk_faction_bodyfont"],[10536800,"thunk_build_scaled_fonts"],[10536960,"an_str"],[10536976,"scratch0_font"],[10537024,"scratch2_font"],[10537072,"g_pf_target"],[10537076,"g_pf_size"],[10537472,"thunk_portrait_avg"],[10538448,"thunk_faction_footer_bump"],[10538688,"g_devfill_params"],[10538736,"g_devfill_rect"],[10538740,"g_devfill_rect_T"],[10538744,"g_devfill_rect_R"],[10538748,"g_devfill_rect_B"],[10538752,"g_title_left"],[10538756,"g_title_right"],[10538760,"g_pf_align_l"],[10538764,"g_pf_align_t"],[10538768,"g_pf_align_r"],[10538772,"g_pf_align_b"],[10538776,"thunk_pf_title_stash"],[10539008,"g_faction_build_active"],[10539024,"g_faction_scratch_rect"],[10539120,"thunk_factionwin_clrflag"],[10539152,"thunk_factionwin_button"],[10539264,"thunk_factionwin_list"],[10539360,"thunk_factionwin_quoteloc"],[10539520,"thunk_factionwin_font"],[10539648,"thunk_factionwin_pitch"],[10539728,"g_faction_active"],[10539792,"thunk_faction_show"],[10539920,"thunk_btntext_nudge"],[10540112,"thunk_faction_rowgap"],[10540208,"thunk_faction_droppos"],[10540344,"g_seven"],[10540348,"g_drop_n"],[10540352,"g_su16"],[10540356,"g_six"],[10540384,"thunk_factionwin_graphicwin"],[10540544,"g_btn_fill_sprite"],[10540548,"g_btn_fill_x"],[10540552,"g_btn_fill_y"],[10540556,"g_btn_fill_w"],[10540560,"g_btn_fill_h"],[10540564,"g_corner_dx"],[10540568,"g_corner_off"],[10540640,"thunk_btn_devfill"],[10540864,"thunk_corner_punch"],[10540928,"thunk_faction_dropimg"],[10541168,"g_submenu_save_font"],[10541172,"g_submenu_save_mv"],[10541176,"g_submenu_save_mh"],[10541184,"thunk_faction_submenu"],[10541360,"thunk_rebuild_pitch"],[10541440,"thunk_rebuild_gap"],[10541504,"thunk_uimod_loader"],[10541568,"thunk_conn_vline"],[10541696,"thunk_conn_hline"],[10541824,"thunk_conn_pixel"],[10541952,"thunk_conn_chevron"],[10542080,"thunk_conn_diag"],[10542336,"thunk_conn_fan_vline"],[10542480,"thunk_conn_fan_row"],[10542624,"thunk_conn_fan_tick"],[10542944,"g_fan_top"],[10542948,"g_fan_bot"],[10543104,"g_d528_left"],[10543120,"g_pf_union_l"],[10543124,"g_pf_union_t"],[10543128,"g_pf_union_r"],[10543132,"g_pf_union_b"],[10543360,"thunk_faction_portrait"],[10543440,"thunk_sprite_scale_nn"],[10543904,"thunk_filedlg_graphicwin"],[10543984,"thunk_filedlg_rects"],[10544032,"g_filedlg_active"],[10544048,"thunk_filedlg_modal_load"],[10544096,"thunk_filedlg_modal_save"],[10544128,"thunk_factionwin_framecover"],[10544448,"g_fc_win_r"],[10544452,"g_fc_title_rect"],[10544468,"g_fc_exact"],[10544608,"g_fd_winbuf"],[10544640,"thunk_filedlg_titlefont"],[10544672,"thunk_filedlg_dlgfont"],[10544736,"thunk_filedlg_editfont"],[10544800,"thunk_filedlg_setflag"],[10544848,"thunk_band_stash"],[10544896,"g_band_left"],[10544900,"g_field_anchor"],[10544904,"g_band_popup"],[10544908,"g_band_bottom"],[10544928,"thunk_filedlg_frame"],[10545408,"g_fd_outer"],[10545424,"g_fd_scratch"],[10545440,"g_fd_inner"],[10545472,"g_fd_bilinear"],[10545504,"thunk_bilinear_blit"],[10546360,"thunk_filedlg_rowbg"],[10546456,"thunk_copy4_flatten"],[10546560,"g_stripe_navy"],[10546564,"g_stripe_sel"],[10546568,"g_stripe_g"],[10546576,"g_stripe_rect_l"],[10546580,"g_stripe_rect_t"],[10546584,"g_stripe_rect_r"],[10546588,"g_stripe_rect_b"],[10546592,"thunk_ensure_stripes"],[10546944,"thunk_filedlg_rowbg_v6"],[10547024,"thunk_copy4_stripes"],[10547104,"g_fe_dst"],[10547108,"g_fe_x"],[10547112,"g_fe_y"],[10547116,"g_fe_w"],[10547120,"g_fe_h"],[10547124,"g_rm_xend"],[10547128,"g_rm_yend"],[10547132,"g_rm_hn"],[10547136,"g_rm_col"],[10547140,"g_fe_src"],[10547144,"g_rm_navy"],[10547148,"g_rm_povr"],[10547152,"thunk_btn_stripes"],[10547552,"thunk_filedlg_listpitch"],[10547664,"thunk_filedlg_titlerect"],[10547712,"thunk_filedlg_insets"],[10547840,"thunk_filedlg_railslide"],[10548160,"thunk_filedlg_slidehide_disarm"],[10548224,"thunk_qdlg_font"],[10548272,"thunk_q8_pitchgap"],[10548304,"thunk_q8_totalgap"],[10548352,"thunk_q8_fill_width"],[10548432,"thunk_quit_rowpitch"],[10548560,"thunk_popup_railshow"],[10548784,"g_popup_railsave"],[10548800,"thunk_popup_d690insets"],[10548896,"thunk_popup_titleinsets"],[10548992,"thunk_popup_fieldR"],[10549104,"thunk_popup_nestpads"],[10549152,"thunk_popup_artalign"],[10549248,"thunk_pp_frame"],[10549312,"thunk_pp_cellrect"],[10549408,"thunk_pp_btnframe"],[10549552,"thunk_pp_boxsprite"],[10549600,"thunk_pp_hity"],[10549632,"thunk_pp_hitx"],[10549680,"thunk_pp_titlepad"],[10549728,"g_rm_c5"],[10549732,"g_rm_bf"],[10549736,"g_rm_c5col"],[10549740,"g_rm_bfcol"],[10549760,"thunk_pcx_fullscreen"],[10549920,"thunk_credits_subwin"],[10550048,"thunk_credits_font"],[10550096,"thunk_credits_scroll"],[10550128,"thunk_credits_fade"],[10550336,"thunk_interlude_font"],[10550496,"g_il_f0"],[10550500,"g_il_f1"],[10550504,"g_il_f2"],[10550512,"thunk_interlude_clamp"],[10550560,"thunk_interlude_nudge"],[10550592,"thunk_credits_music"],[10550720,"thunk_rowbox_guard"],[10550784,"thunk_lbcalc_scale"],[10550896,"thunk_item_wrap_budget"],[10550976,"thunk_lbcalc_minw"],[10551136,"thunk_btnh_read_edx"],[10551296,"thunk_tutbtn_post"],[10551456,"thunk_bw_boxsprite_console"],[10551600,"thunk_basewin_gwinit"],[10551968,"thunk_box_thick_devfill"],[10552496,"g_rm_force"],[10552500,"g_rm_bd"],[10552504,"g_rm_bdcol"],[10552508,"g_field_L"],[10552512,"g_field_R"],[10552516,"g_field_boxw"],[10552528,"thunk_popup_railhide"],[10552896,"thunk_hud_cellring"],[10553344,"g_netwin_active"],[10553348,"g_nw_ret"],[10553360,"thunk_netwin_bracket"],[10553392,"thunk_nw_winsize"],[10553424,"thunk_nw_rectscale"],[10553552,"thunk_nw_font"],[10553584,"thunk_nw_blit_right"],[10553632,"thunk_nw_blit_left"],[10553696,"thunk_nw_toggle"],[10553792,"thunk_opt_ckx"],[10553824,"thunk_opt_rowh"],[10553856,"thunk_opt_indent_edi"],[10553872,"thunk_opt_indent_add"],[10553904,"thunk_opt_indent_sub"],[10553936,"thunk_opt_step"],[10553952,"thunk_opt_col2dx"],[10553984,"thunk_opt_rewind"],[10554000,"thunk_nw_chatfont"],[10554048,"thunk_nw_slackA_ebx"],[10554064,"thunk_nw_slackA_eax"],[10554096,"thunk_nw_slackB_bx_ax"],[10554128,"thunk_nw_slackB_ax_bx"],[10554160,"thunk_nw_slackB_cx_bx"],[10554192,"thunk_nw_slackAp_ebx"],[10554224,"thunk_sb_xinset"],[10554256,"thunk_sb_width"],[10554288,"thunk_sb_thumb"],[10554368,"thunk_nw_blit_gap"],[10554624,"thunk_hud_seedscale"],[10554768,"g_hud_seedtable"],[10554976,"thunk_hud_font"],[10555008,"thunk_band_draw"],[10555268,"thunk_band_recapture"],[10555380,"g_band_scratch"],[10555392,"thunk_hud_fontobj"],[10555488,"thunk_hud_fcache"],[10555696,"thunk_hud_baseargs"],[10555824,"thunk_hud_slotw"],[10555840,"thunk_hud_titley"],[10555856,"thunk_hud_cellw"],[10555872,"thunk_hud_n01"],[10555920,"thunk_hud_n02"],[10555968,"thunk_hud_n03"],[10556016,"thunk_hud_n04"],[10556064,"thunk_hud_n05"],[10556112,"thunk_hud_n06"],[10556160,"thunk_hud_n07"],[10556224,"thunk_hud_n08"],[10556288,"thunk_hud_n09"],[10556336,"thunk_hud_n10"],[10556416,"thunk_hud_n11"],[10556464,"thunk_hud_n12"],[10556512,"thunk_hud_n13"],[10556560,"thunk_hud_n14"],[10556608,"thunk_hud_n15"],[10556688,"thunk_hud_n16"],[10556736,"thunk_hud_cellh"],[10556928,"g_hud_nat_table"],[10557216,"g_hud_rect"],[10557232,"g_hud_rect2"],[10557248,"thunk_hud_boxframe"],[10557472,"thunk_hud_cellclip"],[10557696,"g_hud_rect3"],[10557728,"thunk_btn_fillcap"],[10557840,"thunk_hud_btnfont"],[10557952,"restripe_core"],[10558128,"thunk_band_stretch_remap"],[10558400,"g_hud_rect4"],[10558464,"thunk_worldwin_fill"],[10558544,"thunk_minimap_force"],[10558704,"g_mm_lastX"],[10558708,"g_mm_lastY"],[10558720,"hm_font_size_table"],[10558736,"g_hm_sd2_ret"],[10558740,"g_hm_sd2_args"],[10558764,"g_hm_sbc_ret"],[10558768,"g_hm_sbc_args"],[10558792,"g_hm_sbc_onum"],[10558796,"g_hm_sbc_oden"],[10558816,"hm_sc"],[10558832,"hm_rowY"],[10558944,"hm_scalefont"],[10559104,"thunk_comm_setfont"],[10559248,"thunk_comm_cent5"],[10559392,"thunk_comm_cent7"],[10559472,"thunk_comm_gwinit"],[10559536,"thunk_comm_btninit"],[10559648,"thunk_comm_btnfont"],[10559744,"thunk_menu_layout"],[10559904,"thunk_menu_text"],[10560128,"thunk_menu_winmove"],[10560304,"thunk_hudmenu_sd2"],[10560672,"thunk_hudmenu_sbc"],[10560976,"hm_synth_core"],[10561664,"thunk_hud_n17"],[10561728,"thunk_hud_n18"],[10561792,"thunk_d5a0_center"],[10561888,"thunk_hud_n19"],[10561920,"thunk_hud_n21"],[10561984,"thunk_hud_n22"],[10562016,"thunk_hud_n20"],[10562048,"thunk_channel_adjust"],[10562304,"thunk_portrait_drop"],[10562560,"thunk_frame_intK"],[10562784,"thunk_dfstep1_dispatch"],[10562808,"g_faction_text_bottom"],[10562816,"thunk_d690_fill"],[10562880,"g_fac_body_bottom"],[10562896,"thunk_fac_bottom_stash"],[10563072,"thunk_faction_wrapwidth"],[10563584,"g_bm_fx"],[10571776,"g_bm_fy"],[10575872,"g_bm_fwdx"],[10576128,"g_bm_fwdy"],[10576384,"g_band_nx"],[10576388,"g_band_ny"],[10576392,"g_bm_dstw"],[10576396,"g_bm_dsth"],[10576400,"thunk_fe_bandmap"],[10576640,"thunk_bandmap_blit"],[10577728,"thunk_q16_rowgap"],[10578064,"thunk_tutwin_fonts"],[10578160,"thunk_tutwin_line"],[10578208,"thunk_tutwin_backdrop"],[10578320,"g_tw_dest"],[10578400,"thunk_btn_gate"],[10578656,"thunk_pref_gwinit"],[10579040,"thunk_pref_ffscale"],[10579072,"thunk_pref_dlg2"],[10579136,"thunk_pref_attach"],[10579200,"thunk_pref_boxframe"],[10579296,"thunk_pref_btnzoom"],[10579376,"thunk_pref_sbzoom"],[10579488,"thunk_scale_nn_v1shim"],[10579712,"thunk_scale_boxw"],[10580256,"g_dll_pref_lo"],[10580260,"g_dll_pref_hi"],[10580264,"g_dll_pref_slider"],[10580268,"g_map_font_pct"],[10580272,"thunk_map_font"],[10580352,"thunk_pref_show"],[10580560,"g_pref_wins"],[10580672,"thunk_popup_min_boxh"],[10580736,"thunk_scale_reject_uncache"],[10580800,"thunk_bw_boxsprite_tabframe"],[10580976,"thunk_basewin_btnzoom"],[10581072,"thunk_bw_rect_core"],[10581184,"thunk_bw_xy_core"],[10581248,"thunk_bw_clip"],[10581360,"thunk_bw_text_l4"],[10581376,"thunk_bw_text_c7"],[10581392,"thunk_bw_text_r6"],[10581408,"thunk_bw_text_l3"],[10581424,"thunk_bw_text_r5"],[10581440,"thunk_bw_text_c5"],[10581520,"thunk_bw_fontinit"],[10581568,"thunk_bw_findfont"],[10581616,"thunk_bw_setfont"],[10581712,"g_bw_rect"],[10581728,"g_bw_font"],[10581776,"thunk_bw_boxsprite"],[10581920,"thunk_bw_tile2"],[10582208,"thunk_bw_fill2"],[10582320,"thunk_bw_sd2"],[10582416,"thunk_bw_mono"],[10582512,"thunk_bw_sbc"],[10582656,"g_bw_ret"],[10582660,"g_bw_sav"],[10582672,"thunk_bw_mapblit"],[10582848,"thunk_bw_spotadd"],[10582976,"thunk_bw_ext_l4"],[10583024,"thunk_bw_ext_c7"],[10583072,"thunk_bw_ext_r6"],[10583120,"thunk_bw_ext_l3"],[10583168,"thunk_bw_ext_r5"],[10583216,"g_bw_ret2"],[10583232,"thunk_bw_sf_core"],[10583328,"thunk_bw_sf_14b"],[10583344,"thunk_bw_sf_12p"],[10583360,"thunk_bw_sf_12b"],[10583376,"thunk_bw_sf_10b"],[10583392,"thunk_bw_boxsprite_hdr"],[10583568,"thunk_bw_farmzoom_entry"],[10583648,"thunk_bw_farmseed"],[10583808,"thunk_bw_farmzoomset"],[10583872,"thunk_bw_farmiconadv"],[10583936,"thunk_frame_enlarge"],[10584224,"thunk_draw2_clipkey"],[10585200,"thunk_filedlg_railscale"],[10585600,"thunk_bw_farmorb_mono"],[10585648,"thunk_bw_farmorb_sd2a"],[10585696,"thunk_bw_farmorb_sd2b"],[10585888,"thunk_bw_btnfont"],[10585952,"thunk_bw_farmorb_sbc"],[10586112,"thunk_btn_bandstripe"],[10586624,"thunk_chev_coverage"],[10587456,"thunk_t16_measure_native"],[10587520,"g_chev_lut"],[10588032,"g_chev_scratch"],[10588448,"thunk_bw_striprects"],[10589440,"thunk_hud_vehargs"],[10589584,"g_bwsc_ret"],[10589588,"g_bwsc_tmp"],[10589592,"g_bwsc_flags"],[10589596,"t_bar2a"],[10589632,"t_bar2b"],[10589672,"t_bar2c"],[10589712,"t_bardec"],[10589748,"t_barthresh"],[10589852,"t_chev_btn2"],[10589960,"t_chev_btn3"],[10590012,"t_findfont"],[10590072,"t_flash_ghost5"],[10590152,"t_flash_name41"],[10590184,"t_flash_pic28"],[10590220,"t_flash_union6"],[10590272,"t_fontinit"],[10590304,"t_garr_adv5"],[10590340,"t_garr_cell38"],[10590372,"t_garr_fitdiv"],[10590404,"t_garr_sq1"],[10590444,"t_garr_sq5"],[10590480,"t_garr_stats38"],[10590512,"t_garr_statsy"],[10590568,"t_info_btnframe"],[10590612,"t_info_pad"],[10590644,"t_info_titleb"],[10590676,"t_mov_eax_s2"],[10590704,"t_mov_eax_s3"],[10590732,"t_mov_eax_s5"],[10590760,"t_mov_ebx_s3"],[10590788,"t_mov_ecx_s2"],[10590816,"t_mov_edx_s2"],[10590844,"t_pop_c30"],[10590880,"t_pop_inner3"],[10590956,"t_pop_ratio"],[10591012,"t_prod_ghost5"],[10591068,"t_prod_iconsz"],[10591136,"t_prod_iconxy"],[10591172,"t_prod_inner3"],[10591248,"t_prod_name41b"],[10591284,"t_prod_name41c"],[10591320,"t_prod_pic28"],[10591356,"t_prod_union6"],[10591396,"t_qrow_h_eax"],[10591456,"t_qrow_h_ecx"],[10591516,"t_sf_strip"],[10591588,"t_spotck_nat"],[10591644,"t_sup_cell"],[10591676,"t_sup_fit1"],[10591712,"t_sup_fit2"],[10591748,"t_sup_icon1"],[10591780,"t_sup_icon2"],[10591812,"t_sup_row"],[10591844,"t_sup_scale"],[10591900,"t_tilepick_nat"],[10592256,"thunk_staple_coverage"],[10593120,"g_staple_scratch"],[10595424,"thunk_bw_supprect"],[10595536,"thunk_hud_arrowseeds"],[10595712,"thunk_supsb_dragfix"],[10595744,"thunk_ksb_v2"],[10595904,"thunk_sb_dragfree"],[10595936,"thunk_bw_box2ring"],[10596080,"thunk_bw_box2"],[10596208,"thunk_bw_popbox_pads"],[10596256,"thunk_bw_popbox_text"],[10596304,"g_ring_rect"],[10596352,"thunk_arrow_coverage"],[10597216,"g_arrow_scratch"],[10597728,"thunk_ol8_calc_ratio"],[10597776,"thunk_ol8_draw_ratio"],[10597824,"thunk_ol8_box_ratio"],[10597872,"thunk_ol8_gap"],[10597904,"thunk_ol8_textx"],[10597936,"thunk_hollow_keyint"],[10598816,"thunk_ol8_selbottom"],[10598880,"g_ol8_ret"],[10599312,"thunk_orn_childx"],[10599392,"thunk_pf_union_align"],[10599856,"thunk_pp_layout"],[10599936,"thunk_pp_font"],[10599984,"thunk_pp_font10"],[10600032,"thunk_pp_btn"],[10600224,"thunk_pp_measure"],[10600448,"thunk_fe_pair_remap"],[10601472,"thunk_rail_ytop"],[10601536,"thunk_rail_hstep"],[10601568,"thunk_rail_bufh"],[10601696,"thunk_rail_sbfit"],[10601824,"thunk_sb_arrowfit"],[10601904,"thunk_sb_restripe"],[10602032,"g_sb_cur"],[10602036,"g_rm_f0ovr"],[10602040,"g_rm_f0"],[10602044,"g_rm_f0col"],[10602048,"g_ed_stamp"],[10602052,"g_ed_cw"],[10602056,"g_ed_ch"],[10602060,"g_ed_rs"],[10602064,"g_ed_p3"],[10602068,"g_ed_palu"],[10602084,"g_ed_redu"],[10602100,"g_ed_info"],[10602112,"g_vp_done"],[10602116,"g_vp_old"],[10602120,"g_ed_cred"],[10602140,"g_ed_fl"],[10602148,"g_ed_w"],[10602152,"g_ed_h"],[10602156,"g_ed_pp"],[10602160,"g_ed_maxrun"],[10602164,"g_ed_hn"],[10602168,"g_ed_top"],[10602176,"g_ed_str_k32"],[10602192,"g_ed_str_vp"],[10602208,"thunk_ed_linestep"],[10602240,"thunk_diplo_bracket"],[10602288,"thunk_diplo_btnfont"],[10602352,"thunk_ed_painter"],[10602544,"thunk_ed_seeds"],[10603056,"thunk_ed_immfix"],[10603232,"g_ed_immtab"],[10603616,"thunk_ed_remap"],[10604528,"thunk_diplo_pdsclear"],[10604544,"thunk_q16_fill_width"],[10604704,"thunk_s54_restripe"],[10605056,"thunk_rail_gate"],[10605088,"thunk_railout_hstep"],[10605152,"g_rail_sb"],[10605156,"g_rail_ret"],[10605160,"g_rr_dst"],[10605164,"g_rr_x"],[10605168,"g_rr_y"],[10605172,"g_rr_w"],[10605176,"g_rr_h"],[10605184,"thunk_rail_bake"],[10605568,"thunk_sbarrow_bg"],[10605760,"g_ab_w"],[10605764,"g_ab_h"],[10605824,"thunk_comm_rowrect"],[10605920,"g_dp_panel"],[10605936,"g_dp_logow"],[10605940,"g_dp_sepy"],[10605944,"g_dp_newsy"],[10605948,"g_dp_scr_news"],[10605952,"g_dp_scr_bio"],[10605968,"t_dp_table"],[10606736,"t_dp_box_centre"],[10606820,"t_dp_box_hqunion"],[10607000,"t_dp_box_panel"],[10607128,"t_dp_box_hq"],[10607180,"t_dp_c7_bio"],[10607264,"t_dp_c7_hq"],[10607364,"t_dp_sd2_bar"],[10607476,"t_dp_sd2_logo"],[10607604,"t_dp_sd2_hqpic"],[10607740,"t_dp_sd2_bezel"],[10607792,"t_dp_cent6"],[10607936,"t_dp_txt_wrap3"],[10608040,"t_dp_txt_wl3"],[10608112,"t_dp_news_sep"],[10608196,"t_dp_news_hline"],[10608264,"t_dp_news_t1"],[10608340,"t_dp_news_t2"],[10608424,"t_dp_news_t3"],[10608508,"t_dp_flinit_bio"],[10608564,"t_dp_flinit_news"],[10608640,"t_dp_flicdraw"],[10608916,"t_dp_pushw"],[10608944,"t_dp_movh"],[10608972,"t_dp_movex"],[10609004,"t_dp_frameL"],[10609036,"t_dp_frameR"],[10609068,"t_dp_calc_e4"],[10609108,"t_dp_calc_hdr"],[10609152,"t_dp_oky"],[10609184,"t_dp_q16fixed"],[10609248,"t_dp_knest"],[10609292,"t_dp_fill"],[10609408,"t_dp_title_outer"],[10609576,"t_dp_title_inner"],[10609772,"t_dp_title_text"],[10609968,"t_dp_textblock"],[10610144,"t_dp_boxw_gate"],[10610176,"t_dp_growbox_gate"],[10610208,"t_dp_vcenter_gate"],[10610240,"t_dp_childx_gate"],[10610268,"t_dp_q16gate"],[10610288,"t_dp_wrapwidth"],[10610408,"t_dp_artalign"],[10610512,"t_dp_itemrect"],[10610576,"g_cr_buf"],[10610580,"g_cr_L"],[10610584,"g_cr_R"],[10610588,"g_cr_B"],[10610592,"g_cr_armed"],[10610608,"t_cr_snap"],[10610864,"t_cr_tile"],[10611008,"g_council_active"],[10611012,"g_cw_vpdone"],[10611016,"g_cw_vpold"],[10611020,"g_flag_ret"],[10611024,"g_cw_seedtab"],[10611120,"g_cw_chipscr"],[10611216,"g_title_bottom"],[10611220,"g_fp_ornart"],[10611712,"g_flag_lut"],[10612224,"g_cw_immtab"],[10612896,"thunk_cw_enter"],[10612944,"thunk_cw_immfix"],[10613104,"thunk_cw_seeds"],[10613520,"thunk_cw_texty"],[10613600,"thunk_parity_reblit"],[10614096,"thunk_cw_portrait"],[10614208,"thunk_cw_logo"],[10614336,"thunk_cw_backdrop37"],[10614384,"thunk_cw_chip"],[10614672,"thunk_gv_arthead"],[10614784,"thunk_gv_frameskip"],[10614864,"thunk_flag_restripe"],[10615248,"thunk_sd_reblit_wrap"],[10615344,"thunk_popup_fieldpads"],[10616832,"g_se_vpdone"],[10616836,"g_se_vpold"],[10616840,"g_se_sprg"],[10616848,"g_se_immtab"],[10618368,"g_se_sprsave"],[10619392,"g_se_lockplane"],[10624000,"thunk_se_enter"],[10624016,"thunk_se_immfix"],[10624320,"thunk_se_stripe_top"],[10624352,"thunk_se_sprites"],[10624464,"thunk_se_tiles"],[10624784,"thunk_se_locks"],[10625664,"thunk_se_transform"],[10627200,"thunk_se_sd2"],[10627232,"thunk_se_rr_row"],[10627312,"thunk_se_rr_col"],[10627392,"thunk_se_stripe_px"],[10627408,"thunk_se_rowdraw"],[10628512,"thunk_btn_gate_pre"],[10628608,"g_tech_vpdone"],[10628612,"g_tech_vpold"],[10628624,"g_tech_rbrect"],[10628640,"g_tech_ficache"],[10628768,"g_tech_scratchfont"],[10628864,"g_tech_ffcache"],[10629376,"g_tech_immtab"],[10630144,"thunk_tech_enter"],[10630160,"thunk_tech_immfix"],[10630384,"thunk_tech_inset"],[10630448,"thunk_tech_n8"],[10630464,"thunk_tech_n8ch"],[10630496,"thunk_tech_rb1"],[10630576,"thunk_tech_calib"],[10630736,"thunk_tech_fi"],[10630896,"thunk_tech_ff"],[10631104,"thunk_dw_enter"],[10631152,"thunk_dw_immfix"],[10631440,"thunk_dw_leave"],[10631456,"thunk_dw_pk_enter"],[10631520,"thunk_dw_pk_leave"],[10631584,"thunk_dw_cell"],[10631712,"thunk_dw_click"],[10631792,"thunk_dw_frame"],[10631824,"thunk_dw_bm"],[10631904,"thunk_dw_restripe"],[10632224,"thunk_dw_pickcell"],[10632384,"thunk_dw_container"],[10632496,"thunk_dw_tilecell"],[10632608,"thunk_dw_slotcell"],[10632768,"thunk_dw_btndraw"],[10632816,"thunk_dw_btnface"],[10633920,"thunk_dw_ssaa"],[10635152,"thunk_dw_shim"],[10635328,"thunk_dw_ovl"],[10635392,"thunk_dw_ewin"],[10635440,"thunk_dw_eovl"],[10635472,"thunk_dw_ehalfa"],[10635520,"thunk_dw_ehalfb"],[10635552,"thunk_dw_fp"],[10635680,"thunk_dw_fp2"],[10635792,"thunk_dw_fpset"],[10636064,"thunk_dw_clip"],[10636144,"thunk_dw_resetguard"],[10636240,"thunk_dw_fit"],[10636944,"thunk_dw_axismap"],[10637168,"thunk_dw_backdrop"],[10638464,"thunk_dw_build"],[10638480,"thunk_dw_build2"],[10638512,"thunk_dw_gridleave"],[10638544,"thunk_lbres_ecx"],[10638592,"thunk_lbres_eax"],[10638640,"thunk_lbres_ebp"],[10638688,"thunk_lbres_edx"],[10638736,"thunk_dw_sbv"],[10638784,"thunk_dw_hide"],[10638832,"thunk_wheel_down"],[10639072,"thunk_wheel_up"],[10641408,"g_dw_vpdone"],[10641412,"g_dw_vpold"],[10641416,"g_dw_fitw"],[10641420,"g_dw_fitoff"],[10641424,"g_dw_pickcanvas"],[10641428,"g_dw_ssaaw"],[10641432,"g_dw_gated"],[10641436,"g_dw_fpgated"],[10641440,"g_dw_ovl"],[10641456,"g_dw_fp"],[10641504,"g_dw_pk_ret"],[10641508,"g_dw_pk_armed"],[10641512,"g_dw_ret1"],[10641516,"g_dw_ret2"],[10641520,"g_dw_ret3"],[10641524,"g_dw_ret4"],[10641528,"g_dw_active"],[10641532,"g_dw_exec_ret"],[10641536,"g_dw_bmrect"],[10641552,"g_dw_rect2"],[10641568,"g_dw_busy"],[10641572,"g_dw_cv"],[10641576,"g_dw_zoom"],[10641580,"g_dw_ecx"],[10641584,"g_dw_ss"],[10641664,"g_dw_snap"],[10641920,"g_dw_immtab"],[10643968,"g_dw_cands"],[10644992,"g_dw_present"],[10645504,"g_dw_bd"],[10653696,"g_dw_cache"],[10733312,"thunk_pf_frame_align"],[10733648,"t_dp_q16anch"],[10733728,"thunk_pf_textfollow"],[10733872,"thunk_tutwin_ctop"]];
  function nearest(a) {
    if (a < 0x401000 || a > 0xA30000) return null;
    let lo = 0, hi = SYMS.length - 1, best = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (SYMS[m][0] <= a) { best = m; lo = m + 1; } else hi = m - 1; }
    if (best < 0) return "0x" + a.toString(16);
    const d = a - SYMS[best][0];
    return (d < 0x2000 ? SYMS[best][1] + "+0x" + d.toString(16) : "0x" + a.toString(16));
  }
  globalThis.WP = { armed: false, addrs: [], hits: 0 };
globalThis.DIAG_WP = false; globalThis.DIAG_HEAP = false; globalThis.DIAG_REGS = false; globalThis.DIAG_FREE = false;   // v12k diag-off flags; v12l: globalThis (the const sat in a nested scope -> load-time ReferenceError at the DIAG_FREE gate killed the rest of the script = vanilla menu + per-callback errors)
  globalThis.nearestSym = nearest;
  Process.setExceptionHandler(function (details) {
    if (globalThis.WP.armed && details.type !== "access-violation") {
      try {
        const c = details.context; const eip0 = c.eip.toInt32() >>> 0;
        if (eip0 >= 0x70000000) return true;                         // exception-dispatcher artifacts
        globalThis.WP.hits++;
        if (globalThis.WP.hits <= 200) {
          const eip = c.eip.toInt32() >>> 0; let st = [];
          for (let i = 0; i < 0x30; i++) { let v; try { v = c.esp.add(i * 4).readU32(); } catch (e) { break; } const n = nearest(v); if (n && !n.startsWith("0x")) st.push(n); }
          log("[WP] write at eip=0x" + eip.toString(16) + " " + (nearest(eip) || "") + " watched=" + globalThis.WP.addrs.map(a => "0x" + a.readU32().toString(16)).join(",") + " eax=" + c.eax + " ecx=" + c.ecx + " edx=" + c.edx + " esi=" + c.esi + " edi=" + c.edi + " stack: " + st.slice(0, 8).join(" < "));
        }
      } catch (e) { log("[WP] err " + e); }
      return true;
    }
    if (details.type !== "access-violation") return false;
    try {
      const c = details.context;
      const eip = c.eip.toInt32() >>> 0;
      let sym = ""; try { sym = DebugSymbol.fromAddress(c.eip).toString(); } catch (e) { }
      log("=== ACCESS VIOLATION (dl_scale_proto v11g) === eip=0x" + eip.toString(16) + " " + sym + " op=" + details.memory.operation + " at " + details.memory.address);
      log("  eax=" + c.eax + " ebx=" + c.ebx + " ecx=" + c.ecx + " edx=" + c.edx + " esi=" + c.esi + " edi=" + c.edi + " ebp=" + c.ebp + " esp=" + c.esp);
      try { log("  bytes@eip: " + Array.from(new Uint8Array(c.eip.readByteArray(16))).map(b => b.toString(16).padStart(2, "0")).join(" ")); } catch (e) { }
      try { log("  bytes@edi: " + Array.from(new Uint8Array(c.edi.readByteArray(16))).map(b => b.toString(16).padStart(2, "0")).join(" ")); } catch (e) { }
      const lines = [];
      for (let i = 0; i < 0xC0; i++) {
        let v; try { v = c.esp.add(i * 4).readU32(); } catch (e) { break; }
        const n = nearest(v);
        let ns = ""; if (v >= 0x77000000) { try { ns = DebugSymbol.fromAddress(ptr(v)).toString(); } catch (e) { } }
        if (n || ns) lines.push("[esp+0x" + (i * 4).toString(16) + "]=0x" + v.toString(16) + " " + (n || ns));
      }
      for (const l of lines) log("  " + l);
    } catch (e) { log("AV handler error: " + e); }
    return false;
  });
})();

if (requireBase()) {
  if (!globalThis.SL) { log("FATAL: scaling_laws.js (globalThis.SL) not loaded — use run-frida-at-res.bat"); }
  const G_OBJ = 0x703EA0, G_MAINWIN = 0x7AE820, G_MAINBUF = 0x7AEC64;
  const G_SCREENW = 0x9B7B1C, G_SCREENH = 0x9B7B20, G_STRIPH = 0x7AF59C, G_SCALE = 0x668740;
  const A_EXEC = 0x429180, A_BUILD = 0x429300, A_DRAWPAGE = 0x42BF10, A_SHOWHIDE = 0x432060;
  const PCAVE2 = 0xA0C000, G_NETWIN_ACTIVE = PCAVE2 + 0x4800;   // netwin scrollbar lever flag
  const WING_FACES = [0x78D960, 0x78D988, 0x78D9B0];             // box-sprite face set of the 16 wing buttons
  const OBJ = VA(G_OBJ);

  function safeS32(p, d) { try { return p.readS32(); } catch (e) { return (d === undefined ? -0x7fffffff : d); } }
  function safeU32(p) { try { return p.readU32(); } catch (e) { return 0; } }
  function rect4(p) { return [safeS32(p), safeS32(p.add(4)), safeS32(p.add(8)), safeS32(p.add(12))]; }
  function rstr(p) { const r = rect4(p); return "(" + r.join(",") + ") [" + (r[2] - r[0]) + "x" + (r[3] - r[1]) + "]"; }
  function hex(v) { return "0x" + (v >>> 0).toString(16); }
  function gval() { return safeS32(VA(G_SCALE), -1); }
  const G_PALETTE = 0x94C590;
  function pal(i) { const p = VA(G_PALETTE).add((i & 0xff) * 4); const v = safeU32(p); return [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff]; }
  function envStr() { return "ScreenW=" + safeS32(VA(G_SCREENW)) + " ScreenH=" + safeS32(VA(G_SCREENH)) + " g=" + gval() + " stripH=" + safeS32(VA(G_STRIPH)); }

  let g = 16;
  const s = v => SL.scalePx(v, g);

  // ---------------------------------------------------------------------------
  // Immediate patch table: [addr, immOff, width(1|4), value-fn, label]. Every value-fn carries
  // .nat = the NATIVE immediate the site must hold (verified before writing).
  // ---------------------------------------------------------------------------
  const S   = a => Object.assign(() => s(a), { nat: a });
  const NEG = a => Object.assign(() => -s(a), { nat: -a });
  const S2   = a => Object.assign(() => 2 * s(a), { nat: 2 * a });
  const NEG2 = a => Object.assign(() => -2 * s(a), { nat: -2 * a });
  const S3   = a => Object.assign(() => 3 * s(a), { nat: 3 * a });
  const SD   = (a, b) => Object.assign(() => s(a) - s(b), { nat: a - b });
  const FLOAT = z => Object.assign(() => z * g / 16, { nat: z, isFloat: true });
  const VEH  = sz => Object.assign(() => (SL.vehSizeScaled ? SL.vehSizeScaled(sz, g) : (g <= 16 ? sz : (((sz + 16) * g) >> 4) - 16)), { nat: sz });
  const NUMG = () => Object.assign(() => g, { nat: 1 });
  const DEN16 = () => Object.assign(() => 16, { nat: 1 });
  const NAT  = v => Object.assign(() => v, { nat: v });
  const P = [];
  const add = (addr, off, w, fn, label) => P.push({ addr, off, w, fn, label });
  const skip = (addr, off, w, fn, label) => {};                                   // verify-only rows (leave native)
  const RAW = [];                                                                  // [addr, nativeBytes, newBytes, label]
  const raw = (addr, nat, nu, label) => RAW.push({ addr, nat, nu, label });

  // --- W window law ---
  add(0x42938B, 1, 4, S(0x2E2), "window h 738 (h = s(738) - strip)");
  add(0x429390, 3, 4, S(0x8A), "ofs base 0x8A (list/text/button y extension)");
  add(0x42939F, 1, 4, NEG(800), "window x: (SW - s(800))/2");
  add(0x42958C, 1, 4, S(0x340), "window w 832");
  // --- R rect seeds (builder 0x4293E8..0x4294D1) ---
  add(0x4293E8, 2, 4, S(0x143), "list bottom +0x143 (+ofs)");
  add(0x4293F1, 1, 4, S(7), "title T 7 (list_title + title_rect)");
  add(0x4293F6, 1, 4, S(0xE6), "list R 0xE6");
  add(0x4293FB, 6, 4, S(0x1E), "list_title L 0x1E");
  add(0x429411, 6, 4, S(0x1B), "list_title B 0x1B");
  add(0x42942C, 6, 4, S(0x1E), "list_box L 0x1E");
  add(0x429436, 6, 4, S(0x1D), "list_box T 0x1D");
  add(0x429440, 6, 4, S(0xF8), "art_box L 0xF8");
  add(0x42944A, 6, 4, S(0x2C), "art_box T 0x2C");
  add(0x429454, 6, 4, S(0x177), "art_box R 0x177");
  add(0x42945E, 6, 4, S(0xAB), "art_box B 0xAB");
  add(0x429470, 1, 4, S(0x302), "title/text R 0x302");
  add(0x429475, 6, 4, S(0xDB), "title L 0xDB (overwritten by list.R+9)");
  add(0x42947F, 2, 4, S(0xB4), "text_upper B 0xB4 (+ofs/2)");
  add(0x42948B, 6, 4, S(0x22), "title B 0x22");
  add(0x429498, 2, 4, S(0xB6), "text_lower T 0xB6 (+ofs/2)");
  add(0x4294A4, 2, 4, S(0xDB), "text_upper L 0xDB");
  add(0x4294AA, 3, 4, S(0x24), "text_upper T 0x24");
  add(0x4294B1, 3, 4, S(0x8D), "text_lower B 0x8D (+T+ofs/2)");
  add(0x4294BB, 2, 4, S(0xDB), "text_lower L 0xDB");
  add(0x4294D1, 2, 1, S(9), "title L = list.R + 9");
  add(0x429537, 1, 4, S(3), "right container +3 (R/B)");
  add(0x42953E, 2, 1, NEG(3), "right container -3 (L)");
  add(0x42954E, 2, 1, NEG(3), "right container -3 (T)");
  // --- B wing button rows (left loop 0x4295C9.., right loop 0x42963E..) ---
  const BOT = Object.assign(() => s(3) + 1, { nat: 4 });                       // sub eax,4 -> face bottom = B - s(3)
  const TOPD = Object.assign(() => -(s(25) - s(3) - 1), { nat: -0x15 });        // lea [eax-0x15] -> face top = B - s(25)
  add(0x4295C9, 2, 1, S(4), "L wing R-4");   add(0x4295CC, 2, 1, BOT, "L wing bottom inset");
  add(0x4295D2, 2, 1, S(4), "L wing L+4");   add(0x4295D5, 2, 1, TOPD, "L wing top -21");
  add(0x429609, 1, 4, S(0x18), "L wing pitch 24");
  add(0x42963E, 2, 1, BOT, "R wing bottom inset"); add(0x429641, 2, 1, S(4), "R wing R-4");
  add(0x429644, 2, 1, S(4), "R wing L+4");         add(0x42964A, 2, 1, TOPD, "R wing top -21");
  add(0x429685, 1, 4, S(0x18), "R wing pitch 24");
  // --- BACK / EXIT ---
  add(0x4296A3, 6, 4, S(0x98), "BACK L 0x98");    add(0x4296AD, 6, 4, S(0x18E), "BACK R 0x18E");
  add(0x4296B9, 2, 4, S(0x14E), "buttons T 0x14E (+ofs)");
  add(0x4296C5, 2, 1, S(0x14), "buttons h 0x14 (lea)");  add(0x4296D4, 2, 1, S(0x14), "buttons h 0x14 (add)");
  add(0x4296D7, 6, 4, S(0x192), "EXIT L 0x192");  add(0x4296EC, 6, 4, S(0x288), "EXIT R 0x288");
  // --- F fonts (1024 branch 0x4297EB..0x4298C8; push imm8 size) ---
  add(0x4297F0, 1, 1, S(14), "F9 size 14");   add(0x429806, 1, 1, S(14), "F10 size 14");
  add(0x42981C, 1, 1, S(18), "F0 size 18");   add(0x429831, 1, 1, S(14), "F2 size 14");
  add(0x429847, 1, 1, S(14), "F3 size 14");   add(0x42985C, 1, 1, S(14), "F4 size 14");
  add(0x429872, 1, 1, S(14), "F5 size 14");   add(0x429887, 1, 1, S(14), "F6 size 14");
  add(0x42989D, 1, 1, S(14), "F8 size 14");   add(0x4298B2, 1, 1, S(12), "F7 size 12");
  add(0x4298C8, 1, 1, S(14), "F1 size 14 (list rows)");
  // --- build-time draws + container insets ---
  add(0x429A43, 3, 4, S(0x17), "d690 backdrop L 0x17");  add(0x429A51, 3, 4, S(0x309), "d690 backdrop R 0x309");
  add(0x429A91, 1, 4, S(3), "button container inset 3");
  add(0x429AF1, 1, 4, S(3), "list container inset 3");
  add(0x429B5A, 1, 4, S(3), "list dialog inset 3");
  // --- T TextScroll attach insets ---
  for (const a of [0x429E3E, 0x429E41, 0x429E44, 0x429E47]) add(a, 2, 1, S(3), "TS_center inset 3 @" + hex(a));
  for (const a of [0x429EDA, 0x429EDD, 0x429EE0, 0x429EE3]) add(a, 2, 1, S(3), "TS_A inset 3 @" + hex(a));
  for (const a of [0x429F70, 0x429F73, 0x429F76, 0x429F79]) add(a, 2, 1, S(6), "TS_B inset 6 @" + hex(a));

  // --- v3: PAGE PAINTERS + TECH PAGE (work\_dl_painter_imms.js, verbatim) ---
add(0x42BFFF, 2, 1, S(0x17), "render_topic: d690 restore rect L = win.x-0x17  [MIXED SPACE: rect is built from the SCREEN rect +0x103C4; companion fix = disp32 0x103C4->0x474 @0x42BFF0+2, not a pixel imm]");
add(0x42C012, 2, 1, S(9),    "render_topic: d690 restore rect R = win.R-9 (win.R = x+0x340 lives in the rect, not an imm)");

// =====================================================================================
// B  16 list builders: category-title band = box_sprite(+0x103D4 copy, d618) then rect inset 3 (mov eax,3 imm32)
//    for write_cent_l_7 — one copy per builder (draw-state multiplicity)
// =====================================================================================
add(0x42A597, 1, 4, S(3), "list_all(2): title band inset 3");
add(0x42A704, 1, 4, S(3), "list_units(3): title band inset 3");
add(0x42A86A, 1, 4, S(3), "list_chassis(4): title band inset 3");
add(0x42A9D0, 1, 4, S(3), "list_reactor(5): title band inset 3");
add(0x42AB30, 1, 4, S(3), "list_weapon(6): title band inset 3");
add(0x42AC90, 1, 4, S(3), "list_armor(7): title band inset 3");
add(0x42ADF0, 1, 4, S(3), "list_ability(8): title band inset 3");
add(0x42AF4F, 1, 4, S(3), "list_facility(10): title band inset 3");
add(0x42B102, 1, 4, S(3), "list_project(11): title band inset 3");
add(0x42B26B, 1, 4, S(3), "list_tech(14): title band inset 3");
add(0x42B3FD, 1, 4, S(3), "list_concept(0): title band inset 3");
add(0x42B5A0, 1, 4, S(3), "list_advconcept(1): title band inset 3");
add(0x42B74E, 1, 4, S(3), "list_society(12): title band inset 3");
add(0x42B8AA, 1, 4, S(3), "list_effect(13): title band inset 3");
add(0x42BA19, 1, 4, S(3), "list_faction(15): title band inset 3");
add(0x42BC29, 1, 4, S(3), "list_terraform(9): title band inset 3");

// =====================================================================================
// P0/P1 concept 0x42C2E0 / advconcept 0x42C650: NO pixel immediates (title -> +0x10364, text -> TextScroll[0])
// =====================================================================================

// ---- P3 unit 0x42C9C0 ----
add(0x42CA3A, 2, 1, S(6), "unit: stats x0 = upper.L+6");
add(0x42CA49, 2, 1, S(6), "unit: stats y0 = upper.T+6");
add(0x42CA52, 2, 1, S(6), "unit: stats xR = upper.R-6");
add(0x42CAA9, 1, 1, VEH(4), "unit: veh_draw size index 4 (icon at art_box L,T; dest = DL canvas so thunk_hud_vehargs does NOT cover it)");
add(0x42CB55, 3, 1, S(3), "unit: stats x = x0 + art_box.w + 3");

// ---- P4 chassis 0x42D610 ----
add(0x42D693, 2, 1, S(6), "chassis: stats x0 = upper.L+6");
add(0x42D6A2, 2, 1, S(6), "chassis: stats xR = upper.R-6");
add(0x42D6B4, 2, 1, S(6), "chassis: stats y0 = upper.T+6");
add(0x42D6D9, 1, 'f', FLOAT(0.1), "chassis: Caviar_set_zoom 0.1  [ALT: reuse thunk_dw_fit gated on dst=DL canvas — see .md]");
add(0x42D7C0, 3, 1, S(3), "chassis: stats x = x0 + art_box.w + 3");

// ---- P5 reactor 0x42DEF0 ----
add(0x42DF70, 2, 1, S(6), "reactor: stats x0 = upper.L+6");
add(0x42DF7F, 2, 1, S(6), "reactor: stats xR = upper.R-6");
add(0x42DFA2, 2, 1, S(6), "reactor: stats y0 = upper.T+6");
add(0x42DFB8, 1, 'f', FLOAT(0.2), "reactor: Caviar_set_zoom 0.2  [ALT: thunk_dw_fit]");
add(0x42E09C, 3, 1, S(3), "reactor: stats x = x0 + art_box.w + 3");

// ---- P6 weapon 0x42E2E0 ----
add(0x42E363, 2, 1, S(6), "weapon: stats x0 = upper.L+6");
add(0x42E36C, 2, 1, S(6), "weapon: stats y0 = upper.T+6");
add(0x42E37B, 2, 1, S(6), "weapon: stats xR = upper.R-6");
add(0x42E3E7, 1, 'f', FLOAT(0.3), "weapon: Caviar_set_zoom 0.3 (mode<3)  [ALT: thunk_dw_fit]");
add(0x42E3EE, 1, 'f', FLOAT(0.2), "weapon: Caviar_set_zoom 0.2 (mode>=3)  [ALT: thunk_dw_fit]");
add(0x42E3F5, 1, 'f', FLOAT(0.1), "weapon: Caviar_set_zoom 0.1 (weapon 0x10/0x17)  [ALT: thunk_dw_fit]");
add(0x42E4E6, 3, 1, S(6), "weapon: stats x = x0 + art_box.w + 6");

// ---- P7 armor 0x42E8E0 ----
add(0x42E963, 2, 1, S(6), "armor: stats x0 = upper.L+6");
add(0x42E96C, 2, 1, S(6), "armor: stats y0 = upper.T+6");
add(0x42E975, 2, 1, S(6), "armor: stats xR = upper.R-6");
add(0x42E9C5, 3, 'f', FLOAT(0.15), "armor: zoom 0.15 (armor 8) mov [ebp-0x10],imm  [ALT: thunk_dw_fit]");
add(0x42E9CE, 3, 'f', FLOAT(0.2),  "armor: zoom 0.2 (others) mov [ebp-0x10],imm  [ALT: thunk_dw_fit]");
add(0x42EAFC, 3, 1, S(3), "armor: stats x = x0 + art_box.w + 3");

// ---- P8 ability 0x42EE30 (text only) ----
add(0x42EEB6, 2, 1, S(6), "ability: stats x0 = upper.L+6");
add(0x42EEC2, 2, 1, S(6), "ability: stats y0 = upper.T+6");
add(0x42EED1, 2, 1, S(6), "ability: stats xR = upper.R-6");

// ---- P9 terraform 0x431180 (55-px tile composite in text_upper) ----
skip(0x4311B2, 1, 4, NAT(0x37), "terraform: Texture_draw SOURCE quad {0,0}-{55,55} (texture space) — leave native");
add(0x431208, 2, 1, S(5),    "terraform: x0 = upper.L+5 (tile/diamond left, stats x)");
add(0x431211, 2, 1, S(5),    "terraform: y0 = upper.T+5 (diamond top row)");
add(0x43121D, 2, 1, S(5),    "terraform: xR = upper.R-5 (stats width)");
add(0x431229, 2, 1, S(0x32), "terraform: diamond top/bottom vertex x = x0+50");
add(0x431232, 2, 1, S(0x32), "terraform: diamond left/right vertex y = y0+50");
add(0x431235, 2, 1, S(0x19), "terraform: diamond top vertex y = y0+25 (also the tile sprite y)");
// [v4: handled by REGFIX attach — see below] 0x431238
// [v4: handled by REGFIX attach — see below] 0x431250
// 13 tile Sprite_draw_2 sites: first push = scaleDen, second = scaleNum (native 1:1 -> g:16)
add(0x43130E, 1, 1, DEN16(), "terraform: tile 0x7A6860 den");  add(0x431310, 1, 1, NUMG(), "terraform: tile 0x7A6860 num");
add(0x431342, 1, 1, DEN16(), "terraform: tile 0x79A710 den");  add(0x431344, 1, 1, NUMG(), "terraform: tile 0x79A710 num");
add(0x43137B, 1, 1, DEN16(), "terraform: tile 0x776A50 den");  add(0x43137D, 1, 1, NUMG(), "terraform: tile 0x776A50 num");
add(0x4313AF, 1, 1, DEN16(), "terraform: tile 0x789B68 den");  add(0x4313B1, 1, 1, NUMG(), "terraform: tile 0x789B68 num");
add(0x4313E8, 1, 1, DEN16(), "terraform: tile 0x7991F8 den");  add(0x4313EA, 1, 1, NUMG(), "terraform: tile 0x7991F8 num");
add(0x43141C, 1, 1, DEN16(), "terraform: tile 0x78A5B0 den");  add(0x43141E, 1, 1, NUMG(), "terraform: tile 0x78A5B0 num");
add(0x4314D4, 1, 1, DEN16(), "terraform: tile 0x7AD010 den");  add(0x4314D6, 1, 1, NUMG(), "terraform: tile 0x7AD010 num");
add(0x431508, 1, 1, DEN16(), "terraform: tile 0x7ACC60 den");  add(0x43150A, 1, 1, NUMG(), "terraform: tile 0x7ACC60 num");
add(0x43153C, 1, 1, DEN16(), "terraform: tile 0x7A6830 den");  add(0x43153E, 1, 1, NUMG(), "terraform: tile 0x7A6830 num");
add(0x4315CD, 1, 1, DEN16(), "terraform: tile 0x779390 den");  add(0x4315CF, 1, 1, NUMG(), "terraform: tile 0x779390 num");
add(0x431601, 1, 1, DEN16(), "terraform: tile 0x7ABF60 den");  add(0x431603, 1, 1, NUMG(), "terraform: tile 0x7ABF60 num");
add(0x431635, 1, 1, DEN16(), "terraform: tile 0x78DD20 den");  add(0x431637, 1, 1, NUMG(), "terraform: tile 0x78DD20 num");
add(0x43168F, 1, 1, DEN16(), "terraform: tile 0x75B098 den");  add(0x431691, 1, 1, NUMG(), "terraform: tile 0x75B098 num");
// [v4: handled by REGFIX attach — see below] 0x4316B3
add(0x43194A, 2, 1, S(5),    "terraform: lower text x = lower.L+5");
add(0x431950, 2, 1, S(5),    "terraform: lower text y = lower.T+5");
add(0x431956, 2, 1, S(5),    "terraform: lower text xR = lower.R-5");
// [v4: handled by REGFIX attach — see below] 0x43196C

// ---- P10 facility 0x42F490 ----
add(0x42F4DF, 2, 1, S(3), "facility: stats x0 = upper.L+3");
add(0x42F4E8, 2, 1, S(3), "facility: stats y0 = upper.T+3");
add(0x42F4F7, 2, 1, S(3), "facility: stats xR = upper.R-3");
add(0x42F5E9, 3, 1, S(6), "facility: stats x = x0 + art_box.w + 6  (Sprite_draw_2 @0x42F5CF num=art_box.w, den=[spr+0x18]: both non-imm)");
add(0x42F7CA, 2, 1, S(3), "facility: lower block x = lower.L+3");
add(0x42F7D6, 2, 1, S(3), "facility: lower block xR = lower.R-3");
add(0x42F7E4, 2, 1, S(3), "facility: lower block y = lower.T+3");

// ---- P11 project 0x42FAD0 ----
add(0x42FB1F, 2, 1, S(3), "project: stats x0 = upper.L+3");
add(0x42FB28, 2, 1, S(3), "project: stats y0 = upper.T+3");
add(0x42FB37, 2, 1, S(3), "project: stats xR = upper.R-3");
add(0x42FC26, 3, 1, S(6), "project: stats x = x0 + art_box.w + 6  (Sprite_draw_2 @0x42FC0C num=art_box.w, den=[0x759338]: non-imm)");
add(0x42FDCC, 2, 1, S(3), "project: lower block x = lower.L+3");
add(0x42FDD8, 2, 1, S(3), "project: lower block xR = lower.R-3");
add(0x42FDE6, 2, 1, S(3), "project: lower block y = lower.T+3");

// ---- P12 society model 0x430090 ----
add(0x4300FC, 2, 1, S(3),    "society: stats x0 = upper.L+3");
add(0x43010B, 2, 1, S(3),    "society: stats xR = upper.R-3");
add(0x430117, 2, 1, S(3),    "society: stats yB = upper.B-3");
add(0x43011A, 2, 1, S(3),    "society: stats y0 = upper.T+3");
add(0x430307, 2, 1, S(3),    "society: effect table L = lower.L+3");
add(0x430310, 2, 1, S(3),    "society: effect table T = lower.T+3");
add(0x430319, 2, 1, S(3),    "society: effect table R = lower.R-3");
add(0x430322, 2, 1, S(3),    "society: effect table B = lower.B-3");
add(0x430375, 2, 1, S(0x14), "society: 'no effects' text x indent 20 (write_l_4 rect)");
add(0x4303BB, 2, 1, S(0x14), "society: effect rows value column x = L+3+20 (write_right_l_5 / write_l_3)");

// ---- P13 society effect 0x430770 ----
add(0x4307BF, 2, 1, S(3), "effect: text x0 = upper.L+3");
add(0x4307CE, 2, 1, S(3), "effect: text y0 = upper.T+3");
add(0x4307DD, 2, 1, S(3), "effect: text xR = upper.R-3");

// ---- P15 faction 0x430C80 ----
add(0x430CCF, 2, 1, S(5),   "faction: portrait x = text_panel.L+5");
add(0x430CD8, 2, 1, S(5),   "faction: portrait y = text_panel.T+5");
add(0x430CE7, 2, 1, S(5),   "faction: text xR = text_panel.R-5");
// [v3 proto: portrait kept 1:1 — text x adds the native width] add(0x430D7A, 1, 1, DEN16(), "faction: portrait Sprite_draw_2 den (1:1 -> g:16)");
// [v3 proto: portrait kept 1:1 — text x adds the native width] add(0x430D7E, 1, 1, NUMG(),  "faction: portrait Sprite_draw_2 num");
add(0x430DB8, 3, 1, S(5),   "faction: profile text x = portrait x + [spr+0x18] + 5  ([spr+0x18] is the NATIVE portrait width: needs a lever, see .md)");
add(0x430DFE, 6, 4, S(0x14), "faction: DL canvas Buffer+0x10 = 20 (paragraph first-line indent for write_strings)");

// =====================================================================================
// T  ReportWin_tech_page 0x498B30 — DATALINKS-MODE branch (0x498B90..0x498C55) + the mode-shared tail
//    (ecx = ReportWin_g 0x876478; RW+ = ReportWin field; card/buttons drawn INTO the DL canvas)
// =====================================================================================
add(0x498B9B, 2, 1, S(3),          "tech: T+3 (local_5c)");
add(0x498B9E, 6, 4, S(0x96),       "tech: btn_w 150 -> [RW+0x59A0]");
add(0x498BA8, 2, 1, S(3),          "tech: L+3 (local_60 = column base x)");
add(0x498BAB, 6, 4, S(0x28),       "tech: btn_h 40 -> [RW+0x59A4]");
add(0x498BB5, 2, 1, SD(0x17, 3),   "tech: content top = (T+3)+0x14 = T+0x17 (local_54)");
add(0x498BB8, 6, 4, S(0xAA),       "tech: card_w 170 -> [RW+0x59A8]");
add(0x498BE2, 2, 1, SD(6, 3),      "tech: (L+3)+3 = L+6 (local_2c)");
add(0x498BE5, 2, 1, SD(6, 3),      "tech: (T+3)+3 = T+6 (local_28)");
add(0x498BFB, 3, 1, NEG2(3),       "tech: R-3 = (R-L)+(L+3)-6 (local_58 = column right edge)");
add(0x498C04, 2, 1, NEG2(3),       "tech: inner w = (R-L)-6 (local_24; unused on the DL path)");
add(0x498C07, 2, 1, S2(3),         "tech: inner h = (B-T)-6 (local_20; unused on the DL path)");
add(0x498C16, 2, 1, SD(0x21, 0x17), "tech: card T = T+0x17+0xA = T+0x21 -> [RW+0xA2C]");
add(0x498C26, 1, 4, S(0xB0),       "tech: card L = L+3 + ((R-L)-0xB0)/2  (centring span 0xB0 = card_w+6)");
add(0x498C3E, 1, 4, S(0xAA),       "tech: card R = card L + 0xAA -> [RW+0xA30]");
add(0x498C43, 2, 4, SD(0x111, 0x21), "tech: card B = T+0x21+0xF0 = T+0x111 -> [RW+0xA34]");
// --- mode-shared tail (runs in DL mode) ---
add(0x49953C, 3, 1, S(0xF),        "tech: y0 = [RW+0xE268] (font line h, NON-IMM) + content top + 15");
add(0x49954D, 2, 1, NEG(0x1E),     "tech: column h = [RW+0x5980] (ReportWin's OWN rect.B, NON-IMM) - y0 - 30 -> [RW+0xA20]  (add eax,-0x1E)");
add(0x49959D, 1, 4, NEG(200),      "tech DL SW!=800: column h -= 200 (-0xE6 total) before centring the button rows");
add(0x4995C9, 3, 1, S(0x10),       "tech DL: row below = y_mid + btn_h + 16 -> [RW+0x5960]");
add(0x4995CD, 2, 1, S(0x10),       "tech DL: row above = y_mid - btn_h - 16 -> [RW+0x595C]");
add(0x4995E8, 2, 4, S(200),        "tech DL SW!=800: column h += 200 (restore)");
add(0x49960B, 2, 1, S(0x10),       "tech: row pitch = btn_h + 16 (rows [RW+0x5964..])");
add(0x49964D, 3, 1, S(5),          "tech: column x_i = ((W-btn_w)*i)/2 - 5i + 5 + (L+3)");
// v12d: the -5i is the loop COUNTER [ebp-4] (add eax,5 / cmp eax,0xF / jl): scale the step AND its bound together so
//   the loop still runs 3x and the right column lands at cu.R - s(158) (user 1600 shot 013345: buttons crowding the
//   frame; engine cols: x2 = cu.R-241 @g25 / -380 @g40 vs vanilla 158 -> 247 / 395).
add(0x499657, 2, 1, S(5),          "tech: column loop step 5 -> s(5)  (add eax,5)");
add(0x49965A, 2, 1, S3(5),         "tech: column loop bound 15 -> 3*s(5)  (cmp eax,0xF)");
skip(0x499657, 2, 1, NAT(5),       "tech: column loop step 5 == the -5*i column shift (COUPLED with the bound below; do NOT scale alone)");
skip(0x49965A, 2, 1, NAT(0xF),     "tech: column loop bound 15 (3 columns) — loop control, leave native");
add(0x49967A, 2, 1, S(0x10),       "tech: [RW+0x5970] = y_mid + 1.5*(btn_h+16)");
// button d5a0 frames: L-3 / T-3 / R = L-3 + btn_w + 6 / B = T-3 + btn_h + 6  (6 draw sites)
add(0x499830, 2, 1, S(3),  "tech: btn 0x379 (solo) frame L-3");   add(0x499833, 2, 1, S(3),  "tech: btn 0x379 (solo) frame T-3");
add(0x49983B, 3, 1, S2(3), "tech: btn 0x379 (solo) frame w+6");   add(0x49984B, 3, 1, S2(3), "tech: btn 0x379 (solo) frame h+6");
add(0x499972, 2, 1, S(3),  "tech: btn 0x379 (pair) frame L-3");   add(0x499978, 2, 1, S(3),  "tech: btn 0x379 (pair) frame T-3");
add(0x49997B, 3, 1, S2(3), "tech: btn 0x379 (pair) frame w+6");   add(0x49998E, 3, 1, S2(3), "tech: btn 0x379 (pair) frame h+6");
add(0x499AB1, 2, 1, S(3),  "tech: btn 0x37A frame T-3");          add(0x499AB4, 2, 1, S(3),  "tech: btn 0x37A frame L-3");
add(0x499AC2, 3, 1, S2(3), "tech: btn 0x37A frame w+6");          add(0x499ACF, 3, 1, S2(3), "tech: btn 0x37A frame h+6");
add(0x499C23, 2, 1, S(3),  "tech: leads-to loop A frame L-3");    add(0x499C29, 2, 1, S(3),  "tech: leads-to loop A frame T-3");
add(0x499C2C, 3, 1, S2(3), "tech: leads-to loop A frame w+6");    add(0x499C3C, 3, 1, S2(3), "tech: leads-to loop A frame h+6");
add(0x499DFA, 2, 1, S(3),  "tech: leads-to loop B(3) frame L-3"); add(0x499E00, 2, 1, S(3),  "tech: leads-to loop B(3) frame T-3");
add(0x499E03, 3, 1, S2(3), "tech: leads-to loop B(3) frame w+6"); add(0x499E13, 3, 1, S2(3), "tech: leads-to loop B(3) frame h+6");
add(0x499F80, 2, 1, S(3),  "tech: leads-to loop C frame L-3");    add(0x499F86, 2, 1, S(3),  "tech: leads-to loop C frame T-3");
add(0x499F89, 3, 1, S2(3), "tech: leads-to loop C frame w+6");    add(0x499F99, 3, 1, S2(3), "tech: leads-to loop C frame h+6");
// card (pass 1): frame {cardL-3, y-9, cardL+card_w+3, y+h+6} d5a0, inset 3 d528; text wrap x = cardL+3, w = card_w-6
add(0x49A09B, 2, 1, NEG(3), "tech: card frame L = cardL-3");
add(0x49A0A6, 2, 1, S(3),   "tech: card frame R = cardL+card_w+3");
add(0x49A0B2, 2, 1, NEG(9), "tech: card frame T = y-9");
add(0x49A0B5, 2, 1, S(6),   "tech: card frame B = y+h+6");
add(0x49A0D4, 1, 4, S(3),   "tech: card inner frame inset 3 (d528)");
add(0x49A10C, 2, 1, S2(3),  "tech: title wrap_cent_4 width = card_w-6");
add(0x49A110, 2, 1, S(3),   "tech: title wrap x = cardL+3");
add(0x49A134, 2, 1, S2(3),  "tech: title wrap_height width = card_w-6 (pass 0)");
add(0x49A21A, 2, 1, S2(3),  "tech: category wrap_cent_4 width = card_w-6");
add(0x49A21E, 2, 1, S(3),   "tech: category wrap x = cardL+3");
add(0x49A245, 2, 1, S2(3),  "tech: category wrap_height width = card_w-6 (pass 0)");
// icon (Sprite_draw_mono via FUN_005E3E00: arg6 = scaleNum 0x32, arg7 = scaleDen [0x759E40+id*0x2C] NON-IMM)
add(0x49A2A4, 2, 1, S(3),    "tech: icon y = y+3");
add(0x49A2A8, 1, 1, S(0x32), "tech: icon target width 50 (scaleNum push; 125 at g=40 — imm8 limit)");
// [v4: handled by REGFIX attach — see below] 0x49A2B1
add(0x49A2C3, 3, 1, S(3),    "tech: icon x += 3");
// [v4: handled by REGFIX attach — see below] 0x49A2DA
add(0x49A2E8, 1, 4, S(0x3A), "tech: content h += 58 - font_h (pass 0)");
add(0x49A348, 6, 4, S(0xA),  "tech DL: DL canvas Buffer+0x10 = 10 (paragraph first-line indent) for the link lists (fonts 0x7141AC=DL F10 / 0x714184=DL F9)");
// 9 hyperlink list blocks: wrap_3(str, cardL+3, y, card_w-6) (pass 1) / wrap_height(str, card_w-6) (pass 0)
add(0x49A4B8, 2, 1, S2(3), "tech: list#1 (units) wrap w");   add(0x49A4BB, 2, 1, S(3), "tech: list#1 wrap x");   add(0x49A4D2, 2, 1, S2(3), "tech: list#1 wrap_height w");
add(0x49A68C, 2, 1, S2(3), "tech: list#2 (chassis) wrap w"); add(0x49A68F, 2, 1, S(3), "tech: list#2 wrap x");   add(0x49A6A6, 2, 1, S2(3), "tech: list#2 wrap_height w");
add(0x49A8A0, 2, 1, S2(3), "tech: list#3 (weapons) wrap w"); add(0x49A8A3, 2, 1, S(3), "tech: list#3 wrap x");   add(0x49A8BA, 2, 1, S2(3), "tech: list#3 wrap_height w");
add(0x49AAA0, 2, 1, S2(3), "tech: list#4 (armor) wrap w");   add(0x49AAA3, 2, 1, S(3), "tech: list#4 wrap x");   add(0x49AABA, 2, 1, S2(3), "tech: list#4 wrap_height w");
add(0x49AC0B, 2, 1, S2(3), "tech: list#5 (abilities) wrap w"); add(0x49AC0E, 2, 1, S(3), "tech: list#5 wrap x"); add(0x49AC25, 2, 1, S2(3), "tech: list#5 wrap_height w");
add(0x49AD54, 2, 1, S2(3), "tech: list#6 (units2) wrap w");  add(0x49AD57, 2, 1, S(3), "tech: list#6 wrap x");   add(0x49AD6F, 2, 1, S2(3), "tech: list#6 wrap_height w");
add(0x49AF43, 2, 1, S2(3), "tech: list#7 (fac/proj) wrap w"); add(0x49AF47, 2, 1, S(3), "tech: list#7 wrap x");  add(0x49AF60, 2, 1, S2(3), "tech: list#7 wrap_height w");
add(0x49B02B, 2, 1, S2(3), "tech: list#8 (society) wrap w"); add(0x49B02E, 2, 1, S(3), "tech: list#8 wrap x");   add(0x49B045, 2, 1, S2(3), "tech: list#8 wrap_height w");
add(0x49B129, 2, 1, S2(3), "tech: list#9 (terraform) wrap w"); add(0x49B12C, 2, 1, S(3), "tech: list#9 wrap x"); add(0x49B143, 2, 1, S2(3), "tech: list#9 wrap_height w");

// =====================================================================================
// H  ReportWin_tech_hover 0x49B220 (mode 8 -> draws into the DL canvas; re-derives the page's frames)
// =====================================================================================
// [v9 REMOVED: 0x49B299 mov eax,3 is the button-INDEX compare (k<3), not a pixel value]
add(0x49B2E3, 2, 1, NEG(3),  "hover: button frame L-3");
// [v12: 0x49B2F3 folded into the hover stub at 0x49B2F1]
add(0x49B32E, 2, 1, S(3),    "hover: card y-3 (first half of the page's y-9)");
add(0x49B333, 2, 1, NEG(3),  "hover: card frame L = cardL-3");
add(0x49B336, 2, 1, S(3),    "hover: card frame R = cardL+card_w+3");
add(0x49B339, 3, 1, S(3),    "hover: y+h (+3 cancels the -3 above)");
add(0x49B33D, 2, 1, SD(3, 9), "hover: card frame T = (y-3)-6 = y-9 (matches the page's NEG(9))");
add(0x49B346, 2, 1, S(6),    "hover: card frame B = y+h+6");
add(0x49B375, 1, 4, S(3),    "hover: inner frame inset 3 (hover d5f0)");
add(0x49B3E2, 1, 4, S(3),    "hover: inner frame inset 3 (normal d5a0)");

// =====================================================================================
// X  ReportWin_tech_reset 0x496BB0 — draws ONLY into ReportWin's OWN canvas (RW+0x444), invisible in
//    Datalinks mode -> leave native (verify-only rows)
// =====================================================================================
skip(0x496CA8, 2, 1, NAT(-3), "reset: RW+0x7BF8 rect L-3 (ReportWin canvas) — leave native");
skip(0x496CAB, 2, 1, NAT(-3), "reset: RW+0x7BF8 rect T-3 — leave native");
skip(0x496CBB, 1, 4, NAT(3),  "reset: RW+0x7BF8 rect R/B +3, later L/T +3 (mov ebx,3) — leave native");
skip(0x496CE6, 1, 4, NAT(-3), "reset: RW+0x7BF8 rect R/B -3 (mov eax,-3) — leave native");

// =====================================================================================
// K  ADDENDUM: FUN_0049B450 (RET 0x1C; connector bars + arrow between card and buttons), called 6x by the
//    tech page and by hover; mode 8 -> draws into the DL canvas. Outside the requested list but needed for a
//    complete bake. Semantics are geometric (bar h 20, +-7 caps, +-4/+-3/+-2 edges, arrow at (x-10, y-6)).
// =====================================================================================
add(0x49B4B9, 2, 1, S(2),    "conn: bar x = mid-2");
add(0x49B4DC, 2, 1, S(7),    "conn: bar cap +7");
add(0x49B4E0, 3, 1, NEG(4),  "conn: bar L = x+y-4");
add(0x49B4EF, 2, 1, S(0x14), "conn: bar h 20");
add(0x49B4F2, 2, 1, S(7),    "conn: bar cap +7");
add(0x49B4FF, 1, 4, NEG(7),  "conn: deflate -7 (mov eax,-7)");
add(0x49B52C, 2, 1, NEG(7),  "conn: L-7");
add(0x49B531, 1, 4, S(7),    "conn: inflate +7 (mov eax,7)");
add(0x49B592, 3, 1, S(3),    "conn: L = x+y+3");
add(0x49B5FA, 3, 1, NEG(4),  "conn: L = x+y-4");
add(0x49B638, 2, 1, NEG(7),  "conn: L-7");
add(0x49B63B, 2, 1, S(4),    "conn: R+4");
add(0x49B646, 2, 1, S(0x14), "conn: bar h 20");
add(0x49B654, 1, 4, NEG(7),  "conn: deflate -7 (mov eax,-7)");
add(0x49B659, 2, 1, S(7),    "conn: L+7");
add(0x49B67E, 2, 1, NEG(7),  "conn: L-7");
add(0x49B683, 1, 4, S(7),    "conn: inflate +7 (mov eax,7)");
add(0x49B6EC, 3, 1, NEG(6),  "conn: arrow y = btn_y + h/2 - 6 (Sprite_blit_scaled_core 1:1 via globals 0x696D18/1C — NON-IMM scale)");
add(0x49B6F7, 2, 1, S(0xA),  "conn: arrow x = card L - 10");
add(0x49B730, 2, 1, S(2),    "conn: bar x = mid-2 (right column)");
add(0x49B792, 2, 1, NEG(0xA), "conn: arrow x-10");
add(0x49B7A8, 2, 1, NEG(6),  "conn: arrow y-6");
add(0x49B7C8, 2, 1, S(4),    "conn: R+4");
add(0x49B7CB, 2, 1, NEG(7),  "conn: L-7");
add(0x49B7D7, 2, 1, S(0x14), "conn: bar h 20");
add(0x49B7DA, 2, 1, S(7),    "conn: L+7");
add(0x49B7EA, 1, 4, NEG(7),  "conn: deflate -7 (mov eax,-7)");
add(0x49B814, 2, 1, NEG(7),  "conn: L-7");
add(0x49B819, 1, 4, S(7),    "conn: inflate +7 (mov eax,7)");
add(0x49B836, 2, 1, NEG(3),  "conn: x-3");
add(0x49B898, 3, 1, NEG(6),  "conn: arrow y-6");
add(0x49B8AA, 2, 1, S(0xA),  "conn: arrow x-10");
add(0x49B8F8, 3, 1, NEG(7),  "conn: arrow x-7");
add(0x49B90A, 2, 1, S(0xA),  "conn: arrow y-10");
add(0x49B93C, 2, 1, S(4),    "conn: R+4");
add(0x49B95C, 2, 1, NEG(3),  "conn: x-3");
add(0x49B9BE, 3, 1, NEG(6),  "conn: arrow y-6");
add(0x49B9D0, 2, 1, S(0xA),  "conn: arrow x-10");
add(0x49BA1E, 3, 1, NEG(7),  "conn: arrow x-7");
add(0x49BA30, 2, 1, S(0xA),  "conn: arrow y-10");
add(0x49BA62, 2, 1, S(4),    "conn: R+4");
add(0x49BA82, 2, 1, NEG(3),  "conn: x-3");
add(0x49BAE4, 3, 1, NEG(6),  "conn: arrow y-6");
add(0x49BAF6, 2, 1, S(0xA),  "conn: arrow x-10");
add(0x49BB44, 3, 1, NEG(7),  "conn: arrow x-7");
add(0x49BB56, 2, 1, S(0xA),  "conn: arrow y-10");
add(0x49BB88, 2, 1, S(4),    "conn: R+4");
add(0x49BBE0, 3, 1, NEG(4),  "conn: L = x+y-4");
add(0x49BBF1, 2, 1, S(7),    "conn: cap +7");
add(0x49BBF4, 2, 1, S(0x14), "conn: bar h 20");
add(0x49BC00, 1, 4, NEG(7),  "conn: deflate -7 (mov eax,-7)");
add(0x49BC05, 2, 1, S(7),    "conn: L+7");
add(0x49BC2A, 2, 1, NEG(7),  "conn: L-7");
add(0x49BC34, 1, 4, S(7),    "conn: inflate +7 (mov eax,7)");
add(0x49BC4E, 2, 1, S(7),    "conn: cap +7");
add(0x49BC51, 2, 1, S(0x14), "conn: bar h 20");
add(0x49BC5F, 1, 4, NEG(7),  "conn: deflate -7 (mov eax,-7)");
add(0x49BC64, 2, 1, S(7),    "conn: L+7");
add(0x49BC89, 2, 1, NEG(7),  "conn: L-7");
add(0x49BC93, 1, 4, S(7),    "conn: inflate +7 (mov eax,7)");

  // --- v3 RAW byte patches ---
  raw(0x42BFF0, [0x8D, 0x86, 0xC4, 0x03, 0x01, 0x00], [0x8D, 0x86, 0x74, 0x04, 0x00, 0x00], "render_topic restore rect: lea eax,[esi+0x103C4] -> [esi+0x474] (canvas space)");
  raw(0x499FE3, [0xA1, 0xD4, 0x40, 0x8A, 0x00], [0xB8, 0x1C, 0x40, 0x71, 0x00], "tech title font: mov eax,[0x8A40D4] -> mov eax,&DL.F0 (0x71401C, 18b scaled)");
  raw(0x49A14A, [0xA1, 0xC8, 0x40, 0x8A, 0x00], [0xB8, 0xBC, 0x40, 0x71, 0x00], "tech category font: mov eax,[0x8A40C8] -> mov eax,&DL.F4 (0x7140BC, 14b scaled)");
  // ---- v11 (a): Buffer_box_sprite sites -> baked band-map renderers ----
  const T_HOLLOW_FLAT = 0xA0C140, T_DEVFILL = 0xA102A0, A_BOX_SPRITE = 0x5E2DD3;
  // v11b: MODULE-LEVEL retention (feedback-frida-memory-alloc-gc): a block-local array is itself unreachable after
  // script load -> the stub page was GC-freed and recycled -> AV at eip = stub on the first hollow_flat site.
  const RETAINED = globalThis.DL_RETAINED = globalThis.DL_RETAINED || [];
  // DW v14r stub (54 B): copy the rect arg to scratch with R-1/B-1, replace [esp+4], jmp thunk_box_thick_hollow_flat
  const bmScratch = Memory.alloc(16); RETAINED.push(bmScratch); const bmS = bmScratch.toInt32();
  const bmCode = [0x8b, 0x44, 0x24, 0x04, 0x8b, 0x10, 0x89, 0x15, 0, 0, 0, 0, 0x8b, 0x50, 0x04, 0x89, 0x15, 0, 0, 0, 0, 0x8b, 0x50, 0x08, 0x4a, 0x89, 0x15, 0, 0, 0, 0, 0x8b, 0x50, 0x0c, 0x4a, 0x89, 0x15, 0, 0, 0, 0, 0xc7, 0x44, 0x24, 0x04, 0, 0, 0, 0, 0xe9, 0, 0, 0, 0];
  const bmStub = Memory.alloc(Process.pageSize); RETAINED.push(bmStub);
  Memory.patchCode(bmStub, bmCode.length, c => {
    c.writeByteArray(bmCode);
    for (const o of [8, 45]) c.add(o).writeU32(bmS >>> 0);
    c.add(17).writeU32((bmS + 4) >>> 0); c.add(27).writeU32((bmS + 8) >>> 0); c.add(37).writeU32((bmS + 12) >>> 0);
    c.add(50).writeS32(VA(T_HOLLOW_FLAT).sub(bmStub.add(54)).toInt32());
  });
  globalThis.DL_BMSTUB = bmStub; globalThis.DL_BMSCRATCH = bmScratch;
  log("frame stub (R-1/B-1 -> hollow_flat) at " + bmStub + " scratch " + bmScratch + " bytes " + Array.from(new Uint8Array(bmStub.readByteArray(8))).map(x => x.toString(16)).join(" "));
  // v12f: devfill takes the same INCLUSIVE footprint as hollow_flat (its STEP1) -> the DF sites need the R-1/B-1 stub
  //   too (the DW bake's devfill callers already do: "measured 1px R/B spill"). Proven by [RING]: the builder's d690
  //   right stroke sat at x = R-1..R (2 px) in the canvas, and column R is outside the s(0x309)-wide window -> 1 px on
  //   screen (1600 + 4K), while the left/top strokes were 2 px.
  const bmStubDF = Memory.alloc(Process.pageSize); RETAINED.push(bmStubDF);
  Memory.patchCode(bmStubDF, bmCode.length, c => {
    const S0 = bmScratch.toInt32();
    c.writeByteArray(bmCode);
    for (const o of [8, 45]) c.add(o).writeU32(S0 >>> 0);
    c.add(17).writeU32((S0 + 4) >>> 0); c.add(27).writeU32((S0 + 8) >>> 0); c.add(37).writeU32((S0 + 12) >>> 0);
    c.add(50).writeS32(VA(T_DEVFILL).sub(bmStubDF.add(54)).toInt32());
  });
  log("frame stub (R-1/B-1 -> devfill) at " + bmStubDF);
  // v12j: exact-fill variant for the HC (clipped bracket/frame) sites — also stash the ORIGINAL half-open rect
  // into g_faction_scratch_rect (0xA0D010) and set g_fc_exact (0xA0E554) so thunk_frame_enlarge stretches the
  // small frame to the EXACT rect span: bottom/right strokes land flush (B-2..B-1), the stem meets the chevron tip.
  const bmxCode = [
    0x8b, 0x44, 0x24, 0x04,             // mov eax,[esp+4]
    0x8b, 0x10, 0x89, 0x15, 0, 0, 0, 0, 0x89, 0x15, 0, 0, 0, 0,             // L  -> SR, S
    0x8b, 0x50, 0x04, 0x89, 0x15, 0, 0, 0, 0, 0x89, 0x15, 0, 0, 0, 0,       // T  -> SR+4, S+4
    0x8b, 0x50, 0x08, 0x89, 0x15, 0, 0, 0, 0, 0x4a, 0x89, 0x15, 0, 0, 0, 0, // R  -> SR+8; R-1 -> S+8
    0x8b, 0x50, 0x0c, 0x89, 0x15, 0, 0, 0, 0, 0x4a, 0x89, 0x15, 0, 0, 0, 0, // B  -> SR+12; B-1 -> S+12
    0xc7, 0x05, 0, 0, 0, 0, 1, 0, 0, 0,                                     // mov dword [g_fc_exact],1
    0xc7, 0x44, 0x24, 0x04, 0, 0, 0, 0,                                     // mov dword [esp+4],S
    0xe9, 0, 0, 0, 0];                                                      // jmp T_HOLLOW_FLAT
  const bmStubX = Memory.alloc(Process.pageSize); RETAINED.push(bmStubX);
  Memory.patchCode(bmStubX, bmxCode.length, c => {
    const S0 = bmScratch.toInt32(), SR0 = VA(0xA0D010).toInt32(), FC0 = VA(0xA0E554).toInt32();
    c.writeByteArray(bmxCode);
    c.add(8).writeU32(SR0 >>> 0); c.add(14).writeU32(S0 >>> 0);
    c.add(23).writeU32((SR0 + 4) >>> 0); c.add(29).writeU32((S0 + 4) >>> 0);
    c.add(38).writeU32((SR0 + 8) >>> 0); c.add(45).writeU32((S0 + 8) >>> 0);
    c.add(54).writeU32((SR0 + 12) >>> 0); c.add(61).writeU32((S0 + 12) >>> 0);
    c.add(67).writeU32(FC0 >>> 0);
    c.add(79).writeU32(S0 >>> 0);
    c.add(84).writeS32(VA(T_HOLLOW_FLAT).sub(bmStubX.add(88)).toInt32());
  });
  log("frame stub X (exact-fill + R-1/B-1 -> hollow_flat) at " + bmStubX);
  const relBytes = (tgt, va) => { const r = tgt.sub(VA(va + 5)).toInt32(); return [r & 0xff, (r >> 8) & 0xff, (r >> 16) & 0xff, (r >>> 24) & 0xff]; };
  // v12 hover R/B +3 stub: `add edx,eax; add ecx,-3; add ebx,eax` @0x49B2F1 (7 B) -> call stub (filled at BUILD when g is known)
  const hovStub = Memory.alloc(Process.pageSize); RETAINED.push(hovStub); globalThis.DL_HOVSTUB = hovStub;
  function fillHoverStub() {
    const v = s(3);
    Memory.patchCode(hovStub, 20, c => {
      c.writeByteArray([0x81, 0xC2, v & 0xff, (v >> 8) & 0xff, 0, 0,          // add edx, s3
                        0x81, 0xC1, (-v) & 0xff, ((-v) >> 8) & 0xff, 0xff, 0xff, // add ecx, -s3
                        0x81, 0xC3, v & 0xff, (v >> 8) & 0xff, 0, 0,           // add ebx, s3
                        0xC3]);                                                // ret
    });
    log("hover stub at " + hovStub + " s(3)=" + v);
  }
  raw(0x49B2F1, [0x03, 0xD0, 0x83, 0xC1, 0xFD, 0x03, 0xD8], [0xE8, ...relBytes(hovStub, 0x49B2F1), 0x90, 0x90], "hover: frame R/B +3 + T-3 -> call stub (eax=3 stays the k<3 compare)");
  const FRAME_SITES = [
    // builder (once, DL canvas)
    [0x429A5B, "d690 window backdrop", "DF"], [0x429A6E, "d5a0 panel_outer", "HF"], [0x429ABB, "d5a0 BACK+EXIT container", "HF"],
    [0x429ACE, "d618 list_title", "DF"], [0x429B1B, "d5a0 list+title", "HF"], [0x429B4F, "d618 title_rect", "DF"],
    // list builders (title band per category)
    [0x42A589, "d618", "DF"], [0x42A6F6, "d618", "DF"], [0x42A85C, "d618", "DF"], [0x42A9C2, "d618", "DF"], [0x42AB22, "d618", "DF"],
    [0x42AC82, "d618", "DF"], [0x42ADE2, "d618", "DF"], [0x42AF41, "d618", "DF"], [0x42B0F7, "d618", "DF"], [0x42B260, "d618", "DF"],
    [0x42B3EF, "d618", "DF"], [0x42B592, "d618", "DF"], [0x42B743, "d618", "DF"], [0x42B89C, "d618", "DF"], [0x42BA0B, "d618", "DF"], [0x42BC1E, "d618", "DF"],
    // draw_page (0x42C020 d690 mixed-space+clip stays native; restriped in JS)
    [0x42C03E, "d528 content_union", "HF"], [0x42C051, "d618 title_rect", "DF"],
    // tech page (exec-scoped): button frames + card outer/inner; the 4 clipped bracket draws stay native
    [0x4999A7, "d5a0 prereq btn frame", "HF"], [0x499ADD, "d5a0 prereq btn frame", "HF"], [0x499C55, "d5a0 leads-to btn frame", "HF"],
    [0x499E2C, "d5a0 leads-to btn frame", "HF"], [0x499FB2, "d5a0 btn frame", "HF"], [0x49A0C6, "d5a0 card outer", "HF"], [0x49A0FB, "d528 card inner", "HF"],
    // hover redraw (exec-scoped): card + button frames, normal / hover sets
    [0x49B36A, "d5f0 hover card", "HF"], [0x49B39C, "d5f0 hover btn", "HF"], [0x49B3D7, "d5a0 card", "HF"], [0x49B409, "d5a0 btn", "HF"],
    // v12g: the 10 CLIP-gated bracket draws (a frame drawn under a strip clip so only one edge shows = the connector
    //   bracket lines; 1 px at every g in the user's 1600/4K shots). Same HF stub; the clip is emulated around
    //   thunk_box_thick_hollow_flat (snapshot the frame's bbox, restore everything outside the dest clip rect).
    [0x4991C8, "tech bracket", "HC"], [0x499253, "tech bracket", "HC"], [0x499328, "tech bracket", "HC"], [0x4993EC, "tech bracket", "HC"],
    [0x49B558, "conn bracket", "HC"], [0x49B56E, "conn bracket", "HC"], [0x49B61F, "conn bracket", "HC"], [0x49B6B1, "conn bracket", "HC"],
    [0x49BBBF, "conn bracket", "HC"], [0x49BCAE, "conn bracket", "HC"],
  ];
  const CLIP_RETS = new Set(FRAME_SITES.filter(f => f[2] === "HC").map(f => (f[0] + 5) >>> 0));
  const BISECT_FRAMES = { HF: true, DF: true };    // v12: all frame sites ON
  for (const [va, set, kind] of FRAME_SITES) {
    if (!BISECT_FRAMES[kind === "HC" ? "HF" : kind]) { log("FRAME site @" + hex(va) + " " + set + " left native (bisect)"); continue; }
    const tgt = kind === "DF" ? bmStubDF : (kind === "HC" ? bmStubX : bmStub);
    raw(va, [0xE8, ...relBytes(VA(A_BOX_SPRITE), va)], [0xE8, ...relBytes(tgt, va)], "frame " + set + " -> " + (kind === "HF" ? "hollow_flat(R-1/B-1)" : "devfill") + " @" + hex(va));
  }
  for (const a of [0x4997B7, 0x4998F9, 0x499A3B, 0x499BAB, 0x499D82, 0x499F08])
    raw(a, [0x68, 0xB4, 0x84, 0x6E, 0x00], [0x68, 0x94, 0x40, 0x71, 0x00], "tech button label font: push 0x6E84B4 (BaseWin shared) -> push &DL.F3 0x714094 (= wing-button font +0x101F4) @" + hex(a));

  const TECH_LO = 0x496BB0, TECH_HI = 0x49BD00;
  const isTech = a => a >= TECH_LO && a < TECH_HI;
  let patched = false, techApplied = false;
  function applyPatches() { if (patched) return; patched = true; applySet(false, "build"); }
  function applyTech(on) {
    if (on === techApplied) return;
    techApplied = on;
    if (on) applySet(true, "exec"); else revertSet(true, "exec leave");
  }
  function revertSet(tech, tag) {
    let n = 0;
    for (const r of RAW) { if (isTech(r.addr) !== tech) continue; try { Memory.patchCode(VA(r.addr), r.nat.length, code => code.writeByteArray(r.nat)); n++; } catch (e) { log("REVERT ERROR raw " + r.label + ": " + e); } }
    for (const p of P) {
      if (isTech(p.addr) !== tech) continue;
      try {
        if (p.fn.isFloat || p.w === "f") { Memory.patchCode(VA(p.addr), p.off + 4, code => code.add(p.off).writeFloat(p.fn.nat)); n++; continue; }
        const v = (p.kind === "neg") ? -p.fn.nat : p.fn.nat;
        Memory.patchCode(VA(p.addr), p.off + p.w, code => { if (p.w === 1) code.add(p.off).writeS8(v); else code.add(p.off).writeS32(v); });
        n++;
      } catch (e) { log("REVERT ERROR " + p.label + ": " + e); }
    }
    log("reverted " + n + " " + (tech ? "tech" : "build") + " sites (" + tag + ")");
  }
  function applySet(tech, tag) {
    let n = 0, skip = 0;
    for (const r of RAW) {
      if (isTech(r.addr) !== tech) continue;
      try {
        const cur = Array.from(new Uint8Array(VA(r.addr).readByteArray(r.nat.length)));
        if (cur.join() !== r.nat.join()) { skip++; log("PATCH SKIP raw mismatch " + r.label + " @" + hex(r.addr) + " read " + cur.map(b => b.toString(16)).join(" ")); continue; }
        Memory.patchCode(VA(r.addr), r.nu.length, code => code.writeByteArray(r.nu));
        log("PATCH raw " + r.label + " @" + hex(r.addr)); n++;
      } catch (e) { skip++; log("PATCH ERROR raw " + r.label + ": " + e); }
    }
    for (const p of P) {
      if (isTech(p.addr) !== tech) continue;
      try {
        if (p.fn.isFloat || p.w === "f") {
          const of = VA(p.addr).add(p.off).readFloat();
          if (Math.abs(of - p.fn.nat) > 1e-6) { skip++; log("PATCH SKIP float mismatch " + p.label + " @" + hex(p.addr) + " read " + of + " expect " + p.fn.nat); continue; }
          const fv = p.fn();
          Memory.patchCode(VA(p.addr), p.off + 4, code => code.add(p.off).writeFloat(fv));
          n++; continue;
        }
        const v = p.fn(), expect = p.fn.nat;
        const orig = p.w === 1 ? VA(p.addr).add(p.off).readS8() : VA(p.addr).add(p.off).readS32();
        if (orig !== expect) { skip++; log("PATCH SKIP native mismatch " + p.label + " @" + hex(p.addr) + "+" + p.off + " read " + orig + " expect " + expect); continue; }
        if (p.w === 1 && (v > 127 || v < -128)) { skip++; log("PATCH SKIP imm8 overflow " + p.label + " @" + hex(p.addr) + " -> " + v); continue; }
        Memory.patchCode(VA(p.addr), p.off + p.w, code => { if (p.w === 1) code.add(p.off).writeS8(v); else code.add(p.off).writeS32(v); });
        n++;
      } catch (e) { skip++; log("PATCH ERROR " + p.label + " @" + hex(p.addr) + ": " + e); }
    }
    log("immediates patched (" + tag + "): " + n + (skip ? " (SKIPPED " + skip + ")" : "") + " g=" + g +
        " s(3)=" + s(3) + " s(4)=" + s(4) + " s(22)=" + s(22) + " s(24)=" + s(24) + " s(738)=" + s(738) + " s(832)=" + s(832) + " s(800)=" + s(800));
  }

  // ---------------- verification dump ----------------
  const RECTS = [
    ["gw.screen+13C", 0x13C], ["gw.local+474", 0x474],
    ["content_union", 0x10334], ["art_box", 0x10354], ["title_rect", 0x10364], ["centre_seed_copy", 0x10374],
    ["text_upper", 0x10384], ["text_lower", 0x10394], ["panel_outer", 0x103B4], ["window_screen", 0x103C4],
    ["list_title", 0x103D4], ["list_box", 0x103E4], ["wingL0", 0x103F4], ["wingL7", 0x10464], ["wingR8", 0x10474], ["wingR15", 0x104E4],
    ["btnBACK", 0x104F4], ["btnEXIT", 0x10504],
  ];
  const TS = [["TS_A", 0x10514], ["TS_center", 0x130B4], ["TS_B", 0x15C54]];
  function dump(tag) {
    log("---- DUMP (" + tag + ") " + envStr() + " ----");
    log("win: screen+13C=" + rstr(OBJ.add(0x13C)) + " local+474=" + rstr(OBJ.add(0x474)) + " canvasWH=" + safeS32(OBJ.add(0x4C4)) + "x" + safeS32(OBJ.add(0x4C8)) + " flags=" + hex(safeU32(OBJ.add(0x98))));
    for (const [name, off] of RECTS) log("RECT " + name + " = " + rstr(OBJ.add(off)));
    for (let i = 0; i < 18; i++) { const b = OBJ.add(0x2A3C + i * 0xB4C); log("BTN#" + i + " screen+13C=" + rstr(b.add(0x13C)) + " local=" + rstr(b.add(0x474)) + " canvasWH=" + safeS32(b.add(0x4C4)) + "x" + safeS32(b.add(0x4C8)) + " parent=" + hex(safeU32(b.add(0xC4))) + " faces=" + hex(safeU32(b.add(0xAC8)))); }
    let f = []; for (let i = 0; i < 11; i++) { const fp = OBJ.add(0x1017C + i * 0x28); f.push("F" + i + "=" + safeS32(fp.add(0xC)) + "/" + safeS32(fp.add(0x10))); }
    log("FONTS size+C/+10: " + f.join(" "));
    for (const [name, off] of TS) { const t = OBJ.add(off); log("TS " + name + " screen+13C=" + rstr(t.add(0x13C)) + " canvasWH=" + safeS32(t.add(0x4C4)) + "x" + safeS32(t.add(0x4C8)) + " barW=" + safeS32(t.add(0x1480)) + " sb.local=" + rstr(t.add(0xA20 + 0x474))); }
    log("LISTBOX gw@+F670 screen+13C=" + rstr(OBJ.add(0xF670 + 0x13C)) + " local=" + rstr(OBJ.add(0xF670 + 0x474)) + " dialog x/y/w/h=" + safeS32(OBJ.add(0x100AC)) + "," + safeS32(OBJ.add(0x100B0)) + "," + safeS32(OBJ.add(0x100B4)) + "," + safeS32(OBJ.add(0x100B8)) +
        " rowStride=" + safeS32(OBJ.add(0x100D0)) + " lineH=" + safeS32(OBJ.add(0x100F0)) + " visRows=" + safeS32(OBJ.add(0x100E0)) + " items=" + safeS32(OBJ.add(0x1011C)));
    log("---- END DUMP ----");
  }

  function setNetwinActive(v, tag) {
    try { VA(G_NETWIN_ACTIVE).writeS32(v); log("g_netwin_active=" + v + " (" + tag + ")"); } catch (e) { log("g_netwin_active write failed: " + e); }
  }
  function fixBackExitFaces() {
    for (const off of [0xDEFC, 0xEA48]) {
      const b = OBJ.add(off);
      const cur = [safeU32(b.add(0xAC8)), safeU32(b.add(0xACC)), safeU32(b.add(0xAD0))];
      if (cur[0] !== 0 || cur[1] !== 0 || cur[2] !== 0) { log("FACES @+0x" + off.toString(16) + " already " + cur.map(hex).join("/") + " — untouched"); continue; }
      b.add(0xAC8).writeU32(WING_FACES[0]); b.add(0xACC).writeU32(WING_FACES[1]); b.add(0xAD0).writeU32(WING_FACES[2]);
      log("FACES @+0x" + off.toString(16) + " (" + (off === 0xDEFC ? "BACK" : "EXIT") + ") <- wing set " + WING_FACES.map(hex).join("/"));
    }
  }
  // ---------------- v4 REGFIX: register fix-ups at the imm8-overflow sites ----------------
  // [addr, apply(ctx)] — the instruction at addr still executes with its native immediate.
  const REGFIX = [
    [0x431238, c => { c.eax = c.eax.add(s(75) - 75); },  "terraform diamond bottom y +75 (add eax,0x4B)"],
    [0x431253, c => { c.edx = c.edx.add(s(100) - 100); }, "terraform diamond right x +100 (after lea edx,[esi+0x64])"],
    [0x4316B3, c => { c.esi = c.esi.add(s(103) - 103); }, "terraform upper stats x +103 (add esi,0x67; jl target)"],
    [0x43196F, c => { const d = c.edi.toInt32(); if (d < 0x10 || d > 0x12) c.ecx = c.ecx.add(s(103) - 103); }, "terraform lower text x +103 (cond edi∉[0x10..0x12], at sub eax,ecx)"],
    [0x49A2B1, c => { c.eax = c.eax.sub(s(52) - 52); },  "tech icon centring span 52 (sub eax,0x34)"],
    [0x49A2DA, c => { c.eax = c.eax.add(s(58) - 58); },  "tech y += 58 after icon (add eax,0x3A)"],
  ];
  let inExec = false;
  let regfixArmed = false;
  function armRegfix() {
    if (regfixArmed) return; regfixArmed = true;
    for (const [addr, fn, label] of REGFIX) {
      try { Interceptor.attach(VA(addr), { onEnter() { if (g > 16 && (!isTech(addr) || inExec)) fn(this.context); } }); log("REGFIX armed @" + hex(addr) + " " + label); }
      catch (e) { log("REGFIX FAILED @" + hex(addr) + ": " + e); }
    }
  }

  // ---------------- v4 tech page bracket (ReportWin non-immediate inputs) ----------------
  const G_REPORTWIN = 0x876478, RW_TEXTB = 0x5980, RW_LINEH = 0xE268;
  const G_MODEIDX = 0x7D392C, G_MODETAB = 0x7AE778;
  function modeSlot() { const i = safeS32(VA(G_MODEIDX), 0); return (i >= 0 && i < 64) ? VA(G_MODETAB).add(i * 4) : null; }
  let techN = 0;
  Interceptor.attach(VA(0x498B30), {
    onEnter() {
      const rw = VA(G_REPORTWIN); techN++;
      this.saved = null; this.modeSaved = null; regs(this.context, "tech_page enter"); validateHeaps("tech_page enter");
      restripeContentUnion("tech_page");
      { const sp = this.context.esp; this.slots = [sp.sub(0x228), sp.sub(0x224), sp.sub(0x220)];   // saved edi / esi / ebx (v12: local dropped)
        rearmWP(this.slots, "tech_page saved edi/esi/ebx (entry esp " + sp + ")");
        log("[CLIP] canvas clip=" + rstr(OBJ.add(0x444 + 0x20)) + " at tech_page enter"); }
      const slot = modeSlot(), mode = slot ? safeS32(slot) : -1;
      if (g > 16 && inExec && slot && mode !== 8) { this.modeSaved = [slot, mode]; slot.writeS32(8); log("RW_TECH_PAGE: iface mode " + mode + " -> 8 forced for this call (pre-show paint)"); }
      const b = safeS32(rw.add(RW_TEXTB)), lh = safeS32(rw.add(RW_LINEH));
      if (techN <= 6) log("RW_TECH_PAGE #" + techN + " ecx=" + this.context.ecx + " inExec=" + inExec + " RW+5980(textB)=" + b + " RW+E268(lineH)=" + lh +
                          " RW+5974=" + rstr(rw.add(0x5974)) + " RW+A14=" + rstr(rw.add(0xA14)) + " RW+A24=" + rstr(rw.add(0xA24)) + " DL.textPanel=" + rstr(OBJ.add(0x103A4)));
      if (g > 16 && inExec && this.context.ecx.equals(rw)) {
        const nb = (b > 0 && b <= 800) ? s(b) : b, nl = (lh > 0 && lh <= 64) ? s(lh) : lh;
        rw.add(RW_TEXTB).writeS32(nb); rw.add(RW_LINEH).writeS32(nl);
        this.saved = [b, lh];
        if (techN <= 6) log("RW_TECH_PAGE bracket: textB " + b + " -> " + nb + ", lineH " + lh + " -> " + nl);
      }
    },
    onLeave() {
      const rw = VA(G_REPORTWIN);
      regs(this.context, "tech_page leave"); validateHeaps("tech_page leave");
      if (this.slots) { log("[SLOTS] at tech_page leave: savedEDI=" + this.slots[0].readPointer() + " savedESI=" + this.slots[1].readPointer() + " savedEBX=" + this.slots[2].readPointer() + " clip=" + rstr(OBJ.add(0x444 + 0x20))); }
      { const A = OBJ.add(0x444 + 0x4BC).readPointer(); const hx = A.isNull() ? null : sbhHeaderFor(A); if (hx) rearmWP([VA(SBH_CNT), hx.h.add(8), hx.h.add(0xC), hx.h.add(0x10)], "sbh header for block " + A + " = " + hx.h); else log("[WP] no sbh header contains slot0 block " + A + " | " + sbhStr()); }
      if (this.saved) { rw.add(RW_TEXTB).writeS32(this.saved[0]); rw.add(RW_LINEH).writeS32(this.saved[1]); }
      if (this.modeSaved) this.modeSaved[0].writeS32(this.modeSaved[1]);
      if (techN <= 6) {
        log("RW_TECH_PAGE leave: RW+A14..A34=" + rstr(rw.add(0xA14)) + " " + rstr(rw.add(0xA24)) + " col+A20=" + safeS32(rw.add(0xA20)) +
            " rows+595C/5960/5964/5968/596C/5970=" + [0x595C, 0x5960, 0x5964, 0x5968, 0x596C, 0x5970].map(o => safeS32(rw.add(o))).join(","));
        for (let k = 0; k < 7; k++) { const bt = rw.add(0xA38 + k * 0xB4C); log("   RW btn#" + k + " screen=" + rstr(bt.add(0x13C)) + " flags=" + hex(safeU32(bt.add(0x98))) + " parent=" + hex(safeU32(bt.add(0xC4)))); }
      }
    }
  });

  // ---------------- v10 (c) arrow chevrons: JS scaled redraw (pre-push snapshot + connector onLeave) ----------------
  // Pre-call points inside FUN_0049B450 (never on the call / its return slot):
  //   S1  0x49B6FB: [esp]=x [esp+4]=y ecx=sprite edx=dest      S2  0x49B7AC: [esp]=y esi=x ecx=sprite edx=dest
  //   S3  0x49B90E / S4 0x49BA34 / S5 0x49BB5A: [esp]=x [esp+4]=y eax=sprite edx=dest
  //   alt S3 0x49B8C0 / S4 0x49B9E6 / S5 0x49BB0C (lea eax,[eax*4+0x75AFD0]): [esp]=x [esp+4]=y eax=INDEX edx=dest
  const ARROW_PRE = [
    [0x49B6FB, c => ({ x: safeS32(c.esp), y: safeS32(c.esp.add(4)), spr: c.ecx, dest: c.edx })],
    [0x49B7AC, c => ({ x: c.esi.toInt32(), y: safeS32(c.esp), spr: c.ecx, dest: c.edx })],
    [0x49B90E, c => ({ x: safeS32(c.esp), y: safeS32(c.esp.add(4)), spr: c.eax, dest: c.edx })],
    [0x49BA34, c => ({ x: safeS32(c.esp), y: safeS32(c.esp.add(4)), spr: c.eax, dest: c.edx })],
    [0x49BB5A, c => ({ x: safeS32(c.esp), y: safeS32(c.esp.add(4)), spr: c.eax, dest: c.edx })],
    [0x49B8C0, c => ({ x: safeS32(c.esp), y: safeS32(c.esp.add(4)), spr: VA(0x75AFD0).add(c.eax.toInt32() * 4), dest: c.edx })],
    [0x49B9E6, c => ({ x: safeS32(c.esp), y: safeS32(c.esp.add(4)), spr: VA(0x75AFD0).add(c.eax.toInt32() * 4), dest: c.edx })],
    [0x49BB0C, c => ({ x: safeS32(c.esp), y: safeS32(c.esp.add(4)), spr: VA(0x75AFD0).add(c.eax.toInt32() * 4), dest: c.edx })],
  ];
  let arrowPending = null, arrowN = 0;
  function sprInfo(spr) {
    let bits = ptr(0); try { bits = spr.add(4).readPointer(); } catch (e) { }
    return { bits, key: safeU32(spr.add(8)) & 0xff, pitch: safeS32(spr.add(0xC)), w: safeS32(spr.add(0x10)), h: safeS32(spr.add(0x14)), L: safeS32(spr.add(0x20)), T: safeS32(spr.add(0x24)) };
  }
  function armArrowScale() {
    for (const [a, rd] of ARROW_PRE) {
      Interceptor.attach(VA(a), { onEnter() {
        arrowPending = null;
        if (g <= 16 || !inExec) return;
        const A = rd(this.context);
        if (A.dest.isNull()) return;
        const si = sprInfo(A.spr), bi = bufInfo(A.dest); arrowN++;
        if (arrowN <= 48) log("ARROW pre @" + hex(a) + " sprite=" + A.spr + " bits=" + si.bits + " key=" + si.key + " pitch=" + si.pitch + " " + si.w + "x" + si.h + " LT=" + si.L + "," + si.T + " dest=" + A.dest + " (" + bi.w + "x" + bi.h + ") xy=" + A.x + "," + A.y);
        if (si.bits.isNull() || bi.data.isNull() || si.w <= 0 || si.h <= 0 || si.w > 64 || si.h > 64 || si.pitch < si.w) { if (arrowN <= 48) log("ARROW: no pcBits / bad dims -> left native"); return; }
        const x0 = Math.max(0, A.x + Math.min(si.L, 0)), y0 = Math.max(0, A.y + Math.min(si.T, 0));
        const x1 = Math.min(bi.w, A.x + Math.max(si.L, 0) + si.w + 1), y1 = Math.min(bi.h, A.y + Math.max(si.T, 0) + si.h + 1);
        if (x1 <= x0 || y1 <= y0) return;
        const rows = [];
        for (let yy = y0; yy < y1; yy++) rows.push(new Uint8Array(bi.data.add(yy * bi.pitch + x0).readByteArray(x1 - x0)));
        arrowPending = { bi, si, x: A.x, y: A.y, x0, y0, x1, y1, rows, site: a };
      } });
    }
    log("ARROW JS scaler armed at " + ARROW_PRE.length + " pre-call points (redraw in connector onLeave)");
  }
  function drawPendingArrow() {
    const P = arrowPending; arrowPending = null; if (!P) return;
    const { bi, si } = P;
    for (let yy = P.y0; yy < P.y1; yy++) bi.data.add(yy * bi.pitch + P.x0).writeByteArray(P.rows[yy - P.y0]);   // erase the engine's 1:1 arrow
    const sw = s(si.w), sh = s(si.h), dx0 = P.x + s(si.L), dy0 = P.y + s(si.T);
    const src = new Uint8Array(si.bits.readByteArray(si.pitch * si.h));
    const cx0 = Math.max(0, dx0), cx1 = Math.min(bi.w, dx0 + sw);
    if (cx1 <= cx0) return;
    let drawn = 0;
    for (let dy = 0; dy < sh; dy++) {
      const yy = dy0 + dy; if (yy < 0 || yy >= bi.h) continue;
      const sy = Math.floor(((2 * dy + 1) * si.h) / (2 * sh));
      const rowp = bi.data.add(yy * bi.pitch + cx0), cur = new Uint8Array(rowp.readByteArray(cx1 - cx0));
      let dirty = false;
      for (let xx = cx0; xx < cx1; xx++) {
        const sx = Math.floor(((2 * (xx - dx0) + 1) * si.w) / (2 * sw));
        const v = src[sy * si.pitch + sx];
        if (v === si.key) continue;
        cur[xx - cx0] = v; dirty = true; drawn++;
      }
      if (dirty) rowp.writeByteArray(cur);
    }
    if (arrowN <= 48) log("ARROW scaled @" + hex(P.site) + " -> " + sw + "x" + sh + " at " + dx0 + "," + dy0 + " (" + drawn + " px)");
  }

  // ---------------- v11f: heap validation probe (localise the corrupter) ----------------
  const k32 = Process.getModuleByName("kernel32.dll");
  const GetProcessHeaps = new NativeFunction(k32.getExportByName("GetProcessHeaps"), "uint32", ["uint32", "pointer"], "stdcall");
  const HeapValidate = new NativeFunction(k32.getExportByName("HeapValidate"), "int", ["pointer", "uint32", "pointer"], "stdcall");
  const heapsBuf = Memory.alloc(4 * 64); RETAINED.push(heapsBuf);
  let heapBadSeen = false;
  const regs = (c, tag) => { if (!DIAG_REGS) return; log("[REGS] " + tag + " ebx=" + c.ebx + " esi=" + c.esi + " edi=" + c.edi + " ebp=" + c.ebp + " esp=" + c.esp); };
  const SBH_CNT = 0x9C11BC, SBH_LIST = 0x9C11C0;
  function sbhHeaders() {
    const n = safeS32(VA(SBH_CNT)), list = VA(SBH_LIST).readPointer(); const H = [];
    for (let i = 0; i < Math.min(n, 8); i++) { const h = list.add(i * 0x14); H.push({ h, commit: safeU32(h.add(8)), data: h.add(0xC).readPointer(), region: h.add(0x10).readPointer() }); }
    return { n, list, H };
  }
  function sbhStr() { try { const S = sbhHeaders(); return "SBH cnt=" + S.n + " list=" + S.list + " " + S.H.map((x, i) => "#" + i + "@" + x.h + "{data=" + x.data + " region=" + x.region + " commit=0x" + x.commit.toString(16) + "}").join(" "); } catch (e) { return "SBH err " + e; } }
  function sbhHeaderFor(p) { const S = sbhHeaders(); for (const x of S.H) { const d = p.sub(x.data).toInt32(); if (d >= 0 && d < 0x100000) return x; } return null; }
  function rearmWP(addrs, tag) {
    if (!DIAG_WP) return;
    try {
      const tid = Process.getCurrentThreadId(); const th = Process.enumerateThreads().find(x => x.id === tid);
      for (let i = 0; i < 4; i++) { try { th.unsetHardwareWatchpoint(i); } catch (e) { } }
      globalThis.WP.addrs = addrs; addrs.forEach((a, i) => th.setHardwareWatchpoint(i, a, 4, "w"));
      globalThis.WP.armed = true; log("[WP] re-armed (" + tag + ") on " + addrs.join(","));
    } catch (e) { log("[WP] re-arm failed (" + tag + "): " + e); }
  }
  function validateHeaps(tag) {
    if (!DIAG_HEAP) return;
    try {
      const n = GetProcessHeaps(64, heapsBuf); let bad = [];
      for (let i = 0; i < n && i < 64; i++) { const h = heapsBuf.add(i * 4).readPointer(); if (!HeapValidate(h, 0, ptr(0))) bad.push(h); }
      if (bad.length) { if (!heapBadSeen) { heapBadSeen = true; log("HEAP CORRUPT " + bad.join(",") + " FIRST SEEN at " + tag); } else log("HEAP corrupt (still) at " + tag); }
      else log("HEAP ok (" + n + ") at " + tag);
      const L = OBJ.add(0x444 + 0x4BC); const sl = []; for (let i = 0; i < 20; i++) { const v = L.add(i * 4).readU32(); if (v) sl.push(i + ":0x" + v.toString(16)); }
      try {
        const fb = VA(0x668F10).readPointer();
        if (!fb.isNull()) { const fi = bufInfo(fb); log("FRAMEBUF g_frame_buf=" + fb + " (obj 0x588 -> " + fb.add(0x588) + ") plane=" + fi.data + ".." + fi.data.add(fi.pitch * fi.h) + " " + fi.w + "x" + fi.h + " pitch " + fi.pitch + " clip=" + rstr(fb.add(0x20)) + (globalThis.SBH ? " SBH hdr=" + globalThis.SBH.hdr + " region=" + globalThis.SBH.region : "") + " at " + tag); }
        else log("FRAMEBUF g_frame_buf=NULL at " + tag);
      } catch (e) { log("FRAMEBUF err " + e); }
      log(sbhStr() + " at " + tag);
      log("LINKS canvas +0x4AC=" + OBJ.add(0x444 + 0x4AC).readS32() + " spot@4B0=0x" + OBJ.add(0x444 + 0x4B0).readU32().toString(16) + " cap=" + OBJ.add(0x444 + 0x4B4).readS32() + " used=" + OBJ.add(0x444 + 0x4B8).readS32() + " slots " + (sl.length ? sl.join(" ") : "all 0") + " at " + tag);
    } catch (e) { log("HEAP validate error at " + tag + ": " + e); }
  }
  // ---------------- v11 (b): canvas backdrop dither restripe (P law, per-draw pair) ----------------
  const BISECT_RESTRIPE = true;    // v12: restripes ON (the v11 crash was the 0x42C05C attach, not the frames)
  function detectPairCol(u8, pitch, x, y0, y1) {
    const cnt = new Map();
    for (let y = y0; y < y1; y++) { const v = u8[y * pitch + x]; cnt.set(v, (cnt.get(v) || 0) + 1); }
    const top2 = [...cnt.entries()].sort((p, q) => q[1] - p[1]).slice(0, 2);
    if (top2.length < 2) return null;
    const a = top2[0][0], b = top2[1][0], H = y1 - y0;
    if (top2[0][1] + top2[1][1] < 0.6 * H) return null;
    let run = 0, prev = -1, first = -1;
    for (let y = y0; y < y1; y++) {
      const v = u8[y * pitch + x];
      if (v !== a && v !== b) { prev = -1; run = 0; continue; }
      if (first < 0) first = v;
      if (v === prev) { if (++run > 3) return null; } else { prev = v; run = 1; }
    }
    return [first, first === a ? b : a];
  }
  let restripeN = 0;
  const CANON_TOP = new Map([[196, 65], [174, 238], [65, 198]]);   // top -> bottom
  function restripeRect(buf, l, t, r, b, tag) {
    if (!BISECT_RESTRIPE) { log("RESTRIPE " + tag + " skipped (bisect)"); return; }
    const bi = bufInfo(buf); if (bi.data.isNull()) return;
    l = Math.max(0, l); t = Math.max(0, t); r = Math.min(bi.w, r); b = Math.min(bi.h, b);
    if (r - l < 8 || b - t < 8) return;
    const u8 = new Uint8Array(bi.data.readByteArray(bi.pitch * bi.h));
    let pair = null;
    for (const fx of [0.5, 0.3, 0.7, 0.15, 0.85]) { pair = detectPairCol(u8, bi.pitch, l + Math.floor((r - l) * fx), t + 4, b - 4); if (pair) break; }
    restripeN++;
    if (!pair) { if (restripeN <= 6) log("RESTRIPE " + tag + " (" + l + "," + t + ")..(" + r + "," + b + "): no pair detected"); return; }
    // v12h: canonical stripe-top colour (pristine: navy 196 over black 65; selected teal 174 over violet 238; chrome black
    //   65 over 198). Detection order = whichever colour the sampled column starts with -> flips per row when a row's
    //   height is odd (4K rows 41 px: alternate rows inverted = "heavy banding", user shot 020713).
    if (CANON_TOP.get(pair[1]) === pair[0]) pair = [pair[1], pair[0]];
    else if (CANON_TOP.get(pair[0]) !== pair[1] && restripeN <= 12) log("RESTRIPE " + tag + ": uncanonical pair " + pair.join("/") + " (kept detection order)");
    const [top, bot] = pair; let n = 0;
    for (let y = t; y < b; y++) {
      const c = SL.stripeTop(y, g, 0) ? top : bot, o = y * bi.pitch;
      const row = new Uint8Array(u8.buffer, o + l, r - l); let dirty = false;
      for (let i = 0; i < row.length; i++) { const v = row[i]; if (v === top || v === bot) { if (v !== c) { row[i] = c; n++; } dirty = true; } }
      if (dirty) bi.data.add(o + l).writeByteArray(row.slice().buffer);   // v11c: a VIEW would write the whole 2.7 MB canvas buffer from here (heap corruption)
    }
    if (restripeN <= 6) log("RESTRIPE " + tag + " (" + l + "," + t + ")..(" + r + "," + b + ") pair " + top + "/" + bot + " (" + pal(top).join(",") + " / " + pal(bot).join(",") + ") P=" + SL.stripePeriod(g, 0) + " rewrote " + n + " px");
  }
  // v12b: (a) the ListBox's Win-layer V scrollbar is created inside Win_init (0x5EBD80) at BUILD with
  //   g_scrollbar_w NATIVE (20 px at every g -> "elongated" bar, native arrow squares). The baked LBRES call-helpers
  //   (popup_listbox_reserve) scale that load x g/16 when g_popup_active != 0, and thunk_dw_sbv @0x5EC42C registers
  //   the new bar in g_rail_sb (pref_sbzoom/btn_stripes zoom its arrows + thumb). Arm g_popup_active ONLY while
  //   Win_init runs for the DL ListBox window (OBJ+0xF670) - the flag also gates lbcalc/btn_shrink/popup centring.
  //   (b) list rows: the DL list-background painter 0x42A100 tiles the navy 1px dither natively -> JS restripe of the
  //   ListBox canvas rect at its return (selected-row tile is drawn later by ListBox_draw_item: still 1px, TODO).
  const G_POPUP_ACTIVE = 0xA0C530, G_FILEDLG_ACTIVE = 0xA0E3A0, G_RAIL_SB = 0xA1D260, SB_VTBL = 0x669D58;
  Interceptor.attach(VA(0x5EBD80), {
    onEnter() {
      this.arm = false;
      if (g > 16 && this.context.ecx.equals(OBJ.add(0xF670))) { this.arm = true; this.old = VA(G_POPUP_ACTIVE).readS32(); VA(G_POPUP_ACTIVE).writeS32(1); log("[SB] Win_init(DL ListBox " + this.context.ecx + "): g_popup_active " + this.old + " -> 1 (bar width scales x g/16)"); }
    },
    onLeave() {
      if (!this.arm) return;
      VA(G_POPUP_ACTIVE).writeS32(this.old);
      const sb = OBJ.add(0xF670 + 0x43C).readPointer();
      let vt = 0; try { vt = sb.isNull() ? 0 : sb.readU32(); } catch (e) { }
      log("[SB] Win_init leave: V bar [+0x43C]=" + sb + " vtbl=" + hex(vt) + (vt === SB_VTBL ? " (ScrollBar)" : "") + " screen=" + (sb.isNull() ? "-" : rstr(sb.add(0x13C))) + " local=" + (sb.isNull() ? "-" : rstr(sb.add(0x474))) + " g_rail_sb=" + VA(G_RAIL_SB).readPointer());
      if (!sb.isNull() && vt === SB_VTBL && VA(G_RAIL_SB).readU32() !== sb.toInt32() >>> 0) { VA(G_RAIL_SB).writePointer(sb); log("[SB] g_rail_sb <- DL list bar " + sb); }
    }
  });
  // v12g (a): LIST ROWS. DatalinkWin_list_bg_fill (0x42A100, call @0x42A140) and DatalinkWin_list_row_bg (0x42A150,
  //   call @0x42A1F7; state 0 unsel / 1 hover 0x78D980 / 2 selected 0x78D9A8) tile a 1px navy/black (or violet/teal)
  //   dither at 1:1 -> every row banded 1/1 at any g (user 1600/4K shots: x=300 / x=1100 columns alternate 1 px).
  //   v12b restriped OBJ+0x444 over the window rect at the bg painter's return: wrong buffer/rect, and the rows are
  //   re-tiled per row afterwards anyway. Fix: hook Buffer_tile by RETURN ADDRESS and restripe exactly the tiled rect
  //   in the tile's dest Buffer (ecx) at the P law, per state pair (auto-detected). Bake = a tail thunk at each site.
  const A_BUF_TILE = 0x5DA860;
  const TILE_RETS = new Map([[0x42A145, "list_bg"], [0x42A1FC, "list_row"]]);
  let tileN = 0;
  Interceptor.attach(VA(A_BUF_TILE), {
    onEnter() {
      this.tag = null;
      if (g <= 16) return;
      const tag = TILE_RETS.get(this.returnAddress.toInt32() >>> 0); if (!tag) return;
      const sp = this.context.esp;
      this.tag = tag; this.dest = this.context.ecx;
      this.x = safeS32(sp.add(0x10)); this.y = safeS32(sp.add(0x14)); this.w = safeS32(sp.add(0x18)); this.h = safeS32(sp.add(0x1C));
      tileN++;
      if (tileN <= 8) log("[TILE] " + tag + " dest=" + this.dest + " sprite=" + sp.add(4).readPointer() + " srcOff=" + safeS32(sp.add(8)) + "," + safeS32(sp.add(0xC)) + " at " + this.x + "," + this.y + " " + this.w + "x" + this.h + " (dest " + bufInfo(this.dest).w + "x" + bufInfo(this.dest).h + ")");
    },
    onLeave() {
      if (!this.tag) return;
      restripeRect(this.dest, this.x, this.y, this.x + this.w, this.y + this.h, this.tag);
    }
  });
  // v12g (b): clip-aware wrapper for the HC sites. hollow_flat's enlarge ignores the dest clip; restore the outside.
  let hcN = 0;
  Interceptor.attach(VA(T_HOLLOW_FLAT), {
    onEnter() {
      this.snap = null;
      if (g <= 16 || !CLIP_RETS.has(this.returnAddress.toInt32() >>> 0)) return;
      const dest = this.context.ecx, rp = this.context.esp.add(4).readPointer();
      const pset = "0x" + (this.context.esp.add(8).readPointer().sub(VA(0x400000)).toInt32() + 0x400000).toString(16);
      const bi = bufInfo(dest); if (bi.data.isNull()) return;
      const L = safeS32(rp), T = safeS32(rp.add(4)), R = safeS32(rp.add(8)), B = safeS32(rp.add(12));   // inclusive (stub)
      const clip = [safeS32(dest.add(0x20)), safeS32(dest.add(0x24)), safeS32(dest.add(0x28)), safeS32(dest.add(0x2C))];
      const x0 = Math.max(0, L - 2), y0 = Math.max(0, T - 2), x1 = Math.min(bi.w, R + 4), y1 = Math.min(bi.h, B + 4);
      if (x1 <= x0 || y1 <= y0) return;
      const rows = [];
      for (let y = y0; y < y1; y++) rows.push(bi.data.add(y * bi.pitch + x0).readByteArray(x1 - x0));
      this.snap = { bi, clip, x0, y0, x1, y1, rows, rect: [L, T, R, B], ra: this.returnAddress, pset };
    },
    onLeave() {
      if (g > 16) { try { VA(0xA0E554).writeS32(0); } catch (e) { } }   // v12k: g_fc_exact can never leak past a hollow_flat return
      const S = this.snap; if (!S) return;
      const [cl, ct, cr, cb] = S.clip; let n = 0;
      for (let y = S.y0; y < S.y1; y++) {
        const row = S.rows[y - S.y0], base = S.bi.data.add(y * S.bi.pitch + S.x0);
        if (y < ct || y >= cb) { base.writeByteArray(row); n += S.x1 - S.x0; continue; }
        const u8 = new Uint8Array(row);
        if (cl > S.x0) { const k = Math.min(cl, S.x1) - S.x0; base.writeByteArray(u8.slice(0, k).buffer); n += k; }
        if (cr < S.x1) { const o = Math.max(cr, S.x0) - S.x0; base.add(o).writeByteArray(u8.slice(o).buffer); n += S.x1 - S.x0 - o; }
      }
      hcN++;
      if (hcN <= 80) log("[HC] clipped thick frame @" + hex(S.ra.toInt32() - 5) + " rect(incl)=" + S.rect.join(",") + " clip=" + S.clip.join(",") + " restored " + n + " px outside clip set=" + S.pset);
    }
  });
  // v12h: the v12c (netwin re-assert after pref_sbzoom + gate diag) and v12e (native rect at the painter's box_sprite
  //   call + ring diag) blocks were DELETED by the v12g region replace (they lived between the old 0x42A100 attach and
  //   this line) -> chevrons shrank on hover again (user 4K/1600 shots 0205xx/020713). Re-inserted verbatim.
  // v12c: HOVER SHRINK (user 4K shots 012154/012209: chevron 40 px on first draw, 16 px after hover). The first draw
  //   runs inside thunk_pref_sbzoom's bracket (g_rail_sb match -> g_netwin_active=1 around ScrollBar_draw) and its tail
  //   thunk_sb_restripe CLOSES that bracket by writing g_netwin_active=0 -- clobbering the flag this proto holds for the
  //   whole exec. Every later thunk_btn_gate check (arrow hover/press redraw via FlatButton_content_draw, wing buttons)
  //   then MISSes -> native 9-slice + chevron. Fix: re-assert the flag when pref_sbzoom returns during exec (a bake
  //   gives DL its own OR-flag in btn_gate, so the sb_restripe close is harmless there). Diagnostics: gate_pre in/out
  //   for the two arrow buttons of g_rail_sb (esi == sb+0xAAC / sb+0x15F8).
  const T_PREF_SBZOOM = 0xA16DB0, T_BTN_GATE_PRE = 0xA22DA0, G_NETWIN = 0xA10800;
  let sbzoomN = 0, gateN = 0;
  function isRailArrow(p) {
    const sb = VA(G_RAIL_SB).readPointer(); if (sb.isNull()) return 0;
    if (p.equals(sb.add(0xAAC))) return 1; if (p.equals(sb.add(0x15F8))) return 2; return 0;
  }
  Interceptor.attach(VA(T_PREF_SBZOOM), {
    onEnter() { this.rail = this.context.ecx.equals(VA(G_RAIL_SB).readPointer()); },
    onLeave() {
      if (!this.rail) return;
      sbzoomN++;
      const nw = VA(G_NETWIN).readS32();
      if (g > 16 && inExec && nw === 0) { VA(G_NETWIN).writeS32(1); if (sbzoomN <= 6) log("[SB] pref_sbzoom leave #" + sbzoomN + ": sb_restripe closed the netwin bracket -> re-asserted g_netwin_active=1 (exec)"); }
      else if (sbzoomN <= 6) log("[SB] pref_sbzoom leave #" + sbzoomN + ": netwin=" + nw + " inExec=" + inExec);
    }
  });
  Interceptor.attach(VA(T_BTN_GATE_PRE), {
    onEnter() { this.arrow = isRailArrow(this.context.esi); this.esi = this.context.esi; },
    onLeave(rv) {
      if (!this.arrow) return;
      gateN++;
      if (gateN <= 12) log("[SB] btn_gate_pre arrow#" + this.arrow + " esi=" + this.esi + " state=" + safeS32(this.esi.add(0xAB8)) + " popup=" + VA(G_POPUP_ACTIVE).readS32() + " netwin=" + VA(G_NETWIN).readS32() + " -> " + rv.toInt32() + " (w,h=" + safeS32(this.esi.add(0x4C4)) + "," + safeS32(this.esi.add(0x4C8)) + ")");
    }
  });
  // v12e: (a) HOVER HIGHLIGHT clipped right/bottom on BACK/EXIT (user 1600 shots 014137/014148: hover face's bright
  //   edge 2 px on top/left, ABSENT right/bottom). FlatButton_content_draw with a box-sprite face set (+0xAC8, the wing
  //   set) calls Buffer_box_sprite(&localRect, params) @0x607F60 with the DEVICE-size local rect (0,0,W,H) while
  //   thunk_btn_shrink has descaled the canvas w/h (+0x4C4/+0x4C8) to native: the right/bottom edge slices land past
  //   the shrunk w/h and are clamped away, then thunk_btn_2dscale zooms a render that never had them (the popup
  //   family's buttons use the per-sprite +0xB10 branch, positioned FROM the shrunk w/h, so the bake never hit it).
  //   Fix: while g_btn_pending is armed, hand that call a NATIVE-size rect (L,T,L+nativeW,T+nativeH) (same for all
  //   16 wing buttons + BACK/EXIT, every state).  Bake = a 5-B redirect of the E8 @0x607F60 to a cave helper.
  //   (b) DIAGNOSTIC: the outer window border's bright bevel line (73,108,61) is 1 px on the RIGHT at 1600/4K but 2 px
  //   left/top/bottom -> dump the canvas ring RLE at BUILD leave and after draw_page #1 to see which draw owns it.
  const G_BTN_PENDING = 0xA0C534, A_BOX_SPRITE_RET = 0x607F65;
  const nrScratch = Memory.alloc(16); RETAINED.push(nrScratch);
  let nrN = 0;
  Interceptor.attach(VA(A_BOX_SPRITE), {
    onEnter() {
      if (g <= 16 || !this.returnAddress.equals(VA(A_BOX_SPRITE_RET))) return;
      if (VA(G_BTN_PENDING).readS32() !== 1) return;
      const btn = this.context.esi, rp = this.context.esp.add(4).readPointer();
      const L = safeS32(rp), T = safeS32(rp.add(4)), R = safeS32(rp.add(8)), B = safeS32(rp.add(12));
      const nw = safeS32(btn.add(0x4C4)), nh = -safeS32(btn.add(0x4C8));
      nrN++;
      if (R - L <= nw || nw <= 0 || nh <= 0) { if (nrN <= 8) log("[BTNRECT] box_sprite rect (" + L + "," + T + "," + R + "," + B + ") native " + nw + "x" + nh + " btn=" + btn + " -> left alone"); return; }
      nrScratch.writeS32(L); nrScratch.add(4).writeS32(T); nrScratch.add(8).writeS32(L + nw); nrScratch.add(12).writeS32(T + nh);
      this.context.esp.add(4).writePointer(nrScratch);
      if (nrN <= 8) log("[BTNRECT] box_sprite rect (" + L + "," + T + "," + R + "," + B + ") -> native (" + L + "," + T + "," + (L + nw) + "," + (T + nh) + ") btn=" + btn + " state=" + safeS32(btn.add(0xAB8)) + " hover=" + safeS32(btn.add(0xA74)));
    }
  });
  function rle(u8, off, n) {
    const out = []; let prev = -1, run = 0;
    for (let i = 0; i < n; i++) { const v = u8[off + i]; if (v === prev) run++; else { if (run) out.push(prev + "x" + run); prev = v; run = 1; } }
    if (run) out.push(prev + "x" + run); return out.join(" ");
  }
  function ringProfile(tag) {
    if (g <= 16) return;
    const bi = bufInfo(OBJ.add(0x444)); if (bi.data.isNull()) return;
    const y = bi.h >> 1, l = s(0x17), r = s(0x309);
    const row = new Uint8Array(bi.data.add(y * bi.pitch).readByteArray(bi.w));
    log("[RING] " + tag + " y=" + y + " L[" + (l - 2) + "..]: " + rle(row, Math.max(0, l - 2), 24) + " | R[.." + (r + 2) + "]: " + rle(row, r - 22, 24) + " (canvas " + bi.w + "x" + bi.h + ")");
  }
  let lbDrawN = 0;
  // v12: content restripe at the PAGE PAINTERS' entries (function entries = safe attach points). draw_page draws its
  // three frames, hides the TextScrolls, then dispatches to one painter per category (jump table 0x42C29C).
  const PAINTERS = [0x42C2E0, 0x42C650, 0x42C9C0, 0x42D610, 0x42DEF0, 0x42E2E0, 0x42E8E0, 0x42EE30, 0x42F490, 0x42FAD0, 0x430090, 0x430770, 0x430C80, 0x431180];
  function restripeContentUnion(tag) {
    if (g <= 16) return;
    const cu = OBJ.add(0x10334);
    restripeRect(OBJ.add(0x444), safeS32(cu), safeS32(cu.add(4)), safeS32(cu.add(8)), safeS32(cu.add(12)), "content_union@" + tag);
  }
  for (const pa of PAINTERS) Interceptor.attach(VA(pa), { onEnter() { restripeContentUnion(hex(pa)); } });

  // ---------------- v5 (c) mono tech icon: recolour after the scaled draw ----------------
  function bufInfo(buf) {
    const w = safeS32(buf.add(0x80)); let h = safeS32(buf.add(0x84)); if (h < 0) h = -h;
    let data = ptr(0); try { data = buf.add(0x54).readPointer(); } catch (e) { }
    const p1 = safeS32(buf.add(0x4A4)), p2 = safeS32(buf.add(0x4A8));
    const pitch = (p2 >= w && p2 <= w + 8) ? p2 : ((p1 >= w && p1 <= w + 8) ? p1 : ((w + 3) & ~3));
    return { w, h, data, pitch };
  }
  let monoN = 0;
  Interceptor.attach(VA(0x5E3E00), {
    onEnter() {
      this.snap = null;
      const ra = this.returnAddress.sub(VA(0)).toInt32();
      if (ra === 0x49A2D4) regs(this.context, "mono enter");
      if (ra !== 0x49A2D4 || g <= 16 || !inExec) return;
      const sp = this.context.esp, spr = this.context.ecx;
      const dest = sp.add(4).readPointer(), key = safeS32(sp.add(8)), x = safeS32(sp.add(12)), y = safeS32(sp.add(16)), col = safeS32(sp.add(20)), num = safeS32(sp.add(24)), den = safeS32(sp.add(28));
      const bi = bufInfo(dest); monoN++;
      if (monoN === 1) { const pl = []; for (let i = 0; i < 256; i++) pl.push(i + ":" + pal(i).join(",")); log("PALETTE " + pl.join(" ")); }
      // target = the index the engine just drew the category text ("DISCOVER 1") in: sample the band above the icon
      let best = -1;
      if (!bi.data.isNull()) {
        const hist = new Map();
        const tx0 = Math.max(0, x - s(40)), tx1 = Math.min(bi.w, x + s(90)), ty0 = Math.max(0, y - s(26)), ty1 = Math.max(0, y - s(8));
        for (let yy = ty0; yy < ty1; yy++) { const row = new Uint8Array(bi.data.add(yy * bi.pitch + tx0).readByteArray(tx1 - tx0)); for (const v of row) hist.set(v, (hist.get(v) || 0) + 1); }
        const cand = [...hist.entries()].filter(([i]) => { const c = pal(i); return (c[0] + c[1] + c[2]) > 120; }).sort((a, b) => b[1] - a[1]);
        if (cand.length) best = cand[0][0];
        if (monoN <= 4) log("MONO text band (" + tx0 + "," + ty0 + ")..(" + tx1 + "," + ty1 + ") top idx: " + cand.slice(0, 4).map(([i, c]) => i + "x" + c + "=" + pal(i).join(",")).join(" "));
      }
      if (best < 0) { let bestD = 1e9; for (let i = 0; i < 256; i++) { const c = pal(i); const d = (c[0] - 173) ** 2 + (c[1] - 196) ** 2 + (c[2] - 192) ** 2; if (d < bestD) { bestD = d; best = i; } } }
      if (monoN <= 4) log("MONO icon: sprite=" + spr + " dest=" + dest + " (" + bi.w + "x" + bi.h + " pitch " + bi.pitch + ") key=" + key + " xy=" + x + "," + y + " colourArg=" + hex(col) + " engine idx " + (col & 0xff) + "=" + pal(col & 0xff).join(",") + " -> target idx " + best + "=" + pal(best).join(",") + " num/den=" + num + "/" + den + (dest.equals(OBJ.add(0x444)) ? " [DL canvas]" : ""));
      if (bi.data.isNull() || den <= 0 || num <= 0) return;
      const w = num + 4, h = num * 2 + 4;                                   // dims are lazy-loaded; icons are ~square, num = drawn width
      const x0 = Math.max(0, x - 1), y0 = Math.max(0, y - 1), x1 = Math.min(bi.w, x0 + w), y1 = Math.min(bi.h, y0 + h);
      if (x1 <= x0 || y1 <= y0) return;
      const rows = [];
      for (let yy = y0; yy < y1; yy++) rows.push(new Uint8Array(bi.data.add(yy * bi.pitch + x0).readByteArray(x1 - x0)));
      this.snap = { bi, x0, y0, x1, y1, rows, col: best };
    },
    onLeave() {
      if (this.snap) regs(this.context, "mono leave");
      const S = this.snap; if (!S) return;
      let changed = 0; const natHist = new Map();
      for (let yy = S.y0; yy < S.y1; yy++) {
        const p = S.bi.data.add(yy * S.bi.pitch + S.x0), cur = new Uint8Array(p.readByteArray(S.x1 - S.x0)), before = S.rows[yy - S.y0];
        let dirty = false;
        for (let i = 0; i < cur.length; i++) if (cur[i] !== before[i]) { natHist.set(cur[i], (natHist.get(cur[i]) || 0) + 1); cur[i] = S.col; dirty = true; changed++; }
        if (dirty) p.writeByteArray(cur);
      }
      validateHeaps("mono leave"); if (monoN <= 4) log("MONO icon recoloured " + changed + " px -> index " + S.col + " in (" + S.x0 + "," + S.y0 + ")..(" + S.x1 + "," + S.y1 + ") native-drawn idx: " + [...natHist.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([i, c]) => i + "x" + c).join(" "));
    }
  });

  // ---------------- v12i (1): DL console save-under (diplo t_cr_snap class) ----------------
  // tile_panels 0x45C290 restores console art positionally from the NATIVE art object — wrong + clamped at g>16.
  // Snapshot the inter-panel gap band (x D80.R..D90.L, y 0..DB0.T+2 of the MainWin strip canvas) at DL iface
  // ENTER (the canvas still holds the plain HUD console), restore after every big==0 tile_panels + soft_update.
  // Same rect law + hosts as hook_tile_restore_proto v5 (user-verified 4K); attach hosts proven safe there.
  const MAINWIN = VA(0x7AE820), MW_CANVAS = VA(0x7AEC64), G_BIG_CENTER = VA(0x7D3930);
  const mwSoftUpdate = new NativeFunction(VA(0x5D5720), "void", ["pointer", "int", "int", "int", "int"], "thiscall");
  let mwSaved = null, mwN = 0;
  function dlSnapshotGap() {
    if (g <= 16) return;
    const bi = bufInfo(MW_CANVAS); if (bi.data.isNull()) return;
    const d80 = rect4(MAINWIN.add(0xD80)), d90 = rect4(MAINWIN.add(0xD90)), db0 = rect4(MAINWIN.add(0xDB0));
    const L = Math.max(0, d80[2]), T = 0, R = Math.min(bi.w, d90[0]), B = Math.min(bi.h, db0[1] + 2);
    log("[CR] gap seeds d80=" + d80.join(",") + " d90=" + d90.join(",") + " db0=" + db0.join(",") +
        " centre_seed=" + rstr(OBJ.add(0x10374)) + " canvas " + bi.w + "x" + bi.h);
    if (R <= L || B <= T) { log("[CR] degenerate gap — no snapshot"); return; }
    const rows = [];
    for (let y = T; y < B; y++) rows.push(new Uint8Array(bi.data.add(y * bi.pitch + L).readByteArray(R - L)));
    mwSaved = { L, T, R, B, rows };
    log("[CR] snapshot gap (" + L + "," + T + ")-(" + R + "," + B + ") " + (R - L) + "x" + (B - T));
  }
  Interceptor.attach(VA(0x45C290), {
    onEnter() { this.big = safeS32(G_BIG_CENTER); },
    onLeave() {
      if (g <= 16 || this.big || !mwSaved) return;
      try {
        const bi = bufInfo(MW_CANVAS); if (bi.data.isNull()) return;
        for (let y = mwSaved.T; y < mwSaved.B; y++)
          bi.data.add(y * bi.pitch + mwSaved.L).writeByteArray(mwSaved.rows[y - mwSaved.T].buffer);
        mwSoftUpdate(MAINWIN, mwSaved.L, mwSaved.T, mwSaved.R - mwSaved.L, mwSaved.B - mwSaved.T);
        mwN++; if (mwN <= 10) log("[CR] restored gap (" + mwSaved.L + "," + mwSaved.T + ")-(" + mwSaved.R + "," + mwSaved.B + ") after tile_panels(big=0)");
      } catch (e) { log("[CR] restore failed: " + e); }
    }
  });

  // ---------------- v5 (d) hover / connector instrumentation ----------------
  function dwords(p, n) { let d = []; for (let j = 0; j < n; j++) d.push(safeS32(p.add(j * 4))); return d.join(","); }
  let hovN = 0, connN = 0;
  Interceptor.attach(VA(0x49B220), { onEnter() {
    hovN++; const sp = this.context.esp; const rw = VA(0x876478);
    if (hovN <= 40) log("TECH_HOVER #" + hovN + " id=" + hex(safeU32(sp.add(4))) + " flag=" + safeS32(sp.add(8)) + " cols 594C/5950/5954/5958=" + [0x594C, 0x5950, 0x5954, 0x5958].map(o => safeS32(rw.add(o))).join(",") + " rows 595C..5970=" + [0x595C, 0x5960, 0x5964, 0x5968, 0x596C, 0x5970].map(o => safeS32(rw.add(o))).join(",") + (safeU32(sp.add(4)) >= 0x378 ? " btnrect=" + rstr(rw.add((safeU32(sp.add(4)) - 0x378) * 0xB4C + 0xB74)) : ""));
  } });
  Interceptor.attach(VA(0x49B450), {
    onEnter() {
      arrowPending = null; regs(this.context, "connector enter");
      connN++; const sp = this.context.esp; const rw = VA(0x876478);
      if (connN <= 48) log("CONNECTOR #" + connN + " ecx=" + this.context.ecx + " args(x1,y1,x2,y2,btnW,btnH,hover)=" + dwords(sp.add(4), 7) + " ret=" + this.returnAddress + " cols=" + [0x594C, 0x5950, 0x5954, 0x5958].map(o => safeS32(rw.add(o))).join(",") + " card@A28=" + rstr(rw.add(0xA28)));
    },
    onLeave() { regs(this.context, "connector leave"); validateHeaps("connector leave (before arrow)"); try { drawPendingArrow(); } catch (e) { arrowPending = null; log("ARROW draw error: " + e); } validateHeaps("connector leave (after arrow)"); }
  });

  Interceptor.attach(VA(A_BUILD), {
    onEnter() {
      g = gval();
      log("BUILD enter | " + envStr()); validateHeaps("build enter");
      try {
        if (!DIAG_WP) throw "diag off (v12k)";
        const tid = Process.getCurrentThreadId(); const th = Process.enumerateThreads().find(x => x.id === tid);
        const S0 = sbhHeaders(); globalThis.WP.addrs = [VA(SBH_CNT), VA(SBH_LIST), S0.H[0].h.add(0xC), S0.H[0].h.add(0x10)];   // v11m: sbh globals + header#0 pHeapData/pRegion
        globalThis.WP.addrs.forEach((a, i) => th.setHardwareWatchpoint(i, a, 4, "w"));
        globalThis.WP.armed = true; log("[WP] armed on sbh cnt/list + hdr0 data/region " + globalThis.WP.addrs.join(",") + " thread " + tid);
      } catch (e) { log("[WP] arm failed: " + e); }
      if (g > 16) { fillHoverStub(); applyPatches(); armRegfix(); armArrowScale(); setNetwinActive(1, "build"); } else log("g<=16: native no-op (no patches)");
    },
    onLeave() { validateHeaps("build leave (after frames)"); if (g > 16) { setNetwinActive(0, "build leave"); fixBackExitFaces(); const bi = bufInfo(OBJ.add(0x444)); restripeRect(OBJ.add(0x444), 0, 0, bi.w, bi.h, "canvas@build"); ringProfile("build leave"); } dump("post-build"); validateHeaps("build leave end"); }
  });
  Interceptor.attach(VA(A_EXEC), {
    onEnter() { const sp = this.context.esp; inExec = true; log("EXEC enter cat=" + safeS32(sp.add(4)) + " item=" + safeS32(sp.add(8)) + " | " + envStr()); validateHeaps("exec enter"); if (g > 16) { setNetwinActive(1, "exec"); applyTech(true); } },
    onLeave() { inExec = false; if (g > 16) { setNetwinActive(0, "exec leave"); applyTech(false); } log("EXEC leave"); }
  });
  Interceptor.attach(VA(A_SHOWHIDE), {
    onEnter() { this.show = safeS32(this.context.esp.add(4)); log("SHOW_HIDE show=" + this.show + " win.screen=" + rstr(OBJ.add(0x13C))); validateHeaps("show_hide enter"); if (this.show === 1) { try { dlSnapshotGap(); } catch (e) { log("[CR] snap failed: " + e); } } },
    onLeave() { validateHeaps("show_hide leave"); if (this.show) dump("after show"); }
  });
  let pageN = 0, traceFree = false, freeN = 0;
  // v11n: CRT small-block-heap + ntdll free trace while draw_page #3 runs
  if (DIAG_FREE) Interceptor.attach(VA(0x647DF4), {
    onEnter() { this.p = this.context.esp.add(4).readPointer(); },
    onLeave(rv) { if (traceFree && freeN < 40) { freeN++; log("[FREE] __sbh_find_block(" + this.p + ") -> hdr " + rv + " caller " + (globalThis.nearestSym(this.returnAddress.toInt32() >>> 0) || this.returnAddress)); } }
  });
  if (DIAG_FREE) Interceptor.attach(VA(0x647E1F), {
    onEnter() { if (traceFree && freeN < 40) { freeN++; const sp = this.context.esp; log("[FREE] __sbh_free_block(hdr=" + sp.add(4).readPointer() + ", p=" + sp.add(8).readPointer() + ")"); } },
    onLeave() { if (traceFree && freeN < 40) log("[FREE] __sbh_free_block done"); }
  });
  if (DIAG_FREE) Interceptor.attach(VA(0x644EF2), {
    onEnter() { if (traceFree && freeN < 40) { freeN++; const sp = this.context.esp; log("[FREE] free(" + sp.add(4).readPointer() + ") from " + (globalThis.nearestSym(this.returnAddress.toInt32() >>> 0) || this.returnAddress)); } }
  });
  Interceptor.attach(VA(A_DRAWPAGE), {
    onEnter() { pageN++; regs(this.context, "draw_page#" + pageN + " enter"); log("[THIS] draw_page ecx=" + this.context.ecx + " (DL=" + OBJ + ") caller " + (globalThis.nearestSym(this.returnAddress.toInt32() >>> 0) || this.returnAddress)); if (pageN === 3) { traceFree = true; freeN = 0; log("[FREE] trace ON (draw_page #3)"); } if (pageN <= 3) log("DRAW_PAGE #" + pageN + " cat=" + safeS32(OBJ.add(0x29DC)) + " item=" + safeS32(OBJ.add(0x29E0))); validateHeaps("draw_page#" + pageN + " enter"); },
    onLeave() { regs(this.context, "draw_page#" + pageN + " leave"); validateHeaps("draw_page#" + pageN + " leave"); if (pageN <= 2) { ringProfile("draw_page#" + pageN + " leave"); dump("after draw_page#" + pageN); } }
  });
  log("attached: build 0x429300 (immfix at entry), exec, show_hide, draw_page; " + P.length + " immediate sites");
}
