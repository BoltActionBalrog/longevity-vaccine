"""HD terrain placement is exact: the engine's own rasterizers, under Unicorn on the pristine exe (image_emu), with the
hook's span stubs patched in exactly as terrainhd.cpp generates them (terrainhd_cache_selftest "stubs": the same
BuildSpanStubs bytes, for addresses in the emulated image).

A stock texture of random texels is drawn, then the same picture at level k (each texel a k x k block:
terrain_hd_nearest) in a texture the stubs know as ours. Every pixel of the two draws must be the same, for:

  * Texture_draw_2 (0x6233C0) with mode -1 -> 0x61B1F0, the visible terrain (edges from 0x61FC90: u << 16 + 0x8000)
  * Texture_draw_2 with mode 3, its own fog-of-war path (every even row flat)
  * 0x6239E0 with mode -1 -> 0x61A760, the land / sea fungus and Monsoon Jungle draw (edges from 0x624D80: no half
    texel)

over the stock UV tables' polygons at tile widths up to the deepest zoom at 4K, and random polygons, some partly off
the buffer so the clipping pre-step runs. And a texture that is not ours draws byte-for-byte as it did before the
stubs were patched in. Skipped when the pristine exe or Visual Studio is absent.
"""
from __future__ import annotations

import pathlib
import random
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import config  # noqa: E402
import cpp_harness  # noqa: E402
import scaling_laws as SL  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

TEX_DRAW_2, FUNGUS_DRAW, EXTRACT_2, BUFFER_CTOR, BUFFER_INIT = 0x6233C0, 0x6239E0, 0x619710, 0x5D7210, 0x5D7670
BUF_DATA, BUF_BITS, BUF_W, BUF_PITCH = 0x50, 0x54, 0x80, 0x4A8
W, H = 640, 400
STUB_VA, DATA_VA = 0x30000000, 0x30100000

QUADS = [(27, 27), (27, 55), (0, 55), (0, 0), (27, 27), (27, 0), (55, 0), (55, 55), (27, 27), (55, 27), (55, 55),
         (27, 55), (27, 27), (0, 27), (0, 0), (27, 0)]
TRIS = [(27, 28), (0, 55), (0, 1), (27, 27), (0, 0), (54, 0), (28, 27), (55, 1), (55, 53), (28, 29), (55, 55), (2, 55),
        (27, 27), (0, 27), (0, 0), (27, 0), (28, 27), (28, 0), (55, 0), (55, 27), (28, 28), (55, 28), (55, 55),
        (28, 55), (27, 28), (27, 55), (0, 55), (0, 28)]
TABLE_POLYS = ([QUADS[i:i + 4] for i in range(0, 16, 4)] + [TRIS[i:i + 3] for i in range(0, 12, 3)]
               + [TRIS[12 + i:12 + i + 4] for i in range(0, 16, 4)])
WIDTHS = (96, 200, 448, 552)                # the default zoom, a middle one, the deepest at 3840x1080 and 3840x2160


