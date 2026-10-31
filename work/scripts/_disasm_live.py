"""Disassemble a VA range from the LIVE (patched) exe.

Usage: _disasm_live.py 0x604df0 0x604dfb

The exe is the configured target (work\\game-path.txt / work\\game-exe.txt, see config.py), so
what is printed is the code the game will actually run, caves included. For the unpatched
bytes use _disasm_va.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import pefile  # noqa: E402
from capstone import Cs, CS_ARCH_X86, CS_MODE_32  # noqa: E402

EXE = str(config.terranx(required=True))
start = int(sys.argv[1], 16); end = int(sys.argv[2], 16)
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
data = None
for s in pe.sections:
    va = base + s.VirtualAddress
    if va <= start < va + max(s.Misc_VirtualSize, s.SizeOfRawData):
        off = start - va
        data = s.get_data()[off: off + (end - start)]
        print(f"# section {s.Name.rstrip(bytes([0,0x20])).decode()}  VA=0x{va:x}")
        break
if data is None:
    print("VA not found"); sys.exit(1)
md = Cs(CS_ARCH_X86, CS_MODE_32)
for ins in md.disasm(bytes(data), start):
    raw = " ".join(f"{b:02X}" for b in ins.bytes)
    print(f"0x{ins.address:08x}: {raw:<26} {ins.mnemonic:<7} {ins.op_str}")
