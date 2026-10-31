# Regenerates the W3B rail-scrollbar helpers in pcave2 0x39000..0x3AFFF (2026-10-25 wave-3 W3B, the user-approved
# "rail scrollbar rework" = fix 20 item D; laws scaling_laws.rail_col_map / rail_bar_inset / rail_line_spans /
# rail_grip_span / rail_blit_rows / rail_arrow_col_map; guards tests/test_rail_sym_asm_parity.py,
# tests/test_rail_sbstrip_abut_asm.py and tests/test_scaling_rail_sym_e2e.py).
#
# The rail column, its bar, the bar's arrow plates and its thumb grip become ONE symmetric assembly (g > 16 only):
#
#   t_rsb_cmap     CALL helper, eax = cw (the window canvas width) -> eax = Wc = rail_wall_off(cw) (the visible column)
#                  and the byte table g_rsb_cmap[0..Wc) = rail_col_map(cw, g), zone by zone on the LEFT half: the band
#                  (axis_map_chrome's: the cyan line = the chrome cell 3, K wide, cells 0..2 share b - K), the channel
#                  cells 4..6 (distribute the grip offset), the plate cells 7..24 on the grip span (t_rsb_mnn); the
#                  right half is the mirror (31 - m[Wc - 1 - j]).  Every other register is kept.
#   t_rsb_mnn      CALL helper eax = k, ebx = src_n, ecx = dst_n -> eax = mirror_nn_src(k, src_n, dst_n) (the left
#                  half and an odd centre centre-sampled, the right half the mirror); every other register kept.
#   t_rsb_wspan    CALL helper eax = spr_w, ecx = inner -> eax = w, ecx = off = rail_grip_span(inner, spr_w, g) (v3: the
#                  inner-parity value NEAREST spr_w g/16, an exact tie rounding down); every other register kept.
#   t_rsb_lay      CALL helper eax = Wc -> eax = b, ecx = w, edx = off = rail_layout_zones(Wc, g) (v3: the band depth
#                  minimising the worst zone deviation from vanilla x g/16; ties: smaller sum, nearest 4 Wc / 32,
#                  smaller b); ebx / esi / edi / ebp kept.
#   t_rsb_blit     Buffer_draw_2 drop-in (thiscall ecx = the native strip, args dest, key, x, y, num, den; RET 0x18)
#                  at thunk_rail_bake's strip blit: columns [0, Wc) from g_rsb_cmap, rows on the ENGINE's own map
#                  (engine_scale_runs at g/16, fl(h*g/16) rows clipped at the canvas bottom -- rail_blit_rows, measured
#                  on the real Buffer_draw_2), keyed.  Wc outside 1..256: tail-jumps the engine blit unchanged.
#   t_rsb_bar      CALL helper for thunk_rail_sbfit v5, eax = cw -> eax = S + b (the bar x), ecx = Wc - 2b (its w):
#                  the bar is the channel between the two lines (rail_layout v4).  edx and the rest kept.
#   t_rsb_israil   CALL helper, eax = a ScrollBar* -> ZF = 1 iff it is a rail-family bar: the ProdPicker static
#                  0x6AF164, the ReportWin static 0x882584, FileDlg+0x3DD8 of its parent FileDlg (vtbl 0x669EC8),
#                  PartPicker+0xA14 of its parent Design Workshop PartPicker (vtbl 0x66B2B8; v4, W9C F53 2026-10-27), or
#                  Popup+0x3230 of its parent Popup ([vtbl+4] == Popup_show).  Every register kept.
#   t_rsb_grip     thunk_sb_thumb's armed tail target (was t_sbt_grip): for a rail bar (esi = the ScrollBar in
#                  ScrollBar_draw) the grip is re-laid from the thumb rect on ScrollBar_draw's frame ([esp+0x28..]):
#                  w = rail_grip_span(R - L, canvas w, g), x = L + (R - L - w)/2, h = sh w / sw, y centred the same
#                  way; the args become (dest, key, x, y, w, h) -> t_rsb_gripdraw.  Any other bar, or a grip that is
#                  not a plain memory sprite (no pcBits, draw offsets, blit != canvas dims) -> t_nrs_grip (W10S F56,
#                  assemble_nonrail_sb.py: an armed non-rail ScrollBar on the same span per axis; else t_sbt_grip).
#   t_rsb_gripdraw the grip drawn w x h by t_rsb_mnn on both axes (mirror-exact: plain centre sampling -- the engine's
#                  and thunk_sprite_scale_nn's -- breaks the bevel's symmetry on an exact tie, e.g. w 27 / 33),
#                  keyed and clipped to the dest, then t_sbt_grip's own pair detect + restripe_core over exactly the
#                  drawn rect.  RET 0x18.
#   t_rsb_zoom     the tail of W2D's t_btn_edgeprobe, which sits on thunk_btn_2dscale's zoom call (the chain: 2dscale ->
#                  t_btn_edgeprobe -> t_rsb_zoom -> thunk_btn_bandstripe; KSB contract RET 0x2C): for an arrow of a
#                  rail bar (esi == bar+0xAAC / +0x15F8) our own in-place zoom -- the native plate columns [f0, f1)
#                  (found by scanning the native render for non-key columns) land on rail_grip_span(aw, f1 - f0, g)
#                  by t_rsb_mnn, the margins are key 9, the rows are StretchBlt's centre-NN (rail_arrow_col_map);
#                  a guard failure tail-jumps thunk_btn_bandstripe, anything else t_nrs_zoom (W10S F56: an armed non-rail
#                  ScrollBar's arrow on the same span on both axes; else thunk_btn_bandstripe), the stack untouched.
#
# Cells (BSS, zero-init; non-reentrant UI draw): g_rsb_cmap 256 B, g_rsb_ct 256 B, g_rsb_row 256 B.
#
# Usage: py assemble_rail_sym.py   -> prints the yaml symbol + content lines
from __future__ import annotations

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
REGION = (0x39000, 0x3B000)                        # W3B's pcave2 region

