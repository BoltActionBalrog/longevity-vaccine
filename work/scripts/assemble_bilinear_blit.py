#!/usr/bin/env python
# Keystone assembler for thunk_bilinear_blit -- a palette-aware BILINEAR
# Buffer->Buffer resampler, DROP-IN for thunk_keyed_stretch_blit:
#
#   __cdecl(srcBuf,destBuf,srcX,srcY,srcW,srcH,dstX,dstY,dstW,dstH,key)  RET 0x2C
#
# thunk_frame_enlarge calls EITHER this or the NN thunk_keyed_stretch_blit,
# chosen by the g_fd_bilinear flag (set only by the file-dialog outer frame in
# thunk_filedlg_frame.do_outer; cleared on read). The NN path's Buffer_copy_3
# (GDI StretchBlt) DROPS source rows/cols at fractional ratios -> the ornate
# frame's thin metallic bevel lines vanish = the torn/gappy frame at non-4K.
# This variant keeps ensure_scratch + Buffer_resize + the keyed Buffer_draw_2
# out, but replaces the stretch with a per-output-pixel BILINEAR average:
# coverage = nearest src texel (key/silhouette identical to NN); colour = the
# (1+-fx)(1+-fy)-weighted blend of the non-key 2x2 neighbours' RGB read from the
# active palette @0x94C590, re-quantised to the nearest palette index. Thin
# lines blend instead of dropping -> smooth thick frame at ANY ratio (the
# faction A5 portrait remedy, applied to the frame-enlarge funnel).
#
# Absolute call/data targets are BAKED (regenerate if any cave/offset moves).
# Frame: locals reserved BEFORE the ebx/esi/edi pushes (portrait_avg aliasing
# crash lesson -- saved regs at [ebp-0x94..-0x9C], locals stop at -0x90).

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA      = 0xA0C000
OFF_THUNK      = 0x2960                 # fresh slot past g_fd_inner (0x2920..0x292F)
THUNK_VA       = PCAVE2_VA + OFF_THUNK  # 0xA0E960

ENSURE_SCRATCH = 0x6686D0   # menu_strip_thunks(0x668200)+0x4D0
G_SCRATCH_BUF  = 0x668710   # menu_strip_thunks+0x510
BUFFER_RESIZE  = 0x5D79C0   # __thiscall(buf,w,h) RET 8
BUFFER_DRAW_2  = 0x5D84C0   # __thiscall(src; dest,key,X,Y,num,den) RET 0x18
PALETTE        = 0x94C590   # PALETTEENTRY colors[256] (R,G,B,flags)

def accum(srow, scol, wlocal, tag):
    # texel idx at sdata+[srow]+[scol]; if != key, accumulate palette*weight.
    # `tag` (e.g. "00") names the skip label -- keystone rejects a label built
    # from `wlocal` (it contains '-' / '0x' -> parsed as arithmetic).
    return f"""
    mov ecx, [ebp{srow}]
    add ecx, [ebp{scol}]
    add ecx, [ebp-0x04]
    movzx edx, byte ptr [ecx]
    cmp edx, [ebp-0x24]
    je  skip{tag}
    mov esi, edx
    shl esi, 2
    add esi, {PALETTE}
    mov edi, [ebp{wlocal}]
    movzx eax, byte ptr [esi]
    imul eax, edi
    add [ebp-0x70], eax
    movzx eax, byte ptr [esi+1]
    imul eax, edi
    add [ebp-0x74], eax
    movzx eax, byte ptr [esi+2]
    imul eax, edi
    add [ebp-0x78], eax
    add [ebp-0x7c], edi
skip{tag}:
"""

