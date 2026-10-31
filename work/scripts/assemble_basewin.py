"""Assemble the BaseWin true-relayout thunk set (group basewin_relayout) — slice 1:
window + children + child-button content structure. Option A (user-picked 2026-07-18
after the option-B composite look-prototype; design work\\_tmp_basewin_relayout_design.md,
laws scaling_laws.basewin_window_rect / basewin_pt, trace work\\frida_basewin2.log).

  thunk_basewin_gwinit  -- CHAINS in front of thunk_pref_gwinit: the GraphicWin_init
                           0x5D4EF0 entry detour's abs32 target moves here; this thunk
                           runs the BaseWin gates and tail-jmps thunk_pref_gwinit
                           (whose own gates + displaced bytes + resume are unchanged,
                           byte-identical). Gates:
                           (A) ecx==BaseWin_g 0x6A7628 -> window law
                               w=fl(758g/16) h=fl(490g/16)
                               x=(SW-fl(726g/16))>>1  y=(SH-strip)-h
                               (law scaling_laws.basewin_window_rect; vanilla bytes
                               0041F4B6/0041F4EE/0041EE8D; the ==800 seed branch is
                               g=16-only so the g-gate covers it)
                           (B) parent [esp+0x1C]==BaseWin_g -> child x,y,w,h *= g/16
                               (22 FlatButtons + scrollbars + the MapWin view child).
                               ONE exception (v3 2026-07-21g, supersedes the v2
                               chevron-only arm): RIGHT-half tab-row children
                               (orig y==7 && x>363: chevron2 448, BUILD 470,
                               CONQUER 584) mirror their left twins through
                               GOVERNOR's rendered edge-sum — x = 2*pt(280) +
                               fl(166g/16) - pt(726-x-w) - fl(wg/16) (law
                               scaling_laws.basewin_tab_mirror_x) — so every
                               tab-row gap pair is symmetric (the 1600 report:
                               vanilla's row is fully mirror-symmetric; per-edge
                               flooring broke twin gaps on different phases).
                               The tab-frame box right edge mirrors too via
                               thunk_bw_boxsprite_tabframe (@0xB340, the old
                               gwinit slot; site 0x41F56A).
                           g<=16 -> straight chain (native no-op).
  thunk_basewin_btnzoom -- CHAINS in front of thunk_pref_btnzoom: the FlatButton
                           content-draw vtable slot [0x669784] repoints here; for
                           ecx in the BaseWin button array [0x6B4DE8,0x6C4670)
                           (BaseWin_g+0xD7C0, stride 0xB4C, count 0x16 -- ctor
                           FUN_006457c2(param_1+0x35f0 DWORDS, ...)) bracket the draw
                           with the g_popup_active REFCOUNT (INC / clamped DEC, the
                           v2 semantics -- popups DO open over the base screen, so the
                           absolute 1/0 bracket pref uses would stomp their arming);
                           else tail-jmp thunk_pref_btnzoom (its own gates unchanged).

SLICE 2 (2026-07-18c, group basewin_interior_slice2) -- the TEXT + CLIP + FONT
site-redirect adapters for the 9 CENTER-side draw fns (nutrients/commerce/misc/
farm/energy_alloc/facilities/expenses/psych/support -- the strip-side fns
production/queue/pop/garrison/supported/flash/info stay native, task #13):

  thunk_bw_rect_core   -- CALL-entered common core for the rect-arg text wrappers
                          (write_l_4 / write_cent_l_7 / write_right_l_6, rect at
                          site-arg2): gate ecx==canvas 0x6A7A6C && canvasW>758
                          (canvas Buffer w +0x80 -- TRUE only when slice-1 is
                          ACTIVE and g>16, so the whole slice is inert until the
                          activation flip); scale the caller's RECT through
                          scaling_laws.basewin_pt into the static scratch
                          g_bw_rect (never mutate the caller's local) and swap
                          the arg ptr. Bare RET (consumes only its own stub ret).
  thunk_bw_xy_core     -- same for the x,y-arg wrappers (write_l_3 /
                          write_right_l_5): scales the two coord args in place
                          (pushed args are dead after the callee consumes them).
  stub_l4/c7/r6/l3/r5  -- 10-byte per-target stubs: call core; jmp native.
  thunk_bw_clip        -- standalone set_clip adapter (rect at site-arg1). Only
                          the OPENING set_clip per fn is redirected -- the closing
                          call RESTORES the saved previous clip captured from
                          canvas+0x20 (already device-space; scaling it again =
                          the shared-field double-scale class).
  thunk_bw_cent5       -- standalone write_cent_l_5 adapter (x,y,w at args 2-4).
  thunk_bw_fontinit    -- Font_init site adapter for the 6 center fn-LOCAL fonts:
                          size arg x g/16 EXACT (law basewin_font_size); gate
                          canvasW>758 only (ecx is the Font, not the buffer; the
                          6 sites run exclusively inside center draw fns).
  thunk_bw_findfont    -- find_font (cdecl) site adapter, farm+misc: size arg
                          x g/16 (engine quantizes to its size table -- the
                          bubble/menu-font precedent).
  thunk_bw_setfont     -- set_font adapter for ALL 17 center sites, arg-gated:
                          only when f0 == the SHARED BaseWin font +0x40e8c
                          (Arial-Narrow 14 bold, Font_init @0x41F2A1; ALSO used
                          by strip-side queue/supported so its init must NOT be
                          scaled) swap f0 -> the cave Font g_bw_font, re-
                          Font_init'd per call at floor(14*g/16) (Font_init
                          deletes its old HFONT when present -- no GDI leak --
                          and a zeroed struct is safe: the delete is skipped).
                          Local fonts pass through untouched (already scaled at
                          their Font_init sites).

Assembled at FIXED VAs (pcave2 = 0xA0C000, slots 0xB340.. / free tail after
g_pref_wins 0xB250+0x4C; section ends 0xB800): raw bytes, do not relocate;
regenerate from this script, do not hand-edit patches.yaml.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000

# sentinel imm32 -> patches.yaml placeholder (real VAs: g 0x668740, active 0xA0C530)
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}",
        0xDEADBE04: "{abs32:g_popup_active}",
        0xDEADBE10: "{abs32:t_ntw_wheel_down}",
        0xDEADBE14: "{abs32:t_ntw_wheel_up}",
        0xDEADBE18: "{abs32:g_bw_wheel_ate}",
        0xDEADBE20: "{abs32:thunk_filedlg_railscale}",
        0xDEADBE24: "{abs32:thunk_sprite_scale_nn}",
        0xDEADBE28: "{abs32:g_fd_winbuf}",
        0xDEADBE2C: "{abs32:t_bm_ho_hf}",
        0xDEADBE30: "{abs32:t_bm_ho_df}",
        0xA0C000 + 0x21000: "{abs32:thunk_sprite_bilinear}",
        0xA0C000 + 0x21A00: "{abs32:thunk_face_hybrid}"}

# engine / patch-set constants (verified against terranx.h + the live yaml)
G = 0xDEADBE00               # g_popup_scale_num (placeholder; resolves 0x668740)
SW = 0x9B7B1C                # ScreenWidth
SH = 0x9B7B20                # ScreenHeight
STRIP = 0x7AF59C             # g_console_strip_height (runtime, already g-scaled)
BASEWIN = 0x6A7628           # BaseWin_g static instance
PRODPICKER = 0x6A8044        # BaseWin_g+0xA1C: the production picker window.
                             # EXEMPT from the child arm (v4 2026-08-03): unlike
                             # every other BaseWin child, the picker seeds its
                             # GraphicWin_init from the PARENT's canvas dims
                             # (0,0,[0x6A7AEC],-[0x6A7AF0]) — already DEVICE
                             # space — so the x g/16 child law double-scaled it
                             # (measured 1895x1225 -> 4737x3062 @g=40, 1042x673
                             # -> 1432x925 @g=22; identity only at g=16).  The
                             # canvas overran the screen and the picker's own
                             # button-centring math, which reads [picker+0x4C4],
                             # threw the row (W_infl-W_true)/2 = 1421px right at
                             # 4K.  Law scaling_laws.prodpicker_window_size (the
                             # bug form prodpicker_double_scaled_window is a
                             # regression tripwire in the sweep).
BTN_LO = 0x6B4DE8            # BaseWin_g + 0xD7C0: first of 0x16 FlatButtons
BTN_HI = 0x6C4670            # exclusive end (BTN_LO + 0x16*0xB4C)
PP_BTN_LO = 0x6A8BB8         # ProdPicker+0xB74: first of its 9 FlatButtons
PP_BTN_HI = 0x6AF164         # exclusive end (PP_BTN_LO + 9*0xB4C == the picker's
                             # ScrollBar at +0x7120, confirmed live in the trace).
                             # v5 2026-08-03: the picker's buttons pass NO zoom
                             # gate (it is not a BasePop, so g_popup_active is
                             # never armed for it), so with their windows now
                             # correctly 250x50 the CONTENT still drew at the
                             # native 20px art height — measured in the 4K shot
                             # 003622: lavender band only picker-y 1101..1122 of
                             # a 1100..1150 window, the label clipped at the band
                             # edge.  Bracket them with the same g_popup_active
                             # refcount the BaseWin array uses; thunk_btn_shrink
                             # then descales the scaled canvas back to the native
                             # art (law btn_native_dim, ceil(dev*16/g)) and the
                             # KSB refills it — no double-scale, because the
                             # bracket changes only how the art is RENDERED into
                             # the window, never the window rect.
                             # NB no thunk_bw_btnfont call on this arm: the picker
                             # sets its OWN button font (+0xB14, scaled by
                             # thunk_pp_font at 0x493A61) on all its buttons.
CONTENT_DRAW = 0x607E50      # FlatButton content-draw real entry
PREF_GWINIT = PCAVE2 + 0xAAE0    # thunk_pref_gwinit (chain target; unchanged)
PREF_BTNZOOM = PCAVE2 + 0xAD60   # thunk_pref_btnzoom (chain target; unchanged)
G_POPUP_ACTIVE = 0xDEADBE04      # refcount (placeholder; resolves pcave2+0x530)

# v2 (2026-07-21f): RELOCATED 0xB340 -> 0x4130. The chevron2 mirror-gap arm
# (superseded by v3's whole-row mirror, law basewin_tab_mirror_x) grew the
# thunk past the 176B 0xB340 slot (btnzoom @0xB3F0); 0x4130 sits in the
# measured-free 0x4000..0x42A0 gap after thunk_bw_boxsprite_console v3 (ends
# 0x4126). The vacated 0xB340 slot now holds thunk_bw_boxsprite_tabframe.
# v5 (2026-09-21f): RELOCATED 0x4130 -> 0xB000. The facilities-ScrollBar
# EXEMPTION (+8B, 280B) overran the 272B 0x4130..0x4240 slot (thunk_tutwin_popx
# @0x4240); 0xB000 sits in the cave_map-verified free 0xAFF4..0xB120 gap
# (thunk_scale_boxw ends 0xAFF4, g_dll_pref_lo @0xB120). The vacated 0x4130
# slot now holds thunk_bw_facsb_attach (the single caller of this thunk is the
# GraphicWin_init entry detour's {abs32:} -- re-resolved at bake).
GWINIT_OFF_V5 = 0xB000       # v5's slot (0xB000..0xB11C), vacated by v6 -- zeros
# v6 (2026-10-25 W5A, the base-screen mirror law): RELOCATED 0xB000 -> 0x3C100 (the W5A region 0x3C000..0x3CFFF):
# the right-half tab arm mirrors through the RAIL axis (law basewin_tab_axis_sum v2), GOVERNOR is sized to it
# (basewin_gov_w) and a rim child (the facilities BaseButton, right edge 693) ends on basewin_rim_x
# (basewin_child_w) -- 284 B could not grow in the 288 B slot.
GWINIT_OFF_V6 = 0x3C100      # v6's slot (0x3C100..0x3C29F), vacated by v7 -- zeros
# v7 (2026-10-25 W7H): RELOCATED 0x3C100 -> 0x3C900 (the W7H region 0x3C600..0x3CFFF; cave_map --at): the chevron /
# RENAME-OK / tab-row arms grew it to 679 B, past the 512 B slot.
GWINIT_OFF = 0x3C900
GWINIT_SLOT_END = 0x3CC00
TABROW_TBL_OFF = 0x3CC00      # g_bw_tabrow_tbl (W7H v2): (t, T) bytes per g 17..G_MAX, law basewin_tab_row_v
TABROW_TBL_END = 0x3CC40
TABROW_TBL = 0xA0C000 + TABROW_TBL_OFF
# ---- W8B (2026-10-27): the button rows' gaps (F48 / F49 / F50; region 0x3F970..0x3FFFF) ----
KID_OFF = 0x3F970              # g_bw_kid (12B data): the child's NATIVE x, w, y, saved by gwinit v8 at its child arm
ROWS_TBL_OFF = 0x3F980         # g_bw_rows_tbl: 10 words per g 17..G_MAX (scaling_laws.basewin_rows_table)
ROWS_STRIDE = 20
ROWFIX_OFF_V1 = 0x3FB60        # t_bw_rowfix v1's slot (0x3FB60..0x3FC64), vacated by v2 -- zeros
OKBOX_OFF = 0x3FC80            # thunk_bw_boxsprite_okrow: the RENAME / OK row frame (site 0x41F5B7)
W8B_END = 0x40000
# ---- W8R (2026-10-27, audit-w8B F52): the RESOURCE / SUPPORT / PSYCH row's top (region 0x3FD00..0x3FFFF) ----
RSPV_TBL_OFF = 0x3FD00         # g_bw_rspv_tbl: one word per g 17..G_MAX (scaling_laws.basewin_rsp_row_v)
RSPV_TBL_END = 0x3FD40
RSPV_BASE = 0xA0C000 + RSPV_TBL_OFF - 2 * 17   # + g * 2 = the word for g
ROWFIX_OFF = 0x3FD40           # t_bw_rowfix v2: the twin rows' x / w, the RENAME / OK y and the RESOURCE / SUPPORT /
ROWFIX_END = 0x3FE80           # PSYCH y from the tables -- RELOCATED from 0x3FB60 (297 B past v1's 288 B slot)
G_BW_KID = 0xA0C000 + KID_OFF
ROWS_TBL = 0xA0C000 + ROWS_TBL_OFF
ROWS_BASE = ROWS_TBL - 17 * ROWS_STRIDE   # + g * 20 = the row for g
G_MAX = 40                    # scaling_laws.G_MAX (g_popup_scale_num's clamp)
# ---- W5A: the base-screen mirror law helpers (region 0x3C000..0x3CFFF) ----
RAILSUM_OFF = 0x3C000        # t_bw_railsum: eax = S (rail axis sum), edx = Lx; ecx preserved
RIMCORE_OFF = 0x3C060        # t_bw_rimcore: edx = S - pt(726 - edx); eax/ecx preserved
RIMX_OFF = 0x3C0A0           # t_bw_rimx:   edx native exclusive edge -> rim_x / pt
LMIR_OFF = 0x3C0D0           # t_bw_lmir (W5A v4): edx native LEFT edge -> basewin_left_x (>= 563 mirrored, else pt)
W5A_HELPERS_END = 0x3C100
RIM_LO, RIM_HI = 690, 699    # scaling_laws.BASEWIN_RIM_LO / _HI
MIRRECT_OFF = 0x3C400         # t_bw_mirrect (W5A v2): the centre box / clip / fill rect through basewin_mirror_rect
MIRRECT_END = 0x3C500
FILLRECT_OFF = 0x3C500        # t_bw_fillrect (W5A v5): thunk_bw_fill2's rect through basewin_fill_rect
FILLRECT_END = 0x3C580
RCOL_L = 563                  # scaling_laws.BASEWIN_RCOL_L
OKROW_Y = 449                 # scaling_laws.BASEWIN_OKROW_Y (W7H: the RENAME / OK row, mirrored about 375)
OKROW_SUM = 750               # scaling_laws.BASEWIN_OKROW_SUM
OKROW_BOX_L, OKROW_BOX_R = 128, 622   # scaling_laws.BASEWIN_OKROW_BOX_L / _R (the row frame @0x41F5B7)
# (W5A v3: the production picker 0x6A8044 is NOT armed.  Its show 0x4926F0 calls slide_show only when the base
#  screen is NOT visible: over the base screen it draws no rails at all, and alone its frame's right edge is laid out
#  against railscale's double floor -- the A* anchor opened key-9 columns between that stroke and its rail, audit-w5A
#  v2.  It stays byte-identical to the deployed exe in both cases.)
RAILSCALE_BW_OFF = 0x3C300    # t_bw_railscale (W5A v2): the BaseWin arm in front of thunk_filedlg_railscale
RAILANCHOR_OFF = 0x3C3A0      # t_bw_railanchor (W5A v2): railslide's right-strip anchor (BaseWin A* / double floor)
W5A_V2_END = 0x3C400
G_FD_WINBUF = 0xDEADBE28        # sentinel -> {abs32:g_fd_winbuf} (the sliding window's canvas, set by the rail-arm wrappers)
RAILSCALE = 0xDEADBE20          # sentinel -> {abs32:thunk_filedlg_railscale} v3 (unchanged; the non-BaseWin tail, push+ret)
SCALE_NN = 0xDEADBE24           # sentinel -> {abs32:thunk_sprite_scale_nn} v2 (origin args not rescaled)
FACSB_ATTACH_OFF = 0x4130    # thunk_bw_facsb_attach (in gwinit's vacated slot)
FACSB_ATTACH_END = 0x4240    # thunk_tutwin_popx @0x4240 bounds it
FACSB = 0x6E8A7C             # BaseWin_g+0x41454: the BASE FACILITIES list ScrollBar
                             # (the middle of the ctor's three; +0x435A0 = supported).
                             # EXEMPT from the gwinit child arm (v5 2026-09-21f):
                             # thunk_bw_facsb_attach hands ScrollBar_attach_rect
                             # the DEVICE rect (law basewin_facsb_rect) so
                             # ScrollBar_init_inner sizes the arrow FlatButtons
                             # (w-2 square) and the track (h-2w) in device space --
                             # the generic x g/16 child arm would double-scale it.
ATTACH_RECT = 0x605840       # ScrollBar_attach_rect (thiscall RET 0x10)
PRESSED_L = 0x9B7ACC         # g_pressed_win_l: WINDOW ptr holding the left press
PRESSED_R = 0x9B7AD0         # g_pressed_win_r: right-button twin

# ---- base-screen mouse wheel (t_bw_wheel_down/up, 2026-09-21g) ----------------
# Heads of the WinProc wheel_scroll chain (sites 0x5F07B0 / 0x5F07F0 replace
# `call Win_get_active_target`; [esp+0x68] = wParam, [esp+0x6C] = lParam at
# entry).  While the base screen is SHOWN (BaseWin_g Win+0x9C bit0 = the
# Win_is_visible flag; the base screen is NOT modal -- the 2026-09-22 probe
# measured g_modal_top == 0 with a base open, so v1's `modal top == BaseWin`
# gate never matched) with no modal / basepop on top, a synthetic arrow
# (lParam 0 = PRACX / uimod wheel.cpp) becomes ScrollBar_on_chevron on the
# list under the cursor:
# BASE FACILITIES (bar +0x41454, panel rcFacilities +0x40BAC NATIVE fields ->
# device via (v*g)>>4, BaseWin-local) or FORCES SUPPORTED (bar +0x435A0, panel
# +0x40B7C = MainWin-local DEVICE rect; the bar's parent is MainWin, whose
# vtbl+0xC0 repaints the strip).  Eaten scrolls set g_bw_wheel_ate so the
# KEYUP twin swallows the matching key-up; anything else chains to the
# previous heads (t_ntw -> t_rw -> t_dl -> dw).  Same shape as asm_rw_wheel_down.
MODAL_TOP, BASEPOP = 0x9B7AE0, 0x9B8D7C
GET_TARGET, CHEVRON = 0x5F6A50, 0x606B20
IAT_GETCURSORPOS, IAT_SCREENTOCLIENT, G_HWND = 0x669284, 0x6692D4, 0x9B7B28
WHEEL_STC = PCAVE2 + 0x1292C   # t_wheel_stc (assemble_rw.WHEEL_STC): ScreenToClient drop-in, client -> backbuffer when PRACX stretches
MAINWIN = 0x7AE820
SUPSB = BASEWIN + 0x435A0    # 0x6EABC8
NTW_WHEEL_DOWN, NTW_WHEEL_UP = 0xDEADBE10, 0xDEADBE14   # sentinels -> {abs32:t_ntw_wheel_*}
G_BW_WHEEL_ATE = 0xDEADBE18                             # sentinel -> {abs32:g_bw_wheel_ate}
WHEEL_DOWN_OFF = 0x110A0     # 322B in the free 0x11098..0x11200 gap (thunk_q16_fill_width
WHEEL_DOWN_END = 0x11200     #   ends 0x11098, thunk_rail_gate @0x11200)
WHEEL_UP_OFF = 0x4190        # the up twin + cell in the facsb_attach slot's tail
WHEEL_ATE_OFF = 0x4230       #   (facsb_attach ends 0x4189, thunk_tutwin_popx @0x4240)
WHEEL_UP_END = 0x4240
TABFRAME_OFF = 0xB340        # tab-frame box adapter (site 0x41F56A), in the old gwinit slot
BTNZOOM_OFF = 0xB3F0
CAVE_LIMIT = 0xE000   # grown 0xD800->0xE000 2026-07-25d (strip slice-2a content);
                      # prior 0xD000->0xD800 2026-07-24 (thunk_chev_coverage + LUT +
                      # scratch @0xCA00-0xD10F); prior 0xC800->0xD000 2026-07-22b;
                      # prior 0xB800->0xC800 2026-07-18d for slices 3-4

# scaling_laws.basewin_window_rect constants
W_NATIVE = 758
H_NATIVE = 490
C_NATIVE = 726

# ---- slice 2 constants ----
CANVAS = 0x6A7A6C            # BaseWin center canvas Buffer (BaseWin_g + 0x444)
CANVAS_W = CANVAS + 0x80     # Buffer width field: 758 native / fl(758*g/16) when slice-1 active
SHARED_FONT = 0x6E84B4       # BaseWin_g + 0x40E8C: persistent Arial-Narrow-14-bold (also strip-side!)
HUD_FONT_NAME = 0x691B2C     # g_hud_font_name (char* global; Font_init name arg)
SHARED_FONT_SIZE = 14        # measured: Font_init(g_hud_font_name, 0xE, 1) @0x41F2A1
FONT_INIT = 0x618F40         # thiscall RET 0xC (name, height, style)
FIND_FONT = 0x5882F0         # cdecl (size, variant)
SET_FONT = 0x5DAC70          # thiscall RET 0x10
SET_CLIP = 0x5D8000          # thiscall RET 4
WRITE_L_3 = 0x5DCEA0         # (str, x, y, len)        RET 0x10
WRITE_L_4 = 0x5DCF40         # (str, rect*, len)       RET 0xC
CENT_L_5 = 0x5DD020          # (str, x, y, w, len)     RET 0x14
CENT_L_7 = 0x5DD130          # (str, rect*, len)       RET 0xC
RIGHT_L_5 = 0x5DD3B0         # (str, x, y, len)        RET 0x10
RIGHT_L_6 = 0x5DD450         # (str, rect*, len)       RET 0xC
RECT_CORE_OFF = 0xB450
XY_CORE_OFF = 0xB4C0
CLIP_OFF = 0xB500
STUB_L4_OFF = 0xB570
STUB_C7_OFF = 0xB580
STUB_R6_OFF = 0xB590
STUB_L3_OFF = 0xB5A0
STUB_R5_OFF = 0xB5B0
CENT5_OFF = 0xB5C0
FONTINIT_OFF = 0xB610
FINDFONT_OFF = 0xB640
SETFONT_OFF = 0xB670
G_BW_RECT_OFF = 0xB6D0       # 16B data
G_BW_FONT_OFF = 0xB6E0       # 0x28B data (zero-init by the fresh PE section)
SLICE2_END = 0xB708

# ---- slice 3+4 constants ----
BASEWIN_G = 0x6A7628         # the window object (GraphicWin_fill_2's `this`)
BOX_SPRITE = 0x5E2DD3        # thiscall RET 8 (rect*, params) -- baked hud_boxframe entry detour
BOX_2 = 0x5E3203             # thiscall (rect*, color_h, color_v) 1px outline
TILE_2 = 0x5DA9F0            # thiscall RET 0x1C (src, a3, a4, x, y, W, H) -- W/H = EXTENTS, a3/a4 = src tile phase (tracks dest x,y in every center call)
T_SB_TILE2 = 0xA0C000 + 0x27D00  # t_sb_tile2 (assemble_stripes_base.py): Buffer_tile_2 drop-in, cell dither -> the stripe law
FILL_2 = 0x5D5350            # GraphicWin_fill_2: thiscall(this=WINDOW) (rect*, color)
SPRITE_DRAW_2 = 0x5E4B4A     # thiscall(ecx=Sprite) (dest, key, x, y, num, den) -- baked entry chain
SPRITE_MONO = 0x5E3E00       # FUN_005E3E00 wrapper: thiscall(ecx=Sprite) (dest, color, x, y, a5, num, den) RET 0x1C
SPRITE_BILINEAR = 0xA0C000 + 0x21000   # thunk_sprite_bilinear (assemble_rw_kinds PINNED; Sprite_draw_2 contract)
FACE_HYBRID = 0xA0C000 + 0x21A00       # thunk_face_hybrid (assemble_rw_kinds PINNED; same contract): citizen faces
SPRITE_BLIT_CORE = 0x5E4B9A  # thiscall(ecx=Sprite) (dest, key, x, y) RET 0x10; ratio from globals 0x696D18/1C
SCALE_NUM_G = 0x696D18       # engine sprite-scale num global (transient; 1/1 at rest)
SCALE_DEN_G = 0x696D1C
HOLLOW_FLAT = PCAVE2 + 0x140   # thunk_box_thick_hollow_flat: box_sprite stack contract, K-wide strokes
DEVFILL = PCAVE2 + 0x42A0      # thunk_box_thick_devfill v2: fill-bearing sets, striped interior
T_BM_HO_HF = 0xDEADBE2C        # sentinel -> {abs32:t_bm_ho_hf} (W2A F38): R-1 / B-1 around thunk_box_thick_hollow_flat (W5A v4 boxes)
T_BM_HO_DF = 0xDEADBE30        # sentinel -> {abs32:t_bm_ho_df} (W4C F42): R-1 / B-1 around thunk_box_thick_devfill (W5A v4 boxes)

BOXSPRITE_OFF = 0xB710
TILE2_OFF = 0xB7A0
# (box2 slot 0xB850 freed -- v2 relocated to slice 10, see BOX2_OFF below)
FILL2_OFF = 0xB8C0
SD2_OFF = 0xB930
MONO_OFF = 0xB990
SBC_OFF = 0xB9F0
G_BW_RET_OFF = 0xBA80        # 4B: site ret across the bracketed blit-core call (single UI thread)
G_BW_SAV_OFF = 0xBA84        # 8B: saved SCALE_NUM_G/DEN_G across the bracket
SLICE34_END = 0xBA90

# ---- slice 5 (map-view blit + hit rects) ----
COPY_4 = 0x5DFF00            # thiscall(ecx=src Buffer) (dst, srcX, srcY, dstX, dstY, srcW, srcH) RET 0x1C; 1:1
COPY_3 = 0x5D9610            # thiscall(ecx=src Buffer) (dst, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH) RET 0x24; GDI StretchBlt, clips
SPOT_ADD = 0x5FA960          # thiscall (idx, flag, X, Y, W, H) RET 0x18
MAPBLIT_OFF = 0xBA90
SPOTADD_OFF = 0xBB40
SLICE5_END = 0xBBC0

# ---- slice 6 (2026-07-19 repair: pen-return descale + native-font swap +
#      farm-view zoom scaling + energy_alloc device-rect header box) ----
# Laws: scaling_laws.basewin_pen_descale / basewin_farm_zoom / basewin_farm_seed.
ZOOM_NUM = 0x691E6C          # g_map_zoom_num (engine map zoom fraction; -1 = unset)
ZOOM_DEN = 0x691E70          # g_map_zoom_den
FONT_WIDTH = 0x619280        # thiscall(ecx=Font) (str) -> pixel width (chop loops)
EXT_L4_OFF = 0xBBC0          # write_l_4 pen-descale bracket (stub tail target)
EXT_C7_OFF = 0xBBF0
EXT_R6_OFF = 0xBC20
EXT_L3_OFF = 0xBC50
EXT_R5_OFF = 0xBC80
G_BW_RET2_OFF = 0xBCB0       # 4B: site ret across the EXT bracket (single UI thread;
                             # distinct from G_BW_RET -- the SBC bracket could nest a
                             # text write in a future refactor, never share the cell)
SF_CORE_OFF = 0xBCC0         # set_font swap core (edx = size<<8 | style at entry)
SF_14B_OFF = 0xBD20          # (14,1) shared-font sites
SF_12P_OFF = 0xBD30          # (12,0) facilities-local / nutrients-local / misc
SF_12B_OFF = 0xBD40          # (12,1) psych / farm / energy_alloc / expenses
SF_10B_OFF = 0xBD50          # (10,1) commerce-local
HDRBOX_OFF = 0xBD60          # energy_alloc +0x474 (device canvas-bounds) box_sprite
FARMENTRY_OFF = 0xBE10       # draw_farm zoom entry-compose (0x40F1F5)
FARMSEED_OFF = 0xBE60        # draw_farm seed block (0x40F21B)
FARMZOOMSET_OFF = 0xBF00     # draw_farm mid-fn 1/1 zoom re-seeds (0x40F263, 0x40F4A3)
FARMICONADV_OFF = 0xBF40     # draw_farm icon x-advance (0x40F85C)
SLICE6_END = 0xBF70

# ---- slice 7 (2026-07-21 black-bar fix): the BaseWin_init OUTER console-frame
#      box (0x41F53E, sprite set 0x78d690) passes a MIXED-SPACE rect — device
#      canvas bounds [0,0,W,H] plus NATIVE insets +23/-55/+3. The generic
#      thunk_bw_boxsprite blind-scales all four coords (right 1840 -> 4600,
#      clipped) so the 198-scanline interior floods the margin strip vanilla
#      leaves key-9 transparent = the 4K black bar right of the rails
#      (frida_basewin9/10). Law: scaling_laws.basewin_console_frame_rect —
#      rebuild the rect in device space, scaling each INSET on its own edge.
CANVAS_H = CANVAS + 0x84     # Buffer height field (stored NEGATIVE)
# v3 (2026-07-21e): RELOCATED 0xC6A0 -> 0x40A0. The rail-anchor right edge grew
# the thunk 112 -> 135B past the 128B 0xC6A0 slot (btnfont @0xC720); 0x40A0 sits
# in the measured-free 0x4000..0x42A0 gap (fe_pair_remap v4 -> v5 vacated it),
# after thunk_tutbtn_post v3 @0x4000 (143B, ends 0x408F). Old 0xC6A0 slot free.
CONSOLE_OFF = 0x40A0
CONSOLE_SLOT_END = 0x42A0    # thunk_box_thick_devfill @0x42A0 bounds the gap
BTNFONT_OFF = 0xC720         # thunk_bw_btnfont: label-font swap helper (btnzoom v2 calls it)
T_FDIRECT_A14B = 0xA0C000 + 0x2E590   # t_fdirect_a14b() cdecl -> the shared Arial fl(14g/16) bold slot (assemble_fontlaw.py)
CONSOLE_END = 0xC800         # end of the basewin tail region — thunk_btn_bandstripe2
                             # owns 0xC800.. (assemble_band_restripe.py), do NOT grow past

# ---- slice 8 (2026-07-21d: RESOURCE-view yield orbs) ----
# PRACX rewrites the rel32 of draw_farm's four sprite-blit call sites at
# STARTUP (pracx.cpp m_astHooks 0x40F7DB/0x40F81B/0x40F84D/0x40F8A9 — the
# gray unworked-resources feature), stomping the slice-4 bw4.* farm redirects
# at runtime: those adapters NEVER ran (frida_basewin12.log — live rel32
# points into prax.dll 0x6C8Exxxx; the four dead bw4 farm sites are deleted
# from the yaml, on-disk vanilla). PRACX's wrappers forward every arg
# verbatim to the engine (Sprite_draw_2 stashes num/den -> the SCALE globals
# 0x696D18/1C, save/restore-bracketed, then calls the core), so scaling the
# ALREADY-PUSHED num/den literals (1,1) -> (g,16) from a detour on the last
# PRE-CALL instruction — which PRACX does NOT touch — scales the blit through
# the engine's own path. Positions are NOT touched: the yield loop computes
# DEVICE coords via the slice-6 farm zoom (law basewin_farm_zoom/seed).
# Law: basewin_sprite_ratio with num=den=1. Gate: canvasW>758 (sibling gate;
# the dest is trace-proven canvas 0x6A7A6C, frida_basewin12.log).
SPRITE_TAB = 0x7A72A0        # resource-orb sprite entry table (stride 0xB0)
ZERO_SPR = 0x78A520          # zero-yield marker sprite (displaced mov ecx imm)
FARMORB_MONO_OFF = 0xC600    # detour @0x40F7CA (7B lea) pre mono call 0x40F7DA
FARMORB_SD2A_OFF = 0xC630    # detour @0x40F804 (7B lea) pre sd2 call 0x40F81A
FARMORB_SD2B_OFF = 0xC660    # detour @0x40F839 (7B lea) pre sd2 call 0x40F84C
FARMORB_SBC_OFF = 0xC760     # detour @0x40F8A3 (5B mov ecx) pre core call 0x40F8A8

# ---- slice 9 (2026-07-26: SUPPORT-tab map banding fix) ----
# draw_support renders its embedded world-map Console (BaseWin+0x1E674) at
# NATIVE density because MapWin_init_2's mode-2 branch sizes it from the
# native rcRspPanel rect (+0x40B8C, abs 0x6E81B4) -- and mapblit v2's copy_3
# NN stretch of that render was the water banding (fractional row duplication
# beating the ocean dither).  thunk_bw_supprect scales the rect into the
# mode-2 ebp LOCALS (laws scaling_laws.support_map_rect / support_map_fit --
# the vanilla zoom-fit loop then picks the ~g/16-denser index BY ITSELF and
# the map renders from native tile art: zero resampling); mapblit v3 returns
# to vanilla's 1:1 copy_4 with dst re-centered from the scaled panel rect.
# Mode 2 is exclusively draw_support's (all 5 MapWin_init_2 call sites read);
# the block 0x470B2A..0x470B51 is straight-line and PRACX-clean for terranx
# (the pracx.cpp 0x470B25 DrawTileDraw hook is the _SMAC column, 0x464216 here).
RSP_RECT = 0x6E81B4          # BaseWin_g+0x40B8C rcRspPanel [l,t,r,b] -- READ-ONLY (shared: TutWin + click tooltip)
SUPP_RESUME = 0x470BFB       # the mode-2 block's own JMP target in MapWin_init_2
SUPPRECT_OFF = 0xEC60        # free tail after g_staple_scratch (ends 0xEC5F)
SUPPRECT_END = 0xECD0        # thunk_hud_arrowseeds starts here (166B; then
                             # supsb_dragfix 0xED80+20, sb_dragfree 0xEE40+21)

# ---- slice 10 (2026-07-27: box_2 outline polish + pop-number box pads) ----
# Laws: scaling_laws.box2_ring_rects (K = stroke_width, inward rings) /
# base_popbox_pads (basewin_pt of the +5/+4 box pads, +2/+1 glyph pen).
# thunk_bw_box2 RELOCATED 0xB850 -> 0xEEE0 (v2 grew a second exit past the
# 112B slot; old slot freed/zeros).  0xEE60.. is the free tail after
# thunk_sb_dragfree (0xEE40+21).
BOX2_OLD_SLOT = 0xB850       # freed v1 slot (bounds tile2 growth)
BOX2RING_OFF = 0xEE60        # Buffer_box_2 replacement callee (ring loop)
BOX2_OFF = 0xEEF0            # thunk_bw_box2 v2 (nutrients gate+scale+ring)
POPBOX_PADS_OFF = 0xEF70     # base_draw cut @0x55B3CF (+5/+4 pads)
POPBOX_TEXT_OFF = 0xEFA0     # base_draw cuts @0x55B605 + 0x55B675 (pen +2/+1)
G_RING_RECT_OFF = 0xEFD0     # 16B scratch ring rect (single UI thread)
SLICE10_END = 0xF000         # pcave2 section end (length 0xF000)
G_RING_RECT = PCAVE2 + G_RING_RECT_OFF
BOX2RING = PCAVE2 + BOX2RING_OFF

# own-cave data: FIXED VAs, raw imm32 (a {abs32:} sentinel can't carry the +4/+8/+C
# field offsets -- and 0xDEADBE08+4 would alias the 0xDEADBE0C sentinel window)
G_BW_RECT = PCAVE2 + G_BW_RECT_OFF
G_BW_FONT = PCAVE2 + G_BW_FONT_OFF
G_BW_RET = PCAVE2 + G_BW_RET_OFF
G_BW_SAV = PCAVE2 + G_BW_SAV_OFF
G_BW_RET2 = PCAVE2 + G_BW_RET2_OFF


def asm_railsum():
    """t_bw_railsum (CALL): eax = S = pt(726), the base screen's mirror axis (scaling_laws.basewin_rail_axis_sum v2),
    edx = Lx = fl(15g/16) + fl(8g/16) (basewin_rail_left_extent).  W5A v2: the BaseWin's right rails sit on
    A* = pt(726) - Lx (t_bw_railscale / t_bw_railanchor), so S no longer depends on the canvas width.  ecx and every
    other register preserved; flags clobbered.  g = 16: (726 * 16) >> 4 = 726, 15 + 8 = 23 -- the vanilla values,
    so the wheel test's g <= 16 path needs no gate."""
    return f"""
        push ecx
        mov  ecx, dword ptr [{G}]
        imul eax, ecx, 726
        sar  eax, 4
        imul edx, ecx, 15
        sar  edx, 4
        sar  ecx, 1
        add  edx, ecx
        pop  ecx
        ret
    """


