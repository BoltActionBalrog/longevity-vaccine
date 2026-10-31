"""W8T v3 on the REAL image (2026-10-27): F46, the type-1 popup checkbox rows (Customize Game Rules, Governor Settings;
measure27 FAIL1) on ONE uniform pitch, labels lifted to fit their bars, checkboxes on the bars' top rows -- the user's
decisions (equal gaps; option B of the W8T audit).

Laws (scaling_laws.py, the source of truth): type1_row_h / type1_row_pitch / type1_row_cell / type1_row_top /
type1_row_at / type1_label_lift / type1_checkbox_y_arg (t1c_calc, t1c_barh, t1c_rowtop, t1c_hit, t1c_label + t1c_pdesc,
t1c_ckpos).  Byte-level parity: tests/test_type1_rowcum_asm_parity.py.  The bars / ring / title band of GOVOPTIONS
(flat in game, ornate) at g 17..40 are also checked on the real image by tests/test_scaling_type1_popup_gaps.py.

Each render boots the image under Unicorn (image_emu.py; builder ornate_popup_emu.H) in the engine's own order -- the
calc (t1c_calc) at the dims dispatch, the rows drawn into the list window at the attach (CheckList_draw_item ->
t1c_rowtop, the popup painter FUN_00405b20's checkbox -> t1c_ckpos -> t_ck_list, the label -> t1c_label, whose font
descent comes from GetGlyphOutlineA through GetProcAddress, served by image_emu from host GDI) -- with REAL text
(textout_emu: host-GDI TextOutA into the emulated DIB, the W8T audit's tool, calibrated on the user's shots), then
CLICKS the list: the engine's click handler 0x60F700 (-> t1c_hit) is called per y, and the checkbox bit it toggles
([+0xEC]) is the row it hit.  Images: conftest's `baked_exe`, and the bake with W8T disarmed
(assemble_type1_rowcum.disarm_edits = the 1bfd909 geometry).

Asserted per render (pixels, not fields):
  * bars on type1_row_layout, every gap equal, the list rows x P, the click map type1_row_at (every y, or every cell
    boundary -1 / 0 / +1 and bar middle at 4K);
  * LABEL FIT: every label's main ink ends on or above its bar's last row, a label with a 'p' exactly on it (vanilla:
    the descender ends on row 19 of 19); the shadow pass (+1, +1) is not the label;
  * CHECKBOX on the bar's top row (vanilla top 0), never past the bar's bottom;
  * BAR-FACE STRIPES symmetric: each bar's top and bottom edge runs (the restriped face at the column right of the
    text) are the same length;
  * g = 16: vanilla's numbers (bars [22 r + 1, 22 r + 20), y // 22, label ink ending on row 19, checkbox top 0);
  * the disarmed bake FAILS the bar, list, click and checkbox checks at 1280 x 1024.
Renders: 1024x768 (16), 1280x1024 RULES (20), 1920x1080 (22, the 2-px stripe tier), 3840x2160 (40), disarmed 1280.
COST (~60 s serial over 5 items, 9-15 s each; why: the label ink and the click are pixel / engine facts of a fully built popup,
which only a real-image boot has): one boot + build per item; xdist spreads the items.
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
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn.x86_const import UC_X86_REG_ECX  # noqa: E402

import apply_patches as ap  # noqa: E402
import assemble_type1_rowcum as A  # noqa: E402
import scaling_laws as SL  # noqa: E402

P = SL.TYPE1_POPUP_ROW_PRESET
BAR = (238, 174, 224, 225)               # list-row bar indices (child canvas; 224/225 = the selected row)
BG = (65, 198)                           # the list window's captured background between the bars
CLICK = 0x0060F700                       # the CheckList click handler (thiscall, this = CheckList + 0x1C, (x, y), RET 8)
DRAW_ITEM = 0x0060F030


@pytest.fixture(scope="module")
def images(tmp_path_factory, baked_exe):
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    st = dict(ap.build_symbol_table(symbols, caves))
    data = bytearray(Path(baked_exe).read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    secs = [(ib + s.VirtualAddress, s.PointerToRawData, s.SizeOfRawData) for s in pe.sections]

    def off(va):
        return next(raw + va - v for v, raw, size in secs if v <= va < v + size)

    def rd(va, n):
        return bytes(data[off(va):off(va) + n])
    for va, b in A.disarm_edits(rd, st):
        data[off(va):off(va) + len(b)] = b
    p = tmp_path_factory.mktemp("type1_rowcum") / "off.exe"
    p.write_bytes(bytes(data))
    return {"bake": str(baked_exe), "off": str(p)}


@pytest.fixture(scope="module")
def mods():
    from conftest import _missing
    try:
        import ornate_popup_emu as O
        import textout_emu as T
    except Exception as x:                              # no game dir / host GDI: the end-to-end layer cannot run
        _missing(Path("ornate_popup_emu"), f"the real-image popup renderer ({x})")
    if not (Path(O.GAME) / "interface.pcx").is_file():
        _missing(Path(O.GAME) / "interface.pcx", "the game's frame art")
    return O, T


def _runs(v) -> list:
    out, s = [], 0
    for i in range(1, len(v) + 1):
        if i == len(v) or v[i] != v[s]:
            out.append((s, i, int(v[s])))
            s = i
    return out


def build(mods, exe: str, label: str, screen, sample: bool = False) -> dict:
    """Build the popup with real text; read the list window, its bars, each bar's label ink / checkbox / edge stripe
    runs, and the click map."""
    O, T = mods
    this = []
    with T.text_rendering() as log:
        hh = O.H(exe, *screen, kind="XPOP2", label=label, ornate_mode=False, flags=0x41, mainwin=(label != "RULES"),
                 later=False, hooks=[(DRAW_ITEM, lambda e: this.append(e.reg(UC_X86_REG_ECX)))])
    e = hh.e
    g = max(hh.g, 16)
    lst = max(hh.children, key=lambda k: k["h"])
    cl = this[0]
    d = cl + e.r32(e.r32(cl) + 8)
    c = lst["canvas"].astype(int)
    lh, lw = lst["h"], lst["w"]
    x_face = lw - max(4, (20 * g) >> 4)
    bars = [(a, b) for a, b, v in _runs(np.isin(c[:, x_face], BAR).astype(int)) if v == 1]
    texts = [t for t in log if t[5] == -lh or t[5] == lh]
    main = [t for t in texts if not any(u[1] == t[1] - 1 and u[2] == t[2] - 1 and u[0] == t[0] for u in texts)]
    rows = []
    for i, (a, b) in enumerate(bars):
        lab = next((t for t in main if a - lh // 2 < t[2] < b + lh // 2 and a <= t[3] < b), None)
        x0 = int(np.nonzero(np.isin(c[(a + b) // 2], BAR))[0][0])
        lo = bars[i - 1][1] if i else 0
        hi = bars[i + 1][0] if i + 1 < len(bars) else c.shape[0]
        nb = (~np.isin(c[lo:hi, :x0], BG)).sum(axis=1) >= 3
        run = next(((s + lo, t + lo) for s, t, v in _runs(list(nb.astype(int))) if v and s + lo <= (a + b) // 2 < t + lo),
                   None)
        er = _runs(list(c[a:b, x_face]))
        rows.append(dict(bar=(a, b), text=lab[0] if lab else None, ink=(lab[3], lab[4]) if lab else None,
                         box=run, edges=(er[0][1] - er[0][0], er[-1][1] - er[-1][0])))
    out = dict(g=g, list=(lst["x"], lst["y"], lw, lh), rows_field=e.s32(d + 0x58), rows=rows)
    ys = range(lh)
    if sample:
        ys = sorted({y for r in range(out["rows_field"] + 1) for y in (SL.type1_row_cell(r, P, g) + k for k in (-1, 0, 1))
                     if 0 <= y < lh} | {(a + b) // 2 for a, b in bars})
    hits = {}
    for y in ys:
        before = e.r32(d + 0xEC)
        e.call(CLICK, ecx=cl + 0x1C, args=(lw // 2, y))
        x = before ^ e.r32(d + 0xEC)
        hits[y] = x.bit_length() - 1 if x else None
    out["hits"] = hits
    hh.e.uc = None
    hh.e = None
    del hh
    gc.collect()
    return out


def check_layout(r: dict, g: int, n: int):
    assert r["g"] == g and r["rows_field"] == n
    lh = r["list"][3]
    bars = [x["bar"] for x in r["rows"]]
    assert lh == SL.type1_row_cell(n, P, g), ("list height", lh)
    assert bars == SL.type1_row_layout(n, P, g), ("bars", bars[:3])
    assert len({b0 - a1 for (_a0, a1), (b0, _b1) in zip(bars, bars[1:])}) == 1, "equal gaps"
    bad = {y: h for y, h in r["hits"].items() if h != SL.type1_row_at(y, P, g)}
    assert not bad and len(r["hits"]) > 3 * n, ("click", sorted(bad.items())[:5])


def check_labels(r: dict):
    """Every label's main ink ends on or above its bar's last row; a label with a 'p' (the font's deepest descender,
    with g j q y ( ) ) ends exactly on it."""
    for x in r["rows"]:
        a, b = x["bar"]
        assert x["ink"] is not None, ("no label ink", x)
        assert x["ink"][1] <= b, ("label ink past the bar", x["text"], x["ink"], x["bar"])
        if b"p" in x["text"]:
            assert x["ink"][1] == b, ("label ink not on the bar's last row", x["text"], x["ink"], x["bar"])


def check_checkboxes(r: dict):
    for x in r["rows"]:
        a, b = x["bar"]
        assert x["box"] is not None and x["box"][0] == a and x["box"][1] <= b, ("checkbox", x["box"], x["bar"])


def check_stripes(r: dict):
    for x in r["rows"]:
        assert x["edges"][0] == x["edges"][1], ("bar-face edge stripe runs", x["edges"], x["bar"])


def test_g16_is_vanilla(mods, images):
    r = build(mods, images["bake"], "GOVOPTIONS", (1024, 768))
    assert r["list"][3] == 418 and r["rows_field"] == 19
    assert [x["bar"] for x in r["rows"]] == [(22 * k + 1, 22 * k + 20) for k in range(19)]
    assert r["hits"] == {y: y // 22 for y in range(418)}
    check_labels(r)
    check_checkboxes(r)


def test_rules_1280x1024(mods, images):
    """The user's 1280x1024 Customize Game Rules (measure27 FAIL1)."""
    r = build(mods, images["bake"], "RULES", (1280, 1024))
    check_layout(r, 20, 18)
    assert r["list"][3] == 486 and {x["bar"][1] - x["bar"][0] for x in r["rows"]} == {24}
    check_labels(r)
    check_checkboxes(r)
    check_stripes(r)


def test_governor_1080(mods, images):
    r = build(mods, images["bake"], "GOVOPTIONS", (1920, 1080), sample=True)
    check_layout(r, 22, 19)
    check_labels(r)
    check_checkboxes(r)
    check_stripes(r)


def test_governor_4k(mods, images):
    r = build(mods, images["bake"], "GOVOPTIONS", (3840, 2160), sample=True)
    check_layout(r, 40, 19)
    tops = [x["bar"][0] for x in r["rows"]]
    assert r["list"][3] == 1045 and {b - a for a, b in zip(tops, tops[1:])} == {55}
    assert {x["bar"][1] - x["bar"][0] for x in r["rows"]} == {48}            # the stripe-symmetric pick (47.5 tie)
    check_labels(r)
    check_checkboxes(r)
    check_stripes(r)


def test_disarmed_fails_each_check(mods, images):
    r = build(mods, images["off"], "RULES", (1280, 1024))
    with pytest.raises(AssertionError):
        check_layout(r, 20, 18)
    with pytest.raises(AssertionError):
        check_checkboxes(r)
    assert any(h != SL.type1_row_at(y, P, 20) for y, h in r["hits"].items())
