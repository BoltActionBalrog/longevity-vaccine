#!/usr/bin/env python
"""W7R v2 (2026-10-25 wave 7, user decision "Scale the thin rings"): the 0x78D960 BoxSpriteParams family's draws that
stayed native -- the popup option rows' HOVER ring (K wide but restriped E0 / E1) and the universal Menu's background
and rows (the fill a 1-row tile at every g, the 1 x 1 corner notch, the 1-px row inset).  pcave2 region 0x3F400..0x3FFFF.

PORT OF: scaling_laws.py :: ring_solid / ring_band_rects / menu_row_clip / menu_box_rect / menu_hot_row_colour /
bandmap_rect_from_halfopen /
stroke_width (the SOURCE OF TRUTH; the census of every ref to the family is scaling_laws.THIN_RING_FAMILY_REFS -- the
DiploWin item back there is unreachable and NOT patched).
Guards: tests\\test_thin_rings_asm_parity.py (Unicorn, the yaml bytes at their cave VAs) + tests\\test_scaling_thin_rings.py
(the real image: the census, reach, the popup hover row through ListBox_set_hover, the Menu at g 16..40).

  t_rowbox_solid  the site 0x405BF6 (FUN_00405b20.option_frame: was E8 -> t_rowbox_trim).  g <= 16: push t_rowbox_trim /
                  ret (the deployed path, byte for byte).  Else CALL t_rowbox_trim(rect, set) with the caller's ebp
                  intact (t_rowbox_trim reads the popup at [ebp-4]); it leaves the fn's LOCAL rect as the band-map rect
                  (R / B - 1 for every row: its own trim, or t_dp_itemrect's), so the half-open extent is that + 1 on R / B
                  (g_rs_row); then t_ring_solid(buf, g_rs_row, set).  thiscall RET 8; ebx / esi / edi / ebp kept.
  t_ring_solid    stdcall(Buffer* buf, RECT* rect half-open, BoxSpriteParams* set) RET 0xC, pushad-wrapped: g > 16, the
                  buffer has pixels, rect, set non-null and the rect >= 2K each way (K = stroke_width(g) = (2g + 15) >> 5);
                  the window = the Buffer's clip (+0x20, half-open) cut to [0, w) x [0, |h|) (g_rs_clip); per edge of the
                  set whose strip carries a stroke (top row 0 / bottom row h-1 at w/2, left col 0 / right col w-1 at h/2:
                  the box_edge_strokes probe) with a pair mate (E0 <-> E1, AE <-> EE), every pixel of the edge's band
                  (ring_band_rects of the TRUE rect, corners excluded) inside the window that equals the mate becomes the
                  stroke.  Buffer: clip +0x20, data +0x54, w +0x80, h +0x84 (negative = top-down), stride +0x4A8.
  t_menu_border   the site 0x403B88 (g_menu_border_draw's Buffer_box_sprite(self+0x474, set 0)).  g <= 16: native.
                  Else thunk_rowbox_guard(&g_mb_rect = the rect with R / B - 1, set) -- the band map (menu_box_rect).
  t_menu_row      the site 0x403B55 (g_menu_hilite_draw's Buffer_box_sprite(self+0x474, set 0 / 2) under the row clip
                  (1, t, W - 1, b)).  g <= 16: native.  Else the clip's L + (K - 1) / R - (K - 1) (menu_row_clip) through
                  Buffer_set_clip(&g_mr_clip), the native draw, then the row's fill restriped in the clip: a normal row
                  (set 0, AE / EE) by t_rw_restripe(buf, &buf->clip, set) on the buffer grid; the HOT row (set 2,
                  HOT_SET) anchored to the clip's top (menu_hot_row_colour, v3): every E0 / E1 pixel -> E0 on the first
                  T = stripe_rows(g) rows of each period from the top, E1 on the next T.  The callback restores the clip
                  to the bounds after (0x403B60).

Data: g_mb_rect @0x3F800, g_mr_clip @0x3F810, g_rs_row @0x3F820, g_rs_clip @0x3F830 (16 B each).

Usage: py assemble_thin_rings.py   -> prints the yaml symbol + content lines (byte templates)
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
REGION = (0x3F400, 0x40000)                 # W7R's pcave2 region
SITES = {                                   # va: (original call bytes, the new target)
    0x405BF6: ("E8 {rel32:t_rowbox_trim}", "t_rowbox_solid"),     # the deployed bytes there (W1A F35)
    0x403B55: ("E8 79 F2 1D 00", "t_menu_row"),                   # call Buffer_box_sprite (0x5E2DD3)
    0x403B88: ("E8 46 F2 1D 00", "t_menu_border"),                # call Buffer_box_sprite (0x5E2DD3)
}

SLOTS = {                                   # name: (offset, end)
    "t_rowbox_solid": (0x3F400, 0x3F460),
    "t_ring_solid": (0x3F460, 0x3F700),
    "t_menu_border": (0x3F700, 0x3F750),
    "t_menu_row": (0x3F840, 0x3F980),
}
CELLS = {"g_mb_rect": 0x3F800, "g_mr_clip": 0x3F810, "g_rs_row": 0x3F820, "g_rs_clip": 0x3F830}
CELL_LEN = {n: 16 for n in CELLS}
HOT_SET, HOT_TOP, HOT_MATE = 0x78D9B0, 0xE0, 0xE1   # scaling_laws.MENU_HOT_SET / MENU_HOT_TOP / MENU_HOT_MATE

# sentinel absolutes -> yaml {abs32:} placeholders
SYMS = {n: 0x11110000 + 0x10 * i for i, n in enumerate(("g_popup_scale_num", "Buffer_box_sprite", "t_rowbox_trim",
                                                         *CELLS))}
# sentinel CALL targets -> {rel32:} placeholders
CALLS = {n: 0x22220000 + 0x10 * i for i, n in enumerate(("t_rowbox_trim", "t_ring_solid", "thunk_rowbox_guard",
                                                          "Buffer_set_clip", "Buffer_box_sprite", "t_rw_restripe"))}


def S(name):
    return f"{SYMS[name]:#x}"


def C(name):
    return f"{CALLS[name]:#x}"


def _native(tail="Buffer_box_sprite"):
    return f"""
    cmp  dword ptr [{S('g_popup_scale_num')}], 0x10
    jg   go
    push {S(tail)}
    ret
