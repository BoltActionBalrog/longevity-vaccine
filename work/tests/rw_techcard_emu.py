"""ReportWin_tech_page's F2 card (the research header: text box, lines 1 / 2, the progress bar's two brackets) on the
REAL image, in the engine's own call order (2026-10-25 F45).

rw_techrows_emu.Rig's F2 path with the card's drawing span 0x498D20..0x499521 RUN instead of skipped: the
once-per-session report walker (t_rw_immsum over g_rw_immtab = t_rw_init_leave at init_report_screen's return, which
carries every F2-branch row), then the engine's own `call` at 0x496EEF (ReportWin paint -> t_rw_techpage -> the page).
The page leaves through its epilogue at the shared row block 0x499521 (F44's ground: rw_techrows_emu).  Recorded at
the F45 sites and at the page's own draw calls: the band / text box rects (Buffer_box_sprite arg), the line-1 /
line-2 / blind text x (Buffer_write_l_3 / Buffer_write_cent_l_5 arg), the two text-piece gaps (eax around the add),
each bracket's clip rect (Buffer_set_clip arg) and box rect, the F45 immediates the card READS, and which F45
instructions executed.  The image_emu boot has no art and no report canvas, so the draws return early: every recorded
value is the page's own arithmetic on the values it read, which is what the rows change.

Research state, pinned so every branch runs: faction 1 researches tech 0 (tech 1 leads from it), cost 100 with 40
accumulated (the bar 40 % full) and an increment of 20 % ([0x749AE0] = 2000, set at its read 0x49926F: the second bar
segment and both brackets get a non-empty clip).  `blind` toggles GameRules 0x200 (blind research) with the
omniscient bit (0x9A64C0 & 0x80) clear.  The label lookup 0x6169A0 is a string fetch (stubbed: one label).
ONE boot per rig (~1.5 s); each card() re-runs at any g in ~10 ms.
"""
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EIP, UC_X86_REG_ESP

import rw_techrows_emu as RT

SL = RT.SL
ROW_BLOCK, EPILOGUE, FRAME = RT.ROW_BLOCK, RT.EPILOGUE, RT.FRAME
TECH = 0x94F358                  # Tech table (0x2C stride): +4 name, +8 short name, +0x24 / +0x28 prerequisites
GAMERULES, OMNI = 0x9A649C, 0x9A64C0
PLAYER, FACTION, FACTION_SZ = 0x8A4160, 0x96C9E0, 0x20CC   # current faction; Faction[] (the page's ebx = f * 0x20CC)
F_RESEARCH = 0x3CC                                          # Faction +0x3CC tech being researched (0x96CDAC - 0x96C9E0)
RATE = 0x749AE0
LABEL_FN, LABEL_TAB = 0x6169A0, 0x9B90F8
F45_INSNS = {   # imm VA -> (instruction VA, imm width)
    0x498DBF: (0x498DBD, 1), 0x498DC5: (0x498DC3, 1), 0x499171: (0x49916F, 1), 0x498FDD: (0x498FDB, 1),
    0x49948A: (0x499488, 1), 0x4992C7: (0x4992C6, 4), 0x499334: (0x499333, 4), 0x49938B: (0x49938A, 4),
    0x4993FB: (0x4993FA, 4),
}
assert set(F45_INSNS) == set(SL.RW_TECH_CARD_IMMS)


def _signed(v):
    return v - ((v >> 31) << 32)


