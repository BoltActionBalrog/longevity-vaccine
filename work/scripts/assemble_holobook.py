#!/usr/bin/env python
"""Assembler for the RETIREMENT HOLOBOOK bake (group holobook_scale, 2026-11-15): "Welcome to the Planetary Archives",
the end-of-game rating book quayle 0x496670 opens (Console_retire_game, end_of_game).  Static map + plan + the
user's decisions: work\\_hb_static_map.md.  Laws: scaling_laws "RETIREMENT HOLOBOOK" (hb_*).

Design = the full-screen menus' (Monument / Hall of Fame, user decision 2026-09-13): full-height 4:3, centred,
black letterbox, num = hb_scale_num = hof_scale_num over 16; armed only in the wide layout (0x8A4168) with num > 16,
else every thunk is the native path.  Holobook_g 0x872CB0 is a function-local static (canvas +0x444).

Levers (pcave2 0x44000..0x45FFF, reserved for this group):
  W/T/N  t_hb_build      call_target_redirect at quayle's `call Holobook_gwinit` @0x4966C8 (+ the uncalled
                         Holobook_open_item's @0x496621): the builder, then (ret 0, armed) the window resized to
                         the screen with the painter GATED (GraphicWin_resize repaints synchronously through
                         vtbl+0x30, and the static's page/tier are stale until quayle sets them after gwinit),
                         +0x13C/+0x474 := screen, clip + clear (black letterbox), content rect +0xA24, the 6 rects
                         of +0xA34 REBUILT from gwinit's literals (origin + s(lit)), CLOSE/BACK (t_hb_btn), the 4
                         painter fonts + their 4 vanilla shadows (t_hb_fonts), the 3 list imm8s (t_dl_immfix).
  -      t_hb_drawgate   detour @Holobook_draw 0x4956D0: ret while t_hb_build resizes (g_hb_building).
  B      t_hb_bd_frame   Buffer_copy_4 redirect @0x4957C7 (frame.pcx 1024x768 at (0,0)): t_mon_resample
                         (Lanczos-3 + FS; error-diffusion texture) to the letterbox.
         t_hb_bd_art     Buffer_copy_4 redirect @0x4957F7 (Holobook.pcx 800x600 at the content origin, 1-px
                         scanline field 54/187): t_hof_pairnn (edge-safe NN + pair-only restripe at the P law)
                         with g_hof_num := num and g_hof_field := the Holobook's own pair (HB_FIELD_PAIR) bracketed.
  G      t_hb_artbox     Buffer_draw redirect @0x495A35 (artbox<page>.pcx 420x520, scanline art on the key):
                         t_hof_pairnn at the device art rect, key kept, no field clause.
  F      t_hb_font_*     8 detours on the painter's `mov reg, [table]`: reg := the num font of that table
                         (Font_init at fl(snap(S) x num/16) on a private slot; user decision: the size vanilla
                         RENDERS, hb_font).
  W      t_hb_w_*        call_target_redirects of the painter's 6 wrap calls (title, both intros, the list's
                         measure + draw): g_hb_wrap_* armed around the call (scaled font, its vanilla shadow, the
                         vanilla width, the device width the call passes).
         t_hb_flb        detour @Font_find_line_break_l 0x619370: while g_hb_wrap_on and ecx == the armed font,
                         the word-fit runs with the SHADOW font against the VANILLA width (a continuation segment
                         resumes the native remainder) and hands back a device remainder -- vanilla's breaks
                         (user decision; hb_line_breaks), the draw still lays the lines out in the scaled font.
  C      t_hb_cap / t_hb_cap8  redirects at the 3 caption writers (@0x495B45 / @0x495C5F write_cent_l_7,
                         @0x495D5E wrap_cent_6): +0xA94 := hb_caption_rect(page) (the painter's imm8 heights
                         overflow a byte from num 25), page 8 also under the wrap bracket.
  N      t_hb_gate       chained in front of t_mon_gate (t_ntw_gate's tail push): admits CLOSE/BACK to the 2dzoom
                         chain when armed.
         t_hb_restripe   chained in front of t_mon_restripe at Buffer_draw_2 0x5D84C0: a CLOSE/BACK canvas ->
                         t_mon_face(buf, num) (red/black face pair, darker member on top).
Not levered: the GameLanguage != 0 ListBox list (it gets the scaled list rect and the scaled f11 through W/F).
Parity: tests\\test_holobook_asm_parity.py.  Sweep: tests\\test_scaling_holobook.py.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
OFF_CODE, OFF_LIMIT = 0x44000, 0x46000          # reserved for holobook_scale (the Replay group owns 0x46000..0x47FFF)
SECTION_LENGTH = 0x46000                       # pcave2 grown 0x44000 -> 0x46000 for this group (>=: later groups grow it)

# ---- engine VAs -------------------------------------------------------------------------------------------------
HB = 0x00872CB0                                # Holobook_g
HB_CLOSE, HB_BACK = HB + 0xAAC, HB + 0x15F8    # FlatButtons (window objects; canvas at +0x444)
GWINIT = 0x004951A0                            # Holobook_gwinit (fastcall this)
DRAW = 0x004956D0                              # Holobook_draw (vtbl+0x30, fastcall)
GW_RESIZE = 0x005D5540                         # thiscall(self, w, h, client) RET 0xC -- Win_resize(.., 1) repaints
GW_CLEAR = 0x005D5250                          # thiscall(self, color) RET 4 (fills the current clip)
SET_CLIP = 0x005D8000                          # thiscall(self, RECT*) RET 4
COPY4 = 0x005DFF00                             # Buffer_copy_4 thiscall(src; dest, sx, sy, dx, dy, w, h) RET 0x1C
BUFFER_DRAW = 0x005D8370                       # Buffer_draw thiscall(src; dest, key, x, y) RET 0x10
WRAP_CENT_4 = 0x005DD920                       # thiscall(str, x, y, w) RET 0x10
WRAP_CENT_6 = 0x005DDAB0                       # thiscall(str, RECT*) RET 8
WRAP_HEIGHT = 0x005DC360                       # thiscall(str, w) RET 8
WRAP_2 = 0x005DD530                            # thiscall(str, RECT*) RET 8
WRITE_CENT_L_7 = 0x005DD130                    # thiscall(str, RECT*, len) RET 0xC
FLB = 0x00619370                               # Font_find_line_break_l thiscall(ecx = Font; str, int* budget, len) RET 0xC
FLB_LEN = 7                                    # 83 EC 10 / 8B 44 24 18 (sub esp,0x10 / mov eax,[esp+0x18])
G_WRAP_USED = 0x009B3A9C                       # g_wrap_width_used (Font_find_line_break_l's running line width)
SW, SH = 0x009B7B1C, 0x009B7B20
WIDE = 0x008A4168
SCALE_UNIFORM = 0x00668200                     # eax = dim -> dim * min(W/1024, H/768) floored
# ---- shared cave symbols (other groups' thunks / cells; offsets from patches.yaml) --------------------------------
T_MON_RESAMPLE = PCAVE2 + 0x2BA20              # (sdata, spitch, sx, sy, sw, sh, dest, dx, dy, dw, dh) RET 0x2C
T_MON_GATE = PCAVE2 + 0x2B6D0
T_MON_RESTRIPE = PCAVE2 + 0x2B710
T_MON_FACE = PCAVE2 + 0x2B770                  # (buf, num) RET 8
T_HOF_PAIRNN = PCAVE2 + 0x2CB60                # (sdata, spitch, sx, sy, sw, sh, dest, dx, dy, key) RET 0x28
G_MON_LUT_OK = PCAVE2 + 0x2D3A4
G_HOF_NUM = PCAVE2 + 0x2D3A8
G_HOF_FIELD = PCAVE2 + 0x1AFF0
T_DL_IMMFIX = PCAVE2 + 0x22000                 # esi = row table (site, a, b, bits), 0-terminated
G_DL_IMMG = PCAVE2 + 0x27E10
T_FFN_AT = PCAVE2 + 0x2E490                    # cdecl (slot, S, v, num) -> slot: Font_init at fl(S*num/16), pool face
T_FDIRECT_AT = PCAVE2 + 0x2E4D0                # cdecl (slot, S, style, num) -> slot: "Arial" + own style
K_W4 = 1                                       # t_dl_immfix row bit: 4-byte operand (else imm8)

FONT_TABLES = tuple(SL.HB_FONT_TABLES)         # 0x8A40E4 / E8 / E0 / F0 -> cell index 0..3
FONT_SITES = (                                 # (va, len, reg, table): `mov reg, [table]` in Holobook_draw
    (0x00495754, 6, "ecx", 0x008A40E4), (0x0049584D, 5, "eax", 0x008A40E8), (0x00495B01, 6, "edx", 0x008A40E4),
    (0x00495C1B, 6, "ecx", 0x008A40F0), (0x00495D2E, 5, "eax", 0x008A40F0), (0x00495DF1, 5, "eax", 0x008A40E0),
    (0x00496068, 5, "eax", 0x008A40E0), (0x004962BD, 5, "eax", 0x008A40E8))
IMM_ROWS = ((0x00495E49, SL.HB_LIST_BOTTOM), (0x00495E4C, SL.HB_LIST_GAP), (0x00495FE4, SL.HB_LIST_GAP))
WRAP_SITES = (   # (site, thunk, target, kind, font table, vanilla width); kind = where the device width comes from
    (0x00495848, "t_hb_w_title", WRAP_CENT_4, "arg4", 0x008A40E4, SL.HB_WRAP_SITES[0x00495848][1]),
    (0x0049599F, "t_hb_w_intro", WRAP_CENT_4, "arg4", 0x008A40E8, SL.HB_WRAP_SITES[0x0049599F][1]),
    (0x00495DD4, "t_hb_w_intro", WRAP_CENT_4, "arg4", 0x008A40E8, SL.HB_WRAP_SITES[0x00495DD4][1]),
    (0x00495FBC, "t_hb_w_measure", WRAP_HEIGHT, "arg2", 0x008A40E0, SL.HB_LIST_WRAP_WIDTH),
    (0x0049601F, "t_hb_w_entry", WRAP_2, "rect2", 0x008A40E0, SL.HB_LIST_WRAP_WIDTH),
)
CAP_SITES = ((0x00495B45, "t_hb_cap", WRITE_CENT_L_7), (0x00495C5F, "t_hb_cap", WRITE_CENT_L_7),
             (0x00495D5E, "t_hb_cap8", WRAP_CENT_6))
CAP8_FONT, CAP8_WIDTH = 0x008A40F0, SL.HB_WRAP_SITES[0x00495D5E][1]

SLOT = 0x30                                    # t_ffn_at slot: Font 0x28 + num + key
CELL_DEFS = [("g_hb_num", 4), ("g_hb_armed", 4), ("g_hb_lx", 4), ("g_hb_ly", 4), ("g_hb_ox", 4), ("g_hb_oy", 4),
             ("g_hb_sw", 4), ("g_hb_sh", 4), ("g_hb_building", 4), ("g_hb_immg_save", 4), ("g_hb_hofnum_save", 4),
             ("g_hb_field_save", 4), ("g_hb_wrap_on", 4), ("g_hb_wrap_font", 4), ("g_hb_wrap_shadow", 4),
             ("g_hb_wrap_dev", 4), ("g_hb_wrap_nat", 4), ("g_hb_last_dev", 4), ("g_hb_last_nat", 4),
             ("g_hb_fonts", 16), ("g_hb_shadows", 16),
             ("g_hb_fslots", 4 * SLOT), ("g_hb_sslots", 4 * SLOT), ("g_hb_btnfont", SLOT)]


def HDN(reg: str) -> str:
    """reg = mon_s(reg) = half_down(reg * num, 16) with the Holobook's num."""
    return f"imul {reg}, dword ptr [g_hb_num]\n    lea {reg}, [{reg}*2+15]\n    sar {reg}, 5\n"