go:"""


def asm_rowbox_solid():
    return f"""{_native('t_rowbox_trim')}
    push ebx
    push esi
    push edi
    mov  esi, ecx
    mov  ebx, dword ptr [esp+0x10]
    mov  edi, dword ptr [esp+0x14]
    push edi
    push ebx
    call {C('t_rowbox_trim')}
    mov  edx, {S('g_rs_row')}
    mov  eax, dword ptr [ebx]
    mov  dword ptr [edx], eax
    mov  eax, dword ptr [ebx+4]
    mov  dword ptr [edx+4], eax
    mov  eax, dword ptr [ebx+8]
    inc  eax
    mov  dword ptr [edx+8], eax
    mov  eax, dword ptr [ebx+0xc]
    inc  eax
    mov  dword ptr [edx+0xc], eax
    push edi
    push edx
    push esi
    call {C('t_ring_solid')}
    pop  edi
    pop  esi
    pop  ebx
    ret  8
"""


def asm_menu_border():
    return f"""{_native()}
    mov  eax, dword ptr [esp+4]
    mov  edx, {S('g_mb_rect')}
    push dword ptr [eax]
    pop  dword ptr [edx]
    push dword ptr [eax+4]
    pop  dword ptr [edx+4]
    push dword ptr [eax+8]
    pop  dword ptr [edx+8]
    dec  dword ptr [edx+8]
    push dword ptr [eax+0xc]
    pop  dword ptr [edx+0xc]
    dec  dword ptr [edx+0xc]
    push dword ptr [esp+8]
    push edx
    call {C('thunk_rowbox_guard')}
    ret  8