class CardRig(RT.Rig):
    mutant = False               # True: the F45 sites back to their native bytes after the report walk (kill check)

    def __init__(self, exe, sym=None):
        super().__init__(exe, sym)
        e = self.e
        lab = e.cstr("Label")
        e.stub_fn(LABEL_FN, lambda e: lab, popbytes=4)
        e.w32(LABEL_TAB, e.alloc(0x1000))
        for i in range(0x59):
            b = TECH + i * 0x2C
            e.w32(b + 4, e.cstr(f"Technology {i}"))
            e.w32(b + 8, e.cstr(f"T{i}"))
            e.w32(b + 0x24, 0xFFFFFFFF)                    # no prerequisites (tech 1 <- tech 0: card())
            e.w32(b + 0x28, 0xFFFFFFFF)
        e.observe(0x4991CD, self._progress)
        e.observe(0x49926F, lambda e: e.w32(RATE, 2000))
        e.observe(ROW_BLOCK, self._leave)
        rect = lambda e, p: tuple(e.s32(p + 4 * k) for k in range(4))
        arg0 = lambda e: e.r32(e.reg(UC_X86_REG_ESP))
        argx = lambda e: e.s32(e.reg(UC_X86_REG_ESP) + 4)
        eax = lambda e: _signed(e.reg(UC_X86_REG_EAX))
        obs = {
            0x498D9B: ("band", lambda e: rect(e, arg0(e))),            # Buffer_box_sprite(band rect)
            0x498E6C: ("textbox", lambda e: rect(e, arg0(e))),         # non-blind text box
            0x498DCD: ("blind_box", lambda e: rect(e, arg0(e))),       # blind-research text box
            0x498EF1: ("line1_x", argx),                               # Buffer_write_l_3(str, x, y, len)
            0x499111: ("blind_x", argx),                               # Buffer_write_cent_l_5(str, x, y, w, len)
            0x49947D: ("line2_x", argx),
            0x498FDB: ("name_end", eax), 0x498FDE: ("name_next", eax),
            0x499488: ("rate_end", eax), 0x49948B: ("rate_next", eax),
            0x4991C8: ("bar", lambda e: rect(e, arg0(e))),
            0x4992BB: ("clip1", lambda e: rect(e, arg0(e))),           # Buffer_set_clip(the increment)
            0x499328: ("bracket1", lambda e: rect(e, arg0(e))),
            0x49937F: ("clip2", lambda e: rect(e, arg0(e))),           # the increment inset 1 (inc / dec)
            0x4993EC: ("bracket2", lambda e: rect(e, arg0(e))),
            0x499421: ("after2", lambda e: rect(e, e.reg(UC_X86_REG_EBP) - 0x28)),
        }
        for va, (k, fn) in obs.items():
            e.observe(va, (lambda k, fn: lambda e: self.rec.setdefault(k, fn(e)))(k, fn))
        e.observe(0x498D9B, lambda e: self.rec.setdefault("imms", self.f45_imms()))     # what the card READS
        for imm, (ins, _w) in F45_INSNS.items():
            e.observe(ins, (lambda imm: lambda e: self.rec.setdefault("f45_exec", []).append(imm))(imm))

    def _skip_card(self, e):     # the card runs (F44's rig skips it)
        pass

    def _progress(self, e):
        b = e.reg(UC_X86_REG_EBP)
        e.w32(b - 4, 100)
        e.w32(b - 0x10, 40)

    def _leave(self, e):
        b = e.reg(UC_X86_REG_EBP)
        self.rec["left"] = True
        e.uc.reg_write(UC_X86_REG_ESP, b - FRAME)
        e.uc.reg_write(UC_X86_REG_EIP, EPILOGUE)

    def _walk(self, table, g, immsum=False):
        super()._walk(table, g, immsum)
        if self.mutant and table == "g_rw_immtab":
            for va, v in SL.RW_TECH_CARD_IMMS.items():
                w = F45_INSNS[va][1]
                self.e.uc.mem_write(va, v.to_bytes(w, "little"))
            self.e.uc.ctl_flush_tb()

    def f45_imms(self):
        e = self.e
        return {va: (e.s32(va) if w == 4 else e.uc.mem_read(va, 1)[0]) for va, (_i, w) in F45_INSNS.items()}

    def card(self, g, blind):
        """The F2 card at g in the engine's order; returns the record."""
        e = self.e
        gr = e.r32(GAMERULES)
        e.w32(GAMERULES, (gr | 0x200) if blind else (gr & ~0x200))
        e.uc.mem_write(OMNI, bytes([e.uc.mem_read(OMNI, 1)[0] & 0x7F]))
        e.w32(TECH + 1 * 0x2C + 0x24, 0)
        e.w32(PLAYER, 1)
        e.w32(FACTION + FACTION_SZ + F_RESEARCH, 0)       # faction 1 researches tech 0
        return self.f2(g)
