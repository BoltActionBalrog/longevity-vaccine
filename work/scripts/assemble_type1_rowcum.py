"""Type-1 popup checkbox rows on ONE uniform pitch, labels lifted to fit, checkboxes top-aligned (F46) -- W8T v3.

PORTS OF scaling_laws.py (the SOURCE OF TRUTH; regenerate the yaml bytes from here, never hand-edit):

  t1c_barh             type1_row_h                     (the stripe-symmetric bar height)
  t1c_pn               type1_row_cum_marked            (the draw / click / label / checkbox gate: P or 0)
  t1c_calc             type1_row_cum_calc + type1_row_h + type1_row_cell(rows)
  t1c_rowtop           type1_row_top                   (CheckList_draw_item's bar top)
  t1c_hit              type1_row_at                    (the click handler's row)
  t1c_label            type1_label_lift                (the row label's rect top, lifted)
  t1c_pdesc            the label font's 'p' ink descent (GetGlyphOutlineA GGO_METRICS, cached per font)
  t1c_ckpos            type1_checkbox_y_arg            (the popup painter's checkbox y, top-aligned)
  t1c_bar              type1_bar_gate + type1_bar_restripe / type1_bar_colour   (W9B: each bar striped from its own top)

User decisions 2026-10-27: equal gaps -- one pitch P = half_down(22 g, 16) (the repo's uniform-pitch law, as W8P's
pref_tab_pitch); option B of the W8T audit -- the bar stays ~s(19) (stripe-symmetric pick), each label is lifted so its
main ink ends on the bar's last row, the checkbox sits on the bar's top row.

Placement: pcave2 0x3D6C0.. in W8T's region 0x3D6A0..0x3DFFF (cave_map --at 0x3D6A0: free from 0x3D69B to t_pref_bd
0x3E000; 0x3D6A0..0x3D6BF is the tail of t_cw_logox's pinned slot, assemble_council_mirror.HELPERS); data g_t1c_data
at 0x3DF00 (written at run time: the GetGlyphOutlineA pointer and the per-font cache).

t1c_calc -- SITE FUN_0060ed10 0x60F018 (the else-path pitch reserve), `E8 rel32 90 90 90`, the rel32 moves thunk_rowgap
  -> t1c_calc (wrap, don't relocate: t1c_calc CALLs thunk_rowgap first, which scales [+0x44] and returns ecx = [+0x68]
  + [+0x44]).  eax = the Dialog data region, esi = this.  Gate type1_row_cum_calc (the device glyph height is the real
  Buffer_text_height 0x5DCA80 of the window buffer the calc measured, ecx = esi + [[esi] + 4] + 0x444).  Gate holds:
  [+0x68] = type1_row_h, ecx = P (the caller's 0x60F021 stores [+0x60] = P * rows).  Else ecx = [+0x68] + [+0x44].
  eax / esi preserved; edx / flags clobbered (dead: the original wrote edx).

t1c_rowtop -- SITE CheckList_draw_item 0x60F1D3 (18 B) -> `E8 rel32` + 13 NOP, resuming 0x60F1E5.  In: edi = Dialog
  data, ecx = gap, ebx = r, [esp+0x14] = the multi-line `extra`.  Out: ecx = the bar top (marked: extra + s(1) + r P;
  else the 7 displaced instructions).  eax / ebx clobbered (dead).

t1c_hit -- SITE the click handler 0x60F735 (20 B) -> `E8 rel32` + 15 NOP, resuming 0x60F749 `add ebx,eax`.  In: ecx =
  Dialog data, eax = col, ebp = gap, [esp+0x1C] = y.  Out: ebx = col * rows, eax = row (y / P marked, y / ([+0x68] +
  gap) else), ebp = [+0x68] + gap, edx = the remainder.  ecx / esi / edi preserved.

t1c_label -- SITE CheckList_draw_item 0x60F472 (5 B: mov ecx,[edx+0x1c]; add edi,ecx) -> `E8 rel32`, resuming 0x60F477
  `mov [esp+0x28],edi` (the label rect top).  In: esi = this, edx = the label font (CheckList +0x970's; the engine
  puts the rect top font[+0x1C] = tmDescent below the row top and the writer the baseline font[+0x10] = cap_h below
  that), edi = the row top, [esp+0x18] = the bar height (the caller's [esp+0x14], set at 0x60F2FA; [esp+0x20] after its two pushes).  Out: edi = row top + font[+0x1c] -
  type1_label_lift(font[+0x1c], font[+0x10], t1c_pdesc, bar) for a marked list's single-line row (bar == [+0x68]);
  else row top + font[+0x1c] as vanilla.  ecx = font[+0x1c] as the displaced load left it; eax / ebx / edx / esi
  preserved (0x60F47B reads eax).

t1c_pdesc -- helper: edx = a Font struct (+8 HFONT, +0xC cell, +0x10 cap_h, +0x1C tmDescent) in, eax = the rows the
  'p' glyph's black box reaches below its origin (GetGlyphOutlineA(hdc, 'p', GGO_METRICS, &gm, 0, 0, &identity):
  gmBlackBoxY - gmptGlyphOrigin.y) out; every other register preserved.  GetGlyphOutlineA is not imported: resolved
  once through GetProcAddress(GetModuleHandleA("GDI32.dll")) (IAT 0x669124 / 0x669138) and cached; the DC is a
  CreateCompatibleDC(0) with the HFONT selected, restored and deleted.  The result is cached per (HFONT, cell,
  cap_h).  Any failure (no gdi32 handle, no proc, no DC, GDI_ERROR) -> the font's design descent font[+0x1C]
  (tmDescent, >= the ink: the label then sits a little high, never past the bar).

t1c_ckpos -- the 0x405BD4 call target (FUN_00405b20's type-1 checkbox draw; was t_ck_list, which it tail-jumps).  The
  popup is [ebp-4], its Dialog data popup + [[popup + 0x21D0] + 8] + 0x21D0 (the CheckList's, measured), the row rect
  top [ebp-0x10], bottom [ebp-8].  Marked and single-line (bottom - top == [+0x68]): the y arg [esp+0x10] (= [esp+0xC]
  at the original call) = type1_checkbox_y_arg(top).  eax / edx clobbered (dead after the call: 0x405BD9 reloads eax);
  ecx (the sprite) / ebx / esi / edi preserved.

t1c_bar (W9B, user decision 2026-10-27 "make every row identical") -- SITE FUN_00405b20.option_frame 0x405BF6, the
  bar draw (was E8 -> t_rowbox_solid, which it CALLs or tail-jumps).  thiscall ecx = the list Buffer, (rect*, set*),
  RET 8; ebp = FUN_00405b20's frame (t_rowbox_trim reads the popup at [ebp-4]: ebp is never touched).  Gate
  type1_bar_gate: g > 16, [popup + 0x2350] == 1 (the checkbox kind) and t1c_pn of the CheckList's Dialog data (popup +
  [[popup + 0x21D0] + 8] + 0x21D0, as t1c_ckpos) != 0.  Else push t_rowbox_solid / ret (the deployed path, byte for
  byte: same stack, same registers).  Gate holds: CALL t_rowbox_solid(rect, set) (the deployed draw, unchanged), then
  type1_bar_restripe on the drawn extent = the fn's local rect as t_rowbox_solid leaves it (the band-map rect) + 1 on
  R / B, cut to the Buffer's clip (+0x20, half-open) and to [0, w) x [0, |h|) (+0x80 / +0x84): every pixel of the
  set's pair (E0 / E1 for 0x78D9B0, else EE / AE) -> the opening member on the first T = stripe_rows(g) rows from the
  rect's top (v2, the hover set 0x78D988: from top + K - T, K = stroke_width(g), so its interior opens on a full mate
  stripe flush against the ring; the asm anchors at top + K - 3T, the same phase mod 2T, so y - anchor > 0 and an
  unsigned div serves), the mate on the next T.  No pixels (+0x54 == 0): nothing.  ebx / esi / edi / ebp preserved; eax / ecx /
  edx clobbered (dead: 0x405BFB reloads every one).

Usage: assemble_type1_rowcum.py   -> prints the symbol lines, the content entries and the site bytes
"""
from __future__ import annotations

