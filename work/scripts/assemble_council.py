#!/usr/bin/env python
"""Assembler for the PLANETARY COUNCIL arc BAKE (group council_scale, 2026-08-22).

Ports the user-verified prototype hook_council_proto.js v28 (4K + 1920 + 1600 +
1024 no-op, "Everything passes" 2026-08-22) into pcave2 thunks.  Laws:
scaling_laws.council_* (seed rects / button row / chips / text y / sd2),
popup_textfollow_applies, popup_art_x, popup_field_top,
popup_field_right_src_ornate; dither doctrine = parity-forced re-blit
(feedback-dither-no-resample-on-upscale) + the v17 dest-space pair LUT.

TALLY SCREEN (CouncilWin 0x6FEC80, all E8 call-target redirects):
  thunk_cw_enter      @0x4284CA (the ONE CouncilWin_exec caller, thiscall RET 8):
                      run the imm table, g_council_active=1 around the modal.
  thunk_cw_immfix     CALL helper: one-time VirtualProtect(0x426000, 0x2000) via
                      the kernel32 IAT (same bootstrap as thunk_ed_immfix, shared
                      strings), then the 41 painter/exec immediates = dp(A)-dp(B)
                      (identity at g=16 -> restores vanilla on a res downgrade).
  thunk_cw_seeds      @0x427784 (Font_init E8, esi=CWIN): the 63-dword seed table
                      = law council_seed_rects (pinned column width dp(98)).
  thunk_cw_texty      @0x425F83: name-line y = T+1 + dp(portrait h) + dp(4).
  thunk_cw_portrait   @0x425F3C / thunk_cw_logo @0x426105: sd2 num=g den=16
                      (logo recentred by (cw-dp(cw))/2), CALL sd2, then the
                      parity re-blit over the engine's (measured: floor) rect.
  thunk_parity_reblit CALL helper, sd2 signature (ecx=sprite; dest,key,x,y,num,
                      den; RET 0x18): centre-NN columns, pair-granular centre-NN
                      rows with dest-parity shading, key skipped, pcBits only.
  thunk_cw_backdrop37 @0x426B4E: rect.right -= dp(0x37)-0x37, tail devfill.  (SUPERSEDED 2026-10-25
                      W5B: the site -> t_cw_backdrop, assemble_council_mirror.py.)
  thunk_cw_chip       the 5 chip box_sprite sites: fill tile (borders-nulled
                      params, K/K+1 inset) -> hollow_flat frame -> tile_mask.
  lever F direct:     3 d528 sites -> thunk_box_thick_devfill, d5a0 @0x426B7B ->
                      thunk_box_thick_hollow_flat.
  thunk_btn_gate_pre  v2 (RELOCATED 0xC080 -> tail): HIT for the 6 CouncilWin
                      FlatButtons [CWIN+0xD94, +6*0xB4C), then v1 verbatim.
CAST-A-VOTE + FLAG:
  thunk_gv_arthead    the [popup+0x3168] head (sprite_draw_repoint site):
                      g>16 && council active && ornate && art && no body ->
                      thunk_sprite_draw with the engine's DEVICE seeds, y
                      compensated by -(dp(6)-6) for the thunk's NATIVE y-6
                      draw offset (v2, law council_castvote_art v2; x
                      untouched); else t_dp_artalign as before.
  thunk_gv_frameskip  @0x406238 (final d5a0): same gate -> RET 8 (the empty-body
                      frame hide, user-directed), else thunk_content_frame.
  thunk_flag_restripe @0x5E4C01 (the blit core's Buffer_draw_2 call — every
                      filename-backed art draw passes here): src 200x120 whose
                      rows 1/2 col 2 hold the flag pair (250/230 raw or 4/240
                      remapped) && num>den -> v17 row-parity pair LUT over the
                      dest rect (ceil dims, clipped).  Covers Cast-a-Vote AND the
                      PROTOCOL DIRECTOR modal (both council_sm.pcx).
TALK POPUPS:
  thunk_pf_textfollow v2   + popup_frame_rewrite_applies band test (fix A)
  thunk_popup_artalign v6  g_band_left -> g_title_left (post-shift stash; fix B)
  thunk_popup_fieldpads v6 keyed-T arm gated by popup_frame_rewrite_applies
                           (fix B-y) + ornate R arm ecx = g_title_right - 2*ps3
                           + Delta (fix C, law popup_field_right_src_ornate)
  thunk_sd_reblit_wrap     thunk_sprite_draw's internal call: portrait_drop ->
                           sd2, then the parity re-blit (fix D; faction-quote
                           buffer 0x940824 excluded — it keeps the A5 bilinear).

Run:  py assemble_council.py            -> prints the yaml fragments + checks
      py assemble_council.py --splice   -> writes work\\patches\\_fragment_council_*.yaml
Parity: tests\\test_council_asm_parity.py emulates these exact bytes.
"""
from __future__ import annotations

import os
import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x14000

# ---- engine / existing-cave anchors (all census-verified 2026-08-22) ------
G               = 0x00668740   # g_popup_scale_num
SD2             = 0x005E4B4A   # Sprite_draw_2 (thiscall; dest,key,x,y,num,den; RET 0x18)
STC             = 0x005DACB0   # the thiscall @0x425F83 (ecx=edi)
FONT_INIT       = 0x00618F40
BOX_SPRITE      = 0x005E2DD3
BUF_DRAW2       = 0x005D84C0   # thiscall src; dest,key,X,Y,num,den; RET 0x18
TILEMASK        = 0x005DA6C0   # Buffer_tile_mask thiscall, 8 args, RET 0x20
SPRITE_DRAW     = 0x006688B0   # thunk_sprite_draw
CONTENT_FRAME   = 0x00668BD0   # thunk_content_frame
DEVFILL         = 0x00A102A0   # thunk_box_thick_devfill
HOLLOWFLAT      = 0x00A0C140   # thunk_box_thick_hollow_flat
T_DP_ARTALIGN   = 0x00A1E6E8
PORTRAIT_DROP   = 0x00A12B00   # thunk_portrait_drop
BTN_GATE        = 0x00A169E0   # thunk_btn_gate (v8)
CW_EXEC         = 0x00427230
CWIN            = 0x006FEC80
GOV             = 0x009A6614
IAT_LOADLIB     = 0x00669120
IAT_GETPROC     = 0x00669124
STR_K32         = 0x00A1C6C0   # g_ed_str_k32 "KERNEL32.DLL"
STR_VP          = 0x00A1C6D0   # g_ed_str_vp  "VirtualProtect"
G_TITLE_LEFT    = 0x00A0CF00
G_TITLE_RIGHT   = 0x00A0CF04
G_BAND_LEFT     = 0x00A0E700
G_FIELD_ANCHOR  = 0x00A0E704
G_BAND_POPUP    = 0x00A0E708
G_BAND_BOTTOM   = 0x00A0E70C
G_FIELD_L       = 0x00A104BC
G_FIELD_R       = 0x00A104C0
G_FIELD_BOXW    = 0x00A104C4
G_D528_LEFT     = 0x00A0E000
BUF_WRITE_STRINGS = 0x005DB040
FACTION_QUOTE_BUF = 0x00940824
FACTION_POPUP   = 0x009403E0
VP_PAGE         = 0x00426000   # imm sites 0x4260AD..0x427A14 -> 2 pages
VP_LEN          = 0x2000
PAGE_RWX        = 0x40

# ---- new allocations (free tail 0x1293A..0x14000 per cave_map 2026-08-22) --
OFF_G_COUNCIL_ACTIVE = 0x12940
OFF_G_CW_VPDONE      = 0x12944
OFF_G_CW_VPOLD       = 0x12948
OFF_G_FLAG_RET       = 0x1294C
OFF_G_CW_SEEDTAB     = 0x12950   # 84B: OUTER_L[7] OUTER_T[7] INNER_L[7] dwords
OFF_G_CW_CHIPSCR     = 0x129B0   # 96B: scratchA(40) scratchB(40) scratchR(16) -> 0x12A10
OFF_G_TITLE_BOTTOM   = 0x12A10   # 4B: thunk_pf_title_stash v6's POST-arm rect.bottom (law popup_field_top)
OFF_G_FP_ORNART      = 0x12A14   # 4B: fieldpads scratch: 1 = this draw is an ornate popup WITH art
OFF_G_FLAG_LUT       = 0x12C00   # 512B; base must have BIT 8 CLEAR (0x200-aligned) so `xor ebx,0x100` toggles
                                 # bright(+0)/dark(+0x100) — the proto's page alloc had it; parity test pins it
OFF_G_CW_IMMTAB      = 0x12E00   # 41*16+4 = 660B -> 0x13094 (slot to OFF_CODE 0x130A0)
OFF_CODE             = 0x130A0

