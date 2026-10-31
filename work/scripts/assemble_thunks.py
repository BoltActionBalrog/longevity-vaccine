"""Emit the three menu-strip-scaling thunks as byte strings with relocation
placeholders for the apply_patches.py resolver.

These are hand-assembled. The source assembly lives in this file's
docstrings, accompanied by hex byte sequences. If the asm changes, the bytes
need to change too — there is no auto-assembly.

Layout in the menu_strip_thunks cave (256 bytes reserved at 0x00668000):
   +0x00  scale_uniform              (73 bytes)
   +0x60  thunk_scale_rect_width     (12 bytes)
   +0x80  thunk_strip_blit_stretched (91 bytes)

The `{rel32:NAME}` placeholder is a 4-byte field the patcher computes at
apply time:  bytes = (target_va - (call_va + 5)).to_bytes(4, "little", signed=True)
The token must appear immediately after an `E8` opcode byte. The patcher
locates the E8 by reading the previous byte; if it isn't E8, it errors.

Run via `D:\\SmacxUi\\work\\run-assemble-thunks.bat` — emits a YAML fragment
to stdout, ready to paste into patches.yaml under `code_caves[*].contents`.
"""

import sys


# -----------------------------------------------------------------------------
# scale_uniform — shared helper. EAX in = source dim (assumed >= 0).
# EAX out = source dim * min(ScreenWidth/1024, ScreenHeight/768), rounded down.
# Preserves ECX, EDX, EBX.
#
# Comparison `W*768 vs H*1024` selects the limiting axis without floating
# point. JBE is unsigned (we know both products are positive).
#
# Source:
#   scale_uniform:
#       push ecx                            ; 51
#       push edx                            ; 52
#       push ebx                            ; 53
#       mov  ebx, eax                       ; 8B D8       (save source dim)
#
#       mov  eax, ds:[0x9B7B1C]              ; A1 1C 7B 9B 00   (ScreenWidth)
#       mov  ecx, 768                       ; B9 00 03 00 00
#       mul  ecx                            ; F7 E1       (EDX:EAX = W*768)
#       mov  ecx, eax                       ; 8B C8       (ECX = W*768)
#
#       mov  eax, ds:[0x9B7B20]              ; A1 20 7B 9B 00   (ScreenHeight)
#       mov  edx, 1024                      ; BA 00 04 00 00
#       mul  edx                            ; F7 E2       (EDX:EAX = H*1024)
#
#       cmp  ecx, eax                       ; 3B C8       (W*768 vs H*1024)
#       jbe  .use_w_over_1024                ; 76 12       (short, +0x12 to use_w label)
#
#       ; W*768 > H*1024  =>  W/1024 > H/768  =>  use H/768
#       mov  eax, ds:[0x9B7B20]              ; A1 20 7B 9B 00
#       mov  ecx, ebx                       ; 8B CB
#       mul  ecx                            ; F7 E1       (EDX:EAX = H*dim)
#       mov  ecx, 768                       ; B9 00 03 00 00
#       div  ecx                            ; F7 F1       (EAX = H*dim / 768)
#       jmp  .done                          ; EB 10       (short, +0x10 to done label)
#
#   .use_w_over_1024:
#       mov  eax, ds:[0x9B7B1C]              ; A1 1C 7B 9B 00
#       mov  ecx, ebx                       ; 8B CB
#       mul  ecx                            ; F7 E1       (EDX:EAX = W*dim)
#       mov  ecx, 1024                      ; B9 00 04 00 00
#       div  ecx                            ; F7 F1       (EAX = W*dim / 1024)
#
#   .done:
#       pop  ebx                            ; 5B
#       pop  edx                            ; 5A
#       pop  ecx                            ; 59
#       ret                                 ; C3

SCALE_UNIFORM = (
    "51 52 53 8B D8"
    " A1 1C 7B 9B 00 B9 00 03 00 00 F7 E1 8B C8"
    " A1 20 7B 9B 00 BA 00 04 00 00 F7 E2"
    " 3B C8 76 12"
    " A1 20 7B 9B 00 8B CB F7 E1 B9 00 03 00 00 F7 F1 EB 10"
    " A1 1C 7B 9B 00 8B CB F7 E1 B9 00 04 00 00 F7 F1"
    " 5B 5A 59 C3"
)

# -----------------------------------------------------------------------------
# scale_x / scale_y — the OPENING BACKDROP's per-axis map (laws scaling_laws.opening_map_x / opening_map_y).
# Unlike scale_uniform (min(W/1024, H/768), aspect-preserving) these stretch by the backdrop's own per-axis ratio,
# because the decoration is an overlay on that backdrop (the ONE anamorphic exception): change_opening's
# Buffer_copy_3 @0x589AE8 stretches the art over the whole screen, and the art is the engine's choice on
# ScreenWidth == 800 (deco_art below): xopeningb.pcx 800x600 there, else xopeninga.pcx 1024x768.
#   scale_x(v) = v*ScreenWidth/art_w        scale_y(v) = v*ScreenHeight/art_h
# (2026-10-18 fix 15: was v*W/1024 and v*H/768 on every screen, which shrank the 800x600 planet to 315x600 at
# (538,-168) on a backdrop drawn 1:1.)  SIGNED imul/idiv (truncate toward zero): scale_y maps the 800 planet's
# y = -168.  EAX in / EAX out; ECX/EDX/EBX/ESI/EDI preserved, flags clobbered (the old contract).
#   push ecx ; push edx ; call deco_art            ; ecx = art_w, edx = art_h
#   [scale_y: mov ecx, edx]
#   imul dword [ScreenWidth|ScreenHeight]           ; edx:eax = v * dim
#   idiv ecx ; pop edx ; pop ecx ; ret
SCALE_X = "51 52 E8 {rel32:deco_art} F7 2D 1C 7B 9B 00 F7 F9 5A 59 C3"
SCALE_Y = "51 52 E8 {rel32:deco_art} 8B CA F7 2D 20 7B 9B 00 F7 F9 5A 59 C3"

# -----------------------------------------------------------------------------
# thunk_scale_rect_width — replaces `MOV EAX, 300` at 0x4ADFA5 with a CALL.
# Loads 300, defers to scale_uniform, returns scaled value in EAX.
#
# Source:
#   thunk_scale_rect_width:
#       mov  eax, 300                       ; B8 2C 01 00 00
#       call scale_uniform                  ; E8 {rel32:scale_uniform}
#       ret                                 ; C3

THUNK_SCALE_RECT_WIDTH = "B8 2C 01 00 00 E8 {rel32:strip_px} C3"

# -----------------------------------------------------------------------------
# thunk_strip_blit_stretched — replaces `CALL Buffer_copy_4` at sites A/B/C.
# Translates the 7-arg Buffer_copy_4 frame into a 9-arg Buffer_copy_3 call
# with destination dims scaled uniformly. Also calls Buffer_resize on the
# destination Buffer first so the stretched output fits its DIB
# (the GraphicWin's display Buffer is sized to the strip's intrinsic 354
# pixels wide; without the resize, Buffer_copy_3's StretchBlt would write
# past the allocated pixel storage and crash).
#
# Stack layout on entry (after our `push ebp; mov ebp, esp`):
#   [ebp+0]  = saved ebp        [ebp+8]  = arg1 dest
#   [ebp+4]  = return addr      [ebp+12] = arg2 srcX
#                                [ebp+16] = arg3 srcY
#                                [ebp+20] = arg4 dstX
#                                [ebp+24] = arg5 dstY
#                                [ebp+28] = arg6 srcW
#                                [ebp+32] = arg7 srcH (may be negative)
#
# Source:
#   thunk_strip_blit_stretched:
#       push ebp                            ; 55
#       mov  ebp, esp                       ; 8B EC
#       push ebx                            ; 53                  saved EBX at [ebp-4]
#       push esi                            ; 56                  saved ESI at [ebp-8]
#       push edi                            ; 57                  saved EDI at [ebp-12]
#       sub  esp, 12                        ; 83 EC 0C            locals at [ebp-16..-24]
#       mov  [ebp - 16], ecx                ; 89 4D F0            local: src_this
#                                           ;                     [ebp-20] = scaled_W
#                                           ;                     [ebp-24] = scaled_H
#
#       ; scaled_W = abs(srcW) * scale_uniform()
#       mov  eax, [ebp + 28]                ; 8B 45 1C       (srcW)
#       test eax, eax                       ; 85 C0
#       jns  .w_pos                         ; 79 02
#       neg  eax                            ; F7 D8
#   .w_pos:
#       call scale_uniform                  ; E8 {rel32:scale_uniform}
#       mov  [ebp - 20], eax                ; 89 45 EC
#
#       ; scaled_H = abs(srcH) * scale_uniform()
#       mov  eax, [ebp + 32]                ; 8B 45 20       (srcH)
#       test eax, eax                       ; 85 C0
#       jns  .h_pos                         ; 79 02
#       neg  eax                            ; F7 D8
#   .h_pos:
#       call scale_uniform                  ; E8 {rel32:scale_uniform}
#       mov  [ebp - 24], eax                ; 89 45 E8
#
#       ; Build Buffer_copy_3 frame (right-to-left).
#       push dword ptr [ebp - 24]           ; FF 75 E8       (dstH, scaled)
#       push dword ptr [ebp - 20]           ; FF 75 EC       (dstW, scaled)
#       push dword ptr [ebp + 24]           ; FF 75 18       (dstY)
#       push dword ptr [ebp + 20]           ; FF 75 14       (dstX)
#       push dword ptr [ebp + 32]           ; FF 75 20       (srcH, raw)
#       push dword ptr [ebp + 28]           ; FF 75 1C       (srcW, raw)
#       push dword ptr [ebp + 16]           ; FF 75 10       (srcY)
#       push dword ptr [ebp + 12]           ; FF 75 0C       (srcX)
#       push dword ptr [ebp + 8]            ; FF 75 08       (dest)
#
#       mov  ecx, [ebp - 16]                ; 8B 4D F0       (restore this for thiscall)
#       call Buffer_copy_3                  ; E8 {rel32:Buffer_copy_3}
#
#       add  esp, 12                        ; 83 C4 0C       (reclaim locals)
#       pop  edi                            ; 5F
#       pop  esi                            ; 5E
#       pop  ebx                            ; 5B
#       pop  ebp                            ; 5D
#       ret  28                             ; C2 1C 00       (caller-arg cleanup, 7 dwords)

