#!/usr/bin/env python
"""Assembler for the PLANETARY MONUMENT bake (MonumentWin 0x7F9F58; F9 far pyramid view + near plaque view),
2026-09-14.  Ports the user-verified prototype hook_monument_proto.js v7d (measured-correct at 4K, 1600x1200
and 1920x1080: letterbox exact, layout (0,0) against the pristine 2.8125x reference shots, panel stripes P-law,
button faces 3/3 | 2/1 dark-on-top in every state) into pcave2 thunks.  One group:

  mon_scale   full-height 4:3 letterbox (user decision 2026-09-13): num = min(floor(16*ScreenH/768),
              floor(16*ScreenW/1024)) over den 16 = scale_uniform(16) UNCLAMPED (45 @4K; the width term
              keeps the art inside a narrower-than-4:3 screen, fix 11 2026-10-18); every value = vanilla x
              num/16 (scaling_laws.mon_*); armed only in the
              engine's 1024x768 layout with num > 16, else every thunk is the native path.

Levers (proto -> bake shape; laws in scaling_laws.py "PLANETARY MONUMENT"):
  W/T/N  t_mon_build      call_target_redirect @0x476AE6 (monument(): `call load_monicons`, its ONE caller):
                          runs the builder, then (ret 0, armed) GraphicWin_resize(win, SW, SH, 1) + +0x13C/+0x474
                          := screen + GraphicWin_clear(0) (black letterbox), content rect +0xA24, the 30 rects
                          of tables A/B/C (t_mon_rects: letterbox + s(112|84) + s(native - 112|84)), CLOSE/BACK
                          resized to s(200) x s(21) at (LX + s(824), LY + s(747)), label font find_font(fl(14n/16),1)
                          stamped on the button canvas (+0x970), repainted through vtbl+0xF8.
  B      t_mon_bd_far/near  Buffer_copy_4 redirects @0x4760E2 (FLC still) / @0x4737E9 (monzoom): the 1024x768
                          source resampled (Lanczos-3 + Floyd-Steinberg into the CANVAS palette, t_mon_resample)
                          to (LX + s(dx), LY + s(dy)) s(w) x s(h); the near backdrop then gets its blue plaque
                          panel REGENERATED as device-density scanlines (t_mon_panel, palette-independent
                          detection, P=(n+4)>>3, hN=(P+1)>>1, dark rows NN from the native dark row).
         t_mon_pic        Buffer_copy_4 redirects @0x475F37 / @0x47605D: the 600x360 near picture resampled at
                          the table's (dx, dy), s(w) x s(h).
  G      t_mon_spr_nn     Sprite_blit_scaled_core redirects (icons @0x476258, banners @0x476435/@0x476499, glyph
                          @0x476515, emblem @0x476587): thunk_sprite_scale_nn at num/16 (edge-safe NN, the
                          proto's look minus the engine core's +1 garbage column at fractional scales).
         t_mon_spr_pic    the opaque 160x97 pictures (far view @0x47639D, hover re-blits @0x4768F3/@0x476932/
                          @0x47698E): resampled, placed at x + off*num/16 like the engine, s(w) x s(h).
  F      t_mon_font       detour @0x47374D (painter `mov eax,[0x8A40BC]`): eax = find_font(fl(12n/16), 0).
  N(b)   t_mon_gate       wraps thunk_btn_gate_pre at its ONE caller (thunk_btn_shrink's E8): admits the two
                          Monument FlatButtons to the 2dzoom chain (scaled bevel face) when armed.
  N(c)   t_mon_restripe   detour @Buffer_draw_2 0x5D84C0 keyed on src == a Monument button canvas: the face's
                          red/black pair detected per draw from the middle column (>= 6 runs alternating two
                          indices, runs <= P+1) and restriped, DARKER member on top (t_mon_face).
Scratch: one crt_malloc'd block (lazy, g_mon_scratch): palette LUT (15-bit RGB -> index, key 9 excluded) rebuilt
per open (g_mon_lut_ok), tap tables, an 8-row ring of horizontal-pass rows, two error rows, the panel row table.
Parity: tests/test_mon_asm_parity.py (Unicorn vs scaling_laws.mon_*).
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402
import config  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x30000          # pcave2 grown 0x2B000 -> 0x2D000 for this bake, -> 0x30000 for the Hall of Fame (2026-09-14)
OFF_CODE = 0x2B000             # the new block starts right after g_ts_flowcache (0x2A000..0x2B000)
OFF_LIMIT = SECTION_END

# ---- engine VAs ---------------------------------------------------------------
MW = 0x007F9F58                # MonumentWin_g
MW_CANVAS = MW + 0x444
BTN_CLOSE, BTN_BACK = MW + 0xA58, MW + 0x15A4
OFF_TBL = ((0x3134, 17), (0x334C, 6), (0x366C, 7))
LOAD_MONICONS = 0x00472230     # fastcall(this)
GW_RESIZE = 0x005D5540         # thiscall(self, w, h, a4) RET 0xC
GW_CLEAR = 0x005D5250          # thiscall(self, color) RET 4 -- fills the canvas's CURRENT CLIP only
BUFFER_SET_CLIP = 0x005D8000   # thiscall(self, RECT*) RET 4 -- the HOF build resets the clip to the whole window before the clear:
                               # FameWin_draw's no-scores path leaves the clip at the content rect (the v1 letterbox ghost)
FIND_FONT = 0x005882F0         # cdecl(size, style)
# font_face_law helpers (assemble_fontlaw.py, 2026-09-17): keyed cave slots at the screen's OWN num
T_FFN_AT = 0x00A0C000 + 0x2E490          # t_ffn_at(slot, S, v, num) cdecl -> slot (the pool's face law, exact size)
T_FDIRECT_AT = 0x00A0C000 + 0x2E4D0      # t_fdirect_at(slot, S, style, num) cdecl -> slot ("Arial" + own style)
G_FONT_MON_PLAQUE = 0x00A0C000 + 0x2E380 # Monument plaque text slot (Arial 12 regular law)
G_FONT_MON_BTN = 0x00A0C000 + 0x2E3B0    # Monument button label slot (Arial 14 bold law)
G_FONT_HOF_BTN = 0x00A0C000 + 0x2E3E0    # Hall of Fame CLOSE label slot (Arial 14 bold law)
COPY4 = 0x005DFF00             # thiscall(src; dest, sx, sy, dx, dy, w, h) RET 0x1C
BLIT_CORE = 0x005E4B9A         # thiscall(sprite; dest, key, x, y) RET 0x10
BUFFER_DRAW2 = 0x005D84C0
BUFFER_DRAW2_RESUME = 0x005D84C5
FONT_SITE, FONT_RESUME = 0x0047374D, 0x00473752
PLAQUE_FONT = 0x008A40BC
CRT_MALLOC = 0x0064558A        # cdecl(size)
SW, SH = 0x009B7B1C, 0x009B7B20
WIDE = 0x008A4168
SCALE_NN = PCAVE2 + 0x2150     # thunk_sprite_scale_nn (Sprite_draw_2 contract, RET 0x18)
SCALE_UNIFORM = 0x00668200     # scale_uniform (menu_strip_thunks +0x00): eax = dim -> dim * min(W/1024, H/768) floored; keeps ecx/edx/ebx
GATE_PRE = PCAVE2 + 0x24230    # thunk_btn_gate_pre (rw_scale_shared; E8 helper, esi = button)

SCRATCH_SIZE = 0xE0000
SCR_LUT, SCR_COL, SCR_SLOTS, SCR_TAGS, SCR_E0 = 0x0, 0x8000, 0x40000, 0xA0000, 0xA0040
SCR_E1 = SCR_E0 + (SL.MON_MAX_DW + 4) * 3 * 4          # 0xB8070
SCR_ROWS, SCR_HIST = 0xD1000, 0xDD000                   # panel: per-source-row (idx, lo, hi); 256 x dword histogram
SLOT_STRIDE = SL.MON_MAX_DW * 6                          # 0xC000: dw x 3 channels x int16
COL_STRIDE = 28                                          # 6 clamped indices + phase
assert SCR_E1 + (SL.MON_MAX_DW + 4) * 3 * 4 <= SCR_ROWS and SCR_HIST + 0x400 <= SCRATCH_SIZE
MAX_SRC = 4096

# t_mon_lut's search range [lo, hi) (scaling_laws.mon_nearest_lut): placed cells with the default
# [0, 256) baked in, so the Monument / Hall of Fame search is unchanged; the splash narrows it to the
# logo's own entries around its resample (assemble_splash.py t_splash_lut_on / t_splash_lut_off).
OFF_LUT_LO, OFF_LUT_HI = 0xDEE0, 0xDEE4
PLACED_DATA = [("g_mon_lut_lo", OFF_LUT_LO, struct.pack("<i", 0)), ("g_mon_lut_hi", OFF_LUT_HI, struct.pack("<i", 256))]

CELL_DEFS = [("g_mon_num", 4), ("g_mon_armed", 4), ("g_mon_lx", 4), ("g_mon_ly", 4), ("g_mon_ox", 4), ("g_mon_oy", 4),
             ("g_mon_sw", 4), ("g_mon_sh", 4), ("g_mon_scratch", 4), ("g_mon_lut_ok", 4)]


def lz_table() -> bytes:
    """g_mon_lz: 64 phases x 6 int16 Lanczos-3 weights (sum 256), 12 B per phase."""
    return b"".join(struct.pack("<6h", *w) for w in SL.mon_phase_weights())


# ---- asm helpers -----------------------------------------------------------------
def HDM(reg: str) -> str:
    """reg = mon_s(reg) = half_down(reg*num, 16) = (2*reg*num + 15) >> 5."""
    return f"imul {reg}, dword ptr [g_mon_num]\n    lea {reg}, [{reg}*2+15]\n    sar {reg}, 5\n"


def asm_mon_build() -> str:
    return f"""
    call    {LOAD_MONICONS:#x}
    test    eax, eax
    jnz     mb_done
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     dword ptr [g_mon_armed], 0
    mov     dword ptr [g_mon_lut_ok], 0
    mov     eax, dword ptr [{SH:#x}]
    mov     dword ptr [g_mon_sh], eax
    mov     ecx, dword ptr [{SW:#x}]
    mov     dword ptr [g_mon_sw], ecx
    mov     eax, {SL.NATIVE_G}
    call    {SCALE_UNIFORM:#x}      ; num = scale_uniform(16) = min(fl(16H/768), fl(16W/1024)) (SL.mon_scale_num)
    mov     dword ptr [g_mon_num], eax
    cmp     eax, 16
    jle     mb_native
    cmp     dword ptr [{WIDE:#x}], 0
    je      mb_native
    mov     eax, {SL.MON_NATIVE_W}
    {HDM('eax')}
    mov     ecx, dword ptr [g_mon_sw]
    sub     ecx, eax
    sar     ecx, 1
    mov     dword ptr [g_mon_lx], ecx
    mov     eax, {SL.MON_NATIVE_H}
    {HDM('eax')}
    mov     ecx, dword ptr [g_mon_sh]
    sub     ecx, eax
    sar     ecx, 1
    mov     dword ptr [g_mon_ly], ecx
    mov     eax, {SL.MON_ORG_X}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_lx]
    mov     dword ptr [g_mon_ox], eax
    mov     eax, {SL.MON_ORG_Y}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_ly]
    mov     dword ptr [g_mon_oy], eax
    mov     dword ptr [g_mon_armed], 1
    mov     esi, {MW:#x}
    push    1
    push    dword ptr [g_mon_sh]
    push    dword ptr [g_mon_sw]
    mov     ecx, esi
    call    {GW_RESIZE:#x}
    xor     eax, eax
    mov     dword ptr [esi+0x13C], eax
    mov     dword ptr [esi+0x140], eax
    mov     dword ptr [esi+0x474], eax
    mov     dword ptr [esi+0x478], eax
    mov     eax, dword ptr [g_mon_sw]
    mov     dword ptr [esi+0x144], eax
    mov     dword ptr [esi+0x47C], eax
    mov     eax, dword ptr [g_mon_sh]
    mov     dword ptr [esi+0x148], eax
    mov     dword ptr [esi+0x480], eax
    push    0
    mov     ecx, esi
    call    {GW_CLEAR:#x}
    mov     eax, {SL.MON_CONTENT_NATIVE[0]}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_lx]
    mov     dword ptr [esi+0xA24], eax
    mov     eax, {SL.MON_CONTENT_NATIVE[1]}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_ly]
    mov     dword ptr [esi+0xA28], eax
    mov     eax, {SL.MON_CONTENT_NATIVE[2]}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_lx]
    mov     dword ptr [esi+0xA2C], eax
    mov     eax, {SL.MON_CONTENT_NATIVE[3]}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_ly]
    mov     dword ptr [esi+0xA30], eax
""" + "".join(f"""
    lea     edi, [esi+{off:#x}]
    mov     ecx, {n}
    call    t_mon_rects
""" for off, n in OFF_TBL) + f"""
    lea     edi, [esi+{BTN_CLOSE - MW:#x}]
    call    t_mon_btn
    lea     edi, [esi+{BTN_BACK - MW:#x}]
    call    t_mon_btn
mb_native:
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
mb_done:
    ret
"""


def asm_mon_rects() -> str:     # edi = RECT table, ecx = count; window-space rect -> letterbox + s(112|84) + s(v - 112|84)
    def edge(off: int, org: int, cell: str) -> str:
        return f"""
    mov     eax, dword ptr [edi+{off}]
    sub     eax, {org}
    {HDM('eax')}
    add     eax, dword ptr [{cell}]
    mov     dword ptr [edi+{off}], eax
"""
    return f"""
mr_loop:
    push    ecx
{edge(0, SL.MON_ORG_X, 'g_mon_ox')}{edge(4, SL.MON_ORG_Y, 'g_mon_oy')}{edge(8, SL.MON_ORG_X, 'g_mon_ox')}{edge(12, SL.MON_ORG_Y, 'g_mon_oy')}
    pop     ecx
    add     edi, 16
    dec     ecx
    jnz     mr_loop
    ret
"""


def asm_mon_btn() -> str:       # edi = FlatButton: resize to s(200) x s(21), move to (LX + s(824), LY + s(747)), label font, repaint
    x, y, w, h = SL.MON_BTN_NATIVE
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    mov     eax, {w}
    {HDM('eax')}
    mov     dword ptr [ebp-4], eax
    mov     eax, {h}
    {HDM('eax')}
    mov     dword ptr [ebp-8], eax
    mov     eax, {x}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_lx]
    mov     dword ptr [ebp-0xC], eax
    mov     eax, {y}
    {HDM('eax')}
    add     eax, dword ptr [g_mon_ly]
    mov     dword ptr [ebp-0x10], eax
    push    1
    push    dword ptr [ebp-8]
    push    dword ptr [ebp-4]
    mov     ecx, edi
    call    {GW_RESIZE:#x}
    mov     eax, dword ptr [ebp-0xC]
    mov     dword ptr [edi+0x13C], eax
    add     eax, dword ptr [ebp-4]
    mov     dword ptr [edi+0x144], eax
    mov     eax, dword ptr [ebp-0x10]
    mov     dword ptr [edi+0x140], eax
    add     eax, dword ptr [ebp-8]
    mov     dword ptr [edi+0x148], eax
    xor     eax, eax
    mov     dword ptr [edi+0x474], eax
    mov     dword ptr [edi+0x478], eax
    mov     eax, dword ptr [ebp-4]
    mov     dword ptr [edi+0x47C], eax
    mov     eax, dword ptr [ebp-8]
    mov     dword ptr [edi+0x480], eax
    push    dword ptr [g_mon_num]
    push    1
    push    {SL.MON_FONT_LABEL}
    push    {G_FONT_MON_BTN:#x}
    call    {T_FDIRECT_AT:#x}
    add     esp, 16
    mov     dword ptr [edi+0x970], eax
    mov     eax, dword ptr [edi]
    mov     ecx, edi
    call    dword ptr [eax+0xF8]
    mov     esp, ebp
    pop     ebp
    ret
"""


# ---- B: Buffer_copy_4 redirects (thiscall src; dest, sx, sy, dx, dy, w, h; RET 0x1C) -------------------------
def _bd_body(panel: bool, table_xy: bool) -> str:
    """Resample the copy_4 source rect to the scaled dest rect.  table_xy: dest (dx, dy) are the table's device
    coords (near picture); else dest = letterbox + s(dx|dy) (backdrops)."""
    place_x = "" if table_xy else f"    {HDM('eax')}\n    add     eax, dword ptr [g_mon_lx]\n"
    place_y = "" if table_xy else f"    {HDM('eax')}\n    add     eax, dword ptr [g_mon_ly]\n"
    panel_call = ""
    if panel:
        panel_call = """
    push    dword ptr [ebp-8]
    push    dword ptr [ebp-4]
    push    dword ptr [ebp+0x14]
    push    esi
    call    t_mon_panel
"""
    return f"""
    cmp     dword ptr [g_mon_armed], 0
    je      bd_native
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    sub     esp, 8
    mov     esi, ecx
    mov     eax, dword ptr [ebp+0x2C]
    {HDM('eax')}
    push    eax
    mov     eax, dword ptr [ebp+0x28]
    {HDM('eax')}
    push    eax
    mov     eax, dword ptr [ebp+0x24]
{place_y}    mov     dword ptr [ebp-8], eax
    push    eax
    mov     eax, dword ptr [ebp+0x20]
{place_x}    mov     dword ptr [ebp-4], eax
    push    eax
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x2C]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [esi+0x4A8]
    push    dword ptr [esi+0x54]
    call    t_mon_resample
{panel_call}
    mov     esp, ebp
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
    ret     0x1C
bd_native:
    jmp     {COPY4:#x}
"""


def asm_mon_bd_far() -> str:
    return _bd_body(panel=False, table_xy=False)


def asm_mon_bd_near() -> str:
    return _bd_body(panel=True, table_xy=False)


def asm_mon_pic() -> str:
    return _bd_body(panel=False, table_xy=True)


# ---- G: Sprite_blit_scaled_core redirects (thiscall sprite; dest, key, x, y; RET 0x10) -----------------------
def asm_mon_spr_nn() -> str:
    return f"""
    cmp     dword ptr [g_mon_armed], 0
    je      sn_native
    push    16
    push    dword ptr [g_mon_num]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    mov     eax, {SCALE_NN:#x}
    call    eax
    ret     0x10
sn_native:
    jmp     {BLIT_CORE:#x}
"""


def asm_mon_spr_pic() -> str:
    return f"""
    cmp     dword ptr [g_mon_armed], 0
    je      sp_native
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    mov     esi, ecx
    mov     eax, dword ptr [esi+4]
    test    eax, eax
    jz      sp_fail
    mov     eax, dword ptr [esi+0x10]
    test    eax, eax
    jle     sp_fail
    mov     eax, dword ptr [esi+0x14]
    test    eax, eax
    jle     sp_fail
    {HDM('eax')}
    push    eax
    mov     eax, dword ptr [esi+0x10]
    {HDM('eax')}
    push    eax
    mov     eax, dword ptr [esi+0x24]
    imul    eax, dword ptr [g_mon_num]
    cdq
    mov     ecx, 16
    idiv    ecx
    add     eax, dword ptr [ebp+0x20]
    push    eax
    mov     eax, dword ptr [esi+0x20]
    imul    eax, dword ptr [g_mon_num]
    cdq
    idiv    ecx
    add     eax, dword ptr [ebp+0x1C]
    push    eax
    push    dword ptr [ebp+0x14]
    push    dword ptr [esi+0x14]
    push    dword ptr [esi+0x10]
    push    0
    push    0
    mov     eax, dword ptr [esi+0xC]
    test    eax, eax
    jg      sp_pitch
    mov     eax, dword ptr [esi+0x10]
sp_pitch:
    push    eax
    push    dword ptr [esi+4]
    call    t_mon_resample
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    ret     0x10
sp_fail:
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
sp_native:
    jmp     {BLIT_CORE:#x}
"""


# ---- F: plaque font ---------------------------------------------------------------------------------------
def asm_mon_font() -> str:      # detour @0x47374D (5B: mov eax,[0x8A40BC]); resume 0x473752
    # v2 (2026-09-17, audit finding 3.14): the plaque font is vanilla's find_font(12, 0) = Arial 12
    # REGULAR; v1 asked the pool for fl(12*num/16) and got Arial Narrow bold (the pool's >12 face).
    # t_ffn_at keeps the native face/weight on the Monument's own slot at its own num (never fails).
    return f"""
    mov     eax, dword ptr [{PLAQUE_FONT:#x}]
    cmp     dword ptr [g_mon_armed], 0
    je      ff_done
    push    ecx
    push    edx
    push    dword ptr [g_mon_num]
    push    0
    push    {SL.MON_FONT_PLAQUE}
    push    {G_FONT_MON_PLAQUE:#x}
    call    {T_FFN_AT:#x}
    add     esp, 16
    pop     edx
    pop     ecx
ff_done:
    jmp     {FONT_RESUME:#x}
"""


# ---- N(b): gate admission (E8 helper in front of thunk_btn_gate_pre; esi = button; eax = admit) ----------------
def asm_mon_gate() -> str:
    return f"""
    cmp     dword ptr [g_mon_armed], 0
    je      mg_hof
    cmp     esi, {BTN_CLOSE:#x}
    je      mg_hit
    cmp     esi, {BTN_BACK:#x}
    je      mg_hit
mg_hof:
    cmp     dword ptr [g_hof_armed], 0
    je      mg_pass
    cmp     esi, {HOF_CLOSE:#x}
    je      mg_hit
mg_pass:
    jmp     {GATE_PRE:#x}
mg_hit:
    mov     eax, 1
    ret
"""


# ---- N(c): face restripe at composite time ---------------------------------------------------------------------
def asm_mon_restripe() -> str:  # detour @Buffer_draw_2 0x5D84C0 (5B: sub esp,0x18 / push ebx / push ebp); resume 0x5D84C5
    return f"""
    cmp     dword ptr [g_mon_armed], 0
    je      rs_hof
    cmp     ecx, {BTN_CLOSE + 0x444:#x}
    je      rs_hit
    cmp     ecx, {BTN_BACK + 0x444:#x}
    je      rs_hit
rs_hof:
    cmp     dword ptr [g_hof_armed], 0
    je      rs_pass
    cmp     ecx, {HOF_CLOSE + 0x444:#x}
    jne     rs_pass
    pushad
    push    dword ptr [g_hof_num]
    push    ecx
    call    t_mon_face
    popad
    jmp     rs_pass
rs_hit:
    pushad
    push    dword ptr [g_mon_num]
    push    ecx
    call    t_mon_face
    popad
rs_pass:
    sub     esp, 0x18
    push    ebx
    push    ebp
    jmp     {BUFFER_DRAW2_RESUME:#x}
"""


def asm_mon_face() -> str:      # (buf, num) RET 8: scaling_laws.mon_face_restripe (num = the calling screen's)
    # frame: -4 P, -8 hN, -0xC w, -0x10 h, -0x14 pitch, -0x18 data, -0x1C nruns, -0x20 bestLen, -0x24 a, -0x28 b,
    #        -0x2C top, -0x30 bot, -0x34 pal, -0x38 i, -0x3C j, -0x40 pa, -0x44 pb, -0x850.. runs[256] (val, len)
    return """
    push    ebp
    mov     ebp, esp
    sub     esp, 0x850
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [ebp+0xC]
    cmp     eax, 16                 ; native: untouched
    jle     fc_done
    cmp     eax, 22                 ; T = stripe_rows(num): 1 below 22, else max(2, num >> 4); P = 2T
    sbb     edx, edx
    shr     eax, 4
    cmp     eax, 2
    adc     eax, edx
    mov     dword ptr [ebp-8], eax
    add     eax, eax
    mov     dword ptr [ebp-4], eax
    mov     ebx, dword ptr [ebp+8]
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    jz      fc_done
    mov     dword ptr [ebp-0x18], eax
    mov     eax, dword ptr [ebx+0x80]
    test    eax, eax
    jle     fc_done
    mov     dword ptr [ebp-0xC], eax
    mov     eax, dword ptr [ebx+0x84]
    neg     eax
    test    eax, eax
    jle     fc_done
    cmp     eax, 256
    jg      fc_done
    mov     dword ptr [ebp-0x10], eax
    mov     eax, dword ptr [ebx+0x4A8]
    test    eax, eax
    jle     fc_done
    mov     dword ptr [ebp-0x14], eax
    lea     eax, [ebx+0xA4]
    mov     dword ptr [ebp-0x34], eax
    ; ---- runs of the middle column ----
    mov     esi, dword ptr [ebp-0x18]
    mov     eax, dword ptr [ebp-0xC]
    shr     eax, 1
    add     esi, eax
    lea     edi, [ebp-0x850]
    movzx   eax, byte ptr [esi]
    mov     dword ptr [edi], eax
    mov     dword ptr [edi+4], 1
    mov     ecx, 1
fc_col:
    cmp     ecx, dword ptr [ebp-0x10]
    jge     fc_colend
    add     esi, dword ptr [ebp-0x14]
    movzx   eax, byte ptr [esi]
    cmp     eax, dword ptr [edi]
    jne     fc_newrun
    inc     dword ptr [edi+4]
    jmp     fc_colnext
fc_newrun:
    add     edi, 8
    mov     dword ptr [edi], eax
    mov     dword ptr [edi+4], 1
fc_colnext:
    inc     ecx
    jmp     fc_col
fc_colend:
    lea     eax, [ebp-0x850]
    sub     edi, eax
    shr     edi, 3
    inc     edi
    mov     dword ptr [ebp-0x1C], edi
    ; ---- best alternating chain ----
    mov     dword ptr [ebp-0x20], 0
    mov     dword ptr [ebp-0x24], -1
    mov     dword ptr [ebp-0x38], 0
fc_i:
    mov     eax, dword ptr [ebp-0x38]
    cmp     eax, dword ptr [ebp-0x1C]
    jge     fc_chosen
    lea     esi, [ebp-0x850]
    mov     ebx, dword ptr [esi+eax*8]
    mov     dword ptr [ebp-0x40], ebx
    mov     dword ptr [ebp-0x44], -1
    mov     dword ptr [ebp-0x3C], eax
fc_j:
    mov     eax, dword ptr [ebp-0x3C]
    cmp     eax, dword ptr [ebp-0x1C]
    jge     fc_jend
    mov     ecx, dword ptr [esi+eax*8+4]
    mov     edx, dword ptr [ebp-4]
    inc     edx
    cmp     ecx, edx
    jg      fc_jend
    mov     ecx, dword ptr [esi+eax*8]
    cmp     ecx, dword ptr [ebp-0x40]
    je      fc_jnext
    cmp     dword ptr [ebp-0x44], 0
    jl      fc_setpb
    cmp     ecx, dword ptr [ebp-0x44]
    jne     fc_jend
    jmp     fc_jnext
fc_setpb:
    mov     dword ptr [ebp-0x44], ecx
fc_jnext:
    inc     dword ptr [ebp-0x3C]
    jmp     fc_j
fc_jend:
    cmp     dword ptr [ebp-0x44], 0
    jl      fc_inext
    mov     eax, dword ptr [ebp-0x3C]
    sub     eax, dword ptr [ebp-0x38]
    cmp     eax, 6
    jl      fc_inext
    cmp     eax, dword ptr [ebp-0x20]
    jle     fc_inext
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [ebp-0x40]
    mov     dword ptr [ebp-0x24], eax
    mov     eax, dword ptr [ebp-0x44]
    mov     dword ptr [ebp-0x28], eax
fc_inext:
    inc     dword ptr [ebp-0x38]
    jmp     fc_i
fc_chosen:
    cmp     dword ptr [ebp-0x24], 0
    jl      fc_done
    ; ---- top (wide) = BRIGHTER member (luma b*114 + g*587 + r*299 over the canvas table; v2 2026-09-15, was darker) ----
    mov     esi, dword ptr [ebp-0x34]
    mov     eax, dword ptr [ebp-0x24]
    call    fc_luma
    mov     ebx, eax
    mov     eax, dword ptr [ebp-0x28]
    call    fc_luma
    mov     ecx, dword ptr [ebp-0x24]
    mov     edx, dword ptr [ebp-0x28]
    cmp     ebx, eax
    jge     fc_topa
    xchg    ecx, edx
fc_topa:
    mov     dword ptr [ebp-0x2C], ecx
    mov     dword ptr [ebp-0x30], edx
    ; ---- rewrite every pair pixel: row y -> (y mod P) < hN ? top : bot ----
    mov     esi, dword ptr [ebp-0x18]
    mov     edi, dword ptr [ebp-0x10]
    xor     edx, edx
fc_row:
    mov     eax, dword ptr [ebp-0x2C]
    cmp     edx, dword ptr [ebp-8]
    jl      fc_havec
    mov     eax, dword ptr [ebp-0x30]
fc_havec:
    push    edx
    push    esi
    push    edi
    mov     ecx, dword ptr [ebp-0xC]
    mov     ebx, dword ptr [ebp-0x24]
    mov     edx, dword ptr [ebp-0x28]
fc_px:
    movzx   edi, byte ptr [esi]
    cmp     edi, ebx
    je      fc_store
    cmp     edi, edx
    jne     fc_pxnext
fc_store:
    mov     byte ptr [esi], al
fc_pxnext:
    inc     esi
    dec     ecx
    jnz     fc_px
    pop     edi
    pop     esi
    pop     edx
    add     esi, dword ptr [ebp-0x14]
    inc     edx
    cmp     edx, dword ptr [ebp-4]
    jl      fc_nowrap
    xor     edx, edx
fc_nowrap:
    dec     edi
    jnz     fc_row
fc_done:
    pop     edi
    pop     esi
    pop     ebx
    leave
    ret     8
fc_luma:
    lea     eax, [esi+eax*4]
    movzx   ecx, byte ptr [eax]
    imul    ecx, ecx, 114
    movzx   edx, byte ptr [eax+1]
    imul    edx, edx, 587
    add     ecx, edx
    movzx   edx, byte ptr [eax+2]
    imul    edx, edx, 299
    lea     eax, [ecx+edx]
    ret
"""


# ---- palette LUT ---------------------------------------------------------------------------------------------
def asm_mon_lut() -> str:       # (pal, lut) RET 8: scaling_laws.mon_nearest_lut(pal, [g_mon_lut_lo], [g_mon_lut_hi])
    # best distance starts at 0xFFFFFFFF with an UNSIGNED compare (d <= 3*255^2): the law's strict <
    # from 1<<30, 3 B shorter -- the range loads must fit the 176-B slot before the frozen t_mon_resample.
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    push    ebx
    push    esi
    push    edi
    xor     esi, esi
lu_i:
    mov     eax, esi
    shr     eax, 10
    and     eax, 31
    mov     edx, eax
    shl     eax, 3
    shr     edx, 2
    or      eax, edx
    mov     dword ptr [ebp-4], eax
    mov     eax, esi
    shr     eax, 5
    and     eax, 31
    mov     edx, eax
    shl     eax, 3
    shr     edx, 2
    or      eax, edx
    mov     dword ptr [ebp-8], eax
    mov     eax, esi
    and     eax, 31
    mov     edx, eax
    shl     eax, 3
    shr     edx, 2
    or      eax, edx
    mov     dword ptr [ebp-0xC], eax
    mov     ebx, dword ptr [g_mon_lut_lo]
    or      dword ptr [ebp-0x10], -1
    mov     edi, dword ptr [ebp+8]
    lea     edi, [edi+ebx*4]
    mov     ecx, ebx
lu_k:
    cmp     ecx, {SL.MON_KEY}
    je      lu_knext
    movzx   eax, byte ptr [edi]
    sub     eax, dword ptr [ebp-0xC]
    imul    eax, eax
    movzx   edx, byte ptr [edi+1]
    sub     edx, dword ptr [ebp-8]
    imul    edx, edx
    add     eax, edx
    movzx   edx, byte ptr [edi+2]
    sub     edx, dword ptr [ebp-4]
    imul    edx, edx
    add     eax, edx
    cmp     eax, dword ptr [ebp-0x10]
    jae     lu_knext
    mov     dword ptr [ebp-0x10], eax
    mov     ebx, ecx
lu_knext:
    add     edi, 4
    inc     ecx
    cmp     ecx, dword ptr [g_mon_lut_hi]
    jl      lu_k
    mov     eax, dword ptr [ebp+0xC]
    mov     byte ptr [eax+esi], bl
    inc     esi
    cmp     esi, 32768
    jl      lu_i
    pop     edi
    pop     esi
    pop     ebx
    leave
    ret     8
"""


# ---- the resampler ----------------------------------------------------------------------------------------------
# (sdata, spitch, sx, sy, sw, sh, dest, dx, dy, dw, dh) RET 0x2C; preserves ebx/esi/edi/ebp.  scaling_laws.mon_resample.
def _axis(n_src: str, n_dst: str, i: str) -> str:
    """eax = c64 = ((2*i+1)*32*n_src + 32*n_dst) / n_dst - 64  (unsigned); edx clobbered."""
    return f"""
    mov     eax, {i}
    lea     eax, [eax*2+1]
    shl     eax, 5
    mul     dword ptr [{n_src}]
    mov     edx, dword ptr [{n_dst}]
    shl     edx, 5
    add     eax, edx
    xor     edx, edx
    div     dword ptr [{n_dst}]
    sub     eax, 64
"""


def asm_mon_resample() -> str:
    # args: +8 sdata, +0xC spitch, +0x10 sx, +0x14 sy, +0x18 sw, +0x1C sh, +0x20 dest, +0x24 dx, +0x28 dy, +0x2C dw, +0x30 dh
    # locals: -4 ddata, -8 dpitch, -0xC dW, -0x10 dH, -0x14 pal, -0x18 lut, -0x1C coltab, -0x20 slots, -0x24 tags,
    #         -0x28 e0, -0x2C e1, -0x30 x0, -0x34 x1, -0x38 y0, -0x3C y1, -0x40 j, -0x44 i, -0x48 pw (row weights),
    #         -0x4C..-0x60 rowslot[6], -0x64 ew3, -0x68 y, -0x6C tmp, -0x70 vb, -0x74 vg, -0x78 vr, -0x7C idx, -0x80 t,
    #         -0x84 accr, -0x88 accg, -0x8C accb, -0x90 rowptr (hpass), -0x94 slotptr (hpass), -0x98 ct (hpass col entry),
    #         -0x9C slot (row taps), -0xA0 i (hpass)
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0xA0
    push    ebx
    push    esi
    push    edi
    ; ---- guards ----
    mov     eax, dword ptr [ebp+0x18]
    test    eax, eax
    jle     rs_done
    cmp     eax, {MAX_SRC}
    jg      rs_done
    mov     eax, dword ptr [ebp+0x1C]
    test    eax, eax
    jle     rs_done
    cmp     eax, {MAX_SRC}
    jg      rs_done
    mov     eax, dword ptr [ebp+0x2C]
    test    eax, eax
    jle     rs_done
    cmp     eax, {SL.MON_MAX_DW}
    jg      rs_done
    mov     eax, dword ptr [ebp+0x30]
    test    eax, eax
    jle     rs_done
    cmp     dword ptr [ebp+8], 0
    je      rs_done
    cmp     dword ptr [ebp+0xC], 0
    jle     rs_done
    mov     ebx, dword ptr [ebp+0x20]
    test    ebx, ebx
    jz      rs_done
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    jz      rs_done
    mov     dword ptr [ebp-4], eax
    mov     eax, dword ptr [ebx+0x4A8]
    test    eax, eax
    jle     rs_done
    mov     dword ptr [ebp-8], eax
    mov     eax, dword ptr [ebx+0x80]
    mov     dword ptr [ebp-0xC], eax
    mov     eax, dword ptr [ebx+0x84]
    neg     eax
    mov     dword ptr [ebp-0x10], eax
    lea     eax, [ebx+0xA4]
    mov     dword ptr [ebp-0x14], eax
    ; ---- scratch (lazy) ----
    mov     eax, dword ptr [g_mon_scratch]
    test    eax, eax
    jnz     rs_havescr
    push    {SCRATCH_SIZE:#x}
    call    {CRT_MALLOC:#x}
    add     esp, 4
    test    eax, eax
    jz      rs_done
    mov     dword ptr [g_mon_scratch], eax
rs_havescr:
    lea     edx, [eax+{SCR_LUT:#x}]
    mov     dword ptr [ebp-0x18], edx
    lea     edx, [eax+{SCR_COL:#x}]
    mov     dword ptr [ebp-0x1C], edx
    lea     edx, [eax+{SCR_SLOTS:#x}]
    mov     dword ptr [ebp-0x20], edx
    lea     edx, [eax+{SCR_TAGS:#x}]
    mov     dword ptr [ebp-0x24], edx
    lea     edx, [eax+{SCR_E0:#x}]
    mov     dword ptr [ebp-0x28], edx
    lea     edx, [eax+{SCR_E1:#x}]
    mov     dword ptr [ebp-0x2C], edx
    ; ---- palette LUT once per open ----
    cmp     dword ptr [g_mon_lut_ok], 0
    jne     rs_havelut
    push    dword ptr [ebp-0x18]
    push    dword ptr [ebp-0x14]
    call    t_mon_lut
    mov     dword ptr [g_mon_lut_ok], 1
rs_havelut:
    ; ---- clip window ----
    mov     eax, dword ptr [ebp+0x24]
    test    eax, eax
    jge     rs_x0
    xor     eax, eax
rs_x0:
    mov     dword ptr [ebp-0x30], eax
    mov     eax, dword ptr [ebp+0x24]
    add     eax, dword ptr [ebp+0x2C]
    cmp     eax, dword ptr [ebp-0xC]
    jle     rs_x1
    mov     eax, dword ptr [ebp-0xC]
rs_x1:
    mov     dword ptr [ebp-0x34], eax
    mov     eax, dword ptr [ebp+0x28]
    test    eax, eax
    jge     rs_y0
    xor     eax, eax
rs_y0:
    mov     dword ptr [ebp-0x38], eax
    mov     eax, dword ptr [ebp+0x28]
    add     eax, dword ptr [ebp+0x30]
    cmp     eax, dword ptr [ebp-0x10]
    jle     rs_y1
    mov     eax, dword ptr [ebp-0x10]
rs_y1:
    mov     dword ptr [ebp-0x3C], eax
    ; ---- ring tags := -1 ----
    mov     edi, dword ptr [ebp-0x24]
    mov     eax, -1
    mov     ecx, 8
    rep stosd
    ; ---- column taps ----
    mov     dword ptr [ebp-0x44], 0
    mov     edi, dword ptr [ebp-0x1C]
rs_col:
    mov     eax, dword ptr [ebp-0x44]
    cmp     eax, dword ptr [ebp+0x2C]
    jge     rs_colend
{_axis('ebp+0x18', 'ebp+0x2C', 'dword ptr [ebp-0x44]')}
    mov     ecx, eax
    and     ecx, 63
    mov     dword ptr [edi+24], ecx
    sar     eax, 6
    sub     eax, 2
    xor     ecx, ecx
rs_colt:
    lea     edx, [eax+ecx]
    test    edx, edx
    jge     rs_colt0
    xor     edx, edx
rs_colt0:
    mov     ebx, dword ptr [ebp+0x18]
    dec     ebx
    cmp     edx, ebx
    jle     rs_colt1
    mov     edx, ebx
rs_colt1:
    mov     dword ptr [edi+ecx*4], edx
    inc     ecx
    cmp     ecx, 6
    jl      rs_colt
    add     edi, {COL_STRIDE}
    inc     dword ptr [ebp-0x44]
    jmp     rs_col
rs_colend:
    ; ---- error rows := 0 ----
    mov     eax, dword ptr [ebp+0x2C]
    add     eax, 2
    lea     eax, [eax+eax*2]
    mov     dword ptr [ebp-0x64], eax
    mov     edi, dword ptr [ebp-0x28]
    mov     ecx, eax
    xor     eax, eax
    rep stosd
    mov     edi, dword ptr [ebp-0x2C]
    mov     ecx, dword ptr [ebp-0x64]
    rep stosd
    ; ==== rows ====
    mov     dword ptr [ebp-0x40], 0
rs_row:
    mov     eax, dword ptr [ebp-0x40]
    cmp     eax, dword ptr [ebp+0x30]
    jge     rs_done
    add     eax, dword ptr [ebp+0x28]
    mov     dword ptr [ebp-0x68], eax
{_axis('ebp+0x1C', 'ebp+0x30', 'dword ptr [ebp-0x40]')}
    mov     ecx, eax
    and     ecx, 63
    lea     ecx, [ecx+ecx*2]
    lea     ecx, [g_mon_lz+ecx*4]
    mov     dword ptr [ebp-0x48], ecx
    sar     eax, 6
    sub     eax, 2
    mov     dword ptr [ebp-0x6C], eax
    mov     dword ptr [ebp-0x80], 0
rs_rowt:
    mov     eax, dword ptr [ebp-0x6C]
    add     eax, dword ptr [ebp-0x80]
    test    eax, eax
    jge     rs_rowt0
    xor     eax, eax
rs_rowt0:
    mov     ecx, dword ptr [ebp+0x1C]
    dec     ecx
    cmp     eax, ecx
    jle     rs_rowt1
    mov     eax, ecx
rs_rowt1:
    mov     ecx, eax
    and     ecx, 7
    mov     dword ptr [ebp-0x9C], ecx
    mov     edx, dword ptr [ebp-0x24]
    cmp     dword ptr [edx+ecx*4], eax
    je      rs_rowt2
    mov     dword ptr [edx+ecx*4], eax
    mov     edx, ecx
    shl     edx, 14
    lea     edx, [edx+edx*2]
    add     edx, dword ptr [ebp-0x20]
    call    rs_hpass
rs_rowt2:
    mov     edx, dword ptr [ebp-0x9C]
    shl     edx, 14
    lea     edx, [edx+edx*2]
    add     edx, dword ptr [ebp-0x20]
    mov     ecx, dword ptr [ebp-0x80]
    mov     dword ptr [ebp+ecx*4-0x60], edx
    inc     dword ptr [ebp-0x80]
    cmp     dword ptr [ebp-0x80], 6
    jl      rs_rowt
    ; e1 := 0
    mov     edi, dword ptr [ebp-0x2C]
    mov     ecx, dword ptr [ebp-0x64]
    xor     eax, eax
    rep stosd
    ; ---- pixels ----
    mov     dword ptr [ebp-0x44], 0
rs_px:
    mov     eax, dword ptr [ebp-0x44]
    cmp     eax, dword ptr [ebp+0x2C]
    jge     rs_pxend
    lea     esi, [eax+eax*2]
    add     esi, esi
    xor     ebx, ebx
    mov     dword ptr [ebp-0x88], ebx
    mov     dword ptr [ebp-0x84], ebx
    mov     dword ptr [ebp-0x80], 0
rs_vt:
    mov     ecx, dword ptr [ebp-0x80]
    mov     edx, dword ptr [ebp+ecx*4-0x60]
    add     edx, esi
    mov     eax, dword ptr [ebp-0x48]
    movsx   edi, word ptr [eax+ecx*2]
    movsx   eax, word ptr [edx]
    imul    eax, edi
    add     ebx, eax
    movsx   eax, word ptr [edx+2]
    imul    eax, edi
    add     dword ptr [ebp-0x88], eax
    movsx   eax, word ptr [edx+4]
    imul    eax, edi
    add     dword ptr [ebp-0x84], eax
    inc     ecx
    mov     dword ptr [ebp-0x80], ecx
    cmp     ecx, 6
    jl      rs_vt
    mov     dword ptr [ebp-0x8C], ebx
    ; v_c = (acc_c >> 12) + (e0[(i+1)*3+c] >> 4), clamped
    mov     edi, dword ptr [ebp-0x44]
    inc     edi
    lea     edi, [edi+edi*2]
    shl     edi, 2
    add     edi, dword ptr [ebp-0x28]
    mov     ecx, 0
rs_vc:
    mov     eax, dword ptr [ebp+ecx*4-0x8C]
    sar     eax, 12
    mov     edx, dword ptr [edi+ecx*4]
    sar     edx, 4
    add     eax, edx
    test    eax, eax
    jge     rs_vc0
    xor     eax, eax
rs_vc0:
    cmp     eax, 255
    jle     rs_vc1
    mov     eax, 255
rs_vc1:
    mov     dword ptr [ebp+ecx*4-0x78], eax
    inc     ecx
    cmp     ecx, 3
    jl      rs_vc
    ; idx = lut[(r>>3)<<10 | (g>>3)<<5 | (b>>3)]   (v: -0x78 b, -0x74 g, -0x70 r)
    mov     eax, dword ptr [ebp-0x70]
    shr     eax, 3
    shl     eax, 10
    mov     edx, dword ptr [ebp-0x74]
    shr     edx, 3
    shl     edx, 5
    or      eax, edx
    mov     edx, dword ptr [ebp-0x78]
    shr     edx, 3
    or      eax, edx
    mov     edx, dword ptr [ebp-0x18]
    movzx   eax, byte ptr [edx+eax]
    mov     dword ptr [ebp-0x7C], eax
    ; write if inside the dest
    mov     ecx, dword ptr [ebp-0x68]
    cmp     ecx, dword ptr [ebp-0x38]
    jl      rs_nowrite
    cmp     ecx, dword ptr [ebp-0x3C]
    jge     rs_nowrite
    mov     edx, dword ptr [ebp-0x44]
    add     edx, dword ptr [ebp+0x24]
    cmp     edx, dword ptr [ebp-0x30]
    jl      rs_nowrite
    cmp     edx, dword ptr [ebp-0x34]
    jge     rs_nowrite
    imul    ecx, dword ptr [ebp-8]
    add     ecx, edx
    add     ecx, dword ptr [ebp-4]
    mov     byte ptr [ecx], al
rs_nowrite:
    ; error diffusion: d_c = v_c - pal[idx].c ; e0[i+2] += 7d ; e1[i] += 3d ; e1[i+1] += 5d ; e1[i+2] += d
    mov     esi, dword ptr [ebp-0x7C]
    shl     esi, 2
    add     esi, dword ptr [ebp-0x14]
    mov     edx, dword ptr [ebp-0x44]
    lea     edx, [edx+edx*2]
    shl     edx, 2
    add     edx, dword ptr [ebp-0x2C]
    xor     ecx, ecx
rs_err:
    mov     eax, dword ptr [ebp+ecx*4-0x78]
    movzx   ebx, byte ptr [esi+ecx]
    sub     eax, ebx
    lea     ebx, [eax+eax*2]
    add     dword ptr [edx+ecx*4], ebx
    lea     ebx, [eax+eax*4]
    add     dword ptr [edx+ecx*4+12], ebx
    add     dword ptr [edx+ecx*4+24], eax
    lea     ebx, [eax*8]
    sub     ebx, eax
    add     dword ptr [edi+ecx*4+12], ebx
    inc     ecx
    cmp     ecx, 3
    jl      rs_err
    inc     dword ptr [ebp-0x44]
    jmp     rs_px
rs_pxend:
    mov     eax, dword ptr [ebp-0x28]
    xchg    eax, dword ptr [ebp-0x2C]
    mov     dword ptr [ebp-0x28], eax
    inc     dword ptr [ebp-0x40]
    jmp     rs_row
rs_done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x2C
; ---- horizontal pass of source row eax into the ring slot edx (uses the frame's locals; clobbers eax..edi) ----
rs_hpass:
    mov     dword ptr [ebp-0x94], edx
    add     eax, dword ptr [ebp+0x14]
    imul    eax, dword ptr [ebp+0xC]
    add     eax, dword ptr [ebp+0x10]
    add     eax, dword ptr [ebp+8]
    mov     dword ptr [ebp-0x90], eax
    mov     eax, dword ptr [ebp-0x1C]
    mov     dword ptr [ebp-0x98], eax
    mov     dword ptr [ebp-0xA0], 0
hp_i:
    mov     eax, dword ptr [ebp-0xA0]
    cmp     eax, dword ptr [ebp+0x2C]
    jge     hp_end
    mov     esi, dword ptr [ebp-0x98]
    mov     eax, dword ptr [esi+24]
    lea     eax, [eax+eax*2]
    lea     edi, [g_mon_lz+eax*4]
    xor     ebx, ebx
    mov     dword ptr [ebp-0x88], ebx
    mov     dword ptr [ebp-0x84], ebx
    xor     ecx, ecx
hp_t:
    mov     eax, dword ptr [esi+ecx*4]
    add     eax, dword ptr [ebp-0x90]
    movzx   eax, byte ptr [eax]
    shl     eax, 2
    add     eax, dword ptr [ebp-0x14]
    movsx   edx, word ptr [edi+ecx*2]
    push    ecx
    movzx   ecx, byte ptr [eax]
    imul    ecx, edx
    add     ebx, ecx
    movzx   ecx, byte ptr [eax+1]
    imul    ecx, edx
    add     dword ptr [ebp-0x88], ecx
    movzx   ecx, byte ptr [eax+2]
    imul    ecx, edx
    add     dword ptr [ebp-0x84], ecx
    pop     ecx
    inc     ecx
    cmp     ecx, 6
    jl      hp_t
    mov     eax, dword ptr [ebp-0xA0]
    lea     eax, [eax+eax*2]
    add     eax, eax
    add     eax, dword ptr [ebp-0x94]
    sar     ebx, 4
    mov     word ptr [eax], bx
    mov     ecx, dword ptr [ebp-0x88]
    sar     ecx, 4
    mov     word ptr [eax+2], cx
    mov     ecx, dword ptr [ebp-0x84]
    sar     ecx, 4
    mov     word ptr [eax+4], cx
    add     dword ptr [ebp-0x98], {COL_STRIDE}
    inc     dword ptr [ebp-0xA0]
    jmp     hp_i
hp_end:
    ret
"""


# ---- the blue plaque panel -----------------------------------------------------------------------------------
def asm_mon_panel() -> str:     # (src Buffer, dest Buffer, dx, dy) RET 0x10: scaling_laws.mon_panel_synth
    # locals: -4 sdata, -8 spitch, -0xC sw, -0x10 sh, -0x14 ddata, -0x18 dpitch, -0x1C dW, -0x20 dH, -0x24 rows, -0x28 hist,
    #         -0x2C y/i, -0x30 bestN, -0x34 bestI, -0x38 light, -0x3C n, -0x40 j, -0x44 ny1, -0x48 P, -0x4C hN, -0x50 Y0,
    #         -0x54 Y1, -0x58 / -0x5C (unused; ebx = (y - Y0) // T in the row loop), -0x60 ly, -0x64 X0, -0x68 X1, -0x6C w, -0x70 xs, -0x74 xe, -0x78 nd, -0x7C span, -0x80 srow, -0x84 lo
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x90
    push    ebx
    push    esi
    push    edi
    mov     ebx, dword ptr [ebp+8]
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    jz      pn_done
    mov     dword ptr [ebp-4], eax
    mov     eax, dword ptr [ebx+0x4A8]
    test    eax, eax
    jle     pn_done
    mov     dword ptr [ebp-8], eax
    mov     eax, dword ptr [ebx+0x80]
    test    eax, eax
    jle     pn_done
    cmp     eax, {MAX_SRC}
    jg      pn_done
    mov     dword ptr [ebp-0xC], eax
    mov     eax, dword ptr [ebx+0x84]
    neg     eax
    jle     pn_done
    cmp     eax, {MAX_SRC}
    jg      pn_done
    mov     dword ptr [ebp-0x10], eax
    mov     ebx, dword ptr [ebp+0xC]
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    jz      pn_done
    mov     dword ptr [ebp-0x14], eax
    mov     eax, dword ptr [ebx+0x4A8]
    test    eax, eax
    jle     pn_done
    mov     dword ptr [ebp-0x18], eax
    mov     eax, dword ptr [ebx+0x80]
    mov     dword ptr [ebp-0x1C], eax
    mov     eax, dword ptr [ebx+0x84]
    neg     eax
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [g_mon_scratch]
    test    eax, eax
    jz      pn_done
    lea     edx, [eax+{SCR_ROWS:#x}]
    mov     dword ptr [ebp-0x24], edx
    lea     edx, [eax+{SCR_HIST:#x}]
    mov     dword ptr [ebp-0x28], edx
    ; ---- per source row: dominant index (first strict max), its extent; -1 when < 300 px ----
    mov     dword ptr [ebp-0x2C], 0
pn_y:
    mov     eax, dword ptr [ebp-0x2C]
    cmp     eax, dword ptr [ebp-0x10]
    jge     pn_yend
    mov     edi, dword ptr [ebp-0x28]
    xor     eax, eax
    mov     ecx, 256
    rep stosd
    mov     esi, dword ptr [ebp-0x2C]
    imul    esi, dword ptr [ebp-8]
    add     esi, dword ptr [ebp-4]
    mov     edi, dword ptr [ebp-0x28]
    mov     ecx, dword ptr [ebp-0xC]
pn_cnt:
    movzx   eax, byte ptr [esi]
    inc     dword ptr [edi+eax*4]
    inc     esi
    dec     ecx
    jnz     pn_cnt
    xor     ebx, ebx
    mov     ecx, 1
pn_max:
    mov     eax, dword ptr [edi+ecx*4]
    cmp     eax, dword ptr [edi+ebx*4]
    jle     pn_maxnext
    mov     ebx, ecx
pn_maxnext:
    inc     ecx
    cmp     ecx, 256
    jl      pn_max
    mov     edx, dword ptr [ebp-0x2C]
    lea     edx, [edx+edx*2]
    shl     edx, 2
    add     edx, dword ptr [ebp-0x24]
    mov     dword ptr [edx], -1
    cmp     dword ptr [edi+ebx*4], {SL.MON_PANEL_MIN}
    jl      pn_ynext
    mov     dword ptr [edx], ebx
    mov     esi, dword ptr [ebp-0x2C]
    imul    esi, dword ptr [ebp-8]
    add     esi, dword ptr [ebp-4]
    mov     ecx, dword ptr [ebp-0xC]
    mov     dword ptr [edx+4], ecx
    mov     dword ptr [edx+8], -1
    xor     eax, eax
pn_ext:
    cmp     byte ptr [esi+eax], bl
    jne     pn_extnext
    cmp     eax, dword ptr [edx+4]
    jge     pn_exthi
    mov     dword ptr [edx+4], eax
pn_exthi:
    mov     dword ptr [edx+8], eax
pn_extnext:
    inc     eax
    cmp     eax, ecx
    jl      pn_ext
pn_ynext:
    inc     dword ptr [ebp-0x2C]
    jmp     pn_y
pn_yend:
    ; ---- longest chain of light rows spaced 2, same index, < 100 px of it in between ----
    mov     dword ptr [ebp-0x30], 0
    mov     dword ptr [ebp-0x34], -1
    mov     dword ptr [ebp-0x2C], 0
pn_i:
    mov     eax, dword ptr [ebp-0x2C]
    cmp     eax, dword ptr [ebp-0x10]
    jge     pn_iend
    lea     edx, [eax+eax*2]
    shl     edx, 2
    add     edx, dword ptr [ebp-0x24]
    mov     ebx, dword ptr [edx]
    test    ebx, ebx
    jl      pn_inext
    mov     dword ptr [ebp-0x3C], 1
    mov     dword ptr [ebp-0x40], eax
pn_j:
    mov     eax, dword ptr [ebp-0x40]
    add     eax, 2
    cmp     eax, dword ptr [ebp-0x10]
    jge     pn_jend
    lea     edx, [eax+eax*2]
    shl     edx, 2
    add     edx, dword ptr [ebp-0x24]
    cmp     dword ptr [edx], ebx
    jne     pn_jend
    mov     esi, dword ptr [ebp-0x40]
    inc     esi
    imul    esi, dword ptr [ebp-8]
    add     esi, dword ptr [ebp-4]
    mov     ecx, dword ptr [ebp-0xC]
    xor     edi, edi
pn_gap:
    cmp     byte ptr [esi], bl
    jne     pn_gapnext
    inc     edi
pn_gapnext:
    inc     esi
    dec     ecx
    jnz     pn_gap
    cmp     edi, {SL.MON_PANEL_GAP}
    jge     pn_jend
    inc     dword ptr [ebp-0x3C]
    add     dword ptr [ebp-0x40], 2
    jmp     pn_j
pn_jend:
    mov     eax, dword ptr [ebp-0x3C]
    cmp     eax, dword ptr [ebp-0x30]
    jle     pn_inext
    mov     dword ptr [ebp-0x30], eax
    mov     eax, dword ptr [ebp-0x2C]
    mov     dword ptr [ebp-0x34], eax
    mov     dword ptr [ebp-0x38], ebx
pn_inext:
    inc     dword ptr [ebp-0x2C]
    jmp     pn_i
pn_iend:
    cmp     dword ptr [ebp-0x30], {SL.MON_PANEL_MIN_ROWS}
    jl      pn_done
    ; ---- device rows Y0..Y1 ----
    mov     eax, dword ptr [ebp-0x30]
    add     eax, eax
    add     eax, dword ptr [ebp-0x34]
    mov     dword ptr [ebp-0x44], eax
    {HDM('eax')}
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [ebp-0x54], eax
    mov     eax, dword ptr [ebp-0x34]
    {HDM('eax')}
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [ebp-0x50], eax
    mov     dword ptr [ebp-0x2C], eax
    mov     eax, dword ptr [g_mon_num]
    cmp     eax, 22                 ; T = stripe_rows(num): 1 below 22, else max(2, num >> 4) (P = 2T, hN = T)
    sbb     edx, edx
    shr     eax, 4
    cmp     eax, 2
    adc     eax, edx
    mov     dword ptr [ebp-0x48], eax
pn_dy:
    mov     eax, dword ptr [ebp-0x2C]
    cmp     eax, dword ptr [ebp-0x54]
    jge     pn_done
    test    eax, eax
    jl      pn_dynext
    cmp     eax, dword ptr [ebp-0x20]
    jge     pn_dynext
    sub     eax, dword ptr [ebp-0x50]
    push    eax
    cdq
    div     dword ptr [ebp-0x48]
    mov     ebx, eax                ; (y - Y0) // T: even = light stripe ((y - Y0) mod P < hN)
    pop     eax                     ; k = ((y - Y0) * 8) // num: the native row PAIR under this device row
    shl     eax, 3
    cdq
    div     dword ptr [g_mon_num]
    mov     ecx, dword ptr [ebp-0x30]
    dec     ecx
    cmp     eax, ecx
    jle     pn_k
    mov     eax, ecx
pn_k:
    add     eax, eax
    add     eax, dword ptr [ebp-0x34]
    mov     dword ptr [ebp-0x60], eax
    lea     edx, [eax+eax*2]
    shl     edx, 2
    add     edx, dword ptr [ebp-0x24]
    mov     eax, dword ptr [edx+4]
    {HDM('eax')}
    add     eax, dword ptr [ebp+0x10]
    mov     dword ptr [ebp-0x64], eax
    mov     eax, dword ptr [edx+8]
    inc     eax
    {HDM('eax')}
    add     eax, dword ptr [ebp+0x10]
    mov     dword ptr [ebp-0x68], eax
    sub     eax, dword ptr [ebp-0x64]
    jle     pn_dynext
    mov     dword ptr [ebp-0x6C], eax
    mov     eax, dword ptr [ebp-0x64]
    test    eax, eax
    jge     pn_xs
    xor     eax, eax
pn_xs:
    mov     dword ptr [ebp-0x70], eax
    mov     eax, dword ptr [ebp-0x68]
    cmp     eax, dword ptr [ebp-0x1C]
    jle     pn_xe
    mov     eax, dword ptr [ebp-0x1C]
pn_xe:
    mov     dword ptr [ebp-0x74], eax
    cmp     eax, dword ptr [ebp-0x70]
    jle     pn_dynext
    mov     edi, dword ptr [ebp-0x2C]
    imul    edi, dword ptr [ebp-0x18]
    add     edi, dword ptr [ebp-0x14]
    add     edi, dword ptr [ebp-0x70]
    mov     ecx, dword ptr [ebp-0x74]
    sub     ecx, dword ptr [ebp-0x70]
    test    bl, 1
    jnz     pn_dark
    mov     eax, dword ptr [ebp-0x38]
    rep stosb
    jmp     pn_dynext
pn_dark:
    mov     eax, dword ptr [ebp-0x60]
    inc     eax
    mov     ecx, dword ptr [ebp-0x44]
    dec     ecx
    cmp     eax, ecx
    jle     pn_nd
    mov     eax, ecx
pn_nd:
    imul    eax, dword ptr [ebp-8]
    add     eax, dword ptr [ebp-4]
    mov     dword ptr [ebp-0x80], eax
    mov     eax, dword ptr [edx+8]
    inc     eax
    sub     eax, dword ptr [edx+4]
    mov     dword ptr [ebp-0x7C], eax
    mov     eax, dword ptr [edx+4]
    mov     dword ptr [ebp-0x84], eax
    mov     esi, dword ptr [ebp-0x70]
pn_dx:
    mov     eax, esi
    sub     eax, dword ptr [ebp-0x64]
    mul     dword ptr [ebp-0x7C]
    div     dword ptr [ebp-0x6C]
    add     eax, dword ptr [ebp-0x84]
    mov     ecx, dword ptr [ebp-0xC]
    dec     ecx
    cmp     eax, ecx
    jle     pn_si
    mov     eax, ecx
pn_si:
    add     eax, dword ptr [ebp-0x80]
    mov     al, byte ptr [eax]
    mov     byte ptr [edi], al
    inc     edi
    inc     esi
    cmp     esi, dword ptr [ebp-0x74]
    jl      pn_dx
pn_dynext:
    inc     dword ptr [ebp-0x2C]
    jmp     pn_dy
pn_done:
    pop     edi
    pop     esi
    pop     ebx
    leave
    ret     0x10
"""


THUNKS = [
    ("t_mon_build", asm_mon_build), ("t_mon_rects", asm_mon_rects), ("t_mon_btn", asm_mon_btn),
    ("t_mon_bd_far", asm_mon_bd_far), ("t_mon_bd_near", asm_mon_bd_near), ("t_mon_pic", asm_mon_pic),
    ("t_mon_spr_nn", asm_mon_spr_nn), ("t_mon_spr_pic", asm_mon_spr_pic), ("t_mon_font", asm_mon_font),
    ("t_mon_gate", asm_mon_gate), ("t_mon_restripe", asm_mon_restripe), ("t_mon_face", asm_mon_face),
    ("t_mon_lut", asm_mon_lut), ("t_mon_resample", asm_mon_resample), ("t_mon_panel", asm_mon_panel),
]
DATA = [("g_mon_lz", lz_table)]

CELL: dict[str, int] = {}


def _align(v: int, a: int = 16) -> int:
    return (v + a - 1) & ~(a - 1)


def assemble_all():
    """({name: (offset, bytes)}, cells {name: (offset, size)}, end offset, names {name: VA}).  Iterated to a
    fixed point: the thunks reference each other and the cells by name (substituted as literal VAs)."""
    names = {n: PCAVE2 + OFF_CODE for n, _ in THUNKS}
    names.update({n: PCAVE2 + OFF_CODE for n, _ in DATA})
    names.update({n: PCAVE2 + OFF_CODE for n, _ in CELL_DEFS})
    names.update({n: PCAVE2 + o for n, o, _ in PLACED_THUNKS})
    names.update({n: PCAVE2 + o for n, o, _ in PLACED_CELLS})
    names.update({n: PCAVE2 + o for n, o, _ in PLACED_DATA})
    layout: dict[str, tuple[int, bytes]] = {}
    cells: dict[str, tuple[int, int]] = {}
    for _pass in range(12):
        off = OFF_CODE
        new_layout = {}
        for n, fn in THUNKS:
            if n in FROZEN:                          # a predecessor shrank: keep the baked slot map
                assert off <= FROZEN[n], (n, off, FROZEN[n])
                off = FROZEN[n]
            b = SE.assemble(fn(), names[n], names)
            new_layout[n] = (off, b)
            off = _align(off + len(b))
        for n, fn in DATA:
            b = fn()
            new_layout[n] = (off, b)
            off = _align(off + len(b))
        new_cells = {}
        for n, sz in CELL_DEFS:
            new_cells[n] = (off, sz)
            off = _align(off + sz, 4)
        end = _align(off)
        placed_end = 0
        for n, o, fn in PLACED_THUNKS:               # fixed slots outside the sequential block (no block offset moves)
            assert o >= placed_end, (n, o, placed_end)
            b = SE.assemble(fn(), PCAVE2 + o, names)
            new_layout[n] = (o, b)
            placed_end = o + len(b)
        for n, o, sz in PLACED_CELLS:
            assert o >= placed_end, (n, o, placed_end)
            placed_end = o + sz
        assert placed_end <= OFF_PLACED_END, (hex(placed_end), hex(OFF_PLACED_END))
        for n, o, b in PLACED_DATA:
            new_layout[n] = (o, b)
        new_names = {n: PCAVE2 + o for n, (o, _) in new_layout.items()}
        new_names.update({n: PCAVE2 + o for n, (o, _) in new_cells.items()})
        new_names.update({n: PCAVE2 + o for n, o, _ in PLACED_CELLS})
        stable = new_names == names and all(layout.get(n, (0, None))[1] == b for n, (_, b) in new_layout.items())
        layout, cells, names = new_layout, new_cells, new_names
        if stable:
            break
    else:
        raise RuntimeError("layout did not converge")
    CELL.clear()
    CELL.update({n: PCAVE2 + o for n, (o, _) in cells.items()})
    return layout, cells, end, names


SYM_ABS = {SCALE_NN: "thunk_sprite_scale_nn", GATE_PRE: "thunk_btn_gate_pre", CRT_MALLOC: "crt_malloc", SCALE_UNIFORM: "scale_uniform",
           PCAVE2 + 0x22000: "t_dl_immfix", PCAVE2 + 0x27E10: "g_dl_immg", PCAVE2 + 0x24190: "t_rw_iconblit",
           PCAVE2 + 0x213C0: "t_rwk_parity_nn",
           T_FFN_AT: "t_ffn_at", T_FDIRECT_AT: "t_fdirect_at", G_FONT_MON_PLAQUE: "g_font_mon_plaque",
           G_FONT_MON_BTN: "g_font_mon_btn", G_FONT_HOF_BTN: "g_font_hof_btn"}

# Frozen offsets (fonts v2 2026-09-17: t_mon_btn / t_mon_font / t_hof_btn shrank): the successors keep
# their baked offsets so the block's later thunks, the data and the cells do not move.
FROZEN = {"t_mon_bd_far": 0x2B3C0, "t_mon_gate": 0x2B6D0, "t_mon_resample": 0x2BA20, "t_hof_fonts": 0x2C780}


def templatize(b: bytes, va: int, names: dict[str, int]) -> str:
    syms = dict(SYM_ABS)
    syms.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, syms)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- sites ------------------------------------------------------------------------------------------------------
def site_list(names: dict[str, int]) -> list[dict]:
    S = []

    def add(sid, fn, va, orig, new, pattern, note=""):
        S.append({"id": sid, "group": "mon_scale", "function": fn, "va": va, "orig": orig, "new": new, "pattern": pattern, "note": note})

    def redirect(sid, fn, va, native_target, thunk, note=""):
        orig = bytes([0xE8]) + struct.pack("<i", native_target - (va + 5))
        add(sid, fn, va, orig, f"E8 {{rel32:{thunk}}}", "call_target_redirect", note)

    def detour(sid, fn, va, ln, thunk, note=""):
        orig = SE.base_exe_bytes(va, ln)
        jmp = hx(bytes([0xE9]) + struct.pack("<i", names[thunk] - (va + 5)))
        add(sid, fn, va, orig, jmp + " 90" * (ln - 5), "detour_inplace", f"{note} (E9 -> {thunk})")

    redirect("monument.load_monicons", "monument", 0x476AE6, LOAD_MONICONS, "t_mon_build",
             "call load_monicons (its one caller): builder, then the full-height letterbox levers (window, content rect, 30 rects, CLOSE/BACK)")
    redirect("MonumentWin_draw.far_backdrop", "MonumentWin_draw", 0x4760E2, COPY4, "t_mon_bd_far",
             "Buffer_copy_4 of the 1024x768 monument.flc still 1:1 -> Lanczos-3 + FS dither to the letterboxed s(1024) x s(768)")
    redirect("MonumentWin_draw.near_backdrop", "MonumentWin_draw", 0x4737E9, COPY4, "t_mon_bd_near",
             "Buffer_copy_4 of monzoom1/2.pcx 1:1 -> resampled + the blue plaque panel regenerated as device-density scanlines")
    redirect("MonumentWin_draw.near_picture_a", "MonumentWin_draw", 0x475F37, COPY4, "t_mon_pic",
             "Buffer_copy_4 of the 600x360 faction3.pcx picture 1:1 at the table rect -> resampled s(600) x s(360)")
    redirect("MonumentWin_draw.near_picture_b", "MonumentWin_draw", 0x47605D, COPY4, "t_mon_pic",
             "Buffer_copy_4 of the 600x360 monbigN.pcx picture 1:1 -> resampled s(600) x s(360)")
    for sid, va, what in (("icon", 0x476258, "44x42 milestone icons"), ("banner_l", 0x476435, "left banners"),
                          ("banner_r", 0x476499, "right banners"), ("glyph", 0x476515, "58x50 faction glyphs"),
                          ("emblem", 0x476587, "emblem")):
        redirect(f"MonumentWin_draw.{sid}", "MonumentWin_draw", va, BLIT_CORE, "t_mon_spr_nn",
                 f"Sprite_blit_scaled_core 1:1 ({what}) -> thunk_sprite_scale_nn at num/16")
    redirect("MonumentWin_draw.far_picture", "MonumentWin_draw", 0x47639D, BLIT_CORE, "t_mon_spr_pic",
             "Sprite_blit_scaled_core 1:1 (160x97 far picture, opaque) -> resampled s(160) x s(97)")
    for sid, va in (("hover_own", 0x4768F3), ("hover_big", 0x476932), ("hover_faction", 0x47698E)):
        redirect(f"MonumentWin_on_mouse_move.{sid}", "MonumentWin_on_mouse_move", va, BLIT_CORE, "t_mon_spr_pic",
                 "hover re-blit of the 160x97 picture -> resampled")
    detour("MonumentWin_draw.plaque_font", "MonumentWin_draw", FONT_SITE, 5, "t_mon_font",
           "mov eax,[0x8A40BC] -> find_font(fl(12*num/16), 0) when armed")
    detour("Buffer_draw_2.mon_button_restripe", "Buffer_draw_2", BUFFER_DRAW2, 5, "t_mon_restripe",
           "src == a Monument CLOSE/BACK canvas (or the HOF CLOSE canvas) -> face pair restriped at the P law, darker member on top")
    S.extend(hof_site_list(names))
    return S


def verify_live(sites) -> list[str]:
    """Every site's original bytes must be what the PRISTINE base holds (the patcher applies onto .bak)."""
    out = []
    for s in sites:
        got = SE.base_exe_bytes(s["va"], len(s["orig"]))
        if got != s["orig"]:
            out.append(f"{s['id']} @{s['va']:#x}: base {hx(got)} != expected {hx(s['orig'])}")
    return out


def site_yaml(sites) -> str:
    out = []
    for s in sites:
        new = s["new"] if isinstance(s["new"], str) else hx(s["new"])
        ln = sum(4 if t.startswith("{") else 1 for t in new.split())
        out.append(f"""  - id: {s['id']}
    status: confirmed
    group: {s['group']}
    function: {s['function']}
    virtual_addr: {s['va']:#010x}
    length: {ln}
    original_bytes: "{hx(s['orig'])}"   # {s['note']}
    new_bytes:      "{new}"
    pattern: {s['pattern']}
""")
    return "\n".join(out)


def main(argv):
    layout, cells, end, names = assemble_all()
    ok = True
    print("; ==== Planetary Monument bake (assemble_mon.py) ====")
    print(f"; block {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B); limit {OFF_LIMIT:#x}")
    if end > OFF_LIMIT:
        ok = False
        print("; OVERFLOW past the section end")
    sym_lines, content_lines = [], []
    for name, _fn in THUNKS:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {'hof_scale' if name.startswith('t_hof_') else 'mon_scale'} ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    for name, _o, _fn in PLACED_THUNKS:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # hof_scale ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x} (placed)")
    for name, off, size in PLACED_CELLS:
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    for name, off, b in PLACED_DATA:
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {len(b)} }}   # mon_scale DATA (t_mon_lut range)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{hx(b)}\"")
    for name, _fn in DATA:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {len(b)} }}   # {'hof_scale' if name.startswith('g_hof_') else 'mon_scale'} DATA")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{hx(b)}\"")
    for name, (off, size) in cells.items():
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    sites = site_list(names)
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_mon_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_mon_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_mon_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_mon_*.yaml")
    print(f"; sites: {len(sites)}")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


# =====================================================================================================================
# HALL OF FAME (F10; FameWin 0x74DAF8) -- the second full-screen menu in this block (2026-09-14).
# Same design as the Monument (user decision 2026-09-13): num = min(mon_scale_num(W, H), 72) over 16 (the 72
# clamp = the painter's imm8 literals, scaling_laws.HOF_NUM_MAX), armed only in the wide layout with num > 16.
# Levers (laws scaling_laws.hof_*; parity tests/test_hof_asm_parity.py):
#   W/T/N  t_hof_build      call_target_redirect @0x44AEC0 (hall_of_fame: `call load_hoficons`, its ONE caller): runs
#                           the builder, then (ret 0, armed) GraphicWin_resize(win, SW, SH, 1) + +0x13C/+0x474 := screen
#                           + GraphicWin_clear(0) (the letterbox), content rect +0xA24, the 6 rects of +0xB42C REBUILT
#                           from the 24 literals (g_hof_rects: letterbox + s(119|80) + s(lit)), the 13 icon buttons
#                           resized to fl(cell) and re-centred in their pitch (t_hof_icons), CLOSE resized/moved/font-
#                           stamped (t_hof_btn), the 3 painter fonts at num (t_hof_fonts: find_font, or Font_init on a
#                           scratch Font above the 40-px pool), +0xA44 (row pitch) from the num body font, the 23
#                           painter imm rows walked by t_dl_immfix with g_dl_immg := num (g_hof_immtab).
#   B      t_hof_bd_frame   Buffer_copy_4 redirect @0x448DFC (frame.pcx 1024x768 1:1): Lanczos-3 + FS (t_mon_resample)
#                           to the letterbox (its dither is error-diffusion texture; its scanline field is under hof.pcx).
#          t_hof_bd_hof     Buffer_copy_4 redirect @0x448E32 (hof.pcx 800x600 1:1 at the content origin): the art is
#                           a 1-px light/dark scanline field with 1-px box frames and dithered bands -> t_hof_pairnn
#                           (v6): edge-safe NN with ONLY the row-pair texels regenerated at the P law (brighter
#                           member wide) -- the parity NN of v2..v5 dropped single-row strokes/chamfers at 22/16 and
#                           25/16 (t_rwk_parity_nn stays only on the row-dithered faction picture).  Key 9.
#          t_hof_bd_map     Buffer_copy_4 redirect @0x448FCC (the score's world-map pcx, 238x118 native pixel art, into
#                           rect 1 whose dx,dy are ALREADY device): parity NN of the native 238x118 (clamped to the
#                           source Buffer) at the passed origin (v2; Lanczos+FS speckled the coastlines).
#   G      t_hof_spr_pic    Sprite_blit_scaled_core redirect @0x449076 (233x124 faction picture, row-dithered art):
#                           t_rwk_parity_nn with the engine's (dest, key, x, y) at num/16 (v2; Lanczos+FS moire-banded it).
#   N(a)   t_hof_face       the FlatButton_content_draw state-sprite blit @0x607F43 (shared chain head; previous
#                           target t_rw_iconblit): dest == one of the 13 HOF icon canvases at 1/1 -> re-centred on the
#                           scaled face (hof_face_origin) and drawn by t_rwk_parity_nn at num/16 (the 79x79 / 70x70
#                           faces are cut from the same scanline field), else chain.
#   F      t_hof_font_*     5 detours on the painter's font loads ([0x8A40C8] f14 x3, [0x8A40D4] f16, [0x8A40EC] f22):
#                           reg := g_hof_f14/f16/f22 when armed (flag-transparent).
#   N(b)   t_mon_gate       + the HOF CLOSE static (FameWin+0x9DCC) when g_hof_armed.
#   N(c)   t_mon_restripe   + the HOF CLOSE canvas -> t_mon_face(buf, num) with g_hof_num.
# NOT levers: the 57 HOF rows the rw_scale_kinds table carried at the popup g (window/canvas/content/24 rect literals/
# painter insets/CLOSE) are REMOVED from that table (assemble_rw.rw_rows HOF_ROW_RANGE) -- this block owns the screen.
# =====================================================================================================================
FW = 0x0074DAF8                # FameWin_g
FW_CANVAS = FW + 0x444
HOF_CLOSE = FW + 0x9DCC
HOF_CAT0, HOF_FAC0, HOF_BTN_STRIDE = FW + 0x5A04, FW + 0xA5C, 0xB4C
HOF_TABLE = FW + 0xB42C
LOAD_HOFICONS = 0x00448400     # fastcall(this)
HOF_CALL_SITE = 0x0044AEC0     # hall_of_fame: call load_hoficons
G_POPUP = 0x00668740           # g_popup_scale_num (t_rwk_parity_nn's stripe period source; bracketed to num)
FONT_INIT = 0x00618F40         # thiscall(this, name, size, style) RET 0xC
AN_STR = PCAVE2 + 0x800        # "Arial Narrow" (the popup arc's scaled-font face string)
HOF_FONT_TABLES = (0x008A40C8, 0x008A40D4, 0x008A40EC)     # f14 / f16 / f22 of the report family's table
T_DL_IMMFIX = PCAVE2 + 0x22000
G_DL_IMMG = PCAVE2 + 0x27E10
T_RW_ICONBLIT = PCAVE2 + 0x24190
T_RWK_PARITY_NN = PCAVE2 + 0x213C0
HOF_FONT_SITES = (              # (va, len, reg, table index) -- mov reg, [table]
    (0x00448E3F, 5, "eax", 0), (0x00449E7A, 6, "ecx", 2), (0x00449F97, 5, "eax", 0),
    (0x00449FEE, 5, "eax", 1), (0x0044A169, 6, "ecx", 0))
HOF_PAINTER_IMMS = [            # (operand va, width, a, b, label): value = s(a) - s(b) at num (the rw_kinds_rows idiom)
    (0x449041, 1, 9, 0, "crest x = r5.L+9"), (0x449050, 1, 10, 0, "crest y = r5.T+10"),
    (0x449093, 1, 3, 0, "analysis x+3"), (0x449096, 1, 3, 0, "analysis y+3"),
    (0x4490AF, 1, 6, 0, "analysis w-6"), (0x4490BE, 1, 6, 0, "analysis h-6"),
    (0x449EFB, 1, 0x15, 0, "band h 0x15"), (0x449F0E, 1, 0x14, 0, "band w = tw+0x14"),
    (0x449F11, 1, 0xF, 0, "band y = +0xF"), (0x449F31, 4, 0x186, 0, "band x = -tw/2+0x186"),
    (0x449F4E, 1, 0x10, 0, "title y = +0x10"), (0x449F66, 4, 0x320, 0, "title centre w 800"),
    (0x44A052, 4, 0xF7, 0, "panel title y +0xF7 (TOP 5)"), (0x44A058, 1, 0x1C, 0, "TOP 5 x +0x1C"), (0x44A070, 4, 0x109, 0, "TOP 5 w 0x109"),
    (0x44A0CA, 4, 0xF7, 0, "panel title y +0xF7 (MAP)"), (0x44A0CF, 4, 0x12E, 0, "MAP x +0x12E"), (0x44A0EA, 4, 0xF0, 0, "MAP w 0xF0"),
    (0x44A139, 4, 0xF7, 0, "panel title y +0xF7 (ANALYSIS)"), (0x44A13E, 4, 0x227, 0, "ANALYSIS x +0x227"), (0x44A159, 4, 0xD4, 0, "ANALYSIS w 0xD4"),
    (0x44A1F0, 1, 3, 0, "score row y+3"), (0x44A463, 1, 6, 0, "score row step +6"),
]
HOF_CELL_DEFS = [("g_hof_num", 4), ("g_hof_armed", 4), ("g_hof_lx", 4), ("g_hof_ly", 4), ("g_hof_ox", 4), ("g_hof_oy", 4),
                 ("g_hof_sw", 4), ("g_hof_sh", 4), ("g_hof_f14", 4), ("g_hof_f16", 4), ("g_hof_f22", 4),
                 ("g_hof_fonts_num", 4), ("g_hof_gsave", 4), ("g_hof_immg_save", 4), ("g_hof_fontscratch", 3 * 0x28)]
HOF_FONT_CELLS = ("g_hof_f14", "g_hof_f16", "g_hof_f22")
CAT_OFF = SL.hof_button_offsets(SL.HOF_CAT_N, SL.HOF_RECTS_NATIVE[SL.HOF_CAT_RECT], SL.HOF_CAT_CELL)   # (pitch 108, x0 14, y0 0)
FAC_OFF = SL.hof_button_offsets(SL.HOF_FAC_N, SL.HOF_RECTS_NATIVE[SL.HOF_FAC_RECT], SL.HOF_FAC_CELL)   # (pitch 107, x0 18, y0 22)


def hof_rects_table() -> bytes:
    """g_hof_rects: the 24 native window-space edges of the +0xB42C table (literal + 119|80)."""
    return b"".join(struct.pack("<4i", *r) for r in SL.HOF_RECTS_NATIVE)


def hof_imm_rows():
    K_W4 = 1
    return [(site, a, b, (K_W4 if w == 4 else 0)) for site, w, a, b, _l in HOF_PAINTER_IMMS]


def hof_immtab() -> bytes:
    """g_hof_immtab in t_dl_immfix's row format (site, a, b, bits) + a 0 terminator; every row HD."""
    out = bytearray()
    for site, a, b, bits in hof_imm_rows():
        out += struct.pack("<IiiI", site, a, b, bits)
    return bytes(out) + b"\x00" * 4


def HDN(reg: str) -> str:
    """reg = half_down(reg*num, 16) with the HOF's num."""
    return f"imul {reg}, dword ptr [g_hof_num]\n    lea {reg}, [{reg}*2+15]\n    sar {reg}, 5\n"


def asm_hof_build() -> str:
    return f"""
    call    {LOAD_HOFICONS:#x}
    test    eax, eax
    jnz     hb_done
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     dword ptr [g_hof_armed], 0
    mov     eax, dword ptr [{SH:#x}]
    mov     dword ptr [g_hof_sh], eax
    mov     ecx, dword ptr [{SW:#x}]
    mov     dword ptr [g_hof_sw], ecx
    mov     eax, {SL.NATIVE_G}
    call    {SCALE_UNIFORM:#x}      ; min(fl(16H/768), fl(16W/1024)), then the 72 clamp (SL.hof_scale_num)
    cmp     eax, {SL.HOF_NUM_MAX}
    jle     hb_cap
    mov     eax, {SL.HOF_NUM_MAX}
hb_cap:
    mov     dword ptr [g_hof_num], eax
    cmp     eax, 16
    jle     hb_native
    cmp     dword ptr [{WIDE:#x}], 0
    je      hb_native
    mov     eax, {SL.MON_NATIVE_W}
    {HDN('eax')}
    mov     ecx, dword ptr [g_hof_sw]
    sub     ecx, eax
    sar     ecx, 1
    mov     dword ptr [g_hof_lx], ecx
    mov     eax, {SL.MON_NATIVE_H}
    {HDN('eax')}
    mov     ecx, dword ptr [g_hof_sh]
    sub     ecx, eax
    sar     ecx, 1
    mov     dword ptr [g_hof_ly], ecx
    mov     eax, {SL.HOF_ORG_X}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_lx]
    mov     dword ptr [g_hof_ox], eax
    mov     eax, {SL.HOF_ORG_Y}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_ly]
    mov     dword ptr [g_hof_oy], eax
    mov     dword ptr [g_mon_lut_ok], 0
    mov     esi, {FW:#x}
    push    1
    push    dword ptr [g_hof_sh]
    push    dword ptr [g_hof_sw]
    mov     ecx, esi
    call    {GW_RESIZE:#x}
    mov     dword ptr [g_hof_armed], 1
    xor     eax, eax
    mov     dword ptr [esi+0x13C], eax
    mov     dword ptr [esi+0x140], eax
    mov     dword ptr [esi+0x474], eax
    mov     dword ptr [esi+0x478], eax
    mov     eax, dword ptr [g_hof_sw]
    mov     dword ptr [esi+0x144], eax
    mov     dword ptr [esi+0x47C], eax
    mov     eax, dword ptr [g_hof_sh]
    mov     dword ptr [esi+0x148], eax
    mov     dword ptr [esi+0x480], eax
    lea     eax, [esi+0x474]
    push    eax
    lea     ecx, [esi+0x444]
    call    {BUFFER_SET_CLIP:#x}
    push    0
    mov     ecx, esi
    call    {GW_CLEAR:#x}
    mov     eax, {SL.HOF_CONTENT_NATIVE[0]}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_lx]
    mov     dword ptr [esi+0xA24], eax
    mov     eax, {SL.HOF_CONTENT_NATIVE[1]}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_ly]
    mov     dword ptr [esi+0xA28], eax
    mov     eax, {SL.HOF_CONTENT_NATIVE[2]}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_lx]
    mov     dword ptr [esi+0xA2C], eax
    mov     eax, {SL.HOF_CONTENT_NATIVE[3]}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_ly]
    mov     dword ptr [esi+0xA30], eax
    lea     edi, [esi+{HOF_TABLE - FW:#x}]
    call    t_hof_rects
    lea     edi, [esi+{HOF_CAT0 - FW:#x}]
    lea     edx, [esi+{HOF_TABLE - FW + 16 * SL.HOF_CAT_RECT:#x}]
    mov     ecx, {SL.HOF_CAT_N}
    push    {CAT_OFF[2]}
    push    {CAT_OFF[1]}
    push    {CAT_OFF[0]}
    push    {SL.HOF_CAT_CELL:#x}
    call    t_hof_icons
    lea     edi, [esi+{HOF_FAC0 - FW:#x}]
    lea     edx, [esi+{HOF_TABLE - FW + 16 * SL.HOF_FAC_RECT:#x}]
    mov     ecx, {SL.HOF_FAC_N}
    push    {FAC_OFF[2]}
    push    {FAC_OFF[1]}
    push    {FAC_OFF[0]}
    push    {SL.HOF_FAC_CELL:#x}
    call    t_hof_icons
    lea     edi, [esi+{HOF_CLOSE - FW:#x}]
    call    t_hof_btn
    call    t_hof_fonts
    mov     eax, dword ptr [g_hof_f14]
    mov     ecx, dword ptr [eax]
    test    ecx, ecx
    jns     hb_lh_pad
    mov     ecx, dword ptr [eax+0xC]
    jmp     hb_lh
hb_lh_pad:
    add     ecx, dword ptr [eax+0x10]
hb_lh:
    mov     dword ptr [esi+0xA44], ecx
    mov     eax, dword ptr [{G_DL_IMMG:#x}]
    mov     dword ptr [g_hof_immg_save], eax
    mov     eax, dword ptr [g_hof_num]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
    mov     esi, g_hof_immtab
    call    {T_DL_IMMFIX:#x}
    mov     eax, dword ptr [g_hof_immg_save]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
hb_native:
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
hb_done:
    ret
"""


def asm_hof_rects() -> str:     # edi = the +0xB42C table: 24 edges := origin + s(native - 119|80) from g_hof_rects
    return f"""
    xor     ebx, ebx
    mov     edx, g_hof_rects
hr_loop:
    mov     eax, dword ptr [edx+ebx*4]
    test    ebx, 1
    jnz     hr_y
    sub     eax, {SL.HOF_ORG_X}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_ox]
    jmp     hr_st
hr_y:
    sub     eax, {SL.HOF_ORG_Y}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_oy]
hr_st:
    mov     dword ptr [edi+ebx*4], eax
    inc     ebx
    cmp     ebx, 24
    jl      hr_loop
    ret
"""


def asm_hof_icons() -> str:     # (cell, pitch_nat, x0_nat, y0_nat) RET 0x10; edi = first button, edx = its DEVICE row rect, ecx = n
    # scaling_laws.hof_button_rect v5: x = L_dev + s(x0 + i*pitch), y = T_dev + s(y0) -- the NATIVE centring offsets scaled
    # (centring the scaled face in the scaled row dropped the bottom row onto the art's separator line at 1600x1200).
    # frame: -4 n, -8 cell, -0xC size, -0x10 (unused), -0x14 i, -0x18 rect, -0x1C y, -0x20 x
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x20
    mov     dword ptr [ebp-4], ecx
    mov     dword ptr [ebp-0x18], edx
    mov     eax, dword ptr [ebp+8]
    mov     dword ptr [ebp-8], eax
    imul    eax, dword ptr [g_hof_num]
    sar     eax, 4
    mov     dword ptr [ebp-0xC], eax
    mov     eax, dword ptr [ebp+0x14]
    {HDN('eax')}
    mov     edx, dword ptr [ebp-0x18]
    add     eax, dword ptr [edx+4]
    mov     dword ptr [ebp-0x1C], eax
    mov     dword ptr [ebp-0x14], 0
hi_loop:
    mov     eax, dword ptr [ebp-0x14]
    imul    eax, dword ptr [ebp+0xC]
    add     eax, dword ptr [ebp+0x10]
    {HDN('eax')}
    mov     edx, dword ptr [ebp-0x18]
    add     eax, dword ptr [edx]
    mov     dword ptr [ebp-0x20], eax
    push    1
    push    dword ptr [ebp-0xC]
    push    dword ptr [ebp-0xC]
    mov     ecx, edi
    call    {GW_RESIZE:#x}
    mov     eax, dword ptr [ebp-0x20]
    mov     dword ptr [edi+0x13C], eax
    add     eax, dword ptr [ebp-0xC]
    mov     dword ptr [edi+0x144], eax
    mov     eax, dword ptr [ebp-0x1C]
    mov     dword ptr [edi+0x140], eax
    add     eax, dword ptr [ebp-0xC]
    mov     dword ptr [edi+0x148], eax
    xor     eax, eax
    mov     dword ptr [edi+0x474], eax
    mov     dword ptr [edi+0x478], eax
    mov     eax, dword ptr [ebp-0xC]
    mov     dword ptr [edi+0x47C], eax
    mov     dword ptr [edi+0x480], eax
    mov     eax, dword ptr [edi]
    mov     ecx, edi
    call    dword ptr [eax+0xF8]
    add     edi, {HOF_BTN_STRIDE:#x}
    inc     dword ptr [ebp-0x14]
    mov     eax, dword ptr [ebp-0x14]
    cmp     eax, dword ptr [ebp-4]
    jl      hi_loop
    mov     esp, ebp
    pop     ebp
    ret     0x10
"""


def asm_hof_btn() -> str:       # edi = CLOSE: resize to s(0xCE) x s(0x16), move to (OX + s(0x22A), OY + s(0x22C)), label font, repaint
    x, y, w, h = SL.HOF_CLOSE_NATIVE
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    mov     eax, {w}
    {HDN('eax')}
    mov     dword ptr [ebp-4], eax
    mov     eax, {h}
    {HDN('eax')}
    mov     dword ptr [ebp-8], eax
    mov     eax, {x}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_ox]
    mov     dword ptr [ebp-0xC], eax
    mov     eax, {y}
    {HDN('eax')}
    add     eax, dword ptr [g_hof_oy]
    mov     dword ptr [ebp-0x10], eax
    push    1
    push    dword ptr [ebp-8]
    push    dword ptr [ebp-4]
    mov     ecx, edi
    call    {GW_RESIZE:#x}
    mov     eax, dword ptr [ebp-0xC]
    mov     dword ptr [edi+0x13C], eax
    add     eax, dword ptr [ebp-4]
    mov     dword ptr [edi+0x144], eax
    mov     eax, dword ptr [ebp-0x10]
    mov     dword ptr [edi+0x140], eax
    add     eax, dword ptr [ebp-8]
    mov     dword ptr [edi+0x148], eax
    xor     eax, eax
    mov     dword ptr [edi+0x474], eax
    mov     dword ptr [edi+0x478], eax
    mov     eax, dword ptr [ebp-4]
    mov     dword ptr [edi+0x47C], eax
    mov     eax, dword ptr [ebp-8]
    mov     dword ptr [edi+0x480], eax
    push    dword ptr [g_hof_num]
    push    1
    push    {SL.HOF_FONT_LABEL}
    push    {G_FONT_HOF_BTN:#x}
    call    {T_FDIRECT_AT:#x}
    add     esp, 16
    mov     dword ptr [edi+0x970], eax
    mov     eax, dword ptr [edi]
    mov     ecx, edi
    call    dword ptr [eax+0xF8]
    mov     esp, ebp
    pop     ebp
    ret
"""


def asm_hof_fonts() -> str:     # g_hof_f14/f16/f22 := find_font(fl(size*num/16), 0), or Font_init(scratch, "Arial Narrow", n, BOLD) above 40
    # v2 (2026-09-17, audit finding 3.16): the pool's f14/f16/f22 are Arial Narrow BOLD (style 1|v0);
    # the above-40 scratch branch pushed style 0 and dropped the bold (band @1440p, band+titles @4K).
    body = ""
    for k, sz in enumerate(SL.HOF_FONTS):
        scratch = f"g_hof_fontscratch+{0x28 * k:#x}" if k else "g_hof_fontscratch"
        body += f"""
    mov     eax, {sz}
    imul    eax, dword ptr [g_hof_num]
    sar     eax, 4
    cmp     eax, {SL.HOF_FONT_TABLE_MAX}
    jle     hf_ff{k}
    push    {SL.HOF_FONT_SCRATCH_STYLE}
    push    eax
    push    {AN_STR:#x}
    mov     ecx, {scratch}
    mov     eax, {FONT_INIT:#x}
    call    eax
    mov     eax, {scratch}
    jmp     hf_st{k}
hf_ff{k}:
    push    0
    push    eax
    call    {FIND_FONT:#x}
    add     esp, 8
    test    eax, eax
    jnz     hf_st{k}
    mov     eax, dword ptr [{HOF_FONT_TABLES[k]:#x}]
hf_st{k}:
    mov     dword ptr [{HOF_FONT_CELLS[k]}], eax
"""
    return f"""
    mov     eax, dword ptr [g_hof_num]
    cmp     eax, dword ptr [g_hof_fonts_num]
    je      hf_done
    mov     dword ptr [g_hof_fonts_num], eax
{body}
hf_done:
    ret
"""


def asm_hof_font(reg: str, table: int, resume: int) -> str:     # detour on `mov reg, [table]`: reg := the num font when armed
    return f"""
    pushfd
    cmp     dword ptr [g_hof_armed], 0
    je      hfd_native
    mov     {reg}, dword ptr [{HOF_FONT_CELLS[HOF_FONT_TABLES.index(table)]}]
    popfd
    jmp     {resume:#x}
hfd_native:
    mov     {reg}, dword ptr [{table:#x}]
    popfd
    jmp     {resume:#x}
"""


def _hof_font_thunks():
    return [(f"t_hof_font_{va:x}", (lambda r=reg, t=HOF_FONT_TABLES[ti], rs=va + ln: (lambda: asm_hof_font(r, t, rs)))())
            for va, ln, reg, ti in HOF_FONT_SITES]


def asm_hof_bd_frame() -> str:  # Buffer_copy_4 redirect: the 1024x768 frame.pcx -> t_mon_resample to (LX + s(dx), LY + s(dy)) s(w) x s(h)
    return f"""
    cmp     dword ptr [g_hof_armed], 0
    je      bf_native
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    mov     esi, ecx
    mov     eax, dword ptr [ebp+0x2C]
    {HDN('eax')}
    push    eax
    mov     eax, dword ptr [ebp+0x28]
    {HDN('eax')}
    push    eax
    mov     eax, dword ptr [ebp+0x24]
    {HDN('eax')}
    add     eax, dword ptr [g_hof_ly]
    push    eax
    mov     eax, dword ptr [ebp+0x20]
    {HDN('eax')}
    add     eax, dword ptr [g_hof_lx]
    push    eax
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x2C]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [esi+0x4A8]
    push    dword ptr [esi+0x54]
    call    t_mon_resample
    mov     esp, ebp
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
    ret     0x1C
bf_native:
    jmp     {COPY4:#x}
"""


def asm_hof_bd_map() -> str:    # Buffer_copy_4 redirect: the 238x118 world-map pcx (pixel art; src clamped to its Buffer) -> parity NN at the passed DEVICE origin
    # v2 2026-09-14: Lanczos+FS sprayed error-diffusion speckle around the coastlines (user 4K shot 012008) -> the same
    # v6: t_hof_pairnn (edge-safe NN; a pixel-art dump has no row pairs -> plain NN); literal key texels of the dump -> black first.
    mw, mh = SL.HOF_MAP_NATIVE
    return f"""
    cmp     dword ptr [g_hof_armed], 0
    je      bm_native
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    sub     esp, 0x28
    mov     esi, ecx
    xor     eax, eax
    mov     dword ptr [ebp-0x28], eax
    mov     dword ptr [ebp-0x20], eax
    mov     dword ptr [ebp-0x8], eax
    mov     dword ptr [ebp-0x4], eax
    mov     eax, dword ptr [esi+0x4A8]
    mov     dword ptr [ebp-0x1C], eax
    imul    eax, dword ptr [ebp+0x1C]
    add     eax, dword ptr [ebp+0x18]
    add     eax, dword ptr [esi+0x54]
    mov     dword ptr [ebp-0x24], eax
    mov     eax, {mw}
    mov     ecx, dword ptr [esi+0x80]
    cmp     ecx, eax
    jge     bm_w
    mov     eax, ecx
bm_w:
    mov     dword ptr [ebp-0x18], eax
    mov     dword ptr [ebp-0x10], eax
    mov     eax, {mh}
    mov     ecx, dword ptr [esi+0x84]
    neg     ecx
    cmp     ecx, eax
    jge     bm_h
    mov     eax, ecx
bm_h:
    mov     dword ptr [ebp-0x14], eax
    mov     dword ptr [ebp-0xC], eax
    mov     edi, dword ptr [ebp-0x24]
    mov     edx, dword ptr [ebp-0x14]
bm_fixrow:
    test    edx, edx
    jle     bm_fixdone
    xor     ebx, ebx
bm_fixcol:
    cmp     ebx, dword ptr [ebp-0x18]
    jge     bm_fixnext
    cmp     byte ptr [edi+ebx], {SL.HOF_BLIT_KEY}
    jne     bm_fixskip
    mov     byte ptr [edi+ebx], {SL.HOF_BLACK_INDEX}
bm_fixskip:
    inc     ebx
    jmp     bm_fixcol
bm_fixnext:
    add     edi, dword ptr [ebp-0x1C]
    dec     edx
    jmp     bm_fixrow
bm_fixdone:
    push    {SL.HOF_BLIT_KEY}
    push    dword ptr [ebp+0x24]
    push    dword ptr [ebp+0x20]
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp-0x14]
    push    dword ptr [ebp-0x18]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [ebp-0x1C]
    push    dword ptr [esi+0x54]
    call    t_hof_pairnn
    mov     esp, ebp
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
    ret     0x1C
bm_native:
    jmp     {COPY4:#x}
"""


def asm_hof_bd_hof() -> str:    # Buffer_copy_4 redirect: hof.pcx (scanline art + 1-px chrome) -> t_hof_pairnn at the passed origin, key 9
    # fake Sprite at [ebp-0x28]: +4 pcBits (+ sy*pitch + sx), +8 key byte, +0xC pitch, +0x10/+0x18 w, +0x14/+0x1C h, +0x20/+0x24 offsets 0
    return f"""
    cmp     dword ptr [g_hof_armed], 0
    je      bh_native
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    mov     esi, ecx
    push    {SL.HOF_BLIT_KEY}
    push    dword ptr [ebp+0x24]
    push    dword ptr [ebp+0x20]
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x2C]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [esi+0x4A8]
    push    dword ptr [esi+0x54]
    call    t_hof_pairnn
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
    ret     0x1C
bh_native:
    jmp     {COPY4:#x}
"""


def asm_hof_spr_pic() -> str:   # Sprite_blit_scaled_core redirect: the 233x124 faction picture -> parity NN at num/16 (the engine's key/x/y kept)
    # v2 2026-09-14: the picture art is row-dithered (the Believers cathedral moire-banded through Lanczos+FS in the user's 4K
    # shot 012008) -> t_rwk_parity_nn regenerates its stripes at the P law from num (g_popup_scale_num bracketed); the contract
    # is Sprite_draw_2's, so the engine's (dest, key, x, y) are re-pushed with num/16 and the callee places at x + off*num/16.
    return f"""
    cmp     dword ptr [g_hof_armed], 0
    je      hp_native
    mov     eax, dword ptr [{G_POPUP:#x}]
    mov     dword ptr [g_hof_gsave], eax
    mov     eax, dword ptr [g_hof_num]
    mov     dword ptr [{G_POPUP:#x}], eax
    push    16
    push    dword ptr [g_hof_num]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    call    {T_RWK_PARITY_NN:#x}
    push    eax
    mov     eax, dword ptr [g_hof_gsave]
    mov     dword ptr [{G_POPUP:#x}], eax
    pop     eax
    ret     0x10
hp_native:
    jmp     {BLIT_CORE:#x}
"""


def asm_hof_face() -> str:      # chain head @0x607F43 (Sprite_draw_2 contract): a HOF icon canvas at 1/1 -> parity NN at num/16, re-centred
    cat0, fac0 = HOF_CAT0 + 0x444, HOF_FAC0 + 0x444
    return f"""
    cmp     dword ptr [g_hof_armed], 0
    je      hf_chain
    cmp     dword ptr [esp+0x14], 1
    jne     hf_chain
    cmp     dword ptr [esp+0x18], 1
    jne     hf_chain
    push    edx
    push    ecx
    mov     eax, dword ptr [esp+0xC]
    sub     eax, {cat0:#x}
    jb      hf_fac
    cmp     eax, {HOF_CAT_N * HOF_BTN_STRIDE:#x}
    jb      hf_mod
hf_fac:
    mov     eax, dword ptr [esp+0xC]
    sub     eax, {fac0:#x}
    jb      hf_miss
    cmp     eax, {HOF_FAC_N * HOF_BTN_STRIDE:#x}
    jae     hf_miss
hf_mod:
    mov     ecx, {HOF_BTN_STRIDE:#x}
    xor     edx, edx
    div     ecx
    test    edx, edx
    jnz     hf_miss
    pop     ecx
    pop     edx
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    mov     esi, ecx
    mov     edi, dword ptr [ebp+0x14]
    mov     eax, dword ptr [esi+0x18]
    imul    eax, dword ptr [g_hof_num]
    sar     eax, 4
    mov     ebx, dword ptr [edi+0x80]
    sub     ebx, eax
    sar     ebx, 1
    mov     eax, dword ptr [esi+0x1C]
    imul    eax, dword ptr [g_hof_num]
    sar     eax, 4
    mov     ecx, dword ptr [edi+0x84]
    neg     ecx
    sub     ecx, eax
    sar     ecx, 1
    push    dword ptr [ebp+0x18]
    push    ecx
    push    ebx
    push    edi
    push    dword ptr [esi+0x14]
    push    dword ptr [esi+0x10]
    push    0
    push    0
    mov     eax, dword ptr [esi+0xC]
    test    eax, eax
    jg      hf_pitch
    mov     eax, dword ptr [esi+0x10]
hf_pitch:
    push    eax
    push    dword ptr [esi+4]
    call    t_hof_pairnn
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    ret     0x18
hf_miss:
    pop     ecx
    pop     edx
hf_chain:
    jmp     {T_RW_ICONBLIT:#x}
"""


# ---- v6: NN enlarge + pair-only restripe (scaling_laws.hof_pair_enlarge) ------------------------------------------
# t_hof_pairnn(sdata, spitch, sx, sy, sw, sh, destBuffer*, dx, dy, key) RET 0x28, stack args pushed right-to-left,
# preserves ebx/esi/edi/ebp.  dw/dh = floor(sw|sh * num/16) (g_hof_num); rows/cols nn_center_index; a texel with the
# same other index on both vertical neighbours and the alternation continuing one row further (b/a/b/a) is a row-pair
# member: the device pixel takes the BRIGHTER member (luma over the dest table +0xA4) on the wide phase rows
# ((y_abs) mod P < hN, y_abs = dest row + [destBuffer-0x304] = the window's y in its parent) and the other member
# otherwise.  Every other texel (1-px strokes, chamfers, glyph outlines) is plain edge-safe NN.  Key texels skipped.
def asm_hof_pairnn() -> str:
    # frame: -4 dw, -8 dh, -0xC P, -0x10 hN, -0x14 ddata, -0x18 dpitch, -0x1C dW, -0x20 dH, -0x24 pal, -0x28 yabs0,
    #        -0x2C j, -0x30 i, -0x34 srowabs, -0x38 wide, -0x3C drow ptr, -0x40 2*dw, -0x44 2*dh, -0x48 up, -0x4C dn,
    #        -0x50 mate
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x60
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [ebp+0x18]
    imul    eax, dword ptr [g_hof_num]
    sar     eax, 4
    mov     dword ptr [ebp-4], eax
    add     eax, eax
    mov     dword ptr [ebp-0x40], eax
    mov     eax, dword ptr [ebp+0x1C]
    imul    eax, dword ptr [g_hof_num]
    sar     eax, 4
    mov     dword ptr [ebp-8], eax
    add     eax, eax
    mov     dword ptr [ebp-0x44], eax
    cmp     dword ptr [ebp-4], 0
    jle     pn_done
    cmp     dword ptr [ebp-8], 0
    jle     pn_done
    cmp     dword ptr [ebp+0x18], 0
    jle     pn_done
    cmp     dword ptr [ebp+0x1C], 0
    jle     pn_done
    cmp     dword ptr [ebp+8], 0
    je      pn_done
    cmp     dword ptr [ebp+0xC], 0
    jle     pn_done
    mov     eax, dword ptr [g_hof_num]
    cmp     eax, 22                 ; T = stripe_rows(num): 1 below 22, else max(2, num >> 4); P = 2T
    sbb     edx, edx
    shr     eax, 4
    cmp     eax, 2
    adc     eax, edx
    mov     dword ptr [ebp-0x10], eax
    add     eax, eax
    mov     dword ptr [ebp-0xC], eax
    mov     esi, dword ptr [ebp+0x20]
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    jz      pn_done
    mov     dword ptr [ebp-0x14], eax
    mov     eax, dword ptr [esi+0x4A8]
    test    eax, eax
    jle     pn_done
    mov     dword ptr [ebp-0x18], eax
    mov     eax, dword ptr [esi+0x80]
    mov     dword ptr [ebp-0x1C], eax
    mov     eax, dword ptr [esi+0x84]
    neg     eax
    mov     dword ptr [ebp-0x20], eax
    lea     eax, [esi+0xA4]
    mov     dword ptr [ebp-0x24], eax
    mov     eax, dword ptr [esi-0x304]
    mov     dword ptr [ebp-0x28], eax
    mov     dword ptr [ebp-0x2C], 0
pn_row:
    mov     eax, dword ptr [ebp-0x2C]
    cmp     eax, dword ptr [ebp-8]
    jge     pn_done
    mov     ecx, dword ptr [ebp+0x28]
    add     ecx, eax
    js      pn_rownext
    cmp     ecx, dword ptr [ebp-0x20]
    jge     pn_rownext
    mov     edx, ecx
    imul    edx, dword ptr [ebp-0x18]
    add     edx, dword ptr [ebp-0x14]
    mov     dword ptr [ebp-0x3C], edx
    mov     eax, ecx
    add     eax, dword ptr [ebp-0x28]
    xor     edx, edx
    div     dword ptr [ebp-0xC]
    xor     eax, eax
    cmp     edx, dword ptr [ebp-0x10]
    setb    al
    mov     dword ptr [ebp-0x38], eax
    mov     eax, dword ptr [ebp-0x2C]
    add     eax, eax
    inc     eax
    mul     dword ptr [ebp+0x1C]
    div     dword ptr [ebp-0x44]
    mov     ecx, dword ptr [ebp+0x1C]
    dec     ecx
    cmp     eax, ecx
    jle     pn_rowok
    mov     eax, ecx
pn_rowok:
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [ebp-0x34], eax
    mov     dword ptr [ebp-0x30], 0
pn_col:
    mov     eax, dword ptr [ebp-0x30]
    cmp     eax, dword ptr [ebp-4]
    jge     pn_rownext
    mov     edi, dword ptr [ebp+0x24]
    add     edi, eax
    js      pn_colnext
    cmp     edi, dword ptr [ebp-0x1C]
    jge     pn_colnext
    add     edi, dword ptr [ebp-0x3C]
    add     eax, eax
    inc     eax
    mul     dword ptr [ebp+0x18]
    div     dword ptr [ebp-0x40]
    mov     ecx, dword ptr [ebp+0x18]
    dec     ecx
    cmp     eax, ecx
    jle     pn_colok
    mov     eax, ecx
pn_colok:
    add     eax, dword ptr [ebp+0x10]
    mov     esi, dword ptr [ebp-0x34]
    imul    esi, dword ptr [ebp+0xC]
    add     esi, eax
    add     esi, dword ptr [ebp+8]
    movzx   ebx, byte ptr [esi]
    cmp     ebx, dword ptr [ebp+0x2C]
    je      pn_colnext
    call    t_hof_pairfld
    test    eax, eax
    js      pn_store_a
    mov     dword ptr [ebp-0x50], eax
    push    eax
    push    dword ptr [ebp-0x24]
    call    t_hof_luma
    mov     dword ptr [ebp-0x54], eax
    push    ebx
    push    dword ptr [ebp-0x24]
    call    t_hof_luma
    cmp     eax, dword ptr [ebp-0x54]
    jg      pn_atop
    jl      pn_btop
    cmp     ebx, dword ptr [ebp-0x50]
    jle     pn_atop
pn_btop:
    mov     eax, dword ptr [ebp-0x50]
    mov     edx, ebx
    jmp     pn_pick
pn_atop:
    mov     eax, ebx
    mov     edx, dword ptr [ebp-0x50]
pn_pick:
    cmp     dword ptr [ebp-0x38], 0
    jne     pn_store
    mov     eax, edx
    jmp     pn_store
pn_store_a:
    mov     eax, ebx
pn_store:
    mov     byte ptr [edi], al
pn_colnext:
    inc     dword ptr [ebp-0x30]
    jmp     pn_col
pn_rownext:
    inc     dword ptr [ebp-0x2C]
    jmp     pn_row
pn_done:
    pop     edi
    pop     esi
    pop     ebx
    leave
    ret     0x28
"""


def asm_hof_pairtex() -> str:
    # in: esi = &texel, ebx = its index; reads the caller's frame (ebp): spitch [ebp+0xC], sy [ebp+0x14], sh [ebp+0x1C],
    # key [ebp+0x2C], srowabs [ebp-0x34]; scratch [ebp-0x48] up, [ebp-0x4C] dn.  out: eax = the pair mate or -1.
    # scaling_laws.hof_pair_texel: up == dn != a, neither the key, and up2 == a or dn2 == a (one-sided at the edges).
    return """
    push    ecx
    push    edx
    push    edi
    mov     ecx, dword ptr [ebp+0xC]
    mov     edx, dword ptr [ebp-0x34]
    sub     edx, dword ptr [ebp+0x14]
    cmp     edx, 3
    jl      pt_down
    neg     ecx
    call    pt_side
    neg     ecx
    cmp     eax, -1
    jne     pt_ret
pt_down:
    mov     edi, dword ptr [ebp+0x14]
    add     edi, dword ptr [ebp+0x1C]
    dec     edi
    sub     edi, dword ptr [ebp-0x34]
    cmp     edi, 3
    jl      pt_none
    call    pt_side
    jmp     pt_ret
pt_none:
    mov     eax, -1
pt_ret:
    pop     edi
    pop     edx
    pop     ecx
    ret
pt_side:
    movzx   eax, byte ptr [esi+ecx]
    cmp     eax, ebx
    je      ps_no
    cmp     eax, dword ptr [ebp+0x2C]
    je      ps_no
    lea     edx, [ecx+ecx]
    movzx   edi, byte ptr [esi+edx]
    cmp     edi, ebx
    jne     ps_no
    add     edx, ecx
    movzx   edi, byte ptr [esi+edx]
    cmp     edi, eax
    jne     ps_no
    ret
ps_no:
    mov     eax, -1
    ret
"""


def asm_hof_luma() -> str:
    # (pal, idx) RET 8: eax = b*114 + g*587 + r*299 of RGBQUAD pal[idx] (scaling_laws.mon_luma); clobbers ecx, edx
    return """
    mov     eax, dword ptr [esp+8]
    mov     ecx, dword ptr [esp+4]
    lea     ecx, [ecx+eax*4]
    movzx   eax, byte ptr [ecx]
    imul    eax, eax, 114
    movzx   edx, byte ptr [ecx+1]
    imul    edx, edx, 587
    add     eax, edx
    movzx   edx, byte ptr [ecx+2]
    imul    edx, edx, 299
    add     eax, edx
    ret     8
"""


# ---- v7 (2026-10-11): the hof.pcx field pair (scaling_laws.HOF_FIELD_PAIR; the CLOSE slot's channel rows) ----------
# Placed OUTSIDE the sequential mon block (pcave2 0x1AF00..0x1B000, reserved for this change) so no block offset moves:
# the backdrop site now enters t_hof_bd_field, which brackets g_hof_field around the unchanged t_hof_bd_hof; t_hof_pairnn
# calls t_hof_pairfld in place of t_hof_pairtex (same rel32 slot) = the chain test, then the field rule under the flag.
OFF_BD_FIELD, OFF_PAIRFLD, OFF_HOF_FIELD, OFF_PLACED_END = 0x1AF00, 0x1AF40, 0x1AFF0, 0x1B000


def asm_hof_bd_field() -> str:  # Buffer_copy_4 contract (ecx = src Buffer, 7 args, RET 0x1C): g_hof_field := 1 around t_hof_bd_hof
    return """
    mov     dword ptr [g_hof_field], 1
""" + "    push    dword ptr [esp+0x1C]\n" * 7 + """
    call    t_hof_bd_hof
    mov     dword ptr [g_hof_field], 0
    ret     0x1C
"""


def asm_hof_pairfld() -> str:
    # t_hof_pairtex's contract (esi = &texel, ebx = its index, ebp = t_hof_pairnn's frame; eax = mate or -1; ecx/edx/edi
    # preserved) + scaling_laws.hof_pair_texel's `field` clause: with g_hof_field set and no chain, a texel of the field
    # pair whose upper (then lower) neighbour inside [sy, sy + sh) is its mate is a member.
    fa, fb = SL.HOF_FIELD_PAIR
    return f"""
    call    t_hof_pairtex
    cmp     eax, -1
    jne     pf_ret
    cmp     dword ptr [g_hof_field], 0
    je      pf_ret
    cmp     ebx, {fa}
    je      pf_mate
    cmp     ebx, {fb}
    jne     pf_ret
pf_mate:
    push    ecx
    push    edx
    mov     edx, {fa + fb}
    sub     edx, ebx
    mov     ecx, dword ptr [ebp+0xC]
    mov     eax, dword ptr [ebp-0x34]
    cmp     eax, dword ptr [ebp+0x14]
    jle     pf_dn
    neg     ecx
    movzx   eax, byte ptr [esi+ecx]
    neg     ecx
    cmp     eax, edx
    je      pf_hit
pf_dn:
    mov     eax, dword ptr [ebp+0x14]
    add     eax, dword ptr [ebp+0x1C]
    dec     eax
    cmp     dword ptr [ebp-0x34], eax
    jge     pf_none
    movzx   eax, byte ptr [esi+ecx]
    cmp     eax, edx
    je      pf_hit
pf_none:
    mov     eax, -1
    pop     edx
    pop     ecx
    ret
pf_hit:
    mov     eax, edx
    pop     edx
    pop     ecx
pf_ret:
    ret
"""


PLACED_THUNKS = [("t_hof_bd_field", OFF_BD_FIELD, asm_hof_bd_field), ("t_hof_pairfld", OFF_PAIRFLD, asm_hof_pairfld)]
PLACED_CELLS = [("g_hof_field", OFF_HOF_FIELD, 4)]


HOF_CAT_N, HOF_FAC_N = SL.HOF_CAT_N, SL.HOF_FAC_N
HOF_THUNKS = [
    ("t_hof_build", asm_hof_build), ("t_hof_rects", asm_hof_rects), ("t_hof_icons", asm_hof_icons), ("t_hof_btn", asm_hof_btn),
    ("t_hof_fonts", asm_hof_fonts), ("t_hof_bd_frame", asm_hof_bd_frame), ("t_hof_bd_hof", asm_hof_bd_hof),
    ("t_hof_bd_map", asm_hof_bd_map), ("t_hof_spr_pic", asm_hof_spr_pic), ("t_hof_face", asm_hof_face),
    ("t_hof_pairnn", asm_hof_pairnn), ("t_hof_pairtex", asm_hof_pairtex), ("t_hof_luma", asm_hof_luma),
] + _hof_font_thunks()
HOF_DATA = [("g_hof_rects", hof_rects_table), ("g_hof_immtab", hof_immtab)]


def hof_site_list(names: dict[str, int]) -> list[dict]:
    S = []

    def add(sid, fn, va, orig, new, pattern, note="", group="hof_scale"):
        S.append({"id": sid, "group": group, "function": fn, "va": va, "orig": orig, "new": new, "pattern": pattern, "note": note})

    def redirect(sid, fn, va, native_target, thunk, note="", group="hof_scale"):
        orig = bytes([0xE8]) + struct.pack("<i", native_target - (va + 5))
        add(sid, fn, va, orig, f"E8 {{rel32:{thunk}}}", "call_target_redirect", note, group)

    def detour(sid, fn, va, ln, thunk, note=""):
        orig = SE.base_exe_bytes(va, ln)
        jmp = hx(bytes([0xE9]) + struct.pack("<i", names[thunk] - (va + 5)))
        add(sid, fn, va, orig, jmp + " 90" * (ln - 5), "detour_inplace", f"{note} (E9 -> {thunk})")

    redirect("hall_of_fame.load_hoficons", "hall_of_fame", HOF_CALL_SITE, LOAD_HOFICONS, "t_hof_build",
             "call load_hoficons (its one caller): builder, then the full-height letterbox levers (window, content rect, 6 rects, 13 icon buttons, CLOSE, fonts at num, row pitch, 23 painter imm rows)")
    redirect("FameWin_draw.frame_backdrop", "FameWin_draw", 0x448DFC, COPY4, "t_hof_bd_frame",
             "Buffer_copy_4 of frame.pcx 1024x768 1:1 -> Lanczos-3 + FS dither to the letterboxed s(1024) x s(768)")
    redirect("FameWin_draw.hof_backdrop", "FameWin_draw", 0x448E32, COPY4, "t_hof_bd_field",
             "Buffer_copy_4 of hof.pcx 800x600 1:1 at the content origin -> t_hof_bd_field (g_hof_field bracket) -> t_hof_bd_hof: edge-safe NN + pair restripe at num/16 with the hof.pcx field pair")
    redirect("FameWin_draw.world_map", "FameWin_draw", 0x448FCC, COPY4, "t_hof_bd_map",
             "Buffer_copy_4 of the score's 238x118 world-map pcx 1:1 -> resampled to the (device) map rect")
    redirect("FameWin_draw.faction_picture", "FameWin_draw", 0x449076, BLIT_CORE, "t_hof_spr_pic",
             "Sprite_blit_scaled_core 1:1 (233x124 faction picture, opaque) -> resampled s(233) x s(124)")
    for va, ln, reg, ti in HOF_FONT_SITES:
        detour(f"FameWin_draw.font_{va:x}", "FameWin_draw", va, ln, f"t_hof_font_{va:x}",
               f"mov {reg},[{HOF_FONT_TABLES[ti]:#x}] (f{SL.HOF_FONTS[ti]}) -> the num font when armed")
    redirect("FlatButton_content_draw.faction_dropdown_img", "FlatButton_content_draw", 0x607F43, 0x5E4B4A, "t_hof_face",
             "hof_scale head (chains to t_rw_iconblit): a HOF icon canvas at 1/1 -> parity NN at num/16, re-centred", group="faction_pickwin_buttons")
    return S


THUNKS.extend(HOF_THUNKS)
DATA.extend(HOF_DATA)
CELL_DEFS.extend(HOF_CELL_DEFS)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
