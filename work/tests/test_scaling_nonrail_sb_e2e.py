"""Armed NON-RAIL scrollbars are one symmetric assembly again, end to end on the real image (W10S F56, 2026-10-27; the
user-approved fix of a regression from vanilla).

Vanilla (the pristine survey at 1024x768): every ScrollBar's arrow plates and thumb grip share ONE span centred in the
bar, 1 | 1.  Armed at g > 16 the bars outside the rail family rounded on their own -- the grip 22 at 1 | 2 at g 20, the
plates 27 vs the grip 28 at g 25, 4K plate 45 at 2 | 3 / grip 45 at 3 | 2 (scratchpad w9C\\f53survey, the Prefs
sliders, the MP lobby chat, the base FACILITIES list).  Laws (scaling_laws.py): sb_nonrail_grip_rect (rail_grip_span on
both axes of the thumb rect), sb_nonrail_arrow v5 (the native plate square on the same span on both axes, a plain
NN of it: the deployed keyed stretch's centre-NN with the mirror-exact tie-break -- user decision 2026-10-27: centring
only), sb_nonrail_gate.

On the REAL image (nonrail_sb_emu.py; every engine function and cave thunk running for real, in the engine's order:
the bar's own draw slot -> thunk_pref_sbzoom's bracket -> ScrollBar_draw -> the arrows through thunk_btn_shrink /
thunk_btn_2dscale -> t_btn_edgeprobe -> t_rsb_zoom -> t_nrs_zoom, the grip through thunk_sb_thumb -> t_rsb_grip ->
t_nrs_grip), at g 17 / 18 / 19 / 20 / 22 / 23 / 24 / 25 / 28 / 30 / 32 / 35 / 36 / 39 / 40 -- every standard resolution
at that resolution (1600x900, 1280x1024, 1920x1080, 1600x1200, 2560x1440, 3840x2160), the 2x point, and the g where
the deployed centre-NN's tie broke the up / down mirror (19 / 30 / 35 / 23 / 39); the others at 64g x 48g; every g
17..40 is the unit layer's:
  * the four Prefs Audio / Visual sliders (horizontal) and a uimod.dll-style Longevity slider (the engine ScrollBar
    ctor / init with the exe's slider statics, a PRIVATE vtable copy, named by g_dll_pref_slider: prefs.cpp's recipe);
  * the base screen's FACILITIES bar (vertical, the 12-px class);
  * the MP lobby's chat bar (vertical, the 20-px class);
every relation of nonrail_sb_emu.check holds: both arrows n x n at the bar's ends (their hit rects ARE the drawn
squares), each arrow the law's image of its own native render, up plate == down plate == grip == the law span across
the bar and centred, the down arrow the mirror of the up arrow along the bar, the grip on sb_nonrail_grip_rect of the
drawn thumb rect (centred both ways), the press zone [+0xA4C..] == the drawn thumb rect.  In every state (idle /
hover / pressed) and for every bar: each arrow repainted through the DEPLOYED path (t_rsb_zoom's tail put back on
thunk_btn_bandstripe) is stretch_nn_src of its whole native render and through v5 the law's plain NN of the native
plate at its new size (g = 32: the native render doubled); the up / down faces and inner triangles are mirror images
along the bar wherever vanilla's are (_mirror); and the thumb tracks the value (every value of the bar's range at g 25
-- 128 / 129 values for the sliders / FACILITIES, 0..40 given to the lobby rig's empty chat bar --, both ends, their
neighbours, a third and the middle at the other g).  g = 16: the bars' canvases are byte-identical to the pristine
.bak's (FACILITIES: g 16 forced on the same 4K boot against the .bak's 1024x768 bar).

COST (measured serially, the module alone: ~126 s in 7 items): the four slider items 10..16 s each (one boot ~3 s, a
PrefWin_build per g ~1..3 s, the 128-value sweep at g 25), the FACILITIES item ~53 s (one boot + the 4K base screen ~35
s shared by the g = 16 identity and every forced g, ~0.6 s each, plus the .bak's 1024x768 base screen ~12 s), the lobby
item ~6 s, the slider / lobby g = 16 identity item ~10 s (two boots).  Every item pays only its own boot and splits
cleanly across xdist workers.  Every relation lives in the composition of the engine's own scrollbar code with four
cave thunks and thunk_btn_stripes' pass after them; the unit layer (tests/test_nonrail_sb_asm_parity.py) proves each
thunk against its law at every g, this one proves the real bars reach them and nothing downstream undoes them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("pefile", reason="pefile absent")

import image_emu as IE  # noqa: E402
import nonrail_sb_emu as N  # noqa: E402

SCREENS = N.sweep_screens()
#: the tier representatives (the 2x point 32, 4K), every standard resolution's g (18 1600x900, 20 1280x1024, 22
#: 1920x1080, 25 1600x1200, 30 2560x1440, 40 3840x2160) and the g where a centre-NN tie breaks the up / down mirror
#: (19 / 30 / 35 for the 20-px triangles, 23 / 39 for the 12-px glyphs, audit w10S v4); every other g is the unit layer's
GS = (17, 18, 19, 20, 22, 23, 24, 25, 28, 30, 32, 35, 36, 39, 40)   # + 19 / 23 / 30 / 35 / 39: centre-NN's mirror ties
SLIDER_CHUNKS = ((17, 18, 19, 20), (22, 23, 24, 25), (28, 30, 32, 35), (36, 39, 40))
EVERY_VALUE = (25,)                     # the full value sweep (1600x1200); elsewhere both ends, neighbours, a third, the middle
STATES = ("hover", "press", "idle")
LOBBY_RANGE = 40                        # the lobby rig's chat log is empty (range 0..0): its bar is given 0..40 to track


_SYM = {}


def _sym():
    if not _SYM:
        import mirror_pairs_emu as MP
        _SYM.update(MP.symtab())
    return _SYM


def _retarget(e, to_deployed):
    """Point t_rsb_zoom's non-rail tail back at thunk_btn_bandstripe (the deployed 8948efe9 path) or at t_nrs_zoom."""
    sym = _sym()
    za, nrs, band = sym["t_rsb_zoom"], sym["t_nrs_zoom"], sym["thunk_btn_bandstripe"]
    blob = bytes(e.uc.mem_read(za, 0x200))
    old, new = (nrs, band) if to_deployed else (band, nrs)
    pat = b"\x68" + old.to_bytes(4, "little") + b"\xC3"
    i = blob.rfind(pat)
    assert i >= 0 and blob.rfind(b"\x68" + new.to_bytes(4, "little") + b"\xC3") < i
    e.uc.mem_write(za + i + 1, new.to_bytes(4, "little"))
    e.uc.ctl_remove_cache(za & ~0xFFF, (za + 0x1000) & ~0xFFF)


