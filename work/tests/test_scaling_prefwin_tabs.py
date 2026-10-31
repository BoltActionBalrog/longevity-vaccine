"""The PREFERENCES window's left CATEGORY column on ONE pitch (2026-10-27 wave-8 W8P; user-reported from in-game shots).

DEFECT (measured, deployed bake d34e2291 = the user's shots): the seven category buttons (the six stock tabs + uimod.dll's
"Longevity Mod Preferences") are PrefWin child windows at native (33, 10 + 22 i, 214, 20) and thunk_pref_gwinit floored
each arg on its own, so their tops fl((10 + 22 i) g/16) stepped unevenly and vanilla's equal gaps (all 2) alternated:
4,3,3,3,4,3 at 1920x1080 (g 22), 3,2,3,2,3,2 at 1280x1024 (g 20), 4,3,3,4,3,3 at 1600x1200 (g 25); even only at g 24 / 40.

USER DECISION (2026-10-27): one uniform pitch; the first top (fl(10g/16): the frame chain prefwin_layout reads only that)
and the face height fl(20g/16) unchanged; the slack (the column ends -3..+2 px off its floor position) goes into the space
above Gamma Correction, which -- with Restore Defaults / OK / Cancel -- stays where it is.

Law (scaling_laws.py): pref_tab_pitch (P = half_down(22g, 16): the repo's uniform-pitch law -- the PITCH obeys LAW 1, the
gap is what the floored face leaves, option_row_gap / nutgrid_layout), pref_tab_row (which children are column rows),
pref_child_y (the child arm's y).  Port: t_pref_tabrow (pcave2 0x3E5C0, the free tail of W6A's region), CALLed by
thunk_pref_gwinit's child arm before it floors x / w / h (assemble_prefwin.emit_w6a; its bytes are pinned by
test_scaling_prefwin_halfopen.test_shipped_bytes_are_the_assembler too).

The DLL places nothing itself: its tab reaches GraphicWin_init with NATIVE args from the engine statics (prefs.cpp
BuildWidgets), so the exe's gate moves it with the stock six.  The child window's rect (+0x13C) is both what draws and what
the engine hit-tests (get_mouse_window_recurse -> PtInRect 0x5FA7E0 on +0x13C), so the clicks follow the buttons.

Proof layers (conftest `baked_exe`):
  1. laws: g <= 16 the identity; g 17..256 the gaps equal, row 0 at fl(10g/16), the face fl(20g/16), the pitch within
     0.5 px of 22g/16, the column clear of Gamma (with and without the DLL tab); only the column's rows are recognised;
  2. Unicorn on the shipped bytes: thunk_pref_gwinit's child arm (-> t_pref_tabrow) == the law for g 1..64 over every
     PrefWin child's native args plus near misses; the page-attach exemption untouched; callee-saved registers and ecx
     (GraphicWin_init is thiscall) preserved;
  3. END TO END (prefwin_tabs_emu.py): the real PrefWin_build + uimod.dll's two changes at the seven standard screens:
     the engine's child rects == the law, every gap equal, Gamma / Restore / OK / Cancel unchanged from the deployed
     floor; 1024x768 the pristine rects (PRISTINE_1024, measured on the .bak); the stock-only (no DLL) column too; and
     the HIT TEST through the real PrefWin_show at 1280x1024 / 1920x1080: every device row of the column resolves to its
     button, every gap to PrefWin.

ONE BOOT PER g (the module fixture `screen`): g is fixed per process in game (g_popup_scale_num is set once from the
screen size; a mid-game resolution switch is unreachable), so every check at one screen reads one booted image.  At
1920x1080 that boot runs a stock-only PrefWin_build first and then the DLL's build -- the engine's own re-init on a game
load -- so the stock-only, column and click checks share it.

COST: layers 1-2 cheap.  Layer 3: one boot + PrefWin_build per screen (~2-4 s); the two hit-test screens add
MainWin_build + PrefWin_show (~6-7 s each), paid once by the module fixture whichever of their items runs first.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_prefwin as AP  # noqa: E402
import scaling_laws as SL  # noqa: E402

fl = SL.popup_scale_floor
ROWS = SL.PREF_TAB_ROWS
#: the standard screens (the per-resolution report table) -> g
SCREENS = ((1024, 768), (1280, 1024), (1600, 900), (1920, 1080), (1600, 1200), (2560, 1440), (3840, 2160))
#: every PrefWin child's NATIVE GraphicWin_init args that is NOT a column row (measured on the pristine image at
#: 1024x768: Gamma on row 7 / the DLL's row 8, Restore Defaults / OK / Cancel, More, the audio page's Off toggles; the
#: page list; uimod.dll's option rows at the frame x) plus near misses of the row pattern
NOT_ROWS = ([(33, 164, 214, 20), (33, 186, 214, 20), (33, 314, 214, 20), (33, 337, 214, 20), (33, 360, 214, 20),
             (256, 360, 214, 20), (256, 10, 457, 270), (256, 13, 300, 22), (256, 32, 214, 20)]
            + [(259, 290 + 22 * k, 120, 20) for k in range(4)]
            + [(33, 10 + 22 * i + d, 214, 20) for i in range(ROWS) for d in (-1, 1, 11)]
            + [(33 + dx, 10 + 22 * i, 214 + dw, 20 + dh) for i in (0, 3, 6)
               for dx, dw, dh in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]
            + [(33, 10 - 22, 214, 20), (33, 10 + 22 * ROWS, 214, 20), (33, -100, 214, 20), (33, 0, 214, 20)])
ROW_ARGS = [(33, 10 + 22 * i, 214, 20) for i in range(ROWS)]


def screen_g(w, h):
    return max(16, min(SL.G_MAX, (16 * min(w * 768, h * 1024)) // (1024 * 768)))


def law_rows(g, n=ROWS):
    """The column's device rects (half-open, PrefWin-local) by the law."""
    out = []
    for x, y, w, h in ROW_ARGS[:n]:
        if g <= 16:
            out.append((x, y, x + w, y + h))
        else:
            t = SL.pref_child_y(x, y, w, h, g)
            out.append((fl(x, g), t, fl(x, g) + fl(w, g), t + fl(h, g)))
    return out