def fcell(table: int) -> str:
    return f"g_hb_fonts+{4 * FONT_TABLES.index(table)}"


def scell(table: int) -> str:
    return f"g_hb_shadows+{4 * FONT_TABLES.index(table)}"


# ---- data ---------------------------------------------------------------------------------------------------------
def rects_table() -> bytes:
    """g_hb_rects: gwinit's 24 content-relative literals in table order (+0xA34..+0xA93)."""
    return b"".join(struct.pack("<4i", *r) for r in SL.HB_RECT_LITERALS)


def caps_table() -> bytes:
    """g_hb_caps: pages 1, 2, 8 as content-relative (x0, y0, x0 + w, y0 + h)."""
    return b"".join(struct.pack("<4i", x0, y0, x0 + w, y0 + h) for x0, y0, w, h in (SL.HB_CAPTIONS[p] for p in (1, 2, 8)))


def immtab() -> bytes:
    """g_hb_immtab in t_dl_immfix's row format (site, a, b, bits): imm8 := s(a) - s(b); 0-terminated."""
    return b"".join(struct.pack("<IiiI", site, a, 0, 0) for site, a in IMM_ROWS) + b"\0" * 4


# ---- W/T/N: the build ---------------------------------------------------------------------------------------------
def asm_build() -> str:
    c = SL.HB_CONTENT_NATIVE
    # audit 2026-11-15: disarm BEFORE the builder -- gwinit repaints CLOSE/BACK at their native 120x20 (vtbl+0xF8 @0x495601
    # / @0x4956A6), and on a second open in one process (retire -> new game -> retire, Thinker's GAMEOVERMAN "continue")
    # a stale g_hb_armed sent those native canvases through t_hb_gate / t_hb_restripe at the old num.
    return f"""
    mov     dword ptr [g_hb_armed], 0
    call    {GWINIT:#x}
    test    eax, eax
    jnz     b_done
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     eax, dword ptr [{SH:#x}]
    mov     dword ptr [g_hb_sh], eax
    mov     ecx, dword ptr [{SW:#x}]
    mov     dword ptr [g_hb_sw], ecx
    mov     eax, {SL.NATIVE_G}
    call    {SCALE_UNIFORM:#x}
    cmp     eax, {SL.HOF_NUM_MAX}
    jle     b_cap
    mov     eax, {SL.HOF_NUM_MAX}
b_cap:
    mov     dword ptr [g_hb_num], eax
    cmp     eax, {SL.NATIVE_G}
    jle     b_native
    cmp     dword ptr [{WIDE:#x}], 0
    je      b_native
    mov     eax, 0x400
    {HDN('eax')}
    mov     ecx, dword ptr [g_hb_sw]
    sub     ecx, eax
    sar     ecx, 1
    mov     dword ptr [g_hb_lx], ecx
    mov     eax, 0x300
    {HDN('eax')}
    mov     ecx, dword ptr [g_hb_sh]
    sub     ecx, eax
    sar     ecx, 1
    mov     dword ptr [g_hb_ly], ecx
    mov     eax, {SL.HB_ORG_X}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_lx]
    mov     dword ptr [g_hb_ox], eax
    mov     eax, {SL.HB_ORG_Y}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_ly]
    mov     dword ptr [g_hb_oy], eax
    mov     dword ptr [{G_MON_LUT_OK:#x}], 0
    mov     esi, {HB:#x}
    mov     dword ptr [g_hb_building], 1
    push    1
    push    dword ptr [g_hb_sh]
    push    dword ptr [g_hb_sw]
    mov     ecx, esi
    call    {GW_RESIZE:#x}
    mov     dword ptr [g_hb_building], 0
    mov     dword ptr [g_hb_armed], 1
    xor     eax, eax
    mov     dword ptr [esi+0x13C], eax
    mov     dword ptr [esi+0x140], eax
    mov     dword ptr [esi+0x474], eax
    mov     dword ptr [esi+0x478], eax
    mov     eax, dword ptr [g_hb_sw]
    mov     dword ptr [esi+0x144], eax
    mov     dword ptr [esi+0x47C], eax
    mov     eax, dword ptr [g_hb_sh]
    mov     dword ptr [esi+0x148], eax
    mov     dword ptr [esi+0x480], eax
    lea     eax, [esi+0x474]
    push    eax
    lea     ecx, [esi+0x444]
    call    {SET_CLIP:#x}
    push    0
    mov     ecx, esi
    call    {GW_CLEAR:#x}
    mov     eax, {c[0]}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_lx]
    mov     dword ptr [esi+0xA24], eax
    mov     eax, {c[1]}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_ly]
    mov     dword ptr [esi+0xA28], eax
    mov     eax, {c[2]}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_lx]
    mov     dword ptr [esi+0xA2C], eax
    mov     eax, {c[3]}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_ly]
    mov     dword ptr [esi+0xA30], eax
    xor     ebx, ebx
    mov     edx, g_hb_rects
b_rect:
    mov     eax, dword ptr [edx+ebx*4]
    {HDN('eax')}
    test    ebx, 1
    jnz     b_ry
    add     eax, dword ptr [g_hb_ox]
    jmp     b_rst
b_ry:
    add     eax, dword ptr [g_hb_oy]
b_rst:
    mov     dword ptr [esi+ebx*4+{SL.HB_TABLE_OFF:#x}], eax
    inc     ebx
    cmp     ebx, 24
    jl      b_rect
    call    t_hb_fonts
    lea     edi, [esi+{HB_CLOSE - HB:#x}]
    call    t_hb_btn
    lea     edi, [esi+{HB_BACK - HB:#x}]
    call    t_hb_btn
    mov     eax, dword ptr [{G_DL_IMMG:#x}]
    mov     dword ptr [g_hb_immg_save], eax
    mov     eax, dword ptr [g_hb_num]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
    mov     esi, g_hb_immtab
    call    {T_DL_IMMFIX:#x}
    mov     eax, dword ptr [g_hb_immg_save]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
b_native:
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
b_done:
    ret
"""


