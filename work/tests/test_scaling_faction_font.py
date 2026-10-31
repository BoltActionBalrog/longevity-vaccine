"""SELECT A FACTION ("CHOOSE YOUR FACTIONS") picker: title + button-label font, on the REAL BAKED BYTES (2026-10-18 fix 12).

FactionPickWin_build sets every label font with Buffer_set_font(&g_popup_title_font 0x7CFE8C) -- the title and the six
buttons, seven call sites.  0x7CFE8C is MainWin+0x2166C = Font_init("Arial", 14, 1) (MainWin_build 0x459E34), which
thunk_hud_font already scales to Arial fl(14g/16) bold: the font_direct_law, scaling_laws.button_a14b_font_law, the
same LOGFONT t_fdirect_a14b() builds.  thunk_factionwin_font swapped the seven sites to find_font(fl(16g/16), 0) =
Arial Narrow bold (it read the Font's CELL, 16, as its size) and is retired; the sites are status: skip.

1. the seven sites call Buffer_set_font with vanilla's push 0x7CFE8C, byte-identical to the pristine .bak;
2. 0x7CFE8C, built through the baked MainWin_build.font1 call, has t_fdirect_a14b()'s LOGFONT and the law's
   (Arial, fl(14g/16), bold) at every g 16..40, and vanilla's own at g = 16;
3. every picker label fits its FlatButton wrap budget (w - 6, FlatButton_content_draw 0x6083C6) and the title its
   776-wide title rect at every g 16..40 (the narrowest screen per g: scale_uniform(w) = fl(w*g/16)) and on the real
   screens, measured with the engine's own Font_width (0x619280) on REAL GDI (ctypes), and the label cell fits the
   22-high button;
4. the generic titled-popup title (0x40609D): vanilla's push 0x7CFE8C at every g (thunk_title_font retired 2026-10-18
   fix 14 -- v1 swapped in g_pf0 = Arial Narrow at every g, v2 above g = 16; the rule font is this same object).
The Win32 font calls are real GDI (CreateFontIndirectA / GetTextMetricsA / GetTextExtentPoint32A on a memory DC).
"""
from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

if sys.platform != "win32":
    pytest.skip("real GDI text metrics need Windows", allow_module_level=True)
pytest.importorskip("unicorn")
pefile = pytest.importorskip("pefile")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: E402

import scaling_laws as SL  # noqa: E402

SW, SH, G = 0x9B7B1C, 0x9B7B20, 0x668740
TITLE_FONT = 0x7CFE8C                      # g_popup_title_font = MainWin+0x2166C
FONT_NAME_PTR = 0x691B2C                   # the "Arial" name pointer MainWin_build pushes
MAINWIN_FONT1 = 0x459E34                   # call Font_init(MainWin+0x2166C; name, 14, 1)  (baked: thunk_hud_font)
FONT_INIT, FONT_WIDTH, BUFFER_SET_FONT = 0x618F40, 0x619280, 0x5DAC70
A14B = 0xA3A590                            # t_fdirect_a14b() (pcave2+0x2E590)
HDC_GLOBAL = 0x9BB488
IAT = {0x669044: ("RemoveFontResourceA", 1), 0x669058: ("DeleteObject", 1), 0x669060: ("SelectObject", 2),
       0x669088: ("GetTextExtentPoint32A", 4), 0x669094: ("CreateFontIndirectA", 1),
       0x669098: ("GetTextMetricsA", 2), 0x6690C0: ("GetStockObject", 1)}
SITES = {"FactionPickWin_build.font_title": 0x488BF4, "FactionPickWin_build.font_b106": 0x489311,
         "FactionPickWin_build.font_b107": 0x4893B1, "FactionPickWin_build.font_b103": 0x48944A,
         "FactionPickWin_build.font_b108": 0x4894DD, "FactionPickWin_build.font_b105": 0x489569,
         "FactionPickWin_build.font_b104": 0x4895F5}
