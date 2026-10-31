"""Assemble thunk_list_fill_width v4 -- the type-1 checkbox-list window / row-bar width.

PORT OF: scaling_laws.py :: type1_list_widths() / type1_list_fill_width()
(the SOURCE OF TRUTH; regenerate the yaml bytes from here, never hand-edit).

v4 (2026-10-22, fix 18): the native arm's vanilla re-form (fixed-width test,
native-gap read-back, w / bar base) is `call t_t1_list_w` (pcave2 0xA2C1,
assemble_scale_boxw.py core_asm), the ONE owner of that arithmetic: the box
(t_boxw_t1_term v2 -> thunk_scale_boxw) and the type-1 ring
(thunk_pf_union_align v17, which draws at BasePop_exec_3 0x602B49 BEFORE this
attach and so cannot read the [+0x5c] written here) call the same code.  The
DiploEditWin arm keeps its own (owned-container) law inline.  Equivalence
with v3: every output field, the w arg and every register, differential
emulation over the input domain (fix 18 scratchpad).  169 -> 128 B in place.

SITE (unchanged): FUN_0060e800_type1_attach 0x60e8a1 `call GraphicWin_init`
-> `call thunk_list_fill_width`; the thunk tail-jumps GraphicWin_init (push/ret)
with the caller's frame intact, so GraphicWin_init returns to 0x60e8a6.
At entry: esi = the attach's `this` (element base = esi - 0xa34, its Dialog =
[[esi-0xa34]+8] + esi - 0xa34), ecx = the list's GraphicWin (preserved),
[esp+4..] = GraphicWin_init's 9 args
(x, y, w, h, 0, flags, parent, 0, 0): w at [esp+0xC], parent at [esp+0x1C].

The calc OptionList_calc_reserve (0x60ED10) runs at 0x60e835 just before this
call and writes [+0x5c] / [+0x64]; the w arg is [+0x5c].  At g > 16 those are
NOT vanilla: the calc measured the scaled font's text and (popup lists) the
row gap [+0x44] that thunk_rowgap already scaled.  So the thunk re-forms
VANILLA's results from the native inputs and scales each RESULT:

    vanilla  (fixed: flags&2 && xs)   w = [+0x5c] = xs,          [+0x64] = (xs - 2m)/cols - gap
             (else, xs-dominant)      w = [+0x5c] = xs + 2m - gap, [+0x64] = xs/cols - gap
    patched  each = floor(vanilla * g / 16)

gap = the field's NATIVE value: thunk_rowgap maps a native 3 to floor(3g/16) on
the calc's else-path (flags&1 == 0 or [+0x30] == 0) before this runs, so on
that path a field equal to floor(3g/16) is a native 3 (scaling_laws.
dialog_row_margin_native).  The fixed-height path (PrefWin pages, every
Dialog_init_2 / Dialog_init_3 list) never meets thunk_rowgap: its gap is
native as read.

OWNED CONTAINER: the scenario-editor diplomacy modal (parent vtbl 0x66E964,
DiploEditWin) hands its CheckList a rect its own law already scaled (editor
g_ed_immtab), so xs is device px: w = [+0x5c] = xs (the container's edge-form
width, as vanilla fills it), [+0x64] = (xs - s(2m))/cols - s(gap) with
s(v) = floor(v*g/16).  v1/v2 scaled that xs AGAIN (x2.5 at 4K: 2317 in a
927-wide column).

g <= 16 (or a single row) tail-jumps with every arg and field untouched.

SLOT: menu_strip_thunks + 0x920 (VA 0x668B20), must stay <= 0xB0 bytes
(thunk_content_frame starts at +0x9D0).  v3 outgrew v2's 0x960 slot; it took
the free 0x91D..0x960 gap below it (cave_map.py --at, 2026-10-18: no symbol,
abs32 or rel32 reference into 0x668B10..0x668B60).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

from scaling_laws import DIPLO_EDIT_VTBL   # DiploEditWin vtable: the owned-container parent (one definition)
from assemble_scale_boxw import CORE_VA as T1_LIST_W_VA   # t_t1_list_w: the shared type-1 width core (fix 18)

CODE_VA = 0x00668B20
SLOT_LIMIT = 0xB0

# sentinel imm32 -> patches.yaml placeholder
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}", 0xDEADBE10: "{abs32:GraphicWin_init}",
        0xDEADBE20: "10 00 00 00"}     # the gate immediate, kept in the canonical imm32 form

ASM = r"""
    cmp  dword ptr [0xDEADBE00], 0xDEADBE20  /* g_popup_scale_num vs 0x10 (imm32 form)    */
    jle  tail                           /* g <= 16 -> native no-op (CLAUDE.md)         */
    pushad
    mov  edi, dword ptr [esi - 0xa34]
    mov  edi, dword ptr [edi + 8]
    lea  edi, [edi + esi - 0xa34]       /* edi = the element's Dialog                  */
    cmp  dword ptr [edi + 0xcc], 1
    jle  out                            /* single row (a label / wrapped body): as is  */
    mov  ebp, dword ptr [0xDEADBE00]    /* ebp = g                                     */
    mov  esi, dword ptr [esp + 0x3c]    /* parent window (arg 7, after pushad)         */
    cmp  dword ptr [esi], DIPLO_EDIT_VTBL
    jne  native
    mov  ebx, dword ptr [edi + 0x44]    /* DiploEditWin: container scaled by its owner */
    imul ebx, ebp
    sar  ebx, 4                         /*   s(gap)                                    */
    mov  edx, dword ptr [edi + 0x40]
    add  edx, edx
    imul edx, ebp
    sar  edx, 4                         /*   s(2m)                                     */
    mov  ecx, dword ptr [edi + 0x2c]    /*   w = xs (device px)                        */
    mov  eax, ecx
    sub  eax, edx                       /*   bar base xs - s(2m) (vanilla's fixed form)*/
    push 0x10
    pop  ebp                            /*   results already device px: x16 >> 4      */
    jmp  bar
