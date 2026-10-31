"""Assemble the strip draw-fn CONTENT thunks (group basewin_strip_content,
bottom-HUD slice 2a): every native constant, font size and sprite ratio inside
the 7 strip draw fns scales by the laws in scaling_laws.basewin_strip_content.

Two patch shapes:
  * CALL-redirects: existing `E8 target` sites retargeted at an adapter that
    scales an argument (Font_init size, find_font size, Sprite_draw_2 ratio,
    shared-header set_font swap) and tail-jmps the native target.
  * CUTS: a run of instructions carrying native immediates is replaced by
    `E8 thunk` + NOP padding; the thunk re-runs the block's exact semantics
    with the immediates scaled fl(k*g/16) (identity at g<=16 via the gate in
    sc()).  Register/flag contracts were derived instruction-by-instruction
    from work\\_tmp_disasm_strip_fns.txt; each cut's original bytes are pinned
    here AND in patches.yaml original_bytes.  Cuts that must push args for the
    parent's upcoming call use the pop-ret pattern (RETC cell; single UI
    thread, non-reentrant — the established g_bw_ret precedent).

Laws: scaling_laws.basewin_strip_content / basewin_strip_pop_citizen_y /
basewin_font_size / basewin_sprite_ratio.  Parity:
tests\\test_strip_content_asm_parity.py (Unicorn, per-thunk contracts).

Output: `python assemble_strip_content.py` prints the yaml symbol lines and
the cave content entry, audits cut byte-exactness + branch-into-cut safety
against ../_tmp_disasm_strip_fns.txt when present, and writes
../patches/_fragment_strip_content_sites.yaml (site + group fragments).
Regenerate from this script; never hand-edit those yaml blocks.
"""
from __future__ import annotations

import os
import re

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0xA0C000
BASE_OFF = 0xD590          # after thunk_hud_vehargs v2 (0xD500+135)
SECTION_END = 0xE000       # cave grown 0xD800 -> 0xE000 this slice
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

G = 0xDEADBE00             # g_popup_scale_num placeholder (resolves 0x668740)
STRIP_CANVAS = 0x7AEC64
FONT_INIT = 0x618F40       # thiscall RET 0xC (name, height, style)
SET_FONT = 0x5DAC70        # thiscall RET 0x10
FIND_FONT = 0x5882F0       # cdecl (size, variant)
SPRITE_DRAW_2 = 0x5E4B4A   # thiscall (dest,key,x,y,num,den) — baked entry detour
SPRITE_BILINEAR = PCAVE2_VA + 0x21000   # thunk_sprite_bilinear (assemble_rw_kinds PINNED): Sprite_draw_2 contract,
                                        # palette-aware average; num<=den / any guard failure -> Sprite_draw_2
FACE_HYBRID = PCAVE2_VA + 0x21A00       # thunk_face_hybrid (assemble_rw_kinds PINNED): same contract and guards (+ g<=16
                                        # -> Sprite_draw_2); bilinear photo + the face's scanline background regenerated
SPOT_CHECK = 0x5FAB00      # thiscall RET 0x10 (x, y, int* pos, int* type)
HUD_FONT_NAME = 0x691B2C
SHARED_FONT = 0x6A7628 + 0x40E8C   # BaseWin_g+0x40e8c (Arial-Narrow 14 bold)
G_BW_FONT = 0xA0C000 + 0xB6E0      # cave Font object (re-inited per use)
# font_face_law helpers (assemble_fontlaw.py, 2026-09-17): the base-info name font keeps the pool's
# FACE for its native size (S > 12 -> Arial Narrow bold, else Arial) on its own keyed slot.
T_FFN_AT = 0xA0C000 + 0x2E490      # t_ffn_at(slot, S, v, num) cdecl -> slot
G_FONT_BWNAME = 0xA0C000 + 0x2E350 # g_font_bwname (0x30 keyed slot)
SCALE_NUM_G = 0x696D18
SCALE_DEN_G = 0x696D1C

RETC = PCAVE2_VA + BASE_OFF        # 4B: pop-ret cell
TMP = PCAVE2_VA + BASE_OFF + 4     # 4B: scratch
FLAGC = PCAVE2_VA + BASE_OFF + 8   # 4B: saved EFLAGS (flag-transparent pop-ret thunks)
THUNKS_OFF = BASE_OFF + 12

_lbl = [0]


def sc(reg: str = "eax") -> str:
    """reg = fl(reg*g/16), identity at g<=16. Clobbers flags only."""
    _lbl[0] += 1
    n = _lbl[0]
    return (f"cmp dword ptr [{G:#x}], 0x10\n"
            f"jle sc_{n}\n"
            f"imul {reg}, dword ptr [{G:#x}]\n"
            f"sar {reg}, 4\n"
            f"sc_{n}:\n")


def T(name):
    def deco(fn):
        THUNK_ASM[name] = fn
        return fn
    return deco


THUNK_ASM: dict = {}

# ---- tiny MOV-imm thunks (a 5-byte `MOV reg, imm32` whose register carries
# the constant through the whole vanilla block) ------------------------------
# FLAG LAW: a MOV is flag-neutral, and vanilla puts these between a CMP and
# its Jcc (draw_queue.listx5 sits inside CMP ScreenWidth / JNZ) — so every
# thunk replacing a flag-neutral original must be flag-TRANSPARENT.  sc()'s
# gate clobbers EFLAGS; wrap it in pushfd/popfd.
for _reg, _k in (("eax", 3), ("eax", 5), ("eax", 2), ("ebx", 3),
                 ("edx", 2), ("ecx", 2)):
    THUNK_ASM[f"t_mov_{_reg}_s{_k}"] = (
        lambda reg=_reg, k=_k: f"pushfd\nmov {reg}, {k}\n{sc(reg)}popfd\nret\n")


@T("t_prod_ghost5")
def _():
    # prod 0x40e47d(45B): queue ghost box (l-5,t+5,r-5,b+5) from rect at EDX.
    # Exit: fields in [ebp-1c/-18/-10], ECX=r-s5 (site stores it at +0x40e4b0).
    return f"""
        mov eax, 5
        {sc('eax')}
        mov ecx, [edx]
        sub ecx, eax
        mov [ebp-0x1c], ecx
        mov ecx, [edx+4]
        add ecx, eax
        mov [ebp-0x18], ecx
        mov ecx, [edx+0xc]
        add ecx, eax
        mov [ebp-0x10], ecx
        mov ecx, [edx+8]
        sub ecx, eax
        ret
    """


def _inner3(l_d, t_d, r_d, b_d):
    # shared shape: production 0x40e582 / pop 0x414c27 (44B): rect at ESI ->
    # +-s3 into 4 ebp locals, push &rect-local, ecx=strip canvas (pop-ret:
    # the arg push happens inside the cut).
    return f"""
        pop dword ptr [{RETC:#x}]
        mov eax, 3
        {sc('eax')}
        mov ecx, [esi]
        add ecx, eax
        mov [ebp-{l_d:#x}], ecx
        mov ecx, [esi+4]
        add ecx, eax
        mov [ebp-{t_d:#x}], ecx
        mov edx, [esi+8]
        sub edx, eax
        mov [ebp-{r_d:#x}], edx
        mov esi, [esi+0xc]
        sub esi, eax
        mov [ebp-{b_d:#x}], esi
        lea eax, [ebp-{l_d:#x}]
        push eax
        mov ecx, {STRIP_CANVAS:#x}
        jmp dword ptr [{RETC:#x}]
    """


