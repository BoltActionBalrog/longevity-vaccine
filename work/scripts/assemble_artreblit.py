#!/usr/bin/env python
"""Assembler for group popup_art_reblit (2026-09-20): scanline-dithered art on the shared popup canvas.

Every BasePop picture drawn into FACTION_QUOTE_BUF 0x940824 (the *_sm.pcx event pictures, the version logo, the
faction-picker portrait) was resampled by thunk_portrait_avg (bilinear) and skipped by thunk_sd_reblit_wrap's
council re-blit, so its 1-row scanline dither banded at g=22/25.  Laws: scaling_laws.art_reblit_row /
art_reblit_col / art_reblit / quote_art_origin.

  thunk_art_wrap    new target of thunk_sprite_draw's internal CALL (was thunk_sd_reblit_wrap; same contract:
                    ecx=Sprite, stack dest,key,x,y,num,den, RET 0x18).  dest != quote buf or g <= 16: tail-jump
                    thunk_sd_reblit_wrap (byte-identical behaviour).  Else: CALL it with an arg copy (draw +
                    portrait drop), then thunk_art_reblit at quote_art_origin.
  thunk_art_reblit  the edge-pinned parity re-blit (clone of assemble_council.asm_parity_reblit, new row law).
  thunk_art_draw    Sprite_draw_2 drop-in (same contract, caller's num/den kept): draw, then thunk_art_reblit over
                    it.  Tail target of t_dp_sd2_hqpic (the diplomacy console's base picture; assemble_diplo.py)
                    and CALL target of BasePop_on_redraw's DIRECT art draw @0x604C72 (every popup whose
                    [popup+0x3168] is 0: the in-game event-picture modals -- drone riot etc.; ratio fields =
                    g/16 from popup_art_scaling).
  thunk_art_flic    Flic_draw_frame wrapper for the three diplomacy flic sites (were t_dp_flicdraw): after the
                    StretchBlt of the native scratch frame, re-blit it through the law (key 0x100 = opaque; the
                    BIOSCAN figure's scanline backdrop and the news thumbnail banded at g=22/25).
  thunk_art_core    CALL target of the blit core's Buffer_draw_2 @0x5E4C01 (was thunk_flag_restripe, which it calls
                    first): FILENAME-BACKED sprites (every in-game popup picture; pcBits is NULL forever, so the
                    Sprite-level re-blits above bail on them) reach their pixels only here, as the canvas-manager
                    src Buffer in ecx.  num > den and not the UN flag (thunk_flag_restripe's own content gate) ->
                    thunk_art_reblit from the src Buffer at the device X,Y the core passes.
  g_art_spr         0x30-byte Sprite-shaped view of the scratch Buffer handed to thunk_art_reblit.
  t_art_frame_rows  (v4 2026-10-17) the body's frame-row block, CALLed with the body's ebp: jt/jb/H1/4*H1/H0 and the
                    UNFRAMED flag [ebp-0x6C].  Unframed by IDENTITY: the sprite's pixel pointer [ebp-4] is the BIOSCAN
                    colour bar's ([0x7D1620]) or one of the 16 council portrait slots' ([0x78E978 + f*0x65C +
                    0x478/0x4A4 + 4], f = 0..7) -> no pinned frame row, field rows over all sh rows
                    (scaling_laws.art_reblit_row framed=False).  Everything else: the v3 law, byte for byte.
Parity: tests\test_artreblit_asm_parity.py.  Usage: py assemble_artreblit.py   (prints the yaml entries)
"""
from __future__ import annotations

import contextlib
import io
import sys

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_council as AC

