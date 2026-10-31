"""rw_scale_kinds -- the HQ report screens' remaining pages (kinds 0,3..8: energy, bases, projects,
satellites, units, score, intel) as a bake of hook_report_kinds_proto.js v13 (USER-VERIFIED 4K + 1600
2026-09-08). Companion module of assemble_rw.py (imported as RK): the thunk bodies, cells and sites of
the new group. The 400 immediate rows ride in the shared g_rw_immtab (rw_kinds_rows.KINDS_IMMS).

Levers (proto -> bake shape):
  rows          KINDS_IMMS (HD) + 4 VEH rows (veh_draw/base_draw size pushes; law veh_size_scaled)
  caves         t_rwk_proj_rowdiv / t_rwk_proj_rowy / t_rwk_units_rowdiv (magic-multiply row divisions
                -> idiv by s(cell)), t_rwk_bases_namex / t_rwk_intel_textx (imm8 overflows -> imm32 adds)
  frames        32 Buffer_box_sprite E8 sites in the seven canvas painters -> thunk_box_thick_devfill
                (K strokes + device-density interior; the thunk self-gates on g<=16)
  console bars  10 scroll_small/scroll_normal E8 sites (energy/bases/intel consoles) -> t_rw_scrollsmall /
                t_rw_scrollnormal (v2: per-panel bar slots for the wheel)
  buttons       thunk_btn_gate_pre v7 range admissions + 20 label-font pushes (g_rw_font)
  seams         t_rwk_gov_split1/2, t_rwk_sat_split1/2 (toggle pairs: seam s(2), equal halves)
  satellites    t_rwk_sat_cx/cy (planet recentred for the scaled flic), t_rwk_gdraw (v6: planet flic frame
                through thunk_sprite_bilinear x g/16 from a stack Sprite built like Buffer_draw's; was the
                SCALE_NUM_G/DEN_G NN bracket), t_rwk_gtable (attack explosion frames), rows for the explosion patch
  faces         t_rwk_gblit (bases CITIZENS faces blit under g/16)
  rails         slide_show/slide_hide(ReportWin) call sites -> thunk_popup_railshow/railhide (arms the
                filedlg rail gate = the popup/diplo/SE/DW pattern); thunk_rail_gate v3 admits ReportWin
                (assemble_rail_scrollbar.py); t_rwk_scrollshow/scrollhide save the window's pristine
                right-border column once and restore it after every scroll_hide (the gated slide-out
                bakes the captured bar image into the window canvas: the score/projects residue)
  wheel         t_rw_wheel_down/up v2: kinds 0/3/4 scroll the console list under the cursor
                (GetCursorPos/ScreenToClient via the IAT, MainWin-relative, panel L/R -> bar slot)
  fonts         report fonts whose s(size) exceeds the 40-px find_font table are Font_init'd on cave
                scratch objects (f18/2, f22, f26, f32) -- CHEATED! and the big headers
Laws: scaling_laws.scale_px (HD), stroke_width (K via devfill), veh_size_scaled; v18: the F5 / F7 list rows at
cum(k) = s(k*pitch) (rw_list_row_offset / rw_projects_row_y / rw_units_visible_rows), not k*(s(cell)+s(2)).
"""
from __future__ import annotations
import struct

import assemble_se as SE
import assemble_resampler as ARS
import re
import scaling_laws as SL
from rw_kinds_rows import KINDS_IMMS

HD = SE.HD
FL = SE.FL
PCAVE2 = 0x00A0C000
G = 0x00668740
RW, RI = 0x00876478, 0x00885F38
MAINWIN = 0x007AE820
G_NUM, G_DEN = 0x00696D18, 0x00696D1C          # SCALE_NUM_G / SCALE_DEN_G
BLIT_CORE = 0x005E4B9A                          # Sprite_blit_scaled_core (thiscall RET 0x10)
BUFFER_DRAW = 0x005D8370                        # Buffer_draw(dest,key,x,y) (thiscall RET 0x10)
SPRITE_DRAW_TABLE = 0x005E8FF5                  # Sprite_draw_table(dest,key,x,y,table) (thiscall RET 0x14)
BOX_SPRITE = 0x005E2DD3
SCALE_NN = PCAVE2 + 0x2150                       # thunk_sprite_scale_nn (Sprite_draw_2 contract: ecx=Sprite; dest,key,x,y,num,den; RET 0x18): output-driven centre-sampled NN, full edge coverage
# v4 (2026-09-11): the rw code region is full (4B spare at 0x27E00) -> these two CALL helpers live in pinned free pcave2 slots
PINNED = {"t_rwk_boxforce": 0x4730, "t_rwk_face_blit": 0x6B40, "thunk_sprite_bilinear": 0x21000,
          "t_rwk_parity_nn": 0x213C0, "t_rwk_blink": 0x6E30, "thunk_face_hybrid": 0x21A00,
          # v16 (2026-09-26): intel PROFILE page -- the old t_dl_wheel_down slot 0x230B0..0x23210 (352 B, cave_map --at FREE)
          "t_rwk_intel_portrait": 0x230B0, "t_rwk_intel_title": 0x23130, "t_rwk_intel_lbr_l": 0x23160, "t_rwk_intel_lbr_r": 0x23180,
          "t_rwk_intel_blocky": 0x231A0, "t_rw_sbarrows": 0xC980,
          "t_slide_rail_a": 0x1180, "t_slide_rail_a2": 0x3F80,   # cave_map --fit 128: 0x117F..0x1200 / 0x3F7B..0x4000 free
          "t_slide_rail_s1": 0x2020, "t_slide_rail_s2": 0x5B50,
          # v17 (2026-10-11): the six other consoles' title inset + ListBox R/B inset CALL helpers (cave_map --at 0x30300 FREE .. 0x30E00)
          "t_rwk_con_title_add": 0x30300, "t_rwk_con_title_mov": 0x30320, "t_rwk_con_lbr": 0x30340,
          # v18 (2026-10-11): F5/F7 list-row helpers (cave_map --at: 0x1A924..0x1AA00 and 0x23B3F..0x23C20 FREE; the old
          # in-region proj_rowdiv / proj_rowy / units_rowdiv slots 0x24970..0x24A10 are left free, FROZEN pins t_rwk_bases_namex)
          "t_rwk_proj_rowy": 0x1A930, "t_rwk_units_rowdiv": 0x1A9A0, "t_rwk_units_rowstep": 0x23B40, "t_rwk_proj_rowdiv": 0x23BA0,
          # v18 (2026-10-11): F3 energy-list wheel helpers of t_rw_wheel_down (cave_map --at 0x12865 FREE .. 0x12940 g_council_active);
          # t_rw_wheel_have = t_rw_wheel_down's scroll tail, pinned in down's own former slot (down 376B -> 284B; up FROZEN @0x24110);
          # t_wheel_stc = the shared client->backbuffer cursor stub of every asm wheel head (g_wheel_stc cell @0x1293C)
          "t_rw_wheel_energy": 0x12870, "t_rw_wheel_hfail": 0x12908, "t_rw_wheel_have": 0x240B4, "t_wheel_stc": 0x1292C,
          "t_lb_textpad": 0x28030,
          # 2026-10-17 console tab pairs v2: free tails of the rw arc's own pin reservations (cave_map --at 0x2496A / 0x28068 /
          # 0x231BA / 0x23BD6 / 0x1A96E / 0x1A9D6 FREE) -- the in-region gap 0x24970..0x24A10 the v18 pins left behind, the
          # tail after t_lb_textpad, after t_rwk_intel_blocky, after t_rwk_proj_rowdiv, after t_rwk_proj_rowy / units_rowdiv
          "t_rw_tabpair": 0x24970, "t_rw_labs_w": 0x249F0, "t_rw_insetv": 0x28070, "t_rw_labs_h": 0x280C0, "t_rw_labs_rh": 0x280E0,
          "t_rwk_ops_w": 0x231E0, "t_rwk_govlist": 0x23BE0, "t_rwk_ops_lw": 0x1A970, "t_rwk_ops_lx": 0x1A9E0,
          # 2026-10-17 console chain: the rw walker wrapper, in the slack after t_dl_wheel_down (cave_map --at 0x13F4F FREE
          # up to g_se_vpdone 0x14000)
          "t_rw_immsum": 0x13F50,
          # 2026-10-17 strip frame under its clip (cave_map --at 0x1CF50 FREE up to g_dw_cache 0x1D000; 0x1AFB0 FREE up to
          # g_hof_field 0x1AFF0; no gap in pcave2 holds both)
          "t_rwk_stripframe": 0x1CF50, "t_rwk_stripxfer": 0x1AFB0,
          # 2026-10-18 fix 9 strip anchor (cave_map --at 0x34E5 FREE up to thunk_popup_railshow 0x3550)
          "t_rwk_stripanchor": 0x34F0}   # cave_map --fit 112: 0x2020..0x2090 / 0x5B48..0x5BC0 free     # v13: blink outgrew its last-in-region slot (cave_map --fit: 0x6E28..0x7000 free)     # cave_map --at: 0x472E..0x4800, 0x6B36..0x6C00, 0x21000..0x22000 free (bilinear 936B, then v6's parity_nn v2)
PINNED_END = {"t_rwk_boxforce": 0x4800, "t_rwk_face_blit": 0x6C00, "thunk_sprite_bilinear": 0x213C0,
              "t_rwk_parity_nn": 0x21A00, "t_rwk_blink": 0x7000, "thunk_face_hybrid": 0x22000,
              "t_rwk_intel_portrait": 0x23130, "t_rwk_intel_title": 0x23160, "t_rwk_intel_lbr_l": 0x23180, "t_rwk_intel_lbr_r": 0x231A0,
              "t_rwk_intel_blocky": 0x231E0, "t_rw_sbarrows": 0xCA00,
              "t_slide_rail_a": 0x1200, "t_slide_rail_a2": 0x4000, "t_slide_rail_s1": 0x2090, "t_slide_rail_s2": 0x5BC0,
              "t_rwk_con_title_add": 0x30320, "t_rwk_con_title_mov": 0x30340, "t_rwk_con_lbr": 0x30360,
              "t_rwk_proj_rowy": 0x1A970, "t_rwk_units_rowdiv": 0x1A9E0, "t_rwk_units_rowstep": 0x23BA0, "t_rwk_proj_rowdiv": 0x23BE0,
              "t_rw_wheel_energy": 0x12908, "t_rw_wheel_hfail": 0x1292C, "t_rw_wheel_have": 0x24110, "t_wheel_stc": 0x1293C, "t_lb_textpad": 0x28070,
              "t_rw_tabpair": 0x249F0, "t_rw_labs_w": 0x24A10, "t_rw_insetv": 0x280C0, "t_rw_labs_h": 0x280E0, "t_rw_labs_rh": 0x28100,
              "t_rwk_ops_w": 0x23210, "t_rwk_govlist": 0x23C20, "t_rwk_ops_lw": 0x1A9A0, "t_rwk_ops_lx": 0x1AA00,
              "t_rw_immsum": 0x14000, "t_rwk_stripframe": 0x1D000, "t_rwk_stripxfer": 0x1AFF0, "t_rwk_stripanchor": 0x3550}   # v15: cave_map --at 0x218A8..0x22000 free -> the hybrid at 0x21A00
SPRITE_BILINEAR = PCAVE2 + PINNED["thunk_sprite_bilinear"]
FACE_HYBRID = PCAVE2 + PINNED["thunk_face_hybrid"]
# v16: intel PROFILE leader portrait through the smooth-portrait path (the Datalinks t_dl_portrait / diplo t_dw_artL precedent)
PAVG_GATE_IMM = PCAVE2 + 0xA05      # imm32 of thunk_portrait_avg's dest gate `cmp eax, 0x940824` (assemble_dl.PAVG_GATE_IMM)
ART_DRAW = PCAVE2 + 0x29EB0         # thunk_art_draw (assemble_artreblit.py): Sprite_draw_2 drop-in (ecx=Sprite; dest,key,x,y,num,den; RET 0x18) + parity re-blit; uimod.dll SmoothPortraits hooks its re-blit
RW_CANVAS = RW + 0x444              # ReportWin canvas Buffer 0x8768BC = the portrait blit's dest   # v15: citizen faces = bilinear photo + regenerated scanline background (asm_face_hybrid)
G_BIG_F4 = PCAVE2 + 0xB170                       # "Big F4 indicators" pref flag (prefwin tail block; uimod.dll writes it)   # v5: callable palette-aware bilinear (Sprite_draw_2 contract), see asm_sprite_bilinear
SCROLL_SMALL, SCROLL_NORMAL = 0x005883D0, 0x00588340
SCROLL_SHOW, SCROLL_HIDE = 0x0045DEA0, 0x0045E540
SLIDE_SHOW, SLIDE_HIDE = 0x0045D440, 0x0045D970
DEVFILL = PCAVE2 + 0x42A0                        # thunk_box_thick_devfill (self-gated g<=16)
FE_PAIR_REMAP = PCAVE2 + 0x10000                 # thunk_fe_pair_remap v7 (CALL helper; preserves ebx/esi/edi/ebp)
G_FE_DST, G_FE_X, G_FE_Y, G_FE_W, G_FE_H = (PCAVE2 + o for o in (0x2FA0, 0x2FA4, 0x2FA8, 0x2FAC, 0x2FB0))
G_RM_FORCE = PCAVE2 + 0x44B0                     # one-shot: remap keys its pairs from the DEST rect content
IAT_GETCURSORPOS, IAT_SCREENTOCLIENT = 0x00669284, 0x006692D4
G_HWND = 0x009B7B28

# ---- rows --------------------------------------------------------------------------
# icon size pushes: `push -6/-8` imm8 -> veh_size_scaled (walker kind VEH: min(48, ((a+16)*g>>4)-16))
VEH_ROWS = [(0x4A0E01, -6, "units veh_draw size"), (0x49DC3B, -6, "bases base_draw size"),
            (0x49DF44, -8, "bases veh_draw(prod) size"), (0x49EA70, -8, "bases veh_draw(garrison) size")]

# proto rows whose instruction the bake DISPLACES into a seam cave: the cave computes the scaled value itself
# (proto v13 rewrote these rects at BaseButton_init by return address, so the rows never took effect there).
# They MUST NOT reach the walker table -- the bytes now hold the detour's E9 rel32 and the walker's store
# would rewrite it (bake v1a: the 0x14 row at 0x4A4851 turned the gov_split2 jump into 0xA27B20 -> F2 crash).
DETOUR_COVERED_ROWS = {
    0x4A4851: "t_rwk_gov_split2: ecx += s(0x14) in the cave",
    0x4A4CA2: "t_rwk_sat_split1: eax = L + wl (the lea's -1 disp is replaced)",
    0x4A4D7E: "t_rwk_sat_split2: eax = L + wl + s2 (the lea's +1 disp is replaced)",
    # v2 (2026-09-10) BASE STATUS rows -- chrome follows content (scaling_laws.bases_row_cell / bases_face_y_imm):
    0x49D591: "t_rwk_bases_cell: eax = cell = 2K + floor(38g/16) (the one 0x28 quantity: row height AND icon-cell width)",
    0x49D622: "t_rwk_bases_cellx: x + cell",
    0x49D62B: "t_rwk_bases_celly: y + cell",
    0x49D62E: "t_rwk_bases_celly: the displaced `add eax, 2` (s(2)) is computed in the cave",
    0x49E3FA: "t_rwk_bases_facey: y = rowBottom - pitch/2 - (cell - pitch/2 - K) = rowTop + K",
    # 2026-10-17 console tab pairs v2 (law rw_tab_pair / rw_console_inset_w):
    0x4A47A3: "t_rwk_gov_split1 v2: GOVERNOR h -- the cave writes the whole rect and resumes past this store (dead code)",
    0x4A90E5: "t_rwk_ops_w: F4 tab box w = W - 2*s(6) (inside the detour)",
    0x4A90AA: "t_rwk_ops_lx: BEST BASES list x = L + P (inside the detour)",
    0x4A90C1: "t_rwk_ops_lw: BEST BASES list w = W - 2P (inside the detour)",
    0x4A4F07: "t_rwk_govlist: governor list x = L + P (inside the detour)",
    0x4A4F0A: "t_rwk_govlist: governor list y = T + s(0x23) (inside the detour, computed in the cave)",
    0x4A4F1B: "t_rwk_govlist: governor list w = W - 2P (inside the detour)",
    0x4A4C46: "t_rwk_sat_w: F6 tabs w = clipW - 2*s(3) (inside the detour)",
    0x4A492F: "t_rwk_modes_w: F4 mode tabs w = clipW - 2*s(3) (inside the detour)",
}

# ---- label-font pushes (push 0x6e84b4 -> g_rw_font; imm32 at push+1) ---------------
FONT_PUSH_KINDS = [va + 1 for va in (0x4A47F0, 0x4A48A8, 0x4A49DD, 0x4A4AB1, 0x4A4B91, 0x4A4CE1, 0x4A4DB6, 0x4A4EA9,
                                     0x4A4FB0, 0x4A509E, 0x4A518C, 0x4A527A, 0x4A5368, 0x4A5422, 0x4A54DC,
                                     0x4A55AD, 0x4A5667, 0x4A572C, 0x4A58EF, 0x4AB3B9)]

# ---- cells (appended to assemble_rw.CELL_DEFS) --------------------------------------
CELL_DEFS = [
    ("g_rw_slot", 4), ("g_rw_sbs", 8), ("g_rw_sbparents", 8),          # per-panel console list bars (0 = left, 1 = right)
    ("g_rw_railcol", 4), ("g_rw_colsaved", 4), ("g_rw_colx0", 4), ("g_rw_colw", 4), ("g_rw_colh", 4),
    ("g_rw_tech_rect", 16),                                           # t_rw_techpage's restripe RECT (never g_rw_rect: see asm_rw_techpage)
    ("g_rw_fontscratch", 4 * 0x28 - 32),                              # unused since fonts v2; shrunk by 16 so every later cell keeps its offset, then by 16 more for g_rw_strip_rect
    ("g_rw_strip_rect", 16),                                          # 2026-10-18 fix 9: t_rwk_stripanchor's strip RECT (law rw_strip_anchor), rebuilt every paint
    ("g_blink_tile", 8),                                              # v13: the clicked base's (tx, ty) for t_rwk_blink
]
BIGFONT_IDX = (11, 12, 13, 14)     # FONTS indices whose s(size) can exceed the 40-px table (26, 18/2, 22, 32)