import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

from scaling_laws import NATIVE_G, STRIPE_2ROW_MIN_G, TYPE1_ROW_GAP_NATIVE, TYPE1_ROW_TOP_NATIVE

PCAVE2 = 0x00A0C000
MENU = 0x00668200                       # menu_strip_thunks (virtual_addr)
G = 0x00668740                          # g_popup_scale_num
BUFFER_TEXT_HEIGHT = 0x005DCA80
THUNK_ROWGAP = MENU + 0xA00
T_CK_LIST = PCAVE2 + 0x33600
IAT_GETPROCADDRESS = 0x00669124
IAT_GETMODULEHANDLEA = 0x00669138
IAT_DELETEDC = 0x0066905C
IAT_SELECTOBJECT = 0x00669060
IAT_CREATECOMPATIBLEDC = 0x00669070

T1C_PN = PCAVE2 + 0x3D6C0
T1C_CALC = PCAVE2 + 0x3D740
T1C_ROWTOP = PCAVE2 + 0x3D7E0
T1C_HIT = PCAVE2 + 0x3D820
T1C_BARH = PCAVE2 + 0x3D860
T1C_LABEL = PCAVE2 + 0x3D920
T1C_PDESC = PCAVE2 + 0x3D980
T1C_CKPOS = PCAVE2 + 0x3DA80
T1C_BAR = PCAVE2 + 0x3DAD0              # W9B (cave_map --at 0x3DAD0: free 0x3DAC7..0x3DF00)
CODE_END = PCAVE2 + 0x3DF00
T_ROWBOX_SOLID = PCAVE2 + 0x3F400       # the deployed bar draw at 0x405BF6 (W7R, assemble_thin_rings.py)
SITE_BAR = 0x00405BF6                   # FUN_00405b20.option_frame: its rel32 t_rowbox_solid -> t1c_bar (W9B)
SITE_BAR_ORIG = "E8 D8 D1 1D 00"        # pristine: call Buffer_box_sprite
CHECKED_SET = 0x78D9B0                  # set 2 (the checked row): pair E0 / E1; sets 0 / 1: EE / AE
HOVER_SET = 0x78D988                    # set 1 (the hover row): phase origin top + K - T (v2; asm: - 3T, same mod 2T)
G_T1C_DATA = PCAVE2 + 0x3DF00           # data: DATA below
REGION_END = PCAVE2 + 0x3E000           # W8T's pcave2 region 0x3D6A0..0x3DFFF

