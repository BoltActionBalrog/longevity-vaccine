"""Type-1 popups end to end on the REAL image (W1A, 2026-10-24): fix 25a (the dialog -> button-row span), fix 25b
(the title band on vanilla's half-open rows), F35 (the option-row bars on vanilla's half-open footprint).

Laws (scaling_laws.py, the source of truth): popup_dialog_btn_span / popup_box_h_btn_pad (t_btn_vgap),
popup_title_band_rows (thunk_title_height v2) + title_band_draw_rect (t_band_bdraw), option_row_frame_site_rect
(t_rowbox_trim).  Byte-level parity: tests/test_type1_gaps_asm_parity.py.

The renders boot the module's bake of patches.yaml (and the pristine .bak, and an in-memory variant of the bake with
the three fixes disarmed = the da1474af behaviour) under Unicorn with the shared harness (image_emu.py; builders
ornate_popup_emu.py / popup_listbox_emu.py): every engine function and cave thunk runs, in the engine's own order --
BasePop_exec_3's redraw at 0x602B49 (DRAW #1, the title band and the ring) BEFORE the list attach at 0x602BFE, the
list rows drawn into the list window at the attach, the button row placed from box_h, and a later full redraw
(vtbl+0x30).  Every value is read off the pixels:

  GF  GOVOPTIONS, a type-1 checkbox list in a FLAT popup, in game (console strip shown: the rail title path)
  GM  the same popup from the main menu (console hidden: thunk_title_hmargin's title path; Customize Game Rules)
  GO  the same list in an ORNATE popup (PopupDialogState 6: thunk_pf_title_stash's ornate arm)
  GT  Go To (Console_go_to's #GOTO), a type-2 list: shares the button-row site and the row-frame site

Asserted per render, at g in 16..40 (screens 64g x 48g; g = 16 at 1024 x 768, 40 at 3840 x 2160):
  * g = 16: the composite (popup canvas + every child window) == the pristine .bak's, pixel for pixel;
  * 25a: ring -> button row = fl(12g/16) clear rows (vanilla 12; was 2 fl(6g/16), up to 1.75 short); the list ->
    row span = fl(12g/16) + fl(3g/16) (the row's own +3, thunk_btn_vcenter) in GT too;
  * 25b: the band's outer box ends (exclusive) at fl(28g/16) flat / fl(37g/16) ornate, the inner box fl(3g/16)
    inside it; the outer -> inner channel equal top and bottom; band -> ring clear rows == popup_title_ring_clear;
  * F35: every bar is exactly its engine rect's rows (the rects recorded at the 0x405BF6 frame site, half-open); Go To
    (type 2): the gap between bars fl(3g/16) (vanilla 3); the type-1 list (W8T F46, the user's equal-gap decision):
    every bar on type1_row_layout (s(1) + r P, type1_row_h tall, P = half_down(22 g, 16): every gap equal), the list rows x P,
    the ring hugging the list window by fl(3g/16) on top and bottom -- exact law equalities, no tolerance: what the
    law leaves off vanilla x g/16 (the last bar -> list bottom, the ring clear rows) is the W8T report's, not a
    test's;
  * the disarmed variant FAILS each of the three checks at g = 18 (where all three act; the mutant the checks kill).
Coverage: flat GF {18, 21, 25} + GM {40} (in game and main menu; 21 = 25a's worst g, 1.75 short), ornate GO {17, 22,
30, 40}, Go To {18}; every g in 16..40 is the law / parity layers' (tests/test_type1_gaps_asm_parity.py) and
test_scaling_type1_box_fill.py's chain sweep.
COST (~95 s serial; why: the three fixes are pixel facts of the engine's own draw order -- the band at DRAW #1 before
the attach, the rows at the attach, the row from box_h -- which only a real-image render shows; the stubbed chain
harness cannot see the band map's inclusive footprint): one boot + build per (image, popup, screen) = 17 renders
(3-14 s each, 4K ornate the longest), each a test item of its own so xdist spreads them, shared through a module cache
by every item that reads the same render (the g = 16 pristine / bake pairs).  The bake is conftest's `baked_exe`.
"""
from __future__ import annotations

import gc
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
from unicorn.x86_const import UC_X86_REG_ESP  # noqa: E402

import apply_patches as ap  # noqa: E402
import assemble_type1_gaps as A  # noqa: E402
import scaling_laws as SL  # noqa: E402

LINE, INNER = 31, 34                     # the title / ring stroke indices (popup canvas)
BAR = (238, 174, 224, 225)               # list-row bar indices (child canvas; 224/225 = the selected row)


