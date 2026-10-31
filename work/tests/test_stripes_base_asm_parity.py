"""Differential: scripts/assemble_stripes_base.py under Unicorn.

  (1) t_sb_tile2 (Buffer_tile_2 drop-in) must leave the dest plane equal to the cell law below
      (tile_pair_restripe): g <= 16 == the native callee alone; above it a rect that is a strict 1-row
      two-index parity dither is rewritten to the stripe law with the EVEN-dest-row member on top; anything
      else (solid 0xF0 tile, art, a rect clipped to one row) is exactly what the engine drew; nothing outside
      (rect & clip) is touched.
  (2) BaseWin_draw_queue's row tile through the existing t_tile_force + the real thunk_fe_pair_remap: the two
      row pairs (E0/E1 selected, AE/EE hover) land on scaling_laws.pair_remap_pixel.
  (3) the two PROPOSED file-dialog replacement thunks hand Buffer_tile a phase that puts the list's stripes on
      its parent's row grid (list_stripe_phase), and the composite column then has no off-law run at any g.

The three law functions defined here (tile_pair, tile_pair_restripe, list_stripe_phase) are the reference the
asm is a port of; they are meant to move into scripts/scaling_laws.py.

Skips (does not fail) if keystone/unicorn are absent.  Run with -p no:faulthandler.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_stripes_base as SB  # noqa: E402

G_ALL = tuple(range(16, 41))
G_SWEEP = (16, 17, 18, 21, 22, 25, 32, 40)
SCALED = tuple(g for g in G_ALL if g > 16)


# ==== THE LAWS (reference; to move into scaling_laws.py) =========================================================
# The five base-screen cell pairs, measured on the 1920x1080 shot 20261004-203801 (exact palette match) and
# tied to their tiles by BaseWin_init's loads.  The FIRST members all sit on the same row parity of the base
# canvas (that shot: even screen rows -- 0x95 y=198, 0x99 y=484, 0xE2 y=512, 0x42 y=512, 0x60 y=542), i.e. they
# are one row of their 20x20 tiles; whether that is tile row 0 depends on the window top's parity, which a
# screenshot does not give.  The law never needs it: the top member is whichever sits on even DEST rows.
BASE_CELL_PAIRS = {
    "nut_stored +0xBD4C": (0x95, 0x96),
    "nut_empty  +0xBD20": (0x99, 0x98),
    "min_intake +0xBCC8": (0xE2, 0xE0),
    "min_done   +0xBCF4": (0x42, 0xDE),
    "energy     +0xBC9C": (0x60, 0x5F),
}
BASE_CELL_SOLID = 0xF0            # the empty-cell tile +0xBDA4: one index, never restriped
BASE_CELL_TILE = 20               # every cell tile is 20x20 (BaseWin_init: push 0x14 / push 0x14)


def tile_pair(px, x0: int, y0: int, x1: int, y1: int):
    """(even_row_member, odd_row_member) when [x0,x1) x [y0,y1) is a strict 1-row parity dither of exactly two
    indices (every pixel of a row equal, rows alternating), else None.  Needs two rows.  `px(x, y)` -> index.
    The member on EVEN dest rows is canonical: Buffer_tile_2 maps dest row y to tile row (y - y0 + a4) mod h
    and every caller passes a4 == y0 with h even, so it is the tile's own row-0 member wherever the cell is."""
    if x1 - x0 < 1 or y1 - y0 < 2:
        return None
    a, b = px(x0, y0), px(x0, y0 + 1)
    if a == b:
        return None
    for y in range(y0, y1):
        want = a if (y - y0) % 2 == 0 else b
        if any(px(x, y) != want for x in range(x0, x1)):
            return None
    return (a, b) if y0 % 2 == 0 else (b, a)


def tile_pair_restripe(plane: bytearray, stride: int, rect, clip, g: int) -> bool:
    """A freshly tiled cell `rect` (l,t,r,b half-open) inside `clip`: above native scale, a parity-dither cell
    is rewritten so row y carries the even-row member where scaling_laws.stripe_top(y, g), its mate elsewhere
    (T rows each, the dest buffer's own grid).  Identity at T = 1.  Returns whether it rewrote."""
    if g <= SL.NATIVE_G:
        return False
    x0, y0 = max(rect[0], clip[0]), max(rect[1], clip[1])
    x1, y1 = min(rect[2], clip[2]), min(rect[3], clip[3])
    pair = tile_pair(lambda x, y: plane[y * stride + x], x0, y0, x1, y1)
    if pair is None:
        return False
    for y in range(y0, y1):
        v = pair[0] if SL.stripe_top(y, g) else pair[1]
        for x in range(x0, x1):
            plane[y * stride + x] = v
    return True


