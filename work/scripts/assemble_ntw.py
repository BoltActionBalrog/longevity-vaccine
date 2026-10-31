#!/usr/bin/env python
"""ntw_scale bake (2026-09-19): the TECH BREAKTHROUGH window ("OUR RESEARCHERS HAVE MADE A
BREAKTHROUGH"; Thinker's NetTechWin 0x811E40, builder 0x483F90, painter 0x483950).

PORT OF: scaling_laws.py :: ntw_layout / ntw_caption_size / ntw_ts_inset_delta / ntw_pad_delta /
ntw_icon (the SOURCE OF TRUTH).  Parity: tests\\test_ntw_asm_parity.py.

The builder derives 17 rects from the constant window rect {0,0,550,600} by additive immediates and
stores every one in the object (+0xA14..+0xB20) BEFORE it creates the window; everything after reads
the fields.  So ONE lever re-runs vanilla's cascade at device density over those fields:

  t_ntw_build   0x4842E7 `call GraphicWin_init_2` (ecx = esi = this): g>16 -> t_ntw_rects, arm
                g_ntw_armed + g_netwin_active (label-gated button 2D zoom, TextScroll bar scale).
  t_ntw_rects   CALL helper (esi = this): the law's cascade, every constant s(c) (button dims fl(c)).
  t_ntw_capsz   0x484301 `call Win_center` (ecx = this): [+0x16C] = s(0x1A), then Win_center.
  t_ntw_ts4/3   the two TextScroll_attach sites: the engine insets the (now device) panel rect by the
                NATIVE 4 / 3 -> x,y += d; w,h -= 2d, d = s(n) - n.
  t_ntw_modal   0x48478D `call [edx+0xE4]` (Win_set_modal; the builder is MODAL and loops through
                Datalinks, whose leave writes g_netwin_active := 0): re-arm, run the modal, disarm.
  t_ntw_gate    E8 helper in front of t_mon_gate (thunk_btn_shrink's gate call): the three
                breakthrough FlatButtons (OK + the two unlabelled icon buttons) -> admit while armed.
  t_ntw_bm / t_ntw_bmdf   painter frames: R-1/B-1 rect copy (law bandmap_rect_from_halfopen) ->
                thunk_box_thick_hollow_flat (d5a0) / thunk_box_thick_devfill (d528, d618).
  t_ntw_ring    the OK ring: the painter builds it as OK -/+ native 3 -> -/+ d more, then t_ntw_bm.
  (captions)    the 5 slot-centred Buffer_write_cent_l_7 captions need NO lever: measured on the first bake
                (shots 20260919-1543xx) the un-nudged ink sits within 1.5 px of vanilla x g/16 at 4K/1600/1920;
                a (g-16)>>3 nudge put it 3-4 px high at 4K (removed).
  t_ntw_title   the tech name: rect copy L+d, T+d, R-d, B+d (the painter inset it by native 3).
  t_ntw_icon    Sprite_draw_mono_scaled site: x/y/num per ntw_icon from the painter's own locals
                (caller ebp frame), then the enlarge path's idx 0x0F output recoloured to the
                mono colour arg inside the icon area (the DL tech-page finding: a num > den draw
                is not mono).
  t_ntw_tfont   find_font(40,0) title site: t_ffn_at on a private slot (fl(40g/16) is above the pool).
  t_ntw_nostripe  head of thunk_btn_2dscale's post-zoom call: the two icon buttons (aperiodic pixel art) skip
                the stripes/devfill/ring pass (fe_pair_remap restriped their purple speckle = "garbled colours").
  t_ntw_wheel_down/up   heads of the WinProc wheel_scroll chain (-> t_rw -> t_dl -> dw): while this window is the
                modal top a notch chevron-presses the list under the cursor if it scrolls, else the first
                engaged of quote, list0..3; always swallowed.  (uimod wheel.cpp must list vtbl 0x66CE5C so the
                notch is posted while the map shows.)
REUSED: backdrop 0x6846B0 -> thunk_tutwin_backdrop (the popup chain's ornate arm: plain devfill would
        tile its device fill over the 8-9 px metal band); the 8 other find_font sites -> t_ffn.
g<=16: every thunk tail-jumps / passes through to the native callee untouched.

Usage: py assemble_ntw.py            (assemble + checks)
       py assemble_ntw.py --splice   (also splice into ..\\patches\\patches.yaml, byte-safe, idempotent; a call site
                                      a later group has put its own chain head on is left as is when that head's
                                      tail chain reaches ours -- splice(); tests\\test_ntw_asm_parity.py -k splice)
"""
from __future__ import annotations

import functools
import pathlib
import re
import struct
import sys

import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
BASE_OFF = 0x2E920                     # cave_map: 0x2E91C..0x30000 FREE
CODE_OFF = 0x2EA00
LIMIT_OFF = 0x30000
G = 0x668740                           # g_popup_scale_num

# ---- engine / cave anchors ---------------------------------------------------------
NTW = 0x00811E40                       # NetTechWin_g
BTN_OK, BTN_1, BTN_2 = NTW + 0xB2C, NTW + 0x1678, NTW + 0x21C4
GW_INIT2 = 0x005D50A0
WIN_CENTER = 0x005ED5C0
TS_ATTACH = 0x006292D0
BOX_SPRITE = 0x005E2DD3
CENT7 = 0x005DD130
MONO_FN = 0x005E3E00
FIND_FONT = 0x005882F0
HOLLOWFLAT = PCAVE2 + 0x140
DEVFILL = PCAVE2 + 0x42A0
T_FFN = PCAVE2 + 0x2E570
T_FFN_AT = PCAVE2 + 0x2E490
T_MON_GATE = PCAVE2 + 0x2B6D0
RINGFIX = PCAVE2 + 0x1C800                 # thunk_btn_ringfix (thunk_btn_2dscale's post-zoom stripes/ring call)
EDGEBAND = PCAVE2 + 0x37140                # t_btn_edgeband (2026-10-25 W2D F39, assemble_edge_stroke.py): CALLs ringfix,
                                           # then the 9-slice hover face's K-wide edge bands -- the pass-through target
