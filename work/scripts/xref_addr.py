"""List all references (code + data) TO given absolute addresses, with containing function.
Usage:  python xref_addr.py 0x9403e0 ...
Read-only. Used to find where a global object's position/fields are written/read."""
import sys
import pyghidra
pyghidra.start()
PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

def main() -> int:
    targets = [int(a, 16) for a in sys.argv[1:] if a.strip()]
    if not targets:
        print("no addresses"); return 1
    with pyghidra.open_program(binary_path=None, project_location=PROJECT_LOCATION,
                               project_name=PROJECT_NAME, program_name=PROGRAM_NAME,
                               analyze=False, nested_project_location=False) as api:
        program = api.getCurrentProgram()
        rm = program.getReferenceManager()
        fm = program.getFunctionManager()
        af = program.getAddressFactory()
        listing = program.getListing()
        def addr(v): return af.getDefaultAddressSpace().getAddress(v)
        for t in targets:
            print(f"\n##### refs TO 0x{t:08x} #####")
            refs = rm.getReferencesTo(addr(t))
            rows = []
            for r in refs:
                fa = r.getFromAddress()
                f = fm.getFunctionContaining(fa)
                ins = listing.getInstructionAt(fa)
                rows.append((str(fa), f.getName() if f else "?", r.getReferenceType().getName(),
                             ins.toString() if ins else "(data)"))
            for fa, fn, rt, txt in sorted(rows):
                print(f"  {fa}  {fn:<28} {rt:<14} {txt}")
            if not rows:
                print("  (none)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
