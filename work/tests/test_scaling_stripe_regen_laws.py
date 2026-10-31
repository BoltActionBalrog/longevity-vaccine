"""The "stripe regeneration" laws of scaling_laws.py (fix 7, 2026-10-17), tested as laws -- no emulator.

The byte-level parity of each lives with its thunk (test_stripes_leftovers_asm_parity, test_ensure_scale_parity,
test_ensure_stripes_parity, test_faction_dropimg_parity, test_hm_synth_core_parity, test_se_asm_parity).  Here:
the column rule against a brute-force window oracle, pair_top's table agreeing with its colour order under the game
palette, the dest-driven regeneration against the source-driven port (assemble_stripes_leftovers.hb_synth), and
the small laws' identities over g 16..60.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

G_ALL = tuple(range(16, 61))
Q = SL.DITHER_WINDOW_ROWS


def _game_palette():
    p = ROOT / "_portrait_preview" / "hd" / "game_palette_rgbquad.bin"
    if not p.exists():
        return None
    d = p.read_bytes()
    return [(d[i * 4 + 2], d[i * 4 + 1], d[i * 4]) for i in range(256)]


PAL = _game_palette()
needs_palette = pytest.mark.skipif(PAL is None, reason="game palette dump absent (_portrait_preview/hd)")


# ---- column_dither_marks: brute-force oracle ---------------------------------------------------------------------
def _windows(rows, key, c, sh):
    return [r0 for r0 in range(sh - Q + 1)
            if rows[r0][c] != rows[r0 + 1][c] and key not in (rows[r0][c], rows[r0 + 1][c])
            and rows[r0 + 2][c] == rows[r0][c] and rows[r0 + 3][c] == rows[r0 + 1][c]]


def oracle(rows, key):
    """(r, c) -> mate: the LAST window starting at or above r that spans r."""
    sh, sw = len(rows), len(rows[0])
    out = {}
    for c in range(sw):
        ws = _windows(rows, key, c, sh)
        for r in range(sh):
            own = [r0 for r0 in ws if r0 <= r < r0 + Q]
            if own:
                r0 = own[-1]
                out[(r, c)] = rows[r0][c] ^ rows[r0 + 1][c] ^ rows[r][c]
    return out


def _art(rnd, h, w):
    pal = rnd.choice([(9, 1, 2), (1, 2), (9, 1, 2, 3), (9, 1, 2, 3, 4)])
    if rnd.random() < 0.5:
        return [[rnd.choice(pal) for _ in range(w)] for _ in range(h)]
    a, b = rnd.sample(pal, 2)
    return [[(a if (r + c // 3) % 2 == 0 else b) if rnd.random() > 0.15 else rnd.choice(pal) for c in range(w)]
            for r in range(h)]


def test_column_marks_equal_the_window_oracle():
    rnd = random.Random(11)
    for _ in range(1500):
        h, w = rnd.randint(1, 14), rnd.randint(1, 8)
        rows = _art(rnd, h, w)
        assert SL.column_dither_marks(rows, 9) == oracle(rows, 9)
        sx, sy = rnd.randint(0, w - 1), rnd.randint(0, h - 1)
        sw, sh = rnd.randint(1, w - sx), rnd.randint(1, h - sy)
        sub = [r[sx:sx + sw] for r in rows[sy:sy + sh]]
        assert SL.column_dither_marks(rows, 9, rect=(sx, sy, sw, sh)) == oracle(sub, 9)


def test_column_marks_exclude_the_key_and_short_columns():
    assert SL.column_dither_marks([[1], [2], [1]], 9) == {}                       # 3 rows: no window
    assert SL.column_dither_marks([[9], [2], [9], [2]], 9) == {}                  # a key member
    assert SL.column_dither_marks([[1], [1], [1], [1]], 9) == {}                  # A == B
    assert SL.column_dither_marks([[1], [2], [1], [2], [3]], 9) == {(0, 0): 2, (1, 0): 1, (2, 0): 2, (3, 0): 1}


# ---- pair_top: the table and the colour order -----------------------------------------------------------------------
@needs_palette
def test_pair_top_table_agrees_with_its_colour_order_under_the_game_palette():
    """The asm ports that carry no table (t_hb_col) rely on this: every DITHER_FORCE_PAIRS top is also the
    pair_top_by_colour member under the game palette."""
    rgb = PAL.__getitem__
    for top, mate in SL.DITHER_FORCE_PAIRS.items():
        assert SL.pair_top_by_colour(top, mate, rgb) == SL.pair_top_by_colour(mate, top, rgb) == top, (hex(top), hex(mate))
        assert SL.pair_top(top, mate, rgb) == SL.pair_top(mate, top, rgb) == top


def test_pair_top_is_table_then_colour():
    rnd = random.Random(5)
    for _ in range(400):
        pal = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(256)]
        rgb = pal.__getitem__
        a, b = rnd.sample(range(256), 2)
        if rnd.random() < 0.2:
            a, b = rnd.choice(list(SL.DITHER_FORCE_PAIRS.items()))
        table = next((t for t, m in SL.DITHER_FORCE_PAIRS.items() if {a, b} == {t, m}), None)
        assert SL.pair_top(a, b, rgb) == (table if table is not None else SL.pair_top_by_colour(a, b, rgb))
        # the packed key t_hb_col compares: peak << 20 | sum << 8 | (255 - i), A wins ties
        k = lambda i: (max(pal[i]) << 20) | (sum(pal[i]) << 8) | (255 - i)  # noqa: E731
        assert SL.pair_top_by_colour(a, b, rgb) == (a if k(a) >= k(b) else b)


@needs_palette
def test_drop_arrow_top_is_not_pair_top():
    """Recorded disagreement (no byte changed): the drop arrow and pair_remap_pixel put AE on top; the colour order
    picks EE under the game palette."""
    assert SL.pair_remap_pixel(0xEE, 0, 25) == 0xAE and SL.DROP_ARROW_PAIR[0] == 0xAE
    assert SL.pair_top_by_colour(0xAE, 0xEE, PAL.__getitem__) == 0xEE


# ---- vertical_dither_regen: dest-driven == source-driven ------------------------------------------------------------
def test_regen_equals_the_source_driven_port_and_g16_is_the_stretch():
    import assemble_stripes_leftovers as LO
    rnd = random.Random(3)
    for _ in range(300):
        h, w = rnd.randint(4, 14), rnd.randint(1, 8)
        rows = _art(rnd, h, w)
        pal = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(256)]
        rgb = pal.__getitem__
        sx, sy = rnd.randint(0, w - 1), rnd.randint(0, h - 4)
        sw, sh = rnd.randint(1, w - sx), rnd.randint(4, h - sy)
        g = rnd.choice(G_ALL)
        dw, dh = max(1, (sw * g) // 16 + rnd.randint(-1, 2)), max(1, (sh * g) // 16 + rnd.randint(-1, 2))
        dx, dy = rnd.randint(0, 3), rnd.randint(0, 9)
        bw, bh = dx + dw + 2, dy + dh + 2
        clip = (rnd.randint(0, 4), rnd.randint(0, 6), rnd.randint(bw - 4, bw), rnd.randint(bh - 6, bh))
        a, b, s = bytearray(bw * bh), bytearray(bw * bh), bytearray(bw * bh)
        kw = dict(sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh)
        SL.vertical_dither_regen(a, bw, rows, 9, g, rgb, clip=clip, **kw)
        LO.hb_synth(b, bw, rows, g, rgb, clip=clip, key=9, **kw)
        assert a == b
        SL.stretchblt_centre_nn(s, bw, rows, **kw)
        if g == 16:
            assert a == s
        c = bytearray(bw * bh)
        SL.vertical_dither_regen(c, bw, rows, 9, g, rgb, clip=clip, regen=False, **kw)
        assert c == s


# ---- small laws --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", G_ALL)
def test_tiles_sit_on_the_stripe_grid(g):
    for top, mate in SL.STRIPE_TILE_PAIRS:
        t = SL.stripe_tile_rows(top, mate, g)
        assert len(t) == SL.stripe_period(g)
        assert t == [top if SL.stripe_top(y, g) else mate for y in range(len(t))]
    rows = SL.se_tile_rows((34, 39), g)
    assert len(rows) == SL.se_tile_height(g) and all(len(r) == SL.SE_TILE_W for r in rows)
    assert [r[0] for r in rows] == [34 if SL.stripe_top(y, g) else 39 for y in range(len(rows))]


def test_popup_scale_num_is_the_lever_clamp():
    assert [SL.popup_scale_num(r) for r in (-5, 0, 15, 16, 17, 22, 25, 39, 40, 41, 1000)] == \
        [16, 16, 16, 16, 17, 22, 25, 39, 40, 40, 40]
    assert (SL.G_MIN, SL.G_MAX) == (16, 40)


def test_devfill_inset_and_stage_rect():
    assert [SL.devfill_inset(g) for g in (16, 17, 22, 25, 32, 33, 40, 48, 49, 60)] == [1, 2, 2, 2, 2, 3, 3, 3, 4, 4]
    assert SL.devfill_stage_rect((5, 4, 304, 23)) == (5, 4, 300, 20)


def test_strip_synth_dims_round_half_up():
    assert SL.strip_synth_dims(8, 24, 17, 16) == (9, 26)            # 8.5 -> 9, 25.5 -> 26
    halves = [(w, g) for g in range(17, 61) for w in range(1, 64)
              if SL.strip_synth_dims(w, 1, g, 16)[0] != SL.half_down(w * g, 16)]
    assert halves and all((w * g) % 16 == 8 for w, g in halves)       # differs from LAW 1 exactly at the halves
    with pytest.raises(ValueError):
        SL.strip_synth(bytearray(100), 10, 10, 10, [[1, 2, 3]] * 4, 9, 0, 0, 18, 18, 25)
    d = bytearray(b"\x77" * 100)
    SL.strip_synth(d, 10, 10, 10, [[1, 2, 3]] * 4, 9, 0, 0, 25, 16, 16)  # g <= 16: nothing
    assert d == bytearray(b"\x77" * 100)


def test_drop_arrow_render_is_mirror_nn():
    """v3 (2026-10-25 W2D F40a): the map is the mirror-symmetric centre NN (was floor NN).  Art with no pair member,
    no 1-px edge stroke (each edge texel repeats one of its next two inward) and no key: the plain map."""
    src = [[(r * 4 + c) & 0x3F for c in range(4)] for r in range(4)]
    src = [[v if c not in (0, 3) else row[1 if c == 0 else 2] for c, v in enumerate(row)] for row in src]
    src[0], src[3] = list(src[1]), list(src[2])
    out = SL.drop_arrow_render(src, 10, 6, 40)
    assert out == [[src[SL.nn_mirror_index(r, 6, 4)][SL.nn_mirror_index(c, 10, 4)] for c in range(10)]
                   for r in range(6)]
