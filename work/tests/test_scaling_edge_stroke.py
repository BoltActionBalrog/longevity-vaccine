"""1-px art edge strokes and corner notches on bar faces, and the Load / Save button pair (2026-10-25 wave-2 W2D).

Laws (scaling_laws.py, the source of truth):
  btn_edge_stroke    K = ceil(g/16) = btn_corner_notch = btn_ring_k: a 1-px art edge stroke is a K band, same width on
                     all four sides, solid, in every state that carries one;
  btn_edge_probe     which edges of a native 9-slice face carry a 1-px stroke (not key, unlike both next texels inward);
  btn_edge_band      the bands on the zoomed face (rows [0, D), key pixels kept);
  nn_mirror_index / drop_arrow_render v3   the faction picker's drop arrows;
  faction_row_face   the faction picker's name rows (s x s background notches + K hover bands);
  filedlg_btn_pair   the Load / Save OK | CANCEL windows (one width, the odd px to the seam, B = T + fl(22g/16)).

The defects (user shots 2026-10-25, measured on the real image here):
  F39  4K lobby 000608 / 000611: the hover face's light outline 1 | 2 (g 24) and 2 | 3 (g 40) left|right, restriped;
  F40a 1600x1200 000825: the drop arrows' corners TL 2x2 / TR 1x2 / BL 2x1 / BR 1x1 (and the glyph 1 px off-centre,
       the pressed face's E0 / E1 dither NN-banded);
  F40b 1600x1200 000825: the name rows' 1 x 1 notches at every g (the bar buttons: ceil(g/16)), a 1-px hover ring;
  F41  1600x1200 000837: OK 228 | CANCEL 230 x 35 in game (vanilla 146 | 147 x 22, a mirrored pair), a 30-row face.

Proof layers: 1. the laws (pure); 2. END TO END on the real image of conftest's bake -- the lobby's LAUNCH GAME (a real
default-art 9-slice FlatButton, netwin_lobby_emu.py; the stretch modelled AND, on Windows, the host GDI StretchBlt),
the faction picker (faction_picker_emu.py: the real builder, list, drop arrows, row painter), the FileDlg layout
(filedlg_emu.py); g = 16 against the pristine image.  The thunks' own Unicorn parity: test_edge_stroke_asm_parity.py.

COST: per worker a lobby boot (~2 s), a picker boot (~2 s; each g re-runs the builder, 0.5..4 s) and a FileDlg boot
(~2 s; each layout ~1..2 s); the pristine comparisons boot the .bak once more each.
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
pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402

KEY = 9
OUTLINE = {0xE0, 0xE1}


# ============================================================================== 1. laws
def test_law_edge_stroke_is_the_notch_and_the_ring():
    for g in range(1, 73):
        assert SL.btn_edge_stroke(g) == SL.btn_corner_notch(g) == (1 if g <= 16 else -(-g // 16))
        if g > 16:
            assert SL.btn_edge_stroke(g) == SL.btn_ring_k(g)


@pytest.mark.parametrize("g", range(17, 41))
def test_law_band_covers_every_nn_run_of_a_1px_stroke(g):
    """K >= the centre-NN image of a 1-px edge column / row, for every native size a bar face zooms from."""
    k = SL.btn_edge_stroke(g)
    for native in (16, 20, 22, 192, 216, 236):
        for dev in range(SL.popup_scale_floor(native, g) - 1, SL.popup_scale_floor(native, g) + 3):
            for n in {native, SL.btn_native_dim(dev, g)}:
                idx = [SL.nn_center_index(j, dev, n) for j in range(dev)]
                assert idx.count(0) <= k and idx.count(n - 1) <= k, (g, native, dev, n)


def test_law_edge_stroke_colour():
    assert SL.edge_stroke_colour(0xE0, 0xEE, 0xAE) == 0xE0          # the hover ring over the AE / EE body
    assert SL.edge_stroke_colour(0xAE, 0xEE, 0xAE) is None          # a period-2 dither edge
    assert SL.edge_stroke_colour(0xE1, 0xE0, 0xE1) is None          # the pressed face's dither
    assert SL.edge_stroke_colour(0xAE, 0xAE, 0xEE) is None          # a solid (2-px) run
    assert SL.edge_stroke_colour(KEY, 0xEE, 0xAE) is None           # a keyed edge


def test_law_mirror_nn_is_symmetric_monotone_and_onto():
    for src in range(1, 33):
        for dst in range(src, 97):
            idx = [SL.nn_mirror_index(j, dst, src) for j in range(dst)]
            assert idx == sorted(idx) and set(idx) == set(range(src)), (dst, src)
            mid = {dst // 2} if dst % 2 and src % 2 == 0 else set()     # an odd dest's middle over an even src
            assert all(idx[j] + idx[dst - 1 - j] == src - 1 for j in range(dst) if j not in mid), (dst, src)
            half = (dst - 1) // 2
            assert idx[:half + 1] == [SL.nn_center_index(j, dst, src) for j in range(half + 1)]


def _arrow(state):
    """The faction picker's measured drop arrow (16 x 16; faction_picker_emu reads the real sprites, same layout)."""
    top, mate = ((0xAE, 0xEE), (0xAE, 0xEE), (0xE1, 0xE0))[state]
    rows = []
    for y in range(16):
        r = []
        for x in range(16):
            if x in (0, 15) and y in (0, 15):
                r.append(KEY)
            elif state == 1 and (x in (0, 15) or y in (0, 15)):
                r.append(0xE0)
            elif 5 <= y <= 10 and 2 + (y - 5) <= x <= 13 - (y - 5):
                r.append(0xE0 if state == 1 else 0x41)
            else:
                r.append(top if y % 2 == 0 else mate)
        rows.append(r)
    return rows


