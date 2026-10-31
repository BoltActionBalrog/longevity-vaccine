"""Assemble the console-rail / embedded-ScrollBar scaling thunks.

Group `rail_scrollbar_scale`.  Every thunk is a PORT of scaling_laws.py's
`rail_*` laws (swept in tests/test_scaling_laws.py); if a thunk disagrees with
the module, the thunk has the bug.

WHAT THE ENGINE DOES.  The ProdPicker's scrollbar is created HIDDEN by
ProdPicker_exec (init_inner @0x4949DE) and that rect is never shown.  The
visible widget is produced by the generic console-rail slide helper
`rail_slide_in(win, &sb)` @0x45DEA0 -- shared by Popup_show, the report screens
and the picker (call @0x492720).  The helper:

  1. computes yTop = min(y1+13, max(A,y1)), A = 238 (94 @800px)   [0x45E0A5]
  2. Buffer_init's a strip buffer bufA of 47 x (y2-yTop)          [0x45E22C]
  3. tiles the console_x art into it: top cap 32x26 at y=3, whole 34px mid
     tiles, bottom cap 32x25, and the 15px wall at x=32.  The rail height
     quantizes to esi = 51 + 34*floor((H-95)/34)                  [0x45E23E..]
  4. Buffer_draw_2's the strip into the window canvas at (clientW-47, yTop-y1)
     with num/den = 1/1                                           [0x45E4C1]
  5. resizes the scrollbar to (0x18, esi-10) and moves it to (clientW-0x2B,
     0x15), then shows it                                         [0x45E4C6]

THE DEFECT is that step 2 measures a DEVICE window while steps 3-5 are all
native art constants -- a full-device-height column of native-size tiles with a
native-width bar parked at a native inset.  Measured 4K/native rail-height ratio
1173/425 = 2.80, not 2.50; the bar hangs 8px BELOW the rail bottom cap.

THE FIX descales to native, lets vanilla's own quantization run there, and
rescales: synthesize the strip at NATIVE height (site C), keyed-ENLARGE it x
g/16 at the bake (site D -- Buffer_draw_2 already takes num/den), and scale the
tail constants through the same cascade (site E).  Sites A/B pin the strip
origin to bp(13) and switch off the two slide animations for the gated window
(they would paint the native-size strip straight to the screen and win over the
bake; vanilla itself skips both whenever the step count degenerates, which is
already what happens at 4K).  Everything is gated on
`[ebp+8] == ProdPicker && g > 16`, so every other rail user -- popups, report
screens, and every resolution at g<=16 -- runs the original bytes.

Cave: pcave2 0x10400 (ledger: "0x10362-0x10FFF free" after thunk_fe_pair_remap
v6).  ALLOCATED FROM THE LEDGER, not from an occupancy scan -- see
[[feedback-cave-ledger-lengths]] (the 4th escape crashed the 854fc1e8 build).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000

# --- sentinel placeholders (resolved by the yaml {abs32:} tokens) -----------
G = 0xDEADBE00                # g_popup_scale_num -> 0x668740
G_NETWIN = 0xDEADBE04         # g_netwin_active  -> pcave2+0x4800
G_SB_CUR = 0xDEADBE08         # g_sb_cur         -> pcave2+0x10630
G_FE_DST = 0xDEADBE0C         # g_fe_dst         -> pcave2+0x2FA0
G_FE_X = 0xDEADBE10           # g_fe_x           -> pcave2+0x2FA4
G_FE_Y = 0xDEADBE14           # g_fe_y           -> pcave2+0x2FA8
G_FE_SRC = 0xDEADBE18         # g_fe_src         -> pcave2+0x2FC4
G_FE_W = 0xDEADBE1C           # g_fe_w           -> pcave2+0x2FAC
G_FE_H = 0xDEADBE20           # g_fe_h           -> pcave2+0x2FB0
G_RM_FORCE = 0xDEADBE24       # g_rm_force       -> pcave2+0x44B0
G_RM_F0OVR = 0xDEADBE28       # g_rm_f0ovr       -> pcave2+0x10634
G_RAIL_SB = 0xDEADBE2C        # g_rail_sb        -> pcave2+0x11260 (v2 popup family)
G_RR_RET = 0xDEADBE30         # g_rail_ret       -> pcave2+0x11264 (bake v2 ret stash)
G_RR_DST = 0xDEADBE34         # g_rr_dst         -> pcave2+0x11268 (bake v2 post-pass rect)
G_RR_X = 0xDEADBE38           # g_rr_x           -> pcave2+0x1126C
G_RR_Y = 0xDEADBE3C           # g_rr_y           -> pcave2+0x11270
G_RR_W = 0xDEADBE40           # g_rr_w           -> pcave2+0x11274
G_RR_H = 0xDEADBE44           # g_rr_h           -> pcave2+0x11278
G_RAIL_GATE4 = 0xDEADBE48     # thunk_rail_gate4 -> pcave2+0x6A60 (v4 body; 0x11200 = trampoline)
G_POPUP_ACT = 0xDEADBE4C      # g_popup_active   -> pcave2+0x530
G_FILEDLG_ACT = 0xDEADBE50    # g_filedlg_active -> pcave2+0x23A0
SENT = {
    G: "{abs32:g_popup_scale_num}",
    G_NETWIN: "{abs32:g_netwin_active}",
    G_SB_CUR: "{abs32:g_sb_cur}",
    G_FE_DST: "{abs32:g_fe_dst}",
    G_FE_X: "{abs32:g_fe_x}",
    G_FE_Y: "{abs32:g_fe_y}",
    G_FE_SRC: "{abs32:g_fe_src}",
    G_FE_W: "{abs32:g_fe_w}",
    G_FE_H: "{abs32:g_fe_h}",
    G_RM_FORCE: "{abs32:g_rm_force}",
    G_RM_F0OVR: "{abs32:g_rm_f0ovr}",
    G_RAIL_SB: "{abs32:g_rail_sb}",
    G_RR_RET: "{abs32:g_rail_ret}",
    G_RR_DST: "{abs32:g_rr_dst}",
    G_RR_X: "{abs32:g_rr_x}",
    G_RR_Y: "{abs32:g_rr_y}",
    G_RR_W: "{abs32:g_rr_w}",
    G_RR_H: "{abs32:g_rr_h}",
    G_RAIL_GATE4: "{abs32:thunk_rail_gate4}",
    G_POPUP_ACT: "{abs32:g_popup_active}",
    G_FILEDLG_ACT: "{abs32:g_filedlg_active}",
}
REMAP_VA = PCAVE2 + 0x10000   # thunk_fe_pair_remap v7 (cave-internal, fixed)

PICKER = 0x6A8044             # ProdPicker = BaseWin_g + 0xA1C (the gate)
POPUP_SHOW = 0x404920         # Popup vtable slot +4 (Popup_show) = the popup-family key (v2)
FILEDLG_VTBL = 0x669EC8       # FileDlg vtable (LOAD/SAVE picker; bar at +0x3DD8) = the v4 family key
BUFFER_INIT = 0x5D7670        # Buffer_init(w,h,?,?)      thiscall, RET 0x10
BUFFER_DRAW_2 = 0x5D84C0      # keyed uniform-scale blit  thiscall, RET 0x18
WIN_MOVE = 0x5ED7D0           # Win_move(x,y)             thiscall, RET 0x08
RAIL_EBX_SRC = 0x669368       # the frame-clock fn ptr the helper caches in ebx

F_WINW = 0x4C4                # GraphicWin canvas width

# vanilla magnitudes — measured on the pristine .bak, never eyeballed
TOP_INSET = 13                # yTop - y1 at 1024 (and every non-4K capture)
STRIP_W = 47                  # bufA width: wall 15 + rail column 32
SB_W = 0x18                   # resize w
SB_Y = 0x15                   # move y
SB_XSUB = 0x2B                # move x = clientW - 0x2B

# --- cave layout (ledger-allocated free tail) -------------------------------
YTOP_OFF = 0x10400
HSTEP_OFF = 0x10440
BUFH_OFF = 0x10460
BAKE_OFF = 0x104A0
SBFIT_OFF = 0x104E0
ARROWFIT_OFF = 0x10560
SB_RESTRIPE_OFF = 0x105B0     # 2026-08-08 sb banding fix (120B, ends 0x10628; fix 7 clamped-dec head: 125B, ends 0x1062D)
G_SB_CUR_OFF = 0x10630        # + g_rm_f0ovr 0x10634, g_rm_f0 0x10638, g_rm_f0col 0x1063C
CAVE_END = 0x11000
# v2 (2026-08-14 popup-family rails): free tail past thunk_q16_fill_width v4 (ends 0x111DA)
RAIL_GATE_OFF = 0x11200       # thunk_rail_gate (CALL helper, returns ZF)
RAILOUT_HSTEP_OFF = 0x6B90    # thunk_railout_hstep v4 (rail_slide_out @0x45E7C3; RELOCATED from 0x11220 2026-09-26r)
RAILOUT_HSTEP_END = 0x6C00
RAILOUT_CAPW_OFF = 0xC790     # thunk_railout_capw (rail_slide_out @0x45E68C, 2026-09-26r)
RAILOUT_CAPW_END = 0xC800
STRIP_WALL_SPRITE_W = 0x7D0060  # [0x7D0060] = the r_outer wall sprite width (15)
RAIL_GATE4_OFF = 0x6A60       # v4 (2026-09-26p): thunk_rail_gate4 body (36B; the 0x11200 slot is 32B)
RAIL_SBARROWS_OFF = 0x6A90    # thunk_rail_sbarrows: btn_gate NO-exit extension ([g_rail_sb] arrows)
LIST_GATE_OFF = 0x6AC0        # thunk_list_gate (2026-09-26q): ZF=0 iff g_popup_active || g_filedlg_active
FD_WHEELBAR_OFF = 0x6AD8      # thunk_fd_wheelbar (2026-09-26q): the FileDlg's live list bar for the wheel
SB_VTBL = 0x669D58            # ScrollBar vtable
RAIL_V4_END = 0x6B00
G_RAIL_SB_OFF = 0x11260       # g_rail_sb dword (the fitted popup/picker sb, 0 = none)
G_RR_OFF = 0x11264            # 6 dwords: g_rail_ret, g_rr_dst/x/y/w/h (bake v2 scratch)
BAKE2_OFF = 0x11280           # thunk_rail_bake v2 (RELOCATED from 0x104A0: + channel restripe)
BAKE2_END = 0x11400
CHANNEL_MARK = 0xFD           # scratch index (palette 253 = pure magenta, the pcx key colour;
                              # never console art) marking 0x41/0xC5 in the native strip
CHANNEL_TOP = 0xC5            # C5 on top rows / 0x41 below == fe's C5/41 gutter family
CHANNEL_BOT = 0x41
RAIL_GATE_VA = PCAVE2 + RAIL_GATE_OFF
# 2026-10-17 fix sbstrip: the strip x helpers (law rail_strip_x), pcave2 0x103B0..0x103FC = the free gap between
# thunk_fe_pair_remap (ends 0x103AA) and g_rm_yph @0x103FC (cave_map.py --at 0x103B0: FREE)
RAIL_D_OFF = 0x103B0          # thunk_rail_d:  eax = cw -> eax = cw - fl(47g/16) - rail_strip_x(cw, g)
RAIL_SX_OFF = 0x103D0         # thunk_rail_sx: eax = cw -> eax = rail_strip_x(cw, g)
RAIL_SX_END = 0x103FC         # g_rm_yph
RAIL_SX_VA = PCAVE2 + RAIL_SX_OFF
RAIL_D_VA = PCAVE2 + RAIL_D_OFF
REPORTWIN = 0x876478         # ReportWin static (v3: its list bar RW+0xC10C rides the console-rail assembly)
# 2026-10-17 fix rail2 (laws rail_nn_col / rail_wall_off / rail_layout v3 / rail_out_tail v3): the engine's NN puts
# strip column k at rail_nn_col(k, g) (its run table), not k*g/16 -- the bake draws the rail column through the engine
# and the WALL through thunk_sprite_scale_nn (= slide_show's outer rail), the roll-up shift and the bar follow the
# engine's columns.  Slots ALLOCATED FROM THE LEDGER + cave_map.py --at (retired zero slots / ledger-free tail):
NNCOL_OFF = 0x104A0           # thunk_rail_nncol  (the retired bake v1 slot 0x104A0..0x104DF, zeros)
NNCOL_END = 0x104E0           # thunk_rail_sbfit
MARK_OFF = 0x11208            # thunk_rail_mark   (the retired gate v3 tail 0x11206..0x11215 + railout_hstep v3
MARK_END = 0x11260            #  slot 0x11220..0x1125F, zeros; every gate caller lands on the 6-B trampoline) .. g_rail_sb
WALL_OFF = 0xC3D0             # thunk_rail_wall   (the vacated fe_pair_remap v5 slot tail, after thunk_pf_union_align
WALLOFF_OFF = 0xC448          #  0xC1C0..0xC3CA) + thunk_rail_walloff, flush against thunk_filedlg_railscale 0xC470
WALL_END = WALLOFF_OFF
WALLOFF_END = 0xC470
G_RR_SRC_OFF = 0x103B0        # g_rr_src: the bake's native strip Buffer* (the retired thunk_rail_d slot 0x103B0..)
G_RR_SRC = 0xDEADBE54         # g_rr_src -> pcave2+0x103B0
SENT[G_RR_SRC] = "{abs32:g_rr_src}"
NNCOL_VA = PCAVE2 + NNCOL_OFF
MARK_VA = PCAVE2 + MARK_OFF
WALL_VA = PCAVE2 + WALL_OFF
WALLOFF_VA = PCAVE2 + WALLOFF_OFF
SCALE_NN_VA = PCAVE2 + 0x2150  # thunk_sprite_scale_nn v2 (origin not rescaled; clips to the dest's w / h)
SPR_R_OUTER = 0x7D0048        # g_rail_sprite_r_outer (15 x 529; its key byte at +8 = 0x7D0050)
RAIL_COL_W = 32               # strip columns 0..31 = the rail column; 32..46 = the r_outer wall
RAIL_KEY = 9                  # bufA's fill / the bake's blit key (vanilla `push 9` at 0x45E231 / 0x45E4B8)
# W3B (2026-10-25, the rail scrollbar rework; src assemble_rail_sym.py, W3B region pcave2 0x39000..0x3AFFF):
RSB_BLIT_VA = PCAVE2 + 0x39200  # t_rsb_blit: the column blit (Buffer_draw_2 drop-in, RET 0x18) the bake now CALLs
RSB_BAR_VA = PCAVE2 + 0x39400   # t_rsb_bar:  eax = cw -> eax = S + b, ecx = Wc - 2b (sbfit v5)

GATE = f"""
        call {RAIL_GATE_VA}
        jne  vanilla
        cmp  dword ptr [{G}], 0x10
        jle  vanilla