# -----------------------------------------------------------------------------
# thunk_advance_edi_by_scaled_h — replaces `SUB EDI, [ESI+0x119C]` at the two
# loop-advance sites (0x4ADF2D and 0x4AE176). The original instruction does:
#   EDI -= [ESI+0x119C]  ; where [+0x119C] = -75 (Buffer's neg height)
#   => EDI += 75
# We want EDI += scaled_H (= 210) so strips don't overlap when stacked.
#
# Source:
#   thunk_advance_edi_by_scaled_h:
#       push eax                            ; 50
#       mov  eax, ds:[esi+0x119c]            ; 8B 86 9C 11 00 00
#       neg  eax                             ; F7 D8       (abs: -75 -> 75)
#       call scale_uniform                  ; E8 {rel32:scale_uniform}  (75 -> 210)
#       add  edi, eax                        ; 03 F8       (EDI += 210)
#       pop  eax                             ; 58
#       ret                                  ; C3

THUNK_ADVANCE_EDI_BY_SCALED_H = (
    "50 8B 86 9C 11 00 00 F7 D8 E8 {rel32:strip_px} 03 F8 58 C3"
)

# -----------------------------------------------------------------------------
# thunk_load_strip_w_into_eax — replaces `MOV EAX, [ESI+0x1198]` at 0x4ADE4B.
# Loads strip_W from field, scales, returns in EAX. Used for GraphicWin_init's
# width arg.
#
# Source:
#   thunk_load_strip_w_into_eax:
#       mov  eax, ds:[esi+0x1198]            ; 8B 86 98 11 00 00
#       call scale_uniform                   ; E8 {rel32:scale_uniform}
#       ret                                  ; C3
# Caller's original instr was 6 bytes; replacement is CALL + NOP = 6 bytes,
# the NOP is added at the patch site, not in the thunk.

THUNK_LOAD_STRIP_W_INTO_EAX = (
    "8B 86 98 11 00 00 E8 {rel32:strip_px} C3"
)

# -----------------------------------------------------------------------------
# thunk_load_strip_w_into_edi — replaces `MOV EDI, [ESI+0x1198]` at 0x4ADE25.
# Loads strip_W from field, scales, returns in EDI (NOT EAX) so the caller's
# subsequent `SUB EDX, EDI` uses the scaled value. EAX must be preserved
# because the caller relies on EAX holding an earlier computation (the
# 75*num_items height term).
#
# Source:
#   thunk_load_strip_w_into_edi:
#       push eax                             ; 50
#       mov  eax, ds:[esi+0x1198]            ; 8B 86 98 11 00 00
#       call scale_uniform                   ; E8 {rel32:scale_uniform}
#       mov  edi, eax                        ; 8B F8
#       pop  eax                             ; 58
#       ret                                  ; C3

THUNK_LOAD_STRIP_W_INTO_EDI = (
    # DUAL-PURPOSE (height-from-painted-extent variant): outputs the GraphicWin
    # HEIGHT in EAX and the scaled strip width in EDI. On entry EAX holds the
    # unscaled menu_total_height (75*count [+95]) — IGNORED. Instead we size the
    # window to the *painted* extent so there's no rounding gap at the bottom:
    #     height = count * scale(75)  [+ scale(20) if BL!=0 separator]
    # count = [ESI+0xfcc] (already INC'd for BL!=0). BL flag = [EBP-0x1b0].
    # Downstream: 0x4ADE48 SUB ECX,EAX (Y pos, keeps bottom-anchored) and
    # 0x4ADE4A PUSH EAX (height arg). 0x4ADE37 SUB EDX,EDI (X pos) uses EDI.
    # Clobbers only EAX/EDI (+flags); ECX/EDX reloaded by caller; EBX preserved
    # by scale_uniform.
    "B8 4B 00 00 00"                       # mov eax, 75
    " E8 {rel32:strip_px}"           # EAX = scale(75)
    " 0F AF 86 CC 0F 00 00"                # imul eax, [esi+0xfcc]   ; EAX = count*scale(75)
    " 80 BD 50 FE FF FF 00"                # cmp byte [ebp-0x1b0], 0  ; BL flag
    " 74 0F"                               # jz .nosep  (skip 15 bytes)
    " 50"                                  #   push eax              ; save height
    " B8 14 00 00 00"                      #   mov eax, 20
    " E8 {rel32:strip_px}"           #   EAX = scale(20)
    " 01 04 24"                            #   add [esp], eax        ; height += scale(20)
    " 58"                                  #   pop eax
    # .nosep:
    " 50"                                  # push eax                ; save height
    " 8B 86 98 11 00 00"                   # mov eax, [esi+0x1198]   ; strip_W
    " E8 {rel32:strip_px}"           # EAX = scaled_W
    " 8B F8"                               # mov edi, eax            ; EDI = scaled_W
    " 58"                                  # pop eax                 ; EAX = height
    " C3"                                  # ret
)

# -----------------------------------------------------------------------------
# Win11 24H2 file-lock fix (port of Thinker's fix). The statically-linked MSVC
# CRT's per-FILE locking (_lock_file @ 0x647C37 / _unlock_file @ 0x647C89,
# called from _fwrite/_fread/_fclose/_fseek/_fprintf/_ftell/_fgets/_fgetc/
# _fputc/_rewind) faults on Windows 11 24H2 (crashes when a savegame is
# written -> the hot-seat turn-start hang). We redirect all 20 call sites to a
# single self-contained global lock: a spinlock on one cave dword. No imports,
# no CRT, no init — LOCK CMPXCHG is one instruction; the dword starts 0.
# __cdecl, FILE* arg ignored (global lock), non-recursive (matches Thinker's
# std::mutex; the CRT funcs lock-at-entry/unlock-at-exit with no nesting).

# filelock_lock: acquire the spinlock.
#   push eax ; push ecx
#   .spin: xor eax,eax ; mov ecx,1 ; lock cmpxchg [filelock_var],ecx ; jnz .spin
#   pop ecx ; pop eax ; ret
THUNK_FILELOCK_LOCK = (
    "50 51 33 C0 B9 01 00 00 00 F0 0F B1 0D {abs32:filelock_var} 75 EF 59 58 C3"
)

# filelock_unlock: release (aligned dword store is atomic on x86).
#   mov dword [filelock_var], 0 ; ret
THUNK_FILELOCK_UNLOCK = (
    "C7 05 {abs32:filelock_var} 00 00 00 00 C3"
)

# filelock_var: the lock dword (0 = unlocked). Lives in the cave; padding is 0.
FILELOCK_VAR = "00 00 00 00"

# -----------------------------------------------------------------------------

THUNK_STRIP_BLIT_STRETCHED = (
    "55 8B EC 53 56 57 83 EC 0C 89 4D F0"
    " 8B 45 1C 85 C0 79 02 F7 D8 E8 {rel32:strip_px} 89 45 EC"
    " 8B 45 20 85 C0 79 02 F7 D8 E8 {rel32:strip_px} 89 45 E8"
    " FF 75 E8 FF 75 EC FF 75 18 FF 75 14 FF 75 20 FF 75 1C"
    " FF 75 10 FF 75 0C FF 75 08"
    " 8B 4D F0 E8 {rel32:Buffer_copy_3}"
    " 83 C4 0C 5F 5E 5B 5D C2 1C 00"
)

# -----------------------------------------------------------------------------
# thunk_deco_blit_stretched — replaces `CALL Buffer_copy_4 @ 0x4AE710` (the
# SetupWin per-item DECORATION blit, e.g. the S{1,2,3}L1C1.PCX planet preview on
# the planet-customization screens). Like thunk_strip_blit_stretched (7-arg
# Buffer_copy_4 -> 9-arg Buffer_copy_3, NO resize since dest is the full-screen
# backbuffer) with TWO differences:
#   1. dst dims scaled ANAMORPHICALLY: width via scale_x (*ScreenWidth/1024),
#      height via scale_y (*ScreenHeight/768) — NOT scale_uniform. The deco is an
#      overlay on the full-screen-STRETCHED background (xopeninga.pcx blitted
#      1024x768 -> ScreenWxScreenH at 0x589aed), so it must match that stretch to
#      register with the background's planet slot. Frida-confirmed: background
#      slot at 3840 is x=[2325,3840] (=620*3.75), which scale_x reproduces.
#   2. destination X repositioned to preserve the decoration's right edge:
#        newDstX = dstX + srcW - scaled_W
#      Engine sets dstX = ScreenWidth - srcW, so this yields
#      newDstX = ScreenWidth - scaled_W — correct at ANY resolution, no literal.
#
# Stack on entry (after push ebp; mov ebp,esp): same frame as the strip thunk
#   [ebp+8]=dest [ebp+12]=srcX [ebp+16]=srcY [ebp+20]=dstX [ebp+24]=dstY
#   [ebp+28]=srcW [ebp+32]=srcH(neg);  ECX=src buffer (this)
#
#   ... prologue + scaled_W@[ebp-20] + scaled_H@[ebp-24] identical to strip ...
#   push [ebp-24]        ; dstH (scaled)        FF 75 E8
#   push [ebp-20]        ; dstW (scaled)        FF 75 EC
#   mov  eax, [ebp+24]   ; dstY                 8B 45 18
#   call scale_y ; push eax  ; dstY mapped      E8 .. 50   (fix 15: the 800 art's y = -168 maps by H/600;
#                                                           the 1024 art's y is 0, which every map keeps)
#   mov  eax, [ebp+20]   ; dstX                 8B 45 14
#   add  eax, [ebp+28]   ; + srcW (right edge)  03 45 1C
#   sub  eax, [ebp-20]   ; - scaled_W           2B 45 EC
#   push eax             ; dstX (repositioned)  50
#   push [ebp+32] [ebp+28] [ebp+16] [ebp+12] [ebp+8]   ; srcH srcW srcY srcX dest
#   mov  ecx, [ebp-16] ; call Buffer_copy_3 ; reclaim; ret 28
# Reached only through t_deco_blit_gate (fix 15): a backdrop drawn 1:1 keeps vanilla's Buffer_copy_4.
THUNK_DECO_BLIT_STRETCHED = (
    "55 8B EC 53 56 57 83 EC 0C 89 4D F0"
    " 8B 45 1C 85 C0 79 02 F7 D8 E8 {rel32:scale_x} 89 45 EC"
    " 8B 45 20 85 C0 79 02 F7 D8 E8 {rel32:scale_y} 89 45 E8"
    " FF 75 E8 FF 75 EC"
    " 8B 45 18 E8 {rel32:scale_y} 50"
    " 8B 45 14 03 45 1C 2B 45 EC 50"
    " FF 75 20 FF 75 1C FF 75 10 FF 75 0C FF 75 08"
    " 8B 4D F0 E8 {rel32:Buffer_copy_3}"
    " 83 C4 0C 5F 5E 5B 5D C2 1C 00"
)

