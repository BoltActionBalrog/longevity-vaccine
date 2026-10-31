"""Dither/banding checks: (1) box-interior scanline fill period regularity, (2) portrait scanline regularity."""
import json
import pathlib
import re
import sys
from collections import Counter

sys.path.insert(0, r"D:\SmacxUi\work\scripts")
import scaling_laws as SL

P = pathlib.Path(r"D:\SmacxUi\work\_cmb_probe")
RUNS = {"PRISTINE g16": ("20260918T222427", 16), "1920 g22": ("20260918T232515", 22),
        "1600 g25": ("20260918T232440", 25), "4K g40": ("20260918T232346", 40)}


def load(stamp):
    f = next(P.glob(f"strip_{stamp}_*_report1_leave_*.bin"))
    w, h = map(int, re.search(r"_(\d+)x(\d+)\.bin$", f.name).groups())
    raw = f.read_bytes()
    pal = [tuple(raw[i * 4:i * 4 + 3]) for i in range(256)]
    return raw[1024:], w, h, pal


def rle(seq):
    out, i = [], 0
    while i < len(seq):
        j = i
        while j < len(seq) and seq[j] == seq[i]:
            j += 1
        out.append((seq[i], j - i)); i = j
    return out


for label, (stamp, g) in RUNS.items():
    log = (P / f"combat_geom_{stamp}.log").read_text()
    m = re.search(r"\[REPORT\] rects=(\{.*?\})", log)
    rects = {k: tuple(map(int, v.split(","))) for k, v in json.loads(m.group(1)).items()}
    pix, w, h, pal = load(stamp)
    print(f"\n===== {label}")
    # (1) interior fill: a text-free column near the right edge of each box, full height
    for key in ("+30", "+40", "+50", "+60"):
        L, T, R, B = rects[key]
        res = []
        for x in (R - 6, L + 5):
            col = [pix[y * w + x] for y in range(T + 4, B - 3)]
            runs = rle(col)
            pat = Counter((c, n) for c, n in runs[1:-1])
            res.append(dict(pat))
        print(f"   fill {key} x=R-6: {res[0]}   x=L+5: {res[1]}")
    # (2) portraits: per-row mean luminance inside the law rect; classify rows dark/light vs neighbours
    for key in ("+50", "+60"):
        x, y, pw, ph, top = SL.battle_portrait_layout(rects[key], g)
        lum = []
        for yy in range(y, y + ph):
            row = pix[yy * w + x: yy * w + x + pw]
            lum.append(sum(0.3 * pal[c][0] + 0.59 * pal[c][1] + 0.11 * pal[c][2] for c in row) / pw)
        # identical-row detection: NN row duplication shows as exact repeats
        rows = [bytes(pix[yy * w + x: yy * w + x + pw]) for yy in range(y, y + ph)]
        dup = rle([0] + [1 if rows[i] == rows[i - 1] else 0 for i in range(1, len(rows))])
        group = []        # heights of groups of identical rows
        i = 0
        while i < len(rows):
            j = i
            while j + 1 < len(rows) and rows[j + 1] == rows[i]:
                j += 1
            group.append(j - i + 1); i = j + 1
        gh = Counter(group)
        # scanline signal: sign of (lum[i] - mean of neighbours)
        sign = [1 if lum[i] > (lum[i - 1] + lum[i + 1]) / 2 else 0 for i in range(1, len(lum) - 1)]
        sr = Counter(n for _, n in rle(sign))
        print(f"   portrait {key} {pw}x{ph}: identical-row group heights {dict(sorted(gh.items()))} | "
              f"light/dark alternation run-lengths {dict(sorted(sr.items()))}")