list_stripe_phase = SL.list_stripe_phase   # the law lives in scaling_laws.py (2026-10-06)


# ==== harness ===================================================================================================
PCAVE2, CAVE_LEN = SB.PCAVE2, 0x31000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect)
G_VA, PERIOD_VA = SB.G, SB.PERIOD
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
BUF = DATA + 0x100
SRC_SPRITE = DATA + 0xA00
PLANE = DATA + 0x10000
BW, BH, STRIDE = 120, 72, 128
F_CLIP, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0x4A8
REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9, UC_X86_REG_EAX: 0x0EA0EA0E, UC_X86_REG_EDX: 0x0ED0ED0E}
STUB_EAX = 0x00C0FFEE
FULL = (0, 0, BW, BH)


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


class Emu:
    def __init__(self):
        self.syms = SB.load_syms()
        self.layout = SB.assemble_all(self.syms)
        self.entry = PCAVE2 + self.layout["t_sb_tile2"][0]
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)
        mu.mem_map(SB.BUFFER_TILE_2 & ~0xFFF, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        for _name, (off, b) in self.layout.items():
            mu.mem_write(PCAVE2 + off, b)
        mu.mem_write(SB.BUFFER_TILE_2, b"\xC2\x1C\x00")
        self.calls, self.errors, self.painter = [], [], None
        mu.hook_add(UC_HOOK_CODE, self._on_tile2, begin=SB.BUFFER_TILE_2, end=SB.BUFFER_TILE_2)

    def _on_tile2(self, mu, address, size, user):
        try:
            esp = mu.reg_read(UC_X86_REG_ESP)
            args = [_r32(mu, esp + 4 + 4 * i) for i in range(7)]
            self.calls.append({"esp": esp, "ret": _r32(mu, esp), "ecx": mu.reg_read(UC_X86_REG_ECX), "args": args,
                               "regs": {r: mu.reg_read(r) for r in REGS}})
            _src, _a3, a4, x, y, w, h = (_s32(a) for a in args)
            if self.painter:
                self.painter(x, y, x + w, y + h, a4)
            for i in range(7):                       # the real callee reuses its arg slots (0x5DAA52 / 0x5DAAB7)
                _w32(mu, esp + 4 + 4 * i, 0x7FFF0000 + i)
            mu.reg_write(UC_X86_REG_EAX, STUB_EAX)
            mu.reg_write(UC_X86_REG_ECX, 0xCCCC0001)
            mu.reg_write(UC_X86_REG_EDX, 0xDDDD0002)
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    def run(self, g, args, *, clip=FULL, plane, painter, data_ptr=PLANE, period=None):
        mu = self.mu
        mu.mem_write(BUF, b"\x00" * 0x500)
        _w32(mu, BUF + F_DATA, data_ptr)
        _w32(mu, BUF + F_W, BW)
        _w32(mu, BUF + F_H, -BH)
        _w32(mu, BUF + F_STRIDE, STRIDE)
        for i, v in enumerate(clip):
            _w32(mu, BUF + F_CLIP + 4 * i, v)
        mu.mem_write(PLANE, bytes(plane))
        _w32(mu, G_VA, g)
        _w32(mu, PERIOD_VA, SL.stripe_period(g) if period is None else period)
        self.calls.clear()
        self.errors.clear()
        self.painter = painter
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, MARKER)
        for i, a in enumerate(args):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, BUF)
        mu.reg_write(UC_X86_REG_EFLAGS, 0x202)       # DF clear, as the Win32 ABI guarantees at a call
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.emu_start(self.entry, MARKER, count=20_000_000)
        assert not self.errors, self.errors
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER, "did not return to the caller"
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x1C, "stack imbalance (RET 0x1C contract)"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == REGS[r], "callee-saved register not preserved"
        assert mu.reg_read(UC_X86_REG_EAX) == STUB_EAX, "eax must be the native callee's result"
        assert not mu.reg_read(UC_X86_REG_EFLAGS) & 0x400, "DF left set"
        assert bytes(mu.mem_read(sp - 0x400, 0x400 - 0x80)) == b"\xA5" * (0x400 - 0x80), "stack use deeper than 0x80"
        assert bytes(mu.mem_read(sp + 0x20, 0x100)) == b"\xA5" * 0x100, "wrote above its own args"
        assert len(self.calls) == 1, "the native Buffer_tile_2 must run exactly once"
        c = self.calls[0]
        assert c["ecx"] == BUF and c["args"] == [a & 0xFFFFFFFF for a in args]
        if g <= 16:
            assert c["esp"] == sp and c["ret"] == MARKER and c["regs"] == REGS, "g <= 16 must tail-jump"
        else:
            assert c["esp"] < sp and c["ret"] != MARKER
            assert [_r32(mu, sp + 4 + 4 * i) for i in range(7)] == [a & 0xFFFFFFFF for a in args], \
                "the site's own arg slots must be left as the site wrote them until the RET"
        return bytes(mu.mem_read(PLANE, STRIDE * BH))


