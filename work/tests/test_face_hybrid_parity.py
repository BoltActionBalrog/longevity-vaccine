"""Unicorn parity for thunk_face_hybrid (assemble_rw_kinds.asm_face_hybrid, pinned pcave2+0x21A00): the citizen-face
enlarge with the Sprite_draw_2 contract (ecx=Sprite*; stack dest,key,x,y,num,den; __stdcall RET 0x18).  The REAL
assembled thunk runs at its real VA next to the REAL assembled thunk_sprite_bilinear (pass 1 is a CALL into it) and
the whole dest buffer must equal scaling_laws.face_hybrid_enlarge byte for byte: bilinear photo, the baked scanline
background regenerated on the DEST BUFFER's row phase, key texels untouched, dest-bounds clipping.  Sprites: the
game's own citizens out of newicons.pcx / aliencit.pcx (skipped when the game dir is absent) plus synthetic ones.
"""
from __future__ import annotations

import pathlib
import random
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,  # noqa: E402
                               UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_rw_kinds as RK  # noqa: E402
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402

VA = RK.FACE_HYBRID
BIL = RK.SPRITE_BILINEAR
NATIVE = 0x5E4B4A                 # engine Sprite_draw_2 (the guard-failure tail)
SDATA, DDATA, SPRITE, DEST, RET = 0x2000000, 0x2100000, 0x2200000, 0x2300000, 0x2400000
STACK = 0x2500000
SP0 = STACK + 0x8000
CODE = bytes(SE.assemble(RK.asm_face_hybrid(), VA, {}))
CODE_BIL = bytes(SE.assemble(RK.asm_sprite_bilinear(), BIL, {}))
DW, DH, DSTRIDE = 200, 190, 208   # dest canvas (w, h, row pitch)
FILL = 0xCC


def test_fits_its_pinned_slot_and_leaves_the_bilinear_alone():
    assert RK.PINNED["thunk_face_hybrid"] + len(CODE) <= RK.PINNED_END["thunk_face_hybrid"]
    assert RK.PINNED_END["t_rwk_parity_nn"] <= RK.PINNED["thunk_face_hybrid"]
    assert RK.PINNED["thunk_sprite_bilinear"] + len(CODE_BIL) <= RK.PINNED_END["thunk_sprite_bilinear"]
    assert len(CODE) > 500


def _run(src, table, geo, g, dwid=DW, dhgt=DH):
    sw, sh, pitch, key, num, den, x, y, offl, offt = geo
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(BIL & ~0xFFF, 0x2000)
    uc.mem_write(BIL, CODE_BIL)
    uc.mem_write(VA, CODE)
    for a in (SPRITE, DEST, RET, NATIVE & ~0xFFF, RK.G & ~0xFFF):
        uc.mem_map(a, 0x1000)
    uc.mem_map(SDATA, 0x4000)
    uc.mem_map(DDATA, 0x10000)
    uc.mem_map(STACK, 0x10000)
    # the texels butt against UNMAPPED memory (above the first row at even num, below the last row at odd num):
    # a pair-chain read outside the sprite's rows faults the emulation instead of passing silently
    sbase = SDATA if num % 2 == 0 else SDATA + 0x4000 - len(src)
    uc.mem_write(sbase, bytes(src))
    uc.mem_write(DDATA, bytes([FILL]) * (DSTRIDE * DH))
    uc.mem_write(NATIVE, b"\xf4")
    uc.mem_write(RK.G, struct.pack("<i", g))
    for off, v in ((0x04, sbase), (0x08, key), (0x0C, pitch), (0x10, sw), (0x14, sh),
                   (0x18, sw + 7), (0x1C, sh + 9), (0x20, offl), (0x24, offt)):      # +0x18/+0x1c = decoys
        uc.mem_write(SPRITE + off, struct.pack("<i", v))
    for off, v in ((0x54, DDATA), (0x4a8, DSTRIDE), (0x80, dwid), (0x84, (-dhgt) & 0xFFFFFFFF)):
        uc.mem_write(DEST + off, struct.pack("<I", v))
    uc.mem_write(DEST + 0xA4, table)
    for i, v in enumerate([RET, DEST, key, x, y, num, den]):
        uc.mem_write(SP0 + i * 4, struct.pack("<I", v & 0xFFFFFFFF))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, SPRITE)
    uc.reg_write(UC_X86_REG_EBX, 0xB); uc.reg_write(UC_X86_REG_ESI, 0xE); uc.reg_write(UC_X86_REG_EDI, 0xD)
    uc.reg_write(UC_X86_REG_EBP, 0xBBBB0000)
    uc.mem_write(RET, b"\xf4")
    uc.emu_start(VA, RET, timeout=600_000_000)                     # us: a hang bound only -- the end marker decides
    assert uc.reg_read(UC_X86_REG_EIP) in (RET, NATIVE, NATIVE + 1), "returned, or tail-jumped to the engine draw"
    return uc, bytes(uc.mem_read(DDATA, DSTRIDE * DH))


