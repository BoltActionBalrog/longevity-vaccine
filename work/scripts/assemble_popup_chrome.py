#!/usr/bin/env python
# Keystone assembler for group popup_chrome_rails + popup_chrome_insets
# (in-game popup side-rail scaling + chrome inset scaling, the Quit-modal fix).
#
# WHAT / WHY (prototype hook_margin_reserve.js, user-confirmed all-res 2026-07-03):
#   * RAILS: the in-game popup window slides in via the generic slide_show/slide_hide
#     (0x45D440/0x45D970) whose 4 fixed 15/8x529 rail strips are drawn 1/1 -- the
#     g/16-scaled popup outgrows the art exactly like the file dialog did (P1).
#     The baked filedlg thunks (railscale settled sites + railslide animation sites)
#     are identity-gated on g_filedlg_active && g_fd_winbuf; the popup fix ARMS that
#     same gate around the popup's OWN slide calls (Popup_show 0x4049D3 /
#     Popup_hide 0x404AED -- popup-specific call sites, other slide windows native).
#   * INSETS: Popup_on_draw_background (0x405c80) composes the d690 backdrop +
#     title band + text-field frame from the window rect with NATIVE deltas for
#     in-game type-0/5 popups (d690 L+=0x17=rail width, R-=0x37=rail+32 gap, B+=5;
#     band L+=0x1a(+1), R-=0x3a(-1); field R-10+3, L/T pads -3, nested d5a0 +-3).
#     With scaled rails the chrome must abut them: scale every delta x g/16, the
#     rail-facing edges with railscale's IDENTICAL double-floor cascade
#     (L = (15g>>4)+(8g>>4), R = floor((floor(R*16/g)-55)*g/16)) so abutting
#     artifacts share ONE floor cascade. All thunks: g<=16 -> exact native deltas.
#
# Regenerate if any cave offset moves (offsets below are baked into rel32 math).

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PCAVE2 = 0xA0C000

# sentinels -> yaml placeholders
SENT = {
    0x71111111: "{abs32:g_popup_scale_num}",
    0x72222222: "{abs32:g_filedlg_active}",
    0x73333333: "{abs32:g_fd_winbuf}",
    0x74444444: "{abs32:g_popup_railsave}",
}
CALL_SENT = {
    0x75555555: "{rel32:slide_show}",
    0x76666666: "{rel32:slide_hide}",
}
# push-imm32 tail-jmp targets (E9 rel32 is unsupported by the yaml template engine)
SENT[0x75555555] = "{abs32:slide_show}"
SENT[0x76666666] = "{abs32:slide_hide}"

THUNKS = []


def thunk(name, offset, asm):
    THUNKS.append((name, offset, asm))


# ---- thunk_popup_railshow / railhide (arm the filedlg rail gate around the popup slide) ----
# Entry via E8 from the popup call site: [esp]=ret, [esp+4]=win, [esp+8]=arg2.
# g<=16 or filedlg already active -> plain tail-jmp (byte-identical native).
# Else: save g_fd_winbuf -> g_popup_railsave, point it at &win+0x444, set active,
# re-push both args, call the slide fn, cdecl-clean, disarm+restore, ret (site's
# own `add esp,8` still cleans its args). Single-threaded modal: non-reentrant.
def rail_asm(target):
    return f"""
    mov eax, [0x71111111]
    cmp eax, 0x10
    jle native
    cmp dword ptr [0x72222222], 0
    jne native
    mov eax, [esp+4]
    add eax, 0x444
    mov ecx, [0x73333333]
    mov [0x74444444], ecx
    mov [0x73333333], eax
    mov dword ptr [0x72222222], 1
    push dword ptr [esp+8]
    push dword ptr [esp+8]
    call {target}
    add esp, 8
    mov dword ptr [0x72222222], 0
    mov ecx, [0x74444444]
    mov [0x73333333], ecx
    ret
native:
    push {target}
    ret
"""


thunk("thunk_popup_railshow", 0x3550, rail_asm(0x75555555))
thunk("thunk_popup_railhide", 0x35C0, rail_asm(0x76666666))
# g_popup_railsave (4B data): pcave2 + 0x3630

