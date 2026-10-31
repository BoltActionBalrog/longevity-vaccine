#!/usr/bin/env python
"""Assembler for map sprites above the engine's 4.0 enlarge cap (group sprite_scale_cap, 2026-10-11).

THE BUG (vanilla engine limit, exposed by PRACX's deep map zoom): every scaled sprite core stores
f = (float)(num/den) in 0x9B6624 and REJECTS a blit with f > 4.0 (qword 0x66FDC8; `test ah,0x41; jne accept`, then
`push 1; mov ecx,[ebp+8]; call Buffer_free_data; xor eax,eax; jmp epilogue`) -- nothing is drawn.  Map sprites
are drawn at SCALE_NUM_G/DEN_G = (zoom+16)/16 (scaling_laws.map_sprite_scale: veh_draw 0x55971F, base_draw
0x55B15C, MapWin_gen_terrain_poly 0x464D38), so from zoom 49 (PRACX reaches 72 at 4K, 64 at 3440x1440) unit
flags, base icons and the terrain overlay sprites vanish.  The only thing the cap protects is the enlarge
path's row replay (draw_table 0x5E97BE: runs 1/2/3/else 4).

THE FIX, at the cores themselves (every caller, PRACX's DLL included): the 8 reject-path `call` sites already
retarget to thunk_scale_reject_uncache (group scale_ratio_uncache, 0x696D20 := -1 then Buffer_free_data); they now
call t_zc_reject, which runs that vanilla reject first and then draws what an uncapped engine would
(scaling_laws.engine_enlarge_blit; the same rect / clip / runs as the Planet Buster base's effect_blit_engine):
  1. the engine's dest rect (same x87 + _ftol on 0x9B6624), cut to the dest clip (dest+0x20, IntersectRect);
  2. the engine's runs (Sprite_fill_scaling_table 0x5EB20F's recurrence = engine_scale_runs), stepped from texel 0
     at the rect edge like the clipped-table builders (engine_run_blocks), source indices unbounded like the
     engine's, generated on the fly (t_zc_step: no 800-entry table, no replay limit);
  3. per visible source row: a stack row buffer (cw bytes, pushed a dword at a time so every page is touched) of
     the key byte with each block's texel at its first column, composited 1:1 by the SAME core at the block row's
     top (caller's key and 5th arg: colour / table) -- the core's own per-pixel rule applied once per texel against
     the block's top-left dest pixel, which is exactly what its enlarge path does;
  4. that top-left pixel copied over the block's visible rect (key texels skipped), dest locked once around the
     whole draw (Buffer_get_data / Buffer_free_data nest under the core's own lock).
Cores: decoded from the reject call's return address (ret - 0x89 for the six with their Sprite at [ebp-0x5C],
ret - 0x102 for Sprite_draw_mono_2, the keyed core for the one in between).  EXCLUDED keep the vanilla reject:
Sprite_draw_dest_unk1 (no key arg), Sprite_draw_dest_unk2_2 and Sprite_draw_4 (their enlarge value is not their 1:1
rule -- measured, not modelled).  The keyed core's entry is wrapped by thunk_hudmenu_sbc (COMMLINK); the 1:1
composite enters it through t_zc_sbc_native (the replayed prologue, then 0x5E4BA0): always the plain engine core.
No cells, no heap: everything lives on t_zc_reject's frame and the stack.

Unicorn: tests/test_zoom_cap_asm_parity.py (the real cores, both sides of the cap).  Sites:
tests/test_zoom_cap_sites.py.  Laws: tests/test_scaling_zoom_cap.py.
Run:  py assemble_zoom_cap.py        -> prints the thunk bytes + the yaml fragments to paste
"""
from __future__ import annotations

import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
# reserved pcave2 windows: 0x0439A-0x044AF, 0x04C17-0x04CFF, 0x0C50B-0x0C5FF
OFFS = {"t_zc_reject": 0x43A0, "t_zc_rows": 0x4C18, "t_zc_cols": 0x4CA0, "t_zc_tail": 0xC510, "t_zc_step": 0xC5B4,
        "t_zc_vis": 0xC5D4, "t_zc_sbc_native": 0xC5E8}
WINDOWS = [(0x439A, 0x44B0), (0x4C17, 0x4D00), (0xC50B, 0xC600)]

