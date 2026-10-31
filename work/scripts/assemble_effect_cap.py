#!/usr/bin/env python
"""Assembler for the map-effect blits above the engine's 4.0 enlarge cap (group effect_scale_cap, 2026-10-11).

THE BUG (vanilla engine limit, exposed by PRACX's deep map zoom): every scaled sprite core stores
f = (float)(num/den) and REJECTS a blit with f > 4.0 (g_sprite_scale_max 0x66FDC8; Sprite_draw_table 0x5E8FF5:
`fcomp; fnstsw; test ah,0x41; jne accept` @0x5E9067, reject path 0x5E9079) -- the sprite is simply not drawn.
boom 0x504AA0 draws two map effects at the map zoom:
  - the Planet Buster cloud: buster.flc (Flic 0x90EA68) decoded into the 300x248 Buffer 0x915068, drawn by
    Buffer_draw_table 0x5D94B0 @0x505988 (key 0xFF, blend table 0x6F1B7C + idx<<12) at num/den =
    (zoom_idx+16)*k14 / (k10*16): k14/k10 = 3/2 Fission .. 5/2 Quantum/Singularity.  At 4K PRACX zooms to
    zoom_idx 72 (ratio 13.75); the cloud showed only at the farthest zoom-outs (user 2026-10-11);
  - every combat explosion: XI.pcx / XF.pcx frames (sprite tables 0x7A9B30 / 0x7AB460) drawn by Sprite_draw_table
    @0x505A71 at SCALE_NUM_G/DEN_G = (zoom_idx+16)/16 (or g_map_zoom_num/den), i.e. rejected from zoom_idx 49 up
    (PRACX reaches it on 2856+ px wide screens: 3440x1440 zooms to 64, 4K to 72).
Why the cap exists: the enlarge path's ROW REPLAY (0x5E97BE) only knows run lengths 1, 2, 3 and "else 4" -- each
source row reaches at most 4 dest rows -- so above 4.0 the rows would be compressed.  (A k-fold pre-stretch drawn at
den*k was also rejected: the clipped-table builders 0x5EAB0F / 0x5EABBF walk the 800-entry run table 0x9B3AD8 once
per source pixel, so a pre-stretched source wider than 800 runs off it.)

THE FIX (law: scaling_laws.engine_scale_rejects / effect_blit_rect / effect_blit_clip / engine_scale_runs /
engine_run_blocks / effect_blit_engine):
  t_tb_draw   drop-in for Sprite_draw_table (thiscall ecx=Sprite*; dest, key, x, y, table; RET 0x14; ratio from
              SCALE_NUM_G/DEN_G).  num == den, a null sprite or dest, den <= 0, or the ENGINE's own float test
              passing (<= 4.0) -> tail-jmp 0x5E8FF5 (bit-identical to vanilla wherever vanilla draws).  Otherwise
              it does what an UNCAPPED engine would: Buffer_get_data(dest) (0 -> return 3); the engine's dest rect
              (same x87 arithmetic, _ftol) clipped to dest+0x20 (empty -> unlock, 0); the engine's Bresenham run
              sequence (Sprite_fill_scaling_table's arithmetic, generated on the fly by t_tb_gen, so no 800-entry
              limit) walked like the clipped-table builders (t_tb_skip); per (row block, column block) ONE lookup
              table[src << 8 | dest at the block's top-left] filled over the whole block (the engine's
              per-SOURCE-texel blend), with a row replay of any length; Buffer_free_data(dest, 1); return 0.  The
              dest is written directly, like the engine's own core: no scratch, no allocation.
  t_pb_draw   drop-in for Buffer_draw_table at the buster site (thiscall ecx=Buffer*; dest, key, x, y, num, den,
              table; RET 0x1C).  <= 4.0 (same float test on the num/den args), den <= 0 or a surface Buffer ->
              tail-jmp 0x5D94B0.  Otherwise builds the Sprite view of the Buffer like Buffer_draw_table (data
              +0x54, pitch +0x4A8, w +0x80, h -[+0x84], offsets 0), sets SCALE_NUM_G/DEN_G := num/den around a call
              to t_tb_draw (Sprite_draw_table_scaled's job), RET 0x1C.  The key goes RAW, as the native call's does:
              Buffer_draw_table pushes the caller's key (push ebx @0x5D9590) and the core masks it to a byte
              (0x5E90A8); its -1 -> g_ui_transparency_key swap only reaches Sprite+8, which the core never reads.
Sprite_draw_table reads only +4 / +0xC / +0x10 / +0x14 / +0x20 / +0x24 of its Sprite (tests/test_effect_cap_sites.py),
so t_pb_draw's stack Sprite carries just those.  Cell: g_tb_f (the float32 ratio).  The art (buster.flc, XI.pcx,
XF.pcx) is a 0..14 blend-table index map with no dither pattern (x/y alternation 2-6 %), drawn exactly the way the
engine draws it below the cap: no regeneration tail applies.

Unicorn parity: tests/test_effect_cap_asm_parity.py (incl. the REAL native core at <= 4.0 on a noisy background).
Sites: tests/test_effect_cap_sites.py.
Run:  py assemble_effect_cap.py        -> prints the thunk bytes + the yaml fragments to paste
"""
from __future__ import annotations

