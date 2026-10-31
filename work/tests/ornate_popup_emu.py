"""Real-image ornate popup renderer for the fix-26 guard (tests/test_scaling_ornate_popup_symmetry.py).

The REAL terranx_PRACX image (baked / pristine / a mutant) under Unicorn: every engine function and every cave thunk
runs for real; only OS imports (host GDI for font metrics, read-only game files) and a short explicit list of leaf
primitives are served by Python.  Ported from the audit18..20 harnesses (scratch), which reproduced the
user's ornate-popup shots stroke for stroke (4K 20261022-204501 SELECT A FACTION and 204405 tutorial window:
every emulated stroke pixel equals the shot).

Builders replay each caller's exact sequence (re-derived from the pristine bytes), so the frame, title band, rings,
text boxes and child windows are drawn in the engine's own call order (feedback-emulate-engine-call-order):
  EW  EDITORWHO picker  Console_editor_diplomacy 0x4DB932..: Popup_ctor 0x4048A0, PDS=6, Popup_start via 0x43EF70,
      7 x Dialog add 0x612A70, BasePop_exec_3(0, 0).
  PK  PICKUNIT          veh_pick 0x48D0D0 (unit-sprite painters stubbed: they only paint the unit picture).
  RN  #RENAME / NB #NEWBASE  the generic script popup 0x5BFAB0 (#RENAME call site 0x41A37D), base screen up for RN
      (Popup_calc 0x404BE8 turns type 0/5 into 6); NB is a FLAT popup (no base screen -> type 0).
  TW  TutWin LANDFALL   TutWin_tut_win 0x4BDFE0 on the global TutWin 0x8C6E68 (labels lookup + the GDI pointer line
      stubbed).
  GO / VO / MR / GF  GOVOPTIONS (a type-1 list in an ornate popup), COUNCILVOTE, MPRECEIVEFILE (untitled ornate body
      box) and GOVOPTIONS flat, through the script popup 0x5BF3F0 (label, flags, 0).
  GV  GOVERNOR          the Planetary Governor art popup, popp(script, "GOVERNOR", 0, "council_sm.pcx", 0) 0x48C0A0 --
      its caller 0x428542's exact args (W9C F54; a flat popup with art and body text, no dialog).
  UP  UPHEAVAL          an art popup WITH a dialog list, popp(script, "UPHEAVAL", 0, "talent_sm.pcx", 0) (W9C F54 reach).
  PD  NERVESTAPLED      a plain text + OK popup (no art, no dialog), flat, through the script popup 0x5BF3F0 (flags 0).
Captures: the popup canvas at DRAW #1 (0x602B88) plus every child GraphicWin's canvas (stop at Win_set_modal
0x603714).  Child pixels are tagged index + 256.

The low-level layer (Emu, boot, Files, canvas_of) is image_emu.py, shared with fix 29's popup_listbox_emu.py.
"""
import gc
import sys
from pathlib import Path

import numpy as np
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_ESP  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent))
from image_emu import GAME, PDS, Emu, Files, boot, canvas_of  # noqa: E402,F401  (the shared low-level layer)