def _law(src, table, geo, g, dwid=DW, dhgt=DH):
    sw, sh, pitch, key, num, den, x, y, offl, offt = geo
    dst = bytearray([FILL]) * (DSTRIDE * DH)
    r = SL.face_hybrid_enlarge(src, pitch, sw, sh, offl, offt, table, num, den, g, dst, DSTRIDE, dwid, dhgt, x, y, key)
    return r, bytes(dst)


def _check(src, table, geo, g, **kw):
    uc, got = _run(src, table, geo, g, **kw)
    r, want = _law(src, table, geo, g, **kw)
    assert r is not None
    assert uc.reg_read(UC_X86_REG_EIP) == RET
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x18                                 # RET 0x18
    assert (uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI),
            uc.reg_read(UC_X86_REG_EBP)) == (0xB, 0xE, 0xD, 0xBBBB0000)
    assert got == want
    return got


def _make_table(seed):
    r = random.Random(seed)
    return bytes(v for _ in range(256) for v in (r.randrange(256), r.randrange(256), r.randrange(256), 0))


def _synthetic(seed, sw=30, sh=38, pitch=33, key=9):
    """Photo noise in the middle; a striped background left (pair C9/6D) and right (pair 41/C4, phase flipped), a
    2-wide a/b/a/b coincidence and a lone 1-px stroke inside the photo, a 1-px border, key corners + a key hole in
    the stripes; pitch > width with junk in the slack columns."""
    r = random.Random(seed)
    src = bytearray(r.randrange(256) for _ in range(pitch * sh))
    for yy in range(sh):
        for xx in range(sw):
            v = r.choice([v for v in range(10, 250) if v not in (0xC9, 0x6D, 0x41, 0xC4, 0x77, 0x88)])
            if xx < 8:
                v = 0xC9 if (yy & 1) == 0 else 0x6D
            if xx >= sw - 7:
                v = 0x41 if (yy & 1) == 0 else 0xC4
            if 14 <= xx < 16 and 10 <= yy < 22:
                v = 0x77 if (yy & 1) == 0 else 0x88                       # 2-wide coincidence: not background
            if yy == 30 and 10 <= xx < 20:
                v = 0x77                                                  # lone stroke
            if xx == 0 or xx == sw - 1 or yy == 0 or yy == sh - 1:
                v = 0xE0
            src[yy * pitch + xx] = v
    for xx, yy in ((0, 0), (sw - 1, 0), (0, sh - 1), (sw - 1, sh - 1), (3, 12), (4, 12), (sw - 3, 20)):
        src[yy * pitch + xx] = key
    return bytes(src)


@pytest.mark.parametrize("num", [17, 22, 25, 40, 45])
def test_synthetic_matches_the_law(num):
    src, table = _synthetic(num), _make_table(num)
    got = _check(src, table, (30, 38, 33, 9, num, 16, 5, 7, 2, 1), num)
    assert 9 not in got