# ---- sentinels: abs32 operands and call / push targets resolved to yaml tokens --------------------------------------
SENT = {
    "g_popup_scale_num": 0x7EAD0100,
    "thunk_rail_walloff": 0x7EAD0200,
    "thunk_rail_sx": 0x7EAD0300,
    "thunk_sprite_scale_nn": 0x7EAD0400,
    "restripe_core": 0x7EAD0500,
    "thunk_btn_bandstripe": 0x7EAD0600,
    "t_sbt_grip": 0x7EAD0700,
    "Buffer_draw_2": 0x7EAD0800,
    "t_nrs_grip": 0x7EAD0900,      # W10S F56: the non-rail tails (assemble_nonrail_sb.py)
    "t_nrs_zoom": 0x7EAD0A00,
}

# ---- layout (offset, end of slot) -----------------------------------------------------------------------------------
LAYOUT = {
    "t_rsb_cmap": (0x39000, 0x39200),
    "t_rsb_blit": (0x39200, 0x39400),
    "t_rsb_bar": (0x39400, 0x39440),
    "t_rsb_israil": (0x39440, 0x394C0),
    "t_rsb_grip": (0x394C0, 0x39600),
    "t_rsb_gripdraw": (0x39600, 0x39800),
    "t_rsb_zoom": (0x39800, 0x39C00),
    "t_rsb_mnn": (0x39C00, 0x39C80),
    "t_rsb_wspan": (0x39C80, 0x39CC0),
    "t_rsb_lay": (0x39D00, 0x39F00),
}
CELLS = {"g_rsb_cmap": (0x3A000, 0x100), "g_rsb_ct": (0x3A100, 0x100), "g_rsb_row": (0x3A200, 0x100)}
ORDER = list(LAYOUT)

PICKER_SB = 0x6AF164           # ProdPicker+0x7120 (static)
REPORT_SB = 0x882584           # ReportWin+0xC10C (static)
FILEDLG_VTBL = 0x669EC8        # FileDlg vtable; its rail bar is FileDlg+0x3DD8
POPUP_SHOW = 0x404920          # [Popup vtbl+4]; the popup family's rail bar is Popup+0x3230
SB_UP, SB_DN = 0xAAC, 0x15F8   # the two arrow FlatButtons inside a ScrollBar
PARTPICKER_VTBL, PARTPICKER_SB = 0x66B2B8, 0xA14   # the Design Workshop PartPicker's bar (W9C F53; RAIL_FAMILY_VTBL_BARS)
KEY = 9


def va(name: str) -> int:
    if name in LAYOUT:
        return PCAVE2 + LAYOUT[name][0]
    if name in CELLS:
        return PCAVE2 + CELLS[name][0]
    return SENT[name]


# NO comments inside the asm text (keystone hangs on `;`); the notes live in the docstrings.

def asm_cmap() -> str:
    """eax = cw -> eax = Wc, g_rsb_cmap[j] = rail_col_map(cw, g)[j].  Frame: ebp = Wc, esi = b, ebx = K, ecx = rest =
    b - K, edi = j.  The near cell of jj: the i in 0..2 with cum(i) <= jj < cum(i+1), cum(i) = (2*i*rest + 2) / 6
    (= half_down(i*rest, 3)), or 3 when jj >= rest.  b, w and off come from t_rsb_lay (rail_layout_zones), [esp] =
    w: the channel cells 4 + i over [b, b + off) (cum over off / 3 the same way), the plate 7 + mirror_nn(k, 18, w)
    over [b + off, b + off + w), and the mirror of [0, b + off)."""
    G, T = va("g_popup_scale_num"), va("g_rsb_cmap")
    return f"""
    push ebx
    push ecx
    push edx
    push esi
    push edi
    push ebp
    call {va("thunk_rail_walloff"):#x}
    mov ebp, eax
    call {va("t_rsb_lay"):#x}
    mov esi, eax
    push ecx
    push edx
    mov eax, dword ptr [{G:#x}]
    lea ebx, [eax*2+15]
    sar ebx, 5
    mov ecx, esi
    sub ecx, ebx
    xor edi, edi
near_j:
    cmp edi, esi
    jge chan_init
    mov edx, 3
    cmp edi, ecx
    jge near_put
    xor edx, edx
near_cell:
    cmp edx, 2
    jge near_put
    lea eax, [edx+1]
    imul eax, ecx
    lea eax, [eax*2+2]
    push edx
    push ecx
    mov ecx, 6
    cdq
    idiv ecx
    pop ecx
    pop edx
    cmp edi, eax
    jl near_put
    inc edx
    jmp near_cell
near_put:
    mov byte ptr [{T:#x}+edi], dl
    inc edi
    jmp near_j
chan_init:
    pop ecx
    xor edi, edi
chan_j:
    cmp edi, ecx
    jge plate_init
    xor edx, edx
chan_cell:
    cmp edx, 2
    jge chan_put
    lea eax, [edx+1]
    imul eax, ecx
    lea eax, [eax*2+2]
    push edx
    push ecx
    mov ecx, 6
    cdq
    idiv ecx
    pop ecx
    pop edx
    cmp edi, eax
    jl chan_put
    inc edx
    jmp chan_cell
chan_put:
    add dl, 4
    lea eax, [esi+edi]
    mov byte ptr [{T:#x}+eax], dl
    inc edi
    jmp chan_j
plate_init:
    lea edx, [esi+ecx]
    push ecx
    mov ecx, dword ptr [esp+4]
    mov ebx, 18
    xor edi, edi
plate_k:
    cmp edi, ecx
    jge mirror_init
    mov eax, edi
    call {va("t_rsb_mnn"):#x}
    add al, 7
    mov byte ptr [{T:#x}+edx+edi], al
    inc edi
    jmp plate_k
mirror_init:
    pop ecx
    pop eax
    xor edi, edi
mirror_i:
    cmp edi, edx
    jge cdone
    mov al, byte ptr [{T:#x}+edi]
    neg al
    add al, 31
    mov ebx, ebp
    dec ebx
    sub ebx, edi
    mov byte ptr [{T:#x}+ebx], al
    inc edi
    jmp mirror_i
cdone:
    mov eax, ebp
    pop ebp
    pop edi
    pop esi
    pop edx
    pop ecx
    pop ebx
    ret
"""


