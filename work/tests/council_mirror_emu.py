"""The Planetary Council tally screen on the real image (image_emu.py), in the engine's call order (2026-10-25 wave-5 W5B):

  council(W, H)  the real MainWin_build at that screen (mirror_pairs_emu.Rig.screen: SW / SH written, g recomputed by
                 the image's own thunk_ensure_scale, the console seeded), then the real CouncilWin_exec 0x427230 through
                 its caller's bracket (thunk_cw_enter: g_cw_immtab, g_council_active) on the real CouncilWin static
                 0x6FEC80: the seed table + the E8 @0x427784 chain (t_cw_rowsym -> thunk_cw_seeds -> t_cw_mirror ->
                 Font_init), GraphicWin_init, then the show (vtbl+4 0x427130 -> the iface switch 0x45D310 -> the council
                 iface show CouncilWin_show_hide 0x426FA0): the repaint 0x426AA0 (the d690 backdrop @0x426B4E, the d5a0 ring @0x426B7B, the
                 seven columns 0x425DB0 with their d528 frames and vote chips, the proposal) and then slide_show 0x45D440
                 through thunk_popup_railshow -- the four settled rail strips through thunk_filedlg_railscale onto the
                 council canvas.  Emulation stops right after the show (0x427D6B), before the modal loop.
                 Two engine paths are taken on purpose: the iface switch's hide of the PREVIOUS iface (the map's; not the
                 council's) is skipped (0x45D350 -> 0x45D358), and slide_show runs its own no-animation path (the
                 "animated slides" pref bit 0x8000000 of [0x9A6490] cleared: `je 0x45D7D3` @0x45D63E) -- the settled
                 strips are drawn by the same four sites either way; the animation frames go to the screen buffer.
Every Buffer_box_sprite site of the council painters (COUNCIL_SITES) and the four settled rail sites record their rect
and the canvas pixels they changed (bbox); the canvas after the show is returned.  The pristine image has no g: every
screen is then the vanilla draw.
"""
import sys
from pathlib import Path

import numpy as np

import image_emu as IE
import mirror_pairs_emu as MPE
from unicorn.x86_const import UC_X86_REG_EIP  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

CW = 0x6FEC80
CANVAS = CW + 0x444
GOV = 0x9A6614                      # the governor's faction (-1 none: the flat "inner" column set)
PREFS, SLIDE_ANIM = 0x9A6490, 0x8000000
#: site -> what it draws (CouncilWin_repaint / CouncilWin_draw_column's Buffer_box_sprite E8s)
COUNCIL_SITES = {0x426B4E: "backdrop", 0x426B7B: "ring", 0x425EE9: "column",
                 0x4261AA: "chip", 0x4261D6: "chip", 0x426203: "chip", 0x426230: "chip", 0x42625C: "chip",
                 0x426286: "chip",
                 0x426BD2: "banner"}
#: slide_show's settled strip draws (Sprite_draw_2 E8s; dest = [esp] at the call): outer L, inner L, inner R, outer R
RAIL_SITES = {0x45D82C: "outer_left", 0x45D851: "inner_left", 0x45D875: "inner_right", 0x45D8A9: "outer_right"}
#: the column painter's two Sprite_draw_2 E8s (2026-10-25 W6B): rect = (x, y, sprite w, sprite h) of the call's args
#: (the engine's origin, before the council thunks behind the E8), bbox = the pixels the call changed
SD2_SITES = {0x425F3C: "portrait", 0x426105: "logo"}
#: the emulation budget, WALL CLOCK (us) -- not an instruction count (2026-10-25 W7B, COST): unicorn's `count` budget
#: instruments EVERY translated instruction, ~10x slower here (the 1080 show: 14.7 s counted, 1.5 s timed, canvas and
#: every draw record identical -- measured); a run that does not reach its sentinel still fails in _call
BUDGET_US = 600_000_000
PORTRAIT_SMALL, PORTRAIT_BIG = (96, 115), (118, 144)    # the council portrait canvases (populate)
#: the faction logo's sprite canvas: the real art's 86 x 72 (2026-10-25 W7B; vanilla's trace: faction 1 inner col0 at
#: g = 16, canvas 86 -> x = 38), filled edge to edge so the draw's changed-pixel bbox is its canvas
LOGO = (86, 72)