# ============================================================================== 1. laws
@pytest.mark.parametrize("g", range(1, 17))
def test_law_native_identity(g):
    assert SL.pref_tab_pitch(g) == 22
    for args in ROW_ARGS + NOT_ROWS:
        assert SL.pref_child_y(*args, g) == args[1]


def test_law_recognises_only_the_column():
    assert [SL.pref_tab_row(*a) for a in ROW_ARGS] == list(range(ROWS))
    for a in NOT_ROWS:
        assert SL.pref_tab_row(*a) is None, a


@pytest.mark.parametrize("g", range(17, 257))
def test_law_one_pitch(g):
    rows = law_rows(g)
    p, h = SL.pref_tab_pitch(g), fl(20, g)
    assert rows[0][1] == fl(10, g), "row 0 keeps its floor top (prefwin_layout reads fl(10g/16))"
    assert all(r[3] - r[1] == h for r in rows), "the face height fl(20g/16) on every row"
    gaps = [rows[i + 1][1] - rows[i][3] for i in range(ROWS - 1)]
    assert len(set(gaps)) == 1 and gaps[0] == p - h >= 1, ("every gap equal and visible", gaps)
    assert abs(16 * p - 22 * g) <= 8, "the pitch within 0.5 px of vanilla x g/16 (LAW 1 on the pitch)"
    err16 = abs(16 * gaps[0] - 2 * g)
    assert err16 <= 18, "the gap within 1.125 px of vanilla x g/16"
    assert (err16 > 16) == (g % 8 == 7), "> 1 px only at g = 7 mod 8 (23, 31, ...: reported to the user)"
    drift = rows[-1][1] - fl(142, g)
    assert -3 <= drift <= 2, "the column ends -3..+2 px off its floor position"
    for gamma_y, n in ((186, ROWS), (164, ROWS - 1)):          # with the DLL's tab (Gamma row 8) / stock only (row 7)
        assert fl(gamma_y, g) - law_rows(g, n)[-1][3] > gaps[0], "the column clear of Gamma"