@pytest.fixture(scope="module")
def emu():
    return Emu()


_HOSTILE = (0x41, 0xC6, 0xC4, 0xE0, 0xE1, 0xE2, 0x95, 0x96, 0x98, 0x99, 0x42, 0xDE, 0x5F, 0x60, 0xF0, 0xB9)


def _background():
    return bytearray(_HOSTILE[(x * 7 + y * 3) % len(_HOSTILE)] for y in range(BH) for x in range(STRIDE))


def _clip_box(l, t, r, b, clip):
    return max(l, clip[0], 0), max(t, clip[1], 0), min(r, clip[2], BW), min(b, clip[3], BH)


def _tile_painter(plane, texel, clip):
    """Buffer_tile_2: dest (x, y) <- tile texel ((x - x0 + a3) mod 20, (y - y0 + a4) mod 20), clip-honouring.
    Every site passes a3 == x0, a4 == y0, so the texel is (x mod 20, y mod 20)."""
    def paint(l, t, r, b, a4):
        x0, y0, x1, y1 = _clip_box(l, t, r, b, clip)
        for y in range(y0, y1):
            for x in range(x0, x1):
                plane[y * STRIDE + x] = texel(x % BASE_CELL_TILE, (y - t + a4) % BASE_CELL_TILE)
    return paint


def _dither(pair):
    return lambda tx, ty: pair[ty & 1]


def _cell(emu, g, rect, texel, *, clip=FULL, period=None, a4=None):
    x, y, w, h = rect
    bg = _background()
    native = bytearray(bg)
    _tile_painter(native, texel, clip)(x, y, x + w, y + h, y if a4 is None else a4)
    live = bytearray(bg)

    def painter(l, t, r, b, ph):
        _tile_painter(live, texel, clip)(l, t, r, b, ph)
        emu.mu.mem_write(PLANE, bytes(live))

    got = emu.run(g, [SRC_SPRITE, x, y if a4 is None else a4, x, y, w, h], clip=clip, plane=bg, painter=painter,
                  period=period)
    want = bytearray(native)
    rewrote = tile_pair_restripe(want, STRIDE, (x, y, x + w, y + h), clip, g)
    return got, bytes(want), bytes(native), rewrote


CELL_RECTS = [
    ("nut_cell_odd", (11, 7, 17, 39), FULL),
    ("nut_cell_even", (30, 8, 16, 40), FULL),
    ("pip_narrow", (51, 13, 3, 12), FULL),
    ("one_column", (70, 21, 1, 12), FULL),
    ("two_rows", (30, 41, 20, 2), FULL),
    ("clip_all_sides", (11, 7, 60, 50), (20, 13, 50, 44)),
    ("clip_top_odd", (11, 7, 60, 50), (0, 16, BW, BH)),
    ("past_the_buffer", (-6, -5, 140, 90), FULL),
]


