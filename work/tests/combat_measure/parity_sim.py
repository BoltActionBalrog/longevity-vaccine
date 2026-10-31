"""Run the council parity re-blit port (proven == thunk bytes) on the REAL portrait pixels lifted from the
pristine strip dump, at g=22/25/40, and measure scanline regularity; also save before/after PNGs."""
import pathlib
import re
import sys
from collections import Counter

sys.path.insert(0, r"D:\SmacxUi\work\tests")
sys.path.insert(0, r"D:\SmacxUi\work\scripts")
import test_council_asm_parity as TC
from PIL import Image

S = pathlib.Path(__file__).resolve().parent
P = pathlib.Path(r"D:\SmacxUi\work\_cmb_probe")
f = next(P.glob("strip_20260918T222427_*_report1_leave_*.bin"))
raw = f.read_bytes(); pal = raw[:1024]; pix = raw[1024:]; W = 1024
palette = b"".join(pal[i * 4:i * 4 + 3] for i in range(256))
lumv = [0.3 * pal[i * 4] + 0.59 * pal[i * 4 + 1] + 0.11 * pal[i * 4 + 2] for i in range(256)]


def rle(seq):
    out, i = [], 0
    while i < len(seq):
        j = i
        while j < len(seq) and seq[j] == seq[i]:
            j += 1
        out.append(j - i); i = j
    return out


def regularity(buf, w, h):
    lum = [sum(lumv[c] for c in buf[y * w:(y + 1) * w]) / w for y in range(h)]
    sign = [1 if lum[i] > (lum[i - 1] + lum[i + 1]) / 2 else 0 for i in range(1, h - 1)]
    return dict(sorted(Counter(rle(sign)).items()))


for name, (px, py) in {"morgan": (17, 69), "spartan": (135, 69)}.items():
    sw, sh = 96, 115
    src = bytes(b for y in range(sh) for b in pix[(py + y) * W + px:(py + y) * W + px + sw])
    print(f"{name}: native {regularity(src, sw, sh)}")
    for g in (22, 25, 40):
        dw, dh = sw * g // 16, sh * g // 16
        # plain NN (what the bezel thunk gave): centre-aligned is irrelevant for the run statistic; floor map
        nn = bytes(src[(y * sh // dh) * sw + (x * sw // dw)] for y in range(dh) for x in range(dw))
        before = bytes([0xEE]) * (dw * dh)
        out = TC.py_parity_reblit(before, dw, dh, dw, src, sw, sh, sw, 9, 0, 0, 0, 0, g, 16)
        print(f"   g={g} {dw}x{dh}: plain NN {regularity(nn, dw, dh)}  |  parity re-blit {regularity(out, dw, dh)}  untouched px {out.count(0xEE)}")
        for tag, b in (("nn", nn), ("parity", out)):
            im = Image.frombytes("P", (dw, dh), bytes(b)); im.putpalette(palette)
            im.save(S / f"sim_{name}_g{g}_{tag}.png")
