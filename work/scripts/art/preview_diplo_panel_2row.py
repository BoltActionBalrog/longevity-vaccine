"""Preview: the diplomacy BIOSCAN panel backdrop on today's chrome stripe law vs 2-row scanlines (the picture rule).

Takes the user's real diplomacy shots and re-stripes ONLY the backdrop pixels (the two panel colours, recognised as
stripes: the same column holds the other panel colour within 3 rows); the figure, colour bar, thumbnail and text
stay exactly as the game drew them.  The 2-row phase is locked to the BIOSCAN figure's own stripes (measured from
its rows), so the backdrop continues the figure's scanlines.  Output work\\_portrait_preview\\diplo_panel_<WxH>.png:
left = today, right = 2-row; top = the BIOSCAN box at 1:1, bottom = a 4x zoom of the figure's edge.
View PIXEL-EXACT (mspaint at 100%).
"""
from __future__ import annotations

import collections
import pathlib

import numpy as np
from PIL import Image, ImageDraw

WORK = pathlib.Path(__file__).resolve().parents[2]
SHOTS = WORK / "screenshots"
OUT = WORK / "_portrait_preview"
# (shot, BIOSCAN box crop in screen px, zoom box inside the crop)
CASES = [("scanlines_before_20261004/3840x2160/terranx_pracx_3840x2160_20261004-005043.png", (640, 1640, 1260, 2140), (60, 110, 160, 190)),
         ("scanlines_before_20261004/1920x1080/terranx_pracx_1920x1080_20261004-005258.png", (320, 820, 630, 1070), (30, 55, 80, 95))]


def backdrop_colours(a):
    """The two most common colours of the crop (navy + near-black panel stripes)."""
    c = collections.Counter(map(tuple, a.reshape(-1, 3)))
    (c1, _), (c2, _) = c.most_common(2)
    lum = lambda t: 77 * int(t[0]) + 150 * int(t[1]) + 29 * int(t[2])
    return (c1, c2) if lum(c1) > lum(c2) else (c2, c1)          # (bright, dark)


def mask_of(a, bright, dark):
    is_b = np.all(a == bright, axis=-1)
    is_d = np.all(a == dark, axis=-1)
    either = is_b | is_d
    near_b = np.zeros_like(is_b); near_d = np.zeros_like(is_d)
    for k in range(1, 4):
        near_b[:-k] |= is_b[k:]; near_b[k:] |= is_b[:-k]
        near_d[:-k] |= is_d[k:]; near_d[k:] |= is_d[:-k]
    return either & ((is_b & near_d) | (is_d & near_b))


def figure_phase(a, m, y_screen0):
    """Phase phi (0..3) such that screen row y is a BRIGHT figure row iff ((y + phi) // 2) & 1 == 0."""
    lum = a.astype(np.int64) @ np.array([77, 150, 29])
    fig = (~m) & (lum > 3000)
    rows = [(y, lum[y][fig[y]].mean()) for y in range(1, a.shape[0] - 1) if fig[y].sum() >= 20]
    best, bs = 0, -1e18
    for phi in range(4):
        s = sum(v * (1 if (((y_screen0 + y + phi) // 2) & 1) == 0 else -1) for y, v in rows)
        if s > bs:
            best, bs = phi, s
    return best


def label(im, t):
    out = Image.new("RGB", (im.size[0], im.size[1] + 16), (235, 235, 235))
    out.paste(im, (0, 16))
    ImageDraw.Draw(out).text((2, 2), t, fill=(0, 0, 0))
    return out


def main():
    for shot, (x0, y0, x1, y1), (zx0, zy0, zx1, zy1) in CASES:
        a = np.asarray(Image.open(SHOTS / shot).convert("RGB"))[y0:y1, x0:x1].copy()
        bright, dark = backdrop_colours(a)
        m = mask_of(a, bright, dark)
        phi = figure_phase(a, m, y0)
        b = a.copy()
        for y in range(a.shape[0]):
            col = bright if (((y0 + y + phi) // 2) & 1) == 0 else dark
            b[y][m[y]] = col
        ia, ib = Image.fromarray(a), Image.fromarray(b)
        z = lambda im: im.crop((zx0, zy0, zx1, zy1)).resize(((zx1 - zx0) * 4, (zy1 - zy0) * 4), Image.NEAREST)
        top = [label(ia, "today: chrome stripe law"), label(ib, "2-row, phase-locked to the figure")]
        bot = [label(z(ia), "today, 4x"), label(z(ib), "2-row, 4x")]
        W = max(top[0].size[0] * 2, bot[0].size[0] * 2) + 30
        H = top[0].size[1] + bot[0].size[1] + 30
        sheet = Image.new("RGB", (W, H), (255, 255, 255))
        sheet.paste(top[0], (10, 10)); sheet.paste(top[1], (20 + top[0].size[0], 10))
        sheet.paste(bot[0], (10, 20 + top[0].size[1])); sheet.paste(bot[1], (20 + bot[0].size[0], 20 + top[0].size[1]))
        res = pathlib.PurePosixPath(shot).name.split("_")[2]
        p = OUT / f"diplo_panel_{res}.png"
        sheet.save(p)
        print("wrote", p, "backdrop", bright, dark, "phase", phi, "masked px", int(m.sum()))


if __name__ == "__main__":
    main()