# engine
SCALE_NUM, SCALE_DEN = 0x696D18, 0x696D1C
SCALE_F = 0x9B6624                   # float32 num/den the core just stored
FTOL = 0x6458C8                      # MSVC _ftol: st0 -> eax (truncate), pops
CRT_MALLOC, CRT_FREE = 0x64558A, 0x64557F
BUFFER_GET_DATA, BUFFER_FREE_DATA = 0x5E3373, 0x5E34A3
UNCACHE = PCAVE2 + 0xB300            # thunk_scale_reject_uncache (yaml symbol)
KEYED_CORE, KEYED_BODY = 0x5E4B9A, 0x5E4BA0
# (core start, this-pointer local, reject `call` site, epilogue) for the 8 capped cores
CORES = [
    (0x5E3E50, 0x64, 0x5E3F4D, 0x5E4AD1),   # Sprite_draw_mono_2 (dest, key, x, y, colour) RET 0x14
    (0x5E4B9A, 0x64, 0x5E4C93, 0x5E582A),   # Sprite_blit_scaled_core (dest, key, x, y) RET 0x10
    (0x5E5833, 0x5C, 0x5E58B7, 0x5E6649),   # Sprite_draw_dest (dest, key, x, y, table) RET 0x14
    (0x5E66A2, 0x5C, 0x5E6726, 0x5E73C3),   # Sprite_draw_dest_unk1 (dest, x, y, table) RET 0x10 -- excluded
    (0x5E741C, 0x5C, 0x5E74A0, 0x5E8113),   # Sprite_draw_dest_source (dest, key, x, y, table) RET 0x14
    (0x5E81BC, 0x5C, 0x5E8240, 0x5E8F9C),   # Sprite_draw_dest_unk2_2 (dest, key, x, y, table) RET 0x14
    (0x5E8FF5, 0x5C, 0x5E9079, 0x5E9D3B),   # Sprite_draw_table (dest, key, x, y, table) RET 0x14
    (0x5E9D44, 0x5C, 0x5E9DC8, 0x5EAAF6),   # Sprite_draw_4 (dest, key, x, y, table) RET 0x14
]
DEST_CORE = 0x5E5833                 # first core with its Sprite at [ebp-0x5C] (the two below keep it at [ebp-0x64])
# cores that keep the vanilla reject: Sprite_draw_dest_unk1 takes (dest, x, y, table) -- no key; Sprite_draw_dest_unk2_2
# and Sprite_draw_4 compute a block's value differently from their own 1:1 path (the replica != the native core at
# <= 4.0: tests/test_zoom_cap_asm_parity.py::test_excluded_cores_differ_from_their_1to1_path); none draws a map sprite
EXCLUDED = (0x5E66A2, 0x5E81BC, 0x5E9D44)
ORIG_SITE = "E8 {rel32:thunk_scale_reject_uncache}"


def va(name: str) -> int:
    return PCAVE2 + OFFS[name]


# Frame of t_zc_reject (ebp = its own; [ebp] = the core's ebp, [ebp+4] = the reject call's return address):
#   -4 L0  -8 T0  -0xC H'  -0x1C..-0x10 the visible rect V (l, t, r, b; r/b exclusive)  -0x20 W' then cw
#   -0x24 q  -0x28 2r  -0x2C 2s  -0x30 e0  -0x34 core call target  -0x38 column-pass mode (0 anchors / 1 replicate)
#   -0x3C dest data  -0x40 dest pitch  -0x78 the row buffer (esp right after its allocation)  -0x7C dest  -0x80 key
#   row pass (live across the composite): -0x44 ey  -0x48 py  -0x4C vy0  -0x58 vy1  -0x5C src row
#   column pass (dead across the composite): -0x64 ex  -0x68 px
#   (each axis keeps its position 4 below its error: t_zc_step's contract)
#   Sprite S of the anchor row at -0x74 (+0 -0x74, +4 -0x70, +0xC -0x68, +0x10 -0x64, +0x14 -0x60, +0x20 -0x54,
#   +0x24 -0x50 -- the only fields a core's 1:1 path reads; +0xC/+0x10/+0x14 rewritten after every anchor pass)
FRAME = 0x80
EXIT = """
    pop     edi
    pop     esi
    pop     ebx
    leave
    ret     4
"""


