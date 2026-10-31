#!/usr/bin/env python
"""Assembler for the SOCIAL ENGINEERING screen BAKE (group se_scale, 2026-08-25).

Ports the user-verified prototype hook_se_scale_proto.js v23 (4K + 1600 + 1920,
pixel-measured 2026-08-25) into pcave2 thunks.  Laws: scaling_laws.se_*
(se_modal_rects / se_console_rects / se_imm / se_font_size / se_sprite_canvas /
se_lock_plane_dims / se_tile_height / se_centre_map) + stripe_period/stripe_top
+ stroke_width; every value is scale_px (HALF-DOWN, the proto's s()) except the
FlatButton DIMS (popup_scale_floor, the shrink's exact inverse).

  thunk_se_enter      @ the 2 SocialWin_build callers (0x4BB3A9 / 0x5B565B, E8):
                      call thunk_se_immfix, then jmp SocialWin_build (ecx/stack
                      untouched -> thiscall RET 4 contract preserved).
  thunk_se_immfix     CALL helper: one-time VirtualProtect(0x4AF000, 0x5000) via the
                      kernel32 IAT (the scenedit/council bootstrap, shared strings),
                      then the 75 painter/builder immediates = s(A) - s(B) (identity
                      at g=16 -> vanilla restored on a res downgrade).  62 painter/
                      builder sites (the proto's 79 PATCHES less the 17 t_se_layout
                      owns since W5C: scaling_laws.SE_LAYOUT_IMMS) + 9 Font_init size
                      pushes + 2 font line-pad dwords + the 2 MOV-imm digit-w alias reads.
  thunk_se_transform  @0x4B338C (the builder's SocialWin_model_reset E8; the tables
                      are seeded natively just before, the 35 BaseButton_init run
                      after -> buttons are born scaled): modal table edges x g/16,
                      FlatButton floor dims, SOCIETY uniform pitch, panel-bottom /
                      SPARTANS anchoring (equal channels), console tables from the
                      region globals, then sprites / locks / tiles; jmp model_reset.
  thunk_se_sprites    100 sd2-fed sprite canvases (digits 10 @+0x2C60 + icons 90 @+0x2E18;
                      ctor: Sprite arrays at +0xB18*4/+0xB86*4/+0xF64*4/+0xF7A*4) x g/16 from
                      -- v2 FIX: v1 started at +0x2BB0 x104, i.e. 4 slots EARLY over the
                      scalar block +0x2BB0..+0x2C60 (allocation triple copies +0x2C38..) and
                      scaled two allocation values -> first chevron click jumped --
                      natives saved on the first run (g_se_sprsave; idempotent
                      across reopen AND a g change).
  thunk_se_locks      the 2 raw-blitted lock sprites: native struct saved/restored,
                      centre-NN plane into g_se_lockplane, even/odd-row pair mode
                      detection, P-law restripe with phase = the lock table top.
  thunk_se_tiles      the 6 slider tiles: pure-pair check + save on the first run,
                      Buffer_resize(W, 2P) + P-law stripe rows when H != 2P.
  thunk_se_sd2        the 5 Sprite_draw_2 sites: num=g, den=16, jmp sd2 (identity
                      at g<=16).
  thunk_se_rowdraw    SocialWin vtbl+0x14 (0x66DAB8 -> SocialWin_draw_society_row
                      0x4B17A0, fires per FlatButton draw after the face compose,
                      before the label): face pair family (174/238 | 224/225) from
                      one column, trailing KEY(9) row overdraw, P-law restripe, ring
                      pin to K (remainder law "pin chrome cells to K"); jmp 0x4B17A0.
  thunk_btn_gate_pre  v3 (RELOCATED 0x13760 -> tail): 22B HIT prefix for esi in
                      [SocialWin+0x6020, +35*0xB4C) = the 35 SE FlatButtons (faces
                      through the shrink/2D-zoom pipeline; no global flag, so the
                      MENU/COMMLINK MISS and the btntext_nudge exclusion the proto
                      needed are moot), then v2 VERBATIM.
  lever F direct:     11 modal-canvas Buffer_box_sprite sites -> thunk_box_thick_
                      hollow_flat (d5a0 x3) / thunk_box_thick_devfill (d618 x7 +
                      the builder's d690 backdrop); since W4C F42 (2026-10-25) each
                      through a half-open trimming helper (t_bm_ho_hf / t_bm_ho_df),
                      plus the master painter's OK-row union frame -> t_bm_ho_hf.
  static:             the 2 digit-w alias reads MOV r32,[EDI+0x2C70] -> MOV r32,imm32
                      (imm rewritten by the imm table).

Run:  py assemble_se.py               -> prints the yaml fragments + checks
      py assemble_se.py --fragments   -> writes work\\patches\\_fragment_se_*.yaml
Parity: tests\\test_se_asm_parity.py emulates these exact bytes.
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
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x1A000          # pcave2 grown 0x14000 -> 0x1A000 for this bake

# ---- engine / existing-cave anchors --------------------------------------
G            = 0x00668740   # g_popup_scale_num
OBJ          = 0x008A6270   # SocialWin (singleton)
REG          = 0x007AF5A0   # MainWin region rects (16 dwords, HUD-scaled)
SPR_STRIPES  = PCAVE2 + 0xF9E4   # t_spr_stripes (assemble_stripes_spr.py): Sprite_draw_2 drop-in, per-texel stripe regenerate
SD2          = 0x005E4B4A   # Sprite_draw_2 (thiscall; dest,key,x,y,num,den; RET 0x18)
MODEL_RESET  = 0x004AECE0   # SocialWin_model_reset
T_SE_LAYOUT  = 0xA0C000 + 0x3B040   # t_se_layout (assemble_halfopen_frames.SE_LAYOUT_OFF; W4C F42): btnrun's tail -> model_reset
BUILD        = 0x004B2740   # SocialWin_build (thiscall RET 4)
ROWDRAW      = 0x004B17A0   # SocialWin_draw_society_row (vtbl+0x14)
VTBL_SLOT    = 0x0066DAB8   # SocialWin vtable 0x66DAA4 + 0x14
BUF_RESIZE   = 0x005D79C0   # Buffer_resize thiscall (w, h POSITIVE) RET 8
BOX_SPRITE   = 0x005E2DD3
DEVFILL      = 0x00A102A0   # thunk_box_thick_devfill
HOLLOWFLAT   = 0x00A0C140   # thunk_box_thick_hollow_flat
BTN_GATE     = 0x00A169E0   # thunk_btn_gate (v8)
IAT_LOADLIB  = 0x00669120
IAT_GETPROC  = 0x00669124
STR_K32      = 0x00A1C6C0   # g_ed_str_k32 "KERNEL32.DLL"
STR_VP       = 0x00A1C6D0   # g_ed_str_vp  "VirtualProtect"
VP_PAGE      = 0x004AF000   # imm sites 0x4AF234..0x4B3315 -> 5 pages
VP_LEN       = 0x5000
PAGE_RWX     = 0x40
BTN_LO       = OBJ + 0x6020
BTN_HI       = BTN_LO + 35 * 0xB4C

# ---- new allocations (tail 0x14000..0x1A000, section grown) ---------------
OFF_G_SE_VPDONE   = 0x14000
OFF_G_SE_VPOLD    = 0x14004
OFF_G_SE_SPRG     = 0x14008   # g the sprite/lock/tile pass last ran for (0 = never)
OFF_G_SE_IMMTAB   = 0x14010   # 75*16+4 = 1204B -> 0x144C4 (92 entries until W5C)
OFF_G_SE_SPRSAVE  = 0x14600   # 100*8 canvas natives (0x320; v1 104) + 2*0x2C lock structs @+0x340 (0x58) + 6*2 tile pairs -> 0x149A4
SPR_BASE, SPR_N   = 0x2C60, 100   # SocialWin Sprite digits[10] + icons[90], contiguous 0x2C60..0x3D90 (locks follow)
OFF_G_SE_LOCKPLANE = 0x14A00  # 2 x 0x900 (s(24)*s(14) = 60*35 = 2100B max) -> 0x15C00
OFF_CODE          = 0x15C00
# 2026-10-11 parent-grid face phase: fixed slots outside the consecutive layout (cave_map --fit;
# 0x2FFA0..0x30000 between t_ml_textcolor and t_cav_blit).
OFF_SE_ROWDRAW_PH = 0x2FFA0
OFF_SE_STRIPE_PX_PH = 0x2FFE0
OFF_G_SE_YPH      = 0x2FFFC
OFF_SE_BTNRUN     = 0x30380   # 2026-10-11 even button channels: 0x30359..0x30700 free (t_rwk_con_lbr .. thunk_pf_frame_align)
G_STRIPE_PERIOD   = 0x0066879C   # g_stripe_period (P, law stripe_period)
SPRSAVE_LOCKS = 0x340
SPRSAVE_TILES = 0x398
LOCKPLANE_STRIDE = 0x900

G_SE_VPDONE   = PCAVE2 + OFF_G_SE_VPDONE
G_SE_VPOLD    = PCAVE2 + OFF_G_SE_VPOLD
G_SE_SPRG     = PCAVE2 + OFF_G_SE_SPRG
G_SE_IMMTAB   = PCAVE2 + OFF_G_SE_IMMTAB
G_SE_SPRSAVE  = PCAVE2 + OFF_G_SE_SPRSAVE
G_SE_LOCKPLANE = PCAVE2 + OFF_G_SE_LOCKPLANE
G_SE_YPH      = PCAVE2 + OFF_G_SE_YPH
from assemble_face_own import T_FACE_OWN  # noqa: E402  (W9A: own-top faces, pcave2 0x3E640)

# ---- the immediate table (the proto's PATCHES: [addr, immOff, width, a, b]) --
PATCHES = [
    # builder literals: window x-base / y-anchor / h / w pushes + backdrop L,R,B
    (0x4b3297, 1, 4, 0, 0x321), (0x4b32ae, 2, 4, 0x162, 0),
    (0x4b32d2, 1, 4, 0x162, 0), (0x4b32d7, 1, 4, 0x341, 0),
    (0x4b32fd, 3, 4, 0x17, 0), (0x4b3307, 3, 4, 0x30a, 0), (0x4b330e, 3, 4, 0x162, 0),
    # master painter union-frame outsets
    (0x4b1a08, 1, 4, 3, 0), (0x4b1a65, 1, 4, 3, 0),
    # society panel
    (0x4af234, 2, 1, 3, 0), (0x4af23d, 2, 1, 3, 0), (0x4af240, 2, 1, 3, 0),
    (0x4af246, 2, 1, 3, 0), (0x4af261, 2, 1, 0x17, 3),
    # band painter (incl. locked-row placeholder branch + icon advances)
    (0x4af36d, 2, 1, 3, 0), (0x4af376, 2, 1, 3, 0), (0x4af379, 2, 1, 3, 0),
    (0x4af37f, 2, 1, 3, 0), (0x4af39a, 2, 1, 0x17, 3), (0x4af489, 1, 4, 0x16, 0),
    (0x4af4ca, 2, 1, 0x16, 0), (0x4af4dd, 2, 1, 0x16, 0), (0x4af628, 2, 1, 1, 0),
    (0x4af7de, 3, 1, 1, 0), (0x4af858, 3, 1, 1, 0),
    # spartans box
    (0x4af915, 2, 1, 3, 0), (0x4af918, 2, 1, 3, 0), (0x4af91b, 2, 1, 3, 0),
    (0x4af927, 2, 1, 3, 0), (0x4af936, 2, 1, 0x17, 3), (0x4afa07, 2, 1, 0, 0x14),
    (0x4afa77, 2, 1, 2, 0),
    # center console
    (0x4afbb0, 2, 1, 0x14, 0), (0x4afc5f, 2, 1, 2, 0), (0x4afc81, 1, 4, 3, 0),
    # SOCIAL EFFECTS text
    (0x4b049b, 2, 1, 3, 0), (0x4b049e, 2, 1, 3, 0), (0x4b04ad, 2, 1, 3, 0),
    (0x4b04b8, 2, 1, 3, 0), (0x4b04bb, 2, 1, 0x17, 3), (0x4b0544, 2, 1, 2, 0),
    (0x4b0575, 2, 1, 0x14, 0), (0x4b057b, 2, 1, 0xF, 0x14), (0x4b0586, 2, 1, 3, 0),
    # hover panel
    (0x4b10dc, 2, 1, 3, 0), (0x4b10df, 2, 1, 3, 0), (0x4b10ee, 2, 1, 3, 0),
    (0x4b10f9, 2, 1, 3, 0), (0x4b10fc, 2, 1, 0x17, 3), (0x4b11c6, 2, 1, 2, 0),
    (0x4b11f4, 1, 4, 3, 0), (0x4b1465, 2, 1, 3, 0), (0x4b1696, 2, 1, 0x10, 0),
    (0x4b16b6, 3, 1, 0x10, 0), (0x4b1700, 1, 4, 0, 0x10),
    # button label draw -- DEVICE space
    (0x4b1866, 1, 1, 5, 0), (0x4b1898, 2, 1, 0x25, 0), (0x4b1956, 2, 1, 3, 0),
]
SLIDER_ROWS = [   # identical shapes at ECON/LABS/PSYCH addrs
    ((0x4b08f9, 0x4b0b59, 0x4b0da9), 2, 1, 3, 0),
    ((0x4b08fc, 0x4b0b5c, 0x4b0dac), 2, 1, 3, 0),
    ((0x4b0902, 0x4b0b62, 0x4b0db2), 2, 1, 0x1a, 3),
    ((0x4b0905, 0x4b0b65, 0x4b0db5), 2, 1, 3, 0),
    ((0x4b0919, 0x4b0b79, 0x4b0dc9), 2, 1, 3, 0),
    ((0x4b0927, 0x4b0b87, 0x4b0dd7), 2, 1, 0x1a, 3),
    ((0x4b092a, 0x4b0b8a, 0x4b0dda), 2, 1, 0x17, 3),
]
for _addrs, _off, _w, _a, _b in SLIDER_ROWS:
    for _addr in _addrs:
        PATCHES.append((_addr, _off, _w, _a, _b))
assert len(PATCHES) == 79
# 2026-10-25 W5C (F42 v3): the band / SOCIETY / SPARTANS title-band insets and heights, the row -> cell offset and the
# SPARTANS band insets are t_se_layout's (law scaling_laws.se_halfopen_imms: ONE rounding of every 20, one channel,
# one inset), written after this table on every build -- one owner per immediate, so they leave the table.
LAYOUT_OWNED = [p for p in PATCHES if p[0] + p[1] in SL.SE_LAYOUT_IMMS]
PATCHES = [p for p in PATCHES if p[0] + p[1] not in SL.SE_LAYOUT_IMMS]
assert len(LAYOUT_OWNED) == len(SL.SE_LAYOUT_IMMS) == 17 and len(PATCHES) == 62

FONT_SIZE_PUSHES = [   # (push imm8 site, native size) in Font_init call order F0..F8
    (0x4b2f98, 14), (0x4b2fbe, 14), (0x4b2fd4, 14), (0x4b2fea, 14), (0x4b2fff, 12),
    (0x4b301b, 11), (0x4b3039, 11), (0x4b3050, 14), (0x4b3066, 14),
]
FONT_PAD_SITES = [0x4b3025, 0x4b3043]          # mov dword ptr [edi], 3  (C7 07 imm32)
MOVIMM_SITES = [(0x4af7d8, 0xB8), (0x4af633, 0xBA)]   # 8B 87/97 70 2C 00 00 -> B8/BA imm32 90

# (site, A, B, kind): value = s(A) - s(B); kind bit0 = dword (else byte); static = the
# site's NATIVE byte is not A-B in the base exe (the two MOV-imm rewrites: base holds
# the MOV r32,[EDI+disp32] opcode; the static site patch installs imm 7 first).
IMMTAB = [(addr + off, a, b, 1 if w == 4 else 0, False) for addr, off, w, a, b in PATCHES]
KIND_FLOOR = 2   # = KIND_RAIL_L with b = 0: value = fl(a*g/16) (fonts v2 2026-09-17, law se_font_size)
IMMTAB += [(site + 1, sz, 0, KIND_FLOOR, False) for site, sz in FONT_SIZE_PUSHES]
IMMTAB += [(site + 2, 3, 0, 1, False) for site in FONT_PAD_SITES]
IMMTAB += [(site + 1, 7, 0, 1, True) for site, _opc in MOVIMM_SITES]
assert len(IMMTAB) == 75

# se_scale v2 (slide rails): the builder's d690 backdrop L/R (0x4B32FD+3 = 0x17, 0x4B3307+3 =
# 0x30A) ABUT the window's slide rails (L = rail width 15+8, R = W - 55 = rail start).  With the
# rail gate armed (SocialWin_show_hide.railarm_*) the rails scale through thunk_filedlg_railscale,
# so both imms follow the rails' OWN floor cascades (laws rail_left_extent / se_backdrop_rect):
#   kind bit1: value = fl(A*g/16) + fl(B*g/16)                      (A=15, B=8)
#   kind bit2: value = fl((fl(CEIL(A)*16/g) - B) * g/16)            (A=0x341 = the window w imm, B=55)
#   kind bit3: value = ceil(A*g/16) = (A*g+15)>>4                   (the GraphicWin_init width 0x341
#              @0x4B32D7+1: the unique device width whose railscale floor-descale is exactly 833 at
#              every g, so the right rails -- and R -- land on fl(778g/16); law se_window_w)
KIND_RAIL_L, KIND_RAIL_R, KIND_CEIL = 2, 4, 8
assert KIND_FLOOR == KIND_RAIL_L
IMMTAB = [(0x4B32FD + 3, 15, 8, 1 | KIND_RAIL_L, False) if site == 0x4B32FD + 3 else
          (0x4B3307 + 3, 0x341, 55, 1 | KIND_RAIL_R, False) if site == 0x4B3307 + 3 else
          (0x4B32D7 + 1, 0x341, 0, 1 | KIND_CEIL, False) if site == 0x4B32D7 + 1 else
          (site, a, b, kind, static) for site, a, b, kind, static in IMMTAB]
assert sum(1 for e in IMMTAB if e[3] & (KIND_RAIL_L | KIND_RAIL_R | KIND_CEIL)) == 3 + len(FONT_SIZE_PUSHES)


def imm_native(a: int, b: int, kind: int) -> int:
    """The site's native immediate (what the base exe holds) for a table entry."""
    return a + b if kind & KIND_RAIL_L else a - b


