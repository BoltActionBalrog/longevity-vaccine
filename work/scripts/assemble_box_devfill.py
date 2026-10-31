# Assembles thunk_box_thick_devfill: DITHER-SAFE box-sprite thickener (reusable for any dithered
# modal bg). Drop-in for a Buffer_box_sprite call (ecx=dest,[esp+4]=&rect,[esp+8]=params; RET 8).
#
# Design (v2 -- center-overwrite). The 9-slice BORDER's look DEPENDS on the fill: each edge tiles
# params[8] as a mask alongside the bevel sprite, so a border-only render exposes the raw bevel
# highlight (renders WHITE). So we keep the proven full render for the border, then overwrite only
# the inset center with a clean device-res fill:
#   STEP1: thunk_box_thick_hollow_flat(dest, rect, params)  -- the a77a0495 path: thick bevel (correct,
#          fill-blended) + a StretchBlt-banded CENTER fill, keyed-9 composited into dest.
#   STEP2: Buffer_box_sprite(dest, INSET_rect, scratch[border=0]) -- tiles params[8] at DEVICE
#          resolution across rect inset by N = 6*g/16 (the scaled bevel thickness), overwriting the
#          banded center with a clean dither while leaving the thick bevel band untouched (N ~ bevel
#          so no banded ring, no bevel damage). Portrait/text draw later (BasePop_on_redraw) on top.
# All 9 slices are null-checked by Buffer_box_sprite, so border-zeroing in STEP2 is safe.
import keystone, capstone
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
SYM = dict(
    g_popup_scale_num            = 0x00668740,
    Buffer_box_sprite            = 0x005E2DD3,
    thunk_box_thick_hollow_flat  = PCAVE2 + 0x140,
    g_devfill_params             = PCAVE2 + 0xEC0,   # 40-byte (10-dword) params scratch
    g_devfill_rect               = PCAVE2 + 0xEF0,   # 16-byte inset RECT scratch
)
OFF  = 0xE00
BASE = PCAVE2 + OFF

asm = f"""
    cmp  dword ptr [{SYM['g_popup_scale_num']:#x}], 0x10
    jg   hires
    push {SYM['Buffer_box_sprite']:#x}
    ret
hires:
    push ebp
    mov  ebp, esp
    sub  esp, 0x10
    push ebx
    push esi
    push edi
    cld
    mov  [ebp-4], ecx                 ; dest
    mov  eax, [ebp+8]
    mov  [ebp-8], eax                 ; &rect
    mov  eax, [ebp+0xc]
    mov  [ebp-0xc], eax               ; params
    ; STEP1: proven full thick render (correct bevel + banded center fill)
    push dword ptr [ebp-0xc]
    push dword ptr [ebp-8]
    mov  ecx, [ebp-4]
    call {SYM['thunk_box_thick_hollow_flat']:#x}
    ; STEP2: clean device-res fill over the inset center
    ; N = ceil(g/16) = (g+15)>>4  -- the GREEN stroke width (~2px@g25, 3px@4K). The bevel's visible
    ; green is only ~1px native; the rest of the 6px edge is fill-MASK that must be clean dither, so we
    ; inset by just the green width and let STEP2's device-res fill cover the (formerly banded) fill-mask.
    mov  eax, [{SYM['g_popup_scale_num']:#x}]
    add  eax, 15
    shr  eax, 4
    mov  ebx, eax                     ; ebx = N (top/left inset)
    lea  edx, [ebx+1]                 ; edx = N+1 (right/bottom inset)
    ; build inset rect from [ebp-8]. Asymmetric: StretchBlt rounds the right/bottom strokes 1px
    ; toward the box edge, so a symmetric R-N/B-N clips their outer pixel. Inset right/bottom by N+1
    ; (clean fill stops 1px earlier) so STEP1's green stroke survives there; top/left use N.
    mov  edi, [ebp-8]
    mov  eax, [edi]
    add  eax, ebx
    mov  [{SYM['g_devfill_rect']:#x}], eax        ; L+N
    mov  eax, [edi+4]
    add  eax, ebx
    mov  [{SYM['g_devfill_rect']+4:#x}], eax      ; T+N
    mov  eax, [edi+8]
    sub  eax, edx
    mov  [{SYM['g_devfill_rect']+8:#x}], eax      ; R-(N+1)
    mov  eax, [edi+0xc]
    sub  eax, edx
    mov  [{SYM['g_devfill_rect']+0xc:#x}], eax    ; B-(N+1)
    ; scratch = params, border slices [0..7] zeroed
    mov  esi, [ebp-0xc]
    mov  edi, {SYM['g_devfill_params']:#x}
    mov  ecx, 10
    rep  movs dword ptr [edi], dword ptr [esi]
    mov  edi, {SYM['g_devfill_params']:#x}
    xor  eax, eax
    mov  ecx, 8
    rep  stosd
    ; Buffer_box_sprite(dest, &inset_rect, scratch)  -> device-res center fill
    push {SYM['g_devfill_params']:#x}
    push {SYM['g_devfill_rect']:#x}
    mov  ecx, [ebp-4]
    call {SYM['Buffer_box_sprite']:#x}
    pop  edi
    pop  esi
    pop  ebx
    mov  esp, ebp
    pop  ebp
    ret  8
"""

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
clean = "\n".join(l.split(";", 1)[0].rstrip() for l in asm.splitlines() if l.split(";", 1)[0].strip())
enc, _ = ks.asm(clean, BASE)
blob = bytes(enc)
print(f"thunk_box_thick_devfill: {len(blob)} bytes @ VA {BASE:#x} (off {OFF:#x}) -> ends {BASE+len(blob):#x} (off {OFF+len(blob):#x})")
print(f"  g_devfill_params @ off 0xEC0, g_devfill_rect @ off 0xEF0; body ends off {OFF+len(blob):#x} (must be <= 0xEC0): {OFF+len(blob) <= 0xEC0}")

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
bad = 0
print("  --- disasm ---")
for ins in md.disasm(blob, BASE):
    if ins.mnemonic in ("int3", "(bad)"):
        bad += 1
    print(f"   {ins.address:#08x}: {ins.bytes.hex():<16} {ins.mnemonic} {ins.op_str}")
tail = list(md.disasm(blob, BASE))[-1]
print(f"  last insn: {tail.mnemonic} {tail.op_str} (expect ret 8); bad={bad}")
assert bad == 0 and OFF + len(blob) <= 0xEC0
print("\n  patches.yaml bytes:")
print("    " + " ".join(f"{b:02X}" for b in blob))
