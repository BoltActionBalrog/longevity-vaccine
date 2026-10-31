"""Dump N dword pointers starting at a VA (for reading vtables). Usage: dump_vtable.py 0x66ff40 0x180"""
import sys
import pyghidra
pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"


def main() -> int:
    base = int(sys.argv[1], 16)
    span = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x180
    with pyghidra.open_program(
        binary_path=None, project_location=PROJECT_LOCATION, project_name=PROJECT_NAME,
        program_name=PROGRAM_NAME, analyze=False, nested_project_location=False,
    ) as api:
        p = api.getCurrentProgram(); af = p.getAddressFactory(); mem = p.getMemory()
        sp = af.getDefaultAddressSpace()
        for i in range(0, span, 4):
            va = base + i
            v = mem.getInt(sp.getAddress(va)) & 0xffffffff
            print(f"  +0x{i:03x} (slot {i//4:2d}) = 0x{v:08x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
