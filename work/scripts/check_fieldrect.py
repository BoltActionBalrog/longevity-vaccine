"""Derive the concentric-frame inset law from `frida_fieldrect.log`.

The Quit modal's text box is two concentric frame draws. Their per-side insets are not a
scaled constant, because the outer and inner rects are computed and ROUNDED INDEPENDENTLY:
measured 4/4/4/2 at g=22, 5/5/5/6 at g=25, 10/10/10/10 at g=40. Symmetric at 4K by luck.

This script pairs every nested frame draw on the same destination buffer and reports the four
insets per g. What we need from it:

  * the VANILLA insets (the g=16 run) — CLAUDE.md: patched = vanilla x g/16, and you must
    MEASURE the vanilla value, never eyeball it;
  * whether vanilla is itself asymmetric (then the asymmetry is the engine's and we preserve
    its ratio) or symmetric (then every non-16 g is a scaling bug we introduced);
  * for each g, whether inset == round(vanilla * g/16) per side.

Usage:
    py work\\scripts\\check_fieldrect.py                 # judge the whole log
    py work\\scripts\\check_fieldrect.py --last-run
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaling_laws import half_down  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tests" / "frida_fieldrect.log"

LINE = re.compile(
    r"rect g=(?P<g>\d+) (?P<tag>\S+) set=(?P<set>0x[0-9a-f]+)\S* "
    r"dest=(?P<dest>0x[0-9a-f]+) L=(?P<L>-?\d+) T=(?P<T>-?\d+) R=(?P<R>-?\d+) B=(?P<B>-?\d+)"
)


def parse(text: str, last: bool):
    if last:
        marks = [m.start() for m in re.finditer(r"^===== appended run", text, re.M)]
        if marks:
            text = text[marks[-1]:]
    out = []
    for m in LINE.finditer(text):
        d = m.groupdict()
        out.append({
            "g": int(d["g"]), "tag": d["tag"], "set": d["set"], "dest": d["dest"],
            "L": int(d["L"]), "T": int(d["T"]), "R": int(d["R"]), "B": int(d["B"]),
        })
    return out


def nested(a, b) -> bool:
    """b strictly inside a, by at least 1px on every side."""
    return (b["L"] > a["L"] and b["T"] > a["T"]
            and b["R"] < a["R"] and b["B"] < a["B"]
            and (b["R"] - b["L"]) > 0.5 * (a["R"] - a["L"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--last-run", action="store_true")
    args = ap.parse_args()

    p = Path(args.log)
    if not p.exists():
        print(f"no log at {p}\nrun: run-frida-at-res.bat hook_fieldrect.js 1024 768 frida_log_append.js")
        return 2
    rows = parse(p.read_text(encoding="utf-8", errors="replace"), args.last_run)
    if not rows:
        print("no rect lines — did the hook attach? open the QUIT modal.")
        return 2

    by = defaultdict(list)
    for r in rows:
        by[(r["g"], r["dest"])].append(r)

    pairs = defaultdict(list)          # g -> list of (outer, inner)
    for (g, dest), rs in by.items():
        for a in rs:
            for b in rs:
                if a is b or not nested(a, b):
                    continue
                # keep only the TIGHTEST enclosing outer for each inner
                pairs[g].append((a, b))

    if not pairs:
        print("no nested frame pairs found. Was the Quit modal open?")
        return 2

    print(f"{'g':>3} {'outer set':<10} {'inner set':<10} {'outer wxh':>11} "
          f"{'L':>3} {'T':>3} {'R':>3} {'B':>3}  symmetric?")
    print("-" * 74)
    vanilla = {}
    for g in sorted(pairs):
        seen = set()
        for a, b in sorted(pairs[g], key=lambda ab: -(ab[0]["R"] - ab[0]["L"])):
            L = b["L"] - a["L"]; T = b["T"] - a["T"]
            R = a["R"] - b["R"]; B = a["B"] - b["B"]
            key = (a["set"], b["set"], L, T, R, B)
            if key in seen:
                continue
            seen.add(key)
            w = a["R"] - a["L"] + 1
            h = a["B"] - a["T"] + 1
            sym = "yes" if (L == R and T == B) else f"NO (T{T} vs B{B}, L{L} vs R{R})"
            print(f"{g:>3} {a['set']:<10} {b['set']:<10} {w:>5}x{h:<5} "
                  f"{L:>3} {T:>3} {R:>3} {B:>3}  {sym}")
            if g == 16:
                vanilla[(a["set"], b["set"])] = (L, T, R, B)

    print()
    if not vanilla:
        print("!! NO g=16 RUN. Vanilla insets are UNKNOWN and the fix cannot be made faithful.")
        print("   Capture 1024x768 first: run-frida-at-res.bat hook_fieldrect.js 1024 768 frida_log_append.js")
        return 1

    print("VANILLA (g=16) insets, and what each g SHOULD be (vanilla * g/16, half-down):")
    for (so, si), (L, T, R, B) in vanilla.items():
        print(f"  {so} -> {si}:  L={L} T={T} R={R} B={B}"
              + ("   (vanilla is itself asymmetric — preserve the ratio, do not force equality)"
                 if (L != R or T != B) else "   (vanilla is symmetric — every asymmetry at g>16 is ours)"))
        for g in (22, 25, 40):
            want = tuple(half_down(v * g, 16) for v in (L, T, R, B))
            print(f"      g={g:>2}: want L={want[0]} T={want[1]} R={want[2]} B={want[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