G_COUNCIL_ACTIVE = PCAVE2 + OFF_G_COUNCIL_ACTIVE
G_CW_VPDONE      = PCAVE2 + OFF_G_CW_VPDONE
G_CW_VPOLD       = PCAVE2 + OFF_G_CW_VPOLD
G_FLAG_RET       = PCAVE2 + OFF_G_FLAG_RET
G_CW_SEEDTAB     = PCAVE2 + OFF_G_CW_SEEDTAB
G_CW_CHIPSCR     = PCAVE2 + OFF_G_CW_CHIPSCR
G_FLAG_LUT       = PCAVE2 + OFF_G_FLAG_LUT
G_CW_IMMTAB      = PCAVE2 + OFF_G_CW_IMMTAB
G_TITLE_BOTTOM   = PCAVE2 + OFF_G_TITLE_BOTTOM
G_FP_ORNART      = PCAVE2 + OFF_G_FP_ORNART
SCR_A, SCR_B, SCR_R = G_CW_CHIPSCR, G_CW_CHIPSCR + 40, G_CW_CHIPSCR + 80

# existing slots that are rewritten IN PLACE
OFF_ARTALIGN  = 0x37A0   # slot to 0x3800
OFF_FIELDPADS = 0x4550   # slot to 0x4640
OFF_REBLIT_BODY = 0x27640   # the shared re-blit body (assemble_artreblit.asm_art_reblit_body, v2 2026-10-04)
OFF_TEXTFOLLOW = 0x2090  # slot to 0x2100
OFF_GV_ARTX = 0xFF80     # t_gv_artx (2026-10-14): cave_map free 0xFF72..0x10000 (thunk_pp_measure .. thunk_fe_pair_remap)
SLOT_END = {OFF_ARTALIGN: 0x3800, OFF_FIELDPADS: 0x4640, OFF_TEXTFOLLOW: 0x2100, OFF_GV_ARTX: 0x10000}
T_GV_ARTX = PCAVE2 + OFF_GV_ARTX
# 2026-10-25 wave-5 W5B: thunk_cw_seeds tails t_cw_mirror (assemble_council_mirror.py, pcave2 0x3D200; the right half
# of both column sets mirrored about the slide rails, law scaling_laws.council_column_rects), which tails Font_init
T_CW_MIRROR = PCAVE2 + 0x3D200   # v2 (audit-w5B): relocated from 0x3D040

# ---- the tally-screen data (laws council_seed_rects / the proto's IMMS()) ---
OUTER_L = [30, 130, 230, 330, 452, 552, 652]
OUTER_T = [53, 45, 37, 29, 37, 45, 53]
INNER_L = [32, 135, 238, 341, 444, 547, 650]

# (site, A, B, kind): value = dp(A) - dp(B); kind bit0 = dword (else byte), bit1 = negate
IMMTAB = [
    # exec: console-rect insets + button-row derivation
    (0x42768B + 2, 4, 0, 0), (0x427690 + 1, 4, 0, 3), (0x42769D + 2, 4, 0, 0),
    (0x4276B9 + 2, 3, 0, 0), (0x4276BC + 2, 3, 0, 0),
    (0x4276C2 + 2, 0x17, 3, 2), (0x4276C8 + 2, 3, 0, 0), (0x4276CB + 2, 3, 0, 2),
    (0x4276EF + 2, 3, 0, 0), (0x427726 + 2, 3, 0, 0), (0x427751 + 2, 3, 0, 0),
    # 2026-10-25 W3A F43: the thirds' `lea edx, [edx+ecx-3]` disp8 (r0 = L + third - 3) -- missing until then, so
    # the cells stayed third - 3 wide against sc(3) seams and the row overran the VOTE's right edge by 3*(sc3-3)
    (0x427704 + 3, 3, 0, 2),
    # window init
    (0x4279C4 + 3, 0x18B, 0, 1), (0x4279CB + 2, 0x18B, 0, 1),
    (0x4279DB + 1, 0x30C, 0, 3), (0x427A14 + 1, 0x32C, 0, 1),
    # fonts (push imm8 sizes) + b04 pad 5
    (0x427760 + 1, 20, 0, 0), (0x427791 + 1, 14, 0, 0), (0x4277A7 + 1, 14, 0, 0),
    (0x4277BC + 1, 12, 0, 0), (0x4277DC + 1, 12, 0, 0), (0x4277F2 + 1, 14, 0, 0),
    (0x4277CA + 6, 5, 0, 1),
    # column painter: logo gap 10, chip 3/3/3/-band, votes lift band
    (0x4260AD + 3, 10, 0, 0),
    (0x426116 + 2, 3, 0, 0), (0x42611F + 2, 3, 0, 0), (0x42612F + 2, 3, 0, 0),
    (0x426132 + 2, 0x17, 3, 2), (0x42637E + 1, 0x17, 3, 1),
    # proposal painter: header band 0x14, +2, body 3, tally 2/2
    (0x4264C2 + 2, 0x14, 0, 0), (0x42659A + 2, 2, 0, 0),
    (0x4265B6 + 1, 3, 0, 1), (0x426743 + 2, 2, 0, 0), (0x426746 + 2, 2, 0, 0),
    # repaint: console-box 4s, backdrop L 0x17 + inner 4, banner 3
    (0x426AEE + 2, 4, 0, 0), (0x426AFC + 2, 4, 0, 0), (0x426AFF + 2, 4, 0, 0),
    (0x426B02 + 2, 4, 0, 0), (0x426B3A + 3, 0x17, 0, 1), (0x426B5C + 1, 4, 0, 1),
    (0x426BDD + 1, 3, 0, 1),
]
assert len(IMMTAB) == 41

# the v17 dest-space pair LUT (council_sm.pcx census +10 canvas remap):
# field 0x04<->0xF0, logo 0xFF<->0x2B, laurel 0x4A<->0x2E
LUT_PAIRS = [(0x04, 0xF0), (0xFF, 0x2B), (0x4A, 0x2E)]


def lut_bytes() -> bytes:
    tb, td = list(range(256)), list(range(256))
    for bright, dark in LUT_PAIRS:
        tb[dark] = bright       # even rows -> bright
        td[bright] = dark       # odd rows  -> dark
    return bytes(tb) + bytes(td)


def seedtab_bytes() -> bytes:
    return b"".join(v.to_bytes(4, "little") for v in OUTER_L + OUTER_T + INNER_L)


def immtab_bytes() -> bytes:
    out = bytearray()
    for site, a, b, kind in IMMTAB:
        out += struct.pack("<IIII", site, a, b, kind)
    out += b"\x00\x00\x00\x00"
    assert OFF_G_CW_IMMTAB + len(out) <= OFF_CODE, "g_cw_immtab overruns thunk_cw_enter"
    return bytes(out)


# ---- asm -----------------------------------------------------------------
def SC(reg: str) -> str:
    """reg = floor(reg * g / 16)"""
    return f"imul {reg}, dword ptr [{G:#x}]\n    sar {reg}, 4\n"


def BAND_ORNATE(reg: str, hit: str, miss: str) -> str:
    """raw [+0x30ac] in [20000,30000) or [60000,70000) -> hit else miss (reg clobbered)."""
    return f"""
    sub     {reg}, 20000
    cmp     {reg}, 10000
    jb      {hit}
    sub     {reg}, 40000
    cmp     {reg}, 10000
    jb      {hit}
    jmp     {miss}
"""


def BAND_FLATSLIDE(reg: str, hit: str, miss: str) -> str:
    """popup_frame_rewrite_applies: raw in [0,10000) or [50000,60000)."""
    return f"""
    cmp     {reg}, 10000
    jb      {hit}
    sub     {reg}, 50000
    cmp     {reg}, 10000
    jb      {hit}
    jmp     {miss}
"""


def GV_GATE(winreg: str, miss: str) -> str:
    """Cast-a-Vote content gate on a popup ptr in winreg: council active &&
    ornate && art && no body text.  Clobbers eax.  Falls through on HIT."""
    return f"""
    cmp     dword ptr [{G}], 0x10
    jle     {miss}
    cmp     dword ptr [{G_COUNCIL_ACTIVE:#x}], 0
    je      {miss}
    cmp     dword ptr [{winreg}+0x2144], 0
    je      {miss}
    cmp     dword ptr [{winreg}+0x30d4], 0
    jne     {miss}
    mov     eax, dword ptr [{winreg}+0x30ac]
    {BAND_ORNATE("eax", "gvhit", miss)}
gvhit:
"""


def asm_cw_enter() -> str:
    return f"""
    push    ecx
    call    thunk_cw_immfix
    pop     ecx
    mov     dword ptr [{G_COUNCIL_ACTIVE:#x}], 1
    push    dword ptr [esp+8]
    push    dword ptr [esp+8]
    call    {CW_EXEC:#x}
    mov     dword ptr [{G_COUNCIL_ACTIVE:#x}], 0
    ret     8
"""


