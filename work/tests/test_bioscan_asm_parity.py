"""Unicorn parity for the BIOSCAN figure fix (assemble_artreblit.py v2, 2026-09-21): thunk_art_bioinit fills the flic's
bg canvas with key 9 after Flic_init and captures a DEVICE-size save-under of the strip; thunk_art_flic restores the
rect from it and re-blits the scratch with key 9 (law scaling_laws.art_reblit, key texels skipped)."""
from __future__ import annotations

import contextlib
import io

import pytest

import test_council_asm_parity as TC
from test_council_asm_parity import HEAP, RET_SITE, SL, SP0

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_artreblit as AR

LAY = AR.assemble_all()
VA = {n: AR.PCAVE2 + off for n, (off, _b) in LAY.items()}
STRIP, SDATA = HEAP + 0x30000, HEAP + 0x40000
SCRATCH, SCDATA = HEAP + 0x88000, HEAP + 0x90000
UNDER, UDATA = HEAP + 0xA0000, HEAP + 0xB0000          # clear of the strip data (HEAP+0x40000 .. +0x71000)
CANVAS_DATA = HEAP + 0xC0000
FLINIT_STUB = b"\xB8\x66\x00\x00\x00\xC2\x14\x00"      # mov eax,0x66 ; ret 0x14
FLICDRAW_STUB = b"\xB8\x55\x00\x00\x00\xC2\x08\x00"    # mov eax,0x55 ; ret 8
MALLOC_STUB = b"\xB8" + UNDER.to_bytes(4, "little") + b"\xC3"
CTOR_STUB = b"\xC3"
RESIZE_STUB = b"\xC2\x08\x00"
COPY3_STUB = b"\xC2\x24\x00"
SW, SH = 61, 146


def emu(g):
    e = TC.Emu(g)
    for page in (AR.PCAVE2 + 0x29000, AR.PCAVE2 + 0x1C000, AR.PCAVE2 + 0x2D000, 0x733000, 0x734000, 0x735000,
                 0x5D7000, 0x5D9000, 0x645000):
        try:
            e.uc.mem_map(page, 0x1000)
        except Exception:  # noqa: BLE001  (already mapped by the council harness)
            pass
    for _n, (off, b) in LAY.items():
        e.uc.mem_write(AR.PCAVE2 + off, b)
    for addr, stub in ((AR.T_DP_FLINIT_BIO, FLINIT_STUB), (AR.T_DP_FLICDRAW, FLICDRAW_STUB), (AR.CRT_MALLOC, MALLOC_STUB),
                       (AR.BUF_CTOR, CTOR_STUB), (AR.BUF_RESIZE, RESIZE_STUB), (AR.BUF_COPY_3, COPY3_STUB)):
        e.uc.mem_write(addr, stub)
        e.stub_addrs.add(addr)
    e.w32(AR.G_BIO_UNDER, 0)
    return e


def calls(e, addr):
    return [c for c in e.calls if c[0] == addr]


