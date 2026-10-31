"""Preview sheets for replacement leader / native-life portraits (the Phase-1 sign-off gate).

Renders with the uimod C++ port (portrait_law.h, proven bit-exact against scaling_laws by
tests\\test_portrait_rgb_port.py / test_portrait_port.py, built with the DLL's release codegen) because the Python
law is too slow for hundreds of renders.  Inputs: the HD source PNGs (dist\\portraits-hd-src), the game's faction
sheets, and the game palette as the engine holds it: the 1024-byte RGBQUAD table dumped by the Phase-0 probe
work\\scripts\\hook_portrait_palette.js (its `PAL 0x...` line for a portrait dest).  That dump is game data: it stays
in the gitignored output folder.  Output: work\\_portrait_preview\\hd\\ (gitignored: third-party art).

    py art\\preview_replacement_portraits.py --palette ..\\_portrait_preview\\hd\\game_palette_rgbquad.bin
    py art\\preview_replacement_portraits.py --palette ... --only "" --composite <4K screenshot> [--replace-only a,b]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(WORK / "tests"))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402
import build_portraits_hd as PACK  # noqa: E402
import cpp_harness  # noqa: E402

OUT = WORK / "_portrait_preview" / "hd"
LEADERS = PACK.LEADERS
#: slot -> (x, y, w, h) incl. the 1-px frame, identical on every sheet (load_faction_art's Sprite_extract_2 rects)
SLOTS = {"smallcouncil": (88, 457, 96, 115), "bigcouncil": (185, 457, 118, 144),
         "diplomacy": (304, 457, 131, 157), "datalink": (531, 1, 164, 198)}
KEY = 9                          # Buffer_load_pcx stores (raw + 10) & 0xFF: raw magenta 255 -> 9
OVERLAY, MEAN, OFF = SL.PORTRAIT_SCAN_OVERLAY, SL.PORTRAIT_SCAN_MEAN, SL.PORTRAIT_SCAN_OFF
MODES = [(OVERLAY, "HD scanlines (vanilla model)"), (MEAN, "HD scanlines (brightness kept)"), (OFF, "HD clean")]


class Port:
    def __init__(self):
        self.rgb_exe = cpp_harness.build(WORK / "tests" / "portrait_rgb_selftest.cpp", "pv_rgb_", "/Oi /GL")
        self.van_exe = cpp_harness.build(WORK / "tests" / "portrait_selftest.cpp", "pv_van_", "/Oi /GL")

    @staticmethod
    def _run(exe, blob):
        with tempfile.TemporaryDirectory(prefix="pvio_") as t:   # holds art pixels: never left behind
            d = pathlib.Path(t)
            (d / "i").write_bytes(blob)
            subprocess.run([str(exe), str(d / "i"), str(d / "o")], check=True)
            return (d / "o").read_bytes()

    def bake(self, src, sw, sh, pal, rgb, w, h, scan):
        raw = self._run(self.rgb_exe, struct.pack("<11i", 2, sw, sh, sw, KEY, 16, 16, w, h, scan, 0) + pal + src + rgb)
        vals = struct.unpack_from(f"<{(sw - 2) * (sh - 2)}i", raw, 12)
        out = [list(src[y * sw:(y + 1) * sw]) for y in range(sh)]            # frame from the art
        for y in range(sh - 2):
            out[y + 1][1:sw - 1] = vals[y * (sw - 2):(y + 1) * (sw - 2)]
        return sw, sh, [[None if v == KEY else v for v in r] for r in out]

    def enlarge_rgb(self, src, sw, sh, pal, rgb, w, h, scan, g):
        raw = self._run(self.rgb_exe, struct.pack("<11i", 3, sw, sh, sw, KEY, g, 16, w, h, scan, 0) + pal + src + rgb)
        return self._grid(raw)

    def enlarge_vanilla(self, src, sw, sh, pal, g):
        return self._grid(self._run(self.van_exe, struct.pack("<7i", sw, sh, sw, KEY, g, 16, 0) + pal + src))

    @staticmethod
    def _grid(raw):
        ok, dw, dh = struct.unpack_from("<3i", raw)
        if not ok:
            return None
        vals = struct.unpack_from(f"<{dw * dh}i", raw, 12)
        return dw, dh, [[None if v < 0 else v for v in vals[j * dw:(j + 1) * dw]] for j in range(dh)]


def to_image(grid, pal, bg=(24, 24, 28)):
    dw, dh, rows = grid
    im = Image.new("RGB", (dw, dh), bg)
    px = im.load()
    for j, r in enumerate(rows):
        for i, v in enumerate(r):
            if v is not None:
                px[i, j] = (pal[v * 4 + 2], pal[v * 4 + 1], pal[v * 4])
    return im


def native(src, sw, sh):
    return sw, sh, [[None if v == KEY else v for v in src[y * sw:(y + 1) * sw]] for y in range(sh)]


def slot_pixels(fac, slot):
    """A slot in the ENGINE's index space (the game palette's)."""
    x, y, w, h = SLOTS[slot]
    raw = Image.open(config.game_dir() / f"{fac}.pcx").crop((x, y, x + w, y + h)).tobytes()
    return bytes((v + 10) & 0xFF for v in raw), w, h


def pack_crops():
    """faction -> the builder's registered crop, cached (registration takes ~20 s)."""
    cache = OUT / "pack_crops.json"
    if cache.is_file():
        return {k: tuple(v) for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    crops = {fac: crop for _, fac, _, crop, _, _ in PACK.plan(PACK.DEFAULT_SRC)}
    cache.write_text(json.dumps(crops), encoding="utf-8")
    return crops


def hd_image(n, crop=None):
    im = Image.open(PACK.source_path(PACK.DEFAULT_SRC, n)).convert("RGB")
    if crop:
        x, y, w, h = crop
        im = im.crop((x, y, x + w, y + h))
    return SL.portrait_prereduce(im.tobytes(), im.size[0], im.size[1])


def mean_luma(im):
    px = list(im.convert("L").getdata())
    return sum(px) / len(px)


def alternation(grid, pal):
    """Fraction of interior device rows whose luma is a strict local max/min (1.0 = perfect 1-px scanlines)."""
    dw, dh, rows = grid
    lum = []
    for r in rows[3:-3]:
        v = [77 * pal[p * 4 + 2] + 150 * pal[p * 4 + 1] + 29 * pal[p * 4] for p in r[3:-3] if p is not None]
        lum.append(sum(v) / max(len(v), 1))
    ups = [lum[i] > (lum[i - 1] + lum[i + 1]) / 2 for i in range(1, len(lum) - 1)]
    return sum(ups[i] != ups[i + 1] for i in range(len(ups) - 1)) / max(len(ups) - 1, 1)


def labelled_row(cells, labels, title=None, gap=8, top=30):
    w = sum(c.size[0] for c in cells) + gap * (len(cells) + 1)
    h = max(c.size[1] for c in cells) + top + gap
    im = Image.new("RGB", (w, h), (235, 235, 235))
    d = ImageDraw.Draw(im)
    if title:
        d.text((gap, 2), title, fill=(0, 0, 0))
    x = gap
    for c, t in zip(cells, labels):
        im.paste(c, (x, top))
        d.text((x, top - 12), t[: max(4, c.size[0] // 6)], fill=(60, 60, 60))    # clipped to the cell width
        x += c.size[0] + gap
    return im


def stack(rows, gap=4):
    w = max(r.size[0] for r in rows)
    im = Image.new("RGB", (w, sum(r.size[1] for r in rows) + gap * len(rows)), (255, 255, 255))
    y = 0
    for r in rows:
        im.paste(r, (0, y)); y += r.size[1] + gap
    return im


def composite(port, pal, hd, shot, g, scan, replace_only=None, tag=""):
    """Find each leader portrait of today's build in a screenshot, pixel-exact (vanilla smooth enlarge at g), and
    paste the HD version over it (only the factions in replace_only, if given).  Returns report lines."""
    import numpy as np
    img = Image.open(shot).convert("RGB")
    a = np.asarray(img)
    rows_bytes = [a[y].tobytes() for y in range(a.shape[0])]
    after = img.copy()
    found = []
    for n, fac in LEADERS.items():
        rgb, w, h = hd[n]
        for slot in SLOTS:
            src, sw, sh = slot_pixels(fac, slot)
            van = port.enlarge_vanilla(src, sw, sh, pal, g)
            if van is None:
                continue
            dw, dh, vr = van
            j = dh // 2
            seg = vr[j][dw // 4: dw // 4 + 48]
            if any(v is None for v in seg):
                continue
            needle = b"".join(bytes((pal[v * 4 + 2], pal[v * 4 + 1], pal[v * 4])) for v in seg)
            for y, rb in enumerate(rows_bytes):
                k = rb.find(needle)
                while k >= 0:
                    x0, y0 = k // 3 - dw // 4, y - j
                    if k % 3 == 0 and 0 <= y0 and y0 + dh <= a.shape[0] and 0 <= x0 and x0 + dw <= a.shape[1]:
                        swap = replace_only is None or fac in replace_only
                        found.append(f"{shot.name}{tag}: {fac} {slot} at {x0},{y0} ({dw}x{dh})"
                                     f"{'' if swap else ' (kept vanilla)'}")
                        if swap:
                            new = port.enlarge_rgb(src, sw, sh, pal, rgb, w, h, scan, g)
                            layer = to_image(new, pal)
                            mask = Image.new("L", layer.size, 0)
                            mask.putdata([0 if v is None else 255 for r in new[2] for v in r])
                            after.paste(layer, (x0, y0), mask)
                    k = rb.find(needle, k + 1)
    if found:
        both = Image.new("RGB", (img.size[0], img.size[1] * 2), (0, 0, 0))
        both.paste(img, (0, 0)); both.paste(after, (0, img.size[1]))
        both.save(OUT / f"{shot.stem}{tag}_before_after.png")
    return found or [f"{shot.name}: no portrait found pixel-exact at g={g}"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--palette", required=True, type=pathlib.Path, help="1024-byte RGBQUAD game palette")
    ap.add_argument("--only", default=None,
                    help="comma list: native,enlarge,outliers,upscale,framing (default all; '' = none)")
    ap.add_argument("--composite", nargs="*", help="4K screenshots to swap portraits in (found pixel-exact)")
    ap.add_argument("--replace-only", default=None, help="composite: swap only these factions (mixed neighbours)")
    ap.add_argument("--g", type=int, default=40, help="the screenshots' portrait scale num (/16)")
    a = ap.parse_args()
    pal = a.palette.read_bytes()
    assert len(pal) == 1024
    only = set(a.only.split(",")) if a.only is not None else {"native", "enlarge", "outliers", "upscale", "framing"}
    only.discard("")
    OUT.mkdir(parents=True, exist_ok=True)
    port = Port()
    crops = pack_crops()
    hd = {n: hd_image(n, crops[fac]) for n, fac in LEADERS.items()}          # what the pack ships
    sections = {}

    if "native" in only:                       # g = 16: what a 1024x768 player sees; 1:1 and a 3x NN zoom
        rows, rep = [], []
        for n, fac in LEADERS.items():
            rgb, w, h = hd[n]
            cells, labels = [], []
            for slot in SLOTS:
                src, sw, sh = slot_pixels(fac, slot)
                van = to_image(native(src, sw, sh), pal)
                cells.append(van); labels.append("vanilla")
                for mode, name in MODES:
                    im = to_image(port.bake(src, sw, sh, pal, rgb, w, h, mode), pal)
                    cells.append(im); labels.append(name.split(" (")[0] if mode == OFF else
                                                    "overlay" if mode == OVERLAY else "kept")
                    if slot == "datalink":
                        rep.append(f"{fac:9s} datalink mean luma: vanilla {mean_luma(van):5.1f}  {name}: "
                                   f"{mean_luma(im):5.1f}")
            rows.append(labelled_row(cells, labels, f"{fac}: small council | big council | diplomacy | datalink"))
        sheet = stack(rows)
        sheet.save(OUT / "native_g16_1to1.png")
        sheet.resize((sheet.size[0] * 3, sheet.size[1] * 3), Image.NEAREST).save(OUT / "native_g16_zoom3.png")
        sections["native (g=16)"] = rep

    if "enlarge" in only:                      # device sizes: today's smooth enlarge vs HD in each mode
        rep = []
        for g in (22, 25, 40, 45):
            rows = []
            for n, fac in LEADERS.items():
                rgb, w, h = hd[n]
                src, sw, sh = slot_pixels(fac, "diplomacy")
                van = port.enlarge_vanilla(src, sw, sh, pal, g)
                grids = [port.enlarge_rgb(src, sw, sh, pal, rgb, w, h, mode, g) for mode, _ in MODES]
                rep.append(f"g={g} {fac:9s} {grids[0][0]}x{grids[0][1]}  alternation vanilla={alternation(van, pal):.3f}"
                           f" overlay={alternation(grids[0], pal):.3f} kept={alternation(grids[1], pal):.3f}  "
                           f"mean luma vanilla={mean_luma(to_image(van, pal)):.1f} "
                           + " ".join(f"{nm.split('(')[-1].rstrip(')')}={mean_luma(to_image(gr, pal)):.1f}"
                                      for gr, (_, nm) in zip(grids, MODES)))
                rows.append(labelled_row([to_image(van, pal)] + [to_image(gr, pal) for gr in grids],
                                         ["today (vanilla art)"] + [nm for _, nm in MODES], f"{fac} g={g}/16"))
            half = (len(rows) + 1) // 2
            stack(rows[:half]).save(OUT / f"enlarge_diplomacy_g{g}_a.png")
            stack(rows[half:]).save(OUT / f"enlarge_diplomacy_g{g}_b.png")
        sections["enlarge (diplomacy slot)"] = rep

    if "outliers" in only:                     # the three off-framed sources: runtime cover crop vs the pack's crop
        rows = []
        for n, fac in LEADERS.items():
            if fac not in ("morgan", "usurper", "caretake"):
                continue
            raw_rgb, rw, rh = hd_image(n)
            rgb, w, h = hd[n]
            cells, labels = [], []
            for slot in ("smallcouncil", "datalink"):
                src, sw, sh = slot_pixels(fac, slot)
                cells += [to_image(native(src, sw, sh), pal),
                          to_image(port.bake(src, sw, sh, pal, raw_rgb, rw, rh, OVERLAY), pal),
                          to_image(port.bake(src, sw, sh, pal, rgb, w, h, OVERLAY), pal)]
                labels += ["vanilla", "raw image", "pack crop"]
            rows.append(labelled_row(cells, labels, f"{fac}: a raw drop-in vs the pack's registered framing"))
        stack(rows).save(OUT / "outliers_raw_vs_pack.png")

    if "upscale" in only:                      # a player's SMALL image: enlarged past its own size
        rgb, w, h = hd[14]
        full = Image.frombytes("RGB", (w, h), rgb)
        src, sw, sh = slot_pixels("gaians", "datalink")
        rows = []
        for tw, th in ((96, 115), (200, 240), (500, 600)):
            small = full.resize((tw, th), Image.LANCZOS)
            cells, labels = [small], [f"{tw}x{th} source"]
            for g in (25, 45):
                cells.append(to_image(port.enlarge_rgb(src, sw, sh, pal, small.tobytes(), tw, th, OVERLAY, g), pal))
                labels.append(f"g={g}")
            rows.append(labelled_row(cells, labels, f"player image {tw}x{th} in the datalink slot"))
        stack(rows).save(OUT / "upscale_small_images.png")

    if "framing" in only:                      # arbitrary player images: cover crop of off-aspect inputs
        rgb, w, h = hd[14]
        full = Image.frombytes("RGB", (w, h), rgb)

        def padded(W, H, x, y):
            c = Image.new("RGB", (W, H), (40, 44, 52)); c.paste(full, (x, y)); return c
        tests = {"16:9, subject centred": padded(h * 16 // 9, h, (h * 16 // 9 - w) // 2, 0),
                 "16:9, subject left": padded(h * 16 // 9, h, 0, 0),
                 "square": full.crop((0, 0, w, w)),
                 "tall, space below": padded(w, h * 3 // 2, 0, 0)}
        cells, labels = [], []
        src, sw, sh = slot_pixels("gaians", "datalink")
        for name, im in tests.items():
            rgb2, w2, h2 = SL.portrait_prereduce(im.tobytes(), im.size[0], im.size[1])   # as the DLL does
            cells += [im.resize((im.size[0] * 198 // im.size[1], 198)),
                      to_image(port.bake(src, sw, sh, pal, rgb2, w2, h2, OVERLAY), pal),
                      to_image(port.enlarge_rgb(src, sw, sh, pal, rgb2, w2, h2, OVERLAY, 40), pal)]
            labels += [name, "g16", "g40"]
        labelled_row(cells, labels).save(OUT / "framing_arbitrary_images.png")

    only_set = set(a.replace_only.split(",")) if a.replace_only else None
    for shot in a.composite or []:
        for mode, tag in ((OVERLAY, "_overlay"), (MEAN, "_kept")):
            sections.setdefault("composites", []).extend(
                composite(port, pal, hd, pathlib.Path(shot), a.g, mode, only_set,
                          tag + ("_mixed" if only_set else "")))

    for name, lines in sections.items():       # one report per section: a later partial run never erases another
        (OUT / f"report_{name.split(' ')[0]}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"== {name}\n" + "\n".join(lines))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
