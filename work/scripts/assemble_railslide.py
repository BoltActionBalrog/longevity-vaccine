#!/usr/bin/env python
# Keystone assembler for thunk_filedlg_railslide (group filedlg_chrome_rails, PART 3: the slide ANIMATION rail draws).
#
# slide_show (0x45D440) and slide_hide (0x45D970) each have a SECOND set of rail-strip Sprite_draw_2 sites inside their
# animation loops -- distinct from the settled sites thunk_filedlg_railscale covers -- that draw the 4 strips at 1/1
# straight onto the SCREEN buffer 0x9b7490 in SCREEN coords every animation frame:
#   show: 0x45D6BA / 0x45D6DD / 0x45D6FF / 0x45D728        hide: 0x45DC86 / 0x45DCA9 / 0x45DCCE / 0x45DCF9
# Every slide window whose rail gate is armed (g_fd_winbuf = &win+0x444) comes through here: the file dialog
# (thunk_filedlg_setflag), and every thunk_popup_railshow/railhide-wrapped slide -- in-game popups (Popup_show/hide),
# BaseWin, CouncilWin, Datalinks, DiploTalk, DiploWin (multiplayer), SocialWin, DesignWin, PrefWin (both pages), and
# the HQ report window (ReportIf_activate).
#
# CALL-helper at all 8 sites. Entry: [esp]=ret [esp+4]=dest [esp+8]=key [esp+0xc]=x [esp+0x10]=y [esp+0x14]=num(1)
# [esp+0x18]=den(1); ecx=Sprite*; ebp = the slide function's frame (intact at every site).
# GATE: g>16 && g_fd_winbuf!=0 && (g_fd_winbuf-0x444 == [ebp+8] (slide_show) || == esi (slide_hide)). In slide_show
#   the window ptr is [ebp+8] (esi = the slide row); in slide_hide it is esi ([ebp+8] = the step counter). The other
#   register holds a small int, never a window address. g_filedlg_active is unusable (the modal wrappers clear it
#   BEFORE the close animation).
# Caller-frame locals (both functions): L = [-0x1c], T = [-0x18], B = [-0x10] (the window's settled screen rect);
#   A (the outer strips' start row, t_slide_rail_a / _a2) = [-0x24] in slide_show, [-0x38] in slide_hide.
#
# v2 (2026-10-17, laws scaling_laws.slide_rail_anim_x / slide_rail_anim_y / slide_rail_anim_rows): every animation
# frame draws each strip EXACTLY where the settled draw puts it, so the strips no longer jump at the settle.
#   x: d = x - L is the window-local arg (0 / 15 / bufW - 55 / bufW - 47, bufW = [g_fd_winbuf]+0x80); the strip goes
#      to L + slide_rail_settled_x(bufW, d): L + fl(d*g/16) (left, 2d < bufW), or (right, v3 2026-10-17, law
#      rail_right_strip_x) L + fl((fl(bufW*16/g) - 0x37)*g/16) + fl((d - (bufW - 0x37))*g/16) -- the inner right strip
#      at railscale's identical width source + double floor (v4 2026-10-25 W5A: computed by t_bw_railanchor, which
#      gives the BaseWin -- g_fd_winbuf == its canvas -- the mirror anchor A* = pt(726) - Lx instead, law
#      basewin_rail_strip_x, so its animation frames land where t_bw_railscale's settled draw does), the outer one
#      directly against it (v2 floored
#      (N - 0x2F)*g/16 on its own: a see-through column between the right strips at odd g, mid-slide AND settled,
#      fixed in railscale v3 the same day).  v1 ceil-descaled the SCREEN x
#      (Ln = ceil(L*16/g)) and let thunk_scale_nn_v1shim floor (Ln + n) back: fl((Ln + n)*g/16) == L + fl(n*g/16)
#      only for some phases of L, so mid-slide the strips sat 1 px off (1920x1080 report window: a see-through
#      column between the left strips and the inner strip over the frame's first stroke; 1600x1200 also a column
#      between the right strips).  No descale can land outside the window rect any more: the settled positions are
#      inside it by construction.
#   y: the inner strips' y is the slide row (the moving window top) and stays exact (v1 rounded it DOWN by up to
#      ceil(g/16) - 1 rows).  The outer strips' y = max(slide_y, A) starts no higher than the settled outer top
#      A_s = T + fl(ceil((A - T)*16/g)*g/16) (t_slide_rail_s1/s2 + railscale) when A > T: y' = max(y, A_s).
#   drawn through thunk_sprite_scale_nn v2 directly (origin NOT rescaled, num/den = g/16 sizes the strip).
#   BOTTOM CLAMP (vanilla relies on the screen buffer's clip rect = the window rect; scale_nn clips only to the
#     buffer): y' >= B -> no draw (ret 0x18).  v3 (2026-10-17, law slide_rail_anim_rows): save the dest Buffer's
#     height field [dest+0x84] (NEGATIVE, top-down), set it to -min(B, bufH) for the call, re-push copies of the 6
#     args, CALL scale_nn (RET 0x18 cleans the copies; it clips rows to the buffer height), restore, ret 0x18 -- rows
#     = min(fl(H*g/16), B - y'), exactly vanilla's clip and the settled strip.  v2 shrank the Sprite's blit h to
#     fl((B - y')*16/g) instead: fl(that*g/16) < B - y', so a strip reaching B ended 1-3 rows short of it (the last
#     show frame vs the settled draw).  (Strip iTopOffset == 0, as the settled sites prove.)
#   ebx = g, esi = L, edi = the caller frame for the body; all three restored.
# No match / g<=16 -> tail-jump engine Sprite_draw_2 (byte-identical native).
#
# thunk_filedlg_slidehide_disarm (0x33C0) is NOT emitted here any more: its v2 (also zeroes g_rail_sb) lives as yaml
# bytes (pinned by test_filedlg_listbar_parity.py).  v2/v3 of railslide fit the v1 slot 0x3280..0x33BF in place (v3 286 B).
#
# Usage: py assemble_railslide.py            -> print the yaml bytes template + length