def mk_flic(e, flic, dest, x, y):
    TC.mk_buffer(e, flic + 4, SW, SH, pitch=64, data=CANVAS_DATA, fill=0xC4)     # the engine's bg capture
    e.w32(flic + 0x59C, SW)
    e.w32(flic + 0x5A0, SH)
    e.w32(flic + 0x5A8, dest)
    e.w32(flic + 0x5AC, x)
    e.w32(flic + 0x5B0, y)


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_art_bioinit(g):
    e = emu(g)
    TC.mk_buffer(e, STRIP, 400, 400, data=SDATA)
    mk_flic(e, AR.FLIC_BIO, STRIP, (26 * g) >> 4, (90 * g) >> 4)
    canvas_before = bytes(e.uc.mem_read(CANVAS_DATA, 64 * SH))
    land = e.run(VA["thunk_art_bioinit"], regs={"ecx": AR.FLIC_BIO, "esi": 0x51, "edi": 0x52, "ebx": 0x53, "ebp": 0x54},
                 stack=[RET_SITE, STRIP, 0x700000, 26, 90, 1])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x14 and e.reg("eax") == 0x66
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x51, 0x52, 0x53, 0x54)
    fl = calls(e, AR.T_DP_FLINIT_BIO)
    assert len(fl) == 1 and fl[0][3] == AR.FLIC_BIO and fl[0][2][1:6] == [STRIP, 0x700000, 26, 90, 1]
    canvas = bytes(e.uc.mem_read(CANVAS_DATA, 64 * SH))
    if g <= 16:                                            # native: the wrapper is a pure tail-jump
        assert canvas == canvas_before and e.r32(AR.G_BIO_UNDER) == 0
        assert not calls(e, AR.CRT_MALLOC) and not calls(e, AR.BUF_COPY_3) and not calls(e, AR.BUF_RESIZE)
        return
    for r in range(SH):                                    # every canvas texel = key 9, the pitch padding untouched
        assert canvas[r * 64:r * 64 + SW] == bytes([9]) * SW, r
        assert canvas[r * 64 + SW:(r + 1) * 64] == bytes([0xC4]) * (64 - SW), r
    dw, dh = (SW * g) >> 4, (SH * g) >> 4
    assert e.r32(AR.G_BIO_UNDER) == UNDER
    assert len(calls(e, AR.CRT_MALLOC)) == 1 and calls(e, AR.CRT_MALLOC)[0][2][1] == 0x588
    assert [c[3] for c in calls(e, AR.BUF_CTOR)] == [UNDER]
    rs = calls(e, AR.BUF_RESIZE)
    assert len(rs) == 1 and rs[0][3] == UNDER and rs[0][2][1:3] == [dw, dh]
    cp = calls(e, AR.BUF_COPY_3)
    assert len(cp) == 1 and cp[0][3] == STRIP
    assert cp[0][2][1:10] == [UNDER, (26 * g) >> 4, (90 * g) >> 4, dw, dh, 0, 0, dw, dh]
    # second init (next diplomacy open): the cell is reused -- no malloc / ctor, resize + capture again
    e.calls.clear()
    e.uc.mem_write(CANVAS_DATA, canvas_before)
    land = e.run(VA["thunk_art_bioinit"], regs={"ecx": AR.FLIC_BIO}, stack=[RET_SITE, STRIP, 0x700000, 26, 90, 1])
    assert land == RET_SITE and e.r32(AR.G_BIO_UNDER) == UNDER
    assert not calls(e, AR.CRT_MALLOC) and not calls(e, AR.BUF_CTOR)
    assert len(calls(e, AR.BUF_RESIZE)) == 1 and len(calls(e, AR.BUF_COPY_3)) == 1
    assert bytes(e.uc.mem_read(CANVAS_DATA, SW)) == bytes([9]) * SW


def test_art_bioinit_malloc_failure_is_safe():
    e = emu(25)
    e.uc.mem_write(AR.CRT_MALLOC, b"\x31\xC0\xC3")        # xor eax,eax ; ret
    TC.mk_buffer(e, STRIP, 400, 400, data=SDATA)
    mk_flic(e, AR.FLIC_BIO, STRIP, 40, 140)
    land = e.run(VA["thunk_art_bioinit"], regs={"ecx": AR.FLIC_BIO}, stack=[RET_SITE, STRIP, 0x700000, 26, 90, 1])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x14 and e.reg("eax") == 0x66
    assert e.r32(AR.G_BIO_UNDER) == 0 and not calls(e, AR.BUF_RESIZE) and not calls(e, AR.BUF_COPY_3)
    assert bytes(e.uc.mem_read(CANVAS_DATA, SW)) == bytes([9]) * SW       # the canvas fill still happened


def figure(sw, sh, key=9):
    """A keyed flic frame: key background, a solid silhouette column band with 1-row scanline shading."""
    px = []
    for r in range(sh):
        for c in range(sw):
            inside = sw // 4 <= c < 3 * sw // 4 and sh // 8 <= r < 7 * sh // 8
            px.append((0x30 + (r & 1) * 0x40 + (c % 5)) if inside else key)
    return px


