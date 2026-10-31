#!/usr/bin/env python
"""Assembler for the DATALINKS (DatalinkWin 0x703EA0) BAKE (2026-08-30).
Ports the user-verified prototype hook_dl_scale_proto.js v12l (adversarially audited at 4K + 1600
2026-08-30: strokes K=2 all edges, stripes P-law canonical, chevron tip==stem, console save-under)
into pcave2 thunks.  One group:
  dl_scale    the Datalinks modal + its console sub-interface (gated g>16; tech-range levers
              additionally gated on g_dl_exec because 0x496BB0..0x49BD00 is ReportWin-shared code)
Recipe = the DW bake (assemble_dw.py): a runtime imm table applied by a walker thunk, split in TWO
tables because the tech rows live in ReportWin-shared code:
  MAIN  (189 rows + 1 raw)  applied ONCE at DatalinkWin_build entry (builder + DL-private painters)
  TECH  (162 rows + 8 ptr)  applied at DatalinkWin_open entry, REVERTED (walker g=16) at its return
        (+ TECH_EXTRA_IMMS, 2026-10-25 F44: rows the proto never carried, shared with the F2 bracket's table)
Kinds: HD s(a)-s(b) | MUL2/MUL3 | BIAS1 s(a)-s(b)+1 | NUMG g | DEN16 | FLOAT f32*g/16 | VEH | PTR
(active/native operand swap - the font repoints).  Identity at g=16 for every kind.
Thunks (CALL helper = E8-entered, consumes the ret; detour = E9):
  t_dl_build_enter   detour @DatalinkWin_build 0x429300 (5B prologue replay `55 8B EC 6A FF`):
                     ret-swap -> t_dl_build_leave; immfix(MAIN, g); g_netwin_active=1 (scrollbar
                     attach geometry: sb_xinset/sb_width run inside the build).
  t_dl_build_leave   netwin=0; BACK/EXIT box-sprite face set = the wing set (only-if-zero);
                     whole-canvas restripe; jmp saved ret.
  t_dl_exec_enter    detour @DatalinkWin_open 0x429180 (8B replay): ret-swap -> t_dl_exec_leave;
                     immfix(TECH, g); netwin=1; g_dl_exec=1.
  t_dl_exec_leave    immfix(TECH, 16) = revert the ReportWin-shared imms; netwin=0; g_dl_exec=0.
  t_dl_immfix_*      the walker (VirtualProtect 0x429000..0x49C000 once via kernel32 IAT).
  t_dl_cu            detour @0x42C094 (render_topic, after the three frames, before the painter
                     switch; displaced `8B 45 FC 83 F8 0F`, cmp replayed LAST for the ja):
                     restripe the content_union - the proto's painter-entry restripe.
  t_dl_restripe      CALL helper: P-law restripe of RS_* rect. Pair chosen by a member prescan
                     (C4 present -> 196/65 navy; AE|EE -> 174/238 sel; C6 -> 65/198 backdrop -
                     the proto's detectPairCol outcomes for the DL fields), CANONICAL member on
                     the stripe-top rows (y%%P < hN, P=(g+4)>>3, hN=(P+1)>>1, phase = absolute y).
                     NOT thunk_fe_pair_remap: its backdrop family is C6-top; DL parity is 65-top.
  t_dl_bm / t_dl_bmdf   R-1/B-1 rect copy -> thunk_box_thick_hollow_flat / _devfill (DW law
                     bandmap_rect_from_halfopen; scratch = g_dw_bmrect).
  t_dl_bmt           t_dl_bm + g_dl_exec gate (tech-range HF sites; ReportWin F8 stays native).
  t_dl_bmxt          the 10 clipped bracket sites: snapshot the frame bbox (plane + bounds: t_dl_snapchk,
                     assemble_rw_ring.py, 2026-10-25 W6C -- an oversized or empty bbox draws natively),
                     stash the ORIGINAL half-open rect -> g_faction_scratch_rect + g_fc_exact=1
                     (exact-fill: bottom stroke lands at B-2..B-1 = the chevron-tip law), R-1/B-1,
                     CALL hollow_flat, then restore everything OUTSIDE the dest clip (the enlarge
                     ignores the Buffer clip; the engine's clip is what makes these lines).
  t_dl_tile_bg/row   Buffer_tile wrappers @0x42A140/0x42A1F7: tile, then restripe the dest rect.
                     SUPERSEDED 2026-10-06 by t_dl_tile_ph (dead bytes kept: layout anchors).
  t_dl_tile_ph       2026-10-06, pinned in the free gap pcave2 0x23AC0, both list sites: stages the
                     rect, stores the list's parent-local top ([Win+0x140] + [Win+0x150], canvas =
                     Win+0x444) in g_dl_rs_phi, tiles, restripes (t_dl_restripe adds the cell to its
                     row index: the list stripes on the DatalinkWin grid the ring is on), clears it.
  t_dl_hover         @0x49B2F1 (7B raw -> call): frame R/B +s(3), T -s(3); native 3 outside DL.
  t_dl_arrowzoom     the 5 Sprite_blit_scaled_core sites: SCALE_NUM/DEN = g/16 around the call
                     (chevrons zoom); saved/restored; native outside DL.
  t_dl_mono          @0x49A2CF: the tech icon. Scaled draw is NOT mono -> after the draw, remap
                     idx 0x0F (the DNA art colour, the only index the draw emits) to the category
                     text colour sampled from the band above (brightest-majority via the palette).
  t_dl_btnrect       @0x607F60 (FlatButton box-sprite face): when thunk_btn_shrink flagged the
                     draw (g_btn_pending) pass the NATIVE-sized rect (w/h from btn +0x4C4/+0x4C8)
                     so the face branch positions right (BACK/EXIT hover clip fix).
  t_dl_techwrap      the 2 DL call sites of ReportWin_tech_page: save/scale RW+0x5980 (textB) and
                     RW+0xE268 (lineH), force iface mode 8 for the call, restore.
  t_dl_wininit       detour @Win_init 0x5EBD80: ecx == DL ListBox 0x713510 -> g_popup_active++
                     bracket (ret-swap) = the V-scrollbar width/zoom approval at attach.
  t_cr_snap_dl       clone of diplo t_cr_snap on the DL iface vtbl 0x66AF30 slot 0: console
                     save-under snapshot at DatalinkIface_on_mode(enter) (t_cr_tile restores).
  t_dl_rf1..rf6      the 6 imm8-overflow register fixups (terraform 75/100/103 x2, tech 52/58).
  t_dl_portrait      2026-08-30 addendum, E8 redirect @0x430DA3 (draw_faction): the leader portrait's
                     Sprite_draw_2 re-called with num=g/den=16; around the call the A5 bilinear
                     resampler's dest-gate imm (thunk_portrait_avg, pcave2+0xA05) is poked to the DL
                     canvas so the enlarge is palette-aware bilinear, not NN. Native jmp at g<=16.
  t_dl_portw         detour @0x430DA8: profile-text x advance uses the DRAWN portrait width
                     fl(w*g/16) (the resampler's idiv law) instead of the native sprite width.
  t_dl_wheel_down/up 2026-08-30 addendum, the wheel_scroll sites' new heads (spliced new_bytes):
                     while the DL modal is top, a wheel notch (synthetic VK, lParam 0) chevron-scrolls
                     the first engaged bar - category-list heap bar [LISTWIN+0x43C], else the VISIBLE
                     page/console TextScroll (+0x9C bit0 window-visible check) - and presents the
                     owner; the notch NEVER moves the selection (swallowed when nothing engaged);
                     v2 2026-09-22 (relocated to pcave2+0x13DB0, chained from t_rw_wheel_down by a
                     literal E9): the cursor over the ARTICLE panel (right_container +0x103B4, DL-local)
                     with a visible engaged page TextScroll, or over the console text box (+0x10374,
                     MainWin-local) with the console TextScroll engaged, scrolls THAT text; elsewhere
                     (and when no text under the cursor is engaged) the category list keeps the notch;
                     the KEYUP twin always swallowed; every non-DL context chains to the dw thunks.
IN PLACE (history): thunk_sb_restripe head: `mov [g_netwin_active],0` -> `mov eax,[g_dl_exec]; mov
[g_netwin_active],eax` (10B, eax dead) = the proto's post-sbzoom netwin re-assert (chevron zoom
survives the scrollbar restripe bracket) - identity for every non-DL user.  SUPERSEDED 2026-10-17
(fix 7): sbzoom v11 `inc`s the flag and the restripe head is a clamped `dec`, so DL's hold goes
1 -> 2 -> 1 across an armed draw with no re-assert; splice_dl.py accepts that head (SB_RC) as is.
Parity: tests/test_dl_asm_parity.py (Unicorn) - the walker vs scaling_laws at g 16/22/25/40, the
restripe core vs stripe_top, the bmxt rect/flag contract, native-identity vs the .bak immediates.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402
import dl_imms_gen as GEN  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x2B000          # pcave2 grown 0x22000 -> 0x2A000 (dl bake) -> 0x2B000 (article flow cache)

# ---- engine VAs ---------------------------------------------------------------
G            = 0x00668740      # g_popup_scale_num
OBJ          = 0x00703EA0      # DatalinkWin
CANVAS       = 0x007042E4      # OBJ+0x444 Buffer
CU           = 0x007141D4      # OBJ+0x10334 content_union RECT
LISTWIN      = 0x00713510      # OBJ+0xF670 (the ListBox GraphicWin part)
BACK_BTN     = 0x00711D9C      # OBJ+0xDEFC
EXIT_BTN     = 0x007128E8      # OBJ+0xEA48
WING_FACES   = (0x0078D960, 0x0078D988, 0x0078D9B0)
BOX_SPRITE   = 0x005E2DD3
BUFFER_TILE  = 0x005DA860
BLIT_CORE    = 0x005E4B9A      # Sprite_blit_scaled_core (thiscall, RET 0x10)
MONO_FN      = 0x005E3E00      # scale-swap + Sprite_draw_mono_2 (thiscall ecx=sprite, RET 0x1C)
SCALE_NUM, SCALE_DEN = 0x00696D18, 0x00696D1C
PALETTE      = 0x0094C590
RW           = 0x00876478      # ReportWin
MODETAB, MODEIDX = 0x007AE778, 0x007D392C
TECH_PAGE    = 0x00498B30
EXEC, EXEC_RESUME   = 0x00429180, 0x00429188
BUILD, BUILD_RESUME = 0x00429300, 0x00429305
WININIT, WININIT_RESUME = 0x005EBD80, 0x005EBD86
CU_DETOUR, CU_RESUME = 0x0042C094, 0x0042C09A
ONMODE       = 0x00432060      # DatalinkIface_on_mode
DL_IFACE_VTBL0 = 0x0066AF30
MW           = 0x007AE820
MW_CANVAS    = 0x007AEC64
CANVAS_DATA, CANVAS_STRIDE = MW_CANVAS + 0x54, MW_CANVAS + 0x4A8
SEED_D80, SEED_D90, SEED_DB0 = 0x7AF5A0, 0x7AF5B0, 0x7AF5D0
IAT_LOADLIB, IAT_GETPROC, IAT_VIRTUALALLOC = 0x00669120, 0x00669124, 0x00669134
STR_K32, STR_VP = 0x00A1C6C0, 0x00A1C6D0    # existing g_ed_str_k32 / g_ed_str_vp cells
VP_PAGE, VP_LEN, PAGE_RWX = 0x00429000, 0x73000, 0x40

# ---- portrait + wheel (2026-08-30 addendum) -----------------------------------
SPRITE_DRAW2   = 0x005E4B4A        # Sprite_draw_2 entry (detoured by thunk_portrait_avg push/ret)
PAVG_GATE_IMM  = PCAVE2 + 0xA05    # imm32 of thunk_portrait_avg's dest gate `cmp eax, 0x940824` (thunk @pcave2+0xA00; entry `mov eax,[esp+4]` is 4B, the cmp imm is +5). 2026-08-31 FIX: was +0xCA05 = thunk_chev_coverage+5 — the poke corrupted that thunk's prologue and the bilinear never engaged (portrait drew NN → 1600×1200 banding)
FACTION_BOX    = 0x00940824        # the A5 faction-box dest the gate normally admits
ART_DRAW       = PCAVE2 + 0x29EB0  # thunk_art_draw (assemble_artreblit.py): Sprite_draw_2 drop-in + edge-pinned parity re-blit
PORTRAIT_SITE  = 0x00430DA3        # draw_faction: call Sprite_draw_2 (num=1, den=1)
PORTW_SITE, PORTW_RESUME = 0x00430DA8, 0x00430DAE   # mov ebx,[ebx+0x78EEE4] (native portrait w)
PORTRAIT_W_FIELD = 0x0078EEE4      # faction sprite width (+0x18) read for the profile-text x advance
GET_TARGET     = 0x005F6A50        # Win_get_active_target (the wheel sites' original callee)
CHEVRON        = 0x00606B20        # ScrollBar_on_chevron (thiscall RET 4; btn 1 = up, 2 = down)
MODAL_TOP      = 0x009B7AE0
BASEPOP        = 0x009B8D7C        # g_current_basepop
DW_WHEEL_DOWN  = PCAVE2 + 0x195F0  # thunk_wheel_down (dw bake) - the non-DL chain tail
DW_WHEEL_UP    = PCAVE2 + 0x196E0  # thunk_wheel_up
TS_FULL, TS_LOWER, TS_LOWER800, TS_CONSOLE = OBJ + 0x10514, OBJ + 0x15C54, OBJ + 0x187F4, OBJ + 0x130B4
# v2 (2026-09-22) cursor routing: IAT GetCursorPos / ScreenToClient + the game HWND (as t_bw/t_ntw
# use them); the ARTICLE panel = right_container +0x103B4 (DL-local, union of title/upper/lower +-3,
# device space after the build walker) tested against cursor - DL origin (+0x13C/+0x140); the console
# text box +0x10374 (= MainWin rcConsoleCenterBig, MainWin-local) against cursor - MainWin origin.
IAT_GETCURSORPOS, IAT_SCREENTOCLIENT, G_HWND = 0x00669284, 0x006692D4, 0x009B7B28
WHEEL_STC = PCAVE2 + 0x1292C   # t_wheel_stc (assemble_rw.WHEEL_STC): ScreenToClient drop-in, client -> backbuffer when PRACX stretches
RC_ARTICLE, RC_CONSOLE = OBJ + 0x103B4, OBJ + 0x10374
WHEEL_DOWN_OFF = 0x13DB0       # relocated v2 head slot (592 B free after thunk_hud_baseargs; the old 0x230B0 slot is 352 B)
TILE_PH_OFF = 0x23AC0          # t_dl_tile_ph (2026-10-06): free gap t_rw_init_leave..t_rw_restripe (0x23ABF..0x23C20, cave_map)

# ---- article flow-scroll fix (2026-08-30 addendum 2; VANILLA bug) --------------
WRITE_STRINGS  = 0x005DB040    # Buffer_write_strings (thiscall(canvas) RET 0x14; flags&2 keeps cursor)
WSH            = 0x005DAD70    # Buffer_write_strings_height (thiscall(canvas)(list,width,flags) RET 0xC)
LINEH_FN       = 0x005DCAB0    # Buffer_text_line_height (thiscall(canvas), no args)
TS_DRAW_SITE   = 0x00629C26    # TextScroll_draw mode-0 branch: call Buffer_write_strings

# ---- existing cave symbols ----------------------------------------------------
HOLLOWFLAT   = PCAVE2 + 0x140
DEVFILL      = PCAVE2 + 0x42A0
G_NETWIN     = PCAVE2 + 0x10800 - 0xC000   # 0xA10800 = pcave2+0x4800
G_NETWIN     = PCAVE2 + 0x4800
G_POPUP_ACTIVE = PCAVE2 + 0x530
G_BTN_PENDING  = PCAVE2 + 0x534
G_FSR        = PCAVE2 + 0x1010             # g_faction_scratch_rect
G_FC_EXACT   = PCAVE2 + 0x2554
G_DW_BMRECT  = PCAVE2 + 0x1A080            # 16B rect scratch (DW; shared non-reentrant UI)
G_DW_RECT2   = PCAVE2 + 0x1A090
G_DW_CANDS   = PCAVE2 + 0x1AA00            # 1KB histogram scratch (DW)
CRBUF, CRL, CRR, CRB, CRARM = (PCAVE2 + o for o in (0x12790, 0x12794, 0x12798, 0x1279C, 0x127A0))
T_CR_MARK = PCAVE2 + 0x17080                 # assemble_diplo t_cr_mark (FIXED_OFF)

# ---- allocations --------------------------------------------------------------
OFF_CODE  = 0x22000
OFF_CELLS = 0x27E00
CELLS = [
    ("g_dl_exec", 0x27E00, 4), ("g_dl_exec_ret", 0x27E04, 4), ("g_dl_build_ret", 0x27E08, 4),
    ("g_dl_wret", 0x27E0C, 4), ("g_dl_immg", 0x27E10, 4), ("g_dl_vpdone", 0x27E14, 4),
    ("g_dl_vpold", 0x27E18, 4), ("g_dl_fscr", 0x27E1C, 4),
    ("g_dl_rs", 0x27E20, 0x40),   # +0 buf +4 x0 +8 y0 +C x1 +10 y1 +14 data +18 pitch +1C h
                                  # +20 cC4 +24 cAE +28 cEE +2C cC6 +30 c41 +34 top +38 bot +3C P
    ("g_dl_ts", 0x27E60, 16),     # techwrap: +0 textB +4 lineH +8 slotptr +C slotval
    ("g_dl_sv", 0x27E70, 8),      # arrowzoom saved NUM/DEN
    ("g_dl_snapbuf", 0x27E78, 4), # bmxt snapshot plane: t_rw_init_leave's 4 MB, else t_dl_snapchk's (size in g_dl_snapcap)
    ("g_dl_bx", 0x27E80, 0x40),   # bmxt frame: +0 x0 +4 y0 +8 x1 +C y1 +10 data +14 pitch
                                  # +18 cl +1C ct +20 cr +24 cb +28 dest +2C w +30 h
    ("g_dl_mono", 0x27EC0, 16),   # +0 best +4 x +8 y +C num
    ("g_dl_rs_phi", 0x27ED0, 4),  # t_dl_tile_ph: the list's parent-local top (Win +0x140 + +0x150); t_dl_restripe adds it to its row
    ("g_dl_immtab_main", 0x28100, 0),   # sized below
    ("g_dl_immtab_tech", 0x28100, 0),
    ("g_ts_flowcache", 0x2A000, 0x1000),  # article flow cache: +0 ts +4 width +8 headptr +C count
                                          # +10 lineH +14 total_lines +18 nentries +1C visible
                                          # +20 rawH0; entries @+0x24 {node,idx,cum_px} x12B cap 320
]
CELL = {n: PCAVE2 + o for n, o, _ in CELLS}
FLOW = CELL["g_ts_flowcache"]
RS = {k: CELL["g_dl_rs"] + o for k, o in (("BUF", 0), ("X0", 4), ("Y0", 8), ("X1", 0xC), ("Y1", 0x10),
                                          ("DATA", 0x14), ("PITCH", 0x18), ("H", 0x1C),
                                          ("C4", 0x20), ("AE", 0x24), ("EE", 0x28), ("C6", 0x2C), ("C41", 0x30),
                                          ("TOP", 0x34), ("BOT", 0x38), ("P", 0x3C))}
BX = {k: CELL["g_dl_bx"] + o for k, o in (("X0", 0), ("Y0", 4), ("X1", 8), ("Y1", 0xC), ("DATA", 0x10),
                                          ("PITCH", 0x14), ("CL", 0x18), ("CT", 0x1C), ("CR", 0x20),
                                          ("CB", 0x24), ("DEST", 0x28), ("W", 0x2C), ("H", 0x30))}
TS = {k: CELL["g_dl_ts"] + o for k, o in (("TEXTB", 0), ("LINEH", 4), ("SLOTP", 8), ("SLOTV", 0xC))}
MO = {k: CELL["g_dl_mono"] + o for k, o in (("BEST", 0), ("X", 4), ("Y", 8), ("NUM", 0xC))}
IMMG, FSCR = CELL["g_dl_immg"], CELL["g_dl_fscr"]
PHI = CELL["g_dl_rs_phi"]
VPDONE, VPOLD = CELL["g_dl_vpdone"], CELL["g_dl_vpold"]
G_DL_EXEC = CELL["g_dl_exec"]
T_DL_SNAPCHK = PCAVE2 + 0x3F080      # W6C (assemble_rw_ring.py): t_dl_bmxt's snapshot plane + bounds helper
G_DL_SNAPCAP = PCAVE2 + 0x3F1F0      # its plane size (0 = t_rw_init_leave's 4 MB plane)

# ---- the immediate tables ------------------------------------------------------
K_W4, K_MUL2, K_MUL3, K_BIAS1, K_NUMG, K_DEN16, K_FLOAT, K_VEH, K_NEG, K_PTR = (
    1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80, 0x100, 0x200)
KINDBITS = {'HD': 0, 'MUL2': K_MUL2, 'MUL2NEG': K_MUL2 | K_NEG, 'MUL3': K_MUL3, 'BIAS1': K_BIAS1,
            'NUMG': K_NUMG, 'DEN16': K_DEN16, 'FLOAT': K_FLOAT | K_W4, 'VEH': K_VEH, 'PTR': K_PTR}

# font-pointer swaps (ReportWin-shared code -> PTR rows in the TECH table)
PTR_ROWS = [
    # (site, off, w, active, native, label)
    # v2 (2026-09-17, audit finding 3.13): the tech title/category font repoints (A1 [0x8A40D4] -> B8
    # &DL.F0 Arial 18 bold; A1 [0x8A40C8] -> B8 &DL.F4 Arial 14 bold) are DROPPED: vanilla draws them
    # with the ReportInfc pool fonts f16/f14 (Arial Narrow bold), which rw_scale_shared's init lever
    # scales at desktop_init (before any Datalinks open) -- the vanilla face at the vanilla size law.
] + [(a, 1, 4, 0x714094, 0x6E84B4, "tech button label font push -> &DL.F3") for a in GEN.FONT_PUSH]

# Tech-range rows the proto never carried (GEN.IMMS is generated from it -- do not edit that file), in GEN.IMMS's
# shape (site, off, w, kind, a, b, t, label).  ONE list, read by BOTH tech tables: this one (appended after the PTR
# rows, so the older rows keep their bytes) and assemble_rw.tech_rows() (the F2 bracket's table) -- every report-
# side tech row is also a Datalinks tech row, so DatalinkWin_open's return walk (g = 16) leaves the whole
# ReportWin-shared range native whatever ran inside the Datalinks session.
#   F44 (2026-10-25): ReportWin_tech_page's NON-Datalinks odd pair (law scaling_laws.rw_tech_row_slots).  The page
#   branches on iface mode 8 at 0x499553; the proto only ever ran the mode-8 side, so it scaled the Datalinks pair
#   0x4995CC / 0x4995CF and the shared even pitch, and F2 (mode 5) laid its 3-row column out with a native 16.
#   Dead on the Datalinks path (techwrap forces mode 8); live on F2 (t_rw_techpage / t_rw_techhover apply the table).
TECH_EXTRA_IMMS = [
    (0x49957C, 3, 1, 'HD', 0x10, 0x0, 1, 'tech non-DL: row below = y_mid + btn_h + 16 -> [RW+0x5960]  (lea edx,[edi+eax+0x10])'),
    (0x499580, 2, 1, 'HD', 0x10, 0x0, 1, 'tech non-DL: row above = y_mid - btn_h - 16 -> [RW+0x595C]  (sub ecx,0x10)'),
]


def tech_extra_rows():
    return [(site + off, a, b, KINDBITS[kind] | (K_W4 if w == 4 else 0))
            for site, off, w, kind, a, b, _t, _lbl in TECH_EXTRA_IMMS]


def imm_rows(tech: bool):
    rows = []
    for site, off, w, kind, a, b, t, _lbl in GEN.IMMS:
        if bool(t) != tech:
            continue
        bits = KINDBITS[kind] | (K_W4 if w == 4 else 0)
        rows.append((site + off, a, b, bits))
    if tech:
        for site, off, w, act, nat, _lbl in PTR_ROWS:
            rows.append((site + off, act, nat, K_PTR | (K_W4 if w == 4 else 0)))
        rows += tech_extra_rows()
    return rows


def immtab_bytes(tech: bool) -> bytes:
    out = bytearray()
    for site, a, b, bits in imm_rows(tech):
        out += struct.pack("<IiiI", site, a & 0xFFFFFFFF, b & 0xFFFFFFFF, bits)
    out += b"\x00" * 4
    return bytes(out)


def imm_value(a: int, b: int, bits: int, g: int) -> int:
    """Oracle for the walker (parity tests)."""
    if bits & K_PTR:
        return b if g == 16 else a
    if bits & K_FLOAT:
        f = struct.unpack("<f", struct.pack("<I", a & 0xFFFFFFFF))[0]
        return struct.unpack("<I", struct.pack("<f", f * g / 16.0))[0]
    if bits & K_NUMG:
        return g
    if bits & K_DEN16:
        return 16
    if bits & K_VEH:
        return min(48, (((a + 16) * g) >> 4) - 16)
    v = SL.scale_px(a, g) - SL.scale_px(b, g)
    if bits & K_MUL2:
        v *= 2
    if bits & K_MUL3:
        v *= 3
    if bits & K_BIAS1:
        v += 1
    return -v if bits & K_NEG else v


MAIN_TAB = immtab_bytes(False)
TECH_TAB = immtab_bytes(True)
OFF_TAB_MAIN = 0x28100
# 2026-10-25 F44: the tech table starts DWORD-aligned right after the main table (was 16-aligned at 0x28CE0): its two
# TECH_EXTRA_IMMS rows (+32 B) then end at 0x29778, short of the next occupant t_cmb_init (assemble_combat.BASE_OFF
# 0x29780).  The walker reads dwords; nothing references the table but t_dl_immfix_tech's {abs32:}.
OFF_TAB_TECH = (OFF_TAB_MAIN + len(MAIN_TAB) + 3) & ~3
TECH_TAB_LIMIT = 0x29780
TAB_MAIN = PCAVE2 + OFF_TAB_MAIN
TAB_TECH = PCAVE2 + OFF_TAB_TECH
assert OFF_TAB_TECH + len(TECH_TAB) <= TECH_TAB_LIMIT <= SECTION_END, hex(OFF_TAB_TECH + len(TECH_TAB))
CELLS = [(n, o, (len(MAIN_TAB) if n == "g_dl_immtab_main" else len(TECH_TAB) if n == "g_dl_immtab_tech" else s))
         for n, o, s in CELLS]
CELLS = [(n, (OFF_TAB_MAIN if n == "g_dl_immtab_main" else OFF_TAB_TECH if n == "g_dl_immtab_tech" else o), s)
         for n, o, s in CELLS]


def HDG(reg: str) -> str:
    """reg = half_down(reg * immg / 16) with the walker's g."""
    return f"imul {reg}, dword ptr [{IMMG:#x}]\n    lea {reg}, [{reg}*2+15]\n    sar {reg}, 5\n"


