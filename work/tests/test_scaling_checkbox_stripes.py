"""The checkbox X sprites keep the one stripe law when enlarged, and the lobby panels around them follow it too (fix 28).

Law (scaling_laws.py, the source of truth): scanicon_axis_map / scanicon_pair_lut / scanicon_top_parity /
scanicon_pixels -- SHAPE = a mirror-symmetric NN map on both axes over fl(18 g/16) (the centre NN's outer widths
mirrored, the leftover in the middle pair); SHADE = per texel through the art's own (index, native row parity) pair
LUT, the member the DEST row's stripe wants (stripe_top on the canvas grid + phase); TOP parity = the brighter member of
the dominant pair.  checkbox_list_phase = the list canvas's parent-local top (Win +0x140 + +0x150) mod P; the lobby
phase is 0.  The lobby panel fills (audit F37): box_fill_rect / tile_scan_pair / panel_fill_pixel, phase 0.  Ports:
t_ck_draw / t_ck_list / t_ck_core / t_nw_box (assemble_checkbox_stripes.py; byte parity at every g 16..40 in
test_checkbox_stripes_asm_parity.py, which also cross-checks uimod.dll's Longevity-row call).

The defect (user shots 2026-10-24: lobby 124117 at 1920x1080, Customize Game Rules 125718 / 125856 / 125241,
Governor 125312, Preferences 125535): every checkbox was the engine's plain NN at g/16, so its 1-row scanline dither
came out as 1,2,1,1,2 runs at g = 22 / 25 and 2,3 at 4K -- the CLAUDE.md dither invariant; the lobby's panels kept
vanilla's 1:1 tile (1-row stripes where stripe_rows(g) = 2).

Layers:
  1. LAW (pure Python, ms): the real arts' pair LUTs and top parities (pinned); the axis map is mirror-symmetric on
     both axes at every g 17..40 (only an odd total splits the middle pair 1 px), every texel survives, NN's own widths
     kept where NN was already symmetric; at every g 17..40 and every phase the law's background is uniform T-row
     stripes on the canvas grid while the engine's NN (the parity-tested port assemble_stripes_spr.sd2_draw) bands at
     g 22 / 25 / 40; boxes and lobby panels put their bright member on the same rows at every g 17..40.
  2. END TO END (checkbox_emu.py on image_emu.py, on conftest's shared session `baked_exe`): the real screens in the
     engine's own call order -- the lobby (full NetWin_draw: panels + boxes), Customize Game Rules (flat), Governor
     Settings (ornate), the Preferences CheckList, the scenario editor's treaty CheckList -- every t_ck_draw is the law
     pixel for pixel right after it returns, its phase is checkbox_list_phase of its own dest window, and EVERY box
     with a 2-member background column beside it stripes on that column's grid (measured, not modelled); every lobby
     panel fill is the law and its fill rect is the rect the engine tiled.  At g = 16 the lobby and a PrefWin page equal
     the PRISTINE exe's canvases.

COST: layer 1 ~3 s.  Layer 2: 9 items, each boots the image (~2 s) and draws one screen (~1-6 s): ~45 s serial,
independent (the one shared bake), so xdist spreads them; no cheaper way exists to read the phase the engine's own
canvases carry.  The 4K PrefWin show (~20 s) and the treaty modal's own show (minutes of emulated idle) are not run:
the unit layer covers every g and phase, and the treaty build stops once its rows are drawn (DiploEditWin_update).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")

import assemble_stripes_spr as SPR  # noqa: E402
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402


# ============================================================================================ layer 1: the law
def _arts():
    try:
        from PIL import Image
        pcx = Image.open(config.game_dir(required=False) / "interface.pcx")
    except Exception:
        pytest.skip("interface.pcx (the game files) not found")
    a = np.array(pcx)
    p = np.array(pcx.getpalette()).reshape(-1, 3)
    pal = [(0, 0, 0)] * 10 + [tuple(int(c) for c in p[i]) for i in range(246)]
    # as the engine loads them (+10): 0x7794D8 = (227,1) unchecked, 0x779504 = (227,20), 0x779530 = (227,39) checked
    return {s: (a[y:y + 18, 227:245].astype(int) + 10).tolist() for s, y in ((0x7794D8, 1), (0x779504, 20),
                                                                          (0x779530, 39))}, pal


@pytest.fixture(scope="module")
def arts():
    return _arts()


PINNED_LUT = {
    0x7794D8: {(65, 1): 197, (194, 0): 197, (197, 0): 65, (197, 1): 194},
    0x779504: {(186, 1): 240, (194, 0): 197, (197, 1): 194, (240, 0): 186},
    0x779530: {(185, 0): 240, (224, 1): 226, (226, 0): 224, (240, 1): 185},   # not the 2-3-texel corner bevel C0/E2
}
PINNED_QT = {0x7794D8: 0, 0x779504: 0, 0x779530: 1}


def test_real_arts_pair_luts_and_top_parity(arts):
    """The dim art's 197 is the odd-row BACKGROUND and the even-row STROKE: keyed by (index, parity) both resolve.
    Top parity: dim / middle bg 194 (0d1c30) over 197 (0b1218) on even rows; bright bg 240 (353d73) over 185
    (11324f) on odd rows -- the colours of the user's shots."""
    rows, pal = arts
    for s, art in rows.items():
        lut, n = SL.scanicon_pair_lut(art, 9)
        assert lut == PINNED_LUT[s], hex(s)
        assert SL.scanicon_top_parity(lut, n, lambda i: pal[i]) == PINNED_QT[s], hex(s)


