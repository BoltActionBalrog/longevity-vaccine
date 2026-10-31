"""The PREFERENCES window on the real image (image_emu.py), in the engine's order (2026-10-25 wave-6 W6A, F42; v2 the
mirror rule):

  screen(exe, W, H, page)  a fresh boot at 1024x768, the interface art and strings, then SW / SH written and g
                      recomputed by the image's own thunk_ensure_scale, the real MainWin_build 0x459680 at that screen
                      (it loads the slide-rail art -- without it slide_show draws no rails), the real PrefWin_build
                      0x48D840 (every page, button and slider, through thunk_pref_gwinit / _dlg2 / _attach) and the real
                      PrefWin_show 0x48FA00 (thunk_pref_show, the chrome draws, the page refresh, slide_show) up to its
                      modal loop (Win_modal_always 0x406840).  slide_show runs its no-animation path (the "animated
                      slides" pref bit 0x8000000 of [0x9A6490] cleared after the build): the four settled rail strips
                      are drawn onto the PrefWin canvas by the same sites either way.
Every PREF_FRAME_SITES call is observed at its E8 and at its return: the native rect handed to the site and the DRAWN
footprint (the bounding box of the canvas pixels the call changed, read in a window around the drawn rect).  The two
inner rail strips (0x45D851 / 0x45D875, dest = the PrefWin canvas) are observed the same way over the whole canvas: the
backdrop's borders are measured against the REAL rails.  The content (left-panel buttons, page list, More button,
the audio rows' Off toggles / sliders) are child windows: their rects are read from the engine (+0x13C, parent-relative).
"""
import os
import sys
from pathlib import Path

import numpy as np

import image_emu as IE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

PREFWIN = 0x8578D8
CANVAS = PREFWIN + 0x444
MAINWIN = 0x7AE820
SHOW, BUILD, MODAL, MAINWIN_BUILD = 0x48FA00, 0x48D840, 0x406840, 0x459680
ENSURE_SCALE = 0x668760
PREFS, SLIDE_ANIM = 0x9A6490, 0x8000000
VPDONE = ("g_vp_done", "g_cw_vpdone", "g_se_vpdone", "g_tech_vpdone", "g_dw_vpdone", "g_dl_vpdone", "g_rw_vpdone")
SITES = SL.PREF_FRAME_SITES
RAILS = {0x45D851: "inner_left", 0x45D875: "inner_right"}       # slide_show's settled inner strips (Sprite_draw_2)
#: the content child windows (PrefWin statics)
BUTTONS = (0x858338, 0x858E84, 0x8599D0, 0x85A51C, 0x85B068, 0x85BBB4, 0x85C700, 0x86FF5C, 0x8715F4, 0x870AA8)
LIST0 = 0x85D268                         # page 0's list window (every page list shares x / w / y)
MORE = 0x872140                          # PrefWin_btn_more, under the right panel's list (256, 360, 214, 20)
LABELS = (0x86C6E0, 0x86DD78, 0x86D22C, 0x86E8C4)              # the audio rows' Off toggles (label column), rows 0..3
SLIDERS = (0x862064, 0x8641B0, 0x8662FC, 0x868448)