"""


def asm_rail_sx():
    """thunk_rail_sx (2026-10-17, fix sbstrip) -- CALL helper: eax = cw (the window canvas width, device) ->
    eax = rail_strip_x(cw, g) = fl((fl(cw*16/g) - 0x37)*g/16) + fl(8g/16): the OUTER right slide rail's x, the
    exact arithmetic thunk_filedlg_railscale v3 runs for that strip (cdq/div on the non-negative cw*16, sar
    floors).  The identity cw - 47 at g = 16; callers only reach it at g > 16.  Preserves every register but eax;
    flags clobbered."""
    return f"""
        push ecx
        push edx
        mov  ecx, dword ptr [{G}]
        shl  eax, 4
        xor  edx, edx
        div  ecx
        sub  eax, 0x37
        imul eax, ecx
        sar  eax, 4
        shl  ecx, 3
        sar  ecx, 4
        add  eax, ecx
        pop  edx
        pop  ecx
        ret
    """


def asm_rail_nncol():
    """thunk_rail_nncol (2026-10-17, fix rail2) -- CALL helper: eax = k >= 0 -> eax = rail_nn_col(k, g), the sum of
    the first k dest runs of the engine's own NN table at g/16 (port of Sprite_fill_scaling_table 0x5EB20F, law
    engine_scale_runs): q = g >> 4, r = g & 15, err = r - 32 (+ g when q is odd); per column err += 2r, run = q,
    + 1 and err -= 32 when err > 0.  Computed from g alone -- never read from g_sprite_scale_runs, whose contents
    belong to whichever ratio the engine drew last.  Valid for g >= 16 (callers: g > 16).  Preserves every register
    but eax; flags clobbered."""
    return f"""
        push ebx
        push ecx
        push edx
        push esi
        mov  ecx, eax
        mov  edx, dword ptr [{G}]
        mov  ebx, edx
        sar  ebx, 4
        and  edx, 0xF
        lea  esi, [edx - 0x20]
        test bl, 1
        je   even
        add  esi, dword ptr [{G}]
    even:
        add  edx, edx
        xor  eax, eax
        test ecx, ecx
        jle  done
    col:
        add  esi, edx
        add  eax, ebx
        test esi, esi
        jle  nxt
        inc  eax
        sub  esi, 0x20
    nxt:
        dec  ecx
        jne  col
    done:
        pop  esi
        pop  edx
        pop  ecx
        pop  ebx
        ret
    """


def asm_rail_walloff():
    """thunk_rail_walloff (2026-10-17, fix rail2) -- CALL helper: eax = cw (the window canvas width) -> eax =
    rail_wall_off(cw, g) = min(rail_nn_col(32), cw - rail_strip_x(cw) - fl(15g/16)): the wall's offset from the strip
    x in the bake, and the slide-out's roll-up shift.  g > 16 only.  Preserves every register but eax; flags
    clobbered."""
    return f"""
        push ecx
        mov  ecx, eax
        call {RAIL_SX_VA}
        sub  ecx, eax
        imul eax, dword ptr [{G}], 15
        sar  eax, 4
        sub  ecx, eax
        push {RAIL_COL_W}
        pop  eax
        call {NNCOL_VA}
        cmp  eax, ecx
        jle  done
        mov  eax, ecx
    done:
        pop  ecx
        ret
    """


def asm_rail_mark():
    """thunk_rail_mark (2026-10-17, fix rail2) -- the bake's pass 1, moved out of thunk_rail_bake (v4) and extended.
    CALL helper, ecx = bufA (the NATIVE 47-wide strip, rail_slide_in's [ebp-0x5DC]); pushad-preserving.
      * stash bufA in g_rr_src (thunk_rail_wall reads its native height after the blit, which clobbers ecx);
      * columns 0..31 (the rail column): every 0x41/0xC5 channel-dither pixel -> CHANNEL_MARK 0xFD (unchanged, v2);
      * columns 32..46 (the r_outer wall, drawn into bufA 1:1 by vanilla at 0x45E32D) -> key 9: the engine blit then
        draws ONLY the rail column, and thunk_rail_wall draws the wall through thunk_sprite_scale_nn -- the engine
        NN would put it at rail_nn_col(32) with its own column samples, the outer rail sits at slide_show's.
    Row loop: ecx counts down from w, so pixel x = w - ecx; x >= 32 <=> ecx <= w - 32 (ebp)."""
    return f"""
        pushad
        mov  dword ptr [{G_RR_SRC}], ecx
        mov  esi, dword ptr [ecx + 0x54]
        mov  ebx, dword ptr [ecx + 0x4A8]
        mov  edi, dword ptr [ecx + 0x80]
        mov  edx, dword ptr [ecx + 0x84]
        neg  edx
        lea  ebp, [edi - {RAIL_COL_W}]
        test edi, edi
        jle  m_done
        test edx, edx
        jle  m_done
    m_row:
        mov  ecx, edi
        mov  eax, esi
    m_px:
        cmp  ecx, ebp
        jg   m_art
        mov  byte ptr [eax], {RAIL_KEY}
        jmp  m_next
    m_art:
        cmp  byte ptr [eax], {CHANNEL_BOT}
        je   m_set
        cmp  byte ptr [eax], {CHANNEL_TOP}
        jne  m_next
    m_set:
        mov  byte ptr [eax], {CHANNEL_MARK}
    m_next:
        inc  eax
        dec  ecx
        jnz  m_px
        add  esi, ebx
        dec  edx
        jnz  m_row
    m_done:
        popad
        ret
    """


def asm_rail_wall():
    """thunk_rail_wall (2026-10-17, fix rail2) -- the bake's last step: the strip's WALL, drawn as r_outer
    (0x7D0048) through thunk_sprite_scale_nn at (S + rail_wall_off(cw), Y), num/den = g/16 -- the same sprite, scaler,
    width fl(15g/16) and column samples as slide_show's outer right rail (railscale v3), so the slide-out's rolled-up
    wall IS the closed outer rail.  Rows: vanilla's strip carries the wall over its whole height (r_outer drawn 1:1
    at bufA y 0, clipped to bufA); here the dest Buffer's height field (NEGATIVE, top-down) is set to
    -min(Y + fl(hn*g/16), bufH) for the call -- the engine strip's own rows (fl(h*g/16), measured) -- and restored.
    scale_nn clips columns to the canvas width (no write past it).  CALL helper from thunk_rail_bake's gated tail:
    [g_rr_dst] = canvas, [g_rr_x] = S, [g_rr_y] = Y, [g_rr_src] = bufA (thunk_rail_mark).  pushad-preserving; ebx /
    ebp survive scale_nn (callee-saved)."""
    return f"""
        pushad
        mov  ebx, dword ptr [{G_RR_DST}]
        mov  ecx, dword ptr [{G_RR_SRC}]
        mov  eax, dword ptr [ecx + 0x84]
        neg  eax
        imul eax, dword ptr [{G}]
        sar  eax, 4
        add  eax, dword ptr [{G_RR_Y}]
        mov  ebp, dword ptr [ebx + 0x84]
        mov  edx, ebp
        neg  edx
        cmp  eax, edx
        jle  h_ok
        mov  eax, edx
    h_ok:
        neg  eax
        mov  dword ptr [ebx + 0x84], eax
        mov  eax, dword ptr [ebx + 0x80]
        call {WALLOFF_VA}
        add  eax, dword ptr [{G_RR_X}]
        push 0x10
        push dword ptr [{G}]
        push dword ptr [{G_RR_Y}]
        push eax
        movzx eax, byte ptr [{SPR_R_OUTER + 8}]
        push eax
        push ebx
        mov  ecx, {SPR_R_OUTER}
        call {SCALE_NN_VA}
        mov  dword ptr [ebx + 0x84], ebp
        popad
        ret
    """


def asm_rail_d():
    """RETIRED 2026-10-17 (fix rail2: the bar is seated from the engine's columns, rail_nn_col; the slot now holds
    g_rr_src).  Kept for the byte record.
    thunk_rail_d (2026-10-17, fix sbstrip) -- CALL helper: eax = cw -> eax = d = cw - fl(47g/16) -
    rail_strip_x(cw, g) >= 0, how far the strip sits left of the plain cw - bp(47) (0 at g = 16, 0..4 above).
    sbfit subtracts it from the bar x (the bar keeps its bp(47) - bp(0x2B) offset inside the strip).  Preserves
    every register but eax; flags clobbered."""
    return f"""
        push eax
        call {RAIL_SX_VA}
        neg  eax
        add  eax, dword ptr [esp]
        push ecx
        mov  ecx, dword ptr [{G}]
        imul ecx, ecx, {STRIP_W}
        sar  ecx, 4
        sub  eax, ecx
        pop  ecx
        add  esp, 4
        ret
    """


def asm_rail_gate():
    """thunk_rail_gate v4 TRAMPOLINE at the old 0x11200 entry (6B).

    Every rail thunk reaches the gate by a literal cave-internal `call 0x...11200`
    (the GATE macro), so the entry stays put and forwards to the v4 body -- wrap,
    don't relocate a shared helper.  push/ret keeps the caller's return address on
    top, so the body's `ret` returns straight to the rail thunk."""
    return f"""
        push {G_RAIL_GATE4}
        ret
    """


