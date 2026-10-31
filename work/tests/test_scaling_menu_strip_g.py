"""SetupWin menu strip on g (2026-10-18 fix 13): the REAL BAKED BYTES of SetupWin_do_menu_rightside (0x4ADB70) and
SetupWin_draw_item (0x4AE4D0), emulated under Unicorn against the law scaling_laws.menu_strip_layout.

The main menu and every SetupWin strip submenu (titled: title strip + separator) used to scale by the unclamped
scale_uniform = min(W/1024, H/768): 800x600 drew at 0.78x, 1366x1024 at 1.33x where g = 20, 4K at 2.81x past the
g = 40 cap, and the hit-rect left / blit x / label L,R / title inset / clip band stayed native inside the scaled
strip; the close animation's separator (0x4AE199) was never scaled at all.  Now every element is
menu_strip_px(v, g) = v if g <= 16 else floor(v*g/16).

The harness runs the menu's code windows (font, window geometry, open loop, close loop, Spot_add loop incl. the
title text) and SetupWin_draw_item per item + one hover redraw, every engine callee stubbed and recorded; every cave
thunk (strip_px, thunk_ensure_scale, scale_uniform, the strip thunks, the gates) runs for real.  g starts at 0
(the lazy path: the strip computes g itself) or preset to the screen's g.

1. the law at g = 16 IS the pristine .bak at every resolution (the law's vanilla magnitudes are the bytes');
2. g <= 16: the baked image == pristine EXACTLY -- the semantic records AND the full engine callee sequence
   (name, ECX, args: Buffer_copy_4 for the strips, vanilla's Buffer_set_clip rect, ...);
3. g > 16: the baked image == the law, every element, 32 screens x 6 menu shapes x (lazy, preset g);
4. the hit (Spot) rects are the drawn strips' rows, [s(15), s(300)) across, at every g;
5. no strip thunk calls scale_uniform any more (only thunk_ensure_scale, which derives g);
6. the cave entries are assemble_thunks.py's source;
7. mutants (a scale_uniform call restored, the 0x4AE199 redirect removed) are killed;
8. the WHOLE body of SetupWin_do_menu_rightside (open animation, Spot build, draw_item pass, hover redraws, close
   animation; real Spot_* and CRT string code) at g <= 16 == pristine callee for callee, at g > 16 == the law, with
   ESP == ebp - 0x1228 at the stop point (and the Ocean Coverage planet preview at 800x600 / 1024x768 == pristine).
"""
from __future__ import annotations

import struct
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn")
pefile = pytest.importorskip("pefile")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_thunks as AT  # noqa: E402
import scaling_laws as SL  # noqa: E402

SW, SH, G = 0x9B7B1C, 0x9B7B20, 0x668740
BACKBUF, IAT_CHARUPPER = 0x945824, 0x66931C
FONT_INIT, GW_INIT, BC4, BC3, FILL3 = 0x618F40, 0x5D4EF0, 0x5DFF00, 0x5D9610, 0x5D5440
SPOT_ADD, SPOT_GET, SETCLIP, TXTCOL, WCENT = 0x5FA960, 0x5FAC00, 0x5D8000, 0x5DACB0, 0x5DD130
STRLEN, STRCHR = 0x6453E0, 0x645DD0
DRAW_ITEM = 0x4AE4D0
STACK, STACK_SZ, HEAP, HEAP_SZ, STUBS, SENT = 0x10000000, 0x100000, 0x20000000, 0x100000, 0x30000000, 0x0DEAD000
EBP = STACK + 0x80000
TITLE = "SCENARIO"

# name, retn (callee-cleaned bytes), nargs
STUB_TABLE = {
    FONT_INIT: ("Font_init", 0xC, 3), GW_INIT: ("GraphicWin_init", 0x24, 9), BC4: ("Buffer_copy_4", 0x1C, 7),
    BC3: ("Buffer_copy_3", 0x24, 9), FILL3: ("GraphicWin_fill_3", 0x14, 5), SPOT_ADD: ("Spot_add", 0x18, 6),
    SPOT_GET: ("Spot_get_rect", 0xC, 3), SETCLIP: ("Buffer_set_clip", 4, 1), TXTCOL: ("Buffer_set_text_color", 0x10, 4),
    WCENT: ("Buffer_write_cent_l_7", 0xC, 3), STRLEN: ("strlen", 0, 1), STRCHR: ("strchr", 0, 2),
    STUBS: ("CharUpperA", 4, 1),
}

# g <= 16: the seven named screens + more 16:9 / odd ones (W > 1024 at g = 16 is the classic lo-res-gate trap)
RES_LO = [(800, 600), (1024, 768), (1280, 720), (1366, 768), (2048, 768), (1087, 815), (1024, 1024),
          (640, 480), (1280, 768), (1280, 800), (1360, 768), (1152, 768), (1440, 810), (1920, 815)]
# g > 16: 32 screens, g = 17 .. 40 (the 4:3 / 5:4 / 16:10 / 16:9 / 21:9 families, the cap, past the cap)
RES_HI = [(1088, 816), (1152, 864), (1440, 900), (1600, 900), (1280, 960), (1280, 1024), (1400, 1050), (1680, 1050),
          (1920, 1080), (2560, 1080), (1704, 960), (1792, 1344), (1600, 1200), (1920, 1200), (1500, 1125),
          (1366, 1024), (2048, 1536), (1920, 1440), (2304, 1440), (2560, 1440), (3440, 1440), (2560, 1600),
          (3840, 1600), (2736, 1824), (2880, 1800), (3200, 1800), (3000, 2000), (2560, 2048), (3840, 2160),
          (4096, 2160), (5120, 2880), (7680, 4320)]
