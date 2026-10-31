# Regenerates the W2A helpers in pcave2 0x34000..0x34FFF (2026-10-25 wave-2 W2A) and the W4C ones in 0x3B000..0x3BFFF
# (2026-10-25 wave-4 W4C v2; guards tests/test_halfopen_frames_asm_parity.py + tests/test_scaling_halfopen_pairs.py +
# tests/test_scaling_se_halfopen.py):
#
#   t_rw_btnw   (F30; law scaling_laws.rw_btn_pair) -- CALLed from t_rw_gap1 / t_rw_gap2 v2 (assemble_rw.py,
#               T_RW_BTNW).  The HQ report console's DATALINKS / CLOSE pair: in eax = mid ((clipL + clipR) >> 1),
#               edx = row L; out eax = the button width, edx = CLOSE's x.  g <= 16: vanilla's split (w = mid - L - 1,
#               x = mid + 1); else ONE width w = (R - L - s(2)) >> 1 for both and x = R - w, R = the row's right edge
#               [0x87E078] -- the odd px of an odd row goes to the seam (was: between CLOSE and the ring, 4K 5 | 6).
#               ecx and every other register kept.
#   t_bm_ho_pp / t_bm_ho_hf  (F38; law scaling_laws.union_frame_draw_rect) -- two union frames (a button row /
#               component union outset by a native 3, drawn with Buffer_box_sprite) are HALF-OPEN engine rects that
#               reach a band-map renderer with an INCLUSIVE footprint, so their right / bottom strokes landed one px
#               outside the native extent (1600x900 production picker: channels 2 | 3 both ways):
#                 ProdPicker_exec.btnframe_boxsprite  @0x494F7C -> thunk_pp_boxsprite
#                 DesignWin_master.union_frame        @0x437B89 -> thunk_box_thick_hollow_flat
#               Each site calls a helper with Buffer_box_sprite's contract (thiscall ecx = dest Buffer, args rect,
#               params, RET 8) that at g > 16 decrements the rect's R / B in place (bandmap_rect_from_halfopen), calls
#               the renderer the site called before and restores them; g <= 16 it tail-jumps that renderer unchanged
#               (push + ret: a rel32 placeholder must follow an E8; the renderer's own g gate falls to the native
#               primitive).  ebx is preserved (live in both callers); ecx reaches the renderer intact.
#               The other callers of thunk_pp_boxsprite (the picker grid frame and cell outlines, the scenario editor's
#               frames) keep the inclusive footprint: prodpicker_sel_outline_rects and editor_info_channel are
#               written against it.
#   t_bm_ho_df  (W4C, F42; law scaling_laws.se_frame_draw_rect) -- the same helper in front of thunk_box_thick_devfill.
#               The Social Engineering modal's twelve frame sites (SE_HALFOPEN_FRAME_SITES: eight devfill sites ->
#               t_bm_ho_df, three hollow_flat sites + the OK row's union frame, which went to the native 1-px primitive,
#               -> t_bm_ho_hf) are drawn on their half-open rects.
#   t_se_layout (W4C, F42; laws scaling_laws.se_halfopen_choices / se_halfopen_layout) -- thunk_se_btnrun's tail jump
#               (assemble_se.T_SE_LAYOUT; was `jmp SocialWin_model_reset`), before model_reset and before any SE
#               FlatButton is built from the tables: at g > 16 the four small searches of se_halfopen_choices in
#               integer x16 units, then the band / option / SOCIETY-panel / row / SPARTANS tables rewritten from the
#               drawn half-open frames; every register kept (pushad), then `jmp SocialWin_model_reset` (fastcall ecx).
#               v3 (2026-10-25 wave-5 W5C, in place): vanilla's additive grammar (law se_halfopen_parts: ONE rounding
#               fl(20) for every title band / row / cell, one channel c, one inset c + K, row -> cell offset h + c),
#               and the 17 painter immediates that carry it (SE_LAYOUT_IMMS, law se_halfopen_imms) are written here --
#               out of thunk_se_immfix's g_se_immtab, one owner each -- once g_se_vpdone says immfix made the pages
#               writable; g <= 16 they get their native bytes back.
#
# Usage: py assemble_halfopen_frames.py   -> prints the yaml symbol + content + site lines
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
REGIONS = ((0x34000, 0x35000), (0x3B000, 0x3C000))  # W2A's / W4C's pcave2 regions
G_SCALE = 0x11111111                               # placeholder for g_popup_scale_num
TARGET_PH = 0x22222222                             # placeholder VA for the tail renderer
RW_ROW_L, RW_ROW_R = 0x87E070, 0x87E078            # ReportIf_activate's button row L / R (SL.RW_BTN_ROW)
RW_BTN_SEAM = 2                                    # SL.RW_BTN_SEAM
DEVFILL_VA, HOLLOW_FLAT_VA = PCAVE2 + 0x42A0, PCAVE2 + 0x140
SE_OBJ = 0x8A6270                                  # SocialWin
SE_MODEL_RESET = 0x4AECE0                          # SocialWin_model_reset (fastcall ecx = self)
SE_RAIL_R_IMM = 0x4B330A                           # the builder's backdrop R imm (0x4B3307 + 3), rail-anchored by immfix
SE_LAYOUT_OFF = 0x3B040
G_SE_VPDONE = PCAVE2 + 0x14000                     # g_se_vpdone (assemble_se): thunk_se_immfix's VirtualProtect done
VP_PH = 0x33333333                                 # placeholder for g_se_vpdone

