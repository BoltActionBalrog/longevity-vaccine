#!/usr/bin/env python
# Keystone assembler for thunk_scale_boxw v7 + its CALL-helper t_boxw_t1_term (group popup_wrap_width).
#
# fix 18 (2026-10-22): t_boxw_t1_term v2 + t_t1_list_w (core_asm below) -- the type-1 list-width arithmetic has ONE
# owner, t_t1_list_w, called by thunk_list_fill_width v4 (the list window), t_boxw_t1_term v2 (the box) and,
# through it, thunk_pf_union_align v17 (the ring, drawn at 0x602B49 BEFORE the attach writes [+0x5c]).  v2's ebx
# and every preserved register == v1's for every input (differential emulation, fix 18).
#
# v7 (2026-10-18, fix 14b) -- the mixed-space arm's native term is
# scaling_laws.itemlist_box_term_native, computed by t_boxw_t1_term (pcave2
# +0xA294; `call` replaces the arm's `mov ebx,xs / imul / sar`, so the thunk
# shrinks in place).  Type 1: vanilla's [+0x5c] = xs + 2m - gap (fixed: xs), the
# same vanilla thunk_list_fill_width scales for the list window, so the box
# content == the list width at every g as in vanilla (BasePop_calculate_dimensions
# 0x603BE0..0x603C19 builds both from one [+0x5c]).  v6 scaled xs: box content
# s(660) around the fix-14 list s(657), row bars 8 px short on the right at 4K.
# Types 2 / 8 keep s(xs).
#
# v6 (2026-10-11) -- dlg_type 8 (the OptionList multi-column popup: the unit-stack
# picker, every veh_pick caller, BasePop_exec_3 promoted lists) also takes the
# mixed-space arm: OptionList_calculate_dimensions' tail sets d5c = max(native xs,
# device column content), and v3 scaled that max whole -- a 16-unit stack at 4K was
# (1591+40)*40>>4 = 4077 px, wider than the screen (user shot 225617).  Lawful
# max(s(xs), d5c) + s(trim) = 1691.
#
# v5 (2026-07-12) — the mixed-space arm's gate widens from dlg_type==1 to
# dlg_type in {1,2}: the scenario #FACTION popup (a type-2 #listbox whose items
# exist BEFORE BasePop_calc, so ListBox_calculate_dimensions has already run and
# thunk_lbcalc_minw has already populated d5c [+iv3+0x222c] with a DEVICE-space
# w5c — 1312 = 525*40>>4 @4K, frida_faction_scenario_crash.log line 311) took the
# v3 arm and double-scaled: box 3280 vs faithful 1312 (user 4K screenshot,
# ~3330 measured, near-full-screen + position clamped to x=0). #SELECTSERVICE
# never hit this only because its items attach AFTER the calc (d5c==0 at boxw
# time -> native xs fallback); if a recalc ever sees d5c populated, this arm now
# handles it lawfully too. Type-2 WITH art keeps v3 (same as type-1 policy).
#
# v4 (2026-07-12) — adds the TYPE-1 MIXED-SPACE arm; v3 body byte-preserved for
# every other popup. RELOCATED 0x300 -> 0xAF00 (v4 outgrew the 0x300..0x39F slot
# against thunk_popup_center_x @0x3A0; callers reference {abs32:thunk_scale_boxw}
# so only the ledger moves; old slot zero-fills on the whole-cave write).
#
# WHY v4 (Customize Game Rules over-wide at 4K; frida_boxw2.log 2026-07-12 +
# user-verified prototype hook_rulesboxw.js v2 at 4K/1920/1600/1024):
# For dlg_type==1 (checkbox #itemlist) popups the measured width d5c
# [+iv3+0x222c] = max(#xs, longest item at the dialog's CURRENT font). Under our
# font scaling the text term is already DEVICE-space, so d5c is a MIXED-space
# max — and v3's single (tw+trim)*g/16 double-scales it: (890+22)*40>>4 = 2280
# where faithful is 1705 (== drawn rows 1589 + insets 86+30, exact flush).
# Note #xs itself is the correct 1024-vanilla magnitude: the ENGINE multiplies
# it x3/2 above 1023px wide (BasePop_start @0x601bf0 — genuine vanilla,
# byte-identical in cc659f; popup scripts are 800x600-baseline).
#
# LAW (scaling_laws.py::itemlist_box_width — this thunk is its port; swept +
# golden-pinned by test_scaling_laws.py, emulated by test_scaleboxw_asm_parity):
#
#     type-1 or type-2, d5c != 0, no art:
#         box_w = max(xs*g>>4, d5c) + trim*g>>4        (compare in ONE space)
#     everything else: v3 unchanged:
#         box_w = (max(cw_native, d5c ?: xs) + trim) * g >> 4
#     trim = (init_w[+0x21cc] == -1 ? 2*padx : init_w + padx)   (both arms)
#
# Identity at g=16 is algebraic (fonts native there -> d5c == the engine's own
# tw) and the g<=16 gate bails to the native path anyway. Type 16 (Quit) keeps
# its own q16/fieldpads family; type -1 (Difficulty) has d5c == 0 -> v3 arm.
# Type-1 WITH art falls through to v3 = today's behavior (none known to exist).
#
# Registers: eax/ebx/edx scratch (ecx NOT touched; the displaced
# `mov ebx,[esi+0x30e0]` rewrites ebx on every path so the engine never sees it).
#
# Regenerate if any cave offset moves (absolute addrs are baked).

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PCAVE2_VA = 0xA0C000
OFF_THUNK = 0xAF00                 # RELOCATED from 0x300 (v4 outgrew the slot)
SLOT_END  = 0xB000                 # pcave2 length — hard ceiling
THUNK_VA  = PCAVE2_VA + OFF_THUNK  # 0xA16F00

