"""Assemble the banding re-stripe thunks (bake of hook_band_fixproto.js, USER-CONFIRMED
2026-07-06 at 1600 [MENU/COMMLINK + banner] and 1920 [banner]).

Both defects = 1px scanline dither pairs beaten by the fractional-NN stretch (census:
frida_band_census.log + flc_census.py). Fix = re-stripe the pair pixels at device density
(P-law: P=(g+4)>>3, hN=(P+1)>>1, phase = owning-buffer row) AFTER the existing stretch.
No shared thunk is modified; two call-site retargets route through drop-in wrappers:

restripe_core (internal, callee-clean RET 0x20):
  (buf, rx, ry, rw, rh, a, b, top) -> rewrite pixels ∈ {a,b} in the rect to
  (y%P<hN ? top : a^b^top). Clips rw against stride-rx ONLY — never the buffer W/H
  fields (mid-bracket they hold the SHRUNKEN native dims, the prototype-v1 half-remap
  bug). Callers guarantee ry+rh is within the allocation.

thunk_band_stretch_remap (thiscall drop-in for Buffer_copy_3, RET 0x24):
  retargeted from thunk_band_draw's internal stretch call. Forwards to Buffer_copy_3,
  then detects the pair from the native scratch at (sw/2, sh/2)/(sw/2, sh/2+1) — the
  flash anim recolors the SAME layout with a DIFFERENT pair per frame, so per-draw
  detection is mandatory — and re-stripes the dest rect. Skips when the probe rows are
  equal or hit key 0x09 / border 0x65 (black frame, non-dither content). top = the
  even-native-row member (matches the band sprite's 92-on-top language).

thunk_btn_bandstripe v2 (drop-in for thunk_keyed_stretch_blit, callee-clean RET 0x2C):
  retargeted from thunk_btn_2dscale's stretch call (esi = FlatButton at that site).
  Forwards to KSB; iff esi ∈ {MENU,COMMLINK} DETECTS the pair from the native source
  window at (sx+2, sy+sh/2)/(sx+2, sy+sh/2+1) and re-stripes it over the dest rect.
  v1 hardcoded {0xC8,0x92} = the IDLE band sprite only; the button has THREE state
  band sprites (0x7d059c idle 92/C8, 0x7d05c8 hover E6/E7, 0x7d05f4 pressed 63/66 —
  frida_band_census.log v2 run 2026-07-06), all pure 1px pairs, text drawn post-stretch,
  so per-state detection is safe and total. Sample col sx+2 avoids the border cols
  (0/1) and any stray text-AA pixels near center; rows sh/2,sh/2+1 avoid border rows
  0/sh-1. top = the even-native-row member. Skip on equal or key 9 (solid/no dither).
  WORLD/DETAIL dropped from the gate (v1 restriped C8/92 over them = untargeted):
  they take the plain KSB path, byte-identical to pre-fix behavior.
  Pair-ambiguity rule: C8/92 is legit art shading in unit sprites — the esi identity
  gate scopes it, NEVER add these pairs to fe_pair_remap.

g<=16: neither wrapper can fire (band_draw tails native pre-stretch; g_btn_pending only
set at g>16) -> native no-op by construction.
"""
import pathlib
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scaling_laws as SL  # noqa: E402  (thunk_chev_coverage is a PORT of it)

PCAVE2_VA = 0x00A0C000
CORE_OFF,  CORE_BUDGET  = 0x5A00, 0xB0
BAND_OFF,  BAND_BUDGET  = 0x5AB0, 0xA0
BTN_OFF,   BTN_BUDGET   = 0xC800, 0x200   # v7 RELOCATED from 0xC540 (2026-07-22d: the
                                          # chevron-exclusion gate outgrew the 192B slot;
                                          # old 0xC540..0xC5FF freed/zeros; 0xC800 = the
                                          # 07-22b cave growth, formerly the deleted
                                          # bandstripe2 helper's slot)
CHEV_OFF,  CHEV_BUDGET  = 0xCA00, 0x380   # v8 thunk_chev_coverage (2026-07-24 approved
                                          # "coverage linear g2.2" candidate; 832B)
LUT_OFF                 = 0xCD80          # 512B DATA: SRGB_LIN16 gamma-2.2 LUT (u16 LE)
SCRATCH_OFF             = 0xCF80          # 400B BSS: native 20x20 art snapshot
                                          # (cave grown 0xD000->0xD800 for these)
STAPLE_OFF, STAPLE_BUDGET = 0xE000, 0x360 # v9 thunk_staple_coverage: the N=48
                                          # instance of the coverage template for
                                          # the nerve-staple button (btn16) art
SCRATCH48_OFF           = 0xE360          # 2304B BSS: native 48x48 art snapshot
                                          # (cave grown 0xE000->0xF000 for these)
ARROW_OFF, ARROW_BUDGET = 0xF000, 0x360   # v10 thunk_arrow_coverage: 12x42 RECT
                                          # instance for the garrison/HUD unit-row
                                          # arrow art (buttons[8..10]; the hover
                                          # state is a 1px stripe dither -> NN
                                          # phase-flip banding, chevron class)
