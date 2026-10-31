"""Apply Thinker mod's function names to the terranx Ghidra project.

Parses all `.cpp` files under D:\\SmacxUi\\refs\\thinker\\src for address
bindings of the form

    <TypedefName> <var_name> = (<TypedefName>)0xADDR;

and renames the corresponding function in the Ghidra project to <var_name>.
Phase 1 only: names, no signatures.

Usage:
    run-apply-thinker-names.bat            # dry run (default)
    run-apply-thinker-names.bat --apply    # actually rename
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
THINKER_SRC = Path(r"D:\SmacxUi\refs\thinker\src")

# Single-line binding pattern: TypedefName var_name = (TypedefName)0xADDR;
# Anchored to start-of-line (after optional whitespace) to avoid matching inside
# function bodies or string literals.
BINDING_RE = re.compile(
    r"^[ \t]*([A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*=[ \t]*\([ \t]*\1[ \t]*\*?[ \t]*\)[ \t]*0[xX]([0-9A-Fa-f]+)[ \t]*;",
    re.MULTILINE,
)


def extract_bindings():
    """Return list of (var_name, addr_int, typedef_name, source_file)."""
    bindings = []
    for cpp in sorted(THINKER_SRC.glob("*.cpp")):
        text = cpp.read_text(encoding="utf-8", errors="replace")
        for m in BINDING_RE.finditer(text):
            typedef, var, addr_hex = m.group(1), m.group(2), m.group(3)
            bindings.append((var, int(addr_hex, 16), typedef, cpp.name))
    return bindings


def main() -> int:
    apply_mode = "--apply" in sys.argv

    bindings = extract_bindings()
    print(f"Extracted {len(bindings)} bindings from {THINKER_SRC}")

    # Sanity checks before we touch the project.
    name_counts = Counter(b[0] for b in bindings)
    addr_counts = Counter(b[1] for b in bindings)
    dup_names = [n for n, c in name_counts.items() if c > 1]
    dup_addrs = [a for a, c in addr_counts.items() if c > 1]
    if dup_names:
        print(f"WARN: {len(dup_names)} duplicate names across files; will skip dupes")
        for n in dup_names[:5]:
            locs = [(b[1], b[3]) for b in bindings if b[0] == n]
            print(f"  {n}: {locs}")
    if dup_addrs:
        print(f"WARN: {len(dup_addrs)} addresses bound to multiple names")
        for a in dup_addrs[:5]:
            names = [(b[0], b[3]) for b in bindings if b[1] == a]
            print(f"  0x{a:08x}: {names}")

    # Deduplicate: first occurrence wins, but reject any entry whose name or
    # address collides with another. Safer than picking arbitrarily.
    kept = []
    seen_names = set()
    seen_addrs = set()
    for b in bindings:
        if b[0] in dup_names or b[1] in dup_addrs:
            continue
        if b[0] in seen_names or b[1] in seen_addrs:
            continue
        seen_names.add(b[0])
        seen_addrs.add(b[1])
        kept.append(b)
    print(f"Kept {len(kept)} unique bindings after dedup")

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

        stats = defaultdict(int)
        problems = []

        def addr_of(value: int):
            return af.getDefaultAddressSpace().getAddress(value)

        # First pass: classify every binding without mutating.
        classified = []  # (action, var, addr_int, current_name, note)
        for var, addr_int, typedef, src in kept:
            addr = addr_of(addr_int)
            func = fm.getFunctionAt(addr)
            if func is None:
                # Is there at least an instruction here we could turn into a function?
                instr = listing.getInstructionAt(addr)
                if instr is None:
                    classified.append(("skip_no_code", var, addr_int, None, "no code at addr"))
                else:
                    classified.append(("create", var, addr_int, None, "function would be created"))
                continue
            cur = func.getName()
            if cur == var:
                classified.append(("noop", var, addr_int, cur, "already named"))
            elif cur.startswith("FUN_"):
                classified.append(("rename", var, addr_int, cur, ""))
            else:
                classified.append(("skip_named", var, addr_int, cur, "already has non-default name"))

        for action, *_ in classified:
            stats[action] += 1

        print()
        print("=== Classification summary ===")
        for action in ("rename", "create", "noop", "skip_named", "skip_no_code"):
            print(f"  {action:>14}: {stats[action]:5d}")
        print()

        # Show samples of each non-trivial category.
        def sample(action, n=8):
            return [c for c in classified if c[0] == action][:n]

        if stats["skip_named"]:
            print(f"--- skip_named samples (already named, would not overwrite) ---")
            for _, var, addr_int, cur, _ in sample("skip_named", 10):
                print(f"  0x{addr_int:08x}  current='{cur}'  thinker='{var}'")
            print()

        if stats["create"]:
            print(f"--- create samples (would create new function at addr) ---")
            for _, var, addr_int, _, _ in sample("create", 10):
                print(f"  0x{addr_int:08x}  thinker='{var}'")
            print()

        if stats["skip_no_code"]:
            print(f"--- skip_no_code samples (no instruction at addr) ---")
            for _, var, addr_int, _, _ in sample("skip_no_code", 10):
                print(f"  0x{addr_int:08x}  thinker='{var}'")
            print()

        if not apply_mode:
            print()
            print("=== DRY RUN — no changes written. Re-run with --apply to commit. ===")
            return 0

        # ---- mutate ----
        print(f"=== APPLY MODE — committing {stats['rename'] + stats['create']} changes ===")
        tx = program.startTransaction("Apply Thinker function names")
        try:
            applied_rename = 0
            applied_create = 0
            create_failures = 0

            for action, var, addr_int, cur, _ in classified:
                if action == "rename":
                    func = fm.getFunctionAt(addr_of(addr_int))
                    try:
                        func.setName(var, SourceType.USER_DEFINED)
                        applied_rename += 1
                    except Exception as e:
                        problems.append((addr_int, var, f"rename failed: {e}"))
                elif action == "create":
                    addr = addr_of(addr_int)
                    try:
                        func = api.createFunction(addr, var)
                        if func is None:
                            create_failures += 1
                            problems.append((addr_int, var, "createFunction returned None"))
                        else:
                            applied_create += 1
                    except Exception as e:
                        create_failures += 1
                        problems.append((addr_int, var, f"create failed: {e}"))

            program.endTransaction(tx, True)
        except BaseException:
            program.endTransaction(tx, False)
            raise

        print(f"  renamed: {applied_rename}")
        print(f"  created: {applied_create}")
        print(f"  create failures: {create_failures}")
        if problems:
            print(f"  problems ({len(problems)} total, showing 20):")
            for addr_int, var, msg in problems[:20]:
                print(f"    0x{addr_int:08x}  {var}: {msg}")

        # No explicit save() — pyghidra's open_program context auto-saves on exit.
        # Calling program.save() here conflicts with the still-open context
        # transaction and raises "Unable to lock due to active transaction".

    return 0


if __name__ == "__main__":
    sys.exit(main())
