#!/usr/bin/env python
"""Assembler for the Caviar DIRTY-RECT COMPOSITE (group caviar_dirty_rect, 2026-10-10).

Every unit drawn on the map (veh_draw -> vehdraw_draw -> Caviar_draw 0x617230) is a fresh voxel render into two
offscreen targets that dw_scale option E grew from 256^2 to 1024^2 (g_caviar_target 0x9B9108 colour, key 9;
g_caviar_target2 0x9B96B0 aux, 0). Caviar_draw then composites the WHOLE of each target onto the map and
Caviar_reset clears the WHOLE target2 -- ~3 MB of pixel traffic per unit, 16x vanilla (hook_dragscroll.js
2026-10-10: the units+bases pass 64-85 ms per full map redraw vs 46 ms pristine). The engine already tracks the
drawn extent of each target (UnionRect per rasterised object into 0x9B9690..0x9B969C and 0x9BB438..0x9BB444,
exclusive right/bottom; reset zeroes both AFTER its fills), and everything outside those rects is the
background value, so compositing / clearing only the rects is pixel-identical.

PRACX removes DirectDraw ("Die DDraw Die!"), so every Buffer primitive takes its software path, which reads only
+0x54 data / +0x4A8 stride / +0x80 w / +0x84 -h of the SOURCE (and +0x58 surface == 0). The three thunks
therefore narrow the source to its dirty rect by rewriting those three fields around the engine's own call
(the engine's loop, clip and bookkeeping run untouched), then restore them:

  t_cav_blit    call-redirect @0x6175F4 (Caviar_draw: Buffer_draw_2(target -> dst, key 9, X, Y, num, den)
                RET 0x18). Design Workshop / picker destinations hand off to thunk_dw_shim unchanged (its own
                SSAA / fit composite); otherwise 1:1 only (num == den -- a scaled sub-rect would change the
                stretch phase), surface == 0, and the clamped rect non-empty: blit the rect at (X+l, Y+t).
                An empty rect draws nothing (the target is all key 9).
  t_cav_table   call-redirect @0x6175AC (Caviar_draw: Buffer_draw_dest_source_2(target2 -> dst, 0, x, y, num,
                den, table) RET 0x1C): the same with the target2 rect (map draws pass flag 1 | (state&0x2000)>>12,
                so this software table composite runs for every map unit without state 0x2000). The target2
                rect is dilated by one on the right/bottom: the aux plotter 0x666A80 clip-tests only a block's
                anchor and writes 2x2, so a block can overhang the predicted rect by one pixel.
  t_cav_fill2   call-redirect @0x6184BF (Caviar_reset: Buffer_fill_2(target2, 0) RET 4): fills only the
                clamped, dilated target2 rect (rep stosb per row; Buffer_fill_2 fills the whole buffer when
                clip == bounds, which hook_cavdirty.js confirms for target2).

The rects are clamped to [0, w] x [0, h] (the raster can overrun the target: thunk_dw_resetguard exists for
the same reason). A null data pointer (Buffer_init failure / after shutdown) takes the engine's own path, and
the lock latch +0x50 is saved/restored with the fields (a locked target would otherwise keep the narrowed
pointer). No scale gate: identical pixels at every g, and the work saved is resolution-independent.
Unicorn parity: tests/test_cavdirty_asm_parity.py. Site test: tests/test_cavdirty_sites.py.

Run:  py assemble_cavdirty.py        -> prints the thunk bytes + the yaml fragments to paste
"""
from __future__ import annotations

import sys

from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
OFFS = {"t_cav_blit": 0x30000, "t_cav_table": 0x30120, "t_cav_fill2": 0x30240}
BUDGET = {"t_cav_blit": 0x120, "t_cav_table": 0x120, "t_cav_fill2": 0xC0}

