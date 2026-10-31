"""Preview: every chrome scanline surface of a real screenshot re-striped to even 2-row scanlines (option B).

Law-free detection, per screen column: a CHAIN = >= MIN_RUNS consecutive vertical runs alternating between exactly
two colours, every run <= P + 1 rows (P = today's chrome period (g + 4) >> 3), with an UNEVEN duty (the wide member's
runs are longer than the narrow member's).  Even chains are left alone: 2/2 = pictures already on the 2-row rule,
1/1 = the faction-button / council-flag parity surfaces (not part of this change).  Every pixel of a chain is rewritten
to the wide member on rows ((y // T) & 1) == 0 and the narrow member elsewhere, T = art_scan_rows(g).

The phase here is the SCREEN row (the shipped law counts from each dest buffer's row 0, which a screenshot does not
carry), so stripes of two different windows may sit one row off from what the game will draw; thickness, duty and
colours are exact.  Output work\\_portrait_preview\\chrome_2row\\<shot>_2row.png (full frame, 1:1) and
<shot>_pair.png (today | 2-row crops of the densest striped area at 1:1).  View PIXEL-EXACT (mspaint at 100%).

    py art\\preview_chrome_2row.py <shot.png> [...]      (names resolve against work\\screenshots)
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import scaling_laws as SL  # noqa: E402

WORK = pathlib.Path(__file__).resolve().parents[2]
SHOTS = WORK / "screenshots"
OUT = WORK / "_portrait_preview" / "chrome_2row"
MIN_RUNS = 4
CROP = (900, 600)


def screen_g(h: int) -> int:
    return max(16, min(40, 16 * h // 768))


def restripe_column(col: np.ndarray, p_old: int, t: int, out: np.ndarray) -> int:
    """col = packed 0xRRGGBB per row; rewrites `out` (same shape) in place, returns pixels changed."""
    n = len(col)
    cut = np.flatnonzero(np.diff(col)) + 1
    starts = np.concatenate(([0], cut))
    lens = np.diff(np.concatenate((starts, [n])))
    vals = col[starts]
    nr = len(starts)
    changed = 0
    i = 0
    while i < nr:
        if lens[i] > p_old + 1:
            i += 1
            continue
        a, b, j = int(vals[i]), -1, i
        while j < nr and lens[j] <= p_old + 1:
            v = int(vals[j])
            if v != a:
                if b < 0:
                    b = v
                elif v != b:
                    break
            j += 1
        if b >= 0 and j - i >= MIN_RUNS:
            # interior runs only decide the duty (the chain's first / last run may be cut by a neighbour)
            la = [int(lens[k]) for k in range(i + 1, j - 1) if int(vals[k]) == a]
            lb = [int(lens[k]) for k in range(i + 1, j - 1) if int(vals[k]) == b]
            if la and lb and max(la) != max(lb):
                wide, narrow = (a, b) if max(la) > max(lb) else (b, a)
                y0, y1 = int(starts[i]), int(starts[j - 1] + lens[j - 1])
                ys = np.arange(y0, y1)
                new = np.where(((ys // t) & 1) == 0, wide, narrow)
                changed += int((out[y0:y1] != new).sum())
                out[y0:y1] = new
            i = j
        else:
            i += 1
    return changed


def label(im: Image.Image, text: str) -> Image.Image:
    o = Image.new("RGB", (im.size[0], im.size[1] + 16), (235, 235, 235))
    o.paste(im, (0, 16))
    ImageDraw.Draw(o).text((2, 2), text, fill=(0, 0, 0))
    return o


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    for name in argv:
        p = pathlib.Path(name)
        if not p.exists():
            p = SHOTS / name
        rgb = np.asarray(Image.open(p).convert("RGB")).astype(np.uint32)
        h, w = rgb.shape[:2]
        g = screen_g(h)
        if g <= 16:
            print(p.name, "native g: nothing to do")
            continue
        p_old, t = (g + 4) >> 3, SL.art_scan_rows(g)
        packed = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
        new = packed.copy()
        total = 0
        for x in range(w):
            col_out = new[:, x].copy()
            total += restripe_column(packed[:, x], p_old, t, col_out)
            new[:, x] = col_out
        out = np.stack(((new >> 16) & 255, (new >> 8) & 255, new & 255), axis=-1).astype(np.uint8)
        Image.fromarray(out).save(OUT / f"{p.stem}_2row.png")
        # densest changed area -> side-by-side crop
        diff = (new != packed).astype(np.int64)
        cw, ch = min(CROP[0], w), min(CROP[1], h)
        ii = np.pad(diff.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        best, bx, by = -1, 0, 0
        for y in range(0, h - ch + 1, 40):
            for x in range(0, w - cw + 1, 40):
                s = ii[y + ch, x + cw] - ii[y, x + cw] - ii[y + ch, x] + ii[y, x]
                if s > best:
                    best, bx, by = s, x, y
        box = (bx, by, bx + cw, by + ch)
        a = label(Image.fromarray(rgb.astype(np.uint8)).crop(box), f"today (period {p_old})")
        b = label(Image.fromarray(out).crop(box), f"2-row scanlines (g={g})")
        sheet = Image.new("RGB", (a.size[0] * 2 + 30, a.size[1] + 20), (255, 255, 255))
        sheet.paste(a, (10, 10))
        sheet.paste(b, (20 + a.size[0], 10))
        sheet.save(OUT / f"{p.stem}_pair.png")
        print(f"{p.name}: g={g} period {p_old} -> T={t}; {total} px rewritten ({100.0 * total / (w * h):.1f}%); crop {box}")


if __name__ == "__main__":
    main(sys.argv[1:])
