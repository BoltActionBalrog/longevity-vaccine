"""Diff captured modal snapshots against committed goldens (per resolution).

Regression model: re-capture each modal at the SAME resolutions as the goldens,
then this asserts the numeric fields reproduce. Because a snapshot and its golden
share a resolution, the runtime scale (g) is identical, so values should come
back the same — tolerances are tiny (a couple px), only to absorb any draw
nondeterminism. (The round(native*g/16) scaling math is only needed to compare
ACROSS resolutions, which is a separate optional check, not the gate.)

Numeric diff: every field compared by a dotted path. A small set is required to
match EXACTLY (scale_num, branch, title, dialog.row_count); the rest tolerate
+/-2 px.

Usage:
  python compare_snapshots.py                         # snapshots/ vs golden/
  python compare_snapshots.py --snap DIR --golden DIR
  python compare_snapshots.py --update                # re-baseline: snapshots -> golden
Exit code 0 = all matched, 1 = any diff/missing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SNAP = HERE / "snapshots"
DEFAULT_GOLDEN = HERE / "golden"

POS_TOL = 2                     # px tolerance for sizes/positions
EXACT_PATHS = {                # must match exactly (suffix match on dotted path)
    "scale_num", "branch", "title", "dialog.type", "dialog.row_count",
    "resolution.w", "resolution.h",
}


def _flatten(obj, prefix=""):
    """Flatten a snapshot dict to {dotted_path: scalar}, skipping the volatile
    `pixel` block (compared separately) and indexing list items."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}{i}."))
    else:
        out[prefix.rstrip(".")] = obj
    return out


def _is_exact(path: str) -> bool:
    return any(path == p or path.endswith("." + p) for p in EXACT_PATHS)


def compare_numeric(golden: dict, snap: dict) -> list[str]:
    gf, sf = _flatten(golden), _flatten(snap)
    diffs = []
    for path, gval in gf.items():
        if path not in sf:
            diffs.append(f"missing field {path!r} (golden={gval!r})")
            continue
        sval = sf[path]
        if isinstance(gval, (int, float)) and isinstance(sval, (int, float)) \
                and not isinstance(gval, bool):
            tol = 0 if _is_exact(path) else POS_TOL
            if abs(gval - sval) > tol:
                diffs.append(f"{path}: golden={gval} actual={sval} (tol {tol})")
        else:
            if gval != sval:
                diffs.append(f"{path}: golden={gval!r} actual={sval!r}")
    extra = set(sf) - set(gf)
    for path in sorted(extra):
        diffs.append(f"unexpected field {path!r}=({sf[path]!r})")
    return diffs


def run(snap_dir: Path, golden_dir: Path) -> int:
    goldens = sorted(golden_dir.glob("*@*.json"))
    if not goldens:
        print(f"No goldens in {golden_dir} — capture + --update to create a baseline first.")
        return 1
    fails = 0
    for gj in goldens:
        key = gj.stem                      # <slug>@<res>
        sj = snap_dir / gj.name
        if not sj.exists():
            print(f"[MISS] {key}: no snapshot (modal not captured this run?)")
            fails += 1
            continue
        golden = json.loads(gj.read_text(encoding="utf-8"))
        snap = json.loads(sj.read_text(encoding="utf-8"))
        ndiffs = compare_numeric(golden, snap)
        if ndiffs:
            fails += 1
            print(f"[FAIL] {key}")
            for d in ndiffs:
                print(f"         num: {d}")
        else:
            print(f"[ok]   {key}")
    print(f"\n{len(goldens)-fails}/{len(goldens)} matched.")
    return 1 if fails else 0


def update(snap_dir: Path, golden_dir: Path) -> int:
    golden_dir.mkdir(exist_ok=True)
    n = 0
    for f in snap_dir.glob("*@*.json"):
        shutil.copy2(f, golden_dir / f.name)
        n += 1
    print(f"Re-baselined {n} file(s) into {golden_dir}.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Compare modal snapshots vs goldens.")
    ap.add_argument("--snap", type=Path, default=DEFAULT_SNAP)
    ap.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    ap.add_argument("--update", action="store_true",
                    help="copy snapshots into golden/ (establish/refresh baseline)")
    args = ap.parse_args(argv)
    if args.update:
        return update(args.snap, args.golden)
    return run(args.snap, args.golden)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
