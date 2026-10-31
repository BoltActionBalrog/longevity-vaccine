"""The base screen on the real image (image_emu.py via mirror_pairs_emu.Rig), in the engine's order (2026-10-25 W5A):

  screen(W, H)  the real MainWin_build at that screen (SW / SH written, g recomputed by the image's own
                thunk_ensure_scale), then BaseWin_init 0x41E8D0 (the console frame 0x41F53E, the tab frame 0x41F56A,
                every BaseWin child window through the GraphicWin_init chain), then slide_show 0x45D440 (BaseWin, 0)
                -- its SETTLED rail draws through t_bw_railscale (sound + animation flags cleared, the window marked
                hidden so the show path runs), then the centre painters in BaseWin_on_redraw 0x41E790's order:
                expenses 0x412AA0 (which calls energy_alloc 0x411980 first), misc 0x415730, farm 0x40F0F0,
                facilities 0x40FCC0, commerce 0x410870, nutrients 0x411240 (the strip-side painters it interleaves
                draw on MainWin, not this canvas).  Base 0 has every facility bit set, so the BASE FACILITIES list
                overflows (ScrollBar_attach_rect through thunk_bw_facsb_attach).
  The child windows' FINAL args (after thunk_basewin_gwinit) are read at thunk_pref_gwinit's entry.

measure(canvas, g, kids) walks three rows inward from each rail (the tab row pt(17), the facilities row pt(150), the
energy rows pt(400)): the see-through (key 9) run, the console stroke's VISIBLE width, then each inner stroke's channel
and width -- what the player sees -- and the channel's colours (no stroke colour may sit in a channel).  The palette
indices are the base-screen art's: console 26, panel 31, inner box 34, tab frame 99 (stable across g).

stroke_census(pristine16, canvas, g) (W5A v5) is the stroke-thickness census: every centre box (CENSUS_BOXES, on its
law footprint), on every side, must carry exactly K = stroke_width(g) px of its vanilla stroke colour -- measured
inward from the drawn edge on probe rows / columns where the pristine 1024 canvas shows that side's stroke 1 px wide
(vanilla's K).  audit-w5A v4: the footprint check alone missed the farm panel's interior fill overpainting the inner
column / row of the K = 2 right / bottom strokes.

screen(w, h, farm_mode=0): farm_mode is draw_farm's own argument (0 = the base screen's current view: RESOURCE in the
rig; 3 = the SUPPORT view, BaseWin_draw_support 0x408EB0 -- its full-panel fill @0x408EF2 shares thunk_bw_fill2).

mirror_census(pristine16, canvas, g) is the audit-w5A pair census: every colour transition of a vanilla row that has
a mirror twin about x = 363 (x <-> 726 - x, the transition reversed), located on the device row near pt(x) / pt(726 - x)
by the same colour pair; a pair is symmetric iff its device positions sum to S = pt(726).  Rows within CORNER_ROWS of
a box's top / bottom edge are reported apart: a box corner's chamfer is vertical structure (the left and right
boxes of a twin pair need not share their top row), not a horizontal mirror.

COST: one boot per image (~2 s); a screen is ~1.6 s at 1024 .. ~22 s at 4K (BaseWin_init's console devfill at device
size dominates).  The observer is installed after the boot, so the TB cache is flushed once.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

import numpy as np

import image_emu as IE
import mirror_pairs_emu as MP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

BW = 0x6A7628
CENTRE_PAINTERS = (0x412AA0, 0x415730, 0x40F0F0, 0x40FCC0, 0x410870, 0x411240)   # BaseWin_on_redraw's order
FARM = 0x40F0F0
CON, PAN, INN, TAB, KEY = 26, 31, 34, 99, 9
STROKES = {CON, PAN, INN, TAB}
FACILITIES_BUILT = 0x97D040 + 0x8C          # Bases[0].facilities_built[12]
#: the tab row's children (E D c1 GOV c2 B C), the facilities BaseButton, the facilities ScrollBar
TAB_KIDS = (0x6B7B18, 0x6B8664, 0x6C1940, 0x6BA848, 0x6C248C, 0x6B91B0, 0x6B9CFC)
SUB_KIDS = (0x6BBEE0, 0x6BB394, 0x6BCA2C)                                         # RESOURCE / SUPPORT / PSYCH
FAC_BTN, FAC_SB = 0x6C3B24, BW + 0x41454
#: W7H: every BaseWin FlatButton BaseWin_init builds (OK, RENAME, the tab row, RESOURCE / SUPPORT / PSYCH, the
#: chevrons, the facilities button) and the content-draw vtable slot thunk_basewin_btnzoom heads
BTNS = (0x6B4DE8, 0x6B5934, 0x6B7B18, 0x6B8664, 0x6B91B0, 0x6B9CFC, 0x6BA848, 0x6BB394, 0x6BBEE0, 0x6BCA2C,
        0x6C1940, 0x6C248C, 0x6C3B24)
CHEVRONS = (0x6C1940, 0x6C248C)      # thunk_chev_coverage's filter (user-approved), not the 9-slice zoom
CONTENT_SLOT = 0x669784
#: the centre boxes' native first / last rows (BaseWin_init + the painters, census W5A): rows within CORNER_ROWS of
#: one are the corner (chamfer) zone of the pair census
BOX_ROWS = (0, 4, 29, 33, 36, 55, 57, 183, 186, 190, 193, 212, 214, 253, 256, 260, 263, 282, 284, 303, 305, 324, 326,
            345, 348, 352, 355, 374, 376, 380, 383, 387, 390, 395, 397, 403, 416, 418, 437, 439, 440, 442, 446, 471,
            489, 492)   # every centre box_sprite's first / last row on the pristine image
CORNER_ROWS = 1     # W5A v4: every legitimate y-phase singleton is within 1 row of a box edge (audit-w5A v3)


class Rig:
    def __init__(self, exe, sym):
        self.r = MP.Rig(exe, sym)
        self.e = e = self.r.e
        e.stub_fn(0x4E4430, lambda e: 10, 0)            # nutrient cost factor (rules not loaded)
        e.uc.mem_write(FACILITIES_BUILT, bytes([255]) * 12)
        self.kids = {}
        self.gw = sym.get("thunk_pref_gwinit") if self.r.patched else 0x5D4EF0
        e.observe(self.gw, self._gw)
        e.uc.ctl_flush_tb()

    def _gw(self, e):
        esp = e.reg(IE.UC_X86_REG_ESP)
        if e.r32(esp + 0x1C) == BW:
            self.kids[e.reg(IE.UC_X86_REG_ECX)] = tuple(e.s32(esp + 4 + 4 * i) for i in range(4))

    def screen(self, w, h, farm_mode=0):
        e = self.e
        g = self.r.screen(w, h)
        e.w32(0x90EA30, 0x97D040)
        e.w32(0x689370, 0)
        self.kids = {}
        e.call(0x41E8D0, ecx=BW, count=2_000_000_000)
        e.w32(0x9A6490, e.r32(0x9A6490) & ~(0x400 | 0x8000000))
        e.w32(BW + 0x9C, e.r32(BW + 0x9C) & ~1)
        e.call(0x45D440, args=(BW, 0), count=2_000_000_000)
        for fn in CENTRE_PAINTERS:
            e.call(fn, ecx=BW, args=(farm_mode if fn == FARM else 0,), count=2_000_000_000)
        return g, IE.canvas_of(e, BW), dict(self.kids)

    # ------------------------------------------------------------------ W7H: the button faces
    def buttons(self, objs=BTNS, states=(0, 1, 2)):
        """{(obj, state): canvas} -- each BaseWin FlatButton drawn through its content-draw vtable slot [0x669784]
        (thunk_basewin_btnzoom's chain: the 2D zoom, t_sbt_zoom, the edge probe / band, the stripes) in draw state
        0 / 1 / 2 (FlatButton +0xAB8), after screen() built the base screen at the current g."""
        e, out = self.e, {}
        draw = e.r32(CONTENT_SLOT)
        for b in objs:
            for s in states:
                e.w32(b + 0xAB8, s)
                e.call(draw, ecx=b, count=200_000_000)
                out[(b, s)] = IE.canvas_of(e, b)
            e.w32(b + 0xAB8, 0)
        return out


def face_strokes(dev, nat):
    """{side: sorted set of device runs} of a button face's 1-px edge strokes, sides L / R / T / B, probed at 1/4,
    2/5, 3/5, 3/4 of the face where the NATIVE face (nat, the pristine 1024 draw) has a stroke there
    (scaling_laws.edge_stroke_colour: n0 not the key and unlike both inward neighbours); the device run is that
    colour's run from the edge of the face's ART (rows below the art -- key -- excluded).  Sides without a stroke
    are absent.  Plus (key rows under the art, key columns right of the art)."""
    rows = [y for y in range(dev.shape[0]) if (dev[y] != KEY).any()]
    cols = [x for x in range(dev.shape[1]) if (dev[:, x] != KEY).any()]
    art = dev[:rows[-1] + 1, :cols[-1] + 1]
    out = {}
    for side in "LRTB":
        runs = set()
        for f in (0.25, 0.4, 0.6, 0.75):
            if side in "LR":
                l16, ld = nat[int(nat.shape[0] * f)], art[int(art.shape[0] * f)]
            else:
                l16, ld = nat[:, int(nat.shape[1] * f)], art[:, int(art.shape[1] * f)]
            if side in "RB":
                l16, ld = l16[::-1], ld[::-1]
            if SL.edge_stroke_colour(int(l16[0]), int(l16[1]), int(l16[2]), KEY) is None:
                continue
            runs.add(_run(ld, 0, 1, int(l16[0])))
        if runs:
            out[side] = sorted(runs)
    return out, (dev.shape[0] - len(art), dev.shape[1] - art.shape[1])


def _walk(line, inner, start, step):
    n, x = len(line), start
    out = {"see": 0, "channel_colours": set()}
    while 0 <= x < n and int(line[x]) == KEY:
        out["see"] += 1
        x += step
    out["con_at"], out["con_w"] = x, 0
    while 0 <= x < n and int(line[x]) == CON:
        out["con_w"] += 1
        x += step
    for k, col in enumerate(inner):
        ch = 0
        while 0 <= x < n and int(line[x]) != col and ch < 400:
            out["channel_colours"].add(int(line[x]))
            ch += 1
            x += step
        out[f"ch{k}"], out[f"at{k}"], w = ch, x, 0
        while 0 <= x < n and int(line[x]) == col:
            w += 1
            x += step
        out[f"w{k}"] = w
    return out


def measure(canvas, g, kids):
    """{row: {"L": walk from the left rails' end, "R": walk from the right rail's start}} + the twin rows' gaps."""
    pt = (lambda v: v) if g <= SL.NATIVE_G else (lambda v: (v * g) >> 4)
    lx = SL.basewin_rail_left_extent(g)
    a = SL.basewin_rail_anchor(g)
    res = {"lx": lx, "a": a}
    for name, y, inner in (("tab", pt(17), (TAB,)), ("fac", pt(150), (PAN, INN)), ("nrg", pt(400), (PAN, INN))):
        res[name] = {"L": _walk(canvas[y], inner, lx, 1), "R": _walk(canvas[y], inner, a - 1, -1)}
    t = res["tab"]
    fl = t["L"]["at0"] + t["L"]["w0"] - 1           # the left tab-frame stroke's inner column
    fr = t["R"]["at0"] - t["R"]["w0"] + 1           # the right one's
    btn = [kids[k] for k in TAB_KIDS]
    res["tab_gaps"] = ([btn[0][0] - fl - 1] + [btn[i + 1][0] - (btn[i][0] + btn[i][2]) for i in range(6)]
                       + [fr - (btn[6][0] + btn[6][2])])
    sub = [kids[k] for k in SUB_KIDS]
    res["sub_gaps"] = [sub[i + 1][0] - (sub[i][0] + sub[i][2]) for i in range(2)]
    res["sub_sum"] = sub[0][0] + sub[2][0] + sub[2][2]
    res["kids"] = kids
    return res


# ---------------------------------------------------------------------------------------------- the pair census
def _bounds(row, lo, hi):
    d = np.nonzero(row[lo + 1:hi] != row[lo:hi - 1])[0] + lo + 1
    return [(int(x), int(row[x - 1]), int(row[x])) for x in d]


def _vpairs(row):
    b = _bounds(row, 23, 703)
    s = {x: (a, c) for x, a, c in b}
    return [(x, a, c) for x, a, c in b if x < 363 and (726 - x) in s and s[726 - x] == (c, a)]


def _find(row, x0, a, b, win):
    best = None
    for x in range(max(1, x0 - win), min(len(row), x0 + win + 1)):
        if row[x - 1] == a and row[x] == b and (best is None or abs(x - x0) < abs(best - x0)):
            best = x
    return best


def mirror_census(pristine16, canvas, g):
    """-> (Counter of (left + right) - S over the matched pairs outside the corner zone, the off pairs outside it,
    the off pairs inside it, matched count, unmatched count)."""
    pt = (lambda v: v) if g <= SL.NATIVE_G else (lambda v: (v * g) >> 4)
    S = SL.basewin_rail_axis_sum(g)
    res, off, corner = collections.Counter(), [], []
    unmatched = 0
    for y in range(0, 490):
        pairs = _vpairs(pristine16[y])
        if not pairs:
            continue
        yd = pt(y) + (g >> 5)
        if yd >= canvas.shape[0]:
            continue
        row = canvas[yd]
        cz = any(abs(y - r) <= CORNER_ROWS for r in BOX_ROWS)
        for x, a, b in pairs:
            l, r = _find(row, pt(x), a, b, 5), _find(row, pt(726 - x), b, a, 6)
            if l is None or r is None:
                unmatched += 1
                continue
            d = l + r - S
            if cz:
                if d:
                    corner.append((y, x, l, r, d))
                continue
            res[d] += 1
            if d:
                off.append((y, x, l, r, d))
    return res, off, corner, sum(res.values()), unmatched


# ---------------------------------------------------------------------------------------------- the stroke census
#: every centre box_sprite rect the pristine image draws through thunk_bw_boxsprite (BaseWin_init + the painters,
#: census W5A), minus the two console-set redraws the painters clip to a panel (0x411A9A / 0x412BBC)
CENSUS_BOXES = [(128, 446, 622, 472), (166, 352, 699, 441), (346, 376, 696, 438), (169, 355, 696, 375),
                (169, 376, 297, 396), (299, 376, 344, 396), (169, 397, 297, 417), (299, 397, 344, 417),
                (169, 418, 297, 438), (299, 418, 344, 438), (166, 260, 699, 349), (298, 263, 697, 325),
                (169, 263, 296, 283), (169, 284, 296, 304), (169, 305, 296, 325), (169, 326, 696, 346),
                (27, 387, 163, 443), (30, 390, 160, 440), (166, 33, 560, 257), (563, 33, 699, 257), (566, 36, 696, 56),
                (566, 57, 696, 254), (27, 190, 163, 384), (30, 193, 160, 213), (30, 214, 160, 381), (27, 33, 163, 187),
                (30, 36, 160, 56), (30, 57, 160, 184)]
TAB_FRAME = (27, 4, 699, 30)
OK_FRAME = (128, 446, 622, 472)


def draw_footprint(box, g):
    """The inclusive device footprint (L, T, R, B) a census box is drawn on: the centre boxes basewin_box_draw_rect,
    the tab frame its own row-mirror laws, the RENAME / OK frame basewin_okrow_box_draw_rect (W8B)."""
    if box == TAB_FRAME:
        if g <= SL.NATIVE_G:
            return (27, 4, 698, 29)
        return ((27 * g) >> 4, SL.basewin_tabframe_top(g), SL.basewin_tabframe_right(g), SL.basewin_tabframe_bottom(g))
    if g <= SL.NATIVE_G:
        return (box[0], box[1], box[2] - 1, box[3] - 1)
    if box == OK_FRAME:     # W8B: the RENAME / OK row frame has its own adapter (thunk_bw_boxsprite_okrow)
        return SL.basewin_okrow_box_draw_rect(g)
    return SL.basewin_box_draw_rect(*box, g)


def _run(line, start, step, col):
    n, x, k = len(line), start, 0
    while 0 <= x < n and int(line[x]) == col:
        k += 1
        x += step
    return k


def stroke_census(pristine16, canvas, g, boxes=None, ref16=None):
    """-> ({(box, side): (want, sorted device runs)}, [(box, side, want, runs) that miss]).

    The stroke colour of each side is read from pristine16 (the 1024 base screen, RESOURCE view) on probe rows /
    columns where that stroke is 1 px wide; the native run of that colour at the same probe on ref16 (the same view
    as `canvas` on the pristine image; default pristine16) is 1 (the stroke stands: want K) or 0 (vanilla paints over
    it, e.g. the SUPPORT view's full-panel fill: want 0).  A side misses unless every probe reads >= want and one
    reads exactly want (content next to a stroke can share its colour and read long; a thinned stroke reads short
    on every probe)."""
    K = SL.stroke_width(g) if g > SL.NATIVE_G else 1
    pt = (lambda v: v) if g <= SL.NATIVE_G else (lambda v: (v * g) >> 4)
    ref16 = pristine16 if ref16 is None else ref16
    res, bad = {}, []
    for box in (boxes or CENSUS_BOXES + [TAB_FRAME]):
        l, t, r, b = box
        L, T, R, B = draw_footprint(box, g)
        fl, ft, fr, fb = draw_footprint(box, 16)
        rows = sorted({t + (b - t) * k // 6 for k in (2, 3, 4)})
        cols = sorted({l + (r - l) * k // 8 for k in (2, 3, 4, 5, 6)})
        for side in "LRTB":
            runs, wants = [], set()
            for v in (rows if side in "LR" else cols):
                if side in "LR":
                    line16, ref, at16, step = pristine16[v], ref16[v], (fl if side == "L" else fr), \
                        (1 if side == "L" else -1)
                    at, yd = (L if side == "L" else R), min(pt(v) + (g >> 5), canvas.shape[0] - 1)
                    dline = canvas[yd]
                else:
                    line16, ref, at16, step = pristine16[:, v], ref16[:, v], (ft if side == "T" else fb), \
                        (1 if side == "T" else -1)
                    at, xd = (T if side == "T" else B), min(pt(v) + (g >> 5), canvas.shape[1] - 1)
                    dline = canvas[:, xd]
                if not (0 <= at16 < len(line16) and 0 <= at < len(dline)):
                    continue
                col = int(line16[at16])
                if col == KEY or _run(line16, at16, step, col) != 1:
                    continue
                n16 = _run(ref, at16, step, col)
                if n16 > 1:
                    continue
                wants.add(n16 * K)
                runs.append(_run(dline, at, step, col))
            if not runs:
                continue
            assert len(wants) == 1, (box, side, wants)
            want = wants.pop()
            runs.sort()
            res[(box, side)] = (want, runs)
            if runs[0] < want or want not in runs:
                bad.append((box, side, want, runs))
    return res, bad
