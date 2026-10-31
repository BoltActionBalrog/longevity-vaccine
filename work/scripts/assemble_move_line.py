#!/usr/bin/env python
"""map_move_line_scale (2026-09-24): the map's unit move / Go-To path line and its "Move to" label scale.

PORT OF: scaling_laws.move_line_calls / move_line_offsets / move_label_shadow (+ font_face_law via t_ffn).
Parity: tests/test_move_line_asm_parity.py.  Sweep: tests/test_scaling_move_line.py.

DEFECT (engine code, byte-identical to pristine): dragging a unit on the main map (MapWin_on_mouse_move
0x46F000) and a unit's Go-To order (draw_my_dest 0x4B4BF0) draw a 1px path polyline and the label
"Move to (x, y): Dist = n a/b" on the Console's buffered overlay (Buffer 0x93755C) -- both native size at 4K.

FIX (three call-target redirects, one group):
  0x46F586  Buffer_set_text_color(0x9F, 0x41, 1, 1)  -> t_ml_textcolor: shadow dx/dy = half_down(v*g, 16),
            then tail-jmp 0x5DACB0 (its RET 0x10 consumes the site's frame).
  0x46F595  find_font(12, 1)                         -> t_ffn (the face law; cdecl drop-in, caller add esp,8).
  0x4673DC  Buffer_line_2(x1, y1, x2, y2, color)     -> t_ml_line: K = half_down(g, 16) minor-axis copies + the
            K x K endpoint plugs (Buffer_hline_2 rows), callee-cleans 0x14 like Buffer_line_2.  g <= 16, K <= 1
            or a zero-length line tail-jmps the native Buffer_line_2 with the frame untouched.

Usage: py assemble_move_line.py [--splice]
"""
from __future__ import annotations

import pathlib
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
LINE_OFF = 0x2FE60                     # cave_map --fit: free after t_orn_fieldsub (ends 0x2FE5F), cave ends 0x30000
LIMIT = 0x30000
G = 0x668740                           # g_popup_scale_num
BUFFER_LINE_2 = 0x5E15F0               # thiscall (x1,y1,x2,y2,color) RET 0x14
BUFFER_HLINE_2 = 0x5E1A80              # thiscall (x0,x1,y,color) RET 0x10; no-op on x0 == x1
BUFFER_SET_TEXT_COLOR = 0x5DACB0       # thiscall (color, shadow, dx, dy) RET 0x10

SITE_LINE = 0x4673DC                   # MapWin_direct_dest_line: E8 0F A2 17 00 (call Buffer_line_2)
SITE_TEXTCOLOR = 0x46F586              # MapWin_on_mouse_move:    E8 25 B7 16 00 (call Buffer_set_text_color)
SITE_FONT = 0x46F595                   # MapWin_on_mouse_move:    E8 56 8D 11 00 (call find_font(12,1))

# t_ml_line.  Entered by E8 from 0x4673DC: ecx = Buffer, [esp] = ret, [esp+4..+0x14] = x1,y1,x2,y2,color.
# Scaled frame (after 4 saves + the lo local): B = esp, [B] = lo, x1 [B+0x18], y1 [B+0x1C], x2 [B+0x20],
# y2 [B+0x24], color [B+0x28].  Every 5-push arg build reads [esp+0x28]: each push moves esp by the 4 that the
# next arg sits below the previous one.
ASM_LINE = f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     ml_native
    mov     eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+0xF]
    sar     eax, 5
    cmp     eax, 1
    jle     ml_native
    mov     edx, dword ptr [esp+4]
    cmp     edx, dword ptr [esp+0xC]
    jne     ml_go
    mov     edx, dword ptr [esp+8]
    cmp     edx, dword ptr [esp+0x10]
    je      ml_native
ml_go:
    push    ebp
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
    mov     ebx, eax
    mov     eax, dword ptr [esp+0x1C]
    sub     eax, dword ptr [esp+0x14]
    cdq
    xor     eax, edx
    sub     eax, edx
    mov     ecx, dword ptr [esp+0x20]
    sub     ecx, dword ptr [esp+0x18]
    mov     edx, ecx
    sar     edx, 31
    xor     ecx, edx
    sub     ecx, edx
    xor     edi, edi
    cmp     eax, ecx
    jge     ml_axis
    inc     edi
ml_axis:
    lea     ebp, [ebx-1]
    sar     ebp, 1
    neg     ebp
    push    ebp
ml_line:
    xor     ecx, ecx
    mov     edx, ebp
    test    edi, edi
    jz      ml_l1
    xchg    ecx, edx
