"""A type-1 checkbox popup's BOX, LIST and RING on the real bytes, end to end (fix 14b; the ring: fixes 16-18).

Vanilla builds the popup box and the list window from ONE [+0x5c] (BasePop_calculate_dimensions 0x603BE0..0x603C19:
box = [+0x5c] + trim; FUN_0060e800: GraphicWin_init w = [+0x5c]), so the row bars fill the box content.  Fix 14 put
the list on floor(vanilla [+0x5c] * g/16) = s(657) (thunk_list_fill_width v3) but left the box on s(xs) = s(660)
(thunk_scale_boxw v6): the bars stopped 8 px short of the box on the right at 4K.  thunk_scale_boxw v7 scales the
same vanilla [+0x5c] (law scaling_laws.itemlist_box_term_native, helper t_boxw_t1_term).

The chain, run on a copy of the .bak with the whole patch set applied (and on the pristine .bak for g = 16):
  * Popup_calculate_dimensions 0x404B10 (defaults, box_margin_scale) -> BasePop_calculate_dimensions 0x603800 ->
    Dialog_dims_dispatch -> OptionList_calc_reserve 0x60ED10 (thunk_rowgap) -> the box at 0x603D82 (t_dp_boxw_gate ->
    thunk_scale_boxw) -> g_popup_dialog_x [0x9B8CEC] (0x604292), run twice (the re-layout pass);
  * Popup_on_draw_background 0x405F8A..the ring draw (the title chain and thunk_pf_title_stash -> 0x406238
    thunk_content_frame -> thunk_pf_union_align -> thunk_d5a0_center: the ring rect) -- AT 0x602B49, i.e. BEFORE
    the attach: BasePop_exec_3 redraws the popup there (thunk_popup_edge_anchor -> jmp [vtbl+0x30] 0x404B00 ->
    BasePop_on_redraw 0x604AB0 -> call [vtbl+0x180] @0x604B0F = Popup_on_draw_background), while Dialog[+0x5c]
    still holds OptionList_calc_reserve's measured width;
  * BasePop_exec_3's attach slice 0x602B50..0x602C03 (t_dp_childx_gate -> Dialog_set_type -> FUN_0060e800 ->
    thunk_list_fill_width -> GraphicWin_init, stubbed: its args are the list window);
  * the background AGAIN (standing in for any later full redraw, which reads the post-attach [+0x5c]);
  * the button row: BasePop_exec_3 0x602C1B..0x602C6A (y = box_h - footer - pad - btn_h, the btnrow_center detour
    at 0x602C49, the popup's vtbl+0x178 = Popup_on_adjust_button_placement 0x405050: *y += 3).
Leaf engine primitives (text metrics, fonts, colours, the box draws themselves) are stubbed.  The row bar is
[list x + [+0x40], + [+0x64]) (the row painter FUN_0060f030: x = ([+0x64] + gap) * col + [+0x40]).

Asserted, for the type-1 census lists (#RULES, #BASEWARNINGS, #GOVOPTIONS, #SCENRULES, #SCENVICTORY, #ASSEMBLEGROUP,
#AIEDITOR, #AIEDITOR2, #EDITVEH, Thinker's #OPTIONS -- each with its own #xs) in the flat style with the console hidden
(margins 10/12) and shown (33/67) and the ornate style (19/21):
  * g = 16 (1024x768, 1366x768): box, margins, dialog x, list window args and fields == the pristine .bak's;
  * g in 17..40 and the real screens: box content (box - margins - 2 padx) == list window w == [+0x5c] == [+0x64]
    == floor((xs - 3) g/16) == vanilla x g/16 (xs = #xs x1.5, the engine's W > 1023 factor; 657 for #xs 440), and
    the list starts at the scaled left margin, so the bar spans the box content exactly.
  * the RING (user decision "Hug the list": fix 16 l/r, fix 17 t/b, fix 18 r in the engine's call order; laws
    scaling_laws.itemlist_ring_hug / itemlist_ring_list_r), at BOTH draw points (0x602B49 before the attach, and
    after it): g = 16 -> the pristine ring, whole rect, in every layout, = the list window / D -+ 3 on every side;
    g > 16 -> l = list x - fl(3g/16), r = list x + list w + fl(3g/16) - 1 with the LIST WINDOW taken from the
    GraphicWin_init args, t/b = D.t - fl(3g/16) / D.b + fl(3g/16) - 1 (the band map paints [l, r] x [t, b]
    inclusive): drawn insets T == B == L == R == fl(3g/16), channels fl(3g/16) - K, in the flat, slide and ornate
    families.  D.r is NOT the bar at the first draw: it is D.l + calc_reserve's measured [+0x5c] (the device text
    at g > 16).  Fixes 16/17 hugged D.r; this harness then ran the background AFTER the attach (post-attach
    [+0x5c] = the list), so it passed while the game drew the ring halfway across the rows (4K R 3052 vs 3804).
  * the 7 real in-game shots (2026-10-22, deployed b0464831) as goldens: the calibrated chain (the shot's longest
    row width and line height) reproduces each v16 ring exactly and the list right edge each shot measured; v17
    puts the ring on that list window -+ fl(3g/16).  The shipped v16, rebuilt from the v17 source, is the mutant
    and must fail here.
NB Popup_calculate_dimensions ADDS PopupDialogState * 10000 to [+0x30ac] (0x404C1E..0x404C35); measure() restores
the pre-calc value before the re-layout pass, else an ornate popup reads 120000 (outside every band -- the fix-14b
harness's "slide 5/90" and "ornate 5/10" rings were that artefact; live Pause dumps show 60000).
Skips (does not fail) if unicorn / pefile are absent.
"""
from __future__ import annotations