def asm_cw_immfix() -> str:
    return f"""
    push    esi
    cmp     dword ptr [{G_CW_VPDONE:#x}], 0
    jne     imms
    push    {STR_K32:#x}
    call    dword ptr [{IAT_LOADLIB:#x}]
    test    eax, eax
    je      bail
    push    {STR_VP:#x}
    push    eax
    call    dword ptr [{IAT_GETPROC:#x}]
    test    eax, eax
    je      bail
    push    {G_CW_VPOLD:#x}
    push    {PAGE_RWX:#x}
    push    {VP_LEN:#x}
    push    {VP_PAGE:#x}
    call    eax
    test    eax, eax
    je      bail
    mov     dword ptr [{G_CW_VPDONE:#x}], 1
imms:
    cmp     dword ptr [{G_CW_VPDONE:#x}], 0
    je      bail
    mov     esi, {G_CW_IMMTAB:#x}
nexte:
    mov     eax, dword ptr [esi]
    test    eax, eax
    je      bail
    mov     ecx, dword ptr [esi+4]
    {SC("ecx")}
    mov     edx, dword ptr [esi+8]
    {SC("edx")}
    sub     ecx, edx
    mov     edx, dword ptr [esi+12]
    test    edx, 2
    je      nn
    neg     ecx
nn:
    test    edx, 1
    jne     wr4
    mov     byte ptr [eax], cl
    jmp     adv
wr4:
    mov     dword ptr [eax], ecx
adv:
    add     esi, 16
    jmp     nexte
bail:
    pop     esi
    ret
"""


def asm_cw_seeds() -> str:
    # esi = CWIN.  Writes the banner/params/outer/inner seed table (law
    # council_seed_rects): outer[c] = (dp(OL), dp(OT), dp(OL)+dp(w), dp(OT)+dp(h))
    # with w/h = 98/282 (120/323 for the governor slot c==3); inner[c] =
    # (dp(IL), dp(29), dp(IL)+dp(98), dp(29)+dp(282)).  Then tail-jmp Font_init.
    def wr(disp, native):
        return f"    mov eax, {native}\n    {SC('eax')}    mov dword ptr [esi+{disp:#x}], eax\n"
    singles = (wr(0xBA4, 245) + wr(0xBA8, 355) + wr(0xBAC, 538) + wr(0xBB0, 378) +
               wr(0xBC4, 30) + wr(0xBCC, 750) + wr(0xBD0, 27))
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    push    eax
    push    ebx
    push    ecx
    push    edx
    push    edi
{singles}
    xor     edi, edi
