"""t_ol8_calcgap -- the type-8 OptionList row window reserves the SCALED column gap (2026-10-11).

OptionList_calculate_dimensions' tail (0x610C25..0x610C41) computes [D+0x5c] = max([D+0x2c],
([D+0x64] + gap)*cols - gap) with the NATIVE gap [D+0x44], while OptionList_draw_item strides the columns by
[D+0x64] + s(gap) (thunk_ol8_gap, site 0x610C84).  A multi-column list (the unit-stack picker with 13+ units)
therefore drew (cols-1)*(s(gap)-gap) px past its row window and the last column's labels were clipped.

CALL helper over `mov edx,[ecx+0x44]; add eax,edx` at 0x610C2B (5 bytes): edx = the gap, scaled
fl(gap*g/16) when g > 16 (law scaling_laws.optionlist8_list_width / optionlist8_row_origin_gap), eax += edx.
The caller's following `imul eax,[ecx+0x54]; sub eax,edx` then use the same scaled gap.  ecx preserved; flags
dead (imul follows).

Usage: assemble_ol8_calcgap.py      -> prints the yaml symbol + content + site lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
OFF = 0x30360                      # cave_map: 0x30359..0x30380 free (t_rwk_con_lbr .. thunk_se_btnrun)
END = 0x30380
G = 0x00668740                     # g_popup_scale_num
SITE = 0x00610C2B
SITE_ORIG = bytes.fromhex("8B514403C2")   # mov edx,[ecx+0x44]; add eax,edx


def asm_calcgap() -> str:
    return f"""
    mov     edx, dword ptr [ecx+0x44]
    cmp     dword ptr [{G:#x}], 0x10
    jle     n
    imul    edx, dword ptr [{G:#x}]
    sar     edx, 4
n:
    add     eax, edx
    ret
"""


def build() -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm_calcgap(), PCAVE2 + OFF)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, PCAVE2 + OFF)) == len(b)
    assert OFF + len(b) <= END, f"t_ol8_calcgap {len(b)}B overflows its slot"
    return b


def main() -> int:
    b = build()
    tpl = " ".join(f"{x:02X}" for x in b).replace("40 87 66 00", "{abs32:g_popup_scale_num}")
    print(f"  t_ol8_calcgap:                 {{ cave: pcave2, offset: {OFF:#x} }}   # {len(b)}B")
    print(f"      - id: t_ol8_calcgap\n        offset: {OFF:#x}\n        bytes: \"{tpl}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
