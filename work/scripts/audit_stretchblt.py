"""Find and decompile the StretchBlt and SetStretchBltMode call sites.

Goal: decide whether the engine has a reusable stretched-blit code path we
can call into for the menu-strip scaling patch (saves writing scale math
from scratch), or whether the StretchBlt sites are doing something
unrelated (e.g., FMV scaling) so we write our own.

For each GDI function we care about:
  1. Locate the import thunk in the IAT (an external function/symbol).
  2. Find every call site referencing that thunk.
  3. For each call site, identify the containing function, the args being
     passed (walk back from the call collecting PUSH immediates and the
     register/memory state setup), and decompile the function.

Run via D:\\SmacxUi\\work\\run-audit-stretchblt.bat.
"""

import sys
from collections import defaultdict

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

GDI_FUNCS = ["StretchBlt", "SetStretchBltMode"]


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
        ref_mgr = program.getReferenceManager()
        af = program.getAddressFactory()
        listing = program.getListing()
        symtab = program.getSymbolTable()

        from ghidra.app.decompiler import DecompInterface
        from ghidra.util.task import ConsoleTaskMonitor
        from ghidra.program.model.scalar import Scalar
        from ghidra.program.model.symbol import SourceType

        monitor = ConsoleTaskMonitor()
        decomp = DecompInterface()
        decomp.openProgram(program)

        # We want every function/symbol matching the target names. There can be
        # both an import-thunk function AND an external symbol; both work as
        # xref targets.
        targets_by_name = defaultdict(list)  # name -> list of addresses
        for name in GDI_FUNCS:
            syms = symtab.getSymbols(name)
            for s in syms:
                targets_by_name[name].append(s.getAddress())

        for name in GDI_FUNCS:
            addrs = targets_by_name[name]
            print(f"{name}: {len(addrs)} symbol(s)")
            for a in addrs:
                print(f"  - {a}")

        # Functions we want to fully decompile (deduplicated).
        funcs_to_decomp = set()  # function entry offsets

        # ---- 2. Enumerate calls to each GDI function ----
        for name in GDI_FUNCS:
            print()
            print("=" * 100)
            print(f"call sites of {name}")
            print("=" * 100)
            sites = []
            for sym_addr in targets_by_name[name]:
                for r in ref_mgr.getReferencesTo(sym_addr):
                    if not r.getReferenceType().isCall():
                        continue
                    sites.append(r.getFromAddress())

            if not sites:
                print(f"  (no call sites found for {name})")
                continue

            print(f"  {len(sites)} call site(s)")
            for site_addr in sites:
                caller = fm.getFunctionContaining(site_addr)
                cname = caller.getName() if caller else "<no-function>"
                cva = caller.getEntryPoint().getOffset() if caller else 0
                if caller is not None:
                    funcs_to_decomp.add(cva)
                print()
                print(f"  call @ {site_addr}  in  {cname} @ 0x{cva:08x}")

                # Walk back ~30 instructions and dump them so we can read the
                # arg setup directly.
                instr_at = listing.getInstructionAt(site_addr)
                if instr_at is None:
                    print("    (no instruction at site)")
                    continue
                window = []
                cur = instr_at
                steps = 0
                while cur is not None and steps < 30:
                    if caller is not None and not caller.getBody().contains(cur.getAddress()):
                        break
                    window.append(cur)
                    cur = cur.getPrevious()
                    steps += 1
                window.reverse()
                for ins in window:
                    ba = int(str(ins.getAddress()), 16)
                    bb = " ".join(f"{b & 0xff:02X}" for b in ins.getBytes())
                    marker = "==>" if ins.getAddress() == site_addr else "   "
                    print(f"    {marker} 0x{ba:08x}  {bb:<28}  {ins}")

        # ---- 3. Decompile each unique caller ----
        print()
        print("=" * 100)
        print("decompiled callers")
        print("=" * 100)
        for fva in sorted(funcs_to_decomp):
            f = fm.getFunctionAt(af.getDefaultAddressSpace().getAddress(fva))
            if f is None:
                continue
            print()
            print(f"--- {f.getName()} @ 0x{fva:08x} ---")
            res = decomp.decompileFunction(f, 120, monitor)
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
