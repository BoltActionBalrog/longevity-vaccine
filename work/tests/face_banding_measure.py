"""Offline banding measurement for the citizen faces (BaseWin citizens row / PSYCH rows / F4): enlarge every
citizen sprite with (a) the engine-style NN, (b) the thunk_sprite_bilinear law (scaling_laws.bilinear_axis,
RGB blend -> nearest palette entry) and (c) 'hyb' = the thunk_face_hybrid law (scaling_laws.face_hybrid_enlarge:
bilinear photo + the baked scanline background regenerated at device density) at g = 22 / 25 / 40 and measure, on each sprite's own baked scanline
dither (columns that are a pure 2-row alternation in the native art), how much LOW-frequency energy the
enlarge adds.  A clean enlarge has none (the stripes stay one even texture); banding is a slow beat.

    metric = (spectral energy below half the stripe frequency, DC removed) / (total energy, DC removed)

Run:  py work\\tests\\face_banding_measure.py        (no game launch; reads the game's PCX art)
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

GAME = pathlib.Path(config.game_dir())
SETS = [  # (label, pcx, x0, y0, pitch, w, h, count)
    ("human large", "newicons.pcx", 1, 501, 39, 38, 48, 15),
    ("human small", "newicons.pcx", 44, 458, 31, 30, 38, 15),      # was (45, 459): one px off the cell (a key column inside)
    ("alien large", "aliencit.pcx", 1, 41, 39, 38, 48, 11),
    ("alien small", "aliencit.pcx", 1, 1, 31, 30, 38, 11),
]
PCX_KEY = 255            # the sheets' transparent index (runtime 9 after the loader's +10 shift)
MODES = ("nn", "bil", "hyb")


def lum(rgb):
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def dither_columns(a):
    """Columns + row span where the native art is a pure period-2 alternation with real contrast."""
    L = lum(a.astype(float))
    h, w = L.shape
    out = []
    for x in range(1, w - 1):
        col = L[:, x]
        best = (0, 0)
        y = 1
        while y < h - 3:
            y2 = y
            while y2 + 2 < h - 1 and abs(col[y2] - col[y2 + 2]) < 2 and abs(col[y2] - col[y2 + 1]) > 12:
                y2 += 1
            if y2 - y > best[1] - best[0]:
                best = (y, y2 + 1)
            y = max(y2, y) + 1
        if best[1] - best[0] >= 12:
            out.append((x, best[0], best[1]))
    return out


def enlarge(a, g, mode):
    h, w, _ = a.shape
    H, W = h * g // 16, w * g // 16
    o = np.zeros((H, W, 3), float)
    for dy in range(H):
        if mode == "nn":
            sy = SL.nn_center_index(dy, H, h)
            rowsrc = a[sy].astype(float)
        else:
            i0, i1, f, _ = SL.bilinear_axis(dy, g, 16, h)
            rowsrc = (a[i0].astype(float) * (256 - f) + a[i1].astype(float) * f) / 256
        for dx in range(W):
            if mode == "nn":
                o[dy, dx] = rowsrc[SL.nn_center_index(dx, W, w)]
            else:
                j0, j1, fx, _ = SL.bilinear_axis(dx, g, 16, w)
                o[dy, dx] = (rowsrc[j0] * (256 - fx) + rowsrc[j1] * fx) / 256
    return o


def quantise(o, pal):
    flat = o.reshape(-1, 3)
    d = ((flat[:, None, :] - pal[None, :, :]) ** 2).sum(-1)
    return pal[d.argmin(1)].reshape(o.shape)


def rgbquad(pal, used):
    """The law's dest table (RGBQUAD b,g,r,x) from a PCX palette; entries the sheet never uses take the first
    used colour, so the nearest search only ever lands on the sheet's own colours (as quantise(pal_used))."""
    fill = pal[used[0]]
    isused = set(int(u) for u in used)
    out = bytearray()
    for i in range(256):
        r, g, b = (pal[i] if i in isused else fill)
        out += bytes((int(b), int(g), int(r), 0))
    return bytes(out)