def immtab_bytes() -> bytes:
    out = bytearray()
    for site, a, b, kind, _static in IMMTAB:
        out += struct.pack("<IIII", site, a, b, kind)
    out += b"\x00\x00\x00\x00"
    return bytes(out)


# ---- asm helpers -------------------------------------------------------------
def HD(reg: str) -> str:
    """reg = scale_px(reg) = half_down(reg*g, 16) = floor((2*reg*g + 15) / 32)."""
    return f"imul {reg}, dword ptr [{G:#x}]\n    lea {reg}, [{reg}*2+15]\n    sar {reg}, 5\n"


def FL(reg: str) -> str:
    """reg = popup_scale_floor(reg) = floor(reg*g/16)."""
    return f"imul {reg}, dword ptr [{G:#x}]\n    sar {reg}, 4\n"


def CONST_HD(reg: str, v: int) -> str:
    return f"mov {reg}, {v}\n    {HD(reg)}"


def asm_se_enter() -> str:
    return f"""
    push    ecx
    call    thunk_se_immfix
    pop     ecx
    jmp     {BUILD:#x}
"""


def asm_se_immfix() -> str:
    return f"""
    push    esi
    cmp     dword ptr [{G_SE_VPDONE:#x}], 0
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
    push    {G_SE_VPOLD:#x}
    push    {PAGE_RWX:#x}
    push    {VP_LEN:#x}
    push    {VP_PAGE:#x}
    call    eax
    test    eax, eax
    je      bail
    mov     dword ptr [{G_SE_VPDONE:#x}], 1
imms:
    cmp     dword ptr [{G_SE_VPDONE:#x}], 0
    je      bail
    mov     esi, {G_SE_IMMTAB:#x}
nexte:
    mov     eax, dword ptr [esi]
    test    eax, eax
    je      bail
    test    dword ptr [esi+12], {KIND_RAIL_L}
    jne     kraill
    test    dword ptr [esi+12], {KIND_RAIL_R}
    jne     krailr
    test    dword ptr [esi+12], {KIND_CEIL}
    jne     kceil
    mov     ecx, dword ptr [esi+4]
    {HD("ecx")}
    mov     edx, dword ptr [esi+8]
    {HD("edx")}
    sub     ecx, edx
    jmp     store
kraill:
    mov     ecx, dword ptr [esi+4]
    {FL("ecx")}
    mov     edx, dword ptr [esi+8]
    {FL("edx")}
    add     ecx, edx
    jmp     store
kceil:
    mov     ecx, dword ptr [esi+4]
    imul    ecx, dword ptr [{G:#x}]
    add     ecx, 15
    sar     ecx, 4
    jmp     store
krailr:
    mov     eax, dword ptr [esi+4]
    imul    eax, dword ptr [{G:#x}]
    add     eax, 15
    sar     eax, 4
    shl     eax, 4
    cdq
    idiv    dword ptr [{G:#x}]
    sub     eax, dword ptr [esi+8]
    {FL("eax")}
    mov     ecx, eax
store:
    mov     eax, dword ptr [esi]
    test    dword ptr [esi+12], 1
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


def _inset_rect(src_off: int, dst_off: int) -> str:
    """dst = (src.L + s4, src.T + s4, src.R - s4, src.B - s4); ebx = s4, esi = obj."""
    return (f"    mov eax, dword ptr [{REG + src_off:#x}]\n    add eax, ebx\n    mov dword ptr [esi+{dst_off:#x}], eax\n"
            f"    mov eax, dword ptr [{REG + src_off + 4:#x}]\n    add eax, ebx\n    mov dword ptr [esi+{dst_off + 4:#x}], eax\n"
            f"    mov eax, dword ptr [{REG + src_off + 8:#x}]\n    sub eax, ebx\n    mov dword ptr [esi+{dst_off + 8:#x}], eax\n"
            f"    mov eax, dword ptr [{REG + src_off + 12:#x}]\n    sub eax, ebx\n    mov dword ptr [esi+{dst_off + 12:#x}], eax\n")


def _arrow(i: int, q_off: int) -> str:
    """arrow i from slider rect q (obj-relative offsets); locals: s3 [ebp+0xC], s17 [ebp+0x14]."""
    d = 0x1F000 + i * 0x10
    if i % 2 == 0:
        return (f"    mov eax, dword ptr [esi+{q_off:#x}]\n    add eax, dword ptr [ebp+0xC]\n    mov dword ptr [esi+{d:#x}], eax\n"
                f"    mov eax, dword ptr [esi+{q_off + 4:#x}]\n    add eax, dword ptr [ebp+0xC]\n    mov dword ptr [esi+{d + 4:#x}], eax\n"
                f"    mov eax, dword ptr [esi+{q_off:#x}]\n    add eax, dword ptr [ebp+0x14]\n    mov dword ptr [esi+{d + 8:#x}], eax\n"
                f"    mov eax, dword ptr [esi+{q_off + 4:#x}]\n    add eax, dword ptr [ebp+0x14]\n    mov dword ptr [esi+{d + 12:#x}], eax\n")
    return (f"    mov eax, dword ptr [esi+{q_off + 8:#x}]\n    sub eax, dword ptr [ebp+0x14]\n    mov dword ptr [esi+{d:#x}], eax\n"
            f"    mov eax, dword ptr [esi+{q_off + 4:#x}]\n    add eax, dword ptr [ebp+0xC]\n    mov dword ptr [esi+{d + 4:#x}], eax\n"
            f"    mov eax, dword ptr [esi+{q_off + 8:#x}]\n    sub eax, dword ptr [ebp+0xC]\n    mov dword ptr [esi+{d + 8:#x}], eax\n"
            f"    mov eax, dword ptr [esi+{q_off + 4:#x}]\n    add eax, dword ptr [ebp+0x14]\n    mov dword ptr [esi+{d + 12:#x}], eax\n")


def _lock(i: int, q_off: int) -> str:
    """lock i = (q.L + s3, q.B - s11, q.L + s1B, q.B - s3); locals s3 [ebp+0xC], s11 [ebp+0x18], s1B [ebp+0x1C]."""
    d = 0x1EFD0 + i * 0x10
    return (f"    mov eax, dword ptr [esi+{q_off:#x}]\n    add eax, dword ptr [ebp+0xC]\n    mov dword ptr [esi+{d:#x}], eax\n"
            f"    mov eax, dword ptr [esi+{q_off + 12:#x}]\n    sub eax, dword ptr [ebp+0x18]\n    mov dword ptr [esi+{d + 4:#x}], eax\n"
            f"    mov eax, dword ptr [esi+{q_off:#x}]\n    add eax, dword ptr [ebp+0x1C]\n    mov dword ptr [esi+{d + 8:#x}], eax\n"
            f"    mov eax, dword ptr [esi+{q_off + 12:#x}]\n    sub eax, dword ptr [ebp+0xC]\n    mov dword ptr [esi+{d + 12:#x}], eax\n")


SLD_E, SLD_L, SLD_P = 0x1F260, 0x1F270, 0x1F280


def asm_se_transform() -> str:
    # locals: [ebp+0]=h20 [+4]=w143 [+8]=s4 [+0xC]=s3 [+0x10]=s7 [+0x14]=s17 [+0x18]=s11 [+0x1C]=s1B
    #         [+0x20]=s6 [+0x24]=L [+0x28]=T [+0x2C]=Rr [+0x30]=B [+0x34]=colW
    arrows = "".join(_arrow(i, q) for i, q in enumerate((SLD_E, SLD_E, SLD_L, SLD_L, SLD_P, SLD_P)))
    locks = "".join(_lock(i, q) for i, q in enumerate((SLD_E, SLD_P, SLD_L)))
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    pushad
    sub     esp, 0x40
    mov     ebp, esp
    mov     esi, {OBJ:#x}
    lea     edi, [esi+0x1F060]
    mov     ecx, 124
e1:
    mov     eax, dword ptr [edi]
    {HD("eax")}
    mov     dword ptr [edi], eax
    add     edi, 4
    dec     ecx
    jnz     e1
    lea     edi, [esi+0x1F2A0]
    mov     ecx, 16
e2:
    mov     eax, dword ptr [edi]
    {HD("eax")}
    mov     dword ptr [edi], eax
    add     edi, 4
    dec     ecx
    jnz     e2
    mov     ebx, dword ptr [esi+0x1F074]
    {CONST_HD("edx", 22)}
    mov     ecx, 20
    {FL("ecx")}
    mov     dword ptr [ebp], ecx
    mov     eax, 143
    {FL("eax")}
    mov     dword ptr [ebp+4], eax
    lea     edi, [esi+0x1F070]
    mov     ecx, 10
r1:
    mov     eax, dword ptr [edi]
    add     eax, dword ptr [ebp+4]
    mov     dword ptr [edi+8], eax
    mov     dword ptr [edi+4], ebx
    mov     eax, ebx
    add     eax, dword ptr [ebp]
    mov     dword ptr [edi+0xC], eax
    add     ebx, edx
    add     edi, 0x10
    dec     ecx
    jnz     r1
    mov     edx, 146
    {FL("edx")}
    lea     edi, [esi+0x1F150]
    mov     ecx, 16
o1:
    mov     eax, dword ptr [edi]
    add     eax, edx
    mov     dword ptr [edi+8], eax
    mov     eax, dword ptr [edi+4]
    add     eax, dword ptr [ebp]
    mov     dword ptr [edi+0xC], eax
    add     edi, 0x10
    dec     ecx
    jnz     o1
    mov     edx, 162
    {FL("edx")}
    lea     edi, [esi+0x1F2B0]
    mov     ecx, 3
b1:
    mov     eax, dword ptr [edi]
    add     eax, edx
    mov     dword ptr [edi+8], eax
    mov     eax, dword ptr [edi+4]
    add     eax, dword ptr [ebp]
    mov     dword ptr [edi+0xC], eax
    add     edi, 0x10
    dec     ecx
    jnz     b1
    {CONST_HD("eax", 23)}
    add     eax, dword ptr [esi+0x1F064]
    mov     ebx, dword ptr [esi+0x1F074]
    sub     ebx, eax
    dec     ebx
    {CONST_HD("eax", 1)}
    dec     eax
    add     eax, ebx
    add     eax, dword ptr [esi+0x1F10C]
    mov     dword ptr [esi+0x1F06C], eax
    mov     ecx, dword ptr [esi+0x1F2AC]
    sub     ecx, dword ptr [esi+0x1F2A4]
    {CONST_HD("edx", 3)}
    lea     eax, [eax+edx+1]
    mov     dword ptr [esi+0x1F2A4], eax
    add     eax, ecx
    mov     dword ptr [esi+0x1F2AC], eax
    {CONST_HD("ebx", 4)}
    mov     dword ptr [ebp+8], ebx
    {CONST_HD("eax", 3)}
    mov     dword ptr [ebp+0xC], eax
    {CONST_HD("eax", 7)}
    mov     dword ptr [ebp+0x10], eax
    {CONST_HD("eax", 0x17)}
    mov     dword ptr [ebp+0x14], eax
    {CONST_HD("eax", 0x11)}
    mov     dword ptr [ebp+0x18], eax
    {CONST_HD("eax", 0x1B)}
    mov     dword ptr [ebp+0x1C], eax
    {CONST_HD("eax", 6)}
    mov     dword ptr [ebp+0x20], eax
{_inset_rect(0x10, 0x1F250)}
{_inset_rect(0x20, 0x1F2E0)}
    mov     ecx, dword ptr [ebp+0x10]
    mov     eax, dword ptr [{REG:#x}]
    add     eax, ecx
    mov     dword ptr [ebp+0x24], eax
    mov     eax, dword ptr [{REG + 0x34:#x}]
    add     eax, ecx
    mov     dword ptr [ebp+0x28], eax
    mov     eax, dword ptr [{REG + 0x38:#x}]
    sub     eax, ecx
    mov     dword ptr [ebp+0x2C], eax
    mov     eax, dword ptr [{REG + 0x3C:#x}]
    sub     eax, ecx
    mov     dword ptr [ebp+0x30], eax
    mov     eax, dword ptr [ebp+0x2C]
    sub     eax, dword ptr [ebp+0x24]
    sub     eax, ebx
    mov     ecx, 3
    cdq
    idiv    ecx
    sub     eax, dword ptr [ebp+0xC]
    mov     dword ptr [ebp+0x34], eax
    mov     eax, dword ptr [ebp+0x24]
    mov     dword ptr [esi+{SLD_E:#x}], eax
    mov     eax, dword ptr [ebp+0x28]
    mov     dword ptr [esi+{SLD_E + 4:#x}], eax
    mov     eax, dword ptr [ebp+0x24]
    add     eax, dword ptr [ebp+0x34]
    mov     dword ptr [esi+{SLD_E + 8:#x}], eax
    mov     eax, dword ptr [ebp+0x30]
    mov     dword ptr [esi+{SLD_E + 12:#x}], eax
    mov     eax, dword ptr [esi+{SLD_E + 8:#x}]
    add     eax, dword ptr [ebp+0xC]
    mov     dword ptr [esi+{SLD_P:#x}], eax
    mov     eax, dword ptr [ebp+0x28]
    mov     dword ptr [esi+{SLD_P + 4:#x}], eax
    mov     eax, dword ptr [esi+{SLD_P:#x}]
    add     eax, dword ptr [ebp+0x34]
    mov     dword ptr [esi+{SLD_P + 8:#x}], eax
    mov     eax, dword ptr [ebp+0x30]
    mov     dword ptr [esi+{SLD_P + 12:#x}], eax
    mov     eax, dword ptr [esi+{SLD_P + 8:#x}]
    add     eax, dword ptr [ebp+0xC]
    mov     dword ptr [esi+{SLD_L:#x}], eax
    mov     eax, dword ptr [ebp+0x28]
    mov     dword ptr [esi+{SLD_L + 4:#x}], eax
    mov     eax, dword ptr [ebp+0x2C]
    mov     dword ptr [esi+{SLD_L + 8:#x}], eax
    mov     eax, dword ptr [ebp+0x30]
    mov     dword ptr [esi+{SLD_L + 12:#x}], eax
    mov     eax, dword ptr [{REG:#x}]
    add     eax, ebx
    mov     dword ptr [esi+0x1F290], eax
    mov     eax, dword ptr [{REG + 4:#x}]
    add     eax, ebx
    mov     dword ptr [esi+0x1F294], eax
    mov     eax, dword ptr [{REG + 8:#x}]
    sub     eax, ebx
    mov     dword ptr [esi+0x1F298], eax
    mov     eax, dword ptr [ebp+0x28]
    sub     eax, dword ptr [ebp+0x20]
    mov     dword ptr [esi+0x1F29C], eax
{arrows}
{locks}
    call    thunk_se_sprites
    call    thunk_se_locks
    call    thunk_se_tiles
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{G_SE_SPRG:#x}], eax
    add     esp, 0x40
    popad
native:
    jmp     thunk_se_btnrun
"""


