"""Pre-implementation preconditions for the menu-strip scaling patch.

Validates three load-bearing facts before any thunk bytes get committed:

  1. Buffer_copy_4 and Buffer_copy_3 use callee stack-cleanup.
     - Looks at the final RET instruction of each function.
     - Expected: `RET 0x1C` for Buffer_copy_4 (7 dword args),
                 `RET 0x24` for Buffer_copy_3 (9 dword args).
     - Bare `RET` (C3) would mean caller-cleanup; the thunk design flips.

  2. ECX at each strip-blit CALL site holds the source Buffer pointer
     (not the SetupWin `this`).
     - For each xref to Buffer_copy_4, dumps the 12 instructions immediately
       before the CALL with raw bytes + disasm.
     - We can read off the last write to ECX and identify what's in it.

  3. Per-site arg layout matches the expected
     (dest, srcX, srcY, dstX, dstY, srcW, srcH) shape.
     - Same disasm dump shows the PUSH sequence before each CALL.
     - Sites that pass non-standard args (e.g., the close-animation loop
       that passes a scroll offset) need separate thunk treatment.

Output goes to find_call_sites.out. The plan only proceeds after a human
reads this and confirms the three preconditions hold.

Run via D:\\SmacxUi\\work\\run-find-call-sites.bat.
"""

import sys
from collections import defaultdict

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# Functions whose call-site convention we need to verify.
TARGETS = [
    (0x005DFF00, "Buffer_copy_4", 7),       # __thiscall, expect RET 0x1C
    (0x005D9610, "Buffer_copy_3", 9),       # __thiscall, expect RET 0x24
]

# Functions that contain strip-blit calls — we want to see THEIR CALL
# sites in particular, so the per-site dumps go to the top of output.
PRIORITY_CALLERS = {
    0x004AE4D0: "SetupWin_draw_item",
    0x004ADB70: "SetupWin_do_menu_rightside",
}

# How many instructions to dump back from each CALL site.
PREV_INSTRS = 12


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

        def addr(value):
            return af.getDefaultAddressSpace().getAddress(value)

        def fmt_bytes(b):
            return " ".join(f"{x & 0xFF:02X}" for x in b)

        # =====================================================================
        # Precondition 1: final RET of each target function
        # =====================================================================
        for fn_va, name, nargs in TARGETS:
            print()
            print("=" * 100)
            print(f"PRECONDITION 1 — final RET of {name} @ 0x{fn_va:08x}")
            print("=" * 100)

            func = fm.getFunctionAt(addr(fn_va))
            if func is None:
                print(f"  NO FUNCTION at 0x{fn_va:08x}")
                continue

            body = func.getBody()
            # Walk all instructions in this function, find the last RET/RETN.
            it = listing.getInstructions(body, True)
            instrs = []
            while it.hasNext():
                instrs.append(it.next())

            # Find every RET-family instruction.
            rets = []
            for ins in instrs:
                mnem = ins.getMnemonicString().upper()
                if mnem.startswith("RET"):
                    rets.append(ins)

            expected_imm = nargs * 4
            print(f"  function body : {body.getMinAddress()} - {body.getMaxAddress()}")
            print(f"  total instr   : {len(instrs)}")
            print(f"  RET-family    : {len(rets)}")
            print(f"  expected      : RET 0x{expected_imm:02X} for callee-cleanup of "
                  f"{nargs} dwords")
            print(f"                  (or bare RET = caller-cleanup)")

            if not rets:
                print("  WARN: no RET found — control falls off end?")
                continue

            for r in rets:
                a = int(str(r.getAddress()), 16)
                rb = fmt_bytes(r.getBytes())
                # Operand 0 may be a scalar if RET imm16
                pretty = str(r)
                marker = ""
                if rb.startswith("C2"):  # RET imm16
                    # Bytes 1-2 are the imm16
                    imm = r.getBytes()[1] & 0xFF | ((r.getBytes()[2] & 0xFF) << 8)
                    if imm == expected_imm:
                        marker = "  <-- MATCH (callee-cleanup confirmed)"
                    else:
                        marker = f"  <-- MISMATCH (got 0x{imm:02X}, expected 0x{expected_imm:02X})"
                elif rb.startswith("C3"):  # bare RET
                    marker = "  <-- BARE RET (caller-cleanup — thunk design flips)"
                print(f"    0x{a:08x}  {rb:<10}  {pretty}{marker}")

        # =====================================================================
        # Precondition 2 + 3: per-CALL-site dump for each target
        # =====================================================================
        for fn_va, name, nargs in TARGETS:
            print()
            print("=" * 100)
            print(f"PRECONDITIONS 2+3 — call sites of {name}")
            print("=" * 100)

            sites = []
            for r in ref_mgr.getReferencesTo(addr(fn_va)):
                if not r.getReferenceType().isCall():
                    continue
                site = r.getFromAddress()
                caller = fm.getFunctionContaining(site)
                sites.append((site, caller))

            print(f"  {len(sites)} call site(s)")

            # Sort: priority callers first, then by site address.
            def keyfn(t):
                site, caller = t
                cva = caller.getEntryPoint().getOffset() if caller else 0
                priority = 0 if cva in PRIORITY_CALLERS else 1
                return (priority, cva, str(site))

            sites.sort(key=keyfn)

            for site, caller in sites:
                cname = caller.getName() if caller else "<no-function>"
                cva = caller.getEntryPoint().getOffset() if caller else 0
                pri = "  ** PRIORITY **" if cva in PRIORITY_CALLERS else ""

                print()
                print(f"  ----- call @ {site}  in  {cname} @ 0x{cva:08x}{pri} -----")

                instr_at = listing.getInstructionAt(site)
                if instr_at is None:
                    print("    (no instruction at site)")
                    continue

                # Walk back PREV_INSTRS instructions within the caller's body.
                body = caller.getBody() if caller else None
                window = [instr_at]
                cur = instr_at.getPrevious()
                steps = 0
                while cur is not None and steps < PREV_INSTRS:
                    if body is not None and not body.contains(cur.getAddress()):
                        break
                    window.append(cur)
                    cur = cur.getPrevious()
                    steps += 1
                window.reverse()

                for ins in window:
                    a = int(str(ins.getAddress()), 16)
                    b = fmt_bytes(ins.getBytes())
                    marker = "==>" if ins.getAddress() == site else "   "
                    print(f"    {marker} 0x{a:08x}  {b:<28}  {ins}")

        print()
        print("=" * 100)
        print("DONE.  Review the output before proceeding to thunk implementation.")
        print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