ml_l1:
    push    dword ptr [esp+0x28]
    mov     eax, dword ptr [esp+0x28]
    add     eax, edx
    push    eax
    mov     eax, dword ptr [esp+0x28]
    add     eax, ecx
    push    eax
    mov     eax, dword ptr [esp+0x28]
    add     eax, edx
    push    eax
    mov     eax, dword ptr [esp+0x28]
    add     eax, ecx
    push    eax
    mov     ecx, esi
    call    {BUFFER_LINE_2:#x}
    inc     ebp
    mov     eax, dword ptr [esp]
    add     eax, ebx
    cmp     ebp, eax
    jl      ml_line
    xor     edi, edi
ml_plug:
    mov     ebp, dword ptr [esp]
ml_row:
    push    dword ptr [esp+0x28]
    mov     eax, dword ptr [esp+edi+0x20]
    add     eax, ebp
    push    eax
    mov     eax, dword ptr [esp+edi+0x20]
    add     eax, dword ptr [esp+8]
    lea     ecx, [eax+ebx-1]
    push    ecx
    push    eax
    mov     ecx, esi
    call    {BUFFER_HLINE_2:#x}
    inc     ebp
    mov     eax, dword ptr [esp]
    add     eax, ebx
    cmp     ebp, eax
    jl      ml_row
    add     edi, 8
    cmp     edi, 0x10
    jl      ml_plug
    pop     eax
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret     0x14
ml_native:
    jmp     {BUFFER_LINE_2:#x}
"""

# t_ml_textcolor.  Entered by E8 from 0x46F586: ecx = Buffer, [esp] = ret, [esp+4..+0x10] = color, shadow, dx, dy.
# dx/dy := half_down(v*g, 16) = (2*v*g + 15) >> 5 (arithmetic shift = floor, as the law).  eax is dead at the
# site (the callee clobbers it too); flags are dead (find_font follows).
ASM_TEXTCOLOR = f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     tc_go
    mov     eax, dword ptr [esp+0xC]
    imul    eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+0xF]
    sar     eax, 5
    mov     dword ptr [esp+0xC], eax
    mov     eax, dword ptr [esp+0x10]
    imul    eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+0xF]
    sar     eax, 5
    mov     dword ptr [esp+0x10], eax
tc_go:
    jmp     {BUFFER_SET_TEXT_COLOR:#x}
"""


def _asm(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    return bytes(enc)


def layout():
    """(line_off, line_bytes, tc_off, tc_bytes): t_ml_textcolor follows t_ml_line on a 16-byte boundary."""
    line = _asm(ASM_LINE, PCAVE2 + LINE_OFF)
    tc_off = (LINE_OFF + len(line) + 0xF) & ~0xF
    tc = _asm(ASM_TEXTCOLOR, PCAVE2 + tc_off)
    assert tc_off + len(tc) <= LIMIT, "map_move_line_scale overruns pcave2"
    return LINE_OFF, line, tc_off, tc


def templ(b: bytes) -> str:
    hexs = " ".join(f"{x:02X}" for x in b)
    le = " ".join(f"{x:02X}" for x in G.to_bytes(4, "little"))
    assert le in hexs
    return hexs.replace(le, "{abs32:g_popup_scale_num}")


GROUP = "map_move_line_scale"
M_SYM = (f"  # ==== {GROUP} symbols (2026-09-24, src assemble_move_line.py) ====\n",
         f"# ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} cave (src assemble_move_line.py; laws scaling_laws.move_line_calls / move_label_shadow) ====\n",
          f"# ==== {GROUP} END ==== cave\n")
ANCHOR_SYM = "# ==== ornate_field_right END ==== symbols"
ANCHOR_CAVE = "# ==== ornate_field_right END ==== cave"


def main() -> int:
    lo, line, to, tc = layout()
    print(f"OK  t_ml_line      @0x{lo:05X} len={len(line)} (VA {PCAVE2 + lo:#x})")
    print(f"OK  t_ml_textcolor @0x{to:05X} len={len(tc)} (VA {PCAVE2 + to:#x})")
    if "--splice" not in sys.argv:
        print(templ(line))
        print(templ(tc))
        return 0
    y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    data = y.read_bytes()
    nl = b"\r\n" if b"\r\n" in data[:4096] else b"\n"
    sym = (M_SYM[0]
           + f"  t_ml_line:                     {{ cave: pcave2, offset: {lo:#07x} }}   # {GROUP} ({len(line)}B): Buffer_line_2 redirect @0x4673DC; K = half_down(g,16) minor-axis copies + K x K endpoint plugs (Buffer_hline_2 rows), RET 0x14\n"
           + f"  t_ml_textcolor:                {{ cave: pcave2, offset: {to:#07x} }}   # {GROUP} ({len(tc)}B): Buffer_set_text_color redirect @0x46F586; shadow dx/dy = half_down(v*g,16), tail-jmp 0x5DACB0\n"
           + M_SYM[1])
    cave = (M_CAVE[0]
            + "      # The map's unit move / Go-To path (MapWin_direct_dest_line's one overlay Buffer_line_2 @0x4673DC) draws K parallel\n"
            + "      # copies offset along the minor axis + a K x K plug at both endpoints (the joints between hops that leave by different\n"
            + "      # axes would otherwise notch); the \"Move to\" label's text shadow offset scales (font: t_ffn at 0x46F595).\n"
            + f"      - id: t_ml_line\n        offset: {lo:#07x}\n        bytes: \"{templ(line)}\"\n"
            + f"      - id: t_ml_textcolor\n        offset: {to:#07x}\n        bytes: \"{templ(tc)}\"\n"
            + M_CAVE[1])

    def put_block(data, block, markers, anchor):
        blk = block.replace("\n", nl.decode()).encode("utf-8")
        a, z = markers[0].strip("\n").encode(), markers[1].strip("\n").encode()
        if a in data:
            s = data.index(a)
            s = data.rfind(nl, 0, s) + len(nl)
            e = data.index(z, s) + len(z)
            if data[e:e + len(nl)] == nl:
                e += len(nl)
            assert 0 < s < e
            return data[:s] + blk + data[e:]
        anc = anchor.encode()
        assert data.count(anc) == 1, anchor
        p = data.index(anc) + len(anc)
        p = data.index(nl, p) + len(nl)
        return data[:p] + blk + data[p:]

    data = put_block(data, sym, M_SYM, ANCHOR_SYM)
    data = put_block(data, cave, M_CAVE, ANCHOR_CAVE)
    y.write_bytes(data)
    print("spliced into", y)
    return 0


if __name__ == "__main__":
    sys.exit(main())