import hashlib
import re
import struct
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI,
    UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_pf_align as PF  # noqa: E402
import scaling_laws as SL  # noqa: E402

SW, G, HWND = 0x9B7B1C, 0x668740, 0x9B7B28
DLG_X = 0x9B8CEC                                  # g_popup_dialog_x, written at 0x604292
STYLE, IFACE_TOP, IFACE_STACK, CONSOLE_OBJ = 0x6A721C, 0x7D392C, 0x7AE778, 0x9156B0
POPUP_CALC, BOXW_RESUME = 0x404B10, 0x603D88
ATTACH_FROM, ATTACH_TO = 0x602B50, 0x602C03
BG_FROM, RING_RET = 0x405F8A, 0x40623D
BTN_FROM, BTN_TO, BTN_PLACEMENT = 0x602C1B, 0x602C6A, 0x405050
GW_INIT, TEXT_W, TEXT_H, LINE_H, CONSOLE_VIS, STRLEN = 0x5D4EF0, 0x5DC790, 0x5DCA80, 0x5DCAB0, 0x5F7E90, 0x6453E0
BOX_SPRITE, D5A0 = 0x5E2DD3, 0x78D5A0
UNION_RECT_IAT, IAT_66931C = 0x669328, 0x66931C
HEAP, STACK, SENT, STUBS = 0x20000000, 0x10000000, 0x0DEAD000, 0x0BEEF000
IV3 = 0xBA0                                       # the measured virtual-base offset of the popup's Dialog
XS, CHECKBOX_W = 660, 11                          # #xs 440 x1.5 (engine, W > 1023); the checkbox sprite

# (rows, longest native row text, #xs) -- xscript.txt (Thinker's #OPTIONS: refs/thinker/docs/modmenu.txt), the longest
# row in arialn.ttf synthetic bold at g = 16 (g_pf0; test_scaling_list_fill_width._row_width)
POPUPS = {"#RULES": (18, 380, 440), "#BASEWARNINGS": (17, 293, 440), "#GOVOPTIONS": (19, 572, 440),
          "#SCENRULES": (15, 327, 440), "#SCENVICTORY": (13, 354, 420), "#ASSEMBLEGROUP": (11, 290, 440),
          "#AIEDITOR": (11, 393, 400), "#AIEDITOR2": (13, 206, 400), "#EDITVEH": (7, 349, 480),
          "#OPTIONS": (12, 362, 480)}
# (PopupDialogState, console visible): flat + console hidden (margins 10/12: the main menu), flat + console shown
# (33/67: in game), ornate (19/21)
LAYOUTS = ((0, 0), (0, 1), (6, 0))
REAL = ((3840, 2160), (2560, 1440), (1920, 1080), (1600, 1200), (1600, 900), (1366, 768), (1024, 768))


def _sym():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return dict(ap.build_symbol_table(symbols, caves))


SYM = _sym()


@lru_cache(maxsize=None)
def _image(data: bytes):
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    img = bytes(pe.get_memory_mapped_image())
    size = (max(len(img), pe.OPTIONAL_HEADER.SizeOfImage) + 0xFFF) & ~0xFFF
    pe.close()
    return ib, size, img


def _r(uc, a):
    return struct.unpack("<i", bytes(uc.mem_read(a, 4)))[0]


def _w(uc, a, v):
    uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