# ---- button-gate v7 range admissions (bevel-face FlatButtons the report builds) -------
GATE_RANGES = [
    (RI + 0xD138, 2, "GOVERNOR / BEST BASES"), (RI + 0xE7D0, 7, "governor list"), (RI + 0x1BF9C, 3, "automate units"),
    (RI + 0x13778, 7, "sat faction targets"), (RI + 0x18720, 5, "sat satellite targets"),
    (RW + 0x7C9C, 3, "bases mode tabs"), (RW + 0x9F14, 3, "sat tabs + ATTACK!"),
    # 2026-10-11: the F2 tech FlatButtons. Their first paint runs inside the t_rw_techpage bracket (netwin=1 admits
    # them), but hover/un-hover/press redraw from FlatButton_on_mouse_move through vtbl+0xF8 OUTSIDE any bracket
    # -> native 1-px AE/EE (E0/E1 selected) tile pair after the first touch. Same buttons in the Datalinks TECH
    # ADVANCES page run under DatalinkWin's exec bracket (netwin=1) -> admitted there already.
    (RW + 0xA38, 7, "F2 tech buttons"),
]

# ---- frame retargets: every Buffer_box_sprite call of the seven canvas painters -------
BOX_SITES = {
    "energy": [0x49BDAB, 0x49BDBB, 0x49BDCB, 0x49BDDB, 0x49BDEB, 0x49BDFB],
    "bases": [0x49D653, 0x49D663, 0x49D676, 0x49DAD7, 0x49DAE7, 0x49DAF7, 0x49DB18, 0x49DB28, 0x49DB8B],
    "projects": [0x49EBBE, 0x49EBCE, 0x49EF3B, 0x49EF56],
    "sat": [0x49F3B0, 0x49F3C0, 0x49FB79],
    "units": [0x4A0954, 0x4A0964, 0x4A0D7D, 0x4A0D98],
    "score": [0x4A11B3, 0x4A11C3, 0x4A11D3],
    "intel": [0x4A228A, 0x4A229A, 0x4A22AA],
}
# v3 (2026-09-10): console-canvas frames whose FILL is the C6/41 backdrop tile (d5a0 inner frames, da50 outer
# frames). Every MainWin-canvas Buffer_box_sprite enters thunk_hud_boxframe -> thunk_box_thick_hollow_flat, whose
# NN enlarge bands the 1px tile (1,2,1,2,2 row runs at g=25: user 2026-09-10 BEST BASES panel), and the enlarge-path
# fe_pair_remap is navy-only BY DESIGN (C4/41; the C6/41 backdrop pair must stay untouched there). The d528 panels
# are C4/41 and come out P-striped; these fourteen did not. Call-site VAs = census return address - 5.
BOXFORCE_SITES = {
    "ReportIf_console_chrome": [(0x4A3D3A, "outer L panel"), (0x4A3D4D, "outer R panel"), (0x4A3D60, "outer centre-top"),
                                     (0x4A3D85, "outer centre-bottom"), (0x4A3E18, "inner L panel"), (0x4A3E2E, "inner R panel"),
                                     (0x4A3E3E, "inner centre-top"), (0x4A3E4E, "inner centre-bottom")],
    "ReportIf_console_ops": [(0x4A90FC, "GOVERNOR/BEST BASES tab strip"), (0x4A9124, "left panel"),
                               (0x4A9E2F, "BASE LOCATOR outer"), (0x4A9E85, "BASE LOCATOR title band")],
    "ReportIf_console_projects": [(0x4AA67C, "BASE LOCATOR outer"), (0x4AA6D2, "BASE LOCATOR title band")],
}
STRIP_FRAME_SITE = 0x4A3D85     # the kind-icon strip's da50, drawn at L - s(7) under the strip clip -> t_rwk_stripframe
STRIP_ANCHOR_SITE, STRIP_ANCHOR_LEN = 0x4A3D65, 8   # `add esi,0x40 / mov ecx,MAIN`: esi = the strip RECT every strip draw reads
SCROLL_SMALL_SITES = [(0x4A8664, "energy listA"), (0x4A8D19, "energy listB"), (0x4A915B, "bases list"), (0x4AC30E, "intel listA"), (0x4AC77C, "intel listB")]
SCROLL_NORMAL_SITES = [(0x4A892B, "energy listA"), (0x4A8FFC, "energy listB"), (0x4A9AD8, "bases list"), (0x4AC48E, "intel listA"), (0x4AC95C, "intel listB")]
SCROLL_SHOW_SITES = [(0x4A3CB5, "ReportIf_show_page"), (0x4A5D1B, "ReportIf_activate")]
SCROLL_HIDE_SITES = [(0x49D739, "ReportWin_draw_bases"), (0x49ED11, "ReportWin_draw_projects"), (0x4A0B8D, "ReportWin_draw_units"),
                     (0x4A3BC3, "ReportIf_show_page"), (0x4A5D94, "ReportIf_activate")]


CELL: dict[str, int] = {}     # bound to assemble_rw.CELL by assemble_rw at import (NOT re-imported: the script
                              # runs as __main__, and `import assemble_rw` there would load a second, empty copy)


def _cell(name: str) -> int:
    return CELL[name]


# ==== caves (the proto's 5 caves, jmp-resume form) =======================================
RW_WIN_H = 0x5990    # ReportWin d690 frame rect bottom = the window height (device after t_rw_init_leave). NOT +0xA20:
                     # ReportWin_tech_reset (0x496BB0; the store at 0x496C60; run at the start of every page paint) stores textB - clipT there


def _asm_rowcount(inset: int, div: int, resume: int) -> str:
    """v18b: ecx = the engine's h (device); edx = eax = the visible-row count (law scaling_laws._rw_visible_rows).
    g <= 16: h / div (vanilla).  g > 16: (ceil(win_h*16/g) - 0x35 - inset) / div -- vanilla's count in native space
    from the exactly recovered textB; win_h = RW+0x5990 = fl(H*g/16), written only by init_report_screen and
    t_rw_init_leave.  v18c (2026-10-17): v18b read RW+0xA20, which every page paint overwrites with textB - clipT
    (ReportWin_tech_reset), so F7 showed 9 rows and F5 7 instead of vanilla's 10 / 8 at every g > 16.
    ecx/ebx preserved."""
    return f"""
    mov     eax, ecx
    cmp     dword ptr [{G:#x}], 16
    jle     rcount
    mov     eax, dword ptr [esi+{RW_WIN_H:#x}]
    shl     eax, 4
    add     eax, dword ptr [{G:#x}]
    dec     eax
    cdq
    idiv    dword ptr [{G:#x}]
    sub     eax, {SL.RW_TEXTB_INSET + inset}
rcount:
    push    ebx
    mov     ebx, {div}
    cdq
    idiv    ebx
    pop     ebx
    mov     edx, eax
    jmp     {resume:#x}
"""


def asm_rwk_proj_rowdiv() -> str:   # @0x49EB6F 12B: mov eax,MAGIC / imul ecx / sar edx,4 / mov eax,edx  (rows = h / 54)
    return _asm_rowcount(SL.RW_PROJECTS_COUNT_INSET, SL.RW_PROJECTS_COUNT_DIV, 0x49EB7B)   # law rw_projects_visible_rows


# v18 (2026-10-11): F5 / F7 list rows at the remainder-distributed positions (law scaling_laws.rw_list_row_offset):
# visible row k sits at cum(k) = s(k * pitch) below row 0, never k * (a per-row rounded pitch) -- the v1 caves stepped
# s(0x36)+s(2) = 87 (projects; 87.5 real at g=25) and s(0x2B) = 67 (units; 67.19), 1 px lost every 2..5 rows (measured
# 1600x1200 2026-10-11).  The drawn row (cell / rect height) keeps its own s(); the gap absorbs the rounding (LAW 5).
# Row clicks are Spot rects registered from the same row rect (0x5FA960), so the hit-test follows by construction.
# The three helpers live in pinned free slots (the rw region is full); FROZEN keeps the region's later offsets.
def asm_rwk_proj_rowy() -> str:     # @0x49EE8F 22B: row y = top + 56*k + 2  (x56 lea); eax = visible row k on entry
    return f"""
    mov     dword ptr [esi+0xa14], ecx
    push    ecx
    imul    edi, eax, {SL.RW_PROJECTS_ROW_PITCH}
    {HD("edi")}
    mov     ecx, {SL.RW_PROJECTS_ROW_INSET}
    {HD("ecx")}
    mov     eax, dword ptr [ebp-0x34]
    add     eax, ecx
    add     eax, edi
    pop     ecx
    jmp     0x49EEA5
"""


def asm_rwk_units_rowdiv() -> str:  # @0x4A0974 12B: rows = h / 43  (law rw_units_visible_rows)
    return _asm_rowcount(SL.RW_UNITS_COUNT_INSET, SL.RW_UNITS_ROW_PITCH, 0x4A0980)


def asm_rwk_units_rowstep() -> str:  # @0x4A0D3D 10B: add edx,eax / add ecx,eax / mov [ebp-0x2C],edx / mov [ebp-0x24],ecx
    # edx/ecx = the row rect's top/bottom, eax = the walker's s(0x2B) (row 0x4A0D39 stays live: the site starts after
    # it).  k = row counter [ebp-4] - scroll [esi+0xC0FC] >= 1 (k = 0 skips the advance at 0x4A0D30).  Both edges
    # += cum(k) - cum(k-1) (law rw_list_row_advance); eax/ecx/edx are dead at 0x4A0D47 (reloaded / cdq).
    return f"""
    push    edx
    mov     eax, dword ptr [ebp-4]
    sub     eax, dword ptr [esi+0xc0fc]
    imul    eax, eax, {SL.RW_UNITS_ROW_PITCH}
    lea     edx, [eax-{SL.RW_UNITS_ROW_PITCH}]
    {HD("eax")}
    {HD("edx")}
    sub     eax, edx
    pop     edx
    add     edx, eax
    add     ecx, eax
    mov     dword ptr [ebp-0x2c], edx
    mov     dword ptr [ebp-0x24], ecx
    jmp     0x4A0D47
"""


def asm_rwk_bases_namex() -> str:   # @0x49E129 5B: add edx,0x3c / test eax,eax  (imm8 overflow at g=40)
    return f"""
    push    ecx
    mov     ecx, 0x3c
    {HD("ecx")}
    add     edx, ecx
    pop     ecx
    test    eax, eax
    jmp     0x49E12E
"""


def asm_rwk_intel_textx() -> str:   # @0x4A3407 5B: add eax,0x7d / push ebx / push eax
    return f"""
    push    ecx
    mov     ecx, 0x7d
    {HD("ecx")}
    add     eax, ecx
    pop     ecx
    push    ebx
    push    eax
    jmp     0x4A340C
"""


# ==== toggle seams (the TECH|BASES split law: seam s(2), equal halves) ==================
# v2 (2026-10-17): the GOVERNOR|BEST BASES pair is the F2 TECHNOLOGY|BASES pair's twin (same d5a0 tab box
# {L+6, T+6, R-6, T+6+0x1A} on the console panel region, same 9 / 0x12 / 0x14 button cursor) -> the same law,
# scaling_laws.rw_tab_pair, through assemble_rw's t_rw_tabpair helper.  v1 (W - s2) >> 1 halves off the s(9) / s(0x12)
# cursor left the parity remainder and the s(0x12) - 2*s(9) / s(9)+s(0x14) vs s(6)+s(0x1A) mismatches in the right and
# bottom channels (4K L5 R6 T5 B6, 1600x1200 L3 R2 T3 B3; vanilla 2/2/2/2).
def asm_split_left(resume_native: int, resume_law: int) -> str:
    """@site 6B: sar eax,1 / add esp,8 / dec eax (left toggle w = W/2 - 1).  g > 16: the left button's rect from the
    law (t_rw_tabpair, eax = 0) and resume past vanilla's four rect stores; g <= 16: the displaced bytes."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    add     esp, 8
    xor     eax, eax
    call    t_rw_tabpair
    jmp     {resume_law:#x}
native:
    sar     eax, 1
    add     esp, 8
    dec     eax
    jmp     {resume_native:#x}
"""


def asm_rwk_gov_split1() -> str:    # @0x4A478D 6B: sar eax,1 / add esp,8 / dec eax  (GOVERNOR w = W/2 - 1)
    return asm_split_left(0x4A4793, 0x4A47B0)


def asm_rwk_gov_split2() -> str:    # @0x4A484F 8B: add ecx,0x14 / push ebx / lea edx,[eax+edx+1]  (BEST BASES)
    # `push ebx` is BaseButton_init's first argument: kept on both paths.  g > 16: the right button's rect from the law,
    # resume past the stores (0x4A486B reloads every register it uses from the scratch rect).
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    push    ebx
    mov     eax, 1
    call    t_rw_tabpair
    jmp     0x4A486B
native:
    add     ecx, 0x14
    push    ebx
    lea     edx, [eax+edx+1]
    jmp     0x4A4857
"""


# ---- span - 2*s(v) (law scaling_laws.rw_console_inset_w) at the other cursor builders of the same family ----------
# ops_w v2 (2026-10-17 console chain): the box w = W - 2C (law rw_console_box_w; t_rw_insetv code -1 = C, was s(6))
def asm_rwk_ops_w() -> str:          # @0x4A90DD 9B: lea edi,[esi+0x1E1C8] / sub eax,0xC  (F4 tab box w; edi reloaded)
    return f"""
    mov     edi, eax
    push    -1
    call    t_rw_insetv
    add     eax, eax
    sub     edi, eax
    mov     eax, edi
    lea     edi, [esi+0x1E1C8]
    jmp     0x4A90E6
"""


def asm_rwk_ops_lx() -> str:         # @0x4A90A8 6B: lea edx,[ecx+9] / mov [esi+0xC],edx  (BEST BASES list x; eax/edx dead)
    return f"""
    push    0
    call    t_rw_insetv
    lea     edx, [ecx+eax]
    mov     dword ptr [esi+0xC], edx
    jmp     0x4A90AE
"""


def asm_rwk_ops_lw() -> str:         # @0x4A90BA 8B: mov eax,[edi+8] / sub eax,ebx / sub eax,0x12  (BEST BASES list w)
    return f"""
    push    0
    call    t_rw_insetv
    add     eax, eax
    push    eax
    mov     eax, dword ptr [edi+8]
    sub     eax, ebx
    sub     eax, dword ptr [esp]
    add     esp, 4
    jmp     0x4A90C2
"""


def asm_rwk_govlist() -> str:        # @0x4A4F05 26B: governor list cursor x = L+9, y = T+0x23, w = W-0x12 (+ the stores)
    return f"""
    push    0
    call    t_rw_insetv
    add     ecx, eax
    mov     dword ptr [esi+0xC], ecx
    push    eax
    push    0x23
    call    t_rw_insetv
    add     edx, eax
    mov     dword ptr [esi+0x10], edx
    pop     eax
    add     eax, eax
    neg     eax
    add     eax, dword ptr [esi+0x28]
    mov     ecx, dword ptr [esi+0x20]
    sub     eax, ecx
    mov     dword ptr [esi+0x14], eax
    jmp     0x4A4F1F
"""


def asm_rwk_modes_w() -> str:        # @0x4A4927 9B: sub ecx,[clipL] / sub ecx,6  (F4 PRODUCTION|CITIZENS|GARRISON w = clipW - 6)
    return f"""
    sub     ecx, dword ptr [0x87BDEC]
    push    3
    call    t_rw_insetv
    add     eax, eax
    sub     ecx, eax
    jmp     0x4A4930
"""


def asm_rwk_sat_w() -> str:          # @0x4A4C42 8B: sub edx,edi / sub edx,6 / mov [esi+0x14],edx  (F6 tabs w = clipW - 6)
    return f"""
    sub     edx, edi
    push    3
    call    t_rw_insetv
    add     eax, eax
    sub     edx, eax
    mov     dword ptr [esi+0x14], edx
    jmp     0x4A4C4A