THUNK_ASM["t_prod_inner3"] = lambda: _inner3(0x1C, 0x18, 0x14, 0x10)
THUNK_ASM["t_pop_inner3"] = lambda: _inner3(0x48, 0x44, 0x40, 0x3C)


@T("t_prod_union6")
def _():
    # prod 0x40e50f(6B): ADD ESI,EAX(=s3); PUSH 6; PUSH 6 (blank corner sprite
    # dims for the CHANGE/HURRY union frame). EAX dead after.
    return f"""
        pop dword ptr [{RETC:#x}]
        add esi, eax
        mov eax, 6
        {sc('eax')}
        push eax
        push eax
        jmp dword ptr [{RETC:#x}]
    """


@T("t_flash_union6")
def _():
    # flash 0x40d412(6B): ADD EDI,EBX(=s3); PUSH 6; PUSH 6. EAX LIVE.
    return f"""
        pop dword ptr [{RETC:#x}]
        add edi, ebx
        mov [{TMP:#x}], eax
        mov eax, 6
        {sc('eax')}
        push eax
        push eax
        mov eax, [{TMP:#x}]
        jmp dword ptr [{RETC:#x}]
    """


@T("t_prod_pic28")
def _():
    # prod 0x40e685(10B): EDX=[ebp-0x18]+s(0x28) (unit-pic anchor, both
    # branches), EBX=EAX>>1 (centre-x half-width).
    return f"""
        mov ebx, eax
        sar ebx, 1
        mov eax, 0x28
        {sc('eax')}
        mov edx, [ebp-0x18]
        add edx, eax
        ret
    """


@T("t_flash_pic28")
def _():
    # flash 0x40d517(6B): LEA EAX,[ECX+ECX*2]; LEA EBX,[EDX+s(0x28)].
    # Neutral original (lea/lea) -> flag-transparent.
    return f"""
        pushfd
        lea eax, [ecx+ecx*2]
        push eax
        mov eax, 0x28
        {sc('eax')}
        lea ebx, [edx+eax]
        pop eax
        popfd
        ret
    """


@T("t_prod_name41c")
def _():
    # prod 0x40e7fd(9B): ECX=[ebp-0x18]+s(0x41); EDX=ESI*3.
    return f"""
        lea edx, [esi+esi*2]
        mov eax, 0x41
        {sc('eax')}
        mov ecx, [ebp-0x18]
        add ecx, eax
        ret
    """


@T("t_prod_name41b")
def _():
    # prod 0x40ea60(12B): EBX=[ebp-0x18]+s(0x41); ESI=EDI*48.
    return f"""
        lea esi, [edi+edi*2]
        shl esi, 4
        mov eax, 0x41
        {sc('eax')}
        mov ebx, [ebp-0x18]
        add ebx, eax
        ret
    """


@T("t_flash_name41")
def _():
    # flash 0x40d593(9B): EAX=[ebp-0x1c]+s(0x41); ESI=[EDI+ECX*4].
    return f"""
        lea esi, [edi+ecx*4]
        mov eax, 0x41
        {sc('eax')}
        add eax, [ebp-0x1c]
        ret
    """


@T("t_prod_iconsz")
def _():
    # prod 0x40ea46(6B): PUSH s(0x28); PUSH EAX(color); EAX=[ebp-0x20].
    # ECX/EDX live (sprite ptr / dest) -> scratch cell, no reg use.
    # Neutral original (push/push/mov) -> flag-transparent; flags go through
    # FLAGC because the arg pushes must stay on the stack.
    return f"""
        pop dword ptr [{RETC:#x}]
        mov [{TMP:#x}], eax
        pushfd
        pop dword ptr [{FLAGC:#x}]
        mov eax, 0x28
        {sc('eax')}
        push eax
        push dword ptr [{TMP:#x}]
        mov eax, [ebp-0x20]
        push dword ptr [{FLAGC:#x}]
        popfd
        jmp dword ptr [{RETC:#x}]
    """


@T("t_prod_iconxy")
def _():
    # prod 0x40ea4c(6B): EAX-=s(0x14); EBX-=s(0x14). ECX/EDX live.
    return f"""
        push ecx
        mov ecx, eax
        mov eax, 0x14
        {sc('eax')}
        sub ecx, eax
        sub ebx, eax
        mov eax, ecx
        pop ecx
        ret
    """


@T("t_bar2a")
def _():
    # prod 0x40eb77(5B): EDX=EDI*s(2); CMP EDX,EBX (flags -> site JGE).
    return f"""
        push eax
        mov eax, 2
        {sc('eax')}
        imul eax, edi
        mov edx, eax
        pop eax
        cmp edx, ebx
        ret
    """


@T("t_bar2b")
def _():
    # prod 0x40eb8b(7B): [ebp-0x28]=EDI; EAX*=s(2); CMP EAX,ESI.
    return f"""
        mov [ebp-0x28], edi
        push ecx
        mov ecx, eax
        mov eax, 2
        {sc('eax')}
        imul eax, ecx
        pop ecx
        cmp eax, esi
        ret
    """


@T("t_bar2c")
def _():
    # prod 0x40eb98(7B): CDQ; IDIV EDI; EAX*=s(2); CMP EAX,ESI.
    return f"""
        cdq
        idiv edi
        push ecx
        mov ecx, eax
        mov eax, 2
        {sc('eax')}
        imul eax, ecx
        pop ecx
        cmp eax, esi
        ret
    """


@T("t_barthresh")
def _():
    # prod 0x40ec28(23B): tile-vs-flat threshold s(8) + s(1) cell nudges.
    # cellH in EBX; small: ECX-=s1 -> [ebp-0x40]; big: EAX+=s1, ECX-=s1,
    # ESI+=s1 -> [ebp-0x48/-0x40/-0x44]. EDI preserved.
    return f"""
        push edi
        mov edi, 8
        {sc('edi')}
        cmp ebx, edi
        jge big
        mov edi, 1
        {sc('edi')}
        sub ecx, edi
        pop edi
        mov [ebp-0x40], ecx
        ret
    big:
        mov edi, 1
        {sc('edi')}
        add eax, edi
        sub ecx, edi
        add esi, edi
        pop edi
        mov [ebp-0x48], eax
        mov [ebp-0x40], ecx
        mov [ebp-0x44], esi
        ret
    """


@T("t_bardec")
def _():
    # prod 0x40ec3f(6B): EDX-=s(1); EBX=[ebp-0x60]; TEST EBX,EBX (site flags).
    return f"""
        push eax
        mov eax, 1
        {sc('eax')}
        sub edx, eax
        pop eax
        mov ebx, [ebp-0x60]
        test ebx, ebx
        ret
    """


