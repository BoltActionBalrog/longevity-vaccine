"""W9B on the REAL image (2026-10-27): the type-1 checkbox-list bars (Customize Game Rules, Governor Settings) striped
from each bar's OWN top -- the user's decision "make every row identical" (W8T v3's uniform pitch P put the bars on
different phases of the popup's stripe grid: 2 looks at 1280x1024 / 1600x900 / 1920x1080 / 1600x1200, 4 at 2560x1440 /
4K, the dark edge rows merging with the gaps).

Laws (scaling_laws.py, the source of truth): type1_bar_gate / type1_bar_colour / type1_bar_restripe (t1c_bar at the
bar draw 0x405BF6, assemble_type1_rowcum.py).  Byte-level parity: tests/test_type1_bar_asm_parity.py.

Each render boots the bake (conftest's `baked_exe`) under Unicorn (image_emu.py; builder ornate_popup_emu.H) and builds
the popup in the engine's own order with REAL text (textout_emu), then puts the list in a state mix -- rows 0, 3, 4,
9, 16 checked (state 2, the 0x78D9B0 set), the cursor on row 2 (state 1: the hover ring), every other row plain
(state 0) -- and redraws every row through the engine's CheckList_draw_item TWICE in the same boot: first with the bar
site 0x405BF6 pointed back at t_rowbox_solid (the 2087b42 / W8T v3 draw: OFF), then at t1c_bar (ON).  The redraw is
idempotent (each row's back is redrawn whole, its label and checkbox after it), so OFF and ON differ by W9B alone.

Asserted per render (pixels, not fields):
  * ON == type1_bar_restripe(OFF) over every bar, on the WHOLE list canvas: nothing but bar-face pair pixels changed --
    the labels, the checkboxes, the hover ring, the keyed corners and the gaps are W8T v3's, pixel for pixel;
  * the bars are W8T v3's (type1_row_layout, OFF == ON rects);
  * every bar face IDENTICAL within its state: each bar's whole column profile right of its text (ring included) is
    the same for every bar of the state, its top row vanilla's opening member (EE; E0 checked; the ring's E0 on the
    hovered row) and every face pixel type1_bar_colour of its row;
  * the initial build (all rows plain) obeys the same law;
  * g = 16: ON == OFF (the gate is closed: vanilla's draw);
  * the hover row (v2): the ring, then a full T-row AE stripe flush against it, then EE (vanilla: ring, AE, EE);
  * OFF at 1920x1080 shows the deployed defect (more than one look per state) -- the mutant the checks kill.
Coverage: GOVOPTIONS flat in game at one g per tier (GS: 16, T = 1 at 17 / 19, K < T at 22 / 24 incl. 1920x1080,
1600x1200, h % T != 0 at 26 / 33 / 38, 4K; screens 64g x 48g); Customize Game Rules (main menu) at 1280x1024 and
1600x1200; GOVOPTIONS in an ornate popup at 2560x1440.  Every g in 16..64 is test_type1_bar_asm_parity.py's (the
yaml bytes against the law, all states).
COST (~60 s serial over 13 items, 3-7 s each; why: the bar faces are pixel facts of the engine's own draw -- the band
map, its pair remap, the ring and the label over them -- which only a real-image boot shows): one boot + build per
item (the OFF / ON redraws share it); xdist spreads the items.
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
pytest.importorskip("pefile", reason="pefile absent")
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESP  # noqa: E402

import apply_patches as ap  # noqa: E402
import assemble_type1_rowcum as A  # noqa: E402
import scaling_laws as SL  # noqa: E402

P = SL.TYPE1_POPUP_ROW_PRESET
DRAW_ITEM = 0x0060F030
CHECKED = (1 << 0) | (1 << 3) | (1 << 4) | (1 << 9) | (1 << 16)
CURSOR = 2


@pytest.fixture(scope="module")
def mods():
    from conftest import _missing
    try:
        import ornate_popup_emu as O
        import textout_emu as T
        from image_emu import canvas_of
    except Exception as x:                              # no game dir / host GDI: the end-to-end layer cannot run
        _missing(Path("ornate_popup_emu"), f"the real-image popup renderer ({x})")
    if not (Path(O.GAME) / "interface.pcx").is_file():
        _missing(Path(O.GAME) / "interface.pcx", "the game's frame art")
    return O, T, canvas_of


@pytest.fixture(scope="module")
def rel32s(baked_exe):
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    st = dict(ap.build_symbol_table(symbols, caves))
    return {"on": struct.pack("<i", st["t1c_bar"] - (A.SITE_BAR + 5)),
            "off": struct.pack("<i", st["t_rowbox_solid"] - (A.SITE_BAR + 5))}


def render(mods, exe: str, rel32s: dict, screen, label="GOVOPTIONS", ornate=False, mainwin=True) -> dict:
    O, T, canvas_of = mods
    this, rects, cur = [], [], {}

    def at_site(e):
        esp = e.reg(UC_X86_REG_ESP)
        cur["set"], cur["state"] = e.r32(esp + 4) & 0xFFFFFFFF, e.reg(UC_X86_REG_EDI)

    def after(e):                                       # the fn's local rect as the draw left it (+1 R / B: extent)
        ebp = e.reg(UC_X86_REG_EBP)
        r = [e.s32(ebp - 0x14 + 4 * i) for i in range(4)]
        rects.append(dict(rect=(r[0], r[1], r[2] + 1, r[3] + 1), set=cur["set"], state=cur["state"]))

    with T.text_rendering():
        hh = O.H(exe, *screen, kind="XPOP2", label=label, ornate_mode=ornate, flags=0x41, mainwin=mainwin, later=False,
                 hooks=[(0x405BF6, at_site), (0x405BFB, after), (DRAW_ITEM, lambda e: this.append(e.reg(UC_X86_REG_ECX)))])
        e = hh.e
        assert bytes(e.uc.mem_read(A.SITE_BAR + 1, 4)) == rel32s["on"]
        lst = max(hh.children, key=lambda k: k["h"])
        out = dict(g=max(hh.g, 16), first=lst["canvas"].astype(int), first_rects=list(rects))
        cl = this[0]
        d = cl + e.r32(e.r32(cl) + 8)
        n = out["n"] = e.s32(d + 0x58)
        e.w32(d + 0xEC, CHECKED & ((1 << n) - 1))
        e.w32(d + 0xF0, CURSOR)
        for k in ("off", "on"):
            e.uc.mem_write(A.SITE_BAR + 1, rel32s[k])
            e.uc.ctl_remove_cache(A.SITE_BAR & ~0xFFF, (A.SITE_BAR + 0x1000) & ~0xFFF)   # the JIT keeps the old call
            rects.clear()
            for i in range(n):
                e.call(DRAW_ITEM, ecx=cl, args=(i, (CHECKED >> i) & 1))
            out[k] = canvas_of(e, lst["win"]).astype(int)
            out[k + "_rects"] = list(rects)
        e.uc.mem_write(A.SITE_BAR + 1, rel32s["on"])
    hh.e.uc = None
    hh.e = None
    del hh
    gc.collect()
    return out


def law(canvas, rects, g):
    c = [list(r) for r in canvas.tolist()]
    for k in rects:
        c = SL.type1_bar_restripe(c, k["rect"], k["set"], g)
    return np.array(c)


def faces_ok(canvas, rects, g, x_face):
    """Every bar's column profile at x_face (right of its text: the face + the ring) identical within the state; its
    first row vanilla's opening (the ring's E0 on the hovered row); every pair pixel of the bar on the law."""
    looks = {}
    for k in rects:
        l, t, r, b = k["rect"]
        o, m = SL.type1_bar_pair(k["set"])
        prof = tuple(canvas[t:b, x_face])
        looks.setdefault(k["state"], set()).add(prof)
        assert prof[0] == (0xE0 if k["state"] == 1 else o), (g, k, prof[:4])
        sub = canvas[t:b, l:r]
        want = np.array([SL.type1_bar_colour(y, t, k["set"], g) for y in range(t, b)])[:, None]
        mem = (sub == o) | (sub == m)
        assert (np.broadcast_to(want, sub.shape)[mem] == sub[mem]).all(), (g, k["rect"])
    return looks


def check(r: dict, n_rows: int):
    g = r["g"]
    assert r["n"] == n_rows
    on, off = r["on"], r["off"]
    assert [k["rect"] for k in r["on_rects"]] == [k["rect"] for k in r["off_rects"]]
    lay = SL.type1_row_layout(n_rows, P, g)
    native = 1 if g <= 16 else 0                        # g <= 16: the native draw leaves the rect half-open (no trim)
    assert [(k["rect"][1], k["rect"][3] - native) for k in r["on_rects"]] == lay, ("bars", g)
    states = [k["state"] for k in r["on_rects"]]
    assert states == [2 if (CHECKED >> i) & 1 else (1 if i == CURSOR else 0) for i in range(n_rows)]
    if g <= 16:
        assert (on == off).all()
        return
    assert (on == law(off, r["off_rects"], g)).all(), ("ON is the law of OFF", g)
    x_face = on.shape[1] - max(4, (20 * g) >> 4)
    looks = faces_ok(on, r["on_rects"], g, x_face)
    t, k = SL.stripe_rows(g), SL.stroke_width(g)
    for b in r["on_rects"]:                             # v2: the hover interior opens on a full mate stripe at the ring
        if b["state"] == 1:
            prof = list(on[b["rect"][1]:b["rect"][3], x_face])
            assert prof[:k] == [0xE0] * k and prof[k:k + t] == [0xAE] * t and prof[k + t] == 0xEE, (g, prof[:6])
    assert all(len(v) == 1 for v in looks.values()), (g, {s: len(v) for s, v in looks.items()})
    first = r["first"]
    assert {tuple(first[t:b, x_face]) for t, b in lay}.__len__() == 1
    faces_ok(first, r["first_rects"], g, x_face)
    return looks, faces_ok_off(off, r["off_rects"], x_face)


def faces_ok_off(off, rects, x_face):
    looks = {}
    for k in rects:
        _l, t, _r, b = k["rect"]
        looks.setdefault(k["state"], set()).add(tuple(off[t:b, x_face]))
    return looks


GS = (16, 17, 19, 22, 24, 25, 26, 33, 38, 40)    # one per tier: T 1 / 2, K < T (22, 24), h % T != 0 (26, 33, 38), 4K


@pytest.mark.parametrize("g", GS)
def test_governor_every_g(mods, baked_exe, rel32s, g):
    r = render(mods, str(baked_exe), rel32s, (64 * g, 48 * g))
    out = check(r, 19)
    if g == 22:                                         # the deployed defect, the mutant this test kills
        _on, off_looks = out
        assert max(len(v) for v in off_looks.values()) >= 2


@pytest.mark.parametrize("screen", ((1280, 1024), (1600, 1200)))
def test_customize_rules(mods, baked_exe, rel32s, screen):
    r = render(mods, str(baked_exe), rel32s, screen, label="RULES", mainwin=False)
    check(r, r["n"])


def test_governor_ornate_1440(mods, baked_exe, rel32s):
    r = render(mods, str(baked_exe), rel32s, (2560, 1440), ornate=True)
    check(r, 19)