@pytest.mark.parametrize("g", range(17, 61))
def test_law_drop_arrow(g):
    s = k = SL.btn_corner_notch(g)
    n = (16 * g) >> 4
    for state in (0, 1, 2):
        out = SL.drop_arrow_render(_arrow(state), n, n, g)
        for y in range(n):                                             # the glyph and every band: left == right
            assert [v == 0x41 or (state == 1 and v == 0xE0) for v in out[y]] == \
                   [v == 0x41 or (state == 1 and v == 0xE0) for v in out[y][::-1]], (g, state, y)
        for (y0, x0) in ((0, 0), (0, n - s), (n - s, 0), (n - s, n - s)):
            assert all(out[y][x] == KEY for y in range(y0, y0 + s) for x in range(x0, x0 + s)), (g, state)
        assert out[s][0] != KEY and out[0][s] != KEY, "exactly s x s"
        if state == 1:                                                 # the ring: K on every side, then the body
            mid = n // 2
            assert out[mid][:k] == [0xE0] * k and out[mid][n - k:] == [0xE0] * k, (g, out[mid])
            assert [r[mid] for r in out[:k]] == [0xE0] * k and [r[mid] for r in out[n - k:]] == [0xE0] * k
            assert out[mid + 1][k] != 0xE0 or out[mid][k] != 0xE0, "K, not more (the glyph aside)"
        if state == 2:                                                 # E1 / E0 on the stripe law, never NN'd
            for y in range(s, n - s):
                if out[y][s] != 0x41:
                    assert out[y][s] == (0xE0 if SL.stripe_top(y, g) else 0xE1), (g, y)


@pytest.mark.parametrize("path", ("menu", "ingame"))
def test_law_filedlg_pair(path):
    ok0, ca0 = SL.FILEDLG_BTN_RECTS[path]
    assert (ok0[2] - ok0[0], ca0[2] - ca0[0], ca0[0] - ok0[2], ok0[3] - ok0[1]) == (146, 147, 3, 22)
    assert SL.filedlg_btn_pair(ok0, ca0, 16) == (ok0, ca0)
    for g in range(17, 41):
        ok, ca = SL.filedlg_btn_pair(ok0, ca0, g)
        assert ok[2] - ok[0] == ca[2] - ca[0], g                                        # one width
        assert (ok[0], ca[2]) == (SL.popup_scale_floor(ok0[0], g), SL.popup_scale_floor(ca0[2], g))
        assert ca[0] - ok[2] - SL.popup_scale_floor(3, g) in (0, 1), g                  # the odd px in the seam
        h = ok[3] - ok[1]
        assert h == SL.popup_scale_floor(22, g) and ca[1::2] == ok[1::2]
        assert SL.btn_native_dim(h, g) == 22, g                                         # the CEIL inverse is exact


