"""Armed non-rail scrollbars on the REAL image (W10S F56; guard tests/test_scaling_nonrail_sb_e2e.py).

Three rigs on image_emu.py, each ONE boot reused across resolutions / g (measured equal to a fresh screen per g):

  PrefRig   the PREFERENCES window's four Audio / Visual sliders (horizontal, vanilla 20 px): boot, the interface art,
            MainWin_build once, then per screen SW / SH + the image's own thunk_ensure_scale and the real PrefWin_build
            0x48D840 (every slider through thunk_pref_gwinit).  PrefWin_show is not run: it only paints the window
            around the sliders (the sliders' rects, values and canvases come from the build; measured identical with
            and without the show at 1920x1080 / 1600x1200 / 3840x2160).
  BaseRig   the base screen's FACILITIES bar (vertical, vanilla 12 px): basewin_mirror_emu's real screen once, at
            3840x2160 (BaseWin_init + the centre painters); then any g is FORCED (g_popup_scale_num + g_stripe_period,
            the two values thunk_ensure_scale writes) and the real facilities painter 0x40FCC0 re-run -- it re-attaches
            the bar through ScrollBar_attach_rect / thunk_bw_facsb_attach at that g (basewin_facsb_rect(g)); measured
            identical to the real 1088x816 and 1920x1080 screens' bars.
  LobbyRig  the MP SETUP lobby's chat bar (vertical, vanilla 20 px): netwin_lobby_emu's builder at any forced g on one
            4K boot (its documented contract), g_netwin_active held as the lobby holds it.

draw(e, sb) runs the bar's own draw slot (vtbl+0x30: the armed bracket thunk_pref_sbzoom for the sliders / FACILITIES,
ScrollBar_draw inside the lobby's bracket) exactly as a repaint does, with two observers: the grip site 0x6067ED
(ScrollBar_draw's frame: the thumb rect, the canvas before the grip) and t_btn_edgeprobe's entry (thunk_btn_2dscale's
zoom call: each arrow's NATIVE render, wn x hn, before the in-place zoom).  measure() reads the drawn result.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import image_emu as IE  # noqa: E402
import scaling_laws as SL  # noqa: E402

GRIP_SITE = 0x6067ED
SB_UP, SB_DN = 0xAAC, 0x15F8
THUMB_RECT = 0x606C50              # ScrollBar_thumb_rect: thiscall(RECT* out) RET 4
SET_POS = 0x605D20                 # ScrollBar_set_pos: thiscall(value) RET 4 (redraws through vtbl+0xF8)
SET_RANGE = 0x6059B0               # ScrollBar_set_range: thiscall(min, max) RET 8
KEY = 9
G_VA, G_PERIOD = 0x668740, 0x66879C
STANDARD = ((1024, 768), (1280, 1024), (1600, 900), (1920, 1080), (1600, 1200), (2560, 1440), (3840, 2160))


def g_of(w, h):
    """g_popup_scale_num at a resolution: fl(16 min(W / 1024, H / 768)), clamped to 16..40 (thunk_ensure_scale)."""
    return max(16, min(40, (16 * w) // 1024, (16 * h) // 768))


def sweep_screens():
    """{g: (W, H)}: the 7 standard resolutions' g at those resolutions, every other g 17..40 at the 4:3 64g x 48g."""
    out = {g_of(w, h): (w, h) for w, h in STANDARD}
    for g in range(17, 41):
        out.setdefault(g, (64 * g, 48 * g))
    return dict(sorted(out.items()))


