"""F42 remainder (2026-10-25 wave-6 W6A; v2 the user's mirror rule): the PREFERENCES window's chrome on its half-open
rects, the backdrop rail to rail, every other frame mirrored about its content.

DEFECT (measured, deployed bake 36698ad5 / e168b0a1): the PrefWin window was floor(778g/16) wide, so the right slide
rails' double-floor re-anchor (rail_right_strip_x) landed 1..4 px LEFT of the backdrop's right edge fl(723g/16): the
rails covered its right border entirely at 1280x1024 / 1600x900 / 1920x1080 / 1600x1200 / 2560x1440 and left 1 px of 2
at 4K; at odd g the backdrop's left edge fl(23g/16) sat one px right of the left rails (a see-through column).  Every
frame was band-mapped one px past its native extent (inclusive), and each edge floored on its own, so the vanilla-equal
channel pairs (backdrop -> inner, inner -> panels, panel -> content, slider frame -> labels) came out 1 px apart in
either direction depending on the floor phase.  v1 trimmed every frame (R-1 / B-1), which fixed some pairs and broke
others (audit-w6A); the user ruled: the mirror rule first.

Laws (scaling_laws.py): prefwin_window_wh (w = CEIL(778g/16): the rails land on fl(723g/16)), prefwin_layout /
pref_chain_split (each axis a chain of three channels between the backdrop's border and the fixed content; two mirrored,
the floors' slack in ONE place: the left vs right panel -> content channel horizontally, backdrop -> inner at the bottom
vertically; the slider frames' bottom mirrored about their label column; v3: the split scores the panel gap and the
slider frames' bottom gaps too -- fewest spacings > 1 px off vanilla x g/16, then the smallest worst error),
pref_frame_draw_rect / pref_backdrop_draw_rect.
Ports (assemble_prefwin.emit_w6a): thunk_pref_gwinit (self arm w ceil), thunk_pref_boxframe v3 (jmp t_pref_frame; the
entry uimod.dll's Longevity page calls), t_pref_bd (the backdrop site 0x48FB19), t_pref_frame + g_pref_frame_keys /
g_pref_frame_tbl (the layout table, emitted from the law) in W6A's region pcave2 0x3E000..0x3EFFF.

Proof layers (conftest `baked_exe`):
  1. laws: the rail anchor == the backdrop's R (g 17..256); every vanilla-mirrored pair equal (g 17..40) with the slack
     exactly where the law puts it; every spacing (chain channels, panel gap, slider-frame bottom gaps) bounded against
     vanilla x g/16 and the split optimal for its objective; g = 16 the native rects;
  2. Unicorn on the shipped bytes: the bytes are the assembler's; the sites; t_pref_frame / the boxframe entry / t_pref_bd
     / the gwinit self arm == the laws for g 1..64 and every frame (plus a rect no table row matches);
  3. END TO END (prefwin_halfopen_emu.py): the real MainWin_build (the slide-rail art) + PrefWin_build + PrefWin_show
     (page 4) at 1024 / g 22 / g 25: every frame's drawn footprint == the law, the backdrop's borders K | K against the
     REAL rails and abutting them, every measured channel == the law's, g = 16 the pristine pixels.  The census of every
     pair at g 17..40 and the standard screens is the W6A v2 report's table.

COST: layers 1-2 cheap.  Layer 3: one boot + MainWin_build + the window per item (~10 s at 1024, ~30-40 s at g 22 / 25,
in parallel under xdist); g = 40 (~55 s) is NOT an e2e item -- its table row and thunk path are pinned by layer 2.
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
pytest.importorskip("keystone", reason="keystone absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_prefwin as AP  # noqa: E402
import scaling_laws as SL  # noqa: E402

E2E_G = (16, 22, 25)
STACK, SP0 = 0x10000000, 0x10080000
RECT = STACK + 0x1000
PARAMS = STACK + 0x2000
STUBS = {AP.BBS: "native", AP.HOLLOW_FLAT: "hollow_flat", AP.DEVFILL: "devfill", AP.GWINIT_RESUME: "resume"}
FRAMES = tuple(n for n in SL.PREF_FRAME_NATIVE if n != "backdrop")
G_RANGE = range(SL.NATIVE_G + 1, SL.G_MAX + 1)


def K(g):
    return SL.stroke_width(g) if g > 16 else 1


def fl(v, g):
    return SL.popup_scale_floor(v, g) if g > 16 else v


def law_channels(g):
    """Every vanilla-mirrored PrefWin channel pair from the law's rects (inclusive) and the content (floor-scaled child
    windows, half-open) -- the same formulas the e2e measures on the real pixels."""
    lay = SL.prefwin_layout(g)
    if g <= 16:
        lay = {n: (r[0], r[1], r[2] - 1, r[3] - 1) for n, r in lay.items() if isinstance(r, tuple)}
    k = K(g)
    bd, inn, lp, rp, sf, dl = (lay[n] for n in ("backdrop", "inner", "lpanel", "rpanel", "sframe", "dll"))
    bl, br = fl(33, g), fl(33, g) + fl(214, g)
    bt, bb = fl(10, g), fl(360, g) + fl(20, g)
    ll, lr = fl(256, g), fl(256, g) + fl(457, g)
    lab_t, lab_b = fl(290, g), fl(356, g) + fl(20, g)
    lab_l, sl_r = fl(259, g), fl(382, g) + fl(328, g)
    return {"backdrop>inner L|R": (inn[0] - (bd[0] + k), (bd[2] - k + 1) - inn[2] - 1),
            "backdrop>inner T|B": (inn[1] - (bd[1] + k), (bd[3] - k + 1) - inn[3] - 1),
            "inner>panels L|R": (lp[0] - (inn[0] + k), (inn[2] - k + 1) - rp[2] - 1),
            "inner>left panel T|B": (lp[1] - (inn[1] + k), (inn[3] - k + 1) - lp[3] - 1),
            "inner>right panel T|B": (rp[1] - (inn[1] + k), (inn[3] - k + 1) - rp[3] - 1),
            "left panel>buttons L|R": (bl - (lp[0] + k), (lp[2] - k + 1) - br),
            "left panel>buttons T|B": (bt - (lp[1] + k), (lp[3] - k + 1) - bb),
            "right panel>list L|R": (ll - (rp[0] + k), (rp[2] - k + 1) - lr),
            "right panel>list T | More B": (bt - (rp[1] + k), (rp[3] - k + 1) - bb),
            "~panel gap": rp[0] - lp[2] - 1,
            "right panel>slider frame L|R": (sf[0] - (rp[0] + k), (rp[2] - k + 1) - sf[2] - 1),
            "slider frame>labels T|B": (lab_t - (sf[1] + k), (sf[3] - k + 1) - lab_b),
            "slider frame>labels L | sliders R": (lab_l - (sf[0] + k), (sf[2] - k + 1) - sl_r),
            "right panel>Longevity frame L|R": (dl[0] - (rp[0] + k), (rp[2] - k + 1) - dl[2] - 1),
            "Longevity frame>labels T|B": (fl(334, g) - (dl[1] + k), (dl[3] - k + 1) - lab_b),
            "right panel>slider frame B": (rp[3] - k + 1) - sf[3] - 1,
            "right panel>Longevity frame B": (rp[3] - k + 1) - dl[3] - 1}


# ============================================================================== 1. laws
@pytest.mark.parametrize("g", range(17, 257))
def test_law_rails_land_on_the_backdrop_edges(g):
    w, h = SL.prefwin_window_wh(g)
    assert (w, h) == ((778 * g + 15) >> 4, (390 * g) >> 4)
    assert SL.rail_right_strip_x(w, w - SL.RAIL_INNER_RIGHT_OFF, g) == (723 * g) >> 4, "the right rail's first column"
    l, _t, r, _b = SL.pref_frame_draw_rect(SL.PREFWIN_BACKDROP_SITE, SL.PREF_FRAME_NATIVE["backdrop"], g)
    assert l == SL.rail_left_extent(g) and r == ((723 * g) >> 4) - 1, "border on [rail_l, rail_r): K | K"


def test_law_native_identity():
    assert SL.prefwin_window_wh(16) == (778, 390)
    lay = SL.prefwin_layout(16)
    for name, rect in SL.PREF_FRAME_NATIVE.items():
        assert lay[name] == rect
        for site in SL.PREF_FRAME_SITES:
            assert SL.pref_frame_draw_rect(site, rect, 16) == rect
    ch = law_channels(16)
    assert ch == {"backdrop>inner L|R": (3, 3), "backdrop>inner T|B": (3, 3), "inner>panels L|R": (2, 2),
                  "inner>left panel T|B": (2, 2), "inner>right panel T|B": (2, 2), "left panel>buttons L|R": (2, 2),
                  "left panel>buttons T|B": (2, 2), "right panel>list L|R": (2, 2),
                  "right panel>list T | More B": (2, 2), "~panel gap": 3, "right panel>slider frame L|R": (2, 2),
                  "slider frame>labels T|B": (2, 2), "slider frame>labels L | sliders R": (2, 2),
                  "right panel>Longevity frame L|R": (2, 2), "Longevity frame>labels T|B": (2, 2),
                  "right panel>slider frame B": 3, "right panel>Longevity frame B": 3}, \
        "the vanilla census (pristine image, prefwin_halfopen_emu at 1024x768): every pair mirrored"


@pytest.mark.parametrize("g", G_RANGE)
def test_law_mirror_rule(g):
    """Every frame-owned pair equal; the slack only in its one place per axis (left panel -> buttons vs right panel ->
    list horizontally; backdrop -> inner B vertically); the content-fixed pair (labels L vs sliders R) is the only other
    unequal one."""
    ch = law_channels(g)
    lay = SL.prefwin_layout(g)
    for name in ("backdrop>inner L|R", "inner>panels L|R", "inner>left panel T|B", "inner>right panel T|B",
                 "left panel>buttons L|R", "left panel>buttons T|B", "right panel>list L|R",
                 "right panel>list T | More B", "right panel>slider frame L|R", "slider frame>labels T|B",
                 "right panel>Longevity frame L|R", "Longevity frame>labels T|B"):
        assert ch[name][0] == ch[name][1], (g, name, ch[name])
    assert ch["backdrop>inner L|R"] == (lay["a_h"],) * 2 and ch["inner>panels L|R"] == (lay["b_h"],) * 2
    assert ch["left panel>buttons L|R"] == (lay["c_lp"],) * 2 and ch["right panel>list L|R"] == (lay["c_rp"],) * 2
    assert ch["backdrop>inner T|B"] == (lay["a_t"], lay["a_b"]) and lay["a_b"] - lay["a_t"] in (0, 1, 2)
    assert ch["inner>left panel T|B"] == ch["inner>right panel T|B"] == (lay["b_v"],) * 2
    assert ch["left panel>buttons T|B"] == ch["right panel>list T | More B"] == (lay["c_v"],) * 2
    assert abs(lay["c_lp"] - lay["c_rp"]) <= 1, "the horizontal slack: one px between the two panels, at most"
    labs = ch["slider frame>labels L | sliders R"]
    assert labs[1] - labs[0] == (fl(256, g) + fl(457, g) - fl(382, g) - fl(328, g)) - (fl(259, g) - fl(256, g)), \
        "the labels / sliders' own floor asymmetry inside the page list's columns, nothing added"
    assert ch["~panel gap"] >= 3 and min(min(v) if isinstance(v, tuple) else v for v in ch.values()) >= 0


#: the spacings pref_chain_split sets (law_channels name, which value, vanilla px): each counted ONCE (a mirrored pair is
#: one spacing; the two panels' inner -> panel T|B are the same b_v)
SPACINGS = (("backdrop>inner L|R", 0, 3), ("backdrop>inner T|B", 0, 3), ("backdrop>inner T|B", 1, 3),
            ("inner>panels L|R", 0, 2), ("inner>left panel T|B", 0, 2), ("left panel>buttons L|R", 0, 2),
            ("right panel>list L|R", 0, 2), ("left panel>buttons T|B", 0, 2), ("~panel gap", None, 3),
            ("right panel>slider frame B", None, 3), ("right panel>Longevity frame B", None, 3))


def spacing_errors(g):
    """{spacing: |value - vanilla x g/16|} in sixteenths of a px."""
    ch = law_channels(g)
    return {(n, i): abs(16 * (ch[n] if i is None else ch[n][i]) - w * g) for n, i, w in SPACINGS}


#: the census of the law, pinned: g -> (spacings > 1 px off vanilla x g/16, broken cross-axis relations, worst error
#: in 16ths of a px).  v4 (the user's 2560x1440 decision, symmetry beats 1-px exactness): g 23 / 30 / 39 trade a
#: larger worst error for fewer broken relations (v3: 23 (3, 4, 18), 30 (1, 3, 20), 39 (3, 4, 18)).
CENSUS = {17: (1, 2, 18), 18: (0, 1, 12), 19: (1, 2, 23), 20: (1, 1, 20), 21: (1, 1, 22), 22: (0, 1, 14),
          23: (3, 1, 27), 24: (0, 0, 16), 25: (2, 1, 18), 26: (1, 0, 18), 27: (1, 1, 17), 28: (0, 1, 12),
          29: (0, 0, 10), 30: (1, 1, 22), 31: (2, 0, 19), 32: (0, 0, 0), 33: (1, 2, 18), 34: (0, 1, 12),
          35: (1, 2, 23), 36: (1, 1, 20), 37: (1, 1, 22), 38: (0, 1, 14), 39: (3, 1, 27), 40: (0, 0, 16)}


def cross_breaks(g):
    """The vanilla-equal cross-axis channel pairs the law leaves unequal (a_h | a_t, b_h | b_v, c_lp | c_v, c_rp | c_v)."""
    lay = SL.prefwin_layout(g)
    return ((lay["a_h"] != lay["a_t"]) + (lay["b_h"] != lay["b_v"]) + (lay["c_lp"] != lay["c_v"])
            + (lay["c_rp"] != lay["c_v"]))


@pytest.mark.parametrize("g", G_RANGE)
def test_law_spacing_census(g):
    """Every spacing the split sets -- the chain channels AND the panel gap and the two slider-frame bottom gaps (v2
    left those unscored: 4K's gap 9 vs 7.5, audit-w6A v2) -- against vanilla x g/16: at most 3 spacings more than 1 px
    off at any g, at most 2 cross-axis relations broken, the worst <= 1.69 px; at the standard screens at most 2 off,
    at most 1 relation broken, the worst <= 1.375 px (4K: none off, none broken, <= 1 px)."""
    err = spacing_errors(g)
    n, worst = sum(e > 16 for e in err.values()), max(err.values())
    c = cross_breaks(g)
    assert (n, c, worst) == CENSUS[g], (g, n, c, worst, {k: v for k, v in err.items() if v > 16})
    assert n <= 3 and c <= 2 and worst <= 27
    if g in (18, 20, 22, 25, 30, 40):
        assert n <= 2 and c <= 1 and worst <= 22
    assert g != 40 or (n, c, worst) == (0, 0, 16)
    assert g != 30 or SL.pref_chain_split(30) == ((5, 4, 3, 4), (5, 4, 3, 6)), "the user's 2560x1440 choice"


@pytest.mark.parametrize("g", G_RANGE)
def test_law_gaps_bounded(g):
    """The derived gaps -- the panel gap (vanilla 3) and each slider frame's bottom gap to the right panel (vanilla 3)
    -- never under 1 px (no stroke on a stroke); the slider-frame gaps within 1.25 px of vanilla x g/16 at every g, the
    panel gap within 1.69 px (v4: g 23 / 39 trade it for fewer broken relations) and within 1.375 px at the standard
    screens (2560x1440: the user's choice, 7 vs 5.62)."""
    ch = law_channels(g)
    for name in ("right panel>slider frame B", "right panel>Longevity frame B"):
        assert ch[name] >= 1 and abs(16 * ch[name] - 3 * g) <= 20, (g, name, ch[name])
    gap = ch["~panel gap"]
    assert gap >= 1 and abs(16 * gap - 3 * g) <= (22 if g in (18, 20, 22, 25, 30, 40) else 27), (g, gap)


@pytest.mark.parametrize("g", G_RANGE)
def test_law_split_is_optimal(g):
    """No other mirrored split is better under the law's order -- fewer spacings > 1 px off, then fewer broken
    cross-axis relations, then a smaller worst error (an independent brute force over the census, every mirrored
    assignment re-derived from the budgets)."""
    err = spacing_errors(g)
    key = (sum(e > 16 for e in err.values()), cross_breaks(g), max(err.values()))
    lay = SL.prefwin_layout(g)
    k = lay["K"]

    def f(v):
        return (v * g) >> 4
    s_l = f(33) - (SL.rail_left_extent(g) + k) - 2 * k
    s_r = (f(723) - k) - (f(256) + f(457)) - 2 * k
    s_t, s_b = f(10) - 3 * k, (f(390) - k) - (f(360) + f(20)) - 2 * k
    gap0 = f(256) - (f(33) + f(214)) - 2 * k
    bot = f(360) + f(20)
    sfb = [bot - (f(356) + f(20) + (f(t + 3) - f(t) - k) + k) for t in (287, 331)]
    hs, vs = [], []
    for a in range(s_l + 1):
        for b in range(s_l + 1):
            cl, cr = s_l - a - b, s_r - a - b
            hv = [(a, 3), (b, 2), (cl, 2), (cr, 2), (gap0 - cl - cr, 3)]
            if min(v for v, _w in hv) >= 0:
                hs.append(((a, b, cl, cr), [abs(16 * v - w * g) for v, w in hv]))
    for bv in range(s_t + 1):
        for cv in range(s_t + 1):
            vv = [(s_t - bv - cv, 3), (s_b - bv - cv, 3), (bv, 2), (cv, 2)] + [(x + cv, 3) for x in sfb]
            if min(v for v, _w in vv) >= 0:
                vs.append(((bv, cv, s_t - bv - cv), [abs(16 * v - w * g) for v, w in vv]))
    for h, eh in hs:
        for (bv, cv, at), ev in vs:
            e = eh + ev
            cross = (h[0] != at) + (h[1] != bv) + (h[2] != cv) + (h[3] != cv)
            assert (sum(x > 16 for x in e), cross, max(e)) >= key, (g, h, (at, bv, cv))


@pytest.mark.parametrize("g", (17, 22, 25, 40, 64))
def test_law_backdrop_follows_its_rect(g):
    """t_pref_bd scales the rect it is handed (T / R / B; L on the rails), so the law does too."""
    for rect in (SL.PREF_FRAME_NATIVE["backdrop"], (23, 2, 700, 380)):
        want = SL.bandmap_rect_from_halfopen(SL.rail_left_extent(g), *((v * g) >> 4 for v in rect[1:]), g)
        assert SL.pref_frame_draw_rect(SL.PREFWIN_BACKDROP_SITE, rect, g) == SL.pref_backdrop_draw_rect(rect, g) == want


@pytest.mark.parametrize("g", (17, 22, 25, 40, 64))
def test_law_unknown_rect_is_scaled_and_trimmed(g):
    rect = (100, 50, 300, 200)
    assert SL.pref_frame_draw_rect(0x48FBB7, rect, g) == \
        SL.bandmap_rect_from_halfopen(*((v * g) >> 4 for v in rect), g)


def test_table_is_the_law():
    off, b = AP.emit_w6a()["g_pref_frame_tbl"]
    n = len(AP.PREF_FRAME_ORDER)
    for i, g in enumerate(G_RANGE):
        lay = SL.prefwin_layout(g)
        for j, name in enumerate(AP.PREF_FRAME_ORDER):
            assert struct.unpack_from("<4h", b, (i * n + j) * 8) == lay[name], (g, name)
    keys = AP.emit_w6a()["g_pref_frame_keys"][1]
    assert [struct.unpack_from("<4i", keys, 16 * j) for j in range(n)] == \
        [SL.PREF_FRAME_NATIVE[name] for name in AP.PREF_FRAME_ORDER]


# ============================================================================== 2. the shipped bytes
@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def img(baked_exe):
    data = Path(baked_exe).read_bytes()
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for s in pe.sections:
        va = ib + s.VirtualAddress
        mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
        mu.mem_write(va, s.get_data())
    mu.mem_map(STACK, 0x100000)
    mu.mem_map(0, 0x1000)                       # fs:[0] (the gwinit resume's displaced `mov eax, fs:[0]`)
    for va in STUBS:
        mu.mem_write(va, b"\xF4")
    return mu


@pytest.mark.parametrize("name", [t[0] for t in AP.W6A_THUNKS])
def test_shipped_bytes_are_the_assembler(img, symtab, name):
    off, b = AP.emit_w6a()[name]
    assert symtab[name] == AP.PCAVE2 + off
    assert bytes(img.mem_read(AP.PCAVE2 + off, len(b))) == b
    if name not in ("thunk_pref_gwinit", "thunk_pref_boxframe"):
        assert 0x3E000 <= off and off + len(b) <= 0x3F000, "W6A's pcave2 region"


def test_sites(img, symtab):
    b = bytes(img.mem_read(SL.PREFWIN_BACKDROP_SITE, 5))
    assert b[0] == 0xE8 and SL.PREFWIN_BACKDROP_SITE + 5 + struct.unpack("<i", b[1:])[0] == symtab["t_pref_bd"]
    for site in SL.PREF_FRAME_SITES[1:]:
        b = bytes(img.mem_read(site, 5))
        assert site + 5 + struct.unpack("<i", b[1:])[0] == symtab["thunk_pref_boxframe"], hex(site)
    assert symtab["thunk_pref_boxframe"] == 0xA16D00, "uimod.dll prefs.cpp kVA_PrefBoxFrame calls this entry"


def _run(mu, va):
    try:
        mu.emu_start(va, 0, count=2000)
    except Exception:                           # noqa: BLE001  (hlt at a stub ends the run)
        pass


def _stub_at(eip):
    for va in STUBS:
        if eip in (va, va + 1):
            return va
    raise AssertionError(hex(eip))


def _frame_call(mu, va, g, rect, fill):
    mu.mem_write(0x668740, struct.pack("<I", g))
    mu.mem_write(RECT, struct.pack("<4i", *rect))
    mu.mem_write(PARAMS, bytes(0x40))
    mu.mem_write(PARAMS + 0x20, struct.pack("<I", fill))
    regs = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
    for i, r in enumerate(regs):
        mu.reg_write(r, 0x5A5A0000 + i)
    mu.reg_write(UC_X86_REG_ECX, 0x8578D8 + 0x444)
    esp = SP0 - 12
    mu.mem_write(esp, struct.pack("<III", 0xCAFE0000, RECT, PARAMS))
    mu.reg_write(UC_X86_REG_ESP, esp)
    _run(mu, va)
    eip = _stub_at(mu.reg_read(UC_X86_REG_EIP))
    assert mu.reg_read(UC_X86_REG_ESP) == esp, "a tail jump: the renderer sees the caller's frame"
    assert mu.reg_read(UC_X86_REG_ECX) == 0x8578D8 + 0x444
    assert [mu.reg_read(r) for r in regs] == [0x5A5A0000 + i for i in range(len(regs))]
    return STUBS[eip], struct.unpack("<4i", bytes(mu.mem_read(RECT, 16)))


@pytest.mark.parametrize("g", list(range(1, 65)))
def test_frame_thunks_are_the_law(img, symtab, g):
    calls = [("t_pref_bd", SL.PREFWIN_BACKDROP_SITE, r) for r in (SL.PREF_FRAME_NATIVE["backdrop"], (23, 2, 700, 380))]
    for entry in ("thunk_pref_boxframe", "t_pref_frame"):
        calls += [(entry, 0x48FBB7, SL.PREF_FRAME_NATIVE[n]) for n in FRAMES]
        calls += [(entry, 0x48FBB7, (100, 50, 300, 200)), (entry, 0x48FBB7, (253, 7, 716, 384))]
    for name, site, rect in calls:
        for fill in (0, 1):
            where, seen = _frame_call(img, symtab[name], g, rect, fill)
            if g <= 16:
                assert (where, seen) == ("native", rect)
            else:
                assert seen == SL.pref_frame_draw_rect(site, rect, g), (name, g, rect, seen)
                assert where == ("devfill" if fill else "hollow_flat")


@pytest.mark.parametrize("g", list(range(1, 65)))
def test_gwinit_self_arm_is_the_law(img, symtab, g):
    mu = img
    mu.mem_write(0x668740, struct.pack("<I", g))
    mu.mem_write(0x9B7B1C, struct.pack("<ii", 3840, 2160))
    esp = SP0 - 0x40
    args = (0xCAFE0000, 5, 6, 778, 390, 0, 0, 0)
    mu.mem_write(esp, struct.pack("<8I", *args))
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, 0x8578D8)
    _run(mu, symtab["thunk_pref_gwinit"])
    assert _stub_at(mu.reg_read(UC_X86_REG_EIP)) == AP.GWINIT_RESUME
    x, y, w, h = struct.unpack("<4i", bytes(mu.mem_read(esp + 4, 16)))
    if g <= 16:
        assert (x, y, w, h) == (5, 6, 778, 390)
    else:
        assert (x, y) == SL.prefwin_window_pos(3840, 2160, g) and (w, h) == SL.prefwin_window_wh(g), g


# ============================================================================== 3. end to end
@pytest.mark.parametrize("g", E2E_G)
def test_e2e_prefwin(baked_exe, bak_path, g):
    import prefwin_halfopen_emu as PH
    w, h = (1024, 768) if g == 16 else PH.screen_for(g)
    res = PH.screen(str(baked_exe), w, h, page=4)
    assert res["g"] == g
    p = res["p"]
    assert p.shape[::-1] == SL.prefwin_window_wh(g), "the window the rails anchor on"
    seen = PH.frames(res)
    for va, rect, _bb in res["rec"]:
        want = SL.pref_frame_draw_rect(va, rect, g) if g > 16 else (rect[0], rect[1], rect[2] - 1, rect[3] - 1)
        assert seen[va] == (want[0], want[1], min(want[2], p.shape[1] - 1), min(want[3], p.shape[0] - 1)), \
            (g, hex(va), rect)
    m = PH.measure(res)
    k = K(g)
    assert m["rails>backdrop L|R"] == (0, 0), "the backdrop abuts the REAL inner rails on both sides"
    assert m["backdrop border L|R"] == (k, k), "both borders K wide between the rails"
    want = law_channels(g)
    for name, val in m.items():
        if name in want:
            assert val == want[name], (g, name, val, want[name])
    if g == 16:
        old = PH.screen(str(bak_path), w, h, page=4)
        assert np.array_equal(p, old["p"]), "g = 16: the pristine pixels"
        assert m == PH.measure(old)