# helper -> (offset, end of its slot, renderer symbol or None, renderer VA in the bake)
HELPERS = {
    "t_rw_btnw": (0x34000, 0x34040, None, None),
    "t_bm_ho_pp": (0x34040, 0x34080, "thunk_pp_boxsprite", PCAVE2 + 0x3930),
    "t_bm_ho_hf": (0x34080, 0x340C0, "thunk_box_thick_hollow_flat", HOLLOW_FLAT_VA),
    "t_bm_ho_df": (0x3B000, 0x3B040, "thunk_box_thick_devfill", DEVFILL_VA),
    "t_se_layout": (SE_LAYOUT_OFF, 0x3C000, None, None),
}
SITES = [   # (id, group, function, va, helper, note) -- the call-target retargets (owned in patches.yaml / assemble_dw)
    ("ProdPicker_exec.btnframe_boxsprite", "prodpicker_relayout", "ProdPicker_exec", 0x494F7C, "t_bm_ho_pp",
     "call Buffer_box_sprite (0x5E2DD3)"),
    ("DesignWin_master.union_frame", "dw_scale", "DesignWin_master", 0x437B89, "t_bm_ho_hf",
     "D4: canvas-dest frame through the thick chain"),
]
SE_SITE_HELPER = {"thunk_box_thick_devfill": "t_bm_ho_df", "thunk_box_thick_hollow_flat": "t_bm_ho_hf"}


