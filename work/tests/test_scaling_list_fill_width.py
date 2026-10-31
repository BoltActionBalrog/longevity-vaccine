"""The type-1 checkbox-list window (thunk_list_fill_width v3): w / [+0x5c] / [+0x64] = floor(VANILLA x g/16) EACH.

FUN_0060e800 (the type-1 attach) runs OptionList_calc_reserve 0x60ED10, then `call GraphicWin_init` @0x60e8a1 with
w = [+0x5c]; [+0x64] is the row-highlight bar.  v1/v2 wrote s(xs) to all three (4K Customize Game Rules 1650 where
vanilla x g/16 is fl(657 * 2.5) = 1642; a PrefWin page's bar 1142 where it is fl(451 * 2.5) = 1127; the scenario
editor's CheckList, whose rect the editor law already scaled, got s(s(371)) = 2317 in a 927-wide column).

The census of what the thunk serves (every caller of FUN_0060e800: the CheckList vtable adjustor 0x60FEE0, Dialog_set_
type 0x6129F4, the Dialog attach dispatch 0x61305D):
  * popup type-1 lists (Dialog flags 0, gap 3, #xs 440 x1.5 = 660 at W > 1023): Customize Game Rules (#RULES, 18),
    Announcements (#BASEWARNINGS, 17), Governor Settings (#GOVOPTIONS, 19), #SCENRULES (15);
  * the 7 PrefWin pages (CheckList_ctor 0x49227C.., Dialog_init_2: flags |= 3, xs 457, gap = Dialog default 6, fixed
    height -- the calc's fixed-height path that never meets thunk_rowgap);
  * the scenario-editor diplomacy modal's CheckList (CheckList_ctor 0x4DB8CE, Dialog_init_3 0x4DB452: flags |= 3,
    xs = R - L of the rect the editor immtab law already scaled, gap 6; parent = DiploEditWin, vtbl 0x66E964);
  * NetWin's CheckList (+0x4454) is constructed and cleared but never Dialog_init'd or attached (no consumer).

1. the law (scaling_laws.type1_list_fill_width / type1_list_widths / dialog_row_margin_native);
2. the shipped bytes are scripts/assemble_list_fill_width.py's, in their slot;
3. the REAL resolved bytes under Unicorn == the law for every field input, every g 16..40 (g <= 16: untouched);
4. FUN_0060e800 run WHOLE on the pristine .bak and on the real bake: g = 16 identical (GraphicWin_init args, the
   Dialog bytes) on 800/1024/1366-wide screens; g > 16 every field == the law whether the calc ran once or twice
   (dims dispatch first: thunk_rowgap has already scaled the gap), and each row's text fits its bar.
Skips (does not fail) if unicorn / keystone / pefile are absent.
"""
from __future__ import annotations

import ctypes
import struct
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc, UcError  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_list_fill_width as ASM  # noqa: E402

SW, SH, G = 0x9B7B1C, 0x9B7B20, 0x668740
GW_INIT = 0x5D4EF0
SITE, RESUME = 0x60E8A1, 0x60E8A6
GS = range(16, 41)

# ---- census inputs ------------------------------------------------------------------------------------------------
# Native max row-text widths: Arial Narrow 16 synthetic bold (arialn.ttf ONLY, the face the game registers -- see the
# scaling-text skill), of each popup's longest #itemlist line (xscript.txt).
POPUPS = {"#RULES": (18, 380, "No Unity Scattering: Supply Pods only at landing sites."),
          "#BASEWARNINGS": (17, 293, "Stop for items built by Governors/Queues."),
          "#GOVOPTIONS": (19, 572, "Governor may use multiple priorities (e.g. Explore AND Discover), or no priorities."),
          "#SCENRULES": (15, 327, "No native life--fungus, mind worms, Planet, etc.")}