# engine
T1, T2 = 0x9B9108, 0x9B96B0                       # g_caviar_target / g_caviar_target2 (Buffer)
BB1 = (0x9B9690, 0x9B9694, 0x9B9698, 0x9B969C)    # target dirty rect L T R B (exclusive R/B)
BB2 = (0x9BB438, 0x9BB43C, 0x9BB440, 0x9BB444)    # target2 dirty rect
BUFFER_DRAW_2 = 0x5D84C0                           # thiscall(src; dst, key, X, Y, num, den) RET 0x18
BUFFER_DRAW_DS2 = 0x5D8EE0                         # thiscall(src; dst, key, x, y, num, den, table) RET 0x1C
BUFFER_FILL_2 = 0x5DFB50                           # thiscall(this; color) RET 4
F_DATA, F_SURF, F_W, F_H, F_STRIDE, F_LATCH = 0x54, 0x58, 0x80, 0x84, 0x4A8, 0x50   # +0x50 = the lock latch (= data while locked)
# Design Workshop hand-off (assemble_dw.py: DW_CANVAS, CELL g_dw_pickcanvas, thunk_dw_shim @pcave2+0x18790)
DW_CANVAS, DW_PICKCELL, DW_SHIM = 0x71F6F4, 0xA26010, 0xA24790
# sites
SITE_BLIT, SITE_TABLE, SITE_FILL2 = 0x6175F4, 0x6175AC, 0x6184BF
ORIG_BLIT, ORIG_TABLE, ORIG_FILL2 = "E8 C7 0E FC FF", "E8 2F 19 FC FF", "E8 8C 76 FC FF"


def clamp_asm(bb: tuple[int, int, int, int], dilate: bool = False) -> str:
    """esi = the source Buffer. -> edx = l, ecx = t, eax = r, ebx = b, clamped to [0,w] x [0,h]; edi scratch.
    dilate: r + 1, b + 1 before the clamp (the target2 aux plotter's 2x2 overhang)."""
    L, T, R, B = bb
    inc_r = "    inc     eax\n" if dilate else ""
    inc_b = "    inc     ebx\n" if dilate else ""
    # a dilated rect must still be EMPTY when nothing was drawn (the raw rect is zero after reset)
    raw_empty = f"""
    mov     eax, dword ptr [{L:#x}]
    cmp     eax, dword ptr [{R:#x}]
    jge     done
    mov     eax, dword ptr [{T:#x}]
    cmp     eax, dword ptr [{B:#x}]
    jge     done
""" if dilate else ""
    return raw_empty + f"""
    mov     edx, dword ptr [{L:#x}]
    test    edx, edx
    jge     l_ok
    xor     edx, edx
l_ok:
    mov     ecx, dword ptr [{T:#x}]
    test    ecx, ecx
    jge     t_ok
    xor     ecx, ecx
t_ok:
    mov     eax, dword ptr [{R:#x}]
{inc_r}    cmp     eax, dword ptr [esi+{F_W:#x}]
    jle     r_ok
    mov     eax, dword ptr [esi+{F_W:#x}]
r_ok:
    mov     ebx, dword ptr [{B:#x}]
{inc_b}    mov     edi, dword ptr [esi+{F_H:#x}]
    neg     edi
    cmp     ebx, edi
    jle     b_ok
    mov     ebx, edi
b_ok:
"""


def composite_asm(this: int, bb: tuple[int, int, int, int], target: int, nargs: int, dw_gate: bool,
                  dilate: bool = False) -> str:
    """The narrowed composite: rewrite data/w/h (+ the lock latch) around the engine call. nargs stack args
    (6 or 7); after the 3 register + 4 field pushes the first arg sits at esp+0x20; every arg is then pushed
    from the slot of the LAST arg (each push shifts the next one up by 4)."""
    slot = 0x20 + 4 * (nargs - 1)
    gate = f"""
    mov     eax, dword ptr [esp+4]
    cmp     eax, {DW_CANVAS:#x}
    je      dw
    cmp     eax, dword ptr [{DW_PICKCELL:#x}]
    je      dw
""" if dw_gate else ""
    pushes = "".join(f"    push    dword ptr [esp+{slot:#x}]\n" for _ in range(nargs - 4))   # table?, den, num
    return f"""{gate}
    cmp     ecx, {this:#x}
    jne     full
    cmp     dword ptr [ecx+{F_SURF:#x}], 0
    jne     full
    cmp     dword ptr [ecx+{F_DATA:#x}], 0
    je      full
    mov     eax, dword ptr [esp+0x14]
    cmp     eax, dword ptr [esp+0x18]
    jne     full
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
{clamp_asm(bb, dilate)}
    cmp     edx, eax
    jge     done
    cmp     ecx, ebx
    jge     done
    push    dword ptr [esi+{F_DATA:#x}]
    push    dword ptr [esi+{F_W:#x}]
    push    dword ptr [esi+{F_H:#x}]
    push    dword ptr [esi+{F_LATCH:#x}]
    sub     eax, edx
    mov     dword ptr [esi+{F_W:#x}], eax
    mov     eax, ecx
    sub     eax, ebx
    mov     dword ptr [esi+{F_H:#x}], eax
    mov     eax, ecx
    imul    eax, dword ptr [esi+{F_STRIDE:#x}]
    add     eax, edx
    add     eax, dword ptr [esi+{F_DATA:#x}]
    mov     dword ptr [esi+{F_DATA:#x}], eax
{pushes}    mov     eax, dword ptr [esp+{slot:#x}]
    add     eax, ecx
    push    eax
    mov     eax, dword ptr [esp+{slot:#x}]
    add     eax, edx
    push    eax
    push    dword ptr [esp+{slot:#x}]
    push    dword ptr [esp+{slot:#x}]
    mov     ecx, esi
    mov     eax, {target:#x}
    call    eax
    pop     dword ptr [esi+{F_LATCH:#x}]
    pop     dword ptr [esi+{F_H:#x}]
    pop     dword ptr [esi+{F_W:#x}]
    pop     dword ptr [esi+{F_DATA:#x}]
done:
    pop     edi
    pop     esi
    pop     ebx
    ret     {4 * nargs:#x}
full:
    mov     eax, {target:#x}
    jmp     eax
""" + (f"""dw:
    mov     eax, {DW_SHIM:#x}
    jmp     eax
""" if dw_gate else "")