PCAVE2 = AC.PCAVE2
G = AC.G
QUOTE_BUF = AC.FACTION_QUOTE_BUF
OFF_ART_WRAP = 0x29C00
OFF_ART_REBLIT = 0x29C80                   # v2 (2026-10-04): a stub (same entry bytes) into the body below
OFF_ART_REBLIT_BODY = AC.OFF_REBLIT_BODY   # 0x27640: the shared body (thunk_art_reblit + thunk_parity_reblit)
REBLIT_BODY_END = 0x27900                  # t_pw_enlarge; cave_map.py --at 0x27640
OFF_ART_DRAW = 0x29EB0
OFF_ART_FLIC = 0x2D560                     # v2 (2026-09-21): + bio save-under restore, key 9; was 0x29F20 (155B in a 160B slot)
OFF_ART_BIOINIT = 0x2D460                  # thunk_art_bioinit (2026-09-21)
OFF_G_BIO_UNDER = 0x2D6C0                  # 4B cell: Buffer* device-size save-under of the strip beneath the BIOSCAN rect
OFF_G_ART_SPR = 0x29FC0
OFF_ART_FRAME_ROWS = 0x29F20               # t_art_frame_rows (v4 2026-10-17): free 0x29F06..0x29FC0 (thunk_art_flic v1's old slot)
COLOUR_BAR_DATA = 0x7D161C + 4             # g_diplo_colour_bar_sprite +4: its pixel pointer
COUNCIL_SLOT_DATA = 0x78E978 + 0x478 + 4   # g_faction_sprites[0] council portrait slot (+0x478; +0x4A4 = +0x2C) +4
FAC_STRIDE = 0x65C
N_FACTIONS = 8
OFF_ART_CORE = 0x1CAB0                     # free gap after thunk_btn_ringfix (to 0x1D000)
FLAG_RESTRIPE = AC.PCAVE2 + 0x13850        # thunk_flag_restripe (council_scale)
SLOT_END = 0x2A000
SD2 = AC.SD2
T_DP_FLICDRAW = PCAVE2 + 0x12000           # t_dp_flicdraw (diplo_talk_scale)
T_DP_FLINIT_BIO = PCAVE2 + 0x11F7C         # t_dp_flinit_bio (diplo_talk_scale): scales x,y then jmp Flic_init
CRT_MALLOC = 0x64558A
BUF_CTOR = 0x5D7210
BUF_RESIZE = 0x5D79C0                      # thiscall(w, h) RET 8
BUF_COPY_3 = 0x5D9610                      # thiscall(src; dst, sx, sy, sw, sh, dx, dy, dw, dh) RET 0x24 = GDI StretchBlt
G_DP_SCR_NEWS = PCAVE2 + 0x1157C
G_DP_SCR_BIO = PCAVE2 + 0x11580
FLIC_NEWS = 0x733990 + 0xAE8               # DiploTalkWin news flic
FLIC_BIO = 0x733990 + 0x15CC               # DiploTalkWin bioscan flic
ART_DRAW = PCAVE2 + OFF_ART_DRAW
ART_FLIC = PCAVE2 + OFF_ART_FLIC
ART_BIOINIT = PCAVE2 + OFF_ART_BIOINIT
G_BIO_UNDER = PCAVE2 + OFF_G_BIO_UNDER
G_ART_SPR = PCAVE2 + OFF_G_ART_SPR
ART_CORE = PCAVE2 + OFF_ART_CORE
SD_REBLIT_WRAP = PCAVE2 + 0x139D0          # thunk_sd_reblit_wrap (council_scale)
ART_WRAP = PCAVE2 + OFF_ART_WRAP
ART_REBLIT = PCAVE2 + OFF_ART_REBLIT
ART_REBLIT_BODY = PCAVE2 + OFF_ART_REBLIT_BODY
ART_FRAME_ROWS = PCAVE2 + OFF_ART_FRAME_ROWS