POPUP_XS, POPUP_GAP = 660, 3                  # #xs 440 x1.5 (engine, W > 1023); the popup Dialog's struct-copy gap
CHECKBOX_INDENT = 27                          # [+0x34]: the checkbox sprite width the calc seeds
PREF_PAGES = (8, 12, 14, 8, 13, 4, 8)         # frida_quit_rows.log textelem count_cc
PREF_XS, PREF_GAP, PREF_H = 457, 6, 281       # Dialog_init_2 w (native: thunk_pref_dlg2 leaves it), Dialog default 6
EDITOR_ROWS, EDITOR_GAP = 13, 6


def editor_xs(g: int) -> int:
    """The editor diplomacy CheckList rect width (DiploEditWin_exec 0x4DB410..0x4DB43B on the immtab-scaled window):
    W = su(758); L = W/2 + su(4); R = 2*(W/2) - su(4); su = half_down (thunk_ed_immfix)."""
    su = (lambda v: v) if g <= 16 else (lambda v: (2 * v * g + 15) >> 5)
    w = su(758)
    return (2 * (w // 2) - su(4)) - (w // 2 + su(4))


# ==== 1. the law ===================================================================================================
def test_vanilla_widths_match_the_frida_ground_truth():
    """frida_rulesboxw.log (g=16 xs 660 -> d5c 657) and frida_quit_rows.log (PrefWin gap 6, w5c 457)."""
    assert SL.type1_list_widths(660, 0, 1, 3, False, 380, CHECKBOX_INDENT) == (657, 657, 657)
    assert SL.type1_list_widths(457, 0, 1, 6, True) == (457, 457, 451)
    assert SL.type1_list_widths(editor_xs(16), 0, 1, 6, True) == (371, 371, 365)


@pytest.mark.parametrize("tag", list(POPUPS))
def test_census_popups_are_xs_dominant_at_native(tag):
    """The thunk re-forms vanilla from xs alone; every popup it serves must take the xs arm of the calc's max."""
    rows, text, _s = POPUPS[tag]
    assert SL.type1_list_xs_dominant(POPUP_XS, 0, 1, POPUP_GAP, text, CHECKBOX_INDENT)
    assert SL.type1_list_widths(POPUP_XS, 0, 1, POPUP_GAP, False, text, CHECKBOX_INDENT) == \
        SL.type1_list_widths(POPUP_XS, 0, 1, POPUP_GAP, False)


@pytest.mark.parametrize("g", GS)
def test_law_is_vanilla_times_g_per_field(g):
    for gap_field, flags, fixed_h, xs, gap_n in ((SL.dialog_row_margin(3, g), 0, 0, 660, 3),
                                                 (6, 3, PREF_H, 457, 6)):
        got = SL.type1_list_fill_width(xs, 0, 1, gap_field, flags, fixed_h, 8, g)
        if g <= 16:
            assert got is None
            continue
        van = SL.type1_list_widths(xs, 0, 1, gap_n, bool(flags & 2))
        assert got == tuple(v * g // 16 for v in van), (g, xs, got, van)
    assert SL.type1_list_fill_width(660, 0, 1, 7, 0, 0, 1, g) is None          # one row: never touched


def test_law_4k_magnitudes():
    assert SL.type1_list_fill_width(660, 0, 1, 7, 0, 0, 18, 40) == (1642, 1642, 1642)
    assert SL.type1_list_fill_width(457, 0, 1, 6, 3, PREF_H, 8, 40) == (1142, 1142, 1127)
    assert SL.type1_list_fill_width(editor_xs(40), 0, 1, 6, 3, 300, 13, 40, owned=True) == (927, 927, 912)


@pytest.mark.parametrize("g", GS)
def test_native_gap_round_trip(g):
    """thunk_rowgap's map, read back: exact for every native a type-1 consumer carries, on and off its path."""
    assert SL.dialog_row_margin_native(SL.dialog_row_margin(3, g), g, True) == 3
    assert SL.dialog_row_margin_native(6, g, False) == 6                     # PrefWin / editor: fixed-height path
    assert SL.dialog_row_margin_native(SL.dialog_row_margin(3, g), g, False) == SL.dialog_row_margin(3, g)


# ==== 2. the shipped bytes ===========================================================================================
@lru_cache(maxsize=None)
def _live():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    for c in caves:
        for e in c.get("contents") or []:
            if e["id"] == "thunk_list_fill_width":
                va = int(c["virtual_addr"]) + int(e["offset"])
                t = " ".join(str(e["bytes"]).split())
                return sym, c, va, t, bytes(ap.ByteTemplate(t).resolve(va, sym))
    raise AssertionError("thunk_list_fill_width not in patches.yaml")


@lru_cache(maxsize=None)
def _core():
    """v4 (fix 18): the shipped t_t1_list_w the native arm calls -- (va, resolved bytes)."""
    sym = _live()[0]
    for c in ap.load_patches(Path(ap.DEFAULT_PATCHES))[2]:
        for e in c.get("contents") or []:
            if e["id"] == "t_t1_list_w":
                va = int(c["virtual_addr"]) + int(e["offset"])
                assert va == sym["t_t1_list_w"]
                return va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, sym))
    raise AssertionError("t_t1_list_w not in patches.yaml")


def test_shipped_bytes_are_the_assembler_output():
    sym, cave, va, tmpl, code = _live()
    assert cave["id"] == "menu_strip_thunks" and va == ASM.CODE_VA
    assert tmpl == ASM.template(ASM.assemble())
    assert "E8 {rel32:t_t1_list_w}" in tmpl                     # v4: the one-owner core (fix 18)
    assert len(code) <= ASM.SLOT_LIMIT
    assert va + ASM.SLOT_LIMIT <= sym["thunk_content_frame"]


# ==== 3. the real bytes == the law ===================================================================================
PAGE = 0x1000
STACK = 0x00200000
DLG_BASE = 0x00300000          # the attach `this` region (esi - 0xa34 ... Dialog)
PARENT = 0x00380000
RET = RESUME


class Thunk:
    """The resolved thunk bytes at their VA; run to GraphicWin_init's entry."""

    def __init__(self):
        sym, cave, va, _t, code = _live()
        cva, core = _core()
        self.va, self.code = va, code
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for base in {va & ~0xFFF, (va + len(code)) & ~0xFFF, G & ~0xFFF, GW_INIT & ~0xFFF, STACK - PAGE,
                     DLG_BASE, DLG_BASE + PAGE, PARENT, cva & ~0xFFF, (cva + len(core)) & ~0xFFF}:
            mu.mem_map(base, PAGE)
        mu.mem_write(va, code)
        mu.mem_write(cva, core)

    def run(self, g, d: dict, parent_vtbl=0):
        mu = self.mu
        mu.mem_write(DLG_BASE, bytes(2 * PAGE))
        mu.mem_write(PARENT, struct.pack("<I", parent_vtbl))
        x = DLG_BASE + 0x40                          # element base: [x] -> vtbl-like ptr whose +8 = adjustor
        vt = DLG_BASE + 0x10
        off = 0xA34 + 0x100                          # Dialog = x + off
        mu.mem_write(x, struct.pack("<I", vt))
        mu.mem_write(vt + 8, struct.pack("<I", off))
        dlg = x + off
        mu.mem_write(dlg + 0x20, bytes([d["flags"]]))
        for f, k in ((0x2C, "xs"), (0x30, "fixed_h"), (0x40, "margin"), (0x44, "gap"), (0x4C, "cols"),
                     (0xCC, "rows"), (0x5C, "d5c"), (0x64, "d64")):
            mu.mem_write(dlg + f, struct.pack("<i", d[k]))
        mu.mem_write(G, struct.pack("<i", g))
        args = (7, 9, d["d5c"], 100, 0, 0x20, PARENT, 0, 0)
        sp = STACK - 0x200
        mu.mem_write(sp, struct.pack("<10I", RET, *args))
        regs = {UC_X86_REG_EAX: 0x11, UC_X86_REG_EBX: 0x22, UC_X86_REG_ECX: 0x33, UC_X86_REG_EDX: 0x44,
                UC_X86_REG_ESI: x + 0xA34, UC_X86_REG_EDI: 0x55, UC_X86_REG_EBP: 0x66, UC_X86_REG_ESP: sp}
        for r, v in regs.items():
            mu.reg_write(r, v)
        mu.emu_start(self.va, GW_INIT, count=10_000)
        assert mu.reg_read(UC_X86_REG_EIP) == GW_INIT
        for r, v in regs.items():
            assert mu.reg_read(r) == v, ("register not preserved", r)
        out = struct.unpack("<10I", bytes(mu.mem_read(sp, 40)))
        assert out[0] == RET and out[1:3] == args[:2] and out[4:] == args[3:]
        rd = lambda f: struct.unpack("<i", bytes(mu.mem_read(dlg + f, 4)))[0]   # noqa: E731
        return out[3], rd(0x5C), rd(0x64), bytes(mu.mem_read(dlg, 0x100))


@pytest.fixture(scope="module")
def thunk():
    return Thunk()


def _cases(g):
    for rows in (1, 2, 18):
        for margin in (0, 3):
            for cols in (1, 2):
                for xs in (440, 457, 660):
                    yield dict(flags=0, xs=xs, fixed_h=0, margin=margin, gap=SL.dialog_row_margin(3, g), cols=cols,
                               rows=rows, d5c=890, d64=880), False
                    yield dict(flags=3, xs=xs, fixed_h=PREF_H, margin=margin, gap=6, cols=cols, rows=rows,
                               d5c=xs, d64=xs - 6), False
                    yield dict(flags=1, xs=xs, fixed_h=0, margin=margin, gap=SL.dialog_row_margin(3, g), cols=cols,
                               rows=rows, d5c=900, d64=890), False              # flags&1 but no height: rowgap path
                    yield dict(flags=3, xs=editor_xs(g), fixed_h=300, margin=margin, gap=6, cols=cols, rows=rows,
                               d5c=editor_xs(g), d64=editor_xs(g) - 6), True
        yield dict(flags=0, xs=660, fixed_h=0, margin=0, gap=5, cols=1, rows=rows, d5c=657, d64=657), False  # foreign


@pytest.mark.parametrize("g", list(GS) + [0, 15])
def test_real_bytes_equal_the_law(thunk, g):
    for d, owned in _cases(g):
        w, d5c, d64, mem = thunk.run(g, d, SL.DIPLO_EDIT_VTBL if owned else 0x0066C9F0)
        law = SL.type1_list_fill_width(d["xs"], d["margin"], d["cols"], d["gap"], d["flags"], d["fixed_h"],
                                       d["rows"], g, owned=owned)
        if law is None:
            assert (w, d5c, d64) == (d["d5c"], d["d5c"], d["d64"]), (g, d)
        else:
            assert (w, d5c, d64) == law, (g, d, owned)


def test_owned_container_is_keyed_on_the_parent_vtable(thunk):
    d = dict(flags=3, xs=927, fixed_h=300, margin=0, gap=6, cols=1, rows=13, d5c=927, d64=921)
    assert thunk.run(40, d, SL.DIPLO_EDIT_VTBL)[:3] == (927, 927, 912)
    assert thunk.run(40, d, 0x0066E95C)[:3] == (2317, 2317, 2302)      # any other parent: a native container


# ==== 4. FUN_0060e800 whole, pristine vs the bake ====================================================================
FN = 0x60E800
CALC = 0x60ED10
SET_TC, SET_C2, SET_C3, SET_FONT, TEXT_W, TEXT_H, LINE_H = 0x5DACB0, 0x5DACE0, 0x5DAD10, 0x5DAC70, 0x5DC790, 0x5DCA80, \
    0x5DCAB0
OFF, WIN_OFF = 0xBA0, 0x400
EHEAP, ESTACK, ESENT = 0x20000000, 0x10000000, 0x0DEAD000


@lru_cache(maxsize=None)
def _image(data: bytes):
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    img = bytes(pe.get_memory_mapped_image())
    size = (max(len(img), pe.OPTIONAL_HEADER.SizeOfImage) + 0xFFF) & ~0xFFF
    pe.close()
    return ib, size, img


class Attach:
    """One type-1 element in a fresh copy of the image; the leaf engine primitives stubbed."""

    def __init__(self, data: bytes, w: int, h: int, g: int, cfg: dict, text_dev):
        ib, size, img = _image(data)
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, size)
        uc.mem_write(ib, img)
        for base, n in ((EHEAP, 0x100000), (ESTACK - 0x10000, 0x20000), (ESENT, PAGE)):
            uc.mem_map(base, n)
        self.top = EHEAP
        uc.mem_write(SW, struct.pack("<ii", w, h))
        uc.mem_write(G, struct.pack("<i", g))
        uc.mem_write(0x9B7B28, struct.pack("<I", 1))                    # g_game_hwnd != 0
        self.gw = []
        self.text_w = {}
        stubs = {GW_INIT: (0x24, 9), SET_TC: (0x10, 4), SET_C2: (0x10, 4), SET_C3: (0x10, 4), SET_FONT: (0x10, 4),
                 TEXT_W: (4, 1), TEXT_H: (0, 0), LINE_H: (0, 0)}

        def hook(u, addr, _size, _ud):
            if addr not in stubs:
                return
            retn, n = stubs[addr]
            esp = u.reg_read(UC_X86_REG_ESP)
            args = struct.unpack("<%dI" % n, bytes(u.mem_read(esp + 4, 4 * n))) if n else ()
            ret = 0
            if addr == GW_INIT:
                self.gw.append((u.reg_read(UC_X86_REG_ECX), args))
            elif addr == TEXT_W:
                ret = self.text_w[args[0]]
            elif addr in (TEXT_H, LINE_H):
                ret = 15 * max(g, 16) // 16
            r = struct.unpack("<I", bytes(u.mem_read(esp, 4)))[0]
            u.reg_write(UC_X86_REG_EAX, ret)
            u.reg_write(UC_X86_REG_ESP, esp + 4 + retn)
            u.reg_write(UC_X86_REG_EIP, r)
        for va in stubs:
            uc.hook_add(UC_HOOK_CODE, hook, begin=va, end=va)
        x = self.x = self.alloc(0x2000)
        p = self.alloc(0x10)
        uc.mem_write(x, struct.pack("<I", p))
        uc.mem_write(p + 4, struct.pack("<II", WIN_OFF, OFF))
        d = self.d = x + OFF
        spr = self.alloc(0x40)
        uc.mem_write(spr + 0x18, struct.pack("<ii", 11, 11))
        uc.mem_write(x + 0x10, struct.pack("<II", spr, spr))
        uc.mem_write(d + 0x20, bytes([cfg["flags"]]))
        for f, k in ((0x2C, "xs"), (0x30, "fixed_h"), (0x34, "indent"), (0x40, "margin"), (0x44, "gap")):
            uc.mem_write(d + f, struct.pack("<i", cfg[k]))
        uc.mem_write(d + 0x48, struct.pack("<iii", -1, 1, 0))           # stride preset -1, cols 1
        nodes = [self.alloc(0x20) for _ in range(cfg["rows"])]
        for i, nd in enumerate(nodes):
            item = self.alloc(0x10)
            txt = self.alloc(0x10)
            self.text_w[txt] = text_dev[i % len(text_dev)]
            uc.mem_write(item + 4, struct.pack("<I", txt))
            uc.mem_write(nd + 8, struct.pack("<II", item, nodes[(i + 1) % len(nodes)]))
        uc.mem_write(d + 0xC4, struct.pack("<IIII", 1, nodes[-1], len(nodes), len(nodes) - 1))
        self.parent = self.alloc(0x100)
        uc.mem_write(self.parent, struct.pack("<I", cfg.get("parent_vtbl", 0)))

    def alloc(self, n):
        a = self.top
        self.top += (n + 0xF) & ~0xF
        return a

    def call(self, va, args, ecx):
        sp = ESTACK - 4 * len(args)
        self.uc.mem_write(sp, struct.pack("<%dI" % len(args), *args))
        sp -= 4
        self.uc.mem_write(sp, struct.pack("<I", ESENT))
        self.uc.reg_write(UC_X86_REG_ESP, sp)
        self.uc.reg_write(UC_X86_REG_ECX, ecx)
        self.uc.emu_start(va, ESENT, count=2_000_000)
        assert self.uc.reg_read(UC_X86_REG_EIP) == ESENT

    def run(self, twice: bool):
        if twice:                                                         # the dims dispatch calc ran first
            self.call(CALC, (), self.x)
        self.call(FN, (self.parent, 7, 9, 0), self.x + 0xA34)
        assert len(self.gw) == 1
        rd = lambda f: struct.unpack("<i", bytes(self.uc.mem_read(self.d + f, 4)))[0]   # noqa: E731
        return dict(args=self.gw[0][1], w=self.gw[0][1][2], d5c=rd(0x5C), d64=rd(0x64), indent=rd(0x34),
                    gap=rd(0x44), mem=bytes(self.uc.mem_read(self.d, 0x100)))


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return baked_exe.read_bytes()


