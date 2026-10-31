"""Assemble t_ed_info_right -- the scenario-editor info rect's right edge (fix 24).

PORT OF: scaling_laws.py :: editor_info_right() (the SOURCE OF TRUTH; regenerate the yaml bytes from here, never
hand-edit).

SITE: MainWin_build 0x45B497, `sub eax, 3; mov [esi+0xD74], eax` (83 E8 03 89 86 74 0D 00 00, 9 B) ->
`call t_ed_info_right` + 4 NOPs.  The image's own `mov eax, [esi+0xA3C]` (I.l, the HUD M / I / TOOLBAR column's left
edge, already law via t_hud_mi_square) @0x45B491 stays in place, so eax = I.l on entry.  No branch target inside
0x45B498..0x45B49F (rel8 / rel32 sweep of every executable section); PRACX's hook / change tables touch nothing in
0x45A000..0x45C000.  The vanilla `sub` leaves flags that nothing reads (the next instruction is `call 0x6162D0`).

LAW: +0xD74 = I.l - s(3), s(3) = half_down(3g, 16) = (6g + 15) >> 5 -- the same pad as the info rect's left edge
(editor_panel_seeds' info_left = red_union.r + s(3)), so the box's two flanking channels are equal at every g.
g <= 16 (or g_popup_scale_num not yet set, 0): g is clamped to 16, where (6*16 + 15) >> 5 = 3 -- vanilla's `- 3`.
g_popup_scale_num is set by then: thunk_ed_seeds (the 0x45B0ED detour, which dominates 0x45B497 in MainWin_build)
calls thunk_ensure_scale first.

CONTRACT: entered by E8 (bare `ret` back to 0x45B49C, the NOPs fall into 0x45B4A0); eax out = the stored edge, exactly
as vanilla; edx saved / restored; every other register untouched; only MainWin +0xD74 is written.

SLOT: pcave2 0x6170 (cave_map.py --at / --fit 2026-10-23: free 0x6170..0x61A0, 48 B).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

from scaling_laws import EDITOR_INFO_RIGHT_PAD, NATIVE_G

CODE_VA = 0xA0C000 + 0x6170
SLOT_LIMIT = 0x30
SITE_VA = 0x45B497
SITE_ORIGINAL = "83 E8 03 89 86 74 0D 00 00"

# sentinel imm32 -> patches.yaml placeholder
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

assert EDITOR_INFO_RIGHT_PAD == 3 and NATIVE_G == 16

ASM = f"""
    push edx
    mov  edx, dword ptr [0xDEADBE00]
    cmp  edx, {NATIVE_G:#x}
    jge  scaled
    push {NATIVE_G:#x}
    pop  edx
scaled:
    lea  edx, [edx + edx*2]
    lea  edx, [edx*2 + 0xF]
    shr  edx, 5
    sub  eax, edx
    mov  dword ptr [esi + 0xD74], eax
    pop  edx
    ret
"""


def assemble(va: int = CODE_VA) -> bytes:
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(ASM, addr=va)
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
    blob = assemble()
    assert len(blob) <= SLOT_LIMIT, f"{len(blob)} B does not fit the 0x6170..0x61A0 slot"
    print(f"t_ed_info_right  {len(blob)} bytes @ {CODE_VA:#x} (slot limit {SLOT_LIMIT})")
    print()
    print('        bytes: "' + template(blob) + '"')
    print()
    print(f"site {SITE_VA:#x}: original_bytes \"{SITE_ORIGINAL}\"")
    print('  new_bytes "E8 {rel32:t_ed_info_right} 90 90 90 90"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
