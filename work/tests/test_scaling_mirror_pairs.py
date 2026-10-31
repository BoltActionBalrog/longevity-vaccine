"""Two mirrored pairs (2026-10-25 wave-3 W3A):

F43 -- the Council YES / NO / ABSTAIN row (CouncilWin_exec 0x427661..0x427776).  The thirds' `lea edx, [edx+ecx-3]`
       disp8 (0x427707) was missing from g_cw_immtab, so the cells stayed third - 3 wide against sc(3) seams and the row
       ran 3 * (sc(3) - 3) - rem px past the VOTE's right edge: from g = 22 on the real console, over the d5a0 ring
       stroke from g = 26 (4K third[2] = (2136, 2541) on screen against R = 2530, 6 px into the stroke).  Laws:
       council_button_row (thirds_engine = the block with every native 3 -> sc(3); thirds = its remainder mirrored,
       popup_button_row_bounds) and council_thirds_fixup (t_cw_rowsym's arithmetic).
The red-brush flanks -- the scenario editor's red-brush frame sat between the palette frame and the info box with
       channels palette | red vs red | info 8 | 6 at 4K, 3 | 2 at 1600x900, 5 | 3 at g = 24 (3 | 3 at 1080 and 4 | 4 at
       1600x1200 by accident): editor_panel_seeds placed the red cells at scale_px(497) absolutely, where vanilla chains
       them off the palette (x0 = pal[24].R + 9).  Law: editor_red_chain_delta / editor_red_flank_channels -- x0 =
       pal[24].R + 3 * s(3), both flanks editor_info_channel(g) (= the info box's own channel to the M / I / TOOLBAR
       column, fix 24), every element otherwise untouched.

Proof layers:
  1. the laws, g 16..64 (and the mutants they replace);
  2. END TO END on the real image (mirror_pairs_emu.py on image_emu.py): the real MainWin_build at each screen, the real
     centre painter, the real CouncilWin row block through the E8 @0x427784, the BaseButton_init argument builds and
     the d5a0 / d618 / d528 draws -- on 64g x 48g screens (E2E_G) and on the user's shot screens; g = 16 is the
     pristine image's draw pixel for pixel; the bake with the W3A edits reverted in memory reproduces the user's editor
     shots (20261024-125445 / 20261025-000510 4K, 125805 1080, 125911 1600x1200, 130001 1600x900; the PNG cross-check
     runs when the shot is present) and the auditor's 4K council row.  (Unit parity: test_mirror_pairs_asm_parity.py.)

COST: one boot per image per worker (~3.5 s); each screen item re-runs MainWin_build + the painter + the council slices
on that boot (~1.5 s at 1024 .. ~5 s at 4K).  Items are per screen so the module splits across xdist by measured cost;
the serial total (~70 s) is the price of building every screen for real -- the bug classes here are invisible to a
slice (the console rect, the seeds, the column and the call order all come from MainWin_build / CouncilWin_exec).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402

#: the end-to-end screens (64g x 48g): every red-chain delta (-2 at 24 / 40, -1 at 18, +1 at 19 / 30 / 35, 0), every
#: council remainder on the real console (2 at 17 / 19 / 25 / 30, 1 at 18 / 40, 0 at 21 / 22 / 24 / 35), both stroke
#: widths and the native gate.  The full 16..40 sweep (same harness) is the bake's evidence; the law and the image's
#: own thunk bytes are swept over every g 16..64 here and in test_mirror_pairs_asm_parity.py.
E2E_G = (16, 17, 18, 19, 21, 22, 24, 25, 30, 35, 40)
LAW_G = range(16, 65)
NATIVE_CON = (262, 66, 763, 172)                 # the console proposal rect MainWin_build gives at 1024x768
CANVAS_DX_4K = 640                               # MainWin canvas -> screen x at 3840x2160


# ============================================================================== 1. laws
def _mutant_thirds(con, g):
    """The deployed engine (0a143acd): every native 3 of the block scaled EXCEPT the lea's disp8 (r0 = L + third - 3)."""
    r = SL.council_button_row(con, g)
    L, R = r["full"][0], r["full"][2]
    s3 = SL.dp(3, g)
    third = (R - L + s3) // 3
    r0 = L + third - 3
    step = r0 - L + s3
    return [(L + k * step, r["btn_top"], r0 + k * step, r["full"][3]) for k in range(3)]