def asm_rail_gate4():
    """thunk_rail_gate4 (v4, 2026-09-26p: + the FileDlg family) -- the shared window-family test.

    CALL helper (via the 0x11200 trampoline); returns ZF=1 iff [ebp+8] (the rail
    helper's `win` arg) is the ProdPicker static, the ReportWin static (v3), a
    FileDlg (vtable 0x669EC8: the in-game LOAD/SAVE picker -- FileDlg_show 0x407BE0
    and its sb-create 0x407E80 call rail_slide_in(this, this+0x3DD8) exactly like
    Popup_show; v1..v3 left its bar native-thin and parked at native offsets) OR a
    Popup-family object ([vtbl+4] == Popup_show 0x404920: exactly the four Popup
    vtables 0x6695C8 / 0x66A8A8 / 0x66CB60 / 0x66DD84).  Report screens etc. ->
    ZF=0 -> vanilla.  Preserves every register (eax via push/pop); flags are the
    return value.  ebp = rail_slide_in's frame at all five sites."""
    return f"""
        push eax
        mov  eax, dword ptr [ebp + 8]
        cmp  eax, {PICKER}
        je   done
        cmp  eax, {REPORTWIN}
        je   done
        mov  eax, dword ptr [eax]
        cmp  eax, {FILEDLG_VTBL}
        je   done
        cmp  dword ptr [eax + 4], {POPUP_SHOW}
    done:
        pop  eax
        ret
    """


