r"""cave_map.py — MEASURED occupancy map of a code cave (default pcave2).

The yaml ledger comments lie (six escapes so far: stale lengths, "free" gaps
that were occupied, file-zero scratch BSS).  This tool derives occupancy from
what actually ships: every content entry's ByteTemplate.total_length plus
every cave symbol's declared `size:` (default 4).  Run it BEFORE allocating
or growing any cave slot, and again after editing the yaml.

CAVEAT: a gap is only as free as the ledger's `size:` declarations — runtime
scratch (BSS) that no symbol declares is invisible here too (escapes 2 and 4).
When a symbol names a multi-dword scratch region, DECLARE size:.

    py work\scripts\cave_map.py                 # pcave2 map + free gaps
    py work\scripts\cave_map.py --cave pcave2 --min-gap 0x40
    py work\scripts\cave_map.py --at 0x11000    # who owns / what borders an offset
    py work\scripts\cave_map.py --fit 0x140     # smallest free gap that fits N bytes
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_patches as ap  # noqa: E402

PATCHES = Path(__file__).resolve().parents[1] / "patches" / "patches.yaml"


def spans_for(cave_id: str, patches: Path = PATCHES):
    _, _, caves, symbols = ap.load_patches(patches)
    cave = next((c for c in caves if c["id"] == cave_id), None)
    if cave is None:
        sys.exit(f"no cave {cave_id!r}; caves: {[c['id'] for c in caves]}")
    spans = []
    content_ids = set()
    for ct in cave.get("contents", []) or []:
        off = int(ct["offset"])
        ln = ap.ByteTemplate(ct["bytes"]).total_length
        spans.append((off, off + ln, ct["id"], "code"))
        content_ids.add(ct["id"])
    for name, sym in symbols.items():
        if not isinstance(sym, dict) or sym.get("cave") != cave_id:
            continue
        off = sym.get("offset")
        if off is None or name in content_ids:
            continue
        size = int(sym.get("size", 4))
        spans.append((int(off), int(off) + size, name, "data"))
    spans.sort()
    return cave, spans


def gaps(spans, length):
    out, cur = [], 0
    for a0, a1, _, _ in spans:
        if a0 > cur:
            out.append((cur, a0))
        cur = max(cur, a1)
    if cur < length:
        out.append((cur, length))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cave", default="pcave2")
    p.add_argument("--min-gap", type=lambda s: int(s, 0), default=0x10)
    p.add_argument("--at", type=lambda s: int(s, 0))
    p.add_argument("--fit", type=lambda s: int(s, 0))
    p.add_argument("--patches", type=Path, default=PATCHES)
    a = p.parse_args()
    cave, spans = spans_for(a.cave, a.patches)
    length = int(cave.get("length", 0))
    if a.at is not None:
        hits = [s for s in spans if s[0] <= a.at < s[1]]
        print(f"offset 0x{a.at:x}: " + (", ".join(f"{n} [{k}] 0x{s:x}-0x{e:x}" for s, e, n, k in hits) or "FREE"))
        before = [s for s in spans if s[1] <= a.at]
        after = [s for s in spans if s[0] > a.at]
        if before:
            s, e, n, k = before[-1]; print(f"  prev: {n} [{k}] ends 0x{e:x}")
        if after:
            s, e, n, k = after[0]; print(f"  next: {n} [{k}] starts 0x{s:x}")
        return
    free = gaps(spans, length)
    if a.fit is not None:
        cands = sorted((e - s, s, e) for s, e in free if e - s >= a.fit)
        if not cands:
            print(f"no free gap >= 0x{a.fit:x} in {a.cave} (length 0x{length:x}) — grow the section")
        else:
            for sz, s, e in cands[:5]:
                print(f"fits: 0x{s:x}-0x{e:x} ({sz} B free, need {a.fit})")
        return
    print(f"cave {a.cave}: length 0x{length:x}, {len(spans)} spans")
    for s, e, n, k in spans:
        print(f"  0x{s:05x}-0x{e:05x} {e - s:5d}B {k:4} {n}")
    print("free gaps >= 0x%x:" % a.min_gap)
    for s, e in free:
        if e - s >= a.min_gap:
            print(f"  0x{s:05x}-0x{e:05x} {e - s:5d}B")


if __name__ == "__main__":
    main()