def _census(w: int, g: int):
    """(name, cfg, native text widths, owned) for every list the thunk serves, on a w-wide screen at g."""
    xs = POPUP_XS if w > 1023 else 440
    for tag, (rows, text, _s) in POPUPS.items():
        yield tag, dict(flags=0, xs=xs, fixed_h=0, indent=CHECKBOX_INDENT, margin=0, gap=POPUP_GAP, rows=rows), \
            [text, text * 3 // 4, text // 2], False
    for i, rows in enumerate(PREF_PAGES):
        yield f"PrefWin page {i}", dict(flags=3, xs=PREF_XS, fixed_h=PREF_H, indent=CHECKBOX_INDENT, margin=0,
                                        gap=PREF_GAP, rows=rows), [260, 199, 150], False
    yield "editor diplomacy", dict(flags=3, xs=editor_xs(g), fixed_h=339, indent=CHECKBOX_INDENT, margin=0,
                                   gap=EDITOR_GAP, rows=EDITOR_ROWS, parent_vtbl=SL.DIPLO_EDIT_VTBL), \
        [240, 180, 120], True


G16_SCREENS = ((800, 600), (1024, 768), (1366, 768))
HI_SCREENS = ((1088, 816), (1600, 900), (1920, 1080), (1600, 1200), (2560, 1440), (3840, 2160))


@pytest.mark.parametrize("w, h", G16_SCREENS)
def test_g16_is_pristine(baked, bak_bytes, w, h):
    g = SL.popup_g(w, h)
    assert g == 16
    for name, cfg, text, _owned in _census(w, g):
        for twice in (False, True):
            a = Attach(baked, w, h, g, cfg, text).run(twice)
            v = Attach(bak_bytes, w, h, g, cfg, text).run(twice)
            assert (a["args"], a["mem"]) == (v["args"], v["mem"]), (name, w, h, twice)


def _scaled_text(native: int, g: int) -> int:
    """Device-px row-text widths for the calc stub: native x g/16 (the thunk's outputs do not depend on them)."""
    return native * g // 16


@pytest.mark.parametrize("w, h", HI_SCREENS)
def test_scaled_fields_are_vanilla_times_g(baked, w, h):
    g = SL.popup_g(w, h)
    assert g > 16
    for name, cfg, text, owned in _census(w, g):
        dev = [_scaled_text(t, g) for t in text]
        for twice in (False, True):
            a = Attach(baked, w, h, g, cfg, dev).run(twice)
            gap_field = SL.dialog_row_margin(cfg["gap"], g) if not (cfg["flags"] & 1 and cfg["fixed_h"]) \
                else cfg["gap"]
            law = SL.type1_list_fill_width(cfg["xs"], 0, 1, gap_field, cfg["flags"], cfg["fixed_h"], cfg["rows"], g,
                                           owned=owned)
            assert (a["w"], a["d5c"], a["d64"]) == law, (name, w, h, twice, a["w"], a["d5c"], a["d64"], law)
            if not owned:
                van = SL.type1_list_widths(cfg["xs"], 0, 1, cfg["gap"], bool(cfg["flags"] & 2))
                assert (a["w"], a["d5c"], a["d64"]) == tuple(v * g // 16 for v in van), name


# ---- row text vs the bar: real GDI, the face the game registers (arialn.ttf ONLY: in-game "Arial Narrow bold" is GDI
# synthetic bold of Arial Narrow regular -- the scaling-text skill). The scaled list font is g_pf0 as
# thunk_build_scaled_fonts builds it (Arial Narrow bold, size up from g until cell >= 20g >> 4); +5% covers the
# Frida-measured spread (Customize Game Rules 4K row text 890 vs this model's 863).
_GDI = None


def _gdi():
    global _GDI
    if _GDI is None:
        if sys.platform != "win32":
            pytest.skip("real GDI text metrics need Windows")
        import config
        font = config.game_dir(required=False) / "arialn.ttf"
        if not font.is_file():
            pytest.skip(f"{font} absent")
        gdi = ctypes.windll.gdi32
        assert gdi.AddFontResourceExA(str(font).encode("mbcs"), 0x10, None) == 1         # FR_PRIVATE, arialn ONLY
        gdi.CreateFontIndirectA.restype = ctypes.c_void_p
        gdi.CreateFontIndirectA.argtypes = [ctypes.c_void_p]
        gdi.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi.SelectObject.restype = ctypes.c_void_p
        gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi.GetTextMetricsA.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi.GetTextExtentPoint32A.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        gdi.GetTextFaceA.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
        _GDI = (gdi, gdi.CreateCompatibleDC(None))
    return _GDI


@lru_cache(maxsize=None)
def _pf0(g: int):
    gdi, dc = _gdi()
    size, target = g, (20 * g) >> 4
    while True:
        lf = bytearray(60)
        struct.pack_into("<iiiii", lf, 0, -size, 0, 0, 0, 700)
        lf[24] = 7                                                # lfOutPrecision, as Font_init
        lf[28:28 + 12] = b"Arial Narrow"
        h = gdi.CreateFontIndirectA(ctypes.create_string_buffer(bytes(lf), 60))
        gdi.SelectObject(dc, h)
        tm = ctypes.create_string_buffer(64)
        gdi.GetTextMetricsA(dc, tm)
        face = ctypes.create_string_buffer(64)
        gdi.GetTextFaceA(dc, 64, face)
        assert face.value == b"Arial Narrow", "arialn.ttf did not load: measuring a fallback face"
        tmh, _a, _d, _il, tmel = struct.unpack_from("<iiiii", tm.raw, 0)
        if tmh + tmel >= target or size >= 64:
            return h
        size += 1


def _row_width(s: str, g: int) -> int:
    gdi, dc = _gdi()
    gdi.SelectObject(dc, _pf0(g))
    sz = (ctypes.c_long * 2)()
    gdi.GetTextExtentPoint32A(dc, s.encode("latin-1"), len(s), sz)
    return sz[0]


def test_native_widths_are_the_registered_face():
    """POPUPS' native widths are Arial Narrow 16 synthetic bold (g_pf0 at g = 16) of each list's longest line."""
    for tag, (_rows, native, s) in POPUPS.items():
        assert _row_width(s, 16) == native, tag


@pytest.mark.parametrize("w, h", HI_SCREENS)
def test_rows_fit_their_bar(baked, w, h):
    """Each popup list's longest row, at its scaled indent, fits the row-highlight bar, and the bar the window."""
    g = SL.popup_g(w, h)
    for name, cfg, text, owned in _census(w, g):
        a = Attach(baked, w, h, g, cfg, [_scaled_text(t, g) for t in text]).run(True)
        assert a["d64"] <= a["w"], name
        if name in POPUPS:
            need = -(-(CHECKBOX_INDENT + cfg["gap"]) * g // 16) + -(-_row_width(POPUPS[name][2], g) * 105 // 100)
            assert need <= a["d64"], (name, w, h, need, a["d64"])
