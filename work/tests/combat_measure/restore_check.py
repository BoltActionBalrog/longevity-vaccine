"""Post-combat restore: compare slide_hide_leave vs idle_before_combat inside the save-under region
x [D80.R .. D90.L) x y [0 .. DB0.T+2) and in the native band between box5 and box6."""
import json
import pathlib
import re

P = pathlib.Path(r"D:\SmacxUi\work\_cmb_probe")
RUNS = {"OLD 1600 (pre-fix 222602)": ("20260918T222602", 25), "4K g40": ("20260918T232346", 40),
        "1600 g25": ("20260918T232440", 25), "1920 g22": ("20260918T232515", 22)}


def load(stamp, tag):
    f = next(P.glob(f"strip_{stamp}_*_{tag}_*.bin"))
    w, h = map(int, re.search(r"_(\d+)x(\d+)\.bin$", f.name).groups())
    return f.read_bytes()[1024:], w, h


for label, (stamp, g) in RUNS.items():
    log = (P / f"combat_geom_{stamp}.log").read_text()
    seeds = {k: tuple(map(int, v.split(","))) for k, v in json.loads(re.search(r"\[REPORT\] seeds=(\{.*?\})", log).group(1)).items()}
    armed = re.findall(r"slide_hide\(.*?g_cr_armed=(\d)", log)
    a, w, h = load(stamp, "idle_before_combat")
    b, _, _ = load(stamp, "slide_hide_leave")
    L, R, B = seeds["D80"][2], seeds["D90"][0], seeds["DB0"][1] + 2
    diff = sum(1 for y in range(0, B) for x in range(L, R) if a[y * w + x] != b[y * w + x])
    # the band: native y 169..191, x 250..762
    bx0, bx1, by0, by1 = 250 * g // 16, 762 * g // 16, 169 * g // 16, 191 * g // 16
    bd = sum(1 for y in range(by0, by1) for x in range(bx0, bx1) if a[y * w + x] != b[y * w + x])
    # rows below the snapshot, inside the centre column (box6 area): expected to differ only by content repaint
    print(f"{label}: g_cr_armed at hide={armed}  save-under region {L}..{R} x 0..{B}: {diff} px differ of {(R - L) * B} | "
          f"band {bx0},{by0}..{bx1},{by1}: {bd} px differ of {(bx1 - bx0) * (by1 - by0)}")
