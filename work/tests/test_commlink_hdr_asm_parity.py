"""COMMLINK multiplayer header strip (assemble_commlink_hdr.py): the yaml bytes under Unicorn vs the law.

Law: scaling_laws.commlink_zone_map / commlink_header_synth / scanicon_pair_lut.  Ports: t_clhd_zone (the zone
map), t_clhd_lut (the pair LUT, cached), t_clhd_draw (the whole post-pass), t_clmp_post (t_clmp_synth's tail: the
gate).  Arts: the REAL header (MultiWin +0x1110, read off the pristine image once per module) and synthetic 138 x 28
boxes with two scanline pairs sharing an index, key texels and AA noise.  Every g 17..40 (+ 48 / 60), both heights
the core can hand over (sc(28) and the multiplayer span's +1), negative / cut offsets; the refusals leave the dest;
callee-saved registers and the stdcall cleanup hold.  Cost: ~10 s (one image boot for the real art).
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn import x86_const as X  # noqa: E402

import apply_patches as ap  # noqa: E402
import assemble_commlink_hdr as H  # noqa: E402
import scaling_laws as SL  # noqa: E402

KEY = 9
STACK, MARKER = 0x00200000, 0x00300000
DBUF, DDATA, SDATA = 0x00710000, 0x01000000, 0x00720000
HEADER = SL.COMMLINK_HEADER_SPRITE
FILL = 0x77
REGS = {X.UC_X86_REG_EBX: 0x1111, X.UC_X86_REG_ESI: 0x2222, X.UC_X86_REG_EDI: 0x3333, X.UC_X86_REG_EBP: 0x4444}


def _live():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    out = {}
    for c in caves:
        for e in c.get("contents") or []:
            va = int(c["virtual_addr"]) + int(e["offset"])
            out[e["id"]] = (va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, sym)))
    return out, sym


LIVE, SYM = _live()
NAMES = ("t_clmp_post", "t_clhd_draw", "t_clhd_zone", "t_clhd_lut", "t_clhd_snap", "t_clmp_col", "t_clmp_pre",
         "g_clhd_rsegs", "g_clhd_csegs")


def test_yaml_bytes_are_the_assembler_output():
    built = H.build()
    for n in NAMES:
        assert LIVE[n] == (H.VA[n], built[n]), n
    for n in H.BSS:
        assert SYM[n] == H.VA[n], n


class Rig:
    def __init__(self):
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(H.PCAVE2 + 0x40000, 0x4000)
        uc.mem_map(H.MC_ON & ~0xFFF, 0x1000)                    # g_mc_on / g_mc_w / t_mc_col's page
        uc.mem_map(0x668000, 0x1000)
        uc.mem_map(HEADER & ~0xFFF, 0x1000)
        uc.mem_map(0x00700000, 0x1000)
        uc.mem_map(DBUF, 0x1000)
        uc.mem_map(SDATA, 0x10000)
        uc.mem_map(DDATA, 0x200000)
        uc.mem_map(STACK - 0x10000, 0x20000)
        uc.mem_map(MARKER, 0x1000)
        for n in NAMES:
            va, b = LIVE[n]
            uc.mem_write(va, b)

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def call(self, entry, args, ret_n, ecx=0):
        sp = STACK
        self.uc.mem_write(sp, struct.pack("<I", MARKER) + b"".join(struct.pack("<I", a & 0xFFFFFFFF) for a in args))
        self.uc.reg_write(X.UC_X86_REG_ESP, sp)
        self.uc.reg_write(X.UC_X86_REG_ECX, ecx)
        for r, v in REGS.items():
            self.uc.reg_write(r, v)
        self.uc.emu_start(entry, MARKER, count=400_000_000)
        assert self.uc.reg_read(X.UC_X86_REG_EIP) == MARKER
        assert self.uc.reg_read(X.UC_X86_REG_ESP) - sp == 4 + ret_n, "stdcall cleanup"
        for r, v in REGS.items():
            assert self.uc.reg_read(r) == v, "callee-saved register clobbered"
        return self.uc.reg_read(X.UC_X86_REG_EAX)

    def setup(self, g, art, *, bw, bh, key=KEY, spr=HEADER, pitch=None, data=True, ddata=True, period=None, seed=0):
        sh, sw = len(art), len(art[0])
        pitch = sw if pitch is None else pitch
        self.uc.mem_write(SDATA, b"".join(bytes(r) + bytes(pitch - sw) for r in art))
        self.uc.mem_write(spr, bytes(0x2C))
        self.w32(spr + 4, SDATA if data else 0)
        self.uc.mem_write(spr + 8, bytes([key & 0xFF]))
        for off, v in ((0xC, pitch), (0x10, sw), (0x14, sh)):
            self.w32(spr + off, v)
        for off, v in ((0x54, DDATA if ddata else 0), (0x4A8, bw), (0x80, bw), (0x84, -bh)):
            self.w32(DBUF + off, v)
        self.w32(SL.G_ADDR if hasattr(SL, "G_ADDR") else 0x668740, g)
        self.w32(0x66879C, SL.stripe_period(g) if period is None else period)
        noise = random.Random(seed).randbytes(bw * bh)
        self.uc.mem_write(DDATA, noise)
        return noise

    def plane(self, bw, bh):
        return bytes(self.uc.mem_read(DDATA, bw * bh))


@pytest.fixture(scope="module")
def rig():
    return Rig()


@pytest.fixture(scope="module")
def real_art(bak_path):
    """The header as the engine holds it: read off the pristine image's built COMMLINK panel (one boot)."""
    import commlink_mp_emu as C
    import numpy as np
    got = {}

    def grab(e):
        f = [e.s32(HEADER + 4 * i) for i in range(6)]
        a = np.frombuffer(bytes(e.uc.mem_read(f[1] & 0xFFFFFFFF, f[3] * f[5])), np.uint8).reshape(f[5], f[3])
        got["art"] = a[:, :f[4]].tolist()
        got["key"] = e.r32(HEADER + 8) & 0xFF
    C.panel(bak_path, 16, 0, hooks=[(C.REDRAW, grab)])
    return got["art"], got["key"]


