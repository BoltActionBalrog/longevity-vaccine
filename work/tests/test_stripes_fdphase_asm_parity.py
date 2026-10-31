"""Load / Save file list on the dialog's stripe grid: Unicorn parity for scripts/assemble_stripes_fdphase.py.

The two replacement thunks run against the ENGINE's own Buffer_tile bytes (0x5DA860, read from the pristine
base): only its three callees are stubbed (IntersectRect, Buffer_set_clip, Buffer_copy_4), so the modulo that
turns "list top" into a stripe phase is the engine's `idiv tileH`, not a model of it.

Stripe law (scaling_laws.stripe_top): parent-canvas row y carries the top member iff (y mod P) < T.  A list
whose canvas starts at parent row `top` must therefore show the top member on its row r iff
stripe_top(top + r).

The Win rect fields are written the way Win_init 0x5EBD80 writes them (see win_rects):
  client-area window (the list with its vertical bar, flags 0x80028):  rRect1.top = 0,   rRect2.top = top
  plain window (no client area):                                        rRect1.top = top, rRect2.top = 0
The thunks shipped on 2026-10-04 read rRect1.top alone; the last test pins that they reproduce the bands the
user measured on scanlines_after5 (main menu one row out at four resolutions, in-game two rows out at 1600x1200).
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
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402
import assemble_stripes_fdphase as FP  # noqa: E402

SCALED = tuple(range(17, 41))
PCAVE2, CAVE_LEN = FP.PCAVE2, 0x31000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect)
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
WIN = DATA + 0x2000                       # the list GraphicWin
CANVAS = WIN + FP.CANVAS
PARENT_CANVAS = DATA + 0x5000             # Buffer_copy_4's `this` at the capture sites (unused when scaled)
NAVY_TILE, SEL_TILE = DATA + 0x8000, DATA + 0x9000          # thunk_ensure_stripes' two scratch tiles (Buffers)
NATIVE_UNSEL, NATIVE_SEL = DATA + 0xA000, DATA + 0xB000     # the engine's 24x24 row tiles
F_CLIP, F_DATA, F_W, F_H = 0x20, 0x54, 0x80, 0x84
BUFFER_TILE_LEN = 0x18C                   # 0x5DA860..0x5DA9EC
BUFFER_SET_CLIP = 0x005D8000
IAT_INTERSECTRECT = 0x00669338            # Buffer_tile: call dword ptr [0x669338]
IR_STUB = 0x005D8100
REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9, UC_X86_REG_EAX: 0x0EA0EA0E, UC_X86_REG_EDX: 0x0ED0ED0E}
PAIRS = {NAVY_TILE: (0xC4, 0x41), SEL_TILE: (0xE0, 0xE1)}
UNDRAWN = 0x09


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def win_rects(top: int, client_area: bool) -> tuple[int, int]:
    """(rRect1.top, rRect2.top) as Win_init 0x5EBD80 leaves them for a window created at parent row `top`
    with no chrome above its client area (0x5EC14C..0x5EC1C2; plain windows skip the block at 0x5EC170)."""
    return (0, top) if client_area else (top, 0)


class Emu:
    """thunk -> real Buffer_tile -> stubbed Buffer_copy_4 painting a one-column model of the dest canvas."""

    def __init__(self, thunks: dict[str, tuple[int, bytes]]):
        s = self.syms = FP.load_syms()
        self.thunks = thunks
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        for page in sorted({s["g_popup_scale_num"] & ~0xFFF, s["Buffer_tile"] & ~0xFFF, s["Buffer_copy_4"] & ~0xFFF,
                            BUFFER_SET_CLIP & ~0xFFF, IAT_INTERSECTRECT & ~0xFFF,
                            s["g_filedlg_rowtile_sel"] & ~0xFFF, MARKER & ~0xFFF}):
            mu.mem_map(page, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        for _name, (off, b) in thunks.items():
            mu.mem_write(PCAVE2 + off, b)
        tile = SE.base_exe_bytes(s["Buffer_tile"], BUFFER_TILE_LEN)
        assert tile[:3] == b"\x83\xEC\x24" and tile[-3:] == b"\xC2\x1C\x00", "Buffer_tile is not where it was"
        mu.mem_write(s["Buffer_tile"], tile)
        mu.mem_write(s["thunk_ensure_stripes"], b"\xC3")
        mu.mem_write(s["Buffer_copy_4"], b"\xC2\x1C\x00")
        mu.mem_write(BUFFER_SET_CLIP, b"\xC2\x04\x00")
        mu.mem_write(IR_STUB, b"\xC2\x0C\x00")
        _w32(mu, IAT_INTERSECTRECT, IR_STUB)
        self.calls = []
        self.column: list[int] = []
        self.tile_h = 4
        for name, va in (("thunk_ensure_stripes", s["thunk_ensure_stripes"]), ("Buffer_tile", s["Buffer_tile"]),
                         ("Buffer_copy_4", s["Buffer_copy_4"]), ("Buffer_set_clip", BUFFER_SET_CLIP),
                         ("IntersectRect", IR_STUB)):
            mu.hook_add(UC_HOOK_CODE, self._hook, user_data=name, begin=va, end=va)

    def _rect(self, p):
        return [_s32(_r32(self.mu, p + 4 * i)) for i in range(4)]

    def _hook(self, mu, address, size, name):
        esp = mu.reg_read(UC_X86_REG_ESP)
        ecx = mu.reg_read(UC_X86_REG_ECX)
        args = [_r32(mu, esp + 4 + 4 * i) for i in range(7)]
        if name in ("thunk_ensure_stripes", "Buffer_tile") or (name == "Buffer_copy_4" and ecx not in PAIRS):
            self.calls.append({"fn": name, "esp": esp, "ret": _r32(mu, esp), "ecx": ecx, "args": args})
        if name == "thunk_ensure_stripes":            # contract: preserves ebx/esi/edi, clobbers eax/ecx/edx
            for r, v in ((UC_X86_REG_EAX, 0xE1E1E1E1), (UC_X86_REG_ECX, 0xC1C1C1C1), (UC_X86_REG_EDX, 0xD1D1D1D2)):
                mu.reg_write(r, v)
        elif name == "IntersectRect":                 # BOOL IntersectRect(out, a, b), stdcall
            a, b = self._rect(args[1]), self._rect(args[2])
            r = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
            ok = r[0] < r[2] and r[1] < r[3]
            for i in range(4):
                _w32(mu, args[0] + 4 * i, r[i] if ok else 0)
            mu.reg_write(UC_X86_REG_EAX, 1 if ok else 0)
        elif name == "Buffer_set_clip":               # thiscall(buffer, RECT*): the clip lives at +0x20
            mu.mem_write(ecx + F_CLIP, bytes(mu.mem_read(args[0], 16)))
        elif name == "Buffer_copy_4":                 # thiscall(src; dst, sx, sy, dx, dy, w, h), 1:1, dest-clipped
            if ecx in PAIRS:
                dst, sx, sy, dx, dy, w, h = (_s32(a) for a in args)
                assert dst & 0xFFFFFFFF == CANVAS and (sx, sy) == (0, 0)
                assert h == self.tile_h, "Buffer_tile steps by the tile's own height"
                clip = self._rect(CANVAS + F_CLIP)
                T = self.tile_h // 2
                if dx < clip[2] and dx + w > clip[0]:
                    for row in range(max(dy, clip[1]), min(dy + h, clip[3])):
                        self.column[row] = PAIRS[ecx][0] if (row - dy) < T else PAIRS[ecx][1]
            mu.reg_write(UC_X86_REG_EAX, 0)

    def setup(self, g, active, top, client_area, list_w, list_h, period=None):
        mu, s = self.mu, self.syms
        P = period or SL.stripe_period(g)
        self.tile_h = P
        _w32(mu, s["g_popup_scale_num"], g)
        _w32(mu, s["g_stripe_period"], P)
        _w32(mu, s["g_filedlg_active"], active)
        _w32(mu, s["g_stripe_navy"], NAVY_TILE)
        _w32(mu, s["g_stripe_sel"], SEL_TILE)
        _w32(mu, s["g_filedlg_rowtile_sel"], NATIVE_SEL)
        for t in (NAVY_TILE, SEL_TILE):                # thunk_ensure_stripes: Buffer_resize(0x800, P)
            _w32(mu, t + F_W, 0x800)
            _w32(mu, t + F_H, -P)
        mu.mem_write(WIN, b"\x00" * 0x1000)
        r1, r2 = win_rects(top, client_area)
        _w32(mu, WIN + FP.RRECT1_TOP, r1)
        _w32(mu, WIN + FP.RRECT2_TOP, r2)
        _w32(mu, CANVAS + F_DATA, DATA + 0x20000)
        _w32(mu, CANVAS + F_W, list_w)
        _w32(mu, CANVAS + F_H, -list_h)
        for i, v in enumerate((0, 0, list_w, list_h)):
            _w32(mu, CANVAS + F_CLIP + 4 * i, v)
        self.column = [UNDRAWN] * list_h

    def run(self, which, ecx, args):
        mu = self.mu
        self.calls.clear()
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, MARKER)
        for i, a in enumerate(args):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, ecx)
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.emu_start(PCAVE2 + self.thunks[which][0], MARKER, count=2_000_000)
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x1C, "stack imbalance (RET 0x1C contract)"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == REGS[r]
        assert bytes(mu.mem_read(sp + 0x20, 0x100)) == b"\xA5" * 0x100, "caller frame written"
        assert self._rect(CANVAS + F_CLIP)[:2] == [0, 0], "Buffer_tile restores the canvas clip"
        return list(self.calls), sp

    def paint_list(self, g, top, list_w, list_h, rows=True, selected_row=1):
        """The list as the engine paints it: the backdrop capture, then one Buffer_tile per row."""
        self.run("thunk_copy4_stripes", PARENT_CANVAS, [CANVAS, 14, top, 0, 0, list_w, list_h])
        tops = {}
        if rows:
            pitch = SL.popup_scale_floor(22, g)
            k = 0
            while (k + 1) * pitch <= list_h:
                y = k * pitch
                sel = k == selected_row
                self.run("thunk_filedlg_rowbg_v6", CANVAS,
                         [NATIVE_SEL if sel else NATIVE_UNSEL, 0, y, 0, y, list_w, pitch])
                for r in range(y, y + pitch):
                    tops[r] = 0xE0 if sel else 0xC4
                k += 1
        return tops


def _new_thunks():
    return {name: (off, b) for name, (off, b, _limit) in FP.assemble_all().items()}


def _shipped_thunks():
    """The two thunks as patches.yaml has them today (2026-10-04 build), resolved by the patcher's ByteTemplate."""
    s = FP.load_syms()
    out = {}
    for name, off, _limit, _fn in FP.THUNKS:
        tpl = FP.shipped_templates()[name]
        out[name] = (off, bytes(ap.ByteTemplate(tpl).resolve(PCAVE2 + off, dict(s))))
    return out


