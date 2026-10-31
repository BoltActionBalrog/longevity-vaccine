"""Disasm dump to prepare the text-rendering and first-three-decoration patches.

Two regions, with call targets + immediates resolved:

  1. SetupWin_do_menu_rightside @ 0x004ADB70 — from function start through the
     Buffer_set_font call (~0x4ADEB0). Goal: find which stack-local Font object
     is passed to Buffer_set_font @ ~0x4ADEA4, which ctor builds it, and what
     SIZE literal that ctor is handed (the lever for glyph scaling).

  2. SetupWin_draw_item @ 0x004AE4D0 — full body (to 0x004AE756). Goal: pin the
     addresses of Spot_get_rect, Buffer_write_cent_l_7, the text-inset
     arithmetic (immediates 0x1f/0x39/0xc/0xf etc.), and the decoration block at
     0x4AE679 — specifically how [ESI+0xa28+i*4] / [ESI+0xa34+i*4] positions and
     [deco+0x80]/[deco+0x84] sizes are loaded, so we can scale them.

Read-only. Run via D:\\SmacxUi\\work\\run-dump-text-deco.bat.
"""

import sys
import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

# Names we know from prior analysis, keyed by VA, for tagging CALL targets.
KNOWN = {
    0x005D4EF0: "GraphicWin_init",
    0x005D7670: "Buffer_init",
    0x005D79C0: "Buffer_resize",
    0x005DFF00: "Buffer_copy_4",
    0x005D9610: "Buffer_copy_3",
    0x00629E50: "FLC_loader_629e50",
    0x005D7470: "FUN_005d7470",
    0x00402970: "FUN_00402970",
    0x005FA8A0: "Spot_init",
    0x005FAC00: "Spot_get_rect",
    0x00618F40: "Font_init",
    0x005DACB0: "Buffer_set_text_color",
    0x005DAC70: "Buffer_set_font",
    0x005DD130: "Buffer_write_cent_l_7",
}

REGIONS = [
    ("Buffer_write_cent_l_7 (vertical-centering check)", 0x005DD130, 0x005DD2C0),
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
        af = program.getAddressFactory()
        listing = program.getListing()
        ref_mgr = program.getReferenceManager()
        fm = program.getFunctionManager()

        def addr(value):
            return af.getDefaultAddressSpace().getAddress(value)

        def fmt_bytes(b):
            return " ".join(f"{x & 0xFF:02X}" for x in b)

        def call_target(ins):
            for r in ref_mgr.getReferencesFrom(ins.getAddress()):
                if r.getReferenceType().isCall():
                    return r.getToAddress().getOffset()
            return None

        def tag_for(va):
            if va in KNOWN:
                return KNOWN[va]
            f = fm.getFunctionContaining(addr(va))
            if f is not None and f.getEntryPoint().getOffset() == va:
                return f.getName()
            return f"FUN_{va:08x}" if f is None else f.getName()

        for title, start_va, end_va in REGIONS:
            print("=" * 100)
            print(f"{title}   0x{start_va:08x} .. 0x{end_va:08x}")
            print("=" * 100)
            ins = listing.getInstructionAt(addr(start_va))
            while ins is not None and ins.getAddress().getOffset() < end_va:
                va = ins.getAddress().getOffset()
                bb = fmt_bytes(ins.getBytes())
                line = f"  0x{va:08x}  {bb:<24}  {ins}"
                mnem = ins.getMnemonicString().upper()
                if mnem.startswith("CALL"):
                    tgt = call_target(ins)
                    if tgt is not None:
                        line += f"      ; -> {tag_for(tgt)} (0x{tgt:08x})"
                print(line)
                ins = ins.getNext()
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