@pytest.mark.parametrize("g", LAW_G)
def test_law_council_thirds_mirrored(g):
    s3 = SL.dp(3, g)
    for extra in range(6):
        con = (655, 165, 1907 + extra, 430)
        r = SL.council_button_row(con, g)
        L, R = r["full"][0], r["full"][2]
        t, eng = r["thirds"], r["thirds_engine"]
        rem = R - eng[2][2]
        assert 0 <= rem <= 2 and eng[0][0] == L, "the engine block drops its remainder at the right end"
        assert SL.council_thirds_fixup(R, eng, g) == t, "t_cw_rowsym's arithmetic is the law"
        if g <= 16:
            assert t == eng, "vanilla"
            continue
        assert t[0][0] == L and t[2][2] == R, "outer edges on the VOTE's"
        assert [t[1][0] - t[0][2], t[2][0] - t[1][2]] == [s3, s3]
        w = [a[2] - a[0] for a in t]
        assert w[0] == w[2] and abs(w[1] - w[0]) <= 1 and sum(w) == R - L - 2 * s3, "widths a palindrome"
        assert all(a[1] == r["btn_top"] and a[3] == r["full"][3] for a in t)
        m = _mutant_thirds(con, g)
        assert m[2][2] - R == 3 * (s3 - 3) - rem, "the missing disp8: 3 px per cell too wide"
    r16 = SL.council_button_row(NATIVE_CON, 16)
    assert r16["thirds"] == [(269, 145, 429, 165), (432, 145, 592, 165), (595, 145, 755, 165)]   # the 1024 trace


def test_law_council_4k_auditor_row():
    """The auditor's 4K numbers (screen = canvas + 640): the deployed row's third[2] = (2136, 2541) against R = 2530;
    the law's = (2129, 2530)."""
    con = (655, 165, 1907, 430)
    r = SL.council_button_row(con, 40)
    assert r["full"][2] + CANVAS_DX_4K == 2530
    m = _mutant_thirds(con, 40)
    assert (m[2][0] + CANVAS_DX_4K, m[2][2] + CANVAS_DX_4K) == (2136, 2541)
    assert (r["thirds"][2][0] + CANVAS_DX_4K, r["thirds"][2][2] + CANVAS_DX_4K) == (2129, 2530)


@pytest.mark.parametrize("g", LAW_G)
def test_law_editor_red_flanks(g):
    a, b = SL.editor_red_flank_channels(g)
    assert a == b == SL.editor_info_channel(g), "the mirrored pair, equal to the info box's own channels"
    d = SL.editor_red_chain_delta(g)
    assert -2 <= d <= 1 and (d == 0 if g <= 16 else True)
    s = SL.editor_panel_seeds(g)
    p3 = SL.scale_px(3, g)
    assert s["red"][0][0] == s["pal"][24][2] + (3 * p3 if g > 16 else 9), "chained off the palette like vanilla"
    assert all(r[2] - r[0] == s["red_cell"] for r in s["red"]) and s["red"][3][0] - s["red"][0][0] == \
        SL.scale_px(522, g) - SL.scale_px(497, g), "cells and pitch untouched"
    absolute = s["red_union"][0] - d - s["pal_union"][2] - (g > 16)       # the mutant: red x at scale_px(497)
    assert (absolute != a) == (d != 0)
    if g == 16:
        assert s["red"][0] == (497, 82, 521, 106) and (a, b) == (3, 3)


# ============================================================================== 2. end to end
#: the user's editor shots, deployed (before) geometry on the red-union mid row in MainWin canvas x: the four strokes
#: (palette R, red L, red R, info L) and the canvas -> screen offset.  Measured on the PNGs (pinned; the cross-check
#: below re-reads them when present) == the reverted bake's real-image draw.
SHOTS = {
    "3840x2160": (("20261024-125445", "20261025-000510"), (640, 1518),
                  ((1225, 1226), (1235, 1236), (1371, 1372), (1379, 1380)), (8, 6)),
    "1920x1080": (("20261024-125805",), (256, 727), ((675, 675), (679, 679), (755, 755), (759, 759)), (3, 3)),
    "1600x1200": (("20261024-125911",), (0, 799), ((766, 767), (772, 773), (857, 858), (863, 864)), (4, 4)),
    "1600x900": (("20261024-130001",), (224, 611), ((552, 552), (556, 556), (617, 617), (620, 620)), (3, 2)),
}
SHOT_DIR = ROOT / "screenshots"
STROKE_RGB = ("314e2c", "233b22")