# data (name -> (offset from G_T1C_DATA, initial bytes)): GetGlyphOutlineA (0 unresolved, 1 failed), the per-font
# cache key (HFONT, cell, cap_h) and value, the identity MAT2, the two names for GetModuleHandleA / GetProcAddress
DATA = {
    "g_t1c_ggo": (0x00, bytes(4)),
    "g_t1c_font": (0x04, bytes(4)),
    "g_t1c_hgt": (0x08, bytes(4)),
    "g_t1c_asc": (0x0C, bytes(4)),
    "g_t1c_desc": (0x10, bytes(4)),
    "g_t1c_mat2": (0x20, struct.pack("<hHhHhHhH", 0, 1, 0, 0, 0, 0, 0, 1)),
    "g_t1c_sgdi": (0x40, b"GDI32.dll\0"),
    "g_t1c_sggo": (0x50, b"GetGlyphOutlineA\0"),
}
DV = {n: G_T1C_DATA + o for n, (o, _b) in DATA.items()}

SITE_CALC = 0x0060F018
SITE_ROWTOP = 0x0060F1D3
SITE_ROWTOP_ORIG = "8B 47 68 03 C1 0F AF D8 8B 44 24 10 D1 F9 03 C3 03 C8"
SITE_HIT = 0x0060F735
SITE_HIT_ORIG = "8B 51 68 03 D5 8B EA 8B D8 8B 44 24 18 99 0F AF 59 58 F7 FD"
SITE_LABEL = 0x0060F472
SITE_LABEL_ORIG = "8B 4A 1C 03 F9"
SITE_CK = 0x00405BD4                    # FUN_00405b20.checkbox_scale: its rel32 t_ck_list -> t1c_ckpos

ABS = {G: "{abs32:g_popup_scale_num}", T_CK_LIST: "{abs32:t_ck_list}", T_ROWBOX_SOLID: "{abs32:t_rowbox_solid}"}
ABS.update({va: "{abs32:%s}" % n for n, va in DV.items()})
REL = {BUFFER_TEXT_HEIGHT: "{rel32:Buffer_text_height}", THUNK_ROWGAP: "{rel32:thunk_rowgap}",
       T1C_PN: "{rel32:t1c_pn}", T1C_BARH: "{rel32:t1c_barh}", T1C_PDESC: "{rel32:t1c_pdesc}",
       T_ROWBOX_SOLID: "{rel32:t_rowbox_solid}"}

