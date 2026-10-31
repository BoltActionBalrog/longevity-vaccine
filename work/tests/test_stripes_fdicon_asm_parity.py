"""Differential: t_fdicon_checker (scripts/assemble_stripes_fdicon.py) under Unicorn, chained to the REAL
thunk_checkbox_scale bytes resolved from patches.yaml, must leave the dest plane equal to

    the plain g/16 enlarged icon draw, with every 0xA3 / 0x47 pixel of the walked rect rewritten to
    fdicon_checker_pixel(v, x, y, g)  (T x T device cells on the DEST-BUFFER grid, T = scaling_laws.stripe_rows(g))

and nothing else changed; g <= 16 is the existing path alone (tail-jump, stack and registers as the site left them).

Sprite_draw_2 is a `ret 0x18` stub with a Python-side hook that paints the synthetic icon the way the engine's
scaled path was read to (Sprite_blit_scaled_core 0x5E4ECE: dest rect = ftol(x + trimX*s), ftol(trimW*s) ..., & the
dest clip; nearest neighbour) and records the stack/registers it was entered with.  The three sprites are the
16x16 Jackal.pcx cells (1,1) / (18,1) / (35,1) with the engine's +10 palette shift, as measured on the Load shots.

Skips (does not fail) if keystone/unicorn are absent.  Run with -p no:faulthandler.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_stripes_fdicon as FD  # noqa: E402

G_SWEEP = (16, 18, 21, 22, 25, 32, 40)
TOP, MATE = 0xA3, 0x47
assert (TOP, MATE) == (FD.CHECK_TOP, FD.CHECK_MATE)


# ---- THE LAW (to be moved to scaling_laws.py) -------------------------------------------------------------------
def fdicon_checker_pixel(v: int, x: int, y: int, g: int) -> int:
    """File-dialog icon face: the native 1-px A3/47 checkerboard regenerated at device density.  A pixel that
    holds either member takes the member of its T x T device cell on the dest buffer's own grid,
    T = stripe_rows(g) (the one stripe thickness; P = 2T is g_stripe_period).  g <= 16 and every other index:
    unchanged."""
    if g <= 16 or v not in (TOP, MATE):
        return v
    t = SL.stripe_rows(g)
    return TOP if ((x // t) + (y // t)) & 1 == 0 else MATE


def fdicon_walk_rect(x: int, y: int, g: int) -> tuple[int, int, int, int]:
    """Half-open superset of the icon's drawn rect that the thunk walks (before the clip): the blit writes inside
    [x, x + g) x [y', y' + g), y' = y + ((16 - g) >> 1) (thunk_checkbox_scale's re-centre); 1 px / 2 px slack."""
    yn = y + ((16 - g) >> 1)
    return x - 1, yn - 1, x + g + 2, yn + g + 2


# ---- measured art ------------------------------------------------------------------------------------------------
FOLDER = (
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    "FFFFFFAEAEAEAEAEFFFFFFFFFFFFFFFF",
    "FFFFAEA347A347A3AEFFFFFFFFFFFFFF",
    "FFAEAEAEAEAEAEAEAEAEAEAEAEAEAEFF",
    "FFAE47A347A347A347A347A347A34CAE",
    "FFAEA347A347A347A347A347A347D3AE",
    "FFAE47A347A347A347A347A347A34CAE",
    "FFAEA347A347A347A347A347A347D3AE",
    "FFAE47A347A347A347A347A347A34CAE",
    "FFAEA347A347A347A347A347A347D3AE",
    "FFAE47A347A347A347A347A347A34CAE",
    "FFAEA347A347A347A347A347A347D3AE",
    "FFAE4CD34CD34CD34CD34CD34CD34CAE",
    "FFAEAEAEAEAEAEAEAEAEAEAEAEAEAEAE",
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
)
FILE = (
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    "FFAEAEAEAEAEAEAEAEAEAEAEAEAEAEAE",
    "FFAE41414141414141414141414141AE",
    "FFAE41A347A347A347A347A347A341AE",
    "FFAE4147A347A347A347A347A34741AE",
    "FFAE41A347A347A347A347A347A341AE",
    "FFAE4147A347A347A347A347A34741AE",
    "FFAE41A347A347A347A347A347A341AE",
    "FFAE41414141A347A347A347525241AE",
    "FFAE41646441414141414141414141AE",
    "FFAE41525252525252525252646441AE",
    "FFAE41414141232323232323414141AE",
    "FFAE41414141414141414141414141AE",
    "FFAEAEAEAEAEAEAEAEAEAEAEAEAEAEAE",
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
)
UPDIR = (
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    "FFFFFFAEAEAEAEAEFFFFFFFFFFFFFFFF",
    "FFFFAEA347A347A3AEFFFFFFFFFFFFFF",
    "FFAEAEAEAEAEAEAEAEAEAEAEAEAEAEFF",
    "FFAE47A347A347A347A347A347A34CAE",
    "FFAEA347A3474147A347A347A347D3AE",
    "FFAE47A34741414147A347A347A34CAE",
    "FFAEA347414141414147A347A347D3AE",
    "FFAE47A347A341A347A347A347A34CAE",
    "FFAEA347A3474147A347A347A347D3AE",
    "FFAE47A347A341414141414147A34CAE",
    "FFAEA347A347A347A347A347A347D3AE",
    "FFAE4CD34CD34CD34CD34CD34CD34CAE",
    "FFAEAEAEAEAEAEAEAEAEAEAEAEAEAEAE",
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
)
KEY = 0xFF
ICONS = {n: [list(bytes.fromhex(r)) for r in rows] for n, rows in (("folder", FOLDER), ("file", FILE), ("updir", UPDIR))}


def test_measured_art_facts():
    """The content key's premise: inside the icons 0xA3 / 0x47 occur ONLY as a 1-px 2-D checker."""
    for name, cell in ICONS.items():
        assert len(cell) == 16 and all(len(r) == 16 for r in cell)
        phases = {(x + y + (v == MATE)) % 2 for y in range(16) for x in range(16)
                  for v in (cell[y][x],) if v in (TOP, MATE)}
        assert len(phases) == 1, name                          # one checker phase per icon, no solid use
        assert sum(v in (TOP, MATE) for r in cell for v in r) >= 50, name