def test_law_filedlg_v1_was_unequal_and_short():
    ok0, ca0 = SL.FILEDLG_BTN_RECTS["ingame"]
    v1 = [SL.popup_scale_floor(v, 25) for v in ok0 + ca0]
    assert (v1[2] - v1[0], v1[6] - v1[4], v1[3] - v1[1]) == (228, 230, 35)              # the user's shot 000837
    assert SL.btn_bar_tile_height(35, SL.btn_native_dim(35, 25), 20) == 30
    ok, ca = SL.filedlg_btn_pair(ok0, ca0, 25)
    assert (ok[2] - ok[0], ca[2] - ca[0], SL.btn_bar_tile_height(ok[3] - ok[1], 22, 20)) == (229, 229, 31)


def test_law_faction_row_face_shape():
    g, s = 25, SL.btn_corner_notch(25)
    bg = [[0xC6 if y % 4 < 2 else 0x41 for _ in range(40)] for y in range(30)]
    painted = [list(r) for r in bg]
    for y in range(2, 27):
        for x in range(3, 37):
            if not ((y in (2, 26)) and (x in (3, 36))):
                painted[y][x] = 0xE0 if y in (2, 26) or x in (3, 36) else (0xAE if y % 2 else 0xEE)
    out = SL.faction_row_face(bg, painted, (3, 2, 37, 27), g, (True,) * 4, (0xE0,) * 4)
    for (y0, x0) in ((2, 3), (2, 35), (25, 3), (25, 35)):
        assert all(out[y][x] == bg[y][x] for y in range(y0, y0 + s) for x in range(x0, x0 + s))
    assert out[14][3:3 + s] == [0xE0] * s and out[14][3 + s] != 0xE0
    assert out[2][3 + s:37 - s] == [0xE0] * (34 - 2 * s) and out[3][3 + s:37 - s] == [0xE0] * (34 - 2 * s)
    assert SL.faction_row_face(bg, painted, (3, 2, 37, 27), 16, (True,) * 4, (0xE0,) * 4) == painted


# ============================================================================== 2a. the lobby (default 9-slice)
@pytest.fixture(scope="module")
def lobby(baked_exe):
    import netwin_lobby_emu as NL
    return NL.Lobby(str(baked_exe))


@pytest.fixture(scope="module")
def lobby_cmp(baked_exe):
    """A second boot for the comparisons: image_emu's heap is a bump allocator and every build re-allocates the lobby's
    canvases, so one boot cannot carry every g sweep of the module (a 4K g-40 build is several MB)."""
    import netwin_lobby_emu as NL
    return NL.Lobby(str(baked_exe))


@pytest.fixture(scope="module")
def lobby22(baked_exe):
    import netwin_lobby_emu as NL
    return NL.Lobby(str(baked_exe))


@pytest.fixture(scope="module")
def lobby_before(baked_exe):
    """The bake with F39 reverted in memory: thunk_btn_2dscale's stretch call back on thunk_btn_bandstripe (the probe
    never runs, so t_btn_edgeband draws nothing after ringfix)."""
    import struct
    import netwin_lobby_emu as NL
    import apply_patches as ap
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = ap.build_symbol_table(symbols, caves)
    lb = NL.Lobby(str(baked_exe))
    two = sym["thunk_btn_2dscale"]
    code = bytes(lb.e.uc.mem_read(two, 0x70))
    probe = sym["t_btn_edgeprobe"]
    for i in range(len(code) - 4):
        if code[i] == 0xE8 and (two + i + 5 + struct.unpack("<i", code[i + 1:i + 5])[0]) & 0xFFFFFFFF == probe:
            lb.patch(two + i + 1, struct.pack("<i", sym["thunk_btn_bandstripe"] - (two + i + 5)))
            break
    else:
        raise AssertionError("2dscale's call to t_btn_edgeprobe")
    return lb


def _runs(p, rowcol):
    """(left, right) runs of outline colours along a row (or (top, bottom) along a column)."""
    v = list(rowcol)
    a = 0
    while a < len(v) and v[a] in OUTLINE:
        a += 1
    b = 0
    while b < len(v) and v[-1 - b] in OUTLINE:
        b += 1
    return a, b


