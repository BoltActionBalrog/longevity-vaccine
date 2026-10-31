"""Verify a sample of Thinker function names were applied to the project.

Opens the project read-only and checks a hand-picked list of addresses
against their expected Thinker names. Run after apply_thinker_names.py to
confirm persistence.
"""

import sys

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# Spot-check addresses pulled from our earlier xref work and the dry-run output.
EXPECTED = [
    (0x00455610, "load_interface"),
    (0x004554C0, "def_caption_draw"),
    (0x004547E0, "load_icons"),
    (0x00454FC0, "load_cursors"),
    (0x00455E80, "load_fixed_sprites"),
    (0x005D7DE0, "Buffer_load_pcx"),
    (0x005DE580, "Buffer_change_color"),
    (0x005E39A0, "Sprite_extract_2"),
    (0x005E3960, "Sprite_extract"),
    (0x0043E9A0, "DesignWin_exec"),
    (0x005F0650, None),  # WinProc / Win_window_proc / pfncWinProc — conflict, expect FUN_*
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

        ok = 0
        bad = 0
        print()
        print(f"{'address':<12} {'expected':<28} {'actual':<28} status")
        print("-" * 80)
        for addr_int, expected in EXPECTED:
            addr = af.getDefaultAddressSpace().getAddress(addr_int)
            func = fm.getFunctionAt(addr)
            actual = func.getName() if func else "<no function>"
            exp_str = expected if expected else "(conflict, expect FUN_*)"
            if expected is None:
                # Conflict case — we skip these, expect default FUN_ name
                status = "OK (skip)" if actual.startswith("FUN_") else f"unexpected name"
            else:
                status = "OK" if actual == expected else "MISMATCH"
            if status.startswith("OK"):
                ok += 1
            else:
                bad += 1
            print(f"0x{addr_int:08x}  {exp_str:<28} {actual:<28} {status}")

        print()
        print(f"Result: {ok} ok, {bad} bad")

        # Also count total non-default function names as a coarse health check.
        total = 0
        default = 0
        named = 0
        thunk = 0
        for func in fm.getFunctions(True):
            if func.isExternal():
                continue
            total += 1
            n = func.getName()
            if n.startswith("FUN_"):
                default += 1
            elif n.startswith("thunk_"):
                thunk += 1
            else:
                named += 1
        print()
        print(f"Function name census:")
        print(f"  total           : {total}")
        print(f"  named           : {named}")
        print(f"  thunk_*         : {thunk}")
        print(f"  default (FUN_)  : {default}")
        print(f"  named fraction  : {named / total:.1%}")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
