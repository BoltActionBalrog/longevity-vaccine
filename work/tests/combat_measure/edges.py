"""Raw RGB run-length profiles across the BattleWin box edges in each dump."""
import json
import pathlib
import re

P = pathlib.Path(r"D:\SmacxUi\work\_cmb_probe")
RUNS = {"PRISTINE g16": "20260918T222427", "1920 g22": "20260918T232515", "1600 g25": "20260918T232440", "4K g40": "20260918T232346"}


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


def show(tag, idxs, pal, start):
    parts, pos = [], start
    for c, n in rle(idxs):
        r, g, b = pal[c]
        parts.append(f"{pos}:{c}({r},{g},{b})x{n}")
        pos += n
    print("     ", tag, " ".join(parts))


for label, stamp in RUNS.items():
    log = (P / f"combat_geom_{stamp}.log").read_text()
    m = re.search(r"\[REPORT\] rects=(\{.*?\})\n\[REPORT\] seeds=(\{.*?\})", log)
    rects = {k: tuple(map(int, v.split(","))) for k, v in json.loads(m.group(1)).items()}
    seeds = {k: tuple(map(int, v.split(","))) for k, v in json.loads(m.group(2)).items()}
    pix, w, h, pal = load(stamp)
    print(f"\n===== {label}  unitL {rects['+30']} unitR {rects['+40']} DC0 {seeds['DC0']}")
    L, T, R, B = rects["+30"]
    L2, T2, R2, B2 = rects["+40"]
    my = (T + B) // 2 + 40            # below the unit art / text rows? keep inside box, away from text
    my = B - 12
    sL = seeds["DC0"][0]
    show("row  seed.L-4 .. unitL.L+10 :", list(pix[my * w + sL - 4: my * w + L + 10]), pal, sL - 4)
    show("row  unitL.R-8 .. unitR.L+8 :", list(pix[my * w + R - 8: my * w + L2 + 9]), pal, R - 8)
    sR = seeds["DC0"][2]
    show("row  unitR.R-8 .. seed.R+4  :", list(pix[my * w + R2 - 8: my * w + sR + 5]), pal, R2 - 8)
    mx = L + 30
    sT, sB = seeds["DC0"][1], seeds["DC0"][3]
    show("col  seed.T-4 .. unitL.T+10 :", [pix[y * w + mx] for y in range(sT - 4, T + 10)], pal, sT - 4)
    show("col  unitL.B-8 .. seed.B+4  :", [pix[y * w + mx] for y in range(B - 8, min(h, sB + 5))], pal, B - 8)