def asm_reject() -> str:
    """t_zc_reject: CALLed from the 8 reject paths (ecx = dest, [esp+4] = 1, ebp = the core's frame).  The vanilla
    reject first (thunk_scale_reject_uncache: ratio cache := -1, Buffer_free_data(dest, 1)), then the core, the
    engine's dest rect and its visible part; the runs and the draw continue in t_zc_tail."""
    return f"""
    push    dword ptr [esp+4]
    call    {UNCACHE:#x}
    push    ebp
    mov     ebp, esp
    add     esp, -{FRAME:#x}
    push    ebx
    push    esi
    push    edi
    cld
    mov     ebx, dword ptr [ebp]
    mov     ecx, dword ptr [ebp+4]
    lea     eax, [ecx-0x89]
    mov     esi, dword ptr [ebx-0x5c]
    cmp     eax, {EXCLUDED[0]:#x}
    je      quit
    cmp     eax, {EXCLUDED[1]:#x}
    je      quit
    cmp     eax, {EXCLUDED[2]:#x}
    je      quit
    cmp     ecx, {DEST_CORE:#x}
    jae     core_ok
    mov     esi, dword ptr [ebx-0x64]
    lea     eax, [ecx-0x102]
    cmp     ecx, {KEYED_CORE:#x}
    jb      core_ok
    mov     eax, {va('t_zc_sbc_native'):#x}
core_ok:
    mov     dword ptr [ebp-0x34], eax
    cmp     dword ptr [{SCALE_DEN:#x}], 0
    jle     quit
    mov     eax, dword ptr [ebx+8]
    mov     dword ptr [ebp-0x7C], eax
    mov     eax, dword ptr [ebx+0xC]
    mov     dword ptr [ebp-0x80], eax
    fld     dword ptr [{SCALE_F:#x}]
    fild    dword ptr [esi+0x14]
    fmul    st(0), st(1)
    call    {FTOL:#x}
    mov     dword ptr [ebp-0xC], eax
    fild    dword ptr [esi+0x10]
    fmul    st(0), st(1)
    call    {FTOL:#x}
    mov     dword ptr [ebp-0x20], eax
    fild    dword ptr [ebx+0x14]
    fild    dword ptr [esi+0x24]
    fmul    st(0), st(2)
    faddp   st(1)
    call    {FTOL:#x}
    mov     dword ptr [ebp-8], eax
    fild    dword ptr [ebx+0x10]
    fild    dword ptr [esi+0x20]
    fmul    st(0), st(2)
    faddp   st(1)
    call    {FTOL:#x}
    mov     dword ptr [ebp-4], eax
    fstp    st(0)
    mov     edi, dword ptr [ebp-0x7C]
    add     edi, 0x20
    mov     edx, dword ptr [ebp-0x20]
    add     edx, eax
    call    {va('t_zc_vis'):#x}
    jge     quit
    mov     dword ptr [ebp-0x1C], eax
    mov     dword ptr [ebp-0x14], edx
    sub     edx, eax
    mov     dword ptr [ebp-0x20], edx
    mov     eax, dword ptr [ebp-8]
    mov     edx, dword ptr [ebp-0xC]
    add     edx, eax
    add     edi, 4
    call    {va('t_zc_vis'):#x}
    jge     quit
    mov     dword ptr [ebp-0x18], eax
    mov     dword ptr [ebp-0x10], edx
    jmp     {va('t_zc_tail'):#x}
quit:
{EXIT}"""


def asm_tail() -> str:
    """t_zc_tail: the engine's run parameters (Sprite_fill_scaling_table 0x5EB20F; on the reject path num > 4*den > 0,
    so big = num, small = den), the dest lock (Buffer_get_data, nests under the core's own), SCALE_NUM_G/DEN_G = 1/1,
    a stack row buffer of cw bytes (pushed a dword at a time, so every page is touched), the row pass, then restore
    and unlock."""
    return f"""
    mov     eax, dword ptr [{SCALE_NUM:#x}]
    mov     ecx, dword ptr [{SCALE_DEN:#x}]
    xor     edx, edx
    mov     dword ptr [ebp-0x28], edx
    mov     dword ptr [ebp-0x24], eax
    dec     edx
    cmp     ecx, 1
    jle     runs_ok
    mov     edi, eax
    cdq
    idiv    ecx
    mov     dword ptr [ebp-0x24], eax
    add     edx, edx
    mov     dword ptr [ebp-0x28], edx
    sar     edx, 1
    add     ecx, ecx
    mov     dword ptr [ebp-0x2C], ecx
    sub     edx, ecx
    test    al, 1
    je      runs_ok
    add     edx, edi
runs_ok:
    mov     dword ptr [ebp-0x30], edx
    mov     ecx, dword ptr [ebp-0x7C]
    call    {BUFFER_GET_DATA:#x}
    test    eax, eax
    je      done
    mov     ecx, dword ptr [ebp-0x7C]
    mov     eax, dword ptr [ecx+0x50]
    mov     dword ptr [ebp-0x3C], eax
    mov     eax, dword ptr [ecx+0x4A8]
    mov     dword ptr [ebp-0x40], eax
    push    dword ptr [{SCALE_DEN:#x}]
    push    dword ptr [{SCALE_NUM:#x}]
    xor     eax, eax
    inc     eax
    mov     dword ptr [{SCALE_NUM:#x}], eax
    mov     dword ptr [{SCALE_DEN:#x}], eax
    mov     ecx, dword ptr [ebp-0x20]
alloc:
    push    eax
    sub     ecx, 4
    jg      alloc
    mov     dword ptr [ebp-0x78], esp
    call    {va('t_zc_rows'):#x}
    lea     esp, [ebp-{FRAME + 0x14:#x}]
    pop     dword ptr [{SCALE_NUM:#x}]
    pop     dword ptr [{SCALE_DEN:#x}]
    push    1
    mov     ecx, dword ptr [ebp-0x7C]
    call    {BUFFER_FREE_DATA:#x}
done:
{EXIT}"""


