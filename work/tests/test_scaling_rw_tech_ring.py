"""HQ report F2 tech page: the research-increment ring at K = stroke_width(g), and t_dl_bmxt's snapshot bounds
(2026-10-25 W6C, law scaling_laws.rw_tech_ring_clip; helpers scripts/assemble_rw_ring.py).

Vanilla (measured on the pristine image, 1024x768, rw_ring_emu): bracket 1 fills the progress increment with the
progress art, bracket 2 fills the increment inset 1 (inc / dec 0x499366..0x499378) with the bar art -> a 1-px ring of
progress art around a bar-coloured interior, every ring pixel the colour the progress segment has on the same row.
W4B scaled the brackets' s(7) outset but left the inset at 1: the ring stayed 1 device px at every g.

1. the law (pure): K on all four sides, K = stroke_width(g), identity at g <= 16;
2. the card at every g 16..40 on the real image without art (rw_techcard_emu, the engine's call order): bracket 2's
   clip == the law, its box == the s(7) outset of it, the rect round-trips; g = 16 is the pristine image; a mutant
   with the vanilla inc / dec back fails at every g with K > 1;
3. PAINTED with the art (rw_ring_emu: load_interface + the real init_report_screen + the real ReportWin paint), at
   1024x768 (pristine, the vanilla baseline), 1600x1200 (g 25, K 2), 1920x1080 (g 22, K 1) and 3840x2160 (g 40, K 2):
   the ring measures K px on each side and every ring pixel is the progress segment's colour on its row (the stripe
   phase -- the ring's top / bottom rows used to keep the enlarge's phase: the other member at 1600 / 1080);
4. t_dl_bmxt's bound on the real image (4K): with a 64 KB plane between write-watched guards (t_rw_init_leave's 4 MB
   allocation failed), the paint writes nothing outside it -- the four header frames (bbox > 64 KB) draw natively,
   the two brackets keep the snapshot path; a mutant without the bound overruns.

Cost: each painted resolution boots the image once with its art (~5..15 s); four resolutions + the 4K bound fixture
split across xdist workers (one per test).  They are the only end-to-end proof of the ring's pixels and the bound.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn")
pytest.importorskip("pefile")

import scaling_laws as SL  # noqa: E402

GS = tuple(range(16, 41))


# ============================================================================== 1. the law
@pytest.mark.parametrize("g", tuple(range(1, 65)))
def test_scaling_rw_tech_ring_law(g):
    k = SL.stroke_width(g) if g > 16 else 1
    for clip in ((810, 122, 1096, 175), (324, 49, 438, 70), (0, 0, 3, 3)):
        l, t, r, b = clip
        assert SL.rw_tech_ring_clip(clip, g) == (l + k, t + k, r - k, b - k)
    if g > 16:
        assert k == SL.scale_px(SL.RW_TECH_RING, g)                                     # vanilla 1 x g/16
    else:
        assert SL.rw_tech_ring_clip((324, 49, 438, 70), g) == (325, 50, 437, 69)          # vanilla inc / dec


# ============================================================================== 2. the card, every g
@pytest.fixture(scope="module")
def rig(baked_exe):
    import rw_techcard_emu as RC
    return RC.CardRig(str(baked_exe), RC.RT.symtab())


@pytest.fixture(scope="module")
def rig_pristine(bak_path):
    import rw_techcard_emu as RC
    r = RC.CardRig(str(bak_path))
    assert not r.patched
    return r


@pytest.mark.parametrize("blind", (0, 1))
@pytest.mark.parametrize("g", GS)
def test_ring_clip_on_the_real_image(rig, g, blind):
    rec = rig.card(g, blind)
    assert rec.get("left") and rec["clip1"][2] > rec["clip1"][0]
    assert rec["clip2"] == SL.rw_tech_ring_clip(rec["clip1"], g)
    assert rec["bracket2"] == SL.rw_tech_bracket_rect(rec["clip2"], g)
    assert rec["after2"] == rec["clip2"]                                    # the inset back round-trips


@pytest.mark.parametrize("blind", (0, 1))
def test_ring_g16_is_pristine(rig, rig_pristine, blind):
    a, b = rig.card(16, blind), rig_pristine.card(16, blind)
    for k in ("clip1", "clip2", "bracket1", "bracket2", "after2"):
        assert a[k] == b[k], k
    assert b["clip2"] == SL.rw_tech_ring_clip(b["clip1"], 16)


@pytest.mark.parametrize("g", (25, 32, 40))
def test_mutant_vanilla_inset_fails(rig, g):
    """Kill check: the site's vanilla bytes back (inc / dec 1) -> the ring is 1 px where the law says K = 2."""
    import assemble_rw_ring as RR
    e = rig.e
    site = bytes(e.uc.mem_read(RR.RING_SITE, RR.RING_LEN))
    e.uc.mem_write(RR.RING_SITE, RR.RING_ORIG)
    e.uc.ctl_flush_tb()
    try:
        rec = rig.card(g, 0)
    finally:
        e.uc.mem_write(RR.RING_SITE, site)
        e.uc.ctl_flush_tb()
    assert SL.stroke_width(g) == 2
    assert rec["clip2"] == SL.rw_tech_ring_clip(rec["clip1"], 16) != SL.rw_tech_ring_clip(rec["clip1"], g)