def _band_profile(p):
    import netwin_lobby_emu as NL
    rows = NL.face_rows(p)
    d = rows[-1] + 1
    H, W = p.shape
    ym, xm = d // 2, W // 6
    return _runs(p, p[ym]) + _runs(p, p[:d, xm]), d


@pytest.mark.parametrize("g", range(16, 41))
def test_e2e_lobby_hover_outline_is_k_on_every_side(lobby, g):
    import netwin_lobby_emu as NL
    k, s = SL.btn_edge_stroke(g), SL.btn_corner_notch(g)
    lobby.build(g)
    for obj in NL.LAUNCH, NL.CANCEL:
        p = lobby.draw(obj, 1)
        (l, r, t, b), d = _band_profile(p)
        assert (l, r, t, b) == (k, k, k, k), (g, hex(obj), (l, r, t, b))
        if g > 16:                                                    # SOLID E0 (not the E0 / E1 restripe)
            band = np.concatenate([p[:k, s:-s].ravel(), p[d - k:d, s:-s].ravel(), p[s:d - s, :k].ravel(),
                                   p[s:d - s, -k:].ravel()])
            assert set(band.tolist()) == {0xE0}, (g, set(band.tolist()))
        assert NL.corner_notches(p) == [(s, s)] * 4, (g, NL.corner_notches(p))


@pytest.mark.parametrize("g", (17, 22, 24, 25, 30, 33, 40))
def test_e2e_lobby_only_the_hover_band_changes(lobby_cmp, lobby_before, g):
    """States 0 / 2 byte-identical to the F39-reverted bake; state 1 differs only inside the K band."""
    import netwin_lobby_emu as NL
    k = SL.btn_edge_stroke(g)
    lobby_cmp.build(g)
    lobby_before.build(g)
    for st in (0, 2):
        assert np.array_equal(lobby_cmp.draw(NL.LAUNCH, st), lobby_before.draw(NL.LAUNCH, st)), (g, st)
    a, b = lobby_cmp.draw(NL.LAUNCH, 1), lobby_before.draw(NL.LAUNCH, 1)
    d = NL.face_rows(a)[-1] + 1
    inner = (slice(k, d - k), slice(k, a.shape[1] - k))
    assert np.array_equal(a[inner], b[inner]) and np.array_equal(a[d:], b[d:]), g


@pytest.mark.parametrize("g", (17, 19, 22, 25, 30, 33, 40))
def test_e2e_22_native_band_sits_on_the_art_bottom(lobby22, g):
    """The 22-native class (the faction picker's text buttons, Load / Save OK / CANCEL): the 20-row art stops at
    D = btn_bar_tile_height, so the bottom band is rows [D - K, D) and the key gap below stays key."""
    import struct
    import apply_patches as ap
    import netwin_lobby_emu as NL
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    pin = ap.build_symbol_table(symbols, caves)["t_btn_nath_pin"]
    code = bytes(lobby22.e.uc.mem_read(pin, 0x70))
    i = code.index(b"\x81\xFE" + struct.pack("<I", NL.LAUNCH))
    lobby22.patch(pin + i + 2, struct.pack("<I", 0xFFFFFFF0))          # unpin LAUNCH: the 22-native class
    try:
        wins = lobby22.build(g, native_h=22)
        h = wins[NL.LAUNCH][3]
        d = SL.btn_bar_tile_height(h, SL.btn_native_dim(h, g), 20)
        k = SL.btn_edge_stroke(g)
        p = lobby22.draw(NL.LAUNCH, 1)
        assert NL.face_rows(p)[-1] == d - 1 and (p[d:] == KEY).all(), g
        assert _band_profile(p)[0] == (k, k, k, k), (g, _band_profile(p))
        xm = p.shape[1] // 2
        assert (p[d - k:d, xm] == 0xE0).all() and p[d - k - 1, xm] != 0xE0, g
    finally:
        lobby22.patch(pin + i + 2, struct.pack("<I", NL.LAUNCH))


