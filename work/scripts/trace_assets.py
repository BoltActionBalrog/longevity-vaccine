"""Trace SMAC UI asset strings back to their containing functions, then dump
the loader function(s) and their callers.

Run via D:\\SmacxUi\\work\\run-trace-assets.bat.
"""

import sys
from collections import defaultdict

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# (string_address_hex, expected_value) — pulled from the stats run.
ASSET_STRINGS = [
    (0x00685170, "iface.pcx"),
    (0x00682730, "menu.pcx"),
    (0x00687274, "report.pcx"),
    (0x006832b0, "credits.pcx"),
    (0x00685380, "credits.pcx"),
    (0x00685084, "ICONS.PCX"),
    (0x00685064, "NEWICONS.PCX"),
    (0x00685128, "NEWICONS.PCX"),
    (0x0068458c, "hoficons.pcx"),
    (0x006863e4, "monicons.pcx"),
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
        listing = program.getListing()
        af = program.getAddressFactory()

        from ghidra.app.decompiler import DecompInterface
        from ghidra.util.task import ConsoleTaskMonitor

        monitor = ConsoleTaskMonitor()
        decomp = DecompInterface()
        decomp.openProgram(program)

        def addr(value: int):
            return af.getDefaultAddressSpace().getAddress(value)

        # ----- pass 1: xref each asset string, find containing function -----
        print()
        print("===== pass 1: asset string xrefs =====")
        loaders = defaultdict(list)  # function_entry_int -> [(str_addr, str_val, xref_addr)]

        for str_addr_int, expected in ASSET_STRINGS:
            str_addr = addr(str_addr_int)
            data = listing.getDataAt(str_addr)
            actual = str(data.getValue()) if data else "<no data>"
            mark = "OK" if actual.lower() == expected.lower() else "??"
            print(f"\n  string {str_addr}  {mark}  {actual!r}")

            refs = list(ref_mgr.getReferencesTo(str_addr))
            if not refs:
                print(f"    (no xrefs)")
                continue

            for ref in refs:
                from_addr = ref.getFromAddress()
                func = fm.getFunctionContaining(from_addr)
                if func is None:
                    print(f"    xref from {from_addr}  (NOT inside a function)")
                    continue
                fname = func.getName()
                fentry = func.getEntryPoint()
                print(f"    xref from {from_addr}  in  {fname} @ {fentry}")
                loaders[int(str(fentry), 16)].append(
                    (str_addr_int, expected, int(str(from_addr), 16))
                )

        # ----- pass 2: group strings by containing function -----
        print()
        print()
        print("===== pass 2: strings grouped by containing function =====")
        for fentry_int, items in sorted(loaders.items()):
            func = fm.getFunctionAt(addr(fentry_int))
            name = func.getName() if func else "<unknown>"
            print(f"\n  {name} @ 0x{fentry_int:08x}  ({len(items)} string ref(s))")
            for str_addr_int, val, xref_addr_int in items:
                print(f"    0x{xref_addr_int:08x} -> {val!r} @ 0x{str_addr_int:08x}")

        # ----- pass 3: decompile each loader + list callers -----
        print()
        print()
        print("===== pass 3: decompile each loader + callers =====")
        for fentry_int in sorted(loaders):
            func = fm.getFunctionAt(addr(fentry_int))
            if func is None:
                continue
            print()
            print(f"--- {func.getName()} @ 0x{fentry_int:08x} ---")
            body = func.getBody()
            print(f"  body          : {body.getMinAddress()} - {body.getMaxAddress()}  "
                  f"({body.getNumAddresses()} bytes)")
            print(f"  signature     : {func.getSignature(False).getPrototypeString(True)}")
            print(f"  stack frame   : {func.getStackFrame().getFrameSize()} bytes")

            # Callers (one-hop reverse xrefs)
            callers = set()
            for ref in ref_mgr.getReferencesTo(func.getEntryPoint()):
                from_addr = ref.getFromAddress()
                calling_func = fm.getFunctionContaining(from_addr)
                if calling_func is not None:
                    callers.add((str(calling_func.getEntryPoint()), calling_func.getName(),
                                 str(from_addr)))
            print(f"  callers       : {len(callers)}")
            for cf_entry, cf_name, cf_site in sorted(callers):
                print(f"    {cf_name} @ {cf_entry}  (call site: {cf_site})")

            # Decompile
            res = decomp.decompileFunction(func, 60, monitor)
            if not res.decompileCompleted():
                print(f"  decomp        : FAILED — {res.getErrorMessage()}")
                continue
            c_code = res.getDecompiledFunction().getC()
            print()
            print("  -- decompiled C --")
            for line in c_code.rstrip().splitlines():
                print(f"  {line}")

        decomp.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
