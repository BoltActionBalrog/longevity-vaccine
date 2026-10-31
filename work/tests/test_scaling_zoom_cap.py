"""Law sweep: map sprites above the engine's 4.0 enlarge cap (scaling_laws.map_sprite_scale / pracx_max_zoom /
engine_enlarge_blit).

No g: the cap is a ratio, so the gate is the ratio itself.  Which resolutions lose map sprites is decided by PRACX's
deepest zoom at that resolution; the over-cap draw is the engine's own enlarge (asserted against the real cores in
test_zoom_cap_asm_parity.py), so these sweeps pin the arithmetic it is a port of.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

RESOLUTIONS = [(1024, 768), (1280, 1024), (1366, 768), (1600, 900), (1600, 1200), (1920, 1080), (1920, 1200),
               (2560, 1080), (2560, 1440), (2560, 1600), (3440, 1440), (3840, 1600), (3840, 2160), (5120, 1440),
               (5120, 2880), (7680, 4320)]


def test_map_sprites_vanish_exactly_from_zoom_49():
    for z in range(-15, 300):
        num, den = SL.map_sprite_scale(z)
        assert (num, den) == (z + 16, 16)
        assert SL.engine_scale_rejects(num, den) == (z > 48)
    assert SL.map_sprite_scale(5, 7, 3) == (7, 3)          # g_map_zoom_num > 0 overrides


def test_pracx_deepest_zoom_per_resolution():
    assert [SL.pracx_max_zoom(*r) for r in ((1024, 768), (1600, 1200), (1920, 1080), (3840, 2160))] == [8, 22, 30, 72]
    hit = {r for r in RESOLUTIONS if SL.engine_scale_rejects(*SL.map_sprite_scale(SL.pracx_max_zoom(*r)))}
    # only very wide / very tall screens zoom past 48: everything up to 2560x1600 never reached the cap
    assert hit == {(3440, 1440), (3840, 1600), (3840, 2160), (5120, 1440), (5120, 2880), (7680, 4320)}
    for r in RESOLUTIONS:
        z = SL.pracx_max_zoom(*r)
        assert z % 2 == 0 and SL.pracx_max_zoom(r[0] + 2000, r[1] + 2000) >= z     # monotone in the screen


@pytest.mark.parametrize("num,den", [(65, 16), (88, 16), (64, 16), (61, 16), (17, 16), (7, 2), (35, 9), (440, 32)])
def test_engine_enlarge_blit_is_effect_blit_engine_for_the_table_rule(num, den):
    """The generic replica with the table rule is exactly the Planet Buster law (one engine, one arithmetic)."""
    rnd = random.Random(num * 7 + den)
    w, h, pitch = 19, 13, 24
    src = bytes((0xFF if rnd.random() < 0.3 else rnd.randrange(256)) for _ in range(pitch * (h + 6)))
    table = bytes(rnd.randrange(256) for _ in range(0x10000))
    dw, dh = 260, 200
    dest = bytes(rnd.randrange(256) for _ in range(dw * dh))
    for _ in range(12):
        x, y = rnd.randint(-60, 200), rnd.randint(-60, 150)
        clip = (rnd.randint(0, 40), rnd.randint(0, 40), rnd.randint(150, dw), rnd.randint(120, dh))
        rect = SL.effect_blit_rect(x, y, rnd.randint(-3, 3), rnd.randint(-3, 3), w, h, num, den)
        a, b = bytearray(dest), bytearray(dest)
        SL.effect_blit_engine(a, dw, src, pitch, 0xFF, table, rect, clip, num, den)
        SL.engine_enlarge_blit(b, dw, src, pitch, 0xFF, lambda s, d: table[(s << 8) | d], rect, clip, num, den)
        assert a == b


def test_runs_exceed_the_replay_only_above_the_cap():
    """The row replay (0x5E97BE) handles runs 1..4; at or below 4.0 no run is longer, above it some are -- the reason
    the cap exists and the only thing the replica lifts."""
    for num in range(17, 200):
        for den in (16, 32, 9):
            runs = SL.engine_scale_runs(num, den, 400)
            assert (max(runs) > 4) == SL.engine_scale_rejects(num, den) or num <= den, (num, den)


def test_keyed_blocks_cover_the_clipped_rect():
    """Every dest pixel of the clipped rect belongs to exactly one block (the replicate pass writes each once): the
    blocks' spans tile [Lc, Lc + cw) on each axis."""
    for z in (49, 56, 64, 72, 102):
        num, den = SL.map_sprite_scale(z)
        runs = SL.engine_scale_runs(num, den, 200)
        for off in (0, 1, 5, 37):
            for span in (1, 7, 64, 150):
                blocks = SL.engine_run_blocks(runs, off, span)
                assert sum(ln for _, ln in blocks) == span and all(ln > 0 for _, ln in blocks)
                idx = [i for i, _ in blocks]
                assert idx == list(range(idx[0], idx[0] + len(idx)))