# ---------------------------------------------------------------------------------------------------- the images
@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return dict(ap.build_symbol_table(symbols, caves))


class Image:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        pe = pefile.PE(data=bytes(data), fast_load=True)
        self.ib = pe.OPTIONAL_HEADER.ImageBase
        self.secs = [(self.ib + s.VirtualAddress, s.PointerToRawData, s.SizeOfRawData) for s in pe.sections]

    def off(self, va: int) -> int:
        for v, raw, size in self.secs:
            if v <= va < v + size:
                return raw + va - v
        raise KeyError(hex(va))

    def rd(self, va: int, n: int) -> bytes:
        o = self.off(va)
        return bytes(self.data[o:o + n])

    def wr(self, va: int, b: bytes):
        o = self.off(va)
        self.data[o:o + len(b)] = b


def disarm_edits(im: Image, st: dict) -> list:
    """The three fixes off (= the da1474af geometry): assemble_type1_gaps.disarm_edits."""
    return A.disarm_edits(im.rd, st)


@pytest.fixture(scope="module")
def images(tmp_path_factory, bak_path, symtab, baked_exe):
    """{bake, pristine, off}: conftest's shared bake of patches.yaml, the .bak, the bake with the fixes off."""
    d = tmp_path_factory.mktemp("type1_gaps")
    dst = Path(baked_exe)
    baked = Image(dst.read_bytes())
    off = Image(bytes(baked.data))
    for va, b in disarm_edits(baked, symtab):
        off.wr(va, b)
    p = d / "off.exe"
    p.write_bytes(bytes(off.data))
    return {"bake": str(dst), "pristine": str(bak_path), "off": str(p)}


@pytest.fixture(scope="module")
def emu_mod():
    from conftest import _missing                       # skip, or fail under LONGEVITY_REQUIRE_E2E
    try:
        import ornate_popup_emu as O
        import popup_listbox_emu as L
    except Exception as x:                              # no game dir / host GDI: the end-to-end layer cannot run
        _missing(Path("ornate_popup_emu"), f"the real-image popup renderer ({x})")
    if not (Path(O.GAME) / "interface.pcx").is_file():
        _missing(Path(O.GAME) / "interface.pcx", "the game's frame art")
    return O, L


# ---------------------------------------------------------------------------------------------------- renders
def _runs(v) -> list:
    out, s = [], 0
    for i in range(1, len(v) + 1):
        if i == len(v) or v[i] != v[s]:
            out.append((s, i, int(v[s])))
            s = i
    return out


def _screen(g: int):
    return (1024, 768) if g == 16 else (3840, 2160) if g == 40 else (64 * g, 48 * g)


_RENDERS: dict = {}


def _frames_hook(sink: list):
    def cb(e):
        esp = e.reg(UC_X86_REG_ESP)
        sink.append(struct.unpack("<4i", bytes(e.uc.mem_read(e.r32(esp), 16))))
    return cb


def render(mods, images, name: str, fam: str, g: int) -> dict:
    """One boot + build per (image, family, g), cached for the module (per worker)."""
    key = (name, fam, g)
    if key in _RENDERS:
        return _RENDERS[key]
    O, L = mods
    exe = images[name]
    rows: list = []                               # the row rects at the frame site, as the native fn hands them
    if fam == "GT":
        def patch(e):
            e.observe(A.SITE_ROWBOX, _frames_hook(rows))
        r = L.Run(exe, g, label="GOTO", patch=patch)
        lw = r.lists[-1]
        import image_emu as E
        out = dict(g=r.g, list=(lw["y"], lw["h"]), child=E.canvas_of(r.e, lw["win"]), rows=rows,
                   btn=min(b["y"] for b in r.btns if b["phase"] == "show1"))
        r.e.uc = None
        r.e = None
    else:
        hooks = ((A.SITE_ROWBOX, _frames_hook(rows)),)
        if fam == "GM":                           # O.render's CASES have no main-menu GOVOPTIONS: build it directly
            hh = O.H(exe, *_screen(g), kind="XPOP2", label="GOVOPTIONS", ornate_mode=False, flags=0x41,
                     mainwin=False, hooks=hooks)
            kids = [{k: v for k, v in c.items() if k != "canvas"} for c in hh.children]
            out = dict(g=hh.g, d1=hh.composite("draw1"), later=hh.composite("later"), children=kids)
            hh.e.uc = None
            hh.e = None
            del hh
        else:
            out = O.render(exe, {"GF": "GF", "GO": "GO"}[fam], *_screen(g), hooks=hooks)
        out["rows"] = rows
    gc.collect()
    _RENDERS[key] = out
    return out