@T("t_flash_ghost5")
def _():
    # flash 0x40d399(54B): ghost box from rect at EDI; pushes the two rect
    # ptrs for box_sprite inside the cut (pop-ret); ecx=canvas on exit.
    return f"""
        pop dword ptr [{RETC:#x}]
        mov eax, 5
        {sc('eax')}
        mov ecx, [edi]
        sub ecx, eax
        mov [ebp-0x20], ecx
        mov ecx, [edi+4]
        add ecx, eax
        mov [ebp-0x1c], ecx
        mov ecx, [edi+8]
        sub ecx, eax
        mov [ebp-0x18], ecx
        mov edi, [edi+0xc]
        add edi, eax
        mov [ebp-0x14], edi
        lea ecx, [ebp-0x5c]
        push ecx
        lea edx, [ebp-0x20]
        push edx
        mov ecx, {STRIP_CANVAS:#x}
        jmp dword ptr [{RETC:#x}]
    """


@T("t_pop_c30")
def _():
    # pop 4x(6B): [ebp-0x18]=EAX(cellH); EAX-=s(0x30) (citizen centering,
    # law basewin_strip_pop_citizen_y). ECX live (canvas mask in flight).
    return f"""
        mov [ebp-0x18], eax
        push ecx
        mov ecx, eax
        mov eax, 0x30
        {sc('eax')}
        sub ecx, eax
        mov eax, ecx
        pop ecx
        ret
    """


@T("t_pop_ratio")
def _():
    # pop 4x call-redirect: Sprite_draw_2(dest==strip canvas, num=den=1) ->
    # (g,16); gate on the NATIVE 1/1 (shared-field law) and dest.
    # v2 (2026-09-20): the tail is thunk_sprite_bilinear, not the engine draw --
    # the citizen faces carry their own 1:1 scanline dither (drone red/dark-red,
    # worker navy/black) and the engine's source-driven NN banded it at g=22/25
    # and dropped the last source column at 25/16 (the F4 faces' defect, rw
    # kinds v4/v5).  Law scaling_laws.basewin_pop_face_enlarge.  The untouched
    # 1/1 (g<=16, foreign dest) fails the bilinear's num>den guard, which
    # tail-jumps Sprite_draw_2 with the entry stack intact: native byte-path.
    # v3 (2026-09-20): the tail is thunk_face_hybrid (scaling_laws.face_hybrid_enlarge;
    # basewin_pop_face_enlarge == 'hybrid'): the average only softened the baked
    # scanline background, the hybrid regenerates it at device density.  Same
    # contract and guard set (g<=16 or num<=den -> Sprite_draw_2, stack intact).
    return f"""
        cmp dword ptr [{G:#x}], 0x10
        jle nat
        cmp dword ptr [esp+4], {STRIP_CANVAS:#x}
        jne nat
        cmp dword ptr [esp+0x14], 1
        jne nat
        cmp dword ptr [esp+0x18], 1
        jne nat
        mov eax, dword ptr [{G:#x}]
        mov [esp+0x14], eax
        mov dword ptr [esp+0x18], 0x10
    nat:
        jmp {FACE_HYBRID:#x}
    """


@T("t_garr_cell38")
def _():
    # Neutral original (C7 mov-imm store) -> flag-transparent.
    return f"""
        pushfd
        push eax
        mov eax, 0x38
        {sc('eax')}
        mov [ebp-0x20], eax
        pop eax
        popfd
        ret
    """


@T("t_garr_stats38")
def _():
    # Neutral original (C7 mov-imm store) -> flag-transparent.
    return f"""
        pushfd
        push eax
        mov eax, 0x38
        {sc('eax')}
        mov [ebp-0x34], eax
        pop eax
        popfd
        ret
    """


@T("t_garr_fitdiv")
def _():
    # garr 0x41056d(6B): W / (cell + s(5)); EDX free (CDQ overwrites).
    return f"""
        mov edx, 5
        {sc('edx')}
        add ecx, edx
        cdq
        idiv ecx
        ret
    """


@T("t_garr_sq1")
def _():
    # garr 0x4105b4(6B): ECX=EAX+s(1); EAX=EDX-s(1) (squeeze region edges).
    # Neutral original (lea/lea) -> flag-transparent.
    return f"""
        pushfd
        push esi
        mov esi, eax
        mov eax, 1
        {sc('eax')}
        lea ecx, [esi+eax]
        neg eax
        add eax, edx
        pop esi
        popfd
        ret
    """


@T("t_garr_sq5")
def _():
    # garr 0x4105ca(6B): EAX-=s(5); [ebp-0x20]=EAX (squeeze cell width).
    return f"""
        push ecx
        mov ecx, eax
        mov eax, 5
        {sc('eax')}
        sub ecx, eax
        mov eax, ecx
        pop ecx
        mov [ebp-0x20], eax
        ret
    """


@T("t_garr_statsy")
def _():
    # garr 0x410777(5B): stats-text y.  Vanilla: ECX(bottom) - EDX(font line
    # height) + 6.  v2 (07-25e): scaling only the +6 left EDX as the SCALED
    # font's line height, which is SUBLINEAR (22 at g=25 vs faithful 28) ->
    # digits sat low and their bottoms crossed the panel clip.  Scaled path
    # now replaces the metric with the scaled NATIVE metric 18 (MEASURED
    # from the vanilla 1024 capture): ECX -= fl(18g/16) - fl(6g/16)
    # (law basewin_strip_garrison_stats_y).  g<=16 runs the vanilla metric
    # path -> identity by construction.
    return f"""
        push eax
        mov eax, dword ptr [{G:#x}]
        cmp eax, 0x10
        jle gsy_nat
        mov eax, 18
        imul eax, dword ptr [{G:#x}]
        sar eax, 4
        sub ecx, eax
        mov eax, 6
        imul eax, dword ptr [{G:#x}]
        sar eax, 4
        add ecx, eax
        pop eax
        ret
    gsy_nat:
        sub ecx, edx
        add ecx, 6
        pop eax
        ret
    """


@T("t_qrow_h_ecx")
def _():
    # queue 0x415371(17B): ECX = row height for the engine's 1-based row
    # counter EDI.  Vanilla reads the row font's line height from the
    # [ebp-0x74] metric block; the SCALED font's metric is sublinear (18 at
    # g=25 / 27 at g=40 vs faithful 20.3/32.5) -> cramped rows (07-25e user
    # report).  Scaled: the remainder-distributed vanilla pitch 13
    # (law basewin_strip_queue_row_advance): cum(i)=fl(13*i*g/16), h =
    # cum(EDI)-cum(EDI-1) -- cumulative floor, never i*floor.  g<=16
    # re-runs the vanilla metric read (identity by construction).  EAX/EDX
    # free at the site (rewritten before any read downstream of the cut).
    return f"""
        cmp dword ptr [{G:#x}], 0x10
        jle qa_nat
        mov ecx, edi
        imul ecx, ecx, 13
        imul ecx, dword ptr [{G:#x}]
        sar ecx, 4
        lea eax, [edi-1]
        imul eax, eax, 13
        imul eax, dword ptr [{G:#x}]
        sar eax, 4
        sub ecx, eax
        ret
    qa_nat:
        mov eax, [ebp-0x74]
        test eax, eax
        jl qa_neg
        mov ecx, [ebp-0x64]
        add ecx, eax
        ret
    qa_neg:
        mov ecx, [ebp-0x68]
        ret
    """