P3 = TYPE1_ROW_GAP_NATIVE
assert NATIVE_G == 16 and P3 == 3 and TYPE1_ROW_TOP_NATIVE == 1 and STRIPE_2ROW_MIN_G == 22


def asm_barh() -> str:
    # eax = preset in, eax = type1_row_h out; everything else preserved.  esi = preset, edi = g, ebx = T,
    # [esp] = best err (16ths), [esp+4] = best h, ecx = candidate h, edx scratch; P computed into [esp+8].
    return f"""
    push    ebx
    push    ecx
    push    edx
    push    esi
    push    edi
    mov     esi, eax
    mov     edi, dword ptr [{G:#x}]
    mov     ecx, esi
    imul    ecx, edi
    lea     ecx, [ecx*2+0xF]
    sar     ecx, 5
    cmp     edi, {NATIVE_G:#x}
    jle     plain
    mov     ebx, 1
    cmp     edi, {STRIPE_2ROW_MIN_G}
    jl      t_ok
    mov     ebx, edi
    shr     ebx, 4
    cmp     ebx, 2
    jge     t_ok
    mov     ebx, 2
t_ok:
    lea     eax, [esi+{P3}]
    imul    eax, edi
    lea     eax, [eax*2+0xF]
    sar     eax, 5
    push    eax
    push    ecx
    push    0x7FFFFFFF
    dec     ecx
    mov     edx, 3
cand:
    push    edx
    mov     eax, ecx
    shl     eax, 4
    mov     edx, esi
    imul    edx, edi
    sub     eax, edx
    cdq
    xor     eax, edx
    sub     eax, edx
    cmp     eax, 16
    jg      next
    push    eax
    mov     eax, dword ptr [esp+0x10]
    sub     eax, ecx
    shl     eax, 4
    lea     edx, [edi+edi*2]
    sub     eax, edx
    cdq
    xor     eax, edx
    sub     eax, edx
    cmp     eax, 16
    pop     eax
    jg      next
    push    eax
    mov     eax, ecx
    cdq
    idiv    ebx
    pop     eax
    test    edx, edx
    jne     next
    cmp     eax, dword ptr [esp+4]
    jge     next
    mov     dword ptr [esp+4], eax
    mov     dword ptr [esp+8], ecx
next:
    pop     edx
    inc     ecx
    dec     edx
    jne     cand
    pop     eax
    pop     ecx
    add     esp, 4
plain:
    mov     eax, ecx
    pop     edi
    pop     esi
    pop     edx
    pop     ecx
    pop     ebx
    ret
"""


def asm_pn() -> str:
    # P = half_down((preset + 3) g, 16) when the dialog carries the calc's identity, else 0
    return f"""
    push    ecx
    push    edx
    mov     ecx, eax
    mov     edx, dword ptr [{G:#x}]
    cmp     edx, {NATIVE_G:#x}
    jle     zero
    cmp     dword ptr [ecx+0x58], 1
    jle     zero
    mov     eax, dword ptr [ecx+0x48]
    test    eax, eax
    jle     zero
    cmp     eax, 0x100
    jge     zero
    lea     edx, [edx+edx*2]
    sar     edx, 4
    cmp     dword ptr [ecx+0x44], edx
    jne     zero
    push    eax
    call    {T1C_BARH:#x}
    cmp     dword ptr [ecx+0x68], eax
    pop     eax
    jne     zero
    add     eax, {P3}
    imul    eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+0xF]
    sar     eax, 5
    mov     edx, eax
    imul    edx, dword ptr [ecx+0x58]
    cmp     dword ptr [ecx+0x60], edx
    je      done
zero:
    xor     eax, eax
done:
    pop     edx
    pop     ecx
    ret
"""