import sys

from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
CELLS = {"g_tb_f": 0x30CB0}
OFFS = {"t_pb_draw": 0x30CC0, "t_tb_gen": 0x30D6C, "t_tb_skip": 0x30D80, "t_tb_axis": 0x30DAC, "t_tb_draw": 0x30E60}
BUDGET = {"t_pb_draw": 0x30D6C - 0x30CC0, "t_tb_gen": 0x30D80 - 0x30D6C, "t_tb_skip": 0x30DAC - 0x30D80,
          "t_tb_axis": 0x30E00 - 0x30DAC, "t_tb_draw": 0x31000 - 0x30E60}

# engine
SPRITE_DRAW_TABLE = 0x5E8FF5        # thiscall(Sprite*; dst, key, x, y, table) RET 0x14
SPRITE_DRAW_TABLE_SCALED = 0x5E8FA5 # thiscall(Sprite*; dst, key, x, y, num, den, table) RET 0x1C
BUFFER_DRAW_TABLE = 0x5D94B0        # thiscall(Buffer*; dst, key, x, y, num, den, table) RET 0x1C
BUFFER_GET_DATA = 0x5E3373          # thiscall(Buffer*) -> data (0 = fail): the engine core's dest lock
BUFFER_FREE_DATA = 0x5E34A3         # thiscall(Buffer*; n) RET 4: the matching unlock
SCALE_NUM, SCALE_DEN = 0x696D18, 0x696D1C
SCALE_MAX = 0x66FDC8                # qword 4.0
FTOL = 0x6458C8                     # MSVC _ftol: st0 -> edx:eax (truncate), pops
# sites
SITE_BUSTER, SITE_EXPL = 0x505988, 0x505A71
ORIG_BUSTER, ORIG_EXPL = "E8 23 3B 0D 00", "E8 7F 35 0E 00"

# t_tb_draw frame (ebp-relative; t_tb_gen / t_tb_skip run on it)
ROWERR, COLERR, BASE, INC, DEC, ERR0 = -0x4, -0x8, -0xC, -0x10, -0x14, -0x18
# per-axis pairs, y = x + 4 (t_tb_axis indexes them with ecx = 0 / 4): rect start, clipped start, clipped span, size
L0, T0, LC, TC, CW, ROWS, WP, HP = -0x30, -0x2C, -0x20, -0x1C, -0x28, -0x24, -0x50, -0x4C
R, RL, DROW, STRIDE, SROW = -0x34, -0x38, -0x40, -0x44, -0x48
FRAME = 0x50


def va(name: str) -> int:
    return PCAVE2 + (CELLS.get(name) or OFFS[name])


def gate_asm(num: str, den: str, native: int) -> str:
    """den <= 0 -> native; the engine's own reject test on num/den -> native when the engine would accept;
    the native tail-jmp sits right here (short jumps), the over-cap path continues at `big`."""
    return f"""
    cmp     dword ptr [{den}], 0
    jle     native
    fild    dword ptr [{num}]
    fidiv   dword ptr [{den}]
    fstp    dword ptr [{va('g_tb_f'):#x}]
    fld     dword ptr [{va('g_tb_f'):#x}]
    fcomp   qword ptr [{SCALE_MAX:#x}]
    fnstsw  ax
    test    ah, 0x41
    je      big
native:
    push    {native:#x}
    ret
big:
"""