def asm_mnn() -> str:
    """eax = k, ebx = src_n, ecx = dst_n -> eax = mirror_nn_src(k, src_n, dst_n): m = dst - 1 - k; k <= m: the
    centre sample ((2k+1) src) / (2 dst); else src - 1 - that of m.  edx / esi saved; every register but eax kept."""
    return """
    push edx
    push esi
    mov esi, ecx
    dec esi
    sub esi, eax
    cmp eax, esi
    jle mleft
    mov eax, esi
    lea eax, [eax*2+1]
    imul eax, ebx
    lea esi, [ecx+ecx]
    cdq
    idiv esi
    neg eax
    add eax, ebx
    dec eax
    jmp mout
mleft:
    lea eax, [eax*2+1]
    imul eax, ebx
    lea esi, [ecx+ecx]
    cdq
    idiv esi
mout:
    pop esi
    pop edx
    ret
"""


def asm_blit() -> str:
    """Frame (pushad; ebp = esp): args +0x24 dest, +0x28 key, +0x2C x, +0x30 y.  Locals: -4 Wc, -8 rows left, -0xC d
    (dest row ptr), -0x10 s (src row ptr), -0x14 q = g >> 4, -0x18 err, -0x1C 2r, -0x20 src stride, -0x24 dest stride,
    -0x28 run.  The run table is Sprite_fill_scaling_table's at g/16 (thunk_rail_nncol's port): err = r - 32 (+ g when
    q is odd), per source row err += 2r, run = q (+1 and err -= 32 when err > 0)."""
    G, T = va("g_popup_scale_num"), va("g_rsb_cmap")
    return f"""
    pushad
    mov ebp, esp
    sub esp, 0x30
    mov esi, ecx
    mov edi, dword ptr [ebp+0x24]
    mov eax, dword ptr [edi+0x80]
    call {va("t_rsb_cmap"):#x}
    test eax, eax
    jle engine
    cmp eax, 0x100
    jg engine
    mov dword ptr [ebp-4], eax
    mov eax, dword ptr [esi+0x84]
    neg eax
    imul eax, dword ptr [{G:#x}]
    sar eax, 4
    mov edx, dword ptr [edi+0x84]
    neg edx
    sub edx, dword ptr [ebp+0x30]
    cmp eax, edx
    jle rows_ok
    mov eax, edx
rows_ok:
    test eax, eax
    jle done
    mov dword ptr [ebp-8], eax
    mov eax, dword ptr [esi+0x4A8]
    mov dword ptr [ebp-0x20], eax
    mov eax, dword ptr [edi+0x4A8]
    mov dword ptr [ebp-0x24], eax
    mov eax, dword ptr [ebp+0x30]
    imul eax, dword ptr [ebp-0x24]
    add eax, dword ptr [edi+0x54]
    add eax, dword ptr [ebp+0x2C]
    mov dword ptr [ebp-0xC], eax
    mov eax, dword ptr [esi+0x54]
    mov dword ptr [ebp-0x10], eax
    mov eax, dword ptr [{G:#x}]
    mov ecx, eax
    sar ecx, 4
    mov dword ptr [ebp-0x14], ecx
    and eax, 0xF
    lea edx, [eax-0x20]
    test cl, 1
    je even_q
    add edx, dword ptr [{G:#x}]
even_q:
    mov dword ptr [ebp-0x18], edx
    add eax, eax
    mov dword ptr [ebp-0x1C], eax
    mov bl, byte ptr [ebp+0x28]
src_row:
    mov eax, dword ptr [ebp-0x18]
    add eax, dword ptr [ebp-0x1C]
    mov ecx, dword ptr [ebp-0x14]
    test eax, eax
    jle no_extra
    inc ecx
    sub eax, 0x20
no_extra:
    mov dword ptr [ebp-0x18], eax
    mov dword ptr [ebp-0x28], ecx
dst_row:
    cmp dword ptr [ebp-0x28], 0
    je next_src
    mov esi, dword ptr [ebp-0x10]
    mov edi, dword ptr [ebp-0xC]
    mov ecx, dword ptr [ebp-4]
col:
    dec ecx
    js col_done
    movzx eax, byte ptr [{T:#x}+ecx]
    mov dl, byte ptr [esi+eax]
    cmp dl, bl
    je col
    mov byte ptr [edi+ecx], dl
    jmp col
col_done:
    mov eax, dword ptr [ebp-0x24]
    add dword ptr [ebp-0xC], eax
    dec dword ptr [ebp-8]
    je done
    dec dword ptr [ebp-0x28]
    jmp dst_row
next_src:
    mov eax, dword ptr [ebp-0x20]
    add dword ptr [ebp-0x10], eax
    jmp src_row
done:
    mov esp, ebp
    popad
    ret 0x18
engine:
    mov esp, ebp
    popad
    push {va("Buffer_draw_2"):#x}
    ret
"""