native:
    /* v4 (fix 18): the vanilla re-form is t_t1_list_w, the ONE owner shared with
       t_boxw_t1_term (the box) and, through it, thunk_pf_union_align v17 (the ring
       drawn at 0x602B49 before this attach runs): ecx = vanilla [+0x5c],
       eax = bar base, ebx = native gap.  Byte-for-byte the v3 arithmetic.       */
    call T1_LIST_W
bar:
    cdq
    idiv dword ptr [edi + 0x4c]
    sub  eax, ebx                       /* vanilla [+0x64]                             */
    imul eax, ebp
    sar  eax, 4
    imul ecx, ebp
    sar  ecx, 4                         /* floor(vanilla * g/16), each field           */
    mov  dword ptr [edi + 0x64], eax
    mov  dword ptr [edi + 0x5c], ecx
    mov  dword ptr [esp + 0x2c], ecx    /* GraphicWin_init w arg                       */
out:
    popad
tail:
    push 0xDEADBE10                     /* GraphicWin_init                             */
    ret
"""


def assemble(va: int = CODE_VA) -> bytes:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    src = ASM.replace("DIPLO_EDIT_VTBL", f"{DIPLO_EDIT_VTBL:#x}").replace("T1_LIST_W", f"{T1_LIST_W_VA:#x}")
    code, _ = ks.asm(src, addr=va)
    return bytes(code)


def template(blob: bytes, va: int = CODE_VA) -> str:
    out, i = [], 0
    while i < len(blob):
        if blob[i] == 0xE8 and i + 5 <= len(blob) and \
                (va + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF == T1_LIST_W_VA:
            out.append("E8 {rel32:t_t1_list_w}")
            i += 5
            continue
        for sent, name in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(name)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    return " ".join(out)


def main() -> int:
    blob = assemble()
    print(f"thunk_list_fill_width v4  {len(blob)} bytes (slot limit {SLOT_LIMIT:#x} = {SLOT_LIMIT})")
    assert len(blob) <= SLOT_LIMIT, "does not fit the 0x920..0x9D0 slot"
    print()
    print('        bytes: "' + template(blob) + '"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
