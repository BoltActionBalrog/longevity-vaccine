"""Own-top FlatButton faces (2026-10-27 wave-9 W9A; the user's decisions from the inv-preftabs investigation).

DEFECT (measured, deployed bake bb211440): thunk_btn_stripes v13 striped every FlatButton face on its PARENT canvas's
grid (btn_face_stripe_phase), so the seven PrefWin category tabs -- one face height, tops on a pitch that is no multiple
of the stripe period -- came out in two to four different looks per state (2 at 1920x1080 / 1600x1200, 4 at 2560x1440
and 4K), and vanilla's look (each face opens on its row-0 colour, AE ... EE; pressed E1 ... E0) was lost.  The Social
Engineering screen's right column (ten society rows, pitch 34 at 1600x1200) had the same split.

USER DECISIONS (2026-10-27): every PrefWin FlatButton face (the 7 tabs incl. uimod.dll's, Gamma / Restore Defaults / OK
/ Cancel / More, the audio page's Off toggles, the DLL's labels and Subscribe button) and the SE right column anchor their
stripes to their OWN top, like vanilla -- the "ownc" law: open on vanilla's row-0 colour (the pair's top member AE / E0
normally, its mate E1 when pressed), close on the other member where the height allows, the shorter end run as long as
possible.  The trade accepted: a face's stripes may run out of step with the panel's faint dark side strip beside it.
Every other FlatButton keeps v13's parent grid; g <= 16 native.

Law (scaling_laws.py): own_top_face, own_face_stripe_phase, flatbutton_draw_state, btn_face_phase.  Port: t_face_own
(assemble_face_own.py, pcave2 0x3E640), asked first by thunk_btn_stripes v14's plain fe path (g_rm_yph) and by
thunk_se_rowdraw_ph v2 (g_se_yph, the SE face restripe's vtable entry).  Unicorn parity: test_face_own_asm_parity.py.

Proof layers:
  1. laws: g <= 16 the identity; against an independent brute force over every phase for g 17..64 x h 1..120; the
     vanilla openings; the draw-state truth table; the own-top set (exactly PrefWin's children + the ten SE rows);
  2. END TO END on the real image (conftest `baked_exe`): the real PrefWin_build + uimod.dll's tab at EVERY g 17..40
     (prefwin_tabs_emu.column, no show: the buttons' canvases exist after the build) -- the 7 tabs, Gamma, Restore /
     OK / Cancel and the four Off toggles redrawn through the real FlatButton_content_draw in states 0 / 1 / 2: every
     face of one width identical, each one's stripes exactly the law's rows; and the real Social Engineering build
     (se_halfopen_emu, stop='build') at g 18 / 22 / 25 / 40 (1600x900, 1920x1080, 1600x1200, 4K): the ten society rows identical per state with the
     law's phase staged in g_rm_yph AND g_se_yph, the OK row's three buttons still on v13's parent grid.

COST (measured, full run 20261027-175022, timing_report): 129 s serial for the module.  Layer 1 ~2 s.  Layer 2: one
boot + PrefWin_build per g, 2.3-4.9 s each (24 items, ~79 s), and one boot + SocialWin_build per SE g, 7.3-22.4 s each
(4 items, ~48 s; 4K the heaviest) -- each its own xdist unit, so they split across workers (the longest single item
~22 s, inside the suite's wall).  The PrefWin sweep is every g 17..40 because that is the
user's acceptance criterion and the look depends on h = fl(20g/16) mod 2T, which takes every class; the SE column (the
same law and helper, a second caller) is proven at the standard screens, its every-g arithmetic by the Unicorn parity.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")

import scaling_laws as SL  # noqa: E402

fl = SL.popup_scale_floor
AE, EE, E0, E1 = 0xAE, 0xEE, 0xE0, 0xE1
REDRAW = 0x5D5A70                              # GraphicWin redraw (FlatButton_content_draw through the vtable)


# ============================================================================== 1. laws
def _rows(h, g, ph):
    t = SL.stripe_rows(g)
    return [((r + ph) % (2 * t)) < t for r in range(h)]


def test_law_native_identity():
    for g in range(1, 17):
        for h in range(0, 40):
            assert SL.own_face_stripe_phase(h, g) == SL.own_face_stripe_phase(h, g, True) == 0


@pytest.mark.parametrize("g", range(17, 65))
def test_law_brute_force(g):
    """An independent derivation per (g, h): the phase opens on the top member; it closes on the mate whenever any
    phase can; among those its shorter end run is the longest, then its first run; pressed is the complement."""
    t = SL.stripe_rows(g)
    p = 2 * t
    for h in range(1, 121):
        ph = SL.own_face_stripe_phase(h, g)
        rows = _rows(h, g, ph)
        assert 0 <= ph < p and rows[0], "opens on the top member (AE / E0)"

        def runs(rr):
            a = next((i for i, v in enumerate(rr) if v != rr[0]), h)
            b = next((i for i, v in enumerate(reversed(rr)) if v != rr[-1]), h)
            return a, b
        cands = [q for q in range(p) if _rows(h, g, q)[0] and not _rows(h, g, q)[-1]]
        if cands:
            assert not rows[-1], "closes on the mate"
            best = max((min(runs(_rows(h, g, q))), runs(_rows(h, g, q))[0]) for q in cands)
            a, b = runs(rows)
            assert (min(a, b), a) == best
        else:
            assert ph == 0, (g, h)
        pr = SL.own_face_stripe_phase(h, g, True)
        assert _rows(h, g, pr) == [not v for v in rows], "pressed: the mate opens, the complement of the normal rows"
    assert SL.own_face_stripe_phase(0, g) == 0 and SL.own_face_stripe_phase(0, g, True) == t


def test_law_vanilla_openings():
    """Vanilla's 20-row faces (pristine image, se_probe / prefwin probe at 1024x768): normal AE ... EE, pressed E1 ...
    E0, every row alternating -- what the law reproduces at g = 16's shape (h 20, T 1) and opens with at every g."""
    vanilla_normal = [AE if r % 2 == 0 else EE for r in range(20)]
    vanilla_pressed = [E1 if r % 2 == 0 else E0 for r in range(20)]
    for g in (17, 18, 19, 20, 21):                            # T = 1: the same alternation, any h
        h = fl(20, g)
        n = [AE if v else EE for v in _rows(h, g, SL.own_face_stripe_phase(h, g))]
        pr = [E0 if v else E1 for v in _rows(h, g, SL.own_face_stripe_phase(h, g, True))]
        assert n[:20] == vanilla_normal[:min(20, h)] and pr[:20] == vanilla_pressed[:min(20, h)]
    for g in range(22, 41):
        h = fl(20, g)
        assert _rows(h, g, SL.own_face_stripe_phase(h, g))[0] and not _rows(h, g, SL.own_face_stripe_phase(h, g, True))[0]