def asm_bar() -> str:
    """eax = cw -> eax = S + b, ecx = Wc - 2b (b = rail_layout_zones' band depth, t_rsb_lay).  edx kept."""
    return f"""
    push edx
    push eax
    call {va("thunk_rail_sx"):#x}
    mov edx, eax
    pop eax
    call {va("thunk_rail_walloff"):#x}
    push edx
    push eax
    call {va("t_rsb_lay"):#x}
    pop ecx
    sub ecx, eax
    sub ecx, eax
    pop edx
    add eax, edx
    pop edx
    ret
"""


def asm_israil() -> str:
    """eax = ScrollBar* -> ZF.  The parent is Win +0xC4; a FileDlg / the DW PartPicker (v4, W9C F53: the picker runs
    the rail recipe through thunk_dw_pk_enter, so its plates and grip belong on rail_grip_span) are keyed on their
    vtables, a Popup on [vtbl+4], the ProdPicker / ReportWin bars on their static addresses.  v3 (audit W3B LOW 3): AND the bar is RAIL-FITTED -- its
    client width [+0x4C4] is the law's bar width for its parent's canvas ([parent+0x4C4], thunk_rail_sbfit's cw;
    t_rsb_bar), so an unfitted bar of a family window (the 24-px bar before the fit) keeps today's paths."""
    return f"""
    push ecx
    push edx
    mov ecx, dword ptr [eax+0xC4]
    test ecx, ecx
    je no_fam
    cmp eax, {PICKER_SB:#x}
    je fam
    cmp eax, {REPORT_SB:#x}
    je fam
    lea edx, [ecx+{PARTPICKER_SB:#x}]
    cmp eax, edx
    jne not_pp
    cmp dword ptr [ecx], {PARTPICKER_VTBL:#x}
    je fam
not_pp:
    lea edx, [ecx+0x3DD8]
    cmp eax, edx
    jne not_fd
    cmp dword ptr [ecx], {FILEDLG_VTBL:#x}
    je fam
not_fd:
    lea edx, [ecx+0x3230]
    cmp eax, edx
    jne no_fam
    mov edx, dword ptr [ecx]
    cmp dword ptr [edx+4], {POPUP_SHOW:#x}
    jne no_fam
fam:
    push eax
    mov eax, dword ptr [ecx+0x4C4]
    call {va("t_rsb_bar"):#x}
    pop eax
    cmp dword ptr [eax+0x4C4], ecx
    pop edx
    pop ecx
    ret
no_fam:
    test esp, esp
    pop edx
    pop ecx
    ret
"""


def asm_grip() -> str:
    """Entry = t_sbt_grip's: [esp] ScrollBar_draw's return, +4 dest, +8 key, +0xC x, +0x10 y, +0x14 num, +0x18 den,
    ecx = the grip Sprite, esi = the ScrollBar; ScrollBar_draw's thumb rect L/T/R/B at [esp+0x28/0x2C/0x30/0x34].
    After pushad (ebp = esp): args +0x24.., rect +0x48/+0x4C/+0x50/+0x54.  Only a plain memory sprite is re-laid
    (pcBits set, no draw offsets, blit dims == canvas dims, <= 256 wide) -- the grip is; anything else keeps today's
    path.  Out: x, y, w (the num slot), h (the den slot) -> t_rsb_gripdraw."""
    G = va("g_popup_scale_num")
    return f"""
    push eax
    mov eax, esi
    call {va("t_rsb_israil"):#x}
    pop eax
    jne pass_on
    pushad
    mov ebp, esp
    cmp dword ptr [ecx+4], 0
    je refuse
    cmp dword ptr [ecx+0x20], 0
    jne refuse
    cmp dword ptr [ecx+0x24], 0
    jne refuse
    mov ebx, dword ptr [ecx+0x18]
    cmp ebx, dword ptr [ecx+0x10]
    jne refuse
    mov eax, dword ptr [ecx+0x1C]
    cmp eax, dword ptr [ecx+0x14]
    jne refuse
    test eax, eax
    jle refuse
    test ebx, ebx
    jle refuse
    cmp ebx, 0x100
    jg refuse
    push ecx
    mov eax, ebx
    mov ecx, dword ptr [ebp+0x50]
    sub ecx, dword ptr [ebp+0x48]
    call {va("t_rsb_wspan"):#x}
    mov edi, ecx
    pop ecx
    test eax, eax
    jle refuse
    test edi, edi
    js refuse
    cmp eax, 0x100
    jg refuse
    add edi, dword ptr [ebp+0x48]
    mov dword ptr [ebp+0x2C], edi
    mov dword ptr [ebp+0x34], eax
    imul eax, dword ptr [ecx+0x1C]
    xor edx, edx
    div ebx
    mov dword ptr [ebp+0x38], eax
    mov edx, dword ptr [ebp+0x54]
    sub edx, dword ptr [ebp+0x4C]
    sub edx, eax
    sar edx, 1
    add edx, dword ptr [ebp+0x4C]
    mov dword ptr [ebp+0x30], edx
    popad
    push {va("t_rsb_gripdraw"):#x}
    ret
refuse:
    popad
pass_on:
    push {va("t_nrs_grip"):#x}
    ret
"""


