"""Assemble the commlink_menu_scale thunk set — bake of hook_hudmenu_scale.js
(MENU dropdown + COMMLINK panel scaling, user-verified 4K/1920/1600 2026-07-07).

pcave2 grows 0x6000 -> 0x7000; this block occupies 0x5D00..~0x6740.

Thunks (all offsets fixed; cross-refs are absolute VAs computed here):
  hm_font_size_table  0x5D00  12B   font_table_v0 native sizes per idx
  g_hm_sd2_ret        0x5D10  4B    saved caller ret (sd2 wrap)     } single-threaded UI
  g_hm_sd2_args       0x5D14  24B   dst,dx,dy,num,den,spr           } draw -> non-reentrant
  g_hm_sbc_ret        0x5D2C  4B
  g_hm_sbc_args       0x5D30  24B
  g_hm_sbc_onum/oden  0x5D48/4C     saved scale globals across the wrapped core call
  hm_sc               0x5D60  helper: eax = round(eax*g/16)          (clobbers edx)
  hm_rowY             0x5D70  helper: eax = uniform-row-pitch map    (clobbers edx)
  hm_scalefont        0x5DD0  helper: eax=font* -> scaled font* or 0 (clobbers edx)
  thunk_comm_setfont  0x5E80  entry-detour Buffer_set_font 0x5DAC70 (MW/btn bufs)
  thunk_comm_cent5    0x5F10  entry-detour cent_l_5 0x5DD020 (VOTES pitch / btn text nudge)
  thunk_comm_cent7    0x5FA0  entry-detour cent_l_7 0x5DD130 (header rect pitch)
  thunk_comm_gwinit   0x5FF0  E8 redirect @0x47A1F0 (box rect w/h x g/16)
  thunk_comm_btninit  0x6020  E8 redirect @0x47A255/0x47A315 (Council/MP btn geometry)
  thunk_comm_btnfont  0x60A0  E8 @0x607E50 site head; chains -> thunk_hud_btnfont
  thunk_menu_layout   0x6100  entry-detour layout_show 0x4032A0 (fields + g_menu_font)
  thunk_menu_text     0x61A0  entry-detour Buffer_wmfr_l 0x5DCAE0 (font slot/x/y)
  thunk_menu_winmove  0x6280  entry-detour Win_move 0x5ED7D0 (MENU X / COMM X+Y)
  thunk_hudmenu_sd2   0x6330  Sprite_draw_2 entry chain head (menu strips + council face),
                              delegates ALL traffic to thunk_portrait_avg (A5 detour intact)
  thunk_hudmenu_sbc   0x6440  Sprite_blit_scaled_core entry wrap (MW strips)
  hm_synth_core       0x6540  full strip synthesis (see contract below)

hm_synth_core(dst,dx,dy,num,den,spr) RET 0x18 — re-synthesizes the whole dest rect of a
strip blit: clean NN row/col DDA (covers the last dest row the engine's expander DROPS at
fractional scales -> the map-bleed streaks, see feedback-sprite-expand-drops-last-row),
1px dither pairs (detected per draw from the native sprite, strict-alternation probe at
two adjacent mid rows) remapped to the device-density law P = scaling_laws.stripe_period(g) (the cell
g_stripe_period) / light=P>>1 rows first / phase = DEST BUFFER row (law scaling_laws.strip_synth),
structural pixels NN-placed, key pixels skipped. DDA single-step is valid because
den<num always holds here (num>=g>=17, den in {16,18}, and R=sc(18)>18).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000

# ---- fixed offsets --------------------------------------------------------
OFFS = {
    "hm_font_size_table": 0x5D00,
    "g_hm_sd2_ret":       0x5D10,
    "g_hm_sd2_args":      0x5D14,
    "g_hm_sbc_ret":       0x5D2C,
    "g_hm_sbc_args":      0x5D30,
    "g_hm_sbc_onum":      0x5D48,
    "g_hm_sbc_oden":      0x5D4C,
    "hm_sc":              0x5D60,
    "hm_rowY":            0x5D70,
    "hm_scalefont":       0x5DE0,
    "thunk_comm_setfont": 0x5E80,
    "thunk_comm_cent5":   0x5F10,
    "thunk_comm_cent7":   0x5FA0,
    "thunk_comm_gwinit":  0x5FF0,
    "thunk_comm_btninit": 0x6030,
    "thunk_comm_btnfont": 0x60A0,
    "thunk_menu_layout":  0x6100,
    "thunk_menu_text":    0x61A0,
    "thunk_menu_winmove": 0x6280,
    "thunk_hudmenu_sd2":  0x6330,
    "thunk_hudmenu_sbc":  0x64A0,
    "hm_synth_core":      0x65D0,
}
BUDGET = {
    "hm_sc": 0x10, "hm_rowY": 0x70, "hm_scalefont": 0xA0,
    "thunk_comm_setfont": 0x90, "thunk_comm_cent5": 0x90, "thunk_comm_cent7": 0x50,
    "thunk_comm_gwinit": 0x40, "thunk_comm_btninit": 0x80, "thunk_comm_btnfont": 0x60,
    "thunk_menu_layout": 0xA0, "thunk_menu_text": 0xE0, "thunk_menu_winmove": 0xB0,
    "thunk_hudmenu_sd2": 0x170, "thunk_hudmenu_sbc": 0x130, "hm_synth_core": 0x2D0,
}
V = {k: PCAVE2 + v for k, v in OFFS.items()}

# ---- engine addresses -----------------------------------------------------
G        = 0x668740      # g_popup_scale_num
FINDFONT = 0x5882F0      # __cdecl(size, variant)
MENU_WIN, MENU_BUF = 0x9380DC, 0x938520
COMM_WIN, MW_BUF   = 0x7FD648, 0x7FDA8C
MW_ROW_FONT, MW_HDR_FONT = 0x7FD648 + 0x285C, 0x7FD648 + 0x2884   # MultiWin row_font (Arial 10,0) / hdr_font (Arial 14,1)
T_FFN    = 0xA0C000 + 0x2E570   # t_ffn(S, v) cdecl: the find_font drop-in with the face law (assemble_fontlaw.py)
MW_RECT  = 0x7FE080      # comm+0xa38 (w/h at +8/+0xC == +0xa40/+0xa44)
HS_FIELD = 0x7FE08C      # comm+0xa44 scaled box H
BTN1_OBJ, BTN1_BUF = 0x7FE80C, 0x7FEC50   # Council
BTN2_OBJ, BTN2_BUF = 0x7FF358, 0x7FF79C   # MP time-controls button
NATIVE_MENU_FONT = 0x9400E0               # find_font(16,1) = table idx7/v1
G_MENU_FONT = 0x9B7B68
SW, SH   = 0x9B7B1C, 0x9B7B20
STRIP_T, STRIP_B = 0x7AF240, 0x7AF248
SCALE_NUM, SCALE_DEN = 0x696D18, 0x696D1C
PORTRAIT_AVG = 0xA0CA00  # thunk_portrait_avg (pcave2+0xA00) — prior owner of the 0x5E4B4A entry
HUD_BTNFONT  = 0xA11990  # thunk_hud_btnfont (pcave2+0x5990) — prior owner of the 0x607E50 site
BASEBTN_INIT = 0x607210
GWINIT2      = 0x5D50A0
ELSE_RET     = 0x607F48  # FlatButton content-sprite call's return addr

# W9C F55 (2026-10-27, src assemble_menu_strip.py, law scaling_laws.menu_strip_col_map): the MENU strips' mirrored
# column map.  hm_synth_core keeps its bytes' length; two of its blocks became equal-length CALL helpers that read
# g_mc_on (set only around t_mc_synth's call of the core) and otherwise compute exactly what the blocks did.
T_MC_DIMS = PCAVE2 + 0x3F220     # dest width: the strip_synth_dims x, or g_mc_w while g_mc_on
T_MC_COL = PCAVE2 + 0x3F250      # source column: the DDA column clamped, or menu_strip_col_map(j) while g_mc_on
T_MC_SYNTH = PCAVE2 + 0x3F2E0    # thunk_hudmenu_sd2's post-blit call: a MENU strip -> the core under g_mc_on

ASMS = {}

ASMS["hm_sc"] = f"""
    imul eax, dword ptr [{G:#x}]
    add eax, 8
    sar eax, 4
    ret
"""

# 2026-11-07 (group commlink_mp_spots, src assemble_commlink_mp.py, law scaling_laws.commlink_panel_y): the first 6
# bytes (`cmp eax, 6 / jl hry_small / push ebx`) are `push t_clmp_rowy; ret` -- the entry now pins the collapsed
# multiplayer layout to the box bottom; t_clmp_rowy runs the displaced 6 bytes and re-enters here (+6 body, +0x54
# hry_small).  The body's offsets are unchanged.
T_CLMP_ROWY = PCAVE2 + 0x40D60
# 2026-11-07 (same group): thunk_hudmenu_sbc's post-blit `call hm_synth_core` -> `call t_clmp_synth` (the same args
# under g_clmp_son); hm_synth_core's dest-height block (20 bytes) -> `call t_clmp_synh` + 15 nops, identical while
# g_clmp_son == 0 (the MENU strips and the button faces), + the multiplayer strip row-law span (grow only,
# scaling_laws.commlink_strip_rows) for the COMMLINK panel's x = 0 strips.
T_CLMP_SYNTH = PCAVE2 + 0x40C70
T_CLMP_SYNH = PCAVE2 + 0x40CB0
# 2026-11-07 (COMMLINK title strip, even lines): the core's source-row block (DDA row clamped to sh - 1) is
# `call t_clmp_trow` + 7 nops -- the same row with g_clmp_son clear or any sprite but the COMMLINK title strip
# (scaling_laws.commlink_title_src_row / commlink_title_synth).
T_CLMP_TROW = PCAVE2 + 0x40C00
# 2026-11-08 (COMMLINK rails on one column map): the core's column call is `call t_clmp_col` -- the COMMLINK rail
# mode's map lookup while g_mc_on == 2 (t_clmp_pre), else a tail jump to t_mc_col (unchanged behaviour).
T_CLMP_COL = PCAVE2 + 0x41A80
ASMS["hm_rowY"] = f"""
    push {T_CLMP_ROWY:#x}
    ret
    push ecx
    sub eax, 6
    xor edx, edx
    mov ecx, 18
    div ecx
    mov ebx, edx
    mov ecx, eax
    mov eax, 18
    imul eax, dword ptr [{G:#x}]
    add eax, 8
    sar eax, 4
    imul ecx, eax
    mov eax, 6
    imul eax, dword ptr [{G:#x}]
    add eax, 8
    sar eax, 4
    add ecx, eax
    mov eax, ebx
    imul eax, dword ptr [{G:#x}]
    add eax, 8
    sar eax, 4
    add eax, ecx
    pop ecx
    pop ebx
    ret
hry_small:
    imul eax, dword ptr [{G:#x}]
    add eax, 8
    sar eax, 4
    ret
"""

# hm_scalefont v2 (2026-09-17, audit finding 3.3): MultiWin's two Font_init'd fonts (row_font MW+0x285C =
# Arial 10 REGULAR, hdr_font MW+0x2884 = Arial 14 bold) go through t_ffn(NATIVE size, variant) = the face
# law; v1's off-table branch asked the pool for round((cell-3)g/16) with variant 1 = Arial Narrow bold.
# Any other off-table font keeps the v1 estimate.
ASMS["hm_scalefont"] = f"""
    push ecx
    push ebx
    mov ebx, eax
    cmp ebx, {MW_ROW_FONT:#x}
    jne hsf_nrow
    push 0
    push 10
    jmp hsf_ffn
hsf_nrow:
    cmp ebx, {MW_HDR_FONT:#x}
    jne hsf_pool
    push 1
    push 14
hsf_ffn:
    call {T_FFN:#x}
    add esp, 8
    jmp hsf_done
hsf_pool:
    sub eax, 0x93FC58
    js hsf_off
    cmp eax, 0x780
    jge hsf_off
    xor edx, edx
    mov ecx, 0xA0
    div ecx
    movzx ebx, byte ptr [eax + {V['hm_font_size_table']:#x}]
    mov eax, edx
    xor edx, edx
    mov ecx, 0x28
    div ecx
    mov ecx, eax
    mov eax, ebx
    jmp hsf_scale
hsf_off:
    mov eax, dword ptr [ebx+0xC]
    test eax, eax
    jle hsf_fail
    cmp eax, 3
    jle hsf_v
    sub eax, 3
hsf_v:
    mov ecx, 1
hsf_scale:
    imul eax, dword ptr [{G:#x}]
    add eax, 8
    sar eax, 4
    cmp eax, 40
    jle hsf_c1
    mov eax, 40
hsf_c1:
    cmp eax, 8
    jge hsf_c2
    mov eax, 8
hsf_c2:
    push ecx
    push eax
    call {FINDFONT:#x}
    add esp, 8
    jmp hsf_done
hsf_fail:
    xor eax, eax
hsf_done:
    pop ebx
    pop ecx
    ret
"""

# Buffer_set_font 0x5DAC70 entry detour (displaced: 8B 44 24 04 85 C0; resume 0x5DAC76).
# esp-neutral entry: [esp]=ret, [esp+4/8/0xC]=f0/f1/f2, ecx=buf.
ASMS["thunk_comm_setfont"] = f"""
    cmp ecx, {MW_BUF:#x}
    je csf_go
    cmp ecx, {BTN1_BUF:#x}
    je csf_go
    cmp ecx, {BTN2_BUF:#x}
    jne csf_replay
csf_go:
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle csf_replay
    mov eax, dword ptr [esp+4]
    test eax, eax
    je csf_1
    call {V['hm_scalefont']:#x}
    test eax, eax
    je csf_1
    mov dword ptr [esp+4], eax
csf_1:
    mov eax, dword ptr [esp+8]
    test eax, eax
    je csf_2
    call {V['hm_scalefont']:#x}
    test eax, eax
    je csf_2
    mov dword ptr [esp+8], eax
csf_2:
    mov eax, dword ptr [esp+0xC]
    test eax, eax
    je csf_replay
    call {V['hm_scalefont']:#x}
    test eax, eax
    je csf_replay
    mov dword ptr [esp+0xC], eax
csf_replay:
    mov eax, dword ptr [esp+4]
    test eax, eax
    jmp 0x5DAC76
"""

# cent_l_5 0x5DD020 entry detour (displaced: 53 56 57 8B 7C 24 10; resume 0x5DD027).
# [esp+4]=str, [esp+8]=x, [esp+0xC]=y, [esp+0x10]=w. ecx=buf.
ASMS["thunk_comm_cent5"] = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle c5_replay
    cmp ecx, {MW_BUF:#x}
    jne c5_trybtn
    mov eax, dword ptr [esp+0xC]
    call {V['hm_rowY']:#x}
    mov dword ptr [esp+0xC], eax
    mov eax, dword ptr [esp+0x10]
    call {V['hm_sc']:#x}
    mov dword ptr [esp+0x10], eax
    jmp c5_replay
c5_trybtn:
    cmp ecx, {BTN1_BUF:#x}
    je c5_btn
    cmp ecx, {BTN2_BUF:#x}
    jne c5_replay
c5_btn:
    mov eax, dword ptr [{G:#x}]
    sub eax, 16
    sar eax, 3
    sub dword ptr [esp+0xC], eax
c5_replay:
    push ebx
    push esi
    push edi
    mov edi, dword ptr [esp+0x10]
    jmp 0x5DD027
"""

# cent_l_7 0x5DD130 entry detour (displaced: 83 EC 10 53 55 56 57; resume 0x5DD137).
# [esp+8]=rect*. ecx=buf.
ASMS["thunk_comm_cent7"] = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle c7_replay
    cmp ecx, {MW_BUF:#x}
    jne c7_replay
    push ebx
    mov ebx, dword ptr [esp+0xC]
    mov eax, dword ptr [ebx+4]
    call {V['hm_rowY']:#x}
    mov dword ptr [ebx+4], eax
    mov eax, dword ptr [ebx+0xC]
    call {V['hm_rowY']:#x}
    mov dword ptr [ebx+0xC], eax
    pop ebx
c7_replay:
    sub esp, 0x10
    push ebx
    push ebp
    push esi
    push edi
    jmp 0x5DD137
"""

# E8 redirect @0x47A1F0 (commlink_win_build's GraphicWin_init_2 call): scale the
# box rect w/h in place (the rect IS comm+0xa40/+0xa44, persisted scaled).
ASMS["thunk_comm_gwinit"] = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle cgw_fwd
    mov edx, dword ptr [esp+4]
    cmp edx, {MW_RECT:#x}
    jne cgw_fwd
    mov eax, dword ptr [edx+8]
    push edx
    call {V['hm_sc']:#x}
    pop edx
    mov dword ptr [edx+8], eax
    mov eax, dword ptr [edx+0xC]
    push edx
    call {V['hm_sc']:#x}
    pop edx
    mov dword ptr [edx+0xC], eax
cgw_fwd:
    jmp {GWINIT2:#x}
"""

# E8 redirects @0x47A255/0x47A315 (the two BaseButton_init calls in commlink_win_build):
# x,w,h x g/16; y' = round(y*g/16) - round(Hs*(g-16)/16)  (Hs = scaled box H, the native
# slack subtraction rebuilt proportional). Falls into the existing 0x607210 entry detour
# (thunk_factionwin_button, gate off in-game) -> body. ecx (btn) untouched.
ASMS["thunk_comm_btninit"] = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle cbi_fwd
    cmp dword ptr [esp+0x1C], {COMM_WIN:#x}
    jne cbi_fwd
    mov eax, dword ptr [esp+0xC]
    call {V['hm_sc']:#x}
    mov dword ptr [esp+0xC], eax
    mov eax, dword ptr [esp+0x14]
    call {V['hm_sc']:#x}
    mov dword ptr [esp+0x14], eax
    mov eax, dword ptr [esp+0x18]
    call {V['hm_sc']:#x}
    mov dword ptr [esp+0x18], eax
    mov eax, dword ptr [esp+0x10]
    call {V['hm_sc']:#x}
    push eax
    mov eax, dword ptr [{HS_FIELD:#x}]
    mov edx, dword ptr [{G:#x}]
    sub edx, 16
    imul eax, edx
    add eax, 8
    sar eax, 4
    pop edx
    sub edx, eax
    mov dword ptr [esp+0x10], edx
cbi_fwd:
    jmp {BASEBTN_INIT:#x}
"""

# E8 @0x607E50 site head (was E8 thunk_hud_btnfont): Council/MP button text font — the
# button buffer's font slot (+0x52C of the embedded buffer at obj+0x444 -> obj+0x970)
# never gets a Buffer_set_font, so repoint it each draw (idempotent: derived from the native 12pt,
# never from the current slot).  v2 2026-09-17 (audit finding 3.4, probe hook_btnfont_probe.js): the
# buttons' vanilla font is the engine's default label Font 0x7D3948 = Arial 12 REGULAR (GetObject at
# 1024x768), so t_ffn(12, 0) = Arial fl(12g/16) regular on the (12,0) slot -- v1 asked the pool for
# round(12g/16) with variant 1 = Arial Narrow bold.
# Then chain to thunk_hud_btnfont (which consumes the E8 ret addr + replays the prologue).
ASMS["thunk_comm_btnfont"] = f"""
    cmp ecx, {BTN1_OBJ:#x}
    je cbf_go
    cmp ecx, {BTN2_OBJ:#x}
    jne cbf_tail
cbf_go:
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle cbf_tail
    push ecx
    push edx
    push 0
    push 12
    call {T_FFN:#x}
    add esp, 8
    pop edx
    pop ecx
    test eax, eax
    je cbf_tail
    mov dword ptr [ecx+0x970], eax
cbf_tail:
    jmp {HUD_BTNFONT:#x}
"""

# layout_show 0x4032A0 entry detour (displaced: 56 8B F1 57 6A 00; resume 0x4032A6).
# Menu widget geometry fields from VANILLA constants (idempotent): w=sc(139) (+0x1104
# resize / +0x1130 spot width), rowH=sc(18) (+0x1134), margin=sc(6) (+0x1108); and
# g_menu_font -> find_font(min(g,40), 1)  (sc(16)==g).
ASMS["thunk_menu_layout"] = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle ml_replay
    push ecx
    mov eax, 139
    call {V['hm_sc']:#x}
    mov dword ptr [ecx+0x1104], eax
    mov dword ptr [ecx+0x1130], eax
    mov eax, 18
    call {V['hm_sc']:#x}
    mov dword ptr [ecx+0x1134], eax
    mov eax, 6
    call {V['hm_sc']:#x}
    mov dword ptr [ecx+0x1108], eax
    mov eax, dword ptr [{G:#x}]
    cmp eax, 40
    jle ml_f1
    mov eax, 40
ml_f1:
    push 1
    push eax
    call {FINDFONT:#x}
    add esp, 8
    test eax, eax
    je ml_f2
    mov dword ptr [{G_MENU_FONT:#x}], eax
ml_f2:
    pop ecx
ml_replay:
    push esi
    mov esi, ecx
    push edi
    push 0
    jmp 0x4032A6
"""

# Buffer_wmfr_l 0x5DCAE0 entry detour (displaced: 55 8B EC 83 EC 08; resume 0x5DCAE6).
# MENU item text: font slot +0x52C scaled ONLY from the native menu font (idempotence
# gate — the per-row escalation bug class), x inset x g/16, y rewritten to the uniform
# row formula margin + round((y-margin)/rowH)*rowH + floor(3g/16).
ASMS["thunk_menu_text"] = f"""
    cmp ecx, {MENU_BUF:#x}
    jne mt_replay
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle mt_replay
    cmp dword ptr [ecx+0x52C], {NATIVE_MENU_FONT:#x}
    jne mt_x
    mov eax, dword ptr [{G:#x}]
    cmp eax, 40
    jle mt_f1
    mov eax, 40
mt_f1:
    push ecx
    push 1
    push eax
    call {FINDFONT:#x}
    add esp, 8
    pop ecx
    test eax, eax
    je mt_x
    mov dword ptr [ecx+0x52C], eax
mt_x:
    mov eax, dword ptr [esp+8]
    call {V['hm_sc']:#x}
    mov dword ptr [esp+8], eax
    push ebx
    push esi
    mov eax, 6
    call {V['hm_sc']:#x}
    mov ebx, eax
    mov eax, 18
    call {V['hm_sc']:#x}
    mov esi, eax
    mov eax, dword ptr [esp+0x14]
    sub eax, ebx
    jl mt_ynope
    shl eax, 1
    add eax, esi
    push ecx
    lea ecx, [esi+esi]
    xor edx, edx
    div ecx
    pop ecx
    imul eax, esi
    add eax, ebx
    mov edx, dword ptr [{G:#x}]
    lea edx, [edx+edx*2]
    sar edx, 4
    add eax, edx
    mov dword ptr [esp+0x14], eax
mt_ynope:
    pop esi
    pop ebx
mt_replay:
    push ebp
    mov ebp, esp
    sub esp, 8
    jmp 0x5DCAE6
"""

# Win_move 0x5ED7D0 entry detour (displaced: 8A 81 9C 00 00 00; resume 0x5ED7D6).
# MENU X = (SW - 64g)/2 (recenters over the scaled 1024-wide strip); COMM X+Y anchored
# to the scaled strip: right edge at (SW+64g)/2, bottom at strip top.
ASMS["thunk_menu_winmove"] = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle wm_replay
    cmp ecx, {MENU_WIN:#x}
    je wm_menu
    cmp ecx, {COMM_WIN:#x}
    je wm_comm
    jmp wm_replay
wm_menu:
    mov eax, dword ptr [{G:#x}]
    shl eax, 6
    mov edx, dword ptr [{SW:#x}]
    sub edx, eax
    sar edx, 1
    mov dword ptr [esp+4], edx
    jmp wm_replay
wm_comm:
    mov eax, dword ptr [{G:#x}]
    shl eax, 6
    add eax, dword ptr [{SW:#x}]
    sar eax, 1
    sub eax, dword ptr [ecx+0x4C4]
    mov dword ptr [esp+4], eax
    mov eax, dword ptr [{STRIP_B:#x}]
    sub eax, dword ptr [{STRIP_T:#x}]
    jge wm_abs
    neg eax
wm_abs:
    mov edx, dword ptr [{SH:#x}]
    sub edx, eax
    add edx, dword ptr [ecx+0x4C8]
    mov dword ptr [esp+8], edx
wm_replay:
    mov al, byte ptr [ecx+0x9C]
    jmp 0x5ED7D6
"""

# Sprite_draw_2 0x5E4B4A entry chain HEAD (the entry site now pushes this thunk; it
# delegates ALL traffic to thunk_portrait_avg = the prior owner, so the A5 faction-box
# detour keeps working). For the MENU strips and the Council/MP button faces it first
# adjusts args, then swaps the caller ret for a resume so hm_synth_core runs post-blit.
# esp-neutral: [esp]=ret, [esp+4]=dest, +8=key, +0xC=x, +0x10=y, +0x14=num, +0x18=den. ecx=spr.
ASMS["thunk_hudmenu_sd2"] = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle sd2_pass
    mov eax, dword ptr [esp+4]
    cmp eax, {MENU_BUF:#x}
    je sd2_menu
    cmp eax, {BTN1_BUF:#x}
    je sd2_btnchk
    cmp eax, {BTN2_BUF:#x}
    je sd2_btnchk
sd2_pass:
    push {PORTRAIT_AVG:#x}
    ret
sd2_btnchk:
    cmp dword ptr [esp], {ELSE_RET:#x}
    jne sd2_pass
    mov edx, dword ptr [esp+4]
    push ebx
    mov ebx, dword ptr [edx+0x80]
    mov eax, dword ptr [ecx+0x18]
    call {V['hm_sc']:#x}
    sub ebx, eax
    sar ebx, 1
    mov dword ptr [esp+0x10], ebx
    mov eax, dword ptr [ecx+0x1C]
    call {V['hm_sc']:#x}
    mov edx, dword ptr [esp+8]
    add eax, dword ptr [edx+0x84]
    sar eax, 1
    neg eax
    mov dword ptr [esp+0x14], eax
    mov eax, dword ptr [{G:#x}]
    mov dword ptr [esp+0x18], eax
    mov dword ptr [esp+0x1C], 16
    pop ebx
    jmp sd2_wrap
sd2_menu:
    push ebx
    mov eax, dword ptr [ecx+0x14]
    cmp eax, 18
    jne sd2_mplain
    mov eax, 18
    call {V['hm_sc']:#x}
    mov ebx, eax
    mov eax, 6
    call {V['hm_sc']:#x}
    mov edx, dword ptr [esp+0x14]
    sub edx, eax
    jl sd2_mplain
    mov eax, edx
    xor edx, edx
    div ebx
    test edx, edx
    jnz sd2_mplain
    mov dword ptr [esp+0x18], ebx
    mov dword ptr [esp+0x1C], 18
    pop ebx
    jmp sd2_wrap
sd2_mplain:
    mov eax, dword ptr [{G:#x}]
    mov dword ptr [esp+0x18], eax
    mov dword ptr [esp+0x1C], 16
    pop ebx
sd2_wrap:
    mov eax, dword ptr [esp+4]
    mov dword ptr [{V['g_hm_sd2_args']:#x}], eax
    mov eax, dword ptr [esp+0xC]
    mov dword ptr [{V['g_hm_sd2_args']+4:#x}], eax
    mov eax, dword ptr [esp+0x10]
    mov dword ptr [{V['g_hm_sd2_args']+8:#x}], eax
    mov eax, dword ptr [esp+0x14]
    mov dword ptr [{V['g_hm_sd2_args']+12:#x}], eax
    mov eax, dword ptr [esp+0x18]
    mov dword ptr [{V['g_hm_sd2_args']+16:#x}], eax
    mov dword ptr [{V['g_hm_sd2_args']+20:#x}], ecx
    mov eax, dword ptr [esp]
    mov dword ptr [{V['g_hm_sd2_ret']:#x}], eax
    mov dword ptr [esp], sd2_resume
    push {PORTRAIT_AVG:#x}
    ret
sd2_resume:
    push eax
    push dword ptr [{V['g_hm_sd2_args']+20:#x}]
    push dword ptr [{V['g_hm_sd2_args']+16:#x}]
    push dword ptr [{V['g_hm_sd2_args']+12:#x}]
    push dword ptr [{V['g_hm_sd2_args']+8:#x}]
    push dword ptr [{V['g_hm_sd2_args']+4:#x}]
    push dword ptr [{V['g_hm_sd2_args']:#x}]
    call {T_MC_SYNTH:#x}
    pop eax
    jmp dword ptr [{V['g_hm_sd2_ret']:#x}]
"""

# Sprite_blit_scaled_core 0x5E4B9A entry detour (displaced: 55 8B EC 83 EC 64; resume
# 0x5E4BA0). COMMLINK panel strips: set the scale globals per blit (uniform row pitch:
# native y=6+18k row strips of blit_h 18 stretch EXACTLY sc(18)/18, everything else
# g/16), x=sc(x), y=rowY(y); wrap the core call to restore the globals and run
# hm_synth_core post-blit. Non-MW blits replay the prologue untouched.
ASMS["thunk_hudmenu_sbc"] = f"""
    cmp dword ptr [esp+4], {MW_BUF:#x}
    jne sbc_plain
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle sbc_plain
    mov eax, dword ptr [{SCALE_NUM:#x}]
    mov dword ptr [{V['g_hm_sbc_onum']:#x}], eax
    mov eax, dword ptr [{SCALE_DEN:#x}]
    mov dword ptr [{V['g_hm_sbc_oden']:#x}], eax
    push ebx
    mov eax, dword ptr [ecx+0x14]
    cmp eax, 18
    jne sbc_splain
    mov eax, dword ptr [esp+0x14]
    sub eax, 6
    jl sbc_splain
    mov ebx, 18
    xor edx, edx
    div ebx
    test edx, edx
    jnz sbc_splain
    mov eax, 18
    call {V['hm_sc']:#x}
    mov ebx, eax
    mov dword ptr [{SCALE_DEN:#x}], 18
    jmp sbc_store
sbc_splain:
    mov ebx, dword ptr [{G:#x}]
    mov dword ptr [{SCALE_DEN:#x}], 16
sbc_store:
    mov dword ptr [{SCALE_NUM:#x}], ebx
    mov dword ptr [{V['g_hm_sbc_args']+12:#x}], ebx
    mov eax, dword ptr [{SCALE_DEN:#x}]
    mov dword ptr [{V['g_hm_sbc_args']+16:#x}], eax
    mov eax, dword ptr [esp+0x10]
    call {V['hm_sc']:#x}
    mov dword ptr [esp+0x10], eax
    mov dword ptr [{V['g_hm_sbc_args']+4:#x}], eax
    mov eax, dword ptr [esp+0x14]
    call {V['hm_rowY']:#x}
    mov dword ptr [esp+0x14], eax
    mov dword ptr [{V['g_hm_sbc_args']+8:#x}], eax
    mov dword ptr [{V['g_hm_sbc_args']:#x}], {MW_BUF:#x}
    mov dword ptr [{V['g_hm_sbc_args']+20:#x}], ecx
    pop ebx
    mov eax, dword ptr [esp]
    mov dword ptr [{V['g_hm_sbc_ret']:#x}], eax
    mov dword ptr [esp], sbc_resume
sbc_plain:
    push ebp
    mov ebp, esp
    sub esp, 0x64
    jmp 0x5E4BA0
sbc_resume:
    push eax
    mov eax, dword ptr [{V['g_hm_sbc_onum']:#x}]
    mov dword ptr [{SCALE_NUM:#x}], eax
    mov eax, dword ptr [{V['g_hm_sbc_oden']:#x}]
    mov dword ptr [{SCALE_DEN:#x}], eax
    push dword ptr [{V['g_hm_sbc_args']+20:#x}]
    push dword ptr [{V['g_hm_sbc_args']+16:#x}]
    push dword ptr [{V['g_hm_sbc_args']+12:#x}]
    push dword ptr [{V['g_hm_sbc_args']+8:#x}]
    push dword ptr [{V['g_hm_sbc_args']+4:#x}]
    push dword ptr [{V['g_hm_sbc_args']:#x}]
    call {T_CLMP_SYNTH:#x}
    pop eax
    jmp dword ptr [{V['g_hm_sbc_ret']:#x}]
"""

# hm_synth_core(dst, dx, dy, num, den, spr) — callee-clean RET 0x18. Contract in the
# module docstring. Frame reserved BEFORE the register pushes (thunk frame-aliasing rule).
# Locals: -4 g, -8 sdata, -0xC spitch, -0x10 sw, -0x14 sh, -0x18 key, -0x1C ddata,
# -0x20 stride, -0x24 bw, -0x28 bh, -0x2C W, -0x30 H, -0x34 x0, -0x38 y0, -0x3C x1,
# -0x40 y1, -0x44 xm, -0x48 pairA(-1 none), -0x4C pairB, -0x50 light, -0x54 dark,
# -0x58 tries, -0x5C P, -0x60 lightN, -0x64 sr, -0x68 rerr, -0x6C sc0, -0x70 cerr0,
# -0x74 ycur, -0x78 tex.
ASMS["hm_synth_core"] = f"""
    push ebp
    mov ebp, esp
    sub esp, 0x80
    push ebx
    push esi
    push edi
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle sy_done
    mov dword ptr [ebp-4], eax
    mov esi, dword ptr [ebp+0x1C]
    mov eax, dword ptr [esi+4]
    test eax, eax
    je sy_done
    mov dword ptr [ebp-8], eax
    mov eax, dword ptr [esi+0xC]
    test eax, eax
    jle sy_done
    mov dword ptr [ebp-0xC], eax
    mov eax, dword ptr [esi+0x10]
    cmp eax, 3
    jl sy_done
    cmp eax, 2048
    jg sy_done
    mov dword ptr [ebp-0x10], eax
    mov eax, dword ptr [esi+0x14]
    cmp eax, 2
    jl sy_done
    cmp eax, 256
    jg sy_done
    mov dword ptr [ebp-0x14], eax
    movzx eax, byte ptr [esi+8]
    mov dword ptr [ebp-0x18], eax
    mov esi, dword ptr [ebp+8]
    mov eax, dword ptr [esi+0x54]
    test eax, eax
    je sy_done
    mov dword ptr [ebp-0x1C], eax
    mov eax, dword ptr [esi+0x4A8]
    test eax, eax
    jle sy_done
    mov dword ptr [ebp-0x20], eax
    mov eax, dword ptr [esi+0x80]
    mov dword ptr [ebp-0x24], eax
    mov eax, dword ptr [esi+0x84]
    test eax, eax
    jge sy_bhok
    neg eax
sy_bhok:
    mov dword ptr [ebp-0x28], eax
    mov ecx, dword ptr [ebp+0x18]
    test ecx, ecx
    jle sy_done
    call {T_MC_DIMS:#x}
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    call {T_CLMP_SYNH:#x}
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    mov eax, dword ptr [ebp+0xC]
    test eax, eax
    jge sy_x0
    xor eax, eax
sy_x0:
    mov dword ptr [ebp-0x34], eax
    mov eax, dword ptr [ebp+0x10]
    test eax, eax
    jge sy_y0
    xor eax, eax
sy_y0:
    mov dword ptr [ebp-0x38], eax
    mov eax, dword ptr [ebp+0xC]
    add eax, dword ptr [ebp-0x2C]
    cmp eax, dword ptr [ebp-0x24]
    jle sy_x1
    mov eax, dword ptr [ebp-0x24]
sy_x1:
    mov dword ptr [ebp-0x3C], eax
    mov eax, dword ptr [ebp+0x10]
    add eax, dword ptr [ebp-0x30]
    cmp eax, dword ptr [ebp-0x28]
    jle sy_y1
    mov eax, dword ptr [ebp-0x28]
sy_y1:
    mov dword ptr [ebp-0x40], eax
    mov eax, dword ptr [ebp-0x3C]
    cmp eax, dword ptr [ebp-0x34]
    jle sy_done
    mov eax, dword ptr [ebp-0x40]
    cmp eax, dword ptr [ebp-0x38]
    jle sy_done
    mov eax, dword ptr [ebp-0x10]
    sar eax, 1
    mov dword ptr [ebp-0x44], eax
    mov dword ptr [ebp-0x48], -1
    mov dword ptr [ebp-0x58], 2
    mov ebx, dword ptr [ebp-0x14]
    sar ebx, 1
sy_ptry:
    cmp ebx, 1
    jl sy_pnext
    mov eax, ebx
    add eax, 2
    cmp eax, dword ptr [ebp-0x14]
    jge sy_pnext
    mov eax, ebx
    imul eax, dword ptr [ebp-0xC]
    add eax, dword ptr [ebp-8]
    add eax, dword ptr [ebp-0x44]
    mov esi, eax
    mov eax, dword ptr [ebp-0xC]
    movzx ecx, byte ptr [esi]
    movzx edx, byte ptr [esi+eax]
    cmp ecx, edx
    je sy_pnext
    cmp ecx, dword ptr [ebp-0x18]
    je sy_pnext
    cmp edx, dword ptr [ebp-0x18]
    je sy_pnext
    mov edi, esi
    sub edi, eax
    movzx edi, byte ptr [edi]
    cmp edi, edx
    jne sy_pnext
    lea edi, [esi+eax*2]
    movzx edi, byte ptr [edi]
    cmp edi, ecx
    jne sy_pnext
    mov dword ptr [ebp-0x48], ecx
    mov dword ptr [ebp-0x4C], edx
    test ebx, 1
    jnz sy_lightB
    mov dword ptr [ebp-0x50], ecx
    mov dword ptr [ebp-0x54], edx
    jmp sy_pdone
sy_lightB:
    mov dword ptr [ebp-0x50], edx
    mov dword ptr [ebp-0x54], ecx
    jmp sy_pdone
sy_pnext:
    dec ebx
    dec dword ptr [ebp-0x58]
    jnz sy_ptry
sy_pdone:
    mov eax, dword ptr [ebp-4]
    mov eax, dword ptr [0x66879c]
    nop
    mov dword ptr [ebp-0x5C], eax
    sar eax, 1
    mov dword ptr [ebp-0x60], eax
    mov eax, dword ptr [ebp-0x38]
    sub eax, dword ptr [ebp+0x10]
    imul eax, dword ptr [ebp+0x18]
    xor edx, edx
    div dword ptr [ebp+0x14]
    mov dword ptr [ebp-0x64], eax
    mov dword ptr [ebp-0x68], edx
    mov eax, dword ptr [ebp-0x34]
    sub eax, dword ptr [ebp+0xC]
    imul eax, dword ptr [ebp+0x18]
    xor edx, edx
    div dword ptr [ebp+0x14]
    mov dword ptr [ebp-0x6C], eax
    mov dword ptr [ebp-0x70], edx
    mov eax, dword ptr [ebp-0x38]
    mov dword ptr [ebp-0x74], eax
sy_row:
    call {T_CLMP_TROW:#x}
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    imul eax, dword ptr [ebp-0xC]
    add eax, dword ptr [ebp-8]
    mov esi, eax
    mov eax, dword ptr [ebp-0x74]
    imul eax, dword ptr [ebp-0x20]
    add eax, dword ptr [ebp-0x1C]
    add eax, dword ptr [ebp-0x34]
    mov edi, eax
    mov eax, dword ptr [ebp-0x74]
    xor edx, edx
    div dword ptr [ebp-0x5C]
    mov eax, dword ptr [ebp-0x50]
    cmp edx, dword ptr [ebp-0x60]
    jl sy_texok
    mov eax, dword ptr [ebp-0x54]
sy_texok:
    mov dword ptr [ebp-0x78], eax
    mov ebx, dword ptr [ebp-0x6C]
    mov ecx, dword ptr [ebp-0x70]
    mov edx, dword ptr [ebp-0x34]
sy_col:
    call {T_CLMP_COL:#x}
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    movzx eax, byte ptr [esi+eax]
    cmp dword ptr [ebp-0x48], 0
    jl sy_nopair
    cmp eax, dword ptr [ebp-0x48]
    je sy_tex
    cmp eax, dword ptr [ebp-0x4C]
    jne sy_nopair
sy_tex:
    mov eax, dword ptr [ebp-0x78]
sy_nopair:
    cmp eax, dword ptr [ebp-0x18]
    je sy_skip
    mov byte ptr [edi], al
sy_skip:
    inc edi
    add ecx, dword ptr [ebp+0x18]
    cmp ecx, dword ptr [ebp+0x14]
    jl sy_nostep
    sub ecx, dword ptr [ebp+0x14]
    inc ebx
sy_nostep:
    inc edx
    cmp edx, dword ptr [ebp-0x3C]
    jl sy_col
    mov eax, dword ptr [ebp-0x68]
    add eax, dword ptr [ebp+0x18]
    cmp eax, dword ptr [ebp+0x14]
    jl sy_rny
    sub eax, dword ptr [ebp+0x14]
    inc dword ptr [ebp-0x64]
sy_rny:
    mov dword ptr [ebp-0x68], eax
    inc dword ptr [ebp-0x74]
    mov eax, dword ptr [ebp-0x74]
    cmp eax, dword ptr [ebp-0x40]
    jl sy_row
sy_done:
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    ret 0x18
"""

DATA = {
    "hm_font_size_table": bytes([40, 36, 32, 24, 22, 20, 18, 16, 14, 12, 10, 8]),
}

def main():
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    out = {}
    order = sorted(OFFS, key=lambda k: OFFS[k])
    for name in order:
        if name in DATA:
            out[name] = DATA[name]
            continue
        if name.startswith("g_hm_"):
            continue
        enc, _ = ks.asm(ASMS[name], V[name])
        b = bytes(enc)
        assert len(b) <= BUDGET[name], f"{name}: {len(b)}B > budget {BUDGET[name]:#x}"
        out[name] = b
    # overlap check
    spans = []
    for name in order:
        if name in out:
            spans.append((OFFS[name], OFFS[name] + len(out[name]), name))
        elif name.startswith("g_hm_"):
            size = 24 if name.endswith("args") else 4
            spans.append((OFFS[name], OFFS[name] + size, name))
    spans.sort()
    for (s0, e0, n0), (s1, e1, n1) in zip(spans, spans[1:]):
        assert e0 <= s1, f"OVERLAP {n0} ({s0:#x}..{e0:#x}) vs {n1} @ {s1:#x}"
    assert spans[-1][1] <= 0x7000, f"tail {spans[-1][1]:#x} exceeds section 0x7000"

    for name in order:
        if name not in out:
            continue
        b = out[name]
        print(f"      # {name} @ pcave2+{OFFS[name]:#06x} (VA {V[name]:#x}) = {len(b)}B")
        print(f"      - id: {name}")
        print(f"        offset: {OFFS[name]:#x}")
        print(f"        bytes: \"{' '.join(f'{x:02X}' for x in b)}\"")
    print()
    print(f"tail = pcave2+{spans[-1][1]:#x} / 0x7000")

if __name__ == "__main__":
    main()
