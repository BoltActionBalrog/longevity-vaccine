"""2D-zoomed FlatButton bars: s x s corner notches in EVERY draw state (2026-10-24 wave-1 F33).

Laws (scaling_laws.py, the source of truth):
  btn_corner_notch     -- s = ceil(g/16), every state (idle / hover / pressed-lit), 9-slice and box-sprite faces;
  btn_bar_tile_height  -- v2: the zoomed art bottom is the CENTRE-NN count (2*art*orig + native - 1) // (2*native).
The defect (user shots 4K 20261024-125459 / 125503 / 125445 / 125535, 2560x1440 125656): the idle face had s x s
notches (thunk_btn_devfill re-punches them after its dither re-tile) but a lit / hovered / pressed face kept the NN
image of the art's 1-px notch -- 4K TL 2x2, TR 3x2, BL 2x3, BR 3x3; 1920x1080 / 1600x900 1x1 -- because
thunk_btn_fillcap captured only state 0 (the 9-slice family) and thunk_btn_ringfix punched only when a hover ring
edge drew (the box-sprite family: the lit HUD TOOLBAR).
Ports: thunk_btn_fillcap v3 + thunk_btn_devfill v4 + t_btn_litcorner (assemble_btn_litcorner.py), thunk_btn_ringfix
v2 (assemble_ringfix.py; its own parity: test_ringfix_parity.py).

Proof layers, all on the REAL bytes of a module-scoped bake:
  1. law: the tile height == a brute-force count of nn_center_index; the NN image of a 1-px notch never exceeds s
     (so a punch of s x s covers it: the result is exactly s x s);
  2. UNIT (Unicorn on the baked image; fill_5da9f0 the only stand-in, painting its dest rect): fillcap v3 captures
     every state (HUD MENU / COMMLINK / WORLD / DETAIL still excluded, pending-gated); devfill v4 + t_btn_litcorner on
     zoomed synthetic art == the law's reference canvas for every state, g 17..40, 20- and 22-native, notch present
     / absent per corner; register / stack contract; the capture is consumed;
  3. END TO END (netwin_lobby_emu.py: the lobby's LAUNCH GAME, a real default-art 9-slice FlatButton, through the
     real draw chain): every state and g 16..40 -> four (s, s) notches; re-dressed as a box-sprite face (the HUD
     TOOLBAR's set) -> the same; re-dressed 22-native (unpinned) -> the art stops at btn_bar_tile_height and its
     bottom notches sit there, s x s (v1's floor tile left 2x3 at g 25); the bake with devfill's state exit and
     ringfix's punch reverted in memory reproduces the user's corners (4K 2x2 / 3x2 / 2x3 / 3x3, 1080p 1x1).
     g = 16 against the pristine image: test_scaling_netwin_btnpair.py::test_e2e_g16_is_pristine (all states, both
     face kinds).

COST: two boots per worker on conftest's shared bake (~4 s); each e2e g item re-runs the builder and draws ~9 canvases (~0.4 s).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
FILL = 0x5DA9F0
KEY = 9
HUD4 = (0x7B1804, 0x7B2350, 0x7B39E8, 0x7B4534)
LAUNCH = SL.NETWIN_BTN_OBJECTS[0]


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def baked(baked_exe):
    """The bake of patches.yaml: conftest's shared, read-only `baked_exe`."""
    return Path(baked_exe)


# ============================================================================== 1. law
def _nn_art_rows(orig, native, art):
    return sum(1 for j in range(orig) if SL.nn_center_index(j, orig, native) < art)


def test_law_tile_height_is_the_centre_nn_art_bottom():
    for native in range(1, 41):
        for orig in range(1, 121):
            for art in (1, 2, 5, 19, 20, 22, 30, 44):
                assert SL.btn_bar_tile_height(orig, native, art) == min(orig, _nn_art_rows(orig, native, art)), \
                    (orig, native, art)
    assert SL.btn_bar_tile_height(55, 0, 20) == 55


def test_law_tile_height_v1_was_short_on_22_native_buttons():
    short = [g for g in range(17, 41)
             if (20 * SL.popup_scale_floor(22, g)) // SL.btn_native_dim(SL.popup_scale_floor(22, g), g)
             < SL.btn_bar_tile_height(SL.popup_scale_floor(22, g), SL.btn_native_dim(SL.popup_scale_floor(22, g), g), 20)]
    assert 25 in short, short