@T("t_qrow_h_eax")
def _():
    # queue 0x415695(17B): the row-y ADVANCE (ADD EBX,EAX follows the cut) --
    # same law/height as t_qrow_h_ecx but result in EAX (ECX/EDX free).
    # Cumulative sum telescopes: y_k = y0 + fl(13*k*g/16) exactly.
    return f"""
        cmp dword ptr [{G:#x}], 0x10
        jle qb_nat
        mov eax, edi
        imul eax, eax, 13
        imul eax, dword ptr [{G:#x}]
        sar eax, 4
        lea ecx, [edi-1]
        imul ecx, ecx, 13
        imul ecx, dword ptr [{G:#x}]
        sar ecx, 4
        sub eax, ecx
        ret
    qb_nat:
        mov eax, [ebp-0x74]
        test eax, eax
        jl qb_neg
        mov ecx, [ebp-0x64]
        add eax, ecx
        ret
    qb_neg:
        mov eax, [ebp-0x68]
        ret
    """


@T("t_garr_adv5")
def _():
    # garr 0x4107b8(6B): ECX=EAX; EAX=EDI+EDX+s(5) (cell x advance).
    # Neutral original (mov/lea) -> flag-transparent.
    return f"""
        pushfd
        mov ecx, eax
        mov eax, 5
        {sc('eax')}
        add eax, edx
        add eax, edi
        popfd
        ret
    """


@T("t_sup_scale")
def _():
    # sup 2x(20B): SCALE_NUM_G/DEN_G = (10,16) native, (10g,256) scaled — the
    # exact-fraction rule (basewin_sprite_ratio); raw literals at g<=16 keep
    # the blit core's value-compared scale cache byte-identical.
    # Neutral original (two C7 mov-imm stores) -> flag-transparent.
    return f"""
        pushfd
        push eax
        mov eax, dword ptr [{G:#x}]
        cmp eax, 0x10
        jle nat
        imul eax, eax, 10
        mov [{SCALE_NUM_G:#x}], eax
        mov dword ptr [{SCALE_DEN_G:#x}], 0x100
        pop eax
        popfd
        ret
    nat:
        mov dword ptr [{SCALE_NUM_G:#x}], 0xA
        mov dword ptr [{SCALE_DEN_G:#x}], 0x10
        pop eax
        popfd
        ret
    """


def _mem_imm(imm, disp):
    # replaces a flag-neutral `MOV [ebp-disp], imm` -> must be flag-transparent
    # (same law as the MOV-imm family above).
    return f"""
        pushfd
        push eax
        mov eax, {imm:#x}
        {sc('eax')}
        mov [ebp-{disp:#x}], eax
        pop eax
        popfd
        ret
    """


THUNK_ASM["t_sup_cell"] = lambda: _mem_imm(0x3E, 0x38)
THUNK_ASM["t_sup_row"] = lambda: _mem_imm(0x2E, 0x4C)
THUNK_ASM["t_sup_icon1"] = lambda: _mem_imm(0xD, 0x5C)
THUNK_ASM["t_sup_icon2"] = lambda: _mem_imm(0xD, 0x64)


@T("t_sup_fit1")
def _():
    # sup 0x40cb65(5B): EAX = (EAX-ECX) - s(0xc) (column-fit width pad).
    return f"""
        sub eax, ecx
        push ecx
        mov ecx, eax
        mov eax, 0xC
        {sc('eax')}
        neg eax
        add eax, ecx
        pop ecx
        ret
    """


@T("t_sup_fit2")
def _():
    # sup 0x40cbd2(6B): EAX-=s(0xc); EDI-=s(0xc).
    return f"""
        push ecx
        mov ecx, eax
        mov eax, 0xC
        {sc('eax')}
        sub ecx, eax
        sub edi, eax
        mov eax, ecx
        pop ecx
        ret
    """


@T("t_info_pad")
def _():
    # info 0x415c01(7B): EAX = -s(6 + [chevron w]) (plate inner-frame pad;
    # ECX = the native +0xcaec width — single floor over the sum).
    return f"""
        mov eax, 6
        add eax, ecx
        {sc('eax')}
        neg eax
        ret
    """


@T("t_chev_btn2")
def _():
    # BaseWin_init 0x41f9f5(34B): plate chevron btn2 window rect = [plate.l+3,
    # plate.t+3, +sprite.w(+0xcaec), +sprite.h(+0xcaf0)] -> inset and sprite
    # dims scale s(k); the art stays native (btnzoom KSB fills the window;
    # CEIL descale round-trips every k at g>16). Law
    # basewin_strip_chevron_rects. Entry: ecx=plate.l, edx=plate.t,
    # esi=BaseWin_g; ebx dead (reloaded 0x41fa1d). Exit: ecx=l, edx=t, eax=b,
    # [ebp-0x24/-0x1c/-0x20/-0x18]=l/r/t/b. Vanilla's cut flags are dead
    # (next writer 0x41fa48); both paths still end add-eax,edx like vanilla.
    return f"""
        push ebx
        mov ebx, dword ptr [{G:#x}]
        cmp ebx, 0x10
        jle cb2_nat
        imul ebx, ebx, 3
        sar ebx, 4
        add ecx, ebx
        add edx, ebx
        mov eax, dword ptr [esi+0xcaec]
        imul eax, dword ptr [{G:#x}]
        sar eax, 4
        add eax, ecx
        mov dword ptr [ebp-0x24], ecx
        mov dword ptr [ebp-0x1c], eax
        mov eax, dword ptr [esi+0xcaf0]
        imul eax, dword ptr [{G:#x}]
        sar eax, 4
        add eax, edx
        mov dword ptr [ebp-0x20], edx
        mov dword ptr [ebp-0x18], eax
        pop ebx
        ret
    cb2_nat:
        add ecx, 3
        add edx, 3
        mov eax, dword ptr [esi+0xcaec]
        add eax, ecx
        mov dword ptr [ebp-0x24], ecx
        mov dword ptr [ebp-0x1c], eax
        mov eax, dword ptr [esi+0xcaf0]
        add eax, edx
        mov dword ptr [ebp-0x20], edx
        mov dword ptr [ebp-0x18], eax
        pop ebx
        ret
    """


@T("t_chev_btn3")
def _():
    # BaseWin_init 0x41fac0(9B): btn3 (right chevron): eax = s(sprite.w),
    # ecx = plate.r - s(3). Vanilla continues edx=ecx; [ebp-0x1c]=ecx;
    # edx-=eax (=l). t/b locals still hold btn2's scaled values. Cut flags
    # dead (ADD ESP,8 immediately follows).
    return f"""
        push ebx
        mov ebx, dword ptr [{G:#x}]
        cmp ebx, 0x10
        jle cb3_nat
        imul ebx, ebx, 3
        sar ebx, 4
        sub ecx, ebx
        mov eax, dword ptr [esi+0xcaec]
        imul eax, dword ptr [{G:#x}]
        sar eax, 4
        pop ebx
        ret
    cb3_nat:
        mov eax, dword ptr [esi+0xcaec]
        sub ecx, 3
        pop ebx
        ret
    """


