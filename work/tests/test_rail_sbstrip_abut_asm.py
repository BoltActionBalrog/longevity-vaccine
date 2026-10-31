"""Rail scrollbar strip, measured on the REAL engine: the strip starts AT the outer right slide rail, the bar sits exactly
between the rail column's cyan guide lines, and the slide-out's end state IS the closed state (2026-10-17 fix sbstrip +
fix rail2; laws scaling_laws.rail_strip_x / rail_nn_col / rail_wall_off / rail_layout v3 / rail_out_tail v3).

W3B (2026-10-25, the rail scrollbar rework): the rail column no longer goes through the engine NN -- thunk_rail_bake v5
CALLs t_rsb_blit, which lays the 32 native columns on ONE symmetric map (scaling_laws.rail_col_map = axis_map_chrome(32,
Wc, 4, g, 3, 3): K-wide cyan lines, mirrored outer offsets, Wc = rail_wall_off) and keeps the ENGINE's own rows
(rail_blit_rows); the bar is the channel between the lines (rail_layout v4).  So the open-state column check is now
"native column k fills exactly the dest columns rail_col_map sends it", the lines are K wide at mirrored offsets, and
test_rail_column_rows_are_the_engines runs the REAL Buffer_draw_2 beside t_rsb_blit on row-coded strips and requires
the same source row on every dest row.  Every other property (no sliver, wall = the closed outer rail, no write past
the canvas, the slide-out end state == closed, vanilla at g <= 16 / non-family) is unchanged and still asserted.

rail_slide_in (0x45DEA0) bakes a 47-px strip (32-px rail column + the 15-px r_outer wall) at clientW - 47 -- exactly where
slide_show's OUTER right strip sits -- and seats the list bar between the column's two cyan guide lines (native cols 3 /
28: 3+1 | 24 | 1+3); rail_slide_out (0x45E540) captures [R - 47, R), clears it and re-blits it 32 px left, so the wall
returns onto the outer strip's column.  Scaled, the bake enlarges the strip through the ENGINE's Buffer_draw_2, whose NN
places native column k at rail_nn_col(k, g) (its run table, Sprite_fill_scaling_table 0x5EB20F) -- column 32 lands at
2g + 1 for g = 25..31 / 48, not 2g.  fix sbstrip modelled the wall at 2g and rolled up by 2g: a 1-px dark seam between
the inner and outer right rails after the bar slid away (1600x1200, 1920x1200, 2560x1440, 3440x1440), and a bar 1 px off
the cyan lines at 13 of g = 17..40.

NOTHING HERE IS A MODEL OF THE ENGINE: the pristine PRACX exe (.bak) is mapped under Unicorn and its own Buffer_draw_2
(0x5D84C0) does the strip blit; the REAL bytes (resolved from patches.yaml) of every pcave2 thunk run around it --
thunk_filedlg_railscale + thunk_sprite_scale_nn (slide_show's settled right rail pair = the CLOSED state), thunk_rail_bake
(+ thunk_rail_mark / thunk_rail_wall / thunk_rail_walloff / thunk_rail_nncol / thunk_rail_sx: the OPEN state), thunk_rail_sbfit
(the bar's Win_move / resize = its window = its hit rect), thunk_railout_capw (the capture's left edge) and
thunk_railout_hstep (its final shift); the slide-out tail's clear + keyed re-blit is vanilla's 0x45EA97..0x45EB01 (whole
rows, clipped to [L, R)).  Every art column carries its own palette index, so each pixel is traced to its source column.
For every rail-bar window family -- ProdPicker, in-game FileDlg (LOAD/SAVE), Popup, HQ ReportWin -- plus a non-family
window, at g = 12, 16..48, over the windows' own canvas widths and a dense width sweep:
  * the closed outer rail's first column == the strip x (no sliver) == the law;
  * open: native column k sits at S + rail_nn_col(k) (the engine), the wall is the closed outer rail's own pixels at
    S + rail_wall_off, the strip never writes past the canvas (guard bytes right of the row and below the buffer) and
    the canvas height field is restored; no channel mark (0xFD) survives;
  * the bar window == rail_layout's rect and it touches BOTH cyan lines as drawn (0-px margins, the user's symmetry
    rule), inside the rail column;
  * after the slide-out every strip row == the closed row exactly (FileDlg / Popup / picker); ReportWin's slide-out stays
    vanilla (t_rwk_scrollhide restores [cw - s(47) - 4, cw)) and every baked pixel lies inside that column;
  * g <= 16 and the non-family window run vanilla's arithmetic (clientW - 47 1:1, the bar at clientW - 0x2B, 0x18 wide,
    capture R - 47, no shift change).
The engine path emulated from the .bak is asserted unpatched in the build (no patches.yaml site overlaps an engine
instruction the blit executed).  Skips without unicorn / pefile / the .bak.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402

PCAVE2, CAVE_LEN = 0x00A0C000, 0x3C000      # >= pcave2 length in patches.yaml (W3B: the t_rsb_* helpers at 0x39000)
G_VA = 0x00668740
STRIPE_PERIOD_VA = 0x0066879C
SPRITE_DRAW_2 = 0x005E4B4A
BUFFER_DRAW_2 = 0x005D84C0
WIN_MOVE = 0x005ED7D0
INTERSECT_IAT = 0x00669338      # the IntersectRect import the engine blit calls through
WALL_W_VA = 0x007D0060          # r_outer canvas w (15): rail_slide_out's capture base
SPR_OUT, SPR_IN = 0x007D0048, 0x007D001C       # r_outer (15 wide), r_inner (8 wide)
PICKER, REPORTWIN = 0x006A8044, 0x00876478
FILEDLG_VTBL, POPUP_SHOW = 0x00669EC8, 0x00404920
G_FLAG = PCAVE2 + 0x23A0        # g_filedlg_active (railscale arm A)
G_WINBUF = PCAVE2 + 0x25E0      # g_fd_winbuf
MARK_IDX = 0xFD                 # thunk_rail_mark's channel mark

STACK, HEAP, MARKER, STUB = 0x30000000, 0x40000000, 0x30000000, 0x30010000
KEY, GUARD, SPR_KEY = 9, 0xEE, 0xFE
OUTER, INNER, COLART, WALLART = 0x80, 0x90, 0x50, 0xA0   # per-column indices: col k -> base + k
CHAN_COL = 20                    # one rail-column column carries the 0x41 channel dither (restriped, never 0xFD)
HN = 4                           # native strip rows
Y0 = 2                           # the bake's dest y (strip top)
SLACK, GROWS = 24, 4             # guard bytes right of each canvas row / guard rows below the buffer
FAMILIES = ("picker", "report", "filedlg", "popup", "other")
ENTRIES = ("thunk_filedlg_railscale", "thunk_sprite_scale_nn", "thunk_rail_bake", "thunk_rail_sbfit",
           "thunk_railout_capw", "thunk_railout_hstep", "thunk_rail_gate", "thunk_rail_gate4", "thunk_rail_sx",
           "thunk_rail_nncol", "thunk_rail_walloff", "thunk_rail_mark", "thunk_rail_wall", "t_rsb_blit", "t_rsb_cmap",
           "t_rsb_bar")


def _w32(mu, a, v):
    mu.mem_write(a, int(v & 0xFFFFFFFF).to_bytes(4, "little"))


def _s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def load_build(exe):
    """(the BUILT exe's mapped image incl. .pcave2, {thunk id: VA}) -- the engine as the player runs it (Buffer_draw_2,
    Sprite_draw_2 and the blit core carry their own redirects in the build: mon_scale / hudmenu / commlink)."""
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = ap.build_symbol_table(symbols, caves)
    assert symtab["g_popup_scale_num"] == G_VA
    cave = next(c for c in caves if c["id"] == "pcave2")
    entries = {e["id"]: PCAVE2 + int(e["offset"]) for e in cave["contents"] if e["id"] in ENTRIES}
    assert set(entries) == set(ENTRIES)
    pe = pefile.PE(str(exe), fast_load=True)
    assert pe.OPTIONAL_HEADER.ImageBase == 0x400000
    img = bytes(pe.get_memory_mapped_image())
    assert len(img) >= PCAVE2 + CAVE_LEN - 0x400000, "the build has no .pcave2"
    return img, entries


@pytest.fixture(scope="module")
def build(baked_exe):
    return load_build(baked_exe)


class Rig:
    """One emulator: the .bak image at 0x400000, pcave2 from patches.yaml, a heap and a stack."""

    def __init__(self, build, g):
        img, self.va = build
        self.g = g
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        size = (len(img) + 0xFFF) & ~0xFFF
        mu.mem_map(0x400000, size)
        mu.mem_write(0x400000, img)
        mu.mem_map(STACK, 0x100000)
        mu.mem_map(HEAP, 0x400000)
        mu.mem_write(MARKER, b"\xF4")
        self.bump = HEAP + 0x1000
        _w32(mu, G_VA, g)
        _w32(mu, STRIPE_PERIOD_VA, SL.stripe_period(g) if g > 16 else 2)
        _w32(mu, WALL_W_VA, 15)
        # IntersectRect (the engine blit's clip): a hooked stub, RET 0xC
        mu.mem_write(STUB, bytes((0xC2, 0x0C, 0x00)))
        _w32(mu, INTERSECT_IAT, STUB)

        def intersect(m, a, s, u):
            sp = m.reg_read(UC_X86_REG_ESP)
            d, p1, p2 = (int.from_bytes(m.mem_read(sp + 4 + 4 * i, 4), "little") for i in range(3))
            r1 = [_s32(int.from_bytes(m.mem_read(p1 + 4 * i, 4), "little")) for i in range(4)]
            r2 = [_s32(int.from_bytes(m.mem_read(p2 + 4 * i, 4), "little")) for i in range(4)]
            r = (max(r1[0], r2[0]), max(r1[1], r2[1]), min(r1[2], r2[2]), min(r1[3], r2[3]))
            ok = r[0] < r[2] and r[1] < r[3]
            for i, v in enumerate(r if ok else (0, 0, 0, 0)):
                _w32(m, d + 4 * i, v)
            m.reg_write(UC_X86_REG_EAX, int(ok))
        mu.hook_add(UC_HOOK_CODE, intersect, begin=STUB, end=STUB)
        # Win_move / the sb resize slot: recorded stubs.  Sprite_draw_2 is recorded + skipped ONLY when railscale's
        # native tail lands on it (g <= 16; its return is the test's marker) -- every other call runs for real.
        self.rec = {}
        mu.mem_write(WIN_MOVE, bytes((0xC2, 0x08, 0x00)))
        self.resize = STUB + 0x10
        mu.mem_write(self.resize, bytes((0xC2, 0x0C, 0x00)))

        def record(m, a, s, u):
            sp = m.reg_read(UC_X86_REG_ESP)
            self.rec[a] = [_s32(int.from_bytes(m.mem_read(sp + 4 * i, 4), "little")) for i in range(1, 7)]
        for a in (WIN_MOVE, self.resize):
            mu.hook_add(UC_HOOK_CODE, record, begin=a, end=a)

        def sd2(m, a, s, u):
            sp = m.reg_read(UC_X86_REG_ESP)
            ret = int.from_bytes(m.mem_read(sp, 4), "little")
            if ret == MARKER:                          # railscale's native tail (push Sprite_draw_2 / ret)
                self.rec.setdefault(SPRITE_DRAW_2, []).append(
                    [_s32(int.from_bytes(m.mem_read(sp + 4 * i, 4), "little")) for i in range(1, 7)])
                m.reg_write(UC_X86_REG_ESP, sp + 4 + 0x18)
                m.reg_write(UC_X86_REG_EIP, ret)
        mu.hook_add(UC_HOOK_CODE, sd2, begin=SPRITE_DRAW_2, end=SPRITE_DRAW_2)
        # the scrollbar object (vtbl +0xC = resize)
        self.sb = self.alloc(0x100)
        sbvt = self.alloc(0x100)
        _w32(mu, self.sb, sbvt)
        _w32(mu, sbvt + 0xC, self.resize)
        # window objects
        self.win = {"picker": PICKER, "report": REPORTWIN}
        for fam, vt4 in (("popup", POPUP_SHOW), ("other", 0x005EABCD)):
            w, vt = self.alloc(0x600), self.alloc(0x100)
            _w32(mu, w, vt)
            _w32(mu, vt + 4, vt4)
            self.win[fam] = w
        self.win["filedlg"] = self.alloc(0x600)
        _w32(mu, self.win["filedlg"], FILEDLG_VTBL)
        rwvt = self.alloc(0x100)                       # the ReportWin static is identity-keyed; its vtbl is no family's
        _w32(mu, REPORTWIN, rwvt)
        _w32(mu, rwvt + 4, 0x004A0000)
        # the right rail sprites: one palette index per column, rows uniform (529 rows like the art)
        for spr, w, base in ((SPR_OUT, 15, OUTER), (SPR_IN, 8, INNER)):
            pix = self.alloc(w * 529)
            # r_outer's last column is the sprite key (the real art is transparent at its caps): whatever lies under
            # a transparent wall pixel must be what lay under the closed rail's -- never the engine-blitted wall
            mu.mem_write(pix, bytes((base + k) if (spr, k) != (SPR_OUT, 14) else SPR_KEY for k in range(w)) * 529)
            for off, v in ((0x04, pix), (0x08, SPR_KEY), (0x0C, w), (0x10, w), (0x14, 529), (0x18, w), (0x1C, 529),
                           (0x20, 0), (0x24, 0)):
                _w32(mu, spr + off, v)
        self.exec_engine = set()
        self.mark = self.bump                          # per-scenario allocations restart here

    def alloc(self, n):
        a = self.bump
        self.bump += (n + 0xFFF) & ~0xFFF
        return a

    def buffer(self, at, w, h, stride, fill, data=None):
        """Initialise a Buffer struct at `at` (w x h, h stored negative) over `data` (allocated if None)."""
        mu = self.mu
        if data is None:
            data = self.alloc(stride * (h + GROWS) + 64)
        mu.mem_write(at, bytes(0x4B0))
        mu.mem_write(data, bytes([GUARD]) * (stride * (h + GROWS)))
        for y in range(h):
            mu.mem_write(data + y * stride, bytes([fill]) * w if isinstance(fill, int) else fill[y])
        for off, v in ((0x54, data), (0x80, w), (0x84, -h), (0x4A8, stride), (0x20, 0), (0x24, 0), (0x28, w),
                       (0x2C, h), (0x30, 0), (0x34, 0), (0x38, w), (0x3C, h)):
            _w32(mu, at + off, v)
        return data

    def run(self, entry, stack, regs, trace_engine=False):
        mu = self.mu
        sp = STACK + 0x80000
        for i, v in enumerate(stack):
            _w32(mu, sp + 4 * i, v)
        mu.reg_write(UC_X86_REG_ESP, sp)
        for r, v in regs.items():
            mu.reg_write(r, v & 0xFFFFFFFF)
        h = None
        if trace_engine:
            def tr(m, a, s, u):
                self.exec_engine.add((a, s))
            h = mu.hook_add(UC_HOOK_CODE, tr, begin=0x401000, end=0x667FFF)
        mu.emu_start(entry, MARKER, count=50_000_000)
        if h is not None:
            mu.hook_del(h)
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER
        return sp

    def rows(self, data, w, h, stride):
        raw = bytes(self.mu.mem_read(data, stride * (h + GROWS)))
        return [raw[y * stride: y * stride + w] for y in range(h)], raw

    # ---- the scenario ----------------------------------------------------------------------------------------
    def scenario(self, fam, cw, trace_engine=False):
        mu, g = self.mu, self.g
        self.bump = self.mark
        win = self.win[fam]
        buf = win + 0x444
        hdev = (HN * g) >> 4 if g > 16 else HN
        H = Y0 + hdev + 2
        stride = cw + SLACK
        cdata = self.buffer(buf, cw, H, stride, KEY)
        # CLOSED: slide_show's settled right pair (inner x = cw - 0x37, outer x = cw - 0x2F, y 0) through railscale
        _w32(mu, G_FLAG, 1)
        _w32(mu, G_WINBUF, buf)
        self.rec.pop(SPRITE_DRAW_2, None)
        for spr, x in ((SPR_IN, cw - 0x37), (SPR_OUT, cw - 0x2F)):
            self.run(self.va["thunk_filedlg_railscale"], [MARKER, buf, SPR_KEY, x, 0, 1, 1], {UC_X86_REG_ECX: spr})
        _w32(mu, G_FLAG, 0)
        native_rails = self.rec.pop(SPRITE_DRAW_2, None)
        closed, _ = self.rows(cdata, cw, H, stride)
        # the native strip (bufA): rail column cols 0..31 one index each (CHAN_COL = 0x41 on every row), wall cols
        # 32..46 = what vanilla drew there (r_outer 1:1) but in their own WALLART indices, so a leak is visible
        strip = self.alloc(0x600)
        row = bytes((0x41 if k == CHAN_COL else COLART + k) if k < 32 else WALLART + k - 32 for k in range(47))
        sdata = self.buffer(strip, 47, HN, 47, [row] * HN)
        # OPEN: the bake (rail_slide_in's frame: [ebp+8] = win, [ebp+0xC] = &sb)
        ebp = STACK + 0xC0000
        _w32(mu, ebp + 8, win)
        _w32(mu, ebp + 0xC, self.sb)
        sp = self.run(self.va["thunk_rail_bake"], [MARKER, buf, KEY, cw - 47, Y0, 1, 1],
                      {UC_X86_REG_ECX: strip, UC_X86_REG_EBP: ebp}, trace_engine=trace_engine)
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18
        assert _s32(int.from_bytes(mu.mem_read(buf + 0x84, 4), "little")) == -H           # height field restored
        strip_after = [bytes(mu.mem_read(sdata + y * 47, 47)) for y in range(HN)]      # the native strip, post-bake
        opened, raw = self.rows(cdata, cw, H, stride)
        guards_ok = all(raw[y * stride + cw: (y + 1) * stride] == bytes([GUARD]) * SLACK for y in range(H)) and \
            raw[H * stride:] == bytes([GUARD]) * (stride * GROWS)
        # the bar
        self.rec.pop(WIN_MOVE, None)
        self.rec.pop(self.resize, None)
        sp = STACK + 0x80000
        self.run(self.va["thunk_rail_sbfit"], [MARKER], {UC_X86_REG_EBX: win, UC_X86_REG_ESI: 425, UC_X86_REG_EBP: ebp})
        assert mu.reg_read(UC_X86_REG_EBX) == win and mu.reg_read(UC_X86_REG_EDI) == self.sb
        sbx, sby = self.rec[WIN_MOVE][:2]
        sbw, sbh = self.rec[self.resize][:2]
        # slide-out: capw -> L, hstep (animation pref on, not MP) -> the capture's final x
        left = 600
        R = left + cw
        self.run(self.va["thunk_railout_capw"], [MARKER], {UC_X86_REG_EDI: win, UC_X86_REG_ECX: R, UC_X86_REG_EAX: 0x1234})
        assert mu.reg_read(UC_X86_REG_ECX) == R and mu.reg_read(UC_X86_REG_EAX) == 0x1234
        L = R - _s32(mu.reg_read(UC_X86_REG_EDX)) - 0x20
        self.run(self.va["thunk_railout_hstep"], [MARKER],
                 {UC_X86_REG_EDI: win, UC_X86_REG_ESI: L, UC_X86_REG_EBX: 0x80000, UC_X86_REG_EDX: 0,
                  UC_X86_REG_ECX: 0, UC_X86_REG_EAX: 0x1234})
        assert mu.reg_read(UC_X86_REG_EAX) == 0x1234
        end = _s32(mu.reg_read(UC_X86_REG_ESI))
        lx, bx = L - left, end - left
        final = []
        for r in opened:                               # vanilla's tail: capture [L, R), clear to key, keyed re-blit
            cap = r[lx:cw]
            f = bytearray(r)
            f[lx:cw] = bytes([KEY]) * (cw - lx)
            for c, p in enumerate(cap):
                x = bx + c
                if lx <= x < cw and p != KEY:
                    f[x] = p
            final.append(bytes(f))
        return dict(closed=closed, opened=opened, final=final, guards_ok=guards_ok, sb=(sbx, sby, sbw, sbh),
                    L=lx, shift=bx - lx, hdev=hdev, H=H, native_rails=native_rails, strip=strip_after, strip_row=row)


def _widths(g):
    """Canvas widths: the real rail windows' at this g (4:3 and 16:9 screens) + a dense sweep."""
    s = SL.scale_px
    out = set()
    sh = 48 * g
    for sw in (sh * 4 // 3, sh * 16 // 9):
        strip = s(213, g)
        out.add(SL.rw_canvas_w((650 * g) >> 4, g))
        out.add(SL.basewin_window_rect(sw, sh, strip, g)[2])
        out.add(SL.filedlg_window_origin(sw, sh, strip, *SL.filedlg_native_origin(sw, sh, strip, True), g)[2])
        for i in range(0, 16):
            out.add(s(520, g) + i)
    lo, hi = max(160, (400 * g) >> 4), (820 * g) >> 4
    out.update(range(lo, hi, 23))
    return sorted(out)


def _cols(row, base, n):
    """{k: [x, ...]} for the art indices base + k present in a canvas row."""
    out = {}
    for x, p in enumerate(row):
        if base <= p < base + n:
            out.setdefault(p - base, []).append(x)
    return out


def check(rig, fam, cw):
    """Every property for one (family, g, canvas width); returns the list of failures (empty = pass)."""
    g = rig.g
    bad = []
    r = rig.scenario(fam, cw)
    gated = fam != "other" and g > 16
    closed, opened, final = r["closed"], r["opened"], r["final"]
    yr = range(Y0, Y0 + r["hdev"])
    if not r["guards_ok"]:
        bad.append("wrote past the canvas")
    if any(MARK_IDX in row for row in opened):
        bad.append("channel mark 0xFD survived")
    # thunk_rail_mark keys the native strip IN PLACE on the gated path: wall columns 32..46 are key 9 on every row and
    # the rail column 0..31 holds no key (a mark keyed from column 33 leaves column 32's wall art for the engine NN --
    # a 1-px diff in the top-cap row at g = 21..24 with the real art, invisible to the end state with this rig's art)
    for y, srow in enumerate(r["strip"]):
        if gated and (srow[32:] != bytes([KEY]) * 15 or KEY in srow[:32]):
            bad.append(("strip wall not keyed", y, srow.hex()))
            break
        if not gated and srow != r["strip_row"]:
            bad.append(("native strip touched", y))
            break
    sbx, sby, sbw, sbh = r["sb"]
    if g <= 16 or fam == "other":
        # vanilla arithmetic: strip 1:1 at cw - 47 with its own wall, the bar at cw - 0x2B, capture R - 47, -32 (g<=16)
        o = opened[Y0]
        cols = _cols(o, COLART, 32)
        if any(cols.get(k, [None])[0] != cw - 47 + k for k in range(32) if k != CHAN_COL):
            bad.append(("native column", cols))
        if _cols(o, WALLART, 15).get(0, [None])[0] != cw - 15:
            bad.append("native wall")
        if (sbx, sby, sbw, sbh) != (cw - 0x2B, 0x15, 0x18, 415):
            bad.append(("native bar", r["sb"]))
        if r["L"] != cw - 47:
            bad.append(("native capture", r["L"]))
        if r["shift"] != 0:                            # vanilla's own roll-up frames carry the -32; the thunk adds none
            bad.append(("native shift", r["shift"]))
        if g <= 16 and fam != "other":
            xs = [a[2] for a in (r["native_rails"] or [])]
            if xs != [cw - 0x37, cw - 0x2F]:
                bad.append(("native rails", xs))
        return bad
    lay = SL.rail_layout(cw, 490 * g // 16, g)
    S = lay["bake_x"]
    # 1. the strip starts AT the closed outer rail (no sliver)
    oc = _cols(closed[Y0], OUTER, 15)
    if not oc or min(min(v) for v in oc.values()) != S or S != SL.rail_strip_x(cw, g):
        bad.append(("strip x vs outer rail", S, oc and min(min(v) for v in oc.values())))
    # 2. open (W3B): native column k fills exactly the dest columns rail_col_map sends it -- one symmetric map, the two
    #    cyan lines K wide at mirrored offsets; the wall = the closed outer rail's pixels at wall_x = S + Wc
    cmap = SL.rail_col_map(cw, g)
    want_cols = {k: [S + j for j, v in enumerate(cmap) if v == k] for k in range(32)}
    (l0, l1), (r0, r1) = SL.rail_line_spans(cw, g)
    if not (l1 - l0 == r1 - r0 == SL.stroke_width(g) and l0 == len(cmap) - r1 and lay["wall_x"] == S + len(cmap)):
        bad.append(("lines not symmetric", (l0, l1), (r0, r1), len(cmap)))
    for y in yr:
        o = opened[y]
        cols = _cols(o, COLART, 32)
        for k in range(32):
            if k == CHAN_COL:
                continue
            if cols.get(k, []) != want_cols[k]:
                bad.append(("column", k, y, cols.get(k), want_cols[k]))
                break
        if cols.get(SL.RAIL_CYAN_L) != [S + j for j in range(l0, l1)] or \
                cols.get(SL.RAIL_CYAN_R) != [S + j for j in range(r0, r1)]:
            bad.append(("cyan lines", y, cols.get(SL.RAIL_CYAN_L), cols.get(SL.RAIL_CYAN_R)))
        if _cols(o, WALLART, 15):
            bad.append(("engine wall leaked", y))
        wx, fl15 = lay["wall_x"], (15 * g) >> 4
        if o[wx: wx + fl15] != closed[y][S: S + fl15] or lay["strip_right"] != wx + fl15 or wx + fl15 > cw:
            bad.append(("wall != closed outer rail", y, wx))
        if any(p != KEY for p in o[wx + fl15:]):
            bad.append(("right of the wall drawn", y))
        if o[:S] != closed[y][:S]:
            bad.append(("left of the strip touched", y))
    for y in range(r["H"]):                              # the strip's rows only: the wall stops at the strip bottom
        if y not in yr and opened[y] != closed[y]:
            bad.append(("drawn outside the strip rows", y))
            break
    # 3. the bar == the law, touches both cyan lines as DRAWN, inside the rail column (hit rect == drawn rect)
    cyl = _cols(opened[Y0], COLART, 32).get(SL.RAIL_CYAN_L, [])
    cyr = _cols(opened[Y0], COLART, 32).get(SL.RAIL_CYAN_R, [])
    if (sbx, sby, sbw, sbh) != (lay["sb_x"], lay["sb_y"], lay["sb_w"], lay["sb_h"]):
        bad.append(("bar != law", r["sb"]))
    if not cyl or not cyr or sbx != cyl[-1] + 1 or sbx + sbw != cyr[0]:
        bad.append(("bar not between the cyan lines", r["sb"], cyl, cyr))
    if not (S < sbx and sbx + sbw < lay["art_right"]):
        bad.append(("bar outside the column", r["sb"]))
    # 4. slide-out
    if fam == "report":
        if r["L"] != cw - 47:
            bad.append(("report capture (vanilla)", r["L"]))
        lo = cw - SL.scale_px(47, g) - 4
        for y in range(r["H"]):
            if any(opened[y][x] != closed[y][x] for x in range(min(lo, cw))):
                bad.append(("report: baked outside the saved column", y))
                break
        return bad
    if r["L"] != S or cw - r["L"] != SL.rail_out_tail(g, True, cw)[0]:
        bad.append(("capture L", r["L"], S))
    if r["shift"] != SL.rail_out_tail(g, True, cw)[1] or r["shift"] != -SL.rail_wall_off(cw, g):
        bad.append(("shift", r["shift"]))
    for y in yr:
        if final[y] != closed[y]:
            d = [x for x in range(cw) if final[y][x] != closed[y][x]]
            bad.append(("end state != closed", y, d[:6]))
            break
    return bad


@pytest.mark.parametrize("g", [12, 16] + list(range(17, 49)))
def test_scaling_rail_strip_engine_end_state(build, g):
    rig = Rig(build, g)
    fails = []
    for fam in FAMILIES:
        for cw in _widths(g):
            for f in check(rig, fam, cw):
                fails.append((fam, cw, f))
    assert not fails, fails[:8]


def test_rail_bake_runs_the_column_blit_not_the_engine(build):
    """W3B: at g > 16 the gated strip is drawn by t_rsb_blit (its rows are proven equal to the engine's below); the
    engine blit is not entered for it."""
    rig = Rig(build, 25)
    rig.scenario("filedlg", SL.scale_px(520, 25), trace_engine=True)
    addrs = {a for a, _s in rig.exec_engine}
    assert BUFFER_DRAW_2 not in addrs, "the gated strip must not reach the engine blit"


@pytest.mark.parametrize("g", list(range(17, 49)) + [56, 64, 80])
def test_rail_column_rows_are_the_engines(build, g):
    """t_rsb_blit keeps the ENGINE's rows (measure the engine, do not model it): the REAL Buffer_draw_2 (the build's
    0x5D84C0 + Sprite_draw_2 + the blit core) and t_rsb_blit draw the same row-coded strip (native row r = index
    10 + r % 200 on every column; rows 0..2 key, like the art above the top cap) into identical canvases at g/16; every
    dest row must carry the same source row (or be untouched in both), across strip heights, dest y and a clipped
    canvas bottom; and both equal the law rail_blit_rows.  The column blit writes only the rail column [x, x + Wc)."""
    rig = Rig(build, g)
    mu = rig.mu
    bad = []
    for hn in (5, 37, 120, 333, 480):
        for y0 in (0, 3, 17):
            for clip in (None, 100):
                rig.bump = rig.mark
                full = (hn * g) >> 4
                H = y0 + full + 6 if clip is None else min(clip, y0 + full + 6)
                cw = 2 * g + 40
                rows_out = []
                for entry in (BUFFER_DRAW_2, rig.va["t_rsb_blit"]):
                    dest = rig.alloc(0x600)
                    ddata = rig.buffer(dest, cw, H, cw + SLACK, KEY)
                    strip = rig.alloc(0x600)
                    srows = [bytes([KEY]) * 47 if r < 3 else bytes([10 + r % 200]) * 47 for r in range(hn)]
                    rig.buffer(strip, 47, hn, 47, srows)
                    sp = rig.run(entry, [MARKER, dest, KEY, 0, y0, g, 16], {UC_X86_REG_ECX: strip})
                    assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18
                    raw = bytes(mu.mem_read(ddata, (cw + SLACK) * (H + GROWS)))
                    assert raw[H * (cw + SLACK):] == bytes([GUARD]) * ((cw + SLACK) * GROWS), "wrote below the canvas"
                    rows_out.append([raw[y * (cw + SLACK)] for y in range(H)])
                    if entry != BUFFER_DRAW_2:
                        wc = SL.rail_col_w(cw, g)
                        if any(p != KEY for y in range(H) for p in raw[y * (cw + SLACK) + wc: y * (cw + SLACK) + cw]):
                            bad.append(("t_rsb_blit wrote right of Wc", hn, y0, clip))
                eng, ours = rows_out
                if eng != ours:
                    bad.append((hn, y0, clip, [(y, eng[y], ours[y]) for y in range(H) if eng[y] != ours[y]][:4]))
                law = SL.rail_blit_rows(hn, g, y0, H)
                if [p - 10 if p != KEY else None for p in ours[y0:y0 + len(law)]] != \
                        [r % 200 if r >= 3 else None for r in law] or any(p != KEY for p in ours[y0 + len(law):]):
                    bad.append(("law", hn, y0, clip))
    assert not bad, bad[:6]


@pytest.mark.parametrize("g", list(range(16, 97)))
def test_scaling_rail_nncol_walloff_asm_equal_the_laws(build, g):
    """thunk_rail_nncol / thunk_rail_walloff (real bytes) == rail_nn_col / rail_wall_off; rail_nn_col == the engine's
    own run table (Sprite_fill_scaling_table 0x5EB20F run on the .bak, read back from g_sprite_scale_runs)."""
    rig = Rig(build, g)
    mu = rig.mu
    _w32(mu, 0x00696D18, g)
    _w32(mu, 0x00696D1C, 16)
    rig.run(0x005EB20F, [MARKER], {})
    table = [int.from_bytes(mu.mem_read(0x009B3AD8 + 4 * i, 4), "little") for i in range(64)]
    for k in range(48):
        rig.run(rig.va["thunk_rail_nncol"], [MARKER], {UC_X86_REG_EAX: k, UC_X86_REG_EBX: 0x11, UC_X86_REG_ECX: 0x22,
                                                       UC_X86_REG_EDX: 0x33, UC_X86_REG_ESI: 0x44})
        got = mu.reg_read(UC_X86_REG_EAX)
        assert got == SL.rail_nn_col(k, g) == sum(table[:k]), (g, k, got)
        assert [mu.reg_read(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI)] == \
            [0x11, 0x22, 0x33, 0x44]
    if g == 16:
        return
    for cw in list(range(200, 2600, 37)) + _widths(min(g, 48)):
        rig.run(rig.va["thunk_rail_walloff"], [MARKER], {UC_X86_REG_EAX: cw, UC_X86_REG_ECX: 0x55})
        assert mu.reg_read(UC_X86_REG_EAX) == SL.rail_wall_off(cw, g), (g, cw)
        assert mu.reg_read(UC_X86_REG_ECX) == 0x55
