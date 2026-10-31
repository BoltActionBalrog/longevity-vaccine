"""Build the portraits-hd pack: the curated leader images, framed exactly like the game's own portraits.

Each source image (dist\\portraits-hd-src\\alpha centauri (N).png) is a repaint of one leader.  Its framing differs
a little from the game's (some carry extra margin, three are clearly off: morgan tall, usurper wide, caretake), and
the DLL's runtime framing is a plain cover crop.  So the pack is pre-framed: the vanilla DATALINK portrait (the
largest slot; all four slots show the same full picture) is registered inside the image by normalised
cross-correlation over scale and offset, and the image is cropped to that rect at the datalink interior's aspect.
At runtime the cover crop of a pack image is then (almost) the identity.

    py art\\build_portraits_hd.py --provenance PROVENANCE.txt            # -> dist\\portraits-hd\\
    py art\\build_portraits_hd.py --dry-run                              # register + report, write nothing

Output: <faction>.png (lossless, source resolution) + pack-manifest.json (per-file sha256/size + registration)
+ PROVENANCE.txt (the art's source and licence, copied from --provenance; required for a real build).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import config  # noqa: E402

DEFAULT_SRC = REPO / "dist" / "portraits-hd-src"
DEFAULT_OUT = REPO / "dist" / "portraits-hd"
MANIFEST = "pack-manifest.json"
PROVENANCE = "PROVENANCE.txt"

#: source file number -> faction file name (visual match against each sheet's DATALINK crop, 2026-09-29)
LEADERS = {1: "caretake", 2: "usurper", 3: "spartans", 4: "hive", 5: "pirates", 6: "cyborg", 7: "drone",
           8: "angels", 9: "univ", 10: "morgan", 11: "peace", 12: "fungboy", 13: "believe", 14: "gaians"}
#: the datalink slot incl. its 1-px frame, and its interior (load_faction_art's Sprite_extract_2 rect)
DATALINK = (531, 1, 164, 198)
INTERIOR = (DATALINK[0] + 1, DATALINK[1] + 1, DATALINK[2] - 2, DATALINK[3] - 2)
MIN_NCC = 0.65
MIN_MARGIN = 0.04            # the source's own leader must beat every OTHER leader's vanilla art by this much: the
                             # weakest correct match measured 0.742 (gaians) while the best wrong one reached 0.698
                             # (believe vs hive) -- a threshold alone cannot catch a mis-numbered source (audit
                             # 2026-10-03)
MAX_OVERHANG = 0.02          # a registered rect may poke this far (fraction of the image side) past an edge


def source_path(src_dir: pathlib.Path, n: int) -> pathlib.Path:
    return src_dir / f"alpha centauri ({n}).png"


def _gray(im):
    import numpy as np
    return np.asarray(im.convert("L"), dtype=np.float64)


def _descan(a):
    """Vertical 1-2-1 blur: removes the vanilla art's one-row scanlines before matching."""
    import numpy as np
    p = np.pad(a, ((1, 1), (0, 0)), mode="edge")
    return (p[:-2] + 2 * p[1:-1] + p[2:]) / 4


def _ncc_map(img, t):
    import numpy as np
    from scipy.signal import fftconvolve
    th, tw = t.shape
    tz = t - t.mean()
    tn = np.sqrt((tz * tz).sum())
    num = fftconvolve(img, tz[::-1, ::-1], mode="valid")
    ones = np.ones((th, tw))
    s1 = fftconvolve(img, ones, mode="valid")
    s2 = fftconvolve(img * img, ones, mode="valid")
    var = np.maximum(s2 - s1 * s1 / (th * tw), 1e-9)
    return num / (np.sqrt(var) * tn)


