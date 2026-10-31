"""The in-game popup's body-text box is drawn HALF-OPEN at its bottom, end to end on the real image (W9C F54,
2026-10-27).

Law (scaling_laws.py, the source of truth): popup_body_box_bottom -- when the outer d5a0 union is the body-text rect
alone, the rect's B is decremented once before the inner d528 draw (0x406154) and the union inherits it, so both bottom
strokes land where vanilla's half-open 9-slice puts them; ported by t_gv_bodyb (assemble_body_box.py; asm parity in
test_body_box_asm_parity.py).

REACH (independent audit W9C, scratchpad audit-w9C): every popup with body text whose union is the text rect alone --
  * no dialog element ([+0x2350] == -1): the Planetary Governor (GV), every plain text + OK popup, flat (PD) and ornate,
    the TutWin windows (TW: LANDFALL), the untitled ornate MPRECEIVEFILE (MR);
  * an ART popup ([+0x2144] != 0), WITH or without a dialog: vanilla skips the UnionRect for art popups (0x4061D0), so
    their union boxes the text only -- UPHEAVAL (UP, art + a dialog list), NERVESTAPLE, CALLSCOUNCIL.
Untouched: a popup WITHOUT art that has body text AND a dialog -- its union is UnionRect(text, dialog) (#RENAME,
case RN, dialog type 4; COUNCILVOTE) -- a popup without body text (the site does not run: #NEWBASE, the list popups),
the faction-quote popup, g <= 16.

The defect (user shot 20261027-133512, reproduced by ornate_popup_emu case GV on the bb211440 bake): the Governor
popup's union -> OK channel 7 at 1920x1080 against 6 x 22/16 = 8.25 (vanilla 6 at 1024x768), 1.88 short at g 21 / 29:
the band-map thunks draw a half-open rect's B row.  The same 1 row on every popup in the reach.

END TO END (ornate_popup_emu: each popup built by its own caller's sequence, to the modal loop), every case rendered
twice -- with t_gv_bodyb and with the site's old target thunk_d528_inset restored at Popup_on_draw_background's entry:
  * the body rect's B as the site sees it, and the union rect at 0x406238, logged; the law's B (B - 1 in the reach)
    reaches the union (its bottom one row up), nothing else of either rect moves;
  * the two renders differ only inside the box's bottom band (inner stroke .. outer stroke, one row up);
  * text + OK popups (GV, PD, TW): the union's drawn bottom ends fl(6 g / 16) rows above the OK bar (vanilla 6);
  * GV, pixel-measured: the union's inner / outer stroke gaps equal top and bottom.
RN renders byte-identical with and without the thunk; at g = 16 the Governor popup equals the pristine .bak's.

COST: ~10 s per render, two renders per item (GV x 4 g, PD, TW, UP x 2, RN, the g = 16 pair on the .bak): ~3.5 min
serial, independent items over one shared bake, so they split across the xdist workers.  The with / without pair is
what proves the thunk touches only the bottom strokes; nothing cheaper reads the composed popup.
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
pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402
import apply_patches as ap  # noqa: E402
import ornate_popup_emu as O  # noqa: E402

OUT, INN, ART = 31, 34, 35             # the d5a0 union (outer), the d528 frame (inner), the art frame indices
SITE, POPP = 0x406154, 0x48C0A0
RES = {18: (1600, 900), 22: (1920, 1080), 25: (1600, 1200), 40: (3840, 2160)}


def _sym():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return dict(ap.build_symbol_table(symbols, caves))


BG, UNION_SITE = 0x405C80, 0x406238    # Popup_on_draw_background; its d5a0 union draw


def _hooks(old_target: bool):
    """(hooks, log): log the body rect / dialog / art / popup at the d528 site (before the call) and the union rect at
    0x406238; with old_target, restore the site's pre-F54 target (call thunk_d528_inset) at every
    Popup_on_draw_background entry -- the 'without' render."""
    from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ESI
    tgt = _sym()["thunk_d528_inset"]
    log = []

    def rect(e, a):
        return tuple(e.s32(a + 4 * i) for i in range(4))

    def at_site(e):
        ebp, esi = e.reg(UC_X86_REG_EBP), e.reg(UC_X86_REG_ESI)
        log.append(("B", rect(e, ebp - 0x34), e.s32(esi + 0x2350), e.r32(esi + 0x2144), esi))

    def at_union(e):
        log.append(("U", rect(e, e.reg(UC_X86_REG_EBP) - 0x24)))

    def at_bg(e):
        if old_target:
            e.uc.mem_write(SITE, b"\xE8" + struct.pack("<i", tgt - (SITE + 5)))
    return [(BG, at_bg), (SITE, at_site), (UNION_SITE, at_union)], log


def render(exe, case, W, H, old_target=False):
    hooks, log = _hooks(old_target)
    r = O.render(str(exe), case, W, H, hooks=hooks)
    b = next(x for x in log if x[0] == "B")                            # the first draw (DRAW #1)
    u = next(x for x in log[log.index(b):] if x[0] == "U")
    r.update(body=b[1], dialog=b[2], art=b[3], popup=b[4], union=u[1])
    return r


def check_pair(r, r0, g, ok_channel):
    """The law's B reaches the union, nothing else moves, only the bottom band differs, the OK channel."""
    l, t, rr, b = r0["body"]
    want = SL.popup_body_box_bottom(b, r0["dialog"], r0["art"], r0["popup"], g)
    assert want == b - 1, ("not in the reach", r0["dialog"], hex(r0["art"]))
    assert r["body"] == r0["body"]                                       # logged before the call: the same rect
    ul, ut, ur, ub = r0["union"]
    assert r["union"] == (ul, ut, ur, ub - 1), (r["union"], r0["union"])
    k = SL.stroke_width(g)
    diff = set(np.nonzero((r["d1"] != r0["d1"]).any(axis=1))[0].tolist())
    band = set(range(want - k - 1, ub + 2))
    assert diff and diff <= band, (g, sorted(diff), min(band), max(band))
    if ok_channel:
        ok = max((c for c in r["children"] if c["h"] < 120), key=lambda c: c["y"])
        assert ok["y"] - ub == SL.popup_scale_floor(6, g), (g, ok["y"], ub)


