"""Law sweep: map-effect blits above the engine's 4.0 enlarge cap (scaling_laws.engine_scale_rejects /
effect_blit_rect / effect_blit_clip / engine_scale_runs / engine_run_blocks / effect_blit_engine / buster_scale).

No g here: the cap is a RATIO, so the gate is the ratio itself.  Identity with vanilla = "at or below 4.0 the native
call runs" + "the over-cap arithmetic IS the engine's" -- effect_blit_engine equals the REAL native core pixel for pixel
at <= 4.0 on a noisy dest (test_effect_cap_asm_parity.py, Unicorn on the pristine image); here: the runs and the
block walk on their own.
"""
from __future__ import annotations

import random
import sys
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

ZOOMS = range(-16, 200)


@pytest.mark.parametrize("reactor", [1, 2, 3, 4])
def test_buster_reject_is_the_rational_test(reactor):
    """For every boom ratio (den 16 / 32: dyadic, the float is exact) the engine's float test == num > 4*den,
    and ratio exactly 4.0 is ACCEPTED (test ah,0x41 takes equal)."""
    for z in ZOOMS:
        num, den = SL.buster_scale(z, reactor)
        assert SL.engine_scale_rejects(num, den) == (num > 4 * den), (z, reactor)
        en, ed = z + 16, 16
        assert SL.engine_scale_rejects(en, ed) == (en > 4 * ed and en != ed)
    assert not SL.engine_scale_rejects(*SL.buster_scale(16, 2))          # Fusion at zoom 16: exactly 4.0
    assert SL.engine_scale_rejects(*SL.buster_scale(11, 4))              # Singularity: rejected from zoom 11
    assert not SL.engine_scale_rejects(*SL.buster_scale(9, 4))           # (25*5/32 = 3.906)
    assert not SL.engine_scale_rejects(64, 16) and SL.engine_scale_rejects(65, 16)


def test_buster_tables():
    assert [SL.buster_scale(0, r) for r in (1, 2, 3, 4)] == [(48, 32), (64, 32), (80, 32), (80, 32)]


@pytest.mark.parametrize("w,h", [(300, 248), (44, 36), (1, 1), (63, 17)])
def test_rect_is_the_uncapped_engines(w, h):
    """With a dyadic den the engine's float math is exact: W' = floor(w*num/den), anchor = x + floor(off*num/den)
    (truncation toward zero for negative sums)."""
    for z in range(-15, 200, 3):
        for num, den in ((z + 16, 16), SL.buster_scale(z, 4), SL.buster_scale(z, 1)):
            for x, y, ox, oy in ((0, 0, 0, 0), (-1234, 77, 3, 5), (999, -5, 0, 7)):
                L0, T0, W, H = SL.effect_blit_rect(x, y, ox, oy, w, h, num, den)
                r = Fraction(num, den)
                assert W == int(w * r) and H == int(h * r)
                assert L0 == int(x + ox * r) and T0 == int(y + oy * r)


def test_clip_is_intersect_rect():
    rnd = random.Random(7)
    for _ in range(4000):
        rect = (rnd.randint(-3000, 3000), rnd.randint(-3000, 3000), rnd.randint(1, 5000), rnd.randint(1, 5000))
        cl = rnd.randint(-10, 500); ct = rnd.randint(-10, 500)
        clip = (cl, ct, cl + rnd.randint(-5, 4000), ct + rnd.randint(-5, 2500))
        got = SL.effect_blit_clip(rect, clip)
        xs = range(max(rect[0], clip[0]), min(rect[0] + rect[2], clip[2]))
        ys = range(max(rect[1], clip[1]), min(rect[1] + rect[3], clip[3]))
        if len(xs) == 0 or len(ys) == 0:
            assert got is None
        else:
            assert got == (xs.start, ys.start, len(xs), len(ys))
            assert clip[0] <= got[0] and got[0] + got[2] <= clip[2] and clip[1] <= got[1] and got[1] + got[3] <= clip[3]


def test_engine_runs():
    """Sprite_fill_scaling_table's sequence: the coordinator's measured 5.0 = 6,6,5,5,...; 4.0 = all 4; the runs of
    one period of den entries sum to exactly num (the Bresenham carries no drift); den == 1 = all num."""
    assert SL.engine_scale_runs(80, 16, 6) == [6, 6, 5, 5, 5, 5]
    assert SL.engine_scale_runs(64, 16, 40) == [4] * 40 and SL.engine_scale_runs(7, 1, 5) == [7] * 5
    for num, den in ((60, 16), (65, 16), (88, 16), (440, 32), (237, 32), (750, 64), (17, 16)):
        runs = SL.engine_scale_runs(num, den, 6 * den)
        base = num // den
        assert set(runs) <= {base, base + 1}
        for k in range(1, 5):
            assert sum(runs[k * den:(k + 1) * den]) == num, (num, den, k)


def test_run_blocks_tile_the_clipped_span():
    """The blocks cover exactly the clipped span; the dest offset of each source index is its run-sum position
    (clip-independent), so any clip of the same rect agrees with the unclipped walk on the overlap."""
    rnd = random.Random(9)
    for num, den in ((60, 16), (88, 16), (440, 32), (237, 32), (64, 16)):
        runs = SL.engine_scale_runs(num, den, 600)
        full = SL.engine_run_blocks(runs, 0, sum(runs[:200]))
        owner = [i for i, ln in full for _ in range(ln)]
        for _ in range(300):
            off = rnd.randrange(0, len(owner) - 1)
            span = rnd.randint(1, len(owner) - off)
            blocks = SL.engine_run_blocks(runs, off, span)
            assert sum(ln for _, ln in blocks) == span and all(ln > 0 for _, ln in blocks)
            assert [i for i, ln in blocks for _ in range(ln)] == owner[off:off + span]


def test_engine_blit_one_lookup_per_block():
    """Each (row block, column block) holds ONE value: the table lookup against the block's top-left dest pixel."""
    rnd = random.Random(4)
    w, h, pitch, dw, dh = 9, 7, 9, 120, 90
    src = bytes(rnd.choice([0xFF, 1, 2, 3, 4]) for _ in range(pitch * h))
    table = bytes(rnd.randrange(256) for _ in range(0x10000))
    dest = bytearray(rnd.randrange(256) for _ in range(dw * dh))
    d0 = bytes(dest)
    num, den = 88, 16
    rect = SL.effect_blit_rect(3, 2, 0, 0, w, h, num, den)
    SL.effect_blit_engine(dest, dw, src, pitch, 0xFF, table, rect, (0, 0, dw, dh), num, den)
    runs = SL.engine_scale_runs(num, den, 50)
    y = rect[1]
    for r, rl in SL.engine_run_blocks(runs, 0, rect[3]):
        x = rect[0]
        for c, cl in SL.engine_run_blocks(runs, 0, rect[2]):
            s = src[r * pitch + c]
            block = {dest[yy * dw + xx] for yy in range(y, y + rl) for xx in range(x, x + cl)}
            if s == 0xFF:
                assert all(dest[yy * dw + xx] == d0[yy * dw + xx] for yy in range(y, y + rl) for xx in range(x, x + cl))
            else:
                assert block == {table[(s << 8) | d0[y * dw + x]]}
            x += cl
        y += rl
