"""Assemble thunk_portrait_avg (the palette-aware bilinear sprite resampler) with
keystone, and emit the hex for patches.yaml.

This is the production form of the A5 fix validated in Frida (hook_a5_portraitavg.js):
replace the engine's nearest-neighbour scale of the faction leader portrait with a
palette-aware bilinear AVERAGE, so the thin baked-in green frame blends into the
output instead of dropping at fractional scale (g25 = x1.5625). Reusable technique
for any scaled sprite with fine baked-in detail (see skill scaling-sprites).

Hook: entry-detour at Sprite_draw_2 (0x5E4B4A). The site is overwritten with
`push {abs32:thunk_portrait_avg}; ret; nop; nop` (8 bytes) -- an esp-neutral jump,
so the thunk sees the original entry state: ecx=Sprite*, stack=[ret,dest,key,x,y,num,den].
Gate: dest==0x940824 (faction box) && num>den (g>16). Match -> resample, ret 0x18
(Sprite_draw_2 is __stdcall, cleans 6 args). No match -> run the 2 displaced
instructions (mov eax,[esp+0x14]; mov edx,[esp+0x18]) and jump back to 0x5E4B52.

Sprite struct: data@+0x4, stride@+0x10, w@+0x18, h@+0x1c (confirmed live).
Dest Buffer: data@+0x54, stride@+0x4a8, w@+0x80, h@+0x84 (negative=top-down).
Palette: the DEST BUFFER's own synced DIB color table at dest+0xA4 (RGBQUAD b,g,r,0;
256 entries; Buffer_sync_to_palette 0x5DE8F0 fills it from the live Palette* on every
draw-context setup of a GraphicWin+0x444 canvas). 2026-09-01: was the fixed global
Palette 0x94c590 (g_main_palette) — correct on the menu/faction-select screens where
A5 was validated, STALE in-game (the map screen runs a different palette), so blended
pixels nearest-searched wrong RGB data and wrote junk indices (Morgan 1600 shot 235728:
blue/orange speckle over the dithered shadow side; flat runs survived because identity
maps to itself under ANY self-consistent table). Channel order is irrelevant: the blend
reads and the nearest search use the SAME table, so distance is preserved.
2026-09-01b: the nearest search SKIPS the key index — key 9's RGB is (9,0,0), nearly
pure black, so dark blends (a portrait's shadow side) legitimately won at index 9 and
the keyed window composite punched holes showing the MAP through the portrait (Morgan
4K shot 001528: (17,56,84) ocean speckle; 65=(0,0,0)/198=(12,12,16) absorb those
blends at zero visual cost). Never emit the transparency index from an opaque blend.
"""
import sys
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
THUNK_OFF = 0xA00                 # free slot in pcave2 (used region ends ~0x900)
THUNK_VA  = PCAVE2_VA + THUNK_OFF

NN_OFF    = 0x2150                # free region 0x2147..0x2400 (after thunk_faction_portrait, 71B since fix 8)
NN_VA     = PCAVE2_VA + NN_OFF