TRI = {"idle": (0xF0, 0xB9), "hover": (0xEF, 0xA2), "press": (0xE0, 0xE1, 0xE2)}   # the 20-px arrows' triangle


def _deployed_scaling(e, sb, probe, g):
    """v5 (user decision 2026-10-27, centring only): the faces are a plain NN of the native art -- the deployed
    sampling with the mirror-exact tie-break.  Each arrow is repainted in every state through the DEPLOYED path
    (t_rsb_zoom's tail put back on thunk_btn_bandstripe -> thunk_keyed_stretch_blit): that face must be stretch_nn_src
    of the WHOLE native render (the measured engine sampling; pressed read with E1 as E0, thunk_btn_stripes' pass);
    repainted through v5 it must be the law's plain NN of the native PLATE on the law square (mirror_nn_src: the same
    samples but at exact ties).  At g = 32 (exactly 2x, no ties) the v5 idle face is the native render doubled."""
    bad = []
    for off in (N.SB_UP, N.SB_DN):
        for st in STATES:
            _retarget(e, True)
            try:
                dep = N.redraw_arrow(e, sb + off, st, probe)
                nat = probe.native.get(sb + off)
            finally:
                _retarget(e, False)
            if nat is None:
                bad.append((hex(off), st, "no native on the deployed path"))
                continue
            nat = np.array(nat, np.uint8)
            m = [N.SL.stretch_nn_src(i, nat.shape[0], dep.shape[0]) for i in range(dep.shape[0])]
            want = nat[np.ix_(m, m)]
            if st == "press":
                dep, want = np.where(dep == E1, E0, dep), np.where(want == E1, E0, want)
            if (dep != want).any():
                bad.append((hex(off), st, "the deployed path is not stretch_nn_src of the native"))
            ours = N.redraw_arrow(e, sb + off, st, probe)
            nat2 = probe.native.get(sb + off)
            law = N.SL.sb_nonrail_arrow(nat2, len(nat2), len(nat2), ours.shape[0], ours.shape[0], g)
            law = None if law is None else np.array(law, np.uint8)
            if st == "press" and law is not None:
                ours, law = np.where(ours == E1, E0, ours), np.where(law == E1, E0, law)
            if law is None or (law != ours).any():
                bad.append((hex(off), st, "v5 face != the plain NN of the plate at its new size"))
            if g == 32 and st == "idle" and (ours.shape != (2 * nat.shape[0],) * 2 or
                                             (ours != np.kron(nat, np.ones((2, 2), np.uint8))).any()):
                bad.append((hex(off), "g32 face != the native doubled"))
    return bad