def _need_base():
    try:
        SE.base_exe_bytes(0x005DA860, 4)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"pristine base exe unavailable: {e}")


@pytest.fixture(scope="module")
def emu():
    _need_base()
    return Emu(_new_thunks())


@pytest.fixture(scope="module")
def shipped():
    _need_base()
    return Emu(_shipped_thunks())


# FileDlg_layout list rects, window-local native (top, bottom): in-game {28,32,333,320}, main menu {14,42,319,330}
FILEDLG_LISTS = {"in_game": (32, 320), "main_menu": (42, 330)}
LIST_W = 64


def _geom(which, g):
    t, b = (SL.popup_scale_floor(v, g) for v in FILEDLG_LISTS[which])
    return t, b - t


def _law(top, r, g, member, period=None):
    P = period or SL.stripe_period(g)
    mate = {0xC4: 0x41, 0xE0: 0xE1}[member]
    return member if ((top + r) % P) < P // 2 else mate


def _composite(column, top, g, margin=24):
    """Parent column through ring / list / ring; the ring is on the parent grid (thunk_fe_pair_remap)."""
    out = []
    for py in range(top - margin, top + len(column) + margin):
        if top <= py < top + len(column):
            out.append((py, column[py - top]))
        else:
            out.append((py, 0xC4 if SL.stripe_top(py, g) else 0x41))
    return out