ASM = r"""
; ===== entry-detour gate (esp = [ret,dest,key,x,y,num,den]; ecx = Sprite*) =====
    mov     eax, [esp+0x04]          ; dest
    cmp     eax, 0x00940824          ; faction box?
    jne     fallthrough
    mov     eax, [esp+0x14]          ; num
    mov     edx, [esp+0x18]          ; den
    cmp     eax, edx
    jle     fallthrough              ; num<=den -> native (g<=16)
    test    edx, edx
    jle     fallthrough              ; den<=0 -> native (avoid idiv #DE)

; ===== validity guards (mirror the validated prototype) — on ANY failure run the
;       original NN draw via fallthrough, never ret 0x18 (else we drop the sprite).
;       Stack/ecx are still at entry state here (no frame built yet). =====
    mov     eax, [ecx+0x18]          ; src w
    test    eax, eax
    jle     fallthrough
    mov     eax, [ecx+0x1c]          ; src h
    test    eax, eax
    jle     fallthrough
    mov     eax, [ecx+0x04]          ; src data
    test    eax, eax
    je      fallthrough
    mov     eax, [esp+0x04]          ; dest ptr
    mov     eax, [eax+0x54]          ; dest data
    test    eax, eax
    je      fallthrough
    mov     eax, [esp+0x04]
    mov     eax, [eax+0x4a8]         ; dest stride
    test    eax, eax
    jle     fallthrough

; ===== portrait upscale: build frame =====
;   Reserve the 0x90 local region FIRST, THEN push the callee-saved regs, so the saved
;   ebx/esi/edi land BELOW the locals ([ebp-0x94..-0x9C]) instead of aliasing the local
;   slots [ebp-0x04/-0x08/-0x0C] (= sdata/sstride/sw). The old order saved the regs into
;   those very slots and then overwrote them with locals, so the epilogue pop'd garbage
;   (src.w/sstride/data) back into esi/edi/ebx and corrupted the caller -> AV at 0x604c81.
    push    ebp
    mov     ebp, esp
    sub     esp, 0x90
    push    ebx
    push    esi
    push    edi
    ; --- source (Sprite*) fields from ecx ---
    mov     eax, [ecx+0x04]
    mov     [ebp-0x04], eax          ; sdata
    mov     eax, [ecx+0x10]
    cmp     eax, 0
    jg      sstr_ok                  ; sstride<=0 -> fall back to width (prototype parity)
    mov     eax, [ecx+0x18]
sstr_ok:
    mov     [ebp-0x08], eax          ; sstride
    mov     eax, [ecx+0x18]
    mov     [ebp-0x0C], eax          ; sw
    mov     eax, [ecx+0x1c]
    mov     [ebp-0x10], eax          ; sh
    ; --- dest Buffer fields ---
    mov     eax, [ebp+0x08]          ; dest ptr
    mov     edx, [eax+0x54]
    mov     [ebp-0x14], edx          ; ddata
    mov     edx, [eax+0x4a8]
    mov     [ebp-0x18], edx          ; dstride
    mov     edx, [eax+0x80]
    mov     [ebp-0x1C], edx          ; dwid
    mov     edx, [eax+0x84]
    neg     edx
    mov     [ebp-0x20], edx          ; dhgt (abs)
    lea     edx, [eax+0xA4]
    mov     [ebp-0x90], edx          ; palbase = dest's synced DIB color table (display truth)
    ; --- scalars ---
    mov     eax, [ebp+0x18]
    mov     [ebp-0x24], eax          ; num
    mov     eax, [ebp+0x1c]
    mov     [ebp-0x28], eax          ; den
    mov     eax, [ebp+0x0c]
    mov     [ebp-0x2C], eax          ; key
    mov     eax, [ebp+0x10]
    mov     [ebp-0x30], eax          ; px
    mov     eax, [ebp+0x14]
    mov     [ebp-0x34], eax          ; py
    ; --- dstW = sw*num/den ; dstH = sh*num/den ---
    mov     eax, [ebp-0x0C]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    mov     [ebp-0x38], eax          ; dstW
    mov     eax, [ebp-0x10]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    mov     [ebp-0x3C], eax          ; dstH

    mov     dword ptr [ebp-0x40], 0  ; dyi = 0
yloop:
    mov     eax, [ebp-0x40]
    cmp     eax, dword ptr [ebp-0x3C]
    jge     yend
    ; dy bounds
    mov     eax, [ebp-0x34]
    add     eax, [ebp-0x40]          ; dy = py+dyi
    cmp     eax, 0
    jl      ynext
    cmp     eax, dword ptr [ebp-0x20]
    jge     ynext
    ; y-side: sy_num=dyi*den; y0=/num; rem; fy=rem*256/num; y1; yn
    mov     eax, [ebp-0x40]
    imul    eax, dword ptr [ebp-0x28]
    cdq
    idiv    dword ptr [ebp-0x24]
    mov     [ebp-0x48], eax          ; y0
    mov     ebx, edx                 ; rem
    mov     eax, edx
    shl     eax, 8
    cdq
    idiv    dword ptr [ebp-0x24]
    mov     [ebp-0x50], eax          ; fy
    mov     eax, [ebp-0x48]
    inc     eax
    mov     ecx, [ebp-0x10]
    dec     ecx
    cmp     eax, ecx
    jle     y1ok
    mov     eax, ecx
y1ok:
    mov     [ebp-0x4C], eax          ; y1
    mov     eax, ebx
    add     eax, eax
    cmp     eax, dword ptr [ebp-0x24]
    jl      ynusey0
    mov     eax, [ebp-0x4C]
    jmp     ynset
ynusey0:
    mov     eax, [ebp-0x48]
ynset:
    mov     [ebp-0x54], eax          ; yn
    ; row offsets
    mov     eax, [ebp-0x34]
    add     eax, [ebp-0x40]
    imul    eax, dword ptr [ebp-0x18]
    mov     [ebp-0x84], eax          ; drowoff
    mov     eax, [ebp-0x48]
    imul    eax, dword ptr [ebp-0x08]
    mov     [ebp-0x88], eax          ; sy0off
    mov     eax, [ebp-0x4C]
    imul    eax, dword ptr [ebp-0x08]
    mov     [ebp-0x8C], eax          ; sy1off

    mov     dword ptr [ebp-0x44], 0  ; dxi = 0
xloop:
    mov     eax, [ebp-0x44]
    cmp     eax, dword ptr [ebp-0x38]
    jge     xend
    mov     eax, [ebp-0x30]
    add     eax, [ebp-0x44]          ; dx = px+dxi
    cmp     eax, 0
    jl      xnext
    cmp     eax, dword ptr [ebp-0x1C]
    jge     xnext
    ; x-side
    mov     eax, [ebp-0x44]
    imul    eax, dword ptr [ebp-0x28]
    cdq
    idiv    dword ptr [ebp-0x24]
    mov     [ebp-0x74], eax          ; x0
    mov     ebx, edx                 ; rem
    mov     eax, edx
    shl     eax, 8
    cdq
    idiv    dword ptr [ebp-0x24]
    mov     [ebp-0x7C], eax          ; fx
    mov     eax, [ebp-0x74]
    inc     eax
    mov     ecx, [ebp-0x0C]
    dec     ecx
    cmp     eax, ecx
    jle     x1ok
    mov     eax, ecx
x1ok:
    mov     [ebp-0x78], eax          ; x1
    mov     eax, ebx
    add     eax, eax
    cmp     eax, dword ptr [ebp-0x24]
    jl      xnusex0
    mov     eax, [ebp-0x78]
    jmp     xnset
xnusex0:
    mov     eax, [ebp-0x74]
xnset:
    mov     [ebp-0x80], eax          ; xn
    ; coverage: src[xn + yn*sstride] == key ? skip
    mov     eax, [ebp-0x54]
    imul    eax, dword ptr [ebp-0x08]
    add     eax, [ebp-0x80]
    add     eax, [ebp-0x04]
    movzx   eax, byte ptr [eax]
    cmp     eax, dword ptr [ebp-0x2C]
    je      xnext
    ; zero accumulators
    mov     dword ptr [ebp-0x58], 0  ; accR
    mov     dword ptr [ebp-0x5C], 0  ; accG
    mov     dword ptr [ebp-0x60], 0  ; accB
    mov     dword ptr [ebp-0x64], 0  ; wt
    ; w00 (x0,y0) = (256-fx)*(256-fy)
    mov     eax, 256
    sub     eax, [ebp-0x7C]
    mov     ecx, 256
    sub     ecx, [ebp-0x50]
    imul    eax, ecx
    mov     edx, [ebp-0x74]
    add     edx, [ebp-0x88]
    add     edx, [ebp-0x04]
    movzx   edx, byte ptr [edx]
    call    accum
    ; w10 (x1,y0) = fx*(256-fy)
    mov     eax, [ebp-0x7C]
    mov     ecx, 256
    sub     ecx, [ebp-0x50]
    imul    eax, ecx
    mov     edx, [ebp-0x78]
    add     edx, [ebp-0x88]
    add     edx, [ebp-0x04]
    movzx   edx, byte ptr [edx]
    call    accum
    ; w01 (x0,y1) = (256-fx)*fy
    mov     eax, 256
    sub     eax, [ebp-0x7C]
    imul    eax, dword ptr [ebp-0x50]
    mov     edx, [ebp-0x74]
    add     edx, [ebp-0x8C]
    add     edx, [ebp-0x04]
    movzx   edx, byte ptr [edx]
    call    accum
    ; w11 (x1,y1) = fx*fy
    mov     eax, [ebp-0x7C]
    imul    eax, dword ptr [ebp-0x50]
    mov     edx, [ebp-0x78]
    add     edx, [ebp-0x8C]
    add     edx, [ebp-0x04]
    movzx   edx, byte ptr [edx]
    call    accum
    ; wt<=0 ? skip
    mov     ecx, [ebp-0x64]
    test    ecx, ecx
    jle     xnext
    mov     ebx, ecx
    shr     ebx, 1                   ; wt/2 (rounding bias)
    mov     eax, [ebp-0x58]
    add     eax, ebx
    cdq
    idiv    ecx
    mov     [ebp-0x68], eax          ; tR
    mov     eax, [ebp-0x5C]
    add     eax, ebx
    cdq
    idiv    ecx
    mov     [ebp-0x6C], eax          ; tG
    mov     eax, [ebp-0x60]
    add     eax, ebx
    cdq
    idiv    ecx
    mov     [ebp-0x70], eax          ; tB
    ; nearest palette index over 256 entries
    mov     esi, [ebp-0x90]          ; palbase (dest+0xA4)
    xor     ecx, ecx                 ; i
    mov     edi, 0                   ; best
    mov     ebx, 0x7FFFFFFF          ; bestdist
nloop:
    cmp     ecx, dword ptr [ebp-0x2C]
    je      nskip                    ; NEVER emit the transparency key (idx 9 = RGB (9,0,0):
                                     ; a dark blend maps there and the window composite punches
                                     ; a hole -> the map shows through the portrait)
    movzx   eax, byte ptr [esi]
    sub     eax, [ebp-0x68]
    imul    eax, eax
    mov     edx, eax
    movzx   eax, byte ptr [esi+1]
    sub     eax, [ebp-0x6C]
    imul    eax, eax
    add     edx, eax
    movzx   eax, byte ptr [esi+2]
    sub     eax, [ebp-0x70]
    imul    eax, eax
    add     edx, eax                 ; dist
    cmp     edx, ebx
    jge     nskip
    mov     ebx, edx
    mov     edi, ecx
nskip:
    add     esi, 4
    inc     ecx
    cmp     ecx, 256
    jl      nloop
    ; write dest pixel
    mov     eax, [ebp-0x30]
    add     eax, [ebp-0x44]          ; dx
    add     eax, [ebp-0x84]          ; +drowoff
    add     eax, [ebp-0x14]          ; +ddata
    mov     ecx, edi
    mov     [eax], cl
xnext:
    inc     dword ptr [ebp-0x44]
    jmp     xloop
xend:
ynext:
    inc     dword ptr [ebp-0x40]
    jmp     yloop
yend:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp                 ; discard locals (saved regs already restored above)
    pop     ebp
    ret     0x18

; ----- accum(eax=weight, edx=texel): if texel!=key, acc += pal[texel].rgb * weight; wt += weight
accum:
    cmp     edx, dword ptr [ebp-0x2C]
    je      accret
    mov     esi, eax                 ; weight
    lea     ecx, [edx*4]
    add     ecx, [ebp-0x90]          ; palptr (dest+0xA4)
    movzx   eax, byte ptr [ecx]
    imul    eax, esi
    add     [ebp-0x58], eax
    movzx   eax, byte ptr [ecx+1]
    imul    eax, esi
    add     [ebp-0x5C], eax
    movzx   eax, byte ptr [ecx+2]
    imul    eax, esi
    add     [ebp-0x60], eax
    add     [ebp-0x64], esi
accret:
    ret

; ----- not the portrait: run the 2 displaced instrs, resume original at 0x5E4B52
fallthrough:
    mov     eax, [esp+0x14]
    mov     edx, [esp+0x18]
    push    0x005E4B52
    ret
"""


