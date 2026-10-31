"""Three mirrored pairs on the real image (image_emu.py): the engine's own code slices + the cave thunks + the real
band-map renderers, pixels read off a real Buffer (2026-10-25 wave-2 W2A: F30 / F31 / F38).

  council(g, con)       CouncilWin_exec's row block 0x427661..0x427779 (the text rect +0xBB4 and the VOTE button
                        +0xD04 from the console proposal rect 0x7AF5C0), then CouncilWin_repaint 0x426AD7..0x426B19 (the
                        d5a0 box, site 0x426B14) and CouncilWin_draw_proposal 0x426491..0x4264E2 / 0x426594..0x4265B0
                        (the d618 header band, site 0x4264DD; the d528 body box, site 0x4265AB) onto the console canvas
                        0x7AEC64 -- the user's 4K shot 20261024-233251 geometry exactly (VOTE x 1312..2530, y 1881..1931).
  prodpicker(g, ...)    ProdPicker_exec 0x494F48..0x494F81 on a picker object with its own canvas (the patched
                        thunk_pp_btnframe recomputes the union from the picker's fields; site 0x494F7C).
  dw_union(g, union)    DesignWin_repaint 0x437B59..0x437B8E (the union outset s(3), site 0x437B89).
  report_row(g, clip)   ReportIf_activate 0x4A4397..0x4A4528 (row L / R, the DATALINKS / CLOSE split; BaseButton_init
                        recorded, not run) then ReportWin_show's ring 0x496C96..0x496CD5 (t_rw_rowframe) on the canvas.

The runtime imm tables run at g with their own walkers (t_dl_immfix over g_rw_immtab, thunk_cw_immfix,
thunk_dw_immfix; VirtualProtect flagged done).  ONE boot per Rig (~3 s); each call re-runs at any g (~0.3 s).  The
pristine image has no g: every call is then the vanilla draw, whatever g.
"""
import sys
from pathlib import Path

import numpy as np

import image_emu as IE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI,  # noqa: E402
                               UC_X86_REG_ESI, UC_X86_REG_ESP)

G_VA, G_STRIPE = 0x668740, 0x66879C
CANVAS = 0x7AEC64                   # MainWin's console canvas (the council sites' dest; thunk_hud_boxframe keys on it)
CW_W, CW_H = 2600, 2000             # the console canvas here: holds the 4K shot's council box (x <= 2547, y <= 1948)
PICKER_W, PICKER_H = 1900, 1400
COUNCIL_CON_4K = (1295, 1683, 2547, 1948)    # the console proposal rect of the 4K shot (box = con inset s(4))
COUNCIL_CON_NATIVE = (124, 600, 652, 760)
REPORTIF, REPORTWIN, ROW = 0x885F38, 0x876478, 0x87E070


def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