class Rig(MPE.Rig):
    def __init__(self, exe, sym):
        super().__init__(exe, sym)
        e = self.e
        self.rec = None
        self.pending = None
        for s in COUNCIL_SITES:
            e.observe(s, self._pre_box)
            e.observe(s + 5, self._post)
        for s in RAIL_SITES:
            e.observe(s, self._pre_rail)
            e.observe(s + 5, self._post)
        for s in SD2_SITES:
            e.observe(s, self._pre_sd2)
            e.observe(s + 5, self._post)
        self.populated = False
        e.observe(0x45D350, lambda e: e.uc.reg_write(UC_X86_REG_EIP, 0x45D358))
        e.observe(0x427D6B, lambda e: e.uc.emu_stop())
        call = e.call

        def timed(va, count=0, timeout=0, **kw):     # every e.call of this rig (MainWin_build's included): BUDGET_US
            return call(va, timeout=timeout or (BUDGET_US if count else 0), **kw)
        e.call = timed

    def canvas(self):
        return IE.canvas_of(self.e, CW)

    def _pre_box(self, e):
        if self.rec is None or e.reg(IE.UC_X86_REG_ECX) != CANVAS:
            return
        esp = e.reg(IE.UC_X86_REG_ESP)
        rp = e.r32(esp)
        self.pending = (e.reg(UC_X86_REG_EIP), tuple(e.s32(rp + 4 * i) for i in range(4)), self.canvas())

    def _pre_sd2(self, e):
        if self.rec is None:
            return
        esp, spr = e.reg(IE.UC_X86_REG_ESP), e.reg(IE.UC_X86_REG_ECX)
        self.pending = (e.reg(UC_X86_REG_EIP),
                        (e.s32(esp + 8), e.s32(esp + 12), e.s32(spr + 0x18), e.s32(spr + 0x1C)), self.canvas())

    def _pre_rail(self, e):
        if self.rec is None or e.r32(e.reg(IE.UC_X86_REG_ESP)) != CANVAS:
            return
        self.pending = (e.reg(UC_X86_REG_EIP), None, self.canvas())

    def _post(self, e):
        if self.rec is None or self.pending is None:
            return
        eip, rect, before = self.pending
        if e.reg(UC_X86_REG_EIP) != eip + 5:
            return
        self.pending = None
        ys, xs = np.nonzero(self.canvas() != before)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None
        kind = COUNCIL_SITES.get(eip) or RAIL_SITES.get(eip) or SD2_SITES[eip]
        self.rec.append({"site": eip, "kind": kind, "rect": rect, "bbox": bbox})

    def populate(self):
        """Synthetic memory-backed sprites for factions 1..7 (after audit-w6B's rig6.populate): the small (96 x 115)
        and big (118 x 144) portraits and the two LOGO-sized logos the column painter draws, so its portrait / logo draws
        put real pixels on the canvas -- the portrait a 1-row scanline field with a distinct 1-px border and a face
        block, never the key 9, so the draw's changed-pixel bbox IS its coverage.  The image's own sprite slots are
        empty (no game data loaded)."""
        e = self.e
        self.populated = True

        def sprite(addr, w, h, kind, f):
            a = np.zeros((h, w), np.uint8)
            if kind == "portrait":
                for y in range(h):
                    a[y, :] = 0x04 if y % 2 == 0 else 0xF0
                a[h // 3:2 * h // 3, w // 4:3 * w // 4] = 0x60 + f
                a[:, 0] = 0x50
                a[:, w - 1] = 0x51
                a[0, :] = 0x52
                a[h - 1, :] = 0x53
            else:
                a[:, :] = 0x70 + f
            bits = e.alloc(w * h)
            e.uc.mem_write(bits, a.tobytes())
            for off, v in ((0, 0), (4, bits), (0xC, w), (0x10, w), (0x14, h), (0x18, w), (0x1C, h), (0x20, 0),
                           (0x24, 0)):
                e.w32(addr + off, v)
            e.uc.mem_write(addr + 8, bytes([9]))
        for f in range(1, 8):
            sprite(0x78EDF0 + f * 0x65C, PORTRAIT_SMALL[0], PORTRAIT_SMALL[1], "portrait", f)
            sprite(0x78EE1C + f * 0x65C, PORTRAIT_BIG[0], PORTRAIT_BIG[1], "portrait", f)
            sprite(0x78ED98 + f * 0x65C, LOGO[0], LOGO[1], "logo", f)
            sprite(0x78EDC4 + f * 0x65C, LOGO[0], LOGO[1], "logo", f)

    def _call(self, va, **kw):
        """e.call that FAILS when the budget ran out (BUDGET_US, wall clock): image_emu.call returns silently on its
        budget, so a truncated repaint would pass as a short one (audit-w6B: 400M instructions truncated a 4K vote
        repaint)."""
        e = self.e
        e.call(va, **kw)
        eip = e.reg(UC_X86_REG_EIP)
        if eip not in (IE.SENT, 0x427D6B):
            raise RuntimeError(f"emulation budget exhausted in {va:#x} at eip {eip:#x}")

    def council(self, w, h, gov=-1, prop=0):
        g = self.screen(w, h)
        e = self.e
        if not self.populated:
            self.populate()
        e.w32(GOV, gov & 0xFFFFFFFF)
        e.w32(PREFS, e.r32(PREFS) & ~SLIDE_ANIM)
        start = self.sym["thunk_cw_enter"] if self.patched else 0x427230
        self.rec = []
        try:
            self._call(start, ecx=CW, args=(prop, 0), count=6_000_000_000)
        finally:
            rec, self.rec = self.rec, None
        seeds = {k: [tuple(e.s32(CW + off + 0x20 * c + 4 * i) for i in range(4)) for c in range(7)]
                 for k, off in (("outer", 0xBF4), ("inner", 0xC04))}
        return {"g": g, "W": e.s32(CW + 0x4C4), "H": -e.s32(CW + 0x4C8), "x": e.s32(CW + 0x13C),
                "y": e.s32(CW + 0x140), "seeds": seeds, "rec": rec, "p": self.canvas()}

    def votes(self, calls=1, banner=False):
        """After council(): the modal loop's own redraw entry points, on the shown window (the rails are already on the
        canvas).  CouncilWin_vote_result 0x424720 (thiscall RET 8: faction, vote) for the first `calls` of VOTE_CELLS --
        each re-tallies and repaints the window -- then every VOTE_CELLS vote written (the five abstain-family chips
        -1..-5 and two faction chips, the d528 variant @0x426286: every chip kind of the column painter) and one full
        CouncilWin_repaint.  That is the state after a vote, the one 3 of the user's 6 council shots show (233254 /
        233654 / 125649: the repaint after the slide).  Returns the draws of both steps and the canvas."""
        e = self.e
        self.rec = []
        try:
            for f, v in VOTE_CELLS[:calls]:
                self._call(0x424720, ecx=CW, args=(f, v & 0xFFFFFFFF), count=6_000_000_000)
            for f, v in VOTE_CELLS:
                e.w32(CW + 0xA54 + 4 * f, v & 0xFFFFFFFF)
            if banner:                                   # the session's outcome: the ELECTED banner (d528 @0x426BD2)
                e.w32(CW + 0xA24, 1)
            self._call(0x426AA0, ecx=CW, count=6_000_000_000)
        finally:
            rec, self.rec = self.rec, None
        return {"rec": rec, "p": self.canvas()}


#: (faction, vote) for votes(): every chip kind of CouncilWin_draw_column's jump table + the d528 faction chip
VOTE_CELLS = tuple(zip(range(1, 8), (-1, -2, -3, -4, -5, 2, 3)))


def runs(line):
    """[(first, last, value)] runs of one canvas row."""
    out = []
    for x, v in enumerate(line):
        v = int(v)
        if out and v == out[-1][2]:
            out[-1][1] = x
        else:
            out.append([x, x, v])
    return [tuple(r) for r in out]