RW_WHEEL_DOWN, RW_WHEEL_UP = PCAVE2 + 0x23F90, PCAVE2 + 0x24110     # previous wheel chain heads (rw -> dl -> dw)
MODAL_TOP, BASEPOP = 0x009B7AE0, 0x009B8D7C
GET_TARGET = 0x005F6A50                    # Win_get_active_target (the wheel sites' original callee)
CHEVRON = 0x00606B20                       # ScrollBar_on_chevron thiscall RET 4 (1 up / 2 down)
IAT_GETCURSORPOS, IAT_SCREENTOCLIENT, G_HWND = 0x00669284, 0x006692D4, 0x009B7B28
WHEEL_STC = PCAVE2 + 0x1292C   # t_wheel_stc (assemble_rw.WHEEL_STC): ScreenToClient drop-in, client -> backbuffer when PRACX stretches
TS_QUOTE, TS_LIST0, TS_STRIDE = NTW + 0xDC24, NTW + 0x2DA4, 0x2BA0
ORNATE_BD = PCAVE2 + 0xA920                # thunk_tutwin_backdrop: ornate 0x6846B0 -> devfill + thunk_hollow_keyint over it
G_NETWIN = PCAVE2 + 0x4800
REUSED = {"thunk_box_thick_hollow_flat": HOLLOWFLAT, "thunk_box_thick_devfill": DEVFILL, "t_ffn": T_FFN,
          "t_ffn_at": T_FFN_AT, "t_mon_gate": T_MON_GATE, "g_netwin_active": G_NETWIN,
          "thunk_tutwin_backdrop": ORNATE_BD, "thunk_btn_ringfix": RINGFIX, "t_btn_edgeband": EDGEBAND,
          "t_rw_wheel_down": RW_WHEEL_DOWN, "t_rw_wheel_up": RW_WHEEL_UP,
          "t_wheel_stc": WHEEL_STC}     # (2026-10-25: the shipped yaml calls it {rel32:t_wheel_stc}; templ() now emits that)

# ---- cells (zero-init section padding) ----------------------------------------------
K_NAMES = ["W", "H", "O", "P", "HDR", "ICON", "CAP", "LIST", "OKH", "GAP4", "BW", "BH"]
K_SRC = {"W": (SL.NTW_WIN[0], "HD"), "H": (SL.NTW_WIN[1], "HD"), "O": (SL.NTW_OUTER, "HD"), "P": (SL.NTW_PAD, "HD"),
         "HDR": (SL.NTW_HEADER_H, "HD"), "ICON": (SL.NTW_ICON_H, "HD"), "CAP": (SL.NTW_CAPTION_H, "HD"),
         "LIST": (SL.NTW_LIST_H, "HD"), "OKH": (SL.NTW_OK_H, "FL"), "GAP4": (SL.NTW_OK_GAP, "HD"),
         "BW": (SL.NTW_ICONBTN[0], "FL"), "BH": (SL.NTW_ICONBTN[1], "FL")}
assert SL.NTW_QUOTE_TEXT_GAP == SL.NTW_OK_GAP          # one cell serves both 4s
CELLS = [("g_ntw_k", 4 * 16), ("g_ntw_rect", 16), ("g_ntw_armed", 4), ("g_ntw_icol", 4), ("g_ntw_titlefont", 0x30)]
CELL = {}
_o = BASE_OFF
for _n, _sz in CELLS:
    CELL[_n] = PCAVE2 + _o
    _o = (_o + _sz + 3) & ~3
assert _o <= CODE_OFF
K = {n: CELL["g_ntw_k"] + 4 * i for i, n in enumerate(K_NAMES)}
RECT = CELL["g_ntw_rect"]
ARMED = CELL["g_ntw_armed"]
ICOL = CELL["g_ntw_icol"]
TFONT = CELL["g_ntw_titlefont"]
F = dict(SL.NTW_RECT_FIELDS)


def HD(reg: str) -> str:
    """reg = scale_px(reg, g) = half_down(reg*g, 16)."""
    return f"imul {reg}, dword ptr [{G:#x}]\n    lea {reg}, [{reg}*2+15]\n    sar {reg}, 5"


def FL(reg: str) -> str:
    return f"imul {reg}, dword ptr [{G:#x}]\n    sar {reg}, 4"


def k(n: str) -> str:
    return f"dword ptr [{K[n]:#x}]"


def put(off: int, l: str, t: str, r: str, b: str) -> str:
    """store 4 register/imm operands to the rect field at esi+off"""
    return "\n".join(f"    mov dword ptr [esi+{off + 4 * i:#x}], {v}" for i, v in enumerate((l, t, r, b)))