def synthetic(seed: int):
    """A 138 x 28 box like the header: outside pair (a, b), inside pair (c, a) -- `a` shared at opposite parities --,
    1-px border / rail / edge lines, a few AA texels, optional key texels."""
    rnd = random.Random(seed)
    a, b, c, line, rail, edge, aa1, aa2 = rnd.sample(range(10, 250), 8)
    rows = []
    for y in range(28):
        r = []
        for x in range(138):
            inside = 11 <= x <= 127 and 5 <= y <= 22
            if x == 0:
                v = edge
            elif x in (5, 133):
                v = rail
            elif (y in (2, 25) and 13 <= x <= 124) or (x in (10, 128) and 5 <= y <= 22):
                v = line
            elif inside:
                v = c if y % 2 == 0 else a
            else:
                v = a if y % 2 == 0 else b
            if rnd.random() < 0.01:
                v = rnd.choice((aa1, aa2))
            if seed % 2 and rnd.random() < 0.01:
                v = KEY
            r.append(v)
        rows.append(r)
    return rows


ARTS = {f"syn{s}": synthetic(s) for s in range(4)}


# ------------------------------------------------------------------------------------------------- t_clhd_zone
ZONE_OUT = 0x00700000


@pytest.mark.parametrize("segs", [SL.COMMLINK_HEADER_ROW_SEGS, SL.COMMLINK_HEADER_COL_SEGS,
                                  ((3, 0), (1, 1), (7, 0)), ((1, 1), (5, 0), (5, 0), (1, 1)), ((2, 0),)])
