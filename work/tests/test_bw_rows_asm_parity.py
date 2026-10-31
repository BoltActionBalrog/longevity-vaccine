"""The base screen's button-row gaps (2026-10-27 W8B, the user's F48 / F49 / F50): the laws and their cave port.

The defects (measure27, in-game 2026-10-27, exe d34e2291):
  F48  the RENAME / OK row frame's channels above / below the buttons 3 | 4 at 1920x1080, 5 | 6 at 4K (vanilla 2 | 2):
       the frame on pt(446) / pt(472) and the buttons on pt(449) + fl(20g/16) floor on different phases;
  F49  the tab row's gaps frame | EXPLORE | DISCOVER | chevron | GOVERNOR 2, 4, 3, 3 at 1600x1200, 6, 5, 5, 5 at 4K,
       3, 3, 2, 3 at 1280x1024 (vanilla all 2): every edge on its own floor;
  F50  RESOURCE / SUPPORT / PSYCH 3, 2, 2, 3 at 1280x1024 (vanilla all 2).
  F52  (W8R, audit-w8B, pre-existing) RESOURCE / SUPPORT / PSYCH end too high: their bottom pt(234) + fl(20g/16) up to
       1.62 px short of vanilla x g/16 (g 19 / 27 / 35; 1920x1080 / 2560x1440 -1.25), so the channel below them to the
       middle panel's stroke one wider than the row's side channel (1920x1080 4 vs 3; vanilla 2 | 2).
The laws (scaling_laws): basewin_tab_row_h (EXPLORE / DISCOVER / chevron 1; the right half their mirrors through S),
basewin_rsp_row_h (RESOURCE / SUPPORT; PSYCH the mirror), basewin_okrow_v (the RENAME / OK frame and buttons, the tab
row's channel) -- each chosen per g against vanilla x g/16 and never worse than v7 beyond 1 px; basewin_child_rect v8
places the children, basewin_okrow_box_rect the frame; basewin_rsp_row_v (W8R) the RESOURCE / SUPPORT / PSYCH top
(basewin_child_rect v9).

Proof layers here (the real image is test_scaling_basewin_mirror.py):
  1. the laws at every g 17..40 (the game's clamp; g <= 16 native, g > 40 v7): equal gaps, the remainder only in the
     row-end channel, mirror pairs exact, every dimension within 1 px of vanilla x g/16 except the listed ones (= v7),
     nothing > 1 px that v7 had within 1 px;
  2. Unicorn parity of the cave code resolved from patches.yaml: g_bw_rows_tbl == basewin_rows_table, thunk_basewin_gwinit
     v8 + t_bw_rowfix == basewin_child_rect for every BaseWin child and for probe children the rows do not own,
     g 16..40 and g 41 / 64 (t_bw_rowfix's v7 exit), and thunk_bw_boxsprite_okrow's rect == basewin_okrow_box_draw_rect
     (the RENAME / OK frame) / basewin_box_draw_rect (any other rect) through the shared trim helper, g <= 16 native.
COST: ~2 s (pure Python + short Unicorn runs).
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

LAW_G = range(17, SL.G_MAX + 1)
#: the user's resolutions -> g (1024x768 16, 1280x1024 20, 1600x900 18, 1920x1080 22, 1600x1200 25, 2560x1440 30, 4K 40)
SEVEN = {(1024, 768): 16, (1280, 1024): 20, (1600, 900): 18, (1920, 1080): 22, (1600, 1200): 25, (2560, 1440): 30,
         (3840, 2160): 40}
TAB = ((30, 112), (144, 112), (258, 20), (280, 166), (448, 20), (470, 112), (584, 112))
RSP = (169, 299, 429)
#: the tab row per g (basewin_tab_row_h's scan): all gaps equal / the remainder at the row ends / flanking GOVERNOR /
#: no such layout within 1 px (v7 kept: 2, 3, 3, 2-type rows)
EQUAL = {18, 22, 25, 26, 28, 30, 31, 32, 34, 38}
ENDS = {17, 23, 24, 33, 39, 40}
CENTRE = {20, 36}
V7_KEPT = {19, 21, 27, 29, 35, 37}


def pt(v, g):
    return SL.basewin_pt(v, g)


def tab_gaps(g):
    """The eight visible gaps of the tab row (frame stroke | E | D | c1 | GOV | c2 | B | C | frame stroke)."""
    k = SL.stroke_width(g)
    kids = [SL.basewin_child_rect(x, 7, w, 20, g) for x, w in TAB]
    edges = [pt(27, g) + k] + sum(([x, x + w] for x, _y, w, _h in kids), []) + [SL.basewin_tabframe_right(g) - k + 1]
    return [edges[i + 1] - edges[i] for i in range(0, len(edges), 2)], kids


def rsp_gaps(g):
    k = SL.stroke_width(g)
    kids = [SL.basewin_child_rect(x, 234, 128, 20, g) for x in RSP]
    p = SL.basewin_box_draw_rect(166, 33, 560, 257, g)
    edges = [p[0] + k] + sum(([x, x + w] for x, _y, w, _h in kids), []) + [p[2] - k + 1]
    return [edges[i + 1] - edges[i] for i in range(0, len(edges), 2)], kids


def okrow(g):
    k = SL.stroke_width(g)
    L, T, R, B = SL.basewin_okrow_box_draw_rect(g)
    ren, ok = (SL.basewin_child_rect(x, 449, 238, 20, g) for x in (131, 381))
    return (ren[1] - (T + k), (B - k + 1) - (ren[1] + ren[3])), (ren[0] - (L + k), (R - k + 1) - (ok[0] + ok[2])), ren, ok


def test_seven_resolutions_map_to_g():
    for (w, h), g in SEVEN.items():
        assert SL.popup_scale_num(SL.scale_uniform(16, w, h)) == g, (w, h)


# ============================================================================== 1. the laws
@pytest.mark.parametrize("g", LAW_G)
def test_tab_row_gaps(g):
    """F49: the eight gaps mirrored, within 1 of each other; equal wherever an equal layout is within 1 px; else the
    remainder in ONE mirrored pair -- the row ends (frame | EXPLORE, CONQUER | frame) or flanking GOVERNOR -- the
    other gaps equal; where neither is within 1 px (V7_KEPT) v7's row stays.  EXPLORE == DISCOVER == BUILD ==
    CONQUER wide, the chevrons D x D; GOVERNOR as v7."""
    gaps, kids = tab_gaps(g)
    assert gaps == gaps[::-1], (g, gaps)
    assert max(gaps) - min(gaps) <= 1, (g, gaps)
    half = gaps[:4]
    if g in V7_KEPT:
        assert SL.basewin_tab_row_h(g) == SL.basewin_tab_row_h_v7(g)
    else:
        assert half[1] == half[2] == half[3] or half[0] == half[1] == half[2], (g, gaps)
        assert (half[0] != half[1]) == (g in ENDS) and (half[3] != half[2]) == (g in CENTRE), (g, gaps)
    assert kids[0][2] == kids[1][2] == kids[5][2] == kids[6][2]
    d = SL.popup_scale_floor(20, g)
    assert kids[2][2:] == kids[4][2:] == (d, d)
    assert kids[3] == (pt(280, g), SL.basewin_tab_btn_y(g), SL.basewin_gov_w(g), d)
    assert all(k[1] == SL.basewin_tab_btn_y(g) for k in kids)
    S = SL.basewin_rail_axis_sum(g)
    for a, b in ((0, 6), (1, 5), (2, 4)):
        assert kids[a][0] + kids[b][0] + kids[b][2] == S, (g, a, b)
    # equal everywhere an equal layout is within 1 px (the law's scan)
    assert (len(set(gaps)) == 1) == (g in EQUAL), (g, gaps)


@pytest.mark.parametrize("g", LAW_G)
def test_tab_row_proportion(g):
    """Every tab-row dimension within 1 px of vanilla x g/16 except the frame channel at g 23 / 39 (+1.12, = v7); no
    dimension > 1 px that v7 had within 1 px."""
    _g, e = SL.basewin_tab_row_h_errors(*SL.basewin_tab_row_h(g), g)
    _g7, e7 = SL.basewin_tab_row_h_errors(*SL.basewin_tab_row_h_v7(g), g)
    over = {n for n, v in e.items() if abs(v) > 1}
    assert over == ({"a0"} if g in (23, 39) else set()), (g, e)
    assert not {n for n in over if abs(e7[n]) <= 1}, (g, e, e7)
    for x, w in TAB:
        X, _Y, W, _H = SL.basewin_child_rect(x, 7, w, 20, g)
        assert abs(X - x * g / 16) <= 1 and abs(X + W - (x + w) * g / 16) <= 1, (g, x, X, W)


@pytest.mark.parametrize("g", LAW_G)
def test_rsp_row(g):
    """F50: panel -> RESOURCE == RESOURCE -> SUPPORT (== the mirrors) at every g but 18 / 34 (no equal layout within
    1 px; v7's remainder at both row ends kept); every dimension within 1 px; PSYCH RESOURCE's mirror, SUPPORT
    centred."""
    gaps, kids = rsp_gaps(g)
    assert gaps == gaps[::-1], (g, gaps)
    assert (gaps[0] == gaps[1]) == (g not in (18, 34)), (g, gaps)
    if g in (18, 34):
        assert gaps[0] == gaps[1] + 1, (g, gaps)
    S = SL.basewin_rail_axis_sum(g)
    assert kids[0][0] + kids[2][0] + kids[2][2] == S and kids[0][2] == kids[2][2]
    assert 2 * kids[1][0] + kids[1][2] == S
    _g, _ws, e = SL.basewin_rsp_row_h_errors(*SL.basewin_rsp_row_h(g), g)
    assert all(abs(v) <= 1 for v in e.values()), (g, e)
    for x, (X, _Y, W, _H) in zip(RSP, kids):
        assert abs(X - x * g / 16) <= 1 and abs(X + W - (x + 128) * g / 16) <= 1 and abs(W - 128 * g / 16) <= 1


@pytest.mark.parametrize("g", LAW_G)
def test_okrow(g):
    """F48: the RENAME / OK frame one channel above and below the buttons -- the tab row's channel -- at every g;
    L | R unchanged (box -> RENAME == OK -> box); every dimension within 1 px except the channels at g 23 / 39
    (+1.12, the tab row's); nothing > 1 px that v7 had within 1 px except the top channel there (v7 had the bottom one)."""
    (ct, cb), (cl, cr), ren, ok = okrow(g)
    T, B, t = SL.basewin_okrow_v(g)
    tT, _tB, tt = SL.basewin_tab_row_v(g)
    k = SL.stroke_width(g)
    assert ct == cb == tt - tT - k, (g, ct, cb)
    assert cl == cr and ren[2] == ok[2] and ren[1] == ok[1] == t, (g, cl, cr)
    assert ren[3] == SL.popup_scale_floor(20, g)
    assert SL.basewin_okrow_box_rect(g) == (pt(128, g), T, pt(622, g), B)
    e = SL.basewin_okrow_v_errors(T, B, t, g)
    e7 = SL.basewin_okrow_v_errors(*SL.basewin_okrow_v_v7(g), g)
    over = {n for n, v in e.items() if abs(v) > 1}
    # v2 (audit-w8B C1): the errors include the frame's neighbour gaps (energy panel above, the left column's box
    # above-left, the window bottom); g 26 keeps v7's button bottom -1.12 (the other equal-channel layout puts the
    # gap above-left at +1.12)
    assert over == ({"c", "cb"} if g in (23, 39) else {"tb"} if g == 26 else set()), (g, e)
    assert {n for n in over if abs(e7[n]) <= 1} <= {"c"}, (g, e, e7)
    assert all(abs(e[n]) <= 1 for n in ("above", "aboveL", "below")), (g, e)
    if (T, B, t) != SL.basewin_okrow_v_v7(g):       # v7 kept wherever its channels were already the tab row's
        T7, B7, t7 = SL.basewin_okrow_v_v7(g)
        assert t7 - T7 - k != tt - tT - k or B7 - k - t7 - ren[3] != tt - tT - k, g
    assert abs(ren[1] - 449 * g / 16) <= 1 and (abs(ren[1] + ren[3] - 469 * g / 16) <= 1 or g == 26)


#: W8R (F52): the RESOURCE / SUPPORT / PSYCH row vertically -- the g whose bottom channel != the side channel (no equal
#: layout within 1 px: 19 / 35 cost the top +1.12, 29 the bottom -1.38) and the g whose bottom stays > 1 px short (31:
#: v8's -1.12 kept, its channels already equal -- the within-1-px ceil top would make them 4 | 3)
RSP_V_UNEQUAL = {19, 29, 35}
RSP_V_OVER = {31: {"tb"}}


def rsp_v(g):
    """(button top, bottom half-open, channel below to the panel stroke, side channel) of the RSP row."""
    kids = [SL.basewin_child_rect(x, 234, 128, 20, g) for x in RSP]
    assert len({(y, h) for _x, y, _w, h in kids}) == 1, (g, kids)
    _x, y, _w, h = kids[0]
    return y, y + h, SL.basewin_rsp_panel_stroke_b(g) - (y + h), rsp_gaps(g)[0][0]


@pytest.mark.parametrize("g", LAW_G)
def test_rsp_row_v(g):
    """F52: one top / one height for RESOURCE / SUPPORT / PSYCH; h = fl(20g/16) (the 20-row art fills it: face ==
    window == hit rect); the channel below == the side channel (panel stroke -> RESOURCE) at every g but RSP_V_UNEQUAL;
    every dimension within 1 px of vanilla x g/16 but RSP_V_OVER (= v8); nothing > 1 px that v8 had within 1 px; an
    equality v8 had never broken; the horizontal row (F50) untouched."""
    t, b, cb, a = rsp_v(g)
    assert b - t == SL.popup_scale_floor(20, g)
    assert t == SL.basewin_rsp_row_v(g)
    assert (cb == a) == (g not in RSP_V_UNEQUAL), (g, cb, a)
    e = SL.basewin_rsp_row_v_errors(t, g)
    t8 = SL.basewin_rsp_row_v_v8(g)
    e8 = SL.basewin_rsp_row_v_errors(t8, g)
    over = {n for n, v in e.items() if abs(v) > 1}
    assert over == RSP_V_OVER.get(g, set()), (g, e)
    assert not {n for n in over if abs(e8[n]) <= 1}, (g, e, e8)
    h = SL.popup_scale_floor(20, g)
    if SL.basewin_rsp_panel_stroke_b(g) - t8 - h == a:
        assert cb == a, g
    assert abs(t - t8) <= 1
    assert [k[0::2] for k in (SL.basewin_child_rect(x, 234, 128, 20, g) for x in RSP)] ==         [k[0::2] for k in rsp_gaps(g)[1]]


def test_rsp_row_v_resolutions():
    """The user's seven resolutions (before = v8, the deployed 944a0305): (top, bottom, channel below | side)."""
    want = {  # g: (before, after)
        18: ((263, 285, 3, 3), (263, 285, 3, 3)),
        20: ((292, 317, 3, 3), (292, 317, 3, 3)),
        22: ((321, 348, 4, 3), (322, 349, 3, 3)),
        25: ((365, 396, 3, 3), (365, 396, 3, 3)),
        30: ((438, 475, 4, 3), (439, 476, 3, 3)),
        40: ((585, 635, 5, 5), (585, 635, 5, 5)),
    }
    for g, (before, after) in want.items():
        t8, h = SL.basewin_rsp_row_v_v8(g), SL.popup_scale_floor(20, g)
        assert (t8, t8 + h, SL.basewin_rsp_panel_stroke_b(g) - t8 - h, rsp_gaps(g)[0][0]) == before, g
        assert rsp_v(g) == after, g
    assert SL.basewin_child_rect(169, 234, 128, 20, 16) == (169, 234, 128, 20)


def test_rows_native_and_unreachable():
    """g <= 16: the native args; g > G_MAX (unreachable -- g_popup_scale_num is clamped): v7."""
    for x, w in TAB:
        assert SL.basewin_child_rect(x, 7, w, 20, 16) == (x, 7, w, 20)
    for x in RSP:
        assert SL.basewin_child_rect(x, 234, 128, 20, 16) == (x, 234, 128, 20)
    assert SL.basewin_okrow_box_rect(16) == (128, 446, 622, 472)
    for g in (41, 64):
        assert SL.basewin_tab_row_h(g) == SL.basewin_tab_row_h_v7(g)
        assert SL.basewin_rsp_row_h(g) == SL.basewin_rsp_row_h_v7(g)
        assert SL.basewin_okrow_v(g) == SL.basewin_okrow_v_v7(g)
        assert SL.basewin_rsp_row_v(g) == SL.basewin_rsp_row_v_v8(g) == SL.basewin_pt(234, g)
    assert SL.basewin_rsp_row_v(16) == 234 and SL.basewin_rsp_panel_stroke_b(16) == 256


def test_resolutions_before_after():
    """The user's seven resolutions: the measured defects gone (before = v7, the deployed d34e2291)."""
    want = {  # g: (tab gaps left half, rsp (a, b), ok (top, bottom))
        16: ([2, 2, 2, 2], (2, 2), (2, 2)),
        18: ([3, 3, 3, 3], (3, 2), (3, 3)),
        20: ([3, 3, 3, 2], (3, 3), (3, 3)),
        22: ([3, 3, 3, 3], (3, 3), (3, 3)),
        25: ([3, 3, 3, 3], (3, 3), (3, 3)),
        30: ([4, 4, 4, 4], (3, 3), (4, 4)),
        40: ([6, 5, 5, 5], (5, 5), (5, 5)),
    }
    for g, (tg, rg, og) in want.items():
        if g <= 16:
            continue
        assert tab_gaps(g)[0][:4] == tg, g
        assert tuple(rsp_gaps(g)[0][:2]) == rg, g
        assert okrow(g)[0] == og, g


# ============================================================================== 2. the cave port
unicorn = pytest.importorskip("unicorn", reason="unicorn absent - asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: E402

import apply_patches as ap  # noqa: E402


def _load():
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    thunks = {}
    for cave in doc["code_caves"]:
        base = cave["virtual_addr"]
        base = int(base, 16) if isinstance(base, str) else base
        for c in cave.get("contents", []) or []:
            off = c["offset"]
            off = int(off, 16) if isinstance(off, str) else off
            thunks[c["id"]] = (base + off, ap.ByteTemplate(c["bytes"]).resolve(base + off, symtab))
    return symtab, thunks


SYMTAB, THUNKS = _load()
G_VA = SYMTAB["g_popup_scale_num"]
G_BW_RECT = SYMTAB["g_bw_rect"]
PREF_GWINIT = SYMTAB["thunk_pref_gwinit"]
HOLLOW, DEVFILL = SYMTAB["thunk_box_thick_hollow_flat"], SYMTAB["thunk_box_thick_devfill"]
HO_HF, HO_DF = SYMTAB["t_bm_ho_hf"], SYMTAB["t_bm_ho_df"]
BOX_SPRITE = 0x5E2DD3
BW = 0x6A7628
CANVAS = BW + 0x444
STACK = 0x00200000
SITE_RET = 0x00410031
RENDER_RET = 0x00410051
CODE = ("t_bw_railsum", "t_bw_rimcore", "t_bw_rimx", "t_bw_mirrect", "thunk_basewin_gwinit", "g_bw_tabrow_tbl",
        "g_bw_rows_tbl", "g_bw_rspv_tbl", "t_bw_rowfix", "thunk_bw_boxsprite_okrow", "t_bm_ho_hf", "t_bm_ho_df")
#: every BaseWin child BaseWin_init builds (FlatButton object -> native x, y, w, h) + probes the rows do not own
CHILDREN = {0x6B7B18: (30, 7, 112, 20), 0x6B8664: (144, 7, 112, 20), 0x6C1940: (258, 7, 20, 20),
            0x6BA848: (280, 7, 166, 20), 0x6C248C: (448, 7, 20, 20), 0x6B91B0: (470, 7, 112, 20),
            0x6B9CFC: (584, 7, 112, 20), 0x6BBEE0: (169, 234, 128, 20), 0x6BB394: (299, 234, 128, 20),
            0x6BCA2C: (429, 234, 128, 20), 0x6B5934: (131, 449, 238, 20), 0x6B4DE8: (381, 449, 238, 20),
            0x6C3B24: (569, 231, 124, 20)}
PROBES = [(100, 7, 50, 20), (500, 7, 50, 20), (30, 7, 100, 20), (258, 7, 21, 20), (300, 7, 20, 20),
          (169, 234, 120, 20), (200, 234, 128, 20), (429, 234, 100, 20), (299, 234, 120, 20), (170, 449, 50, 20),
          (30, 8, 112, 20), (169, 233, 128, 20), (131, 448, 238, 20)]


def test_table_is_the_law():
    va, blob = THUNKS["g_bw_rows_tbl"]
    assert va == SYMTAB["g_bw_rows_tbl"] and len(blob) == 20 * len(LAW_G)
    for i, g in enumerate(LAW_G):
        assert struct.unpack_from("<10H", blob, 20 * i) == SL.basewin_rows_table(g), g


def test_rspv_table_is_the_law():
    """W8R: g_bw_rspv_tbl == basewin_rsp_row_v, one word per g 17..40, inside its 64 B slot before t_bw_rowfix v2."""
    va, blob = THUNKS["g_bw_rspv_tbl"]
    assert va == SYMTAB["g_bw_rspv_tbl"] and len(blob) == 2 * len(LAW_G)
    assert va + len(blob) <= SYMTAB["t_bw_rowfix"] == THUNKS["t_bw_rowfix"][0]
    for i, g in enumerate(LAW_G):
        assert struct.unpack_from("<H", blob, 2 * i)[0] == SL.basewin_rsp_row_v(g), g


def _uc(g):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0xA0C000, 0x40000)
    uc.mem_map(0x5D0000, 0x20000)
    uc.mem_map(0x410000, 0x1000)
    uc.mem_map(0x660000, 0x10000)
    uc.mem_map(0x6A0000, 0x50000)
    uc.mem_map(0x7A0000, 0x30000)
    uc.mem_map(0x9B7000, 0x1000)
    uc.mem_map(STACK, 0x10000)
    for tid in CODE:
        uc.mem_write(*THUNKS[tid])
    for va in (HOLLOW, DEVFILL, BOX_SPRITE, SITE_RET, PREF_GWINIT):
        uc.mem_write(va, b"\xF4")
    uc.mem_write(G_VA, struct.pack("<i", g))
    w = (SL.BASEWIN_NATIVE_W * g) >> 4 if g > 16 else SL.BASEWIN_NATIVE_W
    h = (SL.BASEWIN_NATIVE_H * g) >> 4 if g > 16 else SL.BASEWIN_NATIVE_H
    uc.mem_write(CANVAS + 0x80, struct.pack("<2i", w, -h))
    return uc


def _run(uc, va, count=2000):
    try:
        uc.emu_start(va, 0, count=count)
    except unicorn.UcError:
        pass
    return uc.reg_read(UC_X86_REG_EIP)


def _at(eip, t):
    return eip in (t, t + 1)


def _gwinit(uc, ecx, rect):
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I4i3I", 0xCAFE0000, *rect, 0, 0, BW))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, ecx)
    eip = _run(uc, THUNKS["thunk_basewin_gwinit"][0])
    assert _at(eip, PREF_GWINIT) and uc.reg_read(UC_X86_REG_ESP) == esp and uc.reg_read(UC_X86_REG_ECX) == ecx, \
        (rect, hex(eip))
    return struct.unpack("<4i", uc.mem_read(esp + 4, 16))


@pytest.mark.parametrize("g", list(range(16, SL.G_MAX + 1)) + [41, 64])
def test_gwinit_v8_children(g):
    """thunk_basewin_gwinit v8 (+ t_bw_rowfix) == basewin_child_rect v8 for every BaseWin child and the probes (other
    x / w / y on the three rows: left as v7 placed them), g 16..40 and the unreachable g 41 / 64 (rowfix's v7 exit)."""
    uc = _uc(g)
    for ecx, rect in list(CHILDREN.items()) + [(BW + 0xD7C0, p) for p in PROBES]:
        assert _gwinit(uc, ecx, rect) == SL.basewin_child_rect(*rect, g), (g, hex(ecx), rect)


def _box(g, rect, fill, canvas_w=None):
    uc = _uc(g)
    if canvas_w is not None:
        uc.mem_write(CANVAS + 0x80, struct.pack("<i", canvas_w))
    rect_va, params = STACK + 0x100, STACK + 0x200
    uc.mem_write(rect_va, struct.pack("<4i", *rect))
    uc.mem_write(params + 0x20, struct.pack("<I", 1 if fill else 0))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<3I", SITE_RET, rect_va, params))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, CANVAS)
    eip = _run(uc, THUNKS["thunk_bw_boxsprite_okrow"][0])
    return uc, eip, esp, rect_va


@pytest.mark.parametrize("g", list(range(16, SL.G_MAX + 1)) + [41])
def test_okrow_box_adapter(g):
    """thunk_bw_boxsprite_okrow (site 0x41F5B7): the band renderer receives basewin_okrow_box_draw_rect for the row
    frame (basewin_box_draw_rect for any other rect / g > 40) through the shared trim helper (t_bm_ho_df for a fill
    set, t_bm_ho_hf for a hollow one), the caller's rect never written; the renderer's RET 8 returns to the site with
    the half-open rect restored; g <= 16 (canvas 758) -> the native Buffer_box_sprite with the args untouched."""
    if g <= 16:     # v2 (audit-w8B I1): g <= 16 exits native even past the canvas gate (a wide canvas at g 16)
        for fill in (True, False):
            uc, eip, esp, rect_va = _box(g, (128, 446, 622, 472), fill, canvas_w=1000)
            assert _at(eip, BOX_SPRITE) and struct.unpack("<I", uc.mem_read(esp + 4, 4))[0] == rect_va
            assert uc.reg_read(UC_X86_REG_ESP) == esp and uc.reg_read(UC_X86_REG_ECX) == CANVAS
    for rect in ((128, 446, 622, 472), (128, 446, 622, 471), (166, 352, 699, 441)):
        for fill in (True, False):
            uc, eip, esp, rect_va = _box(g, rect, fill)
            if g <= 16:
                assert _at(eip, BOX_SPRITE) and struct.unpack("<I", uc.mem_read(esp + 4, 4))[0] == rect_va
                continue
            assert _at(eip, DEVFILL if fill else HOLLOW), (g, rect, hex(eip))
            sp = uc.reg_read(UC_X86_REG_ESP)
            hret, rp, params = struct.unpack("<3I", uc.mem_read(sp, 12))
            helper = HO_DF if fill else HO_HF
            assert helper < hret < helper + 0x40 and rp == G_BW_RECT and params == STACK + 0x200
            frame = rect == (128, 446, 622, 472) and g <= SL.G_MAX
            want = SL.basewin_okrow_box_draw_rect(g) if frame else SL.basewin_box_draw_rect(*rect, g)
            assert struct.unpack("<4i", uc.mem_read(G_BW_RECT, 16)) == want, (g, rect)
            assert struct.unpack("<4i", uc.mem_read(rect_va, 16)) == rect
            assert uc.reg_read(UC_X86_REG_ECX) == CANVAS
            uc.mem_write(RENDER_RET, b"\xC2\x08\x00")
            assert _at(_run(uc, RENDER_RET, 200), SITE_RET)
            assert uc.reg_read(UC_X86_REG_ESP) == esp + 12 and uc.reg_read(UC_X86_REG_ECX) == CANVAS
            half = SL.basewin_okrow_box_rect(g) if frame else SL.basewin_mirror_rect(*rect, g)
            assert struct.unpack("<4i", uc.mem_read(G_BW_RECT, 16)) == half