# ---- (1) the five pairs, every g ---------------------------------------------------------------------------------
@pytest.mark.parametrize("g", G_ALL)
@pytest.mark.parametrize("pair", list(BASE_CELL_PAIRS.values()), ids=list(BASE_CELL_PAIRS))
def test_cell_pairs_follow_the_stripe_law_at_every_g(emu, g, pair):
    rect = (11, 7, 17, 39)
    got, want, native, rewrote = _cell(emu, g, rect, _dither(pair))
    assert got == want, f"g={g}"
    if g <= 16:
        assert got == native and not rewrote, "g <= 16 must be the native tile alone"
        return
    assert rewrote
    T = SL.stripe_rows(g)
    assert SL.stripe_period(g) == 2 * T
    x, y, w, h = rect
    for yy in range(y, y + h):                       # the rule, stated directly
        v = pair[0] if (yy % (2 * T)) < T else pair[1]
        assert set(got[yy * STRIDE + x: yy * STRIDE + x + w]) == {v}, (g, yy)
    if T == 1:
        assert got == native, "1-row stripes on the buffer grid are the native parity dither"


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("name,rect,clip", CELL_RECTS, ids=[r[0] for r in CELL_RECTS])
@pytest.mark.parametrize("pair", [(0x95, 0x96), (0xE0, 0xE2)], ids=["95_96", "e0_e2"])
def test_cell_rects_and_clips(emu, g, name, rect, clip, pair):
    got, want, native, rewrote = _cell(emu, g, rect, _dither(pair), clip=clip)
    assert got == want, f"{name} g={g}"
    assert rewrote == (g > 16)
    bg = bytes(_background())
    x, y, w, h = rect
    x0, y0, x1, y1 = _clip_box(x, y, x + w, y + h, clip)
    for yy in range(BH):                             # nothing outside (rect & clip), gutter included
        for xx in range(STRIDE):
            if not (x0 <= xx < x1 and y0 <= yy < y1):
                assert got[yy * STRIDE + xx] == bg[yy * STRIDE + xx], (name, g, xx, yy)


@pytest.mark.parametrize("g", SCALED)
def test_adjacent_cells_share_one_grid(emu, g):
    """Cells of one sprite at different origins (odd / even tops, a new row of the grid) get the same member on
    the same dest rows: the pattern is continuous across the 1-px gaps and from grid row to grid row."""
    pair = (0x99, 0x98)
    tops = {}
    for rect in ((10, 7, 16, 30), (28, 7, 16, 30), (10, 39, 16, 30), (60, 12, 16, 21)):
        got, want, _native, rewrote = _cell(emu, g, rect, _dither(pair))
        assert got == want and rewrote
        x, y, w, h = rect
        for yy in range(y, y + h):
            tops.setdefault(yy, set()).add(got[yy * STRIDE + x])
    assert all(len(v) == 1 for v in tops.values())
    assert all(next(iter(v)) == (pair[0] if SL.stripe_top(yy, g) else pair[1]) for yy, v in tops.items())


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("name,texel", [
    ("solid_f0_empty_cell", lambda tx, ty: BASE_CELL_SOLID),
    ("two_row_bands", lambda tx, ty: (0x95, 0x96)[(ty >> 1) & 1]),
    ("checker", lambda tx, ty: (0x95, 0x96)[(tx + ty) & 1]),
    ("art_three_indices", lambda tx, ty: (0x95, 0x96, 0x1F)[ty % 3]),
    ("bevel_column", lambda tx, ty: 0x22 if tx == 19 else (0x98, 0x99)[ty & 1]),
    ("one_foreign_pixel", lambda tx, ty: 0x07 if (tx, ty) == (15, 13) else (0x98, 0x99)[ty & 1]),
])
def test_anything_but_a_parity_dither_is_left_as_drawn(emu, g, name, texel):
    got, want, native, rewrote = _cell(emu, g, (10, 7, 30, 40), texel)
    assert not rewrote and got == want == native, f"{name} g={g}"