@pytest.mark.parametrize("g, want", ((24, (1, 2, 1, 2)), (40, (2, 3, 2, 3)), (22, (1, 1, 1, 1)), (25, (2, 2, 2, 2))))
def test_e2e_reverted_bake_reproduces_the_shots(lobby_before, g, want):
    """The deployed outline (left, right, top, bottom): 4K 1 | 2 at g 24, 2 | 3 at g 40 (shots 000608 / 000611)."""
    import netwin_lobby_emu as NL
    lobby_before.build(g)
    assert _band_profile(lobby_before.draw(NL.LAUNCH, 1))[0] == want


@pytest.fixture(scope="module")
def lobby_gdi(baked_exe):
    import host_gdi_stretch as HG
    if not HG.available():
        pytest.skip("host GDI needs Windows")
    import netwin_lobby_emu as NL
    lb = NL.Lobby(str(baked_exe))
    HG.install(lb.e)
    return lb


@pytest.mark.parametrize("g", (17, 18, 20, 22, 24, 25, 27, 33, 40))
def test_e2e_lobby_host_gdi(lobby_gdi, g):
    """The same faces with the REAL host gdi32 StretchBlt doing the zoom (measure the engine, do not model it)."""
    import netwin_lobby_emu as NL
    k, s = SL.btn_edge_stroke(g), SL.btn_corner_notch(g)
    lobby_gdi.build(g)
    for st in (0, 1, 2):
        p = lobby_gdi.draw(NL.LAUNCH, st)
        assert NL.corner_notches(p) == [(s, s)] * 4, (g, st)
        if st == 1:
            assert _band_profile(p)[0] == (k, k, k, k), (g, _band_profile(p))


# ============================================================================== 2b. the faction picker
PICK_G = (16, 17, 22, 25, 40)


@pytest.fixture(scope="module")
def picker(baked_exe):
    import faction_picker_emu as FP
    return FP.Picker(str(baked_exe))


@pytest.fixture(scope="module")
def picker_pristine(bak_path):
    import faction_picker_emu as FP
    pk = FP.Picker(str(bak_path), 1024, 768)
    pk.build(16)
    return pk


@pytest.mark.parametrize("g", PICK_G)
def test_e2e_drop_arrows(picker, picker_pristine, g):
    picker.build(g)
    s = k = SL.btn_corner_notch(g)
    for st in (0, 1, 2):
        art = picker.drop_art(0, st)
        p = picker.draw_drop(0, st)
        if g <= 16:
            assert np.array_equal(p, picker_pristine.draw_drop(0, st)), st          # the vanilla blit
            continue
        n = p.shape[0]
        assert [list(r) for r in p] == SL.drop_arrow_render(art, p.shape[1], n, g), (g, st)
        for (y0, x0) in ((0, 0), (0, n - s), (n - s, 0), (n - s, n - s)):
            assert (p[y0:y0 + s, x0:x0 + s] == KEY).all(), (g, st, y0, x0)
        assert p[s, 0] != KEY and p[0, s] != KEY and p[n - 1 - s, n - 1] != KEY, "exactly s x s"
        if st == 1:
            mid = n // 2
            assert (p[mid, :k] == 0xE0).all() and (p[mid, n - k:] == 0xE0).all(), g
            assert (p[:k, mid] == 0xE0).all() and (p[n - k:, mid] == 0xE0).all(), g
        assert art == picker_pristine.drop_art(0, st), "the art the law reads is vanilla's"


@pytest.mark.parametrize("g", PICK_G)
def test_e2e_name_rows(picker, picker_pristine, g):
    picker.build(g)
    rects = picker.row_rects()
    s = k = SL.btn_corner_notch(g)
    for item, hover in ((0, -1), (0, 0), (3, -1), (5, 5)):                   # idle, hovered, selected, idle
        c = picker.draw_row(item, hover)
        if g <= 16:
            assert np.array_equal(c, picker_pristine.draw_row(item, hover)), (item, hover)
            continue
        L, T, R, B = rects[item]
        row = c[T:B, L:R]
        for (y0, x0) in ((0, 0), (0, R - L - s), (B - T - s, 0), (B - T - s, R - L - s)):
            sq = set(row[y0:y0 + s, x0:x0 + s].ravel().tolist())
            assert sq <= {0xC6, 0x41}, (g, item, hover, sq)                      # an s x s notch of background
        assert row[s, 0] not in (0xC6, 0x41) and row[0, s] not in (0xC6, 0x41), "exactly s x s"
        if hover == item:
            mid = (B - T) // 2
            assert (row[mid, :k] == 0xE0).all() and (row[mid, -k:] == 0xE0).all() and row[mid, k] != 0xE0
            xm = (R - L) // 2
            assert (row[:k, xm] == 0xE0).all() and (row[-k:, xm] == 0xE0).all() and row[k, xm] != 0xE0


