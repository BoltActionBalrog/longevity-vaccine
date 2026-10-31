"""Extract candidate patch sites from a list of tier-1 functions.

For each function: walk every instruction; emit a record whenever the
instruction touches a "resolution-relevant" value — either:
  - a memory reference to ScreenWidth (0x9B7B1C) or ScreenHeight (0x9B7B20), or
  - an immediate scalar in the well-known set {800, 1024, 600, 768} (and the
    same values expressed as hex 0x320, 0x400, 0x258, 0x300 — same numbers).

For each hit, emit:
  - virtual address
  - mnemonic + operands as Ghidra renders them
  - the raw instruction bytes (anchor material for the patcher)
  - classification (which global or which literal)
  - 2 instructions of context before and after

Output is plain text, grouped by function. Curation into the patches.yaml
schema happens by hand after review.

Run via D:\\SmacxUi\\work\\run-extract-patch-sites.bat.
"""

import sys

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# Tier-1 candidates from D:\SmacxUi\work\symbols\terranx.h.
TARGETS = [
    (0x004A3460, "init_report_screen"),
    (0x004AD880, "SetupWin_ctor"),
    (0x004ADB70, "SetupWin_do_menu_rightside"),
    (0x004AE4D0, "SetupWin_draw_item"),
    (0x0041E8D0, "BaseWin_init"),
    (0x0051D890, "Console_init"),
    (0x005EBD80, "Win_init"),
    (0x005ED5C0, "Win_center"),
    (0x005F01F0, "Win_init_class"),
    (0x00404920, "Popup_show"),
    (0x00404B10, "Popup_calculate_dimensions"),
    (0x00600860, "BasePop_ctor"),
    (0x006015B0, "BasePop_init"),
    (0x00603800, "BasePop_calculate_dimensions"),
]

SCREEN_WIDTH_PTR = 0x009B7B1C
SCREEN_HEIGHT_PTR = 0x009B7B20
SCREEN_GLOBALS = {SCREEN_WIDTH_PTR, SCREEN_HEIGHT_PTR}

# Common screen-dimension literals (decimal and hex are the same number).
SCREEN_VALUES = {
    800,    # 0x320
    1024,   # 0x400
    600,    # 0x258
    768,    # 0x300
}

CONTEXT = 2  # instructions of context on each side


def bytes_hex(byte_arr) -> str:
    return " ".join(f"{b & 0xff:02X}" for b in byte_arr)


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
        from ghidra.program.model.address import Address

        def addr_of(value):
            return af.getDefaultAddressSpace().getAddress(value)

        for addr_int, expected_name in TARGETS:
            entry = addr_of(addr_int)
            func = fm.getFunctionAt(entry)
            if func is None:
                print(f"\n##### NO FUNCTION at 0x{addr_int:08x} ({expected_name}) — skipping #####\n")
                continue

            actual_name = func.getName()
            print(f"\n\n##### {actual_name} @ 0x{addr_int:08x} (expected: {expected_name}) #####")

            body = func.getBody()
            instr_iter = listing.getInstructions(body, True)
            instrs = []
            while instr_iter.hasNext():
                instrs.append(instr_iter.next())

            # Index instructions for context lookups.
            instr_addrs = [int(str(i.getAddress()), 16) for i in instrs]

            hits = []  # list of (index_in_instrs, kind, value_or_addr)

            for idx, instr in enumerate(instrs):
                for op_idx in range(instr.getNumOperands()):
                    ops = instr.getOpObjects(op_idx)
                    for obj in ops:
                        if isinstance(obj, Scalar):
                            v = obj.getUnsignedValue()
                            if v in SCREEN_VALUES:
                                hits.append((idx, "imm", int(v)))
                        elif isinstance(obj, Address):
                            v = obj.getOffset()
                            if v in SCREEN_GLOBALS:
                                hits.append((idx, "mem", int(v)))

            if not hits:
                print("  (no resolution-relevant instructions found)")
                continue

            print(f"  {len(hits)} hit(s):")
            for hit_idx, kind, val in hits:
                instr = instrs[hit_idx]
                a = int(str(instr.getAddress()), 16)
                if kind == "mem":
                    gname = "ScreenWidth" if val == SCREEN_WIDTH_PTR else "ScreenHeight"
                    label = f"refs {gname} (0x{val:08x})"
                else:
                    label = f"immediate 0x{val:x} ({val})"
                print()
                print(f"  --- hit @ 0x{a:08x}  [{label}] ---")
                # Context lines (before)
                for c in range(max(0, hit_idx - CONTEXT), hit_idx):
                    ci = instrs[c]
                    ca = int(str(ci.getAddress()), 16)
                    cb = bytes_hex(ci.getBytes())
                    print(f"      0x{ca:08x}  {cb:<28}  {ci}")
                # The hit
                hb = bytes_hex(instr.getBytes())
                print(f"  >>> 0x{a:08x}  {hb:<28}  {instr}")
                # Context lines (after)
                for c in range(hit_idx + 1, min(len(instrs), hit_idx + 1 + CONTEXT)):
                    ci = instrs[c]
                    ca = int(str(ci.getAddress()), 16)
                    cb = bytes_hex(ci.getBytes())
                    print(f"      0x{ca:08x}  {cb:<28}  {ci}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