def asm_mirrect():
    """t_bw_mirrect (CALL): eax = the caller's NATIVE rect* -> g_bw_rect = scaling_laws.basewin_mirror_rect(*rect, g),
    the HALF-OPEN device rect (W5A v4, F42): a right-column left edge (>= 563) and the right edge of a right-column /
    self-mirrored (l + r == 726) / rim (690..699) rect go through the exclusive axis mirror S - pt(726 - v),
    S = (726g)>>4; every other edge is (v*g)>>4.  The box adapter trims R / B for the inclusive band renderers through
    the shared F42 helpers (t_bm_ho_hf / t_bm_ho_df); the clip / fill adapters hand it on as is.  (v2 / v3 took
    dl = 1 for a box and drew it inclusive, mirroring that +1 onto the right column's left edge.)  eax, ecx, ebx,
    esi, edi preserved; edx and flags clobbered.  Only reached past the callers' canvas gate (g > 16)."""
    return f"""
        push ebx
        push esi
        push ecx
        mov  esi, eax
        mov  ecx, dword ptr [{G}]
        mov  edx, dword ptr [esi + 4]
        imul edx, ecx
        sar  edx, 4
        mov  dword ptr [{G_BW_RECT} + 4], edx
        mov  edx, dword ptr [esi + 0xC]
        imul edx, ecx
        sar  edx, 4
        mov  dword ptr [{G_BW_RECT} + 0xC], edx
        mov  edx, dword ptr [esi]
        cmp  edx, {RCOL_L}
        jl   lplain
        call mir
        jmp  lstore
    lplain:
        imul edx, ecx
        sar  edx, 4
    lstore:
        mov  dword ptr [{G_BW_RECT}], edx
        mov  edx, dword ptr [esi + 8]
        mov  ebx, dword ptr [esi]
        cmp  ebx, {RCOL_L}
        jge  rmir
        add  ebx, edx
        cmp  ebx, 726
        je   rmir
        cmp  edx, {RIM_LO}
        jl   rplain
        cmp  edx, {RIM_HI}
        jg   rplain
    rmir:
        call mir
        jmp  rstore
    rplain:
        imul edx, ecx
        sar  edx, 4
    rstore:
        mov  dword ptr [{G_BW_RECT} + 8], edx
        mov  eax, esi
        pop  ecx
        pop  esi
        pop  ebx
        ret
    mir:
        neg  edx
        add  edx, 726
        imul edx, ecx
        sar  edx, 4
        imul ebx, ecx, 726
        sar  ebx, 4
        sub  ebx, edx
        mov  edx, ebx
        ret
    """


