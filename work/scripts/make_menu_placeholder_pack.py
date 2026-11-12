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

    # panorama: stock columns 0..620 enlarged, then a starfield to 2400 units
    W, H = 2400 * K, 768 * K
    pano = Image.new("RGB", (W, H), (0, 0, 0))
    pano.paste(rgb.crop((0, 0, 620, 768)).resize((620 * K, H), Image.LANCZOS), (0, 0))
    px = pano.load()
    rnd = random.Random(1)
    for _ in range(2600):
        x, y = rnd.randrange(620 * K, W), rnd.randrange(H)
        v = rnd.choice((90, 140, 200, 255))
        for dx in range(rnd.choice((1, 1, 2))):
            for dy in range(rnd.choice((1, 1, 2))):
                if x + dx < W and y + dy < H:
                    px[x + dx, y + dy] = (v, v, v)
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
