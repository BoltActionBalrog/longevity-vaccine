#!/usr/bin/env python
# Keystone assembler for thunk_filedlg_frame (P3c: Load/Save dialog frame
# strokes + corner border images, margin-correct).
#
# All 4 file-dialog 9-slice frames are HOLLOW (fill=0, Frida-confirmed) -- the
# dark background is GraphicWin_fill(9), the frames are pure borders. So every
# frame thickens via thunk_box_thick_hollow_flat (no fill -> no banding, no
# devfill). The bug in the first cut was the MARGINS: FileDlg_layout/title apply
# NATIVE inset constants on the (P1-scaled) outer rect, so the inner frame +
# content overdraw the scaled-thick outer border.
#
# This thunk (drop-in for the Buffer_box_sprite call: ecx=destBuf, [esp+4]=&rect,
# [esp+8]=&params, RET 8) scales each frame's insets to match the scaled window:
#   - OUTER (6846b0 main-menu / d690 in-game): cache the rect -> g_fd_outer,
#     then thicken (the outer spans the buffer; no inset to scale).
#   - INNER (d528): for every side  new = outer + (native - outer)*g/16
#     (a coordinate's distance from the corresponding OUTER side scales x g/16;
#      works for L/T (inset inward, positive) and R/B (negative delta) alike).
#     Then push the BOTTOM down popup_scale(3) (button gap) and CACHE the
#     computed rect -> g_fd_inner so the title can be derived concentric to it.
#   - TITLE (d618): derive CONCENTRIC to the cached INNER rect (the faction-
#     picker remedy), NOT relative to the outer. L=innerL+popup_scale(3),
#     T=innerT+popup_scale(3), R=innerR-popup_scale(3) -> channel_L==channel_R
#     ==channel_T by construction, independent of the art's native 15/15-to-outer
#     vs 12/13-to-outer asymmetry (Frida-measured 7px L / 5px R before the fix).
#     BOTTOM is top-anchored: newB = newT + (nativeB - nativeT)*g/16 (scale the
#     band HEIGHT, not the distance to the far edge).
# Then repoint [esp+4] -> g_fd_scratch and tail-jmp hollow_flat. ecx (dest) is
# never touched. Gate g<=16 -> native Buffer_box_sprite (1024 exact no-op).
#
# Regenerate if the cave offset moves (absolute addrs are baked).

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA      = 0xA0C000
OFF_THUNK      = 0x2720
OFF_FD_OUTER   = 0x2900
OFF_FD_SCRATCH = 0x2910
OFF_FD_INNER   = 0x2920

THUNK_VA   = PCAVE2_VA + OFF_THUNK
G_FD_OUTER = PCAVE2_VA + OFF_FD_OUTER
G_FD_SCRA  = PCAVE2_VA + OFF_FD_SCRATCH
G_FD_INNER = PCAVE2_VA + OFF_FD_INNER

G_POPUP_SCALE      = 0x668740
BUFFER_BOX_SPRITE  = 0x5E2DD3
HOLLOW_FLAT        = 0xA0C140   # thunk_box_thick_hollow_flat (pcave2 + 0x140) -- Delta=0, thickens INWARD
HOLLOW             = 0xA0C000   # thunk_box_thick_hollow      (pcave2 + 0x000) -- grows OUTWARD (Delta=(g-16)/8)
G_FACTION_SCRATCH  = 0xA0D010   # g_faction_scratch_rect -- exact-fill source read by thunk_frame_enlarge
G_FC_EXACT         = 0xA0E554   # g_fc_exact flag -- when set, the enlarge fills the EXACT rect (no floor loss)
G_FD_BILINEAR      = 0xA0E940   # g_fd_bilinear flag -- when set, the enlarge resamples BILINEAR (do_outer only)
# OUTER spans the buffer (can't grow outward) -> hollow_flat (inward) + EXACT-FILL (g_fc_exact) so it fills
# the buffer symmetrically (the NN floor-quantize otherwise pulls the right/bottom stroke in). INNER/TITLE
# grow OUTWARD (hollow) into the margin so the thickened stroke doesn't encroach on the content / title text.