# -----------------------------------------------------------------------------
# thunk_deco_soft_update — replaces the GraphicWin_soft_update arg-setup + call
# at 0x4AE715..0x4AE740 (the per-item DECORATION refresh, right after the deco
# blit). The vanilla code refreshes the NATIVE decoration rect:
#   soft_update(X=[ESI+EBX*4+0xA28], Y=[ESI+EBX*4+0xA34], W=[EDI+0x80], H=-[EDI+0x84])
# i.e. (native dstX, dstY, srcW=404, srcH=768). But thunk_deco_blit_stretched now
# draws the planet ANAMORPHICALLY at (dstX+srcW-scale_x(srcW), dstY, scale_x(srcW),
# scale_y(srcH)). The native-size refresh leaves most of the stretched planet
# un-presented, so changing options shows stale rectangles. This thunk refreshes
# the SAME rectangle the blit draws, so the whole planet repaints.  v2 (2026-10-18 fix 15, law
# scaling_laws.opening_deco "refresh"; it runs after EITHER draw, the keyed moons or the opaque planet, so it is
# path-agnostic -- it covers both):
#   H' = scale_y(-[EDI+0x84]);  W' = max(scale_x([EDI+0x80]), [EDI+0x80])
#   Y' = scale_y([ESI+EBX*4+0xA34])                 (the 800 planet's -168 maps by H/600; 0 stays 0)
#   X' = max(0, [ESI+EBX*4+0xA28] + [EDI+0x80] - W')
# Enlarging, W' = scale_x(srcW): the opaque planet's right-held span exactly, and the moons' (x = 0) clamp to
# [0, W') as before.  Shrinking (a screen narrower than its art: W < 1024, != 800) W' = srcW and X' = x: the
# refresh [x, x + srcW) holds the keyed draw [x, x + dw) AND the opaque [x + srcW - dw, x + srcW) (v1 refreshed
# [srcW - dw, srcW) there and left the moons' [0, srcW - dw) unpresented).  On a backdrop drawn 1:1 every map is
# the identity and this IS vanilla's soft_update(x, y, srcW, srcH) (the loader's x is >= 0).
# Frameless: the pushed W' is read back at [esp+4].  Register contract on entry (kept across either draw):
# EDI = deco Buffer, ESI = window, EBX = item index; GraphicWin_soft_update is __thiscall(ECX=[0x945824]),
# RET 0x10.  scale_x/scale_y preserve ECX/EDX/EBX/ESI/EDI, so the [ESI+EBX*4] / [EDI+..] reads stay valid.
# NOTE: [edi+0x80]/[edi+0x84] MUST use disp32 (8B 87 80 00 00 00), NOT disp8
# (8B 47 80) — 0x80/0x84 exceed the signed-byte range so disp8 sign-extends to a
# negative offset, reading the wrong field. The engine's own code uses disp32 here.
THUNK_DECO_SOFT_UPDATE = (
    "8B 87 84 00 00 00 F7 D8 E8 {rel32:scale_y} 50"           # push H' = scale_y(-[edi+0x84])
    " 8B 87 80 00 00 00 E8 {rel32:scale_x}"                   # eax = scale_x([edi+0x80])
    " 3B 87 80 00 00 00 7D 06 8B 87 80 00 00 00 50"           # W' = max(eax, srcW) (jge: keep); push W'
    " 8B 84 9E 34 0A 00 00 E8 {rel32:scale_y} 50"             # push Y' = scale_y([esi+ebx*4+0xA34])
    " 8B 84 9E 28 0A 00 00 03 87 80 00 00 00 2B 44 24 04"     # eax = x + srcW - W'  ([esp+4] = W')
    " 85 C0 79 02 33 C0 50"                                   # X' = max(0, eax); push X'
    " 8B 0D 24 58 94 00 E8 {rel32:GraphicWin_soft_update}"    # ecx=[0x945824]; call (RET 0x10)
    " C3"
)

# =============================================================================
# REUSABLE keyed-anamorphic scaling infrastructure
# =============================================================================
# General-purpose primitive for drawing a transparent (color-keyed) sprite at an
# arbitrary scale to a destination Buffer. Buffer_draw_2 only scales UNIFORMLY
# and Buffer_copy_3 is opaque, so neither alone can do "keyed + non-uniform".
# This does it in two steps through a reusable scratch Buffer:
#   1. Buffer_copy_3 (nearest-neighbour, index-preserving) stretches src -> scratch
#      at the exact dest dims (key index survives the stretch since 8-bit indexed).
#   2. Buffer_draw_2 keyed-blits scratch -> dest 1:1, keying the transparent index.
# Reusable for any future keyed sprite/UI scaling (unit icons, HUD glyphs, etc.).
#
# g_scratch_buf — cave-resident 4-byte slot holding the lazily-created scratch
# Buffer* (NULL until first use). A plain offscreen Buffer (0x588 bytes), NOT a
# GraphicWin (which would spin up a Win_init window / DDraw surface).
G_SCRATCH_BUF = "00 00 00 00"

# thunk_ensure_scratch — returns the scratch Buffer* in EAX, creating it once.
#   if (g_scratch_buf == 0) { p = crt_malloc(0x588); Buffer_ctor(p); g_scratch_buf = p; }
#   return g_scratch_buf
# crt_malloc = __cdecl(size) caller-cleans; Buffer_ctor(0x5D7210) = __thiscall(ECX) near-ret.
# Preserves EBX/ESI/EDI/EBP (only EAX/ECX used; callees are callee-save).
THUNK_ENSURE_SCRATCH = (
    "A1 {abs32:g_scratch_buf}"          # mov eax,[g_scratch_buf]
    " 85 C0 75 1B"                      # test eax,eax ; jnz +0x1B (already created -> ret)
    " 68 88 05 00 00"                   # push 0x588   (sizeof Buffer)
    " E8 {rel32:crt_malloc} 83 C4 04"   # eax = crt_malloc(0x588) ; add esp,4
    " 8B C8 50"                         # mov ecx,eax (this) ; push eax (save across ctor)
    " E8 {rel32:Buffer_ctor} 58"        # Buffer_ctor(this) ; pop eax (restore obj)
    " A3 {abs32:g_scratch_buf}"         # mov [g_scratch_buf],eax
    " C3"                               # ret  (jnz lands here)
)

# thunk_keyed_stretch_blit — THE reusable primitive. __cdecl, RET 0x2C (11 args):
#   keyed_stretch_blit(srcBuf, destBuf, srcX, srcY, srcW, srcH,
#                      dstX, dstY, dstW, dstH, keyColor)
# Stretches src[srcRect] -> scratch[0,0,dstW,dstH] (Buffer_copy_3), then keyed-blits
# scratch -> destBuf at (dstX,dstY) keying keyColor (Buffer_draw_2). Args at [ebp+8..].
THUNK_KEYED_STRETCH_BLIT = (
    "55 8B EC 56"                       # push ebp; mov ebp,esp; push esi
    " E8 {rel32:thunk_ensure_scratch} 8B F0"   # esi = scratch Buffer*
    # Buffer_resize(scratch, dstW, dstH)   [this=ECX, RET 8]
    " FF 75 2C FF 75 28 8B CE E8 {rel32:Buffer_resize}"   # push dstH,dstW; ecx=scratch
    # Buffer_copy_3(src, scratch, srcX,srcY,srcW,srcH, 0,0, dstW,dstH)  [this=src]
    " FF 75 2C FF 75 28 6A 00 6A 00"    # push dstH, dstW, dstY=0, dstX=0
    " FF 75 1C FF 75 18 FF 75 14 FF 75 10"   # push srcH, srcW, srcY, srcX
    " 56 8B 4D 08 E8 {rel32:Buffer_copy_3}"  # push scratch(dest); ecx=srcBuf; call
    # Buffer_draw_2(scratch, destBuf, key, dstX, dstY, 1, 1)  [this=scratch]
    " 6A 01 6A 01 FF 75 24 FF 75 20 FF 75 30 FF 75 0C"   # push 1,1, dstY, dstX, key, destBuf
    " 8B CE E8 {rel32:Buffer_draw_2}"   # ecx=scratch; call
    " 5E 5D C2 2C 00"                   # pop esi; pop ebp; ret 0x2C
)

