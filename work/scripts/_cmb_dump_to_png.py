"""Render hook_combat_geom.js strip-buffer dumps (work\\_cmb_probe\\strip_*.bin) to PNG.

Dump layout: 1024 bytes PALETTEENTRY[256] (r,g,b,flags) + w*h 8bpp rows; w/h are in the
file name (..._<W>x<H>.bin). Writes <name>.png next to each dump (skips existing).
Usage: py scripts\\_cmb_dump_to_png.py [dir]
"""
import pathlib
import re
import sys

from PIL import Image

d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent / "_cmb_probe")
for f in sorted(d.glob("strip_*.bin")):
    out = f.with_suffix(".png")
    if out.exists():
        continue
    m = re.search(r"_(\d+)x(\d+)\.bin$", f.name)
    w, h = int(m.group(1)), int(m.group(2))
    raw = f.read_bytes()
    pal, pix = raw[:1024], raw[1024:]
    assert len(pix) == w * h, (f.name, len(pix), w * h)
    im = Image.frombytes("P", (w, h), pix)
    im.putpalette(b"".join(pal[i * 4:i * 4 + 3] for i in range(256)))
    im.save(out)
    print("wrote", out.name)
