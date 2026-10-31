#!/usr/bin/env python
"""Assembler for the scenario-editor arc BAKE (2026-08-13).

Ports the user-verified prototype hook_scenedit_fixproto.js v5 (4K + 1600
verified 2026-08-12) into pcave2 thunks.  Laws: scaling_laws.editor_panel_seeds
/ diplo_editor_layout / editor_face_* (chain-credit detection, enable
thresholds, per-pixel remap).  Evidence + 8-step plan: memory
project-smac-scenario-editor (2026-08-12c block).

New thunks (tail block 0x10640..0x11000, allocated from the LEDGER — the
2026-08-13 census confirmed the 0x9C0 contiguous free tail after
g_rm_f0col @0x1063C):

  thunk_ed_linestep    call-redirect @0x45B6C6 (the ONE Buffer_text_line_height
                       call inside painter_editor_info — census-proven single):
                       g>16 -> su(13,g), else tail-jmp 0x5DCAB0.  The global
                       0x5DCAB0 itself is NEVER touched (hot text path).
  thunk_diplo_bracket  call-redirect @0x4DBB19 (the ONE caller of
                       DiploEditWin_exec — census: no vtable ref exists; the
                       old "vtbl 0x66E964" note was wrong, that slot is
                       0x4E23C0): g>16 -> g_popup_active++ around the modal
                       (refcount, pairs with the baked exec_3 brackets).
  thunk_diplo_btnfont  shared redirect for the 4 build-time `call [eax+0xF8]`
                       button renders (0x4DB6EF/0x4DB756/0x4DB7BD/0x4DB824;
                       edi=button, eax=vtbl): stamp font0 (+0x970) =
                       find_font(su(14,g),1) BEFORE the sole render, then
                       jmp [eax+0xF8].  Cold, diplo-only (NEVER touch
                       content_draw itself).
  thunk_ed_painter     entry detour @0x45BC50 (MainWin_draw_center_mode):
                       ecx==MainWin && mode==0x3EA && g>16 && stamp fresh ->
                       copy the law rects (stashed by thunk_ed_seeds) over
                       +0xD4C/+0xD5C/+0xD6C(l,t,b).  Info RIGHT edge stays
                       engine-side (follows the live M/T/I seed).
  thunk_ed_seeds       detour @0x45B0ED (MainWin_build, post seed-derivation;
                       displaces xor eax,eax + lea ecx,[esi+0x21E2C], 8B, no
                       branch targets inside — scanned): ALWAYS run the imm
                       table (identity at g=16), then at g>16 rewrite the 25
                       palette + 6 red seed rects from the law and stash
                       unions/info + g into the g_ed_* globals.
  thunk_ed_immfix      CALL helper (only caller: thunk_ed_seeds, inside its
                       pushad): one-time VirtualProtect(PAGE_EXECUTE_READWRITE)
                       of the two imm pages via LoadLibraryA/GetProcAddress
                       (IAT 0x669120/0x669124 — VirtualProtect is NOT in the
                       exe's IAT, census-proven), then write all 31 diplo +
                       painter imms = su(native, g) each call.  su(v,16)==v so
                       the writes restore vanilla after a res downgrade.  Any
                       bootstrap failure -> bail with ZERO writes.
  thunk_ed_remap       CALL helper (only caller: thunk_btn_stripes v5, editor
                       esi range only, BEFORE thunk_fe_pair_remap — both share
                       the one phase grid so the composition is a fixed point,
                       tested): port of the proto's detectFacePair/restripeFace
                       per scaling_laws.editor_face_* — full-width column scan,
                       run-chain credits (runs<=P+1, chains>=6), enable at
                       2*w credits, fixed canonical tops, red-pair 0x6D
                       arbitration, e0/e2 family absorbing E1 strays.

In-place upgrades:
  thunk_btn_gate v7    22B esi-range prefix [0x7B7264,0x7CD098) -> HIT, then
                       the v6 body VERBATIM (188B measured; slot to 0xAAE0).
  thunk_btn_stripes v5 +21B: editor esi range -> call thunk_ed_remap before
                       the common fe_pair_remap call (slot free to 0x3160).

Emits yaml-ready hex.  Cross-checked keystone vs capstone round-trip; the
parity tests (tests/test_scenedit_asm_parity.py) emulate these exact bytes.
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000

# ---- engine / existing-cave anchors (all census-verified 2026-08-13) ------
G_SCALE       = 0x00668740        # g_popup_scale_num (menu_strip_thunks+0x540)
ENSURE_SCALE  = 0x00668760        # thunk_ensure_scale (EAX-only, idempotent)
G_POPUP_ACT   = PCAVE2 + 0x530    # g_popup_active (refcount)
FIND_FONT     = 0x005882F0        # cdecl(size, style) -> Font*
T_FFN         = PCAVE2 + 0x2E570  # t_ffn(S, v) cdecl: find_font drop-in with the face/weight law (assemble_fontlaw.py)
LINE_HEIGHT   = 0x005DCAB0        # Buffer_text_line_height (thiscall, 0 args)
DIPLO_EXEC    = 0x004DB080        # DiploEditWin_exec (thiscall RET 4)
IAT_LOADLIB   = 0x00669120        # kernel32!LoadLibraryA IAT slot
IAT_GETPROC   = 0x00669124        # kernel32!GetProcAddress IAT slot
MAINWIN       = 0x007AE820
MW_PAL        = MAINWIN + 0xADC   # paletteSeed[25] RECTs
MW_RED        = MAINWIN + 0xC6C   # redSeed[6] RECTs
SEEDS_RESUME  = 0x0045B0F5
SEEDS_TAIL    = PCAVE2 + 0x38060    # t_ed_redchain (2026-10-25 W3A, assemble_mirror_pairs.py): the seeds' tail
                                  # (the red group chained off the palette), which then resumes SEEDS_RESUME
PAINTER_RESUME = 0x0045BC56
G_FE_DST      = PCAVE2 + 0x2FA0
G_FE_W        = PCAVE2 + 0x2FAC
G_FE_H        = PCAVE2 + 0x2FB0
EDITOR_LO     = 0x007B7264        # 31 editor FlatButtons, pitch 0xB4C
EDITOR_HI     = 0x007CD098        # (measured gate census, both res)
VP_PAGE_PAINTER = 0x0045B000      # imms 0x45B5BD..0x45B60A
VP_PAGE_DIPLO   = 0x004DB000      # imms 0x4DB093..0x4DB7D8
PAGE_RWX      = 0x40              # PAGE_EXECUTE_READWRITE
PDS           = 0x006A721C        # engine PopupDialogState (thinker name)
DIPLO_DTOR    = 0x004E2240        # DiploEditWin dtor (sole call @0x4DBB2B)

# ---- new allocations (from the 0x10640..0x11000 free tail) ----------------
G_ED_STAMP   = PCAVE2 + 0x10640   # g the seed/union stash was computed for
G_ED_CW      = PCAVE2 + 0x10644   # su(43)
G_ED_CH      = PCAVE2 + 0x10648   # su(18)
G_ED_RS      = PCAVE2 + 0x1064C   # su(24)
G_ED_P3      = PCAVE2 + 0x10650   # su(3)
G_ED_PALU    = PCAVE2 + 0x10654   # 16B law pal_union
G_ED_REDU    = PCAVE2 + 0x10664   # 16B law red_union
G_ED_INFO    = PCAVE2 + 0x10674   # 12B law info l,t,b
G_VP_DONE    = PCAVE2 + 0x10680   # 1 = both imm pages RWX'd this process
G_VP_OLD     = PCAVE2 + 0x10684   # VirtualProtect lpflOldProtect sink
G_ED_CRED    = PCAVE2 + 0x10688   # 5 dwords: f0/a2/e2/c9/68 chain credits
G_ED_FL      = PCAVE2 + 0x1069C   # 5 flag bytes (+3 pad): f0,a2,e2,c9,m68
G_ED_W       = PCAVE2 + 0x106A4   # clamped rect w
G_ED_H       = PCAVE2 + 0x106A8   # clamped rect |h|
G_ED_P       = PCAVE2 + 0x106AC   # stripe period P
G_ED_MAXRUN  = PCAVE2 + 0x106B0   # P+1
G_ED_HN      = PCAVE2 + 0x106B4   # (P+1)>>1
G_ED_TOP     = PCAVE2 + 0x106B8   # current row phase (1=top member)
G_ED_STR_K32 = PCAVE2 + 0x106C0   # "KERNEL32.DLL\0"
G_ED_STR_VP  = PCAVE2 + 0x106D0   # "VirtualProtect\0"

# Packed tail: total is within ~40B of the cave end — ANY growth here means
# relocating the grown thunk (all callers are name refs except the concrete
# sites this script also emits; regenerate everything on a move).
OFF_LINESTEP = 0x106E0
OFF_BRACKET  = 0x10700
OFF_BTNFONT  = 0x10730
OFF_PAINTER  = 0x10770
OFF_SEEDS    = 0x10830
OFF_IMMFIX   = 0x10A30
OFF_IMMTAB   = 0x10AE0
OFF_EDREMAP  = 0x10C60
OFF_PDSCLEAR = 0x10FF0            # 2026-08-13b: last crumbs of the tail slack
CAVE_END     = 0x11000

SLOTS = {                          # off -> next occupied offset (hard limit)
    OFF_LINESTEP: OFF_BRACKET,
    OFF_BRACKET:  OFF_BTNFONT,
    OFF_BTNFONT:  OFF_PAINTER,
    OFF_PAINTER:  OFF_SEEDS,
    OFF_SEEDS:    OFF_IMMFIX,
    OFF_IMMFIX:   OFF_IMMTAB,
    OFF_IMMTAB:   OFF_EDREMAP,
    OFF_EDREMAP:  OFF_PDSCLEAR,
    OFF_PDSCLEAR: CAVE_END,
}

G_ED_IMMTAB = PCAVE2 + OFF_IMMTAB
THUNK_ED_IMMFIX = PCAVE2 + OFF_IMMFIX
THUNK_ED_REMAP = PCAVE2 + OFF_EDREMAP

# ---- the 31 g-dependent immediates (write_addr, native, kind) --------------
# kind: 0 = byte su, 1 = dword su, 2 = byte neg8(su).  Addresses byte-verified
# against the pristine .bak (2026-08-13 census dumps; live == bak everywhere).
IMMTAB = [
    (0x4DB093, 14, 0),    # diplo dialog font
    (0x4DB0B1, 398, 1),   # push H
    (0x4DB0B6, 758, 1),   # push W
    (0x4DB0CC, 758, 1),   # field W dupe
    (0x4DB0D6, 398, 1),   # field H dupe
    (0x4DB1AD, 4, 1),     # title band inset
    (0x4DB1CD, 20, 0),    # title band h
    (0x4DB1E0, 3, 1),     # title text inset
    (0x4DB201, 16, 0),    # title font
    (0x4DB271, 4, 0),     # list right -4
    (0x4DB278, 4, 1),     # list left 4
    (0x4DB282, 370, 1),   # list bottom
    (0x4DB289, 31, 1),    # list top
    (0x4DB299, 3, 1),     # list content inset
    (0x4DB422, 370, 1),   # chk bottom
    (0x4DB42B, 31, 1),    # chk top
    (0x4DB434, 4, 0),     # chk left +4
    (0x4DB437, 4, 0),     # chk right -4
    (0x4DB67F, 4, 0),     # btn left +4
    (0x4DB682, 4, 0),     # btn right -4
    (0x4DB68D, 2, 0),     # btn span +2
    (0x4DB690, 4, 0),     # btn bottom -4
    (0x4DB6A2, 20, 2),    # btn h (-20 imm8)
    (0x4DB6A6, 2, 2),     # btn w trim (-2 imm8)
    (0x4DB70A, 2, 0),     # btn gap #1
    (0x4DB771, 2, 0),     # btn gap #2
    (0x4DB7D8, 2, 0),     # btn gap #3
    (0x45B5D6, 10, 0),    # info font f0
    (0x45B5CA, 10, 0),    # info font f2
    (0x45B5BD, 10, 0),    # info font f1
    (0x45B607, 4, 1),     # info inset (mov ecx,imm32)
]


def asm_linestep() -> str:
    return f"""
    mov     eax, dword ptr [{G_SCALE:#x}]
    cmp     eax, 0x10
    jle     native
    imul    eax, eax, 26
    add     eax, 15
    shr     eax, 5
    ret
native:
    jmp     {LINE_HEIGHT:#x}
"""


def asm_bracket() -> str:
    return f"""
    call    {ENSURE_SCALE:#x}
    cmp     dword ptr [{G_SCALE:#x}], 0x10
    jle     native
    inc     dword ptr [{G_POPUP_ACT:#x}]
    mov     eax, [esp+4]
    push    eax
    call    {DIPLO_EXEC:#x}
    dec     dword ptr [{G_POPUP_ACT:#x}]
    ret     4
native:
    jmp     {DIPLO_EXEC:#x}
"""


def asm_pdsclear() -> str:
    # call-redirect @0x4DBB2B (the DiploEditWin dtor call on Console_editor_diplomacy's
    # accept path). VANILLA BUG fix: DiploEditWin_exec's call tree sets PopupDialogState
    # [0x6A721C]=6 and nothing on the accept path ever clears it (the picker path clears
    # its own set @0x4DB9CC) — every later BasePop then lays out with the pds=6
    # list-margin family (proven: quit modal 1886x680 margins 82/167/38/125 before vs
    # 1736x622 margins 47/52/47/45 after; frida_scenedit_popupdiag.log 2026-08-13).
    # Runs at EVERY g including 16 — the leak is vanilla's, native included.
    # eax is dead here (exec retval unread); flags not live across the replaced CALL.
    return f"""
    xor     eax, eax
    mov     dword ptr [{PDS:#x}], eax
    jmp     {DIPLO_DTOR:#x}
"""


def asm_btnfont() -> str:
    # v2 (2026-09-17, audit finding 3.6): the diplo buttons draw with the engine's default label Font
    # 0x7D3948 = Arial 12 REGULAR (probe hook_btnfont_probe.js at 1024x768); t_ffn(12, 0) = Arial
    # fl(12g/16) regular on the (12,0) slot.  v1 = find_font(su(14,g), 1) = Arial Narrow bold, size law 14.
    return f"""
    cmp     dword ptr [{G_SCALE:#x}], 0x10
    jle     tail
    pushad
    push    0
    push    12
    call    {T_FFN:#x}
    add     esp, 8
    test    eax, eax
    je      nostamp
    mov     [edi+0x970], eax
nostamp:
    popad
tail:
    jmp     dword ptr [eax+0xF8]
"""


def asm_painter() -> str:
    pairs = "".join(
        f"    mov     eax, dword ptr [{src:#x}]\n"
        f"    mov     [ecx+{dst:#x}], eax\n"
        for src, dst in (
            (G_ED_PALU, 0xD4C), (G_ED_PALU + 4, 0xD50),
            (G_ED_PALU + 8, 0xD54), (G_ED_PALU + 12, 0xD58),
            (G_ED_REDU, 0xD5C), (G_ED_REDU + 4, 0xD60),
            (G_ED_REDU + 8, 0xD64), (G_ED_REDU + 12, 0xD68),
            (G_ED_INFO, 0xD6C), (G_ED_INFO + 4, 0xD70),
            (G_ED_INFO + 8, 0xD78),        # bottom; +0xD74 (right) stays engine
        ))
    return f"""
    cmp     ecx, {MAINWIN:#x}
    jne     resume
    cmp     dword ptr [ecx+0x1E8FC], 0x3EA
    jne     resume
    push    eax
    mov     eax, dword ptr [{G_SCALE:#x}]
    cmp     eax, 0x10
    jle     unarm
    cmp     eax, dword ptr [{G_ED_STAMP:#x}]
    jne     unarm
{pairs}unarm:
    pop     eax
resume:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    push    {PAINTER_RESUME:#x}
    ret
"""


def asm_seeds() -> str:
    return f"""
    pushad
    call    {ENSURE_SCALE:#x}
    call    {THUNK_ED_IMMFIX:#x}
    mov     eax, dword ptr [{G_SCALE:#x}]
    cmp     eax, 0x10
    jle     done
    mov     eax, 43
    call    su
    mov     [{G_ED_CW:#x}], eax
    mov     eax, 18
    call    su
    mov     [{G_ED_CH:#x}], eax
    mov     eax, 24
    call    su
    mov     [{G_ED_RS:#x}], eax
    mov     eax, 3
    call    su
    mov     [{G_ED_P3:#x}], eax
    mov     edi, {MW_PAL:#x}
    xor     ebx, ebx
pcol:
    imul    eax, ebx, 44
    add     eax, 269
    call    su
    mov     ebp, eax
    xor     esi, esi
prow:
    imul    eax, esi, 19
    add     eax, 72
    call    su
    mov     [edi], ebp
    mov     [edi+4], eax
    mov     ecx, ebp
    add     ecx, [{G_ED_CW:#x}]
    mov     [edi+8], ecx
    add     eax, [{G_ED_CH:#x}]
    mov     [edi+12], eax
    add     edi, 16
    inc     esi
    cmp     esi, 5
    jl      prow
    inc     ebx
    cmp     ebx, 5
    jl      pcol
    mov     edi, {MW_RED:#x}
    xor     ebx, ebx
rcol:
    imul    eax, ebx, 25
    add     eax, 497
    call    su
    mov     ebp, eax
    xor     esi, esi
rrow:
    imul    eax, esi, 25
    add     eax, 82
    call    su
    mov     [edi], ebp
    mov     [edi+4], eax
    mov     ecx, ebp
    add     ecx, [{G_ED_RS:#x}]
    mov     [edi+8], ecx
    add     eax, [{G_ED_RS:#x}]
    mov     [edi+12], eax
    add     edi, 16
    inc     esi
    cmp     esi, 3
    jl      rrow
    inc     ebx
    cmp     ebx, 2
    jl      rcol
    mov     eax, 269
    call    su
    sub     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_PALU:#x}], eax
    mov     eax, 72
    call    su
    sub     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_PALU + 4:#x}], eax
    mov     eax, 445
    call    su
    add     eax, [{G_ED_CW:#x}]
    add     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_PALU + 8:#x}], eax
    mov     eax, 148
    call    su
    add     eax, [{G_ED_CH:#x}]
    add     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_PALU + 12:#x}], eax
    mov     eax, 497
    call    su
    sub     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_REDU:#x}], eax
    mov     eax, 82
    call    su
    sub     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_REDU + 4:#x}], eax
    mov     eax, 522
    call    su
    add     eax, [{G_ED_RS:#x}]
    add     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_REDU + 8:#x}], eax
    mov     eax, 132
    call    su
    add     eax, [{G_ED_RS:#x}]
    add     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_REDU + 12:#x}], eax
    mov     eax, [{G_ED_REDU + 8:#x}]
    add     eax, [{G_ED_P3:#x}]
    mov     [{G_ED_INFO:#x}], eax
    mov     eax, [{G_ED_REDU + 4:#x}]
    mov     [{G_ED_INFO + 4:#x}], eax
    mov     eax, [{G_ED_REDU + 12:#x}]
    mov     [{G_ED_INFO + 8:#x}], eax
    mov     eax, dword ptr [{G_SCALE:#x}]
    mov     [{G_ED_STAMP:#x}], eax
done:
    popad
    xor     eax, eax
    lea     ecx, [esi+0x21E2C]
    push    {SEEDS_TAIL:#x}
    ret
su:
    imul    eax, dword ptr [{G_SCALE:#x}]
    lea     eax, [eax*2+15]
    shr     eax, 5
    ret
"""


def asm_immfix() -> str:
    return f"""
    cmp     dword ptr [{G_VP_DONE:#x}], 0
    jne     imms
    push    {G_ED_STR_K32:#x}
    call    dword ptr [{IAT_LOADLIB:#x}]
    test    eax, eax
    je      bail
    push    {G_ED_STR_VP:#x}
    push    eax
    call    dword ptr [{IAT_GETPROC:#x}]
    test    eax, eax
    je      bail
    push    {G_VP_OLD:#x}
    push    {PAGE_RWX:#x}
    push    0x1000
    push    {VP_PAGE_PAINTER:#x}
    mov     esi, eax
    call    esi
    test    eax, eax
    je      bail
    push    {G_VP_OLD:#x}
    push    {PAGE_RWX:#x}
    push    0x1000
    push    {VP_PAGE_DIPLO:#x}
    call    esi
    test    eax, eax
    je      bail
    mov     dword ptr [{G_VP_DONE:#x}], 1
imms:
    cmp     dword ptr [{G_VP_DONE:#x}], 0
    je      bail
    mov     esi, {G_ED_IMMTAB:#x}
nexte:
    mov     eax, [esi]
    test    eax, eax
    je      bail
    mov     ecx, [esi+4]
    imul    ecx, dword ptr [{G_SCALE:#x}]
    lea     ecx, [ecx*2+15]
    shr     ecx, 5
    mov     edx, [esi+8]
    cmp     edx, 1
    je      wr4
    cmp     edx, 2
    jne     wr1
    neg     ecx
wr1:
    mov     [eax], cl
    jmp     adv
wr4:
    mov     [eax], ecx
adv:
    add     esi, 12
    jmp     nexte
bail:
    ret
"""


def asm_edremap() -> str:
    return f"""
    cmp     dword ptr [{G_SCALE:#x}], 0x10
    jle     r0
    push    ebx
    push    esi
    push    edi
    push    ebp
    cld
    mov     edi, {G_ED_CRED:#x}
    xor     eax, eax
    mov     ecx, 7
    rep stosd
    mov     ebx, [{G_FE_DST:#x}]
    test    ebx, ebx
    je      fin
    mov     esi, [ebx+0x54]
    test    esi, esi
    je      fin
    mov     eax, [{G_FE_W:#x}]
    cmp     eax, [ebx+0x80]
    jle     wok
    mov     eax, [ebx+0x80]
wok:
    test    eax, eax
    jle     fin
    mov     [{G_ED_W:#x}], eax
    mov     eax, [{G_FE_H:#x}]
    mov     ecx, [ebx+0x84]
    neg     ecx
    cmp     eax, ecx
    jle     hok
    mov     eax, ecx
hok:
    test    eax, eax
    jle     fin
    mov     [{G_ED_H:#x}], eax
    mov eax, dword ptr [0x66879c]
    mov     [{G_ED_P:#x}], eax
    lea     ecx, [eax+1]
    mov     [{G_ED_MAXRUN:#x}], ecx
    inc     eax
    shr     eax, 1
    mov     [{G_ED_HN:#x}], eax
    mov     ebp, [ebx+0x4A8]
    sub     esp, 0x14
    mov     ebx, esp
    xor     edi, edi
col:
    cmp     edi, [{G_ED_W:#x}]
    jge     detdone
    lea     edx, [esi+edi]
    mov     ecx, [{G_ED_H:#x}]
    mov     dword ptr [ebx], -1
    mov     dword ptr [ebx+4], -1
    mov     dword ptr [ebx+8], 0
    mov     dword ptr [ebx+0xC], -1
    mov     dword ptr [ebx+0x10], 0
yloop:
    movzx   eax, byte ptr [edx]
    cmp     eax, [ebx+0xC]
    jne     newrun
    inc     dword ptr [ebx+0x10]
    jmp     ynext
newrun:
    call    close_run
    mov     [ebx+0xC], eax
    mov     dword ptr [ebx+0x10], 1
ynext:
    add     edx, ebp
    dec     ecx
    jne     yloop
    call    close_run
    call    flush_chain
    inc     edi
    jmp     col
detdone:
    add     esp, 0x14
    mov     edx, [{G_ED_W:#x}]
    add     edx, edx
    mov     eax, [esp+8]
    cmp     eax, {EDITOR_LO:#x}
    jb      thr
    cmp     eax, {EDITOR_HI:#x}
    jae     thr
    xor     edx, edx
thr:
    cmp     [{G_ED_CRED:#x}], edx
    setge   byte ptr [{G_ED_FL:#x}]
    cmp     [{G_ED_CRED + 4:#x}], edx
    setge   byte ptr [{G_ED_FL + 1:#x}]
    cmp     [{G_ED_CRED + 8:#x}], edx
    setge   byte ptr [{G_ED_FL + 2:#x}]
    mov     eax, [{G_ED_CRED + 12:#x}]
    cmp     eax, edx
    jl      f4
    cmp     eax, [{G_ED_CRED + 16:#x}]
    jl      f4
    mov     byte ptr [{G_ED_FL + 3:#x}], 1
    jmp     fx
f4:
    cmp     [{G_ED_CRED + 16:#x}], edx
    jl      fx
    mov     byte ptr [{G_ED_FL + 4:#x}], 1
fx:
    mov     eax, [{G_ED_FL:#x}]
    or      eax, [{G_ED_FL + 4:#x}]
    test    eax, eax
    je      fin
    xor     ecx, ecx
row:
    cmp     ecx, [{G_ED_H:#x}]
    jge     fin
    mov     eax, ecx
    xor     edx, edx
    div     dword ptr [{G_ED_P:#x}]
    xor     eax, eax
    cmp     edx, [{G_ED_HN:#x}]
    setl    al
    mov     [{G_ED_TOP:#x}], al
    mov     eax, ecx
    imul    eax, ebp
    lea     ebx, [esi+eax]
    xor     edi, edi
pix:
    cmp     edi, [{G_ED_W:#x}]
    jge     rownext
    movzx   eax, byte ptr [ebx+edi]
    cmp     al, 0xF0
    je      pf0
    cmp     al, 0xB9
    je      pf0
    cmp     al, 0xA2
    je      pa2
    cmp     al, 0xEF
    je      pa2
    cmp     al, 0xE0
    je      pe2
    cmp     al, 0xE1
    je      pe2
    cmp     al, 0xE2
    je      pe2
    cmp     al, 0xC9
    je      pc9
    cmp     al, 0x68
    je      p68
    cmp     al, 0x6D
    je      p6d
    jmp     pnext
pf0:
    cmp     byte ptr [{G_ED_FL:#x}], 0
    je      pnext
    mov     al, 0xB9
    cmp     byte ptr [{G_ED_TOP:#x}], 0
    je      pwr
    mov     al, 0xF0
    jmp     pwr
pa2:
    cmp     byte ptr [{G_ED_FL + 1:#x}], 0
    je      pnext
    mov     al, 0xEF
    cmp     byte ptr [{G_ED_TOP:#x}], 0
    je      pwr
    mov     al, 0xA2
    jmp     pwr
pe2:
    cmp     byte ptr [{G_ED_FL + 2:#x}], 0
    je      pnext
    mov     al, 0xE2
    cmp     byte ptr [{G_ED_TOP:#x}], 0
    je      pwr
    mov     al, 0xE0
    jmp     pwr
pc9:
    cmp     byte ptr [{G_ED_FL + 3:#x}], 0
    je      pnext
c9w:
    mov     al, 0x6D
    cmp     byte ptr [{G_ED_TOP:#x}], 0
    je      pwr
    mov     al, 0xC9
    jmp     pwr
p68:
    cmp     byte ptr [{G_ED_FL + 4:#x}], 0
    je      pnext
m68w:
    mov     al, 0x68
    cmp     byte ptr [{G_ED_TOP:#x}], 0
    je      pwr
    mov     al, 0x6D
    jmp     pwr
p6d:
    cmp     byte ptr [{G_ED_FL + 3:#x}], 0
    jne     c9w
    cmp     byte ptr [{G_ED_FL + 4:#x}], 0
    jne     m68w
    jmp     pnext
pwr:
    mov     [ebx+edi], al
pnext:
    inc     edi
    jmp     pix
rownext:
    inc     ecx
    jmp     row
fin:
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
r0:
    ret
close_run:
    push    eax
    push    ecx
    push    edx
    cmp     dword ptr [ebx+0x10], 0
    jle     crout
    mov     ecx, [ebx+0x10]
    cmp     ecx, [{G_ED_MAXRUN:#x}]
    jg      crlong
    mov     eax, [ebx+0xC]
    mov     ecx, [ebx+8]
    test    ecx, ecx
    jne     crhave
    mov     [ebx], eax
    mov     dword ptr [ebx+8], 1
    jmp     crout
crhave:
    cmp     ecx, 1
    jne     crcn
    cmp     eax, [ebx]
    je      crout
    mov     [ebx+4], eax
    mov     dword ptr [ebx+8], 2
    jmp     crout
crcn:
    test    ecx, 1
    je      creven
    mov     edx, [ebx+4]
    jmp     crcmp
creven:
    mov     edx, [ebx]
crcmp:
    cmp     eax, edx
    jne     crmis
    inc     dword ptr [ebx+8]
    jmp     crout
crmis:
    call    flush_chain
    mov     [ebx], eax
    mov     dword ptr [ebx+4], -1
    mov     dword ptr [ebx+8], 1
    jmp     crout
crlong:
    call    flush_chain
    mov     dword ptr [ebx], -1
    mov     dword ptr [ebx+4], -1
    mov     dword ptr [ebx+8], 0
crout:
    pop     edx
    pop     ecx
    pop     eax
    ret
flush_chain:
    push    eax
    push    ecx
    push    edx
    cmp     dword ptr [ebx+8], 6
    jl      fcout
    mov     eax, [ebx]
    mov     ecx, [ebx+4]
    cmp     eax, ecx
    jle     fcord
    xchg    eax, ecx
fcord:
    shl     ecx, 8
    or      eax, ecx
    mov     ecx, [ebx+8]
    cmp     eax, 0xF0B9
    jne     fk1
    add     [{G_ED_CRED:#x}], ecx
    jmp     fcout
fk1:
    cmp     eax, 0xEFA2
    jne     fk2
    add     [{G_ED_CRED + 4:#x}], ecx
    jmp     fcout
fk2:
    cmp     eax, 0xE2E0
    jne     fk3
    add     [{G_ED_CRED + 8:#x}], ecx
    jmp     fcout
fk3:
    cmp     eax, 0xC96D
    jne     fk4
    add     [{G_ED_CRED + 12:#x}], ecx
    jmp     fcout
fk4:
    cmp     eax, 0x6D68
    jne     fcout
    add     [{G_ED_CRED + 16:#x}], ecx
fcout:
    pop     edx
    pop     ecx
    pop     eax
    ret
"""


# thunk_btn_gate v6 body VERBATIM (yaml entry, fully concrete; 188B measured).
# v9 (2026-09-21f, byte-neutral 16B-for-16B): statics 4+5 (the FORCES SUPPORTED
# bar's arrow pair 0x6EB674/0x6EC1C0) became the RANGE [0x6E9528, 0x6EC1C0] =
# `cmp esi,0x6E9528 / jb next / cmp esi,0x6EC1C0 / jbe HIT`, admitting the BASE
# FACILITIES bar's arrow pair 0x6E9528/0x6EA074 too (BaseWin_g+0x41454+0xAAC/
# +0x15F8). The range lies entirely inside BaseWin's two ScrollBar sub-objects,
# whose only FlatButtons are those four arrows (test_facsb_asm_parity pins the
# ends). The btn_gate slot had 14B free -- two more statics need 16.
BTN_GATE_V6 = (
    "81 FE 80 50 7B 00 74 32 81 FE CC 5B 7B 00 74 2A 81 FE 18 67 7B 00 74 22 "
    "81 FE 28 95 6E 00 72 08 81 FE C0 C1 6E 00 76 12 81 FE 10 FC 6A 00 74 0A "
    "81 FE 5C 07 6B 00 74 02 EB 06 B8 01 00 00 00 C3 8B 86 C4 00 00 00 3D 68 "
    "6E 8C 00 74 66 81 FE 20 F6 7A 00 74 5E 81 FE 6C 01 7B 00 74 56 81 FE B8 "
    "0C 7B 00 74 4E 81 FE 04 18 7B 00 74 46 81 FE 50 23 7B 00 74 3E 81 FE E8 "
    "39 7B 00 74 36 81 FE 34 45 7B 00 74 2E A1 30 C5 A0 00 85 C0 75 25 A1 00 "
    "08 A1 00 85 C0 75 1C A1 D0 D2 A0 00 85 C0 75 09 A1 A0 E3 A0 00 85 C0 74 "
    "10 8B 86 7C 0A 00 00 85 C0 74 06 B8 01 00 00 00 C3 31 C0 C3"
)

# v7 prefix: editor esi range -> unconditional HIT (mov eax,1; ret).
GATE_PREFIX = (
    f"cmp esi, {EDITOR_LO:#x}\n jb body\n"
    f"cmp esi, {EDITOR_HI:#x}\n jae body\n"
    "mov eax, 1\n ret\nbody:\n"
)

# thunk_btn_stripes v5 yaml template (placeholders preserved; the 21B editor
# clause slots in front of the common fe_pair_remap call).
BTN_STRIPES_V5_TEMPLATE = (
    "81 FE E8 4D 6B 00 72 09 81 FE 70 46 6C 00 73 01 C3 "
    "81 FE 10 FC 6A 00 74 08 81 FE 5C 07 6B 00 75 0A "
    "C7 05 {abs32:g_rm_f0ovr} 01 00 00 00 "
    "83 3D {abs32:g_faction_active} 00 74 0A C7 05 {abs32:g_rm_povr} 02 00 00 00 "
    "E8 {rel32:thunk_btn_devfill} "
    "8D 86 44 04 00 00 A3 {abs32:g_fe_dst} 31 C0 A3 {abs32:g_fe_x} A3 {abs32:g_fe_y} "
    "A3 {abs32:g_fe_src} A1 {abs32:g_btn_origW} A3 {abs32:g_fe_w} A1 {abs32:g_btn_origH} "
    "F7 D8 A3 {abs32:g_fe_h} "
    "81 FE 64 72 7B 00 72 0D 81 FE 98 D0 7C 00 73 05 E8 {rel32:thunk_ed_remap} "
    "E8 {rel32:thunk_fe_pair_remap} C3"
)

STRIPES_SYMS = {
    "g_faction_active":    PCAVE2 + 0x12D0,
    "g_rm_povr":           PCAVE2 + 0x2FCC,
    "g_rm_f0ovr":          PCAVE2 + 0x10634,
    "thunk_btn_devfill":   PCAVE2 + 0x1660,
    "g_fe_dst":            PCAVE2 + 0x2FA0,
    "g_fe_x":              PCAVE2 + 0x2FA4,
    "g_fe_y":              PCAVE2 + 0x2FA8,
    "g_fe_w":              PCAVE2 + 0x2FAC,
    "g_fe_h":              PCAVE2 + 0x2FB0,
    "g_fe_src":            PCAVE2 + 0x2FC4,
    "g_btn_origW":         PCAVE2 + 0x538,
    "g_btn_origH":         PCAVE2 + 0x53C,
    "thunk_fe_pair_remap": PCAVE2 + 0x10000,
    "thunk_ed_remap":      THUNK_ED_REMAP,
}
STRIPES_OFF = 0x2FD0


def resolve_template(tpl: str, base_va: int, syms: dict) -> bytes:
    out = bytearray()
    for tok in tpl.split():
        if tok.startswith("{abs32:"):
            out += syms[tok[7:-1]].to_bytes(4, "little")
        elif tok.startswith("{rel32:"):
            target = syms[tok[7:-1]]
            out += ((target - (base_va + len(out) + 4)) & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


def assemble(asm: str, va: int) -> bytes:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    clean = "\n".join(ln.split(";", 1)[0].rstrip()
                      for ln in asm.splitlines() if ln.split(";", 1)[0].strip())
    enc, _ = ks.asm(clean, va)
    return bytes(enc)


def immtab_bytes() -> bytes:
    out = bytearray()
    for addr, native, kind in IMMTAB:
        out += addr.to_bytes(4, "little")
        out += native.to_bytes(4, "little")
        out += kind.to_bytes(4, "little")
    out += b"\x00\x00\x00\x00"       # terminator
    return bytes(out)


def strings_bytes() -> tuple[bytes, bytes]:
    k32 = b"KERNEL32.DLL\x00".ljust(16, b"\x00")
    vp = b"VirtualProtect\x00".ljust(16, b"\x00")
    return k32, vp


THUNKS = [
    ("thunk_ed_linestep", OFF_LINESTEP, asm_linestep),
    ("thunk_diplo_bracket", OFF_BRACKET, asm_bracket),
    ("thunk_diplo_btnfont", OFF_BTNFONT, asm_btnfont),
    ("thunk_ed_painter", OFF_PAINTER, asm_painter),
    ("thunk_ed_seeds", OFF_SEEDS, asm_seeds),
    ("thunk_ed_immfix", OFF_IMMFIX, asm_immfix),
    ("thunk_ed_remap", OFF_EDREMAP, asm_edremap),
    ("thunk_diplo_pdsclear", OFF_PDSCLEAR, asm_pdsclear),
]


def main() -> int:
    cs = Cs(CS_ARCH_X86, CS_MODE_32)
    ok = True
    print("; ==== scenedit bake thunks (assemble_scenedit.py) ====")
    for name, off, fn in THUNKS:
        va = PCAVE2 + off
        b = assemble(fn(), va)
        limit = SLOTS[off]
        end = off + len(b)
        status = "OK" if end <= limit else "OVERFLOW"
        if end > limit:
            ok = False
        # capstone round-trip sanity
        total = sum(i.size for i in cs.disasm(b, va))
        if total != len(b):
            status += " DISASM-GAP"
            ok = False
        print(f"; {name} @0x{off:X} len {len(b)} end 0x{end:X} "
              f"(slot to 0x{limit:X}) {status}")
        print(f"- id: {name}")
        print(f"  offset: {off:#x}")
        print('  bytes: "' + " ".join(f"{x:02X}" for x in b) + '"')

    tab = immtab_bytes()
    end = OFF_IMMTAB + len(tab)
    print(f"; g_ed_immtab @0x{OFF_IMMTAB:X} len {len(tab)} end 0x{end:X} "
          f"(slot to 0x{SLOTS[OFF_IMMTAB]:X}) "
          f"{'OK' if end <= SLOTS[OFF_IMMTAB] else 'OVERFLOW'}")
    if end > SLOTS[OFF_IMMTAB]:
        ok = False
    print("- id: g_ed_immtab")
    print(f"  offset: {OFF_IMMTAB:#x}")
    print('  bytes: "' + " ".join(f"{x:02X}" for x in tab) + '"')

    k32, vp = strings_bytes()
    print("- id: g_ed_str_k32")
    print(f"  offset: {G_ED_STR_K32 - PCAVE2:#x}")
    print('  bytes: "' + " ".join(f"{x:02X}" for x in k32) + '"')
    print("- id: g_ed_str_vp")
    print(f"  offset: {G_ED_STR_VP - PCAVE2:#x}")
    print('  bytes: "' + " ".join(f"{x:02X}" for x in vp) + '"')

    # ---- btn_gate v7 ----
    prefix = assemble(GATE_PREFIX, PCAVE2 + 0xA9E0)
    v6 = bytes(int(x, 16) for x in BTN_GATE_V6.split())
    assert len(v6) == 188, len(v6)
    gate = prefix + v6
    print(f"; thunk_btn_gate v7: prefix {len(prefix)}B + v6 {len(v6)}B = "
          f"{len(gate)}B (slot 0xA9E0..0xAAE0 = 256B) "
          f"{'OK' if len(gate) <= 0x100 else 'OVERFLOW'}")
    if len(gate) > 0x100:
        ok = False
    print("- id: thunk_btn_gate   # v7")
    print("  offset: 0xA9E0")
    print('  bytes: "' + " ".join(f"{x:02X}" for x in gate) + '"')

    # ---- btn_stripes v5 (template cross-check) ----
    v5 = resolve_template(BTN_STRIPES_V5_TEMPLATE, PCAVE2 + STRIPES_OFF,
                          STRIPES_SYMS)
    print(f"; thunk_btn_stripes v5: {len(v5)}B (slot 0x2FD0..0x3160 = 400B) "
          f"{'OK' if len(v5) <= 0x190 else 'OVERFLOW'}")
    total = sum(i.size for i in cs.disasm(v5, PCAVE2 + STRIPES_OFF))
    if total != len(v5):
        print("; btn_stripes v5 DISASM-GAP")
        ok = False
    print("; v5 template (yaml-ready):")
    print(BTN_STRIPES_V5_TEMPLATE)

    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES — do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