@pytest.mark.parametrize("y", [0, 1, 2, 3, 4, 11])
def test_stripe_phase_follows_the_dest_buffer_row(y):
    num = 25
    src, table = _synthetic(7), _make_table(7)
    got = _check(src, table, (30, 38, 33, 9, num, 16, 6, y, 0, 0), num)
    top = SL.hof_pair_top(0xC9, 0x6D, table)
    col = 6 + 10                                              # dest px 10 -> native column 6: inside the left striped band, off the key hole
    assert SL.bilinear_axis(10, num, 16, 30)[3] == 6
    for yy in range(y + 6, y + 50):
        assert got[yy * DSTRIDE + col] == (top if SL.stripe_top(yy, num) else (0xC9 + 0x6D - top))


@pytest.mark.parametrize("num", [22, 25, 40])
def test_clipped_bottom_and_right(num):
    src, table = _synthetic(3), _make_table(3)
    geo = (30, 38, 33, 9, num, 16, DW - 30, DH - 40, 0, 0)     # overhangs the right and bottom dest bounds
    got = _check(src, table, geo, num)
    assert all(got[yy * DSTRIDE + xx] == FILL for yy in range(DH) for xx in range(DW, DSTRIDE))
    # a caller's temporary height clamp (t_rwk_face_blit writes +0x84 before the call) bounds BOTH passes
    got = _check(src, table, (30, 38, 33, 9, num, 16, 20, 100, 0, 0), num, dhgt=120, dwid=40)
    assert all(v == FILL for v in got[120 * DSTRIDE:])
    assert all(got[yy * DSTRIDE + xx] == FILL for yy in range(DH) for xx in range(40, DSTRIDE))


def test_negative_origin_clips_left_and_top():
    src, table = _synthetic(4), _make_table(4)
    _check(src, table, (30, 38, 33, 9, 25, 16, -9, -13, 0, 0), 25)


def _pocket(sw=38, sh=48, pitch=40, key=9):
    """Membership v2 shapes: a 3-row stripe pocket between the top border and a photo blob (gap fill), a 13-wide
    and a 12-wide same-index bar across blobs (the gap cap), two stripe bands meeting on a shared row (both
    candidates), key texels inside a gap and at a flank."""
    r = random.Random(11)
    src = bytearray(r.randrange(256) for _ in range(pitch * sh))
    for yy in range(sh):
        for xx in range(sw):
            v = 0xC9 if (yy & 1) == 0 else (0x6D if yy < 31 or xx < 5 else 0x41)
            if yy == 0 or yy == sh - 1:
                v = 0xE0
            if (6 if yy >= 8 else 8) <= xx < 19 and 4 <= yy < 18:
                v = r.choice((0x50, 0x51, 0x52))                          # head: 11 wide on top (3-row pocket above), 13 wide below
            if 22 <= xx < 34 and 6 <= yy < 18:
                v = r.choice((0x50, 0x51, 0x52))                          # 12-wide blob
            if yy == 10 and 6 <= xx < 34:
                v = 0xC9                                                  # the bar: 13 wide (no fill) / 12 wide (fill)
            src[yy * pitch + xx] = v
    for xx, yy in ((0, 0), (sw - 1, 0), (9, 2), (30, 40)):
        src[yy * pitch + xx] = key
    return bytes(src)


@pytest.mark.parametrize("num", [17, 22, 25, 40, 45])
def test_membership_v2_shapes_match_the_law(num):
    src, table = _pocket(), _make_table(num + 100)
    sw, sh, pitch = 38, 48, 40
    mate = lambda x, y: SL.face_pair_mate(src, pitch, sw, sh, x, y, 9)   # noqa: E731
    assert all(mate(x, y) is not None for y in (1, 3) for x in range(8, 19))            # the pocket, gap-filled
    assert all(mate(x, 2) is None for x in range(8, 19))        # a key texel inside row 2's gap: neither part keeps both flanks
    assert all(mate(x, 10) is None for x in range(6, 19)) and all(mate(x, 10) is not None for x in range(22, 34))   # 13 / 12
    _check(src, table, (sw, sh, pitch, 9, num, 16, 3, 4, 0, 0), num)
    _check(src, table, (sw, sh, pitch, 9, num, 16, DW - 45, DH - 60, 1, 2), num)