# ============================================================================== 2. the shipped bytes
STACK, SP0 = 0x10000000, 0x10080000
WIN = 0x858338                       # the window being inited (ecx): any; GraphicWin_init is thiscall
REGS = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def img(baked_exe):
    data = Path(baked_exe).read_bytes()
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for s in pe.sections:
        va = ib + s.VirtualAddress
        mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
        mu.mem_write(va, s.get_data())
    mu.mem_map(STACK, 0x100000)
    mu.mem_map(0, 0x1000)                       # fs:[0] (the gwinit resume's displaced `mov eax, fs:[0]`)
    mu.mem_write(AP.GWINIT_RESUME, b"\xF4")
    for va, v in ((AP.TAB_X, 33), (AP.TAB_Y0, 10), (AP.TAB_W, 214), (AP.TAB_H, 20)):    # PrefWin_build's statics
        mu.mem_write(va, struct.pack("<i", v))
    return mu


def test_sites(img, symtab):
    assert symtab["t_pref_tabrow"] == AP.PCAVE2 + AP.T_PREF_TABROW_OFF
    off, b = AP.emit_w6a()["t_pref_tabrow"]
    assert bytes(img.mem_read(AP.PCAVE2 + off, len(b))) == b
    gw = AP.emit_w6a()["thunk_pref_gwinit"][1]
    assert bytes(img.mem_read(symtab["thunk_pref_gwinit"], len(gw))) == gw
    call = gw.find(b"\xE8")
    while call >= 0 and symtab["thunk_pref_gwinit"] + call + 5 + struct.unpack_from("<i", gw, call + 1)[0] \
            != symtab["t_pref_tabrow"]:
        call = gw.find(b"\xE8", call + 1)
    assert call >= 0, "thunk_pref_gwinit's child arm calls t_pref_tabrow"


def _gwinit(mu, va, g, args, ret):
    mu.mem_write(0x668740, struct.pack("<I", g))
    esp = SP0 - 0x40
    mu.mem_write(esp, struct.pack("<I4i4I", ret, *args, 0, 0, 0x8578D8, 0))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, WIN)
    for i, r in enumerate(REGS):
        mu.reg_write(r, 0x5A5A0000 + i)
    try:
        mu.emu_start(va, 0, count=4000)
    except Exception:                           # noqa: BLE001  (hlt at the resume stub ends the run)
        pass
    assert mu.reg_read(UC_X86_REG_EIP) in (AP.GWINIT_RESUME, AP.GWINIT_RESUME + 1), hex(mu.reg_read(UC_X86_REG_EIP))
    assert mu.reg_read(UC_X86_REG_ESP) == esp, "the resume sees GraphicWin_init's own frame"
    assert mu.reg_read(UC_X86_REG_ECX) == WIN, "ecx (thiscall this) preserved"
    assert [mu.reg_read(r) for r in REGS] == [0x5A5A0000 + i for i in range(len(REGS))]
    return struct.unpack("<4i", bytes(mu.mem_read(esp + 4, 16)))


@pytest.mark.parametrize("g", list(range(1, 65)))
def test_gwinit_child_arm_is_the_law(img, symtab, g):
    va = symtab["thunk_pref_gwinit"]
    for args in ROW_ARGS + NOT_ROWS:
        got = _gwinit(img, va, g, args, 0x607300)                       # BaseButton_init's call
        if g <= 16:
            assert got == args
        else:
            x, y, w, h = args
            assert got == (fl(x, g), SL.pref_child_y(x, y, w, h, g), fl(w, g), fl(h, g)), (g, args, got)
        assert _gwinit(img, va, g, args, 0x60E900) == args, "the page-attach path keeps its own law"


@pytest.mark.parametrize("y0", (0, 7, 10, 31))
def test_thunk_reads_the_statics(img, symtab, y0):
    """The row pattern and row 0's top come from the engine's statics, as PrefWin_build / the DLL compute the args."""
    img.mem_write(AP.TAB_Y0, struct.pack("<i", y0))
    try:
        for g in (17, 22, 25, 40):
            for i in range(ROWS):
                got = _gwinit(img, symtab["thunk_pref_gwinit"], g, (33, y0 + 22 * i, 214, 20), 0x607300)
                assert got[1] == SL.pref_child_y(33, y0 + 22 * i, 214, 20, g, y0=y0) == fl(y0, g) + i * SL.pref_tab_pitch(g)
    finally:
        img.mem_write(AP.TAB_Y0, struct.pack("<i", 10))