OFF_HELPER = 0xA294                # t_boxw_t1_term (cave_map.py --at 2026-10-18: FREE 0xA294..0xA300,
HELPER_END = 0xA300                #   between thunk_fe_bandmap and thunk_bandmap_blit; no abs32/rel32 refs)
HELPER_VA  = PCAVE2_VA + OFF_HELPER
# fix 18: t_t1_list_w, the ONE owner of the type-1 list-width arithmetic, packed right behind t_boxw_t1_term
# in the same slot (cave_map.py --at 0xA2FA 2026-10-22: FREE to 0xA300).  OFF_CORE is derived from the
# helper's assembled length below and must end <= HELPER_END.
OFF_CORE   = 0xA2C1
CORE_VA    = PCAVE2_VA + OFF_CORE

MENU_CAVE = 0x668200               # menu_strip_thunks cave VA
G_SCALE   = MENU_CAVE + 0x540      # g_popup_scale_num (0x668740)
RESUME    = 0x603D88               # BasePop_calculate_dimensions resume

asm = f"""
    mov eax, [{G_SCALE}]
    cmp eax, 0x10
    jle tail                         ; g<=16 -> native no-op (lo-res gate on g)

    ; ---- tw = d5c [+iv3+0x222c] ?: xs [+iv3+0x21fc]   (iv3 = [[esi+0x21d0]+8]) ----
    mov edx, [esi+0x21d0]
    mov edx, [edx+8]
    mov eax, [esi+edx+0x222c]
    test eax, eax
    jnz tw_measured
    mov eax, [esi+edx+0x21fc]
    jmp have_tw

tw_measured:
    ; ---- v5 arm: dlg_type in {1,2} -> d5c is MIXED-space; compare in device space ----
    ; (ebx is free scratch here: every path below rewrites it before use, and the
    ;  displaced tail instruction rewrites it again for the engine contract)
    mov ebx, [esi+0x2350]
    cmp ebx, 8                       ; v6: type-8 OptionList (unit-stack picker) -- d5c = max(native xs, device cols)
    je t8_mixed
    dec ebx                          ; 1->0, 2->1; -1/0/16 wrap to unsigned >1
    cmp ebx, 1
    ja have_tw                       ; unsigned: only dlg_type 1, 2 (and 8 above) pass
t8_mixed:
    cmp dword ptr [esi+0x2144], 0    ; with art: fall through to v3
    jne have_tw
    call {HELPER_VA}                 ; v7: ebx = s(itemlist_box_term_native); eax/ecx/edx kept
    cmp eax, ebx
    jge t1_trim
    mov eax, ebx                     ; eax = max(scaled xs, d5c) — device space
t1_trim:
    mov edx, [esi+0x21cc]            ; init_w — same trim path as v3
    cmp edx, -1
    jne t1_fixed
    mov edx, [esi+0x30e0]
    add edx, edx                     ; 2*padx
    jmp t1_scale
t1_fixed:
    add edx, [esi+0x30e0]            ; init_w + padx
t1_scale:
    imul edx, [{G_SCALE}]
    sar edx, 4                       ; scaled trim
    add eax, edx
    mov [esi+0x30bc], eax
    jmp tail

have_tw:
    ; ---- v3 body, unchanged ----
    ; cw = NATIVE content width (0 when the popup carries no art)
    xor ebx, ebx
    mov edx, [esi+0x2144]            ; art object
    test edx, edx
    jz have_cw
    mov ebx, [edx+0x18]              ; art canvas W, native
    add ebx, [esi+0x30e0]            ; + padx
    cmp dword ptr [esi+0x2190], 0    ; art_flag -> engine also adds padY
    jz have_cw
    mov edx, [esi+0x21c4]            ; padY source (4)
    lea edx, [edx+edx*2]             ; *3
    sar edx, 1                       ; /2  -> native padY (6)
    add ebx, edx
have_cw:

    ; pre = max(cw, tw) + (init_w == -1 ? 2*padx : init_w + padx)
    cmp eax, ebx
    jge have_max
    mov eax, ebx
have_max:
    mov edx, [esi+0x21cc]            ; init_w
    cmp edx, -1
    jne fixed_w
    add eax, [esi+0x30e0]
    add eax, [esi+0x30e0]
    jmp scale
fixed_w:
    add eax, edx
    add eax, [esi+0x30e0]

scale:
    imul eax, dword ptr [{G_SCALE}]
    sar eax, 4
    mov [esi+0x30bc], eax

tail:
    mov ebx, [esi+0x30e0]            ; displaced instruction
    push {RESUME}
    ret
"""