class Probe:
    """The draw-time observers (installed once per emu)."""

    def __init__(self, e, edgeprobe):
        self.e, self.thumb, self.before, self.native = e, {}, {}, {}
        e.observe(GRIP_SITE, self._grip)
        if edgeprobe:
            e.observe(edgeprobe, self._zoom)
        e.uc.ctl_flush_tb()

    def _grip(self, e):
        sb = e.reg(IE.UC_X86_REG_ESI)
        sp = e.reg(IE.UC_X86_REG_ESP)
        self.thumb[sb] = tuple(e.s32(sp + 0x24 + 4 * i) for i in range(4))
        self.before[sb] = IE.canvas_of(e, sb)

    def _zoom(self, e):
        btn = e.reg(IE.UC_X86_REG_ESI)
        sp = e.reg(IE.UC_X86_REG_ESP)
        buf, wn, hn = e.r32(sp + 4), e.s32(sp + 0x14), e.s32(sp + 0x18)
        data, stride = e.r32(buf + 0x54), e.s32(buf + 0x4A8)
        if not data or not (0 < wn <= 256 and 0 < hn <= 256) or stride < wn:
            return
        raw = bytes(e.uc.mem_read(data, stride * hn))
        self.native[btn] = [list(raw[y * stride:y * stride + wn]) for y in range(hn)]


def draw(e, sb, probe):
    for d in (probe.thumb, probe.before):
        d.pop(sb, None)
    for a in (SB_UP, SB_DN):
        probe.native.pop(sb + a, None)
    e.call(e.r32(e.r32(sb) + 0x30), ecx=sb, count=200_000_000)


def redraw_arrow(e, arrow, state, probe, arm=None):
    """One arrow alone in draw state idle / hover / pressed (+0xA74 hover, +0xA18 pressed) -- a hover / press repaint."""
    hv, pr = {"idle": (0, 0), "hover": (1, 0), "press": (0, 1)}[state]
    e.w32(arrow + 0xA74, hv)
    e.w32(arrow + 0xA18, pr)
    probe.native.pop(arrow, None)
    if arm:
        arm(1)
    e.call(e.r32(e.r32(arrow) + 0x30), ecx=arrow, count=100_000_000)
    if arm:
        arm(0)
    e.w32(arrow + 0xA74, 0)
    e.w32(arrow + 0xA18, 0)
    return IE.canvas_of(e, arrow)


def rect(e, w):
    return tuple(e.s32(w + 0x13C + 4 * i) for i in range(4))


def thumb_rect_now(e, sb):
    out = e.alloc(16)
    e.call(THUMB_RECT, ecx=sb, args=(out,), count=10_000_000)
    return tuple(e.s32(out + 4 * i) for i in range(4))


def span(mask):
    idx = np.nonzero(mask)[0]
    return (int(idx[0]), int(idx[-1]) + 1) if len(idx) else None


def measure(e, sb, probe, g):
    """-> dict of the drawn bar (bar-local px): orientation, cross size n, both arrows (window rect, canvas, plate
    span on both axes, the law's image from the captured native), the thumb rect, the grip's drawn bbox, the grip
    sprite dims, the press zone [+0xA4C..+0xA58]."""
    c = IE.canvas_of(e, sb)
    H, W = c.shape
    vert = H >= W
    out = dict(vert=vert, n=W if vert else H, W=W, H=H, sbrect=rect(e, sb))
    for nm, off in (("up", SB_UP), ("dn", SB_DN)):
        a = IE.canvas_of(e, sb + off)
        nz = a != KEY
        nat = probe.native.get(sb + off)
        law = None
        if nat is not None:
            law = SL.sb_nonrail_arrow(nat, len(nat[0]), len(nat), a.shape[1], a.shape[0], g)
        out[nm] = dict(win=rect(e, sb + off), shape=a.shape, cols=span(nz.any(0)), rows=span(nz.any(1)), canvas=a,
                       native=nat, law=None if law is None else np.array(law, np.uint8))
    tr = probe.thumb.get(sb)
    out["thumb"] = tr
    if tr is not None and sb in probe.before:
        d = probe.before[sb] != c
        out["grip"] = (span(d.any(0)), span(d.any(1)))         # (x span, y span), bar-local
    spr = e.r32(sb + 0xA74)
    out["sprite"] = (e.s32(spr + 0x18), e.s32(spr + 0x1C)) if spr else None
    out["zone"] = tuple(e.s32(sb + 0xA4C + 4 * i) for i in range(4))
    return out