def _runs(col):
    """[(index, first parent row, last parent row)]"""
    out = []
    for py, v in col:
        if out and out[-1][0] == v and out[-1][2] == py - 1:
            out[-1][2] = py
        else:
            out.append([v, py, py])
    return [tuple(r) for r in out]


@pytest.mark.parametrize("g", SCALED)
@pytest.mark.parametrize("which", list(FILEDLG_LISTS))
@pytest.mark.parametrize("client_area", [True, False])
def test_backdrop_and_rows_sit_on_the_parent_grid(emu, g, which, client_area):
    top, h = _geom(which, g)
    emu.setup(g, 1, top, client_area, LIST_W, h)
    row_tops = emu.paint_list(g, top, LIST_W, h)
    for r, v in enumerate(emu.column):
        assert v == _law(top, r, g, row_tops.get(r, 0xC4)), (g, which, r)


@pytest.mark.parametrize("g", SCALED)
@pytest.mark.parametrize("which", list(FILEDLG_LISTS))
def test_no_band_where_the_list_meets_the_frame(emu, g, which):
    top, h = _geom(which, g)
    emu.setup(g, 1, top, True, LIST_W, h)
    emu.paint_list(g, top, LIST_W, h, selected_row=-1)
    runs = _runs(_composite(emu.column, top, g))[1:-1]
    assert {b - a + 1 for _v, a, b in runs} == {SL.stripe_rows(g)}, (g, which)


