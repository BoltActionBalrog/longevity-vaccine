"""Open the terranx Ghidra project and print baseline stats.

Run via D:\\SmacxUi\\work\\run-stats.bat (which sets the env vars).
"""

import os
import sys

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

GFX_NEEDLES = (
    "Blt", "BltFast", "Lock", "Unlock", "Flip", "GetDC", "ReleaseDC",
    "CreateSurface", "SetCooperativeLevel", "SetDisplayMode",
    "TextOut", "DrawText", "ExtTextOut", "GetTextExtentPoint",
    "BitBlt", "StretchBlt", "CreateCompatibleDC", "CreateDIBSection",
    "CreateFont", "SelectObject", "SetTextColor", "SetBkMode",
)

ASSET_NAMES = (
    "iface.pcx", "console.pcx", "icons.pcx", "report.pcx",
    "menu.pcx", "buttons.pcx", "credits.pcx", "diplomac.pcx",
    "labels.pcx", "opening.pcx",
)


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
        mem = program.getMemory()
        fm = program.getFunctionManager()
        st = program.getSymbolTable()
        ref_mgr = program.getReferenceManager()
        listing = program.getListing()

        print()
        print("===== terranx.exe baseline =====")
        print(f"Executable path : {program.getExecutablePath()}")
        print(f"Executable MD5  : {program.getExecutableMD5()}")
        print(f"Image base      : {program.getImageBase()}")
        print(f"Address range   : {mem.getMinAddress()} - {mem.getMaxAddress()}")
        print(f"Language        : {program.getLanguage().getLanguageID()}")
        print(f"Compiler spec   : {program.getCompilerSpec().getCompilerSpecID()}")
        print(f"Functions total : {fm.getFunctionCount()}")
        print(f"Instructions    : {listing.getNumInstructions()}")
        print(f"Defined data    : {listing.getNumDefinedData()}")
        print(f"Symbols total   : {st.getNumSymbols()}")

        print()
        print("--- memory blocks ---")
        for blk in mem.getBlocks():
            perms = (
                ("R" if blk.isRead() else "-")
                + ("W" if blk.isWrite() else "-")
                + ("X" if blk.isExecute() else "-")
            )
            print(
                f"  {blk.getName():<12} {blk.getStart()} - {blk.getEnd()}  "
                f"({blk.getSize() // 1024:>6} KB)  {perms}"
            )

        print()
        print("--- imported symbols of interest (graphics / text) ---")
        ext_funcs = {}
        for sym in st.getExternalSymbols():
            name = sym.getName()
            if any(needle in name for needle in GFX_NEEDLES):
                ext_funcs[name] = sym

        for name in sorted(ext_funcs):
            sym = ext_funcs[name]
            refs = sum(1 for _ in ref_mgr.getReferencesTo(sym.getAddress()))
            print(f"  {name:<40} ext={sym.getAddress()}  refs={refs}")

        print()
        print("--- string refs matching SMAC UI asset names ---")
        hits = []
        for data in listing.getDefinedData(True):
            dt = data.getDataType()
            if dt is None:
                continue
            # Cheap filter: only inspect string-like data types.
            if "string" not in dt.getName().lower() and "char" not in dt.getName().lower():
                continue
            s = data.getValue()
            if s is None:
                continue
            sl = str(s).lower()
            for needle in ASSET_NAMES:
                if needle in sl:
                    hits.append((data.getAddress(), str(s)))
                    break

        for addr, s in hits[:60]:
            nrefs = sum(1 for _ in ref_mgr.getReferencesTo(addr))
            print(f"  {addr}  refs={nrefs}  {s!r}")
        if len(hits) > 60:
            print(f"  ... {len(hits) - 60} more")

        print()
        print("===== end =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