def asm_btn() -> str:      # edi = FlatButton: resize to s(120) x s(20), move to (OX + s(0x289), OY + s(0x239)), label font, repaint
    l, t, r, b = SL.HB_RECT_LITERALS[SL.HB_BUTTON]
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    mov     eax, {r - l}
    {HDN('eax')}
    mov     dword ptr [ebp-4], eax
    mov     eax, {b - t}
    {HDN('eax')}
    mov     dword ptr [ebp-8], eax
    mov     eax, {l}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_ox]
    mov     dword ptr [ebp-0xC], eax
    mov     eax, {t}
    {HDN('eax')}
    add     eax, dword ptr [g_hb_oy]
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
    push    dword ptr [g_hb_num]
    push    1
    push    {SL.HB_FONT_LABEL}
    push    g_hb_btnfont
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


def asm_fonts() -> str:    # the 4 painter fonts at num (vanilla's snapped size) + their vanilla shadows (num 16)
    body = ""
    for k, table in enumerate(FONT_TABLES):
        s, v = SL.hb_font_native(table)
        for slots, cells, num in (("g_hb_fslots", "g_hb_fonts", "dword ptr [g_hb_num]"), ("g_hb_sslots", "g_hb_shadows", "16")):
            body += f"""
    push    {num}
    push    {v}
    push    {s}
    push    {slots}+{k * SLOT:#x}
    call    {T_FFN_AT:#x}
    add     esp, 16
    mov     dword ptr [{cells}+{4 * k}], eax
"""
    return body + "    ret\n"