# thunk_deco_keyed_scaled — replaces the KEYED-deco arg-setup + call at
# 0x4AE6BC..0x4AE6DA (30 bytes). Erosive-forces MOON{1,2,3}.PCX (450x450, key=9):
# cumulative moon-count images that must track the ANAMORPHICALLY-stretched
# background. Calls the reusable keyed_stretch_blit to stretch the whole canvas
# anamorphically (scale_x wide, scale_y tall) with clean keying — no opaque
# magenta-corner artifacts (vs the earlier per-cluster opaque approach).
# Entry: EAX=dest Buffer, EDI=moon, ESI=window, EBX=slot. scale_x/scale_y and
# keyed_stretch_blit all preserve EDI/ESI/EBX, which the following soft_update
# (0x4AE715) needs. [edi+0x80]=srcW, [edi+0x84]=-srcH (disp32!).
# Frame: [ebp-4]=dest, [ebp-8]=dstW, [ebp-0xC]=dstH.
# Reached only through t_deco_keyed_gate (fix 15): a backdrop drawn 1:1 keeps vanilla's Buffer_draw_2.  decoX/Y
# pass unmapped: the loader writes the moons at the art origin (0, 0) on every screen (0x58C524..0x58C542), which
# every map keeps.
THUNK_DECO_KEYED_SCALED = (
    "55 8B EC 83 EC 0C 89 45 FC"        # push ebp;mov ebp,esp;sub esp,0xC; [ebp-4]=dest
    " 8B 87 80 00 00 00 E8 {rel32:scale_x} 89 45 F8"   # dstW = scale_x([edi+0x80])
    " 8B 87 84 00 00 00 F7 D8 E8 {rel32:scale_y} 89 45 F4"  # dstH = scale_y(-[edi+0x84])
    # keyed_stretch_blit(moon, dest, 0,0, srcW, srcH, decoX, decoY, dstW, dstH, 9)
    " 6A 09"                            # key = 9
    " FF 75 F4 FF 75 F8"                # dstH, dstW
    " FF B4 9E 34 0A 00 00"             # dstY = [esi+ebx*4+0xA34]
    " FF B4 9E 28 0A 00 00"             # dstX = [esi+ebx*4+0xA28]
    " 8B 87 84 00 00 00 F7 D8 50"       # srcH = -[edi+0x84]
    " FF B7 80 00 00 00"                # srcW = [edi+0x80]
    " 6A 00 6A 00"                      # srcY=0, srcX=0
    " FF 75 FC 57"                      # destBuf=[ebp-4], srcBuf=edi(moon)
    " E8 {rel32:thunk_keyed_stretch_blit}"   # RET 0x2C cleans 11 args
    " 8B E5 5D C3"                      # mov esp,ebp; pop ebp; ret
)

# =============================================================================
# THE DECORATION FOLLOWS THE BACKDROP (2026-10-18 fix 15; law scaling_laws.opening_art / opening_backdrop_native /
# opening_deco).  pcave2 0x13C0..0x1443 (cave_map.py --fit: the free 0x13B3..0x1450 gap).
# =============================================================================
# deco_art -- the art change_opening stretches over the screen: ECX = art_w, EDX = art_h.  The engine's own test
# (0x58E422 `cmp eax, edi(0x320)`): ScreenWidth == 800 -> (x)openingb.pcx 800x600, else (x)openinga.pcx 1024x768.
# Clobbers ECX/EDX + flags only.
#   mov ecx, 0x400 ; mov edx, 0x300
#   cmp dword [ScreenWidth], 0x320 ; jne .r
#   mov ecx, 0x320 ; mov edx, 0x258
#   .r: ret
DECO_ART = (
    "B9 00 04 00 00 BA 00 03 00 00"
    " 81 3D 1C 7B 9B 00 20 03 00 00 75 0A"
    " B9 20 03 00 00 BA 58 02 00 00"
    " C3"
)

# deco_native -- ZF = 1 iff the backdrop is drawn 1:1 (ScreenWidth x ScreenHeight == the art: 800x600, 1024x768).
# Every GPR preserved.
#   push ecx ; push edx ; call deco_art
#   cmp ecx, [ScreenWidth] ; jne .o ; cmp edx, [ScreenHeight]
#   .o: pop edx ; pop ecx ; ret
DECO_NATIVE = (
    "51 52 E8 {rel32:deco_art}"
    " 3B 0D 1C 7B 9B 00 75 06 3B 15 20 7B 9B 00"
    " 5A 59 C3"
)

# t_deco_blit_gate -- the opaque deco blit CALL @0x4AE710 (Buffer_copy_4(dest, 0, 0, x, y, srcW, srcH), ECX = the
# deco).  Backdrop 1:1: tail-jump vanilla's Buffer_copy_4; else thunk_deco_blit_stretched.  Entered by CALL; the
# return address and the 7 args stay where the caller put them, so either target returns straight to the caller.
#   call deco_native ; jne .s ; push Buffer_copy_4 ; ret
#   .s: push thunk_deco_blit_stretched ; ret
T_DECO_BLIT_GATE = (
    "E8 {rel32:deco_native} 75 06"
    " 68 {abs32:Buffer_copy_4} C3"
    " 68 {abs32:thunk_deco_blit_stretched} C3"
)

# t_deco_keyed_gate -- the keyed deco site @0x4AE6BC (EAX = dest Buffer, EDI = deco, ESI = window, EBX = slot).
# Backdrop 1:1: vanilla's own 0x4AE6BC..0x4AE6D9, byte for byte (Buffer_draw_2(dest, 9, x, y, 1, 1), ECX = deco);
# else tail-jump thunk_deco_keyed_scaled (entered by CALL, returns to the site).
#   call deco_native ; je .n ; push thunk_deco_keyed_scaled ; ret
#   .n: mov ecx, [esi+ebx*4+0xA34] ; mov edx, [esi+ebx*4+0xA28]
#   push 1 ; push 1 ; push ecx ; push edx ; push 9 ; push eax ; mov ecx, edi ; call Buffer_draw_2 ; ret
T_DECO_KEYED_GATE = (
    "E8 {rel32:deco_native} 74 06"
    " 68 {abs32:thunk_deco_keyed_scaled} C3"
    " 8B 8C 9E 34 0A 00 00 8B 94 9E 28 0A 00 00"
    " 6A 01 6A 01 51 52 6A 09 50 8B CF E8 {rel32:Buffer_draw_2}"
    " C3"
)

# (id, pcave2 offset, body)
DECO_BACKDROP_ENTRIES = (
    ("deco_art",          0x13C0, DECO_ART),
    ("deco_native",       0x13E8, DECO_NATIVE),
    ("t_deco_blit_gate",  0x1400, T_DECO_BLIT_GATE),
    ("t_deco_keyed_gate", 0x1418, T_DECO_KEYED_GATE),
)

# -----------------------------------------------------------------------------
# thunk_push_scaled_font — replaces the 6 bytes at 0x4ADC8E:
#   PUSH 0x12 ; PUSH EDX ; LEA ECX,[EBP-0x44]     (6A 12 52 8D 4D BC)
# with `CALL thunk_push_scaled_font` + NOP. The caller has already done, just
# before our patch region:
#   0x4ADC86  MOV EDX, [0x691B2C]    (font resource ptr)
#   0x4ADC8C  PUSH 1                 (Font_init flag arg)
# so on entry EDX=resource and the stack top is [retaddr=0x4ADC93],[1].
# Font glyph size 18 is replaced by scale_uniform(18) at runtime.
#
# Register-only (no scratch memory). scale_uniform preserves ECX/EDX/EBX, so
# we stash the return address in ECX across the call. The caller's EBX (=0,
# live: read by CMP at 0x4ADCBF) is never touched.
#
#   thunk_push_scaled_font:                ; EDX=resource; stack: [ret],[1]
#       pop  ecx                           ; 59          ECX=ret; stack: [1]
#       mov  eax, 0x12                     ; B8 12 00 00 00   (font size 18)
#       call scale_uniform                 ; E8 {rel32}  EAX=scaled; ECX/EDX/EBX kept
#       push eax                           ; 50          [size],[1]
#       push edx                           ; 52          [resource],[size],[1]
#       push ecx                           ; 51          [ret],[resource],[size],[1]
#       lea  ecx, [ebp-0x44]               ; 8D 4D BC    ECX=&Font (this)
#       ret                                ; C3          -> 0x4ADC93 (NOP) -> CALL Font_init
THUNK_PUSH_SCALED_FONT = (
    "59 B8 12 00 00 00 E8 {rel32:strip_px} 50 52 51 8D 4D BC C3"
)

# -----------------------------------------------------------------------------
# thunk_spot_h_into_edi — replaces `MOV EDI,[ESI+0x119C]` at 0x4AE042 (6 bytes),
# the spot-add loop's INITIAL Y/height setup. [+0x119C] = -75; we return the
# scaled negative height (-210) so the spot rects become 210 tall / 210-spaced,
# matching the scaled strip backgrounds. EAX is LIVE here (carries the X-right
# term, used at 0x4AE052 ADD EAX,EBX), so we preserve it.
#
#   thunk_spot_h_into_edi:
#       push eax                           ; 50
#       mov  eax, [esi+0x119c]             ; 8B 86 9C 11 00 00   (-75)
#       neg  eax                           ; F7 D8               (75)
#       call scale_uniform                 ; E8 {rel32}          (210)
#       neg  eax                           ; F7 D8               (-210)
#       mov  edi, eax                      ; 8B F8
#       pop  eax                           ; 58
#       ret                                ; C3
THUNK_SPOT_H_INTO_EDI = (
    "50 8B 86 9C 11 00 00 F7 D8 E8 {rel32:strip_px} F7 D8 8B F8 58 C3"
)

# -----------------------------------------------------------------------------
# thunk_spot_h_into_eax — replaces `MOV EAX,[ESI+0x119C]` at 0x4AE08D (6 bytes),
# the spot-add loop's per-item Y STEP. Same -scaled-height result, but EAX is
# the target (the caller NEGs it at 0x4AE099 then adds to Y_top/Y_bottom), so
# we return -210 directly in EAX. Nothing else live needs preserving.
#
#   thunk_spot_h_into_eax:
#       mov  eax, [esi+0x119c]             ; 8B 86 9C 11 00 00
#       neg  eax                           ; F7 D8
#       call scale_uniform                 ; E8 {rel32}
#       neg  eax                           ; F7 D8
#       ret                                ; C3
THUNK_SPOT_H_INTO_EAX = (
    "8B 86 9C 11 00 00 F7 D8 E8 {rel32:strip_px} F7 D8 C3"
)

