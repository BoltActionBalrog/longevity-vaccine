"""Assemble thunk_popup_min_boxh -- the in-game popup MINIMUM box height.

PORT OF: scaling_laws.py :: ingame_popup_min_boxh()  (the SOURCE OF TRUTH).

DEFECT FIXED (2026-07-16 namebase report): Popup_calculate_dimensions'
vanilla tail clamps every in-game (mode 0/5, console visible, [+0xa14]==0)
popup to a MINIMUM box height of 300, pouring the shortfall into
footer_reserve [+0x30ec]; Popup_show then bottom-anchors the window on the
console strip. The NATIVE 300 went dead at g>16 (scaled content of even the
smallest popup exceeds it), so short popups lost their tall vanilla body and
sat far below vanilla's placement (namebase @4K: top 1279 vs faithful 878).

    M    = floor(300 * g/16)     (the popup family's floor idiom)
    T    = M - D for a popup that owns its window, else M   (v2/v3 below)
    box' = max(box, T); footer += box' - box

g <= 16 -> M = 300 = vanilla's own constant (algebraic native no-op; the
jle arm is belt-and-braces, 300*16>>4 == 300 anyway).

v2: M is the WINDOW height. BasePop_exec_3 creates the window box + D tall,
D = floor(btn_h*g/16) - btn_h (thunk_grow_box @0x602861, btn_h = [+0x30d0]),
so the box target is M - D (law v2; scaling_laws.ingame_popup_window_h).
v3: only when [+0xa3c] == popup (it creates its own window); a popup embedded
in a parent window (exec_3 0x60281E skips creation and the growth) keeps M.

SITE. Popup_calculate_dimensions tail @0x404EBD..0x404EE8 (44 bytes), the
whole vanilla load/cmp/clamp block:
    8B 86 C0 30 00 00      mov eax,[esi+0x30c0]
    3D 2C 01 00 00         cmp eax,0x12c
    7D 1F                  jge 0x404ee9
    BA 2C 01 00 00         mov edx,0x12c
    C7 86 C0 30 00 00 ...  mov [esi+0x30c0],0x12c
    2B D0                  sub edx,eax
    8B 86 EC 30 00 00      mov eax,[esi+0x30ec]
    03 C2                  add eax,edx
    89 86 EC 30 00 00      mov [esi+0x30ec],eax
replaced by `E8 rel32` + 39 NOP. The mode/visibility gates (0x404E9C..
0x404EBB) stay VANILLA in front of the call, so anything vanilla exempts
(main-menu popups, TutWin/ticker with [+0xa14]!=0, art modes) stays exempt.
The jz @0x404EB6 targets 0x404EBD = the CALL itself (patch START -- safe).
CALL-entered, ends in a BARE RET; resumes into the NOP sled -> 0x404EE9
`xor eax,eax`. Clobbers eax/edx only (the displaced block did the same);
esi (popup) preserved; flags dead at resume.

SLOT: pcave2 + 0x3B0 (VA 0xA0C3B0), the 80-byte gap between
thunk_popup_center_x (ends 0x3B0) and thunk_btn_shrink (0x400). RELOCATED
from 0xB2C0 (v1 51 B / v2 64 B filled that slot; freed, zeros).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

# sentinel imm32 -> patches.yaml placeholder
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

ASM = r"""
    mov  eax, dword ptr [0xDEADBE00]/* g_popup_scale_num                        */
    mov  edx, 0x12C                 /* M = native 300 (vanilla's own constant)  */
    cmp  eax, 0x10
    jle  have                       /* g <= 16 -> native no-op (CLAUDE.md)      */
    imul edx, eax                   /* 300 * g                                  */
    sar  edx, 4                     /* M = floor(300*g/16), the floor idiom     */
    cmp  [esi + 0xa3c], esi         /* embedded in a parent window: no growth   */
    jne  have                       /*   at exec_3 -> target stays M            */
    imul eax, [esi + 0x30d0]        /* g * btn_h                                */
    sar  eax, 4
    sub  eax, [esi + 0x30d0]        /* D = thunk_grow_box's later window growth */
    sub  edx, eax                   /* box target M - D -> window = M           */
have:
    mov  eax, [esi + 0x30c0]        /* box_h                                    */
    cmp  eax, edx
    jge  done                       /* box >= target -> untouched               */
    sub  edx, eax                   /* delta = target - box_h                   */
    add  [esi + 0x30ec], edx        /* footer_reserve += delta (OK stays put)   */
    add  [esi + 0x30c0], edx        /* box_h = target                           */
done:
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

    print(f"thunk_popup_min_boxh  {len(blob)} bytes (slot 0x3B0..0x400)")
    assert len(blob) <= 0x50, "does not fit the slot (thunk_btn_shrink @0x400)"
    print()
    print('        bytes: "' + " ".join(out) + '"')
    print()

    # sanity: the asm arithmetic == the law, for a sweep of box heights
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import ingame_popup_min_boxh

    for g in range(16, 41):
        m = ((300 * g) >> 4) - (((20 * g) >> 4) - 20) if g > 16 else 300
        for box in (0, 1, 100, 136, 299, 300, 301, 349, 468, 749, 750, 751, 2000):
            asm_box = max(box, m)
            asm_delta = asm_box - box
            law_box, law_delta = ingame_popup_min_boxh(box, g)
            assert (asm_box, asm_delta) == (law_box, law_delta), (g, box)
    print("asm arithmetic == scaling_laws.ingame_popup_min_boxh for every "
          "(g in [16,40], box sweep)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
