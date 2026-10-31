"""Assemble thunk_q16_rowgap -- the QUIT-class (type-16) option-row GAP.

PORT OF: scaling_laws.py :: option_row_gap()  (the SOURCE OF TRUTH).
Prototype: scripts/hook_q16gapfix.js, user-verified at 4K/1600/1920/1024.

DEFECT. The type-16 option list draws its rows on a uniform stride
    pitch = [D+0x68] rowH + [D+0x44] gap
and reserves content_h = pitch * count. rowH already scales (thunk_quit_rowpitch
made it Buffer_text_line_height); the gap field is a struct-copy default that
reads a constant 3 at every g. At 4K two 50px bars sit 3px apart.

THE LAW. The PITCH positions row i, so the pitch is what must equal
vanilla * g/16. Pin it; let the gap absorb the rounding:

    pitch' = half_down(22 * g, 16) = (44g + 15) >> 5      (vanilla pitch = 22)
    gap'   = max(0, pitch' - rowH)

Do NOT instead scale the gap directly (gap' = half_down(2g,16)). It agrees with
the engine at 4K/1600/1920 and lands rows 1px off at g = 18, 26, 34, because
rowH and gap round independently. See WHY.md and test_scaling_laws.py
:: test_scaling_the_gap_directly_is_wrong_and_this_is_where_it_breaks.

MEASURED (pristine + patched, work/tests/frida_q16gap*.log):
    g=16  rowH 19  gap 3 -> pitch 22   (gated: native, untouched)
    g=22  rowH 27  gap 3 -> pitch 30
    g=25  rowH 31  gap 3 -> pitch 34
    g=40  rowH 50  gap 3 -> 5, pitch 55        <- the user's report

SITE. Dialog_type16_calc_dimensions Site B @0x60d731, an 8-byte window:
    8B 48 68   mov ecx,[eax+0x68]     <- eax = Dialog base D
    8B 50 44   mov edx,[eax+0x44]
    03 CA      add ecx,edx
replaced by `E8 rel32` + 3 NOP. Both `je 0x60d731` (0x60d70e/0x60d715) land on
the entry byte, so they enter the thunk -- verified no branch targets the
interior. The thunk is CALL-entered, so it ends in a BARE RET (consuming the
return address); execution resumes at 0x60d739 `pop esi; imul ecx,[eax+0x58]`,
which multiplies our pitch into content_h for free.

It writes [D+0x44] because the DRAW loop (0x60d8f3) re-reads the field to build
its own pitch and the per-row `gap>>1` offset. Writing an absolute value derived
from g (never from the field's own prior value) makes it idempotent across the
calc's two passes -- confirmed in the prototype (`gap 5 -> 5` on pass two).

Clobbers ecx/edx only; both are dead at the site (the original wrote both).
eax (D) is preserved.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

# sentinel imm32 -> patches.yaml placeholder
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

ASM = r"""
    mov  ecx, [eax + 0x68]          /* rowH  (= Buffer_text_line_height at g>16) */
    test ecx, ecx
    jle  native                     /* nothing measured -> vanilla                */
    mov  edx, dword ptr [0xDEADBE00]/* g_popup_scale_num                          */
    cmp  edx, 0x10
    jle  native                     /* g <= 16 -> native no-op (CLAUDE.md)        */

    imul edx, edx, 44               /* 44g                                        */
    add  edx, 15
    sar  edx, 5                     /* pitch' = (44g + 15) >> 5 = half_down(22g,16)*/
    sub  edx, ecx                   /* gap'   = pitch' - rowH                     */
    jge  store
    xor  edx, edx                   /* clamp: a line height past the pitch        */
store:
    mov  [eax + 0x44], edx          /* the draw loop re-reads this (0x60d8f3)     */
    add  ecx, edx                   /* ecx = pitch' -> caller's imul [eax+0x58]   */
    ret

native:
    add  ecx, [eax + 0x44]          /* exactly the bytes we replaced              */
    ret
"""


def main() -> int:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(ASM, addr=0)
    blob = bytes(code)

    out, i = [], 0
    while i < len(blob):
        for sent, name in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(name)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1

    print(f"thunk_q16_rowgap  {len(blob)} bytes")
    print()
    print('        bytes: "' + " ".join(out) + '"')
    print()

    # sanity: the law, evaluated the way the asm evaluates it
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import option_row_gap, scale_px

    print(" g | rowH | asm pitch=(44g+15)>>5 | scale_px(22,g) | gap' | law")
    for g, rowH in ((16, 19), (22, 27), (25, 31), (40, 50)):
        asm_pitch = (44 * g + 15) >> 5
        asm_gap = max(0, asm_pitch - rowH)
        law = option_row_gap(22, rowH, g)
        ok = (asm_pitch == scale_px(22, g)) and (asm_gap == law)
        print(f"{g:>2} | {rowH:>4} | {asm_pitch:>21} | {scale_px(22,g):>14} | "
              f"{asm_gap:>4} | {law:>3} {'OK' if ok else 'MISMATCH'}")
        assert ok, f"asm diverges from the reference at g={g}"

    for g in range(16, 41):
        rowH = 19 if g == 16 else scale_px(20, g)
        assert (44 * g + 15) >> 5 == scale_px(22, g), g
        assert max(0, ((44 * g + 15) >> 5) - rowH) == option_row_gap(22, rowH, g), g
    print("\nasm arithmetic == scaling_laws.option_row_gap for every g in [16,40]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