def asm_gen() -> str:
    """t_tb_gen: the next engine run (Sprite_fill_scaling_table's step) for the err cell at ecx: err += INC; run =
    BASE, or BASE + 1 with err -= DEC when err > 0.  -> eax = run.  Clobbers edx; keeps ecx and the rest."""
    return f"""
    mov     eax, dword ptr [ebp{BASE:+#x}]
    mov     edx, dword ptr [ecx]
    add     edx, dword ptr [ebp{INC:+#x}]
    jle     g_done
    inc     eax
    sub     edx, dword ptr [ebp{DEC:+#x}]
g_done:
    mov     dword ptr [ecx], edx
    ret
"""


def asm_skip() -> str:
    """t_tb_skip: the clipped-table builders' entry walk.  eax = off (clipped start - rect start, >= 0), ecx = err
    cell (seeded with ERR0).  Whole runs are consumed while off > 0; a run straddling the edge -> eax = its remaining
    length, edx = its source index; otherwise eax = the next run, edx = its index.  Keeps ebx/esi/edi/ecx."""
    return f"""
    push    ebx
    push    esi
    mov     esi, eax
    xor     ebx, ebx
s_walk:
    test    esi, esi
    jle     s_edge
    call    {va('t_tb_gen'):#x}
    sub     esi, eax
    inc     ebx
    jmp     s_walk
s_edge:
    je      s_full
    mov     eax, esi
    neg     eax
    lea     edx, [ebx-1]
    jmp     s_out
s_full:
    call    {va('t_tb_gen'):#x}
    mov     edx, ebx
s_out:
    pop     esi
    pop     ebx
    ret
"""


def asm_axis() -> str:
    """t_tb_axis: one axis of the engine's dest rect + clip (0x5E92D7 arithmetic; IntersectRect vs dest+0x20), on
    t_tb_draw's frame.  ecx = 0 (x: size +0x10, offset +0x20, arg x, clip l/r) or 4 (y: +0x14, +0x24, arg y, clip t/b);
    esi = Sprite, edi = dest.  size' = ftol(size*f), start = ftol(pos + off*f), clipped start / span -> the axis' locals.
    Returns with the flags of the span (jle = empty).  Keeps ecx/esi/edi/ebx; x87 balanced."""
    F = va("g_tb_f")
    return f"""
    fld     dword ptr [{F:#x}]
    fild    dword ptr [esi+ecx+0x10]
    fmul    st(0), st(1)
    call    {FTOL:#x}
    mov     dword ptr [ebp+ecx{WP:+#x}], eax
    fild    dword ptr [ebp+ecx+0x10]
    fild    dword ptr [esi+ecx+0x20]
    fmul    st(0), st(2)
    faddp   st(1)
    call    {FTOL:#x}
    fstp    st(0)
    mov     dword ptr [ebp+ecx{L0:+#x}], eax
    mov     edx, dword ptr [ebp+ecx{WP:+#x}]
    add     edx, eax
    cmp     eax, dword ptr [edi+ecx+0x20]
    jge     a_lo
    mov     eax, dword ptr [edi+ecx+0x20]
a_lo:
    cmp     edx, dword ptr [edi+ecx+0x28]
    jle     a_hi
    mov     edx, dword ptr [edi+ecx+0x28]
a_hi:
    mov     dword ptr [ebp+ecx{LC:+#x}], eax
    sub     edx, eax
    mov     dword ptr [ebp+ecx{CW:+#x}], edx
    ret
"""


