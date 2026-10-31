#!/usr/bin/env python
# Keystone assembler for the chrome-pipeline CLIP fix (2026-07-19):
# the ENERGY-band eraser (base screen). Laws: scaling_laws.blit_clip_visible /
# blit_clip_contains / remap_clip_bounds. Root cause (frida_basewin3..6.log):
# vanilla primitives write through the dest Buffer's active clip (+0x20..+0x2C);
# our thick-chrome enlarge pipeline bypassed it, so draw_expenses' backdrop
# [23,0,703,404] (clip = the expenses panel) repainted the WHOLE rect at 4K and
# erased the just-drawn energy block (ENERGY ALLOCATION header + ECONOMY row +
# LABS top edge = the user's "black box").
#
#   * thunk_frame_enlarge v2 -- RELOCATED 0x30A0 -> 0xBF80 (slot was capped at
#     192B by thunk@0x3160; all callers are {rel32:}/{abs32:} name refs).
#     v1 + DISARM GATE: after dstW/dstH are final (incl. exact-fill override),
#     if the dest clip does NOT contain [X,Y,X+W,Y+H], zero
#     g_band_nx/ny/g_bm_dstw/dsth so thunk_bandmap_blit falls back to
#     thunk_keyed_stretch_blit (raw band loops cannot clip; KSB's out-blit
#     can, see clipkey below). Popup family: clip == whole window -> gate
#     never fires -> behaviour identical.
#   * thunk_draw2_clipkey @ 0xC0A0 -- retarget of KSB's final Buffer_draw_2
#     out-call (menu_strip cave offset 0x4B9, VA 0x6686B9). Same __thiscall
#     contract (ecx=srcBuf; dest,key,X,Y,num,den; RET 0x18). num!=den or
#     clip-contains -> tail-jmp native Buffer_draw_2 (bit-identical). Empty
#     intersection -> no-op. Else keyed per-row copy of ONLY the visible span.
#
# fe_pair_remap v5 (walk bounds ∩ clip) lives in assemble_devfill_stripes.py.
# Regenerate if any referenced cave offset moves.
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PCAVE2 = 0xA0C000

SENT = {
    0x74444444: "{abs32:Buffer_draw_2}",
    0x7D111111: "{abs32:g_fc_exact}",
    0x7D222222: "{abs32:g_faction_scratch_rect}",
    0x7D333333: "{abs32:g_fe_w}",
    0x7D444444: "{abs32:g_fe_h}",
    0x7D555555: "{abs32:g_fe_src}",
    0x7D666666: "{abs32:g_fe_dst}",
    0x7D777777: "{abs32:g_fe_x}",
    0x7D888888: "{abs32:g_fe_y}",
    0x7D999999: "{abs32:g_fd_bilinear}",
    0x7DAAAAAA: "{abs32:g_band_nx}",
    0x7DBBBBBB: "{abs32:g_band_ny}",
    0x7DCCCCCC: "{abs32:g_bm_dstw}",
    0x7DDDDDDD: "{abs32:g_bm_dsth}",
}
CALL_SENT = {
    0x74111111: "{rel32:thunk_bilinear_blit}",
    0x74222222: "{rel32:thunk_bandmap_blit}",
    0x74333333: "{rel32:thunk_fe_pair_remap}",
}

THUNKS = []
def thunk(name, offset, asm):
    THUNKS.append((name, offset, asm))

# ===================== thunk_frame_enlarge v2 @ 0xBF80 =====================
# thiscall(ecx=src small buf)(dest,key,X,Y,num,den) RET 0x18.
# v1 semantics preserved 1:1; the only new block is the disarm gate.
thunk("thunk_frame_enlarge", 0xBF80, """
    push    ebp
    mov     ebp, esp
    push    esi
    push    edi
    push    ebx
    mov     esi, ecx
    mov     eax, [esi+0x84]
    neg     eax
    mov     edi, eax
    mov     eax, [esi+0x80]
    imul    dword ptr [ebp+0x18]
    idiv    dword ptr [ebp+0x1C]
    mov     ebx, eax
    mov     eax, edi
    imul    dword ptr [ebp+0x18]
    idiv    dword ptr [ebp+0x1C]
    cmp     dword ptr [0x7D111111], 0
    je      no_exact
    mov     edx, 0x7D222222
    mov     ebx, [edx+8]
    sub     ebx, [edx]
    mov     eax, [edx+0xC]
    sub     eax, [edx+4]
    mov     dword ptr [0x7D111111], 0
no_exact:
    mov     [0x7D333333], ebx
    mov     [0x7D444444], eax
    mov     [0x7D555555], esi
    push    eax
    mov     eax, [ebp+8]
    mov     [0x7D666666], eax
    mov     eax, [ebp+0x10]
    mov     [0x7D777777], eax
    mov     eax, [ebp+0x14]
    mov     [0x7D888888], eax
    pop     eax
    mov     edx, [ebp+8]
    mov     ecx, [ebp+0x10]
    cmp     ecx, [edx+0x20]
    jl      disarm
    add     ecx, ebx
    cmp     ecx, [edx+0x28]
    jg      disarm
    mov     ecx, [ebp+0x14]
    cmp     ecx, [edx+0x24]
    jl      disarm
    add     ecx, eax
    cmp     ecx, [edx+0x2C]
    jg      disarm
    jmp     armed
disarm:
    xor     ecx, ecx
    mov     [0x7DAAAAAA], ecx
    mov     [0x7DBBBBBB], ecx
    mov     [0x7DCCCCCC], ecx
    mov     [0x7DDDDDDD], ecx
armed:
    push    dword ptr [ebp+0xC]
    push    eax
    push    ebx
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x10]
    push    edi
    push    dword ptr [esi+0x80]
    push    0
    push    0
    push    dword ptr [ebp+8]
    push    esi
    cmp     dword ptr [0x7D999999], 0
    je      nn_path
    mov     dword ptr [0x7D999999], 0
    call    0x74111111
    jmp     epilogue
nn_path:
    call    0x74222222
    call    0x74333333
epilogue:
    pop     ebx
    pop     edi
    pop     esi
    pop     ebp
    ret     0x18
""")

