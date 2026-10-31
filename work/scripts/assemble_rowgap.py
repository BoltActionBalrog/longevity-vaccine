"""Assemble thunk_rowgap v2 -- the generic Dialog inter-row margin [+0x44].

PORT OF: scaling_laws.py :: dialog_row_margin()  (the SOURCE OF TRUTH).

DEFECT FIXED (v1 -> v2): v1 gated on `cmp [ScreenWidth],0x3FF; jle` -- at
1024x768 (W=0x400, g=16) it FIRED (feedback-loores-gate-on-g; same class as
the thunk_content_frame fix, lock 9e877dc7). The gate is now g > 16.

v2 scales the field's own NATIVE value: margin' = floor(native * g/16),
applied only when the field holds the one MEASURED native (3, the popup
Dialog struct-copy default -- q16 evidence; the PrefWin pages carry the
Dialog default 6 and take the calc's fixed-height path, which never reaches
this site) so the twice-per-build calc is idempotent
(outputs 4..7 pass through untouched; 3 at g<22 is a fixed point). Any other
value passes through unscaled -- conservative by design: only scale what was
measured.

For g>16 the output is bit-identical to v1 (floor(3g/16)), so every
already-verified screen is unchanged; the ONLY behavioral change is the
1024x768 gate.

NOTE (root-cause correction, 2026-07-11): the user's 1024 PrefWin +2px row
pitch was NOT this thunk -- v1's stomp of 3 was an identity there (native IS
3). The real mover was the UNGATED popup_list_rowheight redirect
(Buffer_text_height -> Buffer_text_line_height at 0x60EF29/0x60EF40), which
at g=16 grew every type-1 row by the font leading (+2). Fixed by redirecting
those two sites to the GATED thunk_quit_rowpitch (its type-16 twin).

SITE (unchanged from v1). FUN_0060ed10 0x60f018, the else-path pitch reserve:
    8B 48 68   mov ecx,[eax+0x68]      <- eax = type-1 element data region
    8B 50 44   mov edx,[eax+0x44]
    03 CA      add ecx,edx
replaced by `E8 rel32` + 3 NOP; CALL-entered, ends in a BARE RET; resumes at
0x60f020 `pop esi; imul ecx,[eax+0x58]; mov [eax+0x60],ecx`. The write to
[+0x44] propagates to the render row-advance and hit-test (FUN_0060f030 reads
the same field). Clobbers ecx/edx only (both dead: the original wrote both,
and v1's native path already left edx untouched). eax is preserved.

SLOT: menu_strip_thunks + 0xA00 (VA 0x668C00), must stay < 0x30 bytes
(g_boxw_num sits at +0xA30). v2 is 46 bytes (v1 was 43).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

# sentinel imm32 -> patches.yaml placeholder
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

ASM = r"""
    mov  edx, dword ptr [0xDEADBE00]/* g_popup_scale_num                          */
    cmp  edx, 0x10
    jle  tail                       /* g <= 16 -> native no-op (CLAUDE.md)        */
    cmp  dword ptr [eax + 0x58], 1
    jle  tail                       /* single row: no gutter to scale             */
    mov  ecx, [eax + 0x44]          /* the field's CURRENT value                  */
    cmp  ecx, 3
    jne  tail                       /* not the measured native 3 -> untouched     */
    imul edx, ecx                   /* native * g                                 */
    sar  edx, 4                     /* floor(native * g/16) -- v1's rounding      */
    mov  [eax + 0x44], edx
tail:
    mov  ecx, [eax + 0x68]          /* pitch = line-height + margin, as replaced  */
    add  ecx, [eax + 0x44]
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

    print(f"thunk_rowgap v2  {len(blob)} bytes (slot limit 0x30 = 48)")
    assert len(blob) <= 0x30, "does not fit the 0xA00..0xA30 slot"
    print()
    print('        bytes: "' + " ".join(out) + '"')
    print()

    # sanity: the asm arithmetic == the law, for every field value it can see
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import dialog_row_margin

    for g in range(16, 41):
        for v in range(0, 9):
            if g <= 16 or v != 3:
                asm_out = v
            else:
                asm_out = (v * g) >> 4
            law = dialog_row_margin(v, g)
            assert asm_out == law, (g, v, asm_out, law)
    print("asm arithmetic == scaling_laws.dialog_row_margin for every "
          "(g in [16,40], field in [0,8])")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