def screen(u, v, w, x0=20, y0=H // 2):
    # the tile diamond as the terrain pass lays it: texture top-left on its left corner
    return int(round(x0 + (u + v) * w / 110.0)), int(round(y0 - u * w / 220.0 + v * w / 220.0))


def polygons():
    out = [([screen(u, v, w) for u, v in p], p) for w in WIDTHS for p in TABLE_POLYS]
    rnd = random.Random(16)
    for _ in range(60):
        n = rnd.choice((3, 4))
        uv = [(rnd.randrange(56), rnd.randrange(56)) for _ in range(n)]
        cx, cy, r = rnd.randrange(-40, W + 40), rnd.randrange(-40, H + 40), rnd.randrange(20, 260)
        ang = sorted(rnd.uniform(0, 6.283) for _ in range(n))         # a convex polygon, partly off the buffer at times
        pts = [(int(cx + r * np.cos(a)), int(cy + r * 0.5 * np.sin(a))) for a in ang]
        out.append((pts, uv))
    return out


@pytest.fixture(scope="module")
def stubs(tmp_path_factory):
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    exe = cpp_harness.build(ROOT / "tests" / "terrainhd_cache_selftest.cpp", "terrainhd_cache_", "/Oi /GL")
    d = tmp_path_factory.mktemp("terrainhd_stubs")
    import pefile
    import re
    pe = pefile.PE(str(BAK), fast_load=True)
    src = (ROOT.parent / "src" / "uimod" / "src" / "terrainhd.cpp").read_text(encoding="utf-8")
    sites = [int(v, 16) for v in re.findall(r"0x[0-9A-F]+", re.search(r"kSpanSites\[\] = \{([^}]*)\}", src).group(1))]
    real = []
    for va in sites:                                              # the real exe's bytes: the stubs copy them
        b = pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, 6)
        real.append((b[:5] if b[0] == 0xA3 else b).hex())
    r = subprocess.run([str(exe), str(d), f"stubs {STUB_VA:x} {DATA_VA:x}"], input="\n".join(real) + "\n",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    area, sites, data = None, [], {}
    for ln in r.stdout.splitlines():
        f = ln.split()
        if f[0] == "area":
            area = bytes.fromhex(f[1])
        elif f[0] == "site":
            sites.append((int(f[1], 16), bytes.fromhex(f[2])))
        elif f[0] == "data":
            data = {f[i]: int(f[i + 1]) for i in range(1, len(f), 2)}
    assert area and len(sites) == 100 and data
    return area, sites, data


class Raster:
    def __init__(self):
        import image_emu as ie
        self.e = e = ie.Emu(str(BAK), 1920, 1080)
        ie.crt_stubs(e)
        self.dst = self.buffer(W, H)

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

    def patch(self, stubs, k, ours):
        area, sites, data = stubs
        uc = self.e.uc
        from unicorn import UC_PROT_ALL
        uc.mem_map(STUB_VA, 0x10000, UC_PROT_ALL)
        uc.mem_map(DATA_VA, 0x1000, UC_PROT_ALL)
        uc.mem_write(STUB_VA, area)
        for va, b in sites:
            uc.mem_write(va, b)
        self.data = data
        self.set_ours(k, ours)

    def set_ours(self, k, ours):
        e, d = self.e, self.data
        e.w32(DATA_VA + d["last"], 1)
        e.w32(DATA_VA + d["shift"], 0)
        e.w32(DATA_VA + d["count"], len(ours))
        e.w32(DATA_VA + d["level"], k.bit_length() - 1)
        for i, t in enumerate(ours):
            e.w32(DATA_VA + d["ptrs"] + 4 * i, e.r32(t))           # the texture's bits

    def draw(self, fn, tex, pts, uvs, mode):
        e = self.e
        p, pitch = self.pixels(self.dst), e.r32(self.dst + BUF_PITCH)
        e.uc.mem_write(p, b"\xff" * (pitch * H))
        n = len(pts)
        pa, ua, la = e.alloc(8 * n), e.alloc(8 * n), e.alloc(4 * n)
        for i, ((x, y), (u, v)) in enumerate(zip(pts, uvs)):
            e.w32(pa + 8 * i, x & 0xFFFFFFFF)
            e.w32(pa + 8 * i + 4, y & 0xFFFFFFFF)
            e.w32(ua + 8 * i, u)
            e.w32(ua + 8 * i + 4, v)
            e.w32(la + 4 * i, 0)
        if fn in (TEX_DRAW_2, TEX_DRAW_TRANS):                     # (dst, pts, light, n, uvs, mode)
            args = (self.dst, pa, la, n, ua, mode & 0xFFFFFFFF)
        elif fn in DIRECT:                                         # the rasterizers' own (dst, pts, light, n, uvs)
            args = (self.dst, pa, la, n, ua)
        elif fn == TEX_DRAW_COAST_DISPATCH:                        # (dst, pts, light, n, uvs, 0x10, mode): 0x4646E3
            args = (self.dst, pa, la, n, ua, 0x10, mode & 0xFFFFFFFF)
        elif fn == TEX_DRAW_TRANS_2:                               # (dst, pts, octagon): its UVs are the texture's
            args = (self.dst, pa, mode)                            # own corners (+0x0C quad, +0x2C octagon)
        elif fn == TEX_DRAW_COAST_2:                               # (dst, pts, light, composite, coast table, n,
            args = (self.dst, pa, la, self.composite, self.table, n, ua, mode & 0xFFFFFFFF)   # uvs, mode): 0x46547C
        else:
            args = (self.dst, pa, n, ua, mode & 0xFFFFFFFF)
        e.call(fn, ecx=tex, args=args, count=40000000)
        raw = bytes(e.uc.mem_read(p, pitch * H))
        return np.frombuffer(raw, np.uint8).reshape(H, pitch)[:, :W].copy()


DIRECT = (0x61B1F0, 0x61C090)                                   # called with (dst, pts, light, n, uvs), RET 0x14
TEX_DRAW_TRANS = 0x622DB0                                       # Texture_draw_2's shape; the terrain pass: modes 3, 9
DRAWS = [("visible (0x61B1F0)", TEX_DRAW_2, -1), ("fog (0x6233C0 mode 3)", TEX_DRAW_2, 3),
         ("fungus (0x61A760)", FUNGUS_DRAW, -1), ("0x61B1F0 direct", 0x61B1F0, 0),
         ("quarter tiles (0x61C090)", 0x61C090, 0), ("0x622DB0 mode -1", TEX_DRAW_TRANS, -1),
         ("0x622DB0 mode 3", TEX_DRAW_TRANS, 3), ("0x622DB0 mode 9", TEX_DRAW_TRANS, 9),
         ("fungus fog (0x6239E0 mode 3)", FUNGUS_DRAW, 3),
         ("0x624670 mode -1 (0x61AC60)", 0x624670, -1), ("0x624670 mode 0x41", 0x624670, 0x41),
         ("trans_2 quad (0x61A240)", 0x61A240, 0), ("trans_2 octagon (0x61A240)", 0x61A240, 1)]
TEX_DRAW_COAST_DISPATCH, TEX_DRAW_TRANS_2, TEX_DRAW_COAST_2 = 0x624670, 0x61A240, 0x623F80
# the coast: an ocean texture and a RAINFALL composite through ONE UV array, the composite's texel picking land (0),
# the shaded ocean texel (1) or a flat shore colour through the per-coast-type table
DRAWS += [("coast (0x623F80 mode -1)", TEX_DRAW_COAST_2, -1), ("coast (0x623F80 mode 0x41)", TEX_DRAW_COAST_2, 0x41)]


def shapes(fn, mode, polys):
    """The polygons a draw takes: Texture_draw_trans_2 draws a quad (4 points) or an octagon (8) over the texture's
    own corners, the others any polygon with its UVs."""
    if fn != TEX_DRAW_TRANS_2:
        return polys
    n = 8 if mode else 4
    rnd = random.Random(n)
    out = []
    for _ in range(30):
        cx, cy, r = rnd.randrange(-40, W + 40), rnd.randrange(-40, H + 40), rnd.randrange(30, 260)
        a0 = rnd.uniform(0, 6.283)
        out.append(([(int(cx + r * np.cos(a0 + 6.283 * i / n)), int(cy + r * 0.5 * np.sin(a0 + 6.283 * i / n)))
                     for i in range(n)], [(0, 0)] * n))
    return out


@pytest.fixture(scope="module")
def world(stubs):
    r = Raster()
    rnd = np.random.default_rng(5)
    stock_img = rnd.integers(20, 200, (56, 56), dtype=np.uint8)
    stock = r.texture(stock_img)
    comp_img = rnd.integers(0, 256, (56, 56), dtype=np.uint8)
    comp_stock = r.texture(comp_img)
    r.table = r.e.alloc(256)
    r.e.uc.mem_write(r.table, bytes((0, 1, 200 + v % 40)[v % 3] if v % 3 < 2 else 200 + v % 40 for v in range(256)))
    r.composite = comp_stock
    polys = polygons()
    before = {(name, i): r.draw(fn, stock, pts, uv, mode)
              for name, fn, mode in DRAWS for i, (pts, uv) in enumerate(shapes(fn, mode, polys)[:24])}
    hd = {}
    corners = bytes(r.e.uc.mem_read(stock + 0x0C, 0x60))
    for k in (2, 4, 8):
        big = np.array(SL.terrain_hd_nearest(stock_img.tolist(), k), np.uint8)
        hd[k] = r.texture(big)
        r.e.uc.mem_write(hd[k] + 0x0C, corners)                    # as GiveBits: the stock corner coordinates
    r.patch(stubs, 2, [])
    r.comp = {1: comp_stock}
    for k in (2, 4, 8):
        r.comp[k] = r.texture(np.array(SL.terrain_hd_nearest(comp_img.tolist(), k), np.uint8))
        r.e.uc.mem_write(r.comp[k] + 0x0C, corners)
    r.composite = comp_stock
    return r, stock, hd, polys, before


def test_a_texture_not_ours_draws_as_before_the_stubs(world):
    r, stock, hd, polys, before = world
    r.set_ours(4, [hd[4], r.comp[4]])
    r.composite = r.comp[1]
    for name, fn, mode in DRAWS:
        for i, (pts, uv) in enumerate(shapes(fn, mode, polys)[:24]):
            assert (r.draw(fn, stock, pts, uv, mode) == before[(name, i)]).all(), (name, i)


@pytest.mark.parametrize("k", [2, 4, 8])
@pytest.mark.parametrize("draw", DRAWS, ids=[d[0] for d in DRAWS])
def test_switching_the_level_moves_no_pixel(world, k, draw):
    r, stock, hd, polys, _ = world
    name, fn, mode = draw
    r.set_ours(k, [hd[k], r.comp[k]])
    covered = 0
    for i, (pts, uv) in enumerate(shapes(fn, mode, polys)):
        r.composite = r.comp[1]
        a = r.draw(fn, stock, pts, uv, mode)
        r.composite = r.comp[k]
        b = r.draw(fn, hd[k], pts, uv, mode)
        covered += int((a != 255).sum())
        diff = int((a != b).sum())
        assert diff == 0, (name, k, i, diff, int((a != 255).sum()))
    assert covered > 30000, covered                               # the polygons really drew