def _along(mask, vert):
    v = mask.any(1) if vert else mask.any(0)
    i = np.nonzero(v)[0]
    return None if not len(i) else (int(i[0]), int(i[-1]) + 1 - int(i[0]), len(v) - int(i[-1]) - 1)


def _mirror(e, sb, probe, g, vert, triangle=True):
    """The up / down arrows are mirror images along the bar wherever vanilla's are: the whole face (non-key) and the
    inner triangle (the state's triangle colours), each in every state -- (lead, size, trail) of the down arrow ==
    (trail, size, lead) of the up arrow whenever the native renders satisfy it."""
    bad = []
    for st in STATES:
        faces, nats = {}, {}
        for nm, off in (("up", N.SB_UP), ("dn", N.SB_DN)):
            faces[nm] = N.redraw_arrow(e, sb + off, st, probe)
            nats[nm] = np.array(probe.native.get(sb + off), np.uint8)
        sels = [("face", lambda a: a != N.KEY)] + ([("triangle", lambda a, st=st: np.isin(a, TRI[st]))] if triangle else [])
        for el, sel in sels:
            nu, nd = _along(sel(nats["up"]), vert), _along(sel(nats["dn"]), vert)
            if nu is None or nd is None or nu != nd[::-1]:
                continue                                   # not a mirror in vanilla either (the idle triangles)
            u, d = _along(sel(faces["up"]), vert), _along(sel(faces["dn"]), vert)
            if u is None or d is None or u != d[::-1]:
                bad.append((st, el, "up / down not mirrored", u, d))
    return bad