# ---- emulator ----------------------------------------------------------------------------------------------------
PCAVE2, CAVE_LEN = FD.PCAVE2, 0x31000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect)
G_VA, PERIOD_VA = FD.G, FD.PERIOD
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
BUF = DATA + 0x100
SPRITE = DATA + 0x800
PLANE = DATA + 0x10000
BW, BH, STRIDE = 120, 96, 128
F_CLIP, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0x4A8
REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9, UC_X86_REG_EAX: 0x0EA0EA0E, UC_X86_REG_EDX: 0x0ED0ED0E}
STUB_EAX, STUB_ECX, STUB_EDX = 0x00C0FFEE, 0xCCCC0001, 0xDDDD0002


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def _real_checkbox_scale():
    """thunk_checkbox_scale exactly as patches.yaml ships it (the callee this drop-in wraps)."""
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    table = ap.build_symbol_table(symbols, caves)
    for cave in caves:
        for ent in cave.get("contents") or []:
            if isinstance(ent, dict) and ent.get("id") == "thunk_checkbox_scale":
                va = table["thunk_checkbox_scale"]
                assert va == int(cave["virtual_addr"]) + int(ent["offset"])
                return va, bytes(ap.ByteTemplate(ent["bytes"]).resolve(va, table))
    raise AssertionError("thunk_checkbox_scale content not found in patches.yaml")


def _trim(cell):
    xs = [x for y in range(16) for x in range(16) if cell[y][x] != KEY]
    ys = [y for y in range(16) for x in range(16) if cell[y][x] != KEY]
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def drawn_rect(cell, x, y, num, den):
    """The engine's scaled dest rect before the clip (0x5E4ECE: ftol of x + trim*s and of trimW/H*s, s float32)."""
    tx, ty, tw, th = _trim(cell)
    s = _f32(num / den)
    l, t = int(x + tx * s), int(y + ty * s)
    return l, t, l + int(tw * s), t + int(th * s)


