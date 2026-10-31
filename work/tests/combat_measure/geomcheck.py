"""Check the three patched probe runs against the laws and measure strokes/channels/portraits in the dumps."""
import json
import pathlib
import re
import sys
from collections import Counter

sys.path.insert(0, r"D:\SmacxUi\work\scripts")
import scaling_laws as SL

P = pathlib.Path(r"D:\SmacxUi\work\_cmb_probe")
RUNS = {"4K g40": ("20260918T232346", 40), "1600 g25": ("20260918T232440", 25), "1920 g22": ("20260918T232515", 22),
        "PRISTINE g16": ("20260918T222427", 16)}
PAL = None


def load(stamp, tag):
    f = next(P.glob(f"strip_{stamp}_*_{tag}_*.bin"))
    w, h = map(int, re.search(r"_(\d+)x(\d+)\.bin$", f.name).groups())
    raw = f.read_bytes()
    pal = [tuple(raw[i * 4:i * 4 + 3]) for i in range(256)]
    return raw[1024:], w, h, pal


def is_green(rgb):
    r, g, b = rgb
    return g > 60 and g > r + 20 and g > b + 10


def edge_profile(pix, w, pal, x0, x1, y):
    return [pal[pix[y * w + x]] for x in range(x0, x1)]


def stroke_runs(colors):
    """run-length of green-dominant (frame stroke) pixels -> list of (start, len)"""
    out, i = [], 0
    while i < len(colors):
        if is_green(colors[i]):
            j = i
            while j < len(colors) and is_green(colors[j]):
                j += 1
            out.append((i, j - i)); i = j
        else:
            i += 1
    return out


for label, (stamp, g) in RUNS.items():
    log = (P / f"combat_geom_{stamp}.log").read_text()
    m = re.search(r"\[REPORT\] rects=(\{.*?\})\n\[REPORT\] seeds=(\{.*?\})", log)
    rects = {k: tuple(map(int, v.split(","))) for k, v in json.loads(m.group(1)).items()}
    seeds = {k: tuple(map(int, v.split(","))) for k, v in json.loads(m.group(2)).items()}
    want = SL.battlewin_rects(seeds["D80"], seeds["DC0"], g)
    got = (rects["+30"], rects["+40"], rects["+50"], rects["+60"])
    print(f"\n===== {label}  rects {'OK == law' if got == want else 'MISMATCH'}")
    if got != want:
        print("   got ", got, "\n   want", want)
    pix, w, h, pal = load(stamp, "report1_leave")
    k = SL.stroke_width(g) if hasattr(SL, "stroke_width") else None
    print(f"   law stroke_width(g)={k}  s4={4 * g // 16} s3={3 * g // 16}")
    names = ["unitL", "unitR", "portL", "portR"]
    for nm, r in zip(names, got):
        L, T, R, B = r
        my, mx = (T + B) // 2, (L + R) // 2
        # left edge: scan from L-12 to L+16 at mid row; top edge: scan column
        lr = stroke_runs(edge_profile(pix, w, pal, L - 12, L + 16, my))
        rr = stroke_runs(edge_profile(pix, w, pal, R - 16, R + 12, my))
        col_t = [pal[pix[y * w + mx]] for y in range(T - 12, T + 16)]
        col_b = [pal[pix[y * w + mx]] for y in range(B - 16, B + 12)]
        tr, br = stroke_runs(col_t), stroke_runs(col_b)
        fmt = lambda runs, base: [(base + s, n) for s, n in runs]
        print(f"   {nm} {r}: L strokes {fmt(lr, L - 12)}  R strokes {fmt(rr, R - 16)}  T {fmt(tr, T - 12)}  B {fmt(br, B - 16)}")
    # channel between the pair boxes (unitL.R .. unitR.L) and between portrait boxes
    for a, b, nm in ((got[0], got[1], "unit pair"), (got[2], got[3], "portrait pair")):
        my = (a[1] + a[3]) // 2
        prof = edge_profile(pix, w, pal, a[2] - 10, b[0] + 11, my)
        runs = stroke_runs(prof)
        print(f"   {nm} gap row{my}: strokes {[(a[2] - 10 + s, n) for s, n in runs]}  (law gap between rects = {b[0] - a[2]})")
    # seed frame (outer d5a0/d870?) to inner box channel: distance seed.L -> box.L
    print(f"   seed DC0 {seeds['DC0']} -> unitL inset {got[0][0] - seeds['DC0'][0]},{got[0][1] - seeds['DC0'][1]}; "
          f"seed D80 {seeds['D80']} -> portL inset {got[2][0] - seeds['D80'][0]},{got[2][1] - seeds['D80'][1]}")
    # portraits: content bbox inside each portrait box above the label
    for nm, r in zip(names[2:], got[2:]):
        x, y, pw, ph, top = SL.battle_portrait_layout(r, g)
        L, T, R, B = r
        hist = Counter()
        for yy in range(T + 8, B - 8):
            hist.update(pix[yy * w + L + 8: yy * w + R - 8])
        fills = {c for c, _ in hist.most_common(2)}
        xs, ys = [], []
        for yy in range(T + 3, top - 1):
            row = pix[yy * w + L + 3: yy * w + R - 3]
            idx = [i for i, c in enumerate(row) if c not in fills]
            if idx:
                ys.append(yy); xs += [L + 3 + idx[0], L + 3 + idx[-1]]
        print(f"   {nm}: law x,y,w,h=({x},{y},{pw},{ph}) label_top={top} | drawn bbox x {min(xs)}..{max(xs)} ({max(xs) - min(xs) + 1}) "
              f"y {min(ys)}..{max(ys)} ({max(ys) - min(ys) + 1}) | margins L {min(xs) - L} R {R - max(xs)} T {min(ys) - T}")