def runs(m):
    out, s = [], None
    for i, b in enumerate(list(m) + [False]):
        if b and s is None:
            s = i
        if not b and s is not None:
            out.append((s, i))
            s = None
    return out


def body_box(r):
    """(outer union runs, inner frame runs) down the union's middle column, below the title pair; the OK bar's top."""
    c = r["d1"].astype(int)
    ok = max((k for k in r["children"] if k["h"] < 120), key=lambda k: k["y"])
    ys, xs = np.nonzero(c == ART)                                     # the art's frame (council_sm.pcx index 35)
    ym, art_r = (ys.min() + ys.max()) // 2, xs.max() + 1
    ro = [s for s in runs(c[ym] == OUT) if s[0] > art_r]              # the union's left / right strokes on that row
    xu = (ro[0][1] + ro[-1][0]) // 2
    co, ci = runs(c[:, xu] == OUT), runs(c[:, xu] == INN)             # title pair first, then the union / frame
    return co[2:4], ci[2:4], ok["y"]


@pytest.mark.parametrize("g", sorted(RES))
def test_governor_body_box_bottom_is_half_open(baked_exe, g):
    W, H = RES[g]
    r = render(baked_exe, "GV", W, H)
    r0 = render(baked_exe, "GV", W, H, old_target=True)
    assert r["g"] == g
    check_pair(r, r0, g, ok_channel=True)
    (uo_t, uo_b), (ui_t, ui_b), ok_y = body_box(r)
    assert ok_y - uo_b[1] == SL.popup_scale_floor(6, g), (g, uo_b, ok_y)
    assert ui_t[0] - uo_t[1] == uo_b[0] - ui_b[1], (g, uo_t, ui_t, ui_b, uo_b)
    (vo_t, vo_b), (vi_t, vi_b), _ = body_box(r0)
    assert (vo_t, vi_t) == (uo_t, ui_t) and vo_b[0] == uo_b[0] + 1 and vi_b[0] == ui_b[0] + 1
    diff = np.nonzero((r["d1"] != r0["d1"]).any(axis=1))[0]
    band = set(range(ui_b[0] - 1, uo_b[1] + 1))       # the box's bottom band: inner stroke .. outer stroke, one row up
    assert set(diff.tolist()) <= band, (g, diff.tolist(), sorted(band))   # (its channel rows re-striped with it)


REACH = [("PD", 18, True), ("TW", 22, True), ("UP", 22, False), ("UP", 40, False)]


@pytest.mark.parametrize("case,g,ok_channel", REACH, ids=[f"{c}-g{g}" for c, g, _ in REACH])
def test_the_reach_beyond_the_governor(baked_exe, case, g, ok_channel):
    """A plain text + OK popup (PD), the TutWin LANDFALL window (TW), an art popup with a dialog list (UP): each in the
    law's reach, each moved exactly as the Governor (UP's next element is its list, not an OK bar)."""
    W, H = RES[g]
    r = render(baked_exe, case, W, H)
    r0 = render(baked_exe, case, W, H, old_target=True)
    assert r["g"] == g
    check_pair(r, r0, g, ok_channel)


def test_dialog_popup_without_art_is_untouched(baked_exe):
    """#RENAME: body text, a dialog (type 4), no art -- the union is UnionRect(text, dialog), outside the law's reach:
    the site runs, B is left alone, the popup is byte-identical with and without t_gv_bodyb."""
    W, H = RES[22]
    a = render(baked_exe, "RN", W, H)
    b = render(baked_exe, "RN", W, H, old_target=True)
    assert a["dialog"] != -1 and a["art"] == 0
    assert SL.popup_body_box_bottom(a["body"][3], a["dialog"], a["art"], a["popup"], 22) == a["body"][3]
    assert a["d1"].shape == b["d1"].shape and (a["d1"] == b["d1"]).all()


def test_governor_native_is_pristine(baked_exe, bak_path):
    a = O.render(str(baked_exe), "GV", 1024, 768)
    b = O.render(str(bak_path), "GV", 1024, 768)
    assert a["d1"].shape == b["d1"].shape and (a["d1"] == b["d1"]).all()
    (uo_t, uo_b), (ui_t, ui_b), ok_y = body_box(b)
    assert ok_y - uo_b[1] == 6 and ui_t[0] - uo_t[1] == uo_b[0] - ui_b[1] == 2      # the vanilla relation, measured