# ---- thunk_popup_d690insets: replaces the 27B in-game d690 delta block @0x405F24 ----
# Rect in caller frame: [ebp-0x24]=L(0) [ebp-0x20]=T [ebp-0x1c]=R(=bufW) [ebp-0x18]=B.
# Preserves eax (popup type, live: cmp eax,6 @0x405f51). Scaled:
#   L += (15g>>4)+(8g>>4)  (rail pair device extent)
#   R  = floor((floor(R*16/g)-55)*g/16)   (railscale's double floor; R==bufW here)
#   B += (5g)>>4
# g=16 identities: 23 / R-55 / 5 == the native 0x17/0x37/5 -- but gate anyway (div safety).
thunk("thunk_popup_d690insets", 0x3640, """
    push eax
    push ecx
    push edx
    mov eax, [0x71111111]
    cmp eax, 0x10
    jg scaled
    add dword ptr [ebp-0x24], 0x17
    sub dword ptr [ebp-0x1c], 0x37
    add dword ptr [ebp-0x18], 5
    jmp done
scaled:
    mov ecx, eax
    imul ecx, ecx, 15
    shr ecx, 4
    mov edx, eax
    shl edx, 3
    shr edx, 4
    add ecx, edx
    add [ebp-0x24], ecx
    push eax
    mov eax, [ebp-0x1c]
    shl eax, 4
    xor edx, edx
    div dword ptr [esp]
    sub eax, 55
    mul dword ptr [esp]
    shr eax, 4
    mov [ebp-0x1c], eax
    pop ecx
    lea eax, [ecx+ecx*4]
    shr eax, 4
    add [ebp-0x18], eax
done:
    pop edx
    pop ecx
    pop eax
    ret
""")

# ---- thunk_popup_titleinsets: replaces the 18B in-game title-band delta block @0x405FF1 ----
# Band rect (fresh copy rebuilt @0x405f91): [ebp-0x14]=L(0) [ebp-0xc]=R(=bufW).
# Downstream (0x406027 inc edx / post-title_height dec) add +1 L / -1 R, so:
#   L += railLdev + (4g>>4) - 1    (final band L = frame L + floor(4g/16); native 0x1a)
#   R  = anchor - (4g>>4)          (final band R = anchor - 1 - floor(4g/16); native -0x3a)
# v2 (2026-10-22 fix 19, law scaling_laws.popup_title_band_right): the final band R mirrors L against the
# backdrop's DRAWN right edge, popup_backdrop_draw_right = anchor - 1 (thunk_backdrop_railtrim moves only the
# backdrop's draw copy), so the drawn L/R channels are both floor(4g/16) - K.  v1 kept `inc eax` (final R =
# anchor - floor(4g/16), the untrimmed rect): the right channel was one px short of the left at every g > 16
# (SELECT DESTINATION 8/7 @4K, 4/3 @1080p, 3/2 @1600x900).  The inc is now a nop, so every later byte stands.
# ebx (popup type) preserved.
thunk("thunk_popup_titleinsets", 0x36A0, """
    push eax
    push ecx
    push edx
    mov eax, [0x71111111]
    cmp eax, 0x10
    jg scaled
    add dword ptr [ebp-0x14], 0x1a
    sub dword ptr [ebp-0xc], 0x3a
    jmp done
scaled:
    mov ecx, eax
    imul ecx, ecx, 15
    shr ecx, 4
    mov edx, eax
    shl edx, 3
    shr edx, 4
    add ecx, edx
    mov edx, eax
    shr edx, 2
    add ecx, edx
    dec ecx
    add [ebp-0x14], ecx
    push eax
    mov eax, [ebp-0xc]
    shl eax, 4
    xor edx, edx
    div dword ptr [esp]
    sub eax, 55
    mul dword ptr [esp]
    shr eax, 4
    pop edx
    shr edx, 2
    sub eax, edx
    nop
    mov [ebp-0xc], eax
done:
    pop edx
    pop ecx
    pop eax
    ret
""")