def hybrid_indices(cell, table, g, y_abs=0):
    """scaling_laws.face_hybrid_enlarge of one index cell (h x w) at g/16, drawn at dest row y_abs (the stripe
    phase).  Returns the H x W index image (untouched = key texels -> PCX_KEY)."""
    h, w = cell.shape
    H, W = h * g // 16, w * g // 16
    dst = bytearray([PCX_KEY]) * (W * (H + y_abs))
    SL.face_hybrid_enlarge(cell.reshape(-1).tolist(), w, w, h, 0, 0, table, g, 16, g, dst, W, W, H + y_abs, 0, y_abs, PCX_KEY)
    return np.frombuffer(bytes(dst), np.uint8).reshape(H + y_abs, W)[y_abs:]


def device_col(x, g, w, mode):
    """A device column that SHOWS native column x under the mode's own column map (NN: nn_center_index; bil / hyb:
    bilinear_axis' coverage texel) -- the middle one; the old (x*g)//16 + g//32 guess sampled a neighbouring source
    column at some phases (g=22: x=2 -> device 2 -> native 1)."""
    W = w * g // 16
    if mode == "nn":
        hit = [X for X in range(W) if SL.nn_center_index(X, W, w) == x]
    else:
        hit = [X for X in range(W) if SL.bilinear_axis(X, g, 16, w)[3] == x]
    return hit[len(hit) // 2] if hit else min((x * g) // 16 + g // 32, W - 1)


def low_ratio(sig, stripe_period):
    s = sig - sig.mean()
    F = np.abs(np.fft.rfft(s)) ** 2
    freqs = np.fft.rfftfreq(len(s))
    tot = F[1:].sum()
    return float(F[(freqs > 0) & (freqs < 0.5 / stripe_period)].sum() / tot) if tot > 0 else 0.0


def main():
    rows = []
    member_vals = {}     # (g, mode) -> metric of every column whose whole dither span is BACKGROUND (face_pair_mate)
    for label, pcx, x0, y0, pitch, w, h, n in SETS:
        im = Image.open(GAME / pcx)
        pal = np.array(im.getpalette()[:768], float).reshape(256, 3)
        used = np.unique(np.array(im))
        pal_used = pal[used]
        rgb = np.array(im.convert("RGB"))
        ind = np.array(im)
        table = rgbquad(pal, used)
        for i in range(n):
            a = rgb[y0:y0 + h, x0 + i * pitch:x0 + i * pitch + w]
            cell = ind[y0:y0 + h, x0 + i * pitch:x0 + i * pitch + w]
            cols = dither_columns(a)
            if not cols:
                rows.append((label, i, None))
                continue
            flat = cell.reshape(-1).tolist()
            full = [all(SL.face_pair_mate(flat, w, w, h, x, y, PCX_KEY) is not None for y in range(ya, yb))
                    for x, ya, yb in cols]
            res = {}
            for g in (22, 25, 40):
                for mode in MODES:
                    if mode == "hyb":
                        o = pal[hybrid_indices(cell, table, g)]
                    else:
                        o = enlarge(a, g, mode)
                    if mode == "bil":
                        o = quantise(o, pal_used)
                    L = lum(o)
                    vals = []
                    for x, ya, yb in cols:
                        X = device_col(x, g, w, mode)
                        vals.append(low_ratio(L[ya * g // 16:yb * g // 16, X], 2 * g / 16))
                    member_vals.setdefault((g, mode), []).extend(v for v, f in zip(vals, full) if f)
                    res[(g, mode)] = float(np.mean(vals))
            rows.append((label, i, (len(cols), res)))
    print(f"{'sprite':<16}{'cols':>5}" + "".join(f"{'g%d %s' % (g, m):>10}" for g in (22, 25, 40) for m in ('NN', 'bil', 'hyb')))
    for label, i, r in rows:
        if r is None:
            print(f"{label + ' #' + str(i):<16}{'-':>5}   (no baked scanline dither found)")
            continue
        ncol, res = r
        print(f"{label + ' #' + str(i):<16}{ncol:>5}" + "".join(f"{res[(g, m)]:>10.3f}" for g in (22, 25, 40) for m in MODES))
    for g in (22, 25, 40):
        for m in MODES:
            v = [r[1][(g, m)] for _l, _i, r in rows if r is not None]
            mv = member_vals.get((g, m), [])
            print(f"g{g} {m:<4} all dither columns: mean {np.mean(v):.4f} max {np.max(v):.4f}   |   "
                  f"regenerated (background-member) columns, n={len(mv)}: mean {np.mean(mv):.4f} max {np.max(mv):.4f}")


if __name__ == "__main__":
    main()