def asm_drawgate() -> str:  # detour @Holobook_draw 0x4956D0 (55 8B EC 6A FF): no paint while t_hb_build resizes
    return f"""
    cmp     dword ptr [g_hb_building], 0
    jne     dg_skip
    push    ebp
    mov     ebp, esp
    push    -1
    jmp     {DRAW + 5:#x}
dg_skip:
    ret
"""


# ---- F: fonts -----------------------------------------------------------------------------------------------------
def asm_font(reg: str, table: int, resume: int) -> str:
    return f"""
    pushfd
    cmp     dword ptr [g_hb_armed], 0
    je      fd_native
    mov     {reg}, dword ptr [{fcell(table)}]
    popfd
    jmp     {resume:#x}
fd_native:
    mov     {reg}, dword ptr [{table:#x}]
    popfd
    jmp     {resume:#x}
"""


# ---- B / G: backdrops and the artbox --------------------------------------------------------------------------------
def asm_bd_frame() -> str:  # Buffer_copy_4 redirect: frame.pcx -> t_mon_resample to (LX + s(dx), LY + s(dy)) s(w) x s(h)
    return f"""
    cmp     dword ptr [g_hb_armed], 0
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
    add     eax, dword ptr [g_hb_ly]
    push    eax
    mov     eax, dword ptr [ebp+0x20]
    {HDN('eax')}
    add     eax, dword ptr [g_hb_lx]
    push    eax
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x2C]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [esi+0x4A8]
    push    dword ptr [esi+0x54]
    call    {T_MON_RESAMPLE:#x}
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


def _pair_bracket(field: int, push_args: str) -> str:
    """g_hof_num := num and g_hof_field := field around one t_hof_pairnn call (the HOF's cells, restored)."""
    return f"""
    mov     eax, dword ptr [{G_HOF_NUM:#x}]
    mov     dword ptr [g_hb_hofnum_save], eax
    mov     eax, dword ptr [g_hb_num]
    mov     dword ptr [{G_HOF_NUM:#x}], eax
    mov     eax, dword ptr [{G_HOF_FIELD:#x}]
    mov     dword ptr [g_hb_field_save], eax
    mov     dword ptr [{G_HOF_FIELD:#x}], {field:#x}
{push_args}
    call    {T_HOF_PAIRNN:#x}
    mov     eax, dword ptr [g_hb_hofnum_save]
    mov     dword ptr [{G_HOF_NUM:#x}], eax
    mov     eax, dword ptr [g_hb_field_save]
    mov     dword ptr [{G_HOF_FIELD:#x}], eax
"""


def asm_bd_art() -> str:    # Buffer_copy_4 redirect: Holobook.pcx 800x600 at the (device) content origin -> t_hof_pairnn
    args = f"""    push    {SL.HB_BLIT_KEY}
    push    dword ptr [ebp+0x24]
    push    dword ptr [ebp+0x20]
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x2C]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [esi+0x4A8]
    push    dword ptr [esi+0x54]"""
    return f"""
    cmp     dword ptr [g_hb_armed], 0
    je      ba_native
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    mov     esi, ecx
{_pair_bracket(SL.hof_field_cell(SL.HB_FIELD_PAIR), args)}
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
    ret     0x1C
ba_native:
    jmp     {COPY4:#x}
"""


def asm_artbox() -> str:    # Buffer_draw redirect (src; dest, key, x, y) RET 0x10: artbox<page>.pcx -> t_hof_pairnn at (x, y)
    args = """    push    dword ptr [ebp+0x18]
    push    dword ptr [ebp+0x20]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x14]
    mov     eax, dword ptr [esi+0x84]
    cdq
    xor     eax, edx
    sub     eax, edx
    push    eax
    push    dword ptr [esi+0x80]
    push    0
    push    0
    push    dword ptr [esi+0x4A8]
    push    dword ptr [esi+0x54]"""
    return f"""
    cmp     dword ptr [g_hb_armed], 0
    je      ab_native
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    mov     esi, ecx
{_pair_bracket(0, args)}
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    xor     eax, eax
    ret     0x10
ab_native:
    jmp     {BUFFER_DRAW:#x}
"""


# ---- W: vanilla line breaks -----------------------------------------------------------------------------------------
def asm_wrap(target: int, nargs: int, kind: str, table: int, nat_w: int) -> str:
    """call_target_redirect of one wrap call: arm g_hb_wrap_* around it (armed only), re-push the args, call, disarm."""
    if kind == "arg4":
        dev = "    mov     eax, dword ptr [esp+0x10]\n"
    elif kind == "arg2":
        dev = "    mov     eax, dword ptr [esp+8]\n"
    else:   # rect2: RECT* -> R - L
        dev = "    mov     eax, dword ptr [esp+8]\n    mov     edx, dword ptr [eax]\n    mov     eax, dword ptr [eax+8]\n    sub     eax, edx\n"
    repush = f"    push    dword ptr [esp+{4 * nargs:#x}]\n" * nargs
    return f"""
    cmp     dword ptr [g_hb_armed], 0
    je      w_plain
{dev}    mov     dword ptr [g_hb_wrap_dev], eax
    mov     dword ptr [g_hb_wrap_nat], {nat_w}
    mov     eax, dword ptr [{fcell(table)}]
    mov     dword ptr [g_hb_wrap_font], eax
    mov     eax, dword ptr [{scell(table)}]
    mov     dword ptr [g_hb_wrap_shadow], eax
    mov     dword ptr [g_hb_last_dev], -1
    mov     dword ptr [g_hb_wrap_on], 1
{repush}    call    {target:#x}
    mov     dword ptr [g_hb_wrap_on], 0
    ret     {4 * nargs:#x}
w_plain:
    jmp     {target:#x}
"""


def asm_flb() -> str:      # detour @Font_find_line_break_l: vanilla's break unless the scaled line would not fit
    # v2 (audit 2026-11-15): each piece is measured TWICE from the same g_wrap_width_used -- A: the vanilla (shadow) font
    # against the vanilla budget, B: the scaled font against the device budget (the engine's own call) -- and the line
    # breaks at the EARLIER of the two (law hb_line_breaks).  Vanilla's breaks stand wherever the scaled line fits; where
    # it would not (BOOKLIST4's "Superlubricant (But Were Afraid To" at num 19: 310 px in a 304 box) the engine's own
    # break wins, so a line never runs out of its box.  Both remainders carry over to a continuation segment
    # (g_hb_last_nat / g_hb_last_dev = the real device remainder); g_wrap_width_used is left as A left it.
    # On a break the returned *budget is B's remainder (the engine writes 0 there): every armed caller (wrap_height
    # 0x5DC360, wrap_2 0x5DD530, wrap_cent_4 0x5DD920, wrap_cent_6 0x5DDAB0, via 0x5DC410) resets the budget per line
    # and ignores it after a non-null return.
    # frame: [ebp+8] str, [ebp+0xC] budget*, [ebp+0x10] len; -4 dev_in, -8 nat_in, -0xC rA, -0x10 used
    return f"""
    cmp     dword ptr [g_hb_wrap_on], 0
    je      flb_native
    cmp     ecx, dword ptr [g_hb_wrap_font]
    jne     flb_native
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    push    ebx
    push    esi
    push    edi
    mov     ebx, ecx
    mov     esi, dword ptr [ebp+0xC]
    mov     eax, dword ptr [esi]
    mov     dword ptr [ebp-4], eax
    cmp     eax, dword ptr [g_hb_wrap_dev]
    jne     flb_cont
    mov     eax, dword ptr [g_hb_wrap_nat]
    jmp     flb_go
flb_cont:
    cmp     eax, dword ptr [g_hb_last_dev]
    jne     flb_bail
    mov     eax, dword ptr [g_hb_last_nat]
flb_go:
    mov     dword ptr [ebp-8], eax
    mov     eax, dword ptr [{G_WRAP_USED:#x}]
    mov     dword ptr [ebp-0x10], eax
    mov     eax, dword ptr [ebp-8]
    mov     dword ptr [esi], eax
    push    dword ptr [ebp+0x10]
    push    esi
    push    dword ptr [ebp+8]
    mov     ecx, dword ptr [g_hb_wrap_shadow]
    call    flb_tramp
    mov     dword ptr [ebp-0xC], eax
    mov     edi, dword ptr [esi]
    mov     eax, dword ptr [{G_WRAP_USED:#x}]
    xchg    eax, dword ptr [ebp-0x10]
    mov     dword ptr [{G_WRAP_USED:#x}], eax
    mov     eax, dword ptr [ebp-4]
    mov     dword ptr [esi], eax
    push    dword ptr [ebp+0x10]
    push    esi
    push    dword ptr [ebp+8]
    mov     ecx, ebx
    call    flb_tramp
    mov     ecx, dword ptr [ebp-0x10]
    mov     dword ptr [{G_WRAP_USED:#x}], ecx
    mov     edx, dword ptr [ebp-0xC]
    test    eax, eax
    jz      flb_a
    test    edx, edx
    jz      flb_out
    cmp     edx, eax
    jae     flb_out
flb_a:
    mov     eax, edx
flb_out:
    mov     dword ptr [g_hb_last_nat], edi
    mov     ecx, dword ptr [esi]
    mov     dword ptr [g_hb_last_dev], ecx
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0xC
flb_bail:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
flb_native:
flb_tramp:
    sub     esp, 0x10
    mov     eax, dword ptr [esp+0x18]
    jmp     {FLB + FLB_LEN:#x}
"""


# ---- C: caption rects -----------------------------------------------------------------------------------------------
def asm_caprect() -> str:   # esi = Holobook, eax = page: +0xA94 := hb_caption_rect(page) for pages 1 / 2 / 8, else untouched
    edges = ""
    for k, (reg_o) in enumerate(("g_hb_ox", "g_hb_oy", "g_hb_ox", "g_hb_oy")):
        edges += f"""
    mov     eax, dword ptr [edx+{4 * k}]
    {HDN('eax')}
    add     eax, dword ptr [{reg_o}]
    mov     dword ptr [esi+{0xA94 + 4 * k:#x}], eax
"""
    return f"""
    mov     edx, g_hb_caps
    cmp     eax, 1
    je      cr_go
    add     edx, 16
    cmp     eax, 2
    je      cr_go
    add     edx, 16
    cmp     eax, 8
    jne     cr_ret
cr_go:
{edges}
cr_ret:
    ret
"""


def asm_cap() -> str:       # redirect at the captions' write_cent_l_7 (pages 1, 2): fix the rect, tail-jump the writer
    return f"""
    cmp     dword ptr [g_hb_armed], 0
    je      cp_go
    pushad
    mov     eax, dword ptr [esi+0x2144]
    call    t_hb_caprect
    popad
cp_go:
    jmp     {WRITE_CENT_L_7:#x}
"""


def asm_cap8() -> str:      # redirect at the page-8 caption's wrap_cent_6: fix the rect, then the wrap bracket
    return f"""
    cmp     dword ptr [g_hb_armed], 0
    je      c8_plain
    pushad
    mov     eax, dword ptr [esi+0x2144]
    call    t_hb_caprect
    popad
    jmp     t_hb_w_cap8
c8_plain:
    jmp     {WRAP_CENT_6:#x}
"""


# ---- N: button gate / face restripe chains ---------------------------------------------------------------------------
def asm_gate() -> str:      # in front of t_mon_gate (esi = button; eax = admit)
    return f"""
    cmp     dword ptr [g_hb_armed], 0
    je      hg_chain
    cmp     esi, {HB_CLOSE:#x}
    je      hg_hit
    cmp     esi, {HB_BACK:#x}
    je      hg_hit
hg_chain:
    jmp     {T_MON_GATE:#x}
hg_hit:
    mov     eax, 1
    ret
"""


def asm_restripe() -> str:  # Buffer_draw_2 entry (ecx = src Buffer), in front of t_mon_restripe
    return f"""
    cmp     dword ptr [g_hb_armed], 0
    je      hr_chain
    cmp     ecx, {HB_CLOSE + 0x444:#x}
    je      hr_hit
    cmp     ecx, {HB_BACK + 0x444:#x}
    jne     hr_chain
hr_hit:
    pushad
    push    dword ptr [g_hb_num]
    push    ecx
    call    {T_MON_FACE:#x}
    popad
hr_chain:
    jmp     {T_MON_RESTRIPE:#x}
"""


def _font_thunks():
    return [(f"t_hb_font_{va:x}", (lambda r=reg, t=table, rs=va + ln: (lambda: asm_font(r, t, rs)))())
            for va, ln, reg, table in FONT_SITES]


def _wrap_thunks():
    seen, out = set(), []
    for _site, name, target, kind, table, w in WRAP_SITES:
        if name in seen:
            continue
        seen.add(name)
        nargs = 4 if target == WRAP_CENT_4 else 2
        out.append((name, (lambda a=(target, nargs, kind, table, w): (lambda: asm_wrap(*a)))()))
    out.append(("t_hb_w_cap8", lambda: asm_wrap(WRAP_CENT_6, 2, "rect2", CAP8_FONT, CAP8_WIDTH)))
    return out


# The two chain heads other assemblers pin by VA (assemble_ntw.T_HB_GATE, assemble_mon.T_HB_RESTRIPE) come FIRST so no
# growth of a later thunk ever moves them (test_holobook_asm_parity.test_chain_heads_point_into_this_block).
THUNKS = [("t_hb_gate", asm_gate), ("t_hb_restripe", asm_restripe),
          ("t_hb_build", asm_build), ("t_hb_btn", asm_btn), ("t_hb_fonts", asm_fonts), ("t_hb_drawgate", asm_drawgate),
          ("t_hb_bd_frame", asm_bd_frame), ("t_hb_bd_art", asm_bd_art), ("t_hb_artbox", asm_artbox),
          ("t_hb_flb", asm_flb), ("t_hb_caprect", asm_caprect), ("t_hb_cap", asm_cap), ("t_hb_cap8", asm_cap8)]     + _wrap_thunks() + _font_thunks()
DATA = [("g_hb_rects", rects_table), ("g_hb_caps", caps_table), ("g_hb_immtab", immtab)]


def _align(v: int, a: int = 16) -> int:
    return (v + a - 1) & ~(a - 1)


def assemble_all():
    """({name: (offset, bytes)}, cells {name: (offset, size)}, end offset, names {name: VA}); fixed-point layout."""
    names = {n: PCAVE2 + OFF_CODE for n, _ in THUNKS}
    names.update({n: PCAVE2 + OFF_CODE for n, _ in DATA})
    names.update({n: PCAVE2 + OFF_CODE for n, _ in CELL_DEFS})
    layout: dict[str, tuple[int, bytes]] = {}
    cells: dict[str, tuple[int, int]] = {}
    for _pass in range(12):
        off = OFF_CODE
        new_layout = {}
        for n, fn in THUNKS:
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
        new_names = {n: PCAVE2 + o for n, (o, _) in new_layout.items()}
        new_names.update({n: PCAVE2 + o for n, (o, _) in new_cells.items()})
        stable = new_names == names and all(layout.get(n, (0, None))[1] == b for n, (_, b) in new_layout.items())
        layout, cells, names = new_layout, new_cells, new_names
        if stable:
            break
    else:
        raise RuntimeError("layout did not converge")
    assert end <= OFF_LIMIT, f"holobook block ends {end:#x} > {OFF_LIMIT:#x}"
    return layout, cells, end, names


SYM_ABS = {T_MON_RESAMPLE: "t_mon_resample", T_MON_GATE: "t_mon_gate", T_MON_RESTRIPE: "t_mon_restripe",
           T_MON_FACE: "t_mon_face", T_HOF_PAIRNN: "t_hof_pairnn", G_MON_LUT_OK: "g_mon_lut_ok", G_HOF_NUM: "g_hof_num",
           G_HOF_FIELD: "g_hof_field", T_DL_IMMFIX: "t_dl_immfix", G_DL_IMMG: "g_dl_immg", T_FFN_AT: "t_ffn_at",
           T_FDIRECT_AT: "t_fdirect_at", SCALE_UNIFORM: "scale_uniform"}


def templatize(b: bytes, va: int, names: dict[str, int]) -> str:
    syms = dict(SYM_ABS)
    syms.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, syms)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- sites ----------------------------------------------------------------------------------------------------------