def asm_rects() -> str:
    a = ["    pushad"]
    for n in K_NAMES:
        v, kind = K_SRC[n]
        a += [f"    mov eax, {v}", "    " + (HD if kind == "HD" else FL)("eax"), f"    mov {k(n)}, eax"]
    a += [
        # win
        "    xor eax, eax", f"    mov ecx, {k('W')}", f"    mov edx, {k('H')}", put(F["win"], "eax", "eax", "ecx", "edx"),
        # ebx = il = O+P ; edx = ir = W-il
        f"    mov ebx, {k('O')}", f"    add ebx, {k('P')}", f"    mov edx, {k('W')}", "    sub edx, ebx",
        # ok: B = H-il, T = B-OKH ; content_b = T - P - GAP4 -> edi
        f"    mov eax, {k('H')}", "    sub eax, ebx", "    mov ecx, eax", f"    sub ecx, {k('OKH')}",
        put(F["ok"], "ebx", "ecx", "edx", "eax"),
        "    mov edi, ecx", f"    sub edi, {k('P')}", f"    sub edi, {k('GAP4')}",
        # content (O, O, W-O, content_b)
        f"    mov eax, {k('O')}", f"    mov ecx, {k('W')}", "    sub ecx, eax", put(F["content"], "eax", "eax", "ecx", "edi"),
        # header: t = il
        "    mov ecx, ebx", "    mov eax, ecx", f"    add eax, {k('HDR')}", put(F["header"], "ebx", "ecx", "edx", "eax"),
        f"    mov ecx, eax", f"    add ecx, {k('P')}",
        # icon
        "    mov eax, ecx", f"    add eax, {k('ICON')}", put(F["icon"], "ebx", "ecx", "edx", "eax"),
        "    mov ecx, eax", f"    add ecx, {k('P')}",
        # ebp = mid = ((ir-il)+P)/2 - P + il
        "    mov ebp, edx", "    sub ebp, ebx", f"    add ebp, {k('P')}", "    sar ebp, 1", f"    sub ebp, {k('P')}", "    add ebp, ebx",
    ]
    for cap, lst in (("cap_t", "list_t"), ("cap_b", "list_b")):
        for name, hk in ((cap, "CAP"), (lst, "LIST")):
            a += ["    mov eax, ecx", f"    add eax, {k(hk)}",
                  put(F[name + "l"], "ebx", "ecx", "ebp", "eax"),
                  f"    add ebp, {k('P')}", put(F[name + "r"], "ebp", "ecx", "edx", "eax"), f"    sub ebp, {k('P')}",
                  "    mov ecx, eax", f"    add ecx, {k('P')}"]
    a += [
        # quote (il, t, ir, content_b - P); quote_text L/T/B same
        "    mov eax, edi", f"    sub eax, {k('P')}", put(F["quote"], "ebx", "ecx", "edx", "eax"),
        f"    mov dword ptr [esi+{F['quote_text']:#x}], ebx", f"    mov dword ptr [esi+{F['quote_text'] + 4:#x}], ecx",
        f"    mov dword ptr [esi+{F['quote_text'] + 12:#x}], eax",
        # buttons: b_b = content_b - 2P (eax - P); b_t = b_b - BH; b2_r = (W-O) - 2P
        f"    sub eax, {k('P')}", "    mov ecx, eax", f"    sub ecx, {k('BH')}",
        f"    mov edx, {k('W')}", f"    sub edx, {k('O')}", f"    sub edx, {k('P')}", f"    sub edx, {k('P')}",
        "    mov ebp, edx", f"    sub ebp, {k('BW')}", put(F["btn2"], "ebp", "ecx", "edx", "eax"),
        "    mov edx, ebp", f"    sub edx, {k('P')}", "    mov ebp, edx", f"    sub ebp, {k('BW')}",
        put(F["btn1"], "ebp", "ecx", "edx", "eax"),
        f"    sub ebp, {k('GAP4')}", f"    mov dword ptr [esi+{F['quote_text'] + 8:#x}], ebp",
        "    popad", "    ret",
    ]
    return "\n".join(a)


def _rect_copy(d_l: str = "", d_t: str = "", d_r: str = "", d_b: str = "", arg: str = "esp+4") -> str:
    """copy the RECT at [arg] into g_ntw_rect applying per-edge asm fix-ups on edx, repoint [arg]."""
    out = [f"    mov eax, dword ptr [{arg}]"]
    for i, fix in enumerate((d_l, d_t, d_r, d_b)):
        out += [f"    mov edx, dword ptr [eax+{4 * i}]"] + ([f"    {fix}"] if fix else []) + [f"    mov dword ptr [{RECT + 4 * i:#x}], edx"]
    out.append(f"    mov dword ptr [{arg}], {RECT:#x}")
    return "\n".join(out)


PAD_D = f"""    mov ecx, {SL.NTW_PAD}
    {HD("ecx")}
    sub ecx, {SL.NTW_PAD}"""           # ecx = d = s(3) - 3

