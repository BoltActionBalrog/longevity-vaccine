"""F42 (2026-10-25 wave-4 W4C v2, wave-5 W5C v3): the Social Engineering modal on half-open frames, every vanilla pair kept.

Vanilla draws each SocialWin Buffer_box_sprite frame half-open (right stroke on col R-1, bottom on row B-1).  The
lever-F thunks band-map the rect INCLUSIVE, one device px past the native extent: the backdrop's right border sat ON
the right slide rail's first column (visible K-1: 4K 2 | 1, 1920x1080 1 | 0), the frames one px wide and tall, and the
OK row's union frame stayed on the native 1-px primitive.  The eleven band-map sites and the union frame are now drawn
on the half-open rect (se_frame_draw_rect; t_bm_ho_df / t_bm_ho_hf), and t_se_layout re-derives the band / option /
SOCIETY / SPARTANS tables from the drawn frames (se_halfopen_choices / se_halfopen_layout): the trim alone had unmasked
per-edge rounding that broke vanilla's mirrored channels (audit-w4C: band title -> row vs cell -> bottom 6 | 5 at 4K,
option runs 5 | 6, SOCIETY rows 2 | 3 at 1600x1200, a jog between the band and SOCIETY title bands).
W5C (v3): W4C v2's title bands were s(23) - s(3) tall but the cells fl(20), the cells s(22) below the row, the title
insets s(3) -- so the band's title-top inset vs its cell-row bottom inset (relation a, vanilla 3 | 3) and the option row
centred in its band (relation b, vanilla 25 | 25) could not both hold (audit-w4C v2: 32 and 5 band x g cases).  Now ONE
grammar (scaling_laws.se_halfopen_parts): every 20 is fl(20), one channel c, one inset ti = c + K, row -> cell offset
o = h + c, and t_se_layout owns the 17 painter immediates that carry them (SE_LAYOUT_IMMS, out of g_se_immtab).
W6H (v4, the user's "Hybrid", chosen on the se_options comparison sheets): where W5C's worst vertical error vs vanilla
x g/16 exceeds 2.5 px, exactly ONE of the relations adj / a / b / os is broken by 1 px (se_halfopen_hybrid); the title
bands' L / R inset stays W5C's (the approved prototype), so their 'title L|R|T' trio is uneven where the top inset moved.
The census below expects exactly those keys uneven (HYBRID_BREAKS), every other vanilla pair even.

Proof layers, on the REAL bytes of the shared bake (conftest `baked_exe`):
  1. laws: the draw rect; the layout's drawn geometry keeps every vanilla-mirrored pair mirrored and every
     vanilla-aligned pair aligned, relations (a) / (b) and the SOCIETY panel's analogues included (g 17..96); the
     vanilla-unmirrored distances within their attained bounds of vanilla x g/16; BRUTE FORCE: no integer layout that
     keeps the three band relations (one rounding of 20) has a smaller worst search-A error than the law's, and
     that min-max -- the residual set -- is pinned for g 17..40; BRUTE FORCE (g 17..64) for the hybrid: the
     prototype's own search (every layout with one relation broken by 1) finds the law's layout, worst <= 2.5 px at
     every g; the painter immediates have one owner and
     their native bytes are the pristine image's; the port wiring (assemble_se.FRAME_SITES == SE_HALFOPEN_FRAME_SITES);
  2. t_se_layout from the baked bytes under Unicorn == se_halfopen_layout + se_halfopen_imms for every g 1..256
     (the immediates gated on g_se_vpdone; natives at g <= 16), registers kept;
  3. END TO END (se_halfopen_emu.py): the real MainWin_build, SocialWin_build and SocialWin_show_hide(1) -- the real
     slide rails over the modal, every option-cell branch forced -- at 1024 / g 17 / 22 / 25 / 40.  The engine's own
     tables and BaseButton_init windows == the law; every frame's drawn footprint == its half-open rect; the census of
     the vanilla-mirrored / vanilla-aligned pairs (VANILLA, measured on the pristine image in the 1024 item) mirrored /
     aligned; the backdrop's border widths MEASURED on the composed canvas K | K; g = 16 pixel-identical to the pristine
     image; at 1920x1080 the same boot with the W4C edits reverted in memory reproduces the defect and the census shows
     no pair got worse.

COST (~90 s serial): ONE emulator per worker (~3 s boot; the reverted bake is the same boot rewritten in memory, the
pristine image boots only in the 1024 item); a screen runs MainWin_build + SocialWin_build + show_hide (~5 s at 1024 ..
~30 s at 4K, where the band-map renderers fill a 2083 x 885 canvas), the repaint's console painters skipped (MainWin's
canvas only).  Items are per screen so the module splits across xdist by measured cost.  The brute force is ~1 s.
"""
from __future__ import annotations