@pytest.fixture(scope="module")
def sym():
    import mirror_pairs_emu as MPE
    return MPE.symtab()


@pytest.fixture(scope="module")
def images(tmp_path_factory, bak_path, sym, baked_exe):
    """{'new': the shared bake, 'before': the bake with the W3A edits reverted in memory (the E8 @0x427784 back on
    thunk_cw_seeds, g_cw_immtab without the 0x427707 row, thunk_ed_seeds' tail back on 0x45B0F5) -- the deployed
    0a143acd's behaviour, 'pristine': the .bak}."""
    import shutil
    import assemble_council as AC
    d = tmp_path_factory.mktemp("mirror_pairs")
    data = bytearray(Path(baked_exe).read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)

    def off(va):
        return pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    assert data[off(0x427784)] == 0xE8
    data[off(0x427785):off(0x427789)] = struct.pack("<i", sym["thunk_cw_seeds"] - 0x427789)
    rows = b"".join(struct.pack("<IIII", *r) for r in AC.IMMTAB if r[0] != 0x427707) + bytes(4)
    tab = off(sym["g_cw_immtab"])
    assert len(rows) == 40 * 16 + 4
    data[tab:tab + 41 * 16 + 4] = rows + bytes(16)
    push = b"\x68" + struct.pack("<I", sym["t_ed_redchain"]) + b"\xC3"
    s0 = off(sym["thunk_ed_seeds"])
    k = bytes(data[s0:s0 + 0x200]).index(push)
    data[s0 + k + 1:s0 + k + 5] = struct.pack("<I", 0x45B0F5)
    (d / "before.exe").write_bytes(bytes(data))
    shutil.copy2(bak_path, d / "pristine.exe")
    return {"new": str(baked_exe), "before": str(d / "before.exe"), "pristine": str(d / "pristine.exe")}


@pytest.fixture(scope="module")
def rig_new(images, sym):
    import mirror_pairs_emu as MPE
    return MPE.Rig(images["new"], sym)


@pytest.fixture(scope="module")
def rig_before(images, sym):
    import mirror_pairs_emu as MPE
    return MPE.Rig(images["before"], sym)


@pytest.fixture(scope="module")
def rig_pristine(images, sym):
    import mirror_pairs_emu as MPE
    return MPE.Rig(images["pristine"], sym)


def _measure(rig, w, h):
    """screen + editor + council -> the pair measurements (MainWin canvas x)."""
    import mirror_pairs_emu as MPE
    g = rig.screen(w, h)
    ed = rig.editor()
    p, y, bg = ed["p"], ed["y"], ed["bg"]
    st = ed["strokes"]
    palr, redl, redr = st[0], st[1], st[2]
    x = ed["col_l"] - 1
    while p[y, x] == bg:
        x -= 1
    c = rig.council()
    bl, br = MPE.box_strokes(c["box"], c["vote"])
    return {"g": g, "ed": ed, "c": c, "strokes": (palr, redl, redr, (st[3][0], st[3][0] + redr[1] - redr[0])),
            "pal_red": redl[0] - palr[1] - 1, "red_info": st[3][0] - redr[1] - 1, "info_col": ed["col_l"] - x - 1,
            "K": {palr[1] - palr[0] + 1, redl[1] - redl[0] + 1, redr[1] - redr[0] + 1}, "info_r_end": x,
            "box_l": bl, "box_r": br}


def _check_new(m):
    g, ed, c = m["g"], m["ed"], m["c"]
    K = SL.stroke_width(g) if g > 16 else 1
    # the red-brush flanks: equal, the law, and the info box's own pair (fix 24) and column (t_hud_mi_square) intact
    assert m["pal_red"] == m["red_info"] == SL.editor_info_channel(g), (g, m["pal_red"], m["red_info"])
    assert m["info_col"] == m["red_info"], "fix 24's pair"
    assert m["K"] == {K}
    assert ed["col_l"] == SL.hud_mi_column(g)[0] and ed["info"][2] == SL.editor_info_right(ed["col_l"], g)
    s = SL.editor_panel_seeds(g)
    if g > 16:
        assert ed["red_seeds"] == s["red"] and ed["red_union"] == s["red_union"] and ed["pal_union"] == s["pal_union"]
        assert ed["info"][0] == s["info_left"]
        assert {k: (x, y, x + w, y + h) for k, (x, y, w, h) in ed["red_windows"].items()} == dict(enumerate(s["red"])), \
            "the red FlatButtons are built on the chained seeds"
    # the council row: the law, built as BaseButton windows, flush on the VOTE, inside the d5a0 box
    row = SL.council_button_row(c["con"], g)
    assert c["vote"] == row["full"] and c["thirds"] == row["thirds"], (g, c["thirds"], row["thirds"])
    assert c["windows"] == c["thirds"], "x = L, w = R - L at BaseButton_init"
    t, v = c["thirds"], c["vote"]
    assert t[0][0] == v[0] and t[2][0] > t[1][2] > t[1][0] > t[0][2]
    assert t[2][2] <= m["box_r"][0] - (SL.dp(3, g) - K if g > 16 else 2), "inside the ring, the VOTE's own channel"
    if g > 16:
        assert t[2][2] == v[2] and t[0][2] - t[0][0] == t[2][2] - t[2][0], "symmetric"
    assert v[0] - 1 - m["box_l"][1] == m["box_r"][0] - v[2], "W2A's VOTE pair still holds"