THUNKS = [
    ("t_ntw_rects", asm_rects()),
    ("t_ntw_build", f"""
    cmp dword ptr [{G:#x}], 16
    jle nb_native
    call t_ntw_rects
    mov dword ptr [{ARMED:#x}], 1
    mov dword ptr [{G_NETWIN:#x}], 1
nb_native:
    jmp {GW_INIT2:#x}
"""),
    ("t_ntw_capsz", f"""
    cmp dword ptr [{G:#x}], 16
    jle nc_native
    mov eax, dword ptr [ecx+0x16C]
    {HD("eax")}
    mov dword ptr [ecx+0x16C], eax
nc_native:
    jmp {WIN_CENTER:#x}
"""),
] + [(f"t_ntw_ts{n}", f"""
    cmp dword ptr [{G:#x}], 16
    jle nt_native
    mov eax, {n}
    {HD("eax")}
    sub eax, {n}
    add dword ptr [esp+4], eax
    add dword ptr [esp+8], eax
    add eax, eax
    sub dword ptr [esp+0xC], eax
    sub dword ptr [esp+0x10], eax
nt_native:
    jmp {TS_ATTACH:#x}
""") for n in (SL.NTW_LIST_TS_INSET, SL.NTW_QUOTE_TS_INSET)] + [
    ("t_ntw_modal", f"""
    cmp dword ptr [{G:#x}], 16
    jle nm_go
    mov dword ptr [{ARMED:#x}], 1
    mov dword ptr [{G_NETWIN:#x}], 1
nm_go:
    push dword ptr [esp+0xC]
    push dword ptr [esp+0xC]
    push dword ptr [esp+0xC]
    call dword ptr [edx+0xE4]
    cmp dword ptr [{ARMED:#x}], 0
    je nm_out
    mov dword ptr [{ARMED:#x}], 0
    mov dword ptr [{G_NETWIN:#x}], 0
nm_out:
    ret 0xC
"""),
    ("t_ntw_gate", f"""
    cmp dword ptr [{ARMED:#x}], 0
    je ng_pass
    cmp esi, {BTN_OK:#x}
    je ng_hit
    cmp esi, {BTN_1:#x}
    je ng_hit
    cmp esi, {BTN_2:#x}
    je ng_hit
ng_pass:
    push {T_MON_GATE:#x}
    ret
ng_hit:
    mov eax, 1
    ret
"""),
    ("t_ntw_bm", f"""
    cmp dword ptr [{G:#x}], 16
    jle nbm_native
{_rect_copy(d_r="dec edx", d_b="dec edx")}
    push {HOLLOWFLAT:#x}
    ret
nbm_native:
    jmp {BOX_SPRITE:#x}
"""),
    ("t_ntw_bmdf", f"""
    cmp dword ptr [{G:#x}], 16
    jle nbd_native
{_rect_copy(d_r="dec edx", d_b="dec edx")}
    push {DEVFILL:#x}
    ret
nbd_native:
    jmp {BOX_SPRITE:#x}
"""),
    ("t_ntw_ring", f"""
    cmp dword ptr [{G:#x}], 16
    jle nr_native
    push ecx
{PAD_D}
{_rect_copy(d_l="sub edx, ecx", d_t="sub edx, ecx", d_r="lea edx, [edx+ecx-1]", d_b="lea edx, [edx+ecx-1]", arg="esp+8")}
    pop ecx
    push {HOLLOWFLAT:#x}
    ret
nr_native:
    jmp {BOX_SPRITE:#x}
"""),
    ("t_ntw_title", f"""
    cmp dword ptr [{G:#x}], 16
    jle ntt_native
    push ecx
{PAD_D}
{_rect_copy(d_l="add edx, ecx", d_t="add edx, ecx", d_r="sub edx, ecx", d_b="add edx, ecx", arg="esp+0xC")}
    pop ecx
ntt_native:
    jmp {CENT7:#x}
"""),
    # E8 from 0x483E60; ecx = sprite; [esp+4] dest, +8 key, +0xC x, +0x10 y, +0x14 col, +0x18 num, +0x1C den; RET 0x1C.
    # caller frame (ebp): -0x18 L, -0x10 R, -0x14 top_native, -4 h_native.
    ("t_ntw_icon", f"""
    cmp dword ptr [{G:#x}], 16
    jle ni_native
    push ebx
    push esi
    push edi
    push ecx
{PAD_D}
    mov ebx, ecx
    pop ecx
    mov esi, dword ptr [{G:#x}]
    imul esi, {SL.NTW_ICON_BOX}
    sar esi, 4
    mov dword ptr [esp+0x24], esi
    mov eax, dword ptr [ebp-0x10]
    sub eax, dword ptr [ebp-0x18]
    sub eax, esi
    cdq
    sub eax, edx
    sar eax, 1
    add eax, dword ptr [ebp-0x18]
    mov dword ptr [esp+0x18], eax
    mov eax, dword ptr [ebp-4]
    sub eax, ebx
    sub eax, ebx
    sub eax, esi
    cdq
    sub eax, edx
    sar eax, 1
    add eax, dword ptr [ebp-0x14]
    add eax, ebx
    mov dword ptr [esp+0x1C], eax
    mov eax, dword ptr [esp+0x20]
    mov dword ptr [{ICOL:#x}], eax
    mov edi, dword ptr [esp+0x10]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    call {MONO_FN:#x}
    push eax
    test edi, edi
    je ni_out
    mov esi, dword ptr [edi+0x54]
    test esi, esi
    je ni_out
    mov ecx, dword ptr [ebp-0x14]
    add ecx, ebx
    test ecx, ecx
    jns ni_y0
    xor ecx, ecx
ni_y0:
    mov edx, dword ptr [ebp-0x14]
    add edx, dword ptr [ebp-4]
    sub edx, ebx
    mov eax, dword ptr [edi+0x84]
    test eax, eax
    jns ni_hp
    neg eax
ni_hp:
    cmp edx, eax
    jle ni_y1
    mov edx, eax
ni_y1:
    mov ebx, edx
ni_row:
    cmp ecx, ebx
    jge ni_out
    mov eax, ecx
    imul eax, dword ptr [edi+0x4A8]
    add eax, esi
    mov edx, dword ptr [ebp-0x18]
    test edx, edx
    jns ni_col
    xor edx, edx
ni_col:
    cmp edx, dword ptr [ebp-0x10]
    jge ni_next
    cmp edx, dword ptr [edi+0x80]
    jge ni_next
    cmp byte ptr [eax+edx], 0x0F
    jne ni_skip
    push ecx
    mov cl, byte ptr [{ICOL:#x}]
    mov byte ptr [eax+edx], cl
    pop ecx
ni_skip:
    inc edx
    jmp ni_col
ni_next:
    inc ecx
    jmp ni_row
ni_out:
    pop eax
    pop edi
    pop esi
    pop ebx
    ret 0x1C
ni_native:
    jmp {MONO_FN:#x}
"""),
    ("t_ntw_tfont", f"""
    cmp dword ptr [{G:#x}], 16
    jle nf_native
    push dword ptr [{G:#x}]
    push dword ptr [esp+0xC]
    push dword ptr [esp+0xC]
    push {TFONT:#x}
    call {T_FFN_AT:#x}
    add esp, 0x10
    ret
nf_native:
    jmp {FIND_FONT:#x}
"""),
]