import contextlib
import io
import itertools
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

LAW_G = range(17, 97)
E2E_G = (17, 22, 25, 40)        # K = 1 (17, 22), K = 2 (25, 40): 1080 / 1600x1200 / 4K
#: the pristine image's census at 1024 (measured; test_e2e_g16_is_pristine re-measures it)
VANILLA = {
    "backdrop border L|R": (1, 1), "soc>rows L|R": (2, 2), "soc>rows T|B": (2, 2), "soc>title L|R|T": (2, 2, 2),
    "soc title over rows L|R": (0, 0), "soc title T | rows B inset": (3, 3), "soc row4 T|B": (113, 113),
    **{k: v for i in range(4) for k, v in (
        (f"band{i}>title L|R|T", (2, 2, 2)), (f"band{i}>options L|R", (2, 2)),
        (f"band{i} title>row T | cells>band B", (2, 2)), (f"band{i} title T | cells B inset", (3, 3)),
        (f"band{i} option row T|B", (25, 25)), (f"band{i} option seams", (2, 2, 2)),
        (f"band{i} cell seams", (2, 2, 2)), (f"band{i} cells on options L|R", ((0, 0),) * 4),
        (f"band{i} title over options L|R", (0, 0)))},
    "band gaps": (3, 3, 3), "title bands band0 vs SOCIETY (T, B)": (0, 0), "frame tops band0 vs SOCIETY": 0,
    "SPARTANS bands T|B": (3, 3), "SPARTANS bands L|R": (3, 3), "SPARTANS vs SOCIETY L,R": (0, 0),
    "union>buttons L|R|T|B": (2, 2, 2, 2),
    "~band R>SOCIETY L": 3, "~SPARTANS band gap": 2, "~band 3>union": 18, "~SOCIETY>SPARTANS": 3,
    "~SPARTANS>union": 10, "~SPARTANS B - band 3 B": 8,
}
#: the worst distance from vanilla x g/16 any g 17..96 reaches (attained; test_law_m3_bounds_are_attained), the
#: hybrid's layouts included (W5C alone: band 3 -> union 1.5, SOCIETY -> SPARTANS 1.875, SPARTANS -> union 2.5).
M3_TOL = {"~band R>SOCIETY L": 1.0625, "~SPARTANS band gap": 1.25, "~band 3>union": 1.125, "~SOCIETY>SPARTANS": 1.8125,
          "~SPARTANS>union": 1.25, "~SPARTANS B - band 3 B": 1.5}
#: W6H: the census keys each hybrid kind leaves uneven by exactly 1 (every other vanilla pair stays even), and the
#: title trios that go uneven when the hybrid's top inset ti leaves W5C's L / R inset tlr
HYBRID_BREAKS = {
    "adj": [f"band{i} title>row T | cells>band B" for i in range(4)] + ["soc>rows T|B"],
    "a": [f"band{i} title T | cells B inset" for i in range(4)] + ["soc title T | rows B inset"],
    "b": [f"band{i} option row T|B" for i in range(4)] + ["soc row4 T|B"],
    "os": ["soc row4 T|B"],
}
TLR_KEYS = [f"band{i}>title L|R|T" for i in range(4)] + ["soc>title L|R|T"]


def expected_uneven(g):
    """{census key: its violation} the law leaves on purpose at g (empty where W5C stands)."""
    q = SL.se_halfopen_parts(g)
    out = {}
    if q["kind"]:
        out.update({k: 1 for k in HYBRID_BREAKS[q["kind"]]})
    if q["ti"] != q["tlr"]:
        out.update({k: abs(q["ti"] - q["tlr"]) for k in TLR_KEYS})
    return out


#: THE RESIDUAL SET (px): search A's min-max at g 17..40 (g + 16 repeats g: the same fractional parts).  Holding the
#: three band relations with one rounding of 20 forces ti = c + K, o = h + c, Hb = 3h + 4c + 2K and -- o being the
#: SOCIETY row pitch too (row 1 on the cells' line) -- the panel height 11h + 12c + 2K: c's rounding counts 4x in a band
#: and 12x in the panel.  The band column's own worst (T0, ti, c, o, Hb, band gap, band 3 -> union) stays <= 1.875 px
#: except g 26 / 31 (2.875 / 2.8125, where c buys the panel 3 / 1.25 px); the panel height binds elsewhere (<= 5.5 px at
#: g 20 / 28 / 36; W4C v2's independently rounded s(22) pitch: <= 3.5).  test_law_band_minmax_brute_force proves no
#: integer layout keeping the relations does better at any g.
SEARCH_A_MINMAX = {17: 4.375, 18: 3.25, 19: 1.125, 20: 5.5, 21: 1.125, 22: 3.25, 23: 4.375, 24: 1.5, 25: 3.375,
                   26: 4.25, 27: 1.0625, 28: 5.5, 29: 2.125, 30: 2.25, 31: 5.375, 32: 0.0, 33: 4.375, 34: 3.25,
                   35: 1.125, 36: 5.5, 37: 1.125, 38: 3.25, 39: 4.375, 40: 1.5}