def asm_rail_sbarrows():
    """thunk_rail_sbarrows (2026-09-26p) -- thunk_btn_gate's NO exit, extended.

    btn_gate's last instruction pair (`xor eax,eax / ret`) becomes `push this / ret`.
    esi = the FlatButton; returns eax = 1 iff esi is one of the two arrows of the
    rail-fitted bar [g_rail_sb] (+0xAAC up / +0x15F8 down), else 0 -- the old NO.
    Why: the FileDlg bar's arrows repaint on HOVER outside the sbzoom bracket;
    btn_gate admits file-dialog buttons only when they carry a label (+0xA7C), so
    the unlabeled arrows would redraw their native state sprite.  Popups never
    needed this (g_popup_active admits their arrows); the picker / report bars
    are admitted by statics earlier, so this changes nothing for them.
    g_rail_sb is cleared by railout_hstep on the bar's hide and by the FileDlg
    slide_hide disarm.  Clobbers eax + flags only (btn_gate's contract)."""
    return f"""
        mov  eax, dword ptr [{G_RAIL_SB}]
        test eax, eax
        je   no
        add  eax, 0xAAC
        cmp  esi, eax
        je   yes
        add  eax, 0xB4C
        cmp  esi, eax
        je   yes
    no:
        xor  eax, eax
        ret
    yes:
        mov  eax, 1
        ret
    """


def asm_list_gate():
    """thunk_list_gate (2026-09-26q) -- CALL helper, returns ZF=0 iff g_popup_active != 0 OR
    g_filedlg_active != 0 (ZF=1: neither).  Replaces the `cmp [g_popup_active],0` test in
    thunk_lbres_* / thunk_dw_sbv (assemble_dw.py) so the popup heap-bar lever family also
    serves the LOAD/SAVE list: the main-menu picker (list flags 0x80020, no rail style 0x40)
    builds the same heap V bar as a popup (ScrollBar_init_v, x = w - g_scrollbar_w) with
    g_popup_active == 0.  Preserves every register; flags are the result."""
    return f"""
        cmp  dword ptr [{G_POPUP_ACT}], 0
        jne  done
        cmp  dword ptr [{G_FILEDLG_ACT}], 0
    done:
        ret
    """


