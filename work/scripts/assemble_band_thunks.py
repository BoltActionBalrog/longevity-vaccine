"""Assemble the hud_turn_band thunks (TURN COMPLETE banner scaling, S v4 bake).

Mechanism (prototype hook_hudframes44.js S v4, USER-CONFIRMED 4K 2026-07-06 "It's perfect"):
turn.flc decodes in KEYED mode (flags bit1) — pixel chunk handlers write the flic dst
[+0x5A8] DIRECTLY at dstX/dstY (+0x5AC/+0x5B0), native 233x23; the canvas (+4) holds only
the Flic_init background patch (key-pixel substitution source). Bake = dst-bounce:

thunk_band_draw (call-redirect @0x45C499 anim + @0x45C4C7 static, the only two sites that
draw the turn flic; draw_frame_once 0x62A120 has ZERO static callers):
  g<=16 -> tail native Flic_draw_frame. Else: lazily create g_band_scratch (crt_malloc
  0x588 + Buffer_ctor + Buffer_resize(w,h); scratch PERSISTS = the band's native
  framebuffer, SS2 deltas accumulate). NO initial seed needed: keyed BRUN writes EVERY
  pixel (key pixels substitute CANVAS bg, never the dst's prior content), and the
  state-change static draw (rewind + frame-0 BRUN) always precedes any delta sequence.
  Bounce [+0x5A8]->scratch, call draw_frame(flic,0,0); restore dst + stored x/y; set the
  dirty rect (+0x58C..+0x598) to the scaled rect; ONE Buffer_copy_3 NN stretch
  scratch(0,0,w,h) -> dst(x,y,w*g/16,h*g/16). Unconditional stretch is the correct mirror
  in keyed mode: every keyed handler writes the full dst area.

thunk_band_recapture (call-redirect @0x62A046, Flic_init's bg capture copy_4, SHARED by
all flics): forward the native capture; iff dst==0x7D2D74 (turn canvas) && g>16, redo the
canvas as a copy_3 SHRINK of the FULL scaled band rect (the 1:1 grab holds a wrong-content
native-size crop of the scaled area). The strip backdrop is itself native art x g/16, so
shrink + final stretch round-trips ~losslessly.

Emits keystone-baked concrete hex (all callee VAs fixed) + asserts slot budgets.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
DRAW_OFF, DRAW_BUDGET = 0x4E80, 0x104
RECAP_OFF, RECAP_BUDGET = 0x4F84, 0x70
SCRATCH_OFF = 0x4FF4          # g_band_scratch dword (zero-init by section)

S = {
    "thunk_ensure_scale":  0x668760,   # menu_strip_thunks+0x560, preserves ecx
    "g_popup_scale_num":   0x668740,   # menu_strip_thunks+0x540
    "crt_malloc":          0x64558A,
    "Buffer_ctor":         0x5D7210,
    "Buffer_resize":       0x5D79C0,   # thiscall(this; w,h) RET 8
    "Buffer_copy_3":       0x5D9610,   # thiscall(src; dst,sx,sy,sw,sh,dx,dy,dw,dh) callee-cleans
    "Buffer_copy_4":       0x5DFF00,   # thiscall(src; dst,sx,sy,dx,dy,w,h) RET 0x1C
    "Flic_draw_frame":     0x62A070,   # thiscall(flic; x,y) RET 8
    "TURN_CANVAS":         0x7D2D74,   # turn flic + 4 (static object)
    "g_band_scratch":      PCAVE2_VA + SCRATCH_OFF,
    # v2 (2026-07-06): DRAW's stretch call retargeted to the copy_3-drop-in remap wrapper
    # (assemble_band_restripe.py) — de-bands the banner's 1px dither at fractional g.
    # RECAP keeps the direct Buffer_copy_3 (shrink path, nothing to re-stripe).
    "thunk_band_stretch_remap": PCAVE2_VA + 0x5AB0,
}

DRAW = f"""
    push ebp
    mov ebp, esp
    push ebx
    push esi
    push edi
    mov esi, ecx
    call {S['thunk_ensure_scale']:#x}
    mov eax, dword ptr [{S['g_popup_scale_num']:#x}]
    cmp eax, 16
    jle native
    mov edi, dword ptr [{S['g_band_scratch']:#x}]
    test edi, edi
    jnz have
    push 0x588
    call {S['crt_malloc']:#x}
    add esp, 4
    test eax, eax
    je native
    mov edi, eax
    mov ecx, edi
    call {S['Buffer_ctor']:#x}
    mov eax, dword ptr [esi+0x59C]
    mov edx, dword ptr [esi+0x5A0]
    push edx
    push eax
    mov ecx, edi
    call {S['Buffer_resize']:#x}
    mov dword ptr [{S['g_band_scratch']:#x}], edi
have:
    mov ebx, dword ptr [esi+0x5A8]
    mov dword ptr [esi+0x5A8], edi
    push 0
    push 0
    mov ecx, esi
    call {S['Flic_draw_frame']:#x}
    mov dword ptr [esi+0x5A8], ebx
    mov eax, dword ptr [ebp+8]
    mov dword ptr [esi+0x5AC], eax
    mov eax, dword ptr [ebp+12]
    mov dword ptr [esi+0x5B0], eax
    mov ecx, dword ptr [{S['g_popup_scale_num']:#x}]
    mov eax, dword ptr [esi+0x59C]
    imul eax, ecx
    sar eax, 4
    mov edx, dword ptr [esi+0x5A0]
    imul edx, ecx
    sar edx, 4
    mov ecx, dword ptr [ebp+8]
    mov dword ptr [esi+0x58C], ecx
    add ecx, eax
    mov dword ptr [esi+0x594], ecx
    mov ecx, dword ptr [ebp+12]
    mov dword ptr [esi+0x590], ecx
    add ecx, edx
    mov dword ptr [esi+0x598], ecx
    push edx
    push eax
    push dword ptr [ebp+12]
    push dword ptr [ebp+8]
    push dword ptr [esi+0x5A0]
    push dword ptr [esi+0x59C]
    push 0
    push 0
    push ebx
    mov ecx, edi
    call {S['thunk_band_stretch_remap']:#x}
    xor eax, eax
    pop edi
    pop esi
    pop ebx
    pop ebp
    ret 8
native:
    mov ecx, esi
    pop edi
    pop esi
    pop ebx
    pop ebp
    push {S['Flic_draw_frame']:#x}
    ret
"""

RECAP = f"""
    push ebp
    mov ebp, esp
    push esi
    mov esi, ecx
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push dword ptr [ebp+0x18]
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0x0C]
    push dword ptr [ebp+0x08]
    mov ecx, esi
    call {S['Buffer_copy_4']:#x}
    cmp dword ptr [ebp+8], {S['TURN_CANVAS']:#x}
    jne done
    call {S['thunk_ensure_scale']:#x}
    mov eax, dword ptr [{S['g_popup_scale_num']:#x}]
    cmp eax, 16
    jle done
    mov ecx, eax
    mov eax, dword ptr [ebp+0x1C]
    imul eax, ecx
    sar eax, 4
    mov edx, dword ptr [ebp+0x20]
    imul edx, ecx
    sar edx, 4
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push 0
    push 0
    push edx
    push eax
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0x0C]
    push dword ptr [ebp+8]
    mov ecx, esi
    call {S['Buffer_copy_3']:#x}
done:
    pop esi
    pop ebp
    ret 0x1C
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)

def asm(name, code, va, budget):
    enc, _ = ks.asm(code, va)
    b = bytes(enc)
    print(f"{name} @ {va:#x}: {len(b)} bytes (budget {budget:#x}={budget})")
    assert len(b) <= budget, f"{name} over budget!"
    print("  " + " ".join(f"{x:02X}" for x in b))
    return b

draw = asm("thunk_band_draw", DRAW, PCAVE2_VA + DRAW_OFF, DRAW_BUDGET)
recap = asm("thunk_band_recapture", RECAP, PCAVE2_VA + RECAP_OFF, RECAP_BUDGET)
print(f"\ncave tail after: {RECAP_OFF + len(recap):#x} (g_band_scratch @ {SCRATCH_OFF:#x}, section end 0x5000)")
