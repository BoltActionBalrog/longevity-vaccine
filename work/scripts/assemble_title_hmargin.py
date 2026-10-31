"""thunk_title_hmargin v2 (F36, 2026-10-25) -- the title band's L/R inset on Popup_on_draw_background's "+3" path.

PORT OF scaling_laws.title_band_hmargin_lr.  CALL-entered at 0x40600A (the console hidden -- every main-menu popup --
or a non-rail family; the rail families 0 / 5 in game take thunk_popup_titleinsets at 0x405FF1) and from
thunk_untitled_stash (pushad'd, the same caller frame).  Entry: [ebp-0x14] = band L, [ebp-0xc] = band R (the frame
rect), [ebp-4] = the popup family ([+0x30ac] / 10000).  The engine then adds +1 / -1 (0x406027 inc edx /
thunk_title_height's dec edx), so the block stores ins = fl(4g/16) - 1 on both sides (v1, unchanged).

v2: at g > 16 a non-ornate band is painted by the flat band map with an INCLUSIVE footprint [L, R], so R comes in by
one more (the in-game rail path's popup_title_band_right fold): frame -> band fl(4g/16) - K on BOTH sides (was 8 | 7 at
4K, 4 | 3 at 1080 / 1600x1200, 3 | 2 at 1600x900).  The ornate families 2 / 6 pass ([ebp-4] | 4 == 6 exactly for
2 and 6): thunk_pf_title_stash's ornate arm owns their R (ORNATE_HALF_OPEN).

Contract (v1's): MUST return ebx = 3 (the 9-slice step downstream); eax / edx clobbered (eax reloaded at 0x40601F, edx
at 0x406022); ecx untouched.

RELOCATED menu_strip_thunks 0xB68 (28 B, no room for the arm: thunk_title_font at 0xB90) -> pcave2 0x35300 (wave-2
W2B region); the old slot is dead space.

    py work\\scripts\\assemble_title_hmargin.py      -> prints the yaml byte template
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
VA = PCAVE2 + 0x35300
SLOT_END = PCAVE2 + 0x35400

SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

ASM = r"""
    mov  eax, 4
    imul eax, dword ptr [0xDEADBE00]    /* 4g                                     */
    sar  eax, 4                         /* fl(4g/16)                              */
    dec  eax                            /* ins (the engine adds the last 1)       */
    add  dword ptr [ebp - 0x14], eax    /* L += ins                               */
    sub  dword ptr [ebp - 0xc], eax     /* R -= ins                               */
    cmp  dword ptr [0xDEADBE00], 0x10
    jle  done                           /* g <= 16: vanilla                       */
    mov  edx, dword ptr [ebp - 4]       /* popup family                           */
    or   edx, 4
    cmp  edx, 6
    je   done                           /* ornate 2 / 6: ornate_title_rect's R    */
    dec  dword ptr [ebp - 0xc]          /* v2: R on the half-open axis            */
done:
    mov  ebx, 3
    ret
"""


def template(asm: str = ASM, va: int = VA) -> tuple:
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm, addr=va)
    blob = bytes(code)
    out, i = [], 0
    while i < len(blob):
        for sent, ph in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(ph)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    return blob, " ".join(out)


def main() -> int:
    blob, tmpl = template()
    assert VA + len(blob) <= SLOT_END, "thunk_title_hmargin v2 overruns its slot"
    print(f"thunk_title_hmargin v2  {len(blob)} bytes @ pcave2 {VA - PCAVE2:#x}")
    print('        bytes: "' + tmpl + '"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