from __future__ import annotations

import os
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PCAVE2_VA = 0xA0C000
OFF_SLIDE = 0x3280
SLOT_END = 0x33C0                   # thunk_filedlg_slidehide_disarm
VA_SLIDE = PCAVE2_VA + OFF_SLIDE

G_SCALE = 0x668740                  # g_popup_scale_num
G_WINBUF = PCAVE2_VA + 0x25E0       # g_fd_winbuf
NN = PCAVE2_VA + 0x2150             # thunk_sprite_scale_nn (v2: origin args not rescaled)
SPR_DRAW = 0x5E4B4A                 # engine Sprite_draw_2
SPR_OUTER_L, SPR_OUTER_R = 0x7CFFC4, 0x7D0048   # the 15-px outer strip sprites (slide_show/hide `mov ecx, imm`)
A_SHOW, A_HIDE = -0x24, -0x38       # the A cell in slide_show / slide_hide

RAILANCHOR = PCAVE2_VA + 0x3C3A0    # t_bw_railanchor (W5A v2, assemble_basewin.py): the right inner strip's x --
                                    # the BaseWin's A* = pt(726) - Lx, every other window railscale's double floor

SYMS = {G_SCALE: "g_popup_scale_num", G_WINBUF: "g_fd_winbuf", NN: "thunk_sprite_scale_nn",
        SPR_DRAW: "Sprite_draw_2", RAILANCHOR: "t_bw_railanchor"}


def asm_slide() -> str:
    return f"""
    mov  eax, dword ptr [{G_SCALE:#x}]
    cmp  eax, 0x10
    jle  native
    mov  eax, dword ptr [{G_WINBUF:#x}]
    test eax, eax
    je   native
    lea  edx, [eax - 0x444]
    mov  eax, {A_SHOW & 0xFFFFFFFF:#x}
    cmp  edx, dword ptr [ebp + 8]
    je   matched
    mov  al, {A_HIDE & 0xFF:#x}
    cmp  edx, esi
    jne  native
matched:
    push ebp
    mov  ebp, esp
    push ebx
    push esi
    push edi
    mov  edi, dword ptr [ebp]
    mov  ebx, dword ptr [{G_SCALE:#x}]
    mov  esi, dword ptr [edi - 0x1c]
    mov  eax, dword ptr [edi + eax]
    mov  edx, dword ptr [edi - 0x18]
    cmp  ecx, {SPR_OUTER_L:#x}
    je   outer
    cmp  ecx, {SPR_OUTER_R:#x}
    jne  ydone
outer:
    sub  eax, edx
    jle  ydone
    shl  eax, 4
    add  eax, ebx
    dec  eax
    push edx
    xor  edx, edx
    div  ebx
    imul eax, ebx
    shr  eax, 4
    pop  edx
    add  eax, edx
    cmp  eax, dword ptr [ebp + 0x14]
    jle  ydone
    mov  dword ptr [ebp + 0x14], eax
ydone:
    mov  eax, dword ptr [ebp + 0x10]
    sub  eax, esi
    mov  edx, dword ptr [{G_WINBUF:#x}]
    mov  edx, dword ptr [edx + 0x80]
    add  eax, eax
    cmp  eax, edx
    jl   leftside
    sar  eax, 1
    sub  eax, edx
    add  eax, 0x37
    imul eax, ebx
    sar  eax, 4
    push eax
    call {RAILANCHOR:#x}
    pop  edx
    add  eax, edx
    jmp  xadd
leftside:
    sar  eax, 1
    imul eax, ebx
    sar  eax, 4
xadd:
    add  eax, esi
    mov  dword ptr [ebp + 0x10], eax
    mov  dword ptr [ebp + 0x18], ebx
    mov  dword ptr [ebp + 0x1c], 0x10
    mov  eax, dword ptr [edi - 0x10]
    cmp  eax, dword ptr [ebp + 0x14]
    jle  skipdraw
    mov  edx, dword ptr [ebp + 8]
    push edx
    push dword ptr [edx + 0x84]
    neg  eax
    cmp  eax, dword ptr [edx + 0x84]
    jle  keep
    mov  dword ptr [edx + 0x84], eax
keep:
    push dword ptr [ebp + 0x1c]
    push dword ptr [ebp + 0x18]
    push dword ptr [ebp + 0x14]
    push dword ptr [ebp + 0x10]
    push dword ptr [ebp + 0x0c]
    push dword ptr [ebp + 8]
    call {NN:#x}
    pop  eax
    pop  edx
    mov  dword ptr [edx + 0x84], eax
skipdraw:
    pop  edi
    pop  esi
    pop  ebx
    pop  ebp
    ret  0x18
native:
    push {SPR_DRAW:#x}
    ret
"""


def assemble(va: int = VA_SLIDE) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm_slide(), va)
    b = bytes(enc)
    assert OFF_SLIDE + len(b) <= SLOT_END, f"railslide v3 {len(b)}B overruns the slot (disarm @{SLOT_END:#x})"
    return b


def template() -> str:
    import assemble_se as SE
    return SE.templatize(assemble(), VA_SLIDE, SYMS)


if __name__ == "__main__":
    b = assemble()
    print(f"thunk_filedlg_railslide v3 @ VA 0x{VA_SLIDE:X} (pcave2 + 0x{OFF_SLIDE:X})")
    print(f"length = {len(b)} bytes -> ends 0x{OFF_SLIDE + len(b):X} (slot end 0x{SLOT_END:X})")
    print(template())