@pytest.mark.parametrize("g,num,den", [(16, 25, 16), (10, 40, 16), (25, 16, 16), (25, 12, 16), (25, 25, 0)])
def test_guard_failures_tail_jump_the_engine_draw(g, num, den):
    src, table = _synthetic(1), _make_table(1)
    geo = (30, 38, 33, 9, num, den, 5, 7, 0, 0)
    uc, got = _run(src, table, geo, g)
    assert uc.reg_read(UC_X86_REG_EIP) in (NATIVE, NATIVE + 1)                 # halted on the engine entry stub
    assert got == bytes([FILL]) * (DSTRIDE * DH)
    assert uc.reg_read(UC_X86_REG_ESP) == SP0                                  # entry stack intact for the engine
    assert _law(src, table, geo, g)[0] is None


def test_num_differs_from_g():
    """The stripe period is the SCREEN's (g_popup_scale_num), the extents the call's ratio."""
    src, table = _synthetic(9), _make_table(9)
    _check(src, table, (30, 38, 33, 9, 50, 32, 3, 5, 1, 2), 40)


# ---- the game's own citizens ------------------------------------------------------------------------------------
def _game_cells():
    try:
        import config
        from PIL import Image
        game = pathlib.Path(config.game_dir())
        out = []
        for pcx, x0, y0, pitch, w, h, picks in (("newicons.pcx", 1, 501, 39, 38, 48, (0, 4, 6, 9)),
                                                 ("newicons.pcx", 44, 458, 31, 30, 38, (1, 5, 7)),
                                                 ("aliencit.pcx", 1, 41, 39, 38, 48, (2,)),
                                                 ("aliencit.pcx", 1, 1, 31, 30, 38, (2, 4))):
            im = Image.open(game / pcx)
            palette = im.getpalette()[:768]
            px = im.load()
            # runtime index space: the loader shifts every PCX index +10 mod 256 (PCX 255 -> the key 9)
            table = bytearray(1024)
            for i in range(256):
                j = (i + 10) & 0xFF
                table[j * 4:j * 4 + 3] = bytes((palette[i * 3 + 2], palette[i * 3 + 1], palette[i * 3]))
            for i in picks:
                cell = bytes((px[x0 + i * pitch + xx, y0 + yy] + 10) & 0xFF for yy in range(h) for xx in range(w))
                out.append((f"{pcx}:{w}x{h}#{i}", cell, bytes(table), w, h))
        return out
    except Exception:                                                          # no game dir / no PIL
        return []


CELLS = _game_cells()


@pytest.mark.skipif(not CELLS, reason="game art not available")
@pytest.mark.parametrize("num", [17, 22, 25, 40, 45])
def test_real_citizens_match_the_law(num):
    members = 0
    for k, (name, cell, table, w, h) in enumerate(CELLS):
        if num in (17, 45) and k % 3:                                          # the extremes on a subset (runtime)
            continue
        geo = (w, h, w, 9, num, 16, 4 + k, 3 + 2 * k, 0, 0)
        _check(cell, table, geo, num)
        members += sum(SL.face_pair_mate(cell, w, w, h, xx, yy, 9) is not None for yy in range(h) for xx in range(w))
    assert members > 500                                                       # the drones' backgrounds are found


@pytest.mark.skipif(not CELLS, reason="game art not available")
def test_real_citizen_clipped_at_a_nonzero_row():
    name, cell, table, w, h = CELLS[1]
    _check(cell, table, (w, h, w, 9, 25, 16, DW - 40, DH - 50, 0, 0), 25)
    _check(cell, table, (w, h, w, 9, 22, 16, 10, 37, 0, 0), 22, dhgt=80)
