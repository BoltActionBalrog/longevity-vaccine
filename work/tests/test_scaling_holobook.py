"""Law sweep for the retirement Holobook ("Welcome to the Planetary Archives"; scaling_laws "RETIREMENT HOLOBOOK").

The screen shares the Hall of Fame's frame and content geometry, so its scale and letterbox ARE the HOF's
(hof_scale_num / hof_letterbox); every geometry value is vanilla x num/16 through mon_s with the identity at
num == 16.  Fonts scale the size vanilla RENDERS (find_font's snap of the request, user decision 2026-11-15) and
line breaks are vanilla's (user decision 2026-11-15): the GDI checks below measure with the game's own arialn.ttf
registered alone (feedback_game_font_synthetic_bold) and the engine's word-fit (hb_line_breaks = the decompiled
Font_find_line_break_l 0x619370), and prove that vanilla's lines reproduce the pristine shot and still fit the
scaled boxes at every num the law produces.  The asm ports are checked in test_holobook_asm_parity.py.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import functools
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

RES = {(3840, 2160): (45, (480, 0)), (2560, 1440): (30, (320, 0)), (1920, 1080): (22, (256, 12)),
       (1600, 1200): (25, (0, 0)), (1280, 1024): (20, (0, 32)), (1024, 768): (16, (0, 0))}
NUMS = list(range(17, SL.HOF_NUM_MAX + 1))
GAME = config.game_dir(required=False)


def test_scale_is_the_hall_of_fame_law():
    for (sw, sh), (num, box) in RES.items():
        assert SL.hb_scale_num(sw, sh) == num
        if num > 16:
            assert SL.hb_letterbox(sw, sh, num) == box
        assert SL.hb_armed(sw, sh, 1) == (num > 16)
    assert not SL.hb_armed(3840, 2160, 0)                       # the 800x600 layout is never armed
    for sw in range(640, 7681, 97):
        for sh in range(480, 4321, 61):
            assert SL.hb_scale_num(sw, sh) == SL.hof_scale_num(sw, sh)


def test_identity_at_native():
    assert SL.hb_content_rect(16, 0, 0) == SL.HB_CONTENT_NATIVE
    assert SL.hb_rects(16, 0, 0) == SL.HB_RECTS_NATIVE
    l, t, r, b = SL.HB_RECTS_NATIVE[SL.HB_BUTTON]
    assert SL.hb_button_rect(16, 0, 0) == (l, t, r - l, b - t) == (768, 649, 120, 20)
    assert (SL.hb_list_gap(16), SL.hb_list_bottom(16)) == (6, 10)
    for page, (x0, y0, w, h) in SL.HB_CAPTIONS.items():
        assert SL.hb_caption_rect(page, 16, 0, 0) == (x0 + 119, y0 + 80, x0 + w + 119, y0 + h + 80)


def test_fonts_scale_what_vanilla_renders():
    native = {t: SL.hb_font(t, 16) for t in SL.HB_FONT_TABLES}
    assert native == {0x8A40E4: ("Arial Narrow", 24, 1), 0x8A40E8: ("Arial Narrow", 18, 3),
                      0x8A40E0: ("Arial", 12, 0), 0x8A40F0: ("Arial Narrow", 32, 1)}   # glyph-exact on the pristine
    for num in NUMS:
        for t in SL.HB_FONT_TABLES:
            name, size, style = SL.hb_font(t, num)
            n16 = native[t]
            assert (name, style) == (n16[0], n16[2])                     # the face never changes with num
            assert size == (n16[1] * num) // 16                          # the snapped size, never the request


def _elements(num, lx, ly):
    art = (lx, ly, lx + SL.mon_s(1024, num), ly + SL.mon_s(768, num))
    els = [("content", SL.hb_content_rect(num, lx, ly))]
    els += [(f"rect{k}", r) for k, r in enumerate(SL.hb_rects(num, lx, ly))]
    x, y, w, h = SL.hb_button_rect(num, lx, ly)
    els.append(("button", (x, y, x + w, y + h)))
    els += [(f"caption{p}", SL.hb_caption_rect(p, num, lx, ly)) for p in SL.HB_CAPTIONS]
    return art, els


@pytest.mark.parametrize("num", NUMS)
def test_every_element_is_vanilla_times_scale(num):
    art, els = _elements(num, 0, 0)
    content = SL.hb_content_rect(num, 0, 0)
    nat = dict(_elements(16, 0, 0)[1])
    for name, (l, t, r, b) in els:
        assert art[0] <= l < r <= art[2] and art[1] <= t < b <= art[3], name
        if name != "content":
            assert content[0] <= l and r <= content[2] and content[1] <= t and b <= content[3], name
        nl, nt, nr, nb = nat[name]
        for dev, v in ((l, nl), (t, nt), (r, nr), (b, nb)):              # within 1 px of vanilla x num/16 (abs)
            assert abs(dev - v * num / 16) <= 1.0, (name, dev, v)
    x, y, w, h = SL.hb_button_rect(num, 0, 0)
    assert (w, h) == (SL.mon_s(120, num), SL.mon_s(20, num))
    assert SL.hb_imm_ok(num)


def test_letterbox_keeps_everything_on_screen():
    for sw in range(1024, 7681, 53):
        for sh in range(768, 4321, 47):
            num = SL.hb_scale_num(sw, sh)
            if num <= 16:
                continue
            lx, ly = SL.hb_letterbox(sw, sh, num)
            art, els = _elements(num, lx, ly)
            assert 0 <= art[0] and art[2] <= sw and 0 <= art[1] and art[3] <= sh, (sw, sh)


# ---- the vanilla-breaks lever, measured with real GDI and the game's arialn.ttf ----------------------------------
class _Gdi:
    def __init__(self):
        g = ctypes.windll.gdi32
        g.AddFontResourceExA.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_void_p]
        g.CreateFontIndirectA.restype = ctypes.c_void_p
        g.CreateFontIndirectA.argtypes = [ctypes.c_void_p]
        g.SelectObject.restype = ctypes.c_void_p
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.CreateCompatibleDC.restype = ctypes.c_void_p
        g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        g.GetTextExtentPoint32A.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        assert g.AddFontResourceExA(os.path.join(str(GAME), "arialn.ttf").encode("mbcs"), 0x10, None) > 0
        self.g, self.dc, self.fonts = g, g.CreateCompatibleDC(None), {}

    def width_fn(self, name, size, style):
        key = (name, size, style)
        if key not in self.fonts:
            lf = (ctypes.c_byte * 60)()
            ctypes.memmove(lf, ctypes.byref(W.LONG(-size)), 4)                       # lfHeight
            ctypes.memmove(ctypes.byref(lf, 16), ctypes.byref(W.LONG(700 if style & 1 else 0)), 4)   # lfWeight
            lf[20], lf[21], lf[24] = (style >> 1) & 1, (style >> 2) & 1, 7             # italic, underline, outprec
            ctypes.memmove(ctypes.byref(lf, 28), name.encode(), len(name))
            self.fonts[key] = self.g.CreateFontIndirectA(ctypes.byref(lf))
        h = self.fonts[key]

        @functools.lru_cache(maxsize=None)
        def w(s):
            self.g.SelectObject(self.dc, h)
            sz = W.SIZE()
            self.g.GetTextExtentPoint32A(self.dc, s.encode("latin-1"), len(s), ctypes.byref(sz))
            return sz.cx
        return w


@pytest.fixture(scope="module")
def gdi():
    if GAME is None or not (Path(GAME) / "arialn.ttf").exists():
        pytest.skip("the game's arialn.ttf is not present")
    return _Gdi()


TITLE = "Welcome to the Planetary Archives"
INTRO = ("Following your retirement, the people collect your most memorable writings into a holobook of wisdom "
         "entitled:")
LEADERS = (("CEO", "Morgan"), ("Prime Function", "Aki Zeta-Five"), ("Sister", "Miriam Godwinson"),
           ("Chairman", "Sheng-ji Yang"), ("Academician", "Prokhor Zakharov"))


def _booklist():
    if GAME is None:
        pytest.skip("no game folder")
    txt = (Path(GAME) / "holobook.txt").read_text(encoding="latin-1")
    ents = [m.group(2) for m in re.finditer(r"#BOOKLIST(\d+)\r?\n(.*?)\r?\n", txt)]
    assert len(ents) == 25
    return [re.sub(r"\$\w+", "X", e.replace("$TITLE0", t).replace("$PLAYER1", p)) for e in ents for t, p in LEADERS]


def test_vanilla_breaks_reproduce_the_pristine_shot(gdi):
    """refs\\pristine\\EndGame\\Retirement.png at native: 'Welcome to the' / 'Planetary Archives' and the intro's
    four lines ('the' ends line 1). The emulation must reproduce them before the lever may rely on it."""
    f = lambda t: gdi.width_fn(*SL.hb_font(t, 16))
    assert SL.hb_line_breaks(TITLE, f(0x8A40E4), 236) == ["Welcome to the", "Planetary Archives"]
    assert SL.hb_line_breaks(INTRO, f(0x8A40E8), 256) == [
        "Following your retirement, the", "people collect your most", "memorable writings into a",
        "holobook of wisdom entitled:"]


def _segw(w, s):
    """The engine's measure of a laid-out line: its pieces summed (first word, then each ' word')."""
    tot, start = 0, 0
    while True:
        j = s.find(" ", start + 1)
        tot += w(s[start:j if j != -1 else len(s)])
        if j == -1:
            return tot
        start = j


