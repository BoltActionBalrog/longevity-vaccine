"""Print all references TO a set of addresses, with the containing function.
Usage: run via ghidra python: xref_addrs.py 0x9380DC 0x9b7b58 ...
"""
import sys
import pyghidra
pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"


def main() -> int:
    targets = [int(a, 16) for a in sys.argv[1:] if a.strip()]
    if not targets:
        print("no addrs")
        return 1
    with pyghidra.open_program(
        binary_path=None, project_location=PROJECT_LOCATION, project_name=PROJECT_NAME,
        program_name=PROGRAM_NAME, analyze=False, nested_project_location=False,
    ) as api:
        program = api.getCurrentProgram()
        rm = program.getReferenceManager()
        fm = program.getFunctionManager()
        af = program.getAddressFactory()
        sp = af.getDefaultAddressSpace()
        for t in targets:
            ta = sp.getAddress(t)
            print(f"\n===== refs TO 0x{t:08x} =====")
            refs = rm.getReferencesTo(ta)
            n = 0
            for r in refs:
                frm = r.getFromAddress()
                fn = fm.getFunctionContaining(frm)
                fname = fn.getName() if fn else "?"
                fentry = f"0x{fn.getEntryPoint().getOffset():08x}" if fn else "?"
                print(f"  {frm}  {r.getReferenceType()}  in {fname} ({fentry})")
                n += 1
            if n == 0:
                print("  (none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