def asm_fillrect():
    """t_bw_fillrect (CALL, W5A v5): eax = the caller's NATIVE fill rect* -> g_bw_rect = scaling_laws.basewin_fill_rect:
    the farm panel's interior fill (native (167, 34, 559, 256), the 1-px inset of its box (166, 33, 560, 257),
    BASEWIN_FILL_INSET_BOX) is the box's half-open device rect (t_bw_mirrect on a stack copy of the box) inset by
    K = (2g + 15) >> 5 on every side -- the fill can no longer overpaint the K-wide right / bottom strokes of the
    half-open box, nor leave a backdrop gap inside them; every other fill (the SUPPORT view's full-panel fill) ->
    t_bw_mirrect as before.  eax / ecx / ebx / esi / edi preserved (eax = the caller's rect* on return); edx and
    flags clobbered.  Only reached past thunk_bw_fill2's canvas gate (g > 16)."""
    return f"""
        cmp  dword ptr [eax], 167
        jne  plain
        cmp  dword ptr [eax + 4], 34
        jne  plain
        cmp  dword ptr [eax + 8], 559
        jne  plain
        cmp  dword ptr [eax + 0xC], 256
        jne  plain
        push eax
        push 257
        push 560
        push 33
        push 166
        mov  eax, esp
        call {PCAVE2 + MIRRECT_OFF}
        add  esp, 16
        mov  edx, dword ptr [{G}]
        lea  edx, [edx*2 + 15]
        sar  edx, 5
        add  dword ptr [{G_BW_RECT}], edx
        add  dword ptr [{G_BW_RECT} + 4], edx
        sub  dword ptr [{G_BW_RECT} + 8], edx
        sub  dword ptr [{G_BW_RECT} + 0xC], edx
        pop  eax
        ret
    plain:
        call {PCAVE2 + MIRRECT_OFF}
        ret
    """


def asm_railanchor():
    """t_bw_railanchor (CALL, from thunk_filedlg_railslide's right-strip arm): edx = the window canvas width bufW,
    ebx = g -> eax = the right inner strip's window-local device x.  The BaseWin (g_fd_winbuf == its canvas: the
    sliding window railslide already matched) gets A* = pt(726) - fl(15g/16) - fl(8g/16) (law basewin_rail_anchor);
    every other window railscale's double floor fl((fl(bufW*16/g) - 0x37) * g/16), the exact instructions railslide
    carried in line.  edx clobbered (as the inline code's div did)."""
    return f"""
        cmp  dword ptr [{G_FD_WINBUF}], {CANVAS}
        jne  other
        imul eax, ebx, 726
        sar  eax, 4
        imul edx, ebx, 15
        sar  edx, 4
        sub  eax, edx
        mov  edx, ebx
        sar  edx, 1
        sub  eax, edx
        ret
    other:
        mov  eax, edx
        shl  eax, 4
        xor  edx, edx
        div  ebx
        sub  eax, 0x37
        imul eax, ebx
        sar  eax, 4
        ret
    """


def asm_railscale_bw():
    """t_bw_railscale (the 4 settled slide_show rail sites 0x45D82C / 0x45D851 / 0x45D875 / 0x45D8A9; same entry
    contract as thunk_filedlg_railscale: [esp+4] dest, [esp+0xC] x, [esp+0x10] y, [esp+0x14] / [esp+0x18] num / den,
    ecx = Sprite*).  dest == the BaseWin canvas and g > 16 -> railscale v3's scaled path with the BaseWin anchor
    (law basewin_rail_strip_x): num / den = g / 16, a left strip at fl(x*g/16), a right strip at
    A* + fl((x - (W - 0x37))*g/16), y = fl(y*g/16), tail thunk_sprite_scale_nn.  This arms at g = 17 too (railscale's
    arm B needs a canvas taller than the 529-row art; scale_nn clips the strip to the canvas).  Anything else ->
    tail-jmp thunk_filedlg_railscale, untouched."""
    return f"""
        cmp  dword ptr [esp + 4], {CANVAS}
        jne  rs
        mov  edx, dword ptr [{G}]
        cmp  edx, 0x10
        jle  rs
        push ecx
        mov  ecx, edx
        mov  dword ptr [esp + 0x18], ecx
        push 0x10
        pop  dword ptr [esp + 0x1c]
        mov  eax, dword ptr [esp + 8]
        mov  eax, dword ptr [eax + 0x80]
        mov  edx, dword ptr [esp + 0x10]
        add  edx, edx
        cmp  edx, eax
        jl   left
        sar  edx, 1
        sub  edx, eax
        add  edx, 0x37
        imul edx, ecx
        sar  edx, 4
        imul eax, ecx, 726
        sar  eax, 4
        add  eax, edx
        imul edx, ecx, 15
        sar  edx, 4
        sub  eax, edx
        mov  edx, ecx
        sar  edx, 1
        sub  eax, edx
        jmp  store
    left:
        sar  edx, 1
        imul edx, ecx
        sar  edx, 4
        mov  eax, edx
    store:
        mov  dword ptr [esp + 0x10], eax
        mov  eax, dword ptr [esp + 0x14]
        imul eax, ecx
        sar  eax, 4
        mov  dword ptr [esp + 0x14], eax
        pop  ecx
        push {SCALE_NN}
        ret
    rs:
        push {RAILSCALE}
        ret
    """


def asm_rimcore():
    """t_bw_rimcore (CALL): edx (native rim edge r) -> S - pt(726 - r) (scaling_laws.basewin_rim_x's rim arm).
    eax / ecx and the rest preserved; flags clobbered."""
    return f"""
        push eax
        neg  edx
        add  edx, 726
        imul edx, dword ptr [{G}]
        sar  edx, 4
        push edx
        call {PCAVE2 + RAILSUM_OFF}
        pop  edx
        sub  eax, edx
        mov  edx, eax
        pop  eax
        ret
    """


def asm_rimx(box: bool):
    """t_bw_rimx (CALL; box=True was v1's t_bw_rimbox, retired by t_bw_mirrect in v2): edx = a native RIGHT edge ->
    its device value.  A rim edge (690..699, the right column's) goes through the axis mirror (rimx: basewin_rim_x,
    exclusive; box: basewin_rim_box_r =
    rim_x - 1, the inclusive band renderers' last column); any other edge is the plain interior law pt = (v*g)>>4.
    eax / ecx and the rest preserved; flags clobbered."""
    return f"""
        cmp  edx, {RIM_LO}
        jl   plain
        cmp  edx, {RIM_HI}
        jg   plain
        call {PCAVE2 + RIMCORE_OFF}
        {"dec  edx" if box else ""}
        ret
    plain:
        imul edx, dword ptr [{G}]
        sar  edx, 4
        ret
    """


def asm_lmir():
    """t_bw_lmir (CALL, W5A v4): edx = a native LEFT edge -> scaling_laws.basewin_left_x: a right-column left edge
    (>= 563) is the exclusive axis mirror S - pt(726 - l) (t_bw_rimcore) -- the first column of its half-open box,
    the mirror of the left twin's last column; any other edge the plain interior law pt = (v*g)>>4.  For the text
    rects (thunk_bw_rect_core) and the wheel hit test (t_bw_wheel_down), so both follow the drawn box.  eax / ecx and
    the rest preserved; flags clobbered."""
    return f"""
        cmp  edx, {RCOL_L}
        jl   plain
        call {PCAVE2 + RIMCORE_OFF}
        ret
    plain:
        imul edx, dword ptr [{G}]
        sar  edx, 4
        ret
    """


def tabrow_table() -> bytes:
    """g_bw_tabrow_tbl (W7H v2): for g = 17 .. G_MAX the tab row's button top t and frame top T as two bytes,
    emitted from scaling_laws.basewin_tab_row_v (never retyped)."""
    from scaling_laws import basewin_tab_row_v
    out = b""
    for g in range(17, G_MAX + 1):
        T, _B, t = basewin_tab_row_v(g)
        out += bytes((t, T))
    return out


def rows_table() -> bytes:
    """g_bw_rows_tbl (W8B): for g = 17 .. G_MAX ten little-endian words, scaling_laws.basewin_rows_table (never
    retyped): the tab row's (EXPLORE x, button w, DISCOVER x, chevron 1 x), the RESOURCE / SUPPORT / PSYCH row's
    (RESOURCE x, RESOURCE w, SUPPORT x), the RENAME / OK row's (button top t, frame top T, frame bottom B)."""
    import struct
    from scaling_laws import basewin_rows_table
    out = b""
    for g in range(17, G_MAX + 1):
        row = basewin_rows_table(g)
        assert len(row) * 2 == ROWS_STRIDE and all(0 <= v < 0x10000 for v in row), (g, row)
        out += struct.pack("<10H", *row)
    return out


def rspv_table() -> bytes:
    """g_bw_rspv_tbl (W8R): for g = 17 .. G_MAX the RESOURCE / SUPPORT / PSYCH buttons' device top t as one
    little-endian word, scaling_laws.basewin_rsp_row_v (never retyped)."""
    import struct
    from scaling_laws import basewin_rsp_row_v
    return b"".join(struct.pack("<H", basewin_rsp_row_v(g)) for g in range(17, G_MAX + 1))


