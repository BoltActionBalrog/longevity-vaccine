"""Differential: the MENU strip column map (W9C F55, 2026-10-27) -- t_mc_synth / t_mc_dims / t_mc_col and the
hm_synth_core they ride, run from the BAKED image under Unicorn (image_emu.Emu: every section mapped, no boot), against
the laws:

    t_mc_synth(0x938520, dx, dy, num, den, spr) == scaling_laws.menu_strip_synth   (a 139-wide sprite, g > 16)
                                                == scaling_laws.strip_synth        (any other sprite width / dest)
    g <= 16: the dest untouched (the core's own gate)

for every g 17..64 at both (num, den) the MENU strips are drawn with -- (sc(18), 18) for the 18-row strips and (g, 16)
for the 6-row title (thunk_hudmenu_sd2's sd2_menu) -- on a synthetic strip carrying every class the law treats
differently: a vertical A,B,A,B dither pair (remapped onto the stripe law), the two side-line columns, the brown edge
column, unique per-column values (so a wrong column shows) and key texels (skipped).  Also: g_mc_on is 0 after every
call (COMMLINK and the button faces keep the plain core), ebx / esi / edi / ebp are kept, the assembler's template
equals the yaml bytes, and hm_synth_core's two CALL-helper blocks are the only bytes that changed in it.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402
import apply_patches as ap  # noqa: E402
import image_emu as E  # noqa: E402
import assemble_menu_strip as MS  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI  # noqa: E402

G_VA, PER_VA = 0x668740, 0x66879C
MENU_BUF = 0x938520
KEY = 9
PAIR = (197, 65)
REGS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333,
        UC_X86_REG_EBP: 0x44444444}


@pytest.fixture(scope="module")
def emu(baked_exe):
    e = E.Emu(str(baked_exe), 1024, 768)
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    e.sym = dict(ap.build_symbol_table(symbols, caves))
    e.dbuf = e.alloc(600 * 80)
    e.other = e.alloc(0x600)
    e.spr = e.alloc(0x40)
    e.sdata = e.alloc(260 * 20)
    return e


def strip(w: int, h: int):
    """Rows of a synthetic strip: the fill a vertical dither pair (top on even rows), the line columns 4 / 133 (191),
    the brown edge 138 (233), every other column a unique value in a band the pair never uses, a few key texels."""
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            if x in (SL.HUDMENU_STRIP_LINE_L, SL.HUDMENU_STRIP_EDGE - 1 - SL.HUDMENU_STRIP_LINE_L):
                row.append(191)
            elif x == SL.HUDMENU_STRIP_EDGE:
                row.append(233)
            elif (x * 7 + y) % 23 == 0:
                row.append(KEY)
            elif x % 3 == 0:
                row.append(PAIR[y % 2])
            else:
                row.append(10 + x % 100)
        rows.append(row)
    return rows


def setup(e, rows, dst, bw, bh):
    sh, sw = len(rows), len(rows[0])
    e.uc.mem_write(e.sdata, bytes(v for r in rows for v in r))
    e.uc.mem_write(e.spr, bytes(0x40))
    e.w32(e.spr + 4, e.sdata)
    e.uc.mem_write(e.spr + 8, bytes([KEY]))
    for off, v in ((0xC, sw), (0x10, sw), (0x14, sh), (0x18, sw), (0x1C, sh)):
        e.w32(e.spr + off, v)
    e.w32(dst + 0x54, e.dbuf)
    e.w32(dst + 0x4A8, bw)
    e.w32(dst + 0x80, bw)
    e.w32(dst + 0x84, -bh)
    init = bytes((i * 13) % 251 for i in range(bw * bh))
    e.uc.mem_write(e.dbuf, init)
    return bytearray(init)


def run(e, g, dst, dx, dy, num, den):
    e.w32(G_VA, g)
    e.w32(PER_VA, SL.stripe_period(g))
    e.call(MS.PCAVE2 + MS.LAYOUT["t_mc_synth"][0],
           args=(dst, dx & 0xFFFFFFFF, dy & 0xFFFFFFFF, num, den, e.spr), regs=dict(REGS))
    assert [e.uc.reg_read(r) for r in REGS] == list(REGS.values())
    assert e.r32(e.sym["g_mc_on"]) == 0


def sc18(g):
    return (18 * g + 8) >> 4


@pytest.mark.parametrize("g", list(range(17, 41)) + [44, 48, 56, 64])
def test_menu_strips_take_the_mirrored_column_map(emu, g):
    e = emu
    for h, num, den in ((18, sc18(g), 18), (6, g, 16)):
        rows = strip(SL.HUDMENU_STRIP_W, h)
        bw = SL.menu_strip_dest_w(g) + 3                           # the buffer a little wider: the law stops at W
        bh = SL.strip_synth_dims(SL.HUDMENU_STRIP_W, h, num, den)[1] + 4
        for dx, dy in ((0, 0), (0, 2), (1, 1)):
            want = setup(e, rows, MENU_BUF, bw, bh)
            SL.menu_strip_synth(want, bw, bw, bh, rows, KEY, dx, dy, num, den, g)
            run(e, g, MENU_BUF, dx, dy, num, den)
            got = bytes(e.uc.mem_read(e.dbuf, bw * bh))
            assert got == bytes(want), (g, h, dx, dy)


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_other_strips_keep_the_plain_core(emu, g):
    """A 138-wide strip into the MENU buffer, a 139-wide strip into another buffer: strip_synth exactly (the core
    with g_mc_on clear -- t_mc_dims / t_mc_col reproduce the blocks they replaced)."""
    e = emu
    for w, dst in ((138, MENU_BUF), (139, e.other), (60, e.other)):
        rows = strip(w, 18)
        for num, den in ((sc18(g), 18), (g, 16)):
            dw, dh = SL.strip_synth_dims(w, 18, num, den)
            bw, bh = dw + 5, dh + 3
            want = setup(e, rows, dst, bw, bh)
            SL.strip_synth(want, bw, bw, bh, rows, KEY, 2, 1, num, den, g)
            run(e, g, dst, 2, 1, num, den)
            assert bytes(e.uc.mem_read(e.dbuf, bw * bh)) == bytes(want), (g, w, hex(dst), num, den)


@pytest.mark.parametrize("g", [8, 12, 16])
def test_native_leaves_the_dest(emu, g):
    e = emu
    rows = strip(SL.HUDMENU_STRIP_W, 18)
    want = setup(e, rows, MENU_BUF, 150, 30)
    run(e, g, MENU_BUF, 0, 0, 18, 18)
    assert bytes(e.uc.mem_read(e.dbuf, 150 * 30)) == bytes(want)


def test_law_shape():
    """The layout is mirrored, every zone within 1 px of vanilla x g/16, W = the window; g <= 16 the identity."""
    assert SL.menu_strip_col_map(16) == list(range(139))
    for g in range(17, 65):
        w, i, k, m, b = SL.menu_strip_zones(g)
        cm = SL.menu_strip_col_map(g)
        assert len(cm) == w == (139 * g + 8) >> 4 and w == 2 * i + 2 * k + m + b
        assert k == b == SL.stroke_width(g)
        assert abs(16 * i - 4 * g) <= 16 and abs(16 * m - 128 * g) <= 16, (g, i, m)
        r = w - b
        assert cm[r:] == [138] * b
        assert all(cm[r - 1 - j] == 137 - cm[j] for j in range(r) if 2 * j != r - 1)
        assert [j for j in range(w) if cm[j] == 4] == list(range(i, i + k))
        assert [j for j in range(w) if cm[j] == 133] == list(range(r - i - k, r - i))


def test_yaml_matches_assembler():
    _s, _g, caves, _sym = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    by = {e["id"]: " ".join(str(e["bytes"]).split()) for c in caves for e in (c.get("contents") or [])}
    for n in MS.ORDER:
        assert by[n] == MS.template(n), n
