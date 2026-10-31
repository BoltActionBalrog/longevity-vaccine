"""The Planetary Council layout mirrored about its slide rails (2026-10-25 wave-5 W5B; v2 after audit-w5B).

The council SLIDES (thunk_popup_railshow arms railscale for it), so its side rails are the generic 15 / 8 x 529 strips at
railscale's cascades: left [0, rail_left_extent), right inner strip at rail_right_strip_x(W, W - 0x37) -- a mirror pair
with half-open mirror sum S1 = council_rail_mirror_sum.  The deployed layout (c8374772 .. 0283cc29) put the backdrop R
at W - dp(0x37), 1 (4K) .. 3 px right of the inner right rail, and drew every frame (backdrop d690, d5a0 ring, column
d528s, vote chips) INCLUSIVE of R / B: everything was mirrored about a centre 1 px right of the rails' at 4K (1.5 at
1080 / 1440), the right border hid under the rail (4K shot 20261024-233251: R = 1893, rail at 1892), and a repaint after
the slide (a vote) painted it OVER the rail (1080 shot 20261024-233654: border on 1465, the rail starts at 1463).
Now (laws council_rail_mirror_sum / council_backdrop_rect v2 / council_ring_rect / council_channel_weights /
council_mirror_cols / council_column_rects / council_drawn / council_layout_channels): the backdrop's L / R are the
rails' inner edges, the ring is it inset dp(4), the centre column is centred, columns 0..2 sit on ONE weighted run from
the ring's inner edge to the centre column (the vanilla channels as weights through cum(): the rails' 0..4 px shortfall
spread over ring -> col and the three gaps, not dumped into the centre gaps as v1 did), columns 4..6 are their mirrors
(both sets), every frame is drawn half-open -- borders K | K, every channel L | R, each within 1.38 px of vanilla x g/16.

Proof layers:
  1. the laws, g 16..64 (pairs mirrored, vanilla identity at 16, the weighted run's channel errors and the v1 mutant's);
  2. END TO END on the real image (council_mirror_emu.py on image_emu.py): the real MainWin_build, CouncilWin_exec
     through the E8 @0x427784 chain, the show -- the repaint and slide_show's settled rails, in that order -- and, on
     two screens, the post-slide phase (CouncilWin_vote_result + a full repaint with every chip kind).  Every frame
     draw's footprint == the law, none touches a rail column (the rails' columns are unchanged by the vote phase), the
     rails sit where the law says, the channels measured on the canvas are equal pairs and == council_layout_channels;
     g = 16 is the pristine image's draw pixel for pixel; the deployed build draws the user's 1080 shots (233652 shown,
     233654 after a vote: the border over the rail) -- the stroke columns pinned, re-read from the PNGs when present
     (the 4K 233251 / 1440 125645 pins are data, measured by the same harness).
     (Unit parity: test_council_mirror_asm_parity.py.)
  W7B (2026-10-25 wave-7; council_backdrop_rect v3: B = H + K): the backdrop's / ring's bottom strokes are CLIPPED
  below the canvas as vanilla's are (the last K canvas rows: the backdrop's side strokes and the ring's chamfer rows,
  K in -- vanilla x g/16 of 1024's row 394; the band-map renderers had clamped the frames onto those rows), and the
  faction logo is centred in the column interior (council_logo_x: L | R equal, an odd px on the right) -- both measured
  on every e2e screen, and on the pristine 1024 as the vanilla identity.
  The "before" image is the shared bake with the W5B bytes undone in memory: the nine sites back on their old targets,
  thunk_cw_seeds' tail back on `jmp Font_init`, and every byte of the W5B region zeroed (the region holds only W5B
  symbols -- asserted).  Measured 2026-10-25 against a real bake of 73c42bb (0283cc29): every section is then
  byte-identical, pcave2 up to its 0x4000-byte zero growth -- so it IS the deployed council, not a model of it.

COST: one boot per image per worker (~3 s); each screen item builds MainWin and runs the exec + show for real.  Items
are per screen so xdist splits the module by measured cost.  The price is the engine's call order -- the defect lives
in the order (the rails drawn after the repaint, a later repaint over them, the repaint's rect feeding the ring) and in
the column / chip arithmetic of the real painters.  W7B (2026-10-25) cut it from ~240 s serial (the heaviest module in
the repo; 1600x1200 + votes alone ~70 s) to ~50 s (the slowest item ~10 s) with nothing dropped: the rig's emulation
budget is wall clock (council_mirror_emu.BUDGET_US), not unicorn's instruction `count`, which instruments every
instruction (~10x: the 1080 show 14.7 s -> 1.5 s, canvas and every draw record identical).
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

LAW_G = range(16, 65)
#: (screen, governor (-1: the flat inner set; 4: the governor set), run the post-slide vote phase).  64g x 48g at g = 17
#: (K = 1; the deployed backdrop L was 1 px right of the rails; the governor set's centre column parity +1), the user's
#: three resolutions (inner set), the governor set at 1600x1200 (K = 2 from g = 25) with the vote / banner phase.
E2E = [((1088, 816), 4, False), ((1920, 1080), -1, False), ((2560, 1440), -1, False), ((3840, 2160), -1, False),
       ((1600, 1200), 4, True)]   # the vote / banner phase at g = 25: K = 2, so W6B's inset, chip pad and portrait move
#: the user's council shots under the deployed build: (governor, phase, the stroke row on screen, window x, the green
#: stroke runs on that row in screen x left of col0's interior, and right of col6's up to the inner right rail's end:
#: border B, ring R, column C).  Measured on the PNGs (pinned; the cross-check re-reads them when present) == the
#: deployed build's real-image draw.
SHOTS = {
    "3840x2160_20261024-233251": (-1, "show", 1412, 945,
                                  [(1002, 1003, "B"), (1012, 1013, "R"), (1025, 1026, "C")],
                                  [(2814, 2815, "C"), (2827, 2828, "R")]),
    "1920x1080_20261024-233652": (-1, "show", 668, 424,
                                  [(455, 455, "B"), (460, 460, "R"), (468, 468, "C")],
                                  [(1451, 1451, "C"), (1460, 1460, "R")]),
    "1920x1080_20261024-233654": (4, "votes", 701, 424,
                                  [(455, 455, "B"), (460, 460, "R"), (465, 465, "C")],
                                  [(1454, 1454, "C"), (1460, 1460, "R"), (1465, 1465, "B")]),
    "2560x1440_20261024-125645": (-1, "show", 879, 549,
                                  [(592, 593, "B"), (599, 600, "R"), (609, 610, "C")],
                                  [(1949, 1950, "C"), (1960, 1961, "R")]),
}
#: replayed every run: the 1080 pair (shown / after a vote); the 4K and 1440 pins are data (another ~45 s serial)
SHOTS_RUN = ("1920x1080_20261024-233652", "1920x1080_20261024-233654")
SHOT_DIR = ROOT / "screenshots"
STROKE_RGB = {(73, 108, 61): "B", (49, 78, 44): "R", (35, 59, 34): "C"}
STROKE_IDX = {26: "B", 31: "R", 34: "C"}            # the same three colours on the 8-bit canvas
SETS = (("inner", SL.COUNCIL_INNER_L), ("outer", SL.COUNCIL_OUTER_L))


# ============================================================================== 1. laws
@pytest.mark.parametrize("g", LAW_G)
def test_law_layout_mirrored_about_the_rails(g):
    W = SL.dp(SL.COUNCIL_W, g)
    s1 = SL.council_rail_mirror_sum(W, g)
    E = SL.rail_left_extent(g) if g > 16 else 23
    xri = SL.rail_right_strip_x(W, W - 0x37, g) if g > 16 else W - 0x37
    assert s1 == E + xri, "the rails' half-open mirror sum"
    K = SL.stroke_width(g) if g > 16 else 1
    assert SL.council_backdrop_rect(W, 395, g) == (E, 0, xri, 395 + K), "the backdrop's edges are the rails' inner edges"
    assert SL.council_frame_clip(SL.council_backdrop_rect(W, 395, g), 395)[3] == 395, "its bottom stroke below (W7B)"
    ring = SL.council_ring_rect(W, 395, g)
    assert ring[0] + ring[2] == s1
    cols = SL.council_column_rects(g)
    for k, w_c, w3 in (("inner", SL.COUNCIL_COL_W, SL.COUNCIL_COL_W), ("outer", SL.COUNCIL_COL_W, SL.COUNCIL_CENTER_COL_W)):
        c = cols[k]
        assert all(c[i][0] + c[6 - i][2] == s1 for i in range(7)), (g, k)
        assert all(c[i][1] == c[6 - i][1] and c[i][3] == c[6 - i][3] for i in range(7))
        assert all(c[i][2] - c[i][0] == SL.dp(w_c, g) for i in (0, 1, 2, 4, 5, 6)), "the six side columns one width"
        exact = w3 * g / 16
        assert abs((c[3][2] - c[3][0]) - exact) < 1.0 + 1e-9 if g > 16 else c[3][2] - c[3][0] == w3
        assert 2 * c[3][0] + (c[3][2] - c[3][0]) == s1, "the centre column centred between the rails"
        assert all(c[i][2] <= c[i + 1][0] for i in range(6)), "columns never butt"
    if g == 16:
        assert {k: cols[k] for k in ("outer", "inner")} == {k: SL.council_seed_rects(16)[k] for k in ("outer", "inner")}
        assert s1 == 780, "vanilla is mirrored already: 30 + 749 = 779"


def _run_channels(cols, start):
    return [cols[0][0] - start] + [cols[i + 1][0] - cols[i][2] for i in range(3)]


def _v1_cols(g, key):
    """v1 (the audited W5B): columns 0..2 on their dp() seeds, the centre centred, 4..6 mirrored -- the rails' shortfall
    all in the two centre gaps."""
    s = SL.council_seed_rects(g)[key]
    new = SL.council_column_rects(g)[key]
    return list(s[:3]) + [new[3]]


@pytest.mark.parametrize("g", range(17, 65))
def test_law_weighted_run(g):
    """The left half's run from the ring's inner edge to the centre column: four channels in the vanilla proportions
    (inner 4:5:5:5, governor set 2:2:2:2) through cum() -- every channel within 1.31 / 1.38 px of vanilla x g/16 for
    g 17..64 (v1: 2.25 / 2.38), the budget never negative, columns 0..2 within 2 px of their dp() seeds (3 above the
    game's g clamp of 40)."""
    c = SL.council_column_rects(g)
    start = c["start"]
    assert start == SL.council_ring_rect(SL.dp(SL.COUNCIL_W, g), 0, g)[0] + SL.stroke_width(g), "the ring's inner edge"
    for key, left in SETS:
        w = SL.council_channel_weights(left)
        cols = c[key]
        ch = _run_channels(cols, start)
        budget = cols[3][0] - start - 3 * SL.dp(SL.COUNCIL_COL_W, g)
        assert budget >= 0 and sum(ch) == budget
        acc = 0
        for i in range(4):
            acc += w[i]
            assert sum(ch[:i + 1]) == SL.cum(acc, budget, sum(w)), "the weighted remainder law (cum)"
        err = max(abs(a - b * g / 16) for a, b in zip(ch, w))
        assert err <= {"inner": 1.3125, "outer": 1.375}[key] + 1e-9, (g, key, ch)
        seeds = SL.council_seed_rects(g)[key]
        move = 2 if g <= SL.G_MAX else 3                    # g is clamped to 40 in the game; 3 at g = 51 (governor)
        assert all(abs(cols[i][0] - seeds[i][0]) <= move for i in range(3)), (g, key)


def test_law_weighted_run_beats_v1():
    """The audit's numbers: the worst channel error over g 17..40, v1 -> v2: governor set 2.12 -> 1.38, inner 2.25 ->
    1.31; v1's governor-set gaps at 1080 [3, 4, 2, 2, 4, 3] (vanilla x g/16: 2.75 each), 4K [5, 5, 4, 4, 5, 5] with
    ring -> col 6."""
    worst = {}
    for key, left in SETS:
        w = SL.council_channel_weights(left)
        for g in range(17, 41):
            start = SL.council_column_rects(g)["start"]
            for tag, cols in (("v1", _v1_cols(g, key)), ("v2", SL.council_column_rects(g)[key])):
                e = max(abs(a - b * g / 16) for a, b in zip(_run_channels(cols, start), w))
                worst[(key, tag)] = max(worst.get((key, tag), 0), e)
    assert round(worst[("outer", "v1")], 2) == 2.12 and round(worst[("outer", "v2")], 2) == 1.38
    assert round(worst[("inner", "v1")], 2) == 2.25 and round(worst[("inner", "v2")], 2) == 1.31
    assert _run_channels(_v1_cols(22, "outer"), SL.council_column_rects(22)["start"]) == [4, 3, 4, 2]   # ring->col, gaps
    assert _run_channels(SL.council_column_rects(22)["outer"], SL.council_column_rects(22)["start"]) == [3, 3, 4, 3]


@pytest.mark.parametrize("g", LAW_G)
def test_law_channels_are_pairs(g):
    for inner in (True, False):
        ch = SL.council_layout_channels(g, inner)
        for key in ("border", "border_ring", "ring_col"):
            a, b = ch[key]
            assert a == b and a > 0, (g, key, ch[key])
        assert all(a == b and a >= 0 for a, b in ch["gaps"]), ch["gaps"]
        assert all(a == b for a, b in ch["col_chip"]) and all(a == b for a, b in ch["chip_mirror"])
    if g == 16:
        ch = SL.council_layout_channels(16)
        assert (ch["border"], ch["border_ring"], ch["ring_col"]) == ((1, 1), (3, 3), (4, 4)), "vanilla 1024"


@pytest.mark.parametrize("g", LAW_G)
def _kinds(g):
    """{kind: column rect} of every distinct column width: the side columns, the inner centre (W5B's parity +1 at some
    g), the governor's (120)."""
    out = {}
    for key in ("inner", "outer"):
        for i, c in enumerate(SL.council_column_rects(g)[key]):
            kind = "gov" if (key == "outer" and i == 3) else ("centre" if i == 3 else "side")
            out.setdefault(kind, c)
    return out


@pytest.mark.parametrize("g", LAW_G)
def test_law_w6b_column_interior(g):
    """W6B v2: the column painter's inset is the stroke width (vanilla: 1 = the stroke); the portrait centred in the
    interior (gaps L | R equal, an odd px on the right: |L - R| <= 1, 0 | 0 at g = 16); the chip's L = R = B inset
    council_chip_pad -- within 0.75 px of 4g/16 -- and its width within 1 px of its own vanilla x g/16 (90 / 112) in
    every column kind; t_cw_chipfix's delta composes the painter's block into the law; mirrored columns, mirrored chips."""
    fi = SL.council_frame_inset(g)
    assert fi == (SL.stroke_width(g) if g > 16 else 1)
    for kind, col in _kinds(g).items():
        w = col[2] - col[0]
        vw = SL.council_column_vanilla_w(w, g)
        assert vw == (120 if kind == "gov" else 98)
        sw = 118 if kind == "gov" else 96
        gl, gr = SL.council_portrait_gaps(w, sw, g)
        assert gr - gl in (0, 1) or (gl == 0 and gr == -1), (g, kind, gl, gr)
        assert SL.council_portrait_xy(col, g) == (col[0] + fi + gl, col[1] + fi)
        if g == 16:
            assert (gl, gr) == (0, 0)
        chip = SL.council_chip_rects(col, g)["chip"]
        p = chip[0] - col[0]
        assert (col[2] - chip[2], col[3] - chip[3]) == (p, p), "L = R = B"
        assert abs(p - 4 * g / 16) <= 0.75 + 1e-9 and abs((chip[2] - chip[0]) - (vw - 8) * g / 16) <= 1 + 1e-9, \
            (g, kind, p, chip[2] - chip[0])
        assert chip[3] - chip[1] == SL.dp(0x17, g) - SL.dp(3, g)
        if g > 16:
            d = SL.council_chip_fix_delta(w, g)
            assert chip[0] == col[0] + fi + SL.dp(3, g) + d and chip[3] == col[3] - fi - SL.dp(3, g) - d
    for key in ("inner", "outer"):
        cols = SL.council_column_rects(g)[key]
        chips = [SL.council_chip_rects(c, g)["chip"] for c in cols]
        assert all(chips[i][0] + chips[6 - i][2] == cols[i][0] + cols[6 - i][2] for i in range(7)), "mirrored"


@pytest.mark.parametrize("g", LAW_G)
def test_law_w7b_logo_centred(g):
    """W7B (council_logo_x): the real 86-wide logo canvas centred in every column's interior, both sets -- the slack
    split, an odd px on the right (the portrait's rule); vanilla 5 | 5 (16 | 16 the governor set's centre column).
    The deployed two-floor recentre (thunk_cw_logo alone) was up to 2 px off: 4K 12 | 14, g = 24 7 | 9."""
    fi = SL.council_frame_inset(g)
    for key in ("inner", "outer"):
        cols = SL.council_column_rects(g)[key] if g > 16 else SL.council_seed_rects(16)[key]
        for col in cols:
            x = SL.council_logo_x(col[0], col[2], 86, g)
            gl, gr = x - (col[0] + fi), (col[2] - fi) - (x + SL.dp(86, g))
            assert gr - gl in (0, 1) and gl >= 0, (g, key, col, gl, gr)
            if g == 16:
                assert (gl, gr) in ((5, 5), (16, 16))
    W = SL.dp(SL.COUNCIL_W, 40)
    assert SL.council_frame_clip(SL.council_ring_rect(W, 987, 40), 987) == (67, 10, 1882, 987)


def test_law_screen_numbers():
    """4K: the rails end at 56 / start at 1892 (canvas); the deployed backdrop R 1893 hid the right border, the law's
    [57, 1892) draws it on 1890..1891; ring [67, 1882); both B = 987 + K (W7B: the 2-row bottom stroke below the
    canvas).  Inner set ring -> col 10, gaps 13 / 12 / 13 (vanilla x 2.5: 10, 12.5); the governor set exact: ring ->
    col and every gap 5.  1440 governor set all 4, 1600x1200 all 3."""
    W = SL.dp(SL.COUNCIL_W, 40)
    assert W == 2030 and SL.council_backdrop_rect_v1(W, 987, 40)[2] == 1893
    assert SL.council_backdrop_rect(W, 987, 40) == (57, 0, 1892, 989)
    assert SL.council_ring_rect(W, 987, 40) == (67, 10, 1882, 989)
    ch = SL.council_layout_channels(40)
    assert (ch["border"], ch["border_ring"], ch["ring_col"]) == ((2, 2), (8, 8), (10, 10))
    assert [a for a, _b in ch["gaps"]] == [13, 12, 13]
    for g, v in ((40, 5), (30, 4), (25, 3)):
        o = SL.council_layout_channels(g, False)
        assert o["ring_col"] == (v, v) and [a for a, _b in o["gaps"]] == [v, v, v], g


# ============================================================================== 2. end to end
@pytest.fixture(scope="module")
def sym():
    import mirror_pairs_emu as MPE
    return MPE.symtab()


@pytest.fixture(scope="module")
def images(tmp_path_factory, bak_path, sym, baked_exe):
    """{'new': the shared bake, 'before': the bake with the W5B bytes undone (module docstring: == the deployed bake
    section for section), 'pristine': the .bak}."""
    import shutil
    import assemble_council_mirror as CM
    d = tmp_path_factory.mktemp("council_mirror")
    data = bytearray(Path(baked_exe).read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)

    def off(va):
        return pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    for _sid, va, _helper, was in CM.SITES:
        assert data[off(va)] == 0xE8
        data[off(va) + 1:off(va) + 5] = struct.pack("<i", sym[was] - (va + 5))
    for _sid, va, orig, _new, _note in CM.W6_BLOCKS:                     # W6B's two block sites, back to vanilla
        o = bytes.fromhex(orig.replace(" ", ""))
        data[off(va):off(va) + len(o)] = o
    push = b"\x68" + struct.pack("<I", sym["t_cw_mirror"]) + b"\xC3"
    s0 = off(sym["thunk_cw_seeds"])
    k = bytes(data[s0:s0 + 0x200]).index(push)
    data[s0 + k:s0 + k + 6] = b"\xE9" + struct.pack("<i", 0x618F40 - (sym["thunk_cw_seeds"] + k + 5)) + b"\x00"
    lo, hi = CM.PCAVE2 + CM.REGION[0], CM.PCAVE2 + CM.REGION[1]
    owners = {n for n, v in sym.items() if lo <= v < hi}
    assert owners == set(CM.HELPERS) | set(CM.DATA), owners
    data[off(lo):off(hi)] = bytes(hi - lo)
    (d / "before.exe").write_bytes(bytes(data))
    shutil.copy2(bak_path, d / "pristine.exe")
    return {"new": str(baked_exe), "before": str(d / "before.exe"), "pristine": str(d / "pristine.exe")}


@pytest.fixture(scope="module")
def rig_new(images, sym):
    import council_mirror_emu as CME
    return CME.Rig(images["new"], sym)


@pytest.fixture(scope="module")
def rig_before(images, sym):
    import council_mirror_emu as CME
    return CME.Rig(images["before"], sym)


@pytest.fixture(scope="module")
def rig_pristine(images, sym):
    import council_mirror_emu as CME
    return CME.Rig(images["pristine"], sym)


def _draws(c, kind):
    return [r for r in c["rec"] if r["kind"] == kind]


def _run_at(p, y, x):
    row = p[y]
    v = row[x]
    a = x
    while a > 0 and row[a - 1] == v:
        a -= 1
    b = x
    while b + 1 < len(row) and row[b + 1] == v:
        b += 1
    return a, b


def _measure(c):
    """The drawn footprints and the channels on the stroke row (2 rows below col0's chip: inside the outer columns,
    below every content draw)."""
    p, W, H = c["p"], c["W"], c["H"]
    bd = _draws(c, "backdrop")[0]["bbox"]
    rg = _draws(c, "ring")[0]["bbox"]
    cols = sorted(r["bbox"] for r in _draws(c, "column"))
    chips = sorted(r["bbox"] for r in _draws(c, "chip"))
    y = chips[0][3] + 2                                    # col0's (the outer set's centre column runs deeper)
    bl, br = _run_at(p, y, bd[0]), _run_at(p, y, bd[2])
    rl, rr = _run_at(p, y, rg[0]), _run_at(p, y, rg[2])
    cl, cr = _run_at(p, y, cols[0][0]), _run_at(p, y, cols[6][2])
    return {"bd": bd, "rg": rg, "cols": cols, "chips": chips, "y": y,
            "rails": {r["kind"]: r["bbox"] for r in c["rec"] if r["kind"].endswith(("_left", "_right")) and r["bbox"]},
            "border": (bl[1] - bl[0] + 1, br[1] - br[0] + 1),
            "border_ring": (rl[0] - bl[1] - 1, br[0] - rr[1] - 1),
            "ring": (rl[1] - rl[0] + 1, rr[1] - rr[0] + 1),
            "ring_col": (cl[0] - rl[1] - 1, rr[0] - cr[1] - 1),
            "colK": (cl[1] - cl[0] + 1, cr[1] - cr[0] + 1)}


def _rails(g, W):
    E = SL.rail_left_extent(g) if g > 16 else 23
    xri = SL.rail_right_strip_x(W, W - 0x37, g) if g > 16 else W - 0x37
    return E, xri


def _check_draws(rec, g, W, H, inner, first=True):
    """Every council frame draw of `rec` is off the rail columns and on the law: on the first paint of a clean canvas
    (`first`) its changed pixels' bbox IS the law's half-open footprint; on a repaint over itself the changed pixels
    are a subset, so the rect the painter passed must be the law's (columns / chips; the ring's L / T / R) and the
    changed pixels must lie inside the footprint."""
    law = SL.council_column_rects(g)["inner" if inner else "outer"]
    clip = lambda r: (r[0], r[1], r[2], min(r[3], H - 1))   # noqa: E731
    rects = {"column": set(law), "chip": {SL.council_chip_rects(r, g)["chip"] for r in law}}
    want = {"backdrop": {clip(SL.council_drawn(SL.council_backdrop_rect(W, H, g), g))},
            "ring": {clip(SL.council_drawn(SL.council_ring_rect(W, H, g), g))},
            "column": {SL.council_drawn(r, g) for r in law},
            "chip": {SL.council_drawn(SL.council_chip_rects(r, g)["chip"], g) for r in law}}
    E, xri = _rails(g, W)
    ring = SL.council_ring_rect(W, H, g)
    for r in rec:
        if r["kind"] not in want or not r["bbox"]:
            continue
        b = r["bbox"]
        assert E <= b[0] and b[2] < xri, ("a council draw on a rail column", r)
        if first:
            assert b in want[r["kind"]], (g, r)
            continue
        if r["kind"] in rects:
            assert r["rect"] in rects[r["kind"]], (g, r)
            fps = [clip(SL.council_drawn(r["rect"], g))]
        elif r["kind"] == "ring":
            assert r["rect"][:3] == ring[:3], (g, r)
            fps = want["ring"]
        else:
            fps = want["backdrop"]
        assert any(f[0] <= b[0] and f[1] <= b[1] and b[2] <= f[2] and b[3] <= f[3] for f in fps), (g, r)


def _bottom_errors(c, p=None):
    """W7B (law council_frame_clip): the canvas's last 2K rows under the backdrop.  The last K rows hold the backdrop's
    side strokes [L, L+K) / [R-K, R) and the ring's chamfer rows (its side strokes K in), no bottom stroke; the K rows
    above them the ring's plain side strokes -- vanilla's 1024 rows 393 / 394, x g/16.  Returns the rows that differ."""
    p = c["p"] if p is None else p
    W, H, g = c["W"], c["H"], c["g"]
    K = SL.stroke_width(g) if g > 16 else 1
    bL, _t, bR, _b = SL.council_backdrop_rect(W, H, g)
    rL, _t, rR, _b = SL.council_ring_rect(W, H, g)
    errs = []
    for y in range(H - 2 * K, H):
        row = p[y][bL:bR]
        b = set((np.nonzero(row == 26)[0] + bL).tolist())
        r = set((np.nonzero(row == 31)[0] + bL).tolist())
        k = K if y >= H - K else 0
        if b != set(range(bL, bL + K)) | set(range(bR - K, bR)) or \
                r != set(range(rL + k, rL + K + k)) | set(range(rR - K - k, rR - k)):
            errs.append((y, len(b), len(r)))
    return errs


def _check_logos(c, law_cols):
    """W7B: every logo drawn dp(86) x dp(72) at council_logo_x -- centred in its column's interior, the slack split
    with an odd px on the right (the portrait's rule; deployed c8e5fafd: 4K 12 | 14, governor 40 | 42)."""
    import council_mirror_emu as CME
    g = c["g"]
    fi = SL.council_frame_inset(g)
    logos = sorted((r for r in c["rec"] if r["kind"] == "logo"), key=lambda r: r["bbox"])
    assert len(logos) == 7 and all(r["rect"][2:] == CME.LOGO for r in logos)
    cw, ch = SL.dp(CME.LOGO[0], g), SL.dp(CME.LOGO[1], g)
    for r, col in zip(logos, sorted(law_cols)):
        x = SL.council_logo_x(col[0], col[2], CME.LOGO[0], g)
        assert r["bbox"] == (x, r["rect"][1], x + cw - 1, r["rect"][1] + ch - 1), ("the logo centred (W7B)", r, col)
        gl, gr = x - (col[0] + fi), (col[2] - fi) - (x + cw)
        assert gr - gl in (0, 1), (g, col, gl, gr)


def _check_new(c, inner):
    g, W, H = c["g"], c["W"], c["H"]
    m = _measure(c)
    assert not _bottom_errors(c), ("the bottom strokes clipped below the canvas (W7B)", _bottom_errors(c))
    law_cols = SL.council_column_rects(g)["inner" if inner else "outer"]
    fi = SL.council_frame_inset(g)
    portraits = [r for r in c["rec"] if r["kind"] == "portrait"]
    assert len(portraits) == 7
    for r in portraits:                                # pixel coverage of the synthetic portrait (populate)
        x0, y0, sw, sh = r["rect"]
        col = [cc for cc in law_cols if (cc[0] + fi, cc[1] + fi) == (x0, y0)][0]
        x, y = SL.council_portrait_xy(col, g, sw)
        assert r["bbox"] == (x, y, x + SL.dp(sw, g) - 1, y + SL.dp(sh, g) - 1), ("the portrait centred (W6B)", r, col)
    _check_logos(c, law_cols)
    E, xri = _rails(g, W)
    assert m["border"][1] > 0 and m["bd"][2] == xri - 1, "the right border drawn, against the inner right rail"
    assert W == SL.dp(SL.COUNCIL_W, g), "the canvas t_cw_mirror assumed (imm 0x427A14)"
    law = SL.council_column_rects(g)["inner" if inner else "outer"]
    assert c["seeds"]["inner" if inner else "outer"] == law
    _check_draws(c["rec"], g, W, H, inner)
    assert m["cols"] == sorted(SL.council_drawn(r, g) for r in law)
    assert m["chips"] == sorted(SL.council_drawn(SL.council_chip_rects(r, g)["chip"], g) for r in law)
    inner_w = (8 * g) >> 4 if g > 16 else 8
    rl, rr = m["rails"]["inner_left"], m["rails"]["inner_right"]
    assert (rl[0], rl[2]) == (E - inner_w, E - 1) and (rr[0], rr[2]) == (xri, xri + inner_w - 1), "the rails, by law"
    assert rl[0] + rr[2] == SL.council_rail_mirror_sum(W, g) - 1
    ch = SL.council_layout_channels(g, inner)
    for key in ("border", "border_ring", "ring_col"):
        assert m[key] == ch[key] and m[key][0] == m[key][1], (g, key, m[key], ch[key])
    assert m["ring"][0] == m["ring"][1] and m["colK"][0] == m["colK"][1]
    s = SL.council_rail_mirror_sum(W, g) - 1
    assert {m["cols"][i][0] + m["cols"][6 - i][2] for i in range(7)} == {s}
    assert {m["chips"][i][0] + m["chips"][6 - i][2] for i in range(7)} == {s}
    return m


@pytest.mark.parametrize("res, gov, votes", E2E,
                         ids=[f"{w}x{h}-{'outer' if gov >= 0 else 'inner'}{'-votes' if v else ''}" for (w, h), gov, v in E2E])
def test_e2e_new(rig_new, res, gov, votes):
    c = rig_new.council(*res, gov=gov)
    _check_new(c, gov < 0)
    if not votes:
        return
    v = rig_new.votes(banner=True)
    assert not _bottom_errors(c, v["p"]), "the repaint after the slide clips them too"
    banner = [r for r in v["rec"] if r["kind"] == "banner"]
    assert banner and {r["bbox"] for r in banner} == {SL.council_drawn(SL.council_seed_rects(c["g"])["banner"], c["g"])}, \
        ("the ELECTED banner half-open (W6B)", banner)
    kinds = {r["site"] for r in v["rec"] if r["kind"] == "chip"}
    assert kinds == {0x4261AA, 0x4261D6, 0x426203, 0x426230, 0x42625C, 0x426286}, "every chip kind redrawn"
    _check_draws(v["rec"], c["g"], c["W"], c["H"], gov < 0, first=False)
    E, xri = _rails(c["g"], c["W"])
    assert np.array_equal(c["p"][:, :E], v["p"][:, :E]) and np.array_equal(c["p"][:, xri:], v["p"][:, xri:]), \
        "the post-slide repaints leave every rail column alone"


@pytest.mark.parametrize("gov", (-1, 4))
def test_e2e_g16_is_pristine(rig_new, rig_pristine, gov):
    new = rig_new.council(1024, 768, gov=gov)
    old = rig_pristine.council(1024, 768, gov=gov)
    assert new["g"] == 16 and np.array_equal(new["p"], old["p"]), "pixel for pixel"
    assert [(r["site"], r["rect"], r["bbox"]) for r in new["rec"]] == [(r["site"], r["rect"], r["bbox"]) for r in old["rec"]]
    assert new["seeds"] == old["seeds"] == {k: SL.council_seed_rects(16)[k] for k in ("outer", "inner")}
    _check_new(old, gov < 0)            # vanilla obeys the laws at g = 16 (the identities)


def _stroke_runs(get, lo, hi):
    out = []
    for x in range(lo, hi):
        t = get(x)
        if t and out and out[-1][1] == x - 1 and out[-1][2] == t:
            out[-1][1] = x
        elif t:
            out.append([x, x, t])
    return [tuple(r) for r in out]


@pytest.mark.parametrize("shot", SHOTS_RUN)
def test_e2e_before_draws_the_user_shots(rig_before, shot):
    """The deployed build draws the shots' stroke columns: shown, the right border under the rail and the layout's
    mirror sum 3 px (1080) right of the rails'; after a vote, the border repainted over the rail's first columns."""
    res, name = shot.split("_", 1)
    w, h = (int(v) for v in res.split("x"))
    gov, phase, sy, sx0, left, right = SHOTS[shot]
    old = rig_before.council(w, h, gov=gov)
    g, W = old["g"], old["W"]
    m = _measure(old)
    assert old["x"] == sx0 and old["y"] + m["y"] == sy
    p = old["p"] if phase == "show" else rig_before.votes(calls=0)["p"]   # a repaint after the slide
    assert _bottom_errors(old, p), "the deployed band map clamped the bottom strokes onto the canvas (W7B's defect)"
    y = sy - old["y"]
    E, xri = _rails(g, W)
    inner_w = (8 * g) >> 4
    cols = m["cols"]
    get = lambda x: STROKE_IDX.get(int(p[y][x - sx0]))      # noqa: E731
    runs_l = _stroke_runs(get, sx0 + E, sx0 + cols[0][0] + 2)
    runs_r = _stroke_runs(get, sx0 + cols[6][2] - 2, sx0 + xri + inner_w)
    assert runs_l == left and runs_r == right, (runs_l, runs_r)
    bd = m["bd"]
    assert bd[2] >= xri, "the deployed backdrop reached the rail (its right border hidden, or painted over the rail)"
    assert bd[0] + bd[2] - (SL.council_rail_mirror_sum(W, g) - 1) == 3, "the old centre offset x 2 (1080)"
    png = SHOT_DIR / f"terranx_pracx_{res}_{name}.png"
    if png.exists():
        from PIL import Image
        img = Image.open(png).convert("RGB")
        got = _stroke_runs(lambda x: STROKE_RGB.get(img.getpixel((x, sy))), sx0 + E, sx0 + xri + inner_w)
        assert got[:3] == left and got[-len(right):] == right, (name, got)
