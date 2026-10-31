"""Unicorn parity for the council_scale thunks (assemble_council.py).

Oracle = scaling_laws (council_seed_rects, popup_field_right_src_ornate,
popup_field_top, popup_art_x, popup_textfollow_applies), a Python port of the
user-verified parity re-blit (hook_council_proto.js v22/v28), the v17 pair LUT,
and the run-26/27 probe vectors.  Every thunk is emulated from its REAL
assembled bytes at its REAL cave VA; engine callees are either landing pads
(emulation stops on arrival) or tiny `ret N` stubs for call-and-continue thunks.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
pytest.importorskip("pefile")

from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_council as AC  # noqa: E402

LAYOUT, _END = AC.assemble_all()
VA = {n: AC.PCAVE2 + LAYOUT[n][0] for n in LAYOUT}
R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
     "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}
STACK, SP0 = 0x00300000, 0x00308000
RET_SITE = 0x00600100
POPUP = 0x03000000
HEAP = 0x04000000
ENGINE_LANDINGS = [AC.SD2, AC.STC, AC.FONT_INIT, AC.BOX_SPRITE, AC.BUF_DRAW2, AC.TILEMASK, AC.SPRITE_DRAW,
                   AC.CONTENT_FRAME, AC.DEVFILL, AC.HOLLOWFLAT, AC.T_DP_ARTALIGN, AC.PORTRAIT_DROP, AC.BTN_GATE,
                   AC.CW_EXEC, AC.BUF_WRITE_STRINGS, RET_SITE,
                   AC.T_CW_MIRROR]   # thunk_cw_seeds' tail since 2026-10-25 W5B (test_council_mirror_asm_parity runs it)


def dp(v, g):
    return v if g <= 16 else (v * g) >> 4


class Emu:
    def __init__(self, g, stubs=None):
        """stubs: {addr: bytes} — callee bodies (e.g. `ret 0x18`) that are NOT landings."""
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        for base, size in ((AC.PCAVE2, 0x14000), (STACK, 0x10000), (POPUP, 0x4000), (HEAP, 0x100000),
                           (0x668000, 0x1000), (0x5D8000, 0x1000), (0x5DA000, 0x2000), (0x5E2000, 0x3000),
                           (0x618000, 0x1000), (0x600000, 0x1000), (0x9A6000, 0x1000), (0x669000, 0x1000),
                           (0x425000, 0x4000), (0x6FE000, 0x6000), (0x940000, 0x1000),
                           # the shared body's unframed-art identity test (t_art_frame_rows, 2026-10-17) reads the
                           # council portrait slots' pixel pointers (g_faction_sprites 0x78E978 + 8 * 0x65C) and
                           # the BIOSCAN colour bar's (g_diplo_colour_bar_sprite +4 = 0x7D1620)
                           (0x78E000, 0x5000), (0x7D1000, 0x1000),
                           # t_cw_mirror's page (W5B region): a landing here
                           (AC.T_CW_MIRROR & ~0xFFF, 0x1000)):
            uc.mem_map(base, size)
        for name, (off, blob) in LAYOUT.items():
            uc.mem_write(AC.PCAVE2 + off, blob)
        # the shared re-blit body thunk_parity_reblit's stub jumps into (assemble_artreblit, v2 2026-10-04)
        import assemble_artreblit as AR
        uc.mem_map(AC.PCAVE2 + (AC.OFF_REBLIT_BODY & ~0xFFF), 0x1000)
        ar = AR.assemble_all()
        uc.mem_write(AC.PCAVE2 + AC.OFF_REBLIT_BODY, ar["thunk_art_reblit_body"][1])
        # ... and the frame-row helper it CALLs (t_art_frame_rows, v4 2026-10-17; the pcave2 0x29000 page also holds
        # thunk_art_wrap / thunk_art_reblit / thunk_art_draw, which the art harnesses write over it)
        uc.mem_map(AC.PCAVE2 + (AR.OFF_ART_FRAME_ROWS & ~0xFFF), 0x1000)
        uc.mem_write(AR.ART_FRAME_ROWS, ar["t_art_frame_rows"][1])
        uc.mem_write(AC.G, g.to_bytes(4, "little", signed=True))
        stubs = dict(stubs or {})
        self.landings = set(a for a in ENGINE_LANDINGS if a not in stubs)
        for a in ENGINE_LANDINGS:
            uc.mem_write(a, stubs.get(a, b"\xf4"))
        self.calls = []          # (addr, esp, stack dwords)
        self.stub_addrs = set(stubs)
        self.stopped_at = None
        uc.hook_add(UC_HOOK_CODE, self._hook)

    def _hook(self, uc, addr, size, ud):
        if addr in self.landings:
            self.stopped_at = addr
            uc.emu_stop()
        elif addr in self.stub_addrs:
            esp = uc.reg_read(UC_X86_REG_ESP)
            self.calls.append((addr, esp, [self.r32(esp + 4 * i) for i in range(10)],
                               uc.reg_read(UC_X86_REG_ECX)))

    def w32(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "little", signed=True)

    def run(self, va, regs=None, stack=None, eflags=0x202):
        uc = self.uc
        stack = list(stack or [RET_SITE])
        sp = SP0
        for i, v in enumerate(stack):
            self.w32(sp + 4 * i, v)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_EFLAGS, eflags)
        for k, v in (regs or {}).items():
            uc.reg_write(R[k], v & 0xFFFFFFFF)
        self.stopped_at = None
        uc.emu_start(va, 0, count=5_000_000)
        return self.stopped_at

    def reg(self, k):
        return self.uc.reg_read(R[k])


def mk_buffer(emu, addr, w, h, pitch=None, data=None, fill=0xEE):
    """Minimal engine Buffer: data +0x54, w +0x80, h +0x84 (NEGATIVE), pitch +0x4A8."""
    pitch = pitch or w
    data = data or (addr + 0x1000)
    emu.w32(addr + 0x54, data)
    emu.w32(addr + 0x80, w)
    emu.w32(addr + 0x84, -h)
    emu.w32(addr + 0x4A8, pitch)
    emu.uc.mem_write(data, bytes([fill]) * (pitch * h))
    return data


def mk_sprite(emu, addr, pixels, w, h, key=9, offx=0, offy=0, pitch=None, pcbits=None):
    pitch = pitch or w
    pcbits = pcbits or (addr + 0x100)
    emu.w32(addr + 0, 0)
    emu.w32(addr + 4, pcbits)
    emu.uc.mem_write(addr + 8, bytes([key, 0, 0, 0]))
    emu.w32(addr + 0xC, pitch)
    emu.w32(addr + 0x10, w)
    emu.w32(addr + 0x14, h)
    emu.w32(addr + 0x18, w)
    emu.w32(addr + 0x1C, h)
    emu.w32(addr + 0x20, offx)
    emu.w32(addr + 0x24, offy)
    emu.uc.mem_write(pcbits, bytes(pixels))
    return pcbits


def py_parity_reblit(dest, dw_, dh_, dpitch, src, sw, sh, spitch, key, x, y, offx, offy, num, den):
    """thunk_parity_reblit since v2 (2026-10-04) = a stub into the shared re-blit body: scaling_laws.art_reblit."""
    return SL.art_reblit(dest, dw_, dh_, dpitch, src, sw, sh, spitch, key, x, y, offx, offy, num, den)


def py_parity_reblit_v1(dest, dw_, dh_, dpitch, src, sw, sh, spitch, key, x, y, offx, offy, num, den):
    """v1 (until 2026-10-04): port of hook_council_proto.js parityReblit with the ENGINE's floor dest dims."""
    x0 = x + (offx * num) // den
    y0 = y + (offy * num) // den
    dw = (sw * num) // den
    dh = (sh * num) // den
    out = bytearray(dest)
    if num <= den or x0 < 0 or y0 < 0:
        return bytes(out)
    iw = min(dw, dw_ - x0)
    if iw <= 0:
        return bytes(out)
    pmax = (sh - 1) >> 1
    for jj in range(dh):
        dy = y0 + jj
        if dy >= dh_:
            break
        p = min(((2 * jj + 1) * den) // (4 * num), pmax)
        r = 2 * p + (jj & 1)
        if r >= sh:
            r = sh - 1
        for i in range(iw):
            sx = ((2 * i + 1) * den) // (2 * num)
            if sx >= sw:
                sx = sw - 1
            v = src[r * spitch + sx]
            if v == key:
                continue
            out[dy * dpitch + x0 + i] = v
    return bytes(out)


def scanline_sprite(w, h, key=9):
    """two shadings per image row (bright/dark), a keyed top-left corner."""
    px = []
    for r in range(h):
        base = 0x20 + (r // 2) * 2
        for c in range(w):
            v = base + (r & 1) * 0x40 + (c % 3)
            if r == 0 and c == 0:
                v = key
            px.append(v & 0xFF)
    return px


# ---- tally: seed table -------------------------------------------------------
@pytest.mark.parametrize("g", list(range(16, 41)))
def test_cw_seeds_matches_law(g):
    e = Emu(g)
    e.uc.mem_write(AC.CWIN, b"\xCC" * 0xE00)
    land = e.run(VA["thunk_cw_seeds"], regs={"esi": AC.CWIN, "eax": 1, "ebx": 2, "ecx": 3, "edx": 4, "edi": 5})
    # 2026-10-25 W5B: the tail is push t_cw_mirror; ret (the right half mirrored about the rails, then Font_init --
    # emulated through the whole chain in test_council_mirror_asm_parity.py); this test pins thunk_cw_seeds' own table
    assert land == AC.T_CW_MIRROR
    for k in ("eax", "ebx", "ecx", "edx", "edi"):
        assert e.reg(k) == {"eax": 1, "ebx": 2, "ecx": 3, "edx": 4, "edi": 5}[k], k
    assert e.reg("esp") == SP0 and e.r32(SP0) == RET_SITE
    if g == 16:
        assert bytes(e.uc.mem_read(AC.CWIN, 0xE00)) == b"\xCC" * 0xE00     # native no-op
        return
    s = SL.council_seed_rects(g)
    rect = lambda a: tuple(e.r32(a + 4 * i) for i in range(4))
    assert rect(AC.CWIN + 0xBA4) == s["banner"]
    assert (e.r32(AC.CWIN + 0xBC4), e.r32(AC.CWIN + 0xBCC), e.r32(AC.CWIN + 0xBD0)) == s["params"]
    for c in range(7):
        assert rect(AC.CWIN + 0xBF4 + c * 0x20) == s["outer"][c], (g, c)
        assert rect(AC.CWIN + 0xC04 + c * 0x20) == s["inner"][c], (g, c)


# ---- tally: immediates ------------------------------------------------------
def _exe_pages():
    import pefile
    import config
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)     # the pristine base
    return pe.get_data(0x426000 - pe.OPTIONAL_HEADER.ImageBase, 0x3000)


EXE_PAGES = _exe_pages()


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_cw_immfix_table(g):
    e = Emu(g)
    e.uc.mem_write(0x426000, EXE_PAGES)
    e.w32(AC.G_CW_VPDONE, 1)                     # bootstrap already done this process
    land = e.run(VA["thunk_cw_immfix"], regs={"esi": 0x1234})
    assert land == RET_SITE and e.reg("esi") == 0x1234
    pages = bytes(e.uc.mem_read(0x426000, 0x3000))
    if g == 16:
        assert pages == EXE_PAGES                   # identity: vanilla bytes restored
    touched = set()
    for site, a, b, kind in AC.IMMTAB:
        want = dp(a, g) - dp(b, g)
        if kind & 2:
            want = -want
        o = site - 0x426000
        if kind & 1:
            have = struct.unpack_from("<i", pages, o)[0]
            touched.update(range(o, o + 4))
        else:
            have = struct.unpack_from("<b", pages, o)[0]
            touched.add(o)
        assert have == want, (hex(site), g)
    for i in range(0x3000):
        if i not in touched:
            assert pages[i] == EXE_PAGES[i], hex(0x426000 + i)   # nothing else disturbed


def test_cw_immfix_bails_without_bootstrap():
    e = Emu(25)
    e.uc.mem_write(0x426000, EXE_PAGES)
    e.w32(AC.G_CW_VPDONE, 0)
    e.w32(AC.IAT_LOADLIB, 0x669800)               # LoadLibraryA stub -> eax=0 (failure)
    e.uc.mem_write(0x669800, b"\x31\xc0\xc2\x04\x00")   # xor eax,eax; ret 4
    land = e.run(VA["thunk_cw_immfix"])
    assert land == RET_SITE
    assert bytes(e.uc.mem_read(0x426000, 0x3000)) == EXE_PAGES   # zero writes


# ---- tally: name-line y ----------------------------------------------------
@pytest.mark.parametrize("g,faction,gov", [(25, 2, 2), (25, 3, 2), (40, 1, 1), (22, 5, 0), (16, 2, 2)])
def test_cw_texty(g, faction, gov):
    e = Emu(g)
    e.w32(AC.GOV, gov)
    idx = faction * 2 + (1 if gov == faction else 0)
    spr = HEAP + 0x200
    e.w32(AC.CWIN + 0xD54 + idx * 4, spr)
    e.w32(spr + 0x1C, 115 if idx & 1 == 0 else 144)
    ph = e.r32(spr + 0x1C)
    ebp = SP0 - 0x100
    e.w32(ebp - 0x14, 500)
    e.w32(ebp + 8, 0x7777)
    land = e.run(VA["thunk_cw_texty"], regs={"ebx": faction, "esi": AC.CWIN, "edi": 0xBEEF, "ecx": 0xBEEF, "ebp": ebp})
    assert land == AC.STC and e.reg("ecx") == 0xBEEF
    if g == 16:
        assert e.r32(ebp + 8) == 0x7777
    else:
        assert e.r32(ebp + 8) == 500 + dp(ph, g) + dp(4, g)


# ---- parity re-blit ---------------------------------------------------------
@pytest.mark.parametrize("g", [17, 22, 25, 40])
@pytest.mark.parametrize("sw,sh,offx,offy", [(7, 10, 0, 0), (12, 9, 1, 2), (131, 157, 0, 0)])
def test_parity_reblit_matches_port(g, sw, sh, offx, offy):
    e = Emu(g)
    key = 9
    px = scanline_sprite(sw, sh, key)
    spr = HEAP + 0x10000
    mk_sprite(e, spr, px, sw, sh, key=key, offx=offx, offy=offy)
    dest = HEAP + 0x20000
    W, H = 420, 420
    data = mk_buffer(e, dest, W, H)
    before = bytes(e.uc.mem_read(data, W * H))
    x, y = 3, 4
    land = e.run(VA["thunk_parity_reblit"], regs={"ecx": spr, "ebx": 0x11, "esi": 0x22, "edi": 0x33, "ebp": 0x44},
                 stack=[RET_SITE, dest, key, x, y, g, 16])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18      # RET 0x18
    for k, v in (("ebx", 0x11), ("esi", 0x22), ("edi", 0x33), ("ebp", 0x44)):
        assert e.reg(k) == v, k
    want = py_parity_reblit(before, W, H, W, bytes(px), sw, sh, sw, key, x, y, offx, offy, g, 16)
    got = bytes(e.uc.mem_read(data, W * H))
    assert got == want
    assert got != before                                              # it did something


def test_parity_reblit_native_and_null_noop():
    e = Emu(16)
    spr = HEAP + 0x10000
    mk_sprite(e, spr, scanline_sprite(5, 6), 5, 6)
    dest = HEAP + 0x20000
    data = mk_buffer(e, dest, 64, 64)
    before = bytes(e.uc.mem_read(data, 64 * 64))
    assert e.run(VA["thunk_parity_reblit"], regs={"ecx": spr}, stack=[RET_SITE, dest, 9, 1, 1, 16, 16]) == RET_SITE
    assert bytes(e.uc.mem_read(data, 64 * 64)) == before            # num<=den: untouched
    e.w32(spr + 4, 0)                                                 # filename-backed: pcBits NULL
    assert e.run(VA["thunk_parity_reblit"], regs={"ecx": spr}, stack=[RET_SITE, dest, 9, 1, 1, 25, 16]) == RET_SITE
    assert bytes(e.uc.mem_read(data, 64 * 64)) == before


def test_parity_reblit_clips_to_dest():
    e = Emu(25)
    spr = HEAP + 0x10000
    px = scanline_sprite(20, 20)
    mk_sprite(e, spr, px, 20, 20)
    dest = HEAP + 0x20000
    data = mk_buffer(e, dest, 24, 24)
    guard = data + 24 * 24
    e.uc.mem_write(guard, b"\xAA" * 64)
    assert e.run(VA["thunk_parity_reblit"], regs={"ecx": spr}, stack=[RET_SITE, dest, 9, 10, 10, 25, 16]) == RET_SITE
    assert bytes(e.uc.mem_read(guard, 64)) == b"\xAA" * 64
    want = py_parity_reblit(bytes([0xEE]) * (24 * 24), 24, 24, 24, bytes(px), 20, 20, 20, 9, 10, 10, 0, 0, 25, 16)
    assert bytes(e.uc.mem_read(data, 24 * 24)) == want


# ---- portrait / logo sd2 wrappers -------------------------------------------
SD2_STUB = b"\xb8\x34\x12\x00\x00\xc2\x18\x00"      # mov eax,0x1234; ret 0x18


@pytest.mark.parametrize("g", [16, 25, 40])
@pytest.mark.parametrize("logo", [False, True])
def test_cw_sprite_wrappers(g, logo):
    e = Emu(g, stubs={AC.SD2: SD2_STUB})
    sw, sh = (84, 71) if logo else (96, 115)
    spr = HEAP + 0x10000
    px = scanline_sprite(sw, sh)
    mk_sprite(e, spr, px, sw, sh)
    e.w32(spr + 0x18, 86 if logo else sw)          # canvas w (logo: 86 vs blit 84)
    dest = HEAP + 0x20000
    W, H = 600, 600
    data = mk_buffer(e, dest, W, H)
    before = bytes(e.uc.mem_read(data, W * H))
    x, y = 40, 50
    land = e.run(VA["thunk_cw_logo" if logo else "thunk_cw_portrait"], regs={"ecx": spr},
                 stack=[RET_SITE, dest, 9, x, y, 1, 1])
    if g == 16:
        # native: tail-jmp into sd2 (the stub) with the frame untouched -> it returns straight to the site
        assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18 and e.reg("eax") == 0x1234
        assert len(e.calls) == 1 and e.calls[0][0] == AC.SD2 and e.calls[0][3] == spr
        assert e.calls[0][2][0:7] == [RET_SITE, dest, 9, x, y, 1, 1]
        assert bytes(e.uc.mem_read(data, W * H)) == before
        return
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18
    assert e.reg("eax") == 0x1234                                      # sd2's return survives the re-blit
    assert len(e.calls) == 1
    addr, _esp, args, ecx = e.calls[0]
    assert addr == AC.SD2 and ecx == spr
    cw = 86 if logo else sw
    want_x = x + ((cw - dp(cw, g)) >> 1) if logo else x
    assert args[1:7] == [dest, 9, want_x, y, g, 16]
    want = py_parity_reblit(before, W, H, W, bytes(px), sw, sh, sw, 9, want_x, y, 0, 0, g, 16)
    assert bytes(e.uc.mem_read(data, W * H)) == want


# ---- backdrop-37 / chips / button gate -------------------------------------
@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_cw_backdrop37(g):
    e = Emu(g)
    rect = HEAP + 0x40
    for i, v in enumerate((10, 20, 1000, 400)):
        e.w32(rect + 4 * i, v)
    land = e.run(VA["thunk_cw_backdrop37"], regs={"ecx": 0x5555, "eax": 7, "edx": 8}, stack=[RET_SITE, rect, HEAP + 0x80])
    assert land == AC.DEVFILL and e.reg("ecx") == 0x5555 and e.reg("eax") == 7 and e.reg("edx") == 8
    assert e.r32(rect + 8) == 1000 - (dp(0x37, g) - 0x37)
    assert [e.r32(SP0 + 4 * i) for i in range(3)] == [RET_SITE, rect, HEAP + 0x80]


def _params(e, addr, fill, mask):
    for i in range(10):
        e.w32(addr + 4 * i, 0x100 + i)       # border pieces
    e.w32(addr + 0x20, fill)
    e.w32(addr + 0x24, mask)


@pytest.mark.parametrize("g", [16, 25, 40])
@pytest.mark.parametrize("fill", [0, 0x6000])
def test_cw_chip(g, fill):
    stubs = {AC.BOX_SPRITE: b"\xc2\x08\x00", AC.HOLLOWFLAT: b"\xc2\x08\x00", AC.TILEMASK: b"\xc2\x20\x00"}
    e = Emu(g, stubs=stubs)
    rect, params = HEAP + 0x40, HEAP + 0x80
    for i, v in enumerate((100, 200, 190, 220)):
        e.w32(rect + 4 * i, v)
    _params(e, params, fill, 0x7000)
    land = e.run(VA["thunk_cw_chip"], regs={"ecx": 0xD0D0, "ebx": 1, "esi": 2, "edi": 3, "ebp": 4}, stack=[RET_SITE, rect, params])
    if g == 16:
        # native: tail-jmp into Buffer_box_sprite (the stub) with the frame untouched
        assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8
        assert len(e.calls) == 1 and e.calls[0][0] == AC.BOX_SPRITE and e.calls[0][3] == 0xD0D0
        assert e.calls[0][2][0:3] == [RET_SITE, rect, params]
        return
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8          # RET 8
    for k, v in (("ebx", 1), ("esi", 2), ("edi", 3), ("ebp", 4)):
        assert e.reg(k) == v
    K = (g + 15) >> 4
    names = [c[0] for c in e.calls]
    assert names[:2] == [AC.BOX_SPRITE, AC.HOLLOWFLAT]
    _a, _esp, args, ecx = e.calls[0]
    assert ecx == 0xD0D0 and args[1] == AC.SCR_R and args[2] == AC.SCR_A
    assert [e.r32(AC.SCR_R + 4 * i) for i in range(4)] == [100 + K, 200 + K, 190 - K - 1, 220 - K - 1]
    assert all(e.r32(AC.SCR_A + 4 * i) == 0 for i in range(8))       # borders nulled
    assert e.r32(AC.SCR_A + 0x20) == fill and e.r32(AC.SCR_A + 0x24) == 0x7000
    _a, _esp, args, ecx = e.calls[1]
    assert ecx == 0xD0D0 and args[1] == rect and args[2] == AC.SCR_B
    assert e.r32(AC.SCR_B + 0x20) == 0 and [e.r32(AC.SCR_B + 4 * i) for i in range(8)] == [0x100 + i for i in range(8)]
    if fill:
        assert names == [AC.BOX_SPRITE, AC.HOLLOWFLAT, AC.TILEMASK]
        _a, _esp, args, ecx = e.calls[2]
        assert ecx == 0xD0D0
        assert args[1:9] == [fill, 100, 200, 100, 200, 90, 20, 0x7000]
    else:
        assert names == [AC.BOX_SPRITE, AC.HOLLOWFLAT]


@pytest.mark.parametrize("esi,want", [
    (AC.CWIN + 0xD94, 1), (AC.CWIN + 0xD94 + 5 * 0xB4C, 1), (AC.CWIN + 0xD94 + 6 * 0xB4C, None),
    (AC.CWIN + 0xD94 - 4, None), (0x7FE80C, 0), (0x7FF358, 0), (0x123456, None)])
def test_btn_gate_pre_v2(esi, want):
    e = Emu(40)
    land = e.run(VA["thunk_btn_gate_pre"], regs={"esi": esi, "eax": 0x99})
    if want is None:
        assert land == AC.BTN_GATE and e.reg("esp") == SP0 and e.r32(SP0) == RET_SITE
    else:
        assert land == RET_SITE and e.reg("eax") == want
    assert e.reg("esi") == esi


# ---- Cast-a-Vote gates ------------------------------------------------------
def _popup(e, typ, art, body):
    e.w32(POPUP + 0x30ac, typ)
    e.w32(POPUP + 0x2144, art)
    e.w32(POPUP + 0x30d4, body)


GV_CASES = [  # (g, council, type, art, body) -> hit
    ((25, 1, 60000, 0x5000, 0), True), ((40, 1, 20000, 0x5000, 0), True),
    ((16, 1, 60000, 0x5000, 0), False), ((25, 0, 60000, 0x5000, 0), False),
    ((25, 1, 0, 0x5000, 0), False), ((25, 1, 50000, 0x5000, 0), False),
    ((25, 1, 60000, 0, 0), False), ((25, 1, 60000, 0x5000, 62), False), ((25, 1, 70000, 0x5000, 0), False)]


@pytest.mark.parametrize("case,hit", GV_CASES)
def test_gv_arthead(case, hit):
    g, council, typ, art, body = case
    e = Emu(g)
    e.w32(AC.G_COUNCIL_ACTIVE, council)
    _popup(e, typ, art, body)
    land = e.run(VA["thunk_gv_arthead"], stack=[RET_SITE, 0x111, POPUP, 0, 29, 73])
    assert land == (AC.SPRITE_DRAW if hit else AC.T_DP_ARTALIGN)
    # v3: armed branch pre-subtracts (5g>>4)-5 from x (via t_gv_artx) and dp(6)-6 from y (law
    # council_castvote_art v3); every other slot stays verbatim.
    x, y = SL.council_castvote_art(29, 73, g) if hit else (29, 73)
    assert e.reg("esp") == SP0 and [e.r32(SP0 + 4 * i) for i in range(6)] == [RET_SITE, 0x111, POPUP, 0, x, y]


def _yaml_bytes(names):
    """The SHIPPED (patches.yaml) bytes of `names`, templates resolved at their own VAs."""
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(ROOT / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    cs = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    out = {}
    for n in names:
        va = AC.PCAVE2 + int(cs[n]["offset"])
        out[n] = (va, ap.ByteTemplate(cs[n]["bytes"]).resolve(va, symtab))
    return out


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_gv_arthead_v3_shipped_bytes_follow_the_law(g):
    """2026-10-14: the SHIPPED head + t_gv_artx hand thunk_sprite_draw exactly council_castvote_art v3's (x, y) --
    the flag moved left by (5g>>4)-5 (7 @g40, 2 @g25, 1 @g22) and up by dp(6)-6; g<=16 untouched (gate closed)."""
    e = Emu(g)
    for _n, (va, blob) in _yaml_bytes(("thunk_gv_arthead", "t_gv_artx")).items():
        e.uc.mem_write(va, blob)
    e.w32(AC.G_COUNCIL_ACTIVE, 1)
    _popup(e, 60000, 0x5000, 0)
    land = e.run(VA["thunk_gv_arthead"], stack=[RET_SITE, 0x111, POPUP, 0, 47, 117])
    assert land == (AC.SPRITE_DRAW if g > 16 else AC.T_DP_ARTALIGN)
    assert (e.r32(SP0 + 0x10), e.r32(SP0 + 0x14)) == SL.council_castvote_art(47, 117, g)
    assert e.reg("esp") == SP0 and [e.r32(SP0 + 4 * i) for i in range(4)] == [RET_SITE, 0x111, POPUP, 0]


def test_gv_v3_yaml_is_the_assembler_output():
    shipped = _yaml_bytes(("thunk_gv_arthead", "t_gv_artx", "thunk_gv_frameskip"))
    for n, (va, blob) in shipped.items():
        assert va == VA[n] and blob == LAYOUT[n][1], n
    assert LAYOUT["thunk_gv_frameskip"][0] == 0x13800                      # nothing after the head moved
    assert LAYOUT["thunk_gv_arthead"][0] + len(LAYOUT["thunk_gv_arthead"][1]) <= 0x13800


@pytest.mark.parametrize("case,hit", GV_CASES)
def test_gv_frameskip(case, hit):
    g, council, typ, art, body = case
    e = Emu(g)
    e.w32(AC.G_COUNCIL_ACTIVE, council)
    _popup(e, typ, art, body)
    land = e.run(VA["thunk_gv_frameskip"], regs={"esi": POPUP, "ecx": 0xC0C0}, stack=[RET_SITE, 0x222, 0x333])
    assert e.reg("ecx") == 0xC0C0 and e.reg("esi") == POPUP
    if hit:
        assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8
    else:
        assert land == AC.CONTENT_FRAME and e.reg("esp") == SP0


def test_gv_arthead_null_win():
    e = Emu(25)
    e.w32(AC.G_COUNCIL_ACTIVE, 1)
    assert e.run(VA["thunk_gv_arthead"], stack=[RET_SITE, 0x111, 0, 0, 1, 2]) == AC.T_DP_ARTALIGN


# ---- flag restripe (Buffer_draw_2 wrapper) ----------------------------------
DRAW2_STUB = b"\xb8\x77\x00\x00\x00\xc2\x18\x00"     # mov eax,0x77; ret 0x18


def _flag_src(e, addr, remapped):
    data = mk_buffer(e, addr, 200, 120, fill=0x33)
    b1, b2 = (4, 240) if remapped else (250, 230)
    e.uc.mem_write(data + 200 + 2, bytes([b1]))
    e.uc.mem_write(data + 400 + 2, bytes([b2]))
    return data


def _lut_expect(dest_before, W, x0, y0, dw, dh, g):
    tb = list(range(256)); td = list(range(256))
    for bright, dark in AC.LUT_PAIRS:
        tb[dark] = bright; td[bright] = dark
    out = bytearray(dest_before)
    for r in range(dh):
        lut = tb if SL.flag_restripe_bright(y0 + r, g) else td        # the dest buffer's row, not the rect's
        for i in range(dw):
            o = (y0 + r) * W + x0 + i
            out[o] = lut[out[o]]
    return bytes(out)


@pytest.mark.parametrize("g", [18, 21, 22, 25, 40])
@pytest.mark.parametrize("remapped", [False, True])
@pytest.mark.parametrize("Y", [48, 49, 51])                            # on / off the 2T grid: the phase must show
def test_flag_restripe(g, remapped, Y):
    e = Emu(g, stubs={AC.BUF_DRAW2: DRAW2_STUB})
    src = HEAP + 0x30000
    _flag_src(e, src, remapped)
    dest = HEAP + 0x50000
    W, H = 700, 500
    data = mk_buffer(e, dest, W, H, fill=0x41)
    X = 42
    dw = -(-200 * g // 16); dh = -(-120 * g // 16)
    # paint a banded field: pair indices in both phases + non-pair text
    rows = []
    for r in range(dh + 3):
        rows.append(bytes([0x04 if ((r // 3) & 1) else 0xF0] * (dw + 3)))
    for r, row in enumerate(rows):
        e.uc.mem_write(data + (Y + r) * W + X, row)
    e.uc.mem_write(data + (Y + 5) * W + X + 7, bytes([0xFF, 0x2B, 0x4A, 0x2E, 0x23, 0x41]))
    before = bytes(e.uc.mem_read(data, W * H))
    land = e.run(VA["thunk_flag_restripe"], regs={"ecx": src, "ebx": 1, "esi": 2, "edi": 3, "ebp": 4},
                 stack=[RET_SITE, dest, 0, X, Y, g, 16])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18 and e.reg("eax") == 0x77
    for k, v in (("ebx", 1), ("esi", 2), ("edi", 3), ("ebp", 4)):
        assert e.reg(k) == v
    assert e.calls and e.calls[0][0] == AC.BUF_DRAW2 and e.calls[0][3] == src and e.calls[0][2][1:7] == [dest, 0, X, Y, g, 16]
    got = bytes(e.uc.mem_read(data, W * H))
    assert got == _lut_expect(before, W, X, Y, dw, dh, g)
    # even T-row stripes on the DEST buffer's grid (law stripe_top): bright (0x04) where the chrome's coloured member is
    t = SL.stripe_rows(g)
    for r in range(dh):
        v = got[(Y + r) * W + X]
        assert v == (0xF0 if (((Y + r) // t) & 1) else 0x04), r
        assert (v == 0x04) == SL.stripe_top(Y + r, g)
    assert got[(Y + 5) * W + X + 7 + 4] == 0x23 and got[(Y + 5) * W + X + 7 + 5] == 0x41   # non-pair untouched


def test_flag_restripe_passthrough_cases():
    # not the flag (no pair bytes) / native / wrong size -> dest untouched, eax preserved
    for g, w, h, pair in ((25, 200, 120, False), (16, 200, 120, True), (25, 200, 121, True), (25, 199, 120, True)):
        e = Emu(g, stubs={AC.BUF_DRAW2: DRAW2_STUB})
        src = HEAP + 0x30000
        data_s = mk_buffer(e, src, w, h, fill=0x33)
        if pair:
            e.uc.mem_write(data_s + w + 2, b"\xfa"); e.uc.mem_write(data_s + 2 * w + 2, b"\xe6")
        dest = HEAP + 0x50000
        data = mk_buffer(e, dest, 700, 500, fill=0xF0)
        before = bytes(e.uc.mem_read(data, 700 * 500))
        land = e.run(VA["thunk_flag_restripe"], regs={"ecx": src}, stack=[RET_SITE, dest, 0, 42, 48, g, 16])
        assert land == RET_SITE and e.reg("eax") == 0x77
        assert bytes(e.uc.mem_read(data, 700 * 500)) == before, (g, w, h, pair)


def test_flag_restripe_clips():
    e = Emu(25, stubs={AC.BUF_DRAW2: DRAW2_STUB})
    src = HEAP + 0x30000
    _flag_src(e, src, True)
    dest = HEAP + 0x50000
    W, H = 320, 200
    data = mk_buffer(e, dest, W, H, fill=0xF0)
    guard = data + W * H
    e.uc.mem_write(guard, b"\xAA" * 0x400)
    X, Y = 100, 100                                      # 313x188 would overrun -> clipped to 220x100
    land = e.run(VA["thunk_flag_restripe"], regs={"ecx": src}, stack=[RET_SITE, dest, 0, X, Y, 25, 16])
    assert land == RET_SITE
    assert bytes(e.uc.mem_read(guard, 0x400)) == b"\xAA" * 0x400
    got = bytes(e.uc.mem_read(data, W * H))
    before = bytes([0xF0]) * (W * H)
    assert got == _lut_expect(before, W, X, Y, W - X, H - Y, 25)


# ---- popup portrait re-blit wrap (fix D) ------------------------------------
DROP_STUB = b"\xb8\x05\x00\x00\x00\xc2\x18\x00"      # mov eax,5; ret 0x18


@pytest.mark.parametrize("g,dest_is_quote", [(25, False), (40, False), (25, True), (16, False)])
def test_sd_reblit_wrap(g, dest_is_quote):
    e = Emu(g, stubs={AC.PORTRAIT_DROP: DROP_STUB})
    spr = HEAP + 0x10000
    px = scanline_sprite(131, 157)
    mk_sprite(e, spr, px, 131, 157)
    dest = AC.FACTION_QUOTE_BUF if dest_is_quote else HEAP + 0x20000
    W, H = 500, 500
    data = mk_buffer(e, dest, W, H, data=HEAP + 0x60000)
    before = bytes(e.uc.mem_read(data, W * H))
    x, y = 23, 64
    land = e.run(VA["thunk_sd_reblit_wrap"], regs={"ecx": spr, "esi": 0x5151}, stack=[RET_SITE, dest, 9, x, y, g, 16])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18 and e.reg("eax") == 5 and e.reg("esi") == 0x5151
    assert e.calls[0][0] == AC.PORTRAIT_DROP and e.calls[0][3] == spr and e.calls[0][2][1:7] == [dest, 9, x, y, g, 16]
    got = bytes(e.uc.mem_read(data, W * H))
    if dest_is_quote or g == 16:
        assert got == before
    else:
        assert got == py_parity_reblit(before, W, H, W, bytes(px), 131, 157, 131, 9, x, y, 0, 0, g, 16)
        # run-28 measured rect: 204x245 @g25 from 131x157 (engine floor)
        if g == 25:
            assert got[(y + 244) * W + x + 203] != 0xEE and got[(y + 245) * W + x] == 0xEE and got[y * W + x + 204] == 0xEE


# ---- council exec bracket -----------------------------------------------------
def test_cw_enter_bracket():
    flag_seen = []
    stub = b"\xb8\x42\x00\x00\x00\xc2\x08\x00"                               # mov eax,0x42; ret 8
    e = Emu(25, stubs={AC.CW_EXEC: stub})
    e.uc.mem_write(0x426000, EXE_PAGES)
    e.uc.mem_write(AC.CW_EXEC, stub)                                          # (the page load overwrote it)
    e.w32(AC.G_CW_VPDONE, 1)

    def probe(uc, addr, size, ud):
        if addr == AC.CW_EXEC:
            flag_seen.append(e.r32(AC.G_COUNCIL_ACTIVE))
    e.uc.hook_add(UC_HOOK_CODE, probe)
    land = e.run(VA["thunk_cw_enter"], regs={"ecx": AC.CWIN}, stack=[RET_SITE, 0x1A, 0x2B])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 8 and e.reg("eax") == 0x42
    assert flag_seen == [1] and e.r32(AC.G_COUNCIL_ACTIVE) == 0
    assert e.calls[0][0] == AC.CW_EXEC and e.calls[0][3] == AC.CWIN and e.calls[0][2][1:3] == [0x1A, 0x2B]
    # the imm table ran before exec
    assert struct.unpack_from("<b", bytes(e.uc.mem_read(0x42768B + 2, 1)))[0] == dp(4, 25)


# ---- talk popups: fieldpads v6 (B-y + C), artalign v6 (B), textfollow v2 (A) --
def _run_fieldpads(g, typ, keyed, t_src, l_src, r_src, title_right, title_bottom, art=0, boxw=1087, title_left=22):
    e = Emu(g)
    e.w32(POPUP + 0x30ac, typ)
    e.w32(POPUP + 0x2144, art)
    e.w32(POPUP + 0x30bc, boxw)
    e.w32(AC.G_BAND_POPUP, POPUP if keyed else 0)
    e.w32(AC.G_TITLE_RIGHT, title_right)
    e.w32(AC.G_TITLE_LEFT, title_left)
    e.w32(AC.G_TITLE_BOTTOM, title_bottom)
    e.w32(AC.G_BAND_BOTTOM, title_bottom - 7)          # the stale PRE-arm bottom: must NOT be read
    ebp = SP0 - 0x100
    land = e.run(VA["thunk_popup_fieldpads"], regs={"esi": POPUP, "ebx": t_src, "edi": l_src, "ecx": r_src,
                                                     "ebp": ebp, "eax": 0x0A0A, "edx": 0x0B0B})
    assert land == RET_SITE and e.reg("esp") == SP0 + 4
    assert e.reg("eax") == 0x0A0A and e.reg("edx") == 0x0B0B                      # restored
    assert (e.uc.reg_read(UC_X86_REG_EFLAGS) & 0x40) == 0                          # test eax,eax on 0x0A0A -> ZF clear
    return e, (e.r32(ebp - 0x30), e.r32(ebp - 0x34), e.r32(ebp - 0x2c))


def test_fieldpads_v9_run26_ornate_vectors():
    # '' popup @g25: t_src 73, L src 29, R src 1063 (engine), title R' 1065 -> ENGINE arm T 69
    e, (T, L, Rr) = _run_fieldpads(25, 60000, True, 73, 29, 1063, 1065, 57)
    assert (T, L, Rr) == (69, 25, 1061)                                             # R: band inner, title draws FLAT
    assert e.r32(AC.G_FIELD_ANCHOR) == 69 and e.r32(AC.G_FIELD_L) == 25 and e.r32(AC.G_FIELD_R) == 1061
    assert e.r32(AC.G_FIELD_BOXW) == 1087 and e.r32(AC.G_BAND_POPUP) == POPUP      # key NOT consumed here
    assert e.r32(AC.G_TITLE_LEFT) == 22                                              # no art: anchors untouched
    # University (art): same T/R laws, field L/R stash zeroed, artalign anchors pre-adjusted:
    # @g25 x adjust = ceil-floor-delta = 2-1-1 = 0, y anchor = T + delta = 70
    e, (T, L, Rr) = _run_fieldpads(25, 60000, True, 73, 242, 1060, 1062, 57, art=0x79015c, boxw=1084)
    assert (T, L, Rr) == (69, 238, 1058)
    assert e.r32(AC.G_FIELD_L) == 0 and e.r32(AC.G_FIELD_R) == 0
    assert e.r32(AC.G_TITLE_LEFT) == 22 + SL.popup_art_ornate_x_adjust(25) == 23 and e.r32(AC.G_FIELD_ANCHOR) == 69
    assert SL.popup_art_y(69, 0, 25) == SL.popup_art_y(69, 60000, 25)               # artalign's flat math on the adjusted anchor == the ornate law


def test_fieldpads_v9_g40_probe_vectors():
    # probe 2026-08-23c @g40: t_src [30e8]=117 -> ENGINE arm T 110 (union top 103, text 117: proportionate);
    # title_left s(13)=32 -> 30 (ceil 3 - floor 2 - delta 3); anchor 113 (= T + delta)
    e, (T, L, Rr) = _run_fieldpads(40, 60000, True, 117, 47, 1702, 1709, 92, art=0x79015c, boxw=1736, title_left=32)
    assert T == 110 and T == SL.popup_field_top(117, 92, 60000, True, 40)
    assert Rr == 1709 - 7 and L == 40
    assert e.r32(AC.G_TITLE_LEFT) == 32 + SL.popup_art_ornate_x_adjust(40) == 33
    assert e.r32(AC.G_FIELD_ANCHOR) == 110
    # artalign (unchanged v6 math) on the adjusted anchors reproduces the ornate laws
    assert e.r32(AC.G_TITLE_LEFT) + 5 + (40 >> 4) == SL.popup_art_x(32 - SL.ornate_title_inset_delta(40), 60000, 40)
    assert e.r32(AC.G_FIELD_ANCHOR) - 7 + 6 == SL.popup_art_y(110, 60000, 40)
    # the drawn chain: flat band bottom stroke ON row 92, union top 103, d528 top 110, text 117
    assert (T - 7) - (92 + 1) == 10
    # no art: anchors untouched
    e, (T, _L, _R) = _run_fieldpads(40, 60000, True, 117, 47, 1702, 1709, 92, title_left=32)
    assert T == 110 and e.r32(AC.G_TITLE_LEFT) == 32 and e.r32(AC.G_FIELD_ANCHOR) == 110


def test_fieldpads_v7_flat_keeps_v5():
    # PROTOCOL DIRECTOR @g25 (flat, keyed): ENGINE arm T = 59 - 4 = 55 (2026-09-18), R = 1075+4, L = 372-4
    e, (T, L, Rr) = _run_fieldpads(25, 0, True, 59, 372, 1075, 1083, 43)
    assert (T, L, Rr) == (55, 368, 1079)
    assert e.r32(AC.G_TITLE_LEFT) == 22 and e.r32(AC.G_FIELD_ANCHOR) == 55
    # slide family keyed too; unkeyed flat -> default arm
    assert _run_fieldpads(25, 50000, True, 59, 372, 1075, 1083, 43)[1] == (55, 368, 1079)
    assert _run_fieldpads(25, 0, False, 59, 372, 1075, 1083, 43)[1] == (55, 368, 1079)
    # ornate but UNKEYED (band not stashed this draw): engine R, default T, anchors untouched
    e, tlr = _run_fieldpads(25, 60000, False, 73, 29, 1063, 1065, 59, art=0x79015c)
    assert tlr == (69, 25, 1067) and e.r32(AC.G_TITLE_LEFT) == 22 and e.r32(AC.G_FIELD_ANCHOR) == 69


@pytest.mark.parametrize("g", list(range(16, 41)))
def test_fieldpads_v7_law_sweep(g):
    w = SL.dp(696, g)
    pre_r = w - 9 - SL.popup_pad(3, g) - 2
    title_r = pre_r - (SL.ornate_title_inset_delta(g) if g > 16 else 0)
    # the engine's ecx at the fieldpads call = pre_r - 9 (native `sub ecx,9` @0x40612c on top of the scaled -10)
    r_src = pre_r - 9
    t_pre = SL.ornate_title_engine_top(g)                                             # 13 / 15 @g25 / 19 @g40
    t_src = SL.dp(47, g)
    title_b = SL.ornate_title_outer_bottom(t_pre, g)                                  # s(37)
    tl_post = SL.ornate_title_rect(t_pre, t_pre, 1000, g)[0]                          # s(13)
    e, (T, L, Rr) = _run_fieldpads(g, 60000, True, t_src, SL.dp(19, g), r_src, title_r, title_b,
                                    art=0x79015c, title_left=tl_post)
    ps3 = SL.popup_pad(3, g) if g > 16 else 3
    delta = SL.title_grow_delta(g)
    if g == 16:
        assert (T, Rr) == (t_src - 3, r_src + 3)                                     # vanilla identity
        assert e.r32(AC.G_FIELD_ANCHOR) == T
        return
    assert Rr == SL.popup_field_right_src_ornate(pre_r, g) + ps3
    assert T == SL.popup_field_top(t_src, title_b, 60000, True, g) == t_src - ps3   # ENGINE arm
    assert Rr == title_r - ps3 + delta                                                # == band inner (drawn)
    # drawn channel: union top (T - ps3) vs the flat band stroke (ON row s(37), inclusive footprint) stays
    # proportionate to vanilla's 4 clear rows (37..40) within the floor cascade
    assert -2 <= ((T - ps3) - (SL.popup_scale_floor(37, g) + delta + 1)) - ((4 * g) >> 4) <= 2
    # artalign anchors: x -> adjacent to the grown band stroke, y -> the union's drawn top
    tl = tl_post
    assert e.r32(AC.G_TITLE_LEFT) == tl + SL.popup_art_ornate_x_adjust(g)
    assert e.r32(AC.G_TITLE_LEFT) + (g >> 4) == tl - delta + ((g + 15) >> 4)        # drawn art x == stroke edge + 1
    assert e.r32(AC.G_FIELD_ANCHOR) - ps3 - delta == T - ps3                         # drawn art y == union top
    # flat keyed family == popup_field_top band arm at every g (title bottom == band bottom there)
    e, (T2, _L2, R2) = _run_fieldpads(g, 0, True, t_src, SL.dp(19, g), r_src, title_r, SL.dp(37, g))
    assert T2 == SL.popup_field_top(t_src, SL.dp(37, g), 0, True, g) and R2 == r_src + ps3


def test_artalign_v6_run26_vector():
    # University popup @g25: title_left (post-shift) 22, field anchor 69 -> x 28, y 71 (flat law, delta == 0)
    e = Emu(25)
    e.w32(AC.G_BAND_POPUP, POPUP)
    e.w32(AC.G_TITLE_LEFT, 22)
    e.w32(AC.G_BAND_LEFT, 15)                 # the PRE-shift stash must no longer be read
    e.w32(AC.G_FIELD_ANCHOR, 69)
    land = e.run(VA["thunk_popup_artalign"], stack=[RET_SITE, 0x111, POPUP, 0, 29, 73])
    assert land == AC.SPRITE_DRAW and e.reg("esp") == SP0
    assert e.r32(SP0 + 0x10) == 28 and e.r32(SP0 + 0x14) == 71
    assert e.r32(AC.G_BAND_POPUP) == 0                                      # key consumed
    assert e.r32(SP0 + 0x10) + SL.popup_art_ornate_x_adjust(25) == SL.popup_art_x(15, 60000, 25)   # fieldpads pre-adds the adjust
    assert e.r32(SP0 + 0x14) == SL.popup_art_y(69, 0, 25)
    # flat popup: title_left == band_left, unchanged from v5
    e = Emu(25)
    e.w32(AC.G_BAND_POPUP, POPUP); e.w32(AC.G_TITLE_LEFT, 27); e.w32(AC.G_BAND_LEFT, 27); e.w32(AC.G_FIELD_ANCHOR, 55)
    assert e.run(VA["thunk_popup_artalign"], stack=[RET_SITE, 0x111, POPUP, 0, 1, 2]) == AC.SPRITE_DRAW
    assert e.r32(SP0 + 0x10) == SL.popup_art_x(27, 0, 25) and e.r32(SP0 + 0x14) == SL.popup_art_y(55, 0, 25)
    # unkeyed / native: passthrough
    e = Emu(25); e.w32(AC.G_BAND_POPUP, 0)
    assert e.run(VA["thunk_popup_artalign"], stack=[RET_SITE, 0x111, POPUP, 0, 1, 2]) == AC.SPRITE_DRAW
    assert e.r32(SP0 + 0x10) == 1 and e.r32(SP0 + 0x14) == 2


def test_artalign_v6_is_v5_plus_one_dword():
    off, b6 = LAYOUT["thunk_popup_artalign"]
    b5 = bytearray(b6)
    i = b6.find(AC.G_TITLE_LEFT.to_bytes(4, "little"))
    assert i > 0 and b6.count(AC.G_TITLE_LEFT.to_bytes(4, "little")) == 1
    b5[i:i + 4] = AC.G_BAND_LEFT.to_bytes(4, "little")
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    symtab = ap.build_symbol_table(symbols, caves)
    v5_hex = ("A1 {abs32:g_popup_scale_num} 83 F8 10 7E 46 8B 0D {abs32:g_band_popup} 3B 4C 24 08 75 3A 33 C9 89 0D "
              "{abs32:g_band_popup} 8B 0D {abs32:g_band_left} 8B D0 C1 FA 04 8D 4C 11 05 89 4C 24 10 8D 14 40 C1 FA 04 "
              "8B 0D {abs32:g_field_anchor} 2B CA 8B D0 83 EA 10 C1 FA 1F 2B CA 83 C1 06 89 4C 24 14 68 {abs32:thunk_sprite_draw} C3")
    # 2026-09-18: + the delta shift count 3 -> 31 (title_grow_delta == 0)
    assert bytes(b5) == ap.ByteTemplate(v5_hex).resolve(AC.PCAVE2 + off, symtab)


@pytest.mark.parametrize("g,typ,art,ext,want_follow", [
    (25, 0, 0, 0, True), (25, 50000, 0, 0, True), (25, 60000, 0, 0, False), (25, 20000, 0, 0, False),
    (25, 0, 0x5000, 0, False), (25, 0, 0, 0x733990, False), (16, 0, 0, 0, False), (40, 10000000, 0, 0, False)])
def test_textfollow_v2_gate(g, typ, art, ext, want_follow):
    e = Emu(g)
    e.w32(POPUP + 0x30ac, typ); e.w32(POPUP + 0x2144, art); e.w32(POPUP + 0xa14, ext)
    e.w32(AC.G_D528_LEFT, 368)
    land = e.run(VA["thunk_pf_textfollow"], regs={"esi": POPUP, "ecx": 0xD1}, stack=[RET_SITE, 0x100, 29, 73, 1026])
    assert land == AC.BUF_WRITE_STRINGS and e.reg("ecx") == 0xD1 and e.reg("esp") == SP0
    assert want_follow == SL.popup_textfollow_applies(typ, art, ext, g)
    assert e.r32(SP0 + 8) == (368 + SL.popup_pad(3, g) if want_follow else 29)


@pytest.mark.parametrize("g,typ", [(40, 60000), (25, 60000), (40, 0), (16, 60000)])
def test_textfollow_never_touches_y(g, typ):
    """the body-text Y is the engine's [30e8] for every family (the 2026-08-23b Y arm was reverted)"""
    e = Emu(g)
    e.w32(POPUP + 0x30ac, typ); e.w32(POPUP + 0x2144, 0x5000); e.w32(POPUP + 0xa14, 0)
    land = e.run(VA["thunk_pf_textfollow"], regs={"esi": POPUP, "ecx": 0xD1}, stack=[RET_SITE, 0x100, 29, 117, 1026])
    assert land == AC.BUF_WRITE_STRINGS and e.reg("ecx") == 0xD1 and e.reg("esp") == SP0
    assert e.r32(SP0 + 0xC) == 117 and e.r32(SP0 + 8) == 29


def test_textfollow_v2_faction_singleton():
    e = Emu(25)
    e.w32(AC.G_D528_LEFT, 368)
    land = e.run(VA["thunk_pf_textfollow"], regs={"esi": AC.FACTION_POPUP}, stack=[RET_SITE, 0x100, 29, 73, 1026])
    assert land == AC.BUF_WRITE_STRINGS and e.r32(SP0 + 8) == 29


# ---- layout sanity -----------------------------------------------------------
def test_layout_fits_and_is_disjoint():
    spans = []
    for name, (off, b) in LAYOUT.items():
        spans.append((off, off + len(b), name))
    for name, off, size in AC.CELLS:
        spans.append((off, off + size, name))
    spans.sort()
    for (a0, a1, n1), (b0, b1, n2) in zip(spans, spans[1:]):
        assert a1 <= b0, (n1, n2)
    assert spans[-1][1] <= AC.SECTION_END
    assert (AC.G_FLAG_LUT & 0x1FF) == 0                          # xor ebx,0x100 LUT toggle needs bit 8 CLEAR
    assert AC.verify_live() == []


def test_template_roundtrip_is_exact():
    """Templatized yaml hex -> patcher ByteTemplate.resolve == the assembled bytes.
    Regression for build 1a2da25b: `jmp Font_init` was emitted as E9 {abs32:Font_init}
    (capstone reports branch operands as absolute targets) -> the patcher wrote an
    absolute address into the rel32 field -> EIP 0x1038244 on council open."""
    names = {n: AC.PCAVE2 + LAYOUT[n][0] for n, _ in AC.NEW_THUNKS}
    extra = {va: n for n, va in names.items()}
    extra.update(AC.EXTRA_SYMS)
    assert AC.roundtrip_problems(LAYOUT, extra) == []
    # and no branch ever carries a placeholder
    for name, (off, b) in LAYOUT.items():
        hexs = AC.templatize(b, AC.PCAVE2 + off, extra)
        toks = hexs.split()
        for i, t in enumerate(toks):
            if t.startswith("{") and i > 0:
                assert toks[i - 1] != "E9" and not (toks[i - 1].startswith("0F") and t.startswith("{rel32")), (name, toks[i - 1], t)


def test_sites_are_fresh():
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    ours = {s for _i, _f, s, _t, _th, _n in AC.SITES}
    for s in sites:
        va = int(s.get("virtual_addr", 0) or 0)
        if va in ours:
            assert s.get("group") == "council_scale", f"site {va:#x} owned by {s.get('group')}"