@pytest.mark.parametrize("top", list(range(0, 14)) + [50, 57, 65, 105, 1001])
@pytest.mark.parametrize("period", [2, 4, 6, 8])
@pytest.mark.parametrize("client_area", [True, False])
def test_any_top_any_period(emu, top, period, client_area):
    """The offset is reduced by Buffer_tile's own `idiv tileH`: right for every period, 6 included."""
    h = 61
    emu.setup(25, 1, top, client_area, LIST_W, h, period=period)
    emu.run("thunk_copy4_stripes", PARENT_CANVAS, [CANVAS, 14, top, 0, 0, LIST_W, h])
    assert emu.column == [_law(top, r, 25, 0xC4, period) for r in range(h)]
    y, rh = 17, 23
    emu.run("thunk_filedlg_rowbg_v6", CANVAS, [NATIVE_SEL, 3, y, 3, y, LIST_W - 3, rh])
    for r in range(h):
        assert emu.column[r] == _law(top, r, 25, 0xE0 if y <= r < y + rh else 0xC4, period)


@pytest.mark.parametrize("g", SCALED)
def test_rowbg_tail_jumps_into_buffer_tile_with_the_swapped_tile(emu, g):
    top, h = _geom("in_game", g)
    emu.setup(g, 1, top, True, LIST_W, h)
    for native, want in ((NATIVE_UNSEL, NAVY_TILE), (NATIVE_SEL, SEL_TILE)):
        calls, sp = emu.run("thunk_filedlg_rowbg_v6", CANVAS, [native, 5, 46, 5, 46, 300, 23])
        assert [c["fn"] for c in calls] == ["thunk_ensure_stripes", "Buffer_tile"]
        c = calls[1]
        assert c["ecx"] == CANVAS and c["esp"] == sp and c["ret"] == MARKER
        assert c["args"] == [want, 5, 46 + top, 5, 46, 300, 23]


@pytest.mark.parametrize("which,native,ecx,args", [
    ("thunk_filedlg_rowbg_v6", "Buffer_copy_4", CANVAS, [NATIVE_UNSEL, 0, 37, 0, 37, 300, 23]),
    ("thunk_copy4_stripes", "Buffer_copy_4", PARENT_CANVAS, [CANVAS, 28, 50, 0, 0, 476, 450]),
])
@pytest.mark.parametrize("g,active", [(16, 1), (12, 1), (25, 0), (40, 0), (16, 0)])
def test_native_paths_are_untouched(emu, which, native, ecx, args, g, active):
    emu.setup(g, active, 50, True, LIST_W, 450)
    for t in (NATIVE_UNSEL, NATIVE_SEL):
        _w32(emu.mu, t + F_W, 24)
        _w32(emu.mu, t + F_H, -24)
    calls, sp = emu.run(which, ecx, args)
    assert "thunk_ensure_stripes" not in [c["fn"] for c in calls]
    c = calls[0]
    assert c["esp"] == sp and c["ret"] == MARKER and c["ecx"] == ecx and c["args"] == args
    assert c["fn"] == ("Buffer_tile" if which == "thunk_filedlg_rowbg_v6" else "Buffer_copy_4")
    assert emu.column == [UNDRAWN] * 450, "no stripe tile reaches the canvas"


