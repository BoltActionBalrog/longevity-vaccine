"""Assemble thunk_t4_winw / thunk_t4_colw -- the type-4 (text-entry) dialog width.

PORT OF: scaling_laws.py :: type4_dialog_width() / type4_column_width().

DEFECT (user 4K + 1600x1200 shots 20261004-013401 / -013435, base RENAME and
first-base name entry): the EditLine's black field kept its NATIVE pixel width
while the "Name:" label beside it scaled, so label + field stayed ~666 px wide
at every g (field 612 @g16, 582 @g25, 546 @g40) and ended far short of the
ring. Vanilla: the dialog window is [+0x5c] = max(min_width [+0x2c], measured)
wide and the field's right edge is column width [+0x64] + [+0x34]
(Dialog_type4_calc_dimensions 0x6123D1..0x6123F4, Dialog_type4_attach
0x611C95..0x611CB9); pristine NameBase.png: field right = dialog left + xs.
[+0x2c] is the popup's native #xs and is a SHARED source (thunk_scale_boxw,
wrap budget) -- it must stay native in the field, so the scale is applied IN
REGISTER at the three attach-time reads:

    win_w  = max(floor(min_w * g/16), item_w)             (0x611B84)
    col_w  = max(col_w, floor(min_w * g/16) / columns)    (0x611C95, 0x611CF5)

item_w / col_w already carry the device-font measure, so the max is taken in
one space (the type-1/2 mixed-space lesson). g <= 16 -> the displaced load
unchanged. A fixed-width dialog (flags [+0x20] & 2, anchored popups: its
[+0x2c] is the host's own device width) passes through.

SITES (all `8B .. disp32`, 6 bytes -> `E8 rel32 90`), base = Dialog vbase ptr:
    0x611B84  mov ecx,[ecx-0xa48]   window w for GraphicWin_init   -> thunk_t4_winw
    0x611C95  mov edx,[eax-0xa40]   field right = col_w + ...      -> thunk_t4_colw
    0x611CF5  mov edx,[eax-0xa40]   column stride                  -> thunk_t4_colw
(-0xa48 = +0x5c, -0xa40 = +0x64, -0xa78 = +0x2c, -0xa58 = +0x4c columns,
-0xa84 = +0x20 flags, relative to the Dialog base at edi-0xaa4.)
CALL-entered, bare RET. winw: clobbers nothing but ecx (its output); eax (the
GraphicWin_init `this`) preserved. colw: output edx; eax/ecx/ebp preserved.
Flags are dead at all three resumes.

SLOT: pcave2 0xFBE0.. (the freed thunk_pf_union_align v10 slot, 464 B).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

ASM_WINW = r"""
    push eax
    mov  eax, [ecx - 0xa78]             /* min_width [+0x2c] (native #xs)        */
    test byte ptr [ecx - 0xa84], 2      /* fixed width (anchored) -> engine      */
    mov  ecx, [ecx - 0xa48]             /* the displaced load: item_width [+0x5c]*/
    jnz  done
    cmp  dword ptr [0xDEADBE00], 0x10
    jle  done                           /* g <= 16 -> native                     */
    imul eax, dword ptr [0xDEADBE00]
    sar  eax, 4                         /* floor(min_w * g/16)                   */
    cmp  ecx, eax
    jge  done
    mov  ecx, eax
done:
    pop  eax
    ret
"""

ASM_COLW = r"""
    mov  edx, [eax - 0xa40]             /* the displaced load: col width [+0x64] */
    test byte ptr [eax - 0xa84], 2
    jnz  done
    cmp  dword ptr [0xDEADBE00], 0x10
    jle  done
    push eax
    push ecx
    push edx
    mov  ecx, eax
    mov  eax, [ecx - 0xa78]
    imul eax, dword ptr [0xDEADBE00]
    sar  eax, 4
    cdq
    idiv dword ptr [ecx - 0xa58]        /* / columns [+0x4c] (engine divides too)*/
    pop  edx
    cmp  edx, eax
    jge  keep
    mov  edx, eax
keep:
    pop  ecx
    pop  eax
done:
    ret
"""

THUNKS = (("thunk_t4_winw", ASM_WINW), ("thunk_t4_colw", ASM_COLW))


def assemble(asm: str, addr: int = 0) -> bytes:
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm, addr=addr)
    return bytes(code)


def template(blob: bytes) -> str:
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
    return " ".join(out)


def main() -> int:
    for name, asm in THUNKS:
        blob = assemble(asm)
        print(f"{name}  {len(blob)} bytes")
        print('        bytes: "' + template(blob) + '"')
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