def asm_fd_wheelbar():
    """thunk_fd_wheelbar (2026-09-26q) -- called by thunk_wheel_down/up (assemble_dw.py) for a
    FileDlg modal top (esi = FileDlg).  Returns edi = the list bar the wheel should press:
    the in-game RAIL bar FileDlg+0x3DD8 when it is live (parent +0xC4 != 0), else the list
    window's heap V bar [FileDlg+0x3704] (= ListBox FileDlg+0x3280, window part +0x48,
    scroll_vert +0x43C; the main-menu picker) when it is a ScrollBar, else +0x3DD8 again
    (the caller's parent test then passes the key through, as before).  v1 always took
    +0x3DD8: at the main menu the wheel fell through to the list's arrow keys and moved
    the SELECTION instead of scrolling.  Clobbers ecx only (the caller reloads it)."""
    return f"""
        lea  edi, [esi + 0x3DD8]
        cmp  dword ptr [edi + 0xC4], 0
        jne  done
        mov  ecx, dword ptr [esi + 0x3704]
        test ecx, ecx
        je   done
        cmp  dword ptr [ecx], {SB_VTBL}
        jne  done
        mov  edi, ecx
    done:
        ret
    """


def asm_railout_hstep():
    """rail_slide_out @0x45E7C3 (6B: `and ecx,0xFFFFFFFC` + `add ecx,8`) -- v4 (2026-09-26r).

    For the gated family at g>16: zero the horizontal roll-up FRAMES (the roll-up
    slides a capture over the enlarged strip = a visible tear), clear g_rail_sb,
    AND -- v4 -- apply the roll-up's net x shift when vanilla would have rolled
    (anim pref ebx=[0x9A6494]&0x80000 and not MP edx=[0x93F660]==0): esi -= 2g
    (= fl(32g/16), law rail_out_tail).  esi = the capture's screen L here; the
    tail re-blits the capture at esi (0x45EB01) clipped to the strip, so the
    scaled WALL alone survives, like vanilla's -32.  v3 left the shift at 0: an
    open window (the in-game LOAD/SAVE picker entering a folder that fits) kept
    the whole rail strip.  Family test on edi (= win; [ebp+8] is clobbered at
    0x45E796).  eax LIVE across the site -> push/pop; flags dead after.
    v5 (2026-10-17, fix rail2): the shift is rail_wall_off(cw) (thunk_rail_walloff,
    cw = [edi+0x4C4]) -- where the bake drew the wall, the engine's column 32
    (2g + 1 at g = 25..31 / 48), not 2g: v4 left a 1-px seam between the inner and
    outer right rails after the bar slid away (law rail_out_tail v3)."""
    return f"""
        and  ecx, 0xFFFFFFFC
        add  ecx, 8
        push eax
        cmp  edi, {PICKER}
        je   fam
        mov  eax, dword ptr [edi]
        cmp  eax, {FILEDLG_VTBL}
        je   fam
        cmp  dword ptr [eax + 4], {POPUP_SHOW}
        jne  done
    fam:
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  done
        test ebx, 0x80000
        je   still
        test edx, edx
        jne  still
        mov  eax, dword ptr [edi + {F_WINW}]
        call {WALLOFF_VA}
        sub  esi, eax
    still:
        xor  ecx, ecx
        mov  dword ptr [{G_RAIL_SB}], 0
    done:
        pop  eax
        ret
    """


def asm_railout_capw():
    """rail_slide_out @0x45E68C (6B: `mov edx,[0x7D0060]`) -- call-helper (2026-09-26r).

    The capture/clear column is L = R - [0x7D0060] - 0x20 = R - 47 NATIVE; the
    gated strip at g>16 is bp(47) wide, so its left part was neither captured,
    cleared nor re-blitted.  For the family at g>16 return edx = bp(47) - 0x20 so
    L = R - bp(47) (law rail_out_tail; = rail_layout bake_x).  edi = win.  ecx
    (= R) preserved; eax preserved; flags dead (the caller's `sub` follows).
    v2 (2026-10-17, fix sbstrip): edx = cw - rail_strip_x(cw, g) - 0x20 (cw = [edi+0x4C4], thunk_rail_sx), so
    L = R - cw + rail_strip_x = the bake x (law rail_out_tail v2 with win_w): the capture runs from the strip's
    left edge to the window edge, and the -2g roll-up shift lands the wall exactly on the outer right rail."""
    return f"""
        mov  edx, dword ptr [{STRIP_WALL_SPRITE_W}]
        push eax
        cmp  edi, {PICKER}
        je   fam
        mov  eax, dword ptr [edi]
        cmp  eax, {FILEDLG_VTBL}
        je   fam
        cmp  dword ptr [eax + 4], {POPUP_SHOW}
        jne  done
    fam:
        cmp  dword ptr [{G}], 0x10
        jle  done
        mov  eax, dword ptr [edi + {F_WINW}]
        mov  edx, eax
        call {RAIL_SX_VA}
        sub  edx, eax
        sub  edx, 0x20
    done:
        pop  eax
        ret
    """


def asm_ytop():
    """Site A @0x45E0B7 (8B: `mov eax,edi` + `mov ebx,[0x669368]`).

    Pins the strip origin to the native inset scaled, yTop = y1 + bp(13),
    instead of vanilla's mixed-space min(y1+13, max(238,y1)) -- which silently
    drops to 0 once the window happens to sit below y=238 on a big screen (the
    4K capture) and would leave the bar's top/bottom margins asymmetric.
    Setting eax = ecx also makes the caller's `sub eax,ecx` yield 0, so
    g_rail_vstep = 0 and the vertical slide animation takes vanilla's own
    degenerate path (`jle 0x45E215`) -- see the module docstring.
    Live across the site: ecx (yTop), esi (step), edi (max(A,y1)), ebp frame.
    edx is dead (cdq at 0x45E0C4); flags are dead (`sub` at 0x45E0BF)."""
    return f"""
        mov  eax, edi
        mov  ebx, dword ptr [{RAIL_EBX_SRC}]
        {GATE}
        mov  edx, dword ptr [{G}]
        imul edx, edx, {TOP_INSET}
        sar  edx, 4
        add  edx, dword ptr [ebp - 0x18]
        mov  ecx, edx
        mov  eax, edx
    vanilla:
        ret
    """


def asm_hstep():
    """Site B @0x45E351 (6B: `and ecx,0xFFFFFFFC` + `add ecx,8`).

    Zeroes the horizontal unroll's frame count for the gated window, so the
    caller's `test ecx,ecx / jle 0x45E472` takes the no-animation path -- which
    still restores the screen clip and falls through to the bake.  Without this
    the last animation frame blits the NATIVE strip straight to the screen and
    is what the player sees.  eax/edx (the MP flag copies) and edi are live."""
    return f"""
        and  ecx, 0xFFFFFFFC
        add  ecx, 8
        {GATE}
        xor  ecx, ecx
    vanilla:
        ret
    """