TITLE, TITLE_W = "CHOOSE YOUR FACTIONS", 776       # +0x624C title rect {7, 7, 783, 31}
BTN_H = 22
LABELS = {"PLAY SELECTED FACTION": 216, "PLAY RANDOM FACTION": 216,   # the two 216 x 22 PLAY buttons
          "INFO": 192, "QUOTE": 192, "CHANGE NAME": 192, "OK": 192, "CANCEL": 192}   # the 192 x 22 bottom bar
FLATBUTTON_SLACK = 6                                 # ellipsis / wrap when width > (R - L) - 6 (0x6083C6)
REAL = ((3840, 2160), (2560, 1440), (1920, 1080), (1600, 1200), (1600, 900), (1024, 768), (1366, 768),
        (1680, 1050), (3440, 1440), (2560, 1600), (1280, 1024), (1440, 900))
STUBS, HEAP, STACK, SENT = 0x70000000, 0x40000000, 0x20000000, 0x0DEAD000

# ---- real GDI behind the imports --------------------------------------------------------------------------------
_gdi = ctypes.windll.gdi32
_gdi.CreateFontIndirectA.restype = ctypes.c_void_p
_gdi.CreateFontIndirectA.argtypes = [ctypes.c_void_p]
_gdi.SelectObject.restype = ctypes.c_void_p
_gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi.GetStockObject.restype = ctypes.c_void_p
_gdi.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi.GetTextMetricsA.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi.GetTextExtentPoint32A.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
_DC = _gdi.CreateCompatibleDC(None)
FAKE_DC = 0x0DC00001


def lf_key(lf: bytes) -> tuple:
    """(face, lfHeight, lfWeight, italic, charset, out precision, quality, pitch&family) of a LOGFONTA."""
    h, _w, _e, _o, wgt = struct.unpack_from("<iiiii", lf, 0)
    return (lf[28:60].split(b"\0")[0].decode(), h, wgt, lf[20], lf[23], lf[24], lf[26], lf[27])