def register(hd, vanilla_interior, work_scale: int = 2, steps: int = 60):
    """Where the vanilla interior sits in the HD image: (ncc, (x, y, w, h)) in HD pixels, floats.
    Searches uniform scales from 'the interior just fits' to 2.2x that, on the HD image reduced by work_scale."""
    import numpy as np
    from PIL import Image
    small = hd.resize((hd.size[0] // work_scale, hd.size[1] // work_scale), Image.LANCZOS)
    t = _descan(_gray(vanilla_interior))
    th, tw = t.shape
    W, H = small.size
    lo = max(tw / W, th / H)
    best = (-2.0, 1.0, 0, 0)
    for s in np.linspace(lo * 0.97, lo * 2.2, steps):
        sw, sh = int(round(W * s)), int(round(H * s))
        if sw < tw or sh < th:
            continue
        m = _ncc_map(_descan(_gray(small.resize((sw, sh), Image.LANCZOS))), t)
        oy, ox = np.unravel_index(int(np.argmax(m)), m.shape)
        if m[oy, ox] > best[0]:
            best = (float(m[oy, ox]), float(s), int(ox), int(oy))
    ncc, s, ox, oy = best
    k = s / work_scale                                   # HD px -> template px
    return ncc, (ox / k, oy / k, tw / k, th / k)


def crop_rect(rect, img_w: int, img_h: int, aspect=(INTERIOR[2], INTERIOR[3])):
    """The registered rect at exactly the interior's aspect (height kept, width derived, centred on the rect),
    shifted inside the image.  Returns ((x, y, w, h) ints, overhang fraction before the shift)."""
    x, y, w, h = rect
    ch = int(round(h))
    cw = int(round(ch * aspect[0] / aspect[1]))
    # the overhang of the rect AS REGISTERED, before any clamp (a clamp first would hide it)
    cx0, cy0 = int(round(x + w / 2 - cw / 2)), int(round(y + h / 2 - ch / 2))
    over = max(max(0, -cx0, cx0 + cw - img_w) / img_w, max(0, -cy0, cy0 + ch - img_h) / img_h)
    if cw > img_w:                                       # never wider than the image: shrink uniformly
        cw = img_w
        ch = int(round(cw * aspect[1] / aspect[0]))
    if ch > img_h:                                       # never taller either: shrink uniformly (keep the aspect)
        ch = img_h
        cw = int(round(ch * aspect[0] / aspect[1]))
    cx = int(round(x + w / 2 - cw / 2))
    cy = int(round(y + h / 2 - ch / 2))
    cx = min(max(cx, 0), img_w - cw)
    cy = min(max(cy, 0), img_h - ch)
    return (cx, cy, cw, ch), over


def vanilla_interior(faction: str):
    from PIL import Image
    sheet = Image.open(config.game_dir() / f"{faction}.pcx").convert("RGB")
    x, y, w, h = INTERIOR
    return sheet.crop((x, y, x + w, y + h))


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan(src_dir: pathlib.Path, only=None):
    """Register every source.  Returns [(n, faction, ncc, crop, overhang, image)]; raises on a refusal."""
    from PIL import Image
    out, problems = [], []
    for n, fac in LEADERS.items():
        if only and fac not in only:
            continue
        p = source_path(src_dir, n)
        if not p.is_file():
            problems.append(f"missing source {p.name} ({fac})")
            continue
        im = Image.open(p).convert("RGB")
        ncc, rect = register(im, vanilla_interior(fac))
        crop, over = crop_rect(rect, *im.size)
        if ncc < MIN_NCC:
            problems.append(f"{fac}: registration NCC {ncc:.3f} < {MIN_NCC} (wrong image for this leader?)")
        else:                                            # it must match ITS leader clearly better than any other
            rivals = [(register(im, vanilla_interior(o), steps=30)[0], o) for o in LEADERS.values() if o != fac]
            best, who = max(rivals) if rivals else (-2.0, "")
            if best > ncc - MIN_MARGIN:
                problems.append(f"{fac}: also matches {who}'s art ({best:.3f} vs its own {ncc:.3f}): is source "
                                f"({n}) really {fac}?")
        if over > MAX_OVERHANG:
            problems.append(f"{fac}: registered rect overhangs the image by {over:.1%} (> {MAX_OVERHANG:.0%})")
        out.append((n, fac, ncc, crop, over, im))
    if problems:
        raise SystemExit("REFUSED:\n  " + "\n  ".join(problems))
    return out


def build(src_dir: pathlib.Path, out_dir: pathlib.Path, provenance: pathlib.Path | None, dry_run: bool,
          only=None) -> int:
    rows = plan(src_dir, only)
    for n, fac, ncc, crop, over, im in rows:
        print(f"  {fac:9s} <- ({n:2d}) {im.size[0]}x{im.size[1]}  ncc={ncc:.3f}  crop={crop}  overhang={over:.2%}")
    if dry_run:
        print("dry run: nothing written")
        return 0
    if provenance is None or not provenance.is_file():
        raise SystemExit("REFUSED: --provenance <file> (the art's source and licence) is required for a real build")
    out_dir.mkdir(parents=True, exist_ok=True)
    stale = {p.name for p in out_dir.iterdir() if p.is_file()} - {f"{f}.png" for _, f, *_ in rows} \
        - {MANIFEST, PROVENANCE}
    if stale:
        raise SystemExit(f"REFUSED: unexpected files in {out_dir}: {sorted(stale)} (the pack is exactly the leaders "
                         f"+ {MANIFEST} + {PROVENANCE}; remove them first)")
    files = []
    for n, fac, ncc, (x, y, w, h), over, im in rows:
        dst = out_dir / f"{fac}.png"
        im.crop((x, y, x + w, y + h)).save(dst, format="PNG")
        files.append({"name": dst.name, "size": dst.stat().st_size, "sha256": sha256_file(dst),
                      "source": source_path(src_dir, n).name, "ncc": round(ncc, 4), "crop": [x, y, w, h]})
    (out_dir / PROVENANCE).write_text(provenance.read_text(encoding="utf-8"), encoding="utf-8")
    doc = {"schema": 1, "pack": "portraits-hd", "file_count": len(files),
           "total_size": sum(f["size"] for f in files), "files": files}
    (out_dir / MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(files)} portraits + {MANIFEST} + {PROVENANCE} to {out_dir}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=pathlib.Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    ap.add_argument("--provenance", type=pathlib.Path, default=None,
                    help="text file naming the art's source and licence (copied into the pack)")
    ap.add_argument("--only", default=None, help="comma list of faction names (default: all 14)")
    ap.add_argument("--dry-run", action="store_true", help="register and report; write nothing")
    a = ap.parse_args(argv)
    only = set(a.only.split(",")) if a.only else None
    if only and not a.dry_run:                           # a partial pack is never valid (release needs all 14)
        ap.error("--only is for --dry-run checks; a real build always writes the whole pack")
    return build(a.src, a.out, a.provenance, a.dry_run, only)


if __name__ == "__main__":
    sys.exit(main())