def asm_rows() -> str:
    """t_zc_rows: the row pass, CALLed by t_zc_tail right after the row buffer (its return address sits just below
    the buffer).  Per visible source row: key-fill the buffer, anchor pass, 1:1 composite of the row through the core
    (the caller's key and 5th arg), replicate pass."""
    return f"""
    mov     eax, dword ptr [ebp-0x30]
    mov     dword ptr [ebp-0x44], eax
    mov     eax, dword ptr [ebp-8]
    mov     dword ptr [ebp-0x48], eax
    mov     eax, dword ptr [esi+4]
    mov     dword ptr [ebp-0x5C], eax
    xor     eax, eax
    mov     dword ptr [ebp-0x74], eax
    mov     dword ptr [ebp-0x54], eax
    mov     dword ptr [ebp-0x50], eax
    mov     eax, dword ptr [ebp-0x78]
    mov     dword ptr [ebp-0x70], eax
row:
    lea     edx, [ebp-0x44]
    lea     edi, [ebp-0x18]
    call    {va('t_zc_step'):#x}
    jge     next_row
    mov     dword ptr [ebp-0x4C], eax
    mov     dword ptr [ebp-0x58], edx
    mov     edi, dword ptr [ebp-0x78]
    mov     al, byte ptr [ebp-0x80]
    mov     ecx, dword ptr [ebp-0x20]
    rep stosb
    and     dword ptr [ebp-0x38], 0
    call    {va('t_zc_cols'):#x}
    mov     ecx, dword ptr [ebp-0x20]
    mov     dword ptr [ebp-0x68], ecx
    mov     dword ptr [ebp-0x64], ecx
    mov     dword ptr [ebp-0x60], 1
    mov     edx, dword ptr [ebp]
    push    dword ptr [edx+0x18]
    push    dword ptr [ebp-0x4C]
    push    dword ptr [ebp-0x1C]
    push    dword ptr [ebp-0x80]
    push    dword ptr [ebp-0x7C]
    lea     ecx, [ebp-0x74]
    call    dword ptr [ebp-0x34]
    mov     esp, dword ptr [ebp-0x78]
    sub     esp, 4
    inc     dword ptr [ebp-0x38]
    call    {va('t_zc_cols'):#x}
next_row:
    mov     eax, dword ptr [esi+0xC]
    add     dword ptr [ebp-0x5C], eax
    jmp     row
"""


def asm_step() -> str:
    """t_zc_step: one block along an axis (edx = &error, its position at [edx-4]; edi = &lo, hi at [edi+8]):
    run = q (+1 and error -= 2s when error + 2r > 0); [a, b) = [pos, pos + run); pos = b.  a >= hi: past the
    visible end -> returns from its CALLER (pop; ret).  Else falls into t_zc_vis."""
    return f"""
    mov     ecx, dword ptr [ebp-0x24]
    mov     eax, dword ptr [edx]
    add     eax, dword ptr [ebp-0x28]
    jle     q_ok
    inc     ecx
    sub     eax, dword ptr [ebp-0x2C]
q_ok:
    mov     dword ptr [edx], eax
    mov     eax, dword ptr [edx-4]
    add     dword ptr [edx-4], ecx
    mov     edx, dword ptr [edx-4]
    cmp     eax, dword ptr [edi+8]
    jl      {va('t_zc_vis'):#x}
    pop     ecx
    ret
"""


def asm_vis() -> str:
    """t_zc_vis: [a, b) = [eax, edx) cut to [[edi], [edi+8]); returns the flags of `cmp eax, edx` (jge = empty)."""
    return """
    cmp     eax, dword ptr [edi]
    jge     a_ok
    mov     eax, dword ptr [edi]
a_ok:
    cmp     edx, dword ptr [edi+8]
    jle     b_ok
    mov     edx, dword ptr [edi+8]
b_ok:
    cmp     eax, edx
    ret
"""


