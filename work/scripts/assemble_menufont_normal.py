r"""Assemble thunk_popnorm_menufont -- popups_normal's g_menu_font store.

PORT OF: scaling_laws.py :: menu_font_request()  (the SOURCE OF TRUTH).

DEFECT FIXED (2026-09-18, 4K shot 20260918-000615): after ANY tutorial popup
(Help > Design Workshop Tour, hints, ...) every HUD dropdown submenu -- the
universal Menu control, sized and drawn purely from g_menu_font 0x9B7B68 --
reverted to native-tiny. TutWin_tut_win ends in popups_normal 0x588460, whose
0x5886C1 `mov [g_menu_font],ecx` re-installs the native
[g_popup_menu_font_src]; the bake only scaled the OTHER writer
(thunk_menu_layout, the MENU widget's layout), which does not run again.

SITE  0x5886C1  89 0D 68 7B 9B 00   mov [0x9B7B68],ecx   (6 B; not a branch
      target, not PRACX-stomped)  ->  E8 {rel32:thunk_popnorm_menufont} 90
CALL-entered helper, bare RET (memory feedback-thunk-call-vs-detour).
pushad/pushfd transparent: every register and EFLAGS survive, so the site's
live ecx/edx/esi/edi and the pending `add esp,0x40` frame are untouched.

    g <= 16                       -> [g_menu_font] = ecx   (the displaced insn)
    g  > 16                       -> [g_menu_font] = find_font(min(g,40), 1)
    find_font returned NULL       -> [g_menu_font] = ecx

SLOT: pcave2 + 0x47B0 (VA 0xA107B0), 49 B, inside the free 0x47A6..0x4800
gap between t_rwk_boxforce and g_netwin_active (cave_map --at 0x47a6 +
live-byte zero check 2026-09-18).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_tutwin_popx import resolve  # noqa: E402  (the apply_patches-equivalent resolver)

TEMPLATE = (
    "60 "                                   # pushad
    "9C "                                   # pushfd
    "A1 {abs32:g_popup_scale_num} "         # mov  eax,[g]
    "83 F8 10 "                             # cmp  eax,16
    "7E 19 "                                # jle  native
    "83 F8 28 "                             # cmp  eax,40
    "7E 05 "                                # jle  +5
    "B8 28 00 00 00 "                       # mov  eax,40
    "6A 01 "                                # push 1                 variant
    "50 "                                   # push eax               size
    "E8 {rel32:find_font} "                 # cdecl(size, variant) -> Font*
    "83 C4 08 "                             # add  esp,8
    "85 C0 "                                # test eax,eax
    "75 04 "                                # jnz  store
    # native:
    "8B 44 24 1C "                          # mov  eax,[esp+0x1C]    pushad's ECX (under pushfd)
    # store:
    "A3 {abs32:g_menu_font} "               # mov  [g_menu_font],eax
    "9D "                                   # popfd
    "61 "                                   # popad
    "C3"                                    # ret
)

SLOT_OFFSET = 0x47B0
SLOT_END = 0x4800
PCAVE2_VA = 0x00A0C000
SITE_VA = 0x005886C1


def main() -> int:
    blob = resolve(TEMPLATE, PCAVE2_VA + SLOT_OFFSET,
                   {"g_popup_scale_num": 0, "g_menu_font": 0, "find_font": 0})
    n = len(blob)
    print(f"thunk_popnorm_menufont  {n} bytes (slot 0x{SLOT_OFFSET:X}..0x{SLOT_END:X})")
    assert SLOT_OFFSET + n <= SLOT_END, "overruns the slot"
    # branch bookkeeping
    native_i = blob.index(bytes.fromhex("8B44241C"))
    jle_i = blob.index(bytes.fromhex("7E19"))
    assert jle_i + 2 + 0x19 == native_i, "jle native displacement"
    jnz_i = blob.index(bytes.fromhex("7504"))
    assert jnz_i + 2 + 4 == native_i + 4, "jnz store displacement"
    print()
    print('        bytes: "' + TEMPLATE + '"')
    print()

    from scaling_laws import menu_font_request
    for g in range(16, 49):
        want = menu_font_request(g)
        have = None if g <= 16 else (min(g, 40), 1)
        assert want == have, (g, want, have)
    print("template arithmetic == scaling_laws.menu_font_request for g in [16,48]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
