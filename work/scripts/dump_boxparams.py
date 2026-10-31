"""Dump BoxSpriteParams structs for the title boxes + GraphicWin_fill_2 disasm + titled-branch disasm."""
import pyghidra
pyghidra.start()
PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

with pyghidra.open_program(
    binary_path=None, project_location=PROJECT_LOCATION,
    project_name=PROJECT_NAME, program_name=PROGRAM_NAME,
    analyze=False, nested_project_location=False,
) as api:
    program = api.getCurrentProgram()
    af = program.getAddressFactory()
    mem = program.getMemory()
    sp = af.getDefaultAddressSpace()

    def rdptr(va):
        b = bytearray(4)
        mem.getBytes(sp.getAddress(va), b)
        return int.from_bytes(b, 'little')

    for name, va in (("d5a0", 0x0078d5a0), ("d618", 0x0078d618), ("d690", 0x0078d690), ("d528", 0x0078d528)):
        print(f"\n=== {name} @ 0x{va:08x} (10 dwords) ===")
        for i in range(10):
            v = rdptr(va + i*4)
            print(f"  param[{i}] (+0x{i*4:02x}) = 0x{v:08x}")
