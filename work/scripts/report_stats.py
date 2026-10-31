# Ghidra headless post-script: dump baseline stats for terranx.exe.
# Run via:  analyzeHeadless <proj_loc> <proj_name> -process terranx.exe -noanalysis -postScript report_stats.py
#@category SMACX

from ghidra.program.model.symbol import SymbolType

prog = currentProgram
mem = prog.getMemory()
fm = prog.getFunctionManager()
st = prog.getSymbolTable()
ref_mgr = prog.getReferenceManager()

print("")
print("===== terranx.exe baseline =====")
print("Executable path : " + str(prog.getExecutablePath()))
print("Executable MD5  : " + str(prog.getExecutableMD5()))
print("Image base      : " + str(prog.getImageBase()))
print("Min/Max address : %s - %s" % (mem.getMinAddress(), mem.getMaxAddress()))
print("Language        : " + str(prog.getLanguage().getLanguageID()))
print("Compiler spec   : " + str(prog.getCompilerSpec().getCompilerSpecID()))
print("Functions total : %d (external excluded: %d)" % (
    fm.getFunctionCount(),
    sum(1 for f in fm.getFunctions(True) if not f.isExternal()),
))

# Count defined data, instructions, symbols
print("Instructions    : %d" % prog.getListing().getNumInstructions())
print("Defined data    : %d" % prog.getListing().getNumDefinedData())
print("Symbols total   : %d" % st.getNumSymbols())

# Memory blocks
print("")
print("--- memory blocks ---")
for blk in mem.getBlocks():
    print("  %-12s %s - %s  (%6d KB)  %s%s%s" % (
        blk.getName(),
        blk.getStart(), blk.getEnd(),
        blk.getSize() / 1024,
        "R" if blk.isRead() else "-",
        "W" if blk.isWrite() else "-",
        "X" if blk.isExecute() else "-",
    ))

# Imports of interest for UI scaling work
print("")
print("--- imported symbols of interest (graphics / text) ---")
interesting = (
    "Blt", "BltFast", "Lock", "Unlock", "Flip", "GetDC", "ReleaseDC",
    "CreateSurface", "SetCooperativeLevel", "SetDisplayMode",
    "TextOut", "DrawText", "ExtTextOut", "GetTextExtentPoint",
    "BitBlt", "StretchBlt", "CreateCompatibleDC", "CreateDIBSection",
    "CreateFont", "SelectObject", "SetTextColor", "SetBkMode",
)
ext_funcs = {}
for sym in st.getExternalSymbols():
    name = sym.getName()
    if any(needle in name for needle in interesting):
        ext_funcs[name] = sym

for name in sorted(ext_funcs):
    sym = ext_funcs[name]
    # Find thunks/call sites referencing this external
    refs = 0
    for ref in ref_mgr.getReferencesTo(sym.getAddress()):
        refs += 1
    print("  %-40s ext=%s  refs=%d" % (name, sym.getAddress(), refs))

# Strings that match likely UI bitmap asset filenames
print("")
print("--- string refs matching SMAC UI asset names ---")
from ghidra.program.util import DefinedDataIterator
asset_names = ("iface.pcx", "console.pcx", "icons.pcx", "report.pcx",
               "menu.pcx", "buttons.pcx", "credits.pcx", "diplomac.pcx",
               "labels.pcx")
hits = []
for data in DefinedDataIterator.definedStrings(prog):
    s = data.getValue()
    if not s:
        continue
    sl = str(s).lower()
    for needle in asset_names:
        if needle in sl:
            hits.append((data.getAddress(), str(s)))
            break

for addr, s in hits[:50]:
    nrefs = sum(1 for _ in ref_mgr.getReferencesTo(addr))
    print("  %s  refs=%d  %r" % (addr, nrefs, s))
if len(hits) > 50:
    print("  ... %d more" % (len(hits) - 50))

print("")
print("===== end =====")