# -----------------------------------------------------------------------------
# thunk_text_fullrect — replaces `CALL Buffer_write_cent_l_7` at 0x4AE642.
# Buffer_write_cent_l_7 centers the text BOTH axes within the rect it is given
# (verified: text_Y = top + (rect_height - font_height)/2). draw_item passes a
# 22px band pinned near the strip top (rect.top = spot.top + 0x21). We rewrite
# the rect IN PLACE to span the full scaled strip, then tail-jump into the real
# function, so centering uses only runtime-scaled inputs (strip height via
# scale_uniform, font height via the font thunk) — resolution-independent.
#
# On entry (our CALL replaces the original): stack = [ret=0x4AE647],[str],
# [&rect],[len]; ECX = the draw buffer (this, needed by write_cent); EBX = item
# index (LIVE after, used by the decoration block) — left untouched.
# rect.top currently = spot.top + 0x21 (vanilla 0x1f + 2, never scaled), so
# subtracting 0x21 recovers spot.top exactly at any resolution.
# write_cent is original code at a fixed address (0x5DD130); we reach it via an
# absolute `MOV EAX,imm32 ; JMP EAX` (the {rel32} placeholder only follows E8).
#
#   thunk_text_fullrect:
#       mov  edx, [esp+0x08]               ; 8B 54 24 08   EDX=&rect
#       mov  eax, [edx+0x04]               ; 8B 42 04      rect.top (= spot.top+0x21)
#       sub  eax, 0x21                     ; 83 E8 21      spot.top
#       mov  [edx+0x04], eax               ; 89 42 04      rect.top = spot.top
#       mov  eax, 0x4B                     ; B8 4B 00 00 00   (75)
#       call scale_uniform                 ; E8 {rel32}    EAX=scaled height (210); EDX kept
#       add  eax, [edx+0x04]               ; 03 42 04      EAX = spot.top + 210
#       mov  [edx+0x0c], eax               ; 89 42 0C      rect.bottom = spot.top + 210
#       mov  eax, 0x005DD130               ; B8 30 D1 5D 00   Buffer_write_cent_l_7
#       jmp  eax                           ; FF E0         tail call; its RET 0xC returns to 0x4AE647
# NOTE (2026-05-29): now centers in the SCALED VANILLA BAND
# {spot.top+scale(0x21), spot.top+scale(0x37)} (~59% down, matching vanilla's
# position in the flat label area) rather than the full strip (50% center, read
# as too high). spot.top is held on [esp] across both scale_uniform calls.
#   mov edx,[esp+8]; mov eax,[edx+4]; sub eax,0x21        ; EDX=&rect, EAX=spot.top
#   push eax                                              ; save spot.top
#   mov eax,0x21; call scale_uniform; add eax,[esp]; mov [edx+4],eax   ; band top
#   mov eax,0x37; call scale_uniform; add eax,[esp]; mov [edx+0xc],eax ; band bottom
#   pop eax; mov eax,0x5DD130; jmp eax                    ; tail-call write_cent
THUNK_TEXT_FULLRECT = (
    "8B 54 24 08 8B 42 04 83 E8 21 50"
    " B8 21 00 00 00 E8 {rel32:strip_px} 03 04 24 89 42 04"
    " B8 37 00 00 00 E8 {rel32:strip_px} 03 04 24 89 42 0C"
    " 58 B8 30 D1 5D 00 FF E0"
)

# -----------------------------------------------------------------------------
# thunk_spot_h_into_ecx — replaces `MOV ECX,[ESI+0x119C]` at 0x4ADF95, the spot
# height source for the MAIN-MENU (BL==0) path. The branch at 0x4ADFBC
# (JZ 0x4AE063) skips the 0x4AE042 init thunk, so spot height comes from here:
# ECX=[+0x119C]=-75, NEG at 0x4ADFA1 -> 75 -> Y_bottom; height = Y_bottom-0 = 75.
# We return -scale_uniform(75) = -210 so after the caller's NEG height is 210
# (full strip) -> hit box covers the whole strip. EAX is free (overwritten at
# 0x4ADFA5 by the rect-width thunk); EDX/EBX preserved by scale_uniform.
#   mov eax,[esi+0x119c]; neg eax; call scale_uniform; neg eax; mov ecx,eax; ret
THUNK_SPOT_H_INTO_ECX = (
    "8B 86 9C 11 00 00 F7 D8 E8 {rel32:strip_px} F7 D8 8B C8 C3"
)

# -----------------------------------------------------------------------------
# thunk_clip_fullstrip — replaces `CALL Buffer_set_clip` at 0x4AE51A.
# draw_item clips drawing to a vanilla 26px band (rect.top = spot.top+0x1f,
# rect.bottom = spot.top+0x39) BEFORE drawing the strip + text. With the text
# now centered at ~spot.top+80 (full-strip centering), that band clips the text
# away. We widen the clip's BOTTOM to spot.top + scale_uniform(75) (full strip)
# so the centered text is inside it. We do NOT touch rect.top: it is reused at
# 0x4AE554 for the strip-blit dst Y (dst = rect.top - 0x1f = spot.top), so
# moving it would shift the strip. rect.bottom here is later overwritten by
# thunk_text_fullrect, so widening it only affects the clip.
#
# On entry (our CALL replaces the original): stack = [ret=0x4AE51F],[&rect];
# ECX = the draw buffer (this). EBX = item index, LIVE — left untouched.
# Buffer_set_clip is __thiscall(this, &rect), RET 4. We tail-jump to it (abs
# MOV/JMP; {rel32} only follows E8) so its RET returns straight to 0x4AE51F.
#
#   thunk_clip_fullstrip:               ; ECX=buffer; stack: [ret],[&rect]
#       push ecx                        ; 51            save buffer
#       mov  edx, [esp+0x08]            ; 8B 54 24 08   EDX=&rect
#       mov  eax, [edx+0x04]            ; 8B 42 04      rect.top (= spot.top+0x1f)
#       sub  eax, 0x1f                  ; 83 E8 1F      spot.top
#       push edx                        ; 52            save &rect
#       push eax                        ; 50            save spot.top
#       mov  eax, 0x4B                  ; B8 4B 00 00 00   (75)
#       call scale_uniform              ; E8 {rel32}    EAX=scaled (210)
#       pop  ecx                        ; 59            ECX=spot.top
#       add  eax, ecx                   ; 03 C1         EAX=spot.top+210
#       pop  edx                        ; 5A            EDX=&rect
#       mov  [edx+0x0c], eax            ; 89 42 0C      rect.bottom = spot.top+210
#       pop  ecx                        ; 59            ECX=buffer (this)
#       mov  eax, 0x005D8000            ; B8 00 80 5D 00   Buffer_set_clip
#       jmp  eax                        ; FF E0
THUNK_CLIP_FULLSTRIP = (
    "51 8B 54 24 08 8B 42 04 83 E8 1F 52 50"
    " B8 4B 00 00 00 E8 {rel32:strip_px} 59 03 C1 5A 89 42 0C 59"
    " B8 00 80 5D 00 FF E0"
)

# -----------------------------------------------------------------------------
# BL!=0 submenu separator-bar scaling (the title divider). The vanilla bar is
# 354x20 (color 9), drawn once below the title strip, with the layout then
# advanced by 20. All three +20/width pieces scale via scale_uniform so the bar
# matches the scaled strips and the items stay aligned.

# thunk_fill3_scaled — redirect CALL GraphicWin_fill_3 @ 0x4ADF50. Scales the W
# (354->995) and H (20->56) args in place, AND advances EDI by (scale(20)-20)
# so the vanilla `ADD EDI,0x14` left at 0x4ADF55 brings the total layout step to
# scale(20) (items follow the scaled separator). We do NOT patch 0x4ADF55 — its
# trailing byte 0x4ADF58 is a live JZ/JNZ target (clobbering it crashes the main
# menu). fill_3 preserves EDI (vanilla uses EDI right after the call), so the
# pre-jump += is safe. Tail-jumps to fill_3 (0x5D5440, RET 0x14). Stack on entry:
#   [esp]=ret [+4]=x [+8]=y [+0xc]=w [+0x10]=h [+0x14]=color ; ECX=this (preserved)
#   mov eax,[esp+0xc];  call scale_uniform; mov [esp+0xc],eax      ; W
#   mov eax,[esp+0x10]; call scale_uniform; mov [esp+0x10],eax     ; H
#   mov eax,0x14; call scale_uniform; sub eax,0x14; add edi,eax    ; EDI += scale(20)-20
#   mov eax,0x5D5440; jmp eax
THUNK_FILL3_SCALED = (
    "8B 44 24 0C E8 {rel32:strip_px} 89 44 24 0C"
    " 8B 44 24 10 E8 {rel32:strip_px} 89 44 24 10"
    " B8 14 00 00 00 E8 {rel32:strip_px} 83 E8 14 03 F8"
    " B8 40 54 5D 00 FF E0"
)

# =============================================================================
# MODAL / POPUP scaling infrastructure (BasePop/Popup pipeline)
# =============================================================================
# Every pop-up in the game funnels through Popup_start -> BasePop_* and sizes
# itself parametrically from font metrics. The engine has a hardcoded 1.5x
# hi-res popup mode (`*3/2` when ScreenWidth>0x3ff) that caps scaling, so modals
# stay tiny at 4K. We (1) enlarge the popup default fonts to a resolution-scaled
# size and (2) [later] replace the `*3/2` geometry with popup_scale(). Since
# layout derives from font metrics, enlarging the font alone already re-flows
# the dialog larger. Fonts are TrueType (Arial) so larger sizes stay crisp.
#
# g_popup_scale_num: the chosen popup font SIZE (snapped table entry, 16..40),
# computed once by thunk_ensure_scale. Doubles as the geometry scale numerator
# (scale = g_popup_scale_num / 16) so geometry tracks the achieved font scale.
# 0 = not yet computed. Denominator is a literal 16 baked into popup_scale.
G_POPUP_SCALE_NUM = "00 00 00 00"
# g_pf0/1/2: scaled popup Font* for variants 0/1/2 = find_font(g_popup_scale_num, v).
# Populated by thunk_popup_setup_fonts; substituted for the size-16 globals that
# popups_normal would otherwise install as the popup string/dialog/button fonts.
G_PF0 = "00 00 00 00"
G_PF1 = "00 00 00 00"
G_PF2 = "00 00 00 00"

# popup_scale — REUSABLE geometry helper. EAX in = pixel value, EAX out =
# value * g_popup_scale_num / 16 (>>4). Assumes g_popup_scale_num already set
# (ensure_scale runs at config_popups/system_init, before any popup). Values are
# small (<2000) so value*40 never overflows int32. Clobbers only EAX (+flags).
#   imul eax, [g_popup_scale_num] ; sar eax, 4 ; ret
POPUP_SCALE = "0F AF 05 {abs32:g_popup_scale_num} C1 F8 04 C3"