def asm_se_sprites() -> str:
    return f"""
    pushad
    mov     edi, {G_SE_SPRSAVE:#x}
    lea     ebx, [esi+{SPR_BASE:#x}]
    mov     ecx, {SPR_N}
s1:
    cmp     dword ptr [{G_SE_SPRG:#x}], 0
    jne     s2
    mov     eax, dword ptr [ebx+0x18]
    mov     dword ptr [edi], eax
    mov     eax, dword ptr [ebx+0x1C]
    mov     dword ptr [edi+4], eax
s2:
    mov     eax, dword ptr [edi]
    lea     edx, [eax-1]
    cmp     edx, 63
    ja      s3
    mov     edx, dword ptr [edi+4]
    dec     edx
    cmp     edx, 63
    ja      s3
    {HD("eax")}
    mov     dword ptr [ebx+0x18], eax
    mov     eax, dword ptr [edi+4]
    {HD("eax")}
    mov     dword ptr [ebx+0x1C], eax
s3:
    add     ebx, 0x2C
    add     edi, 8
    dec     ecx
    jnz     s1
    popad
    ret
"""


def asm_se_stripe_top() -> str:
    """eax = Y (>= 0) -> eax = 1 iff stripe_top(Y): (Y mod P) < (P+1)>>1, P = (g+4)>>3.
    Preserves ecx/edx/ebx/esi/edi."""
    return f"""
    push    ecx
    push    edx
    mov     ecx, dword ptr [{G:#x}]
    mov ecx, dword ptr [0x66879c]
    xor     edx, edx
    div     ecx
    inc     ecx
    shr     ecx, 1
    xor     eax, eax
    cmp     edx, ecx
    setb    al
    pop     edx
    pop     ecx
    ret
"""


