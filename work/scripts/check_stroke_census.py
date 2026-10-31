"""Verdict on `frida_strokecensus.log` — the bake's before/after acceptance oracle.

The census (hook_strokecensus.js) MEASURES the real stroke thickness of every enlarged
frame by reading destination pixels. This script judges those measurements against the
laws in `scaling_laws.py`:

    near == far == stroke_width(g)          for every frame, at every resolution
    stroke_width(16) == 1                   native is byte-identical to vanilla

Run it on the SHIPPED exe to capture the "before" (expect widespread wobble), and again
after the bake (expect zero). The table flipping from N wobbles to 0 is the objective
acceptance criterion the bake has lacked — until now the only test was a human looking
at three screenshots.

    py work\\scripts\\check_stroke_census.py                 # judge the whole log
    py work\\scripts\\check_stroke_census.py --run <label>   # only the last run, tagged

Exit code 0 = every measurable frame obeys the laws. 1 = at least one violation.
Unmeasurable edges (reported as -1 by the census: the sampled column could not
discriminate src row 0 from row 1) are counted and reported, never silently passed.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaling_laws import stroke_width  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tests" / "frida_strokecensus.log"

LINE = re.compile(
    r"frame g=(?P<g>\d+) src=(?P<sw>\d+)x(?P<sh>\d+) dst=(?P<dw>\d+)x(?P<dh>\d+) "
    r"at=\((?P<x>-?\d+),(?P<y>-?\d+)\) destbuf=0x(?P<buf>[0-9a-f]+) "
    r"strokeY=(?P<yn>-?\d+)/(?P<yf>-?\d+) strokeX=(?P<xn>-?\d+)/(?P<xf>-?\d+)"
)


def parse(text: str, last_run_only: bool) -> list[dict]:
    if last_run_only:
        marks = [m.start() for m in re.finditer(r"^===== appended run", text, re.M)]
        if marks:
            text = text[marks[-1]:]
    out = []
    for m in LINE.finditer(text):
        d = {k: int(v, 16 if k == "buf" else 10) for k, v in m.groupdict().items()}
        out.append(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--last-run", action="store_true", help="only the final appended run")
    args = ap.parse_args()

    path = Path(args.log)
    if not path.exists():
        print(f"no census log at {path}\n"
              f"run: run-frida-at-res.bat hook_strokecensus.js 1600 1200 frida_log_append.js")
        return 2

    rows = parse(path.read_text(encoding="utf-8", errors="replace"), args.last_run)
    if not rows:
        print("census log has no frame lines — did the hook attach?")
        return 2

    by_g: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_g[r["g"]].append(r)

    violations = unmeasurable = total = 0
    print(f"{'g':>3} {'K':>2}  {'src':>9} {'dst':>10}   {'strokeY':>9} {'strokeX':>9}  verdict")
    print("-" * 72)
    for g in sorted(by_g):
        k = stroke_width(g)
        for r in sorted(by_g[g], key=lambda r: (r["dw"], r["dh"])):
            total += 1
            pairs = [("Y", r["yn"], r["yf"]), ("X", r["xn"], r["xf"])]
            bad, unk = [], []
            for axis, near, far in pairs:
                # near/far == 0 means the sampled outermost source pixel is the
                # transparent KEY (index 9): a keyed blit never writes it, so it can
                # never match in the dest. That is unmeasurable at this column, not a
                # stroke of width zero. -1 is the census's own "cannot discriminate".
                if near <= 0 or far <= 0:
                    unk.append(axis)
                elif near != far:
                    bad.append(f"{axis}:{near}!={far}")
                elif near != k:
                    bad.append(f"{axis}:{near}!=K{k}")
            if bad:
                violations += 1
                verdict = "FAIL " + ",".join(bad)
            elif unk:
                unmeasurable += 1
                verdict = "unmeasurable(" + ",".join(unk) + ")"
            else:
                verdict = "ok"
            print(f"{g:>3} {k:>2}  {r['sw']:>4}x{r['sh']:<4} {r['dw']:>4}x{r['dh']:<5}"
                  f"   {r['yn']:>4}/{r['yf']:<4} {r['xn']:>4}/{r['xf']:<4}  {verdict}")

    print("-" * 72)
    print(f"frames measured: {total}   violations: {violations}   unmeasurable: {unmeasurable}")
    if 16 in by_g:
        native_bad = [r for r in by_g[16]
                      if (r["yn"] > 0 and r["yn"] != 1) or (r["xn"] > 0 and r["xn"] != 1)]
        if native_bad:
            print(f"!! NATIVE (g=16) IS NOT VANILLA: {len(native_bad)} frames with stroke != 1")
            violations += len(native_bad)
        else:
            print("native g=16: all measured strokes are 1px (vanilla preserved)")
    else:
        print("note: no g=16 run in this log - the native no-op is UNVERIFIED. "
              "Capture 1024x768 before calling the bake done.")

    if violations:
        print("\nVERDICT: laws violated. On the SHIPPED exe this is EXPECTED (uniform NN "
              "enlarge). After the bake it is a regression.")
        return 1
    print("\nVERDICT: every measurable frame obeys near == far == K.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