# thunk_ensure_scale — compute g_popup_scale_num once (idempotent via the !=0
# guard). target = scale_uniform(16) = floor(16*min(W/1024,H/768)); clamp to
# [16,40] (16 = no shrink below native; 40 = font table max). At the user's test
# resolutions (4K->40, 1080p->22, 1280x1024->20) the clamped value already lands
# on a font-table entry, so find_font picks it exactly -> geometry==font scale.
# Clobbers EAX only (scale_uniform preserves ECX/EDX/EBX); ESI/EDI untouched.
#   cmp [num],0 ; jne done ; mov eax,16 ; call scale_uniform
#   cmp eax,40 ; jle +5 ; mov eax,40 ; cmp eax,16 ; jge +5 ; mov eax,16
#   mov [num],eax ; done: ret
THUNK_ENSURE_SCALE = (
    "83 3D {abs32:g_popup_scale_num} 00"   # cmp dword [g_popup_scale_num], 0
    " 75 31"                                # jne done (skip the 0x31 compute bytes)
    " B8 10 00 00 00"                       # mov eax, 16
    " E8 {rel32:scale_uniform}"             # eax = floor(16 * scale_uniform)
    " 83 F8 28 7E 05 B8 28 00 00 00"        # cmp eax,40 ; jle +5 ; mov eax,40
    " 83 F8 10 7D 05 B8 10 00 00 00"        # cmp eax,16 ; jge +5 ; mov eax,16
    " A3 {abs32:g_popup_scale_num}"         # mov [g_popup_scale_num], eax
    " 83 F8 16 19 C0 8D 44 00 04"           # cmp eax,22 ; sbb eax,eax ; lea eax,[eax+eax+4]  (2 below g=22, else 4)
    " A3 {abs32:g_stripe_period}"           # mov [g_stripe_period], eax   (law scaling_laws.stripe_period)
    " C3"                                   # done: ret
)
# g_stripe_period: the chrome stripe period P = stripe_period(g), written with g (the popup-g stripe thunks
# read it).  Static 2 so a read before thunk_ensure_scale can never divide by zero.
G_STRIPE_PERIOD = "02 00 00 00"

# thunk_popup_setup_fonts — replaces the entry instruction of popups_normal
# (MOV EAX,[0x945760], 5 bytes) with a CALL. Ensures the scale is computed, then
# fills g_pf0/1/2 = find_font(g_popup_scale_num, 0/1/2), and finally reproduces
# the original load (EAX = scaled variant-2 font) so the following code (which
# pushes EAX/ECX/EDX as the string-font args) gets scaled fonts. The other two
# loads (ECX,EDX) + the dialog/button trios are repointed to g_pf1/g_pf0/g_pf2 by
# same-length MOV-address patches at their sites. find_font = __cdecl(size,variant)
# caller-cleans 8. Preserves ECX/EDX/ESI/EDI/EBX (popups_normal saves ESI/EDI for
# ITS caller AFTER our hook, so we must not corrupt them; EBX saved defensively).
# v2 (the shipped patches.yaml entry, 26 B; synced here 2026-10-18 so the slot check above sees the real extent --
# v1's 84 B of inline find_font calls ran to 0x5F4 and hid the free 0x5BA..0x6B0 gap): the three fonts are built by
# thunk_build_scaled_fonts (dedicated Arial Narrow at cell 20*g/16).
THUNK_POPUP_SETUP_FONTS = (
    "51 52 56 57 53"                        # push ecx,edx,esi,edi,ebx
    " E8 {rel32:thunk_ensure_scale}"        # compute g_popup_scale_num if needed
    " E8 {rel32:thunk_build_scaled_fonts}"  # g_pf0/1/2
    " 5B 5F 5E 5A 59"                       # pop ebx,edi,esi,edx,ecx
    " A1 {abs32:g_pf2}"                     # mov eax,[g_pf2]  (replicate original load, scaled)
    " C3"                                   # ret -> 0x588465
)

# =============================================================================
# thunk_sprite_draw — drop-in replacement for sprite_draw_func (0x404860), the
# popup art-sprite draw on the [+0x3168] custom-draw path (Path A in
# BasePop_on_redraw). The original hardcodes scale 1,1 (native) in its
# FUN_005E4B4A(dest, sprite, x-5, y-6, num, den) call, so popups on that path
# (e.g. Quit) never scale their image. This thunk is byte-identical EXCEPT it
# passes (g_popup_scale_num, 16) instead of (1, 1) -> art scales by popup_scale.
# [+0x3168] is repointed here via the Popup_calculate_dimensions assignment.
# FUN_005E4B4A is __stdcall (cleans its 6 args), matching the original's
# no-add-esp epilogue. Args at [ebp+8]=sprite,[+0xc]=dest,[+0x14]=x,[+0x18]=y.
THUNK_SPRITE_DRAW = (
    "55 8B EC"                              # push ebp; mov ebp,esp
    " 8B 4D 14 8B 55 18 8B 45 0C"           # ecx=x, edx=y, eax=dest
    " 83 E9 05 83 EA 06"                    # x-=5; y-=6
    " 85 C0 74 07 05 44 04 00 00 EB 02 33 C0"  # eax = dest? dest+0x444 : 0
    " 6A 10"                                # push 16              (denom; was 1)
    " FF 35 {abs32:g_popup_scale_num}"      # push [g_popup_scale_num] (num; was 1)
    " 52 51"                                # push y; push x
    " 8B 4D 08 33 D2 8A 51 08 52"           # ecx=sprite; dl=[ecx+8]; push edx
    " 50"                                   # push dest
    " E8 {rel32:FUN_005e4b4a}"              # call FUN_005E4B4A (stdcall, cleans 6 args)
    " 5D C3"                                # pop ebp; ret
)

# thunk_scale_btnheight — detours the `MOV [esi+0x30d0], 0x14` at 0x404d0b in
# Popup_calculate_dimensions. [esi+0x30d0] is the popup option-button ROW HEIGHT
# (param_7/h passed to BaseButton_init -> GraphicWin_init), hardcoded to 20px so
# the scaled 40px button text overflows. We store popup_scale(20) instead (=50 at
# 4K, proportional at other res). ESI=popup here (the MOV targets [esi+..]).
# popup_scale clobbers EAX + FLAGS; the resume at 0x404d15 is a JZ that reads
# flags set BEFORE the MOV, so we MUST save/restore both EAX and flags.
THUNK_SCALE_BTNHEIGHT = (
    "50 9C"                                 # push eax; pushfd
    " B8 14 00 00 00"                       # mov eax, 0x14
    " E8 {rel32:popup_scale}"               # eax = popup_scale(20)
    " 89 86 D0 30 00 00"                    # mov [esi+0x30d0], eax
    " 9D 58"                                # popfd; pop eax
    " 68 {abs32:btnheight_resume} C3"       # resume at 0x404d15
)

# thunk_btnfont_enter / _leave — popup-scoped bracket on BasePop_exec_3 so the
# GENERIC button default font (DAT_009b8e34/38/3c, read by BaseButton_init for
# the popup's option buttons) is scaled DURING popup show and restored after, so
# gameplay buttons (162 other BaseButton_init callers) are untouched. enter saves
# the 3 globals to g_btnfont_save0/1/2 and sets them to g_pf0/1/2 (the scaled
# fonts), then re-runs the displaced prologue `MOV EAX,FS:[0]` and resumes at
# 0x602606. Only EAX is used (about to be overwritten by FS:[0] anyway).
THUNK_BTNFONT_ENTER = (
    "A1 {abs32:DAT_009b8e34} A3 {abs32:g_btnfont_save0}"
    " A1 {abs32:DAT_009b8e38} A3 {abs32:g_btnfont_save1}"
    " A1 {abs32:DAT_009b8e3c} A3 {abs32:g_btnfont_save2}"
    " A1 {abs32:g_pf0} A3 {abs32:DAT_009b8e34}"
    " A1 {abs32:g_pf1} A3 {abs32:DAT_009b8e38}"
    " A1 {abs32:g_pf2} A3 {abs32:DAT_009b8e3c}"
    " 64 A1 00 00 00 00"                                # displaced: mov eax,fs:[0]
    " 68 {abs32:exec3_enter_resume} C3"                 # resume at 0x602606
)

# leave: restore the 3 globals from the saves (preserving EAX = return value via
# push/pop so [ESP+0x30] in the displaced epilogue still reads correctly), then
# re-run the displaced epilogue and resume at 0x6037E6.
THUNK_BTNFONT_LEAVE = (
    "50"                                                # push eax (retval)
    " A1 {abs32:g_btnfont_save0} A3 {abs32:DAT_009b8e34}"
    " A1 {abs32:g_btnfont_save1} A3 {abs32:DAT_009b8e38}"
    " A1 {abs32:g_btnfont_save2} A3 {abs32:DAT_009b8e3c}"
    " 58"                                               # pop eax
    " 8B 4C 24 30 5F 5E"                                # displaced epilogue
    " 68 {abs32:exec3_leave_resume} C3"                 # resume at 0x6037E6
)

# -----------------------------------------------------------------------------
# thunk_scale20_into_edx — replaces `MOV EDX,0x14` at 0x4AE04D (5 bytes, exact).
# Returns scale_uniform(20)=56 in EDX so the BL!=0 spot init computes
# Y_top = scale(20) - EDI = 56 + 210 = 266, matching the scaled separator.
# Preserves the live EAX (X-right, used at 0x4AE052).
#   push eax; mov eax,0x14; call scale_uniform; mov edx,eax; pop eax; ret
THUNK_SCALE20_INTO_EDX = (
    "50 B8 14 00 00 00 E8 {rel32:strip_px} 8B D0 58 C3"
)

# =============================================================================
# MENU STRIP ON g (2026-10-18 fix 13; law scaling_laws.menu_strip_px / menu_strip_layout)
# =============================================================================
# Every strip thunk above used to call scale_uniform (unclamped min(W/1024, H/768)): 800x600 drew at 0.78x,
# 1366x1024 at 1.33x where g = 20, 4K at 2.81x past the g = 40 cap. They now call strip_px, the law's port:
# v if g <= 16 else floor(v*g/16). thunk_ensure_scale keeps its own call scale_uniform (it DERIVES g).
# The new thunks below put g <= 16 back on vanilla's own callees and scale the native constants that were
# still left inside the scaled strip (hit-rect left 15, draw_item blit x 15, text rect +12/+4, title inset 4,
# the 26-px clip band).

