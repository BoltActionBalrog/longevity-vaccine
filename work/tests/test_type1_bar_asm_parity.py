"""W9B asm parity (assemble_type1_rowcum.py :: t1c_bar): the type-1 checkbox-list bars striped from each bar's OWN top
(user decision 2026-10-27, "make every row identical") -- Unicorn on the patches.yaml bytes at their real cave VAs (t1c_bar
with the real t1c_pn / t1c_barh under it; t_rowbox_solid, the deployed draw it wraps, a stub that records what it is
handed, trims the fn's local rect R / B - 1 as the real one leaves it, and paints the canvas with a random mix of every
index the list shows), against scaling_laws.py: type1_bar_gate / type1_bar_restripe / type1_bar_colour.

Each g in 16..64: every state's set (0x78D960 / 0x78D988 / 0x78D9B0), the gate's every arm (g, the popup's list kind
0 / 1 / 2, the marked Dialog identity and each field one off it), rects inside, across and outside the Buffer's clip
and canvas (negative top, a bottom-up Buffer h < 0, an empty Buffer), and checks: the WHOLE canvas == the law applied
to what the deployed draw left; the deployed draw entered once with the caller's ecx / ebp / args and, off the gate,
from the caller's own stack (a tail jump: same esp, same return address); ebx / esi / edi / ebp kept, RET 8; nothing
written but the canvas and the stack.  The wiring: the site bytes, the yaml bytes == the assembler's, the pristine
call.  Pure Unicorn on a few hundred bytes: no bake, no boot (~17 s serial over 155 items, 0.3 s per g).
"""
from __future__ import annotations

import pathlib
import random
import struct
import sys
from functools import lru_cache

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_patches as ap  # noqa: E402
import assemble_type1_rowcum as A  # noqa: E402
import scaling_laws as SL  # noqa: E402

YAML = ROOT / "patches" / "patches.yaml"
GS = range(16, 65)
P = SL.TYPE1_POPUP_ROW_PRESET
SETS = SL.FACTION_ROW_BOX_SETS                       # 0x78D960 / 0x78D988 / 0x78D9B0: states 0 / 1 / 2
STACK, SP0 = 0x00300000, 0x00308000
EBP0 = 0x00307000                                    # FUN_00405b20's frame: [ebp-4] = the popup
POPUP = 0x00530000
DATA = POPUP + 0x2800                                # the CheckList's Dialog data (popup + [[popup+0x21D0]+8] + 0x21D0)
VT = POPUP + 0x2000
BUF = 0x00540000                                     # the list Buffer (ecx at the site)
PIX = 0x00600000                                     # its pixels
RECT = EBP0 - 0x14                                   # the fn's local rect
RET_SITE = 0x00401000
STRIDE, W, H = 96, 90, 120
INKS = (0xAE, 0xEE, 0xE0, 0xE1, 0xC6, 0x41, 0x00, 0xFF, 0x13)
REGS0 = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: EBP0,
         UC_X86_REG_EDX: 0x5555, UC_X86_REG_EAX: 0x6666}


@lru_cache(maxsize=1)
def _yaml():
    sites, _g, caves, syms = ap.load_patches(YAML)
    st = dict(ap.build_symbol_table(syms, caves))
    ents = {c["id"]: c for cave in caves for c in cave.get("contents") or []}
    return sites, st, ents


def _bytes(name: str) -> bytes:
    _s, st, ents = _yaml()
    return bytes(ap.ByteTemplate(ents[name]["bytes"]).resolve(st[name], st))