HD, FL = SE.HD, SE.FL


# ==== walker =====================================================================
def asm_dl_immfix_main() -> str:
    return f"""
    push    esi                     ; 2026-09-20: the walker's own push/pop saved the TABLE pointer, so every
    mov     esi, {TAB_MAIN:#x}     ; Datalinks open returned esi = the table VA to the engine caller
    call    t_dl_immfix             ; (secret-project flow keeps the project id in esi -> Monument record
    pop     esi                     ; param = 0xA34CE0 -> AV @0x4742BB drawing the plaque)
    ret
"""


def asm_dl_immfix_tech() -> str:
    return f"""
    push    esi                     ; 2026-09-20: the walker's own push/pop saved the TABLE pointer, so every
    mov     esi, {TAB_TECH:#x}     ; Datalinks open returned esi = the table VA to the engine caller
    call    t_dl_immfix             ; (secret-project flow keeps the project id in esi -> Monument record
    pop     esi                     ; param = 0xA34CE0 -> AV @0x4742BB drawing the plaque)
    ret
"""


def asm_dl_immfix() -> str:
    return f"""
    push    esi
    push    ebx
    cmp     dword ptr [{VPDONE:#x}], 0
    jne     rows
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
rows:
    mov     eax, dword ptr [esi]
    test    eax, eax
    je      bail
    mov     edx, dword ptr [esi+12]
    test    edx, {K_PTR}
    jne     kptr
    test    edx, {K_FLOAT}
    jne     kfloat
    test    edx, {K_NUMG}
    jne     knumg
    test    edx, {K_DEN16}
    jne     kden
    test    edx, {K_VEH}
    jne     kveh
    mov     ecx, dword ptr [esi+4]
    {HDG("ecx")}
    mov     ebx, dword ptr [esi+8]
    {HDG("ebx")}
    sub     ecx, ebx
    test    edx, {K_MUL2}
    je      nm2
    add     ecx, ecx
nm2:
    test    edx, {K_MUL3}
    je      nm3
    lea     ecx, [ecx+ecx*2]
nm3:
    test    edx, {K_BIAS1}
    je      nb1
    inc     ecx
nb1:
    test    edx, {K_NEG}
    je      store
    neg     ecx
    jmp     store
kptr:
    mov     ecx, dword ptr [esi+4]
    cmp     dword ptr [{IMMG:#x}], 16
    jg      store
    mov     ecx, dword ptr [esi+8]
    jmp     store
knumg:
    mov     ecx, dword ptr [{IMMG:#x}]
    jmp     store
kden:
    mov     ecx, 16
    jmp     store
kveh:
    mov     ecx, dword ptr [esi+4]
    add     ecx, 16
    imul    ecx, dword ptr [{IMMG:#x}]
    sar     ecx, 4
    sub     ecx, 16
    cmp     ecx, 48
    jle     store
    mov     ecx, 48
    jmp     store
kfloat:
    mov     ecx, dword ptr [esi+4]
    mov     dword ptr [{FSCR:#x}], ecx
    fld     dword ptr [{FSCR:#x}]
    fild    dword ptr [{IMMG:#x}]
    fmulp
    mov     dword ptr [{FSCR:#x}], 16
    fild    dword ptr [{FSCR:#x}]
    fdivp
    fstp    dword ptr [{FSCR:#x}]
    mov     ecx, dword ptr [{FSCR:#x}]
store:
    mov     eax, dword ptr [esi]
    test    dword ptr [esi+12], {K_W4}
    jne     wr4
    mov     byte ptr [eax], cl
    jmp     adv
wr4:
    mov     dword ptr [eax], ecx
adv:
    add     esi, 16
    jmp     rows
bail:
    pop     ebx
    pop     esi
    ret
"""