def profile(r: dict, fam: str, which: str = "d1") -> dict:
    """The vertical profile of a rendered type-1 popup at the column 20g/16 px inside the list's right edge (right
    of every row's text, left of the ring)."""
    g = max(r["g"], 16)
    kids = r["children"]
    lst = max(kids, key=lambda k: k["h"])
    c = r[which]
    x = lst["x"] + lst["w"] - max(4, (20 * g) >> 4)
    col = c[:, x]
    ly0, ly1 = lst["y"], lst["y"] + lst["h"]
    st = [(a, b, v) for a, b, v in _runs(col[:ly0]) if v in (LINE, INNER)]
    i1 = next(i for i, s in enumerate(st) if s[2] == INNER)
    i2 = next(i for i in range(i1 + 1, len(st)) if st[i][2] == INNER)
    outer_t, inner_t, inner_b, outer_b, ring_t = st[i1 - 1], st[i1], st[i2], st[i2 + 1], st[i2 + 2]
    assert outer_t[2] == outer_b[2] == ring_t[2] == LINE, st
    ring_b = next((a, b) for a, b, v in _runs(col[ly1:]) if v == LINE)
    ring_b = (ring_b[0] + ly1, ring_b[1] + ly1)
    bars = [(ly0 + a, ly0 + b) for a, b, v in _runs(np.isin(col[ly0:ly1], [256 + v for v in BAR]).astype(int))
            if v == 1]
    btn = min(k["y"] for k in kids if k["h"] <= 80)
    return dict(outer=(outer_t[0], outer_b[1]), inner=(inner_t[0], inner_b[1]), k=(outer_t[1] - outer_t[0]),
                ch_top=inner_t[0] - outer_t[1], ch_bot=outer_b[0] - inner_b[1], ring=(ring_t[0], ring_b[1]),
                title_clear=ring_t[0] - outer_b[1], btn_clear=btn - ring_b[1], list=(ly0, ly1), bars=bars, btn=btn,
                list_btn=btn - ly1)


def gt_profile(r: dict) -> dict:
    c = r["child"]
    col = c[:, c.shape[1] - 5]
    bars = [(a, b) for a, b, v in _runs(np.isin(col, BAR).astype(int)) if v == 1]
    y, h = r["list"]
    return dict(bars=bars, list_btn=r["btn"] - (y + h))


# ---------------------------------------------------------------------------------------------------- the checks
def check_btn(p: dict, g: int, fam: str):
    """25a: the dialog -> row span is ONE vanilla 12, scaled once (+ the row's own +3, scaled)."""
    span, plus3 = SL.popup_dialog_btn_span(SL.POPUP_PAD_Y_SRC, g), SL.popup_pad(3, g)
    assert span == (12 * g) >> 4
    if fam != "GT":
        assert p["btn_clear"] == span, (fam, g, "ring -> row", p["btn_clear"], span)
    assert p["list_btn"] == span + plus3, (fam, g, "list -> row", p["list_btn"], span + plus3)


def check_band(p: dict, g: int, fam: str):
    """25b: the band's boxes end on their vanilla half-open rows; channels equal top / bottom; band -> ring."""
    ps3 = SL.popup_pad(3, g)
    if fam == "GO":
        t, b = SL.ornate_title_rect(0, 0, 0, g)[1], SL.ornate_title_rect(0, 0, 0, g)[3]
    else:
        t, b = SL.popup_title_band_rows(0, g)
    assert p["outer"] == (t, b), (fam, g, "outer band rows", p["outer"], (t, b))
    assert p["inner"] == (t + ps3, b - ps3), (fam, g, "inner band rows", p["inner"], (t + ps3, b - ps3))
    assert p["k"] == (SL.stroke_width(g) if g > 16 else 1)
    assert p["ch_top"] == p["ch_bot"] == ps3 - p["k"], (fam, g, p["ch_top"], p["ch_bot"])
    want = SL.popup_title_ring_clear(g, fam == "GO")
    assert p["title_clear"] == want, (fam, g, "band -> ring", p["title_clear"], want)