class Chain:
    """One type-1 checkbox popup (titled, no art, no body text) in a fresh copy of the image."""

    def __init__(self, data: bytes, baked: bool, w: int, h: int, g: int, rows_text_dev, style=0, console=0, xs=XS,
                 line_h=None, union_code=None):
        ib, size, img = _image(data)
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, size)
        uc.mem_write(ib, img)
        for base, n in ((HEAP, 0x200000), (STACK - 0x20000, 0x40000), (SENT, 0x1000), (STUBS, 0x1000)):
            uc.mem_map(base, n)
        self.top, self.g, self.console, self.xs = HEAP, g, console, xs
        self.line_h = line_h                                        # calibration: the shot's font line height
        self.union_code = union_code                                # (va, bytes): a mutant union the hook enters
        if union_code:
            uc.mem_map(union_code[0] & ~0xFFF, 0x1000)
            uc.mem_write(union_code[0], union_code[1])
        for a, v in ((SW, w), (SW + 4, h), (G, g), (STYLE, style), (IFACE_TOP, 0), (IFACE_STACK, 0), (HWND, 1),
                     (UNION_RECT_IAT, STUBS + 0x10), (IAT_66931C, STUBS + 0x20)):
            _w(uc, a, v)
        self.vstub = STUBS + 0x30                                   # every vfunc the slices reach: `ret`, 0 args
        uc.mem_write(self.vstub, b"\xC3")
        self.gw, self.text_w, self.ring, self.box_at_site = [], {}, None, None
        stubs = {0x5DACB0: 4, 0x5DACE0: 4, 0x5DAD10: 4, 0x5DAD40: 4, 0x5DAC70: 4,     # colours, Buffer_set_font
                 LINE_H: 0, TEXT_H: 0, TEXT_W: 1, 0x5DC360: 2, 0x5DDDA0: 2, 0x5DDDE0: 1, 0x5DDEF0: 0,
                 CONSOLE_VIS: 0, STRLEN: 0, 0x5DD130: 3, GW_INIT: 9, BOX_SPRITE: 2, STUBS + 0x10: 3, STUBS + 0x20: 1}
        self.draw_stubs = {BOX_SPRITE}
        if baked:
            for k in ("thunk_box_thick", "thunk_box_thick_flat", "thunk_box_thick_hollow",
                      "thunk_box_thick_hollow_flat", "thunk_box_thick_devfill"):
                stubs[SYM[k]] = 2
                self.draw_stubs.add(SYM[k])
        self.stop_at = SYM["thunk_d5a0_center"] if baked else None
        self.union_at = SYM["thunk_pf_union_align"] if baked else None
        self.local = self.d_rect = None
        self.frames = []                                            # frame draws before the ring: the title band
        self.stubs = stubs
        for va in list(stubs) + [BOXW_RESUME] + ([self.stop_at, self.union_at] if baked else []):
            uc.hook_add(UC_HOOK_CODE, self._hook, begin=va, end=va)
        self._build(rows_text_dev)
        _w(uc, CONSOLE_OBJ, self.alloc(0x10))

    def alloc(self, n):
        a = self.top
        self.top += (n + 0xF) & ~0xF
        return a

    def _build(self, rows_text_dev):
        uc = self.uc
        p = self.p = self.alloc(0x3400)
        vt = self.alloc(0x400)
        for k in range(0, 0x400, 4):
            _w(uc, vt + k, self.vstub)
        title = self.alloc(32)
        uc.mem_write(title, b"CUSTOMIZE GAME RULES\0")
        font = self.alloc(0x40)
        _w(uc, font + 0x10, 15)
        for off, v in ((0, vt), (0xA3C, p), (0xA48, title), (0x2350, 1), (0x21CC, -1), (0xA44, -1), (0xA18, -5),
                       (0xA1C, -5), (0x20F4, 1), (0x316C, font), (0x3104, 1), (0x3108, 1)):
            _w(uc, p + off, v)
        # the Dialogs multi-object at +0x21d0, its type-1 element at +0x2228 (virtual-base offsets as measured)
        vb1, vb2 = self.alloc(0x10), self.alloc(0x10)
        for a, v in ((p + 0x21D0, vb1), (vb1 + 4, 0x400), (vb1 + 8, IV3), (p + 0x2228, vb2), (vb2 + 4, 0x400 - 0x58),
                     (vb2 + 8, IV3 - 0x58), (p + 0x21D0 + 0x400, vt)):
            _w(uc, a, v)
        d = self.d = p + 0x21D0 + IV3
        spr = self.alloc(0x40)
        uc.mem_write(spr + 0x18, struct.pack("<ii", CHECKBOX_W, CHECKBOX_W))
        uc.mem_write(p + 0x2228 + 0x10, struct.pack("<II", spr, spr))
        _w(uc, d + 0x2C, self.xs)
        _w(uc, d + 0x4C, 1)
        nodes = [self.alloc(0x20) for _ in rows_text_dev]
        for i, nd in enumerate(nodes):
            item, txt = self.alloc(0x10), self.alloc(0x10)
            self.text_w[txt] = rows_text_dev[i]
            _w(uc, item + 4, txt)
            uc.mem_write(nd + 8, struct.pack("<II", item, nodes[(i + 1) % len(nodes)]))
        uc.mem_write(d + 0xC4, struct.pack("<IIII", 1, nodes[-1], len(nodes), len(nodes) - 1))

    def _hook(self, u, addr, _size, _ud):
        if addr == BOXW_RESUME:
            self.box_at_site = _r(u, self.p + 0x30BC)
            return
        esp = u.reg_read(UC_X86_REG_ESP)
        if addr == self.union_at:                                   # bake: the engine local + its dialog rect D
            self.local = struct.unpack("<4i", bytes(u.mem_read(_r(u, esp + 4), 16)))
            self.d_rect = struct.unpack("<4i", bytes(u.mem_read(u.reg_read(UC_X86_REG_EBP) - 0x44, 16)))
            if self.union_code:                                     # the mutant runs in the real union's place
                u.reg_write(UC_X86_REG_EIP, self.union_code[0])
            return
        if addr == self.stop_at:                                    # bake: the ring rect handed to the drawer
            self.ring = struct.unpack("<4i", bytes(u.mem_read(_r(u, esp + 4), 16)))
            u.emu_stop()
            return
        n = self.stubs[addr]
        args = struct.unpack("<%dI" % n, bytes(u.mem_read(esp + 4, 4 * n))) if n else ()
        ret = 0
        if addr == GW_INIT:
            self.gw.append(args)
        elif addr == TEXT_W:
            ret = self.text_w.get(args[0], 0)
        elif addr in (TEXT_H, LINE_H):
            ret = self.line_h if self.line_h is not None else 15 * max(self.g, 16) // 16
        elif addr == CONSOLE_VIS:
            ret = self.console
        elif addr == STRLEN:
            ret = 20
        elif addr == STUBS + 0x10:                                  # UnionRect(dst, a, b)
            a = struct.unpack("<4i", bytes(u.mem_read(args[1], 16)))
            b = struct.unpack("<4i", bytes(u.mem_read(args[2], 16)))
            u.mem_write(args[0], struct.pack("<4i", min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])))
            ret = 1
        elif addr in self.draw_stubs and self.stop_at is None and _r(u, esp) == RING_RET and args[1] == D5A0:
            self.ring = struct.unpack("<4i", bytes(u.mem_read(args[0], 16)))   # pristine: the ring IS this draw
            self.d_rect = struct.unpack("<4i", bytes(u.mem_read(u.reg_read(UC_X86_REG_EBP) - 0x44, 16)))
            u.emu_stop()
            return
        if addr in self.draw_stubs and self.ring is None:
            self.frames.append(struct.unpack("<4i", bytes(u.mem_read(args[0], 16))))
        u.reg_write(UC_X86_REG_EAX, ret & 0xFFFFFFFF)
        u.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * n)
        u.reg_write(UC_X86_REG_EIP, _r(u, esp) & 0xFFFFFFFF)

    def calc(self):
        uc, p, d = self.uc, self.p, self.d
        sp = STACK - 4
        _w(uc, sp, SENT)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_ECX, p)
        uc.emu_start(POPUP_CALC, SENT, count=3_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == SENT and uc.reg_read(UC_X86_REG_EAX) == 0
        f = {k: _r(uc, p + o) for k, o in (("box", 0x30BC), ("boxh", 0x30C0), ("padx", 0x30E0), ("ml", 0x30F0),
                                           ("mr", 0x30F4), ("cw", 0x30D8), ("btn_w", 0x30CC))}
        f.update(box_site=self.box_at_site, dlg_x=_r(uc, DLG_X), d5c_calc=_r(uc, d + 0x5C))
        return f

    def attach(self):
        uc = self.uc
        uc.reg_write(UC_X86_REG_ESP, STACK - 0x400)
        uc.reg_write(UC_X86_REG_EBP, STACK - 0x100)
        uc.reg_write(UC_X86_REG_ESI, self.p)
        uc.emu_start(ATTACH_FROM, ATTACH_TO, count=2_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == ATTACH_TO and len(self.gw) == 1, hex(uc.reg_read(UC_X86_REG_EIP))
        a = self.gw[0]
        return dict(gw=a, list_x=a[0], list_w=a[2], d5c=_r(uc, self.d + 0x5C), d64=_r(uc, self.d + 0x64),
                    margin=_r(uc, self.d + 0x40), dialog=bytes(uc.mem_read(self.d, 0x100)))

    def background(self, style):
        """0x405F8A (title present) .. the ring draw; the popup window rect +0x474 = (0, 0, box, box_h).
        Runs at each point the engine draws the background (0x602B49 before the attach, any redraw after it)."""
        self.ring, self.frames, self.d_rect, self.local = None, [], None, None
        uc, p = self.uc, self.p
        uc.mem_write(p + 0x474, struct.pack("<4i", 0, 0, _r(uc, p + 0x30BC), _r(uc, p + 0x30C0)))
        ebp = STACK - 0x1000
        uc.mem_write(ebp - 0x44, bytes(0x44))
        _w(uc, ebp - 4, style)
        for r, v in ((UC_X86_REG_EBP, ebp), (UC_X86_REG_ESP, ebp - 0x44 - 12), (UC_X86_REG_ESI, p),
                     (UC_X86_REG_EDI, p + 0x444), (UC_X86_REG_EBX, p + 0x474), (UC_X86_REG_EAX, _r(uc, p + 0xA48))):
            uc.reg_write(r, v & 0xFFFFFFFF)
        uc.emu_start(BG_FROM, RING_RET, count=2_000_000)
        assert self.ring is not None, hex(uc.reg_read(UC_X86_REG_EIP))
        return dict(ring=self.ring, d_rect=self.d_rect, local=self.local, frames=list(self.frames))

    def buttons(self):
        """The button-row top y (window-local) from the real bytes, after background()."""
        uc, p = self.uc, self.p
        _w(uc, _r(uc, p) + 0x178, BTN_PLACEMENT)                   # the popup's real button-placement vfunc
        sp = STACK - 0x800
        uc.mem_write(sp, bytes(0x80))
        for r, v in ((UC_X86_REG_ESP, sp), (UC_X86_REG_EBP, STACK - 0x100), (UC_X86_REG_ESI, p)):
            uc.reg_write(r, v)
        uc.emu_start(BTN_FROM, BTN_TO, count=200_000)
        assert uc.reg_read(UC_X86_REG_EIP) == BTN_TO and uc.reg_read(UC_X86_REG_ESP) == sp
        return _r(uc, sp + 0x14)


def measure(data: bytes, baked: bool, w: int, h: int, tag: str, style: int, console: int, longest_dev=None,
            line_h=None, union_code=None) -> dict:
    """The popup in BasePop_exec_3's own order: calc, calc (the re-layout), the background at 0x602B49 (the
    redraw BEFORE the attach), the attach 0x602B50.., the background again (any later redraw), the button row.
    `longest_dev` / `line_h`: the calibration of a real shot (its longest row's device width, its line height)."""
    g = SL.popup_g(w, h)
    rows, native, xs = POPUPS[tag]
    xs = xs * 3 // 2 if w > 1023 else xs                            # the engine's #xs x1.5 above 1023 px
    if longest_dev is None:
        text = [native, native * 3 // 4, native // 2] * (rows // 3) + [native // 3] * (rows % 3)
        dev = [t * max(g, 16) // 16 for t in text]
    else:
        L = longest_dev
        dev = [L, L * 3 // 4, L // 2] * (rows // 3) + [L // 3] * (rows % 3)
    c = Chain(data, baked, w, h, g, dev, style, console, xs, line_h=line_h, union_code=union_code)
    p30ac = _r(c.uc, c.p + 0x30AC)
    out = c.calc()
    _w(c.uc, c.p + 0x30AC, p30ac)                                   # the engine's += state * 10000 must not double
    again = c.calc()                                                # Popup_calc runs again on a re-layout
    assert {k: again[k] for k in ("box", "dlg_x", "ml", "mr")} == {k: out[k] for k in ("box", "dlg_x", "ml", "mr")}
    pre = c.background(style)                                       # 0x602B49: the redraw BEFORE the attach
    out.update(c.attach())
    post = c.background(style)                                      # any later full redraw
    btn_y = c.buttons()
    bar_l = out["list_x"] + out["margin"]
    bar_r = bar_l + out["d64"]
    win_l, win_r = out["list_x"], out["list_x"] + out["list_w"]     # the list window: GraphicWin_init's args
    incl = 1 if baked and g > 16 else 0                         # g > 16: the band map paints col r / row b (inclusive)
    k = SL.stroke_width(g) if incl else 1
    for pt in (pre, post):
        l, t, r, b = pt["ring"]
        dl, dt, dr, db = pt["d_rect"]
        pt.update(
            # DRAWN insets (stroke outer edge -> the list window's l/r, D's t/b) and channels (stroke inner edge)
            drawn=(win_l - l, dt - t, r + incl - win_r, b + incl - db),
            chan=(win_l - (l + k), dt - (t + k), (r + incl - k) - win_r, (b + incl - k) - db),
            # clear rows between the title band's last painted row and the ring's first, and between the ring's
            # last painted row and the button row
            title_clear=t - (max(f[3] for f in pt["frames"]) - (1 - incl)) - 1, btn_clear=btn_y - (b - (1 - incl)) - 1)
    l, t, r, b = pre["ring"]
    out.update(g=g, xs=xs, bar=(bar_l, bar_r), win=(win_l, win_r), pre=pre, post=post, incl=incl, k=k,
               ring=pre["ring"], d_rect=post["d_rect"], local=post["local"],
               inset_l=bar_l - l, inset_r=r - bar_r, drawn_l=bar_l - l, drawn_r=r + incl - bar_r,
               drawn_d=pre["drawn"], chan_d=pre["chan"], title_clear=pre["title_clear"], btn_clear=pre["btn_clear"],
               p30ac=_r(c.uc, c.p + 0x30AC), content=out["box"] - out["ml"] - out["mr"] - 2 * out["padx"])
    return out


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return baked_exe.read_bytes()


def _screen(g: int):
    """A screen whose popup_g is g (64g x 48g: W > 1023, so #xs takes the engine's x1.5)."""
    assert SL.popup_g(64 * g, 48 * g) == g
    return 64 * g, 48 * g


# ==== g = 16: pristine ===============================================================================================
@pytest.mark.parametrize("w, h", ((1024, 768), (1366, 768)))
def test_g16_box_and_list_are_pristine(baked, bak_bytes, w, h):
    keys = ("box", "boxh", "padx", "ml", "mr", "cw", "btn_w", "box_site", "dlg_x", "d5c_calc", "gw", "dialog")
    for tag in POPUPS:
        for style, console in LAYOUTS:
            a = measure(baked, True, w, h, tag, style, console)
            v = measure(bak_bytes, False, w, h, tag, style, console)
            assert {k: a[k] for k in keys} == {k: v[k] for k in keys}, (tag, w, h, style, console)
            assert a["ring"][0] == v["ring"][0] and v["inset_l"] == v["inset_r"] == 3     # vanilla: the ring hugs
            assert v["content"] == v["list_w"] == v["xs"] - 3                             # the list, 3 / 3


# ==== g > 16: the box content IS the list window =====================================================================
def _check(o: dict, tag, ctx):
    g = o["g"]
    van = ((o["xs"] - 3) * g) >> 4                                  # vanilla [+0x5c] = xs - 3 (gap) x g/16
    assert o["list_w"] == o["d5c"] == o["d64"] == van, (tag, ctx, o["list_w"], o["d5c"], o["d64"], van)
    assert o["content"] == o["list_w"], (tag, ctx, "box content", o["content"], "list", o["list_w"])
    assert o["padx"] == 0 and o["box_site"] == van, (tag, ctx, o["box_site"])   # Popup_calc: [+0x21c0] = 0
    assert o["list_x"] == o["dlg_x"] == o["ml"] + o["padx"] + o["cw"], (tag, ctx)
    assert o["bar"] == (o["ml"] + o["padx"], o["box"] - o["mr"] - o["padx"]), (tag, ctx, o["bar"], o["box"])


@pytest.mark.parametrize("g", range(17, 41))
def test_box_content_is_the_list_window_every_g(baked, g):
    w, h = _screen(g)
    for tag in POPUPS:
        for style, console in LAYOUTS:
            _check(measure(baked, True, w, h, tag, style, console), tag, (g, style, console))


@pytest.mark.parametrize("w, h", REAL[:5])
def test_box_content_is_the_list_window_real_screens(baked, w, h):
    for tag in POPUPS:
        for style, console in LAYOUTS:
            o = measure(baked, True, w, h, tag, style, console)
            _check(o, tag, (w, h, style, console))
            # the row text still fits its bar (vanilla's own calc measure, device font, + the checkbox indent)
            assert o["d5c_calc"] <= o["list_w"], (tag, w, h, o["d5c_calc"], o["list_w"])


def test_4k_customize_rules_golden(baked):
    """Customize Game Rules at 4K, main menu (flat, console hidden): box = s(10) + s(657) + s(12) = 25 + 1642 + 30."""
    o = measure(baked, True, 3840, 2160, "#RULES", 0, 0)
    assert (o["box"], o["ml"], o["mr"], o["content"], o["list_w"], o["bar"]) == (1697, 25, 30, 1642, 1642, (25, 1667))
    # fix 14 (box s(660) = 1650): box 1705, bar (25, 1667), the bar stopping 8 px short of the content's right edge


# ==== the RING (fix 16, user decision "Hug the list") ================================================================
# every popup family a type-1 list can draw in: flat (main menu: console hidden 10/12; in game: shown 33/67), slide 5,
# ornate 6 (base screen / scenario editor: PopupDialogState 6) with the console hidden and shown
RING_LAYOUTS = ((0, 0), (0, 1), (5, 0), (5, 1), (6, 0), (6, 1))
VAN_CLEAR = (7, 12)             # pristine g = 16, every census popup and layout: title band -> ring, ring -> buttons
G16 = ((1024, 768), (1366, 768), (1280, 720))


@pytest.mark.parametrize("w, h", G16)
def test_g16_ring_is_the_pristine_ring(baked, bak_bytes, w, h):
    """g = 16 draws the engine's own ring, whole rect, in every layout: the v5-v14 native-fix arm moved the
    right stroke to boxw - 7 (in game 1024x768: 750 where vanilla draws 693; main menu 672 vs 670; ornate 690 vs
    679).  Its premise -- vanilla rows under the stroke -- is false on the pristine bytes: bars end 3 px before
    the ring's right line (stroke col r - 1 two px clear) in every layout here."""
    for tag in POPUPS:
        for style, console in RING_LAYOUTS:
            a = measure(baked, True, w, h, tag, style, console)
            v = measure(bak_bytes, False, w, h, tag, style, console)
            assert a["g"] == 16
            for pt in ("pre", "post"):                                  # both draw points, bake == pristine
                assert a[pt]["ring"] == v[pt]["ring"] == v["pre"]["ring"], (tag, w, h, style, console, pt)
                assert v[pt]["drawn"] == (3, 3, 3, 3) and v[pt]["chan"] == (2, 2, 2, 2), (tag, pt, v[pt]["drawn"])
            assert v["inset_l"] == v["inset_r"] == 3 and v["ring"][2] - 1 - v["bar"][1] == 2
            assert v["pre"]["d_rect"] == v["post"]["d_rect"]           # vanilla: calc's [+0x5c] IS the list w
            assert (v["title_clear"], v["btn_clear"]) == (a["title_clear"], a["btn_clear"]) == VAN_CLEAR
            assert a["p30ac"] == style * 10000


def _check_ring(o: dict, tag, ctx):
    """At BOTH draw points the ring is the list window -+ fl(3g/16) (t/b: D -+ fl(3g/16)); the window comes from
    the GraphicWin_init args, never from D (whose r is calc_reserve's width at the first draw)."""
    g = o["g"]
    p, k = SL.popup_pad(3, g), SL.stroke_width(g)
    win_l, win_r = o["win"]
    assert o["bar"] == o["win"], (tag, ctx, o["bar"], o["win"])                  # the row bar IS the list window
    for pt in ("pre", "post"):
        q = o[pt]
        dl, dt, dr, db = q["d_rect"]
        assert dl == win_l, (tag, ctx, pt, q["d_rect"])
        assert tuple(q["ring"]) == SL.itemlist_ring_hug(win_l, dt, win_r, db, g) == \
            (win_l - p, dt - p, win_r + p - 1, db + p - 1), (tag, ctx, pt, q["ring"], o["win"], q["d_rect"])
        assert q["drawn"] == (p, p, p, p), (tag, ctx, pt, q["drawn"], p)         # T == B == L == R == fl(3g/16)
        assert q["chan"] == (p - k,) * 4 and p - k >= 1, (tag, ctx, pt, q["chan"])
        # the ring keeps clear of the title band and the button row (2026-10-24 W1A, tightened from "within one floor
        # of vanilla x g/16"): ring -> row = fl(12g/16) exactly (fix 25a, law popup_dialog_btn_span: one vanilla 12
        # span, scaled once); band -> ring == law popup_title_ring_clear exactly (fix 25b: the band's last painted
        # row is its half-open b - 1, law title_band_draw_rect; the span composes the content top, the hug inset and
        # the band end, each one floor of its own vanilla position)
        assert q["btn_clear"] == (VAN_CLEAR[1] * g) >> 4, (tag, ctx, pt, "ring -> row", q["btn_clear"])
        ornate = o["p30ac"] // 10000 in SL.ORNATE_POPUP_TYPES
        assert q["title_clear"] == SL.popup_title_ring_clear(g, ornate), \
            (tag, ctx, pt, "band -> ring", q["title_clear"], SL.popup_title_ring_clear(g, ornate))
    assert o["pre"]["ring"] == o["post"]["ring"], (tag, ctx)                      # one ring, whenever it is drawn
    assert o["drawn_l"] == o["drawn_r"] == p, (tag, ctx, o["drawn_l"], o["drawn_r"], p)
    # the mechanism: the first draw's D.r is calc_reserve's measured width, the later one's the list window, and
    # the law recovers the list's right edge from the first draw's D
    pre_d, post_d = o["pre"]["d_rect"], o["post"]["d_rect"]
    assert pre_d[2] - pre_d[0] == o["d5c_calc"] and post_d[2] - post_d[0] == o["list_w"], (tag, ctx, pre_d, post_d)
    assert pre_d[1] == post_d[1] and pre_d[3] == post_d[3], (tag, ctx, pre_d, post_d)
    assert SL.itemlist_ring_list_r(pre_d[0], pre_d[2], o["xs"], 0, 1, SL.dialog_row_margin(3, g), 0, 0, 2, g) \
        == win_r, (tag, ctx)


@pytest.mark.parametrize("g", range(17, 41))
def test_type1_ring_hugs_the_list_every_g(baked, g):
    """Every census popup and ring layout, with the harness text (native x g/16) and 15 % wider text (the
    font-metric sublinearity margin: the first draw's D.r follows the MEASURED text, the ring must not)."""
    w, h = _screen(g)
    for tag in POPUPS:
        for style, console in RING_LAYOUTS:
            for wide in (None, POPUPS[tag][1] * g * 115 // 1600):
                _check_ring(measure(baked, True, w, h, tag, style, console, longest_dev=wide), tag,
                            (g, style, console, wide))


@pytest.mark.parametrize("w, h", REAL[:5])
def test_type1_ring_hugs_the_list_real_screens(baked, w, h):
    for tag in POPUPS:
        for style, console in RING_LAYOUTS:
            _check_ring(measure(baked, True, w, h, tag, style, console), tag, (w, h, style, console))


def test_4k_ring_golden(baked):
    """4K, the two layouts the user sees: Customize Game Rules (main menu, flat, console hidden) and Governor /
    Announcements in game (flat, console shown).  v14 (fix 14b): ring 17 / 1680 and 74 / 1735 = drawn insets 8/14
    and 8/12 (both edges on the title inner); v15: L/R 7/7 with T/B = the engine local 5/6; v16: 7/7/7/7."""
    o = measure(baked, True, 3840, 2160, "#RULES", 0, 0)
    assert (o["bar"], o["ring"][0], o["ring"][2], o["drawn_l"], o["drawn_r"]) == ((25, 1667), 18, 1673, 7, 7)
    assert o["drawn_d"] == (7, 7, 7, 7) and o["chan_d"] == (5, 5, 5, 5), (o["drawn_d"], o["chan_d"])
    assert o["post"]["ring"] == o["pre"]["ring"]
    o = measure(baked, True, 3840, 2160, "#GOVOPTIONS", 0, 1)
    assert (o["bar"], o["ring"][0], o["ring"][2], o["drawn_l"], o["drawn_r"]) == ((82, 1724), 75, 1730, 7, 7)
    assert o["drawn_d"] == (7, 7, 7, 7), o["drawn_d"]
    assert o["post"]["ring"] == o["pre"]["ring"]


# ==== the 7 real in-game shots (fix 18) ===============================================================================
# (shot, w, h, tag, console, longest row device width, line height, the ring the shot shows (L, T, R, B inclusive,
# deployed v16 / lock b0464831), the list window's right edge the shot shows (exclusive)) -- measured from the shots
# (work\screenshots, ring colour 49,78,44; fix-18 investigation meas.py / runs.py); the longest row and the line
# height calibrated so the chain reproduces each shot's d5c_calc and ring height; None = the harness default
REAL_SHOTS = (
    ("4K Rules 20261022-204738", 3840, 2160, "#RULES", 0, 863, 50, (2149, 990, 3052, 2029), 3798),
    ("2560x1440 Rules 20261022-205306", 2560, 1440, "#RULES", 0, 694, 37, (1293, 578, 2023, 1343), 2529),
    ("1920x1080 Rules 20261022-205522", 1920, 1080, "#RULES", 0, None, 27, (991, 445, 1655, 1010), 1898),
    ("1600x900 Rules 20261022-210112", 1600, 900, "#RULES", 0, None, 22, (840, 388, 1502, 843), 1582),
    ("1366x768 Rules 20261022-210239", 1366, 768, "#RULES", 0, None, None, (689, 314, 1351, 715), 1349),
    ("1024x768 Rules 20261022-210432", 1024, 768, "#RULES", 0, None, None, (347, 314, 1009, 715), 1007),
    ("4K Governor 20261022-204855", 3840, 2160, "#GOVOPTIONS", 1, 1288, 50, (1089, 527, 2417, 1623), 2738),
)
# the predicted (fixed) ring per shot, screen space: the list window -+ fl(3g/16) (g = 16: the shot itself)
REAL_SHOT_FIXED = {"4K Rules 20261022-204738": (2149, 990, 3804, 2029),
                   "2560x1440 Rules 20261022-205306": (1293, 578, 2533, 1343),
                   "1920x1080 Rules 20261022-205522": (991, 445, 1901, 1010),
                   "1600x900 Rules 20261022-210112": (840, 388, 1584, 843),
                   "1366x768 Rules 20261022-210239": (689, 314, 1351, 715),
                   "1024x768 Rules 20261022-210432": (347, 314, 1009, 715),
                   "4K Governor 20261022-204855": (1089, 527, 2744, 1623)}

# the shipped v16 (lock b0464831): v17's source with the right-edge block reverted -- pinned to the v16 template
V16_TEMPLATE_MD5 = "457d74194a8fdb2860a4e0adbde2a002"
MUTANT_VA = 0x0C000000


@lru_cache(maxsize=None)
def _v16_union():
    src = re.sub(r"    /\* v17 \(fix 18\).*?keepdr:\n    pop  edx\n    pop  ebx\n", "    mov  eax, [ebp - 0x3c]\n",
                 PF.ASM_UNION, flags=re.S)
    # v18 (F34): the type-2 entry label and the container arm's type-2 test came after v16 -- strip them too
    src = re.sub(r"hug2:\n    /\* v18 \(F34\).*?\*/\n", "", src, flags=re.S)
    src = re.sub(r"    /\* v18 \(F34, law listbox_ring_takes_hug_arm\).*?je   hug2\n", "", src, flags=re.S)
    tmpl = PF.template(src, PF.UNION_VA)[1]
    assert hashlib.md5(tmpl.encode()).hexdigest() == V16_TEMPLATE_MD5, "the rebuilt mutant is not the shipped v16"
    return MUTANT_VA, bytes(ap.ByteTemplate(tmpl).resolve(MUTANT_VA, SYM))


def _drawn(o, pt):
    """The pt ring's inclusive drawn extents (window-local)."""
    l, t, r, b = o[pt]["ring"]
    return l, t, r - (1 - o["incl"]), b - (1 - o["incl"])


@pytest.mark.parametrize("shot", REAL_SHOTS, ids=[s[0] for s in REAL_SHOTS])
def test_real_shot_golden(baked, shot):
    """Each real shot, the calibrated chain, the engine's order.  Anchored on the shot's ring L/T (the popup's
    screen position): the v16 mutant's FIRST draw reproduces the shot's ring on all four sides and the list
    window's right edge lands where the shot shows it; v17 draws the ring on that window -+ fl(3g/16) at both
    draw points (g = 16: the shot, unchanged)."""
    name, w, h, tag, con, longest, lh, real, real_list_r = shot
    m = measure(baked, True, w, h, tag, 0, con, longest_dev=longest, line_h=lh, union_code=_v16_union())
    o = measure(baked, True, w, h, tag, 0, con, longest_dev=longest, line_h=lh)
    g, p = o["g"], (SL.popup_pad(3, o["g"]) if o["g"] > 16 else 3)
    pre16 = _drawn(m, "pre")
    ox, oy = real[0] - pre16[0], real[1] - pre16[1]
    sh = lambda r: (r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)  # noqa: E731
    assert sh(pre16) == real, (name, sh(pre16), real)                       # the bug, reproduced exactly
    assert o["win"][1] + ox == m["win"][1] + ox == real_list_r, (name, o["win"], ox)   # the shot's list right
    want = REAL_SHOT_FIXED[name]
    assert want == ((real[0], real[1], real_list_r + p - 1, real[3]) if g > 16 else real)
    assert sh(_drawn(o, "pre")) == sh(_drawn(o, "post")) == want, (name, sh(_drawn(o, "pre")), want)
    if g > 16:
        assert sh(pre16)[2] < want[2], "v16 drew the ring short of the rows"


@pytest.mark.parametrize("w, h", REAL[:5])
def test_v16_mutant_fails_in_the_engine_order(baked, w, h):
    """The shipped v16 in the engine's order: its first draw hugs calc_reserve's width and fails the ring check
    for every census popup on every real screen above g = 16 -- while its post-attach redraw hugs the list,
    which is all the fixes-16/17 harness (background after the attach) ever looked at."""
    killed = 0
    for tag in POPUPS:
        m = measure(baked, True, w, h, tag, 0, 0, union_code=_v16_union())
        assert m["post"]["ring"] == SL.itemlist_ring_hug(m["win"][0], m["post"]["d_rect"][1], m["win"][1],
                                                         m["post"]["d_rect"][3], m["g"])
        assert m["pre"]["ring"] != m["post"]["ring"], (tag, w, h)
        with pytest.raises(AssertionError):
            _check_ring(m, tag, (w, h, "v16"))
        killed += 1
    assert killed == len(POPUPS), (w, h, killed)
