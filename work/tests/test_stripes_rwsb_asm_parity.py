"""Differential: the HQ energy report's own list scrollbar (scripts/assemble_stripes_rwsb.py) under Unicorn.

The emulator holds EVERY pcave2 contents entry of patches.yaml, resolved by the patcher's own ByteTemplate,
so the bracket thunks run against the real thunk_list_gate / thunk_lbres_ecx and the two edited thunks run
against the real thunk_sb_restripe, thunk_fe_pair_remap, thunk_btn_stripes, thunk_sbarrow_bg, thunk_ed_remap.

  cause    the LIVE thunk_pref_sbzoom / t_rw_sbarrows / thunk_btn_stripes leave the bar's canvases native;
  bracket  t_rwsb_begin .. t_rwsb_end: g_scrollbar_w == scaling_laws.listbox_bar_reserve inside, the live
           value outside; one scale step in every gate combination; stack + registers on every path;
  edits    thunk_pref_sbzoom v10 / t_rw_sbarrows v3 (assembled in memory from the modified text): the bar
           canvas == scaling_laws.pair_remap_pixel (F0/B9 one-shot + keyed trough), the arrow canvas ==
           scaling_laws.sbarrow_bg_pixel + stripe_color_sb, on the canvas's own rows; g = 16 untouched;
           nothing outside the canvas written; every other admission identical to the live bytes.
  applied  the live yaml entries equal the proposed templates -- SKIPPED with a message until the edits land.

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
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_stripes_rwsb as RB  # noqa: E402

G_SWEEP = (16, 18, 21, 22, 25, 32, 40)

PCAVE2, CAVE_LEN = RB.PCAVE2, 0x40000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect)
G_VA, PERIOD_VA, SBW_VA = RB.G, 0x0066879C, RB.G_SBW
SB_DRAW = 0x006066F0
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
VT = DATA + 0x100                         # a fake vtable: [VT+4] -> SHOW
SHOW = DATA + 0x200                       # the list window's show virtual (thiscall, 1 arg, RET 4)
BAR = DATA + 0x1000                       # the heap ScrollBar (0x214C B); arrows at +0xAAC / +0x15F8
BAR2 = DATA + 0x4000                      # some other heap ScrollBar
PARENT = DATA + 0x7000
PLANE = DATA + 0x10000
PLANE_LEN = 0x8000
F_CLIP, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0x4A8
F_PARENT = 0xC4

REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9, UC_X86_REG_EAX: 0x0EA0EA0E, UC_X86_REG_EDX: 0x0ED0ED0E,
        UC_X86_REG_ECX: 0x0EC0EC0E}
SAVED = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
STUB_EAX = 0x00C0FFEE
STROKE, KEY = 0x22, 0x09


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


class Emu:
    """edited=False: the cave exactly as patches.yaml has it (+ the two new thunks).  edited=True: the same with
    thunk_pref_sbzoom v10 and t_rw_sbarrows v3 written over their slots."""

    def __init__(self, edited: bool):
        _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
        self.s2v = dict(ap.build_symbol_table(symbols, caves))
        self.syms = RB.load_syms()
        self.layout, self.cell_off = RB.assemble_all(self.syms)
        self.va = RB.names_of(self.layout, self.cell_off)
        self.cell = self.va[RB.CELL_NAME]
        self.edits = {e["name"]: e for e in RB.edits(self.syms)}
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)
        mu.mem_map(0x009B7000, 0x2000)                       # g_modal_top, g_scrollbar_w
        mu.mem_map(0x00876000, 0x10000)                      # ReportWin statics (the scroll_vert field)
        mu.mem_map(SB_DRAW & ~0xFFF, 0x1000)
        mu.mem_map(RB.DIALOG_INIT_3 & ~0xFFF, 0x1000)
        mu.mem_map(RB.END_RESUME & ~0xFFF, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        cave = next(c for c in caves if c["id"] == "pcave2")
        self.unresolved = []
        for e in cave.get("contents") or []:
            try:
                b = ap.ByteTemplate(str(e["bytes"])).resolve(PCAVE2 + int(e["offset"]), self.s2v)
            except Exception as exc:  # noqa: BLE001  (an entry the patcher itself rejects is not ours to judge)
                self.unresolved.append((e.get("id"), repr(exc)))
                continue
            mu.mem_write(PCAVE2 + int(e["offset"]), bytes(b))
        self.cave_image = bytes(mu.mem_read(PCAVE2, CAVE_LEN))
        for name, (off, b) in self.layout.items():
            mu.mem_write(PCAVE2 + off, b)
        if edited:
            for e in self.edits.values():
                mu.mem_write(PCAVE2 + e["off"], e["new_bytes"])
        mu.mem_write(RB.DIALOG_INIT_3, b"\xC2\x08\x00")       # ret 8
        mu.mem_write(SHOW, b"\xC2\x04\x00")                   # ret 4
        mu.mem_write(SB_DRAW, b"\xC3")                        # thiscall, no args
        _w32(mu, VT + 4, SHOW)
        self.calls, self.errors, self.painter = [], [], None
        mu.hook_add(UC_HOOK_CODE, self._on_callee, begin=RB.DIALOG_INIT_3, end=RB.DIALOG_INIT_3, user_data="init3")
        mu.hook_add(UC_HOOK_CODE, self._on_callee, begin=SHOW, end=SHOW, user_data="show")
        mu.hook_add(UC_HOOK_CODE, self._on_callee, begin=SB_DRAW, end=SB_DRAW, user_data="sbdraw")

    def _on_callee(self, mu, address, size, kind):
        try:
            esp = mu.reg_read(UC_X86_REG_ESP)
            self.calls.append({
                "kind": kind, "esp": esp, "ret": _r32(mu, esp), "args": [_r32(mu, esp + 4), _r32(mu, esp + 8)],
                "regs": {r: mu.reg_read(r) for r in REGS}, "sbw": _r32(mu, SBW_VA), "cell": _r32(mu, self.cell),
                "netwin": _r32(mu, self.s2v["g_netwin_active"]), "sb_cur": _r32(mu, self.s2v["g_sb_cur"])})
            if kind == "sbdraw" and self.painter:
                self.painter()
            if kind != "init3":                               # a real callee may scribble on the volatile registers
                mu.reg_write(UC_X86_REG_ECX, 0xCCCC0001)
                mu.reg_write(UC_X86_REG_EDX, 0xDDDD0002)
            if kind != "sbdraw":
                mu.reg_write(UC_X86_REG_EAX, STUB_EAX)
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    # ---- state ----
    def reset(self, g, *, sbw=20, popup=0, filedlg=0, inlist=0, cell=0, modal=RB.RW, field=0):
        mu = self.mu
        _w32(mu, G_VA, g)
        _w32(mu, PERIOD_VA, SL.stripe_period(g))
        _w32(mu, SBW_VA, sbw)
        _w32(mu, self.s2v["g_popup_active"], popup)
        _w32(mu, self.s2v["g_filedlg_active"], filedlg)
        _w32(mu, self.s2v["g_rw_inlist"], inlist)
        _w32(mu, self.cell, cell)
        _w32(mu, RB.G_MODAL_TOP, modal)
        _w32(mu, RB.RW_ENERGY_VBAR, field)
        for n in ("g_netwin_active", "g_sb_cur", "g_rail_sb", "g_rm_force", "g_rm_f0ovr", "g_rm_povr", "g_faction_active",
                  "g_btn_fill_sprite", "g_dll_pref_slider"):
            _w32(mu, self.s2v[n], 0)
        for i in range(2):
            _w32(mu, self.s2v["g_rw_sbs"] + 4 * i, 0)
            _w32(mu, self.s2v["g_rw_sbparents"] + 4 * i, 0)
        self.calls.clear()
        self.errors.clear()
        self.painter = None

    def run(self, entry, *, stack=(), regs=None, until=MARKER, first=MARKER):
        """Enter `entry` as a CALL would: [esp] = `first`, then `stack`.  Returns (esp at entry, final regs)."""
        mu = self.mu
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, first)
        for i, a in enumerate(stack):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        want = dict(REGS)
        want.update(regs or {})
        for r, v in want.items():
            mu.reg_write(r, v)
        mu.emu_start(entry, until, count=20_000_000)
        assert not self.errors, self.errors
        assert mu.reg_read(UC_X86_REG_EIP) == until, "did not reach the caller's resume address"
        assert bytes(mu.mem_read(sp - 0x400, 0x400 - 0x100)) == b"\xA5" * (0x400 - 0x100), "stack use deeper than 0x100"
        assert bytes(mu.mem_read(sp + 4 + 4 * len(stack), 0x100)) == b"\xA5" * 0x100, "wrote above its own frame"
        return sp, want, {r: mu.reg_read(r) for r in REGS}

    def make_buffer(self, obj, w, h, stride, data=PLANE):
        mu = self.mu
        mu.mem_write(obj, b"\x00" * 0xB4C)
        b = obj + 0x444
        _w32(mu, b + F_DATA, data)
        _w32(mu, b + F_W, w)
        _w32(mu, b + F_H, -h)                                 # Buffer h is stored negative
        _w32(mu, b + F_STRIDE, stride)
        for i, v in enumerate((0, 0, w, h)):
            _w32(mu, b + F_CLIP + 4 * i, v)


@pytest.fixture(scope="module")
def live():
    return Emu(edited=False)


@pytest.fixture(scope="module")
def emu():
    return Emu(edited=True)


def _law_w(sbw, g):
    """The direct statement next to the module law: vanilla x g/16, floor, above native scale."""
    want = sbw if g <= 16 else (sbw * g) // 16
    assert RB.energy_list_bar_width(sbw, g) == want == SL.listbox_bar_reserve(sbw, g, popup_active=True)
    return want


# ---- (1) the bracket ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("sbw", [20, 12])
def test_begin_scales_the_writer_and_tail_jumps(emu, g, sbw):
    emu.reset(g, sbw=sbw)
    sp, want, got = emu.run(emu.va["t_rwsb_begin"], stack=(0x11112222, 0x33334444))
    assert emu.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 8, "Dialog_init_3 is RET 8"
    (c,) = emu.calls
    assert c["kind"] == "init3" and c["esp"] == sp and c["ret"] == MARKER, "the callee must see the SITE's frame"
    assert c["args"] == [0x11112222, 0x33334444] and c["regs"] == want, "args / registers disturbed"
    assert c["sbw"] == _law_w(sbw, g)
    assert c["cell"] == (sbw if g > 16 else 0)
    for r in SAVED:
        assert got[r] == want[r]
    assert got[UC_X86_REG_EAX] == STUB_EAX
    if g > 16 and g % 16:
        assert c["sbw"] > sbw


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("gate", ["popup", "filedlg", "inlist", "nested"])
def test_begin_leaves_gated_contexts_alone(emu, g, gate):
    """Under a popup / file-dialog gate the READERS scale; inside the console bracket the console WRITER holds
    s(12); an open bracket must not be re-entered.  In all four the global is not touched and no restore is armed."""
    kw = {"popup": {"popup": 2}, "filedlg": {"filedlg": 1}, "inlist": {"inlist": 1}, "nested": {"cell": 77}}[gate]
    emu.reset(g, **kw)
    sp, want, _ = emu.run(emu.va["t_rwsb_begin"], stack=(1, 2))
    (c,) = emu.calls
    assert c["esp"] == sp and c["ret"] == MARKER and c["regs"] == want
    assert c["sbw"] == 20 and c["cell"] == kw.get("cell", 0)


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("opened", [True, False])
def test_end_runs_the_show_then_restores(emu, g, opened):
    emu.reset(g)
    if opened:
        emu.run(emu.va["t_rwsb_begin"], stack=(1, 2))
        emu.calls.clear()
    before = _r32(emu.mu, SBW_VA)
    assert before == (_law_w(20, g) if opened else 20)
    sp, want, got = emu.run(emu.va["t_rwsb_end"], stack=(0x0000ABCD,), first=RB.END_RESUME, until=RB.END_RESUME,
                            regs={UC_X86_REG_EAX: VT, UC_X86_REG_ESI: BAR})
    (c,) = emu.calls
    assert c["kind"] == "show" and c["regs"][UC_X86_REG_ECX] == BAR, "mov ecx,esi"
    assert c["esp"] == sp and c["args"][0] == 0x0000ABCD, "the virtual must find vanilla's arg at [esp+4]"
    assert PCAVE2 <= c["ret"] < PCAVE2 + CAVE_LEN
    assert c["sbw"] == before, "the bracket must still be open while the list window shows"
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert c["regs"][r] == want[r] and got[r] == want[r]
    assert emu.mu.reg_read(UC_X86_REG_ESP) == sp + 8, "our return address + the callee-cleaned arg, nothing else"
    assert got[UC_X86_REG_EAX] == STUB_EAX, "eax must be the virtual's result"
    assert _r32(emu.mu, SBW_VA) == 20 and _r32(emu.mu, emu.cell) == 0


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("gate", ["plain", "popup", "filedlg"])
def test_readers_see_exactly_one_scale_step(emu, g, gate):
    """The real thunk_lbres_ecx (the g_scrollbar_w reader at calc_dims / GraphicWin_init / Win_create_scrollbars),
    called inside the bracket, returns the law in every gate combination -- never 20, never the square."""
    emu.reset(g, **({"popup": 1} if gate == "popup" else {"filedlg": 1} if gate == "filedlg" else {}))
    emu.run(emu.va["t_rwsb_begin"], stack=(1, 2))
    _sp, _want, got = emu.run(emu.s2v["thunk_lbres_ecx"])
    assert got[UC_X86_REG_ECX] == _law_w(20, g)
    emu.run(emu.va["t_rwsb_end"], stack=(0,), first=RB.END_RESUME, until=RB.END_RESUME,
            regs={UC_X86_REG_EAX: VT, UC_X86_REG_ESI: BAR})
    assert _r32(emu.mu, SBW_VA) == 20 and _r32(emu.mu, emu.cell) == 0


# ---- (2) the bar canvas: thunk_pref_sbzoom ------------------------------------------------------------------------
def _nn(j, dst, src):
    return min(src - 1, ((2 * j + 1) * src) // (2 * dst))


def _bar_canvas(g, trough):
    """What the armed ScrollBar_draw leaves in the bar's own canvas: a 1-px stroke frame, the trough, and the
    18-px grip NN-enlarged x g/16 with its native 1-row F0/B9 dither.  trough = 'black' (the energy list's bar)
    or 'c541' (a rail-style 1-row C5/41 trough, the keyed family)."""
    w = max(4, _law_w(20, g))
    h = 96
    stride = w + 9
    grip = max(2, (18 * g) // 16)
    plane = bytearray((0x41, 0xC5, 0xF0, 0xB9, 0xE0, 0xAE, 0x07)[(x * 5 + y * 3) % 7] for y in range(h + 4) for x in range(stride))
    for y in range(h):
        for x in range(w):
            if x in (0, w - 1) or y in (0, h - 1):
                v = STROKE
            elif trough == "c541":
                v = 0xC5 if y % 2 == 0 else 0x41
            else:
                v = 0x00
            if 30 <= y < 30 + grip and 1 <= x < w - 1:
                v = 0xF0 if _nn(y - 30, grip, 18) % 2 == 0 else 0xB9
            plane[y * stride + x] = v
    return w, h, stride, plane


def _bar_law(native, w, h, stride, g):
    out = bytearray(native)
    if g <= 16:
        return bytes(out)
    counts: dict[int, int] = {}
    for y in range(min(h, 8)):
        for x in range(w):
            counts[native[y * stride + x]] = counts.get(native[y * stride + x], 0) + 1
    top = SL.dither_force_mate(counts, w)
    for y in range(h):
        for x in range(w):
            out[y * stride + x] = SL.pair_remap_pixel(native[y * stride + x], y, g, navy=top == 0xC4, bd=top == 0xC6,
                                                      c5=top == 0xC5, bf=top == 0xBF, f0=True)
    return bytes(out)


def _draw_bar(e, g, trough, *, field=BAR, ecx=BAR, modal=RB.RW):
    w, h, stride, native = _bar_canvas(g, trough)
    e.reset(g, field=field, modal=modal)
    e.make_buffer(BAR, w, h, stride)
    e.make_buffer(BAR2, w, h, stride)
    e.mu.mem_write(PLANE, bytes(native) + b"\x5A" * (PLANE_LEN - len(native)))
    sp, want, got = e.run(e.s2v["thunk_pref_sbzoom"], regs={UC_X86_REG_ECX: ecx})
    assert e.mu.reg_read(UC_X86_REG_ESP) == sp + 4, "ScrollBar_draw takes no stack args"
    for r in SAVED:
        assert got[r] == want[r], "callee-saved register not preserved"
    (c,) = e.calls
    assert c["kind"] == "sbdraw" and c["regs"][UC_X86_REG_ECX] == ecx
    assert _r32(e.mu, e.s2v["g_netwin_active"]) == 0 and _r32(e.mu, e.s2v["g_rm_f0ovr"]) == 0
    assert _r32(e.mu, e.s2v["g_rm_force"]) == 0, "g_rm_force left set"
    plane = bytes(e.mu.mem_read(PLANE, PLANE_LEN))
    assert plane[len(native):] == b"\x5A" * (PLANE_LEN - len(native)), "wrote past the canvas"
    return c, sp, plane[:len(native)], bytes(native), (w, h, stride)


# The "cause" assertions describe the PRE-fix yaml; once the two edits are in patches.yaml they no longer hold.
_APPLIED = all(e["applied"] for e in RB.edits())


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("trough", ["black", "c541"])
def test_edited_sbzoom_restripes_the_bar_to_the_law(emu, g, trough):
    c, sp, got, native, (w, h, stride) = _draw_bar(emu, g, trough)
    assert c["netwin"] == 1 and c["sb_cur"] == BAR and c["ret"] != MARKER, "the armed (bracketed) draw"
    assert got == _bar_law(native, w, h, stride, g)
    if g <= 16:                                              # thunk_sb_restripe: bracket close only, like every admitted bar
        assert got == native, "g <= 16 must be a native no-op"
        return
    assert _r32(emu.mu, emu.s2v["g_sb_cur"]) == 0, "the stash must be consumed"
    T = SL.stripe_rows(g)                                    # direct statement of THE RULE on the grip
    seen = 0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if native[y * stride + x] in (0xF0, 0xB9):
                assert got[y * stride + x] == (0xF0 if (y % (2 * T)) < T else 0xB9), (g, x, y)
                seen += 1
            elif trough == "black":
                assert got[y * stride + x] == native[y * stride + x]
    assert seen > 0
    for y in range(h):                                        # strokes and the row gutter never move
        assert got[y * stride] == STROKE and got[y * stride + w - 1] == STROKE
        assert got[y * stride + w:(y + 1) * stride] == native[y * stride + w:(y + 1) * stride]


@pytest.mark.parametrize("g", (16, 22, 40))
@pytest.mark.parametrize("case", ["closed", "other_bar", "other_bar_not_modal"])
def test_edited_sbzoom_admits_only_the_field_s_own_bar(emu, g, case):
    """A closed list (field 0) admits nothing; another heap bar is not admitted because this one exists."""
    kw = {"closed": {"field": 0, "ecx": BAR}, "other_bar": {"field": BAR, "ecx": BAR2},
          "other_bar_not_modal": {"field": BAR, "ecx": BAR2, "modal": 0x12345678}}[case]
    c, sp, got, native, _ = _draw_bar(emu, g, "black", **kw)
    assert c["esp"] == sp and c["ret"] == MARKER and c["netwin"] == 0
    assert got == native


@pytest.mark.parametrize("g", (16, 25))
@pytest.mark.parametrize("who", ["rail", "slot0", "slot1", "slot0_stale_parent", "slot1_not_modal", "none"])
def test_edited_sbzoom_keeps_every_dynamic_admission(live, emu, g, who):
    """Same verdict, same canvas, live vs edited, for the dynamic admissions the edit sits next to."""
    out = []
    for e in (live, emu):
        w, h, stride, native = _bar_canvas(g, "c541")
        e.reset(g, field=0, modal=0x12345678 if who == "slot1_not_modal" else RB.RW)
        e.make_buffer(BAR, w, h, stride)
        e.mu.mem_write(PLANE, bytes(native))
        _w32(e.mu, BAR + F_PARENT, PARENT)
        if who == "rail":
            _w32(e.mu, e.s2v["g_rail_sb"], BAR)
        elif who.startswith("slot"):
            i = int(who[4])
            _w32(e.mu, e.s2v["g_rw_sbs"] + 4 * i, BAR)
            _w32(e.mu, e.s2v["g_rw_sbparents"] + 4 * i, PARENT + (4 if "stale" in who else 0))
        e.run(e.s2v["thunk_pref_sbzoom"], regs={UC_X86_REG_ECX: BAR})
        (c,) = e.calls
        out.append((c["netwin"], c["ret"] == MARKER, bytes(e.mu.mem_read(PLANE, len(native)))))
    assert out[0] == out[1]
    assert out[0][0] == (1 if who in ("rail", "slot0", "slot1") else 0)


# ---- (3) the arrows: t_rw_sbarrows + the real thunk_btn_stripes --------------------------------------------------
def _sbarrows(e, esi, **state):
    e.reset(22, **{k: v for k, v in state.items() if k in ("field", "modal")})
    e.mu.mem_write(BAR, b"\x00" * 0x2200)
    e.mu.mem_write(BAR2, b"\x00" * 0x2200)
    _w32(e.mu, BAR + F_PARENT, PARENT)
    _w32(e.mu, BAR2 + F_PARENT, PARENT + 0x40)
    for i, (bar, par) in enumerate(state.get("slots", ((0, 0), (0, 0)))):
        _w32(e.mu, e.s2v["g_rw_sbs"] + 4 * i, bar)
        _w32(e.mu, e.s2v["g_rw_sbparents"] + 4 * i, par)
    sp, want, got = e.run(e.s2v["t_rw_sbarrows"], regs={UC_X86_REG_ESI: esi})
    assert e.mu.reg_read(UC_X86_REG_ESP) == sp + 4, "stack imbalance"
    for r in SAVED + (UC_X86_REG_EDX, UC_X86_REG_ECX):
        assert got[r] == want[r], "t_rw_sbarrows may clobber eax only"
    assert got[UC_X86_REG_EAX] in (0, 1)
    return got[UC_X86_REG_EAX]


@pytest.mark.parametrize("modal", [RB.RW, 0x12345678])
def test_edited_sbarrows_admits_the_energy_bar_s_two_arrows(emu, live, modal):
    for off, want in ((RB.ARROW_UP, 1), (RB.ARROW_DN, 1), (0, 0), (RB.ARROW_UP + 4, 0), (RB.ARROW_DN + 0xB4C, 0), (0x444, 0)):
        assert _sbarrows(emu, BAR + off, field=BAR, modal=modal) == want, hex(off)
        if not _APPLIED:
            assert _sbarrows(live, BAR + off, field=BAR, modal=modal) == 0, "cause: the live helper refuses them"
    for off in (RB.ARROW_UP, RB.ARROW_DN):
        assert _sbarrows(emu, BAR2 + off, field=BAR, modal=modal) == 0, "another bar's arrow"
        assert _sbarrows(emu, BAR + off, field=0, modal=modal) == 0, "closed list: the null field admits nothing"
    # (esi == 0xAAC / 0x15F8 itself would match a null field; esi is always a live FlatButton `this`.)


@pytest.mark.parametrize("modal", [RB.RW, 0x12345678])
@pytest.mark.parametrize("slots", [((BAR, PARENT), (0, 0)), ((0, 0), (BAR, PARENT)), ((BAR, PARENT + 4), (0, 0)),
                                   ((BAR2, PARENT + 0x40), (BAR, PARENT)), ((0, 0), (0, 0))])
def test_edited_sbarrows_keeps_the_console_bar_verdicts(emu, live, modal, slots):
    for bar in (BAR, BAR2):
        for off in (RB.ARROW_UP, RB.ARROW_DN, 0, 0x15F8 + 0xB4C):
            a = _sbarrows(live, bar + off, field=0, modal=modal, slots=slots)
            assert _sbarrows(emu, bar + off, field=0, modal=modal, slots=slots) == a


def _arrow_canvas(g):
    """An arrow FlatButton's canvas after the 2D zoom: the 18x18 state sprite NN-enlarged to the button -- bevel
    column, C2/C5 1-row face background, F0/B9 1-row chevron."""
    side = max(6, _law_w(20, g) - 2)
    stride = side + 7
    plane = bytearray((0xC2, 0xC5, 0xF0, 0xB9, 0x41, 0x07)[(x * 5 + y) % 6] for y in range(side + 3) for x in range(stride))
    for y in range(side):
        sy = _nn(y, side, 18)
        for x in range(side):
            sx = _nn(x, side, 18)
            if sx == 0 or sy == 17:
                v = 0x29
            elif 5 <= sy <= 12 and abs(sx - 9) <= sy - 5:
                v = 0xF0 if sy % 2 == 0 else 0xB9
            else:
                v = 0xC2 if sy % 2 == 1 else 0xC5
            plane[y * stride + x] = v
    return side, stride, plane


def _stripe_arrow(e, g):
    side, stride, native = _arrow_canvas(g)
    e.reset(g, field=BAR)
    e.mu.mem_write(BAR, b"\x00" * 0x2200)
    arrow = BAR + RB.ARROW_DN
    e.make_buffer(arrow, side, side, stride)
    e.mu.mem_write(PLANE, bytes(native) + b"\x5A" * (PLANE_LEN - len(native)))
    _w32(e.mu, e.s2v["g_btn_origW"], side)
    _w32(e.mu, e.s2v["g_btn_origH"], -side)
    e.run(e.s2v["thunk_btn_stripes"], regs={UC_X86_REG_ESI: arrow})
    plane = bytes(e.mu.mem_read(PLANE, PLANE_LEN))
    assert plane[len(native):] == b"\x5A" * (PLANE_LEN - len(native)), "wrote past the canvas"
    assert _r32(e.mu, e.s2v["g_rm_f0ovr"]) == 0, "the F0 one-shot must be consumed"
    return plane[:len(native)], bytes(native), side, stride


@pytest.mark.parametrize("g", (18, 21, 22, 25, 32, 40))
def test_arrow_face_follows_the_law_through_the_real_btn_stripes(emu, live, g):
    """thunk_btn_stripes is only reached above native scale (thunk_btn_shrink arms the zoom at g > 16)."""
    got, native, side, stride = _stripe_arrow(emu, g)
    T = SL.stripe_rows(g)
    seen = set()
    for y in range(side):
        for x in range(side):
            v = native[y * stride + x]
            want = SL.sbarrow_bg_pixel(v, y, g)
            if v in (0xF0, 0xB9):
                want = SL.stripe_color_sb(y, g)
                assert want == (0xF0 if (y % (2 * T)) < T else 0xB9)
            if v in (0xC2, 0xC5):
                assert want == (0xC2 if (y % (2 * T)) < T else 0xC5)
            assert got[y * stride + x] == want, (g, x, y, hex(v), hex(got[y * stride + x]), hex(want))
            seen.add(v)
        assert got[y * stride + side:(y + 1) * stride] == native[y * stride + side:(y + 1) * stride], "row gutter written"
    assert {0xF0, 0xB9, 0xC2, 0xC5, 0x29} <= seen
    if not _APPLIED:
        cause, native2, _side, _stride = _stripe_arrow(live, g)
        assert cause == native2, "cause: with the live t_rw_sbarrows the arrow face keeps its NN-enlarged 1-row dither"


# ---- (4) layout, sites, and the state of the hand-applied edits --------------------------------------------------
def test_block_sits_in_a_free_gap_and_templates_round_trip(emu):
    end = emu.cell_off + 4
    assert RB.OFF_CODE <= min(o for o, _ in emu.layout.values()) and end <= RB.OFF_LIMIT
    assert _APPLIED or emu.cave_image[RB.OFF_CODE:end] == b"\x00" * (end - RB.OFF_CODE), "the block overlaps live cave contents"
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    for name, spec in symbols.items():
        if spec.get("cave") == "pcave2" and name not in emu.va:
            lo, hi = int(spec["offset"]), int(spec["offset"]) + int(spec.get("size", 4))
            assert hi <= RB.OFF_CODE or lo >= end, f"{name} is declared inside the block"
    assert not RB.roundtrip_problems(emu.layout, emu.cell_off, emu.syms)
    assert emu.cell % 4 == 0


def test_sites_match_the_pristine_base_and_collide_with_nothing():
    sites = RB.site_list()
    assert not RB.verify_live(sites)
    mine = [(s["va"], s["va"] + len(s["orig"])) for s in sites]
    yaml_sites, _groups, _caves, _symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    ids = {s["id"] for s in sites}
    for y in yaml_sites:
        if y.get("id") in ids or "virtual_addr" not in y:
            continue
        lo, hi = int(y["virtual_addr"]), int(y["virtual_addr"]) + int(y.get("length", 0))
        for a, b in mine:
            assert hi <= a or lo >= b, f"{y['id']} overlaps a new site"
    import rw_kinds_rows                                     # the report walker's imm rows live in a table, not in sites
    for row in rw_kinds_rows.KINDS_IMMS:
        for a, b in mine:
            assert not (a <= row[0] < b) and not (a < row[0] + row[1] <= b), f"walker row {row} inside a new site"
    assert RB.SITE_END + 5 == RB.END_RESUME


def test_edits_derive_from_the_live_entries_and_fit(emu):
    for e in emu.edits.values():
        assert e["applied"] or e["anchor_ok"], f"{e['name']}: the yaml entry is neither the anchored old text nor the edit"
        assert e["fits"], f"{e['name']}: {e['new_len']}B does not fit its slot"
        nxt = [int(c["offset"]) for c in _pcave2_contents() if int(c["offset"]) > e["off"]]
        assert e["off"] + e["new_len"] <= min(nxt), f"{e['name']}: runs into the next cave entry"
    assert not emu.unresolved or all(n not in ("thunk_pref_sbzoom", "t_rw_sbarrows", "thunk_sb_restripe", "thunk_fe_pair_remap",
                                                "thunk_btn_stripes", "thunk_sbarrow_bg", "thunk_ed_remap", "thunk_list_gate",
                                                "thunk_lbres_ecx") for n, _ in emu.unresolved)


def _pcave2_contents():
    _sites, _groups, caves, _symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    return next(c for c in caves if c["id"] == "pcave2").get("contents") or []


@pytest.mark.parametrize("name", ["thunk_pref_sbzoom", "t_rw_sbarrows"])
def test_live_yaml_carries_the_edit(emu, name):
    e = emu.edits[name]
    if not e["applied"]:
        pytest.skip(f"EDIT NOT APPLIED YET: patches.yaml `{name}` is still the old text; paste the `new:` template "
                    f"printed by `py scripts/assemble_stripes_rwsb.py` (+{e['new_len'] - e['old_len']}B, same offset)")
    assert e["live"] == e["new"]


def test_fragments_are_current():
    frag = ROOT / "patches"
    files = [frag / f"_fragment_stripes_rwsb_{k}.yaml" for k in ("symbols", "cave", "sites")]
    if not all(f.exists() for f in files):
        pytest.skip("fragments not generated: run `py scripts/assemble_stripes_rwsb.py --fragments`")
    syms = RB.load_syms()
    layout, cell_off = RB.assemble_all(syms)
    names = RB.names_of(layout, cell_off)
    cave = files[1].read_text(encoding="utf-8")
    for name, (off, b) in layout.items():
        assert f"- id: {name}\n        offset: {off:#x}\n        bytes: \"{RB.templatize(b, PCAVE2 + off, syms, names)}\"" in cave
    assert RB.site_yaml(RB.site_list()) == files[2].read_text(encoding="utf-8")
    assert f"offset: {cell_off:#x}, size: 4" in files[0].read_text(encoding="utf-8")