# ===========================================================================
# thunk_sprite_scale_nn -- reusable edge-safe output-driven NN sprite->buffer scaler.
#
# General primitive (NOT faction-specific): any site that calls Sprite_draw_2 and wants
# crisp NN that does NOT drop the trailing edge at fractional scale can tail-jump here
# (`push {abs32:thunk_sprite_scale_nn}; ret`) as a drop-in. SAME contract as Sprite_draw_2:
#   ecx = Sprite*; stack = [ret, dest, key, x, y, num, den]; __stdcall, RET 0x18.
# Caller supplies dest Buffer + transparency key + dest origin (x,y) + scale ratio num/den;
# dstW = srcW*num/den, dstH = srcH*num/den (matches the engine + popup_scale's floor math); the
# scaled draw is placed at (x + iLeftOffset*num/den, y + iTopOffset*num/den).
# v2 2026-07-26l: the dest ORIGIN args are NOT scaled. v1 computed (x+off)*num/den "like the
# engine" citing Sprite_blit_scaled_core — but Sprite_draw_2 (the entry this is a drop-in for)
# does NOT scale its x/y args (proven: thunk_sb_thumb passed device coords at num=g/den=16 and
# placed correctly through the engine, then double-scaled through v1 = the 4K thumb-1/3-down +
# vanish-on-scroll regression). The faction-portrait caller zeroes x/y so v1==v2 for it.
#
# WHY this exists: the engine's Sprite_draw_2 NN is SOURCE-driven (a DDA over source pixels)
# which drops the last source col/row's output run at a fractional ratio -> the baked-in edge
# stroke disappears (item #1 @1600x1200, same class as the A5 portrait-frame drop). This is
# OUTPUT-driven: iterate every dest pixel, inverse-map a CENTER-SAMPLED, EDGE-CLAMPED source
# index, so the last dest col/row always reads the last source col/row -> the edge survives.
# Palette index copied VERBATIM (no blend, no palette search) -> crisp, palette-exact, thin
# 1px lines stay full-strength. Honors the sprite key (transparent texels skipped). Clips to
# the dest buffer bounds (safe for arbitrary caller rects). Upscale is lossless; NN is lossy on
# DOWNSCALE (skips source px) -- callers gate g>16 so this primitive only ever upscales here.
#
# Reentrant/leaf: stack-only locals, saves+restores ebx/esi/edi, no shared cave scratch.
# On ANY guard failure (den<=0, zero src/dest dims or pointers) it tail-jumps to the engine
# Sprite_draw_2 (native NN) so degenerate cases still draw rather than vanish.
#
# Sprite struct (engine semantics, confirmed live via Frida + Sprite_blit_scaled_core decompile):
#   pcBits@+0x4, key@+0x8, ROW PITCH iSpriteWidth2@+0xC (<=0 -> fall back to width), blit width
#   iSpriteWidth@+0x10, blit height iSpriteHeight@+0x14, iLeftOffset@+0x20, iTopOffset@+0x24.
#   iWidth@+0x18 / iHeight@+0x1c are the LOGICAL CANVAS (incl. transparent margins) -- do NOT use.
# Dest Buffer:   data@+0x54, stride@+0x4a8, w@+0x80, h@+0x84 (negative = top-down).
# Frame layout mirrors thunk_portrait_avg's fix: reserve locals BEFORE pushing ebx/esi/edi
# (else the saved regs alias the local slots -> caller AV; see feedback-thunk-frame-aliasing).
ASM_NN = r"""
; ===== guards (entry stack/ecx state; no frame built yet) =====
    mov     eax, [esp+0x18]          ; den
    test    eax, eax
    jle     nn_native                ; den<=0 -> native (avoid idiv #DE)
    mov     eax, [ecx+0x10]          ; src w  (iSpriteWidth, the engine's blit width)
    test    eax, eax
    jle     nn_native
    mov     eax, [ecx+0x14]          ; src h  (iSpriteHeight)
    test    eax, eax
    jle     nn_native
    mov     eax, [ecx+0x04]          ; src data (pcBits)
    test    eax, eax
    je      nn_native
    mov     eax, [esp+0x04]          ; dest ptr
    mov     eax, [eax+0x54]          ; dest data
    test    eax, eax
    je      nn_native
    mov     eax, [esp+0x04]
    mov     eax, [eax+0x4a8]         ; dest stride
    test    eax, eax
    jle     nn_native

; ===== build frame (reserve locals FIRST, then save callee-saved) =====
    push    ebp
    mov     ebp, esp
    sub     esp, 0x60
    push    ebx
    push    esi
    push    edi
    ; --- source (Sprite*) fields from ecx (engine semantics from Sprite_blit_scaled_core):
    ;     pcBits@+0x4, key@+0x8, ROW PITCH = iSpriteWidth2@+0xC, blit W = iSpriteWidth@+0x10,
    ;     blit H = iSpriteHeight@+0x14, left/top draw offset = iLeftOffset@+0x20 / iTopOffset@+0x24.
    ;     (NOT iWidth@+0x18 / iHeight@+0x1c -- those are the logical canvas incl. transparent margins.)
    mov     eax, [ecx+0x04]
    mov     [ebp-0x04], eax          ; sdata
    mov     eax, [ecx+0x0C]          ; pitch (iSpriteWidth2)
    cmp     eax, 0
    jg      nn_sstr_ok               ; pitch<=0 -> fall back to blit width
    mov     eax, [ecx+0x10]
nn_sstr_ok:
    mov     [ebp-0x08], eax          ; sstride (row pitch)
    mov     eax, [ecx+0x10]
    mov     [ebp-0x0C], eax          ; sw (iSpriteWidth)
    mov     eax, [ecx+0x14]
    mov     [ebp-0x10], eax          ; sh (iSpriteHeight)
    ; --- dest Buffer fields ---
    mov     eax, [ebp+0x08]          ; dest ptr
    mov     edx, [eax+0x54]
    mov     [ebp-0x14], edx          ; ddata
    mov     edx, [eax+0x4a8]
    mov     [ebp-0x18], edx          ; dstride
    mov     edx, [eax+0x80]
    mov     [ebp-0x1C], edx          ; dwid
    mov     edx, [eax+0x84]
    neg     edx
    mov     [ebp-0x20], edx          ; dhgt (abs)
    ; --- scalars ---
    mov     eax, [ebp+0x18]
    mov     [ebp-0x24], eax          ; num
    mov     eax, [ebp+0x1c]
    mov     [ebp-0x28], eax          ; den
    mov     eax, [ebp+0x0c]
    mov     [ebp-0x2C], eax          ; key
    ; px = x + iLeftOffset*num/den ; py = y + iTopOffset*num/den
    ; (v2: origin args UNSCALED — Sprite_draw_2 semantics; only the sprite's own
    ;  draw offsets scale. ecx still = Sprite* here.)
    mov     eax, [ecx+0x20]          ; iLeftOffset
    imul    eax, dword ptr [ebp-0x24] ; * num
    cdq
    idiv    dword ptr [ebp-0x28]     ; / den
    add     eax, [ebp+0x10]          ; + x (dest origin, unscaled)
    mov     [ebp-0x30], eax          ; px (dstX)
    mov     eax, [ecx+0x24]          ; iTopOffset
    imul    eax, dword ptr [ebp-0x24] ; * num
    cdq
    idiv    dword ptr [ebp-0x28]     ; / den
    add     eax, [ebp+0x14]          ; + y (dest origin, unscaled)
    mov     [ebp-0x34], eax          ; py (dstY)
    ; --- dstW = sw*num/den ; dstH = sh*num/den (floor, matches popup_scale) ---
    mov     eax, [ebp-0x0C]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    mov     [ebp-0x38], eax          ; dstW
    mov     eax, [ebp-0x10]
    imul    eax, dword ptr [ebp-0x24]
    cdq
    idiv    dword ptr [ebp-0x28]
    mov     [ebp-0x3C], eax          ; dstH

    mov     dword ptr [ebp-0x40], 0  ; dyi = 0
nn_yloop:
    mov     eax, [ebp-0x40]
    cmp     eax, dword ptr [ebp-0x3C]
    jge     nn_yend
    ; dy = py+dyi, clip to dest
    mov     eax, [ebp-0x34]
    add     eax, [ebp-0x40]
    cmp     eax, 0
    jl      nn_ynext
    cmp     eax, dword ptr [ebp-0x20]
    jge     nn_ynext
    ; sy = ((2*dyi+1)*sh) / (2*dstH), clamp [0, sh-1]  (center-sampled inverse map)
    mov     eax, [ebp-0x40]
    add     eax, eax
    inc     eax
    imul    eax, dword ptr [ebp-0x10]
    cdq
    mov     ecx, [ebp-0x3C]
    add     ecx, ecx
    idiv    ecx
    mov     ecx, [ebp-0x10]
    dec     ecx
    cmp     eax, ecx
    jle     nn_syhi
    mov     eax, ecx
nn_syhi:
    test    eax, eax
    jns     nn_sylo
    xor     eax, eax
nn_sylo:
    imul    eax, dword ptr [ebp-0x08] ; *sstride
    mov     [ebp-0x4C], eax          ; srowoff
    ; drowoff = dy*dstride
    mov     eax, [ebp-0x34]
    add     eax, [ebp-0x40]
    imul    eax, dword ptr [ebp-0x18]
    mov     [ebp-0x50], eax          ; drowoff

    mov     dword ptr [ebp-0x44], 0  ; dxi = 0
nn_xloop:
    mov     eax, [ebp-0x44]
    cmp     eax, dword ptr [ebp-0x38]
    jge     nn_xend
    ; dx = px+dxi, clip to dest
    mov     eax, [ebp-0x30]
    add     eax, [ebp-0x44]
    cmp     eax, 0
    jl      nn_xnext
    cmp     eax, dword ptr [ebp-0x1C]
    jge     nn_xnext
    ; sx = ((2*dxi+1)*sw) / (2*dstW), clamp [0, sw-1]
    mov     eax, [ebp-0x44]
    add     eax, eax
    inc     eax
    imul    eax, dword ptr [ebp-0x0C]
    cdq
    mov     ecx, [ebp-0x38]
    add     ecx, ecx
    idiv    ecx
    mov     ecx, [ebp-0x0C]
    dec     ecx
    cmp     eax, ecx
    jle     nn_sxhi
    mov     eax, ecx
nn_sxhi:
    test    eax, eax
    jns     nn_sxlo
    xor     eax, eax
nn_sxlo:
    ; texel = src[srowoff + sx]
    add     eax, [ebp-0x4C]
    add     eax, [ebp-0x04]
    movzx   eax, byte ptr [eax]
    cmp     eax, dword ptr [ebp-0x2C] ; key? -> transparent
    je      nn_xnext
    ; dest[drowoff + dx] = texel (verbatim palette index)
    mov     ecx, eax
    mov     eax, [ebp-0x30]
    add     eax, [ebp-0x44]          ; dx
    add     eax, [ebp-0x50]          ; +drowoff
    add     eax, [ebp-0x14]          ; +ddata
    mov     [eax], cl
nn_xnext:
    inc     dword ptr [ebp-0x44]
    jmp     nn_xloop
nn_xend:
nn_ynext:
    inc     dword ptr [ebp-0x40]
    jmp     nn_yloop
nn_yend:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x18

; ----- guard failure: tail-jump engine Sprite_draw_2 (native NN), entry stack intact
nn_native:
    push    0x005E4B4A
    ret
"""