def asm_art_wrap() -> str:
    push6a = "".join("    push dword ptr [esp+0x1C]\n" for _ in range(6))
    return f"""
    cmp     dword ptr [esp+4], {QUOTE_BUF:#x}
    jne     plain
    cmp     dword ptr [{G:#x}], 0x10
    jle     plain
    push    esi
    mov     esi, ecx
{push6a}
    mov     ecx, esi
    call    {SD_REBLIT_WRAP:#x}
    push    eax
    push    dword ptr [esp+0x20]            ; den
    push    dword ptr [esp+0x20]            ; num
    mov     eax, dword ptr [{G:#x}]
    sub     eax, 0x10
    imul    eax, eax, 12
    sar     eax, 4
    add     eax, dword ptr [esp+0x20]       ; y + fl(12(g-16)/16)
    push    eax
    mov     eax, dword ptr [{G:#x}]
    imul    eax, eax, 5
    sar     eax, 4
    push    eax                             ; x = fl(5g/16)
    push    dword ptr [esp+0x20]            ; key
    push    dword ptr [esp+0x20]            ; dest
    mov     ecx, esi
    call    {ART_REBLIT:#x}
    pop     eax
    pop     esi
    ret     0x18
plain:
    push    {SD_REBLIT_WRAP:#x}
    ret
"""


def asm_art_reblit() -> str:
    """assemble_council.asm_parity_reblit with the row law swapped for scaling_laws.art_reblit_row."""
    src = AC.asm_parity_reblit()
    old_row = src[src.index("    lea     eax, [eax*2+1]\n    imul    eax, dword ptr [ebp+0x1C]\n    xor     edx, edx\n    div     dword ptr [ebp-0x44]"):
                  src.index("r_ok:")]
    assert "p_ok" in old_row and old_row.count("\n") < 20
    new_row = """    lea     ebx, [eax*2+1]
    mov     eax, ebx
    imul    eax, dword ptr [ebp-0x10]
    xor     edx, edx
    div     dword ptr [ebp-0x50]
    mov     ecx, dword ptr [ebp-0x10]
    dec     ecx
    cmp     eax, ecx
    jl      c_ok
    mov     eax, ecx
c_ok:
    test    eax, eax
    jz      r_ok
    cmp     eax, ecx
    je      r_ok
    cmp     dword ptr [ebp-0x10], 4
    jl      r_ok
    mov     eax, ebx
    imul    eax, dword ptr [ebp+0x1C]
    xor     edx, edx
    div     dword ptr [ebp-0x44]
    add     eax, eax
    mov     edx, dword ptr [ebp-0x38]
    and     edx, 1
    add     eax, edx
r_lo:
    cmp     eax, 1
    jge     r_hi
    add     eax, 2
    jmp     r_lo
r_hi:
    dec     ecx
r_hi2:
    cmp     eax, ecx
    jle     r_ok
    sub     eax, 2
    jmp     r_hi2
"""
    mask = "    and     eax, 0xFF\n"
    assert src.count(mask) == 1
    src = src.replace(mask, "")                    # key > 0xFF = opaque (no texel equals it)
    start, end = src.index(old_row), src.index(old_row) + len(old_row)
    assert 0 < start < end
    src = src[:start] + new_row + src[end:]
    # column map: nn_center_index(i, dw, sw) = (2i+1)*sw / (2*dw)
    lines = src.split("\n")
    k = [i for i, ln in enumerate(lines) if ln.strip() == 'div     dword ptr [ebp-0x40]']
    assert len(k) == 1 and lines[k[0] - 2].strip() == 'imul    eax, dword ptr [ebp+0x1C]'
    lines[k[0] - 2] = '    imul    eax, dword ptr [ebp-0xC]'
    lines[k[0]] = '    div     dword ptr [ebp-0x4C]'
    # stash 2*dw / 2*dh once both device extents are known
    d = [i for i, ln in enumerate(lines) if ln.strip() == 'mov     dword ptr [ebp-0x20], eax']
    assert len(d) == 1
    lines[d[0] + 1:d[0] + 1] = ['    add     eax, eax', '    mov     dword ptr [ebp-0x50], eax',
                                '    mov     eax, dword ptr [ebp-0x1C]', '    add     eax, eax',
                                '    mov     dword ptr [ebp-0x4C], eax']
    return "\n".join(lines)


