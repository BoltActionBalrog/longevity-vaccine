"""The F2 research card's progress bar PAINTED on the REAL image at a real resolution, with its art (2026-10-25 W6C).

Unlike rw_techcard_emu (no art, no canvas: the draws return early), this rig loads the box-sprite sets
(load_interface 0x455610), runs the real init_report_screen 0x4A3460 (t_rw_init_enter / t_rw_init_leave: the report
walker, the 4 MB snapshot plane) and the real ReportWin paint 0x496D00 -> t_rw_techpage -> ReportWin_tech_page, so the
bar, the progress segment and the two research brackets land on the RW canvas through the shipped thunks
(t_dl_bmxt, t_rw_br1, t_rw_ring, the page's restripe).  The page is left at the shared row block 0x499521 (the card
is all that is drawn).  Lineage: the W4B auditor's px.py (audit-w4B), the W6C probe ring.py.

Research state as rw_techcard_emu: faction 1 researches tech 0, cost 100 (tech_rate 0x5BE6B0 stubbed), 40
accumulated, increment 20 % ([0x749AE0] = 2000 at its read 0x49926F), not blind.

paint() records, per call: the two clips (bracket 1 = the increment, bracket 2 = its inset), every t_dl_bmxt call
(rect, staged bbox, which path it took: the snapshot / thick draw or the native Buffer_box_sprite), and the final
canvas.  One boot per rig (~5..15 s by resolution: the art load and the 4K canvas); paint() re-runs in ~1 s.
"""
import sys
from pathlib import Path

from unicorn import UC_HOOK_MEM_WRITE
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EIP, UC_X86_REG_ESP

import image_emu as IE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # noqa: E402

RW, RIF = 0x876478, 0x885F38
CANVAS = RW + 0x444
TECH = 0x94F358
BOX_SPRITE = 0x5E2DD3
PAINT, INIT_REPORT, LOAD_IFACE = 0x496D00, 0x4A3460, 0x455610
CLIP1_AT, CLIP2_AT = 0x4992BB, 0x49937F           # Buffer_set_clip(the increment) / (its inset)
ROW_BLOCK, EPILOGUE, FRAME = 0x499521, 0x49B1D5, 0x218 + 12
for _n, _k in (("LoadLibraryA", 1), ("GetProcAddress", 2), ("VirtualProtect", 4), ("FreeLibrary", 1),
               ("GetModuleHandleA", 1)):
    IE.NARGS[_n] = _k


def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