# ==== brackets ===================================================================
def asm_dl_build_enter() -> str:
    return f"""
    pop     eax
    mov     dword ptr [{CELL['g_dl_build_ret']:#x}], eax
    push    t_dl_build_leave
    push    ecx
    push    edx
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{IMMG:#x}], eax
    call    t_dl_immfix_main
    pop     edx
    pop     ecx
    mov     dword ptr [{G_NETWIN:#x}], 1
    push    ebp
    mov     ebp, esp
    push    -1
    jmp     {BUILD_RESUME:#x}
"""


def asm_dl_build_leave() -> str:
    fw = "\n".join(
        f"    mov     dword ptr [{btn + 0xAC8 + i * 4:#x}], {WING_FACES[i]:#x}"
        for btn in (BACK_BTN, EXIT_BTN) for i in range(3))
    return f"""
    mov     dword ptr [{G_NETWIN:#x}], 0
    push    eax
    cmp     dword ptr [{BACK_BTN + 0xAC8:#x}], 0
    jne     faced
{fw}
faced:
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 16
    jle     nors
    mov     dword ptr [{RS['BUF']:#x}], {CANVAS:#x}
    xor     eax, eax
    mov     dword ptr [{RS['X0']:#x}], eax
    mov     dword ptr [{RS['Y0']:#x}], eax
    mov     eax, dword ptr [{CANVAS + 0x80:#x}]
    mov     dword ptr [{RS['X1']:#x}], eax
    mov     eax, dword ptr [{CANVAS + 0x84:#x}]
    test    eax, eax
    jns     hp
    neg     eax
hp:
    mov     dword ptr [{RS['Y1']:#x}], eax
    call    t_dl_restripe
nors:
    pop     eax
    jmp     dword ptr [{CELL['g_dl_build_ret']:#x}]
"""


def asm_dl_exec_enter() -> str:
    # displaced 8B: push ebp / mov ebp,esp / mov eax,[0x9B7B1C]
    return f"""
    pop     eax
    mov     dword ptr [{CELL['g_dl_exec_ret']:#x}], eax
    push    t_dl_exec_leave
    push    ecx
    push    edx
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{IMMG:#x}], eax
    call    t_dl_immfix_tech
    pop     edx
    pop     ecx
    mov     dword ptr [{G_NETWIN:#x}], 1
    mov     dword ptr [{G_DL_EXEC:#x}], 1
    push    ebp
    mov     ebp, esp
    mov     eax, dword ptr [0x9B7B1C]
    jmp     {EXEC_RESUME:#x}
"""


def asm_dl_exec_leave() -> str:
    return f"""
    push    eax
    push    ecx
    push    edx
    mov     dword ptr [{IMMG:#x}], 16
    call    t_dl_immfix_tech
    pop     edx
    pop     ecx
    mov     dword ptr [{G_NETWIN:#x}], 0
    mov     dword ptr [{G_DL_EXEC:#x}], 0
    pop     eax
    jmp     dword ptr [{CELL['g_dl_exec_ret']:#x}]
"""