# strip_px -- EAX in = vanilla magnitude (>= 0), EAX out = menu_strip_px(EAX, g). g is computed lazily (the
# strip can draw before anything else has asked for g). Clobbers EAX + flags only; ECX/EDX/EBX/ESI/EDI kept
# (thunk_ensure_scale clobbers only EAX; `imul r32, m32` writes only EAX) -- scale_uniform's own contract.
#   push eax ; call thunk_ensure_scale ; pop eax
#   cmp dword [g_popup_scale_num], 0x10 ; jle .done
#   imul eax, [g_popup_scale_num] ; sar eax, 4
#   .done: ret
STRIP_PX = (
    "50 E8 {rel32:thunk_ensure_scale} 58"
    " 83 3D {abs32:g_popup_scale_num} 10 7E 0A"
    " 0F AF 05 {abs32:g_popup_scale_num} C1 F8 04"
    " C3"
)

# t_strip_blit_gate -- the three strip-blit CALLs (0x4ADF28 open loop, 0x4AE171 close loop, 0x4AE570 draw_item).
# g <= 16 tail-jumps to vanilla's Buffer_copy_4 (the 1:1 blit; the engine callee sequence stays vanilla's), else to
# thunk_strip_blit_stretched (Buffer_copy_3 at s(354) x s(75)). Entered by CALL; the return address and the 7
# Buffer_copy_4 args stay where the caller put them, so either target returns straight to the caller.
#   push eax ; call thunk_ensure_scale ; pop eax
#   cmp dword [g_popup_scale_num], 0x10 ; jle .native
#   push thunk_strip_blit_stretched ; ret
#   .native: push Buffer_copy_4 ; ret
T_STRIP_BLIT_GATE = (
    "50 E8 {rel32:thunk_ensure_scale} 58"
    " 83 3D {abs32:g_popup_scale_num} 10 7E 06"
    " 68 {abs32:thunk_strip_blit_stretched} C3"
    " 68 {abs32:Buffer_copy_4} C3"
)

# t_spot_l -- replaces `mov dword [ebp-0x1c], 0xF` (7 B) @0x4ADFAC: the Spot rect LEFT = s(15). The flags of the
# `test bl, bl` @0x4ADFAA are live to the `je` @0x4ADFBC (the titled / untitled split), so they are kept.
#   pushfd ; push eax ; mov eax, 0xF ; call strip_px ; mov [ebp-0x1c], eax ; pop eax ; popfd ; ret
T_SPOT_L = (
    "9C 50 B8 0F 00 00 00 E8 {rel32:strip_px} 89 45 E4 58 9D C3"
)

# t_strip_dstx -- replaces `mov ecx, [ebp-0x10] ; add edx, -0x1F ; add ecx, -0xF` (9 B) @0x4AE558 in draw_item:
# the strip blit's dst x = spot L - s(15) (= 0, the strip's own left edge) and dst y = clip top - 0x1F (= spot top,
# untouched). EAX (the dest-buffer mask, `and eax, edi` next) is kept; that `and` rewrites the flags.
#   mov ecx, [ebp-0x10] ; add edx, -0x1F ; push eax ; mov eax, 0xF ; call strip_px ; sub ecx, eax ; pop eax ; ret
T_STRIP_DSTX = (
    "8B 4D F0 83 C2 E1 50 B8 0F 00 00 00 E8 {rel32:strip_px} 29 C1 58 C3"
)

# t_text_lr -- replaces `add eax,4 ; sub ecx,4 ; sub edx,2 ; add eax,8 ; add ecx,8` (15 B) @0x4AE587 in draw_item:
# the item text rect in EDGE form. On entry EAX = spot L (= s(15)), ECX = spot R (= s(300)), EDX = the clip
# bottom. Out: L = EAX + s(27) - s(15) = s(27), R = ECX + s(304) - s(300) = s(304), EDX - 2 (the text bottom
# that thunk_text_fullrect then replaces). The flags are rewritten by `test ebx, ebx` @0x4AE599.
#   push eax
#   mov eax, 0x1B  ; call strip_px ; add [esp], eax
#   mov eax, 0xF   ; call strip_px ; sub [esp], eax
#   mov eax, 0x130 ; call strip_px ; add ecx, eax
#   mov eax, 0x12C ; call strip_px ; sub ecx, eax
#   pop eax ; sub edx, 2 ; ret
T_TEXT_LR = (
    "50"
    " B8 1B 00 00 00 E8 {rel32:strip_px} 01 04 24"
    " B8 0F 00 00 00 E8 {rel32:strip_px} 29 04 24"
    " B8 30 01 00 00 E8 {rel32:strip_px} 01 C1"
    " B8 2C 01 00 00 E8 {rel32:strip_px} 29 C1"
    " 58 83 EA 02 C3"     # pop eax ; sub edx,2 -- dead (thunk_text_fullrect rewrites the bottom), kept for vanilla parity ; ret
)

# t_title_inset -- replaces `mov ebx, 4` (5 B) @0x4ADFE0: the titled menu's title-rect inset s(4) (the same EBX
# undoes it @0x4AE03A / 0x4AE052, so the item spots keep s(15) / s(300)). `add eax, ebx` next rewrites the flags.
#   push eax ; mov eax, 4 ; call strip_px ; mov ebx, eax ; pop eax ; ret
T_TITLE_INSET = (
    "50 B8 04 00 00 00 E8 {rel32:strip_px} 8B D8 58 C3"
)

# t_clip_exact -- the draw_item clip CALL @0x4AE51A (Buffer_set_clip(&rect), thiscall RET 4; rect = {spot L,
# spot top + 0x1F, spot R, spot top + 0x39}). g <= 16: tail-jump to vanilla's Buffer_set_clip with vanilla's rect.
# g > 16: the clip band on the law, {L, top + s(31), R, top + s(57)}, built in a STACK COPY (the frame rect's top
# feeds the strip blit's dst y and the text rect, so it is never written); Buffer_set_clip copies the rect.
# Replaces thunk_clip_fullstrip (which widened the band to top + s(75); now dead bytes). ECX (the buffer) is
# preserved for the call; EBX/EDX are restored; EAX is the callee's (reloaded @0x4AE51F).
#   push eax ; call thunk_ensure_scale ; pop eax
#   cmp dword [g_popup_scale_num], 0x10 ; jg .hi
#   push Buffer_set_clip ; ret
#   .hi: push ebx ; push edx ; mov edx, [esp+0xC]              ; &rect
#   sub esp, 0x10 ; mov eax, [edx] ; mov [esp], eax ; mov eax, [edx+8] ; mov [esp+8], eax
#   mov ebx, [edx+4] ; sub ebx, 0x1F                             ; the strip top
#   mov eax, 0x1F ; call strip_px ; add eax, ebx ; mov [esp+4], eax
#   mov eax, 0x39 ; call strip_px ; add eax, ebx ; mov [esp+0xC], eax
#   push esp ; call Buffer_set_clip ; add esp, 0x10 ; pop edx ; pop ebx ; ret 4
T_CLIP_EXACT = (
    "50 E8 {rel32:thunk_ensure_scale} 58"
    " 83 3D {abs32:g_popup_scale_num} 10 7F 06"
    " 68 {abs32:Buffer_set_clip} C3"
    " 53 52 8B 54 24 0C"
    " 83 EC 10 8B 02 89 04 24 8B 42 08 89 44 24 08"
    " 8B 5A 04 83 EB 1F"
    " B8 1F 00 00 00 E8 {rel32:strip_px} 01 D8 89 44 24 04"
    " B8 39 00 00 00 E8 {rel32:strip_px} 01 D8 89 44 24 0C"
    " 54 E8 {rel32:Buffer_set_clip} 83 C4 10 5A 5B C2 04 00"
)

# The menu_strip_thunks offsets of the fix-13 entries (cave_map.py --fit: the 0x5BA..0x6B0 and 0xB04..0xB68 gaps).
MENU_STRIP_G_ENTRIES = (
    ("strip_px",          0x5C0, STRIP_PX),
    ("t_strip_blit_gate", 0x5E0, T_STRIP_BLIT_GATE),
    ("t_spot_l",          0x600, T_SPOT_L),
    ("t_strip_dstx",      0x620, T_STRIP_DSTX),
    ("t_text_lr",         0x640, T_TEXT_LR),
    ("t_title_inset",     0x680, T_TITLE_INSET),
    ("t_clip_exact",      0xB04, T_CLIP_EXACT),
)


def count_bytes(token_string: str) -> int:
    """Count raw bytes in a placeholder-bearing token string.
    Each hex pair = 1 byte; each `{rel32:NAME}` placeholder = 4 bytes."""
    n = 0
    for tok in token_string.replace("\n", " ").split():
        tok = tok.strip(",")
        if not tok:
            continue
        if tok.startswith("{") and tok.endswith("}"):
            n += 4
            continue
        # hex pair
        assert len(tok) == 2, f"bad token: {tok!r}"
        int(tok, 16)
        n += 1
    return n


def normalize(token_string: str) -> str:
    """Collapse whitespace; keep placeholders intact."""
    return " ".join(token_string.split())


