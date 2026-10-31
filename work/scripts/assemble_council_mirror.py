# Regenerates the W5B helpers in pcave2 0x3D000..0x3DFFF (2026-10-25 wave-5 W5B; laws scaling_laws.council_rail_mirror_sum
# / council_backdrop_rect v2 / council_ring_rect / council_mirror_cols / council_column_rects / council_drawn; guards
# tests/test_council_mirror_asm_parity.py + tests/test_scaling_council_mirror.py):
#
# The Planetary Council (CouncilWin 0x6FEC80) was mirrored about a centre 1 (4K) .. 2 px (1080, 1440) right of its
# slide rails' centre: the backdrop R was W - dp(0x37) (the rails sit at railscale's double floor, 1..3 px left of it)
# and every frame (backdrop d690, d5a0 ring, column d528s, vote chips) reached a band-map renderer INCLUSIVE of R / B.
# The right border hid under the inner right rail (4K shot 20261024-233251: R = 1893, rail at 1892).  Now:
#
#   t_cw_s1        CALL helper: eax = the council canvas width W -> eax = S1 = council_rail_mirror_sum(W, g) =
#                  fl((fl(W*16/g) - 0x37)*g/16) + fl(15g/16) + fl(8g/16) -- the inner right rail's x (railscale v3's
#                  arithmetic, cdq-free div on the non-negative W*16) plus the left rails' extent.  Every other
#                  register kept; g > 16 callers only.
#   t_cw_mirror    v2 (after audit-w5B; @0x3D200, v1's 0x3D040 slot left free) thunk_cw_seeds' tail (its
#                  `jmp Font_init` -> push t_cw_mirror; ret).  g > 16: S1 from W = dp(0x32C) (the canvas
#                  GraphicWin_init creates next, imm 0x427A14) and the run start = rail extent + dp(4) + K (the
#                  ring's inner edge) into g_cw_mstate; on both column sets (outer [+0xBF4], inner [+0xC04], stride
#                  0x20): the centre column w + ((S1 - w) & 1) wide at L3 = (S1 - w3) / 2; budget B = L3 - start - 3w;
#                  column c (0..2) L = start + half_down(Wc_c * B, sum) + c*w with the cumulative vanilla channel
#                  weights of g_cw_wts (inner 4/9/14 of 19, governor set 2/4/6 of 8 -- scaling_laws.cum, the
#                  weighted remainder law), R = L + w; column 6 - c = (S1 - R_c, T, S1 - L_c, B)
#                  (council_mirror_cols).  pushad / popad; then (every g) push Font_init; ret, the call's stack as it
#                  came.  v1 left columns 0..2 on their dp() seeds: the rails' 0..4 px shortfall all in the centre gaps.
#   t_cw_backdrop  CouncilWin_repaint's d690 backdrop @0x426B4E (was thunk_cw_backdrop37), Buffer_box_sprite's
#                  contract.  g > 16: rect.L = rail_left_extent, rect.R = S1 - L (the inner right rail's x), in place
#                  (the d5a0 ring @0x426B7B is this rect inset dp(4)), then jmp t_cw_hodf (half-open devfill).
#                  g <= 16: Buffer_box_sprite unchanged.  (A jmp between two helpers of this region is position-
#                  independent: both move together.)
#   t_cw_chiphalf  the five vote-chip sites (was t_si_chip): g > 16 R-1 / B-1 around t_si_chip (rect restored, ebx
#                  kept -- live in the column painter); g <= 16 tail t_si_chip unchanged.
#   (t_cw_backdrop is no longer called by a site since W7B -- t_cw_bd2 below; left assembled, outside W7B's region.)
#   t_cw_hodf      the same wrapper around thunk_box_thick_devfill (the W2A t_bm_ho_* shape): the backdrop's tail and
#                  the two column d528 sites.  NOT t_rw_backdrop: its exact-fill flag re-phases the d690 enlarge (the
#                  border came out 2 px at g = 24 against the 1-px ring / columns, 3 px at 4K against 2) -- measured on
#                  the real image g 17..40; columns, ring and chips are pixel-identical either way.
# Site retargets (patches.yaml, group council_scale; assemble_council.SITES carries the shipped targets):
#   0x426B4E -> t_cw_backdrop, 0x426B7B (d5a0 ring) -> t_bm_ho_hf (W2A's half-open hollow_flat), 0x425EE9 (column
#   d528) / 0x426286 (d528 chip) -> t_cw_hodf, 0x4261AA / 0x4261D6 / 0x426203 / 0x426230 / 0x42625C (chips) ->
#   t_cw_chiphalf.
#
# 2026-10-25 wave-7 W7B (region 0x3D500..0x3DFFF; laws council_backdrop_rect v3 / council_frame_clip / council_logo_x):
#   t_cw_clipdraw  the council's clip-not-clamp frame draw: Buffer_box_sprite's contract plus eax = the renderer.  The
#                  band-map renderers CLAMP their rect to the dest (thunk_clamp_frame_rect: B <= |H| - 1), so a frame
#                  running below the canvas had its bottom stroke squeezed onto the canvas's last rows; vanilla's
#                  Buffer_box_sprite clips it (measured at 1024: the last canvas row 394 holds the backdrop's side
#                  strokes and the ring's chamfer row, no horizontal stroke).  g > 16 and rect.B > |H|: the renderer
#                  draws into a canvas-wide scratch Buffer on the stack (W x rect.B, key 9) and Buffer_draw_2 (key 9,
#                  1:1) copies it onto the canvas, clipped there.  Every other case, and every other caller of the
#                  renderers, is a tail jump: byte-identical.
#   t_cw_bd2       the backdrop site 0x426B4E (was t_cw_backdrop): its L / R plus B = H + K, then t_cw_clipdraw with
#                  t_cw_hodf.
#   t_cw_ring2     the d5a0 ring site 0x426B7B (was t_bm_ho_hf): t_cw_clipdraw with t_bm_ho_hf.
#   t_cw_logox     the logo's Sprite_draw_2 E8 0x426105 (was thunk_cw_logo): x centred in the column interior (the
#                  portrait's rule), compensating thunk_cw_logo's own recentre.
#
# Data: g_cw_wts @0x3D1C0 (the weights, from scaling_laws -- never retyped), g_cw_mstate @0x3D1E0 (scratch).
#
# Usage: py assemble_council_mirror.py   -> prints the yaml symbol + content lines
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
REGION = (0x3D000, 0x3D6C0)                        # W5B's pcave2 region (its tail 0x3D6C0..0x3DFFF: W8T, 2026-10-27)
COUNCIL_W = 0x32C                                  # SL.COUNCIL_W (exec imm 0x427A14)
RAIL_RIGHT_OFF = 0x37                              # SL.RAIL_INNER_RIGHT_OFF
RAIL_L_OUTER, RAIL_L_INNER = 15, 8                 # SL.SE_RAIL_LEFT_STRIPS
CW_OUTER, CW_INNER, CW_STRIDE = 0xBF4, 0xC04, 0x20 # CouncilWin column seed sets (terranx.h)
BUF_W = 0x80                                       # Buffer +0x80 = the window canvas width (railscale's own read)

