#!/usr/bin/env python
"""Refresh the rw_scale entries in patches.yaml from the regenerated fragments (assemble_rw.py
--fragments): symbol lines, cave content entries (offset + bytes) and site new_bytes are replaced IN
PLACE by id/name. A fragment entry with no counterpart yet (a NEW thunk / cell / site) is INSERTED:
symbols and contents right after the previous fragment entry's counterpart (fragment order), sites
appended at the end of the file and their id added to the owning group's members list.
Use after any change to assemble_rw.py."""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "..", "patches", "patches.yaml")
F = os.path.join(HERE, "..", "patches", "_fragment_rw_%s.yaml")


def main() -> int:
    txt = io.open(P, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.split(nl)
    probs, added = [], []
    # symbols
    prev = None
    for l in io.open(F % "symbols", encoding="utf-8").read().splitlines():
        m = re.match(r"  (\S+):\s", l)
        if not m:
            continue
        name = m.group(1)
        idx = [i for i, x in enumerate(lines) if x.startswith(f"  {name}:")]
        if len(idx) > 1:
            probs.append(f"symbol {name}: {len(idx)} matches")
            continue
        if not idx:
            if prev is None:
                probs.append(f"symbol {name}: new but no anchor")
                continue
            lines.insert(prev + 1, l)
            added.append(f"symbol {name}")
            prev += 1
            continue
        lines[idx[0]] = l
        prev = idx[0]
    # cave contents (3-line blocks: id / offset / bytes)
    cave = io.open(F % "cave", encoding="utf-8").read().splitlines()
    prev = None
    for i in range(0, len(cave), 3):
        cid = cave[i].split("- id: ")[1].strip()
        idx = [k for k, x in enumerate(lines) if x == f"      - id: {cid}"]
        if len(idx) > 1:
            probs.append(f"content {cid}: {len(idx)} matches")
            continue
        if not idx:
            if prev is None:
                probs.append(f"content {cid}: new but no anchor")
                continue
            lines[prev + 3:prev + 3] = cave[i:i + 3]
            added.append(f"content {cid}")
            prev += 3
            continue
        k = idx[0]
        assert lines[k + 1].strip().startswith("offset:") and lines[k + 2].strip().startswith("bytes:")
        lines[k + 1], lines[k + 2] = cave[i + 1], cave[i + 2]
        prev = k
    # sites: new_bytes by id; unknown ids appended + registered in their group
    sites = io.open(F % "sites", encoding="utf-8").read().splitlines()
    blocks, cur = [], None
    for l in sites:
        if re.match(r"  - id: (\S+)", l):
            cur = [l]
            blocks.append(cur)
        elif cur is not None and l.strip():
            cur.append(l)
    for blk in blocks:
        sid = re.match(r"  - id: (\S+)", blk[0]).group(1)
        idx = [k for k, x in enumerate(lines) if x == f"  - id: {sid}"]
        if len(idx) > 1:
            probs.append(f"site {sid}: {len(idx)} matches")
            continue
        if not idx:
            grp = next(x.split("group:")[1].strip() for x in blk if x.strip().startswith("group:"))
            while lines and not lines[-1].strip():
                lines.pop()
            lines.extend([""] + blk + [""])
            gi = [k for k, x in enumerate(lines) if x == f"  - id: {grp}"]
            if len(gi) != 1:
                probs.append(f"site {sid}: group {grp} not found")
                continue
            k = gi[0]
            while not lines[k].startswith("    members:"):
                k += 1
            k += 1
            while lines[k].startswith("      - "):
                k += 1
            lines.insert(k, f"      - {sid}")
            added.append(f"site {sid} (+{grp} member)")
            continue
        k = idx[0]
        nb = next(x for x in blk if x.startswith("    new_bytes:"))
        while not lines[k].startswith("    new_bytes:"):
            k += 1
        lines[k] = nb
    if probs:
        print("\n".join("PROBLEM: " + p for p in probs))
        return 1
    io.open(P, "w", encoding="utf-8", newline="").write(nl.join(lines))
    print("patches.yaml refreshed from the rw fragments" + (": added " + ", ".join(added) if added else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
