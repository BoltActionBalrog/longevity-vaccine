#!/usr/bin/env python
# Keystone assembler for thunk_filedlg_railscale (group filedlg_chrome_rails).
#
# The slide-window metallic side rails are the CHROME painted by slide_show (0x45D440, Thinker name): 4 FIXED-size
# strip sprites (15x529 outer + 8x529 inner per side; Sprites 0x7CFFC4/0x7CFFF0/0x7D001C/0x7D0048) drawn at scale 1/1
# from 4 Sprite_draw_2 call sites at the settle (0x45D82C/0x45D851/0x45D875/0x45D8A9).  Every VANILLA window is
# shorter than the 529px art, so it always covered; a g-scaled window outgrows it.
#
# This CALL-helper replaces `call Sprite_draw_2` at all 4 sites (one helper, the CALL-vs-detour rule).  Entry:
# [esp]=ret [esp+4]=dest [esp+8]=key [esp+0xc]=x [esp+0x10]=y [esp+0x14]=num [esp+0x18]=den; ecx=Sprite* (preserved).
# GATE (g > 16 always):
#   arm A: g_filedlg_active && dest == g_fd_winbuf (the file dialog + every rail-armed slide window);
#   arm B (v2 2026-07-19c, generic console windows): dest != the screen buffer (the slide-loop draws stay native)
#          and the dest canvas is TALLER than the rail art (laws scaling_laws.console_rail_arm).
# Scaled path (v3, 2026-10-17, law scaling_laws.rail_right_strip_x / slide_rail_settled_x): num/den = g,16
#   (thunk_sprite_scale_nn sizes the strip fl(w*g/16)); the thunk computes the window-local DEVICE origin itself and
#   tail-jumps thunk_sprite_scale_nn v2 (origin not rescaled) -- no thunk_scale_nn_v1shim any more:
#     x = fl(A*g/16) + fl(e*g/16)   with   LEFT strips (2x < winW = [dest+0x80]):  A = x (native 0 / 15), e = 0
#                                          RIGHT strips:  A = N - 0x37 (N = fl(winW*16/g)),  e = x - (winW - 0x37)
#     y = fl(y*g/16)   (the settled y args are >= 0: 0, or the outer strips' ceil-descaled v' -- t_slide_rail_s1/s2)
#   Left strips + the inner right strip (e = 0) land exactly where the v2 shim path put them (the shim's trunc-div ==
#   floor for these non-negative args), so every abutting frame/backdrop R that reads railscale's double floor
#   (rail_right_anchor) is untouched.  The OUTER right strip (x = winW - 0x2F, e = 8) now sits DIRECTLY against the
#   inner one: + fl(8g/16) = the inner strip's drawn width -- the way the left pair abuts (outer at 0, inner at
#   fl(15g/16)).  v2 floored (N - 0x2F)*g/16 independently: a see-through column between the right strips whenever
#   the two floors phase apart (odd g; 1600x1200 base-name popup x=1202).  Its right end moves left by <= 1 px (never
#   outward: no new overrun).
#   Tail -> edge-safe output-driven NN (CLIPS to the dest -- the 529*g/16 strip must clip at the window bottom; the
#   engine expand path is the 1-row-OOB trap).  No match -> tail Sprite_draw_2 (byte-identical native).
#   ecx (Sprite*) holds g during the body (push/pop around it); eax/edx clobbered (the engine's own contract).
# v3 also folds the two `g > 16` tests into one: 160 B in place at pcave2+0xC470, ends flush at t_zc_tail 0xC510.
#
# Usage: py assemble_railscale.py   -> print the yaml bytes template + length

from __future__ import annotations

import os
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PCAVE2_VA = 0xA0C000
OFF_THUNK = 0xC470                 # v2 RELOCATED from 0x2560 (2026-07-19c); v3 in place
SLOT_END = 0xC510                  # t_zc_tail
THUNK_VA = PCAVE2_VA + OFF_THUNK   # 0xA18470

G_FLAG = PCAVE2_VA + 0x23A0        # g_filedlg_active
G_WINBUF = PCAVE2_VA + 0x25E0      # g_fd_winbuf (stashed by thunk_filedlg_setflag / the rail-arm wrappers)
G_SCALE = 0x668740                 # g_popup_scale_num
NN = PCAVE2_VA + 0x2150            # thunk_sprite_scale_nn v2 (origin args not rescaled)
SPR_DRAW = 0x5E4B4A                # engine Sprite_draw_2
G_SCREEN = 0x9B7490                # g_screen_buffer object (the slide-loop dest: never arms B)
ART_H = 0x7CFFE0                   # rail sprite 1 canvas h (+0x1C) = 529 native
RIGHT_OFF = 0x37                   # the inner right strip's offset from the canvas right (0x20 gap + 15 + 8)

SYMS = {G_SCALE: "g_popup_scale_num", G_FLAG: "g_filedlg_active", G_WINBUF: "g_fd_winbuf",
        NN: "thunk_sprite_scale_nn", SPR_DRAW: "Sprite_draw_2"}


def asm_railscale() -> str:
    return f"""
    mov  edx, dword ptr [{G_SCALE:#x}]
    cmp  edx, 0x10
    jle  native
    mov  eax, dword ptr [esp + 4]
    cmp  dword ptr [{G_FLAG:#x}], 0
    je   armb
    cmp  eax, dword ptr [{G_WINBUF:#x}]
    je   scaled
armb:
    cmp  eax, {G_SCREEN:#x}
    je   native
    mov  eax, dword ptr [eax + 0x84]
    add  eax, dword ptr [{ART_H:#x}]
    jge  native
scaled:
    push ecx
    mov  ecx, edx
    mov  dword ptr [esp + 0x18], ecx
    push 0x10
    pop  dword ptr [esp + 0x1c]
    mov  eax, dword ptr [esp + 8]
    mov  eax, dword ptr [eax + 0x80]
    mov  edx, dword ptr [esp + 0x10]
    add  edx, edx
    cmp  edx, eax
    jl   left
    sar  edx, 1
    sub  edx, eax
    add  edx, {RIGHT_OFF:#x}
    shl  eax, 4
    push edx
    cdq
    div  ecx
    pop  edx
    sub  eax, {RIGHT_OFF:#x}
    jmp  common
left:
    sar  edx, 1
    mov  eax, edx
    cdq
common:
    imul eax, ecx
    sar  eax, 4
    imul edx, ecx
    sar  edx, 4
    add  eax, edx
    mov  dword ptr [esp + 0x10], eax
    mov  eax, dword ptr [esp + 0x14]
    imul eax, ecx
    sar  eax, 4
    mov  dword ptr [esp + 0x14], eax
    pop  ecx
    push {NN:#x}
    ret
native:
    push {SPR_DRAW:#x}
    ret
"""


def assemble(va: int = THUNK_VA) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm_railscale(), va)
    b = bytes(enc)
    assert OFF_THUNK + len(b) <= SLOT_END, f"railscale v3 {len(b)}B overruns the slot (t_zc_tail @{SLOT_END:#x})"
    return b


def template() -> str:
    import assemble_se as SE
    return SE.templatize(assemble(), THUNK_VA, SYMS)


if __name__ == "__main__":
    b = assemble()
    print(f"thunk_filedlg_railscale v3 @ VA 0x{THUNK_VA:X} (pcave2 + 0x{OFF_THUNK:X})")
    print(f"length = {len(b)} bytes -> ends 0x{OFF_THUNK + len(b):X} (slot end 0x{SLOT_END:X})")
    print(template())