"""


def asm_menu_row():
    return f"""{_native()}
    push esi
    push edi
    mov  esi, ecx
    mov  edi, {S('g_mr_clip')}
    mov  eax, dword ptr [{S('g_popup_scale_num')}]
    lea  eax, [eax*2+0xf]
    sar  eax, 5
    dec  eax
    mov  edx, dword ptr [esi+0x20]
    add  edx, eax
    mov  dword ptr [edi], edx
    mov  edx, dword ptr [esi+0x24]
    mov  dword ptr [edi+4], edx
    mov  edx, dword ptr [esi+0x28]
    sub  edx, eax
    mov  dword ptr [edi+8], edx
    mov  edx, dword ptr [esi+0x2c]
    mov  dword ptr [edi+0xc], edx
    push edi
    mov  ecx, esi
    call {C('Buffer_set_clip')}
    push dword ptr [esp+0x10]
    push dword ptr [esp+0x10]
    mov  ecx, esi
    call {C('Buffer_box_sprite')}
    cmp  dword ptr [esp+0x10], {HOT_SET:#x}
    je   hot
    push dword ptr [esp+0x10]
    lea  eax, [esi+0x20]
    push eax
    push esi
    call {C('t_rw_restripe')}
    jmp  done
hot:
    push ebx
    push ebp
    sub  esp, 0x10
    mov  eax, dword ptr [{S('g_popup_scale_num')}]
    cmp  eax, 0x16
    jl   t_one
    shr  eax, 4
    cmp  eax, 2
    jge  t_ok
    mov  eax, 2
    jmp  t_ok
t_one:
    mov  eax, 1
t_ok:
    mov  ebp, eax
    mov  ecx, dword ptr [esi+0x2c]
    mov  eax, dword ptr [esi+0x84]
    test eax, eax
    jge  h_pos
    neg  eax
h_pos:
    cmp  ecx, eax
    jle  h_ok
    mov  ecx, eax
h_ok:
    mov  dword ptr [esp], ecx
    mov  eax, dword ptr [esi+0x20]
    test eax, eax
    jge  l_ok
    xor  eax, eax
l_ok:
    mov  dword ptr [esp+4], eax
    mov  eax, dword ptr [esi+0x28]
    mov  ecx, dword ptr [esi+0x80]
    cmp  eax, ecx
    jle  r_ok
    mov  eax, ecx
r_ok:
    mov  dword ptr [esp+8], eax
    mov  dword ptr [esp+0xc], ebp
    mov  bl, {HOT_TOP:#x}
    mov  edx, dword ptr [esi+0x24]
    test edx, edx
    jl   h_done
yl:
    cmp  edx, dword ptr [esp]
    jge  h_done
    mov  edi, edx
    imul edi, dword ptr [esi+0x4a8]
    add  edi, dword ptr [esi+0x54]
    mov  ecx, dword ptr [esp+4]
xl:
    cmp  ecx, dword ptr [esp+8]
    jge  xd
    mov  al, byte ptr [edi+ecx]
    cmp  al, {HOT_TOP:#x}
    je   wr
    cmp  al, {HOT_MATE:#x}
    jne  nx
wr:
    mov  byte ptr [edi+ecx], bl
nx:
    inc  ecx
    jmp  xl
xd:
    inc  edx
    dec  dword ptr [esp+0xc]
    jnz  yl
    mov  dword ptr [esp+0xc], ebp
    xor  bl, {HOT_TOP ^ HOT_MATE:#x}
    jmp  yl
h_done:
    add  esp, 0x10
    pop  ebp
    pop  ebx
done:
    pop  edi
    pop  esi
    ret  8
"""


# BoxSpriteParams edge strips (box_edge_strokes): (slot, row, col) -- top (0, w/2), bottom (h-1, w/2), left (h/2, 0),
# right (h/2, w-1)
STRIPS = ((0x10, "0", "half_w"), (0x14, "last", "half_w"), (0x18, "half_h", "0"), (0x1C, "half_h", "last_w"))
# ring_band_rects as (x0, y0, x1, y1) half-open, edx = the rect, ebp = K
BANDS = (("LK", "T", "RK", "TK"), ("LK", "BK", "RK", "B"), ("L", "TK", "LK", "BK"), ("RK", "TK", "R", "BK"))
BAND_VAL = {
    "L": "mov  eax, dword ptr [edx]", "T": "mov  eax, dword ptr [edx+4]",
    "R": "mov  eax, dword ptr [edx+8]", "B": "mov  eax, dword ptr [edx+0xc]",
    "LK": "mov  eax, dword ptr [edx]\n    add  eax, ebp", "TK": "mov  eax, dword ptr [edx+4]\n    add  eax, ebp",
    "RK": "mov  eax, dword ptr [edx+8]\n    sub  eax, ebp", "BK": "mov  eax, dword ptr [edx+0xc]\n    sub  eax, ebp",
}


def _art_px(slot, row, col, fail):
    """al = the texel (row, col) of the Sprite at [set + slot] (ebx = set); jump to `fail` when absent.
    Sprite: bits +4, pitch +0xC, w +0x10, h +0x14."""
    rr = {"0": "",
          "last": "mov  eax, dword ptr [ecx+0x14]\n    dec  eax\n    imul eax, dword ptr [ecx+0xc]\n    add  edx, eax",
          "half_h": "mov  eax, dword ptr [ecx+0x14]\n    shr  eax, 1\n    imul eax, dword ptr [ecx+0xc]\n    add  edx, eax"}[row]
    cc = {"0": "", "half_w": "mov  eax, dword ptr [ecx+0x10]\n    shr  eax, 1\n    add  edx, eax",
          "last_w": "mov  eax, dword ptr [ecx+0x10]\n    dec  eax\n    add  edx, eax"}[col]
    return f"""
    mov  ecx, dword ptr [ebx+{slot:#x}]
    test ecx, ecx
    je   {fail}
    mov  edx, dword ptr [ecx+4]
    test edx, edx
    je   {fail}
    cmp  dword ptr [ecx+0x10], 0
    jle  {fail}
    cmp  dword ptr [ecx+0x14], 0
    jle  {fail}
    {rr}
    {cc}
    mov  al, byte ptr [edx]
"""


def asm_solid():
    edges = []
    for i, (slot, row, col) in enumerate(STRIPS):
        x0, y0, x1, y1 = BANDS[i]
        edges.append(f"""{_art_px(slot, row, col, f"e{i}")}
    call mate
    jc   e{i}
    mov  ecx, eax
    mov  edx, dword ptr [esp+0x28]
    {BAND_VAL[y1]}
    push eax
    {BAND_VAL[x1]}
    push eax
    {BAND_VAL[y0]}
    push eax
    {BAND_VAL[x0]}
    push eax
    mov  eax, ecx
    call fixb
e{i}:
""")
    return f"""
    pushad
    cmp  dword ptr [{S('g_popup_scale_num')}], 0x10
    jle  out
    mov  esi, dword ptr [esp+0x24]
    test esi, esi
    je   out
    cmp  dword ptr [esi+0x54], 0
    je   out
    mov  ebp, dword ptr [{S('g_popup_scale_num')}]
    lea  ebp, [ebp*2+0xf]
    sar  ebp, 5
    mov  edx, dword ptr [esp+0x28]
    test edx, edx
    je   out
    mov  ebx, dword ptr [esp+0x2c]
    test ebx, ebx
    je   out
    mov  eax, dword ptr [edx+8]
    sub  eax, dword ptr [edx]
    sub  eax, ebp
    sub  eax, ebp
    jl   out
    mov  eax, dword ptr [edx+0xc]
    sub  eax, dword ptr [edx+4]
    sub  eax, ebp
    sub  eax, ebp
    jl   out
    mov  edi, {S('g_rs_clip')}
    mov  eax, dword ptr [esi+0x20]
    test eax, eax
    jge  c1
    xor  eax, eax
c1:
    mov  dword ptr [edi], eax
    mov  eax, dword ptr [esi+0x24]
    test eax, eax
    jge  c2
    xor  eax, eax
c2:
    mov  dword ptr [edi+4], eax
    mov  eax, dword ptr [esi+0x28]
    mov  ecx, dword ptr [esi+0x80]
    cmp  eax, ecx
    jle  c3
    mov  eax, ecx
c3:
    mov  dword ptr [edi+8], eax
    mov  eax, dword ptr [esi+0x2c]
    mov  ecx, dword ptr [esi+0x84]
    test ecx, ecx
    jge  c4
    neg  ecx
c4:
    cmp  eax, ecx
    jle  c5
    mov  eax, ecx
c5:
    mov  dword ptr [edi+0xc], eax
{"".join(edges)}
out:
    popad
    ret  0xc
mate:
    mov  ah, 0xe1
    cmp  al, 0xe0
    je   m_ok
    mov  ah, 0xe0
    cmp  al, 0xe1
    je   m_ok
    mov  ah, 0xee
    cmp  al, 0xae
    je   m_ok
    mov  ah, 0xae
    cmp  al, 0xee
    je   m_ok
    stc
    ret
m_ok:
    clc
    ret
fixb:
    push ebx
    push edx
    push ecx
    push edi
    mov  ecx, dword ptr [esp+0x14]
    cmp  ecx, dword ptr [edi]
    jge  f1
    mov  ecx, dword ptr [edi]
f1:
    mov  dword ptr [esp+0x14], ecx
    mov  ecx, dword ptr [esp+0x18]
    cmp  ecx, dword ptr [edi+4]
    jge  f2
    mov  ecx, dword ptr [edi+4]
f2:
    mov  dword ptr [esp+0x18], ecx
    mov  ecx, dword ptr [esp+0x1c]
    cmp  ecx, dword ptr [edi+8]
    jle  f3
    mov  ecx, dword ptr [edi+8]
f3:
    mov  dword ptr [esp+0x1c], ecx
    mov  ecx, dword ptr [esp+0x20]
    cmp  ecx, dword ptr [edi+0xc]
    jle  f4
    mov  ecx, dword ptr [edi+0xc]
f4:
    mov  dword ptr [esp+0x20], ecx
    mov  edx, dword ptr [esp+0x18]
fy:
    cmp  edx, dword ptr [esp+0x20]
    jge  fend
    mov  edi, edx
    imul edi, dword ptr [esi+0x4a8]
    add  edi, dword ptr [esi+0x54]
    mov  ecx, dword ptr [esp+0x14]
fx:
    cmp  ecx, dword ptr [esp+0x1c]
    jge  fnext
    cmp  byte ptr [edi+ecx], ah
    jne  fk
    mov  byte ptr [edi+ecx], al
fk:
    inc  ecx
    jmp  fx
fnext:
    inc  edx
    jmp  fy
fend:
    pop  edi
    pop  ecx
    pop  edx
    pop  ebx
    ret  0x10
"""


SOURCES = {"t_rowbox_solid": asm_rowbox_solid, "t_ring_solid": asm_solid, "t_menu_border": asm_menu_border,
           "t_menu_row": asm_menu_row}


def assemble(src, va):
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def to_template(blob, va):
    """abs32 sentinels -> {abs32:name}; E8 to a CALL sentinel -> {rel32:name}."""
    rabs = {v: k for k, v in SYMS.items()}
    rcall = {v: k for k, v in CALLS.items()}
    out, i = [], 0
    while i < len(blob):
        if blob[i] == 0xE8 and i + 5 <= len(blob):
            tgt = (va + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in rcall:
                out += ["E8", "{rel32:%s}" % rcall[tgt]]
                i += 5
                continue
        if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") in rabs:
            out.append("{abs32:%s}" % rabs[int.from_bytes(blob[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{blob[i]:02X}")
        i += 1
    return " ".join(out)


def resolve(tpl, va, syms, calls):
    """Template -> bytes at va with the given symbol VAs (the patcher's own rules: rel32 only after E8)."""
    out = bytearray()
    for tok in tpl.split():
        if tok.startswith("{abs32:"):
            out += syms[tok[7:-1]].to_bytes(4, "little")
        elif tok.startswith("{rel32:"):
            assert out[-1] == 0xE8
            out += ((calls[tok[7:-1]] - (va + len(out) + 4)) & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


def build():
    parts = {}
    for name, fn in SOURCES.items():
        off, end = SLOTS[name]
        assert REGION[0] <= off and end <= REGION[1], name
        va = PCAVE2 + off
        blob = assemble(fn(), va)
        assert off + len(blob) <= end, (name, hex(off + len(blob)), hex(end))
        tpl = to_template(blob, va)
        assert resolve(tpl, va, SYMS, CALLS) == blob, name
        parts[name] = (off, len(blob), tpl)
    for name, off in CELLS.items():
        assert REGION[0] <= off and off + CELL_LEN[name] <= REGION[1], name
    return parts


def main():
    for name, (off, n, tpl) in build().items():
        print(f"  {name}:  {{ cave: pcave2, offset: {off:#x} }}   # {n}B @0x{off:X}..0x{off + n:X}")
        print(f'      - id: {name}\n        offset: {off:#x}\n        bytes: "{tpl}"')
    for name, off in CELLS.items():
        print(f"  {name}:  {{ cave: pcave2, offset: {off:#x}, size: {CELL_LEN[name]} }}")
    for va, (orig, tgt) in SITES.items():
        print(f'site {va:#x}: original_bytes "{orig}"  new_bytes "E8 {{rel32:{tgt}}}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