class PaintRig:
    def __init__(self, exe, w, h, sym=None):
        e = self.e = IE.boot(exe, w, h)
        self.g = e.r32(0x668740)
        self.sym = sym or {}
        fake = IE.STUB + 0x7F00                         # t_rw_init_enter's VirtualProtect bootstrap
        e.imp[fake] = "VirtualProtect"
        e.api_LoadLibraryA = lambda: 0x7FF00000
        e.api_GetModuleHandleA = lambda: 0x7FF00000
        e.api_GetProcAddress = lambda: fake

        def vp():
            if e.arg(3):
                e.w32(e.arg(3), 0x20)
            return 1
        e.api_VirtualProtect = vp
        e.call(LOAD_IFACE, args=(0,), count=0)           # the box-sprite sets
        e.call(INIT_REPORT, ecx=RIF, count=400_000_000)
        lab = e.cstr("Label")
        e.stub_fn(0x6169A0, lambda e: lab, popbytes=4)
        e.w32(0x9B90F8, e.alloc(0x1000))
        for i in range(0x59):
            b = TECH + i * 0x2C
            e.w32(b + 4, e.cstr(f"Technology {i}"))
            e.w32(b + 8, e.cstr(f"T{i}"))
            e.w32(b + 0x24, 0xFFFFFFFF)
            e.w32(b + 0x28, 0xFFFFFFFF)
        e.w32(TECH + 1 * 0x2C + 0x24, 0)
        e.w32(0x8A4160, 1)
        fb = 0x96C9E0 + 0x20CC
        e.w32(fb + 0x3CC, 0)
        e.w32(fb + 0x3C8, 40)
        e.stub_fn(0x5BE6B0, lambda e: 100)
        e.observe(0x49926F, lambda e: e.w32(0x749AE0, 2000))
        e.w32(0x9A649C, e.r32(0x9A649C) & ~0x200)
        e.uc.mem_write(0x9A64C0, bytes([e.uc.mem_read(0x9A64C0, 1)[0] & 0x7F]))
        self.rec = {}
        e.observe(CLIP1_AT, lambda e: self.rec.setdefault("clip1", self._rect(self._top())))
        e.observe(CLIP2_AT, lambda e: self.rec.setdefault("clip2", self._rect(self._top())))
        e.observe(ROW_BLOCK, self._leave)
        self.bmxt = self.sym.get("t_dl_bmxt")
        if self.bmxt:
            e.observe(self.bmxt, self._bmxt_in)
            e.observe(BOX_SPRITE, self._native)
            e.observe(self.sym["thunk_box_thick_hollow_flat"], self._thick)
        self.guard = self.guard_hook = None
        self.guard_writes = []

    # ------------------------------------------------------------------ observers
    def _top(self):                                     # at a call instruction: its first argument
        return self.e.r32(self.e.reg(UC_X86_REG_ESP))

    def _arg(self, k):                                  # at a function's entry: argument k
        return self.e.r32(self.e.reg(UC_X86_REG_ESP) + 4 + 4 * k)

    def _rect(self, p):
        return tuple(self.e.s32(p + 4 * k) for k in range(4))

    def _bmxt_in(self, e):
        self.rec.setdefault("bmxt", []).append({"rect": self._rect(self._arg(0)), "path": None})

    def _native(self, e):
        calls = self.rec.get("bmxt")
        if calls and calls[-1]["path"] is None:
            calls[-1]["path"] = "native"

    def _thick(self, e):
        calls = self.rec.get("bmxt")
        if calls and calls[-1]["path"] is None:
            calls[-1]["path"] = "snapshot"
            bx = self.sym["g_dl_bx"]
            x0, y0, x1, y1 = (e.s32(bx + 4 * k) for k in range(4))
            calls[-1]["bbox"] = (x0, y0, x1, y1)

    def _leave(self, e):
        b = e.reg(UC_X86_REG_EBP)
        self.rec["left"] = True
        e.uc.reg_write(UC_X86_REG_ESP, b - FRAME)
        e.uc.reg_write(UC_X86_REG_EIP, EPILOGUE)

    # ------------------------------------------------------------------ the snapshot plane
    def plane(self, size, cap, guard=0x200000):
        """Replace g_dl_snapbuf by a fresh `size`-byte plane with write-watched guard bands on both sides and set
        g_dl_snapcap = cap (the t_dl_snapchk contract).  Returns the plane's address."""
        e = self.e
        base = e.alloc(size + 2 * guard)
        p = base + guard
        e.w32(self.sym["g_dl_snapbuf"], p)
        e.w32(self.sym["g_dl_snapcap"], cap)
        if self.guard_hook is not None:
            e.uc.hook_del(self.guard_hook)

        def hit(uc, acc, addr, sz, val, ud):
            lo, hi = self.guard
            if (addr < lo or addr + sz > hi) and len(self.guard_writes) < 64:
                self.guard_writes.append((addr, sz, uc.reg_read(UC_X86_REG_EIP)))
        self.guard_hook = e.uc.hook_add(UC_HOOK_MEM_WRITE, hit, begin=base, end=base + size + 2 * guard - 1)
        self.guard_writes = []
        self.guard = (p, p + size)
        return p

    # ------------------------------------------------------------------ the paint
    def paint(self):
        e = self.e
        self.rec = {}
        e.w32(0x885F40, 2)                              # report kind 2 = F2 Technology
        e.w32(0x7AE778 + 4 * e.r32(0x7D392C), 5)
        e.w32(RW + 0xFAB8, 0)
        e.call(PAINT, ecx=RW, count=600_000_000)
        self.rec["canvas"] = IE.canvas_of(e, RW)
        return self.rec


def ring_widths(c, clip1, clip2):
    """Per-side ring width measured on the canvas: from each clip-1 edge inward, the run of pixels whose colour is
    NOT the interior's (bracket 2's art) at the middle row / column."""
    l, t, r, b = clip1
    ym, xm = (t + b) // 2, (l + r) // 2
    inner = set(c[clip2[1]:clip2[3], clip2[0]:clip2[2]].ravel().tolist())

    def run(seq):
        n = 0
        for v in seq:
            if v in inner:
                break
            n += 1
        return n
    return {"L": run(c[ym, l:r]), "R": run(c[ym, l:r][::-1]), "T": run(c[t:b, xm]), "B": run(c[t:b, xm][::-1])}
