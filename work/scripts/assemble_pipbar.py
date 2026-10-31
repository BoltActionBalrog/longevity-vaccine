#!/usr/bin/env python
"""Assembler for group basewin_pipbar (2026-09-21): the base screen's NUTRIENTS / MINERALS / ENERGY intake bars.

Law: scaling_laws.pipbar_pip (one device pitch per bar, capped to the bar's native span; pip k at pt(x0) + k*P).
All 18 sites sit in BaseWin_draw_expenses (0x412AA0, ebp-framed): pip pitch = esi at every call, bar start x0 =
[ebp-0x20].

  thunk_bw_pipx     CALL helper: eax = native pip x, edx = native pip width, esi = pitch, ebp = the painter's frame
                    -> eax = x', edx = W'.  Off the bar's native grid (or pitch < 2) = the plain edge law.
                    Preserves ecx/ebx/esi/edi/ebp.
  thunk_bw_piptile  12 Buffer_tile_2 sites (was thunk_bw_tile2): x, W and the src phase x from the helper; y, H and
                    the phase y keep thunk_bw_tile2's edge law.
  thunk_bw_pipfill  6 GraphicWin_fill_2 sites (was thunk_bw_fill2): L/R from the helper, T/B = basewin_pt.
Native no-op at g <= 16 (the canvas gate).  Parity: tests\\test_pipbar_asm_parity.py.
"""
from __future__ import annotations

import contextlib
import io
import sys

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_council as AC

PCAVE2 = AC.PCAVE2
G = AC.G
CANVAS = 0x6A7A6C
CANVAS_W = CANVAS + 0x80
W_NATIVE = 758
BASEWIN_G = 0x6A7628
FILL_2 = 0x5D5350
TILE_2 = 0x5DA9F0
T_SB_TILE2 = 0xA0C000 + 0x27D00     # t_sb_tile2 (assemble_stripes_base.py): Buffer_tile_2 drop-in, cell dither -> the stripe law; g <= 16 -> Buffer_tile_2
G_BW_RECT = PCAVE2 + 0xB6D0
SPAN = 0xC2
OFF_PIPX, OFF_PIPTILE, OFF_PIPFILL, SLOT_END = 0x1CD30, 0x1CE50, 0x1CEC0, 0x1CF40
PIPX = PCAVE2 + OFF_PIPX
OFF_G_PIP_TOP = 0x1CF40
G_PIP_TOP = PCAVE2 + OFF_G_PIP_TOP           # 4B: device start of the last bar (the three bars share one)
TILE_SITES = [0x4132EB, 0x413390, 0x4133E7, 0x41342C, 0x413B83, 0x413C28, 0x413C8E, 0x413CD3,
              0x41444E, 0x4144E2, 0x4145B0, 0x4145F5]
FILL_SITES = [0x413330, 0x41346B, 0x413BC8, 0x413D12, 0x414490, 0x414512]


def asm_pipx() -> str:
    return f"""
    push    ebx
    push    edi
    push    ecx
    mov     ebx, eax                    ; x
    mov     ecx, edx                    ; width
    cmp     esi, 2
    jl      plain
    mov     eax, ebx
    sub     eax, dword ptr [ebp-0x20]
    js      plain
    cdq
    idiv    esi                         ; eax = k, edx = remainder
    test    edx, edx
    jne     plain
    mov     edi, eax                    ; k
    mov     eax, {SPAN}
    cdq
    idiv    esi
    inc     eax                         ; n
    cmp     edi, eax
    jg      plain
    push    edi                         ; [esp+4] k (after the next push)
    push    eax                         ; [esp]   n
    imul    eax, esi
    add     eax, dword ptr [ebp-0x20]
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     edi, dword ptr [ebp-0x20]
    imul    edi, dword ptr [{G:#x}]
    sar     edi, 4                      ; top = pt(x0)
    sub     eax, edi                    ; span
    cdq
    idiv    dword ptr [esp]             ; span // n
    mov     edx, esi
    imul    edx, dword ptr [{G:#x}]
    lea     edx, [edx*2+15]
    sar     edx, 5                      ; half_down(p*g, 16)
    cmp     eax, edx
    jle     p_min
    mov     eax, edx
p_min:
    cmp     eax, 1
    jge     p_ok
    mov     eax, 1
p_ok:
    mov     ecx, eax                    ; P
    push    eax
    mov     eax, dword ptr [{G_PIP_TOP:#x}]
    sub     eax, edi
    cdq
    xor     eax, edx
    sub     eax, edx                    ; |prev_top - top|
    mov     edx, dword ptr [{G:#x}]
    sar     edx, 4
    add     edx, 2                      ; pipbar_snap(g)
    cmp     eax, edx
    jg      newtop
    mov     edi, dword ptr [{G_PIP_TOP:#x}]
newtop:
    mov     dword ptr [{G_PIP_TOP:#x}], edi
    pop     eax
    imul    eax, dword ptr [esp+4]
    add     eax, edi                    ; x' = top + k*P
    add     esp, 8
    mov     ebx, eax
    mov     eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5                      ; K
    mov     edx, ecx
    sub     edx, eax
    lea     eax, [ecx+1]
    sar     eax, 1
    cmp     edx, eax
    jge     c_half
    mov     edx, eax
c_half:
    cmp     edx, ecx
    jl      c_ok
    lea     edx, [ecx-1]
    cmp     edx, 1
    jge     c_ok
    mov     edx, 1
c_ok:
    mov     eax, ebx
    jmp     done
plain:
    mov     eax, ebx
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     edx, ebx
    add     edx, ecx
    imul    edx, dword ptr [{G:#x}]
    sar     edx, 4
    sub     edx, eax
done:
    pop     ecx
    pop     edi
    pop     ebx
    ret
"""