def _dominant(lut, n):
    best, w = None, -1
    for k in sorted(lut):
        v, p = k
        wgt = n[k] + n[(lut[k], p ^ 1)]
        if wgt > w:
            best, w = k, wgt
    return best


def _bg_rows_on_law(pix, art, keys, top_idx, mate_idx, g, y0, phase, src_map=None):
    """(pixels checked, pixels off-law): every dest pixel whose source texel is a DOMINANT-pair (background) texel
    -- by (index, parity) key: the dim art's 197 is also the stroke's even member -- must be the pair's TOP member iff
    stripe_top(dest row), its mate otherwise.  src_map(j, i) -> (sy, sx): the centre NN by default."""
    n = len(pix)
    mp = SL.scanicon_axis_map(n, 18)
    tot = off = 0
    for j, row in enumerate(pix):
        want_top = SL.stripe_top(y0 + j + phase, g)
        for i, v in enumerate(row):
            sy, sx = src_map(j, i) if src_map else (mp[j], mp[i])
            if (art[sy][sx], sy & 1) in keys:
                tot += 1
                off += int(v != (top_idx if want_top else mate_idx))
    return tot, off


def _bg(art, pal):
    """(the two dominant-pair keys, its top member, its mate)."""
    lut, n = SL.scanicon_pair_lut(art, 9)
    k = _dominant(lut, n)
    v, p = k
    m = lut[k]
    qt = SL.scanicon_top_parity(lut, n, lambda i: pal[i])
    top, mate = (v, m) if p == qt else (m, v)
    return {k, (m, p ^ 1)}, top, mate


@pytest.mark.parametrize("g", list(range(17, 41)))
def test_law_background_is_uniform_stripes_on_the_grid(arts, g):
    rows, pal = arts
    for s, art in rows.items():
        keys, top, mate = _bg(art, pal)
        for phase in range(SL.stripe_period(g)):
            for y0 in (0, 1, 597, 598):
                pix = SL.scanicon_pixels(art, 9, g, 16, g, y0, phase, lambda i: pal[i])
                assert len(pix) == len(pix[0]) == (18 * g) // 16
                tot, off = _bg_rows_on_law(pix, art, keys, top, mate, g, y0, phase)
                assert tot > 0 and off == 0, (hex(s), g, phase, y0)


def test_engine_nn_bands_the_same_art(arts):
    """The before image: the engine's NN (sd2_draw, parity-tested against the real bytes) puts the background pair's
    members on rows that no stripe phase explains at g 22 / 25 / 40 -- the user's shots."""
    rows, pal = arts
    for g in (22, 25, 40):
        for s, art in rows.items():
            keys, top, mate = _bg(art, pal)
            n = (18 * g) // 16
            dest = bytearray(n * n)
            SPR.sd2_draw(dest, n, art, 9, 0, 0, g)
            pix = [list(dest[j * n:(j + 1) * n]) for j in range(n)]
            cell = {(Y, X): (r, c) for X, Y, r, c in SPR.sd2_cells(0, 0, g, w=18, h=18)}
            for ph in range(SL.stripe_period(g)):
                tot, off = _bg_rows_on_law(pix, art, keys, top, mate, g, 0, ph, src_map=lambda j, i: cell[(j, i)])
                assert tot > 0 and off > 0, (hex(s), g, ph)


