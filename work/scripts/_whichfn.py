"""Identify the function containing a VA, list its callers, and decompile it.

Usage: _whichfn.py 0x5e56ef [0x...]      (prints to stdout)

Needs the Ghidra project that work\\import-terranx.bat creates under work\\ghidra-projects,
pyghidra (version matching the Ghidra release), and GHIDRA_INSTALL_DIR / JAVA_HOME set the way
work\\run-decompile.bat sets them: copy that launcher to run this script. Close the project in
the Ghidra GUI first.
"""
import sys
import pyghidra

pyghidra.start()
PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

TARGETS = [int(x, 16) for x in sys.argv[1:]] or [0x5e56ef]

with pyghidra.open_program(
    binary_path=None, project_location=PROJECT_LOCATION,
    project_name=PROJECT_NAME, program_name=PROGRAM_NAME,
    analyze=False, nested_project_location=False,
) as api:
    program = api.getCurrentProgram()
    fm = program.getFunctionManager()
    af = program.getAddressFactory()
    ref = program.getReferenceManager()

    def addr(v):
        return af.getDefaultAddressSpace().getAddress(v)

    from ghidra.app.decompiler import DecompInterface
    dec = DecompInterface()
    dec.openProgram(program)

    seen = set()
    for t in TARGETS:
        fn = fm.getFunctionContaining(addr(t))
        if fn is None:
            print(f"0x{t:08x}: NO function")
            continue
        ent = fn.getEntryPoint()
        key = ent.getOffset()
        print(f"\n##### 0x{t:08x} is in {fn.getName()} @ {ent} #####")
        # callers
        callers = set()
        for r in ref.getReferencesTo(ent):
            cf = fm.getFunctionContaining(r.getFromAddress())
            callers.add((str(r.getFromAddress()), cf.getName() if cf else "?"))
        print("  callers:")
        for a, n in sorted(callers):
            print(f"    {a}  {n}")
        if key in seen:
            continue
        seen.add(key)
        res = dec.decompileFunction(fn, 60, None)
        if res and res.decompileCompleted():
            print("  ---- decompile ----")
            print(res.getDecompiledFunction().getC())