SCRATCH_ARROW_OFF       = 0xF360          # 504B BSS: native 12x42 art snapshot
                                          # (cave grown 0xF000->0x10000 for these)

S = {
    "g_popup_scale_num":  0x668740,
    "Buffer_copy_3":      0x5D9610,   # thiscall(src; dst,sx,sy,sw,sh,dx,dy,dw,dh) RET 0x24
    "KSB":                0x668670,   # thunk_keyed_stretch_blit, 11 args, callee-clean RET 0x2C
    "restripe_core":      PCAVE2_VA + CORE_OFF,
    "BTN_MENU":           0x7B1804,
    "BTN_COMMLINK":       0x7B2350,
    "BTN_WORLD":          0x7B39E8,
    "BTN_DETAIL":         0x7B4534,
    "BASEWIN_BTN_LO":     0x6B4DE8,   # BaseWin's 22 FlatButtons array
    "BASEWIN_BTN_HI":     0x6C4670,   # exclusive end (22 * 0xB4C)
    "BILINEAR":           PCAVE2_VA + 0x2960,   # thunk_bilinear_blit, KSB drop-in
    "BTN_CHEV1":          0x6C1940,   # BaseWin btn18 = GOVERNOR left chevron (base+18*0xB4C)
    "BTN_CHEV2":          0x6C248C,   # BaseWin btn19 = right chevron (v8: coverage filter)
    "BTN_STAPLE":         0x6C02A8,   # BaseWin btn16 = nerve-staple button (base+16*0xB4C;
                                      # 48x48 KSB art; v9: coverage filter — the pair-
                                      # restripe remapped the bg stripe pair THROUGH the
                                      # face art, dither-pair-ambiguity class)
    "PALETTE":            0x94C590,   # global Palette: PALETTEENTRY[256] (r,g,b,flags)
    "CHEVCOV":            PCAVE2_VA + CHEV_OFF,
    "STAPLECOV":          PCAVE2_VA + STAPLE_OFF,
    "LUT":                PCAVE2_VA + LUT_OFF,
    "SCRATCH":            PCAVE2_VA + SCRATCH_OFF,
    "SCRATCH48":          PCAVE2_VA + SCRATCH48_OFF,
    "BTN_ARROW1":         0x7B5080,   # MainWin buttons[8] — garrison/HUD unit-row arrows
    "BTN_ARROW2":         0x7B5BCC,   # buttons[9] (shares the left 12x42 art set with [8])
    "BTN_ARROW3":         0x7B6718,   # buttons[10] (right 12x42 art set)
    "ARROWCOV":           PCAVE2_VA + ARROW_OFF,
    "SBT_ZOOM":           PCAVE2_VA + 0x3C600,   # t_sbt_zoom (assemble_stripes_btn.py; 2026-10-25 W7H relocated from 0x12A20): KSB drop-in, dither regenerated on the stripe law
    "SCRATCH_ARROW":      PCAVE2_VA + SCRATCH_ARROW_OFF,
}

CORE = f"""
    push ebp
    mov ebp, esp
    sub esp, 8
    push ebx
    push esi
    push edi
    mov eax, dword ptr [{S['g_popup_scale_num']:#x}]
    mov eax, dword ptr [0x66879c]
    nop
    test eax, eax
    jle rdone
    mov dword ptr [ebp-4], eax
    mov ecx, eax
    inc ecx
    shr ecx, 1
    mov dword ptr [ebp-8], ecx
    mov ebx, dword ptr [ebp+8]
    mov esi, dword ptr [ebx+0x54]
    test esi, esi
    je rdone
    mov edi, dword ptr [ebx+0x4A8]
    test edi, edi
    jle rdone
    mov ecx, edi
    sub ecx, dword ptr [ebp+0xC]
    cmp ecx, dword ptr [ebp+0x14]
    jge rw_ok
    mov dword ptr [ebp+0x14], ecx
rw_ok:
    cmp dword ptr [ebp+0x14], 0
    jle rdone
    mov eax, dword ptr [ebp+0x10]
    imul eax, edi
    add eax, dword ptr [ebp+0xC]
    add esi, eax
    mov eax, dword ptr [ebp+0x10]
    cdq
    idiv dword ptr [ebp-4]
rowloop:
    cmp dword ptr [ebp+0x18], 0
    jle rdone
    mov eax, dword ptr [ebp+0x24]
    cmp edx, dword ptr [ebp-8]
    jl havec
    xor eax, dword ptr [ebp+0x1C]
    xor eax, dword ptr [ebp+0x20]
havec:
    push edx
    push esi
    mov ecx, dword ptr [ebp+0x14]
xloop:
    mov dl, byte ptr [esi]
    cmp dl, byte ptr [ebp+0x1C]
    je xstore
    cmp dl, byte ptr [ebp+0x20]
    jne xnext
xstore:
    mov byte ptr [esi], al
xnext:
    inc esi
    dec ecx
    jnz xloop
    pop esi
    pop edx
    add esi, edi
    inc edx
    cmp edx, dword ptr [ebp-4]
    jl nowrap
    xor edx, edx
nowrap:
    dec dword ptr [ebp+0x18]
    jmp rowloop
rdone:
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    ret 0x20
"""

