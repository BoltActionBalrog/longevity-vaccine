"""Offline preview of the HYBRID citizen-face enlarge (approved 2026-09-20; law scaling_laws.face_hybrid_enlarge, port
thunk_face_hybrid): photo texels through the thunk_sprite_bilinear law, the face's own baked period-2 scanline
background REGENERATED at device density (membership scaling_laws.face_pair_mate: the hof_pair_texel a/b/a/b chain
plus a run of >= FACE_PAIR_MIN_RUN same-pair texels on the row; wide member = the brighter, hof_pair_top; period /
duty = stripe_period / stripe_top over the DEST rows).  Renders every citizen sprite (newicons.pcx humans,
aliencit.pcx aliens; large 38x48 and small 30x38) at g = 22 / 25 / 40 as NN | bilinear | hybrid, 1:1 and x3, plus a
membership map.  This script holds NO private copy of the law: the hybrid row is face_banding_measure.hybrid_indices
-> SL.face_hybrid_enlarge, drawn at dest row 0 (in game the phase is the dest buffer's row, a pure phase shift).

Run:  py work\\tests\\face_hybrid_preview.py      -> work\\_face_hybrid_preview\\*.png
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import config  # noqa: E402,F401
import scaling_laws as SL  # noqa: E402
import face_banding_measure as FM  # noqa: E402

OUT = ROOT / "_face_hybrid_preview"


def members(cell):
    """Background-membership map of one sprite cell (h x w palette indices): True where face_pair_mate fires."""
    h, w = cell.shape
    flat = cell.reshape(-1).tolist()
    return np.array([[SL.face_pair_mate(flat, w, w, h, x, y, FM.PCX_KEY) is not None for x in range(w)]
                     for y in range(h)])


def main():
    OUT.mkdir(exist_ok=True)
    for label, pcx, x0, y0, pitch, w, h, n in FM.SETS:
        im = Image.open(FM.GAME / pcx)
        pal = np.array(im.getpalette()[:768], float).reshape(256, 3)
        ind = np.array(im)
        used = np.unique(ind)
        table = FM.rgbquad(pal, used)
        rgb_all = np.array(im.convert("RGB"))
        print(f"== {label}")
        for g in (22, 25, 40):
            tiles, stats = [], []
            for i in range(n):
                cell = ind[y0:y0 + h, x0 + i * pitch:x0 + i * pitch + w]
                a = rgb_all[y0:y0 + h, x0 + i * pitch:x0 + i * pitch + w]
                nn = FM.enlarge(a, g, "nn").astype("uint8")
                bil = FM.quantise(FM.enlarge(a, g, "bil"), pal[used]).astype("uint8")
                hyb = pal[FM.hybrid_indices(cell, table, g)].astype("uint8")
                tiles.append((nn, bil, hyb))
                if g == 25:
                    mem = members(cell)
                    stats.append(100.0 * mem.mean())
                    mm = np.where(mem[..., None], np.array([0, 255, 0]), a // 3).astype("uint8")
                    Image.fromarray(mm).resize((w * 4, h * 4), Image.NEAREST).save(OUT / f"members_{label.replace(' ', '_')}_{i:02d}.png")
            th, tw = tiles[0][0].shape[:2]
            sheet = Image.new("RGB", ((tw + 4) * n, (th + 4) * 3), (8, 14, 24))
            for i, trio in enumerate(tiles):
                for r, t in enumerate(trio):
                    sheet.paste(Image.fromarray(t), (i * (tw + 4), r * (th + 4)))
            name = f"{label.replace(' ', '_')}_g{g}"
            sheet.save(OUT / f"{name}_1to1.png")
            sheet.resize((sheet.width * 3, sheet.height * 3), Image.NEAREST).save(OUT / f"{name}_x3.png")
            if g == 25:
                print("   background-member texels per sprite (%):", " ".join(f"{s:.0f}" for s in stats))
    print("rows of each sheet: NN (engine) / bilinear (thunk_sprite_bilinear) / hybrid (thunk_face_hybrid)")


if __name__ == "__main__":
    main()
