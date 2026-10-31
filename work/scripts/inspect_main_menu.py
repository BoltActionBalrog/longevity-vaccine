"""Inspect the main-menu code path: visual setup, click handling, hit-testing.

Decompiles a hand-picked set of main-menu functions and dumps:
  - one-hop callers and callees
  - full decompiled C
  - any references to the global cursor-position pair (if we can find it)

The goal is to answer: do main-menu click hit-zones come from parametric
math on ScreenWidth (good — auto-scales) or hardcoded literal rectangles
(bad — separate patch sites)?

Run via D:\\SmacxUi\\work\\run-inspect-main-menu.bat.
"""

import sys
from collections import defaultdict

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# Candidate main-menu functions, ordered by likely interest.
TARGETS = [
    (0x004ADB70, "SetupWin_do_menu_rightside", "the real menu loop — wrappers all delegate here"),
    (0x005FA860, "Spot_ctor",                  "clickable-region constructor"),
    (0x005FA8A0, "Spot_init",                  "clickable-region init — rect populated here?"),
    (0x005FAC00, "Spot_get_rect",              "returns the hit-test rect for an item"),
    (0x005EC8A0, "Win_get_mouse_pos",          "cursor position getter — used by hit-test"),
]


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

        # ----- pass 1: call-graph context -----
        print("===== pass 1: call graph (one hop) =====")
        for addr_int, expected_name, why in TARGETS:
            entry = addr(addr_int)
            func = fm.getFunctionAt(entry)
            if func is None:
                print(f"\n  NO FUNCTION at 0x{addr_int:08x} ({expected_name})")
                continue
            print(f"\n  {func.getName()} @ 0x{addr_int:08x}  — {why}")
            print(f"    body          : {func.getBody().getMinAddress()} - {func.getBody().getMaxAddress()}")
            print(f"    body bytes    : {func.getBody().getNumAddresses()}")

            # Callers
            callers = set()
            for ref in ref_mgr.getReferencesTo(entry):
                cf = fm.getFunctionContaining(ref.getFromAddress())
                if cf is None:
                    continue
                callers.add((str(cf.getEntryPoint()), cf.getName(), str(ref.getFromAddress())))
            print(f"    callers ({len(callers)}):")
            for cf_entry, cf_name, cf_site in sorted(callers):
                print(f"      {cf_name:<40} @ {cf_entry}  call site: {cf_site}")

            # Callees (one hop)
            callees = defaultdict(int)  # name -> count
            body = func.getBody()
            it = body.getAddresses(True)
            while it.hasNext():
                a = it.next()
                refs_from = ref_mgr.getReferencesFrom(a)
                for r in refs_from:
                    rt = r.getReferenceType()
                    if not rt.isCall():
                        continue
                    target = fm.getFunctionAt(r.getToAddress())
                    if target is None:
                        continue
                    callees[target.getName()] += 1
            print(f"    callees ({len(callees)} unique):")
            for cname, count in sorted(callees.items(), key=lambda x: -x[1])[:25]:
                print(f"      {count:>3}x  {cname}")
            if len(callees) > 25:
                print(f"      ... and {len(callees) - 25} more")

        # ----- pass 2: full decompilation -----
        print()
        print()
        print("===== pass 2: full decompiled C =====")
        for addr_int, expected_name, why in TARGETS:
            entry = addr(addr_int)
            func = fm.getFunctionAt(entry)
            if func is None:
                continue
            print()
            print(f"--- {func.getName()} @ 0x{addr_int:08x} ---")
            res = decomp.decompileFunction(func, 90, monitor)
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
