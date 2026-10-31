"""Assemble thunk_faction_dropimg v3 (the faction row drop arrow) with keystone.

The faction row dropdown arrow is ONE opaque 16x16 state sprite (measured on the real image, g = 16):
  state 0  AE / EE 1-row scanline background, a 0x41 glyph, key-9 corners;
  state 1  the same with a 1-px E0 ring (all four sides) and an E0 glyph (hover);
  state 2  E1 / E0 scanline background, a 0x41 glyph, key-9 corners (pressed).
v1 NN-filled it uniformly x2.5 (the 1px scanlines became ~2.5px bands); v2 regenerated AE / EE at native density on
a FLOOR NN map.  v3 (2026-10-25 wave-2 W2D, F40a; law scaling_laws.drop_arrow_render; guards
tests/test_faction_dropimg_parity.py + tests/test_scaling_edge_stroke.py):
  1. MIRROR-SYMMETRIC centre NN on both axes (scaling_laws.nn_mirror_index): the centred glyph stays centred (v2's
     floor map: 1600x1200 margins 4 | 3, 1920x1080 3 | 2);
  2. AE / EE -> AE on the dest-row stripe-top rows ((r mod P) < P >> 1, P = g_stripe_period), else EE (as v2);
     E1 -> E0 on top rows, else E1, and E0 likewise only when the source holds an E1 texel (content-keyed: state 1's
     E0 is a SOLID ring + glyph colour) -- v2 copied E0 / E1 through, so the pressed arrow banded;
  3. each source edge whose outermost texel is a 1-px stroke (not key, differs from the next two inward, at the
     middle row / column) -> a K = ceil(g/16) band of that colour on the whole side (needs outW, outH >= 2K);
  4. each corner whose source texel is the key -> an s x s key square, s = ceil(g/16) (v2: the NN image of the 1-px
     notch, 1600x1200 TL 2x2 / TR 1x2 / BL 2x1 / BR 1x1).
RELOCATED 0x1780 -> pcave2 0x37900 (the W2D region; the old 225 B slot is zeroed).

Entry (thunk_faction_portrait's `push thunk_faction_dropimg / ret` tail for the small sprites): ecx = src Sprite,
  [esp]=ret, [esp+4]=dest Buffer, [esp+8]=key, [esp+c]=x, [esp+10]=y, [esp+14]=num, [esp+18]=den.
Gate: g_faction_active == 1 && g_popup_scale_num > 16 && the sprite is one of the drop arrows' three state sprites
(FactionPickWin+0x85FC / +0x8628 / +0x8654, FactionPickWin_build @0x488FF3..0x489013; v2 took ANY <= 32 px state
sprite while the picker ran -- the generic ScrollBar arrows of a popup opened from the picker included, 2026-10-25 audit)
&& 3 <= srcW <= 32 && srcH >= 3 && src data != 0 -> custom render, ret 0x18 (Sprite_draw_2 is __stdcall, cleans its 6 args).  Else -> tail-call Sprite_draw_2 (native NN,
unmodified args).  dest = the dropdown's OWN buffer (w@+0x80, h@+0x84 neg, stride@+0x4a8, data@+0x54), filled whole
from (0,0) (x/y ignored).  src: data@+0x4, stride@+0x10, w@+0x18, h@+0x1c (v2's fields).
(fix 8, 2026-10-18: the gate was ScreenWidth>1024, which rendered at g = 16 on 1280..1366-wide screens -- key-9
corners copied into the buffer -- and is g-gated now like every other scaling thunk.)
Preserves ebx/esi/edi/ebp (callee-saved); clobbers eax/ecx/edx (Sprite_draw_2 does too).
"""
import sys
from pathlib import Path
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
THUNK_OFF = 0x37900
THUNK_VA  = PCAVE2_VA + THUNK_OFF