# ---- thunk_popup_fieldR: replaces `lea ecx,[edx-0xa]; lea edx,[eax+ebx]` @0x406116 (6B) ----
# edx = scaled frame R ([ebp-0x1c], already anchor'd by d690insets); the text-field
# frame right edge = frame R - floor(10g/16) (+ floor(3g/16) later in fieldpads).
# eax=[esi+0x30d4] must survive for the displaced second lea.
thunk("thunk_popup_fieldR", 0x3700, """
    push eax
    mov eax, [0x71111111]
    cmp eax, 0x10
    jg scaled
    lea ecx, [edx-0xa]
    jmp done
scaled:
    lea ecx, [eax+eax*4]
    add ecx, ecx
    shr ecx, 4
    neg ecx
    add ecx, edx
done:
    pop eax
    lea edx, [eax+ebx]
    ret
""")

# ---- thunk_popup_fieldpads: replaces the 20B field-frame pad cluster @0x40612F ----
# p3 = floor(3g/16). [ebp-0x34]=edi-p3 (field L), ecx+=p3 -> [ebp-0x2c] (field R),
# [ebp-0x30]=ebx-p3 (field T). Ends with `test eax,eax` -- the je @0x406143 consumes
# these flags (ret preserves them).
thunk("thunk_popup_fieldpads", 0x3730, """
    push eax
    push edx
    mov eax, [0x71111111]
    cmp eax, 0x10
    jg scaled
    mov edx, 3
    jmp apply
scaled:
    lea edx, [eax+eax*2]
    shr edx, 4
apply:
    add ecx, edx
    mov eax, edi
    sub eax, edx
    mov [ebp-0x34], eax
    mov [ebp-0x2c], ecx
    mov eax, ebx
    sub eax, edx
    mov [ebp-0x30], eax
    pop edx
    pop eax
    test eax, eax
    ret
""")

# ---- thunk_popup_nestpads: replaces the 15B nested-d5a0 +-3 block @0x406211 ----
# The inner hairline nests p3 = floor(3g/16) inside the field rect (native 3).
# eax-=p3 (R), ecx+=p3 (L), [ebp-0x24]=eax, edx-=p3 (B), edi+=p3 (T).
thunk("thunk_popup_nestpads", 0x3770, """
    push ebx
    mov ebx, [0x71111111]
    cmp ebx, 0x10
    jg scaled
    mov ebx, 3
    jmp apply
scaled:
    lea ebx, [ebx+ebx*2]
    shr ebx, 4
apply:
    sub eax, ebx
    add ecx, ebx
    mov [ebp-0x24], eax
    sub edx, ebx
    add edi, ebx
    pop ebx
    ret
""")

ks = Ks(KS_ARCH_X86, KS_MODE_32)
cs = Cs(CS_ARCH_X86, CS_MODE_32)

for name, offset, asm in THUNKS:
    va = PCAVE2 + offset
    src = "\n".join(l.split(";")[0] for l in asm.splitlines())
    enc, _ = ks.asm(src, va)
    b = bytes(enc)
    # rebuild as yaml hex with placeholders, instruction by instruction
    parts = []
    for ins in cs.disasm(b, va):
        raw = ins.bytes
        hexs = " ".join(f"{x:02X}" for x in raw)
        if raw[0] == 0xE8 and len(raw) == 5:
            tgt = (ins.address + 5 + int.from_bytes(raw[1:], "little", signed=True)) & 0xFFFFFFFF
            if tgt in CALL_SENT:
                hexs = "E8 " + CALL_SENT[tgt]
        elif raw[0] == 0xE9 and len(raw) == 5:
            tgt = (ins.address + 5 + int.from_bytes(raw[1:], "little", signed=True)) & 0xFFFFFFFF
            if tgt in CALL_SENT:
                hexs = "E9 " + CALL_SENT[tgt]
        else:
            for sent, ph in SENT.items():
                sb = " ".join(f"{x:02X}" for x in sent.to_bytes(4, "little"))
                if sb in hexs:
                    hexs = hexs.replace(sb, ph)
        parts.append(hexs)
    yaml_bytes = " ".join(parts)
    print(f"==== {name} @ pcave2+0x{offset:X} (VA 0x{va:X}) len={len(b)} ends 0x{offset+len(b):X} ====")
    for ins in cs.disasm(b, va):
        print(f"  {ins.address:08X}  {ins.bytes.hex(' '):<26}  {ins.mnemonic} {ins.op_str}")
    print(f'  bytes: "{yaml_bytes}"')
    print()