PARAMS_OUTER_MM = 0x6846B0   # main-menu outer
PARAMS_OUTER_IG = 0x78D690   # in-game outer
PARAMS_INNER    = 0x78D528   # inner content frame
# anything else (0x78D618) -> title

# Uniform per-side scale: dst[k] = outer[k] + (rect[k]-outer[k])*g/16
# edx=&rect, esi=&g_fd_outer, edi=&g_fd_scratch, ebx=g. eax scratch.
def side(k):
    return f"""
    mov eax, [edx + {k}]
    sub eax, [esi + {k}]
    imul eax, ebx
    sar eax, 4
    add eax, [esi + {k}]
    mov [edi + {k}], eax
"""

asm = f"""
    cmp dword ptr [{G_POPUP_SCALE}], 0x10
    jg scaled
    push {BUFFER_BOX_SPRITE}
    ret

scaled:
    push esi
    push edi
    push ebx
    mov edx, [esp + 0x10]          ; &rect (orig [esp+4] after 3 pushes)
    mov eax, [esp + 0x14]          ; &params
    cmp eax, {PARAMS_OUTER_MM}
    je do_outer
    cmp eax, {PARAMS_OUTER_IG}
    je do_outer
    cmp eax, {PARAMS_INNER}
    je do_inner
    ; fallthrough -> title

do_title:
    ; derive CONCENTRIC to the cached INNER rect (faction-picker remedy): uniform
    ; popup_scale(3) inset L/R/T -> equal channels regardless of art asymmetry.
    mov esi, {G_FD_INNER}
    mov edi, {G_FD_SCRA}
    mov ebx, [{G_POPUP_SCALE}]
    mov eax, 3                     ; ps3 = popup_scale(3) = (3*g)>>4
    imul eax, ebx
    sar eax, 4
    push eax                       ; stash ps3 at [esp] (ecx is the dest buffer -> must NOT be clobbered)
    mov eax, [esi]                 ; L = innerL + ps3
    add eax, [esp]
    mov [edi], eax
    mov eax, [esi + 4]            ; T = innerT + ps3
    add eax, [esp]
    mov [edi + 4], eax
    mov eax, [esi + 8]            ; R = innerR - ps3
    sub eax, [esp]
    mov [edi + 8], eax
    ; bottom: newB = newT + (rectB - rectT)*g/16  (band height from the ORIGINAL rect in edx)
    mov eax, [edx + 0xc]
    sub eax, [edx + 4]
    imul eax, ebx
    sar eax, 4
    add eax, [edi + 4]
    mov [edi + 0xc], eax
    ; EXACT-FILL the title box so it renders flush to its (now concentric) rect
    mov esi, {G_FACTION_SCRATCH}
    mov eax, [edi]
    mov [esi], eax
    mov eax, [edi + 4]
    mov [esi + 4], eax
    mov eax, [edi + 8]
    mov [esi + 8], eax
    mov eax, [edi + 0xc]
    mov [esi + 0xc], eax
    mov dword ptr [{G_FC_EXACT}], 1
    pop eax                        ; discard ps3 -> esp back, [esp+0x10] = &rect
    mov [esp + 0x10], edi          ; repoint &rect -> scratch
    pop ebx
    pop edi
    pop esi
    push {HOLLOW_FLAT}             ; exact-fill pairs with the Delta=0 (flat) variant
    ret

do_inner:
    mov esi, {G_FD_OUTER}
    mov edi, {G_FD_SCRA}
    mov ebx, [{G_POPUP_SCALE}]
    {side(0)}
    {side(4)}
    {side(8)}
    {side(0xc)}
    ; push the inner BOTTOM down by popup_scale(3) (~7px @4K) so the OK/CANCEL buttons clear the bottom stroke
    ; (a genuine EXTRA gap -- the engine lays the buttons ~flush to the inner-bottom; NOT floor-compensation).
    mov eax, 3
    imul eax, ebx
    sar eax, 4
    add [edi + 0xc], eax
    ; cache the computed inner rect -> g_fd_inner (do_title derives the title concentric to it)
    mov esi, {G_FD_INNER}
    mov eax, [edi]
    mov [esi], eax
    mov eax, [edi + 4]
    mov [esi + 4], eax
    mov eax, [edi + 8]
    mov [esi + 8], eax
    mov eax, [edi + 0xc]
    mov [esi + 0xc], eax
    ; EXACT-FILL the inner frame (the faction/outer/title remedy). The NN frame-enlarge floor-quantizes its
    ; output anchored top-LEFT, so the right+bottom strokes render INSET from the rect (top/left land flush).
    ; That inset is LARGE at low g (1600x1200) and ~0 at 4K -- so it ate the content's right margin at 1600
    ; (buttons collided) but was harmless at 4K. A popup_scale(3) push (v9) compensated backwards (more at high
    ; g) and CRUSHED the 4K right channel. Exact-fill instead overrides the enlarge dstW/dstH to the EXACT rect
    ; W x H so all four strokes land flush at ANY g: copy the (bottom-pushed) inner rect -> g_faction_scratch_rect
    ; + set g_fc_exact=1, then tail thunk_box_thick_hollow_flat (Delta=0; exact-fill pairs with the flat variant,
    ; same as outer/title). Content keeps its ~10px margins from the rect on every side, so the inward-thickened
    ; stroke does not encroach (unlike pre-margin-scaling v2).
    mov esi, {G_FACTION_SCRATCH}
    mov eax, [edi]
    mov [esi], eax
    mov eax, [edi + 4]
    mov [esi + 4], eax
    mov eax, [edi + 8]
    mov [esi + 8], eax
    mov eax, [edi + 0xc]
    mov [esi + 0xc], eax
    mov dword ptr [{G_FC_EXACT}], 1
    mov [esp + 0x10], edi
    pop ebx
    pop edi
    pop esi
    push {HOLLOW_FLAT}
    ret

do_outer:
    mov esi, {G_FD_OUTER}
    mov eax, [edx]
    mov [esi], eax
    mov eax, [edx + 4]
    mov [esi + 4], eax
    mov eax, [edx + 8]
    mov [esi + 8], eax
    mov eax, [edx + 0xc]
    mov [esi + 0xc], eax
    mov esi, {G_FACTION_SCRATCH}      ; exact-fill source for the enlarge
    mov eax, [edx]
    mov [esi], eax
    mov eax, [edx + 4]
    mov [esi + 4], eax
    mov eax, [edx + 8]
    mov [esi + 8], eax
    mov eax, [edx + 0xc]
    mov [esi + 0xc], eax
    mov dword ptr [{G_FC_EXACT}], 1   ; enlarge fills the EXACT rect (symmetric, no floor loss)
    mov dword ptr [{G_FD_BILINEAR}], 1 ; ornate edges TEAR under NN at fractional ratios -> resample BILINEAR
    pop ebx
    pop edi
    pop esi
    push {HOLLOW_FLAT}
    ret
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
encoding, _ = ks.asm(asm, THUNK_VA)
b = bytes(encoding)
hexstr = " ".join(f"{x:02X}" for x in b)
lines = [
    f"thunk_filedlg_frame @ VA 0x{THUNK_VA:X} (pcave2 + 0x{OFF_THUNK:X})",
    f"length = {len(b)} bytes  -> ends 0x{OFF_THUNK + len(b):X}",
    f"g_fd_outer   @ 0x{G_FD_OUTER:X} (pcave2 + 0x{OFF_FD_OUTER:X})",
    f"g_fd_scratch @ 0x{G_FD_SCRA:X} (pcave2 + 0x{OFF_FD_SCRATCH:X})",
    "",
    hexstr,
]
out = "\n".join(lines)
with open(r"D:\SmacxUi\work\scripts\filedlg_frame_bytes.txt", "w") as f:
    f.write(out + "\n")
print(out)