def asm_bufh():
    """Site C @0x45E22C (Buffer_init call-target redirect).

    h := ceil(h*16/g) -- the floor-descale round-trip law -- so the art
    quantization at 0x45E23E runs on a NATIVE-sized buffer with native tiles,
    exactly as it does at 1024.  [law rail_strip_src_h]
    Stack: [esp]=ret, +4=w, +8=h, +0xC/+0x10 = 0.  ecx = &bufA (preserved)."""
    return f"""
        {GATE}
        push eax
        push edx
        mov  eax, dword ptr [esp + 0x10]
        shl  eax, 4
        add  eax, dword ptr [{G}]
        dec  eax
        xor  edx, edx
        div  dword ptr [{G}]
        mov  dword ptr [esp + 0x10], eax
        pop  edx
        pop  eax
    vanilla:
        jmp  {BUFFER_INIT}
    """


def asm_bake_v1():
    """RETIRED 2026-08-15 (superseded by asm_bake2 at 0x11280; kept for the byte record).
    Site D @0x45E4C1 (Buffer_draw_2 call-target redirect).

    Enlarges the native strip into the window canvas: num/den := g/16 and the
    destination x moves from clientW-47 to clientW-bp(47).  y is already
    bp(13) because site A set yTop.  [law rail_layout bake_x/blit_num]
    Stack: [esp]=ret, +4=dest, +8=key, +0xC=X, +0x10=Y, +0x14=num, +0x18=den."""
    return f"""
        {GATE}
        mov  eax, dword ptr [{G}]
        mov  dword ptr [esp + 0x14], eax
        mov  dword ptr [esp + 0x18], 0x10
        push edx
        imul edx, eax, {STRIP_W}
        sar  edx, 4
        sub  edx, {STRIP_W}
        sub  dword ptr [esp + 0x10], edx
        pop  edx
    vanilla:
        jmp  {BUFFER_DRAW_2}
    """


def asm_bake2():
    """thunk_rail_bake v2 (2026-08-15, RELOCATED 0x104A0 -> 0x11280): v1 + the
    channel restripe.  The whole console_x rail column art is a 1px ROW dither
    0x41/0xC5 (console_x.pcx rows 279..400: k/c alternate on every row, teal AE
    lines and cap bevels overlaid); NN-enlarging it x g/16 bands at fractional g
    (1920x1080 shot 20260815-010148, g=22: 1,2,1,1,2 runs in the channel).
    [[feedback-dither-no-resample-on-upscale]] -> regenerate at device density:
      pass 1  mark every 0x41/0xC5 of the NATIVE strip bufA (ecx) as CHANNEL_MARK
              (0xFD, never art) -- so pass 2 needs no geometry model of the blit;
      blit    Buffer_draw_2 exactly as v1 (num/den = g/16, x = clientW-bp(47));
              v3 (2026-10-17, fix sbstrip): x = rail_strip_x(cw, g) via thunk_rail_sx
              (cw = [dest+0x80]) -- the outer right slide rail's own x, 0..4 px left of
              clientW-bp(47) (law rail_layout v2 bake_x);
      pass 2  over the dest rect (X,Y, fl(47g/16)+1, fl(h*g/16)+1 clipped to the
              canvas; over-cover is safe: only 0xFD is touched) rewrite the mark
              to C5 on stripe-top rows / 0x41 below (law rail_channel_pixel, the
              same phase grid + C5/41 duty as fe's gutter family; y = dest row).
    v4 (2026-10-17, fix rail2): pass 1 moved to thunk_rail_mark (+ it keys out the
    wall columns 32..46 and stashes bufA in g_rr_src), so the engine blit draws the
    rail column alone (rail_nn_col(32) wide); after pass 2, thunk_rail_wall draws
    the wall as r_outer through thunk_sprite_scale_nn at S + rail_wall_off -- the
    outer rail's own pixels (law rail_layout v3 wall_x).  In place, shorter.
    v5 (2026-10-25, W3B): the strip blit is t_rsb_blit (assemble_rail_sym.py) instead of the engine Buffer_draw_2 --
    same args and callee-clean contract; the rail column's COLUMNS follow rail_col_map (one symmetric map: K-wide
    lines, mirrored outer offsets) and its rows stay the engine's own (rail_blit_rows).  Same size, one rel32.
    Ret addr is popped into g_rail_ret so the callee-clean (RET 0x18) blit can be
    CALLed with the args in place; the thunk exits by jmp [g_rail_ret] with the
    args consumed exactly as the vanilla call would.  Vanilla path unchanged."""
    return f"""
        {GATE}
        mov  eax, dword ptr [{G}]
        mov  dword ptr [esp + 0x14], eax
        mov  dword ptr [esp + 0x18], 0x10
        mov  eax, dword ptr [esp + 4]
        mov  eax, dword ptr [eax + 0x80]
        call {RAIL_SX_VA}
        mov  dword ptr [esp + 0x0C], eax
        call {MARK_VA}
        pop  eax
        mov  dword ptr [{G_RR_RET}], eax
        mov  eax, dword ptr [esp]
        mov  dword ptr [{G_RR_DST}], eax
        mov  eax, dword ptr [esp + 8]
        mov  dword ptr [{G_RR_X}], eax
        mov  eax, dword ptr [esp + 0x0C]
        mov  dword ptr [{G_RR_Y}], eax
        mov  eax, dword ptr [ecx + 0x80]
        imul eax, dword ptr [{G}]
        sar  eax, 4
        inc  eax
        mov  dword ptr [{G_RR_W}], eax
        mov  eax, dword ptr [ecx + 0x84]
        neg  eax
        imul eax, dword ptr [{G}]
        sar  eax, 4
        inc  eax
        mov  dword ptr [{G_RR_H}], eax
        call {RSB_BLIT_VA}
        pushad
        mov  ebx, dword ptr [{G_RR_DST}]
        mov  ebp, dword ptr [ebx + 0x4A8]
        mov  esi, dword ptr [ebx + 0x54]
        mov  eax, dword ptr [{G_RR_X}]
        mov  ecx, dword ptr [{G_RR_W}]
        add  ecx, eax
        cmp  ecx, dword ptr [ebx + 0x80]
        jle  p_wok
        mov  ecx, dword ptr [ebx + 0x80]
    p_wok:
        sub  ecx, eax
        jle  p_done
        mov  dword ptr [{G_RR_W}], ecx
        mov  edi, dword ptr [{G_RR_Y}]
        mov  edx, dword ptr [{G_RR_H}]
        add  edx, edi
        mov  ecx, dword ptr [ebx + 0x84]
        neg  ecx
        cmp  edx, ecx
        jle  p_hok
        mov  edx, ecx
    p_hok:
        mov  dword ptr [{G_RR_H}], edx
        cmp  edi, edx
        jge  p_done
        add  esi, eax
        mov  eax, edi
        imul eax, ebp
        add  esi, eax
        mov  ebx, dword ptr [{G}]
        mov ebx, dword ptr [0x66879c]
    p_row:
        mov  eax, edi
        xor  edx, edx
        div  ebx
        lea  eax, [ebx + 1]
        shr  eax, 1
        cmp  edx, eax
        mov  dl, {CHANNEL_TOP}
        jb   p_col
        mov  dl, {CHANNEL_BOT}
    p_col:
        mov  ecx, dword ptr [{G_RR_W}]
        mov  eax, esi
    p_px:
        cmp  byte ptr [eax], {CHANNEL_MARK}
        jne  p_next
        mov  byte ptr [eax], dl
    p_next:
        inc  eax
        dec  ecx
        jnz  p_px
        add  esi, ebp
        inc  edi
        cmp  edi, dword ptr [{G_RR_H}]
        jl   p_row
    p_done:
        popad
        call {WALL_VA}
        jmp  dword ptr [{G_RR_RET}]
    vanilla:
        jmp  {BUFFER_DRAW_2}
    """


