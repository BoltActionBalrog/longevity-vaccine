"""Assemble thunk_btn_ringfix — device-density hover-ring overdraw for 2d-zoomed
box-sprite-faced FlatButtons (the DL BACK/EXIT/category hover ring asymmetry).

Placement: thunk_btn_2dscale's zoomed path calls thunk_btn_stripes via a direct E8
(pcave2+0x4D1, rel32 at +0x4D2). That call is retargeted to this thunk, which first
calls thunk_btn_stripes (the original pass, including the E0/E1 pair remap that
corrupts the ring), then overdraws the ring at device density:

  K = ceil(g/16) = (g+15)>>4                              [g>16 gate]
  state s = content_draw's law (+0xAB8 forced 0..2, else pressed(+0xA9C|+0xA18)=2,
            else hover(+0xA74)=1, else 0)
  skip if stateSprites[s] (+0xAD4) != 0 or boxParams[s] (+0xAC8) == 0
  per-edge stroke colour read from the BoxSpriteParams edge-strip ART
    (top strip +0x10: row0[w/2]; bottom +0x14: row(h-1)[w/2];
     left +0x18: col0[h/2]; right +0x1C: col(w-1)[h/2];
     strip Sprite: data+0x4 pitch+0xC w+0x10 h+0x14)
  colour 7 (pass-through) or 9 (key) => that edge has no stroke, skip it
  draw K-thick strokes full-length on the button canvas (esi+0x444: data+0x54,
  stride+0x4A8, W+0x80, H=-[+0x84]), then punch 4 KxK key-9 corner notches iff the
  TL corner art's (0,0) is keyed (the vanilla chamfer, scaled).

Only the hover set carries a stroke in the DL/toolbar family (idle+pressed strips are
all idx 7), so the art gate self-limits the STROKE overdraw to hovered buttons.
v2 (2026-10-24 wave-1 F33, law scaling_laws.btn_corner_notch): the corner punch no longer
needs a drawn edge -- the idle and pressed / lit faces carry the same 1-px keyed corner art
and kept its NN image (4K 2x2 / 3x2 / 2x3 / 3x3, 1080p 1x1: the lit HUD TOOLBAR); every
state with a keyed TL corner now gets the KxK notch.  The drew-edge flag is still kept
(unread).

Context: called inside thunk_btn_2dscale's pushad frame -> every GP register is
restored by the popad after our return; esi=FlatButton at entry. Flags are dead
(the resume site 0x60836B starts with test eax,eax). Plain near RET.

Sentinels (runtime/bake patching): 0x11111111 = g_popup_scale_num VA,
0x22222222 = thunk_btn_stripes VA.
"""
import sys
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
G_SENT = 0x11111111
STRIPES_SENT = 0x22222222

