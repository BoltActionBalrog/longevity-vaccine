"""Real-image Design Workshop part-picker rail scrollbar harness (W9C F53, 2026-10-27; tests/test_scaling_dw_rail_grip.py).

The DW part picker (PartPicker, a STACK object in the game, vtbl 0x66B2B8, its ScrollBar at +0xA14) runs the popup
family's rail recipe: thunk_dw_pk_enter (the detour at PartPicker_exec 0x433F70) points thunk_rail_gate4's ProdPicker
comparand at the live picker, so rail_slide_in -> thunk_rail_bake / thunk_rail_sbfit lay its rail column and fit its
bar exactly as for the ProdPicker.  This harness builds it on the REAL terranx_PRACX image (image_emu.py; every engine
function and cave thunk runs for real) in the engine's own order:

  * the console rail sprites and the scrollbar art (rail_sym_emu.load_rail_art: the game's own files, the engine's
    own loaders);
  * DesignWin_exec 0x43E9A0 (its thunk_dw_enter bracket: the imm table, g_dw_active) up to the return of
    DesignWin_build @0x43E9E4 -- the DW window sized and placed by the bake's laws (the picker's GraphicWin_init takes
    the DW canvas dims [0x71F774] / [0x71F778] and the DW as parent); the rest of the exec (the unit model, the modal
    loop) is not run;
  * PartPicker_ctor 0x4328B0 on a heap block, then PartPicker_exec(0, 0, 1, type 1 (weapons), 0, ...) through its
    detour, stopped at the modal loop call @0x4343F4: GraphicWin_init, the container frame, ScrollBar_init_inner,
    the cells, slide_show, rail_slide_in -> the bar fit, the strip bake, ScrollBar_draw (arrows through
    thunk_btn_shrink / thunk_btn_2dscale -> t_btn_edgeprobe -> t_rsb_zoom, the grip through thunk_sb_thumb ->
    t_rsb_grip).
Two inputs the emulator does not have are supplied: the part COUNT (the rules tables are not loaded: [+0x2B74] is set
to `count` right after the engine's own count loop, @0x43420B -- more than the 20 visible cells, so the bar and the
rail exist) and the cell painter PartPicker_draw_cell 0x433D60 (stubbed: it only paints the Caviar part models).
Stubbed as well: the DW's own 25 BaseButton_init calls inside DesignWin_build (restored before the picker, whose bar
arrows init for real) and Win_set_modal 0x5EE190 (the picker's vtbl+0xE4 @0x4343B6 enters the message pump there).
The pristine image has no g: everything is then the vanilla draw.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import image_emu as E  # noqa: E402
import rail_sym_emu as R  # noqa: E402
import scaling_laws as SL  # noqa: E402

DESIGNWIN = 0x71F2B0
DW_EXEC, DW_BUILD_RET = 0x43E9A0, 0x43E9E4
PP_CTOR, PP_EXEC, PP_COUNT_DONE, PP_MODAL = 0x4328B0, 0x433F70, 0x43420B, 0x4343F4
PP_DRAW_CELL = 0x433D60
WIN_SET_MODAL = 0x5EE190
PP_SB = 0xA14
BB_INIT = 0x607210                  # BaseButton_init (thiscall RET 0x20)
PP_VTBL = 0x66B2B8
VPDONE = ("g_vp_done", "g_dw_vpdone")
_SYM = None


def _symtab():
    global _SYM
    if _SYM is None:
        import apply_patches as ap
        _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
        _SYM = ap.build_symbol_table(symbols, caves)
    return _SYM

#: g -> a resolution at that g (scaling_laws.popup_g)
RES = {16: (1024, 768), 17: (1088, 816), 18: (1600, 900), 20: (1280, 1024), 22: (1920, 1080), 25: (1600, 1200),
       30: (2560, 1440), 40: (3840, 2160)}


def _log(*a):
    import os
    if os.environ.get("DWRAIL_VERBOSE"):
        import time
        print(round(time.time(), 1), *a, flush=True)


class Run:
    def __init__(self, exe: str, g: int, count: int = 40, res=None):
        W, H = res or RES[g]
        E.HEAP_SZ = max(E.HEAP_SZ, 0x10000000)
        e = self.e = E.boot(exe, W, H)
        if bytes(e.uc.mem_read(DW_EXEC, 1)) != b"U":                # the bake's thunk_dw_enter detour
            sym = _symtab()
            for k in VPDONE:                                               # VirtualProtect: the image is RWX here
                e.w32(sym[k], 1)
        E.Files(e)
        self.g = e.r32(E.GSCALE)
        e.w32(0x7AE820 + 0x9C, e.r32(0x7AE820 + 0x9C) | 1)               # MainWin visible
        e.w32(0x7AE820 + 0xC4, 0)
        e.w32(0x7AF59C, (213 * self.g) >> 4 if self.g > 16 else 213)       # g_console_strip_height (patched)
        e.call(0x455610, count=0)                                         # load_interface
        e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))                    # the labels (labels.txt), as mirror_pairs_emu
        e.call(0x616A00, count=50_000_000)
        R.load_rail_art(e)
        self.rects = []

        def at_grip(e):
            sp = e.reg(E.UC_X86_REG_ESP)
            self.rects.append((e.reg(E.UC_X86_REG_ESI), tuple(e.s32(sp + 0x24 + 4 * i) for i in range(4))))
        e.observe(R.GRIP_SITE, at_grip)
        bb = bytes(e.uc.mem_read(BB_INIT, 5))
        e.stub_fn(BB_INIT, lambda e: 0, popbytes=0x20)                  # the DW's 25 FlatButtons (not the picker's bar)
        e.observe(DW_BUILD_RET, lambda e: e.uc.emu_stop())
        _log("dw exec")
        e.call(DW_EXEC, ecx=DESIGNWIN, args=(1, 0xFFFFFFFF), count=800_000_000)
        e.uc.mem_write(BB_INIT, bb)                                       # the picker's bar arrows init for real
        _log("dw built", e.s32(DESIGNWIN + 0x4C4), e.s32(DESIGNWIN + 0x4C8))
        assert e.s32(DESIGNWIN + 0x4C4) > 0, "DesignWin_build did not size the window"
        self.pp = pp = e.alloc(0x5000)
        e.call(PP_CTOR, ecx=pp)
        assert e.r32(pp) == PP_VTBL
        e.stub_fn(PP_DRAW_CELL, lambda e: 0, popbytes=8)
        e.stub_fn(WIN_SET_MODAL, lambda e: 0, popbytes=0xC)              # vtbl+0xE4 @0x4343B6: the modal message pump

        def at_count(e):
            e.w32(e.reg(E.UC_X86_REG_EBX) + 0x2B74, count)
        e.observe(PP_COUNT_DONE, at_count)
        self.reached = False

        def at_modal(e):
            self.reached = True
            e.uc.emu_stop()
        e.observe(PP_MODAL, at_modal)
        _log("pp exec")
        e.call(PP_EXEC, ecx=pp, args=(0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0x6FEB7C), count=1_500_000_000)
        assert self.reached, "PartPicker_exec did not reach its modal loop"
        self.sb = pp + PP_SB
        self.thumb_rects = [r for b, r in self.rects if b == self.sb]


def measure(run) -> dict:
    """rail_sym_emu.measure's spans for the picker's bar: the bar window, both arrow plates, the grip columns / rows
    and its thumb rect, the cyan lines on a row below the grip (strip-local x)."""
    e, g, sb = run.e, run.g, run.sb
    comp = R.composite(e, run.pp)
    cw = comp.shape[1]
    x0 = SL.rail_strip_x(cw, g)
    sx, sy, sr, sbt = R.rect(e, sb)
    bar = (sx - x0, sr - x0)
    out = dict(g=g, cw=cw, x0=x0, bar=bar, wc=SL.rail_col_w(cw, g), comp=comp, sbw=e.s32(sb + 0x4C4))
    for nm, off in (("up", R.SB_UP), ("dn", R.SB_DN)):
        a = E.canvas_of(e, sb + off)
        ax = R.rect(e, sb + off)
        sp = R.colspan(a, lambda c: c != R.KEY)
        out[nm] = (sp[0] + ax[0] + bar[0], sp[1] + ax[0] + bar[0]) if sp else None
    b = E.canvas_of(e, sb)
    ua, da = R.rect(e, sb + R.SB_UP), R.rect(e, sb + R.SB_DN)
    mid = b[ua[3]:da[1]]
    import numpy as np
    grip = lambda c: ~np.isin(c, R.TROUGH + (R.KEY,))                    # noqa: E731
    sp = R.colspan(mid, grip)
    out["thumb"] = (sp[0] + bar[0], sp[1] + bar[0]) if sp else None
    rows = [y for y in range(mid.shape[0]) if grip(mid[y]).any()]
    out["thumb_rows"] = (rows[0], rows[-1] + 1) if rows else None
    if run.thumb_rects:
        tl, tt, tr, tb = run.thumb_rects[-1]
        out["thumb_rect"] = (tl + bar[0], tt - ua[3], tr + bar[0], tb - ua[3])
    probe = sy + ua[3] + (rows[-1] + 8 if rows else 8)
    out["lines"] = R.spans(comp[probe, x0:x0 + out["wc"]], lambda v: v == R.CYAN)
    return out


if __name__ == "__main__":
    import time
    exe, g = sys.argv[1], int(sys.argv[2])
    t = time.time()
    r = Run(exe, g)
    m = measure(r)
    print({k: v for k, v in m.items() if k != "comp"}, round(time.time() - t, 1), "s")
