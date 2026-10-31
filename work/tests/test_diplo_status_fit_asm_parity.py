"""Unicorn parity: t_dp_status_fit + t_dp_status_tail (assemble_diplo.py) == scaling_laws.diplo_status_font_size.

The shipped bytes (resolved from patches.yaml, and identical to the assembler's) run at their real cave VAs.
Every engine callee is a Python stub at its real VA with its real calling convention:
  crt_strlen 0x6453E0 (cdecl), Font_init 0x618F40 (thiscall RET 0xC: records the size, sets the HFONT +8),
  Buffer_set_font 0x5DAC70 (thiscall RET 0x10: +0x52C <- f0 only when f0->+8 != 0),
  Buffer_find_line_break_l 0x5DC410 (thiscall RET 0xC, Font_find_line_break_l's semantics: fits -> 0 and
    *budget = remaining; a break -> ptr and *budget = 0; ONE unbreakable word that overflows -> 0 and *budget = 0,
    0x619505 -- indistinguishable from a fit by the return value),
  Buffer_wrap_3 0x5DD730 (thiscall RET 0x10: greedy word wrap in the canvas font at w; returns y + lines x the
    font's line advance read from its real Font fields: [f] >= 0 ? [f+0x10]+[f] : [f+0xC], 0x5DD8B8).
Font_init's stub writes the fields the engine's does (+0 = -1, +0xC = cell, +0x10 = glyph height) with a
non-linear cell(size), so a fit font's advance differs from +0xA44's.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
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
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_diplo as AD  # noqa: E402

from test_scaling_diplo_status import GDI, STATUS, standin_width  # noqa: E402

LAYOUT, _END = AD.assemble_all()
CANVAS = AD.MW_CANVAS
STR_VA = 0x05000100
STACK = 0x00300000
SP0 = STACK + 0x8000
RET_SITE = 0x43FE0C
FACE_PTR = 0x00691BD4
STRLEN, FONT_INIT, SET_FONT, FIND_BREAK, WRAP_3 = AD.CRT_STRLEN, AD.FONT_INIT, AD.SET_FONT, AD.FIND_BREAK, AD.WRAP_3
REGS = {"ebx": UC_X86_REG_EBX, "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP}
SENTINEL = {"ebx": 0x11111111, "esi": 0x22222222, "edi": 0x33333333, "ebp": 0x44444444}

MEASURES = [pytest.param(standin_width, id="standin")]
NOSPACE = "DIPLOMATICSTATUS:NONE"      # one unbreakable word: the 0x619505 overflow path must still shrink


def cell(size):
    """stand-in GDI cell height (tmHeight): sub-linear in size, like the real metric"""
    return size + (size + 4) // 7 + 1
if GDI is not None:
    MEASURES.insert(0, pytest.param(GDI, id="gdi"))


def _shipped(name):
    import apply_patches as ap
    doc = ap._yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == name:
                base = cave["virtual_addr"]
                base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]
                off = int(off, 16) if isinstance(off, str) else off
                return base + off, ap.ByteTemplate(str(c["bytes"])).resolve(base + off, symtab)
    raise AssertionError(f"{name} not in patches.yaml")


@pytest.mark.parametrize("name", ["t_dp_status_fit", "t_dp_status_tail"])
def test_shipped_bytes_are_the_assemblers(name):
    va, blob = _shipped(name)
    off, mine = LAYOUT[name]
    assert va == AD.PCAVE2_VA + off and blob == mine


def test_status_site_is_redirected_to_the_fit():
    import apply_patches as ap
    doc = ap._yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    s = next(s for s in doc["sites"] if s["id"] == "DiploTalkWin_draw_status_panels.status_wrap")
    assert s["new_bytes"].split("#")[0].strip() == "E8 {rel32:t_dp_status_fit}"
    i = next(s for s in doc["sites"] if s["id"] == "DiploTalkWin_draw_status_panels.infil_wrap")
    assert i["new_bytes"].strip() == "E8 {rel32:t_dp_txt_wrap3}"      # the INFILTRATION line is untouched


class World:
    def __init__(self, g, text, measure, panel=None, logow=None):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc, self.g, self.text, self.measure = uc, g, text, measure
        for base, size in ((0x668000, 0x1000), (0x691000, 0x1000), (0x733000, 0x2000), (0x7AE000, 0x1000),
                           (0xA1D000, 0x1000), (0xA33000, 0x1000), (0xA3C000, 0x1000), (STACK, 0x10000), (0x05000000, 0x1000),
                           (0x5DA000, 0x4000), (0x618000, 0x1000), (0x645000, 0x1000)):
            uc.mem_map(base, size)
        for name, (off, blob) in LAYOUT.items():
            if name in ("t_dp_status_fit", "t_dp_status_tail"):
                uc.mem_write(AD.PCAVE2_VA + off, blob)
        self.w32(AD.G, g)
        self.w32(AD.HUD_FONT_NAME, FACE_PTR)
        uc.mem_write(FACE_PTR, b"Arial\0")
        uc.mem_write(STR_VA, text.encode() + b"\0")
        # the painter's own +0xA44 (Font_init'd by t_fontinit at fl(12g/16)), already on the canvas
        self.sizes = {AD.STATUS_FONT: SL.dp(12, g)}
        self.font_fields(AD.STATUS_FONT, SL.dp(12, g))
        self.w32(AD.STATUS_FONT + 8, 0xF0A44)
        self.canvas_font = AD.STATUS_FONT
        pL, pR = panel or SL.diplo_status_panel0(g)
        self.w32(AD.CELL_VA["g_dp_panel"], pL)
        self.w32(AD.CELL_VA["g_dp_panel"] + 8, pR)
        self.w32(AD.CELL_VA["g_dp_logow"], SL.dp(65, g) if logow is None else logow)
        self.inits, self.wraps, self.sets = [], [], []
        self.passive = False
        for a in (STRLEN, FONT_INIT, SET_FONT, FIND_BREAK, WRAP_3, RET_SITE):
            if not (0x5DA000 <= a < 0x5DE000 or 0x618000 <= a < 0x619000 or 0x645000 <= a < 0x646000):
                try:
                    uc.mem_map(a & ~0xFFF, 0x1000)
                except Exception:  # noqa: BLE001
                    pass
            uc.mem_write(a, b"\xf4")
        uc.hook_add(UC_HOOK_CODE, self._hook)

    def font_fields(self, f, size):
        self.w32(f, -1)
        self.w32(f + 0xC, cell(size))
        self.w32(f + 0x10, size)

    def lh(self, f):
        lead = self.r32(f)
        lead = lead - (1 << 32) if lead & 0x80000000 else lead
        return self.r32(f + 0x10) + lead if lead >= 0 else self.r32(f + 0xC)

    def lines(self, size, s, w):
        n, cur = 1, ""
        for word in s.split(" "):
            cand = word if not cur else cur + " " + word
            if cur and self.measure(size, cand) > w:
                n, cur = n + 1, word
            else:
                cur = cand
        return n

    def w32(self, a, v):
        self.uc.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, a):
        return int.from_bytes(self.uc.mem_read(a, 4), "little")

    def _ret(self, nargs_clean, eax):
        uc = self.uc
        sp = uc.reg_read(UC_X86_REG_ESP)
        ra = self.r32(sp)
        uc.reg_write(UC_X86_REG_ESP, sp + 4 + 4 * nargs_clean)
        uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        for r in (UC_X86_REG_ECX, UC_X86_REG_EDX):           # callee may clobber the volatiles
            uc.reg_write(r, 0xDEADBEEF)
        uc.reg_write(UC_X86_REG_EIP, ra)

    def _str(self, a):
        return bytes(self.uc.mem_read(a, 256)).split(b"\0")[0].decode()

    def _hook(self, uc, addr, size, ud):
        if self.passive:
            return
        sp = uc.reg_read(UC_X86_REG_ESP)
        arg = lambda i: self.r32(sp + 4 + 4 * i)  # noqa: E731
        ecx = uc.reg_read(UC_X86_REG_ECX)
        if addr == STRLEN:
            self._ret(0, len(self._str(arg(0))))
        elif addr == FONT_INIT:
            assert self._str(arg(0)) == "Arial" and arg(2) == 0, "face/style must stay vanilla's (Arial, regular)"
            self.inits.append((ecx, arg(1)))
            self.sizes[ecx] = arg(1)
            self.font_fields(ecx, arg(1))
            self.w32(ecx + 8, 0xF0000 | arg(1))
            self._ret(3, 0)
        elif addr == SET_FONT:
            assert ecx == CANVAS and arg(1) == arg(2) == arg(3) == 0
            if self.r32(arg(0) + 8):
                self.canvas_font = arg(0)
            self.sets.append(arg(0))
            self._ret(4, 0)
        elif addr == FIND_BREAK:
            assert ecx == CANVAS
            s, pb, n = self._str(arg(0)), arg(1), arg(2)
            assert n == len(s) == len(self.text)
            budget = self.r32(pb)
            wd = self.measure(self.sizes[self.canvas_font], s)
            if wd <= budget:
                self.w32(pb, budget - wd)
                self._ret(3, 0)
            else:
                self.w32(pb, 0)
                self._ret(3, 0 if " " not in s else arg(0) + 10)
        elif addr == WRAP_3:
            assert ecx == CANVAS
            size, s = self.sizes[self.canvas_font], self._str(arg(0))
            self.wraps.append((size, self.canvas_font, s, arg(1), arg(2), arg(3)))
            self._ret(4, arg(2) + self.lines(size, s, arg(3)) * self.lh(self.canvas_font))
        elif addr == RET_SITE:
            uc.emu_stop()

    def run(self, x_in=777, y=300, w_in=55):
        uc = self.uc
        sp = SP0 - 0x14
        for i, v in enumerate((RET_SITE, STR_VA, x_in, y, w_in)):
            self.w32(sp + 4 * i, v)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_ECX, CANVAS)
        for k, v in SENTINEL.items():
            uc.reg_write(REGS[k], v)
        self.sp_in = sp
        uc.emu_start(AD.PCAVE2_VA + LAYOUT["t_dp_status_fit"][0], 0, count=200_000)
        assert uc.reg_read(UC_X86_REG_EIP) == RET_SITE, f"stopped at {uc.reg_read(UC_X86_REG_EIP):#x}"
        return self


@pytest.mark.parametrize("measure", MEASURES)
@pytest.mark.parametrize("text", STATUS + [NOSPACE])
@pytest.mark.parametrize("g", [17, 20, 22, 24, 25, 30, 32, 36, 40, 44, 48, 52, 56, 64])
def test_fit_matches_the_law(g, text, measure):
    W = World(g, text, measure).run()
    x, w = SL.diplo_status_wrap(g)
    want = SL.diplo_status_font_size(g, lambda s: measure(s, text), w)
    assert len(W.wraps) == 1
    size, font, s, wx, wy, ww = W.wraps[0]
    assert (s, wx, wy, ww) == (text, x, 300, w)                    # x/w exactly as t_dp_txt_wrap3
    assert size == want, f"g={g} {text!r}: drew at {size}, law {want}"
    assert font == (AD.STATUS_FONT if want == SL.dp(12, g) else AD.FITFONT)
    assert W.canvas_font == AD.STATUS_FONT                         # +0xA44 back for INFILTRATION / Energy / Might
    for k, v in SENTINEL.items():
        assert W.uc.reg_read(REGS[k]) == v, f"{k} clobbered"
    assert W.uc.reg_read(UC_X86_REG_ESP) == W.sp_in + 4 + 0x10     # RET 0x10, like Buffer_wrap_3
    # the y handed to INFILTRATION / Energy / Might == the no-fit layout: one +0xA44 line when vanilla shows one
    # line (the fit), wrap_3's own A44 result when vanilla wraps (no fit)
    lh_a44 = W.lh(AD.STATUS_FONT)
    lines = W.lines(size, text, w)
    y_wrap = 300 + lines * W.lh(font)
    assert W.uc.reg_read(UC_X86_REG_EAX) == SL.diplo_status_next_y(y_wrap, lh_a44, W.lh(font))
    if measure(12, text) <= SL.DIPLO_STATUS_NATIVE_W and (size > SL.DIPLO_STATUS_FONT_MIN or measure(size, text) <= w):
        assert lines == 1
        assert W.uc.reg_read(UC_X86_REG_EAX) == 300 + lh_a44
    elif font == AD.STATUS_FONT:
        assert W.uc.reg_read(UC_X86_REG_EAX) == y_wrap
    for font, sz in W.inits:
        assert font in (AD.NATFONT, AD.FITFONT)
        if font == AD.NATFONT:
            assert sz == 12


def test_native_slot_is_built_once_and_fit_slot_keyed_on_size():
    meas = GDI or standin_width
    W = World(40, STATUS[0], meas)
    W.run()
    first = list(W.inits)
    W.inits.clear()
    W.wraps.clear()
    W.run()                                                         # a repaint at the same g
    assert sum(1 for f, _ in first if f == AD.NATFONT) == 1
    assert not [i for i in W.inits if i[0] == AD.NATFONT]           # native slot: once per process
    want = SL.diplo_status_font_size(40, lambda s: meas(s, STATUS[0]), SL.diplo_status_wrap(40)[1])
    if want < 30:
        # the loop walks 29.. down from the cached size: the final size is cached, so the repaint re-inits
        # only the intermediate steps (none when the first step fits)
        assert all(sz > want for _, sz in W.inits)
    assert W.wraps[0][0] == want


@pytest.mark.parametrize("g", [8, 12, 16])
def test_low_res_is_wrap3_verbatim(g):
    W = World(g, STATUS[0], standin_width)
    W.passive = True
    uc = W.uc
    sp = SP0 - 0x14
    for i, v in enumerate((RET_SITE, STR_VA, 777, 300, 55)):
        W.w32(sp + 4 * i, v)
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_ECX, CANVAS)
    stopped = []

    def at_wrap(uc_, addr, size, ud):
        if addr == WRAP_3:
            stopped.append(uc_.reg_read(UC_X86_REG_ESP))
            uc_.emu_stop()
    uc.hook_add(UC_HOOK_CODE, at_wrap)
    uc.emu_start(AD.PCAVE2_VA + LAYOUT["t_dp_status_fit"][0], 0, count=1000)
    assert stopped == [sp]                                           # tail-jumped, frame untouched
    assert [W.r32(sp + 4 * i) for i in range(5)] == [RET_SITE, STR_VA, 777, 300, 55]
    assert uc.reg_read(UC_X86_REG_ECX) == CANVAS
    assert not W.inits and not W.sets


def superlinear_width(size, text):
    """a measure whose glyphs grow faster than the size (so a vanilla-fitting word overflows at scale)"""
    return standin_width(size, text) * (64 + size - 12) // 64


@pytest.mark.parametrize("measure", ([pytest.param(GDI, id="gdi")] if GDI is not None else [])
                         + [pytest.param(superlinear_width, id="superlinear")])
def test_unbreakable_word_overflow_still_shrinks(measure):
    """Font_find_line_break_l returns 0 for one overflowing word (0x619505); the fit must still see the overflow.
    Pick the g values where the law shrinks the no-space string and check the thunk draws at the law's size."""
    hits = 0
    import itertools
    cands = [NOSPACE + "".join(x) for k in range(4) for x in itertools.product("I.:!E", repeat=k)]
    cands += ["E" * a + "I" * b for a in range(40) for b in range(6)]
    cands = [s for s in cands if measure(12, s) <= SL.DIPLO_STATUS_NATIVE_W]     # vanilla: one line

    def shrinks(word):
        return sum(SL.diplo_status_font_size(g, lambda s: measure(s, word), SL.diplo_status_wrap(g)[1]) < SL.dp(12, g)
                   for g in range(17, 65))
    for word in sorted(cands, key=shrinks, reverse=True)[:2]:
        for g in range(17, 65):
            w = SL.diplo_status_wrap(g)[1]
            want = SL.diplo_status_font_size(g, lambda s: measure(s, word), w)
            if want < SL.dp(12, g):
                hits += 1
                assert World(g, word, measure).run().wraps[0][0] == want, (g, word)
    assert hits, "no g overflows the no-space string -- the test proves nothing"


def test_fit_y_matches_the_audited_4k_case():
    """Audit 2026-10-11: g=40 NONE drew at 29 and handed the next lines y + lh(29) (2 px up). Now y + lh(30)."""
    meas = GDI or standin_width
    W = World(40, STATUS[0], meas).run(y=500)
    assert W.wraps[0][1] == AD.FITFONT
    assert W.uc.reg_read(UC_X86_REG_EAX) == 500 + cell(30)
