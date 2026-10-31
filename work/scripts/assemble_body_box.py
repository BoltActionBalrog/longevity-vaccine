"""Assemble t_gv_bodyb (W9C F54, 2026-10-27): PORT of scaling_laws.popup_body_box_bottom.  Guards:
tests/test_body_box_asm_parity.py (these bytes under Unicorn against the law), tests/test_scaling_popup_body_box.py
(the Planetary Governor popup and its siblings drawn end to end on the real image).

  t_gv_bodyb  call-redirect at Popup_on_draw_background's d528 body-box draw 0x406154 (was `call thunk_d528_inset`),
              in FRONT of thunk_d528_inset: g > 16, esi != the faction-quote popup 0x9403E0, and the outer union is the
              text rect alone ([esi+0x2350] == -1, or art [esi+0x2144] != 0 with or without a dialog;
              reach: plain text + OK popups, TutWin, MPRECEIVEFILE, UPHEAVAL / NERVESTAPLE / CALLSCOUNCIL) -> `dec [ebp-0x28]`, the body rect's B (the
              rect the call draws -- its arg is &[ebp-0x34] -- and the one the union is built from at 0x4061FA); then
              push thunk_d528_inset / ret: the site's call, args, ecx and flags-free contract unchanged.
              Every register and EFLAGS kept (pushfd; the site's next instruction reloads eax anyway).

Usage: py assemble_body_box.py -> the yaml content line.
"""
from __future__ import annotations

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard)

PCAVE2 = 0xA0C000
REGION = (0x3FE70, 0x40000)                        # W9C's pcave2 region B
SENT = {"g_popup_scale_num": 0x7EAD0100, "thunk_d528_inset": 0x7EAD0200}
LAYOUT = {"t_gv_bodyb": (0x3FE70, 0x3FEC0)}
FACTION_QUOTE_POPUP = 0x9403E0
SITE = 0x406154
ORDER = list(LAYOUT)


def va(name: str) -> int:
    if name in LAYOUT:
        return PCAVE2 + LAYOUT[name][0]
    return SENT[name]


def asm_bodyb() -> str:
    return f"""
    pushfd
    cmp dword ptr [{va("g_popup_scale_num"):#x}], 0x10
    jle bb_pass
    cmp esi, {FACTION_QUOTE_POPUP:#x}
    je bb_pass
    cmp dword ptr [esi+0x2350], -1
    je bb_dec
    cmp dword ptr [esi+0x2144], 0
    je bb_pass
bb_dec:
    dec dword ptr [ebp-0x28]
bb_pass:
    popfd
    push {va("thunk_d528_inset"):#x}
    ret
"""


ASM = {"t_gv_bodyb": asm_bodyb}


def assemble(name: str, resolve: dict | None = None) -> bytes:
    src = ASM[name]()
    assert ";" not in src
    if resolve:
        for n, s in SENT.items():
            src = src.replace(f"{s:#x}", f"{resolve[n]:#x}")
    off, end = LAYOUT[name]
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, PCAVE2 + off)[0])
    assert REGION[0] <= off and off + len(b) <= end <= REGION[1], (name, hex(off), len(b))
    return b


def template(name: str) -> str:
    b = assemble(name)
    rev = {v: k for k, v in SENT.items()}
    out, i = [], 0
    while i < len(b):
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in rev:
            out.append(f"{{abs32:{rev[int.from_bytes(b[i:i + 4], 'little')]}}}")
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    tpl = " ".join(out)
    for s in SENT.values():
        assert s.to_bytes(4, "little").hex(" ").upper() not in tpl, (name, hex(s))
    return tpl


def main() -> int:
    for name in ORDER:
        off, end = LAYOUT[name]
        print(f"; {name} {len(assemble(name))} B @{off:#x} (slot to {end:#x})")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
