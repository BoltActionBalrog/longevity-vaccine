"""t_pp_selbox -- the production picker's selected-cell outline inside the scaled frame stroke (2026-10-11).

ProdPicker_draw_cell insets the cell rect by 1 px after the frame draw (0x49289A..0x4928B7) and, for the
selected item, calls Buffer_box_2(rect, 0xFF, 0xFF) at 0x492F74: vanilla's 1-px white ring just inside the 1-px
frame stroke.  With the scaled stroke K = stroke_width(g) = 2 (g >= 25) that ring's corner pixel lands in the
frame's K x K keyed corner notch; an unselected redraw never repaints the notch, so a white pixel stays at
(L+1, T+1) and the one-row scroll copies it down the column (trace frida_pp_corner_20261012T054649.log: the
only 0xFF write is item 109's, the selected cell, between write_raw_l and the draw_cell leave).

This adapter replaces that call: K <= 1 -> Buffer_box_2 verbatim (stack untouched); else the rect is copied to
g_pp_selrect pushed in by K-1 on the left / top and K-2 on the right / bottom (the cell frame draws its R/B strokes
INCLUSIVE of R0/B0) and handed to thunk_bw_box2ring (K nested inward rings) -- law
scaling_laws.prodpicker_sel_outline_rects.  Same contract as Buffer_box_2: thiscall ecx = dest Buffer,
(rect*, color_h, color_v), RET 0xC.

Usage: assemble_pp_selbox.py      -> prints the yaml symbol + content + site lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
OFF = 0x30990                      # cave_map: 0x3098E..0x30A00 free (thunk_tutwin_ctop .. t_splash_blit)
RECT_OFF = 0x309F0                 # g_pp_selrect, 16B scratch (single synchronous draw)
END = 0x30A00
G = 0x00668740                     # g_popup_scale_num
BOX_2 = 0x005E3203                 # Buffer_box_2 (thiscall rect*, color_h, color_v; RET 0xC)
BOX2RING = PCAVE2 + 0xEE60         # thunk_bw_box2ring (same contract)
SITE = 0x00492F74                  # ProdPicker_draw_cell: the selected-cell Buffer_box_2 call
RECT = PCAVE2 + RECT_OFF

ABS = {G: "{abs32:g_popup_scale_num}", RECT: "{abs32:g_pp_selrect}"}


def asm_pp_selbox() -> str:
    return f"""
    mov     eax, dword ptr [{G:#x}]
    add     eax, eax
    add     eax, 15
    shr     eax, 5
    cmp     eax, 1
    jle     {BOX_2:#x}
    dec     eax
    push    esi
    mov     esi, dword ptr [esp+8]
    mov     edx, dword ptr [esi]
    add     edx, eax
    mov     dword ptr [{RECT:#x}], edx
    mov     edx, dword ptr [esi+4]
    add     edx, eax
    mov     dword ptr [{RECT + 4:#x}], edx
    dec     eax
    mov     edx, dword ptr [esi+8]
    sub     edx, eax
    mov     dword ptr [{RECT + 8:#x}], edx
    mov     edx, dword ptr [esi+0xC]
    sub     edx, eax
    mov     dword ptr [{RECT + 0xC:#x}], edx
    pop     esi
    mov     dword ptr [esp+4], {RECT:#x}
    jmp     {BOX2RING:#x}
"""


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def to_template(b: bytes) -> str:
    """abs32 cells -> {abs32:}; branch operands stay raw (fixed VAs; the patcher takes {rel32:} after E8 only)."""
    out, i = [], 0
    while i < len(b):
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in ABS:
            out.append(ABS[int.from_bytes(b[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def build() -> bytes:
    b = assemble(asm_pp_selbox(), PCAVE2 + OFF)
    assert OFF + len(b) <= RECT_OFF, f"t_pp_selbox {len(b)}B overflows into g_pp_selrect"
    return b


def main() -> int:
    b = build()
    print(f"  t_pp_selbox:                   {{ cave: pcave2, offset: {OFF:#x} }}   # {len(b)}B")
    print(f"  g_pp_selrect:                  {{ cave: pcave2, offset: {RECT_OFF:#x}, size: 16 }}")
    print(f"      - id: t_pp_selbox\n        offset: {OFF:#x}\n        bytes: \"{to_template(b)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
