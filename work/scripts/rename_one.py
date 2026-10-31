"""Force-rename a single symbol at a VA (overrides an existing custom name)."""
import sys
import pyghidra

pyghidra.start()
PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

VA = int(sys.argv[1], 16)
NEW = sys.argv[2]

with pyghidra.open_program(
    binary_path=None, project_location=PROJECT_LOCATION,
    project_name=PROJECT_NAME, program_name=PROGRAM_NAME,
    analyze=False, nested_project_location=False,
) as api:
    program = api.getCurrentProgram()
    af = program.getAddressFactory()
    fm = program.getFunctionManager()
    from ghidra.program.model.symbol import SourceType
    addr = af.getDefaultAddressSpace().getAddress(VA)
    func = fm.getFunctionAt(addr)
    txn = program.startTransaction("rename")
    try:
        old = func.getName()
        func.setName(NEW, SourceType.USER_DEFINED)
        print(f"renamed 0x{VA:08x}: {old} -> {NEW}")
    finally:
        program.endTransaction(txn, True)
    program.save("rename", None)