def asm_rowfix():
    """t_bw_rowfix (W8B, CALLed by thunk_basewin_gwinit v8 after every BaseWin child's v7 arms, just before the
    chain): g <= G_MAX only (g > G_MAX keeps v7).  The child's NATIVE x / w / y are in g_bw_kid (saved at gwinit's
    child arm); the device args are gwinit's [esp+4..] (here [esp+0x10..] past the call's return and two pushes).
      * y == 449 (RENAME / OK): y = the table's t (law basewin_okrow_v);
      * y == 7 / 234 (the twin rows): the LEFT twin's native x (x, or 726 - x - w right of the axis 363) picks the
        table pair (Lx, Lw): EXPLORE 30 / DISCOVER 144 with w 112 (basewin_tab_row_h), chevron 1 258 with w 20 (Lw =
        the device D gwinit's chevron arm already stored), RESOURCE 169 with w 128 (basewin_rsp_row_h); a left child
        takes (Lx, Lw), a right one (x > 363) the mirror (S - Lx - Lw, Lw), S = t_bw_railsum; SUPPORT (299, w 128)
        x = the table's xS, w = S - 2 xS.  Every other child is left as v7 placed it (law basewin_child_rect v8).
      * v2 (W8R, audit-w8B F52): RESOURCE / SUPPORT / PSYCH (the three row-234 children matched above) y =
        g_bw_rspv_tbl's t (law basewin_rsp_row_v; basewin_child_rect v9).
    ecx preserved (t_bw_railsum keeps it); eax / edx / flags clobbered (gwinit's chain does not read them)."""
    A = 0x10    # gwinit's x arg: [esp+4] there, + the call's return + push esi + push ebx
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, {G_MAX}
        jg   out
        push esi
        push ebx
        imul esi, eax, {ROWS_STRIDE}
        add  esi, {ROWS_BASE}
        mov  edx, dword ptr [{G_BW_KID} + 8]
        cmp  edx, {OKROW_Y}
        jne  twin
        movzx eax, word ptr [esi + 14]
        mov  dword ptr [esp + {A + 4}], eax
        jmp  done
    twin:
        cmp  edx, 7
        je   tw
        cmp  edx, 234
        jne  done
    tw:
        call {PCAVE2 + RAILSUM_OFF}
        mov  ebx, eax
        mov  edx, dword ptr [{G_BW_KID}]
        cmp  edx, 363
        jle  isleft
        neg  edx
        add  edx, 726
        sub  edx, dword ptr [{G_BW_KID} + 4]
    isleft:
        cmp  dword ptr [{G_BW_KID} + 8], 7
        jne  rsp
        cmp  dword ptr [{G_BW_KID} + 4], 20
        je   chev
        cmp  dword ptr [{G_BW_KID} + 4], 112
        jne  done
        cmp  edx, 30
        je   te
        cmp  edx, 144
        jne  done
        movzx edx, word ptr [esi + 4]
        jmp  tw2
    te:
        movzx edx, word ptr [esi]
    tw2:
        movzx eax, word ptr [esi + 2]
        jmp  store
    chev:
        cmp  edx, 258
        jne  done
        movzx edx, word ptr [esi + 6]
        mov  eax, dword ptr [esp + {A + 8}]
        jmp  store
    rsp:
        cmp  dword ptr [{G_BW_KID} + 4], 128
        jne  done
        cmp  edx, 169
        je   rr
        cmp  edx, 299
        jne  done
        movzx edx, word ptr [esi + 12]
        mov  dword ptr [esp + {A}], edx
        add  edx, edx
        sub  ebx, edx
        mov  dword ptr [esp + {A + 8}], ebx
        jmp  rspy
    rr:
        movzx edx, word ptr [esi + 8]
        movzx eax, word ptr [esi + 10]
    store:
        mov  dword ptr [esp + {A + 8}], eax
        cmp  dword ptr [{G_BW_KID}], 363
        jle  sl
        add  edx, eax
        sub  ebx, edx
        mov  edx, ebx
    sl:
        mov  dword ptr [esp + {A}], edx
        cmp  dword ptr [{G_BW_KID} + 8], 234
        jne  done
    rspy:
        mov  eax, dword ptr [{G}]
        movzx eax, word ptr [eax*2 + {RSPV_BASE}]
        mov  dword ptr [esp + {A + 4}], eax
    done:
        pop  ebx
        pop  esi
    out:
        ret
    """


def asm_boxsprite_okrow():
    """thunk_bw_boxsprite_okrow (W8B, site 0x41F5B7 ONLY: BaseWin_init's RENAME / OK row frame (128, 446, 622, 472)):
    thunk_bw_boxsprite's contract (canvas gate -> native; t_bw_mirrect's half-open rect into g_bw_rect; push + ret to
    the shared trim helper t_bm_ho_df / t_bm_ho_hf by the set's fill flag) with the frame's top / bottom replaced by
    the table's T / B (law basewin_okrow_box_rect: one channel above and below the buttons, t_bw_rowfix's t) when
    g <= G_MAX and the rect is the row frame's (t 446, b 472); anything else stays basewin_mirror_rect.  v2 (audit-w8B
    I1): g <= 16 -> the native Buffer_box_sprite with the caller's rect even past the canvas gate (the table has no
    row for it)."""
    return f"""
        {gate_buffer()}
        mov  eax, dword ptr [esp + 4]
        call {PCAVE2 + MIRRECT_OFF}
        mov  edx, dword ptr [{G}]
        cmp  edx, 0x10
        jle  native
        cmp  edx, {G_MAX}
        jg   go
        cmp  dword ptr [eax + 4], 446
        jne  go
        cmp  dword ptr [eax + 0xC], 472
        jne  go
        imul edx, edx, {ROWS_STRIDE}
        movzx eax, word ptr [edx + {ROWS_BASE + 16}]
        mov  dword ptr [{G_BW_RECT} + 4], eax
        movzx eax, word ptr [edx + {ROWS_BASE + 18}]
        mov  dword ptr [{G_BW_RECT} + 0xC], eax
    go:
        mov  dword ptr [esp + 4], {G_BW_RECT}
        mov  edx, dword ptr [esp + 8]
        cmp  dword ptr [edx + 0x20], 0
        jne  fill
        push {T_BM_HO_HF}
        ret
    fill:
        push {T_BM_HO_DF}
        ret
    native:
        jmp  {BOX_SPRITE}
    """


def asm_gwinit():
    """v7 (2026-10-25 W7H): v6 + three arms (law scaling_laws.basewin_child_rect v7):
      the tab row (y == 7): y = g_bw_tabrow_tbl's t (law basewin_tab_btn_y / basewin_tab_row_v; g > G_MAX pt(7)),
        h = fl(20g/16) as before -- the shared `vert`
        tail (every other child y = pt(y), h = fl(hg/16), v6's chyh);
      the chevrons (y == 7, w == 20): D = fl(20g/16) square, chevron 1 x1 = (fl(2 (x + 10) S / 726) - D + 1) >> 1
        (basewin_chev_x: its centre on the rail axis S, t_bw_railsum), chevron 2 S - x1(726 - x - 20) - D;
      the RENAME / OK row (y == 449): RENAME x = pt(x), w = pt(x + w) - pt(x); OK (2x > 750) the mirror through the
        row frame's own sum S2 = pt(128) + pt(622): x = S2 - pt(750 - x), w = pt(750 - x) - pt(750 - x - w).
    GOVERNOR / SUPPORT, the right-half twin-row children, the rim child, the generic child, the window law and the
    exemptions are v6's arithmetic.  eax == g on every path into `gen`, the OK arm and `rimpt` (loaded at entry;
    t_bw_rimx / t_bw_rimcore preserve it); `vert` reloads it."""
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  chain
        cmp  ecx, {BASEWIN}
        je   selfwin
        mov  edx, dword ptr [esp + 0x1C]
        cmp  edx, {BASEWIN}
        je   child
        jmp  chain
    selfwin:
        imul edx, eax, {W_NATIVE}
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
        imul edx, eax, {H_NATIVE}
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
        imul edx, eax, {C_NATIVE}
        sar  edx, 4
        mov  eax, dword ptr [{SW}]
        sub  eax, edx
        sar  eax, 1
        mov  dword ptr [esp + 4], eax
        mov  eax, dword ptr [{SH}]
        sub  eax, dword ptr [{STRIP}]
        sub  eax, dword ptr [esp + 0x10]
        mov  dword ptr [esp + 8], eax
        jmp  chain
    child:
        cmp  ecx, {PRODPICKER}
        je   chain
        cmp  ecx, {FACSB}
        je   chain
        mov  edx, dword ptr [esp + 4]
        mov  dword ptr [{G_BW_KID}], edx
        mov  edx, dword ptr [esp + 0xC]
        mov  dword ptr [{G_BW_KID} + 4], edx
        mov  edx, dword ptr [esp + 8]
        mov  dword ptr [{G_BW_KID} + 8], edx
        cmp  edx, 7
        jne  nottab
        cmp  dword ptr [esp + 0xC], 20
        je   chev
        jmp  twinrow
    nottab:
        cmp  edx, 234
        je   twinrow
        cmp  edx, {OKROW_Y}
        jne  rimchk
        mov  edx, dword ptr [esp + 4]
        add  edx, edx
        cmp  edx, {OKROW_SUM}
        jle  okleft
        imul edx, eax, {OKROW_BOX_L}
        sar  edx, 4
        imul eax, eax, {OKROW_BOX_R}
        sar  eax, 4
        add  eax, edx
        mov  edx, {OKROW_SUM}
        push ecx
        sub  edx, dword ptr [esp + 8]
        mov  ecx, edx
        sub  ecx, dword ptr [esp + 0x10]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        imul ecx, dword ptr [{G}]
        sar  ecx, 4
        sub  eax, edx
        mov  dword ptr [esp + 8], eax
        sub  edx, ecx
        mov  dword ptr [esp + 0x10], edx
        pop  ecx
        jmp  vert
    okleft:
        push ecx
        mov  ecx, eax
        mov  edx, dword ptr [esp + 8]
        mov  eax, edx
        add  eax, dword ptr [esp + 0x10]
        imul edx, ecx
        sar  edx, 4
        imul eax, ecx
        sar  eax, 4
        mov  dword ptr [esp + 8], edx
        sub  eax, edx
        mov  dword ptr [esp + 0x10], eax
        pop  ecx
        jmp  vert
    chev:
        push ebx
        push ecx
        imul ebx, eax, 20
        sar  ebx, 4
        call {PCAVE2 + RAILSUM_OFF}
        mov  ecx, eax
        mov  edx, dword ptr [esp + 0xC]
        cmp  edx, 363
        jle  chl
        neg  edx
        add  edx, 706
    chl:
        add  edx, 10
        add  edx, edx
        imul eax, edx
        xor  edx, edx
        push 726
        div  dword ptr [esp]
        add  esp, 4
        sub  eax, ebx
        inc  eax
        sar  eax, 1
        cmp  dword ptr [esp + 0xC], 363
        jle  chst
        neg  eax
        add  eax, ecx
        sub  eax, ebx
    chst:
        mov  dword ptr [esp + 0xC], eax
        mov  dword ptr [esp + 0x14], ebx
        pop  ecx
        pop  ebx
        jmp  vert
    twinrow:
        cmp  dword ptr [esp + 4], 363
        jg   tabright
        mov  edx, dword ptr [esp + 4]
        add  edx, edx
        add  edx, dword ptr [esp + 0xC]
        cmp  edx, 726
        jne  gen
        call {PCAVE2 + RAILSUM_OFF}
        mov  edx, dword ptr [esp + 4]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  dword ptr [esp + 4], edx
        sub  eax, edx
        sub  eax, edx
        mov  dword ptr [esp + 0xC], eax
        jmp  vert
    tabright:
        call {PCAVE2 + RAILSUM_OFF}
        mov  edx, 726
        sub  edx, dword ptr [esp + 4]
        sub  edx, dword ptr [esp + 0xC]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        sub  eax, edx
        mov  edx, dword ptr [esp + 0xC]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        sub  eax, edx
        mov  dword ptr [esp + 4], eax
        mov  dword ptr [esp + 0xC], edx
        jmp  vert
    rimchk:
        mov  edx, dword ptr [esp + 4]
        add  edx, dword ptr [esp + 0xC]
        cmp  edx, {RIM_LO}
        jl   gen
        cmp  edx, {RIM_HI}
        jg   gen
        call {PCAVE2 + RIMX_OFF}
        mov  dword ptr [esp + 0xC], edx
        mov  edx, dword ptr [esp + 4]
        cmp  edx, {RCOL_L}
        jl   rimpt
        call {PCAVE2 + RIMCORE_OFF}
        jmp  rimx0
    rimpt:
        imul edx, eax
        sar  edx, 4
    rimx0:
        mov  dword ptr [esp + 4], edx
        sub  dword ptr [esp + 0xC], edx
        jmp  vert
    gen:
        mov  edx, dword ptr [esp + 4]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 4], edx
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
    vert:
        mov  eax, dword ptr [{G}]
        mov  edx, dword ptr [esp + 8]
        cmp  edx, 7
        jne  vpt
        cmp  eax, {G_MAX}
        jg   vpt
        movzx edx, byte ptr [{TABROW_TBL} + eax*2 - {2 * 17}]
        jmp  vst
    vpt:
        imul edx, eax
        sar  edx, 4
    vst:
        mov  dword ptr [esp + 8], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
        call {PCAVE2 + ROWFIX_OFF}
    chain:
        jmp  {PREF_GWINIT}
    """


def asm_facsb_attach():
    """thunk_bw_facsb_attach (2026-09-21f, group basewin_facsb): call-redirect
    target for BaseWin_draw_facilities' overflow-branch ScrollBar_attach_rect
    @0x41002C (thiscall ecx=BaseWin_g+0x41454, args [RECT*, BaseWin_g, 1, 0],
    RET 0x10; the site ignores eax).

    (1) Scaling: the RECT local [r-12, t, r, b] is NATIVE (the panel's inner
    rect); rewrite it IN PLACE to law basewin_facsb_rect --
    [pt(r)-fl(12g/16), pt(t), pt(r), pt(b)] -- so ScrollBar_init_inner sizes
    the arrow FlatButtons and the track in device space.  The caller's local
    ([ebp-0x68..-0x5C]) is DEAD after the call (verified in the disasm: the
    following set_range/set_pos/show read other locals), so no scratch copy.
    thunk_basewin_gwinit v5 exempts this bar from its child arm (no double
    scale).  g<=16 -> rect untouched (native no-op).

    (2) VANILLA drag-loss fix (the supported_sb_dragfix class): the overflow
    branch re-attaches the bar on EVERY repaint, and each thumb-drag step
    repaints (ScrollBar notifies BaseWin_on_scrolled -> draw_facilities(1));
    the attach's GraphicWin_init -> GraphicWin_close -> Win_close clears
    g_pressed_win_l/r when they equal the closing window, killing the drag.
    While the bar itself HOLDS the press (g_pressed_win_l/r == ecx) skip the
    re-attach with the callee's exact contract (eax=0, RET 0x10) -- the rect
    cannot change mid-drag, and set_range/set_pos/show still run.  Any other
    state (first engage, re-engage after the subctor/close reset, the
    facilities BaseButton toggling the list bottom) attaches normally."""
    return f"""
        cmp  ecx, dword ptr [{PRESSED_L}]
        je   skip
        cmp  ecx, dword ptr [{PRESSED_R}]
        je   skip
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  go
        mov  edx, dword ptr [esp + 4]
        push ecx
        mov  ecx, dword ptr [edx + 4]
        imul ecx, eax
        sar  ecx, 4
        mov  dword ptr [edx + 4], ecx
        mov  ecx, dword ptr [edx + 0xC]
        imul ecx, eax
        sar  ecx, 4
        mov  dword ptr [edx + 0xC], ecx
        push edx
        mov  edx, dword ptr [edx + 8]
        call {PCAVE2 + RIMX_OFF}
        mov  ecx, edx
        pop  edx
        mov  dword ptr [edx + 8], ecx
        imul eax, eax, 12
        sar  eax, 4
        sub  ecx, eax
        mov  dword ptr [edx], ecx
        pop  ecx
    go:
        push {ATTACH_RECT}
        ret
    skip:
        xor  eax, eax
        ret  0x10
    """


def asm_bw_wheel_down():
    """t_bw_wheel_down: see the constants block above.  eax (the key target
    from Win_get_active_target) is saved across the cursor math and returned
    untouched on every non-eaten path.  Register use on the eaten path: ebx = chevron id (1 up / 2 down), esi/edi = cursor scratch then
    edi = the bar; ecx = the scale (clamped >= 16 so native fields stay native
    at g<=16).  The FACILITIES test scales rcFacilities' four NATIVE edges
    exactly as thunk_bw_boxsprite draws them ((v*g)>>4 per edge); the SUPPORTED
    test compares the MainWin-local cursor against the strip panel's DEVICE
    rect.  ENGAGED = bar window open ([bar+0xC4] != 0, cleared by the
    subctor/close reset) AND range max > min."""
    return f"""
        cmp  dword ptr [{BASEPOP}], 0
        jne  chain
        cmp  dword ptr [{MODAL_TOP}], 0
        jne  chain
        test byte ptr [{BASEWIN + 0x9C}], 1
        jz   chain
        call {GET_TARGET}
        test eax, eax
        jz   xout
        cmp  dword ptr [esp + 0x6C], 0
        jne  xout
        mov  edx, dword ptr [esp + 0x68]
        cmp  edx, 0x26
        je   go
        cmp  edx, 0x28
        jne  xout
    go:
        push eax
        push ebx
        push esi
        push edi
        mov  ebx, 1
        cmp  edx, 0x26
        je   dir
        mov  ebx, 2
    dir:
        sub  esp, 8
        push esp
        call dword ptr [{IAT_GETCURSORPOS}]
        push esp
        push dword ptr [{G_HWND}]
        call {WHEEL_STC}
        nop
        pop  eax
        pop  edx
        mov  esi, eax
        mov  edi, edx
        sub  esi, dword ptr [{BASEWIN + 0x13C}]
        sub  edi, dword ptr [{BASEWIN + 0x140}]
        mov  ecx, dword ptr [{G}]
        cmp  ecx, 0x10
        jg   fdev
        mov  ecx, 0x10
    fdev:
        push eax
        push edx
        mov  edx, dword ptr [{BASEWIN + 0x40BAC}]
        call {PCAVE2 + LMIR_OFF}
        cmp  esi, edx
        pop  edx
        jl   fno
        push edx
        mov  edx, dword ptr [{BASEWIN + 0x40BB4}]
        call {PCAVE2 + RIMX_OFF}
        cmp  esi, edx
        pop  edx
        jge  fno
        mov  eax, dword ptr [{BASEWIN + 0x40BB0}]
        imul eax, ecx
        sar  eax, 4
        cmp  edi, eax
        jl   fno
        mov  eax, dword ptr [{BASEWIN + 0x40BB8}]
        imul eax, ecx
        sar  eax, 4
        cmp  edi, eax
        jge  fno
        pop  eax
        mov  edi, {FACSB}
        jmp  have
    fno:
        pop  eax
        sub  eax, dword ptr [{MAINWIN + 0x13C}]
        sub  edx, dword ptr [{MAINWIN + 0x140}]
        cmp  eax, dword ptr [{BASEWIN + 0x40B7C}]
        jl   restore
        cmp  eax, dword ptr [{BASEWIN + 0x40B84}]
        jge  restore
        cmp  edx, dword ptr [{BASEWIN + 0x40B80}]
        jl   restore
        cmp  edx, dword ptr [{BASEWIN + 0x40B88}]
        jge  restore
        mov  edi, {SUPSB}
    have:
        cmp  dword ptr [edi + 0xC4], 0
        je   restore
        mov  ecx, dword ptr [edi + 0xA24]
        cmp  ecx, dword ptr [edi + 0xA20]
        jle  restore
        push ebx
        mov  ecx, edi
        call {CHEVRON}
        mov  dword ptr [{G_BW_WHEEL_ATE}], 1
        pop  edi
        pop  esi
        pop  ebx
        pop  eax
        xor  eax, eax
        ret
    restore:
        pop  edi
        pop  esi
        pop  ebx
        pop  eax
    xout:
        ret
    chain:
        push {NTW_WHEEL_DOWN}
        ret
    """


def asm_bw_wheel_up():
    """t_bw_wheel_up: the KEYUP twin -- swallows only a synthetic arrow key-up
    whose key-down was scrolled by t_bw_wheel_down (g_bw_wheel_ate, cleared
    here); everything else chains."""
    return f"""
        cmp  dword ptr [{BASEPOP}], 0
        jne  chain
        cmp  dword ptr [{MODAL_TOP}], 0
        jne  chain
        test byte ptr [{BASEWIN + 0x9C}], 1
        jz   chain
        cmp  dword ptr [{G_BW_WHEEL_ATE}], 0
        je   chain
        mov  dword ptr [{G_BW_WHEEL_ATE}], 0
        call {GET_TARGET}
        test eax, eax
        jz   xout
        cmp  dword ptr [esp + 0x6C], 0
        jne  xout
        mov  edx, dword ptr [esp + 0x68]
        cmp  edx, 0x26
        je   eat
        cmp  edx, 0x28
        jne  xout
    eat:
        xor  eax, eax
    xout:
        ret
    chain:
        push {NTW_WHEEL_UP}
        ret
    """


def asm_btnzoom():
    # v2 (2026-07-21c): + call thunk_bw_btnfont before the content draw — swaps
    # the button canvas's label font to the scaled twin (see asm_btnfont).
    return f"""
        cmp  ecx, {PP_BTN_LO}
        jb   notpp
        cmp  ecx, {PP_BTN_HI}
        jae  notpp
        inc  dword ptr [{G_POPUP_ACTIVE}]
        call {CONTENT_DRAW}
        jmp  unbracket
    notpp:
        cmp  ecx, {BTN_LO}
        jb   chain
        cmp  ecx, {BTN_HI}
        jae  chain
        inc  dword ptr [{G_POPUP_ACTIVE}]
        call {PCAVE2 + BTNFONT_OFF}
        call {CONTENT_DRAW}
    unbracket:
        mov  edx, dword ptr [{G_POPUP_ACTIVE}]
        test edx, edx
        je   done
        dec  dword ptr [{G_POPUP_ACTIVE}]
    done:
        ret
    chain:
        jmp  {PREF_BTNZOOM}
    """


