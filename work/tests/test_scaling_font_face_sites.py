"""Text drawn in vanilla's font face, scaled (the 2026-11-10 sweep after the TutWin button report).

Six sites drew a different FACE / WEIGHT than vanilla at g > 16.  Each vanilla font is pinned here by its evidence
(pristine glyph maps / static font calls) and each port is emulated from its REAL baked bytes:

  site                              vanilla                      law (scaling_laws)            port
  TutWin TOUR/Close/... buttons     Arial Narrow 16 bold         TUTWIN_BTN_FONT (16,0)        thunk_tutbtn_post t_ffn
  Load/Save file list               Arial 12 regular             FILEDLG_TEXT_FONT (12,0)      thunk_filedlg_dlgfont
  Load/Save filename field          Arial 12 regular             FILEDLG_TEXT_FONT (12,0)      thunk_filedlg_editfont
  MP lobby chat                     Arial 12 regular (0x7D3948)  LOBBY_CHAT_FONT (12,0)        thunk_nw_chatfont
  COMMLINK MP turn-clock            Font_init("Arial",14,1)      COMMLINK_HDR_FONT             hm_scalefont -> t_fdirect_a14b
  COMMLINK pool fonts <= 12         e.g. NO CONTACTS Arial 12 b  commlink_pool_font_law        hm_scalefont -> t_ffn(S,v)

t_ffn / t_fdirect_a14b themselves are emulated against the laws in test_fontlaw_asm_parity.py; here they are
recording stubs that CLOBBER eax/ecx/edx like the real cdecl helpers, so a thunk that forgets to preserve a register
it owes its caller fails.
"""
from __future__ import annotations

import contextlib
import ctypes
import io
import os
import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_font_face_sites as AFS  # noqa: E402
    import assemble_tutbtn_post as AT  # noqa: E402

YAML = ROOT / "patches" / "patches.yaml"
PRISTINE = ROOT.parent / "refs" / "pristine"

PCAVE2 = 0xA0C000
G_VA = 0x668740
T_FFN, T_FDIRECT_A14B, FIND_FONT = 0xA3A570, 0xA3A590, 0x5882F0
DIALOG_SET_DIALOG_FONT, BUFFER_SET_FONT = 0x609C60, 0x5DAC70
HM_SCALEFONT = PCAVE2 + 0x5DE0
HM_SIZE_TABLE = PCAVE2 + 0x5D00
MW_ROW_FONT, MW_HDR_FONT = 0x7FD648 + 0x285C, 0x7FD648 + 0x2884
POOL0 = 0x93FC58
NW_TS_FONT, NW_EL_FONT = 0x80BDA8, 0x80E948
GS = (16, 17, 18, 22, 25, 40)
MARK_FFN, MARK_A14B, MARK_FF = 0x11110000, 0x22220000, 0x33330000
CLOBBER = 0xDEADBEEF


# ----------------------------------------------------------------------------------------------------------- laws
def test_scaling_tutwin_btnfont_law_is_the_body_font():
    for g in range(10, 17):
        assert SL.tutwin_button_font_law(g) == ("Arial Narrow", 16, 1)
    for g in range(17, SL.FONT_POOL_MAX + 1):   # == what thunk_tutwin_fonts gives the body: find_font(g, 0)
        n = SL.find_font_snap(g)
        assert SL.tutwin_button_font_law(g) == (SL.font_pool_face(n, 0)[0], n, SL.font_pool_face(n, 0)[1]), g
    assert SL.G_MAX == SL.FONT_POOL_MAX, "above 40 the button (cave slot) and the body (pool snap) would diverge"


def test_scaling_tutwin_body_font_is_find_font_g_0():
    """The button law claims equality with the body font: pin that thunk_tutwin_fonts installs find_font(g, 0)
    (mov ebx,eax = g; push 0; push ebx; call find_font) for the def-dialog font v0."""
    tpl = " ".join(_yaml_template("thunk_tutwin_fonts").split())
    assert tpl.startswith("E8 {rel32:popups_tutorial} A1 {abs32:g_popup_scale_num} 83 F8 10 7E")
    assert "8B D8 6A 00 53 E8 {rel32:find_font}" in tpl


def test_scaling_tutwin_btnfont_is_not_the_default_label_font():
    assert SL.TUTWIN_BTN_FONT != SL.BUTTON_DEFAULT_FONT
    for g in (16, 18, 22, 25, 40):
        assert SL.tutwin_button_font_law(g) != SL.button_default_font_law(g), g