def asm_piptile() -> str:
    # Buffer_tile_2 (src, a3, a4, x, y, W, H): [esp+4] src +8 a3 +C a4 +10 x +14 y +18 W +1C H ; ecx = dest
    return f"""
    cmp     ecx, {CANVAS:#x}
    jne     native
    cmp     dword ptr [{CANVAS_W:#x}], {W_NATIVE}
    jle     native
    mov     eax, dword ptr [esp+0x10]
    mov     edx, dword ptr [esp+0x18]
    call    {PIPX:#x}
    mov     dword ptr [esp+0x10], eax
    mov     dword ptr [esp+8], eax
    mov     dword ptr [esp+0x18], edx
    mov     eax, dword ptr [esp+0x14]
    mov     edx, dword ptr [esp+0x1C]
    add     edx, eax
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    imul    edx, dword ptr [{G:#x}]
    sar     edx, 4
    sub     edx, eax
    mov     dword ptr [esp+0x14], eax
    mov     dword ptr [esp+0xC], eax
    mov     dword ptr [esp+0x1C], edx
native:
    push    {T_SB_TILE2:#x}
    ret
"""


def asm_pipfill() -> str:
    return f"""
    cmp     ecx, {BASEWIN_G:#x}
    jne     native
    cmp     dword ptr [{CANVAS_W:#x}], {W_NATIVE}
    jle     native
    push    ebx
    mov     ebx, dword ptr [esp+8]      ; rect*
    mov     eax, dword ptr [ebx]
    mov     edx, dword ptr [ebx+8]
    sub     edx, eax
    call    {PIPX:#x}
    mov     dword ptr [{G_BW_RECT:#x}], eax
    add     eax, edx
    mov     dword ptr [{G_BW_RECT + 8:#x}], eax
    mov     eax, dword ptr [ebx+4]
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     dword ptr [{G_BW_RECT + 4:#x}], eax
    mov     eax, dword ptr [ebx+0xC]
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     dword ptr [{G_BW_RECT + 0xC:#x}], eax
    pop     ebx
    mov     dword ptr [esp+4], {G_BW_RECT:#x}
native:
    push    {FILL_2:#x}
    ret
"""


THUNKS = [("thunk_bw_pipx", OFF_PIPX, asm_pipx, OFF_PIPTILE),
          ("thunk_bw_piptile", OFF_PIPTILE, asm_piptile, OFF_PIPFILL),
          ("thunk_bw_pipfill", OFF_PIPFILL, asm_pipfill, SLOT_END)]
SYMS = {G: "g_popup_scale_num", PIPX: "thunk_bw_pipx", G_BW_RECT: "g_bw_rect", G_PIP_TOP: "g_bw_pip_top"}


def assemble_all() -> dict[str, tuple[int, bytes]]:
    out = {}
    for name, off, fn, end in THUNKS:
        b = AC.assemble(fn(), PCAVE2 + off)
        assert off + len(b) <= end, (name, hex(off + len(b)), hex(end))
        out[name] = (off, b)
    return out


def main() -> int:
    lay = assemble_all()
    print(f"  {'g_bw_pip_top:':<31}{{ cave: pcave2, offset: {OFF_G_PIP_TOP:#x}, size: 4 }}   # basewin_pipbar")
    for name, (off, b) in lay.items():
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # basewin_pipbar ({len(b)}B)")
    for name, (off, b) in lay.items():
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{AC.templatize(b, PCAVE2 + off, SYMS)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
