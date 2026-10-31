"""Dump N little-endian int32s at a VA from the Ghidra program image.

Usage (via run-decompile.bat-style env): python dump_data.py <hexVA> <count> [<hexVA> <count> ...]
"""
import sys
import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"


def main() -> int:
    pairs = []
    a = sys.argv[1:]
    for i in range(0, len(a), 2):
        pairs.append((int(a[i], 16), int(a[i + 1])))

    with pyghidra.open_program(
        binary_path=None, project_location=PROJECT_LOCATION,
        project_name=PROJECT_NAME, program_name=PROGRAM_NAME,
        analyze=False, nested_project_location=False,
    ) as api:
        program = api.getCurrentProgram()
        mem = program.getMemory()
        af = program.getAddressFactory()

        def addr(v):
            return af.getDefaultAddressSpace().getAddress(v)

        for va, count in pairs:
            vals = []
            for i in range(count):
                vals.append(mem.getInt(addr(va + i * 4)) & 0xFFFFFFFF)
            print(f"0x{va:08x} x{count}: " + ", ".join(str(v) for v in vals))
            print("           hex : " + ", ".join(f"0x{v:x}" for v in vals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