col:
    mov     ebx, edi
    shl     ebx, 5
    add     ebx, esi                     ; ebx = CWIN + c*0x20
    mov     eax, dword ptr [{G_CW_SEEDTAB:#x}+edi*4]
    {SC("eax")}
    mov     dword ptr [ebx+0xBF4], eax   ; outer L
    mov     ecx, eax
    mov     eax, 98
    cmp     edi, 3
    jne     ow
    mov     eax, 120
ow:
    {SC("eax")}
    add     eax, ecx
    mov     dword ptr [ebx+0xBFC], eax   ; outer R = L + dp(w)
    mov     eax, dword ptr [{G_CW_SEEDTAB + 28:#x}+edi*4]
    {SC("eax")}
    mov     dword ptr [ebx+0xBF8], eax   ; outer T
    mov     ecx, eax
    mov     eax, 282
    cmp     edi, 3
    jne     oh
    mov     eax, 323
oh:
    {SC("eax")}
    add     eax, ecx
    mov     dword ptr [ebx+0xC00], eax   ; outer B = T + dp(h)
    mov     eax, dword ptr [{G_CW_SEEDTAB + 56:#x}+edi*4]
    {SC("eax")}
    mov     dword ptr [ebx+0xC04], eax   ; inner L
    mov     ecx, eax
    mov     eax, 98
    {SC("eax")}
    add     eax, ecx
    mov     dword ptr [ebx+0xC0C], eax   ; inner R
    mov     eax, 29
    {SC("eax")}
    mov     dword ptr [ebx+0xC08], eax   ; inner T
    mov     ecx, eax
    mov     eax, 282
    {SC("eax")}
    add     eax, ecx
    mov     dword ptr [ebx+0xC10], eax   ; inner B
    inc     edi
    cmp     edi, 7
    jl      col
    pop     edi
    pop     edx
    pop     ecx
    pop     ebx
    pop     eax
native:
    push    {T_CW_MIRROR:#x}
    ret
"""


def asm_cw_texty() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    mov     eax, dword ptr [{GOV:#x}]
    xor     ecx, ecx
    cmp     eax, ebx
    sete    cl
    lea     ecx, [ecx+ebx*2]
    mov     eax, dword ptr [esi+ecx*4+0xd54]
    mov     eax, dword ptr [eax+0x1c]
    {SC("eax")}
    add     eax, dword ptr [ebp-0x14]
    mov     ecx, 4
    {SC("ecx")}
    add     eax, ecx
    mov     dword ptr [ebp+8], eax
    mov     ecx, edi
native:
    jmp     {STC:#x}
"""


def _sd2_body() -> str:
    """num=g den=16, CALL sd2 with an arg copy, then the parity re-blit with a
    second copy; eax (sd2's return) preserved; RET 0x18."""
    push6 = lambda off: "".join(f"    push dword ptr [esp+{off:#x}]\n" for _ in range(6))
    return f"""
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [esp+0x14], eax
    mov     dword ptr [esp+0x18], 16
    push    ecx
{push6(0x1C)}
    call    {SD2:#x}
    pop     ecx
    push    eax
    push    ecx
{push6(0x20)}
    call    thunk_parity_reblit
    pop     ecx
    pop     eax
    ret     0x18
"""


def asm_cw_portrait() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
{_sd2_body()}
native:
    jmp     {SD2:#x}
"""


def asm_cw_logo() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    mov     eax, dword ptr [ecx+0x18]
    mov     edx, eax
    {SC("edx")}
    sub     eax, edx
    sar     eax, 1
    add     dword ptr [esp+0xC], eax
{_sd2_body()}
native:
    jmp     {SD2:#x}
"""


def asm_parity_reblit() -> str:
    # frame: [ebp+8]=dest [ebp+0xC]=key [ebp+0x10]=x [ebp+0x14]=y [ebp+0x18]=num [ebp+0x1C]=den
    # locals: -4 sData -8 sPitch -0xC sw -0x10 sh -0x14 x0 -0x18 y0 -0x1C dw -0x20 dh
    #         -0x24 dData -0x28 dPitch -0x2C dW -0x30 dH -0x34 pMax -0x38 jj -0x3C iw
    #         -0x40 num2 -0x44 num4 -0x48 key
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x50
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [ebp+0x18]
    cmp     eax, dword ptr [ebp+0x1C]
    jle     done
    test    ecx, ecx
    je      done
    mov     esi, ecx
    mov     eax, dword ptr [esi+4]
    test    eax, eax
    je      done
    mov     dword ptr [ebp-4], eax
    mov     eax, dword ptr [esi+0xC]
    mov     dword ptr [ebp-8], eax
    mov     eax, dword ptr [esi+0x10]
    mov     dword ptr [ebp-0xC], eax
    mov     edx, dword ptr [esi+0x14]
    test    edx, edx
    jns     h_ok
    neg     edx
h_ok:
    mov     dword ptr [ebp-0x10], edx
    test    eax, eax
    jle     done
    cmp     eax, 400
    jg      done
    test    edx, edx
    jle     done
    cmp     edx, 400
    jg      done
    cmp     dword ptr [ebp-8], eax
    jl      done
    mov     edi, dword ptr [ebp+8]
    test    edi, edi
    je      done
    mov     eax, dword ptr [edi+0x54]
    test    eax, eax
    je      done
    mov     dword ptr [ebp-0x24], eax
    mov     eax, dword ptr [edi+0x4A8]
    test    eax, eax
    jle     done
    mov     dword ptr [ebp-0x28], eax
    mov     eax, dword ptr [edi+0x80]
    mov     dword ptr [ebp-0x2C], eax
    mov     eax, dword ptr [edi+0x84]
    test    eax, eax
    jns     d_ok
    neg     eax
d_ok:
    mov     dword ptr [ebp-0x30], eax
    mov     eax, dword ptr [ebp+0xC]
    and     eax, 0xFF
    mov     dword ptr [ebp-0x48], eax
    mov     eax, dword ptr [esi+0x20]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    add     eax, dword ptr [ebp+0x10]
    mov     dword ptr [ebp-0x14], eax
    mov     eax, dword ptr [esi+0x24]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [ebp-0x18], eax
    mov     eax, dword ptr [ebp-0xC]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    mov     dword ptr [ebp-0x1C], eax
    mov     eax, dword ptr [ebp-0x10]
    imul    eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [ebp-0x14]
    test    eax, eax
    js      done
    mov     ecx, dword ptr [ebp-0x2C]
    sub     ecx, eax
    mov     eax, dword ptr [ebp-0x1C]
    cmp     eax, ecx
    jle     iw_ok
    mov     eax, ecx
iw_ok:
    test    eax, eax
    jle     done
    mov     dword ptr [ebp-0x3C], eax
    mov     eax, dword ptr [ebp-0x18]
    test    eax, eax
    js      done
    mov     eax, dword ptr [ebp-0x10]
    dec     eax
    sar     eax, 1
    mov     dword ptr [ebp-0x34], eax
    mov     eax, dword ptr [ebp+0x18]
    add     eax, eax
    mov     dword ptr [ebp-0x40], eax
    add     eax, eax
    mov     dword ptr [ebp-0x44], eax
    mov     dword ptr [ebp-0x38], 0
rowloop:
    mov     eax, dword ptr [ebp-0x38]
    cmp     eax, dword ptr [ebp-0x20]
    jge     done
    mov     edx, eax
    add     edx, dword ptr [ebp-0x18]
    cmp     edx, dword ptr [ebp-0x30]
    jge     done
    lea     eax, [eax*2+1]
    imul    eax, dword ptr [ebp+0x1C]
    xor     edx, edx
    div     dword ptr [ebp-0x44]
    cmp     eax, dword ptr [ebp-0x34]
    jle     p_ok
    mov     eax, dword ptr [ebp-0x34]
p_ok:
    add     eax, eax
    mov     ecx, dword ptr [ebp-0x38]
    and     ecx, 1
    add     eax, ecx
    cmp     eax, dword ptr [ebp-0x10]
    jl      r_ok
    mov     eax, dword ptr [ebp-0x10]
    dec     eax
r_ok:
    imul    eax, dword ptr [ebp-8]
    add     eax, dword ptr [ebp-4]
    mov     esi, eax
    mov     eax, dword ptr [ebp-0x38]
    add     eax, dword ptr [ebp-0x18]
    imul    eax, dword ptr [ebp-0x28]
    add     eax, dword ptr [ebp-0x24]
    add     eax, dword ptr [ebp-0x14]
    mov     edi, eax
    xor     ebx, ebx
colloop:
    cmp     ebx, dword ptr [ebp-0x3C]
    jge     colend
    lea     eax, [ebx*2+1]
    imul    eax, dword ptr [ebp+0x1C]
    xor     edx, edx
    div     dword ptr [ebp-0x40]
    cmp     eax, dword ptr [ebp-0xC]
    jl      sx_ok
    mov     eax, dword ptr [ebp-0xC]
    dec     eax
sx_ok:
    movzx   eax, byte ptr [esi+eax]
    cmp     eax, dword ptr [ebp-0x48]
    je      skip
    mov     byte ptr [edi+ebx], al
skip:
    inc     ebx
    jmp     colloop
colend:
    inc     dword ptr [ebp-0x38]
    jmp     rowloop
done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x18
"""


def asm_parity_reblit_stub() -> str:
    """v2 (2026-10-04): thunk_parity_reblit is a stub into the shared re-blit body (scaling_laws.art_reblit: 2-row
    scanlines, edge-pinned frame) -- the same 6 entry bytes (uimod.dll detours them), padded (int3, then ret 0x18) to v1's
    length so every later council thunk keeps its offset.  v1 (asm_parity_reblit) is the body's clone source."""
    stub = """
    push    ebp
    mov     ebp, esp
    sub     esp, 0x50
    jmp     {body:#x}
""".format(body=PCAVE2 + OFF_REBLIT_BODY)
    pad = len(assemble(asm_parity_reblit(), PCAVE2 + OFF_CODE)) - len(assemble(stub, PCAVE2 + OFF_CODE))
    assert pad >= 3
    # int3 pad, closed by an (unreachable) ret 0x18 so the slot still ends in a control transfer
    return stub + "    int3\n" * (pad - 3) + "    ret     0x18\n"


def asm_cw_backdrop37() -> str:
    return f"""
    push    eax
    push    edx
    mov     eax, 0x37
    {SC("eax")}
    sub     eax, 0x37
    mov     edx, dword ptr [esp+0xC]
    sub     dword ptr [edx+8], eax
    pop     edx
    pop     eax
    push    {DEVFILL:#x}
    ret
"""


def asm_cw_chip() -> str:
    # drop-in for Buffer_box_sprite: ecx=dest, [esp+4]=rect, [esp+8]=params, RET 8
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      scaled
    jmp     {BOX_SPRITE:#x}
scaled:
    push    ebp
    push    ebx
    push    esi
    push    edi
    mov     ebp, ecx
    mov     esi, dword ptr [esp+0x18]
    mov     edi, {SCR_A:#x}
    mov     ecx, 10
    .byte 0xF3, 0xA5                     ; rep movsd (keystone lacks the mnemonic)
    mov     esi, dword ptr [esp+0x18]
    mov     edi, {SCR_B:#x}
    mov     ecx, 10
    .byte 0xF3, 0xA5                     ; rep movsd (keystone lacks the mnemonic)
    mov     edi, {SCR_A:#x}
    xor     eax, eax
    mov     ecx, 8
    .byte 0xF3, 0xAB                     ; rep stosd
    mov     dword ptr [{SCR_B + 0x20:#x}], 0
    mov     eax, dword ptr [{G:#x}]
    add     eax, 15
    shr     eax, 4
    mov     edx, dword ptr [esp+0x14]
    mov     ecx, dword ptr [edx]
    add     ecx, eax
    mov     dword ptr [{SCR_R:#x}], ecx
    mov     ecx, dword ptr [edx+4]
    add     ecx, eax
    mov     dword ptr [{SCR_R + 4:#x}], ecx
    inc     eax
    mov     ecx, dword ptr [edx+8]
    sub     ecx, eax
    mov     dword ptr [{SCR_R + 8:#x}], ecx
    mov     ecx, dword ptr [edx+0xC]
    sub     ecx, eax
    mov     dword ptr [{SCR_R + 12:#x}], ecx
    push    {SCR_A:#x}
    push    {SCR_R:#x}
    mov     ecx, ebp
    call    {BOX_SPRITE:#x}
    push    {SCR_B:#x}
    push    dword ptr [esp+0x18]
    mov     ecx, ebp
    call    {HOLLOWFLAT:#x}
    mov     edx, dword ptr [esp+0x18]
    mov     eax, dword ptr [edx+0x20]
    test    eax, eax
    je      fin
    mov     ecx, dword ptr [edx+0x24]
    push    ecx
    mov     edx, dword ptr [esp+0x18]
    mov     ecx, dword ptr [edx+0xC]
    sub     ecx, dword ptr [edx+4]
    push    ecx
    mov     ecx, dword ptr [edx+8]
    sub     ecx, dword ptr [edx]
    push    ecx
    push    dword ptr [edx+4]
    push    dword ptr [edx]
    push    dword ptr [edx+4]
    push    dword ptr [edx]
    push    eax
    mov     ecx, ebp
    call    {TILEMASK:#x}
fin:
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret     8
"""


def asm_btn_gate_pre() -> str:
    lo, hi = CWIN + 0xD94, CWIN + 0xD94 + 6 * 0xB4C
    return f"""
    cmp     esi, {lo:#x}
    jb      v1
    cmp     esi, {hi:#x}
    jae     v1
    mov     eax, 1
    ret
v1:
    cmp     esi, 0x7fe80c
    je      miss
    cmp     esi, 0x7ff358
    jne     pass
miss:
    xor     eax, eax
    ret
pass:
    push    {BTN_GATE:#x}
    ret
"""


def asm_gv_arthead() -> str:
    # v2 (2026-08-23): armed branch compensates thunk_sprite_draw's NATIVE
    # y-6 draw offset hitting the DEVICE seed — y' = y - (dp(6)-6), law
    # council_castvote_art v2.
    # v3 (2026-10-14): + the x half, x' = x - ((5g>>4)-5) via t_gv_artx (the
    # flag sat 7 / 2 dev px right of vanilla at g 40 / 25, measured frame- and
    # row-relative on user shots 232732 / 233126 vs BadCastVote.png).
    return f"""
    mov     eax, dword ptr [esp+8]
    test    eax, eax
    je      pass
    {GV_GATE("eax", "pass")}
    mov     eax, dword ptr [{G}]
    imul    eax, eax, 6
    shr     eax, 4
    sub     eax, 6
    sub     dword ptr [esp+0x14], eax
    call    {T_GV_ARTX:#x}
    push    {SPRITE_DRAW:#x}
    ret
pass:
    push    {T_DP_ARTALIGN:#x}
    ret
"""


def asm_gv_artx() -> str:
    """t_gv_artx (v3): CALLed from thunk_gv_arthead's armed branch, after the y compensation.  thunk_sprite_draw
    subtracts vanilla's NATIVE x offset 5 from the DEVICE x seed (its [ebp+0x14] = the head's [esp+0x10] = [esp+0x14]
    here, past this call's return address): x' = x - ((5g>>4)-5), law council_castvote_art v3.  The head's armed
    branch only runs at g > 16 (GV_GATE).  Clobbers eax only (dead: the head then does push SPRITE_DRAW; ret)."""
    return f"""
    mov     eax, dword ptr [{G}]
    lea     eax, [eax+eax*4]
    shr     eax, 4
    sub     eax, 5
    sub     dword ptr [esp+0x14], eax
    ret
"""


def asm_gv_frameskip() -> str:
    return f"""
    {GV_GATE("esi", "pass")}
    ret     8
pass:
    push    {CONTENT_FRAME:#x}
    ret
"""


def asm_flag_restripe() -> str:
    # E8 @0x5E4C01 inside the blit core: ecx = src Buffer (canvas 0x9b6080);
    # [esp+4]=dest [esp+8]=key [esp+0xC]=X [esp+0x10]=Y [esp+0x14]=num [esp+0x18]=den
    push6 = "".join("    push dword ptr [esp+0x28]\n" for _ in range(6))
    return f"""
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     esi, ecx
{push6}
    mov     ecx, esi
    call    {BUF_DRAW2:#x}
    mov     dword ptr [{G_FLAG_RET:#x}], eax
    mov     eax, dword ptr [esp+0x24]
    cmp     eax, dword ptr [esp+0x28]
    jle     out
    cmp     dword ptr [esi+0x80], 200
    jne     out
    mov     eax, dword ptr [esi+0x84]
    test    eax, eax
    jns     h1
    neg     eax
h1:
    cmp     eax, 120
    jne     out
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    je      out
    mov     ecx, dword ptr [esi+0x4A8]
    cmp     ecx, 200
    jl      out
    movzx   edx, byte ptr [eax+ecx+2]
    movzx   eax, byte ptr [eax+ecx*2+2]
    cmp     dl, 250
    jne     p2
    cmp     al, 230
    je      ok
p2:
    cmp     edx, 4
    jne     out
    cmp     al, 240
    jne     out
ok:
    mov     edi, dword ptr [esp+0x14]
    test    edi, edi
    je      out
    mov     ebp, dword ptr [edi+0x4A8]
    test    ebp, ebp
    jle     out
    mov     eax, dword ptr [edi+0x54]
    test    eax, eax
    je      out
    mov     ecx, dword ptr [esp+0x1C]
    test    ecx, ecx
    js      out
    mov     edx, dword ptr [esp+0x20]
    test    edx, edx
    js      out
    imul    edx, ebp
    add     eax, edx
    add     eax, ecx
    mov     esi, eax                     ; dest row0 ptr
    imul    eax, dword ptr [esp+0x24], 200
    add     eax, dword ptr [esp+0x28]
    dec     eax
    cdq
    idiv    dword ptr [esp+0x28]         ; dw = ceil(200*num/den)
    mov     edx, dword ptr [edi+0x80]
    sub     edx, ecx                     ; dW - X
    cmp     eax, edx
    jle     w_ok
    mov     eax, edx
w_ok:
    mov     ecx, eax                     ; ecx = dw (clipped)
    imul    eax, dword ptr [esp+0x24], 120
    add     eax, dword ptr [esp+0x28]
    dec     eax
    cdq
    idiv    dword ptr [esp+0x28]         ; dh = ceil(120*num/den)
    mov     edx, dword ptr [edi+0x84]
    test    edx, edx
    jns     h2
    neg     edx
h2:
    sub     edx, dword ptr [esp+0x20]    ; dH - Y
    cmp     eax, edx
    jle     h_ok2
    mov     eax, edx
h_ok2:
    mov     edx, eax                     ; edx = dh (clipped)
    mov     edi, ecx                     ; edi = dw
    test    edi, edi
    jle     out
    mov     ecx, dword ptr [0x66879c]
    shr     ecx, 1                       ; T = stripe_rows(g) (the period cell / 2)
rowloop:
    test    edx, edx
    jle     out
    mov     eax, dword ptr [esp+0x20]    ; the DEST row (Y + r): law flag_restripe_bright = stripe_top(Y + r)
    push    edx
    xor     edx, edx
    div     ecx
    pop     edx
    and     eax, 1
    shl     eax, 8
    lea     ebx, [eax+{G_FLAG_LUT:#x}]   ; bright half where ((Y + r) / T) is even, dark half (+0x100) otherwise
    push    esi
    push    edi
colloop:
    movzx   eax, byte ptr [esi]
    mov     al, byte ptr [ebx+eax]
    mov     byte ptr [esi], al
    inc     esi
    dec     edi
    jnz     colloop
    pop     edi
    pop     esi
    add     esi, ebp
    inc     dword ptr [esp+0x20]         ; our own (callee-cleaned) Y slot walks down the rows
    dec     edx
    jmp     rowloop
out:
    mov     eax, dword ptr [{G_FLAG_RET:#x}]
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    ret     0x18
"""


def asm_sd_reblit_wrap() -> str:
    push6a = "".join("    push dword ptr [esp+0x1C]\n" for _ in range(6))
    push6b = "".join("    push dword ptr [esp+0x20]\n" for _ in range(6))
    return f"""
    push    esi
    mov     esi, ecx
{push6a}
    mov     ecx, esi
    call    {PORTRAIT_DROP:#x}
    push    eax
    cmp     dword ptr [esp+0xC], {FACTION_QUOTE_BUF:#x}
    je      skip
{push6b}
    mov     ecx, esi
    call    thunk_parity_reblit
skip:
    pop     eax
    pop     esi
    ret     0x18
"""


# ---- in-place rewrites of existing thunks ----------------------------------
def asm_textfollow_v2() -> str:
    # v2 (2026-08-22): + the popup_frame_rewrite_applies band test (law popup_textfollow_applies).
    # (The 2026-08-23b v3 ornate text-Y arm was REVERTED the same day: the engine Y = [30e8] is
    # proportionate; the band was the thing out of place — title_stash v7.)
    return f"""
    cmp     esi, {FACTION_POPUP:#x}
    je      tail
    mov     eax, dword ptr [esi+0xa14]
    test    eax, eax
    jne     tail
    mov     eax, dword ptr [esi+0x2144]
    test    eax, eax
    jne     tail
    mov     eax, dword ptr [esi+0x30ac]
    {BAND_FLATSLIDE("eax", "ok", "tail")}
ok:
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jle     tail
    mov     edx, dword ptr [{G:#x}]
    lea     edx, [edx+edx*2]
    sar     edx, 4
    mov     eax, dword ptr [{G_D528_LEFT:#x}]
    add     eax, edx
    mov     dword ptr [esp+8], eax
tail:
    push    {BUF_WRITE_STRINGS:#x}
    ret
"""


ARTALIGN_V5_HEX = ("A1 {abs32:g_popup_scale_num} 83 F8 10 7E 46 8B 0D {abs32:g_band_popup} 3B 4C 24 08 75 3A 33 C9 89 0D "
                   "{abs32:g_band_popup} 8B 0D {abs32:g_band_left} 8B D0 C1 FA 04 8D 4C 11 05 89 4C 24 10 8D 14 40 C1 FA 04 "
                   "8B 0D {abs32:g_field_anchor} 2B CA 8B D0 83 EA 10 C1 FA 1F 2B CA 83 C1 06 89 4C 24 14 68 {abs32:thunk_sprite_draw} C3")


def artalign_v6_bytes() -> bytes:
    """v5's EXACT bytes (user-verified) with the one dword swapped:
    g_band_left (pre-shift band stash) -> g_title_left (thunk_pf_title_stash's
    POST-ornate-shift stash) = law popup_art_x for both families."""
    import pathlib
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = ap.build_symbol_table(symbols, caves)
    b = bytearray(ap.ByteTemplate(ARTALIGN_V5_HEX).resolve(PCAVE2 + OFF_ARTALIGN, symtab))
    needle = G_BAND_LEFT.to_bytes(4, "little")
    assert b.count(needle) == 1
    i = b.find(needle)
    b[i:i + 4] = G_TITLE_LEFT.to_bytes(4, "little")
    return bytes(b)


def asm_artalign_v6() -> str:
    # (reference listing only — the shipped bytes come from artalign_v6_bytes())
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jle     tail
    mov     ecx, dword ptr [{G_BAND_POPUP:#x}]
    cmp     ecx, dword ptr [esp+8]
    jne     tail
    xor     ecx, ecx
    mov     dword ptr [{G_BAND_POPUP:#x}], ecx
    mov     ecx, dword ptr [{G_TITLE_LEFT:#x}]
    mov     edx, eax
    sar     edx, 4
    lea     ecx, [ecx+edx+5]
    mov     dword ptr [esp+0x10], ecx
    lea     edx, [eax+eax*2]
    sar     edx, 4
    mov     ecx, dword ptr [{G_FIELD_ANCHOR:#x}]
    sub     ecx, edx
    mov     edx, eax
    sub     edx, 0x10
    sar     edx, 31
    sub     ecx, edx
    add     ecx, 6
    mov     dword ptr [esp+0x14], ecx
tail:
    push    {SPRITE_DRAW:#x}
    ret
"""


def asm_fieldpads_v6() -> str:
    # v10 (2026-09-18, title_grow_delta == 0): every `sar r,3` delta is `sar r,31` (== 0, same length) and the keyed
    # flat/slide T arm is 22 NOPs -- eax keeps the engine arm T = ebx - ps3 (law popup_field_top).
    # v9 (2026-08-23c): keyed-T arm = FLAT/SLIDE only (popup_frame_rewrite_applies), reading
    # g_title_bottom (== band_stash's bottom for those families); the ORNATE family keeps the
    # engine arm T = ebx - ps3 (law popup_field_top: its chain is proportionate once the band
    # sits at s(13)/s(37), title_stash v7).  Ornate+art popups pre-adjust the two artalign
    # anchors: g_title_left += ceil(g/16)-(g>>4)-Delta (law popup_art_x) and g_field_anchor =
    # T + Delta (law popup_art_y).  (v7/v8's band-anchored-for-all arm + text-Y stash: REVERTED.)
    return f"""
    push    eax
    push    edx
    mov     dword ptr [{G_FP_ORNART:#x}], 0
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jg      s1
    mov     edx, 3
    jmp     s2
s1:
    lea     edx, [eax+eax*2]
    shr     edx, 4
s2:
    cmp     eax, 0x10
    jle     noorn
    cmp     esi, dword ptr [{G_BAND_POPUP:#x}]
    jne     noorn
    push    eax
    mov     eax, dword ptr [esi+0x30ac]
    {BAND_ORNATE("eax", "orn", "noorn_pop")}
noorn_pop:
    pop     eax
    jmp     noorn
orn:
    mov     ecx, dword ptr [{G_TITLE_RIGHT:#x}]
    sub     ecx, edx
    sub     ecx, edx
    mov     eax, dword ptr [{G:#x}]
    sub     eax, 0x10
    sar     eax, 31
    add     ecx, eax
    cmp     dword ptr [esi+0x2144], 0
    je      orn_done
    mov     dword ptr [{G_FP_ORNART:#x}], 1
    push    ecx
    mov     eax, dword ptr [{G:#x}]
    add     eax, 15
    shr     eax, 4
    mov     ecx, dword ptr [{G:#x}]
    shr     ecx, 4
    sub     eax, ecx
    mov     ecx, dword ptr [{G:#x}]
    sub     ecx, 0x10
    sar     ecx, 31
    sub     eax, ecx
    add     dword ptr [{G_TITLE_LEFT:#x}], eax
    pop     ecx
orn_done:
    pop     eax
noorn:
    add     ecx, edx
    mov     eax, edi
    sub     eax, edx
    mov     dword ptr [ebp-0x34], eax
    mov     dword ptr [ebp-0x2c], ecx
    mov     dword ptr [{G_FIELD_L:#x}], eax
    mov     dword ptr [{G_FIELD_R:#x}], ecx
    cmp     dword ptr [esi+0x2144], 0
    je      s3
    mov     dword ptr [{G_FIELD_L:#x}], 0
    mov     dword ptr [{G_FIELD_R:#x}], 0
s3:
    push    eax
    mov     eax, dword ptr [esi+0x30bc]
    mov     dword ptr [{G_FIELD_BOXW:#x}], eax
    pop     eax
    mov     eax, ebx
    sub     eax, edx
    cmp     dword ptr [{G:#x}], 0x10
    jle     s4
    cmp     esi, dword ptr [{G_BAND_POPUP:#x}]
    jne     s4
    push    ecx
    mov     ecx, dword ptr [esi+0x30ac]
    {BAND_FLATSLIDE("ecx", "s5", "s4_pop")}
s4_pop:
    pop     ecx
    jmp     s4
s5:
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    pop     ecx
s4:
    mov     dword ptr [ebp-0x30], eax
    cmp     dword ptr [{G_FP_ORNART:#x}], 0
    je      s6
    push    ecx
    mov     ecx, dword ptr [{G:#x}]
    sub     ecx, 0x10
    sar     ecx, 31
    add     eax, ecx
    pop     ecx
s6:
    mov     dword ptr [{G_FIELD_ANCHOR:#x}], eax
    pop     edx
    pop     eax
    test    eax, eax
    ret
"""


# ---- layout / assembly ------------------------------------------------------
NEW_THUNKS = [   # (name, asm fn) — laid out consecutively from OFF_CODE, 16-aligned
    ("thunk_cw_enter", asm_cw_enter),
    ("thunk_cw_immfix", asm_cw_immfix),
    ("thunk_cw_seeds", asm_cw_seeds),
    ("thunk_cw_texty", asm_cw_texty),
    ("thunk_parity_reblit", asm_parity_reblit_stub),
    ("thunk_cw_portrait", asm_cw_portrait),
    ("thunk_cw_logo", asm_cw_logo),
    ("thunk_cw_backdrop37", asm_cw_backdrop37),
    ("thunk_cw_chip", asm_cw_chip),
    ("thunk_btn_gate_pre", asm_btn_gate_pre),
    ("thunk_gv_arthead", asm_gv_arthead),
    ("thunk_gv_frameskip", asm_gv_frameskip),
    ("thunk_flag_restripe", asm_flag_restripe),
    ("thunk_sd_reblit_wrap", asm_sd_reblit_wrap),
    ("thunk_popup_fieldpads", asm_fieldpads_v6),   # v6..v9 RELOCATED 0x4550 -> tail (outgrew the 240B slot)
]
RELOCATED = {"thunk_popup_fieldpads": OFF_FIELDPADS, "thunk_btn_gate_pre": 0xC080}
# Assembled here (layout + parity tests) but NEVER written to the fragments: a later bake owns the shipped entry
# (feedback-fragment-refresh-reverts-foreign-entries; same mechanism as assemble_se.OWNED_ELSEWHERE).
OWNED_ELSEWHERE = {"thunk_btn_gate_pre": "assemble_rw.py (v5 @0x24230, group rw_scale_shared)",
                   "thunk_pf_textfollow": "assemble_pf_align.py (v3 @0x308A0, + the ornate arm, 2026-10-11)"}
INPLACE = [
    ("thunk_pf_textfollow", OFF_TEXTFOLLOW, asm_textfollow_v2),
    ("thunk_popup_artalign", OFF_ARTALIGN, artalign_v6_bytes),   # returns BYTES (v5 template + dword swap)
    ("t_gv_artx", OFF_GV_ARTX, asm_gv_artx),
]
NEW_INPLACE = {"t_gv_artx"}   # in-place slots this module ADDS (a symbol line is emitted for them)
DATA = [   # (name, offset, bytes)
    ("g_cw_seedtab", OFF_G_CW_SEEDTAB, seedtab_bytes),
    ("g_flag_lut", OFF_G_FLAG_LUT, lut_bytes),
    ("g_cw_immtab", OFF_G_CW_IMMTAB, immtab_bytes),
]
CELLS = [   # zero-init data (symbol + size only)
    ("g_council_active", OFF_G_COUNCIL_ACTIVE, 4),
    ("g_cw_vpdone", OFF_G_CW_VPDONE, 4),
    ("g_cw_vpold", OFF_G_CW_VPOLD, 4),
    ("g_flag_ret", OFF_G_FLAG_RET, 4),
    ("g_cw_chipscr", OFF_G_CW_CHIPSCR, 96),
    ("g_title_bottom", OFF_G_TITLE_BOTTOM, 4),
    ("g_fp_ornart", OFF_G_FP_ORNART, 4),
]

_ks = Ks(KS_ARCH_X86, KS_MODE_32)
_cs = Cs(CS_ARCH_X86, CS_MODE_32)
_cs.detail = True


def _clean(asm: str) -> str:
    return "\n".join(ln.split(";", 1)[0].rstrip() for ln in asm.splitlines() if ln.split(";", 1)[0].strip())


def assemble(asm: str, va: int, names: dict[str, int] | None = None) -> bytes:
    src = _clean(asm)
    if names:
        for k, v in names.items():
            src = src.replace(k, f"{v:#x}")
    enc, _ = _ks.asm(src, va)
    b = bytes(enc)
    total = sum(i.size for i in _cs.disasm(b, va))
    assert total == len(b), "capstone round-trip gap"
    return b


def assemble_all() -> tuple[dict[str, tuple[int, bytes]], int]:
    """Returns ({name: (offset, bytes)}, end_offset).  Two passes resolve the
    forward references between the new thunks (names substituted as literals)."""
    layout: dict[str, tuple[int, bytes]] = {}
    names = {n: PCAVE2 + OFF_CODE for n, _ in NEW_THUNKS}   # provisional
    for _pass in range(3):
        off = OFF_CODE
        new_names = {}
        for name, fn in NEW_THUNKS:
            va = PCAVE2 + off
            b = assemble(fn(), va, names)
            layout[name] = (off, b)
            new_names[name] = va
            off = (off + len(b) + 15) & ~15
        if new_names == names:
            break
        names = new_names
    else:
        raise RuntimeError("thunk layout did not converge")
    end = off
    for name, o, fn in INPLACE:
        src = fn()
        b = src if isinstance(src, (bytes, bytearray)) else assemble(src, PCAVE2 + o, names)
        assert o + len(b) <= SLOT_END[o], f"{name} overflows its slot: end {o + len(b):#x} > {SLOT_END[o]:#x}"
        layout[name] = (o, b)
    for name, o, fn in DATA:
        layout[name] = (o, fn())
    return layout, end


# ---- placeholder templating ------------------------------------------------
SYM_ABS = {   # literal VA -> yaml symbol name (abs32 placeholders)
    G: "g_popup_scale_num", G_TITLE_LEFT: "g_title_left", G_TITLE_RIGHT: "g_title_right",
    G_BAND_LEFT: "g_band_left", G_FIELD_ANCHOR: "g_field_anchor", G_BAND_POPUP: "g_band_popup",
    G_BAND_BOTTOM: "g_band_bottom", G_FIELD_L: "g_field_L", G_FIELD_R: "g_field_R",
    G_FIELD_BOXW: "g_field_boxw", G_D528_LEFT: "g_d528_left", SPRITE_DRAW: "thunk_sprite_draw",
    BUF_WRITE_STRINGS: "Buffer_write_strings", BTN_GATE: "thunk_btn_gate", STR_K32: "g_ed_str_k32",
    STR_VP: "g_ed_str_vp", DEVFILL: "thunk_box_thick_devfill", HOLLOWFLAT: "thunk_box_thick_hollow_flat",
    T_DP_ARTALIGN: "t_dp_artalign", CONTENT_FRAME: "thunk_content_frame", PORTRAIT_DROP: "thunk_portrait_drop",
    BOX_SPRITE: "Buffer_box_sprite", BUF_DRAW2: "Buffer_draw_2", FONT_INIT: "Font_init", SD2: "Sprite_draw_2",
}


EXTRA_SYMS = {G_COUNCIL_ACTIVE: "g_council_active", G_CW_VPDONE: "g_cw_vpdone", G_CW_VPOLD: "g_cw_vpold",
              G_FLAG_RET: "g_flag_ret", G_CW_SEEDTAB: "g_cw_seedtab", G_FLAG_LUT: "g_flag_lut",
              G_CW_IMMTAB: "g_cw_immtab", G_CW_CHIPSCR: "g_cw_chipscr", G_TITLE_BOTTOM: "g_title_bottom",
              G_FP_ORNART: "g_fp_ornart", 0x66879C: "g_stripe_period", T_GV_ARTX: "t_gv_artx",
              T_CW_MIRROR: "t_cw_mirror"}   # the flag thunk's period-cell read


def templatize(b: bytes, va: int, extra: dict[int, str]) -> str:
    """Emit yaml hex with {abs32:}/{rel32:} placeholders for every operand that
    equals a known symbol VA (capstone operand inspection, no blind byte scans)."""
    syms = dict(SYM_ABS)
    syms.update(extra)
    out = []
    for ins in _cs.disasm(b, va):
        raw = bytearray(ins.bytes)
        repl: list[tuple[int, str]] = []
        # the patcher accepts {rel32:} ONLY after E8 — jmp rel32 stays literal (engine targets);
        # cave-symbol tails use `push {abs32:sym}; ret` in the asm instead
        if ins.mnemonic == "call" and ins.operands and ins.operands[0].type == X86_OP_IMM and ins.size == 5:
            tgt = ins.operands[0].imm & 0xFFFFFFFF
            if tgt in syms:
                repl.append((1, "{rel32:" + syms[tgt] + "}"))
        elif ins.mnemonic.startswith("j") or ins.mnemonic == "call":
            # BRANCHES: capstone reports rel8/rel32 operands as their ABSOLUTE target, so a
            # jmp to a symbol VA must NOT become {abs32:} (build 1a2da25b: `jmp Font_init`
            # shipped as E9 <abs> -> EIP 0x1038244, the council-open crash). Literal.
            pass
        else:
            for op in ins.operands:
                if op.type == X86_OP_IMM and (op.imm & 0xFFFFFFFF) in syms and ins.imm_size == 4:
                    repl.append((ins.imm_offset, "{abs32:" + syms[op.imm & 0xFFFFFFFF] + "}"))
                elif op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0 and (op.mem.disp & 0xFFFFFFFF) in syms:
                    repl.append((ins.disp_offset, "{abs32:" + syms[op.mem.disp & 0xFFFFFFFF] + "}"))
                elif op.type == X86_OP_MEM and op.mem.index != 0 and op.mem.base == 0 and (op.mem.disp & 0xFFFFFFFF) in syms:
                    repl.append((ins.disp_offset, "{abs32:" + syms[op.mem.disp & 0xFFFFFFFF] + "}"))
        pos = 0
        for off, tok in sorted(repl):
            out.extend(f"{x:02X}" for x in raw[pos:off])
            out.append(tok)
            pos = off + 4
        out.extend(f"{x:02X}" for x in raw[pos:])
    return " ".join(out)


# ---- sites -------------------------------------------------------------------
def rel32(site: int, target: int) -> str:
    return " ".join(f"{x:02X}" for x in b"\xE8" + struct.pack("<i", target - (site + 5)))


SITES = [   # (id, function, site, original target, thunk, note)
    ("CouncilWin_exec.caller_bracket", "council_open_session(0x4284xx)", 0x4284CA, CW_EXEC, "thunk_cw_enter",
     "call CouncilWin_exec (thiscall RET 8; the ONE caller) -> immfix + g_council_active bracket"),
    ("CouncilWin_exec.seed_table", "CouncilWin_exec", 0x427784, FONT_INIT, "t_cw_rowsym",
     "call Font_init (the first of 6; esi=CWIN, seed table already written natively) -> rewrite the 63 seeds x g/16"),
    ("CouncilWin_draw_column.name_text_y", "CouncilWin_draw_column", 0x425F83, STC, "thunk_cw_texty",
     "call 0x5DACB0 (thiscall, ecx=edi) -> name-line y = T+1 + dp(portrait h) + dp(4)"),
    ("CouncilWin_draw_column.portrait_sd2", "CouncilWin_draw_column", 0x425F3C, SD2, "t_cw_portx",
     "call Sprite_draw_2 portrait (1,1) -> num=g/16 + parity re-blit"),
    ("CouncilWin_draw_column.logo_sd2", "CouncilWin_draw_column", 0x426105, SD2, "t_cw_logox",
     "call Sprite_draw_2 logo (1,1) -> recentre + num=g/16 + parity re-blit"),
    ("CouncilWin_repaint.backdrop37", "CouncilWin_repaint", 0x426B4E, BOX_SPRITE, "t_cw_bd2",
     "call Buffer_box_sprite d690 backdrop -> rect.right W-0x37 -> W-dp(0x37), tail devfill"),
    ("CouncilWin_draw_column.frame_d528", "CouncilWin_draw_column", 0x425EE9, BOX_SPRITE, "t_cw_hodf",
     "column frame d528 -> thick frame + device-density fill"),
    ("CouncilWin_draw_column.chip_da00", "CouncilWin_draw_column", 0x4261AA, BOX_SPRITE, "t_cw_chiphalf", "vote chip da00"),
    ("CouncilWin_draw_column.chip_d9d8", "CouncilWin_draw_column", 0x4261D6, BOX_SPRITE, "t_cw_chiphalf", "vote chip d9d8"),
    ("CouncilWin_draw_column.chip_da28_a", "CouncilWin_draw_column", 0x426203, BOX_SPRITE, "t_cw_chiphalf", "vote chip da28"),
    ("CouncilWin_draw_column.chip_da28_b", "CouncilWin_draw_column", 0x426230, BOX_SPRITE, "t_cw_chiphalf", "vote chip da28"),
    ("CouncilWin_draw_column.chip_da28_c", "CouncilWin_draw_column", 0x42625C, BOX_SPRITE, "t_cw_chiphalf", "vote chip da28"),
    ("CouncilWin_draw_column.d528_b", "CouncilWin_draw_column", 0x426286, BOX_SPRITE, "t_cw_hodf", "d528"),
    ("CouncilWin_repaint.d5a0", "CouncilWin_repaint", 0x426B7B, BOX_SPRITE, "t_cw_ring2", "d5a0 band (hollow)"),
    ("CouncilWin_repaint.d528", "CouncilWin_repaint", 0x426BD2, BOX_SPRITE, "t_cw_hodf", "repaint d528 (the ELECTED banner)"),
    # 2026-10-25 wave-2 W2A (F31; law scaling_laws.council_console_frame_rect): the three console-canvas (0x7AEC64)
    # frames around the proposal / VOTE row were drawn through thunk_hud_boxframe's pass-through, INCLUSIVE of R / B
    # (4K ring 5 | 6, 1080 top / bottom 3 | 4) -> t_rw_rowframe: exact-fill hollow_flat with R-1 / B-1 (g<=16 native)
    ("CouncilWin_repaint.console_box", "CouncilWin_repaint", 0x426B14, BOX_SPRITE, "t_rw_rowframe",
     "console d5a0 box (proposal rect inset 4): half-open R-1/B-1 exact-fill helper (was inclusive via hud_boxframe)"),
    ("CouncilWin_draw_proposal.header_band", "CouncilWin_draw_proposal", 0x4264DD, BOX_SPRITE, "t_rw_rowframe",
     "console d618 header band: half-open R-1/B-1 exact-fill helper (was inclusive via hud_boxframe)"),
    ("CouncilWin_draw_proposal.body_box", "CouncilWin_draw_proposal", 0x4265AB, BOX_SPRITE, "t_rw_rowframe",
     "console d528 body box (B = text bottom): half-open R-1/B-1 exact-fill helper (was inclusive via hud_boxframe)"),
    ("Sprite_blit_scaled_core.flag_restripe", "Sprite_blit_scaled_core", 0x5E4C01, BUF_DRAW2, "thunk_art_core",
     "call Buffer_draw_2 (filename-backed art path, ecx=canvas 0x9b6080) -> flag-content-gated pair-LUT restripe of the dest rect"),
]
# 2026-10-25 wave-5 W5B (assemble_council_mirror.py, laws scaling_laws.council_backdrop_rect v2 / council_drawn): the
# backdrop goes to t_cw_backdrop (rect L / R on the slide rails' cascades, then t_cw_hodf -- thunk_cw_backdrop37 is
# still assembled here, no longer called by a site), the d5a0 ring to t_bm_ho_hf, the column d528 / d528 chip to
# t_cw_hodf and the five vote chips to t_cw_chiphalf (R-1 / B-1 around their old renderers): every council frame
# half-open.  2026-10-25 wave-7 W7B (assemble_council_mirror.py, laws council_backdrop_rect v3 / council_frame_clip /
# council_logo_x): the backdrop goes to t_cw_bd2 (+ B = H + K) and the ring to t_cw_ring2, both through t_cw_clipdraw
# (the frame clipped below the canvas, not clamped onto it); the logo to t_cw_logox (centred, then thunk_cw_logo).
# The vote-chip sites went to t_si_chip first (assemble_stripes_icon.py, 2026-10-04; thunk_cw_chip is still assembled
# here, no longer called by a site) and the flag site to thunk_art_core (assemble_artreblit.py, 2026-09-20; it
# calls thunk_flag_restripe first); the seed_table site goes to t_cw_rowsym (assemble_mirror_pairs.py, 2026-10-25 W3A F43;
# it tails thunk_cw_seeds).  Those bakes took the sites over; the targets here are the SHIPPED ones so a
# --splice reproduces patches.yaml (tests/test_stale_sources.py).
NEW_BYTES_NOTE = {
    "CouncilWin_repaint.backdrop37":
        "2026-10-25 W7B: + B = H + K, the frame clipped below the canvas (was {rel32:t_cw_backdrop}; W5B: was {rel32:thunk_cw_backdrop37})",
    "CouncilWin_draw_column.logo_sd2":
        "2026-10-25 W7B: the logo centred in the column interior, then thunk_cw_logo (was {rel32:thunk_cw_logo})",
    "CouncilWin_draw_column.portrait_sd2":
        "2026-10-25 W6B v2: the portrait centred in the column interior, then thunk_cw_portrait (was {rel32:thunk_cw_portrait})",
    "CouncilWin_repaint.d528":
        "2026-10-25 W6B: the ELECTED banner half-open (was {rel32:thunk_box_thick_devfill})",
    "CouncilWin_repaint.d5a0":
        "2026-10-25 W7B: the ring clipped below the canvas (was {rel32:t_bm_ho_hf}; W5B: was {rel32:thunk_box_thick_hollow_flat})",
    "CouncilWin_draw_column.frame_d528":
        "2026-10-25 W5B: half-open (was {rel32:thunk_box_thick_devfill})",
    "CouncilWin_draw_column.d528_b":
        "2026-10-25 W5B: half-open (was {rel32:thunk_box_thick_devfill})",
    "CouncilWin_draw_column.chip_da00":
        "2026-10-25 W5B: half-open around t_si_chip (was {rel32:t_si_chip})",
    "CouncilWin_draw_column.chip_d9d8":
        "2026-10-25 W5B: half-open around t_si_chip (was {rel32:t_si_chip})",
    "CouncilWin_draw_column.chip_da28_a":
        "2026-10-25 W5B: half-open around t_si_chip (was {rel32:t_si_chip})",
    "CouncilWin_draw_column.chip_da28_b":
        "2026-10-25 W5B: half-open around t_si_chip (was {rel32:t_si_chip})",
    "CouncilWin_draw_column.chip_da28_c":
        "2026-10-25 W5B: half-open around t_si_chip (was {rel32:t_si_chip})",
    "CouncilWin_exec.seed_table":
        "2026-10-25 W3A F43: the YES / NO / ABSTAIN row's remainder mirrored at g>16, then thunk_cw_seeds "
        "(was {rel32:thunk_cw_seeds})",
    "Sprite_blit_scaled_core.flag_restripe":
        "popup_art_reblit 2026-09-20: calls thunk_flag_restripe first, then re-blits filename-backed popup pictures "
        "(was {rel32:thunk_flag_restripe})",
}


def base_exe_bytes(va: int, n: int) -> bytes:
    """Bytes of the PRISTINE base (.bak = 2d0b1438) the patcher applies onto."""
    exe = str(config.terranx_bak(required=True))
    import pefile
    pe = pefile.PE(exe, fast_load=True)
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def roundtrip_problems(layout, extra) -> list[str]:
    """The patcher must resolve every templatized entry back to the EXACT assembled
    bytes (the templating step is the one thing the Unicorn parity tests cannot see)."""
    import pathlib
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(symbols, caves))
    for va, name in extra.items():
        symtab[name] = va
    out = []
    for name, (off, b) in layout.items():
        if name in ("g_cw_seedtab", "g_flag_lut", "g_cw_immtab"):
            continue
        va = PCAVE2 + off
        hexs = templatize(b, va, extra)
        try:
            back = ap.ByteTemplate(hexs).resolve(va, symtab)
        except Exception as e:  # noqa: BLE001
            out.append(f"{name}: template does not resolve: {e}")
            continue
        if back != b:
            i = next(k for k in range(min(len(b), len(back))) if b[k] != back[k]) if len(b) == len(back) else -1
            out.append(f"{name}: resolved bytes differ at +{i:#x} (len {len(back)} vs {len(b)})")
    return out


def verify_live() -> list[str]:
    """Every redirect site must hold E8 -> the expected native target, and every
    imm site its native value, in the BASE exe (the imm audit was done on the
    pristine Ghidra project — re-check the bytes the patcher really sees; PRACX
    stomps its sites at RUNTIME, which the proto's [live] dump covered)."""
    problems = []
    for sid, _fn, site, tgt, _th, _note in SITES:
        have = base_exe_bytes(site, 5)
        want = bytes.fromhex(rel32(site, tgt).replace(" ", ""))
        if have != want:
            problems.append(f"{sid} @{site:#x}: live {have.hex()} != {want.hex()}")
    for site, a, b, kind in IMMTAB:
        native = a - b
        if kind & 2:
            native = -native
        if kind & 1:
            have = struct.unpack("<i", base_exe_bytes(site, 4))[0]
        else:
            have = struct.unpack("<b", base_exe_bytes(site, 1))[0]
        if have != native:
            problems.append(f"imm @{site:#x}: live {have} != native {native}")
    return problems


def main(argv: list[str]) -> int:
    layout, end = assemble_all()
    names = {n: PCAVE2 + layout[n][0] for n, _ in NEW_THUNKS}
    extra = {va: n for n, va in names.items()}
    extra.update(EXTRA_SYMS)
    ok = True
    print("; ==== council_scale bake (assemble_council.py) ====")
    print(f"; new code {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B), section end {SECTION_END:#x}")
    if end > SECTION_END:
        ok = False
        print("; OVERFLOW past the section end")
    sym_lines, content_lines = [], []
    for name, off, size in CELLS:
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    for name, _o, _fn in DATA:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {len(b)} }}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{' '.join(f'{x:02X}' for x in b)}\"")
    for name, _fn in NEW_THUNKS:
        off, b = layout[name]
        if name in OWNED_ELSEWHERE:
            print(f"; {name} @{off:#x} len {len(b)} -- NOT EMITTED, owned by {OWNED_ELSEWHERE[name]}")
            continue
        reloc = f", RELOCATED from {RELOCATED[name]:#x} (old slot freed/zeros)" if name in RELOCATED else ""
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # council_scale ({len(b)}B{reloc})")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, extra)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    for name, o, _fn in INPLACE:
        off, b = layout[name]
        if name in OWNED_ELSEWHERE:
            print(f"; {name} @{off:#x} len {len(b)} -- NOT EMITTED, owned by {OWNED_ELSEWHERE[name]}")
            continue
        print(f"; {name} IN PLACE @{off:#x} len {len(b)} end {off + len(b):#x} (slot to {SLOT_END[off]:#x})")
        if name in NEW_INPLACE:
            sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # council_scale ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, extra)}\"")
    site_lines = []
    for sid, fn, site, tgt, th, note in SITES:
        nb_note = f"   # {NEW_BYTES_NOTE[sid]}" if sid in NEW_BYTES_NOTE else ""
        site_lines.append(
            f"  - id: {sid}\n    status: confirmed\n    group: council_scale\n    function: {fn}\n"
            f"    virtual_addr: {site:#010x}\n    length: 5\n    original_bytes: \"{rel32(site, tgt)}\"   # {note}\n"
            f"    new_bytes:      \"E8 {{rel32:{th}}}\"{nb_note}\n    pattern: call_target_redirect\n")
    probs = verify_live()
    for p in probs:
        print("; LIVE MISMATCH:", p)
    if probs:
        ok = False
    rt = roundtrip_problems(layout, extra)
    for p in rt:
        print("; TEMPLATE ROUND-TRIP MISMATCH:", p)
    if rt:
        ok = False
    if "--splice" in argv or "--fragments" in argv:
        frag_dir = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag_dir, "_fragment_council_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_council_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_council_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(site_lines))
        print("; fragments written to work/patches/_fragment_council_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print("\n".join(site_lines))
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