@pytest.mark.parametrize("g", list(range(17, 41)))
def test_axis_map_is_mirror_symmetric(g):
    """The user rule: symmetry beats 1-px exactness.  Widths of mirror texels are equal; only an odd total puts the
    leftover pixel in the middle pair (plain centre NN gave the edge columns 1 / 2 at g = 24 and 2 / 3 at 40); every
    texel survives; the widths are NN's own wherever NN was already symmetric.  Both axes use the one map."""
    n = (18 * g) // 16
    m = SL.scanicon_axis_map(n, 18)
    assert len(m) == n and m == sorted(m) and m[0] == 0 and m[-1] == 17
    w = [m.count(k) for k in range(18)]
    nn = [[SL.nn_center_index(d, n, 18) for d in range(n)].count(k) for k in range(18)]
    assert min(w) >= 1 and sum(w) == n
    for k in range(8):                                   # the 8 outer pairs: exactly mirrored
        assert w[k] == w[17 - k] == nn[k], (g, k, w)
    assert abs(w[8] - w[9]) == n % 2                     # the middle pair: equal, or 1 apart for an odd total
    assert all(w[k] == nn[k] for k in range(18) if nn[k] == nn[17 - k] and k not in (8, 9))
    for d in range(n // 2 - (2 if n % 2 else 0)):        # the index map itself mirrors outside the middle pair
        if m[d] < 8:
            assert m[n - 1 - d] == 17 - m[d]


def test_axis_map_general_sizes():
    """Any sprite size the law may see (odd and even): monotone, every texel >= 1 px, mirror widths except the
    middle (pair or texel) taking the remainder."""
    for src in (4, 5, 9, 14, 17, 18, 21, 32):
        for n in range(src, 3 * src + 1):
            m = SL.scanicon_axis_map(n, src)
            w = [m.count(k) for k in range(src)]
            assert m == sorted(m) and min(w) >= 1 and sum(w) == n, (src, n, w)
            k_out = src // 2 - 1 if src % 2 == 0 else src // 2
            assert all(w[k] == w[src - 1 - k] for k in range(k_out)), (src, n, w)


@pytest.mark.parametrize("g", [17, 19, 22, 25, 30, 40])
def test_law_shape_is_the_symmetric_class_map(arts, g):
    """Shading only ever swaps a texel for its own pair mate: the class map (pair members merged) is exactly the
    symmetric NN map of the art's -- every native row and column included."""
    rows, pal = arts
    for s_, art in rows.items():
        lut, _n = SL.scanicon_pair_lut(art, 9)

        def cls(v, par):
            m = lut.get((v, par))
            return frozenset((v, m)) if m is not None else frozenset((v,))
        pix = SL.scanicon_pixels(art, 9, g, 16, g, 3, 1, lambda i: pal[i])
        n = len(pix)
        mp = SL.scanicon_axis_map(n, 18)
        for j in range(n):
            for i in range(n):
                assert pix[j][i] in cls(art[mp[j]][mp[i]], mp[j] & 1), (hex(s_), g, j, i)


@pytest.mark.parametrize("g", list(range(17, 41)))
def test_boxes_and_lobby_panels_share_the_grid(arts, g):
    """The lobby box (t_ck_core, phase 0) and the lobby panel fill (t_nw_box, phase 0) show their bright member on the
    same NetWin canvas rows at every g: a panel pixel's member == the box background's member, row by row."""
    rows, pal = arts
    rgb = lambda i: pal[i]  # noqa: E731
    art = rows[0x779530]
    keys, top, mate = _bg(art, pal)
    for y0 in (0, 1, 2, 3, 570, 597):
        pix = SL.scanicon_pixels(art, 9, g, 16, g, y0, 0, rgb)
        mp = SL.scanicon_axis_map(len(pix), 18)
        for j, row in enumerate(pix):
            bright_box = None
            for i, v in enumerate(row):
                if (art[mp[j]][mp[i]], mp[j] & 1) in keys:
                    bright_box = v == top
                    break
            for a, b in ((0xC4, 0x41), (0xC6, 0x41)):
                panel = SL.panel_fill_pixel(a, y0 + j, g, a, b, rgb)
                bright_panel = panel == a                     # C4 / C6 are the brighter members
                if bright_box is not None:
                    assert bright_box == bright_panel, (g, y0, j)


def test_tile_scan_pair_and_fill_rect():
    assert SL.tile_scan_pair([[0xC6] * 24 if r % 2 == 0 else [0x41] * 24 for r in range(24)]) == (0xC6, 0x41)
    assert SL.tile_scan_pair([[0xC4] * 24 for _ in range(24)]) is None
    assert SL.tile_scan_pair([[0xC4, 0x41] * 12 for _ in range(24)]) is None
    assert SL.box_fill_rect((9, 79, 423, 528), 6, 6, 6, 6) == (15, 85, 417, 522)   # emulated: the tile call's rect


def test_checkbox_list_phase_is_the_row_bars_phase():
    for g in range(17, 41):
        for t1, t2 in ((64, 0), (73, 0), (25, 0), (13, 0), (0, 59), (-3, 0), (410, 225)):
            assert SL.checkbox_list_phase(t1, t2, g) == SL.option_row_stripe_phase(t1, t2, g)
    assert SL.checkbox_list_phase(25, 0, 40) == 1          # PrefWin CheckList at 4K: one row off the canvas grid
    assert SL.checkbox_list_phase(73, 0, 25) == 1          # Governor (ornate) list at 1600x1200


# ============================================================================================ layer 2: end to end
def _check_draws(rec, g, pal, *, list_phase: bool):
    assert rec.draws, "no checkbox drawn"
    br = [sum(int(c) for c in pal[i]) for i in range(256)]
    refs = 0
    for d in rec.draws:
        assert (d["num"], d["den"]) == (g, 16) and d["key"] == 9
        want_ph = SL.checkbox_list_phase(*d["tops"], g) if list_phase else 0
        assert d["ph"] == want_ph, d["tops"]
        exp = SL.scanicon_pixels(d["art"], 9, g, 16, g, d["y"], d["ph"], lambda i: tuple(int(c) for c in pal[i]))
        y0, x0, snap = d["snap"]
        for j, row in enumerate(exp):
            for i, v in enumerate(row):
                Y, X = d["y"] + j - y0, d["x"] + i - x0
                if v is not None and 0 <= Y < snap.shape[0] and 0 <= X < snap.shape[1]:
                    assert snap[Y, X] == v, (hex(d["spr"]), d["x"], d["y"], j, i)
        # the grid the box stripes on == the grid of the background beside it (the nearest 2-member column left /
        # right): EVERY box that has one must match
        n, nw = len(exp), len(exp[0])
        for X in [d["x"] - 1 - k - x0 for k in range(4)] + [d["x"] + nw + k - x0 for k in range(4)]:
            if not 0 <= X < snap.shape[1]:
                continue
            col = [int(v) for v in snap[max(d["y"] - y0, 0):d["y"] - y0 + n, X]]
            if len(col) == n and len(set(col)) == 2:
                hi = max(set(col), key=lambda v: (br[v], -v))
                assert [j for j, v in enumerate(col) if v == hi] == \
                    [j for j in range(n) if SL.stripe_top(d["y"] + j + d["ph"], g)], (hex(d["spr"]), d["x"], d["y"])
                refs += 1
                break
    return refs


def _check_panels(pr, g, pal):
    rgb = lambda i: tuple(int(c) for c in pal[i])  # noqa: E731
    pairs = set()
    for b in pr.boxes:
        t, bt, l, r = b["dims"]
        fr = SL.box_fill_rect(b["rect"], l, t, r, bt)
        pair = SL.tile_scan_pair(b["tile_rows"]) if b["tile_rows"] else None
        assert pair, ("every t_nw_box site fills with a row-dither tile", hex(b["site"]))
        assert tuple(b["tiled"]) == tuple(fr), ("the law's fill rect is the rect the engine tiled", hex(b["site"]))
        pairs.add(pair)
        c = b["canvas"]
        x0, y0, x1, y1 = max(fr[0], 0), max(fr[1], 0), min(fr[2], c.shape[1]), min(fr[3], c.shape[0])
        assert x1 > x0 and y1 > y0
        blk = c[y0:y1, x0:x1]
        assert set(np.unique(blk).tolist()) <= set(pair)
        for y in range(y0, y1):
            row = set(c[y, x0:x1].tolist())
            assert len(row) == 1, (hex(b["site"]), y)
            v = row.pop()
            assert SL.panel_fill_pixel(v, y, g, *pair, rgb) == v, (hex(b["site"]), y)
    return pairs


#: g 18 / 19 / 22 / 25 / 30 / 40 across the screens; list tops odd and even (GOV 19: 55, 30: 88; RULES 25: 59;
#: PrefWin 22: 13; treaty 22: 31); both checkbox states on every screen but the treaty list (no treaty set).
E2E = [("lobby", 18), ("lobby", 22), ("lobby", 40), ("RULES", 25), ("GOV", 19), ("GOV", 30), ("prefs", 22),
       ("treaty", 22)]


@pytest.mark.parametrize("screen, g", E2E)
def test_every_checkbox_is_the_law_on_the_canvas_grid(baked_exe, screen, g):
    import checkbox_emu as CE
    pal = CE.palette()
    rec = CE.Recorder(pal)
    pr = None
    if screen == "lobby":
        pr = CE.PanelRecorder(pal, LOBBY_PANEL_SITES)
        out = CE.lobby(str(baked_exe), g, rec, pr)
    elif screen == "prefs":
        out = CE.prefs(str(baked_exe), g, 0, rec)
    elif screen == "treaty":
        out = CE.treaty(str(baked_exe), g, rec)
    else:
        out = CE.popup(str(baked_exe), g, "RULES" if screen == "RULES" else "GOV", rec)
    assert out["g"] == g
    sprites = {d["spr"] for d in rec.draws}
    if screen != "treaty":
        assert sprites & {0x779530} and sprites & {0x7794D8, 0x779504}, "checked AND unchecked boxes"
    refs = _check_draws(rec, g, pal, list_phase=screen != "lobby")
    assert refs >= len(rec.draws) - 2, f"a background reference beside only {refs} of {len(rec.draws)} boxes"
    if screen == "lobby":                               # the pull-down arrows (2026-11-07): the same law, phase 0
        arrows = [d for d in rec.draws if d["spr"] == SL.LOBBY_ARROW_SPRITE]
        assert len(arrows) >= 8, "the roster arrows reach t_ck_draw"
        assert all(d["art"] == ARROW_ART for d in arrows), "the real arrow is the 7x13 ae / ee art"
    if pr is not None:
        assert len(pr.boxes) >= 40                      # 17 sites, the roster rows repeat
        assert _check_panels(pr, g, pal) == {(0xC6, 0x41), (0xC4, 0x41), (0x27, 0x22)}


#: the lobby's pull-down arrow 0x788038 as the engine holds it (interface.pcx +10, key 9): a 1-row ae / ee dither
ARROW_AE, ARROW_EE = 0xAE, 0xEE
ARROW_ART = [[(ARROW_AE if r % 2 == 0 else ARROW_EE) if c <= min(r, 12 - r) else 9 for c in range(7)] for r in range(13)]


@pytest.mark.parametrize("g", list(range(17, 41)))
def test_law_arrow_is_uniform_stripes_and_mirror_symmetric(g):
    """The arrow under the law: every texel shows the member its dest row's stripe wants (the law's own top parity)
    and the triangle's outline stays mirror-symmetric about its tip row."""
    import checkbox_emu as CE
    pal = CE.palette()
    rgb = lambda i: tuple(int(c) for c in pal[i])  # noqa: E731
    lut, n = SL.scanicon_pair_lut(ARROW_ART, 9)
    qt = SL.scanicon_top_parity(lut, n, rgb)
    top = ARROW_AE if qt == 0 else ARROW_EE
    other = ARROW_EE if top == ARROW_AE else ARROW_AE
    for y0 in (0, 1, 84, 115, 266):
        pix = SL.scanicon_pixels(ARROW_ART, 9, g, 16, g, y0, 0, rgb)
        assert len(pix) == (13 * g) // 16 and len(pix[0]) == (7 * g) // 16
        for j, row in enumerate(pix):
            want = top if SL.stripe_top(y0 + j, g) else other
            assert all(v in (None, want) for v in row), (g, y0, j)
        shape = [[v is not None for v in row] for row in pix]
        widths = [sum(r) for r in shape]
        assert widths == widths[::-1], (g, widths)          # 13 rows: an odd source, the middle texel takes the rest


def test_engine_nn_bands_the_arrow():
    """The before image: the engine's NN of the arrow puts its two members on rows no stripe phase explains at 1080p."""
    for g in (22, 25):
        n = (13 * g) // 16
        rows = [ARROW_ART[SL.nn_center_index(j, n, 13)][0] for j in range(n)]
        runs, k = [], 1
        for a, b in zip(rows, rows[1:]):
            if a == b:
                k += 1
            else:
                runs.append(k)
                k = 1
        runs.append(k)
        assert len(set(runs[1:-1])) > 1, (g, runs)


ARROW_SITES_ROSTER = (0x47FFD2, 0x48027C, 0x480620)                         # via thunk_nw_blit_right
ARROW_SITES_SETTINGS = (0x480BA8, 0x480CCA, 0x480EC2, 0x4810EB, 0x481297, 0x481441, 0x4815ED, 0x481797)   # via _gap
NW_BLIT_LEFT = 0x00A0C000 + 0x4920


@pytest.mark.parametrize("g", (18, 22, 25, 40))
def test_every_lobby_arrow_site_draws_the_law(baked_exe, g):
    """The host lobby (NetWin_draw_settings draws its arrows only for the host): all 11 arrow sites reach
    thunk_nw_blit_left, every one of those draws reaches t_ck_draw (none falls back to the engine), and each is the
    law on the canvas grid (_check_draws)."""
    import checkbox_emu as CE
    from unicorn.x86_const import UC_X86_REG_ESP
    pal = CE.palette()
    rec = CE.Recorder(pal)
    sites = []
    hook = (NW_BLIT_LEFT, lambda e: sites.append(e.r32(e.reg(UC_X86_REG_ESP)) - 5))
    out = CE.lobby(str(baked_exe), g, rec, host=True, hooks=[hook])
    assert out["g"] == g
    assert set(sites) == set(ARROW_SITES_ROSTER + ARROW_SITES_SETTINGS), sorted(map(hex, set(sites)))
    assert all(sites.count(s) == 1 for s in ARROW_SITES_SETTINGS)
    arrows = [d for d in rec.draws if d["spr"] == SL.LOBBY_ARROW_SPRITE]
    assert len(arrows) == len(sites), "every arrow draw went through the law"
    assert all(d["art"] == ARROW_ART for d in arrows)
    _check_draws(rec, g, pal, list_phase=False)


LOBBY_PANEL_SITES = (0x47F9A5, 0x47FA3E, 0x47FA51, 0x47FEAB, 0x47FEBE, 0x47FF2B, 0x4801DB, 0x4803CD, 0x48049D,
                     0x4804B0, 0x4804D6, 0x4809A6, 0x480A40, 0x481AFB, 0x481B5D, 0x481C0F, 0x481C22)


@pytest.mark.parametrize("screen", ["lobby", "prefs"])
def test_g16_canvases_equal_the_pristine_exe(baked_exe, bak_path, screen):
    """g = 16: the lobby (every panel site + both checkbox sites) and the PrefWin page with the fewest rows (page 0)
    are byte-identical to the pristine exe; the list sites' g <= 16 call is the vanilla one by construction (unit
    layer) and the audit's emulated RULES / GOV / treaty pairs."""
    import checkbox_emu as CE
    outs = [CE.lobby(exe, 16) if screen == "lobby" else CE.prefs(exe, 16, 0) for exe in (str(baked_exe), str(bak_path))]
    a, b = outs
    assert a["g"] == 16 and set(a["canvases"]) == set(b["canvases"])
    for k in a["canvases"]:
        assert a["canvases"][k].shape == b["canvases"][k].shape and (a["canvases"][k] == b["canvases"][k]).all(), k