def paint_icon(plane, cell, x, y, num, den, clip):
    """Keyed nearest-neighbour enlarge of the trimmed cell into `plane`, clipped like the engine (dest +0x20)."""
    tx, ty, tw, th = _trim(cell)
    l, t, r, b = drawn_rect(cell, x, y, num, den)
    dw, dh = r - l, b - t
    for j in range(dh):
        yy = t + j
        if not (max(clip[1], 0) <= yy < min(clip[3], BH)):
            continue
        for i in range(dw):
            xx = l + i
            if not (max(clip[0], 0) <= xx < min(clip[2], BW)):
                continue
            v = cell[ty + min(th - 1, j * th // dh)][tx + min(tw - 1, i * tw // dw)]
            if v != KEY:
                plane[yy * STRIDE + xx] = v


class Emu:
    def __init__(self):
        self.syms = FD.load_syms()
        self.layout = FD.assemble_all(self.syms)
        self.entry = FD.names_of(self.layout)["t_fdicon_checker"]
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)
        mu.mem_map(FD.SPRITE_DRAW_2 & ~0xFFF, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        cb_va, cb = _real_checkbox_scale()
        assert cb_va == self.syms["thunk_checkbox_scale"] and (cb_va & ~0xFFF) == (G_VA & ~0xFFF)
        mu.mem_write(cb_va, cb)
        off, code = self.layout["t_fdicon_checker"]
        mu.mem_write(PCAVE2 + off, code)
        mu.mem_write(FD.SPRITE_DRAW_2, b"\xC2\x18\x00")           # ret 0x18 (the native contract)
        self.calls, self.errors, self.painter = [], [], None
        mu.hook_add(UC_HOOK_CODE, self._on_draw, begin=FD.SPRITE_DRAW_2, end=FD.SPRITE_DRAW_2)

    def _on_draw(self, mu, address, size, user):
        try:
            esp = mu.reg_read(UC_X86_REG_ESP)
            rec = {"esp": esp, "ret": _r32(mu, esp), "ecx": mu.reg_read(UC_X86_REG_ECX),
                   "args": [_r32(mu, esp + 4 + 4 * i) for i in range(6)],
                   "regs": {r: mu.reg_read(r) for r in REGS}}
            self.calls.append(rec)
            if self.painter:
                self.painter(*(_s32(a) for a in rec["args"]))
            mu.reg_write(UC_X86_REG_EAX, STUB_EAX)
            mu.reg_write(UC_X86_REG_ECX, STUB_ECX)
            mu.reg_write(UC_X86_REG_EDX, STUB_EDX)
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    def run(self, g, cell, x, y, *, plane, clip=(0, 0, BW, BH), dest=BUF, data_ptr=PLANE, period=None, key=KEY):
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
        live = bytearray(plane)

        def painter(a_dest, a_key, ax, ay, num, den):
            if a_dest and data_ptr and cell is not None:
                paint_icon(live, cell, ax, ay, num, den, clip)
                mu.mem_write(PLANE, bytes(live))
        self.painter = painter
        args = [dest, key, x, y, 1, 1]                           # the site's own num/den are 1, 1
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, MARKER)
        for i, a in enumerate(args):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, SPRITE)
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.emu_start(self.entry, MARKER, count=20_000_000)
        assert not self.errors, self.errors
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER, "did not return to the caller"
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18, "stack imbalance (thiscall, six args: RET 0x18)"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == REGS[r], "callee-saved register not preserved"
        assert mu.reg_read(UC_X86_REG_EAX) == STUB_EAX, "eax must be the native draw's result"
        assert mu.reg_read(UC_X86_REG_ECX) == STUB_ECX and mu.reg_read(UC_X86_REG_EDX) == STUB_EDX
        assert bytes(mu.mem_read(sp - 0x400, 0x400 - 0x80)) == b"\xA5" * (0x400 - 0x80), "stack use deeper than 0x80"
        assert bytes(mu.mem_read(sp + 4 + 0x18, 0x100)) == b"\xA5" * 0x100, "wrote above its own args"
        assert len(self.calls) == 1, "Sprite_draw_2 must run exactly once"
        c = self.calls[0]
        yn = y + ((16 - g) >> 1)
        assert c["ecx"] == SPRITE, "the sprite `this` must reach the draw"
        assert [_s32(a) for a in c["args"]] == [_s32(dest), key, x, yn, g, 16], "thunk_checkbox_scale's rewrite"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_EAX, UC_X86_REG_EDX):
            assert c["regs"][r] == REGS[r], "the draw must see the site's registers"
        if g <= 16:
            assert c["esp"] == sp and c["ret"] == MARKER, "g <= 16 must be a pure tail-jump"
        else:
            assert c["esp"] == sp - 0x1C and c["ret"] != MARKER
        return bytes(mu.mem_read(PLANE, STRIDE * BH)), bytes(live)


