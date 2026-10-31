"""Unicorn parity for thunk_portrait_avg (assemble_resampler.py) — the A5
palette-aware bilinear sprite resampler.

The thunk is emulated from its freshly-assembled bytes at its real cave VA
(pcave2+0xA00) against a Python reference of the law: source-driven inverse map
(y0=dyi*den/num, fx/fy in 256ths), coverage = nearest src texel != key, weighted
blend of the non-key 2x2 neighbours' table RGB, round (acc+wt/2)/wt, nearest
index by strict-< argmin over 256 entries.

2026-09-01 regression lock: the palette source is the DEST buffer's own synced
DIB color table at dest+0xA4 — NEVER the fixed global Palette 0x94c590 (correct
only on the menu screens; stale in-game, junk indices over blended regions —
Morgan 1600 shot 235728). 0x94C590's page is left UNMAPPED here, so any stale
read faults the emulation.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import random
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP,
)

import assemble_resampler as AR  # noqa: E402

VA = AR.THUNK_VA
DEST = 0x940824               # the gate imm (t_dl_portrait pokes it per-call)
SDATA, DDATA, SPRITE = 0x02000000, 0x02010000, 0x02020000
STACK, RET = 0x00300000, 0x00700000
SP0 = STACK + 0x8000
NATIVE_RESUME = 0x5E4B52      # Sprite_draw_2 entry + displaced instrs


def _assemble():
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    clean = "\n".join(
        ln.split(";", 1)[0].rstrip()
        for ln in AR.ASM.splitlines()
        if ln.split(";", 1)[0].strip())
    enc, _ = ks.asm(clean, VA)
    return bytes(enc)


CODE = _assemble()


def test_fits_before_next_thunk():
    # thunk_faction_footer_bump sits at pcave2+0xDD0
    assert AR.THUNK_OFF + len(CODE) <= 0xDD0


def _reference(src, table, geo):
    sw, sh, sstride, key, num, den, px, py, dwid, dhgt, dstride = geo
    tab = [tuple(table[i * 4:i * 4 + 3]) for i in range(256)]
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
            if src[yn * sstride + xn] == key:
                continue
            acc = [0, 0, 0]
            wt = 0
            for xx, yy, w in ((x0, y0, (256 - fx) * (256 - fy)),
                              (x1, y0, fx * (256 - fy)),
                              (x0, y1, (256 - fx) * fy),
                              (x1, y1, fx * fy)):
                t = src[yy * sstride + xx]
                if t == key:
                    continue
                for c in range(3):
                    acc[c] += tab[t][c] * w
                wt += w
            if wt <= 0:
                continue
            tv = [(acc[c] + (wt >> 1)) // wt for c in range(3)]
            best, bd = 0, 1 << 62
            for i in range(256):
                if i == key:            # never emit the transparency index
                    continue
                d = sum((tab[i][c] - tv[c]) ** 2 for c in range(3))
                if d < bd:
                    bd, best = d, i
            dst[dy * dstride + dx] = best
    return bytes(dst)


def _run(src, table, geo):
    sw, sh, sstride, key, num, den, px, py, dwid, dhgt, dstride = geo
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(AR.PCAVE2_VA, 0x2000)
    uc.mem_write(VA, CODE)
    uc.mem_map(0x940000, 0x1000)          # dest struct page; 0x94C590 UNMAPPED
    for a in (SDATA, DDATA, SPRITE, RET):
        uc.mem_map(a, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(SDATA, src)
    uc.mem_write(DDATA, b"\xCC" * dstride * dhgt)
    for off, v in ((0x04, SDATA), (0x10, sstride), (0x18, sw), (0x1c, sh)):
        uc.mem_write(SPRITE + off, struct.pack("<I", v))
    for off, v in ((0x54, DDATA), (0x4a8, dstride), (0x80, dwid),
                   (0x84, (-dhgt) & 0xFFFFFFFF)):
        uc.mem_write(DEST + off, struct.pack("<I", v))
    uc.mem_write(DEST + 0xA4, table)
    for i, v in enumerate([RET, DEST, key, px, py, num, den]):
        uc.mem_write(SP0 + i * 4, struct.pack("<I", v))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, SPRITE)
    uc.emu_start(VA, RET, timeout=600_000_000)                     # us: a hang bound only -- the end marker decides
    assert uc.reg_read(UC_X86_REG_EIP) == RET, "returned (not cut short)"
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x18   # ret 0x18 contract
    return bytes(uc.mem_read(DDATA, dstride * dhgt))


def _make_table(seed):
    r = random.Random(seed)
    return bytes(b for _ in range(256)
                 for b in (r.randrange(256), r.randrange(256), r.randrange(256), 0))


@pytest.mark.parametrize("num", [22, 25, 40])
def test_bilinear_matches_reference(num):
    random.seed(7)
    geo = (16, 16, 16, 9, num, 16, 2, 3, 16 * num // 16 + 8, 16 * num // 16 + 8, 64)
    src = bytes(random.choice([5, 6, 7, 8, 9, 30, 31, 200]) for _ in range(256))
    table = _make_table(1)
    assert _run(src, table, geo) == _reference(src, table, geo)


def test_output_reads_dest_table_not_global():
    # Two different dest tables MUST give different output (and 0x94C590 is
    # unmapped throughout, so a stale global read faults the run).
    random.seed(7)
    geo = (16, 16, 16, 9, 25, 16, 2, 3, 40, 40, 64)
    src = bytes(random.choice([5, 6, 7, 8, 9, 30, 31, 200]) for _ in range(256))
    a = _run(src, _make_table(1), geo)
    b = _run(src, _make_table(2), geo)
    assert a != b


def test_never_emits_the_key_index():
    # Regression lock for the map-through-the-portrait holes (Morgan 4K shot
    # 001528): key 9's table RGB is (9,0,0) ~ black, so dark blends won the
    # nearest search at the transparency index and the keyed window composite
    # punched holes. The search must skip i == key.
    key = 9
    geo = (16, 16, 16, key, 25, 16, 2, 3, 40, 40, 64)
    src = bytes([10, 11] * 8 * 16)          # dithered pair of dark indices
    table = bytearray(_make_table(3))
    table[key * 4:key * 4 + 4] = bytes((0, 0, 9, 0))       # key ~ black (BGR0)
    table[10 * 4:10 * 4 + 4] = bytes((6, 8, 25, 0))        # dark browns whose
    table[11 * 4:11 * 4 + 4] = bytes((2, 4, 12, 0))        # blends sit near key
    table[65 * 4:65 * 4 + 4] = bytes((0, 0, 0, 0))         # legit pure black
    out = _run(src, bytes(table), geo)
    assert key not in set(out) - {0xCC}     # 0xCC = untouched fill
    assert out == _reference(src, bytes(table), geo)


def test_fallthrough_is_esp_neutral():
    for args in ([RET, 0x123456, 9, 2, 3, 40, 16],      # dest mismatch
                 [RET, DEST, 9, 2, 3, 16, 16]):         # num == den
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(AR.PCAVE2_VA, 0x2000)
        uc.mem_write(VA, CODE)
        uc.mem_map(STACK, 0x10000)
        uc.mem_map(0x5E4000, 0x1000)
        for i, v in enumerate(args):
            uc.mem_write(SP0 + i * 4, struct.pack("<I", v))
        uc.reg_write(UC_X86_REG_ESP, SP0)
        uc.emu_start(VA, NATIVE_RESUME, count=1000)
        assert uc.reg_read(UC_X86_REG_EIP) == NATIVE_RESUME
        assert uc.reg_read(UC_X86_REG_ESP) == SP0             # esp-neutral
        assert uc.reg_read(UC_X86_REG_EAX) == args[5]         # displaced num load
        assert uc.reg_read(UC_X86_REG_EDX) == args[6]         # displaced den load


def test_yaml_bytes_match_assembled():
    # patches.yaml carries raw hex for this thunk; it must equal the source build.
    import re
    yaml_text = (ROOT / "patches" / "patches.yaml").read_bytes().decode("utf-8")
    m = re.search(r'- id: thunk_portrait_avg\r?\n\s+offset: 0xA00\r?\n\s+bytes: "([^"]+)"',
                  yaml_text)
    assert m, "thunk_portrait_avg entry missing from patches.yaml"
    assert bytes(int(b, 16) for b in m.group(1).split()) == CODE
