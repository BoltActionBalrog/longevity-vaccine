"""Real-image checkbox screens for the fix-28 guard (tests/test_scaling_checkbox_stripes.py).

Boots the REAL terranx_PRACX image (a bake of patches.yaml, or the pristine .bak) under Unicorn with the shared
harness image_emu.py and builds a screen that draws the checkbox X sprites, with its caller's own sequence:

  LOBBY    NetWin_setup_lobby 0x482490 (session/network side stubbed, stopped before the modal), the window marked
           shown (NetWin_draw opens with Win_is_visible 0x5F7E90), then NetWin_draw 0x481AD0 (vtbl+0x30): every panel
           (the t_nw_box sites) and the 18 CUSTOM GAME OPTIONS boxes (sites 0x47FAD4 / 0x47FD2B).
  TREATY   the scenario editor's diplomacy modal: Console_editor_diplomacy 0x4DB870 with the EDITORWHO picker's
           BasePop_exec_3 answering faction 1, stopped at DiploEditWin_loop 0x4DA990; its CheckList treaty rows
           (sites 0x60F41C / 0x60F457).
  RULES    the main menu's Customize Game Rules: script popup 0x5BF3F0("RULES", 0x41, 0) (caller 0x58A398), flat.
  GOV      GOVOPTIONS (Governor Settings), the same entry, in an ornate popup (base screen mode).  Both: site 0x405BD4;
           the checkbox-state word 0x9BC06C (the caller's input) is set to alternate rows checked / unchecked.
  PREFS    PrefWin_build 0x48D840 + PrefWin_show 0x48FA00(page): the CheckList rows, sites 0x60F41C / 0x60F457.

Every t_ck_draw call (new image) is recorded at its entry -- sprite, the six args, g_ck_ph, the dest window's +0x140 /
+0x150 -- and the dest canvas around the box is snapshotted right after the call returns (the instruction after each
adapter's CALL), before anything later overdraws it.  At entry the dest Buffer's colour table (+0xA4, which the
emulator never syncs) is set to the in-game colours of these indices: interface.pcx's palette at +10, the colours the
user's shots show for every checkbox texel.  On any image the final canvases are returned too (the g = 16 identity).
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import image_emu as E  # noqa: E402
import ornate_popup_emu as O  # noqa: E402
import assemble_checkbox_stripes as AC  # noqa: E402
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP  # noqa: E402

NW = 0x80A6F8                    # NetWin (the lobby)
PREFWIN = 0x8578D8
CK_DRAW = AC.PCAVE2 + AC.SLOTS["t_ck_draw"]
# the 17 filled lobby panel sites call t_nwf_box since netwin_frame_strokes (2026-11-07; same thiscall contract, the
# engine box at the caller's rect inside it, t_nw_box only as its guard fallback) -- the panel recorder hooks its entry
import assemble_nw_frames as NWF  # noqa: E402
NW_BOX = NWF.PCAVE2 + NWF.SLOTS["t_nwf_box"]
BUFFER_TILE_PHASE = 0x5DA860
SPRITES = (0x7794D8, 0x779504, 0x779530)
RES = {16: (1024, 768), 18: (1600, 900), 19: (1216, 912), 22: (1920, 1080), 25: (1600, 1200), 30: (2560, 1440),
       40: (3840, 2160)}


def palette():
    from PIL import Image
    pcx = Image.open(Path(E.GAME) / "interface.pcx")
    p = np.array(pcx.getpalette()).reshape(-1, 3)
    pal = np.zeros((256, 3), np.uint8)
    pal[10:] = p[:246]
    return pal


def _after_call_vas():
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    built = AC.build()
    out = []
    for name in ("t_ck_list", "t_ck_core"):
        base = AC.PCAVE2 + AC.SLOTS[name]
        for i in md.disasm(built[name], base):
            if i.mnemonic == "call" and int(i.op_str, 16) == CK_DRAW:
                out.append(i.address + i.size)
    assert len(out) == 2
    return out


class Recorder:
    def __init__(self, pal):
        self.palb = bytes(b for i in range(256) for b in (int(pal[i][2]), int(pal[i][1]), int(pal[i][0]), 0))
        self.pending, self.draws = [], []

    def hooks(self):
        return [(CK_DRAW, self._entry)] + [(va, self._after) for va in _after_call_vas()]

    def _entry(self, e):
        esp = e.reg(UC_X86_REG_ESP)
        a = [e.s32(esp + 4 + 4 * i) for i in range(6)]
        dest = a[0] & 0xFFFFFFFF
        e.uc.mem_write(dest + 0xA4, self.palb)
        win = dest - 0x444
        spr = e.reg(UC_X86_REG_ECX)
        f = [e.s32(spr + 4 * i) for i in range(10)]
        art = np.frombuffer(bytes(e.uc.mem_read(f[1] & 0xFFFFFFFF, f[3] * f[5])), np.uint8).reshape(f[5], f[3])[:, :f[4]]
        self.pending.append(dict(spr=spr, dest=dest, key=a[1], x=a[2], y=a[3], num=a[4], den=a[5],
                                 ph=e.r32(AC.PCAVE2 + AC.SLOTS["g_ck_ph"]),
                                 tops=(e.s32(win + 0x140), e.s32(win + 0x150)), art=art.tolist()))

    def _after(self, e):
        d = self.pending.pop()
        c = E.canvas_of(e, d["dest"] - 0x444)
        nh = (len(d["art"]) * d["num"]) // d["den"]           # the art's own dims (18x18 boxes, the 7x13 lobby arrow)
        nw = (len(d["art"][0]) * d["num"]) // d["den"]
        y0, x0 = max(d["y"], 0), max(d["x"] - 6, 0)
        d["snap"] = (y0, x0, c[y0:d["y"] + nh, x0:d["x"] + nw + 6].copy())
        self.draws.append(d)


class PanelRecorder:
    """Every t_nw_box call on the lobby canvas: the rect, the params' edge-sprite dims and fill tile (its texels),
    the rect Buffer_tile_phase actually tiled inside it, and the canvas right after the call returns (the
    instruction after the site's CALL), before text or a checkbox overdraws the panel."""

    def __init__(self, pal, sites):
        self.palb = bytes(b for i in range(256) for b in (int(pal[i][2]), int(pal[i][1]), int(pal[i][0]), 0))
        self.sites, self.cur, self.boxes = sites, None, []

    def hooks(self):
        return [(NW_BOX, self._entry), (BUFFER_TILE_PHASE, self._tile)] + [(va + 5, self._after) for va in self.sites]

    def _entry(self, e):
        esp = e.reg(UC_X86_REG_ESP)
        dest, rp, prm = e.reg(UC_X86_REG_ECX), e.r32(esp + 4), e.r32(esp + 8)
        e.uc.mem_write(dest + 0xA4, self.palb)
        dims = []
        for off, f in ((0x10, 0x1C), (0x14, 0x1C), (0x18, 0x18), (0x1C, 0x18)):      # top, bottom, left, right
            sp = e.r32(prm + off)
            dims.append(e.s32(sp + f) if sp else 0)
        tile = e.r32(prm + 0x20)
        rows = None
        if tile:
            tw, th, st = e.s32(tile + 0x80), abs(e.s32(tile + 0x84)), e.s32(tile + 0x4A8)
            px = bytes(e.uc.mem_read(e.r32(tile + 0x54), st * th))
            rows = [list(px[r * st:r * st + tw]) for r in range(th)]
        self.cur = dict(dest=dest, site=e.r32(esp) - 5, rect=[e.s32(rp + 4 * i) for i in range(4)], dims=dims,
                        tile_rows=rows, tiled=None)

    def _tile(self, e):
        if self.cur is not None and self.cur["tiled"] is None and e.reg(UC_X86_REG_ECX) == self.cur["dest"]:
            a = [e.s32(e.reg(UC_X86_REG_ESP) + 4 + 4 * i) for i in range(7)]
            self.cur["tiled"] = (a[3], a[4], a[3] + a[5], a[4] + a[6])

    def _after(self, e):
        if self.cur is None:
            return
        d, self.cur = self.cur, None
        d["canvas"] = E.canvas_of(e, d["dest"] - 0x444)
        self.boxes.append(d)


def _free(e):
    e.uc = None
    gc.collect()


def lobby(exe, g, rec=None, panels=None, host=False, hooks=()):
    """host: [0x93E8C0] = 1, so NetWin_draw_settings also draws its 8 pull-down arrows (0 skips them)."""
    W, H = RES[g]
    e = E.boot(exe, W, H)
    E.Files(e)
    e.call(0x455610, count=0)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
    e.call(0x616A00, count=50_000_000)
    for va, cb in (rec.hooks() if rec else []) + (panels.hooks() if panels else []) + list(hooks):
        e.observe(va, cb)
    e.observe(0x482C8D, lambda e: e.uc.emu_stop())     # after the buttons + font, before the modal (vtbl+0xE4)
    for va in (0x481FD0, 0x632070, 0x630080):          # network / session side of the builder (not UI)
        e.stub_fn(va, lambda e: 0)
    e.w32(0x9B2068, 0)
    e.w32(0x93E8C0, 1 if host else 0)
    e.w32(NW + 0x772C, 1)
    if (e.r32(0x58DBDB) + 0x58DBDF) & 0xFFFFFFFF != 0x482490:   # the patched bracket call: its netwin flag
        e.w32(0xA10800, 1)
    e.call(0x482490, ecx=NW, count=300_000_000)
    e.w32(NW + 0x9C, e.r32(NW + 0x9C) | 1)             # shown, top level (what the modal's show sets)
    e.w32(NW + 0xC4, 0)
    e.call(0x481AD0, ecx=NW, count=600_000_000)        # NetWin_draw: the panels, the options (checkboxes), ...
    out = dict(g=e.r32(E.GSCALE), canvases={"NW": E.canvas_of(e, NW)})
    _free(e)
    return out


CHECK_MASK = 0x9BC06C           # the script popup's checkbox-state word (the RULES caller stores it @0x58A393)


def popup(exe, g, label, rec=None):
    W, H = RES[g]
    kw = dict(kind="XPOP2", label="RULES", flags=0x41, mainwin=False) if label == "RULES" else O.CASES["GO"]

    def checked(e):                              # alternate rows checked / unchecked: both sprites draw
        e.w32(CHECK_MASK, 0x05555555)
    hh = O.H(exe, W, H, hooks=(rec.hooks() if rec else []) + [(0x5BF3F0, checked)], **kw)
    out = dict(g=hh.g, canvases={f"child{k}": c["canvas"] for k, c in enumerate(hh.children) if c["canvas"] is not None})
    out["canvases"]["popup"] = hh.draw1
    _free(hh.e)
    return out


def prefs(exe, g, page=0, rec=None):
    W, H = RES[g]
    e = E.boot(exe, W, H)
    E.Files(e)
    e.uc.mem_write(0x9B8AA8, b"xscript\0")
    e.call(0x455610, count=0)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
    e.call(0x616A00, count=50_000_000)
    e.w32(0x7AE820 + 0x9C, e.r32(0x7AE820 + 0x9C) | 1)
    for va, cb in (rec.hooks() if rec else ()):
        e.observe(va, cb)
    e.call(0x48D840, ecx=PREFWIN, count=200_000_000)   # PrefWin_build
    e.observe(0x406840, lambda e: e.uc.emu_stop())     # Win_modal_always: the modal loop starts
    try:
        e.call(0x48FA00, ecx=PREFWIN, args=(page,), count=2_000_000_000)
    except RuntimeError as x:
        if "stopped" not in str(x):
            raise
    lists = [PREFWIN + off + 0x1C for off in (0x5974, 0x649C, 0x6FC4, 0x7AEC, 0x8614, 0x913C, 0x9C64)]
    cv = {f"list{k}": E.canvas_of(e, w) for k, w in enumerate(lists)}
    cv["prefwin"] = E.canvas_of(e, PREFWIN)
    out = dict(g=e.r32(E.GSCALE), canvases={k: v for k, v in cv.items() if v is not None})
    _free(e)
    return out


def treaty(exe, g, rec=None):
    """The scenario editor's diplomacy modal (native 758x398, NOT scaled) and its CheckList treaty rows."""
    W, H = RES[g]
    e = E.boot(exe, W, H)
    E.Files(e)
    e.uc.mem_write(0x9B8AA8, b"xscript\0")
    e.call(0x455610, count=0)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
    e.call(0x616A00, count=50_000_000)
    e.w32(0x7AE820 + 0x9C, e.r32(0x7AE820 + 0x9C) | 1)
    for va, cb in (rec.hooks() if rec else ()):
        e.observe(va, cb)
    e.stub_fn(0x602600, lambda e: 1, popbytes=8)        # EDITORWHO's BasePop_exec_3 -> faction 1
    e.observe(0x4DA990, lambda e: e.uc.emu_stop())      # DiploEditWin_loop: the modal loop starts
    e.observe(0x4DADA0, lambda e: e.uc.emu_stop())      # DiploEditWin_update: the rows are drawn (the show after it spins)
    try:
        e.call(0x4DB870, ecx=0x7AE820, count=400_000_000)
    except RuntimeError as x:
        if "stopped" not in str(x):
            raise
    out = dict(g=e.r32(E.GSCALE))
    _free(e)
    return out