# ============================================================================== 3. painted, with the art
RES = {"1024x768": (1024, 768), "1600x1200": (1600, 1200), "1920x1080": (1920, 1080), "3840x2160": (3840, 2160)}


def _check_ring(rec, g):
    import rw_ring_emu as RE
    c, c1, c2 = rec["canvas"], rec["clip1"], rec["clip2"]
    k = SL.stroke_width(g) if g > 16 else 1
    assert c2 == SL.rw_tech_ring_clip(c1, g)
    assert RE.ring_widths(c, c1, c2) == {"L": k, "R": k, "T": k, "B": k}
    l, t, r, b = c1
    seg = c[t:b, l - 1]                                    # the progress segment's column left of the increment
    ring = [(y, x) for y in range(t, b) for x in range(l, r) if not (c2[1] <= y < c2[3] and c2[0] <= x < c2[2])]
    bad = [(y, x, int(c[y, x]), int(seg[y - t])) for y, x in ring if c[y, x] != seg[y - t]]
    assert bad == [], bad[:8]                              # every ring pixel = the segment's colour on its row
    inner = set(c[c2[1]:c2[3], c2[0]:c2[2]].ravel().tolist())
    assert not inner & set(seg.tolist())                   # the interior is the bar art, not the progress art


@pytest.mark.parametrize("res", tuple(RES))
def test_ring_painted(res, baked_exe, bak_path):
    import rw_ring_emu as RE
    w, h = RES[res]
    if res == "1024x768":                                  # the vanilla baseline: the pristine image
        r = RE.PaintRig(str(bak_path), w, h)
    else:
        r = RE.PaintRig(str(baked_exe), w, h, RE.symtab())
    rec = r.paint()
    assert rec.get("left")
    g = r.g if res != "1024x768" else 16
    _check_ring(rec, g)


# ============================================================================== 4. the bound, painted at 4K
@pytest.fixture(scope="module")
def rig4k(baked_exe):
    import rw_ring_emu as RE
    return RE.PaintRig(str(baked_exe), 3840, 2160, RE.symtab())


def test_bound_on_the_real_image(rig4k):
    r = rig4k
    assert r.g == 40
    r.plane(0x10000, 0x10000)                              # the 64 KB fallback plane, t_dl_snapchk's own record
    rec = r.paint()
    assert r.guard_writes == []
    calls = rec["bmxt"]
    big = [c for c in calls if c["path"] == "native"]
    snap = [c for c in calls if c["path"] == "snapshot"]
    assert len(big) >= 4 and len(snap) == 2               # header frames native; the two research brackets thick
    for c in snap:
        x0, y0, x1, y1 = c["bbox"]
        assert (x1 - x0) * (y1 - y0) <= 0x10000
    _check_ring(rec, 40)                                   # the ring is untouched by the fallback


def test_bound_mutant_overruns(rig4k):
    """Kill check: the same paint with the bound disabled (cap forced huge) writes past the 64 KB plane."""
    rig4k.plane(0x10000, 0x7FFFFFFF)
    rig4k.paint()
    assert len(rig4k.guard_writes) > 0