@T("t_info_titleb")
def _():
    # info 0x415c15(7B): title-box top/bottom. Vanilla: ESI(=plate.t)+=EBX(s3);
    # EDX(=plate.b)-=EBX; [ebp-0x4]=EDX. Scaled: bottom = ESI + s(35) - 1 —
    # size-anchored to the chevron KSB fill so the title stroke stays flush
    # with the chevron art bottom (law basewin_title_box; the 3px "chevron
    # sits high" defect was plate.b - s3 diverging from s3 + s35). EAX dead
    # (reloaded 0x415c35); cut flags dead (next reader inside 0x5e2dd3).
    return f"""
        add esi, ebx
        mov eax, dword ptr [{G:#x}]
        cmp eax, 0x10
        jle tb_nat
        imul eax, eax, 35
        sar eax, 4
        lea edx, [esi+eax-1]
        mov dword ptr [ebp-0x4], edx
        ret
    tb_nat:
        sub edx, ebx
        mov dword ptr [ebp-0x4], edx
        ret
    """


@T("t_info_btnframe")
def _():
    # info 0x415b4f(18B): staple-ring frame rect r/b. Vanilla: EDX(=r)+=EBX(s3);
    # ECX=0x7aec64; EDI=[EDI+0xc](=b); [ebp-8]=EDX; EDI+=EBX; [ebp-4]=EDI.
    # Scaled: r/b -> r/b + s3 - 1 (law basewin_redbtn_frame): the art window
    # is w = r-l off the same fields (art spans [l, r-1], exclusive right)
    # and vanilla's 9-slice strokes at coordinate-1 where our thick band ends
    # AT the coordinate — without the -1 the ring's right/bottom channels run
    # exactly 1px wider than left/top at every scaled g. Cut flags dead (next
    # is call 0x5d8000); nat path ends on the same add edi,ebx as vanilla.
    return f"""
        mov ecx, 0x7aec64
        mov edi, dword ptr [edi+0xc]
        cmp dword ptr [{G:#x}], 0x10
        jle bf_nat
        add edx, ebx
        dec edx
        add edi, ebx
        dec edi
        mov dword ptr [ebp-0x8], edx
        mov dword ptr [ebp-0x4], edi
        ret
    bf_nat:
        add edx, ebx
        add edi, ebx
        mov dword ptr [ebp-0x8], edx
        mov dword ptr [ebp-0x4], edi
        ret
    """


@T("t_spotck_nat")
def _():
    # 3x call-redirect (hover 0x416c72 / lbdown 0x41b1ab / lbup 0x41b305):
    # Spot_check on the NATIVE-space spot set BaseWin+0x40ec0 (map area +
    # facilities rows — their Spot_add sites 0x40f1ac/0x410337 register
    # vanilla-native rects). Descale the device mouse x/y in place with the
    # exact point inverse (16*dev+15)/g (law descale_point), then tail-jmp
    # Spot_check; its RET 0x10 unwinds to the original caller. ECX (this)
    # preserved; eax/edx are callee-scratch.
    return f"""
        cmp dword ptr [{G:#x}], 0x10
        jle sk_tail
        push ecx
        mov ecx, dword ptr [{G:#x}]
        mov eax, dword ptr [esp+8]
        shl eax, 4
        add eax, 15
        cdq
        idiv ecx
        mov dword ptr [esp+8], eax
        mov eax, dword ptr [esp+0xc]
        shl eax, 4
        add eax, 15
        cdq
        idiv ecx
        mov dword ptr [esp+0xc], eax
        pop ecx
    sk_tail:
        jmp {SPOT_CHECK:#x}
    """


@T("t_tilepick_nat")
def _():
    # BaseWin map pixel->tile 0x409100 entry cut (9B: prologue + first field
    # load). The fn is entirely vanilla-native space (bounds 0..0x180/0..0xc0,
    # tile divisors, spot set +0x40ecc); EVERY caller passes device coords
    # (live mouse or the raw-stored click pair +0x40b44/48), so this entry is
    # the single choke point: rebuild the prologue, descale [ebp+8]/[ebp+0xc]
    # in place (args die with the RET 8), replay the field load, resume.
    return f"""
        pop edx
        push ebp
        mov ebp, esp
        push edx
        pushfd
        mov eax, dword ptr [{G:#x}]
        cmp eax, 0x10
        jle tp_done
        push ecx
        mov ecx, eax
        mov eax, dword ptr [ebp+8]
        shl eax, 4
        add eax, 15
        cdq
        idiv ecx
        mov dword ptr [ebp+8], eax
        mov eax, dword ptr [ebp+0xc]
        shl eax, 4
        add eax, 15
        cdq
        idiv ecx
        mov dword ptr [ebp+0xc], eax
        pop ecx
    tp_done:
        popfd
        mov eax, dword ptr [ecx+0x40b94]
        ret
    """


@T("t_fontinit")
def _():
    # 10x call-redirect: strip fn-LOCAL Font_init sizes scale at their sites
    # (device-space layout; law fonts entry of basewin_strip_content).
    return f"""
        cmp dword ptr [{G:#x}], 0x10
        jle nat
        mov edx, [esp+8]
        imul edx, dword ptr [{G:#x}]
        sar edx, 4
        mov [esp+8], edx
    nat:
        jmp {FONT_INIT:#x}
    """


@T("t_sf_strip")
def _():
    # 2x call-redirect (queue/supported header): swap the SHARED 14-bold for
    # the cave Font re-inited at fl(14*g/16) (sf_core recipe; Font_init frees
    # the prior HFONT).
    return f"""
        cmp dword ptr [{G:#x}], 0x10
        jle nat
        cmp ecx, {STRIP_CANVAS:#x}
        jne nat
        cmp dword ptr [esp+4], {SHARED_FONT:#x}
        jne nat
        mov eax, dword ptr [{G:#x}]
        imul eax, eax, 14
        sar eax, 4
        push ecx
        push 1
        push eax
        push dword ptr [{HUD_FONT_NAME:#x}]
        mov ecx, {G_BW_FONT:#x}
        call {FONT_INIT:#x}
        pop ecx
        mov dword ptr [esp+4], {G_BW_FONT:#x}
    nat:
        jmp {SET_FONT:#x}
    """


@T("t_findfont")
def _():
    # info 2x call-redirect: find_font's table caps at 40 -> above native the
    # name font is a cave Font at fl(size*g/16) with the POOL's face law for the
    # NATIVE size (t_ffn_at: S > 12 -> Arial Narrow + bold|variant, else Arial;
    # v2 2026-09-17, audit finding 3.10 -- v1 Font_init'd "Arial" at every S) on
    # its own keyed slot g_font_bwname; returns it in EAX (cdecl, caller cleans).
    # Slot is FROZEN at 0xd73c..0xd778 (the next thunk's offset, see assemble_all).
    return f"""
        cmp dword ptr [{G:#x}], 0x10
        jle nat
        push ecx
        push dword ptr [{G:#x}]
        push dword ptr [esp+0x10]
        push dword ptr [esp+0x10]
        push {G_FONT_BWNAME:#x}
        call {T_FFN_AT:#x}
        add esp, 0x10
        pop ecx
        ret
    nat:
        jmp {FIND_FONT:#x}
    """


