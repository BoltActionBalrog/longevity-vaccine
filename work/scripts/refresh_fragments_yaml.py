#!/usr/bin/env python
"""Refresh patches.yaml IN PLACE from a bake's regenerated fragments, by id/name (generic form of
refresh_rw_yaml.py / refresh_mon_yaml.py):  py refresh_fragments_yaml.py <prefix>
reads work/patches/_fragment_<prefix>_{symbols,cave,sites}.yaml (each optional) and replaces
  symbols  : the `  name: {...}` line of every fragment symbol (must already exist, once)
  contents : the offset + bytes lines under `      - id: <cid>` (must already exist, once)
  sites    : the new_bytes line of every fragment site (must already exist, once)
Blank lines between fragment blocks are tolerated.  Nothing is inserted: a fragment entry with no
counterpart is a PROBLEM (use the bake's own splice script for a first-time splice).
UTF-8 + newline preserving (feedback-yaml-utf8-encoding)."""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "..", "patches", "patches.yaml")


def main(prefix: str) -> int:
    F = os.path.join(HERE, "..", "patches", f"_fragment_{prefix}_%s.yaml")
    txt = io.open(P, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.split(nl)
    probs, n_sym, n_con, n_site = [], 0, 0, 0
    # RELOCATION GUARD (2026-09-17: the se refresh silently moved thunk_btn_gate_pre back to the SE-era
    # slot 0x16DA0 although the rw bake had relocated it to 0x24230 = boot crash at 1600x1200).  A
    # fragment may only change an entry's BYTES; an offset/size change means a LATER bake owns that
    # entry now, and the fragment is stale -> abort unless --allow-relocate is passed deliberately.
    allow_move = "--allow-relocate" in sys.argv
    if os.path.exists(F % "symbols"):
        for l in io.open(F % "symbols", encoding="utf-8").read().splitlines():
            m = re.match(r"  (\S+):\s+(\{[^}]*\})", l)
            if not m:
                continue
            name = m.group(1)
            idx = [i for i, x in enumerate(lines) if x.startswith(f"  {name}:")]
            if len(idx) != 1:
                probs.append(f"symbol {name}: {len(idx)} matches")
                continue
            cur = re.match(r"  \S+:\s+(\{[^}]*\})", lines[idx[0]])
            if cur and not allow_move:
                def _off(spec):
                    mm = re.search(r"offset:\s*(0x[0-9A-Fa-f]+|\d+)", spec)
                    return int(mm.group(1), 0) if mm else None
                if _off(cur.group(1)) != _off(m.group(2)):
                    probs.append(f"symbol {name}: offset {cur.group(1)} -> {m.group(2)} (owned by a later bake? pass --allow-relocate)")
                    continue
            lines[idx[0]] = l
            n_sym += 1
    if os.path.exists(F % "cave"):
        cave = [l for l in io.open(F % "cave", encoding="utf-8").read().splitlines() if l.strip()]
        for i in range(0, len(cave), 3):
            cid = cave[i].split("- id: ")[1].strip()
            assert cave[i + 1].strip().startswith("offset:") and cave[i + 2].strip().startswith("bytes:"), cid
            idx = [k for k, x in enumerate(lines) if x == f"      - id: {cid}"]
            if len(idx) != 1:
                probs.append(f"content {cid}: {len(idx)} matches")
                continue
            k = idx[0]
            assert lines[k + 1].strip().startswith("offset:") and lines[k + 2].strip().startswith("bytes:"), cid
            if not allow_move and int(lines[k + 1].split("offset:")[1].strip(), 0) != int(cave[i + 1].split("offset:")[1].strip(), 0):
                probs.append(f"content {cid}: offset {lines[k + 1].strip()} -> {cave[i + 1].strip()} (owned by a later bake? pass --allow-relocate)")
                continue
            lines[k + 1], lines[k + 2] = cave[i + 1], cave[i + 2]
            n_con += 1
    if os.path.exists(F % "sites"):
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
            if len(idx) != 1:
                probs.append(f"site {sid}: {len(idx)} matches")
                continue
            k = idx[0]
            nb = next(x for x in blk if x.startswith("    new_bytes:"))
            while not lines[k].startswith("    new_bytes:"):
                k += 1
            lines[k] = nb
            n_site += 1
    if probs:
        print("\n".join("PROBLEM: " + p for p in probs))
        return 1
    io.open(P, "w", encoding="utf-8", newline="").write(nl.join(lines))
    print(f"patches.yaml refreshed from the {prefix} fragments: {n_sym} symbols, {n_con} contents, {n_site} sites")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
