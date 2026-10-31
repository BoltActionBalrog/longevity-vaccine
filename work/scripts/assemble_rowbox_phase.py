"""t_rowbox_ph -- popup option-row bars on the popup's stripe grid (2026-10-11).

The per-option row frame call at FUN_00405b20+0xD6 (0x405BF6, site FUN_00405b20.option_frame) draws
into the Dialog's OWN child GraphicWin (Dialog_type16_attach 0x60D1F0 creates it; type-1 checkbox and
type-2 ListBox lists draw through the same item_back_draw), whose buffer row 0 sits at a popup-local top
that is not a multiple of the stripe period P: thunk_fe_pair_remap (reached through thunk_rowbox_guard ->
thunk_box_thick_hollow_flat -> thunk_frame_enlarge) regenerated the bars' 0xE0/0xE1 / 0xAE/0xEE stripes
from the CHILD's row 0, so they sat a row (g=22: child top 225) or half a period (g=40: 410) off the popup
frame's grid (Protocol Director shots 1920x1080 200650, 4K 125149).

This CALL wrapper replaces {rel32:thunk_rowbox_guard} at the site: g>16 -> g_rm_yph = the child's
parent-local top (Win +0x140 + +0x150; Win = ecx - 0x444) reduced to [0, P) -- law
scaling_laws.option_row_stripe_phase, the same as thunk_btn_stripes v13's FlatButton staging -- around the
guard call, cleared after.  g<=16 -> straight jmp to the guard (native).  thiscall, 2 args, RET 8; ecx and
every callee-saved register are the guard's own contract; eax (the guard's return) is preserved.

Usage: assemble_rowbox_phase.py      -> prints the yaml symbol + content lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
OFF = 0x11040                     # cave_map: 0x11040..0x110A0 free (thunk_q16_fill_width v6 ends 0x11040)
END = 0x110A0                     # t_bw_wheel_down
G = 0x00668740                    # g_popup_scale_num
G_STRIPE_PERIOD = 0x0066879C      # g_stripe_period (P; written with g by thunk_ensure_scale)
G_RM_YPH = PCAVE2 + 0x103FC       # thunk_fe_pair_remap v8 row-phase cell
ROWBOX_GUARD = PCAVE2 + 0x3DC0    # thunk_rowbox_guard (thiscall, RET 8)
SITE = 0x00405BF6

ABS = {G: "{abs32:g_popup_scale_num}", G_STRIPE_PERIOD: "{abs32:g_stripe_period}", G_RM_YPH: "{abs32:g_rm_yph}"}
REL = {ROWBOX_GUARD: "{rel32:thunk_rowbox_guard}"}


def asm_rowbox_ph() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     plain
    mov     eax, dword ptr [ecx-0x304]
    add     eax, dword ptr [ecx-0x2F4]
    jns     ok
    cdq
    idiv    dword ptr [{G_STRIPE_PERIOD:#x}]
    mov     eax, edx
    add     eax, dword ptr [{G_STRIPE_PERIOD:#x}]
ok:
    mov     dword ptr [{G_RM_YPH:#x}], eax
    push    dword ptr [esp+8]
    push    dword ptr [esp+8]
    call    {ROWBOX_GUARD:#x}
    and     dword ptr [{G_RM_YPH:#x}], 0
    ret     8
plain:
    jmp     {ROWBOX_GUARD:#x}
"""


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):   # the patcher takes {rel32:} after E8 only; a JMP stays raw (fixed VAs)
            tgt = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in REL:
                out += [f"{b[i]:02X}", REL[tgt]]
                i += 5
                continue
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in ABS:
            out.append(ABS[int.from_bytes(b[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def build() -> bytes:
    b = assemble(asm_rowbox_ph(), PCAVE2 + OFF)
    assert OFF + len(b) <= END, f"t_rowbox_ph {len(b)}B overflows its slot"
    return b


def main() -> int:
    b = build()
    print(f"  t_rowbox_ph:                   {{ cave: pcave2, offset: {OFF:#x} }}   # {len(b)}B")
    print(f"      - id: t_rowbox_ph\n        offset: {OFF:#x}\n        bytes: \"{to_template(b, PCAVE2 + OFF)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
