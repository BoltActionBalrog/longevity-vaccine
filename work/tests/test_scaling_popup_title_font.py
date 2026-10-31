"""Popup titles above native scale use the RULE font (USER DECISION 2026-10-18, fix 14): vanilla's 0x7CFE8C, no nudge.

The generic titled-popup path of Popup_on_draw_background (0x405F7C..0x4060E7, every titled popup that is not the
diplomacy talk window -- that one is the 0x405D3E branch, push 0x7CFE8C @0x405DEB, untouched) pushes 0x7CFE8C @0x40609D
for Buffer_set_font and draws the title with Buffer_write_cent_l_7 @0x4060E2.  0x7CFE8C is MainWin+0x2166C =
Font_init("Arial", 14, 1), which thunk_hud_font (MainWin_build.font1) builds as Arial fl(14g/16) bold -- the law
(scaling_laws.button_a14b_font_law; test_scaling_faction_font.py pins the LOGFONT at every g).  thunk_title_font
swapped in g_pf0 (Arial Narrow synthetic bold, cell >= 20g/16) above g = 16 and thunk_title_textnudge lifted the text
(g-16)>>3; both sites are retired (status: skip, group popup_title_font_retired).

1. the two sites are retired in the yaml, and the bake carries vanilla's bytes there (and in the diplomacy branch);
2. the title slice run on the REAL bake (thunks live, box draws stubbed) hands Buffer_write_cent_l_7 the 0x7CFE8C
   object and a rect; at g = 16 font, rect and box are the pristine .bak's;
3. with the writer's own centring (0x5DD130: y = top + (h - Font+0x10)/2 truncated; TA_BASELINE at y + Font+0x10 --
   which reproduces the user's 4K SELECT DESTINATION shot 20261017-114940 to the pixel for the g_pf0 build) and real
   GDI ink, the title's cap ink lies within 1 px of vanilla x g/16 (box-relative), its cap height within 1 px of
   vanilla's x g/16 and its width within 8% of vanilla's x g/16 (GDI's per-size advance rounding: 1280x960 g = 20
   CUSTOMIZE GAME RULES is 209 for 222.5, -6.1%), at every g 17..40 and on the real screens.
"""
from __future__ import annotations

import ctypes
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform != "win32":
    pytest.skip("real GDI text metrics need Windows", allow_module_level=True)
pytest.importorskip("unicorn")
pefile = pytest.importorskip("pefile")

from unicorn import UC_HOOK_CODE  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402
import test_scaling_faction_font as T  # noqa: E402   the image + real GDI behind Font_init / Font_width

SITES = {"Popup_on_draw_background.title_font": 0x40609D, "Popup_on_draw_background.title_textnudge": 0x4060AA}
TITLE_FONT = 0x7CFE8C
SLICE, SLICE_END = 0x405F8A, 0x4060E7
BOX, SETFONT, SETCOLOR, WRITE, STRLEN, CONSOLE_VIS = 0x5E2DD3, 0x5DAC70, 0x5DACB0, 0x5DD130, 0x6453E0, 0x5F7E90
DIPLO_TITLE = (0x405D3E, 0x405F7C)            # the diplomacy talk title branch (push 0x7CFE8C @0x405DEB)
TITLES = ("SELECT DESTINATION", "CUSTOMIZE GAME RULES")
GS = range(17, 41)
REAL = ((3840, 2160), (2560, 1440), (1920, 1080), (1600, 1200), (1600, 900), (1366, 768), (1024, 768))


# ---- 1. retired sites ----------------------------------------------------------------------------------------------
def test_title_font_sites_are_retired_in_the_yaml(loaded):
    sites = {s["id"]: s for s in loaded["sites"]}
    groups = {g["id"]: g for g in loaded["groups"]}
    for sid, va in SITES.items():
        assert sites[sid]["status"] == "skip" and int(sites[sid]["virtual_addr"]) == va, sid
        assert sites[sid]["group"] == "popup_title_font_retired", sid
    g = groups["popup_title_font_retired"]
    assert g.get("skippable") is True and sorted(g["members"]) == sorted(SITES)
    assert not set(SITES) & set(groups["popup_title_scaling"]["members"])


@pytest.fixture(scope="module")
def baked(baked_exe) -> str:
    return str(baked_exe)


def _va_bytes(path: str, va: int, n: int) -> bytes:
    pe = pefile.PE(path, fast_load=True)
    data = open(path, "rb").read()
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    pe.close()
    return data[off:off + n]


def test_title_sites_carry_vanilla_bytes(baked, bak_path):
    assert _va_bytes(baked, 0x40609D, 5) == b"\x68" + struct.pack("<I", TITLE_FONT)
    for va in SITES.values():
        assert _va_bytes(baked, va, 5) == _va_bytes(str(bak_path), va, 5), hex(va)