# ---- site tables -----------------------------------------------------------
# CUTS: (site_id, va, len, original_hex, thunk)
CUTS = [
    ("BaseWin_draw_production.ghost5", 0x40E478, 50,
     "8B 02 89 45 E4 8B 42 04 83 E8 05 8B 4A 08 83 C1 05 8B 52 0C 89 55 F0"
     " 8B 55 E4 83 EA 05 89 55 E4 8B 55 F0 83 C2 05 83 C0 0A 89 55 F0"
     " 89 45 E8 83 E9 0A", "t_prod_ghost5"),
    ("BaseWin_draw_production.union3", 0x40E4EF, 5,
     "B8 03 00 00 00", "t_mov_eax_s3"),
    ("BaseWin_draw_production.union6", 0x40E50F, 6,
     "03 F0 6A 06 6A 06", "t_prod_union6"),
    ("BaseWin_draw_production.inner3", 0x40E582, 44,
     "8B 06 83 C0 03 8B 4E 04 89 45 E4 83 C1 03 8D 45 E4 8B 56 08 89 4D E8"
     " 83 EA 03 50 8B 76 0C B9 64 EC 7A 00 83 EE 03 89 55 EC 89 75 F0",
     "t_prod_inner3"),
    ("BaseWin_draw_production.post3", 0x40E5B9, 5,
     "B8 03 00 00 00", "t_mov_eax_s3"),
    ("BaseWin_draw_production.pic28", 0x40E685, 10,
     "8B 55 E8 8B D8 83 C2 28 D1 FB", "t_prod_pic28"),
    ("BaseWin_draw_production.name41_veh", 0x40E7FD, 9,
     "8B 4D E8 8D 14 76 83 C1 41", "t_prod_name41c"),
    ("BaseWin_draw_production.pad2_veh", 0x40E965, 5,
     "BA 02 00 00 00", "t_mov_edx_s2"),
    ("BaseWin_draw_production.iconsz", 0x40EA46, 6,
     "6A 28 50 8B 45 E0", "t_prod_iconsz"),
    ("BaseWin_draw_production.iconxy", 0x40EA4C, 6,
     "83 C0 EC 83 C3 EC", "t_prod_iconxy"),
    ("BaseWin_draw_production.name41_fac", 0x40EA60, 12,
     "8B 5D E8 8D 34 7F C1 E6 04 83 C3 41", "t_prod_name41b"),
    ("BaseWin_draw_production.pad2_fac", 0x40EADC, 5,
     "BA 02 00 00 00", "t_mov_edx_s2"),
    ("BaseWin_draw_production.bar2a", 0x40EB77, 5,
     "8D 14 3F 3B D3", "t_bar2a"),
    ("BaseWin_draw_production.bar2b", 0x40EB8B, 7,
     "89 7D D8 D1 E0 3B C6", "t_bar2b"),
    ("BaseWin_draw_production.bar2c", 0x40EB98, 7,
     "99 F7 FF D1 E0 3B C6", "t_bar2c"),
    ("BaseWin_draw_production.barthresh", 0x40EC28, 23,
     "83 FB 08 7D 06 49 89 4D C0 EB 0C 40 49 46 89 45 B8 89 4D C0 89 75 BC",
     "t_barthresh"),
    ("BaseWin_draw_production.bardec", 0x40EC3F, 6,
     "8B 5D A0 4A 85 DB", "t_bardec"),
    ("BaseWin_draw_flash.ghost5", 0x40D399, 54,
     "8B 17 83 EA 05 8B 47 04 89 55 E0 83 E8 05 8D 55 E0 8B 4F 08 83 C0 0A"
     " 83 C1 05 89 45 E4 8B 7F 0C 83 E9 0A 89 4D E8 8D 4D A4 83 C7 05 51 52"
     " B9 64 EC 7A 00 89 7D EC", "t_flash_ghost5"),
    ("BaseWin_draw_flash.union3", 0x40D3EF, 5,
     "BB 03 00 00 00", "t_mov_ebx_s3"),
    ("BaseWin_draw_flash.union6", 0x40D412, 6,
     "03 FB 6A 06 6A 06", "t_flash_union6"),
    ("BaseWin_draw_flash.pic28", 0x40D517, 6,
     "8D 04 49 8D 5A 28", "t_flash_pic28"),
    ("BaseWin_draw_flash.name41", 0x40D593, 9,
     "8B 45 E4 8D 34 8F 83 C0 41", "t_flash_name41"),
    ("BaseWin_draw_flash.pad2", 0x40D622, 5,
     "B9 02 00 00 00", "t_mov_ecx_s2"),
    ("BaseWin_draw_queue.hdr3", 0x4151EC, 5,
     "B8 03 00 00 00", "t_mov_eax_s3"),
    ("BaseWin_draw_queue.listx5", 0x4152E8, 5,
     "B8 05 00 00 00", "t_mov_eax_s5"),
    ("BaseWin_draw_queue.listy2", 0x41530B, 5,
     "B8 02 00 00 00", "t_mov_eax_s2"),
    ("BaseWin_draw_queue.rowh", 0x415371, 17,
     "8B 45 8C 85 C0 7C 07 8B 4D 9C 03 C8 EB 03 8B 4D 98", "t_qrow_h_ecx"),
    ("BaseWin_draw_queue.rowadv", 0x415695, 17,
     "8B 45 8C 85 C0 7C 07 8B 4D 9C 03 C1 EB 03 8B 45 98", "t_qrow_h_eax"),
    ("BaseWin_draw_pop.inner3", 0x414C27, 44,
     "8B 06 83 C0 03 8B 4E 04 89 45 B8 83 C1 03 8D 45 B8 8B 56 08 89 4D BC"
     " 83 EA 03 50 8B 76 0C B9 64 EC 7A 00 83 EE 03 89 55 C0 89 75 C4",
     "t_pop_inner3"),
    ("BaseWin_draw_pop.c30_a", 0x414D65, 6,
     "89 45 E8 83 C0 D0", "t_pop_c30"),
    ("BaseWin_draw_pop.c30_b", 0x414DFA, 6,
     "89 45 E8 83 C0 D0", "t_pop_c30"),
    ("BaseWin_draw_pop.c30_c", 0x414EF7, 6,
     "89 45 E8 83 C0 D0", "t_pop_c30"),
    ("BaseWin_draw_pop.c30_d", 0x414FA7, 6,
     "89 45 E8 83 C0 D0", "t_pop_c30"),
    ("BaseWin_draw_garrison.inner3", 0x4104B1, 5,
     "B8 03 00 00 00", "t_mov_eax_s3"),
    ("BaseWin_draw_garrison.cell38", 0x4104FB, 7,
     "C7 45 E0 38 00 00 00", "t_garr_cell38"),
    ("BaseWin_draw_garrison.fitdiv", 0x41056D, 6,
     "99 83 C1 05 F7 F9", "t_garr_fitdiv"),
    ("BaseWin_draw_garrison.sq1", 0x4105B4, 6,
     "8D 48 01 8D 42 FF", "t_garr_sq1"),
    ("BaseWin_draw_garrison.sq5", 0x4105CA, 6,
     "83 E8 05 89 45 E0", "t_garr_sq5"),
    ("BaseWin_draw_garrison.stats38", 0x410768, 7,
     "C7 45 CC 38 00 00 00", "t_garr_stats38"),
    ("BaseWin_draw_garrison.statsy6", 0x410777, 5,
     "2B CA 83 C1 06", "t_garr_statsy"),
    ("BaseWin_draw_garrison.adv5", 0x4107B8, 6,
     "8B C8 8D 44 17 05", "t_garr_adv5"),
    ("BaseWin_draw_supported.hdr3", 0x40C964, 5,
     "B8 03 00 00 00", "t_mov_eax_s3"),
    ("BaseWin_draw_supported.list3", 0x40CA56, 5,
     "B8 03 00 00 00", "t_mov_eax_s3"),
    ("BaseWin_draw_supported.scale_a", 0x40CAA4, 20,
     "C7 05 18 6D 69 00 0A 00 00 00 C7 05 1C 6D 69 00 10 00 00 00",
     "t_sup_scale"),
    ("BaseWin_draw_supported.cell3e", 0x40CACD, 7,
     "C7 45 C8 3E 00 00 00", "t_sup_cell"),
    ("BaseWin_draw_supported.row2e", 0x40CAE9, 7,
     "C7 45 B4 2E 00 00 00", "t_sup_row"),
    ("BaseWin_draw_supported.icon1", 0x40CB04, 7,
     "C7 45 A4 0D 00 00 00", "t_sup_icon1"),
    ("BaseWin_draw_supported.icon2", 0x40CB1F, 7,
     "C7 45 9C 0D 00 00 00", "t_sup_icon2"),
    ("BaseWin_draw_supported.fit1", 0x40CB65, 5,
     "2B C1 83 E8 0C", "t_sup_fit1"),
    ("BaseWin_draw_supported.fit2", 0x40CBD2, 6,
     "83 E8 0C 83 C7 F4", "t_sup_fit2"),
    ("BaseWin_draw_supported.scale_b", 0x40CD8B, 20,
     "C7 05 18 6D 69 00 0A 00 00 00 C7 05 1C 6D 69 00 10 00 00 00",
     "t_sup_scale"),
    ("BaseWin_draw_info.pad3", 0x415B2B, 5,
     "BB 03 00 00 00", "t_mov_ebx_s3"),
    ("BaseWin_draw_info.chevpad", 0x415C01, 7,
     "B8 FA FF FF FF 2B C1", "t_info_pad"),
    # -- slice 2b: plate chevron button WINDOW rects (BaseWin_init; audit
    # reads _tmp_disasm_basewin_init.txt for these two)
    ("BaseWin_init.chev_btn2", 0x41F9F5, 34,
     "83 C1 03 8B 86 EC CA 00 00 83 C2 03 03 C1 89 4D DC 89 45 E4"
     " 8B 86 F0 CA 00 00 03 C2 89 55 E0 89 45 E8", "t_chev_btn2"),
    ("BaseWin_init.chev_btn3", 0x41FAC0, 9,
     "8B 86 EC CA 00 00 83 E9 03", "t_chev_btn3"),
    # -- slice 2c: title-box flush + native-space hit path (audit reads
    # _tmp_disasm_hitfix.txt for 0x409100 and the redirect sites)
    ("BaseWin_draw_info.titleb", 0x415C15, 7,
     "03 F3 2B D3 89 55 FC", "t_info_titleb"),
    ("BaseWin_draw_info.btnframe", 0x415B4F, 18,
     "03 D3 B9 64 EC 7A 00 8B 7F 0C 89 55 F8 03 FB 89 7D FC",
     "t_info_btnframe"),
    ("BaseWin_map_to_tile.entry", 0x409100, 9,
     "55 8B EC 8B 81 94 0B 04 00", "t_tilepick_nat"),
]