class H:
    def __init__(self, exe, W, Hh, kind, label=None, n_items=7, item_text=None, mainwin=True, ornate_mode=False,
                 flags=0x18, later=True, hooks=(), pcx=None):
        e = self.e = boot(exe, W, Hh)
        self.files = Files(e)
        e.uc.mem_write(0x9B8AA8, b"xscript\0")
        self.g = e.r32(0x668740)
        for va, cb in hooks:                      # caller observers (e.g. the ornate blit capture), from boot on
            e.observe(va, cb)
        if mainwin:
            e.w32(0x7AE820 + 0x9C, e.r32(0x7AE820 + 0x9C) | 1)
            e.w32(0x7AE820 + 0xC4, 0)
            e.w32(0x7AF59C, (213 * self.g) >> 4 if self.g > 16 else 213)
        if ornate_mode:
            top = e.r32(0x7D392C)
            e.w32(0x7AE778 + 4 * top, 1)
        e.call(0x455610, count=0)                 # load_interface (the real frame art)
        self.gw = []
        self.pop = None
        self.draw1 = None
        self.bg = 0
        e.observe(0x5D4EF0, self._gw)
        e.observe(0x405C80, self._bgc)
        e.observe(0x602B88, self._d1)
        e.observe(0x603714, lambda e: e.uc.emu_stop())
        if kind == "EDITORWHO":
            self._editorwho(label or "EDITORWHO", n_items, item_text)
        elif kind == "PICKUNIT":
            self._pickunit(label or "PICKUNIT", n_items, item_text)
        elif kind == "XPOP":
            self._xpop(label, flags)
        elif kind == "TUTWIN":
            self.pop = 0x8C6E68
            close = e.cstr("Close")
            e.stub_fn(0x6169A0, lambda e: close, popbytes=4)      # labels lookup (labels.txt not loaded in the emu)
            if e.r32(0x9B90F8) == 0:
                e.w32(0x9B90F8, e.alloc(0x1000))                   # the label index table the lookup is fed from
            e.stub_fn(0x5F2AC0, lambda e: 0, popbytes=28)         # Win_window_line_raw: the GDI pointer line (not the frame)
            try:
                e.call(0x4BDFE0, ecx=0x8C6E68, args=(0x7AE820, e.cstr(label or "LANDFALL"), 1200, 700, 0, 0x100,
                                                     0xFFFFFFFF, 0xFFFFFFFF))
            except RuntimeError as x:
                if "stopped" not in str(x):
                    raise
        elif kind == "XPOP2":
            e.call(0x5BF3F0, args=(e.cstr(label), flags, 0))
        elif kind == "POPP":                      # popp(script, label, 0, pcx, 0) 0x48C0A0: an art popup (W9C F54)
            try:
                e.call(0x48C0A0, args=(0x9B8AA8, e.cstr(label), 0, e.cstr(pcx), 0), count=900_000_000)
            except RuntimeError as x:
                if "stopped" not in str(x):
                    raise
        else:
            raise ValueError(kind)
        p = self.pop
        self.typ_raw = e.s32(p + 0x30AC)
        self.placed = (e.s32(p + 0x30B4), e.s32(p + 0x30B8))
        self.children = []
        par = {g[0]: g[5] for g in self.gw}

        def absxy(win):
            if win == p or win not in par:
                return (0, 0)
            px, py = absxy(par[win])
            return (px + e.s32(win + 0x13C), py + e.s32(win + 0x140))
        for (win, x, y, w, h, parent) in self.gw:
            if win == p:
                continue
            c = canvas_of(e, win)
            ax, ay = absxy(win)
            self.children.append(dict(win=win, x=ax, y=ay, w=w, h=h, flags=parent, canvas=c,
                                      clip=(absxy(parent) + (e.s32(parent + 0x474 + 8), e.s32(parent + 0x474 + 12)))
                                      if parent != p else None))
        self.final_children = self.children
        self.later = None
        if later:
            e.call(e.r32(e.r32(p) + 0x30), ecx=p)
            self.later = canvas_of(e, p)

    # ---------------------------------------------------------------- observers
    def _gw(self, e):
        esp = e.reg(UC_X86_REG_ESP)
        a = [e.s32(esp + 4 + 4 * i) for i in range(7)]
        win = e.reg(UC_X86_REG_ECX)
        self.gw = [g for g in self.gw if g[0] != win] + [(win, a[0], a[1], a[2], a[3], a[6] & 0xFFFFFFFF)]

    def _bgc(self, e):
        self.bg += 1
        if self.pop is None:
            self.pop = e.reg(UC_X86_REG_ECX)

    def _d1(self, e):
        p = e.reg(UC_X86_REG_ESI)
        if self.draw1 is None:
            self.draw1 = canvas_of(e, p)
            self.pop = p

    # ---------------------------------------------------------------- builders
    def _editorwho(self, label, n, text):
        e = self.e
        p = e.alloc(0xB000)
        e.call(0x4048A0, ecx=p)
        e.w32(PDS, 6)
        e.call(0x43EF70, ecx=p, args=(0x9B8AA8, e.cstr(label), 0xFFFFFFFF, 0, 0x40))
        names = text or ["Gaians", "Hive", "University", "Morganites", "Spartans", "Believers", "Peacekeepers"]
        for i in range(n):
            e.call(0x612A70, ecx=p + 0x21D0, args=(e.cstr(names[i % len(names)]), i + 1))
        self.pop = p
        e.call(0x602600, ecx=p, args=(0, 0))
        e.w32(PDS, 0)

    def _pickunit(self, label, n, text):
        e = self.e
        p = e.alloc(0x5400)
        b = 0x53B4
        e.call(0x4048A0, ecx=p)
        spr = e.alloc(0x100)
        e.call(0x5E37E0, ecx=spr)
        e.call(0x5EAF3F, ecx=spr, args=(0x64, 0x4B, e.r32(0x696D14) & 0xFF))
        e.call(0x406380, ecx=p, args=(0x9B8AA8, e.cstr(label), 0xFFFFFFFF, 0, 0x800, 0))
        for off, v in ((0x22B0, 1), (0x22AC, 2), (0x3158, 1), (0x3154, 2)):
            e.w32(p + b - off, v)
        t = text or "Hardened (+) Clean String Shock Troops"
        for i in range(n):
            e.w32(p + b - 0x3270, spr if e.r32(p + b - 0x3140) == 0 else 0)
            e.call(0x6108E0, ecx=p + b - 0x3174, args=(spr, e.cstr(t), i))
        stub = e.alloc(16)
        e.uc.mem_write(stub, b"\x31\xC0\xC3")             # xor eax,eax / ret: the unit-sprite painters
        for off in (0x224C, 0x3110, 0x2254, 0x2250):
            e.w32(p + b - off, stub)
        e.w32(PDS, 6)
        self.pop = p
        e.call(0x602600, ecx=p, args=(0, 0))
        e.w32(PDS, 0)

    def _xpop(self, label, flags):
        e = self.e
        buf = e.alloc(0x100)
        e.uc.mem_write(buf, b"Sparta Command\0")
        try:
            e.call(0x5BFAB0, args=(e.cstr(label), flags, buf, 0, 0))
        except RuntimeError as x:
            if "stopped" not in str(x):
                raise

    # ---------------------------------------------------------------- composite (popup canvas + child windows)
    def composite(self, which="draw1"):
        base = (self.draw1 if which == "draw1" else self.later).copy().astype(np.int16)
        for c in self.children:
            cv = c["canvas"]
            if cv is None:
                continue
            x, y = c["x"], c["y"]
            if c.get("clip"):
                px, py, pw, ph = c["clip"]
                x0, y0 = max(x, px), max(y, py)
                x1, y1 = min(x + cv.shape[1], px + pw), min(y + cv.shape[0], py + ph)
                cv = cv[y0 - y:y1 - y, x0 - x:x1 - x]
                x, y = x0, y0
            h, w = cv.shape
            if x < 0 or y < 0 or x + w > base.shape[1] or y + h > base.shape[0]:
                continue
            base[y:y + h, x:x + w] = cv.astype(np.int16) + 256         # child pixels tagged (index + 256)
        return base