@pytest.mark.parametrize("g", range(16, 41))
def test_law_nn_notch_never_exceeds_s(g):
    s = SL.btn_corner_notch(g)
    assert s == (1 if g <= 16 else -(-g // 16))
    if g <= 16:
        return
    for native in (20, 22):
        for dev in range(SL.popup_scale_floor(native, g) - 1, SL.popup_scale_floor(native, g) + 3):
            for n in {native, SL.btn_native_dim(dev, g)}:
                idx = [SL.nn_center_index(j, dev, n) for j in range(dev)]
                assert idx.count(0) <= s and idx.count(n - 1) <= s, (g, native, dev, n)


# ============================================================================== 2. unit
class Img:
    def __init__(self, path, symtab):
        pe = pefile.PE(str(path))
        ib = pe.OPTIONAL_HEADER.ImageBase
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        pe.close()
        mu.mem_map(0x10000000, 0x400000)
        self.sym = symtab
        mu.mem_write(FILL, b"\xC2\x1C\x00")
        mu.hook_add(UC_HOOK_CODE, self._fill, begin=FILL, end=FILL)
        self.fills = []

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def _fill(self, mu, a, s, u):
        sp = mu.reg_read(UC_X86_REG_ESP)
        args = [self.r32(sp + 4 + 4 * i) for i in range(7)]
        buf = mu.reg_read(UC_X86_REG_ECX)
        self.fills.append((buf, args))
        if self.paint:
            _spr, _px, _py, x, y, w, h = args
            data, stride = self.r32(buf + 0x54) & 0xFFFFFFFF, self.r32(buf + 0x4A8)
            for yy in range(y, y + h):
                mu.mem_write(data + yy * stride + x, bytes([0x40 + (yy & 1)]) * w)


@pytest.fixture(scope="module")
def img(baked, symtab):
    return Img(baked, symtab)


BTN, PLANE, SPRITE, STK, RET = 0x10000000, 0x10100000, 0x10300000, 0x10380000, 0x103F0000
STRIDE = 1024


def _zoomed_art(dev_w, dev_h, native_w, native_h, art_h, notches):
    """The canvas thunk_btn_2dscale's stretch leaves: a native art (art_h rows of colour 0x30, top-anchored, a 1-px
    key notch at each corner in `notches`, key below art_h) NN-zoomed centre-sampled to dev_w x dev_h."""
    nat = np.full((native_h, native_w), KEY, np.uint8)
    nat[:min(art_h, native_h)] = 0x30
    bot = min(art_h, native_h) - 1
    for k, (y, x) in enumerate(((0, 0), (0, native_w - 1), (bot, 0), (bot, native_w - 1))):
        if notches[k]:
            nat[y, x] = KEY
    ys = [SL.nn_center_index(j, dev_h, native_h) for j in range(dev_h)]
    xs = [SL.nn_center_index(i, dev_w, native_w) for i in range(dev_w)]
    return nat[np.ix_(ys, xs)]


def _reference(canvas, g, state, D):
    """The law: state 0 re-tiles rows [0, D) full width, then punches four s x s squares (bottom pair on D); states
    1 / 2 punch each corner whose corner pixel is key."""
    out = canvas.copy()
    H, W = out.shape
    s = SL.btn_corner_notch(g)
    if state == 0:
        for y in range(D):
            out[y, :] = 0x40 + (y & 1)
    for (cy, cx), (y0, x0) in (((0, 0), (0, 0)), ((0, W - 1), (0, W - s)), ((D - 1, 0), (D - s, 0)),
                               ((D - 1, W - 1), (D - s, W - s))):
        if state == 0 or canvas[cy, cx] == KEY:
            out[y0:y0 + s, x0:x0 + s] = KEY
    return out


def _run_devfill(img, g, state, dev_w, dev_h, native_h, art_h, notches, native_w=None):
    sym, mu = img.sym, img.mu
    native_w = native_w or SL.btn_native_dim(dev_w, g)
    cv = _zoomed_art(dev_w, dev_h, native_w, native_h, art_h, notches)
    full = np.full((dev_h, STRIDE), 0x77, np.uint8)
    full[:, :dev_w] = cv
    mu.mem_write(PLANE, full.tobytes())
    img.w32(G_VA, g)
    img.w32(sym["g_btn_origH"], -dev_h)
    img.w32(sym["g_btn_origW"], dev_w)
    img.w32(sym["g_btn_nativeH"], native_h)
    img.w32(sym["g_btn_fill_sprite"], SPRITE)
    img.w32(sym["g_btn_fill_state"], state)
    img.w32(SPRITE + 0x1C, art_h)
    img.w32(BTN + 0x4C4, dev_w)
    img.w32(BTN + 0x4C8, -dev_h)
    img.w32(BTN + 0x444 + 0x54, PLANE)
    img.w32(BTN + 0x444 + 0x4A8, STRIDE)
    img.paint = True
    img.fills.clear()
    img.w32(STK, RET)
    mu.mem_write(RET, b"\xF4")
    for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EDI, UC_X86_REG_EBP):
        mu.reg_write(r, 0x5A5A0000 + r)
    mu.reg_write(UC_X86_REG_ESI, BTN)
    mu.reg_write(UC_X86_REG_ESP, STK)
    mu.emu_start(sym["thunk_btn_devfill"], RET, count=2_000_000)
    assert mu.reg_read(UC_X86_REG_ESP) == STK + 4 and mu.reg_read(UC_X86_REG_ESI) == BTN
    assert img.r32(sym["g_btn_fill_sprite"]) == 0, "the capture is consumed"
    got = np.frombuffer(bytes(mu.mem_read(PLANE, STRIDE * dev_h)), np.uint8).reshape(dev_h, STRIDE)
    assert (got[:, dev_w:] == 0x77).all(), "nothing past the button's width"
    D = SL.btn_bar_tile_height(dev_h, native_h, art_h)
    assert img.r32(sym["g_btn_tileH"]) == D
    assert len(img.fills) == (1 if state == 0 else 0), "states 1 / 2 never re-tile"
    return cv, got[:, :dev_w].copy(), D


NOTCH_SETS = ((1, 1, 1, 1), (0, 0, 0, 0), (1, 0, 1, 0), (0, 1, 1, 1))


@pytest.mark.parametrize("g", range(17, 41))
def test_devfill_and_litcorner_are_the_law(img, g):
    for native_h, art_h in ((20, 20), (22, 20)):
        dev_h = SL.popup_scale_floor(native_h, g) + (1 if native_h == 20 and g % 3 == 0 else 0)
        dev_w = SL.popup_scale_floor(236, g)
        for state in (0, 1, 2):
            for notches in NOTCH_SETS:
                cv, got, D = _run_devfill(img, g, state, dev_w, dev_h, native_h, art_h, notches)
                want = _reference(cv, g, state, D)
                assert np.array_equal(got, want), (g, native_h, state, notches)
                if state and all(notches):
                    s = SL.btn_corner_notch(g)
                    for (y, x) in ((0, 0), (0, dev_w - s), (D - s, 0), (D - s, dev_w - s)):
                        assert (got[y:y + s, x:x + s] == KEY).all()
                    # the punch covered the NN notch: the square is exactly s x s (the next row / col is art)
                    assert got[s, 0] != KEY and got[0, s] != KEY and got[D - 1 - s, 0] != KEY


def test_devfill_without_a_capture_is_a_no_op(img):
    sym, mu = img.sym, img.mu
    img.w32(sym["g_btn_fill_sprite"], 0)
    img.w32(sym["g_btn_fill_state"], 2)
    mu.mem_write(PLANE, bytes([0x33]) * (STRIDE * 8))
    img.w32(STK, RET)
    mu.mem_write(RET, b"\xF4")
    regs = {r: 0x6B6B0000 + r for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                                         UC_X86_REG_EDI, UC_X86_REG_EBP)}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_ESI, BTN)
    mu.reg_write(UC_X86_REG_ESP, STK)
    mu.emu_start(sym["thunk_btn_devfill"], RET, count=1000)
    assert all(mu.reg_read(r) == v for r, v in regs.items())
    assert bytes(mu.mem_read(PLANE, STRIDE * 8)) == bytes([0x33]) * (STRIDE * 8)