class Emu:
    """The PE image in Unicorn; the seven gdi32 imports Font_init / Font_width use are real GDI on a memory DC."""

    def __init__(self, path: str, w: int, h: int, g: int):
        pe = pefile.PE(path)
        img = pe.get_memory_mapped_image()
        ib = pe.OPTIONAL_HEADER.ImageBase
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, (max(len(img), pe.OPTIONAL_HEADER.SizeOfImage) + 0xFFF) & ~0xFFF)
        uc.mem_write(ib, bytes(img))
        pe.close()
        for base, size in ((STUBS, 0x1000), (HEAP, 0x100000), (STACK, 0x100000), (SENT, 0x1000)):
            uc.mem_map(base, size)
        self.heap = HEAP
        self.real, self.lfs, self.stubs = {}, {}, {}
        for k, (iat, (name, n)) in enumerate(IAT.items()):
            va = STUBS + 8 * k
            uc.mem_write(va, b"\xC3")
            uc.mem_write(iat, struct.pack("<I", va))
            self.stubs[va] = (getattr(self, "_" + name), n)
        uc.mem_write(HDC_GLOBAL, struct.pack("<I", FAKE_DC))
        uc.mem_write(SW, struct.pack("<ii", w, h))
        uc.mem_write(G, struct.pack("<i", g))
        uc.hook_add(UC_HOOK_CODE, self._hook, begin=STUBS, end=STUBS + 0xFFF)

    # -- memory
    def r32(self, a):
        return struct.unpack("<I", bytes(self.uc.mem_read(a, 4)))[0]

    def alloc(self, data: bytes) -> int:
        a = self.heap
        self.heap += (len(data) + 0xF) & ~0xF
        self.uc.mem_write(a, data)
        return a

    # -- the imports
    def _hook(self, uc, addr, _size, _ud):
        fn, n = self.stubs[addr]
        esp = uc.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<%dI" % n, bytes(uc.mem_read(esp + 4, 4 * n))) if n else ()
        ret = fn(*args)
        uc.reg_write(UC_X86_REG_EAX, ret & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * n)
        uc.reg_write(UC_X86_REG_EIP, self.r32(esp))

    def _dc(self, h):
        return _DC if h == FAKE_DC else self.real.get(h, h)

    def _CreateFontIndirectA(self, p):
        lf = bytes(self.uc.mem_read(p, 60))
        tok = 0x0F000000 + len(self.real) + 1
        self.real[tok] = _gdi.CreateFontIndirectA(ctypes.create_string_buffer(lf, 60))
        self.lfs[tok] = lf
        return tok

    def _SelectObject(self, hdc, obj):
        _gdi.SelectObject(self._dc(hdc), self._dc(obj))
        return 0x0E000000

    def _GetTextMetricsA(self, _hdc, out):
        buf = ctypes.create_string_buffer(64)
        _gdi.GetTextMetricsA(_DC, buf)
        self.uc.mem_write(out, buf.raw[:56])
        return 1

    def _GetTextExtentPoint32A(self, _hdc, p, n, out):
        sz = wintypes.SIZE()
        _gdi.GetTextExtentPoint32A(_DC, bytes(self.uc.mem_read(p, n)), n, ctypes.byref(sz))
        self.uc.mem_write(out, struct.pack("<ii", sz.cx, sz.cy))
        return 1

    def _GetStockObject(self, i):
        return _gdi.GetStockObject(i) & 0xFFFFFFFF

    def _DeleteObject(self, _h):
        return 1

    def _RemoveFontResourceA(self, _p):
        return 0

    # -- running
    def call(self, va: int, args=(), ecx: int = 0) -> int:
        sp = STACK + 0xF0000 - 4 * len(args)
        self.uc.mem_write(sp, struct.pack("<%dI" % len(args), *args) if args else b"")
        sp -= 4
        self.uc.mem_write(sp, struct.pack("<I", SENT))
        self.uc.reg_write(UC_X86_REG_ESP, sp)
        self.uc.reg_write(UC_X86_REG_ECX, ecx)
        self.uc.emu_start(va, SENT, count=2_000_000)
        assert self.uc.reg_read(UC_X86_REG_EIP) == SENT, hex(self.uc.reg_read(UC_X86_REG_EIP))
        return self.uc.reg_read(UC_X86_REG_EAX)

    def call_target(self, site: int) -> int:
        """The callee of the `E8 rel32` at site, as this image has it (pristine Font_init / baked thunk_hud_font)."""
        code = bytes(self.uc.mem_read(site, 5))
        assert code[0] == 0xE8
        return (site + 5 + struct.unpack("<i", code[1:])[0]) & 0xFFFFFFFF

    def title_font(self) -> int:
        """MainWin_build's own call: Font_init(MainWin+0x2166C; "Arial", 14, 1) through whatever 0x459E34 calls."""
        self.uc.mem_write(TITLE_FONT, bytes(0x28))
        self.call(self.call_target(MAINWIN_FONT1), (self.r32(FONT_NAME_PTR), 14, 1), ecx=TITLE_FONT)
        return TITLE_FONT

    def logfont(self, font: int) -> tuple:
        return lf_key(self.lfs[self.r32(font + 8)])

    def cell(self, font: int) -> int:
        return self.r32(font + 0xC)

    def width(self, font: int, s: str) -> int:
        """The engine's Font_width (thiscall ecx = Font) on real GDI."""
        p = self.alloc(s.encode("latin-1") + b"\0")
        return self.call(FONT_WIDTH, (p,), ecx=font)


# ---- fixtures ----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def baked(baked_exe):
    return str(baked_exe)


def g_screen(g: int) -> tuple:
    """A screen that runs at g: exactly 4:3 at g/16 (popup_g(64g, 48g) == g)."""
    return 64 * g, 48 * g