@pytest.mark.parametrize("g", (22, 25, 40))
def test_mineral_blue_never_gains_e1(emu, g):
    """0xE0's mate here is 0xE2; fe's unconditional E0/E1 family must never be what rewrites these cells."""
    got, want, _native, rewrote = _cell(emu, g, (11, 7, 17, 39), _dither((0xE0, 0xE2)))
    assert rewrote and got == want
    cell = [got[y * STRIDE + x] for y in range(7, 46) for x in range(11, 28)]
    assert set(cell) == {0xE0, 0xE2}


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("name,rect,clip", [
    ("zero_w", (20, 9, 0, 30), FULL), ("zero_h", (20, 9, 30, 0), FULL),
    ("negative_w", (20, 9, -4, 30), FULL), ("negative_h", (20, 9, 30, -4), FULL),
    ("one_row", (20, 9, 30, 1), FULL), ("one_row_clip", (0, 5, BW, 60), (0, 21, BW, 22)),
    ("outside_clip", (10, 7, 20, 10), (40, 30, 80, 60)), ("empty_clip", (10, 7, 60, 30), (30, 20, 30, 20)),
    ("inverted_clip", (10, 7, 60, 30), (50, 40, 30, 20)),
])
def test_degenerate_rects_write_nothing_extra(emu, g, name, rect, clip):
    got, want, native, rewrote = _cell(emu, g, rect, _dither((0x42, 0xDE)), clip=clip)
    assert not rewrote and got == want == native, f"{name} g={g}"


@pytest.mark.parametrize("g", G_SWEEP)
def test_buffer_without_pixels(emu, g):
    """Buffer_tile_2's own early-out (data +0x54 == 0): the restripe must not walk a null plane."""
    bg = _background()
    got = emu.run(g, [SRC_SPRITE, 11, 7, 11, 7, 17, 39], plane=bg, painter=None, data_ptr=0)
    assert got == bytes(bg)


@pytest.mark.parametrize("period,T", [(2, 1), (4, 2), (6, 3)])
def test_period_cell_is_the_only_source_of_T(emu, period, T):
    """The thunk reads g_stripe_period; it never derives T from g (the cell is what thunk_ensure_scale wrote)."""
    pair = (0x5F, 0x60)
    got, _want, _native, _ = _cell(emu, 40, (11, 7, 17, 39), _dither(pair), period=period)
    for yy in range(7, 46):
        assert got[yy * STRIDE + 11] == (pair[0] if (yy % period) < T else pair[1])


def test_tile_pair_law_canonical_member():
    """The even-row member is canonical whatever row the cell starts on (python law, both parities)."""
    for top in (6, 7):
        px = lambda x, y: (0x95, 0x96)[y & 1]        # noqa: E731
        assert tile_pair(px, 3, top, 9, top + 11) == (0x95, 0x96)
    assert tile_pair(lambda x, y: 0xF0, 0, 0, 8, 8) is None
    assert tile_pair(lambda x, y: (0x95, 0x96)[y & 1], 0, 0, 8, 1) is None


# ---- (2) the queue row tile through the existing t_tile_force ------------------------------------------------------
QUEUE_PAIRS = {"selected [0x78D9D0]": (0xE0, 0xE1), "hover [0x78D980]": (0xAE, 0xEE)}


@pytest.fixture(scope="module")
def tf():
    T = pytest.importorskip("test_tileforce_asm_parity")
    return T, T.Emu()


@pytest.mark.parametrize("g", G_ALL)
@pytest.mark.parametrize("pair", list(QUEUE_PAIRS.values()), ids=list(QUEUE_PAIRS))
@pytest.mark.parametrize("phase", [0, 1])
def test_queue_row_tile_via_tile_force(tf, g, pair, phase):
    """A queue row: fl(13*i*g/16) tall rows at odd/even tops, tiled 1:1 from the 24x24 row tile with
    srcOff == dest.  Both pairs are fe's unconditional families, so the plain t_tile_force redirect is enough."""
    T, emu = tf
    i = 3
    y = 5 + SL.basewin_strip_queue_row_y(i, g) % 30
    h = max(2, min(SL.basewin_strip_queue_row_advance(i + 1, g), T.BH - y - 1))
    x, w = 9, 97
    bg = T._background()
    native = bytearray(bg)
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            native[yy * T.STRIDE + xx] = pair[(yy + phase) & 1]

    def painter(l, t, r, b):
        emu.mu.mem_write(T.PLANE, bytes(native))

    got, _call = emu.run(emu.va["t_tile_force"], g, [T.SRC_TILE, x, y, x, y, w, h], 0x1C, plane=bg, painter=painter)
    for yy in range(T.BH):
        for xx in range(T.STRIDE):
            inside = g > 16 and x <= xx < x + w and y <= yy < y + h
            v = native[yy * T.STRIDE + xx]
            assert got[yy * T.STRIDE + xx] == (SL.pair_remap_pixel(v, yy, g) if inside else v), (g, xx, yy)
    if g > 16:
        Tr = SL.stripe_rows(g)
        for yy in range(y, y + h):
            assert got[yy * T.STRIDE + x] == (pair[0] if (yy % (2 * Tr)) < Tr else pair[1])