def asm_blit() -> str:
    return composite_asm(T1, BB1, BUFFER_DRAW_2, 6, True)


def asm_table() -> str:
    return composite_asm(T2, BB2, BUFFER_DRAW_DS2, 7, False, dilate=True)


def asm_fill2() -> str:
    return f"""
    cmp     ecx, {T2:#x}
    jne     full
    cmp     dword ptr [ecx+{F_SURF:#x}], 0
    jne     full
    cmp     dword ptr [ecx+{F_DATA:#x}], 0
    je      full
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
{clamp_asm(BB2, dilate=True)}
    sub     eax, edx
    jle     done
    cmp     ecx, ebx
    jge     done
    mov     edi, ecx
    imul    edi, dword ptr [esi+{F_STRIDE:#x}]
    add     edi, edx
    add     edi, dword ptr [esi+{F_DATA:#x}]
    mov     edx, eax
    sub     ebx, ecx
    mov     eax, dword ptr [esp+0x10]
rows:
    mov     ecx, edx
    push    edi
    rep stosb
    pop     edi
    add     edi, dword ptr [esi+{F_STRIDE:#x}]
    dec     ebx
    jnz     rows
done:
    pop     edi
    pop     esi
    pop     ebx
    ret     4
full:
    mov     eax, {BUFFER_FILL_2:#x}
    jmp     eax
"""


THUNKS = [("t_cav_blit", asm_blit), ("t_cav_table", asm_table), ("t_cav_fill2", asm_fill2)]


def assemble(name: str) -> bytes:
    src = dict(THUNKS)[name]()
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(src, PCAVE2 + OFFS[name])
    b = bytes(enc)
    assert len(b) <= BUDGET[name], f"{name}: {len(b)}B exceeds budget {BUDGET[name]:#x}"
    return b


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def main() -> int:
    out = {n: assemble(n) for n, _ in THUNKS}
    for n, b in out.items():
        print(f"{n} @ pcave2+{OFFS[n]:#07x} (VA {PCAVE2 + OFFS[n]:#x}) = {len(b)} bytes")
    print("\n# symbols")
    for n, b in out.items():
        print(f"  {n}:{' ' * (30 - len(n))}{{ cave: pcave2, offset: {OFFS[n]:#x} }}   # {len(b)}B caviar_dirty_rect, src scripts/assemble_cavdirty.py")
    print("\n# pcave2 contents")
    for n, b in out.items():
        print(f"      - id: {n}\n        offset: {OFFS[n]:#x}\n        bytes: \"{hx(b)}\"")
    print("\n# sites")
    print(f"  Caviar_draw.composite        @{SITE_BLIT:#x}  orig {ORIG_BLIT}  -> E8 {{rel32:t_cav_blit}}")
    print(f"  Caviar_draw.table_composite  @{SITE_TABLE:#x}  orig {ORIG_TABLE}  -> E8 {{rel32:t_cav_table}}")
    print(f"  Caviar_reset.target2_fill    @{SITE_FILL2:#x}  orig {ORIG_FILL2}  -> E8 {{rel32:t_cav_fill2}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
