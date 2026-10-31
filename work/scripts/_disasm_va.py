"""Disassemble a VA range from the UNPATCHED exe (the pristine .bak beside the target).

Usage: _disasm_va.py 0x604d80 0x604e05

This is the vanilla code a patch site must be measured against. For the code the game runs
after patching (caves included) use _disasm_live.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import pefile  # noqa: E402
from capstone import Cs, CS_ARCH_X86, CS_MODE_32  # noqa: E402

EXE = str(config.terranx_bak(required=True))

start = int(sys.argv[1], 16)
end = int(sys.argv[2], 16)

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
data = None
for s in pe.sections:
    va = base + s.VirtualAddress
    if va <= start < va + s.Misc_VirtualSize:
        off = start - va
        data = s.get_data()[off: off + (end - start)]
        break
if data is None:
    print("VA not found in any section"); sys.exit(1)

md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = False
for ins in md.disasm(bytes(data), start):
    raw = " ".join(f"{b:02X}" for b in ins.bytes)
    print(f"0x{ins.address:08x}: {raw:<24} {ins.mnemonic:<7} {ins.op_str}")