# REDIRECTS: (site_id, va, original_hex, thunk)
REDIRECTS = [
    ("BaseWin_draw_production.font_a", 0x40E62D, "E8 0E A9 20 00", "t_fontinit"),
    ("BaseWin_draw_production.font_b", 0x40E643, "E8 F8 A8 20 00", "t_fontinit"),
    ("BaseWin_draw_flash.font_a", 0x40D4E5, "E8 56 BA 20 00", "t_fontinit"),
    ("BaseWin_draw_flash.font_b", 0x40D4FB, "E8 40 BA 20 00", "t_fontinit"),
    ("BaseWin_draw_queue.font_800", 0x415158, "E8 E3 3D 20 00", "t_fontinit"),
    ("BaseWin_draw_queue.font_a", 0x41517D, "E8 BE 3D 20 00", "t_fontinit"),
    ("BaseWin_draw_queue.font_b", 0x41519B, "E8 A0 3D 20 00", "t_fontinit"),
    ("BaseWin_draw_pop.font", 0x414C12, "E8 29 43 20 00", "t_fontinit"),
    ("BaseWin_draw_garrison.font", 0x410445, "E8 F6 8A 20 00", "t_fontinit"),
    ("BaseWin_draw_supported.font", 0x40C916, "E8 25 C6 20 00", "t_fontinit"),
    ("BaseWin_draw_queue.sf_hdr", 0x41521A, "E8 51 5A 1C 00", "t_sf_strip"),
    ("BaseWin_draw_supported.sf_hdr", 0x40C98F, "E8 DC E2 1C 00", "t_sf_strip"),
    ("BaseWin_draw_info.findfont_a", 0x415D17, "E8 D4 25 17 00", "t_findfont"),
    ("BaseWin_draw_info.findfont_b", 0x415D5D, "E8 8E 25 17 00", "t_findfont"),
    ("BaseWin_draw_pop.ratio_a", 0x414D90, "E8 B5 FD 1C 00", "t_pop_ratio"),
    ("BaseWin_draw_pop.ratio_b", 0x414E23, "E8 22 FD 1C 00", "t_pop_ratio"),
    ("BaseWin_draw_pop.ratio_c", 0x414F38, "E8 0D FC 1C 00", "t_pop_ratio"),
    ("BaseWin_draw_pop.ratio_d", 0x414FCD, "E8 78 FB 1C 00", "t_pop_ratio"),
    ("BaseWin_hover.spotck_nat", 0x416C72, "E8 89 3E 1E 00", "t_spotck_nat"),
    ("BaseWin_lbdown.spotck_nat", 0x41B1AB, "E8 50 F9 1D 00", "t_spotck_nat"),
    ("BaseWin_lbup.spotck_nat", 0x41B305, "E8 F6 F7 1D 00", "t_spotck_nat"),
]

FN_RANGES = [(0x40C850, 0x40D24C), (0x40D250, 0x40E35B), (0x40E360, 0x40F0E5),
             (0x4103B0, 0x410868), (0x414B40, 0x415078), (0x415080, 0x415724),
             (0x415B20, 0x415DCE)]

DISASM = os.path.join(os.path.dirname(__file__), "..",
                      "_tmp_disasm_strip_fns.txt")
# slice-2b chevron-window cuts live in BaseWin_init, not the strip draw fns
DISASM_INIT = os.path.join(os.path.dirname(__file__), "..",
                           "_tmp_disasm_basewin_init.txt")
# slice-2c hit-path sites (0x409100 fn + the three Spot_check redirect sites)
DISASM_HITFIX = os.path.join(os.path.dirname(__file__), "..",
                             "_tmp_disasm_hitfix.txt")


