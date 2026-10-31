"""Read the timing log timing_plugin.py writes (timings/ beside this file).

    py timing_report.py                 slowest tests, modules and collection of the newest FULL run
    py timing_report.py --last          ... of the newest run, whatever it ran (e.g. a -k scaling)
    py timing_report.py --run <id>      ... of one named run (a timings/runs/<id>.json stem)
    py timing_report.py --history [N]   one line per run, newest last
    py timing_report.py -n 40           show 40 rows per table (default 20)

A "full" run is the one with the most tests among the kept runs, newest wins a tie -- the
pre-commit hook's `-k scaling` runs are partial and must not hide the whole-suite picture.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

TIMINGS_DIR = Path(__file__).resolve().parent / "timings"


def _load_runs() -> list[Path]:
    return sorted((TIMINGS_DIR / "runs").glob("*.json"))


def _pick(args) -> Path | None:
    runs = _load_runs()
    if not runs:
        return None
    if args.run:
        p = TIMINGS_DIR / "runs" / f"{args.run}.json"
        return p if p.is_file() else None
    if args.last:
        return runs[-1]
    best, best_n = None, -1
    for p in runs:                                  # oldest -> newest, so >= lets newest win a tie
        n = json.loads(p.read_text(encoding="utf-8"))["summary"]["n_tests"]
        if n >= best_n:
            best, best_n = p, n
    return best


def _table(title: str, rows: list[tuple], header: tuple, total: float) -> None:
    print(f"\n{title}")
    print("  " + "  ".join(header))
    for row in rows:
        secs = row[0]
        pct = 100.0 * secs / total if total else 0.0
        print(f"  {secs:8.2f}s {pct:5.1f}%  " + "  ".join(str(c) for c in row[1:]))


def report(path: Path, n: int) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    s, tests, collect = data["summary"], data["tests"], data["collect"]
    wall = s["wall_s"] or 1.0
    workers = s.get("workers") or 0
    print(f"run {s['run']}  args={' '.join(s['args']) or '(none)'}  exit={s['exitstatus']}")
    if workers:
        # %wall below is then a share of the SERIAL sum, which is what a slow test costs.
        print(f"  wall {s['wall_s']:.1f}s on {workers} workers  |  serial test time "
              f"{s['tests_s']:.1f}s ({s['tests_s'] / (s['wall_s'] or 1):.1f}x speed-up)")
        wall = s["tests_s"] or 1.0
    else:
        print(f"  wall {s['wall_s']:.1f}s = collection {s['collect_s']:.1f}s + tests "
              f"{s['tests_s']:.1f}s (+ overhead)")
    print(f"  {s['n_tests']} tests, {s['n_failed']} failed, {s['n_skipped']} skipped")

    by_mod: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for nodeid, t in tests.items():
        m = by_mod[nodeid.split("::", 1)[0]]
        m[0] += t["total"]
        m[1] += 1
    mods = sorted(((v[0] + collect.get(k, 0.0), v[0], collect.get(k, 0.0), v[1], k)
                   for k, v in by_mod.items()), reverse=True)
    _table(f"slowest modules (collect + tests), top {n} of {len(mods)}",
           [(m[0], f"collect {m[2]:6.2f}s  {m[3]:5d} tests  {m[4]}") for m in mods[:n]],
           ("    total    %wall",), wall)

    slow = sorted(((t["total"], t["setup"], t["call"], t["outcome"], k)
                   for k, t in tests.items()), reverse=True)
    _table(f"slowest tests, top {n} of {len(slow)}",
           [(t[0], f"setup {t[1]:6.2f}s  call {t[2]:7.2f}s  {t[3]:7s}  {t[4]}") for t in slow[:n]],
           ("    total    %wall",), wall)

    coll = sorted(((v, k) for k, v in collect.items()), reverse=True)
    _table(f"slowest collection (module import), top {min(n, 10)} of {len(coll)}",
           coll[:min(n, 10)], ("     secs    %wall  module",), wall)


def history(n: int) -> None:
    p = TIMINGS_DIR / "history.jsonl"
    if not p.is_file():
        sys.exit("no timing history yet -- run the suite once")
    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    print(f"{'run':24s} {'wall':>8s} {'collect':>8s} {'tests':>6s} {'fail':>5s} {'-n':>3s}  args")
    for line in lines:
        s = json.loads(line)
        coll = "-" if s.get("collect_s") is None else f"{s['collect_s']:.1f}s"   # parallel: no collection phase
        print(f"{s['run']:24s} {s['wall_s']:7.1f}s {coll:>8s} {s['n_tests']:6d} "
              f"{s['n_failed']:5d} {s.get('workers') or 0:3d}  {' '.join(s['args'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--last", action="store_true", help="newest run, even a partial one")
    ap.add_argument("--run", help="a run id (timings/runs/<id>.json)")
    ap.add_argument("--history", nargs="?", const=30, type=int, metavar="N", help="last N runs")
    ap.add_argument("-n", type=int, default=20, help="rows per table")
    args = ap.parse_args()
    if args.history is not None:
        history(args.history)
        return
    path = _pick(args)
    if path is None:
        sys.exit("no timing runs recorded yet -- run the suite once (cd work/tests && py -m pytest)")
    report(path, args.n)


if __name__ == "__main__":
    main()