# ================================================================ measurement
STROKE = (31, 34)


def runs(mask):
    out, s = [], None
    for i, b in enumerate(list(mask) + [False]):
        if b and s is None:
            s = i
        if not b and s is not None:
            out.append((s, i))
            s = None
    return out


def sig_rows(c, x0, x1, idx=STROKE):
    """[(y0, y1, [(start, end, idx), ...])] rows grouped by identical stroke-run signature in [x0, x1)."""
    out = []
    for y in range(c.shape[0]):
        row = c[y, x0:x1]
        sig = []
        for v in idx:
            for s, e in runs(row == v):
                sig.append((x0 + s, x0 + e, v))
        sig = tuple(sorted(sig))
        if out and out[-1][2] == sig and out[-1][1] == y:
            out[-1][1] = y + 1
        else:
            out.append([y, y + 1, sig])
    return out


def content_span(c, y, bg=(256 + 65, 256 + 84, 256 + 9)):
    row = c[y]
    xs = [x for x in range(c.shape[1]) if row[x] >= 256 and row[x] not in bg]
    return (xs[0], xs[-1] + 1) if xs else None



def groups(c, side, strip=140, minh=3):
    W = c.shape[1]
    x0, x1 = (0, strip) if side == "L" else (W - strip, W)
    return [g for g in sig_rows(c, x0, x1) if g[1] - g[0] >= minh]