def main():
    out = open(r"D:\SmacxUi\work\patches\resampler_hex.txt", "w")
    def w(s):
        out.write(s + "\n"); out.flush()
    try:
        ks = Ks(KS_ARCH_X86, KS_MODE_32)
        w("; keystone ready")

        # keystone's MC parser does not treat ';' as a comment -- strip comments ourselves.
        def assemble(asm, va):
            clean = "\n".join(
                ln.split(";", 1)[0].rstrip()
                for ln in asm.splitlines()
                if ln.split(";", 1)[0].strip()
            )
            return ks.asm(clean, va)

        enc, count = assemble(ASM, THUNK_VA)
        hexbytes = " ".join("%02X" % b for b in enc)
        w(f"; thunk_portrait_avg @ VA 0x{THUNK_VA:X} (pcave2 +0x{THUNK_OFF:X})")
        w(f"; {len(enc)} bytes, {count} statements; ends at pcave2 +0x{THUNK_OFF+len(enc):X}")
        if THUNK_OFF + len(enc) > 0x1000:
            w("; !!! OVERFLOWS pcave2 (0x1000) -- grow the section length")
        w(hexbytes)

        enc2, count2 = assemble(ASM_NN, NN_VA)
        hex2 = " ".join("%02X" % b for b in enc2)
        w("")
        w(f"; thunk_sprite_scale_nn @ VA 0x{NN_VA:X} (pcave2 +0x{NN_OFF:X})")
        w(f"; {len(enc2)} bytes, {count2} statements; ends at pcave2 +0x{NN_OFF+len(enc2):X}")
        if NN_OFF + len(enc2) > 0x2400:
            w("; !!! OVERFLOWS pcave2 free region (0x2400) -- grow the section length")
        w(hex2)
    except Exception as e:
        w(f"; ERROR: {type(e).__name__}: {e}")
        out.close()
        raise
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
