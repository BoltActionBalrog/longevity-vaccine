"""Unicorn parity for thunk_sprite_bilinear (assemble_rw_kinds.asm_sprite_bilinear, pinned pcave2+0x21000):
the callable palette-aware bilinear with thunk_sprite_scale_nn's contract (ecx=Sprite*; stack dest,key,x,y,num,den;
__stdcall RET 0x18).  Oracle = test_resampler_parity's reference law for thunk_portrait_avg (the A5 bilinear the
thunk's text is derived from) with the engine's Sprite field semantics (pitch +0xC, blit W/H +0x10/+0x14) and the
scale_nn v2 placement (x + iLeftOffset*num/den).  The real assembled bytes run at the real VA.
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
from unicorn.x86_const import (UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_EBX,  # noqa: E402
                               UC_X86_REG_ESI, UC_X86_REG_EDI)

import assemble_rw_kinds as RK  # noqa: E402
import assemble_se as SE  # noqa: E402

VA = RK.SPRITE_BILINEAR
NATIVE = 0x5E4B4A                 # engine Sprite_draw_2 (the guard-failure tail)
SDATA, DDATA, SPRITE, DEST, RET = 0x2000000, 0x2100000, 0x2200000, 0x2300000, 0x2400000
STACK = 0x2500000
SP0 = STACK + 0x8000
CODE = bytes(SE.assemble(RK.asm_sprite_bilinear(), VA, {}))


def test_fits_its_pinned_slot():
    assert RK.PINNED["thunk_sprite_bilinear"] + len(CODE) <= RK.PINNED_END["thunk_sprite_bilinear"]
    assert len(CODE) > 700                           # the whole averager is there, not a stub


def _reference(src, table, geo):
    sw, sh, pitch, key, num, den, x, y, offl, offt, dwid, dhgt, dstride = geo
    tab = [tuple(table[i * 4:i * 4 + 3]) for i in range(256)]
    px, py = x + offl * num // den, y + offt * num // den
    dst = bytearray(b"\xCC" * dstride * dhgt)
    for dyi in range(sh * num // den):
        dy = py + dyi
        if not (0 <= dy < dhgt):
            continue
        y0, remy = divmod(dyi * den, num)
        fy = (remy << 8) // num
        y1 = min(y0 + 1, sh - 1)
        yn = y1 if 2 * remy >= num else y0
        for dxi in range(sw * num // den):
            dx = px + dxi
            if not (0 <= dx < dwid):
                continue
            x0, remx = divmod(dxi * den, num)
            fx = (remx << 8) // num
            x1 = min(x0 + 1, sw - 1)
            xn = x1 if 2 * remx >= num else x0
            if src[yn * pitch + xn] == key:
                continue
            acc = [0, 0, 0]
            wt = 0
            for xx, yy, w in ((x0, y0, (256 - fx) * (256 - fy)), (x1, y0, fx * (256 - fy)),
                              (x0, y1, (256 - fx) * fy), (x1, y1, fx * fy)):
                tv = src[yy * pitch + xx]
                if tv == key:
                    continue
                for c in range(3):
                    acc[c] += tab[tv][c] * w
                wt += w
            if wt <= 0:
                continue
            tv = [(acc[c] + (wt >> 1)) // wt for c in range(3)]
            best, bd = 0, 1 << 62
            for i in range(256):
                if i == key:
                    continue
                d = sum((tab[i][c] - tv[c]) ** 2 for c in range(3))
                if d < bd:
                    bd, best = d, i
            dst[dy * dstride + dx] = best
    return bytes(dst)


def _run(src, table, geo):
    sw, sh, pitch, key, num, den, x, y, offl, offt, dwid, dhgt, dstride = geo
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(VA & ~0xFFF, 0x2000)
    uc.mem_write(VA, CODE)
    for a in (SDATA, SPRITE, DEST, RET, NATIVE & ~0xFFF):
        uc.mem_map(a, 0x1000)
    uc.mem_map(DDATA, 0x8000)                 # 128 x 130 dest canvas
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(SDATA, src)
    uc.mem_write(DDATA, b"\xCC" * dstride * dhgt)
    uc.mem_write(NATIVE, b"\xf4")
    for off, v in ((0x04, SDATA), (0x08, key), (0x0C, pitch), (0x10, sw), (0x14, sh),
                   (0x18, sw + 7), (0x1C, sh + 9), (0x20, offl), (0x24, offt)):      # +0x18/+0x1c = decoys
        uc.mem_write(SPRITE + off, struct.pack("<i", v))
    for off, v in ((0x54, DDATA), (0x4a8, dstride), (0x80, dwid), (0x84, (-dhgt) & 0xFFFFFFFF)):
        uc.mem_write(DEST + off, struct.pack("<I", v))
    uc.mem_write(DEST + 0xA4, table)
    for i, v in enumerate([RET, DEST, key, x, y, num, den]):
        uc.mem_write(SP0 + i * 4, struct.pack("<I", v))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, SPRITE)
    uc.reg_write(UC_X86_REG_EBX, 0xB); uc.reg_write(UC_X86_REG_ESI, 0xE); uc.reg_write(UC_X86_REG_EDI, 0xD)
    uc.mem_write(RET, b"\xf4")
    try:
        uc.emu_start(VA, RET, timeout=600_000_000)                 # us: a hang bound only -- the end marker decides
    except Exception:
        pass                                  # the guard tail-jump halts on the engine stub (hlt at NATIVE)
    assert uc.reg_read(UC_X86_REG_EIP) in (RET, NATIVE, NATIVE + 1), "returned, or tail-jumped to the engine draw"
    return uc, bytes(uc.mem_read(DDATA, dstride * dhgt))


def _make_table(seed):
    r = random.Random(seed)
    return bytes(v for _ in range(256) for v in (r.randrange(256), r.randrange(256), r.randrange(256), 0))


def _face(seed, sw=30, sh=38, pitch=32, key=9):
    """A citizen-like sprite: photo noise, a 1-px border, a 1:1 two-colour dither band on the left edge,
    transparent (key) corners; pitch > width (the decoy columns hold junk)."""
    r = random.Random(seed)
    src = bytearray(r.randrange(256) for _ in range(pitch * sh))
    for yy in range(sh):
        for xx in range(sw):
            v = r.randrange(10, 250)
            if xx < 3:
                v = 0xC9 if (yy & 1) == 0 else 0x6D
            if xx == 0 or xx == sw - 1 or yy == 0 or yy == sh - 1:
                v = 0xE0
            src[yy * pitch + xx] = v
    for xx, yy in ((0, 0), (sw - 1, 0), (0, sh - 1), (sw - 1, sh - 1)):
        src[yy * pitch + xx] = key
    return bytes(src)


@pytest.mark.parametrize("num", [22, 25, 32, 40])
def test_bilinear_matches_the_reference_law(num):
    src = _face(num)
    table = _make_table(num)
    geo = (30, 38, 32, 9, num, 16, 5, 7, 2, 1, 120, 130, 128)
    uc, got = _run(src, table, geo)
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x18                     # RET 0x18 contract
    assert (uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI)) == (0xB, 0xE, 0xD)
    assert got == _reference(src, table, geo)


def test_full_coverage_and_never_the_key():
    """Every dest px of the floor(30*25/16) x floor(38*25/16) rect is written (the last column/row included --
    the engine core's dropped-edge defect) except where the coverage texel is transparent; the key never appears."""
    num, den = 25, 16
    src = _face(3)
    table = _make_table(3)
    geo = (30, 38, 32, 9, num, den, 4, 4, 0, 0, 120, 130, 128)
    _uc, got = _run(src, table, geo)
    dw, dh = 30 * num // den, 38 * num // den
    assert (dw, dh) == (46, 59)
    ref = _reference(src, table, geo)
    written = [(x, y) for y in range(130) for x in range(128) if got[y * 128 + x] != 0xCC]
    assert written and all(4 <= x < 4 + dw and 4 <= y < 4 + dh for x, y in written)
    assert sum(1 for y in range(4, 4 + dh) if got[y * 128 + 4 + dw - 1] != 0xCC) > dh // 2   # the last column exists
    assert 9 not in got and got == ref


@pytest.mark.parametrize("num,den", [(16, 16), (12, 16), (25, 0)])
def test_guard_failures_tail_jump_the_engine_draw(num, den):
    src = _face(1); table = _make_table(1)
    geo = (30, 38, 32, 9, num, den, 5, 7, 0, 0, 120, 130, 128)
    uc, got = _run(src, table, geo)
    assert got == b"\xCC" * (128 * 130)                                        # nothing drawn by us
    assert uc.reg_read(UC_X86_REG_ESP) == SP0                                  # entry stack intact for the engine


def test_clips_to_the_dest_bounds():
    src = _face(5); table = _make_table(5)
    geo = (30, 38, 32, 9, 25, 16, 100, 110, 0, 0, 120, 130, 128)               # overhangs right/bottom
    _uc, got = _run(src, table, geo)
    assert got == _reference(src, table, geo)
    assert all(got[y * 128 + x] == 0xCC for y in range(130) for x in range(120, 128))   # stride slack untouched
