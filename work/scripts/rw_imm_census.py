#!/usr/bin/env python
"""Static immediate census of the HQ report painters (pristine .bak): every instruction carrying an
immediate or a displacement that is a plausible GEOMETRY constant (add/sub/lea/cmp/mov/imul/push with
imm, idiv-by-constant setups, 'and reg,imm' width masks), with the file address of the imm byte(s) so a
row can be poked. Skips calls/jumps/stack adjusts/large addresses.

  py rw_imm_census.py [--exe PATH] [--out FILE]

Ranges = the seven remaining ReportWin canvas painters, their ReportIf console painters, the HOF build
and painter, plus the kind-4/5 click helpers."""
from __future__ import annotations

import io
import os
import sys

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402

RANGES = [
    ("rw_energy  FUN_0049bcd0", 0x49BCD0, 0x49D490),
    ("rw_energy_sel FUN_0049d490", 0x49D490, 0x49D540),
    ("rw_ops     FUN_0049d540", 0x49D540, 0x49EB10),
    ("rw_projects FUN_0049eb10", 0x49EB10, 0x49F350),
    ("rw_sat     FUN_0049f350", 0x49F350, 0x49FFC0),
    ("sat_daemons 0x49ffc0..", 0x49FFC0, 0x4A0260),
    ("sat_attack 0x4a0260", 0x4A0260, 0x4A0810),
    ("rw_units   FUN_004a08e0", 0x4A08E0, 0x4A1140),
    ("rw_score   FUN_004a1140", 0x4A1140, 0x4A2210),
    ("rw_intel   FUN_004a2210", 0x4A2210, 0x4A3460),
    ("ri_energy  FUN_004a84a0", 0x4A84A0, 0x4A9050),
    ("ri_ops     FUN_004a9050", 0x4A9050, 0x4AA0B0),
    ("ri_projects FUN_004aa0b0", 0x4AA0B0, 0x4AA970),
    ("ri_sat     FUN_004aa970", 0x4AA970, 0x4AB600),
    ("ri_units   FUN_004ab600", 0x4AB600, 0x4ABE70),
    ("ri_score   FUN_004abe70", 0x4ABE70, 0x4AC140),
    ("ri_intel   FUN_004ac140", 0x4AC140, 0x4ACDA0),
    ("rw_on_l_click FUN_00496e10", 0x496E10, 0x497A60),
    ("bl_blink   FUN_004a4060", 0x4A4060, 0x4A41D0),
    ("hof_build  load_hoficons", 0x448400, 0x448D90),
    ("hof_paint  0x448d90 (vtbl+0x30)", 0x448D90, 0x44A4B0), ("hof_handlers 0x44a4b0..", 0x44A4B0, 0x44AE50),
    ("hall_of_fame 0x44ae50", 0x44AE50, 0x44B400),
]
SKIP_MN = {"call", "jmp", "ret", "push", "pop"} | {m for m in ("je", "jne", "jl", "jle", "jg", "jge", "ja", "jae", "jb", "jbe", "js", "jns")}


def main() -> int:
    exe = None
    out = os.path.join(HERE, "..", "_rw_imm_census.txt")
    a = sys.argv[1:]
    while a:
        if a[0] == "--exe":
            exe = a[1]; a = a[2:]
        elif a[0] == "--out":
            out = a[1]; a = a[2:]
        else:
            a = a[1:]
    if exe is None:
        exe = str(config.terranx_bak())
    pe = pefile.PE(exe, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    text = None
    for s in pe.sections:
        if s.Name.startswith(b".text"):
            text = (base + s.VirtualAddress, s.get_data())
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    lines = [f"# immediate census of {exe}", ""]
    for label, lo, hi in RANGES:
        lines.append(f"\n## {label}  {lo:#x}..{hi:#x}\n")
        data = text[1][lo - text[0]: hi - text[0]]
        n = 0
        for ins in md.disasm(data, lo):
            if ins.mnemonic in SKIP_MN:
                continue
            found = []
            for op in ins.operands:
                if op.type == X86_OP_IMM:
                    v = op.imm
                    if 0 < abs(v) <= 0x400 or (ins.mnemonic == "and" and 0 < (v & 0xFFFFFFFF) < 0x10000):
                        found.append(("imm", v, op.size))
                elif op.type == X86_OP_MEM and op.mem.disp and op.mem.base != 0 and 0 < abs(op.mem.disp) <= 0x400:
                    # lea reg,[reg+disp] and [reg+disp] operand displacements that are small enough to be geometry
                    if ins.mnemonic == "lea":
                        found.append(("disp", op.mem.disp, 0))
            if not found:
                continue
            # locate the imm/disp bytes inside the encoding
            raw = ins.bytes
            annot = []
            for kind, v, sz in found:
                loc = None
                for w in (1, 4, 2):
                    b = (v & ((1 << (8 * w)) - 1)).to_bytes(w, "little")
                    idx = raw.rfind(b)
                    if idx >= 0 and (w == 1 and -128 <= v < 128 or w != 1):
                        loc = (ins.address + idx, w); break
                annot.append(f"{kind}={v:#x}({v})" + (f"@{loc[0]:#x}/{loc[1]}B" if loc else "@?"))
            lines.append(f"{ins.address:#010x}: {' '.join(f'{b:02X}' for b in raw):<24} {ins.mnemonic:<6} {ins.op_str:<40} ; {' '.join(annot)}")
            n += 1
        lines.append(f"; {n} candidate sites")
    io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print(f"wrote {out} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