def asm_btnfont():
    # slice-7 label-font swap (2026-07-21c): the BaseWin FlatButton label is
    # drawn by content_draw's Buffer_wrap_cent_4 with the canvas's PERSISTENT
    # font0 (+0x52C; content_draw contains no set_font/Font_init/find_font —
    # byte-scanned) and every label metric (y-centering @0x6083E4, width-
    # shrink fallback @0x608406) derives from that font at draw time — so a
    # persistent swap to the scaled twin makes the engine's own layout math
    # self-consistent (the tooltip/menu-font precedent, law basewin_font_size).
    # Gates: window device-scaled (|dims H +0x4C8| > 20 native — false at
    # g<=16, and false for the strip-side native buttons by design) AND
    # font0 == the SHARED native font (gate on the NATIVE value: after one
    # swap the field holds our font -> idempotent, and a strip button never
    # matches its own untouched font twice). find_font is cdecl (table-owned
    # font, no alloc); ecx (button) preserved for the content draw.
    return f"""
        mov  edx, dword ptr [ecx + 0x4C8]
        neg  edx
        cmp  edx, 20
        jle  done
        cmp  dword ptr [ecx + 0x970], {SHARED_FONT}
        jne  done
        push ecx
        call {T_FDIRECT_A14B}
        pop  ecx
        test eax, eax
        je   done
        mov  dword ptr [ecx + 0x970], eax
    done:
        ret
    """
    # v3 (2026-09-17, audit finding 3.9): the shared native font 0x6E84B4 is Font_init("Arial", 14, 1)
    # -- Arial, not the pool's Arial Narrow; t_fdirect_a14b (assemble_fontlaw.py) = Arial fl(14g/16)
    # bold on one shared keyed slot (also the HQ report / kinds console labels).


def asm_farmorb_mono():
    # slice-8 detour @0x40F7CA (displaced 7B lea; resume 0x40F7D1), ahead of
    # the mono-wrapper call 0x40F7DA (PRACX-owned rel32). Stack at this point:
    # [esp]=x [esp+4]=y [esp+8]=a5 [esp+0xC]=num(1) [esp+0x10]=den(1).
    # ecx is consumed by the displaced lea, then dead (site re-zeroes it).
    return f"""
        lea  esi, [ecx*4 + {SPRITE_TAB}]
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  done
        mov  ecx, dword ptr [{G}]
        mov  dword ptr [esp + 0xC], ecx
        mov  dword ptr [esp + 0x10], 16
    done:
        jmp  {0x40F7D1}
    """


def asm_farmorb_sd2a():
    # slice-8 detour @0x40F804 (displaced 7B lea; resume 0x40F80B), ahead of
    # the Sprite_draw_2 call 0x40F81A. Stack: [esp]=y [esp+4]=num [esp+8]=den.
    # eax is LIVE (centering dividend, cdq at resume); edx dead (cdq rewrites).
    return f"""
        lea  ecx, [edx*4 + {SPRITE_TAB}]
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  done
        mov  edx, dword ptr [{G}]
        mov  dword ptr [esp + 4], edx
        mov  dword ptr [esp + 8], 16
    done:
        jmp  {0x40F80B}
    """


def asm_farmorb_sd2b():
    # slice-8 detour @0x40F839 (displaced 7B lea; resume 0x40F840), ahead of
    # the Sprite_draw_2 call 0x40F84C. Stack: [esp]=num [esp+4]=den.
    # eax is LIVE (the masked dest); edx dead (rewritten at resume).
    return f"""
        lea  ecx, [edx*4 + {SPRITE_TAB}]
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  done
        mov  edx, dword ptr [{G}]
        mov  dword ptr [esp], edx
        mov  dword ptr [esp + 4], 16
    done:
        jmp  {0x40F840}
    """


def asm_farmorb_sbc():
    # slice-8 call-helper @0x40F8A3 (the 5B site only fits E8; displaced
    # mov ecx,imm; bare RET consumes the site ret = resume at the call
    # 0x40F8A8 -- the CALL-helper law) ahead of the ratio-less
    # Sprite_blit_scaled_core call (zero-yield marker): the core reads the
    # SCALE globals directly, so arm them (g,16). Sticky only within
    # draw_farm: every later Sprite_draw_2/mono call save/restore-brackets
    # the globals around its own stash, and the fn's common exit resets them
    # to 1/1 before the composite. eax/edx are dead here (args all pushed).
    return f"""
        mov  ecx, {ZERO_SPR}
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  done
        mov  eax, dword ptr [{G}]
        mov  dword ptr [{SCALE_NUM_G}], eax
        mov  dword ptr [{SCALE_DEN_G}], 16
    done:
        ret
    """


def gate_buffer(label: str = "native") -> str:
    """ecx==canvas && canvasW>758 -- inert until slice-1 activation scales the canvas."""
    return f"""
        cmp  ecx, {CANVAS}
        jne  {label}
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  {label}
    """


def asm_rect_core():
    # CALL-entered from a 10B stub: [esp]=stub ret, [esp+4]=site ret,
    # [esp+8]=str, [esp+0xC]=rect*. Bare RET (consumes only the stub ret).
    # W5A: the RIGHT edge through t_bw_rimx (a right-column rim 690..699 ->
    # basewin_rim_x; else pt) -- the centred / clipped text in the mirrored
    # right column follows its box.  v4: the LEFT edge through t_bw_lmir (a
    # right-column left edge >= 563 -> the box's first column, the mirror of
    # its left twin's) -- law basewin_text_rect.
    fields = _rect_fields(PCAVE2 + RIMX_OFF, PCAVE2 + LMIR_OFF)
    return f"""
        {gate_buffer('done')}
        mov  eax, dword ptr [esp + 0xC]
        {fields}
        mov  dword ptr [esp + 0xC], {G_BW_RECT}
    done:
        ret
    """


def asm_xy_core():
    # CALL-entered from a 10B stub: [esp+8]=str, [esp+0xC]=x, [esp+0x10]=y.
    return f"""
        {gate_buffer('done')}
        mov  eax, dword ptr [{G}]
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
    done:
        ret
    """


def asm_stub(core_va: int, native_va: int):
    return f"""
        call {core_va}
        jmp  {native_va}
    """


def asm_clip():
    # set_clip site adapter: rect* at [esp+4].
    # W5A v2 / v4: the rect through t_bw_mirrect (half-open,
    # basewin_mirror_rect) -- the facilities / energy / intake / middle panel
    # clips follow their mirrored boxes.
    return f"""
        {gate_buffer()}
        mov  eax, dword ptr [esp + 4]
        call {PCAVE2 + MIRRECT_OFF}
        mov  dword ptr [esp + 4], {G_BW_RECT}
    native:
        jmp  {SET_CLIP}
    """


def asm_cent5():
    # write_cent_l_5 site adapter: x,y,w at [esp+8]/[esp+0xC]/[esp+0x10].
    coords = "\n".join(f"""
        mov  edx, dword ptr [esp + {o:#x}]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + {o:#x}], edx""" for o in (8, 0xC, 0x10))
    return f"""
        {gate_buffer()}
        mov  eax, dword ptr [{G}]
        {coords}
    native:
        jmp  {CENT_L_5}
    """


def asm_fontinit():
    # Font_init site adapter (center fn-local fonts): size at [esp+8].
    # ecx = the Font object -- gate on the canvas width alone (the 6 redirected
    # sites run only inside center draw fns).
    return f"""
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  edx, dword ptr [esp + 8]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  dword ptr [esp + 8], edx
    native:
        jmp  {FONT_INIT}
    """


def asm_findfont():
    # find_font (cdecl) site adapter: size at [esp+4]; engine quantizes to its
    # own size table (nearest; the bubble/menu-font precedent).
    return f"""
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  edx, dword ptr [esp + 4]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  dword ptr [esp + 4], edx
    native:
        jmp  {FIND_FONT}
    """


def asm_setfont():
    # SUPERSEDED by the slice-6 sf_core/variant family (kept emitted so the cave
    # bytes stay stable; no site targets this any more). Old behavior: swap only
    # the SHARED font +0x40e8c for the cave Font at fl(14*g/16).
    return f"""
        {gate_buffer()}
        cmp  dword ptr [esp + 4], {SHARED_FONT}
        jne  native
        mov  eax, dword ptr [{G}]
        imul eax, eax, {SHARED_FONT_SIZE}
        sar  eax, 4
        push ecx
        push 1
        push eax
        push dword ptr [{HUD_FONT_NAME}]
        mov  ecx, {G_BW_FONT}
        call {FONT_INIT}
        pop  ecx
        mov  dword ptr [esp + 4], {G_BW_FONT}
    native:
        jmp  {SET_FONT}
    """


def asm_text_ext(native_va: int):
    # Slice-6 pen-return bracket (law basewin_pen_descale): the write_l family
    # RETURNS the advanced pen x in DEVICE space and the draw fns chain the next
    # write from it (misc M.Y./Energy rows, every expenses intake segment, the
    # energy_alloc bonus columns). The stub tail jmp lands here instead of the
    # native: stash the SITE ret, run the native writer (it cleans the args via
    # RET imm), then descale eax = eax*16/g so the chain re-enters native-space
    # math. Gate re-check is canvasW alone: only center-fn sites route through
    # these stubs, and their target buffer is always the center canvas.
    # G_BW_RET2 is single-cell safe: text writers never nest.
    return f"""
        pop  dword ptr [{G_BW_RET2}]
        call {native_va}
        mov  ecx, dword ptr [{CANVAS_W}]
        cmp  ecx, {W_NATIVE}
        jle  done
        mov  ecx, dword ptr [{G}]
        shl  eax, 4
        cdq
        idiv ecx
    done:
        jmp  dword ptr [{G_BW_RET2}]
    """


def asm_sf_variant(size: int, style: int):
    # Slice-6 set_font swap entry: encode (native size, style) and share the core.
    return f"""
        mov  edx, {(size << 8) | style}
        jmp  {PCAVE2 + SF_CORE_OFF}
    """


def asm_sf_core():
    # Slice-6 set_font swap core (law basewin_font_size): ALL center fonts stay
    # NATIVE objects now (fn-local Font_init and find_font sites reverted), so
    # every inline metric read -- misc line centering, facilities row pitch and
    # Font_width chop budget, nutrients bar-area height -- runs in native space.
    # The swap to a scaled font happens ONLY here, at the buffer set: re-init
    # the cave Font at fl(size*g/16) with the site's native size/style (edx)
    # and substitute it as f0. Font_init deletes the prior HFONT (no GDI leak).
    return f"""
        cmp  ecx, {CANVAS}
        jne  native
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  eax, edx
        shr  eax, 8
        imul eax, dword ptr [{G}]
        sar  eax, 4
        and  edx, 0xFF
        push ecx
        push edx
        push eax
        push dword ptr [{HUD_FONT_NAME}]
        mov  ecx, {G_BW_FONT}
        call {FONT_INIT}
        pop  ecx
        mov  dword ptr [esp + 4], {G_BW_FONT}
    native:
        jmp  {SET_FONT}
    """


def asm_boxsprite_hdr():
    # Slice-6: the ONE center rect seeded from the +0x474 canvas-bounds fields
    # (energy_alloc's outer header frame, site 0x411A9A). With slice-1 active
    # those fields are already DEVICE space; the incoming rect is
    # (0x17, 0, x1_dev-0x37, y1_dev). Descale the device edges back to native
    # ((v<<4)/g, undoing the +-0x37 first so the native inset survives), then
    # the standard basewin_pt scale + pref_boxframe dispatch. +-1px round-trip
    # wobble on the frame line is invisible; the alternative (hardcoding the
    # native canvas extent) would bake an assumption about the +0x474 semantic.
    return f"""
        {gate_buffer('native')}
        mov  eax, dword ptr [esp + 4]
        mov  edx, dword ptr [eax]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  dword ptr [{G_BW_RECT}], edx
        mov  edx, dword ptr [eax + 4]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  dword ptr [{G_BW_RECT} + 4], edx
        push eax
        mov  eax, dword ptr [eax + 8]
        add  eax, 0x37
        shl  eax, 4
        cdq
        idiv dword ptr [{G}]
        sub  eax, 0x37
        imul eax, dword ptr [{G}]
        sar  eax, 4
        mov  dword ptr [{G_BW_RECT} + 8], eax
        pop  eax
        mov  eax, dword ptr [eax + 0xC]
        shl  eax, 4
        cdq
        idiv dword ptr [{G}]
        imul eax, dword ptr [{G}]
        sar  eax, 4
        mov  dword ptr [{G_BW_RECT} + 0xC], eax
        mov  dword ptr [esp + 4], {G_BW_RECT}
        mov  edx, dword ptr [esp + 8]
        cmp  dword ptr [edx + 0x20], 0
        jne  fill
        jmp  {HOLLOW_FLAT}
    fill:
        jmp  {DEVFILL}
    native:
        jmp  {BOX_SPRITE}
    """


def asm_farmentry():
    # Slice-6 farm-view zoom entry-compose (law basewin_farm_zoom), replacing
    # the 5B `mov eax,[zoom_num]` at 0x40F1F5: compose the engine's own zoom
    # fraction with g/16 so the WHOLE farm pipeline (tile step raw = num*50/den,
    # terrain polys, veh/base stamps, icon centering) scales through the
    # engine's zoom machinery -- the same path the main map uses. num<=0 is the
    # -1 'unset' sentinel -> normalize to 1/1 first. draw_farm's common exit
    # resets the globals to -1, so the compose never leaks across calls.
    # Site contract: eax := composed zoom_num; only eax may be clobbered.
    return f"""
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  native
        mov  eax, dword ptr [{ZOOM_NUM}]
        test eax, eax
        jg   pos
        mov  dword ptr [{ZOOM_NUM}], 1
        mov  dword ptr [{ZOOM_DEN}], 1
    pos:
        mov  eax, dword ptr [{ZOOM_NUM}]
        imul eax, dword ptr [{G}]
        mov  dword ptr [{ZOOM_NUM}], eax
        mov  eax, dword ptr [{ZOOM_DEN}]
        shl  eax, 4
        mov  dword ptr [{ZOOM_DEN}], eax
    native:
        mov  eax, dword ptr [{ZOOM_NUM}]
        ret
    """


def asm_farmseed():
    # Slice-6 farm-view seed block (law basewin_farm_seed), replacing
    # 0x40F21B..0x40F251: entry eax = zoom-rounded raw tile width (already
    # device-scaled via the entry-compose when armed), esi = &panel rect
    # (+0x40b8c, NATIVE fields). Computes local_24 (=ebx AND [ebp-0x20]),
    # local_28 [ebp-0x24], local_2c [ebp-0x28] in ONE space -- armed: fields
    # through basewin_pt per edge, the +4 nudge as pt(4)=g>>2; native: the
    # vanilla math verbatim. ecx untouched (the site reloads it after).
    return f"""
        mov  ebx, eax
        sar  ebx, 2
        shl  ebx, 1
        mov  dword ptr [ebp - 0x20], ebx
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  native
        mov  eax, dword ptr [esi]
        imul eax, dword ptr [{G}]
        sar  eax, 4
        mov  edx, dword ptr [esi + 8]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        sub  edx, eax
        sar  edx, 1
        sub  edx, ebx
        sub  edx, ebx
        add  edx, eax
        mov  dword ptr [ebp - 0x24], edx
        mov  eax, dword ptr [esi + 4]
        imul eax, dword ptr [{G}]
        sar  eax, 4
        lea  edx, [ebx + ebx*2]
        add  edx, eax
        mov  eax, dword ptr [{G}]
        sar  eax, 2
        add  edx, eax
        mov  dword ptr [ebp - 0x28], edx
        ret
    native:
        mov  eax, dword ptr [esi]
        mov  edx, dword ptr [esi + 8]
        sub  edx, eax
        sar  edx, 1
        sub  edx, ebx
        sub  edx, ebx
        add  edx, eax
        mov  dword ptr [ebp - 0x24], edx
        mov  eax, dword ptr [esi + 4]
        lea  edx, [ebx + ebx*2]
        add  edx, eax
        add  edx, 4
        mov  dword ptr [ebp - 0x28], edx
        ret
    """


def asm_farmzoomset():
    # Slice-6: draw_farm's two mid-fn zoom re-seeds to 1/1 (0x40F263 pre-poly,
    # 0x40F4A3 pre-icon-loop) become (g,16) when armed (basewin_farm_zoom with
    # num=den=1). Preserves eax (site1 needs eax=0, site2 eax=1 for the
    # following SCALE_NUM/DEN stores); flags are dead at both sites.
    return f"""
        push eax
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  native
        mov  eax, dword ptr [{G}]
        mov  dword ptr [{ZOOM_NUM}], eax
        mov  dword ptr [{ZOOM_DEN}], 16
        jmp  done
    native:
        mov  dword ptr [{ZOOM_NUM}], 1
        mov  dword ptr [{ZOOM_DEN}], 1
    done:
        pop  eax
        ret
    """


def asm_farmiconadv():
    # Slice-6: the one resource-icon x-advance that reads the width table RAW
    # (0x40F85C `mov eax,[edx*4+0x7a72b0]; add edi,eax`) while its centering
    # sibling (0x40F6E1) already divides through the zoom -- scale the addend
    # by g/16 to match (== the zoom fraction the rest of the row uses).
    return f"""
        mov  eax, dword ptr [edx*4 + 0x7A72B0]
        cmp  dword ptr [{CANVAS_W}], {W_NATIVE}
        jle  advance
        imul eax, dword ptr [{G}]
        sar  eax, 4
    advance:
        add  edi, eax
        ret
    """


