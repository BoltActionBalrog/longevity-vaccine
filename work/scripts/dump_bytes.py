"""Dump raw hex bytes at (va,len) pairs. Usage: python dump_bytes.py 0x488bdf:5 0x607210:8 ..."""
import sys
import pyghidra
pyghidra.start()
PL = r"D:\SmacxUi\work\ghidra-projects"; PN = "terranx"; PROG = "terranx.exe"
def main():
    pairs = []
    for a in sys.argv[1:]:
        va, ln = a.split(":"); pairs.append((int(va, 16), int(ln)))
    with pyghidra.open_program(binary_path=None, project_location=PL, project_name=PN,
                              program_name=PROG, analyze=False, nested_project_location=False) as api:
        prog = api.getCurrentProgram(); af = prog.getAddressFactory(); mem = prog.getMemory()
        def addr(v): return af.getDefaultAddressSpace().getAddress(v)
        for va, ln in pairs:
            vals = []
            for i in range(ln):
                vals.append(mem.getByte(addr(va + i)) & 0xff)
            print(f"0x{va:08x} ({ln}): " + " ".join(f"{x:02X}" for x in vals))
    return 0
if __name__ == "__main__":
    sys.exit(main())
