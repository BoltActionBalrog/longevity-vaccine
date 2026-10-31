"""Preview sheet: the patcher's art re-blit (thunk_art_reblit / thunk_parity_reblit) v1 (scanlines 1 device row)
vs v2 (art_reblit_row: the popup pictures' art_scan_rows(num, den)-row scanlines), plus a vanilla native-life face
v1 (the patcher re-blit, today) vs the leaders' smooth enlarge (portrait_enlarge, the DLL's new path for them).

Rows: Btwrm.pcx (mind worm, combat console), ac_logo_sm.pcx (version logo), dip_m_0.flc frame 0 (BIOSCAN figure
art), each at g = 22 / 25 / 40, full size + a 1:1 crop.  View PIXEL-EXACT (mspaint at 100%), never Photos.
Output: work\\_portrait_preview\\reblit_v2_g<g>.png (gitignored).   py art\\preview_reblit_v2.py
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

OUT = WORK / "_portrait_preview"


def v1_row(j, sh, num, den=16):
    """art_reblit_row as shipped before 2026-10-04 (pair-granular, 1-row alternation)."""
    c = SL.nn_center_index(j, (sh * num) // den, sh)
    if c <= 0 or c >= sh - 1 or sh < 4:
        return max(c, 0)
    r = 2 * (((2 * j + 1) * den) // (4 * num)) + (j & 1)
    while r < 1:
        r += 2
    while r > sh - 2:
        r -= 2
    return r


def reblit(src, sw, sh, key, num, row_fn):
    dw, dh = (sw * num) // 16, (sh * num) // 16
    out = bytearray([0] * (dw * dh))
    for j in range(dh):
        r = row_fn(j, sh, num)
        for i in range(dw):
            v = src[r * sw + SL.art_reblit_col(i, sw, num)]
            out[j * dw + i] = 0 if v == key else v
    return out, dw, dh


def to_img(idx, w, h, pal_rgb):
    im = Image.frombytes("P", (w, h), bytes(idx))
    im.putpalette(pal_rgb)
    return im.convert("RGB")


def label(im, t):
    out = Image.new("RGB", (max(im.size[0], 6 * len(t) + 6), im.size[1] + 16), (235, 235, 235))
    out.paste(im, (0, 16))
    ImageDraw.Draw(out).text((2, 2), t, fill=(0, 0, 0))
    return out


def hstack(cells, gap=8):
    w = sum(c.size[0] for c in cells) + gap * (len(cells) + 1)
    h = max(c.size[1] for c in cells) + 2 * gap
    out = Image.new("RGB", (w, h), (255, 255, 255))
    x = gap
    for c in cells:
        out.paste(c, (x, gap)); x += c.size[0] + gap
    return out


def vstack(rows):
    out = Image.new("RGB", (max(r.size[0] for r in rows), sum(r.size[1] for r in rows)), (255, 255, 255))
    y = 0
    for r in rows:
        out.paste(r, (0, y)); y += r.size[1]
    return out


def load(name):
    im = Image.open(config.game_dir() / name)
    im.seek(0)
    return im.convert("P") if im.mode != "P" else im


def main():
    gd = config.game_dir()
    arts = []
    wrm = load("Btwrm.pcx")
    arts.append(("mind worm (native life)", wrm, True))
    arts.append(("version logo", load("ac_logo_sm.pcx"), False))
    if (gd / "dip_m_0.flc").exists():
        arts.append(("BIOSCAN figure (dip_m_0.flc)", load("dip_m_0.flc"), False))
    for g in (22, 25, 40):
        rows = []
        for name, im, portrait in arts:
            sw, sh = im.size
            pal = im.getpalette()[:768]
            src = im.tobytes()
            a, dw, dh = reblit(src, sw, sh, -1, g, v1_row)
            b, _, _ = reblit(src, sw, sh, -1, g, SL.art_reblit_row)
            cells = [label(to_img(a, dw, dh, pal), f"{name}: today (1 row)")]
            if portrait:
                # the engine's view: stored index = raw + 10 (Buffer_load_pcx), key 9
                gpal = [0] * 768
                for i in range(256):
                    gpal[i * 3:i * 3 + 3] = pal[((i - 10) % 256) * 3:((i - 10) % 256) * 3 + 3]
                rq = bytearray(1024)
                for i in range(256):
                    rq[i * 4], rq[i * 4 + 1], rq[i * 4 + 2] = gpal[i * 3 + 2], gpal[i * 3 + 1], gpal[i * 3]
                gsrc = bytes((v + 10) & 0xFF for v in src)
                ew, eh, er = SL.portrait_enlarge(gsrc, sw, sw, sh, 9, bytes(rq), g)
                flat = bytearray(v if v is not None else 0 for r in er for v in r)
                cells.append(label(to_img(flat, ew, eh, gpal), "new: leaders' smooth enlarge (2 rows)"))
            else:
                cells.append(label(to_img(b, dw, dh, pal), "new: re-blit v2 (2 rows)"))
            big = [c for c in cells]
            crops = []
            for c in big:
                w, h = c.size
                crops.append(c.crop((w // 4, 16 + (h - 16) // 4, w // 4 + min(160, w // 2), 16 + (h - 16) // 4 + min(120, (h - 16) // 2))))
            rows.append(hstack(big + [label(x, "1:1 crop") for x in crops]))
        p = OUT / f"reblit_v2_g{g}.png"
        vstack(rows).save(p)
        print("wrote", p)


if __name__ == "__main__":
    main()