def test_diplomacy_title_push_is_untouched(baked, bak_path):
    """The diplomacy talk branch keeps its own push 0x7CFE8C @0x405DEB (its title levers are the t_dp_title_* family)."""
    assert _va_bytes(baked, 0x405DEB, 5) == _va_bytes(str(bak_path), 0x405DEB, 5) == \
        b"\x68" + struct.pack("<I", TITLE_FONT)


# ---- 2. the title slice on the real bytes --------------------------------------------------------------------------
def _sym():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return dict(ap.build_symbol_table(symbols, caves))


SYM = _sym()


def title_slice(path: str, w: int, h: int, title: str, typ: int = 0, console: int = 0):
    """Run 0x405F8A..0x4060E7 (the generic title) on the image; the box draws are stubbed (the frame thickeners are
    not under test).  -> dict(font, rect, box): the Font* Buffer_write_cent_l_7 draws with, its RECT, and the outer
    title box rect (the d5a0 draw's)."""
    g = SL.popup_g(w, h)
    e = T.Emu(path, w, h, g)
    uc = e.uc
    font = e.title_font()                             # 0x7CFE8C as the image's MainWin_build.font1 builds it
    pop = e.alloc(bytes(0x3200))
    ts = e.alloc(title.encode() + b"\0")
    uc.mem_write(pop + 0xA48, struct.pack("<I", ts))
    uc.mem_write(pop + 0x474, struct.pack("<4i", 100, 100, 100 + 23 * g, 100 + 18 * g))
    uc.mem_write(pop + 0x30AC, struct.pack("<i", typ * 10000))
    log = {"box": [], "font": None, "write": None}

    def ret(u, n, val=0):
        esp = u.reg_read(UC_X86_REG_ESP)
        r = struct.unpack("<I", bytes(u.mem_read(esp, 4)))[0]
        u.reg_write(UC_X86_REG_EAX, val)
        u.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * n)
        u.reg_write(UC_X86_REG_EIP, r)

    def args(u, n):
        esp = u.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<%dI" % n, bytes(u.mem_read(esp + 4, 4 * n)))

    def box(u):
        a = args(u, 2)
        log["box"].append(struct.unpack("<4i", bytes(u.mem_read(a[0], 16))))
        ret(u, 2)

    def setfont(u):
        log["font"] = args(u, 4)[0]
        ret(u, 4)

    def write(u):
        a = args(u, 3)
        log["write"] = (bytes(u.mem_read(a[0], a[2])).decode(), struct.unpack("<4i", bytes(u.mem_read(a[1], 16))))
        ret(u, 3)

    stubs = {BOX: box, SYM["thunk_pf_title_stash"]: box, SYM["thunk_box_thick_flat"]: box, SETFONT: setfont,
             SETCOLOR: lambda u: ret(u, 4), WRITE: write, CONSOLE_VIS: lambda u: ret(u, 0, console),
             STRLEN: lambda u: ret(u, 0, len(title)), e.r32(0x66931C): lambda u: ret(u, 1)}

    def hook(u, addr, _size, _ud):
        if addr in stubs:
            stubs[addr](u)
    uc.hook_add(UC_HOOK_CODE, hook)
    ebp = T.STACK + 0x80000
    uc.mem_write(ebp - 0x44, bytes(0x44))
    uc.mem_write(ebp - 4, struct.pack("<i", typ))
    for r, v in ((UC_X86_REG_EBP, ebp), (UC_X86_REG_ESP, ebp - 0x44 - 12), (UC_X86_REG_ESI, pop),
                 (UC_X86_REG_EDI, pop + 0x444), (UC_X86_REG_EBX, pop + 0x474), (UC_X86_REG_EAX, ts)):
        uc.reg_write(r, v)
    uc.emu_start(SLICE, SLICE_END, count=200_000)
    assert uc.reg_read(UC_X86_REG_EIP) == SLICE_END
    assert log["write"] and log["write"][0] == title and log["box"]
    return dict(font=log["font"], rect=log["write"][1], box=log["box"][0], emu=e, title_font=font)


CASES = ((0, 0), (0, 1), (5, 1), (6, 0), (2, 0))       # (popup type, console visible): every title-inset arm


@pytest.mark.parametrize("w, h", ((1024, 768), (1366, 768), (800, 600)))
def test_g16_title_is_pristine(baked, bak_path, w, h):
    for typ, con in CASES:
        a = title_slice(baked, w, h, TITLES[0], typ, con)
        v = title_slice(str(bak_path), w, h, TITLES[0], typ, con)
        assert a["font"] == v["font"] == TITLE_FONT
        assert (a["rect"], a["box"]) == (v["rect"], v["box"]), (w, h, typ, con)
        assert a["emu"].logfont(TITLE_FONT) == v["emu"].logfont(TITLE_FONT) == ("Arial", -14, 700, 0, 0, 7, 0, 0)