class Rig:
    def __init__(self, exe, sym):
        IE.HEAP_SZ = max(IE.HEAP_SZ, 0x10000000)     # the band-map renderers allocate per draw on the bump heap
        e = self.e = IE.boot(exe, 3840, 2160)
        IE.Files(e)
        e.call(0x455610, args=(0,), count=0)            # load_interface: the box-sprite sets
        e.call(0x5D7670, ecx=CANVAS, args=(CW_W, CW_H, 0, 0))   # Buffer_init the console canvas
        self.sym = sym
        self.patched = bytes(e.uc.mem_read(0x4A4418, 1)) == b"\xE9"
        self.frame = e.alloc(0x400) + 0x200
        self.obj = e.alloc(0x4000)
        self.pk = None
        self.stops = set()
        self.recs = []
        self._rw_stubs()

    # ---------------------------------------------------------------- plumbing
    def set_g(self, g):
        e, S = self.e, self.sym
        if not self.patched:
            return
        e.w32(G_VA, g)
        e.w32(G_STRIPE, SL.stripe_period(g))
        e.w32(S["g_dl_vpdone"], 1)
        e.w32(S["g_dl_immg"], g)
        e.call(S["t_dl_immfix"], regs={UC_X86_REG_ESI: S["g_rw_immtab"]}, count=5_000_000)
        e.w32(S["g_cw_vpdone"], 1)
        e.call(S["thunk_cw_immfix"], count=5_000_000)
        e.w32(S["g_dw_vpdone"], 1)
        e.call(S["thunk_dw_immfix"], count=5_000_000)
        e.uc.ctl_flush_tb()

    def buf(self, b=CANVAS):
        e = self.e
        return e.r32(b + 0x54), e.s32(b + 0x38), abs(e.s32(b + 0x3C))

    def clear(self, b=CANVAS):
        bits, w, h = self.buf(b)
        self.e.uc.mem_write(bits, bytes(((w + 3) & ~3) * h))

    def pixels(self, b=CANVAS):
        bits, w, h = self.buf(b)
        st = (w + 3) & ~3
        return np.frombuffer(bytes(self.e.uc.mem_read(bits, st * h)), np.uint8).reshape(h, st)[:, :w].copy()

    def run(self, start, stop, regs, count=50_000_000):
        e = self.e
        if stop not in self.stops:
            e.observe(stop, lambda e: e.uc.emu_stop())
            self.stops.add(stop)
        r = {UC_X86_REG_EBP: self.frame}
        r.update(regs)
        e.call(start, regs=r, count=count)

    def _rw_stubs(self):
        """ReportIf_activate's non-geometry calls: BaseButton_init (records its 8 args), the label lookup / copy,
        the font set, the button render vcall and 0x5D5A70 -- the slice computes only the button rects."""
        e = self.e

        def bbinit(e):
            esp = e.reg(UC_X86_REG_ESP)
            self.recs.append(tuple(e.s32(esp + 4 + 4 * i) for i in range(8)))
            return 0
        self.lbl = e.cstr("X")
        e.stub_fn(0x607210, bbinit, 0x20)                # BaseButton_init (thiscall RET 0x20)
        e.stub_fn(0x6169A0, lambda e: self.lbl, 4)       # label lookup (thiscall RET 4)
        e.stub_fn(0x645470, lambda e: 0, 0)              # strcpy (cdecl)
        e.stub_fn(0x5DAC70, lambda e: 0, 0x10)           # Buffer_set_font (thiscall RET 0x10)
        e.stub_fn(0x5D5A70, lambda e: 0, 0)
        vt = e.alloc(0x200)
        ret = e.alloc(4)
        e.uc.mem_write(ret, b"\xC3")
        for k in range(0, 0x200, 4):
            e.w32(vt + k, ret)
        self.vt = vt

    # ---------------------------------------------------------------- the four draws
    def council(self, g, con):
        e = self.e
        self.set_g(g)
        self.clear()
        cw = self.obj
        for i, v in enumerate(con):
            e.w32(0x7AF5C0 + 4 * i, v)
        self.run(0x427661, 0x427779, {UC_X86_REG_EAX: cw + 0xBB4, UC_X86_REG_EBX: cw + 0xD04, UC_X86_REG_EDI: cw + 0xCD4,
                                      UC_X86_REG_ESI: cw})
        text = tuple(e.s32(cw + 0xBB4 + 4 * i) for i in range(4))
        vote = tuple(e.s32(cw + 0xD04 + 4 * i) for i in range(4))
        self.run(0x426AD7, 0x426B19, {UC_X86_REG_ESI: cw})
        self.run(0x426491, 0x4264E2, {UC_X86_REG_EBX: cw})
        self.run(0x426594, 0x4265B0, {UC_X86_REG_EBX: cw})
        return {"vote": vote, "text": text, "p": self.pixels()}

    def picker(self):
        e = self.e
        if self.pk is None:
            self.pk = e.alloc(0xB800)
            e.call(0x5D7210, ecx=self.pk + 0x444)                                   # Buffer_ctor
            e.call(0x5D7670, ecx=self.pk + 0x444, args=(PICKER_W, PICKER_H, 0, 0))   # Buffer_init
        return self.pk

    def prodpicker(self, g, count=4, vis=4):
        """-> (the button union per prodpicker_button_rects, the picker canvas)."""
        e = self.e
        self.set_g(g)
        pk = self.picker()
        self.clear(pk + 0x444)
        pitch = SL.prodpicker_row_pitch(g) if self.patched else 108
        e.w32(pk + 0xB6C, count)
        e.w32(pk + 0xA820, pitch)
        e.w32(pk + 0xA814, vis)
        rects = SL.prodpicker_button_rects(PICKER_W, count, pitch, vis, g if self.patched else 16)
        union = (rects[-1][0], rects[0][1], rects[0][2], rects[0][3])
        for i, v in enumerate(union):                   # the vanilla path (g <= 16 / pristine) reads these locals
            e.w32(self.frame - 0x28 + 4 * i, v)
        self.run(0x494F48, 0x494F81, {UC_X86_REG_EBX: pk})
        return union, self.pixels(pk + 0x444)

    def dw_union(self, g, union):
        e = self.e
        self.set_g(g)
        self.clear()
        for i, v in enumerate(union):
            e.w32(self.frame - 0x10 + 4 * i, v)
        self.run(0x437B59, 0x437B8E, {UC_X86_REG_EDI: CANVAS})
        return self.pixels()

    def report_row(self, g, clip):
        """-> {'row': (L, T, R, B) built by ReportIf_activate, 'btns': [(x0, x1) DATALINKS, CLOSE], 'p': canvas}."""
        e = self.e
        self.set_g(g)
        self.clear()
        for i, v in enumerate(clip):
            e.w32(0x87BDEC + 4 * i, v)
        e.w32(0x87D524, self.vt)
        e.w32(0x9B90F8, e.alloc(0x1000))
        self.recs.clear()
        self.run(0x4A4397, 0x4A4528, {UC_X86_REG_ESI: REPORTIF})
        row = tuple(e.s32(ROW + 4 * i) for i in range(4))
        btns = [(a[2], a[2] + a[4]) for a in self.recs]
        self.run(0x496C96, 0x496CD5, {UC_X86_REG_ESI: REPORTWIN, UC_X86_REG_EDI: CANVAS})
        return {"row": row, "btns": btns, "p": self.pixels()}