def cross(m, sp_cols, sp_rows):
    """The span across the bar (columns of a vertical bar, rows of a horizontal one)."""
    return sp_cols if m["vert"] else sp_rows


def along(m, sp_cols, sp_rows):
    return sp_rows if m["vert"] else sp_cols


# ---- the rigs --------------------------------------------------------------------------------------------------------
class PrefRig:
    def __init__(self, exe):
        import prefwin_halfopen_emu as P
        self.P = P
        os.environ.setdefault("SMACX_EXE_NAME", "terranx_PRACX.exe")
        IE.HEAP_SZ = max(IE.HEAP_SZ, 0x10000000)
        e = self.e = IE.boot(exe, 1024, 768)
        self.patched = bytes(e.uc.mem_read(0x4A4418, 1)) == b"\xE9"
        self.sym = P._symtab() if self.patched else {}
        if self.patched:
            for k in P.VPDONE:
                e.w32(self.sym[k], 1)
        IE.Files(e)
        e.uc.mem_write(0x9B8AA8, b"xscript\0")
        e.call(0x455610, count=0)
        e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
        e.call(0x616A00, count=50_000_000)
        e.stub_fn(0x514880, lambda e: 0, popbytes=4)
        e.call(0x4547E0, count=500_000_000)                       # load_icons: the scrollbar art
        self.built = False
        self.probe = Probe(e, self.sym.get("t_btn_edgeprobe"))
        self.bars = P.SLIDERS

    def screen(self, w, h):
        e, P = self.e, self.P
        e.w32(IE.SW, w)
        e.w32(IE.SH, h)
        if self.patched:
            e.w32(IE.GSCALE, 0)
            e.call(P.ENSURE_SCALE)
        if not self.built:
            e.call(P.MAINWIN_BUILD, ecx=P.MAINWIN, count=2_000_000_000)
            e.w32(P.MAINWIN + 0x9C, e.r32(P.MAINWIN + 0x9C) | 1)
            self.built = True
        e.call(P.BUILD, ecx=P.PREFWIN, count=200_000_000)
        return e.r32(IE.GSCALE) if self.patched else 16

    def arm(self, v):
        """The arrows' hover / press repaints outside the draw bracket (btn_gate admits the sliders' arrows)."""
        return None


class BaseRig:
    def __init__(self, exe, w=3840, h=2160):
        import basewin_mirror_emu as B
        import mirror_pairs_emu as MP
        self.B = B
        sym = MP.symtab()
        self.rig = B.Rig(exe, sym)
        e = self.e = self.rig.e
        self.patched = self.rig.r.patched
        e.call(0x4547E0, count=500_000_000)
        self.probe = Probe(e, sym.get("t_btn_edgeprobe") if self.patched else None)
        self.g0 = self.rig.screen(w, h)[0]
        self.bars = (B.FAC_SB,)

    def force(self, g):
        e = self.e
        if self.patched:
            e.w32(G_VA, g)
            e.w32(G_PERIOD, SL.stripe_period(g) if g > 16 else 2)
        e.call(0x40FCC0, ecx=self.B.BW, args=(0,), count=2_000_000_000)
        return g if self.patched else 16