def K(g):
    return SL.stroke_width(g) if g > 16 else 1


# ============================================================================== 1. laws
@pytest.mark.parametrize("g", range(1, 17))
def test_law_native_identity(g):
    for va in SL.SE_HALFOPEN_FRAME_SITES:
        assert SL.se_frame_draw_rect(va, 23, 4, 778, 354, g) == (23, 4, 778, 354)
    assert SL.se_halfopen_choices(g) == (0,) * 9
    assert SL.se_halfopen_layout(g) == SL.se_modal_rects(g)
    assert SL.se_halfopen_imms(g) == {va: nat for va, (_w, _r, nat) in SL.SE_LAYOUT_IMMS.items()}


@pytest.mark.parametrize("g", (17, 25, 40, 64))
def test_law_draw_rect_is_the_half_open_extent(g):
    for va in SL.SE_HALFOPEN_FRAME_SITES:
        assert SL.se_frame_draw_rect(va, 100, 50, 300, 200, g) == (100, 50, 299, 199)
        assert SL.se_frame_footprint((100, 50, 300, 200), g) == (100, 50, 299, 199)


def _law_census(g):
    """The census keys on the law's DRAWN geometry: every frame [L, R-1] x [T, B-1] with K-wide strokes, the painter's
    own insets from se_halfopen_parts (title bands T + ti .. T + ti + h inset ti; row-2 cells +o; SPARTANS bands
    inset ti (L / R) and fi (T / B), h tall), the union frame the OK row outset s3."""
    L, k, q = SL.se_halfopen_layout(g), K(g), SL.se_halfopen_parts(g)
    ti, h, o, fi, tl = q["ti"], q["h"], q["o"], q["fi"], q["tlr"]
    s3 = SL.scale_px(3, g)

    def D(r):
        return (r[0], r[1], r[2] - 1, r[3] - 1)
    m = {}
    P = L["society_outer"]
    soc, st = D(P), D((P[0] + tl, P[1] + ti, P[2] - tl, P[1] + ti + h))
    rows = L["society_rows"]
    m["soc>title L|R|T"] = (st[0] - soc[0] - k, soc[2] - st[2] - k, st[1] - soc[1] - k)
    m["soc>rows L|R"] = (rows[0][0] - (soc[0] + k), (soc[2] - k + 1) - rows[0][2])
    m["soc>rows T|B"] = (rows[0][1] - st[3] - 1, (soc[3] - k + 1) - rows[-1][3])
    m["soc title over rows L|R"] = (rows[0][0] - st[0], st[2] - (rows[0][2] - 1))
    m["soc title T | rows B inset"] = (st[1] - soc[1], soc[3] - (rows[-1][3] - 1))
    m["soc row4 T|B"] = (rows[4][1] - soc[1], soc[3] - (rows[4][3] - 1))
    for i, Bd in enumerate(L["bands"]):
        b, t = D(Bd), D((Bd[0] + tl, Bd[1] + ti, Bd[2] - tl, Bd[1] + ti + h))
        op = L["options"][4 * i:4 * i + 4]
        m[f"band{i}>title L|R|T"] = (t[0] - b[0] - k, b[2] - t[2] - k, t[1] - b[1] - k)
        m[f"band{i}>options L|R"] = (op[0][0] - (b[0] + k), (b[2] - k + 1) - op[3][2])
        m[f"band{i} title>row T | cells>band B"] = (op[0][1] - t[3] - 1, (b[3] - k + 1) - (op[0][3] + o))
        m[f"band{i} title T | cells B inset"] = (t[1] - b[1], b[3] - (op[0][3] + o - 1))
        m[f"band{i} option row T|B"] = (op[0][1] - b[1], b[3] - (op[0][3] - 1))
        m[f"band{i} option seams"] = tuple(op[j + 1][0] - op[j][2] for j in range(3))
        m[f"band{i} title over options L|R"] = (op[0][0] - t[0], t[2] - (op[3][2] - 1))
        if i == 0:
            m["title bands band0 vs SOCIETY (T, B)"] = (t[1] - st[1], t[3] - st[3])
    bs = [D(b) for b in L["bands"]]
    m["band gaps"] = tuple(bs[i + 1][1] - bs[i][3] - 1 for i in range(3))
    F = L["faction"]
    fac, f1, f2 = D(F), D((F[0] + tl, F[1] + fi, F[2] - tl, F[1] + fi + h)), D((F[0] + tl, F[3] - fi - h, F[2] - tl, F[3] - fi))
    m["SPARTANS bands T|B"] = (f1[1] - fac[1], fac[3] - f2[3])
    m["SPARTANS vs SOCIETY L,R"] = (fac[0] - soc[0], fac[2] - soc[2])
    bt = (L["cancel"], L["reset"], L["ok"])
    un = D((bt[0][0] - s3, bt[0][1] - s3, bt[2][2] + s3, bt[0][3] + s3))
    m["union>buttons L|R|T|B"] = (bt[0][0] - (un[0] + k), (un[2] - k + 1) - bt[2][2], bt[0][1] - (un[1] + k),
                                  (un[3] - k + 1) - bt[0][3])
    m["~band R>SOCIETY L"] = soc[0] - bs[0][2] - 1
    m["~SPARTANS band gap"] = f2[1] - f1[3] - 1
    m["~band 3>union"] = un[1] - bs[3][3] - 1
    m["~SOCIETY>SPARTANS"] = fac[1] - soc[3] - 1
    m["~SPARTANS>union"] = un[1] - fac[3] - 1
    m["~SPARTANS B - band 3 B"] = fac[3] - bs[3][3]
    return m


