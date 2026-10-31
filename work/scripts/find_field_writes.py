"""Find writes to specific instance-field offsets within a function.

For SetupWin: the visible-strip width and height come from [this+0x1198] and
[this+0x119c] (see Buffer_copy_4 call in SetupWin_draw_item @ 0x4AE5B0-ish).
We want the literal values written into those fields — that's the visual
sprite dimension we need to scale in lockstep with the logical width literal
at 0x4ADFA5.

This script:
  1. Decompiles SetupWin_do_menu_rightside (0x4ADB70) — full C source.
  2. Disassembles the same function, hunting for any instruction whose
     destination is a memory operand with displacement in the target set
     {0x1198, 0x119c}. Records the source operand (immediate or register).
  3. For matches whose source is an immediate, print it. For register
     sources, walk backward up to ~6 instructions trying to find what the
     register was last loaded with.
  4. Also handles writes outside SetupWin_do_menu_rightside — scan all
     functions whose body touches these offsets.

Run via D:\\SmacxUi\\work\\run-find-field-writes.bat.
"""

import sys

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

SETUP_WIN_DO_MENU_RIGHTSIDE_VA = 0x004ADB70
TARGET_OFFSETS = {0x1198: "strip_width", 0x119C: "strip_height"}


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

        from ghidra.app.decompiler import DecompInterface
        from ghidra.util.task import ConsoleTaskMonitor
        from ghidra.program.model.scalar import Scalar
        from ghidra.program.model.lang import Register

        def addr(value):
            return af.getDefaultAddressSpace().getAddress(value)

        monitor = ConsoleTaskMonitor()
        decomp = DecompInterface()
        decomp.openProgram(program)

        # -------- 1. Decompile the target function --------
        entry = addr(SETUP_WIN_DO_MENU_RIGHTSIDE_VA)
        func = fm.getFunctionAt(entry)
        if func is None:
            print(f"NO FUNCTION at 0x{SETUP_WIN_DO_MENU_RIGHTSIDE_VA:08x}")
            return 1

        print(f"===== {func.getName()} @ 0x{SETUP_WIN_DO_MENU_RIGHTSIDE_VA:08x} =====")
        print(f"  body: {func.getBody().getMinAddress()} - {func.getBody().getMaxAddress()}")
        print(f"  bytes: {func.getBody().getNumAddresses()}")

        # -------- 2. Find writes anywhere in the binary --------
        # Search all functions whose body contains an instruction with a memory
        # operand whose displacement matches one of TARGET_OFFSETS.
        print()
        print("===== scanning ALL functions for writes to target offsets =====")

        funcs = list(fm.getFunctions(True))
        print(f"  scanning {len(funcs)} functions")

        matches_by_fn = {}  # fn_va -> list of (ins, off, src_imm or None, raw_src)
        for f in funcs:
            body = f.getBody()
            it = listing.getInstructions(body, True)
            while it.hasNext():
                ins = it.next()
                mnem = ins.getMnemonicString().upper()
                # We care about writes — MOV is by far the dominant store form here.
                # Don't bother with PUSH/POP, etc.
                if mnem != "MOV":
                    continue
                if ins.getNumOperands() != 2:
                    continue
                # Operand 0 is destination.
                dst_objs = ins.getOpObjects(0)
                # Destination must be a memory reference with a displacement
                # equal to one of our targets.
                # The objects list for [REG+disp] is typically [Register, Scalar].
                # For [REG] alone it's [Register] with disp == 0.
                disp_match = None
                has_reg = False
                for o in dst_objs:
                    if isinstance(o, Register):
                        has_reg = True
                    elif isinstance(o, Scalar):
                        v = o.getUnsignedValue()
                        if v in TARGET_OFFSETS:
                            disp_match = v
                if not (has_reg and disp_match is not None):
                    continue

                # Source operand 1 — capture as immediate if scalar, else describe.
                src_objs = ins.getOpObjects(1)
                src_imm = None
                src_desc = []
                for o in src_objs:
                    if isinstance(o, Scalar):
                        src_imm = o.getUnsignedValue()
                    src_desc.append(str(o))

                fn_va = f.getEntryPoint().getOffset()
                matches_by_fn.setdefault(fn_va, (f.getName(), []))[1].append(
                    (ins, disp_match, src_imm, ", ".join(src_desc))
                )

        if not matches_by_fn:
            print("  (no matches!)")
        else:
            for fn_va in sorted(matches_by_fn.keys()):
                name, hits = matches_by_fn[fn_va]
                print()
                print(f"  --- {name} @ 0x{fn_va:08x} ({len(hits)} write(s)) ---")
                for ins, off, src_imm, src_desc in hits:
                    bytes_str = " ".join(f"{b & 0xff:02X}" for b in ins.getBytes())
                    a = int(str(ins.getAddress()), 16)
                    label = TARGET_OFFSETS[off]
                    if src_imm is not None:
                        tag = ""
                        if src_imm == 300:
                            tag = "  ** value=300 — matches 0x4ADFA5 ! **"
                        elif 150 <= src_imm <= 1000:
                            tag = f"  ** value={src_imm} (in plausible UI range) **"
                        print(f"    0x{a:08x}  {bytes_str:<28}  {ins}    "
                              f"<- {label} = imm {src_imm} (0x{src_imm:x}){tag}")
                    else:
                        print(f"    0x{a:08x}  {bytes_str:<28}  {ins}    "
                              f"<- {label} (src={src_desc})")
                        # Walk back up to 6 ins to see register origin
                        prev = ins.getPrevious()
                        steps = 0
                        body = fm.getFunctionContaining(ins.getAddress()).getBody()
                        while prev is not None and steps < 6 and body.contains(prev.getAddress()):
                            pa = int(str(prev.getAddress()), 16)
                            pb = " ".join(f"{b & 0xff:02X}" for b in prev.getBytes())
                            print(f"        prev  0x{pa:08x}  {pb:<28}  {prev}")
                            prev = prev.getPrevious()
                            steps += 1

        # -------- 3. Full decompilation of the rightside function --------
        print()
        print("===== full decompiled C for SetupWin_do_menu_rightside =====")
        res = decomp.decompileFunction(func, 120, monitor)
        if not res.decompileCompleted():
            print(f"  DECOMP FAILED: {res.getErrorMessage()}")
        else:
            c = res.getDecompiledFunction().getC()
            for line in c.rstrip().splitlines():
                print(f"  {line}")

        decomp.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