def _values(e, sb, g):
    """Every value of the bar's range at the EVERY_VALUE g; elsewhere both ends, their neighbours, a third, the middle."""
    lo, hi = e.s32(sb + 0xA20), e.s32(sb + 0xA24)
    if g in EVERY_VALUE:
        return None
    return sorted({v for v in (lo, lo + 1, lo + (hi - lo) // 3, (lo + hi) // 2, hi - 1, hi) if lo <= v <= hi})


E1, E0 = 0xE1, 0xE0                     # the pressed face's E0 / E1: thunk_btn_stripes re-stripes them by rows


@pytest.mark.parametrize("gs", SLIDER_CHUNKS, ids=lambda gs: f"g{gs[0]}-{gs[-1]}")
def test_prefs_sliders_and_the_dll_slider(baked_exe, gs):
    rig = N.PrefRig(str(baked_exe))
    e, probe = rig.e, rig.probe
    bad = []
    for want_g in gs:
        g = rig.screen(*SCREENS[want_g])
        assert g == want_g, (SCREENS[want_g], g)
        dll = N.dll_slider(rig)
        for sb in rig.bars + (dll,):
            N.draw(e, sb, probe)
            m = N.measure(e, sb, probe, g)
            if m["vert"]:
                bad.append((g, hex(sb), "not horizontal"))
            bad += [(g, hex(sb)) + f for f in N.check(m, g)]
        for name, sb in (("slider0", rig.bars[0]), ("dll", dll)):
            bad += [(g, name) + f for f in _deployed_scaling(e, sb, probe, g)]
            bad += [(g, name) + f for f in _mirror(e, sb, probe, g, vert=False)]
        for sb in (rig.bars[0], dll):
            tb, _pos = N.track(e, sb, probe, g, _values(e, sb, g))
            bad += [(g, hex(sb)) + f for f in tb]
    assert not bad, bad[:8]


def test_base_facilities_bar(baked_exe, bak_path):
    """One 4K base screen, every GS g forced on it (the facilities painter re-attaches the bar at that g); g = 16
    forced on the same boot must equal the pristine .bak's bar at 1024x768, byte for byte."""
    rig = N.BaseRig(str(baked_exe))
    e, probe, sb = rig.e, rig.probe, rig.bars[0]
    assert rig.g0 == 40
    bad = []
    assert rig.force(16) == 16
    N.draw(e, sb, probe)
    ours16 = _canvases(e, rig.bars)
    pristine = N.BaseRig(str(bak_path), 1024, 768)
    assert pristine.g0 == 16
    N.draw(pristine.e, pristine.bars[0], pristine.probe)
    for a, b in zip(ours16, _canvases(pristine.e, pristine.bars)):
        if a.shape != b.shape or (a != b).any():
            bad.append((16, "not pristine"))
    del pristine
    for g in GS:
        assert rig.force(g) == g
        N.draw(e, sb, probe)
        m = N.measure(e, sb, probe, g)
        if not m["vert"] or m["n"] != (12 * g) >> 4:
            bad.append((g, "bar", m["vert"], m["n"]))
        bad += [(g,) + f for f in N.check(m, g)]
        bad += [(g,) + f for f in _deployed_scaling(e, sb, probe, g)]
        bad += [(g,) + f for f in _mirror(e, sb, probe, g, vert=True, triangle=False)]
        bad += [(g,) + f for f in N.track(e, sb, probe, g, _values(e, sb, g))[0]]
    assert not bad, bad[:8]


def test_lobby_chat_bar(baked_exe):
    rig = N.LobbyRig(str(baked_exe))
    e, probe = rig.e, rig.probe
    bad = []
    for g in GS:
        rig.build(g)
        bars = rig.bars()
        assert len(bars) == 1, bars
        sb = bars[0]
        N.draw(e, sb, probe)
        m = N.measure(e, sb, probe, g)
        if not m["vert"] or m["n"] != (20 * g) >> 4:
            bad.append((g, "bar", m["vert"], m["n"]))
        bad += [(g,) + f for f in N.check(m, g)]
        bad += [(g,) + f for f in _deployed_scaling(e, sb, probe, g)]
        bad += [(g,) + f for f in _mirror(e, sb, probe, g, vert=True)]
        e.call(N.SET_RANGE, ecx=sb, args=(0, LOBBY_RANGE), count=50_000_000)
        tb, pos = N.track(e, sb, probe, g, _values(e, sb, g))
        bad += [(g,) + f for f in tb]
        if len(set(pos)) < 3:
            bad.append((g, "the lobby thumb did not move", pos))
    assert not bad, bad[:8]


def _canvases(e, sbs):
    return [IE.canvas_of(e, sb + off) for sb in sbs for off in (0, N.SB_UP, N.SB_DN)]


def test_g16_sliders_and_lobby_are_pristine(baked_exe, bak_path):
    """1024x768: the four sliders (drawn through their armed slot) and the lobby chat bar equal the pristine .bak's,
    byte for byte -- every W10S thunk is gated off at g <= 16."""
    out = []
    for exe in (baked_exe, bak_path):
        rig = N.PrefRig(str(exe))
        assert rig.screen(1024, 768) == 16
        for sb in rig.bars:
            N.draw(rig.e, sb, rig.probe)
        lob = N.LobbyRig(str(exe))
        lob.build(16)
        sbs = lob.bars()
        for sb in sbs:
            N.draw(lob.e, sb, lob.probe)
        out.append(_canvases(rig.e, rig.bars) + _canvases(lob.e, sbs))
    assert len(out[0]) == len(out[1]) == 15
    for a, b in zip(*out):
        assert a.shape == b.shape and (a == b).all()