def asm_sbfit():
    """Site E @0x45E4C6 (37B: the whole resize + Win_move tail).

    sb = (clientW - bp(0x2B), bp(0x15), bp(0x18), fl((railH-10)*g/16)) --
    the bar seated in the enlarged rail with vanilla's 5px/4px margins scaled.
    v3 (2026-10-17, fix sbstrip): x -= thunk_rail_d(clientW) = clientW - bp(47) -
    rail_strip_x, i.e. sb_x = rail_strip_x + bp(47) - bp(0x2B): the bar moves with
    the strip and keeps its offset inside it (law rail_layout v2 sb_x).
    v4 (2026-10-17, fix rail2): sb_x = S + rail_nn_col(4), sb_w = rail_nn_col(28) -
    rail_nn_col(4) (thunk_rail_sx + thunk_rail_nncol): the bar sits exactly between
    the column's cyan guide lines (native cols 3 / 28) where the ENGINE drew them
    (law rail_layout v3); thunk_rail_d retired.
    v5 (2026-10-25, W3B): sb_x = S + b, sb_w = Wc - 2b via t_rsb_bar (b = cum(4, Wc, 32), Wc = rail_wall_off): the
    bar is the channel between the two symmetric K-wide lines of rail_col_map (law rail_layout v4).  Shorter.
    [law rail_layout sb_x/sb_y/sb_w/sb_h]
    In: ebx = win, esi = railH (native), [ebp+0xC] = &sb.  Out: edi = &sb for
    the caller's show at 0x45E4EB.  Both callees are callee-clean."""
    return f"""
        mov  edi, dword ptr [ebp + 0x0C]
        add  esi, -0x0A
        push ebx
        mov  ebx, dword ptr [ebx + {F_WINW}]
        mov  eax, {SB_W}
        mov  edx, {SB_Y}
        {GATE}
        mov  dword ptr [{G_RAIL_SB}], edi
        mov  eax, ebx
        call {RSB_BAR_VA}
        mov  ebx, eax
        mov  eax, ecx
        mov  ecx, dword ptr [{G}]
        imul esi, ecx
        sar  esi, 4
        imul edx, ecx
        sar  edx, 4
        jmp  seat
    vanilla:
        sub  ebx, {SB_XSUB}
    seat:
        push ebx
        push edx
        push 0
        push esi
        push eax
        mov  eax, dword ptr [edi]
        mov  ecx, edi
        call dword ptr [eax + 0x0C]
        pop  edx
        pop  eax
        push edx
        push eax
        mov  ecx, edi
        call {WIN_MOVE}
        pop  ebx
        ret
    """


def asm_arrowfit():
    """ScrollBar_on_resize 0x606860, BOTH arms (0x6068DB 26B / 0x606935 30B).

    Vanilla re-derives b = min(w,h) and then resizes ONLY the down arrow
    (+0x15F8); the up arrow (+0xAAC) is never touched at either arm.  Latent
    forever, because b only moves when the bar's SHORT axis changes and vanilla
    only grows scrollbars along their long axis -- widening the picker's bar
    24 -> bp(24) is the first thing in the game that does it.  The up arrow's
    window then stays 24x24 at the client origin, so FlatButton_content_draw
    centres the zoomed chevron against the stale W and clips it to the stale
    buffer: a smaller, offset ghost chevron on top of the real one, and a
    24x24 hit rect in the corner instead of one under the drawn arrow.
    [law scrollbar_arrow_square]

    ONE thunk serves both arms: it re-derives the -2 border inset from
    [esi+0xA1C] itself, exactly as the two arms differ.  The up-arrow resize is
    SELF-GATED on the size actually differing, so for every other scrollbar in
    the game -- and for the picker at g<=16, where bp(24) == 24 -- this emits
    no call at all and the function behaves bit-identically to vanilla.  No
    Win_move: the up arrow's origin is (0,0)/(1,1) at every size.

    In:  esi = Scroll, ecx = 0.   Out: ebp = esi+0x15F8 (the caller's Win_move
    uses it), down arrow resized exactly as vanilla.  ebx/esi/edi preserved;
    eax/ecx/edx/ebp are dead across both sites (eax is recomputed at 0x6068FD
    / 0x60695E, ecx at 0x6068FD, edx at 0x60695E).

    NB: no inline `;` comments in the asm text -- keystone's parser hangs on
    them (cost one 120s timeout).  The commentary lives in this docstring:
      b        <- [esi+0xA60], minus 2 when [esi+0xA1C] != -1 (the bordered arm)
      up arrow <- [esi+0xAAC], resized only when [ebp+0x4C4] already differs
      dn arrow <- [esi+0x15F8], resized exactly as vanilla, ebp left pointing at it
    """
    return """
        mov  eax, dword ptr [esi + 0xA60]
        cmp  dword ptr [esi + 0xA1C], -1
        je   sized
        add  eax, -2
    sized:
        lea  ebp, [esi + 0xAAC]
        cmp  dword ptr [ebp + 0x4C4], eax
        je   down
        push eax
        push 0
        push eax
        push eax
        mov  edx, dword ptr [ebp]
        mov  ecx, ebp
        call dword ptr [edx + 0x0C]
        pop  eax
    down:
        mov  edx, dword ptr [esi + 0x15F8]
        lea  ebp, [esi + 0x15F8]
        push 0
        push eax
        push eax
        mov  ecx, ebp
        call dword ptr [edx + 0x0C]
        ret
    """