def test_fillcap_captures_every_state(img):
    sym, mu = img.sym, img.mu
    for pending in (0, 1):
        for esi in HUD4 + (LAUNCH, 0x7AF620, 0x891944):
            for state in (0, 1, 2):
                img.w32(sym["g_btn_pending"], pending)
                img.w32(sym["g_btn_fill_sprite"], 0)
                img.w32(sym["g_btn_fill_state"], 0x1234)
                sp = STK - 0x40
                img.w32(sp, RET)                                     # the 0x608118 call's return, as a sentinel
                mu.mem_write(RET, b"\xF4")
                for i, v in enumerate((SPRITE, 0, 0, 3, 0, 61, 20)):
                    img.w32(sp + 4 + 4 * i, v)
                mu.reg_write(UC_X86_REG_ESP, sp)
                mu.reg_write(UC_X86_REG_ESI, esi)
                mu.reg_write(UC_X86_REG_EBP, state)
                mu.reg_write(UC_X86_REG_ECX, BTN + 0x444)
                img.paint = False
                img.fills.clear()
                mu.emu_start(sym["thunk_btn_fillcap"], RET, count=200)
                assert len(img.fills) == 1 and img.fills[0][1][0] == SPRITE, "the native fill still runs"
                assert mu.reg_read(UC_X86_REG_ESP) == sp + 0x20 and mu.reg_read(UC_X86_REG_EBP) == state
                cap = pending == 1 and esi not in HUD4
                assert img.r32(sym["g_btn_fill_sprite"]) == (SPRITE if cap else 0), (pending, hex(esi), state)
                assert img.r32(sym["g_btn_fill_state"]) == (state if cap else 0x1234)