class LobbyRig:
    def __init__(self, exe):
        import netwin_lobby_emu as N
        self.N = N
        self.L = N.Lobby(exe)
        e = self.e = self.L.e
        self.patched = self.L.patched
        e.call(0x4547E0, count=500_000_000)
        sym = {}
        if self.patched:
            import mirror_pairs_emu as MP
            sym = MP.symtab()
        self.probe = Probe(e, sym.get("t_btn_edgeprobe"))

    def build(self, g):
        self.L.build(g)
        if self.patched:
            self.e.w32(self.N.G_NETWIN_ACTIVE, 1)
        return g

    def bars(self):
        out, seen = [], set()

        def walk(w, depth):
            if w in seen or depth > 6:
                return
            seen.add(w)
            for i in range(max(0, min(self.e.s32(w + 0x3FC), 150))):
                c = self.e.r32(w + 0x1A4 + 4 * i)
                if not c:
                    continue
                if self.e.r32(c) == 0x669D58:
                    out.append(c)
                walk(c, depth + 1)
        walk(self.N.NETWIN, 0)
        return sorted(set(out))


def check(m, g):
    """The F56 relations on one drawn bar at g > 16 -> [failure, ...] (empty = every relation holds):
      * both arrows are n x n windows at the bar's two ends (their hit rects ARE their drawn squares);
      * each arrow is the law's image of its own native render (sb_nonrail_arrow v5: the plate on rail_grip_span(n, F,
        g) on both axes, a plain mirror-exact NN of the native plate);
      * up plate == down plate == grip == rail_grip_span(n, sprite, g) across the bar, centred (equal channels);
      * along the bar the down arrow is the mirror of the up arrow (vanilla: 1 | 1 for the 20-px bars, 1 | 2 / 2 | 1
        for the 12-px bars' glyphs);
      * the grip is drawn exactly on sb_nonrail_grip_rect(thumb rect) -- centred on both axes -- and the press zone
        [+0xA4C..+0xA58] is the drawn thumb rect;
      * the thumb rect lies in the track between the arrows."""
    bad = []
    n, W, H, vert = m["n"], m["W"], m["H"], m["vert"]
    ends = {"up": (0, 0, n, n), "dn": (0, H - n, n, H) if vert else (W - n, 0, W, n)}
    for nm in ("up", "dn"):
        a = m[nm]
        if a["shape"] != (n, n) or a["win"] != ends[nm]:
            bad.append((nm, "window", a["win"], a["shape"], ends[nm]))
        if a["law"] is None or a["law"].shape != a["canvas"].shape or (a["law"] != a["canvas"]).any():
            bad.append((nm, "canvas != law image of its native"))
    sw, sh = m["sprite"]
    off, w = SL.rail_grip_span(n, sw if vert else sh, g)
    want = (off, off + w)
    for nm in ("up", "dn"):
        c = cross(m, m[nm]["cols"], m[nm]["rows"])
        if c != want:
            bad.append((nm, "plate across", c, want))
    u, d = along(m, m["up"]["cols"], m["up"]["rows"]), along(m, m["dn"]["cols"], m["dn"]["rows"])
    if u is None or d is None or (u[0], n - u[1]) != (n - d[1], d[0]):
        bad.append(("arrows along not mirrored", u, d))
    tr = m["thumb"]
    if tr is None or "grip" not in m:
        bad.append(("no grip draw",))
        return bad
    x, y, gw, gh = SL.sb_nonrail_grip_rect(tr, sw, sh, g)
    if m["grip"] != ((x, x + gw), (y, y + gh)):
        bad.append(("grip", m["grip"], (x, y, gw, gh), tr))
    l, t, r, b = tr
    if (x - l, r - x - gw) != ((r - l - gw) // 2,) * 2 or (y - t, b - y - gh) != ((b - t - gh) // 2,) * 2:
        bad.append(("grip not centred", (x, y, gw, gh), tr))
    if cross(m, (x, x + gw), (y, y + gh)) != want:
        bad.append(("grip across != plate", (x, y, gw, gh), want))
    if m["zone"] != tr:
        bad.append(("press zone != drawn thumb", m["zone"], tr))
    lo, hi = (t, b) if vert else (l, r)
    if lo < n or hi > (H if vert else W) - n:
        bad.append(("thumb outside the track", tr))
    return bad


def track(e, sb, probe, g, values=None):
    """The thumb follows the value: for every value in [+0xA20, +0xA24] (or `values`), ScrollBar_set_pos then the
    bar's draw; the grip must sit on sb_nonrail_grip_rect(the thumb rect) at every value, the thumb must stay in the
    track and move monotonically with the value (the bar's +0xA28 inverts it).  -> ([failure, ...], positions)."""
    lo, hi = e.s32(sb + 0xA20), e.s32(sb + 0xA24)
    vals = list(range(lo, hi + 1)) if values is None else values
    keep = e.s32(sb + 0xA2C)
    bad, pos = [], []
    for v in vals:
        e.call(SET_POS, ecx=sb, args=(v,), count=100_000_000)
        draw(e, sb, probe)
        m = measure(e, sb, probe, g)
        tr = m["thumb"]
        if tr is None or "grip" not in m:
            bad.append(("no grip", v))
            continue
        x, y, gw, gh = SL.sb_nonrail_grip_rect(tr, *m["sprite"], g)
        if m["grip"] != ((x, x + gw), (y, y + gh)):
            bad.append(("grip off the thumb", v, m["grip"], tr))
        if m["zone"] != tr:
            bad.append(("press zone", v, m["zone"], tr))
        a = (tr[1], tr[3]) if m["vert"] else (tr[0], tr[2])
        if a[0] < m["n"] or a[1] > (m["H"] if m["vert"] else m["W"]) - m["n"]:
            bad.append(("thumb outside the track", v, tr))
        pos.append(a[0])
    e.call(SET_POS, ecx=sb, args=(keep,), count=100_000_000)
    inv = e.s32(sb + 0xA28) != 0
    steps = [b - a for a, b in zip(pos, pos[1:])]
    if any((s > 0) if inv else (s < 0) for s in steps) or (len(set(pos)) < 2 and len(vals) > 1):
        bad.append(("thumb does not track the value", pos[:8], pos[-8:]))
    return bad, pos


def dll_slider(rig, value=50):
    """uimod.dll's Longevity slider, built the way prefs.cpp BuildWidgets builds it, on the exe's own code: the
    registry slot g_dll_pref_slider names it (thunk_pref_sbzoom arms its draw, thunk_pref_gwinit scales its arrows /
    thumb), the engine ScrollBar ctor 0x6051D0, a PRIVATE copy of the ScrollBar vtable (0x170 bytes of 0x669D58), the
    engine ScrollBar_init 0x6058D0 at the PrefWin slider statics (x [0x8578CC], y [0x8578D0] + 44, w [0x8578B8],
    parent PrefWin, id 0x60), range 0..100, the value.  The registry's lo / hi (g_dll_pref_lo / _hi: the DLL's widget
    block, which the exe's FlatButton zoom stubs admit) cover the slider object, so its arrows' hover / press repaints
    zoom as the DLL's do.  One slider per screen (the registry holds one)."""
    e = rig.e
    sb = e.alloc(0x2200)
    vt = e.alloc(0x200)
    e.uc.mem_write(vt, bytes(e.uc.mem_read(0x669D58, 0x170)))
    if rig.patched:                                   # the DLL widget registry (prefs.cpp: lo / hi = its widget block)
        e.w32(rig.sym["g_dll_pref_lo"], sb)
        e.w32(rig.sym["g_dll_pref_hi"], sb + 0x2200 - 1)
        e.w32(rig.sym["g_dll_pref_slider"], sb)
    e.call(0x6051D0, ecx=sb, count=50_000_000)
    e.w32(sb, vt)
    e.call(0x6058D0, ecx=sb, args=(e.s32(0x8578CC), e.s32(0x8578D0) + 44, e.s32(0x8578B8), 0x8578D8, 0x60),
           count=200_000_000)
    e.call(0x6059B0, ecx=sb, args=(0, 100), count=50_000_000)
    e.call(SET_POS, ecx=sb, args=(value,), count=100_000_000)
    return sb
