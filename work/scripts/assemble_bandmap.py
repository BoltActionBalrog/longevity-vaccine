#!/usr/bin/env python
"""Keystone assembler for the 9-slice BAND-MAP enlarge bake (2026-07-09).

Replaces the uniform nearest-neighbour enlarge of an already-rendered 9-slice frame with a
per-axis band map. Reference implementation + proof: work/scripts/scaling_laws.py
(`axis_map`), swept by work/tests/test_scaling_laws.py. THIS IS A PORT — if it disagrees
with the reference, this is wrong. Parity is checked by tests/test_bandmap_asm_parity.py,
which runs THIS code under an x86 emulator against the Python.

WHY (measured, not modelled — work/tests/strokecensus_before_75cae700.log):
  the shipped blit is Buffer_copy_3 -> a CENTRE-ALIGNED NN stretch, symmetric at every
  ratio EXCEPT a half-integer one. g=40 is exactly 40/16 = 2.5, so at 4K (and only at 4K)
  the .5 phase splits the opposite strokes: 34 of 42 frames measured 2px near / 3px far.
  At g=22 and g=25 all 84 measured frames were already symmetric.

THE BAKE (two thunks; no byte-length change at any existing site):

  thunk_fe_bandmap    -- the four frame renderers each reach thunk_frame_enlarge through one
                         `E8`, and each keeps `params` at [ebp-8] in its own live frame.
                         Retarget those four rel32s here: read params[0] (the TL corner
                         sprite), stash its canvas dims as the per-axis band depth into
                         g_band_nx/g_band_ny, then push;ret into the UNCHANGED
                         thunk_frame_enlarge, so its epilogue (g_fe_* stash -> fe_pair_remap,
                         g_fc_exact consume) is preserved exactly.

  thunk_bandmap_blit  -- DROP-IN for thunk_keyed_stretch_blit:
                         __cdecl(srcBuf,destBuf,srcX,srcY,srcW,srcH,dstX,dstY,dstW,dstH,key)
                         RET 0x2C. thunk_frame_enlarge's NN path calls this instead. Consumes
                         g_band_nx/ny (one-shot, the g_fc_exact pattern) and falls back by
                         tail-jumping to thunk_keyed_stretch_blit for any geometry it does not
                         handle. The bilinear path (g_fd_bilinear) is untouched.

NATIVE NO-OP: the four renderers early-out to a plain Buffer_box_sprite at g<=16 and never
call the enlarge, so 1024x768 is byte-identical to vanilla by construction. (That is also
why the stroke census cannot observe g=16 — no frame_enlarge call exists there.)

FALLBACK (-> thunk_keyed_stretch_blit == today's shipped behaviour):
  nx<=0 or ny<=0 (no stash)      nx>64 or ny>64        srcX!=0 or srcY!=0
  srcW < 2*nx+1 or srcH < 2*ny+1                       dstW<=0 or dstH<=0
  dstW>4096 or dstH>2048         B<=0 or B>255 or dstN < 2*B   (per axis)
  null src/dest pixel data
These mirror `scaling_laws.axis_map` returning None, plus buffer-size limits.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PCAVE2 = 0xA0C000

# Sentinel imm32 -> yaml placeholder (same convention as assemble_devfill_stripes.py).
SENT = {
    0x71111111: "{abs32:g_band_nx}",
    0x71222222: "{abs32:g_band_ny}",
    0x71333333: "{abs32:g_bm_fwdx}",
    0x71444444: "{abs32:g_bm_fwdy}",
    0x71555555: "{abs32:g_bm_fx}",
    0x71666666: "{abs32:g_bm_fy}",
    0x71777777: "{abs32:g_popup_scale_num}",
    0x71888888: "{abs32:g_bm_dstw}",
    0x71999999: "{abs32:g_bm_dsth}",
    0x71AAAAAA: "{abs32:g_fe_w}",
    0x71BBBBBB: "{abs32:g_fe_h}",
    0x72111111: "{abs32:thunk_frame_enlarge}",
    0x72222222: "{abs32:thunk_keyed_stretch_blit}",
}

THUNKS = []
def thunk(name, offset, asm):
    THUNKS.append((name, offset, asm))


# ============================ thunk_fe_bandmap ============================
# Entered by E8 from a renderer whose frame is still live: ecx = native scratch buffer,
# [ebp-8] = BoxSpriteParams*. Stash the TL corner sprite's canvas dims (the native band
# depth per axis; 6x6 simple, 61x44 ornate picker), then push;ret into thunk_frame_enlarge
# so its RET 0x18 cleans the caller's args. Must not clobber ecx or the stack.
thunk("thunk_fe_bandmap", 0xA210, """
    mov     dword ptr [0x71111111], 0
    mov     dword ptr [0x71222222], 0
    mov     dword ptr [0x71888888], 0
    mov     dword ptr [0x71999999], 0
    mov     eax, [ebp-8]
    test    eax, eax
    je      go
    mov     eax, [eax]
    test    eax, eax
    je      go
    mov     edx, [eax+0x18]
    mov     dword ptr [0x71111111], edx
    mov     edx, [eax+0x1c]
    mov     dword ptr [0x71222222], edx
    /* EXACT FILL. The rect the renderer intends is its [ebp+8] arg. thunk_frame_enlarge sizes the
       blit as dstW = srcW*g/16 where srcW = span*16/g was ALREADY floored -- a double floor that
       under-fills the rect by up to 2px. Measured on the Quit modal @1920: outer rect 637x42 drawn
       635x39, inner 629x34 drawn 627x33 -> top channel 3px, bottom 1px, though the two rects are
       perfectly concentric (4/4/4/4). At g=16 dst == span exactly, so EXACT FILL IS the vanilla
       behaviour; the frame9 prototype had it by construction and the first bake dropped it.
       D = L - X (the renderer's outward grow); W = (R+D) - X + 1; H = (B+D) - Y + 1.
       Stack here: [esp]=ret [esp+4]=dest [esp+8]=key [esp+0xc]=X [esp+0x10]=Y (+4 after push ebx). */
    mov     eax, [ebp+8]
    test    eax, eax
    je      go
    push    ebx
    mov     edx, [eax]
    sub     edx, [esp+0x10]
    mov     ebx, [eax+8]
    add     ebx, edx
    sub     ebx, [esp+0x10]
    inc     ebx
    mov     dword ptr [0x71888888], ebx
    mov     edx, [eax+4]
    sub     edx, [esp+0x14]
    mov     ebx, [eax+0xc]
    add     ebx, edx
    sub     ebx, [esp+0x14]
    inc     ebx
    mov     dword ptr [0x71999999], ebx
    pop     ebx