def _wheel_candidates() -> str:
    """cursor-over list first (window-local point eax,edx vs the list rect FIELDS), then the first engaged of
    quote, list0..3.  esi = TextScroll, edi = its ScrollBar (+0xA20); falls to wh_eaten when nothing is engaged.
    ENGAGED = TextScroll shown AND the BAR shown (bar Win+0x9C bit0 = TS+0xABC, the flag TextScroll_draw reserves the
    bar width on) AND range max > min: the range stays live on a hidden bar (v2 scrolled a box with no bar)."""
    def engaged(ts: int, nxt: str) -> str:
        return f"""
    mov     esi, {ts:#x}
    test    byte ptr [esi+0x9C], 1
    jz      {nxt}
    lea     edi, [esi+0xA20]
    test    byte ptr [edi+0x9C], 1
    jz      {nxt}
    cmp     dword ptr [edi+0xC4], 0
    je      {nxt}
    mov     ecx, dword ptr [edi+0xA24]
    cmp     ecx, dword ptr [edi+0xA20]
    jg      wh_have"""
    out = ""
    lists = [F["list_tl"], F["list_tr"], F["list_bl"], F["list_br"]]
    for i, f in enumerate(lists):
        out += f"""
wh_h{i}:
    cmp     eax, dword ptr [{NTW + f:#x}]
    jl      wh_h{i + 1}
    cmp     eax, dword ptr [{NTW + f + 8:#x}]
    jge     wh_h{i + 1}
    cmp     edx, dword ptr [{NTW + f + 4:#x}]
    jl      wh_h{i + 1}
    cmp     edx, dword ptr [{NTW + f + 12:#x}]
    jge     wh_h{i + 1}{engaged(TS_LIST0 + i * TS_STRIDE, "wh_h4")}"""
    out += "\nwh_h4:"
    order = [TS_QUOTE] + [TS_LIST0 + i * TS_STRIDE for i in range(4)]
    for i, ts in enumerate(order):
        out += f"\nwh_c{i}:{engaged(ts, f'wh_c{i + 1}')}"
    out += f"\nwh_c{len(order)}:\n    jmp     wh_eaten"
    return out


WHEEL_THUNKS = [
    # head of the WinProc wheel_scroll KEYDOWN site chain (E8 replacing `call Win_get_active_target`;
    # [esp+0x68] = wParam, [esp+0x6C] = lParam at entry).  UNGATED on g, like the DW/DL wheel arms.
    ("t_ntw_wheel_down", f"""
    cmp     dword ptr [{BASEPOP:#x}], 0
    jne     wh_chain
    cmp     dword ptr [{MODAL_TOP:#x}], {NTW:#x}
    jne     wh_chain
    call    {GET_TARGET:#x}
    test    eax, eax
    jz      wh_xout
    cmp     dword ptr [esp+0x6C], 0
    jne     wh_xout
    mov     edx, dword ptr [esp+0x68]
    cmp     edx, 0x26
    je      wh_go
    cmp     edx, 0x28
    jne     wh_xout
wh_go:
    push    ebx
    push    esi
    push    edi
    mov     ebx, 1
    cmp     edx, 0x26
    je      wh_dir
    mov     ebx, 2
wh_dir:
    sub     esp, 8
    push    esp
    call    dword ptr [{IAT_GETCURSORPOS:#x}]
    push    esp
    push    dword ptr [{G_HWND:#x}]
    call    {WHEEL_STC:#x}
    nop
    pop     eax
    pop     edx
    sub     eax, dword ptr [{NTW + 0x13C:#x}]
    sub     edx, dword ptr [{NTW + 0x140:#x}]
{_wheel_candidates()}
wh_have:
    push    ebx
    mov     ecx, edi
    call    {CHEVRON:#x}
    mov     edx, dword ptr [esi]
    mov     ecx, esi
    call    dword ptr [edx+0xFC]
wh_eaten:
    xor     eax, eax
    pop     edi
    pop     esi
    pop     ebx
    ret
wh_xout:
    ret
wh_chain:
    push    {RW_WHEEL_DOWN:#x}
    ret
"""),
    ("t_ntw_wheel_up", f"""
    cmp     dword ptr [{BASEPOP:#x}], 0
    jne     wu_chain
    cmp     dword ptr [{MODAL_TOP:#x}], {NTW:#x}
    jne     wu_chain
    call    {GET_TARGET:#x}
    test    eax, eax
    jz      wu_xout
    cmp     dword ptr [esp+0x6C], 0
    jne     wu_xout
    mov     edx, dword ptr [esp+0x68]
    cmp     edx, 0x26
    je      wu_eat
    cmp     edx, 0x28
    jne     wu_xout
wu_eat:
    xor     eax, eax
wu_xout:
    ret
wu_chain:
    push    {RW_WHEEL_UP:#x}
    ret
"""),
    # thunk_btn_2dscale's post-zoom call (esi = button): the two icon buttons are APERIODIC pixel art (speckle
    # texture, no dither pair) -> no stripes / devfill / ring pass: fe_pair_remap restriped their purple members.
    # Every other button passes on to t_btn_edgeband (2026-10-25 W2D F39), which CALLs thunk_btn_ringfix first.
    ("t_ntw_nostripe", f"""
    cmp     dword ptr [{ARMED:#x}], 0
    je      ns_pass
    cmp     esi, {BTN_1:#x}
    je      ns_skip
    cmp     esi, {BTN_2:#x}
    je      ns_skip
ns_pass:
    push    {EDGEBAND:#x}
    ret
ns_skip:
    ret
"""),
]
THUNKS += WHEEL_THUNKS