def asm_se_tiles() -> str:
    # locals: [ebp]=TH [+4]=i [+8]=W [+0xC]=H [+0x10]=data [+0x14]=stride [+0x18]=pair(al=a, ah=b)
    return f"""
    pushad
    sub     esp, 0x20
    mov     ebp, esp
    mov     eax, dword ptr [{G:#x}]
    mov eax, dword ptr [0x66879c]
    nop
    add     eax, eax
    mov     dword ptr [ebp], eax
    mov     dword ptr [ebp+4], 0
t1:
    mov     ecx, dword ptr [ebp+4]
    imul    ebx, ecx, 0x588
    lea     ebx, [esi+ebx+0x3EF0]
    mov     edi, {G_SE_SPRSAVE + SPRSAVE_TILES:#x}
    add     edi, ecx
    add     edi, ecx
    mov     eax, dword ptr [ebx+0x80]
    test    eax, eax
    jle     tnext
    mov     dword ptr [ebp+8], eax
    mov     edx, dword ptr [ebx+0x84]
    neg     edx
    test    edx, edx
    jle     tnext
    mov     dword ptr [ebp+0xC], edx
    mov     eax, dword ptr [ebx+0x54]
    test    eax, eax
    je      tnext
    mov     dword ptr [ebp+0x10], eax
    mov     eax, dword ptr [ebx+0x4A8]
    mov     dword ptr [ebp+0x14], eax
    cmp     dword ptr [{G_SE_SPRG:#x}], 0
    jne     tsaved
    mov     word ptr [edi], 0xFFFF
    cmp     dword ptr [ebp+0xC], 3
    jl      tnext
    mov     edx, dword ptr [ebp+0x10]
    mov     ecx, dword ptr [ebp+0x14]
    mov     al, byte ptr [edx]
    mov     ah, byte ptr [edx+ecx]
    cmp     al, ah
    je      tnext
    lea     ecx, [ecx+ecx]
    cmp     byte ptr [edx+ecx], al
    jne     tnext
    mov     ecx, dword ptr [ebp+0x14]
    push    ebx
    xor     ebx, ebx
tp:
    cmp     byte ptr [edx+ebx], al
    jne     tbad
    push    edx
    add     edx, ecx
    cmp     byte ptr [edx+ebx], ah
    pop     edx
    jne     tbad
    inc     ebx
    cmp     ebx, dword ptr [ebp+8]
    jl      tp
    pop     ebx
    mov     word ptr [edi], ax
    jmp     tsaved
tbad:
    pop     ebx
    jmp     tnext
tsaved:
    movzx   eax, word ptr [edi]
    cmp     eax, 0xFFFF
    je      tnext
    mov     dword ptr [ebp+0x18], eax
    mov     eax, dword ptr [ebp+0xC]
    cmp     eax, dword ptr [ebp]
    je      tnext
    push    dword ptr [ebp]
    push    dword ptr [ebp+8]
    mov     ecx, ebx
    call    {BUF_RESIZE:#x}
    mov     edx, dword ptr [ebx+0x54]
    mov     dword ptr [ebp+0x10], edx
    mov     eax, dword ptr [ebx+0x4A8]
    mov     dword ptr [ebp+0x14], eax
    xor     ecx, ecx
tf:
    mov     eax, ecx
    call    thunk_se_stripe_top
    mov     edx, dword ptr [ebp+0x18]
    test    eax, eax
    jnz     tf2
    mov     dl, dh
tf2:
    mov     eax, ecx
    imul    eax, dword ptr [ebp+0x14]
    add     eax, dword ptr [ebp+0x10]
    push    ecx
    mov     ecx, dword ptr [ebp+8]
tf3:
    mov     byte ptr [eax], dl
    inc     eax
    dec     ecx
    jnz     tf3
    pop     ecx
    inc     ecx
    cmp     ecx, dword ptr [ebp]
    jl      tf
tnext:
    inc     dword ptr [ebp+4]
    cmp     dword ptr [ebp+4], 6
    jl      t1
    add     esp, 0x20
    popad
    ret
"""


def asm_se_locks() -> str:
    # locals: [ebp]=phaseY [+4]=i [+8]=sp [+0xC]=save [+0x10]=plane [+0x14]=src [+0x18]=pitch [+0x1C]=bw
    #  [+0x20]=bh [+0x24]=cw [+0x28]=ch [+0x2C]=key [+0x30]=w2 [+0x34]=h2 [+0x38]=cw2 [+0x3C]=ch2
    #  [+0x40]=rowBytes [+0x44]=srow [+0x48]=drow [+0x4C]=a [+0x50]=amax [+0x54]=atot [+0x58]=b
    #  [+0x5C]=bmax [+0x60]=btot [+0x64]=c ; histograms even @+0x80 odd @+0x480 (256 dwords each)
    def argmax(hist_off: int, out: int, outmax: int, outtot: int, lbl: str) -> str:
        return f"""
    lea     edi, [ebp+{hist_off:#x}]
    mov     dword ptr [ebp+{out:#x}], -1
    mov     dword ptr [ebp+{outmax:#x}], 0
    mov     dword ptr [ebp+{outtot:#x}], 0
    xor     ecx, ecx
{lbl}:
    mov     eax, dword ptr [edi+ecx*4]
    add     dword ptr [ebp+{outtot:#x}], eax
    cmp     eax, dword ptr [ebp+{outmax:#x}]
    jle     {lbl}n
    mov     dword ptr [ebp+{outmax:#x}], eax
    mov     dword ptr [ebp+{out:#x}], ecx
{lbl}n:
    inc     ecx
    cmp     ecx, 256
    jl      {lbl}
"""
    return f"""
    pushad
    sub     esp, 0x880
    mov     ebp, esp
    {CONST_HD("eax", 0x11)}
    mov     edx, dword ptr [esi+{SLD_E + 12:#x}]
    sub     edx, eax
    mov     dword ptr [ebp], edx
    mov     dword ptr [ebp+4], 0
l1:
    mov     ecx, dword ptr [ebp+4]
    imul    ebx, ecx, 0x2C
    lea     ebx, [esi+ebx+0x3D90]
    mov     dword ptr [ebp+8], ebx
    imul    edi, ecx, 0x2C
    add     edi, {G_SE_SPRSAVE + SPRSAVE_LOCKS:#x}
    mov     dword ptr [ebp+0xC], edi
    imul    eax, ecx, {LOCKPLANE_STRIDE:#x}
    add     eax, {G_SE_LOCKPLANE:#x}
    mov     dword ptr [ebp+0x10], eax
    cmp     dword ptr [{G_SE_SPRG:#x}], 0
    jne     l2
    push    esi
    mov     esi, ebx
    mov     ecx, 11
    rep     movsd dword ptr es:[edi], dword ptr [esi]
    pop     esi
l2:
    push    esi
    mov     edi, dword ptr [ebp+8]
    mov     esi, dword ptr [ebp+0xC]
    mov     ecx, 11
    rep     movsd dword ptr es:[edi], dword ptr [esi]
    pop     esi
    mov     ebx, dword ptr [ebp+8]
    mov     eax, dword ptr [ebx+4]
    test    eax, eax
    je      lnext
    mov     dword ptr [ebp+0x14], eax
    mov     eax, dword ptr [ebx+0xC]
    mov     dword ptr [ebp+0x18], eax
    lea     edx, [eax-1]
    cmp     edx, 4095
    ja      lnext
    mov     eax, dword ptr [ebx+0x10]
    mov     dword ptr [ebp+0x1C], eax
    lea     edx, [eax-1]
    cmp     edx, 63
    ja      lnext
    mov     eax, dword ptr [ebx+0x14]
    mov     dword ptr [ebp+0x20], eax
    lea     edx, [eax-1]
    cmp     edx, 63
    ja      lnext
    mov     eax, dword ptr [ebx+0x18]
    mov     dword ptr [ebp+0x24], eax
    lea     edx, [eax-1]
    cmp     edx, 63
    ja      lnext
    mov     eax, dword ptr [ebx+0x1C]
    mov     dword ptr [ebp+0x28], eax
    lea     edx, [eax-1]
    cmp     edx, 63
    ja      lnext
    movzx   eax, byte ptr [ebx+8]
    mov     dword ptr [ebp+0x2C], eax
    mov     eax, dword ptr [ebp+0x1C]
    {HD("eax")}
    mov     dword ptr [ebp+0x30], eax
    mov     eax, dword ptr [ebp+0x20]
    {HD("eax")}
    mov     dword ptr [ebp+0x34], eax
    mov     eax, dword ptr [ebp+0x24]
    {HD("eax")}
    mov     dword ptr [ebp+0x38], eax
    mov     eax, dword ptr [ebp+0x28]
    {HD("eax")}
    mov     dword ptr [ebp+0x3C], eax
    mov     eax, dword ptr [ebp+0x1C]
    cmp     eax, dword ptr [ebp+0x18]
    jle     rb
    mov     eax, dword ptr [ebp+0x18]
rb:
    mov     dword ptr [ebp+0x40], eax
    mov     edi, dword ptr [ebp+0x10]
    mov     eax, dword ptr [ebp+0x2C]
    mov     ecx, dword ptr [ebp+0x38]
    imul    ecx, dword ptr [ebp+0x3C]
    rep     stosb
    xor     ecx, ecx
ly:
    cmp     ecx, dword ptr [ebp+0x34]
    jge     ly_end
    lea     eax, [ecx*2+1]
    imul    eax, dword ptr [ebp+0x20]
    mov     edx, dword ptr [ebp+0x34]
    add     edx, edx
    push    ecx
    mov     ecx, edx
    xor     edx, edx
    div     ecx
    pop     ecx
    mov     edx, dword ptr [ebp+0x20]
    dec     edx
    cmp     eax, edx
    jle     sy_ok
    mov     eax, edx
sy_ok:
    imul    eax, dword ptr [ebp+0x18]
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [ebp+0x44], eax
    mov     eax, ecx
    imul    eax, dword ptr [ebp+0x38]
    add     eax, dword ptr [ebp+0x10]
    mov     dword ptr [ebp+0x48], eax
    xor     ebx, ebx
lx:
    cmp     ebx, dword ptr [ebp+0x30]
    jge     lx_end
    lea     eax, [ebx*2+1]
    imul    eax, dword ptr [ebp+0x1C]
    mov     edx, dword ptr [ebp+0x30]
    add     edx, edx
    push    ecx
    mov     ecx, edx
    xor     edx, edx
    div     ecx
    pop     ecx
    mov     edx, dword ptr [ebp+0x1C]
    dec     edx
    cmp     eax, edx
    jle     sx_ok
    mov     eax, edx
sx_ok:
    cmp     eax, dword ptr [ebp+0x40]
    jae     use_key
    mov     edx, dword ptr [ebp+0x44]
    movzx   eax, byte ptr [edx+eax]
    jmp     put
use_key:
    mov     eax, dword ptr [ebp+0x2C]
put:
    mov     edx, dword ptr [ebp+0x48]
    mov     byte ptr [edx+ebx], al
    inc     ebx
    jmp     lx
lx_end:
    inc     ecx
    jmp     ly
ly_end:
    lea     edi, [ebp+0x80]
    xor     eax, eax
    mov     ecx, 0x200
    rep     stosd
    xor     ecx, ecx
hy:
    cmp     ecx, dword ptr [ebp+0x20]
    jge     hy_end
    mov     eax, ecx
    imul    eax, dword ptr [ebp+0x18]
    add     eax, dword ptr [ebp+0x14]
    mov     dword ptr [ebp+0x44], eax
    lea     edi, [ebp+0x80]
    test    ecx, 1
    jz      h_even
    add     edi, 0x400
h_even:
    xor     ebx, ebx
hx:
    cmp     ebx, dword ptr [ebp+0x40]
    jge     hx_end
    mov     edx, dword ptr [ebp+0x44]
    movzx   eax, byte ptr [edx+ebx]
    cmp     eax, dword ptr [ebp+0x2C]
    je      hskip
    inc     dword ptr [edi+eax*4]
hskip:
    inc     ebx
    jmp     hx
hx_end:
    inc     ecx
    jmp     hy
hy_end:
{argmax(0x80, 0x4C, 0x50, 0x54, "am_e")}
{argmax(0x480, 0x58, 0x5C, 0x60, "am_o")}
    mov     eax, dword ptr [ebp+0x4C]
    cmp     eax, dword ptr [ebp+0x58]
    je      lfields
    test    eax, eax
    js      lfields
    cmp     dword ptr [ebp+0x58], 0
    jl      lfields
    mov     eax, dword ptr [ebp+0x50]
    lea     eax, [eax+eax*4]
    mov     edx, dword ptr [ebp+0x54]
    add     edx, edx
    cmp     eax, edx
    jl      lfields
    mov     eax, dword ptr [ebp+0x5C]
    lea     eax, [eax+eax*4]
    mov     edx, dword ptr [ebp+0x60]
    add     edx, edx
    cmp     eax, edx
    jl      lfields
    xor     ecx, ecx
ry:
    cmp     ecx, dword ptr [ebp+0x34]
    jge     lfields
    mov     eax, dword ptr [ebp]
    add     eax, ecx
    call    thunk_se_stripe_top
    mov     edx, dword ptr [ebp+0x4C]
    test    eax, eax
    jnz     rc
    mov     edx, dword ptr [ebp+0x58]
rc:
    mov     dword ptr [ebp+0x64], edx
    mov     eax, ecx
    imul    eax, dword ptr [ebp+0x38]
    add     eax, dword ptr [ebp+0x10]
    mov     dword ptr [ebp+0x48], eax
    xor     ebx, ebx
rx:
    cmp     ebx, dword ptr [ebp+0x30]
    jge     rx_end
    mov     edx, dword ptr [ebp+0x48]
    movzx   eax, byte ptr [edx+ebx]
    cmp     eax, dword ptr [ebp+0x4C]
    je      rw
    cmp     eax, dword ptr [ebp+0x58]
    jne     rn
rw:
    mov     eax, dword ptr [ebp+0x64]
    mov     byte ptr [edx+ebx], al
rn:
    inc     ebx
    jmp     rx
rx_end:
    inc     ecx
    jmp     ry
lfields:
    mov     ebx, dword ptr [ebp+8]
    mov     eax, dword ptr [ebp+0x10]
    mov     dword ptr [ebx+4], eax
    mov     eax, dword ptr [ebp+0x38]
    mov     dword ptr [ebx+0xC], eax
    mov     dword ptr [ebx+0x18], eax
    mov     eax, dword ptr [ebp+0x30]
    mov     dword ptr [ebx+0x10], eax
    mov     eax, dword ptr [ebp+0x34]
    mov     dword ptr [ebx+0x14], eax
    mov     eax, dword ptr [ebp+0x3C]
    mov     dword ptr [ebx+0x1C], eax
lnext:
    inc     dword ptr [ebp+4]
    cmp     dword ptr [ebp+4], 2
    jl      l1
    add     esp, 0x880
    popad
    ret
"""


