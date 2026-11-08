"""Assembler for the COMMLINK multiplayer header strip on the zone law (group commlink_mp_spots, 2026-11-07).

Law: scaling_laws.commlink_zone_map / commlink_header_synth (COMMLINK_HEADER_ROW_SEGS / _COL_SEGS, scanicon_pair_lut,
the even native row on stripe_top).  The header (MultiWin +0x1110, 138 x 28) is re-synthesized by hm_synth_core
(its one-pair probe + NN banded it in 3 colours, its 1-px lines came out 2 / 3 px); this post-pass redraws the whole
rect the core drew.

Thunks (pcave2 region 0x41000..0x43FFF, grown 0x41000 -> 0x44000):
  t_clmp_post   t_clmp_synth's tail (jmp, was `mov [g_clmp_son], 0 / ret 0x18`): son := 0; when g > 16, the 6th arg
                is the header sprite and g_clmp_h > 0 (t_clmp_synh's H of THIS core call; t_clmp_synth sets it -1
                before the call, so a refused core leaves -1), CALL t_clhd_draw(dst, dx, dy, num, den, spr, H);
                RET 0x18.  eax / ecx / edx clobbered (the core's contract).
  t_clhd_draw   stdcall (dst, dx, dy, num, den, spr, H) RET 0x1C: the law over [max(dx,0), min(dx+W, bw)) x
                [max(dy,0), min(dy+H, bh)), W = (138 num + den / 2) / den; refuses (draws nothing) on g <= 16, P < 2,
                den <= 0, num <= 0, a sprite not 138 x 28 / no texels / pitch <= 0, no dest plane / stride <= 0,
                W outside 1..1024, H outside 1..256, a zone map that does not fit, an empty cut.  Keeps ebx/esi/edi/ebp.
  t_clhd_zone   stdcall (segs, nsegs, dst_n, k, out) RET 0x14 -> eax 1 / 0: commlink_zone_map into out (bytes).
  t_clmp_pre    (2026-11-08) CALL helper at t_clmp_synth's start: every railed COMMLINK strip (138 wide, not the 6-row
                title, dx 0) -> g_mc_w = hm_sc(138), the column zone map into g_clhd_cmap, g_mc_on = 2
                (scaling_laws.commlink_rail_strip_synth); t_clmp_post clears g_mc_on.
  t_clmp_col    hm_synth_core's column call (was t_mc_col): mode 2 -> g_clhd_cmap[x - dx], else t_mc_col.
  t_clhd_snap   stdcall (h, dy) RET 8: commlink_header_rowmap's snap of the inner box (native rows 6..21) to whole
                stripe periods, on the zone map already in g_clhd_rmap.
  t_clhd_draw   swaps a pair texel to its mate only where the mate is its vertical neighbour in the art.
  t_clhd_lut    stdcall (art, pitch, w, h, key) RET 0x14: scanicon_pair_lut into g_clhd_lut (512 words, index
                (v << 1) | parity, 0xFFFF = no mate); cached on (art, pitch, w, h, key, a rolling hash of the texels).
Data: g_clhd_rsegs / g_clhd_csegs (len, line) byte pairs; cells g_clhd_cache (6 dwords), g_clmp_h; BSS g_clhd_rmap
(256 B), g_clhd_cmap (1024 B), g_clhd_lut (1 KB), g_clhd_n (2 KB), g_clhd_pl (2 KB), g_clhd_cnt (1 KB).

Guard: tests/test_commlink_hdr_asm_parity.py (Unicorn: the yaml bytes vs the law, real + synthetic art, every g,
cuts, refusals, the cache); tests/test_commlink_mp_spots.py (the real panel end to end).

Usage: assemble_commlink_hdr.py [--splice]
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: F401,E402

import scaling_laws as SL

PCAVE2 = 0x00A0C000
REGION = (0x41000, 0x44000)
SLOTS = {"t_clmp_post": 0x41000, "t_clhd_draw": 0x41080, "t_clhd_zone": 0x41400, "t_clhd_lut": 0x41600,
         "t_clhd_snap": 0x43C00, "t_clmp_col": 0x41A80, "t_clmp_pre": 0x41AC0,
         "g_clhd_rsegs": 0x41A00, "g_clhd_csegs": 0x41A20, "g_clhd_cache": 0x41A40, "g_clmp_h": 0x41A60,
         "g_clhd_rmap": 0x41C00, "g_clhd_cmap": 0x42000, "g_clhd_lut": 0x42400, "g_clhd_n": 0x42800,
         "g_clhd_pl": 0x43000, "g_clhd_cnt": 0x43800}
SIZES = {"g_clhd_rsegs": 0x20, "g_clhd_csegs": 0x20, "g_clhd_cache": 0x18, "g_clmp_h": 4, "g_clhd_rmap": 0x100,
         "g_clhd_cmap": 0x400, "g_clhd_lut": 0x400, "g_clhd_n": 0x800, "g_clhd_pl": 0x800, "g_clhd_cnt": 0x400}
CODE = ("t_clmp_post", "t_clhd_draw", "t_clhd_zone", "t_clhd_lut", "t_clhd_snap", "t_clmp_col", "t_clmp_pre")
BSS = ("g_clhd_cache", "g_clmp_h", "g_clhd_rmap", "g_clhd_cmap", "g_clhd_lut", "g_clhd_n", "g_clhd_pl", "g_clhd_cnt")
VA = {n: PCAVE2 + o for n, o in SLOTS.items()}
G = 0x00668740
G_PERIOD = 0x0066879C
SON = PCAVE2 + 0x40D40             # g_clmp_son (assemble_commlink_mp.py)
MC_ON, MC_W = PCAVE2 + 0x3F200, PCAVE2 + 0x3F204    # g_mc_on / g_mc_w (assemble_menu_strip.py): 2 = the COMMLINK rail mode
T_MC_COL = PCAVE2 + 0x3F250        # t_mc_col (assemble_menu_strip.py): t_clmp_col's tail for every other mode
HEADER = SL.COMMLINK_HEADER_SPRITE
MAX_W, MAX_H = 0x400, 0x100
MAX_TEXELS = 0x4000                # votes stay < 0x8000 in the 16-bit vote field
ROW_SEGS, COL_SEGS = SL.COMMLINK_HEADER_ROW_SEGS, SL.COMMLINK_HEADER_COL_SEGS


def seg_bytes(segs) -> bytes:
    return bytes(b for n, ln in segs for b in (n, ln))


def asm_post() -> str:
    return f"""
    mov     dword ptr [{SON:#x}], 0
    mov     dword ptr [{MC_ON:#x}], 0
    cmp     dword ptr [{G:#x}], 0x10
    jle     done
    cmp     dword ptr [esp+0x18], {HEADER:#x}
    jne     done
    cmp     dword ptr [{VA['g_clmp_h']:#x}], 0
    jle     done
    push    dword ptr [{VA['g_clmp_h']:#x}]
    push    dword ptr [esp+0x1c]
    push    dword ptr [esp+0x1c]
    push    dword ptr [esp+0x1c]
    push    dword ptr [esp+0x1c]
    push    dword ptr [esp+0x1c]
    push    dword ptr [esp+0x1c]
    call    {VA['t_clhd_draw']:#x}
done:
    ret     0x18
"""


def asm_col() -> str:
    """hm_synth_core's column call (was `call t_mc_col`): g_mc_on == 2 (the COMMLINK rail mode, t_clmp_pre) -> eax =
    g_clhd_cmap[x - dx] (edx = x, [ebp+0xC] = dx, the core's frame); else the tail t_mc_col, stack untouched.
    ebx / ecx / edx / esi / edi kept."""
    return f"""
    cmp     dword ptr [{MC_ON:#x}], 2
    jne     menu
    mov     eax, edx
    sub     eax, dword ptr [ebp+0xc]
    movzx   eax, byte ptr [eax+{VA['g_clhd_cmap']:#x}]
    ret
menu:
    push    {T_MC_COL:#x}
    ret
"""


def asm_pre() -> str:
    """CALL helper at t_clmp_synth's start (before its pushes: [esp+4] the synth's own return, +8 dst, +0xC dx,
    +0x10 dy, +0x14 num, +0x18 den, +0x1C spr): g > 16, the sprite 138 wide and not 6 rows (the title), dx == 0 ->
    g_mc_w = (138 g + 8) >> 4, commlink_zone_map of the column segments over it into g_clhd_cmap (K = (2 g + 15) >> 5),
    g_mc_on = 2 (t_mc_dims takes g_mc_w, t_clmp_col the map); t_clmp_post clears g_mc_on.  eax / ecx / edx clobbered
    (the core's own contract); ebx / esi / edi / ebp kept."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     pre_out
    mov     eax, dword ptr [esp+0x1c]
    cmp     dword ptr [eax+0x10], {SL.COMMLINK_STRIP_COLS}
    jne     pre_out
    cmp     dword ptr [eax+0x14], {SL.COMMLINK_TITLE_ROWS}
    je      pre_out
    cmp     dword ptr [esp+0xc], 0
    jne     pre_out
    mov     eax, dword ptr [{G:#x}]
    imul    eax, eax, {SL.COMMLINK_STRIP_COLS}
    add     eax, 8
    sar     eax, 4
    cmp     eax, {MAX_W:#x}
    jg      pre_out
    mov     dword ptr [{MC_W:#x}], eax
    mov     ecx, dword ptr [{G:#x}]
    lea     ecx, [ecx*2+0xf]
    sar     ecx, 5
    push    {VA['g_clhd_cmap']:#x}
    push    ecx
    push    eax
    push    {len(COL_SEGS)}
    push    {VA['g_clhd_csegs']:#x}
    call    {VA['t_clhd_zone']:#x}
    test    eax, eax
    je      pre_out
    mov     dword ptr [{MC_ON:#x}], 2
pre_out:
    ret
"""


def asm_draw() -> str:
    """Frame: [ebp+8] dst, +0xC dx, +0x10 dy, +0x14 num, +0x18 den, +0x1C spr, +0x20 H."""
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x50
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jle     out
    lea     eax, [eax*2+0xf]
    sar     eax, 5
    mov     dword ptr [ebp-4], eax
    mov     ecx, dword ptr [{G_PERIOD:#x}]
    cmp     ecx, 2
    jl      out
    mov     dword ptr [ebp-8], ecx
    sar     ecx, 1
    mov     dword ptr [ebp-0xc], ecx
    cmp     dword ptr [ebp+0x18], 0
    jle     out
    cmp     dword ptr [ebp+0x14], 0
    jle     out
    mov     esi, dword ptr [ebp+0x1c]
    mov     eax, dword ptr [esi+4]
    test    eax, eax
    je      out
    mov     dword ptr [ebp-0x10], eax
    mov     eax, dword ptr [esi+0xc]
    test    eax, eax
    jle     out
    mov     dword ptr [ebp-0x14], eax
    cmp     dword ptr [esi+0x10], {SL.COMMLINK_HEADER_COLS}
    jne     out
    cmp     dword ptr [esi+0x14], {SL.COMMLINK_HEADER_ROWS}
    jne     out
    movzx   eax, byte ptr [esi+8]
    mov     dword ptr [ebp-0x18], eax
    mov     esi, dword ptr [ebp+8]
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    je      out
    mov     dword ptr [ebp-0x1c], eax
    mov     eax, dword ptr [esi+0x4a8]
    test    eax, eax
    jle     out
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [esi+0x80]
    mov     dword ptr [ebp-0x24], eax
    mov     eax, dword ptr [esi+0x84]
    test    eax, eax
    jge     bh_ok
    neg     eax
bh_ok:
    mov     dword ptr [ebp-0x28], eax
    mov     eax, dword ptr [ebp+0x14]
    imul    eax, eax, {SL.COMMLINK_HEADER_COLS}
    mov     ecx, dword ptr [ebp+0x18]
    mov     edx, ecx
    sar     edx, 1
    add     eax, edx
    xor     edx, edx
    div     ecx
    cmp     eax, 1
    jl      out
    cmp     eax, {MAX_W:#x}
    jg      out
    mov     dword ptr [ebp-0x2c], eax
    mov     eax, dword ptr [ebp+0x20]
    cmp     eax, 1
    jl      out
    cmp     eax, {MAX_H:#x}
    jg      out
    push    {VA['g_clhd_cmap']:#x}
    push    dword ptr [ebp-4]
    push    dword ptr [ebp-0x2c]
    push    {len(COL_SEGS)}
    push    {VA['g_clhd_csegs']:#x}
    call    {VA['t_clhd_zone']:#x}
    test    eax, eax
    je      out
    push    {VA['g_clhd_rmap']:#x}
    push    dword ptr [ebp-4]
    push    dword ptr [ebp+0x20]
    push    {len(ROW_SEGS)}
    push    {VA['g_clhd_rsegs']:#x}
    call    {VA['t_clhd_zone']:#x}
    test    eax, eax
    je      out
    push    dword ptr [ebp+0x10]
    push    dword ptr [ebp+0x20]
    call    {VA['t_clhd_snap']:#x}
    push    dword ptr [ebp-0x18]
    push    {SL.COMMLINK_HEADER_ROWS}
    push    {SL.COMMLINK_HEADER_COLS}
    push    dword ptr [ebp-0x14]
    push    dword ptr [ebp-0x10]
    call    {VA['t_clhd_lut']:#x}
    mov     eax, dword ptr [ebp+0xc]
    test    eax, eax
    jge     xs_ok
    xor     eax, eax
xs_ok:
    mov     dword ptr [ebp-0x30], eax
    mov     eax, dword ptr [ebp+0x10]
    test    eax, eax
    jge     ys_ok
    xor     eax, eax
ys_ok:
    mov     dword ptr [ebp-0x34], eax
    mov     eax, dword ptr [ebp+0xc]
    add     eax, dword ptr [ebp-0x2c]
    cmp     eax, dword ptr [ebp-0x24]
    jle     xe_ok
    mov     eax, dword ptr [ebp-0x24]
xe_ok:
    mov     dword ptr [ebp-0x38], eax
    mov     eax, dword ptr [ebp+0x10]
    add     eax, dword ptr [ebp+0x20]
    cmp     eax, dword ptr [ebp-0x28]
    jle     ye_ok
    mov     eax, dword ptr [ebp-0x28]
ye_ok:
    mov     dword ptr [ebp-0x3c], eax
    mov     eax, dword ptr [ebp-0x38]
    cmp     eax, dword ptr [ebp-0x30]
    jle     out
    mov     eax, dword ptr [ebp-0x3c]
    cmp     eax, dword ptr [ebp-0x34]
    jle     out
    mov     ebx, dword ptr [ebp-0x34]
row:
    mov     eax, ebx
    sub     eax, dword ptr [ebp+0x10]
    movzx   eax, byte ptr [eax+{VA['g_clhd_rmap']:#x}]
    mov     dword ptr [ebp-0x48], eax
    mov     ecx, eax
    and     ecx, 1
    mov     dword ptr [ebp-0x44], ecx
    imul    eax, dword ptr [ebp-0x14]
    add     eax, dword ptr [ebp-0x10]
    mov     esi, eax
    mov     eax, ebx
    xor     edx, edx
    div     dword ptr [ebp-8]
    xor     eax, eax
    cmp     edx, dword ptr [ebp-0xc]
    setge   al
    xor     eax, dword ptr [ebp-0x44]
    mov     dword ptr [ebp-0x40], eax
    mov     edi, ebx
    imul    edi, dword ptr [ebp-0x20]
    add     edi, dword ptr [ebp-0x1c]
    add     edi, dword ptr [ebp-0x30]
    mov     ecx, dword ptr [ebp-0x30]
col:
    mov     eax, ecx
    sub     eax, dword ptr [ebp+0xc]
    movzx   eax, byte ptr [eax+{VA['g_clhd_cmap']:#x}]
    mov     dword ptr [ebp-0x4c], eax
    movzx   eax, byte ptr [esi+eax]
    cmp     eax, dword ptr [ebp-0x18]
    je      skip
    cmp     dword ptr [ebp-0x40], 0
    je      put
    lea     edx, [eax*2]
    add     edx, dword ptr [ebp-0x44]
    movzx   edx, word ptr [edx*2+{VA['g_clhd_lut']:#x}]
    cmp     edx, 0xffff
    je      put
    push    ebx
    push    esi
    mov     ebx, dword ptr [ebp-0x4c]
    cmp     dword ptr [ebp-0x48], 0
    jle     nb_dn
    sub     esi, dword ptr [ebp-0x14]
    cmp     dl, byte ptr [esi+ebx]
    je      nb_yes
    add     esi, dword ptr [ebp-0x14]
nb_dn:
    cmp     dword ptr [ebp-0x48], {SL.COMMLINK_HEADER_ROWS - 1}
    jge     nb_no
    add     esi, dword ptr [ebp-0x14]
    cmp     dl, byte ptr [esi+ebx]
    jne     nb_no
nb_yes:
    mov     eax, edx
nb_no:
    pop     esi
    pop     ebx
put:
    mov     byte ptr [edi], al
skip:
    inc     edi
    inc     ecx
    cmp     ecx, dword ptr [ebp-0x38]
    jl      col
    inc     ebx
    cmp     ebx, dword ptr [ebp-0x3c]
    jl      row
out:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x1c
"""


def asm_snap() -> str:
    """stdcall (h, dy) RET 8: commlink_header_rowmap's snap on g_clhd_rmap (the zone map already in it), P from
    g_stripe_period.  Frame: [ebp+8] h, +0xC dy.  Locals: -4 zs, -8 s, -0xC e, -0x10 ze, -0x14 s2, -0x18 e2,
    -0x1C P, -0x20 lo, -0x24 hi, -0x28 n.  The local helper `snap` (eax = j, ecx = lo, edx = hi -> eax) runs in
    this frame."""
    rm = VA["g_clhd_rmap"]
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x30
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [{G_PERIOD:#x}]
    cmp     eax, 2
    jl      sret
    mov     dword ptr [ebp-0x1c], eax
    mov     dword ptr [ebp-4], -1
    mov     dword ptr [ebp-8], -1
    mov     dword ptr [ebp-0xc], -1
    mov     dword ptr [ebp-0x10], -1
    xor     ecx, ecx
sf:
    cmp     ecx, dword ptr [ebp+8]
    jge     sf_end
    movzx   eax, byte ptr [ecx+{rm:#x}]
    lea     edx, [ecx+1]
    cmp     eax, 5
    jne     sf6
    cmp     dword ptr [ebp-4], 0
    jge     sf_n
    mov     dword ptr [ebp-4], ecx
    jmp     sf_n
sf6:
    cmp     eax, 6
    jne     sf21
    cmp     dword ptr [ebp-8], 0
    jge     sf_n
    mov     dword ptr [ebp-8], ecx
    jmp     sf_n
sf21:
    cmp     eax, 21
    jne     sf22
    mov     dword ptr [ebp-0xc], edx
    jmp     sf_n
sf22:
    cmp     eax, 22
    jne     sf_n
    mov     dword ptr [ebp-0x10], edx
sf_n:
    inc     ecx
    jmp     sf
sf_end:
    cmp     dword ptr [ebp-4], 0
    jl      sret
    cmp     dword ptr [ebp-8], 0
    jl      sret
    cmp     dword ptr [ebp-0xc], 0
    jl      sret
    cmp     dword ptr [ebp-0x10], 0
    jl      sret
    mov     eax, dword ptr [ebp-8]
    mov     ecx, dword ptr [ebp-4]
    mov     edx, dword ptr [ebp-0x10]
    call    snap
    mov     dword ptr [ebp-0x14], eax
    lea     ecx, [eax+2]
    mov     eax, dword ptr [ebp-0xc]
    mov     edx, dword ptr [ebp-0x10]
    call    snap
    mov     dword ptr [ebp-0x18], eax
    sub     eax, dword ptr [ebp-0x14]
    cmp     eax, 2
    jl      sret
    mov     dword ptr [ebp-0x28], eax
    mov     edi, dword ptr [ebp-4]
sw:
    cmp     edi, dword ptr [ebp-0x10]
    jge     sret
    mov     eax, 5
    cmp     edi, dword ptr [ebp-0x14]
    jl      sw_put
    mov     eax, 22
    cmp     edi, dword ptr [ebp-0x18]
    jge     sw_put
    mov     ecx, edi
    sub     ecx, dword ptr [ebp-0x14]
    mov     ebx, dword ptr [ebp-0x28]
    mov     eax, ebx
    dec     eax
    sub     eax, ecx
    cmp     ecx, eax
    jg      sw_r
    lea     eax, [ecx*2+1]
    shl     eax, 4
    xor     edx, edx
    lea     esi, [ebx*2]
    div     esi
    add     eax, 6
    jmp     sw_put
sw_r:
    lea     eax, [eax*2+1]
    shl     eax, 4
    xor     edx, edx
    lea     esi, [ebx*2]
    div     esi
    mov     edx, 21
    sub     edx, eax
    mov     eax, edx
sw_put:
    mov     byte ptr [edi+{rm:#x}], al
    inc     edi
    jmp     sw
sret:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     8
snap:
    mov     dword ptr [ebp-0x20], ecx
    mov     dword ptr [ebp-0x24], edx
    mov     esi, eax
    add     eax, dword ptr [ebp+0xc]
    cdq
    idiv    dword ptr [ebp-0x1c]
    test    edx, edx
    jge     sn_pos
    add     edx, dword ptr [ebp-0x1c]
sn_pos:
    test    edx, edx
    jne     sn_two
    mov     eax, esi
    cmp     eax, dword ptr [ebp-0x20]
    jl      sn_keep
    cmp     eax, dword ptr [ebp-0x24]
    jg      sn_keep
    ret
sn_two:
    mov     ebx, esi
    sub     ebx, edx
    mov     edi, esi
    add     edi, dword ptr [ebp-0x1c]
    sub     edi, edx
    xor     ecx, ecx
    cmp     ebx, dword ptr [ebp-0x20]
    jl      sn_upchk
    cmp     ebx, dword ptr [ebp-0x24]
    jg      sn_upchk
    mov     ecx, 1
sn_upchk:
    xor     eax, eax
    cmp     edi, dword ptr [ebp-0x20]
    jl      sn_pick
    cmp     edi, dword ptr [ebp-0x24]
    jg      sn_pick
    mov     eax, 1
sn_pick:
    test    ecx, ecx
    je      sn_nodown
    test    eax, eax
    je      sn_down
    mov     eax, esi
    sub     eax, ebx
    mov     ecx, edi
    sub     ecx, esi
    cmp     eax, ecx
    jg      sn_up
sn_down:
    mov     eax, ebx
    ret
sn_nodown:
    test    eax, eax
    je      sn_keep
sn_up:
    mov     eax, edi
    ret
sn_keep:
    mov     eax, esi
    ret
"""


def asm_zone() -> str:
    """Frame: [ebp+8] segs, +0xC n, +0x10 dst_n, +0x14 k, +0x18 out.  Locals: -4 big, -8 big len, -0xC R, -0x10 F,
    -0x14 sum of the small fields, -0x18 big width, -0x1C start, -0x20 len."""
    return """
    push    ebp
    mov     ebp, esp
    sub     esp, 0x20
    push    ebx
    push    esi
    push    edi
    xor     ecx, ecx
    xor     ebx, ebx
    xor     edi, edi
    mov     dword ptr [ebp-4], -1
    mov     dword ptr [ebp-8], 0
za:
    cmp     ecx, dword ptr [ebp+0xc]
    jge     za_end
    mov     esi, dword ptr [ebp+8]
    movzx   eax, byte ptr [esi+ecx*2]
    movzx   edx, byte ptr [esi+ecx*2+1]
    test    edx, edx
    je      za_field
    inc     ebx
    jmp     za_next
za_field:
    add     edi, eax
    cmp     eax, dword ptr [ebp-8]
    jle     za_next
    mov     dword ptr [ebp-8], eax
    mov     dword ptr [ebp-4], ecx
za_next:
    inc     ecx
    jmp     za
za_end:
    mov     eax, dword ptr [ebp+0x14]
    imul    eax, ebx
    mov     edx, dword ptr [ebp+0x10]
    sub     edx, eax
    mov     dword ptr [ebp-0xc], edx
    test    edx, edx
    jle     zfail
    test    edi, edi
    jle     zfail
    mov     dword ptr [ebp-0x10], edi
    xor     ecx, ecx
    mov     dword ptr [ebp-0x14], 0
zb:
    cmp     ecx, dword ptr [ebp+0xc]
    jge     zb_end
    cmp     ecx, dword ptr [ebp-4]
    je      zb_next
    mov     esi, dword ptr [ebp+8]
    cmp     byte ptr [esi+ecx*2+1], 0
    jne     zb_next
    movzx   eax, byte ptr [esi+ecx*2]
    call    hdw
    cmp     eax, 1
    jl      zfail
    add     dword ptr [ebp-0x14], eax
zb_next:
    inc     ecx
    jmp     zb
zb_end:
    mov     eax, dword ptr [ebp-0xc]
    sub     eax, dword ptr [ebp-0x14]
    cmp     eax, 1
    jl      zfail
    mov     dword ptr [ebp-0x18], eax
    mov     edi, dword ptr [ebp+0x18]
    xor     ecx, ecx
    mov     dword ptr [ebp-0x1c], 0
zc:
    cmp     ecx, dword ptr [ebp+0xc]
    jge     zok
    mov     esi, dword ptr [ebp+8]
    movzx   eax, byte ptr [esi+ecx*2]
    mov     dword ptr [ebp-0x20], eax
    cmp     byte ptr [esi+ecx*2+1], 0
    je      zc_field
    mov     edx, dword ptr [ebp+0x14]
    mov     eax, dword ptr [ebp-0x1c]
zc_line:
    mov     byte ptr [edi], al
    inc     edi
    dec     edx
    jnz     zc_line
    jmp     zc_next
zc_field:
    cmp     ecx, dword ptr [ebp-4]
    jne     zc_small
    mov     ebx, dword ptr [ebp-0x18]
    jmp     zc_w
zc_small:
    call    hdw
    mov     ebx, eax
zc_w:
    push    ecx
    xor     ecx, ecx
zc_x:
    cmp     ecx, ebx
    jge     zc_xend
    mov     eax, ebx
    dec     eax
    sub     eax, ecx
    cmp     ecx, eax
    jg      zc_right
    lea     eax, [ecx*2+1]
    imul    eax, dword ptr [ebp-0x20]
    xor     edx, edx
    lea     esi, [ebx*2]
    div     esi
    jmp     zc_put
zc_right:
    lea     eax, [eax*2+1]
    imul    eax, dword ptr [ebp-0x20]
    xor     edx, edx
    lea     esi, [ebx*2]
    div     esi
    mov     edx, dword ptr [ebp-0x20]
    dec     edx
    sub     edx, eax
    mov     eax, edx
zc_put:
    add     eax, dword ptr [ebp-0x1c]
    mov     byte ptr [edi], al
    inc     edi
    inc     ecx
    jmp     zc_x
zc_xend:
    pop     ecx
zc_next:
    mov     eax, dword ptr [ebp-0x20]
    add     dword ptr [ebp-0x1c], eax
    inc     ecx
    jmp     zc
zok:
    mov     eax, 1
    jmp     zret
zfail:
    xor     eax, eax
zret:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x14
hdw:
    imul    eax, dword ptr [ebp-0xc]
    shl     eax, 1
    add     eax, dword ptr [ebp-0x10]
    dec     eax
    push    ecx
    mov     ecx, dword ptr [ebp-0x10]
    shl     ecx, 1
    xor     edx, edx
    div     ecx
    pop     ecx
    ret
"""


def asm_lut() -> str:
    """Frame: [ebp+8] art, +0xC pitch, +0x10 w, +0x14 h, +0x18 key.  Locals: -4 hash, -8 k, -0xC v, -0x10 r,
    -0x14 best, -0x18 tie."""
    c = VA["g_clhd_cache"]
    n, pl, cnt, lut = VA["g_clhd_n"], VA["g_clhd_pl"], VA["g_clhd_cnt"], VA["g_clhd_lut"]
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x20
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [ebp+0x10]
    imul    eax, dword ptr [ebp+0x14]
    cmp     eax, {MAX_TEXELS:#x}
    jg      none
    xor     eax, eax
    xor     ecx, ecx
h_r:
    cmp     ecx, dword ptr [ebp+0x14]
    jge     h_done
    mov     esi, ecx
    imul    esi, dword ptr [ebp+0xc]
    add     esi, dword ptr [ebp+8]
    xor     edx, edx
h_c:
    cmp     edx, dword ptr [ebp+0x10]
    jge     h_n
    movzx   ebx, byte ptr [esi+edx]
    rol     eax, 5
    add     eax, ebx
    inc     edx
    jmp     h_c
h_n:
    inc     ecx
    jmp     h_r
h_done:
    mov     dword ptr [ebp-4], eax
    cmp     eax, dword ptr [{c + 0x14:#x}]
    jne     build
    mov     eax, dword ptr [ebp+8]
    cmp     eax, dword ptr [{c:#x}]
    jne     build
    mov     eax, dword ptr [ebp+0xc]
    cmp     eax, dword ptr [{c + 4:#x}]
    jne     build
    mov     eax, dword ptr [ebp+0x10]
    cmp     eax, dword ptr [{c + 8:#x}]
    jne     build
    mov     eax, dword ptr [ebp+0x14]
    cmp     eax, dword ptr [{c + 0xc:#x}]
    jne     build
    mov     eax, dword ptr [ebp+0x18]
    cmp     eax, dword ptr [{c + 0x10:#x}]
    jne     build
    jmp     lret
build:
    mov     edi, {n:#x}
    mov     ecx, 0x200
    xor     eax, eax
    rep     stosd
    xor     ecx, ecx
p1_r:
    cmp     ecx, dword ptr [ebp+0x14]
    jge     p1_done
    mov     esi, ecx
    imul    esi, dword ptr [ebp+0xc]
    add     esi, dword ptr [ebp+8]
    xor     edx, edx
p1_c:
    cmp     edx, dword ptr [ebp+0x10]
    jge     p1_n
    movzx   eax, byte ptr [esi+edx]
    cmp     eax, dword ptr [ebp+0x18]
    je      p1_skip
    lea     eax, [eax*2]
    mov     ebx, ecx
    and     ebx, 1
    add     eax, ebx
    inc     dword ptr [eax*4+{n:#x}]
p1_skip:
    inc     edx
    jmp     p1_c
p1_n:
    inc     ecx
    jmp     p1_r
p1_done:
    mov     dword ptr [ebp-8], 0
p2_k:
    mov     eax, dword ptr [ebp-8]
    cmp     eax, 0x200
    jge     p2_done
    cmp     dword ptr [eax*4+{n:#x}], 0
    jne     p2_count
    mov     dword ptr [eax*4+{pl:#x}], 0xffff
    jmp     p2_next
p2_count:
    mov     edi, {cnt:#x}
    mov     ecx, 0x100
    xor     eax, eax
    rep     stosd
    mov     eax, dword ptr [ebp-8]
    mov     ecx, eax
    shr     ecx, 1
    mov     dword ptr [ebp-0xc], ecx
    and     eax, 1
    mov     dword ptr [ebp-0x10], eax
p2_r:
    mov     ecx, dword ptr [ebp-0x10]
    cmp     ecx, dword ptr [ebp+0x14]
    jge     p2_best
    mov     esi, ecx
    imul    esi, dword ptr [ebp+0xc]
    add     esi, dword ptr [ebp+8]
    xor     edx, edx
p2_c:
    cmp     edx, dword ptr [ebp+0x10]
    jge     p2_rn
    movzx   eax, byte ptr [esi+edx]
    cmp     eax, dword ptr [ebp-0xc]
    jne     p2_cn
    cmp     dword ptr [ebp-0x10], 0
    jle     p2_below
    mov     edi, esi
    sub     edi, dword ptr [ebp+0xc]
    movzx   eax, byte ptr [edi+edx]
    cmp     eax, dword ptr [ebp+0x18]
    je      p2_below
    inc     dword ptr [eax*4+{cnt:#x}]
p2_below:
    mov     eax, dword ptr [ebp-0x10]
    inc     eax
    cmp     eax, dword ptr [ebp+0x14]
    jge     p2_cn
    mov     edi, esi
    add     edi, dword ptr [ebp+0xc]
    movzx   eax, byte ptr [edi+edx]
    cmp     eax, dword ptr [ebp+0x18]
    je      p2_cn
    inc     dword ptr [eax*4+{cnt:#x}]
p2_cn:
    inc     edx
    jmp     p2_c
p2_rn:
    add     dword ptr [ebp-0x10], 2
    jmp     p2_r
p2_best:
    xor     ebx, ebx
    xor     edi, edi
    mov     ecx, 1
p2_u:
    cmp     ecx, 0x100
    jge     p2_store
    mov     eax, dword ptr [ecx*4+{cnt:#x}]
    cmp     eax, dword ptr [ebx*4+{cnt:#x}]
    jl      p2_un
    jg      p2_new
    mov     edi, 1
    jmp     p2_un
p2_new:
    mov     ebx, ecx
    xor     edi, edi
p2_un:
    inc     ecx
    jmp     p2_u
p2_store:
    mov     eax, dword ptr [ebx*4+{cnt:#x}]
    shl     eax, 0x10
    test    edi, edi
    je      p2_nt
    or      eax, 0xffff
    jmp     p2_put
p2_nt:
    or      eax, ebx
p2_put:
    mov     ecx, dword ptr [ebp-8]
    mov     dword ptr [ecx*4+{pl:#x}], eax
p2_next:
    inc     dword ptr [ebp-8]
    jmp     p2_k
p2_done:
    xor     ecx, ecx
p3_k:
    cmp     ecx, 0x200
    jge     p3_done
    mov     word ptr [ecx*2+{lut:#x}], 0xffff
    mov     eax, dword ptr [ecx*4+{pl:#x}]
    movzx   ebx, ax
    cmp     ebx, 0xffff
    je      p3_next
    mov     edx, ecx
    shr     edx, 1
    cmp     ebx, edx
    je      p3_next
    shr     eax, 0x10
    cmp     eax, 2
    jl      p3_next
    cmp     dword ptr [ecx*4+{n:#x}], {SL.SCANICON_MIN_MEMBER}
    jl      p3_next
    lea     esi, [ebx*2]
    mov     eax, ecx
    and     eax, 1
    xor     eax, 1
    add     esi, eax
    cmp     dword ptr [esi*4+{n:#x}], {SL.SCANICON_MIN_MEMBER}
    jl      p3_next
    movzx   eax, word ptr [esi*4+{pl:#x}]
    cmp     eax, edx
    jne     p3_next
    mov     word ptr [ecx*2+{lut:#x}], bx
p3_next:
    inc     ecx
    jmp     p3_k
p3_done:
    mov     eax, dword ptr [ebp+8]
    mov     dword ptr [{c:#x}], eax
    mov     eax, dword ptr [ebp+0xc]
    mov     dword ptr [{c + 4:#x}], eax
    mov     eax, dword ptr [ebp+0x10]
    mov     dword ptr [{c + 8:#x}], eax
    mov     eax, dword ptr [ebp+0x14]
    mov     dword ptr [{c + 0xc:#x}], eax
    mov     eax, dword ptr [ebp+0x18]
    mov     dword ptr [{c + 0x10:#x}], eax
    mov     eax, dword ptr [ebp-4]
    mov     dword ptr [{c + 0x14:#x}], eax
    jmp     lret
none:
    mov     edi, {lut:#x}
    mov     ecx, 0x100
    or      eax, -1
    rep     stosd
    mov     dword ptr [{c:#x}], 0
lret:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x14
"""


SOURCES = {"t_clmp_post": asm_post, "t_clhd_draw": asm_draw, "t_clhd_zone": asm_zone, "t_clhd_lut": asm_lut,
           "t_clhd_snap": asm_snap, "t_clmp_col": asm_col, "t_clmp_pre": asm_pre}
DATA = {"g_clhd_rsegs": seg_bytes(ROW_SEGS), "g_clhd_csegs": seg_bytes(COL_SEGS)}


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b), "disassembly does not cover"
    return b


ABS = {G: "{abs32:g_popup_scale_num}", G_PERIOD: "{abs32:g_stripe_period}", SON: "{abs32:g_clmp_son}",
       MC_ON: "{abs32:g_mc_on}", MC_W: "{abs32:g_mc_w}", T_MC_COL: "{abs32:t_mc_col}"}
for _n in SLOTS:
    if _n.startswith("g_"):
        ABS[VA[_n]] = "{abs32:" + _n + "}"
for _off in (4, 8, 0xC, 0x10, 0x14):
    ABS[VA["g_clhd_cache"] + _off] = None          # interior cells of g_clhd_cache: raw (the patcher has no +off)
REL = {VA[n]: "{rel32:" + n + "}" for n in CODE}


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):
            tgt = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in REL:
                out += [f"{b[i]:02X}", REL[tgt]]
                i += 5
                continue
        if i + 4 <= len(b):
            v = int.from_bytes(b[i:i + 4], "little")
            if ABS.get(v):
                out.append(ABS[v])
                i += 4
                continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def build() -> dict[str, bytes]:
    out = {}
    order = sorted(SLOTS, key=lambda n: SLOTS[n])
    for k, name in enumerate(order):
        limit = SLOTS[order[k + 1]] if k + 1 < len(order) else REGION[1]
        if name in SOURCES:
            b = assemble(SOURCES[name](), VA[name])
        elif name in DATA:
            b = DATA[name]
        else:
            assert SLOTS[name] + SIZES[name] <= limit, name
            continue
        assert SLOTS[name] + len(b) <= limit, f"{name} {len(b)}B overflows its slot"
        out[name] = b
    return out


GROUP = "commlink_mp_spots"
NOTES = {
    "t_clmp_post": "t_clmp_synth's tail (jmp): son := 0; the MP header strip -> t_clhd_draw(dst, dx, dy, num, den, spr, g_clmp_h); RET 0x18",
    "t_clhd_draw": "stdcall (dst, dx, dy, num, den, spr, H) RET 0x1C: the header strip on commlink_zone_map + the scanicon shade (scaling_laws.commlink_header_synth)",
    "t_clhd_zone": "stdcall (segs, n, dst_n, k, out) RET 0x14 -> eax 1/0: scaling_laws.commlink_zone_map",
    "t_clhd_lut": "stdcall (art, pitch, w, h, key) RET 0x14: scaling_laws.scanicon_pair_lut -> g_clhd_lut, cached",
    "t_clmp_col": "hm_synth_core's column call (was t_mc_col): g_mc_on == 2 -> g_clhd_cmap[x - dx], else the tail t_mc_col",
    "t_clmp_pre": "CALL helper at t_clmp_synth's start: a railed COMMLINK strip -> g_mc_w = hm_sc(138), the column zone map, g_mc_on = 2",
    "t_clhd_snap": "stdcall (h, dy) RET 8: commlink_header_rowmap's inner-box snap to whole stripe periods on g_clhd_rmap",
    "g_clhd_rsegs": "COMMLINK_HEADER_ROW_SEGS (len, line) bytes",
    "g_clhd_csegs": "COMMLINK_HEADER_COL_SEGS (len, line) bytes",
    "g_clhd_cache": "t_clhd_lut's cache key: art, pitch, w, h, key, texel hash",
    "g_clmp_h": "t_clmp_synh's H of the current core call (-1 before it)",
    "g_clhd_rmap": "BSS row map (bytes)", "g_clhd_cmap": "BSS column map (bytes)",
    "g_clhd_lut": "BSS pair LUT (512 words, 0xFFFF = none)", "g_clhd_n": "BSS texel counts (512 dwords)",
    "g_clhd_pl": "BSS pluralities (512 dwords: votes << 16 | mate)", "g_clhd_cnt": "BSS vote counts (256 dwords)",
}
M_SYM = (f"  # ==== {GROUP} header symbols (2026-11-07, src assemble_commlink_hdr.py) ====\n",
         f"  # ==== {GROUP} header END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} header (assemble_commlink_hdr.py), 2026-11-07 ====\n",
          f"      # ==== {GROUP} header END ==== cave\n")


def splice(path) -> None:
    """Text-only splice into patches.yaml (CRLF kept), idempotent; anchored after the commlink_mp_spots blocks."""
    import pathlib
    import assemble_commlink_mp as M
    p = pathlib.Path(path)
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    built = build()
    sym = ""
    for n in sorted(SLOTS, key=lambda n: SLOTS[n]):
        size = f", size: {SIZES[n]}" if n in SIZES else ""
        ln = f"({len(built[n])}B) " if n in built else ""
        sym += f"  {n + ':':<31}{{ cave: pcave2, offset: {SLOTS[n]:#x}{size} }}   # {GROUP} {ln}{NOTES[n]}\n"
    cave = "".join(f"      - id: {n}\n        offset: {SLOTS[n]:#x}\n        bytes: \"{to_template(built[n], VA[n])}\"\n"
                   for n in sorted(built, key=lambda n: SLOTS[n]))
    text = M._replace_or_insert(text, M_SYM, sym, f"  # ==== {GROUP} END ==== symbols")
    text = M._replace_or_insert(text, M_CAVE, cave, f"      # ==== {GROUP} END ==== cave")
    p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main() -> int:
    if "--splice" in sys.argv:
        import pathlib
        splice(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
        print("spliced")
        return 0
    for name, b in build().items():
        print(f"  {name}: {SLOTS[name]:#x} {len(b)}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