ks = Ks(KS_ARCH_X86, KS_MODE_32)


def assemble_all() -> dict[str, tuple[int, bytes]]:
    names = {n: PCAVE2 + CODE_OFF for n, _ in THUNKS}
    out: dict[str, tuple[int, bytes]] = {}
    for _pass in range(4):
        off, new = CODE_OFF, {}
        for name, asm in THUNKS:
            src = asm
            for n2, va in sorted(names.items(), key=lambda kv: -len(kv[0])):
                src = re.sub(rf"\b{n2}\b", f"{va:#x}", src)
            enc, _ = ks.asm(src, PCAVE2 + off)
            b = bytes(enc)
            out[name] = (off, b)
            new[name] = PCAVE2 + off
            off = (off + len(b) + 15) & ~15
        if new == names:
            break
        names = new
    else:
        raise RuntimeError("layout did not converge")
    assert off <= LIMIT_OFF, hex(off)
    return out


OUT = assemble_all()
VA = {n: PCAVE2 + o for n, (o, _) in OUT.items()}

pe = pefile.PE(str(config.terranx_bak()), fast_load=True)
IMG = pe.OPTIONAL_HEADER.ImageBase


def orig(va: int, n: int) -> bytes:
    for s in pe.sections:
        a = IMG + s.VirtualAddress
        if a <= va < a + s.SizeOfRawData:
            return s.get_data()[va - a: va - a + n]
    raise KeyError(hex(va))


# (id, function, va, length, native callee (None = indirect), target, note)
P, B = "NetTechWin_draw", "NetTechWin_exec"
SITES = [
    ("ntw_exec.gwinit", B, 0x4842E7, 5, GW_INIT2, "t_ntw_build", "GraphicWin_init_2: the 17 rect fields re-derived at device density first"),
    ("ntw_exec.win_center", B, 0x484301, 5, WIN_CENTER, "t_ntw_capsz", "Win_center: caption size [+0x16C] = s(0x1A)"),
    ("ntw_exec.ts_lists", B, 0x4843C6, 5, TS_ATTACH, "t_ntw_ts4", "TextScroll_attach x4 (unlock lists): native inset 4 -> s(4)"),
    ("ntw_exec.ts_quote", B, 0x4844AA, 5, TS_ATTACH, "t_ntw_ts3", "TextScroll_attach (quote): native inset 3 -> s(3)"),
    ("ntw_exec.modal", B, 0x48478D, 6, None, "t_ntw_modal", "call [edx+0xE4] Win_set_modal: arm/disarm around every modal pass"),
    ("ntw_draw.backdrop", P, 0x483998, 5, BOX_SPRITE, "thunk_tutwin_backdrop",
     "ornate 0x6846B0 window backdrop {0,0,W,H}: the popup chain's ornate arm (devfill interior + metal band-mapped over it)"),
    ("ntw_draw.content_d5a0", P, 0x4839AB, 5, BOX_SPRITE, "t_ntw_bm", "content frame"),
    ("ntw_draw.okring_d5a0", P, 0x4839E6, 5, BOX_SPRITE, "t_ntw_ring", "OK ring = OK rect -/+ s(3)"),
    ("ntw_draw.header_d528", P, 0x483A25, 5, BOX_SPRITE, "t_ntw_bmdf", "header box"),
]
for _i, (_bx, _tx) in enumerate(((0x483AAE, 0x483B07), (0x483B1A, 0x483B73), (0x483B86, 0x483BDE), (0x483BF1, 0x483C4A))):
    SITES.append((f"ntw_draw.cap{_i}_d618", P, _bx, 5, BOX_SPRITE, "t_ntw_bmdf", f"panel caption box {_i}"))
for _i, _bx in enumerate((0x483C5D, 0x483C70, 0x483C83, 0x483C96)):
    SITES.append((f"ntw_draw.list{_i}_d528", P, _bx, 5, BOX_SPRITE, "t_ntw_bmdf", f"unlock list box {_i}"))
SITES += [
    ("ntw_draw.icon_d528", P, 0x483CA9, 5, BOX_SPRITE, "t_ntw_bmdf", "icon panel box"),
    ("ntw_draw.title_text", P, 0x483DB1, 5, CENT7, "t_ntw_title", "tech name: native-3 inset -> s(3)"),
    ("ntw_draw.icon", P, 0x483E60, 5, MONO_FN, "t_ntw_icon", "Sprite_draw_mono_scaled: num 160 -> 10g, re-centred, 0x0F recolour"),
    ("ntw_draw.quote_d528", P, 0x483E73, 5, BOX_SPRITE, "t_ntw_bmdf", "quote box"),
    ("ntw_draw.font_header", P, 0x4839F5, 5, FIND_FONT, "t_ffn", "find_font(16,1) -> the face law"),
    ("ntw_draw.font_title", P, 0x483CB8, 5, FIND_FONT, "t_ntw_tfont", "find_font(40,0) -> private slot at fl(40g/16)"),
]
for _i, _va in enumerate((0x4843DA, 0x4843E7, 0x4843F4, 0x484401)):
    SITES.append((f"ntw_exec.font_list{_i}", B, _va, 5, FIND_FONT, "t_ffn", "find_font(14,v) unlock lists -> the face law"))
