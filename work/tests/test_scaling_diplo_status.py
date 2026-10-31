"""Diplomacy talk screen: the "DIPLOMATIC STATUS: <treaty>" line fit (scaling_laws.diplo_status_*).

Defect (user shot 3840x2160 20261006-221655): at 4K "DIPLOMATIC STATUS: NONE" wrapped onto two lines; vanilla
(refs\\pristine\\Diplomacy\\Opening.png) keeps it on one.  Vanilla fits it at 2 px of slack (161 px in 163), so
GDI's per-size advance rounding pushes fl(12g/16) over the fl-scaled budget at some g (4K: 411 in 410).

Measures: the real GDI advance widths of the +0xA44 face (g_hud_font_name = "Arial", regular, lfHeight = -size,
exactly Font_init's LOGFONT) when this host has the face; otherwise a deterministic stand-in with the same
non-linear per-size rounding shape (the law is measure-agnostic -- the thunk measures in-game).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scaling_laws as SL  # noqa: E402

GS = list(range(16, 65))

# The strings the line can show: label 0xE98 + ": " + treaty word (labels 0xA14/0xA10/0xA0C/0xA1C/0x64),
# CharUpper'd by the painter (0x43FDEF).  INFILTRATION is the next wrap_3 (0x43FE97) -- checked for slack.
STATUS = ["DIPLOMATIC STATUS: NONE", "DIPLOMATIC STATUS: PACT", "DIPLOMATIC STATUS: TRUCE",
          "DIPLOMATIC STATUS: TREATY", "DIPLOMATIC STATUS: VENDETTA"]
INFIL = ["INFILTRATION: INACTIVE", "INFILTRATION: ACTIVE"]


def _gdi_measure():
    if sys.platform != "win32":
        return None
    import ctypes
    gdi = ctypes.windll.gdi32
    hdc = gdi.CreateCompatibleDC(0)
    if not hdc:
        return None

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    face = ctypes.create_string_buffer(32)
    f = gdi.CreateFontA(-12, 0, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0, 0, b"Arial")
    old = gdi.SelectObject(hdc, f)
    gdi.GetTextFaceA(hdc, 32, face)
    gdi.SelectObject(hdc, old)
    gdi.DeleteObject(f)
    if face.value != b"Arial":
        return None
    cache = {}

    def width(size, text):
        k = (size, text)
        if k not in cache:
            f = gdi.CreateFontA(-size, 0, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0, 0, b"Arial")
            old = gdi.SelectObject(hdc, f)
            sz = SIZE()
            gdi.GetTextExtentPoint32A(hdc, text.encode(), len(text), ctypes.byref(sz))
            gdi.SelectObject(hdc, old)
            gdi.DeleteObject(f)
            cache[k] = sz.cx
        return cache[k]
    return width


GDI = _gdi_measure()


def standin_width(size, text):
    """Deterministic stand-in: per-glyph advance rounded per size (the non-linearity that causes the defect)."""
    return sum((size * (40 + (ord(c) * 7) % 23) + 37) // 72 for c in text)


MEASURES = [pytest.param(standin_width, id="standin")]
if GDI is not None:
    MEASURES.insert(0, pytest.param(GDI, id="gdi"))


# ---- geometry ------------------------------------------------------------------------------------------------

def test_native_budget_is_vanillas_wrap_width():
    """g=16 reproduces vanilla's arithmetic: panel0 269..511, x = 342, w = 163 (static map 0x43FA90)."""
    assert SL.diplo_status_panel0(16) == (269, 511)
    assert SL.diplo_status_wrap(16) == (342, SL.DIPLO_STATUS_NATIVE_W) == (342, 163)