# ---- (3) the PROPOSED file-dialog list-phase thunks ---------------------------------------------------------------
WIN = DATA + 0x2000                      # a GraphicWin: rRect1.top +0x140, canvas +0x444
CANVAS = WIN + 0x444
NAVY_TILE, SEL_TILE, NATIVE_UNSEL, NATIVE_SEL = 0x00AA0010, 0x00AA0020, 0x00BB0010, 0x00BB0020
SRC_WINBUF = DATA + 0x5000               # Buffer_copy_4's `this` (the parent canvas; discarded when scaled)


class PEmu:
    def __init__(self):
        s = self.syms = SB.load_syms()
        self.props = SB.assemble_proposals(s)
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)
        pages = {s["Buffer_tile"] & ~0xFFF, s["Buffer_copy_4"] & ~0xFFF, s["g_filedlg_rowtile_sel"] & ~0xFFF}
        for p in pages:
            mu.mem_map(p, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        for _name, (off, b, _limit) in self.props.items():
            mu.mem_write(PCAVE2 + off, b)
        mu.mem_write(s["thunk_ensure_stripes"], b"\xC3")
        mu.mem_write(s["Buffer_tile"], b"\xC2\x1C\x00")
        mu.mem_write(s["Buffer_copy_4"], b"\xC2\x1C\x00")
        self.calls = []
        for name in ("thunk_ensure_stripes", "Buffer_tile", "Buffer_copy_4"):
            mu.hook_add(UC_HOOK_CODE, self._hook, user_data=name, begin=s[name], end=s[name])

    def _hook(self, mu, address, size, name):
        esp = mu.reg_read(UC_X86_REG_ESP)
        self.calls.append({"fn": name, "esp": esp, "ret": _r32(mu, esp), "ecx": mu.reg_read(UC_X86_REG_ECX),
                           "args": [_r32(mu, esp + 4 + 4 * i) for i in range(7)]})
        if name == "thunk_ensure_stripes":           # documented contract: preserves ebx/esi/edi, clobbers the rest
            for r, v in ((UC_X86_REG_EAX, 0xE1E1E1E1), (UC_X86_REG_ECX, 0xC1C1C1C1), (UC_X86_REG_EDX, 0xD1D1D1D2)):
                mu.reg_write(r, v)
        else:
            mu.reg_write(UC_X86_REG_EAX, 0)

    def run(self, which, g, active, ecx, args, win_top):
        mu, s = self.mu, self.syms
        _w32(mu, G_VA, g)
        _w32(mu, PERIOD_VA, SL.stripe_period(g))
        _w32(mu, s["g_filedlg_active"], active)
        _w32(mu, s["g_stripe_navy"], NAVY_TILE)
        _w32(mu, s["g_stripe_sel"], SEL_TILE)
        _w32(mu, s["g_filedlg_rowtile_sel"], NATIVE_SEL)
        mu.mem_write(WIN, b"\x00" * 0x500)
        _w32(mu, WIN + 0x140, win_top)
        self.calls.clear()
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, MARKER)
        for i, a in enumerate(args):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, ecx)
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.emu_start(PCAVE2 + self.props[which][0], MARKER, count=100_000)
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x1C, "stack imbalance (RET 0x1C contract)"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == REGS[r]
        assert bytes(mu.mem_read(sp + 0x20, 0x100)) == b"\xA5" * 0x100
        return list(self.calls), sp


@pytest.fixture(scope="module")
def pemu():
    return PEmu()


LIST_TOPS = (0, 1, 2, 3, 50, 57, 65, 80, 105, 0x7FFFFFF1, -3 & 0xFFFFFFFF)