def _check_census(m, g, where):
    """Mirrored pairs equal (except the hybrid's expected_uneven keys: uneven by exactly their amount), aligned pairs on
    vanilla's offsets (the title-band overhangs symmetric and <= 2), the M3 distances within M3_TOL of vanilla x g/16."""
    import se_halfopen_emu as SH
    kinds = SH.classify(VANILLA)
    exp = expected_uneven(g)
    for key, v in m.items():
        kind, f = kinds[key], SH.flat(v)
        if key in exp:
            assert SH.violation(kind, v, VANILLA[key]) == exp[key], (where, g, key, v, exp[key])
        elif " over " in key:
            # the title band (inset ti = K + c) over its row run (4 fl(146) + 3 s(2), or fl(143)), centred with a
            # channel nearest c under the parity of its frame: a symmetric overhang 0..2 px
            assert f[0] == f[1] and -1 <= f[0] <= 2, (where, g, key, v)
        elif kind == "mirror":
            assert len(set(f)) == 1, (where, g, key, v)
        elif kind == "align":
            assert v == VANILLA[key], (where, g, key, v)
        else:
            assert abs(v - VANILLA[key] * g / 16) <= M3_TOL[key], (where, g, key, v)


@pytest.mark.parametrize("g", LAW_G)
def test_law_layout_keeps_every_vanilla_pair(g):
    _check_census(_law_census(g), g, "law")


@pytest.mark.parametrize("g", LAW_G)
def test_law_relations_exact_or_one_broken(g):
    """The vertical relations, stated outright: adj (title -> row channel == cell -> stroke channel), (a) the title band's
    top inset == the cell row's bottom inset, (b) the option row centred in its band, os (the SOCIETY row pitch == the
    cell offset: row 1 on the cells' line) -- all exact where W5C stands; under the hybrid exactly the named one off by
    exactly 1, every other exact (the SOCIETY analogues follow the band's)."""
    q, L = SL.se_halfopen_parts(g), SL.se_halfopen_layout(g)
    k, h = K(g), q["h"]
    rel = {"adj": q["c1"] - q["c3"], "a": q["ti"] - (q["c3"] + k), "b": (q["ti"] + h + q["c1"]) - (q["c2"] + h + q["c3"] + k),
           "os": q["os"] - (h + q["c2"])}
    broken = {n: d for n, d in rel.items() if d}
    assert broken == ({} if q["kind"] is None else {q["kind"]: broken.get(q["kind"])}) and all(abs(d) == 1 for d in broken.values()), \
        (g, q["kind"], rel)
    m = _law_census(g)
    for i in range(4):
        for key in (f"band{i} title>row T | cells>band B", f"band{i} title T | cells B inset", f"band{i} option row T|B"):
            assert (m[key][0] == m[key][1]) == (key not in expected_uneven(g)), (g, key, m[key])
    assert (L["society_rows"][1][1] == L["options"][0][1] + q["o"]) == (q["kind"] != "os"), "SOCIETY row 1 on the cells' line"


@pytest.mark.parametrize("g", LAW_G)
def test_law_one_rounding_and_worst_within_2_5(g):
    """Every 20 is ONE rounding (fl(20): rows, cells, every title band, both SPARTANS bands); the worst of the 18
    vertical terms vs vanilla x g/16 <= 2.5 px (the hybrid's promise); W5C's deltas small."""
    q = SL.se_halfopen_parts(g)
    h = SL.popup_scale_floor(20, g)
    L = SL.se_halfopen_layout(g)
    assert q["h"] == h and all(r[3] - r[1] == h for r in L["options"] + L["society_rows"])
    imms = SL.se_halfopen_imms(g)
    assert {imms[va] for va, (_w, role, _n) in SL.SE_LAYOUT_IMMS.items() if role == "h"} == {h}
    assert imms[0x4AFA09] == -h
    assert SL.se_halfopen_worst16(g) <= SL.SE_HYBRID_LIMIT16 == 40
    d = SL.se_halfopen_choices(g)
    assert abs(d[0]) <= 1 and abs(d[1]) <= 2 and abs(d[2]) <= 2 and all(abs(x) <= 2 for x in d[3:]), d