@pytest.mark.parametrize("g", (18, 22, 25, 40))
def test_copy4_null_dest_draws_nothing(emu, g):
    """The engine passes dst = 0 when its window pointer is null (0x60BB88 / 0x60C3EF)."""
    emu.setup(g, 1, 50, True, LIST_W, 100)
    calls, _sp = emu.run("thunk_copy4_stripes", PARENT_CANVAS, [0, 28, 50, 0, 0, 476, 450])
    assert [c["fn"] for c in calls] == ["thunk_ensure_stripes"]


def test_gate_and_native_tail_bytes_are_the_shipped_ones():
    new, old = FP.templates(), FP.shipped_templates()
    for name, (off, tpl, n, limit) in new.items():
        assert off + n <= limit, name
        assert tpl.startswith(FP.GATE_PREFIX) and old[name].startswith(FP.GATE_PREFIX)
        assert tpl.split(" C3 ")[0] == old[name].split(" C3 ")[0], name   # gate + `push native / ret`
    assert (new["thunk_filedlg_rowbg_v6"][2], new["thunk_copy4_stripes"][2]) == (75, 79)
    # the whole edit, as text
    assert new["thunk_filedlg_rowbg_v6"][1] == old["thunk_filedlg_rowbg_v6"].replace(
        "83 E0 03", "03 81 0C FD FF FF").replace("EB CA", "EB C7")
    assert new["thunk_copy4_stripes"][1] == old["thunk_copy4_stripes"].replace(
        "83 E0 03", "03 81 0C FD FF FF").replace("74 24 8B 81", "74 27 8B 81")


def test_fragment_matches_the_assembler():
    frag = (ROOT / "patches" / "_fragment_stripes_fdphase_cave.yaml").read_text(encoding="utf-8")
    assert frag == FP.cave_yaml()


# ---- the measured defect ------------------------------------------------------------------------------------------
# scanlines_after5, the 2026-10-04 build.  (which, g) -> seam runs as (index, first, last) in PARENT-canvas rows.
# Screen row = window top + parent row; window tops: main menu (SH - floor(393g/16)) >> 1 = 270 / 589 / 293 / 229,
# in-game 1600x1200 = 242.
MEASURED = {
    ("main_menu", 22): [(0xC4, 56, 58), (0xC4, 453, 453)],       # 1920x1080 ...001822: C4x3 y326..328, C4x1 y723
    ("main_menu", 40): [(0xC4, 104, 106), (0xC4, 825, 825)],     # 3840x2160 ...001324: C4x3 y693..695, C4x1 y1414
    ("main_menu", 25): [(0xC4, 64, 66), (0x41, 515, 515)],       # 1600x1200 ...001604: C4x3 y357..359, 00x1 y808
    ("main_menu", 18): [(0xC4, 46, 47), (0x41, 370, 371)],       # 1600x900  ...002025: C4x2 y275..276, 00x2 y599..600
    ("in_game", 25): [(0xC4, 48, 51), (0xC4, 498, 501)],         # 1600x1200 ...001556: C4x4 y290..293, y740..743
    ("in_game", 22): [],                                         # 1920x1080 ...001815: clean
    ("in_game", 40): [],                                         # 3840x2160 ...001313: clean
    ("in_game", 18): [],                                         # 1600x900  ...002017: clean
}


@pytest.mark.parametrize("which,g", list(MEASURED))
def test_new_thunks_clear_every_measured_case(emu, which, g):
    top, h = _geom(which, g)
    emu.setup(g, 1, top, True, LIST_W, h)
    emu.paint_list(g, top, LIST_W, h, selected_row=-1)
    T = SL.stripe_rows(g)
    assert [r for r in _runs(_composite(emu.column, top, g))[1:-1] if r[2] - r[1] + 1 != T] == []
