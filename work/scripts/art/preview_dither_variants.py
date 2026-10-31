"""Preview sheet: the replacement-portrait colour step under candidate settings (audit findings F1 / F2, 2026-10-03).

  A  today        error diffusion 85% (PORTRAIT_DITHER_Q8 = 218), error terms floor-shifted (>> rounds toward -inf)
  B  F1 only      85%, error terms rounded to nearest
  C  F1 + 95%     rounded, 95% diffusion
  D  F1 + 100%    rounded, full diffusion

Everything before the colour step is the law (scaling_laws: portrait_frame_rect, the Lanczos taps, portrait_scan_rows),
so the variants differ ONLY in the dither.  Renders the datalink interior at the 4K size (g = 40) from the HD pack
images, with "bright" scanlines (MEAN) and with scanlines off, plus 4x crops and the measured mean colour shift vs the
source (no palette).  Output: work\\_portrait_preview\\hd\\dither_variants_*.png + dither_variants.txt (gitignored).

    py art\\preview_dither_variants.py --palette ..\\_portrait_preview\\hd\\game_palette_rgbquad.bin
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

OUT = WORK / "_portrait_preview" / "hd"
PACK = WORK.parent / "dist" / "portraits-hd"
G = 40
DL = (531, 1, 164, 198)                         # the datalink slot incl. its frame
VARIANTS = [("A today (85%, floor)", 218, False), ("B F1: rounded, 85%", 218, True),
            ("C F1 + 95%", 243, True), ("D F1 + 100%", 256, True)]
FACES = {"hive": "Yang (white hair)", "morgan": "Morgan", "peace": "Lal", "gaians": "Deirdre (skin)",
         "spartans": "Santiago"}


def shr(v: int, n: int, rounded: bool) -> int:
    """v / 2**n: floor (today's >>) or round-half-away-from-zero (symmetric)."""
    if not rounded:
        return v >> n
    h = 1 << (n - 1)
    return (v + h) >> n if v >= 0 else -((-v + h) >> n)


def dither(big, pal, q8: int, rounded: bool):
    th, tw, _ = big.shape
    cand = np.arange(SL.PORTRAIT_PAL_LO, SL.PORTRAIT_PAL_HI + 1)
    pr = np.array([pal[i * 4 + 2] for i in cand], dtype=np.int64)
    pg = np.array([pal[i * 4 + 1] for i in cand], dtype=np.int64)
    pb = np.array([pal[i * 4] for i in cand], dtype=np.int64)
    wr, wg, wb = SL.PORTRAIT_DIST_WEIGHTS
    acc = big.astype(np.int64).tolist()
    out = np.zeros((th, tw, 3), dtype=np.uint8)
    for y in range(th):
        dx = 1 if (y & 1) == 0 else -1
        for x in (range(tw) if dx == 1 else range(tw - 1, -1, -1)):
            r, g_, b = (min(255, max(0, v)) for v in acc[y][x])
            k = int(np.argmin(wr * (pr - r) ** 2 + wg * (pg - g_) ** 2 + wb * (pb - b) ** 2))
            out[y, x] = (pr[k], pg[k], pb[k])
            err = (shr((r - int(pr[k])) * q8, 8, rounded), shr((g_ - int(pg[k])) * q8, 8, rounded),
                   shr((b - int(pb[k])) * q8, 8, rounded))
            for ox, oy, kk in ((dx, 0, 7), (-dx, 1, 3), (0, 1, 5), (dx, 1, 1)):
                xx, yy = x + ox, y + oy
                if 0 <= xx < tw and yy < th:
                    for c in range(3):
                        acc[yy][xx][c] += shr(err[c] * kk, 4, rounded)
    return out


def resampled(fac, tw, th):
    """The law's Lanczos stage for the pack image, cropped like the DLL (cover crop to the native interior)."""
    im = Image.open(PACK / f"{fac}.png").convert("RGB")
    rgb, w, h = SL.portrait_prereduce(im.tobytes(), im.size[0], im.size[1])
    cx, cy, cw, ch = SL.portrait_frame_rect(w, h, DL[2] - 2, DL[3] - 2)
    a = np.frombuffer(rgb, dtype=np.uint8).reshape(h, w, 3)[cy:cy + ch, cx:cx + cw].astype(np.int64)
    half = 1 << (SL.PORTRAIT_WEIGHT_Q - 1)
    mx, my = SL._portrait_weight_matrix(cw, tw), SL._portrait_weight_matrix(ch, th)
    hor = np.stack([np.clip((a[:, :, c] @ mx.T + half) >> SL.PORTRAIT_WEIGHT_Q, 0, 255) for c in range(3)], -1)
    return np.stack([np.clip((my @ hor[:, :, c] + half) >> SL.PORTRAIT_WEIGHT_Q, 0, 255) for c in range(3)], -1)


def vanilla_params(fac, pal):
    sheet = Image.open(config.game_dir() / f"{fac}.pcx")
    x, y, w, h = DL
    src = bytes((v + 10) & 0xFF for v in sheet.crop((x, y, x + w, y + h)).tobytes())
    return SL.portrait_scanline_params(src, w, w, h, pal)


def label(im, text):
    out = Image.new("RGB", (im.size[0], im.size[1] + 18), (235, 235, 235))
    out.paste(im, (0, 18))
    ImageDraw.Draw(out).text((3, 3), text, fill=(0, 0, 0))
    return out


def row(cells, gap=8):
    w = sum(c.size[0] for c in cells) + gap * (len(cells) + 1)
    h = max(c.size[1] for c in cells) + 2 * gap
    out = Image.new("RGB", (w, h), (255, 255, 255))
    x = gap
    for c in cells:
        out.paste(c, (x, gap)); x += c.size[0] + gap
    return out


def stack(rows):
    w = max(r.size[0] for r in rows)
    out = Image.new("RGB", (w, sum(r.size[1] for r in rows)), (255, 255, 255))
    y = 0
    for r in rows:
        out.paste(r, (0, y)); y += r.size[1]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--palette", required=True, type=pathlib.Path)
    a = ap.parse_args()
    pal = a.palette.read_bytes()
    tw, th = (DL[2] - 2) * G // 16, (DL[3] - 2) * G // 16
    report = []
    for mode, mname in ((SL.PORTRAIT_SCAN_MEAN, "bright"), (SL.PORTRAIT_SCAN_OFF, "off")):
        rows, zrows = [], []
        for fac, who in FACES.items():
            base = resampled(fac, tw, th)
            bright, ratio = vanilla_params(fac, pal)
            scanned = base.copy()
            SL.portrait_scan_rows(scanned, th, mode, bright, ratio, 0)
            cells, zooms = [label(Image.fromarray(base.astype(np.uint8)), f"{who}: source (no palette)")], []
            box = (tw // 4, th // 10, tw // 4 + 90, th // 10 + 70)       # upper face / hair
            zooms.append(label(Image.fromarray(scanned.astype(np.uint8)).crop(box).resize((360, 280), Image.NEAREST),
                               "source 4x"))
            for name, q8, rnd in VARIANTS:
                d = dither(scanned, pal, q8, rnd)
                m = d.reshape(-1, 3).mean(0) - scanned.reshape(-1, 3).clip(0, 255).mean(0)
                neu = (base.max(-1) - base.min(-1) < 12) & (base.min(-1) > 150)        # bright neutrals
                tint = (d[neu][:, 1].astype(float) - (d[neu][:, 0].astype(float) + d[neu][:, 2]) / 2).mean() \
                    if neu.any() else float("nan")
                src_tint = (base[neu][:, 1] - (base[neu][:, 0] + base[neu][:, 2]) / 2).mean() if neu.any() else float("nan")
                report.append(f"{mname:6s} {fac:9s} {name:22s} mean shift R{m[0]:+5.1f} G{m[1]:+5.1f} B{m[2]:+5.1f}"
                              f"   bright-neutral green excess {tint:+5.1f} (source {src_tint:+5.1f}, n={int(neu.sum())})")
                cells.append(label(Image.fromarray(d), name))
                zooms.append(label(Image.fromarray(d).crop(box).resize((360, 280), Image.NEAREST), name + " 4x"))
            rows.append(row(cells))
            zrows.append(row(zooms))
            print(f"{mname} {fac} done", flush=True)
        stack(rows).save(OUT / f"dither_variants_{mname}.png")
        stack(zrows).save(OUT / f"dither_variants_{mname}_zoom4x.png")
    (OUT / "dither_variants.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
