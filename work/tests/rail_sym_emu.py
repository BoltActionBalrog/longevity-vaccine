"""Real-image rail scrollbar harness for the W3B guard (tests/test_scaling_rail_sym_e2e.py).

Builds the popup family's rail bar on the REAL terranx_PRACX image (popup_listbox_emu.py's GOTO popup on image_emu.py,
every engine function and cave thunk running for real) with more rows than fit, so Popup_show calls rail_slide_in: the
strip bake (thunk_rail_bake -> t_rsb_blit), the bar fit (thunk_rail_sbfit), ScrollBar_draw (arrows through
thunk_btn_shrink / thunk_btn_2dscale -> t_rsb_zoom, the grip through thunk_sb_thumb -> t_rsb_grip), in the engine's own
order.  Two pieces of MainWin_build / startup state the popup harness does not emulate are loaded here, from the game's
own files through the engine's own loaders:
  * the 8 console rail sprites (MainWin+0x216F4.. / +0x217A4..: top cap, mid tile, bottom cap, filler, the four slide
    strips) -- Buffer_load_pcx 0x5D7DE0("console_x2_A.pcx", 0, 0xA, 0xEC) then Sprite cut 0x5E39A0 with
    MainWin_build's own rects (0x45A3D8..0x45A5C6, the non-800 arm);
  * the scrollbar art (g_scrollbar_sprite_block 0x791D88: arrow faces, grip, trough) -- load_icons 0x4547E0.
composite() lays every visible child canvas over its parent's at its parent-relative rect, key 9 transparent (the
engine's own child composite is keyed the same way); measure() reads the bar column off the canvases.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import image_emu as E  # noqa: E402
import popup_listbox_emu as P  # noqa: E402
import scaling_laws as SL  # noqa: E402

MAINWIN = 0x7AE820
RAIL_CUTS = (  # (sprite VA, x, y, w, h) -- MainWin_build's console_x2_A cuts (ScreenWidth != 800)
    (MAINWIN + 0x217A4, 0x2C9, 1, 0xF, 0x211), (MAINWIN + 0x217D0, 0x2D9, 1, 8, 0x211),
    (MAINWIN + 0x217FC, 0x2E2, 1, 8, 0x211), (MAINWIN + 0x21828, 0x2EB, 1, 0xF, 0x211),
    (MAINWIN + 0x216F4, 1, 0x117, 0x20, 0x1A), (MAINWIN + 0x21720, 1, 0x132, 0x20, 0x22),
    (MAINWIN + 0x2174C, 1, 0x155, 0x20, 0x19), (MAINWIN + 0x21778, 1, 0x16F, 0x20, 0x22))
KEY = 9
POPUP_SB = 0x3230                  # the popup family's rail bar
SB_UP, SB_DN = 0xAAC, 0x15F8
TROUGH = (0x41, 0xC5)
CYAN = 0xAE
RES = dict(P.RES)
RES.update({30: (2560, 1440)})     # 1440p, the clamp-free middle of the 25..31 band (nn(32) = 2g + 1)


def load_rail_art(e):
    buf = e.alloc(0x600)
    e.call(0x5D7210, ecx=buf)                                                  # Buffer ctor
    e.call(0x5D7DE0, ecx=buf, args=(e.cstr("console_x2_A.pcx"), 0, 0xA, 0xEC), count=200_000_000)
    key = e.uc.mem_read(0x696D14, 1)[0]
    for va, x, y, w, h in RAIL_CUTS:
        e.call(0x5E39A0, ecx=va, args=(buf, key, x, y, w, h, 0), count=50_000_000)
        assert (e.s32(va + 0x18), e.s32(va + 0x1C)) == (w, h), hex(va)
    e.call(0x4547E0, count=500_000_000)                                       # load_icons: the scrollbar art


GRIP_SITE = 0x6067ED                # ScrollBar_draw's grip Sprite_draw_2 call (thunk_sb_thumb's site)


def build(exe: str, g: int, nrows: int = 40):
    """The GOTO popup with nrows bases on `exe` at RES[g]; returns the popup_listbox_emu Run with .thumb_rects = the
    thumb rect (L, T, R, B, bar-canvas local) of every grip draw, read off ScrollBar_draw's frame at the site."""
    P.RES.setdefault(g, RES[g])
    rects = []

    def patch(e):
        load_rail_art(e)

        def at_grip(e):
            sp = e.reg(E.UC_X86_REG_ESP)
            rects.append((e.reg(E.UC_X86_REG_ESI), tuple(e.s32(sp + 0x24 + 4 * i) for i in range(4))))
        e.observe(GRIP_SITE, at_grip)
    run = P.Run(exe, g, nrows=nrows, patch=patch)
    run.thumb_rects = [r for b, r in rects if b == run.pop + POPUP_SB]
    return run