def test_zone_is_commlink_zone_map(rig, segs):
    segs_va = 0x00700800
    rig.uc.mem_write(segs_va, H.seg_bytes(segs))
    total = sum(n for n, _ in segs)
    for k in (1, 2, 3, 4):
        for dst in range(1, min(4 * total + 8, 700)):
            want = SL.commlink_zone_map(segs, dst, k)
            rig.uc.mem_write(ZONE_OUT, b"\xEE" * (dst + 4))
            ok = rig.call(H.VA["t_clhd_zone"], (segs_va, len(segs), dst, k, ZONE_OUT), 0x14)
            if want is None:
                assert ok == 0, (segs, dst, k)
            else:
                assert ok == 1 and list(rig.uc.mem_read(ZONE_OUT, dst)) == want, (segs, dst, k)
                assert bytes(rig.uc.mem_read(ZONE_OUT + dst, 4)) == b"\xEE" * 4, "writes past dst_n"


# ------------------------------------------------------------------------------------------------- t_clhd_snap
@pytest.mark.parametrize("g", list(range(17, 61)))
def test_snap_is_commlink_header_rowmap(rig, g):
    """t_clhd_zone then t_clhd_snap on the row segments == commlink_header_rowmap, every dy phase (negative too) and
    both heights the core hands over."""
    rig.w32(0x668740, g)
    rig.w32(0x66879C, SL.stripe_period(g))
    dh = SL.strip_synth_dims(138, 28, g, 16)[1]
    for h in (dh, dh + 1):
        for dy in range(-2 * SL.stripe_period(g) - 1, 3 * SL.stripe_period(g) + 2):
            assert rig.call(H.VA["t_clhd_zone"], (H.VA["g_clhd_rsegs"], len(SL.COMMLINK_HEADER_ROW_SEGS), h,
                                                  SL.stroke_width(g), H.VA["g_clhd_rmap"]), 0x14) == 1
            rig.call(H.VA["t_clhd_snap"], (h, dy), 8)
            assert list(rig.uc.mem_read(H.VA["g_clhd_rmap"], h)) == SL.commlink_header_rowmap(h, dy, g), (h, dy)


# ------------------------------------------------------------------------------------------------- t_clhd_lut
def _lut_words(rig):
    return struct.unpack("<512H", rig.uc.mem_read(H.VA["g_clhd_lut"], 1024))


def _law_lut(art, key):
    lut, _n = SL.scanicon_pair_lut(art, key)
    return tuple(lut.get((k >> 1, k & 1), 0xFFFF) for k in range(512))


def test_lut_is_scanicon_pair_lut_and_the_cache_follows_the_texels(rig, real_art):
    arts = [(real_art[0], real_art[1])] + [(a, KEY) for a in ARTS.values()]
    for art, key in arts + arts[::-1]:                     # same pointer every time: the hash must see the change
        rig.setup(22, art, bw=8, bh=8, key=key)
        rig.call(H.VA["t_clhd_lut"], (SDATA, 138, 138, 28, key), 0x14)
        assert _lut_words(rig) == _law_lut(art, key)
    real, key = real_art
    lut = SL.scanicon_pair_lut(real, key)[0]
    assert lut == {(0x41, 1): 0xC5, (0xC2, 0): 0xC5, (0xC5, 0): 0x41, (0xC5, 1): 0xC2}, lut


# ------------------------------------------------------------------------------------------------- t_clhd_draw
CASES = [(0, 174), (3, 5), (-7, -4), (0, 0), (40, 2)]


def _draw_problems(rig, g, art, key, *, cases=CASES, extra_h=(0, 1)):
    out = []
    dw, dh = SL.strip_synth_dims(138, 28, g, 16)
    for dx, dy in cases:
        for eh in extra_h:
            h = dh + eh
            bw = max(1, dw + abs(dx) - (12 if dx == 40 else -6))
            bh = max(1, dh + abs(dy) + (2 if dy != 174 else 2) - (5 if dx == 40 else 0))
            if dy == 174:
                bh = dy + h - 3
            noise = rig.setup(g, art, bw=bw, bh=bh, key=key, seed=g * 31 + dx)
            rig.call(H.VA["t_clhd_draw"], (DBUF, dx, dy, g, 16, HEADER, h), 0x1C)
            want = bytearray(noise)
            SL.commlink_header_synth(want, bw, bw, bh, art, key, dx, dy, g, 16, g, h=h)
            if rig.plane(bw, bh) != bytes(want):
                out.append((g, dx, dy, h))
    return out