"""


def asm_rwk_sat_split1() -> str:    # @0x4A4C9A 9B: push ReportWin / lea eax,[eax+edi-1]  (SUMMARY R = L + W/2 - 1)
    return f"""
    push    {RW:#x}
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    push    ecx
    mov     ecx, dword ptr [esi+0x14]
    push    edx
    mov     edx, 2
    {HD("edx")}
    sub     ecx, edx
    pop     edx
    sar     ecx, 1
    lea     eax, [edi+ecx]                      ; R = L + wl (vanilla eax = W/2, edi = L)
    pop     ecx
    jmp     0x4A4CA3
native:
    lea     eax, [eax+edi-1]
    jmp     0x4A4CA3
"""


def asm_rwk_sat_split2() -> str:    # @0x4A4D76 9B: push ReportWin / lea eax,[eax+edi+1]  (ATTACK VIEW L = L + W/2 + 1)
    return f"""
    push    {RW:#x}
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    push    ecx
    push    edx
    mov     edx, 2
    {HD("edx")}
    mov     ecx, dword ptr [esi+0x14]
    sub     ecx, edx
    sar     ecx, 1
    add     ecx, edx
    lea     eax, [edi+ecx]                      ; L2 = L + wl + s2 (vanilla eax = W/2, edi = L)
    pop     edx
    pop     ecx
    jmp     0x4A4D7F
native:
    lea     eax, [eax+edi+1]
    jmp     0x4A4D7F
"""


# ==== satellites: planet recentre + G brackets =============================================
def asm_rwk_sat_cx() -> str:        # @0x49FB00 6B: mov eax,[esi+0xf3d0]   (planet x = centre - w/2 -> s(w)/2)
    return f"""
    mov     eax, dword ptr [esi+0xf3d0]
    cmp     dword ptr [{G:#x}], 0x10
    jle     r
    {HD("eax")}
r:
    jmp     0x49FB06
"""


def asm_rwk_sat_cy() -> str:        # @0x49FB1B 9B: mov ecx,[esi+0xf3d4] / mov eax,ecx / push ecx  (h native for Buffer_init, s(h)/2 for y)
    return f"""
    mov     ecx, dword ptr [esi+0xf3d4]
    push    ecx
    mov     eax, ecx
    cmp     dword ptr [{G:#x}], 0x10
    jle     r
    {HD("eax")}
r:
    jmp     0x49FB24
"""


def _gwrap(callee: int, nargs: int) -> str:
    """CALL-helper wrapper for a thiscall(ecx=self, nargs stack args) draw primitive: g>16 -> run it with
    SCALE_NUM_G/DEN_G = g/16 (prior pair restored after); g<=16 -> tail-jump (byte-identical native)."""
    fwd = "".join(f"    push    dword ptr [esp+{4 + 8 + 4 * nargs - 4:#x}]\n" for _ in range(nargs))
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    push    dword ptr [{G_NUM:#x}]
    push    dword ptr [{G_DEN:#x}]
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{G_NUM:#x}], eax
    mov     dword ptr [{G_DEN:#x}], 16
{fwd}    mov     eax, {callee:#x}
    call    eax
    pop     dword ptr [{G_DEN:#x}]
    pop     dword ptr [{G_NUM:#x}]
    ret     {4 * nargs:#x}
native:
    jmp     {callee:#x}
"""


def asm_rwk_gblit() -> str:         # citizens faces: Sprite_blit_scaled_core(dest,key,x,y) @0x49E806/0x49E8CA
    return _gwrap(BLIT_CORE, 4)


# v6 (2026-09-12): the ORBITAL ATTACK VIEW planet (the 115x115 flic frame Buffer at ReportWin+0xE8A8,
# drawn by ReportWin_sat_frame once per paint, once per 4 s orbit tick and at an attack start) went through
# the engine's Buffer_draw under the g/16 SCALE bracket = NN (2/3-px blocks at 4K, 1/2 at 1600/1920).
# Buffer_draw's memory path only builds the global Sprite g_buffer_draw_sprite (0x9B3A50) from the source
# Buffer -- data +0x54, key, pitch +0x4A8, W +0x80, H = -[+0x84], offsets 0 -- and calls
# Sprite_blit_scaled_core(dest,key,x,y); the DDraw-surface path ([+0x58] != 0 on either side) never scales.
# v6 builds that Sprite on its own stack frame and calls thunk_sprite_bilinear with num/den = g/16 (the faces'
# path); a surface-backed source or dest, or g<=16, takes the engine's Buffer_draw untouched (tail-jump).
def asm_rwk_gdraw() -> str:         # CALL helper: thiscall(ecx=src Buffer)(dest, key, x, y) RET 0x10 @0x49FF38
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    cmp     dword ptr [ecx+0x58], 0
    jne     native
    mov     eax, dword ptr [esp+4]
    cmp     dword ptr [eax+0x58], 0
    jne     native
    push    ebp
    mov     ebp, esp
    sub     esp, 0x28
    xor     eax, eax
    mov     dword ptr [ebp-0x28], eax
    mov     dword ptr [ebp-0x08], eax
    mov     dword ptr [ebp-0x04], eax
    mov     eax, dword ptr [ecx+0x54]
    mov     dword ptr [ebp-0x24], eax
    mov     eax, dword ptr [ebp+0xC]
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [ecx+0x4A8]
    mov     dword ptr [ebp-0x1C], eax
    mov     eax, dword ptr [ecx+0x80]
    mov     dword ptr [ebp-0x18], eax
    mov     dword ptr [ebp-0x10], eax
    mov     eax, dword ptr [ecx+0x84]
    neg     eax
    mov     dword ptr [ebp-0x14], eax
    mov     dword ptr [ebp-0x0C], eax
    push    16
    push    dword ptr [{G:#x}]
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x10]
    push    dword ptr [ebp+0xC]
    push    dword ptr [ebp+8]
    lea     ecx, [ebp-0x28]
    mov     eax, {SPRITE_BILINEAR:#x}
    call    eax
    mov     esp, ebp
    pop     ebp
    ret     0x10
native:
    jmp     {BUFFER_DRAW:#x}
"""


def asm_rwk_gtable() -> str:        # attack explosion frames: Sprite_draw_table(dest,key,x,y,table) @0x4A020C
    return _gwrap(SPRITE_DRAW_TABLE, 5)


# ==== list-bar residue: save/restore the window's right-border column ======================
def asm_rwk_scrollshow() -> str:    # CALL helper at the 2 scroll_show(win, sb) sites: save the column once (before the bar draws)
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    cmp     dword ptr [{_cell('g_rw_colsaved'):#x}], 0
    jne     go
    mov     eax, dword ptr [{_cell('g_rw_railcol'):#x}]
    test    eax, eax
    je      go
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, eax                            ; ebp = column store
    mov     eax, dword ptr [{RW + 0x444 + 0x80:#x}]      ; canvas w
    mov     ecx, 47
    {HD("ecx")}
    add     ecx, 4
    sub     eax, ecx                            ; x0 = w - s(47) - 4
    mov     dword ptr [{_cell('g_rw_colx0'):#x}], eax
    mov     dword ptr [{_cell('g_rw_colw'):#x}], ecx
    mov     edx, dword ptr [{RW + 0x444 + 0x84:#x}]
    neg     edx                                 ; h
    mov     dword ptr [{_cell('g_rw_colh'):#x}], edx
    mov     esi, dword ptr [{RW + 0x444 + 0x54:#x}]
    add     esi, eax                            ; esi = data + x0
    mov     edi, ebp                            ; edi = store
    mov     ebx, dword ptr [{RW + 0x444 + 0x4a8:#x}]      ; pitch
rows:
    test    edx, edx
    jle     done
    push    esi
    push    edi
    mov     ecx, dword ptr [{_cell('g_rw_colw'):#x}]
    rep movsb
    pop     edi
    pop     esi
    add     edi, dword ptr [{_cell('g_rw_colw'):#x}]
    add     esi, ebx
    dec     edx
    jmp     rows
done:
    mov     dword ptr [{_cell('g_rw_colsaved'):#x}], 1
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
go:
    jmp     {SCROLL_SHOW:#x}
"""


def asm_rwk_scrollhide() -> str:    # CALL helper at the 5 scroll_hide(win, sb) sites: run it, then restore the saved column
    return f"""
    push    dword ptr [esp+8]
    push    dword ptr [esp+8]
    mov     eax, {SCROLL_HIDE:#x}
    call    eax
    add     esp, 8
    cmp     dword ptr [{_cell('g_rw_colsaved'):#x}], 0
    je      done
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     edi, dword ptr [{RW + 0x444 + 0x54:#x}]
    add     edi, dword ptr [{_cell('g_rw_colx0'):#x}]     ; edi = data + x0
    mov     esi, dword ptr [{_cell('g_rw_railcol'):#x}]   ; esi = store
    mov     ebx, dword ptr [{RW + 0x444 + 0x4a8:#x}]      ; pitch
    mov     edx, dword ptr [{_cell('g_rw_colh'):#x}]
rows:
    test    edx, edx
    jle     fin
    push    esi
    push    edi
    mov     ecx, dword ptr [{_cell('g_rw_colw'):#x}]
    rep movsb
    pop     edi
    pop     esi
    add     esi, dword ptr [{_cell('g_rw_colw'):#x}]
    add     edi, ebx
    dec     edx
    jmp     rows
fin:
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
done:
    ret
"""



# ==== v2 (2026-09-10): BASE STATUS rows -- chrome follows content =================================
# Vanilla entry box 40 = 1px stroke + 38-row face + 1px stroke (pitch 42 = cell + 2); the painter keeps ONE
# cell quantity (0x28 @0x49D591 -> [+0x59A0]/[+0x59A4]: row height AND leader-icon cell width) and puts the
# face at y = rowBottom - pitch/2 - 18.  Walker rows scaled the cell by s(40) and the G bracket the face by
# floor(38g/16) -> 0..2 rows short of the strokes (user 2026-09-09).  Laws scaling_laws.bases_row_cell /
# bases_row_pitch / bases_face_y_imm: cell = 2K + floor(38g/16), pitch = cell + s(2), y imm = cell - pitch/2 - K.
# Identity at g=16 by arithmetic (2+38 = 40; 40-21-1 = 18) -> no gate.  User-verified proto v2 at 1600/1920/4K.
SPRITE_DRAW_2 = 0x005E4B4A


def _cell_asm() -> str:
    """eax = cell(g) = 2K + floor(38g/16), edx = K (clobbers eax, edx only)."""
    return f"""
    mov     eax, dword ptr [{G:#x}]
    mov     edx, eax
    add     edx, edx
    add     edx, 15
    sar     edx, 5
    imul    eax, eax, 38
    sar     eax, 4
    lea     eax, [eax+edx*2]
"""


def _s2_asm(reg: str) -> str:
    """reg = s(2) = (4g+15)>>5 (clobbers reg only)."""
    return f"""
    mov     {reg}, dword ptr [{G:#x}]
    shl     {reg}, 2
    add     {reg}, 15
    sar     {reg}, 5
"""


def asm_rwk_bases_cell() -> str:      # @0x49D590 5B: mov eax, 0x28
    return f"""
    push    edx
{_cell_asm()}    pop     edx
    jmp     0x49D595
"""


def asm_rwk_bases_cellx() -> str:     # @0x49D620 6B: add eax, 0x28 / mov [ebp-0x2C], eax
    return f"""
    push    ecx
    push    edx
    mov     ecx, eax
{_cell_asm()}    add     eax, ecx
    pop     edx
    pop     ecx
    mov     dword ptr [ebp-0x2C], eax
    jmp     0x49D626
"""


def asm_rwk_bases_celly() -> str:     # @0x49D629 6B: lea edx, [ecx+0x28] / add eax, 2
    return f"""
    push    ecx
    push    eax
{_cell_asm()}    add     eax, ecx
    mov     edx, eax
    pop     eax
    push    edx
{_s2_asm("edx")}    add     eax, edx
    pop     edx
    pop     ecx
    jmp     0x49D62F
"""


def asm_rwk_bases_facey() -> str:     # @0x49E3F8 9B: sub ecx, 0x12 / mov [esi+0xA14], edx
    return f"""
    push    eax
    push    edx
{_cell_asm()}    push    edx
{_s2_asm("edx")}    add     edx, eax
    sar     edx, 1
    sub     eax, edx
    pop     edx
    sub     eax, edx
    sub     ecx, eax
    pop     edx
    pop     eax
    mov     dword ptr [esi+0xA14], edx
    jmp     0x49E401
"""


# ==== v2: the 32 kinds K-frame sites -- half-open rect -> the inclusive thick renderer ===========
# Vanilla Buffer_box_sprite draws [L,R) x [T,B) (1024x768 rect census 2026-09-10: icon cell rect 29..69
# draws 193..232); thunk_box_thick_devfill covers its rect inclusively -> every kinds K-frame was one row
# and one column too large (bake v1: entry box s(40)+1).  Same contract as t_rw_rowframe: R-1/B-1 in place
# around the call, restored after (the rect is the caller's live local).  g<=16 -> devfill's own native path.
def asm_rwk_boxhalf() -> str:         # CALL helper: thiscall(ecx=dest)(rect, params) RET 8
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    mov     eax, dword ptr [esp+4]
    dec     dword ptr [eax+8]
    dec     dword ptr [eax+0xC]
    push    dword ptr [esp+8]
    push    dword ptr [esp+8]
    mov     eax, {DEVFILL:#x}
    call    eax
    mov     eax, dword ptr [esp+4]
    inc     dword ptr [eax+8]
    inc     dword ptr [eax+0xC]
    ret     8
native:
    jmp     {DEVFILL:#x}
"""


# ==== v3: console-canvas frame + FORCE restripe of its drawn rect ===============================
# CALL helper with Buffer_box_sprite's contract (thiscall ecx=dest; rect, params; RET 8).  The native call runs
# unchanged (MainWin canvas -> thunk_hud_boxframe -> hollow_flat: K strokes, NN-banded C6/41 fill), then the drawn
# rect [L,R)x[T,B) is staged into g_fe_dst/x/y/w/h and thunk_fe_pair_remap runs on its FORCE path (g_rm_force):
# the pre-scan keys the pair from the dest content (C6 majority in the first rows -- the stroke rows count 0,
# the fill rows > w/2), every 0x41/0xC6 pixel becomes the device-row stripe colour (P=(g+4)>>3, hN=(P+1)>>1,
# same law/phase as devfill's STEP3), every other index (strokes, corner art) passes through.  g<=16 -> native.
def asm_rwk_boxforce() -> str:        # CALL helper: thiscall(ecx=dest)(rect, params) RET 8
    # v3b (2026-09-11): R-1/B-1 in place around the native call (restored after), the same half-open contract as
    # t_rwk_boxhalf -- the hud_boxframe/hollow_flat renderer covers its rect INCLUSIVELY, so two abutting console
    # frames (the ops console sets the left panel's T = the tab strip's B) shared one stroke row: the GOVERNOR/BEST
    # BASES toggle's bottom band measured 2K-1 = 1/3/3 px at 1920/1600/4K against vanilla's 2 (user sweep 2026-09-11).
    # The force-remap rect is staged from the adjusted (= drawn) rect.
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    push    ebx
    push    esi
    mov     esi, ecx
    mov     ebx, dword ptr [esp+0xC]
    dec     dword ptr [ebx+8]
    dec     dword ptr [ebx+0xC]
    push    dword ptr [esp+0x10]
    push    dword ptr [esp+0x10]
    mov     ecx, esi
    mov     eax, {BOX_SPRITE:#x}
    call    eax
    mov     dword ptr [{G_FE_DST:#x}], esi
    mov     eax, dword ptr [ebx]
    mov     dword ptr [{G_FE_X:#x}], eax
    mov     edx, dword ptr [ebx+8]
    sub     edx, eax
    mov     dword ptr [{G_FE_W:#x}], edx
    mov     eax, dword ptr [ebx+4]
    mov     dword ptr [{G_FE_Y:#x}], eax
    mov     edx, dword ptr [ebx+0xC]
    sub     edx, eax
    mov     dword ptr [{G_FE_H:#x}], edx
    inc     dword ptr [ebx+8]
    inc     dword ptr [ebx+0xC]
    mov     dword ptr [{G_RM_FORCE:#x}], 1
    mov     eax, {FE_PAIR_REMAP:#x}
    call    eax
    pop     esi
    pop     ebx
    ret     8
native:
    mov     eax, {BOX_SPRITE:#x}
    jmp     eax
"""


# ==== 2026-10-17: the kind-icon strip's outer da50 under its clip (law scaling_laws.rw_strip_frame) ================
# ReportIf_console_chrome sets the clip to the strip region and draws the da50 at L - s(7) (0x4A3D85), so the frame leaves
# its clip on the left; thunk_frame_enlarge then refuses the band map (it writes the plane directly, unclipped) and the
# frame went through the GDI NN stretch at the exact-fill size of the R-1/B-1 rect: 3-row strokes at 4K, bottom / right
# stroke one px inside the panels' at every g (channel to the d5a0 7/6 at 4K, 4/3 at 1600x1200 and 1920x1080).
# CALL helper with Buffer_box_sprite's contract (thiscall ecx=dest; rect, params; RET 8): save the hidden band
# [L', clipL) x [T, B) of the dest plane on the stack, widen the clip's left edge to L' for the draw, run t_rwk_boxforce
# (the panels' own path: band map, K strokes, force restripe), restore the clip edge and the band.  Anything it cannot
# save (no band, off-plane, larger than RW_STRIP_SAVE_CAP) -> t_rwk_boxforce under the clip as before.  g<=16 -> native.
def asm_rwk_stripframe() -> str:      # CALL helper: thiscall(ecx=dest)(rect, params) RET 8
    cap = SL.RW_STRIP_SAVE_CAP
    # frame: [ebp-0x10] w = clipL - L'  [ebp-0x14] B  [ebp-0x18] T  [ebp-0x1C] clip L  [ebp-0x20] L'
    #        save area [ebp-0x20-cap, ebp-0x20); ebx = t_rwk_stripxfer's direction (0 plane -> area, 1 area -> plane)
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      scaled
    push    {BOX_SPRITE:#x}
    ret
scaled:
    push    ebp
    mov     ebp, esp
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
    mov     ebx, dword ptr [ebp+8]
    mov     eax, dword ptr [esi+0x20]
    sub     eax, dword ptr [ebx]
    jle     plain
    mov     edx, dword ptr [ebx+4]
    mov     ecx, dword ptr [ebx+0xC]
    push    eax
    push    ecx
    push    edx
    push    dword ptr [esi+0x20]
    push    dword ptr [ebx]
    sub     ecx, edx
    jle     plain
    or      edx, dword ptr [ebx]
    jl      plain
    mov     edi, dword ptr [esi+0x84]
    add     edi, dword ptr [ebx+0xC]
    jg      plain
    cmp     dword ptr [esi+0x54], 0
    je      plain
    imul    ecx, eax
    cmp     ecx, {cap:#x}
    jg      plain
    sub     esp, {cap:#x}
    xor     ebx, ebx
    call    t_rwk_stripxfer
    mov     eax, dword ptr [ebp-0x20]
    mov     dword ptr [esi+0x20], eax
    push    dword ptr [ebp+0xC]
    push    dword ptr [ebp+8]
    mov     ecx, esi
    call    t_rwk_boxforce
    mov     eax, dword ptr [ebp-0x1C]
    mov     dword ptr [esi+0x20], eax
    inc     ebx
    call    t_rwk_stripxfer
    lea     esp, [ebp-0xC]
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret     8
plain:
    mov     ecx, esi
    lea     esp, [ebp-0xC]
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    jmp     t_rwk_boxforce
"""


def asm_rwk_stripxfer() -> str:       # t_rwk_stripframe's band copy, run in ITS frame (ebp, esi = dest, ebx = direction)
    cap = SL.RW_STRIP_SAVE_CAP
    return f"""
    lea     edi, [ebp-{0x20 + cap:#x}]
    mov     edx, dword ptr [ebp-0x18]
xrow:
    mov     eax, edx
    imul    eax, dword ptr [esi+0x4A8]
    add     eax, dword ptr [esi+0x54]
    add     eax, dword ptr [ebp-0x20]
    push    esi
    mov     esi, eax
    test    ebx, ebx
    je      xgo
    xchg    esi, edi
xgo:
    mov     ecx, dword ptr [ebp-0x10]
    rep movsb
    test    ebx, ebx
    je      xnext
    xchg    esi, edi
xnext:
    pop     esi
    inc     edx
    cmp     edx, dword ptr [ebp-0x14]
    jl      xrow
    ret
"""


# ==== 2026-10-18 fix 9: the strip's left edge = the left panel's right stroke (law scaling_laws.rw_strip_anchor) =====
# Vanilla's seeds put the strip region on the left panel's last column (244 = 245 - 1), so the strip draw covers the
# panel's right stroke in the strip rows and the two d5a0 sit the strip's own channel apart.  Scaled, fl(244g/16) and
# fl(245g/16) - K disagree by +-1 at g = 23 / 25 / 28 / 39: a surviving stroke column at L-1 (25 / 28) and the
# d5a0 -> d5a0 gap off the T / B / R channel by 1 (1600x1200: 5 vs 4).  Detour over `add esi,0x40 / mov ecx,MAIN`
# (0x4A3D65, the strip section's head; esi is the RECT every strip draw and the painter's own L/R/T/B steps read):
# g > 16 -> g_rw_strip_rect = (panel R - K, T, R, B) from ReportIf+0x28 / +0x40, esi = g_rw_strip_rect, so the clip,
# the da50 at L - s(7) (t_rwk_stripframe), the d5a0 and the d528 all anchor on the panel's stroke and ReportIf+0x40
# itself is never written (the kind tabs keep the region; the cell is rebuilt every paint, no state crosses one).
# K = half_down(g, 16) = (2g + 15) >> 5 (stroke_width).  edi (the centre RECT) preserved; eax and the flags are dead
# at the resume (push esi / call Buffer_set_clip).  g <= 16: the displaced pair only (vanilla).
def asm_rwk_stripanchor() -> str:     # detour @0x4A3D65 8B -> resume 0x4A3D6D
    scr = _cell("g_rw_strip_rect")
    return f"""
    add     esi, 0x40
    mov     ecx, {MAINWIN + 0x444:#x}
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jle     done
    lea     eax, [eax*2+0xF]
    sar     eax, 5
    neg     eax
    add     eax, dword ptr [esi-0x18]
    push    edi
    mov     edi, {scr:#x}
    mov     dword ptr [edi], eax
    mov     eax, dword ptr [esi+4]
    mov     dword ptr [edi+4], eax
    mov     eax, dword ptr [esi+8]
    mov     dword ptr [edi+8], eax
    mov     eax, dword ptr [esi+0xC]
    mov     dword ptr [edi+0xC], eax
    mov     esi, edi
    pop     edi
done:
    jmp     {STRIP_ANCHOR_SITE + STRIP_ANCHOR_LEN:#x}
"""


# ==== v8 (2026-09-12c): BASE LOCATOR ring stamp x g/16 (law scaling_laws.blink_stamp) ==========================
# ReportIf_blink_step 0x4A4060 stamps ReportIf+0x20254's four 12x12 dot sprites onto the minimap canvas
# (WorldWin+0x444) through Sprite_blit_scaled_core at the four sites below, at the SCALE globals' 1:1 ratio ->
# a 12-px ring on a g/16-scaled minimap (user 2026-09-12).  CALL helper with the core's contract (thiscall
# ecx=Sprite; dest,key,x,y; RET 0x10): g>16 -> bracket SCALE_NUM_G/DEN_G = g/16 (prior pair restored) and
# undo/redo the native -7/-5 centring at s(7)/s(5); g<=16 -> the core untouched (tail-jump).
BLINK_SITES = [(0x4A40AD, "a"), (0x4A40EA, "d"), (0x4A4127, "c"), (0x4A4164, "b")]   # jump-table arms A/D/C/B
# v9 (2026-09-12d): [g_big_f4] != 0 ("Big F4 indicators" checkbox, uimod.dll) -> the ring stamps at 2g/16 (v10: 3g
# until 2026-09-12f) through thunk_sprite_scale_nn (Sprite_draw_2 contract, no engine 4.0 cap; 2g/16 > 4 above
# g=32) with the centring on the ring's own centre (law v2: x' = px - hd(3g,32) - 6r, y' = py + hd(g,32) - 6r); the SCALE
# globals are untouched on that path.  Every g (deliberate).  v3: x term hd(g,32) (centred on the box).
# v13 (2026-09-13g): the ring is placed on the BOX (law scaling_laws.blink_place): the blink point is ignored at g>16;
# g_blink_tile (stashed by t_rwk_blinktile at the WorldWin_tile_to_pixel call in ReportWin_on_lclick) -> MapWin_tile_to_pixel
# -> box centre (px+6, py+3) mapped like the composition (StretchBlt ratio win/buf, or the 1:1 offsets) - 6r, half_down.
# v13a (user shots 165333/165402/165426: ring 4/1.5/2 dev LOW at 4K/1600/1920, x exact): the base pass passes
# tile_to_pixel_y - [console+0x1DDC0] (row height 2) to MapWin_draw_base_tile (decompile 0x469B40), so py -= that field.
# v14 (2026-09-13i): per-FRAME centring -- each dot frame's drawn content (thunk_sprite_scale_nn: P = floor(off*num/16),
# W = floor(w*num/16) from the sprite's +0x20/+0x24 offsets and +0x10/+0x14 blit size) is centred on the box:
# X' = hd(cx2*win_w - (2P+W)*buf_w, 2*buf_w) (stretched) / hd(2*off + cx2 - (2P+W), 2) (1:1); BOTH modes now draw
# through scale_nn at mg/16 (the lawful mode used the engine core's G bracket, whose frame rounding is not ours to
# know); g<=16 lawful stays the engine's own stamp.  Removes the -0.75 @1600 / -0.5 @1920 frame bias.


WW, WW_CONSOLE, TILE_TO_PX, TILE_TO_PX_WIN = 0x008E9F60, 0x008EB48C, 0x00462F00, 0x004C44E0   # WorldWindow, its embedded Console, MapWin_tile_to_pixel, WorldWin_tile_to_pixel
WW_WIN_W, WW_WIN_H, WW_BUF_W, WW_BUF_H, WW_OFF_X, WW_OFF_Y = (WW + o for o in (0x4C4, 0x4C8, 0xA14, 0xA18, 0x239C4, 0x239C8))
CONSOLE_ROW_H = WW_CONSOLE + 0x1DDC0        # the base pass (MapWin_gen_bases_only 0x469B40) draws each base at tile_to_pixel_y - this row height


def asm_rwk_blinktile() -> str:     # call_target_redirect @0x4974B2 (ReportWin_on_lclick): stash (tx, ty), then WorldWin_tile_to_pixel
    return f"""
    mov     eax, dword ptr [esp+4]
    mov     dword ptr [{_cell('g_blink_tile'):#x}], eax
    mov     eax, dword ptr [esp+8]
    mov     dword ptr [{_cell('g_blink_tile') + 4:#x}], eax
    jmp     {TILE_TO_PX_WIN:#x}
"""


def asm_rwk_blink() -> str:         # v14 CALL helper: thiscall(ecx=Sprite)(dest, key, x, y) RET 0x10; law scaling_laws.blink_place
    # frame: [ebp-4]=py [ebp-8]=px [ebp-0xC]=Sprite [ebp-0x10]=num(mg) [ebp-0x14]=win_w [ebp-0x18]=win_h ; then ebx/esi/edi
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jg      scaled
    cmp     dword ptr [{G_BIG_F4:#x}], 0
    jne     scaled
    jmp     {BLIT_CORE:#x}
scaled:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x18
    push    ebx
    push    esi
    push    edi
    mov     dword ptr [ebp-0xC], ecx
    lea     eax, [ebp-4]
    push    eax
    lea     eax, [ebp-8]
    push    eax
    push    dword ptr [{_cell('g_blink_tile') + 4:#x}]
    push    dword ptr [{_cell('g_blink_tile'):#x}]
    mov     ecx, {WW_CONSOLE:#x}
    mov     eax, {TILE_TO_PX:#x}
    call    eax
    lea     esp, [ebp-0x24]
    mov     eax, dword ptr [{CONSOLE_ROW_H:#x}]
    sub     dword ptr [ebp-4], eax
    mov     ebx, dword ptr [{G:#x}]
    cmp     dword ptr [{G_BIG_F4:#x}], 0
    je      m1
    add     ebx, ebx
m1:
    mov     dword ptr [ebp-0x10], ebx
    mov     esi, dword ptr [{WW_WIN_W:#x}]
    mov     edi, dword ptr [{WW_WIN_H:#x}]
    neg     edi
    mov     dword ptr [ebp-0x14], esi
    mov     dword ptr [ebp-0x18], edi
    mov     ecx, dword ptr [ebp-0xC]
    mov     eax, dword ptr [ecx+0x20]
    imul    eax, ebx
    sar     eax, 4
    add     eax, eax
    mov     edx, dword ptr [ecx+0x10]
    imul    edx, ebx
    sar     edx, 4
    add     eax, edx
    mov     esi, eax
    mov     eax, dword ptr [ecx+0x24]
    imul    eax, ebx
    sar     eax, 4
    add     eax, eax
    mov     edx, dword ptr [ecx+0x14]
    imul    edx, ebx
    sar     edx, 4
    add     eax, edx
    mov     edi, eax
    mov     eax, dword ptr [{WW_BUF_W:#x}]
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    cmp     dword ptr [ebp-0x14], eax
    jl      stretched
    mov     eax, dword ptr [{WW_BUF_H:#x}]
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    cmp     dword ptr [ebp-0x18], eax
    jl      stretched
    mov     eax, dword ptr [{WW_BUF_W:#x}]
    cmp     dword ptr [ebp-0x14], eax
    jl      stretched
    mov     eax, dword ptr [{WW_BUF_H:#x}]
    cmp     dword ptr [ebp-0x18], eax
    jl      stretched
    mov     eax, dword ptr [{WW_OFF_X:#x}]
    add     eax, eax
    add     eax, dword ptr [ebp-8]
    add     eax, dword ptr [ebp-8]
    add     eax, 12
    sub     eax, esi
    lea     eax, [eax*2+1]
    sar     eax, 2
    mov     dword ptr [ebp+0x10], eax
    mov     eax, dword ptr [{WW_OFF_Y:#x}]
    add     eax, eax
    add     eax, dword ptr [ebp-4]
    add     eax, dword ptr [ebp-4]
    add     eax, 6
    sub     eax, edi
    lea     eax, [eax*2+1]
    sar     eax, 2
    mov     dword ptr [ebp+0x14], eax
    jmp     place
stretched:
    mov     eax, dword ptr [ebp-8]
    add     eax, eax
    add     eax, 12
    imul    eax, dword ptr [ebp-0x14]
    mov     ecx, esi
    imul    ecx, dword ptr [{WW_BUF_W:#x}]
    sub     eax, ecx
    add     eax, eax
    mov     ecx, dword ptr [{WW_BUF_W:#x}]
    add     ecx, ecx
    add     eax, ecx
    dec     eax
    add     ecx, ecx
    cdq
    idiv    ecx
    mov     dword ptr [ebp+0x10], eax
    mov     eax, dword ptr [ebp-4]
    add     eax, eax
    add     eax, 6
    imul    eax, dword ptr [ebp-0x18]
    mov     ecx, edi
    imul    ecx, dword ptr [{WW_BUF_H:#x}]
    sub     eax, ecx
    add     eax, eax
    mov     ecx, dword ptr [{WW_BUF_H:#x}]
    add     ecx, ecx
    add     eax, ecx
    dec     eax
    add     ecx, ecx
    cdq
    idiv    ecx
    mov     dword ptr [ebp+0x14], eax
place:
    mov     ecx, dword ptr [ebp-0xC]
    push    16
    push    dword ptr [ebp-0x10]
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x10]
    push    dword ptr [ebp+0xC]
    push    dword ptr [ebp+8]
    mov     eax, {SCALE_NN:#x}
    call    eax
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x10
"""


# ==== v5: thunk_sprite_bilinear -- the validated palette-aware bilinear (thunk_portrait_avg's core) as a CALLABLE
# primitive with thunk_sprite_scale_nn's contract (ecx=Sprite*; stack dest,key,x,y,num,den; __stdcall RET 0x18).
# The source text IS assemble_resampler.ASM's frame/loops/accum/nearest-search (A5, user-verified 1600/1920/4K,
# 2026-09-01 palette-from-dest + never-emit-the-key fixes) with four surgical differences, each asserted below:
#   1. guards: no dest gate (any canvas), num>den (an averager must never downscale), the NN scaler's validity set;
#      any failure tail-jumps the engine's Sprite_draw_2 (native NN), entry stack intact;
#   2. Sprite fields with the engine's blit semantics (Sprite_blit_scaled_core): ROW PITCH iSpriteWidth2@+0xC
#      (<=0 -> blit width), blit W iSpriteWidth@+0x10, blit H iSpriteHeight@+0x14 -- not the logical canvas +0x18/+0x1c
#      (the portrait's own fields coincide for the leader sprite; a citizen face has pitch != width);
#   3. placement px = x + iLeftOffset*num/den, py = y + iTopOffset*num/den (scale_nn v2: origin args UNSCALED,
#      only the sprite's own draw offsets scale) -- the portrait caller zeroes x/y so it never needed this;
#   4. everything else byte-for-byte the portrait law (top-left-aligned 8.8 bilinear over the 4 taps, key texels
#      excluded from the average, coverage = nearest texel != key, nearest dest-palette index never = key).
# WHY: the CITIZENS faces (t_rwk_face_blit) -- the WAR OUTPOST citizen's 1:1 red/dark-red edge dither NN-banded
# 2,1,1,2 at g=22 and 1,2,1,2,2 at g=25 through the full-coverage NN (user 2026-09-11 second set); the deferred
# "bilinear faces" item.  Pinned at pcave2 0x21000 (cave_map: 0x21000..0x22000 free).
def asm_sprite_bilinear() -> str:
    body = ARS.ASM
    a = body.index("; ===== portrait upscale: build frame =====")
    b = body.index("; ----- not the portrait: run the 2 displaced instrs")
    assert 0 < a < b
    core = body[a:b]

    def sub(pat, new, count=1):
        nonlocal core
        core, n = re.subn(pat, new, core, flags=re.M)
        assert n == count, (pat, n, count)

    # 2. sprite fields: pitch@+0xC (fallback blit W @+0x10), W@+0x10, H@+0x14
    sub(r"mov\s+eax, \[ecx\+0x10\]\s*\n\s*cmp\s+eax, 0\s*\n\s*jg\s+sstr_ok[^\n]*\n\s*mov\s+eax, \[ecx\+0x18\]\n",
        "    mov     eax, [ecx+0x0C]\n    cmp     eax, 0\n    jg      sstr_ok\n    mov     eax, [ecx+0x10]\n")
    sub(r"mov\s+eax, \[ecx\+0x18\]\s*\n(\s*mov\s+\[ebp-0x0C\], eax)", r"mov     eax, [ecx+0x10]\n\1")
    sub(r"mov\s+eax, \[ecx\+0x1c\]\s*\n(\s*mov\s+\[ebp-0x10\], eax)", r"mov     eax, [ecx+0x14]\n\1")
    # 3. placement with the sprite's scaled draw offsets (ecx is still the Sprite* here; num/den already stored)
    sub(r"mov\s+eax, \[ebp\+0x10\]\s*\n\s*mov\s+\[ebp-0x30\], eax[^\n]*\n\s*mov\s+eax, \[ebp\+0x14\]\s*\n\s*mov\s+\[ebp-0x34\], eax[^\n]*\n",
        "    mov     eax, [ecx+0x20]\n    imul    eax, dword ptr [ebp-0x24]\n    cdq\n    idiv    dword ptr [ebp-0x28]\n"
        "    add     eax, [ebp+0x10]\n    mov     [ebp-0x30], eax\n"
        "    mov     eax, [ecx+0x24]\n    imul    eax, dword ptr [ebp-0x24]\n    cdq\n    idiv    dword ptr [ebp-0x28]\n"
        "    add     eax, [ebp+0x14]\n    mov     [ebp-0x34], eax\n")
    assert "0x940824" not in core and "fallthrough" not in core and "0x5E4B52" not in core
    guards = """
    mov     eax, [esp+0x18]
    test    eax, eax
    jle     bl_native
    mov     edx, [esp+0x14]
    cmp     edx, eax
    jle     bl_native
    mov     eax, [ecx+0x10]
    test    eax, eax
    jle     bl_native
    mov     eax, [ecx+0x14]
    test    eax, eax
    jle     bl_native
    mov     eax, [ecx+0x04]
    test    eax, eax
    je      bl_native
    mov     eax, [esp+0x04]
    mov     eax, [eax+0x54]
    test    eax, eax
    je      bl_native
    mov     eax, [esp+0x04]
    mov     eax, [eax+0x4a8]
    test    eax, eax
    jle     bl_native
"""
    tail = """
bl_native:
    push    0x005E4B4A
    ret
"""
    return guards + core + tail


# ==== v15 (2026-09-20): thunk_face_hybrid -- citizen faces: bilinear photo + REGENERATED scanline background ====
# Sprite_draw_2 contract (ecx=Sprite*; stack dest,key,x,y,num,den; RET 0x18); PORT of scaling_laws.face_hybrid_enlarge.
# Every citizen face (newicons / aliencit) is a photo over a baked period-2 scanline background; the palette-aware
# average only softens its banding at g=22/25 (the dither invariant: regenerate, never resample).  Structure:
#   guards   g<=16, then thunk_sprite_bilinear's own guard set verbatim; any failure tail-jumps the engine's
#            Sprite_draw_2 with the entry stack intact (the bilinear's native path);
#   pass 1   CALL thunk_sprite_bilinear with the caller's six args (the whole face; that thunk stays byte-identical);
#   pass 2   the same clipped dest rect (same Sprite/Buffer fields read in the same call, so a caller's temporary
#            +0x84 clamp -- t_rwk_face_blit -- bounds both passes): a dest pixel whose NEAREST texel (bilinear_axis
#            `near`, both axes) is a background texel (fh_mate = face_pair_mate v2: fh_vrun = face_pair_vrun, the
#            texel anywhere inside a >= 4-row a/b alternation of its column; fh_m12 = face_pair_run_mate, a run of
#            >= 3 same-pair direct texels on the row, candidates above then below; then the <= 12-texel gap fill
#            between two same-index same-mate members) is overwritten with the pair's brighter member
#            (luma over the dest table +0xA4, ties -> lower index) on the wide rows (dest-buffer y mod P < hN,
#            P = (g+4)>>3, hN = (P+1)>>1) and the other member on the rest.  Every other pixel keeps pass 1.
# Frame (locals reserved BEFORE the reg pushes): -4 sdata, -8 pitch, -0xC sw, -0x10 sh, -0x14 ddata, -0x18 dstride,
# -0x1C dwid, -0x20 dhgt, -0x24 pal, -0x28 px, -0x2C py, -0x30 dstW, -0x34 dstH, -0x38 dyi, -0x3C dxi, -0x40 yn,
# -0x44 xn, -0x48 wide, -0x4C P, -0x50 hN, -0x54 drow, -0x58 a, -0x5C mate, -0x60 run, -0x64 dir, -0x68 Sprite*,
# -0x6C luma(mate), -0x70 vrun count, -0x74 m12 a, -0x78/-0x7C column top/bottom texel ptr, -0x80 m12 x, -0x84 m12 b,
# -0x88 gap x, -0x8C gap length, -0x90 m12 tried b, -0x94 m12 side, -0x98 gap dir.  v2 (2026-09-20): membership v2 --
# v1's one-sided hof_pair_texel chain left the rows between the top border and the head bilinear (a smudge above
# every drone's head at 1600x1200).  Pinned at pcave2 0x21A00 (cave_map: 0x218A8..0x22000 free; the rw region is full).
from scaling_laws import FACE_PAIR_MAX_GAP, FACE_PAIR_MIN_RUN, FACE_PAIR_MIN_VRUN  # noqa: E402  (the port's constants ARE the law's)


def asm_face_hybrid() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     fh_native
    mov     eax, [esp+0x18]
    test    eax, eax
    jle     fh_native
    mov     edx, [esp+0x14]
    cmp     edx, eax
    jle     fh_native
    mov     eax, [ecx+0x10]
    test    eax, eax
    jle     fh_native
    mov     eax, [ecx+0x14]
    test    eax, eax
    jle     fh_native
    mov     eax, [ecx+0x04]
    test    eax, eax
    je      fh_native
    mov     eax, [esp+0x04]
    mov     eax, [eax+0x54]
    test    eax, eax
    je      fh_native
    mov     eax, [esp+0x04]
    mov     eax, [eax+0x4a8]
    test    eax, eax
    jle     fh_native
    push    ebp
    mov     ebp, esp
    sub     esp, 0xA0
    push    ebx
    push    esi
    push    edi
    mov     [ebp-0x68], ecx
    ; ---- pass 1: the whole face through the palette-aware bilinear ----
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x10]
    push    dword ptr [ebp+0x0C]
    push    dword ptr [ebp+0x08]
    mov     eax, {SPRITE_BILINEAR:#x}
    call    eax
    ; ---- pass 2 setup: the bilinear's own field reads / placement / extents ----
    mov     ecx, [ebp-0x68]
    mov     eax, [ecx+0x04]
    mov     [ebp-0x04], eax
    mov     eax, [ecx+0x0C]
    cmp     eax, 0
    jg      fh_pitch_ok
    mov     eax, [ecx+0x10]
fh_pitch_ok:
    mov     [ebp-0x08], eax
    mov     eax, [ecx+0x10]
    mov     [ebp-0x0C], eax
    mov     eax, [ecx+0x14]
    mov     [ebp-0x10], eax
    mov     eax, [ebp+0x08]
    mov     edx, [eax+0x54]
    mov     [ebp-0x14], edx
    mov     edx, [eax+0x4a8]
    mov     [ebp-0x18], edx
    mov     edx, [eax+0x80]
    mov     [ebp-0x1C], edx
    mov     edx, [eax+0x84]
    neg     edx
    mov     [ebp-0x20], edx
    lea     edx, [eax+0xA4]
    mov     [ebp-0x24], edx
    mov     eax, [ecx+0x20]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    add     eax, [ebp+0x10]
    mov     [ebp-0x28], eax
    mov     eax, [ecx+0x24]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    add     eax, [ebp+0x14]
    mov     [ebp-0x2C], eax
    mov     eax, [ebp-0x0C]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    mov     [ebp-0x30], eax
    mov     eax, [ebp-0x10]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    mov     [ebp-0x34], eax
    mov     eax, dword ptr [{G:#x}]
    mov eax, dword ptr [0x66879c]
    nop
    mov     [ebp-0x4C], eax
    inc     eax
    shr     eax, 1
    mov     [ebp-0x50], eax
    mov     dword ptr [ebp-0x38], 0
fh_row:
    mov     eax, [ebp-0x38]
    cmp     eax, dword ptr [ebp-0x34]
    jge     fh_done
    mov     ecx, [ebp-0x2C]
    add     ecx, eax
    js      fh_rownext
    cmp     ecx, dword ptr [ebp-0x20]
    jge     fh_rownext
    mov     edx, ecx
    imul    edx, dword ptr [ebp-0x18]
    add     edx, [ebp-0x14]
    mov     [ebp-0x54], edx
    mov     eax, ecx
    xor     edx, edx
    div     dword ptr [ebp-0x4C]
    xor     eax, eax
    cmp     edx, dword ptr [ebp-0x50]
    setb    al
    mov     [ebp-0x48], eax
    mov     eax, [ebp-0x38]
    imul    eax, dword ptr [ebp+0x1C]
    cdq
    idiv    dword ptr [ebp+0x18]
    add     edx, edx
    cmp     edx, dword ptr [ebp+0x18]
    jl      fh_yn
    inc     eax
    mov     ecx, [ebp-0x10]
    dec     ecx
    cmp     eax, ecx
    jle     fh_yn
    mov     eax, ecx
fh_yn:
    mov     [ebp-0x40], eax
    mov     dword ptr [ebp-0x3C], 0
fh_col:
    mov     eax, [ebp-0x3C]
    cmp     eax, dword ptr [ebp-0x30]
    jge     fh_rownext
    mov     ecx, [ebp-0x28]
    add     ecx, eax
    js      fh_colnext
    cmp     ecx, dword ptr [ebp-0x1C]
    jge     fh_colnext
    imul    eax, dword ptr [ebp+0x1C]
    cdq
    idiv    dword ptr [ebp+0x18]
    add     edx, edx
    cmp     edx, dword ptr [ebp+0x18]
    jl      fh_xn
    inc     eax
    mov     ecx, [ebp-0x0C]
    dec     ecx
    cmp     eax, ecx
    jle     fh_xn
    mov     eax, ecx
fh_xn:
    mov     [ebp-0x44], eax
    call    fh_mate
    test    eax, eax
    js      fh_colnext
    call    fh_luma
    mov     [ebp-0x6C], eax
    mov     eax, [ebp-0x58]
    call    fh_luma
    mov     edx, [ebp-0x58]
    mov     ecx, [ebp-0x5C]
    cmp     eax, dword ptr [ebp-0x6C]
    jg      fh_top_ok
    jl      fh_top_swap
    cmp     edx, ecx
    jle     fh_top_ok
fh_top_swap:
    xchg    edx, ecx
fh_top_ok:
    cmp     dword ptr [ebp-0x48], 0
    jne     fh_store
    mov     edx, ecx
fh_store:
    mov     eax, [ebp-0x28]
    add     eax, [ebp-0x3C]
    add     eax, [ebp-0x54]
    mov     [eax], dl
fh_colnext:
    inc     dword ptr [ebp-0x3C]
    jmp     fh_col
fh_rownext:
    inc     dword ptr [ebp-0x38]
    jmp     fh_row
fh_done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x18
fh_native:
    push    0x005E4B4A
    ret

; ---- fh_mate: face_pair_mate(xn [ebp-0x44], yn [ebp-0x40]) -> eax = mate | -1; a -> [ebp-0x58], mate -> [ebp-0x5C]
fh_mate:
    mov     eax, [ebp-0x44]
    mov     [ebp-0x80], eax
    call    fh_m12
    mov     [ebp-0x58], edx
    test    eax, eax
    js      fhg_try
    mov     [ebp-0x5C], eax
    ret
fhg_try:                                         ; rule 3: gap fill
    cmp     edx, dword ptr [ebp+0x0C]
    je      fhg_none
    mov     dword ptr [ebp-0x8C], 1
    mov     dword ptr [ebp-0x98], -1
fhg_dir:
    mov     eax, [ebp-0x44]
    mov     [ebp-0x88], eax
fhg_step:
    mov     eax, [ebp-0x88]
    add     eax, [ebp-0x98]
    js      fhg_none
    cmp     eax, dword ptr [ebp-0x0C]
    jge     fhg_none
    mov     [ebp-0x88], eax
    mov     [ebp-0x80], eax
    call    fh_m12
    cmp     edx, dword ptr [ebp-0x58]
    jne     fhg_none
    test    eax, eax
    jns     fhg_flank
    inc     dword ptr [ebp-0x8C]
    cmp     dword ptr [ebp-0x8C], {FACE_PAIR_MAX_GAP}
    jg      fhg_none
    jmp     fhg_step
fhg_flank:
    cmp     dword ptr [ebp-0x98], 1
    je      fhg_right
    mov     [ebp-0x5C], eax
    mov     dword ptr [ebp-0x98], 1
    jmp     fhg_dir
fhg_right:
    cmp     eax, dword ptr [ebp-0x5C]
    jne     fhg_none
    ret
fhg_none:
    or      eax, -1
    ret

; ---- fh_m12: face_pair_run_mate(x = [ebp-0x80], yn) -> eax = mate | -1, edx = the texel's index
fh_m12:
    mov     ebx, [ebp-0x80]
    mov     esi, [ebp-0x40]
    imul    esi, dword ptr [ebp-0x08]
    add     esi, ebx
    add     esi, [ebp-0x04]
    movzx   edx, byte ptr [esi]
    mov     [ebp-0x74], edx
    cmp     edx, dword ptr [ebp+0x0C]
    je      fhm_none
    mov     dword ptr [ebp-0x90], -1
    mov     dword ptr [ebp-0x94], 0
fhm_side:
    mov     ebx, [ebp-0x80]
    mov     esi, [ebp-0x40]
    imul    esi, dword ptr [ebp-0x08]
    add     esi, ebx
    add     esi, [ebp-0x04]
    cmp     dword ptr [ebp-0x94], 0
    jne     fhm_below
    cmp     dword ptr [ebp-0x40], 0
    je      fhm_nextside
    sub     esi, [ebp-0x08]
    jmp     fhm_load
fhm_below:
    mov     eax, [ebp-0x40]
    inc     eax
    cmp     eax, dword ptr [ebp-0x10]
    jge     fhm_nextside
    add     esi, [ebp-0x08]
fhm_load:
    movzx   eax, byte ptr [esi]
    cmp     eax, dword ptr [ebp-0x90]
    je      fhm_nextside
    mov     [ebp-0x84], eax
    call    fh_vrun
    test    eax, eax
    js      fhm_nextside
    mov     eax, [ebp-0x84]
    mov     [ebp-0x90], eax
    mov     dword ptr [ebp-0x60], 1
    mov     dword ptr [ebp-0x64], -1
fhm_dir:
    mov     ebx, [ebp-0x80]
fhm_step:
    add     ebx, [ebp-0x64]
    js      fhm_dirend
    cmp     ebx, dword ptr [ebp-0x0C]
    jge     fhm_dirend
    mov     esi, [ebp-0x40]
    imul    esi, dword ptr [ebp-0x08]
    add     esi, ebx
    add     esi, [ebp-0x04]
    movzx   edx, byte ptr [esi]
    cmp     edx, dword ptr [ebp-0x74]
    jne     fhm_cross
    mov     eax, [ebp-0x84]
    jmp     fhm_v
fhm_cross:
    cmp     edx, dword ptr [ebp-0x84]
    jne     fhm_dirend
    mov     eax, [ebp-0x74]
fhm_v:
    call    fh_vrun
    test    eax, eax
    js      fhm_dirend
    inc     dword ptr [ebp-0x60]
    cmp     dword ptr [ebp-0x60], {FACE_PAIR_MIN_RUN}
    jl      fhm_step
    mov     eax, [ebp-0x84]
    mov     edx, [ebp-0x74]
    ret
fhm_dirend:
    cmp     dword ptr [ebp-0x64], 1
    je      fhm_nextside
    mov     dword ptr [ebp-0x64], 1
    jmp     fhm_dir
fhm_nextside:
    inc     dword ptr [ebp-0x94]
    cmp     dword ptr [ebp-0x94], 2
    jl      fhm_side
fhm_none:
    or      eax, -1
    mov     edx, [ebp-0x74]
    ret

; ---- fh_vrun: face_pair_vrun(x = ebx, yn, b = eax) -> eax = b | -1; keeps ebx; clobbers ecx, edx, esi, edi
fh_vrun:
    mov     esi, [ebp-0x40]
    imul    esi, dword ptr [ebp-0x08]
    add     esi, ebx
    add     esi, [ebp-0x04]
    movzx   edx, byte ptr [esi]
    cmp     edx, dword ptr [ebp+0x0C]
    je      fhv_fail
    cmp     eax, edx
    je      fhv_fail
    cmp     eax, dword ptr [ebp+0x0C]
    je      fhv_fail
    mov     ecx, [ebp-0x04]
    add     ecx, ebx
    mov     [ebp-0x78], ecx
    mov     edi, [ebp-0x10]
    dec     edi
    imul    edi, dword ptr [ebp-0x08]
    add     ecx, edi
    mov     [ebp-0x7C], ecx
    mov     ch, al
    xor     ch, dl
    mov     dword ptr [ebp-0x70], 1
    mov     edi, esi
    mov     cl, dl
fhv_up:
    cmp     edi, dword ptr [ebp-0x78]
    je      fhv_dn0
    sub     edi, [ebp-0x08]
    xor     cl, ch
    cmp     byte ptr [edi], cl
    jne     fhv_dn0
    inc     dword ptr [ebp-0x70]
    cmp     dword ptr [ebp-0x70], {FACE_PAIR_MIN_VRUN}
    jge     fhv_ok
    jmp     fhv_up
fhv_dn0:
    mov     edi, esi
    mov     cl, dl
fhv_dn:
    cmp     edi, dword ptr [ebp-0x7C]
    je      fhv_fail
    add     edi, [ebp-0x08]
    xor     cl, ch
    cmp     byte ptr [edi], cl
    jne     fhv_fail
    inc     dword ptr [ebp-0x70]
    cmp     dword ptr [ebp-0x70], {FACE_PAIR_MIN_VRUN}
    jge     fhv_ok
    jmp     fhv_dn
fhv_fail:
    or      eax, -1
fhv_ok:
    ret

; ---- fh_luma: eax = index -> eax = b*114 + g*587 + r*299 over the dest RGBQUAD table (mon_luma); clobbers ecx, edx
fh_luma:
    mov     ecx, [ebp-0x24]
    lea     ecx, [ecx+eax*4]
    movzx   eax, byte ptr [ecx]
    imul    eax, eax, 114
    movzx   edx, byte ptr [ecx+1]
    imul    edx, edx, 587
    add     eax, edx
    movzx   edx, byte ptr [ecx+2]
    imul    edx, edx, 299
    add     eax, edx
    ret
"""


# ==== v4/v5: CITIZENS faces -- full-coverage resample in place of the engine's source-driven blit ==========
# CALL helper with Sprite_blit_scaled_core's contract (thiscall ecx=Sprite; dest, key, x, y; RET 0x10).  The engine
# core is SOURCE-driven and covers one dest column/row short of floor(30*g/16) at a fractional ratio: at g=25 the
# face's last source column (the right gold border) was dropped on every citizen face (user sweep 2026-09-11; g=22
# and g=40 kept it by phase).  v4 routed the faces to thunk_sprite_scale_nn (crisp NN, full coverage); v5 routes them
# to thunk_sprite_bilinear (palette-aware average): the WAR OUTPOST citizen's 1:1 edge dither still NN-banded at
# g=22/25.  Both take the Sprite_draw_2 contract, num/den = g/16 and the caller's dest/key/x/y (placement
# x + off*num/den exactly like the engine core).  They clip to the dest BOUNDS only, so the canvas height (+0x84,
# negative) is clamped to the clip rect's bottom (+0x2C) for the call and restored -- the report scrolls whole rows,
# the clip bottom is the only edge a face can meet.  g<=16 -> the engine core, byte-identical.
# v15 (2026-09-20): the callee is thunk_face_hybrid (same contract; the bilinear photo + the face's baked scanline
# background regenerated at device density, scaling_laws.face_hybrid_enlarge); it reads +0x84 inside this bracket.
def asm_rwk_face_blit() -> str:       # CALL helper: thiscall(ecx=Sprite)(dest, key, x, y) RET 0x10
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    push    ebx
    mov     ebx, dword ptr [esp+8]
    push    dword ptr [ebx+0x84]
    mov     eax, dword ptr [ebx+0x2C]
    neg     eax
    mov     dword ptr [ebx+0x84], eax
    push    16
    push    dword ptr [{G:#x}]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    mov     eax, {FACE_HYBRID:#x}
    call    eax
    pop     dword ptr [ebx+0x84]
    pop     ebx
    ret     0x10
native:
    jmp     {BLIT_CORE:#x}
"""


# ==== v16 (2026-09-26): intel PROFILE page (ReportWin kind 0) =======================================
# The leader portrait (g_faction_art[f] +0, 131x157, key 9) is the page's only sprite: ReportWin_draw_intel calls
# Sprite_blit_scaled_core(dest=RW canvas, key, x=[+0xA14], y=[+0xA18]) @0x4A2415 under SCALE 1/1, so it stayed native at
# every g while the dossier column already sits at x + s(158) (user shot _Problems/ProfilePage.png: a 157-px picture
# beside a 264-px gap at 4K).  CALL helper with the core's contract (thiscall ecx=Sprite; dest,key,x,y; RET 0x10):
# g<=16 -> the engine core untouched; else the six-arg Sprite_draw_2 contract with num/den = g/16 through
# thunk_art_draw, with thunk_portrait_avg's dest gate pointed at the report canvas for exactly this call (saved and
# restored around it, the t_dw_artL shape) so the A5 palette-aware bilinear + the parity re-blit + the DLL's Lanczos
# composite handle the enlarge -- byte-for-byte the path the Datalinks FACTION PROFILES portrait takes.  Drawn size =
# fl(131*g/16) x fl(157*g/16) at the caller's x/y (already device space); the text column's s(158) keeps the vanilla
# 27-px gap proportionate.  Sprite_draw_2 saves/sets/restores SCALE_NUM_G/DEN_G itself (no G bracket needed).
# v16b: also records g_rwk_intel_pbot = y + fl(h*g/16) + s(4) (h = Sprite blit_h +0x14 + off_y +0x24, the resampler's own idiv placement/height law) for
# t_rwk_intel_blocky (scaling_laws.intel_block_top); eax/edx are the call's scratch (the engine core clobbers them too).
def asm_rwk_intel_portrait() -> str:   # CALL helper: thiscall(ecx=Sprite)(dest, key, x, y) RET 0x10
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    mov     eax, dword ptr [esp+0x10]
    mov     edx, dword ptr [ecx+0x14]
    add     edx, dword ptr [ecx+0x24]
    {FL("edx")}
    add     eax, edx
    mov     edx, 4
    {HD("edx")}
    add     eax, edx
    mov     dword ptr [{_cell('g_rwk_intel_pbot'):#x}], eax
    push    dword ptr [{PAVG_GATE_IMM:#x}]
    mov     dword ptr [{PAVG_GATE_IMM:#x}], {RW_CANVAS:#x}
    push    16
    push    dword ptr [{G:#x}]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    call    {ART_DRAW:#x}
    pop     dword ptr [{PAVG_GATE_IMM:#x}]
    ret     0x10
native:
    jmp     {BLIT_CORE:#x}
"""


# The intel console's centre panel title ("[FACTION] INTELLIGENCE FILES, M.Y. n") is centred right of the faction logo:
# x += wide ? 0x4C : 0 (eax = 0/-1 mask) @0x4AC4BE -- imm8, so the proto's row never covered it (s(0x4C) = 190 at g=40);
# the labs console's twin 0x4A75FF is caved as t_rw_title.  Same law: mask & s(0x4C).  Displaced 5B: and eax,0x4C /
# mov ecx,eax; edx (the panel x) is live across the site.
def asm_rwk_intel_title() -> str:   # @0x4AC4BE 5B: and eax,0x4C / mov ecx,eax
    return f"""
    push    edx
    mov     edx, 0x4C
    {HD("edx")}
    and     eax, edx
    pop     edx
    mov     ecx, eax
    jmp     0x4AC4C3
"""


# The two console ListBox rects (left / right panels): L/T get +3 through rows 0x4AC2F3/0x4AC300 (0x4AC761/0x4AC76E)
# while R/B came from `mov eax,-3` (imm32 @0x4AC2F9 / 0x4AC767) -> native 3 px at every g (4 px asymmetric at 4K).
# The shared imm table is full to its 16-byte pad (moving it would shift every rw cell), so each is a 5B detour:
# eax = -s(3).  The row at 0x4AC300 / 0x4AC76E lies OUTSIDE the displaced range (row_site_conflicts guards it).
def _asm_intel_lbr(resume: int) -> str:
    return f"""
    mov     eax, 3
    {HD("eax")}
    neg     eax
    jmp     {resume:#x}
"""


def asm_rwk_intel_lbr_l() -> str:   # @0x4AC2F9 5B: mov eax,-3  (left ListBox R/B inset)
    return _asm_intel_lbr(0x4AC2FE)


def asm_rwk_intel_lbr_r() -> str:   # @0x4AC767 5B: mov eax,-3  (right ListBox R/B inset)
    return _asm_intel_lbr(0x4AC76C)


# v17 (2026-10-11): the same two levers at the SIX other console painters (energy / ops / projects / sat / units /
# score), which kept the native constants (live bytes == pristine, no row, no detour).  One shared CALL helper per
# displaced shape instead of a detour per site (E8 rel32 over the 5 bytes; the helper does the displaced work, rets).
#   title  `and eax,0x4C / add ecx,eax` (5 sites) and `and eax,0x4C / mov ecx,eax` (units 0x4ABAD3): law
#          scaling_laws.rw_console_title_inset; edx preserved; EFLAGS on return = the vanilla last ALU op's (add / and).
#   lbr    `mov eax,-3` (7 sites): law scaling_laws.rw_console_listbox_rb.  The helper leaves EFLAGS from neg where
#          vanilla left them untouched: dead at every site (the next instruction is an `add`, which writes all six).
TITLE_ADD_SITES = [(0x4A8961, "energy"), (0x4A9B95, "ops"), (0x4AA490, "projects"), (0x4AADC9, "sat"), (0x4ABF0E, "score")]
TITLE_MOV_SITES = [(0x4ABAD3, "units")]
LBR_SITES = [(0x4A864F, "energy", "listA"), (0x4A8D04, "energy", "listB"), (0x4AA1F8, "projects", "list"),
             (0x4AABF3, "sat", "listA"), (0x4AB1BE, "sat", "listB"), (0x4AB6B1, "units", "listA"), (0x4ABD22, "units", "listB")]   # 0x4ABD22 lies in units (0x4AB600..ret 0x4ABE23), not score
CONSOLE_FN = {"energy": "ReportIf_console_energy", "ops": "ReportIf_console_ops", "projects": "ReportIf_console_projects",
              "sat": "ReportIf_console_sat", "units": "ReportIf_console_units", "score": "ReportIf_console_score"}


def _asm_con_title(tail: str) -> str:
    return f"""
    push    edx
    mov     edx, 0x4C
    {HD("edx")}
    and     eax, edx
    pop     edx
    {tail}
    ret
"""


def asm_rwk_con_title_add() -> str:   # CALL helper for `and eax,0x4C / add ecx,eax` (5B)
    return _asm_con_title("add     ecx, eax")


def asm_rwk_con_title_mov() -> str:   # CALL helper for `and eax,0x4C / mov ecx,eax` (5B, units)
    return _asm_con_title("mov     ecx, eax")


def asm_rwk_con_lbr() -> str:         # CALL helper for `mov eax,-3` (5B)
    return f"""
    mov     eax, 3
    {HD("eax")}
    neg     eax
    ret
"""


# 2026-10-11: the report lists' text pad.  ListBox_close (0x609F20, esi = the ListBox element) re-seeds the per-list
# text pad [elem+0x2C] from the static default [0x6970E4] = 2 on every close; ListBox_draw_item insets each column's
# text rect by pad + 1 per side, so the right-aligned column ended 1 px from the s(12) bar trough at g=25 (F3 BASE
# EXPENDITURES) and the left text sat 3 native px from the stroke.  Every report list closes right before its
# Dialog_init_3: the six console lists INSIDE the g_rw_inlist bracket (scroll_small .. close .. init .. attach ..
# scroll_normal, all six call orders verified), the energy page's canvas list ReportWin+0x5A0C (0x49CC46) just before
# t_rwsb_begin opens its bar bracket -> keyed on the element address.  Law scaling_laws.rw_list_text_pad.
LB_PAD_DEFAULT = 0x006970E4          # ListBox ctor/close default text pad (2)
LB_TEXTPAD_SITE = 0x00609F5E         # ListBox_close: mov edx,[0x6970E4] (6B) / mov [esi+0x2C],edx
RW_ENERGY_LIST = RW + 0x5A0C         # ReportWin_draw_energy's ListBox element (closed at 0x49CC46)


def asm_lb_textpad() -> str:         # CALL helper for `mov edx,[0x6970E4]` (6B -> E8 rel32 + 90); edx only, flags dead
    return f"""
    mov     edx, dword ptr [{LB_PAD_DEFAULT:#x}]
    cmp     dword ptr [{G:#x}], 16
    jle     done
    cmp     dword ptr [{_cell('g_rw_inlist'):#x}], 0
    jne     scale
    cmp     esi, {RW_ENERGY_LIST:#x}
    jne     done
scale:
    mov     edx, 3
    {HD("edx")}
    dec     edx
done:
    ret
"""


# The POLITICS / treaty block: vanilla advances y = y + lineH + 0x14 after the COUNCIL VOTES row (@0x4A3046: add eax,edx /
# mov [esi+0xA18],eax) with 8..11 rows above it (AGENDA / ENERGY RESERVES / RESEARCHING are conditional) and lets the block
# overlap the 157-px portrait by 2 (9 rows) / 17 (8 rows) native px.  The enlarged portrait grows as fl(157*g/16) while
# the line height is sublinear (36 at g=40, not 37.5), so the overlap deepens to 18 / 54 device px at 4K.  Law
# scaling_laws.intel_block_top: y = max(flow y, g_rwk_intel_pbot); the cell is written by t_rwk_intel_portrait only at g>16
# and is 0 otherwise (section data), so g<=16 is byte-identical.  eax is the flow y, edx dead after (0x4A304E xor eax,eax).
# ==== slide-window chrome: the outer rail strips' start row (report-wide, every slide window) ==================
# slide_show 0x45D440 draws the 4 rail strips: the 8-px inner pair at y=0 and the 15x529 OUTER pair whose start is
# A = [ebp-0x24] = 0x5E + (ScreenWidth != 800 ? 0x90 : 0) = 238 = SCREEN row 238 (238 + 529 = 767 = the last row of
# the 768 screen: the outer art's foot lands on the screen floor, hidden under the console).  For ReportWin (top 3)
# the wide pillar therefore starts 235 rows below the window top in vanilla.  A is consumed by TWO kinds of draw:
#   * the open/close ANIMATION frames (slide_show loop 0x45D68F.., slide_hide 0x45DC5B..): y = max(slide_y, A) in
#     SCREEN coordinates onto the screen buffer, through thunk_railslide (v2 2026-10-17: device y as pushed, outer
#     top no higher than the settled one, law slide_rail_anim_y), and
#   * the two SETTLED draws (0x45D7FD.. / 0x45D87A..): v = max(slide_y, A) - T window-local, through
#     thunk_filedlg_railscale's v1 shim (fl(v*g/16)).
# Both compared the NATIVE 238 against DEVICE positions, so at 4K (T_dev 246) the wide pillars began at the window
# top on every report page (user 4K shots 175649 intel / F2 / F4; 2 px at 1600x1200, invisible in verification).
# v3 (two antagonist rounds): the cells hold R_dev = ScreenHeight_dev - fl(530*g/16) (law slide_rail_outer_row,
# identity 238 at 768/g16) so the animation frames are right as they are, and the two settled sites ceil-descale
# their v (law slide_rail_settled_v: v' = ceil(v*16/g), the shim's fl(v'*g/16) lands on R_dev - T within g/16 - 1,
# [[feedback-floor-descale-roundtrip]]).  g<=16: every path byte-identical to vanilla.
SCREEN_W, SCREEN_H = 0x009B7B1C, 0x009B7B20
SLIDE_OUTER_H = 530          # 529-row outer strip + 1: R = SH - 530 puts its foot on the screen floor


def _asm_slide_rail(prefix: str, sw_reg: str, store: str, resume: int) -> str:
    # the A cell = R_dev at g>16, the native constant at g<=16 (sw_reg = the register the native sequence loads
    # ScreenWidth into; reloaded on the scaled path too so both paths leave the same registers)
    return f"""
{prefix}
    cmp     dword ptr [{G:#x}], 16
    jle     native
    mov     eax, {SLIDE_OUTER_H}
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     edx, dword ptr [{SCREEN_H:#x}]
    sub     edx, eax
    mov     eax, edx
    mov     {sw_reg}, dword ptr [{SCREEN_W:#x}]
    jmp     store
native:
    mov     {sw_reg}, dword ptr [{SCREEN_W:#x}]
    xor     eax, eax
    cmp     {sw_reg}, 0x320
    setne   al
    neg     eax
    sbb     eax, eax
    and     eax, 0x90
    add     eax, 0x5E
store:
    mov     dword ptr [{store}], eax
    jmp     {resume:#x}
"""


def asm_slide_rail_a() -> str:      # @0x45D4AE 40B (slide_show): A = [ebp-0x24] (+ push ebx / push edi / mov edi,[0x93F660])
    return _asm_slide_rail("    push    ebx\n    push    edi\n    mov     edi, dword ptr [0x93F660]", "edx", "ebp-0x24", 0x45D4D6)


def asm_slide_rail_a2() -> str:     # @0x45DA07 33B (slide_hide): A = [ebp-0x38] (+ push ebx)
    return _asm_slide_rail("    push    ebx", "ecx", "ebp-0x38", 0x45DA28)


# The settled draws: v = max(slide_y, A) - T is window-local and goes through the railscale shim (x g/16), so hand it
# back ceil-descaled.  v >= 0 always here (settled slide_y == T, A >= T or clamped), so the idiv is the plain ceil.
def asm_slide_rail_s1() -> str:     # @0x45D7FD 17B: eax = max(esi,A) - T; ecx = T; edx = L   (left outer strip)
    return f"""
    mov     eax, dword ptr [ebp-0x24]
    cmp     esi, eax
    jle     s1max
    mov     eax, esi
s1max:
    mov     ecx, dword ptr [ebp-0x18]
    mov     edx, dword ptr [ebp-0x1C]
    sub     eax, ecx
    cmp     dword ptr [{G:#x}], 16
    jle     s1done
    push    ecx
    push    edx
    mov     ecx, dword ptr [{G:#x}]
    shl     eax, 4
    add     eax, ecx
    dec     eax
    cdq
    idiv    ecx
    pop     edx
    pop     ecx
s1done:
    jmp     0x45D80E
"""


def asm_slide_rail_s2() -> str:     # @0x45D87A 20B: esi = max(esi,A) - T; edx = T; eax = [ebp-0x2C]; ecx = L   (right outer strip)
    return f"""
    mov     eax, dword ptr [ebp-0x24]
    cmp     esi, eax
    jg      s2max
    mov     esi, eax
s2max:
    mov     edx, dword ptr [ebp-0x18]
    sub     esi, edx
    cmp     dword ptr [{G:#x}], 16
    jle     s2done
    push    edx
    mov     ecx, dword ptr [{G:#x}]
    mov     eax, esi
    shl     eax, 4
    add     eax, ecx
    dec     eax
    cdq
    idiv    ecx
    mov     esi, eax
    pop     edx
s2done:
    mov     eax, dword ptr [ebp-0x2C]
    mov     ecx, dword ptr [ebp-0x1C]
    jmp     0x45D88E
"""


# ==== console list bar arrows: the admission for BOTH stashed bars (btn_gate_pre v7, btn_stripes v11) =========
# CALL helper (esi = the FlatButton `this` btn_gate / btn_stripes are consulted with): eax = 1 when esi is the up
# (+0xAAC) or down (+0x15F8 = +0xAAC+0xB4C) arrow of either console list bar in g_rw_sbs[0..1], while
# g_modal_top == ReportWin_g AND the bar's parent [+0xC4] still equals g_rw_sbparents[i] (heap bars: the report's
# own list bar reuses freed console-bar addresses within one kind session -- the parent check refuses the stale
# pointer); else 0.  Clobbers eax only (edx saved).  v1 keyed on g_rw_sb = the LAST stashed bar only -> the left
# list's arrows drew native on hover (probe 2026-09-26).  Pinned 0xC980 (cave_map: 0xC979..0xCA00 free).
G_MODAL_TOP = 0x009B7AE0


RW_ENERGY_VBAR = 0x0087C308   # assemble_stripes_rwsb.RW_ENERGY_VBAR: the energy ListBox Win's heap V bar (0 when closed)


def asm_rw_sbarrows() -> str:
    # v3 (assemble_stripes_rwsb.sbarrows_text(s, True), 128B): the energy list bar's two arrow FlatButtons are tested
    # FIRST (no modal-top gate, no parent check).  Emitted here so the rw fragment carries v3: refresh_rw_yaml.py used to
    # revert patches.yaml to this function's v2 (106B) text.
    return f"""
    push    edx
    mov     eax, esi
    sub     eax, dword ptr [{RW_ENERGY_VBAR:#x}]
    cmp     eax, 0xAAC
    je      hit
    cmp     eax, 0x15F8
    je      hit
    mov     eax, dword ptr [{G_MODAL_TOP:#x}]
    cmp     eax, {RW:#x}
    jne     miss
    mov     eax, dword ptr [{_cell('g_rw_sbs'):#x}]
    test    eax, eax
    jz      slot1
    mov     edx, dword ptr [eax+0xC4]
    cmp     edx, dword ptr [{_cell('g_rw_sbparents'):#x}]
    jne     slot1
    add     eax, 0xAAC
    cmp     esi, eax
    je      hit
    add     eax, 0xB4C
    cmp     esi, eax
    je      hit
slot1:
    mov     eax, dword ptr [{_cell('g_rw_sbs') + 4:#x}]
    test    eax, eax
    jz      miss
    mov     edx, dword ptr [eax+0xC4]
    cmp     edx, dword ptr [{_cell('g_rw_sbparents') + 4:#x}]
    jne     miss
    add     eax, 0xAAC
    cmp     esi, eax
    je      hit
    add     eax, 0xB4C
    cmp     esi, eax
    je      hit
miss:
    xor     eax, eax
    pop     edx
    ret
hit:
    mov     eax, 1
    pop     edx
    ret
"""


def asm_rwk_intel_blocky() -> str:   # @0x4A3046 8B: add eax,edx / mov [esi+0xA18],eax
    return f"""
    add     eax, edx
    cmp     eax, dword ptr [{_cell('g_rwk_intel_pbot'):#x}]
    jge     keep
    mov     eax, dword ptr [{_cell('g_rwk_intel_pbot'):#x}]
keep:
    mov     dword ptr [esi+0xA18], eax
    jmp     0x4A304E
"""


# ==== v2: parity-preserving NN sprite enlarge (the console icon family) =========================
# Drop-in for Sprite_draw_2 (ecx=Sprite*, stack dest,key,x,y,num,den; RET 0x18), the thunk_sprite_scale_nn
# contract (output-driven, centre-sampled, edge-clamped columns) plus the scanline law: the sprite's TOP
# stripe parity is voted from its own texels (scaling_laws.stripe_parity_vote_sums, dest palette at
# dest+0xA4), and every dest row samples the native row of the parity its device stripe phase demands
# (parity_nn_row; phase grid = the PARENT's rows: dest is a FlatButton canvas, top = [btn+0x140]).
# Only t_rw_iconblit's hit path enters (g>16, the 7 kind-tab + 7 faction-tab state sprites); any guard
# failure tail-jumps the engine's Sprite_draw_2.  User-verified proto v1..v3 at 1600/1920/4K.
# v2 (2026-09-12, laws scaling_laws.bilinear_axis / parity_hblend_pixel / palette_nearest): the COLUMNS
# take thunk_sprite_bilinear's tap law (i0 = floor(dx*den/num), i1 = i0+1 clamped, 8.8 weight, coverage =
# the nearer tap) INSIDE the parity-selected native row: equal taps or a key tap emit the surviving index
# verbatim (the stripe pair members survive for the later restripe passes), a true glyph edge blends the
# two palette entries and takes the nearest dest-palette index (never the key).  The icon art is row-
# parity through and through (Report.pcx: odd rows E6/BB, even rows B0/37), so the v1 NN columns' 1/2-px
# beat at 22/16 and 25/16 (a 2-px stem = 3 or 4 device px by phase) was the only artefact left; the rows
# keep the v1 law exactly.  Frame 0xB0 (v1 0xA0): locals -0x90 i0, -0x94 i1, -0x98 f, -0x9C near, -0xA0..
# -0xA8 the blended channels.  Pinned at pcave2 0x213C0 (after the bilinear; the rw region is full).
def asm_rwk_parity_nn() -> str:
    return f"""
    mov     eax, dword ptr [esp+0x18]
    test    eax, eax
    jle     pn_native
    mov     eax, dword ptr [ecx+0x10]
    test    eax, eax
    jle     pn_native
    mov     eax, dword ptr [ecx+0x14]
    test    eax, eax
    jle     pn_native
    mov     eax, dword ptr [ecx+0x04]
    test    eax, eax
    je      pn_native
    mov     eax, dword ptr [esp+0x04]
    mov     eax, dword ptr [eax+0x54]
    test    eax, eax
    je      pn_native
    mov     eax, dword ptr [esp+0x04]
    mov     eax, dword ptr [eax+0x4A8]
    test    eax, eax
    jle     pn_native
    push    ebp
    mov     ebp, esp
    sub     esp, 0xB0
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [ecx+0x04]
    mov     dword ptr [ebp-0x04], eax
    mov     eax, dword ptr [ecx+0x0C]
    cmp     eax, 0
    jg      pn_sstr_ok
    mov     eax, dword ptr [ecx+0x10]
pn_sstr_ok:
    mov     dword ptr [ebp-0x08], eax
    mov     eax, dword ptr [ecx+0x10]
    mov     dword ptr [ebp-0x0C], eax
    mov     eax, dword ptr [ecx+0x14]
    mov     dword ptr [ebp-0x10], eax
    mov     eax, dword ptr [ebp+0x08]
    mov     edx, dword ptr [eax+0x54]
    mov     dword ptr [ebp-0x14], edx
    mov     edx, dword ptr [eax+0x4A8]
    mov     dword ptr [ebp-0x18], edx
    mov     edx, dword ptr [eax+0x80]
    mov     dword ptr [ebp-0x1C], edx
    mov     edx, dword ptr [eax+0x84]
    neg     edx
    mov     dword ptr [ebp-0x20], edx
    lea     edx, [eax+0xA4]
    mov     dword ptr [ebp-0x68], edx
    mov     edx, dword ptr [eax-0x304]
    mov     dword ptr [ebp-0x54], edx
    mov     eax, dword ptr [ebp+0x18]
    mov     dword ptr [ebp-0x24], eax
    mov     eax, dword ptr [ebp+0x1C]
    mov     dword ptr [ebp-0x28], eax
    mov     eax, dword ptr [ebp+0x0C]
    mov     dword ptr [ebp-0x2C], eax
    mov     eax, dword ptr [ecx+0x20]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    add     eax, dword ptr [ebp+0x10]
    mov     dword ptr [ebp-0x30], eax
    mov     eax, dword ptr [ecx+0x24]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [ebp-0x34], eax
    mov     eax, dword ptr [ebp-0x0C]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    mov     dword ptr [ebp-0x38], eax
    mov     eax, dword ptr [ebp-0x10]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    mov     dword ptr [ebp-0x3C], eax
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [ebp-0x5C], eax
    cmp     eax, 22
    sbb     edx, edx
    shr     eax, 4
    cmp     eax, 2
    adc     eax, edx
    add     eax, eax
    mov     dword ptr [ebp-0x60], eax
    inc     eax
    sar     eax, 1
    mov     dword ptr [ebp-0x64], eax
    xor     eax, eax
    mov     dword ptr [ebp-0x6C], eax
    mov     dword ptr [ebp-0x70], eax
    mov     dword ptr [ebp-0x74], eax
    mov     dword ptr [ebp-0x78], eax
    mov     dword ptr [ebp-0x7C], eax
    mov     dword ptr [ebp-0x80], eax
    mov     dword ptr [ebp-0x84], eax
pn_vy:
    mov     eax, dword ptr [ebp-0x84]
    cmp     eax, dword ptr [ebp-0x10]
    jge     pn_vend
    mov     dword ptr [ebp-0x88], 0
pn_vx:
    mov     eax, dword ptr [ebp-0x88]
    cmp     eax, dword ptr [ebp-0x0C]
    jge     pn_vxend
    mov     eax, dword ptr [ebp-0x84]
    imul    eax, dword ptr [ebp-0x08]
    add     eax, dword ptr [ebp-0x88]
    add     eax, dword ptr [ebp-0x04]
    movzx   eax, byte ptr [eax]
    cmp     eax, dword ptr [ebp-0x2C]
    je      pn_vxnext
    mov     edx, dword ptr [ebp-0x68]
    lea     edx, [edx+eax*4]
    movzx   ebx, byte ptr [edx]
    movzx   esi, byte ptr [edx+1]
    movzx   edi, byte ptr [edx+2]
    mov     eax, ebx
    cmp     eax, esi
    jge     pn_p1
    mov     eax, esi
pn_p1:
    cmp     eax, edi
    jge     pn_p2
    mov     eax, edi
pn_p2:
    lea     ecx, [ebx+esi]
    add     ecx, edi
    test    dword ptr [ebp-0x84], 1
    jnz     pn_vodd
    add     dword ptr [ebp-0x74], eax
    add     dword ptr [ebp-0x7C], ecx
    inc     dword ptr [ebp-0x6C]
    jmp     pn_vxnext
pn_vodd:
    add     dword ptr [ebp-0x78], eax
    add     dword ptr [ebp-0x80], ecx
    inc     dword ptr [ebp-0x70]
pn_vxnext:
    inc     dword ptr [ebp-0x88]
    jmp     pn_vx
pn_vxend:
    inc     dword ptr [ebp-0x84]
    jmp     pn_vy
pn_vend:
    mov     dword ptr [ebp-0x58], -1
    cmp     dword ptr [ebp-0x5C], 16
    jle     pn_vdone
    cmp     dword ptr [ebp-0x10], 2
    jl      pn_vdone
    cmp     dword ptr [ebp-0x6C], 0
    je      pn_vdone
    cmp     dword ptr [ebp-0x70], 0
    je      pn_vdone
    mov     eax, dword ptr [ebp-0x74]
    xor     edx, edx
    div     dword ptr [ebp-0x6C]
    mov     ecx, eax
    mov     eax, dword ptr [ebp-0x78]
    xor     edx, edx
    div     dword ptr [ebp-0x70]
    sub     eax, ecx
    mov     edx, eax
    test    edx, edx
    jns     pn_a1
    neg     edx
pn_a1:
    cmp     edx, 4
    jge     pn_decide
    mov     eax, dword ptr [ebp-0x7C]
    xor     edx, edx
    div     dword ptr [ebp-0x6C]
    mov     ecx, eax
    mov     eax, dword ptr [ebp-0x80]
    xor     edx, edx
    div     dword ptr [ebp-0x70]
    sub     eax, ecx
    mov     edx, eax
    test    edx, edx
    jns     pn_a2
    neg     edx
pn_a2:
    cmp     edx, 4
    jl      pn_vdone
pn_decide:
    test    eax, eax
    jle     pn_dz
    mov     dword ptr [ebp-0x58], 1
    jmp     pn_vdone
pn_dz:
    mov     dword ptr [ebp-0x58], 0
pn_vdone:
    mov     dword ptr [ebp-0x40], 0
pn_yloop:
    mov     eax, dword ptr [ebp-0x40]
    cmp     eax, dword ptr [ebp-0x3C]
    jge     pn_yend
    mov     eax, dword ptr [ebp-0x34]
    add     eax, dword ptr [ebp-0x40]
    cmp     eax, 0
    jl      pn_ynext
    cmp     eax, dword ptr [ebp-0x20]
    jge     pn_ynext
    mov     eax, dword ptr [ebp-0x40]
    add     eax, eax
    inc     eax
    imul    eax, dword ptr [ebp-0x10]
    cdq
    mov     ecx, dword ptr [ebp-0x3C]
    add     ecx, ecx
    idiv    ecx
    mov     ecx, dword ptr [ebp-0x10]
    dec     ecx
    cmp     eax, ecx
    jle     pn_syhi
    mov     eax, ecx
pn_syhi:
    test    eax, eax
    jns     pn_sylo
    xor     eax, eax
pn_sylo:
    mov     dword ptr [ebp-0x8C], eax
    cmp     dword ptr [ebp-0x58], 0
    jl      pn_rowok
    mov     eax, dword ptr [ebp-0x54]
    add     eax, dword ptr [ebp-0x34]
    add     eax, dword ptr [ebp-0x40]
    cdq
    idiv    dword ptr [ebp-0x60]
    test    edx, edx
    jns     pn_m1
    add     edx, dword ptr [ebp-0x60]
pn_m1:
    mov     eax, dword ptr [ebp-0x58]
    cmp     edx, dword ptr [ebp-0x64]
    jl      pn_w1
    xor     eax, 1
pn_w1:
    mov     ecx, dword ptr [ebp-0x8C]
    mov     edx, ecx
    and     edx, 1
    cmp     edx, eax
    je      pn_rowok
    lea     edx, [ecx-1]
    test    edx, edx
    js      pn_usehi
    lea     eax, [ecx+1]
    cmp     eax, dword ptr [ebp-0x10]
    jge     pn_uselo
    mov     esi, dword ptr [ebp-0x40]
    add     esi, esi
    inc     esi
    imul    esi, dword ptr [ebp-0x10]
    lea     edi, [edx+edx+1]
    imul    edi, dword ptr [ebp-0x3C]
    sub     edi, esi
    test    edi, edi
    jns     pn_d1
    neg     edi
pn_d1:
    lea     ebx, [eax+eax+1]
    imul    ebx, dword ptr [ebp-0x3C]
    sub     ebx, esi
    test    ebx, ebx
    jns     pn_d2
    neg     ebx
pn_d2:
    cmp     edi, ebx
    jle     pn_uselo
    mov     dword ptr [ebp-0x8C], eax
    jmp     pn_rowok
pn_usehi:
    lea     eax, [ecx+1]
    mov     dword ptr [ebp-0x8C], eax
    jmp     pn_rowok
pn_uselo:
    mov     dword ptr [ebp-0x8C], edx
pn_rowok:
    mov     eax, dword ptr [ebp-0x8C]
    imul    eax, dword ptr [ebp-0x08]
    mov     dword ptr [ebp-0x4C], eax
    mov     eax, dword ptr [ebp-0x34]
    add     eax, dword ptr [ebp-0x40]
    imul    eax, dword ptr [ebp-0x18]
    mov     dword ptr [ebp-0x50], eax
    mov     dword ptr [ebp-0x44], 0
pn_xloop:
    mov     eax, dword ptr [ebp-0x44]
    cmp     eax, dword ptr [ebp-0x38]
    jge     pn_xend
    mov     eax, dword ptr [ebp-0x30]
    add     eax, dword ptr [ebp-0x44]
    cmp     eax, 0
    jl      pn_xnext
    cmp     eax, dword ptr [ebp-0x1C]
    jge     pn_xnext
    mov     eax, dword ptr [ebp-0x44]
    imul    eax, dword ptr [ebp-0x28]
    cdq
    idiv    dword ptr [ebp-0x24]
    mov     ecx, dword ptr [ebp-0x0C]
    dec     ecx
    cmp     eax, ecx
    jle     pn_x0ok
    mov     eax, ecx
pn_x0ok:
    mov     dword ptr [ebp-0x90], eax
    lea     esi, [eax+1]
    cmp     esi, ecx
    jle     pn_x1ok
    mov     esi, ecx
pn_x1ok:
    mov     dword ptr [ebp-0x94], esi
    mov     ecx, edx
    lea     edx, [ecx+ecx]
    cmp     edx, dword ptr [ebp-0x24]
    jl      pn_near0
    mov     eax, esi
pn_near0:
    mov     dword ptr [ebp-0x9C], eax
    mov     eax, ecx
    shl     eax, 8
    xor     edx, edx
    div     dword ptr [ebp-0x24]
    mov     dword ptr [ebp-0x98], eax
    mov     esi, dword ptr [ebp-0x4C]
    add     esi, dword ptr [ebp-0x04]
    mov     eax, dword ptr [ebp-0x9C]
    movzx   eax, byte ptr [esi+eax]
    cmp     eax, dword ptr [ebp-0x2C]
    je      pn_xnext
    mov     ecx, dword ptr [ebp-0x90]
    movzx   ecx, byte ptr [esi+ecx]
    mov     edx, dword ptr [ebp-0x94]
    movzx   edx, byte ptr [esi+edx]
    cmp     ecx, edx
    je      pn_emit
    cmp     ecx, dword ptr [ebp-0x2C]
    jne     pn_t0ok
    mov     ecx, edx
    jmp     pn_emit
pn_t0ok:
    cmp     edx, dword ptr [ebp-0x2C]
    je      pn_emit
    mov     esi, dword ptr [ebp-0x68]
    lea     ebx, [esi+ecx*4]
    lea     edi, [esi+edx*4]
    mov     esi, dword ptr [ebp-0x98]
    mov     ecx, 256
    sub     ecx, esi
    movzx   eax, byte ptr [ebx]
    imul    eax, ecx
    movzx   edx, byte ptr [edi]
    imul    edx, esi
    add     eax, edx
    add     eax, 128
    shr     eax, 8
    mov     dword ptr [ebp-0xA0], eax
    movzx   eax, byte ptr [ebx+1]
    imul    eax, ecx
    movzx   edx, byte ptr [edi+1]
    imul    edx, esi
    add     eax, edx
    add     eax, 128
    shr     eax, 8
    mov     dword ptr [ebp-0xA4], eax
    movzx   eax, byte ptr [ebx+2]
    imul    eax, ecx
    movzx   edx, byte ptr [edi+2]
    imul    edx, esi
    add     eax, edx
    add     eax, 128
    shr     eax, 8
    mov     dword ptr [ebp-0xA8], eax
    mov     esi, dword ptr [ebp-0x68]
    xor     ecx, ecx
    xor     edi, edi
    mov     ebx, 0x7FFFFFFF
pn_nloop:
    cmp     ecx, dword ptr [ebp-0x2C]
    je      pn_nskip
    movzx   eax, byte ptr [esi]
    sub     eax, dword ptr [ebp-0xA0]
    imul    eax, eax
    mov     edx, eax
    movzx   eax, byte ptr [esi+1]
    sub     eax, dword ptr [ebp-0xA4]
    imul    eax, eax
    add     edx, eax
    movzx   eax, byte ptr [esi+2]
    sub     eax, dword ptr [ebp-0xA8]
    imul    eax, eax
    add     edx, eax
    cmp     edx, ebx
    jge     pn_nskip
    mov     ebx, edx
    mov     edi, ecx
pn_nskip:
    add     esi, 4
    inc     ecx
    cmp     ecx, 256
    jl      pn_nloop
    mov     ecx, edi
pn_emit:
    mov     eax, dword ptr [ebp-0x30]
    add     eax, dword ptr [ebp-0x44]
    add     eax, dword ptr [ebp-0x50]
    add     eax, dword ptr [ebp-0x14]
    mov     byte ptr [eax], cl
pn_xnext:
    inc     dword ptr [ebp-0x44]
    jmp     pn_xloop
pn_xend:
pn_ynext:
    inc     dword ptr [ebp-0x40]
    jmp     pn_yloop
pn_yend:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x18
pn_native:
    push    {SPRITE_DRAW_2:#x}
    ret
"""


# ---- thunk registry (name, asm fn) in group rw_scale_kinds ---------------------------
THUNKS = [
    ("t_rwk_proj_rowdiv", asm_rwk_proj_rowdiv), ("t_rwk_proj_rowy", asm_rwk_proj_rowy), ("t_rwk_units_rowdiv", asm_rwk_units_rowdiv),
    ("t_rwk_units_rowstep", asm_rwk_units_rowstep),   # v18 (pinned 0x23B40; proj_rowy / units_rowdiv / proj_rowdiv pinned 0x1A930 / 0x1A9A0 / 0x23BA0)
    ("t_rwk_bases_namex", asm_rwk_bases_namex), ("t_rwk_intel_textx", asm_rwk_intel_textx),
    ("t_rwk_gov_split1", asm_rwk_gov_split1), ("t_rwk_gov_split2", asm_rwk_gov_split2),
    ("t_rwk_sat_w", asm_rwk_sat_w), ("t_rwk_modes_w", asm_rwk_modes_w),   # 2026-10-17: in gov_split v2's freed slot tail (FROZEN sat_split1)
    ("t_rwk_ops_w", asm_rwk_ops_w), ("t_rwk_ops_lx", asm_rwk_ops_lx), ("t_rwk_ops_lw", asm_rwk_ops_lw),   # pinned
    ("t_rwk_govlist", asm_rwk_govlist),                                                                      # pinned
    ("t_rwk_sat_split1", asm_rwk_sat_split1), ("t_rwk_sat_split2", asm_rwk_sat_split2),
    ("t_rwk_sat_cx", asm_rwk_sat_cx), ("t_rwk_sat_cy", asm_rwk_sat_cy),
    ("t_rwk_gblit", asm_rwk_gblit), ("t_rwk_gdraw", asm_rwk_gdraw), ("t_rwk_gtable", asm_rwk_gtable),
    ("t_rwk_scrollshow", asm_rwk_scrollshow), ("t_rwk_scrollhide", asm_rwk_scrollhide),
    # v2 (2026-09-10)
    ("t_rwk_bases_cell", asm_rwk_bases_cell), ("t_rwk_bases_cellx", asm_rwk_bases_cellx),
    ("t_rwk_bases_celly", asm_rwk_bases_celly), ("t_rwk_bases_facey", asm_rwk_bases_facey),
    ("t_rwk_boxhalf", asm_rwk_boxhalf), ("t_rwk_parity_nn", asm_rwk_parity_nn),
    # v3 (2026-09-10)
    ("t_rwk_boxforce", asm_rwk_boxforce),
    # 2026-10-17: the kind-icon strip's da50 under its clip (pinned 0x1CF50 / 0x1AFB0)
    ("t_rwk_stripframe", asm_rwk_stripframe), ("t_rwk_stripxfer", asm_rwk_stripxfer),
    # 2026-10-18 fix 9: the strip anchored on the left panel's right stroke (pinned 0x34F0)
    ("t_rwk_stripanchor", asm_rwk_stripanchor),
    # v4/v5 (2026-09-11)
    ("thunk_sprite_bilinear", asm_sprite_bilinear), ("t_rwk_face_blit", asm_rwk_face_blit),
    # v15 (2026-09-20): citizen-face hybrid (pinned 0x21A00)
    ("thunk_face_hybrid", asm_face_hybrid),
    # v8 (2026-09-12c); v13 (2026-09-13g): pinned at 0xA770, + the tile stash helper (takes blink's old region slot)
    ("t_rwk_blink", asm_rwk_blink), ("t_rwk_blinktile", asm_rwk_blinktile),
    # v16 (2026-09-26): intel PROFILE page (pinned 0x230B0..)
    ("t_rwk_intel_portrait", asm_rwk_intel_portrait), ("t_rwk_intel_title", asm_rwk_intel_title),
    ("t_rwk_intel_lbr_l", asm_rwk_intel_lbr_l), ("t_rwk_intel_lbr_r", asm_rwk_intel_lbr_r), ("t_rwk_intel_blocky", asm_rwk_intel_blocky),
    # slide-window outer rail row (report-wide; pinned 0x2020)
    ("t_slide_rail_a", asm_slide_rail_a), ("t_slide_rail_a2", asm_slide_rail_a2),
    ("t_slide_rail_s1", asm_slide_rail_s1), ("t_slide_rail_s2", asm_slide_rail_s2),
    # console list bar arrows for btn_gate_pre v7 (pinned 0x231C0)
    ("t_rw_sbarrows", asm_rw_sbarrows),
    # v17 (2026-10-11): the six other consoles' title inset + ListBox R/B inset (pinned 0x30300..)
    ("t_rwk_con_title_add", asm_rwk_con_title_add), ("t_rwk_con_title_mov", asm_rwk_con_title_mov), ("t_rwk_con_lbr", asm_rwk_con_lbr),
    # 2026-10-11: report-list text pad (pinned 0x28030)
    ("t_lb_textpad", asm_lb_textpad),
]


def add_sites(add, redirect, detour):
    """Append the group's sites through assemble_rw.site_list's helpers."""
    K = "rw_scale_kinds"
    redirect("ReportWin_on_lclick.blink_tile", K, "ReportWin_on_lclick", 0x4974B2, TILE_TO_PX_WIN, "t_rwk_blinktile", "v13: stash the clicked base's (tx,ty) in g_blink_tile for t_rwk_blink, then WorldWin_tile_to_pixel as before")
    detour("ReportWin_draw_projects.rowdiv", K, "ReportWin_draw_projects", 0x49EB6F, 12, "t_rwk_proj_rowdiv", "rows = vanilla (textB-top-5)/0x36 in native space from ceil(win_h*16/g) (magic-multiply /54 replaced; law rw_projects_visible_rows)")
    detour("ReportWin_draw_projects.rowy", K, "ReportWin_draw_projects", 0x49EE8F, 22, "t_rwk_proj_rowy", "row y = top + s(2) + s(56k) (x56 lea replaced; law rw_projects_row_y: cum(k), not k*(s(0x36)+s(2)))")
    detour("ReportWin_draw_units.rowdiv", K, "ReportWin_draw_units", 0x4A0974, 12, "t_rwk_units_rowdiv", "rows = vanilla (textB-top-2)/0x2B in native space from ceil(win_h*16/g) (magic-multiply /43 replaced; law rw_units_visible_rows)")
    detour("ReportWin_draw_units.rowstep", K, "ReportWin_draw_units", 0x4A0D3D, 10, "t_rwk_units_rowstep", "row rect top/bottom += cum(k) - cum(k-1) at pitch 0x2B (law rw_list_row_advance; was += s(0x2B))")
    detour("ReportWin_draw_bases.name_x", K, "ReportWin_draw_bases", 0x49E129, 5, "t_rwk_bases_namex", "name x += s(0x3C) (imm8 overflow at g=40)")
    detour("ReportWin_draw_intel.text_x", K, "ReportWin_draw_intel", 0x4A3407, 5, "t_rwk_intel_textx", "text x += s(0x7D) (imm8 overflow at g=40)")
    # v16 (2026-09-26): intel PROFILE page
    redirect("ReportWin_draw_intel.portrait", K, "ReportWin_draw_intel", 0x4A2415, BLIT_CORE, "t_rwk_intel_portrait", "leader portrait 131x157 x g/16 through thunk_art_draw (bilinear + parity re-blit + DLL Lanczos), portrait_avg gate = RW canvas for this call; was 1:1 at every g")
    detour("ReportIf_console_intel.title_inset", K, "ReportIf_console_intel", 0x4AC4BE, 5, "t_rwk_intel_title", "and eax,0x4C mask -> s(0x4C) (imm8 overflow; centre console title right of the logo)")
    detour("ReportIf_console_intel.lbr_l", K, "ReportIf_console_intel", 0x4AC2F9, 5, "t_rwk_intel_lbr_l", "left ListBox R/B inset -3 -> -s(3) (imm32 mov; table full)")
    detour("ReportIf_console_intel.lbr_r", K, "ReportIf_console_intel", 0x4AC767, 5, "t_rwk_intel_lbr_r", "right ListBox R/B inset -3 -> -s(3) (imm32 mov; table full)")
    # v17 (2026-10-11): the six other consoles (CALL helpers; one per displaced shape)
    for va, con in TITLE_ADD_SITES:
        add(f"{CONSOLE_FN[con]}.title_inset", K, CONSOLE_FN[con], va, SE.base_exe_bytes(va, 5), "E8 {rel32:t_rwk_con_title_add}", "instruction_to_thunk_call",
            "and eax,0x4C / add ecx,eax -> CALL: ecx += mask & s(0x4C) (imm8 overflow; centre console title right of the logo; law rw_console_title_inset)")
    for va, con in TITLE_MOV_SITES:
        add(f"{CONSOLE_FN[con]}.title_inset", K, CONSOLE_FN[con], va, SE.base_exe_bytes(va, 5), "E8 {rel32:t_rwk_con_title_mov}", "instruction_to_thunk_call",
            "and eax,0x4C / mov ecx,eax -> CALL: ecx = mask & s(0x4C) (imm8 overflow; law rw_console_title_inset)")
    for va, con, lst in LBR_SITES:
        add(f"{CONSOLE_FN[con]}.lbr_{lst}", K, CONSOLE_FN[con], va, SE.base_exe_bytes(va, 5), "E8 {rel32:t_rwk_con_lbr}", "instruction_to_thunk_call",
            "ListBox R/B inset mov eax,-3 -> CALL: eax = -s(3) (mirror of the +s(3) L/T rows; imm table full; law rw_console_listbox_rb)")
    detour("ReportWin_draw_intel.block_y", K, "ReportWin_draw_intel", 0x4A3046, 8, "t_rwk_intel_blocky", "POLITICS/treaty block top = max(flow y, portrait bottom + s(4)) (law intel_block_top; vanilla overlaps the portrait with <=9 rows)")
    detour("slide_show.outer_rail_row", K, "slide_show", 0x45D4AE, 40, "t_slide_rail_a", "outer rail strips start at screen row ScreenH - fl(530g/16) (vanilla 238 = 768-530), ceil-descaled for the railscale shim; was the native 238 vs a device window top -> the wide pillars began at the window top at 4K")
    detour("slide_hide.outer_rail_row", K, "slide_hide", 0x45DA07, 33, "t_slide_rail_a2", "the close animation's copy of the outer rail row (same law; else the pillars jump to the window top when the close slide starts)")
    detour("slide_show.outer_left_settled", K, "slide_show", 0x45D7FD, 17, "t_slide_rail_s1", "settled left outer strip: v = max(slide_y, A) - T ceil-descaled for the railscale shim (law slide_rail_settled_v)")
    detour("slide_show.outer_right_settled", K, "slide_show", 0x45D87A, 20, "t_slide_rail_s2", "settled right outer strip: v = max(slide_y, A) - T ceil-descaled for the railscale shim (law slide_rail_settled_v)")
    detour("ReportIf_activate.govsplit_w", K, "ReportIf_activate", 0x4A478D, 6, "t_rwk_gov_split1", "v2: GOVERNOR rect = t_rw_tabpair(left) (law rw_tab_pair), resume 0x4A47B0")
    detour("ReportIf_activate.govsplit_x", K, "ReportIf_activate", 0x4A484F, 8, "t_rwk_gov_split2", "v2: BEST BASES rect = t_rw_tabpair(right) (law rw_tab_pair), resume 0x4A486B")
    detour("ReportIf_console_ops.tabbox_w", K, "ReportIf_console_ops", 0x4A90DD, 9, "t_rwk_ops_w", "GOVERNOR|BEST BASES tab box + list box w = W - 2*s(6) (law rw_console_inset_w; was W - s(0xC))")
    detour("ReportIf_console_ops.list_x", K, "ReportIf_console_ops", 0x4A90A8, 6, "t_rwk_ops_lx", "BEST BASES list x = L + P (law rw_tab_inset: aligned with the toggles above)")
    detour("ReportIf_console_ops.list_w", K, "ReportIf_console_ops", 0x4A90BA, 8, "t_rwk_ops_lw", "BEST BASES list w = W - 2P (law rw_tab_inset)")
    detour("ReportIf_activate.govlist_cursor", K, "ReportIf_activate", 0x4A4F05, 26, "t_rwk_govlist", "governor list buttons x = L + P, y = T + s(0x23), w = W - 2P (aligned with the toggles; law rw_tab_inset)")
    detour("ReportIf_activate.sat_w", K, "ReportIf_activate", 0x4A4C42, 8, "t_rwk_sat_w", "F6 tabs w = clipW - 2*s(3) (law rw_sat_tabs / rw_console_inset_w; was clipW - s(6))")
    detour("ReportIf_activate.modes_w", K, "ReportIf_activate", 0x4A4927, 9, "t_rwk_modes_w", "F4 PRODUCTION|CITIZENS|GARRISON w = clipW - 2*s(3) (law rw_console_inset_w; was clipW - s(6))")
    detour("ReportIf_activate.satsplit_r", K, "ReportIf_activate", 0x4A4C9A, 9, "t_rwk_sat_split1", "SATELLITE SUMMARY R = L + (W - s(2)) >> 1")
    detour("ReportIf_activate.satsplit_l", K, "ReportIf_activate", 0x4A4D76, 9, "t_rwk_sat_split2", "ORBITAL ATTACK VIEW L = L + (W - s(2)) >> 1 + s(2)")
    detour("ReportWin_draw_sat.planet_cx", K, "ReportWin_draw_sat", 0x49FB00, 6, "t_rwk_sat_cx", "planet x = centre - s(flicW)/2")
    detour("ReportWin_draw_sat.planet_cy", K, "ReportWin_draw_sat", 0x49FB1B, 9, "t_rwk_sat_cy", "planet y = centre - s(flicH)/2 (Buffer_init keeps native h)")
    redirect("ReportWin_draw_bases.face_a", K, "ReportWin_draw_bases", 0x49E806, BLIT_CORE, "t_rwk_face_blit", "CITIZENS face: hybrid enlarge x g/16 (thunk_face_hybrid: bilinear photo + regenerated scanline background, full coverage), clamped to the canvas clip bottom")
    redirect("ReportWin_draw_bases.face_b", K, "ReportWin_draw_bases", 0x49E8CA, BLIT_CORE, "t_rwk_face_blit", "CITIZENS face: hybrid enlarge x g/16 (thunk_face_hybrid: bilinear photo + regenerated scanline background, full coverage), clamped to the canvas clip bottom")
    # v2: the six other face blits (the specialist sprite tables -- a Transcend rendered native at 4K/1600, user 2026-09-09)
    for i, va in enumerate((0x49E4D1, 0x49E56D, 0x49E604, 0x49E681, 0x49E745, 0x49E96D)):
        redirect(f"ReportWin_draw_bases.face_{'cdefgh'[i]}", K, "ReportWin_draw_bases", va, BLIT_CORE, "t_rwk_face_blit", "CITIZENS specialist face: hybrid enlarge x g/16 (thunk_face_hybrid: bilinear photo + regenerated scanline background, full coverage), clamped to the canvas clip bottom")
    # v2: BASE STATUS rows, chrome follows content (bases_row_cell / bases_face_y_imm; rows 0x49D591/0x49D622/0x49D62B/0x49D62E/0x49E3FA dropped)
    detour("ReportWin_draw_bases.cell", K, "ReportWin_draw_bases", 0x49D590, 5, "t_rwk_bases_cell", "cell = 2K + floor(38g/16) (row height AND icon-cell width)")
    detour("ReportWin_draw_bases.cell_x", K, "ReportWin_draw_bases", 0x49D620, 6, "t_rwk_bases_cellx", "x + cell")
    detour("ReportWin_draw_bases.cell_y", K, "ReportWin_draw_bases", 0x49D629, 6, "t_rwk_bases_celly", "y + cell; x + s(2)")
    detour("ReportWin_draw_bases.face_y", K, "ReportWin_draw_bases", 0x49E3F8, 9, "t_rwk_bases_facey", "face y = rowBottom - pitch/2 - (cell - pitch/2 - K) = rowTop + K")
    redirect("ReportWin_sat_frame.planet", K, "ReportWin_sat_frame", 0x49FF38, BUFFER_DRAW, "t_rwk_gdraw", "planet flic frame under SCALE g/16")
    for va, arm in BLINK_SITES:
        redirect(f"ReportIf_blink_step.stamp_{arm}", K, "ReportIf_blink_step", va, BLIT_CORE, "t_rwk_blink", "BASE LOCATOR ring stamp x g/16 (dot sprite, SCALE bracket + s(7)/s(5) recentre)")
    redirect("sat_expl_step.frame", K, "sat_expl_step", 0x4A020C, SPRITE_DRAW_TABLE, "t_rwk_gtable", "explosion frame under SCALE g/16")
    for painter, sites in BOX_SITES.items():
        for i, va in enumerate(sites):
            redirect(f"ReportWin_draw_{painter}.box{i}", K, f"ReportWin_draw_{painter}", va, BOX_SPRITE, "t_rwk_boxhalf", "K-stroke frame + device-density interior (g<=16 native inside the thunk)")
    # v3: the fourteen console-canvas frames with the C6/41 backdrop fill (banded through hud_boxframe's NN enlarge)
    detour("ReportIf_console_chrome.strip_anchor", K, "ReportIf_console_chrome", STRIP_ANCHOR_SITE, STRIP_ANCHOR_LEN, "t_rwk_stripanchor",
           "2026-10-18 fix 9: the strip draws (clip, da50, d5a0, d528) read g_rw_strip_rect = (left panel R - K, T, R, B) at g>16 (law rw_strip_anchor: the panel's right stroke is the strip's first K columns, d5a0 gap = the strip's T/B/R channel s(4)-K); ReportIf+0x40 untouched")
    for fn, sites in BOXFORCE_SITES.items():
        for i, (va, what) in enumerate(sites):
            if va == STRIP_FRAME_SITE:      # 2026-10-17: drawn left of its clip -> t_rwk_stripframe (law rw_strip_frame)
                redirect(f"{fn}.boxforce{i}", K, fn, va, BOX_SPRITE, "t_rwk_stripframe", f"{what}: t_rwk_boxforce with the clip widened to the frame + the hidden band restored (band map, K strokes, half-open)")
                continue
            redirect(f"{fn}.boxforce{i}", K, fn, va, BOX_SPRITE, "t_rwk_boxforce", f"{what}: native draw, then fe_pair_remap FORCE over the drawn rect (C6/41 tile -> P stripes)")
    for va, nm in SCROLL_SMALL_SITES:
        redirect(f"ReportIf_console.scroll_small.{nm.replace(' ', '_')}", K, "ReportIf_console", va, SCROLL_SMALL, "t_rw_scrollsmall", "console list bar width s(12) + panel slot")
    for va, nm in SCROLL_NORMAL_SITES:
        redirect(f"ReportIf_console.scroll_normal.{nm.replace(' ', '_')}", K, "ReportIf_console", va, SCROLL_NORMAL, "t_rw_scrollnormal", "inlist=0")
    for va, fn in SCROLL_SHOW_SITES:
        redirect(f"{fn}.scroll_show", K, fn, va, SCROLL_SHOW, "t_rwk_scrollshow", "save the window's right-border column once (before the bar draws)")
    for va, fn in SCROLL_HIDE_SITES:
        redirect(f"{fn}.scroll_hide", K, fn, va, SCROLL_HIDE, "t_rwk_scrollhide", "restore the right-border column after the gated slide-out")
    redirect("ReportIf_activate.railarm_show", K, "ReportIf_activate", 0x4A5CEE, SLIDE_SHOW, "thunk_popup_railshow", "arm the filedlg rail gate around slide_show(ReportWin)")
    redirect("ReportIf_activate.railarm_hide", K, "ReportIf_activate", 0x4A5DA8, SLIDE_HIDE, "thunk_popup_railhide", "arm the filedlg rail gate around slide_hide(ReportWin)")
    # 2026-10-11: report-list text pad (law rw_list_text_pad)
    add("ListBox_close.report_text_pad", K, "ListBox_close", LB_TEXTPAD_SITE, SE.base_exe_bytes(LB_TEXTPAD_SITE, 6), "E8 {rel32:t_lb_textpad} 90",
        "instruction_to_thunk_call", "mov edx,[0x6970E4] -> CALL: edx = s(3)-1 for the console lists (g_rw_inlist) and the energy list ReportWin+0x5A0C at g>16, else the static 2 (ListBox_draw_item text inset pad+1 per side)")
