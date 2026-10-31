"""Dump the instruction listing (address + bytes + mnemonic/operands) for functions.

Usage (via run-decompile.bat, which sets JAVA_HOME/GHIDRA env then runs python):
    run-decompile.bat  -> but that calls decompile_funcs.py. Instead invoke directly:
    python dump_listing.py 0x4887a0 0x489660

Read-only (analyze=False). Annotates CALL targets and flags instructions whose operands
reference faction-window field offsets / size constants of interest, so call-site VAs
(GraphicWin_init / Dialog_init_3 / field stores) are easy to pin for Phase-1 thunk placement.
"""

import sys
import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# operand substrings worth flagging (field offsets + size literals from the confirmed lever map)
FLAG = ["0x6244", "0x6248", "0x623c", "0x6240", "0x624c", "0x86ac", "0x86b0", "0x86b4", "0x86b8",
        "0x316", "0x12c", "0x9240", "0x9250", "0x9210", "0x9220", "0x9230", "0x9260",
        "0xd638", "0xd63c", "0x625c", "0x626c", "0x627c", "0x13", "0xa1c", "0xa20", "0xa14", "0xa18"]


def main() -> int:
    targets = [int(a, 16) for a in sys.argv[1:] if a.strip()]
    if not targets:
        print("no addresses given")
        return 1

    with pyghidra.open_program(
        binary_path=None, project_location=PROJECT_LOCATION, project_name=PROJECT_NAME,
        program_name=PROGRAM_NAME, analyze=False, nested_project_location=False,
    ) as api:
        program = api.getCurrentProgram()
        fm = program.getFunctionManager()
        listing = program.getListing()
        af = program.getAddressFactory()

        def addr(v):
            return af.getDefaultAddressSpace().getAddress(v)

        for t in targets:
            func = fm.getFunctionAt(addr(t)) or fm.getFunctionContaining(addr(t))
            if func is None:
                print(f"\n##### NO FUNCTION at 0x{t:08x} #####")
                continue
            print(f"\n##### {func.getName()} @ {func.getEntryPoint()} #####")
            it = listing.getInstructions(func.getBody(), True)
            while it.hasNext():
                ins = it.next()
                a = ins.getAddress()
                mn = ins.toString()
                # call target annotation
                note = ""
                if ins.getMnemonicString().lower().startswith("call"):
                    refs = ins.getReferencesFrom()
                    for r in refs:
                        tf = fm.getFunctionAt(r.getToAddress())
                        if tf is not None:
                            note = f"   -> {tf.getName()}"
                            break
                flag = "  <==FLAG" if any(s in mn for s in FLAG) else ""
                print(f"  {a}: {mn}{note}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