def _rect_fields(right_helper=None, left_helper=None) -> str:
    """The four per-edge scales of the RECT at [eax] into g_bw_rect.  right_helper (W5A): the RIGHT edge goes through
    that helper (t_bw_rimx: edx native -> device, eax / ecx preserved) -- 14 B where the plain field is
    18 B, so every adapter that takes it shrinks."""
    def field(i):
        if i == 0 and left_helper is not None:
            return f"""
        mov  edx, dword ptr [eax]
        call {left_helper}
        mov  dword ptr [{G_BW_RECT}], edx"""
        if i == 2 and right_helper is not None:
            return f"""
        mov  edx, dword ptr [eax + 8]
        call {right_helper}
        mov  dword ptr [{G_BW_RECT} + 8], edx"""
        return f"""
        mov  edx, dword ptr [eax + {i * 4}]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  dword ptr [{G_BW_RECT} + {i * 4}], edx"""
    return "\n".join(field(i) for i in range(4))


def _scale_rect_arg1(right_helper=None) -> str:
    """Scale the RECT at [esp+4] into g_bw_rect and swap the arg ptr."""
    fields = _rect_fields(right_helper)
    return f"""
        mov  eax, dword ptr [esp + 4]
        {fields}
        mov  dword ptr [esp + 4], {G_BW_RECT}
    """


def asm_boxsprite():
    # Buffer_box_sprite site adapter: scale the rect (SCRATCH copy -- BaseWin fns
    # reuse their rect locals after the call, unlike PrefWin's), then the
    # pref_boxframe dispatch: fill-bearing set ([params+0x20]!=0) -> devfill,
    # hollow set -> hollow_flat (K-wide band strokes). Gate off -> plain native
    # (which is the baked hud_boxframe detour entry; canvas passes its gates).
    # W5A v4 (F42): the half-open rect (t_bw_mirrect) goes to the renderer
    # through the shared trim helpers t_bm_ho_df / t_bm_ho_hf (R - 1 / B - 1
    # in place around the call, restored after; same box_sprite contract,
    # RET 8): law basewin_box_draw_rect -- every centre box on its native
    # half-open extent, both columns, the mirror pairs exact.
    return f"""
        {gate_buffer()}
        mov  eax, dword ptr [esp + 4]
        call {PCAVE2 + MIRRECT_OFF}
        mov  dword ptr [esp + 4], {G_BW_RECT}
        mov  edx, dword ptr [esp + 8]
        cmp  dword ptr [edx + 0x20], 0
        jne  fill
        push {T_BM_HO_HF}
        ret
    fill:
        push {T_BM_HO_DF}
        ret
    native:
        jmp  {BOX_SPRITE}
    """


def asm_boxsprite_console():
    # BaseWin_init OUTER console-frame adapter (site 0x41F53E ONLY): ignore the
    # caller's mixed-space rect (device bounds + native insets) and rebuild it
    # per scaling_laws.basewin_console_frame_rect v3. Left/bottom are vanilla
    # constants through basewin_pt; the RIGHT edge is the side-rails' OWN
    # double-floor anchor fl((fl(W_dev*16/g) - 55) * g/16) — v2's pt(703) only
    # meets the rails at exact multiples (g=40); at g=25 the rails land at 1096
    # vs pt(703)=1098 and overlaid the whole right stroke (the 2026-07-21e
    # 1600x1200 "frame stroke cut off" report). W_dev read live from the canvas
    # Buffer width field (== fl(758g/16) by the slice-1 window law). Then the
    # same devfill/hollow_flat dispatch as thunk_bw_boxsprite. Gate off
    # (g<=16: canvas stays 758 wide) -> plain native with the vanilla rect.
    # v4 (2026-10-25 W5A, law basewin_console_frame_rect v4): the rails' own
    # span, drawn inclusive -- L = Lx (the left rails' composed extent, closes
    # the odd-g see-through column), R = A - 1 (the right stroke K wide, off
    # the rail's first column).  Both from t_bw_railsum (eax = S, edx = Lx;
    # A = S - Lx).  135 -> 103 B in place.
    def edge(i, v):
        return f"""
        mov  edx, dword ptr [{G}]
        imul edx, edx, {v}
        sar  edx, 4
        mov  dword ptr [{G_BW_RECT} + {i * 4}], edx"""
    return f"""
        {gate_buffer()}
        call {PCAVE2 + RAILSUM_OFF}
        mov  dword ptr [{G_BW_RECT}], edx
        mov  dword ptr [{G_BW_RECT} + 4], 0
        sub  eax, edx
        dec  eax
        mov  dword ptr [{G_BW_RECT} + 8], eax
        {edge(3, 493)}
        mov  dword ptr [esp + 4], {G_BW_RECT}
        mov  edx, dword ptr [esp + 8]
        cmp  dword ptr [edx + 0x20], 0
        jne  fill
        jmp  {HOLLOW_FLAT}
    fill:
        jmp  {DEVFILL}
    native:
        jmp  {BOX_SPRITE}
    """


def asm_boxsprite_tabframe():
    # Tab-frame box adapter (site 0x41F56A ONLY; the primitive renders each
    # stroke inclusively AT its arg, and vanilla's native args are
    # [27,4,698,29] — the [27,4,699,30] seed is exclusive-space): l/t through
    # basewin_pt; RIGHT edge = the exact column mirror of the left stroke,
    # r = 2*pt(280)+fl(166g/16)-pt(27)-1 (law basewin_tabframe_right);
    # BOTTOM edge = the row mirror of the top stroke about the buttons'
    # inclusive interval, b = 2*pt(7)+fl(20g/16)-pt(4)-1 (law
    # basewin_tabframe_bottom) — so the VISIBLE channels are equal on both
    # axes at every g (the 07-21g law's edge-coordinate mirror left the
    # far-edge channel 1 wide everywhere: 3/4 at g=22, the 2026-07-22
    # report). The -1s cost ZERO bytes: the far-edge seeds use NOT instead
    # of NEG (~x = -x-1). g is CACHED in ecx (push/pop around the body —
    # the 0xB340 slot is 176B) — no [esp+N] refs while pushed; the gate's
    # native exit never pushes. Same dispatch as the siblings.
    # v4 (2026-10-25 W5A): the axis sum is the RAIL axis (t_bw_railsum, law
    # basewin_tab_axis_sum v2) instead of GOVERNOR's 2*pt(280)+fl(166g/16):
    # r = S - pt(27) - 1 == basewin_rim_box_r(699), flush with the right
    # panel's rim and centred in the console frame.  175 -> 146 B in place.
    # v5 (2026-10-25 W7H v2, law basewin_tab_row_v): g <= G_MAX reads the frame top T and the button top t from
    # g_bw_tabrow_tbl (emitted from the law; thunk_basewin_gwinit v7 reads the same t), the bottom stroke row
    # b = ~T + 2t + fl(20g/16) -- the top stroke's mirror about the buttons, as before; g > G_MAX (unreachable)
    # keeps v4's T = pt(4), t = pt(7).  v4's 2*pt(7) left the bottom -1.12..-1.88 px off 30g/16.
    def term(v, op):
        return f"""
        imul edx, ecx, {v}
        sar  edx, 4
        {op}"""
    return f"""
        {gate_buffer()}
        push ecx
        mov  ecx, dword ptr [{G}]
        {term(27, f"mov  dword ptr [{G_BW_RECT}], edx")}
        not  edx
        mov  dword ptr [{G_BW_RECT} + 8], edx
        cmp  ecx, {G_MAX}
        jg   tfv6
        movzx edx, byte ptr [{TABROW_TBL} + ecx*2 - {2 * 17 - 1}]
        movzx eax, byte ptr [{TABROW_TBL} + ecx*2 - {2 * 17}]
        jmp  tfgo
    tfv6:
        imul edx, ecx, 4
        sar  edx, 4
        imul eax, ecx, 7
        sar  eax, 4
    tfgo:
        mov  dword ptr [{G_BW_RECT} + 4], edx
        not  edx
        add  edx, eax
        add  edx, eax
        imul eax, ecx, 20
        sar  eax, 4
        add  edx, eax
        mov  dword ptr [{G_BW_RECT} + 12], edx
        call {PCAVE2 + RAILSUM_OFF}
        add  dword ptr [{G_BW_RECT} + 8], eax
        pop  ecx
        mov  dword ptr [esp + 4], {G_BW_RECT}
        mov  edx, dword ptr [esp + 8]
        cmp  dword ptr [edx + 0x20], 0
        jne  fill
        jmp  {HOLLOW_FLAT}
    fill:
        jmp  {DEVFILL}
    native:
        jmp  {BOX_SPRITE}
    """


def asm_tile2():
    # Buffer_tile_2 site adapter: dest x,y scale via basewin_pt; W,H are EXTENTS
    # -> edge law W' = pt(x+W)-pt(x) (remainder rule: abutting expense cells stay
    # flush); src phase a3,a4 scale through the same map (vanilla passes a3==x,
    # a4==y, so a3'==x' keeps the tile pattern continuous across cells).
    def axis(pos_off, ext_off):
        return f"""
        mov  eax, dword ptr [esp + {pos_off:#x}]
        mov  edx, dword ptr [esp + {ext_off:#x}]
        add  edx, eax
        imul eax, dword ptr [{G}]
        sar  eax, 4
        imul edx, dword ptr [{G}]
        sar  edx, 4
        sub  edx, eax
        mov  dword ptr [esp + {pos_off:#x}], eax
        mov  dword ptr [esp + {ext_off:#x}], edx"""
    def phase(off):
        return f"""
        mov  eax, dword ptr [esp + {off:#x}]
        imul eax, dword ptr [{G}]
        sar  eax, 4
        mov  dword ptr [esp + {off:#x}], eax"""
    return f"""
        {gate_buffer()}
        {axis(0x10, 0x18)}
        {axis(0x14, 0x1C)}
        {phase(0x8)}
        {phase(0xC)}
    native:
        jmp  {T_SB_TILE2}
    """


def asm_box2():
    # v2 (slice-10, RELOCATED 0xB850 -> 0xEEE0): Buffer_box_2 site adapter
    # (nutrients intake highlight, site 0x4116A5): rect via scratch, then the
    # scaled path tail-jmps the ring thunk (law box2_ring_rects) so the 1px
    # outline thickens to K = stroke_width(g).  Native path stays plain BOX_2
    # (bit-identical, no scratch write).
    return f"""
        {gate_buffer()}
        {_scale_rect_arg1()}
        jmp  {BOX2RING}
    native:
        jmp  {BOX_2}
    """


def asm_box2ring():
    # slice-10 Buffer_box_2 REPLACEMENT callee (law scaling_laws.
    # box2_ring_rects): draws the vanilla outline then K-1 nested INWARD
    # rings, K = stroke_width(g) = half_down(g,16) = (2g+15)>>5 (LAW 4 --
    # NOT the HUD cellring's ceil).  Same contract as BOX_2: thiscall
    # ecx=dest Buffer; (rect*, color_h, color_v); RET 0xC.  Ring 0 is
    # unconditional (g<=16 -> K=1 -> the vanilla call, rect values
    # identical through the scratch); an inner ring that would degenerate
    # (span < 1 either axis) stops the loop (hline/vline zero-span class).
    # Targets: production current-turn site 0x40ED80 (rect already
    # device-space -- slice-2a scaled the bar grid) + thunk_bw_box2's
    # scaled tail (nutrients, rect pre-scaled in g_bw_rect).
    # K <= 1 EARLY-OUT (g <= 24): tail-jmp BOX_2 with the caller's stack
    # untouched -- bit-identical args/no scratch write, so the g=16
    # whole-function trace differ (test_strip_g16_identity executes pcave2
    # and records out-of-region call args) sees exactly the pristine call.
    return f"""
        mov  eax, dword ptr [{G}]
        add  eax, eax
        add  eax, 15
        shr  eax, 5
        cmp  eax, 1
        jle  {BOX_2}
        push ebx
        push esi
        push edi
        push ebp
        mov  esi, ecx
        mov  ebp, dword ptr [esp + 0x14]
        xor  edi, edi
    rl:
        mov  eax, dword ptr [ebp]
        add  eax, edi
        mov  dword ptr [{G_RING_RECT}], eax
        mov  ebx, dword ptr [ebp + 8]
        sub  ebx, edi
        mov  dword ptr [{G_RING_RECT} + 8], ebx
        mov  ecx, dword ptr [ebp + 4]
        add  ecx, edi
        mov  dword ptr [{G_RING_RECT} + 4], ecx
        mov  edx, dword ptr [ebp + 0xC]
        sub  edx, edi
        mov  dword ptr [{G_RING_RECT} + 0xC], edx
        test edi, edi
        jz   draw
        cmp  ebx, eax
        jle  done
        cmp  edx, ecx
        jle  done
    draw:
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push {G_RING_RECT}
        mov  ecx, esi
        call {BOX_2}
        inc  edi
        mov  eax, dword ptr [{G}]
        add  eax, eax
        add  eax, 15
        shr  eax, 5
        cmp  edi, eax
        jl   rl
    done:
        pop  ebp
        pop  edi
        pop  esi
        pop  ebx
        ret  0xC
    """


def asm_popbox_pads():
    # slice-10 base_draw cut @0x55B3CF (11B: mov edx,[ebp+0x10]; add eax,5;
    # add eax,edx; lea ecx,[edi+4]) -- the pop-number box +5/+4 pads (law
    # base_popbox_pads).  FARM-VIEW gate esi == BaseWin canvas (esi = the
    # buf arg, set @0x55B2C5 and unwritten through the whole box region;
    # main map / StatusWin / TutWin callers keep native pads -- vanilla
    # design).  Entry: eax = Font_width(text), edi = font height metric
    # ([font+0x10]), ebx LIVE (untouched), ebp = base_draw's frame.
    # Exit contract == vanilla: eax = x + textw + pad_w, ecx = metric +
    # pad_h, edx = x (param_3; stored to rect.left @0x55B3EA), edi/ebx
    # preserved; last flag writer add eax,edx (same as vanilla; the next
    # consumer sets its own flags @0x55B403).
    return f"""
        cmp  esi, {CANVAS}
        jne  nat
        mov  ecx, dword ptr [{G}]
        cmp  ecx, 16
        jle  nat
        lea  edx, [ecx + ecx*4]
        shr  edx, 4
        add  eax, edx
        shr  ecx, 2
        lea  ecx, [edi + ecx]
        jmp  fin
    nat:
        add  eax, 5
        lea  ecx, [edi + 4]
    fin:
        mov  edx, dword ptr [ebp + 0x10]
        add  eax, edx
        ret
    """


def asm_popbox_text():
    # slice-10 base_draw cuts @0x55B605 + @0x55B675 (6B each: lea edi,
    # [edx+1]; lea ebx,[eax+2]) -- the glyph pen offsets +2/+1 (law
    # base_popbox_pads text_dx/dy), same farm gate.  Both cuts sit BETWEEN
    # a live `test ecx,ecx` and its consuming `je` (vanilla keeps flags
    # across the flag-neutral leas) -> pushfd/popfd transparent
    # (feedback-cut-thunk-flag-liveness).  One thunk serves both sites
    # (plain RET; each site = E8 + 1 NOP).  Entry: eax = box left, edx =
    # box top (both post-fill-inset); outputs ebx = pen x, edi = pen y;
    # eax/edx/esi untouched (eax/edx die at the next call, esi = buffer
    # reused @0x55B689).
    return f"""
        pushfd
        cmp  esi, {CANVAS}
        jne  nat
        mov  ebx, dword ptr [{G}]
        cmp  ebx, 16
        jle  nat
        mov  edi, ebx
        shr  edi, 4
        add  edi, edx
        add  ebx, ebx
        shr  ebx, 4
        add  ebx, eax
        jmp  fin
    nat:
        lea  edi, [edx + 1]
        lea  ebx, [eax + 2]
    fin:
        popfd
        ret
    """


def asm_fill2():
    # GraphicWin_fill_2 site adapter: `this` is the WINDOW (BaseWin_g), not the
    # canvas Buffer -- gate on ecx==BaseWin_g && canvasW>758.  W5A v5: the
    # rect through t_bw_fillrect (law basewin_fill_rect: the farm panel's
    # interior fill = its half-open box inset by K; the SUPPORT view's
    # full-panel fill = basewin_mirror_rect).
    return f"""
        cmp  ecx, {BASEWIN_G}
        jne  native
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  eax, dword ptr [esp + 4]
        call {PCAVE2 + FILLRECT_OFF}
        mov  dword ptr [esp + 4], {G_BW_RECT}
    native:
        jmp  {FILL_2}
    """


def asm_sd2():
    # Sprite_draw_2 site adapter: ecx is the SPRITE; gate on the dest ARG
    # [esp+4]==canvas. x,y via basewin_pt; ratio law basewin_sprite_ratio:
    # (num,den) -> (num*g, den*16) composed exactly, never pre-floored.
    return f"""
        cmp  dword ptr [esp + 4], {CANVAS}
        jne  native
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  eax, dword ptr [{G}]
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
        imul eax, dword ptr [esp + 0x14]
        mov  dword ptr [esp + 0x14], eax
        shl  dword ptr [esp + 0x18], 4
    native:
        jmp  {SPRITE_DRAW_2}
    """


def asm_mono():
    # FUN_005E3E00 (mono-draw wrapper) site adapter: same laws; num/den at
    # [esp+0x18]/[esp+0x1C] (the wrapper stashes them into the scale globals).
    return f"""
        cmp  dword ptr [esp + 4], {CANVAS}
        jne  native
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  eax, dword ptr [{G}]
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
        imul eax, dword ptr [esp + 0x18]
        mov  dword ptr [esp + 0x18], eax
        shl  dword ptr [esp + 0x1C], 4
    native:
        jmp  {SPRITE_MONO}
    """