BAND = f"""
    push ebp
    mov ebp, esp
    push ebx
    push esi
    push edi
    mov esi, ecx
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push dword ptr [ebp+0x18]
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xC]
    push dword ptr [ebp+8]
    mov ecx, esi
    call {S['Buffer_copy_3']:#x}
    mov eax, dword ptr [esi+0x54]
    test eax, eax
    je bdone
    mov ecx, dword ptr [esi+0x4A8]
    test ecx, ecx
    jle bdone
    mov edx, dword ptr [ebp+0x18]
    sar edx, 1
    mov ebx, edx
    and ebx, 1
    imul edx, ecx
    add edx, eax
    mov eax, dword ptr [ebp+0x14]
    sar eax, 1
    add edx, eax
    movzx eax, byte ptr [edx]
    movzx edi, byte ptr [edx+ecx]
    cmp eax, edi
    je bdone
    cmp eax, 9
    je bdone
    cmp edi, 9
    je bdone
    cmp eax, 0x65
    je bdone
    cmp edi, 0x65
    je bdone
    mov ecx, eax
    test ebx, ebx
    je topok
    mov ecx, edi
topok:
    push ecx
    push edi
    push eax
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push dword ptr [ebp+8]
    call {S['restripe_core']:#x}
bdone:
    xor eax, eax
    pop edi
    pop esi
    pop ebx
    pop ebp
    ret 0x24
"""

# v7 (2026-07-22d): the GOVERNOR chevrons (btn18/btn19) are EXCLUDED from the
# restripe — plain KSB zoom only. Side-by-side comparison (pristine capture vs
# raw NN vs the v5.1 P-law vs the v6 balanced pattern, all at g=25) showed the
# ENGINE'S OWN centre-NN zoom of the chevron art is the closest match to
# pristine; every synthesized pattern either recolors the high-contrast
# orange/red pair (P-law 2:1 = "mostly red") or coarsens the 1px texture into
# 2px bands (balanced 2P = "muddy"). The original "color irregularities" report
# was v4's OWN flank restripe (2:1, light-heavy at g=22 / dark-heavy at g=25)
# clashing with the raw glyph triangle — the treatment was the defect. The bar
# buttons KEEP the restripe (their low-contrast wood pair hides the 2:1 duty
# and the de-banding is user-approved).
# v4 (2026-07-21c): BaseWin tab/row FlatButtons JOIN the KSB + pair-restripe
# path (the MENU/COMMLINK band treatment) instead of v3's bilinear tail. The
# basewin11 census proved v3's bilinear output was always fully overpainted by
# thunk_btn_devfill's 1:1 native full-bleed re-tile (the visible "stamp lines"
# = the 20-row art repeating at y=20/40 in the 50-device-tall bars) -- the
# bilinear never reached the screen, and bilinear would blur the scanline pair
# anyway. The tab art (screenshot pixel census 2026-07-21) = ONE dominant 1px
# scanline pair + a solid highlight band + wood-gradient rows: NN zoom keeps
# the gradient/caps vanilla-proportionate and the per-draw pair-detect
# restripes the scanlines at device density (per state -- normal/hover/
# pressed art each carry their own pair). thunk_btn_stripes v3 skips the
# devfill full-bleed for the same esi range so this output stays visible.
# BILINEAR retained in S for reference; no longer referenced by the thunk.
# v8 (2026-07-24, approved candidate "coverage linear g2.2"): the chevrons get
# thunk_chev_coverage INSTEAD of the KSB — coverage(area)-weighted linear-light
# (gamma 2.2) zoom of the native art, redmean-quantized to the live palette.
# Raw NN was pixel-diff-proven faithful yet still read wrong: the art is a
# horizontal 1px 50/50 stripe DITHER and fractional NN duplicates one color's
# rows in phase-flipped clusters (g=25: red doubled top half / orange bottom).
# See scaling_laws.chevron_coverage_filter (the SPEC this thunk ports).
BTN = f"""
    push ebp
    mov ebp, esp
    push ebx
    xor ebx, ebx
    cmp esi, {S['BTN_MENU']:#x}
    je bmatch
    cmp esi, {S['BTN_COMMLINK']:#x}
    je bmatch
    cmp esi, {S['BTN_CHEV1']:#x}
    je bchev
    cmp esi, {S['BTN_CHEV2']:#x}
    je bchev
    cmp esi, {S['BTN_STAPLE']:#x}
    je bstap
    cmp esi, {S['BTN_ARROW1']:#x}
    je barw
    cmp esi, {S['BTN_ARROW2']:#x}
    je barw
    cmp esi, {S['BTN_ARROW3']:#x}
    je barw
    cmp esi, {S['BASEWIN_BTN_LO']:#x}
    jb bnom
    cmp esi, {S['BASEWIN_BTN_HI']:#x}
    jae bnom
bmatch:
    mov ebx, 1
bnom:
    push dword ptr [ebp+0x30]
    push dword ptr [ebp+0x2C]
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push dword ptr [ebp+0x18]
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xC]
    push dword ptr [ebp+8]
    call {S['SBT_ZOOM']:#x}
    test ebx, ebx
    je bsdone
    mov edx, dword ptr [ebp+8]
    mov eax, dword ptr [edx+0x54]
    test eax, eax
    je bsdone
    mov ecx, dword ptr [edx+0x4A8]
    test ecx, ecx
    jle bsdone
    mov edx, dword ptr [ebp+0x1C]
    sar edx, 1
    add edx, dword ptr [ebp+0x14]
    mov ebx, edx
    and ebx, 1
    imul edx, ecx
    add eax, edx
    add eax, dword ptr [ebp+0x10]
    movzx edx, byte ptr [eax+2]
    movzx eax, byte ptr [eax+ecx+2]
    cmp edx, eax
    je bsdone
    cmp edx, 9
    je bsdone
    cmp eax, 9
    je bsdone
    mov ecx, edx
    test ebx, ebx
    je topok2
    mov ecx, eax
topok2:
    push ecx
    push eax
    push edx
    push dword ptr [ebp+0x2C]
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0xC]
    call {S['restripe_core']:#x}
bsdone:
    pop ebx
    pop ebp
    ret 0x2C
bchev:
    push dword ptr [ebp+0x30]
    push dword ptr [ebp+0x2C]
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push dword ptr [ebp+0x18]
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xC]
    push dword ptr [ebp+8]
    call {S['CHEVCOV']:#x}
    jmp bsdone
bstap:
    push dword ptr [ebp+0x30]
    push dword ptr [ebp+0x2C]
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push dword ptr [ebp+0x18]
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xC]
    push dword ptr [ebp+8]
    call {S['STAPLECOV']:#x}
    jmp bsdone
barw:
    push dword ptr [ebp+0x30]
    push dword ptr [ebp+0x2C]
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    push dword ptr [ebp+0x20]
    push dword ptr [ebp+0x1C]
    push dword ptr [ebp+0x18]
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xC]
    push dword ptr [ebp+8]
    call {S['SBT_ZOOM']:#x}
    jmp bsdone
"""