# ---------------------------------------------------------------- measuring
def channels(p, rect):
    """The dark channel between the half-open content rect [l, r) x [t, b) and the nearest lit pixel outward on its
    centre row / column: {'L', 'R', 'T', 'B'}, plus the stroke runs {'kL', 'kR', 'kT', 'kB'} (lit px in a row)."""
    l, t, r, b = rect
    ym, xm = (t + b) // 2, (l + r) // 2
    row, col = p[ym], p[:, xm]

    def run_out(line, start, step):
        i = start
        while line[i] == 0:
            i += step
        first = i
        while line[i] != 0:
            i += step
        return first, abs(i - first)
    xl, kl = run_out(row, l - 1, -1)
    xr, kr = run_out(row, r, 1)
    yt, kt = run_out(col, t - 1, -1)
    yb, kb = run_out(col, b, 1)
    return {"L": l - 1 - xl, "R": xr - r, "T": t - 1 - yt, "B": yb - b, "kL": kl, "kR": kr, "kT": kt, "kB": kb}


def report_channels(res):
    """F30: widths, seam and the ring channels (ring = the lit runs left of DATALINKS / right of CLOSE)."""
    (a0, a1), (b0, b1) = res["btns"]
    row = res["row"]
    ch = channels(res["p"], (a0, row[1], b1, row[3]))
    return {"wl": a1 - a0, "wr": b1 - b0, "seam": b0 - a1, "L": ch["L"], "R": ch["R"], "kL": ch["kL"], "kR": ch["kR"]}