# ==== restripe ===================================================================
def asm_dl_cu() -> str:
    # displaced 6B @0x42C094: mov eax,[ebp-4]; cmp eax,0xF (cmp replayed LAST: the ja consumes it)
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 16
    jle     skip
    mov     eax, dword ptr [{CU:#x}]
    mov     dword ptr [{RS['X0']:#x}], eax
    mov     eax, dword ptr [{CU + 4:#x}]
    mov     dword ptr [{RS['Y0']:#x}], eax
    mov     eax, dword ptr [{CU + 8:#x}]
    mov     dword ptr [{RS['X1']:#x}], eax
    mov     eax, dword ptr [{CU + 12:#x}]
    mov     dword ptr [{RS['Y1']:#x}], eax
    mov     dword ptr [{RS['BUF']:#x}], {CANVAS:#x}
    call    t_dl_restripe
skip:
    mov     eax, dword ptr [ebp-4]
    cmp     eax, 0xF
    jmp     {CU_RESUME:#x}
"""


def asm_dl_restripe() -> str:
    # Reads RS_*: buf,x0,y0,x1,y1.  pushad/popad.  Port of restripeRect + detectPairCol outcomes +
    # CANON_TOP (196/65, 174/238, 65/198 - canonical member on stripe-top rows).
    return f"""
    pushad
    mov     esi, dword ptr [{RS['BUF']:#x}]
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    je      out
    mov     dword ptr [{RS['DATA']:#x}], eax
    mov     ecx, dword ptr [esi+0x80]
    mov     edx, dword ptr [esi+0x4A8]
    cmp     edx, ecx
    jl      p1c
    lea     ebx, [ecx+8]
    cmp     edx, ebx
    jle     pok
p1c:
    mov     edx, dword ptr [esi+0x4A4]
    cmp     edx, ecx
    jl      pdef
    lea     ebx, [ecx+8]
    cmp     edx, ebx
    jle     pok
pdef:
    lea     edx, [ecx+3]
    and     edx, -4
pok:
    mov     dword ptr [{RS['PITCH']:#x}], edx
    mov     edx, dword ptr [esi+0x84]
    test    edx, edx
    jns     hp
    neg     edx
hp:
    mov     dword ptr [{RS['H']:#x}], edx
    ; clamp x0/y0 >= 0, x1 <= w, y1 <= h
    xor     ebx, ebx
    cmp     dword ptr [{RS['X0']:#x}], ebx
    jge     cx0
    mov     dword ptr [{RS['X0']:#x}], ebx
cx0:
    cmp     dword ptr [{RS['Y0']:#x}], ebx
    jge     cy0
    mov     dword ptr [{RS['Y0']:#x}], ebx
cy0:
    cmp     dword ptr [{RS['X1']:#x}], ecx
    jle     cx1
    mov     dword ptr [{RS['X1']:#x}], ecx
cx1:
    cmp     dword ptr [{RS['Y1']:#x}], edx
    jle     cy1
    mov     dword ptr [{RS['Y1']:#x}], edx
cy1:
    mov     eax, dword ptr [{RS['X1']:#x}]
    sub     eax, dword ptr [{RS['X0']:#x}]
    cmp     eax, 8
    jl      out
    mov     eax, dword ptr [{RS['Y1']:#x}]
    sub     eax, dword ptr [{RS['Y0']:#x}]
    cmp     eax, 8
    jl      out
    ; prescan: count pair members
    xor     eax, eax
    mov     dword ptr [{RS['C4']:#x}], eax
    mov     dword ptr [{RS['AE']:#x}], eax
    mov     dword ptr [{RS['EE']:#x}], eax
    mov     dword ptr [{RS['C6']:#x}], eax
    mov     dword ptr [{RS['C41']:#x}], eax
    mov     edi, dword ptr [{RS['Y0']:#x}]
sy:
    cmp     edi, dword ptr [{RS['Y1']:#x}]
    jge     sdone
    mov     esi, edi
    imul    esi, dword ptr [{RS['PITCH']:#x}]
    add     esi, dword ptr [{RS['DATA']:#x}]
    mov     ebx, dword ptr [{RS['X0']:#x}]
sx:
    cmp     ebx, dword ptr [{RS['X1']:#x}]
    jge     srow
    mov     al, byte ptr [esi+ebx]
    cmp     al, 0xC4
    jne     s1
    inc     dword ptr [{RS['C4']:#x}]
    jmp     snext
s1:
    cmp     al, 0xAE
    jne     s2
    inc     dword ptr [{RS['AE']:#x}]
    jmp     snext
s2:
    cmp     al, 0xEE
    jne     s3
    inc     dword ptr [{RS['EE']:#x}]
    jmp     snext
s3:
    cmp     al, 0xC6
    jne     s4
    inc     dword ptr [{RS['C6']:#x}]
    jmp     snext
s4:
    cmp     al, 0x41
    jne     snext
    inc     dword ptr [{RS['C41']:#x}]
snext:
    inc     ebx
    jmp     sx
srow:
    inc     edi
    jmp     sy
sdone:
    ; choose the pair (canonical member first = stripe-top colour)
    cmp     dword ptr [{RS['C4']:#x}], 0
    je      t1
    mov     eax, 0xC4
    mov     edx, 0x41
    mov     ecx, dword ptr [{RS['C4']:#x}]
    add     ecx, dword ptr [{RS['C41']:#x}]
    jmp     chose
t1:
    mov     ecx, dword ptr [{RS['AE']:#x}]
    add     ecx, dword ptr [{RS['EE']:#x}]
    test    ecx, ecx
    je      t2
    mov     eax, 0xAE
    mov     edx, 0xEE
    jmp     chose
t2:
    cmp     dword ptr [{RS['C6']:#x}], 0
    je      out
    mov     eax, 0x41
    mov     edx, 0xC6
    mov     ecx, dword ptr [{RS['C6']:#x}]
    add     ecx, dword ptr [{RS['C41']:#x}]
chose:
    mov     dword ptr [{RS['TOP']:#x}], eax
    mov     dword ptr [{RS['BOT']:#x}], edx
    ; dominance bail: pairSum*4 < area -> out
    mov     eax, dword ptr [{RS['X1']:#x}]
    sub     eax, dword ptr [{RS['X0']:#x}]
    mov     ebx, dword ptr [{RS['Y1']:#x}]
    sub     ebx, dword ptr [{RS['Y0']:#x}]
    imul    eax, ebx
    shl     ecx, 2
    cmp     ecx, eax
    jl      out
    ; P law: the period cell thunk_ensure_scale writes with g (2 under 1080 px, 4 above)
    mov     eax, dword ptr [0x66879c]
    mov     dword ptr [{RS['P']:#x}], eax
    ; rewrite
    mov     edi, dword ptr [{RS['Y0']:#x}]
ry:
    cmp     edi, dword ptr [{RS['Y1']:#x}]
    jge     out
    mov     eax, edi
    add     eax, dword ptr [{PHI:#x}]
    xor     edx, edx
    div     dword ptr [{RS['P']:#x}]
    mov     eax, dword ptr [{RS['P']:#x}]
    inc     eax
    sar     eax, 1
    cmp     edx, eax
    mov     ecx, dword ptr [{RS['TOP']:#x}]
    jl      coltop
    mov     ecx, dword ptr [{RS['BOT']:#x}]
coltop:
    mov     esi, edi
    imul    esi, dword ptr [{RS['PITCH']:#x}]
    add     esi, dword ptr [{RS['DATA']:#x}]
    mov     ebx, dword ptr [{RS['X0']:#x}]
rx:
    cmp     ebx, dword ptr [{RS['X1']:#x}]
    jge     rrow
    mov     al, byte ptr [esi+ebx]
    cmp     al, byte ptr [{RS['TOP']:#x}]
    je      wr
    cmp     al, byte ptr [{RS['BOT']:#x}]
    jne     rnext
wr:
    mov     byte ptr [esi+ebx], cl
rnext:
    inc     ebx
    jmp     rx
rrow:
    inc     edi
    jmp     ry
out:
    popad
    ret
"""


# ==== frame stubs ================================================================
def _bm_copy() -> str:
    return f"""
    mov     eax, dword ptr [esp+4]
    mov     edx, dword ptr [eax]
    mov     dword ptr [{G_DW_BMRECT:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{G_DW_BMRECT + 4:#x}], edx
    mov     edx, dword ptr [eax+8]
    dec     edx
    mov     dword ptr [{G_DW_BMRECT + 8:#x}], edx
    mov     edx, dword ptr [eax+12]
    dec     edx
    mov     dword ptr [{G_DW_BMRECT + 12:#x}], edx
    mov     dword ptr [esp+4], {G_DW_BMRECT:#x}
"""


def asm_dl_bm() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
{_bm_copy()}
    jmp     {HOLLOWFLAT:#x}
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_dl_bmdf() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
{_bm_copy()}
    jmp     {DEVFILL:#x}
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_dl_bmt() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    cmp     dword ptr [{G_DL_EXEC:#x}], 0
    je      native
{_bm_copy()}
    jmp     {HOLLOWFLAT:#x}
native:
    jmp     {BOX_SPRITE:#x}
"""


# t_dl_bmxt keeps its baked 599 B (dead int3 fill after the restore loop's `ret 8`; the thunk still ends in its native
# jmp) so every thunk after it keeps its offset (the layout is sequential)
BMXT_LEN = 599
BMXT_PAD = 34


def asm_dl_bmxt() -> str:
    # Clipped bracket sites: snapshot bbox -> restore outside the dest clip after the thick draw;
    # exact-fill (g_faction_scratch_rect + g_fc_exact) so the bottom stroke lands at B-2..B-1.
    fill = "\n".join(["    int3"] * BMXT_PAD)
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    cmp     dword ptr [{G_DL_EXEC:#x}], 0
    je      native
    push    esi
    push    edi
    push    ebx
    ; dest buffer fields (ecx = dest)
    mov     eax, dword ptr [ecx+0x54]
    test    eax, eax
    je      nat3
    mov     dword ptr [{BX['DATA']:#x}], eax
    mov     dword ptr [{BX['DEST']:#x}], ecx
    mov     eax, dword ptr [ecx+0x80]
    mov     dword ptr [{BX['W']:#x}], eax
    mov     edx, dword ptr [ecx+0x4A8]
    mov     dword ptr [{BX['PITCH']:#x}], edx
    mov     eax, dword ptr [ecx+0x84]
    test    eax, eax
    jns     bhh
    neg     eax
bhh:
    mov     dword ptr [{BX['H']:#x}], eax
    ; clip
    mov     eax, dword ptr [ecx+0x20]
    mov     dword ptr [{BX['CL']:#x}], eax
    mov     eax, dword ptr [ecx+0x24]
    mov     dword ptr [{BX['CT']:#x}], eax
    mov     eax, dword ptr [ecx+0x28]
    mov     dword ptr [{BX['CR']:#x}], eax
    mov     eax, dword ptr [ecx+0x2C]
    mov     dword ptr [{BX['CB']:#x}], eax
    ; bbox = rect grown (L-2,T-2,R+4,B+4), clamped
    mov     eax, dword ptr [esp+0x10]
    mov     edx, dword ptr [eax]
    sub     edx, 2
    jns     bx0
    xor     edx, edx
bx0:
    mov     dword ptr [{BX['X0']:#x}], edx
    mov     edx, dword ptr [eax+4]
    sub     edx, 2
    jns     by0
    xor     edx, edx
by0:
    mov     dword ptr [{BX['Y0']:#x}], edx
    mov     edx, dword ptr [eax+8]
    add     edx, 4
    cmp     edx, dword ptr [{BX['W']:#x}]
    jle     bx1
    mov     edx, dword ptr [{BX['W']:#x}]
bx1:
    mov     dword ptr [{BX['X1']:#x}], edx
    mov     edx, dword ptr [eax+12]
    add     edx, 4
    cmp     edx, dword ptr [{BX['H']:#x}]
    jle     by1
    mov     edx, dword ptr [{BX['H']:#x}]
by1:
    mov     dword ptr [{BX['Y1']:#x}], edx
    ; snapshot plane + bounds (2026-10-25 W6C, t_dl_snapchk @pcave2 0x3F080): ebx = the plane when the bbox fits
    ; it, else 0 -> the native draw (was: VirtualAlloc 64K here, then an unchecked copy of any bbox into it)
    call    {T_DL_SNAPCHK:#x}
    test    ebx, ebx
    je      nat3
    ; copy rows [y0,y1) x [x0,x1) -> buf (packed rows, stride = x1-x0)
    mov     edi, ebx
    mov     edx, dword ptr [{BX['Y0']:#x}]
crow:
    cmp     edx, dword ptr [{BX['Y1']:#x}]
    jge     cdone
    mov     esi, edx
    imul    esi, dword ptr [{BX['PITCH']:#x}]
    add     esi, dword ptr [{BX['DATA']:#x}]
    add     esi, dword ptr [{BX['X0']:#x}]
    mov     ecx, dword ptr [{BX['X1']:#x}]
    sub     ecx, dword ptr [{BX['X0']:#x}]
    jle     cdone
    rep movsb
    inc     edx
    jmp     crow
cdone:
    ; exact-fill: original half-open rect -> g_faction_scratch_rect; flag; R-1/B-1 copy
    mov     eax, dword ptr [esp+0x10]
    mov     edx, dword ptr [eax]
    mov     dword ptr [{G_FSR:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{G_FSR + 4:#x}], edx
    mov     edx, dword ptr [eax+8]
    mov     dword ptr [{G_FSR + 8:#x}], edx
    dec     edx
    mov     dword ptr [{G_DW_BMRECT + 8:#x}], edx
    mov     edx, dword ptr [eax]
    mov     dword ptr [{G_DW_BMRECT:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{G_DW_BMRECT + 4:#x}], edx
    mov     edx, dword ptr [eax+12]
    mov     dword ptr [{G_FSR + 12:#x}], edx
    dec     edx
    mov     dword ptr [{G_DW_BMRECT + 12:#x}], edx
    mov     dword ptr [{G_FC_EXACT:#x}], 1
    ; call hollow_flat(dest ecx)(rect', params) - re-push
    mov     ecx, dword ptr [{BX['DEST']:#x}]
    push    dword ptr [esp+0x14]
    push    {G_DW_BMRECT:#x}
    call    {HOLLOWFLAT:#x}
    mov     dword ptr [{G_FC_EXACT:#x}], 0
    ; restore outside the clip
    mov     ebx, dword ptr [{CELL['g_dl_snapbuf']:#x}]
    mov     edx, dword ptr [{BX['Y0']:#x}]
rrow:
    cmp     edx, dword ptr [{BX['Y1']:#x}]
    jge     rdone
    mov     edi, edx
    imul    edi, dword ptr [{BX['PITCH']:#x}]
    add     edi, dword ptr [{BX['DATA']:#x}]
    add     edi, dword ptr [{BX['X0']:#x}]
    mov     esi, ebx
    mov     ecx, dword ptr [{BX['X1']:#x}]
    sub     ecx, dword ptr [{BX['X0']:#x}]
    cmp     edx, dword ptr [{BX['CT']:#x}]
    jl      full
    cmp     edx, dword ptr [{BX['CB']:#x}]
    jge     full
    ; partial: left seg [x0, min(cl,x1)) then right seg [max(cr,x0), x1)
    mov     eax, dword ptr [{BX['CL']:#x}]
    sub     eax, dword ptr [{BX['X0']:#x}]
    jle     rseg
    cmp     eax, ecx
    jle     lcap
    mov     eax, ecx
lcap:
    push    ecx
    push    esi
    push    edi
    mov     ecx, eax
    rep movsb
    pop     edi
    pop     esi
    pop     ecx
rseg:
    mov     eax, dword ptr [{BX['CR']:#x}]
    sub     eax, dword ptr [{BX['X0']:#x}]
    jl      rz
    cmp     eax, ecx
    jge     radv
    jmp     rgo
rz:
    xor     eax, eax
rgo:
    push    ecx
    sub     ecx, eax
    add     esi, eax
    add     edi, eax
    rep movsb
    pop     ecx
    jmp     radv2
full:
    push    esi
    push    edi
    rep movsb
    pop     edi
    pop     esi
radv:
radv2:
    mov     eax, dword ptr [{BX['X1']:#x}]
    sub     eax, dword ptr [{BX['X0']:#x}]
    add     ebx, eax
    inc     edx
    jmp     rrow
rdone:
    pop     ebx
    pop     edi
    pop     esi
    ret     8
{fill}
nat3:
    pop     ebx
    pop     edi
    pop     esi
native:
    jmp     {BOX_SPRITE:#x}
"""


# ==== tiles ======================================================================
def _tile_wrap() -> str:
    # Buffer_tile thiscall(ecx=dest)(sprite,srcX,srcY,dstX,dstY,w,h) RET 0x1C.
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    mov     eax, dword ptr [esp+0x10]
    mov     dword ptr [{RS['X0']:#x}], eax
    mov     edx, dword ptr [esp+0x18]
    add     edx, eax
    mov     dword ptr [{RS['X1']:#x}], edx
    mov     eax, dword ptr [esp+0x14]
    mov     dword ptr [{RS['Y0']:#x}], eax
    mov     edx, dword ptr [esp+0x1C]
    add     edx, eax
    mov     dword ptr [{RS['Y1']:#x}], edx
    mov     dword ptr [{RS['BUF']:#x}], ecx
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    call    {BUFFER_TILE:#x}
    call    t_dl_restripe
    ret     0x1C
native:
    jmp     {BUFFER_TILE:#x}
"""


def asm_dl_tile_bg() -> str:
    return _tile_wrap()


def asm_dl_tile_row() -> str:
    return _tile_wrap()


def asm_dl_tile_ph() -> str:
    # 2026-10-06: ONE Buffer_tile drop-in for both list sites (bg fill 0x42A140, row bg 0x42A1F7);
    # thiscall(ecx = the list canvas = Win+0x444)(sprite,srcX,srcY,dstX,dstY,w,h) RET 0x1C.
    # Phase = Win.rRect1.top + Win.rRect2.top (+0x140 / +0x150 = [ecx-0x304] / [ecx-0x2F4]), the sum
    # Win_flip_rect_2 0x5ECFE0 maps local rows to the parent with -- so the list restripes on the
    # DatalinkWin canvas grid the ring is on.  Stored raw: t_dl_restripe reduces (row + phase) by the
    # real period itself (`div P`).  Cleared after the call: the whole-canvas callers
    # (t_dl_build_leave, t_dl_cu) keep phase 0.  g <= 16: untouched tail-jump to Buffer_tile.
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    mov     eax, dword ptr [esp+0x10]
    mov     dword ptr [{RS['X0']:#x}], eax
    mov     edx, dword ptr [esp+0x18]
    add     edx, eax
    mov     dword ptr [{RS['X1']:#x}], edx
    mov     eax, dword ptr [esp+0x14]
    mov     dword ptr [{RS['Y0']:#x}], eax
    mov     edx, dword ptr [esp+0x1C]
    add     edx, eax
    mov     dword ptr [{RS['Y1']:#x}], edx
    mov     dword ptr [{RS['BUF']:#x}], ecx
    mov     eax, dword ptr [ecx-0x304]
    add     eax, dword ptr [ecx-0x2F4]
    mov     dword ptr [{PHI:#x}], eax
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    push    dword ptr [esp+0x1C]
    call    {BUFFER_TILE:#x}
    call    t_dl_restripe
    and     dword ptr [{PHI:#x}], 0
    ret     0x1C
native:
    jmp     {BUFFER_TILE:#x}
"""


# ==== tech-range levers ==========================================================
def asm_dl_hover() -> str:
    # @0x49B2F1 raw (7B -> call+2nop): add edx,eax / add ecx,-3 / add ebx,eax with eax=3 live.
    return f"""
    push    eax
    mov     eax, 3
    cmp     dword ptr [{G_DL_EXEC:#x}], 0
    je      nat
    {HD("eax")}
nat:
    add     edx, eax
    sub     ecx, eax
    add     ebx, eax
    pop     eax
    ret
"""


def asm_dl_arrowzoom() -> str:
    return f"""
    cmp     dword ptr [{G_DL_EXEC:#x}], 0
    je      native
    cmp     dword ptr [{G:#x}], 16
    jle     native
    mov     eax, dword ptr [{SCALE_NUM:#x}]
    mov     dword ptr [{CELL['g_dl_sv']:#x}], eax
    mov     eax, dword ptr [{SCALE_DEN:#x}]
    mov     dword ptr [{CELL['g_dl_sv'] + 4:#x}], eax
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{SCALE_NUM:#x}], eax
    mov     dword ptr [{SCALE_DEN:#x}], 16
    push    dword ptr [esp+0x10]
    push    dword ptr [esp+0x10]
    push    dword ptr [esp+0x10]
    push    dword ptr [esp+0x10]
    call    {BLIT_CORE:#x}
    mov     eax, dword ptr [{CELL['g_dl_sv']:#x}]
    mov     dword ptr [{SCALE_NUM:#x}], eax
    mov     eax, dword ptr [{CELL['g_dl_sv'] + 4:#x}]
    mov     dword ptr [{SCALE_DEN:#x}], eax
    ret     0x10
native:
    jmp     {BLIT_CORE:#x}
"""


def asm_dl_mono() -> str:
    # @0x49A2CF -> MONO_FN thiscall(ecx=sprite)(dest,key,x,y,col,num,den) RET 0x1C.
    return f"""
    cmp     dword ptr [{G_DL_EXEC:#x}], 0
    je      native
    cmp     dword ptr [{G:#x}], 16
    jle     native
    push    esi
    push    edi
    push    ebx
    ; args after 3 pushes: [esp+0x10]=dest [esp+0x18]=x [esp+0x1C]=y [esp+0x28]=num
    mov     eax, dword ptr [esp+0x18]
    mov     dword ptr [{MO['X']:#x}], eax
    mov     eax, dword ptr [esp+0x1C]
    mov     dword ptr [{MO['Y']:#x}], eax
    mov     eax, dword ptr [esp+0x28]
    mov     dword ptr [{MO['NUM']:#x}], eax
    mov     esi, dword ptr [esp+0x10]
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    je      nosample
    ; histogram the text band (x-s(40) .. x+s(90)) x (y-s(26) .. y-s(8)) into g_dw_cands
    push    ecx
    mov     edi, {G_DW_CANDS:#x}
    xor     eax, eax
    mov     ecx, 256
    rep stosd
    mov     dword ptr [{RS['BUF']:#x}], esi
    ; reuse RS pitch/data/h derivation via a mini copy (data/pitch only)
    mov     eax, dword ptr [esi+0x54]
    mov     dword ptr [{RS['DATA']:#x}], eax
    mov     edx, dword ptr [esi+0x4A8]
    mov     dword ptr [{RS['PITCH']:#x}], edx
    mov     eax, dword ptr [esi+0x84]
    test    eax, eax
    jns     mh
    neg     eax
mh:
    mov     dword ptr [{RS['H']:#x}], eax
    ; band bounds
    mov     eax, 40
    {HD("eax")}
    mov     edx, dword ptr [{MO['X']:#x}]
    sub     edx, eax
    jns     b0
    xor     edx, edx
b0:
    mov     dword ptr [{RS['X0']:#x}], edx
    mov     eax, 90
    {HD("eax")}
    add     eax, dword ptr [{MO['X']:#x}]
    cmp     eax, dword ptr [esi+0x80]
    jle     b1
    mov     eax, dword ptr [esi+0x80]
b1:
    mov     dword ptr [{RS['X1']:#x}], eax
    mov     eax, 26
    {HD("eax")}
    mov     edx, dword ptr [{MO['Y']:#x}]
    sub     edx, eax
    jns     b2
    xor     edx, edx
b2:
    mov     dword ptr [{RS['Y0']:#x}], edx
    mov     eax, 8
    {HD("eax")}
    mov     edx, dword ptr [{MO['Y']:#x}]
    sub     edx, eax
    jns     b3
    xor     edx, edx
b3:
    mov     dword ptr [{RS['Y1']:#x}], edx
    ; count
    mov     edi, dword ptr [{RS['Y0']:#x}]
my:
    cmp     edi, dword ptr [{RS['Y1']:#x}]
    jge     mcount
    mov     esi, edi
    imul    esi, dword ptr [{RS['PITCH']:#x}]
    add     esi, dword ptr [{RS['DATA']:#x}]
    mov     ebx, dword ptr [{RS['X0']:#x}]
mx:
    cmp     ebx, dword ptr [{RS['X1']:#x}]
    jge     mrow
    movzx   eax, byte ptr [esi+ebx]
    inc     dword ptr [{G_DW_CANDS:#x}+eax*4]
    inc     ebx
    jmp     mx
mrow:
    inc     edi
    jmp     my
mcount:
    ; argmax over bright entries (palette r+g+b > 120)
    xor     esi, esi
    xor     edi, edi
    mov     dword ptr [{MO['BEST']:#x}], 0x0F
mnext:
    cmp     esi, 256
    jge     mdone
    movzx   eax, byte ptr [{PALETTE:#x}+esi*4]
    movzx   edx, byte ptr [{PALETTE + 1:#x}+esi*4]
    add     eax, edx
    movzx   edx, byte ptr [{PALETTE + 2:#x}+esi*4]
    add     eax, edx
    cmp     eax, 120
    jle     mskip
    mov     eax, dword ptr [{G_DW_CANDS:#x}+esi*4]
    cmp     eax, edi
    jle     mskip
    mov     edi, eax
    mov     dword ptr [{MO['BEST']:#x}], esi
mskip:
    inc     esi
    jmp     mnext
mdone:
    pop     ecx
nosample:
    ; call the original (re-push 7)
    push    dword ptr [esp+0x28]
    push    dword ptr [esp+0x28]
    push    dword ptr [esp+0x28]
    push    dword ptr [esp+0x28]
    push    dword ptr [esp+0x28]
    push    dword ptr [esp+0x28]
    push    dword ptr [esp+0x28]
    call    {MONO_FN:#x}
    ; recolour idx 0x0F -> BEST in rect (x-1, y-1, +num+4, +2*num+4)
    mov     esi, dword ptr [esp+0x10]
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    je      mout
    mov     eax, dword ptr [{MO['X']:#x}]
    dec     eax
    jns     r0
    xor     eax, eax
r0:
    mov     dword ptr [{RS['X0']:#x}], eax
    mov     edx, dword ptr [{MO['NUM']:#x}]
    add     edx, 4
    add     edx, eax
    cmp     edx, dword ptr [esi+0x80]
    jle     r1
    mov     edx, dword ptr [esi+0x80]
r1:
    mov     dword ptr [{RS['X1']:#x}], edx
    mov     eax, dword ptr [{MO['Y']:#x}]
    dec     eax
    jns     r2
    xor     eax, eax
r2:
    mov     dword ptr [{RS['Y0']:#x}], eax
    mov     edx, dword ptr [{MO['NUM']:#x}]
    add     edx, edx
    add     edx, 4
    add     edx, eax
    cmp     edx, dword ptr [{RS['H']:#x}]
    jle     r3
    mov     edx, dword ptr [{RS['H']:#x}]
r3:
    mov     dword ptr [{RS['Y1']:#x}], edx
    mov     edi, dword ptr [{RS['Y0']:#x}]
qy:
    cmp     edi, dword ptr [{RS['Y1']:#x}]
    jge     mout
    mov     esi, edi
    imul    esi, dword ptr [{RS['PITCH']:#x}]
    add     esi, dword ptr [{RS['DATA']:#x}]
    mov     ebx, dword ptr [{RS['X0']:#x}]
qx:
    cmp     ebx, dword ptr [{RS['X1']:#x}]
    jge     qrow
    cmp     byte ptr [esi+ebx], 0x0F
    jne     qnext
    mov     eax, dword ptr [{MO['BEST']:#x}]
    mov     byte ptr [esi+ebx], al
qnext:
    inc     ebx
    jmp     qx
qrow:
    inc     edi
    jmp     qy
mout:
    pop     ebx
    pop     edi
    pop     esi
    ret     0x1C
native:
    jmp     {MONO_FN:#x}
"""


def asm_dl_btnrect() -> str:
    # @0x607F60 (Buffer_box_sprite of the FlatButton face): g_btn_pending -> native-sized rect.
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    cmp     dword ptr [{G_BTN_PENDING:#x}], 1
    jne     native
    push    ebx
    mov     eax, dword ptr [esp+8]
    mov     edx, dword ptr [eax+8]
    sub     edx, dword ptr [eax]
    mov     ebx, dword ptr [esi+0x4C4]
    cmp     edx, ebx
    jle     natpop
    mov     edx, dword ptr [eax]
    mov     dword ptr [{G_DW_RECT2:#x}], edx
    add     edx, ebx
    mov     dword ptr [{G_DW_RECT2 + 8:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{G_DW_RECT2 + 4:#x}], edx
    mov     ebx, dword ptr [esi+0x4C8]
    neg     ebx
    add     edx, ebx
    mov     dword ptr [{G_DW_RECT2 + 12:#x}], edx
    mov     dword ptr [esp+8], {G_DW_RECT2:#x}
    pop     ebx
    jmp     {BOX_SPRITE:#x}
natpop:
    pop     ebx
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_dl_techwrap() -> str:
    # E8-redirect of the two DL callers of ReportWin_tech_page (fastcall ecx, no stack args).
    # textB/lineH scale ONCE (SL.dl_tech_inputs): only the vanilla state textB == win_h - 0x35;
    # the rw_scale_shared init lever leaves both as device values.
    # 2026-10-17: win_h = RW+0x5990 (the frame rect bottom; init_report_screen / t_rw_init_leave only), NOT
    # RW+0xA20: ReportWin_tech_reset overwrites +0xA20 with textB - clipT on every page paint. Both DL callers
    # run tech_reset right before this wrapper (0x42C1D2 / 0x430BD0), so the old +0xA20 identity was DEAD in every
    # state. It now fires only in the native state at g>16, i.e. when the rw_scale_shared init lever was skipped
    # (t_rw_init_leave's VirtualProtect bootstrap failed); the real DL device state is byte-identical.
    return f"""
    push    esi
    mov     esi, {RW:#x}
    mov     eax, dword ptr [esi+0x5980]
    mov     dword ptr [{TS['TEXTB']:#x}], eax
    mov     edx, dword ptr [esi+0xE268]
    mov     dword ptr [{TS['LINEH']:#x}], edx
    cmp     dword ptr [{G:#x}], 16
    jle     nof
    add     eax, 0x35
    cmp     eax, dword ptr [esi+0x5990]
    jne     sk2
    sub     eax, 0x35
    {HD("eax")}
    mov     dword ptr [esi+0x5980], eax
    {HD("edx")}
    mov     dword ptr [esi+0xE268], edx
sk2:
    mov     eax, dword ptr [{MODEIDX:#x}]
    cmp     eax, 0
    jl      nof
    cmp     eax, 63
    jg      nof
    lea     eax, [{MODETAB:#x}+eax*4]
    mov     dword ptr [{TS['SLOTP']:#x}], eax
    mov     edx, dword ptr [eax]
    mov     dword ptr [{TS['SLOTV']:#x}], edx
    mov     dword ptr [eax], 8
    call    {TECH_PAGE:#x}
    mov     eax, dword ptr [{TS['SLOTP']:#x}]
    mov     edx, dword ptr [{TS['SLOTV']:#x}]
    mov     dword ptr [eax], edx
    jmp     rest
nof:
    call    {TECH_PAGE:#x}
rest:
    mov     eax, dword ptr [{TS['TEXTB']:#x}]
    mov     dword ptr [{RW + 0x5980:#x}], eax
    mov     eax, dword ptr [{TS['LINEH']:#x}]
    mov     dword ptr [{RW + 0xE268:#x}], eax
    pop     esi
    ret
"""


def asm_dl_wininit() -> str:
    # detour @Win_init 0x5EBD80 (6B displaced: mov eax,fs:[0])
    return f"""
    cmp     ecx, {LISTWIN:#x}
    jne     nat
    cmp     dword ptr [{G:#x}], 16
    jle     nat
    inc     dword ptr [{G_POPUP_ACTIVE:#x}]
    pop     eax
    mov     dword ptr [{CELL['g_dl_wret']:#x}], eax
    push    t_dl_wininit_leave
nat:
    mov     eax, dword ptr fs:[0]
    jmp     {WININIT_RESUME:#x}
"""


def asm_dl_wininit_leave() -> str:
    return f"""
    dec     dword ptr [{G_POPUP_ACTIVE:#x}]
    jmp     dword ptr [{CELL['g_dl_wret']:#x}]
"""


def asm_cr_snap_dl() -> str:
    # Clone of diplo t_cr_snap with the DL on_mode tail (shares the g_cr_* cells + buffer).
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     cr_pass
    cmp     dword ptr [esp+4], 0
    je      cr_pass
    pushad
    mov     eax, dword ptr [{SEED_D80 + 8:#x}]
    dec     eax
    mov     dword ptr [{CRL:#x}], eax
    mov     edx, dword ptr [{SEED_D90:#x}]
    mov     dword ptr [{CRR:#x}], edx
    mov     ecx, dword ptr [{SEED_DB0 + 4:#x}]
    add     ecx, 2
    mov     dword ptr [{CRB:#x}], ecx
    mov     ebx, dword ptr [{CRBUF:#x}]
    test    ebx, ebx
    jnz     cr_have
    mov     eax, edx
    sub     eax, dword ptr [{CRL:#x}]
    imul    eax, ecx
    push    4
    push    0x3000
    push    eax
    push    0
    call    dword ptr [{IAT_VIRTUALALLOC:#x}]
    test    eax, eax
    jz      cr_bail
    mov     dword ptr [{CRBUF:#x}], eax
    mov     ebx, eax
cr_have:
    mov     esi, dword ptr [{CANVAS_DATA:#x}]
    test    esi, esi
    jz      cr_bail
    add     esi, dword ptr [{CRL:#x}]
    mov     edi, ebx
    mov     edx, dword ptr [{CRR:#x}]
    sub     edx, dword ptr [{CRL:#x}]
    mov     ebp, dword ptr [{CRB:#x}]
cr_row:
    push    esi
    push    edi
    mov     ecx, edx
    rep movsb
    pop     edi
    pop     esi
    add     esi, dword ptr [{CANVAS_STRIDE:#x}]
    add     edi, edx
    dec     ebp
    jnz     cr_row
    call {T_CR_MARK:#x}
    .byte 0x0F, 0x1F, 0x40, 0x00
cr_bail:
    popad
cr_pass:
    jmp     {ONMODE:#x}
"""


# ==== register fixups ============================================================
def asm_dl_rf1() -> str:  # @0x431238: add eax,0x4B / mov [ebp-0x58],ecx  -> eax += s(75)
    return f"""
    push    ecx
    mov     ecx, 75
    {HD("ecx")}
    add     eax, ecx
    pop     ecx
    mov     dword ptr [ebp-0x58], ecx
    jmp     0x43123E
"""


def asm_dl_rf2() -> str:  # @0x431250: lea edx,[esi+0x64] / cmp eax,0x10 -> edx = esi + s(100)
    return f"""
    push    eax
    mov     eax, 100
    {HD("eax")}
    lea     edx, [esi+eax]
    pop     eax
    cmp     eax, 0x10
    jmp     0x431256
"""


def asm_dl_rf3() -> str:  # @0x4316B3: add esi,0x67 / mov [ebp-0x3C],esi -> esi += s(103)
    return f"""
    push    eax
    mov     eax, 103
    {HD("eax")}
    add     esi, eax
    pop     eax
    mov     dword ptr [ebp-0x3C], esi
    jmp     0x4316B9
"""


def asm_dl_rf4() -> str:  # @0x43196F: (edi<0x10 || edi>0x12 -> ecx += s(103)-103) then the natives
    return f"""
    cmp     edi, 0x10
    jl      fix
    cmp     edi, 0x12
    jle     nof
fix:
    push    eax
    mov     eax, 103
    {HD("eax")}
    sub     eax, 103
    add     ecx, eax
    pop     eax
nof:
    sub     eax, ecx
    push    ebx
    push    eax
    push    edx
    jmp     0x431974
"""


def asm_dl_rf5() -> str:  # @0x49A2B1 (tech): sub eax,0x34 -> sub eax,s(52); push edx / cdq replayed
    return f"""
    cmp     dword ptr [{G_DL_EXEC:#x}], 0
    je      nat
    push    edx
    mov     edx, 52
    {HD("edx")}
    sub     eax, edx
    pop     edx
    jmp     cont
nat:
    sub     eax, 0x34
cont:
    push    edx
    cdq
    jmp     0x49A2B6
"""


def asm_dl_rf6() -> str:  # @0x49A2DA (tech): add eax,0x3A -> add eax,s(58); mov [ebp-8],eax replayed
    return f"""
    cmp     dword ptr [{G_DL_EXEC:#x}], 0
    je      nat
    push    edx
    mov     edx, 58
    {HD("edx")}
    add     eax, edx
    pop     edx
    jmp     stz
nat:
    add     eax, 0x3A
stz:
    mov     dword ptr [ebp-8], eax
    jmp     0x49A2E0
"""


def asm_ts_cache() -> str:
    # Article flow cache builder (VANILLA line-break-jump fix). Contract: ebx=TS, esi=list,
    # ebp=width, edi=g_ts_flowcache; preserves ebx/esi/edi; engine callees preserve the rest.
    # For each PARAGRAPH HEAD node (idx 0, or node flag != 0 - the file's ^ prefixes), measures the
    # flow height from that head to the end with the engine's own measurer (cursor pre-positioned,
    # flags=2) and stores cum_px = H0 - Hi = the paragraph's pixel offset in the CANONICAL full
    # flow. Also repoints the embedded bar's range to wrapped LINES (vanilla wrote the NODE count
    # at TextScroll_finish: TS+0x1444 max / TS+0x1460 page) and total/visible bookkeeping.
    return f"""
    mov     dword ptr [edi+4], ebp
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    mov     dword ptr [edi], ebx
    mov     eax, dword ptr [esi+8]
    mov     dword ptr [edi+8], eax
    mov     eax, dword ptr [esi+0x10]
    mov     dword ptr [edi+0xC], eax
    lea     ecx, [ebx+0x444]
    call    {LINEH_FN:#x}
    test    eax, eax
    jnz     ch0
    mov     eax, 12
ch0:
    mov     dword ptr [edi+0x10], eax
    mov     eax, dword ptr [ebx+0x4C8]
    neg     eax
    xor     edx, edx
    div     dword ptr [edi+0x10]
    mov     dword ptr [edi+0x1C], eax
    push    0
    push    dword ptr [edi+4]
    push    esi
    lea     ecx, [ebx+0x444]
    call    {WSH:#x}
    mov     dword ptr [edi+0x20], eax
    add     eax, dword ptr [edi+0x10]
    dec     eax
    xor     edx, edx
    div     dword ptr [edi+0x10]
    mov     dword ptr [edi+0x14], eax
    mov     edx, eax
    sub     edx, dword ptr [edi+0x1C]
    jns     ch1
    xor     edx, edx
ch1:
    mov     dword ptr [ebx+0x1444], edx
    mov     dword ptr [ebx+0x1440], 0
    mov     eax, dword ptr [edi+0x1C]
    dec     eax
    jg      ch2
    mov     eax, 1
ch2:
    mov     dword ptr [ebx+0x1460], eax
    mov     eax, dword ptr [esi+8]
    mov     dword ptr [ebp-4], eax
    mov     dword ptr [ebp-8], 0
    lea     eax, [edi+0x24]
    mov     dword ptr [ebp-0xC], eax
    mov     dword ptr [edi+0x18], 0
cw0:
    mov     eax, dword ptr [ebp-8]
    cmp     eax, dword ptr [edi+0xC]
    jge     cwx
    mov     eax, dword ptr [ebp-4]
    test    eax, eax
    jz      cwx
    cmp     dword ptr [ebp-8], 0
    je      cw1
    mov     ecx, dword ptr [eax+8]
    cmp     dword ptr [ecx+8], 0
    je      cw2
cw1:
    cmp     dword ptr [edi+0x18], 320
    jge     cw2
    mov     dword ptr [esi+0xC], eax
    mov     ecx, dword ptr [ebp-8]
    mov     dword ptr [esi+0x14], ecx
    push    2
    push    dword ptr [edi+4]
    push    esi
    lea     ecx, [ebx+0x444]
    call    {WSH:#x}
    mov     ecx, dword ptr [ebp-0xC]
    mov     edx, dword ptr [ebp-4]
    mov     dword ptr [ecx], edx
    mov     edx, dword ptr [ebp-8]
    mov     dword ptr [ecx+4], edx
    mov     edx, dword ptr [edi+0x20]
    sub     edx, eax
    mov     dword ptr [ecx+8], edx
    add     ecx, 12
    mov     dword ptr [ebp-0xC], ecx
    inc     dword ptr [edi+0x18]
cw2:
    mov     eax, dword ptr [ebp-4]
    mov     eax, dword ptr [eax+0xC]
    mov     dword ptr [ebp-4], eax
    inc     dword ptr [ebp-8]
    jmp     cw0
cwx:
    mov     esp, ebp
    pop     ebp
    ret
"""


def asm_ts_flowdraw() -> str:
    # E8 redirect @0x629C26 (TextScroll_draw mode-0 `call Buffer_write_strings`). VANILLA BUG FIX:
    # a scrolled draw entered the node FLOW mid-paragraph with fresh wrap/link state, so line
    # breaks re-flowed while scrolling and a $LINK tag opened in a skipped node rendered literally.
    # DL TextScrolls with first_line k >= 0: ensure the flow cache (lazily keyed on
    # ts/width/head/count - self-heals on article switch and bar show/hide), clamp k to
    # total-visible, start the flow at the PARAGRAPH HEAD containing line k and pass
    # y0 = cum_px - k*lineH (<= 0; GDI TextOutA clips the off-canvas lines above). Break points
    # and link tags now always match the canonical top-down flow at every scroll position.
    # Non-DL TextScrolls and negative k (bottom-anchored consoles) pass through untouched.
    return f"""
    lea     eax, [ecx-0x444]
    cmp     eax, {TS_FULL:#x}
    je      fd0
    cmp     eax, {TS_LOWER:#x}
    je      fd0
    cmp     eax, {TS_LOWER800:#x}
    je      fd0
    cmp     eax, {TS_CONSOLE:#x}
    jne     fdn
fd0:
    cmp     dword ptr [eax+0xA1C], 0
    jl      fdn
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebx, eax
    mov     esi, dword ptr [esp+0x14]
    mov     ebp, dword ptr [esp+0x20]
    mov     edi, {FLOW:#x}
    cmp     dword ptr [edi], ebx
    jne     fdr
    cmp     dword ptr [edi+4], ebp
    jne     fdr
    mov     eax, dword ptr [esi+8]
    cmp     dword ptr [edi+8], eax
    jne     fdr
    mov     eax, dword ptr [esi+0x10]
    cmp     dword ptr [edi+0xC], eax
    je      fdh
fdr:
    call    t_ts_cache
fdh:
    cmp     dword ptr [edi+0x18], 0
    je      fdq
    mov     eax, dword ptr [ebx+0xA1C]
    mov     ecx, dword ptr [edi+0x14]
    sub     ecx, dword ptr [edi+0x1C]
    jns     fd1
    xor     ecx, ecx
fd1:
    cmp     eax, ecx
    jle     fd2
    mov     eax, ecx
    mov     dword ptr [ebx+0xA1C], eax
fd2:
    imul    eax, dword ptr [edi+0x10]
    mov     edx, dword ptr [edi+0x18]
    lea     ecx, [edi+0x24]
fd3:
    cmp     edx, 1
    jle     fd4
    cmp     dword ptr [ecx+0x14], eax
    jg      fd4
    add     ecx, 12
    dec     edx
    jmp     fd3
fd4:
    mov     edx, dword ptr [ecx]
    mov     dword ptr [esi+0xC], edx
    mov     edx, dword ptr [ecx+4]
    mov     dword ptr [esi+0x14], edx
    mov     ecx, dword ptr [ecx+8]
    sub     ecx, eax
    mov     dword ptr [esp+0x1C], ecx
fdq:
    lea     ecx, [ebx+0x444]
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
fdn:
    jmp     {WRITE_STRINGS:#x}
"""


def asm_dl_portrait() -> str:
    # E8-entered @0x430DA3 (draw_faction). Native pushes num=1/den=1 (1:1 portrait). g>16: re-push
    # the six args with num=g/den=16 and, around the call only, poke thunk_portrait_avg's dest-gate
    # imm (pcave2+0xA05: `cmp eax,0x940824`) to the DL canvas so the A5 palette-aware bilinear
    # resampler handles the enlarge (its own guards fall back to the native NN scale on any oddity).
    # Single-threaded UI; the poke window is exactly this call. ecx = Sprite* passes through.
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 16
    jg      big
    jmp     {SPRITE_DRAW2:#x}
big:
    mov     dword ptr [{PAVG_GATE_IMM:#x}], {CANVAS:#x}
    push    16
    push    eax
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    call    {ART_DRAW:#x}                 ; 2026-09-20: bilinear alone still banded the portrait's scanlines (1600 + 1920 shots)
    mov     dword ptr [{PAVG_GATE_IMM:#x}], {FACTION_BOX:#x}
    ret     0x18
"""


def asm_dl_portw() -> str:
    # detour @0x430DA8: `mov ebx,[ebx+0x78EEE4]` loads the NATIVE portrait width for the profile-
    # text x advance (x + w + s(5)); substitute the DRAWN width fl(w*g/16). eax dead (@0x430DAE
    # reloads it); no flag consumer before the next test.
    return f"""
    mov     ebx, dword ptr [ebx+{PORTRAIT_W_FIELD:#x}]
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 16
    jle     done
    imul    ebx, eax
    shr     ebx, 4
done:
    jmp     {PORTW_RESUME:#x}
"""


def asm_dl_wheel_down() -> str:
    # Wheel-notch KEYDOWN (PRACX synthetic VK_UP/DOWN, lParam 0) while the Datalinks modal is the
    # top: chevron-scroll the first ENGAGED bar - the category list's heap V-bar [LISTWIN+0x43C]
    # first, else the VISIBLE page TextScroll (+0x10514 full / +0x15C54 lower / +0x187F4 800-only /
    # console +0x130B4) - then present the owning window. The notch NEVER moves the list selection
    # (swallowed even when nothing is engaged; real arrow keys carry a scan code and pass through).
    # Every non-DL context chains to the dw thunk_wheel_down unchanged. UNGATED on g (vanilla
    # behaviour change, the DW wheel_scroll decision).
    #
    # v2 2026-09-22 (user: "the category picker captures the wheel everywhere, EXCEPT over an
    # article with its own scroll box"): the cursor (client space) is read first. Inside the ARTICLE
    # panel (right_container +0x103B4, DL-local) the visible engaged page TextScroll (full / lower /
    # lower800) takes the notch; inside the console text box (+0x10374, MainWin-local) the console
    # TextScroll does. Otherwise - or when no text under the cursor is engaged - the old order holds:
    # the category list first, then any visible engaged TextScroll. try_ts is a local helper:
    # esi = TextScroll; visible + engaged -> drops its return address and jumps to `have` with
    # edi = its bar; else returns. ebx (chevron id) is fixed BEFORE the cursor calls clobber edx.
    def scan(tss):
        return "".join(f"\n    mov     esi, {ts:#x}\n    call    try_ts" for ts in tss)

    return f"""
    cmp     dword ptr [{BASEPOP:#x}], 0
    jne     chain
    cmp     dword ptr [{MODAL_TOP:#x}], {OBJ:#x}
    jne     chain
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
    mov     ebx, 1
    cmp     edx, 0x26
    je      dir
    mov     ebx, 2
dir:
    sub     esp, 8
    push    esp
    call    dword ptr [{IAT_GETCURSORPOS:#x}]
    push    esp
    push    dword ptr [{G_HWND:#x}]
    call    {WHEEL_STC:#x}
    nop
    pop     eax
    pop     edx
    mov     esi, eax
    mov     edi, edx
    sub     eax, dword ptr [{OBJ + 0x13C:#x}]
    sub     edx, dword ptr [{OBJ + 0x140:#x}]
    cmp     eax, dword ptr [{RC_ARTICLE:#x}]
    jl      nopanel
    cmp     eax, dword ptr [{RC_ARTICLE + 8:#x}]
    jge     nopanel
    cmp     edx, dword ptr [{RC_ARTICLE + 4:#x}]
    jl      nopanel
    cmp     edx, dword ptr [{RC_ARTICLE + 12:#x}]
    jge     nopanel{scan((TS_FULL, TS_LOWER, TS_LOWER800))}
    jmp     lst
nopanel:
    mov     eax, esi
    mov     edx, edi
    sub     eax, dword ptr [{MW + 0x13C:#x}]
    sub     edx, dword ptr [{MW + 0x140:#x}]
    cmp     eax, dword ptr [{RC_CONSOLE:#x}]
    jl      lst
    cmp     eax, dword ptr [{RC_CONSOLE + 8:#x}]
    jge     lst
    cmp     edx, dword ptr [{RC_CONSOLE + 4:#x}]
    jl      lst
    cmp     edx, dword ptr [{RC_CONSOLE + 12:#x}]
    jge     lst{scan((TS_CONSOLE,))}
lst:
    mov     esi, {LISTWIN:#x}
    mov     edi, dword ptr [esi+0x43C]
    test    edi, edi
    jz      fb
    test    byte ptr [edi+0x9C], 1
    jz      fb
    cmp     dword ptr [edi+0xC4], 0
    je      fb
    mov     ecx, dword ptr [edi+0xA24]
    cmp     ecx, dword ptr [edi+0xA20]
    jg      have
fb:{scan((TS_FULL, TS_LOWER, TS_LOWER800, TS_CONSOLE))}
    jmp     eaten
try_ts:
    test    byte ptr [esi+0x9C], 1
    jz      tsno
    lea     edi, [esi+0xA20]
    cmp     dword ptr [edi+0xC4], 0
    je      tsno
    mov     ecx, dword ptr [edi+0xA24]
    cmp     ecx, dword ptr [edi+0xA20]
    jle     tsno
    add     esp, 4
    jmp     have
tsno:
    ret
have:
    push    ebx
    mov     ecx, edi
    call    {CHEVRON:#x}
    mov     edx, dword ptr [esi]
    mov     ecx, esi
    call    dword ptr [edx+0xFC]
eaten:
    xor     eax, eax
    pop     edi
    pop     esi
    pop     ebx
    ret
xout:
    ret
chain:
    jmp     {DW_WHEEL_DOWN:#x}
"""


def asm_dl_wheel_up() -> str:
    # The matching synthetic KEYUP: swallowed whenever the DL modal is the top, so the notch never
    # reaches the key handler at all. Non-DL contexts chain to the dw thunk_wheel_up.
    return f"""
    cmp     dword ptr [{BASEPOP:#x}], 0
    jne     chain
    cmp     dword ptr [{MODAL_TOP:#x}], {OBJ:#x}
    jne     chain
    call    {GET_TARGET:#x}
    test    eax, eax
    jz      xout
    cmp     dword ptr [esp+0x6C], 0
    jne     xout
    mov     edx, dword ptr [esp+0x68]
    cmp     edx, 0x26
    je      eat
    cmp     edx, 0x28
    jne     xout
eat:
    xor     eax, eax
xout:
    ret
chain:
    jmp     {DW_WHEEL_UP:#x}
"""


# ==== layout =====================================================================
NEW_THUNKS = [
    ("t_dl_immfix", asm_dl_immfix, "dl_scale"),
    ("t_dl_immfix_main", asm_dl_immfix_main, "dl_scale"),
    ("t_dl_immfix_tech", asm_dl_immfix_tech, "dl_scale"),
    ("t_dl_build_enter", asm_dl_build_enter, "dl_scale"),
    ("t_dl_build_leave", asm_dl_build_leave, "dl_scale"),
    ("t_dl_exec_enter", asm_dl_exec_enter, "dl_scale"),
    ("t_dl_exec_leave", asm_dl_exec_leave, "dl_scale"),
    ("t_dl_restripe", asm_dl_restripe, "dl_scale"),
    ("t_dl_cu", asm_dl_cu, "dl_scale"),
    ("t_dl_bm", asm_dl_bm, "dl_scale"),
    ("t_dl_bmdf", asm_dl_bmdf, "dl_scale"),
    ("t_dl_bmt", asm_dl_bmt, "dl_scale"),
    ("t_dl_bmxt", asm_dl_bmxt, "dl_scale"),
    ("t_dl_tile_bg", asm_dl_tile_bg, "dl_scale"),
    ("t_dl_tile_row", asm_dl_tile_row, "dl_scale"),
    ("t_dl_hover", asm_dl_hover, "dl_scale"),
    ("t_dl_arrowzoom", asm_dl_arrowzoom, "dl_scale"),
    ("t_dl_mono", asm_dl_mono, "dl_scale"),
    ("t_dl_btnrect", asm_dl_btnrect, "dl_scale"),
    ("t_dl_techwrap", asm_dl_techwrap, "dl_scale"),
    ("t_dl_wininit", asm_dl_wininit, "dl_scale"),
    ("t_dl_wininit_leave", asm_dl_wininit_leave, "dl_scale"),
    ("t_cr_snap_dl", asm_cr_snap_dl, "dl_scale"),
    ("t_dl_rf1", asm_dl_rf1, "dl_scale"),
    ("t_dl_rf2", asm_dl_rf2, "dl_scale"),
    ("t_dl_rf3", asm_dl_rf3, "dl_scale"),
    ("t_dl_rf4", asm_dl_rf4, "dl_scale"),
    ("t_dl_rf5", asm_dl_rf5, "dl_scale"),
    ("t_dl_rf6", asm_dl_rf6, "dl_scale"),
    ("t_dl_portrait", asm_dl_portrait, "dl_scale"),
    ("t_dl_portw", asm_dl_portw, "dl_scale"),
    ("t_dl_wheel_down", asm_dl_wheel_down, "dl_scale"),
    ("t_dl_wheel_up", asm_dl_wheel_up, "dl_scale"),
    ("t_ts_cache", asm_ts_cache, "dl_scale"),
    ("t_ts_flowdraw", asm_ts_flowdraw, "dl_scale"),
    ("t_dl_tile_ph", asm_dl_tile_ph, "dl_scale"),
]
DATA = [("g_dl_immtab_main", lambda: MAIN_TAB), ("g_dl_immtab_tech", lambda: TECH_TAB)]
PINNED = {"t_dl_wheel_down": WHEEL_DOWN_OFF, "t_dl_wheel_up": 0x23210, "t_dl_tile_ph": TILE_PH_OFF}


def assemble_all():
    layout = {}
    names = {n: 0 for n, _f, _g in NEW_THUNKS}
    for _pass in range(6):
        off = OFF_CODE
        prev = dict(names)
        for name, fn, _g in NEW_THUNKS:
            # PINNED: t_dl_wheel_down v2 (2026-09-22) outgrew its 352 B slot and lives at
            # WHEEL_DOWN_OFF; t_dl_wheel_up stays at its baked 0x23210 so nothing after it moves
            # (splice_dl.py is not re-runnable - single entries are ported byte-safely).
            at = PINNED.get(name, off)
            b = SE.assemble(fn(), PCAVE2 + at, names)
            layout[name] = (at, b)
            names[name] = PCAVE2 + at
            if at >= off:
                off = (at + len(b) + 15) & ~15
        if names == prev:
            break
    else:
        raise RuntimeError("thunk layout did not converge")
    end = off
    for name, fn in DATA:
        o = dict(CELLS_BY)[name][0] if False else None
    layout["g_dl_immtab_main"] = (OFF_TAB_MAIN, MAIN_TAB)
    layout["g_dl_immtab_tech"] = (OFF_TAB_TECH, TECH_TAB)
    return layout, end, names


CELLS_BY = {n: (o, s) for n, o, s in CELLS}

SYM_ABS = {
    G: "g_popup_scale_num", HOLLOWFLAT: "thunk_box_thick_hollow_flat", DEVFILL: "thunk_box_thick_devfill",
    BOX_SPRITE: "Buffer_box_sprite", G_NETWIN: "g_netwin_active", G_POPUP_ACTIVE: "g_popup_active",
    G_BTN_PENDING: "g_btn_pending", G_FSR: "g_faction_scratch_rect", G_FC_EXACT: "g_fc_exact",
    STR_K32: "g_ed_str_k32", STR_VP: "g_ed_str_vp",
    CRBUF: "g_cr_buf", CRL: "g_cr_L", CRR: "g_cr_R", CRB: "g_cr_B", CRARM: "g_cr_armed",
    T_DL_SNAPCHK: "t_dl_snapchk",
}


def templatize(b: bytes, va: int, names: dict[str, int]) -> str:
    syms = dict(SYM_ABS)
    syms.update({v: n for n, v in names.items()})
    syms[TAB_MAIN] = "g_dl_immtab_main"
    syms[TAB_TECH] = "g_dl_immtab_tech"
    syms[ART_DRAW] = "thunk_art_draw"
    syms[WHEEL_STC] = "t_wheel_stc"
    for n, (o, _s) in CELLS_BY.items():
        if n.startswith("g_dl_") and not n.startswith("g_dl_immtab"):
            syms[PCAVE2 + o] = n
    return SE.templatize(b, va, syms)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- sites -------------------------------------------------------------------
# 2026-10-25 W6C: the F2 research bracket 1 (ReportWin_tech_page, never run by Datalinks) draws through t_rw_br1
# (assemble_rw_ring.py): t_dl_bmxt, then the increment restriped on the device grid so the K-row ring keeps its phase.
SITE_TARGET_OVERRIDE = {0x499328: "t_rw_br1"}


def site_list(names: dict[str, int]) -> list[dict]:
    S = []

    def add(sid, fn, va, orig, new, pattern, note=""):
        S.append({"id": sid, "group": "dl_scale", "function": fn, "va": va, "orig": orig,
                  "new": new, "pattern": pattern, "note": note})

    def redirect(sid, fn, va, native_target, thunk, note=""):
        orig = bytes([0xE8]) + struct.pack("<i", native_target - (va + 5))
        add(sid, fn, va, orig, f"E8 {{rel32:{thunk}}}", "call_target_redirect", note)

    def detour(sid, fn, va, ln, thunk, note=""):
        orig = SE.base_exe_bytes(va, ln)
        jmp = hx(bytes([0xE9]) + struct.pack("<i", names[thunk] - (va + 5)))
        add(sid, fn, va, orig, jmp + " 90" * (ln - 5), "detour_inplace", f"{note} (E9 -> {thunk})")

    detour("DatalinkWin_build.enter", "DatalinkWin_build", BUILD, 5, "t_dl_build_enter",
           "prologue replay + ret swap -> t_dl_build_leave: immfix(MAIN) once, netwin bracket, faces, canvas restripe")
    detour("DatalinkWin_open.enter", "DatalinkWin_open", EXEC, 8, "t_dl_exec_enter",
           "prologue replay + ret swap -> t_dl_exec_leave: immfix(TECH) applied/REVERTED (ReportWin-shared range), netwin + g_dl_exec bracket")
    detour("DatalinkWin_render_topic.cu_restripe", "DatalinkWin_render_topic", CU_DETOUR, 6, "t_dl_cu",
           "content_union restripe after the three frames, before the painter switch (cmp replayed last)")
    detour("Win_init.dl_listbox_bracket", "Win_init", WININIT, 6, "t_dl_wininit",
           "ecx==DL ListBox -> g_popup_active++ bracket (scrollbar geometry at attach)")
    detour("terraform.diamond_y75", "DatalinkWin_terraform_painter", 0x431238, 6, "t_dl_rf1", "imm8 overflow: y+75 -> +s(75)")
    detour("terraform.diamond_x100", "DatalinkWin_terraform_painter", 0x431250, 6, "t_dl_rf2", "imm8 overflow: x+100 -> +s(100)")
    detour("terraform.stats_x103", "DatalinkWin_terraform_painter", 0x4316B3, 6, "t_dl_rf3", "imm8 overflow: x+103 -> +s(103)")
    detour("terraform.lower_x103", "DatalinkWin_terraform_painter", 0x43196F, 5, "t_dl_rf4", "imm8 overflow: cond x+103 -> +s(103)")
    detour("tech.icon_span52", "ReportWin_tech_page", 0x49A2B1, 5, "t_dl_rf5", "imm8 overflow (g_dl_exec-gated): span 52")
    detour("tech.icon_yadv58", "ReportWin_tech_page", 0x49A2DA, 6, "t_dl_rf6", "imm8 overflow (g_dl_exec-gated): y+58")

    for va, setname, kind in GEN.FRAME_SITES:
        tech = GEN.TECH_LO <= va < GEN.TECH_HI
        th = {"HF": ("t_dl_bmt" if tech else "t_dl_bm"),
              "DF": "t_dl_bmdf",
              "HC": "t_dl_bmxt"}[kind]
        th = SITE_TARGET_OVERRIDE.get(va, th)
        redirect(f"frame_{va:06x}", "DatalinkWin frames", va, BOX_SPRITE, th, f"{setname} [{kind}]")

    redirect("list_bg.tile", "DatalinkWin_list_bg_fill", 0x42A140, BUFFER_TILE, "t_dl_tile_ph", "tile + P-law restripe on the parent grid (phase = list top in DatalinkWin)")
    redirect("list_row.tile", "DatalinkWin_list_row_bg", 0x42A1F7, BUFFER_TILE, "t_dl_tile_ph", "row tile + restripe on the parent grid (canonical pair order)")
    for va in (0x49B702, 0x49B7B4, 0x49B917, 0x49BA3D, 0x49BB63):
        redirect(f"arrow_{va:06x}", "tech_connector", va, BLIT_CORE, "t_dl_arrowzoom", "chevron zoom g:16 (g_dl_exec-gated)")
    redirect("tech.mono_icon", "ReportWin_tech_page", 0x49A2CF, MONO_FN, "t_dl_mono", "scaled icon + mono recolour to the category text colour")
    redirect("flatbutton.face_rect", "FlatButton_content_draw", 0x607F60, BOX_SPRITE, "t_dl_btnrect", "native-sized face rect when g_btn_pending (BACK/EXIT hover clip)")
    for va in (0x42C1F2, 0x430BF0):
        redirect(f"techpage_wrap_{va:06x}", "DatalinkWin dispatch", va, TECH_PAGE, "t_dl_techwrap", "RW textB/lineH scale + iface mode-8 force bracket")

    # hover raw: 7B -> call t_dl_hover + 2 nops
    orig = bytes([0x03, 0xD0, 0x83, 0xC1, 0xFD, 0x03, 0xD8])
    jmp = hx(bytes([0xE8]) + struct.pack("<i", names["t_dl_hover"] - (0x49B2F1 + 5))) + " 90 90"
    add("tech.hover_rb3", "tech_hover", 0x49B2F1, orig, jmp, "inplace_rewrite",
        "frame R/B +s(3), T -s(3) (call t_dl_hover; eax=3 stays the k<3 compare)")
    # render_topic restore-rect disp (DL-private): static rewrite
    add("render_topic.restore_rect", "DatalinkWin_render_topic", 0x42BFF0,
        bytes([0x8D, 0x86, 0xC4, 0x03, 0x01, 0x00]), "8D 86 74 04 00 00", "inplace_rewrite",
        "lea eax,[esi+0x103C4] -> [esi+0x474] (canvas space; the mixed-space vanilla accident)")
    # DL iface vtbl slot 0 -> t_cr_snap_dl
    add("dl_iface_vtbl.on_mode_saveunder", "DatalinkIface_vtbl", DL_IFACE_VTBL0,
        struct.pack("<I", ONMODE), "{abs32:t_cr_snap_dl}", "vtable_repoint",
        "console save-under snapshot on DL enter (t_cr_tile restores at exit)")
    # faction page: leader portrait scaled (2026-08-30 addendum)
    redirect("faction.portrait_scale", "DatalinkWin_draw_faction", PORTRAIT_SITE, SPRITE_DRAW2,
             "t_dl_portrait", "num/den 1:1 -> g:16 + thunk_portrait_avg dest-gate poke (bilinear enlarge)")
    detour("faction.portrait_text_x", "DatalinkWin_draw_faction", PORTW_SITE, 6, "t_dl_portw",
           "profile-text x advance: native sprite width -> drawn width fl(w*g/16)")
    # article flow-scroll (VANILLA bug: scrolled draw entered the node flow mid-paragraph)
    redirect("ts.flowdraw", "TextScroll_draw", TS_DRAW_SITE, WRITE_STRINGS, "t_ts_flowdraw",
             "DL article scroll: start the flow at the containing PARAGRAPH head, y0=cum-k*lineH; bar range -> wrapped lines")
    return S


def verify_live(sites) -> list[str]:
    probs = []
    for s in sites:
        try:
            cur = SE.base_exe_bytes(s["va"], len(s["orig"]))
        except Exception as e:  # noqa: BLE001
            probs.append(f"{s['id']}: read failed {e}")
            continue
        if cur != s["orig"]:
            probs.append(f"{s['id']} @{s['va']:#x}: base {cur.hex()} != expected {s['orig'].hex()}")
    return probs


def native_identity_problems() -> list[str]:
    """Every imm row's g=16 value must equal the .bak's own immediate (the walker is a no-op at native)."""
    probs = []
    for site, off, w, kind, a, b, _t, lbl in GEN.IMMS:
        bits = KINDBITS[kind] | (K_W4 if w == 4 else 0)
        want = imm_value(a, b, bits, 16)
        raw = SE.base_exe_bytes(site + off, 4 if w == 4 else 1)
        if kind == 'FLOAT':
            have = struct.unpack("<I", raw)[0]
        elif w == 4:
            have = struct.unpack("<i", raw)[0]
        else:
            have = struct.unpack("<b", raw)[0]
        if kind == 'FLOAT':
            ok = have == (a & 0xFFFFFFFF)
        elif kind in ('NUMG', 'DEN16'):
            ok = have in (1, 16)
        else:
            ok = have == want
        if not ok:
            probs.append(f"imm @{site:#x}+{off} [{kind}] base={have} vs native={want} ({lbl})")
    for site, off, w, _act, nat, lbl in PTR_ROWS:
        raw = SE.base_exe_bytes(site + off, 4 if w == 4 else 1)
        have = struct.unpack("<I", raw)[0] if w == 4 else raw[0]
        if have != nat:
            probs.append(f"ptr @{site:#x}+{off} base={have:#x} vs native={nat:#x} ({lbl})")
    return probs


def site_yaml(sites) -> str:
    lines = []
    for s in sites:
        lines.append(
            f"  - id: {s['id']}\n    status: confirmed\n    group: {s['group']}\n    function: {s['function'].replace(' ', '_')}\n"
            f"    virtual_addr: {s['va']:#010x}\n    length: {len(s['orig'])}\n    original_bytes: \"{hx(s['orig'])}\""
            + (f"   # {s['note']}" if s["note"] else "") + "\n"
            f"    new_bytes:      \"{s['new']}\"\n    pattern: {s['pattern']}\n")
    return "\n".join(lines)


def main(argv):
    layout, end, names = assemble_all()
    ok = True
    print("; ==== Datalinks bake (assemble_dl.py) ====")
    print(f"; code {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B); cells {OFF_CELLS:#x}; tables main {OFF_TAB_MAIN:#x} ({len(MAIN_TAB)}B) tech {OFF_TAB_TECH:#x} ({len(TECH_TAB)}B); section end {SECTION_END:#x}")
    if end > OFF_CELLS:
        ok = False
        print("; OVERFLOW: code runs into the cells")
    sym_lines, content_lines = [], []
    for name, off, size in CELLS:
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    for name, _fn in DATA:
        off, b = layout[name]
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{hx(b)}\"")
    for name, _fn, _grp in NEW_THUNKS:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # dl_scale ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    sites = site_list(names)
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    for p in native_identity_problems():
        ok = False
        print("; NATIVE-IDENTITY:", p)
    ids = [s["id"] for s in sites]
    if len(ids) != len(set(ids)):
        ok = False
        print("; DUPLICATE SITE IDS")
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_dl_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_dl_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_dl_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_dl_*.yaml")
    print(f"; sites: {len(sites)}")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