@pytest.fixture(scope="module")
def emu():
    return Emu()


_HOSTILE = (0x41, 0xC4, 0xA3, 0xE0, 0x47, 0xE1, 0xAE, 0x4C, 0xD3, 0xA3, 0xA3, 0x47, 0x52, 0xE2, 0x47)


def _hostile():
    """Both members everywhere (and every other icon index): any write outside the walked rect shows."""
    return bytearray(_HOSTILE[(x * 7 + y * 3) % len(_HOSTILE)] for y in range(BH) for x in range(STRIDE))


def _row_bg(selected=False):
    """What is really behind an icon (measured, 1600x1200): 2-row C4/41 stripes; selected row E0/E1; E2 text."""
    a, b = (0xE0, 0xE1) if selected else (0xC4, 0x41)
    p = bytearray((a if (y // 2) % 2 == 0 else b) for y in range(BH) for _x in range(STRIDE))
    for y in range(4, BH, 9):
        for x in range(70, 110, 3):
            p[y * STRIDE + x] = 0xE2
    return p


def _expect(plain, x, y, g, clip):
    """The law over the walked rect & clip & buffer; everything else = the plain draw."""
    out = bytearray(plain)
    if g <= 16:
        return bytes(out)
    l, t, r, b = fdicon_walk_rect(x, y, g)
    for yy in range(max(t, clip[1], 0), min(b, clip[3], BH)):
        for xx in range(max(l, clip[0], 0), min(r, clip[2], BW)):
            out[yy * STRIDE + xx] = fdicon_checker_pixel(plain[yy * STRIDE + xx], xx, yy, g)
    return bytes(out)


POSITIONS = [("even", 30, 40), ("odd", 31, 43), ("x_odd", 7, 50), ("edge", 0, 30)]
CLIPS = [("whole", (0, 0, BW, BH)), ("through_icon", (38, 36, 52, 55)), ("row", (0, 34, BW, 62)),
         ("left_half", (0, 0, 44, BH)), ("empty", (60, 60, 60, 60)), ("inverted", (80, 70, 20, 10)),
         ("beyond_buffer", (-9, -9, BW + 40, BH + 40))]


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("icon", sorted(ICONS))
@pytest.mark.parametrize("pos", POSITIONS, ids=[p[0] for p in POSITIONS])
@pytest.mark.parametrize("clip", CLIPS, ids=[c[0] for c in CLIPS])
def test_checker_matches_the_law_on_a_hostile_plane(emu, g, icon, pos, clip):
    _n, x, y = pos
    _cn, cl = clip
    bg = _hostile()
    got, plain = emu.run(g, ICONS[icon], x, y, plane=bg, clip=cl)
    assert got == _expect(plain, x, y, g, cl), f"{icon} g={g}"
    if g <= 16:
        assert got == plain, "g <= 16 must be the plain draw alone"
    for yy in range(BH):                                     # nothing but the two members is ever rewritten
        for xx in range(STRIDE):
            if plain[yy * STRIDE + xx] not in (TOP, MATE):
                assert got[yy * STRIDE + xx] == plain[yy * STRIDE + xx], (xx, yy)
            else:
                assert got[yy * STRIDE + xx] in (TOP, MATE)


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("icon", sorted(ICONS))
@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("pos", POSITIONS[:3], ids=[p[0] for p in POSITIONS[:3]])
def test_real_row_only_the_face_changes(emu, g, icon, selected, pos):
    """On the measured row backgrounds: the face is the T x T checker, every outline / glyph / shadow / highlight
    pixel and every pixel outside the icon's drawn rect is byte-identical to the plain enlarged draw."""
    _n, x, y = pos
    cell = ICONS[icon]
    bg = _row_bg(selected)
    got, plain = emu.run(g, cell, x, y, plane=bg)
    l, t, r, b = drawn_rect(cell, x, y + ((16 - g) >> 1), g, 16)
    wl, wt, wr, wb = fdicon_walk_rect(x, y, g)
    assert wl <= l and wt <= t and r <= wr and b <= wb, "the walked rect must contain the engine's drawn rect"
    T = SL.stripe_rows(g)
    face = 0
    for yy in range(BH):
        for xx in range(STRIDE):
            p, q = plain[yy * STRIDE + xx], got[yy * STRIDE + xx]
            inside = l <= xx < r and t <= yy < b
            if inside and p in (TOP, MATE):
                face += 1
                if g > 16:
                    assert q == (TOP if ((xx // T) + (yy // T)) & 1 == 0 else MATE), (g, xx, yy)
                else:
                    assert q == p
            else:
                assert q == p, (g, xx, yy, hex(p), hex(q))
    assert face >= 50
    if g > 16:                                                # both members really present: a checker, not a fill
        vals = {got[yy * STRIDE + xx] for yy in range(t, b) for xx in range(l, r)} & {TOP, MATE}
        assert vals == {TOP, MATE}


@pytest.mark.parametrize("g", (18, 22, 25, 40))
def test_idempotent_and_shared_grid(emu, g):
    """A redraw (hover / selection repaint) over an already regenerated icon gives the same pixels, and two icons
    at different origins share one dest-grid phase."""
    cell = ICONS["folder"]
    got1, _ = emu.run(g, cell, 30, 40, plane=_row_bg())
    got2, _ = emu.run(g, cell, 30, 40, plane=bytearray(got1))
    assert got1 == got2
    got3, _ = emu.run(g, cell, 33, 41, plane=bytearray(got1))
    T = SL.stripe_rows(g)
    for yy in range(BH):
        for xx in range(BW):
            v = got3[yy * STRIDE + xx]
            if v in (TOP, MATE):
                assert v == (TOP if ((xx // T) + (yy // T)) & 1 == 0 else MATE)


@pytest.mark.parametrize("g", G_SWEEP)
def test_no_dest_no_plane_no_period(emu, g):
    """dest NULL (the caller passes 0 when its window arg is 0), a Buffer without pixels, and an unset period cell
    must not walk anything (and must not divide by zero)."""
    bg = _hostile()
    got, _ = emu.run(g, None, 30, 40, plane=bg, dest=0)
    assert got == bytes(bg)
    got, _ = emu.run(g, None, 30, 40, plane=bg, data_ptr=0)
    assert got == bytes(bg)
    for period in (0, 1):
        got, plain = emu.run(g, ICONS["file"], 30, 40, plane=bg, period=period)
        assert got == plain


def test_period_cell_is_the_law(emu):
    """T comes from g_stripe_period / 2: a future 3-row law (P = 6) needs no reassembly."""
    cell = ICONS["folder"]
    got, plain = emu.run(40, cell, 30, 40, plane=_row_bg(), period=6)
    for yy in range(BH):
        for xx in range(BW):
            if plain[yy * STRIDE + xx] in (TOP, MATE):
                assert got[yy * STRIDE + xx] == (TOP if ((xx // 3) + (yy // 3)) & 1 == 0 else MATE)


def test_layout_and_templates():
    syms = FD.load_syms()
    layout = FD.assemble_all(syms)
    off, b = layout["t_fdicon_checker"]
    assert off == FD.OFF_CODE and off % 16 == 0 and off + len(b) <= FD.OFF_LIMIT
    assert b[-3:] == b"\xC2\x18\x00"
    assert FD.roundtrip_problems(layout, syms) == [], "yaml templates must resolve back to the assembled bytes"
    sites = FD.site_list()
    assert [s["va"] for s in sites] == [0x614CC8, 0x614D24, 0x614D7E]


def test_sites_are_the_existing_checkbox_redirects():
    """The three sites already exist in patches.yaml (group filedlg_rows); this change only retargets them."""
    sites, _groups, _caves, _symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    by_va = {int(s["virtual_addr"]): s for s in sites if "virtual_addr" in s}
    for s in FD.site_list():
        cur = by_va[s["va"]]
        assert cur["id"] == s["id"] and cur.get("group") == FD.GROUP
        assert bytes.fromhex(cur["original_bytes"].replace(" ", "")) == s["orig"]
        assert "thunk_checkbox_scale" in cur["new_bytes"] or "t_fdicon_checker" in cur["new_bytes"]


def test_sites_match_the_pristine_base():
    import config
    if not config.terranx_bak(required=False).exists():
        pytest.skip("pristine .bak absent")
    assert FD.verify_live(FD.site_list()) == []
