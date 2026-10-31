"""Two mirrored pairs on the real image (image_emu.py), in the engine's order (2026-10-25 wave-3 W3A):

  screen(W, H)  the real MainWin_build 0x459680 at that screen (SW / SH written, g recomputed by the image's own
                thunk_ensure_scale) -- the HUD seeds, the console proposal rect 0x7AF5C0 (= MainWin +0xDA0), the
                scenario-editor seeds (thunk_ed_seeds -> t_ed_redchain), the unions / info rect, every BaseButton_init
                (recorded, run for real).  Re-running it on one boot gives the same canvases as a fresh boot per screen
                (checked when this harness was built), so ONE boot serves every screen of a module.
  editor()      mode 0x3EA + the real centre painter MainWin_draw_center_mode 0x45BC50 (thunk_ed_painter, the three
                engraved frames through thunk_pp_boxsprite, painter_editor_info) on MainWin's real canvas 0x7AEC64;
                -> the strokes on the red-brush union's mid row (palette union R, red union L / R, info L / R) and the
                M / I / TOOLBAR column's left edge, the red FlatButtons' windows.
  council()     CouncilWin_exec's row block 0x427661 .. 0x427789 on the real CouncilWin static 0x6FEC80 and the real
                console rect, THROUGH the E8 @0x427784 (t_cw_rowsym -> thunk_cw_seeds -> Font_init), then the three
                BaseButton_init argument builds of the YES / NO / ABSTAIN row (0x427A62 / 0x427B47 / 0x427BB6;
                BaseButton_init stubbed for these three only, the args recorded) and the d5a0 box / d618 / d528 draws
                (0x426AD7 / 0x426491 / 0x426594 slices, as halfopen_frames_emu) on the canvas.
The runtime imm tables run at g with the image's own walkers (thunk_cw_immfix; the editor's thunk_ed_immfix runs
inside MainWin_build); VirtualProtect is flagged done (the emulated image is RWX).  The pristine image has no g: every
screen is then the vanilla draw.
"""
import struct
import sys
from pathlib import Path

import numpy as np

import image_emu as IE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI  # noqa: E402

MW = 0x7AE820
CANVAS = MW + 0x444                 # 0x7AEC64
CWIN = 0x6FEC80                     # CouncilWin (static; its ctor runs at boot)
BB_INIT = 0x607210                  # BaseButton_init (thiscall RET 0x20)
ENSURE_SCALE = 0x668760
VPDONE = ("g_vp_done", "g_cw_vpdone", "g_se_vpdone", "g_tech_vpdone", "g_dw_vpdone", "g_dl_vpdone", "g_rw_vpdone")
RED_LO, RED_N, BTN_STRIDE = 0x7C8CD0, 6, 0xB4C            # the 6 red-brush FlatButtons (MainWin +0x1A4B0)
MI_I = MW + 0xA3C                                         # the HUD I button rect (M / I / TOOLBAR column)
#: (thirds index, slice start, slice end (after the BaseButton_init call))
THIRD_SLICES = ((0, 0x427A62, 0x427A8E), (1, 0x427B47, 0x427B80), (2, 0x427BB6, 0x427BEF))


def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


def runs(line, bg):
    """[(first, last)] of the pixels != bg."""
    nz = np.nonzero(line != bg)[0]
    out = []
    for v in nz:
        if out and v == out[-1][1] + 1:
            out[-1][1] = int(v)
        else:
            out.append([int(v), int(v)])
    return [tuple(r) for r in out]