@pytest.mark.parametrize("g", (22, 25, 40))
def test_e2e_name_row_text_lands_on_the_bands(picker, g):
    """Audit condition 2: vanilla draws the 1-px stroke first and the row's text on top; the K bands must not overwrite
    text ink (descenders reach the bottom band at 1080p: rows 22 px, K = 2).  The emulated TextOutA draws nothing, so
    ink is synthesized where draw_item writes its text -- right after the painter returns (@0x60BB5B) -- inside every
    band, and must come out as drawn while the rest of each band is the solid stroke."""
    from unicorn import UC_HOOK_CODE
    import faction_picker_emu as FP
    picker.build(g)
    rects = picker.row_rects()
    k = SL.btn_edge_stroke(g)
    item = 0                                        # unselected (the build selects list id 3 = index 2): hover = state 1
    L, T, R, B = rects[item]
    ink = {(T, L + 3 * k): 0xFF, (T + k - 1, (L + R) // 2): 0x8A, (B - 1, L + 5 * k): 0xFF,
           (B - k, (L + R) // 2 + 7): 0x10, ((T + B) // 2, L): 0x8A, ((T + B) // 2 + 1, R - 1): 0xFF}
    e = picker.e

    def text(uc, _a, _s, _u):
        bits, st = e.r32(FP.LIST_WIN + 0x498), (e.s32(FP.LIST_WIN + 0x444 + 0x38) + 3) & ~3
        for (y, x), v in ink.items():
            uc.mem_write(bits + y * st + x, bytes([v]))
    h = e.uc.hook_add(UC_HOOK_CODE, text, begin=0x60BB5B, end=0x60BB5B)
    try:
        c = picker.draw_row(item, item)
    finally:
        e.uc.hook_del(h)
    for (y, x), v in ink.items():
        assert c[y, x] == v, (g, y, x, c[y, x])
    row = c[T:B, L:R]
    mid = (B - T) // 2
    band = [row[:k, 4 * k:-4 * k], row[-k:, 4 * k:-4 * k], row[k:mid - 1, :k], row[mid + 2:-k, -k:]]
    for b in band:
        vals = set(b.ravel().tolist()) - set(ink.values())
        assert vals == {0xE0}, (g, vals)


# ============================================================================== 2c. Load / Save OK | CANCEL
FD_G = (16, 17, 21, 22, 25, 29, 30, 40)


@pytest.fixture(scope="module")
def filedlg(baked_exe):
    import apply_patches as ap
    import filedlg_emu as FE
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    blit = ap.build_symbol_table(symbols, caves)["thunk_bilinear_blit"]
    return FE.FileDlgEmu(str(baked_exe), skip_draws=((blit, 0x2C),))      # icon / art pixels only: the rects are layout


@pytest.fixture(scope="module")
def filedlg_pristine(bak_path):
    import filedlg_emu as FE
    return FE.FileDlgEmu(str(bak_path), 1024, 768)


@pytest.mark.parametrize("g", FD_G)
def test_e2e_filedlg_pair(filedlg, filedlg_pristine, g):
    for path in ("menu", "ingame"):
        rects, objs = filedlg.layout(g, path == "ingame")
        want = SL.filedlg_btn_pair(*SL.FILEDLG_BTN_RECTS[path], g)
        assert (rects["OK"], rects["CANCEL"]) == want, (g, path, rects)
        e = filedlg.e
        for nm, r in rects.items():                                    # the button canvases follow the windows
            o = objs[nm]
            assert (e.s32(o + 0x4C4), -e.s32(o + 0x4C8)) == (r[2] - r[0], r[3] - r[1]), (g, nm)
        if g <= 16:
            assert filedlg_pristine.layout(16, path == "ingame")[0] == rects, path