@pytest.mark.parametrize("g", range(17, SL.G_MAX + 1))
def test_scaling_twelve_px_sites_stay_arial_regular_at_every_g(g):
    for law in (SL.FILEDLG_TEXT_FONT, SL.LOBBY_CHAT_FONT):
        assert SL.font_face_law_font(*law, g) == ("Arial", (12 * g) // 16, 0), (law, g)
    assert SL.font_direct_law(*SL.COMMLINK_HDR_FONT, g) == ("Arial", (14 * g) // 16, 1)
    assert SL.commlink_pool_font_law(12, 1, g) == ("Arial", (12 * g) // 16, 1)    # NO CONTACTS
    name, _, style = SL.commlink_pool_font_law(16, 0, g)
    assert name == "Arial Narrow" and style & 1                                      # > 12 pool: unchanged


# ----------------------------------------------------------------------------------- yaml == assemblers == laws
def _yaml_template(entry_id: str, text: str = None) -> str:
    text = text if text is not None else YAML.read_text(encoding="utf-8")
    m = re.search(r"- id: " + re.escape(entry_id) + r"\s*\n\s*offset:[^\n]*\n\s*bytes: \"([^\"]*)\"", text)
    assert m, entry_id + " not in patches.yaml"
    return m.group(1)


def test_scaling_font_sites_yaml_is_the_assemblers():
    text = YAML.read_text(encoding="utf-8")
    assert _yaml_template("thunk_tutbtn_post", text).split() == AT.TEMPLATE.split()
    for name, (_off, tpl) in AFS.TEMPLATES.items():
        assert _yaml_template(name, text).split() == tpl.split(), name
    s, v = SL.TUTWIN_BTN_FONT
    assert " ".join(_yaml_template("thunk_tutbtn_post", text).split()).count(
        f"6A {v:02X} 6A {s:02X} E8 {{rel32:t_ffn}}") == 1
    hm = " ".join(_yaml_template("hm_scalefont", text).split())
    assert hm.count("E8 {rel32:t_fdirect_a14b}") == 1 and hm.count("E8 {rel32:t_ffn}") == 1


# ----------------------------------------------------------------------------------------- emulation (baked bytes)
@pytest.fixture(scope="module")
def image(baked_exe):
    pefile = pytest.importorskip("pefile")
    data = pathlib.Path(baked_exe).read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    secs = [(ib + s.VirtualAddress, s.get_data()) for s in pe.sections]

    def read(va: int, n: int) -> bytes:
        for base, raw in secs:
            if base <= va and va + n <= base + len(raw):
                return raw[va - base:va - base + n]
        raise AssertionError(hex(va))
    return read


class Emu:
    """One small Unicorn: the thunk's page(s) from the baked exe, recording stubs for t_ffn / t_fdirect_a14b /
    find_font, HLT at every exit, a stack."""
    STACK, SP0, RET = 0x00300000, 0x00308000, 0x00400100

    def __init__(self, image, g: int, code_vas, ffn_ret=MARK_FFN):
        unicorn = pytest.importorskip("unicorn")
        from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn import x86_const as X
        self.X = X
        self.uc = uc = unicorn.Uc(UC_ARCH_X86, UC_MODE_32)
        pages = set()
        for va, n in code_vas:
            for p in range(va & ~0xFFF, (va + n + 0xFFF) & ~0xFFF, 0x1000):
                pages.add(p)
        for p in (T_FFN & ~0xFFF, FIND_FONT & ~0xFFF, DIALOG_SET_DIALOG_FONT & ~0xFFF, BUFFER_SET_FONT & ~0xFFF,
                  G_VA & ~0xFFF, self.RET & ~0xFFF, NW_TS_FONT & ~0xFFF, NW_EL_FONT & ~0xFFF, 0x7FF000,
                  0x940000, 0x93F000):
            pages.add(p)
        for p in sorted(pages):
            uc.mem_map(p, 0x1000)
        for va, n in code_vas:
            uc.mem_write(va, image(va, n))
        uc.mem_map(self.STACK, 0x10000)
        uc.mem_write(G_VA, struct.pack("<i", g))
        for va in (self.RET, DIALOG_SET_DIALOG_FONT, BUFFER_SET_FONT):
            uc.mem_write(va, b"\xF4")
        self.calls = []
        stubs = {T_FFN: ("t_ffn", ffn_ret), T_FDIRECT_A14B: ("t_fdirect_a14b", MARK_A14B), FIND_FONT: ("find_font", None)}
        for va in stubs:
            uc.mem_write(va, b"\xC3")                     # ret (args are cdecl, the caller cleans)

        def hook(u, addr, size, _):
            if addr in stubs:
                name, ret = stubs[addr]
                sp = u.reg_read(X.UC_X86_REG_ESP)
                a1, a2 = struct.unpack("<ii", bytes(u.mem_read(sp + 4, 8)))
                self.calls.append((name, a1, a2) if name != "t_fdirect_a14b" else (name,))
                u.reg_write(X.UC_X86_REG_EAX, ret if ret is not None else MARK_FF + a1 * 0x10 + a2)
                u.reg_write(X.UC_X86_REG_ECX, CLOBBER)
                u.reg_write(X.UC_X86_REG_EDX, CLOBBER)
        for va in stubs:
            uc.hook_add(UC_HOOK_CODE, hook, begin=va, end=va)

    def reg(self, name, value=None):
        r = getattr(self.X, "UC_X86_REG_" + name.upper())
        if value is None:
            return self.uc.reg_read(r)
        self.uc.reg_write(r, value)

    def run(self, entry: int, stack_words):
        sp = self.SP0 - 4 * len(stack_words)
        self.uc.mem_write(sp, b"".join(struct.pack("<I", w & 0xFFFFFFFF) for w in stack_words))
        self.reg("esp", sp)
        self.uc.emu_start(entry, 0, count=2000)
        return self.reg("eip")

    def r32(self, va):
        return struct.unpack("<I", bytes(self.uc.mem_read(va, 4)))[0]


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("name,callee", [("thunk_filedlg_dlgfont", DIALOG_SET_DIALOG_FONT),
                                         ("thunk_filedlg_editfont", BUFFER_SET_FONT)])
def test_scaling_filedlg_font_thunks_install_arial_regular(image, g, name, callee):
    va = PCAVE2 + AFS.TEMPLATES[name][0]
    e = Emu(image, g, [(va, 0x40)])
    e.reg("ecx", 0x7CF000)                                # the thiscall self Buffer_set_font needs
    e.reg("ebx", 0x1111); e.reg("esi", 0x2222); e.reg("edi", 0x3333)
    native = 0x7CFEB4
    eip = e.run(va, [Emu.RET, native, 0, 0, 0])
    assert eip == callee + 1                              # hlt at the callee (eip past it)
    sp = e.reg("esp")
    assert e.r32(sp) == Emu.RET
    if g <= 16:
        assert e.calls == [] and e.r32(sp + 4) == native
    else:
        assert e.calls == [("t_ffn", *SL.FILEDLG_TEXT_FONT)]
        assert e.r32(sp + 4) == MARK_FFN
    assert e.reg("ecx") == 0x7CF000, "ecx (the callee's this) must survive t_ffn"
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (0x1111, 0x2222, 0x3333)


def test_scaling_filedlg_font_thunk_keeps_native_on_null(image):
    va = PCAVE2 + AFS.TEMPLATES["thunk_filedlg_dlgfont"][0]
    e = Emu(image, 25, [(va, 0x40)], ffn_ret=0)
    e.run(va, [Emu.RET, 0x7CFEB4, 0, 0, 0])
    assert e.r32(e.reg("esp") + 4) == 0x7CFEB4


TUT_FONTS = PCAVE2 + 0xA890
TUT_CALLEES = {0x5888E0: "popups_tutorial", 0x5882F0: "find_font", 0x6048C0: "string",
               0x609D20: "dialog", 0x6049C0: "button"}


@pytest.mark.parametrize("g", GS)
def test_scaling_tutorial_popups_scale_all_three_default_fonts(image, g):
    """thunk_tutwin_fonts v2 from the baked bytes: popups_tutorial first; at g > 16 the string, dialog AND button
    triples (the button one was missing: every tutor.txt popup's OK stayed native) get find_font(g, 0/1/2);
    callee-saved registers and esp come back intact.  Callees are cdecl stubs that clobber eax/ecx/edx."""
    unicorn = pytest.importorskip("unicorn")
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32
    from unicorn import x86_const as X
    uc = unicorn.Uc(UC_ARCH_X86, UC_MODE_32)
    for page in {TUT_FONTS & ~0xFFF, G_VA & ~0xFFF, Emu.RET & ~0xFFF} | {a & ~0xFFF for a in TUT_CALLEES}:
        uc.mem_map(page, 0x1000)
    uc.mem_map(Emu.STACK, 0x10000)
    uc.mem_write(TUT_FONTS, image(TUT_FONTS, 0x60))
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(Emu.RET, b"\xF4")
    calls = []
    for va in TUT_CALLEES:
        uc.mem_write(va, b"\xC3")

    def hook(u, addr, size, _):
        sp = u.reg_read(X.UC_X86_REG_ESP)
        args = struct.unpack("<4I", bytes(u.mem_read(sp + 4, 16)))
        name = TUT_CALLEES[addr]
        n = {"popups_tutorial": 0, "find_font": 2, "string": 4, "dialog": 3, "button": 3}[name]
        calls.append((name,) + args[:n])
        u.reg_write(X.UC_X86_REG_EAX, MARK_FF + args[0] * 0x10 + args[1] if name == "find_font" else 0)
        u.reg_write(X.UC_X86_REG_ECX, CLOBBER)
        u.reg_write(X.UC_X86_REG_EDX, CLOBBER)
    for va in TUT_CALLEES:
        uc.hook_add(UC_HOOK_CODE, hook, begin=va, end=va)
    sp0 = Emu.SP0 - 4
    uc.mem_write(sp0, struct.pack("<I", Emu.RET))
    regs = {X.UC_X86_REG_ESP: sp0, X.UC_X86_REG_EBX: 0x1111, X.UC_X86_REG_ESI: 0x2222, X.UC_X86_REG_EDI: 0x3333,
            X.UC_X86_REG_EBP: 0x4444}
    for r, v in regs.items():
        uc.reg_write(r, v)
    uc.emu_start(TUT_FONTS, 0, count=500)
    assert uc.reg_read(X.UC_X86_REG_EIP) == Emu.RET + 1
    assert uc.reg_read(X.UC_X86_REG_ESP) == sp0 + 4, "esp not balanced"
    for r, v in regs.items():
        if r != X.UC_X86_REG_ESP:
            assert uc.reg_read(r) == v, f"callee-saved register {r} clobbered"
    if g <= 16:
        assert calls == [("popups_tutorial",)]
        return
    f = [MARK_FF + g * 0x10 + v for v in range(3)]
    assert calls == [("popups_tutorial",), ("find_font", g, 0), ("find_font", g, 1), ("find_font", g, 2),
                     ("string", *f, 0), ("dialog", *f), ("button", *f)], calls
    for v in range(3):                                  # find_font(g, v) IS the law for all three triples
        n = SL.find_font_snap(g)
        assert SL.tutorial_popup_font_law(v, g) == (SL.font_pool_face(n, v)[0], n, SL.font_pool_face(n, v)[1])


def _e8(image, site):
    b = image(site, 5)
    assert b[0] == 0xE8, (hex(site), b.hex())
    return site + 5 + struct.unpack("<i", b[1:])[0]


def test_scaling_popup_style_sites_reach_the_font_thunks(image):
    """The baked call sites really enter the wrappers (an emulated thunk proves nothing if no site calls it)."""
    assert _e8(image, 0x48C324) == TUT_FONTS          # popt -> thunk_tutwin_fonts
    assert _e8(image, 0x4BE083) == TUT_FONTS          # TutWin_tut_win -> thunk_tutwin_fonts
    assert _e8(image, TUT_FONTS) == 0x5888E0           # the vanilla install runs first


@pytest.mark.parametrize("g", GS)
def test_scaling_lobby_chat_font_is_arial_regular(image, g):
    va = PCAVE2 + AFS.TEMPLATES["thunk_nw_chatfont"][0]
    e = Emu(image, g, [(va, 0x40)])
    ebx = 0x7FF000
    e.uc.mem_write(ebx + 0x3978 - 0x3000 if False else 0x7FF000 + 0x978, struct.pack("<I", 0xC0FFEE))
    e.reg("ebx", ebx - 0x3000)                            # [ebx+0x3978] = 0x7FF978
    e.uc.mem_write(NW_TS_FONT, struct.pack("<I", 0x7D3948)); e.uc.mem_write(NW_EL_FONT, struct.pack("<I", 0x7D3948))
    assert e.run(va, [Emu.RET]) == Emu.RET + 1
    assert e.reg("esi") == 0xC0FFEE, "the displaced MOV ESI,[EBX+0x3978]"
    if g <= 16:
        assert e.calls == [] and e.r32(NW_TS_FONT) == e.r32(NW_EL_FONT) == 0x7D3948
    else:
        assert e.calls == [("t_ffn", *SL.LOBBY_CHAT_FONT)]
        assert e.r32(NW_TS_FONT) == e.r32(NW_EL_FONT) == MARK_FFN


def _pool_font(size: int, variant: int) -> int:
    return POOL0 + SL.FONT_POOL_SIZES.index(size) * 0xA0 + variant * 0x28


def _hm(image, g: int, font: int, cell: int = None):
    e = Emu(image, g, [(HM_SCALEFONT, 0xA0), (HM_SIZE_TABLE, 12)])
    if cell is not None:
        e.uc.mem_write(font + 0xC, struct.pack("<i", cell))
    e.reg("eax", font); e.reg("ecx", 0x7FD648); e.reg("ebx", 0x1111)
    assert e.run(HM_SCALEFONT, [Emu.RET]) == Emu.RET + 1
    assert e.reg("ecx") == 0x7FD648, "thunk_comm_setfont's ecx (the buffer) must survive"
    assert e.reg("ebx") == 0x1111
    return e, e.reg("eax")


@pytest.mark.parametrize("g", [g for g in GS if g > 16])
def test_scaling_commlink_fonts_take_vanilla_faces(image, g):
    e, r = _hm(image, g, MW_ROW_FONT)
    assert e.calls == [("t_ffn", 10, 0)] and r == MARK_FFN                  # row_font = Arial 10 regular
    e, r = _hm(image, g, MW_HDR_FONT)
    assert e.calls == [("t_fdirect_a14b",)] and r == MARK_A14B              # turn clock = Arial 14 bold (direct)
    for size in SL.FONT_POOL_SIZES:
        for v in range(4):                                                     # the pool holds 4 variants
            e, r = _hm(image, g, _pool_font(size, v))
            if size <= SL.FONT_POOL_SMALL_MAX:
                assert e.calls == [("t_ffn", size, v)], (size, v, e.calls)    # face law (NO CONTACTS = (12, 1))
                n = (size * g) // 16
                if (size, v) in SL.FONT_LAW_SLOT_KEYS:                         # t_ffn: Arial on the keyed slot
                    want = ("Arial", n, SL.FONT_VARIANT_FLAGS[v])
                else:                                                          # t_ffn_num: no slot -> the pool
                    snap = SL.find_font_snap(n)
                    want = ("Arial Narrow" if snap > 12 else "Arial", snap,
                            (1 if snap > 12 else 0) | SL.FONT_VARIANT_FLAGS[v])
                assert SL.commlink_pool_font_law(size, v, g) == want, (size, v, g)
            else:                                                              # v1's round ask, unchanged
                n = min(40, max(8, (size * g + 8) >> 4))
                assert e.calls == [("find_font", n, v)], (size, v, e.calls)
                law = SL.commlink_pool_font_law(size, v, g)
                assert law[1] == SL.find_font_snap(n) and law[0] == "Arial Narrow"
    e, r = _hm(image, g, 0x7FF100, cell=15)                                  # off-table: v1 estimate, unchanged
    assert e.calls == [("find_font", min(40, max(8, (12 * g + 8) >> 4)), 1)]


def test_scaling_tutwin_baked_call_is_t_ffn_16_0(image):
    va = PCAVE2 + 0x4000 + 0x63          # push 0; push 16; call t_ffn (the 0x10 is the byte at 0xA10066)
    b = image(va, 7)
    assert b[:4] == bytes([0x6A, SL.TUTWIN_BTN_FONT[1], 0x6A, SL.TUTWIN_BTN_FONT[0]]) and b[4] == 0xE8
    assert va + 9 + struct.unpack("<i", image(va + 5, 4))[0] == T_FFN


# ------------------------------------------------------------------------- vanilla pixels (the laws' evidence)
def _native_rows(png: pathlib.Path, x0, x1, y0, y1, light: bool, thr: int):
    Image = pytest.importorskip("PIL.Image")
    im = Image.open(png).convert("RGB")
    W, H = im.size
    scale = H / 768
    xoff = (W - 1024 * scale) / 2
    rows = []
    for ny in range(y0, y1):
        Y = int((ny + 0.5) * scale)
        row = ""
        for nx in range(x0, x1):
            s = sum(im.getpixel((int(xoff + (nx + 0.5) * scale), Y)))
            row += "#" if ((s > thr) if light else (s < thr)) else "."
        rows.append(row)
    return _trim(rows)


def _trim(rows):
    rows = [r for r in rows if "#" in r]
    lo = min(r.index("#") for r in rows)
    hi = max(r.rindex("#") for r in rows)
    return [r[lo:hi + 1] for r in rows]


_GDI32 = None


def _gdi32():
    """A PRIVATE gdi32 (ctypes.WinDLL, not the process-shared ctypes.windll) with every prototype this module calls.

    Two flake sources this closes (2026-11-15: the CrashLandTooltip case failed ~1 full run in 5, never alone):
    an HDC/HGDIOBJ is a sign-extended 32-bit value, so whenever its bit 31 is set c_void_p hands back
    0xFFFFFFFF8xxxxxxx and an UNDECLARED parameter raises "OverflowError: int too long to convert" (the old
    ReleaseDC(0, GetDC(0)): the screen DC's handle changes on every GetDC); and ctypes.windll's function objects are
    shared by every module in the xdist worker, so prototypes another module sets (or omits) leak in here."""
    global _GDI32
    if _GDI32 is None:
        from ctypes import wintypes as w
        g = ctypes.WinDLL("gdi32", use_last_error=True)
        for name, res, args in (
                ("CreateCompatibleDC", w.HDC, [w.HDC]),
                ("CreateDIBSection", w.HBITMAP, [w.HDC, ctypes.c_void_p, w.UINT, ctypes.POINTER(ctypes.c_void_p),
                                                 w.HANDLE, w.DWORD]),
                ("SelectObject", w.HGDIOBJ, [w.HDC, w.HGDIOBJ]),
                ("PatBlt", w.BOOL, [w.HDC] + [ctypes.c_int] * 4 + [w.DWORD]),
                ("SetBkMode", ctypes.c_int, [w.HDC, ctypes.c_int]),
                ("TextOutW", w.BOOL, [w.HDC, ctypes.c_int, ctypes.c_int, w.LPCWSTR, ctypes.c_int]),
                ("GetTextFaceW", ctypes.c_int, [w.HDC, ctypes.c_int, w.LPWSTR]),
                ("GdiFlush", w.BOOL, []),
                ("CreateFontW", w.HFONT, [ctypes.c_int] * 5 + [w.DWORD] * 8 + [w.LPCWSTR]),
                ("DeleteObject", w.BOOL, [w.HGDIOBJ]),
                ("DeleteDC", w.BOOL, [w.HDC])):
            f = getattr(g, name)
            f.restype, f.argtypes = res, args
        _GDI32 = g
    return _GDI32


def _gdi_glyphs(text: str, face: str, size: int, weight: int):
    """`text` in (face, -size, weight), NONANTIALIASED, black on white, as '#'/'.' rows.  A memory DC on a 32-bpp
    top-down DIB section: no screen DC (nothing shared with the desktop), pixels read straight from the bits."""
    gdi = _gdi32()
    W, H = 160, 40
    dc = gdi.CreateCompatibleDC(None)
    assert dc, f"CreateCompatibleDC failed ({ctypes.get_last_error()})"
    bmi = struct.pack("<IiiHHIIiiII", 40, W, -H, 1, 32, 0, 0, 0, 0, 0, 0)     # BITMAPINFOHEADER, BI_RGB
    bits = ctypes.c_void_p()
    bmp = gdi.CreateDIBSection(dc, bmi, 0, ctypes.byref(bits), None, 0)
    font = gdi.CreateFontW(-size, 0, 0, 0, weight, 0, 0, 0, 0, 0, 0, 3, 0, face)   # NONANTIALIASED_QUALITY
    try:
        assert bmp and bits.value and font, f"GDI object creation failed ({ctypes.get_last_error()})"
        old_bmp = gdi.SelectObject(dc, bmp)
        old_font = gdi.SelectObject(dc, font)
        try:
            got = ctypes.create_unicode_buffer(64)
            gdi.GetTextFaceW(dc, 64, got)
            assert got.value == face, f"{face!r} resolved to {got.value!r}: is the game's arialn.ttf loaded?"
            assert gdi.PatBlt(dc, 0, 0, W, H, 0x00FF0062)                  # WHITENESS
            gdi.SetBkMode(dc, 1)
            assert gdi.TextOutW(dc, 2, 2, text, len(text))
            gdi.GdiFlush()
            px = struct.unpack(f"<{W * H}I", ctypes.string_at(bits.value, W * H * 4))
        finally:
            gdi.SelectObject(dc, old_font)
            gdi.SelectObject(dc, old_bmp)
    finally:
        for obj in (font, bmp):
            if obj:
                gdi.DeleteObject(obj)
        gdi.DeleteDC(dc)
    return _trim(["".join("#" if px[y * W + x] & 0xFFFFFF == 0 else "." for x in range(W)) for y in range(H)])


@pytest.fixture(scope="module")
def game_arialn(need_local):
    if sys.platform != "win32":
        pytest.skip("GDI rendering needs Windows")
    import config
    gd = config.game_dir(required=False)
    if not gd:
        pytest.skip("no game install for arialn.ttf")
    windir = pathlib.Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if any((windir / n).exists() for n in ("ARIALNB.TTF", "arialnb.ttf")):
        pytest.skip("a real Arial Narrow Bold is installed system-wide; the game's synthetic bold cannot be emulated")
    ttf = need_local(pathlib.Path(gd) / "arialn.ttf", "the game's arialn.ttf")
    g = ctypes.WinDLL("gdi32")                                # private prototypes (see _gdi32)
    add, rem = g.AddFontResourceExW, g.RemoveFontResourceExW
    add.argtypes = rem.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    add.restype = rem.restype = ctypes.c_int
    assert add(str(ttf), 0x10, None) > 0                      # FR_PRIVATE
    yield
    rem(str(ttf), 0x10, None)


# (png, native box x0,x1,y0,y1, light text?, threshold, text, the law's native (face, size, weight), a wrong face)
EVIDENCE = [
    ("CrashLandTooltip.png", (341, 386, 728, 745), False, 150, "Close", ("Arial Narrow", 16, 700), ("Arial", 12, 400)),
    ("Save.png", (383, 412, 208, 222), True, 250, "auto", ("Arial", 12, 400), ("Arial Narrow", 14, 700)),
    ("CommlinkMenu.png", (908, 1000, 364, 380), True, 200, "NO CONTACTS", ("Arial", 12, 700), ("Arial Narrow", 14, 700)),
]


@pytest.mark.parametrize("png,box,light,thr,text,want,wrong", EVIDENCE, ids=[e[0] for e in EVIDENCE])
def test_scaling_font_sites_vanilla_pixels(game_arialn, need_local, png, box, light, thr, text, want, wrong):
    path = need_local(PRISTINE / png, "the pristine capture " + png)
    vanilla = _native_rows(path, *box, light, thr)
    assert vanilla == _gdi_glyphs(text, *want), "\n".join(vanilla)
    assert vanilla != _gdi_glyphs(text, *wrong)


def test_gdi_glyphs_ignore_the_shared_ctypes_prototypes(monkeypatch):
    """The GDI renderer is immune to what other modules in the same xdist worker do to ctypes.windll (the 2026-11-15
    flake): it renders the same glyphs with the shared prototypes poisoned, and never touches ctypes.windll."""
    if sys.platform != "win32":
        pytest.skip("GDI rendering needs Windows")
    want = _gdi_glyphs("Close", "Arial", 12, 400)
    shared = getattr(ctypes.windll, "gdi32")              # the process-shared one the other modules mutate
    for name in ("CreateCompatibleDC", "CreateDIBSection", "SelectObject", "CreateFontW", "TextOutW", "DeleteObject"):
        f = getattr(shared, name)
        monkeypatch.setattr(f, "argtypes", None)
        monkeypatch.setattr(f, "restype", ctypes.c_int)
    assert _gdi_glyphs("Close", "Arial", 12, 400) == want
    code = re.sub(r'"""(?:.|\n)*?"""|#[^\n]*', "", pathlib.Path(__file__).read_text(encoding="utf-8"))
    assert not re.search(r"windll\.(gdi32|user32)", code), "use a private ctypes.WinDLL with full prototypes"


def test_scaling_font_sites_evidence_matches_the_laws():
    def face(law_font):
        name, size, style = law_font
        return (name, size, 700 if style & 1 else 400)
    assert face(SL.font_face_law_font(*SL.TUTWIN_BTN_FONT, 16)) == EVIDENCE[0][5]
    assert face(SL.font_face_law_font(*SL.FILEDLG_TEXT_FONT, 16)) == EVIDENCE[1][5]
    assert face(SL.commlink_pool_font_law(12, 1, 16)) == EVIDENCE[2][5]


# ------------------------------------------------------------------------- PrefWin More / Back (2026-11-14)
MORE_SLOT = 0x872140 + 0x970        # PrefWin_btn_more's label font slot
MORE_FONT = PCAVE2 + 0xAFF0         # t_pref_morefont


@pytest.mark.parametrize("g", range(10, SL.G_MAX + 1))
def test_scaling_pref_more_font_is_the_default_label_font(g):
    """More / Back keeps vanilla's default label font (Arial 12 regular, user shot 20261114-171000 glyph-exact), never
    the a14b the other 14 stock buttons get: Arial fl(12g/16) regular at every g."""
    assert SL.PREF_MORE_BTN_FONT == SL.BUTTON_DEFAULT_FONT != SL.BUTTON_SHARED_A14B
    assert SL.button_default_font_law(g) == ("Arial", max(12, (12 * g) // 16) if g > 16 else 12, 0)


def test_scaling_pref_show_thunk_skips_more_and_calls_the_helper():
    """thunk_pref_show's a14b loop covers the first 14 buttons (g_pref_wins puts More last) and then calls
    t_pref_morefont, whose yaml bytes are its assembler's (push 0; push 12; call t_ffn)."""
    with contextlib.redirect_stdout(io.StringIO()):
        import assemble_prefwin as AP
    assert AP.BTNS[-1] == 0x872140 and AP.PCAVE2 + AP.MORE_FONT_OFF == MORE_FONT
    show = " ".join(_yaml_template("thunk_pref_show").split())
    assert "BF 0E 00 00 00 8B 0E" in show and "BF 0F 00 00 00 8B 0E" not in show     # mov edi, 14 (the font loop)
    assert show.count("E8 {rel32:t_pref_morefont}") == 1
    assert show.index("E8 {rel32:t_fdirect_a14b}") < show.index("E8 {rel32:t_pref_morefont}")
    more = _yaml_template("t_pref_morefont").split()
    s, v = SL.PREF_MORE_BTN_FONT
    assert " ".join(more).count(f"6A {v:02X} 6A {s:02X} E8 {{rel32:t_ffn}}") == 1
    code = AP.assemble(AP.asm_more_font(), MORE_FONT)
    asm = [f"{b:02X}" for b in code]
    i = asm.index("E8")
    assert more[:i] == asm[:i] and more[i + 2:] == asm[i + 5:], "t_pref_morefont yaml != assemble_prefwin.asm_more_font"


@pytest.mark.parametrize("seed,ret,want_calls,want_slot", [
    (0x7D3948, MARK_FFN, [("t_ffn", 12, 0)], MARK_FFN),    # seeded slot -> the scaled default label font
    (0, MARK_FFN, [], 0),                                  # unseeded: left alone (the loop's rule)
    (0x7D3948, 0, [("t_ffn", 12, 0)], 0x7D3948),           # t_ffn failed: the native font stays
])
def test_scaling_pref_more_font_helper_emulated(image, seed, ret, want_calls, want_slot):
    e = Emu(image, 25, [(MORE_FONT, 0x20)], ffn_ret=ret)
    e.uc.mem_map(MORE_SLOT & ~0xFFF, 0x1000)
    e.uc.mem_write(MORE_SLOT, struct.pack("<I", seed))
    e.reg("ebx", 0x1111); e.reg("esi", 0x2222); e.reg("edi", 0x3333); e.reg("ebp", 0x4444)
    eip = e.run(MORE_FONT, [Emu.RET])
    assert eip == Emu.RET + 1 and e.reg("esp") == Emu.SP0, "returns to its caller with the stack balanced"
    assert e.calls == want_calls and e.r32(MORE_SLOT) == want_slot
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0x1111, 0x2222, 0x3333, 0x4444)
