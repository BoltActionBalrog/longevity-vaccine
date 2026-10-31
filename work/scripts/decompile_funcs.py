"""Generic decompiler: decompile arbitrary functions by address.

Usage (via run-decompile.bat):
    run-decompile.bat 0x589d30 0x4adb70 0x5fa8a0 ...

For each address: prints one-hop callers + callees, then full decompiled C.
Read-only (analyze=False); safe while the .gpr is otherwise idle.
"""

import sys
from collections import defaultdict

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"


def main() -> int:
    targets = []
    for a in sys.argv[1:]:
        a = a.strip()
        if not a:
            continue
        targets.append(int(a, 16) if a.lower().startswith("0x") else int(a, 16))
    if not targets:
        print("no addresses given")
        return 1

    with pyghidra.open_program(
        binary_path=None,
        project_location=PROJECT_LOCATION,
        project_name=PROJECT_NAME,
        program_name=PROGRAM_NAME,
        analyze=False,
        nested_project_location=False,
    ) as api:
        program = api.getCurrentProgram()
        ref_mgr = program.getReferenceManager()
        fm = program.getFunctionManager()
        af = program.getAddressFactory()

        from ghidra.app.decompiler import DecompInterface
        from ghidra.util.task import ConsoleTaskMonitor

        monitor = ConsoleTaskMonitor()
        decomp = DecompInterface()
        decomp.openProgram(program)

        def addr(value):
            return af.getDefaultAddressSpace().getAddress(value)

        for addr_int in targets:
            entry = addr(addr_int)
            func = fm.getFunctionAt(entry)
            if func is None:
                # maybe address is inside a function, not its entry
                func = fm.getFunctionContaining(entry)
            if func is None:
                print(f"\n##### NO FUNCTION at 0x{addr_int:08x} #####")
                continue
            print(f"\n##### {func.getName()} @ {func.getEntryPoint()} "
                  f"(asked 0x{addr_int:08x}) #####")
            print(f"  body  : {func.getBody().getMinAddress()} - {func.getBody().getMaxAddress()} "
                  f"({func.getBody().getNumAddresses()} bytes)")

            callers = set()
            for ref in ref_mgr.getReferencesTo(func.getEntryPoint()):
                cf = fm.getFunctionContaining(ref.getFromAddress())
                if cf is None:
                    continue
                callers.add((cf.getName(), str(ref.getFromAddress())))
            if callers:
                print(f"  callers ({len(callers)}):")
                for cf_name, cf_site in sorted(callers):
                    print(f"    {cf_name:<38} call site: {cf_site}")

            callees = defaultdict(int)
            it = func.getBody().getAddresses(True)
            while it.hasNext():
                a = it.next()
                for r in ref_mgr.getReferencesFrom(a):
                    if not r.getReferenceType().isCall():
                        continue
                    t = fm.getFunctionAt(r.getToAddress())
                    if t is None:
                        continue
                    callees[t.getName()] += 1
            if callees:
                print(f"  callees ({len(callees)} unique): " +
                      ", ".join(f"{c}x {n}" for n, c in sorted(callees.items(), key=lambda x: -x[1])))

            res = decomp.decompileFunction(func, 120, monitor)
            print("  --- C ---")
            if not res.decompileCompleted():
                print(f"  DECOMP FAILED: {res.getErrorMessage()}")
                continue
            c = res.getDecompiledFunction().getC()
            for line in c.rstrip().splitlines():
                print(f"  {line}")

        decomp.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