def assemble_all():
    """-> (layout {thunk: (off, blob)}, end_off). Deterministic order."""
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    layout = {}
    off = THUNKS_OFF
    for name in sorted(THUNK_ASM):
        if name in FROZEN:                      # a predecessor shrank: keep the baked slot map
            assert off <= FROZEN[name], (name, off, FROZEN[name])
            off = FROZEN[name]
        _lbl[0] = 0
        code, _ = ks.asm(THUNK_ASM[name](), addr=PCAVE2_VA + off)
        blob = bytes(code)
        layout[name] = (off, blob)
        off += len(blob)
        off = (off + 3) & ~3
    return layout, off


# Frozen offsets: when a thunk gets SHORTER the packer would slide every later thunk down and
# invalidate the baked yaml/site map; pin the successor at its baked offset instead.
FROZEN = {"t_flash_ghost5": 0xd778}   # t_findfont v2 (2026-09-17) 57B -> 46B


def audit(layout):
    """Original-bytes + branch-into-cut audit against the disasm dump."""
    if not os.path.exists(DISASM):
        print("[audit] disasm dump missing — SKIPPED")
        return
    insns = []
    for path in (DISASM, DISASM_INIT, DISASM_HITFIX):
        if not os.path.exists(path):
            continue
        for ln in open(path, encoding="utf-8", errors="replace"):
            m = re.match(r"\s+([0-9a-f]{8})\s+([0-9A-F ]+?)\s{2,}(\S.*)", ln)
            if m:
                insns.append((int(m.group(1), 16),
                              bytes.fromhex(m.group(2).replace(" ", "")),
                              m.group(3).strip()))
    by_va = {va: (b, t) for va, b, t in insns}
    # original bytes byte-exact
    stream = {}
    for va, b, _t in insns:
        for i, x in enumerate(b):
            stream[va + i] = x
    for sid, va, ln_, orig, _ in CUTS:
        want = bytes.fromhex(orig.replace(" ", ""))
        assert len(want) == ln_, f"{sid}: len mismatch {len(want)} != {ln_}"
        got = bytes(stream[va + i] for i in range(ln_))
        assert got == want, f"{sid}: bytes mismatch at {va:#x}\n {got.hex()}\n {want.hex()}"
    for sid, va, orig, _ in REDIRECTS:
        want = bytes.fromhex(orig.replace(" ", ""))
        got = bytes(stream[va + i] for i in range(5))
        assert got == want, f"{sid}: bytes mismatch at {va:#x}"
        assert got[0] == 0xE8, f"{sid}: not a CALL"
    # no external branch targets INSIDE any cut (start byte itself is fine)
    targets = []
    for va, b, t in insns:
        m = re.search(r"\b(J\w+|CALL) 0x([0-9a-f]{8})$", t)
        if m:
            targets.append((va, int(m.group(2), 16)))
    for sid, va, ln_, _o, _t in CUTS:
        inside = range(va + 1, va + ln_)
        for src, tgt in targets:
            if tgt in inside and not (va <= src < va + ln_):
                raise AssertionError(
                    f"{sid}: external branch {src:#x} -> {tgt:#x} lands inside the cut")
    print(f"[audit] OK: {len(CUTS)} cuts + {len(REDIRECTS)} redirects byte-exact,"
          f" no external branch into any cut")


def to_tokens(blob: bytes) -> str:
    out, i = [], 0
    while i < len(blob):
        v = int.from_bytes(blob[i:i + 4], "little") if i + 4 <= len(blob) else None
        if v in SENT:
            out.append(SENT[v])
            i += 4
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    return " ".join(out)


def main() -> int:
    layout, end = assemble_all()
    assert end <= SECTION_END, f"content overruns section: {end:#x} > {SECTION_END:#x}"
    audit(layout)

    print(f"cells: g_bwsc_ret @ pcave2+{BASE_OFF:#x}, g_bwsc_tmp @ +{BASE_OFF + 4:#x},"
          f" g_bwsc_flags @ +{BASE_OFF + 8:#x}")
    print(f"thunks: pcave2+{THUNKS_OFF:#x} .. +{end:#x} (VA {PCAVE2_VA + THUNKS_OFF:#x}"
          f" .. {PCAVE2_VA + end:#x}); section end {SECTION_END:#x}\n")

    print("# ---- symbols (paste into patches.yaml symbols:) ----")
    sym_lines = [f"  g_bwsc_ret:                   {{ cave: pcave2, offset: {BASE_OFF:#x} }}   # 4B pop-ret cell (strip-content cuts; single UI thread)",
                 f"  g_bwsc_tmp:                   {{ cave: pcave2, offset: {BASE_OFF + 4:#x} }}   # 4B scratch (strip-content cuts)",
                 f"  g_bwsc_flags:                 {{ cave: pcave2, offset: {BASE_OFF + 8:#x} }}   # 4B saved EFLAGS (flag-transparent pop-ret thunks)"]
    for name in sorted(layout):
        off, blob = layout[name]
        sym_lines.append(f"  {name}:{' ' * max(1, 30 - len(name) - 3)}{{ cave: pcave2, offset: {off:#x} }}   # {len(blob)}B strip-content (src assemble_strip_content.py)")
    print("\n".join(sym_lines))
    with open(os.path.join(os.path.dirname(__file__), "..", "patches",
                           "_fragment_strip_content_symbols.yaml"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(sym_lines) + "\n")
    print()
    ids = [sid for sid, *_ in REDIRECTS] + [sid for sid, *_ in CUTS]
    with open(os.path.join(os.path.dirname(__file__), "..", "patches",
                           "_fragment_strip_content_members.yaml"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("".join(f"      - {i}\n" for i in ids))

    # per-thunk content entries (id == symbol name; the integrity guard pairs
    # symbol spans with same-named content entries). Data cells stay zero-init
    # section padding, reserved by their symbol entries.
    ce = []
    for name in sorted(layout):
        off, blob = layout[name]
        ce.append(f"      - id: {name}\n"
                  f"        offset: {off:#x}\n"
                  f'        bytes: "{to_tokens(blob)}"\n')
    with open(os.path.join(os.path.dirname(__file__), "..", "patches",
                           "_fragment_strip_content_cave.yaml"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(ce))
    print(f"# ---- {len(ce)} per-thunk cave content entries -> "
          f"_fragment_strip_content_cave.yaml ----")

    # site fragment file
    frag = []
    for sid, va, orig, thunk in REDIRECTS:
        frag.append(f"""\
  - id: {sid}
    status: confirmed
    group: basewin_strip_content
    function: {sid.split('.')[0]}
    virtual_addr: {va:#010x}
    length: 5
    original_bytes: "{orig}"
    new_bytes:      "E8 {{rel32:{thunk}}}"
    pattern: call_target_redirect
""")
    for sid, va, ln_, orig, thunk in CUTS:
        nops = " 90" * (ln_ - 5)
        frag.append(f"""\
  - id: {sid}
    status: confirmed
    group: basewin_strip_content
    function: {sid.split('.')[0]}
    virtual_addr: {va:#010x}
    length: {ln_}
    original_bytes: "{orig}"
    new_bytes:      "E8 {{rel32:{thunk}}}{nops}"
    pattern: block_cut_thunk
""")
    out = os.path.join(os.path.dirname(__file__), "..", "patches",
                       "_fragment_strip_content_sites.yaml")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(frag))
    print(f"\n[sites] {len(REDIRECTS) + len(CUTS)} entries -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
