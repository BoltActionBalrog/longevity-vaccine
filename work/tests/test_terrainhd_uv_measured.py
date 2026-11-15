"""The terrain UV law measured on the engine's own rasterizer: Texture_draw_2 (0x6233C0) of the real image under
Unicorn (image_emu), drawing the stock UV tables' 12 polygons over a tile diamond with textures whose texels hold
their own u / v (and a zero texture for the shading the rasterizer adds to the index).

For every pixel both draws cover, the level-k texel should lie inside the stock texel stock drew there:
floor(U / k) == u. scaling_laws.terrain_hd_uv_offset must be the best whole offset for k = 2 and 4, and the law
must beat the hook's first law, round(u * (56k - 1) / 55).
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

QUADS = [(27, 27), (27, 55), (0, 55), (0, 0), (27, 27), (27, 0), (55, 0), (55, 55), (27, 27), (55, 27), (55, 55),
         (27, 55), (27, 27), (0, 27), (0, 0), (27, 0)]
TRIS = [(27, 28), (0, 55), (0, 1), (27, 27), (0, 0), (54, 0), (28, 27), (55, 1), (55, 53), (28, 29), (55, 55), (2, 55),
        (27, 27), (0, 27), (0, 0), (27, 0), (28, 27), (28, 0), (55, 0), (55, 27), (28, 28), (55, 28), (55, 55),
        (28, 55), (27, 28), (27, 55), (0, 55), (0, 28)]
POLYS = ([QUADS[i:i + 4] for i in range(0, 16, 4)] + [TRIS[i:i + 3] for i in range(0, 12, 3)]
         + [TRIS[12 + i:12 + i + 4] for i in range(0, 16, 4)])
WIDTHS = (48, 112, 220)
TEX_DRAW_2, EXTRACT_2, BUFFER_CTOR, BUFFER_INIT = 0x6233C0, 0x619710, 0x5D7210, 0x5D7670
BUF_DATA, BUF_BITS, BUF_W, BUF_PITCH, SIDE = 0x50, 0x54, 0x80, 0x4A8, 384


def test_the_stock_tables_are_the_hooks():
    src = (ROOT.parent / "src" / "uimod" / "src" / "terrainhd.cpp").read_text(encoding="utf-8")
    flat = [v for uv in QUADS for v in uv], [v for uv in TRIS for v in uv]
    for name, vals in zip(("kUvStock0", "kUvStock1"), flat):
        body = src.split(name, 1)[1].split("};", 1)[0].split("{", 1)[1]
        assert [int(t) for t in body.replace("\n", " ").split(",") if t.strip()] == vals


class Raster:
    def __init__(self):
        import image_emu as ie
        self.e = e = ie.Emu(str(BAK), 1920, 1080)
        ie.crt_stubs(e)
        self.dst = self.buffer(SIDE, SIDE)

    def buffer(self, w, h):
        e = self.e
        b = e.alloc(0x588)
        e.call(BUFFER_CTOR, ecx=b)
        e.call(BUFFER_INIT, ecx=b, args=(w, h, 0, 0))
        assert e.r32(b + BUF_W) == w
        return b

    def pixels(self, b):
        return self.e.r32(b + BUF_DATA) or self.e.r32(b + BUF_BITS)

    def texture(self, img):
        e, n = self.e, img.shape[0]
        src = self.buffer(n, n)
        p, pitch = self.pixels(src), e.r32(src + BUF_PITCH)
        for y in range(n):
            e.uc.mem_write(p + y * pitch, img[y].tobytes())
        tex = e.alloc(0x70)
        e.call(EXTRACT_2, ecx=tex, args=(src, 0, 0, n, n, 0))
        assert e.r32(tex + 4) == n
        return tex

    def draw(self, tex, pts, uvs):
        e = self.e
        p, pitch = self.pixels(self.dst), e.r32(self.dst + BUF_PITCH)
        e.uc.mem_write(p, b"\xff" * (pitch * SIDE))
        n = len(pts)
        pa, ua, la = e.alloc(8 * n), e.alloc(8 * n), e.alloc(4 * n)
        for i, ((x, y), (u, v)) in enumerate(zip(pts, uvs)):
            e.w32(pa + 8 * i, x)
            e.w32(pa + 8 * i + 4, y)
            e.w32(ua + 8 * i, u)
            e.w32(ua + 8 * i + 4, v)
            e.w32(la + 4 * i, 0)
        e.call(TEX_DRAW_2, ecx=tex, args=(self.dst, pa, la, n, ua, 3), count=20000000)
        raw = bytes(e.uc.mem_read(p, pitch * SIDE))
        return np.frombuffer(raw, np.uint8).reshape(SIDE, pitch)[:, :SIDE].astype(int)


def screen(u, v, w):
    # the tile diamond, texture top-left on its left corner (as the terrain pass lays a tile)
    return int(round(20 + (u + v) * w / 110.0)), int(round(SIDE // 2 - u * w / 220.0 + v * w / 220.0))


@pytest.fixture(scope="module")
def mismatch():
    r = Raster()
    tex = {}
    for k in (1, 2, 4):
        n = 56 * k
        ramp = np.tile(np.arange(n, dtype=np.uint8), (n, 1))
        tex[k] = (r.texture(ramp), r.texture(ramp.T.copy()), r.texture(np.zeros((n, n), np.uint8)))
    stock = {}
    for w in WIDTHS:
        for i, poly in enumerate(POLYS):
            pts = [screen(u, v, w) for u, v in poly]
            st = [r.draw(t, pts, poly) for t in tex[1]]
            stock[(w, i)] = (pts, [(st[a] - st[2]) % 256 for a in range(2)], st[2] != 255)

    def rate(k, law):
        bad = tot = 0
        for w in WIDTHS:
            for i, poly in enumerate(POLYS):
                pts, s, cover = stock[(w, i)]
                hd = [r.draw(t, pts, [(law(u), law(v)) for u, v in poly]) for t in tex[k]]
                both = cover & (hd[2] != 255)
                bad += int((cover != (hd[2] != 255)).sum())
                for a in range(2):
                    h = (hd[a] - hd[2]) % 256
                    tot += int(both.sum())
                    bad += int(((h // k) != s[a])[both].sum())
        return bad / tot

    return rate


@pytest.mark.parametrize("k", [2, 4])
def test_the_law_offset_is_the_best_whole_offset(mismatch, k):
    rates = {c: mismatch(k, lambda u, c=c: k * u + c) for c in range(k)}
    law = SL.terrain_hd_uv_offset(k)
    assert min(rates, key=rates.get) == law, rates
    assert rates[law] < 0.07, rates


@pytest.mark.parametrize("k", [2, 4])
def test_the_law_beats_the_first_law(mismatch, k):
    first = mismatch(k, lambda u: (u * (56 * k - 1) * 2 + 55) // 110)
    law = mismatch(k, lambda u: SL.terrain_hd_uv(u, k))
    assert law < first, (law, first)