def asm_cols() -> str:
    """t_zc_cols: one source row's columns (near subroutine on t_zc_reject's frame; esi = the source Sprite, kept;
    clobbers eax/ecx/edx/ebx/edi).  Mode [ebp-0x38] 0: each visible block's source texel at its column in the row
    buffer; else: the composited top-left dest pixel replicated over the block's visible rect, key texels skipped."""
    return f"""
    mov     ebx, dword ptr [ebp-0x5C]
    mov     eax, dword ptr [ebp-0x30]
    mov     dword ptr [ebp-0x64], eax
    mov     eax, dword ptr [ebp-4]
    mov     dword ptr [ebp-0x68], eax
col:
    lea     edx, [ebp-0x64]
    lea     edi, [ebp-0x1C]
    call    {va('t_zc_step'):#x}
    jge     next_col
    sub     edx, eax
    mov     cl, byte ptr [ebx]
    cmp     byte ptr [ebp-0x38], 0
    jne     rep_blk
    sub     eax, dword ptr [ebp-0x1C]
    add     eax, dword ptr [ebp-0x78]
    mov     byte ptr [eax], cl
    jmp     next_col
rep_blk:
    cmp     cl, byte ptr [ebp-0x80]
    je      next_col
    mov     edi, dword ptr [ebp-0x4C]
    imul    edi, dword ptr [ebp-0x40]
    add     edi, eax
    add     edi, dword ptr [ebp-0x3C]
    mov     al, byte ptr [edi]
    push    ebx
    mov     ebx, dword ptr [ebp-0x58]
    sub     ebx, dword ptr [ebp-0x4C]
fill:
    mov     ecx, edx
    push    edi
    rep stosb
    pop     edi
    add     edi, dword ptr [ebp-0x40]
    dec     ebx
    jne     fill
    pop     ebx
next_col:
    inc     ebx
    jmp     col
"""


def asm_stub() -> str:
    return f"""
    .byte   0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x64
    jmp     {KEYED_BODY:#x}
"""


THUNKS = [("t_zc_reject", asm_reject), ("t_zc_step", asm_step), ("t_zc_vis", asm_vis), ("t_zc_cols", asm_cols),
          ("t_zc_tail", asm_tail), ("t_zc_rows", asm_rows), ("t_zc_sbc_native", asm_stub)]


def assemble(name: str) -> bytes:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(dict(THUNKS)[name](), va(name))
    return bytes(enc)


def spans() -> dict:
    """pcave2 offset span of every entry; each inside ONE reserved window, no two overlapping."""
    out = {n: (OFFS[n], OFFS[n] + len(assemble(n))) for n, _ in THUNKS}
    for n, (a, b) in out.items():
        assert any(lo <= a and b <= hi for lo, hi in WINDOWS), f"{n} {a:#x}..{b:#x} outside the reserved windows"
    items = sorted(out.items(), key=lambda kv: kv[1])
    for (n1, (_, b1)), (n2, (a2, _)) in zip(items, items[1:]):
        assert b1 <= a2, f"{n1} overlaps {n2}"
    return out


def template(name: str) -> str:
    """Hex with {rel32:thunk_scale_reject_uncache} for the one call into another group's thunk; every other branch
    (engine code, this group's fixed windows) stays literal (feedback-templatize-branch-operands)."""
    b = assemble(name)
    base = va(name)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    out = [f"{x:02X}" for x in b]
    for ins in md.disasm(b, base):
        off = ins.address - base
        if ins.mnemonic == "call" and b[off] == 0xE8 and int(ins.op_str, 16) == UNCACHE:
            out[off + 1:off + 5] = ["{rel32:thunk_scale_reject_uncache}", "", "", ""]
    return " ".join(x for x in out if x)


def main() -> int:
    for n, (a, b) in sorted(spans().items(), key=lambda kv: kv[1]):
        print(f"{n:18s} pcave2+{a:#07x}..{b:#07x} ({b - a}B)")
    print("\n# symbols")
    for n, _ in THUNKS:
        print(f"  {n}:{' ' * (30 - len(n))}{{ cave: pcave2, offset: {OFFS[n]:#x} }}")
    print("\n# pcave2 contents")
    for n, _ in THUNKS:
        print(f"      - id: {n}\n        offset: {OFFS[n]:#x}\n        bytes: \"{template(n)}\"")
    print("\n# sites (retarget)")
    for start, _, site, _ in CORES:
        print(f"  {site:#x}  {ORIG_SITE}  ->  E8 {{rel32:t_zc_reject}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
