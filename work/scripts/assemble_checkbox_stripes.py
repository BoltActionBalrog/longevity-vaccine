"""Assembler for the checkbox scanline law (group checkbox_stripes, fix 28, 2026-10-24).

The three 18x18 checkbox X sprites (0x7794D8 / 0x779504 / 0x779530; interface.pcx (227,1) / (227,20) / (227,39);
a 1-row scanline dither over every art class) were enlarged by the engine's plain NN: the type-1 popup lists
(0x405BD4) and the CheckList rows (0x60F41C / 0x60F457) through thunk_checkbox_scale -> Sprite_draw_2 at g/16, the
lobby's CUSTOM GAME OPTIONS (0x47FAD4 / 0x47FD2B) through thunk_nw_blit_left -> Sprite_blit_scaled_core under the
scale globals.  NN keeps the 1-px source period, so the dither banded (1,2,1,1,2 at g = 22 / 25, 2,3 at 40).

Law: scaling_laws.scanicon_pair_lut / scanicon_top_parity / scanicon_pixels / scanicon_draw (SHAPE = centre-aligned
edge-clamped NN on both axes; SHADE = the dest row's stripe member through the art's own (index, parity) pair LUT;
TOP parity = the brighter member of the dominant pair), phase = checkbox_list_phase for the lists, 0 for the lobby.

Thunks (pcave2 0x33000.., this fix's own region):
  t_ck_draw   Sprite_draw_2 drop-in: thiscall ecx = Sprite*; dest, key, x, y, num, den; RET 0x18.  Refuses (pushes
              Sprite_draw_2 and returns into it, stack and ecx untouched) when num <= den, g <= 16, no pixel plane,
              blit w <= 0 / h < 2 / w*h > 0x400 texels, no dest pixel plane / stride, den <= 0 or the period cell < 2.
              Builds the LUT in its frame (N: texels per key, R: plurality | flags, CNT: one key's votes; 0xA80 B
              below ebp, under a page: no stack probe), then draws every dest pixel of the clipped rect.  The phase
              is read from g_ck_ph (0 at rest).  Leaf: saves ebx/esi/edi/ebp; clobbers eax/ecx/edx.
  t_ck_list   the list sites' call-target (replaces {rel32:thunk_checkbox_scale} at 0x405BD4 / 0x60F41C / 0x60F457;
              thunk_checkbox_scale itself stays as it is for the jackal file icons and t_fdicon_checker):
              g <= 16 -> push Sprite_draw_2 / ret with the vanilla args (1, 1) untouched;
              else thunk_checkbox_scale's own arg rewrite (y += (16 - g) >> 1, num = g, den = 16), g_ck_ph =
              ([dest-0x304] + [dest-0x2F4]) floor-mod P (Win +0x140 + +0x150, Win = dest - 0x444), CALL t_ck_draw
              with the six args, clear g_ck_ph, RET 0x18.
  t_ck_core   the lobby core sites' call-target (replaces {rel32:thunk_nw_blit_left} at 0x47FAD4 / 0x47FD2B):
              thiscall ecx = Sprite*; dest, key, x, y; RET 0x10.  g <= 16 -> push Sprite_blit_scaled_core / ret
              (the vanilla call); else CALL t_ck_draw(dest, key, x, y, g, 16) (phase 0: the NetWin canvas), RET 0x10.
  g_ck_ph     dword, 0 at rest.

Parity: tests/test_checkbox_stripes_asm_parity.py (Unicorn, the yaml bytes vs the law).  End to end on the real
image: tests/test_scaling_checkbox_stripes.py.

Usage: assemble_checkbox_stripes.py   -> prints the yaml symbol + content lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: F401,E402  (master 4aac25b: every keystone import is guarded)

PCAVE2 = 0x00A0C000
REGION = (0x33000, 0x34000)       # fix 28's own pcave2 region (wave-1 allocation)
SLOTS = {                          # name: pcave2 offset
    "t_ck_draw": 0x33000,
    "t_ck_list": 0x33600,
    "t_ck_core": 0x336A0,
    "t_nw_box": 0x33700,
    "g_ck_ph": 0x33FF0,
}
G = 0x00668740                     # g_popup_scale_num
G_STRIPE_PERIOD = 0x0066879C       # g_stripe_period (P = 2T, written with g by thunk_ensure_scale)
SPRITE_DRAW_2 = 0x005E4B4A
SPRITE_BLIT_SCALED_CORE = 0x005E4B9A
BUFFER_BOX_SPRITE = 0x005E2DD3     # thiscall(ecx = dest Buffer; RECT* half-open, BoxSpriteParams*) RET 8
G_CK_PH = PCAVE2 + SLOTS["g_ck_ph"]
T_CK_DRAW = PCAVE2 + SLOTS["t_ck_draw"]
MAX_TEXELS = 0x400
MAX_RATIO = 14                     # num <= 14 den: dw, dh = 18 num/den <= 252 fit the byte axis maps
MIN_MEMBER = 4                     # scaling_laws.SCANICON_MIN_MEMBER
SPRITES = (0x007794D8, 0x00779504, 0x00779530)   # scaling_laws.CHECKBOX_SPRITES: every other sprite -> native
FRAME = 0xC80
N_TAB, R_TAB, CNT_TAB = -0x480, -0x880, -0xA80     # ebp-relative: 512 words, 512 words, 256 words (locals above -0x80)
XMAP, YMAP = -0xB80, -0xC80                         # 256-byte axis maps (scaling_laws.scanicon_axis_map)
SITES_LIST = (0x00405BD4, 0x0060F41C, 0x0060F457)
SITES_CORE = (0x0047FAD4, 0x0047FD2B)

ABS = {G: "{abs32:g_popup_scale_num}", G_STRIPE_PERIOD: "{abs32:g_stripe_period}", G_CK_PH: "{abs32:g_ck_ph}",
       SPRITE_DRAW_2: "{abs32:Sprite_draw_2}", SPRITE_BLIT_SCALED_CORE: "{abs32:Sprite_blit_scaled_core}"}
REL = {T_CK_DRAW: "{rel32:t_ck_draw}", BUFFER_BOX_SPRITE: "{rel32:Buffer_box_sprite}"}
ABS[BUFFER_BOX_SPRITE] = "{abs32:Buffer_box_sprite}"

# ebp-relative locals of t_ck_draw
L_SDATA, L_SPITCH, L_SW, L_SH = -0x04, -0x08, -0x0C, -0x10
L_DDATA, L_DSTRIDE = -0x14, -0x18
L_CL, L_CT, L_CR, L_CB = -0x1C, -0x20, -0x24, -0x28
L_PX, L_PY, L_DW, L_DH = -0x2C, -0x30, -0x34, -0x38
L_QT, L_T, L_PH = -0x40, -0x44, -0x48
L_K, L_R, L_J, L_I = -0x4C, -0x50, -0x54, -0x58
L_SROW, L_DROW, L_SPAR, L_SWAP = -0x5C, -0x60, -0x64, -0x68
L_BESTW, L_BESTK = -0x6C, -0x70
L_KO, L_B = -0x74, -0x78


def _e(off: int) -> str:
    return f"ebp-{-off:#x}" if off < 0 else f"ebp+{off:#x}"


def asm_ck_draw() -> str:
    a = f"""
    cmp     ecx, {SPRITES[0]:#x}
    je      spr_ok
    cmp     ecx, {SPRITES[1]:#x}
    je      spr_ok
    cmp     ecx, {SPRITES[2]:#x}
    jne     native
spr_ok:
    mov     eax, dword ptr [esp+0x14]
    cmp     eax, dword ptr [esp+0x18]
    jle     native
    cmp     dword ptr [esp+0x18], 0
    jle     native
    mov     edx, dword ptr [esp+0x18]
    imul    edx, edx, {MAX_RATIO}
    cmp     eax, edx
    jg      native
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    cmp     dword ptr [{G_STRIPE_PERIOD:#x}], 2
    jl      native
    cmp     dword ptr [ecx+4], 0
    je      native
    mov     eax, dword ptr [ecx+0x10]
    test    eax, eax
    jle     native
    mov     edx, dword ptr [ecx+0x14]
    cmp     edx, 2
    jl      native
    cmp     eax, {MAX_TEXELS:#x}
    jg      native
    imul    eax, edx
    cmp     eax, {MAX_TEXELS:#x}
    jg      native
    mov     eax, dword ptr [esp+4]
    test    eax, eax
    je      native
    cmp     dword ptr [eax+0x54], 0
    je      native
    cmp     dword ptr [eax+0x4a8], 0
    jg      body
native:
    push    {SPRITE_DRAW_2:#x}
    ret
body:
    push    ebp
    mov     ebp, esp
    sub     esp, {FRAME:#x}
    push    ebx
    push    esi
    push    edi
    cld
    mov     eax, dword ptr [ecx+4]
    mov     dword ptr [{_e(L_SDATA)}], eax
    mov     eax, dword ptr [ecx+0xc]
    test    eax, eax
    jg      pitch_ok
    mov     eax, dword ptr [ecx+0x10]
pitch_ok:
    mov     dword ptr [{_e(L_SPITCH)}], eax
    mov     eax, dword ptr [ecx+0x10]
    mov     dword ptr [{_e(L_SW)}], eax
    mov     eax, dword ptr [ecx+0x14]
    mov     dword ptr [{_e(L_SH)}], eax
    mov     eax, dword ptr [ecx+0x20]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1c]
    add     eax, dword ptr [ebp+0x10]
    mov     dword ptr [{_e(L_PX)}], eax
    mov     eax, dword ptr [ecx+0x24]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1c]
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [{_e(L_PY)}], eax
    mov     eax, dword ptr [{_e(L_SW)}]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1c]
    mov     dword ptr [{_e(L_DW)}], eax
    mov     eax, dword ptr [{_e(L_SH)}]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1c]
    mov     dword ptr [{_e(L_DH)}], eax
    mov     esi, dword ptr [ebp+8]
    mov     eax, dword ptr [esi+0x54]
    mov     dword ptr [{_e(L_DDATA)}], eax
    mov     eax, dword ptr [esi+0x4a8]
    mov     dword ptr [{_e(L_DSTRIDE)}], eax
    mov     eax, dword ptr [esi+0x20]
    test    eax, eax
    jns     cl_ok
    xor     eax, eax
cl_ok:
    mov     dword ptr [{_e(L_CL)}], eax
    mov     eax, dword ptr [esi+0x24]
    test    eax, eax
    jns     ct_ok
    xor     eax, eax
ct_ok:
    mov     dword ptr [{_e(L_CT)}], eax
    mov     eax, dword ptr [esi+0x28]
    mov     edx, dword ptr [esi+0x80]
    cmp     eax, edx
    jle     cr_ok
    mov     eax, edx
cr_ok:
    mov     dword ptr [{_e(L_CR)}], eax
    mov     eax, dword ptr [esi+0x2c]
    mov     edx, dword ptr [esi+0x84]
    test    edx, edx
    jns     hb_pos
    neg     edx
hb_pos:
    cmp     eax, edx
    jle     cb_ok
    mov     eax, edx
cb_ok:
    mov     dword ptr [{_e(L_CB)}], eax
    mov     eax, dword ptr [{G_STRIPE_PERIOD:#x}]
    shr     eax, 1
    mov     dword ptr [{_e(L_T)}], eax
    mov     eax, dword ptr [{G_CK_PH:#x}]
    mov     dword ptr [{_e(L_PH)}], eax
    lea     edi, [{_e(N_TAB)}]
    mov     ecx, 0x100
    xor     eax, eax
    rep stosd
    lea     edi, [{_e(R_TAB)}]
    mov     ecx, 0x100
    mov     eax, 0x80008000
    rep stosd
    xor     ebx, ebx
a_row:
    cmp     ebx, dword ptr [{_e(L_SH)}]
    jge     a_done
    mov     esi, ebx
    imul    esi, dword ptr [{_e(L_SPITCH)}]
    add     esi, dword ptr [{_e(L_SDATA)}]
    xor     ecx, ecx
a_col:
    cmp     ecx, dword ptr [{_e(L_SW)}]
    jge     a_next
    movzx   eax, byte ptr [esi+ecx]
    cmp     al, byte ptr [ebp+0xc]
    je      a_skip
    mov     edx, ebx
    and     edx, 1
    lea     eax, [edx+eax*2]
    inc     word ptr [ebp+eax*2{N_TAB:+#x}]
a_skip:
    inc     ecx
    jmp     a_col
a_next:
    inc     ebx
    jmp     a_row
a_done:
    xor     ebx, ebx
b_key:
    cmp     ebx, 0x200
    jge     b_done
    cmp     word ptr [ebp+ebx*2{N_TAB:+#x}], 0
    je      b_nextkey
    lea     edi, [{_e(CNT_TAB)}]
    mov     ecx, 0x80
    xor     eax, eax
    rep stosd
    mov     eax, ebx
    and     eax, 1
    mov     dword ptr [{_e(L_R)}], eax
b_row:
    mov     eax, dword ptr [{_e(L_R)}]
    cmp     eax, dword ptr [{_e(L_SH)}]
    jge     b_argmax
    mov     esi, eax
    imul    esi, dword ptr [{_e(L_SPITCH)}]
    add     esi, dword ptr [{_e(L_SDATA)}]
    xor     ecx, ecx
b_col:
    cmp     ecx, dword ptr [{_e(L_SW)}]
    jge     b_rownext
    movzx   eax, byte ptr [esi+ecx]
    mov     edx, ebx
    shr     edx, 1
    cmp     eax, edx
    jne     b_colnext
    cmp     dword ptr [{_e(L_R)}], 0
    je      b_down
    mov     edi, esi
    sub     edi, dword ptr [{_e(L_SPITCH)}]
    movzx   eax, byte ptr [edi+ecx]
    cmp     al, byte ptr [ebp+0xc]
    je      b_down
    inc     word ptr [ebp+eax*2{CNT_TAB:+#x}]
b_down:
    mov     eax, dword ptr [{_e(L_R)}]
    inc     eax
    cmp     eax, dword ptr [{_e(L_SH)}]
    jge     b_colnext
    mov     edi, esi
    add     edi, dword ptr [{_e(L_SPITCH)}]
    movzx   eax, byte ptr [edi+ecx]
    cmp     al, byte ptr [ebp+0xc]
    je      b_colnext
    inc     word ptr [ebp+eax*2{CNT_TAB:+#x}]
b_colnext:
    inc     ecx
    jmp     b_col
b_rownext:
    add     dword ptr [{_e(L_R)}], 2
    jmp     b_row
b_argmax:
    xor     edx, edx
    xor     edi, edi
    mov     ecx, 1
m_loop:
    cmp     ecx, 0x100
    jge     m_done
    movzx   eax, word ptr [ebp+ecx*2{CNT_TAB:+#x}]
    movzx   esi, word ptr [ebp+edx*2{CNT_TAB:+#x}]
    cmp     eax, esi
    jb      m_next
    ja      m_new
    mov     edi, 1
    jmp     m_next
m_new:
    mov     edx, ecx
    xor     edi, edi
m_next:
    inc     ecx
    jmp     m_loop
m_done:
    test    edi, edi
    jne     b_nextkey
    movzx   eax, word ptr [ebp+edx*2{CNT_TAB:+#x}]
    cmp     eax, 2
    jl      m_store
    or      edx, 0x100
m_store:
    mov     word ptr [ebp+ebx*2{R_TAB:+#x}], dx
b_nextkey:
    inc     ebx
    jmp     b_key
b_done:
    xor     ebx, ebx
c_key:
    cmp     ebx, 0x200
    jge     c_done
    movzx   eax, word ptr [ebp+ebx*2{R_TAB:+#x}]
    test    eax, 0x8000
    jne     c_next
    test    eax, 0x100
    je      c_next
    and     eax, 0xff
    mov     edx, ebx
    shr     edx, 1
    cmp     eax, edx
    je      c_next
    mov     ecx, ebx
    and     ecx, 1
    xor     ecx, 1
    lea     ecx, [ecx+eax*2]
    movzx   ecx, word ptr [ebp+ecx*2{R_TAB:+#x}]
    test    ecx, 0x8000
    jne     c_next
    and     ecx, 0xff
    cmp     ecx, edx
    jne     c_next
    cmp     word ptr [ebp+ebx*2{N_TAB:+#x}], {MIN_MEMBER}
    jb      c_next
    mov     ecx, ebx
    and     ecx, 1
    xor     ecx, 1
    lea     ecx, [ecx+eax*2]
    cmp     word ptr [ebp+ecx*2{N_TAB:+#x}], {MIN_MEMBER}
    jb      c_next
    or      word ptr [ebp+ebx*2{R_TAB:+#x}], 0x200
c_next:
    inc     ebx
    jmp     c_key
c_done:
    mov     dword ptr [{_e(L_BESTW)}], 0xffffffff
    mov     dword ptr [{_e(L_BESTK)}], 0xffffffff
    xor     ebx, ebx
d_key:
    cmp     ebx, 0x200
    jge     d_done
    movzx   eax, word ptr [ebp+ebx*2{R_TAB:+#x}]
    test    eax, 0x200
    je      d_next
    and     eax, 0xff
    mov     ecx, ebx
    and     ecx, 1
    xor     ecx, 1
    lea     ecx, [ecx+eax*2]
    movzx   eax, word ptr [ebp+ecx*2{N_TAB:+#x}]
    movzx   edx, word ptr [ebp+ebx*2{N_TAB:+#x}]
    add     eax, edx
    cmp     eax, dword ptr [{_e(L_BESTW)}]
    jle     d_next
    mov     dword ptr [{_e(L_BESTW)}], eax
    mov     dword ptr [{_e(L_BESTK)}], ebx
d_next:
    inc     ebx
    jmp     d_key
d_done:
    mov     dword ptr [{_e(L_QT)}], 0
    mov     ebx, dword ptr [{_e(L_BESTK)}]
    test    ebx, ebx
    js      e_draw
    movzx   ecx, word ptr [ebp+ebx*2{R_TAB:+#x}]
    and     ecx, 0xff
    mov     edx, ebx
    shr     edx, 1
    mov     esi, dword ptr [ebp+8]
    movzx   eax, byte ptr [esi+edx*4+0xa4]
    movzx   edi, byte ptr [esi+edx*4+0xa5]
    add     eax, edi
    movzx   edi, byte ptr [esi+edx*4+0xa6]
    add     eax, edi
    movzx   edi, byte ptr [esi+ecx*4+0xa4]
    push    eax
    movzx   eax, byte ptr [esi+ecx*4+0xa5]
    add     edi, eax
    movzx   eax, byte ptr [esi+ecx*4+0xa6]
    add     edi, eax
    pop     eax
    and     ebx, 1
    cmp     eax, edi
    ja      top_v
    jb      top_m
    cmp     edx, ecx
    jb      top_v
top_m:
    xor     ebx, 1
top_v:
    mov     dword ptr [{_e(L_QT)}], ebx
e_draw:
    lea     edi, [{_e(XMAP)}]
    mov     ecx, dword ptr [{_e(L_DW)}]
    mov     ebx, dword ptr [{_e(L_SW)}]
    call    axismap
    lea     edi, [{_e(YMAP)}]
    mov     ecx, dword ptr [{_e(L_DH)}]
    mov     ebx, dword ptr [{_e(L_SH)}]
    call    axismap
    mov     dword ptr [{_e(L_J)}], 0
e_row:
    mov     eax, dword ptr [{_e(L_J)}]
    cmp     eax, dword ptr [{_e(L_DH)}]
    jge     e_done
    mov     ebx, dword ptr [{_e(L_PY)}]
    add     ebx, eax
    cmp     ebx, dword ptr [{_e(L_CT)}]
    jl      e_rownext
    cmp     ebx, dword ptr [{_e(L_CB)}]
    jge     e_rownext
    movzx   eax, byte ptr [ebp+eax{YMAP:+#x}]
    mov     edx, eax
    and     edx, 1
    mov     dword ptr [{_e(L_SPAR)}], edx
    imul    eax, dword ptr [{_e(L_SPITCH)}]
    add     eax, dword ptr [{_e(L_SDATA)}]
    mov     dword ptr [{_e(L_SROW)}], eax
    mov     eax, ebx
    add     eax, dword ptr [{_e(L_PH)}]
    xor     edx, edx
    div     dword ptr [{_e(L_T)}]
    and     eax, 1
    xor     eax, dword ptr [{_e(L_QT)}]
    xor     eax, dword ptr [{_e(L_SPAR)}]
    mov     dword ptr [{_e(L_SWAP)}], eax
    mov     eax, ebx
    imul    eax, dword ptr [{_e(L_DSTRIDE)}]
    add     eax, dword ptr [{_e(L_DDATA)}]
    mov     dword ptr [{_e(L_DROW)}], eax
    mov     dword ptr [{_e(L_I)}], 0
e_col:
    mov     eax, dword ptr [{_e(L_I)}]
    cmp     eax, dword ptr [{_e(L_DW)}]
    jge     e_rownext
    mov     edi, dword ptr [{_e(L_PX)}]
    add     edi, eax
    cmp     edi, dword ptr [{_e(L_CL)}]
    jl      e_colnext
    cmp     edi, dword ptr [{_e(L_CR)}]
    jge     e_colnext
    movzx   eax, byte ptr [ebp+eax{XMAP:+#x}]
    add     eax, dword ptr [{_e(L_SROW)}]
    movzx   eax, byte ptr [eax]
    cmp     al, byte ptr [ebp+0xc]
    je      e_colnext
    cmp     dword ptr [{_e(L_SWAP)}], 0
    je      e_put
    mov     edx, dword ptr [{_e(L_SPAR)}]
    lea     edx, [edx+eax*2]
    movzx   edx, word ptr [ebp+edx*2{R_TAB:+#x}]
    test    edx, 0x200
    je      e_put
    mov     eax, edx
e_put:
    add     edi, dword ptr [{_e(L_DROW)}]
    mov     byte ptr [edi], al
e_colnext:
    inc     dword ptr [{_e(L_I)}]
    jmp     e_col
e_rownext:
    inc     dword ptr [{_e(L_J)}]
    jmp     e_row
e_done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x18
axismap:
    mov     eax, ebx
    shr     eax, 1
    test    bl, 1
    jne     am_k
    dec     eax
am_k:
    mov     dword ptr [{_e(L_KO)}], eax
    xor     esi, esi
am_b:
    cmp     esi, ecx
    jge     am_bdone
    mov     eax, esi
    call    nnc
    cmp     eax, dword ptr [{_e(L_KO)}]
    jge     am_bdone
    inc     esi
    jmp     am_b
am_bdone:
    mov     dword ptr [{_e(L_B)}], esi
    xor     esi, esi
am_d:
    cmp     esi, ecx
    jge     am_done
    cmp     esi, dword ptr [{_e(L_B)}]
    jge     am_right
    mov     eax, esi
    call    nnc
    jmp     am_put
am_right:
    mov     eax, ecx
    sub     eax, dword ptr [{_e(L_B)}]
    cmp     esi, eax
    jl      am_mid
    mov     eax, ecx
    dec     eax
    sub     eax, esi
    call    nnc
    neg     eax
    lea     eax, [eax+ebx-1]
    jmp     am_put
am_mid:
    mov     eax, dword ptr [{_e(L_KO)}]
    test    bl, 1
    jne     am_put
    mov     edx, ecx
    sub     edx, dword ptr [{_e(L_B)}]
    sub     edx, dword ptr [{_e(L_B)}]
    inc     edx
    shr     edx, 1
    add     edx, dword ptr [{_e(L_B)}]
    cmp     esi, edx
    jl      am_put
    inc     eax
am_put:
    mov     byte ptr [edi+esi], al
    inc     esi
    jmp     am_d
am_done:
    ret
nnc:
    add     eax, eax
    inc     eax
    imul    eax, ebx
    xor     edx, edx
    push    ecx
    add     ecx, ecx
    div     ecx
    pop     ecx
    lea     edx, [ebx-1]
    cmp     eax, edx
    jbe     nnc_ok
    mov     eax, edx
nnc_ok:
    ret
"""
    return a


def asm_ck_list() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     vanilla
    mov     eax, 0x10
    sub     eax, dword ptr [{G:#x}]
    sar     eax, 1
    add     dword ptr [esp+0x10], eax
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [esp+0x14], eax
    mov     dword ptr [esp+0x18], 0x10
    xor     eax, eax
    cmp     dword ptr [{G_STRIPE_PERIOD:#x}], 2
    jl      ph_ok
    mov     eax, dword ptr [esp+4]
    mov     edx, dword ptr [eax-0x2f4]
    mov     eax, dword ptr [eax-0x304]
    add     eax, edx
    cdq
    idiv    dword ptr [{G_STRIPE_PERIOD:#x}]
    mov     eax, edx
    test    eax, eax
    jns     ph_ok
    add     eax, dword ptr [{G_STRIPE_PERIOD:#x}]
ph_ok:
    mov     dword ptr [{G_CK_PH:#x}], eax
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    call    {T_CK_DRAW:#x}
    and     dword ptr [{G_CK_PH:#x}], 0
    ret     0x18
vanilla:
    push    {SPRITE_DRAW_2:#x}
    ret
"""


def asm_ck_core() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     vanilla
    push    0x10
    push    dword ptr [{G:#x}]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    call    {T_CK_DRAW:#x}
    ret     0x10
vanilla:
    push    {SPRITE_BLIT_SCALED_CORE:#x}
    ret
"""


def asm_nw_box() -> str:
    """t_nw_box: the NetWin lobby's filled Buffer_box_sprite sites (law scaling_laws.box_fill_rect /
    tile_scan_pair / panel_fill_pixel).  g <= 16 -> push Buffer_box_sprite / ret (the vanilla call).  Else the
    engine box, then -- when params+0x20 holds a fill tile whose first four rows are a 2-member row dither a,b,a,b --
    every fill-rect pixel (the rect the engine tiled, intersected with the clip and the buffer) holding a or b
    becomes the brighter member on stripe_top(dest row) rows, the other member elsewhere (phase 0: the NetWin
    canvas grid, the same as t_ck_core's checkboxes)."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      hi
    push    {BUFFER_BOX_SPRITE:#x}
    ret
hi:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x30
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
    push    dword ptr [ebp+0xc]
    push    dword ptr [ebp+8]
    call    {BUFFER_BOX_SPRITE:#x}
    mov     eax, dword ptr [ebp+0xc]
    test    eax, eax
    je      done
    mov     edi, dword ptr [eax+0x20]
    test    edi, edi
    je      done
    mov     eax, dword ptr [{G_STRIPE_PERIOD:#x}]
    cmp     eax, 2
    jl      done
    shr     eax, 1
    mov     dword ptr [ebp-4], eax
    cmp     dword ptr [esi+0x54], 0
    je      done
    mov     ecx, dword ptr [edi+0x80]
    test    ecx, ecx
    jle     done
    mov     dword ptr [ebp-8], ecx
    mov     edx, dword ptr [edi+0x84]
    test    edx, edx
    jns     th_pos
    neg     edx
th_pos:
    cmp     edx, 4
    jl      done
    mov     ebx, dword ptr [edi+0x54]
    test    ebx, ebx
    je      done
    mov     edx, dword ptr [edi+0x4a8]
    test    edx, edx
    jle     done
    movzx   eax, byte ptr [ebx]
    mov     dword ptr [ebp-0xc], eax
    movzx   eax, byte ptr [ebx+edx]
    mov     dword ptr [ebp-0x10], eax
    cmp     eax, dword ptr [ebp-0xc]
    je      done
    xor     edi, edi
v_row:
    cmp     edi, 4
    jge     v_ok
    mov     eax, dword ptr [ebp-0xc]
    test    edi, 1
    je      v_even
    mov     eax, dword ptr [ebp-0x10]
v_even:
    xor     ecx, ecx
v_col:
    cmp     ecx, dword ptr [ebp-8]
    jge     v_next
    cmp     al, byte ptr [ebx+ecx]
    jne     done
    inc     ecx
    jmp     v_col
v_next:
    add     ebx, edx
    inc     edi
    jmp     v_row
v_ok:
    mov     ecx, dword ptr [ebp-0xc]
    mov     edx, dword ptr [ebp-0x10]
    movzx   eax, byte ptr [esi+ecx*4+0xa4]
    movzx   edi, byte ptr [esi+ecx*4+0xa5]
    add     eax, edi
    movzx   edi, byte ptr [esi+ecx*4+0xa6]
    add     eax, edi
    movzx   ebx, byte ptr [esi+edx*4+0xa4]
    movzx   edi, byte ptr [esi+edx*4+0xa5]
    add     ebx, edi
    movzx   edi, byte ptr [esi+edx*4+0xa6]
    add     ebx, edi
    cmp     eax, ebx
    ja      a_top
    jb      b_top
    cmp     ecx, edx
    jb      a_top
b_top:
    xchg    ecx, edx
a_top:
    mov     dword ptr [ebp-0x14], ecx
    mov     dword ptr [ebp-0x18], edx
    mov     eax, dword ptr [ebp+8]
    mov     ebx, dword ptr [ebp+0xc]
    mov     ecx, dword ptr [eax]
    mov     edx, dword ptr [ebx+0x18]
    test    edx, edx
    je      no_l
    add     ecx, dword ptr [edx+0x18]
no_l:
    mov     dword ptr [ebp-0x1c], ecx
    mov     ecx, dword ptr [eax+4]
    mov     edx, dword ptr [ebx+0x10]
    test    edx, edx
    je      no_t
    add     ecx, dword ptr [edx+0x1c]
no_t:
    mov     dword ptr [ebp-0x20], ecx
    mov     ecx, dword ptr [eax+8]
    mov     edx, dword ptr [ebx+0x1c]
    test    edx, edx
    je      no_r
    sub     ecx, dword ptr [edx+0x18]
no_r:
    mov     dword ptr [ebp-0x24], ecx
    mov     ecx, dword ptr [eax+0xc]
    mov     edx, dword ptr [ebx+0x14]
    test    edx, edx
    je      no_b
    sub     ecx, dword ptr [edx+0x1c]
no_b:
    mov     dword ptr [ebp-0x28], ecx
    mov     eax, dword ptr [esi+0x20]
    test    eax, eax
    jns     c1
    xor     eax, eax
c1:
    cmp     eax, dword ptr [ebp-0x1c]
    jge     c1s
    mov     eax, dword ptr [ebp-0x1c]
c1s:
    mov     dword ptr [ebp-0x1c], eax
    mov     eax, dword ptr [esi+0x24]
    test    eax, eax
    jns     c2
    xor     eax, eax
c2:
    cmp     eax, dword ptr [ebp-0x20]
    jge     c2s
    mov     eax, dword ptr [ebp-0x20]
c2s:
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [esi+0x28]
    cmp     eax, dword ptr [esi+0x80]
    jle     c3
    mov     eax, dword ptr [esi+0x80]
c3:
    cmp     eax, dword ptr [ebp-0x24]
    jle     c3s
    mov     eax, dword ptr [ebp-0x24]
c3s:
    mov     dword ptr [ebp-0x24], eax
    mov     edx, dword ptr [esi+0x84]
    test    edx, edx
    jns     c4h
    neg     edx
c4h:
    mov     eax, dword ptr [esi+0x2c]
    cmp     eax, edx
    jle     c4
    mov     eax, edx
c4:
    cmp     eax, dword ptr [ebp-0x28]
    jle     c4s
    mov     eax, dword ptr [ebp-0x28]
c4s:
    mov     dword ptr [ebp-0x28], eax
    mov     ebx, dword ptr [ebp-0x20]
r_row:
    cmp     ebx, dword ptr [ebp-0x28]
    jge     done
    mov     eax, ebx
    xor     edx, edx
    div     dword ptr [ebp-4]
    mov     edx, dword ptr [ebp-0x14]
    test    al, 1
    je      r_top
    mov     edx, dword ptr [ebp-0x18]
r_top:
    mov     edi, ebx
    imul    edi, dword ptr [esi+0x4a8]
    add     edi, dword ptr [esi+0x54]
    mov     ecx, dword ptr [ebp-0x1c]
r_col:
    cmp     ecx, dword ptr [ebp-0x24]
    jge     r_next
    mov     al, byte ptr [edi+ecx]
    cmp     al, byte ptr [ebp-0xc]
    je      r_put
    cmp     al, byte ptr [ebp-0x10]
    jne     r_skip
r_put:
    mov     byte ptr [edi+ecx], dl
r_skip:
    inc     ecx
    jmp     r_col
r_next:
    inc     ebx
    jmp     r_row
done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     8
"""


SOURCES = {"t_ck_draw": asm_ck_draw, "t_ck_list": asm_ck_list, "t_ck_core": asm_ck_core, "t_nw_box": asm_nw_box}


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b), "disassembly does not cover"
    return b


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):   # the patcher takes {rel32:} after E8 only
            tgt = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in REL:
                out += [f"{b[i]:02X}", REL[tgt]]
                i += 5
                continue
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in ABS:
            out.append(ABS[int.from_bytes(b[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def build() -> dict[str, bytes]:
    out = {}
    order = sorted(SOURCES, key=lambda n: SLOTS[n])
    for k, name in enumerate(order):
        b = assemble(SOURCES[name](), PCAVE2 + SLOTS[name])
        limit = SLOTS[order[k + 1]] if k + 1 < len(order) else SLOTS["g_ck_ph"]
        assert SLOTS[name] + len(b) <= limit, f"{name} {len(b)}B overflows its slot"
        out[name] = b
    assert REGION[0] <= min(SLOTS.values()) and SLOTS["g_ck_ph"] + 4 <= REGION[1]
    return out


def main() -> int:
    for name, b in build().items():
        off = SLOTS[name]
        print(f"  {name}: {{ cave: pcave2, offset: {off:#x} }}   # {len(b)}B")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{to_template(b, PCAVE2 + off)}\"")
    print(f"      - id: g_ck_ph\n        offset: {SLOTS['g_ck_ph']:#x}\n        bytes: \"00 00 00 00\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