def asm_art_frame_rows() -> str:
    """t_art_frame_rows (v4 2026-10-17): CALLed by the body with its ebp.  Writes -0x54 jt, -0x58 jb (0, 0 below 4
    rows or with no device row: then nothing else), -0x5C H1 = jb - jt, -0x68 4*H1, -0x60 H0, -0x6C unframed (0/1).
    Framed: art_frame_rows' closed form, H0 = sh - 2 (the v3 inline block).  Unframed (identity, see the module doc):
    jt = 0, jb = dh, H0 = sh.  Clobbers eax, ebx, ecx, edx, like the v3 inline block."""
    return f"""
    xor     eax, eax
    mov     dword ptr [ebp-0x54], eax
    mov     dword ptr [ebp-0x58], eax
    mov     dword ptr [ebp-0x6C], eax
    mov     ecx, dword ptr [ebp-0x10]
    cmp     ecx, 4
    jl      fr_done
    mov     eax, dword ptr [ebp-0x20]
    test    eax, eax
    jle     fr_done
    mov     edx, dword ptr [ebp-4]
    cmp     edx, dword ptr [{COLOUR_BAR_DATA:#x}]
    je      unf
    mov     ebx, {COUNCIL_SLOT_DATA:#x}
uloop:
    cmp     edx, dword ptr [ebx]
    je      unf
    cmp     edx, dword ptr [ebx+0x2C]
    je      unf
    add     ebx, {FAC_STRIDE:#x}
    cmp     ebx, {COUNCIL_SLOT_DATA + N_FACTIONS * FAC_STRIDE:#x}
    jb      uloop
    lea     eax, [eax*2+ecx-1]
    lea     ebx, [ecx+ecx]
    xor     edx, edx
    div     ebx
    cmp     eax, dword ptr [ebp-0x20]
    jle     jt_ok
    mov     eax, dword ptr [ebp-0x20]
jt_ok:
    mov     dword ptr [ebp-0x54], eax
    mov     eax, dword ptr [ebp-0x20]
    add     eax, eax
    lea     ebx, [ecx-1]
    imul    eax, ebx
    dec     eax
    xor     edx, edx
    div     ecx
    inc     eax
    shr     eax, 1
    cmp     eax, dword ptr [ebp-0x20]
    jle     jb_ok
    mov     eax, dword ptr [ebp-0x20]
jb_ok:
    sub     ecx, 2
    jmp     rows
unf:
    mov     dword ptr [ebp-0x6C], 1
rows:
    mov     dword ptr [ebp-0x58], eax
    sub     eax, dword ptr [ebp-0x54]
    mov     dword ptr [ebp-0x5C], eax
    shl     eax, 2
    mov     dword ptr [ebp-0x68], eax
    mov     dword ptr [ebp-0x60], ecx
fr_done:
    ret
"""


# the body's frame-row block (v4): the helper, then T = art_scan_rows(num, den) at -0x64 (computed always now; read
# only by field rows, which exist only when jt < jb)
FRAME_ROWS = f"""    call    {ART_FRAME_ROWS:#x}
    mov     eax, dword ptr [ebp+0x18]
    cdq
    idiv    dword ptr [ebp+0x1C]
    cmp     eax, 2
    jge     t_ok
    mov     eax, dword ptr [ebp+0x18]
    shl     eax, 4
    imul    edx, dword ptr [ebp+0x1C], 22
    cmp     eax, edx
    setge   al
    movzx   eax, al
    inc     eax
t_ok:
    mov     dword ptr [ebp-0x64], eax"""

