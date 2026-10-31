"""Unicorn parity + law sweep for group popup_art_reblit (assemble_artreblit.py).

Oracle = scaling_laws.art_reblit / art_reblit_row / quote_art_origin.  The thunks are emulated from their real
assembled bytes at their real cave VAs on top of the council harness (thunk_sd_reblit_wrap is the REAL council
code; thunk_portrait_drop is a `ret 0x18` stub)."""
from __future__ import annotations

import contextlib
import io

import pytest

import test_council_asm_parity as TC
from test_council_asm_parity import AC, HEAP, RET_SITE, SL, SP0

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_artreblit as AR

LAY = AR.assemble_all()
VA = {n: AR.PCAVE2 + off for n, (off, _b) in LAY.items()}
DROP_STUB = b"\xB8\x77\x00\x00\x00\xC2\x18\x00"          # mov eax,0x77 ; ret 0x18


def emu(g):
    e = TC.Emu(g, stubs={AC.PORTRAIT_DROP: DROP_STUB})
    e.uc.mem_map(AR.PCAVE2 + 0x1C000, 0x1000)
    e.uc.mem_map(AR.PCAVE2 + 0x2D000, 0x1000)
    for _n, (off, b) in LAY.items():
        e.uc.mem_write(AR.PCAVE2 + off, b)
    return e