def asm_gripdraw() -> str:
    """Entry: ecx = the grip Sprite, [esp] ret, +4 dest, +8 key, +0xC x, +0x10 y, +0x14 w, +0x18 h (t_rsb_grip's).
    pushad; ebp = esp: +0x24 dest, +0x28 key, +0x2C x, +0x30 y, +0x34 w, +0x38 h.  Locals: -4 pitch, -8 dest row,
    -0xC src row.  g_rsb_ct[c] = mirror_nn(c, sw, w); per dest row r (clipped to [0, H)): sr = mirror_nn(r, sh, h);
    per c (clipped to [0, W)): a non-key source pixel is written.  Then t_sbt_grip's tail verbatim in meaning: the pair
    = the first A,B,A,B window in the sprite's mid column (top = the even-row member), restripe_core over (x, y, w, h)
    unless x / y < 0 or the rect passes the buffer's last row.  RET 0x18."""
    CT = va("g_rsb_ct")
    MNN = va("t_rsb_mnn")
    return f"""
    pushad
    mov ebp, esp
    sub esp, 0x10
    mov esi, ecx
    mov edi, dword ptr [ebp+0x24]
    mov ebx, dword ptr [esi+0x10]
    mov ecx, dword ptr [ebp+0x34]
    xor edx, edx
gcol:
    cmp edx, ecx
    jge gtab_done
    mov eax, edx
    call {MNN:#x}
    mov byte ptr [{CT:#x}+edx], al
    inc edx
    jmp gcol
gtab_done:
    mov eax, dword ptr [esi+0xC]
    test eax, eax
    jg gpitch_ok
    mov eax, dword ptr [esi+0x10]
gpitch_ok:
    mov dword ptr [ebp-4], eax
    xor edx, edx
grow:
    cmp edx, dword ptr [ebp+0x38]
    jge gdrawn
    mov eax, dword ptr [ebp+0x30]
    add eax, edx
    js gnext
    mov ecx, dword ptr [edi+0x84]
    neg ecx
    cmp eax, ecx
    jge gnext
    imul eax, dword ptr [edi+0x4A8]
    add eax, dword ptr [edi+0x54]
    mov dword ptr [ebp-8], eax
    mov eax, edx
    mov ebx, dword ptr [esi+0x14]
    mov ecx, dword ptr [ebp+0x38]
    call {MNN:#x}
    imul eax, dword ptr [ebp-4]
    add eax, dword ptr [esi+4]
    mov dword ptr [ebp-0xC], eax
    xor ecx, ecx
gpx:
    cmp ecx, dword ptr [ebp+0x34]
    jge gnext
    mov eax, dword ptr [ebp+0x2C]
    add eax, ecx
    js gskip
    cmp eax, dword ptr [edi+0x80]
    jge gskip
    movzx ebx, byte ptr [{CT:#x}+ecx]
    add ebx, dword ptr [ebp-0xC]
    mov bl, byte ptr [ebx]
    cmp bl, byte ptr [ebp+0x28]
    je gskip
    add eax, dword ptr [ebp-8]
    mov byte ptr [eax], bl
gskip:
    inc ecx
    jmp gpx
gnext:
    inc edx
    jmp grow
gdrawn:
    mov edi, dword ptr [esi+4]
    mov eax, dword ptr [esi+0x10]
    mov ecx, dword ptr [esi+0xC]
    test ecx, ecx
    jg gp2
    mov ecx, eax
gp2:
    shr eax, 1
    add edi, eax
    mov ebx, dword ptr [esi+0x14]
    sub ebx, 3
    jle gdone
gscan:
    movzx eax, byte ptr [edi]
    movzx edx, byte ptr [edi+ecx]
    add edi, ecx
    cmp al, dl
    je gscan_next
    cmp al, byte ptr [edi+ecx]
    jne gscan_next
    cmp dl, byte ptr [edi+ecx*2]
    je gfound
gscan_next:
    dec ebx
    jnz gscan
    jmp gdone
gfound:
    mov ecx, dword ptr [esi+0x14]
    sub ecx, ebx
    test cl, 1
    jnz gtop
    xchg eax, edx
gtop:
    push eax
    push edx
    push eax
    push dword ptr [ebp+0x38]
    push dword ptr [ebp+0x34]
    push dword ptr [ebp+0x30]
    mov eax, dword ptr [ebp+0x2C]
    push eax
    mov edi, dword ptr [ebp+0x24]
    push edi
    or eax, dword ptr [esp+8]
    js gdrop
    mov eax, dword ptr [esp+8]
    add eax, dword ptr [esp+0x10]
    add eax, dword ptr [edi+0x84]
    jg gdrop
    call {va("restripe_core"):#x}
    jmp gdone
gdrop:
    add esp, 0x20
gdone:
    mov esp, ebp
    popad
    ret 0x18
"""


