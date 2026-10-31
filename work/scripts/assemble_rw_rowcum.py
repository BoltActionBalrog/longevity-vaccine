"""t_rw_bases_rowstep / t_rw_energy_stride -- HQ report rows at vanilla x g/16 pitch (F4 BASE STATUS, F3 ENERGY).

F4 (kind 4 painter, PRACX base 2d0b1438): the row loop advances both row rects by the pitch [ebp-0x1C] = cell + s(2)
(0x49D687, walker-scaled) at 0x49D9E1 whenever the base index i (ecx) passes the first visible index [+0xC0FC] (eax):
  0x49D9E1  8B 45 E4  mov eax,[ebp-0x1C] / 8B 7D BC  mov edi,[ebp-0x44] / 8B 4D C4  mov ecx,[ebp-0x3C]   (9 bytes)
-> jmp t_rw_bases_rowstep + 4 NOP; the thunk replays the two loads and hands eax = bases_row_advance(i - first, g),
returning to 0x49D9EA (edx is reloaded there).  Law scaling_laws.bases_row_advance: row k at s(42k).
F3 (kind 3 painter): the energy ListBox's row stride [Dialog+0x48] = [ReportWin+0xE268] + s(3):
  0x49CC7D  8B 96 68 E2 00 00  mov edx,[esi+0xE268] / 2B C8  sub ecx,eax / 03 D0  add edx,eax   (10 bytes)
-> jmp t_rw_energy_stride + 5 NOP; edx = rw_energy_row_stride (s(18) at g > 16), back to 0x49CC87.
Flags are dead after both sites (next reader is a load / store run ending in a call or a cmp).  g <= 16: the
engine's own bytes' result.  Neither site is a PRACX hook (refs\\pracx\\shared\\pracx.cpp) nor in patches.yaml.

Usage: assemble_rw_rowcum.py      -> prints the yaml symbol + content + site lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
G = 0x00668740
BASES_OFF, BASES_END = 0x306C0, 0x30700     # cave_map: free between t_pw_fit1 (planwin_native_render) and thunk_pf_frame_align
ENERGY_OFF, ENERGY_END = 0x5BD0, 0x5C00     # cave_map --fit 48 vs master yaml: free after g_hud_rect4, before thunk_worldwin_fill
BASES_SITE, BASES_BACK = 0x0049D9E1, 0x0049D9EA
ENERGY_SITE, ENERGY_BACK = 0x0049CC7D, 0x0049CC87
SITES = {"ReportWin_draw_bases.rowstep": (BASES_SITE, "8B 45 E4 8B 7D BC 8B 4D C4", "t_rw_bases_rowstep", 9),
         "ReportWin_draw_energy.row_stride": (ENERGY_SITE, "8B 96 68 E2 00 00 2B C8 03 D0", "t_rw_energy_stride", 10)}
PITCH = 42
STRIDE = 18


def asm_bases() -> str:
    # in: ecx = i, eax = first visible (i > first).  out: eax = s(42k) - s(42(k-1)), k = i - first; edi/ecx replayed.
    return f"""
    mov     edx, dword ptr [{G:#x}]
    cmp     edx, 0x10
    jg      scaled
    mov     eax, dword ptr [ebp-0x1c]
    jmp     tail
scaled:
    sub     ecx, eax
    imul    edx, edx, {PITCH}
    imul    ecx, edx
    lea     eax, [ecx*2+15]
    sar     eax, 5
    sub     ecx, edx
    lea     ecx, [ecx*2+15]
    sar     ecx, 5
    sub     eax, ecx
tail:
    mov     edi, dword ptr [ebp-0x44]
    mov     ecx, dword ptr [ebp-0x3c]
    jmp     {BASES_BACK:#x}
"""


def asm_energy() -> str:
    return f"""
    mov     edx, dword ptr [esi+0xe268]
    sub     ecx, eax
    add     edx, eax
    cmp     dword ptr [{G:#x}], 0x10
    jle     back
    mov     edx, dword ptr [{G:#x}]
    imul    edx, edx, {2 * STRIDE}
    add     edx, 15
    sar     edx, 5
back:
    jmp     {ENERGY_BACK:#x}
"""


def _build(src: str, off: int, end: int, name: str) -> bytes:
    va = PCAVE2 + off
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    assert off + len(b) <= end, f"{name} {len(b)}B overflows its slot"
    return b


def build() -> tuple:
    return (_build(asm_bases(), BASES_OFF, BASES_END, "t_rw_bases_rowstep"),
            _build(asm_energy(), ENERGY_OFF, ENERGY_END, "t_rw_energy_stride"))


def site_bytes(site: int, thunk_va: int, length: int) -> bytes:
    rel = (thunk_va - (site + 5)) & 0xFFFFFFFF
    return b"\xE9" + rel.to_bytes(4, "little") + b"\x90" * (length - 5)


def _tpl(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b).replace("40 87 66 00", "{abs32:g_popup_scale_num}")


def main() -> int:
    bb, eb = build()
    print(f"  t_rw_bases_rowstep:            {{ cave: pcave2, offset: {BASES_OFF:#x} }}   # {len(bb)}B")
    print(f"  t_rw_energy_stride:            {{ cave: pcave2, offset: {ENERGY_OFF:#x} }}   # {len(eb)}B")
    print(f"      - id: t_rw_bases_rowstep\n        offset: {BASES_OFF:#x}\n        bytes: \"{_tpl(bb)}\"")
    print(f"      - id: t_rw_energy_stride\n        offset: {ENERGY_OFF:#x}\n        bytes: \"{_tpl(eb)}\"")
    for name, (va, orig, thunk, n) in SITES.items():
        print(f"  site {name} {va:#x} orig {orig} -> jmp {thunk} + {n - 5} NOP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
