"""Differential: the UNTITLED-popup chrome thunks vs scaling_laws.py.

scripts/assemble_untitled_popup.py ships three thunks; each is emulated under
Unicorn at its real VA, with the REAL (yaml-resolved) thunk_popup_titleinsets /
thunk_title_hmargin bytes mapped so the stash is checked against the very
cascade the titled path runs:

  thunk_untitled_stash   virtual g_title_left/right == titled cascade on the
                         same rect (+1/-1); g_title_bottom == law
                         untitled_virtual_title_bottom, which makes fieldpads'
                         keyed arm (law popup_field_top) land on the engine
                         T = content_top - ps3; key/flag hygiene on every path
  thunk_scale_header v2  == popup_header_reserve
  thunk_popup_nestpads v3 == nested_frame_pad(g, body_only) per source-rect
                         path; untitled anchor pre-add == flat_art_anchor

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import functools
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

import apply_patches as ap  # noqa: E402
import assemble_untitled_popup as ASM  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

PAGE = 0x1000
STACK = 0x00200000
SP0 = STACK + 0x800
FRAME = STACK + 0xC00                 # the caller's ebp
RECT = STACK + 0xE00                  # &window rect (ebx)
POPUP = 0x00300000                    # fake popup object (esi), 0x4000 mapped
FACTION = ASM.FACTION_POPUP
RET_SITE = 0x00405F81
VIS_CELL = 0x005F7F00                 # Win_is_visible stub's return value cell
G_RANGE = range(16, 41)


@functools.lru_cache(maxsize=None)
def _sym():
    return ASM.sym_vas()


@functools.lru_cache(maxsize=None)
def _layout():
    return ASM.assemble_all()


@functools.lru_cache(maxsize=None)
def _yaml_thunk(name: str) -> tuple[int, bytes]:
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    st = ap.build_symbol_table(symbols, caves)
    for cave in caves:
        for ent in cave.get("contents") or []:
            if ent.get("id") == name:
                return st[name], ap.ByteTemplate(ent["bytes"]).resolve(st[name], st)
    raise KeyError(name)


class _Machine:
    def __init__(self):
        self.s = _sym()
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(0x00668000, 2 * PAGE)                 # menu_strip cave (g, hmargin)
        mu.mem_map(ASM.PCAVE2, 0x38000)                  # pcave2 (thunk_title_hmargin v2 at 0x35300, F36)
        mu.mem_map(STACK, PAGE)
        mu.mem_map(POPUP, 4 * PAGE)
        mu.mem_map(FACTION & ~(PAGE - 1), 4 * PAGE)
        mu.mem_map(0x005F7000, PAGE)                     # Win_is_visible stub
        mu.mem_map(0x00405000, PAGE)                     # ret site (never executed)
        mu.mem_map(0x00603000, PAGE)                     # header_reserve_resume (never executed)
        for name, (off, b) in _layout().items():
            mu.mem_write(ASM.PCAVE2 + off, b)
        for name in ("thunk_popup_titleinsets", "thunk_title_hmargin"):
            va, b = _yaml_thunk(name)
            mu.mem_write(va, b)
        ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
        stub, _ = ks.asm(f"mov eax,[{VIS_CELL:#x}]; mov ecx,0x22222222; mov edx,0x33333333; ret",
                         ASM.WIN_IS_VISIBLE)
        mu.mem_write(ASM.WIN_IS_VISIBLE, bytes(stub))    # written ONCE (param in a data cell)

    def reset(self, g: int, visible: int):
        for base, size in ((STACK, PAGE), (POPUP, 4 * PAGE), (FACTION & ~(PAGE - 1), 4 * PAGE)):
            self.mu.mem_write(base, bytes(size))
        for k in ("g_title_left", "g_title_right", "g_title_bottom", "g_band_popup",
                  "g_field_anchor", "g_fp_ornart"):
            self.w32(self.s[k], 0)
        self.w32(VIS_CELL, visible)
        self.w32(self.s["g_popup_scale_num"], g)
        for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                  UC_X86_REG_ESI, UC_X86_REG_EDI):
            self.mu.reg_write(r, 0)

    def w32(self, a, v): self.mu.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    def r32(self, a): return int.from_bytes(self.mu.mem_read(a, 4), "little")
    def rs32(self, a): return int.from_bytes(self.mu.mem_read(a, 4), "little", signed=True)

    def call(self, va: int, regs: dict[int, int], until: int = RET_SITE) -> None:
        self.w32(SP0, until)
        self.mu.reg_write(UC_X86_REG_ESP, SP0)
        self.mu.reg_write(UC_X86_REG_EBP, FRAME)
        for r, v in regs.items():
            self.mu.reg_write(r, v & 0xFFFFFFFF)
        self.mu.emu_start(va, until, count=2000)

    def reg(self, r): return self.mu.reg_read(r)


_M: list = []


@pytest.fixture(scope="module", autouse=True)
def _drop_machine():
    yield
    _M.clear()          # free the Uc before interpreter teardown (exit-time AV otherwise)


def Emu(g: int, visible: int = 1) -> _Machine:
    if not _M:
        _M.append(_Machine())
    _M[0].reset(g, visible)
    return _M[0]


def _va(name: str) -> int:
    off, _ = _layout()[name]
    return ASM.PCAVE2 + off


# ---------------------------------------------------------------- stash ----
def _titled_cascade(g: int, visible: int, L: int, R: int) -> tuple[int, int]:
    """Run the inset thunk the TITLED path would run on [ebp-0x14]/[ebp-0xc]."""
    e = Emu(g, visible)
    e.w32(FRAME - 0x14, L); e.w32(FRAME - 0xC, R)
    name = "thunk_popup_titleinsets" if visible else "thunk_title_hmargin"
    va, _ = _yaml_thunk(name)
    e.call(va, {})
    return e.rs32(FRAME - 0x14) + 1, e.rs32(FRAME - 0xC) - 1


@pytest.mark.parametrize("visible", [0, 1])
@pytest.mark.parametrize("ptype", [0, 5])
def test_stash_matches_titled_cascade_and_field_top_law(visible, ptype):
    for g in range(17, 41):
        for (L, R, ct) in ((0, 1831, 45), (0, 977, 18 * g // 16), (12, 2640, 61)):
            want_lr = _titled_cascade(g, visible, L, R)      # FIRST: it resets the shared machine
            e = Emu(g, visible)
            s = e.s
            e.w32(POPUP + 0xA48, 0)
            e.w32(POPUP + 0x30E8, ct - 2); e.w32(POPUP + 0x30E0, 2)
            e.w32(FRAME - 4, ptype)
            e.w32(RECT, L); e.w32(RECT + 8, R)
            e.w32(s["g_title_left"], 0x7777); e.w32(s["g_title_right"], 0x7777)   # STALE
            e.call(_va("thunk_untitled_stash"),
                   {UC_X86_REG_ESI: POPUP, UC_X86_REG_EBX: RECT, UC_X86_REG_EDI: 0x444444})
            assert e.reg(UC_X86_REG_EAX) == 0
            assert e.reg(UC_X86_REG_ESP) == SP0 + 4 and e.reg(UC_X86_REG_EBP) == FRAME
            assert (e.reg(UC_X86_REG_ESI), e.reg(UC_X86_REG_EBX), e.reg(UC_X86_REG_EDI)) == (POPUP, RECT, 0x444444)
            assert (e.rs32(s["g_title_left"]), e.rs32(s["g_title_right"])) == want_lr
            tb = e.rs32(s["g_title_bottom"])
            assert tb == SL.untitled_virtual_title_bottom(ct, g)
            raw = ptype * 10000
            assert SL.popup_field_top(ct, tb, raw, True, g) == ct - SL.popup_pad(3, g) \
                == SL.popup_field_top(ct, 0, raw, False, g)
            assert e.r32(s["g_band_popup"]) == POPUP


@pytest.mark.parametrize("g,ptype,popup", [(16, 0, POPUP), (25, 2, POPUP), (40, 6, POPUP),
                                           (40, 1000, POPUP), (40, 0, FACTION)])
def test_stash_off_paths_disarm(g, ptype, popup):
    for stale_key in (popup, 0x12345678):
        e = Emu(g)
        s = e.s
        e.w32(popup + 0xA48, 0)
        e.w32(FRAME - 4, ptype)
        e.w32(s["g_band_popup"], stale_key)
        e.w32(s["g_title_left"], 111); e.w32(s["g_title_right"], 222)
        e.call(_va("thunk_untitled_stash"), {UC_X86_REG_ESI: popup, UC_X86_REG_EBX: RECT})
        assert e.reg(UC_X86_REG_EAX) == 0 and e.reg(UC_X86_REG_ESP) == SP0 + 4
        assert e.r32(s["g_band_popup"]) == (0 if stale_key == popup else stale_key)
        assert (e.r32(s["g_title_left"]), e.r32(s["g_title_right"])) == (111, 222)


@pytest.mark.parametrize("g", [16, 25, 40])
def test_stash_titled_is_the_displaced_instruction(g):
    e = Emu(g)
    s = e.s
    e.w32(POPUP + 0xA48, 0x00ABCDEF)
    e.w32(s["g_band_popup"], POPUP)
    e.w32(s["g_title_left"], 111)
    e.call(_va("thunk_untitled_stash"), {UC_X86_REG_ESI: POPUP, UC_X86_REG_EBX: RECT})
    assert e.reg(UC_X86_REG_EAX) == 0x00ABCDEF
    assert e.r32(s["g_band_popup"]) == POPUP
    assert e.r32(s["g_title_left"]) == 111


# --------------------------------------------------------- scale_header ----
@pytest.mark.parametrize("raw", [0, 9999, 10000, 20000, 50000, 59999, 60000, 10000000])
def test_scale_header_matches_law(raw):
    resume = _sym()["header_reserve_resume"]
    for g in G_RANGE:
        for titled in (0, 1):
            for popup in (POPUP, FACTION):
                for native in (18, 38, 27, 47, 0):
                    e = Emu(g)
                    e.w32(popup + 0x21B8, native)
                    e.w32(popup + 0xA48, 0x5000 if titled else 0)
                    e.w32(popup + 0x30AC, raw)
                    e.mu.reg_write(UC_X86_REG_ESP, SP0)
                    e.mu.reg_write(UC_X86_REG_ESI, popup)
                    e.mu.reg_write(UC_X86_REG_EAX, 0xCAFE)
                    e.mu.emu_start(_va("thunk_scale_header"), resume, count=200)
                    assert e.reg(UC_X86_REG_ESP) == SP0 and e.reg(UC_X86_REG_EAX) == 0xCAFE
                    assert e.reg(UC_X86_REG_ECX) == SL.popup_header_reserve(
                        native, bool(titled), raw, popup == FACTION, g)


def test_scale_header_untitled_version_popup_4k():
    assert SL.popup_header_reserve(18, False, 0, False, 40) == 45       # 18 x 2.5
    assert SL.popup_header_reserve(18, False, 0, False, 16) == 18       # native no-op
    assert SL.popup_header_reserve(18, False, 60000, False, 40) == 18   # ornate: TutWin chain owns it
    assert SL.popup_header_reserve(38, True, 0, False, 40) == 95        # v1 behaviour kept


# ------------------------------------------------------------- nestpads ----
PATHS = [   # (body_h, dlg_type, art, body_only)
    (0, 2, 0, False),          # list container only
    (0, -1, 0, False),
    (40, 1, 0, False),         # UnionRect(d528, dialog): unchanged v2
    (40, -1, 0, True),         # OK-only text popup
    (40, 16, 0x5000, True),    # Quit: art + dialog
    (40, -1, 0x5000, True),    # version popup
]


@pytest.mark.parametrize("body_h,dlg,art,body_only", PATHS)
def test_nestpads_matches_law(body_h, dlg, art, body_only):
    for g in G_RANGE:
        for keyed, ornart in ((0, 0), (1, 0), (1, 1)):
            e = Emu(g)
            s = e.s
            e.w32(POPUP + 0x30D4, body_h); e.w32(POPUP + 0x2350, dlg); e.w32(POPUP + 0x2144, art)
            e.w32(s["g_band_popup"], POPUP if keyed else 0x12345678)
            e.w32(s["g_fp_ornart"], ornart)
            e.w32(s["g_field_anchor"], 38)
            L, T, R, B = 600, 38, 2600, 320
            e.call(_va("thunk_popup_nestpads"),
                   {UC_X86_REG_ESI: POPUP, UC_X86_REG_EAX: L, UC_X86_REG_ECX: R,
                    UC_X86_REG_EDX: T, UC_X86_REG_EDI: B, UC_X86_REG_EBX: 0xB0B0})
            pad = SL.nested_frame_pad(g, body_only)
            assert (e.reg(UC_X86_REG_EAX), e.reg(UC_X86_REG_ECX), e.reg(UC_X86_REG_EDX),
                    e.reg(UC_X86_REG_EDI)) == (L - pad, R + pad, T - pad, B + pad)
            assert e.rs32(FRAME - 0x24) == L - pad
            assert e.reg(UC_X86_REG_EBX) == 0xB0B0 and e.reg(UC_X86_REG_ESP) == SP0 + 4
            pre = bool(keyed) and not ornart and body_only and g > SL.NATIVE_G
            assert e.rs32(s["g_field_anchor"]) == (SL.flat_art_anchor(38, g) if pre else 38)
            assert e.r32(s["g_band_popup"]) == (POPUP if keyed else 0x12345678)      # never consumed here


def test_nestpads_foreign_key_never_preadds():
    e = Emu(40)
    s = e.s
    e.w32(POPUP + 0x30D4, 40); e.w32(POPUP + 0x2350, -1)
    e.w32(s["g_band_popup"], 0x12345678); e.w32(s["g_field_anchor"], 38)
    e.call(_va("thunk_popup_nestpads"), {UC_X86_REG_ESI: POPUP})
    assert e.rs32(s["g_field_anchor"]) == 38


def test_body_only_pitch_equals_the_pf_aligned_right_pitch():
    """The defect: L/T/B stroke pitch 5 vs R 7 @g40.  Law: every side == ps3."""
    for g in G_RANGE:
        r_pitch = SL.body_outer_edge_r(1000, g) - SL.body_inner_edge_r(1000, g)
        assert SL.nested_frame_pad(g, body_only=True) == r_pitch == (3 if g <= 16 else SL.popup_pad(3, g))


def test_art_top_lands_on_the_ring_top():
    """artalign's flat math on the pre-added anchor == ring top (T - ps3)."""
    for g in range(17, 41):
        T = 45 * g // 40
        y_seed = SL.popup_art_y(SL.flat_art_anchor(T, g), 0, g)
        assert y_seed - 6 == T - SL.nested_frame_pad(g, body_only=True)


