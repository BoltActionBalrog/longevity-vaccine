"""Disassemble a VA range: address, raw bytes, mnemonic. For byte-level patch design.

Usage: python disasm_range.py <hexStartVA> <hexEndVA> [<hexStartVA> <hexEndVA> ...]
"""
import sys
import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"


def main() -> int:
    ranges = []
    a = sys.argv[1:]
    for i in range(0, len(a), 2):
        ranges.append((int(a[i], 16), int(a[i + 1], 16)))

    with pyghidra.open_program(
        binary_path=None, project_location=PROJECT_LOCATION,
        project_name=PROJECT_NAME, program_name=PROGRAM_NAME,
        analyze=False, nested_project_location=False,
    ) as api:
        program = api.getCurrentProgram()
        listing = program.getListing()
        af = program.getAddressFactory()

        def addr(v):
            return af.getDefaultAddressSpace().getAddress(v)

        for start, end in ranges:
            print(f"===== 0x{start:08x} .. 0x{end:08x} =====")
            a = addr(start)
            enda = addr(end)
            while a.getOffset() < enda.getOffset():
                ins = listing.getInstructionAt(a)
                if ins is None:
                    print(f"  {a}  (no instruction)")
                    a = a.add(1)
                    continue
                b = ins.getBytes()
                hexb = " ".join(f"{x & 0xFF:02X}" for x in b)
                print(f"  {a}  {hexb:<28}  {ins}")
                a = a.add(ins.getLength())
    return 0


if __name__ == "__main__":
    sys.exit(main())