@pytest.mark.parametrize("g", list(range(17, 41)) + [48, 60])
def test_draw_is_commlink_header_synth_real_art(rig, real_art, g):
    assert _draw_problems(rig, g, *real_art) == []


@pytest.mark.parametrize("art", sorted(ARTS))
def test_draw_is_commlink_header_synth_synthetic(rig, art):
    for g in (17, 19, 22, 25, 30, 40):
        assert _draw_problems(rig, g, ARTS[art], KEY, cases=CASES[:3]) == []


@pytest.mark.parametrize("why", ["g16", "period1", "den0", "num0", "no_texels", "pitch0", "w137", "h27", "no_plane",
                                 "stride0", "h0", "h257", "empty_cut"])
def test_draw_refusals_leave_the_dest(rig, real_art, why):
    art, key = real_art
    g, args = 22, [DBUF, 2, 3, 22, 16, HEADER, 39]
    kw = {}
    if why == "g16":
        g = 16
    elif why == "period1":
        kw["period"] = 1
    elif why == "den0":
        args[4] = 0
    elif why == "num0":
        args[3] = 0
    elif why == "no_texels":
        kw["data"] = False
    elif why == "no_plane":
        kw["ddata"] = False
    elif why == "h0":
        args[6] = 0
    elif why == "h257":
        args[6] = 257
    elif why == "empty_cut":
        args[1] = 400
    if why == "w137":
        art = [r[:137] for r in art]
    if why == "h27":
        art = art[:27]
    noise = rig.setup(g, art, bw=200, bh=48, key=key, **kw)
    if why == "pitch0":
        rig.w32(HEADER + 0xC, 0)
    if why == "stride0":
        rig.w32(DBUF + 0x4A8, 0)
    rig.call(H.VA["t_clhd_draw"], tuple(args), 0x1C)
    assert rig.plane(200, 48) == noise


# ------------------------------------------------------------------------------------------------- t_clmp_pre / _col
@pytest.mark.parametrize("case", ["title", "narrow", "dx7", "g16"] + [f"rail{g}" for g in range(17, 61)])
def test_pre_gate_sets_the_rail_mode(rig, case):
    """t_clmp_pre (entered by t_clmp_synth's call, before its pushes: [esp+4] the synth's return, +8.. the 6 args):
    a 138-wide strip at dx 0 that is not the 6-row title -> g_mc_w = hm_sc(138), the column map, g_mc_on = 2;
    anything else leaves both cells alone."""
    g = 16 if case == "g16" else int(case[4:]) if case.startswith("rail") else 25
    rig.setup(g, [[0] * 138] * 18, bw=8, bh=8)
    spr = 0x00700400
    w, h = {"narrow": (139, 18), "title": (138, 6)}.get(case, (138, 18))
    rig.w32(spr + 0x10, w)
    rig.w32(spr + 0x14, h)
    rig.w32(H.MC_ON, 0)
    rig.w32(H.MC_W, 0x5A5A)
    dx = 7 if case == "dx7" else 0
    rig.uc.mem_write(STACK - 4, struct.pack("<I", 0x12345678))
    sp = STACK - 4
    rig.uc.mem_write(STACK, struct.pack("<6I", DBUF, dx, 3, g, 16, spr))
    rig.uc.mem_write(sp - 4, struct.pack("<I", MARKER))
    rig.uc.reg_write(X.UC_X86_REG_ESP, sp - 4)
    for r, v in REGS.items():
        rig.uc.reg_write(r, v)
    rig.uc.emu_start(H.VA["t_clmp_pre"], MARKER, count=1_000_000)
    assert rig.uc.reg_read(X.UC_X86_REG_ESP) == sp
    for r, v in REGS.items():
        assert rig.uc.reg_read(r) == v
    if case.startswith("rail"):
        assert rig.r32(H.MC_ON) == 2 and rig.r32(H.MC_W) == SL.commlink_strip_width(g)
        assert list(rig.uc.mem_read(H.VA["g_clhd_cmap"], SL.commlink_strip_width(g))) == SL.commlink_strip_cols(g)
    else:
        assert rig.r32(H.MC_ON) == 0 and rig.r32(H.MC_W) == 0x5A5A