@pytest.mark.parametrize("g", [22, 25, 40])
@pytest.mark.parametrize("have_under", [True, False])
def test_art_flic_bio_restores_then_keyed_reblit(g, have_under):
    e = emu(g)
    px = figure(SW, SH)
    sdata = TC.mk_buffer(e, SCRATCH, SW + 3, SH, pitch=SW + 3, data=SCDATA)
    for r in range(SH):
        e.uc.mem_write(sdata + r * (SW + 3), bytes(px[r * SW:(r + 1) * SW]))
    W, H = 420, 640
    data = TC.mk_buffer(e, STRIP, W, H, data=SDATA)
    before = bytes(e.uc.mem_read(data, W * H))
    dw, dh = (SW * g) >> 4, (SH * g) >> 4
    x, y = (26 * g) >> 4, (90 * g) >> 4
    e.w32(AR.G_DP_SCR_BIO, SCRATCH)
    e.w32(AR.G_DP_SCR_NEWS, SCRATCH + 0x100)
    if have_under:
        TC.mk_buffer(e, UNDER, dw, dh, data=UDATA)
        e.w32(AR.G_BIO_UNDER, UNDER)
    mk_flic(e, AR.FLIC_BIO, STRIP, x, y)
    land = e.run(VA["thunk_art_flic"], regs={"ecx": AR.FLIC_BIO, "esi": 0x5151, "ebx": 0x61, "edi": 0x62, "ebp": 0x63},
                 stack=[RET_SITE, x, y])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8 and e.reg("eax") == 0x55
    assert (e.reg("esi"), e.reg("ebx"), e.reg("edi"), e.reg("ebp")) == (0x5151, 0x61, 0x62, 0x63)
    fd = calls(e, AR.T_DP_FLICDRAW)
    assert len(fd) == 1 and fd[0][3] == AR.FLIC_BIO and fd[0][2][1:3] == [x, y]
    cp = calls(e, AR.BUF_COPY_3)
    if have_under:                                          # restore: under (0,0,dw,dh) -> strip (x,y,dw,dh), 1:1
        assert len(cp) == 1 and cp[0][3] == UNDER and cp[0][2][1:10] == [STRIP, 0, 0, dw, dh, x, y, dw, dh]
    else:
        assert not cp
    src = bytearray((SW + 3) * SH)
    for r in range(SH):
        src[r * (SW + 3):r * (SW + 3) + SW] = bytes(px[r * SW:(r + 1) * SW])
    want = SL.art_reblit(before, W, H, W, bytes(src), SW, SH, SW + 3, 9, x, y, 0, 0, g, 16)
    got = bytes(e.uc.mem_read(data, W * H))
    assert got == want and got != before
    # the key texels were skipped: outside the silhouette the strip is untouched
    assert got[(y + 1) * W + x + 1] == before[(y + 1) * W + x + 1]
    assert 9 not in got


@pytest.mark.parametrize("g", [22, 40])
def test_art_flic_news_unchanged_opaque(g):
    e = emu(g)
    sw, sh = 105, 87
    px = [(0x20 + (r & 1) * 0x40 + (c % 7)) & 0xFF for r in range(sh) for c in range(sw)]
    sdata = TC.mk_buffer(e, SCRATCH, sw, sh, data=SCDATA)
    e.uc.mem_write(sdata, bytes(px))
    W, H = 500, 400
    data = TC.mk_buffer(e, STRIP, W, H, data=SDATA)
    before = bytes(e.uc.mem_read(data, W * H))
    TC.mk_buffer(e, UNDER, 10, 10, data=UDATA)
    e.w32(AR.G_BIO_UNDER, UNDER)
    e.w32(AR.G_DP_SCR_NEWS, SCRATCH)
    e.w32(AR.G_DP_SCR_BIO, SCRATCH + 0x100)
    e.w32(AR.FLIC_NEWS + 0x59C, sw); e.w32(AR.FLIC_NEWS + 0x5A0, sh); e.w32(AR.FLIC_NEWS + 0x5A8, STRIP)
    land = e.run(VA["thunk_art_flic"], regs={"ecx": AR.FLIC_NEWS, "esi": 0x5151}, stack=[RET_SITE, 100, 90])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8 and e.reg("eax") == 0x55 and e.reg("esi") == 0x5151
    assert not calls(e, AR.BUF_COPY_3)
    got = bytes(e.uc.mem_read(data, W * H))
    assert got == SL.art_reblit(before, W, H, W, bytes(px), sw, sh, sw, 0x100, 100, 90, 0, 0, g, 16) and got != before


def test_art_flic_native_and_foreign_passthrough():
    for g, flic in ((16, AR.FLIC_BIO), (25, AR.FLIC_BIO + 0x10)):
        e = emu(g)
        data = TC.mk_buffer(e, STRIP, 64, 64, data=SDATA)
        before = bytes(e.uc.mem_read(data, 64 * 64))
        land = e.run(VA["thunk_art_flic"], regs={"ecx": flic, "esi": 0x77}, stack=[RET_SITE, 5, 6])
        assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8 and e.reg("eax") == 0x55 and e.reg("esi") == 0x77
        assert bytes(e.uc.mem_read(data, 64 * 64)) == before and not calls(e, AR.BUF_COPY_3)