def check_bars(p: dict, rows: list, g: int, fam: str):
    """F35: each bar is its half-open rect's rows; bars fl(3g/16) apart; type-1 split smaller share first."""
    bars = p["bars"]
    assert len(bars) >= 3
    hs = {r[3] - r[1] for r in rows}                  # every row rect's half-open height at the frame site
    assert len(hs) == 1 and {b1 - b0 for b0, b1 in bars[1:-1]} == hs, (fam, g, hs, bars[:4])
    if fam == "GT":
        gap = SL.popup_pad(3, g)
        for (a0, a1), (b0, b1) in zip(bars, bars[1:]):
            assert b0 - a1 == gap, (fam, g, "gap between bars", b0 - a1, gap, bars[:4])
        return
    P = SL.TYPE1_POPUP_ROW_PRESET
    lt, lb = p["list"]
    want = SL.type1_row_layout(len(bars), P, g)
    assert [(a - lt, b - lt) for a, b in bars] == want, (fam, g, "bars", bars[:3], want[:3])
    assert len({b0 - a1 for (_a0, a1), (b0, _b1) in zip(bars, bars[1:])}) == 1, (fam, g, "equal gaps")
    assert lb - lt == SL.type1_row_cell(len(bars), P, g), (fam, g, "list height", lb - lt)
    ps3 = SL.popup_pad(3, g)
    assert lt - p["ring"][0] == p["ring"][1] - lb == ps3, (fam, g, "ring -> list", p["ring"], p["list"])


# ---------------------------------------------------------------------------------------------------- tests
G16_FAMS = ("GF", "GO", "GT")               # g = 16 vs pristine: the flat, ornate and type-2 paths
E2E = [("GF", 18), ("GF", 21), ("GF", 25), ("GM", 40),          # flat: in game, and the main-menu title path at 4K
       ("GO", 17), ("GO", 22), ("GO", 30), ("GO", 40)]          # ornate
GS_GT = (18,)                               # Go To: 25a acts at 18 (not at 22 / 25 / 40), F35 at every g


@pytest.mark.parametrize("fam", G16_FAMS)
def test_scaling_type1_gaps_g16_is_pristine(emu_mod, images, fam):
    a, v = render(emu_mod, images, "bake", fam, 16), render(emu_mod, images, "pristine", fam, 16)
    if fam == "GT":
        assert np.array_equal(a["child"], v["child"]) and a["list"] == v["list"] and a["btn"] == v["btn"]
        assert a["rows"] == v["rows"]
        p = gt_profile(v)
        assert p["list_btn"] == 15 and {b0 - a1 for (_a0, a1), (b0, _b1) in zip(p["bars"], p["bars"][1:])} == {3}
        return
    for which in ("d1", "later"):
        assert np.array_equal(a[which], v[which]), (fam, which)
    assert a["children"] == v["children"] and a["rows"] == v["rows"]
    p = profile(v, fam)                                # vanilla, measured: the constants every law scales
    assert (p["btn_clear"], p["list_btn"], p["title_clear"], p["ch_top"], p["ch_bot"]) == (12, 15, 7, 2, 2)
    assert p["outer"] == ((13, 37) if fam == "GO" else (4, 28)) and p["inner"][1] == p["outer"][1] - 3
    assert [b1 - b0 for b0, b1 in p["bars"][:2]] == [19, 19] and p["bars"][1][0] - p["bars"][0][1] == 3
    assert (p["bars"][0][0] - p["ring"][0] - 1, p["ring"][1] - p["bars"][-1][1] - 1) == (3, 4)


@pytest.mark.parametrize("fam, g", E2E)
def test_scaling_type1_gaps_end_to_end(emu_mod, images, fam, g):
    r = render(emu_mod, images, "bake", fam, g)
    assert r["g"] == g
    for which in ("d1", "later"):                     # DRAW #1 (before the attach) and a later full redraw
        p = profile(r, fam, which)
        check_btn(p, g, fam)
        check_band(p, g, fam)
        check_bars(p, r["rows"], g, fam)


@pytest.mark.parametrize("g", GS_GT)
def test_scaling_type1_gaps_goto_list(emu_mod, images, g):
    r = render(emu_mod, images, "bake", "GT", g)
    assert r["g"] == g
    p = gt_profile(r)
    check_btn(p, g, "GT")
    check_bars(p, r["rows"], g, "GT")


@pytest.mark.parametrize("fam", ("GF", "GO"))
def test_scaling_type1_gaps_disarmed_fails_each_check(emu_mod, images, fam):
    """The fixes off (the da1474af behaviour) at g = 18, where all three act (25a: fl(13.5) = 13 vs 2 fl(6.75) = 12):
    each check this module makes fails on it."""
    g = 18
    r = render(emu_mod, images, "off", fam, g)
    p = profile(r, fam)
    with pytest.raises(AssertionError):
        check_btn(p, g, fam)
    with pytest.raises(AssertionError):
        check_band(p, g, fam)
    with pytest.raises(AssertionError):
        check_bars(p, r["rows"], g, fam)