go:
    push    0x72111111
    ret
""")


# ============================ thunk_bandmap_blit ============================
# __cdecl(srcBuf,destBuf,srcX,srcY,srcW,srcH,dstX,dstY,dstW,dstH,key)  RET 0x2C
# On entry: [esp+4]=srcBuf [esp+8]=destBuf [esp+0xc]=srcX [esp+0x10]=srcY [esp+0x14]=srcW
#           [esp+0x18]=srcH [esp+0x1c]=dstX [esp+0x20]=dstY [esp+0x24]=dstW
#           [esp+0x28]=dstH [esp+0x2c]=key
# After `push ebp; mov ebp,esp`, add 4 to each: srcBuf=+8 ... key=+0x30.
#
# Locals (ebp-):  4 Bx   8 By   12 K   16 srcData  20 srcStride  24 dstData  28 dstStride
#                32 dstBufW  36 dstBufH  40 i0  44 i1  48 nx  52 ny  56 j
thunk("thunk_bandmap_blit", 0xA300, """
    mov     eax, dword ptr [0x71111111]
    mov     edx, dword ptr [0x71222222]
    mov     dword ptr [0x71111111], 0
    mov     dword ptr [0x71222222], 0
    test    eax, eax
    jle     fallback
    test    edx, edx
    jle     fallback
    /* EXACT FILL: replace dstW/dstH with the renderer's rect span (consume-on-use), and refresh
       g_fe_w/h so thunk_frame_enlarge's fe_pair_remap epilogue covers the whole rect. Sanity cap:
       only ever GROW, and never by more than 4px -- anything else means the stash does not belong
       to this blit, so keep the enlarge's own numbers.
       After push ecx + push ebx: dstW at [esp+0x2c], dstH at [esp+0x30]. */
    push    ecx
    push    ebx
    mov     ecx, dword ptr [0x71888888]
    mov     dword ptr [0x71888888], 0
    test    ecx, ecx
    jle     ov_h
    mov     ebx, [esp+0x2c]
    cmp     ecx, ebx
    jl      ov_h
    sub     ebx, ecx
    neg     ebx
    cmp     ebx, 4
    jg      ov_h
    mov     [esp+0x2c], ecx
    mov     dword ptr [0x71AAAAAA], ecx