def asm_tb() -> str:
    """t_tb_draw. Args [ebp+8] dest, +0xC key, +0x10 x, +0x14 y, +0x18 table; locals above."""
    F = va("g_tb_f")
    return f"""
    cmp     dword ptr [ecx+4], 0
    je      native
    cmp     dword ptr [esp+4], 0
    je      native
{gate_asm(hex(SCALE_NUM), hex(SCALE_DEN), SPRITE_DRAW_TABLE)}
    push    ebp
    mov     ebp, esp
    sub     esp, {FRAME:#x}
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
    mov     ecx, dword ptr [ebp+8]
    call    {BUFFER_GET_DATA:#x}
    test    eax, eax
    jne     locked
    mov     al, 3
    jmp     out
locked:
    mov     edi, dword ptr [ebp+8]
    xor     ecx, ecx
    call    {va('t_tb_axis'):#x}
    jle     drawn
    mov     cl, 4
    call    {va('t_tb_axis'):#x}
    jle     drawn
    mov     eax, dword ptr [ebp{TC:+#x}]
    mov     ecx, dword ptr [edi+0x4A8]
    mov     dword ptr [ebp{STRIDE:+#x}], ecx
    imul    eax, ecx
    add     eax, dword ptr [edi+0x50]
    add     eax, dword ptr [ebp{LC:+#x}]
    mov     dword ptr [ebp{DROW:+#x}], eax
    mov     eax, dword ptr [{SCALE_NUM:#x}]
    cdq
    idiv    dword ptr [{SCALE_DEN:#x}]
    mov     dword ptr [ebp{BASE:+#x}], eax
    lea     ecx, [edx+edx]
    mov     dword ptr [ebp{INC:+#x}], ecx
    mov     ecx, dword ptr [{SCALE_DEN:#x}]
    add     ecx, ecx
    mov     dword ptr [ebp{DEC:+#x}], ecx
    sub     edx, ecx
    test    al, 1
    je      e_even
    add     edx, dword ptr [{SCALE_NUM:#x}]
e_even:
    cmp     ecx, 2
    jne     e_set
    xor     edx, edx
e_set:
    mov     dword ptr [ebp{ERR0:+#x}], edx
    mov     dword ptr [ebp{ROWERR:+#x}], edx
    mov     eax, dword ptr [ebp{TC:+#x}]
    sub     eax, dword ptr [ebp{T0:+#x}]
    lea     ecx, [ebp{ROWERR:+#x}]
    call    {va('t_tb_skip'):#x}
    mov     dword ptr [ebp{RL:+#x}], eax
    mov     dword ptr [ebp{R:+#x}], edx
rowloop:
    mov     eax, dword ptr [ebp{ROWS:+#x}]
    cmp     dword ptr [ebp{RL:+#x}], eax
    jle     rl_ok
    mov     dword ptr [ebp{RL:+#x}], eax
rl_ok:
    mov     edx, dword ptr [ebp{R:+#x}]
    imul    edx, dword ptr [esi+0xC]
    add     edx, dword ptr [esi+4]
    mov     dword ptr [ebp{SROW:+#x}], edx
    mov     eax, dword ptr [ebp{ERR0:+#x}]
    mov     dword ptr [ebp{COLERR:+#x}], eax
    mov     eax, dword ptr [ebp{LC:+#x}]
    sub     eax, dword ptr [ebp{L0:+#x}]
    lea     ecx, [ebp{COLERR:+#x}]
    call    {va('t_tb_skip'):#x}
    mov     ebx, dword ptr [ebp{CW:+#x}]
    mov     edi, dword ptr [ebp{DROW:+#x}]
colloop:
    cmp     eax, ebx
    jle     cl_ok
    mov     eax, ebx
cl_ok:
    push    eax
    push    edx
    mov     ecx, dword ptr [ebp{SROW:+#x}]
    movzx   ecx, byte ptr [ecx+edx]
    cmp     cl, byte ptr [ebp+0xC]
    je      blk_done
    shl     ecx, 8
    mov     cl, byte ptr [edi]
    add     ecx, dword ptr [ebp+0x18]
    mov     al, byte ptr [ecx]
    mov     edx, dword ptr [ebp{RL:+#x}]
    push    edi
fillrow:
    push    edi
    mov     ecx, dword ptr [esp+0xC]
    rep stosb
    pop     edi
    add     edi, dword ptr [ebp{STRIDE:+#x}]
    dec     edx
    jne     fillrow
    pop     edi
blk_done:
    pop     edx
    pop     eax
    add     edi, eax
    sub     ebx, eax
    jle     coldone
    inc     edx
    push    edx
    lea     ecx, [ebp{COLERR:+#x}]
    call    {va('t_tb_gen'):#x}
    pop     edx
    jmp     colloop
coldone:
    mov     eax, dword ptr [ebp{RL:+#x}]
    sub     dword ptr [ebp{ROWS:+#x}], eax
    jle     drawn
    imul    eax, dword ptr [ebp{STRIDE:+#x}]
    add     dword ptr [ebp{DROW:+#x}], eax
    inc     dword ptr [ebp{R:+#x}]
    lea     ecx, [ebp{ROWERR:+#x}]
    call    {va('t_tb_gen'):#x}
    mov     dword ptr [ebp{RL:+#x}], eax
    jmp     rowloop
drawn:
    push    1
    mov     ecx, dword ptr [ebp+8]
    call    {BUFFER_FREE_DATA:#x}
    xor     eax, eax
out:
    pop     edi
    pop     esi
    pop     ebx
    leave
    ret     0x14
"""


