"""End-to-end apply check: the strong byte-exact regression lock.

Applies the live patches.yaml to a throwaway copy of the pristine .bak via the
real CLI (subprocess), then asserts the resulting MD5 equals the known-good
`patched_md5` recorded in patches.yaml. ANY change to a site or cave's resolved
output bytes moves this MD5 — so this is the gate that catches semantic drift a
disassembler can't (a valid-but-wrong instruction swap still changes the hash).

When you intentionally change the patch output, update target.patched_md5 in
patches.yaml (a deliberate, reviewed step) and this stays green.

Also pins the human-facing dry-run contract (the "Will write" / "all
verifications passed" lines) and the set of groups that apply on a clean base.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import apply_patches as ap

_APPLY = str(Path(ap.__file__).resolve())

# Groups that apply on the pristine base. The other 4 are intentionally
# site-status=skip (popup_bar_fill, win11_24h2_cs_zeroinit,
# popup_button_font_scaling, popup_qdlg_font_disarmed — the 2026-07-26 type-8
# crash disarm). If a group silently drops out of this set, a finished fix has
# regressed.
EXPECTED_ELIGIBLE_GROUPS = {
    "combat_console_scale", "msglog_scale", "ntw_scale", "popup_art_reblit",
    # 2026-10-04: console backdrop tiles + the HUD message panel on the stripe law.
    "console_tile_stripes",
    "base_cell_stripes",
    "button_grip_stripes",
    "report_energy_list_bar",
    "sprite_stripes",
    "checkbox_stripes",                # 2026-10-24 fix 28: the checkbox X sprites' scanline law
    "netwin_panel_stripes",            # 2026-10-25 fix 28 v2: the lobby panel fills on the stripe law
    "netwin_frame_strokes",            # 2026-11-07: the lobby frames on the stroke law, title rect, lock icon
    "commlink_mp_spots",               # 2026-11-07: the COMMLINK multiplayer click spots (time widget, LEDs)
    "hud_backdrop_stripes",
    # 2026-09-17: the font face/weight law helpers (no member sites; cave contents only).
    "font_face_law",
    "dl_scale",
    # 2026-09-14: the Planetary Monument (F9) full-height letterbox bake.
    "mon_scale",
    # 2026-09-14: the Hall of Fame (F10) full-height letterbox bake (same block, own group).
    "hof_scale",
    "rw_scale_shared",
    "rw_scale_tech", "listbox_hover_clamp",
    # 2026-09-08: HQ report screens, the remaining pages (F3..F8 + intel PROFILE).
    "rw_scale_kinds",
    "rail_scrollbar_scale",
    # 2026-10-11: popup screen-edge gaps (negative x/y request + the faction picker origin).
    "popup_edge_anchor_scale",
    "popup_edge_positive_scale",
    "popup_art_scaling", "popup_button_height_scaling", "popup_box_grow",
    "popup_title_scaling", "popup_button_2dzoom", "popup_wrap_width",
    "popup_list_rowheight", "popup_list_rowgap", "popup_optionlist_type8_scale",
    # 2026-07-31: type-8 sprite-ratio scaling (stack-picker measure/draw fix).
    "popup_optionlist8_spritezoom",
    "hud_ticker_rows",                 # 2026-10-12 ticker window + row tops at vanilla x g/16
    "planwin_line_scale",              # 2026-10-12 Go To map panel route line thickness
    "planwin_native_render",           # 2026-10-15 Go To map panel rendered natively, enlarged x g/16
    "popup_quit_type16_rowpitch", "popup_quit_type16_fillwidth",
    "popup_quit_type16_rowgap",
    "popup_list_checkbox_indent",
    "popup_list_checkbox_scale", "popup_button_vcenter", "popup_btnrow_center", "popup_dialog_btn_span",
    "popup_btnrow_distribute",         # 2026-10-22 fix 19: the button-row remainder, both ends flush
    "popup_button_block_frame", "popup_list_option_frame",
    "popup_outer_backdrop_scale",
    "popup_box_margin_scale", "popup_list_fill_width", "modal_scaling",
    "menu_strip_scaling", "win11_24h2_filelock_fix", "save_header_init",
    "faction_quote_textmargin", "faction_quote_fontscale",
    "faction_pickwin_geometry", "faction_pickwin_content",
    "faction_pickwin_buttons", "faction_submenu_scale",
    "faction_listrebuild_scale", "uimod_bootstrap",
    "faction_connector_scale", "popup_bubble_font_scaling",
    "popup_bubble_frame_scaling", "credits_interlude_scaling",
    "credits_menu_music_dedupe", "popup_type2_list_scale", "netwin_lobby_scale",
    "hud_console_scale",
    "hud_turn_band",
    "hud_widgets_scale",
    "filedlg_geometry", "filedlg_fonts", "filedlg_buttons", "filedlg_rows",
    "filedlg_frames", "filedlg_rowbg", "filedlg_titlerect",
    "filedlg_chrome_rails",
    "popup_chrome_rails", "popup_chrome_insets", "popup_art_align",
    "hud_minimap_fill", "hud_minimap_box", "map_recentre_fullredraw",
    # 2026-10-11: the logo.pcx startup splash scaled (t_splash_blit).
    "splash_scale",
    "map_move_line_scale",
    "commlink_menu_scale",
    "tutwin_tooltip_scale",
    "prefwin_scale",
    "map_label_fonts",
    "popup_ingame_min_boxh",
    "popup_type4_field_width",
    "scale_ratio_uncache",
    "veh_pick_single_list",
    # 2026-08-13: scenario-editor arc bake (diplo modal + editor panel + faces).
    "scenedit_scale",
    # 2026-08-18: DIPLOMACY talk screen (speech box + console-strip content).
    "diplo_talk_scale",
    # 2026-08-20: arm the rail gate around the talk window's own slide calls
    # (errant native right side-bar during the open/close slide animation).
    "diplo_slide_rails",
    # 2026-09-24: the same arm around the base screen's own slide calls (phantom
    # native right rail pair while the base screen slides up/down).
    "basewin_slide_rails",
    # 2026-09-26: the same arm around the Council + Datalinks slide calls.
    "slide_rails_council_dl",
    # 2026-09-26c: the multiplayer negotiation window (DiploWin) bake.
    "diplowin_scale",
    # 2026-08-22: PLANETARY COUNCIL screen + its popups (src assemble_council.py).
    "council_scale", "se_scale", "tech_scale",
    # 2026-08-29: DESIGN WORKSHOP bake (src assemble_dw.py) + the popup-family listbox reserve,
    # the wheel = chevron vanilla change and the picker grid-leave present fix.
    "dw_scale", "wheel_scroll", "popup_listbox_reserve", "picker_grid_leave_present",
    # basewin_interior_slice2: the 120 text/clip/font site redirects ARE applied
    # but every adapter gates on canvas Buffer w > 758, which stays false until
    # the basewin_relayout activation switches flip -> runtime-inert.
    "basewin_interior_slice2",
    "basewin_interior_slice3",
    "basewin_interior_slice4",
    "basewin_interior_slice5",
    # 2026-07-26b: SUPPORT-tab map density (embedded-MapWin rect device-scale;
    # coupled with slice-5's mapblit v3 — the water-banding fix).
    "basewin_support_mapzoom",
    "basewin_slice6_repair",
    # 2026-07-21d: yield-orb pre-call detours (the four PRACX-stomped bw4 farm
    # sites were deleted from slice4; PRACX owns their rel32 at runtime).
    "basewin_farm_orbs",
    "basewin_strip_scale",
    "basewin_strip_content",
    # 2026-07-26g: vanilla supported-list scrollbar drag-loss fix (skip the
    # per-repaint re-attach while engaged).
    "supported_sb_dragfix",
    "basewin_facsb",
    "scrollbar_drag_capture",
    # 2026-07-27 slice-10: box_2 ring outlines (production current-turn +
    # nutrients) + base_draw pop-number box pads (farm gate).
    "basewin_box2_polish",
    # ACTIVATED 2026-07-18e: the two chain-head switches are confirmed; the
    # superseded prefwin entry/vtbl sites were deleted (the basewin thunks
    # chain to the pref thunks).
    "basewin_relayout",
    # 2026-08-02i: base production picker relayout (row pitch + grid margin +
    # fonts + button row; pairs with the gwinit v4 ProdPicker exemption).
    "prodpicker_relayout",
    # 2026-10-10: the Caviar unit renderer's composite / target2 clear narrowed to the engine's dirty
    # rects (t_cav_blit / t_cav_table / t_cav_fill2; pcave2 0x30000 -> 0x31000).
    "caviar_dirty_rect",
    # 2026-10-11: map effects above the engine's 4.0 blit cap (Planet Buster cloud, combat explosions at deep
    # PRACX zoom; t_pb_draw / t_tb_draw / t_tb_fill).
    "effect_scale_cap",
    # 2026-10-25 W7R v2: the universal Menu background / rows (t_menu_border / t_menu_row, laws menu_box_rect /
    # menu_row_clip).
    "menu_box_scale",
}


def _run(args, dst):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, _APPLY, "--target", str(dst), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


@pytest.fixture
def fresh_copy(tmp_path, bak_path) -> Path:
    dst = tmp_path / "terranx_test.exe"
    shutil.copy2(bak_path, dst)
    return dst


def test_dry_run_smoke(fresh_copy):
    r = _run([], fresh_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "all verifications passed" in r.stdout
    assert "Will write: 1436 site(s), 2 cave(s)" in r.stdout   # 2026-11-07 +11: netwin_frame_strokes +7 (NetWin_draw.outline_d5a0_title -> t_nwf_title, .title_band_inset -> t_nwf_ins3, the options / chat / players / settings d5a0 outlines -> t_nwf_bm, NetWin_setup_lobby.chat_log_attach -> t_nwf_ts (law nw_chat_log_inset): the lobby frames on the stroke law, laws nw_frame_bands / nw_title_band_inset / nw_title_rect_bottom; the 17 netwin_panel_stripes sites and NetWin_draw_players.toggle retargeted in place to t_nwf_box / t_nwf_lock) + commlink_mp_spots +4 (commlink_draw_mp_header.time_spot -> t_clmp_hdr, commlink_redraw.mp_strip_clip -> t_clmp_clip, commlink_redraw.mp_strip_spot -> t_clmp_strip, commlink_draw_faction_row.mute_led_spot -> t_clmp_led: the COMMLINK multiplayer click spots + the strip text's clip, law commlink_spot) (1436); 2026-10-27 W8T +3 popup_list_rowgap CheckList_draw_item.row_top / .label_top / CheckList_on_click.row_at (-> t1c_rowtop / t1c_label / t1c_hit: the type-1 popup checkbox rows on one pitch half_down(22g, 16), equal gaps, the labels lifted to end on the bars' last rows; laws type1_row_top / type1_label_lift / type1_row_at) (1425); 2026-10-25 W7R v2 +2 menu_box_scale g_menu_border_draw.box / g_menu_hilite_draw.box (-> t_menu_border / t_menu_row: the universal Menu fill on the stripe law, K x K notch, row inset K, laws menu_box_rect / menu_row_clip; the popup option-row site retargeted in place to t_rowbox_solid, law ring_solid) (1422); 2026-10-25 W6B +2 council_scale CouncilWin_draw_column.frame_inset / .chip_fix (-> t_cw_inset / t_cw_chipfix: the column interior inset = the stroke width, the chip dp(4) inside its column, laws council_frame_inset / council_chip_rects v2) (1420); 2026-10-25 W6C +1 rw_scale_tech tech_page.research_ring (detour -> t_rw_ring: the research ring inset K, law rw_tech_ring_clip) (1418); 2026-10-25 W4C +1 se_scale SocialWin_repaint.union_frame (-> t_bm_ho_hf: the OK / RESET / CANCEL union frame K-wide on its half-open rect, law se_frame_draw_rect) (1417); 2026-10-25 W2C +1 hud_console_scale MainWin_draw_box9.outer_frame (-> t_box9_outer: the box-9 outer frame nested s(3) inside the right console panel, law hud_box9_outer_rect) (1416); 2026-10-25 W2D +1 faction_pickwin_buttons FactionPickWin_row_painter.rowbox (-> t_fac_rowbox: the name rows' s x s background notches + K hover bands under the text, law faction_row_face) (1415); 2026-10-25 W2A +3 council_scale CouncilWin_repaint.console_box / CouncilWin_draw_proposal.header_band / .body_box (-> t_rw_rowframe, law council_console_frame_rect) (1414); 2026-10-25 fix 28 v2 +17 netwin_panel_stripes (the NetWin lobby's filled Buffer_box_sprite panel sites -> t_nw_box: the fill tile's pair on the stripe law, law panel_fill_pixel) (1411); 2026-10-24 W1A +1 popup_dialog_btn_span BasePop_calculate_dimensions.dialog_btn_span (-> t_btn_vgap: the dialog -> button-row span fl(12g/16) with no body text, law popup_box_h_btn_pad) (1394); 2026-10-24 fix 26 +1 popup_chrome_insets Popup_calc.ornate_margin_r (-> t_orn_rmargin: the ornate 2/6 right content margin 19 at g > 16, law ornate_popup_margin_r) (1393); 2026-10-23 fix 24 +1 scenedit_scale MainWin_build.ed_info_right (-> t_ed_info_right: the scenario-editor info rect's right pad s(3), law editor_info_right) (1392); 2026-10-22 fix 19 +4 popup_btnrow_distribute (BasePop_calculate_dimensions.btnrow_rem_stash -> t_btnrow_stash; BasePop_exec_3.btnrow_init_extra1 / _loop / _extra2 -> t_btnrow_init: the button-row remainder distributed) (1391); 2026-10-22 fix 18 -1 popup_edge_positive_scale NetMsg_pop.set_loc_args (t_netmsg_loc backed out, user decision: the call is vanilla) (1388); 2026-10-18 fix 14 -2 popup_title_scaling Popup_on_draw_background.title_font / .title_textnudge (retired to the skippable popup_title_font_retired: titled popups keep vanilla's 0x7CFE8C, law-scaled by thunk_hud_font, and the writer's own centring) (1390); 2026-10-18 fix 13 +5 menu_strip_scaling on g (SetupWin_do_menu_rightside.separator_fill_scaled_loop2 / spot_left_scaled / title_inset_scaled, SetupWin_draw_item.strip_dstx_scaled / text_rect_lr_scaled: the close-animation separator + the native constants left inside the scaled strip, law menu_strip_layout) (1390); 2026-10-18 fix 12 -7 faction_pickwin_content FactionPickWin_build.font_* (retired to the skippable faction_pickwin_font_retired: the picker keeps vanilla's 0x7CFE8C, law-scaled by thunk_hud_font) (1385); 2026-10-18 fix 9 +1 rw_scale_kinds ReportIf_console_chrome.strip_anchor (t_rwk_stripanchor: the kind-icon strip drawn from the left panel's right stroke, law rw_strip_anchor) (1392); 2026-10-17m +4 popup_edge_positive_scale (TutWin_tut_win.edge_gap -> t_tw_gap, BasePop_start.script_x_loc/_y_loc -> t_scrloc_x/_y, NetMsg_pop.set_loc_args -> t_netmsg_loc) (1391); 2026-10-17h +24 HQ report console chain (24 console d528 box draws -> t_rw_rowframe) (1387); 2026-10-17e +16 HQ report console tab pairs v2 (F2 labs: 4 cursor w/h detours + tab box -> t_rwk_boxforce + 3 d528 -> t_rw_rowframe; console chrome centre/strip d528 -> t_rw_rowframe; F4 ops tab box w + BEST BASES list x/w, governor list cursor, F6 / F4-mode tab row w) (1363); 2026-10-15 +5 planwin_native_render (render / overlay_draw / fit_two / fit_one entries + the present) -1 PlanWin_overlay_draw.route_line -1 PlanWin_open.zoom_init (1347); 2026-10-14f -2 planwin_zoom_floor v2 (fit_two/fit_one back-off back to the engine dec; option (a)) (1344); 2026-10-14b +2 rw_scale_kinds (ReportWin_draw_bases.rowstep -> t_rw_bases_rowstep: F4 rows at cum(k); ReportWin_draw_energy.row_stride -> t_rw_energy_stride: F3 stride s(18)) (1346); 2026-10-14 +1 planwin_line_scale MapWin_direct_dest_line.dash_line (main-map dashed order lines -> t_pw_line) (1344); 2026-10-12c +3 planwin_zoom_floor (fit_two/fit_one back-off, open init -> t_pw_zdec/t_pw_zinit) (1343); 2026-10-12b +1 planwin_line_scale (PlanWin_overlay_draw route line -> t_pw_line) (1340); 2026-10-12 +2 hud_ticker_rows (MainWin_build.ticker_attach -> t_ticker_attach, TextScroll_draw.ticker_wraph -> t_ticker_wraph) (1339); 2026-10-11j +1 popup_optionlist8_spritezoom OptionList_calc.list_gap (t_ol8_calcgap: row window reserves the scaled column gap) (1337); 2026-10-11i +1 prodpicker_relayout ProdPicker_draw_cell.selbox (t_pp_selbox: selected-cell outline inside the frame stroke) (1336); 2026-10-11h +1 rw_scale_kinds ListBox_close.report_text_pad (t_lb_textpad: report-list text pad s(3)-1) (1335); 2026-10-11g +1 rw_scale_kinds v18 ReportWin_draw_units.rowstep (t_rwk_units_rowstep: units rows at cum(k)) (1334); 2026-10-11f +2 effect_scale_cap (boom.buster_draw -> t_pb_draw, boom.expl_draw -> t_tb_draw) (1333); 2026-10-11e +1 optionlist8 row width (OptionList_calc.row_width -> thunk_ol8_rowwidth) (1331); 2026-10-11d +1 popup_edge_anchor_scale (BasePop_exec_3.edge_anchor -> thunk_popup_edge_anchor) (1330); 2026-10-11 +2 splash_scale (Win_init_class.splash_blit / GraphicsMgr_set_mode.splash_blit -> t_splash_blit) (1329); 2026-10-11 +13 rw_scale_kinds v17 (the six other HQ consoles: 6 title-inset + 7 ListBox R/B-inset CALL helpers t_rwk_con_title_add/_mov / t_rwk_con_lbr) (1327); 2026-10-10c +2 prodpicker_relayout ProdPicker_scroll_to.blit_up/blit_down (both Buffer_copy_4 self-blits -> thunk_pp_scrollblit) (1312); 2026-10-10 +2 caviar_dirty_rect (Caviar_draw.table_composite -> t_cav_table, Caviar_reset.target2_fill -> t_cav_fill2; Caviar_draw.composite retargeted to t_cav_blit; pcave2 0x30000->0x31000) (1310); 2026-10-06 +1 hud_backdrop_stripes (MainWin_build.console_backdrop); 2026-10-05 +2 report_energy_list_bar (ReportWin_draw_energy list rebuild bracket: t_rwsb_begin / t_rwsb_end) (1309); 2026-10-04l +3 base_cell_stripes (production box x2 -> t_sb_tile2, build-queue row tile -> t_tile_force) (1307); 2026-10-04j +7 console_tile_stripes ListBox_draw_item call sites -> t_lb_item_stripes (faction picker name-list rows on the stripe law) (1304); 2026-10-04h +7 console_tile_stripes (6 Buffer_tile redirects -> t_tile_force: MainWin_tile_panels x4, BaseWin_draw_garrison, DesignWin_draw_slot_strip; MessageWin_draw_bg box -> t_msg_bgforce: native 1:1 console dither onto the stripe law) (1297); 2026-10-04b +3 popup_type4_field_width Dialog_type4_attach.win_width/field_right/col_stride (thunk_t4_winw / thunk_t4_colw: the text-entry dialog width scaled at the attach reads) (1290); 2026-10-04 +1 save_header_init game_data.header_init (thunk_save_header_init: the save header local zeroed, version 12; VANILLA bug) (1287); 2026-09-26q2/r +3 g_scrollbar_w.CD1/CD2 (calc_dims fixed-box reserve subtract -> thunk_lbres_edx) + rail_slide_out.capw (thunk_railout_capw: capture column bp(47)) (1286); 2026-09-26k +2 slide_show.outer_left/right_settled (t_slide_rail_s1/s2: the settled draws ceil-descale v for the railscale shim; the A cells now hold the device row for the animation frames) (1283); 2026-09-26j +1 slide_hide.outer_rail_row (t_slide_rail_a2, the close-animation copy) -1 report_intel.observer_faction WITHDRAWN (ReportIf_activate already sets the observer; the blank DIPLOMATIC STATUS is game state) (1281); 2026-09-26i +1 rw_scale_kinds slide_show.outer_rail_row (t_slide_rail_a: the slide windows' outer rail strips start at ScreenH - fl(530g/16), vanilla's screen row 238 scaled) (1281); 2026-09-26g +5 rw_scale_kinds v16 (intel PROFILE: leader portrait -> t_rwk_intel_portrait via thunk_art_draw, console title inset cave, 2 ListBox R/B inset caves, POLITICS block clamp t_rwk_intel_blocky) (1279); 2026-09-26d +2 diplowin_scale v3 (chat font stamp, iface vtbl save-under snapshot) (1274); 2026-09-26c +42 diplowin_scale (DiploWin lever + painters + fonts + art + rails) (1272); 2026-09-26 +4 slide_rails_council_dl CouncilWin_show_hide/DatalinkIface_on_mode railarm_show/hide (1230); 2026-09-24c +2 basewin_slide_rails BaseWin_on_status.railarm_show/hide (1226); 2026-09-24b +3 map_move_line_scale (path line Buffer_line_2 -> t_ml_line, label shadow -> t_ml_textcolor, label find_font -> t_ffn) (1224); 2026-09-21f +1 basewin_facsb BaseWin_draw_facilities.sb_attach (thunk_bw_facsb_attach: the BASE FACILITIES overflow scrollbar's attach rect made device space, law basewin_facsb_rect, + the vanilla thumb-drag-loss fix for that bar) (1220); 2026-09-20 +1 popup_art_reblit BasePop_on_redraw.art_draw_direct (thunk_art_draw: the direct popup-art Sprite_draw_2 @0x604C72 gets the edge-pinned parity re-blit) (1219); 2026-09-19c ntw_scale v2: -5 caption-nudge sites (measured: no nudge), icon buttons skip the stripes pass, wheel chain head (1218); 2026-09-19b +35 ntw_scale (TECH BREAKTHROUGH window NetTechWin: GraphicWin_init_2 layout lever, Win_center caption, 2 TextScroll_attach, modal bracket, 14 frame + 6 caption/title text + icon redirects, 9 find_font redirects; thunk_btn_shrink gate call -> t_ntw_gate) (1223); 2026-09-19 +1 veh_pick_single_list veh_pick.force_list_type (thunk_vehpick_list1: one-unit pick forced to a type-8 list, VANILLA bug) (1188); 2026-09-18g +17 combat_console_scale (BattleWin combat console: BattleWin_init wrapper, 3 Font_init + 2 find_font redirects, 2 portrait Sprite_draw_2 redirects + 4 sprite-dim read thunks, slot/inset x2/stats-y thunks, BattleWin iface vtbl save-under arm) (1184); 2026-09-18b +1 popup_chrome_insets Popup_on_draw_background.untitled_stash (thunk_untitled_stash: virtual title stash for untitled popups) (1166); 2026-09-18 +1 commlink_menu_scale popups_normal.menu_font (thunk_popnorm_menufont: popups_normal keeps the scaled g_menu_font after a tutorial popup) (1165); 2026-09-17j +19 tutwin_tooltip_scale *.basel2s_* (thunk_tutwin_basel2s: base-screen tutorial pointer targets scaled by basewin_pt before the BaseWin origin add) (1146); 2026-09-17i +2 tutwin_tooltip_scale TutWin_tour6.drone_pointer_x_1/_5 (thunk_tutwin_popx: drone-tour pointer x through local_to_screen(MainWin); vanilla pushed the raw strip-local left+5) (1144); 2026-09-17h +1 se_scale SocialWin_build.set_modal (SE label fit v3: t_se_labelfit at the build's Win_set_modal call) (1143); 2026-09-14b +10 hof_scale (Hall of Fame bake: load_hoficons wrapper, 3 backdrop copy_4 redirects, faction-picture blit-core redirect, 5 painter font detours; the FlatButton face-blit head retargeted to t_hof_face; pcave2 0x2D000->0x30000) (1133); 2026-09-14 +16 mon_scale (Planetary Monument bake: load_monicons wrapper, 2 backdrop + 2 picture copy_4 redirects, 5 keyed-sprite + 4 picture blit-core redirects, plaque-font detour, Buffer_draw_2 face-restripe detour; pcave2 0x2B000->0x2D000) (1117); 2026-09-13g +1 rw_scale_kinds v13 (ReportWin_on_lclick.blink_tile -> t_rwk_blinktile: stash the clicked tile for the ring placed on the box) (1116); 2026-09-12c +4 rw_scale_kinds v8 (BASE LOCATOR ring stamps -> t_rwk_blink: SCALE bracket g/16 + s(7)/s(5) recentre) (1112); 2026-09-10b +14 rw_scale_kinds v3 (console-canvas frames with the C6/41 backdrop fill -> t_rwk_boxforce: native draw + fe_pair_remap FORCE over the drawn rect) (1098); 2026-09-10 +10 rw_scale_kinds v2 (6 specialist-face G brackets, 4 BASE STATUS row caves: cell = 2K + face, face y = top + K) (1088); 2026-09-08 +66 rw_scale_kinds (HQ report screens F3..F8 + intel PROFILE: 11 caves, 4 G-bracket redirects, 32 box_sprite->devfill, 10 scroll_small/normal, 7 scroll_show/hide column save/restore, 2 rail arms) (1022); 2026-09-07 +2 listbox_hover_clamp (VANILLA ListBox_set_hover slot clamp: grid row >= rows / slot >= rows*cols -> un-hover; t_lb_hover_grid/slot) + btn_gate_pre v6 kind/faction-tab MISS prefix (post-Datalinks icon zoom) (1020); 2026-09-04e +1 ReportWin_vtbl.tech_hover (t_rw_techhover: F2 hover bracket) (1019); 2026-09-04 +31 rw_scale_shared/rw_scale_tech (HQ report screens bake: init lever detour, row 0x4B/gap caves, sbinit/scroll/lbclose, row frame + backdrop, 3 tech-page bracket redirects, 3 hdr caves, 2 hdr frames->bmxt, title/crest caves, labs bracket, 8 bar redirects, 2 kind-tab mov-imm rewrites; 3 existing heads retargeted) (1016); 2026-08-30c +1 ts.flowdraw (VANILLA article flow-scroll fix: paragraph-head flow start + wrapped-line bar range, cave t_ts_cache/t_ts_flowdraw + g_ts_flowcache, pcave2 0x2A000->0x2B000) (985); 2026-08-30b +2 dl portrait/wheel addendum (faction leader portrait bilinear g:16 via the A5 resampler dest-gate poke + profile-text x advance; the 2 wheel_scroll sites retargeted to the DL cascade heads t_dl_wheel_down/up) (984); 2026-08-30 +69 dl_scale (Datalinks bake: build/exec/cu/wininit detours + 6 regfix, 45 frame redirects, 2 tiles, 5 arrowzoom, mono, btnrect, 2 techwrap, hover raw, render_topic raw, iface vtbl repoint) (982); 2026-08-29 +78 Design Workshop bake (dw_scale 55: exec/picker detours, 10 Caviar_draw redirects, composite shim, 17 option-E imms + 4 stubs, 2 plotter caves, frames/fills, backdrop; wheel_scroll 2; popup_listbox_reserve 20: 18 g_scrollbar_w helpers + bar stash/clear; picker_grid_leave_present 1) (913); 2026-08-28 +19 tech_scale (SELECT RESEARCH GOAL bake: exec caller + 3 box + 4 Font_init + 8 find_font redirects + 3 cuts) (835); 2026-08-25b +2 se_scale v2 rail arms (816); 2026-08-25 +22 se_scale (SOCIAL ENGINEERING bake: 19 E8 redirects + vtable slot + 2 MOV-imm rewrites) (792); 2026-08-22 +16 council_scale (Planetary Council bake: 15 CouncilWin E8 redirects + the blit-core flag restripe) (776); 2026-08-21b +1 Dialog_type16_calc.measure_native council propose width (775); 2026-08-20 +2 diplo_slide_rails railarm_show/hide (773); 2026-08-18 +52 diplo_talk_scale (760); 2026-08-15c +1 commlink_draw_faction_row.rowrect COMMLINK row text/spot rect (708); 2026-08-14b +1 rail_slide_out.hstep popup-family rail (707); 2026-08-13b +1 Console_editor_diplomacy.pdsclear vanilla pds-leak fix (706); 2026-08-13 +14 scenedit_scale (705); 08-08 +2 ScrollBar_on_resize arrowfit arms (691); 08-07 +5 rail_scrollbar_scale (689); 08-05 +4 prodpicker pass-5 hity/hitx/titlepad/measure (684); 08-04 +3 prodpicker pass-4 boxsprite redirects (680); 08-03b +3 prodpicker pass-3 frame/cellrect/btnframe (677); 08-02i +13 prodpicker_relayout (674); 08-02d +6 n17..n22 pitch/seed (661); 08-02c +3 cell_clip_base/cell_clip_unit/cell_highlight_base (655); 08-01g +1 StatusWin.cellh (652); 08-01d +1 Dialog_attach.childx (651); 08-01 +1 selbox_bottom (650); 07-31 +5 popup_optionlist8_spritezoom (649); 07-27 +4 basewin_box2_polish (644); 26h +sb dragfree (640); 26g +sb_reattach (639); 26f +arrowseeds (638)


def test_eligible_group_set(fresh_copy):
    r = _run([], fresh_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    eligible = set(re.findall(r"\[ok\]\s+group\s+(\S+):", r.stdout))
    assert eligible == EXPECTED_ELIGIBLE_GROUPS, (
        f"eligible groups changed.\n  missing: "
        f"{sorted(EXPECTED_ELIGIBLE_GROUPS - eligible)}\n  unexpected: "
        f"{sorted(eligible - EXPECTED_ELIGIBLE_GROUPS)}")


def test_apply_produces_known_good_md5(fresh_copy, target_meta):
    expected = target_meta.get("patched_md5")
    assert expected, "patches.yaml target.patched_md5 is missing"
    r = _run(["--apply"], fresh_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    got = hashlib.md5(fresh_copy.read_bytes()).hexdigest()
    assert got == expected, (
        f"apply produced {got}, expected {expected}. If the patch set changed "
        f"intentionally, update target.patched_md5 in patches.yaml.")


# --- prax.dll (patches_prax.yaml): same byte-exact lock, separate target ---

_PRAX_PATCHES = Path(ap.DEFAULT_PATCHES).with_name("patches_prax.yaml")


@pytest.fixture
def prax_fresh_copy(tmp_path) -> Path:
    import config
    src = config.game_dir(required=False) / "prax.dll.bak"
    if not src.exists():
        pytest.skip(f"prax.dll.bak not found at {src} (created on first "
                    "patches_prax.yaml apply)")
    dst = tmp_path / "prax_test.dll"
    shutil.copy2(src, dst)
    return dst


def test_prax_apply_produces_known_good_md5(prax_fresh_copy):
    import yaml
    if not _PRAX_PATCHES.exists():
        pytest.skip(f"{_PRAX_PATCHES} not found")
    meta = ap._yaml_load(_PRAX_PATCHES.read_text(encoding="utf-8"))["target"]
    expected = meta.get("patched_md5")
    assert expected, "patches_prax.yaml target.patched_md5 is missing"
    r = _run(["--patches", str(_PRAX_PATCHES), "--apply"], prax_fresh_copy)
    assert r.returncode == 0, r.stdout + r.stderr
    got = hashlib.md5(prax_fresh_copy.read_bytes()).hexdigest()
    assert got == expected, (
        f"prax apply produced {got}, expected {expected}. If the patch changed "
        f"intentionally, update target.patched_md5 in patches_prax.yaml.")
