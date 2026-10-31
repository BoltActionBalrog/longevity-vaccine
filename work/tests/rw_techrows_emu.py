"""ReportWin_tech_page's leads-to row slots on the REAL image (image_emu.py), in the engine's own call order
(2026-10-25 F44).

  f2(g)  the F2 report path: the once-per-session report walker (t_rw_immsum over g_rw_immtab, what
         t_rw_init_leave runs at init_report_screen's return), then the engine's own `call` at 0x496EEF
         (ReportWin paint -> t_rw_techpage: tech table at g -> ReportWin_tech_page -> table back at 16).
  dl(g)  the Datalinks path: g_dl_immtab_tech at g (DatalinkWin_open's entry walk), then the engine's own `call`
         at 0x42C1F2 (DatalinkWin_dispatch -> t_dl_techwrap: textB / lineH once, iface mode 8 -> tech_page).

Inside ReportWin_tech_page everything runs for real except the F2 card's DRAWING span 0x498D20..0x499521
(text / icon / bar draws on the canvas; it writes none of the row block's inputs -- [ebp-0x5C] / [ebp-0x54] /
[ebp-0x50], RW+0x59A0 / 0x59A4 / 0xA28 / 0xE268 / 0x5980 are all set before 0x498D20 or by init) and the page's tail
past the slot stores (0x499693.., the buttons); the page leaves through its own epilogue 0x49B1D5.  Recorded:
the six row-gap immediates at the page's ENTRY (what the page reads) and after the caller's revert, and the
seven slots RW+0x5958..0x5970 the row block stores.  The pristine image runs the same calls (no thunks; g = 16).
ONE boot per Rig (~3 s); each call re-runs at any g.
"""
import sys
from pathlib import Path

import image_emu as IE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP  # noqa: E402

s = SL.scale_px
G_VA, G_STRIPE = 0x668740, 0x66879C
RW = 0x876478
TECH_PAGE = 0x498B30
F2_CALL, F2_NEXT = 0x496EEF, 0x496EF4            # ReportWin paint: `call ReportWin_tech_page` (t_rw_techpage when patched)
DL_CALL, DL_NEXT = 0x42C1F2, 0x42C1F7            # DatalinkWin_dispatch: `call ReportWin_tech_page` (t_dl_techwrap)
CARD_DRAW, ROW_BLOCK = 0x498D20, 0x499521        # F2 branch: first draw call / the shared row block
SLOTS_DONE, EPILOGUE = 0x499693, 0x49B1D5        # after the RW+0x5970 store / pop edi; pop esi; pop ebx; leave; ret
FRAME = 0x218 + 12                               # sub esp,0x218 + push ebx/esi/edi
MODEIDX, MODETAB = 0x7D392C, 0x7AE778            # current iface index / g_iface_mode_table
DL_RECT = 0x714244                               # DatalinkWin text panel clip (L, T, R, B) the DL branch reads
GAP_IMMS = {                                      # the row block's gap immediates (pristine value 0x10 each)
    "f2_below": 0x49957F, "f2_above": 0x499582,  # non-DL odd pair (F44)
    "dl_below": 0x4995CC, "dl_above": 0x4995CF,  # DL odd pair
    "even_pitch": 0x49960D, "even_last": 0x49967C,
}
SLOT_OFF = {"y_mid": 0x5958, "above": 0x595C, "below": 0x5960, "e0": 0x5964, "e1": 0x5968, "e2": 0x596C, "e3": 0x5970}
NATIVE_WIN_H, NATIVE_LINE_H = 553, 15            # the F2 window at >= 1024 (353 + 0xC8) / the report line height