def test_slot_layout():
    lay = _layout()
    end = max(o + len(b) for o, b in lay.values())
    assert ASM.SLOT_START <= min(o for o, _ in lay.values()) and end <= ASM.SLOT_END
    offs = sorted((o, o + len(b)) for o, b in lay.values())
    assert all(a[1] <= b[0] for a, b in zip(offs, offs[1:]))


def test_quit_art_lands_on_the_ring_top():
    """Titled keyed popup (Quit): fieldpads' band arm T, ring at T - ps3, artalign's flat
    math on the pre-added anchor == ring top.  Before: art delta ABOVE (928 vs 931 @g40)."""
    for g in range(17, 41):
        T = SL.popup_field_top(0, SL.popup_pad(29, g), 0, True, g)
        ring_top = T - SL.nested_frame_pad(g, body_only=True)
        assert SL.popup_art_y(SL.flat_art_anchor(T, g), 0, g) - 6 == ring_top


# ------------------------------------------------------ backdrop railtrim ----
BACKDROP_RET = 0x00405F7C


@pytest.mark.parametrize("g", list(G_RANGE))
@pytest.mark.parametrize("inset", [True, False])
def test_backdrop_railtrim_matches_law(g, inset):
    """The d690 DRAW copy's R per law popup_backdrop_draw_right; L/T/B, the window rect, ecx and
    the arg slots untouched; control leaves for thunk_tutwin_backdrop with the stack intact."""
    e = Emu(g)
    win = (0, 0, 1886, 1200)
    for i, v in enumerate(win):
        e.w32(RECT + 4 * i, v)
    draw = (57, 0, 1747 if inset else win[2], 1212)
    DRAW = FRAME - 0x14
    for i, v in enumerate(draw):
        e.w32(DRAW + 4 * i, v)
    e.w32(SP0 + 4, DRAW); e.w32(SP0 + 8, 0x0078D690)
    target = e.s["thunk_tutwin_backdrop"]
    e.call(_va("thunk_backdrop_railtrim"), {UC_X86_REG_EBX: RECT, UC_X86_REG_ECX: 0x11111111}, until=target)
    assert e.reg(UC_X86_REG_ESP) == SP0 and e.r32(SP0) == target       # `ret` not executed yet: [esp] = the pushed target
    got = tuple(e.rs32(DRAW + 4 * i) for i in range(4))
    assert got == (draw[0], draw[1], SL.popup_backdrop_draw_right(draw[2], win[2], g), draw[3])
    assert tuple(e.rs32(RECT + 4 * i) for i in range(4)) == win
    assert e.reg(UC_X86_REG_ECX) == 0x11111111
    assert e.r32(SP0 + 4) == DRAW and e.r32(SP0 + 8) == 0x0078D690


def test_backdrop_border_abuts_the_rail():
    """The inclusive band-map footprint of the trimmed rect ends ON the column before the rail's first
    column at every g: the border keeps its full K (was K-1: 1/1/0 px @g40/25/22)."""
    for g in range(17, 41):
        for win_w in range(900, 2000, 37):
            anchor = ((win_w * 16 // g) - 55) * g // 16            # thunk_popup_d690insets R == the rail's first col
            r = SL.popup_backdrop_draw_right(anchor, win_w, g)
            assert r == anchor - 1                                 # last drawn col (inclusive) = anchor-1