# thunk_chev_coverage — KSB-compatible drop-in (11 args, callee-clean RET 0x2C):
#   (dst_buf, src_buf, sx, sy, sw, sh, dx, dy, dw, dh, key)
# PORT of scaling_laws.chevron_coverage_filter: snapshot the native 20x20 art
# from the canvas (it is about to be overwritten in place), then per dest pixel
# average the <=4 geometrically-covered texels in LINEAR light (SRGB_LIN16 LUT),
# key-9 texels excluded and renormalized (>=half key coverage -> dest = key 9,
# the transparent corner notch), inverse-gamma by binary search over the LUT,
# and write the redmean-nearest non-key palette index (Palette @0x94C590).
# Guards: sw==sh==20 and 20<dw,dh<=50 and live data/stride — else unwind the
# frame and TAIL-JMP the KSB (args + return address still in place, KSB rets
# 0x2C: behavior identical to v7's plain zoom; this is also the g<=16 path
# since dw==20 there). Frame law: locals reserved BEFORE the callee-saved
# pushes (thunk_frame_aliasing lesson). Single-threaded draw => static scratch.
def coverage_code(N: int, dmax: int, scratch: int) -> str:
    """The coverage-zoom thunk body for N x N art (KSB drop-in, RET 0x2C).

    N=20 + SCRATCH = the LOCKED v8 chevron instance (asserted byte-identical
    to the baked yaml bytes at bake time); N=48 + SCRATCH48 = the staple
    button (btn16) instance.  Same instruction stream, only the immediates
    (N, N*N, dmax) and the snapshot scratch address differ.  Guards:
    sw==sh==N and N<dw,dh<=dmax — else unwind and TAIL-JMP the KSB (also the
    g<=16 path, where dw==N).  <=4 taps requires dw,dh>=N (upscale) — the
    guard enforces it."""
    NN = N * N
    return f"""
    push ebp
    mov ebp, esp
    sub esp, 0x70
    push ebx
    push esi
    push edi
    cmp dword ptr [ebp+0x18], {N}
    jne fallb
    cmp dword ptr [ebp+0x1C], {N}
    jne fallb
    mov eax, dword ptr [ebp+0x28]
    cmp eax, {N}
    jle fallb
    cmp eax, {dmax}
    jg fallb
    mov edx, dword ptr [ebp+0x2C]
    cmp edx, {N}
    jle fallb
    cmp edx, {dmax}
    jg fallb
    mov ebx, dword ptr [ebp+8]
    mov eax, dword ptr [ebx+0x54]
    test eax, eax
    je fallb
    mov dword ptr [ebp-4], eax
    mov ecx, dword ptr [ebx+0x4A8]
    test ecx, ecx
    jle fallb
    mov dword ptr [ebp-8], ecx
    mov eax, dword ptr [ebp+0x28]
    mov dword ptr [ebp-0xC], eax
    mov eax, dword ptr [ebp+0x2C]
    mov dword ptr [ebp-0x10], eax
    mov eax, dword ptr [ebp+0x14]
    imul eax, dword ptr [ebp-8]
    add eax, dword ptr [ebp+0x10]
    add eax, dword ptr [ebp-4]
    mov esi, eax
    mov edi, {scratch:#x}
    mov ebx, {N}
cploop:
    mov ecx, {N // 4}
cpword:
    mov eax, dword ptr [esi]
    mov dword ptr [edi], eax
    add esi, 4
    add edi, 4
    dec ecx
    jnz cpword
    add esi, dword ptr [ebp-8]
    sub esi, {N}
    dec ebx
    jnz cploop
    mov dword ptr [ebp-0x14], 0
yloop:
    mov eax, dword ptr [ebp-0x14]
    mov ecx, dword ptr [ebp-0x10]
    call taps
    mov dword ptr [ebp-0x1C], eax
    mov dword ptr [ebp-0x20], edx
    mov eax, {N}
    sub eax, edx
    mov dword ptr [ebp-0x24], eax
    mov eax, dword ptr [ebp+0x24]
    add eax, dword ptr [ebp-0x14]
    imul eax, dword ptr [ebp-8]
    add eax, dword ptr [ebp+0x20]
    add eax, dword ptr [ebp-4]
    mov dword ptr [ebp-0x50], eax
    mov dword ptr [ebp-0x18], 0
xloop:
    mov eax, dword ptr [ebp-0x18]
    mov ecx, dword ptr [ebp-0xC]
    call taps
    mov dword ptr [ebp-0x28], eax
    mov dword ptr [ebp-0x2C], edx
    mov eax, {N}
    sub eax, edx
    mov dword ptr [ebp-0x30], eax
    xor eax, eax
    mov dword ptr [ebp-0x34], eax
    mov dword ptr [ebp-0x38], eax
    mov dword ptr [ebp-0x3C], eax
    mov dword ptr [ebp-0x40], eax
    mov eax, dword ptr [ebp-0x20]
    imul eax, dword ptr [ebp-0x2C]
    imul edx, dword ptr [ebp-0x1C], {N}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch:#x}]
    call acc4
    cmp dword ptr [ebp-0x30], 0
    je no01
    mov eax, dword ptr [ebp-0x20]
    imul eax, dword ptr [ebp-0x30]
    imul edx, dword ptr [ebp-0x1C], {N}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch + 1:#x}]
    call acc4
no01:
    cmp dword ptr [ebp-0x24], 0
    je no1x
    mov eax, dword ptr [ebp-0x24]
    imul eax, dword ptr [ebp-0x2C]
    imul edx, dword ptr [ebp-0x1C], {N}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch + N:#x}]
    call acc4
    cmp dword ptr [ebp-0x30], 0
    je no1x
    mov eax, dword ptr [ebp-0x24]
    imul eax, dword ptr [ebp-0x30]
    imul edx, dword ptr [ebp-0x1C], {N}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch + N + 1:#x}]
    call acc4
no1x:
    mov eax, dword ptr [ebp-0x40]
    add eax, eax
    cmp eax, {NN}
    jl colpix
    mov dword ptr [ebp-0x5C], 9
    jmp wrpix
colpix:
    mov eax, {NN}
    sub eax, dword ptr [ebp-0x40]
    mov dword ptr [ebp-0x54], eax
    shr eax, 1
    mov dword ptr [ebp-0x58], eax
    mov eax, dword ptr [ebp-0x34]
    add eax, dword ptr [ebp-0x58]
    xor edx, edx
    div dword ptr [ebp-0x54]
    call invg
    mov dword ptr [ebp-0x44], ecx
    mov eax, dword ptr [ebp-0x38]
    add eax, dword ptr [ebp-0x58]
    xor edx, edx
    div dword ptr [ebp-0x54]
    call invg
    mov dword ptr [ebp-0x48], ecx
    mov eax, dword ptr [ebp-0x3C]
    add eax, dword ptr [ebp-0x58]
    xor edx, edx
    div dword ptr [ebp-0x54]
    call invg
    mov dword ptr [ebp-0x4C], ecx
    mov esi, {S['PALETTE']:#x}
    xor ecx, ecx
    mov edi, 0x7FFFFFFF
    mov dword ptr [ebp-0x5C], 0
nloop:
    cmp ecx, 9
    je nnext
    movzx eax, byte ptr [esi]
    mov edx, eax
    add edx, dword ptr [ebp-0x44]
    shr edx, 1
    mov dword ptr [ebp-0x60], edx
    sub eax, dword ptr [ebp-0x44]
    imul eax, eax
    mov edx, dword ptr [ebp-0x60]
    add edx, 512
    imul eax, edx
    mov dword ptr [ebp-0x64], eax
    movzx eax, byte ptr [esi+1]
    sub eax, dword ptr [ebp-0x48]
    imul eax, eax
    shl eax, 10
    add dword ptr [ebp-0x64], eax
    movzx eax, byte ptr [esi+2]
    sub eax, dword ptr [ebp-0x4C]
    imul eax, eax
    mov edx, 767
    sub edx, dword ptr [ebp-0x60]
    imul eax, edx
    add eax, dword ptr [ebp-0x64]
    cmp eax, edi
    jge nnext
    mov edi, eax
    mov dword ptr [ebp-0x5C], ecx
nnext:
    add esi, 4
    inc ecx
    cmp ecx, 256
    jl nloop
wrpix:
    mov edx, dword ptr [ebp-0x50]
    add edx, dword ptr [ebp-0x18]
    mov eax, dword ptr [ebp-0x5C]
    mov byte ptr [edx], al
    inc dword ptr [ebp-0x18]
    mov eax, dword ptr [ebp-0x18]
    cmp eax, dword ptr [ebp-0xC]
    jl xloop
    inc dword ptr [ebp-0x14]
    mov eax, dword ptr [ebp-0x14]
    cmp eax, dword ptr [ebp-0x10]
    jl yloop
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    ret 0x2C
fallb:
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    jmp {S['KSB']:#x}
taps:
    imul eax, eax, {N}
    xor edx, edx
    div ecx
    neg edx
    add edx, ecx
    cmp edx, {N}
    jle tret
    mov edx, {N}
tret:
    ret
acc4:
    cmp edx, 9
    jne acc_col
    add dword ptr [ebp-0x40], eax
    ret
acc_col:
    push esi
    lea esi, [edx*4 + {S['PALETTE']:#x}]
    movzx edx, byte ptr [esi]
    movzx edx, word ptr [edx*2 + {S['LUT']:#x}]
    imul edx, eax
    add dword ptr [ebp-0x34], edx
    movzx edx, byte ptr [esi+1]
    movzx edx, word ptr [edx*2 + {S['LUT']:#x}]
    imul edx, eax
    add dword ptr [ebp-0x38], edx
    movzx edx, byte ptr [esi+2]
    movzx edx, word ptr [edx*2 + {S['LUT']:#x}]
    imul edx, eax
    add dword ptr [ebp-0x3C], edx
    pop esi
    ret
invg:
    xor ecx, ecx
    mov edx, 255
invg_bs:
    cmp ecx, edx
    jae invg_done
    lea ebx, [ecx+edx]
    shr ebx, 1
    movzx edi, word ptr [ebx*2 + {S['LUT']:#x}]
    cmp edi, eax
    jae invg_hi
    lea ecx, [ebx+1]
    jmp invg_bs
invg_hi:
    mov edx, ebx
    jmp invg_bs
invg_done:
    test ecx, ecx
    je invg_ret
    movzx edi, word ptr [ecx*2 + {S['LUT']:#x}]
    sub edi, eax
    movzx ebx, word ptr [ecx*2 + {S['LUT']-2:#x}]
    mov edx, eax
    sub edx, ebx
    cmp edx, edi
    jae invg_ret
    dec ecx
invg_ret:
    ret
"""


