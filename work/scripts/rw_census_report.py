#!/usr/bin/env python
"""Summarise work\\frida_report_census.log (hook_report_census.js) into per-kind site tables.

  py rw_census_report.py [log] [--kind N] [--prim NAME] [--md out.md]

Groups every `D <prim> @0xRET dest=<tag> <args> k=<kind>` line by kind, then by (ret, prim, dest), and
prints the count of distinct arg-sets plus up to 3 samples per site, so each remaining report page's
native draw inventory (frames, fills, text rows, sprite blits, widget builds) reads as one table.
Also echoes the RW/RI/HOF DUMP blocks and the SUMMARY blocks verbatim, in order.
"""
from __future__ import annotations

import collections
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "frida_report_census.log")
D_RE = re.compile(r"^D (\S+) @(0x[0-9a-f]+) dest=(\S+) (.*) k=(-?\d+)( HOF)?$")
KIND = {0: "intel", 2: "tech", 3: "energy", 4: "base-status", 5: "projects", 6: "satellites", 7: "units", 8: "score"}


def main() -> int:
    args = sys.argv[1:]
    log = DEFAULT
    want_kind = want_prim = md = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--kind":
            want_kind = int(args[i + 1]); i += 2
        elif a == "--prim":
            want_prim = args[i + 1]; i += 2
        elif a == "--md":
            md = args[i + 1]; i += 2
        else:
            log = a; i += 1
    lines = io.open(log, encoding="utf-8", errors="replace").read().splitlines()
    out = []
    per_kind = collections.OrderedDict()   # kind -> {(ret,prim,dest): [args...]}
    env = []
    for l in lines:
        m = D_RE.match(l)
        if m:
            prim, ret, dest, a, k, hof = m.groups()
            k = int(k)
            if hof:
                k = 100  # Hall of Fame bucket
            if want_kind is not None and k != want_kind:
                continue
            if want_prim and prim != want_prim:
                continue
            per_kind.setdefault(k, collections.OrderedDict()).setdefault((ret, prim, dest), []).append(a)
        elif l.startswith(("---- ", "==== ", "S 0x", "rw.", "ri.", "hof.", "hud", "ENTRY", "show_page", "ReportIf_activate", "hall_of_fame", "HOF vtbl", "PAINTER", "env:")):
            env.append(l)
    for k, sites in per_kind.items():
        name = "Hall of Fame" if k == 100 else KIND.get(k, "?")
        out.append(f"\n## kind {k} ({name}) — {len(sites)} sites, {sum(len(v) for v in sites.values())} distinct arg-sets logged\n")
        out.append("| ret | prim | dest | distinct | samples |")
        out.append("|---|---|---|---|---|")
        for (ret, prim, dest), samples in sorted(sites.items(), key=lambda kv: int(kv[0][0], 16)):
            ex = " ⏎ ".join(s.replace("|", "\\|") for s in samples[:3])
            out.append(f"| {ret} | {prim} | {dest} | {len(samples)} | {ex} |")
    out.append("\n## dumps / summaries (in log order)\n")
    out.append("```")
    out.extend(env)
    out.append("```")
    text = "\n".join(out)
    if md:
        io.open(md, "w", encoding="utf-8", newline="\n").write(text)
        print(f"wrote {md} ({len(text)} chars)")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