def asm_se_sd2() -> str:
    return f"""
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [esp+0x14], eax
    mov     dword ptr [esp+0x18], 16
    jmp     {SPR_STRIPES:#x}
"""


# ---- row-draw restripe: shared-frame helpers (called ONLY from thunk_se_rowdraw,
# they read its locals through ebp): [ebp]=data [+4]=W [+8]=H [+0xC]=stride
# [+0x1C]=top [+0x20]=bot [+0x3C]=W-8 [+0x50]=H-8
def asm_se_rr_row() -> str:
    """eax = y -> eax = 1 iff >= 90% of x in [8, W-8) are NON-pair (a ring row)."""
    return f"""
    push    ecx
    push    edx
    push    ebx
    mov     edx, eax
    imul    edx, dword ptr [ebp+0xC]
    add     edx, dword ptr [ebp]
    xor     ebx, ebx
    mov     ecx, 8
rr1:
    movzx   eax, byte ptr [edx+ecx]
    cmp     eax, dword ptr [ebp+0x1C]
    je      rr2
    cmp     eax, dword ptr [ebp+0x20]
    je      rr2
    inc     ebx
rr2:
    inc     ecx
    cmp     ecx, dword ptr [ebp+0x3C]
    jl      rr1
    lea     ebx, [ebx+ebx*4]
    add     ebx, ebx
    mov     eax, dword ptr [ebp+4]
    sub     eax, 16
    lea     eax, [eax+eax*8]
    cmp     ebx, eax
    setge   al
    movzx   eax, al
    pop     ebx
    pop     edx
    pop     ecx
    ret
"""


def asm_se_rr_col() -> str:
    """eax = x -> eax = 1 iff >= 90% of y in [8, H-8) are NON-pair (a ring column)."""
    return f"""
    push    ecx
    push    edx
    push    ebx
    mov     edx, dword ptr [ebp]
    add     edx, eax
    mov     ecx, dword ptr [ebp+0xC]
    lea     edx, [edx+ecx*8]
    xor     ebx, ebx
    mov     ecx, 8
rc1:
    movzx   eax, byte ptr [edx]
    cmp     eax, dword ptr [ebp+0x1C]
    je      rc2
    cmp     eax, dword ptr [ebp+0x20]
    je      rc2
    inc     ebx
rc2:
    add     edx, dword ptr [ebp+0xC]
    inc     ecx
    cmp     ecx, dword ptr [ebp+0x50]
    jl      rc1
    lea     ebx, [ebx+ebx*4]
    add     ebx, ebx
    mov     eax, dword ptr [ebp+8]
    sub     eax, 16
    lea     eax, [eax+eax*8]
    cmp     ebx, eax
    setge   al
    movzx   eax, al
    pop     ebx
    pop     edx
    pop     ecx
    ret
"""


def asm_se_stripe_px() -> str:
    """eax = y -> al = the pair member for row y (top if stripe_top(y) else bot)."""
    return f"""
    call    thunk_se_stripe_top
    test    eax, eax
    mov     eax, dword ptr [ebp+0x1C]
    jnz     sp1
    mov     eax, dword ptr [ebp+0x20]
sp1:
    ret
"""


def _fill_rows(y0: str, y1: str, x0: str, x1: str, lbl: str) -> str:
    """for y in [y0,y1): for x in [x0,x1): px(y,x) = stripe_px(y).  Args are asm operands
    (locals / immediates); uses ecx=y, ebx=x, edi=row ptr, edx=colour."""
    return f"""
    mov     ecx, {y0}
{lbl}y:
    cmp     ecx, {y1}
    jge     {lbl}end
    mov     eax, ecx
    call    thunk_se_stripe_px
    mov     edx, eax
    mov     edi, ecx
    imul    edi, dword ptr [ebp+0xC]
    add     edi, dword ptr [ebp]
    mov     ebx, {x0}
{lbl}x:
    cmp     ebx, {x1}
    jge     {lbl}xe
    mov     byte ptr [edi+ebx], dl
    inc     ebx
    jmp     {lbl}x
{lbl}xe:
    inc     ecx
    jmp     {lbl}y
{lbl}end:
"""


def _copy_rows(y0: str, y1: str, src_y: str, lbl: str) -> str:
    """rows y in [y0,y1) = copy of row src_y (full width)."""
    return f"""
    mov     ecx, {y0}
{lbl}y:
    cmp     ecx, {y1}
    jge     {lbl}end
    mov     edi, ecx
    imul    edi, dword ptr [ebp+0xC]
    add     edi, dword ptr [ebp]
    mov     eax, {src_y}
    imul    eax, dword ptr [ebp+0xC]
    add     eax, dword ptr [ebp]
    push    esi
    push    ecx
    mov     esi, eax
    mov     ecx, dword ptr [ebp+4]
    rep     movsb
    pop     ecx
    pop     esi
    inc     ecx
    jmp     {lbl}y
{lbl}end:
"""


def _copy_cols(x0: str, x1: str, src_x: str, lbl: str) -> str:
    """cols x in [x0,x1) = copy of column src_x (all rows)."""
    return f"""
    mov     ebx, {x0}
{lbl}x:
    cmp     ebx, {x1}
    jge     {lbl}end
    mov     edi, dword ptr [ebp]
    mov     edx, {src_x}
    add     edx, dword ptr [ebp]
    mov     ecx, dword ptr [ebp+8]
{lbl}y:
    mov     al, byte ptr [edx]
    mov     byte ptr [edi+ebx], al
    add     edi, dword ptr [ebp+0xC]
    add     edx, dword ptr [ebp+0xC]
    dec     ecx
    jnz     {lbl}y
    inc     ebx
    jmp     {lbl}x
{lbl}end:
"""


def asm_se_rowdraw(phased: bool = True) -> str:
    """phased (2026-10-11, law scaling_laws.btn_face_stripe_phase): every stripe row goes through
    thunk_se_stripe_px_ph (y + g_se_yph) instead of thunk_se_stripe_px -- the same call width, so the
    body keeps its size and slot.  g_se_yph is staged per draw by thunk_se_rowdraw_ph, the vtable entry.
    assemble_dw.asm_dw_btnface derives its body from phased=True since 2026-10-14 (t_dw_face_ph stages the cell)."""
    # frame 0x60: [ebp]=data [+4]=W [+8]=H [+0xC]=stride [+0x10]=xcol [+0x14]=n1 [+0x18]=n2 [+0x1C]=top
    #  [+0x20]=bot [+0x24]=W-4 [+0x28]=9*(W-8) [+0x2C]=kb [+0x30]=srcrow [+0x34]=c [+0x38]=K [+0x3C]=W-8
    #  [+0x40]=dT [+0x44]=dB [+0x48]=dL [+0x4C]=dR [+0x50]=H-8 [+0x54]=W-K [+0x58]=H-K [+0x5C]=tmp
    src = f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    pushad
    sub     esp, 0x60
    mov     ebp, esp
    mov     ebx, dword ptr [esp+0x84]
    lea     ebx, [ebx+0x444]
    mov     edi, dword ptr [ebx+0x54]
    test    edi, edi
    je      done
    mov     dword ptr [ebp], edi
    mov     eax, dword ptr [ebx+0x80]
    test    eax, eax
    jle     done
    mov     dword ptr [ebp+4], eax
    mov     eax, dword ptr [ebx+0x84]
    neg     eax
    test    eax, eax
    jle     done
    mov     dword ptr [ebp+8], eax
    mov     eax, dword ptr [ebx+0x4A8]
    cmp     eax, dword ptr [ebp+4]
    jl      done
    mov     dword ptr [ebp+0xC], eax
    mov     eax, dword ptr [ebp+4]
    shr     eax, 2
    cmp     eax, 1
    jge     f1
    mov     eax, 1