for _i, _va in enumerate((0x4844BB, 0x4844C8, 0x4844D5)):
    SITES.append((f"ntw_exec.font_quote{_i}", B, _va, 5, FIND_FONT, "t_ffn", "find_font(12,v) quote -> the face law"))

for sid, fn, va, ln, callee, tgt, note in SITES:
    o = orig(va, ln)
    if callee is None:
        assert o == bytes.fromhex("FF92E4000000"), (sid, o.hex())
    else:
        assert o == b"\xE8" + struct.pack("<i", callee - (va + 5)), (sid, o.hex())

GROUP = "ntw_scale"
SRC = "src assemble_ntw.py"
M_SYM = (f"  # ==== {GROUP} symbols (2026-09-19, {SRC}) ====\n", f"# ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} cave ({SRC}; laws scaling_laws.ntw_*; parity tests\\test_ntw_asm_parity.py) ====\n", f"# ==== {GROUP} END ==== cave\n")
M_GRP = (f"  # ==== {GROUP} group ====\n", f"# ==== {GROUP} END ==== groups\n")
M_SITE = (f"  # ==== {GROUP} sites (2026-09-19; {SRC}) ====\n", f"# ==== {GROUP} END ==== sites\n")


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def templ(name: str) -> str:
    """cave bytes with inter-cave calls as {rel32:} and push-ret tail jumps as {abs32:} placeholders (engine targets stay literal)."""
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    from capstone.x86 import X86_OP_IMM
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    off, b = OUT[name]
    syms = {v: n for n, v in {**REUSED, **VA}.items()}
    out = []
    for ins in md.disasm(b, PCAVE2 + off):
        raw = hexs(ins.bytes)
        if ins.mnemonic == "call" and ins.size == 5 and ins.operands[0].type == X86_OP_IMM:
            tgt = ins.operands[0].imm & 0xFFFFFFFF
            if tgt in syms:
                raw = f"E8 {{rel32:{syms[tgt]}}}"
        elif ins.mnemonic == "push" and ins.size == 5 and ins.bytes[0] == 0x68:
            tgt = ins.operands[0].imm & 0xFFFFFFFF      # cave law: inter-thunk tail jumps are push abs32 / ret
            if tgt in syms and tgt != TFONT:
                raw = f"68 {{abs32:{syms[tgt]}}}"
        out.append(raw)
    return " ".join(out)


CAVE_NOTES = {   # comment line emitted above a cave entry (the shipped yaml carries it; a splice must not drop it)
    "t_ntw_nostripe": "2026-10-25 W2D F39: the tail push target thunk_btn_ringfix -> t_btn_edgeband (which CALLs ringfix first).",
}


@functools.lru_cache(maxsize=None)          # a pure function of this module's (import-time) assembly
def blocks() -> tuple[str, str, str, str]:
    sym = M_SYM[0]
    for n, sz in CELLS:
        sym += f"  {n}:{' ' * max(1, 29 - len(n))}{{ cave: pcave2, offset: {CELL[n] - PCAVE2:#07x}, size: {sz} }}\n"
    for n, (o, b) in OUT.items():
        sym += f"  {n}:{' ' * max(1, 29 - len(n))}{{ cave: pcave2, offset: {o:#07x} }}   # {GROUP} ({len(b)}B)\n"
    sym += M_SYM[1]
    cave = M_CAVE[0]
    for n, (o, _b) in OUT.items():
        if n in CAVE_NOTES:
            cave += f"      # {CAVE_NOTES[n]}\n"
        cave += f"      - id: {n}\n        offset: {o:#07x}\n        bytes: \"{templ(n)}\"\n"
    cave += M_CAVE[1]
    grp = M_GRP[0] + f"""  - id: {GROUP}
    description: >
      TECH BREAKTHROUGH window (NetTechWin 0x811E40; builder 0x483F90, painter 0x483950) scales to the
      popup scale.  One lever re-runs vanilla's rect cascade at device density over the 17 object rect
      fields just before GraphicWin_init_2 (law scaling_laws.ntw_layout: every additive constant s(c),
      the quote box takes the remainder exactly as in vanilla, button dims floor for the 2D-zoom's ceil
      inverse); TextScroll insets, caption size, the OK ring, the title inset and the icon (num 10g,
      re-centred, enlarge-path 0x0F recoloured to the mono colour) follow through call-site wrappers;
      frames via the band-map thunks with R-1/B-1, the ornate backdrop via thunk_tutwin_backdrop; fonts via the face law (t_ffn,
      the 40 px tech name on a private slot); the three FlatButtons admitted to the 2D zoom by
      t_ntw_gate (chained in front of t_mon_gate) while armed; arm + g_netwin_active bracket every modal
      pass (the builder loops through Datalinks).  Every thunk is a native pass-through at g<=16.
      Parity + law properties: tests\\test_ntw_asm_parity.py.
    code_caves:
      - pcave2
    members:
""" + "".join(f"      - {s[0]}\n" for s in SITES) + M_GRP[1]
    site = M_SITE[0]
    for sid, fn, va, ln, _callee, tgt, note in SITES:
        site += (f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n"
                 f"    virtual_addr: 0x{va:08X}\n    length: {ln}\n"
                 f"    original_bytes: \"{hexs(orig(va, ln))}\"\n"
                 f"    new_bytes:      \"E8 {{rel32:{tgt}}}{' 90' * (ln - 5)}\"\n"
                 f"    pattern: call_target_redirect\n    # {note}\n")
    site += M_SITE[1]
    return sym, cave, grp, site


