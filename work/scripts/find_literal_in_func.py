"""Find all instructions in a given function that use a specific immediate value.

Quick disposable scanner for hunting specific literals (e.g., 300 = 0x12C in
SetupWin_do_menu_rightside). Run via run-find-literal.bat.
"""

import sys

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# (function_entry_va, target_literal, label)
SEARCHES = [
    (0x004ADB70, 300, "SetupWin_do_menu_rightside: menu-item width literal"),
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
        fm = program.getFunctionManager()
        af = program.getAddressFactory()
        listing = program.getListing()

        from ghidra.program.model.scalar import Scalar

        for fn_va, lit, label in SEARCHES:
            func = fm.getFunctionAt(af.getDefaultAddressSpace().getAddress(fn_va))
            if func is None:
                print(f"NO FUNCTION at 0x{fn_va:08x} ({label})")
                continue
            print(f"\n##### {label}")
            print(f"##### {func.getName()} @ 0x{fn_va:08x}, searching for immediate {lit} (0x{lit:x})\n")

            body = func.getBody()
            it = listing.getInstructions(body, True)
            instrs = []
            while it.hasNext():
                instrs.append(it.next())

            hits = []
            for idx, instr in enumerate(instrs):
                for op_idx in range(instr.getNumOperands()):
                    for obj in instr.getOpObjects(op_idx):
                        if isinstance(obj, Scalar) and obj.getUnsignedValue() == lit:
                            hits.append(idx)
                            break

            if not hits:
                print("  (no hits)")
                continue

            print(f"  {len(hits)} hit(s):")
            for idx in hits:
                instr = instrs[idx]
                a = int(str(instr.getAddress()), 16)
                bytes_str = " ".join(f"{b & 0xff:02X}" for b in instr.getBytes())
                # 2 lines context before/after
                print()
                for c in range(max(0, idx - 2), idx):
                    ci = instrs[c]
                    ca = int(str(ci.getAddress()), 16)
                    cb = " ".join(f"{b & 0xff:02X}" for b in ci.getBytes())
                    print(f"      0x{ca:08x}  {cb:<28}  {ci}")
                print(f"  >>> 0x{a:08x}  {bytes_str:<28}  {instr}")
                for c in range(idx + 1, min(len(instrs), idx + 3)):
                    ci = instrs[c]
                    ca = int(str(ci.getAddress()), 16)
                    cb = " ".join(f"{b & 0xff:02X}" for b in ci.getBytes())
                    print(f"      0x{ca:08x}  {cb:<28}  {ci}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
