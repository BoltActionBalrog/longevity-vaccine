r"""Assemble thunk_tutwin_popx -- the drone tour's citizens-row pointer x.

PORT OF: scaling_laws.py :: tutwin_pop_pointer_x()  (the SOURCE OF TRUTH).

DEFECT FIXED (2026-09-17, 4K shot 20260917-225639 vs refs\pristine\
DroneDetails.png): the DRONETOUR1 / DRONETOUR5 tooltips (TutWin_tour6
0x4BAA70) point their line at `citizens_rect.left + 5` -- the raw MainWin-
LOCAL left -- while only y goes through GraphicWin_local_to_screen. A VANILLA
bug masked at 1024x768 (strip origin x = 0); at 4K the strip is centred at
x=640 and the rect is device-scaled, so the line ended on the console's
left rail, 690 px left of the drone citizen.

    x = MainWin.x + left_dev + floor(5*g/16)      (g > 16)
    x = left + 5                                   (g <= 16, the displaced insn)

SITES (identical 5-byte blocks, ONE shared thunk):
    0x4BAB5B  83 C2 05 51 52   add edx,5 ; push ecx ; push edx    (DRONETOUR1)
    0x4BAD49  83 C2 05 51 52   add edx,5 ; push ecx ; push edx    (DRONETOUR5)
Live at entry: eax = anchor Win* (pushed 5 bytes later), ecx = converted
centre y, edx = rect.left (device), ebx = TutWin this. CALL-entered: the
return address is consumed into g_tw_ret (memory feedback-thunk-call-vs-
detour), the two pushes are re-issued under it, resume = jmp [g_tw_ret]
(next site insn `push label`). eax/ecx preserved across the engine call
(caller-saved there); flags dead at resume.

SLOT: pcave2 + 0x4240 (VA 0xA10240), 68 B; g_tw_ret @ +0x4290 (4 B); the
slot is the free 0x60 between t_bw_wheel_up (in gwinit v2's old 0x4130 slot; gwinit itself is at
0x3C100 since W5A, 2026-10-25) and thunk_box_thick_devfill (cave_map --at 0x4240 2026-09-17).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Hand-assembled (hex + placeholders). Comments name every instruction;
# tests\test_tutwin_popx_asm_parity.py emulates the RESOLVED bytes under
# Unicorn against the law for every g in [16,40].
TEMPLATE = (
    "50 "                                   # push eax            (anchor, live)
    "51 "                                   # push ecx            (y, live)
    "A1 {abs32:g_popup_scale_num} "         # mov  eax,[g]
    "83 F8 10 "                             # cmp  eax,16
    "7F 05 "                                # jg   scaled
    "83 C2 05 "                             # add  edx,5          (g<=16: the displaced insn)
    "EB 23 "                                # jmp  fin
    # scaled:
    "8D 04 80 "                             # lea  eax,[eax+eax*4]   5*g
    "C1 F8 04 "                             # sar  eax,4             floor(5g/16)
    "01 C2 "                                # add  edx,eax           left_dev + inset
    "6A 00 "                                # push 0                 ytmp
    "52 "                                   # push edx               x
    "8D 44 24 04 "                          # lea  eax,[esp+4]       &ytmp
    "50 "                                   # push eax               arg y*
    "8D 44 24 04 "                          # lea  eax,[esp+4]       &x
    "50 "                                   # push eax               arg x*
    "B9 20 E8 7A 00 "                       # mov  ecx,MainWin_g (0x7AE820)
    "E8 {rel32:GraphicWin_local_to_screen} "  # thiscall RET 8: *x += origin chain
    "5A "                                   # pop  edx               x (screen)
    "83 C4 04 "                             # add  esp,4             drop ytmp
    # fin:
    "59 "                                   # pop  ecx
    "58 "                                   # pop  eax
    "51 "                                   # push ecx               (re-issued site push)
    "52 "                                   # push edx               (re-issued site push)
    "FF 25 {abs32:g_tw_ret}"                # jmp  [g_tw_ret]
)

TEMPLATE_ENTRY = "8F 05 {abs32:g_tw_ret} " + TEMPLATE   # pop [g_tw_ret] first

SLOT_OFFSET = 0x4240
SLOT_END = 0x42A0
RET_CELL_OFFSET = 0x4290
PCAVE2_VA = 0x00A0C000


def resolve(template: str, va: int, symbols: dict[str, int]) -> bytes:
    """Resolve {abs32:}/{rel32:} placeholders the way apply_patches does,
    for a thunk placed at `va`. rel32 is relative to the END of the E8."""
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
            here = va + len(out) + 4          # end of the rel32 field
            out += ((target - here) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def main() -> int:
    blob = resolve(TEMPLATE_ENTRY, PCAVE2_VA + SLOT_OFFSET,
                   {"g_popup_scale_num": 0, "g_tw_ret": 0,
                    "GraphicWin_local_to_screen": 0})
    n = len(blob)
    print(f"thunk_tutwin_popx  {n} bytes (slot 0x{SLOT_OFFSET:X}..0x{RET_CELL_OFFSET:X})")
    assert SLOT_OFFSET + n <= RET_CELL_OFFSET, "overruns g_tw_ret"
    assert RET_CELL_OFFSET + 4 <= SLOT_END, "g_tw_ret overruns the slot"
    # branch bookkeeping: jg +5 lands on the `lea`; jmp +0x23 lands on `pop ecx`
    body = TEMPLATE.split()
    jg_i = body.index("7F") + 2
    lea_i = body.index("8D")
    assert body[jg_i:jg_i + 5] == ["83", "C2", "05", "EB", "23"]
    assert body[lea_i] == "8D" and body[lea_i - 1] == "23"
    fin_i = body.index("59")
    scaled_len = len(resolve(" ".join(body[lea_i:fin_i]), 0,
                             {"GraphicWin_local_to_screen": 0}))
    assert scaled_len == 0x23, f"jmp fin displacement: scaled block is {scaled_len:#x}"
    print()
    print('        bytes: "' + TEMPLATE_ENTRY + '"')
    print()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import tutwin_pop_pointer_x  # noqa: E402
    for g in range(16, 41):
        want = tutwin_pop_pointer_x(667, 640, g)
        have = (667 + 5) if g <= 16 else 640 + 667 + ((5 * g) >> 4)
        assert want == have, (g, want, have)
    print("template arithmetic == scaling_laws.tutwin_pop_pointer_x for g in [16,40]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