FIELD_ROW = """    lea     ebx, [eax*2+1]
    mov     eax, ebx
    imul    eax, dword ptr [ebp-0x10]
    xor     edx, edx
    div     dword ptr [ebp-0x50]
    mov     ecx, dword ptr [ebp-0x10]
    dec     ecx
    cmp     eax, ecx
    jl      c_ok
    mov     eax, ecx
c_ok:
    mov     ecx, dword ptr [ebp-0x38]
    cmp     ecx, dword ptr [ebp-0x54]
    jl      r_ok
    cmp     ecx, dword ptr [ebp-0x58]
    jge     r_ok
    mov     eax, ecx
    add     eax, dword ptr [ebp-0x18]
    sub     ecx, dword ptr [ebp-0x54]
    xor     edx, edx
    div     dword ptr [ebp-0x64]
    and     eax, 1
    mov     ebx, eax
    xor     ebx, dword ptr [ebp-0x6C]
    lea     eax, [ecx*2+1]
    imul    eax, dword ptr [ebp-0x60]
    mov     edx, dword ptr [ebp-0x5C]
    test    ebx, ebx
    jz      add_h1
    neg     edx
add_h1:
    add     eax, edx
    jns     m_pos
    xor     eax, eax
    jmp     m_clamp
m_pos:
    xor     edx, edx
    div     dword ptr [ebp-0x68]
m_clamp:
    mov     ecx, dword ptr [ebp-0x60]
    sub     ecx, ebx
    inc     ecx
    shr     ecx, 1
    dec     ecx
    cmp     eax, ecx
    jle     m_ok
    mov     eax, ecx
m_ok:
    lea     eax, [eax*2+ebx+1]
    sub     eax, dword ptr [ebp-0x6C]
"""


def asm_art_reblit_body() -> str:
    """v2 (2026-10-04): scaling_laws.art_reblit with art_reblit_row's FIELD map (scanlines art_scan_rows(num, den)
    device rows thick, the popup pictures' rule).  v3 (2026-10-06, option B stage 2): the field is that of the
    DEST-BUFFER row y0 + j ([ebp-0x18] + the row index), the chrome's stripe grid (art_scan_phase), not of the
    interior row j - jt.  Entered by JMP from the two stubs, which ran
    push ebp / mov ebp,esp / sub esp,0x50; 0x20 more bytes of locals: -0x54 jt, -0x58 jb, -0x5C H1 = jb-jt,
    -0x60 H0 = sh-2, -0x64 T, -0x68 4*H1 (jt/jb = art_frame_rows' closed form; jt = jb = 0 below 4 rows).
    v4 (2026-10-17): the frame-row block is t_art_frame_rows (CALLed; -0x6C = unframed by identity -> jt = 0,
    jb = dh, H0 = sh), the field row's parity q = k ^ unframed, source row 2m + q + 1 - unframed
    (scaling_laws.art_scan_near, top = 1 - unframed)."""
    src = asm_art_reblit()
    head = "\n    push    ebp\n    mov     ebp, esp\n    sub     esp, 0x50\n"
    assert src.startswith(head)
    src = "\n    sub     esp, 0x20\n" + src[len(head):]
    start, end = src.index("    lea     ebx, [eax*2+1]\n"), src.index("r_ok:")
    assert 0 < start < end and "r_hi2" in src[start:end]
    src = src[:start] + FIELD_ROW + src[end:]
    anchor = "    mov     dword ptr [ebp-0x4C], eax\n"
    assert src.count(anchor) == 1
    return src.replace(anchor, anchor + FRAME_ROWS + "\n")


