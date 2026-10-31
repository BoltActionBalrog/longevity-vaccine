"""Measure text ink in the strip dumps and compare against GDI-equivalent renders of candidate faces."""
import pathlib
from collections import Counter
from PIL import Image, ImageFont

P = pathlib.Path(r"D:\SmacxUi\work\_cmb_probe")
FONTS = pathlib.Path(r"C:\Windows\Fonts")
GD = pathlib.Path(r"D:/GOG Galaxy/Games/Sid Meier's Alpha Centauri Planetary Pack")
# The game registers ONLY arialn.ttf: in-game "Arial Narrow bold" is GDI's SYNTHETIC bold of it (~9% wider than the
# arialnb.ttf face), which PIL cannot render -- measure bold Narrow with GDI (CreateFontIndirectA, lfWeight 700, after
# AddFontResourceExA(arialn.ttf, FR_PRIVATE) alone; scaling-text skill), never with arialnb.ttf.
FACES = {"Arial": FONTS / "arial.ttf", "Arial Bold": FONTS / "arialbd.ttf", "Arial Narrow": GD / "arialn.ttf"}


def load(name):
    raw = (P / name).read_bytes()
    import re
    m = re.search(r"_(\d+)x(\d+)\.bin$", name)
    w, h = int(m.group(1)), int(m.group(2))
    return raw[1024:], w, h


def ink(pix, w, rect, fill_top=2):
    L, T, R, B = rect
    hist = Counter()
    for y in range(T, B):
        hist.update(pix[y * w + L:y * w + R])
    fills = {c for c, _ in hist.most_common(fill_top)}
    rows = {}
    for y in range(T, B):
        xs = [x for x in range(L, R) if pix[y * w + x] not in fills]
        if xs:
            rows[y] = xs
    return rows


def describe(tag, name, rect, text, size_candidates):
    pix, w, h = load(name)
    rows = ink(pix, w, rect)
    if not rows:
        print(tag, "no ink"); return
    ys = sorted(rows)
    # first text line = first contiguous run of rows
    line = [ys[0]]
    for y in ys[1:]:
        if y - line[-1] <= 1:
            line.append(y)
        else:
            break
    x0 = min(min(rows[y]) for y in line); x1 = max(max(rows[y]) for y in line)
    # horizontal run lengths (stems) over the line's rows
    runs = Counter()
    for y in line:
        xs = rows[y]; s = xs[0]; p = xs[0]
        for x in xs[1:] + [None]:
            if x is None or x != p + 1:
                runs[p - s + 1] += 1
                if x is not None:
                    s = x
            if x is not None:
                p = x
    print(f"{tag}: first line rows {line[0]}..{line[-1]} (inkH {len(line)}), ink x {x0}..{x1} = {x1 - x0 + 1}px, "
          f"h-run histogram {sorted(runs.items())[:8]}")
    for size in size_candidates:
        for face, file in FACES.items():
            f = ImageFont.truetype(str(file), size)
            bb = f.getbbox(text)
            print(f"      {face:18s} {size:2d}px: '{text}' ink width {bb[2] - bb[0]:4d}  inkH {bb[3] - bb[1]}")


# faction label, first line (1920: wraps -> "Spartan"; 1600/4K: whole string on one line)
describe("1920 g22 faction", "strip_20260918T232515_2_report1_leave_1408x353.bin", (13, 257, 165, 338), "Spartan", [19, 20])
describe("1600 g25 faction", "strip_20260918T232440_2_report1_leave_1600x401.bin", (15, 291, 189, 384), "Spartan Federation", [21, 22])
describe("4K   g40 faction", "strip_20260918T232346_2_report1_leave_2560x642.bin", (23, 468, 305, 617), "Spartan Federation", [35, 36])
describe("PRISTINE faction", "strip_20260918T222427_2_report1_leave_1024x257.bin", (11, 187, 120, 245), "Morgan Industries", [14])
# stats first line "30-1-1*4"
describe("1920 g22 stats", "strip_20260918T232515_2_report1_leave_1408x353.bin", (533, 105, 697, 124), "30-1-1*4", [16])
describe("1600 g25 stats", "strip_20260918T232440_2_report1_leave_1600x401.bin", (607, 120, 795, 142), "30-1-1*4", [18])
describe("4K   g40 stats", "strip_20260918T232346_2_report1_leave_2560x642.bin", (971, 194, 1270, 230), "30-1-1*4", [30])
describe("PRISTINE stats", "strip_20260918T222427_2_report1_leave_1024x257.bin", (388, 78, 507, 93), "30-1-1*4", [12])
# unit name first line
describe("1920 g22 unit", "strip_20260918T232515_2_report1_leave_1408x353.bin", (369, 202, 533, 228), "Cloaked String", [22])
describe("1600 g25 unit", "strip_20260918T232440_2_report1_leave_1600x401.bin", (419, 230, 607, 259), "Cloaked String", [24, 25])
describe("4K   g40 unit", "strip_20260918T232346_2_report1_leave_2560x642.bin", (672, 369, 971, 416), "Cloaked String", [40])
describe("PRISTINE unit", "strip_20260918T222427_2_report1_leave_1024x257.bin", (269, 148, 388, 168), "Morganic", [16])
