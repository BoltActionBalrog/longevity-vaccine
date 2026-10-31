"""Convert the grand-probe canvas dumps (work\\_rw_dumps\\*.raw, written by hook_report_kinds_proto.js v3) to PNGs.

Each .raw = pitch*h bytes of 8bpp indices (pitch-strided rows) + 1024 bytes RGBQUAD[256] (the buffer's synced DIB
colour table at Buffer+0xA4, BGRA order). Geometry comes from the matching "DUMP <file> w=.. h=.. pitch=.." line in the
Frida log (default work\\frida_report_kinds_proto.log). Usage:

    py scripts/rw_dump_png.py [--log LOG] [--dir _rw_dumps] [--out _rw_dumps/png] [name-substring ...]
"""
import argparse, os, re, sys
from PIL import Image

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(os.path.dirname(__file__), "..", "frida_report_kinds_proto.log"))
    ap.add_argument("--dir", default=os.path.join(os.path.dirname(__file__), "..", "_rw_dumps"))
    ap.add_argument("--out", default=None)
    ap.add_argument("filters", nargs="*")
    a = ap.parse_args()
    out = a.out or os.path.join(a.dir, "png")
    os.makedirs(out, exist_ok=True)
    geom = {}
    with open(a.log, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r"DUMP (\S+\.raw) w=(\d+) h=(\d+) pitch=(\d+) bytes=(\d+)", line)
            if m: geom[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
    n = 0
    for fn in sorted(os.listdir(a.dir)):
        if not fn.endswith(".raw"): continue
        if a.filters and not any(s in fn for s in a.filters): continue
        if fn not in geom: print("no DUMP line for", fn); continue
        w, h, pitch, nbytes = geom[fn]
        data = open(os.path.join(a.dir, fn), "rb").read()
        if len(data) < nbytes + 1024: print("short file", fn, len(data), "<", nbytes + 1024); continue
        pal = data[nbytes:nbytes + 1024]
        rgb = []
        for i in range(256): b, g, r = pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2]; rgb += [r, g, b]
        img = Image.frombytes("P", (pitch, h), data[:nbytes]).crop((0, 0, w, h))
        img.putpalette(rgb)
        dst = os.path.join(out, fn[:-4] + ".png")
        img.convert("RGB").save(dst); n += 1
        print(dst, w, h)
    print(n, "converted")

if __name__ == "__main__":
    main()