def asm_calc() -> str:
    return f"""
    call    {THUNK_ROWGAP:#x}
    cmp     dword ptr [{G:#x}], {NATIVE_G:#x}
    jle     out
    cmp     dword ptr [eax+0x58], 1
    jle     out
    mov     edx, dword ptr [eax+0x48]
    test    edx, edx
    jle     out
    cmp     edx, 0x100
    jge     out
    mov     edx, dword ptr [{G:#x}]
    lea     edx, [edx+edx*2]
    sar     edx, 4
    cmp     dword ptr [eax+0x44], edx
    jne     out
    push    eax
    mov     ecx, dword ptr [esi]
    mov     ecx, dword ptr [ecx+4]
    lea     ecx, [ecx+esi+0x444]
    call    {BUFFER_TEXT_HEIGHT:#x}
    mov     ecx, eax
    mov     eax, dword ptr [esp]
    mov     eax, dword ptr [eax+0x48]
    call    {T1C_BARH:#x}
    mov     edx, eax
    pop     eax
    cmp     ecx, edx
    jg      engine
    mov     dword ptr [eax+0x68], edx
    mov     ecx, dword ptr [eax+0x48]
    add     ecx, {P3}
    imul    ecx, dword ptr [{G:#x}]
    lea     ecx, [ecx*2+0xF]
    sar     ecx, 5
    ret
engine:
    mov     ecx, dword ptr [eax+0x68]
    add     ecx, dword ptr [eax+0x44]
out:
    ret
"""


def asm_rowtop() -> str:
    return f"""
    mov     eax, edi
    call    {T1C_PN:#x}
    test    eax, eax
    je      native
    imul    eax, ebx
    mov     ecx, dword ptr [{G:#x}]
    lea     ecx, [ecx*2+0xF]
    sar     ecx, 5
    add     ecx, eax
    add     ecx, dword ptr [esp+0x14]
    ret
native:
    mov     eax, dword ptr [edi+0x68]
    add     eax, ecx
    imul    ebx, eax
    mov     eax, dword ptr [esp+0x14]
    sar     ecx, 1
    add     eax, ebx
    add     ecx, eax
    ret
"""


def asm_hit() -> str:
    return f"""
    mov     edx, dword ptr [ecx+0x68]
    add     edx, ebp
    mov     ebp, edx
    mov     ebx, eax
    imul    ebx, dword ptr [ecx+0x58]
    mov     eax, ecx
    call    {T1C_PN:#x}
    test    eax, eax
    je      native
    push    eax
    mov     eax, dword ptr [esp+0x20]
    cdq
    idiv    dword ptr [esp]
    add     esp, 4
    ret
native:
    mov     eax, dword ptr [esp+0x1C]
    cdq
    idiv    ebp
    ret
"""


def asm_label() -> str:
    return f"""
    mov     ecx, dword ptr [edx+0x1c]
    add     edi, ecx
    push    eax
    push    ebx
    mov     ebx, dword ptr [esi]
    mov     ebx, dword ptr [ebx+8]
    add     ebx, esi
    mov     eax, ebx
    call    {T1C_PN:#x}
    test    eax, eax
    je      out
    mov     eax, dword ptr [esp+0x20]
    cmp     eax, dword ptr [ebx+0x68]
    jne     out
    call    {T1C_PDESC:#x}
    add     eax, dword ptr [edx+0x1c]
    add     eax, dword ptr [edx+0x10]
    sub     eax, dword ptr [esp+0x20]
    jle     out
    sub     edi, eax
out:
    pop     ebx
    pop     eax
    mov     ecx, dword ptr [edx+0x1c]
    ret
"""