ov_h:
    mov     ecx, dword ptr [0x71999999]
    mov     dword ptr [0x71999999], 0
    test    ecx, ecx
    jle     ov_done
    mov     ebx, [esp+0x30]
    cmp     ecx, ebx
    jl      ov_done
    sub     ebx, ecx
    neg     ebx
    cmp     ebx, 4
    jg      ov_done
    mov     [esp+0x30], ecx
    mov     dword ptr [0x71BBBBBB], ecx
ov_done:
    pop     ebx
    pop     ecx
    cmp     eax, 64
    jg      fallback
    cmp     edx, 64
    jg      fallback
    cmp     dword ptr [esp+0xc], 0
    jne     fallback
    cmp     dword ptr [esp+0x10], 0
    jne     fallback
    mov     ecx, [esp+0x24]
    test    ecx, ecx
    jle     fallback
    cmp     ecx, 4096
    jg      fallback
    mov     ecx, [esp+0x28]
    test    ecx, ecx
    jle     fallback
    cmp     ecx, 2048
    jg      fallback
    mov     ecx, eax
    add     ecx, ecx
    inc     ecx
    cmp     [esp+0x14], ecx
    jl      fallback
    mov     ecx, edx
    add     ecx, ecx
    inc     ecx
    cmp     [esp+0x18], ecx
    jl      fallback

    push    ebp
    mov     ebp, esp
    sub     esp, 96
    push    ebx
    push    esi
    push    edi
    mov     [ebp-48], eax
    mov     [ebp-52], edx

    /* K = halfDown(g,16) = (2g+15)/32 */
    mov     eax, dword ptr [0x71777777]
    add     eax, eax
    add     eax, 15
    xor     edx, edx
    mov     ecx, 32
    div     ecx
    mov     [ebp-12], eax

    /* --- X axis: bm_axis(n=nx, dstN=dstW, srcN=srcW, K, f=fwdx, out=fx) --- */
    push    0x71555555
    push    0x71333333
    push    dword ptr [ebp-12]
    push    dword ptr [ebp+0x18]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp-48]
    call    bm_axis
    add     esp, 24
    test    eax, eax
    je      unwind_fallback
    mov     [ebp-4], edx

    /* --- Y axis --- */
    push    0x71666666
    push    0x71444444
    push    dword ptr [ebp-12]
    push    dword ptr [ebp+0x1c]
    push    dword ptr [ebp+0x2c]
    push    dword ptr [ebp-52]
    call    bm_axis
    add     esp, 24
    test    eax, eax
    je      unwind_fallback
    mov     [ebp-8], edx

    /* --- buffer fields --- */
    mov     esi, [ebp+0x8]
    mov     eax, [esi+0x54]
    test    eax, eax
    je      unwind_fallback
    mov     [ebp-16], eax
    mov     eax, [esi+0x4a8]
    mov     [ebp-20], eax
    mov     edi, [ebp+0xc]
    mov     eax, [edi+0x54]
    test    eax, eax
    je      unwind_fallback
    mov     [ebp-24], eax
    mov     eax, [edi+0x4a8]
    mov     [ebp-28], eax
    mov     eax, [edi+0x80]
    mov     [ebp-32], eax
    mov     eax, [edi+0x84]
    neg     eax
    mov     [ebp-36], eax

    /* --- x clip: i0 = max(0,-dstX), i1 = min(dstW, dstBufW-dstX) --- */
    xor     eax, eax
    mov     ecx, [ebp+0x20]
    neg     ecx
    cmp     ecx, eax
    jle     x0ok
    mov     eax, ecx
x0ok:
    mov     [ebp-40], eax
    mov     eax, [ebp-32]
    sub     eax, [ebp+0x20]
    mov     ecx, [ebp+0x28]
    cmp     eax, ecx
    jle     x1ok
    mov     eax, ecx
x1ok:
    mov     [ebp-44], eax
    mov     eax, [ebp-40]
    cmp     eax, [ebp-44]
    jge     done

    mov     dword ptr [ebp-56], 0