def asm_pb() -> str:
    """t_pb_draw. Entry: [esp+4] dest, +8 key, +0xC x, +0x10 y, +0x14 num, +0x18 den, +0x1C table.
    Frame: Sprite S at ebp-0x2C -- the fields Sprite_draw_table reads (+4 data -0x28, +0xC pitch -0x20, +0x10 w
    -0x1C, +0x14 h -0x18, +0x20/+0x24 offsets = -0xC/-8 = 0); the key goes as the arg, raw."""
    return f"""
    cmp     dword ptr [ecx+0x58], 0
    jne     native
{gate_asm('esp+0x14', 'esp+0x18', BUFFER_DRAW_TABLE)}
    push    ebp
    mov     ebp, esp
    sub     esp, 0x2C
    mov     eax, dword ptr [ecx+0x54]
    mov     dword ptr [ebp-0x28], eax
    mov     eax, dword ptr [ecx+0x4A8]
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [ecx+0x80]
    mov     dword ptr [ebp-0x1C], eax
    mov     eax, dword ptr [ecx+0x84]
    neg     eax
    mov     dword ptr [ebp-0x18], eax
    xor     eax, eax
    mov     dword ptr [ebp-0xC], eax
    mov     dword ptr [ebp-8], eax
    push    dword ptr [{SCALE_DEN:#x}]
    push    dword ptr [{SCALE_NUM:#x}]
    mov     edx, dword ptr [ebp+0x18]
    mov     dword ptr [{SCALE_NUM:#x}], edx
    mov     edx, dword ptr [ebp+0x1C]
    mov     dword ptr [{SCALE_DEN:#x}], edx
    push    dword ptr [ebp+0x20]
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x10]
    push    dword ptr [ebp+0xC]
    push    dword ptr [ebp+8]
    lea     ecx, [ebp-0x2C]
    call    {va('t_tb_draw'):#x}
    pop     dword ptr [{SCALE_NUM:#x}]
    pop     dword ptr [{SCALE_DEN:#x}]
    leave
    ret     0x1C
"""


THUNKS = [("t_pb_draw", asm_pb), ("t_tb_gen", asm_gen), ("t_tb_skip", asm_skip), ("t_tb_axis", asm_axis),
          ("t_tb_draw", asm_tb)]


def assemble(name: str) -> bytes:
    src = dict(THUNKS)[name]()
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(src, va(name))
    b = bytes(enc)
    assert len(b) <= BUDGET[name], f"{name}: {len(b)}B exceeds budget {BUDGET[name]:#x}"
    return b


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def main() -> int:
    out = {n: assemble(n) for n, _ in THUNKS}
    for n, b in out.items():
        print(f"{n} @ pcave2+{OFFS[n]:#07x} (VA {va(n):#x}) = {len(b)} bytes")
    print("\n# symbols")
    for n, off in CELLS.items():
        print(f"  {n}:{' ' * (30 - len(n))}{{ cave: pcave2, offset: {off:#x} }}")
    for n, b in out.items():
        print(f"  {n}:{' ' * (30 - len(n))}{{ cave: pcave2, offset: {OFFS[n]:#x} }}   # {len(b)}B effect_scale_cap")
    print("\n# pcave2 contents")
    for n, b in out.items():
        print(f"      - id: {n}\n        offset: {OFFS[n]:#x}\n        bytes: \"{hx(b)}\"")
    print("\n# sites")
    print(f"  boom.buster_draw  @{SITE_BUSTER:#x}  orig {ORIG_BUSTER}  -> E8 {{rel32:t_pb_draw}}")
    print(f"  boom.expl_draw    @{SITE_EXPL:#x}  orig {ORIG_EXPL}  -> E8 {{rel32:t_tb_draw}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