# ============================================================================== 3. end to end
@pytest.fixture(scope="module")
def lobby(baked):
    import netwin_lobby_emu as NL
    return NL.Lobby(str(baked))


@pytest.fixture(scope="module")
def lobby_before(baked, symtab, tmp_path_factory):
    """The bake with F33's two state exits reverted in memory: devfill's jne -> t_btn_litcorner retargeted to the
    capture clear + ret (states 1 / 2 consumed with no punch, as v3 never saw them), ringfix's punch block jumped
    over (no punch where no ring edge drew)."""
    import netwin_lobby_emu as NL
    lb = NL.Lobby(str(baked))
    mu = lb.e.uc
    df = symtab["thunk_btn_devfill"]
    code = bytes(mu.mem_read(df, 224))
    j = code.index(b"\x0F\x85")
    assert j == 0x47 and df + j + 6 + struct.unpack("<i", code[j + 2:j + 6])[0] == symtab["t_btn_litcorner"]
    clear = code.rindex(b"\xC7\x05")                 # mov [g_btn_fill_sprite],0 ; ret
    lb.patch(df + j + 2, struct.pack("<i", (df + clear) - (df + j + 6)))
    rf = symtab["thunk_btn_ringfix"]
    rcode = bytes(mu.mem_read(rf, 672))
    k = rcode.index(bytes.fromhex("8B5DE8") + b"\x8B\x0B")      # mov ebx,[ebp-0x18]; mov ecx,[ebx] (the notch block)
    out1 = rcode.index(bytes.fromhex("89EC5DC3"))                  # mov esp,ebp; pop ebp; ret
    lb.patch(rf + k, b"\xE9" + struct.pack("<i", out1 - (k + 5)))
    return lb


@pytest.mark.parametrize("g", range(16, 41))
def test_e2e_every_state_has_s_by_s_corners(lobby, g):
    import netwin_lobby_emu as NL
    s = SL.btn_corner_notch(g)
    wins = lobby.build(g)
    for box in (False, True):
        for st in (0, 1, 2):
            p = lobby.draw(LAUNCH, st, box)
            assert p.shape == (wins[LAUNCH][3], wins[LAUNCH][2])
            assert NL.corner_notches(p) == [(s, s)] * 4, (g, box, st, NL.corner_notches(p))
            assert len(NL.face_rows(p)) == p.shape[0]


@pytest.mark.parametrize("g", (17, 19, 22, 25, 30, 33, 40))
def test_e2e_22_native_bottom_notch_sits_on_the_art_bottom(lobby, symtab, g):
    import netwin_lobby_emu as NL
    mu = lobby.e.uc
    pin = symtab["t_btn_nath_pin"]
    code = bytes(mu.mem_read(pin, 0x70))
    k = code.index(b"\x81\xFE" + struct.pack("<I", LAUNCH))
    lobby.patch(pin + k + 2, struct.pack("<I", 0xFFFFFFF0))          # unpin LAUNCH: the 22-native class
    try:
        wins = lobby.build(g, native_h=22)
        h = wins[LAUNCH][3]
        assert h == SL.popup_scale_floor(234, g) - SL.popup_scale_floor(212, g)
        n = SL.btn_native_dim(h, g)
        D = SL.btn_bar_tile_height(h, n, 20)
        s = SL.btn_corner_notch(g)
        for st in (0, 1, 2):
            p = lobby.draw(LAUNCH, st)
            assert NL.face_rows(p)[-1] == D - 1, (g, st)
            assert NL.corner_notches(p) == [(s, s)] * 4, (g, st, NL.corner_notches(p))
    finally:
        lobby.patch(pin + k + 2, struct.pack("<I", LAUNCH))


@pytest.mark.parametrize("g, want", (
    (40, [(2, 2), (3, 2), (2, 3), (3, 3)]),      # 4K: the user's lit corners (125459 / 125503 / 125445 / 125535)
    (22, [(1, 1)] * 4),                          # 1920x1080: lit 1x1 vs idle 2x2
    (25, [(2, 2)] * 4),                          # 1600x1200: already s x s by NN (the user's "2x2")
    (30, [(2, 2)] * 4),                          # 2560x1440: ditto
))
def test_e2e_reverted_bake_reproduces_the_lit_corners(lobby_before, g, want):
    import netwin_lobby_emu as NL
    s = SL.btn_corner_notch(g)
    lobby_before.build(g)
    for box in (False, True):
        assert NL.corner_notches(lobby_before.draw(LAUNCH, 0, box)) == ([(s, s)] * 4 if not box else want)
        for st in (1, 2) if not box else (0, 2):
            assert NL.corner_notches(lobby_before.draw(LAUNCH, st, box)) == want, (g, box, st)
