"""Scan terranx.exe for the prevalence of resolution-conditional code paths.

Anchor: the global pointers ScreenWidth (0x9B7B1C) and ScreenHeight (0x9B7B20),
named in Thinker's engine.cpp. Every read xref to either is a place where the
game branches on screen resolution — a candidate patch site for the
"register a new resolution tier" v0.1 strategy.

Output:
  pass 1  — raw xref dump for both globals (addr, refType, enclosing function)
  pass 2  — grouped by enclosing function, with read/write split
  pass 3  — for each function with reads, dump a short instruction window
            around each read so we can see the cmp/branch context

Run via D:\\SmacxUi\\work\\run-scan-resolution.bat.
"""

import sys
from collections import defaultdict

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

SCREEN_WIDTH = 0x009B7B1C
SCREEN_HEIGHT = 0x009B7B20

# Instructions to print before and after each read xref.
CONTEXT_BEFORE = 2
CONTEXT_AFTER = 6


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
        ref_mgr = program.getReferenceManager()
        fm = program.getFunctionManager()
        af = program.getAddressFactory()
        listing = program.getListing()

        def addr(value):
            return af.getDefaultAddressSpace().getAddress(value)

        targets = [("ScreenWidth", SCREEN_WIDTH), ("ScreenHeight", SCREEN_HEIGHT)]

        # ---- pass 1: raw xrefs ----
        print("===== pass 1: raw xrefs =====")
        all_refs = []  # (target_name, from_addr_int, ref_type_str, func_name, func_entry_int)
        for tname, taddr_int in targets:
            taddr = addr(taddr_int)
            refs = list(ref_mgr.getReferencesTo(taddr))
            print(f"\n  {tname} @ 0x{taddr_int:08x} : {len(refs)} xrefs")
            for ref in refs:
                from_addr = ref.getFromAddress()
                rtype = ref.getReferenceType()
                func = fm.getFunctionContaining(from_addr)
                fname = func.getName() if func else "<none>"
                fentry = int(str(func.getEntryPoint()), 16) if func else 0
                all_refs.append(
                    (tname, int(str(from_addr), 16), str(rtype), fname, fentry)
                )

        # ---- pass 2: group by function with read/write split ----
        print()
        print()
        print("===== pass 2: grouped by enclosing function =====")
        # per_func[fentry] = {"name": str, "reads": [...], "writes": [...]}
        per_func = defaultdict(lambda: {"name": "<none>", "reads": [], "writes": []})
        for tname, from_int, rtype, fname, fentry in all_refs:
            entry = per_func[fentry]
            entry["name"] = fname
            bucket = "writes" if "WRITE" in rtype else "reads"
            entry[bucket].append((from_int, tname, rtype))

        # Split: pure-read funcs are our patch candidates; setters are infrastructure.
        readers = [(fe, d) for fe, d in per_func.items() if d["reads"]]
        writers_only = [(fe, d) for fe, d in per_func.items() if not d["reads"] and d["writes"]]

        readers.sort(key=lambda x: -len(x[1]["reads"]))

        print(f"\n  {len(readers)} functions READ ScreenWidth/ScreenHeight")
        print(f"  {len(writers_only)} functions only WRITE them")
        print(f"  {len(all_refs)} total xref records")

        print()
        print(f"  {'#':>3} {'addr':<11} {'reads':>5} {'writes':>6}  function")
        print(f"  {'---':>3} {'-' * 10:<11} {'-' * 5:>5} {'-' * 6:>6}  {'-' * 40}")
        for i, (fentry, d) in enumerate(readers, 1):
            print(
                f"  {i:>3} 0x{fentry:08x} {len(d['reads']):>5} {len(d['writes']):>6}  {d['name']}"
            )

        if writers_only:
            print()
            print(f"--- pure-write functions (resolution setters) ---")
            for fentry, d in writers_only:
                print(
                    f"      0x{fentry:08x} {0:>5} {len(d['writes']):>6}  {d['name']}"
                )

        # ---- pass 3: instruction context around each read ----
        print()
        print()
        print("===== pass 3: instruction context for each READ =====")
        for fentry, d in readers:
            print()
            print(f"--- {d['name']} @ 0x{fentry:08x}  ({len(d['reads'])} read(s)) ---")
            for site_int, tname, rtype in sorted(d["reads"]):
                site = addr(site_int)
                instr = listing.getInstructionAt(site)
                if instr is None:
                    print(f"  0x{site_int:08x}  {tname:<13}  (no instruction)")
                    continue
                # Walk a few instructions before/after for context.
                window = []
                # Before
                cur = instr
                before = []
                for _ in range(CONTEXT_BEFORE):
                    prev = cur.getPrevious()
                    if prev is None:
                        break
                    before.insert(0, prev)
                    cur = prev
                # After
                cur = instr
                after = []
                for _ in range(CONTEXT_AFTER):
                    nxt = cur.getNext()
                    if nxt is None:
                        break
                    after.append(nxt)
                    cur = nxt

                print(f"  read site 0x{site_int:08x}  ({tname})")
                for it in before:
                    print(f"    {it.getAddress()}  {it}")
                print(f"  >>{instr.getAddress()}  {instr}")
                for it in after:
                    print(f"    {it.getAddress()}  {it}")
                print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
