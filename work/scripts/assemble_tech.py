#!/usr/bin/env python
"""Assembler for the SELECT RESEARCH GOAL (tech_pick / TechWin) BAKE (group tech_scale, 2026-08-28).

Ports the user-verified prototype hook_tech_proto.js v3b (4K + 1600 + 1920, pixel-measured
2026-08-28: every drawn channel/gap/font on law) into pcave2 thunks.  Laws: scaling_laws.tech_*
(tech_layout / tech_cell_rect / tech_cell_inset_rb / tech_strip_h_imm / tech_font_cell /
tech_icon_imms / tech_imm); every immediate is scale_px (HALF-DOWN) except the icon-ratio
literals (linear in g, native restored at g<=16).

  thunk_tech_enter   @ the single TechWin_exec caller (tech_pick 0x5BEBB7, E8): call
                     thunk_tech_immfix, then jmp TechWin_exec (ecx/stack untouched).
  thunk_tech_immfix  CALL helper: one-time VirtualProtect(0x484000, 0x4000) via the kernel32
                     IAT (the scenedit/council/SE bootstrap, shared strings), then the 36
                     cluster immediates: HD kind = s(a) - s(b) (identity at g=16 -> vanilla
                     restored on a res downgrade); LIN kind = a*g + b at g>16, the NATIVE
                     (kind >> 8) at g<=16 (the 6 icon-ratio literals: den 16->256, the s
                     literals -> (16+s)*g-16, sar 4->8).
  thunk_tech_inset   11-byte cut @0x48646C (mov eax,3 / sub ebx,eax / sub edx,eax / cmp ecx,eax):
                     R/B -= c_rb = s(4)-1 (the +1 gutter is a shared `inc` -> the inset carries
                     the proportion: gap = s(4)), L-clamp s(3); flags of the cmp reach the jg.
  thunk_tech_n8      9-byte cut @0x487981 (mov esi,edi / mov [ebp+8],12): the n>8 body-font
                     size stays native 10 while edi (pad, imm-scaled) is s(10).
  thunk_tech_n8ch    6-byte cut @0x487D21 (add eax,-0x45 / cdq / idiv ecx): eax -= s(0x45)
                     (imm8 overflows at g>=30), then cdq/idiv ecx.
  thunk_tech_rb1     the d618 strip + d528/d578 cell Buffer_box_sprite sites: g<=16 -> box_sprite;
                     else devfill gets a COPY of the rect with R-1/B-1 (MEASURED: devfill paints
                     the R/B strokes 1 px outside the half-open rect at g=22/25/40).
  thunk_tech_fi      the 4 Font_init sites (TechWin F0-F3): g<=16 -> Font_init; else the size
                     is rewritten to N = the smallest nominal >= max(S, s(S)-8) whose cell
                     (Font+0xC) reaches fl(native_cell*g/16) (native cell measured on the
                     scratch font), cached per (S, flags, g).
  thunk_tech_ff      the 8 find_font sites (name/title): g<=16 -> find_font; else a dedicated
                     cave Font object per (S, variant, g), Font_init'd with config_popups' own
                     face/flags law (S>12 -> g_hud_font_name_narrow + bold, else g_hud_font_name;
                     flags |= font_variant_flags[v]) and calibrated to fl(pool_cell*g/16).
  thunk_tech_calib   shared CALL helper (obj, name, S, flags, c0) -> eax = N, obj initialised.
  lever direct:      the d690 backdrop site -> thunk_box_thick_devfill (gates g<=16 itself).

Run:  py assemble_tech.py               -> prints the yaml fragments + checks
      py assemble_tech.py --fragments   -> writes work\\patches\\_fragment_tech_*.yaml
Parity: tests\\test_tech_asm_parity.py emulates these exact bytes.
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
with contextlib.redirect_stdout(io.StringIO()):
    import assemble_se as SE  # noqa: E402  (assemble / templatize / base_exe_bytes / rel32 / HD / FL)
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x1A000

# ---- engine anchors ----------------------------------------------------------
G            = 0x00668740   # g_popup_scale_num
EXEC         = 0x00486510   # TechWin_exec (thiscall)
EXEC_CALLER  = 0x005BEBB7   # tech_pick: the ONLY E8 caller (census in verify_live)
FONT_INIT    = 0x00618F40   # Font_init(this; name, size, flags) thiscall RET 0xC
FIND_FONT    = 0x005882F0   # find_font(size, variant) cdecl
BOX_SPRITE   = 0x005E2DD3
DEVFILL      = 0x00A102A0   # thunk_box_thick_devfill
FONT_NAME    = 0x00691B2C   # g_hud_font_name (char**) "Arial"
FONT_NAME_NR = 0x00691B30   # g_hud_font_name_narrow (char**) "Arial Narrow"
VARIANT_FLAGS = 0x0068F250  # font_variant_flags[4]
IAT_LOADLIB  = 0x00669120
IAT_GETPROC  = 0x00669124
STR_K32      = 0x00A1C6C0   # g_ed_str_k32
STR_VP       = 0x00A1C6D0   # g_ed_str_vp
VP_PAGE      = 0x00484000   # imm sites 0x484C1F..0x487E3A -> 4 pages
VP_LEN       = 0x4000
PAGE_RWX     = 0x40

# ---- new allocations (tail after the SE block 0x16D65) --------------------------
OFF_G_VPDONE   = 0x16E00
OFF_G_VPOLD    = 0x16E04
OFF_G_RBRECT   = 0x16E10   # 16B rect copy for rb1
OFF_G_FICACHE  = 0x16E20   # 8 x {S, flags, g, N} = 128B -> 0x16EA0
OFF_G_SCRATCH  = 0x16EA0   # scratch Font (0x28) for the fi calibration
OFF_G_FFCACHE  = 0x16F00   # 6 x 0x40 {S, v, g, pad, Font@+0x10} = 0x180 -> 0x17080
OFF_G_IMMTAB   = 0x17100   # 36 x 16 + 4 = 580B -> 0x17344
OFF_CODE       = 0x17400
FI_SLOTS, FF_SLOTS, FF_STRIDE = 8, 6, 0x40

G_VPDONE  = PCAVE2 + OFF_G_VPDONE
G_VPOLD   = PCAVE2 + OFF_G_VPOLD
G_RBRECT  = PCAVE2 + OFF_G_RBRECT
G_FICACHE = PCAVE2 + OFF_G_FICACHE
G_SCRATCH = PCAVE2 + OFF_G_SCRATCH
G_FFCACHE = PCAVE2 + OFF_G_FFCACHE
G_IMMTAB  = PCAVE2 + OFF_G_IMMTAB

# ---- the immediate table -------------------------------------------------------
# HD entries: (site, immOff, width, a, b) -> value s(a) - s(b), native a - b (the proto's P table
# minus the 0x487D21 imm8-overflow site, which is a cut; 0x487DBD carries the one-cascade strip law).
HD_IMMS = [
    (0x487358, 1, 4, 10, 0),        # edi = pad (n>8 body-font share cut at 0x487981)
    (0x487C96, 2, 1, 0x14, 0),      # cw = SW/cols - 20 (n<=8)
    (0x487CA1, 2, 1, 0, 0x14),      # cw = (SW-20)/cols (n>8): disp8 -0x14
    (0x487D0C, 2, 1, 0x1D, 0),      # overflow test ch*rows + 0x1D > SH
    (0x487D1C, 2, 1, 0x28, 0),      # ch = SH/rows - 40 (n<=8)
    (0x487D48, 2, 1, 0x1E, 0),      # H = (ch+1)*rows + 0x1E
    (0x487D6C, 6, 4, 0x1D, 0),      # [+0x16C] caption size
    (0x487DA6, 1, 4, 3, 0),         # caption strip inset
    (0x487DBD, 2, 1, 26, 3),        # caption strip height = s(26) - s(3) (one cascade)
    (0x487DDC, 1, 4, 3, 0),         # caption text inset
    (0x48644F, 2, 1, 0x1E, 0),      # T = row*(ch+1) + 0x1E
    (0x48648B, 2, 1, 0, 3),         # R clamp canvasW - 3
    (0x486498, 1, 4, 0x1D, 0),      # T clamp 0x1D
    (0x4864AD, 1, 4, 0, 3),         # B clamp -3 - canvasH
    (0x485FCD, 2, 1, 0x1D, 0),      # hit-test y -= 0x1D
    (0x484E48, 2, 1, 2, 0), (0x484E7E, 2, 1, 2, 0), (0x484EC3, 2, 1, 2, 0),   # name overflow W-2
    (0x484F54, 2, 1, 4, 0), (0x484F76, 2, 1, 4, 0), (0x484F8E, 2, 1, 2, 0),   # name (n>8) W-4, x+2
    (0x484FAE, 2, 1, 6, 0), (0x484FB2, 2, 1, 2, 0),                           # name wrap W-6, x+2
    (0x48507A, 2, 1, 2, 0),                                                   # category wrap W-2
    (0x4850DD, 1, 4, 0xB4, 0), (0x4850ED, 1, 4, 0x8C, 0),                     # icon class thresholds
    (0x4853E6, 2, 1, 8, 0), (0x4853E9, 2, 1, 4, 0),                           # quote W-8, x+4
    (0x484C1F, 2, 1, 2, 0), (0x484C47, 2, 1, 2, 0),                           # unlock W-2
]
# LIN entries: (site, immOff, width, a, b, native) -> value a*g + b at g>16, native at g<=16
LIN_IMMS = [
    (0x4850E4, 1, 4, 6, -16, -10),   # icon s=-10 literal -> 6g-16
    (0x4850F6, 2, 1, 2, 0, 2),       # and ebx,2 -> 2g
    (0x4850F9, 2, 1, 2, -16, -14),   # add ebx,-14 -> 2g-16
    (0x485140, 6, 4, 0, 256, 16),    # SCALE_DEN_G 16 -> 256
    (0x485183, 2, 1, 0, 8, 4),       # iconW sar 4 -> 8 (pre-blit)
    (0x485213, 2, 1, 0, 8, 4),       # iconW sar 4 -> 8 (advance)
]
KIND_DWORD, KIND_LIN = 1, 2


def immtab_entries() -> list[tuple[int, int, int, int]]:
    """(site, a, b, kind) rows of g_tech_immtab."""
    rows = []
    for site, off, w, a, b in HD_IMMS:
        rows.append((site + off, a, b, KIND_DWORD if w == 4 else 0))
    for site, off, w, a, b, native in LIN_IMMS:
        kind = (KIND_DWORD if w == 4 else 0) | KIND_LIN | ((native & 0xFFFFFF) << 8)
        rows.append((site + off, a, b, kind))
    return rows


def immtab_bytes() -> bytes:
    out = bytearray()
    for site, a, b, kind in immtab_entries():
        out += struct.pack("<IiiI", site, a, b, kind & 0xFFFFFFFF)
    out += b"\x00\x00\x00\x00"
    return bytes(out)


def imm_value(site_off: int, g: int) -> int:
    """Oracle: what the imm table must write at site+off for g (the laws)."""
    for site, off, _w, a, b in HD_IMMS:
        if site + off == site_off:
            return SL.scale_px(a, g) - SL.scale_px(b, g)
    for site, off, _w, a, b, native in LIN_IMMS:
        if site + off == site_off:
            return a * g + b if g > 16 else native
    raise KeyError(hex(site_off))


def imm_native(site_off: int) -> int:
    return imm_value(site_off, 16)


HD, FL = SE.HD, SE.FL


# ---- thunks ---------------------------------------------------------------------
def asm_tech_enter() -> str:
    return f"""
    push    ecx
    push    edx
    call    thunk_tech_immfix
    pop     edx
    pop     ecx
    jmp     {EXEC:#x}
"""


def asm_tech_immfix() -> str:
    return f"""
    push    esi
    cmp     dword ptr [{G_VPDONE:#x}], 0
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
    push    {G_VPOLD:#x}
    push    {PAGE_RWX:#x}
    push    {VP_LEN:#x}
    push    {VP_PAGE:#x}
    call    eax
    test    eax, eax
    je      bail
    mov     dword ptr [{G_VPDONE:#x}], 1
imms:
    cmp     dword ptr [{G_VPDONE:#x}], 0
    je      bail
    mov     esi, {G_IMMTAB:#x}
nexte:
    mov     eax, dword ptr [esi]
    test    eax, eax
    je      bail
    test    dword ptr [esi+12], {KIND_LIN}
    jne     klin
    mov     ecx, dword ptr [esi+4]
    {HD("ecx")}
    mov     edx, dword ptr [esi+8]
    {HD("edx")}
    sub     ecx, edx
    jmp     store
klin:
    mov     ecx, dword ptr [{G:#x}]
    cmp     ecx, 16
    jg      klinsc
    mov     ecx, dword ptr [esi+12]
    sar     ecx, 8
    jmp     store
klinsc:
    imul    ecx, dword ptr [esi+4]
    add     ecx, dword ptr [esi+8]
store:
    mov     eax, dword ptr [esi]
    test    dword ptr [esi+12], {KIND_DWORD}
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


def asm_tech_inset() -> str:
    return f"""
    mov     eax, 4
    {HD("eax")}
    dec     eax
    sub     ebx, eax
    sub     edx, eax
    mov     eax, 3
    {HD("eax")}
    cmp     ecx, eax
    ret
"""


def asm_tech_n8() -> str:
    return """
    mov     esi, 10
    mov     dword ptr [ebp+8], 12
    ret
"""


def asm_tech_n8ch() -> str:
    return f"""
    push    ecx
    mov     ecx, 0x45
    {HD("ecx")}
    sub     eax, ecx
    pop     ecx
    cdq
    idiv    ecx
    ret
"""


def asm_tech_rb1() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    push    eax
    push    edx
    mov     edx, dword ptr [esp+0xC]
    mov     eax, dword ptr [edx]
    mov     dword ptr [{G_RBRECT:#x}], eax
    mov     eax, dword ptr [edx+4]
    mov     dword ptr [{G_RBRECT + 4:#x}], eax
    mov     eax, dword ptr [edx+8]
    dec     eax
    mov     dword ptr [{G_RBRECT + 8:#x}], eax
    mov     eax, dword ptr [edx+12]
    dec     eax
    mov     dword ptr [{G_RBRECT + 12:#x}], eax
    mov     dword ptr [esp+0xC], {G_RBRECT:#x}
    pop     edx
    pop     eax
    jmp     {DEVFILL:#x}
native:
    jmp     {BOX_SPRITE:#x}
"""


def asm_tech_calib() -> str:
    """calib(obj, name, S, flags, c0) -> eax = N; obj Font_init'd at N.  c0 = 0 -> measure the
    native cell on obj itself (Font_init(obj, name, S, flags)).  N = first n in
    [max(S, s(S)-8), s(S)+16] with cell >= fl(c0*g/16); fallback s(S).  Own convention: args
    pushed right-to-left, RET 0x14; preserves ebx/esi/edi/ebp; clobbers eax/ecx/edx."""
    return f"""
    push    ebp
    mov     ebp, esp
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [ebp+0x18]
    test    eax, eax
    jne     havec0
    push    dword ptr [ebp+0x14]
    push    dword ptr [ebp+0x10]
    push    dword ptr [ebp+0xC]
    mov     ecx, dword ptr [ebp+8]
    call    {FONT_INIT:#x}
    mov     ecx, dword ptr [ebp+8]
    mov     eax, dword ptr [ecx+0xC]
havec0:
    {FL("eax")}
    mov     edi, eax
    mov     ebx, dword ptr [ebp+0x10]
    {HD("ebx")}
    lea     esi, [ebx-8]
    add     ebx, 16
    cmp     esi, dword ptr [ebp+0x10]
    jge     loop_
    mov     esi, dword ptr [ebp+0x10]
loop_:
    push    dword ptr [ebp+0x14]
    push    esi
    push    dword ptr [ebp+0xC]
    mov     ecx, dword ptr [ebp+8]
    call    {FONT_INIT:#x}
    mov     ecx, dword ptr [ebp+8]
    cmp     dword ptr [ecx+0xC], edi
    jge     done
    inc     esi
    cmp     esi, ebx
    jle     loop_
    mov     esi, dword ptr [ebp+0x10]
    {HD("esi")}
    push    dword ptr [ebp+0x14]
    push    esi
    push    dword ptr [ebp+0xC]
    mov     ecx, dword ptr [ebp+8]
    call    {FONT_INIT:#x}
done:
    mov     eax, esi
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret     0x14
"""


def asm_tech_fi() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    push    ebp
    mov     ebp, esp
    push    ebx
    push    esi
    push    edi
    mov     ebx, ecx
    mov     esi, dword ptr [ebp+0xC]
    mov     edi, dword ptr [ebp+0x10]
    mov     ecx, {G_FICACHE:#x}
    mov     edx, {FI_SLOTS}
lk:
    cmp     dword ptr [ecx], esi
    jne     lknext
    cmp     dword ptr [ecx+4], edi
    jne     lknext
    mov     eax, dword ptr [{G:#x}]
    cmp     dword ptr [ecx+8], eax
    jne     lknext
    mov     eax, dword ptr [ecx+12]
    jmp     hit
lknext:
    add     ecx, 16
    dec     edx
    jne     lk
    push    0
    push    edi
    push    esi
    push    dword ptr [ebp+8]
    push    {G_SCRATCH:#x}
    call    thunk_tech_calib
    mov     ecx, {G_FICACHE:#x}
    mov     edx, {FI_SLOTS}
sl:
    cmp     dword ptr [ecx+8], 0
    je      take
    cmp     dword ptr [ecx], esi
    jne     slnext
    cmp     dword ptr [ecx+4], edi
    je      take
slnext:
    add     ecx, 16
    dec     edx
    jne     sl
    mov     ecx, {G_FICACHE:#x}
take:
    mov     dword ptr [ecx], esi
    mov     dword ptr [ecx+4], edi
    mov     edx, dword ptr [{G:#x}]
    mov     dword ptr [ecx+8], edx
    mov     dword ptr [ecx+12], eax
hit:
    mov     dword ptr [ebp+0xC], eax
    mov     ecx, ebx
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
native:
    jmp     {FONT_INIT:#x}
"""


def asm_tech_ff() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     native
    push    ebp
    mov     ebp, esp
    push    ebx
    push    esi
    push    edi
    mov     esi, dword ptr [ebp+8]
    mov     edi, dword ptr [ebp+0xC]
    mov     ecx, {G_FFCACHE:#x}
    mov     edx, {FF_SLOTS}
lk:
    cmp     dword ptr [ecx], esi
    jne     lknext
    cmp     dword ptr [ecx+4], edi
    jne     lknext
    mov     eax, dword ptr [{G:#x}]
    cmp     dword ptr [ecx+8], eax
    jne     lknext
    lea     eax, [ecx+0x10]
    jmp     done
lknext:
    add     ecx, {FF_STRIDE}
    dec     edx
    jne     lk
    mov     ecx, {G_FFCACHE:#x}
    mov     edx, {FF_SLOTS}
sl:
    cmp     dword ptr [ecx+8], 0
    je      take
    cmp     dword ptr [ecx], esi
    jne     slnext
    cmp     dword ptr [ecx+4], edi
    je      take
slnext:
    add     ecx, {FF_STRIDE}
    dec     edx
    jne     sl
    mov     ecx, {G_FFCACHE:#x}
take:
    mov     ebx, ecx
    mov     dword ptr [ebx], esi
    mov     dword ptr [ebx+4], edi
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [ebx+8], eax
    push    edi
    push    esi
    call    {FIND_FONT:#x}
    add     esp, 8
    mov     eax, dword ptr [eax+0xC]
    mov     ecx, dword ptr [{FONT_NAME:#x}]
    xor     edx, edx
    cmp     esi, 12
    jle     small_
    mov     ecx, dword ptr [{FONT_NAME_NR:#x}]
    mov     edx, 1
small_:
    or      edx, dword ptr [edi*4+{VARIANT_FLAGS:#x}]
    push    eax
    push    edx
    push    esi
    push    ecx
    lea     eax, [ebx+0x10]
    push    eax
    call    thunk_tech_calib
    lea     eax, [ebx+0x10]
done:
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret
native:
    jmp     {FIND_FONT:#x}
"""


NEW_THUNKS = [
    ("thunk_tech_enter", asm_tech_enter),
    ("thunk_tech_immfix", asm_tech_immfix),
    ("thunk_tech_inset", asm_tech_inset),
    ("thunk_tech_n8", asm_tech_n8),
    ("thunk_tech_n8ch", asm_tech_n8ch),
    ("thunk_tech_rb1", asm_tech_rb1),
    ("thunk_tech_calib", asm_tech_calib),
    ("thunk_tech_fi", asm_tech_fi),
    ("thunk_tech_ff", asm_tech_ff),
]
DATA = [("g_tech_immtab", OFF_G_IMMTAB, immtab_bytes)]
CELLS = [
    ("g_tech_vpdone", OFF_G_VPDONE, 4),
    ("g_tech_vpold", OFF_G_VPOLD, 4),
    ("g_tech_rbrect", OFF_G_RBRECT, 16),
    ("g_tech_ficache", OFF_G_FICACHE, FI_SLOTS * 16),
    ("g_tech_scratchfont", OFF_G_SCRATCH, 0x28),
    ("g_tech_ffcache", OFF_G_FFCACHE, FF_SLOTS * FF_STRIDE),
]


def assemble_all() -> tuple[dict[str, tuple[int, bytes]], int]:
    layout: dict[str, tuple[int, bytes]] = {}
    names = {n: PCAVE2 + OFF_CODE for n, _ in NEW_THUNKS}
    for _pass in range(4):
        off = OFF_CODE
        new_names = {}
        for name, fn in NEW_THUNKS:
            va = PCAVE2 + off
            try:
                b = SE.assemble(fn(), va, names)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"{name}: {e}") from e
            layout[name] = (off, b)
            new_names[name] = va
            off = (off + len(b) + 15) & ~15
        if new_names == names:
            break
        names = new_names
    else:
        raise RuntimeError("thunk layout did not converge")
    end = off
    for name, o, fn in DATA:
        layout[name] = (o, fn())
    return layout, end


EXTRA_SYMS = {G_VPDONE: "g_tech_vpdone", G_VPOLD: "g_tech_vpold", G_RBRECT: "g_tech_rbrect",
              G_FICACHE: "g_tech_ficache", G_SCRATCH: "g_tech_scratchfont", G_FFCACHE: "g_tech_ffcache",
              G_IMMTAB: "g_tech_immtab", FONT_INIT: "Font_init", FIND_FONT: "find_font"}

# ---- sites ----------------------------------------------------------------------
FONT_INIT_SITES = [0x487999, 0x4879AE, 0x4879C2, 0x4879DA]
FIND_FONT_SITES = [0x484D4F, 0x484D5C, 0x484D6D, 0x484D7A, 0x484D8E, 0x484D9B, 0x484DA8, 0x487E3A]
CALL_SITES = [   # (id, function, site, original target, thunk, note) -- call_target_redirect
    ("tech_pick.exec", "tech_pick", EXEC_CALLER, EXEC, "thunk_tech_enter",
     "call TechWin_exec (the only caller) -> immfix (36 imms, VirtualProtect bootstrap), then the exec"),
    ("TechWin_exec.backdrop_d690", "TechWin_exec", 0x487D9E, BOX_SPRITE, "thunk_box_thick_devfill",
     "Buffer_box_sprite d690 backdrop {0,0,W,H} -> thick chrome / device-density fill (gates g<=16 itself)"),
    ("TechWin_exec.strip_d618", "TechWin_exec", 0x487DD1, BOX_SPRITE, "thunk_tech_rb1",
     "Buffer_box_sprite d618 caption strip -> devfill with R-1/B-1 (measured 1px R/B spill)"),
    ("TechWin_draw_cell.frame_d528", "TechWin_draw_cell", 0x4864D8, BOX_SPRITE, "thunk_tech_rb1",
     "Buffer_box_sprite d528/d578 cell frame -> devfill with R-1/B-1 (measured 1px R/B spill)"),
]
CALL_SITES += [(f"TechWin_exec.font_init_{i}", "TechWin_exec", s_, FONT_INIT, "thunk_tech_fi",
                "call Font_init F%d -> size rewritten to the cell-calibrated nominal (g<=16: untouched)" % i)
               for i, s_ in enumerate(FONT_INIT_SITES)]
FF_FN = ["TechWin_draw_cell_content"] * 7 + ["TechWin_exec"]
FF_NOTE = ["find_font(20,2) name italic", "find_font(20,1) name", "find_font(18,2) name (800 branch)",
           "find_font(18,1) name (800 branch)", "find_font(12,2) name (n>8)", "find_font(12,1) name (n>8)",
           "find_font(S,1) name shared tail", "find_font(18,1) caption title"]
CALL_SITES += [(f"tech.find_font_{i}", FF_FN[i], s_, FIND_FONT, "thunk_tech_ff",
                FF_NOTE[i] + " -> dedicated cell-calibrated Font (pool face/flags law); g<=16: the pool")
               for i, s_ in enumerate(FIND_FONT_SITES)]
CUT_SITES = [   # (id, function, site, original bytes, thunk, note)
    ("TechWin_draw_cell.inset", "TechWin_draw_cell", 0x48646C, "B8 03 00 00 00 2B D8 2B D0 3B C8", "thunk_tech_inset",
     "mov eax,3 / sub ebx,eax / sub edx,eax / cmp ecx,eax -> R/B -= s(4)-1, L-clamp s(3) (cmp flags reach the jg)"),
    ("TechWin_exec.n8_fontsize", "TechWin_exec", 0x487981, "8B F7 C7 45 08 0C 00 00 00", "thunk_tech_n8",
     "mov esi,edi / mov [ebp+8],12 (n>8) -> esi = native 10 (edi = pad is imm-scaled)"),
    ("TechWin_exec.n8_overflow", "TechWin_exec", 0x487D21, "83 C0 BB 99 F7 F9", "thunk_tech_n8ch",
     "add eax,-0x45 / cdq / idiv ecx (n>8 overflow ch) -> eax -= s(0x45) (imm8 overflows at g>=30)"),
]


def verify_live() -> list[str]:
    problems = []
    for sid, _fn, site, tgt, _th, _note in CALL_SITES:
        have = SE.base_exe_bytes(site, 5)
        want = bytes.fromhex(SE.rel32(site, tgt).replace(" ", ""))
        if have != want:
            problems.append(f"{sid} @{site:#x}: live {have.hex()} != {want.hex()}")
    for sid, _fn, site, orig, _th, _note in CUT_SITES:
        want = bytes.fromhex(orig.replace(" ", ""))
        have = SE.base_exe_bytes(site, len(want))
        if have != want:
            problems.append(f"{sid} @{site:#x}: live {have.hex()} != {want.hex()}")
    for site, a, b, kind in immtab_entries():
        native = imm_native(site)
        if kind & KIND_DWORD:
            have = struct.unpack("<i", SE.base_exe_bytes(site, 4))[0]
        else:
            have = struct.unpack("<b", SE.base_exe_bytes(site, 1))[0]
        if have != native:
            problems.append(f"imm @{site:#x}: live {have} != native {native}")
    # census: TechWin_exec must have exactly the one E8 caller we redirect
    import pefile
    import config
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    callers = []
    for sec in pe.sections:
        if not sec.Name.startswith(b".text"):
            continue
        data, va0 = sec.get_data(), base + sec.VirtualAddress
        i = data.find(b"\xE8")
        while 0 <= i < len(data) - 5:
            rel = int.from_bytes(data[i + 1:i + 5], "little", signed=True)
            if (va0 + i + 5 + rel) & 0xFFFFFFFF == EXEC:
                callers.append(va0 + i)
            i = data.find(b"\xE8", i + 1)
    if callers != [EXEC_CALLER]:
        problems.append(f"TechWin_exec E8 callers {[hex(c) for c in callers]} != [{EXEC_CALLER:#x}]")
    return problems


def roundtrip_problems(layout, extra) -> list[str]:
    import pathlib
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(symbols, caves))
    for va, name in extra.items():
        symtab[name] = va
    out = []
    for name, (off, b) in layout.items():
        if name in ("g_tech_immtab",):
            continue
        va = PCAVE2 + off
        hexs = SE.templatize(b, va, extra)
        try:
            back = ap.ByteTemplate(hexs).resolve(va, symtab)
        except Exception as e:  # noqa: BLE001
            out.append(f"{name}: template does not resolve: {e}")
            continue
        if back != b:
            out.append(f"{name}: resolved bytes differ (len {len(back)} vs {len(b)})")
    return out


def site_yaml() -> list[str]:
    lines = []
    for sid, fn, site, tgt, th, note in CALL_SITES:
        lines.append(
            f"  - id: {sid}\n    status: confirmed\n    group: tech_scale\n    function: {fn}\n"
            f"    virtual_addr: {site:#010x}\n    length: 5\n    original_bytes: \"{SE.rel32(site, tgt)}\"   # {note}\n"
            f"    new_bytes:      \"E8 {{rel32:{th}}}\"\n    pattern: call_target_redirect\n")
    for sid, fn, site, orig, th, note in CUT_SITES:
        n = len(orig.split())
        nops = " ".join(["90"] * (n - 5))
        lines.append(
            f"  - id: {sid}\n    status: confirmed\n    group: tech_scale\n    function: {fn}\n"
            f"    virtual_addr: {site:#010x}\n    length: {n}\n    original_bytes: \"{orig}\"   # {note}\n"
            f"    new_bytes:      \"E8 {{rel32:{th}}} {nops}\"\n    pattern: block_cut_thunk\n")
    return lines


def main(argv: list[str]) -> int:
    layout, end = assemble_all()
    names = {n: PCAVE2 + layout[n][0] for n, _ in NEW_THUNKS}
    extra = {va: n for n, va in names.items()}
    extra.update(EXTRA_SYMS)
    ok = True
    print("; ==== tech_scale bake (assemble_tech.py) ====")
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
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # tech_scale ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{SE.templatize(b, PCAVE2 + off, extra)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
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
    if "--fragments" in argv:
        frag_dir = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag_dir, "_fragment_tech_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_tech_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag_dir, "_fragment_tech_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(site_lines))
        print("; fragments written to work/patches/_fragment_tech_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print("\n".join(site_lines))
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