def site_list(names: dict[str, int]) -> list[dict]:
    S = []

    def add(sid, fn, va, orig, new, pattern, note):
        S.append({"id": sid, "group": "holobook_scale", "function": fn, "va": va, "orig": orig, "new": new,
                  "pattern": pattern, "note": note})

    def redirect(sid, fn, va, native_target, thunk, note):
        orig = bytes([0xE8]) + struct.pack("<i", native_target - (va + 5))
        add(sid, fn, va, orig, f"E8 {{rel32:{thunk}}}", "call_target_redirect", note)

    def detour(sid, fn, va, ln, thunk, note):
        orig = SE.base_exe_bytes(va, ln)
        jmp = hx(bytes([0xE9]) + struct.pack("<i", names[thunk] - (va + 5)))
        add(sid, fn, va, orig, jmp + " 90" * (ln - 5), "detour_inplace", f"{note} (E9 -> {thunk})")

    redirect("quayle.gwinit", "quayle", 0x4966C8, GWINIT, "t_hb_build",
             "call Holobook_gwinit -> the builder, then the full-height letterbox levers (window, rects, buttons, fonts, imm8s)")
    redirect("Holobook_open_item.gwinit", "Holobook_open_item", 0x496621, GWINIT, "t_hb_build",
             "call Holobook_gwinit (uncalled entry, same shape as quayle) -> t_hb_build")
    detour("Holobook_draw.paint_gate", "Holobook_draw", DRAW, 5, "t_hb_drawgate",
           "push ebp / mov ebp,esp / push -1 -> ret while t_hb_build resizes the window (stale page/tier)")
    redirect("Holobook_draw.frame_backdrop", "Holobook_draw", 0x4957C7, COPY4, "t_hb_bd_frame",
             "Buffer_copy_4 of frame.pcx 1024x768 1:1 at (0,0) -> Lanczos-3 + FS to the letterbox")
    redirect("Holobook_draw.art_backdrop", "Holobook_draw", 0x4957F7, COPY4, "t_hb_bd_art",
             "Buffer_copy_4 of Holobook.pcx 800x600 1:1 at the content origin -> pair-NN (field 64/197) at num/16")
    redirect("Holobook_draw.artbox", "Holobook_draw", 0x495A35, BUFFER_DRAW, "t_hb_artbox",
             "Buffer_draw of artbox<page>.pcx 420x520 (key 9) at the art rect -> pair-NN at num/16")
    for va, ln, reg, table in FONT_SITES:
        detour(f"Holobook_draw.font_{va:x}", "Holobook_draw", va, ln, f"t_hb_font_{va:x}",
               f"mov {reg},[{table:#x}] -> the num font (vanilla's snapped size x num/16) when armed")
    for site, name, target, _kind, _table, _w in WRAP_SITES:
        redirect(f"Holobook_draw.wrap_{site:x}", "Holobook_draw", site, target, name,
                 "wrap call -> vanilla's line breaks (word-fit measured with the vanilla font at the vanilla width)")
    for site, name, target in CAP_SITES:
        redirect(f"Holobook_draw.caption_{site:x}", "Holobook_draw", site, target, name,
                 "caption writer -> +0xA94 := hb_caption_rect(page) first")
    detour("Font_find_line_break_l.hb_vanilla_breaks", "Font_find_line_break_l", FLB, FLB_LEN, "t_hb_flb",
           "sub esp,0x10 / mov eax,[esp+0x18] -> while a Holobook wrap is armed: the vanilla font and width")
    return S