def asm_pdesc() -> str:
    return f"""
    push    ebx
    push    ecx
    push    edx
    push    esi
    push    edi
    mov     esi, edx
    mov     eax, dword ptr [esi+8]
    cmp     eax, dword ptr [{DV['g_t1c_font']:#x}]
    jne     miss
    mov     eax, dword ptr [esi+0xC]
    cmp     eax, dword ptr [{DV['g_t1c_hgt']:#x}]
    jne     miss
    mov     eax, dword ptr [esi+0x10]
    cmp     eax, dword ptr [{DV['g_t1c_asc']:#x}]
    jne     miss
    mov     eax, dword ptr [{DV['g_t1c_desc']:#x}]
    jmp     done
miss:
    mov     eax, dword ptr [{DV['g_t1c_ggo']:#x}]
    test    eax, eax
    jne     have
    push    {DV['g_t1c_sgdi']:#x}
    call    dword ptr [{IAT_GETMODULEHANDLEA:#x}]
    test    eax, eax
    je      unres
    push    {DV['g_t1c_sggo']:#x}
    push    eax
    call    dword ptr [{IAT_GETPROCADDRESS:#x}]
    test    eax, eax
    jne     store
unres:
    mov     eax, 1
store:
    mov     dword ptr [{DV['g_t1c_ggo']:#x}], eax
have:
    cmp     eax, 1
    je      fallback
    mov     edi, eax
    push    0
    call    dword ptr [{IAT_CREATECOMPATIBLEDC:#x}]
    test    eax, eax
    je      fallback
    mov     ebx, eax
    push    dword ptr [esi+8]
    push    ebx
    call    dword ptr [{IAT_SELECTOBJECT:#x}]
    push    eax
    sub     esp, 0x14
    mov     ecx, esp
    push    {DV['g_t1c_mat2']:#x}
    push    0
    push    0
    push    ecx
    push    0
    push    0x70
    push    ebx
    call    edi
    mov     ecx, dword ptr [esp+4]
    sub     ecx, dword ptr [esp+0xC]
    add     esp, 0x14
    cmp     eax, -1
    je      gfail
    mov     edi, ecx
    jmp     unsel
gfail:
    mov     edi, dword ptr [esi+0x1C]
unsel:
    pop     eax
    push    eax
    push    ebx
    call    dword ptr [{IAT_SELECTOBJECT:#x}]
    push    ebx
    call    dword ptr [{IAT_DELETEDC:#x}]
    mov     eax, edi
    jmp     cache
fallback:
    mov     eax, dword ptr [esi+0x1C]
cache:
    mov     ecx, dword ptr [esi+8]
    mov     dword ptr [{DV['g_t1c_font']:#x}], ecx
    mov     ecx, dword ptr [esi+0xC]
    mov     dword ptr [{DV['g_t1c_hgt']:#x}], ecx
    mov     ecx, dword ptr [esi+0x10]
    mov     dword ptr [{DV['g_t1c_asc']:#x}], ecx
    mov     dword ptr [{DV['g_t1c_desc']:#x}], eax
done:
    pop     edi
    pop     esi
    pop     edx
    pop     ecx
    pop     ebx
    ret
"""


def asm_ckpos() -> str:
    return f"""
    push    ebx
    mov     eax, dword ptr [ebp-4]
    mov     edx, dword ptr [eax+0x21D0]
    mov     edx, dword ptr [edx+8]
    lea     ebx, [eax+edx+0x21D0]
    mov     eax, ebx
    call    {T1C_PN:#x}
    test    eax, eax
    je      go
    mov     eax, dword ptr [ebp-8]
    sub     eax, dword ptr [ebp-0x10]
    cmp     eax, dword ptr [ebx+0x68]
    jne     go
    mov     edx, {NATIVE_G:#x}
    sub     edx, dword ptr [{G:#x}]
    sar     edx, 1
    mov     eax, dword ptr [ebp-0x10]
    sub     eax, edx
    mov     dword ptr [esp+0x14], eax
go:
    pop     ebx
    push    {T_CK_LIST:#x}
    ret
"""


