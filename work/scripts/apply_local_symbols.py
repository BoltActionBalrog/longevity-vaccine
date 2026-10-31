"""Apply our OWN confirmed symbols (work/symbols/terranx.h) to the Ghidra project.

Distinct from apply_thinker_names.py (which parses refs/thinker/src/*.cpp). This
reads terranx.h, whose symbol bindings are one per line:

    extern <ret> <name>(<args>);   // addr: 0xADDR  <origin>  <note>
    extern <type> <name>;          // addr: 0xADDR  <origin>  <note>

The declared identifier (last identifier before '(' or ';') is the name; the
0xADDR after `addr:` is the address. `// field:` lines are struct layout, not
bindings, and are ignored.

Function-vs-data is decided against the PROGRAM, not the header text:
  - function exists  -> rename (only if currently FUN_*) / noop / skip_named
  - code, no func    -> create function
  - otherwise (data) -> create a primary label / noop / skip_named
Never overwrites an existing non-default name.

Usage:
    run-apply-local-symbols.bat            # dry run (default)
    run-apply-local-symbols.bat --apply    # commit
"""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"
SYMBOLS_FILE = Path(r"D:\SmacxUi\work\symbols\terranx.h")

# One symbol per line: `extern <decl>;  // addr: 0xADDR ...`
_BIND_RE = re.compile(r"^\s*extern\s+(?P<decl>.+?)\s*;\s*//\s*addr:\s*0x(?P<addr>[0-9A-Fa-f]+)")


def _name_from_decl(decl: str):
    """Declared identifier: last identifier before '(' (function) or end (global)."""
    base = decl.split("(", 1)[0].split("[", 1)[0]  # drop args / array dims
    idents = re.findall(r"[A-Za-z_]\w*", base)
    return idents[-1] if idents else None


def extract_symbols():
    """Return list of (name, addr_int)."""
    out = []
    for line in SYMBOLS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _BIND_RE.match(line)
        if not m:
            continue
        name = _name_from_decl(m.group("decl"))
        if name:
            out.append((name, int(m.group("addr"), 16)))
    return out


def main() -> int:
    apply_mode = "--apply" in sys.argv

    syms = extract_symbols()
    print(f"Parsed {SYMBOLS_FILE.name}: {len(syms)} symbol bindings")

    # Dedup by address (conflicting names at one addr -> drop & report) and by
    # name (same name on two addrs -> drop & report).
    by_addr = defaultdict(list)
    for name, addr in syms:
        by_addr[addr].append(name)
    conflict_addrs = {a for a, names in by_addr.items() if len(set(names)) > 1}

    name_counts = Counter(name for name, _ in syms)
    dup_names = {n for n, c in name_counts.items() if c > 1
                 and len({a for nm, a in syms if nm == n}) > 1}

    kept = []
    seen_addr, seen_name = set(), set()
    for name, addr in sorted(syms, key=lambda s: s[1]):
        if addr in conflict_addrs or name in dup_names:
            continue
        if addr in seen_addr or name in seen_name:
            continue
        seen_addr.add(addr)
        seen_name.add(name)
        kept.append((name, addr))
    print(f"Kept {len(kept)} unique bindings "
          f"({len(conflict_addrs)} addr conflicts, {len(dup_names)} name dups dropped)")

    from ghidra.program.model.symbol import SourceType

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
        mem = program.getMemory()
        symtab = program.getSymbolTable()

        def addr_of(value: int):
            return af.getDefaultAddressSpace().getAddress(value)

        stats = defaultdict(int)
        classified = []  # (action, name, addr_int, current, note)

        for name, addr_int in kept:
            addr = addr_of(addr_int)
            if not mem.contains(addr):
                classified.append(("skip_no_addr", name, addr_int, None, "addr not in any block"))
                continue
            func = fm.getFunctionAt(addr)
            if func is not None:
                cur = func.getName()
                if cur == name:
                    classified.append(("noop", name, addr_int, cur, "already named"))
                elif cur.startswith("FUN_"):
                    classified.append(("rename", name, addr_int, cur, ""))
                else:
                    classified.append(("skip_named", name, addr_int, cur, "non-default name"))
                continue
            instr = listing.getInstructionAt(addr)
            block = mem.getBlock(addr)
            if instr is not None and block is not None and block.isExecute():
                classified.append(("create_func", name, addr_int, None, "code, no function"))
            else:
                sym = symtab.getPrimarySymbol(addr)
                if sym is None or sym.getSource() == SourceType.DEFAULT:
                    classified.append(("label", name, addr_int,
                                       None if sym is None else sym.getName(), "data label"))
                elif sym.getName() == name:
                    classified.append(("noop", name, addr_int, sym.getName(), "already labeled"))
                else:
                    classified.append(("skip_named", name, addr_int, sym.getName(), "non-default label"))

        for action, *_ in classified:
            stats[action] += 1

        order = ("rename", "create_func", "label", "noop", "skip_named", "skip_no_addr")
        print("\n=== Classification summary ===")
        for action in order:
            print(f"  {action:>14}: {stats[action]:5d}")

        def dump(action, label, fmt):
            rows = [c for c in classified if c[0] == action]
            if not rows:
                return
            print(f"\n--- {label} ({len(rows)}) ---")
            for _, name, addr_int, cur, _ in rows:
                print("  " + fmt(name, addr_int, cur))

        dump("rename", "rename (FUN_* -> our name)",
             lambda n, a, c: f"0x{a:08x}  {c:<28} -> {n}")
        dump("create_func", "create function",
             lambda n, a, c: f"0x{a:08x}  {n}")
        dump("label", "data label",
             lambda n, a, c: f"0x{a:08x}  {n}" + (f"   (was {c})" if c else ""))
        dump("skip_named", "skip (already has a non-default name)",
             lambda n, a, c: f"0x{a:08x}  keep '{c}'  (terranx.h: {n})")
        dump("skip_no_addr", "skip (addr not mapped)",
             lambda n, a, c: f"0x{a:08x}  {n}")

        if not apply_mode:
            print("\n=== DRY RUN — no changes written. Re-run with --apply to commit. ===")
            return 0

        n_changes = stats["rename"] + stats["create_func"] + stats["label"]
        print(f"\n=== APPLY MODE — committing {n_changes} changes ===")
        problems = []
        tx = program.startTransaction("Apply local symbols (terranx.h)")
        try:
            applied = defaultdict(int)
            for action, name, addr_int, cur, _ in classified:
                addr = addr_of(addr_int)
                try:
                    if action == "rename":
                        fm.getFunctionAt(addr).setName(name, SourceType.USER_DEFINED)
                        applied["rename"] += 1
                    elif action == "create_func":
                        if api.createFunction(addr, name) is None:
                            problems.append((addr_int, name, "createFunction returned None"))
                        else:
                            applied["create_func"] += 1
                    elif action == "label":
                        sym = symtab.createLabel(addr, name, SourceType.USER_DEFINED)
                        sym.setPrimary()
                        applied["label"] += 1
                except Exception as e:  # noqa: BLE001
                    problems.append((addr_int, name, f"{action} failed: {e}"))
            program.endTransaction(tx, True)
        except BaseException:
            program.endTransaction(tx, False)
            raise

        print(f"  renamed:   {applied['rename']}")
        print(f"  created:   {applied['create_func']}")
        print(f"  labeled:   {applied['label']}")
        if problems:
            print(f"  problems ({len(problems)}):")
            for addr_int, name, msg in problems[:25]:
                print(f"    0x{addr_int:08x}  {name}: {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