def _wrapped_texts():
    """Every text the painter wraps, as (text, font table, vanilla width): BOOKTITLE, BOOKINTRO, every BOOKLIST entry x
    5 leaders at the list width (list page) AND at the intro width in the intro font (the book page's GameLanguage
    != 0 path shows BOOKLIST<n> there), and the page-8 caption (leader title + name) at its own width."""
    title, intro, lst = SL.HB_RECT_LITERALS[3], SL.HB_RECT_LITERALS[4], SL.HB_RECT_LITERALS[0]
    x8, _y8, w8, _h8 = SL.HB_CAPTIONS[8]
    out = [(TITLE, 0x8A40E4, (title[0], title[2])), (INTRO, 0x8A40E8, (intro[0], intro[2]))]
    books = _booklist()
    out += [(b, 0x8A40E0, (lst[0], lst[2])) for b in books]
    out += [(b, 0x8A40E8, (intro[0], intro[2])) for b in books]
    out += [(f"{t} {p}", 0x8A40F0, (x8, x8 + w8)) for t, p in LEADERS]
    return out


def _dev_width(edges, num):
    """The width the engine passes the wrap at num: each rect edge scaled on its own (s(R) - s(L), as t_hb_build
    rebuilds the table), which is +-1 off s(R - L) at many num (audit of 4f9762e)."""
    return SL.mon_s(edges[1], num) - SL.mon_s(edges[0], num)