class Rig:
    def __init__(self, exe, sym):
        IE.HEAP_SZ = max(IE.HEAP_SZ, 0x10000000)
        e = self.e = IE.boot(exe, 1024, 768)
        self.sym = sym
        self.patched = bytes(e.uc.mem_read(0x4A4418, 1)) == b"\xE9"
        if self.patched:
            for k in VPDONE:
                e.w32(sym[k], 1)
        IE.Files(e)
        e.call(0x455610, count=0)
        e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
        e.call(0x616A00, count=50_000_000)
        e.stub_fn(0x514880, lambda e: 0, popbytes=4)    # MapWin repaint after the centre arm (the map window, not MainWin)
        self.frame = e.alloc(0x800) + 0x400
        self.bb = []
        self.rec = False
        e.observe(BB_INIT, self._bb)
        self.stops = set()
        self.screen_wh = None

    def _bb(self, e):
        if self.rec:
            esp = e.reg(IE.UC_X86_REG_ESP)
            self.bb.append((e.reg(IE.UC_X86_REG_ECX), tuple(e.s32(esp + 4 + 4 * i) for i in range(8))))

    def rect(self, a):
        return tuple(self.e.s32(a + 4 * i) for i in range(4))

    # ---------------------------------------------------------------- the build
    def screen(self, w, h):
        e = self.e
        e.w32(IE.SW, w)
        e.w32(IE.SH, h)
        if self.patched:
            e.w32(IE.GSCALE, 0)
            e.call(ENSURE_SCALE)
        self.bb = []
        self.rec = True
        try:
            e.call(0x459680, ecx=MW, count=2_000_000_000)
        finally:
            self.rec = False
        # image_emu.call returns quietly when its budget runs out: a cut-short build must fail, not measure as a short one
        assert e.reg(IE.UC_X86_REG_EIP) == IE.SENT, f"MainWin_build did not return (eip {e.reg(IE.UC_X86_REG_EIP):#x})"
        self.screen_wh = (w, h)
        return self.g

    @property
    def g(self):
        return self.e.r32(IE.GSCALE) if self.patched else 16

    def red_windows(self):
        """{button index: (x, y, w, h)} of the 6 red-brush FlatButtons' BaseButton_init in the last build."""
        out = {}
        for ecx, a in self.bb:
            k, r = divmod(ecx - RED_LO, BTN_STRIDE)
            if r == 0 and 0 <= k < RED_N:
                out[k] = a[2:6]
        return out

    # ---------------------------------------------------------------- the editor centre panel
    def editor(self):
        e = self.e
        e.w32(MW + 0x1E8FC, 0x3EA)
        e.call(0x45BC50, ecx=MW, count=2_000_000_000)
        p = IE.canvas_of(e, MW)
        pu, ru, info = self.rect(MW + 0xD4C), self.rect(MW + 0xD5C), self.rect(MW + 0xD6C)
        y = (ru[1] + ru[3]) // 2
        bg = p[y, pu[2] + 1] if p[y, pu[2] + 1] == p[y, (pu[2] + ru[0]) // 2] else p[y, ru[0] + 6]
        st = [s for s in runs(p[y], bg) if pu[2] - 8 <= s[0] <= info[0] + 8]
        return {"p": p, "y": y, "bg": int(bg), "strokes": st, "pal_union": pu, "red_union": ru, "info": info,
                "col_l": self.rect(MI_I)[0], "red_seeds": [self.rect(MW + 0xC6C + 16 * k) for k in range(6)],
                "red_windows": self.red_windows()}

    # ---------------------------------------------------------------- the council row
    def _run(self, start, stop, regs, count=80_000_000):
        e = self.e
        if stop not in self.stops:
            e.observe(stop, lambda e: e.uc.emu_stop())
            self.stops.add(stop)
        r = {UC_X86_REG_EBP: self.frame}
        r.update(regs)
        e.call(start, regs=r, count=count)

    def council(self):
        e, S = self.e, self.sym
        g = self.g
        if self.patched:
            e.w32(S["g_cw_vpdone"], 1)
            e.call(S["thunk_cw_immfix"], count=5_000_000)
            e.uc.ctl_flush_tb()
        cw = CWIN
        con = self.rect(0x7AF5C0)
        self._run(0x427661, 0x427789, {UC_X86_REG_EAX: cw + 0xBB4, UC_X86_REG_EBX: cw + 0xD04,
                                       UC_X86_REG_EDI: cw + 0xCD4, UC_X86_REG_ESI: cw})
        vote = self.rect(cw + 0xD04)
        thirds = [self.rect(cw + 0xCD4 + 0x10 * k) for k in range(3)]
        # the three BaseButton_init argument builds (BaseButton_init stubbed for these only, then restored)
        saved = bytes(e.uc.mem_read(BB_INIT, 5))
        got = {}

        def bbstub(e):
            esp = e.reg(IE.UC_X86_REG_ESP)
            got.setdefault("args", []).append(tuple(e.s32(esp + 4 + 4 * i) for i in range(8)))
            return 0
        e.stub_fn(BB_INIT, bbstub, 0x20)
        e.uc.ctl_flush_tb()                             # MainWin_build ran BaseButton_init: drop its cached block
        try:
            for k, a, b in THIRD_SLICES:
                self._run(a, b, {UC_X86_REG_ESI: cw, UC_X86_REG_EDI: cw + 0xCD4})
        finally:
            e.uc.mem_write(BB_INIT, saved)
            e.uc.ctl_flush_tb()
        wins = [(x, y, x + w, y + h) for (_lbl, _id, x, y, w, h, _par, _z) in got["args"]]
        # the d5a0 box / d618 header / d528 body on the canvas, the d5a0 alone first (its strokes)
        p0 = IE.canvas_of(e, MW)
        bits, wd, ht = e.r32(MW + 0x498), e.s32(CANVAS + 0x38), abs(e.s32(CANVAS + 0x3C))
        e.uc.mem_write(bits, bytes(((wd + 3) & ~3) * ht))
        self._run(0x426AD7, 0x426B19, {UC_X86_REG_ESI: cw})
        box = IE.canvas_of(e, MW)
        self._run(0x426491, 0x4264E2, {UC_X86_REG_EBX: cw})
        self._run(0x426594, 0x4265B0, {UC_X86_REG_EBX: cw})
        comp = IE.canvas_of(e, MW)
        del p0
        return {"g": g, "con": con, "vote": vote, "thirds": thirds, "windows": wins, "box": box, "p": comp}


def box_strokes(box, vote):
    """The d5a0 box's left / right stroke runs on the VOTE row's mid line: (left run, right run)."""
    y = (vote[1] + vote[3]) // 2
    st = runs(box[y], 0)
    left = [s for s in st if s[1] < vote[0]][-1]
    right = [s for s in st if s[0] >= vote[2]][0]
    return left, right