#: the 18 terms (vanilla values) of the hybrid metric, written out independently of the law (the se_options prototype)
_VAN18 = dict(T0=4, ti=3, ht=20, c1=2, c2=2, c3=2, o=22, os=22, Hb=70, gap=3, b3u=18, socH=246, gs=3, facH=48, gf=2,
              facu=10, facb3=8, fi=3)


def _quantities(g, T0, ti, ht, c1, c2, c3, os_, P, gs, fi, gf):
    k, h = SL.stroke_width(g), SL.popup_scale_floor(20, g)
    union_t = SL.scale_px(SL.SE_BTN_OK[1], g) - SL.scale_px(3, g)
    Hb = ti + ht + c1 + h + c2 + h + c3 + k
    socH = ti + ht + c1 + 9 * os_ + h + c3 + k
    b3b = T0 + 3 * P + Hb
    fac_b = T0 + socH + gs + 2 * fi + 2 * h + gf
    return dict(T0=T0, ti=ti, ht=ht, c1=c1, c2=c2, c3=c3, o=h + c2, os=os_, Hb=Hb, gap=P - Hb, b3u=union_t - b3b,
                socH=socH, gs=gs, facH=2 * fi + 2 * h + gf, gf=gf, facu=union_t - fac_b, facb3=fac_b - b3b, fi=fi)


def _errs(g, **kw):
    q = _quantities(g, **kw)
    return [abs(q[n] - v * g / 16) for n, v in _VAN18.items()]


@pytest.mark.parametrize("g", range(17, 65))
def test_law_hybrid_brute_force(g):
    """PROOF (g 17..64): W5C's worst <= 2.5 px where the law keeps it; elsewhere the prototype the user approved -- a
    product search over T0 (s4 +- 1), ti (s3 -1..+2), c1 / c2 / c3 (s2 -1..+2), os (s22 +- 1), P (s73 +- 3), the title
    band one rounding, every layout with exactly ONE of adj / a / b / os off by exactly 1, the right column per layout
    by (worst, sum) over gs (s3 -2..+3) / fi (s3 +- 1) / gf (s2 +- 1) -- finds the law's layout as its first minimum of
    (worst, sum), and that worst is <= 2.5 px."""
    s = lambda v: SL.scale_px(v, g)   # noqa: E731
    k, h = SL.stroke_width(g), SL.popup_scale_floor(20, g)
    q5 = SL.se_halfopen_parts_w5c(g)
    w5 = max(_errs(g, T0=q5["T0"], ti=q5["ti"], ht=h, c1=q5["c"], c2=q5["c"], c3=q5["c"], os_=q5["o"], P=q5["P"],
                   gs=q5["gs"], fi=q5["fi"], gf=q5["gf"]))
    q = SL.se_halfopen_parts(g)
    if w5 <= 2.5:
        assert q["kind"] is None
        return
    union_t = s(SL.SE_BTN_OK[1]) - s(3)
    rc = {}

    def right(soc_b, b3b):
        if (soc_b, b3b) not in rc:
            best = None
            for gs, fi, gf in itertools.product(range(s(3) - 2, s(3) + 4), range(s(3) - 1, s(3) + 2), range(s(2) - 1, s(2) + 2)):
                fb = soc_b + gs + 2 * fi + 2 * h + gf
                e = [abs(x - v * g / 16) for x, v in ((gs, 3), (fi, 3), (gf, 2), (2 * fi + 2 * h + gf, 48),
                                                       (union_t - fb, 10), (fb - b3b, 8))]
                if best is None or (max(e), sum(e)) < best[0]:
                    best = ((max(e), sum(e)), gs, fi, gf)
            rc[(soc_b, b3b)] = best
        return rc[(soc_b, b3b)]
    best = None
    for T0, ti, c1, c2, c3, os_ in itertools.product(range(s(4) - 1, s(4) + 2), range(s(3) - 1, s(3) + 3),
                                                     range(s(2) - 1, s(2) + 3), range(s(2) - 1, s(2) + 3),
                                                     range(s(2) - 1, s(2) + 3), range(s(22) - 1, s(22) + 2)):
        rel = [c1 - c3, ti - c3 - k, ti + c1 - (c2 + c3 + k), os_ - h - c2]
        if sum(1 for d in rel if d) != 1 or max(abs(d) for d in rel) != 1:
            continue
        for P in range(s(73) - 3, s(73) + 4):
            Hb = ti + h + c1 + h + c2 + h + c3 + k
            socH = ti + h + c1 + 9 * os_ + h + c3 + k
            r = right(T0 + socH, T0 + 3 * P + Hb)
            e = _errs(g, T0=T0, ti=ti, ht=h, c1=c1, c2=c2, c3=c3, os_=os_, P=P, gs=r[1], fi=r[2], gf=r[3])
            key = (max(e), sum(e))
            if best is None or key < best[0]:
                best = (key, dict(T0=T0, ti=ti, c1=c1, c2=c2, c3=c3, os=os_, P=P, gs=r[1], fi=r[2], gf=r[3]))
    assert best[0][0] <= 2.5, (g, best)
    assert {n: q[n] for n in best[1]} == best[1], (g, best[1], q)
    assert SL.se_halfopen_worst16(g) == round(16 * best[0][0])