def analyse(c):
    W = c.shape[1]
    out = {"W": W}
    gl, gr = groups(c, "L"), groups(c, "R")
    # title rows: the tallest group whose 3rd-from-edge run is idx 34 (line 31, outer 31, inner 34)
    def title(gs, side):
        cand = [g for g in gs if len(g[2]) == 3 and [r[2] for r in (g[2] if side == "L" else g[2][::-1])] == [31, 31, 34]]
        return min(cand, key=lambda g: g[0]) if cand else None
    tl, tr = title(gl, "L"), title(gr, "R")
    if not tl or not tr:
        return None
    line_l, outer_l, inner_l = tl[2]
    inner_r, outer_r, line_r = tr[2]
    out["rows_title"] = (tl[0], tl[1])
    out["line"] = (line_l[:2], line_r[:2])
    out["outer"] = (outer_l[:2], outer_r[:2])
    out["inner"] = (inner_l[:2], inner_r[:2])
    out["ch_line_band"] = (outer_l[0] - line_l[1], line_r[0] - outer_r[1])
    out["ch_band_inner"] = (inner_l[0] - outer_l[1], outer_r[0] - inner_r[1])
    out["off_line"] = (line_l[0], W - line_r[1])
    out["off_outer"] = (outer_l[0], W - outer_r[1])
    tb = tl[1]
    # below the title: groups with (line, ring) or (line, ring, textbox)
    below_l = [g for g in gl if g[0] >= tb + 2]
    below_r = [g for g in gr if g[0] >= tb + 2]
    # ring: the tallest group with >= 2 runs whose first (L) / last (R) run is the line
    def ring_group(gs, side):
        cand = [g for g in gs if len(g[2]) >= 2]
        return max(cand, key=lambda g: g[1] - g[0]) if cand else None
    rl, rr = ring_group(below_l, "L"), ring_group(below_r, "R")
    if rl and rr:
        ring_l = rl[2][1]
        ring_r = rr[2][-2]
        out["ring"] = (ring_l[:2], ring_r[:2])
        out["off_ring"] = (ring_l[0], W - ring_r[1])
        out["ch_line_ring"] = (ring_l[0] - line_l[1], line_r[0] - ring_r[1])
        out["inner_to_ring"] = (ring_l[0] - inner_l[0], inner_r[1] - ring_r[1])     # 0 flush, + ring inside
        out["outer_to_ring"] = (ring_l[0] - outer_l[0], outer_r[1] - ring_r[1])     # 0 flush, - ring sticks out
        ym = (max(rl[0], rr[0]) + min(rl[1], rr[1])) // 2
        cs = content_span(c, ym)
        if cs and cs[0] > ring_l[1] and cs[1] < ring_r[0]:
            out["content"] = cs
            out["ch_ring_content"] = (cs[0] - ring_l[1], ring_r[0] - cs[1])
    # text box (idx 34 runs below the title)
    tbl = [g for g in below_l if any(r[2] == 34 for r in g[2])]
    tbr = [g for g in below_r if any(r[2] == 34 for r in g[2])]
    if tbl and tbr:
        a = max(tbl, key=lambda g: g[1] - g[0])
        b = max(tbr, key=lambda g: g[1] - g[0])
        x_l = [r for r in a[2] if r[2] == 34][0]
        x_r = [r for r in b[2] if r[2] == 34][-1]
        out["textbox"] = (x_l[:2], x_r[:2])
        out["inner_to_textbox"] = (x_l[0] - inner_l[0], inner_r[1] - x_r[1])
        out["ch_line_textbox"] = (x_l[0] - line_l[1], line_r[0] - x_r[1])
        if "ring" in out:
            out["ch_ring_textbox"] = (x_l[0] - out["ring"][0][1], out["ring"][1][0] - x_r[1])
    return out