@pytest.mark.parametrize("g", SCALED)
@pytest.mark.parametrize("top", LIST_TOPS)
@pytest.mark.parametrize("tile,want_tile", [(NATIVE_UNSEL, NAVY_TILE), (NATIVE_SEL, SEL_TILE)])
def test_proposed_rowbg_adds_the_list_phase(pemu, g, top, tile, want_tile):
    x, y, w, h = 0, 37, 300, 23
    calls, sp = pemu.run("thunk_filedlg_rowbg_v6", g, 1, CANVAS, [tile, x, y, x, y, w, h], top)
    assert [c["fn"] for c in calls] == ["thunk_ensure_stripes", "Buffer_tile"]
    c = calls[1]
    assert c["ecx"] == CANVAS and c["esp"] == sp and c["ret"] == MARKER, "tail-jump into the native Buffer_tile"
    assert c["args"][0] == want_tile and c["args"][1] == x and c["args"][3:] == [x, y, w, h]
    phase = (c["args"][2] - y) & 0xFFFFFFFF
    assert phase < 4 and phase % SL.stripe_period(g) == list_stripe_phase(_s32(top), g)


@pytest.mark.parametrize("g", SCALED)
@pytest.mark.parametrize("top", LIST_TOPS)
def test_proposed_copy4_tiles_the_backdrop_on_the_parent_grid(pemu, g, top):
    w, h = 476, 450
    calls, _sp = pemu.run("thunk_copy4_stripes", g, 1, SRC_WINBUF, [CANVAS, 28, _s32(top) & 0xFFFFFFFF, 0, 0, w, h], top)
    assert [c["fn"] for c in calls] == ["thunk_ensure_stripes", "Buffer_tile"]
    c = calls[1]
    assert c["ecx"] == CANVAS
    assert c["args"][0] == NAVY_TILE and c["args"][1] == 0 and c["args"][3:] == [0, 0, w, h]
    assert c["args"][2] < 4 and c["args"][2] % SL.stripe_period(g) == list_stripe_phase(_s32(top), g)


@pytest.mark.parametrize("which,native,ecx,args", [
    ("thunk_filedlg_rowbg_v6", "Buffer_tile", CANVAS, [NATIVE_UNSEL, 0, 37, 0, 37, 300, 23]),
    ("thunk_copy4_stripes", "Buffer_copy_4", SRC_WINBUF, [CANVAS, 28, 50, 0, 0, 476, 450]),
])
@pytest.mark.parametrize("g,active", [(16, 1), (12, 1), (25, 0), (40, 0), (16, 0)])
def test_proposed_thunks_native_paths_are_untouched(pemu, which, native, ecx, args, g, active):
    calls, sp = pemu.run(which, g, active, ecx, args, 50)
    assert [c["fn"] for c in calls] == [native]
    c = calls[0]
    assert c["esp"] == sp and c["ret"] == MARKER and c["ecx"] == ecx and c["args"] == args


@pytest.mark.parametrize("g", (22, 25, 40))
def test_proposed_copy4_null_dest_draws_nothing(pemu, g):
    """The engine passes dst = 0 when its window pointer is null (0x60BB88 / 0x60C3EF); the native copy returns
    at once for it, so the replacement must neither read [0 - 0x304] nor tile."""
    calls, _sp = pemu.run("thunk_copy4_stripes", g, 1, SRC_WINBUF, [0, 28, 50, 0, 0, 476, 450], 50)
    assert [c["fn"] for c in calls] == ["thunk_ensure_stripes"]


def _stripe_tile_row(ty: int, g: int, pair=(0xC4, 0x41)) -> int:
    """thunk_ensure_stripes' scratch tile: P rows, the top member on rows [0, T)."""
    return pair[0] if ty < SL.stripe_rows(g) else pair[1]


def _composite_column(g: int, list_top: int, list_h: int, phase: int, margin: int = 24) -> list[int]:
    """One screen column through parent ring / list / parent ring.  The parent's ring is on the parent buffer
    grid (thunk_fe_pair_remap: stripe_top(parent y)); the list rows come from Buffer_tile, whose tile row for
    list row y is (y + srcOffY - dstY) mod P (0x5DA95B: start = dst - srcOff mod tileH)."""
    P = SL.stripe_period(g)
    col = []
    for py in range(list_top - margin, list_top + list_h + margin):
        if list_top <= py < list_top + list_h:
            col.append(_stripe_tile_row((py - list_top + phase) % P, g))
        else:
            col.append(0xC4 if SL.stripe_top(py, g) else 0x41)
    return col