class Rig:
    def __init__(self, g: int):
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((0x00400000, 0x2000), (0x00668000, 0x1000), (A.PCAVE2 + 0x3D000, 0x1000),
                           (A.PCAVE2 + 0x3F000, 0x1000), (STACK, 0x10000), (POPUP, 0x3000), (BUF, 0x1000),
                           (PIX, 0x10000)):
            uc.mem_map(base, size)
        uc.mem_write(RET_SITE, b"\xF4")
        uc.mem_write(A.G, struct.pack("<i", g))
        for name in ("t1c_pn", "t1c_barh", "t1c_bar"):
            uc.mem_write(_yaml()[1][name], _bytes(name))
        self.g, self.writes, self.calls, self.paint = g, [], [], None
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size, val, _: self.writes.append((addr, size)))
        uc.hook_add(UC_HOOK_CODE, self._solid, begin=A.T_ROWBOX_SOLID, end=A.T_ROWBOX_SOLID)

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def _solid(self, u, addr, size, _):
        """The deployed draw: record, trim the local rect R / B - 1, paint the canvas (self.paint), RET 8."""
        esp = u.reg_read(UC_X86_REG_ESP)
        a1, a2 = self.r32(esp + 4) & 0xFFFFFFFF, self.r32(esp + 8) & 0xFFFFFFFF
        self.calls.append(dict(esp=esp, ret=self.r32(esp) & 0xFFFFFFFF, ecx=u.reg_read(UC_X86_REG_ECX),
                               ebp=u.reg_read(UC_X86_REG_EBP), a1=a1, a2=a2))
        r = struct.unpack("<4i", bytes(u.mem_read(a1, 16)))
        u.mem_write(a1, struct.pack("<4i", r[0], r[1], r[2] - 1, r[3] - 1))
        if self.paint is not None:
            u.mem_write(PIX, self.paint)
        u.reg_write(UC_X86_REG_ESP, esp + 12)
        u.reg_write(UC_X86_REG_EIP, self.r32(esp) & 0xFFFFFFFF)

    def setup(self, kind: int, f: dict, rect, clip, h=H, data=PIX):
        self.calls.clear()
        self.w32(EBP0 - 4, POPUP)
        self.w32(POPUP + 0x2350, kind)
        self.w32(POPUP + 0x21D0, VT)
        self.w32(VT + 8, DATA - 0x21D0 - POPUP)
        for off, k in ((0x58, "rows"), (0x48, "preset"), (0x44, "gap"), (0x68, "row_h"), (0x60, "list_h")):
            self.w32(DATA + off, f[k])
        for i, v in enumerate(clip):
            self.w32(BUF + 0x20 + 4 * i, v)
        self.w32(BUF + 0x54, data)
        self.w32(BUF + 0x80, W)
        self.w32(BUF + 0x84, h)
        self.w32(BUF + 0x4A8, STRIDE)
        for i, v in enumerate(rect):
            self.w32(RECT + 4 * i, v)

    def run(self, set_va: int):
        uc = self.uc
        self.w32(SP0, RET_SITE)
        self.w32(SP0 + 4, RECT)
        self.w32(SP0 + 8, set_va)
        for r, v in {**REGS0, UC_X86_REG_ECX: BUF}.items():
            uc.reg_write(r, v & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, SP0)
        self.writes.clear()
        uc.emu_start(A.T1C_BAR, RET_SITE, count=2_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == RET_SITE
        return uc

    def canvas(self):
        b = bytes(self.uc.mem_read(PIX, STRIDE * H))
        return [list(b[y * STRIDE:y * STRIDE + W]) for y in range(H)]


_RIGS: dict = {}


def _rig(g: int) -> Rig:
    if g not in _RIGS:
        _RIGS[g] = Rig(g)
    return _RIGS[g]


def marked(g, **kw):
    f = dict(rows=19, preset=P, gap=(3 * g) >> 4, row_h=SL.type1_row_h(P, g), list_h=SL.type1_row_cell(19, P, g))
    f.update(kw)
    return f


def paint(rng) -> bytes:
    return bytes(rng.choice(INKS) for _ in range(STRIDE * H))


def as_rows(blob: bytes):
    return [list(blob[y * STRIDE:y * STRIDE + W]) for y in range(H)]


CASES = (  # (rect half-open as the CheckList hands it, clip)
    ((10, 5, 80, 31), (0, 0, W, H)),
    ((10, 33, 80, 59), (0, 0, W, H)),
    ((4, 61, 88, 109), (0, 0, W, H)),
    ((10, -7, 80, 20), (0, 0, W, H)),            # a top above the canvas
    ((-5, 100, 95, 140), (0, 0, W, H)),          # past the canvas right / bottom
    ((10, 20, 80, 70), (12, 30, 70, 55)),        # cut by the clip on every side
    ((10, 20, 80, 70), (0, 0, 200, 300)),        # a clip larger than the canvas
    ((10, 50, 80, 51), (0, 0, W, H)),            # one row (the trim leaves an empty extent: b + 1 == t + 1)
)


@pytest.mark.parametrize("g", GS)
def test_bar_is_the_law(g):
    rig = _rig(g)
    rng = random.Random(g)
    pn = SL.type1_row_pitch(P, g) if g > SL.NATIVE_G else 0
    for rect, clip in CASES:
        for set_va in SETS:
            for kind in (1, 0, 2):
                rig.paint = paint(rng)
                rig.setup(kind, marked(g), rect, clip)
                uc = rig.run(set_va)
                gate = SL.type1_bar_gate(g, kind, pn)
                assert len(rig.calls) == 1, (g, rect, kind)
                c = rig.calls[0]
                assert c["ecx"] == BUF and c["ebp"] == EBP0 and c["a1"] == RECT and c["a2"] == set_va
                if gate:
                    assert c["ret"] != RET_SITE and c["esp"] < SP0
                    l, t, r, b = (rig.r32(RECT + 4 * i) for i in range(4))
                    want = SL.type1_bar_restripe(as_rows(rig.paint), (l, t, r + 1, b + 1), set_va, g, clip)
                else:                                     # a tail jump: the caller's own frame
                    assert c["ret"] == RET_SITE and c["esp"] == SP0
                    want = as_rows(rig.paint)
                assert rig.canvas() == want, (g, rect, clip, hex(set_va), kind)
                assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 12
                for reg in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
                    assert uc.reg_read(reg) == REGS0[reg] & 0xFFFFFFFF, (g, reg)
                bad = [(hex(a), n) for a, n in rig.writes
                       if not (PIX <= a < PIX + STRIDE * H or SP0 - 0x40 <= a < SP0)]
                assert not bad, (g, bad[:4])


@pytest.mark.parametrize("g", (16, 17, 22, 25, 40, 64))
def test_gate_arms(g):
    """Every marker field one off the identity (and the PrefWin / editor shape, preset -1): the deployed draw only,
    from the caller's frame, the canvas untouched; the bottom-up Buffer (h < 0) and an empty Buffer (no pixels)."""
    rig = _rig(g)
    rng = random.Random(1000 + g)
    base = marked(g)
    offs = [dict(rows=1), dict(preset=-1, gap=6, row_h=50, list_h=339), dict(gap=base["gap"] + 1),
            dict(row_h=base["row_h"] + 1), dict(list_h=base["list_h"] - 1), dict(preset=0x100)]
    for kw in offs:
        rig.paint = paint(rng)
        rig.setup(1, marked(g, **kw), CASES[0][0], CASES[0][1])
        rig.run(SETS[0])
        assert rig.calls[0]["esp"] == SP0 and rig.canvas() == as_rows(rig.paint), (g, kw)
    rig.paint = paint(rng)
    rig.setup(1, base, CASES[2][0], CASES[2][1], h=-H)
    rig.run(SETS[2])
    pn = SL.type1_row_pitch(P, g) if g > SL.NATIVE_G else 0
    want = (SL.type1_bar_restripe(as_rows(rig.paint), (4, 61, 88, 109), SETS[2], g) if SL.type1_bar_gate(g, 1, pn)
            else as_rows(rig.paint))
    assert rig.canvas() == want
    rig.paint = None
    rig.setup(1, base, CASES[0][0], CASES[0][1], data=0)
    rig.run(SETS[0])
    assert not [a for a, _n in rig.writes if not SP0 - 0x40 <= a < SP0]


# ================================================================ the law itself
@pytest.mark.parametrize("g", range(16, 65))
def test_law_every_bar_identical(g):
    """Each bar's face depends only on (y - its top) and the state: identical rows; the top row is vanilla's opening
    member (EE; E0 checked), T rows a stripe; g <= 16 never gated (vanilla's draw)."""
    t = SL.stripe_rows(g)
    h = SL.type1_row_h(P, g) if g > 16 else P
    for s in SETS:
        o, m = SL.type1_bar_pair(s)
        faces = {tuple(SL.type1_bar_colour(top + k, top, s, g) for k in range(h))
                 for top, _b in SL.type1_row_layout(19, P, g)}
        assert len(faces) == 1
        face = faces.pop()
        k0 = SL.stroke_width(g) - t if s == SL.TYPE1_BAR_HOVER_SET else 0      # v2: the hover row from top + K - T
        assert all(face[k] == (o if ((k - k0) // t) % 2 == 0 else m) for k in range(h))
        assert face[0] == o or s == SL.TYPE1_BAR_HOVER_SET          # the hover top row is under the ring
    assert SL.type1_bar_pair(0x78D960) == (0xEE, 0xAE) and SL.type1_bar_pair(0x78D9B0) == (0xE0, 0xE1)
    assert not SL.type1_bar_gate(min(g, 16), 1, 22)


@pytest.mark.parametrize("g", range(17, 65))
def test_hover_interior_against_the_ring(g):
    """v2 (audit-w9B item 3): the hover row's interior (under the K-px ring) opens on a FULL T-row mate stripe flush
    against the ring, as vanilla's AE row right under its 1-px ring; every interior stripe T rows but the last (cut
    by the bar height); the plain / checked rows keep the top anchor (unchanged from v1); K == T: the hover face is
    the plain face."""
    t, k = SL.stripe_rows(g), SL.stroke_width(g)
    h = SL.type1_row_h(P, g)
    o, m = SL.type1_bar_pair(SL.TYPE1_BAR_HOVER_SET)
    inner = [SL.type1_bar_colour(y, 0, SL.TYPE1_BAR_HOVER_SET, g) for y in range(k, h - k)]
    runs, s0 = [], 0
    for i in range(1, len(inner) + 1):
        if i == len(inner) or inner[i] != inner[s0]:
            runs.append((inner[s0], i - s0))
            s0 = i
    assert runs[0] == (m, t), (g, runs[:3])
    assert all(n == t for _c, n in runs[:-1]) and 0 < runs[-1][1] <= t
    if k == t:
        assert [SL.type1_bar_colour(y, 0, SL.TYPE1_BAR_HOVER_SET, g) for y in range(h)] ==             [SL.type1_bar_colour(y, 0, 0x78D960, g) for y in range(h)]


def test_vanilla_face_g16():
    """g = 16 (the law's T = 1 face, never applied): vanilla's own 19-row bars, measured on the pristine render --
    EE AE EE ... EE (states 0 / 1), E0 E1 ... E0 (checked)."""
    assert [SL.type1_bar_colour(y, 0, 0x78D960, 16) for y in range(19)] == [0xEE, 0xAE] * 9 + [0xEE]
    assert [SL.type1_bar_colour(y, 0, 0x78D9B0, 16) for y in range(19)] == [0xE0, 0xE1] * 9 + [0xE0]


# ================================================================ wiring
def test_yaml_bytes_and_site():
    sites, st, _e = _yaml()
    va, blob, _t = A.build()["t1c_bar"]
    assert st["t1c_bar"] == va == A.T1C_BAR and _bytes("t1c_bar") == blob
    assert st["t_rowbox_solid"] == A.T_ROWBOX_SOLID
    assert A.T1C_BAR + len(blob) <= A.CODE_END
    (sid, (sva, orig, new)), = A.bar_site_bytes().items()
    s = next(x for x in sites if x["id"] == sid)
    assert s["virtual_addr"] == sva == 0x405BF6 and s["original_bytes"] == orig and s["new_bytes"] == new
    assert s["group"] == "popup_list_option_frame" and s["length"] == 5