def asm_art_reblit_stub() -> str:
    """thunk_art_reblit's entry: the v1 prologue bytes 55 89 E5 83 EC 50 (uimod.dll's detour checks them), then
    the shared body."""
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x50
    jmp     {ART_REBLIT_BODY:#x}
"""


def asm_art_draw() -> str:
    push6a = "".join("    push dword ptr [esp+0x1C]\n" for _ in range(6))
    push6b = "".join("    push dword ptr [esp+0x20]\n" for _ in range(6))
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      scaled
    push    {SD2:#x}
    ret
scaled:
    push    esi
    mov     esi, ecx
{push6a}
    mov     ecx, esi
    call    {SD2:#x}
    push    eax
{push6b}
    mov     ecx, esi
    call    {ART_REBLIT:#x}
    pop     eax
    pop     esi
    ret     0x18
"""


def asm_art_bioinit() -> str:
    """Flic_init wrapper for the BIOSCAN flic (site DiploTalkWin_open.flic_bio; was t_dp_flinit_bio directly).
    thiscall(flic=ecx; dst, name, x, y, flag) RET 0x14.  Probe 2026-09-21 (hook_bioscan_probe.js): dip_?_n.flc runs
    KEYED (flags 0x3, key 9) and Flic_init captures the flic's bg canvas (+4) as w x h NATIVE texels from the already
    DEVICE-scaled strip, so every frame the engine BG-restores a device-density stripe patch into our native scratch
    and substitutes it for the key texels; the x g/16 stretch + parity re-blit then mangle it (4K too).  After the
    native init: (1) fill that canvas with index 9 -> the scratch becomes figure + key; (2) alloc/resize g_dp_bio_under
    to the DEVICE rect (w*g/16 x h*g/16) and capture the strip under (x, y) into it (the panel is drawn before
    Flic_init -- the engine's own capture relies on it).  thunk_art_flic restores from it and re-blits with key 9."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      scaled
    push    {T_DP_FLINIT_BIO:#x}
    ret
scaled:
    push    esi
    push    edi
    push    ebx
    mov     esi, ecx
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    mov     ecx, esi
    call    {T_DP_FLINIT_BIO:#x}
    push    eax
    mov     edi, dword ptr [esi+0x58]       ; canvas(+4) data
    test    edi, edi
    jz      nofill
    mov     edx, dword ptr [esi+0x88]       ; canvas h (negative)
    test    edx, edx
    jns     hpos
    neg     edx
hpos:
    mov     ebx, dword ptr [esi+0x4AC]      ; canvas pitch
    mov     al, 9
fillrow:
    test    edx, edx
    jle     nofill
    mov     ecx, dword ptr [esi+0x84]       ; canvas w
    test    ecx, ecx
    jle     nofill
    push    edi
    rep     stosb
    pop     edi
    add     edi, ebx
    dec     edx
    jmp     fillrow
nofill:
    mov     edi, dword ptr [{G_BIO_UNDER:#x}]
    test    edi, edi
    jnz     have
    push    0x588
    call    {CRT_MALLOC:#x}
    add     esp, 4
    test    eax, eax
    jz      done
    mov     edi, eax
    mov     ecx, edi
    call    {BUF_CTOR:#x}
    mov     dword ptr [{G_BIO_UNDER:#x}], edi
have:
    mov     ecx, dword ptr [{G:#x}]
    mov     eax, dword ptr [esi+0x59C]
    imul    eax, ecx
    sar     eax, 4                          ; dw
    mov     edx, dword ptr [esi+0x5A0]
    imul    edx, ecx
    sar     edx, 4                          ; dh
    mov     ebx, eax
    push    edx
    push    edx
    push    ebx
    mov     ecx, edi
    call    {BUF_RESIZE:#x}
    pop     edx
    push    edx
    push    ebx
    push    0
    push    0
    push    edx
    push    ebx
    push    dword ptr [esi+0x5B0]           ; sy = y (device, stored by Flic_init)
    push    dword ptr [esi+0x5AC]           ; sx = x
    push    edi                             ; dst = save-under
    mov     ecx, dword ptr [esi+0x5A8]      ; src = the strip
    call    {BUF_COPY_3:#x}
done:
    pop     eax
    pop     ebx
    pop     edi
    pop     esi
    ret     0x14
"""


def asm_art_flic() -> str:
    # thiscall(flic=ecx; x, y) RET 8.  v2: the BIOSCAN path restores the strip under the rect from g_dp_bio_under
    # (1:1 StretchBlt over t_dp_flicdraw's stretch of figure + key) and re-blits with key 9 (the lawful panel shows
    # through the silhouette); the news path is unchanged (opaque key 0x100).
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     plain
    cmp     ecx, {FLIC_NEWS:#x}
    je      ours
    cmp     ecx, {FLIC_BIO:#x}
    je      ours
plain:
    push    {T_DP_FLICDRAW:#x}
    ret
ours:
    push    esi
    mov     esi, ecx
    push    dword ptr [esp+0xC]
    push    dword ptr [esp+0xC]
    call    {T_DP_FLICDRAW:#x}
    push    eax
    push    0x100                           ; re-blit key
    mov     edx, dword ptr [{G_DP_SCR_NEWS:#x}]
    cmp     esi, {FLIC_NEWS:#x}
    je      got
    mov     edx, dword ptr [{G_DP_SCR_BIO:#x}]
    mov     dword ptr [esp], 9
    mov     ecx, dword ptr [{G_BIO_UNDER:#x}]
    test    ecx, ecx
    jz      got
    push    edx
    mov     eax, dword ptr [{G:#x}]
    mov     ecx, dword ptr [esi+0x59C]
    imul    ecx, eax
    sar     ecx, 4                          ; dw
    imul    eax, dword ptr [esi+0x5A0]
    sar     eax, 4                          ; dh
    push    eax
    push    ecx
    push    dword ptr [esp+0x20]            ; dy = y
    push    dword ptr [esp+0x20]            ; dx = x
    push    eax
    push    ecx
    push    0
    push    0
    push    dword ptr [esi+0x5A8]           ; dst = the strip
    mov     ecx, dword ptr [{G_BIO_UNDER:#x}]
    call    {BUF_COPY_3:#x}
    pop     edx
got:
    test    edx, edx
    je      out
    mov     eax, dword ptr [edx+0x54]
    mov     dword ptr [{G_ART_SPR + 4:#x}], eax
    mov     eax, dword ptr [edx+0x4A8]
    mov     dword ptr [{G_ART_SPR + 0xC:#x}], eax
    mov     eax, dword ptr [esi+0x59C]
    mov     dword ptr [{G_ART_SPR + 0x10:#x}], eax
    mov     eax, dword ptr [esi+0x5A0]
    mov     dword ptr [{G_ART_SPR + 0x14:#x}], eax
    push    16
    push    dword ptr [{G:#x}]
    push    dword ptr [esp+0x1C]            ; y
    push    dword ptr [esp+0x1C]            ; x
    push    dword ptr [esp+0x10]            ; key
    push    dword ptr [esi+0x5A8]
    mov     ecx, {G_ART_SPR:#x}
    call    {ART_REBLIT:#x}
out:
    add     esp, 4
    pop     eax
    pop     esi
    ret     8
"""


def asm_art_core() -> str:
    # E8-entered from the blit core: ecx = src Buffer; [esp+4]=dest +8 key +C X +10 Y +14 num +18 den; RET 0x18
    push6 = "".join("    push dword ptr [esp+0x1C]" + chr(10) for _ in range(6))
    return f"""
    push    esi
    mov     esi, ecx
{push6}
    mov     ecx, esi
    call    {FLAG_RESTRIPE:#x}
    push    eax
    mov     eax, dword ptr [esp+0x1C]
    cmp     eax, dword ptr [esp+0x20]
    jle     out
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    je      out
    mov     ecx, dword ptr [esi+0x4A8]
    test    ecx, ecx
    jle     out
    mov     edx, dword ptr [esi+0x84]
    test    edx, edx
    jns     hpos
    neg     edx
hpos:
    cmp     dword ptr [esi+0x80], 200
    jne     art
    cmp     edx, 120
    jne     art
    cmp     ecx, 200
    jl      art
    push    edx
    movzx   edx, byte ptr [eax+ecx+2]
    movzx   eax, byte ptr [eax+ecx*2+2]
    cmp     edx, 250
    jne     f2
    cmp     eax, 230
    je      isflag
f2:
    cmp     edx, 4
    jne     notflag
    cmp     eax, 240
    jne     notflag
isflag:
    pop     edx
    jmp     out
notflag:
    pop     edx
    mov     eax, dword ptr [esi+0x54]
art:
    mov     dword ptr [{G_ART_SPR + 4:#x}], eax
    mov     dword ptr [{G_ART_SPR + 0xC:#x}], ecx
    mov     eax, dword ptr [esi+0x80]
    mov     dword ptr [{G_ART_SPR + 0x10:#x}], eax
    mov     dword ptr [{G_ART_SPR + 0x14:#x}], edx
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    mov     ecx, {G_ART_SPR:#x}
    call    {ART_REBLIT:#x}
out:
    pop     eax
    pop     esi
    ret     0x18
"""


THUNKS = [("thunk_art_wrap", OFF_ART_WRAP, asm_art_wrap), ("thunk_art_reblit", OFF_ART_REBLIT, asm_art_reblit_stub),
          ("thunk_art_draw", OFF_ART_DRAW, asm_art_draw), ("thunk_art_flic", OFF_ART_FLIC, asm_art_flic),
          ("thunk_art_core", OFF_ART_CORE, asm_art_core), ("thunk_art_bioinit", OFF_ART_BIOINIT, asm_art_bioinit),
          ("thunk_art_reblit_body", OFF_ART_REBLIT_BODY, asm_art_reblit_body),
          ("t_art_frame_rows", OFF_ART_FRAME_ROWS, asm_art_frame_rows)]
SYMS = {SD_REBLIT_WRAP: "thunk_sd_reblit_wrap", ART_REBLIT: "thunk_art_reblit", ART_WRAP: "thunk_art_wrap",
        ART_REBLIT_BODY: "thunk_art_reblit_body", ART_FRAME_ROWS: "t_art_frame_rows",
        G: "g_popup_scale_num", ART_DRAW: "thunk_art_draw", ART_FLIC: "thunk_art_flic", G_ART_SPR: "g_art_spr",
        SD2: "Sprite_draw_2", ART_CORE: "thunk_art_core", FLAG_RESTRIPE: "thunk_flag_restripe", T_DP_FLICDRAW: "t_dp_flicdraw", G_DP_SCR_NEWS: "g_dp_scr_news", G_DP_SCR_BIO: "g_dp_scr_bio",
        T_DP_FLINIT_BIO: "t_dp_flinit_bio", G_BIO_UNDER: "g_dp_bio_under", ART_BIOINIT: "thunk_art_bioinit",
        BUF_COPY_3: "Buffer_copy_3", BUF_RESIZE: "Buffer_resize", BUF_CTOR: "Buffer_ctor", CRT_MALLOC: "crt_malloc"}


def assemble_all() -> dict[str, tuple[int, bytes]]:
    out = {}
    for name, off, fn in THUNKS:
        out[name] = (off, AC.assemble(fn(), PCAVE2 + off))
    ends = [OFF_ART_REBLIT, OFF_ART_DRAW, OFF_ART_DRAW + 0x70, OFF_G_BIO_UNDER, 0x1D000, OFF_ART_FLIC, REBLIT_BODY_END,
            OFF_G_ART_SPR]
    assert OFF_ART_DRAW + 0x70 <= OFF_ART_FRAME_ROWS
    for (name, off, _fn), end in zip(THUNKS, ends):
        assert off + len(out[name][1]) <= end, (name, hex(off + len(out[name][1])), hex(end))
    assert OFF_G_ART_SPR + 0x30 <= SLOT_END
    return out


def main() -> int:
    lay = assemble_all()
    print(f"  {'g_art_spr:':<31}{{ cave: pcave2, offset: {OFF_G_ART_SPR:#x}, size: 48 }}   # popup_art_reblit")
    print(f"  {'g_dp_bio_under:':<31}{{ cave: pcave2, offset: {OFF_G_BIO_UNDER:#x}, size: 4 }}   # popup_art_reblit (BIOSCAN save-under)")
    for name, (off, b) in lay.items():
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # popup_art_reblit ({len(b)}B)")
    for name, (off, b) in lay.items():
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{AC.templatize(b, PCAVE2 + off, SYMS)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