def asm_bar() -> str:
    # locals (after the three saves and sub 0x14): [esp] y1, [esp+4] x0, [esp+8] x1, [esp+0xC] T, [esp+0x10] the top;
    # dl = the opening member, dh = the mate, cl = this row's colour, ch = the pixel, eax = x, ebx = y, edi = the row
    return f"""
    cmp     dword ptr [{G:#x}], {NATIVE_G:#x}
    jle     tail
    mov     eax, dword ptr [ebp-4]
    cmp     dword ptr [eax+0x2350], 1
    jne     tail
    mov     edx, dword ptr [eax+0x21D0]
    mov     edx, dword ptr [edx+8]
    lea     eax, [eax+edx+0x21D0]
    call    {T1C_PN:#x}
    test    eax, eax
    jne     marked
tail:
    push    {T_ROWBOX_SOLID:#x}
    ret
marked:
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
    mov     ebx, dword ptr [esp+0x10]
    mov     edi, dword ptr [esp+0x14]
    push    edi
    push    ebx
    call    {T_ROWBOX_SOLID:#x}
    cmp     dword ptr [esi+0x54], 0
    je      out
    mov     edx, 0xAEEE
    cmp     edi, {CHECKED_SET:#x}
    jne     pair_ok
    mov     edx, 0xE1E0
pair_ok:
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, {STRIPE_2ROW_MIN_G}
    jl      t_one
    shr     eax, 4
    cmp     eax, 2
    jge     t_ok
    mov     eax, 2
    jmp     t_ok
t_one:
    mov     eax, 1
t_ok:
    sub     esp, 0x14
    mov     dword ptr [esp+0xC], eax
    mov     eax, dword ptr [ebx+4]
    cmp     edi, {HOVER_SET:#x}
    jne     anchor_ok
    mov     ecx, dword ptr [{G:#x}]
    lea     ecx, [ecx*2+0xF]
    sar     ecx, 5
    add     eax, ecx
    mov     ecx, dword ptr [esp+0xC]
    lea     ecx, [ecx+ecx*2]
    sub     eax, ecx
anchor_ok:
    mov     dword ptr [esp+0x10], eax
    mov     eax, dword ptr [ebx+0xC]
    inc     eax
    cmp     eax, dword ptr [esi+0x2C]
    jle     yb_clip
    mov     eax, dword ptr [esi+0x2C]
yb_clip:
    mov     ecx, dword ptr [esi+0x84]
    test    ecx, ecx
    jge     yb_abs
    neg     ecx
yb_abs:
    cmp     eax, ecx
    jle     yb_ok
    mov     eax, ecx
yb_ok:
    mov     dword ptr [esp], eax
    mov     eax, dword ptr [ebx]
    cmp     eax, dword ptr [esi+0x20]
    jge     xl_clip
    mov     eax, dword ptr [esi+0x20]
xl_clip:
    test    eax, eax
    jge     xl_ok
    xor     eax, eax
xl_ok:
    mov     dword ptr [esp+4], eax
    mov     eax, dword ptr [ebx+8]
    inc     eax
    cmp     eax, dword ptr [esi+0x28]
    jle     xr_clip
    mov     eax, dword ptr [esi+0x28]
xr_clip:
    cmp     eax, dword ptr [esi+0x80]
    jle     xr_ok
    mov     eax, dword ptr [esi+0x80]
xr_ok:
    mov     dword ptr [esp+8], eax
    mov     ebx, dword ptr [ebx+4]
    cmp     ebx, dword ptr [esi+0x24]
    jge     yt_clip
    mov     ebx, dword ptr [esi+0x24]
yt_clip:
    test    ebx, ebx
    jge     yloop
    xor     ebx, ebx
yloop:
    cmp     ebx, dword ptr [esp]
    jge     done
    push    edx
    mov     eax, ebx
    sub     eax, dword ptr [esp+0x14]
    xor     edx, edx
    div     dword ptr [esp+0x10]
    pop     edx
    mov     cl, dl
    test    al, 1
    je      c_ok
    mov     cl, dh
c_ok:
    mov     edi, ebx
    imul    edi, dword ptr [esi+0x4A8]
    add     edi, dword ptr [esi+0x54]
    mov     eax, dword ptr [esp+4]
xloop:
    cmp     eax, dword ptr [esp+8]
    jge     xdone
    mov     ch, byte ptr [edi+eax]
    cmp     ch, dl
    je      wr
    cmp     ch, dh
    jne     nx
wr:
    mov     byte ptr [edi+eax], cl
nx:
    inc     eax
    jmp     xloop
xdone:
    inc     ebx
    jmp     yloop
done:
    add     esp, 0x14
out:
    pop     edi
    pop     esi
    pop     ebx
    ret     8
"""