HELPERS = {     # name -> (offset, end of its slot)
    "t_cw_s1": (0x3D000, 0x3D040),
    # 0x3D040..0x3D0E0: t_cw_mirror v1's slot (v2 outgrew it; zeros, free)
    "t_cw_backdrop": (0x3D0E0, 0x3D140),
    "t_cw_chiphalf": (0x3D140, 0x3D180),
    "t_cw_hodf": (0x3D180, 0x3D1C0),
    "t_cw_mirror": (0x3D200, 0x3D340),          # v2 (audit-w5B): the weighted run, RELOCATED from 0x3D040
    # ---- 2026-10-25 wave-6 W6B (the council leftovers; region 0x3D400..0x3DFFF) ----
    "t_cw_inset": (0x3D400, 0x3D440),
    "t_cw_chipfix": (0x3D440, 0x3D4C0),         # v2 (W6B v2): the pad solved per column
    "t_cw_portx": (0x3D4C0, 0x3D500),           # W6B v2: the portrait centred in the column interior
    # ---- 2026-10-25 wave-7 W7B (region 0x3D500..0x3DFFF) ----
    "t_cw_clipdraw": (0x3D500, 0x3D5C0),        # clip-not-clamp: the frame drawn into a canvas-wide scratch, then blitted
    "t_cw_bd2": (0x3D5C0, 0x3D640),             # the backdrop: t_cw_backdrop's L / R + B = H + K, via t_cw_clipdraw
    "t_cw_ring2": (0x3D640, 0x3D660),           # the d5a0 ring via t_cw_clipdraw (renderer t_bm_ho_hf)
    "t_cw_logox": (0x3D660, 0x3D6C0),           # the logo centred like the portrait
}
# data -- g_cw_wts: per set {Wc0, Wc1, Wc2, sum}, the CUMULATIVE vanilla channel weights (scaling_laws.
# council_channel_weights; outer set at +0, inner at +16); g_cw_mstate: t_cw_mirror's scratch {S1, start, B, w}
DATA = {"g_cw_wts": (0x3D1C0, 32), "g_cw_mstate": (0x3D1E0, 16)}