def test_col_lookup_and_tail(rig):
    """t_clmp_col: mode 2 -> g_clhd_cmap[x - dx] (edx = x, [ebp+0xC] = dx); any other mode -> t_mc_col with the
    stack untouched (a stub there answers 0x1234)."""
    rig.uc.mem_write(H.T_MC_COL, bytes.fromhex("B834120000C3"))           # mov eax, 0x1234 ; ret
    rig.uc.mem_write(H.VA["g_clhd_cmap"], bytes(range(200)))
    frame = STACK - 0x100
    for mode, x, want in ((2, 37, 30), (0, 37, 0x1234), (1, 37, 0x1234)):
        rig.w32(H.MC_ON, mode)
        rig.w32(frame + 0xC, 7)
        rig.uc.mem_write(STACK, struct.pack("<I", MARKER))
        rig.uc.reg_write(X.UC_X86_REG_ESP, STACK)
        rig.uc.reg_write(X.UC_X86_REG_EBP, frame)
        rig.uc.reg_write(X.UC_X86_REG_EDX, x)
        rig.uc.emu_start(H.VA["t_clmp_col"], MARKER, count=10_000)
        assert rig.uc.reg_read(X.UC_X86_REG_EAX) == want and rig.uc.reg_read(X.UC_X86_REG_EDX) == x
        assert rig.uc.reg_read(X.UC_X86_REG_ESP) == STACK + 4
    rig.w32(H.MC_ON, 0)


# ------------------------------------------------------------------------------------------------- t_clmp_post
SON = H.SON


@pytest.mark.parametrize("case", ["header", "other_sprite", "h_unset", "g16"])
def test_post_gate(rig, real_art, case):
    """t_clmp_post is entered by `push t_clmp_post / ret` from t_clmp_synth with the caller's return address and the
    6 synth args on the stack: son cleared always; the post-pass only for the header, g > 16 and g_clmp_h > 0."""
    art, key = real_art
    g = 16 if case == "g16" else int(case[4:]) if case.startswith("rail") else 25
    dw, dh = SL.strip_synth_dims(138, 28, g, 16)
    noise = rig.setup(g, art, bw=dw + 4, bh=dh + 4, key=key)
    rig.w32(SON, 1)
    rig.w32(H.VA["g_clmp_h"], -1 if case == "h_unset" else dh)
    spr = 0x00700400 if case == "other_sprite" else HEADER
    rig.w32(H.MC_ON, 2)
    rig.call(H.VA["t_clmp_post"], (DBUF, 1, 2, g, 16, spr), 0x18)
    assert rig.r32(SON) == 0 and rig.r32(H.MC_ON) == 0
    want = bytearray(noise)
    if case == "header":
        SL.commlink_header_synth(want, dw + 4, dw + 4, dh + 4, art, key, 1, 2, g, 16, g, h=dh)
    assert rig.plane(dw + 4, dh + 4) == bytes(want)


def test_mutants_are_killed(real_art):
    """The sweep catches the even-row-on-top choice flipped and the mate test dropped (a fresh Uc per mutant: Unicorn
    keeps a stale translation of code it already ran)."""
    va, live = LIVE["t_clhd_draw"]
    muts = {"top parity": (b"\x0F\x9D\xC0", b"\x0F\x9C\xC0"),            # setge al -> setl al
            "mate": (b"\x81\xFA\xFF\xFF\x00\x00\x74", b"\x81\xFA\xFF\xFF\x00\x00\xEB")}    # je put -> jmp put
    for name, (old, new) in muts.items():
        assert live.count(old) == 1, name
        r = Rig()
        r.uc.mem_write(va, live.replace(old, new))
        assert any(_draw_problems(r, g, *real_art, cases=CASES[:1], extra_h=(0,)) for g in (22, 40)), name
