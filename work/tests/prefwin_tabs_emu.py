"""The PREFERENCES window's left CATEGORY column on the real image (image_emu.py), in the engine's order (2026-10-27
wave-8 W8P):

  column(exe, W, H)   a fresh boot at 1024x768, the interface strings, SW / SH written and g recomputed by the image's
                      own thunk_ensure_scale; uimod.dll's two PrefWin changes reproduced as the DLL makes them -- the
                      Gamma button's `add edx, 0x9A` imm @0x48DD03 -> 0xB0 (prefs.cpp gammaNew, written before the
                      build) and, after the real PrefWin_build 0x48D840, its "Longevity Mod Preferences" tab:
                      FlatButton_ctor 0x607CF0 + BaseButton_init 0x607210(text, 0x5F, [0x85788C], [0x857890] + 0x84,
                      [0x857894], [0x686B88], PrefWin, 0) (prefs.cpp BuildWidgets; its block registered in
                      g_dll_pref_lo / _hi first, as BuildWidgets does, so the zoom stubs draw it) -- so every row reaches
                      GraphicWin_init through the baked thunk_pref_gwinit exactly as in game.  dll=False: the stock
                      six tabs, Gamma on row 7.
                      stock=True (with dll): a stock-only PrefWin_build FIRST (its six rows and Gamma kept as
                      .stock_tabs / .stock_gamma), then the DLL's changes and a second PrefWin_build -- the engine's
                      own re-init (desktop_init reruns PrefWin_build on every game load), so one boot serves both.
                      show=True: also the real MainWin_build (the PrefWin_show path needs it) and PrefWin_show 0x48FA00
                      (page 0) up to its modal loop, so the HIT TEST runs on the shown window: hit(x, y) is the engine's
                      own Win_get_mouse_window 0x5F6F10 (screen point -> window).  PrefWin's parent is MapWin_g
                      0x939444, which the emulator never builds; its visible bit is set (in game the map is up).

Rects are the engine's child rects (+0x13C, PrefWin-local, half-open) read after the build (and the show).  Measured
against the user's 1920x1080 shot terranx_pracx_1920x1080_20261027-090141.png on the deployed bake d34e2291: the
column's runs at x 535 are exactly the emulator's rects (13..40, 44..71, ..., 195..222; Gamma 255..282).
"""
import os

import assemble_prefwin as AP
import image_emu as IE
import prefwin_halfopen_emu as PH

PREFWIN = 0x8578D8
TABS = (0x858338, 0x858E84, 0x8599D0, 0x85A51C, 0x85B068, 0x85BBB4)     # PrefWin_btn_prefs .. PrefWin_btn_map
GAMMA = 0x85C700
BOTTOM = (0x86FF5C, 0x8715F4, 0x870AA8)                                 # Restore Defaults, OK, Cancel
TAB_X, TAB_Y0, TAB_W, TAB_H = 0x85788C, 0x857890, 0x857894, 0x686B88
GAMMA_IMM = 0x48DD03                     # PrefWin_build's `add edx, 0x9A` (the Gamma row) imm, uimod.dll writes 0xB0
FLATBUTTON_CTOR, BASEBUTTON_INIT = 0x607CF0, 0x607210
GET_MOUSE_WINDOW = 0x5F6F10
MAPWIN = 0x939444
DLL_TAB_ID, DLL_TAB_DY = 0x5F, 0x84       # prefs.cpp kTabId / kTabRowY


def _rect(e, a):
    return tuple(e.s32(a + 0x13C + 4 * i) for i in range(4))


class Column:
    def __init__(self, e, g, rows, dll_tab):
        self.e, self.g, self.rows, self.dll_tab = e, g, rows, dll_tab
        rect = lambda a: _rect(e, a)                                          # noqa: E731
        self.tabs = [rect(a) for a in rows]
        self.gamma = rect(GAMMA)
        self.bottom = [rect(a) for a in BOTTOM]
        self.win = rect(PREFWIN)
        self._pt = None

    def hit(self, x, y):
        """The window Win_get_mouse_window resolves at PrefWin-local (x, y): a row index, 'gamma', 'prefwin' or the VA."""
        e = self.e
        if self._pt is None:
            self._pt = e.alloc(8)
        e.w32(self._pt, self.win[0] + x)
        e.w32(self._pt + 4, self.win[1] + y)
        r = e.call(GET_MOUSE_WINDOW, args=(self._pt, self._pt + 4))
        if r in self.rows:
            return self.rows.index(r)
        return {GAMMA: "gamma", PREFWIN: "prefwin"}.get(r, r)