def button_w(native: int, w: int, h: int) -> int:
    """thunk_factionwin_button: BaseButton_init's w through popup_scale = fl(w * g/16) at g > 16 (g the screen's
    popup_g -- NOT scale_uniform(w, W, H): 1920x1080 is 297, not 303), native at g <= 16."""
    g = SL.popup_g(w, h)
    return native * g // 16 if g > 16 else native


_FONT_CACHE: dict = {}


def picker_font(path: str, w: int, h: int) -> dict:
    """{logfont, cell, title, labels} of 0x7CFE8C built by the image's MainWin_build call on a w x h screen."""
    g = SL.popup_g(w, h)
    key = (path, g)
    if key not in _FONT_CACHE:
        e = Emu(path, w, h, g)
        f = e.title_font()
        _FONT_CACHE[key] = {"logfont": e.logfont(f), "cell": e.cell(f), "title": e.width(f, TITLE),
                            "labels": {s: e.width(f, s) for s in LABELS}}
    return _FONT_CACHE[key]


# ---- 1. the seven sites are vanilla's -------------------------------------------------------------------------------
def test_picker_font_sites_are_retired_in_the_yaml(loaded):
    sites = {s["id"]: s for s in loaded["sites"]}
    groups = {g["id"]: g for g in loaded["groups"]}
    for sid, va in SITES.items():
        s = sites[sid]
        assert s["status"] == "skip" and int(s["virtual_addr"]) == va, sid
        assert s["group"] == "faction_pickwin_font_retired", sid
    assert sorted(groups["faction_pickwin_font_retired"]["members"]) == sorted(SITES)
    assert groups["faction_pickwin_font_retired"].get("skippable") is True
    assert not set(SITES) & set(groups["faction_pickwin_content"]["members"])


@pytest.mark.parametrize("sid", list(SITES))
def test_picker_font_site_calls_buffer_set_font_with_the_title_font(baked, bak_bytes, sid):
    va = SITES[sid]
    pe = pefile.PE(baked, fast_load=True)
    data = open(baked, "rb").read()
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    pe.close()
    assert data[off] == 0xE8 and va + 5 + struct.unpack_from("<i", data, off + 1)[0] == BUFFER_SET_FONT, sid
    push = b"\x68" + struct.pack("<I", TITLE_FONT)
    window = data[off - 12:off]
    assert push in window, (sid, window.hex(" "))
    assert data[off - 12:off + 5] == bak_bytes[off - 12:off + 5], f"{sid}: differs from the pristine .bak"