def screen_for(g):
    return -(-1024 * g // 16), -(-768 * g // 16)


def _symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


class Rec:
    def __init__(self, e):
        self.e, self.rec, self.rails, self.pend = e, [], {}, {}
        for va in SITES:
            e.observe(va, self._pre)
            e.observe(va + 5, self._post)
        for va in RAILS:
            e.observe(va, self._pre_rail)
            e.observe(va + 5, self._post_rail)

    def _region(self, x0, y0, x1, y1):
        e = self.e
        bits, w, h = e.r32(CANVAS + 0x54), e.s32(CANVAS + 0x38), abs(e.s32(CANVAS + 0x3C))
        if not bits:
            return (0, 0), None
        st = (w + 3) & ~3
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        raw = bytes(self.e.uc.mem_read(bits + y0 * st, (y1 - y0) * st))
        return (x0, y0), np.frombuffer(raw, np.uint8).reshape(y1 - y0, st)[:, x0:x1].copy()

    def _pre(self, e):
        if e.reg(IE.UC_X86_REG_ECX) != CANVAS:
            return
        esp = e.reg(IE.UC_X86_REG_ESP)
        rp = e.r32(esp)
        rect = tuple(e.s32(rp + 4 * i) for i in range(4))
        g = max(16, e.r32(IE.GSCALE))
        win = tuple(((v * g) >> 4) + d for v, d in zip(rect, (-4, -4, 5, 5)))
        self.pend[e.reg(IE.UC_X86_REG_EIP)] = (rect, self._region(*win), win)

    def _post(self, e):
        va = e.reg(IE.UC_X86_REG_EIP) - 5
        if va not in self.pend:
            return
        rect, (org, before), win = self.pend.pop(va)
        _o, after = self._region(*win)
        self.rec.append((va, rect, _bbox(before, after, org)))

    def _pre_rail(self, e):
        if e.r32(e.reg(IE.UC_X86_REG_ESP)) != CANVAS:
            return
        self.pend[e.reg(IE.UC_X86_REG_EIP)] = (None, self._region(0, 0, 1 << 15, 1 << 15), None)

    def _post_rail(self, e):
        va = e.reg(IE.UC_X86_REG_EIP) - 5
        if va not in self.pend:
            return
        _r, (org, before), _w = self.pend.pop(va)
        _o, after = self._region(0, 0, 1 << 15, 1 << 15)
        bb = _bbox(before, after, org)
        if bb is not None and va not in self.rails:
            self.rails[va] = bb


def _bbox(before, after, org):
    if before is None or after is None:
        return None
    ys, xs = np.nonzero(after != before)
    if not len(xs):
        return None
    return int(xs.min()) + org[0], int(ys.min()) + org[1], int(xs.max()) + org[0], int(ys.max()) + org[1]


def screen(exe, w, h, page=4):
    """-> {'g', 'rec': [(site, native rect, drawn bbox)], 'rails': {site: drawn bbox}, 'p': the canvas,
    'kids': {static: rect}} (rects PrefWin-local, child rects half-open)."""
    os.environ.setdefault("SMACX_EXE_NAME", "terranx_PRACX.exe")
    IE.HEAP_SZ = max(IE.HEAP_SZ, 0x10000000)
    e = IE.boot(exe, 1024, 768)
    patched = bytes(e.uc.mem_read(0x4A4418, 1)) == b"\xE9"
    if patched:
        sym = _symtab()
        for k in VPDONE:
            e.w32(sym[k], 1)
    IE.Files(e)
    e.uc.mem_write(0x9B8AA8, b"xscript\0")
    e.call(0x455610, count=0)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
    e.call(0x616A00, count=50_000_000)
    e.stub_fn(0x514880, lambda e: 0, popbytes=4)        # MapWin repaint (the map window, not PrefWin)
    e.w32(IE.SW, w)
    e.w32(IE.SH, h)
    if patched:
        e.w32(IE.GSCALE, 0)
        e.call(ENSURE_SCALE)
    e.call(MAINWIN_BUILD, ecx=MAINWIN, count=2_000_000_000)     # the interface art, the slide rails' included
    e.w32(MAINWIN + 0x9C, e.r32(MAINWIN + 0x9C) | 1)
    r = Rec(e)
    e.call(BUILD, ecx=PREFWIN, count=200_000_000)
    e.w32(PREFS, e.r32(PREFS) & ~SLIDE_ANIM)
    e.observe(MODAL, lambda e: e.uc.emu_stop())
    try:
        e.call(SHOW, ecx=PREFWIN, args=(page,), count=2_000_000_000)
    except RuntimeError as x:
        if "stopped" not in str(x):
            raise
    rect = lambda a: tuple(e.s32(a + 0x13C + 4 * i) for i in range(4))   # noqa: E731
    kids = {a: rect(a) for a in BUTTONS + (LIST0, MORE) + LABELS + SLIDERS}
    out = {"g": e.r32(IE.GSCALE) if patched else 16, "rec": r.rec, "rails": r.rails, "p": IE.canvas_of(e, PREFWIN),
           "kids": kids}
    del e
    return out


def frames(res):
    """{site: drawn bbox} -- the FIRST draw of each site onto a fresh canvas (a repeat draw over identical pixels only
    changes what was drawn over it in between, so its pixel diff is not its footprint)."""
    out = {}
    for va, _rect, bbox in res["rec"]:
        if bbox is not None and va not in out:
            out[va] = bbox
    return out


def measure(res):
    """The PrefWin channels (device px) that are mirrored in vanilla, from the drawn footprints (inclusive), the REAL
    inner rails and the engine's child rects: (left / top value, right / bottom value) per pair."""
    g = res["g"]
    k = SL.stroke_width(g) if g > 16 else 1
    f = frames(res)
    bd, inn, lp = f[0x48FB19], f[0x48FB29], f[0x48FB39]
    rp = f.get(0x48FBB7, f.get(0x491C42))
    sf = f.get(0x491C8C, f.get(0x48FC01))
    rl, rr = res["rails"][0x45D851], res["rails"][0x45D875]
    kid = res["kids"]
    btn = [kid[a] for a in BUTTONS]
    bl, bt, br, bb = min(b[0] for b in btn), min(b[1] for b in btn), max(b[2] for b in btn), max(b[3] for b in btn)
    li, rs = kid[LIST0], kid[MORE]
    lab = [kid[a] for a in LABELS]
    sl = [kid[a] for a in SLIDERS]
    bd_in_l = max(bd[0] + k, rl[2] + 1)                 # the backdrop's inner edge: its border or the rail over it
    bd_in_r = min(bd[2] - k + 1, rr[0])
    m = {"rails>backdrop L|R": (bd[0] - rl[2] - 1, rr[0] - bd[2] - 1),
         "backdrop border L|R": (bd_in_l - max(bd[0], rl[2] + 1), min(bd[2] + 1, rr[0]) - bd_in_r),
         "backdrop>inner L|R": (inn[0] - bd_in_l, bd_in_r - inn[2] - 1),
         "backdrop>inner T|B": (inn[1] - (bd[1] + k), (bd[3] - k + 1) - inn[3] - 1),
         "inner>panels L|R": (lp[0] - (inn[0] + k), (inn[2] - k + 1) - rp[2] - 1),
         "inner>left panel T|B": (lp[1] - (inn[1] + k), (inn[3] - k + 1) - lp[3] - 1),
         "inner>right panel T|B": (rp[1] - (inn[1] + k), (inn[3] - k + 1) - rp[3] - 1),
         "left panel>buttons L|R": (bl - (lp[0] + k), (lp[2] - k + 1) - br),
         "left panel>buttons T|B": (bt - (lp[1] + k), (lp[3] - k + 1) - bb),
         "right panel>list L|R": (li[0] - (rp[0] + k), (rp[2] - k + 1) - li[2]),
         "right panel>list T | More B": (li[1] - (rp[1] + k), (rp[3] - k + 1) - rs[3]),
         "~panel gap": rp[0] - lp[2] - 1}
    if sf is not None:
        m["right panel>slider frame L|R"] = (sf[0] - (rp[0] + k), (rp[2] - k + 1) - sf[2] - 1)
        m["slider frame>labels T|B"] = (min(b[1] for b in lab) - (sf[1] + k), (sf[3] - k + 1) - max(b[3] for b in lab))
        m["slider frame>labels L | sliders R"] = (min(b[0] for b in lab) - (sf[0] + k),
                                                  (sf[2] - k + 1) - max(b[2] for b in sl))
    return m
