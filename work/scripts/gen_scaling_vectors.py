"""Emit golden vectors for the scaling laws — the contract every PORT must meet.

`scaling_laws.py` is the reference. The Frida prototypes and the baked cave
thunks are ports of it, written in JS and x86 asm respectively, where a sweep
is impractical. This script freezes the reference's output at the geometry the
game actually draws, so a port can be checked against NUMBERS rather than
against "it looked fine at 4K".

    py work\\scripts\\gen_scaling_vectors.py            # print
    py work\\scripts\\gen_scaling_vectors.py --write    # refresh the JSON

The JSON is committed and guarded by `tests/test_scaling_laws.py`, so a change
to a law shows up as a reviewable diff of concrete pixel values instead of a
silent behavioural drift.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scaling_laws import band_widths, cum, stroke_width  # noqa: E402

VECTORS_PATH = Path(__file__).resolve().parent.parent / "tests" / "golden_scaling_vectors.json"

# The real draws, from work/tests/frida_frame9.log. (params VA, band n, dst span)
# Kept small and REAL: these are frames a human has looked at and signed off.
CASES = [
    # label,                    n,   dst spans at g = 16 / 22 / 25 / 40
    ("quote_ring_d5a0",         6,   {16: 575, 22: 790, 25: 898, 40: 1432}),
    ("quote_backdrop_d690",     6,   {16: 721, 22: 991, 25: 1126, 40: 1805}),
    ("picker_window_6846b0",   61,   {16: 790, 22: 1086, 25: 1234, 40: 1975}),
    ("picker_window_y",        44,   {16: 300, 22: 412, 25: 468, 40: 750}),
    ("title_band_d618",         6,   {16: 778, 22: 1069, 25: 1215, 40: 1942}),
]


def build() -> dict:
    out = {
        "_comment": (
            "Golden vectors for scaling_laws.py. Ports (hook_frame9.js, the baked "
            "thunk) MUST reproduce these exactly. Regenerate with "
            "scripts/gen_scaling_vectors.py --write and review the diff."
        ),
        "stroke_width": {str(g): stroke_width(g) for g in range(16, 41)},
        "frames": {},
    }
    for label, n, spans in CASES:
        entry = {}
        for g, span in spans.items():
            src = max(2 * n, span * 16 // g)
            b = cum(n, span, src)
            entry[str(g)] = {
                "src": src,
                "dst": span,
                "band": b,
                "stroke": stroke_width(g),
                "widths": band_widths(n, b, stroke_width(g)),
            }
        out["frames"][label] = {"n": n, "by_g": entry}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rewrite the JSON in place")
    args = ap.parse_args()

    data = build()
    text = json.dumps(data, indent=2) + "\n"
    if args.write:
        VECTORS_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {VECTORS_PATH}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