def test_law_m3_bounds_are_attained():
    """M3_TOL is the law's worst case, not slack."""
    for key, tol in M3_TOL.items():
        worst = max(abs(_law_census(g)[key] - VANILLA[key] * g / 16) for g in LAW_G)
        assert worst <= tol and (worst == tol or tol == 1.0), (key, worst)


def _band_errors(g, t0, ti, ct, o, hb, p, h):
    """Search A's eight errors (px) vs vanilla x g/16: T0, ti, the channel, o, Hb, the band gap, band 3 -> the OK
    union, and the SOCIETY panel height (2 ti + 2 h + channel + 9 o, its rows on pitch o)."""
    unt = SL.scale_px(SL.SE_BTN_OK[1], g) - SL.scale_px(3, g)
    return [abs(x - v * g / 16) for x, v in ((t0, 4), (ti, 3), (ct, 2), (o, 22), (hb, 70), (p - hb, 3),
                                             (unt - (t0 + 3 * p + hb), 18), (2 * ti + 2 * h + ct + 9 * o, 246))]


@pytest.mark.parametrize("g", range(17, 41))
def test_law_band_minmax_brute_force(g):
    """(W5C's relation-exact layout, still the base of the hybrid) PROOF of the residual set: over EVERY integer band layout near the scaled values -- T0, ti, the title -> row
    channel, o, Hb, P free (ti, channel, o, Hb within 2 of s(), T0 within 1, P within 3), the title band and cells ONE
    rounding h = fl(20) -- that keeps the three relations (title -> row == cell -> bottom; (a) ti == bottom inset; (b)
    the option row centred), none has a smaller worst search-A error than the law's: SEARCH_A_MINMAX is forced by the
    relations + one rounding, not by the search."""
    s = lambda v: SL.scale_px(v, g)   # noqa: E731
    k, h = SL.stroke_width(g), SL.popup_scale_floor(20, g)
    q = SL.se_halfopen_parts_w5c(g)
    law = max(_band_errors(g, q["T0"], q["ti"], q["c"], q["o"], q["Hb"], q["P"], h))
    best = None
    for t0, ti, ct, o, hb, p in itertools.product(range(s(4) - 1, s(4) + 2), range(s(3) - 2, s(3) + 3),
                                                  range(s(2) - 2, s(2) + 3), range(s(22) - 2, s(22) + 3),
                                                  range(s(70) - 2, s(70) + 3), range(s(73) - 3, s(73) + 4)):
        y = ti + h + ct
        cb = (hb - k) - (y + o + h)
        if ct != cb or ti != cb + k or y != hb - (y + h):
            continue
        e = max(_band_errors(g, t0, ti, ct, o, hb, p, h))
        best = e if best is None else min(best, e)
    assert best is not None and abs(best - law) < 1e-9, (g, best, law)
    assert law == SEARCH_A_MINMAX[g], (g, law)


def test_layout_imms_have_one_owner(bak_bytes):
    """The 17 painter immediates t_se_layout writes left thunk_se_immfix's table (one owner each), every one of them
    holds its native value in the pristine image, and each is the operand of the instruction the law names."""
    with contextlib.redirect_stdout(io.StringIO()):
        import assemble_se as AS
    pe = pefile.PE(data=bak_bytes)
    ib = pe.OPTIONAL_HEADER.ImageBase
    sites = {e[0] for e in AS.IMMTAB}
    assert not sites & set(SL.SE_LAYOUT_IMMS)
    assert {a + o for a, o, _w, _a, _b in AS.LAYOUT_OWNED} == set(SL.SE_LAYOUT_IMMS)
    for va, (w, _role, nat) in SL.SE_LAYOUT_IMMS.items():
        raw = pe.get_data(va - ib, w)
        assert raw == struct.pack("<i", nat)[:w], (hex(va), raw)
        op = pe.get_data(va - ib - (1 if w == 4 else 2), 2)
        assert (op[0] == 0xB8) if w == 4 else (op[0] == 0x83 and op[1] in (0xC0, 0xC1, 0xE8, 0xEA, 0xEF)), (hex(va), op)