def asm_zoom() -> str:
    """Entry (KSB contract, RET 0x2C): +4 buf, +8 buf, +0xC sx, +0x10 sy, +0x14 wn, +0x18 hn, +0x1C dx, +0x20 dy,
    +0x24 aw, +0x28 ah, +0x2C key; esi = the FlatButton.  After pushad (ebp = esp) the args sit at +0x24..+0x4C.
    Locals: -4 stride, -8 f0, -0xC f1, -0x10 F, -0x14 w, -0x18 off, -0x1C y, -0x20 data.
    The buffer's own w / h fields hold the SHRUNK native dims here (thunk_btn_shrink; 2dscale restores them after the
    zoom), so like the KSB the zoom trusts the caller's dims; it only requires aw <= the row stride.

    Scan: f0 / f1 = the first / last+1 native column (of [0, wn) x [0, hn)) holding a non-key pixel.
    Column table g_rsb_ct[j] = f0 + mirror_nn(k, F, w) for k = j - off in [0, w) (t_rsb_mnn), else 0xFF (key).
    Rows bottom-up (sy <= y: a native row is read before the dest row that could overwrite it):
    sy = min(((2y+1) hn) / (2 ah), hn - 1); g_rsb_row = native row sy; dest row y from the table."""
    G, CT, ROW = va("g_popup_scale_num"), va("g_rsb_ct"), va("g_rsb_row")
    return f"""
    push eax
    push edx
    mov eax, dword ptr [esi+0xC4]
    test eax, eax
    je fwd_pop
    lea edx, [eax+{SB_UP:#x}]
    cmp esi, edx
    je is_arrow
    lea edx, [eax+{SB_DN:#x}]
    cmp esi, edx
    jne fwd_pop
is_arrow:
    cmp dword ptr [{G:#x}], 0x10
    jle fwd_pop
    call {va("t_rsb_israil"):#x}
    jne fwd_pop
    pop edx
    pop eax
    pushad
    mov ebp, esp
    sub esp, 0x20
    mov eax, dword ptr [ebp+0x2C]
    or eax, dword ptr [ebp+0x30]
    or eax, dword ptr [ebp+0x3C]
    or eax, dword ptr [ebp+0x40]
    jne bail
    mov eax, dword ptr [ebp+0x24]
    cmp eax, dword ptr [ebp+0x28]
    jne bail
    mov ecx, dword ptr [ebp+0x34]
    test ecx, ecx
    jle bail
    cmp ecx, 0xFF
    jg bail
    mov edx, dword ptr [ebp+0x44]
    cmp edx, ecx
    jl bail
    cmp edx, 0x100
    jg bail
    mov eax, dword ptr [ebp+0x38]
    test eax, eax
    jle bail
    cmp dword ptr [ebp+0x48], eax
    jl bail
    mov edi, dword ptr [ebp+0x24]
    mov ebx, dword ptr [edi+0x54]
    test ebx, ebx
    je bail
    mov eax, dword ptr [edi+0x4A8]
    cmp eax, edx
    jl bail
    mov dword ptr [ebp-4], eax
    mov dword ptr [ebp-0x20], ebx
    mov dword ptr [ebp-8], -1
    xor ecx, ecx
sc_col:
    cmp ecx, dword ptr [ebp+0x34]
    jge sc_done
    lea esi, [ebx+ecx]
    mov edx, dword ptr [ebp+0x38]
sc_row:
    cmp byte ptr [esi], {KEY}
    jne sc_hit
    add esi, dword ptr [ebp-4]
    dec edx
    jne sc_row
    jmp sc_next
sc_hit:
    cmp dword ptr [ebp-8], 0
    jge sc_last
    mov dword ptr [ebp-8], ecx
sc_last:
    lea eax, [ecx+1]
    mov dword ptr [ebp-0xC], eax
sc_next:
    inc ecx
    jmp sc_col
sc_done:
    mov eax, dword ptr [ebp-8]
    test eax, eax
    js bail
    mov ecx, dword ptr [ebp-0xC]
    sub ecx, eax
    mov dword ptr [ebp-0x10], ecx
    mov eax, ecx
    mov ecx, dword ptr [ebp+0x44]
    call {va("t_rsb_wspan"):#x}
    test eax, eax
    jle bail
    test ecx, ecx
    js bail
    mov dword ptr [ebp-0x14], eax
    mov dword ptr [ebp-0x18], ecx
    xor ecx, ecx
ct_clear:
    cmp ecx, dword ptr [ebp+0x44]
    jge ct_fill
    mov byte ptr [{CT:#x}+ecx], 0xFF
    inc ecx
    jmp ct_clear
ct_fill:
    xor ecx, ecx
    mov ebx, dword ptr [ebp-0x10]
    mov esi, dword ptr [ebp-0x14]
ct_k:
    cmp ecx, esi
    jge rows_init
    mov eax, ecx
    push ecx
    mov ecx, esi
    call {va("t_rsb_mnn"):#x}
    pop ecx
    add eax, dword ptr [ebp-8]
    mov edx, dword ptr [ebp-0x18]
    add edx, ecx
    mov byte ptr [{CT:#x}+edx], al
    inc ecx
    jmp ct_k
rows_init:
    mov eax, dword ptr [ebp+0x48]
    mov dword ptr [ebp-0x1C], eax
row_y:
    dec dword ptr [ebp-0x1C]
    js zdone
    mov eax, dword ptr [ebp-0x1C]
    lea eax, [eax*2+1]
    imul eax, dword ptr [ebp+0x38]
    mov ecx, dword ptr [ebp+0x48]
    add ecx, ecx
    cdq
    idiv ecx
    mov ecx, dword ptr [ebp+0x38]
    dec ecx
    cmp eax, ecx
    jle sy_ok
    mov eax, ecx
sy_ok:
    imul eax, dword ptr [ebp-4]
    mov esi, dword ptr [ebp-0x20]
    add esi, eax
    xor ecx, ecx
cp_row:
    cmp ecx, dword ptr [ebp+0x34]
    jge put_row
    mov al, byte ptr [esi+ecx]
    mov byte ptr [{ROW:#x}+ecx], al
    inc ecx
    jmp cp_row
put_row:
    mov edi, dword ptr [ebp-0x1C]
    imul edi, dword ptr [ebp-4]
    add edi, dword ptr [ebp-0x20]
    xor ecx, ecx
put_j:
    cmp ecx, dword ptr [ebp+0x44]
    jge row_y
    movzx eax, byte ptr [{CT:#x}+ecx]
    mov dl, {KEY}
    cmp al, 0xFF
    je put_px
    mov dl, byte ptr [{ROW:#x}+eax]
put_px:
    mov byte ptr [edi+ecx], dl
    inc ecx
    jmp put_j
zdone:
    mov esp, ebp
    popad
    ret 0x2C
bail:
    mov esp, ebp
    popad
    push {va("thunk_btn_bandstripe"):#x}
    ret
fwd_pop:
    pop edx
    pop eax
    push {va("t_nrs_zoom"):#x}
    ret
"""