def wts_bytes() -> bytes:
    import scaling_laws as SL
    out = b""
    for left in (SL.COUNCIL_OUTER_L, SL.COUNCIL_INNER_L):
        w = SL.council_channel_weights(left)
        out += b"".join(int.to_bytes(sum(w[:k + 1]), 4, "little") for k in range(3)) + int.to_bytes(sum(w), 4, "little")
    assert len(out) == DATA["g_cw_wts"][1]
    return out
# placeholders -> yaml symbols (abs32 operands and E8 targets carry the symbol in the shipped bytes)
PH = {
    0x11111111: "g_popup_scale_num",
    0x22222222: "Font_init",
    0x33333333: "Buffer_box_sprite",
    0x44444444: "thunk_box_thick_devfill",
    0x55555555: "t_si_chip",
    0x66666666: "thunk_cw_portrait",
    0x77777771: "Buffer_ctor",
    0x77777772: "Buffer_resize",
    0x77777773: "Buffer_fill_2",
    0x77777774: "Buffer_draw_2",
    0x77777775: "Buffer_dtor",
    0x77777776: "t_bm_ho_hf",
    0x77777777: "thunk_cw_logo",
}
for _n, (_o, _e) in HELPERS.items():
    PH[PCAVE2 + _o] = _n
for _n, (_o, _sz) in DATA.items():
    PH[PCAVE2 + _o] = _n
SYM = {v: k for k, v in PH.items()}
SITES = [   # (id, va, helper, was)
    ("CouncilWin_repaint.backdrop37", 0x426B4E, "t_cw_bd2", "thunk_cw_backdrop37"),   # W7B: was t_cw_backdrop
    ("CouncilWin_repaint.d5a0", 0x426B7B, "t_cw_ring2", "thunk_box_thick_hollow_flat"),   # W7B: was t_bm_ho_hf
    ("CouncilWin_draw_column.frame_d528", 0x425EE9, "t_cw_hodf", "thunk_box_thick_devfill"),
    ("CouncilWin_draw_column.d528_b", 0x426286, "t_cw_hodf", "thunk_box_thick_devfill"),
    ("CouncilWin_draw_column.chip_da00", 0x4261AA, "t_cw_chiphalf", "t_si_chip"),
    ("CouncilWin_draw_column.chip_d9d8", 0x4261D6, "t_cw_chiphalf", "t_si_chip"),
    ("CouncilWin_draw_column.chip_da28_a", 0x426203, "t_cw_chiphalf", "t_si_chip"),
    ("CouncilWin_draw_column.chip_da28_b", 0x426230, "t_cw_chiphalf", "t_si_chip"),
    ("CouncilWin_draw_column.chip_da28_c", 0x42625C, "t_cw_chiphalf", "t_si_chip"),
    ("CouncilWin_repaint.d528", 0x426BD2, "t_cw_hodf", "thunk_box_thick_devfill"),   # W6B: the ELECTED banner
    ("CouncilWin_draw_column.portrait_sd2", 0x425F3C, "t_cw_portx", "thunk_cw_portrait"),  # W6B v2: centred
    ("CouncilWin_draw_column.logo_sd2", 0x426105, "t_cw_logox", "thunk_cw_logo"),   # W7B: centred
]
# W6B block sites (id, va, original bytes, new template, note)
W6_BLOCKS = [
    ("CouncilWin_draw_column.frame_inset", 0x425EEE,
     "8B 45 E8 8B 55 F0 8B 4D EC 40 89 45 E8 8B 45 F4 4A 41 48 89 55 F0 89 45 F4",
     "E8 {rel32:t_cw_inset} EB 12" + " 90" * 18,
     "L+1 / T+1 / R-1 / B-1 after the column frame -> the stroke width fi (law council_frame_inset); ecx = T' for the "
     "store @0x425F17"),
    ("CouncilWin_draw_column.chip_fix", 0x426135, "89 4D E0 85 C0", "E8 {rel32:t_cw_chipfix}",
     "mov [ebp-0x20],ecx ; test eax,eax -> the chip dp(4) inside the column (law council_chip_rects v2); the thunk "
     "replays both (flags for the je @0x42613D)"),
]