row_loop:
    mov     eax, [ebp-56]
    cmp     eax, [ebp+0x2c]
    jge     done
    mov     ecx, [ebp+0x24]
    add     ecx, eax
    js      row_next
    cmp     ecx, [ebp-36]
    jge     done

    mov     edx, 0x71666666
    movzx   edx, word ptr [edx+eax*2]
    imul    edx, [ebp-20]
    add     edx, [ebp-16]
    mov     esi, edx

    mov     eax, ecx
    imul    eax, [ebp-28]
    add     eax, [ebp-24]
    add     eax, [ebp+0x20]
    mov     edi, eax

    mov     ebx, [ebp-40]
col_loop:
    cmp     ebx, [ebp-44]
    jge     row_next
    mov     edx, 0x71555555
    movzx   edx, word ptr [edx+ebx*2]
    mov     al, [esi+edx]
    mov     ecx, [ebp+0x30]
    cmp     ecx, -1
    je      store
    movzx   edx, al
    cmp     edx, ecx
    je      col_next
store:
    mov     [edi+ebx], al
col_next:
    inc     ebx
    jmp     col_loop
row_next:
    inc     dword ptr [ebp-56]
    jmp     row_loop

done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x2c

unwind_fallback:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
fallback:
    push    0x72222222
    ret

/* ============================ bm_axis ============================
   cdecl(n, dstN, srcN, K, fbuf, outbuf) -> eax = 1 ok / 0 fail, edx = B
   After prologue: n=[ebp+8] dstN=[ebp+0xc] srcN=[ebp+0x10] K=[ebp+0x14]
                   fbuf=[ebp+0x18] outbuf=[ebp+0x1c]
   Locals: -4 B  -8 mode  -12 rem  -16 m  -20 pos  -24 y  -28 acc  -32 s
   Mirrors scaling_laws.axis_map (incl. its None conditions) exactly. */
bm_axis:
    push    ebp
    mov     ebp, esp
    sub     esp, 40
    push    ebx
    push    esi
    push    edi

    /* B = halfDown(n*dstN, srcN) */
    mov     eax, [ebp+8]
    imul    eax, [ebp+0xc]
    add     eax, eax
    add     eax, [ebp+0x10]
    dec     eax
    xor     edx, edx
    mov     ecx, [ebp+0x10]
    add     ecx, ecx
    div     ecx
    mov     [ebp-4], eax
    test    eax, eax
    jle     ax_fail
    cmp     eax, 255
    jg      ax_fail
    mov     ecx, eax
    add     ecx, ecx
    cmp     [ebp+0xc], ecx
    jl      ax_fail

    /* mode = pinned iff n > 2 && B >= 2K */
    mov     dword ptr [ebp-8], 0
    cmp     dword ptr [ebp+8], 2
    jle     ax_mode_done
    mov     eax, [ebp+0x14]
    add     eax, eax
    cmp     [ebp-4], eax
    jl      ax_mode_done
    mov     dword ptr [ebp-8], 1
    mov     eax, [ebp-4]
    sub     eax, [ebp+0x14]
    sub     eax, [ebp+0x14]
    mov     [ebp-12], eax
    mov     eax, [ebp+8]
    sub     eax, 2
    mov     [ebp-16], eax
ax_mode_done:

    /* fbuf: pos=0; for y=0..n-1: repeat width(y): fbuf[pos++] = y */
    mov     dword ptr [ebp-20], 0
    mov     dword ptr [ebp-24], 0
ax_y_loop:
    mov     eax, [ebp-24]
    cmp     eax, [ebp+8]
    jge     ax_build_out
    mov     eax, [ebp-24]
    inc     eax
    push    eax
    call    bm_cum
    add     esp, 4
    mov     ebx, eax
    push    dword ptr [ebp-24]
    call    bm_cum
    add     esp, 4
    sub     ebx, eax
    jle     ax_y_next
    mov     edi, [ebp+0x18]
    add     edi, [ebp-20]
    mov     eax, [ebp-24]
ax_fill:
    cmp     dword ptr [ebp-20], 255
    jg      ax_fail
    mov     [edi], al
    inc     edi
    inc     dword ptr [ebp-20]
    dec     ebx
    jnz     ax_fill
ax_y_next:
    inc     dword ptr [ebp-24]
    jmp     ax_y_loop

ax_build_out:
    mov     edi, [ebp+0x1c]
    mov     esi, [ebp+0x18]
    xor     ebx, ebx