f1:
    mov     edx, dword ptr [ebp+4]
    sub     edx, 2
    cmp     eax, edx
    jle     f2
    mov     eax, edx
f2:
    mov     dword ptr [ebp+0x10], eax
    mov     dword ptr [ebp+0x14], 0
    mov     dword ptr [ebp+0x18], 0
    xor     ecx, ecx
fy:
    cmp     ecx, dword ptr [ebp+8]
    jge     fy_end
    mov     eax, ecx
    imul    eax, dword ptr [ebp+0xC]
    add     eax, dword ptr [ebp]
    add     eax, dword ptr [ebp+0x10]
    movzx   eax, byte ptr [eax]
    cmp     eax, 174
    je      n1
    cmp     eax, 238
    je      n1
    cmp     eax, 224
    je      n2
    cmp     eax, 225
    jne     fn
n2:
    inc     dword ptr [ebp+0x18]
    jmp     fn
n1:
    inc     dword ptr [ebp+0x14]
fn:
    inc     ecx
    jmp     fy
fy_end:
    mov     eax, dword ptr [ebp+0x14]
    mov     edx, dword ptr [ebp+0x18]
    mov     dword ptr [ebp+0x1C], 174
    mov     dword ptr [ebp+0x20], 238
    cmp     eax, edx
    jge     fsel
    mov     eax, edx
    mov     dword ptr [ebp+0x1C], 224
    mov     dword ptr [ebp+0x20], 225
fsel:
    lea     eax, [eax+eax*4]
    mov     edx, dword ptr [ebp+8]
    lea     edx, [edx+edx*2]
    cmp     eax, edx
    jl      done
    mov     eax, dword ptr [ebp+4]
    sub     eax, 4
    mov     dword ptr [ebp+0x24], eax
    sub     eax, 4
    lea     eax, [eax+eax*8]
    mov     dword ptr [ebp+0x28], eax
    xor     ecx, ecx
ok1:
    cmp     ecx, 2
    jge     ok_end
    mov     eax, dword ptr [ebp+8]
    dec     eax
    sub     eax, ecx
    jle     ok_end
    mov     edx, eax
    imul    edx, dword ptr [ebp+0xC]
    add     edx, dword ptr [ebp]
    push    ecx
    mov     ecx, 4
    xor     ebx, ebx
rk:
    cmp     byte ptr [edx+ecx], 9
    jne     rk1
    inc     ebx
rk1:
    inc     ecx
    cmp     ecx, dword ptr [ebp+0x24]
    jl      rk
    pop     ecx
    lea     ebx, [ebx+ebx*4]
    add     ebx, ebx
    cmp     ebx, dword ptr [ebp+0x28]
    jl      ok_end
    inc     ecx
    jmp     ok1
ok_end:
    mov     dword ptr [ebp+0x2C], ecx
    test    ecx, ecx
    jz      rs0
    mov     eax, dword ptr [ebp+8]
    dec     eax
    sub     eax, ecx
    mov     dword ptr [ebp+0x30], eax
    mov     eax, dword ptr [ebp+8]
    sub     eax, ecx
    mov     dword ptr [ebp+0x5C], eax
{_copy_rows("dword ptr [ebp+0x5C]", "dword ptr [ebp+8]", "dword ptr [ebp+0x30]", "oc")}
rs0:
    xor     ecx, ecx
sy:
    cmp     ecx, dword ptr [ebp+8]
    jge     sy_end
    mov     eax, ecx
    call    thunk_se_stripe_px
    mov     dword ptr [ebp+0x34], eax
    mov     edi, ecx
    imul    edi, dword ptr [ebp+0xC]
    add     edi, dword ptr [ebp]
    xor     ebx, ebx
sx:
    cmp     ebx, dword ptr [ebp+4]
    jge     sx_end
    movzx   eax, byte ptr [edi+ebx]
    cmp     eax, dword ptr [ebp+0x1C]
    je      sw
    cmp     eax, dword ptr [ebp+0x20]
    jne     sn
sw:
    mov     eax, dword ptr [ebp+0x34]
    mov     byte ptr [edi+ebx], al
sn:
    inc     ebx
    jmp     sx
sx_end:
    inc     ecx
    jmp     sy
sy_end:
    {CONST_HD("eax", 1)}
    mov     dword ptr [ebp+0x38], eax
    cmp     dword ptr [ebp+4], 32
    jl      done
    cmp     dword ptr [ebp+8], 32
    jl      done
    mov     eax, dword ptr [ebp+4]
    sub     eax, 8
    mov     dword ptr [ebp+0x3C], eax
    mov     eax, dword ptr [ebp+8]
    sub     eax, 8
    mov     dword ptr [ebp+0x50], eax
    mov     eax, dword ptr [ebp+4]
    sub     eax, dword ptr [ebp+0x38]
    mov     dword ptr [ebp+0x54], eax
    mov     eax, dword ptr [ebp+8]
    sub     eax, dword ptr [ebp+0x38]
    mov     dword ptr [ebp+0x58], eax
    xor     ecx, ecx
dtop:
    cmp     ecx, 8
    jge     dtop_end
    mov     eax, ecx
    call    thunk_se_rr_row
    test    eax, eax
    jz      dtop_end
    inc     ecx
    jmp     dtop
dtop_end:
    mov     dword ptr [ebp+0x40], ecx
    xor     ecx, ecx
dbot:
    cmp     ecx, 8
    jge     dbot_end
    mov     eax, dword ptr [ebp+8]
    dec     eax
    sub     eax, ecx
    call    thunk_se_rr_row
    test    eax, eax
    jz      dbot_end
    inc     ecx
    jmp     dbot
dbot_end:
    mov     dword ptr [ebp+0x44], ecx
    xor     ecx, ecx
dlef:
    cmp     ecx, 8
    jge     dlef_end
    mov     eax, ecx
    call    thunk_se_rr_col
    test    eax, eax
    jz      dlef_end
    inc     ecx
    jmp     dlef
dlef_end:
    mov     dword ptr [ebp+0x48], ecx
    xor     ecx, ecx
drig:
    cmp     ecx, 8
    jge     drig_end
    mov     eax, dword ptr [ebp+4]
    dec     eax
    sub     eax, ecx
    call    thunk_se_rr_col
    test    eax, eax
    jz      drig_end
    inc     ecx
    jmp     drig
drig_end:
    mov     dword ptr [ebp+0x4C], ecx
    mov     eax, dword ptr [ebp+0x40]
    or      eax, dword ptr [ebp+0x44]
    or      eax, dword ptr [ebp+0x48]
    or      eax, dword ptr [ebp+0x4C]
    jz      done
{_fill_rows("dword ptr [ebp+0x38]", "dword ptr [ebp+0x40]", "dword ptr [ebp+0x38]", "dword ptr [ebp+0x54]", "tt")}
    mov     eax, dword ptr [ebp+8]
    sub     eax, dword ptr [ebp+0x44]
    mov     dword ptr [ebp+0x5C], eax
{_fill_rows("dword ptr [ebp+0x5C]", "dword ptr [ebp+0x58]", "dword ptr [ebp+0x38]", "dword ptr [ebp+0x54]", "tb")}
{_fill_rows("dword ptr [ebp+0x38]", "dword ptr [ebp+0x58]", "dword ptr [ebp+0x38]", "dword ptr [ebp+0x48]", "tl")}
    mov     eax, dword ptr [ebp+4]
    sub     eax, dword ptr [ebp+0x4C]
    mov     dword ptr [ebp+0x5C], eax
{_fill_rows("dword ptr [ebp+0x38]", "dword ptr [ebp+0x58]", "dword ptr [ebp+0x5C]", "dword ptr [ebp+0x54]", "tr")}
    mov     eax, dword ptr [ebp+0x40]
    test    eax, eax
    jz      gb
    cmp     eax, dword ptr [ebp+0x38]
    jge     gb
    dec     eax
    mov     dword ptr [ebp+0x5C], eax
{_copy_rows("dword ptr [ebp+0x40]", "dword ptr [ebp+0x38]", "dword ptr [ebp+0x5C]", "gtr")}
gb:
    mov     eax, dword ptr [ebp+0x44]
    test    eax, eax
    jz      gl
    cmp     eax, dword ptr [ebp+0x38]
    jge     gl
    mov     edx, dword ptr [ebp+8]
    sub     edx, eax
    mov     dword ptr [ebp+0x5C], edx
{_copy_rows("dword ptr [ebp+0x58]", "dword ptr [ebp+0x5C]", "dword ptr [ebp+0x5C]", "gbr")}
gl:
    mov     eax, dword ptr [ebp+0x48]
    test    eax, eax
    jz      gr
    cmp     eax, dword ptr [ebp+0x38]
    jge     gr
    dec     eax
    mov     dword ptr [ebp+0x5C], eax
{_copy_cols("dword ptr [ebp+0x48]", "dword ptr [ebp+0x38]", "dword ptr [ebp+0x5C]", "glc")}
gr:
    mov     eax, dword ptr [ebp+0x4C]
    test    eax, eax
    jz      done
    cmp     eax, dword ptr [ebp+0x38]
    jge     done
    mov     edx, dword ptr [ebp+4]
    sub     edx, eax
    mov     dword ptr [ebp+0x5C], edx
{_copy_cols("dword ptr [ebp+0x54]", "dword ptr [ebp+0x5C]", "dword ptr [ebp+0x5C]", "grc")}
done:
    add     esp, 0x60
    popad