# ---- 2. the object is the law ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", range(16, 41))
def test_title_font_object_is_the_a14b_law(baked, g):
    w, h = g_screen(g)
    e = Emu(baked, w, h, g)
    got = e.logfont(e.title_font())
    law = e.logfont(e.call(A14B))                            # t_fdirect_a14b(): the project's port of the law
    name, size, style = SL.button_a14b_font_law(g)
    assert (name, size, style) == ("Arial", 14 * g // 16, 1)
    assert got == law, f"g{g}: 0x7CFE8C {got} != t_fdirect_a14b() {law}"
    assert got[:3] == (name, -size, 700), f"g{g}: {got}"


def test_title_font_object_is_vanilla_at_g16(baked, bak_path):
    for w, h in ((1024, 768), (1366, 768), (800, 600)):
        g = SL.popup_g(w, h)
        assert g == 16
        e, v = Emu(baked, w, h, g), Emu(str(bak_path), w, h, g)
        assert v.call_target(MAINWIN_FONT1) == FONT_INIT
        fe, fv = e.title_font(), v.title_font()
        assert e.logfont(fe) == v.logfont(fv) == ("Arial", -14, 700, 0, 0, 7, 0, 0)
        assert e.cell(fe) == v.cell(fv) == 16


# ---- 3. every label fits ---------------------------------------------------------------------------------------------
def _fit_failures(m: dict, w: int, h: int) -> list:
    bad = []
    g = SL.popup_g(w, h)
    for s, native in LABELS.items():
        budget = button_w(native, w, h) - FLATBUTTON_SLACK
        if m["labels"][s] > budget:
            bad.append(f"{w}x{h} g{g}: {s!r} {m['labels'][s]} > {budget}")
    title_w = TITLE_W * g // 16 if g > 16 else TITLE_W
    if m["title"] > title_w:
        bad.append(f"{w}x{h} g{g}: title {m['title']} > {title_w}")
    btn_h = BTN_H * g // 16 if g > 16 else BTN_H                    # popup_scale, as button_w
    if m["cell"] > btn_h:
        bad.append(f"{w}x{h} g{g}: cell {m['cell']} > button h {btn_h}")
    return bad


def test_button_budget_is_the_thunks_popup_scale(loaded):
    """The budget the fit checks use is what thunk_factionwin_button hands BaseButton_init: each of x, y, w, h through
    popup_scale (fl(v * g/16), g = the screen's popup_g) -- not scale_uniform(v, W, H), which runs 2% wide at 16:9."""
    caves = {e["id"]: str(e["bytes"]) for c in loaded["caves"] for e in (c.get("contents") or [])}
    t = " ".join(caves["thunk_factionwin_button"].split())
    for k in ("0C", "10", "14", "18"):                       # [esp+0xC..0x18] -> popup_scale -> back
        assert f"8B 44 24 {k} E8 {{rel32:popup_scale}} 89 44 24 {k}" in t, k
    assert (button_w(216, 1920, 1080), button_w(192, 1920, 1080)) == (297, 264)
    assert (button_w(216, 3840, 2160), button_w(216, 1600, 1200), button_w(216, 1366, 768)) == (540, 337, 216)


@pytest.mark.parametrize("g", range(16, 41))
def test_picker_labels_fit_their_wrap_budget(baked, g):
    w, h = g_screen(g)
    assert not _fit_failures(picker_font(baked, w, h), w, h)


@pytest.mark.parametrize("w, h", REAL)
def test_picker_labels_fit_on_the_real_screens(baked, w, h):
    assert not _fit_failures(picker_font(baked, w, h), w, h)


def test_picker_label_widths_are_proportionate_to_vanilla(baked, bak_path):
    """Each label / title width stays within 10% of vanilla x g/16 (the retired Arial Narrow ran 9-35% over with the
    face the investigator's GDI had; the law font is Arial, the face vanilla draws, at fl(14g/16))."""
    v = picker_font(str(bak_path), 1024, 768)
    for g in range(17, 41):
        m = picker_font(baked, *g_screen(g))
        for s in LABELS:
            assert abs(m["labels"][s] / (v["labels"][s] * g / 16) - 1) <= 0.10, (g, s, m["labels"][s], v["labels"][s])
        assert abs(m["title"] / (v["title"] * g / 16) - 1) <= 0.10, (g, m["title"], v["title"])


# ---- 4. the titled-popup title font (0x40609D) ----------------------------------------------------------------------
# thunk_title_font is retired (2026-10-18 fix 14, user decision: popup titles above native scale use the rule font):
# the site keeps vanilla's push 0x7CFE8C at every g -- the object section 2 pins as the law.  The title's placement
# and size against vanilla x g/16 live in test_scaling_popup_title_font.py.
TITLE_FONT_SITE = 0x40609D


def test_popup_title_font_site_is_vanillas_push(baked, bak_bytes):
    pe = pefile.PE(baked, fast_load=True)
    data = open(baked, "rb").read()
    off = pe.get_offset_from_rva(TITLE_FONT_SITE - pe.OPTIONAL_HEADER.ImageBase)
    pe.close()
    assert data[off:off + 5] == b"\x68" + struct.pack("<I", TITLE_FONT) == bak_bytes[off:off + 5]
