"""Differential: t_sbt_zoom / t_sbt_grip (scripts/assemble_stripes_btn.py) under Unicorn, wired exactly as they
ship -- behind the REAL cave bytes of thunk_btn_bandstripe, restripe_core, thunk_sb_thumb and thunk_sprite_scale_nn
resolved from patches.yaml, with the module's three token retargets applied in memory -- must leave the canvas equal
to the stripe law:

    FlatButton zoom   canvas == assemble_stripes_btn.btn_synth_zoom(native canvas)  (centre NN; every vertical
                      1-row dither regenerated: its top member where scaling_laws.stripe_top(dest row, g), else its
                      bottom), for every owned button class, every state pair, g in 18..40; glyph / stroke / bevel
                      pixels are plain NN; nothing outside the dest rect is written.
    scrollbar grip    canvas == today's draw (thunk_sb_thumb -> thunk_sprite_scale_nn, emulated from the same bytes)
                      with the grip's own pair inside thunk_sprite_scale_nn's rect rewritten by the same law.
    native / unowned  g <= 16, unarmed bars, unowned or excluded buttons and every refusal reach the callee they
                      reach today with the stack and registers the caller made.

It also pins the CAUSE of the MENU / COMMLINK defect on the unmodified bytes: thunk_btn_bandstripe probes two rows
of the already-zoomed canvas and bails when both map to one native row (g = 25 and g = 40 among others).

Skips (does not fail) if keystone/unicorn are absent.  Run with -p no:faulthandler.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_stripes_btn as M  # noqa: E402

G_SWEEP = (16, 18, 21, 22, 25, 32, 40)
PCAVE2, CAVE_LEN = M.PCAVE2, 0x40000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect; 0x40000 2026-10-25 W7H: t_sbt_zoom @0x3C600)
G_VA, PERIOD_VA = 0x00668740, 0x0066879C
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
BUF = DATA + 0x100                       # the dest Buffer object
SPR = DATA + 0x800                       # a Sprite object (grip)
SPR_DATA = DATA + 0x1000
PLANE = DATA + 0x10000
STRIDE, ROWS = 320, 160                  # stride > every dest width: a write past the row end lands in a checked gutter
F_CLIP, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0x4A8
SPRITE_DRAW_2 = 0x005E4B4A
REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9}
KEY9, GLYPH, BEVEL, STROKE = 9, 0x65, 0xBC, 0x1F
FILL = 0x77                              # canvas fill outside the composed native rect (not a pair member)

OTHER_BTN = 0x00940000                   # a popup-class FlatButton: not owned
EDITOR_BTN = 0x007B7264                  # scenario-editor palette button: not owned
WORLD_BTN = 0x007B39E8                   # HUD planet button (icon art): not owned


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _load():
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    return caves, ap.build_symbol_table(symbols, caves)


def _live(caves, symtab, entry, retarget=True):
    """(va, bytes) of a live pcave2 cave entry; with `retarget`, this module's token edits applied first (an entry
    that already carries them resolves the same way)."""
    cave = next(c for c in caves if c["id"] == "pcave2")
    e = next(c for c in cave["contents"] if c["id"] == entry)
    tpl = " ".join(str(e["bytes"]).split())
    for (ent, new), chained in M.CHAINED.items():        # W3B: t_rsb_grip forwards every non-rail bar to t_sbt_grip
        if ent == entry and chained in tpl:              # (this module's bars are not rail bars: emulate that hop's
            tpl = tpl.replace(chained, new)              # exit; tests/test_rail_sym_asm_parity.py proves it)
    if retarget:
        for ent, old, new in M.RETARGETS:
            if ent != entry:
                continue
            if tpl.count(old) == 1:
                tpl = tpl.replace(old, new)
            else:                                            # already applied to patches.yaml
                assert tpl.count(old) == 0 and new in tpl, (entry, old)
    va = PCAVE2 + int(e["offset"])
    return va, bytes(ap.ByteTemplate(tpl).resolve(va, symtab))


class Emu:
    """One emulator per wiring (Unicorn caches translated code: never re-wire a live instance)."""

    def __init__(self, retargeted: bool = True):
        caves, symtab = _load()
        self.syms = M.load_syms()
        self.layout = M.assemble_all(self.syms)
        self.va = M.names_of(self.layout)
        symtab = dict(symtab)
        symtab.update(self.va)
        self.symtab = symtab
        self.code = {}
        for name in ("thunk_btn_bandstripe", "restripe_core", "thunk_sb_thumb", "thunk_sprite_scale_nn"):
            self.code[name] = _live(caves, symtab, name, retarget=retargeted)
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)                  # g, the period cell and the KSB entry share this page
        mu.mem_map(SPRITE_DRAW_2 & ~0xFFF, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        # 2026-10-15: t_sbt_ph reads the esi-owned FlatButton's Win +0x140 / +0x150 (its parent-local top)
        for lo, hi in ((M.DW_LO, M.DW_HI), (M.BTN_ARROW_FIRST, M.BTN_ARROW_LAST + M.BTN_STRIDE), (M.SE_LO, M.SE_HI)):
            a, b_ = lo & ~0xFFF, (hi + 0x1000 + 0xFFF) & ~0xFFF
            try:
                mu.mem_map(a, b_ - a)
            except Exception:  # noqa: BLE001  (an overlapping range is already mapped)
                for pg in range(a, b_, 0x1000):
                    try:
                        mu.mem_map(pg, 0x1000)
                    except Exception:  # noqa: BLE001
                        pass
        for name, (off, b) in self.layout.items():
            mu.mem_write(PCAVE2 + off, b)
        self.ksb = symtab["thunk_keyed_stretch_blit"]
        assert G_VA & ~0xFFF == self.ksb & ~0xFFF
        mu.mem_write(self.ksb, b"\xC2\x2C\x00")            # ret 0x2C
        mu.mem_write(SPRITE_DRAW_2, b"\xC2\x18\x00")       # ret 0x18
        self.cov = {symtab[n]: n for n in ("thunk_chev_coverage", "thunk_staple_coverage", "thunk_arrow_coverage")}
        for va in self.cov:
            mu.mem_write(va, b"\xC2\x2C\x00")
        self.calls, self.errors = [], []
        self.ksb_zooms = True
        mu.hook_add(UC_HOOK_CODE, self._on_ksb, begin=self.ksb, end=self.ksb)
        mu.hook_add(UC_HOOK_CODE, self._on_sd2, begin=SPRITE_DRAW_2, end=SPRITE_DRAW_2)
        for va in self.cov:
            mu.hook_add(UC_HOOK_CODE, self._on_cov, begin=va, end=va)
        self.core_calls = []
        core = symtab["restripe_core"]
        mu.hook_add(UC_HOOK_CODE, lambda m, a, sz, u: self.core_calls.append(
            [_r32(m, m.reg_read(UC_X86_REG_ESP) + 4 + 4 * i) for i in range(8)]), begin=core, end=core)
        for va, b in self.code.values():
            mu.mem_write(va, b)

    # ---- callee stand-ins ----
    def _rec(self, kind, nargs):
        mu = self.mu
        esp = mu.reg_read(UC_X86_REG_ESP)
        rec = {"kind": kind, "esp": esp, "ret": _r32(mu, esp),
               "args": [_r32(mu, esp + 4 + 4 * i) for i in range(nargs)],
               "ecx": mu.reg_read(UC_X86_REG_ECX),
               "regs": {r: mu.reg_read(r) for r in REGS}}
        self.calls.append(rec)
        return rec

    def _on_ksb(self, mu, address, size, user):
        """The engine stretch: centre-sampled NN of (sx,sy,sw,sh) -> (dx,dy,dw,dh), same buffer, opaque."""
        try:
            rec = self._rec("ksb", 11)
            if not self.ksb_zooms:
                return
            _dst, _src, sx, sy, sw, sh, dx, dy, dw, dh, _key = rec["args"]
            pl = bytearray(mu.mem_read(PLANE, STRIDE * ROWS))
            src = [[pl[(sy + r) * STRIDE + sx + c] for c in range(sw)] for r in range(sh)]
            for j in range(dh):
                r = SL.nn_center_index(j, dh, sh)
                for i in range(dw):
                    pl[(dy + j) * STRIDE + dx + i] = src[r][SL.nn_center_index(i, dw, sw)]
            mu.mem_write(PLANE, bytes(pl))
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    def _on_sd2(self, mu, address, size, user):
        self._rec("sd2", 6)

    def _on_cov(self, mu, address, size, user):
        self._rec(self.cov[address], 11)

    # ---- common run ----
    def start(self, entry, args, ecx, esi, ebx=None, count=80_000_000):
        mu = self.mu
        self.calls.clear()
        self.core_calls.clear()
        self.errors.clear()
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x1000, b"\xA5" * 0x1400)
        _w32(mu, sp, MARKER)
        for i, a in enumerate(args):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_EFLAGS, 0x202)               # DF clear, as the ABI guarantees at a call
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.reg_write(UC_X86_REG_ESI, esi)
        mu.reg_write(UC_X86_REG_ECX, ecx)
        if ebx is not None:
            mu.reg_write(UC_X86_REG_EBX, ebx)
        mu.emu_start(entry, MARKER, count=count)
        assert not self.errors, self.errors
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER, "did not return to the caller"
        assert bytes(mu.mem_read(sp + 4 + 4 * len(args), 0x100)) == b"\xA5" * 0x100, "wrote above its own args"
        assert bytes(mu.mem_read(sp - 0x1000, 0x400)) == b"\xA5" * 0x400, "stack use deeper than 0xC00"
        return sp

    def set_scale(self, g):
        _w32(self.mu, G_VA, g)
        _w32(self.mu, PERIOD_VA, SL.stripe_period(g))

    def set_buffer(self, w, h, clip, data_ptr=PLANE):
        mu = self.mu
        mu.mem_write(BUF, b"\x00" * 0x500)
        _w32(mu, BUF + F_DATA, data_ptr)
        _w32(mu, BUF + F_W, w)
        _w32(mu, BUF + F_H, -h)
        _w32(mu, BUF + F_STRIDE, STRIDE)
        for i, v in enumerate(clip):
            _w32(mu, BUF + F_CLIP + 4 * i, v)

    def plane(self):
        return bytes(self.mu.mem_read(PLANE, STRIDE * ROWS))


@pytest.fixture(scope="module")
def emu():
    return Emu()


@pytest.fixture(scope="module")
def emu_orig():
    """The live bytes WITHOUT this module's retargets: today's behaviour."""
    return Emu(retargeted=False)


# ==== native canvases ============================================================================================
def _band(sw, sh, pair=(0x92, 0xC8)):
    """The HUD MENU / COMMLINK state band: a pure 1-row pair, corner pixels of other indices, row 0 = pair[0]."""
    a, b = pair
    rows = [[a if y % 2 == 0 else b for _x in range(sw)] for y in range(sh)]
    rows[0][0] = rows[0][1] = 0x26
    rows[sh - 1][0] = rows[sh - 1][1] = 0x40
    rows[0][sw - 1] = 0x94
    return rows


def _arrow_face(sw, sh, bg=(0xC5, 0x41), chev=(0xF0, 0xB9), phase=0):
    """An SE / DW style arrow button: bevel ring, a 1-row dither face background, a chevron triangle of a SECOND
    1-row pair, a solid 3-row bar of the chevron's top colour (solid art sharing a pair index) and a glyph pixel."""
    rows = [[BEVEL] * sw for _ in range(sh)]
    for y in range(1, sh - 1):
        for x in range(1, sw - 1):
            rows[y][x] = bg[(y + phase) % 2]
    mid = sh // 2
    for y in range(3, sh - 3):
        half = (sw // 2 - 2) - abs(y - mid)
        for x in range(sw // 2 - max(half, 0), sw // 2 + max(half, 0)):
            if half > 0:
                rows[y][x] = chev[y % 2]
    for y in range(1, 4):                                    # solid art in a pair member's index: must stay solid
        rows[y][2] = rows[y][3] = chev[0]
    rows[mid][1] = GLYPH
    return rows


def _unit_arrow(sw=12, sh=42, pair=(0xF0, 0xB9)):
    """The 12x42 unit-row arrow: a triangle of a 1-row pair over the canvas key, a stroke on its flat edge."""
    rows = []
    for y in range(sh):
        half = abs(2 * y + 1 - sh) / 2
        span = max(0, round(sw * (1 - 2 * half / sh)))
        row = [KEY9] * sw
        for x in range(span):
            row[x] = pair[y % 2]
        if span:
            row[0] = STROKE
        rows.append(row)
    return rows


def _bar(sw, sh, pair=(0x1C, 0x50)):
    """A BaseWin bar / tab: caps, a solid highlight row, a 1-row wood pair, a solid gradient row."""
    rows = [[pair[y % 2] for _x in range(sw)] for y in range(sh)]
    rows[0] = [0x8F] * sw
    rows[1] = [0x8E] * sw
    rows[sh - 1] = [0x12] * sw
    for y in range(sh):
        rows[y][0] = rows[y][sw - 1] = 0x14
    return rows


def _dims(nw, nh, g):
    """Device dims of a button whose native client is nw x nh, and the native dims thunk_btn_shrink derives back
    (origW * 16 / g, truncating) -- what thunk_btn_2dscale passes as (sw, sh, dw, dh)."""
    dw, dh = nw * g // 16, nh * g // 16
    return dw * 16 // g, dh * 16 // g, dw, dh


def _compose(native):
    """Plane with the native canvas at (0,0); FILL elsewhere (anything written outside the dest rect shows)."""
    pl = bytearray([FILL]) * (STRIDE * ROWS)
    for y, row in enumerate(native):
        pl[y * STRIDE: y * STRIDE + len(row)] = bytes(row)
    return pl


def _crop(art, sw, sh):
    return [row[:sw] for row in art[:sh]]


def _expected(native, dw, dh, g, phase=0, esi=0):
    """esi: the FlatButton -- a BaseWin face is sampled mirror-symmetrically (W7H, law btn_zoom_index)."""
    pl = _compose(native)
    out = M.btn_synth_zoom(native, dw, dh, g, phase=phase, mirror=SL.btn_zoom_mirrored(esi))
    for j, row in enumerate(out):
        pl[j * STRIDE: j * STRIDE + dw] = bytes(row)
    return bytes(pl)


def _nn(native, dw, dh):
    pl = _compose(native)
    sh, sw = len(native), len(native[0])
    for j in range(dh):
        r = SL.nn_center_index(j, dh, sh)
        pl[j * STRIDE: j * STRIDE + dw] = bytes(native[r][SL.nn_center_index(i, dw, sw)] for i in range(dw))
    return bytes(pl)


def _run_band(emu, g, esi, native, dw, dh, *, clip=None, tops=(0, 0)):
    """Call thunk_btn_bandstripe exactly as thunk_btn_2dscale does.  tops = the button's Win +0x140 / +0x150
    (written only for the esi-owned classes, whose objects the emulator maps)."""
    sh, sw = len(native), len(native[0])
    if not M.btn_zoom_owned(esi) or M.BASEWIN_LO <= esi < M.BASEWIN_HI or esi in (M.BTN_MENU, M.BTN_COMMLINK):
        assert tops == (0, 0)
    else:
        _w32(emu.mu, esi + 0x140, tops[0] & 0xFFFFFFFF)
        _w32(emu.mu, esi + 0x150, tops[1] & 0xFFFFFFFF)
    emu.set_scale(g)
    emu.set_buffer(sw, sh, clip or (0, 0, dw, dh))            # mid-bracket the W / H fields hold the NATIVE dims
    emu.mu.mem_write(PLANE, bytes(_compose(native)))
    args = [BUF, BUF, 0, 0, sw, sh, 0, 0, dw, dh, 0xFFFFFFFF]
    sp = emu.start(emu.code["thunk_btn_bandstripe"][0], args, ecx=0xCCCC0001, esi=esi)
    mu = emu.mu
    assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C, "stack imbalance (RET 0x2C)"
    assert mu.reg_read(UC_X86_REG_ESI) == esi
    for r in (UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert mu.reg_read(r) == REGS[r], "callee-saved register not preserved"
    return emu.plane()


def _assert_law_direct(got, native, dw, dh, g, mirror=False):
    """The rule itself, not via the model's enlarge: every dest pixel whose source pixel is dither carries its
    pair's top exactly where (row mod 2T) < T, and its bottom elsewhere; every other dest pixel is its source
    (through nn_mirror_index for a BaseWin face, W7H)."""
    T = SL.stripe_rows(g)
    assert SL.stripe_period(g) == 2 * T
    sh, sw = len(native), len(native[0])
    canon, marks, bottom = M.btn_dither_marks(native)
    idx = SL.nn_mirror_index if mirror else SL.nn_center_index
    seen = 0
    for j in range(dh):
        r = idx(j, dh, sh)
        for i in range(dw):
            c = idx(i, dw, sw)
            v = got[j * STRIDE + i]
            if (r, c) in marks:
                top = canon[r][c]
                assert v == (top if (j % (2 * T)) < T else bottom[top]), (g, i, j, hex(v))
                seen += 1
            else:
                assert v == native[r][c], (g, i, j, hex(v))
    assert seen > 0, "the fixture has no dither"


# ==== (0) the cause, pinned on the UNMODIFIED bytes ================================================================
def _band_probe_fires(emu, g):
    sw, sh, dw, dh = 106, 14, 106 * g // 16, 14 * g // 16
    native = _band(sw, sh)
    got = _run_band(emu, g, M.BTN_MENU, native, dw, dh)
    assert [c["kind"] for c in emu.calls] == ["ksb"]
    assert got == _nn(native, dw, dh) or emu.core_calls, "only restripe_core may change the zoomed band"
    return bool(emu.core_calls), got, native, dw, dh


BAND_PROBE_BAILS = [g for g in range(17, 41)
                    if SL.nn_center_index(7, 14 * g // 16, 14) == SL.nn_center_index(8, 14 * g // 16, 14)]


# ==== (1) + (3) t_sbt_zoom through the retargeted chain =============================================================
ZOOM_CASES = [
    ("menu_idle", M.BTN_MENU, lambda sw, sh: _band(sw, sh, (0x92, 0xC8)), (106, 14)),
    ("menu_hover", M.BTN_MENU, lambda sw, sh: _band(sw, sh, (0xE6, 0xE7)), (106, 14)),
    ("commlink_pressed", M.BTN_COMMLINK, lambda sw, sh: _band(sw, sh, (0x63, 0x66)), (106, 14)),
    ("basewin_bar", M.BASEWIN_LO, lambda sw, sh: _bar(sw, sh), (90, 20)),
    ("basewin_name_arrow", M.BASEWIN_LO + 20 * M.BTN_STRIDE,
     lambda sw, sh: _crop(_unit_arrow(18, 30, (0xAE, 0xEE)), sw, sh), (18, 30)),
    ("unit_arrow_left", M.BTN_ARROW_FIRST + M.BTN_STRIDE, lambda sw, sh: _crop(_unit_arrow(), sw, sh), (12, 42)),
    ("unit_arrow_right_hover", M.BTN_ARROW_LAST,
     lambda sw, sh: _crop(_unit_arrow(pair=(0xA2, 0xEF)), sw, sh), (12, 42)),
    ("se_arrow", M.SE_LO + 33 * M.BTN_STRIDE, lambda sw, sh: _arrow_face(sw, sh), (20, 20)),
    ("se_arrow_odd_phase", M.SE_LO, lambda sw, sh: _arrow_face(sw, sh, phase=1), (20, 20)),
    ("dw_arrow_hover", M.DW_LO + 5 * M.BTN_STRIDE,
     lambda sw, sh: _arrow_face(sw, sh, bg=(0xC2, 0xC5), chev=(0xA2, 0xEF)), (14, 24)),
    ("dw_last", M.DW_HI - M.BTN_STRIDE, lambda sw, sh: _arrow_face(sw, sh), (20, 20)),
]


@pytest.mark.parametrize("g", [g for g in G_SWEEP if g > 16])
@pytest.mark.parametrize("name,esi,art,nat", ZOOM_CASES, ids=[c[0] for c in ZOOM_CASES])
def test_zoom_regenerates_every_dither_on_the_law(emu, g, name, esi, art, nat):
    sw, sh, dw, dh = _dims(*nat, g)
    native = art(sw, sh)
    got = _run_band(emu, g, esi, native, dw, dh)
    assert emu.calls == [], "an owned button must not reach the KSB or a coverage filter"
    assert got == _expected(native, dw, dh, g, esi=esi), f"{name} g={g}"
    _assert_law_direct(got, native, dw, dh, g, mirror=SL.btn_zoom_mirrored(esi))


# ==== 2026-10-25 W7H: a BaseWin face is sampled mirror-symmetrically (law scaling_laws.btn_zoom_index) =============
def _stroke_face(sw, sh, stroke=0xE7, pair=(0xE8, 0xE9)):
    """The BaseWin tab-row 9-slice face (EXPLORE, state 0, measured on the pristine image): a 1-px stroke on all four
    sides with 1x1 key corner notches around a vertical 1-row dither."""
    rows = []
    for y in range(sh):
        edge_y = y in (0, sh - 1)
        rows.append([KEY9 if (edge_y and x in (0, sw - 1)) else stroke if (edge_y or x in (0, sw - 1))
                     else pair[y % 2] for x in range(sw)])
    return rows


def _edge_runs(got, dw, dh, stroke=0xE7):
    """(left, right, top, bottom) stroke runs on the middle row / column, (TL, TR, BL, BR) key-notch widths."""
    rows = [list(got[j * STRIDE: j * STRIDE + dw]) for j in range(dh)]

    def run(line):
        k = 0
        while k < len(line) and line[k] == stroke:
            k += 1
        return k
    ym, xm = dh // 2, dw // 2
    col = [r[xm] for r in rows]

    def notch(row):
        k = 0
        while k < len(row) and row[k] == KEY9:
            k += 1
        return k
    return ((run(rows[ym]), run(rows[ym][::-1]), run(col), run(col[::-1])),
            (notch(rows[0]), notch(rows[0][::-1]), notch(rows[-1]), notch(rows[-1][::-1])))


def test_law_mirror_map_is_in_place_safe():
    """t_sbt_zoom enlarges IN PLACE (rows bottom-up, columns right-to-left): every dest index must read a source
    index <= itself, and the map must be monotone -- for the mirror map too (every enlarge 1..64 -> src..4 src)."""
    for src in range(1, 65):
        for dst in range(src, 4 * src + 1):
            m = [SL.btn_zoom_index(j, dst, src, True) for j in range(dst)]
            assert all(m[j] <= j for j in range(dst)) and m == sorted(m) and set(m) == set(range(src)), (src, dst)
            # mirror pairs of dest indices read mirror source indices (palindromic edge runs); an odd dest axis's
            # middle pixel has no twin (an even source cannot map it to both central pixels)
            assert all(m[j] + m[dst - 1 - j] == src - 1 for j in range(dst) if 2 * j + 1 != dst), (src, dst)
    assert SL.btn_zoom_mirrored(M.BASEWIN_LO) and not SL.btn_zoom_mirrored(M.BASEWIN_HI)
    assert (SL.BASEWIN_BTN_LO, SL.BASEWIN_BTN_HI) == (M.BASEWIN_LO, M.BASEWIN_HI)


@pytest.mark.parametrize("g", (17, 22, 24, 25, 33, 40))
def test_basewin_face_strokes_and_notches_are_palindromic(emu, g):
    """W7H (the F39 class on the base screen): a BaseWin 9-slice face's 1-px stroke and its 1x1 notches come out the
    same on every side at every g (the centre map drew 1 | 2 at g 24 and 2 | 3 at g 40 -- measured on the real image
    in every state); the run is the centre map's left / top run, so only the tie g's change.  The same face under
    another owned class (SE) keeps the centre map: uneven at g 24 / 40 (pins that the arm is scoped)."""
    sw, sh, dw, dh = _dims(112, 20, g)
    native = _stroke_face(sw, sh)
    got = _run_band(emu, g, M.BASEWIN_LO + 2 * M.BTN_STRIDE, native, dw, dh)
    assert got == _expected(native, dw, dh, g, esi=M.BASEWIN_LO)
    (l, r, t, b), notches = _edge_runs(got, dw, dh)
    assert l == r == t == b and len(set(notches)) == 1, (g, (l, r, t, b), notches)
    assert l == SL.nn_center_index(0, dw, sw) * 0 + sum(1 for i in range(dw) if SL.nn_center_index(i, dw, sw) == 0)
    assert abs(l - g / 16) < 1 and notches[0] == l
    se = _run_band(emu, g, M.SE_LO, native, dw, dh)
    (l2, r2, t2, b2), _n2 = _edge_runs(se, dw, dh)
    assert (l2 == r2) == (g not in (24, 40)) and l2 == l, (g, l2, r2)


@pytest.mark.parametrize("g", (22, 25, 40))
def test_zoom_nominal_native_dims(emu, g):
    """The band at its nominal 106 x 14 native client (the screenshots show 14 -> 21 / 35 rows)."""
    sw, sh, dw, dh = 106, 14, 106 * g // 16, 14 * g // 16
    native = _band(sw, sh)
    got = _run_band(emu, g, M.BTN_MENU, native, dw, dh)
    assert got == _expected(native, dw, dh, g)
    T = SL.stripe_rows(g)
    col = [got[j * STRIDE + 50] for j in range(dh)]
    assert col == [0x92 if (j % (2 * T)) < T else 0xC8 for j in range(dh)], "92 on top, T rows each, from row 0"


def test_zoom_leaves_solid_art_glyphs_and_strokes_alone(emu):
    """Pair-ambiguity: a solid block in a pair member's index, the bevel, the glyph pixel and the key are plain NN."""
    g = 25
    sw, sh, dw, dh = _dims(20, 20, g)
    native = _arrow_face(sw, sh)
    canon, marks, _bottom = M.btn_dither_marks(native)
    assert (1, 2) not in marks and (2, 3) not in marks and native[1][2] == 0xF0, "the solid bar is not dither"
    got = _run_band(emu, g, M.SE_LO, native, dw, dh)
    for j in range(dh):
        r = SL.nn_center_index(j, dh, sh)
        for i in range(dw):
            c = SL.nn_center_index(i, dw, sw)
            if native[r][c] in (BEVEL, GLYPH) or (r, c) in ((1, 2), (1, 3), (2, 2), (2, 3), (3, 2), (3, 3)):
                assert got[j * STRIDE + i] == native[r][c]
    g2 = 22
    sw, sh, dw, dh = _dims(12, 42, g2)
    arrow = _crop(_unit_arrow(), sw, sh)
    got = _run_band(emu, g2, M.BTN_ARROW_LAST, arrow, dw, dh)
    for j in range(dh):
        r = SL.nn_center_index(j, dh, sh)
        for i in range(dw):
            c = SL.nn_center_index(i, dw, sw)
            if arrow[r][c] in (KEY9, STROKE):
                assert got[j * STRIDE + i] == arrow[r][c]


def test_zoom_checkerboard_is_regenerated_per_column(emu):
    """A checkerboard (adjacent columns in opposite phase) keeps its column alternation: each column regenerates
    its own even-row member on stripe-top rows."""
    g = 32
    native = [[(0xC5, 0x41)[(x + y) % 2] for x in range(16)] for y in range(12)]
    got = _run_band(emu, g, M.SE_LO, native, 32, 24)
    assert got == _expected(native, 32, 24, g)
    assert got[0] == 0xC5 and got[2] == 0x41 and got[2 * STRIDE] == 0x41


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("esi", [OTHER_BTN, EDITOR_BTN, WORLD_BTN, M.DW_LO - M.BTN_STRIDE, M.DW_HI, M.SE_HI,
                                 M.BTN_ARROW_FIRST - M.BTN_STRIDE, M.BTN_ARROW_LAST + M.BTN_STRIDE])
def test_unowned_buttons_keep_the_plain_ksb(emu, g, esi):
    sw, sh, dw, dh = _dims(20, 20, g)
    native = _arrow_face(sw, sh)
    got = _run_band(emu, g, esi, native, dw, dh)
    assert [c["kind"] for c in emu.calls] == ["ksb"]
    assert emu.calls[0]["args"] == [BUF, BUF, 0, 0, sw, sh, 0, 0, dw, dh, 0xFFFFFFFF]
    assert got == _nn(native, dw, dh)


@pytest.mark.parametrize("esi,stub", [(M.EXCLUDED[0], "thunk_staple_coverage"), (M.EXCLUDED[1], "thunk_chev_coverage"),
                                      (M.EXCLUDED[2], "thunk_chev_coverage")])
def test_staple_and_chevrons_keep_their_coverage_filter(emu, esi, stub):
    sw, sh, dw, dh = _dims(20, 20, 25)
    native = _arrow_face(sw, sh)
    got = _run_band(emu, 25, esi, native, dw, dh)
    assert [c["kind"] for c in emu.calls] == [stub]
    assert got == bytes(_compose(native)), "the (stubbed) coverage filter is the only writer"


def _direct_zoom(emu, g, esi, ebx, native, dw, dh, *, clip=None, data_ptr=PLANE, period=None):
    """Call t_sbt_zoom itself (the contract with its caller: ebx in, ebx out, the pass path's stack)."""
    sh, sw = len(native), len(native[0])
    emu.set_scale(g)
    if period is not None:
        _w32(emu.mu, PERIOD_VA, period)
    emu.set_buffer(sw, sh, clip or (0, 0, dw, dh), data_ptr=data_ptr)
    emu.mu.mem_write(PLANE, bytes(_compose(native)))
    args = [BUF, BUF, 0, 0, sw, sh, 0, 0, dw, dh, 0xFFFFFFFF]
    sp = emu.start(emu.va["t_sbt_zoom"], args, ecx=0xCCCC0001, esi=esi, ebx=ebx)
    mu = emu.mu
    assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C
    assert mu.reg_read(UC_X86_REG_ESI) == esi
    for r in (UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert mu.reg_read(r) == REGS[r]
    return emu.plane(), mu.reg_read(UC_X86_REG_EBX), sp


def test_zoom_native_scale_is_the_ksb_alone(emu):
    """g <= 16: tail-jump to the KSB with the caller's stack and registers; the canvas is the KSB's (1:1)."""
    native = _band(106, 14)
    for ebx in (0, 1):
        got, ebx_out, sp = _direct_zoom(emu, 16, M.BTN_MENU, ebx, native, 106, 14)
        assert [c["kind"] for c in emu.calls] == ["ksb"]
        c = emu.calls[0]
        assert c["esp"] == sp and c["ret"] == MARKER and c["regs"][UC_X86_REG_EBX] == ebx and ebx_out == ebx
        assert c["regs"][UC_X86_REG_EDI] == REGS[UC_X86_REG_EDI] and c["regs"][UC_X86_REG_EBP] == REGS[UC_X86_REG_EBP]
        assert got == bytes(_compose(native))


def test_zoom_match_flag_contract(emu):
    """Owned by ebx != 0 (thunk_btn_bandstripe's flag) whatever esi is; on success ebx comes back 0 so the caller
    skips its probe.  ebx == 0 and an unowned esi -> the KSB, ebx untouched."""
    sw, sh, dw, dh = _dims(90, 20, 25)
    native = _bar(sw, sh)
    got, ebx_out, _sp = _direct_zoom(emu, 25, OTHER_BTN, 1, native, dw, dh)
    assert emu.calls == [] and ebx_out == 0 and got == _expected(native, dw, dh, 25)
    got, ebx_out, sp = _direct_zoom(emu, 25, OTHER_BTN, 0, native, dw, dh)
    assert [c["kind"] for c in emu.calls] == ["ksb"] and ebx_out == 0 and emu.calls[0]["esp"] == sp
    assert got == _nn(native, dw, dh)


REFUSALS = [
    ("three_rows", dict(native=_bar(40, 3), dw=62, dh=4)),
    ("not_an_enlarge_w", dict(native=_bar(40, 12), dw=39, dh=18)),
    ("not_an_enlarge_h", dict(native=_bar(40, 12), dw=62, dh=11)),
    ("too_many_native_px", dict(native=_bar(130, 64), dw=140, dh=70)),
    ("clip_ends_short_right", dict(native=_bar(40, 12), dw=62, dh=18, clip=(0, 0, 61, 18))),
    ("clip_ends_short_bottom", dict(native=_bar(40, 12), dw=62, dh=18, clip=(0, 0, 62, 17))),
    ("period_cell_zero", dict(native=_bar(40, 12), dw=62, dh=18, period=0)),
]


@pytest.mark.parametrize("name,kw", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_zoom_refusals_fall_back_to_the_ksb_untouched(emu, name, kw):
    kw = dict(kw)
    native = kw.pop("native")
    got, ebx_out, sp = _direct_zoom(emu, 25, M.BTN_MENU, 1, native, kw.pop("dw"), kw.pop("dh"), **kw)
    assert [c["kind"] for c in emu.calls] == ["ksb"], name
    c = emu.calls[0]
    assert c["esp"] == sp and c["ret"] == MARKER and ebx_out == 1, "the pass path must not touch the stack or ebx"


def test_zoom_buffer_without_pixels(emu):
    emu.ksb_zooms = False
    try:
        native = _bar(40, 12)
        got, ebx_out, sp = _direct_zoom(emu, 25, M.BTN_MENU, 1, native, 62, 18, data_ptr=0)
        assert [c["kind"] for c in emu.calls] == ["ksb"] and ebx_out == 1 and got == bytes(_compose(native))
    finally:
        emu.ksb_zooms = True


def test_zoom_writes_nothing_outside_the_dest_rect(emu):
    """Hostile surroundings: pair members everywhere beyond the dest rect; none may change."""
    g = 40
    sw, sh, dw, dh = _dims(20, 20, g)
    native = _arrow_face(sw, sh)
    emu.set_scale(g)
    emu.set_buffer(sw, sh, (0, 0, dw, dh))
    pl = bytearray((0xC5, 0x41, 0xF0, 0xB9, 0xAE, 0xEE)[(x + 5 * y) % 6] for y in range(ROWS) for x in range(STRIDE))
    for y, row in enumerate(native):
        pl[y * STRIDE: y * STRIDE + sw] = bytes(row)
    emu.mu.mem_write(PLANE, bytes(pl))
    emu.start(emu.code["thunk_btn_bandstripe"][0], [BUF, BUF, 0, 0, sw, sh, 0, 0, dw, dh, 0xFFFFFFFF],
              ecx=0, esi=M.SE_LO)
    got = emu.plane()
    out = M.btn_synth_zoom(native, dw, dh, g)
    for y in range(ROWS):
        for x in range(STRIDE):
            want = out[y][x] if (y < dh and x < dw) else pl[y * STRIDE + x]
            assert got[y * STRIDE + x] == want, (x, y)


# ==== (2) t_sbt_grip =================================================================================================
def _grip(w=10, h=10, pair=(0xC5, 0xC2), first_row=1):
    """A thumb grip: light top/left border, dark bottom/right border, a 1-row pair between (row 1 = pair[0])."""
    rows = [[0xE4] * w]
    for y in range(1, h - 1):
        rows.append([0xE4] + [pair[(y - first_row) % 2]] * (w - 2) + [0xB7])
    rows.append([0xB7] * w)
    return rows


def _solid_grip(w=10, h=10):
    rows = _grip(w, h)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            rows[y][x] = 0xF0
    return rows


def _trough_plane(bw, bh):
    """The bar canvas: a 1-row 0x41 / 0xC5 trough dither (hostile: the grip pair shares 0xC5) and rail strokes."""
    pl = bytearray([FILL]) * (STRIDE * ROWS)
    for y in range(bh):
        for x in range(bw):
            pl[y * STRIDE + x] = STROKE if x in (0, bw - 1) else (0xC5 if y % 2 == 0 else 0x41)
    return pl


def _run_grip(emu, g, sprite, x, y, *, netwin=1, lo=0, to=0, pad=0, bw=24, bh=120, key=KEY9):
    """Enter thunk_sb_thumb as the ScrollBar_draw site does: Sprite_draw_2(dest, key, x, y, 1, 1), ecx = sprite."""
    mu = emu.mu
    h, w = len(sprite), len(sprite[0])
    pitch = w + pad
    mu.mem_write(SPR, b"\x00" * 0x40)
    _w32(mu, SPR + 4, SPR_DATA)
    mu.mem_write(SPR + 8, bytes([key]))
    _w32(mu, SPR + 0xC, pitch)
    _w32(mu, SPR + 0x10, w)
    _w32(mu, SPR + 0x14, h)
    _w32(mu, SPR + 0x18, w + lo)
    _w32(mu, SPR + 0x1C, h + to)
    _w32(mu, SPR + 0x20, lo)
    _w32(mu, SPR + 0x24, to)
    blob = bytearray([0xEE]) * (pitch * h)
    for r, row in enumerate(sprite):
        blob[r * pitch: r * pitch + w] = bytes(row)
    mu.mem_write(SPR_DATA, bytes(blob))
    emu.set_scale(g)
    _w32(mu, emu.symtab["g_netwin_active"], netwin)
    emu.set_buffer(bw, bh, (0, 0, bw, bh))
    mu.mem_write(PLANE, bytes(_trough_plane(bw, bh)))
    sp = emu.start(emu.code["thunk_sb_thumb"][0], [BUF, key, x, y, 1, 1], ecx=SPR, esi=REGS[UC_X86_REG_ESI])
    assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18, "stack imbalance (RET 0x18)"
    for r in REGS:
        assert mu.reg_read(r) == REGS[r], "callee-saved register not preserved"
    assert bytes(mu.mem_read(SPR_DATA, len(blob))) == bytes(blob), "the shared sprite art must never be written"
    return emu.plane(), sp


def _grip_expected(emu_orig, g, sprite, x, y, **kw):
    """Today's draw (same live bytes, no retarget), then the law over thunk_sprite_scale_nn's rect."""
    base, _sp = _run_grip(emu_orig, g, sprite, x, y, **kw)
    if g <= 16 or not kw.get("netwin", 1):
        return base, None, None
    h, w = len(sprite), len(sprite[0])
    adj_x = x - (((w + kw.get("lo", 0)) * (g - 16)) >> 5)       # thunk_sb_thumb's recentre (its live bytes ran above)
    adj_y = y - (((h + kw.get("to", 0)) * (g - 16)) >> 5)
    pair = M.sb_grip_pair(sprite)
    rect = M.sb_grip_rect(adj_x, adj_y, g, w=w, h=h, lo=kw.get("lo", 0), to=kw.get("to", 0), buf_h=kw.get("bh", 120))
    want = bytearray(base)
    if pair and rect:
        rx, ry, rw, rh = rect
        for yy in range(ry, ry + rh):
            for xx in range(rx, min(rx + rw, STRIDE)):
                want[yy * STRIDE + xx] = M.sb_grip_pixel(base[yy * STRIDE + xx], yy, g, pair)
    return bytes(want), pair, rect


GRIP_STATES = [
    ("base_screen_c5_c2", _grip(10, 10, (0xC5, 0xC2))),
    ("console_f0_b9", _grip(10, 12, (0xB9, 0xF0))),
    ("hover_a2_ef", _grip(12, 9, (0xA2, 0xEF))),
    ("pair_starts_on_row_2", _grip(10, 11, (0xC2, 0xC5), first_row=2)),
]


@pytest.mark.parametrize("g", [g for g in G_SWEEP if g > 16])
@pytest.mark.parametrize("name,sprite", GRIP_STATES, ids=[s[0] for s in GRIP_STATES])
def test_grip_pair_is_restriped_over_the_drawn_rect(emu, emu_orig, g, name, sprite):
    x, y = 9, 47
    want, pair, rect = _grip_expected(emu_orig, g, sprite, x, y)
    got, _sp = _run_grip(emu, g, sprite, x, y)
    assert pair is not None and rect is not None
    assert got == want, f"{name} g={g}"
    assert [c["kind"] for c in emu.calls] == [], "the armed path draws through thunk_sprite_scale_nn"
    assert len(emu.core_calls) == 1 and emu.core_calls[0][:5] == [BUF, *rect], "restripe_core gets exactly the drawn rect"
    assert set(emu.core_calls[0][5:7]) == set(pair) and emu.core_calls[0][7] == pair[0]
    rx, ry, rw, rh = rect
    T = SL.stripe_rows(g)
    for yy in range(ry + 2, ry + rh - 2):                    # the rule itself, inside the grip (borders aside)
        v = got[yy * STRIDE + rx + rw // 2]
        if v in pair:
            assert v == (pair[0] if (yy % (2 * T)) < T else pair[1]), (g, yy)
    base, _ = _run_grip(emu_orig, g, sprite, x, y)
    for yy in range(ROWS):                                   # outside the rect: the trough (0xC5 / 0x41) is untouched
        for xx in range(STRIDE):
            if not (rx <= xx < rx + rw and ry <= yy < ry + rh):
                assert got[yy * STRIDE + xx] == base[yy * STRIDE + xx], (xx, yy)
            elif base[yy * STRIDE + xx] not in pair:
                assert got[yy * STRIDE + xx] == base[yy * STRIDE + xx], "borders are not pair members"


def test_grip_top_is_the_even_native_row_member(emu):
    assert M.sb_grip_pair(_grip(10, 10, (0xC5, 0xC2))) == (0xC2, 0xC5)       # row 1 = C5 -> even rows C2
    assert M.sb_grip_pair(_grip(10, 12, (0xB9, 0xF0))) == (0xF0, 0xB9)
    assert M.sb_grip_pair(_solid_grip()) is None


@pytest.mark.parametrize("g", (22, 40))
def test_grip_without_a_dither_is_left_alone(emu, emu_orig, g):
    want, pair, _rect = _grip_expected(emu_orig, g, _solid_grip(), 9, 47)
    got, _sp = _run_grip(emu, g, _solid_grip(), 9, 47)
    assert pair is None and got == want


@pytest.mark.parametrize("g", (22, 25, 40))
def test_grip_with_draw_offsets_and_row_padding(emu, emu_orig, g):
    sprite = _grip(10, 10)
    want, pair, rect = _grip_expected(emu_orig, g, sprite, 12, 50, lo=2, to=3, pad=6)
    got, _sp = _run_grip(emu, g, sprite, 12, 50, lo=2, to=3, pad=6)
    assert pair and rect and got == want


@pytest.mark.parametrize("name,x,y", [("past_the_bottom", 9, 119), ("above_the_top", 9, 1), ("left_of_the_canvas", 0, 47)])
def test_grip_rect_leaving_the_buffer_drops_the_restripe(emu, emu_orig, name, x, y):
    g = 40
    sprite = _grip(10, 10)
    base, _ = _run_grip(emu_orig, g, sprite, x, y)
    got, _sp = _run_grip(emu, g, sprite, x, y)
    adj = (x - ((10 * (g - 16)) >> 5), y - ((10 * (g - 16)) >> 5))
    assert M.sb_grip_rect(*adj, g, w=10, h=10, buf_h=120) is None
    assert got == base, name


@pytest.mark.parametrize("g,netwin", [(16, 1), (16, 0), (25, 0), (40, 0)])
def test_grip_native_and_unarmed_bars_reach_the_engine_blit(emu, g, netwin):
    """g <= 16 or no netwin bracket: thunk_sb_thumb's own native branch -> Sprite_draw_2 with the site's frame;
    t_sbt_grip is never entered."""
    sprite = _grip(10, 10)
    got, sp = _run_grip(emu, g, sprite, 9, 47, netwin=netwin)
    assert [c["kind"] for c in emu.calls] == ["sd2"]
    c = emu.calls[0]
    assert c["esp"] == sp and c["ret"] == MARKER and c["ecx"] == SPR and c["args"] == [BUF, KEY9, 9, 47, 1, 1]
    assert got == bytes(_trough_plane(24, 120))


# ==== layout, templates, hooks ====================================================================================
def test_layout_and_templates():
    syms = M.load_syms()
    layout = M.assemble_all(syms)
    assert tuple(layout) == M.THUNK_ORDER
    for name, (off, b) in layout.items():
        assert M.SLOTS[name][0] == off and off + len(b) <= M.SLOTS[name][1], name
    assert M.roundtrip_problems(layout, syms) == []
    assert layout["t_sbt_zoom"][1][-3:] == bytes([0xC2, 0x2C, 0x00]) and layout["t_sbt_grip"][1][-3:] == bytes([0xC2, 0x18, 0x00])


def test_slots_do_not_overlap_any_live_cave_entry_or_symbol():
    """Checked against patches.yaml AS IT IS NOW (other modules bake into the same cave)."""
    assert M.slot_problems(M.assemble_all()) == []


def test_retarget_tokens_exist_once_in_the_live_entries():
    assert M.retarget_problems() == [] or all("already retargeted" in p for p in M.retarget_problems())
    caves, symtab = _load()
    va, live = _live(caves, symtab, "thunk_btn_bandstripe", retarget=False)
    if b"\xE8" + ((symtab["thunk_keyed_stretch_blit"] - (va + M.BAND_KSB_CALL_OFF + 5)) & 0xFFFFFFFF).to_bytes(4, "little") \
            == live[M.BAND_KSB_CALL_OFF: M.BAND_KSB_CALL_OFF + 5]:
        tgt = (symtab["thunk_arrow_coverage"] - (va + M.BAND_ARROW_CALL_OFF + 5)) & 0xFFFFFFFF
        assert live[M.BAND_ARROW_CALL_OFF: M.BAND_ARROW_CALL_OFF + 5] == b"\xE8" + tgt.to_bytes(4, "little")


def test_grip_site_matches_the_pristine_base():
    import config
    if not config.terranx_bak(required=False).exists():
        pytest.skip("pristine .bak absent")
    assert M.verify_live() == []


def test_laws_agree_with_scaling_laws():
    """The module's laws use only scaling_laws primitives; pin the two facts the asm bakes in."""
    for g in range(17, 41):
        p = SL.stripe_period(g)
        for j in range(64):
            assert SL.stripe_top(j, g) == (2 * (j % p) < p), "the thunk's 2*(j mod P) >= P test is stripe_top"
    assert M.btn_zoom_owned(M.BTN_MENU, True) and not M.btn_zoom_owned(M.BTN_MENU, False)
    assert M.btn_zoom_owned(M.SE_LO) and not M.btn_zoom_owned(M.SE_HI) and M.btn_zoom_owned(M.BTN_ARROW_LAST)


# ==== 2026-10-15: the owned faces on their PARENT's grid (t_sbt_ph, law btn_zoom_stripe_phase) =====================
# Real MainWin-local tops of the arrow rects (DW slot-strip arrows = the HUD unit-row arrows, MainWin-parented):
# hud_unit_arrow_rects with anchors fl(192 g/16) / fl(248 g/16) -> 274 / 311 / 497 at g 22 / 25 / 40; the shots
# 20261014-231506 / -231218 / -230811 imply exactly these canvas tops (see the law's doc).
ARROW_TOPS = {22: 274, 25: 311, 40: 497}


def test_arrow_tops_are_the_hud_arrow_law():
    for g, top in ARROW_TOPS.items():
        s = lambda k: SL.popup_scale_floor(k, g)  # noqa: E731
        assert SL.hud_unit_arrow_rects((s(779), s(192), s(1020), s(248)), s(900), 12, 42, g)["btn10"][1] == top


PH_CASES = [
    ("dw_slot_arrow_right", M.DW_LO + 0x18 * M.BTN_STRIDE, lambda sw, sh: _crop(_unit_arrow(), sw, sh), (12, 42)),
    ("dw_slot_arrow_left", M.DW_LO + 0x17 * M.BTN_STRIDE, lambda sw, sh: _crop(_unit_arrow(pair=(0xA2, 0xEF)), sw, sh),
     (12, 42)),
    ("hud_unit_arrow", M.BTN_ARROW_LAST, lambda sw, sh: _crop(_unit_arrow(), sw, sh), (12, 42)),
    ("se_face", M.SE_LO + 3 * M.BTN_STRIDE, lambda sw, sh: _arrow_face(sw, sh), (20, 20)),
]


@pytest.mark.parametrize("g", sorted(ARROW_TOPS))
@pytest.mark.parametrize("name,esi,art,nat", PH_CASES, ids=[c[0] for c in PH_CASES])
@pytest.mark.parametrize("split", ["rect1", "rect2"])
def test_owned_faces_take_their_parent_local_phase(emu, g, name, esi, art, nat, split):
    top = ARROW_TOPS[g]
    tops = (top, 0) if split == "rect1" else (0, top)
    ph = SL.btn_zoom_stripe_phase(tops[0], tops[1], g, band_match=False)
    assert ph != 0, "every fixture top here is a non-zero phase (the case the bytes before 10-15 got wrong)"
    sw, sh, dw, dh = _dims(*nat, g)
    native = art(sw, sh)
    got = _run_band(emu, g, esi, native, dw, dh, tops=tops)
    assert emu.calls == []
    assert got == _expected(native, dw, dh, g, phase=ph), f"{name} g={g}"
    assert got != _expected(native, dw, dh, g, phase=0)


@pytest.mark.parametrize("g", (22, 40))
def test_negative_top_takes_the_floor_modulus(emu, g):
    esi, top = M.BTN_ARROW_FIRST, -3
    sw, sh, dw, dh = _dims(12, 42, g)
    native = _crop(_unit_arrow(), sw, sh)
    got = _run_band(emu, g, esi, native, dw, dh, tops=(top, 0))
    assert got == _expected(native, dw, dh, g, phase=top % SL.stripe_period(g))


def test_band_classes_keep_phase_zero():
    assert SL.btn_zoom_stripe_phase(311, 0, 25, band_match=True) == 0
    assert SL.btn_zoom_stripe_phase(311, 0, 25, band_match=False) == 3


def test_yaml_is_the_assembler_output():
    """Baked 2026-10-14 (audit): every thunk this module owns sits in patches.yaml at its slot, byte-identical to
    assemble_all() -- the emulator cases above run the ASSEMBLER's bytes, so this pins them to what ships."""
    import assemble_stripes_btn as AB
    _s, _g, caves, syms = ap.load_patches(ROOT / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    cs = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    for name, (off, built) in AB.assemble_all().items():
        assert int(cs[name]["offset"]) == off and symtab[name] == AB.PCAVE2 + off, name
        assert ap.ByteTemplate(cs[name]["bytes"]).resolve(AB.PCAVE2 + off, symtab) == built, name
