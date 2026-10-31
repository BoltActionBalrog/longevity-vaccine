"""HQ console tab buttons (TECHNOLOGY | BASES, GOVERNOR | BEST BASES; fix 19) and the six CouncilWin buttons (fix 21):
the 2D-zoom source height.

The REAL FlatButton draw chain of the baked image runs under Unicorn in the engine's own order -- FlatButton_content_draw
from its 0x607E7F detour: thunk_btn_shrink (the real gate t_dw_gate -> thunk_btn_gate admits the ReportIf buttons) ->
thunk_tutbtn_post -> t_btn_nath_pin -> the engine's native 9-slice render (default art: TL / T / TR, 20 rows, top-
anchored; the T fill through thunk_btn_fillcap) -> the 0x608365 detour thunk_btn_2dscale -> thunk_btn_bandstripe -> the
keyed stretch -> restore -> thunk_btn_ringfix / thunk_btn_stripes / thunk_btn_devfill -> 0x60836B.  Only the engine's
pixel primitives are stand-ins: the canvas clear, Sprite draw, Buffer tile fill and the keyed stretch (the measured
centre-sampled NN, scaling_laws.nn_center_index).

Law scaling_laws.rw_tab_btn_zoom_src_h: the zoom source is vanilla's own 0x14 rows, so the face fills
rw_tab_pair's law rect and both channels are s(2).  The deployed tail (push 0x607E85: the CEIL inverse alone)
reproduces the four real shots' short faces; every other FlatButton draws byte-identically with and without the pin.

Fix 21 (law scaling_laws.flatbutton_zoom_src_h / council_btn_h): the CouncilWin buttons [0x6FFA14, 0x703DDC) are
vanilla 0x14 with the same art; the immfix'd row height s(23) - s(3) is fl(20g/16) + 1 at g 19/21/23/26/30/31/35/37/39,
so the CEIL inverse recovered 21 and the face stopped 2 rows short at g 26/30/31/35/37/39 (the 2560x1440 council shot:
36 of 38) and 1 row short at g 19/21/23.  The `fix19` chain restores fix 19's tab-only admit (the Council `jb out` ->
`jmp out`) so the Council change is measured against exactly what shipped.

Fix 22b (the user's symmetry rule; fix 22's HUD M / I pin backed out): the HUD M / I buttons (MainWin FlatButtons[0] /
[1] 0x7AF620 / 0x7B016C) are NOT pinned.  Fix 23 (law scaling_laws.hud_mi_btn_rect, port t_hud_mi_square = the tail
of thunk_hud_seedscale): their windows were the floor image of both vanilla edges, fl(20g/16) or one more per axis
and per button (1080p M 27x27, I 27x28; 1440p M 37x38, I 37x37), so the faces fell short and M != I at some g; they are
now s(20) squares, where the CEIL inverse is exactly 20: both faces fill, M == I, square, at every g.  Fix 23b (laws
hud_mi_column / hud_toolbar_rect): the scenario editor's TOOLBAR (0x7B0CB8, vanilla 734..754 like M / I) shares their
column -- one left and one right edge, right-anchored at fl(754g/16) so no corner pair that held before fix 23 breaks;
fix 23 left it 1 px wider on the right at g 17/18/19/25/26/27/33/34/35 -- and M / I are anchored at their
TOOLBAR-facing edges.  The guard runs the image's own bytes in the engine's order -- MainWin_build's seed stores and
derivation (0x459912.. / 0x459A53..0x459B7B), the seedscale call-redirect @0x459E8A into its tail, BaseButton_init's
arg loads (I @0x45A960, M @0x45A9EB, TOOLBAR @0x45AA76) -- then draws the windows on the real chain; the pre-fix-23
tail (push Buffer_load_pcx), fix 23's own thunk and the left-anchored column are the mutants the checks must kill.

Shot goldens (work\\screenshots, gitignored -- the measured rows are pinned here; the PNG cross-check runs when the
shot is present): the face is the run of face colours 78a4d4 / 688cc4 / 675bb5 / 1c5063 down column x; the box
strokes are 314e2c.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
KSB = 0x668670                 # thunk_keyed_stretch_blit (the engine stretch: stand-in)
SPR_DRAW, FILL, CLEAR, GW5250 = 0x5E4B4A, 0x5DA9F0, 0x5DE8F0, 0x5D5250
DETOUR, NATIVE_RESUME, RESUME = 0x607E7F, 0x607E85, 0x60836B
TUTBTN_POST_TAIL = 0xA10081    # thunk_tutbtn_post's `push imm32` (pcave2 0x4000 + 0x81)
G_BTN_NATIVE_H = 0xA0C544
KEY = 9
HEAP = 0x20000000
PLANE = HEAP + 0x100000
STRIDE = 4096
ROWS = 128
SPR_T, SPR_TL, SPR_TR = HEAP + 0x1000, HEAP + 0x1100, HEAP + 0x1200
ART = {SPR_T: (67, 20, 0x10), SPR_TL: (3, 20, 0x20), SPR_TR: (3, 20, 0x30)}   # the default frame pieces (terranx.h)
TABS = SL.RW_TAB_BTN_OBJECTS
REGION = (0, 0, 600, 300)
PIN_LEN = 110                  # t_btn_nath_pin (fix 21 / 22b; + the NetWin lobby pair, wave-1 fix 27)
COUNCIL = tuple(range(SL.COUNCIL_BTN_RANGE[0], SL.COUNCIL_BTN_RANGE[1], 0xB4C))     # CouncilWin + 0xD94, the six
COUNCIL_W = 487                # CouncilWin_exec: the row's full-width buttons (ids 4 / 5) at g = 16
HUD_MI = SL.HUD_MI_BTN_OBJECTS  # MainWin FlatButtons[0] M / [1] I: NOT pinned (fix 22b)
NETWIN = SL.NETWIN_BTN_OBJECTS  # the lobby LAUNCH GAME / CANCEL: pinned since wave-1 fix 27 (test_scaling_netwin_btnpair.py)

#: (shot, g, tab object, column x, box top row (screen), the face rows the shot shows [top, bottom) -- deployed)
SHOTS = (
    ("3840x2160_20261022-204219", 40, TABS[1], 1000, 1672, (1679, 1728)),    # F2 BASES (normal state)
    ("3840x2160_20261022-204238", 40, TABS[3], 1000, 1672, (1679, 1728)),    # F4 BEST BASES
    ("1920x1080_20261022-205410", 22, TABS[0], 500, 812, (816, 843)),        # F2 TECHNOLOGY
    ("1600x1200_20261022-210944", 25, TABS[0], 200, 896, (901, 932)),        # F2: already law at g = 25
)
FACE_COLOURS = {"78a4d4", "688cc4", "675bb5", "1c5063"}
SHOT_DIR = ROOT / "screenshots"


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return baked_exe.read_bytes()


class Chain:
    """One Unicorn over the whole baked image.  deployed=True restores the pre-fix-19 tail (push 0x607E85);
    fix19=True keeps the pin but restores fix 19's tab-only admit (the Council range's `jb out` -> `jmp out`)."""

    def __init__(self, image: bytes, deployed: bool = False, fix19: bool = False):
        pe = pefile.PE(data=image)
        ib = pe.OPTIONAL_HEADER.ImageBase
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(HEAP, 0x400000)
        assert bytes(mu.mem_read(DETOUR, 6)) == b"\x68" + struct.pack("<I", 0xA0C400) + b"\xC3", "shrink detour"
        assert bytes(mu.mem_read(TUTBTN_POST_TAIL - 2, 3)) == b"\x61\x9D\x68", "thunk_tutbtn_post tail shape"
        self.pin_va = struct.unpack("<I", mu.mem_read(TUTBTN_POST_TAIL + 1, 4))[0]
        if deployed:
            mu.mem_write(TUTBTN_POST_TAIL + 1, struct.pack("<I", NATIVE_RESUME))
        pin = bytes(mu.mem_read(self.pin_va, PIN_LEN))
        cw = pin.index(b"\x81\xFE" + struct.pack("<I", SL.COUNCIL_BTN_RANGE[0]))
        assert pin[cw + 6] == 0x72, "the Council admit's `jb out`"
        if fix19:
            mu.mem_write(self.pin_va + cw + 6, b"\xEB")
        for va, n in ((KSB, 0x2C), (SPR_DRAW, 0x18), (FILL, 0x1C), (CLEAR, 4), (GW5250, 4)):
            mu.mem_write(va, b"\xC2" + struct.pack("<H", n))
        mu.hook_add(UC_HOOK_CODE, self._ksb, begin=KSB, end=KSB)
        mu.hook_add(UC_HOOK_CODE, self._spr, begin=SPR_DRAW, end=SPR_DRAW)
        mu.hook_add(UC_HOOK_CODE, self._fill, begin=FILL, end=FILL)
        mu.hook_add(UC_HOOK_CODE, self._clear, begin=CLEAR, end=CLEAR)
        mu.hook_add(UC_HOOK_CODE, self._at_native, begin=NATIVE_RESUME, end=NATIVE_RESUME)
        self.calls, self.errors, self.native, self.stop_native = [], [], None, False
        for spv, (w, h, _c) in ART.items():
            self.w32(spv + 0x18, w)
            self.w32(spv + 0x1C, h)

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def _args(self, n):
        sp = self.mu.reg_read(UC_X86_REG_ESP)
        return [self.r32(sp + 4 + 4 * i) for i in range(n)]

    def _paint(self, buf, x, y, w, h, c):
        bw, bh = self.r32(buf + 0x80), -self.r32(buf + 0x84)
        data = self.r32(buf + 0x54) & 0xFFFFFFFF
        for yy in range(max(0, y), min(bh, y + h)):
            x0, x1 = max(0, x), min(bw, x + w)
            if x1 > x0:
                self.mu.mem_write(data + yy * STRIDE + x0, bytes([c]) * (x1 - x0))

    def _clear(self, mu, a, s, u):
        buf = mu.reg_read(UC_X86_REG_ECX)
        self.calls.append("clear")
        self._paint(buf, 0, 0, self.r32(buf + 0x80), -self.r32(buf + 0x84), self._args(1)[0] & 0xFF)

    def _spr(self, mu, a, s, u):
        buf, _key, x, y, _a, _b = self._args(6)
        w, h, c = ART[mu.reg_read(UC_X86_REG_ECX)]
        self.calls.append("spr")
        if buf:
            self._paint(buf, x, y, w, h, c)

    def _fill(self, mu, a, s, u):
        spr, _sx, _sy, x, y, w, h = self._args(7)
        self.calls.append("fill")
        self._paint(mu.reg_read(UC_X86_REG_ECX), x, y, w, h, ART[spr & 0xFFFFFFFF][2] + 0x40)

    def _ksb(self, mu, a, s, u):
        try:
            _dst, src, sx, sy, sw, sh, dx, dy, dw, dh, _key = self._args(11)
            self.calls.append(("ksb", sw, sh, dw, dh))
            data = self.r32(src + 0x54) & 0xFFFFFFFF
            pl = bytearray(mu.mem_read(data, STRIDE * ROWS))
            srcpx = [bytes(pl[(sy + r) * STRIDE + sx:(sy + r) * STRIDE + sx + sw]) for r in range(sh)]
            cols = [SL.nn_center_index(i, dw, sw) for i in range(dw)]
            for j in range(dh):
                row = srcpx[SL.nn_center_index(j, dh, sh)]
                pl[(dy + j) * STRIDE + dx:(dy + j) * STRIDE + dx + dw] = bytes(row[c] for c in cols)
            mu.mem_write(data, bytes(pl))
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    def _at_native(self, mu, a, s, u):
        if self.stop_native:
            mu.emu_stop()
            return
        esi = mu.reg_read(UC_X86_REG_ESI)
        self.native = (self.r32(G_BTN_NATIVE_H), self.r32(esi + 0x4C8), self.r32(esi + 0x4C4))

    def draw(self, esi: int, w: int, h: int, g: int, state: int = 0):
        """FlatButton_content_draw from its 0x607E7F detour to the 0x60836B resume (no label).  Returns the canvas
        (rows x STRIDE) and the native dims the render saw at 0x607E85 (g_btn_nativeH, [esi+0x4C8], [esi+0x4C4])."""
        mu = self.mu
        self.calls.clear()
        self.errors.clear()
        self.native = None
        self.w32(G_VA, g)
        self.w32(0x9B7B28, 1)
        self.w32(0x9B8180, KEY)
        mu.mem_write(0xA0C534, b"\0" * 0x18)                # g_btn_pending .. g_btn_tileH: no state across draws
        mu.mem_write(esi, b"\0" * 0xB4C)
        self.w32(esi + 0xC4, 0x7AE820)                     # parent MainWin (ReportIf_activate: push 0x7AE820)
        buf = esi + 0x444
        self.w32(buf + 0x54, PLANE)
        self.w32(buf + 0x80, w)
        self.w32(buf + 0x84, -h)
        self.w32(buf + 0x4A8, STRIDE)
        for i, v in enumerate((0, 0, w, h)):
            self.w32(esi + 0x474 + 4 * i, v)
        self.w32(esi + 0xAB8, state)
        for st in range(3):
            self.w32(esi + 0xAF8 + 4 * st, SPR_T)
            self.w32(esi + 0xB10 + 4 * st, SPR_TL)
            self.w32(esi + 0xB1C + 4 * st, SPR_TR)
        mu.mem_write(PLANE, bytes([0x77]) * (STRIDE * ROWS))
        stk = HEAP + 0x80000
        mu.mem_write(stk - 0x2000, b"\0" * 0x3000)
        for r, v in ((UC_X86_REG_ESP, stk), (UC_X86_REG_ESI, esi), (UC_X86_REG_EBP, 0), (UC_X86_REG_EDI, 0),
                     (UC_X86_REG_EBX, 0)):
            mu.reg_write(r, v)
        mu.emu_start(DETOUR, RESUME, count=50_000_000)
        assert not self.errors, self.errors
        assert mu.reg_read(UC_X86_REG_EIP) == RESUME
        assert self.r32(esi + 0x4C8) == -h and self.r32(esi + 0x4C4) == w, "2dscale restores the device dims"
        return bytes(mu.mem_read(PLANE, STRIDE * ROWS)), self.native


@pytest.fixture(scope="module")
def fixed(baked):
    return Chain(baked)


@pytest.fixture(scope="module")
def deployed(baked):
    return Chain(baked, deployed=True)


@pytest.fixture(scope="module")
def fix19(baked):
    return Chain(baked, fix19=True)


def _face(canvas: bytes, h: int, x: int) -> list:
    return [j for j in range(h) if canvas[j * STRIDE + x] != KEY]


def _tab(g: int):
    box, a, _b = SL.rw_tab_pair(REGION, g)
    return box, a, a[2] - a[0], a[3] - a[1]


# ==== the law itself ==================================================================================================
@pytest.mark.parametrize("g", range(17, 41))
def test_law_face_needs_the_pin_where_the_ceil_inverse_overshoots(g):
    """rw_tab_btn_zoom_src_h is vanilla's 0x14 == the art rows; with it the zoom fills the law face at every g,
    with the CEIL inverse it falls short exactly where that inverse exceeds 20 (the g = 22 / 40 shots)."""
    _box, _a, _w, h = _tab(g)
    assert SL.rw_tab_btn_zoom_src_h(g) == SL.BTN_BAR_NATIVE_H == 0x14
    assert SL.flatbutton_zoom_face_rows(h, SL.rw_tab_btn_zoom_src_h(g)) == h
    ceil = SL.btn_native_dim(h, g)
    assert (SL.flatbutton_zoom_face_rows(h, ceil) < h) == (ceil > 20), (g, h, ceil)


# ==== the real chain: fixed ===========================================================================================
@pytest.mark.parametrize("g", range(17, 41))
def test_tab_face_is_the_law_rect_and_channels_are_s2(fixed, g):
    box, a, w, h = _tab(g)
    k = SL.stroke_width(g)
    for esi in TABS:
        for state in (0, 1, 2):
            canvas, native = fixed.draw(esi, w, h, g, state)
            assert native[:2] == (0x14, -0x14), (g, hex(esi), native)
            for x in (w // 4, w // 2, 3 * w // 4):         # off the corner chamfers thunk_btn_devfill re-punches
                assert _face(canvas, h, x) == list(range(h)), (g, hex(esi), state, x, h)
            top, bottom = a[1] - (box[1] + k), (box[3] - k) - (a[1] + len(_face(canvas, h, w // 2)))
            assert top == bottom == SL.scale_px(2, g), (g, top, bottom)


def test_g16_draws_natively(fixed, deployed):
    """g = 16: no 2D zoom (thunk_btn_shrink's gate), so the pin never fires; identical to the deployed chain."""
    for esi in TABS:
        a = fixed.draw(esi, 0x12C, 0x14, 16)
        assert a == deployed.draw(esi, 0x12C, 0x14, 16)
        assert a[1][1:] == (-0x14, 0x12C) and _face(a[0], 0x14, 0x96) == list(range(0x14))


# ==== the real chain: deployed reproduces the shots; fixed predicts them ===============================================
@pytest.mark.parametrize("shot", SHOTS, ids=[s[0] for s in SHOTS])
def test_real_shots(fixed, deployed, shot):
    name, g, esi, x, box_top, measured = shot
    box, a, w, h = _tab(g)
    dy = box_top - box[1]                                  # the shot's console region offset
    k = SL.stroke_width(g)
    dep = _face(deployed.draw(esi, w, h, g)[0], h, w // 2)
    assert (a[1] + dy, a[1] + dy + len(dep)) == measured, (name, len(dep))
    new = _face(fixed.draw(esi, w, h, g)[0], h, w // 2)
    assert (a[1] + dy, a[1] + dy + len(new)) == (a[1] + dy, a[3] + dy)
    t_dep, b_dep = a[1] - (box[1] + k), (box[3] - k) - (a[1] + len(dep))
    assert t_dep == SL.scale_px(2, g)
    assert b_dep == {40: 7, 22: 4, 25: 3}[g], (name, b_dep)     # the shots' bottom channels (T 5 / 3 / 3)
    png = SHOT_DIR / f"terranx_pracx_{name}.png"
    if not png.exists():
        return
    from PIL import Image
    img = Image.open(png).convert("RGB")
    col = ["%02x%02x%02x" % img.getpixel((x, y)) for y in range(box[1] + dy, box[3] + dy)]
    face = [box[1] + dy + i for i, c in enumerate(col) if c in FACE_COLOURS]
    assert (min(face), max(face) + 1) == measured, name
    assert col[0] == col[k - 1] == col[-1] == col[-k] == "314e2c", (name, col[:k], col[-k:])   # the box strokes


# ==== every other FlatButton is untouched ==============================================================================
OTHER_BUTTONS = (
    TABS[0] - 0xB4C, TABS[0] + 4, TABS[1] + 0xB4C, TABS[3] + 0xB4C,     # neighbours of the four
    0x885F38 + 0x80, 0x885F38 + 0x5384, 0x885F38 + 0xE7D0,              # ReportIf faction / kind tabs, governor rows
    HUD_MI[0], HUD_MI[1], 0x7B0CB8, 0x7B1804, HUD_MI[0] - 0xB4C,       # MainWin M / I (fix 22b), TOOLBAR / MENU, below M
    0x8C78C4,                                                           # TutWin + 0xA5C
    COUNCIL[0] - 0xB4C, COUNCIL[0] - 1, COUNCIL[-1] + 0xB4C,            # around the CouncilWin six (fix 21)
    0x82B988, 0x82C4D4, 0x82D020, 0x82DB6C, 0x82E6B8, 0x82F204,         # faction picker text buttons: same art, vanilla 0x16
    NETWIN[0] - 0xB4C, NETWIN[1] + 0xB4C,                               # around the NetWin lobby pair (pinned: fix 27)
)


@pytest.mark.parametrize("g", (17, 19, 22, 25, 33, 40))
def test_non_tab_buttons_draw_identically(fixed, deployed, g):
    """Differential over the whole FlatButton pipeline: every non-tab button, at heights where the CEIL inverse is
    exact (fl(20g/16)) and where it overshoots (the tab law face), draws byte-identically with and without the pin."""
    _box, _a, w, law_h = _tab(g)
    for esi in OTHER_BUTTONS:
        for h in sorted({SL.popup_scale_floor(20, g), law_h, SL.popup_scale_floor(22, g)}):
            assert fixed.draw(esi, w, h, g) == deployed.draw(esi, w, h, g), (g, hex(esi), h)


def test_tab_draw_differs_only_where_the_ceil_overshoots(fixed, deployed):
    for g in range(17, 41):
        _box, _a, w, h = _tab(g)
        same = fixed.draw(TABS[2], w, h, g) == deployed.draw(TABS[2], w, h, g)
        assert same == (SL.btn_native_dim(h, g) == 20), g


# ==== t_rw_tabbtn_nath in isolation: contract ============================================================================
def _pin_run(chain: Chain, esi: int, g: int, pending: int, eflags: int):
    mu = chain.mu
    chain.w32(G_VA, g)
    chain.w32(0xA0C534, pending)
    chain.w32(G_BTN_NATIVE_H, 21)
    mu.mem_write(esi, b"\0" * 0xB4C)
    chain.w32(esi + 0x4C8, -21)
    stk = HEAP + 0x90000
    regs = {UC_X86_REG_EAX: 0xA1A1A1A1, UC_X86_REG_EBX: 0xB2B2B2B2, UC_X86_REG_ECX: 0xC3C3C3C3,
            UC_X86_REG_EDX: 0xD4D4D4D4, UC_X86_REG_EDI: 0xE5E5E5E5, UC_X86_REG_EBP: 0xF6F6F6F6,
            UC_X86_REG_ESI: esi, UC_X86_REG_ESP: stk, UC_X86_REG_EFLAGS: eflags}
    for r, v in regs.items():
        mu.reg_write(r, v)
    chain.stop_native = True
    try:
        mu.emu_start(chain.pin_va, 0, count=200)
    finally:
        chain.stop_native = False
    assert mu.reg_read(UC_X86_REG_EIP) == NATIVE_RESUME
    for r, v in regs.items():
        got = mu.reg_read(r)
        if r == UC_X86_REG_EFLAGS:
            assert got & 0x8D5 == v & 0x8D5, "flags preserved"
        else:
            assert got == v, r
    return chain.r32(G_BTN_NATIVE_H), chain.r32(esi + 0x4C8)


CONTRACT_MISSES = (TABS[0] + 0xB4C, TABS[0] - 1, TABS[3] + 1, 0x82B988,
                   SL.COUNCIL_BTN_RANGE[0] - 1, SL.COUNCIL_BTN_RANGE[1], SL.COUNCIL_BTN_RANGE[0] - 0xB4C,
                   HUD_MI[0], HUD_MI[1], HUD_MI[0] - 1, HUD_MI[0] + 1, HUD_MI[1] + 1, HUD_MI[0] - 0xB4C, HUD_MI[1] + 0xB4C,
                   NETWIN[0] - 1, NETWIN[0] + 1, NETWIN[1] - 1, NETWIN[1] + 1, NETWIN[0] - 0xB4C, NETWIN[1] + 0xB4C)


def test_pin_contract(fixed):
    for eflags in (0x202, 0x2C7 | 0x800):
        for g in (16, 17, 40):
            for pending in (0, 1):
                for esi in TABS + COUNCIL + NETWIN + CONTRACT_MISSES:
                    got = _pin_run(fixed, esi, g, pending, eflags)
                    pinned = pending == 1 and g > 16 and SL.flatbutton_nath_pinned(esi)
                    assert SL.flatbutton_nath_pinned(esi) == (esi in TABS + COUNCIL + NETWIN), hex(esi)
                    assert got == ((0x14, -0x14) if pinned else (21, -21)), (eflags, g, pending, hex(esi))


# ==== fix 21: the CouncilWin buttons ====================================================================================
#: the 2560x1440 council session shot (work\screenshots\council_20261010\base, gitignored; the measured rows are pinned
#: here): the OK button's face is the run of 1c5063 / 675bb5 down column x from row 1231, then 2 rows of the backdrop.
COUNCIL_SHOT = ("council_20261010/base/terranx_pracx_2560x1440_20261010-194955.png", 30, (900, 1150, 1600), 1231, 36)


@pytest.mark.parametrize("g", range(17, 41))
def test_law_council_height_overshoots_exactly_where_the_ceil_inverse_says(g):
    """council_btn_h = s(23) - s(3) is fl(20g/16) or one more; where it is one more the CEIL inverse is 21 and the
    unpinned zoom leaves the bottom rows key; the pinned source (0x14 = the art rows) fills it at every g."""
    h, s20 = SL.council_btn_h(g), SL.popup_scale_floor(20, g)
    assert h in (s20, s20 + 1)
    over = g in (19, 21, 23, 26, 30, 31, 35, 37, 39)
    assert (h > s20) == over and SL.btn_native_dim(h, g) == (21 if over else 20)
    assert (SL.flatbutton_zoom_face_rows(h, SL.btn_native_dim(h, g)) < h) == over
    if over:                                               # the unpinned face's shortfall: 2 rows / 1 row
        short = h - SL.flatbutton_zoom_face_rows(h, 21)
        assert short == (2 if g in (26, 30, 31, 35, 37, 39) else 1 if g in (19, 21, 23) else None), (g, short)
    for obj in COUNCIL:
        assert SL.flatbutton_zoom_src_h(obj, h, g) == SL.COUNCIL_BTN_NATIVE_H == SL.BTN_BAR_NATIVE_H
        assert SL.flatbutton_zoom_face_rows(h, SL.flatbutton_zoom_src_h(obj, h, g)) == h
    assert SL.council_btn_h(16) == 0x14


@pytest.mark.parametrize("g", range(17, 41))
def test_council_face_fills_its_window(fixed, fix19, g):
    """The real chain, all six objects and three draw states: the face fills the window; fix 19's chain is short by
    exactly the CEIL-inverse overshoot and identical everywhere else."""
    h = SL.council_btn_h(g)
    w = SL.popup_scale_floor(COUNCIL_W, g)
    for esi in COUNCIL:
        for state in (0, 1, 2):
            canvas, native = fixed.draw(esi, w, h, g, state)
            assert native[:2] == (0x14, -0x14), (g, hex(esi), native)
            for x in (w // 4, w // 2, 3 * w // 4):
                assert _face(canvas, h, x) == list(range(h)), (g, hex(esi), state, x, h)
            old = fix19.draw(esi, w, h, g, state)
            if SL.btn_native_dim(h, g) == 20:
                assert old == (canvas, native), (g, hex(esi), state)
            else:
                assert len(_face(old[0], h, w // 2)) == SL.flatbutton_zoom_face_rows(h, 21) < h, (g, hex(esi))


@pytest.mark.parametrize("g", (17, 19, 22, 25, 30, 33, 40))
def test_fix21_touches_only_the_council_buttons(fixed, fix19, g):
    """Differential against fix 19 as shipped: the tabs and every other button (incl. the faction picker's vanilla-0x16
    default-art buttons and the NetWin / HUD default-art buttons) draw byte-identically, at the floor heights of 20 and
    22 and at the composite heights the census measured."""
    _box, _a, w, tab_h = _tab(g)
    hs = sorted({SL.popup_scale_floor(20, g), SL.popup_scale_floor(22, g), tab_h, SL.council_btn_h(g)})
    for esi in TABS + OTHER_BUTTONS:
        for h in hs:
            assert fixed.draw(esi, w, h, g) == fix19.draw(esi, w, h, g), (g, hex(esi), h)


def test_council_g16_draws_natively(fixed, deployed):
    for esi in COUNCIL:
        a = fixed.draw(esi, COUNCIL_W, 0x14, 16)
        assert a == deployed.draw(esi, COUNCIL_W, 0x14, 16)
        assert _face(a[0], 0x14, COUNCIL_W // 2) == list(range(0x14))


def test_council_shot(fixed, fix19):
    """The 2560x1440 council session shot: fix 19's chain reproduces its 36-row face in the 38-row window; fix 21
    fills all 38."""
    name, g, xs, top, measured = COUNCIL_SHOT
    h, w = SL.council_btn_h(g), SL.popup_scale_floor(COUNCIL_W, g)
    assert h == 38
    assert len(_face(fix19.draw(COUNCIL[4], w, h, g)[0], h, w // 2)) == measured
    assert len(_face(fixed.draw(COUNCIL[4], w, h, g)[0], h, w // 2)) == h
    png = SHOT_DIR / name
    if not png.exists():
        return
    from PIL import Image
    img = Image.open(png).convert("RGB")
    for x in xs:
        col = ["%02x%02x%02x" % img.getpixel((x, y)) for y in range(top, top + h)]
        face = [i for i, c in enumerate(col) if c in FACE_COLOURS]
        assert face == list(range(measured)), (x, col)
        assert col[measured] == col[measured + 1] == "0c0c10", (x, col[measured:])


# ==== fix 23 / 23b: the HUD M / I / TOOLBAR column (hud_mi_column / hud_mi_btn_rect / hud_toolbar_rect) ===============
MAINWIN = 0x7AE820
SEEDSCALE_SITE, SEEDSCALE_RET, BUFFER_LOAD_PCX = 0x459E8A, 0x459E8F, 0x5D7DE0
SW_VA, SH_VA = 0x9B7B1C, 0x9B7B20
T_HUD_MI_SQUARE = 0xA0C000 + 0x2320          # pcave2 0x2320 (patches.yaml symbol t_hud_mi_square)
SLOT = 0x50                                  # its slot, 0x2320..0x2370
TOOLBAR = SL.HUD_TOOLBAR_OBJ                 # MainWin FlatButtons[2] 0x7B0CB8: the scenario editor's, in the M / I column
COLUMN = HUD_MI + (TOOLBAR,)
BTN_IDS = {HUD_MI[0]: 0x3E8, HUD_MI[1]: 0x3E9, TOOLBAR: 0x3EA}
#: the five dwords the thunk may write: M.l, M.t, I.l, I.b, TOOLBAR.l
MI_WRITES = {MAINWIN + o for o in (0xA2C, 0xA30, 0xA3C, 0xA48, 0xA4C)}
#: F32: t_hud_btnpair (seedscale v2's tail, before t_hud_mi_square) writes WORLD.r / DETAIL.l; the pre-fix-23 mutant tail
#: (push Buffer_load_pcx) skips it, so the table compare of test_hud_mi_windows_real_order excludes them too.
BTNPAIR_WRITES = {MAINWIN + 0xA94, MAINWIN + 0xA9C}
#: MainWin_build's seed stores of the centre console rect +0xDA0 (mov [esi+off], imm32), the derivation block that builds
#: M / I / TOOLBAR from it (no calls), and BaseButton_init's arg loads (stop at the call): I, M, then TOOLBAR.
DA0_STORES = (0x459912, 0x45991C, 0x459926, 0x459930)
DERIVE = (0x459A53, 0x459B7B)
ARG_SLICES = {HUD_MI[1]: (0x45A960, 0x45A995), HUD_MI[0]: (0x45A9EB, 0x45AA20), TOOLBAR: (0x45AA76, 0x45AAAB)}
#: every instruction in MainWin_build's range that names MainWin +0xA2C..+0xA58, and every abs32 of 0x7AF24C..0x7AF278
#: in the image: the derivation (pre-seedscale, native), the three arg loads, one read of I's l (+0xA3C) @0x45B491 (the
#: scenario-editor info rect's right edge, +0xD74 = I.l - s(3) via t_ed_info_right since fix 24: it follows the
#: column), the TutWin tour's rect centres
#: (M / I only) and the thunk's own base `mov edx, 0x7AF24C`.  A new reader of the column must be reviewed (fix 23b).
MI_READERS = (0x459B0A, 0x459B33, 0x459B39, 0x459B4B, 0x459B51, 0x459B63, 0x459B69, 0x459B95,
              0x45A960, 0x45A966, 0x45A96C, 0x45A978, 0x45A9EB, 0x45A9F1, 0x45A9F7, 0x45AA03,
              0x45AA76, 0x45AA7C, 0x45AA82, 0x45AA8E, 0x45B491)
MI_ABS_REFS = (0x4BD69E, 0x4BD6A4, 0x4BD6B3, 0x4BD6BB, 0x4BD719, 0x4BD71F, 0x4BD72E, 0x4BD736, 0xA0E334)
#: the rejected / superseded thunks (resolved bytes: g_popup_scale_num 0x668740, Buffer_load_pcx 0x5D7DE0) -- mutants:
#: FIX23 = fix 23 as built (M / I left-anchored squares, TOOLBAR left at the floor of each edge: 1 px wider);
#: LEFT_COLUMN = the audit prototype (the whole column left-anchored, l = fl(734g/16); M / I top-anchored).
FIX23_THUNK = bytes.fromhex(
    "9c608b0d4087660083f9107e366bc914c1f904a14cf27a0001c8a354f27a00a150f27a0001c8a358f27a00a15cf27a0001c8a364f27a00"
    "a160f27a0001c8a368f27a00619d68e07d5d00c3")
LEFT_COLUMN_THUNK = bytes.fromhex(
    "9c608b0d4087660083f9107e326bc914c1f904ba4cf27a008b0201c88942088b420401c889420c8b421001c88942188b421401c889421c"
    "8b422001c8894228619d68e07d5d00c3")
#: where fl(754g/16) - fl(734g/16) is s(20) + 1: fix 23's TOOLBAR stuck out on the right; the column's left edge moves
#: right by 1 vs the floor of 734.  Where fl(95g/16) - fl(75g/16) is s(20) + 1: M's top moves down by 1.
COLUMN_WIDE_G = {17, 18, 19, 25, 26, 27, 33, 34, 35}
M_TALL_G = {23, 26, 27, 29, 30, 31, 39}
#: the real centre painter's console inner frame (MainWin_draw_center_mode 0x45BC50 after the real MainWin_build, mode
#: 0x3E8; audit 23 real-image harness, cross-checked on the shots below): g -> (FT inner top stroke row, FR inner right
#: stroke col, FB inner bottom stroke row), MainWin canvas coordinates.
FRAMES = {16: (70, 758, 167), 17: (74, 806, 178), 18: (78, 853, 189), 19: (83, 901, 199), 20: (87, 948, 210),
          21: (91, 996, 220), 22: (96, 1043, 231), 23: (100, 1091, 241), 24: (105, 1138, 252), 25: (110, 1184, 261),
          26: (114, 1232, 272), 27: (119, 1279, 282), 28: (123, 1327, 293), 29: (127, 1374, 303), 30: (132, 1422, 314),
          31: (136, 1469, 324), 32: (141, 1517, 335), 33: (145, 1564, 345), 34: (149, 1611, 356), 35: (154, 1659, 366),
          36: (158, 1706, 377), 37: (162, 1754, 387), 38: (167, 1801, 398), 39: (171, 1849, 408), 40: (176, 1896, 419)}
#: the vanilla-symmetric pairs that held BEFORE fix 23 (b7043354, real image: the visible faces, which fell short where
#: the floored window was one more than s(20)): M corner = M top inset == M right inset; I corner = I right == I bottom;
#: TOOLBAR gaps = M-to-TOOLBAR == TOOLBAR-to-I.  None may break; the law's own sets are pinned.
PAIRS_PRE_FIX23 = {"M": {16, 18, 25, 34}, "I": {16, 21, 23, 28, 29, 30, 31, 32, 37},
                   "gap": {16, 19, 22, 25, 28, 32, 35, 38}}
PAIRS_LAW = {"M": {16, 18, 25, 26, 27, 29, 31, 34}, "I": {16, 21, 23, 28, 29, 30, 31, 32, 37, 39},
             "gap": {16, 19, 22, 23, 25, 26, 28, 29, 32, 35, 38, 39}}
#: (shot, g, column x (off the caption and the corner chamfers), deployed window left (screen x), M window top,
#: I window top, the deployed (pre-fix-23) M h, I h, M w = I w, the face rows both show).  Measured on the real shots
#: (work\\screenshots, gitignored; pinned here, the PNG cross-check runs when the shot is present).  The tops do not move
#: at these g; the shots' faces are already s(20) rows.  Predictions (fix 23b): 1080p M / I at (1265, 830) / (1265, 923)
#: 27x27, I's window drops row 950, which the shot already shows as a key (transparent) row: nothing visible moves;
#: 900p M / I at (1050, 695) / (1050, 771) 22x22: both faces lose the LEFT column x = 1049 (the right edge and its 5-px inset
#: to the frame stay; fix 23 dropped the right column 1071); I's window also drops row 793, which was ALREADY a key row
#: in the shot (its face is rows 771..792), so I's visible face loses no row; 4K unchanged (M (2475, 1705), I (2475,
#: 1875), 50x50).
HUD_MI_SHOTS = (
    tuple((f"1920x1080_20261022-{t}", 22, 1268, 1265, 830, 923, 27, 28, 27, 27)
          for t in ("205531", "205605", "205616", "205618"))
    + tuple((f"1600x900_20261022-{t}", 18, 1052, 1049, 695, 771, 22, 23, 23, 22) for t in ("210123", "210127"))
    + tuple((f"3840x2160_20261022-{t}", 40, 2479, 2475, 1705, 1875, 50, 50, 50, 50)
            for t in ("204321", "204324", "204405", "204501")))
FRAMELESS_SHOTS = {"3840x2160_20261022-204501"}     # the centre console's frame strokes are not on screen in this shot


def _floor_edges(obj: int, g: int):
    """The pre-fix-23 window: thunk_hud_seedscale's floor of each vanilla edge alone (the mutant)."""
    rect = SL.HUD_TOOLBAR_RECT if obj == TOOLBAR else SL.HUD_MI_BTN_RECTS[obj]
    return tuple(v * g >> 4 for v in rect) if g > 16 else rect


def _law(obj: int, g: int):
    return SL.hud_toolbar_rect(g) if obj == TOOLBAR else SL.hud_mi_btn_rect(obj, g)


def _fills(chain: Chain, esi: int, w: int, h: int, g: int, state: int) -> bool:
    canvas = chain.draw(esi, w, h, g, state)[0]
    cols = all(_face(canvas, h, x) == list(range(h)) for x in (w // 4, w // 2, 3 * w // 4))
    rows = all(canvas[y * STRIDE + 3:y * STRIDE + w - 3].count(KEY) == 0 for y in (h // 4, h // 2, 3 * h // 4))
    return cols and rows


def _pairs(m, i, t, g):
    """The three pairs on windows whose faces fill (squares) against the real painter's frame: held or not."""
    ft, fr, fb = FRAMES[g]
    return {"M": m[1] - ft - 1 == fr - m[2], "I": fr - i[2] == fb - i[3], "gap": t[1] - m[3] == i[1] - t[3]}


class SeedChain:
    """The baked image's own bytes, in MainWin_build's order, for the M / I / TOOLBAR windows: the +0xDA0 seed stores,
    the derivation 0x459A53..0x459B7B, the seedscale call-redirect from 0x459E8A (its tail t_hud_mi_square, then
    Buffer_load_pcx = stop), BaseButton_init's arg loads for I (0x45A960), M (0x45A9EB) and TOOLBAR (0x45AA76) up to the
    call."""

    def __init__(self, image: bytes):
        pe = pefile.PE(data=image)
        ib = pe.OPTIONAL_HEADER.ImageBase
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(HEAP, 0x200000)
        self.img = image
        self.slot = bytes(mu.mem_read(T_HUD_MI_SQUARE, SLOT))
        assert mu.mem_read(SEEDSCALE_SITE, 1) == b"\xE8"
        self.seedscale = SEEDSCALE_SITE + 5 + struct.unpack("<i", mu.mem_read(SEEDSCALE_SITE + 1, 4))[0]
        # seedscale v2 (F32): 139 B in its 0x4D00..0x4D90 slot, tail push t_hud_btnpair, whose own tail pushes
        # t_hud_mi_square (the chain seedscale -> t_hud_btnpair -> t_hud_mi_square -> Buffer_load_pcx).
        body = bytes(mu.mem_read(self.seedscale, 0x90))
        k = body.index(b"\x61\x9D\x68")
        assert body[k + 7] == 0xC3, "seedscale ends `popad; popfd; push imm32; ret`"
        self.body_len = k + 8
        self.own_tail = struct.unpack("<I", body[k + 3:k + 7])[0]
        btnpair = bytes(mu.mem_read(self.own_tail, 0x40))
        j = btnpair.index(b"\x61\x9D\x68")
        assert struct.unpack("<I", btnpair[j + 3:j + 7])[0] == T_HUD_MI_SQUARE, "t_hud_btnpair tail -> t_hud_mi_square"
        self.tail_va = self.seedscale + self.body_len - 5     # the push imm32 (`68 imm32 C3` ends the thunk)
        self.da0 = []
        for va in DA0_STORES:
            ins = bytes(mu.mem_read(va, 10))
            assert ins[:2] == b"\xC7\x86", hex(va)
            self.da0.append((struct.unpack("<i", ins[2:6])[0], struct.unpack("<i", ins[6:10])[0]))
        assert [o for o, _v in self.da0] == [0xDA0, 0xDA4, 0xDA8, 0xDAC]

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def run(self, sw: int, sh: int, pre_fix23: bool = False, thunk: bytes = None):
        """Returns (g, {obj: BaseButton_init (x, y, w, h)}, MainWin +0xA00..+0xE00 dwords).  thunk: a mutant tail in
        the slot instead of the image's own bytes."""
        mu = self.mu
        tail = struct.pack("<I", BUFFER_LOAD_PCX if pre_fix23 else self.own_tail)
        if bytes(mu.mem_read(self.tail_va, 4)) != tail:
            mu.mem_write(self.tail_va, tail)
            mu.ctl_remove_cache(self.seedscale, self.seedscale + self.body_len)   # unicorn keeps the translated block
        assert bytes(mu.mem_read(self.tail_va, 4)) == tail
        slot = self.slot if thunk is None else thunk + bytes(SLOT - len(thunk))
        if bytes(mu.mem_read(T_HUD_MI_SQUARE, SLOT)) != slot:
            mu.mem_write(T_HUD_MI_SQUARE, slot)
            mu.ctl_remove_cache(T_HUD_MI_SQUARE, T_HUD_MI_SQUARE + SLOT)
        mu.mem_write(MAINWIN, b"\0" * 0x26000)
        for off, v in self.da0:
            mu.mem_write(MAINWIN + off, struct.pack("<i", v))
        for a, v in ((SW_VA, sw), (SH_VA, sh), (G_VA, 0)):
            mu.mem_write(a, struct.pack("<i", v))
        frame = HEAP + 0x100000
        mu.reg_write(UC_X86_REG_ESI, MAINWIN)
        mu.reg_write(UC_X86_REG_EBP, frame)
        mu.reg_write(UC_X86_REG_ESP, frame - 0x400)
        mu.emu_start(DERIVE[0], DERIVE[1], count=200)
        sp = frame - 0x800
        mu.mem_write(sp, struct.pack("<I", SEEDSCALE_RET))
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ESI, 0x12345678)                # seedscale must not need the caller's esi
        mu.emu_start(self.seedscale, BUFFER_LOAD_PCX, count=200_000)
        assert mu.reg_read(UC_X86_REG_ESP) == sp and mu.reg_read(UC_X86_REG_ESI) == 0x12345678
        g = self.r32(G_VA)
        args = {}
        for obj, (a, b) in ARG_SLICES.items():
            mu.reg_write(UC_X86_REG_ESI, MAINWIN)
            mu.reg_write(UC_X86_REG_ESP, frame - 0x400)
            mu.emu_start(a, b, count=100)
            st = struct.unpack("<8i", mu.mem_read(mu.reg_read(UC_X86_REG_ESP), 32))
            assert st[1] == BTN_IDS[obj] and st[6] == MAINWIN, st
            args[obj] = st[2:6]
        table = struct.unpack("<256i", mu.mem_read(MAINWIN + 0xA00, 0x400))
        return g, args, table


@pytest.fixture(scope="module")
def seedchain(baked):
    return SeedChain(baked)


def _res(g: int):
    return 64 * g, 48 * g                                 # 1024 x 768 scaled: the screen whose g is exactly g


def _rects(args):
    return {o: (x, y, x + w, y + h) for o, (x, y, w, h) in args.items()}


@pytest.mark.parametrize("g", range(16, 41))
def test_law_hud_mi_column(g):
    """hud_mi_column / hud_mi_btn_rect / hud_toolbar_rect: vanilla at g = 16; else ONE column -- M, I and TOOLBAR share
    the left and the right edge -- right-anchored at fl(754g/16) (the right edge every pre-fix-23 window had) and s(20)
    wide; M / I are s(20) squares anchored at their TOOLBAR-facing edges (M.b = fl(95g/16), I.t = fl(143g/16)), whose
    CEIL inverse is exactly the art's 20 rows / cols (no pin); TOOLBAR keeps its floored rows."""
    m, i, t = (_law(o, g) for o in COLUMN)
    assert m[0] == i[0] == t[0] and m[2] == i[2] == t[2] and (m[0], m[2]) == SL.hud_mi_column(g)
    for obj in HUD_MI:
        assert not SL.flatbutton_nath_pinned(obj)
    if g == 16:
        assert (m, i, t) == (SL.HUD_MI_BTN_RECTS[HUD_MI[0]], SL.HUD_MI_BTN_RECTS[HUD_MI[1]], SL.HUD_TOOLBAR_RECT)
        assert SL.hud_mi_btn_h(HUD_MI[0], g) == SL.hud_mi_btn_h(HUD_MI[1], g) == 0x14
        return
    s20 = SL.popup_scale_floor(20, g)
    fm, fi, ft = (_floor_edges(o, g) for o in COLUMN)
    assert m[2] == fm[2] == fi[2] == ft[2] and m[2] - m[0] == s20                  # right edge kept, s(20) wide
    assert m[3] - m[1] == i[3] - i[1] == s20 == SL.hud_mi_btn_h(HUD_MI[0], g) == SL.hud_mi_btn_h(HUD_MI[1], g)
    assert m[3] == fm[3] and i[1] == fi[1] and t[1::2] == ft[1::2]                  # the TOOLBAR-facing edges, its rows
    assert m[0] - fm[0] == int(g in COLUMN_WIDE_G) and m[1] - fm[1] == int(g in M_TALL_G), g
    assert 0 <= fi[3] - i[3] <= 1
    assert SL.btn_native_dim(s20, g) == SL.BTN_BAR_NATIVE_H == SL.flatbutton_zoom_src_h(HUD_MI[0], s20, g)
    assert SL.flatbutton_zoom_face_rows(s20, SL.btn_native_dim(s20, g)) == s20


def test_law_hud_column_pairs():
    """The anchoring choice against the real painter's frame (FRAMES): every vanilla-symmetric pair that held before
    fix 23 still holds (M corner, I corner, TOOLBAR gaps), and the law's sets are pinned.  The rejected anchorings each
    break one: left-anchoring the column (fix 23 / the audit prototype) puts the extra px into the right inset and loses
    the M corner at g 18 / 25 / 34; anchoring I at its bottom loses the I corner at 23 and the TOOLBAR gaps at
    19 / 22 / 35 / 38."""
    held = {k: set() for k in PAIRS_LAW}
    for g in range(16, 41):
        for k, v in _pairs(*(_law(o, g) for o in COLUMN), g).items():
            if v:
                held[k].add(g)
    assert held == PAIRS_LAW
    assert all(PAIRS_PRE_FIX23[k] <= held[k] for k in held)
    fl = lambda v, g: v * g >> 4                                      # noqa: E731

    def broken(rects):
        out = {k: set() for k in PAIRS_LAW}
        for g in range(17, 41):
            for k, v in _pairs(*rects(g), g).items():
                if not v and g in PAIRS_PRE_FIX23[k]:
                    out[k].add(g)
        return out

    def left(g):
        s, l = fl(20, g), fl(734, g)
        return ((l, fl(75, g), l + s, fl(75, g) + s), (l, fl(143, g), l + s, fl(143, g) + s), (l, fl(100, g), l + s, fl(138, g)))

    def i_bottom(g):
        s, r = fl(20, g), fl(754, g)
        return ((r - s, fl(95, g) - s, r, fl(95, g)), (r - s, fl(163, g) - s, r, fl(163, g)), (r - s, fl(100, g), r, fl(138, g)))
    assert broken(left) == {"M": {18, 25, 34}, "I": set(), "gap": set()}
    assert broken(i_bottom) == {"M": set(), "I": {23}, "gap": {19, 22, 35, 38}}


def test_hud_mi_square_readers_are_known(baked):
    """Nothing else reads the column: every MainWin_build instruction naming +0xA2C..+0xA58 (M, I, TOOLBAR) and every
    abs32 of 0x7AF24C..0x7AF278 in the image is in the reviewed list."""
    import capstone
    from capstone import x86
    pe = pefile.PE(data=baked)
    ib = pe.OPTIONAL_HEADER.ImageBase
    img = pe.get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    hits = [i.address for i in md.disasm(img[0x459680 - ib:0x45C000 - ib], 0x459680)
            if any(o.type == x86.X86_OP_MEM and 0xA2C <= (o.mem.disp & 0xFFFFFFFF) <= 0xA58 for o in i.operands)]
    assert tuple(hits) == MI_READERS, [hex(h) for h in hits]
    refs = []
    for v in range(0x7AF24C, 0x7AF27C):
        k, j = struct.pack("<I", v), img.find(struct.pack("<I", v))
        while j >= 0:
            refs.append(ib + j)
            j = img.find(k, j + 1)
    assert tuple(sorted(refs)) == MI_ABS_REFS, [hex(r) for r in sorted(refs)]


@pytest.mark.parametrize("g", range(16, 41))
def test_hud_mi_windows_real_order(seedchain, g):
    """The image's own bytes in MainWin_build's order hand BaseButton_init exactly the law for M, I and TOOLBAR -- one
    column, flush on both sides; the rest of the 0x100-dword MainWin table (+0xA00..+0xE00, incl. every derived rect)
    is the pre-fix-23 one, and only the five written dwords may differ -- exactly where the old windows were not the
    law.  The pre-fix-23 tail hands over the floor of each edge (the mutant)."""
    sw, sh = _res(g)
    got_g, args, table = seedchain.run(sw, sh)
    old_g, old_args, old_table = seedchain.run(sw, sh, pre_fix23=True)
    assert got_g == old_g == g
    got, old = _rects(args), _rects(old_args)
    for obj in COLUMN:
        assert got[obj] == _law(obj, g), (g, hex(obj), args[obj])
        assert old[obj] == _floor_edges(obj, g)
    m, i, t = (got[o] for o in COLUMN)
    assert m[0] == i[0] == t[0] and m[2] == i[2] == t[2], (g, m, i, t)        # three-way column flush
    for k, (n, o) in enumerate(zip(table, old_table)):
        va = MAINWIN + 0xA00 + 4 * k
        if va not in MI_WRITES | BTNPAIR_WRITES:
            assert n == o, (g, hex(va), n, o)
    changed = [v for k, v in enumerate(table) if MAINWIN + 0xA00 + 4 * k not in BTNPAIR_WRITES] != \
        [v for k, v in enumerate(old_table) if MAINWIN + 0xA00 + 4 * k not in BTNPAIR_WRITES]
    assert changed == any(_floor_edges(o, g) != _law(o, g) for o in COLUMN), g


def test_hud_column_mutants_fail(seedchain):
    """Mutation check on the real order: fix 23's thunk (TOOLBAR left at the floor of each edge) breaks the three-way
    flush exactly at COLUMN_WIDE_G (its right edge 1 px past M / I); the left-anchored column (the audit prototype)
    is flush but is not the law wherever an edge was dropped on the other side (COLUMN_WIDE_G | M_TALL_G)."""
    flush_broken, not_law = set(), set()
    for g in range(16, 41):
        _g, args, _t = seedchain.run(*_res(g), thunk=FIX23_THUNK)
        m, i, t = (_rects(args)[o] for o in COLUMN)
        if not (m[0] == i[0] == t[0] and m[2] == i[2] == t[2]):
            flush_broken.add(g)
            assert t[2] - m[2] == 1 and t[0] == m[0], (g, m, t)
        _g, args, _t = seedchain.run(*_res(g), thunk=LEFT_COLUMN_THUNK)
        r = _rects(args)
        m, i, t = (r[o] for o in COLUMN)
        assert m[0] == i[0] == t[0] and m[2] == i[2] == t[2], g
        if any(r[o] != _law(o, g) for o in COLUMN):
            not_law.add(g)
    assert flush_broken == COLUMN_WIDE_G, sorted(flush_broken)
    assert not_law == COLUMN_WIDE_G | M_TALL_G, sorted(not_law)
    _g, args, _t = seedchain.run(*_res(22))                          # the image's own bytes are restored
    assert all(_rects(args)[o] == _law(o, 22) for o in COLUMN)


def test_t_hud_mi_square_contract(seedchain):
    """t_hud_mi_square alone (from seedscale's ret): every register and the arithmetic flags preserved, the frame
    untouched, tail to Buffer_load_pcx; only the five column dwords change, at g > 16: M.l / I.l / TOOLBAR.l = r - s(20),
    M.t = M.b - s(20), I.b = I.t + s(20)."""
    import random
    rnd = random.Random(23)
    mu = seedchain.mu
    seedchain.run(*_res(22))                                         # the image's own slot bytes
    for case in range(300):
        g = rnd.choice(list(range(0, 50)) + [16, 17, 40, -1, 0x3FFFFFF])
        rect = [rnd.randint(-5000, 5000) for _ in range(12)]
        mu.mem_write(MAINWIN + 0xA2C, struct.pack("<12i", *rect))
        mu.mem_write(G_VA, struct.pack("<i", g))
        sp = HEAP + 0x180000
        regs = {r: rnd.getrandbits(32) for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                                                    UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESI)}
        regs[UC_X86_REG_ESP] = sp
        regs[UC_X86_REG_EFLAGS] = 0x202 | (rnd.getrandbits(12) & 0x8D5)
        mu.mem_write(sp, struct.pack("<I", SEEDSCALE_RET))
        for r, v in regs.items():
            mu.reg_write(r, v)
        mu.emu_start(T_HUD_MI_SQUARE, BUFFER_LOAD_PCX, count=100)
        assert mu.reg_read(UC_X86_REG_EIP) == BUFFER_LOAD_PCX
        for r, v in regs.items():
            got = mu.reg_read(r)
            assert (got & 0x8D5 == v & 0x8D5) if r == UC_X86_REG_EFLAGS else got == v, (case, r)
        assert struct.unpack("<I", mu.mem_read(sp, 4))[0] == SEEDSCALE_RET
        out = list(struct.unpack("<12i", mu.mem_read(MAINWIN + 0xA2C, 48)))
        want = list(rect)
        if g > 16:
            s20 = (20 * g) >> 4                                # imul ecx, ecx, 0x14; sar ecx, 4 (20g < 2^31 here)
            for base in (0, 4, 8):                             # M l,t,r,b = [0..3], I = [4..7], TOOLBAR [8..11]
                want[base] = rect[base + 2] - s20
            want[1] = rect[3] - s20                            # M t = b - s(20)
            want[7] = rect[5] + s20                            # I b = t + s(20)
        assert out == want, (case, g, rect, out)


@pytest.mark.parametrize("g", range(17, 41))
def test_hud_mi_faces_fill_equal_square(fixed, seedchain, g):
    """The real chain at the windows the image's own bytes hand BaseButton_init: M and I faces fill their windows in
    all three draw states, the two canvases are identical, the windows are squares, and TOOLBAR shares their column
    (its width's CEIL inverse is the vanilla 20 too)."""
    _g, args, _t = seedchain.run(*_res(g))
    (mx, my, mw, mh), (ix, iy, iw, ih), (tx, ty, tw, th) = (args[o] for o in COLUMN)
    assert mw == mh == iw == ih == tw == SL.popup_scale_floor(20, g) and mx == ix == tx
    assert SL.btn_native_dim(tw, g) == 20
    for state in (0, 1, 2):
        cm, nm = fixed.draw(HUD_MI[0], mw, mh, g, state)
        ci, ni = fixed.draw(HUD_MI[1], iw, ih, g, state)
        assert nm[:2] == ni[:2] == (0x14, -0x14), (g, nm, ni)
        assert cm == ci, (g, state)
        assert _fills(fixed, HUD_MI[0], mw, mh, g, state) and _fills(fixed, HUD_MI[1], iw, ih, g, state)


def test_hud_mi_pre_fix23_windows_fail(fixed, seedchain):
    """Mutation check: the pre-fix-23 tail's windows (floor of each edge) fail the same guard -- M != I or a short face
    -- at every g where they are not s(20) squares (17/18/19/22/23/25/26/27/29/30/31/33/34/35/38/39), and pass where
    they are."""
    failing = set()
    for g in range(17, 41):
        _g, old, _t = seedchain.run(*_res(g), pre_fix23=True)
        (mx, my, mw, mh), (ix, iy, iw, ih) = old[HUD_MI[0]], old[HUD_MI[1]]
        ok = (mw == mh == iw == ih) and all(_fills(fixed, o, w, h, g, st) for o, w, h in
                                            ((HUD_MI[0], mw, mh), (HUD_MI[1], iw, ih)) for st in (0, 1, 2))
        if not ok:
            failing.add(g)
        square = [(r[2] - r[0], r[3] - r[1]) == (SL.popup_scale_floor(20, g),) * 2 for r in (_floor_edges(o, g) for o in HUD_MI)]
        assert ok == all(square), g
    assert failing == {17, 18, 19, 22, 23, 25, 26, 27, 29, 30, 31, 33, 34, 35, 38, 39}, sorted(failing)


@pytest.mark.parametrize("shot", HUD_MI_SHOTS, ids=[s[0] for s in HUD_MI_SHOTS])
def test_hud_mi_shots(fixed, shot):
    """The user's shots (deployed = pre-fix-23 windows): the faces are s(20) rows from the unchanged tops, which is the
    law window's height; the deployed windows are the floor of each edge (1080p I 28, 900p M / I 23 wide, I 23 high);
    on the real chain the law windows fill; the law keeps the deployed RIGHT edge (screen left + old w), so its insets
    to the console frame are the shot's.  The PNG cross-check: the shot's face rows down column x and face columns
    along row top + 4, and the frame strokes there (FRAMES) at the right / above M / below I."""
    name, g, x, left, m_top, i_top, m_h, i_h, old_w, rows = shot
    s20 = SL.popup_scale_floor(20, g)
    assert rows == s20
    dx = left - _floor_edges(HUD_MI[0], g)[0]                       # MainWin canvas -> screen
    dy = m_top - _floor_edges(HUD_MI[0], g)[1]
    for obj, top, h in zip(HUD_MI, (m_top, i_top), (m_h, i_h)):
        old, law = _floor_edges(obj, g), SL.hud_mi_btn_rect(obj, g)
        assert (old[2] - old[0], old[3] - old[1]) == (old_w, h) and law[2] - law[0] == law[3] - law[1] == rows
        assert (old[0] + dx, old[1] + dy) == (left, top) and (law[1] + dy, law[2] + dx) == (top, left + old_w)
        assert law[0] + dx == left + old_w - rows                    # 900p: the left column 1049 goes, 1071 stays
        for state in (0, 1, 2):
            assert _fills(fixed, obj, rows, rows, g, state), (name, hex(obj), state)
    assert SL.hud_toolbar_rect(g)[0::2] == SL.hud_mi_btn_rect(HUD_MI[0], g)[0::2]
    png = SHOT_DIR / f"terranx_pracx_{name}.png"
    if not png.exists():
        return
    from PIL import Image
    img = Image.open(png).convert("RGB")
    px = lambda xx, yy: "%02x%02x%02x" % img.getpixel((xx, yy))     # noqa: E731
    ft, fr, fb = FRAMES[g]
    framed = name not in FRAMELESS_SHOTS

    def stroke(coords):                                             # the first console-frame stroke pixel, or None
        return next((c for c in coords if px(*c) == "314e2c"), None)
    for obj, top, h in zip(HUD_MI, (m_top, i_top), (m_h, i_h)):
        col = [px(x, y) for y in range(top - 1, top + h + 1)]
        face = [i for i, c in enumerate(col[1:-1]) if c in FACE_COLOURS]
        assert face == list(range(rows)), (name, top, col)
        assert col[0] not in FACE_COLOURS and col[rows + 1] not in FACE_COLOURS, (name, top, col)
        row = [xx for xx in range(left - 4, left + old_w + 4) if px(xx, top + 4) in FACE_COLOURS]
        assert row == list(range(left, left + old_w)), (name, top, row)
        right = stroke((xx, top + 4) for xx in range(left + old_w, left + old_w + rows))
        assert right == ((fr + dx, top + 4) if framed else None), (name, top, right)
    above = stroke((x, yy) for yy in range(m_top - 1, m_top - 1 - rows, -1))
    below = stroke((x, yy) for yy in range(i_top + rows, i_top + 2 * rows))
    assert (above, below) == (((x, ft + dy), (x, fb + dy)) if framed else (None, None)), (name, above, below)


@pytest.mark.parametrize("g", range(16, 41))
def test_hud_mi_draw_is_the_deployed_one(fixed, deployed, g):
    """Differential against the pre-fix-19 tail (no pin at all): M and I at their law windows draw byte-identically
    at every g -- the pair is not pinned, the fill comes from the window alone."""
    for esi in HUD_MI:
        h = SL.hud_mi_btn_h(esi, g)
        for state in (0, 1, 2):
            assert fixed.draw(esi, h, h, g, state) == deployed.draw(esi, h, h, g, state), (g, hex(esi), state)