# ---- 3. the ink against vanilla x g/16 -------------------------------------------------------------------------------
_gdi = ctypes.windll.gdi32
_gdi.CreateFontIndirectA.restype = ctypes.c_void_p
_gdi.CreateFontIndirectA.argtypes = [ctypes.c_void_p]
_gdi.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi.CreateDIBSection.restype = ctypes.c_void_p
_gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.c_void_p, ctypes.c_uint]
_gdi.SelectObject.restype = ctypes.c_void_p
_gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi.SetTextAlign.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_gdi.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
_gdi.SetTextColor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_gdi.TextOutA.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
_DW, _DH, _BASE = 1200, 160, 120
_DC = _gdi.CreateCompatibleDC(None)
_BITS = ctypes.c_void_p()
_gdi.SelectObject(_DC, _gdi.CreateDIBSection(_DC, struct.pack("<IiiHHIIiiII", 40, _DW, -_DH, 1, 32, 0, 0, 0, 0, 0, 0),
                                             0, ctypes.byref(_BITS), None, 0))


def ink_rows(lf: bytes, s: str):
    """(top, bottom) ink rows of `s` drawn TA_BASELINE with the LOGFONT `lf`, relative to the baseline (bottom exclusive)."""
    h = _gdi.CreateFontIndirectA(ctypes.create_string_buffer(lf, 60))
    _gdi.SelectObject(_DC, h)
    ctypes.memset(_BITS, 0, _DW * _DH * 4)
    _gdi.SetTextAlign(_DC, 0x18)
    _gdi.SetBkMode(_DC, 1)
    _gdi.SetTextColor(_DC, 0xFFFFFF)
    _gdi.TextOutA(_DC, 4, _BASE, s.encode(), len(s))
    buf = ctypes.string_at(_BITS, _DW * _DH * 4)
    rows = [y for y in range(_DH) if any(buf[y * _DW * 4:(y + 1) * _DW * 4])]
    return rows[0] - _BASE, rows[-1] + 1 - _BASE


def placed(r: dict, s: str):
    """The title's cap ink rows relative to the outer title box top, as Buffer_write_cent_l_7 places them."""
    e, f = r["emu"], r["font"]
    top, bot = r["rect"][1], r["rect"][3]
    f10 = e.r32(f + 0x10)
    q = bot - top - f10
    y = top + (q // 2 if q >= 0 else -((-q) // 2))                       # cdq; sub eax,edx; sar eax,1
    base = y + f10                                                        # 0x5DBDDD: baseline = y + Font+0x10
    it, ib = ink_rows(e.lfs[e.r32(f + 8)], s)
    return base + it - r["box"][1], base + ib - r["box"][1]


@pytest.fixture(scope="module")
def vanilla(bak_path):
    out = {}
    for s in TITLES:
        r = title_slice(str(bak_path), 1024, 768, s)
        out[s] = (placed(r, s), r["emu"].width(r["font"], s), r["box"][3] - r["box"][1])
    return out


def _check(baked, vanilla, w, h):
    g = SL.popup_g(w, h)
    bad = []
    for s in TITLES:
        (vt, vb), vw, vbox = vanilla[s]
        r = title_slice(baked, w, h, s)
        assert r["font"] == TITLE_FONT, (w, h, hex(r["font"]))
        t, b = placed(r, s)
        width = r["emu"].width(r["font"], s)
        k = g / 16 if g > 16 else 1
        if abs((t + b) / 2 - (vt + vb) / 2 * k) > 1.0:
            bad.append(f"{w}x{h} g{g} {s!r}: ink centre {(t + b) / 2} vs law {(vt + vb) / 2 * k:.2f}")
        if abs((b - t) - (vb - vt) * k) > 1.0:
            bad.append(f"{w}x{h} g{g} {s!r}: cap height {b - t} vs law {(vb - vt) * k:.2f}")
        if abs(width / (vw * k) - 1) > 0.08:                              # GDI's per-size advance rounding
            bad.append(f"{w}x{h} g{g} {s!r}: width {width} vs law {vw * k:.1f}")
        if not (0 <= t and b <= r["box"][3] - r["box"][1]):
            bad.append(f"{w}x{h} g{g} {s!r}: ink [{t},{b}) outside the box")
    return bad


def test_vanilla_title_ink_is_centred(vanilla):
    """The reference itself: vanilla's caps sit centred in the 24-row title box (rows 7..16)."""
    for s in TITLES:
        (t, b), _w, box = vanilla[s]
        assert (t, b, box) == (7, 17, 24), (s, t, b, box)


@pytest.mark.parametrize("g", GS)
def test_title_ink_is_vanilla_times_g(baked, vanilla, g):
    assert not _check(baked, vanilla, 64 * g, 48 * g)


@pytest.mark.parametrize("w, h", REAL)
def test_title_ink_on_the_real_screens(baked, vanilla, w, h):
    assert not _check(baked, vanilla, w, h)