def column(exe, w, h, dll=True, show=False, stock=False):
    os.environ.setdefault("SMACX_EXE_NAME", "terranx_PRACX.exe")
    IE.HEAP_SZ = max(IE.HEAP_SZ, 0x10000000)
    e = IE.boot(exe, 1024, 768)
    patched = bytes(e.uc.mem_read(0x4A4418, 1)) == b"\xE9"
    if patched and show:
        sym = PH._symtab()
        for k in PH.VPDONE:
            e.w32(sym[k], 1)
    IE.Files(e)
    e.uc.mem_write(0x9B8AA8, b"xscript\0")
    e.call(0x455610, count=0)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
    e.call(0x616A00, count=50_000_000)
    e.stub_fn(0x514880, lambda e: 0, popbytes=4)        # MapWin repaint (the map window, not PrefWin)
    e.w32(IE.SW, w)
    e.w32(IE.SH, h)
    if patched:
        e.w32(IE.GSCALE, 0)
        e.call(PH.ENSURE_SCALE)
    if show:
        e.call(PH.MAINWIN_BUILD, ecx=PH.MAINWIN, count=2_000_000_000)
        e.w32(PH.MAINWIN + 0x9C, e.r32(PH.MAINWIN + 0x9C) | 1)
    rows = list(TABS)
    stock_tabs = stock_gamma = None
    if dll and stock:
        e.call(PH.BUILD, ecx=PREFWIN, count=200_000_000)
        stock_tabs, stock_gamma = [_rect(e, a) for a in TABS], _rect(e, GAMMA)
    if dll:
        assert bytes(e.uc.mem_read(GAMMA_IMM - 2, 6)) == b"\x81\xC2\x9A\x00\x00\x00", "prefs.cpp gammaExpect"
        e.uc.mem_write(GAMMA_IMM, b"\xB0")
        if stock:                                         # the stock build ran this code: drop its translated block
            e.uc.ctl_remove_cache(GAMMA_IMM - 2, GAMMA_IMM + 4)
    e.call(PH.BUILD, ecx=PREFWIN, count=200_000_000)
    if dll:
        tab = e.alloc(0xC00)                              # prefs.cpp: FlatButton storage padded to 0xC00
        if patched:                                       # BuildWidgets registers its block FIRST (the zoom stubs)
            e.w32(AP.G_DLL_LO, tab)
            e.w32(AP.G_DLL_HI, tab + 0xC00 - 1)
        e.call(FLATBUTTON_CTOR, ecx=tab)
        e.call(BASEBUTTON_INIT, ecx=tab, args=(e.cstr("Longevity Mod Preferences"), DLL_TAB_ID, e.s32(TAB_X),
                                               e.s32(TAB_Y0) + DLL_TAB_DY, e.s32(TAB_W), e.s32(TAB_H), PREFWIN, 0))
        rows.append(tab)
    if show:
        e.w32(PH.PREFS, e.r32(PH.PREFS) & ~PH.SLIDE_ANIM)
        e.observe(PH.MODAL, lambda e: e.uc.emu_stop())
        try:
            e.call(PH.SHOW, ecx=PREFWIN, args=(0,), count=2_000_000_000)
        except RuntimeError as x:
            if "stopped" not in str(x):
                raise
        e.w32(MAPWIN + 0x9C, e.r32(MAPWIN + 0x9C) | 1)
    c = Column(e, e.r32(IE.GSCALE) if patched else 16, rows, dll)
    c.stock_tabs, c.stock_gamma = stock_tabs, stock_gamma
    return c