def asm_sb_restripe():
    """Tail of thunk_pref_sbzoom v5's ARMED path (2026-08-08 sb banding fix).

    The armed ScrollBar_draw NN-enlarges the trough (0x41/0xC5 dither) and the
    thumb grip (0xF0/0xB9 via thunk_sb_thumb) at fractional g -> both band
    ([[feedback-dither-no-resample-on-upscale]]; visible in the 20260808
    1600x1200 shot).  This tail regenerates them at device density: one
    fe_pair_remap v7 pass over the WHOLE sb canvas with g_rm_force=1 (the
    content-keyed C5/41 trough family) + the g_rm_f0ovr one-shot (the F0/B9
    face pair -- NEVER content-keyed, 0xF0 is solid console art elsewhere).
    Strokes/art/key pixels pass through by the remap's own law.

    Entered by pref_sbzoom v5's tail-jmp AFTER the bracketed draw returns:
    also closes the bracket (g_netwin_active=0, previously done inline) and
    consumes the g_sb_cur stash (stale-ptr hygiene).  g<=16 -> bracket close
    only (the one-shot contract: never set the ovr unless g>16).  Clobbers
    eax/ecx/edx only (caller-saved); the remap preserves ebx/esi/edi/ebp.
    The arrows are children with their OWN canvases -- thunk_btn_stripes v3
    restripes those on the same one-shot.

    Head (2026-10-17, fix 7): the bracket close is a CLAMPED DECREMENT, the mate of
    sbzoom v11's `inc` -- `cmp [g_netwin_active],0 / jle / dec`.  It replaces splice_dl's
    `mov eax,[g_dl_exec] / mov [g_netwin_active],eax` re-assert (itself a patch over the
    original `:= 0`): a count needs no re-assert, Datalinks' hold is 1 -> 2 -> 1 across
    the armed draw, and every other holder (tech-breakthrough modal, lobby) keeps its flag
    too.  The clamp is REQUIRED: a negative count reads nonzero = permanently armed, which
    would mis-scale every later TextScroll attach.  15B head (was 10B): 125B, ends 0x1062D.

    No inline `;` comments -- keystone hangs on them."""
    return f"""
        cmp  dword ptr [{G_NETWIN}], 0
        jle  nodec
        dec  dword ptr [{G_NETWIN}]
    nodec:
        cmp  dword ptr [{G}], 0x10
        jle  done
        mov  eax, dword ptr [{G_SB_CUR}]
        test eax, eax
        je   done
        mov  dword ptr [{G_SB_CUR}], 0
        add  eax, 0x444
        mov  dword ptr [{G_FE_DST}], eax
        xor  edx, edx
        mov  dword ptr [{G_FE_X}], edx
        mov  dword ptr [{G_FE_Y}], edx
        mov  dword ptr [{G_FE_SRC}], edx
        mov  ecx, dword ptr [eax + 0x80]
        mov  dword ptr [{G_FE_W}], ecx
        mov  ecx, dword ptr [eax + 0x84]
        neg  ecx
        mov  dword ptr [{G_FE_H}], ecx
        mov  dword ptr [{G_RM_FORCE}], 1
        mov  dword ptr [{G_RM_F0OVR}], 1
        call {REMAP_VA}
    done:
        ret
    """


def emit(name, off, asm):
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


def main():
    n = emit("thunk_rail_ytop", YTOP_OFF, asm_ytop())
    assert YTOP_OFF + n <= HSTEP_OFF, "rail_ytop overruns its slot"
    n = emit("thunk_rail_hstep", HSTEP_OFF, asm_hstep())
    assert HSTEP_OFF + n <= BUFH_OFF, "rail_hstep overruns its slot"
    n = emit("thunk_rail_bufh", BUFH_OFF, asm_bufh())
    assert BUFH_OFF + n <= BAKE_OFF, "rail_bufh overruns its slot"
    # v1 thunk_rail_bake (0x104A0..0x104D5) is RETIRED: slot zeroed, v2 lives at BAKE2_OFF
    n = emit("thunk_rail_sbfit", SBFIT_OFF, asm_sbfit())
    assert SBFIT_OFF + n <= ARROWFIT_OFF, "rail_sbfit overruns its slot"
    n = emit("thunk_sb_arrowfit", ARROWFIT_OFF, asm_arrowfit())
    assert ARROWFIT_OFF + n <= SB_RESTRIPE_OFF, "sb_arrowfit overruns its slot"
    n = emit("thunk_sb_restripe", SB_RESTRIPE_OFF, asm_sb_restripe())
    assert SB_RESTRIPE_OFF + n <= G_SB_CUR_OFF, "sb_restripe overruns its slot"
    n = emit("thunk_rail_gate", RAIL_GATE_OFF, asm_rail_gate())
    assert RAIL_GATE_OFF + n <= 0x11220, "rail_gate overruns its slot"
    n = emit("thunk_railout_hstep", RAILOUT_HSTEP_OFF, asm_railout_hstep())
    assert RAILOUT_HSTEP_OFF + n <= RAILOUT_HSTEP_END, "railout_hstep overruns its slot"
    n = emit("thunk_railout_capw", RAILOUT_CAPW_OFF, asm_railout_capw())
    assert RAILOUT_CAPW_OFF + n <= RAILOUT_CAPW_END, "railout_capw overruns its slot"
    n = emit("thunk_rail_gate4", RAIL_GATE4_OFF, asm_rail_gate4())
    assert RAIL_GATE4_OFF + n <= RAIL_SBARROWS_OFF, "rail_gate4 overruns its slot"
    n = emit("thunk_rail_sbarrows", RAIL_SBARROWS_OFF, asm_rail_sbarrows())
    assert RAIL_SBARROWS_OFF + n <= LIST_GATE_OFF, "rail_sbarrows overruns its slot"
    n = emit("thunk_list_gate", LIST_GATE_OFF, asm_list_gate())
    assert LIST_GATE_OFF + n <= FD_WHEELBAR_OFF, "list_gate overruns its slot"
    n = emit("thunk_fd_wheelbar", FD_WHEELBAR_OFF, asm_fd_wheelbar())
    assert FD_WHEELBAR_OFF + n <= RAIL_V4_END, "fd_wheelbar overruns its slot"
    n = emit("thunk_rail_bake", BAKE2_OFF, asm_bake2())
    assert BAKE2_OFF + n <= BAKE2_END, "rail_bake v2 overruns its slot"
    # thunk_rail_d (0x103B0) is RETIRED (fix rail2): its slot holds g_rr_src (0x103B0)
    n = emit("thunk_rail_sx", RAIL_SX_OFF, asm_rail_sx())
    assert RAIL_SX_OFF + n <= RAIL_SX_END, "rail_sx overruns its slot (g_rm_yph @0x103FC)"
    assert G_RR_SRC_OFF + 4 <= RAIL_SX_OFF
    n = emit("thunk_rail_walloff", WALLOFF_OFF, asm_rail_walloff())
    assert WALLOFF_OFF + n <= WALLOFF_END, "rail_walloff overruns its slot (thunk_filedlg_railscale @0xC470)"
    n = emit("thunk_rail_nncol", NNCOL_OFF, asm_rail_nncol())
    assert NNCOL_OFF + n <= NNCOL_END, "rail_nncol overruns its slot (thunk_rail_sbfit @0x104E0)"
    n = emit("thunk_rail_mark", MARK_OFF, asm_rail_mark())
    assert MARK_OFF + n <= MARK_END, "rail_mark overruns its slot (g_rail_sb @0x11260)"
    n = emit("thunk_rail_wall", WALL_OFF, asm_rail_wall())
    assert WALL_OFF + n <= WALL_END, "rail_wall overruns its slot (thunk_rail_walloff @0xC448)"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