def asm_s1() -> str:
    g = SYM["g_popup_scale_num"]
    return f"""
    push    ecx
    push    edx
    mov     ecx, dword ptr [{g:#x}]
    shl     eax, 4
    xor     edx, edx
    div     ecx
    sub     eax, {RAIL_RIGHT_OFF:#x}
    imul    eax, ecx
    sar     eax, 4
    imul    edx, ecx, {RAIL_L_OUTER}
    sar     edx, 4
    add     eax, edx
    imul    edx, ecx, {RAIL_L_INNER}
    sar     edx, 4
    add     eax, edx
    pop     edx
    pop     ecx
    ret
"""


def asm_mirror() -> str:
    g = SYM["g_popup_scale_num"]
    st = SYM["g_cw_mstate"]
    wo, wi = SYM["g_cw_wts"], SYM["g_cw_wts"] + 16
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jle     tail
    pushad
    mov     eax, {COUNCIL_W:#x}
    imul    eax, dword ptr [{g:#x}]
    sar     eax, 4
    call    {SYM['t_cw_s1']:#x}
    mov     dword ptr [{st:#x}], eax
    mov     ecx, dword ptr [{g:#x}]
    imul    edx, ecx, {RAIL_L_OUTER}
    sar     edx, 4
    imul    eax, ecx, {RAIL_L_INNER}
    sar     eax, 4
    add     edx, eax
    lea     eax, [ecx*4]
    sar     eax, 4
    add     edx, eax
    lea     eax, [ecx*2+15]
    sar     eax, 5
    add     edx, eax
    mov     dword ptr [{st + 4:#x}], edx
    lea     ebx, [esi+{CW_OUTER:#x}]
    mov     edi, {wo:#x}
    call    setm
    lea     ebx, [esi+{CW_INNER:#x}]
    mov     edi, {wi:#x}
    call    setm
    popad
tail:
    push    {SYM['Font_init']:#x}
    ret
setm:
    mov     ebp, dword ptr [{st:#x}]
    mov     eax, dword ptr [ebx+{3 * CW_STRIDE + 8:#x}]
    sub     eax, dword ptr [ebx+{3 * CW_STRIDE:#x}]
    mov     edx, ebp
    sub     edx, eax
    and     edx, 1
    add     eax, edx
    mov     edx, ebp
    sub     edx, eax
    sar     edx, 1
    mov     dword ptr [ebx+{3 * CW_STRIDE:#x}], edx
    add     eax, edx
    mov     dword ptr [ebx+{3 * CW_STRIDE + 8:#x}], eax
    mov     eax, dword ptr [ebx+8]
    sub     eax, dword ptr [ebx]
    mov     dword ptr [{st + 12:#x}], eax
    sub     edx, dword ptr [{st + 4:#x}]
    lea     eax, [eax+eax*2]
    sub     edx, eax
    mov     dword ptr [{st + 8:#x}], edx
    xor     ecx, ecx
lp:
    mov     eax, dword ptr [edi+ecx*4]
    imul    eax, dword ptr [{st + 8:#x}]
    add     eax, eax
    add     eax, dword ptr [edi+12]
    dec     eax
    push    ecx
    mov     ecx, dword ptr [edi+12]
    add     ecx, ecx
    cdq
    idiv    ecx
    pop     ecx
    mov     edx, dword ptr [{st + 12:#x}]
    imul    edx, ecx
    add     eax, edx
    add     eax, dword ptr [{st + 4:#x}]
    mov     edx, ecx
    shl     edx, 5
    mov     dword ptr [ebx+edx], eax
    add     eax, dword ptr [{st + 12:#x}]
    mov     dword ptr [ebx+edx+8], eax
    push    ecx
    neg     ecx
    add     ecx, 6
    shl     ecx, 5
    mov     edx, ebp
    sub     edx, eax
    mov     dword ptr [ebx+ecx], edx
    sub     eax, dword ptr [{st + 12:#x}]
    mov     edx, ebp
    sub     edx, eax
    mov     dword ptr [ebx+ecx+8], edx
    pop     ecx
    inc     ecx
    cmp     ecx, 3
    jl      lp
    ret
"""


def asm_backdrop() -> str:
    g = SYM["g_popup_scale_num"]
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jg      scaled
    push    {SYM['Buffer_box_sprite']:#x}
    ret
scaled:
    push    eax
    push    edx
    push    ebx
    mov     eax, dword ptr [ecx+{BUF_W:#x}]
    call    {SYM['t_cw_s1']:#x}
    mov     ebx, dword ptr [{g:#x}]
    imul    edx, ebx, {RAIL_L_OUTER}
    sar     edx, 4
    imul    ebx, ebx, {RAIL_L_INNER}
    sar     ebx, 4
    add     edx, ebx
    sub     eax, edx
    mov     ebx, dword ptr [esp+0x10]
    mov     dword ptr [ebx], edx
    mov     dword ptr [ebx+8], eax
    pop     ebx
    pop     edx
    pop     eax
    jmp     {SYM['t_cw_hodf']:#x}
"""


def asm_hodf() -> str:
    g = SYM["g_popup_scale_num"]
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jg      scaled
    push    {SYM['thunk_box_thick_devfill']:#x}
    ret
scaled:
    push    ebx
    mov     ebx, dword ptr [esp+8]
    dec     dword ptr [ebx+8]
    dec     dword ptr [ebx+0xC]
    push    dword ptr [esp+0xC]
    push    ebx
    call    {SYM['thunk_box_thick_devfill']:#x}
    inc     dword ptr [ebx+8]
    inc     dword ptr [ebx+0xC]
    pop     ebx
    ret     8
"""


def asm_chiphalf() -> str:
    g = SYM["g_popup_scale_num"]
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jg      scaled
    push    {SYM['t_si_chip']:#x}
    ret
scaled:
    push    ebx
    mov     ebx, dword ptr [esp+8]
    dec     dword ptr [ebx+8]
    dec     dword ptr [ebx+0xC]
    push    dword ptr [esp+0xC]
    push    ebx
    call    {SYM['t_si_chip']:#x}
    inc     dword ptr [ebx+8]
    inc     dword ptr [ebx+0xC]
    pop     ebx
    ret     8
"""


def asm_inset() -> str:
    """t_cw_inset (W6B): CALLed from 0x425EEE in place of the column painter's INC / DEC block (the jmp after the call
    skips the dead bytes to 0x425F07).  fi = council_frame_inset(g) (stroke_width = (2g+15)>>5 at g > 16, else 1):
    [ebp-0x18] L += fi, [ebp-0x10] R -= fi, [ebp-0xC] B -= fi, ecx = T + fi (the engine stores it @0x425F17),
    eax = B', edx = R' as the block left them; ebp is the painter's frame."""
    g = SYM["g_popup_scale_num"]
    return f"""
    mov     eax, dword ptr [{g:#x}]
    cmp     eax, 0x10
    jg      scaled
    mov     eax, 1
    jmp     go
scaled:
    lea     eax, [eax*2+15]
    sar     eax, 5
go:
    add     dword ptr [ebp-0x18], eax
    mov     edx, dword ptr [ebp-0x10]
    sub     edx, eax
    mov     dword ptr [ebp-0x10], edx
    mov     ecx, dword ptr [ebp-0x14]
    add     ecx, eax
    sub     dword ptr [ebp-0xc], eax
    mov     eax, dword ptr [ebp-0xc]
    ret
"""


def asm_chipfix() -> str:
    """t_cw_chipfix v2 (W6B v2): CALLed from 0x426135 (`mov [ebp-0x20],ecx; test eax,eax`).  Replays the store; g > 16:
    fi = (2g+15)>>5, the column width w = R' - L' + 2 fi (the inset rect [ebp-0x10] / [ebp-0x18]), the vanilla chip
    width vc = 112 if 16w > 109g (the governor's 120 column) else 90, the pad p = (2(16w - vc g) + 31) >> 6
    (= half_down(16w - vc g, 32), law council_chip_pad), d = p - dp(3) - fi (council_chip_fix_delta) -- chip L
    [ebp-0x28] += d, R [ebp-0x20] -= d, B [ebp-0x1C] -= d, T (edx, stored @0x42613A) -= d; eax (the vote cell),
    ebx, esi kept; then test eax,eax for the je @0x42613D.  ecx clobbered (dead: both paths reload it)."""
    import scaling_laws as SL
    g = SYM["g_popup_scale_num"]
    thr = (SL.COUNCIL_COL_W + SL.COUNCIL_CENTER_COL_W) // 2
    vc_small = SL.COUNCIL_COL_W - 2 * SL.COUNCIL_CHIP_PAD
    vc_big = SL.COUNCIL_CENTER_COL_W - 2 * SL.COUNCIL_CHIP_PAD
    return f"""
    mov     dword ptr [ebp-0x20], ecx
    cmp     dword ptr [{g:#x}], 0x10
    jle     done
    push    eax
    push    ebx
    push    esi
    mov     ebx, dword ptr [{g:#x}]
    lea     esi, [ebx*2+15]
    sar     esi, 5
    mov     eax, dword ptr [ebp-0x10]
    sub     eax, dword ptr [ebp-0x18]
    lea     eax, [eax+esi*2]
    shl     eax, 4
    imul    ecx, ebx, {thr}
    cmp     eax, ecx
    mov     ecx, {vc_small}
    jle     sm
    mov     ecx, {vc_big}
sm:
    imul    ecx, ebx
    sub     eax, ecx
    lea     eax, [eax*2+31]
    sar     eax, 6
    lea     ecx, [ebx+ebx*2]
    sar     ecx, 4
    sub     eax, ecx
    sub     eax, esi
    add     dword ptr [ebp-0x28], eax
    sub     dword ptr [ebp-0x20], eax
    sub     dword ptr [ebp-0x1c], eax
    sub     edx, eax
    pop     esi
    pop     ebx
    pop     eax
done:
    test    eax, eax
    ret
"""


def asm_portx() -> str:
    """t_cw_portx (W6B v2): the portrait's Sprite_draw_2 E8 @0x425F3C (was thunk_cw_portrait; ecx = the sprite, args
    dest, key, x, y, num, den).  g > 16: slack = (R' - L') - fl(w g/16) (w = the sprite canvas [ecx+0x18], R' / L' the
    inset rect in the painter's frame), x += slack / 2 truncated toward zero (council_portrait_xy: an odd px on the
    right); then push thunk_cw_portrait; ret with the call's stack as it came."""
    g = SYM["g_popup_scale_num"]
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jle     tail
    push    eax
    push    edx
    mov     eax, dword ptr [ecx+0x18]
    imul    eax, dword ptr [{g:#x}]
    sar     eax, 4
    mov     edx, dword ptr [ebp-0x10]
    sub     edx, dword ptr [ebp-0x18]
    sub     edx, eax
    mov     eax, edx
    shr     eax, 31
    add     edx, eax
    sar     edx, 1
    add     dword ptr [esp+0x14], edx
    pop     edx
    pop     eax
tail:
    push    {SYM['thunk_cw_portrait']:#x}
    ret
"""


def asm_clipdraw() -> str:
    """t_cw_clipdraw (W7B): the COUNCIL's clip-not-clamp frame draw.  Buffer_box_sprite's contract (ecx = the canvas,
    [esp+4] = rect, [esp+8] = params, RET 8) plus eax = the renderer to use.  The band-map renderers clamp their
    rect to the dest buffer (thunk_clamp_frame_rect: B <= |H| - 1), so a frame whose half-open B lies below the canvas
    is squeezed in and its bottom stroke lands on the canvas's last rows; vanilla's native Buffer_box_sprite CLIPS it.
    g > 16 and rect.B > |H| (the canvas, [ecx+0x84]): a scratch Buffer on the stack (Buffer_ctor, Buffer_resize to the
    canvas width x rect.B, Buffer_fill_2 with the key 9) takes the renderer's draw at the same coordinates -- whole,
    nothing clamped, the stripe phase on the same rows -- and Buffer_draw_2 (key 9, 1:1, at 0, 0) copies it onto the
    canvas, which clips at the canvas's clip rect (the repaint set it to the canvas); Buffer_dtor.  Else (and at
    g <= 16) a tail jump to the renderer: byte-identical to calling it.  ebx / esi / edi / ebp kept."""
    g = SYM["g_popup_scale_num"]
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jle     direct0
    push    ebp
    mov     ebp, esp
    push    ebx
    push    esi
    push    edi
    mov     ebx, eax
    mov     esi, dword ptr [ebp+8]
    mov     edi, ecx
    mov     eax, dword ptr [ecx+0x84]
    cdq
    xor     eax, edx
    sub     eax, edx
    cmp     dword ptr [esi+0xc], eax
    jle     direct
    sub     esp, 0x600
    lea     ecx, [ebp-0x60c]
    call    {SYM['Buffer_ctor']:#x}
    push    dword ptr [esi+0xc]
    push    dword ptr [edi+0x80]
    lea     ecx, [ebp-0x60c]
    call    {SYM['Buffer_resize']:#x}
    push    9
    lea     ecx, [ebp-0x60c]
    call    {SYM['Buffer_fill_2']:#x}
    push    dword ptr [ebp+0xc]
    push    esi
    lea     ecx, [ebp-0x60c]
    call    ebx
    push    1
    push    1
    push    0
    push    0
    push    9
    push    edi
    lea     ecx, [ebp-0x60c]
    call    {SYM['Buffer_draw_2']:#x}
    lea     ecx, [ebp-0x60c]
    call    {SYM['Buffer_dtor']:#x}
    add     esp, 0x600
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret     8
direct:
    mov     ecx, edi
    mov     eax, ebx
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
direct0:
    jmp     eax
"""


def asm_bd2() -> str:
    """t_cw_bd2 (W7B; the 0x426B4E site): t_cw_backdrop's rect -- L = the rail extent, R = the inner right rail x --
    plus B = H + K (rect.B + K - 1: vanilla's H + 1 overdraw is the 1-px stroke below the canvas, law
    council_backdrop_rect v3), in place (the ring is built from it); then t_cw_clipdraw with the renderer t_cw_hodf
    (half-open devfill).  g <= 16: tail Buffer_box_sprite."""
    g = SYM["g_popup_scale_num"]
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jg      scaled
    push    {SYM['Buffer_box_sprite']:#x}
    ret
scaled:
    push    eax
    push    edx
    push    ebx
    mov     eax, dword ptr [ecx+{BUF_W:#x}]
    call    {SYM['t_cw_s1']:#x}
    mov     ebx, dword ptr [{g:#x}]
    imul    edx, ebx, {RAIL_L_OUTER}
    sar     edx, 4
    imul    ebx, ebx, {RAIL_L_INNER}
    sar     ebx, 4
    add     edx, ebx
    sub     eax, edx
    mov     ebx, dword ptr [esp+0x10]
    mov     dword ptr [ebx], edx
    mov     dword ptr [ebx+8], eax
    mov     eax, dword ptr [{g:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5
    dec     eax
    add     dword ptr [ebx+0xc], eax
    pop     ebx
    pop     edx
    pop     eax
    mov     eax, {SYM['t_cw_hodf']:#x}
    jmp     {SYM['t_cw_clipdraw']:#x}
"""


def asm_ring2() -> str:
    """t_cw_ring2 (W7B; the 0x426B7B site, was t_bm_ho_hf): t_cw_clipdraw with the renderer t_bm_ho_hf (the half-open
    hollow_flat) -- the ring inherits the backdrop's B, so its bottom stroke is clipped below the canvas too."""
    return f"""
    mov     eax, {SYM['t_bm_ho_hf']:#x}
    jmp     {SYM['t_cw_clipdraw']:#x}
"""


def asm_logox() -> str:
    """t_cw_logox (W7B; the logo's Sprite_draw_2 E8 @0x426105, was thunk_cw_logo).  The engine centres the logo with
    its NATIVE canvas width and thunk_cw_logo then adds (cw - dp(cw)) >> 1: two floors, the logo up to 2 px off centre
    (real 86-wide canvas: 4K 12 | 14 in the side columns, vanilla 5 | 5).  g > 16: x := L' + ((R' - L') - dp(cw)) >> 1
    (law council_logo_x: the slack split, an odd px on the right) minus that same (cw - dp(cw)) >> 1 thunk_cw_logo
    adds back; L' / R' = the painter's inset rect [ebp-0x18] / [ebp-0x10], cw = [ecx+0x18].  Then push thunk_cw_logo;
    ret with the call's stack.  g <= 16: untouched."""
    g = SYM["g_popup_scale_num"]
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jle     tail
    push    eax
    push    edx
    mov     eax, dword ptr [ecx+0x18]
    mov     edx, eax
    imul    edx, dword ptr [{g:#x}]
    sar     edx, 4
    sub     eax, edx
    sar     eax, 1
    push    eax
    mov     eax, dword ptr [ebp-0x10]
    sub     eax, dword ptr [ebp-0x18]
    sub     eax, edx
    sar     eax, 1
    add     eax, dword ptr [ebp-0x18]
    pop     edx
    sub     eax, edx
    mov     dword ptr [esp+0x14], eax
    pop     edx
    pop     eax
tail:
    push    {SYM['thunk_cw_logo']:#x}
    ret
"""


ASM = {"t_cw_s1": asm_s1, "t_cw_mirror": asm_mirror, "t_cw_backdrop": asm_backdrop, "t_cw_chiphalf": asm_chiphalf,
       "t_cw_hodf": asm_hodf, "t_cw_inset": asm_inset, "t_cw_chipfix": asm_chipfix, "t_cw_portx": asm_portx,
       "t_cw_clipdraw": asm_clipdraw, "t_cw_bd2": asm_bd2, "t_cw_ring2": asm_ring2, "t_cw_logox": asm_logox}
_cs = Cs(CS_ARCH_X86, CS_MODE_32)
_cs.detail = True


def assemble(name: str) -> bytes:
    """The helper's bytes at its VA with the placeholder symbol VAs (templated back by template())."""
    off, end = HELPERS[name]
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(ASM[name](), PCAVE2 + off)[0])
    assert off + len(b) <= end and REGION[0] <= off and end <= REGION[1], (name, len(b))
    assert sum(i.size for i in _cs.disasm(b, PCAVE2 + off)) == len(b), "capstone round-trip gap"
    return b


def template(name: str) -> str:
    """The yaml bytes: E8 to a symbol -> {rel32:<sym>}; an imm32 / disp32 equal to a symbol -> {abs32:<sym>}; every
    other branch literal (local labels; the patcher takes {rel32:} only after E8)."""
    off, _end = HELPERS[name]
    va = PCAVE2 + off
    b = assemble(name)
    out = []
    for ins in _cs.disasm(b, va):
        raw = bytes(ins.bytes)
        repl = []
        if ins.mnemonic == "call" and ins.size == 5 and ins.operands[0].type == X86_OP_IMM:
            tgt = ins.operands[0].imm & 0xFFFFFFFF
            if tgt in PH:
                repl.append((1, "{rel32:" + PH[tgt] + "}"))
        elif ins.mnemonic.startswith("j") or ins.mnemonic == "call":
            pass
        else:
            for op in ins.operands:
                if op.type == X86_OP_IMM and ins.imm_size == 4 and (op.imm & 0xFFFFFFFF) in PH:
                    repl.append((ins.imm_offset, "{abs32:" + PH[op.imm & 0xFFFFFFFF] + "}"))
                elif op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0 and (op.mem.disp & 0xFFFFFFFF) in PH:
                    repl.append((ins.disp_offset, "{abs32:" + PH[op.mem.disp & 0xFFFFFFFF] + "}"))
        pos = 0
        for o, tok in sorted(repl):
            out.extend(f"{x:02X}" for x in raw[pos:o])
            out.append(tok)
            pos = o + 4
        out.extend(f"{x:02X}" for x in raw[pos:])
    tpl = " ".join(out)
    lits = bytes.fromhex("".join(t for t in tpl.split() if not t.startswith("{")))
    assert not any(k.to_bytes(4, "little") in lits for k in PH if k < PCAVE2), tpl   # no placeholder left literal
    return tpl


def main() -> int:
    for name, (off, end) in HELPERS.items():
        b = assemble(name)
        print(f"; {name} {len(b)} B @{off:#x}..{off + len(b):#x} (slot to {end:#x})")
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    w = wts_bytes()
    for name, (off, size) in DATA.items():
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    print(f"      - id: g_cw_wts\n        offset: {DATA['g_cw_wts'][0]:#x}\n        bytes: \"{' '.join(f'{x:02X}' for x in w)}\"")
    for sid, va, helper, was in SITES:
        print(f"; site {sid} @{va:#x}: new_bytes \"E8 {{rel32:{helper}}}\"   # was {{rel32:{was}}}")
    for sid, va, orig, new, note in W6_BLOCKS:
        print(f"; W6B block {sid} @{va:#x} len {len(orig.split())}: {orig} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