# t_boxw_t1_term v2 (fix 18) -- PORT OF scaling_laws.itemlist_box_term_native, scaled:
#   in:  esi = popup, edx = iv3 (Dialog = esi + edx + 0x21d0)
#   out: ebx = floor(term * g / 16);  every other register preserved (eax = d5c, live in boxw's caller)
#   type 1: term = t_t1_list_w's vanilla [+0x5c] (the SAME arithmetic thunk_list_fill_width scales for the list
#           window -- one owner, fix 18; v1 carried a private copy of it)
#   else:   term = xs
# Callers: thunk_scale_boxw v7 (the box) and thunk_pf_union_align v17 (the type-1 ring's right edge at the
# 0x602B49 pre-attach draw, while Dialog[+0x5c] still holds calc_reserve's measured width).
# v1 (fix 14b, 102 B) inlined the native-gap / fixed-width arithmetic; v2 is byte-for-byte equivalent in ebx and
# in every preserved register for every input (scratchpad differential, fix 18).
helper_asm = f"""
    mov ebx, [esi+edx+0x21fc]        ; xs
    cmp dword ptr [esi+0x2350], 1
    jne scale                        ; types 2 / 8: s(xs), as v6
    pushad
    lea edi, [esi+edx+0x21d0]        ; the Dialog
    call {CORE_VA}                   ; t_t1_list_w: ecx = vanilla [+0x5c]
    mov [esp+0x10], ecx              ; -> the saved ebx slot
    popad
scale:
    imul ebx, [{G_SCALE}]
    sar ebx, 4
    ret
"""