def buttons(children):
    """The bottom row of child windows (the OK / CANCEL bar): (left, right) half-open, popup-canvas x."""
    if not children:
        return None
    ymax = max(c["y"] for c in children)
    row = [c for c in children if c["y"] == ymax and c["h"] <= 80]
    if not row:
        return None
    return min(c["x"] for c in row), max(c["x"] + c["w"] for c in row)


def pairs(c, children):
    """analyse() + line -> buttons (frame green line to the button row's ends)."""
    a = analyse(c)
    if not a:
        return None
    b = buttons(children)
    if b:
        a["line_btn"] = (b[0] - a["line"][0][1], a["line"][1][0] - b[1])
    return a


# ================================================================ cases
CASES = {
    "EW": dict(kind="EDITORWHO"),
    "PK": dict(kind="PICKUNIT", n_items=16),
    "RN": dict(kind="XPOP", label="RENAME", ornate_mode=True, flags=0x18),
    "NB": dict(kind="XPOP", label="NEWBASE", ornate_mode=False, flags=0x17),
    "TW": dict(kind="TUTWIN", label="LANDFALL"),
    "GO": dict(kind="XPOP2", label="GOVOPTIONS", ornate_mode=True, flags=0x41),    # type-1 list in an ornate popup
    "VO": dict(kind="XPOP2", label="COUNCILVOTE", ornate_mode=True, flags=0x41),
    "MR": dict(kind="XPOP2", label="MPRECEIVEFILE", ornate_mode=True, flags=0),    # untitled ornate body box
    "GF": dict(kind="XPOP2", label="GOVOPTIONS", ornate_mode=False, flags=0x41),   # the same, flat
    "GV": dict(kind="POPP", label="GOVERNOR", pcx="council_sm.pcx", later=False),  # the art popup (W9C F54)
    "UP": dict(kind="POPP", label="UPHEAVAL", pcx="talent_sm.pcx", later=False),   # art + a dialog list (W9C F54)
    "PD": dict(kind="XPOP2", label="NERVESTAPLED", ornate_mode=False, flags=0, later=False),  # plain text + OK, flat
}


def render(exe, case, w, h, hooks=()):
    """Boot `exe` at w x h, build `case` with the engine's own call order; returns a dict: g, typ, placed, d1 (popup
    canvas at DRAW #1 + child windows), later (after a full vtbl+0x30 redraw + children), children (rects).
    hooks: (va, callback(emu)) observers installed right after boot."""
    hh = H(exe, w, h, hooks=hooks, **CASES[case])
    kids = [{k: v for k, v in c.items() if k != "canvas"} for c in hh.children]
    out = dict(g=hh.g, typ=hh.typ_raw, placed=hh.placed, d1=hh.composite("draw1"),
               later=hh.composite("later") if hh.later is not None else None, children=kids)
    # the emulator (~170 MB committed) sits in a reference cycle (its hooks close over it): free it NOW, not at the
    # next GC -- under xdist dozens of workers render at once (a -k scaling run hit UC_ERR_NOMEM without this)
    hh.e.uc = None
    hh.e = None
    del hh
    gc.collect()
    return out