def framed_sprite(w, h, key=9):
    """1-px frame (0x19, keyed chamfer corners) around a 1-row scanline interior: the *_sm.pcx structure."""
    px = []
    for r in range(h):
        for c in range(w):
            if (r in (0, h - 1)) and (c in (0, w - 1)):
                v = key
            elif r in (0, h - 1) or c in (0, w - 1):
                v = 0x19
            else:
                v = 0x20 + ((r // 2) * 2) % 0x60 + (r & 1) * 0x80 + (c % 3)
            px.append(v & 0xFF)
    return px


@pytest.mark.parametrize("g", [17, 21, 22, 25, 34, 40])
@pytest.mark.parametrize("sw,sh,offx,offy", [(7, 10, 0, 0), (12, 9, 1, 2), (200, 120, 0, 0), (131, 157, 0, 0), (5, 3, 0, 0),
                                            (12, 9, -1, -1)])   # negative offsets: C truncation, not Python floor
@pytest.mark.parametrize("y", [5, 6])                                   # y0 + jt odd at T = 1 too (jt = 1 here)
def test_art_reblit_matches_law(g, sw, sh, offx, offy, y):
    e = emu(g)
    px = framed_sprite(sw, sh)
    spr = HEAP + 0x10000
    TC.mk_sprite(e, spr, px, sw, sh, key=9, offx=offx, offy=offy)
    dest = HEAP + 0x30000
    W, H = 520, 420
    data = TC.mk_buffer(e, dest, W, H, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(data, W * H))
    land = e.run(VA["thunk_art_reblit"], regs={"ecx": spr, "ebx": 0x11, "esi": 0x22, "edi": 0x33, "ebp": 0x44},
                 stack=[RET_SITE, dest, 9, 3, y, g, 16])              # y off the 2T grid: the phase shows
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18
    for k, v in (("ebx", 0x11), ("esi", 0x22), ("edi", 0x33), ("ebp", 0x44)):
        assert e.reg(k) == v, k
    got = bytes(e.uc.mem_read(data, W * H))
    assert got == SL.art_reblit(before, W, H, W, bytes(px), sw, sh, sw, 9, 3, y, offx, offy, g, 16)
    assert got != before


def test_art_reblit_native_noop_and_clip():
    e = emu(16)
    px = framed_sprite(20, 20)
    spr = HEAP + 0x10000
    TC.mk_sprite(e, spr, px, 20, 20)
    dest = HEAP + 0x30000
    data = TC.mk_buffer(e, dest, 24, 24, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(data, 24 * 24))
    assert e.run(VA["thunk_art_reblit"], regs={"ecx": spr}, stack=[RET_SITE, dest, 9, 1, 1, 16, 16]) == RET_SITE
    assert bytes(e.uc.mem_read(data, 24 * 24)) == before
    e.uc.mem_write(AC.G, (25).to_bytes(4, "little"))
    assert e.run(VA["thunk_art_reblit"], regs={"ecx": spr}, stack=[RET_SITE, dest, 9, 10, 10, 25, 16]) == RET_SITE
    got = bytes(e.uc.mem_read(data, 24 * 24))
    assert got == SL.art_reblit(before, 24, 24, 24, bytes(px), 20, 20, 20, 9, 10, 10, 0, 0, 25, 16)
    guard = bytes(e.uc.mem_read(data + 24 * 24, 64))
    assert guard == bytes(64)                                          # nothing past the buffer


@pytest.mark.parametrize("g", [16, 22, 25, 40])
@pytest.mark.parametrize("quote", [False, True])
def test_art_wrap(g, quote):
    e = emu(g)
    sw, sh = 200, 120
    px = framed_sprite(sw, sh)
    spr = HEAP + 0x10000
    TC.mk_sprite(e, spr, px, sw, sh)
    dest = AC.FACTION_QUOTE_BUF if quote else HEAP + 0x30000
    W, H = 640, 480
    data = TC.mk_buffer(e, dest, W, H, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(data, W * H))
    x, y = 17, 9
    land = e.run(VA["thunk_art_wrap"], regs={"ecx": spr, "esi": 0x5151, "ebx": 0x61, "edi": 0x62},
                 stack=[RET_SITE, dest, 9, x, y, g, 16])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18
    assert e.reg("eax") == 0x77 and e.reg("esi") == 0x5151 and e.reg("ebx") == 0x61 and e.reg("edi") == 0x62
    drops = [c for c in e.calls if c[0] == AC.PORTRAIT_DROP]
    assert len(drops) == 1 and drops[0][2][1:7] == [dest, 9, x, y, g, 16] and drops[0][3] == spr
    got = bytes(e.uc.mem_read(data, W * H))
    if g <= 16:
        assert got == before
    elif quote:
        ox, oy = SL.quote_art_origin(x, y, g)
        assert got == SL.art_reblit(before, W, H, W, bytes(px), sw, sh, sw, 9, ox, oy, 0, 0, g, 16)
    else:
        assert got == TC.py_parity_reblit(before, W, H, W, bytes(px), sw, sh, sw, 9, x, y, 0, 0, g, 16)


@pytest.mark.parametrize("g", list(range(17, 65)))
@pytest.mark.parametrize("y0", [0, 1, 3, 6])
def test_scaling_art_reblit_row_law(g, y0):
    for sh in (4, 5, 9, 10, 119, 120, 157, 158):
        dh = sh * g // 16
        rows = [SL.art_reblit_row(j, sh, g, 16, y0) for j in range(dh)]
        cen = [SL.nn_center_index(j, dh, sh) for j in range(dh)]
        assert rows[0] == 0 and rows[-1] == sh - 1                     # both frame rows drawn, at the edges
        last = -1
        for j, (r, c) in enumerate(zip(rows, cen)):
            if c in (0, sh - 1):
                assert r == c
            else:
                # v2 (2026-10-04): the row shows its scanline FIELD -- art_scan_rows(g) device rows per field --
                # at the field's nearest source row; v3 (2026-10-06): the field of its DEST-BUFFER row y0 + j
                k = SL.art_scan_field(y0 + j, g)
                assert 1 <= r <= sh - 2 and (r - 1) & 1 == k and abs(r - c) <= 2, (g, sh, j)
                assert r >= last - 2                                   # never steps back more than a pair
                last = max(last, r)
        assert rows.index(sh - 1) == cen.index(sh - 1)                 # no picture row under the bottom frame
        if sh >= 9:                                                     # every scanline is a whole T-row stripe
            jt, jb = SL.art_frame_rows(sh, g)
            t = SL.art_scan_rows(g)
            j0 = jt + (-(y0 + jt)) % t                                  # the first interior row opening a grid stripe
            fields = [(rows[j] - 1) & 1 for j in range(j0, jb)]
            assert all(len(set(fields[s:s + t])) == 1 for s in range(0, len(fields) - t + 1, t)), (g, sh)
            assert all(fields[s] != fields[s + t] for s in range(0, len(fields) - 2 * t + 1, t)), (g, sh)


def test_scaling_art_reblit_native_identity():
    assert SL.quote_art_origin(11, 22, 16) == (11, 22)
    assert SL.quote_art_origin(11, 22, 25) == (7, 22 + 6) and SL.quote_art_origin(0, 0, 40) == (12, 18)
    src = bytes(range(64))
    assert SL.art_reblit(bytes(100), 10, 10, 10, src, 8, 8, 8, 255, 0, 0, 0, 0, 16) == bytes(100)


def test_scaling_art_reblit_negative_offset_truncates():
    """offx/offy * num / den truncates toward zero (cdq; idiv in the asm, int `/` in uimod portrait.cpp): at g = 25
    offsets (-1, -3) place the art at (x - 1, y - 4); Python's floor would say (x - 2, y - 5)."""
    W = 40
    out = SL.art_reblit(bytes(W * W), W, W, W, bytes([1]) * 16, 4, 4, 4, 255, 10, 10, -1, -3, 25, 16)
    first = min(i for i, v in enumerate(out) if v)
    assert (first % W, first // W) == (9, 6)


SD2_STUB = b"\xB8\x66\x00\x00\x00\xC2\x18\x00"           # mov eax,0x66 ; ret 0x18


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_art_draw(g):
    e = TC.Emu(g, stubs={AC.SD2: SD2_STUB})
    e.uc.mem_map(AR.PCAVE2 + 0x1C000, 0x1000)
    e.uc.mem_map(AR.PCAVE2 + 0x2D000, 0x1000)
    for _n, (off, b) in LAY.items():
        e.uc.mem_write(AR.PCAVE2 + off, b)
    sw, sh = 233, 124
    px = framed_sprite(sw, sh)
    spr = HEAP + 0x10000
    TC.mk_sprite(e, spr, px, sw, sh)
    dest = HEAP + 0x30000
    W, H = 700, 400
    data = TC.mk_buffer(e, dest, W, H, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(data, W * H))
    land = e.run(VA["thunk_art_draw"], regs={"ecx": spr, "esi": 0x5151, "ebx": 0x61, "edi": 0x62},
                 stack=[RET_SITE, dest, 9, 31, 12, g, 16])
    got = bytes(e.uc.mem_read(data, W * H))
    if g <= 16:
        assert land is None or land == RET_SITE                       # tail-jumped into the engine stub
        assert got == before and [c[2][1:7] for c in e.calls] == [[dest, 9, 31, 12, 16, 16]]
        return
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18 and e.reg("eax") == 0x66
    assert e.reg("esi") == 0x5151 and e.reg("ebx") == 0x61 and e.reg("edi") == 0x62
    assert [c[2][1:7] for c in e.calls] == [[dest, 9, 31, 12, g, 16]] and e.calls[0][3] == spr
    assert got == SL.art_reblit(before, W, H, W, bytes(px), sw, sh, sw, 9, 31, 12, 0, 0, g, 16)


@pytest.mark.parametrize("g", [16, 22, 25, 40])
@pytest.mark.parametrize("which", ["bio", "news", "other"])
def test_art_flic(g, which):
    FLICDRAW_STUB = b"\xB8\x55\x00\x00\x00\xC2\x08\x00"  # mov eax,0x55 ; ret 8
    e = TC.Emu(g)
    e.uc.mem_map(AR.PCAVE2 + 0x1C000, 0x1000)
    e.uc.mem_map(AR.PCAVE2 + 0x2D000, 0x1000)
    for _n, (off, b) in LAY.items():
        e.uc.mem_write(AR.PCAVE2 + off, b)
    e.uc.mem_write(AR.T_DP_FLICDRAW, FLICDRAW_STUB)
    e.uc.mem_map(0x733000, 0x3000)
    flic = {"bio": AR.FLIC_BIO, "news": AR.FLIC_NEWS, "other": AR.FLIC_BIO + 0x10}[which]
    sw, sh = 60, 100
    key = 9 if which == "bio" else 0x100                            # v2: the BIOSCAN path re-blits KEYED
    px = framed_sprite(sw, sh, key=key)                               # news: opaque, corners are real texels
    scratch, dest = HEAP + 0x88000, HEAP + 0x30000
    sdata = TC.mk_buffer(e, scratch, sw + 4, sh, pitch=sw + 4, data=HEAP + 0x90000)
    for r in range(sh):
        e.uc.mem_write(sdata + r * (sw + 4), bytes(px[r * sw:(r + 1) * sw]))
    W, H = 400, 400
    data = TC.mk_buffer(e, dest, W, H, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(data, W * H))
    e.w32(AR.G_DP_SCR_BIO, scratch); e.w32(AR.G_DP_SCR_NEWS, scratch)
    e.w32(AR.G_BIO_UNDER, 0)                                           # no save-under: re-blit only
    e.w32(flic + 0x59C, sw); e.w32(flic + 0x5A0, sh); e.w32(flic + 0x5A8, dest)
    land = e.run(VA["thunk_art_flic"], regs={"ecx": flic, "esi": 0x5151, "ebx": 0x61, "edi": 0x62},
                 stack=[RET_SITE, 40, 30])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8 and e.reg("eax") == 0x55
    assert e.reg("esi") == 0x5151 and e.reg("ebx") == 0x61 and e.reg("edi") == 0x62
    got = bytes(e.uc.mem_read(data, W * H))
    if g <= 16 or which == "other":
        assert got == before
    else:
        src = bytearray((sw + 4) * sh)
        for r in range(sh):
            src[r * (sw + 4):r * (sw + 4) + sw] = bytes(v & 0xFF for v in px[r * sw:(r + 1) * sw])
        assert got == SL.art_reblit(before, W, H, W, bytes(src), sw, sh, sw + 4, key, 40, 30, 0, 0, g, 16)
        assert got != before


BD2_STUB = b"\xB8\x44\x00\x00\x00\xC2\x18\x00"           # Buffer_draw_2 stand-in: mov eax,0x44 ; ret 0x18


@pytest.mark.parametrize("g", [16, 22, 25, 40])
@pytest.mark.parametrize("kind", ["art", "flag", "odd_size"])
def test_art_core(g, kind):
    """Blit-core site: filename-backed popup pictures (pcBits NULL) are re-blitted from the canvas-manager src
    Buffer; the UN flag keeps thunk_flag_restripe's LUT pass; native ratio = untouched."""
    e = TC.Emu(g, stubs={AC.BUF_DRAW2: BD2_STUB})
    e.uc.mem_map(AR.PCAVE2 + 0x1C000, 0x1000)
    e.uc.mem_map(AR.PCAVE2 + 0x2D000, 0x1000)
    for _n, (off, b) in LAY.items():
        e.uc.mem_write(AR.PCAVE2 + off, b)
    sw, sh = (233, 124) if kind == "odd_size" else (200, 120)
    px = bytearray(v & 0xFF for v in framed_sprite(sw, sh))
    if kind == "flag":
        px[sw + 2], px[2 * sw + 2] = 250, 230
    src, dest = HEAP + 0x88000, HEAP + 0x30000
    sdata = TC.mk_buffer(e, src, sw, sh, data=HEAP + 0x90000)
    e.uc.mem_write(sdata, bytes(px))
    W, H = 640, 400
    data = TC.mk_buffer(e, dest, W, H, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(data, W * H))
    num, den = (g, 16)
    land = e.run(VA["thunk_art_core"], regs={"ecx": src, "esi": 0x5151, "ebx": 0x61, "edi": 0x62, "ebp": 0x63},
                 stack=[RET_SITE, dest, 9, 21, 13, num, den])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18
    assert e.reg("esi") == 0x5151 and e.reg("ebx") == 0x61 and e.reg("edi") == 0x62 and e.reg("ebp") == 0x63
    draws = [c for c in e.calls if c[0] == AC.BUF_DRAW2]
    assert len(draws) == 1 and draws[0][2][1:7] == [dest, 9, 21, 13, num, den] and draws[0][3] == src
    got = bytes(e.uc.mem_read(data, W * H))
    if g <= 16:
        assert got == before
    elif kind == "flag":
        assert got != SL.art_reblit(before, W, H, W, bytes(px), sw, sh, sw, 9, 21, 13, 0, 0, g, 16)   # LUT pass only
        dw, dh = -(-200 * g // 16), -(-120 * g // 16)                   # the LUT pass itself, on the dest grid (Y = 13)
        assert got == TC._lut_expect(before, W, 21, 13, dw, dh, g)
    else:
        assert got == SL.art_reblit(before, W, H, W, bytes(px), sw, sh, sw, 9, 21, 13, 0, 0, g, 16)