#: the phase the PrefWin / SE faces take (h = fl(20g/16)), pinned: the per-g table reported to the user
PHASE = {g: (1 if g in (24, 31, 34, 37, 40) else 0) for g in range(17, 41)}


def test_law_pinned_face_phases():
    assert {g: SL.own_face_stripe_phase(fl(20, g), g) for g in range(17, 41)} == PHASE


def test_law_draw_state():
    """flatbutton_draw_state == FlatButton_content_draw 0x607EC8..0x607EFC (ebp)."""
    for forced in (-7, -1, 0, 1, 2, 3, 99):
        for hover in (0, 1):
            for pa in (0, 1):
                for pb in (0, 1):
                    want = forced if 0 <= forced < 3 else (2 if (pa or pb) else hover)
                    assert SL.flatbutton_draw_state(forced, hover, pa, pb) == want


def test_law_own_top_set():
    se = [0x8B829C + i * 0xB4C for i in range(10)]
    assert se[0] == 0x8A6270 + 0x6020 + 17 * 0xB4C, "SocialWin+0x6020 + i*0xB4C, i = 17..26"
    for b in se:
        assert SL.own_top_face(b, 0x8A6270)
    for b in (se[0] - 0xB4C, se[-1] + 0xB4C, 0x8AC290):
        assert not SL.own_top_face(b, 0x8A6270)
    assert SL.own_top_face(0x12345678, 0x8578D8) and not SL.own_top_face(0x862B10, 0x862064)
    for g in (17, 25, 40):
        assert SL.btn_face_phase(0x8B7750, 0x8A6270, 45, 0, 31, g, 2) == SL.btn_face_stripe_phase(45, 0, g)
        assert SL.btn_face_phase(se[3], 0x8A6270, 45, 0, 31, g, 2) == SL.own_face_stripe_phase(31, g, True)


# ============================================================================== 2. end to end
def _face_cols(cv, k):
    """The face's left edge column (inside the corner notch) and six right-edge columns: no label / icon reaches them."""
    w = cv.shape[1]
    return np.concatenate([cv[:, k + 1:k + 2], cv[:, w - k - 7:w - k - 1]], axis=1)


def _check_rows(col, h, g, pressed):
    ph = SL.own_face_stripe_phase(h, g, pressed)
    top, mate = (E0, E1) if pressed else (AE, EE)
    want = [top if v else mate for v in _rows(h, g, ph)]
    assert [int(v) for v in col] == want, (g, pressed, [hex(int(v)) for v in col])


@pytest.fixture(scope="module")
def symtab():
    import apply_patches as ap
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


def _g_param(g):
    return pytest.param(g, id=f"g{g}", marks=pytest.mark.xdist_group(f"face_own_pref_g{g}"))