ASM = r"""
    mov     eax, 0x22222222
    call    eax                       ; thunk_btn_stripes (original pass) first
    mov     eax, dword ptr [0x11111111]
    cmp     eax, 16
    jle     out0
    push    ebp
    mov     ebp, esp
    sub     esp, 0x20
    ; [ebp-4]=K [ebp-8]=data [ebp-0xC]=stride [ebp-0x10]=W [ebp-0x14]=H [ebp-0x18]=params
    add     eax, 15
    sar     eax, 4
    mov     [ebp-4], eax              ; K
    ; ---- state law ----
    mov     eax, [esi+0xAB8]
    cmp     eax, 0
    jl      derive
    cmp     eax, 3
    jl      havestate
derive:
    mov     eax, 2
    cmp     dword ptr [esi+0xA9C], 0
    jne     havestate
    cmp     dword ptr [esi+0xA18], 0
    jne     havestate
    xor     eax, eax
    cmp     dword ptr [esi+0xA74], 0
    je      havestate
    mov     eax, 1
havestate:
    cmp     dword ptr [esi+eax*4+0xAD4], 0
    jne     out1                      ; stateSprite path -> no box face
    mov     ebx, [esi+eax*4+0xAC8]
    test    ebx, ebx
    je      out1
    mov     [ebp-0x18], ebx           ; params
    ; ---- canvas ----
    lea     edx, [esi+0x444]
    mov     eax, [edx+0x54]
    test    eax, eax
    je      out1
    mov     [ebp-8], eax              ; data
    mov     ecx, [edx+0x4A8]
    cmp     ecx, 0
    jle     out1
    mov     [ebp-0xC], ecx            ; stride
    mov     eax, [edx+0x80]
    cmp     eax, 8
    jle     out1
    cmp     eax, 4096
    jge     out1
    cmp     eax, ecx
    jg      out1                      ; W must fit stride
    mov     [ebp-0x10], eax           ; W
    mov     eax, [edx+0x84]
    neg     eax
    cmp     eax, 8
    jle     out1
    cmp     eax, 4096
    jge     out1
    mov     [ebp-0x14], eax           ; H
    mov     dword ptr [ebp-0x1C], 0  ; drew-any-edge flag
    cld
    ; ---- TOP: colour = strip(+0x10) row0[w/2]; fill rows 0..K-1 ----
    mov     ecx, [ebx+0x10]
    call    strip_head
    jc      no_top
    movzx   eax, byte ptr [edx]       ; edx = data + w/2 (strip_head)
    call    edge_live
    jc      no_top
    mov     dword ptr [ebp-0x1C], 1
    mov     edi, [ebp-8]
    xor     ebx, ebx
toploop:
    mov     ecx, [ebp-0x10]
    push    eax
    rep stosb
    pop     eax
    mov     edi, [ebp-8]
    inc     ebx
    mov     edx, ebx
    imul    edx, dword ptr [ebp-0xC]
    add     edi, edx
    cmp     ebx, [ebp-4]
    jl      toploop
no_top:
    ; ---- BOTTOM: strip(+0x14) row(h-1)[w/2]; rows H-K..H-1 ----
    mov     ebx, [ebp-0x18]
    mov     ecx, [ebx+0x14]
    call    strip_head
    jc      no_bottom
    mov     eax, [ecx+0x14]           ; h
    dec     eax
    imul    eax, dword ptr [ecx+0xC]  ; * pitch
    add     edx, eax                  ; data + pitch*(h-1) + w/2
    movzx   eax, byte ptr [edx]
    call    edge_live
    jc      no_bottom
    mov     dword ptr [ebp-0x1C], 1
    mov     ebx, [ebp-0x14]
    sub     ebx, [ebp-4]              ; y = H-K
botloop:
    mov     edi, ebx
    imul    edi, dword ptr [ebp-0xC]
    add     edi, [ebp-8]
    mov     ecx, [ebp-0x10]
    push    eax
    rep stosb
    pop     eax
    inc     ebx
    cmp     ebx, [ebp-0x14]
    jl      botloop
no_bottom:
    ; ---- LEFT: strip(+0x18) col0[h/2]; cols 0..K-1, all rows ----
    mov     ebx, [ebp-0x18]
    mov     ecx, [ebx+0x18]
    call    strip_head
    jc      no_left
    mov     eax, [ecx+0x14]           ; h
    shr     eax, 1
    imul    eax, dword ptr [ecx+0xC]
    mov     edx, [ecx+4]
    add     edx, eax                  ; data + pitch*(h/2) + 0
    movzx   eax, byte ptr [edx]
    call    edge_live
    jc      no_left
    mov     dword ptr [ebp-0x1C], 1
    mov     edi, [ebp-8]
    xor     ebx, ebx
leftloop:
    mov     ecx, [ebp-4]              ; K
    push    eax
    rep stosb
    pop     eax
    inc     ebx
    mov     edi, ebx
    imul    edi, dword ptr [ebp-0xC]
    add     edi, [ebp-8]
    cmp     ebx, [ebp-0x14]
    jl      leftloop
no_left:
    ; ---- RIGHT: strip(+0x1C) col(w-1)[h/2]; cols W-K..W-1 ----
    mov     ebx, [ebp-0x18]
    mov     ecx, [ebx+0x1C]
    call    strip_head
    jc      no_right
    mov     eax, [ecx+0x14]
    shr     eax, 1
    imul    eax, dword ptr [ecx+0xC]
    add     eax, [ecx+0x10]
    dec     eax                       ; + w-1
    mov     edx, [ecx+4]
    add     edx, eax
    movzx   eax, byte ptr [edx]
    call    edge_live
    jc      no_right
    mov     dword ptr [ebp-0x1C], 1
    xor     ebx, ebx
rightloop:
    mov     edi, ebx
    imul    edi, dword ptr [ebp-0xC]
    add     edi, [ebp-8]
    add     edi, [ebp-0x10]
    sub     edi, [ebp-4]              ; + W-K
    mov     ecx, [ebp-4]
    push    eax
    rep stosb
    pop     eax
    inc     ebx
    cmp     ebx, [ebp-0x14]
    jl      rightloop
no_right:
    ; ---- corner notches: iff TL corner art (0,0) == 9 (every state; v2) ----
    mov     ebx, [ebp-0x18]
    mov     ecx, [ebx]                ; TL corner Sprite*
    test    ecx, ecx
    je      out1
    mov     edx, [ecx+4]
    test    edx, edx
    je      out1
    cmp     byte ptr [edx], 9
    jne     out1
    xor     ebx, ebx                  ; y
notchy:
    mov     edi, ebx
    imul    edi, dword ptr [ebp-0xC]
    add     edi, [ebp-8]
    mov     ecx, [ebp-4]
    mov     al, 9
    push    edi
    rep stosb                         ; TL
    pop     edi
    add     edi, [ebp-0x10]
    sub     edi, [ebp-4]
    mov     ecx, [ebp-4]
    rep stosb                         ; TR
    mov     edi, [ebp-0x14]
    dec     edi
    sub     edi, ebx
    imul    edi, dword ptr [ebp-0xC]
    add     edi, [ebp-8]
    mov     ecx, [ebp-4]
    push    edi
    rep stosb                         ; BL
    pop     edi
    add     edi, [ebp-0x10]
    sub     edi, [ebp-4]
    mov     ecx, [ebp-4]
    rep stosb                         ; BR
    inc     ebx
    cmp     ebx, [ebp-4]
    jl      notchy
out1:
    mov     esp, ebp
    pop     ebp
out0:
    ret

; ---- strip_head: ecx = strip Sprite* -> guards; returns CF=1 skip, else
;      ecx=strip, edx = data + w/2 (top-row midpoint) ----
strip_head:
    test    ecx, ecx
    je      sh_bad
    mov     edx, [ecx+4]              ; data
    test    edx, edx
    je      sh_bad
    mov     eax, [ecx+0x10]           ; w
    cmp     eax, 0
    jle     sh_bad
    cmp     eax, 512
    jge     sh_bad
    cmp     eax, [ecx+0xC]            ; w <= pitch
    jg      sh_bad
    mov     eax, [ecx+0x14]           ; h
    cmp     eax, 0
    jle     sh_bad
    cmp     eax, 512
    jge     sh_bad
    mov     eax, [ecx+0x10]
    shr     eax, 1
    add     edx, eax
    clc
    ret
sh_bad:
    stc
    ret

; ---- edge_live: al = colour -> CF=1 if 7 or 9 (no stroke) ----
edge_live:
    cmp     al, 7
    je      el_bad
    cmp     al, 9
    je      el_bad
    clc
    ret
el_bad:
    stc
    ret
"""


def assemble(va):
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    clean = "\n".join(
        ln.split(";", 1)[0].rstrip()
        for ln in ASM.splitlines()
        if ln.split(";", 1)[0].strip())
    enc, _ = ks.asm(clean, va)
    return bytes(enc)


def main():
    code = assemble(PCAVE2_VA)  # position-dependent only via sentinels + internal rel calls
    hexs = " ".join("%02X" % b for b in code)
    with open(r"D:\SmacxUi\work\patches\ringfix_hex.txt", "w") as f:
        f.write("; thunk_btn_ringfix  %d bytes (sentinels: 11111111=g_popup_scale_num, 22222222=thunk_btn_stripes VA)\n" % len(code))
        f.write(hexs + "\n")
    print("%d bytes -> work/patches/ringfix_hex.txt" % len(code))
    return 0


if __name__ == "__main__":
    sys.exit(main())
