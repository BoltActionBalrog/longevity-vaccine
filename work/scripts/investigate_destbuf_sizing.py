"""Map where SetupWin's destination Buffer at +0x444 gets its dimensions.

The menu_strip_scaling crash showed: our thunk stretches the strip blit from
354x75 to 995x210, but the destination Buffer is sized only 354 wide, so the
GDI StretchBlt writes past the allocated DIB and crashes.

Goal of this script: enumerate every call inside SetupWin_do_menu_rightside
to:
  - Buffer_init     (0x5D7670)   — (Buffer* this, int W, int H, int a4, ddraw)
  - Buffer_resize   (0x5D79C0)   — (Buffer* this, int W, int H)
  - GraphicWin_init (0x5D4EF0)   — (GraphicWin* this, int a2, int a3, int W, int H, ...)
  - FUN_00629e50    (the FLC loader — used as a landmark)

For each call site, dump the preceding 16 instructions so we can see which
register/stack location holds 'this' and how W/H are computed. The goal is
to identify: (1) which call sites the dest Buffer at SetupWin+0x444 gets
its initial size from, (2) what literal/expression that size is, and
(3) whether we can patch it.

Also dumps the immediately-preceding instructions of every direct CALL
inside SetupWin_do_menu_rightside, tagged with the callee name when known.

Run via D:\\SmacxUi\\work\\run-investigate-destbuf.bat.
"""

import sys

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

SETUP_WIN_DO_MENU_RIGHTSIDE_VA = 0x004ADB70

CALLEES_OF_INTEREST = {
    0x005D7670: ("Buffer_init",      "(this, width, height, a4, ddraw)"),
    0x005D79C0: ("Buffer_resize",    "(this, width, height)"),
    0x005D4EF0: ("GraphicWin_init",  "(this, a2, a3, width, height, a6, a7, a8, a9, a10)"),
    0x00629E50: ("FUN_00629e50",     "(?, ?, filename, buffer_ptr)  -- FLC loader"),
    0x005DFF00: ("Buffer_copy_4",    "(this_src, dest, srcX, srcY, dstX, dstY, srcW, srcH)"),
    0x005D9610: ("Buffer_copy_3",    "(this_src, dest, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH)"),
    0x005D7470: ("FUN_005d7470",     "(unknown - called near top of function)"),
    0x00402970: ("FUN_00402970",     "(possibly memset)"),
}

WALK_BACK = 20


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

        def addr(value):
            return af.getDefaultAddressSpace().getAddress(value)

        def fmt_bytes(b):
            return " ".join(f"{x & 0xFF:02X}" for x in b)

        entry = addr(SETUP_WIN_DO_MENU_RIGHTSIDE_VA)
        func = fm.getFunctionAt(entry)
        if func is None:
            print("no function at SetupWin_do_menu_rightside entry")
            return 1
        body = func.getBody()

        print(f"===== SetupWin_do_menu_rightside @ 0x{SETUP_WIN_DO_MENU_RIGHTSIDE_VA:08x} =====")
        print(f"  body : {body.getMinAddress()} - {body.getMaxAddress()}")
        print(f"  total bytes: {body.getNumAddresses()}")
        print()

        # Walk every instruction; for each CALL whose target is in our list,
        # dump a window of preceding context.
        it = listing.getInstructions(body, True)
        all_instrs = []
        while it.hasNext():
            all_instrs.append(it.next())

        # Find CALL instructions
        for idx, ins in enumerate(all_instrs):
            mnem = ins.getMnemonicString().upper()
            if not mnem.startswith("CALL"):
                continue
            # Get call target
            refs = list(ref_mgr.getReferencesFrom(ins.getAddress()))
            call_target_va = None
            for r in refs:
                if r.getReferenceType().isCall():
                    call_target_va = r.getToAddress().getOffset()
                    break
            if call_target_va is None:
                continue
            if call_target_va not in CALLEES_OF_INTEREST:
                continue

            callee_name, sig = CALLEES_OF_INTEREST[call_target_va]
            site_va = ins.getAddress().getOffset()
            print(f"--- CALL to {callee_name} @ 0x{call_target_va:08x}  from 0x{site_va:08x} ---")
            print(f"    sig: {sig}")

            start = max(0, idx - WALK_BACK)
            for j in range(start, idx + 1):
                cur = all_instrs[j]
                ba = cur.getAddress().getOffset()
                bb = fmt_bytes(cur.getBytes())
                marker = "==>" if j == idx else "   "
                print(f"    {marker} 0x{ba:08x}  {bb:<28}  {cur}")
            print()

        # --- Also dump every instruction that READS or WRITES [ESI + 0x1198]
        #     or [ESI + 0x119C] within this function ---
        print("=" * 100)
        print("Instructions referencing [ESI + 0x1198] (strip width) or [ESI + 0x119C] (strip height):")
        print("=" * 100)
        from ghidra.program.model.scalar import Scalar
        from ghidra.program.model.lang import Register

        for ins in all_instrs:
            for opi in range(ins.getNumOperands()):
                objs = ins.getOpObjects(opi)
                has_esi = any(isinstance(o, Register) and o.getName().upper() == "ESI" for o in objs)
                disp_match = None
                for o in objs:
                    if isinstance(o, Scalar):
                        v = o.getUnsignedValue()
                        if v in (0x1198, 0x119C):
                            disp_match = v
                            break
                if has_esi and disp_match is not None:
                    ba = ins.getAddress().getOffset()
                    bb = fmt_bytes(ins.getBytes())
                    print(f"    0x{ba:08x}  {bb:<28}  {ins}    [+0x{disp_match:x}]")
                    break

        print()
        print("=" * 100)
        print("Instructions referencing [ESI + 0x444] (display buffer):")
        print("=" * 100)
        for ins in all_instrs:
            for opi in range(ins.getNumOperands()):
                objs = ins.getOpObjects(opi)
                has_esi = any(isinstance(o, Register) and o.getName().upper() == "ESI" for o in objs)
                disp_match = None
                for o in objs:
                    if isinstance(o, Scalar):
                        v = o.getUnsignedValue()
                        if v == 0x444:
                            disp_match = v
                            break
                if has_esi and disp_match is not None:
                    ba = ins.getAddress().getOffset()
                    bb = fmt_bytes(ins.getBytes())
                    print(f"    0x{ba:08x}  {bb:<28}  {ins}")
                    break

    return 0


if __name__ == "__main__":
    sys.exit(main())