native:
    jmp     {ROWDRAW:#x}
"""
    if not phased:
        return src
    call = "call    thunk_se_stripe_px\n"
    assert src.count(call) == 5, "asm_se_rowdraw stripe_px call census changed"
    return src.replace(call, "call    thunk_se_stripe_px_ph\n")


def asm_se_rowdraw_ph(own: bool = True) -> str:
    """The SocialWin vtbl+0x14 entry (2026-10-11): g_se_yph = btn_face_stripe_phase(+0x140, +0x150) of the
    FlatButton at [esp+4] -- its parent-local top reduced to [0, P) (the SE panel stripes on SocialWin's own
    buffer grid; only SocialWin's children reach this slot -- FlatButton_content_draw calls [parent vtbl]+0x14,
    so the MainWin-parented console arrows 0x1D..0x22 never do) -- then jmp thunk_se_rowdraw.  Staged on EVERY
    draw (no clear: rowdraw tail-jumps, and only rowdraw reads the cell).  g<=16 -> straight on (rowdraw's
    own native path; P is not valid there).  Preserves every register.
    v2 own (2026-10-27 W9A, the user's decision; law scaling_laws.btn_face_phase): t_face_own first
    (assemble_face_own.py) -- the right column's ten society rows (0x8B829C + i*0xB4C) take their OWN-top phase
    own_face_stripe_phase (CF = 1, edx), like vanilla; every other SE face keeps the parent-local top.  64 B = the
    slot exactly (0x2FFA0..0x2FFE0)."""
    ask = f"    call    {T_FACE_OWN:#x}\n    jc      ok\n" if own else ""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    push    edx
    mov     edx, dword ptr [esp+0xC]
{ask}    mov     eax, dword ptr [edx+0x140]
    add     eax, dword ptr [edx+0x150]
    cdq
    idiv    dword ptr [{G_STRIPE_PERIOD:#x}]
    test    edx, edx
    jge     ok
    add     edx, dword ptr [{G_STRIPE_PERIOD:#x}]
ok:
    mov     dword ptr [{G_SE_YPH:#x}], edx
    pop     edx
    pop     eax
go:
    jmp     thunk_se_rowdraw
"""


def _btn_run(span_l: int, span_r: int, w: int, gap: int, n: int, base: int, stride: int, bands: int,
             bstride: int, lbl: str) -> str:
    """One FlatButton run (law scaling_laws.se_button_run_lefts): W = fl(w), G = s(gap), L0 = s(span_l) +
    floor((s(span_r) - s(span_l) - nW - (n-1)G) / 2); button i's rect L/R = L0 + i*(W+G) / + W, written
    into `bands` rect-table rows (bstride apart) per column.  esi = SocialWin; clobbers eax..ebp."""
    return f"""
    mov     ebx, {w}
    {FL("ebx")}
    mov     ecx, {gap}
    {HD("ecx")}
    mov     eax, {span_r}
    {HD("eax")}
    mov     edx, {span_l}
    {HD("edx")}
    sub     eax, edx
    imul    edi, ebx, {n}
    sub     eax, edi
    imul    edi, ecx, {n - 1}
    sub     eax, edi
    sar     eax, 1
    add     eax, edx
    add     ecx, ebx
    lea     edi, [esi+{base:#x}]
    mov     ebp, {n}
{lbl}c:
    push    edi
    mov     edx, {bands}
{lbl}b:
    mov     dword ptr [edi], eax
    push    eax
    add     eax, ebx
    mov     dword ptr [edi+8], eax
    pop     eax
    add     edi, {bstride}
    dec     edx
    jnz     {lbl}b
    pop     edi
    add     eax, ecx
    add     edi, {stride}
    dec     ebp
    jnz     {lbl}c
"""


def asm_se_btnrun() -> str:
    """thunk_se_transform's tail (2026-10-11; its shared `jmp model_reset` now lands here): the option
    columns (4 per band, centred in the band frame 0x1A..0x26E) and CANCEL / RESET / OK (centred in
    0x9A..0x286) re-laid with ONE channel width each -- law se_button_run_lefts.  The transform already
    wrote every T/B and an L/R pair per button; only L/R change.  g<=16 -> straight to the tail.
    Tail (2026-10-25 W4C F42): `jmp t_se_layout` (was `jmp SocialWin_model_reset`) -- the band / option / SOCIETY /
    SPARTANS tables re-derived for the half-open frames (law se_halfopen_layout), which then jumps to model_reset."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    pushad
    mov     esi, {OBJ:#x}
{_btn_run(0x1A, 0x26E, 146, 2, 4, 0x1F150, 0x10, 4, 0x40, "op")}
{_btn_run(0x9A, 0x286, 162, 3, 3, 0x1F2D0, -0x10, 1, 0, "ok")}
    popad
go:
    jmp     {T_SE_LAYOUT:#x}
"""


def asm_se_stripe_px_ph() -> str:
    """thunk_se_stripe_px on the parent grid: eax = y -> stripe_px(y + g_se_yph)."""
    return f"""
    add     eax, dword ptr [{G_SE_YPH:#x}]
    jmp     thunk_se_stripe_px
"""


def asm_btn_gate_pre() -> str:
    """v3 = 22B SE-statics HIT prefix + v2 VERBATIM (council HIT prefix + v1 body)."""
    cwin_lo, cwin_hi = 0x6FEC80 + 0xD94, 0x6FEC80 + 0xD94 + 6 * 0xB4C
    return f"""
    cmp     esi, {BTN_LO:#x}
    jb      v2
    cmp     esi, {BTN_HI:#x}
    jae     v2
    mov     eax, 1
    ret
v2:
    cmp     esi, {cwin_lo:#x}
    jb      v1
    cmp     esi, {cwin_hi:#x}
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


# ---- layout / assembly ------------------------------------------------------
NEW_THUNKS = [   # (name, asm fn) — laid out consecutively from OFF_CODE, 16-aligned
    ("thunk_se_enter", asm_se_enter),
    ("thunk_se_immfix", asm_se_immfix),
    ("thunk_se_stripe_top", asm_se_stripe_top),
    ("thunk_se_sprites", asm_se_sprites),
    ("thunk_se_tiles", asm_se_tiles),
    ("thunk_se_locks", asm_se_locks),
    ("thunk_se_transform", asm_se_transform),
    ("thunk_se_sd2", asm_se_sd2),
    ("thunk_se_rr_row", asm_se_rr_row),
    ("thunk_se_rr_col", asm_se_rr_col),
    ("thunk_se_stripe_px", asm_se_stripe_px),
    ("thunk_se_rowdraw", asm_se_rowdraw),
    ("thunk_btn_gate_pre", asm_btn_gate_pre),   # v3 RELOCATED 0x13760 -> tail (old slot zeros)
]
# Fixed-slot thunks outside the consecutive run (2026-10-11 parent-grid face phase): (name, offset, asm fn)
FIXED_THUNKS = [
    ("thunk_se_rowdraw_ph", OFF_SE_ROWDRAW_PH, asm_se_rowdraw_ph),
    ("thunk_se_stripe_px_ph", OFF_SE_STRIPE_PX_PH, asm_se_stripe_px_ph),
    ("thunk_se_btnrun", OFF_SE_BTNRUN, asm_se_btnrun),
]
FIXED_END = {"thunk_se_rowdraw_ph": OFF_SE_STRIPE_PX_PH, "thunk_se_stripe_px_ph": OFF_G_SE_YPH,
             "thunk_se_btnrun": 0x30700}   # slot ends (cave_map)
RELOCATED = {"thunk_btn_gate_pre": 0x13760}
# Entries a LATER bake took over: still assembled here (the SE parity tests emulate the v4 body) but
# never written to the fragments -- the live yaml entry belongs to the owner named here.
OWNED_ELSEWHERE = {"thunk_btn_gate_pre": "assemble_rw.py (v5 @0x24230, group rw_scale_shared)"}
DATA = [   # (name, offset, bytes)
    ("g_se_immtab", OFF_G_SE_IMMTAB, immtab_bytes),
]
CELLS = [   # zero-init data (symbol + size only)
    ("g_se_vpdone", OFF_G_SE_VPDONE, 4),
    ("g_se_vpold", OFF_G_SE_VPOLD, 4),
    ("g_se_sprg", OFF_G_SE_SPRG, 4),
    ("g_se_sprsave", OFF_G_SE_SPRSAVE, 0x3A4),
    ("g_se_lockplane", OFF_G_SE_LOCKPLANE, 2 * LOCKPLANE_STRIDE),
    ("g_se_yph", OFF_G_SE_YPH, 4),
]

_ks = Ks(KS_ARCH_X86, KS_MODE_32)
_cs = Cs(CS_ARCH_X86, CS_MODE_32)
_cs.detail = True


def _clean(asm: str) -> str:
    return "\n".join(ln.split(";", 1)[0].rstrip() for ln in asm.splitlines() if ln.split(";", 1)[0].strip())


def assemble(asm: str, va: int, names: dict[str, int] | None = None) -> bytes:
    src = _clean(asm)
    if names:
        for k, v in sorted(names.items(), key=lambda kv: -len(kv[0])):
            src = src.replace(k, f"{v:#x}")
    enc, _ = _ks.asm(src, va)
    b = bytes(enc)
    total = sum(i.size for i in _cs.disasm(b, va))
    assert total == len(b), "capstone round-trip gap"
    return b


def assemble_all() -> tuple[dict[str, tuple[int, bytes]], int]:
    """Returns ({name: (offset, bytes)}, end_offset).  Passes resolve the forward
    references between the new thunks (names substituted as literals)."""
    layout: dict[str, tuple[int, bytes]] = {}
    names = {n: PCAVE2 + OFF_CODE for n, _ in NEW_THUNKS}   # provisional
    fixed = {n: PCAVE2 + o for n, o, _ in FIXED_THUNKS}
    names.update(fixed)
    for _pass in range(4):
        off = OFF_CODE
        new_names = {}
        for name, fn in NEW_THUNKS:
            va = PCAVE2 + off
            try:
                b = assemble(fn(), va, names)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"{name}: {e}") from e
            layout[name] = (off, b)
            new_names[name] = va
            off = (off + len(b) + 15) & ~15
        for name, o, fn in FIXED_THUNKS:
            try:
                b = assemble(fn(), PCAVE2 + o, names)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"{name}: {e}") from e
            layout[name] = (o, b)
        new_names.update(fixed)
        if new_names == names:
            break
        names = new_names
    else:
        raise RuntimeError("thunk layout did not converge")
    end = off
    for name, o, fn in DATA:
        layout[name] = (o, fn())
    return layout, end


# ---- placeholder templating ------------------------------------------------
SYM_ABS = {   # literal VA -> yaml symbol name (abs32 placeholders)
    G: "g_popup_scale_num", BTN_GATE: "thunk_btn_gate", STR_K32: "g_ed_str_k32", STR_VP: "g_ed_str_vp",
    DEVFILL: "thunk_box_thick_devfill", HOLLOWFLAT: "thunk_box_thick_hollow_flat",
    BOX_SPRITE: "Buffer_box_sprite", SD2: "Sprite_draw_2",
}
EXTRA_SYMS = {T_FACE_OWN: "t_face_own", G_SE_VPDONE: "g_se_vpdone", G_SE_VPOLD: "g_se_vpold", G_SE_SPRG: "g_se_sprg",
              G_SE_IMMTAB: "g_se_immtab", G_SE_SPRSAVE: "g_se_sprsave", G_SE_LOCKPLANE: "g_se_lockplane",
              G_SE_YPH: "g_se_yph"}


def templatize(b: bytes, va: int, extra: dict[int, str]) -> str:
    """Emit yaml hex with {abs32:}/{rel32:} placeholders for every operand that
    equals a known symbol VA (capstone operand inspection, no blind byte scans).
    The sprsave/lockplane INTERIOR addresses (base + SPRSAVE_LOCKS/TILES, + i*stride)
    are literal — they are not symbols; the base cells are declared with size:."""
    syms = dict(SYM_ABS)
    syms.update(extra)
    out = []
    for ins in _cs.disasm(b, va):
        raw = bytearray(ins.bytes)
        repl: list[tuple[int, str]] = []
        if ins.mnemonic == "call" and ins.operands and ins.operands[0].type == X86_OP_IMM and ins.size == 5:
            tgt = ins.operands[0].imm & 0xFFFFFFFF
            if tgt in syms:
                repl.append((1, "{rel32:" + syms[tgt] + "}"))
        elif ins.mnemonic.startswith("j") or ins.mnemonic == "call":
            pass   # branches stay literal (capstone reports ABSOLUTE targets; never {abs32:} them)
        else:
            for op in ins.operands:
                if op.type == X86_OP_IMM and (op.imm & 0xFFFFFFFF) in syms and ins.imm_size == 4:
                    repl.append((ins.imm_offset, "{abs32:" + syms[op.imm & 0xFFFFFFFF] + "}"))
                elif op.type == X86_OP_MEM and op.mem.base == 0 and (op.mem.disp & 0xFFFFFFFF) in syms:
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


# 2026-10-25 W4C F42: every target is a half-open trimming helper (assemble_halfopen_frames.SE_SITE_HELPER, law
# scaling_laws.se_frame_draw_rect) in front of the renderer the site called before; the OK row's union frame (was the
# native Buffer_box_sprite, a 1-px ring) now goes to thunk_box_thick_hollow_flat through t_bm_ho_hf.  Tied to
# scaling_laws.SE_HALFOPEN_FRAME_SITES by tests/test_scaling_se_halfopen.py.
FRAME_SITES = [   # (id suffix, function, callVA, target)
    ("SocialWin_draw_society_panel.d5a0", "SocialWin_draw_society_panel", 0x4AF226, "t_bm_ho_hf"),
    ("SocialWin_draw_society_panel.d618", "SocialWin_draw_society_panel", 0x4AF26F, "t_bm_ho_df"),
    ("SocialWin_draw_band.d5a0", "SocialWin_draw_band", 0x4AF35F, "t_bm_ho_hf"),
    ("SocialWin_draw_band.d618_title", "SocialWin_draw_band", 0x4AF3A8, "t_bm_ho_df"),
    ("SocialWin_draw_band.d618_lock_a", "SocialWin_draw_band", 0x4AF47E, "t_bm_ho_df"),
    ("SocialWin_draw_band.d618_lock_b", "SocialWin_draw_band", 0x4AF4A7, "t_bm_ho_df"),
    ("SocialWin_draw_band.d618_lock_c", "SocialWin_draw_band", 0x4AF4E9, "t_bm_ho_df"),
    ("SocialWin_draw_faction_box.d5a0", "SocialWin_draw_faction_box", 0x4AF904, "t_bm_ho_hf"),
    ("SocialWin_draw_faction_box.d618", "SocialWin_draw_faction_box", 0x4AF94A, "t_bm_ho_df"),
    ("SocialWin_draw_faction_box.d618_b", "SocialWin_draw_faction_box", 0x4AFA13, "t_bm_ho_df"),
    ("SocialWin_build.backdrop_d690", "SocialWin_build", 0x4B3315, "t_bm_ho_df"),
    ("SocialWin_repaint.union_frame", "SocialWin_repaint", 0x4B1A8F, "t_bm_ho_hf"),
]
SD2_SITES = [
    ("SocialWin_draw_band.digit_sd2", "SocialWin_draw_band", 0x4AF7D3),
    ("SocialWin_draw_band.icon_sd2", "SocialWin_draw_band", 0x4AF84D),
    ("SocialWin_draw_faction_box.icon_sd2", "SocialWin_draw_faction_box", 0x4AFB1D),
    ("SocialWin_draw_hover_panel.icon_sd2", "SocialWin_draw_hover_panel", 0x4B16A1),
    ("SocialWin_draw_society_row.state_sd2", "SocialWin_draw_society_row", 0x4B1878),
]
SET_MODAL_SITE = 0x4B3C4A   # SocialWin_build: FF 90 E4 00 00 00 = call [eax+0xE4] Win_set_modal (fonts v3 label-fit site)
CALL_SITES = [   # (id, function, site, original target, thunk, note) -- call_target_redirect
    ("SocialWin_build.caller_a", "social_open(0x4BB3xx)", 0x4BB3A9, BUILD, "thunk_se_enter",
     "call SocialWin_build (thiscall RET 4; caller 1 of 2) -> immfix, then the builder"),
    ("SocialWin_build.caller_b", "social_select", 0x5B565B, BUILD, "thunk_se_enter",
     "call SocialWin_build (thiscall RET 4; caller 2 of 2) -> immfix, then the builder"),
    ("SocialWin_build.model_reset", "SocialWin_build", 0x4B338C, MODEL_RESET, "thunk_se_transform",
     "call SocialWin_model_reset (tables seeded natively, buttons not yet created) -> table transform x g/16 + sprites/locks/tiles, then model_reset"),
]
CALL_SITES += [(sid, fn, site, SD2, "thunk_se_sd2", "call Sprite_draw_2 (1,1) -> num=g den=16") for sid, fn, site in SD2_SITES]
CALL_SITES += [(sid, fn, site, BOX_SPRITE, tgt, "Buffer_box_sprite " + sid.rsplit(".", 1)[1] + " -> thick chrome / device-density fill")
               for sid, fn, site, tgt in FRAME_SITES]
# se_scale v2: the modal SLIDES (SocialWin_show_hide 0x4B2120 calls slide_show/slide_hide directly, `push 0 /
# push esi(win)` cdecl = Popup_show's shape), so its side rails are the generic 15/8x529 strips drawn 1/1 --
# native-size "pillars" ~6 native px off the scaled backdrop at every g>16 (user shot 20260825-221937 @1920).
# Arm the popup rail gate around ITS two slide calls (the Popup_show/Diplo precedent): railscale (settled) +
# railslide (animation) then scale the rails; the backdrop imms above abut them.
SLIDE_SHOW, SLIDE_HIDE = 0x0045D440, 0x0045D970
CALL_SITES += [
    ("SocialWin_show_hide.railarm_show", "SocialWin_show_hide", 0x4B2192, SLIDE_SHOW, "thunk_popup_railshow",
     "call slide_show (0x45d440); args: push 0 / push esi(win) -> arm the rail-scale gate around the call"),
    ("SocialWin_show_hide.railarm_hide", "SocialWin_show_hide", 0x4B21B3, SLIDE_HIDE, "thunk_popup_railhide",
     "call slide_hide (0x45d970); args: push 0 / push esi(win) -> arm the rail-scale gate around the call"),
]


def base_exe_bytes(va: int, n: int) -> bytes:
    """Bytes of the PRISTINE base (.bak = 2d0b1438) the patcher applies onto."""
    exe = str(config.terranx_bak(required=True))
    import pefile
    pe = pefile.PE(exe, fast_load=True)
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def roundtrip_problems(layout, extra) -> list[str]:
    import pathlib
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(symbols, caves))
    for va, name in extra.items():
        symtab[name] = va
    out = []
    for name, (off, b) in layout.items():
        if name in ("g_se_immtab",):
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
    """Every redirect site must hold E8 -> the expected native target, every imm site
    its native value, the vtable slot the native entry, and the MOV-imm sites their
    native opcodes -- in the BASE exe."""
    problems = []
    for sid, _fn, site, tgt, _th, _note in CALL_SITES:
        have = base_exe_bytes(site, 5)
        want = bytes.fromhex(rel32(site, tgt).replace(" ", ""))
        if have != want:
            problems.append(f"{sid} @{site:#x}: live {have.hex()} != {want.hex()}")
    for site, a, b, kind, static in IMMTAB:
        if static:
            continue
        native = imm_native(a, b, kind)
        if kind & 1:
            have = struct.unpack("<i", base_exe_bytes(site, 4))[0]
        else:
            have = struct.unpack("<b", base_exe_bytes(site, 1))[0]
        if have != native:
            problems.append(f"imm @{site:#x}: live {have} != native {native}")
    if base_exe_bytes(VTBL_SLOT, 4) != struct.pack("<I", ROWDRAW):
        problems.append(f"vtable slot @{VTBL_SLOT:#x} != {ROWDRAW:#x}")
    for site, opc in MOVIMM_SITES:
        have = base_exe_bytes(site, 6)
        want = bytes([0x8B, 0x87 if opc == 0xB8 else 0x97, 0x70, 0x2C, 0x00, 0x00])
        if have != want:
            problems.append(f"movimm @{site:#x}: live {have.hex()} != {want.hex()}")
    return problems


def site_yaml() -> list[str]:
    lines = []
    for sid, fn, site, tgt, th, note in CALL_SITES:
        lines.append(
            f"  - id: {sid}\n    status: confirmed\n    group: se_scale\n    function: {fn}\n"
            f"    virtual_addr: {site:#010x}\n    length: 5\n    original_bytes: \"{rel32(site, tgt)}\"   # {note}\n"
            f"    new_bytes:      \"E8 {{rel32:{th}}}\"\n    pattern: call_target_redirect\n")
    # fonts v3 (2026-09-17, font_face_law's t_se_labelfit; assemble_fontlaw.py): the build is MODAL -- its
    # tail `call [vtbl+0xE4]` (Win_set_modal) returns only when the screen closes -- so the label fit hooks
    # THAT call: fit + repaint the 35 buttons, then tail-jmp into Win_set_modal.  Site owned here (se_scale).
    lines.append(
        f"  - id: SocialWin_build.set_modal\n    status: confirmed\n    group: se_scale\n    function: SocialWin_build\n"
        f"    virtual_addr: {SET_MODAL_SITE:#010x}\n    length: 6\n    original_bytes: \"FF 90 E4 00 00 00\""
        f"   # call [vtbl+0xE4] = Win_set_modal (blocks until the screen closes) -> t_se_labelfit: label fit + repaint, then Win_set_modal\n"
        f"    new_bytes:      \"E8 {{rel32:t_se_labelfit}} 90\"   # fonts v3 2026-09-17 (thunk in font_face_law, assemble_fontlaw.py)\n"
        f"    pattern: call_target_redirect\n")
    lines.append(
        f"  - id: SocialWin_vtbl.draw_society_row\n    status: confirmed\n    group: se_scale\n    function: SocialWin_vtbl\n"
        f"    virtual_addr: {VTBL_SLOT:#010x}\n    length: 4\n    original_bytes: \"{' '.join(f'{x:02X}' for x in struct.pack('<I', ROWDRAW))}\""
        f"  # SocialWin_draw_society_row slot (+0x14; fires per FlatButton draw after the face compose)\n"
        f"    new_bytes:      \"{{abs32:thunk_se_rowdraw_ph}}\"\n    pattern: vtable_repoint\n")
    for site, opc in MOVIMM_SITES:
        reg = "EAX" if opc == 0xB8 else "EDX"
        orig = f"8B {'87' if opc == 0xB8 else '97'} 70 2C 00 00"
        lines.append(
            f"  - id: SocialWin_draw_band.digitw_{'advance' if opc == 0xB8 else 'rowwidth'}\n    status: confirmed\n    group: se_scale\n"
            f"    function: SocialWin_draw_band\n    virtual_addr: {site:#010x}\n    length: 6\n"
            f"    original_bytes: \"{orig}\"   # mov {reg},[edi+0x2C70] = the digit[4] blit-w ALIAS (native 7, stays native for the sd2 ratio)\n"
            f"    new_bytes:      \"{opc:02X} 07 00 00 00 90\"   # mov {reg},imm32 7 (+nop); the imm is rewritten to s(7) by g_se_immtab\n"
            f"    pattern: inplace_rewrite\n")
    return lines


def main(argv: list[str]) -> int:
    layout, end = assemble_all()
    names = {n: PCAVE2 + layout[n][0] for n, _ in NEW_THUNKS}
    names.update({n: PCAVE2 + o for n, o, _ in FIXED_THUNKS})
    extra = {va: n for n, va in names.items()}
    extra.update(EXTRA_SYMS)
    ok = True
    print("; ==== se_scale bake (assemble_se.py) ====")
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
            # NOT emitted: a later bake owns the live entry (a refresh from this fragment would revert
            # it -- 2026-09-17 the se refresh put thunk_btn_gate_pre back to the v4 @0x16DA0 = boot crash).
            print(f"; {name} @{off:#x} len {len(b)} -- NOT EMITTED, owned by {OWNED_ELSEWHERE[name]}")
            continue
        reloc = f", RELOCATED from {RELOCATED[name]:#x} (old slot freed/zeros)" if name in RELOCATED else ""
        size = f", size: {len(b)}" if name == "thunk_btn_gate_pre" else ""
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}{size} }}   # se_scale ({len(b)}B{reloc})")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, extra)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    for name, o, _fn in FIXED_THUNKS:
        off, b = layout[name]
        nxt = FIXED_END[name]
        if off + len(b) > nxt:
            ok = False
            print(f"; {name} OVERFLOWS its fixed slot ({off + len(b):#x} > {nxt:#x})")
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # se_scale ({len(b)}B, fixed slot)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, extra)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x} (fixed)")
    site_lines = site_yaml()
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
        with open(os.path.join(frag_dir, "_fragment_se_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_se_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_se_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(site_lines))
        print("; fragments written to work/patches/_fragment_se_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print("\n".join(site_lines))
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
