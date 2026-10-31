"""Map custom_planet's background-image (MOON*.PCX) draw mechanism.

Dumps:
  1. Full decompiled C of custom_planet (0x58C2A0).
  2. Raw instruction listing of the moon-image draw block (0x58C440-0x58C560),
     with each CALL target resolved to a function name.
  3. The callees of custom_planet (one hop) so we can spot the blit primitive.

Run via run-dump-custom-planet.bat.
"""

import sys
import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

CUSTOM_PLANET = 0x0058C2A0
BLOCK_LO = 0x0058C440
BLOCK_HI = 0x0058C560


def main() -> int:
    with pyghidra.open_program(
        binary_path=None,
        project_location=PROJECT_LOCATION,
        project_name=PROJECT_NAME,
        program_name=PROGRAM_NAME,
        analyze=False,
        nested_project_location=False,
    ) as api:
        program = api.getCurrentProgram()
        fm = program.getFunctionManager()
        af = program.getAddressFactory()
        listing = program.getListing()
        ref_mgr = program.getReferenceManager()

        from ghidra.app.decompiler import DecompInterface
        from ghidra.util.task import ConsoleTaskMonitor

        monitor = ConsoleTaskMonitor()
        decomp = DecompInterface()
        decomp.openProgram(program)

        def addr(v):
            return af.getDefaultAddressSpace().getAddress(v)

        func = fm.getFunctionAt(addr(CUSTOM_PLANET))
        print(f"custom_planet @ 0x{CUSTOM_PLANET:08x}: {func.getName() if func else 'NO FUNC'}")
        if func:
            print(f"  body {func.getBody().getMinAddress()} - {func.getBody().getMaxAddress()}")

        # ----- callees (one hop) -----
        print("\n===== callees (one hop) =====")
        from collections import defaultdict
        callees = defaultdict(int)
        it = func.getBody().getAddresses(True)
        while it.hasNext():
            a = it.next()
            for r in ref_mgr.getReferencesFrom(a):
                if r.getReferenceType().isCall():
                    t = fm.getFunctionAt(r.getToAddress())
                    if t:
                        callees[t.getName()] += 1
        for cname, n in sorted(callees.items(), key=lambda x: -x[1]):
            print(f"  {n:>3}x  {cname}")

        # ----- raw listing of the moon-draw block -----
        print(f"\n===== listing 0x{BLOCK_LO:08x} - 0x{BLOCK_HI:08x} =====")
        a = addr(BLOCK_LO)
        end = addr(BLOCK_HI)
        while a is not None and a.compareTo(end) <= 0:
            ins = listing.getInstructionAt(a)
            if ins is None:
                a = a.next()
                continue
            # resolve call targets
            note = ""
            for r in ref_mgr.getReferencesFrom(a):
                if r.getReferenceType().isCall():
                    t = fm.getFunctionAt(r.getToAddress())
                    note = f"   -> {t.getName()}" if t else f"   -> {r.getToAddress()}"
                elif r.getReferenceType().isData():
                    # data ref (e.g. string pointer) — show target
                    d = listing.getDataAt(r.getToAddress())
                    if d is not None and d.hasStringValue():
                        note = f"   ; \"{d.getValue()}\""
            print(f"  {a}  {ins.toString()}{note}")
            a = ins.getMaxAddress().next()

        # ----- full decompile -----
        print("\n===== decompiled custom_planet =====")
        res = decomp.decompileFunction(func, 120, monitor)
        if res.decompileCompleted():
            for line in res.getDecompiledFunction().getC().rstrip().splitlines():
                print(f"  {line}")
        else:
            print(f"  DECOMP FAILED: {res.getErrorMessage()}")
        decomp.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