ax_near:
    cmp     ebx, [ebp-4]
    jge     ax_mid_init
    movzx   eax, byte ptr [esi+ebx]
    mov     [edi+ebx*2], ax
    inc     ebx
    jmp     ax_near

ax_mid_init:
    /* s = (B*srcN)/dstN ; acc = (B*srcN) % dstN */
    mov     eax, [ebp-4]
    imul    eax, [ebp+0x10]
    xor     edx, edx
    div     dword ptr [ebp+0xc]
    mov     [ebp-32], eax
    mov     [ebp-28], edx

ax_mid:
    mov     eax, [ebp+0xc]
    sub     eax, [ebp-4]
    cmp     ebx, eax
    jge     ax_far
    mov     eax, [ebp-32]
    cmp     eax, [ebp+8]
    jge     ax_hi
    mov     eax, [ebp+8]
ax_hi:
    mov     ecx, [ebp+0x10]
    dec     ecx
    sub     ecx, [ebp+8]
    cmp     eax, ecx
    jle     ax_store_mid
    mov     eax, ecx
ax_store_mid:
    mov     [edi+ebx*2], ax
    mov     eax, [ebp-28]
    add     eax, [ebp+0x10]
ax_carry:
    cmp     eax, [ebp+0xc]
    jl      ax_carry_done
    sub     eax, [ebp+0xc]
    inc     dword ptr [ebp-32]
    jmp     ax_carry
ax_carry_done:
    mov     [ebp-28], eax
    inc     ebx
    jmp     ax_mid

ax_far:
    cmp     ebx, [ebp+0xc]
    jge     ax_ok
    mov     eax, [ebp+0xc]
    dec     eax
    sub     eax, ebx
    movzx   ecx, byte ptr [esi+eax]
    mov     eax, [ebp+0x10]
    dec     eax
    sub     eax, ecx
    mov     [edi+ebx*2], ax
    inc     ebx
    jmp     ax_far

ax_ok:
    mov     edx, [ebp-4]
    mov     eax, 1
    jmp     ax_ret
ax_fail:
    xor     eax, eax
    xor     edx, edx
ax_ret:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret

/* ============================ bm_cum ============================
   cdecl(y) -> eax = cum(y), reading bm_axis's frame through the saved-ebp chain
   ([ebp] == bm_axis's ebp).  mode 0: halfDown(y*dstN, srcN)
                              mode 1: y<=2 -> y*K ; else 2K + halfDown((y-2)*rem, m) */
bm_cum:
    push    ebp
    mov     ebp, esp
    push    ebx
    push    ecx
    push    edx
    mov     ebx, [ebp]
    mov     eax, [ebp+8]
    cmp     dword ptr [ebx-8], 0
    jne     cum_pinned
    imul    eax, [ebx+0xc]
    add     eax, eax
    add     eax, [ebx+0x10]
    dec     eax
    xor     edx, edx
    mov     ecx, [ebx+0x10]
    add     ecx, ecx
    div     ecx
    jmp     cum_ret
cum_pinned:
    cmp     eax, 2
    jg      cum_tail
    imul    eax, [ebx+0x14]
    jmp     cum_ret
cum_tail:
    sub     eax, 2
    imul    eax, [ebx-12]
    add     eax, eax
    add     eax, [ebx-16]
    dec     eax
    xor     edx, edx
    mov     ecx, [ebx-16]
    add     ecx, ecx
    div     ecx
    mov     ecx, [ebx+0x14]
    add     ecx, ecx
    add     eax, ecx
cum_ret:
    pop     edx
    pop     ecx
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret
""")


def build() -> dict:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    out = {}
    for name, off, asm in THUNKS:
        va = PCAVE2 + off
        enc, _ = ks.asm(asm, va)
        out[name] = (off, va, bytes(enc))
    return out


def main() -> None:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for name, (off, va, data) in build().items():
        print(f"\n===== {name} @ pcave2+0x{off:X} (VA 0x{va:X})  {len(data)} bytes =====")
        hexs = " ".join(f"{b:02X}" for b in data)
        for val, ph in SENT.items():
            le = " ".join(f"{b:02X}" for b in val.to_bytes(4, "little"))
            hexs = hexs.replace(le, ph)
        print(hexs)
        print(f"--- first insns ---")
        for i in list(md.disasm(data, va))[:6]:
            print(f"  {i.address:08x} {i.mnemonic:8} {i.op_str}")


if __name__ == "__main__":
    main()