@pytest.mark.parametrize("g", [_g_param(g) for g in range(17, 41)])
def test_e2e_prefwin_faces_alike(baked_exe, symtab, g):
    os.environ.setdefault("SMACX_EXE_NAME", "terranx_PRACX.exe")
    import image_emu as IE
    import prefwin_halfopen_emu as PH
    import prefwin_tabs_emu as PT
    w, h = -(-1024 * g // 16), -(-768 * g // 16)
    staged = []
    lo, fe = symtab["thunk_btn_stripes"], symtab["thunk_fe_pair_remap"]

    def on_fe(e):
        ra = e.r32(e.reg(IE.UC_X86_REG_ESP))
        if lo <= ra < lo + 0x200:
            staged.append((e.r32(symtab["g_fe_dst"]) - 0x444, e.s32(symtab["g_rm_yph"])))
    boot = IE.boot

    def hooked(*a, **k):
        e = boot(*a, **k)
        e.observe(fe, on_fe)
        return e
    IE.boot = hooked
    try:
        c = PT.column(str(baked_exe), w, h, dll=True, show=False)
    finally:
        IE.boot = boot
    assert c.g == g
    e, k, fh = c.e, SL.btn_corner_notch(g), fl(20, g)
    wide = list(c.rows) + [PT.GAMMA] + list(PT.BOTTOM)         # the 214-wide faces: 7 tabs, Gamma, Restore/OK/Cancel
    for st in (0, 1, 2):
        cols, lefts = set(), set()
        for a in wide + list(PH.LABELS):
            e.w32(a + 0xAB8, st)
            staged.clear()
            e.call(REDRAW, ecx=a, count=400_000_000)
            cv = IE.canvas_of(e, a)
            assert cv.shape[0] == fh
            assert staged and all(s == (a, SL.own_face_stripe_phase(fh, g, st == 2)) for s in staged), (hex(a), staged)
            lefts.add(cv[:, k + 1].tobytes())
            if a in wide:
                cols.add(_face_cols(cv, k).tobytes())
            if st != 1:                                          # hover: solid E0 edge rows over the pair (vanilla's)
                _check_rows(cv[:, k + 1], fh, g, st == 2)
        assert len(cols) == 1 and len(lefts) == 1, (g, st, len(cols), len(lefts))


SE_G = (18, 22, 25, 40)


@pytest.mark.parametrize("g", [pytest.param(g, id=f"g{g}", marks=pytest.mark.xdist_group(f"face_own_se_g{g}"))
                               for g in SE_G])
def test_e2e_se_column_alike(baked_exe, symtab, g):
    os.environ.setdefault("SMACX_EXE_NAME", "terranx_PRACX.exe")
    import image_emu as IE
    import se_halfopen_emu as SH
    rig = SH.Rig(str(baked_exe), symtab)
    e = rig.e
    rd, fe, lo = symtab["thunk_se_rowdraw"], symtab["thunk_fe_pair_remap"], symtab["thunk_btn_stripes"]
    log = []
    e.observe(rd, lambda e: log.append(("se", e.r32(e.reg(IE.UC_X86_REG_ESP) + 4), e.s32(symtab["g_se_yph"]))))

    def on_fe(e):
        if lo <= e.r32(e.reg(IE.UC_X86_REG_ESP)) < lo + 0x200:
            log.append(("fe", e.r32(symtab["g_fe_dst"]) - 0x444, e.s32(symtab["g_rm_yph"])))
    e.observe(fe, on_fe)
    w, h = SH.screen_for(g)
    r = rig.screen(w, h, stop="build")
    assert r["g"] == g
    btns = [SH.SEW + 0x6020 + i * 0xB4C for i in range(35)]
    col, okrow = btns[17:27], [btns[16], btns[27], btns[28]]
    k = SL.btn_corner_notch(g)
    for st in (0, 1, 2):
        faces = set()
        for a in col + okrow:
            e.w32(a + 0xAB8, st)
            log.clear()
            e.call(REDRAW, ecx=a, count=400_000_000)
            cv = IE.canvas_of(e, a)
            fh = cv.shape[0]
            top = e.s32(a + 0x140) + e.s32(a + 0x150)
            want = (SL.own_face_stripe_phase(fh, g, st == 2) if a in col else SL.btn_face_stripe_phase(top, 0, g))
            assert {x[0] for x in log} == {"se", "fe"}, log
            for kind, btn, ph in log:
                assert btn == a
                assert (ph if kind == "se" else ph % SL.stripe_period(g)) == want, (hex(a), kind, ph, want, st)
            if a in col:
                faces.add(_face_cols(cv, k).tobytes())
                if st != 1:
                    _check_rows(cv[:, k + 1], fh, g, st == 2)
        assert len(faces) == 1, (g, st)