# ============================================================================== 3. end to end
#: the pristine image's column at 1024x768 (prefwin_tabs_emu.column on the .bak 2d0b1438, 2026-10-27; with the DLL's
#: changes, and stock-only: Gamma on row 7): the native rects the baked image must reproduce at g = 16
PRISTINE_1024 = {"tabs": [(33, 10 + 22 * i, 247, 30 + 22 * i) for i in range(ROWS)], "gamma": (33, 186, 247, 206),
                 "stock_gamma": (33, 164, 247, 184), "bottom": [(33, 314, 247, 334), (33, 337, 247, 357),
                                                                (33, 360, 247, 380)]}
SHOW_SCREENS = ((1280, 1024), (1920, 1080))          # the hit-test screens: booted through PrefWin_show
STOCK_SCREEN = (1920, 1080)                          # also carries the stock-only build


def on_screen(wh):
    """wh as a param, its items one xdist unit with every other item of that screen (the shared boot)."""
    return pytest.param(wh, id=f"{wh[0]}x{wh[1]}", marks=pytest.mark.xdist_group(f"prefwin_tabs_{wh[0]}x{wh[1]}"))


@pytest.fixture(scope="module")
def screen(baked_exe):
    """screen(w, h) -> the module's one prefwin_tabs_emu.Column for that screen (one boot per g)."""
    import prefwin_tabs_emu as PT
    cache = {}

    def get(w, h):
        if (w, h) not in cache:
            cache[(w, h)] = PT.column(str(baked_exe), w, h, show=(w, h) in SHOW_SCREENS, stock=(w, h) == STOCK_SCREEN)
        return cache[(w, h)]
    return get


@pytest.mark.parametrize("wh", [on_screen(wh) for wh in SCREENS])
def test_e2e_column(screen, wh):
    c = screen(*wh)
    g = c.g
    assert g == screen_g(*wh)
    assert c.tabs == law_rows(g), (wh, c.tabs)
    gaps = [c.tabs[i + 1][1] - c.tabs[i][3] for i in range(ROWS - 1)]
    assert len(set(gaps)) == 1, gaps
    f = (lambda v: v) if g <= 16 else (lambda v: fl(v, g))                # noqa: E731
    assert c.gamma == (f(33), f(186), f(33) + f(214), f(186) + f(20)), "Gamma stays on its floor (the DLL's row 8)"
    assert c.bottom == [(f(33), f(y), f(33) + f(214), f(y) + f(20)) for y in (314, 337, 360)], "Restore / OK / Cancel"
    if g == 16:
        assert (c.tabs, c.gamma, c.bottom) == (PRISTINE_1024["tabs"], PRISTINE_1024["gamma"], PRISTINE_1024["bottom"]),             "g = 16: the pristine rects"


@pytest.mark.xdist_group(f"prefwin_tabs_{STOCK_SCREEN[0]}x{STOCK_SCREEN[1]}")
def test_e2e_column_stock_only(screen):
    """No uimod.dll: the six stock tabs on the pitch, Gamma on its row-7 floor."""
    c = screen(*STOCK_SCREEN)
    assert c.g == 22 and c.stock_tabs == law_rows(22, ROWS - 1)
    assert c.stock_gamma[1] == fl(164, 22)


@pytest.mark.parametrize("wh", [on_screen(wh) for wh in SHOW_SCREENS])
def test_e2e_clicks_follow_the_buttons(screen, wh):
    """The engine's own Win_get_mouse_window on the shown window: every device row of the column resolves to its
    button (both x edges and the middle), every gap and the slack above Gamma to PrefWin, Gamma to Gamma."""
    c = screen(*wh)
    assert c.tabs == law_rows(c.g)
    l, r = c.tabs[0][0], c.tabs[0][2]
    for y in range(c.tabs[0][1] - 2, c.gamma[3] + 2):
        want = next((i for i, t in enumerate(c.tabs) if t[1] <= y < t[3]), None)
        if want is None:
            want = "gamma" if c.gamma[1] <= y < c.gamma[3] else "prefwin"
        for x in (l, (l + r) // 2, r - 1):
            assert c.hit(x, y) == want, (wh, x, y)
    assert c.hit(l - 1, c.tabs[0][1]) == "prefwin" and c.hit(r, c.tabs[0][1]) == "prefwin"