def symtab(yaml_path=None):
    _s, _g, caves, symbols = ap.load_patches(Path(yaml_path or ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


class Rig:
    def __init__(self, exe, sym=None):
        e = self.e = IE.boot(exe, 3840, 2160)
        rel = e.s32(F2_CALL + 1)
        self.patched = (F2_CALL + 5 + rel) & 0xFFFFFFFF != TECH_PAGE
        self.sym = (sym if sym is not None else symtab()) if self.patched else {}
        self.rec = {}
        self.path = None
        self.frame = e.alloc(0x400) + 0x200
        e.observe(TECH_PAGE, self._entry)
        e.observe(CARD_DRAW, self._skip_card)
        e.observe(SLOTS_DONE, self._slots)
        e.observe(F2_NEXT, lambda e: e.uc.emu_stop())
        e.observe(DL_NEXT, lambda e: e.uc.emu_stop())
        if self.patched:
            th = self.sym["t_rw_techpage"]
            code = bytes(e.uc.mem_read(th, 0x200))
            k = code.find(bytes.fromhex("B8B4846E00"))       # `mov eax, 0x6E84B4` right after the revert walk
            assert k > 0, "t_rw_techpage: revert-walk marker not found"
            self.f2_after_revert = th + k
            e.observe(self.f2_after_revert, lambda e: e.uc.emu_stop())

    # ---------------------------------------------------------------- observers
    def imms(self):
        return {k: self.e.uc.mem_read(va, 1)[0] for k, va in GAP_IMMS.items()}

    def _entry(self, e):
        self.rec["entry_imms"] = self.imms()
        self.rec["entries"] = self.rec.get("entries", 0) + 1

    def _skip_card(self, e):
        e.uc.reg_write(UC_X86_REG_EIP, ROW_BLOCK)

    def _slots(self, e):
        r = self.rec
        r["slots"] = {k: e.s32(RW + o) for k, o in SLOT_OFF.items()}
        r["btn_h"] = e.s32(RW + 0x59A4)
        r["col_h"] = e.s32(RW + 0xA20)
        ebp = e.reg(UC_X86_REG_EBP)
        r["y0"] = e.s32(ebp - 8)
        r["dl_flag"] = e.s32(ebp - 0x38)
        e.uc.reg_write(UC_X86_REG_ESP, ebp - FRAME)
        e.uc.reg_write(UC_X86_REG_EIP, EPILOGUE)

    # ---------------------------------------------------------------- state
    def _walk(self, table, g, immsum=False):
        e, S = self.e, self.sym
        e.w32(S["g_dl_vpdone"], 1)
        e.w32(S["g_dl_immg"], g)
        e.call(S["t_rw_immsum" if immsum else "t_dl_immfix"], regs={UC_X86_REG_ESI: S[table]}, count=5_000_000)
        e.uc.ctl_flush_tb()

    def reset(self, g):
        """Every runtime table back at 16 (the native bytes), then g in the cells -- g never changes mid-session in
        the game, so each sweep point starts from the pristine bytes."""
        e = self.e
        if self.patched:
            for t in ("g_dl_immtab_main", "g_dl_immtab_tech", "g_rw_immtab_tech"):
                self._walk(t, 16)
            self._walk("g_rw_immtab", 16, immsum=True)
            e.w32(self.sym["g_dl_immg"], 0)
            e.w32(self.sym["g_dl_exec"], 0)
            e.w32(G_VA, g)
            e.w32(G_STRIPE, SL.stripe_period(g))
        self.rec = {}

    def seed(self, g, mode):
        """The RW fields the page reads at entry, as the report init lever leaves them (device = vanilla x g/16)."""
        e = self.e
        e.w32(MODEIDX, 3)
        e.w32(MODETAB + 4 * 3, mode)
        win_h = s(NATIVE_WIN_H, g)
        e.w32(RW + 0xA14, s(87, g))
        e.w32(RW + 0xA18, s(47, g))
        e.w32(RW + 0xA1C, s(844, g))
        e.w32(RW + 0xA20, win_h)
        e.w32(RW + 0x5990, win_h)
        e.w32(RW + 0x5980, win_h - s(0x35, g))
        e.w32(RW + 0xE268, SL.rw_line_h(0, g) if g > 16 else NATIVE_LINE_H)
        for i, v in enumerate((s(250, g), s(60, g), s(800, g), s(500, g))):
            e.w32(DL_RECT + 4 * i, v)
        for k in SLOT_OFF.values():
            e.w32(RW + k, 0x7EADBEEF)

    # ---------------------------------------------------------------- the two paths
    def f2(self, g):
        """F2 report path in the engine's order; returns the record."""
        e = self.e
        self.reset(g)
        if self.patched and g > 16:
            e.w32(self.sym["g_dl_immg"], 0)
            self._walk("g_rw_immtab", g, immsum=True)            # t_rw_init_leave at init_report_screen's return
            e.w32(self.sym["g_dl_immg"], 0)                     # (it restores the prior immg)
        self.seed(g, 5)                                          # ReportIf = SubInterface mode 5
        e.call(F2_CALL, regs={UC_X86_REG_EBX: RW, UC_X86_REG_EBP: self.frame}, ecx=RW, count=50_000_000)
        self.rec["after_imms"] = self.imms()
        return self.rec

    def dl(self, g):
        """Datalinks tech page in the engine's order; returns the record."""
        e = self.e
        self.reset(g)
        if self.patched and g > 16:
            e.w32(self.sym["g_dl_immg"], 0)
            self._walk("g_rw_immtab", g, immsum=True)            # the report init ran at game load
            self._walk("g_dl_immtab_tech", g)                    # DatalinkWin_open entry (t_dl_immfix_tech)
            e.w32(self.sym["g_dl_exec"], 1)
        self.seed(g, 8)                                          # Datalinks = mode 8 (techwrap forces it at g > 16)
        e.call(DL_CALL, regs={UC_X86_REG_EBP: self.frame}, ecx=RW, count=50_000_000)
        self.rec["after_imms"] = self.imms()
        return self.rec
