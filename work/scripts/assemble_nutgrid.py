#!/usr/bin/env python
"""Assembler for group basewin_nutgrid (2026-09-21): the base screen's NUTRIENTS storage grid with sub-8-px rows.

Law: scaling_laws.nutgrid_layout / nutgrid_row_rect (one device pitch for every row, grid re-centred in the box).
The three sites sit inside BaseWin_draw_nutrients' cell loop (ebp-framed): pitch [ebp-0x28], rows [ebp-0x2c],
row index [ebp-0x44], grid area top/bottom [ebp-0x50]/[ebp-0x48]; the cell RECT is the first stack arg.

  thunk_bw_nutrect  CALL helper: eax = native RECT*, ebp = the painter's frame -> g_bw_rect (L/R = basewin_pt;
                    T/B = the law when 2 <= pitch < 8, basewin_pt otherwise).  Preserves ecx/ebx/esi/edi/ebp.
  thunk_bw_nutfill  GraphicWin_fill_2 sites 0x411611 (filled, 0x95) / 0x41163F (empty, 0x98): was thunk_bw_fill2.
  thunk_bw_nutring  Buffer_box_2 site 0x4116A5 (intake highlight): was thunk_bw_box2; tail = thunk_bw_box2ring.
Native no-op at g <= 16 (the canvas gate is false until the base screen is scaled).
Parity: tests\\test_nutgrid_asm_parity.py.  Usage: py assemble_nutgrid.py   (prints the yaml entries)
"""
from __future__ import annotations

import contextlib
import io
import sys

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_council as AC

PCAVE2 = AC.PCAVE2
G = AC.G                                  # g_popup_scale_num
CANVAS = 0x6A7A6C                         # BaseWin centre canvas Buffer (BaseWin_g + 0x444)
CANVAS_W = CANVAS + 0x80
W_NATIVE = 758
BASEWIN_G = 0x6A7628
FILL_2 = 0x5D5350                         # GraphicWin_fill_2 thiscall(this=window; rect*, color) RET 8
BOX_2 = 0x5E3203                          # Buffer_box_2 thiscall(rect*, c_h, c_v) RET 0xC
BOX2RING = PCAVE2 + 0xEE60                # thunk_bw_box2ring
G_BW_RECT = PCAVE2 + 0xB6D0               # 16B scratch RECT (basewin slice 2)
OFF_NUTRECT, OFF_NUTFILL, OFF_NUTRING, SLOT_END = 0x1CBA0, 0x1CCC0, 0x1CCF0, 0x1D000
NUTRECT = PCAVE2 + OFF_NUTRECT


def _pt(src: str, dst: int) -> str:
    return f"""
    mov     edx, dword ptr [{src}]
    imul    edx, dword ptr [{G:#x}]
    sar     edx, 4
    mov     dword ptr [{dst:#x}], edx"""


def asm_nutrect() -> str:
    return f"""
    push    ebx
    push    esi
    push    edi
    mov     esi, eax
{_pt("esi", G_BW_RECT)}
{_pt("esi+8", G_BW_RECT + 8)}
    mov     ebx, dword ptr [ebp-0x28]
    cmp     ebx, 2
    jl      plain
    cmp     ebx, 8
    jge     plain
    mov     edi, dword ptr [ebp-0x2c]
    test    edi, edi
    jle     plain
    mov     eax, dword ptr [ebp-0x50]
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     edx, dword ptr [ebp-0x48]
    imul    edx, dword ptr [{G:#x}]
    sar     edx, 4
    sub     edx, eax
    push    eax                         ; [esp+4] = top'
    push    edx                         ; [esp]   = avail
    mov     eax, ebx
    imul    eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5
    mov     ebx, eax                    ; half_down(p*g, 16)
    mov     eax, dword ptr [esp]
    cdq
    idiv    edi
    cmp     eax, ebx
    jge     p_min
    mov     ebx, eax
p_min:
    cmp     ebx, 1
    jge     p_ok
    mov     ebx, 1
p_ok:
    mov     eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+15]
    sar     eax, 5                      ; K = stroke_width(g)
    mov     edx, ebx
    sub     edx, eax
    lea     eax, [ebx+1]
    sar     eax, 1
    cmp     edx, eax
    jge     c_half
    mov     edx, eax
c_half:
    cmp     edx, ebx
    jl      c_ok
    lea     edx, [ebx-1]
    cmp     edx, 1
    jge     c_ok
    mov     edx, 1
c_ok:
    mov     eax, edi
    imul    eax, ebx
    neg     eax
    add     eax, dword ptr [esp]
    sar     eax, 1
    add     eax, dword ptr [esp+4]      ; y0
    add     esp, 8
    mov     edi, dword ptr [ebp-0x44]
    imul    edi, ebx
    add     eax, edi
    mov     dword ptr [{G_BW_RECT + 4:#x}], eax
    add     eax, edx
    mov     dword ptr [{G_BW_RECT + 0xC:#x}], eax
    jmp     done
plain:
{_pt("esi+4", G_BW_RECT + 4)}
{_pt("esi+0xC", G_BW_RECT + 0xC)}
done:
    pop     edi
    pop     esi
    pop     ebx
    ret
"""


def asm_nutfill() -> str:
    return f"""
    cmp     ecx, {BASEWIN_G:#x}
    jne     native
    cmp     dword ptr [{CANVAS_W:#x}], {W_NATIVE}
    jle     native
    mov     eax, dword ptr [esp+4]
    call    {NUTRECT:#x}
    mov     dword ptr [esp+4], {G_BW_RECT:#x}
native:
    push    {FILL_2:#x}
    ret
"""


def asm_nutring() -> str:
    return f"""
    cmp     ecx, {CANVAS:#x}
    jne     native
    cmp     dword ptr [{CANVAS_W:#x}], {W_NATIVE}
    jle     native
    mov     eax, dword ptr [esp+4]
    call    {NUTRECT:#x}
    mov     dword ptr [esp+4], {G_BW_RECT:#x}
    push    {BOX2RING:#x}
    ret
native:
    push    {BOX_2:#x}
    ret
"""


THUNKS = [("thunk_bw_nutrect", OFF_NUTRECT, asm_nutrect, OFF_NUTFILL),
          ("thunk_bw_nutfill", OFF_NUTFILL, asm_nutfill, OFF_NUTRING),
          ("thunk_bw_nutring", OFF_NUTRING, asm_nutring, SLOT_END)]
SYMS = {G: "g_popup_scale_num", NUTRECT: "thunk_bw_nutrect", BOX2RING: "thunk_bw_box2ring", G_BW_RECT: "g_bw_rect",
        }


def assemble_all() -> dict[str, tuple[int, bytes]]:
    out = {}
    for name, off, fn, end in THUNKS:
        b = AC.assemble(fn(), PCAVE2 + off)
        assert off + len(b) <= end, (name, hex(off + len(b)), hex(end))
        out[name] = (off, b)
    return out


def main() -> int:
    lay = assemble_all()
    for name, (off, b) in lay.items():
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # basewin_nutgrid ({len(b)}B)")
    for name, (off, b) in lay.items():
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{AC.templatize(b, PCAVE2 + off, SYMS)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