@pytest.mark.parametrize("g", E2E_G)
def test_e2e_every_g(rig_new, g):
    _check_new(_measure(rig_new, 64 * g, 48 * g))


@pytest.mark.parametrize("res", sorted(SHOTS) + ["2560x1440", "1280x1024"])
def test_e2e_user_screens(request, rig_new, res):
    """The user's screens: the bake draws the law; the reverted bake draws the shots."""
    w, h = (int(v) for v in res.split("x"))
    new = _measure(rig_new, w, h)
    _check_new(new)
    if res not in SHOTS:
        return
    names, (dx, dy), strokes, (left, right) = SHOTS[res]
    old = _measure(request.getfixturevalue("rig_before"), w, h)
    assert old["strokes"] == strokes and (old["pal_red"], old["red_info"]) == (left, right), (res, old["strokes"])
    assert old["info_col"] == right, "fix 24's info channels (deployed)"
    assert new["strokes"][0] == strokes[0] and new["info_r_end"] == old["info_r_end"], \
        "the palette frame and the info box's right edge do not move"
    assert new["red_info"] == right and new["pal_red"] == right, "the red | info side was already the law's"
    for name in names:
        png = SHOT_DIR / f"terranx_pracx_{res}_{name}.png"
        if not png.exists():
            continue
        from PIL import Image
        img = Image.open(png).convert("RGB")
        y = old["ed"]["y"]
        got = []
        for xx in range(strokes[0][0] - 4, strokes[3][1] + 1):
            col = "%02x%02x%02x" % img.getpixel((xx + dx, y + dy))
            if col in STROKE_RGB:
                if got and got[-1][1] == xx - 1:
                    got[-1][1] = xx
                else:
                    got.append([xx, xx])
        assert [tuple(r) for r in got] == list(strokes), (name, got)


def test_e2e_before_council_overruns(rig_before):
    """The auditor's 4K finding on the real image: the deployed row ends at canvas 1901 (screen 2541) against the
    VOTE's 1890 (2530), 6 px into the d5a0 stroke (1895..1896 + the two px past it)."""
    old = _measure(rig_before, 3840, 2160)
    t, v = old["c"]["thirds"], old["c"]["vote"]
    assert (t[2][0] + CANVAS_DX_4K, t[2][2] + CANVAS_DX_4K) == (2136, 2541) and v[2] + CANVAS_DX_4K == 2530
    assert t[2][2] - old["box_r"][0] == 6 and old["c"]["windows"] == t
    assert t == _mutant_thirds(old["c"]["con"], 40)


def test_e2e_g16_is_pristine(rig_new, rig_pristine):
    new = _measure(rig_new, 1024, 768)
    old = _measure(rig_pristine, 1024, 768)
    assert np.array_equal(new["ed"]["p"], old["ed"]["p"]), "the editor centre panel, pixel for pixel"
    assert new["ed"]["red_windows"] == old["ed"]["red_windows"] and new["ed"]["red_seeds"] == old["ed"]["red_seeds"]
    for k in ("vote", "thirds", "windows", "con"):
        assert new["c"][k] == old["c"][k], k
    assert np.array_equal(new["c"]["p"], old["c"]["p"])
    assert (old["pal_red"], old["red_info"], old["info_col"]) == (3, 3, 3)
    assert old["c"]["thirds"] == [(269, 145, 429, 165), (432, 145, 592, 165), (595, 145, 755, 165)]