def asm_sbc():
    # Sprite_blit_scaled_core site adapter (the 8 BaseWin_psych_row faces -- the
    # farm marker has its own detour).  CALL helper with the core's contract
    # (thiscall ecx=Sprite; dest, key, x, y; RET 0x10).  x,y scale via basewin_pt.
    # v2 (2026-09-20): the faces go through thunk_sprite_bilinear x g/16 (Sprite_draw_2
    # contract: + num, den), not the engine core under a SCALE-globals bracket --
    # every citizen face carries its own 1:1 scanline dither under a photo and the
    # core's source-driven NN banded it at g=22/25 (the F4 faces' law, rw kinds v5;
    # scaling_laws.basewin_pop_face_enlarge).  psych_row sets no clip of its own and
    # its step law keeps every face inside [x, x+w), so the bilinear's dest-bounds
    # clip is sufficient.  g_bw_ret / g_bw_sav stay reserved (unused by this thunk).
    # v3 (2026-09-20): the callee is thunk_face_hybrid (same contract, same clip):
    # bilinear photo + the face's baked scanline background regenerated at device
    # density (scaling_laws.face_hybrid_enlarge; basewin_pop_face_enlarge == 'hybrid').
    return f"""
        cmp  dword ptr [esp + 4], {CANVAS}
        jne  native
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  eax, dword ptr [{G}]
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
        push 16
        push eax
        push dword ptr [esp + 0x18]
        push dword ptr [esp + 0x18]
        push dword ptr [esp + 0x18]
        push dword ptr [esp + 0x18]
        mov  eax, {FACE_HYBRID}
        call eax
        ret  0x10
    native:
        jmp  {SPRITE_BLIT_CORE}
    """


def asm_mapblit():
    # v3 (2026-07-26, SUPPORT-tab banding fix): the embedded map window is now
    # DEVICE-sized (thunk_bw_supprect scales MapWin_init_2's mode-2 rect
    # locals), so the map renders at device density from native tile art and
    # the composite goes back to vanilla's 1:1 Buffer_copy_4 -- ZERO
    # resampling (v2's copy_3 NN stretch of the native-density render was the
    # water banding).  The caller's centering math mixes the NATIVE panel rect
    # with the now-DEVICE srcW/srcH, so its dstX/dstY are cross-space garbage:
    # recompute dst = scaled-panel centering, per axis
    #     dst = pt(lo) + ((pt(hi) - pt(lo)) - src) >> 1
    # (laws support_map_rect edges + vanilla's own centering form; since the
    # window rect == the scaled panel rect the offset is 0 and the map fills
    # the panel flush with the thunk_bw_clip clip).  srcX/Y/W/H pass through;
    # ecx (src Buffer) untouched.  COUPLED to thunk_bw_supprect -- one yaml
    # group; without it the map would draw native-small (crisp, no crash).
    # entry: [esp+4]=dst, +8=srcX(0), +0xC=srcY(0), +0x10=dstX, +0x14=dstY,
    #        +0x18=srcW, +0x1C=srcH.  ecx = src Buffer (passes through).
    return f"""
        cmp  dword ptr [esp + 4], {CANVAS}
        jne  native
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  edx, dword ptr [{RSP_RECT}]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  eax, dword ptr [{RSP_RECT} + 8]
        imul eax, dword ptr [{G}]
        sar  eax, 4
        sub  eax, edx
        sub  eax, dword ptr [esp + 0x18]
        sar  eax, 1
        add  edx, eax
        mov  dword ptr [esp + 0x10], edx
        mov  edx, dword ptr [{RSP_RECT} + 4]
        imul edx, dword ptr [{G}]
        sar  edx, 4
        mov  eax, dword ptr [{RSP_RECT} + 0xC]
        imul eax, dword ptr [{G}]
        sar  eax, 4
        sub  eax, edx
        sub  eax, dword ptr [esp + 0x1C]
        sar  eax, 1
        add  edx, eax
        mov  dword ptr [esp + 0x14], edx
    native:
        jmp  {COPY_4}
    """


def asm_supprect():
    # SUPPORT-tab banding fix root (2026-07-26): 5-byte JMP detour @0x470B2A
    # over MapWin_init_2's mode-2 rect-load block (0x470B2A..0x470B51,
    # straight-line, entered only by the JNZ fallthrough; original bytes past
    # the JMP stay in place, unreachable).  Replicates the four rcRspPanel
    # loads into the mode-2 ebp locals [ebp-0x10..-0x4], then -- device gate
    # only -- scales each edge fl(v*g/16) IN THE LOCALS (law
    # scaling_laws.support_map_rect: the same per-edge form thunk_bw_clip
    # applies to draw_support's opening set_clip, so window and clip stay
    # flush).  The +0x40B8C GLOBAL is shared (TutWin_tour1, BaseWin_click
    # tooltip) and is never written.  GraphicWin_init_2 then sizes the
    # embedded map window+canvas device, and draw_support's vanilla fit loop
    # picks the ~g/16-denser zoom index by itself (law support_map_fit).
    # Gate = the family gate (canvasW>758 <=> slice-1 active, implies g>16;
    # belt-and-braces g check too); g<=16 stores byte-identical values.
    # Original block is MOV-only (flag-neutral) -> pushfd/popfd transparent
    # per the cut-thunk EFLAGS rule; eax/ecx/edx clobbered exactly like the
    # original block, all other regs untouched.
    scale4 = "\n".join(f"""
        mov  edx, dword ptr [ebp - {o:#x}]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [ebp - {o:#x}], edx""" for o in (0x10, 0xC, 8, 4))
    return f"""
        pushfd
        mov  edx, dword ptr [{RSP_RECT}]
        mov  eax, dword ptr [{RSP_RECT} + 4]
        mov  ecx, dword ptr [{RSP_RECT} + 8]
        mov  dword ptr [ebp - 0x10], edx
        mov  edx, dword ptr [{RSP_RECT} + 0xC]
        mov  dword ptr [ebp - 0xC], eax
        mov  dword ptr [ebp - 8], ecx
        mov  dword ptr [ebp - 4], edx
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  done
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  done
        {scale4}
    done:
        popfd
        jmp  {SUPP_RESUME}
    """


def asm_spotadd():
    # Spot_add site adapter (farm + facilities center hit rects): X,Y through
    # basewin_pt, W,H via the edge law so the hit rect covers exactly the drawn
    # (scaled) pixels. `this` is the window -- gate ecx==BaseWin_g.
    return f"""
        cmp  ecx, {BASEWIN_G}
        jne  native
        mov  eax, dword ptr [{CANVAS_W}]
        cmp  eax, {W_NATIVE}
        jle  native
        mov  eax, dword ptr [esp + 0xC]
        mov  edx, dword ptr [esp + 0x14]
        add  edx, eax
        imul eax, dword ptr [{G}]
        sar  eax, 4
        imul edx, dword ptr [{G}]
        sar  edx, 4
        sub  edx, eax
        mov  dword ptr [esp + 0xC], eax
        mov  dword ptr [esp + 0x14], edx
        mov  eax, dword ptr [esp + 0x10]
        mov  edx, dword ptr [esp + 0x18]
        add  edx, eax
        imul eax, dword ptr [{G}]
        sar  eax, 4
        imul edx, dword ptr [{G}]
        sar  edx, 4
        sub  edx, eax
        mov  dword ptr [esp + 0x10], eax
        mov  dword ptr [esp + 0x18], edx
    native:
        jmp  {SPOT_ADD}
    """


def raw(name: str, off: int, asm: str) -> bytes:
    """Assembled bytes with sentinel imm32s left in place (parity tests map a
    page at the sentinel address instead of resolving the placeholder)."""
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, addr=PCAVE2 + off)
    return bytes(code)


def emit(name: str, off: int, asm: str) -> int:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, addr=PCAVE2 + off)
    blob = bytes(code)
    out, i = [], 0
    while i < len(blob):
        for sent, tok in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(tok)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    print(f"{name}  {len(blob)} bytes @ pcave2+{off:#x} (VA {PCAVE2 + off:#x})"
          f" .. end {off + len(blob):#x}")
    print('        bytes: "' + " ".join(out) + '"')
    print()
    return len(blob)