def test_frame_sites_wiring():
    """assemble_se.FRAME_SITES (the site yaml generator) == SE_HALFOPEN_FRAME_SITES through the helper map."""
    import assemble_halfopen_frames as HO
    with contextlib.redirect_stdout(io.StringIO()):
        import assemble_se as AS
    got = {va: (sid, tgt) for sid, _fn, va, tgt in AS.FRAME_SITES}
    want = {va: (sid, HO.SE_SITE_HELPER[ren]) for va, (sid, ren) in SL.SE_HALFOPEN_FRAME_SITES.items()}
    assert got == want
    assert AS.T_SE_LAYOUT == HO.PCAVE2 + HO.SE_LAYOUT_OFF


# ============================================================================== 2. t_se_layout on the baked bytes
@pytest.fixture(scope="module")
def sym():
    import se_halfopen_emu as SH
    return SH.symtab()


@pytest.fixture(scope="module")
def layout_uc(baked_exe, sym):
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    pe = pefile.PE(data=Path(baked_exe).read_bytes())
    ib = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for s in pe.sections:
        va = ib + s.VirtualAddress
        mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
        mu.mem_write(va, s.get_data())
    mu.mem_map(0x10000000, 0x100000)          # the stack (SocialWin 0x8A6270 is in the image's own data)
    mu.mem_write(0x4AECE0, b"\xF4")
    return mu


def _imm_bytes(g):
    return {va: struct.pack("<i", v)[:SL.SE_LAYOUT_IMMS[va][0]] for va, v in SL.se_halfopen_imms(g).items()}


def test_t_se_layout_is_the_law(layout_uc, sym):
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                                   UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)
    mu, va = layout_uc, sym["t_se_layout"]
    regs = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
    obj = 0x8A6270
    for vpdone in (1, 0):
        mu.mem_write(sym["g_se_vpdone"], struct.pack("<I", vpdone))
        for g in range(1, 257):
            mu.mem_write(0x668740, struct.pack("<I", g))
            m = SL.se_modal_rects(g)
            mu.mem_write(obj + 0x1F2B4, struct.pack("<i", m["ok"][1]))
            mu.mem_write(0x4B330A, struct.pack("<i", m["backdrop"][2]))
            for a, (w, _r, _n) in SL.SE_LAYOUT_IMMS.items():
                mu.mem_write(a, b"\xA5" * w)
            before = bytes(mu.mem_read(obj + 0x1F060, 0x260))
            sp = 0x10080000
            mu.reg_write(UC_X86_REG_ESP, sp)
            for i, r in enumerate(regs):
                mu.reg_write(r, 0x5A5A0000 + i)
            mu.emu_start(va, 0x4AECE0, count=60_000_000)
            assert mu.reg_read(UC_X86_REG_EIP) == 0x4AECE0 and mu.reg_read(UC_X86_REG_ESP) == sp, g
            assert [mu.reg_read(r) for r in regs] == [0x5A5A0000 + i for i in range(len(regs))], "pushad / popad"
            # the immediates: written only once thunk_se_immfix made the pages writable; g <= 16 the native bytes
            want = _imm_bytes(g)
            for a, (w, _r, _n) in SL.SE_LAYOUT_IMMS.items():
                assert bytes(mu.mem_read(a, w)) == (want[a] if vpdone else b"\xA5" * w), (g, vpdone, hex(a))
            if g <= 16:
                assert bytes(mu.mem_read(obj + 0x1F060, 0x260)) == before, "native: the tables untouched"
                continue

            def rect(a):
                return struct.unpack("<4i", bytes(mu.mem_read(obj + a, 16)))
            L = SL.se_halfopen_layout(g)
            assert [rect(0x1F110 + 16 * i) for i in range(4)] == L["bands"], g
            assert [rect(0x1F150 + 16 * i) for i in range(16)] == L["options"], g
            assert [rect(0x1F070 + 16 * i) for i in range(10)] == L["society_rows"], g
            assert rect(0x1F060) == L["society_outer"] and rect(0x1F2A0) == L["faction"], g


# ============================================================================== 3. end to end
@pytest.fixture(scope="module")
def rig_new(sym, baked_exe):
    """ONE emulator per worker (a 4K SocialWin draw needs the 256 MB bump heap): the 'before' bake is this same boot
    with the W4C edits reverted in memory (se_halfopen_emu.Rig.reverted); the pristine image boots only in its item."""
    import se_halfopen_emu as SH
    return SH.Rig(str(baked_exe), sym)


def _clip(fp, p):
    h, w = p.shape
    return (max(fp[0], 0), max(fp[1], 0), min(fp[2], w - 1), min(fp[3], h - 1))


