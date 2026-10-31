r"""Assemble thunk_tutwin_basel2s -- base-screen tutorial pointer targets.

PORT OF: scaling_laws.py :: tutwin_base_pointer_pt()  (= basewin_pt, the
SOURCE OF TRUTH for every BaseWin interior consumer boundary).

DEFECT FIXED (2026-09-17, 4K shot 20260917-234627 vs refs\pristine\
DronePsych.png): every TutWin site that converts a pointer target through
GraphicWin_local_to_screen(BaseWin_g) hands it a NATIVE BaseWin-local rect
centre (the base screen's interior scales at the primitive boundary, so the
rect fields stay native). At 4K the DRONETOUR6 psych line ended in the map
view: BaseWin origin + (428,394) native instead of + (1070,985) device.

    *x = floor(*x * g/16), *y = floor(*y * g/16)   before the origin add (g > 16)
    g <= 16: pass-through (identity, the vanilla call)

CALL-target redirect for the 19 `mov ecx,BaseWin_g; call local_to_screen`
sites in the TutWin code (do_base 0x4BA8AB, base_rect 0x4BC628, tour6
0x4BADB8/0x4BAE34/0x4BAEC6, tour1 x14). The thunk ALSO gates on ecx ==
BaseWin_g, so it is byte-neutral for any other window (the MainWin-relative
strip rects are DEVICE space already). Entered by CALL with the two int*
args still on the stack ([esp+4] = x*, [esp+8] = y*); scales the pointed
ints in place, then `push local_to_screen; ret` -- the original return
address stays for the callee's RET 8. eax/edx scratch (caller-saved at a
call boundary); ecx = this untouched; flags dead.

SLOT: pcave2 + 0x5E0 (VA 0xA0C5E0), 60 B; free 0x5D4..0x620 after
g_frame_inset_rect (cave_map --at 0x5E0 2026-09-17).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATE = (
    "81 F9 28 76 6A 00 "                    # cmp  ecx,BaseWin_g (0x6A7628)
    "75 2E "                                # jne  tail
    "A1 {abs32:g_popup_scale_num} "         # mov  eax,[g]
    "83 F8 10 "                             # cmp  eax,16
    "7E 24 "                                # jle  tail            (g<=16: identity)
    "8B 54 24 04 "                          # mov  edx,[esp+4]     x*
    "8B 02 "                                # mov  eax,[edx]
    "0F AF 05 {abs32:g_popup_scale_num} "   # imul eax,[g]
    "C1 F8 04 "                             # sar  eax,4           floor(x*g/16)
    "89 02 "                                # mov  [edx],eax
    "8B 54 24 08 "                          # mov  edx,[esp+8]     y*
    "8B 02 "                                # mov  eax,[edx]
    "0F AF 05 {abs32:g_popup_scale_num} "   # imul eax,[g]
    "C1 F8 04 "                             # sar  eax,4
    "89 02 "                                # mov  [edx],eax
    # tail:
    "68 {abs32:GraphicWin_local_to_screen} "  # push local_to_screen
    "C3"                                    # ret  (tail-jmp; ret addr + args intact)
)

SLOT_OFFSET = 0x5E0
SLOT_END = 0x620
PCAVE2_VA = 0x00A0C000
BASEWIN_G = 0x006A7628

SITES = {   # va: function  (all `mov ecx,0x6A7628 ; call 0x5ED240`)
    0x4BA8AB: "TutWin_do_base",
    0x4BADB8: "TutWin_tour6", 0x4BAE34: "TutWin_tour6", 0x4BAEC6: "TutWin_tour6",
    0x4BB86C: "TutWin_tour1", 0x4BB8E6: "TutWin_tour1", 0x4BB960: "TutWin_tour1",
    0x4BB9DA: "TutWin_tour1", 0x4BBA54: "TutWin_tour1", 0x4BBACE: "TutWin_tour1",
    0x4BBB48: "TutWin_tour1", 0x4BC078: "TutWin_tour1", 0x4BC103: "TutWin_tour1",
    0x4BC17D: "TutWin_tour1", 0x4BC211: "TutWin_tour1", 0x4BC2DB: "TutWin_tour1",
    0x4BC355: "TutWin_tour1", 0x4BC3CF: "TutWin_tour1",
    0x4BC628: "TutWin_base_rect",
}
L2S = 0x005ED240


def resolve(template: str, va: int, symbols: dict[str, int]) -> bytes:
    out = bytearray()
    for tok in template.split():
        m = re.fullmatch(r"\{(abs32|rel32):(\w+)\}", tok)
        if not m:
            out.append(int(tok, 16))
            continue
        kind, name = m.groups()
        target = symbols[name]
        if kind == "abs32":
            out += target.to_bytes(4, "little")
        else:
            here = va + len(out) + 4
            out += ((target - here) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def site_original_bytes(va: int) -> str:
    rel = (L2S - (va + 5)) & 0xFFFFFFFF
    return "E8 " + " ".join(f"{b:02X}" for b in rel.to_bytes(4, "little"))


def main() -> int:
    syms = {"g_popup_scale_num": 0, "GraphicWin_local_to_screen": 0}
    blob = resolve(TEMPLATE, PCAVE2_VA + SLOT_OFFSET, syms)
    n = len(blob)
    print(f"thunk_tutwin_basel2s  {n} bytes (slot 0x{SLOT_OFFSET:X}..0x{SLOT_END:X})")
    assert SLOT_OFFSET + n <= SLOT_END, "overruns the slot"
    # branch bookkeeping: both branches land on the `push` (tail)
    tail = n - 6
    assert blob[6] == 0x75 and 8 + blob[7] == tail, "jne displacement"
    jle_at = 6 + 2 + 5 + 3
    assert blob[jle_at] == 0x7E and jle_at + 2 + blob[jle_at + 1] == tail, "jle displacement"
    print()
    print('        bytes: "' + TEMPLATE + '"')
    print()
    for va, fn in SITES.items():
        print(f"  {va:#010x} {fn:<18} original {site_original_bytes(va)}")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import tutwin_base_pointer_pt, basewin_pt  # noqa: E402
    for g in range(16, 41):
        for v in (0, 7, 17, 363, 394, 428, 700, -3):
            have = v if g <= 16 else (v * g) >> 4
            assert have == tutwin_base_pointer_pt(v, g) == basewin_pt(v, g), (g, v)
    print("template arithmetic == scaling_laws.tutwin_base_pointer_pt (= basewin_pt) for g in [16,40]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
