"""HQ report window (ReportWin): the four settled slide rails ABUT the d690 window frame (rw_window_rects v5).

slide_show (0x45D440) draws the four rail strips into the window canvas at its settle (0x45D82C / 0x45D851 / 0x45D875
/ 0x45D8A9) through thunk_filedlg_railscale v3 (generic arm: the canvas is taller than the 529-row art) ->
thunk_sprite_scale_nn.  The REAL bytes of those cave entries (resolved from patches.yaml) run under Unicorn on a
ReportWin-sized canvas (cw = rw_canvas_w v2 = ceil(728g/16), H = fl(553g/16)) with the four strips at
slide_show's own x args (0, 15, cw - 15 - 8 - 0x20, cw - 15 - 0x20).  The frame t_rw_backdrop draws covers the
half-open rect [L, R) (exact-fill, R-1 = its right stroke), so abutment is:
    the inner-left strip's last written column == L - 1     (no see-through column; 1920x1080 x512 before v5)
    the inner-right strip's first written column == R        (it never covers the R-1 stroke; 1-3 px before v5)
for every g in 17..48, with the left strips seamless and the right pair seamless (railscale v3), and the frame R =
the inner right strip = fl(673g/16) = vanilla x g/16 (rw_canvas_w v2; v1's W + s(0x4E) left it 1-2 px short).
Skips without unicorn.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: E402

import apply_patches as ap  # noqa: E402

PCAVE2, CAVE_LEN = 0x00A0C000, 0x31000
G_VA = 0x00668740
ART_H_VA = 0x007CFFE0           # rail sprite 1 canvas h (railscale's arm-B comparand) = 529
SPRITE_DRAW_2 = 0x005E4B4A      # the native tail (must not be reached at g > 16)
STACK, DATA, MARKER = 0x00200000, 0x01000000, 0x00DEAD00
BUF, SPR0 = DATA, DATA + 0x100  # dest Buffer object, 4 Sprite objects (0x40 apart)
SPR_PIX = DATA + 0x1000         # strip pixels (4 x 0x400)
PLANE = DATA + 0x10000
STRIDE, ROWS = 2304, 8          # cw <= 2184 at g = 48; the strips are 4 rows tall (rows written: fl(4g/16) <= 12 -> 8 kept)
SPR_H = 2
RAIL_W = (15, 8, 8, 15)         # outer-left, inner-left, inner-right, outer-right (slide_show draw order)
COLORS = (0x31, 0x32, 0x33, 0x34)
ENTRIES = ("thunk_filedlg_railscale", "thunk_sprite_scale_nn")   # railscale v3: no v1shim


def _w32(mu, a, v):
    mu.mem_write(a, int(v & 0xFFFFFFFF).to_bytes(4, "little"))


@pytest.fixture(scope="module")
def code():
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = ap.build_symbol_table(symbols, caves)
    cave = next(c for c in caves if c["id"] == "pcave2")
    out = {}
    for name in ENTRIES:
        e = next(c for c in cave["contents"] if c["id"] == name)
        va = PCAVE2 + int(e["offset"])
        out[name] = (va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, symtab)))
    return out


def _draw_strips(code, g, cw, h):
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(PCAVE2, CAVE_LEN)
    mu.mem_map(G_VA & ~0xFFF, 0x1000)
    mu.mem_map(ART_H_VA & ~0xFFF, 0x1000)
    mu.mem_map(SPRITE_DRAW_2 & ~0xFFF, 0x1000)
    mu.mem_map(STACK, 0x10000)
    mu.mem_map(DATA, (0x10000 + STRIDE * ROWS + 0x1FFF) & ~0xFFF)
    mu.mem_map(MARKER & ~0xFFF, 0x1000)
    for va, b in code.values():
        mu.mem_write(va, b)
    _w32(mu, G_VA, g)
    _w32(mu, ART_H_VA, 529)
    mu.mem_write(SPRITE_DRAW_2, b"\xC2\x18\x00")
    native = []
    mu.hook_add(UC_HOOK_CODE, lambda m, a, s, u: native.append(a), begin=SPRITE_DRAW_2, end=SPRITE_DRAW_2)
    # dest Buffer: data +0x54, W +0x80, H +0x84 (NEGATIVE: top-down), stride +0x4A8
    _w32(mu, BUF + 0x54, PLANE)
    _w32(mu, BUF + 0x80, cw)
    _w32(mu, BUF + 0x84, -h)
    _w32(mu, BUF + 0x4A8, STRIDE)
    # slide_show's settled x args (window-local): 0, [outer w], cw - [outer w] - [inner w] - 0x20, cw - [outer w] - 0x20
    xs = (0, RAIL_W[0], cw - RAIL_W[3] - RAIL_W[2] - 0x20, cw - RAIL_W[3] - 0x20)
    for k, (w, col, x) in enumerate(zip(RAIL_W, COLORS, xs)):
        spr, pix = SPR0 + 0x40 * k, SPR_PIX + 0x400 * k
        mu.mem_write(pix, bytes([col]) * (w * SPR_H))
        _w32(mu, spr + 0x04, pix)
        _w32(mu, spr + 0x0C, w)          # pitch
        _w32(mu, spr + 0x10, w)
        _w32(mu, spr + 0x14, SPR_H)
        _w32(mu, spr + 0x20, 0)          # draw offsets 0 (the rail strips)
        _w32(mu, spr + 0x24, 0)
        sp = STACK + 0x8000
        for i, v in enumerate((MARKER, BUF, 9, x, 0, 1, 1)):     # ret, dest, key, x, y, num, den
            _w32(mu, sp + 4 * i, v)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, spr)
        mu.emu_start(code["thunk_filedlg_railscale"][0], MARKER, count=2_000_000)
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18             # RET 0x18 (Sprite_draw_2's contract)
    assert not native, "g > 16 on a canvas taller than the art must take the scaled path"
    row = bytes(mu.mem_read(PLANE, STRIDE))[:cw]
    return {col: [i for i, p in enumerate(row) if p == col] for col in COLORS}


@pytest.mark.parametrize("g", range(17, 49))
def test_scaling_rw_rails_abut_the_frame(code, g):
    W, H = (650 * g) >> 4, (553 * g) >> 4
    cw = SL.rw_canvas_w(W, g)
    (L, _t, R, _b), _clip = SL.rw_window_rects(W, H, g)
    cols = _draw_strips(code, g, cw, H)
    ol, il, ir, orr = (cols[c] for c in COLORS)
    assert ol and il and ir and orr
    assert ol[0] == 0 and il[0] == ol[-1] + 1                   # left pair seamless from the canvas edge
    assert il[-1] == L - 1, (g, il[-1], L)                      # no see-through column before the frame's left stroke
    assert ir[0] == R, (g, ir[0], R)                            # the frame's R-1 stroke column stays visible
    assert R == (673 * g) >> 4 and (cw << 4) // g == 728        # vanilla x g/16 (the exact native canvas)
    assert orr[0] == ir[-1] + 1                                 # right pair seamless
    assert orr[-1] < cw
    # every strip at its proportionate width (the railscale floor)
    assert [len(c) for c in (ol, il, ir, orr)] == [(w * g) >> 4 for w in RAIL_W]
