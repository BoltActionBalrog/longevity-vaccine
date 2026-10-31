"""Real-image type-2 #listbox popup builder for the fix-29 guard (tests/test_scaling_popup_listbox_once.py).

Boots the REAL terranx_PRACX image (a bake of patches.yaml, or an in-memory variant of it) under Unicorn with the
shared harness image_emu.py (every engine function and cave thunk runs for real; OS imports and the CRT allocators
are served by Python) and builds one type-2 list popup with its caller's own sequence, re-derived from the bytes:

  GOTO        Console_go_to 0x4D61A0: Popup_ctor 0x4048A0 -> Popup_start 0x406380(xscript, "GOTO", -1, 0, 0x42, 0)
              -> 3 x BasePop add button 0x6019F0 (Sort: Name / Size / Dist) -> BasePop_set_loc 0x601B80(-10, -10)
              -> Dialogs_item 0x612A70 per base -> ListBox get-selection 0x609A50 -> BasePop_exec_3 0x602600(0, 0).
              A Sort button jumps back to Popup_start on the SAME popup object (a second show).
  EDITORUNIT  0x4DED4C..: PopupDialogState 6, Popup_start(.., -1, 0, 0x40, 0), N rows, exec_3(0, 0), state 0.

In-game state: MainWin visible, the console strip at its patched height fl(213 g/16), the real interface art
(load_interface 0x455610).  Inside exec_3 the engine runs, in its own order: Popup_calculate_dimensions
(vtbl+0x168 @0x60279B; its BasePop_calc call @0x404E93 is the fix-29 site) -> BasePop_calc's ListBox calc (pass 1,
dims dispatch @0x603B42: box reserve [popup+0x30C4], button row y) -> DRAW #1 @0x602B88 -> Dialog_set_type
@0x602BFE -> ListBox_attach -> ListBox calc (pass 2 @0x60A6C1) -> GraphicWin_init of the list window (return
0x60A7B1) -> the button row (BaseButton init 0x607210) -> the modal loop (exec_3's call @0x603714).

lifecycle=True (the passes that COMPOUND under a calc-entry scale; ported from the fix-29 audit harness): the modal
loop is intercepted and, inside it, the engine's own re-layout entries run in turn -- the popup's full redraw
(vtbl+0x30), ListBox_update_changes 0x60C9B0 (calc @0x60C9F4 + re-attach), a direct re-attach ListBox_attach
0x60A670 with the args Dialog_set_type used -- then the modal returns 0, exec_3 runs to its end (hide,
g_popup_active--) and the caller's Sort branch shows the SAME popup again (Popup_start ... exec_3).

Recorded: every ListBox calc entry on the popup's list (the stride/gap/indent it READS), every list window rect with
the reserve at that moment, the button rects, every read of the three sources between the 0x404E93 call and the
first calc, and the reserve at the first modal stop.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_emu as E  # noqa: E402
from unicorn import UC_HOOK_MEM_READ  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

LB_CALC = 0x60A1E0
LB_ATTACH = 0x60A670
LB_UPDATE = 0x60C9B0
LB_WIN_RET = 0x60A7B1            # GraphicWin_init's return inside ListBox_attach: the list window
GW_INIT = 0x5D4EF0
BTN_INIT = 0x607210
BTN_RETS = (0x602D6B, 0x6030E1, 0x603430)     # exec_3's button-row inits (OK path, custom #buttons, CANCEL)
SITE = 0x404E93                  # Popup_calc's BasePop_calc call (the fix-29 site)
MODAL = 0x603714                 # exec_3's modal loop call
MODAL_RET = 0x60371A
RESERVE = 0x30C4                 # popup [+0x30C4]: the list box reserve BasePop_calc lays the box out with
POPUP_LB = 0x21D0

#: g -> a resolution that runs at it (g = floor(16 min(W/1024, H/768)), scaling_laws.popup_g)
RES = {16: (1024, 768), 17: (1088, 816), 18: (1600, 900), 19: (1216, 912), 20: (1280, 1024), 22: (1920, 1080),
       25: (1600, 1200), 40: (3840, 2160)}

NAMES = [("Sparta Command", 6, 2), ("Hawk of Chiron", 17, 2), ("Fort Liberty", 8, 1), ("Militia Station", 12, 1),
         ("Commander's Keep", 8, 1), ("Survival Base", 11, 1), ("Hommel's Citadel", 14, 1),
         ("Janissary Rock", 17, 1), ("War Outpost", 14, 1), ("Halls of Discipline", 16, 1),
         ("Centurion Cave", 16, 1), ("Fort Legion", 20, 1)]


def _dialog(e, lb):
    return lb + e.r32(e.r32(lb) + 8)


class Run:
    """One popup on one image at RES[g]; `patch(e)` may edit the emulated image first."""

    def __init__(self, exe: str, g: int, label: str = "GOTO", nrows: int = 12, lifecycle: bool = False, patch=None):
        W, H = RES[g]
        e = self.e = E.boot(exe, W, H)
        if patch:
            patch(e)
        E.Files(e)
        e.uc.mem_write(0x9B8AA8, b"xscript\0")
        self.g = e.r32(E.GSCALE)
        self.label, self.nrows, self.lifecycle = label, nrows, lifecycle
        self.goto = label == "GOTO"
        e.w32(0x7AE820 + 0x9C, e.r32(0x7AE820 + 0x9C) | 1)               # MainWin visible
        e.w32(0x7AE820 + 0xC4, 0)
        e.w32(0x7AF59C, (213 * self.g) >> 4 if self.g > 16 else 213)       # g_console_strip_height (patched)
        e.call(0x455610, count=0)                                         # load_interface
        for a, v in ((0x7CFF30, 26), (0x7CFF5C, 34), (0x7CFF88, 25)):     # MainWin rail sprite heights (MainWin_build
            if e.s32(a) == 0:                                             # is not emulated; only a >12-row bar reads them)
                e.w32(a, v)
        self.pop = pop = e.alloc(0x6000)
        self.phase = "build"
        self.calcs, self.lists, self.btns, self.attach_args, self.shows = [], [], [], [], []
        self.early_reads, self._watch = [], False
        e.call(0x4048A0, ecx=pop)                                         # Popup_ctor
        self.D = _dialog(e, pop + POPUP_LB)
        e.observe(LB_CALC, self._calc)
        e.observe(GW_INIT, self._gw)
        e.observe(BTN_INIT, self._btn)
        e.observe(LB_ATTACH, self._att)
        e.observe(SITE, self._site)
        e.observe(MODAL, self._modal)
        e.uc.hook_add(UC_HOOK_MEM_READ, self._read, begin=self.D + 0x34, end=self.D + 0x4B)
        self.show("show1")
        if lifecycle and self.goto:
            self.show("show2")                                            # the Sort branch: same object again

    # ------------------------------------------------------------------ observers
    def _site(self, e):
        self._watch = True

    def _read(self, uc, access, addr, size, value, ud):
        if self._watch and addr - self.D in (0x48, 0x44, 0x34):
            self.early_reads.append((self.phase, hex(addr - self.D), hex(uc.reg_read(UC_X86_REG_EIP))))

    def _calc(self, e):
        d = _dialog(e, e.reg(UC_X86_REG_ECX))
        if d == self.D:
            self._watch = False
            self.calcs.append((self.phase, e.r32(e.reg(UC_X86_REG_ESP)), e.s32(d + 0x48), e.s32(d + 0x44),
                               e.s32(d + 0x34)))

    def _gw(self, e):
        esp = e.reg(UC_X86_REG_ESP)
        a = [e.s32(esp + 4 + 4 * i) for i in range(4)]
        if e.reg(UC_X86_REG_ECX) == self.pop:
            self.popwin = tuple(a)
        if e.r32(esp) == LB_WIN_RET:
            self.lists.append(dict(phase=self.phase, win=e.reg(UC_X86_REG_ECX), x=a[0], y=a[1], w=a[2], h=a[3],
                                   reserve=e.s32(self.pop + RESERVE)))

    def _btn(self, e):
        esp = e.reg(UC_X86_REG_ESP)
        if e.r32(esp) in BTN_RETS:
            a = [e.s32(esp + 4 + 4 * i) for i in range(6)]
            self.btns.append(dict(phase=self.phase, x=a[2], y=a[3], w=a[4], h=a[5]))

    def _att(self, e):
        esp = e.reg(UC_X86_REG_ESP)
        self.attach_args.append((self.phase, e.reg(UC_X86_REG_ECX), [e.r32(esp + 4 + 4 * i) for i in range(4)]))

    def _modal(self, e):
        uc = e.uc
        self.saved = {r: uc.reg_read(r) for r in (UC_X86_REG_ESP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                                                  UC_X86_REG_EBP)}
        if not self.shows:
            self.reserve = e.s32(self.pop + RESERVE)
        if self.lifecycle:
            uc.reg_write(UC_X86_REG_EIP, E.SENT)                          # leave exec_3 parked at its modal call
        else:
            uc.emu_stop()

    # ------------------------------------------------------------------ the caller's sequence
    def show(self, tag):
        e, pop = self.e, self.pop
        self.phase = tag
        if not self.goto:
            e.w32(E.PDS, 6)
        e.call(0x406380, ecx=pop, args=(0x9B8AA8, e.cstr(self.label), 0xFFFFFFFF, 0, 0x42 if self.goto else 0x40, 0),
               count=50_000_000)
        if self.goto:
            for s in ("Sort: Name", "Sort: Size", "Sort: Dist"):
                e.call(0x6019F0, ecx=pop, args=(e.cstr(s),))
            e.call(0x601B80, ecx=pop, args=(0xFFFFFFF6, 0xFFFFFFF6))
        for i in range(self.nrows):
            n, d, s = NAMES[i % len(NAMES)]
            e.call(0x612A70, ecx=pop + POPUP_LB, args=(e.cstr(f"{n}|Distance: {d}, Size: {s}"), i))
        if self.goto:
            e.w32(pop + 0x220C, 0)            # the selection callback 0x4D6070 recentres the map -- not emulated
            e.call(0x609A50, ecx=self.D)
        self.saved = None
        e.call(0x602600, ecx=pop, args=(0, 0), count=600_000_000)
        assert self.saved, "the modal loop was not reached"
        if self.lifecycle:
            self.phase = tag + ":modal"
            e._esp_base = self.saved[UC_X86_REG_ESP] - 0x8000
            e.call(e.r32(e.r32(pop) + 0x30), ecx=pop, count=300_000_000)                 # full popup redraw
            e.call(LB_UPDATE, ecx=pop + POPUP_LB, count=300_000_000)                     # ListBox_update_changes
            first = next(a for a in self.attach_args if a[0] == tag)
            e.call(LB_ATTACH, ecx=first[1], args=tuple(first[2]), count=300_000_000)     # re-attach, same args
            del e._esp_base
            self.phase = tag + ":close"                                                  # modal returns 0
            uc = e.uc
            for r, v in self.saved.items():
                uc.reg_write(r, v)
            uc.reg_write(UC_X86_REG_ESP, self.saved[UC_X86_REG_ESP] + 12)
            uc.reg_write(UC_X86_REG_EAX, 0)
            uc.emu_start(MODAL_RET, E.SENT, count=300_000_000)
        if not self.goto:
            e.w32(E.PDS, 0)
        self.shows.append(tag)
        self.final_src = (e.s32(self.D + 0x48), e.s32(self.D + 0x44), e.s32(self.D + 0x34))
