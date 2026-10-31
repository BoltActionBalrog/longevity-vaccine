"""t_pw_line -- the Go To / battle-plan map panel's dashed route line at vanilla x g/16 thickness (2026-10-12).

The panel (PlanWin 0x834D70) draws at device size (its canvas / save Buffer is the scaled 597x297 at 4K, trace
frida_planwin_terranx_PRACX_20261012T070954Z.log), but its route lines go through Buffer_line 0x5E09D0
(thiscall x1,y1,x2,y2, a5, colour, dash_on 4, dash_off 4, phase [0x939FD4]; RET 0x24) at 1 px with native dashes:
a hairline at 4K (user 2026-10-12).  This drop-in replaces PlanWin_overlay_draw's call 0x48B370 (also the line
timer's marching-dash redraw, 0x50EE80 -> 0x48AF30): K = stroke_width(g) copies offset along the minor axis (one at
K = 1), dash on / off / phase each scale_px at every g > 16 -- law scaling_laws.planwin_line_calls.
g <= 16: tail-jmp Buffer_line, stack untouched.
t_map_dash (2026-10-14) -- the main map's dashed order lines, MapWin_direct_dest_line 0x4672C0's non-overlay call
0x46741E: the caller already shifted slot 1 by (+1, +1) and slot 2 by (0, -1) (mode [ebp+0x18]); this adds K - 1 more
so each separation is K (law scaling_laws.map_dest_slot_shift), then tail-jmps t_pw_line.  ebp is the caller's
frame at the call; eax / edx / flags are dead there.

Usage: assemble_planwin_line.py      -> prints the yaml symbol + content lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
OFF, END = 0xF830, 0xF9A0           # cave_map: free between g_rwsb_sbw (ends 0xF824) and thunk_ol8_selbottom (old pf_frame_align slot)
MAP_DASH_OFF = 0xF920               # t_map_dash, after t_pw_line (ends 0xF91A) in the same slot
G = 0x00668740
BUFFER_LINE = 0x005E09D0
SITES = {"MapWin_direct_dest_line.dash_line": 0x0046741E}   # PlanWin 0x48B370 is the engine's again (planwin_native_render, 2026-10-15)
                                                            # sit in functions nothing calls (audit 2026-10-12)


def _hd(src_off: int, dst_off: int) -> str:
    """[ebp+dst] = scale_px([ebp+src]) = (2*v*g + 15) >> 5 (arithmetic)."""
    return f"""
    mov     eax, dword ptr [ebp+{src_off:#x}]
    imul    eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5
    mov     dword ptr [ebp+{dst_off:#x}], eax
"""


def asm_pw_line() -> str:
    # frame after 4 pushes + 0x10 locals, ebp = esp: [ebp] on', [+4] off', [+8] phase', [+0xC] x_major;
    # args a1..a9 at [ebp+0x24 + 4*(i-1)]: x1 0x24, y1 0x28, x2 0x2C, y2 0x30, a5 0x34, colour 0x38,
    # on 0x3C, off 0x40, phase 0x44.  esi = Buffer, edi = copies left, ebx = current minor offset.
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jle     native
    lea     eax, [eax*2+15]
    shr     eax, 5
    push    ebx
    push    esi
    push    edi
    push    ebp
    sub     esp, 0x10
    mov     ebp, esp
    mov     esi, ecx
    mov     edi, eax
    dec     eax
    shr     eax, 1
    neg     eax
    mov     ebx, eax
{_hd(0x3C, 0x0)}{_hd(0x40, 0x4)}{_hd(0x44, 0x8)}
    mov     eax, dword ptr [ebp+0x2C]
    sub     eax, dword ptr [ebp+0x24]
    cdq
    xor     eax, edx
    sub     eax, edx
    mov     ecx, dword ptr [ebp+0x30]
    sub     ecx, dword ptr [ebp+0x28]
    mov     edx, ecx
    sar     edx, 31
    xor     ecx, edx
    sub     ecx, edx
    xor     edx, edx
    cmp     eax, ecx
    setge   dl
    mov     dword ptr [ebp+0xC], edx
lp:
    push    dword ptr [ebp+0x8]
    push    dword ptr [ebp+0x4]
    push    dword ptr [ebp]
    push    dword ptr [ebp+0x38]
    push    dword ptr [ebp+0x34]
    cmp     dword ptr [ebp+0xC], 0
    je      xminor
    mov     eax, dword ptr [ebp+0x30]
    add     eax, ebx
    push    eax
    push    dword ptr [ebp+0x2C]
    mov     eax, dword ptr [ebp+0x28]
    add     eax, ebx
    push    eax
    push    dword ptr [ebp+0x24]
    jmp     drw
xminor:
    push    dword ptr [ebp+0x30]
    mov     eax, dword ptr [ebp+0x2C]
    add     eax, ebx
    push    eax
    push    dword ptr [ebp+0x28]
    mov     eax, dword ptr [ebp+0x24]
    add     eax, ebx
    push    eax
drw:
    mov     ecx, esi
    call    {BUFFER_LINE:#x}
    inc     ebx
    dec     edi
    jnz     lp
    add     esp, 0x10
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    ret     0x24
native:
    jmp     {BUFFER_LINE:#x}
"""


def asm_map_dash() -> str:
    # [esp] = return into 0x467423; args x1 [esp+4], y1 [esp+8], x2 [esp+0xC], y2 [esp+0x10]
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jle     go
    lea     eax, [eax*2+15]
    shr     eax, 5
    dec     eax
    jz      go
    mov     edx, dword ptr [ebp+0x18]
    cmp     edx, 1
    jne     m2
    add     dword ptr [esp+4], eax
    add     dword ptr [esp+8], eax
    add     dword ptr [esp+0xC], eax
    add     dword ptr [esp+0x10], eax
    jmp     go
m2:
    cmp     edx, 2
    jne     go
    sub     dword ptr [esp+8], eax
    sub     dword ptr [esp+0x10], eax
go:
    jmp     {PCAVE2 + OFF:#x}
"""


def build_map_dash() -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm_map_dash(), PCAVE2 + MAP_DASH_OFF)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, PCAVE2 + MAP_DASH_OFF)) == len(b)
    assert OFF + len(build()) <= MAP_DASH_OFF and MAP_DASH_OFF + len(b) <= END, "t_map_dash overflows its slot"
    return b


def build() -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm_pw_line(), PCAVE2 + OFF)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, PCAVE2 + OFF)) == len(b)
    assert OFF + len(b) <= END, f"t_pw_line {len(b)}B overflows its slot"
    return b


def main() -> int:
    b = build()
    tpl = " ".join(f"{x:02X}" for x in b).replace("40 87 66 00", "{abs32:g_popup_scale_num}")
    print(f"  t_pw_line:                     {{ cave: pcave2, offset: {OFF:#x} }}   # {len(b)}B")
    print(f"      - id: t_pw_line\n        offset: {OFF:#x}\n        bytes: \"{tpl}\"")
    m = build_map_dash()
    hx = " ".join(f"{x:02X}" for x in m).replace("40 87 66 00", "{abs32:g_popup_scale_num}")
    print(f"  t_map_dash:                    {{ cave: pcave2, offset: {MAP_DASH_OFF:#x} }}   # {len(m)}B")
    print(f"      - id: t_map_dash\n        offset: {MAP_DASH_OFF:#x}\n        bytes: \"{hx}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