def rect(e, w):
    return tuple(e.s32(w + 0x13C + 4 * i) for i in range(4))


def composite(e, win):
    can = E.canvas_of(e, win).copy()
    for i in range(max(0, min(e.s32(win + 0x3FC), 150))):
        c = e.r32(win + 0x1A4 + 4 * i)
        if not c or not (e.r32(c + 0x9C) & 1):
            continue
        sub = composite(e, c)
        x, y, _r, _b = rect(e, c)
        h, w = sub.shape
        y0, y1, x0, x1 = max(0, y), min(can.shape[0], y + h), max(0, x), min(can.shape[1], x + w)
        if y1 <= y0 or x1 <= x0:
            continue
        part = sub[y0 - y:y1 - y, x0 - x:x1 - x]
        view = can[y0:y1, x0:x1]
        view[part != KEY] = part[part != KEY]
    return can


def colspan(a, keep):
    cols = [x for x in range(a.shape[1]) if keep(a[:, x]).any()]
    return (min(cols), max(cols) + 1) if cols else None


def spans(row, pred):
    out, s = [], None
    for i, v in enumerate(row):
        if pred(v):
            s = i if s is None else s
        elif s is not None:
            out.append((s, i))
            s = None
    if s is not None:
        out.append((s, len(row)))
    return out


def measure(run, g: int) -> dict:
    """Strip-local spans of the drawn bar assembly: cyan lines, the bar window, both arrow plates (non-key columns of
    each arrow canvas), the grip (non-trough columns of the bar canvas between the arrows) and its rows."""
    e = run.e
    sb = run.pop + POPUP_SB
    comp = composite(e, run.pop)
    cw = comp.shape[1]
    x0 = SL.rail_strip_x(cw, g)
    sx, sy, sr, sbt = rect(e, sb)
    bar = (sx - x0, sr - x0)
    out = dict(g=g, cw=cw, x0=x0, bar=bar, wc=SL.rail_col_w(cw, g), comp=comp)
    for nm, off in (("up", SB_UP), ("dn", SB_DN)):
        a = E.canvas_of(e, sb + off)
        ax = rect(e, sb + off)
        sp = colspan(a, lambda c: c != KEY)
        out[nm] = (sp[0] + ax[0] + bar[0], sp[1] + ax[0] + bar[0]) if sp else None
    b = E.canvas_of(e, sb)
    ua, da = rect(e, sb + SB_UP), rect(e, sb + SB_DN)
    mid = b[ua[3]:da[1]]
    grip = lambda c: ~np.isin(c, TROUGH + (KEY,))                         # noqa: E731
    sp = colspan(mid, grip)
    out["thumb"] = (sp[0] + bar[0], sp[1] + bar[0]) if sp else None
    rows = [y for y in range(mid.shape[0]) if grip(mid[y]).any()]
    out["thumb_rows"] = (rows[0], rows[-1] + 1) if rows else None
    tl, tt, tr, tb = run.thumb_rects[-1]                                 # the last grip draw's thumb rect
    out["thumb_rect"] = (tl + bar[0], tt - ua[3], tr + bar[0], tb - ua[3])   # strip-local x, mid-local y
    probe = sy + ua[3] + (rows[-1] + 8 if rows else 8)
    out["lines"] = spans(comp[probe, x0:x0 + out["wc"]], lambda v: v == CYAN)
    out["probe_row"] = probe
    return out
