"""F36: the main-menu ("+3" path) popup title band's right channel mirrors its left (thunk_title_hmargin v2).

Law (scaling_laws.py, the source of truth): title_band_hmargin_lr -- on Popup_on_draw_background's "+3" path
(0x40600A: the console hidden, i.e. every main-menu popup) the band is [frame_l + fl(4g/16), frame_r - fl(4g/16)), and
at g > 16 the flat band map paints it inclusive, so a non-ornate band's R comes in by one: frame -> band fl(4g/16) - K
on both sides.  v1 painted the right stroke one column out: 8 | 7 at 4K, 4 | 3 at 1080 / 1600x1200, 3 | 2 at 1600x900
(vanilla 3 | 3).  g_title_right is stashed from the same rect, so every consumer reached from this path moves with it.

Proof (ornate_popup_emu.py on image_emu.py: the REAL script-popup builders, console hidden, every engine function
and cave thunk running for real; the popup canvas at draw #1 AND after a full vtbl+0x30 redraw, with every child):
  * Customize-Game-Rules-shaped GOVOPTIONS (type-1 list): in the title band's rows the frame, outer and inner band
    strokes are mirror-symmetric (L == W - 1 - R) and frame -> outer band == fl(4g/16) - K, g 18 / 22 / 25 / 40;
  * the g_title_right consumers on this path, every row mirror-symmetric (every stroke index): COUNCILVOTE (body text
    + list: the UnionRect ring and the d528 text box) at g 22 and 40, NEWBASE (the type-4 field ring) and
    MPRECEIVEFILE (untitled: the untitled stash) at g 22;
  * g = 16 renders pixel-identical to the pristine .bak;
  * the v1 bytes (in memory on the bake) fail: 8 | 7 at 4K.
The in-game rail path (thunk_popup_titleinsets) and the ornate bands are not reachable by v2's change (family gate,
test_title_hmargin_asm_parity.py) and keep their own guards (test_scaling_title_band_channels.py,
test_scaling_ornate_popup_symmetry.py).

COST (~35 s serial, 11 image renders of ~3 s in 10 tests; xdist splits by test, the slowest item ~7 s).  The unit
layer (test_title_hmargin_asm_parity.py, ~1 s) covers every g 1..40 and every family; this module only proves what
it cannot -- the real chain's pixels and the g_title_right consumers moving with the band.
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("pefile", reason="pefile absent")

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

FRAME, OUTER, INNER = 26, 31, 34          # palette indices: popup frame, title outer band / rings, title inner band
RES = {16: (1024, 768), 18: (1600, 900), 22: (1920, 1080), 25: (1600, 1200), 40: (3840, 2160)}
CASES = {
    "GM": dict(kind="XPOP2", label="GOVOPTIONS", flags=0x41),
    "CV": dict(kind="XPOP2", label="COUNCILVOTE", flags=0x41),
    "NB": dict(kind="XPOP", label="NEWBASE", flags=0x17),
    "MR": dict(kind="XPOP2", label="MPRECEIVEFILE", flags=0),
}
V1 = "B8 04 00 00 00 0F AF 05 {abs32:g_popup_scale_num} C1 F8 04 48 01 45 EC 29 45 F4 BB 03 00 00 00 C3"

_R: dict = {}


@pytest.fixture(scope="module")
def images(tmp_path_factory, baked_exe, bak_path):
    """{'after': the bake, 'pristine': the .bak, 'v1': the bake with thunk_title_hmargin's v1 bytes at its slot}."""
    import pefile
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    st = ap.build_symbol_table(symbols, caves)
    va = st["thunk_title_hmargin"]
    data = bytearray(Path(baked_exe).read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    v1 = ap.ByteTemplate(V1).resolve(va, st)
    data[off:off + 51] = v1 + b"\x00" * (51 - len(v1))
    d = tmp_path_factory.mktemp("title_hmargin")
    (d / "v1.exe").write_bytes(bytes(data))
    return {"after": str(baked_exe), "pristine": str(bak_path), "v1": str(d / "v1.exe")}


def _render(images, which, case, g):
    key = (which, case, g)
    if key not in _R:
        import ornate_popup_emu as O
        hh = O.H(images[which], *RES[g], ornate_mode=False, mainwin=False, later=True, **CASES[case])
        _R[key] = dict(g=hh.g, typ=hh.typ_raw, d1=hh.composite("draw1"), later=hh.composite("later"))
        hh.e.uc = None
        hh.e = None
        del hh
        gc.collect()
    return _R[key]


def _asym_rows(c, rows, idx=(FRAME, OUTER, INNER)):
    w = c.shape[1]
    bad = []
    for v in idx:
        for y in rows:
            xs = np.nonzero(c[y] == v)[0]
            if len(xs) >= 2 and xs.min() != w - 1 - xs.max():
                bad.append((v, y, int(xs.min()), int(w - 1 - xs.max())))
    return bad


def _band_channels(c, g):
    """frame -> outer band clear columns L | R on a row inside the band."""
    y = (16 * g) >> 4
    row = c[y]
    fr = np.nonzero(row == FRAME)[0]
    ob = np.nonzero(row == OUTER)[0]
    mid = c.shape[1] // 2
    fl, frr = fr[fr < mid].max(), fr[fr > mid].min()
    return int(ob.min() - fl - 1), int(frr - ob.max() - 1), int(fl + 1)       # (L, R, frame stroke K)


@pytest.mark.parametrize("g", (18, 22, 25, 40))
def test_main_menu_band_is_mirror_symmetric(images, g):
    r = _render(images, "after", "GM", g)
    assert r["g"] == g and r["typ"] == 0
    band = range((4 * g) >> 4, (28 * g) >> 4)
    for which in ("d1", "later"):
        c = r[which]
        assert _asym_rows(c, band) == [], which
        L, R, k = _band_channels(c, g)
        assert L == R == ((4 * g) >> 4) - k, (which, L, R, k)


@pytest.mark.parametrize("case, g", (("CV", 22), ("CV", 40), ("NB", 22), ("MR", 22)))
def test_title_right_consumers_mirror(images, case, g):
    """The body ring / d528 text box (CV), the type-4 field ring (NB) and the untitled stash's chrome (MR) on the
    main-menu path: every row of every stroke index mirror-symmetric -- they moved with g_title_right."""
    r = _render(images, "after", case, g)
    assert r["g"] == g
    for which in ("d1", "later"):
        c = r[which]
        assert _asym_rows(c, range(c.shape[0])) == [], (case, which)


def test_g16_is_pristine(images):
    for case in ("GM",):
        a = _render(images, "pristine", case, 16)
        b = _render(images, "after", case, 16)
        for which in ("d1", "later"):
            assert a[which].shape == b[which].shape and (a[which] == b[which]).all(), (case, which)
        assert _band_channels(b["d1"], 16)[:2] == (3, 3)


def test_v1_bytes_fail(images):
    r = _render(images, "v1", "GM", 40)
    assert _band_channels(r["d1"], 40)[:2] == (8, 7)
    assert _asym_rows(r["d1"], range(10, 70)) != []