# Rectangular generalization of coverage_code for W x H art (W%4 == 0).
# PORT of scaling_laws.coverage_filter_rect: identical pipeline, but the two
# axes carry separate totals (y-taps sum to H, x-taps sum to W; per-pixel
# weight total = W*H) and the snapshot row stride is W.  coverage_code stays
# UNTOUCHED so the locked chevron/staple instances cannot drift.
def coverage_code_rect(W: int, H: int, dwmax: int, dhmax: int,
                       scratch: int) -> str:
    assert W % 4 == 0, "snapshot copy loop moves whole dwords"
    WH = W * H
    return f"""
    push ebp
    mov ebp, esp
    sub esp, 0x70
    push ebx
    push esi
    push edi
    cmp dword ptr [ebp+0x18], {W}
    jne fallb
    cmp dword ptr [ebp+0x1C], {H}
    jne fallb
    mov eax, dword ptr [ebp+0x28]
    cmp eax, {W}
    jle fallb
    cmp eax, {dwmax}
    jg fallb
    mov edx, dword ptr [ebp+0x2C]
    cmp edx, {H}
    jle fallb
    cmp edx, {dhmax}
    jg fallb
    mov ebx, dword ptr [ebp+8]
    mov eax, dword ptr [ebx+0x54]
    test eax, eax
    je fallb
    mov dword ptr [ebp-4], eax
    mov ecx, dword ptr [ebx+0x4A8]
    test ecx, ecx
    jle fallb
    mov dword ptr [ebp-8], ecx
    mov eax, dword ptr [ebp+0x28]
    mov dword ptr [ebp-0xC], eax
    mov eax, dword ptr [ebp+0x2C]
    mov dword ptr [ebp-0x10], eax
    mov eax, dword ptr [ebp+0x14]
    imul eax, dword ptr [ebp-8]
    add eax, dword ptr [ebp+0x10]
    add eax, dword ptr [ebp-4]
    mov esi, eax
    mov edi, {scratch:#x}
    mov ebx, {H}
cploop:
    mov ecx, {W // 4}
cpword:
    mov eax, dword ptr [esi]
    mov dword ptr [edi], eax
    add esi, 4
    add edi, 4
    dec ecx
    jnz cpword
    add esi, dword ptr [ebp-8]
    sub esi, {W}
    dec ebx
    jnz cploop
    mov dword ptr [ebp-0x14], 0
yloop:
    mov eax, dword ptr [ebp-0x14]
    mov ecx, dword ptr [ebp-0x10]
    call tapsy
    mov dword ptr [ebp-0x1C], eax
    mov dword ptr [ebp-0x20], edx
    mov eax, {H}
    sub eax, edx
    mov dword ptr [ebp-0x24], eax
    mov eax, dword ptr [ebp+0x24]
    add eax, dword ptr [ebp-0x14]
    imul eax, dword ptr [ebp-8]
    add eax, dword ptr [ebp+0x20]
    add eax, dword ptr [ebp-4]
    mov dword ptr [ebp-0x50], eax
    mov dword ptr [ebp-0x18], 0
xloop:
    mov eax, dword ptr [ebp-0x18]
    mov ecx, dword ptr [ebp-0xC]
    call tapsx
    mov dword ptr [ebp-0x28], eax
    mov dword ptr [ebp-0x2C], edx
    mov eax, {W}
    sub eax, edx
    mov dword ptr [ebp-0x30], eax
    xor eax, eax
    mov dword ptr [ebp-0x34], eax
    mov dword ptr [ebp-0x38], eax
    mov dword ptr [ebp-0x3C], eax
    mov dword ptr [ebp-0x40], eax
    mov eax, dword ptr [ebp-0x20]
    imul eax, dword ptr [ebp-0x2C]
    imul edx, dword ptr [ebp-0x1C], {W}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch:#x}]
    call acc4
    cmp dword ptr [ebp-0x30], 0
    je no01
    mov eax, dword ptr [ebp-0x20]
    imul eax, dword ptr [ebp-0x30]
    imul edx, dword ptr [ebp-0x1C], {W}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch + 1:#x}]
    call acc4
no01:
    cmp dword ptr [ebp-0x24], 0
    je no1x
    mov eax, dword ptr [ebp-0x24]
    imul eax, dword ptr [ebp-0x2C]
    imul edx, dword ptr [ebp-0x1C], {W}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch + W:#x}]
    call acc4
    cmp dword ptr [ebp-0x30], 0
    je no1x
    mov eax, dword ptr [ebp-0x24]
    imul eax, dword ptr [ebp-0x30]
    imul edx, dword ptr [ebp-0x1C], {W}
    add edx, dword ptr [ebp-0x28]
    movzx edx, byte ptr [edx + {scratch + W + 1:#x}]
    call acc4
no1x:
    mov eax, dword ptr [ebp-0x40]
    add eax, eax
    cmp eax, {WH}
    jl colpix
    mov dword ptr [ebp-0x5C], 9
    jmp wrpix
colpix:
    mov eax, {WH}
    sub eax, dword ptr [ebp-0x40]
    mov dword ptr [ebp-0x54], eax
    shr eax, 1
    mov dword ptr [ebp-0x58], eax
    mov eax, dword ptr [ebp-0x34]
    add eax, dword ptr [ebp-0x58]
    xor edx, edx
    div dword ptr [ebp-0x54]
    call invg
    mov dword ptr [ebp-0x44], ecx
    mov eax, dword ptr [ebp-0x38]
    add eax, dword ptr [ebp-0x58]
    xor edx, edx
    div dword ptr [ebp-0x54]
    call invg
    mov dword ptr [ebp-0x48], ecx
    mov eax, dword ptr [ebp-0x3C]
    add eax, dword ptr [ebp-0x58]
    xor edx, edx
    div dword ptr [ebp-0x54]
    call invg
    mov dword ptr [ebp-0x4C], ecx
    mov esi, {S['PALETTE']:#x}
    xor ecx, ecx
    mov edi, 0x7FFFFFFF
    mov dword ptr [ebp-0x5C], 0
nloop:
    cmp ecx, 9
    je nnext
    movzx eax, byte ptr [esi]
    mov edx, eax
    add edx, dword ptr [ebp-0x44]
    shr edx, 1
    mov dword ptr [ebp-0x60], edx
    sub eax, dword ptr [ebp-0x44]
    imul eax, eax
    mov edx, dword ptr [ebp-0x60]
    add edx, 512
    imul eax, edx
    mov dword ptr [ebp-0x64], eax
    movzx eax, byte ptr [esi+1]
    sub eax, dword ptr [ebp-0x48]
    imul eax, eax
    shl eax, 10
    add dword ptr [ebp-0x64], eax
    movzx eax, byte ptr [esi+2]
    sub eax, dword ptr [ebp-0x4C]
    imul eax, eax
    mov edx, 767
    sub edx, dword ptr [ebp-0x60]
    imul eax, edx
    add eax, dword ptr [ebp-0x64]
    cmp eax, edi
    jge nnext
    mov edi, eax
    mov dword ptr [ebp-0x5C], ecx
nnext:
    add esi, 4
    inc ecx
    cmp ecx, 256
    jl nloop
wrpix:
    mov edx, dword ptr [ebp-0x50]
    add edx, dword ptr [ebp-0x18]
    mov eax, dword ptr [ebp-0x5C]
    mov byte ptr [edx], al
    inc dword ptr [ebp-0x18]
    mov eax, dword ptr [ebp-0x18]
    cmp eax, dword ptr [ebp-0xC]
    jl xloop
    inc dword ptr [ebp-0x14]
    mov eax, dword ptr [ebp-0x14]
    cmp eax, dword ptr [ebp-0x10]
    jl yloop
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    ret 0x2C
fallb:
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    jmp {S['KSB']:#x}
tapsy:
    imul eax, eax, {H}
    xor edx, edx
    div ecx
    neg edx
    add edx, ecx
    cmp edx, {H}
    jle tyret
    mov edx, {H}
tyret:
    ret
tapsx:
    imul eax, eax, {W}
    xor edx, edx
    div ecx
    neg edx
    add edx, ecx
    cmp edx, {W}
    jle txret
    mov edx, {W}
txret:
    ret
acc4:
    cmp edx, 9
    jne acc_col
    add dword ptr [ebp-0x40], eax
    ret
acc_col:
    push esi
    lea esi, [edx*4 + {S['PALETTE']:#x}]
    movzx edx, byte ptr [esi]
    movzx edx, word ptr [edx*2 + {S['LUT']:#x}]
    imul edx, eax
    add dword ptr [ebp-0x34], edx
    movzx edx, byte ptr [esi+1]
    movzx edx, word ptr [edx*2 + {S['LUT']:#x}]
    imul edx, eax
    add dword ptr [ebp-0x38], edx
    movzx edx, byte ptr [esi+2]
    movzx edx, word ptr [edx*2 + {S['LUT']:#x}]
    imul edx, eax
    add dword ptr [ebp-0x3C], edx
    pop esi
    ret
invg:
    xor ecx, ecx
    mov edx, 255
invg_bs:
    cmp ecx, edx
    jae invg_done
    lea ebx, [ecx+edx]
    shr ebx, 1
    movzx edi, word ptr [ebx*2 + {S['LUT']:#x}]
    cmp edi, eax
    jae invg_hi
    lea ecx, [ebx+1]
    jmp invg_bs
invg_hi:
    mov edx, ebx
    jmp invg_bs
invg_done:
    test ecx, ecx
    je invg_ret
    movzx edi, word ptr [ecx*2 + {S['LUT']:#x}]
    sub edi, eax
    movzx ebx, word ptr [ecx*2 + {S['LUT']-2:#x}]
    mov edx, eax
    sub edx, ebx
    cmp edx, edi
    jae invg_ret
    dec ecx
invg_ret:
    ret
"""