def _runs(col):
    out, n = [], 1
    for a, b in zip(col, col[1:]):
        if a == b:
            n += 1
        else:
            out.append(n)
            n = 1
    return out + [n]


# FileDlg_layout list rects, window-local native (top, bottom): in-game {28,32,333,320}, main menu {14,42,319,330}
FILEDLG_LISTS = {"in_game": (32, 320), "main_menu": (42, 330)}


@pytest.mark.parametrize("g", SCALED)
@pytest.mark.parametrize("which", list(FILEDLG_LISTS))
def test_list_on_the_parent_grid_has_no_seam(g, which):
    t, b = (SL.popup_scale_floor(v, g) for v in FILEDLG_LISTS[which])
    col = _composite_column(g, t, b - t, list_stripe_phase(t, g))
    T = SL.stripe_rows(g)
    assert set(_runs(col)[1:-1]) == {T}, (g, which)


def test_buffer_local_phase_reproduces_the_measured_seam():
    """Today's producers (phase 0).  1600x1200 = g 25, in-game dialog: list top 50, height 450 -> one 4-row navy
    band at each end of the list, as measured on 20261004-221651 (screen y 290..293 and 740..743)."""
    g = 25
    t, b = (SL.popup_scale_floor(v, g) for v in FILEDLG_LISTS["in_game"])
    assert (t, b - t) == (50, 450)
    col = _composite_column(g, t, b - t, 0)
    runs = _runs(col)[1:-1]
    assert sorted(set(runs)) == [2, 4] and runs.count(4) == 2
    seamed = [g2 for g2 in SCALED
              if set(_runs(_composite_column(g2, SL.popup_scale_floor(32, g2),
                                             SL.popup_scale_floor(320, g2) - SL.popup_scale_floor(32, g2), 0))[1:-1])
              != {SL.stripe_rows(g2)}]
    assert seamed == [g2 for g2 in SCALED if g2 >= 22 and g2 % 2 == 1], "in-game dialog: every odd g from 23 up"
    menu = [g2 for g2 in (18, 22, 25, 40)
            if set(_runs(_composite_column(g2, SL.popup_scale_floor(42, g2),
                                           SL.popup_scale_floor(330, g2) - SL.popup_scale_floor(42, g2), 0))[1:-1])
            != {SL.stripe_rows(g2)}]
    assert menu == [18, 22, 25, 40], "main-menu dialog (list top 42): seamed at 1600x900, 1080, 1600x1200 and 4K"


def test_and3_is_the_period_modulo_at_every_popup_g():
    """The asm takes `top & 3`; that is top mod P only while P divides 4."""
    assert {SL.stripe_period(g) for g in SCALED} <= {2, 4}


# ---- layout, templates, sites --------------------------------------------------------------------------------------
def test_layout_and_templates():
    syms = SB.load_syms()
    layout = SB.assemble_all(syms)
    assert set(layout) == set(SB.THUNK_ORDER)
    for name, (off, b) in layout.items():
        assert SB.OFF_CODE <= off and off + len(b) <= SB.OFF_LIMIT, f"{name} leaves the gap"
        assert b[-3:] == b"\xC2\x1C\x00", "RET 0x1C contract tail"
    assert SB.roundtrip_problems(layout, syms) == []
    sites = SB.site_list()
    assert len(sites) == 3 and len({s["va"] for s in sites}) == 3
    assert {s["thunk"] for s in sites} == {"t_sb_tile2", "t_tile_force"}


def test_proposals_fit_their_slots_and_round_trip():
    syms = SB.load_syms()
    for name, (off, tpl, n, limit) in SB.proposal_templates(syms).items():
        assert off + n <= limit, name
        assert "{abs32:g_filedlg_active}" in tpl and "{rel32:thunk_ensure_stripes}" in tpl
        assert tpl.startswith("83 3D {abs32:g_filedlg_active} 00 74 09 83 3D {abs32:g_popup_scale_num} 10 7F 06 68"), \
            "the gate + native tail must stay byte-identical to the shipped thunk"


def test_sites_match_the_pristine_base():
    import config
    if not config.terranx_bak(required=False).exists():
        pytest.skip("pristine .bak absent")
    assert SB.verify_live(SB.site_list()) == []
