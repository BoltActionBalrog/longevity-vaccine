#!/usr/bin/env python
"""Assembler for the DESIGN WORKSHOP (DesignWin 0x71F2B0 + stack PartPicker) BAKE (2026-08-29).

Ports the user-verified prototype hook_dw_scale_proto.js v15l ("perfect at all resolutions": 4K +
1920 + 1600, 2026-08-29) into pcave2 thunks.  Four groups (work/_dw_bake_plan.md):

  dw_scale                 the workshop itself (gated on g_popup_scale_num > 16; every thunk is a native
                           no-op at g<=16 -- the immediates are the identity there)
  wheel_scroll             mouse wheel = chevron scroll on every scrollable modal (UNGATED vanilla change)
  popup_listbox_reserve    the type-2 listbox popup scrollbar reserve + heap-bar regeneration (popup family)
  picker_grid_leave_present the picker's stale hover after the pointer leaves the grid (vanilla bug)

Laws: scaling_laws.scale_px / popup_scale_floor / stroke_width / stripe_top / line_axis_map /
distribute / dw_fit_plan / dw_button_rows / listbox_bar_reserve / bandmap_rect_from_halfopen /
nested_frame_pad / ornate_dialog_child_x.  Every thunk here is a PORT of the proto's JS; the parity
test tests/test_dw_asm_parity.py emulates these exact bytes (Unicorn) against the Python laws.

Thunks (CALL helper = entered by E8, consumes the return address; detour = entered by JMP):
  thunk_dw_enter      detour @DesignWin_exec 0x43E9A0 (5B prologue replay): immfix, then the SEH prologue.
  thunk_dw_immfix     CALL helper: one-time VirtualProtect(0x432000, 0xD000) via the kernel32 IAT, then the
                      113-entry imm table (kinds HD s(a)-s(b) / FLOOR / CEIL / VEH, optional NEGATE; byte or
                      dword store).  Identity at g=16 (vanilla restored on a resolution downgrade).
  thunk_dw_pk_enter   detour @PartPicker_exec 0x433F70 (ret-address swap -> thunk_dw_pk_leave): picker canvas
                      cell for the composite shim, thunk_rail_gate imm = the live picker (popup-family rail
                      recipe: sbfit/grip zoom/arrow stripes), g_popup_active++ (arrows 2D zoom).
  thunk_dw_pk_leave   the swapped return: undo the three, jmp to the caller.
  thunk_dw_cell       JMP-entered @0x433D84 (picker cell rect law: absolute native coords x g/16, HD).
  thunk_dw_click      PartPicker vtbl+0x44 on_click: x,y descaled 16/g then the native hit test.
  thunk_dw_frame      JMP-entered @0x434266: picker container R inset s(55) (imm8 overflow at g=40).
  thunk_dw_bm         call-redirect @0x434285 (picker container Buffer_box_sprite): rect COPY with R-1/B-1
                      (law bandmap_rect_from_halfopen) -> thunk_box_thick_hollow_flat.
  thunk_dw_pickcell   call-redirect @0x433E2C (picker cell frame): the bm copy, hollow_flat, then the cell
                      interior restriped (pair 196/65, inset K+2) -- the remap table does not know the pair.
  thunk_dw_tilecell   call-redirect @0x433DE9 (empty cell Buffer_tile_2): tile, then restripe 197/65 inset 0.
  thunk_dw_slotcell   call-redirect @0x43D755 (slot strip cell Buffer_box_sprite): draw, then restripe the
                      hover (d550: 194/65) / selected (d578: 191/83) fill at inset K+2 in the MainWin buffer.
  thunk_dw_restripe   CALL helper (buf, rect*, inset, top, mate): P-law restripe of a dither pair inside a rect.
  thunk_dw_btndraw    detour @0x404220 (the default vtbl+0x14 item-draw stub): DesignWin FlatButtons ->
                      thunk_se_rowdraw (the SE face restripe: pair per draw, ring pinned to K, key rows
                      overdrawn); its tail jumps back here -> a busy flag ends the pass.
  thunk_btn_gate_pre  v4 IN PLACE (0x16DA0): + DW HIT prefix [0x71FF9C, 0x731DB8) for thunk_btn_gate.
  thunk_dw_shim       call-redirect @0x6175F4 (Caviar_draw's composite Buffer_draw_2): dst == DW canvas ||
                      picker canvas && g>16: SSAA composite ([g_dw_ssaaw]) or keyed stretch (thunk_keyed_
                      stretch_blit, [g_dw_fitw]/[g_dw_fitoff]); [g_dw_fitw]==0 suppresses; else Buffer_draw_2.
  thunk_dw_fit        call-redirect at the 10 Caviar_draw sites (DW painters, picker cells, Caviar_overlay's
                      inner draw): gated draws TRIAL-render at native zoom (composite suppressed), read the
                      rasterizer bbox, plan (law dw_fit_plan: radial), render at zoom*k, composite at W.
  thunk_dw_ssaa       CALL helper: 2x2-ish box-filter composite of the target into dst with palette nearest
                      (candidates = the render's own indices, 4096-entry direct-mapped colour cache).
  thunk_dw_clip       call-redirect @0x6174CE (Caviar_rasterize): gated -> ctx clip = the whole target.
  thunk_dw_fpset      call-redirect @0x63EA1F / 0x63F0BC (run-table build): per-part footprint n x n from
                      the projected voxel axis steps (gated real draws), 2x2 otherwise; DEND/ZROW/DROW/SPAN.
  thunk_dw_fp / fp2   JMP-entered @0x6649B4 / 0x664C64: the 8-bit plotter's big-mode block, n x n (v14b).
  thunk_dw_ewin/eovl/ehalfa/ehalfb   JMP-entered Caviar sites whose disp8 cannot hold the 1024 target.
  thunk_dw_resetguard call-redirect @0x61760F (Caviar_draw tail Caviar_reset): dirty rect clamped to [0,TN].
  thunk_dw_ovl        call-redirect @0x6171F8 (Caviar_overlay's table blit): one-shot rescale armed by fit.
  thunk_dw_build      call-redirect @0x43E9DF (DesignWin_build): build, then the backdrop at device density.
  thunk_dw_backdrop   CALL helper (ecx = DesignWin): deswin.pcx re-rendered into the canvas + the pcx Buffer:
                      families/variants/strokes MEASURED from the plane, line-pinned axis maps
                      (line_axis_map), every vertical dither pair regenerated on the P-law stripe.
  thunk_dw_gridleave  call-redirect @0x433914: draw_cell(hover,0) then vtbl+0xFC present (vanilla bug).
  thunk_dw_sbv        call-helper @0x5EC42C (`mov ecx,[esi+0x43c]` after ScrollBar_init_v): under the popup
                      gate register the Win-layer heap ScrollBar in g_rail_sb (pref_sbzoom/btn_stripes arm).
  thunk_dw_hide       call-redirect @0x404A84 (Popup_hide's first call): clear g_rail_sb if it is this
                      popup's heap bar.
  thunk_lbres_ecx/eax/ebp/edx   call-helpers at the 14 g_scrollbar_w loads (law listbox_bar_reserve).
  thunk_wheel_down/up call-redirects @0x5F07B0 / 0x5F07F0 (WinProc WM_KEYDOWN/KEYUP `call Win_get_active_
                      target`): PRACX's synthetic VK_UP/DOWN (lParam 0) -> one chevron press on the modal's bar.
  thunk_popup_nestpads v2 / thunk_orn_childx v2   IN PLACE (laws nested_frame_pad / ornate_dialog_child_x).

Run:  py assemble_dw.py               -> prints the yaml fragments + checks
      py assemble_dw.py --fragments   -> writes work\\patches\\_fragment_dw_*.yaml
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
with contextlib.redirect_stdout(io.StringIO()):
    import assemble_se as SE  # noqa: E402  (assemble / templatize / base_exe_bytes / rel32 / HD / FL)
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x22000          # pcave2 grown 0x1A000 -> 0x22000 for this bake (big data cells)
TN = 1024                      # Caviar render target (option E)

# ---- engine anchors ----------------------------------------------------------
G            = 0x00668740   # g_popup_scale_num
G_OBJ        = 0x0071F2B0   # DesignWin (static)
DW_CANVAS    = G_OBJ + 0x444
DW_PCX       = G_OBJ + 0x13C6C
DW_LO, DW_HI = G_OBJ + 0xCEC, G_OBJ + 0xCEC + 0x19 * 0xB4C   # the 25 DesignWin FlatButtons
EXEC         = 0x0043E9A0   # DesignWin_exec (thiscall RET 8; 6 callers -> prologue detour)
EXEC_RESUME  = 0x0043E9A5
BUILD        = 0x0043C270   # DesignWin_build (thiscall)
BUILD_SITE   = 0x0043E9DF
PK_EXEC      = 0x00433F70   # PartPicker_exec (4 callers -> prologue detour + ret swap)
PK_RESUME    = 0x00433F75
PK_ONCLICK   = 0x00433820
PK_VTBL_CLICK = 0x0066B2FC
PK_DRAWCELL  = 0x00433D60
GRIDLEAVE_SITE = 0x00433914
CELL_SITE, CELL_RESUME = 0x00433D84, 0x00433DC6
FRAME_SITE, FRAME_RESUME = 0x00434266, 0x0043426B
BM_SITE, PICKCELL_SITE, TILE_SITE, SLOTCELL_SITE = 0x00434285, 0x00433E2C, 0x00433DE9, 0x0043D755
UNION_SITE   = 0x00437B89
BOX_SPRITE   = 0x005E2DD3
BUFFER_TILE_2 = 0x005DA9F0
HOLLOWFLAT   = PCAVE2 + 0x140     # thunk_box_thick_hollow_flat
RAILSHOW, RAILHIDE = PCAVE2 + 0x3550, PCAVE2 + 0x44D0
SLIDESHOW, SLIDEHIDE = 0x0045D440, 0x0045D970
RAIL_SITES   = ((0x0043D1BE, SLIDESHOW, "thunk_popup_railshow"), (0x0043D1FA, SLIDEHIDE, "thunk_popup_railhide"))
PRODPICKER   = 0x006A8044


def _rail_gate_picker_imm() -> int:
    """VA of the ProdPicker comparand (`3D imm32` cmp eax, ProdPicker) in the LIVE rail-gate body.

    Tied to thunk_rail_gate4 itself (RAIL_GATE4_OFF), never to the old gate's slot: rail_gate v4 (2026-09-26p)
    moved the body to thunk_rail_gate4 and left a push/ret trampoline at 0x11200, so the old
    `thunk_rail_gate+5` became the trampoline's `ret` -- the picker bracket overwrote it and every DW part
    picker crashed at g>16 (AV at pcave2+0x11207, 2026-09-27).

    2026-10-18 (fix 12, N5): NO assembly at import.  This module is imported (via assemble_rw) by every rw / DW
    test module at COLLECTION, so an import-time keystone run here was a single point whose one transient failure
    (seen once under two overlapping `-n 24` runs: "exactly one `cmp eax, ProdPicker`") aborted the whole xdist
    run ("Different tests were collected").  The comparand is gate4's first `cmp eax, imm32` after
    `push eax` (1) / `mov eax, [ebp+8]` (3) / opcode 3D (1); tests/test_dw_asm_parity.py
    test_pk_bracket_targets_the_live_rail_gate_comparand assembles + disassembles the live body and pins it."""
    with contextlib.redirect_stdout(io.StringIO()):
        import assemble_rail_scrollbar as RS
    assert RS.PICKER == PRODPICKER
    return RS.PCAVE2 + RS.RAIL_GATE4_OFF + 5


RAIL_GATE_IMM = _rail_gate_picker_imm()   # thunk_rail_gate4 + 5 (pcave2+0x6A65)
G_POPUP_ACTIVE = PCAVE2 + 0x530
G_RW_INLIST = PCAVE2 + 0x27488      # assemble_rw CELL g_rw_inlist: 1 between t_rw_scrollsmall and t_rw_scrollnormal = an HQ-report console list is being attached (its bar width is already s(12) at the WRITER)
G_RAIL_SB    = PCAVE2 + 0x11260
SB_VTBL      = 0x00669D58
T_LIST_GATE  = PCAVE2 + 0x6AC0     # thunk_list_gate (assemble_rail_scrollbar.py): ZF=0 iff g_popup_active || g_filedlg_active (2026-09-26q)
T_FD_WHEELBAR = PCAVE2 + 0x6AD8    # thunk_fd_wheelbar (assemble_rail_scrollbar.py): edi = the FileDlg's live list bar (2026-09-26q)
SE_ROWDRAW   = PCAVE2 + 0x16950   # thunk_se_rowdraw: its TAIL jumps to SocialWin_draw_society_row (draws SE's slider sprites) -> NEVER reuse it
SE_HELPERS   = {"thunk_se_stripe_top": PCAVE2 + 0x15D40, "thunk_se_stripe_px": PCAVE2 + 0x16940,
                "thunk_se_rr_row": PCAVE2 + 0x168A0, "thunk_se_rr_col": PCAVE2 + 0x168F0,
                "thunk_se_stripe_px_ph": PCAVE2 + 0x2FFE0}   # pure CALL helpers on the rowdraw frame
T_DW_FACE_PH = PCAVE2 + 0x2F5C0   # t_dw_face_ph (assemble_list_face_phase.py): g_se_yph = the face's parent-local top mod P, then jmp thunk_dw_btnface
ITEMDRAW_STUB = 0x00404220
BTN_GATE     = PCAVE2 + 0xA9E0
BTN_GATE_PRE_OFF = 0x16DA0
SE_LO, SE_HI = 0x8AC290, 0x8C4DF4
ITEMDRAW_RESUME = ITEMDRAW_STUB + 5
KSB          = 0x00668670   # thunk_keyed_stretch_blit trampoline (frozen)
BUFFER_DRAW_2 = 0x005D84C0
COMPOSITE_SITE = 0x006175F4
CAVIAR_DRAW  = 0x00617230
CAVIAR_RESET = 0x00618470
CAVIAR_RASTERIZE = 0x00639E60
RASTER_SITE  = 0x006174CE
RESET_TAIL_SITE = 0x0061760F
RUNTAB       = 0x006404F0
RUNTAB_SITES = (0x0063EA1F, 0x0063F0BC)
BUFFER_FILL_2 = 0x005DFB50
CV_TARGET    = 0x009B9108
CV_CTX       = 0x009BB478
CV_MINX      = 0x009B9690
CV_MTX       = 0x009C0A40
CV_DATA_BASE, CV_Z_BASE, CV_PITCH, CV_ZPITCH = 0x009BE6A8, 0x009BE6A4, 0x009BE6B0, 0x009BE6B4
CV_SHADE_TBL = 0x009BE6BC
PALETTE      = 0x0094C590
KEY          = 9
OVL_SITE, OVL_TARGET = 0x006171F8, 0x005D94B0
FP_SITE, FP_RESUME = 0x006649B4, 0x00664A29
FP2_SITE, FP2_RESUME = 0x00664C64, 0x00664CC6
FIT_SITES    = (0x00434D4D, 0x0043516D, 0x004355DA, 0x00435A3D, 0x004362FD,        # DesignWin painters
                0x00432ADF, 0x00432F55, 0x0043332A, 0x0043365C,                     # PartPicker cells
                0x006171CF)                                                         # Caviar_overlay inner draw
SBV_SITE     = 0x005EC42C
HIDE_SITE, HIDE_TARGET = 0x00404A84, 0x005F7E90
GET_TARGET, CHEVRON, MODAL_TOP, BASEPOP = 0x005F6A50, 0x00606B20, 0x009B7AE0, 0x009B8D7C
WHEEL_DOWN_SITE, WHEEL_UP_SITE = 0x005F07B0, 0x005F07F0
G_SBW        = 0x009B8DD4   # g_scrollbar_w (SHARED runtime global: read live, never baked)
IAT_LOADLIB, IAT_GETPROC = 0x00669120, 0x00669124
STR_K32, STR_VP = 0x00A1C6C0, 0x00A1C6D0
VP_PAGE, VP_LEN, PAGE_RWX = 0x00432000, 0xD000, 0x40
BUFFER_RESIZE = 0x005D79C0

# ---- allocations --------------------------------------------------------------
OFF_CODE   = 0x177C0                     # tail after the tech block (0x177B0)
OFF_CELLS  = 0x1A000                     # small cells
OFF_SNAP   = 0x1A100                     # 0x100 Caviar header snapshot
OFF_IMMTAB = 0x1A200                     # 113 x 16 + 4 = 1812
OFF_CANDS  = 0x1AA00                     # 256 x 4
OFF_PRESENT = 0x1AE00                    # 256
OFF_BD     = 0x1B000                     # backdrop census: cnt/vrun/cntE/cntS (4 x 1024) + FAM/VAR (2 x 256) + lrow 512 + lcol 1024
OFF_CACHE  = 0x1D000                     # 4096 x 4 colour cache (after the census 0x1B000..0x1C800)
OFF_BIG_END = 0x21000
# cells (name, offset, size)
CELLS = [
    ("g_dw_vpdone", OFF_CELLS + 0x00, 4), ("g_dw_vpold", OFF_CELLS + 0x04, 4),
    ("g_dw_fitw", OFF_CELLS + 0x08, 4), ("g_dw_fitoff", OFF_CELLS + 0x0C, 4), ("g_dw_pickcanvas", OFF_CELLS + 0x10, 4),
    ("g_dw_ssaaw", OFF_CELLS + 0x14, 4), ("g_dw_gated", OFF_CELLS + 0x18, 4), ("g_dw_fpgated", OFF_CELLS + 0x1C, 4),
    ("g_dw_ovl", OFF_CELLS + 0x20, 16),                       # +0 ON +4 OFF +8 NUM +12 DEN
    ("g_dw_fp", OFF_CELLS + 0x30, 48),                        # +0 SAVE_ECX +4 N +8 ROWS +12 ZROW +16 DROW +20 SPAN +24 DEND +28 IDX +32 NY
    ("g_dw_pk_ret", OFF_CELLS + 0x60, 4), ("g_dw_pk_armed", OFF_CELLS + 0x64, 4),
    ("g_dw_ret1", OFF_CELLS + 0x68, 4), ("g_dw_ret2", OFF_CELLS + 0x6C, 4), ("g_dw_ret3", OFF_CELLS + 0x70, 4), ("g_dw_ret4", OFF_CELLS + 0x74, 4),
    ("g_dw_active", OFF_CELLS + 0x78, 4), ("g_dw_exec_ret", OFF_CELLS + 0x7C, 4),
    ("g_dw_bmrect", OFF_CELLS + 0x80, 16), ("g_dw_rect2", OFF_CELLS + 0x90, 16),
    ("g_dw_busy", OFF_CELLS + 0xA0, 4), ("g_dw_cv", OFF_CELLS + 0xA4, 4), ("g_dw_zoom", OFF_CELLS + 0xA8, 4), ("g_dw_ecx", OFF_CELLS + 0xAC, 4),
    ("g_dw_ss", OFF_CELLS + 0xB0, 0x50),                      # ssaa frame (see asm_dw_ssaa)
    ("g_dw_snap", OFF_SNAP, 0x100),
    ("g_dw_cands", OFF_CANDS, 0x400), ("g_dw_present", OFF_PRESENT, 0x100),
    ("g_dw_bd", OFF_BD, 0x1000 + 0x200 + 0x200 + 0x400),      # cnt 0x400, vrun 0x400, cntE 0x400, cntS 0x400, FAM 0x100, VAR 0x100, lrow 0x200, lcol 0x400
    ("g_dw_cache", OFF_CACHE, 0x4000),
]
CELL = {n: PCAVE2 + o for n, o, _ in CELLS}
G_IMMTAB = PCAVE2 + OFF_IMMTAB
FPC = {k: CELL["g_dw_fp"] + o for k, o in (("SAVE_ECX", 0), ("N", 4), ("ROWS", 8), ("ZROW", 12), ("DROW", 16), ("SPAN", 20), ("DEND", 24), ("IDX", 28), ("NY", 32))}
OVL = {k: CELL["g_dw_ovl"] + o for k, o in (("ON", 0), ("OFF", 4), ("NUM", 8), ("DEN", 12))}
BD = {k: CELL["g_dw_bd"] + o for k, o in (("cnt", 0), ("vrun", 0x400), ("cntE", 0x800), ("cntS", 0xC00), ("FAM", 0x1000), ("VAR", 0x1100), ("lrow", 0x1200), ("lcol", 0x1400))}

# ---- the immediate table -------------------------------------------------------
KIND_DWORD, KIND_FLOOR, KIND_CEIL, KIND_VEH, KIND_NEG = 1, 4, 8, 0x10, 0x20
HD_, FL_, CE_, VE_ = 0, KIND_FLOOR, KIND_CEIL, KIND_VEH
# (site, immOff, width, kind, a, b, label) -- transcribed from the proto's P table (hook_dw_scale_proto.js).
# HD: s(a)-s(b) (NEG(a) == HD(0,a)); FLOOR: fl(a*g/16); CEIL: ceil(a*g/16); VEH: min(48, fl((a+16)g/16)-16).
IMMS = [
    # builder 0x43C270: fonts + leadings
    (0x43C2B7, 1, 1, HD_, 10, 0, "F0 size"), (0x43C2D2, 2, 4, HD_, 3, 0, "F0 leading"),
    (0x43C2E6, 1, 1, HD_, 12, 0, "F1 size"), (0x43C2F0, 2, 4, HD_, 5, 0, "F1 leading"),
    (0x43C304, 1, 1, HD_, 16, 0, "F2 size"), (0x43C30E, 2, 4, HD_, 4, 0, "F2 leading"),
    # builder: part boxes + preview literals
    (0x43C314, 1, 4, HD_, 0x1E, 0, "box L"), (0x43C319, 1, 4, HD_, 7, 0, "box T"), (0x43C31E, 1, 4, HD_, 0x81, 0, "box R"),
    (0x43C323, 6, 4, HD_, 0x8C, 0, "preview L"), (0x43C32D, 6, 4, HD_, 9, 0, "preview T"), (0x43C337, 6, 4, HD_, 0x1C3, 0, "preview R"),
    (0x43C341, 6, 4, HD_, 0x140, 0, "preview B"),
    (0x43C35D, 6, 4, HD_, 0x5C, 0, "box0 B"), (0x43C36D, 6, 4, HD_, 0x65, 0, "box1 T"), (0x43C37D, 6, 4, HD_, 0xBA, 0, "box1 B"),
    (0x43C393, 1, 4, HD_, 0x118, 0, "box2/5 B"), (0x43C398, 1, 4, HD_, 0x1CE, 0, "box R-col L"), (0x43C39D, 1, 4, HD_, 0x231, 0, "box R-col R"),
    (0x43C3A2, 6, 4, HD_, 0xC3, 0, "box2 T"), (0x43C3C4, 6, 4, HD_, 0x5C, 0, "box3 B"), (0x43C3D4, 6, 4, HD_, 0x65, 0, "box4 T"),
    (0x43C3E4, 6, 4, HD_, 0xBA, 0, "box4 B"), (0x43C3FC, 6, 4, HD_, 0xC3, 0, "box5 T"),
    # builder: console overlay insets
    (0x43C44E, 2, 1, HD_, 4, 0, "slotStrip L+4"),
    (0x43C495, 2, 1, HD_, 3, 0, "flash L+3"), (0x43C49A, 1, 4, HD_, 0, 3, "flash R/B-3"), (0x43C4A1, 2, 1, HD_, 3, 0, "flash T+3"),
    (0x43C4E5, 2, 1, HD_, 4, 0, "title L+4"), (0x43C4EA, 1, 4, HD_, 0, 4, "title R/B-4"), (0x43C4F1, 2, 1, HD_, 4, 0, "title T+4"),
    (0x43C51C, 2, 1, HD_, 4, 0, "rcont L+4"), (0x43C51F, 2, 1, HD_, 4, 0, "rcont T+4"), (0x43C522, 2, 1, HD_, 4, 0, "rcont R-4"), (0x43C527, 2, 1, HD_, 4, 0, "rcont B-4"),
    (0x43C52A, 2, 1, HD_, 7, 4, "presets L+3"), (0x43C530, 2, 1, HD_, 7, 4, "presets T+3"), (0x43C536, 2, 1, HD_, 7, 4, "presets R-3"), (0x43C542, 2, 1, HD_, 7, 4, "presets B-3"),
    (0x43C556, 2, 1, HD_, 0x15, 0, "presets title h"), (0x43C56F, 2, 1, HD_, 0x18, 0x15, "presets area T+3"),
    # builder: preset buttons + arrows
    (0x43C770, 2, 1, HD_, 3, 0, "preset w +3"), (0x43C78E, 2, 1, HD_, 3, 0, "preset w -3"), (0x43C7BA, 1, 1, HD_, 0x15, 0, "preset h"),
    (0x43C824, 2, 1, HD_, 0x17, 0, "preset pitch"), (0x43C841, 3, 1, HD_, 3, 0, "preset col +3"), (0x43C879, 2, 1, HD_, 8, 0, "left arrow +8"),
    # builder: modal button rows (law dw_button_rows)
    (0x43C8D3, 2, 1, HD_, 0x1B, 0, "btn x0"), (0x43C8DF, 2, 1, HD_, 0x20, 0, "btn R -0x20"), (0x43C8E2, 2, 1, HD_, 0x1B, 0, "btn R -0x1B"),
    (0x43C8EA, 2, 1, HD_, 0x14, 0, "btn B -0x14"), (0x43C8ED, 2, 1, HD_, 3, 0, "btn cell +3"), (0x43C900, 2, 1, FL_ | KIND_NEG, 0x14, 0, "btn h (floor, negated)"),
    (0x43C911, 3, 1, HD_, 0, 3, "btn cell -3"), (0x43C927, 2, 1, HD_, 3, 0, "btn pitch +3"), (0x43C972, 2, 1, HD_, 0, 6, "upper row -6"),
    (0x43C9B2, 2, 1, HD_, 3, 0, "PROTO pitch +3"), (0x43CA27, 2, 1, HD_, 3, 0, "RETIRE ALL pitch -3"),
    # builder: window
    (0x43C6A3, 1, 4, HD_, 600, 0, "window h"), (0x43C6CA, 1, 4, CE_, 623, 0, "window w (MOV ecx,imm rewrite)"), (0x43C70F, 2, 1, HD_, 0x20, 0, "window x nudge"),
    # painters: title box / master / part boxes / abil
    (0x434708, 1, 1, HD_, 18, 0, "title font"), (0x434732, 1, 4, HD_, 3, 0, "title inset"),
    (0x437A26, 1, 4, HD_, 3, 0, "master presets-title inset"), (0x437B65, 1, 4, HD_, 3, 0, "master union-frame inset"),
    (0x434CC5, 1, 4, HD_, 0, 5, "chassis icon -5"), (0x435066, 1, 4, HD_, 0, 5, "weapon icon -5"), (0x435508, 1, 4, HD_, 0, 5, "armor icon -5"), (0x4359A8, 1, 4, HD_, 0, 5, "reactor icon -5"),
    (0x434E72, 2, 1, HD_, 3, 0, "chassis stats +3"), (0x43528E, 2, 1, HD_, 3, 0, "weapon stats +3"), (0x43570A, 2, 1, HD_, 3, 0, "armor stats +3"),
    (0x435BAF, 2, 1, HD_, 2, 0, "abil1 title y+2"), (0x435BC0, 1, 4, HD_, 5, 0, "abil1 title x+-5"), (0x435E5F, 2, 1, HD_, 2, 0, "abil2 title y+2"), (0x435E70, 1, 4, HD_, 5, 0, "abil2 title x+-5"),
    # painters: preview
    (0x43621C, 1, 4, HD_, 0xBB, 0, "preview veh x"), (0x436246, 1, 4, HD_, 0x8C, 0, "preview veh y"), (0x436274, 1, 1, VE_, 14, 0, "preview veh size"),
    (0x4363EC, 1, 4, HD_, 0x2D, 0, "preview name inset"), (0x437268, 2, 1, HD_, 0x14, 0, "DATA x"),
    # painters: slot strip (D7/D7')
    (0x43D5B3, 2, 1, HD_, 3, 0, "slot R-3"), (0x43D5B6, 2, 1, HD_, 3, 0, "slot L+3"), (0x43D5C2, 2, 1, HD_, 3, 0, "slot B-3"), (0x43D5CD, 2, 1, HD_, 2, 0, "slot cellW +2"),
    (0x43D5E0, 2, 1, HD_, 3, 0, "slot T+3"), (0x43D5F4, 1, 1, HD_, 10, 0, "slot font"), (0x43D739, 1, 4, HD_, 2, 0, "slot inset (hover/normal)"),
    (0x43D726, 1, 1, HD_, 2, 0, "slot selected inset (push imm8 rewrite)"),
    (0x43D8E1, 2, 1, HD_, 12, 0, "slot icon y"), (0x43D8EA, 2, 1, HD_, 15, 0, "slot icon x"), (0x43DAEF, 2, 1, HD_, 3, 0, "slot name x+3"), (0x43DAF2, 2, 1, HD_, 3, 0, "slot name r-3"),
    (0x43DCBE, 2, 1, HD_, 2, 0, "slot pitch +2 (unit)"), (0x43DCCC, 1, 4, HD_, 2, 0, "slot restore 2 (unit)"),
    (0x43D880, 2, 1, HD_, 2, 0, "slot pitch +2 (empty)"), (0x43D890, 1, 4, HD_, 2, 0, "slot restore 2 (empty)"), (0x43D5EB, 3, 1, HD_, 0, 2, "slot cellW -2"),
    # painters: draw_flash
    (0x43DE9A, 1, 4, HD_, 3, 0, "flash inset a"), (0x43DED2, 1, 4, HD_, 3, 0, "flash inset b"), (0x43DF55, 1, 1, HD_, 12, 0, "flash font"), (0x43DF68, 1, 1, HD_, 12, 0, "flash font b"),
    (0x43DF87, 2, 1, HD_, 3, 0, "flash half +3"), (0x43DF95, 3, 1, HD_, 0, 3, "flash half -3"), (0x43DFD4, 2, 1, HD_, 0, 0x25, "flash veh y"), (0x43DFDD, 2, 1, HD_, 0, 0x32, "flash veh x"),
    (0x43E001, 2, 1, HD_, 3, 0, "flash text +3 a"), (0x43E014, 2, 1, HD_, 3, 0, "flash text +3 b"), (0x43E10B, 1, 4, HD_, 2, 0, "flash name +2"), (0x43E279, 2, 1, HD_, 3, 0, "flash stats +3"),
    # part picker
    (0x43406F, 1, 1, HD_, 10, 0, "picker font 10"), (0x434081, 1, 1, HD_, 12, 0, "picker font 12 bold"),
    (0x433E37, 1, 4, HD_, 3, 0, "picker cell inset"), (0x434271, 3, 4, HD_, 0x17, 0, "picker frame L"),
]
assert len(IMMS) == 114   # 113 proto add() sites + the D7' push-imm8 rewrite
STATIC_REWRITES = {0x43C6CA, 0x43D726}   # the .bak holds a different instruction there (checked as sites)


def imm_value(site: int, off: int, g: int) -> int:
    """Oracle: the value the table writes at site+off for g (the proto's S/NEG/FLOORH/CEILW/VEH)."""
    for s, o, w, kind, a, b, _ in IMMS:
        if s == site and o == off:
            base = kind & ~(KIND_DWORD | KIND_NEG)
            if base == KIND_FLOOR:
                v = SL.popup_scale_floor(a, g)
            elif base == KIND_CEIL:
                v = -((-a * g) // 16)
            elif base == KIND_VEH:
                v = min(48, ((a + 16) * g >> 4) - 16)
            else:
                v = SL.scale_px(a, g) - SL.scale_px(b, g)
            return -v if kind & KIND_NEG else v
    raise KeyError(hex(site))


def immtab_entries() -> list[tuple[int, int, int, int]]:
    rows = []
    for s, o, w, kind, a, b, _ in IMMS:
        rows.append((s + o, a, b, kind | (KIND_DWORD if w == 4 else 0)))
    return rows


def immtab_bytes() -> bytes:
    out = bytearray()
    for site, a, b, kind in immtab_entries():
        out += struct.pack("<IiiI", site, a, b, kind & 0xFFFFFFFF)
    out += b"\x00\x00\x00\x00"
    return bytes(out)


HD, FL = SE.HD, SE.FL


# ==== dw_scale: exec entry + immfix ================================================
def asm_dw_enter() -> str:
    # 5-byte prologue replay (push ebp / mov ebp,esp / push -1); eax + flags are dead (mov eax,fs:[0] follows).
    # Ret-address swap -> thunk_dw_leave: g_dw_active brackets the modal (the button HIT prefix and the face
    # detour must be EXEC-scoped: DesignWin_build also runs at game init/load via 0x58EEB7 and the
    # MainWin-parented preset buttons draw then with no art assigned -> the zoom face compose AV'd in
    # Buffer_load_pcx(-1); the proto armed the range only inside exec).
    return f"""
    pop     eax
    mov     dword ptr [{CELL['g_dw_exec_ret']:#x}], eax
    push    thunk_dw_leave
    push    ecx
    push    edx
    call    thunk_dw_immfix
    pop     edx
    pop     ecx
    mov     dword ptr [{CELL['g_dw_active']:#x}], 1
    push    ebp
    mov     ebp, esp
    push    -1
    jmp     {EXEC_RESUME:#x}
"""


def asm_dw_leave() -> str:
    # after DesignWin_exec's `ret 8`: eax = result (kept); ecx/edx dead
    return f"""
    mov     dword ptr [{CELL['g_dw_active']:#x}], 0
    jmp     dword ptr [{CELL['g_dw_exec_ret']:#x}]
"""


def asm_dw_immfix() -> str:
    VPDONE, VPOLD = CELL["g_dw_vpdone"], CELL["g_dw_vpold"]
    return f"""
    push    esi
    cmp     dword ptr [{VPDONE:#x}], 0
    jne     imms
    push    {STR_K32:#x}
    call    dword ptr [{IAT_LOADLIB:#x}]
    test    eax, eax
    je      bail
    push    {STR_VP:#x}
    push    eax
    call    dword ptr [{IAT_GETPROC:#x}]
    test    eax, eax
    je      bail
    push    {VPOLD:#x}
    push    {PAGE_RWX:#x}
    push    {VP_LEN:#x}
    push    {VP_PAGE:#x}
    call    eax
    test    eax, eax
    je      bail
    mov     dword ptr [{VPDONE:#x}], 1
imms:
    cmp     dword ptr [{VPDONE:#x}], 0
    je      bail
    mov     esi, {G_IMMTAB:#x}
nexte:
    mov     eax, dword ptr [esi]
    test    eax, eax
    je      bail
    mov     edx, dword ptr [esi+12]
    test    edx, {KIND_FLOOR}
    jne     kfloor
    test    edx, {KIND_CEIL}
    jne     kceil
    test    edx, {KIND_VEH}
    jne     kveh
    mov     ecx, dword ptr [esi+4]
    {HD("ecx")}
    mov     edx, dword ptr [esi+8]
    {HD("edx")}
    sub     ecx, edx
    jmp     negate
kfloor:
    mov     ecx, dword ptr [esi+4]
    {FL("ecx")}
    jmp     negate
kceil:
    mov     ecx, dword ptr [esi+4]
    imul    ecx, dword ptr [{G:#x}]
    add     ecx, 15
    sar     ecx, 4
    jmp     negate
kveh:
    mov     ecx, dword ptr [esi+4]
    add     ecx, 16
    {FL("ecx")}
    sub     ecx, 16
    cmp     ecx, 48
    jle     negate
    mov     ecx, 48
negate:
    test    dword ptr [esi+12], {KIND_NEG}
    je      store
    neg     ecx
store:
    mov     eax, dword ptr [esi]
    test    dword ptr [esi+12], {KIND_DWORD}
    jne     wr4
    mov     byte ptr [eax], cl
    jmp     adv
wr4:
    mov     dword ptr [eax], ecx
adv:
    add     esi, 16
    jmp     nexte
bail:
    pop     esi
    ret
"""


# ==== dw_scale: picker bracket + stubs ==============================================
def asm_dw_pk_enter() -> str:
    # entry: [esp] = caller ret; eax/flags dead (SEH prologue reloads eax); ecx = this (kept)
    return f"""
    pop     eax
    mov     dword ptr [{CELL['g_dw_pk_ret']:#x}], eax
    push    thunk_dw_pk_leave
    cmp     dword ptr [{G:#x}], 16
    jle     pro
    lea     eax, [ecx+0x444]
    mov     dword ptr [{CELL['g_dw_pickcanvas']:#x}], eax
    mov     dword ptr [{RAIL_GATE_IMM:#x}], ecx
    inc     dword ptr [{G_POPUP_ACTIVE:#x}]
    mov     dword ptr [{CELL['g_dw_pk_armed']:#x}], 1
pro:
    push    ebp
    mov     ebp, esp
    push    -1
    jmp     {PK_RESUME:#x}
"""


def asm_dw_pk_leave() -> str:
    # after PartPicker_exec's `ret N`: eax = result (kept); ecx/edx dead
    return f"""
    cmp     dword ptr [{CELL['g_dw_pk_armed']:#x}], 0
    je      xout
    mov     dword ptr [{CELL['g_dw_pk_armed']:#x}], 0
    mov     dword ptr [{CELL['g_dw_pickcanvas']:#x}], 0
    mov     dword ptr [{RAIL_GATE_IMM:#x}], {PRODPICKER:#x}
    mov     ecx, dword ptr [{G_POPUP_ACTIVE:#x}]
    dec     ecx
    jns     stp
    xor     ecx, ecx
stp:
    mov     dword ptr [{G_POPUP_ACTIVE:#x}], ecx
xout:
    jmp     dword ptr [{CELL['g_dw_pk_ret']:#x}]
"""


def asm_dw_cell() -> str:
    # JMP-entered @0x433D84 (replaces `mov ecx,[esi+0x2b6c]` 6B); at g<=16 the vanilla arithmetic resumes @0x433D8A.
    # Law: x0=s(col*108+27) x1=s(col*108+132) y0=s(row*94+4) y1=s(row*94+95) (absolute native coords, no accumulation).
    return f"""
    mov     ecx, dword ptr [esi+0x2b6c]
    cmp     dword ptr [{G:#x}], 16
    jle     native
    mov     edi, ebx
    sub     edi, eax
    mov     eax, edi
    cdq
    idiv    ecx
    imul    eax, eax, 94
    imul    edx, edx, 108
    lea     ecx, [eax+4]
    lea     edi, [eax+95]
    lea     eax, [edx+132]
    add     edx, 27
    push    esi
    mov     esi, dword ptr [{G:#x}]
    imul    ecx, esi
    add     ecx, ecx
    add     ecx, 15
    shr     ecx, 5
    imul    edi, esi
    add     edi, edi
    add     edi, 15
    shr     edi, 5
    imul    eax, esi
    add     eax, eax
    add     eax, 15
    shr     eax, 5
    imul    edx, esi
    add     edx, edx
    add     edx, 15
    shr     edx, 5
    pop     esi
    mov     dword ptr [ebp-0xc], ecx
    mov     dword ptr [ebp-4], edi
    jmp     {CELL_RESUME:#x}
native:
    jmp     {CELL_SITE + 6:#x}
"""


PK_HIT_FRAME = 0x17   # VANILLA BUG: on_click's hit grid is (x-4)/108 while the cells are drawn at col*108+27 (+0x17 frame)


def asm_dw_click() -> str:
    # PartPicker vtbl+0x44: x,y descaled CEIL(v*16/g) (g>16; the inverse of the half-down cell law, law
    # floor_descale_roundtrip: a truncating descale lands a cell's first device px one native px short and the
    # engine's x<4 guard drops it), then x -= 0x17 at EVERY g: vanilla's hit test uses
    # col = (x-4)/108 while draw_cell places the cells at x = col*108+27 (the frame-left inset 0x17), so the
    # right ~20% of each cell selected its neighbour (base-game bug; same class as the ProdPicker edge fix).
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 16
    jle     go
    push    edx
    mov     eax, dword ptr [esp+8]
    shl     eax, 4
    add     eax, dword ptr [{G:#x}]
    dec     eax
    cdq
    idiv    dword ptr [{G:#x}]
    mov     dword ptr [esp+8], eax
    mov     eax, dword ptr [esp+0xc]
    shl     eax, 4
    add     eax, dword ptr [{G:#x}]
    dec     eax
    cdq
    idiv    dword ptr [{G:#x}]
    mov     dword ptr [esp+0xc], eax
    pop     edx
go:
    sub     dword ptr [esp+4], {PK_HIT_FRAME}
    jmp     {PK_ONCLICK:#x}
"""


def asm_dw_frame() -> str:
    # JMP-entered @0x434266 (`add edi,-0x37; push ecx; push edx` 5B); eax is dead here (GraphicWin_clear's result unused)
    return f"""
    mov     eax, 0x37
    {HD("eax")}
    sub     edi, eax
    push    ecx
    push    edx
    jmp     {FRAME_RESUME:#x}
"""


def _bm_copy(dst: int) -> str:
    """rect COPY with R-1/B-1 into the cell at dst, [esp+4] repointed at it (law bandmap_rect_from_halfopen)."""
    return f"""
    mov     eax, dword ptr [esp+4]
    mov     edx, dword ptr [eax]
    mov     dword ptr [{dst:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{dst + 4:#x}], edx
    mov     edx, dword ptr [eax+8]
    dec     edx
    mov     dword ptr [{dst + 8:#x}], edx
    mov     edx, dword ptr [eax+12]
    dec     edx
    mov     dword ptr [{dst + 12:#x}], edx
    mov     dword ptr [esp+4], {dst:#x}
"""


def asm_dw_bm() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
{_bm_copy(CELL['g_dw_bmrect'])}
    jmp     {HOLLOWFLAT:#x}
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_dw_pickcell() -> str:
    # picker cell frame: bm copy -> hollow_flat (thiscall RET 8) -> restripe the ORIGINAL rect's interior @K+2 with the
    # pair of the params set (proto log: d528 normal 196/65, d578 selected 191/83, d550 hover 194/65)
    R2 = CELL["g_dw_rect2"]
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    pop     eax
    mov     dword ptr [{CELL['g_dw_ret1']:#x}], eax
    mov     eax, dword ptr [esp]
    mov     edx, dword ptr [eax]
    mov     dword ptr [{R2:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{R2 + 4:#x}], edx
    mov     edx, dword ptr [eax+8]
    mov     dword ptr [{R2 + 8:#x}], edx
    mov     edx, dword ptr [eax+12]
    mov     dword ptr [{R2 + 12:#x}], edx
    mov     eax, dword ptr [esp+4]
    mov     dword ptr [{CELL['g_dw_ret2']:#x}], eax
    mov     dword ptr [{CELL['g_dw_ecx']:#x}], ecx
    call    thunk_dw_bm
    mov     ecx, dword ptr [{CELL['g_dw_ecx']:#x}]
    mov     eax, dword ptr [{CELL['g_dw_ret2']:#x}]
    cmp     eax, 0x78D578
    je      sel
    cmp     eax, 0x78D550
    je      hov
    push    65
    push    196
    jmp     rs
sel:
    push    83
    push    191
    jmp     rs
hov:
    push    65
    push    194
rs:
    push    -1
    push    {R2:#x}
    call    thunk_dw_restripe
    jmp     dword ptr [{CELL['g_dw_ret1']:#x}]
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_dw_container() -> str:
    # picker CONTAINER frame (0x434285, drawn by PartPicker_repaint BEFORE its cell loop): bm copy -> hollow_flat ->
    # restripe the container interior with the TILE pair 197/65 at inset K+2.  The whole grid area is tiled by the
    # repaint at 1:1 (NN-banded at device res); the cells redraw their own interiors afterwards, so this pass is what
    # regenerates the GUTTERS between cells and the empty rows' seams (user 1600 shot 201157: a faint dark grid).
    # The proto's hollow_flat hook restriped every picker-canvas draw, container included.
    R2 = CELL["g_dw_rect2"]
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    pop     eax
    mov     dword ptr [{CELL['g_dw_ret1']:#x}], eax
    mov     eax, dword ptr [esp]
    mov     edx, dword ptr [eax]
    mov     dword ptr [{R2:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{R2 + 4:#x}], edx
    mov     edx, dword ptr [eax+8]
    mov     dword ptr [{R2 + 8:#x}], edx
    mov     edx, dword ptr [eax+12]
    mov     dword ptr [{R2 + 12:#x}], edx
    mov     dword ptr [{CELL['g_dw_ecx']:#x}], ecx
    call    thunk_dw_bm
    mov     ecx, dword ptr [{CELL['g_dw_ecx']:#x}]
    push    65
    push    197
    push    -1
    push    {R2:#x}
    call    thunk_dw_restripe
    jmp     dword ptr [{CELL['g_dw_ret1']:#x}]
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_dw_tilecell() -> str:
    # Buffer_tile_2(self, src, a3, a4, x, y, W, H) RET 0x1C: tile, then restripe (x,y,x+W,y+H) inset 0 pair 197/65
    R2 = CELL["g_dw_rect2"]
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    pop     eax
    mov     dword ptr [{CELL['g_dw_ret1']:#x}], eax
    mov     eax, dword ptr [esp+0xC]
    mov     dword ptr [{R2:#x}], eax
    add     eax, dword ptr [esp+0x14]
    mov     dword ptr [{R2 + 8:#x}], eax
    mov     eax, dword ptr [esp+0x10]
    mov     dword ptr [{R2 + 4:#x}], eax
    add     eax, dword ptr [esp+0x18]
    mov     dword ptr [{R2 + 12:#x}], eax
    mov     dword ptr [{CELL['g_dw_ecx']:#x}], ecx
    call    {BUFFER_TILE_2:#x}
    mov     ecx, dword ptr [{CELL['g_dw_ecx']:#x}]
    push    65
    push    197
    push    0
    push    {R2:#x}
    call    thunk_dw_restripe
    jmp     dword ptr [{CELL['g_dw_ret1']:#x}]
native:
    jmp     {BUFFER_TILE_2:#x}
"""


def asm_dw_slotcell() -> str:
    # slot strip cell Buffer_box_sprite(rect*, params*) RET 8 into the MainWin buffer: params d550 (hover) -> 194/65,
    # d578 (selected) -> 191/83, inset K+2.  Other params: plain.
    R2 = CELL["g_dw_rect2"]
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    mov     eax, dword ptr [esp+8]
    cmp     eax, 0x78D550
    je      go
    cmp     eax, 0x78D578
    jne     native
go:
    pop     eax
    mov     dword ptr [{CELL['g_dw_ret1']:#x}], eax
    mov     eax, dword ptr [esp+4]
    mov     dword ptr [{CELL['g_dw_ret2']:#x}], eax
    mov     eax, dword ptr [esp]
    mov     edx, dword ptr [eax]
    mov     dword ptr [{R2:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{R2 + 4:#x}], edx
    mov     edx, dword ptr [eax+8]
    mov     dword ptr [{R2 + 8:#x}], edx
    mov     edx, dword ptr [eax+12]
    mov     dword ptr [{R2 + 12:#x}], edx
    mov     dword ptr [{CELL['g_dw_ecx']:#x}], ecx
    call    {BOX_SPRITE:#x}
    mov     ecx, dword ptr [{CELL['g_dw_ecx']:#x}]
    cmp     dword ptr [{CELL['g_dw_ret2']:#x}], 0x78D578
    je      sel
    push    65
    push    194
    jmp     rs
sel:
    push    83
    push    191
rs:
    push    -1
    push    {R2:#x}
    call    thunk_dw_restripe
    jmp     dword ptr [{CELL['g_dw_ret1']:#x}]
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_dw_restripe() -> str:
    """CALL helper: (ecx = Buffer, [esp+4] rect*, [esp+8] inset (-1 = K+2), [esp+0xC] top, [esp+0x10] mate) RET 0x10.
    Every pixel of the pair inside the inset rect (clamped to the buffer) becomes stripe_top(y) ? top : mate
    (P-law, phase = buffer row).  Skips rects narrower/shorter than 8.  Native no-op at g<=16."""
    # frame (ebp): +0 data +4 pitch +8 x0 +0xC y0 +0x10 x1 +0x14 y1 +0x18 P +0x1C hN +0x20 top +0x24 mate +0x28 w +0x2C h
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     xout
    pushad
    sub     esp, 0x30
    mov     ebp, esp
    mov     ebx, ecx
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    je      done
    mov     dword ptr [ebp], eax
    mov     eax, dword ptr [ebx+0x80]
    test    eax, eax
    jle     done
    mov     dword ptr [ebp+0x28], eax
    mov     edx, dword ptr [ebx+0x84]
    neg     edx
    test    edx, edx
    jle     done
    mov     dword ptr [ebp+0x2C], edx
    mov     edx, dword ptr [ebx+0x4A8]
    cmp     edx, eax
    jl      p4
    lea     ecx, [eax+8]
    cmp     edx, ecx
    jle     pok
p4:
    lea     edx, [eax+3]
    and     edx, -4
pok:
    mov     dword ptr [ebp+4], edx
    mov     eax, dword ptr [{G:#x}]
    mov eax, dword ptr [0x66879c]
    nop
    mov     dword ptr [ebp+0x18], eax
    inc     eax
    sar     eax, 1
    mov     dword ptr [ebp+0x1C], eax
    mov     eax, dword ptr [esp+0x5C]
    mov     dword ptr [ebp+0x20], eax
    mov     eax, dword ptr [esp+0x60]
    mov     dword ptr [ebp+0x24], eax
    mov     ecx, dword ptr [esp+0x58]
    test    ecx, ecx
    jns     ins
    mov     ecx, dword ptr [{G:#x}]
    lea     ecx, [ecx*2+15]
    sar     ecx, 5
    add     ecx, 2
ins:
    mov     esi, dword ptr [esp+0x54]
    mov     eax, dword ptr [esi]
    add     eax, ecx
    test    eax, eax
    jns     cx0
    xor     eax, eax
cx0:
    mov     dword ptr [ebp+8], eax
    mov     eax, dword ptr [esi+4]
    add     eax, ecx
    test    eax, eax
    jns     cy0
    xor     eax, eax
cy0:
    mov     dword ptr [ebp+0xC], eax
    mov     eax, dword ptr [esi+8]
    sub     eax, ecx
    cmp     eax, dword ptr [ebp+0x28]
    jle     cx1
    mov     eax, dword ptr [ebp+0x28]
cx1:
    mov     dword ptr [ebp+0x10], eax
    mov     eax, dword ptr [esi+12]
    sub     eax, ecx
    cmp     eax, dword ptr [ebp+0x2C]
    jle     cy1
    mov     eax, dword ptr [ebp+0x2C]
cy1:
    mov     dword ptr [ebp+0x14], eax
    mov     eax, dword ptr [ebp+0x10]
    sub     eax, dword ptr [ebp+8]
    cmp     eax, 8
    jl      done
    mov     eax, dword ptr [ebp+0x14]
    sub     eax, dword ptr [ebp+0xC]
    cmp     eax, 8
    jl      done
    mov     esi, dword ptr [ebp+0xC]
rowy:
    cmp     esi, dword ptr [ebp+0x14]
    jge     done
    mov     eax, esi
    xor     edx, edx
    div     dword ptr [ebp+0x18]
    mov     ecx, dword ptr [ebp+0x24]
    cmp     edx, dword ptr [ebp+0x1C]
    jge     usec
    mov     ecx, dword ptr [ebp+0x20]
usec:
    mov     edi, esi
    imul    edi, dword ptr [ebp+4]
    add     edi, dword ptr [ebp]
    mov     edx, dword ptr [ebp+8]
colx:
    cmp     edx, dword ptr [ebp+0x10]
    jge     nextrow
    movzx   eax, byte ptr [edi+edx]
    cmp     eax, dword ptr [ebp+0x20]
    je      wr
    cmp     eax, dword ptr [ebp+0x24]
    jne     nx
wr:
    mov     byte ptr [edi+edx], cl
nx:
    inc     edx
    jmp     colx
nextrow:
    inc     esi
    jmp     rowy
done:
    add     esp, 0x30
    popad
xout:
    ret     0x10
"""


def asm_dw_btndraw() -> str:
    # detour @0x404220 (`xor eax,eax; ret 0xC`, the vtbl+0x14 item-draw default): DesignWin FlatButtons while the
    # workshop is open -> t_dw_face_ph (2026-10-14: stages g_se_yph, law dw_button_face_stripe_phase) ->
    # thunk_dw_btnface (the SE face-restripe recipe, DW-owned: it RETURNS); everything else gets the stub's own
    # behaviour.  The near jmp (was short to the next thunk) fits the 5 B of alignment slack before btnface.
    return f"""
    cmp     dword ptr [{CELL['g_dw_active']:#x}], 0
    je      plain
    cmp     dword ptr [{G:#x}], 16
    jle     plain
    mov     eax, dword ptr [esp+4]
    cmp     eax, {DW_LO:#x}
    jb      plain
    cmp     eax, {DW_HI:#x}
    jae     plain
    jmp     {T_DW_FACE_PH:#x}
plain:
    xor     eax, eax
    ret     0xC
"""


def asm_dw_btnface() -> str:
    """The SE FlatButton face restripe (assemble_se.asm_se_rowdraw: pair detected per draw from one face column,
    every pair pixel rewritten to stripe_top(row), the state-sprite ring pinned to K, trailing key rows overdrawn)
    with ONE change: the tail RETURNS (`xor eax,eax; ret 0xC` = the item-draw default) instead of jumping to
    SocialWin_draw_society_row.  v1/v1b reused thunk_se_rowdraw itself and that tail drew SocialWin's slider
    sprites relative to a DesignWin button's parent (MainWin) -> Sprite_draw_2(&hudbtn3->art) -> Buffer_load_pcx(-1)
    -> the strcat AV on opening the workshop.  Same frame layout, so the SE CALL helpers are shared.
    2026-10-14: built phased=True -- the 5 stripe rows go through thunk_se_stripe_px_ph (y + g_se_yph), staged by
    t_dw_face_ph (law dw_button_face_stripe_phase); phased=False striped every face from its own row 0, a stripe
    off DesignWin's grid wherever the button's parent-local top is odd (1920x1080 DONE row, shot 20261006-201336)."""
    src = SE.asm_se_rowdraw(phased=True)
    old = "native:\n    jmp     " + f"{SE.ROWDRAW:#x}" + "\n"
    assert src.count(old) == 1, "asm_se_rowdraw tail changed"
    return src.replace(old, "native:\n    xor     eax, eax\n    ret     0xC\n")


def asm_btn_gate_pre_v4() -> str:
    """v4 = DW HIT prefix (EXEC-scoped: g_dw_active) + v3's SE/council prefixes + v1 body; the three HIT
    tails are `push 1; pop eax; ret` (4B) so v4 fits the 96B slot."""
    cwin_lo, cwin_hi = 0x6FEC80 + 0xD94, 0x6FEC80 + 0xD94 + 6 * 0xB4C
    return f"""
    cmp     dword ptr [{CELL['g_dw_active']:#x}], 0
    je      v3
    cmp     esi, {DW_LO:#x}
    jb      v3
    cmp     esi, {DW_HI:#x}
    jae     v3
    push    1
    pop     eax
    ret
v3:
    cmp     esi, {SE_LO:#x}
    jb      v2
    cmp     esi, {SE_HI:#x}
    jae     v2
    push    1
    pop     eax
    ret
v2:
    cmp     esi, {cwin_lo:#x}
    jb      v1
    cmp     esi, {cwin_hi:#x}
    jae     v1
    push    1
    pop     eax
    ret
v1:
    cmp     esi, 0x7fe80c
    je      miss
    cmp     esi, 0x7ff358
    jne     pass
miss:
    xor     eax, eax
    ret
pass:
    push    {BTN_GATE:#x}
    ret
"""


# ==== dw_scale: Caviar composite / render path ======================================
def asm_dw_shim() -> str:
    """call-redirect @0x6175F4: Buffer_draw_2(src=target [ecx], dst, key, X, Y, num, den) RET 0x18.
    Gate: dst == DW canvas || dst == [g_dw_pickcanvas], g>16.  [g_dw_ssaaw] != 0 -> the SSAA composite;
    else [g_dw_fitw] == 0 -> suppressed (trial); else keyed stretch of the TN^2 target to fitw^2 at
    (X-[fitoff], Y-[fitoff]) via thunk_keyed_stretch_blit (RET 0x2C).  Half mode (num==2): fitw/2."""
    FITW, FITOFF, PICK, SSW = CELL["g_dw_fitw"], CELL["g_dw_fitoff"], CELL["g_dw_pickcanvas"], CELL["g_dw_ssaaw"]
    return f"""
    mov     eax, dword ptr [esp+4]
    cmp     eax, {DW_CANVAS:#x}
    je      hit
    cmp     eax, dword ptr [{PICK:#x}]
    jne     plain
hit:
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 16
    jle     plain
    cmp     dword ptr [{SSW:#x}], 0
    jne     ssaa
    mov     eax, dword ptr [{FITW:#x}]
    test    eax, eax
    jz      skip
    push    ebx
    push    esi
    push    edi
    mov     edi, eax
    mov     ebx, dword ptr [{FITOFF:#x}]
    mov     edx, dword ptr [esp+0x24]
    cmp     edx, 2
    jne     full
    shr     edi, 1
    sar     ebx, 1
full:
    mov     esi, {TN}
    push    dword ptr [esp+0x14]
    push    edi
    push    edi
    mov     eax, dword ptr [esp+0x28]
    sub     eax, ebx
    push    eax
    mov     eax, dword ptr [esp+0x28]
    sub     eax, ebx
    push    eax
    push    esi
    push    esi
    push    0
    push    0
    push    dword ptr [esp+0x34]
    push    ecx
    mov     eax, {KSB:#x}
    call    eax
    pop     edi
    pop     esi
    pop     ebx
skip:
    ret     0x18
ssaa:
    push    ecx
    mov     eax, dword ptr [{SSW:#x}]
    sar     eax, 1
    sub     eax, {TN // 2}
    mov     edx, dword ptr [esp+0x14]
    sub     edx, eax
    push    edx
    mov     edx, dword ptr [esp+0x14]
    sub     edx, eax
    push    edx
    push    dword ptr [esp+0x10]
    call    thunk_dw_ssaa
    pop     ecx
    ret     0x18
plain:
    jmp     {BUFFER_DRAW_2:#x}
"""


def asm_dw_ovl() -> str:
    return f"""
    mov     eax, dword ptr [{OVL['ON']:#x}]
    test    eax, eax
    jz      pass
    mov     dword ptr [{OVL['ON']:#x}], 0
    mov     eax, dword ptr [{OVL['OFF']:#x}]
    sub     dword ptr [esp+0xc], eax
    sub     dword ptr [esp+0x10], eax
    mov     eax, dword ptr [{OVL['NUM']:#x}]
    mov     dword ptr [esp+0x14], eax
    mov     eax, dword ptr [{OVL['DEN']:#x}]
    mov     dword ptr [esp+0x18], eax
pass:
    jmp     {OVL_TARGET:#x}
"""


def asm_dw_ewin() -> str:
    return f"""
    lea     edi, [ecx - {TN // 2}]
    mov     dword ptr [esp+0x4c], edx
    lea     esi, [eax - {TN // 2}]
    lea     ecx, [esp+0x40]
    lea     edx, [edi + {TN}]
    push    ecx
    lea     eax, [esi + {TN}]
    jmp     0x617328
"""


def asm_dw_eovl() -> str:
    return f"""
    add     ecx, -{TN // 2}
    push    1
    add     edx, -{TN // 2}
    jmp     0x6171EF
"""


def asm_dw_ehalfa() -> str:
    return f"""
    add     eax, -{TN // 4}
    mov     edx, dword ptr [ecx+0x54]
    mov     ecx, dword ptr [esp+0x8c]
    push    edx
    push    2
    push    1
    add     ecx, -{TN // 4}
    push    eax
    push    ecx
    jmp     0x6175A4
"""


def asm_dw_ehalfb() -> str:
    return f"""
    add     ecx, -{TN // 4}
    push    1
    add     edx, -{TN // 4}
    push    ecx
    push    edx
    jmp     0x6175EC
"""


E_IMMS = [   # (va, width, native, new, note) -- option E: the Caviar render target 256^2 -> TN^2 (17 immediates)
    (0x6188B1 + 1, 4, 0x100, TN, "init Buffer_init dims/descriptor/ctx w,h/row stride (esi)"),
    (0x618A91 + 1, 4, 0x20000, TN * TN * 2, "init z-plane malloc"),
    (0x618BA9 + 1, 4, 0x10000, TN * TN, "init z-plane memset16 count"),
    (0x618C67 + 1, 4, 0xFF, TN - 1, "init ctx clip R/B"),
    (0x618CB4 + 1, 4, 0x400, TN * 4, "init row-table loop bound"),
    (0x61728D + 1, 4, 0xFF, TN - 1, "Caviar_draw obj clip R/B"), (0x6172A8 + 1, 4, 0x100, TN, "Caviar_draw obj clip W/H"),
    (0x61735E + 1, 4, 0x80, TN // 2, "Caviar_draw window centre x"), (0x617365 + 1, 4, 0x80, TN // 2, "Caviar_draw window centre y"),
    (0x616ED4 + 1, 4, 0xFF, TN - 1, "ctor clip R/B"), (0x616EEB + 1, 4, 0x100, TN, "ctor clip W/H"),
    (0x6170C5 + 1, 4, 0xFF, TN - 1, "attach clip R/B"), (0x6170DB + 1, 4, 0x100, TN, "attach clip W/H"),
    (0x6183FC + 1, 4, 0xFF, TN - 1, "set_target clip R/B"), (0x618410 + 1, 4, 0x100, TN, "set_target clip W/H"),
    (0x618497 + 2, 1, 8, 10, "reset z row shift"), (0x6184DD + 2, 4, 0x200, TN * 2, "reset z row stride"),
]
E_STUB_SITES = [   # (name, site, len, native prefix)
    ("thunk_dw_ewin", 0x61730D, 27, bytes([0x8d, 0x79, 0x80, 0x89, 0x54, 0x24, 0x4c, 0x8d, 0x70, 0x80])),
    ("thunk_dw_eovl", 0x6171E7, 8, bytes([0x83, 0xc1, 0x80, 0x6a, 0x01, 0x83, 0xc2, 0x80])),
    ("thunk_dw_ehalfa", 0x61757B, 25, bytes([0x83, 0xc0, 0xc0, 0x8b, 0x51, 0x54])),
    ("thunk_dw_ehalfb", 0x6175DA, 12, bytes([0x83, 0xc1, 0xc0, 0x6a, 0x01, 0x83, 0xc2, 0xc0])),
]


def asm_dw_fp() -> str:
    # v14 footprint cave 1 (asm_fp.py verbatim, cells resolved): no stack use (esp = shade table); ecx saved.
    F = FPC
    return f"""
    mov     bh, byte ptr [esp+eax]
    add     edi, 3
    mov     esi, dword ptr [{CV_SHADE_TBL:#x}]
    mov     al, byte ptr [esi+ebx]
    mov     bl, byte ptr [edi-3]
    mov     dword ptr [{F['SAVE_ECX']:#x}], ecx
    mov     ecx, ebp
    add     ecx, dword ptr [{CV_DATA_BASE:#x}]
    mov     esi, ecx
    add     esi, dword ptr [{F['SPAN']:#x}]
    cmp     esi, dword ptr [{F['DEND']:#x}]
    jae     done
    mov     esi, ebp
    add     esi, esi
    add     esi, dword ptr [{CV_Z_BASE:#x}]
    mov     ah, byte ptr [{F['NY']:#x}]
    mov     byte ptr [{F['ROWS']:#x}], ah
row:
    mov     ah, byte ptr [{F['N']:#x}]
col:
    cmp     dx, word ptr [esi]
    jae     skip
    mov     word ptr [esi], dx
    mov     byte ptr [ecx], al
skip:
    add     esi, 2
    inc     ecx
    dec     ah
    jnz     col
    add     esi, dword ptr [{F['ZROW']:#x}]
    add     ecx, dword ptr [{F['DROW']:#x}]
    dec     byte ptr [{F['ROWS']:#x}]
    jnz     row
done:
    mov     ecx, dword ptr [{F['SAVE_ECX']:#x}]
    jmp     {FP_RESUME:#x}
"""


def asm_dw_fp2() -> str:
    F = FPC
    return f"""
    add     ecx, ebx
    mov     dword ptr [{F['IDX']:#x}], ecx
    add     ecx, dword ptr [{CV_DATA_BASE:#x}]
    mov     ebx, ecx
    add     ebx, dword ptr [{F['SPAN']:#x}]
    cmp     ebx, dword ptr [{F['DEND']:#x}]
    jae     done
    mov     ebx, dword ptr [{F['IDX']:#x}]
    add     ebx, ebx
    add     ebx, dword ptr [{CV_Z_BASE:#x}]
    mov     ah, byte ptr [{F['NY']:#x}]
    mov     byte ptr [{F['ROWS']:#x}], ah
row:
    mov     ah, byte ptr [{F['N']:#x}]
col:
    cmp     dx, word ptr [ebx]
    jae     skip
    mov     word ptr [ebx], dx
    mov     byte ptr [ecx], al
skip:
    add     ebx, 2
    inc     ecx
    dec     ah
    jnz     col
    add     ebx, dword ptr [{F['ZROW']:#x}]
    add     ecx, dword ptr [{F['DROW']:#x}]
    dec     byte ptr [{F['ROWS']:#x}]
    jnz     row
done:
    jmp     {FP2_RESUME:#x}
"""


def asm_dw_fpset() -> str:
    """call-redirect at the two `call 0x6404F0` run-table sites: per-part footprint.  Gated real draws
    (g_dw_fpgated): nx = clamp(2..8, ceil(sum|x-row|/256)), ny likewise from the 8.8 projected axis
    steps 0x9C0A40 (v14d law); otherwise 2x2 (vanilla).  Cells: N NY ZROW DROW SPAN DEND from the bound
    target's pitches.  Every register preserved (pushad)."""
    F = FPC
    return f"""
    pushad
    mov     ecx, 2
    mov     edx, 2
    cmp     dword ptr [{CELL['g_dw_fpgated']:#x}], 0
    je      setcells
    xor     ecx, ecx
    movsx   eax, word ptr [{CV_MTX:#x}]
    cdq
    xor     eax, edx
    sub     eax, edx
    add     ecx, eax
    movsx   eax, word ptr [{CV_MTX + 2:#x}]
    cdq
    xor     eax, edx
    sub     eax, edx
    add     ecx, eax
    movsx   eax, word ptr [{CV_MTX + 4:#x}]
    cdq
    xor     eax, edx
    sub     eax, edx
    add     ecx, eax
    add     ecx, 255
    shr     ecx, 8
    cmp     ecx, 2
    jge     cx2
    mov     ecx, 2
cx2:
    cmp     ecx, 8
    jle     cx8
    mov     ecx, 8
cx8:
    push    ecx
    xor     ecx, ecx
    movsx   eax, word ptr [{CV_MTX + 6:#x}]
    cdq
    xor     eax, edx
    sub     eax, edx
    add     ecx, eax
    movsx   eax, word ptr [{CV_MTX + 8:#x}]
    cdq
    xor     eax, edx
    sub     eax, edx
    add     ecx, eax
    movsx   eax, word ptr [{CV_MTX + 10:#x}]
    cdq
    xor     eax, edx
    sub     eax, edx
    add     ecx, eax
    add     ecx, 255
    shr     ecx, 8
    cmp     ecx, 2
    jge     cy2
    mov     ecx, 2
cy2:
    cmp     ecx, 8
    jle     cy8
    mov     ecx, 8
cy8:
    mov     edx, ecx
    pop     ecx
setcells:
    mov     dword ptr [{F['N']:#x}], ecx
    mov     dword ptr [{F['NY']:#x}], edx
    mov     eax, dword ptr [{CV_ZPITCH:#x}]
    add     eax, eax
    sub     eax, ecx
    sub     eax, ecx
    mov     dword ptr [{F['ZROW']:#x}], eax
    mov     eax, dword ptr [{CV_PITCH:#x}]
    sub     eax, ecx
    mov     dword ptr [{F['DROW']:#x}], eax
    mov     eax, edx
    dec     eax
    imul    eax, dword ptr [{CV_PITCH:#x}]
    add     eax, ecx
    dec     eax
    mov     dword ptr [{F['SPAN']:#x}], eax
    mov     eax, dword ptr [{CV_PITCH:#x}]
    shl     eax, 10
    add     eax, dword ptr [{CV_DATA_BASE:#x}]
    mov     dword ptr [{F['DEND']:#x}], eax
    popad
    jmp     {RUNTAB:#x}
"""


def asm_dw_clip() -> str:
    # call-redirect @0x6174CE (Caviar_rasterize, cdecl; args pushed): gated -> ctx clip = whole target.  eax dead.
    return f"""
    cmp     dword ptr [{CELL['g_dw_gated']:#x}], 0
    je      go
    mov     eax, dword ptr [{CV_CTX:#x}]
    test    eax, eax
    je      go
    mov     dword ptr [eax+0x38], 0
    mov     dword ptr [eax+0x3C], 0
    mov     dword ptr [eax+0x40], {TN}
    mov     dword ptr [eax+0x44], {TN}
    mov     dword ptr [eax+0x48], {TN}
    mov     dword ptr [eax+0x4C], {TN}
go:
    jmp     {CAVIAR_RASTERIZE:#x}
"""


def asm_dw_resetguard() -> str:
    # call-redirect @0x61760F (Caviar_draw tail: Caviar_reset(flag&1)): clamp the dirty rect to [0, TN] first
    # (Caviar_reset memsets rows miny..maxy UNCLIPPED -- the v7/v8 heap overrun).  eax = the pushed arg copy: dead.
    return f"""
    mov     eax, dword ptr [{CV_MINX:#x}]
    test    eax, eax
    jns     a1
    mov     dword ptr [{CV_MINX:#x}], 0
a1:
    mov     eax, dword ptr [{CV_MINX + 4:#x}]
    test    eax, eax
    jns     a2
    mov     dword ptr [{CV_MINX + 4:#x}], 0
a2:
    cmp     dword ptr [{CV_MINX + 8:#x}], {TN}
    jle     a3
    mov     dword ptr [{CV_MINX + 8:#x}], {TN}
a3:
    cmp     dword ptr [{CV_MINX + 12:#x}], {TN}
    jle     a4
    mov     dword ptr [{CV_MINX + 12:#x}], {TN}
a4:
    jmp     {CAVIAR_RESET:#x}
"""


def asm_dw_fit() -> str:
    """call-redirect at the Caviar_draw sites: Caviar_draw(this, dst, x, y, flag) thiscall RET 0x10.
    Gated (g>16, dst == DW canvas || picker canvas, zoom > 0; the part-box/picker icons pass flag 6, the preview 0x17):
      1. snapshot this+0x14..+0x114; [fitw]=0 (composite suppressed), [gated]=1 (ctx clip override), TRIAL
         Caviar_draw at native zoom; Caviar_reset(this, 0); overlay (flag&8): refill the target with the
         wrapper's bg (target pixel 0,0 read before the trial); restore the snapshot.
      2. plan from the trial bbox (ctx+8..+0x14 inclusive -> +1): law dw_fit_plan, integer form
         (tn=1024, c=512, slack 4, margin 8): r = max(1, R-c, c-L, B-c, c-T) + 4;
         ssaa (not overlay) if g*r <= 8064: k = min(2g/16, 504/r): 2gr <= 8064 -> W=512 else W=(128gr+504)/1008;
         else fit if r <= 494: gr <= 8064 -> W=1024 (fit1:1) else W=(128gr+504)/1008; else nn: W=64g, k=1.
         zoom' = zoom * 64g/W (x87) when not nn.
      3. overlay: OFF = W/2 - 512, NUM/DEN = W/1024 reduced, ON=1.  ssaa: [ssaaw]=W; else [fitw]=W,
         [fitoff]=W/2-512.  [fpgated] = (mode != nn).  Real Caviar_draw; restore zoom; clear cells; ret 0x10."""
    SNAP, FITW, FITOFF, PICK, SSW = CELL["g_dw_snap"], CELL["g_dw_fitw"], CELL["g_dw_fitoff"], CELL["g_dw_pickcanvas"], CELL["g_dw_ssaaw"]
    GATED, FPG, CV, ZOOM, RET = CELL["g_dw_gated"], CELL["g_dw_fpgated"], CELL["g_dw_cv"], CELL["g_dw_zoom"], CELL["g_dw_ret3"]
    # frame after pop ret + pushad + sub 0x30 (ebp=esp): args at [ebp+0x50..]: dst +0x50 x +0x54 y +0x58 flag +0x5C
    # locals: +0 r +4 W +8 mode(0 nn,1 fit,2 ssaa) +0xC bg +0x10 ovl +0x14 tmp +0x18 num +0x1C den
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     plain
    mov     eax, dword ptr [esp+4]
    cmp     eax, {DW_CANVAS:#x}
    je      hit
    cmp     eax, dword ptr [{PICK:#x}]
    jne     plain
hit:
    mov     eax, dword ptr [ecx+0xD5]
    test    eax, eax
    jle     plain
    pop     eax
    mov     dword ptr [{RET:#x}], eax
    pushad
    sub     esp, 0x30
    mov     ebp, esp
    mov     ebx, ecx
    mov     dword ptr [{CV:#x}], ecx
    mov     eax, dword ptr [ebp+0x5C]
    and     eax, 8
    mov     dword ptr [ebp+0x10], eax
    mov     dword ptr [ebp+0xC], -1
    test    eax, eax
    je      nobg
    mov     eax, dword ptr [{CV_TARGET + 0x54:#x}]
    test    eax, eax
    je      nobg
    movzx   eax, byte ptr [eax]
    mov     dword ptr [ebp+0xC], eax
nobg:
    lea     esi, [ebx+0x14]
    mov     edi, {SNAP:#x}
    mov     ecx, 0x40
    rep movsd dword ptr es:[edi], dword ptr [esi]
    mov     dword ptr [{FITW:#x}], 0
    mov     dword ptr [{SSW:#x}], 0
    mov     dword ptr [{GATED:#x}], 1
    mov     dword ptr [{FPG:#x}], 0
    push    dword ptr [ebp+0x5C]
    push    dword ptr [ebp+0x58]
    push    dword ptr [ebp+0x54]
    push    dword ptr [ebp+0x50]
    mov     ecx, ebx
    call    {CAVIAR_DRAW:#x}
    push    0
    mov     ecx, ebx
    call    {CAVIAR_RESET:#x}
    mov     eax, dword ptr [ebp+0xC]
    test    eax, eax
    js      norefill
    push    eax
    mov     ecx, {CV_TARGET:#x}
    call    {BUFFER_FILL_2:#x}
norefill:
    mov     esi, {SNAP:#x}
    lea     edi, [ebx+0x14]
    mov     ecx, 0x40
    rep movsd dword ptr es:[edi], dword ptr [esi]
    mov     esi, dword ptr [{CV_CTX:#x}]
    mov     eax, 1
    mov     ecx, dword ptr [esi+0x10]
    inc     ecx
    sub     ecx, {TN // 2}
    cmp     ecx, eax
    jle     r1
    mov     eax, ecx
r1:
    mov     ecx, {TN // 2}
    sub     ecx, dword ptr [esi+8]
    cmp     ecx, eax
    jle     r2
    mov     eax, ecx
r2:
    mov     ecx, dword ptr [esi+0x14]
    inc     ecx
    sub     ecx, {TN // 2}
    cmp     ecx, eax
    jle     r3
    mov     eax, ecx
r3:
    mov     ecx, {TN // 2}
    sub     ecx, dword ptr [esi+0xC]
    cmp     ecx, eax
    jle     r4
    mov     eax, ecx
r4:
    add     eax, {SL.DW_FIT_SLACK}
    mov     dword ptr [ebp], eax
    mov     ecx, dword ptr [{G:#x}]
    imul    ecx, eax
    mov     dword ptr [ebp+0x14], ecx
    cmp     dword ptr [ebp+0x10], 0
    jne     tryfit
    cmp     ecx, {(TN // 2 - SL.DW_FIT_MARGIN) * 16}
    jg      tryfit
    mov     dword ptr [ebp+8], 2
    lea     edx, [ecx+ecx]
    cmp     edx, {(TN // 2 - SL.DW_FIT_MARGIN) * 16}
    jg      wfrac
    mov     dword ptr [ebp+4], {TN // 2}
    jmp     planned
tryfit:
    cmp     dword ptr [ebp], {int(((TN // 2 - SL.DW_FIT_MARGIN) / SL.DW_FIT_MIN_FIT) - 1e-9)}
    jg      nn
    mov     dword ptr [ebp+8], 1
    cmp     ecx, {(TN // 2 - SL.DW_FIT_MARGIN) * 16}
    jg      wfrac
    mov     dword ptr [ebp+4], {TN}
    jmp     planned
wfrac:
    mov     eax, ecx
    shl     eax, 7
    add     eax, {(TN // 2 - SL.DW_FIT_MARGIN)}
    xor     edx, edx
    mov     ecx, {(TN // 2 - SL.DW_FIT_MARGIN) * 2}
    div     ecx
    mov     dword ptr [ebp+4], eax
    jmp     planned
nn:
    mov     dword ptr [ebp+8], 0
    mov     eax, dword ptr [{G:#x}]
    shl     eax, 6
    mov     dword ptr [ebp+4], eax
planned:
    mov     eax, dword ptr [ebx+0xD5]
    mov     dword ptr [{ZOOM:#x}], eax
    cmp     dword ptr [ebp+8], 0
    je      zoomok
    mov     eax, dword ptr [{G:#x}]
    shl     eax, 6
    mov     dword ptr [ebp+0x14], eax
    fld     dword ptr [ebx+0xD5]
    fimul   dword ptr [ebp+0x14]
    fidiv   dword ptr [ebp+4]
    fstp    dword ptr [ebx+0xD5]
    mov     dword ptr [{FPG:#x}], 1
zoomok:
    cmp     dword ptr [ebp+0x10], 0
    je      noovl
    mov     eax, dword ptr [ebp+4]
    sar     eax, 1
    sub     eax, {TN // 2}
    mov     dword ptr [{OVL['OFF']:#x}], eax
    mov     eax, dword ptr [ebp+4]
    mov     ecx, {TN}
gcd:
    xor     edx, edx
    div     ecx
    mov     eax, ecx
    mov     ecx, edx
    test    ecx, ecx
    jne     gcd
    mov     ecx, eax
    mov     eax, dword ptr [ebp+4]
    xor     edx, edx
    div     ecx
    mov     dword ptr [{OVL['NUM']:#x}], eax
    mov     eax, {TN}
    xor     edx, edx
    div     ecx
    mov     dword ptr [{OVL['DEN']:#x}], eax
    mov     dword ptr [{OVL['ON']:#x}], 1
noovl:
    mov     eax, dword ptr [ebp+4]
    cmp     dword ptr [ebp+8], 2
    jne     nnfit
    mov     dword ptr [{SSW:#x}], eax
    jmp     real
nnfit:
    mov     dword ptr [{FITW:#x}], eax
    sar     eax, 1
    sub     eax, {TN // 2}
    mov     dword ptr [{FITOFF:#x}], eax
real:
    push    dword ptr [ebp+0x5C]
    push    dword ptr [ebp+0x58]
    push    dword ptr [ebp+0x54]
    push    dword ptr [ebp+0x50]
    mov     ecx, ebx
    call    {CAVIAR_DRAW:#x}
    mov     dword ptr [ebp+0x1C], eax
    mov     eax, dword ptr [{ZOOM:#x}]
    mov     dword ptr [ebx+0xD5], eax
    mov     dword ptr [{GATED:#x}], 0
    mov     dword ptr [{FPG:#x}], 0
    mov     dword ptr [{SSW:#x}], 0
    mov     dword ptr [{FITW:#x}], 0
    mov     dword ptr [{OVL['ON']:#x}], 0
    mov     eax, dword ptr [ebp+0x1C]
    mov     dword ptr [esp+0x30+0x1C], eax
    add     esp, 0x30
    popad
    add     esp, 0x10
    jmp     dword ptr [{RET:#x}]
plain:
    jmp     {CAVIAR_DRAW:#x}
"""


def asm_dw_ssaa() -> str:
    """CALL helper (thunk_dw_shim): (ecx = src Buffer (the target), [esp+4] dst Buffer, [esp+8] left, [esp+0xC] top)
    RET 0xC; W = [g_dw_ssaaw].  Port of the proto's CModule `ssaa`: per dst pixel the box [b0,b1) per axis
    (b0 = d*TN/W), mean RGB of the non-key samples, coverage >= 1/2 else keyed, nearest palette index among
    the render's OWN indices (sample bbox = ctx result bbox) via a 4096-entry direct-mapped 18-bit RGB cache.
    frame g_dw_ss: +0 src +4 sp +8 dst +0xC dp +0x10 L +0x14 T +0x18 R +0x1C B +0x20 left +0x24 top +0x28 W
      +0x2C sx0 +0x30 sy0 +0x34 sx1 +0x38 sy1 +0x3C nc +0x40 dy +0x44 dx +0x48 s0 +0x4C s1"""
    S = CELL["g_dw_ss"]
    # stack frame (ebp): +0 t0 +4 t1 +8 n +0xC tot +0x10 rs +0x14 gs +0x18 bs +0x1C Y +0x20 X +0x24 drow +0x28 dx0 +0x2C dx1 +0x30 dy1 +0x34 k +0x38 best +0x3C bd
    CANDS, PRESENT, CACHE = CELL["g_dw_cands"], CELL["g_dw_present"], CELL["g_dw_cache"]
    return f"""
    pushad
    sub     esp, 0x40
    mov     ebp, esp
    mov     ebx, ecx
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    je      done
    mov     dword ptr [{S:#x}], eax
    mov     eax, dword ptr [ebx+0x80]
    mov     edx, dword ptr [ebx+0x4A8]
    cmp     edx, eax
    jl      sp4
    lea     ecx, [eax+8]
    cmp     edx, ecx
    jle     spok
sp4:
    lea     edx, [eax+3]
    and     edx, -4
spok:
    mov     dword ptr [{S + 4:#x}], edx
    mov     ebx, dword ptr [esp+0x64]
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    je      done
    mov     dword ptr [{S + 8:#x}], eax
    mov     eax, dword ptr [ebx+0x80]
    mov     edx, dword ptr [ebx+0x4A8]
    cmp     edx, eax
    jl      dp4
    lea     ecx, [eax+8]
    cmp     edx, ecx
    jle     dpok
dp4:
    lea     edx, [eax+3]
    and     edx, -4
dpok:
    mov     dword ptr [{S + 0xC:#x}], edx
    mov     ecx, dword ptr [ebx+0x20]
    test    ecx, ecx
    jns     l0
    xor     ecx, ecx
l0:
    mov     dword ptr [{S + 0x10:#x}], ecx
    mov     ecx, dword ptr [ebx+0x24]
    test    ecx, ecx
    jns     t0
    xor     ecx, ecx
t0:
    mov     dword ptr [{S + 0x14:#x}], ecx
    mov     ecx, dword ptr [ebx+0x28]
    cmp     ecx, eax
    jle     r0
    mov     ecx, eax
r0:
    mov     dword ptr [{S + 0x18:#x}], ecx
    mov     ecx, dword ptr [ebx+0x2C]
    mov     edx, dword ptr [ebx+0x84]
    neg     edx
    cmp     ecx, edx
    jle     b0
    mov     ecx, edx
b0:
    mov     dword ptr [{S + 0x1C:#x}], ecx
    mov     eax, dword ptr [esp+0x68]
    mov     dword ptr [{S + 0x20:#x}], eax
    mov     eax, dword ptr [esp+0x6C]
    mov     dword ptr [{S + 0x24:#x}], eax
    mov     eax, dword ptr [{CELL['g_dw_ssaaw']:#x}]
    test    eax, eax
    jle     done
    mov     dword ptr [{S + 0x28:#x}], eax
    mov     esi, dword ptr [{CV_CTX:#x}]
    test    esi, esi
    je      done
    mov     eax, dword ptr [esi+8]
    test    eax, eax
    jns     c0
    xor     eax, eax
c0:
    mov     dword ptr [{S + 0x2C:#x}], eax
    mov     eax, dword ptr [esi+0xC]
    test    eax, eax
    jns     c1
    xor     eax, eax
c1:
    mov     dword ptr [{S + 0x30:#x}], eax
    mov     eax, dword ptr [esi+0x10]
    cmp     eax, {TN - 1}
    jle     c2
    mov     eax, {TN - 1}
c2:
    mov     dword ptr [{S + 0x34:#x}], eax
    mov     eax, dword ptr [esi+0x14]
    cmp     eax, {TN - 1}
    jle     c3
    mov     eax, {TN - 1}
c3:
    mov     dword ptr [{S + 0x38:#x}], eax
    cmp     eax, dword ptr [{S + 0x30:#x}]
    jl      done
    mov     eax, dword ptr [{S + 0x34:#x}]
    cmp     eax, dword ptr [{S + 0x2C:#x}]
    jl      done
    mov     edi, {PRESENT:#x}
    xor     eax, eax
    mov     ecx, 0x40
    rep stosd
    mov     esi, dword ptr [{S + 0x30:#x}]
py:
    cmp     esi, dword ptr [{S + 0x38:#x}]
    jg      pdone
    mov     edi, esi
    imul    edi, dword ptr [{S + 4:#x}]
    add     edi, dword ptr [{S:#x}]
    mov     ecx, dword ptr [{S + 0x2C:#x}]
px:
    cmp     ecx, dword ptr [{S + 0x34:#x}]
    jg      pnext
    movzx   eax, byte ptr [edi+ecx]
    mov     byte ptr [eax+{PRESENT:#x}], 1
    inc     ecx
    jmp     px
pnext:
    inc     esi
    jmp     py
pdone:
    mov     byte ptr [{PRESENT + KEY:#x}], 0
    xor     ecx, ecx
    xor     edx, edx
candl:
    cmp     byte ptr [ecx+{PRESENT:#x}], 0
    je      cn
    mov     dword ptr [edx*4+{CANDS:#x}], ecx
    inc     edx
cn:
    inc     ecx
    cmp     ecx, 256
    jl      candl
    mov     dword ptr [{S + 0x3C:#x}], edx
    test    edx, edx
    je      done
    mov     edi, {CACHE:#x}
    mov     eax, -1
    mov     ecx, 0x1000
    rep stosd
    mov     eax, dword ptr [{S + 0x30:#x}]
    imul    eax, dword ptr [{S + 0x28:#x}]
    xor     edx, edx
    mov     ecx, {TN}
    div     ecx
    mov     dword ptr [{S + 0x40:#x}], eax
    mov     eax, dword ptr [{S + 0x38:#x}]
    inc     eax
    imul    eax, dword ptr [{S + 0x28:#x}]
    add     eax, {TN - 1}
    xor     edx, edx
    div     ecx
    cmp     eax, dword ptr [{S + 0x28:#x}]
    jle     dy1ok
    mov     eax, dword ptr [{S + 0x28:#x}]
dy1ok:
    mov     dword ptr [ebp+0x30], eax
    mov     eax, dword ptr [{S + 0x2C:#x}]
    imul    eax, dword ptr [{S + 0x28:#x}]
    xor     edx, edx
    div     ecx
    mov     dword ptr [ebp+0x28], eax
    mov     eax, dword ptr [{S + 0x34:#x}]
    inc     eax
    imul    eax, dword ptr [{S + 0x28:#x}]
    add     eax, {TN - 1}
    xor     edx, edx
    div     ecx
    cmp     eax, dword ptr [{S + 0x28:#x}]
    jle     dx1ok
    mov     eax, dword ptr [{S + 0x28:#x}]
dx1ok:
    mov     dword ptr [ebp+0x2C], eax
dyloop:
    mov     eax, dword ptr [{S + 0x40:#x}]
    cmp     eax, dword ptr [ebp+0x30]
    jge     done
    mov     ecx, eax
    add     ecx, dword ptr [{S + 0x24:#x}]
    mov     dword ptr [ebp+0x1C], ecx
    cmp     ecx, dword ptr [{S + 0x14:#x}]
    jl      dynext
    cmp     ecx, dword ptr [{S + 0x1C:#x}]
    jge     dynext
    imul    ecx, dword ptr [{S + 0xC:#x}]
    add     ecx, dword ptr [{S + 8:#x}]
    mov     dword ptr [ebp+0x24], ecx
    mov     eax, dword ptr [{S + 0x40:#x}]
    shl     eax, 10
    xor     edx, edx
    div     dword ptr [{S + 0x28:#x}]
    mov     dword ptr [{S + 0x48:#x}], eax
    mov     eax, dword ptr [{S + 0x40:#x}]
    inc     eax
    shl     eax, 10
    xor     edx, edx
    div     dword ptr [{S + 0x28:#x}]
    mov     ecx, dword ptr [{S + 0x48:#x}]
    inc     ecx
    cmp     eax, ecx
    jge     s1a
    mov     eax, ecx
s1a:
    cmp     eax, {TN}
    jle     s1b
    mov     eax, {TN}
s1b:
    mov     dword ptr [{S + 0x4C:#x}], eax
    mov     eax, dword ptr [ebp+0x28]
    mov     dword ptr [{S + 0x44:#x}], eax
dxloop:
    mov     eax, dword ptr [{S + 0x44:#x}]
    cmp     eax, dword ptr [ebp+0x2C]
    jge     dynext
    mov     ecx, eax
    add     ecx, dword ptr [{S + 0x20:#x}]
    mov     dword ptr [ebp+0x20], ecx
    cmp     ecx, dword ptr [{S + 0x10:#x}]
    jl      dxnext
    cmp     ecx, dword ptr [{S + 0x18:#x}]
    jge     dxnext
    shl     eax, 10
    xor     edx, edx
    div     dword ptr [{S + 0x28:#x}]
    mov     dword ptr [ebp], eax
    mov     eax, dword ptr [{S + 0x44:#x}]
    inc     eax
    shl     eax, 10
    xor     edx, edx
    div     dword ptr [{S + 0x28:#x}]
    mov     ecx, dword ptr [ebp]
    inc     ecx
    cmp     eax, ecx
    jge     t1a
    mov     eax, ecx
t1a:
    cmp     eax, {TN}
    jle     t1b
    mov     eax, {TN}
t1b:
    mov     dword ptr [ebp+4], eax
    xor     eax, eax
    mov     dword ptr [ebp+8], eax
    mov     dword ptr [ebp+0xC], eax
    mov     dword ptr [ebp+0x10], eax
    mov     dword ptr [ebp+0x14], eax
    mov     dword ptr [ebp+0x18], eax
    mov     esi, dword ptr [{S + 0x48:#x}]
syloop:
    cmp     esi, dword ptr [{S + 0x4C:#x}]
    jge     boxdone
    mov     edi, esi
    imul    edi, dword ptr [{S + 4:#x}]
    add     edi, dword ptr [{S:#x}]
    mov     ecx, dword ptr [ebp]
sxloop:
    cmp     ecx, dword ptr [ebp+4]
    jge     synext
    movzx   eax, byte ptr [edi+ecx]
    inc     dword ptr [ebp+0xC]
    cmp     eax, {KEY}
    je      sxnext
    inc     dword ptr [ebp+8]
    movzx   edx, byte ptr [eax*4+{PALETTE:#x}]
    add     dword ptr [ebp+0x10], edx
    movzx   edx, byte ptr [eax*4+{PALETTE + 1:#x}]
    add     dword ptr [ebp+0x14], edx
    movzx   edx, byte ptr [eax*4+{PALETTE + 2:#x}]
    add     dword ptr [ebp+0x18], edx
sxnext:
    inc     ecx
    jmp     sxloop
synext:
    inc     esi
    jmp     syloop
boxdone:
    mov     ecx, dword ptr [ebp+8]
    test    ecx, ecx
    je      dxnext
    lea     eax, [ecx+ecx]
    cmp     eax, dword ptr [ebp+0xC]
    jl      dxnext
    mov     eax, dword ptr [ebp+0x10]
    xor     edx, edx
    div     ecx
    mov     dword ptr [ebp+0x10], eax
    mov     eax, dword ptr [ebp+0x14]
    xor     edx, edx
    div     ecx
    mov     dword ptr [ebp+0x14], eax
    mov     eax, dword ptr [ebp+0x18]
    xor     edx, edx
    div     ecx
    mov     dword ptr [ebp+0x18], eax
    mov     eax, dword ptr [ebp+0x10]
    shr     eax, 2
    shl     eax, 6
    mov     edx, dword ptr [ebp+0x14]
    shr     edx, 2
    or      eax, edx
    shl     eax, 6
    mov     edx, dword ptr [ebp+0x18]
    shr     edx, 2
    or      eax, edx
    mov     dword ptr [ebp+0x34], eax
    mov     edx, eax
    and     edx, 0xFFF
    mov     esi, dword ptr [edx*4+{CACHE:#x}]
    mov     edi, esi
    shr     edi, 8
    cmp     edi, eax
    jne     miss
    and     esi, 0xFF
    mov     dword ptr [ebp+0x38], esi
    jmp     put
miss:
    mov     dword ptr [ebp+0x3C], 0x7FFFFFFF
    mov     eax, dword ptr [{CANDS:#x}]
    mov     dword ptr [ebp+0x38], eax
    xor     esi, esi
cand:
    cmp     esi, dword ptr [{S + 0x3C:#x}]
    jge     cdone
    mov     ecx, dword ptr [esi*4+{CANDS:#x}]
    movzx   eax, byte ptr [ecx*4+{PALETTE:#x}]
    sub     eax, dword ptr [ebp+0x10]
    imul    eax, eax
    mov     edi, eax
    movzx   eax, byte ptr [ecx*4+{PALETTE + 1:#x}]
    sub     eax, dword ptr [ebp+0x14]
    imul    eax, eax
    add     edi, eax
    movzx   eax, byte ptr [ecx*4+{PALETTE + 2:#x}]
    sub     eax, dword ptr [ebp+0x18]
    imul    eax, eax
    add     edi, eax
    cmp     edi, dword ptr [ebp+0x3C]
    jge     cnext
    mov     dword ptr [ebp+0x3C], edi
    mov     dword ptr [ebp+0x38], ecx
cnext:
    inc     esi
    jmp     cand
cdone:
    mov     eax, dword ptr [ebp+0x34]
    mov     edx, eax
    and     edx, 0xFFF
    shl     eax, 8
    or      eax, dword ptr [ebp+0x38]
    mov     dword ptr [edx*4+{CACHE:#x}], eax
put:
    mov     eax, dword ptr [ebp+0x38]
    mov     ecx, dword ptr [ebp+0x24]
    add     ecx, dword ptr [ebp+0x20]
    mov     byte ptr [ecx], al
dxnext:
    inc     dword ptr [{S + 0x44:#x}]
    jmp     dxloop
dynext:
    inc     dword ptr [{S + 0x40:#x}]
    jmp     dyloop
done:
    add     esp, 0x40
    popad
    ret     0xC
"""


# ==== dw_scale: backdrop at device density =========================================
def asm_dw_build() -> str:
    # call-redirect @0x43E9DF (`mov ecx,esi; call DesignWin_build`): build, then the backdrop (esi = DesignWin).
    return f"""
    pop     eax
    mov     dword ptr [{CELL['g_dw_ret2']:#x}], eax
    push    thunk_dw_build2
    jmp     {BUILD:#x}
"""


def asm_dw_build2() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     xout
    mov     ecx, esi
    call    thunk_dw_backdrop
xout:
    jmp     dword ptr [{CELL['g_dw_ret2']:#x}]
"""


def asm_dw_backdrop() -> str:
    """CALL helper (ecx = DesignWin): deswin.pcx (the window's pcx Buffer +0x13C6C, 623x368) re-rendered at
    device density into the window canvas (+0x444) rows < H = s(368), W = ceil(623 g/16), then the pcx Buffer
    is resized to W x canvasH and refilled from the canvas (the painters restore box backgrounds from it).
    Port of the proto's renderBackdrop (D1/D2/D6):
      families  = indices with 50*cnt >= sw*sh and max vertical run <= 2 (not the key 9)
      variants  = non-family indices with cnt >= 40, >= 95% on one row parity, >= 80% sandwiched by one family
      strokes   = rows/cols with an ink (non-key, non-family, non-variant) run >= 60
      axis maps = line_axis_map (every stroke row/col renders at K, the field by distribute)
      pixels    = a family/variant pixel with a different family/variant member directly above or below is a
                  dither pair -> stripe_top(yd) ? even-row colour : odd-row colour (P-law); else NN.
    Registers preserved (pushad).  Native no-op at g<=16 (the caller gates)."""
    # frame (ebp): +0 src +4 sp +8 sw +0xC sh +0x10 W +0x14 H +0x18 cdata +0x1C cp +0x20 cw +0x24 ch +0x28 K
    #  +0x2C P +0x30 hN +0x34 g +0x38 obj +0x3C n_l +0x40 n_f +0x44 rem +0x48 fi +0x4C yd +0x50 ys +0x54 hy
    #  +0x58 xd +0x5C xs +0x60 wx +0x64 Hc(=min(H,ch)) +0x68 rowptr +0x6C prev +0x70 run +0x74 out +0x78 pcx
    #  +0x7C tmp +0x80 N(sw*sh) +0x84 top
    cnt, vrun, cntE, cntS, FAM, VAR, lrow, lcol = (BD[k] for k in ("cnt", "vrun", "cntE", "cntS", "FAM", "VAR", "lrow", "lcol"))
    return f"""
    pushad
    sub     esp, 0x90
    mov     ebp, esp
    mov     dword ptr [ebp+0x38], ecx
    lea     ebx, [ecx+0x13C6C]
    mov     dword ptr [ebp+0x78], ebx
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    je      done
    mov     dword ptr [ebp], eax
    mov     eax, dword ptr [ebx+0x80]
    cmp     eax, 623
    jne     done
    mov     dword ptr [ebp+8], eax
    mov     edx, dword ptr [ebx+0x84]
    neg     edx
    cmp     edx, 368
    jne     done
    mov     dword ptr [ebp+0xC], edx
    imul    edx, eax
    mov     dword ptr [ebp+0x80], edx
    mov     edx, dword ptr [ebx+0x4A8]
    cmp     edx, eax
    jl      sp4
    lea     ecx, [eax+8]
    cmp     edx, ecx
    jle     spok
sp4:
    lea     edx, [eax+3]
    and     edx, -4
spok:
    mov     dword ptr [ebp+4], edx
    mov     ebx, dword ptr [ebp+0x38]
    add     ebx, 0x444
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    je      done
    mov     dword ptr [ebp+0x18], eax
    mov     eax, dword ptr [ebx+0x80]
    test    eax, eax
    jle     done
    mov     dword ptr [ebp+0x20], eax
    mov     edx, dword ptr [ebx+0x84]
    neg     edx
    test    edx, edx
    jle     done
    mov     dword ptr [ebp+0x24], edx
    mov     edx, dword ptr [ebx+0x4A8]
    cmp     edx, eax
    jl      cp4
    lea     ecx, [eax+8]
    cmp     edx, ecx
    jle     cpok
cp4:
    lea     edx, [eax+3]
    and     edx, -4
cpok:
    mov     dword ptr [ebp+0x1C], edx
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [ebp+0x34], eax
    mov     ecx, dword ptr [ebp+8]
    imul    ecx, eax
    add     ecx, 15
    sar     ecx, 4
    mov     dword ptr [ebp+0x10], ecx
    mov     ecx, dword ptr [ebp+0xC]
    imul    ecx, eax
    lea     ecx, [ecx*2+15]
    sar     ecx, 5
    mov     dword ptr [ebp+0x14], ecx
    cmp     ecx, dword ptr [ebp+0x24]
    jle     hc
    mov     ecx, dword ptr [ebp+0x24]
hc:
    mov     dword ptr [ebp+0x64], ecx
    lea     ecx, [eax*2+15]
    sar     ecx, 5
    mov     dword ptr [ebp+0x28], ecx
    mov ecx, dword ptr [0x66879c]
    mov     dword ptr [ebp+0x2C], ecx
    inc     ecx
    sar     ecx, 1
    mov     dword ptr [ebp+0x30], ecx
    mov     edi, {cnt:#x}
    xor     eax, eax
    mov     ecx, 0x600
    rep stosd
    xor     ecx, ecx
cnx:
    cmp     ecx, dword ptr [ebp+8]
    jge     cx_end
    mov     dword ptr [ebp+0x6C], 256
    mov     dword ptr [ebp+0x70], 0
    mov     esi, dword ptr [ebp]
    add     esi, ecx
    xor     edx, edx
cny:
    cmp     edx, dword ptr [ebp+0xC]
    jge     cy_end
    movzx   eax, byte ptr [esi]
    inc     dword ptr [eax*4+{cnt:#x}]
    cmp     eax, dword ptr [ebp+0x6C]
    jne     newrun
    inc     dword ptr [ebp+0x70]
    jmp     runok
newrun:
    mov     dword ptr [ebp+0x70], 1
    mov     dword ptr [ebp+0x6C], eax
runok:
    mov     edi, dword ptr [ebp+0x70]
    cmp     edi, dword ptr [eax*4+{vrun:#x}]
    jle     vok
    mov     dword ptr [eax*4+{vrun:#x}], edi
vok:
    add     esi, dword ptr [ebp+4]
    inc     edx
    jmp     cny
cy_end:
    inc     ecx
    jmp     cnx
cx_end:
    xor     ecx, ecx
fam:
    cmp     ecx, {KEY}
    je      famn
    mov     eax, dword ptr [ecx*4+{cnt:#x}]
    imul    eax, eax, 50
    cmp     eax, dword ptr [ebp+0x80]
    jl      famn
    cmp     dword ptr [ecx*4+{vrun:#x}], 2
    jg      famn
    mov     byte ptr [ecx+{FAM:#x}], 1
famn:
    inc     ecx
    cmp     ecx, 256
    jl      fam
    xor     edx, edx
vy:
    cmp     edx, dword ptr [ebp+0xC]
    jge     vy_end
    mov     esi, edx
    imul    esi, dword ptr [ebp+4]
    add     esi, dword ptr [ebp]
    xor     ecx, ecx
vx:
    cmp     ecx, dword ptr [ebp+8]
    jge     vx_end
    movzx   eax, byte ptr [esi+ecx]
    cmp     eax, {KEY}
    je      vxn
    cmp     byte ptr [eax+{FAM:#x}], 0
    jne     vxn
    test    edx, 1
    jne     vodd
    inc     dword ptr [eax*4+{cntE:#x}]
vodd:
    test    edx, edx
    je      vxn
    mov     edi, dword ptr [ebp+0xC]
    dec     edi
    cmp     edx, edi
    jge     vxn
    mov     edi, esi
    sub     edi, dword ptr [ebp+4]
    movzx   edi, byte ptr [edi+ecx]
    mov     ebx, esi
    add     ebx, dword ptr [ebp+4]
    movzx   ebx, byte ptr [ebx+ecx]
    cmp     edi, ebx
    jne     vxn
    cmp     byte ptr [edi+{FAM:#x}], 0
    je      vxn
    inc     dword ptr [eax*4+{cntS:#x}]
vxn:
    inc     ecx
    jmp     vx
vx_end:
    inc     edx
    jmp     vy
vy_end:
    xor     ecx, ecx
var:
    cmp     ecx, {KEY}
    je      varn
    cmp     byte ptr [ecx+{FAM:#x}], 0
    jne     varn
    mov     eax, dword ptr [ecx*4+{cnt:#x}]
    cmp     eax, 40
    jl      varn
    mov     edx, dword ptr [ecx*4+{cntE:#x}]
    mov     edi, eax
    sub     edi, edx
    cmp     edx, edi
    jge     vmax
    mov     edx, edi
vmax:
    imul    edx, edx, 20
    mov     edi, eax
    imul    edi, edi, 19
    cmp     edx, edi
    jl      varn
    mov     edx, dword ptr [ecx*4+{cntS:#x}]
    imul    edx, edx, 5
    mov     edi, eax
    shl     edi, 2
    cmp     edx, edi
    jl      varn
    mov     byte ptr [ecx+{VAR:#x}], 1
varn:
    inc     ecx
    cmp     ecx, 256
    jl      var
    xor     edx, edx
ly:
    cmp     edx, dword ptr [ebp+0xC]
    jge     ly_end
    mov     esi, edx
    imul    esi, dword ptr [ebp+4]
    add     esi, dword ptr [ebp]
    xor     ecx, ecx
    xor     edi, edi
lx:
    cmp     ecx, dword ptr [ebp+8]
    jge     lxe
    movzx   eax, byte ptr [esi+ecx]
    cmp     eax, {KEY}
    je      lbrk
    cmp     byte ptr [eax+{FAM:#x}], 0
    jne     lbrk
    cmp     byte ptr [eax+{VAR:#x}], 0
    jne     lbrk
    inc     edi
    cmp     edi, 60
    jl      lxn
    mov     byte ptr [edx+{lrow:#x}], 1
    jmp     lxe
lbrk:
    xor     edi, edi
lxn:
    inc     ecx
    jmp     lx
lxe:
    inc     edx
    jmp     ly
ly_end:
    xor     ecx, ecx
lcx:
    cmp     ecx, dword ptr [ebp+8]
    jge     lcx_end
    mov     esi, dword ptr [ebp]
    add     esi, ecx
    xor     edx, edx
    xor     edi, edi
lcy:
    cmp     edx, dword ptr [ebp+0xC]
    jge     lcye
    movzx   eax, byte ptr [esi]
    cmp     eax, {KEY}
    je      lcbrk
    cmp     byte ptr [eax+{FAM:#x}], 0
    jne     lcbrk
    cmp     byte ptr [eax+{VAR:#x}], 0
    jne     lcbrk
    inc     edi
    cmp     edi, 60
    jl      lcyn
    mov     byte ptr [ecx+{lcol:#x}], 1
    jmp     lcye
lcbrk:
    xor     edi, edi
lcyn:
    add     esi, dword ptr [ebp+4]
    inc     edx
    jmp     lcy
lcye:
    inc     ecx
    jmp     lcx
lcx_end:
    push    {lrow:#x}
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0xC]
    call    thunk_dw_axismap
    test    eax, eax
    je      done
    push    {lcol:#x}
    push    dword ptr [ebp+0x10]
    push    dword ptr [ebp+8]
    call    thunk_dw_axismap
    test    eax, eax
    je      done
    mov     dword ptr [ebp+0x4C], 0
    mov     dword ptr [ebp+0x50], 0
ry:
    mov     edx, dword ptr [ebp+0x50]
    cmp     edx, dword ptr [ebp+0xC]
    jge     rend
    movzx   eax, byte ptr [edx+{lrow:#x}]
    mov     dword ptr [ebp+0x54], eax
rrep:
    cmp     dword ptr [ebp+0x54], 0
    je      rynext
    dec     dword ptr [ebp+0x54]
    mov     eax, dword ptr [ebp+0x4C]
    cmp     eax, dword ptr [ebp+0x64]
    jge     rend
    xor     edx, edx
    div     dword ptr [ebp+0x2C]
    xor     eax, eax
    cmp     edx, dword ptr [ebp+0x30]
    jge     ntop
    inc     eax
ntop:
    mov     dword ptr [ebp+0x84], eax
    mov     edi, dword ptr [ebp+0x4C]
    imul    edi, dword ptr [ebp+0x1C]
    add     edi, dword ptr [ebp+0x18]
    mov     esi, dword ptr [ebp+0x50]
    imul    esi, dword ptr [ebp+4]
    add     esi, dword ptr [ebp]
    mov     dword ptr [ebp+0x68], esi
    mov     dword ptr [ebp+0x58], 0
    mov     dword ptr [ebp+0x5C], 0
rx:
    mov     ecx, dword ptr [ebp+0x5C]
    cmp     ecx, dword ptr [ebp+8]
    jge     rxend
    movzx   edx, byte ptr [ecx+{lcol:#x}]
    mov     dword ptr [ebp+0x60], edx
    mov     esi, dword ptr [ebp+0x68]
    movzx   eax, byte ptr [esi+ecx]
    mov     dword ptr [ebp+0x74], eax
    cmp     byte ptr [eax+{FAM:#x}], 0
    jne     fl
    cmp     byte ptr [eax+{VAR:#x}], 0
    je      emit
fl:
    mov     ebx, 256
    cmp     dword ptr [ebp+0x50], 0
    je      tdn
    mov     ebx, esi
    sub     ebx, dword ptr [ebp+4]
    movzx   ebx, byte ptr [ebx+ecx]
    cmp     ebx, eax
    je      tdn
    cmp     byte ptr [ebx+{FAM:#x}], 0
    jne     mate
    cmp     byte ptr [ebx+{VAR:#x}], 0
    jne     mate
tdn:
    mov     edx, dword ptr [ebp+0x50]
    inc     edx
    cmp     edx, dword ptr [ebp+0xC]
    jge     emit
    mov     ebx, esi
    add     ebx, dword ptr [ebp+4]
    movzx   ebx, byte ptr [ebx+ecx]
    cmp     ebx, eax
    je      emit
    cmp     byte ptr [ebx+{FAM:#x}], 0
    jne     mate
    cmp     byte ptr [ebx+{VAR:#x}], 0
    je      emit
mate:
    mov     edx, dword ptr [ebp+0x50]
    and     edx, 1
    xor     edx, dword ptr [ebp+0x84]
    test    edx, edx
    jne     emit
    mov     dword ptr [ebp+0x74], ebx
emit:
    mov     eax, dword ptr [ebp+0x74]
    mov     ecx, dword ptr [ebp+0x60]
    mov     edx, dword ptr [ebp+0x58]
    add     edx, ecx
    cmp     edx, dword ptr [ebp+0x20]
    jle     wfit
    mov     ecx, dword ptr [ebp+0x20]
    sub     ecx, dword ptr [ebp+0x58]
    jle     rxend
wfit:
    push    edi
    add     edi, dword ptr [ebp+0x58]
    rep stosb
    pop     edi
    mov     eax, dword ptr [ebp+0x60]
    add     dword ptr [ebp+0x58], eax
    inc     dword ptr [ebp+0x5C]
    jmp     rx
rxend:
    inc     dword ptr [ebp+0x4C]
    jmp     rrep
rynext:
    inc     dword ptr [ebp+0x50]
    jmp     ry
rend:
    push    dword ptr [ebp+0x24]
    push    dword ptr [ebp+0x10]
    mov     ecx, dword ptr [ebp+0x78]
    call    {BUFFER_RESIZE:#x}
    mov     ebx, dword ptr [ebp+0x78]
    mov     eax, dword ptr [ebx+0x80]
    cmp     eax, dword ptr [ebp+0x10]
    jne     done
    mov     edx, dword ptr [ebx+0x84]
    neg     edx
    cmp     edx, dword ptr [ebp+0x24]
    jne     done
    mov     edx, dword ptr [ebx+0x4A8]
    cmp     edx, eax
    jl      pp4
    lea     ecx, [eax+8]
    cmp     edx, ecx
    jle     ppok
pp4:
    lea     edx, [eax+3]
    and     edx, -4
ppok:
    mov     dword ptr [ebp+4], edx
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    je      done
    mov     dword ptr [ebp], eax
    mov     ecx, dword ptr [ebp+0x10]
    cmp     ecx, dword ptr [ebp+0x20]
    jle     cwok
    mov     ecx, dword ptr [ebp+0x20]
cwok:
    mov     dword ptr [ebp+0x7C], ecx
    xor     edx, edx
cprow:
    cmp     edx, dword ptr [ebp+0x24]
    jge     done
    mov     esi, edx
    imul    esi, dword ptr [ebp+0x1C]
    add     esi, dword ptr [ebp+0x18]
    mov     edi, edx
    imul    edi, dword ptr [ebp+4]
    add     edi, dword ptr [ebp]
    mov     ecx, dword ptr [ebp+0x7C]
    rep movsb
    inc     edx
    jmp     cprow
done:
    add     esp, 0x90
    popad
    ret
"""


def asm_dw_axismap() -> str:
    """CALL helper: (src_n, dst_n, flags*) RET 0xC; law line_axis_map in place: flags[i] (1 = stroke) becomes
    the WIDTH of source cell i (K for strokes, distribute(rem, n_f) for the field: cum(i) = half_down(i*rem, n_f)).
    eax = 1 ok / 0 = the field cannot get >= 1 px per cell (the caller then renders nothing)."""
    # locals: [esp] K [esp+4] rem [esp+8] n_f [esp+0xC] fi [esp+0x10] i; args [esp+0x28] src_n [esp+0x2C] dst_n [esp+0x30] flags
    return f"""
    push    ebx
    push    esi
    push    edi
    push    ebp
    sub     esp, 0x14
    mov     eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5
    mov     dword ptr [esp], eax
    mov     esi, dword ptr [esp+0x28]
    mov     edi, dword ptr [esp+0x30]
    xor     ecx, ecx
    xor     edx, edx
cnt:
    cmp     ecx, esi
    jge     cnt_end
    movzx   eax, byte ptr [edi+ecx]
    add     edx, eax
    inc     ecx
    jmp     cnt
cnt_end:
    mov     ebx, esi
    sub     ebx, edx
    mov     dword ptr [esp+8], ebx
    mov     eax, edx
    imul    eax, dword ptr [esp]
    mov     ecx, dword ptr [esp+0x2C]
    sub     ecx, eax
    mov     dword ptr [esp+4], ecx
    test    ebx, ebx
    jne     field
    test    ecx, ecx
    jne     fail
    jmp     fill
field:
    cmp     ecx, ebx
    jl      fail
fill:
    mov     dword ptr [esp+0xC], 0
    mov     dword ptr [esp+0x10], 0
fl:
    mov     ecx, dword ptr [esp+0x10]
    cmp     ecx, esi
    jge     ok
    cmp     byte ptr [edi+ecx], 0
    je      fcell
    mov     eax, dword ptr [esp]
    mov     byte ptr [edi+ecx], al
    jmp     fnext
fcell:
    mov     ebx, dword ptr [esp+8]
    add     ebx, ebx
    mov     eax, dword ptr [esp+0xC]
    inc     eax
    imul    eax, dword ptr [esp+4]
    add     eax, eax
    add     eax, dword ptr [esp+8]
    dec     eax
    xor     edx, edx
    div     ebx
    mov     ebp, eax
    mov     eax, dword ptr [esp+0xC]
    imul    eax, dword ptr [esp+4]
    add     eax, eax
    add     eax, dword ptr [esp+8]
    dec     eax
    xor     edx, edx
    div     ebx
    sub     ebp, eax
    mov     eax, ebp
    mov     ecx, dword ptr [esp+0x10]
    mov     byte ptr [edi+ecx], al
    inc     dword ptr [esp+0xC]
fnext:
    inc     dword ptr [esp+0x10]
    jmp     fl
ok:
    mov     eax, 1
    jmp     xout
fail:
    xor     eax, eax
xout:
    add     esp, 0x14
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    ret     0xC
"""


# ==== picker_grid_leave_present ======================================================
def asm_dw_gridleave() -> str:
    # call-redirect @0x433914 (`call PartPicker_draw_cell(hover, 0)`, esi = picker): draw, then vtbl+0xFC present.
    # eax/ecx/edx are dead after the site (two stores + pops + ret).  Runs at every g (vanilla bug).
    return f"""
    pop     edx
    mov     dword ptr [{CELL['g_dw_ret4']:#x}], edx
    call    {PK_DRAWCELL:#x}
    mov     ecx, esi
    mov     edx, dword ptr [esi]
    call    dword ptr [edx+0xFC]
    jmp     dword ptr [{CELL['g_dw_ret4']:#x}]
"""


# ==== popup_listbox_reserve ==========================================================
def asm_lbres(reg: str) -> str:
    # v3 (2026-09-26q): the popup test is the shared thunk_list_gate (g_popup_active || g_filedlg_active):
    # the MAIN-MENU LOAD list (flags 0x80020, no rail style 0x40) builds the same heap V bar as the popups
    # (ScrollBar_init_v @0x5EC427, x = w - g_scrollbar_w) and every one of these reads stayed native there
    # (probe frida_filedlg_heapbar_20260927T0542xx: 20-px bar at 4K and 1600).  2 bytes SHORTER, slots unchanged.
    # v2 (2026-09-26): SHARED-FIELD ONE OWNER -- inside the HQ report console-list bracket (g_rw_inlist == 1) the
    # writer t_rw_scrollsmall already holds g_scrollbar_w = s(12); a PROFILE opened from the diplomacy talk runs
    # inside the talk popup's exec_3 loop (g_popup_active >= 1), so these readers scaled it AGAIN (bar 75 px at 4K,
    # the BASES count column 45 px left, the list child window 45 px past the panel frame).  Pass it raw there.
    return f"""
    mov     {reg}, dword ptr [{G_SBW:#x}]
    cmp     dword ptr [{G_RW_INLIST:#x}], 0
    jne     xout
    call    {T_LIST_GATE:#x}
    je      xout
    cmp     dword ptr [{G:#x}], 16
    jle     xout
    imul    {reg}, dword ptr [{G:#x}]
    sar     {reg}, 4
xout:
    ret
"""


def asm_dw_sbv() -> str:
    # call-helper @0x5EC42C (`mov ecx,[esi+0x43c]` after ScrollBar_init_v; flags dead): register the heap bar.
    return f"""
    mov     ecx, dword ptr [esi+0x43c]
    call    {T_LIST_GATE:#x}
    je      xout
    cmp     dword ptr [{G:#x}], 16
    jle     xout
    test    ecx, ecx
    je      xout
    cmp     dword ptr [ecx], {SB_VTBL:#x}
    jne     xout
    mov     dword ptr [{G_RAIL_SB:#x}], ecx
xout:
    ret
"""


def asm_dw_hide() -> str:
    # call-redirect @0x404A84 (Popup_hide's first call, esi = popup; eax dead): clear g_rail_sb if it is this popup's bar.
    return f"""
    mov     eax, dword ptr [esi+0x2794]
    test    eax, eax
    je      go
    cmp     eax, dword ptr [{G_RAIL_SB:#x}]
    jne     go
    mov     dword ptr [{G_RAIL_SB:#x}], 0
go:
    jmp     {HIDE_TARGET:#x}
"""


LBRES_SITES = [   # (id, site, reg, len)  -- every g_scrollbar_w consumer in the popup-list path (v15c/v15d/v15j)
    ("LBR1", 0x60A632, "ecx", 6), ("LBR2", 0x60A609, "ecx", 6), ("LBR3", 0x60A650, "eax", 5),
    ("GW1", 0x5D503E, "ecx", 6), ("GW2", 0x5D51EB, "ecx", 6), ("GW3", 0x5D6246, "ecx", 6), ("WC1", 0x5EC342, "ebp", 6), ("WC2", 0x5EC3F5, "ecx", 6),
    ("CV1", 0x5EEE95, "edx", 6), ("CV2", 0x5EEEAA, "edx", 6), ("CV3", 0x5EEF85, "edx", 6), ("CV4", 0x5EEF9A, "edx", 6),
    ("CV5", 0x5EF066, "eax", 5), ("CV6", 0x5EF07C, "edx", 6), ("CV7", 0x5EF126, "eax", 5), ("CV8", 0x5EF13C, "edx", 6),
    ("SBI", 0x6058E9, "edx", 6), ("SBIV", 0x605938, "eax", 5),
    # 2026-09-26q: calc_dims FIXED-BOX branch (flags&1, no rail style 0x40) -- w5c = [+0x2C] - sbw @0x60A532 /
    # h60 twin @0x60A50F; vanilla nets them to zero with LBR1/LBR2's += sbw.  Native here + scaled there grew the
    # main-menu LOAD list window by s(20)-20 and pushed its heap bar over the frame (pristine LoadMainMenu.png:
    # bar INSIDE the rect, window-local 299..319 = rect R).
    ("CD1", 0x60A50F, "edx", 6), ("CD2", 0x60A532, "edx", 6),
]
LBRES_MODRM = {"ecx": 0x0D, "ebp": 0x2D, "edx": 0x15}


def lbres_native(reg: str) -> bytes:
    if reg == "eax":
        return bytes([0xA1]) + struct.pack("<I", G_SBW)
    return bytes([0x8B, LBRES_MODRM[reg]]) + struct.pack("<I", G_SBW)


# ==== wheel_scroll ====================================================================
VT_PART, VT_PROD, VT_POPUP, VT_POPUP2, VT_FILEDLG, VT_TEXTSCROLL, VT_PREFSUB = 0x66B2B8, 0x66A250, 0x6695C8, 0x66A8A8, 0x669EC8, 0x66ADC8, 0x66C3D8


def asm_wheel(do_press: bool) -> str:
    press = f"""
    mov     ebx, 1
    cmp     edx, 0x26
    je      press
    mov     ebx, 2
press:
    push    ebx
    mov     ecx, edi
    call    {CHEVRON:#x}
    mov     edx, dword ptr [esi]
    mov     ecx, esi
    call    dword ptr [edx+0xFC]
""" if do_press else ""
    return f"""
    call    {GET_TARGET:#x}
    test    eax, eax
    jz      xout
    cmp     dword ptr [esp+0x6C], 0
    jne     xout
    mov     edx, dword ptr [esp+0x68]
    cmp     edx, 0x26
    je      go
    cmp     edx, 0x28
    jne     xout
go:
    push    ebx
    push    esi
    push    edi
    mov     esi, dword ptr [{BASEPOP:#x}]
    test    esi, esi
    jnz     cls
    mov     esi, dword ptr [{MODAL_TOP:#x}]
    test    esi, esi
    jz      restore
cls:
    mov     ecx, dword ptr [esi]
    cmp     ecx, {VT_POPUP:#x}
    je      popc
    cmp     ecx, {VT_POPUP2:#x}
    je      popc
    lea     edi, [esi+0xA14]
    cmp     ecx, {VT_PART:#x}
    je      have
    lea     edi, [esi+0x7120]
    cmp     ecx, {VT_PROD:#x}
    je      have
    cmp     ecx, {VT_FILEDLG:#x}
    jne     notfd
    call    {T_FD_WHEELBAR:#x}
    jmp     have
notfd:
    lea     edi, [esi+0xA20]
    cmp     ecx, {VT_TEXTSCROLL:#x}
    je      have
    lea     edi, [esi+0xEF0]
    cmp     ecx, {VT_PREFSUB:#x}
    je      have
    jmp     restore
popc:
    mov     edi, dword ptr [esi+0x2794]
    test    edi, edi
    jz      restore
have:
    cmp     dword ptr [edi+0xC4], 0
    je      restore
    mov     ecx, dword ptr [edi+0xA24]
    cmp     ecx, dword ptr [edi+0xA20]
    jle     restore
{press}
    xor     eax, eax
    pop     edi
    pop     esi
    pop     ebx
    ret
restore:
    pop     edi
    pop     esi
    pop     ebx
xout:
    ret
"""


# ==== in-place cave upgrades (proto v15g bytes, Unicorn-checked in scratch nest_childx_v2.py) ===
NESTPADS_V1 = bytes.fromhex("53 8B 1D 40 87 66 00 83 FB 10 7F 07 BB 03 00 00 00 EB 06 8D 1C 5B C1 EB 04 29 D8 01 D9 89 45 DC 29 DA 01 DF 5B C3".replace(" ", ""))
NESTPADS_V2 = bytes.fromhex("53 8B 1D 40 87 66 00 83 FB 10 7F 07 BB 03 00 00 00 EB 08 01 DB 83 C3 07 C1 EB 04 29 D8 01 D9 89 45 DC 29 DA 01 DF 5B C3".replace(" ", ""))
CHILDX_V1 = bytes.fromhex("52 A1 40 87 66 00 83 F8 10 7E 2F 8B 96 AC 30 00 00 81 EA 20 4E 00 00 81 FA 10 27 00 00 72 0E 81 EA 40 9C 00 00 81 FA 10 27 00 00 73 0D 8D 14 40 C1 FA 04 83 EA 03 01 54 24 18 5A 83 BE 50 23 00 00 FF C3".replace(" ", ""))
CHILDX_V2 = bytes.fromhex("52 A1 40 87 66 00 83 F8 10 7E 38 8B 96 AC 30 00 00 81 EA 20 4E 00 00 81 FA 10 27 00 00 72 0E 81 EA 40 9C 00 00 81 FA 10 27 00 00 73 16 83 BE E0 30 00 00 00 74 0D 8D 14 40 C1 FA 04 83 EA 03 01 54 24 18 5A 83 BE 50 23 00 00 FF C3".replace(" ", ""))
assert len(NESTPADS_V1) == 38 and len(NESTPADS_V2) == 40 and len(CHILDX_V1) == 67 and len(CHILDX_V2) == 76
INPLACE = [   # (content id, offset, new bytes fn, max size)
    # thunk_popup_nestpads v2 (NESTPADS_V2, this file) -> v3 = v2 + the body-only ring arm, RELOCATED to the pcave2 tail by
    # assemble_untitled_popup.py (2026-09-18); the 0x3770 slot is padding now. NESTPADS_V2 stays as the v2 reference
    # (its list-law arithmetic is byte-for-byte the v3 `listpad` arm).
    ("thunk_orn_childx", 0xFB90, lambda: CHILDX_V2, 0x50),
    # thunk_btn_gate_pre v4 (this file) -> v5 = rw report prefix + this v4 VERBATIM, RELOCATED to the rw region by
    # assemble_rw.py (2026-09-04 HQ report screens bake); the 0x16DA0 slot is padding now. asm_btn_gate_pre_v4() stays
    # the body source for v5 and is parity-tested there.
]


# ---- layout / assembly ------------------------------------------------------
NEW_THUNKS = [   # (name, asm fn, group) -- laid out consecutively from OFF_CODE, 16-aligned
    ("thunk_dw_enter", asm_dw_enter, "dw_scale"),
    ("thunk_dw_immfix", asm_dw_immfix, "dw_scale"),
    ("thunk_dw_leave", asm_dw_leave, "dw_scale"),
    ("thunk_dw_pk_enter", asm_dw_pk_enter, "dw_scale"),
    ("thunk_dw_pk_leave", asm_dw_pk_leave, "dw_scale"),
    ("thunk_dw_cell", asm_dw_cell, "dw_scale"),
    ("thunk_dw_click", asm_dw_click, "dw_scale"),
    ("thunk_dw_frame", asm_dw_frame, "dw_scale"),
    ("thunk_dw_bm", asm_dw_bm, "dw_scale"),
    ("thunk_dw_restripe", asm_dw_restripe, "dw_scale"),
    ("thunk_dw_pickcell", asm_dw_pickcell, "dw_scale"),
    ("thunk_dw_container", asm_dw_container, "dw_scale"),
    ("thunk_dw_tilecell", asm_dw_tilecell, "dw_scale"),
    ("thunk_dw_slotcell", asm_dw_slotcell, "dw_scale"),
    ("thunk_dw_btndraw", asm_dw_btndraw, "dw_scale"),
    ("thunk_dw_btnface", asm_dw_btnface, "dw_scale"),
    ("thunk_dw_ssaa", asm_dw_ssaa, "dw_scale"),
    ("thunk_dw_shim", asm_dw_shim, "dw_scale"),
    ("thunk_dw_ovl", asm_dw_ovl, "dw_scale"),
    ("thunk_dw_ewin", asm_dw_ewin, "dw_scale"),
    ("thunk_dw_eovl", asm_dw_eovl, "dw_scale"),
    ("thunk_dw_ehalfa", asm_dw_ehalfa, "dw_scale"),
    ("thunk_dw_ehalfb", asm_dw_ehalfb, "dw_scale"),
    ("thunk_dw_fp", asm_dw_fp, "dw_scale"),
    ("thunk_dw_fp2", asm_dw_fp2, "dw_scale"),
    ("thunk_dw_fpset", asm_dw_fpset, "dw_scale"),
    ("thunk_dw_clip", asm_dw_clip, "dw_scale"),
    ("thunk_dw_resetguard", asm_dw_resetguard, "dw_scale"),
    ("thunk_dw_fit", asm_dw_fit, "dw_scale"),
    ("thunk_dw_axismap", asm_dw_axismap, "dw_scale"),
    ("thunk_dw_backdrop", asm_dw_backdrop, "dw_scale"),
    ("thunk_dw_build", asm_dw_build, "dw_scale"),
    ("thunk_dw_build2", asm_dw_build2, "dw_scale"),
    ("thunk_dw_gridleave", asm_dw_gridleave, "picker_grid_leave_present"),
    ("thunk_lbres_ecx", lambda: asm_lbres("ecx"), "popup_listbox_reserve"),
    ("thunk_lbres_eax", lambda: asm_lbres("eax"), "popup_listbox_reserve"),
    ("thunk_lbres_ebp", lambda: asm_lbres("ebp"), "popup_listbox_reserve"),
    ("thunk_lbres_edx", lambda: asm_lbres("edx"), "popup_listbox_reserve"),
    ("thunk_dw_sbv", asm_dw_sbv, "popup_listbox_reserve"),
    ("thunk_dw_hide", asm_dw_hide, "popup_listbox_reserve"),
    ("thunk_wheel_down", lambda: asm_wheel(True), "wheel_scroll"),
    ("thunk_wheel_up", lambda: asm_wheel(False), "wheel_scroll"),
]
DATA = [("g_dw_immtab", OFF_IMMTAB, immtab_bytes)]

assemble = SE.assemble


def assemble_all() -> tuple[dict[str, tuple[int, bytes]], int]:
    layout: dict[str, tuple[int, bytes]] = {}
    names = {n: PCAVE2 + OFF_CODE for n, _, _ in NEW_THUNKS}
    names.update(SE_HELPERS)
    for _pass in range(4):
        off = OFF_CODE
        new_names = {}
        for name, fn, _g in NEW_THUNKS:
            va = PCAVE2 + off
            try:
                b = assemble(fn(), va, names)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"{name}: {e}") from e
            layout[name] = (off, b)
            new_names[name] = va
            off = (off + len(b) + 15) & ~15
        new_names.update(SE_HELPERS)
        if new_names == names:
            break
        names = new_names
    else:
        raise RuntimeError("thunk layout did not converge")
    end = off
    for name, o, fn in DATA:
        layout[name] = (o, fn())
    return layout, end


SYM_ABS = {
    G: "g_popup_scale_num", BTN_GATE: "thunk_btn_gate", STR_K32: "g_ed_str_k32", STR_VP: "g_ed_str_vp",
    HOLLOWFLAT: "thunk_box_thick_hollow_flat", BOX_SPRITE: "Buffer_box_sprite",
    G_POPUP_ACTIVE: "g_popup_active", G_RAIL_SB: "g_rail_sb",
    **{va: n for n, va in SE_HELPERS.items()},
    G_IMMTAB: "g_dw_immtab",
}   # RAIL_GATE_IMM (thunk_rail_gate4+5) stays a LITERAL: a symbol into code would overlap the content entry
EXTRA_SYMS = {PCAVE2 + o: n for n, o, _ in CELLS}
EXTRA_SYMS[G_IMMTAB] = "g_dw_immtab"
def templatize(b: bytes, va: int) -> str:
    """SE.templatize + interior cell offsets (`{abs32:sym}` cannot carry +off -> emit them LITERAL: the cave
    section VA is frozen at 0xA0C000 and the offsets are fixed by this file)."""
    syms = dict(SYM_ABS)
    syms.update(EXTRA_SYMS)
    return SE.templatize(b, va, syms)


def base_exe_bytes(va: int, n: int) -> bytes:
    return SE.base_exe_bytes(va, n)


def rel32(site: int, target: int) -> str:
    return SE.rel32(site, target)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- sites -------------------------------------------------------------------
def site_list(names: dict[str, int] | None = None) -> list[dict]:
    """Every exe site: dict(id, group, function, va, orig(bytes), new(template str), pattern, note).
    E8 redirects carry {rel32:} placeholders; E9 detours carry a LITERAL rel32 (the patcher's template
    grammar allows rel32 only after E8; the pcave2 VA and every thunk offset are frozen by this file)."""
    if not names:
        layout, _end = assemble_all()
        names = {n: PCAVE2 + layout[n][0] for n, _f, _g in NEW_THUNKS}
    S = []

    def add(sid, group, fn, va, orig, new, pattern, note=""):
        S.append({"id": sid, "group": group, "function": fn, "va": va, "orig": orig, "new": new, "pattern": pattern, "note": note})

    def redirect(sid, group, fn, va, native_target, thunk, note=""):
        orig = bytes.fromhex(rel32(va, native_target).replace(" ", ""))
        add(sid, group, fn, va, orig, f"E8 {{rel32:{thunk}}}", "call_target_redirect", note)

    def detour(sid, group, fn, va, ln, thunk, note=""):
        orig = base_exe_bytes(va, ln)
        jmp = hx(bytes([0xE9]) + struct.pack("<i",names[thunk] - (va + 5)))
        add(sid, group, fn, va, orig, jmp + " 90" * (ln - 5), "detour_inplace", f"{note} (E9 -> {thunk})")

    g = "dw_scale"
    detour("DesignWin_exec.enter", g, "DesignWin_exec", EXEC, 5, "thunk_dw_enter", "prologue replay + ret swap -> thunk_dw_leave (g_dw_active bracket): immfix at every exec (6 callers)")
    detour("PartPicker_exec.enter", g, "PartPicker_exec", PK_EXEC, 5, "thunk_dw_pk_enter", "prologue replay + ret swap -> thunk_dw_pk_leave")
    detour("PartPicker_draw_cell.rect_law", g, "PartPicker_draw_cell", CELL_SITE, 6, "thunk_dw_cell", "cell rect = absolute native coords x g/16; g<=16 resumes the vanilla arithmetic")
    detour("PartPicker_repaint.frame_r_inset", g, "PartPicker_repaint", FRAME_SITE, 5, "thunk_dw_frame", "R inset s(55) (imm8 overflow at g=40)")
    add("PartPicker_vtbl.on_click", g, "PartPicker_vtbl", PK_VTBL_CLICK, struct.pack("<I", PK_ONCLICK), "{abs32:thunk_dw_click}", "vtable_repoint", "x,y descaled 16/g then the native hit test")
    redirect("PartPicker_repaint.container_frame", g, "PartPicker_repaint", BM_SITE, BOX_SPRITE, "thunk_dw_container", "rect copy R-1/B-1 -> thunk_box_thick_hollow_flat (law bandmap_rect_from_halfopen) + interior restripe 197/65 (the gutters)")
    redirect("PartPicker_draw_cell.cell_frame", g, "PartPicker_draw_cell", PICKCELL_SITE, BOX_SPRITE, "thunk_dw_pickcell", "+ interior restripe 196/65")
    redirect("PartPicker_draw_cell.empty_tile", g, "PartPicker_draw_cell", TILE_SITE, BUFFER_TILE_2, "thunk_dw_tilecell", "+ restripe 197/65 (tile 0x6B33F8)")
    redirect("DesignWin_draw_slot_strip.cell", g, "DesignWin_draw_slot_strip", SLOTCELL_SITE, BOX_SPRITE, "thunk_dw_slotcell", "hover/selected fill restripe (194/65, 191/83)")
    # 2026-10-25 W2A F38: through t_bm_ho_hf (assemble_halfopen_frames.py, law union_frame_draw_rect): R-1 / B-1 at g>16
    redirect("DesignWin_master.union_frame", g, "DesignWin_master", UNION_SITE, BOX_SPRITE, "t_bm_ho_hf", "D4: canvas-dest frame through the thick chain")
    for va, nat, th in RAIL_SITES:
        redirect(f"DesignWin_on_mode.{th.split('_')[-1]}", g, "DesignWin_on_mode", va, nat, th, "popup-family rail recipe (SE v2 / diplo)")
    detour("FlatButton_itemdraw_stub", g, "GraphicWin_vtbl_default", ITEMDRAW_STUB, 5, "thunk_dw_btndraw", "the vtbl+0x14 default `xor eax,eax; ret 0xC`: DesignWin buttons -> thunk_se_rowdraw")
    redirect("Caviar_draw.composite", g, "Caviar_draw", COMPOSITE_SITE, BUFFER_DRAW_2, "t_cav_blit", "dirty-rect composite (caviar_dirty_rect, src scripts/assemble_cavdirty.py); DW/picker dst hand off to thunk_dw_shim (SSAA or keyed stretch of the TN^2 target)")
    for va in FIT_SITES:
        fn = "Caviar_overlay" if va == 0x6171CF else ("PartPicker_draw_cell" if va < 0x434000 else "DesignWin_painters")
        redirect(f"{fn}.caviar_draw_{va:x}", g, fn, va, CAVIAR_DRAW, "thunk_dw_fit", "trial render + fit plan (law dw_fit_plan)")
    redirect("Caviar_draw.rasterize", g, "Caviar_draw", RASTER_SITE, CAVIAR_RASTERIZE, "thunk_dw_clip", "gated: ctx clip = whole target")
    redirect("Caviar_draw.reset_tail", g, "Caviar_draw", RESET_TAIL_SITE, CAVIAR_RESET, "thunk_dw_resetguard", "dirty rect clamped to [0,TN] before the unclipped memset")
    for va in RUNTAB_SITES:
        redirect(f"Caviar_rasterize_part.runtab_{va:x}", g, "Caviar_rasterize_part", va, RUNTAB, "thunk_dw_fpset", "per-part footprint cells")
    detour("Caviar_plot8.big_block", g, "Caviar_plot8", FP_SITE, 6, "thunk_dw_fp", "fixed 2x2 -> n x n block (resume 0x664A29)")
    detour("Caviar_plot8.big_block_plain", g, "Caviar_plot8", FP2_SITE, 6, "thunk_dw_fp2", "the non-flag&4 path (resume 0x664CC6)")
    for name, va, ln, prefix in E_STUB_SITES:
        orig = base_exe_bytes(va, ln)
        assert orig.startswith(prefix), (name, orig.hex())
        jmp = hx(bytes([0xE9]) + struct.pack("<i",names[name] - (va + 5)))
        add(f"Caviar.E_{name.split('_')[-1]}", g, "Caviar", va, orig, jmp + " 90" * (ln - 5), "detour_inplace", f"option E: disp8 site of the {TN}^2 target (E9 -> {name})")
    for va, w, nat, new, note in E_IMMS:
        orig = base_exe_bytes(va, w)
        assert orig == (struct.pack("<I", nat) if w == 4 else bytes([nat])), (hex(va), orig.hex())
        add(f"Caviar.E_imm_{va:x}", g, "Caviar", va, orig, hx(struct.pack("<I", new) if w == 4 else bytes([new])), "inplace_rewrite", f"option E: {note}")
    redirect("Caviar_overlay.table_blit", g, "Caviar_overlay", OVL_SITE, OVL_TARGET, "thunk_dw_ovl", "one-shot rescale armed by thunk_dw_fit")
    redirect("DesignWin_exec.build", g, "DesignWin_exec", BUILD_SITE, BUILD, "thunk_dw_build", "+ backdrop at device density")
    add("DesignWin_build.window_w_movimm", g, "DesignWin_build", 0x43C6CA, bytes([0x8B, 0x8E, 0xEC, 0x3C, 0x01, 0x00]), "B9 6F 02 00 00 90", "inplace_rewrite", "mov ecx,[esi+0x13CEC] (pcx w) -> mov ecx,imm32 623 (+nop); the imm is rewritten to ceil(623g/16) by g_dw_immtab")
    add("DesignWin_draw_slot_strip.selected_split", g, "DesignWin_draw_slot_strip", 0x43D726, bytes([0xBF, 0x02, 0x00, 0x00, 0x00, 0x8B, 0xC7, 0xEB, 0x12]), "6A 02 5F 6A 02 58 EB 13 90", "inplace_rewrite", "D7': `mov edi,2; mov eax,edi` is dual-purpose (state 2 + inset 2) -> push imm8/pop edi (inset, table-scaled) + push 2/pop eax (state)")
    g = "wheel_scroll"
    redirect("WinProc.wm_keydown_target", g, "WinProc", WHEEL_DOWN_SITE, GET_TARGET, "t_dw_wheel_down", "synthetic VK_UP/DOWN (PRACX wheel) -> chevron press on the modal's bar")
    redirect("WinProc.wm_keyup_target", g, "WinProc", WHEEL_UP_SITE, GET_TARGET, "t_dw_wheel_up", "the matching KEYUP swallowed")
    g = "popup_listbox_reserve"
    for sid, va, reg, ln in LBRES_SITES:
        orig = lbres_native(reg)
        assert len(orig) == ln
        add(f"g_scrollbar_w.{sid}", g, "listbox_bar_reserve", va, orig, f"E8 {{rel32:thunk_lbres_{reg}}}" + " 90" * (ln - 5), "call_helper", "law listbox_bar_reserve: load live, x g/16 under the popup gate")
    add("Win_create_vbar.stash", g, "Win_create_scrollbars", SBV_SITE, bytes([0x8B, 0x8E, 0x3C, 0x04, 0x00, 0x00]), "E8 {rel32:thunk_dw_sbv} 90", "call_helper", "register the heap V bar in g_rail_sb after ScrollBar_init_v")
    redirect("Popup_hide.railsb_clear", g, "Popup_hide", HIDE_SITE, HIDE_TARGET, "thunk_dw_hide", "clear g_rail_sb when it is this popup's heap bar")
    g = "picker_grid_leave_present"
    redirect("PartPicker_on_click.grid_leave", g, "PartPicker_on_click", GRIDLEAVE_SITE, PK_DRAWCELL, "thunk_dw_gridleave", "vanilla bug: the un-hover draw never presented")
    return S


def verify_live(sites: list[dict]) -> list[str]:
    problems = []
    for s in sites:
        have = base_exe_bytes(s["va"], len(s["orig"]))
        if have != s["orig"]:
            problems.append(f"{s['id']} @{s['va']:#x}: live {have.hex()} != {s['orig'].hex()}")
    for site, off, w, kind, a, b, label in IMMS:
        if site in STATIC_REWRITES:
            continue
        native = imm_value(site, off, 16)
        if w == 4:
            have = struct.unpack("<i", base_exe_bytes(site + off, 4))[0]
        else:
            have = struct.unpack("<b", base_exe_bytes(site + off, 1))[0]
        if have != native:
            problems.append(f"imm {label} @{site:#x}+{off}: live {have} != native {native}")
    for g in range(17, 41):
        for site, off, w, kind, a, b, label in IMMS:
            v = imm_value(site, off, g)
            if w == 1 and not -128 <= v <= 127:
                problems.append(f"imm {label}: imm8 overflow {v} at g={g}")
    # in-place cave upgrades: the yaml must currently hold the v1 bytes
    import pathlib
    import apply_patches as ap
    _s, _g, caves, _sym = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(_sym, caves))
    for n, va in SE_HELPERS.items():
        if symtab.get(n) != va:
            problems.append(f"SE helper {n}: yaml {symtab.get(n)} != {va:#x}")
    contents = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    for cid, off, fn, maxsz in INPLACE:
        if cid not in contents:
            problems.append(f"inplace {cid}: no cave content entry")
            continue
        if int(contents[cid]["offset"]) != off:
            problems.append(f"inplace {cid}: yaml offset {contents[cid]['offset']} != {off:#x}")
        new = fn()
        if len(new) > maxsz:
            problems.append(f"inplace {cid}: {len(new)}B > slot {maxsz}B")
    return problems


def roundtrip_problems(layout) -> list[str]:
    import pathlib
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(symbols, caves))
    for va, name in EXTRA_SYMS.items():
        symtab[name] = va
    for n, _fn, _g in NEW_THUNKS:
        symtab[n] = PCAVE2 + layout[n][0]
    out = []
    for name, (off, b) in layout.items():
        if name == "g_dw_immtab":
            continue
        va = PCAVE2 + off
        hexs = templatize(b, va)
        try:
            back = ap.ByteTemplate(hexs).resolve(va, symtab)
        except Exception as e:  # noqa: BLE001
            out.append(f"{name}: template does not resolve: {e}")
            continue
        if back != b:
            i = next((k for k in range(min(len(b), len(back))) if b[k] != back[k]), -1)
            out.append(f"{name}: resolved bytes differ at +{i:#x} (len {len(back)} vs {len(b)})")
    return out


GROUP_ORDER = ["dw_scale", "wheel_scroll", "popup_listbox_reserve", "picker_grid_leave_present"]


def site_yaml(sites: list[dict]) -> str:
    lines = []
    for s in sites:
        lines.append(
            f"  - id: {s['id']}\n    status: confirmed\n    group: {s['group']}\n    function: {s['function']}\n"
            f"    virtual_addr: {s['va']:#010x}\n    length: {len(s['orig'])}\n    original_bytes: \"{hx(s['orig'])}\""
            + (f"   # {s['note']}" if s["note"] else "") + "\n"
            f"    new_bytes:      \"{s['new']}\"\n    pattern: {s['pattern']}\n")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    layout, end = assemble_all()
    names = {n: PCAVE2 + layout[n][0] for n, _, _ in NEW_THUNKS}
    ok = True
    print("; ==== Design Workshop bake (assemble_dw.py) ====")
    print(f"; new code {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B); data cells {OFF_CELLS:#x}..{OFF_BIG_END:#x}; section end {SECTION_END:#x}")
    if end > OFF_CELLS:
        ok = False
        print("; OVERFLOW: code runs into the data cells")
    sym_lines, content_lines, inplace_lines = [], [], []
    for name, off, size in CELLS:
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    for name, _o, _fn in DATA:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {len(b)} }}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{hx(b)}\"")
    for name, _fn, grp in NEW_THUNKS:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {grp} ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    for cid, off, fn, maxsz in INPLACE:
        b = fn()
        inplace_lines.append(f"      - id: {cid}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off)}\"")
        print(f"; INPLACE {cid} @{off:#x} len {len(b)} (slot {maxsz})")
    sites = site_list(names)
    probs = verify_live(sites)
    for p in probs:
        print("; LIVE MISMATCH:", p)
    if probs:
        ok = False
    rt = roundtrip_problems(layout)
    for p in rt:
        print("; TEMPLATE ROUND-TRIP MISMATCH:", p)
    if rt:
        ok = False
    ids = [s["id"] for s in sites]
    if len(ids) != len(set(ids)):
        ok = False
        print("; DUPLICATE SITE IDS")
    if "--fragments" in argv:
        frag_dir = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag_dir, "_fragment_dw_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_dw_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_dw_inplace.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(inplace_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_dw_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_dw_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print("\n".join(inplace_lines))
        print(site_yaml(sites))
    print(f"; sites: {len(sites)} ({', '.join(f'{grp} {sum(1 for s in sites if s['group'] == grp)}' for grp in GROUP_ORDER)})")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