CHEV = coverage_code(20, 50, S["SCRATCH"])       # the LOCKED v8 chevron instance
STAPLE = coverage_code(48, 120, S["SCRATCH48"])  # v9 staple-button instance
ARROW = coverage_code_rect(12, 42, 32, 112, S["SCRATCH_ARROW"])  # v10 arrow instance


def lut_bytes() -> bytes:
    """The baked SRGB_LIN16 data (u16 LE), verbatim from the law module."""
    out = b"".join(v.to_bytes(2, "little") for v in SL.SRGB_LIN16)
    assert len(out) == 512
    return out

ks = Ks(KS_ARCH_X86, KS_MODE_32)

def asm(name, code, va, budget):
    enc, _ = ks.asm(code, va)
    b = bytes(enc)
    print(f"{name} @ {va:#x}: {len(b)} bytes (budget {budget:#x}={budget})")
    assert len(b) <= budget, f"{name} over budget!"
    print("  " + " ".join(f"{x:02X}" for x in b))
    return b

core = asm("restripe_core",           CORE, PCAVE2_VA + CORE_OFF, CORE_BUDGET)
band = asm("thunk_band_stretch_remap", BAND, PCAVE2_VA + BAND_OFF, BAND_BUDGET)
btn  = asm("thunk_btn_bandstripe",     BTN,  PCAVE2_VA + BTN_OFF,  BTN_BUDGET)
chev = asm("thunk_chev_coverage",      CHEV, PCAVE2_VA + CHEV_OFF, CHEV_BUDGET)
staple = asm("thunk_staple_coverage",  STAPLE, PCAVE2_VA + STAPLE_OFF,
             STAPLE_BUDGET)
arrow = asm("thunk_arrow_coverage",    ARROW, PCAVE2_VA + ARROW_OFF,
            ARROW_BUDGET)
assert len(staple) == len(chev), "template instances must be byte-length equal"
lut = lut_bytes()
print(f"\nSRGB_LIN16 LUT @ {PCAVE2_VA + LUT_OFF:#x}: {len(lut)} bytes")
print("  " + " ".join(f"{x:02X}" for x in lut))
print(f"\nscratch (BSS, no content entry) @ {PCAVE2_VA + SCRATCH_OFF:#x}: 400 bytes")
print(f"scratch48 (BSS, no content entry) @ {PCAVE2_VA + SCRATCH48_OFF:#x}: 2304 bytes")
print(f"scratch_arrow (BSS, no content entry) @ {PCAVE2_VA + SCRATCH_ARROW_OFF:#x}: 504 bytes")
print(f"tail after staple: {STAPLE_OFF + len(staple):#x}; after arrow: "
      f"{ARROW_OFF + len(arrow):#x}; cave end 0x10000")