RETARGETS = [   # (site template, {T} = its callee; the callee before ntw_scale; ntw's head; what) -- each site found once
    ("E8 {rel32:{T}} 85 C0 74 53", "t_mon_gate", "t_ntw_gate", "thunk_btn_shrink gate call"),
    ("E8 {rel32:{T}} C7 05 {abs32:g_btn_pending}", "thunk_btn_ringfix", "t_ntw_nostripe", "thunk_btn_2dscale stripes call"),
    ('"E8 {rel32:{T}}"', "t_rw_wheel_down", "t_ntw_wheel_down", "wheel keydown site"),
    ('"E8 {rel32:{T}}"', "t_rw_wheel_up", "t_ntw_wheel_up", "wheel keyup site"),
]
_ID_OR_BYTES = re.compile(r'^[ \t]*- id:[ \t]*(\S+)|^[ \t]*bytes:[ \t]*"([^"]*)"', re.M)   # (sites: new_bytes)
_TAIL = re.compile(r'\b68 \{abs32:(\w+)\} C3\b|\bE9 \{rel32:(\w+)\}')


def tail_edges(text: str) -> dict[str, set[str]]:
    """cave id -> the cave ids its bytes tail-jump to (the cave law: push {abs32:X} / ret, or E9 {rel32:X})."""
    out: dict[str, set[str]] = {}
    cur = None
    for m in _ID_OR_BYTES.finditer(text):
        if m.group(1) is not None:
            cur = m.group(1)
        elif cur is not None:
            out.setdefault(cur, set()).update(x or y for x, y in _TAIL.findall(m.group(2)))
            cur = None
    return out


def chains_to(edges: dict[str, set[str]], head: str, target: str) -> bool:
    """Does the tail chain entered at `head` reach `target`?  A later group puts its own head in front of ours
    (diplowin's t_dw_gate -> t_ntw_gate, t_dw_wheel_* -> t_bw_wheel_* -> t_ntw_wheel_*): the site is then ITS."""
    seen, todo = set(), [head]
    while todo:
        n = todo.pop()
        if n == target:
            return True
        if n not in seen:
            seen.add(n)
            todo.extend(edges.get(n, ()))
    return False


def retarget(data: bytes, template: str, old: str, new: str, what: str, edges=None) -> bytes:
    """The one site matching `template` whose callee is `old` (-> retargeted to `new`) or a head whose tail chain
    reaches `new` (already ours, directly or behind a later group's head: left as is).  Anything else fails closed:
    a site found zero or several times, or a chain that no longer passes through `new`.  `edges`: tail_edges(data),
    when the caller has it (a retarget rewrites a CALL's target, never a tail edge)."""
    assert template.lstrip('"').startswith("E8 {rel32:{T}}"), template
    text = data.decode("utf-8")
    edges = tail_edges(text) if edges is None else edges
    pat = re.compile(re.escape(template).replace(re.escape("{T}"), r"(\w+)"))
    hits = [m for m in pat.finditer(text) if m.group(1) == old or chains_to(edges, m.group(1), new)]
    assert len(hits) == 1, f"{what}: {len(hits)} sites call {old} or a chain through {new} (want exactly 1)"
    m = hits[0]
    if m.group(1) != old:
        return data
    return (text[:m.start(1)] + new + text[m.end(1):]).encode("utf-8")


def put_block(data: bytes, block: str, markers: tuple[str, str], anchor: str) -> bytes:
    """`block` between its markers in `data` (replacing what is there), else inserted after the `anchor` line."""
    nl = b"\r\n" if b"\r\n" in data[:4096] else b"\n"
    blk = block.replace("\n", nl.decode()).encode("utf-8")
    a, z = markers[0].strip("\n").encode(), markers[1].strip("\n").encode()
    if a in data:
        s = data.index(a)
        s = data.rfind(nl, 0, s) + len(nl)
        e = data.index(z, s) + len(z)
        if data[e:e + len(nl)] == nl:
            e += len(nl)
        assert 0 < s < e
        return data[:s] + blk + data[e:]
    anc = anchor.encode()
    assert data.count(anc) == 1, anchor
    p = data.index(anc) + len(anc)
    p = data.index(nl, p) + len(nl)
    return data[:p] + blk + data[p:]


def splice(data: bytes) -> bytes:
    """patches.yaml bytes with the four ntw_scale blocks and the four call-site retargets applied (byte-safe:
    the file's own EOL; idempotent: on the shipped yaml this is the identity)."""
    sym, cave, grp, site = blocks()
    data = put_block(data, sym, M_SYM, "# ==== msglog_scale END ==== symbols")
    data = put_block(data, cave, M_CAVE, "# ==== msglog_scale END ==== cave")
    data = put_block(data, grp, M_GRP, "# ==== msglog_scale END ==== groups")
    data = put_block(data, site, M_SITE, "# ==== msglog_scale END ==== sites")
    edges = tail_edges(data.decode("utf-8"))
    for template, old, new, what in RETARGETS:
        data = retarget(data, template, old, new, what, edges)
    return data


def main() -> int:
    for n, (o, b) in OUT.items():
        print(f"OK  {n:14s} @0x{o:05X} len={len(b):4d}")
    print(f"sites: {len(SITES)}")
    if "--splice" not in sys.argv:
        return 0
    y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    data = y.read_bytes()
    new = splice(data)
    if new == data:
        print("already spliced (no change):", y)
    else:
        y.write_bytes(new)
        print("spliced into", y)
    return 0


if __name__ == "__main__":
    sys.exit(main())