THUNKS = (  # (name, asm builder, va, slot end)
    ("t1c_pn", asm_pn, T1C_PN, T1C_CALC),
    ("t1c_calc", asm_calc, T1C_CALC, T1C_ROWTOP),
    ("t1c_rowtop", asm_rowtop, T1C_ROWTOP, T1C_HIT),
    ("t1c_hit", asm_hit, T1C_HIT, T1C_BARH),
    ("t1c_barh", asm_barh, T1C_BARH, T1C_LABEL),
    ("t1c_label", asm_label, T1C_LABEL, T1C_PDESC),
    ("t1c_pdesc", asm_pdesc, T1C_PDESC, T1C_CKPOS),
    ("t1c_ckpos", asm_ckpos, T1C_CKPOS, T1C_BAR),
    ("t1c_bar", asm_bar, T1C_BAR, CODE_END),
)


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def to_template(b: bytes, va: int) -> str:
    """Bytes -> the yaml template: E8 rel32 to a named target, abs32 of g / t_ck_list / each g_t1c_* data cell."""
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):   # the patcher takes {rel32:} after E8 only
            tgt = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in REL:
                out += ["E8", REL[tgt]]
                i += 5
                continue
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in ABS:
            out.append(ABS[int.from_bytes(b[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def site_bytes() -> dict:
    """site id -> (va, original_bytes, new_bytes) for the yaml (new W8T sites + the two retargeted ones)."""
    return {
        "FUN_0060ed10.rowgap_scale": (SITE_CALC, "8B 48 68 8B 50 44 03 CA", "E8 {rel32:t1c_calc} 90 90 90"),
        "CheckList_draw_item.row_top": (SITE_ROWTOP, SITE_ROWTOP_ORIG, "E8 {rel32:t1c_rowtop}" + " 90" * 13),
        "CheckList_on_click.row_at": (SITE_HIT, SITE_HIT_ORIG, "E8 {rel32:t1c_hit}" + " 90" * 15),
        "CheckList_draw_item.label_top": (SITE_LABEL, SITE_LABEL_ORIG, "E8 {rel32:t1c_label}"),
        "FUN_00405b20.checkbox_scale": (SITE_CK, "E8 71 EF 1D 00", "E8 {rel32:t1c_ckpos}"),
    }


def disarm_edits(rd, st: dict) -> list:
    """[(va, bytes)] that turn W8T off in a baked image (= the 1bfd909 geometry), for the tests' mutants: 0x60F018 and
    0x405BD4 back to thunk_rowgap / t_ck_list, the three CheckList sites back to their original bytes."""
    assert rd(SITE_CALC, 1) == b"\xE8" and rd(SITE_CK, 1) == b"\xE8"
    return [(SITE_CALC + 1, struct.pack("<i", st["thunk_rowgap"] - (SITE_CALC + 5))),
            (SITE_CK + 1, struct.pack("<i", st["t_ck_list"] - (SITE_CK + 5))),
            (SITE_ROWTOP, bytes.fromhex(SITE_ROWTOP_ORIG.replace(" ", ""))),
            (SITE_HIT, bytes.fromhex(SITE_HIT_ORIG.replace(" ", ""))),
            (SITE_LABEL, bytes.fromhex(SITE_LABEL_ORIG.replace(" ", "")))]


def bar_site_bytes() -> dict:
    """W9B's one site (group popup_list_option_frame, W7R's retarget chain): site id -> (va, original, new)."""
    return {"FUN_00405b20.option_frame": (SITE_BAR, SITE_BAR_ORIG, "E8 {rel32:t1c_bar}")}


def disarm_bar_edits(rd, st: dict) -> list:
    """[(va, bytes)] that turn W9B's bar restripe off in a baked image (= 2087b42, W8T v3): 0x405BF6 back to
    t_rowbox_solid."""
    assert rd(SITE_BAR, 1) == b"\xE8"
    return [(SITE_BAR + 1, struct.pack("<i", st["t_rowbox_solid"] - (SITE_BAR + 5)))]


def build() -> dict:
    """name -> (va, bytes, yaml template)."""
    out = {}
    for name, fn, va, end in THUNKS:
        b = assemble(fn(), va)
        assert va + len(b) <= end, f"{name} {len(b)} B overflows its slot ({end - va} B)"
        out[name] = (va, b, to_template(b, va))
    for n, (o, data) in DATA.items():
        out[n] = (G_T1C_DATA + o, data, " ".join(f"{x:02X}" for x in data))
    return out


def main() -> int:
    for name, (va, b, tmpl) in build().items():
        print(f"# {name}: pcave2 {va - PCAVE2:#x}, {len(b)} B")
        print(f'        bytes: "{tmpl}"')
    for sid, (va, orig, new) in {**site_bytes(), **bar_site_bytes()}.items():
        print(f'site {sid} {va:#x}: original_bytes "{orig}" -> new_bytes "{new}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