def emit_yaml_fragment() -> str:
    contents = [
        ("scale_uniform",                0x00, SCALE_UNIFORM),
        ("thunk_scale_rect_width",       0x60, THUNK_SCALE_RECT_WIDTH),
        ("thunk_strip_blit_stretched",   0x80, THUNK_STRIP_BLIT_STRETCHED),
        ("thunk_advance_edi_by_scaled_h", 0xF0, THUNK_ADVANCE_EDI_BY_SCALED_H),
        ("thunk_load_strip_w_into_eax",  0x110, THUNK_LOAD_STRIP_W_INTO_EAX),
        ("thunk_push_scaled_font",       0x140, THUNK_PUSH_SCALED_FONT),
        ("thunk_spot_h_into_edi",        0x160, THUNK_SPOT_H_INTO_EDI),
        ("thunk_spot_h_into_eax",        0x180, THUNK_SPOT_H_INTO_EAX),
        ("thunk_spot_h_into_ecx",        0x190, THUNK_SPOT_H_INTO_ECX),
        ("thunk_text_fullrect",          0x1A4, THUNK_TEXT_FULLRECT),
        ("thunk_clip_fullstrip",         0x1D8, THUNK_CLIP_FULLSTRIP),
        ("thunk_fill3_scaled",           0x200, THUNK_FILL3_SCALED),
        ("thunk_scale20_into_edx",       0x240, THUNK_SCALE20_INTO_EDX),
        ("thunk_load_strip_w_into_edi",  0x250, THUNK_LOAD_STRIP_W_INTO_EDI),
        ("filelock_lock",                0x290, THUNK_FILELOCK_LOCK),
        ("filelock_unlock",              0x2B0, THUNK_FILELOCK_UNLOCK),
        ("filelock_var",                 0x2C0, FILELOCK_VAR),
        ("thunk_deco_blit_stretched",    0x300, THUNK_DECO_BLIT_STRETCHED),
        ("scale_x",                      0x370, SCALE_X),
        ("scale_y",                      0x390, SCALE_Y),
        ("thunk_deco_soft_update",       0x3B0, THUNK_DECO_SOFT_UPDATE),
        ("thunk_deco_keyed_scaled",      0x410, THUNK_DECO_KEYED_SCALED),
        ("thunk_keyed_stretch_blit",     0x470, THUNK_KEYED_STRETCH_BLIT),
        ("thunk_ensure_scratch",         0x4D0, THUNK_ENSURE_SCRATCH),
        ("g_scratch_buf",                0x510, G_SCRATCH_BUF),
        # ---- modal/popup scaling (added 2026-05-30) ----
        ("g_popup_scale_num",            0x540, G_POPUP_SCALE_NUM),
        ("g_pf0",                        0x544, G_PF0),
        ("g_pf1",                        0x548, G_PF1),
        ("g_pf2",                        0x54C, G_PF2),
        ("popup_scale",                  0x550, POPUP_SCALE),
        ("thunk_ensure_scale",           0x560, THUNK_ENSURE_SCALE),
        ("g_stripe_period",              0x59C, G_STRIPE_PERIOD),
        ("thunk_popup_setup_fonts",      0x5A0, THUNK_POPUP_SETUP_FONTS),
        # ---- menu strip on g (fix 13) ----
        *MENU_STRIP_G_ENTRIES,
        # ---- popup geometry scaling (GraphicWin_init detour) ----
        ("thunk_sprite_draw",            0x6B0, THUNK_SPRITE_DRAW),
        ("thunk_scale_btnheight",        0x700, THUNK_SCALE_BTNHEIGHT),
        ("thunk_btnfont_enter",          0x730, THUNK_BTNFONT_ENTER),
        ("thunk_btnfont_leave",          0x780, THUNK_BTNFONT_LEAVE),
    ]
    lines = []
    lines.append("# Paste under code_caves[0].contents in patches.yaml.")
    lines.append("# Each `{rel32:NAME}` placeholder is a 4-byte field the patcher resolves at apply-time.")
    lines.append("")
    for name, off, body in contents:
        nbytes = count_bytes(body)
        # Verify the symbol-table offset is large enough that the next thunk doesn't overlap
        lines.append(f"      # {name}: {nbytes} bytes (next byte at offset 0x{off + nbytes:02X})")
        lines.append(f"      - id: {name}")
        lines.append(f"        offset: 0x{off:02X}")
        lines.append(f'        bytes: "{normalize(body)}"')
        lines.append("")
    lines.append("# Paste under pcave2's contents (the decoration-follows-the-backdrop block, fix 15).")
    lines.append("")
    for name, off, body in DECO_BACKDROP_ENTRIES:
        nbytes = count_bytes(body)
        lines.append(f"      # {name}: {nbytes} bytes (next byte at offset 0x{off + nbytes:X})")
        lines.append(f"      - id: {name}")
        lines.append(f"        offset: 0x{off:X}")
        lines.append(f'        bytes: "{normalize(body)}"')
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    # Sanity-check sizes match the planned layout.
    sizes = {
        "scale_uniform":                 count_bytes(SCALE_UNIFORM),
        "thunk_scale_rect_width":        count_bytes(THUNK_SCALE_RECT_WIDTH),
        "thunk_strip_blit_stretched":    count_bytes(THUNK_STRIP_BLIT_STRETCHED),
        "thunk_advance_edi_by_scaled_h": count_bytes(THUNK_ADVANCE_EDI_BY_SCALED_H),
        "thunk_load_strip_w_into_eax":   count_bytes(THUNK_LOAD_STRIP_W_INTO_EAX),
        "thunk_load_strip_w_into_edi":   count_bytes(THUNK_LOAD_STRIP_W_INTO_EDI),
        "thunk_push_scaled_font":        count_bytes(THUNK_PUSH_SCALED_FONT),
        "thunk_spot_h_into_edi":         count_bytes(THUNK_SPOT_H_INTO_EDI),
        "thunk_spot_h_into_eax":         count_bytes(THUNK_SPOT_H_INTO_EAX),
        "thunk_spot_h_into_ecx":         count_bytes(THUNK_SPOT_H_INTO_ECX),
        "thunk_text_fullrect":           count_bytes(THUNK_TEXT_FULLRECT),
        "thunk_clip_fullstrip":          count_bytes(THUNK_CLIP_FULLSTRIP),
        "thunk_fill3_scaled":            count_bytes(THUNK_FILL3_SCALED),
        "thunk_scale20_into_edx":        count_bytes(THUNK_SCALE20_INTO_EDX),
        "filelock_lock":                 count_bytes(THUNK_FILELOCK_LOCK),
        "filelock_unlock":               count_bytes(THUNK_FILELOCK_UNLOCK),
        "filelock_var":                  count_bytes(FILELOCK_VAR),
        "thunk_deco_blit_stretched":     count_bytes(THUNK_DECO_BLIT_STRETCHED),
        "scale_x":                       count_bytes(SCALE_X),
        "scale_y":                       count_bytes(SCALE_Y),
        "thunk_deco_soft_update":        count_bytes(THUNK_DECO_SOFT_UPDATE),
        "thunk_deco_keyed_scaled":       count_bytes(THUNK_DECO_KEYED_SCALED),
        "thunk_keyed_stretch_blit":      count_bytes(THUNK_KEYED_STRETCH_BLIT),
        "thunk_ensure_scratch":          count_bytes(THUNK_ENSURE_SCRATCH),
        "g_scratch_buf":                 count_bytes(G_SCRATCH_BUF),
        "g_popup_scale_num":             count_bytes(G_POPUP_SCALE_NUM),
        "g_pf0":                         count_bytes(G_PF0),
        "g_pf1":                         count_bytes(G_PF1),
        "g_pf2":                         count_bytes(G_PF2),
        "popup_scale":                   count_bytes(POPUP_SCALE),
        "thunk_ensure_scale":            count_bytes(THUNK_ENSURE_SCALE),
        "g_stripe_period":               count_bytes(G_STRIPE_PERIOD),
        "thunk_popup_setup_fonts":       count_bytes(THUNK_POPUP_SETUP_FONTS),
        "thunk_sprite_draw":             count_bytes(THUNK_SPRITE_DRAW),
        "thunk_scale_btnheight":         count_bytes(THUNK_SCALE_BTNHEIGHT),
        "thunk_btnfont_enter":           count_bytes(THUNK_BTNFONT_ENTER),
        "thunk_btnfont_leave":           count_bytes(THUNK_BTNFONT_LEAVE),
        **{n: count_bytes(b) for n, _o, b in MENU_STRIP_G_ENTRIES},
    }
    offsets = {
        "scale_uniform":                 0x00,
        "thunk_scale_rect_width":        0x60,
        "thunk_strip_blit_stretched":    0x80,
        "thunk_advance_edi_by_scaled_h": 0xF0,
        "thunk_load_strip_w_into_eax":   0x110,
        "thunk_push_scaled_font":        0x140,
        "thunk_spot_h_into_edi":         0x160,
        "thunk_spot_h_into_eax":         0x180,
        "thunk_spot_h_into_ecx":         0x190,
        "thunk_text_fullrect":           0x1A4,
        "thunk_clip_fullstrip":          0x1D8,
        "thunk_fill3_scaled":            0x200,
        "thunk_scale20_into_edx":        0x240,
        "thunk_load_strip_w_into_edi":   0x250,
        "filelock_lock":                 0x290,
        "filelock_unlock":               0x2B0,
        "filelock_var":                  0x2C0,
        "thunk_deco_blit_stretched":     0x300,
        "scale_x":                       0x370,
        "scale_y":                       0x390,
        "thunk_deco_soft_update":        0x3B0,
        "thunk_deco_keyed_scaled":       0x410,
        "thunk_keyed_stretch_blit":      0x470,
        "thunk_ensure_scratch":          0x4D0,
        "g_scratch_buf":                 0x510,
        "g_popup_scale_num":             0x540,
        "g_pf0":                         0x544,
        "g_pf1":                         0x548,
        "g_pf2":                         0x54C,
        "popup_scale":                   0x550,
        "thunk_ensure_scale":            0x560,
        "g_stripe_period":               0x59C,
        "thunk_popup_setup_fonts":       0x5A0,
        "thunk_sprite_draw":             0x6B0,
        "thunk_scale_btnheight":         0x700,
        "thunk_btnfont_enter":           0x730,
        "thunk_btnfont_leave":           0x780,
        **{n: o for n, o, _b in MENU_STRIP_G_ENTRIES},
    }
    print("=== thunk size check ===", file=sys.stderr)
    ok = True
    items = list(offsets.items())
    items.sort(key=lambda kv: kv[1])
    for i, (name, off) in enumerate(items):
        size = sizes[name]
        end = off + size
        next_off = items[i + 1][1] if i + 1 < len(items) else 0xE00
        clash = end > next_off
        print(f"  {name:<32} @ +0x{off:02X}  size={size:>3} bytes  ends at +0x{end:02X}"
              f"  (next slot +0x{next_off:02X}){'  *** OVERLAP ***' if clash else ''}",
              file=sys.stderr)
        if clash:
            ok = False
    print(f"  cave reserved : 3584 bytes (0xE00)", file=sys.stderr)
    print(f"  total used    : {sum(sizes.values())} bytes", file=sys.stderr)
    if not ok:
        return 1
    print(file=sys.stderr)
    print(emit_yaml_fragment())
    return 0


if __name__ == "__main__":
    sys.exit(main())
