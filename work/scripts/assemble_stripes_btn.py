#!/usr/bin/env python
"""Assembler for the FlatButton / scrollbar-grip stripe regeneration (group button_grip_stripes), 2026-10-04.

Above native scale (g = g_popup_scale_num > 16) every stripe follows the one law: T = scaling_laws.stripe_rows(g)
device rows per member, P = stripe_period(g) = 2T (cell g_stripe_period), the TOP member on dest-buffer rows where
(y mod P) < T.  Three surface families still showed a nearest-neighbour-enlarged 1-row dither (uneven runs):

  (1) arrow FlatButtons (Social Engineering, Design Workshop, base-name prev/next, garrison / HUD unit-row arrows),
  (2) scrollbar thumbs (the grip sprite),
  (3) the HUD MENU / COMMLINK band (1600x1200 AND 3840x2160: the band restripe's probe bails there).

Thunks (pcave2; t_sbt_grip at 0x27B60, t_sbt_zoom proposed at 0x27ED0 -- see SLOTS):
  t_sbt_zoom   drop-in for thunk_keyed_stretch_blit (KSB) at thunk_btn_bandstripe's two blit calls -- the common
               one and the unit-row-arrow one (esi = the FlatButton; ebx = thunk_btn_bandstripe's own match flag:
               1 for MENU / COMMLINK / the BaseWin button range; args (buf, buf, 0, 0, nativeW, nativeH, 0, 0,
               devW, devH, -1), callee-clean RET 0x2C).  For the owned button classes it REPLACES the in-place KSB
               zoom.  Pass 1 classifies the NATIVE canvas: a pixel is dither when it lies in a vertical window of
               four rows A,B,A,B (A != B, neither the canvas key 9); it is rewritten to its pair's top (the
               even-native-row member: skill scaling-frames 7 / hm_synth_core's rule), its bit is set in a stack
               bitmask and bottom[top] is recorded.  Pass 2 is our own centre-sampled NN enlarge, in place (rows
               bottom-up, columns right-to-left: a source pixel is never read after it was overwritten), which
               writes a marked pixel as its pair's top / bottom member by DEST row.  Dither is regenerated, never
               resampled; every other pixel is plain NN.  Detection is per draw and per pixel: every state (idle /
               hover / pressed / disabled / selected) and several pairs in one face are covered by construction.
               On success it returns ebx = 0, so thunk_btn_bandstripe skips its own probe + restripe (the pass
               that bails at g = 25 / 40); anything not owned or not provably safe tail-jumps the KSB with the
               stack and every register untouched = today's path.
  t_sbt_grip   drop-in for thunk_sprite_scale_nn at thunk_sb_thumb's ARMED tail (thiscall ecx = Sprite*; dest, key,
               x, y, num, den; RET 0x18 -- x / y already recentred, num = g, den = 16).  Draws through
               thunk_sprite_scale_nn exactly as today, then rewrites the grip's own pair -- found per draw in the
               NATIVE sprite's mid column -- to the law with restripe_core over exactly the rect
               thunk_sprite_scale_nn wrote (rows clamped to the dest buffer).

g <= 16: t_sbt_zoom tail-jumps the KSB (and is not reached anyway: thunk_btn_shrink arms the zoom only under
g > 16); t_sbt_grip is never reached (thunk_sb_thumb's g <= 16 / unarmed branch still goes to the engine
Sprite_draw_2) -> native no-op.

NOTHING here is live until three tokens inside two EXISTING cave entries are retargeted (see
work/briefs/stripes_btn_findings.md):
  thunk_btn_bandstripe   E8 D7 FD C4 FF (call KSB, +0x94)                     ->  E8 {rel32:t_sbt_zoom}
  thunk_btn_bandstripe   E8 89 26 00 00 (call thunk_arrow_coverage, +0x172)   ->  E8 {rel32:t_sbt_zoom}
  thunk_sb_thumb         68 {abs32:thunk_sprite_scale_nn} C3                  ->  68 {abs32:t_sbt_grip} C3
No call SITE in the exe changes (both hooks sit behind sites that are already patched).

The Python laws at the bottom (btn_dither_marks / btn_synth_zoom / sb_grip_pair / sb_grip_rect / sb_grip_pixel)
are the SPEC these thunks port; they belong in scaling_laws.py (this module may not edit it) and are built only
from scaling_laws primitives (stripe_top, nn_center_index).

Parity: tests/test_stripes_btn_asm_parity.py.  Fragments: `py assemble_stripes_btn.py --fragments`.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
assert PCAVE2 == SE.PCAVE2
GROUP = "button_grip_stripes"

# Placement (cave_map.py, 2026-10-04 23:40).  The assigned run was 0x27B60..0x27E00 (672 B) and the two thunks were
# sized to it (656 B) -- but base_cell_stripes' t_sb_tile2 was baked at 0x27D00..0x27DEB while this module was being
# written, leaving 0x27B60..0x27D00 (416 B): t_sbt_grip (194 B) stays there, t_sbt_zoom (462 B) does not fit and is
# PROPOSED for the free run 0x27ED0..0x28100 (g_dl_mono ends / g_dl_immtab_main starts; 560 B).  Both thunks are
# position independent of each other: move either by editing SLOTS only (re-run cave_map.py --fit first).
SLOTS = {                # name: (offset, exclusive limit)
    "t_sbt_grip": (0x27B60, 0x27D00),
    "t_sbt_zoom": (0x3C600, 0x3C880),   # 2026-10-25 W7H: RELOCATED 0x12A20 -> 0x3C600 (W7H region 0x3C600..0x3CFFF;
                                        # the BaseWin mirror arm outgrew the 0x12A20..0x12C00 slot, now zeros)
    "t_sbt_ph": (0x3FD0, 0x4000),       # 2026-10-15: cave_map --fit 48: 0x3FD0..0x4000 FREE (t_slide_rail_a2 ends / thunk_tutbtn_post)
}

G = 0x00668740           # g_popup_scale_num
KEY9 = 9                 # the FlatButton canvas key (gwfill)
MASK_BYTES = 0x400       # stack bitmask: one bit per native pixel
MAX_NATIVE_PX = MASK_BYTES * 8
QUAD = 4                 # rows of the vertical A,B,A,B window

# ---- the owned FlatButton classes (esi at thunk_btn_2dscale), inclusive [lo, hi] --------------------------------
BTN_STRIDE = 0xB4C
BTN_MENU, BTN_COMMLINK = 0x7B1804, 0x7B2350            # MainWin buttons[3], [4]
BTN_ARROW_FIRST, BTN_ARROW_LAST = 0x7B5080, 0x7B6718   # MainWin buttons[8..10]: unit-row / garrison arrows
BASEWIN_LO, BASEWIN_HI = 0x6B4DE8, 0x6C4670            # BaseWin's 22 FlatButtons (exclusive end)
SE_LO, SE_HI = 0x8AC290, 0x8C4E0C                      # SocialWin+0x6020 + [0..35)*0xB4C (exclusive end)
DW_LO, DW_HI = 0x71FF9C, 0x731DB8                      # the Design Workshop FlatButtons (exclusive end)
# thunk_btn_bandstripe dispatches these three to the coverage filter BEFORE its KSB call (user-approved, a different
# treatment by decision), so they never reach t_sbt_zoom:
EXCLUDED = (0x6C02A8, 0x6C1940, 0x6C248C)              # BaseWin btn16 nerve staple, btn18 / btn19 GOVERNOR chevrons
assert EXCLUDED == tuple(BASEWIN_LO + k * BTN_STRIDE for k in (16, 18, 19)) and BASEWIN_LO + 22 * BTN_STRIDE == BASEWIN_HI
BAND_KSB_CALL_OFF, BAND_ARROW_CALL_OFF = 0x94, 0x172   # the two E8s inside thunk_btn_bandstripe that get retargeted

SYM_NAMES = ("g_popup_scale_num", "g_stripe_period", "thunk_keyed_stretch_blit", "thunk_sprite_scale_nn",
             "restripe_core")
THUNK_ORDER = ("t_sbt_zoom", "t_sbt_grip", "t_sbt_ph")
THUNK_NOTE = {
    "t_sbt_zoom": "KSB drop-in (RET 0x2C) at thunk_btn_bandstripe's two blit calls: owned FlatButtons -> in-place NN enlarge that regenerates every vertical 1-row dither at the stripe law, returns ebx=0; else tail-jump thunk_keyed_stretch_blit",
    "t_sbt_grip": "thunk_sprite_scale_nn drop-in (RET 0x18) at thunk_sb_thumb's armed tail: draw, then restripe the grip sprite's own pair (restripe_core) over the drawn rect",
    "t_sbt_ph": "t_sbt_zoom's frame helper (CALL, on its ebp): [ebp-0x14] = the FlatButton's parent-local top mod P for the esi-owned classes, 0 for the band-match classes (law btn_zoom_stripe_phase)",
}


def load_syms(patches: Path | None = None) -> dict[str, int]:
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["g_popup_scale_num"] == G
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["virtual_addr"]) == PCAVE2
    return out


# ---- asm --------------------------------------------------------------------------------------------------------
# NO comments inside the asm text (keystone hangs on `;`); the notes live here.
#
# t_sbt_zoom.  Entry (esp-relative): +4 buf, +8 buf, +0xC 0, +0x10 0, +0x14 sw, +0x18 sh, +0x1C 0, +0x20 0, +0x24 dw,
# +0x28 dh, +0x2C -1 -- thunk_btn_2dscale pushes the buffer twice, the four origins as `push 0` and the key as
# `push -1`, and thunk_btn_bandstripe re-pushes them verbatim, so those are constants of the one caller chain and are
# not re-checked.  OWNED: ebx != 0 (thunk_btn_bandstripe's match flag = MENU, COMMLINK, the BaseWin range; it sends
# the staple and the chevrons to their coverage filters before this call) or esi in the DW / unit-row-arrow / SE
# ranges (unsigned `esi - lo` against the span).  Every refusal happens BEFORE the frame is built, so `pass` leaves
# the stack and all registers exactly as the caller made them.  Refusals: g <= 16; not owned; sh < 4 (no A,B,A,B
# window fits); not an enlarge on both axes; more native pixels than the bitmask holds (or the product overflows);
# no pixel plane; stride < dw; the dest clip ends before the dest rect (pass 1 rewrites native pixels that pass 2
# must then overwrite, so under a short clip the KSB keeps its own semantics); period cell <= 0 (it is a divisor).
# Frame: pushad, ebp = esp -> args +0x24 buf, +0x34 sw, +0x38 sh, +0x44 dw, +0x48 dh.  Locals: -4 x / j, -8 data,
# -0xC rows left, -0x10 stride, -0x1C bit base (r * sw), -0x20 2*dw; bitmask [ebp-0x424, ebp-0x24); bottom[]
# (indexed by top) [ebp-0x524, ebp-0x424).  The frame is 0x524 B (< one page: no stack probe needed).
# Pass 1, per column, top to bottom: bl = rows left of the current chain, bh = its top.  The window test at row y
# reads rows y..y+3, none rewritten yet (only rows < y were), so it always sees native pixels.  y is even iff
# (sh ^ rows-left) is even -> top = p0 on an even row, else p1.
# Pass 2: j = dh-1..0, r = ((2j+1)*sh) / (2*dh) <= j; i = dw-1..0, c = ((2i+1)*sw) / (2*dw) <= i.  The pixel
# (r, c) is overwritten only by the store at (j, i) = (r, c) itself, which comes after its last read.  bl = 1 on
# a stripe-bottom row: 2 * (j mod P) >= P, which is (j mod P) >= (P+1)>>1 for every P (stripe_top's hN).
# 2026-10-15: j is advanced by [ebp-0x14] (t_sbt_ph, called once after the bitmask clear) = the button's
# parent-local top (Win +0x140 + +0x150) mod P for the esi-owned classes (DW, unit-row arrows, SE) and 0 for the
# band-match classes -- law scaling_laws.btn_zoom_stripe_phase.  Before, every owned face phased from its own row
# 0: the DW slot-strip arrows and the HUD unit-row arrows (same rects, same art, this same path) sat a stripe off
# the console at 4K / 1600 and half a period off at 1080 (shots 20261014-230811 / -230642 / -231218 / -231100 /
# -231506).  -0x14 is a free local (the frame's locals are -4, -8, -0xC, -0x10, -0x1C, -0x20).
# Exit: popad, then ebx = 0 (the caller's `test ebx, ebx / je done` then skips its probe restripe).
# 2026-10-25 W7H (law scaling_laws.btn_zoom_index): a BaseWin face (the caller's esi, [ebp+4] after pushad, in
# [BASEWIN_LO, BASEWIN_HI)) samples both axes MIRROR-symmetrically (scaling_laws.nn_mirror_index: the second half of
# each dest axis is the mirror of the first, c = sw - 1 - centre(dw - 1 - i) = ~centre(m) + sw), flag [ebp-0x18]
# (a free local).  The plain centre map ties at an exact half and split every 1-px edge stroke unevenly: the
# EXPLORE .. CONQUER / GOVERNOR / RENAME / OK / RESOURCE .. PSYCH / facilities faces drew 1 | 2 at g 24 and 2 | 3 at
# g 40 in every state (and SUPPORT's 193-wide hover ring T 2 / B 3 at 4K), the corner notches 1x1 / 2x2 and 2x2 / 3x3.
# Mirrored, every edge run and notch is palindromic; the map stays monotone with c <= i (in-place safe, proved in
# the law's test).  Every other owned class keeps the centre map, byte for byte in effect.
def asm_zoom(s: dict[str, int]) -> str:
    period = s['g_stripe_period']
    return f"""
    cmp dword ptr [{G:#x}], 16
    jle pass
    test ebx, ebx
    jnz go
    mov eax, esi
    sub eax, {DW_LO:#x}
    cmp eax, {DW_HI - DW_LO:#x}
    jb go
    mov eax, esi
    sub eax, {BTN_ARROW_FIRST:#x}
    cmp eax, {BTN_ARROW_LAST - BTN_ARROW_FIRST:#x}
    jbe go
    mov eax, esi
    sub eax, {SE_LO:#x}
    cmp eax, {SE_HI - SE_LO:#x}
    jb go
pass:
    push {s['thunk_keyed_stretch_blit']:#x}
    ret
go:
    mov eax, dword ptr [esp+4]
    mov ecx, dword ptr [esp+0x14]
    mov edx, dword ptr [esp+0x18]
    cmp edx, {QUAD}
    jl pass
    cmp edx, dword ptr [esp+0x28]
    jg pass
    test ecx, ecx
    jle pass
    cmp ecx, dword ptr [esp+0x24]
    jg pass
    imul edx, ecx
    jo pass
    cmp edx, {MAX_NATIVE_PX}
    jg pass
    cmp dword ptr [eax+0x54], 0
    je pass
    mov ecx, dword ptr [esp+0x24]
    cmp dword ptr [eax+0x4A8], ecx
    jl pass
    cmp dword ptr [eax+0x28], ecx
    jl pass
    mov ecx, dword ptr [esp+0x28]
    cmp dword ptr [eax+0x2C], ecx
    jl pass
    cmp dword ptr [{period:#x}], 0
    jle pass
    pushad
    mov ebp, esp
    sub esp, 0x524
    lea edi, [ebp-0x424]
    xor eax, eax
    mov ecx, {MASK_BYTES // 4}
    cld
    rep stosd
    call {PCAVE2 + SLOTS["t_sbt_ph"][0]:#x}
    mov eax, dword ptr [ebp+4]
    sub eax, {BASEWIN_LO:#x}
    cmp eax, {BASEWIN_HI - BASEWIN_LO:#x}
    setb al
    movzx eax, al
    mov dword ptr [ebp-0x18], eax
    mov eax, dword ptr [ebp+0x24]
    mov ecx, dword ptr [eax+0x54]
    mov dword ptr [ebp-8], ecx
    mov ecx, dword ptr [eax+0x4A8]
    mov dword ptr [ebp-0x10], ecx
    and dword ptr [ebp-4], 0
colloop:
    mov esi, dword ptr [ebp-8]
    add esi, dword ptr [ebp-4]
    mov edi, dword ptr [ebp-4]
    xor ebx, ebx
    mov eax, dword ptr [ebp+0x38]
    mov dword ptr [ebp-0xC], eax
rowloop:
    cmp dword ptr [ebp-0xC], {QUAD}
    jl noquad
    mov ecx, dword ptr [ebp-0x10]
    movzx eax, byte ptr [esi]
    movzx edx, byte ptr [esi+ecx]
    cmp al, dl
    je noquad
    cmp al, {KEY9}
    je noquad
    cmp dl, {KEY9}
    je noquad
    cmp al, byte ptr [esi+ecx*2]
    jne noquad
    lea ecx, [ecx+ecx*2]
    cmp dl, byte ptr [esi+ecx]
    jne noquad
    mov ecx, dword ptr [ebp+0x38]
    xor ecx, dword ptr [ebp-0xC]
    test cl, 1
    jz evenrow
    xchg eax, edx
evenrow:
    mov byte ptr [ebp+eax-0x524], dl
    mov bh, al
    mov bl, {QUAD}
noquad:
    test bl, bl
    jz nomark
    dec bl
    mov byte ptr [esi], bh
    bts dword ptr [ebp-0x424], edi
nomark:
    add esi, dword ptr [ebp-0x10]
    add edi, dword ptr [ebp+0x34]
    dec dword ptr [ebp-0xC]
    jnz rowloop
    inc dword ptr [ebp-4]
    mov eax, dword ptr [ebp-4]
    cmp eax, dword ptr [ebp+0x34]
    jl colloop
    mov eax, dword ptr [ebp+0x44]
    add eax, eax
    mov dword ptr [ebp-0x20], eax
    mov eax, dword ptr [ebp+0x48]
    mov dword ptr [ebp-4], eax
jloop:
    dec dword ptr [ebp-4]
    js zdone
    mov eax, dword ptr [ebp-4]
    cmp dword ptr [ebp-0x18], 0
    je rnorm
    mov edx, dword ptr [ebp+0x48]
    dec edx
    sub edx, eax
    cmp eax, edx
    jle rnorm
    lea eax, [edx+edx+1]
    imul eax, dword ptr [ebp+0x38]
    xor edx, edx
    mov ecx, dword ptr [ebp+0x48]
    add ecx, ecx
    div ecx
    not eax
    add eax, dword ptr [ebp+0x38]
    jmp rgot
rnorm:
    lea eax, [eax+eax+1]
    imul eax, dword ptr [ebp+0x38]
    xor edx, edx
    mov ecx, dword ptr [ebp+0x48]
    add ecx, ecx
    div ecx
rgot:
    mov ecx, eax
    imul ecx, dword ptr [ebp+0x34]
    mov dword ptr [ebp-0x1C], ecx
    imul eax, dword ptr [ebp-0x10]
    add eax, dword ptr [ebp-8]
    mov esi, eax
    mov eax, dword ptr [ebp-4]
    add eax, dword ptr [ebp-0x14]
    xor edx, edx
    div dword ptr [{period:#x}]
    add edx, edx
    cmp edx, dword ptr [{period:#x}]
    setge bl
    mov edi, dword ptr [ebp-4]
    imul edi, dword ptr [ebp-0x10]
    add edi, dword ptr [ebp-8]
    mov ecx, dword ptr [ebp+0x44]
iloop:
    dec ecx
    js jloop
    cmp dword ptr [ebp-0x18], 0
    je cnorm
    mov edx, dword ptr [ebp+0x44]
    dec edx
    sub edx, ecx
    cmp ecx, edx
    jle cnorm
    lea eax, [edx+edx+1]
    imul eax, dword ptr [ebp+0x34]
    xor edx, edx
    div dword ptr [ebp-0x20]
    not eax
    add eax, dword ptr [ebp+0x34]
    jmp cgot
cnorm:
    lea eax, [ecx+ecx+1]
    imul eax, dword ptr [ebp+0x34]
    xor edx, edx
    div dword ptr [ebp-0x20]
cgot:
    movzx edx, byte ptr [esi+eax]
    add eax, dword ptr [ebp-0x1C]
    bt dword ptr [ebp-0x424], eax
    jnc store
    test bl, bl
    jz store
    mov dl, byte ptr [ebp+edx-0x524]
store:
    mov byte ptr [edi+ecx], dl
    jmp iloop
zdone:
    mov esp, ebp
    popad
    xor ebx, ebx
    ret 0x2C
"""


# t_sbt_grip.  Entered by thunk_sb_thumb's armed tail (`push t_sbt_grip; ret`) with thunk_sprite_scale_nn's own
# contract: ecx = Sprite*, [esp] the site's return (ScrollBar_draw 0x6067F2, which reloads eax at once: the blit's
# result is dead), +4 dest, +8 key, +0xC x, +0x10 y, +0x14 num (= g), +0x18 den (= 16).  Frame: pushad, ebp = esp
# -> +0x24 dest, +0x28 key, +0x2C x, +0x30 y, +0x34 num, +0x38 den; popad restores every register.  The six args
# are re-pushed and thunk_sprite_scale_nn CALLED (ecx untouched).
# Pair: the first vertical A,B,A,B window in the sprite's mid column (data +4; pitch +0xC, <= 0 -> width +0x10;
# rows +0x14).  edi is advanced one row right after p0 / p1 are loaded, so p2 = [edi+pitch], p3 = [edi+2*pitch].
# ebx counts the windows left, so the window row k = h-3-ebx is even iff (h - ebx) is odd -> top = p0, else p1.
# Rect = thunk_sprite_scale_nn's own placement (law sb_grip_rect), den = 16:
#   rx = x + (iLeftOffset(+0x20) * g >> 4),  rw = iSpriteWidth(+0x10) * g >> 4
#   ry = y + (iTopOffset(+0x24) * g >> 4),   rh = iSpriteHeight(+0x14) * g >> 4
# restripe_core clips rw against stride - rx and returns at once on a non-positive rw / rh, but trusts the rows:
# the pass is DROPPED when rx or ry is negative or ry + rh passes the buffer's last row (H, +0x84, is stored
# negative: ry + rh + H > 0).  Columns in [W, stride) are row padding, never displayed.
def asm_grip(s: dict[str, int]) -> str:
    return f"""
    pushad
    mov ebp, esp
    mov esi, ecx
    push dword ptr [ebp+0x38]
    push dword ptr [ebp+0x34]
    push dword ptr [ebp+0x30]
    push dword ptr [ebp+0x2C]
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    call {s['thunk_sprite_scale_nn']:#x}
    mov edi, dword ptr [esi+4]
    test edi, edi
    jz gdone
    mov eax, dword ptr [esi+0x10]
    mov ecx, dword ptr [esi+0xC]
    test ecx, ecx
    jg gpitch
    mov ecx, eax
gpitch:
    shr eax, 1
    add edi, eax
    mov ebx, dword ptr [esi+0x14]
    sub ebx, {QUAD - 1}
    jle gdone
gscan:
    movzx eax, byte ptr [edi]
    movzx edx, byte ptr [edi+ecx]
    add edi, ecx
    cmp al, dl
    je gnext
    cmp al, byte ptr [edi+ecx]
    jne gnext
    cmp dl, byte ptr [edi+ecx*2]
    je gfound
gnext:
    dec ebx
    jnz gscan
    jmp gdone
gfound:
    mov ecx, dword ptr [esi+0x14]
    sub ecx, ebx
    test cl, 1
    jnz gtop
    xchg eax, edx
gtop:
    push eax
    push edx
    push eax
    mov ecx, dword ptr [ebp+0x34]
    mov eax, dword ptr [esi+0x14]
    imul eax, ecx
    sar eax, 4
    push eax
    mov eax, dword ptr [esi+0x10]
    imul eax, ecx
    sar eax, 4
    push eax
    mov eax, dword ptr [esi+0x24]
    imul eax, ecx
    sar eax, 4
    add eax, dword ptr [ebp+0x30]
    push eax
    mov eax, dword ptr [esi+0x20]
    imul eax, ecx
    sar eax, 4
    add eax, dword ptr [ebp+0x2C]
    push eax
    mov edi, dword ptr [ebp+0x24]
    push edi
    or eax, dword ptr [esp+8]
    js gdrop
    mov eax, dword ptr [esp+8]
    add eax, dword ptr [esp+0x10]
    add eax, dword ptr [edi+0x84]
    jg gdrop
    call {s['restripe_core']:#x}
    jmp gdone
gdrop:
    add esp, 0x20
gdone:
    popad
    ret 0x18
"""


def assemble_all(syms: dict[str, int] | None = None) -> dict[str, tuple[int, bytes]]:
    """{name: (pcave2 offset, bytes)}.  No cross references between the two thunks."""
    s = syms or load_syms()
    layout: dict[str, tuple[int, bytes]] = {}
    for name in THUNK_ORDER:
        off = SLOTS[name][0]
        src = {"t_sbt_zoom": asm_zoom, "t_sbt_grip": asm_grip, "t_sbt_ph": asm_ph}[name](s)
        assert ";" not in src
        layout[name] = (off, SE.assemble(src, PCAVE2 + off))
    return layout


def slot_problems(layout, patches: Path | None = None) -> list[str]:
    """Each thunk inside its slot, and no live cave entry or cave symbol of another module inside a thunk's span."""
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    symtab = ap.build_symbol_table(symbols, caves)
    cave = next(c for c in caves if c["id"] == "pcave2")
    out = []
    for name, (off, b) in layout.items():
        lo, hi = off, off + len(b)
        if not (SLOTS[name][0] <= lo and hi <= SLOTS[name][1]):
            out.append(f"{name}: {lo:#x}..{hi:#x} leaves its slot {SLOTS[name][0]:#x}..{SLOTS[name][1]:#x}")
        for e in cave["contents"]:
            if e["id"] in layout:
                continue
            eo = int(e["offset"])
            n = sum(4 if tok.startswith("{") else 1 for tok in str(e["bytes"]).split())   # every placeholder is 4 B
            if eo < hi and lo < eo + n:
                out.append(f"{name}: {lo:#x}..{hi:#x} overlaps live entry {e['id']} {eo:#x}..{eo + n:#x}")
        for sym, va in symtab.items():
            if sym not in layout and PCAVE2 + lo <= va < PCAVE2 + hi:
                out.append(f"{name}: symbol {sym} ({va - PCAVE2:#x}) lies inside {lo:#x}..{hi:#x}")
    return out


def names_of(layout) -> dict[str, int]:
    return {n: PCAVE2 + o for n, (o, _) in layout.items()}


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def templatize(name: str, b: bytes, va: int, syms: dict[str, int], names: dict[str, int]) -> str:
    table = {v: n for n, v in syms.items()}
    table.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, table)


def roundtrip_problems(layout, syms) -> list[str]:
    """The emitted templates, resolved by the patcher's own ByteTemplate, must reproduce the assembled bytes, and no
    symbol VA may be left as a literal."""
    names = names_of(layout)
    table = dict(syms)
    table.update(names)
    out = []
    for name, (off, b) in layout.items():
        tpl = templatize(name, b, PCAVE2 + off, syms, names)
        got = ap.ByteTemplate(tpl).resolve(PCAVE2 + off, table)
        if bytes(got) != b:
            out.append(f"{name}: template does not round-trip")
        for lit in syms.values():
            if struct.pack("<I", lit).hex().upper() in tpl.replace(" ", ""):
                out.append(f"{name}: literal {lit:#x} left untemplatized")
    return out


# ---- the hooks: two token retargets inside EXISTING cave entries (emitted for review, never applied here) --------
GRIP_SITE_VA = 0x006067ED                                                                # ScrollBar_draw.sb_thumb
GRIP_SITE_ORIG = bytes([0xE8]) + struct.pack("<i", 0x005E4B4A - (GRIP_SITE_VA + 5))      # call Sprite_draw_2
assert hx(GRIP_SITE_ORIG) == "E8 58 E3 FD FF"
RETARGETS = (
    ("thunk_btn_bandstripe", "E8 D7 FD C4 FF", "E8 {rel32:t_sbt_zoom}"),      # +0x94: call thunk_keyed_stretch_blit
    ("thunk_btn_bandstripe", "E8 89 26 00 00", "E8 {rel32:t_sbt_zoom}"),      # +0x172: call thunk_arrow_coverage
    ("thunk_sb_thumb", "68 {abs32:thunk_sprite_scale_nn} C3", "68 {abs32:t_sbt_grip} C3"),
)
# 2026-10-25 W3B (rail scrollbar rework, assemble_rail_sym.py): thunk_sb_thumb's armed tail now pushes t_rsb_grip, which
# re-lays a RAIL-family bar's grip and tail-jumps t_sbt_grip for every other bar (tests/test_rail_sym_asm_parity.py
# proves the pass-through) -- the retarget above is still in force, one hop later.
CHAINED = {("thunk_sb_thumb", "68 {abs32:t_sbt_grip} C3"): "68 {abs32:t_rsb_grip} C3"}


def verify_live() -> list[str]:
    """The one exe site upstream of t_sbt_grip (already patched to thunk_sb_thumb) must still be the pristine call."""
    got = SE.base_exe_bytes(GRIP_SITE_VA, 5)
    return [] if got == GRIP_SITE_ORIG else [f"ScrollBar_draw.sb_thumb @{GRIP_SITE_VA:#x}: base {hx(got)} != {hx(GRIP_SITE_ORIG)}"]


def retarget_problems(patches: Path | None = None) -> list[str]:
    """Each retarget's OLD token must occur exactly once in the live cave entry it edits."""
    _sites, _groups, caves, _symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    out = []
    for entry, old, new in RETARGETS:
        hit = [c for c in cave["contents"] if c["id"] == entry]
        if len(hit) != 1:
            out.append(f"{entry}: {len(hit)} cave entries")
        elif " ".join(str(hit[0]["bytes"]).split()).count(old) != 1:
            live = " ".join(str(hit[0]["bytes"]).split())
            done = new in live or (CHAINED.get((entry, new)) or new) in live
            state = "already retargeted" if done else "old token not found exactly once"
            out.append(f"{entry}: {state}")
    return out


def site_yaml() -> str:
    lines = ["# button_grip_stripes: NO new exe sites.  The hooks are three token retargets inside two existing pcave2",
             "# cave entries (apply by hand; rationale and slack in work/briefs/stripes_btn_findings.md):", "#"]
    for entry, old, new in RETARGETS:
        lines += [f"#   - id: {entry}", f"#       old: {old}", f"#       new: {new}", "#"]
    lines += ["# and the group to add:", "#",
              f"#   - id: {GROUP}", "#     members: []            # no sites; reached via the two retargets above",
              "#     code_caves: [pcave2]"]
    return "\n".join(lines) + "\n"


def main(argv) -> int:
    syms = load_syms()
    layout = assemble_all(syms)
    names = names_of(layout)
    ok = True
    print("; ==== FlatButton / scrollbar-grip stripe regeneration (assemble_stripes_btn.py) ====")
    for p in slot_problems(layout):
        ok = False
        print("; SLOT:", p)
    sym_lines, content_lines = [], []
    for name in THUNK_ORDER:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {GROUP} ({len(b)}B) {THUNK_NOTE[name]}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(name, b, PCAVE2 + off, syms, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x} (slot ends {SLOTS[name][1]:#x}, {SLOTS[name][1] - off - len(b)}B spare)")
    for p in roundtrip_problems(layout, syms):
        ok = False
        print("; TEMPLATE:", p)
    for p in verify_live():
        ok = False
        print("; LIVE MISMATCH:", p)
    for p in retarget_problems():
        print("; RETARGET NOTE:", p)
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_stripes_btn_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_btn_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_btn_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml())
        print("; fragments written to work/patches/_fragment_stripes_btn_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print(site_yaml())
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


# ==== the laws these thunks port (to be moved into scaling_laws.py) ==============================================
def btn_dither_marks(native, key: int = KEY9):
    """Pass 1 of t_sbt_zoom over the native canvas `native` (rows of palette indices).  A pixel is DITHER when it
    lies in a vertical window of four rows A,B,A,B (A != B, neither the key): scaling_laws.column_dither_marks, the
    one column rule (its owning window = the last one starting at or above the row).  The pair's TOP is its
    even-native-row member (skill scaling-frames 7; hm_synth_core's rule): the pixel itself on an even row, else its
    mate.  Returns (canon, marks, bottom): canon = the canvas with every dither pixel replaced by its pair's top,
    marks = set of (y, x), bottom = {top: bottom}, last owning window in column-major scan order wins (the asm's
    table is written per window start; every window owns its start row, so the final entries agree)."""
    sh, sw = len(native), len(native[0])
    canon = [list(r) for r in native]
    marks, bottom = set(), {}
    cm = SL.column_dither_marks(native, key)
    for x in range(sw):
        for y in range(sh):
            mate = cm.get((y, x))
            if mate is None:
                continue
            v = native[y][x]
            top = v if y % 2 == 0 else mate
            bottom[top] = v ^ mate ^ top
            canon[y][x] = top
            marks.add((y, x))
    return canon, marks, bottom


def btn_synth_zoom(native, dw: int, dh: int, g: int, key: int = KEY9, phase: int = 0, mirror: bool = False):
    """t_sbt_zoom's output: the dw x dh canvas.  Centre-sampled NN (scaling_laws.nn_center_index) of the native
    canvas -- MIRROR-symmetric on both axes for a BaseWin face (mirror = scaling_laws.btn_zoom_mirrored(esi), law
    btn_zoom_index, W7H 2026-10-25); a dither pixel is REGENERATED -- its pair's top where
    scaling_laws.stripe_top(dest row, g), else its bottom -- so every stripe is stripe_rows(g) rows of each member on
    the dest-buffer row grid."""
    sh, sw = len(native), len(native[0])
    canon, marks, bottom = btn_dither_marks(native, key)
    out = []
    for j in range(dh):
        r = SL.btn_zoom_index(j, dh, sh, mirror)
        top = SL.stripe_top(j + phase, g)
        row = []
        for i in range(dw):
            c = SL.btn_zoom_index(i, dw, sw, mirror)
            v = canon[r][c]
            if (r, c) in marks and not top:
                v = bottom[v]
            row.append(v)
        out.append(row)
    return out


def btn_zoom_owned(esi: int, band_match: bool = False) -> bool:
    """The FlatButton draws t_sbt_zoom takes at thunk_btn_bandstripe's blit calls: band_match = that thunk's own
    flag (MENU, COMMLINK, the BaseWin range minus staple / chevrons), plus the DW, unit-row-arrow and SE objects."""
    return (band_match or DW_LO <= esi < DW_HI or BTN_ARROW_FIRST <= esi <= BTN_ARROW_LAST or SE_LO <= esi < SE_HI)


def sb_grip_pair(sprite):
    """t_sbt_grip's detection: the first vertical A,B,A,B window (A != B) in the sprite's mid column ->
    (top, bottom) with top = the even-native-row member, or None (a solid / non-dither grip is left alone)."""
    sh, sw = len(sprite), len(sprite[0])
    x = sw >> 1
    for y in range(sh - (QUAD - 1)):
        p0, p1, p2, p3 = (sprite[y + k][x] for k in range(QUAD))
        if p0 != p1 and p0 == p2 and p1 == p3:
            return (p0, p1) if y % 2 == 0 else (p1, p0)
    return None


def sb_grip_rect(x: int, y: int, g: int, *, w: int, h: int, lo: int = 0, to: int = 0, buf_h: int | None = None):
    """thunk_sprite_scale_nn's dest rect at num = g, den = 16 for origin (x, y): blit dims w/h (+0x10/+0x14) floor
    scaled, the sprite's draw offsets lo/to (+0x20/+0x24) floor scaled.  -> (rx, ry, rw, rh), or None when the
    restripe is dropped (negative origin, or the rect passes the buffer's last row)."""
    rx, ry, rw, rh = x + ((lo * g) >> 4), y + ((to * g) >> 4), (w * g) >> 4, (h * g) >> 4
    if rx < 0 or ry < 0 or (buf_h is not None and ry + rh > buf_h):
        return None
    return rx, ry, rw, rh


def sb_grip_pixel(idx: int, y: int, g: int, pair) -> int:
    """Per pixel inside the grip rect: a member of the detected pair becomes top on stripe-top rows / bottom below."""
    if pair is None or idx not in pair:
        return idx
    return pair[0] if SL.stripe_top(y, g) else pair[1]



def asm_ph(s: dict[str, int]) -> str:
    """t_sbt_ph: CALLed by t_sbt_zoom inside its frame (ebp = t_sbt_zoom's pushad base: +4 saved esi = the
    FlatButton, +0x10 saved ebx = thunk_btn_bandstripe's match flag).  Clobbers eax / ecx / edx (dead there).
    P > 0 is guaranteed: t_sbt_zoom refuses a non-positive period cell before building the frame."""
    period = s['g_stripe_period']
    return f"""
    xor ecx, ecx
    cmp dword ptr [ebp+0x10], 0
    jnz phst
    mov edx, dword ptr [ebp+4]
    mov eax, dword ptr [edx+0x140]
    add eax, dword ptr [edx+0x150]
    cdq
    idiv dword ptr [{period:#x}]
    test edx, edx
    jge phpos
    add edx, dword ptr [{period:#x}]
phpos:
    mov ecx, edx
phst:
    mov dword ptr [ebp-0x14], ecx
    ret
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