def test_budget_matches_the_baked_rect_table_at_4k_and_1600():
    """The device panel equals the shipped t_dp_box_panel output on the proto-logged worlds
    (test_diplo_asm_parity TABLE40_POST / TABLE25_POST 0x20F4 from the DC0 seeds)."""
    assert SL.diplo_status_panel0(40, (655, 1907)) == (672, 672 + (1218 + 7) // 2 - 7)
    assert SL.diplo_status_wrap(40, (655, 1907)) == (853, 410)
    assert SL.diplo_status_wrap(25, (409, 1192))[1] == 259
    assert SL.diplo_status_wrap(40) == SL.diplo_status_wrap(40, (655, 1907))


@pytest.mark.parametrize("g", GS)
def test_budget_is_proportionate(g):
    """w tracks 163 x g/16 to within the floor cascade of its six floored terms (|error| < 7 px; the subtracted
    insets floor down, so the budget errs WIDE -- the fit is not compensating for a short budget)."""
    x, w = SL.diplo_status_wrap(g)
    assert 0 <= w - 163 * g / 16 < 7


# ---- the fit law ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("measure", MEASURES)
@pytest.mark.parametrize("text", STATUS + ["X" * 40])
@pytest.mark.parametrize("g", GS)
def test_fit_law(measure, text, g):
    """vanilla one line -> one line at g at the largest size <= fl(12g/16) that fits (or the minimum);
    vanilla wraps -> fl(12g/16) untouched; g <= 16 -> 12."""
    w = SL.diplo_status_wrap(g)[1]
    size = SL.diplo_status_font_size(g, lambda s: measure(s, text), w)
    start = SL.dp(12, g)
    if g <= 16:
        assert size == 12
        return
    assert SL.DIPLO_STATUS_FONT_MIN <= size <= start
    if measure(12, text) > SL.DIPLO_STATUS_NATIVE_W:
        assert size == start                       # vanilla wraps: its own layout, never shrunk
        return
    assert measure(size, text) <= w or size == SL.DIPLO_STATUS_FONT_MIN
    if size < start:
        assert measure(size + 1, text) > w         # largest size that fits: no gratuitous shrink


@pytest.mark.skipif(GDI is None, reason="GDI Arial unavailable")
def test_vanilla_line_counts():
    """Vanilla (12 px, 163 px): NONE / PACT one line, TRUCE / TREATY / VENDETTA two -- the pristine shot shows NONE
    on one line."""
    fits = {t: GDI(12, t) <= 163 for t in STATUS}
    assert fits == {STATUS[0]: True, STATUS[1]: True, STATUS[2]: False, STATUS[3]: False, STATUS[4]: False}


@pytest.mark.skipif(GDI is None, reason="GDI Arial unavailable")
def test_reported_defect_and_fix_at_4k_and_1600():
    w40, w25 = SL.diplo_status_wrap(40)[1], SL.diplo_status_wrap(25)[1]
    none = STATUS[0]
    assert GDI(30, none) > w40                      # the reported 4K wrap (411 > 410)
    assert SL.diplo_status_font_size(40, lambda s: GDI(s, none), w40) == 29
    assert GDI(18, none) <= w25                     # 1600 already fits: unchanged
    assert SL.diplo_status_font_size(25, lambda s: GDI(s, none), w25) == 18


@pytest.mark.skipif(GDI is None, reason="GDI Arial unavailable")
@pytest.mark.parametrize("g", GS)
def test_every_one_line_status_fits_after_the_law(g):
    w = SL.diplo_status_wrap(g)[1]
    for t in STATUS:
        if GDI(12, t) <= 163:
            size = SL.diplo_status_font_size(g, lambda s, t=t: GDI(s, t), w)
            assert GDI(size, t) <= w, (g, t, size)
            assert size >= SL.dp(12, g) - 2, (g, t, size)   # a pixel-rounding correction, not a resize


@pytest.mark.skipif(GDI is None, reason="GDI Arial unavailable")
@pytest.mark.parametrize("g", GS)
def test_infiltration_line_needs_no_fit(g):
    """The INFILTRATION wrap (0x43FE97, same font, same budget) keeps >= 10% slack at fl(12g/16): no fit there."""
    w = SL.diplo_status_wrap(g)[1]
    for t in INFIL:
        assert GDI(SL.dp(12, g), t) <= 0.9 * w, (g, t)