def main() -> int:
    # ---- W5A (2026-10-25): the base-screen mirror law helpers + gwinit v6 (region 0x3C000..0x3CFFF) ----
    for name, off, asm, limit in [
        ("t_bw_railsum", RAILSUM_OFF, asm_railsum(), RIMCORE_OFF),
        ("t_bw_rimcore", RIMCORE_OFF, asm_rimcore(), RIMX_OFF),
        ("t_bw_rimx", RIMX_OFF, asm_rimx(False), LMIR_OFF),
        ("t_bw_lmir", LMIR_OFF, asm_lmir(), W5A_HELPERS_END),
        ("t_bw_railscale", RAILSCALE_BW_OFF, asm_railscale_bw(), RAILANCHOR_OFF),
        ("t_bw_mirrect", MIRRECT_OFF, asm_mirrect(), MIRRECT_END),
        ("t_bw_fillrect", FILLRECT_OFF, asm_fillrect(), FILLRECT_END),
        ("t_bw_railanchor", RAILANCHOR_OFF, asm_railanchor(), W5A_V2_END),
    ]:
        n = emit(name, off, asm)
        assert off + n <= limit, f"{name} overruns its slot ({off:#x}+{n} > {limit:#x})"
    n1 = emit("thunk_basewin_gwinit", GWINIT_OFF, asm_gwinit())
    assert W5A_HELPERS_END <= GWINIT_OFF and GWINIT_OFF + n1 <= GWINIT_SLOT_END, "gwinit v8 overruns its W7H slot"
    # ---- W8B (2026-10-27): the button rows' gaps (region 0x3F970..0x3FFFF) ----
    tbl = rows_table()
    print(f"g_bw_rows_tbl  {len(tbl)} bytes @ pcave2+{ROWS_TBL_OFF:#x} .. end {ROWS_TBL_OFF + len(tbl):#x}")
    print('        bytes: "' + " ".join(f"{b:02X}" for b in tbl) + '"')
    print()
    assert KID_OFF + 12 <= ROWS_TBL_OFF and ROWS_TBL_OFF + len(tbl) <= ROWFIX_OFF_V1, "g_bw_rows_tbl overruns"
    rtbl = rspv_table()
    print(f"g_bw_rspv_tbl  {len(rtbl)} bytes @ pcave2+{RSPV_TBL_OFF:#x} .. end {RSPV_TBL_OFF + len(rtbl):#x}")
    print('        bytes: "' + " ".join(f"{b:02X}" for b in rtbl) + '"')
    print()
    assert RSPV_TBL_OFF + len(rtbl) <= RSPV_TBL_END <= W8B_END, "g_bw_rspv_tbl overruns"
    n = emit("t_bw_rowfix", ROWFIX_OFF, asm_rowfix())
    assert RSPV_TBL_END <= ROWFIX_OFF and ROWFIX_OFF + n <= ROWFIX_END <= W8B_END, "t_bw_rowfix overruns its slot"
    n = emit("thunk_bw_boxsprite_okrow", OKBOX_OFF, asm_boxsprite_okrow())
    assert OKBOX_OFF + n <= W8B_END, "thunk_bw_boxsprite_okrow overruns the W8B region"
    nf = emit("thunk_bw_facsb_attach", FACSB_ATTACH_OFF, asm_facsb_attach())
    assert FACSB_ATTACH_OFF + nf <= FACSB_ATTACH_END, "facsb_attach overruns gwinit's old slot"
    nw = emit("t_bw_wheel_down", WHEEL_DOWN_OFF, asm_bw_wheel_down())
    assert WHEEL_DOWN_OFF + nw <= WHEEL_DOWN_END, "bw_wheel_down overruns thunk_rail_gate"
    nu = emit("t_bw_wheel_up", WHEEL_UP_OFF, asm_bw_wheel_up())
    assert FACSB_ATTACH_OFF + nf <= WHEEL_UP_OFF, "bw_wheel_up overlaps facsb_attach"
    assert WHEEL_UP_OFF + nu <= WHEEL_ATE_OFF <= WHEEL_UP_END - 4, "bw_wheel_up overruns the cell"
    n = emit("thunk_bw_boxsprite_tabframe", TABFRAME_OFF, asm_boxsprite_tabframe())
    assert TABFRAME_OFF + n <= BTNZOOM_OFF, "tabframe overruns the old gwinit slot"
    n2 = emit("thunk_basewin_btnzoom", BTNZOOM_OFF, asm_btnzoom())
    # WARNING (learned 2026-08-03, btnzoom v5): this bound only knows about the
    # thunks THIS script emits.  A later arc had squatted an unrelated thunk
    # (thunk_scale_reject_uncache, group scale_ratio_uncache) at 0xB430 — inside
    # what the assert below calls free — so v5 grew straight through it and this
    # assert still passed.  Only the patcher's own cave-overlap verifier caught
    # it (it refused to write; the squatter was relocated to 0xB300).  Treat a
    # green assert here as necessary, NOT sufficient: before growing any thunk,
    # check the pcave2 occupancy in patches.yaml itself.  [[feedback-cave-ledger-lengths]]
    assert BTNZOOM_OFF + n2 <= RECT_CORE_OFF, "btnzoom overruns the slice-2 slots"

    # ---- slice 2 ----
    slots = [
        ("thunk_bw_rect_core", RECT_CORE_OFF, asm_rect_core(), XY_CORE_OFF),
        ("thunk_bw_xy_core", XY_CORE_OFF, asm_xy_core(), CLIP_OFF),
        ("thunk_bw_clip", CLIP_OFF, asm_clip(), STUB_L4_OFF),
        # slice-6: the stub tails route through the pen-descale EXT brackets
        # (same 10B, only the jmp rel32 changed -- no site bytes move)
        ("thunk_bw_text_l4", STUB_L4_OFF,
         asm_stub(PCAVE2 + RECT_CORE_OFF, PCAVE2 + EXT_L4_OFF), STUB_C7_OFF),
        ("thunk_bw_text_c7", STUB_C7_OFF,
         asm_stub(PCAVE2 + RECT_CORE_OFF, PCAVE2 + EXT_C7_OFF), STUB_R6_OFF),
        ("thunk_bw_text_r6", STUB_R6_OFF,
         asm_stub(PCAVE2 + RECT_CORE_OFF, PCAVE2 + EXT_R6_OFF), STUB_L3_OFF),
        ("thunk_bw_text_l3", STUB_L3_OFF,
         asm_stub(PCAVE2 + XY_CORE_OFF, PCAVE2 + EXT_L3_OFF), STUB_R5_OFF),
        ("thunk_bw_text_r5", STUB_R5_OFF,
         asm_stub(PCAVE2 + XY_CORE_OFF, PCAVE2 + EXT_R5_OFF), CENT5_OFF),
        ("thunk_bw_text_c5", CENT5_OFF, asm_cent5(), FONTINIT_OFF),
        ("thunk_bw_fontinit", FONTINIT_OFF, asm_fontinit(), FINDFONT_OFF),
        ("thunk_bw_findfont", FINDFONT_OFF, asm_findfont(), SETFONT_OFF),
        ("thunk_bw_setfont", SETFONT_OFF, asm_setfont(), G_BW_RECT_OFF),
    ]
    for name, off, asm, limit in slots:
        n = emit(name, off, asm)
        assert off + n <= limit, f"{name} overruns its slot ({off:#x}+{n} > {limit:#x})"
    assert G_BW_FONT_OFF + 0x28 <= SLICE2_END <= BOXSPRITE_OFF

    # ---- slices 3 + 4 ----
    slots34 = [
        ("thunk_bw_boxsprite", BOXSPRITE_OFF, asm_boxsprite(), TILE2_OFF),
        ("thunk_bw_tile2", TILE2_OFF, asm_tile2(), BOX2_OLD_SLOT),
        ("thunk_bw_fill2", FILL2_OFF, asm_fill2(), SD2_OFF),
        ("thunk_bw_sd2", SD2_OFF, asm_sd2(), MONO_OFF),
        ("thunk_bw_mono", MONO_OFF, asm_mono(), SBC_OFF),
        ("thunk_bw_sbc", SBC_OFF, asm_sbc(), G_BW_RET_OFF),
    ]
    for name, off, asm, limit in slots34:
        n = emit(name, off, asm)
        assert off + n <= limit, f"{name} overruns its slot ({off:#x}+{n} > {limit:#x})"
    assert G_BW_SAV_OFF + 8 <= SLICE34_END

    # ---- slice 5 (mapblit = v3, slice-9 semantics; slot unchanged) ----
    for name, off, asm, limit in [
        ("thunk_bw_mapblit", MAPBLIT_OFF, asm_mapblit(), SPOTADD_OFF),
        ("thunk_bw_spotadd", SPOTADD_OFF, asm_spotadd(), SLICE5_END),
    ]:
        n = emit(name, off, asm)
        assert off + n <= limit, f"{name} overruns its slot ({off:#x}+{n} > {limit:#x})"
    assert SLICE5_END <= CAVE_LIMIT

    # ---- slice 9 (SUPPORT-tab map density) ----
    n = emit("thunk_bw_supprect", SUPPRECT_OFF, asm_supprect())
    assert SUPPRECT_OFF + n <= SUPPRECT_END, "supprect overruns the pcave2 tail"

    # ---- slice 10 (box_2 ring polish + pop-number box pads) ----
    for name, off, asm, limit in [
        ("thunk_bw_box2ring", BOX2RING_OFF, asm_box2ring(), BOX2_OFF),
        ("thunk_bw_box2", BOX2_OFF, asm_box2(), POPBOX_PADS_OFF),
        ("thunk_bw_popbox_pads", POPBOX_PADS_OFF, asm_popbox_pads(), POPBOX_TEXT_OFF),
        ("thunk_bw_popbox_text", POPBOX_TEXT_OFF, asm_popbox_text(), G_RING_RECT_OFF),
    ]:
        n = emit(name, off, asm)
        assert off + n <= limit, f"{name} overruns its slot ({off:#x}+{n} > {limit:#x})"
    print("slice-10 arithmetic == scaling_laws.box2_ring_rects (K = (2g+15)>>5"
          " == stroke_width, ring 0 unconditional, degenerate inner rings"
          " dropped) / base_popbox_pads (basewin_pt of 5/4 + pen 2/1)")

    # ---- slice 6 ----
    for name, off, asm, limit in [
        ("thunk_bw_ext_l4", EXT_L4_OFF, asm_text_ext(WRITE_L_4), EXT_C7_OFF),
        ("thunk_bw_ext_c7", EXT_C7_OFF, asm_text_ext(CENT_L_7), EXT_R6_OFF),
        ("thunk_bw_ext_r6", EXT_R6_OFF, asm_text_ext(RIGHT_L_6), EXT_L3_OFF),
        ("thunk_bw_ext_l3", EXT_L3_OFF, asm_text_ext(WRITE_L_3), EXT_R5_OFF),
        ("thunk_bw_ext_r5", EXT_R5_OFF, asm_text_ext(RIGHT_L_5), G_BW_RET2_OFF),
        ("thunk_bw_sf_core", SF_CORE_OFF, asm_sf_core(), SF_14B_OFF),
        ("thunk_bw_sf_14b", SF_14B_OFF, asm_sf_variant(14, 1), SF_12P_OFF),
        ("thunk_bw_sf_12p", SF_12P_OFF, asm_sf_variant(12, 0), SF_12B_OFF),
        ("thunk_bw_sf_12b", SF_12B_OFF, asm_sf_variant(12, 1), SF_10B_OFF),
        ("thunk_bw_sf_10b", SF_10B_OFF, asm_sf_variant(10, 1), HDRBOX_OFF),
        ("thunk_bw_boxsprite_hdr", HDRBOX_OFF, asm_boxsprite_hdr(), FARMENTRY_OFF),
        ("thunk_bw_farmzoom_entry", FARMENTRY_OFF, asm_farmentry(), FARMSEED_OFF),
        ("thunk_bw_farmseed", FARMSEED_OFF, asm_farmseed(), FARMZOOMSET_OFF),
        ("thunk_bw_farmzoomset", FARMZOOMSET_OFF, asm_farmzoomset(), FARMICONADV_OFF),
        ("thunk_bw_farmiconadv", FARMICONADV_OFF, asm_farmiconadv(), SLICE6_END),
    ]:
        n = emit(name, off, asm)
        assert off + n <= limit, f"{name} overruns its slot ({off:#x}+{n} > {limit:#x})"
    assert G_BW_RET2_OFF + 4 <= SF_CORE_OFF
    assert SLICE6_END <= CAVE_LIMIT

    # ---- slice 7 ----
    n = emit("thunk_bw_boxsprite_console", CONSOLE_OFF, asm_boxsprite_console())
    assert CONSOLE_OFF + n <= CONSOLE_SLOT_END, "console v3 overruns the 0x4000 gap"
    n = emit("thunk_bw_btnfont", BTNFONT_OFF, asm_btnfont())
    assert BTNFONT_OFF + n <= CONSOLE_END <= CAVE_LIMIT

    # ---- slice 8 (farm yield orbs) ----
    for name, off, asm, limit in [
        ("thunk_bw_farmorb_mono", FARMORB_MONO_OFF, asm_farmorb_mono(), FARMORB_SD2A_OFF),
        ("thunk_bw_farmorb_sd2a", FARMORB_SD2A_OFF, asm_farmorb_sd2a(), FARMORB_SD2B_OFF),
        ("thunk_bw_farmorb_sd2b", FARMORB_SD2B_OFF, asm_farmorb_sd2b(), BTNFONT_OFF),
        ("thunk_bw_farmorb_sbc", FARMORB_SBC_OFF, asm_farmorb_sbc(), CONSOLE_END),
    ]:
        n = emit(name, off, asm)
        assert off + n <= limit, f"{name} overruns its slot ({off:#x}+{n} > {limit:#x})"

    # slice-8 arithmetic == scaling_laws.basewin_sprite_ratio(1,1,g): the
    # thunks write num=g, den=16 over the literal 1,1 (gate canvasW>758
    # falls through to vanilla 1,1 at g<=16 = the law's identity branch).
    import sys as _s8
    from pathlib import Path as _P8
    _s8.path.insert(0, str(_P8(__file__).resolve().parent))
    from scaling_laws import basewin_sprite_ratio
    for g in range(17, 41):
        assert (g, 16) == basewin_sprite_ratio(1, 1, g), g
    assert (1, 1) == basewin_sprite_ratio(1, 1, 16)
    print("slice-8 arithmetic == scaling_laws.basewin_sprite_ratio(1,1,g) "
          "(g 17..40); g<=16 falls through to the vanilla 1,1 literals")

    # slice-7 v4 arithmetic == scaling_laws.basewin_console_frame_rect v4 (W5A v2): t_bw_railsum's
    # S = (726g)>>4 and Lx = (15g)>>4 + (g>>1); L = Lx, R = S - Lx - 1, B = (493g)>>4.  The right rails
    # sit on A* = S - Lx (t_bw_railscale / t_bw_railanchor, law basewin_rail_strip_x).
    import sys as _s
    from pathlib import Path as _P
    _s.path.insert(0, str(_P(__file__).resolve().parent))
    from scaling_laws import basewin_console_frame_rect, basewin_rail_axis_sum

    from scaling_laws import basewin_rail_strip_x, basewin_rail_anchor

    def _railsum(g):
        lx = ((15 * g) >> 4) + (g >> 1)
        return (726 * g) >> 4, lx
    for g in range(16, 41):        # t_bw_railscale / t_bw_railanchor == basewin_rail_strip_x
        w = (W_NATIVE * g) >> 4 if g > 16 else W_NATIVE
        S, lx = _railsum(g)
        if g > 16:
            assert S - lx == basewin_rail_anchor(g), g
            for x, want in ((0, 0), (15, (15 * g) >> 4), (w - 55, S - lx), (w - 47, S - lx + ((8 * g) >> 4))):
                assert basewin_rail_strip_x(w, x, g) == want, (g, x)
            assert S - lx + ((8 * g) >> 4) + ((15 * g) >> 4) == S <= w, g    # the right rails end ON the axis
    assert basewin_rail_anchor(16) == 703
    for g in range(17, 41):
        S, lx = _railsum(g)
        assert S == basewin_rail_axis_sum(g), g
        want = (lx, 0, S - lx - 1, (493 * g) >> 4)
        assert want == basewin_console_frame_rect(g), g
    assert basewin_console_frame_rect(40) == (57, 0, 1757, 1232)  # 4K: the right rail at A* = 1758
    print("slice-7 v4 arithmetic == scaling_laws.basewin_console_frame_rect v4 "
          "(g 17..40, the rails' own span, inclusive); g<=16 vanilla (gate)")

    # sanity: the asm arithmetic == scaling_laws.basewin_window_rect
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import basewin_window_rect

    for g, sw, sh, strip in ((16, 1024, 768, 213), (22, 1920, 1080, 292),
                             (25, 1600, 1200, 332), (40, 3840, 2160, 532)):
        if g <= 16:
            continue  # thunk chains straight through at g<=16 (vanilla args stand)
        w = (W_NATIVE * g) >> 4
        h = (H_NATIVE * g) >> 4
        x = (sw - ((C_NATIVE * g) >> 4)) >> 1
        y = (sh - strip) - h
        assert (x, y, w, h) == basewin_window_rect(sw, sh, strip, g), g
    print("asm arithmetic == scaling_laws.basewin_window_rect at g=22/25/40; "
          "g=16 falls through to vanilla args (algebraic identity)")

    # gwinit v3 mirror arm == scaling_laws.basewin_tab_mirror_x: for a child at
    # (x>363, y==7) the asm computes -pt(726-x-w) - fl(wg/16) + 2*pt(280) +
    # fl(166g/16) into the x slot; the tabframe thunk seeds the far edges
    # with NOT (~pt = -pt-1: the stroke-row mirror) then adds the axis sum
    # (laws basewin_tabframe_right/_bottom, v3 2026-07-22).
    # v6 / tabframe v4 (W5A): the axis sum is t_bw_railsum's S (law basewin_tab_axis_sum v2);
    # GOVERNOR (2x + w == 726) w = S - 2*pt(x); a rim child w = rim_x(x + w) - pt(x).
    from scaling_laws import (basewin_tab_mirror_x, basewin_tabframe_right, basewin_gov_w,
                              basewin_child_w, basewin_rim_x, basewin_rim_box_r)
    from scaling_laws import basewin_child_rect
    for g in range(17, 41):
        S, _lx = _railsum(g)
        for x, w in ((470, 112), (584, 112)):
            asm_x = S - (((726 - x - w) * g) >> 4) - ((w * g) >> 4)
            assert asm_x == basewin_tab_mirror_x(x, w, g), (x, g)
        # v7 (W7H): the chevrons (D square, centre on S), OK through S2 = pt(128) + pt(622), the tab-row top;
        # v8 (W8B): t_bw_rowfix then overwrites the chevrons' x, the twin rows' buttons and the RENAME / OK y from
        # g_bw_rows_tbl (pinned against the laws in test_bw_rows_asm_parity.py)
        import struct as _st
        d, yt = (20 * g) >> 4, tabrow_table()[2 * (g - 17)]
        xe, wb, xd, xc, xr, wr, xs, tok, _T, _B = _st.unpack_from("<10H", rows_table(), ROWS_STRIDE * (g - 17))
        assert (xc, yt, d, d) == basewin_child_rect(258, 7, 20, 20, g), g
        assert (S - xc - d, yt, d, d) == basewin_child_rect(448, 7, 20, 20, g), g
        assert (xe, yt, wb, d) == basewin_child_rect(30, 7, 112, 20, g), g
        assert (S - xd - wb, yt, wb, d) == basewin_child_rect(470, 7, 112, 20, g), g
        yr = _st.unpack_from("<H", rspv_table(), 2 * (g - 17))[0]      # W8R: the row's top (basewin_rsp_row_v)
        assert (xr, yr, wr, d) == basewin_child_rect(169, 234, 128, 20, g), g
        assert (xs, yr, S - 2 * xs, d) == basewin_child_rect(299, 234, 128, 20, g), g
        assert (S - xr - wr, yr, wr, d) == basewin_child_rect(429, 234, 128, 20, g), g
        s2 = ((128 * g) >> 4) + ((622 * g) >> 4)
        assert (s2 - ((369 * g) >> 4), tok, ((369 * g) >> 4) - ((131 * g) >> 4),
                (20 * g) >> 4) == basewin_child_rect(381, 449, 238, 20, g), g
        assert (yt, d) == basewin_child_rect(30, 7, 112, 20, g)[1::2], g
        assert S - 2 * ((280 * g) >> 4) == basewin_gov_w(g), g
        asm_r = S + ~((27 * g) >> 4)
        assert asm_r == basewin_tabframe_right(g) == basewin_rim_box_r(699, g), g
        for r in range(560, 710):
            rim = 690 <= r <= 699
            asm_rx = S - (((726 - r) * g) >> 4) if rim else (r * g) >> 4
            assert asm_rx == basewin_rim_x(r, g), (r, g)
            assert asm_rx - 1 == basewin_rim_box_r(r, g), (r, g)     # v4: every box half-open
        assert basewin_rim_x(693, g) - (S - ((157 * g) >> 4)) == basewin_child_w(569, 124, g), g   # v3: left mirrored too
    # tabframe v3 bottom edge == basewin_tabframe_bottom (stroke-row mirror):
    # asm accumulates ~pt(4) + 2*pt(7) + fl(20g/16) in RECT+12.
    from scaling_laws import basewin_tabframe_bottom
    for g in range(17, 41):
        # v5 (W7H v2): T, t from g_bw_tabrow_tbl; b = ~T + 2t + fl(20g/16)
        tbl = tabrow_table()
        yt, tt = tbl[2 * (g - 17)], tbl[2 * (g - 17) + 1]
        from scaling_laws import basewin_tabframe_top, stroke_width
        assert tt == basewin_tabframe_top(g), g
        asm_b = ~tt + 2 * yt + ((20 * g) >> 4)
        assert asm_b == basewin_tabframe_bottom(g), g
        top_channel = yt - tt - stroke_width(g)
        btn_b = yt + ((20 * g) >> 4) - 1 + stroke_width(g)
        assert asm_b - btn_b == top_channel, g     # visible-channel symmetry pin
    print("gwinit v7 tab / chevron / OK-row arms == scaling_laws.basewin_tab_mirror_x / basewin_child_rect / basewin_gov_w + tabframe v5 "
          "right/bottom == basewin_tabframe_right/_bottom + rim_x / rim_box_r / child_w (g 17..40); "
          "g<=16 chains native")

    # facsb_attach arithmetic == scaling_laws.basewin_facsb_rect: t/b/r via
    # (v*g)>>4, x0 = pt(r) - ((12*g)>>4); g<=16 leaves the rect untouched.
    from scaling_laws import basewin_facsb_rect
    for g in (17, 22, 25, 40):
        for (l, t, r, b) in ((572, 42, 730, 470), (572, 42, 730, 300), (681, 60, 693, 251)):
            x1 = basewin_rim_x(r, g)      # t_bw_rimx (W5A): the real r 693 is a rim
            asm = (x1 - ((12 * g) >> 4), (t * g) >> 4, x1, (b * g) >> 4)
            assert asm == basewin_facsb_rect(l, t, r, b, g), (g, l, t, r, b)
    assert basewin_facsb_rect(572, 42, 730, 470, 16) == (718, 42, 730, 470)
    print("facsb_attach arithmetic == scaling_laws.basewin_facsb_rect (g 17..45; g<=16 native)")

    # slice-2 arithmetic == scaling_laws.basewin_pt / basewin_font_size:
    # every adapter computes (v*g)>>4 (imul; sar 4 = arithmetic shift, floor
    # toward -inf for the negative clip sentinels) behind a canvasW>758 gate
    # that is FALSE whenever g<=16 (canvas stays 758) -> identity, same as the
    # laws' g<=NATIVE_G arm.
    from scaling_laws import basewin_pt, basewin_font_size
    for g in (17, 22, 25, 32, 40):
        for v in (-5, 0, 3, 14, 490, 758, 1000):
            assert (v * g) >> 4 == basewin_pt(v, g), (v, g)
        assert (SHARED_FONT_SIZE * g) >> 4 == basewin_font_size(SHARED_FONT_SIZE, g)
        for size in (10, 12, 14):
            assert (size * g) >> 4 == basewin_font_size(size, g), (size, g)
    print("slice-2 adapter arithmetic == scaling_laws.basewin_pt/basewin_font_size "
          "(g>16 sweep; g<=16 = gate-off identity)")

    # slice-3/4 arithmetic == the laws:
    #   tile_2 extents: W' = pt(x+W) - pt(x)  (edge/remainder law, per axis)
    #   sprite ratio:   (num, den) -> (num*g, den*16), never pre-floored
    from scaling_laws import basewin_sprite_ratio
    for g in (17, 22, 25, 40):
        for x, w in ((0, 10), (3, 7), (13, 22), (100, 1), (-2, 4)):
            wp = (((x + w) * g) >> 4) - ((x * g) >> 4)
            assert wp == basewin_pt(x + w, g) - basewin_pt(x, g), (x, w, g)
        for num, den in ((1, 1), (2, 1), (3, 2)):
            assert (num * g, den << 4) == basewin_sprite_ratio(num, den, g)
    print("slice-3/4 adapter arithmetic == basewin_pt edge law / basewin_sprite_ratio")

    # slice-6 arithmetic == the laws:
    #   EXT bracket:  eax = (eax<<4) idiv g  (eax>=0: trunc == floor) == pen law
    #   sf variants:  fl(size*g/16) == basewin_font_size (10/12/14 swept above)
    #   farm zoom:    (num*g, den<<4), num<=0 -> (1,1) first == basewin_farm_zoom
    #   farm seed:    port of basewin_farm_seed, both arms
    from scaling_laws import (basewin_farm_seed, basewin_farm_zoom,
                              basewin_pen_descale)
    for g in (17, 22, 25, 40):
        for x in (0, 23, 199, 473, 1183, 1857, 4700):
            assert (x << 4) // g == basewin_pen_descale(x, g), (x, g)
        for num, den in ((-1, -1), (0, 7), (1, 1), (2, 3)):
            n2, d2 = (1, 1) if num <= 0 else (num, den)
            assert (n2 * g, d2 << 4) == basewin_farm_zoom(num, den, g)
        for x0, y0, x1 in ((70, 20, 540), (186, 35, 656)):
            for raw in (51, 126, (g * 50 // 16) + 1):
                step2 = ((raw >> 2) << 1)
                x0d, x1d = (x0 * g) >> 4, (x1 * g) >> 4
                y0d = (y0 * g) >> 4
                l28 = ((x1d - x0d) >> 1) - 2 * step2 + x0d
                l2c = 3 * step2 + (g >> 2) + y0d
                assert (step2, l28, l2c) == basewin_farm_seed(x0, y0, x1, raw, g)
                # native arm (thunk's gate-off path)
                l28n = ((x1 - x0) >> 1) - 2 * step2 + x0
                l2cn = 3 * step2 + 4 + y0
                assert (step2, l28n, l2cn) == basewin_farm_seed(x0, y0, x1, raw, 16)
    print("slice-6 adapter arithmetic == basewin_pen_descale / basewin_farm_zoom"
          " / basewin_farm_seed (both arms)")

    # slice-9 arithmetic == scaling_laws.support_map_rect (+ the fit-loop
    # consequence support_map_fit): supprect computes (v*g)>>4 per edge over
    # the rcRspPanel loads; mapblit v3 centers dst = l' + ((r'-l') - srcW)>>1
    # over the same edges, which is 0-offset when srcW == the window width
    # the fit loop saw (both derive from the identical per-edge floors).
    from scaling_laws import (BASEWIN_RSP_PANEL_NATIVE, support_map_fit,
                              support_map_rect)
    assert BASEWIN_RSP_PANEL_NATIVE == (166, 33, 560, 257)
    assert support_map_rect(*BASEWIN_RSP_PANEL_NATIVE, 16) == \
        BASEWIN_RSP_PANEL_NATIVE
    for g in range(17, 41):
        edges = tuple((v * g) >> 4 for v in BASEWIN_RSP_PANEL_NATIVE)
        assert edges == support_map_rect(*BASEWIN_RSP_PANEL_NATIVE, g), g
        l, t, r, b = edges
        assert l + (((r - l) - (r - l)) >> 1) == l          # flush-fill dst
        # the denser index the loop now picks still FITS the device window
        for half in (16, 32, 40, 64):
            idx = support_map_fit(r - l, b - t, half, half)
            tw, th = (800 + 50 * idx) >> 4, (400 + 25 * idx) >> 4
            if idx > -15:
                assert half * tw <= r - l and half * th <= b - t, (g, half)
    print("slice-9 arithmetic == scaling_laws.support_map_rect edges; fit-loop "
          "indices verified against support_map_fit (g 17..40)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