def verify_live(sites) -> list[str]:
    out = []
    for s in sites:
        got = SE.base_exe_bytes(s["va"], len(s["orig"]))
        if got != s["orig"]:
            out.append(f"{s['id']} @{s['va']:#x}: base {hx(got)} != expected {hx(s['orig'])}")
    return out


def site_yaml(sites) -> str:
    out = []
    for s in sites:
        new = s["new"]
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


def fragments():
    """(symbols lines, cave content lines, sites yaml) for patches.yaml."""
    layout, cells, end, names = assemble_all()
    sym, content = [], []
    for name, _fn in THUNKS:
        off, b = layout[name]
        sym.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # holobook_scale ({len(b)}B)")
        content.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, names)}\"")
    for name, _fn in DATA:
        off, b = layout[name]
        sym.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {len(b)} }}   # holobook_scale DATA")
        content.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{hx(b)}\"")
    for name, (off, size) in cells.items():
        sym.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    return sym, content, site_yaml(site_list(names)), end


def main(argv) -> int:
    layout, cells, end, names = assemble_all()
    ok = True
    print(f"; ==== retirement Holobook (assemble_holobook.py): block {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B), limit {OFF_LIMIT:#x}")
    for name, _fn in THUNKS:
        off, b = layout[name]
        print(f"; {name} @{off:#x} len {len(b)}")
    sites = site_list(names)
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    if "--fragments" in argv:
        sym, content, sy, _end = fragments()
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        for nm, txt in (("symbols", "\n".join(sym)), ("cave", "\n".join(content)), ("sites", sy)):
            with open(os.path.join(frag, f"_fragment_hb_{nm}.yaml"), "w", encoding="utf-8", newline="\n") as f:
                f.write(txt + "\n")
        print("; fragments written to work/patches/_fragment_hb_*.yaml")
    print(f"; sites: {len(sites)}")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