@pytest.mark.parametrize("num", NUMS)
def test_the_lever_keeps_vanilla_breaks_and_never_overflows(gdi, num):
    """t_hb_flb v2's law at every num 17..72 over every wrapped text: every line fits its device box when drawn in the
    scaled font, and the lines ARE vanilla's wherever vanilla's lines fit (the audit's BOOKLIST4 at num 19 -- the
    vanilla line is 256 of 256 and 310 in the 304 box -- breaks one word earlier instead of running out)."""
    for text, table, edges in _wrapped_texts():
        wn = edges[1] - edges[0]
        wv = gdi.width_fn(*SL.hb_font(table, 16))
        ws = gdi.width_fn(*SL.hb_font(table, num))
        dev = _dev_width(edges, num)
        van = SL.hb_line_breaks(text, wv, wn)
        got = SL.hb_line_breaks(text, wv, wn, ws, dev)
        for ln in got:
            assert len(ln.split(" ")) == 1 or _segw(ws, ln) <= dev, (num, table, ln)
        if all(_segw(ws, ln) <= dev for ln in van):
            assert got == van, (num, table, text)


def test_the_overflow_case_the_audit_found(gdi):
    """BOOKLIST4 in the intro font at num 19: vanilla's line overflows the scaled box, so the lever breaks earlier."""
    text = next(t for t, tab, _e in _wrapped_texts() if tab == 0x8A40E8 and "Superlubricant" in t)
    wv, ws = gdi.width_fn(*SL.hb_font(0x8A40E8, 16)), gdi.width_fn(*SL.hb_font(0x8A40E8, 19))
    van = SL.hb_line_breaks(text, wv, 256)
    assert any(_segw(ws, ln) > SL.mon_s(256, 19) for ln in van)
    got = SL.hb_line_breaks(text, wv, 256, ws, SL.mon_s(256, 19))
    assert got != van and all(_segw(ws, ln) <= SL.mon_s(256, 19) for ln in got)