ASM = r"""
    cmp     dword ptr [0x00A0D2D0], 1      ; g_faction_active
    jne     native
    cmp     dword ptr [0x00668740], 0x10   ; g_popup_scale_num <= 16 -> native (the lo-res gate is on g, never a width)
    jle     native
    lea     eax, [ecx-0x0082AD14]         ; only the drop arrows' three state sprites, FactionPickWin+0x85FC/+0x8628/+0x8654
    cmp     eax, 0
    je      arrow
    cmp     eax, 0x2c
    je      arrow
    cmp     eax, 0x58
    jne     native
arrow:
    mov     eax, [ecx+0x18]               ; srcW
    cmp     eax, 0x20
    jg      native
    cmp     eax, 3
    jl      native
    cmp     dword ptr [ecx+0x1c], 3       ; srcH
    jl      native
    cmp     dword ptr [ecx+0x04], 0       ; src data
    je      native

    push    ebp
    mov     ebp, esp
    sub     esp, 0x40
    push    ebx
    push    esi
    push    edi
    mov     esi, [ecx+0x04]
    mov     [ebp-0x24], esi               ; srcData
    mov     eax, [ecx+0x10]
    mov     [ebp-0x04], eax               ; srcStride
    mov     eax, [ecx+0x18]
    mov     [ebp-0x08], eax               ; srcW
    mov     eax, [ecx+0x1c]
    mov     [ebp-0x0c], eax               ; srcH
    mov     edx, [ebp+0x08]
    mov     eax, [edx+0x54]
    mov     [ebp-0x28], eax               ; destData
    mov     eax, [edx+0x4a8]
    mov     [ebp-0x10], eax               ; destStride
    mov     eax, [edx+0x80]
    mov     [ebp-0x14], eax               ; outW
    mov     eax, [edx+0x84]               ; destH (negative=top-down)
    test    eax, eax
    jge     hpos
    neg     eax
hpos:
    mov     [ebp-0x18], eax               ; outH
    xor     ebx, ebx                      ; hasE1: any E1 texel in the source
    xor     ecx, ecx
scan_r:
    cmp     ecx, [ebp-0x0c]
    jge     scan_done
    mov     edi, ecx
    imul    edi, [ebp-0x04]
    add     edi, esi
    xor     edx, edx
scan_c:
    cmp     edx, [ebp-0x08]
    jge     scan_next
    cmp     byte ptr [edi+edx], 0xe1
    jne     scan_n
    mov     bl, 1
scan_n:
    inc     edx
    jmp     scan_c
scan_next:
    inc     ecx
    jmp     scan_r
scan_done:
    mov     [ebp-0x2c], ebx               ; hasE1
    xor     ebx, ebx                      ; r = 0
rowloop:
    cmp     ebx, [ebp-0x18]
    jge     render_done
    push    dword ptr [ebp-0x0c]
    push    dword ptr [ebp-0x18]
    push    ebx
    call    mirror                        ; sy
    imul    eax, [ebp-0x04]
    add     eax, [ebp-0x24]
    mov     [ebp-0x1c], eax               ; srcRowPtr
    mov     eax, ebx
    imul    eax, [ebp-0x10]
    add     eax, [ebp-0x28]
    mov     [ebp-0x20], eax               ; destRowPtr
    mov     eax, ebx                      ; law stripe_top: (row mod P) < P >> 1
    xor     edx, edx
    div     dword ptr [0x66879c]
    mov     eax, dword ptr [0x66879c]
    shr     eax, 1
    xor     ecx, ecx
    cmp     edx, eax
    setb    cl
    mov     [ebp-0x30], ecx               ; onTop
    xor     edi, edi                      ; c = 0
colloop:
    cmp     edi, [ebp-0x14]
    jge     rownext
    push    dword ptr [ebp-0x08]
    push    dword ptr [ebp-0x14]
    push    edi
    call    mirror                        ; sx
    add     eax, [ebp-0x1c]
    movzx   eax, byte ptr [eax]
    cmp     al, 0xae
    je      pair_a
    cmp     al, 0xee
    je      pair_a
    cmp     al, 0xe1
    je      pair_e
    cmp     al, 0xe0
    jne     write
    cmp     dword ptr [ebp-0x2c], 0
    je      write
pair_e:
    mov     al, 0xe0
    cmp     dword ptr [ebp-0x30], 0
    jne     write
    mov     al, 0xe1
    jmp     write
pair_a:
    mov     al, 0xae
    cmp     dword ptr [ebp-0x30], 0
    jne     write
    mov     al, 0xee
write:
    mov     edx, [ebp-0x20]
    mov     [edx+edi], al
    inc     edi
    jmp     colloop
rownext:
    inc     ebx
    jmp     rowloop
render_done:
    mov     eax, dword ptr [0x00668740]   ; K = s = ceil(g/16); bands + corners need outW, outH >= 2K
    add     eax, 15
    sar     eax, 4
    mov     [ebp-0x34], eax
    add     eax, eax
    cmp     [ebp-0x14], eax
    jl      done
    cmp     [ebp-0x18], eax
    jl      done
    mov     esi, [ebp-0x08]               ; TOP: src rows 0 / 1 / 2 at xm
    shr     esi, 1
    add     esi, [ebp-0x24]
    mov     ebx, [ebp-0x04]
    call    chk
    jc      nb0
    push    dword ptr [ebp-0x34]
    push    dword ptr [ebp-0x14]
    push    0
    push    0
    call    fillr
nb0:
    mov     esi, [ebp-0x0c]               ; BOTTOM: src rows H-1 / H-2 / H-3 at xm
    dec     esi
    imul    esi, [ebp-0x04]
    mov     eax, [ebp-0x08]
    shr     eax, 1
    add     esi, eax
    add     esi, [ebp-0x24]
    neg     ebx
    call    chk
    jc      nb1
    push    dword ptr [ebp-0x34]
    push    dword ptr [ebp-0x14]
    mov     edx, [ebp-0x18]
    sub     edx, [ebp-0x34]
    push    edx
    push    0
    call    fillr
nb1:
    mov     esi, [ebp-0x0c]               ; LEFT: src row ym, cols 0 / 1 / 2
    shr     esi, 1
    imul    esi, [ebp-0x04]
    add     esi, [ebp-0x24]
    mov     ebx, 1
    call    chk
    jc      nb2
    push    dword ptr [ebp-0x18]
    push    dword ptr [ebp-0x34]
    push    0
    push    0
    call    fillr
nb2:
    add     esi, [ebp-0x08]               ; RIGHT: src row ym, cols W-1 / W-2 / W-3
    dec     esi
    neg     ebx
    call    chk
    jc      nb3
    push    dword ptr [ebp-0x18]
    push    dword ptr [ebp-0x34]
    push    0
    mov     edx, [ebp-0x14]
    sub     edx, [ebp-0x34]
    push    edx
    call    fillr
nb3:
    mov     esi, [ebp-0x24]               ; corners: s x s key where the src corner texel is the key
    mov     al, 9
    cmp     byte ptr [esi], 9
    jne     nc0
    push    dword ptr [ebp-0x34]
    push    dword ptr [ebp-0x34]
    push    0
    push    0
    call    fillr
nc0:
    mov     esi, [ebp-0x24]
    add     esi, [ebp-0x08]
    cmp     byte ptr [esi-1], 9
    jne     nc1
    mov     al, 9
    push    dword ptr [ebp-0x34]
    push    dword ptr [ebp-0x34]
    push    0
    mov     edx, [ebp-0x14]
    sub     edx, [ebp-0x34]
    push    edx
    call    fillr
nc1:
    mov     esi, [ebp-0x0c]
    dec     esi
    imul    esi, [ebp-0x04]
    add     esi, [ebp-0x24]
    cmp     byte ptr [esi], 9
    jne     nc2
    mov     al, 9
    push    dword ptr [ebp-0x34]
    push    dword ptr [ebp-0x34]
    mov     edx, [ebp-0x18]
    sub     edx, [ebp-0x34]
    push    edx
    push    0
    call    fillr
nc2:
    add     esi, [ebp-0x08]
    cmp     byte ptr [esi-1], 9
    jne     done
    mov     al, 9
    push    dword ptr [ebp-0x34]
    push    dword ptr [ebp-0x34]
    mov     edx, [ebp-0x18]
    sub     edx, [ebp-0x34]
    push    edx
    mov     edx, [ebp-0x14]
    sub     edx, [ebp-0x34]
    push    edx
    call    fillr
done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x18
native:
    push    0x005E4B4A                     ; Sprite_draw_2 (native NN, original args)
    ret
mirror:
    mov     ecx, [esp+0x08]               ; stdcall(j, dst, src) -> eax = scaling_laws.nn_mirror_index; clobbers ecx, edx
    lea     eax, [ecx-1]
    sub     eax, [esp+0x04]               ; m = dst - 1 - j
    cmp     [esp+0x04], eax
    jle     m_first
    lea     eax, [eax+eax+1]
    imul    eax, dword ptr [esp+0x0c]
    add     ecx, ecx
    cdq
    idiv    ecx
    neg     eax
    add     eax, [esp+0x0c]
    dec     eax                           ; src - 1 - ((2m+1)*src) // (2*dst)
    ret     0x0c
m_first:
    mov     eax, [esp+0x04]
    lea     eax, [eax+eax+1]
    imul    eax, dword ptr [esp+0x0c]
    add     ecx, ecx
    cdq
    idiv    ecx                           ; ((2j+1)*src) // (2*dst)
    ret     0x0c
chk:
    mov     al, byte ptr [esi]            ; esi = &n0, ebx = step -> CF clear + al = n0 iff a 1-px stroke
    cmp     al, 9
    je      chk_no
    cmp     al, byte ptr [esi+ebx]
    je      chk_no
    cmp     al, byte ptr [esi+ebx*2]
    je      chk_no
    clc
    ret
chk_no:
    stc
    ret
fillr:
    push    edi                           ; stdcall(x, y, w, h), al = colour; dest [ebp-0x28] / [ebp-0x10]
    push    ebx
    mov     ebx, [esp+0x18]               ; h
    mov     edx, [esp+0x10]               ; y
fr_row:
    mov     edi, edx
    imul    edi, [ebp-0x10]
    add     edi, [ebp-0x28]
    add     edi, [esp+0x0c]               ; + x
    mov     ecx, [esp+0x14]               ; w
fr_px:
    mov     [edi], al
    inc     edi
    dec     ecx
    jnz     fr_px
    inc     edx
    dec     ebx
    jnz     fr_row
    pop     ebx
    pop     edi
    ret     0x10
"""


HEX_OUT = Path(__file__).resolve().parent.parent / "patches" / "dropdither_hex.txt"   # work\patches, this repo's


def main():
    out = open(HEX_OUT, "w")
    def w(s): out.write(s + "\n"); out.flush()
    try:
        ks = Ks(KS_ARCH_X86, KS_MODE_32)
        clean = "\n".join(ln.split(";", 1)[0].rstrip() for ln in ASM.splitlines() if ln.split(";",1)[0].strip())
        enc, count = ks.asm(clean, THUNK_VA)
        hexbytes = " ".join("%02X" % b for b in enc)
        w(f"; thunk_faction_dropimg @ VA 0x{THUNK_VA:X} (pcave2 +0x{THUNK_OFF:X}; src scripts/assemble_dropdither.py)")
        w(f"; {len(enc)} bytes, {count} statements; ends at pcave2 +0x{THUNK_OFF+len(enc):X}")
        w(hexbytes)
    except Exception as e:
        w(f"; ERROR: {type(e).__name__}: {e}"); out.close(); raise
    out.close(); return 0


if __name__ == "__main__":
    sys.exit(main())