SHAPES = [(7, False), (6, True), (1, False), (1, True), (9, False), (8, True)]   # (items, titled)
REPORT = [(3840, 2160), (2560, 1440), (1920, 1080), (1600, 1200), (1600, 900), (1280, 1024), (1366, 768),
          (1024, 768), (800, 600)]


# ---- the image under test ----------------------------------------------------------------------------------------
class Img(bytes):
    """A PE image; a short repr keeps a failure report readable."""

    def __repr__(self):
        return f"<PE image {len(self)} B>"


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return Img(baked_exe.read_bytes())


@pytest.fixture(scope="module")
def pristine(bak_bytes) -> bytes:
    return Img(bak_bytes)


@lru_cache(maxsize=None)
def _image(data: bytes):
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    img = bytes(pe.get_memory_mapped_image())
    size = (max(len(img), pe.OPTIONAL_HEADER.SizeOfImage) + 0xFFF) & ~0xFFF
    pe.close()
    return ib, size, img


class Menu:
    """One SetupWin strip menu on a W x H screen, in a fresh copy of the image."""

    def __init__(self, data: bytes, w: int, h: int, items: int, titled: bool, g_pre: int = 0):
        ib, size, img = _image(data)
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, size)
        uc.mem_write(ib, img)
        for base, sz in ((STACK, STACK_SZ), (HEAP, HEAP_SZ), (STUBS, 0x1000), (SENT, 0x1000)):
            uc.mem_map(base, sz)
        uc.mem_write(STUBS, b"\xC3")
        uc.mem_write(SENT, b"\xF4")
        self.heap = HEAP
        self.w32(SW, w)
        self.w32(SH, h)
        self.w32(G, g_pre)
        self.w32(BACKBUF, 0)                     # no backbuffer: the planet-preview decoration block is skipped
        self.w32(IAT_CHARUPPER, STUBS)
        self.items, self.titled = items, titled
        self.esi = self.alloc(b"\0" * 0x1400)
        self.w32(self.esi + 0x1198, SL.MENU_STRIP_W)
        self.w32(self.esi + 0x119C, -SL.MENU_STRIP_H)
        self.w32(self.esi + 0xA14, w)
        self.w32(self.esi + 0xA18, h)
        self.w32(self.esi + 0xA40, 0x12345678)
        self.w32(self.esi + 0xFCC, items)
        uc.mem_write(EBP - 0x1B0, (TITLE.encode() + b"\0") if titled else b"\0")
        self.rec: list = []      # semantic records (the law's vocabulary)
        self.calls: list = []    # every engine callee: (name, ecx, args)
        self.spots: dict = {}
        for va in STUB_TABLE:
            uc.hook_add(UC_HOOK_CODE, self._stub, begin=va, end=va)

    # -- memory
    def r32(self, a: int) -> int:
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def w32(self, a: int, v: int) -> None:
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def alloc(self, data: bytes) -> int:
        a = self.heap
        self.heap += (len(data) + 0xF) & ~0xF
        self.uc.mem_write(a, data)
        return a

    def cstr(self, a: int) -> str:
        return bytes(self.uc.mem_read(a, 64)).split(b"\0")[0].decode()

    # -- the engine, stubbed
    def _stub(self, uc, addr, _size, _ud):
        name, retn, nargs = STUB_TABLE[addr]
        esp = uc.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<%di" % nargs, bytes(uc.mem_read(esp + 4, 4 * nargs)))
        ecx = uc.reg_read(UC_X86_REG_ECX)
        self.calls.append((name, ecx, args))
        ret = 0
        r = self.rec
        if addr == FONT_INIT:
            r.append(("font", args[1], args[2]))
        elif addr == GW_INIT:
            r.append(("window",) + args[:4])
        elif addr == BC4:
            r.append(("blit", args[3], args[4], args[5], abs(args[6])))
        elif addr == BC3:
            r.append(("blit", args[5], args[6], args[7], args[8]))
        elif addr == FILL3:
            r.append(("fill",) + args[:5])
        elif addr == SPOT_ADD:
            r.append(("spot",) + args[:6])
        elif addr == SPOT_GET:
            x, y, w, h = self.spots[args[0]]
            for k, v in enumerate((x, y, x + w, y + h)):
                self.w32(args[2] + 4 * k, v)
        elif addr == SETCLIP:
            r.append(("clip",) + tuple(self.r32(args[0] + 4 * k) for k in range(4)))
        elif addr == WCENT:
            r.append(("text", self.cstr(args[0])) + tuple(self.r32(args[1] + 4 * k) for k in range(4)))
        elif addr == STRLEN:
            ret = len(self.cstr(args[0]))
        elif addr == STUBS:
            ret = args[0]
        uc.reg_write(UC_X86_REG_EAX, ret & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + retn)
        uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", bytes(uc.mem_read(esp, 4)))[0])

    # -- the menu's code windows
    def window(self, start: int, stop: int, regs=None) -> None:
        uc = self.uc
        uc.reg_write(UC_X86_REG_ESI, self.esi)
        uc.reg_write(UC_X86_REG_EBP, EBP)
        uc.reg_write(UC_X86_REG_ESP, EBP - 0x1300)
        for k, v in (regs or {}).items():
            uc.reg_write(k, v)
        uc.emu_start(start, stop, count=2_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == stop, hex(uc.reg_read(UC_X86_REG_EIP))

    def draw_item(self, item: int, hover: int) -> None:
        lst = self.alloc(b"\0" * 0x20)
        nodes = []
        for i in range(self.count):
            s = self.alloc(f"Item{i}\0".encode())
            o = self.alloc(b"\0" * 8)
            self.w32(o + 4, s)
            n = self.alloc(b"\0" * 16)
            self.w32(n + 8, o)
            nodes.append(n)
        for a, b in zip(nodes, nodes[1:]):
            self.w32(a + 0xC, b)
        self.w32(lst + 8, nodes[0])
        self.w32(lst + 0x10, self.count)
        self.w32(self.esi + 0x1010, lst)
        sp = STACK + STACK_SZ - 0x1000
        self.uc.mem_write(sp, struct.pack("<III", SENT, item, hover))
        self.uc.reg_write(UC_X86_REG_ESP, sp)
        self.uc.reg_write(UC_X86_REG_ECX, self.esi)
        self.uc.emu_start(DRAW_ITEM, SENT, count=2_000_000)

    def run(self) -> "Menu":
        self.window(0x4ADC86, 0x4ADC99, {UC_X86_REG_EBX: 0})      # Font_init (size)
        self.window(0x4ADDF9, 0x4ADE5B, {UC_X86_REG_EBX: 0})      # window geometry -> GraphicWin_init
        self.window(0x4ADEF0, 0x4ADF63, {UC_X86_REG_EBX: 0})      # one OPEN-animation frame
        self.window(0x4AE137, 0x4AE1AC)                              # one CLOSE-animation frame
        self.window(0x4ADF95, 0x4AE0B0)                              # title text + the Spot_add loop
        for t in self.rec:
            if t[0] == "spot":
                self.spots[t[1]] = t[3:7]
        self.count = self.r32(self.esi + 0xFCC)
        for i in range(self.count):
            self.draw_item(i, 0)
        self.draw_item(min(1, self.count - 1), 1)                  # a hover redraw
        self.g = self.r32(G)
        return self


def run_menu(data: bytes, w: int, h: int, items: int, titled: bool, g_pre: int = 0) -> Menu:
    return Menu(data, w, h, items, titled, g_pre).run()


# ---- the law, in the harness's vocabulary ---------------------------------------------------------------------------
def law_records(w: int, h: int, items: int, titled: bool, g: int) -> list:
    L = SL.menu_strip_layout(w, h, items, titled, g)
    recs = [("font", L["font"], 1), ("window",) + L["window"]]
    loop = []
    for k, (x, y, sw, sh) in enumerate(L["strips"]):
        loop.append(("blit", x, y, sw, sh))
        if k == 0 and L["separator"]:
            loop.append(("fill",) + L["separator"] + (9,))
    recs += loop + loop                                              # the open frame, then the close frame
    if L["title"]:
        recs.append(("text", TITLE) + L["title"])
    recs += [("spot", i, 0) + s for i, s in enumerate(L["spots"])]

    def item(i):
        it = L["item"][i]
        return [("clip",) + it["clip"], ("blit",) + it["blit"], ("text", f"Item{i}") + it["text"], ("clip", 0, 0, 0, 0)]
    for i in range(items):
        recs += item(i)
    recs += item(min(1, items - 1))
    return recs


def first_diff(a: list, b: list):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i, x, y
    return None if len(a) == len(b) else ("len", len(a), len(b))


# ---- 1. the law's vanilla magnitudes are the pristine bytes' ------------------------------------------------------
@pytest.mark.parametrize("w,h", RES_LO + RES_HI)
def test_law_at_g16_is_the_pristine_menu(pristine, w, h):
    for items, titled in SHAPES:
        m = run_menu(pristine, w, h, items, titled)
        assert first_diff(law_records(w, h, items, titled, SL.NATIVE_G), m.rec) is None, (w, h, items, titled)


# ---- 2. g <= 16 is vanilla, records AND callees -------------------------------------------------------------------
@pytest.mark.parametrize("w,h", RES_LO)
def test_scaling_menu_strip_g16_is_pristine(baked, pristine, w, h):
    assert SL.popup_g(w, h) <= SL.NATIVE_G
    for items, titled in SHAPES:
        p = run_menu(pristine, w, h, items, titled)
        for g_pre in (0, SL.popup_g(w, h)):
            b = run_menu(baked, w, h, items, titled, g_pre)
            assert b.g == SL.popup_g(w, h)
            assert first_diff(p.rec, b.rec) is None, (w, h, items, titled, g_pre, first_diff(p.rec, b.rec))
            assert first_diff(p.calls, b.calls) is None, (w, h, items, titled, g_pre, first_diff(p.calls, b.calls))
            assert "Buffer_copy_3" not in {c[0] for c in b.calls}


# ---- 3. g > 16 is the law, every element ---------------------------------------------------------------------------
@pytest.mark.parametrize("w,h", RES_HI)
def test_scaling_menu_strip_is_the_law_above_g16(baked, w, h):
    g = SL.popup_g(w, h)
    assert g > SL.NATIVE_G
    for items, titled in SHAPES:
        for g_pre in (0, g):
            b = run_menu(baked, w, h, items, titled, g_pre)
            assert b.g == g
            want = law_records(w, h, items, titled, g)
            assert first_diff(want, b.rec) is None, (w, h, g, items, titled, g_pre, first_diff(want, b.rec))


def test_screen_set_covers_every_g_above_16():
    assert len(RES_HI) == 32
    assert {SL.popup_g(w, h) for w, h in RES_HI} >= {17, 18, 20, 21, 22, 25, 30, 33, 40}
    assert {SL.popup_g(w, h) for w, h in RES_LO} == {SL.NATIVE_G}


# ---- 4. the hit rects are the drawn strips --------------------------------------------------------------------------
@pytest.mark.parametrize("w,h", [(800, 600), (1024, 768), (1366, 768), (1600, 900), (1280, 1024), (1920, 1080),
                                 (1600, 1200), (2560, 1440), (3840, 2160)])
def test_scaling_menu_strip_spots_are_the_drawn_strips(baked, w, h):
    g = SL.popup_g(w, h)
    s = lambda v: SL.menu_strip_px(v, g)  # noqa: E731
    for items, titled in SHAPES:
        m = run_menu(baked, w, h, items, titled)
        win = [r for r in m.rec if r[0] == "window"][0]
        blits = [r for r in m.rec if r[0] == "blit"]
        n = items + titled
        open_loop, item_blits = blits[:n], blits[2 * n:]
        spots = [r[3:] for r in m.rec if r[0] == "spot"]
        assert len(spots) == items
        for i, (x, y, sw, sh) in enumerate(spots):
            strip = open_loop[i + titled][1:]                 # the animation strip this item sits on
            drawn = item_blits[i][1:]                          # the strip draw_item repaints for it
            assert (strip[1], strip[3]) == (y, sh) == (drawn[1], drawn[3]), (w, h, i, strip, drawn, (x, y, sw, sh))
            assert strip[0] == drawn[0] == 0 and strip[2] == drawn[2] == win[3] == s(SL.MENU_STRIP_W)
            assert (x, x + sw) == (s(SL.MENU_STRIP_HIT_L), s(SL.MENU_STRIP_HIT_R))
            assert 0 <= x and x + sw <= drawn[2] and y + sh <= win[4]
        # the strips tile the window exactly: no gap, no overlap, no sliver
        last = open_loop[-1][1:]
        assert last[1] + last[3] == win[4]


# ---- 5. no strip thunk calls scale_uniform ---------------------------------------------------------------------------
def _cave(loaded_caves) -> dict:
    return next(c for c in loaded_caves if c["id"] == "menu_strip_thunks")


def scale_uniform_callers(data: bytes) -> list:
    """Every `call scale_uniform` inside the menu_strip_thunks cave."""
    pe = pefile.PE(data=data, fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    base = 0x668200
    blob = pe.get_data(base - ib, 0xE00)
    pe.close()
    out = []
    for k in range(len(blob) - 4):
        if blob[k] == 0xE8 and base + k + 5 + struct.unpack_from("<i", blob, k + 1)[0] == base:
            out.append(base + k)
    return out


def census_failures(data: bytes, ensure_va: int) -> list:
    return [hex(v) for v in scale_uniform_callers(data) if not ensure_va <= v < ensure_va + 0x3B]


def test_scaling_menu_strip_no_thunk_calls_scale_uniform(baked, loaded):
    ensure = loaded["s2v"]["thunk_ensure_scale"]
    assert loaded["s2v"]["scale_uniform"] == 0x668200
    assert census_failures(baked, ensure) == []
    assert [v for v in scale_uniform_callers(baked)] == [ensure + 0xE]      # thunk_ensure_scale derives g


# ---- 6. the cave entries are the assembler's source ----------------------------------------------------------------
STRIP_THUNKS = ("thunk_scale_rect_width", "thunk_strip_blit_stretched", "thunk_advance_edi_by_scaled_h",
                "thunk_load_strip_w_into_eax", "thunk_push_scaled_font", "thunk_spot_h_into_edi",
                "thunk_spot_h_into_eax", "thunk_spot_h_into_ecx", "thunk_text_fullrect", "thunk_clip_fullstrip",
                "thunk_fill3_scaled", "thunk_scale20_into_edx", "thunk_load_strip_w_into_edi")


def test_scaling_menu_strip_cave_is_the_assembler_source(loaded):
    src = {name: (off, AT.normalize(body)) for name, off, body in
           [(n, o, b) for n, o, b in AT.MENU_STRIP_G_ENTRIES]}
    consts = {"thunk_scale_rect_width": AT.THUNK_SCALE_RECT_WIDTH, "thunk_strip_blit_stretched":
              AT.THUNK_STRIP_BLIT_STRETCHED, "thunk_advance_edi_by_scaled_h": AT.THUNK_ADVANCE_EDI_BY_SCALED_H,
              "thunk_load_strip_w_into_eax": AT.THUNK_LOAD_STRIP_W_INTO_EAX, "thunk_push_scaled_font":
              AT.THUNK_PUSH_SCALED_FONT, "thunk_spot_h_into_edi": AT.THUNK_SPOT_H_INTO_EDI, "thunk_spot_h_into_eax":
              AT.THUNK_SPOT_H_INTO_EAX, "thunk_spot_h_into_ecx": AT.THUNK_SPOT_H_INTO_ECX, "thunk_text_fullrect":
              AT.THUNK_TEXT_FULLRECT, "thunk_clip_fullstrip": AT.THUNK_CLIP_FULLSTRIP, "thunk_fill3_scaled":
              AT.THUNK_FILL3_SCALED, "thunk_scale20_into_edx": AT.THUNK_SCALE20_INTO_EDX,
              "thunk_load_strip_w_into_edi": AT.THUNK_LOAD_STRIP_W_INTO_EDI}
    cave = {e["id"]: (int(e["offset"]), " ".join(str(e["bytes"]).split())) for e in _cave(loaded["caves"])["contents"]}
    for name, (off, body) in src.items():
        assert cave[name] == (off, body), name
    for name in STRIP_THUNKS:
        assert cave[name][1] == AT.normalize(consts[name]), name
        assert "{rel32:strip_px}" in cave[name][1] and "{rel32:scale_uniform}" not in cave[name][1], name
    assert sum(cave[n][1].count("{rel32:strip_px}") for n in STRIP_THUNKS) == 19


# ---- 7. mutants ------------------------------------------------------------------------------------------------------
LIVE_SITES = [0x668265, 0x668295, 0x6682A6, 0x6682F9, 0x668316, 0x668346, 0x668369, 0x668388, 0x668398, 0x6683B4,
              0x6683C4, 0x668404, 0x668411, 0x66841F, 0x668446, 0x668455, 0x668470, 0x668480]
DEAD_SITES = [0x6683EA]                  # thunk_clip_fullstrip: dead since t_clip_exact; only the census sees it
MUTANT_SCREENS = [(800, 600), (1600, 900), (1280, 1024), (1920, 1080), (3840, 2160)]


def _patch(data: bytes, va: int, new: bytes) -> bytes:
    pe = pefile.PE(data=data, fast_load=True)
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    pe.close()
    b = bytearray(data)
    b[off:off + len(new)] = new
    return Img(b)


def _call(at: int, target: int) -> bytes:
    return b"\xE8" + struct.pack("<i", target - (at + 5))


def behaviour_failures(data: bytes, pristine: bytes) -> list:
    bad = []
    for w, h in MUTANT_SCREENS:
        g = SL.popup_g(w, h)
        for items, titled in ((7, False), (6, True)):
            b = run_menu(data, w, h, items, titled)
            want = run_menu(pristine, w, h, items, titled).rec if g <= 16 else law_records(w, h, items, titled, g)
            d = first_diff(want, b.rec)
            if d:
                bad.append((w, h, items, titled, d))
    return bad


def test_mutants_baseline_is_clean(baked, pristine):
    assert behaviour_failures(baked, pristine) == []


@pytest.mark.parametrize("site", LIVE_SITES + DEAD_SITES, ids=hex)
def test_mutant_scale_uniform_restored_is_killed(baked, pristine, loaded, site):
    mut = _patch(baked, site, _call(site, 0x668200))
    assert census_failures(mut, loaded["s2v"]["thunk_ensure_scale"]), hex(site)
    if site in LIVE_SITES:
        assert behaviour_failures(mut, pristine), f"restoring scale_uniform @{site:#x} is invisible to the law check"


def test_mutant_close_separator_unredirected_is_killed(baked, pristine):
    mut = _patch(baked, 0x4AE199, _call(0x4AE199, FILL3))
    assert behaviour_failures(mut, pristine)


# ---- the before/after table (run with -s to print; asserts nothing beyond the law above) ---------------------------
def test_scaling_menu_strip_report_table(baked, capsys):
    rows = []
    for w, h in REPORT:
        g = SL.popup_g(w, h)
        m = run_menu(baked, w, h, 7, False)
        win = [r for r in m.rec if r[0] == "window"][0]
        sp = [r for r in m.rec if r[0] == "spot"]
        rows.append(f"{w}x{h} g={g}: font {m.rec[0][1]}, strip {win[3]}x{sp[1][4] - sp[0][4]}, window "
                    f"({win[1]},{win[2]}) h={win[4]} ({100 * win[4] / h:.1f}% of H), hit [{sp[0][3]},"
                    f"{sp[0][3] + sp[0][5]})")
        assert win[3] == SL.menu_strip_px(SL.MENU_STRIP_W, g)
    with capsys.disabled():
        print("\n" + "\n".join(rows))


# ---- 8. the WHOLE body of SetupWin_do_menu_rightside, ESP-balanced -------------------------------------------------
# The windows above run the menu in pieces.  This runs 0x4ADB92 .. 0x4AE2B1 in one go (everything after the SEH
# prologue / chkstk, before the fs:[0] epilogue): the script read, the 6-frame open animation, the Spot build (REAL
# Spot_* code), the first draw_item pass (REAL draw_item), the modal loop (vtbl +0xE4: intercepted; from there the
# hover redraws SetupWin_on_mouse_move makes, REAL draw_item), the 6-frame close animation.  CRT strcpy / strncmp /
# strlen / strchr run REAL; every other engine callee is stubbed and recorded (callee, ECX, args).  The stop point's
# ESP must be ebp - 0x1228 (validates every stub's RET imm and every cave thunk's stack discipline end to end).
WB_STUBS = {  # va: (name, retn, recorded)
    0x5D7210: ("ctor_5d7210", 0, 0), 0x618EA0: ("Font_ctor", 0, 0), 0x4C66E0: ("ctor_4c66e0", 0, 0),
    0x629D60: ("Flic_ctor", 0, 0), 0x5D7470: ("dtor_5d7470", 0, 1), 0x402970: ("list_clear", 0, 0),
    0x5BECA0: ("script_open", 0, 1), 0x629DF0: ("Flic_close", 0, 0), 0x618F40: ("Font_init", 0xC, 1),
    0x4C6C20: ("sound_load", 4, 0), 0x6007B0: ("trim_a", 0, 0), 0x600760: ("trim_b", 0, 0),
    0x5FD530: ("script_close", 0, 0), 0x5D7670: ("Buffer_init", 0x10, 1), 0x629E50: ("Flic_load", 0x14, 1),
    0x5D4EF0: ("GraphicWin_init", 0x24, 1), 0x5DACB0: ("Buffer_set_text_color", 0x10, 1),
    0x5DAC70: ("Buffer_set_font", 0x10, 1), 0x4C6920: ("sound_play", 0, 1), 0x62A070: ("Flic_frame", 8, 1),
    0x5DFF00: ("Buffer_copy_4", 0x1C, 1), 0x5D9610: ("Buffer_copy_3", 0x24, 1), 0x5D5440: ("GraphicWin_fill_3", 0x14, 1),
    0x5D5890: ("GraphicWin_update", 0, 1), 0x5D8000: ("Buffer_set_clip", 4, 1), 0x5DD130: ("write_cent", 0xC, 1),
    0x5FE2E0: ("dtor_5fe2e0", 0, 0), 0x5D7410: ("dtor_5d7410", 0, 0), 0x4C67C0: ("dtor_4c67c0", 0, 0),
    0x618EE0: ("Font_dtor", 0, 0), 0x5D4510: ("malloc", 0, 0), 0x644EF2: ("free", 0, 0),
    0x5E2210: ("Buffer_get_pixel", 8, 1), 0x5D84C0: ("Buffer_draw_2", 0x18, 1), 0x5D5720: ("soft_update", 0x10, 1),
    0x668670: ("thunk_keyed_stretch_blit", 0x2C, 1),
}
WB_VT = 0x0BEE0000                    # fake vtable page: entry k -> WB_VT + 0x100 + k
WB_VTSLOTS = {4: ("vt_04", 4), 8: ("vt_08", 0), 0xFC: ("vt_FC_flush", 0), 0xE4: ("vt_E4_modal", 0xC), 0xE8: ("vt_E8", 0)}
WB_STACK, WB_STACK_SZ, WB_HEAP = 0x10000000, 0x200000, 0x30000000
WB_STOP = 0x4AE2B1


class WholeMenu:
    def __init__(self, data: bytes, w: int, h: int, items: list, title, g_pre: int = 0, deco=None, sel: int = 0):
        ib, size, img = _image(data)
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, size)
        uc.mem_write(ib, img)
        uc.mem_map(WB_STACK, WB_STACK_SZ)
        uc.mem_map(WB_HEAP, 0x1000000)
        uc.mem_map(SENT, 0x1000)
        uc.mem_map(WB_VT, 0x1000)
        uc.mem_write(SENT, b"\xF4" * 0x1000)
        uc.mem_write(WB_VT, b"\xC3" * 0x1000)
        self.heap, self.rec, self.ticks, self.sel = WB_HEAP, [], 1000, sel
        self.stop_at = {WB_STOP}
        self.w32(SW, w)
        self.w32(SH, h)
        self.w32(G, g_pre)
        for a in (0x9A6490, 0x9A6488, BACKBUF):
            self.w32(a, 0)
        self.tick_stub, self.upper_stub = WB_VT + 0x800, WB_VT + 0x810
        self.w32(0x669368, self.tick_stub)              # GetTickCount
        self.w32(IAT_CHARUPPER, self.upper_stub)        # CharUpperA
        vt = WB_VT + 0x400
        for off in range(0, 0x200, 4):
            self.w32(vt + off, WB_VT + 0x100 + off)
        self.esi = self.alloc(0x1400)
        self.w32(self.esi, vt)
        self.w32(self.esi + 0xA40, self.alloc(0x800))
        lines = ([b"#caption " + title.encode()] if title else []) + [b"#itemlist", b"#x -5"]
        lines += [s.encode() for s in items] + [b""]
        self.lines = [self.alloc(len(ln) + 1, ln + b"\0") for ln in lines]
        self.li, self.nodes = 0, []
        self.deco = []
        if deco:                                        # (x, y, src_w, src_h): the planet preview, opaque
            bb = self.alloc(0x600)
            self.w32(BACKBUF, bb)
            x, y, dw, dh = deco
            for k in range(3):
                d = self.alloc(0x600)
                self.w32(d + 0x80, dw)
                self.w32(d + 0x84, -dh)
                self.w32(self.esi + 0xA1C + 4 * k, d)
                self.w32(self.esi + 0xA28 + 4 * k, x)
                self.w32(self.esi + 0xA34 + 4 * k, y)
                self.deco.append(d)
        self.extra = {0x5FD570: self._getline, 0x401100: self._listadd}
        uc.hook_add(UC_HOOK_CODE, self._dispatch)
        self.label = self.alloc(16, b"TESTMENU\0")

    def alloc(self, n: int, init: bytes = b"") -> int:
        a = self.heap
        self.heap += (n + 0x1F) & ~0xF
        self.uc.mem_write(a, init.ljust(n, b"\0") if init else b"\0" * n)
        return a

    def r32(self, a: int) -> int:
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def w32(self, a: int, v: int) -> None:
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def _ret(self, retn: int, eax=None) -> None:
        uc = self.uc
        esp = uc.reg_read(UC_X86_REG_ESP)
        ra = struct.unpack("<I", bytes(uc.mem_read(esp, 4)))[0]
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + retn)
        if eax is not None:
            uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_EIP, ra)

    def args(self, n: int) -> list:
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return [self.r32(esp + 4 + 4 * i) for i in range(n)]

    def _dispatch(self, uc, addr, _size, _ud):
        f = self.extra.get(addr)
        if f and addr not in self.stop_at:
            f()
            return
        if addr in self.stop_at:
            uc.emu_stop()
            return
        if addr == self.tick_stub:
            self.ticks += 20
            self._ret(0, self.ticks)
            return
        if addr == self.upper_stub:
            self._ret(4, self.args(1)[0])
            return
        if WB_VT + 0x100 <= addr < WB_VT + 0x300:
            off = addr - WB_VT - 0x100
            name, retn = WB_VTSLOTS.get(off, (f"vt_{off:x}", 0))
            self.rec.append((name, *self.args(retn // 4)))
            if off == 0xE4:
                self.pending_hover = True
                uc.emu_stop()
                return
            self._ret(retn, 0)
            return
        s = WB_STUBS.get(addr)
        if not s:
            return
        name, retn, recd = s
        ecx = uc.reg_read(UC_X86_REG_ECX)
        a = self.args(max(retn // 4, 4))
        ret = 0
        if name == "Flic_load":                       # the loader writes the FLC frame dims into the Buffer
            self.w32(a[0] + 0x80, SL.MENU_STRIP_W)
            self.w32(a[0] + 0x84, -SL.MENU_STRIP_H)
        elif name == "malloc":
            ret = self.alloc(self.args(1)[0])
        elif name == "Buffer_set_clip":
            a = [self.r32(a[0] + 4 * k) for k in range(4)]
        elif name == "write_cent":
            a = [bytes(uc.mem_read(a[0], 40)).split(b"\0")[0].decode()] + [self.r32(a[1] + 4 * k) for k in range(4)]
        if recd:
            full = name in ("Buffer_set_clip", "write_cent")
            self.rec.append((name, ecx, *(a if full else a[:retn // 4 if retn else len(a)])))
        self._ret(retn, ret)

    def _getline(self):                               # the menu-script line reader (no script file is loaded)
        v = self.lines[self.li] if self.li < len(self.lines) else 0
        self.li += 1
        self._ret(0, v)

    def _listadd(self):                               # list add: one node per item line
        lst = self.uc.reg_read(UC_X86_REG_ECX)
        obj = self.alloc(8)
        self.w32(obj + 4, self.r32(lst + 0x1C))
        n = self.alloc(16)
        self.w32(n + 8, obj)
        if self.nodes:
            self.w32(self.nodes[-1] + 0xC, n)
        else:
            self.w32(lst + 8, n)
        self.nodes.append(n)
        self.w32(lst + 0x10, len(self.nodes))
        self._ret(4, 0)

    def call(self, va: int, args: tuple, ecx: int, sp: int) -> None:
        uc = self.uc
        for a in reversed(args):
            sp -= 4
            self.w32(sp, a)
        sp -= 4
        self.w32(sp, SENT)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_ECX, ecx)
        stop, self.stop_at = self.stop_at, {SENT}
        uc.emu_start(va, 0xFFFFFFFF, count=5_000_000)
        self.stop_at = stop
        assert uc.reg_read(UC_X86_REG_EIP) == SENT
        assert uc.reg_read(UC_X86_REG_ESP) == sp + 4 + 4 * len(args), "draw_item stack imbalance"

    def run(self) -> "WholeMenu":
        uc = self.uc
        ebp = WB_STACK + 0x180000
        self.w32(ebp + 8, self.label)
        self.w32(ebp + 0xC, self.sel)
        self.w32(ebp + 4, SENT)
        uc.reg_write(UC_X86_REG_EBP, ebp)
        uc.reg_write(UC_X86_REG_ESP, ebp - 0x121C)
        uc.reg_write(UC_X86_REG_ECX, self.esi)
        self.pending_hover = False
        pc = 0x4ADB92
        while True:
            uc.emu_start(pc, 0xFFFFFFFF, count=20_000_000)
            if not self.pending_hover:
                break
            self.pending_hover = False
            regs = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                    UC_X86_REG_EBP, UC_X86_REG_ESP)
            saved = {r: uc.reg_read(r) for r in regs}
            n = self.r32(self.esi + 0xFCC)
            self.rec.append(("--hover--",))
            # SetupWin_on_mouse_move: the old item un-highlighted, the new one highlighted
            for i, hl in ((self.sel, 0), ((self.sel + 1) % n, 1), (n - 1, 1), (n - 1, 0)):
                self.call(DRAW_ITEM, (i, hl), self.esi, saved[UC_X86_REG_ESP] - 0x4000)
            self.rec.append(("--/hover--",))
            for r, v in saved.items():
                uc.reg_write(r, v)
            esp = saved[UC_X86_REG_ESP]
            uc.reg_write(UC_X86_REG_ESP, esp + 4 + 0xC)                     # the modal call returns (RET 0xC)
            pc = struct.unpack("<I", bytes(uc.mem_read(esp, 4)))[0]
        assert uc.reg_read(UC_X86_REG_EIP) == WB_STOP, hex(uc.reg_read(UC_X86_REG_EIP))
        self.esp_balance = uc.reg_read(UC_X86_REG_ESP) - (ebp - 0x1228)
        assert self.esp_balance == 0, ("ESP imbalance over the whole body", self.esp_balance)
        self.g = self.r32(G)
        return self


WB_SHAPES = {"TOPMENU7": (["START GAME", "QUICK START", "SCENARIO", "LOAD GAME", "MULTIPLAYER", "VIEW CREDITS",
                           "EXIT GAME"], None),
             "SCENARIO4T": (["PLAY SCENARIO", "CREATE SCENARIO", "LOAD MAP FILE", "EDIT SCENARIO"], "SCENARIO"),
             "ONE1T": (["X"], "T")}
WB_LO = [(800, 600), (1024, 768), (1366, 768), (1280, 720)]
WB_HI = [(1600, 1200), (1920, 1080), (1280, 1024), (3840, 2160)]


def wb_project(rec: list) -> list:
    """The whole-body stream in the law's vocabulary (the geometry the law speaks; dtors as markers)."""
    out = []
    for t in rec:
        n = t[0]
        if n == "dtor_5d7470":
            out.append(("dtor",))
        elif n == "Font_init":
            out.append(("font", t[3]))
        elif n == "GraphicWin_init":
            out.append(("window",) + tuple(t[2:6]))
        elif n == "Buffer_copy_4":
            out.append(("blit", t[5], t[6], t[7], abs(t[8])))
        elif n == "Buffer_copy_3":
            out.append(("blit", t[7], t[8], t[9], t[10]))
        elif n == "GraphicWin_fill_3":
            out.append(("fill",) + tuple(t[2:7]))
        elif n == "write_cent":
            out.append(("text",) + tuple(t[2:7]))
        elif n == "Buffer_set_clip":
            out.append(("clip",) + tuple(t[2:6]))
    return out


def wb_law(w: int, h: int, items: list, title, g: int) -> list:
    L = SL.menu_strip_layout(w, h, len(items), bool(title), g)
    loop = []
    for k, strip in enumerate(L["strips"]):
        loop.append(("blit",) + strip)
        if k == 0 and L["separator"]:
            loop.append(("fill",) + L["separator"] + (9,))
    out = [("dtor",), ("font", L["font"]), ("window",) + L["window"]] + loop * 6
    if title:
        out.append(("text", " " + title) + L["title"])

    def item(i):
        it = L["item"][i]
        return [("clip",) + it["clip"], ("blit",) + it["blit"], ("text", items[i]) + it["text"], ("clip", 0, 0, 0, 0)]
    for i in range(len(items)):
        out += item(i)
    n = len(items)
    for i in (0, 1 % n, n - 1, n - 1):                  # the hover redraws (sel = 0)
        out += item(i)
    return out + loop * 6 + [("dtor",), ("clip", 0, 0, 0, 0)]


@pytest.mark.parametrize("w,h", WB_LO)
@pytest.mark.parametrize("shape", list(WB_SHAPES))
def test_scaling_menu_strip_whole_body_g16_is_pristine(baked, pristine, w, h, shape):
    items, title = WB_SHAPES[shape]
    p = WholeMenu(pristine, w, h, items, title).run()
    assert wb_project(p.rec) == wb_law(w, h, items, title, SL.NATIVE_G)        # the law at g = 16 is vanilla
    for g_pre in (0, SL.popup_g(w, h)):
        b = WholeMenu(baked, w, h, items, title, g_pre).run()
        assert b.g == SL.popup_g(w, h) == SL.NATIVE_G
        assert first_diff(p.rec, b.rec) is None, (w, h, shape, g_pre, first_diff(p.rec, b.rec))


@pytest.mark.parametrize("w,h", WB_HI)
@pytest.mark.parametrize("shape", list(WB_SHAPES))
def test_scaling_menu_strip_whole_body_is_the_law_above_g16(baked, w, h, shape):
    items, title = WB_SHAPES[shape]
    g = SL.popup_g(w, h)
    assert g > SL.NATIVE_G
    for g_pre in (0, g):
        b = WholeMenu(baked, w, h, items, title, g_pre).run()
        assert b.g == g
        want = wb_law(w, h, items, title, g)
        assert first_diff(want, wb_project(b.rec)) is None, (w, h, g, shape, g_pre, first_diff(want, wb_project(b.rec)))


@pytest.mark.parametrize("w,h,deco", [(800, 600, (449, -168, 404, 768)), (1024, 768, (620, 0, 404, 768))])
def test_scaling_menu_strip_whole_body_with_planet_is_pristine_on_a_1to1_backdrop(baked, pristine, w, h, deco):
    """Select Ocean Coverage at 800x600 / 1024x768, the planet preview on (fix 15: the opening backdrop is drawn 1:1
    there, so the decoration is vanilla's) -- the whole body, hover redraws included, callee for callee."""
    items, title = ["30-50% of surface", "50-70% of surface", "70-90% of surface"], "SELECT OCEAN COVERAGE"
    p = WholeMenu(pristine, w, h, items, title, deco=deco).run()
    b = WholeMenu(baked, w, h, items, title, deco=deco).run()
    assert any(t[0] == "Buffer_copy_4" and t[1] in p.deco for t in p.rec)      # the hover pass drew the planet
    assert first_diff(p.rec, b.rec) is None, (w, h, first_diff(p.rec, b.rec))


def test_whole_body_esp_check_is_live(baked, loaded):
    """The ESP assert is not vacuous: a stub with the wrong RET imm (Font_init RET 0x10, not 0xC) and a cave thunk
    that pops one dword too many (t_title_inset `ret` -> `ret 4`) each unbalance the whole body, and the run says so."""
    saved = WB_STUBS[FONT_INIT]
    WB_STUBS[FONT_INIT] = ("Font_init", 0x10, 1)
    try:
        with pytest.raises(AssertionError, match="ESP imbalance"):
            WholeMenu(baked, 1024, 768, *WB_SHAPES["TOPMENU7"]).run()
    finally:
        WB_STUBS[FONT_INIT] = saved
    ret = loaded["s2v"]["t_title_inset"] + AT.count_bytes(AT.T_TITLE_INSET) - 1
    assert baked[_file_off(baked, ret)] == 0xC3
    for w, h in ((1024, 768), (1600, 1200)):
        with pytest.raises(AssertionError, match="ESP imbalance"):
            WholeMenu(_patch(baked, ret, b"\xC2\x04\x00"), w, h, *WB_SHAPES["SCENARIO4T"]).run()


def _file_off(data: bytes, va: int) -> int:
    pe = pefile.PE(data=data, fast_load=True)
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    pe.close()
    return off