def asm_wspan() -> str:
    """eax = spr_w, ecx = inner -> eax = w, ecx = off (signed; < 0 = does not fit) = rail_grip_span(inner, spr_w, g),
    g > 16: f = (spr_w g) >> 4, r = (spr_w g) & 15; inner - f odd -> f + 1 when r != 0, else f - 1 (the tie rounds
    down); off = (inner - w) >> 1 (sar).  edx saved; every register but eax / ecx kept."""
    G = va("g_popup_scale_num")
    return f"""
    push edx
    imul eax, dword ptr [{G:#x}]
    mov edx, eax
    sar eax, 4
    and edx, 15
    sub ecx, eax
    test cl, 1
    je ws_ok
    test edx, edx
    je ws_down
    inc eax
    dec ecx
    jmp ws_ok
ws_down:
    dec eax
    inc ecx
ws_ok:
    sar ecx, 1
    pop edx
    ret
"""


def asm_lay() -> str:
    """eax = Wc -> eax = b, ecx = w, edx = off = rail_layout_zones(Wc, g).  Frame (ebp): -4 Wc, -8 K, -0xC g, -0x10 b,
    -0x14 bw, -0x18 w, -0x1C off, -0x28 / -0x2C / -0x30 best max / sum / proximity, -0x34 / -0x38 / -0x3C best b / w /
    off.  Ascending b, a candidate replaces the best only when strictly better on (max, sum, |32 b - 4 Wc|), so an
    exact tie keeps the smaller b.  Deviations in 16ths: |16(b - K) - 3g|, |16 bw - 24g|, |16 w - 18g|, |16 off - 3g|.
    ebx / esi / edi / ebp kept."""
    G = va("g_popup_scale_num")
    WS = va("t_rsb_wspan")
    absv = """
    cdq
    xor eax, edx
    sub eax, edx"""
    return f"""
    push ebx
    push esi
    push edi
    push ebp
    mov ebp, esp
    sub esp, 0x40
    mov dword ptr [ebp-4], eax
    mov ecx, dword ptr [{G:#x}]
    mov dword ptr [ebp-0xC], ecx
    lea edx, [ecx*2+15]
    sar edx, 5
    mov dword ptr [ebp-8], edx
    mov dword ptr [ebp-0x10], edx
    mov dword ptr [ebp-0x34], edx
    mov dword ptr [ebp-0x28], 0x7FFFFFFF
    xor eax, eax
    mov dword ptr [ebp-0x38], eax
    mov dword ptr [ebp-0x3C], eax
lay_b:
    mov eax, dword ptr [ebp-0x10]
    add eax, eax
    cmp eax, dword ptr [ebp-4]
    jg lay_done
    mov ecx, dword ptr [ebp-4]
    sub ecx, eax
    mov dword ptr [ebp-0x14], ecx
    mov eax, 18
    call {WS:#x}
    test ecx, ecx
    js lay_next
    mov dword ptr [ebp-0x18], eax
    mov dword ptr [ebp-0x1C], ecx
    mov eax, dword ptr [ebp-0x10]
    sub eax, dword ptr [ebp-8]
    shl eax, 4
    mov ecx, dword ptr [ebp-0xC]
    lea ecx, [ecx+ecx*2]
    sub eax, ecx{absv}
    mov edi, eax
    mov esi, eax
    mov eax, dword ptr [ebp-0x14]
    shl eax, 4
    imul ecx, dword ptr [ebp-0xC], 24
    sub eax, ecx{absv}
    add esi, eax
    cmp eax, edi
    jle d2_ok
    mov edi, eax
d2_ok:
    mov eax, dword ptr [ebp-0x18]
    shl eax, 4
    imul ecx, dword ptr [ebp-0xC], 18
    sub eax, ecx{absv}
    add esi, eax
    cmp eax, edi
    jle d3_ok
    mov edi, eax
d3_ok:
    mov eax, dword ptr [ebp-0x1C]
    shl eax, 4
    mov ecx, dword ptr [ebp-0xC]
    lea ecx, [ecx+ecx*2]
    sub eax, ecx{absv}
    add esi, eax
    cmp eax, edi
    jle d4_ok
    mov edi, eax
d4_ok:
    mov eax, dword ptr [ebp-0x10]
    shl eax, 5
    mov ecx, dword ptr [ebp-4]
    shl ecx, 2
    sub eax, ecx{absv}
    cmp edi, dword ptr [ebp-0x28]
    jl lay_take
    jg lay_next
    cmp esi, dword ptr [ebp-0x2C]
    jl lay_take
    jg lay_next
    cmp eax, dword ptr [ebp-0x30]
    jge lay_next
lay_take:
    mov dword ptr [ebp-0x30], eax
    mov dword ptr [ebp-0x28], edi
    mov dword ptr [ebp-0x2C], esi
    mov eax, dword ptr [ebp-0x10]
    mov dword ptr [ebp-0x34], eax
    mov eax, dword ptr [ebp-0x18]
    mov dword ptr [ebp-0x38], eax
    mov eax, dword ptr [ebp-0x1C]
    mov dword ptr [ebp-0x3C], eax
lay_next:
    inc dword ptr [ebp-0x10]
    jmp lay_b
lay_done:
    mov eax, dword ptr [ebp-0x34]
    mov ecx, dword ptr [ebp-0x38]
    mov edx, dword ptr [ebp-0x3C]
    mov esp, ebp
    pop ebp
    pop edi
    pop esi
    pop ebx
    ret
"""