# t_t1_list_w (fix 18) -- THE type-1 list-width arithmetic, one owner (PORT OF scaling_laws.type1_list_widths
# re-formed from the native inputs = itemlist_box_term_native type 1 = type1_list_fill_width's vanilla):
#   in:  edi = the Dialog (+0x20 flags, +0x2c xs, +0x30 fixed_h, +0x40 m, +0x44 gap)
#   out: ecx = vanilla [+0x5c] (native px; fixed: xs, else xs + 2m - gap)
#        eax = vanilla's row-bar base (fixed: xs - 2m, else xs)     ebx = the native gap     edx = 2m
#        esi, edi, ebp, esp preserved
#   gap: thunk_rowgap's floor(3g/16) on the calc's else-path (flags&1 == 0 or fixed_h == 0) reads back as the
#        native 3 (scaling_laws.dialog_row_margin_native); the fixed-height path keeps the field as read.
# Callers: thunk_list_fill_width v4 (the list window w, [+0x5c], [+0x64]) and t_boxw_t1_term v2 (the box term,
# and through it the ring).
core_asm = f"""
    mov ebx, [edi+0x44]              ; row gap as the calc left it
    mov ecx, [edi+0x2c]              ; xs
    mov edx, [edi+0x40]
    add edx, edx                     ; 2m
    mov eax, ecx                     ; bar base xs
    test byte ptr [edi+0x20], 1
    je elig
    cmp dword ptr [edi+0x30], 0
    jne have                         ; fixed-height path: thunk_rowgap never ran
elig:
    push eax
    mov eax, [{G_SCALE}]
    lea eax, [eax+eax*2]
    sar eax, 4                       ; floor(3g/16)
    cmp eax, ebx
    pop eax
    jne have
    push 3
    pop ebx                          ; floor(3g/16) on the else-path = the native 3
have:
    test byte ptr [edi+0x20], 2
    je nonfix
    test ecx, ecx
    je nonfix
    sub eax, edx                     ; fixed: bar base xs - 2m, w = xs
    ret
nonfix:
    add ecx, edx
    sub ecx, ebx                     ; else: w = xs + 2m - gap, bar base xs
    ret
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
# keystone rejects some punctuation inside ';' comments -> strip them pre-assembly
_strip = lambda src: "\n".join(l.split(";")[0] for l in src.splitlines())  # noqa: E731
enc, _ = ks.asm(_strip(asm), THUNK_VA)
b = bytes(enc)
henc, _ = ks.asm(_strip(helper_asm), HELPER_VA)
hb = bytes(henc)
cenc, _ = ks.asm(_strip(core_asm), CORE_VA)
cb = bytes(cenc)
assert OFF_THUNK + len(b) <= SLOT_END, "v7 overruns the 0xAF00..0xB000 slot (bounded by the 0xB000 gap gwinit v5 vacated in W5A, 2026-10-25; gwinit v6 is at 0x3C100) — relocate"
assert OFF_HELPER + len(hb) == OFF_CORE, "t_boxw_t1_term v2 length moved -- re-pack OFF_CORE behind it"
assert OFF_CORE + len(cb) <= HELPER_END, "t_t1_list_w overruns 0xA2C1..0xA300 (thunk_bandmap_blit) — relocate"

G_LE = G_SCALE.to_bytes(4, "little")


def template(blob: bytes, va: int) -> str:
    """The yaml form: g_popup_scale_num as {abs32:}, the helper calls as {rel32:}."""
    out, i = [], 0
    calls = {HELPER_VA: "t_boxw_t1_term", CORE_VA: "t_t1_list_w"}
    while i < len(blob):
        tgt = (va + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF \
            if blob[i] == 0xE8 and i + 5 <= len(blob) else None
        if blob[i:i + 4] == G_LE:
            out.append("{abs32:g_popup_scale_num}")
            i += 4
        elif tgt in calls:
            out.append("E8 {rel32:%s}" % calls[tgt])
            i += 5
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    return " ".join(out)


if __name__ == "__main__":
    cs = Cs(CS_ARCH_X86, CS_MODE_32)
    for name, blob, va, off, end in (("thunk_scale_boxw v7", b, THUNK_VA, OFF_THUNK, SLOT_END),
                                     ("t_boxw_t1_term v2", hb, HELPER_VA, OFF_HELPER, OFF_CORE),
                                     ("t_t1_list_w", cb, CORE_VA, OFF_CORE, HELPER_END)):
        print(f"{name} @ VA 0x{va:X} (pcave2 + 0x{off:X}), {len(blob)} bytes -> ends 0x{off + len(blob):X} "
              f"(<= 0x{end:X})")
        print('        bytes: "' + template(blob, va) + '"')
        for i in cs.disasm(blob, va):
            print(f"  {i.address:08X}  {i.bytes.hex(' '):<24}  {i.mnemonic} {i.op_str}")
        print()