def asm_btnw(g: int = G_SCALE) -> str:
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jg      scaled
    lea     edx, [eax+1]
    sub     eax, dword ptr [{RW_ROW_L:#x}]
    dec     eax
    ret
scaled:
    push    ecx
    mov     eax, dword ptr [{RW_ROW_R:#x}]
    sub     eax, edx
    mov     ecx, {RW_BTN_SEAM}
    imul    ecx, dword ptr [{g:#x}]
    lea     ecx, [ecx*2+15]
    sar     ecx, 5
    sub     eax, ecx
    sar     eax, 1
    mov     edx, dword ptr [{RW_ROW_R:#x}]
    sub     edx, eax
    pop     ecx
    ret
"""


def asm_helper(target: int, g: int = G_SCALE) -> str:
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jg      scaled
    push    {target:#x}
    ret
scaled:
    push    ebx
    mov     ebx, dword ptr [esp+8]
    dec     dword ptr [ebx+8]
    dec     dword ptr [ebx+0xC]
    push    dword ptr [esp+0xC]
    push    ebx
    call    {target:#x}
    inc     dword ptr [ebx+8]
    inc     dword ptr [ebx+0xC]
    pop     ebx
    ret     8
"""


# ---- t_se_layout ----------------------------------------------------------------------------------------------------
# locals [ebp + off]
_L = {n: 4 * i for i, n in enumerate((
    "GG", "CT0", "CTI", "CC1", "CC2", "CC3", "COS", "CP", "CHB", "CSOCB", "CB3B", "CGS", "CFI", "CGF", "CMAX", "CSUM",
    "BMX", "BSM", "RMX", "RSM", "RTIE", "RGS", "RFI", "RGF", "F1", "F2", "F3", "D4", "D5",
    "K", "H", "S2", "S3", "S22", "UNT", "TMP",
    "HMAX", "HSUM", "HTIE", "HT0", "HTI", "HC1", "HC2", "HC3", "HOS", "HP", "HGS", "HFI", "HGF",
    "C1", "C2", "C3", "OS", "TLR",
    "W146", "W143", "S4", "S73", "BL", "BR0", "PR0", "RAILR", "RUN",
    "BR", "PL", "PR", "T0", "C", "TI", "O", "HB", "P", "GS", "FI", "GF", "B3B", "SOCB",
    "CC", "CO", "CBF",
    "D1", "D2", "D3", "BMAX", "BSUM", "BTIE", "E1", "E2", "E3", "CHX", "X0"))}
_FRAME = 4 * len(_L)
_ORDERED: list = []
_SEQ = [0]


#: ebp sits _BIAS bytes into the frame so disp8 reaches 64 locals; the most referenced ones (counted on the generated
#: source, _order_locals) get the disp8 slots
_BIAS = 0x80


def _v(n: str) -> str:
    d = _L[n] - _BIAS
    return f"dword ptr [ebp{'+' if d >= 0 else '-'}{abs(d):#x}]"


def _order_locals() -> None:
    """Re-pack _L: locals by reference count in asm_se_layout's source, most used nearest ebp (disp8)."""
    global _L
    names = list(_L)
    _L = {n: 4 * i for i, n in enumerate(names)}
    src = asm_se_layout(G_SCALE, VP_PH, _ordered=True)
    count = {n: src.count(_v(n) + "") for n in names}
    ranked = sorted(names, key=lambda n: -count[n])
    slots = sorted(range(len(names)), key=lambda i: abs(4 * i - _BIAS + 2))
    _L = {n: 4 * i for n, i in zip(ranked, slots)}


def _hd(n: str, v: int, g: int) -> str:
    """local n = half_down(v * g, 16) = (2*v*g + 15) >> 5 (scale_px)."""
    return f"""
    mov     eax, {v}
    imul    eax, dword ptr [{g:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5
    mov     {_v(n)}, eax"""


def _fl(n: str, v: int, g: int) -> str:
    """local n = (v * g) >> 4 (popup_scale_floor)."""
    return f"""
    mov     eax, {v}
    imul    eax, dword ptr [{g:#x}]
    sar     eax, 4
    mov     {_v(n)}, eax"""


def _abs(r: str, scratch: str) -> str:
    return f"""
    mov     {scratch}, {r}
    sar     {scratch}, 31
    xor     {r}, {scratch}
    sub     {r}, {scratch}"""


def _err(r: str, coef: int, g: int) -> str:
    """r = |r - coef*g| (r already holds 16*x); g from the GG local (set first thing in the scaled path).  eax: cdq form
    (edx clobbered)."""
    if r == "eax":
        return f"""
    imul    ebx, {_v("GG")}, {coef}
    sub     eax, ebx
    cdq
    xor     eax, edx
    sub     eax, edx"""
    return f"""
    imul    ebx, {_v("GG")}, {coef}
    sub     {r}, ebx{_abs(r, "ebx")}"""


def _acc(coef: int, g: int = 0) -> str:
    """eax holds x: CMAX = max(CMAX, |16x - coef*g|), CSUM += it (_se_err16), through the acc_sub subroutine (ecx / edx /
    ebx clobbered)."""
    return f"""
    push    {coef}
    pop     ecx
    call    acc_sub"""


def _accl(coef: int) -> str:
    return _acc(coef)


def _take_better(lbl: str, m: str, s: str, t: str) -> str:
    """(CMAX, CSUM, edi) vs the (m, s, t) locals, lexicographic <: falls through to `{lbl}_take` (stored) else jumps
    to `{lbl}_skip`."""
    return f"""
    mov     eax, {_v("CMAX")}
    mov     edx, {_v("CSUM")}
    cmp     eax, {_v(m)}
    jl      {lbl}_take
    jg      {lbl}_skip
    cmp     edx, {_v(s)}
    jl      {lbl}_take
    jg      {lbl}_skip
    cmp     edi, {_v(t)}
    jge     {lbl}_skip
{lbl}_take:
    mov     {_v(m)}, eax
    mov     {_v(s)}, edx
    mov     {_v(t)}, edi"""


def _in_range(var: str, base: str, lo: int, hi: int, fail: str) -> str:
    """jump to fail unless base + lo <= var <= base + hi."""
    return f"""
    mov     eax, {_v(var)}
    sub     eax, {_v(base)}
    cmp     eax, {lo}
    jl      {fail}
    cmp     eax, {hi}
    jg      {fail}"""


def _take_if_better(lbl: str) -> str:
    """(CMAX, CSUM, TIE in edi) vs (BMAX, BSUM, BTIE): lexicographic (max, sum, tie) <.  Falls through to
    `{lbl}_take` when better, else jumps to `{lbl}_skip`."""
    return f"""
    mov     eax, {_v("CMAX")}
    mov     edx, {_v("CSUM")}
    cmp     eax, {_v("BMAX")}
    jl      {lbl}_take
    jg      {lbl}_skip
    cmp     edx, {_v("BSUM")}
    jl      {lbl}_take
    jg      {lbl}_skip
    cmp     edi, {_v("BTIE")}
    jge     {lbl}_skip
{lbl}_take:
    mov     {_v("BMAX")}, eax
    mov     {_v("BSUM")}, edx
    mov     {_v("BTIE")}, edi"""


def _take3_if_better(lbl: str) -> str:
    """W4C's (E1, E2, E3, TIE in edi) form (search C): max / sum of the three, then as _take_if_better."""
    return f"""
    mov     eax, {_v("E1")}
    mov     ecx, {_v("E2")}
    cmp     ecx, eax
    cmovg   eax, ecx
    mov     ecx, {_v("E3")}
    cmp     ecx, eax
    cmovg   eax, ecx
    mov     edx, {_v("E1")}
    add     edx, {_v("E2")}
    add     edx, {_v("E3")}
    mov     {_v("CMAX")}, eax
    mov     {_v("CSUM")}, edx{_take_if_better(lbl)}"""


def _reset_best() -> str:
    return f"""
    mov     {_v("BMAX")}, 0x7FFFFFFF
    mov     {_v("BSUM")}, 0x7FFFFFFF
    mov     {_v("BTIE")}, 0x7FFFFFFF"""


def _start_cand() -> str:
    return f"""
    mov     {_v("CMAX")}, 0
    mov     {_v("CSUM")}, 0"""


def _tie(fields: tuple) -> str:
    """edi = scaling_laws._se_tie(((D, bits), ...)) from the delta locals."""
    total = sum(b for _n, b in fields)
    out = "\n    xor     edi, edi"
    for n, _b in fields:
        out += f"\n    mov     eax, {_v(n)}{_abs('eax', 'ebx')}\n    add     edi, eax"
    out += f"\n    shl     edi, {total}"
    shift = total
    for n, b in fields:
        shift -= b
        out += f"\n    mov     eax, {_v(n)}\n    add     eax, {1 << (b - 1)}"
        if shift:
            out += f"\n    shl     eax, {shift}"
        out += "\n    or      edi, eax"
    return out


def _loop(var: str, lo: int, hi: int, body: str, name: str) -> str:
    return f"""
    mov     {_v(var)}, {lo}
{name}:{body}
{name}_next:
    inc     {_v(var)}
    cmp     {_v(var)}, {hi}
    jle     {name}"""


def _imm_writes(native: bool) -> str:
    """The SE_LAYOUT_IMMS stores: natives (g <= 16) as immediates, else from the TI / H / O / FI locals."""
    import scaling_laws as SL
    out = ""
    for va, (w, role, nat) in SL.SE_LAYOUT_IMMS.items():
        ptr = "dword" if w == 4 else "byte"
        if native:
            out += f"\n    mov     {ptr} ptr [{va:#x}], {nat & (0xFFFFFFFF if w == 4 else 0xFF):#x}"
            continue
        src = {"ti": "TI", "tlr": "TLR", "h": "H", "o": "O", "fi": "FI", "-h": "H"}[role]
        out += f"\n    mov     eax, {_v(src)}"
        if role == "-h":
            out += "\n    neg     eax"
        out += f"\n    mov     {ptr} ptr [{va:#x}], {'eax' if w == 4 else 'al'}"
    return out


def _hybrid() -> str:
    """Section E (W6H; law scaling_laws.se_halfopen_hybrid): W5C's 18-term worst; above SE_HYBRID_LIMIT16 the search
    over (T0, c, kind, sign, P) with one relation broken by 1, the right column per candidate (right_search), pruned
    when the band part alone cannot beat the best.  Leaves the final T0 / TI / C1 / C2 / C3 / OS / P / GS / FI / GF /
    HB / SOCB / O and TLR (the L / R inset: W5C's TI) for the tables and the immediates."""
    import scaling_laws as SL
    body = f"""
    cmp     {_v("D4")}, 0
    je      lh4_next
    mov     eax, {_v("S4")}
    add     eax, {_v("D1")}
    mov     {_v("CT0")}, eax
    mov     eax, {_v("S2")}
    add     eax, {_v("D2")}
    mov     {_v("CC1")}, eax
    mov     {_v("CC3")}, eax
    mov     ecx, eax
    add     ecx, {_v("K")}
    mov     {_v("CTI")}, ecx
    mov     edx, {_v("D4")}
    lea     ecx, [eax+edx]
    mov     {_v("CC2")}, ecx
    add     ecx, {_v("H")}
    mov     {_v("COS")}, ecx
    mov     ecx, {_v("D3")}
    cmp     ecx, 0
    jne     hk1
    add     {_v("CC1")}, edx
    jmp     hkd
hk1:
    cmp     ecx, 1
    jne     hk3
    add     {_v("CTI")}, edx
    jmp     hkd
hk3:
    cmp     ecx, 3
    jne     hkd
    mov     {_v("CC2")}, eax
hkd:{_in_range("CTI", "S3", -1, 2, "lh4_next")}{_in_range("CC1", "S2", -1, 2, "lh4_next")}{_in_range("CC2", "S2", -1, 2, "lh4_next")}{_in_range("COS", "S22", -1, 1, "lh4_next")}
    mov     {_v("D5")}, -3
lh5:
    mov     eax, {_v("S73")}
    add     eax, {_v("D5")}
    mov     {_v("CP")}, eax
    call    band_err
    mov     eax, {_v("CMAX")}
    mov     {_v("BMX")}, eax
    mov     edx, {_v("CSUM")}
    mov     {_v("BSM")}, edx
    cmp     eax, {_v("HMAX")}
    jg      lh5_next
    jl      lh5_go
    cmp     edx, {_v("HSUM")}
    jg      lh5_next
lh5_go:
    call    right_search
    mov     eax, {_v("BMX")}
    cmp     eax, {_v("RMX")}
    cmovl   eax, {_v("RMX")}
    mov     {_v("CMAX")}, eax
    mov     eax, {_v("BSM")}
    add     eax, {_v("RSM")}
    mov     {_v("CSUM")}, eax
    mov     edi, {_v("D1")}
    inc     edi
    shl     edi, 2
    mov     eax, {_v("CTI")}
    sub     eax, {_v("S3")}
    inc     eax
    or      edi, eax
    shl     edi, 2
    mov     eax, {_v("CC1")}
    sub     eax, {_v("S2")}
    inc     eax
    or      edi, eax
    shl     edi, 2
    mov     eax, {_v("CC2")}
    sub     eax, {_v("S2")}
    inc     eax
    or      edi, eax
    shl     edi, 2
    mov     eax, {_v("CC3")}
    sub     eax, {_v("S2")}
    inc     eax
    or      edi, eax
    shl     edi, 2
    mov     eax, {_v("COS")}
    sub     eax, {_v("S22")}
    inc     eax
    or      edi, eax
    shl     edi, 3
    mov     eax, {_v("D5")}
    add     eax, 3
    or      edi, eax{_take_better("hb", "HMAX", "HSUM", "HTIE")}""" + "".join(f"""
    mov     eax, {_v(src)}
    mov     {_v(dst)}, eax""" for src, dst in (("CT0", "HT0"), ("CTI", "HTI"), ("CC1", "HC1"), ("CC2", "HC2"),
                                            ("CC3", "HC3"), ("COS", "HOS"), ("CP", "HP"), ("RGS", "HGS"),
                                            ("RFI", "HFI"), ("RGF", "HGF"))) + """
hb_skip:
lh5_next:
    inc     {D5}
    cmp     {D5}, 3
    jle     lh5""".replace("{D5}", _v("D5"))
    search = f"""
    mov     {_v("HMAX")}, 0x7FFFFFFF
    mov     {_v("HSUM")}, 0x7FFFFFFF
    mov     {_v("HTIE")}, 0x7FFFFFFF""" + _loop("D1", -1, 1, _loop("D2", -1, 2, _loop("D3", 0, 3, _loop(
        "D4", -1, 1, body, "lh4"), "lh3"), "lh2"), "lh1")
    copy = "".join(f"""
    mov     eax, {_v(src)}
    mov     {_v(dst)}, eax""" for src, dst in (("HT0", "T0"), ("HTI", "TI"), ("HC1", "C1"), ("HC2", "C2"),
                                            ("HC3", "C3"), ("HOS", "OS"), ("HP", "P"), ("HGS", "GS"), ("HFI", "FI"),
                                            ("HGF", "GF"), ("HT0", "CT0"), ("HTI", "CTI"), ("HC1", "CC1"),
                                            ("HC2", "CC2"), ("HC3", "CC3"), ("HOS", "COS"), ("HP", "CP")))
    return f"""
    ; ---- E. the hybrid (law se_halfopen_hybrid): W5C defaults, its 18-term worst, the search above 2.5 px
    mov     eax, {_v("C")}
    mov     {_v("C1")}, eax
    mov     {_v("C2")}, eax
    mov     {_v("C3")}, eax
    mov     {_v("CC1")}, eax
    mov     {_v("CC2")}, eax
    mov     {_v("CC3")}, eax
    mov     eax, {_v("O")}
    mov     {_v("OS")}, eax
    mov     {_v("COS")}, eax
    mov     eax, {_v("TI")}
    mov     {_v("TLR")}, eax
    mov     {_v("CTI")}, eax
    mov     eax, {_v("T0")}
    mov     {_v("CT0")}, eax
    mov     eax, {_v("P")}
    mov     {_v("CP")}, eax
    call    band_err
    mov     eax, {_v("CMAX")}
    mov     {_v("BMX")}, eax
    mov     eax, {_v("GS")}
    mov     {_v("CGS")}, eax
    mov     eax, {_v("FI")}
    mov     {_v("CFI")}, eax
    mov     eax, {_v("GF")}
    mov     {_v("CGF")}, eax
    mov     {_v("CMAX")}, 0
    call    right_eval
    mov     eax, {_v("CMAX")}
    cmp     eax, {_v("BMX")}
    cmovl   eax, {_v("BMX")}
    cmp     eax, {SL.SE_HYBRID_LIMIT16}
    jle     hy_done
{search}
{copy}
    call    band_err
    mov     eax, {_v("CHB")}
    mov     {_v("HB")}, eax
    mov     eax, {_v("CSOCB")}
    mov     {_v("SOCB")}, eax
hy_done:
    mov     eax, {_v("C2")}
    add     eax, {_v("H")}
    mov     {_v("O")}, eax"""


def _hybrid_subs() -> str:
    """band_err / right_eval / right_search: CALLed subroutines (locals at ebp; eax / ebx / ecx / edx / edi clobbered)."""
    rs_body = f"""
    mov     eax, {_v("S3")}
    add     eax, {_v("F1")}
    sub     eax, 2
    mov     {_v("CGS")}, eax
    mov     eax, {_v("S3")}
    add     eax, {_v("F2")}
    dec     eax
    mov     {_v("CFI")}, eax
    mov     eax, {_v("S2")}
    add     eax, {_v("F3")}
    dec     eax
    mov     {_v("CGF")}, eax
    mov     {_v("CMAX")}, 0
    mov     {_v("CSUM")}, 0
    call    right_eval
    mov     edi, {_v("F1")}
    shl     edi, 2
    or      edi, {_v("F2")}
    shl     edi, 2
    or      edi, {_v("F3")}{_take_better("rs", "RMX", "RSM", "RTIE")}
    mov     eax, {_v("CGS")}
    mov     {_v("RGS")}, eax
    mov     eax, {_v("CFI")}
    mov     {_v("RFI")}, eax
    mov     eax, {_v("CGF")}
    mov     {_v("RGF")}, eax
rs_skip:"""
    return f"""
acc_sub:
    shl     eax, 4
    imul    ecx, {_v("GG")}
    sub     eax, ecx
    cdq
    xor     eax, edx
    sub     eax, edx
    add     {_v("CSUM")}, eax
    cmp     eax, {_v("CMAX")}
    jle     acc_ret
    mov     {_v("CMAX")}, eax
acc_ret:
    ret
band_err:
    mov     {_v("CMAX")}, 0
    mov     {_v("CSUM")}, 0
    mov     ecx, {_v("H")}
    lea     ecx, [ecx*2+ecx]
    mov     eax, {_v("CTI")}
    add     eax, {_v("CC1")}
    add     eax, {_v("CC3")}
    add     eax, {_v("K")}
    mov     edx, eax
    add     eax, {_v("CC2")}
    add     eax, ecx
    mov     {_v("CHB")}, eax
    mov     eax, {_v("COS")}
    lea     eax, [eax*8+eax]
    add     eax, edx
    mov     ecx, {_v("H")}
    lea     eax, [eax+ecx*2]
    mov     {_v("TMP")}, eax
    add     eax, {_v("CT0")}
    mov     {_v("CSOCB")}, eax
    mov     eax, {_v("CP")}
    lea     eax, [eax*2+eax]
    add     eax, {_v("CT0")}
    add     eax, {_v("CHB")}
    mov     {_v("CB3B")}, eax
    mov     eax, {_v("CT0")}{_accl(4)}
    mov     eax, {_v("CTI")}{_accl(3)}
    mov     eax, {_v("H")}{_accl(20)}
    mov     eax, {_v("CC1")}{_accl(2)}
    mov     eax, {_v("CC2")}{_accl(2)}
    mov     eax, {_v("CC3")}{_accl(2)}
    mov     eax, {_v("CC2")}
    add     eax, {_v("H")}{_accl(22)}
    mov     eax, {_v("COS")}{_accl(22)}
    mov     eax, {_v("CHB")}{_accl(70)}
    mov     eax, {_v("CP")}
    sub     eax, {_v("CHB")}{_accl(3)}
    mov     eax, {_v("UNT")}
    sub     eax, {_v("CB3B")}{_accl(18)}
    mov     eax, {_v("TMP")}{_accl(246)}
    ret
right_eval:
    mov     eax, {_v("CGS")}{_accl(3)}
    mov     eax, {_v("CFI")}{_accl(3)}
    mov     eax, {_v("CGF")}{_accl(2)}
    mov     eax, {_v("CFI")}
    add     eax, {_v("H")}
    add     eax, eax
    add     eax, {_v("CGF")}
    mov     {_v("TMP")}, eax{_accl(48)}
    mov     eax, {_v("CSOCB")}
    add     eax, {_v("CGS")}
    add     eax, {_v("TMP")}
    mov     {_v("TMP")}, eax
    mov     eax, {_v("UNT")}
    sub     eax, {_v("TMP")}{_accl(10)}
    mov     eax, {_v("TMP")}
    sub     eax, {_v("CB3B")}{_accl(8)}
    ret
right_search:
    mov     {_v("RMX")}, 0x7FFFFFFF
    mov     {_v("RSM")}, 0x7FFFFFFF
    mov     {_v("RTIE")}, 0x7FFFFFFF{_loop("F1", 0, 5, _loop("F2", 0, 2, _loop("F3", 0, 2, rs_body, "rs3"), "rs2"), "rs1")}
    ret"""


def asm_se_layout(g: int = G_SCALE, vp: int = G_SE_VPDONE, _ordered: bool = False) -> str:
    if not _ordered and not _ORDERED:
        _ORDERED.append(1)
        _order_locals()
    _SEQ[0] = 0
    O = SE_OBJ
    consts = "".join((
        f"""
    mov     eax, dword ptr [{g:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5
    mov     {_v("K")}, eax""",
        _fl("H", 20, g), _fl("W146", 146, g), _fl("W143", 143, g),
        _hd("S2", 2, g), _hd("S3", 3, g), _hd("S4", 4, g), _hd("S73", 73, g),
        _hd("BL", 0x1A, g), _hd("BR0", 0x26E, g), _hd("PR0", 0x306, g), _hd("S22", 22, g),
        f"""
    mov     eax, dword ptr [{g:#x}]
    mov     {_v("GG")}, eax"""))
    # ---- A. T0, c, P (the band column)
    body_a = f"""
    mov     eax, {_v("S4")}
    add     eax, {_v("D1")}
    mov     {_v("CT0")}, eax
    mov     eax, {_v("S2")}
    add     eax, {_v("D2")}
    mov     {_v("CC")}, eax
    mov     ecx, eax
    add     ecx, {_v("K")}
    mov     {_v("CTI")}, ecx
    mov     ecx, eax
    add     ecx, {_v("H")}
    mov     {_v("CO")}, ecx
    mov     ecx, {_v("H")}
    lea     ecx, [ecx*2+ecx]
    lea     ecx, [ecx+eax*4]
    mov     edx, {_v("K")}
    lea     ecx, [ecx+edx*2]
    mov     {_v("CHB")}, ecx
    mov     eax, {_v("S73")}
    add     eax, {_v("D3")}
    mov     {_v("CP")}, eax{_start_cand()}
    mov     eax, {_v("CT0")}{_acc(4, g)}
    mov     eax, {_v("CTI")}{_acc(3, g)}
    mov     eax, {_v("CC")}{_acc(2, g)}
    mov     eax, {_v("CO")}{_acc(22, g)}
    mov     eax, {_v("CHB")}{_acc(70, g)}
    mov     eax, {_v("CP")}
    sub     eax, {_v("CHB")}{_acc(3, g)}
    mov     eax, {_v("CP")}
    lea     eax, [eax*2+eax]
    add     eax, {_v("CT0")}
    add     eax, {_v("CHB")}
    neg     eax
    add     eax, {_v("UNT")}{_acc(18, g)}
    mov     eax, {_v("CO")}
    lea     eax, [eax*8+eax]
    add     eax, {_v("CC")}
    mov     ecx, {_v("CTI")}
    add     ecx, {_v("H")}
    lea     eax, [eax+ecx*2]{_acc(246, g)}{_tie((("D1", 2), ("D2", 2), ("D3", 3)))}{_take_if_better("sa")}
    mov     eax, {_v("CT0")}
    mov     {_v("T0")}, eax
    mov     eax, {_v("CC")}
    mov     {_v("C")}, eax
    mov     eax, {_v("CP")}
    mov     {_v("P")}, eax
sa_skip:"""
    search_a = _reset_best() + _loop("D1", -1, 1, _loop("D2", -1, 1, _loop("D3", -2, 2, body_a, "la3"), "la2"), "la1")
    # ---- D. gs, fi, gf (the right column)
    body_d = f"""
    mov     eax, {_v("S3")}
    add     eax, {_v("D1")}
    mov     {_v("CGS")}, eax
    mov     eax, {_v("S3")}
    add     eax, {_v("D2")}
    mov     {_v("CFI")}, eax
    mov     eax, {_v("S2")}
    add     eax, {_v("D3")}
    mov     {_v("CGF")}, eax
    mov     ecx, {_v("CFI")}
    add     ecx, {_v("H")}
    add     ecx, ecx
    add     ecx, eax
    add     ecx, {_v("CGS")}
    add     ecx, {_v("SOCB")}
    mov     {_v("CBF")}, ecx{_start_cand()}
    mov     eax, {_v("CGS")}{_acc(3, g)}
    mov     eax, {_v("CFI")}{_acc(3, g)}
    mov     eax, {_v("CGF")}{_acc(2, g)}
    mov     eax, {_v("UNT")}
    sub     eax, {_v("CBF")}{_acc(10, g)}
    mov     eax, {_v("CBF")}
    sub     eax, {_v("B3B")}{_acc(8, g)}
    mov     eax, {_v("CFI")}
    add     eax, {_v("H")}
    add     eax, eax
    add     eax, {_v("CGF")}{_acc(48, g)}{_tie((("D1", 3), ("D2", 2), ("D3", 2)))}{_take_if_better("sd")}
    mov     eax, {_v("CGS")}
    mov     {_v("GS")}, eax
    mov     eax, {_v("CFI")}
    mov     {_v("FI")}, eax
    mov     eax, {_v("CGF")}
    mov     {_v("GF")}, eax
sd_skip:"""
    search_d = _reset_best() + _loop("D1", -2, 2, _loop("D2", -1, 1, _loop("D3", -1, 1, body_d, "ld3"), "ld2"), "ld1")
    return f"""
    cmp     dword ptr [{g:#x}], 0x10
    jg      scaled
    cmp     dword ptr [{vp:#x}], 0
    je      native{_imm_writes(True)}
native:
    jmp     {SE_MODEL_RESET:#x}
scaled:
    pushad
    sub     esp, {_FRAME:#x}
    lea     ebp, [esp+{_BIAS:#x}]
    mov     esi, {O:#x}
{consts}
    mov     eax, dword ptr [esi+0x1F2B4]
    sub     eax, {_v("S3")}
    mov     {_v("UNT")}, eax
    mov     eax, dword ptr [{SE_RAIL_R_IMM:#x}]
    mov     {_v("RAILR")}, eax
    mov     eax, {_v("W146")}
    shl     eax, 2
    mov     ecx, {_v("S2")}
    lea     ecx, [ecx*2+ecx]
    add     eax, ecx
    mov     {_v("RUN")}, eax

    ; ---- A. T0 / c / P: min (max, sum, tie) of the seven band-column errors (x16)
{search_a}
    mov     eax, {_v("C")}
    mov     ecx, eax
    add     ecx, {_v("K")}
    mov     {_v("TI")}, ecx
    mov     ecx, eax
    add     ecx, {_v("H")}
    mov     {_v("O")}, ecx
    mov     ecx, {_v("H")}
    lea     ecx, [ecx*2+ecx]
    lea     ecx, [ecx+eax*4]
    mov     edx, {_v("K")}
    lea     ecx, [ecx+edx*2]
    mov     {_v("HB")}, ecx

    ; ---- B. bR: the option run centred, leftover even, channel nearest c, then |d|, then R
    mov     {_v("BTIE")}, 0x7FFFFFFF
    mov     {_v("D1")}, -1
s1:
    mov     eax, {_v("BR0")}
    add     eax, {_v("D1")}
    mov     edx, eax
    sub     edx, {_v("K")}
    sub     edx, {_v("BL")}
    sub     edx, {_v("K")}
    sub     edx, {_v("RUN")}
    test    edx, 1
    jnz     s1_next
    sar     edx, 1
    sub     edx, {_v("C")}{_abs("edx", "ebx")}
    shl     edx, 3
    mov     ecx, {_v("D1")}{_abs("ecx", "ebx")}
    lea     edx, [edx+ecx*4+1]
    add     edx, {_v("D1")}
    cmp     edx, {_v("BTIE")}
    jge     s1_next
    mov     {_v("BTIE")}, edx
    mov     {_v("BR")}, eax
s1_next:
    inc     {_v("D1")}
    cmp     {_v("D1")}, 1
    jle     s1

    ; ---- C. pL, pR: min (max, sum, |dl|+|dr|, pL, pR)
{_reset_best()}
    mov     {_v("D1")}, -1
s3l:
    mov     {_v("D2")}, -2
s3r:
    mov     ecx, {_v("BR")}
    add     ecx, {_v("S3")}
    add     ecx, {_v("D1")}
    mov     {_v("TMP")}, ecx
    mov     eax, {_v("PR0")}
    add     eax, {_v("D2")}
    mov     {_v("CHX")}, eax
    sub     eax, {_v("K")}
    sub     eax, ecx
    sub     eax, {_v("K")}
    sub     eax, {_v("W143")}
    test    eax, 1
    jnz     s3_skip
    sar     eax, 1
    sub     eax, {_v("C")}{_abs("eax", "ebx")}
    shl     eax, 5
    mov     {_v("E2")}, eax
    mov     eax, ecx
    sub     eax, {_v("BR")}
    shl     eax, 4{_err("eax", 3, g)}
    mov     {_v("E1")}, eax
    mov     eax, {_v("RAILR")}
    sub     eax, {_v("K")}
    sub     eax, {_v("CHX")}
    shl     eax, 4{_err("eax", 3, g)}
    mov     {_v("E3")}, eax
    mov     edi, {_v("D1")}{_abs("edi", "ebx")}
    mov     edx, {_v("D2")}{_abs("edx", "ebx")}
    add     edi, edx
    shl     edi, 5
    mov     edx, {_v("D1")}
    lea     edi, [edi+edx*8+10]
    add     edi, {_v("D2")}
{_take3_if_better("s3")}
    mov     eax, {_v("TMP")}
    mov     {_v("PL")}, eax
    mov     eax, {_v("CHX")}
    mov     {_v("PR")}, eax
s3_skip:
    inc     {_v("D2")}
    cmp     {_v("D2")}, 2
    jle     s3r
    inc     {_v("D1")}
    cmp     {_v("D1")}, 1
    jle     s3l

    ; ---- D. gs / fi / gf: the right column (SOCIETY B = T0 + ti + h + c + 9o + h + ti, band 3 B = T0 + 3P + Hb)
    mov     eax, {_v("P")}
    lea     eax, [eax*2+eax]
    add     eax, {_v("T0")}
    add     eax, {_v("HB")}
    mov     {_v("B3B")}, eax
    mov     eax, {_v("O")}
    lea     eax, [eax*8+eax]
    add     eax, {_v("T0")}
    add     eax, {_v("C")}
    mov     ecx, {_v("TI")}
    add     ecx, {_v("H")}
    add     ecx, ecx
    add     eax, ecx
    mov     {_v("SOCB")}, eax
{search_d}
{_hybrid()}

    ; ---- the tables
    mov     eax, {_v("BR")}
    sub     eax, {_v("K")}
    sub     eax, {_v("BL")}
    sub     eax, {_v("K")}
    sub     eax, {_v("RUN")}
    sar     eax, 1
    add     eax, {_v("BL")}
    add     eax, {_v("K")}
    mov     {_v("X0")}, eax
    lea     edi, [esi+0x1F110]
    lea     ebx, [esi+0x1F150]
    mov     ecx, {_v("T0")}
    mov     {_v("D1")}, 4
bands:
    mov     eax, {_v("BL")}
    mov     dword ptr [edi], eax
    mov     dword ptr [edi+4], ecx
    mov     eax, {_v("BR")}
    mov     dword ptr [edi+8], eax
    mov     eax, ecx
    add     eax, {_v("HB")}
    mov     dword ptr [edi+0xC], eax
    mov     edx, ecx
    add     edx, {_v("TI")}
    add     edx, {_v("H")}
    add     edx, {_v("C1")}
    mov     eax, {_v("X0")}
    mov     {_v("D2")}, 4
opts:
    mov     dword ptr [ebx], eax
    mov     dword ptr [ebx+4], edx
    add     eax, {_v("W146")}
    mov     dword ptr [ebx+8], eax
    push    edx
    add     edx, {_v("H")}
    mov     dword ptr [ebx+0xC], edx
    pop     edx
    add     eax, {_v("S2")}
    add     ebx, 0x10
    dec     {_v("D2")}
    jnz     opts
    add     ecx, {_v("P")}
    add     edi, 0x10
    dec     {_v("D1")}
    jnz     bands
    ; society rows: centred in [pL+K, pR-K), from T0 + ti + h + c1, pitch os
    mov     eax, {_v("PR")}
    sub     eax, {_v("K")}
    sub     eax, {_v("PL")}
    sub     eax, {_v("K")}
    sub     eax, {_v("W143")}
    sar     eax, 1
    add     eax, {_v("PL")}
    add     eax, {_v("K")}
    mov     edx, {_v("T0")}
    add     edx, {_v("TI")}
    add     edx, {_v("H")}
    add     edx, {_v("C1")}
    lea     edi, [esi+0x1F070]
    mov     {_v("D1")}, 10
rows:
    mov     dword ptr [edi], eax
    mov     dword ptr [edi+4], edx
    mov     ecx, eax
    add     ecx, {_v("W143")}
    mov     dword ptr [edi+8], ecx
    mov     ecx, edx
    add     ecx, {_v("H")}
    mov     dword ptr [edi+0xC], ecx
    add     edx, {_v("OS")}
    add     edi, 0x10
    dec     {_v("D1")}
    jnz     rows
    ; the SOCIETY panel: B = last row B + c3 + K (== SOCB)
    mov     eax, {_v("PL")}
    mov     dword ptr [esi+0x1F060], eax
    mov     dword ptr [esi+0x1F2A0], eax
    mov     eax, {_v("T0")}
    mov     dword ptr [esi+0x1F064], eax
    mov     eax, {_v("PR")}
    mov     dword ptr [esi+0x1F068], eax
    mov     dword ptr [esi+0x1F2A8], eax
    mov     ecx, {_v("SOCB")}
    mov     dword ptr [esi+0x1F06C], ecx
    ; SPARTANS: T = B + gs, H = fi + h + gf + h + fi
    add     ecx, {_v("GS")}
    mov     dword ptr [esi+0x1F2A4], ecx
    mov     ecx, {_v("FI")}
    add     ecx, {_v("H")}
    add     ecx, ecx
    add     ecx, {_v("GF")}
    add     ecx, dword ptr [esi+0x1F2A4]
    mov     dword ptr [esi+0x1F2AC], ecx
    ; the painter immediates (SE_LAYOUT_IMMS; their pages made writable by thunk_se_immfix's one-time VirtualProtect)
    cmp     dword ptr [{vp:#x}], 0
    je      done{_imm_writes(False)}
done:
    add     esp, {_FRAME:#x}
    popad
    jmp     {SE_MODEL_RESET:#x}
{_hybrid_subs()}
"""


def assemble(name: str, g: int = G_SCALE, target: int | None = None, vp: int = G_SE_VPDONE) -> bytes:
    off, end, _sym, tva = HELPERS[name]
    if name == "t_rw_btnw":
        src = asm_btnw(g)
    elif name == "t_se_layout":
        src = asm_se_layout(g, vp)
    else:
        src = asm_helper(tva if target is None else target, g)
    src = "\n".join(line.split(";")[0] if line.strip().startswith(";") else line for line in src.splitlines())
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, PCAVE2 + off)[0])
    assert off + len(b) <= end and any(lo <= off and end <= hi for lo, hi in REGIONS), (name, len(b))
    return b


def template(name: str) -> str:
    """The yaml bytes: g -> {abs32:g_popup_scale_num}; the renderer -> {abs32:<renderer>} (push) / {rel32:<renderer>}
    (call).  Branches to engine code stay literal (rel32 between fixed VAs)."""
    off, _end, sym, _tva = HELPERS[name]
    b = assemble(name, target=TARGET_PH, vp=VP_PH)
    out, i = [], 0
    while i < len(b):
        word = b[i:i + 4]
        if word == G_SCALE.to_bytes(4, "little"):
            out.append("{abs32:g_popup_scale_num}")
            i += 4
            continue
        if name == "t_se_layout" and word == VP_PH.to_bytes(4, "little"):
            out.append("{abs32:g_se_vpdone}")
            i += 4
            continue
        if sym and word == TARGET_PH.to_bytes(4, "little") and b[i - 1] == 0x68:          # push imm32 (+ ret)
            out.append(f"{{abs32:{sym}}}")
            i += 4
            continue
        if sym and i >= 1 and b[i - 1] == 0xE8 and i + 4 <= len(b) and (
                int.from_bytes(word, "little", signed=True) + PCAVE2 + off + i + 4) & 0xFFFFFFFF == TARGET_PH:
            out.append(f"{{rel32:{sym}}}")
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    tpl = " ".join(out)
    if name == "t_se_layout":
        rest = bytes.fromhex(tpl.replace("{abs32:g_popup_scale_num}", "").replace("{abs32:g_se_vpdone}", "").replace(" ", ""))
        assert G_SCALE.to_bytes(4, "little") not in rest and VP_PH.to_bytes(4, "little") not in rest, tpl
        assert tpl.count("{abs32:g_se_vpdone}") == 2, tpl
    elif sym:
        assert tpl.count("{abs32:g_popup_scale_num}") == 1 and tpl.count(f"{{rel32:{sym}}}") == 1 \
            and tpl.count(f"{{abs32:{sym}}}") == 1, tpl
    else:
        assert tpl.count("{abs32:g_popup_scale_num}") == 2, tpl
    return tpl


def se_sites() -> list:
    """The SocialWin frame sites (law scaling_laws.SE_HALFOPEN_FRAME_SITES) as SITES rows."""
    import scaling_laws as SL
    return [(sid, "se_scale", sid.split(".")[0], va, SE_SITE_HELPER[renderer],
             ("was the native Buffer_box_sprite (0x5E2DD3)" if va == SL.SE_UNION_FRAME_SITE else
              f"was {{rel32:{renderer}}}") + "; half-open R-1 / B-1 at g>16")
            for va, (sid, renderer) in SL.SE_HALFOPEN_FRAME_SITES.items()]


def main() -> int:
    for name, (off, end, sym, _tva) in HELPERS.items():
        b = assemble(name)
        print(f"; {name} {len(b)} B @{off:#x}..{off + len(b):#x} (slot to {end:#x})" + (f" -> {sym}" if sym else ""))
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    for sid, grp, fn, va, helper, note in SITES + se_sites():
        print(f"; site {sid} ({grp}, {fn}) @{va:#x}: new_bytes \"E8 {{rel32:{helper}}}\"   # {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