ASM = {"t_rsb_cmap": asm_cmap, "t_rsb_blit": asm_blit, "t_rsb_bar": asm_bar, "t_rsb_israil": asm_israil,
       "t_rsb_grip": asm_grip, "t_rsb_gripdraw": asm_gripdraw, "t_rsb_zoom": asm_zoom, "t_rsb_mnn": asm_mnn,
       "t_rsb_wspan": asm_wspan, "t_rsb_lay": asm_lay}


def assemble(name: str, resolve: dict[str, int] | None = None) -> bytes:
    """The thunk's bytes at its pcave2 VA.  `resolve` maps sentinel names to real VAs (a bake's symbol table) for
    execution; without it the sentinels stay in (template use)."""
    src = ASM[name]()
    assert ";" not in src
    if resolve:
        for n, s in SENT.items():
            src = src.replace(f"{s:#x}", f"{resolve[n]:#x}")
    off, end = LAYOUT[name]
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, PCAVE2 + off)[0])
    assert REGION[0] <= off and off + len(b) <= end <= REGION[1], (name, hex(off), len(b))
    return b


def template(name: str) -> str:
    """The yaml bytes: sentinels -> {abs32:NAME} (a disp32 / imm32 / push) or {rel32:NAME} (after E8 only)."""
    off, _end = LAYOUT[name]
    b = assemble(name)
    base = PCAVE2 + off
    rev = {v: k for k, v in SENT.items()}
    rev.update({PCAVE2 + o: n for n, (o, _e) in LAYOUT.items()})
    cells = {PCAVE2 + o: n for n, (o, _sz) in CELLS.items()}
    out, i = [], 0
    while i < len(b):
        if i + 4 <= len(b):
            word = int.from_bytes(b[i:i + 4], "little")
            if i >= 1 and b[i - 1] == 0xE8:
                tgt = (base + i + 4 + int.from_bytes(b[i:i + 4], "little", signed=True)) & 0xFFFFFFFF
                if tgt in rev:
                    out.append(f"{{rel32:{rev[tgt]}}}")
                    i += 4
                    continue
            if word in rev:
                out.append(f"{{abs32:{rev[word]}}}")
                i += 4
                continue
            if word in cells:
                out.append(f"{{abs32:{cells[word]}}}")
                i += 4
                continue
        out.append(f"{b[i]:02X}")
        i += 1
    tpl = " ".join(out)
    for s in SENT.values():                        # no sentinel survives as raw bytes
        assert s.to_bytes(4, "little").hex(" ").upper() not in tpl, (name, hex(s))
    return tpl


def main() -> int:
    for name in ORDER:
        off, end = LAYOUT[name]
        b = assemble(name)
        print(f"; {name} {len(b)} B @{off:#x}..{off + len(b):#x} (slot to {end:#x})")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    for n, (o, sz) in CELLS.items():
        print(f"  {n + ':':<31}{{ cave: pcave2, offset: {o:#x}, size: {sz:#x} }}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
