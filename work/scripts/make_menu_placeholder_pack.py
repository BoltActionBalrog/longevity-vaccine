"""A placeholder pack for the HD main menu (src/uimod/src/menuhd.cpp), built from the player's own game files: smooth
3x enlargements of the stock opening, planet strips and moons, quantized to the stock xopeninga palette (indices
0..235), in the layout menuhd reads. It exercises the hook at any resolution without an art pack.

Usage: python make_menu_placeholder_pack.py <game dir> [<out dir>]   (default out: <game>\\menu\\hd)   needs Pillow + numpy
Writes space_x3.pcx (the stock left part + a generated starfield), the 27 S#L#C#_x3.pcx and moon1..3_x3.pcx, plus
PLACEHOLDER.txt so nobody mistakes them for real art.
"""
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

K = 3


def pal_image(pal):
    p = Image.new("P", (1, 1))
    p.putpalette(pal[:236 * 3] + pal[:3] * 20)      # only 0..235 usable; pad by repeating entry 0
    return p


def quant(rgb, pimg):
    q = np.array(rgb.quantize(palette=pimg, dither=Image.Dither.FLOYDSTEINBERG))
    return np.minimum(q, 235).astype(np.uint8)


def save(idx, pal, path):
    im = Image.fromarray(idx, "P")
    im.putpalette(pal)
    im.save(path)


def main():
    game = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else game / "menu" / "hd"
    out.mkdir(parents=True, exist_ok=True)
    stock = Image.open(game / ("xopeninga.pcx.orig" if (game / "xopeninga.pcx.orig").exists() else "xopeninga.pcx"))
    pal = stock.getpalette()[:768]
    pimg = pal_image(pal)
    rgb = stock.convert("RGB")

    # panorama: the stock columns 0..620, then a starfield to 2400 units made at 1x like the stock sky (its star
    # density, and star colours taken from its own stars), and the whole enlarged the same way, so the seam vanishes
    src = np.array(rgb).astype(np.uint8)
    lum = src.astype(int).mean(2)
    # clean sky only (no suns' glow, no logo): right of the glow, left of the logo, under it
    patches = [(460, 0, 620, 330), (0, 330, 90, 690), (0, 700, 620, 740)]
    star_px = np.concatenate([src[y0:y1, x0:x1][lum[y0:y1, x0:x1] > 35] for x0, y0, x1, y1 in patches])
    density = sum((lum[y0:y1, x0:x1] > 35).sum() for x0, y0, x1, y1 in patches) / \
        sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in patches)
    W1, H1 = 2400, 768
    one = np.zeros((H1, W1, 3), np.uint8)
    one[:, :620] = src[:, :620]
    rnd = random.Random(1)
    n = int(density * (W1 - 620) * H1)
    for _ in range(n):
        x, y = rnd.randrange(620, W1), rnd.randrange(H1)
        one[y, x] = star_px[rnd.randrange(len(star_px))]
        if rnd.random() < 0.12 and x + 1 < W1:           # a few stars are two pixels wide, as in the stock sky
            one[y, x + 1] = one[y, x] // 2
    pano = Image.fromarray(one).resize((W1 * K, H1 * K), Image.LANCZOS)
    save(quant(pano, pimg), pal, out / "space_x3.pcx")

    for s in (1, 2, 3):
        for l in (1, 2, 3):
            for c in (1, 2, 3):
                n = f"S{s}L{l}C{c}"
                im = Image.open(game / f"{n}.pcx").convert("RGB").resize((404 * K, 768 * K), Image.LANCZOS)
                save(quant(im, pimg), pal, out / f"{n}_x3.pcx")

    for m in (1, 2, 3):
        src = Image.open(game / f"moon{m}.pcx")
        idx = np.array(src)
        key = idx == 255
        rgbm = np.array(src.convert("RGB"))
        rgbm[key] = 0                                   # no magenta in the colours: dithering would smear it into the edges
        col = np.minimum(np.array(Image.fromarray(rgbm).quantize(palette=pimg, dither=Image.Dither.NONE)), 235).astype(np.uint8)
        col[key] = 255
        big = np.repeat(np.repeat(col, K, 0), K, 1)
        save(big, pal, out / f"moon{m}_x3.pcx")

    (out / "PLACEHOLDER.txt").write_text("Placeholder art made by smac_menu_placeholder.py from the stock pictures. "
                                         "Replace with a real art pack.\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