def _check_footprints(res):
    p = res["p"]
    assert set(res["rec"]) == set(SL.SE_HALFOPEN_FRAME_SITES), "every frame site drew (lock_c forced)"
    for va, calls in res["rec"].items():
        for c in calls:
            assert c["bbox"] == _clip(SL.se_frame_footprint(c["rect"], res["g"]), p), (res["g"], hex(va), c)


def _windows(res):
    return {(a[2], a[3], a[2] + a[4], a[3] + a[5]) for _ecx, a in res["bb"]}


@pytest.mark.parametrize("g", E2E_G)
def test_e2e_tables_footprints_census(rig_new, g):
    import se_halfopen_emu as SH
    res = rig_new.screen(*SH.screen_for(g))
    assert res["g"] == g
    L, T = SL.se_halfopen_layout(g), res["tables"]
    for key in ("bands", "options", "society_rows"):
        assert T[key] == L[key], (g, key)
    assert T["society_outer"] == [L["society_outer"]] and T["faction"] == [L["faction"]], g
    # the builder's BaseButton_init windows (the ten SOCIETY rows and CANCEL / RESET / OK; the option buttons are built
    # by model_reset for the faction's available options, none with the emulated faction) are the table rects
    assert set(L["society_rows"]) | set(T["btns"]) <= _windows(res), "BaseButton_init got the table rects"
    _check_footprints(res)
    for va, calls in res["rec"].items():
        assert all(c["restored"] == c["rect"] for c in calls), ("the caller's rect restored", hex(va))
    (bd,) = res["rec"][0x4B3315]
    assert bd["rect"] == SL.se_backdrop_rect(g) and bd["rect"][3] == res["p"].shape[0], "rail to rail, canvas-tall"
    m = SH.census(res)
    assert m["backdrop border L|R"] == (K(g), K(g)), "measured between the real rails"
    _check_census({k: v for k, v in m.items() if k != "backdrop border L|R" and "cell" not in k}, g, "image")
    for i in range(4):
        assert m[f"band{i} cells on options L|R"] == ((0, 0),) * 4, "a cell is its option button's own rect"
        assert len(set(m[f"band{i} cell seams"])) == 1
    law = _law_census(g)
    assert {k: v for k, v in m.items() if k in law} == law, "the image draws the law's geometry"
    if g == 22:
        _reverted_at_1080(rig_new, m)


def _reverted_at_1080(rig, new):
    """The deployed c8374772 bake on the same boot: the defect reproduced, and no vanilla pair worse in the new bake.
    The backdrop: thunk_box_thick_devfill clamps the rect's B (the canvas height) to the last row IN PLACE before it
    draws -- the caller's local comes back clamped from the untrimmed call, intact from the trimming helper."""
    import se_halfopen_emu as SH
    with rig.reverted(22):
        old = rig.screen(*SH.screen_for(22))
    (bd,) = old["rec"][0x4B3315]
    assert bd["restored"] == bd["rect"][:3] + (old["p"].shape[0] - 1,), "devfill's in-place clamp"
    for va, calls in old["rec"].items():
        for c in calls:
            want = (c["rect"][0], c["rect"][1], c["rect"][2] - 1, c["rect"][3] - 1) if va == SL.SE_UNION_FRAME_SITE \
                else c["rect"]
            assert c["bbox"] == _clip(want, old["p"]), ("the untrimmed footprint", hex(va), c)
    m = SH.census(old)
    assert m["backdrop border L|R"] == (1, 0), "1080: no right border"
    assert m["soc>rows L|R"] == (3, 5) and m["band0 cells on options L|R"] == ((0, 1),) * 4
    kinds = SH.classify(VANILLA)
    exp = expected_uneven(22)
    for key, v in new.items():
        if kinds[key] != "scalar" and key not in exp:
            assert SH.violation(kinds[key], v, VANILLA[key]) <= SH.violation(kinds[key], m[key], VANILLA[key]), \
                ("no vanilla pair worse than the deployed bake", key, m[key], v)


def test_e2e_g16_is_pristine(rig_new, sym, bak_path):
    import se_halfopen_emu as SH
    a = rig_new.screen(1024, 768)
    b = SH.Rig(str(bak_path), sym).screen(1024, 768)
    assert a["tables"] == b["tables"] and _windows(a) == _windows(b)
    assert {va: [c["rect"] for c in cs] for va, cs in a["rec"].items()} == \
           {va: [c["rect"] for c in cs] for va, cs in b["rec"].items()}
    assert np.array_equal(a["build_p"], b["build_p"]) and np.array_equal(a["p"], b["p"]), "g = 16: the pristine pixels"
    _check_footprints(b)
    assert SH.census(b) == VANILLA, "the vanilla census (measured)"