def test_engine_rewrap_differs_somewhere(gdi):
    """Why the lever exists: without it the engine re-breaks at the scaled width (the intro is 3 lines at 4K)."""
    van = SL.hb_line_breaks(INTRO, gdi.width_fn(*SL.hb_font(0x8A40E8, 16)), 256)
    scaled = SL.hb_line_breaks(INTRO, gdi.width_fn(*SL.hb_font(0x8A40E8, 45)), SL.mon_s(256, 45))
    assert len(van) == 4 and scaled != van


# ---- the real Holobook.pcx under the pair enlarge: the scanline field stays on the dest grid ------------------------
def _holobook_crop():
    if GAME is None or not (Path(GAME) / "Holobook.pcx").exists():
        pytest.skip("no Holobook.pcx")
    from PIL import Image
    im = Image.open(Path(GAME) / "Holobook.pcx")
    w, h = im.size
    src = bytes(((v + 10) & 0xFF) if v != 255 else SL.HB_BLIT_KEY for v in im.tobytes())
    pal = bytearray(1024)
    p = im.getpalette()
    for i in range(10, 256):
        j = i - 10
        if j * 3 + 2 < len(p):
            pal[i * 4:i * 4 + 3] = bytes((p[j * 3 + 2], p[j * 3 + 1], p[j * 3]))
    return src, w, h, bytes(pal)


@pytest.mark.parametrize("num", (19, 22, 25, 45))
def test_holobook_field_is_on_the_dest_grid_around_the_art(num):
    """The panel's 64/197 field around the book icon and the shushing head (source rows 120..300 / 430..560, the region
    the field clause changes) comes out as one T-row stripe per member on the dest grid at every phase."""
    src, w, h, pal = _holobook_crop()
    f0, f1 = SL.HB_FIELD_PAIR
    top = SL.hof_pair_top(f0, f1, pal)
    bot = f0 + f1 - top
    for sx, sy, sw, sh in ((40, 120, 240, 180), (90, 430, 120, 130)):
        dw, dh = (sw * num) // 16, (sh * num) // 16
        for y0 in range(SL.stripe_period(num)):
            dst = bytearray(dw * dh)
            SL.hof_pair_enlarge(src, w, sx, sy, sw, sh, pal, num, dst, dw, dw, dh, 0, 0, y0, SL.HB_BLIT_KEY,
                                SL.HB_FIELD_PAIR)
            bad = 0
            m = (4 * num) // 16 + 2                  # the pair chain looks 3 source rows out: skip the crop's own edges
            for y in range(m, dh - m):
                want = top if SL.stripe_top(y0 + y, num) else bot
                sr = sy + SL.nn_center_index(y, dh, sh)
                for x in range(2, dw - 2):
                    v = dst[y * dw + x]
                    if v not in SL.HB_FIELD_PAIR or v == want:
                        continue
                    sc = sx + SL.nn_center_index(x, dw, sw)
                    mate = f0 + f1 - src[sr * w + sc]
                    if src[(sr - 1) * w + sc] == mate or src[(sr + 1) * w + sc] == mate:
                        bad += 1                      # a texel of a real field stripe (a lone 1-row gap between
                                                      # the icon's strokes is art detail: NN keeps it as drawn)
            assert bad == 0, (num, sx, sy, y0, bad)