# ===================== thunk_draw2_clipkey @ 0xC0A0 =====================
# thiscall(ecx=srcBuf scratch)(dest,key,X,Y,num,den) RET 0x18.
# Buffer fields: data +0x54, clip L/T/R/B +0x20/24/28/2C, w +0x80,
# h +0x84 (NEGATIVE), stride +0x4A8.
thunk("thunk_draw2_clipkey", 0xC0A0, """
    mov     eax, [esp+0x14]
    cmp     eax, [esp+0x18]
    je      one2one
passthru0:
    push    0x74444444
    ret
one2one:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x20
    push    ebx
    push    esi
    push    edi
    mov     [ebp-4], ecx
    mov     ebx, [ebp+8]
    mov     eax, [ebp+0x10]
    mov     edx, [ebx+0x20]
    cmp     eax, edx
    jge     vx0_ok
    mov     eax, edx
vx0_ok:
    mov     [ebp-8], eax
    mov     eax, [ebp+0x10]
    add     eax, [ecx+0x80]
    mov     edx, [ebx+0x28]
    cmp     eax, edx
    jle     vx1_ok
    mov     eax, edx
vx1_ok:
    mov     [ebp-0xC], eax
    mov     eax, [ebp+0x14]
    mov     edx, [ebx+0x24]
    cmp     eax, edx
    jge     vy0_ok
    mov     eax, edx
vy0_ok:
    mov     [ebp-0x10], eax
    mov     eax, [ecx+0x84]
    neg     eax
    add     eax, [ebp+0x14]
    mov     edx, [ebx+0x2C]
    cmp     eax, edx
    jle     vy1_ok
    mov     eax, edx
vy1_ok:
    mov     [ebp-0x14], eax
    mov     eax, [ebp-8]
    cmp     eax, [ebp+0x10]
    jne     clipped
    mov     eax, [ebp-0x10]
    cmp     eax, [ebp+0x14]
    jne     clipped
    mov     eax, [ebp+0x10]
    add     eax, [ecx+0x80]
    cmp     eax, [ebp-0xC]
    jne     clipped
    mov     eax, [ecx+0x84]
    neg     eax
    add     eax, [ebp+0x14]
    cmp     eax, [ebp-0x14]
    jne     clipped
    mov     ecx, [ebp-4]
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    jmp     passthru0
clipped:
    mov     eax, [ebp-0xC]
    sub     eax, [ebp-8]
    jle     done
    mov     [ebp-0x18], eax
    mov     eax, [ebp-0x14]
    sub     eax, [ebp-0x10]
    jle     done
    mov     [ebp-0x1C], eax
    mov     ecx, [ebp-4]
    mov     eax, [ebp-0x10]
    sub     eax, [ebp+0x14]
    imul    eax, [ecx+0x4A8]
    add     eax, [ecx+0x54]
    add     eax, [ebp-8]
    sub     eax, [ebp+0x10]
    mov     esi, eax
    mov     eax, [ebp-0x10]
    imul    eax, [ebx+0x4A8]
    add     eax, [ebx+0x54]
    add     eax, [ebp-8]
    mov     edi, eax
    mov     edx, [ebp+0xC]
row_loop:
    push    esi
    push    edi
    mov     ecx, [ebp-0x18]
pix_loop:
    mov     al, [esi]
    cmp     al, dl
    je      no_write
    mov     [edi], al
no_write:
    inc     esi
    inc     edi
    dec     ecx
    jnz     pix_loop
    pop     edi
    pop     esi
    mov     ecx, [ebp-4]
    add     esi, [ecx+0x4A8]
    mov     ecx, [ebp+8]
    add     edi, [ecx+0x4A8]
    dec     dword ptr [ebp-0x1C]
    jnz     row_loop
done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x18
""")

ks = Ks(KS_ARCH_X86, KS_MODE_32)
cs = Cs(CS_ARCH_X86, CS_MODE_32)

for name, offset, asm in THUNKS:
    va = PCAVE2 + offset
    src = "\n".join(l.split(";")[0] for l in asm.splitlines())
    enc, _ = ks.asm(src, va)
    b = bytes(enc)
    parts = []
    for ins in cs.disasm(b, va):
        raw = ins.bytes
        hexs = " ".join(f"{x:02X}" for x in raw)
        if raw[0] in (0xE8, 0xE9) and len(raw) == 5:
            tgt = (ins.address + 5 + int.from_bytes(raw[1:], "little", signed=True)) & 0xFFFFFFFF
            if tgt in CALL_SENT:
                hexs = f"{raw[0]:02X} " + CALL_SENT[tgt]
        else:
            for sent, ph in SENT.items():
                sb = " ".join(f"{x:02X}" for x in sent.to_bytes(4, "little"))
                if sb in hexs:
                    hexs = hexs.replace(sb, ph)
        parts.append(hexs)
    yaml_bytes = " ".join(parts)
    print(f"==== {name} @ pcave2+0x{offset:X} (VA 0x{va:X}) len={len(b)} ends 0x{offset+len(b):X} ====")
    print(f'  bytes: "{yaml_bytes}"')
    print()