asm = f"""
    push ebp
    mov ebp, esp
    sub esp, 0x90
    push ebx
    push esi
    push edi

    ; ---- ensure scratch (eax) + resize to dstW x dstH ----
    call {ENSURE_SCRATCH}
    mov [ebp-0x84], eax              ; scratch ptr
    mov esi, eax
    push dword ptr [ebp+0x2c]        ; dstH
    push dword ptr [ebp+0x28]        ; dstW
    mov ecx, esi
    call {BUFFER_RESIZE}

    ; ---- cache src geometry (region base includes srcX/srcY) ----
    mov eax, [ebp+0x08]
    mov edx, [eax+0x4a8]
    mov [ebp-0x08], edx              ; sstride
    mov ecx, [eax+0x54]
    mov ebx, [ebp+0x14]
    imul ebx, edx
    add ecx, ebx
    add ecx, [ebp+0x10]
    mov [ebp-0x04], ecx              ; sdata (region top-left)
    mov eax, [ebp+0x18]
    mov [ebp-0x0c], eax              ; srcW
    mov eax, [ebp+0x1c]
    mov [ebp-0x10], eax              ; srcH

    ; ---- cache dst (scratch) geometry ----
    mov edx, [esi+0x54]
    mov [ebp-0x14], edx              ; ddata
    mov edx, [esi+0x4a8]
    mov [ebp-0x18], edx              ; dstride
    mov eax, [ebp+0x28]
    mov [ebp-0x1c], eax              ; dstW
    mov eax, [ebp+0x2c]
    mov [ebp-0x20], eax              ; dstH
    mov eax, [ebp+0x30]
    mov [ebp-0x24], eax              ; key

    mov dword ptr [ebp-0x28], 0      ; oy = 0
row_loop:
    mov eax, [ebp-0x28]
    cmp eax, [ebp-0x20]
    jge done
    imul eax, [ebp-0x10]
    shl eax, 8
    cdq
    idiv dword ptr [ebp-0x20]
    mov ebx, eax
    sar ebx, 8
    mov [ebp-0x30], ebx              ; sy
    and eax, 0xff
    mov [ebp-0x34], eax              ; fy
    mov eax, ebx
    inc eax
    mov ecx, [ebp-0x10]
    dec ecx
    cmp eax, ecx
    jle sy1_ok
    mov eax, ecx
sy1_ok:
    mov [ebp-0x38], eax             ; sy1
    mov eax, [ebp-0x30]
    imul eax, [ebp-0x08]
    mov [ebp-0x48], eax             ; srow0
    mov eax, [ebp-0x38]
    imul eax, [ebp-0x08]
    mov [ebp-0x4c], eax             ; srow1
    mov eax, 0x100
    sub eax, [ebp-0x34]
    mov [ebp-0x58], eax             ; wy0
    mov eax, [ebp-0x34]
    mov [ebp-0x5c], eax             ; wy1
    mov eax, [ebp-0x28]
    imul eax, [ebp-0x18]
    mov [ebp-0x80], eax             ; drow

    mov dword ptr [ebp-0x2c], 0     ; ox = 0
col_loop:
    mov eax, [ebp-0x2c]
    cmp eax, [ebp-0x1c]
    jge row_next
    imul eax, [ebp-0x0c]
    shl eax, 8
    cdq
    idiv dword ptr [ebp-0x1c]
    mov ebx, eax
    sar ebx, 8
    mov [ebp-0x3c], ebx             ; sx
    and eax, 0xff
    mov [ebp-0x40], eax             ; fx
    mov eax, ebx
    inc eax
    mov ecx, [ebp-0x0c]
    dec ecx
    cmp eax, ecx
    jle sx1_ok
    mov eax, ecx
sx1_ok:
    mov [ebp-0x44], eax             ; sx1
    mov eax, 0x100
    sub eax, [ebp-0x40]
    mov [ebp-0x50], eax             ; wx0
    mov eax, [ebp-0x40]
    mov [ebp-0x54], eax             ; wx1
    mov eax, [ebp-0x50]
    imul eax, [ebp-0x58]
    mov [ebp-0x60], eax             ; w00
    mov eax, [ebp-0x54]
    imul eax, [ebp-0x58]
    mov [ebp-0x64], eax             ; w01
    mov eax, [ebp-0x50]
    imul eax, [ebp-0x5c]
    mov [ebp-0x68], eax             ; w10
    mov eax, [ebp-0x54]
    imul eax, [ebp-0x5c]
    mov [ebp-0x6c], eax             ; w11

    ; coverage: nearest texel
    mov ecx, [ebp-0x48]
    cmp dword ptr [ebp-0x34], 0x80
    jl  cov_y0
    mov ecx, [ebp-0x4c]
cov_y0:
    mov edx, [ebp-0x3c]
    cmp dword ptr [ebp-0x40], 0x80
    jl  cov_x0
    mov edx, [ebp-0x44]
cov_x0:
    add ecx, edx
    add ecx, [ebp-0x04]
    movzx eax, byte ptr [ecx]
    cmp eax, [ebp-0x24]
    je  put_key

    mov dword ptr [ebp-0x70], 0     ; accR
    mov dword ptr [ebp-0x74], 0     ; accG
    mov dword ptr [ebp-0x78], 0     ; accB
    mov dword ptr [ebp-0x7c], 0     ; sumw
{accum("-0x48","-0x3c","-0x60","00")}{accum("-0x48","-0x44","-0x64","01")}{accum("-0x4c","-0x3c","-0x68","10")}{accum("-0x4c","-0x44","-0x6c","11")}
    mov ebx, [ebp-0x7c]             ; sumw
    test ebx, ebx
    jle put_key
    mov eax, [ebp-0x70]
    cdq
    idiv ebx
    mov [ebp-0x70], eax             ; R
    mov eax, [ebp-0x74]
    cdq
    idiv ebx
    mov [ebp-0x74], eax             ; G
    mov eax, [ebp-0x78]
    cdq
    idiv ebx
    mov [ebp-0x78], eax             ; B
    xor esi, esi                    ; i
    mov edi, {PALETTE}
    xor ecx, ecx                    ; best
    mov ebx, 0x7fffffff             ; bestd
pal_loop:
    movzx eax, byte ptr [edi]
    sub eax, [ebp-0x70]
    imul eax, eax
    mov edx, eax
    movzx eax, byte ptr [edi+1]
    sub eax, [ebp-0x74]
    imul eax, eax
    add edx, eax
    movzx eax, byte ptr [edi+2]
    sub eax, [ebp-0x78]
    imul eax, eax
    add edx, eax
    cmp edx, ebx
    jge pal_next
    mov ebx, edx
    mov ecx, esi
pal_next:
    add edi, 4
    inc esi
    cmp esi, 0x100
    jl pal_loop
    mov eax, [ebp-0x80]
    add eax, [ebp-0x2c]
    add eax, [ebp-0x14]
    mov [eax], cl
    jmp col_next
put_key:
    mov eax, [ebp-0x80]
    add eax, [ebp-0x2c]
    add eax, [ebp-0x14]
    mov edx, [ebp-0x24]
    mov [eax], dl
col_next:
    inc dword ptr [ebp-0x2c]
    jmp col_loop
row_next:
    inc dword ptr [ebp-0x28]
    jmp row_loop

done:
    ; ---- keyed blit scratch -> destBuf at (dstX,dstY), 1:1 ----
    mov esi, [ebp-0x84]            ; scratch ptr
    push 1
    push 1
    push dword ptr [ebp+0x24]      ; dstY
    push dword ptr [ebp+0x20]      ; dstX
    push dword ptr [ebp+0x30]      ; key
    push dword ptr [ebp+0x0c]      ; destBuf
    mov ecx, esi
    call {BUFFER_DRAW_2}

    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    ret 0x2c
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
enc, _ = ks.asm(asm, THUNK_VA)
b = bytes(enc)
print("THUNK_VA 0x%X  OFF 0x%X" % (THUNK_VA, OFF_THUNK))
print("LEN", len(b), "ENDS 0x%X" % (OFF_THUNK + len(b)))
print(" ".join("%02X" % x for x in b))
