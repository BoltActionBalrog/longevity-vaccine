"""The 0x78D960 BoxSpriteParams family's thin rings and native-density draws (2026-10-25 wave-7 W7R v2; user decision "Scale
the thin rings").

Laws (scaling_laws.py, the source of truth): THIN_RING_FAMILY_REFS (the census of every ref to the family),
box_edge_strokes, ring_solid / ring_band_rects, menu_row_clip / menu_box_rect, bandmap_rect_from_halfopen, stroke_width,
stripe_rows / stripe_top.  Port: t_rowbox_solid / t_ring_solid / t_menu_border / t_menu_row
(scripts/assemble_thin_rings.py); their Unicorn parity is test_thin_rings_asm_parity.py.

Proof layers:
  1. CENSUS (the pristine image's bytes): every imm32 / disp32 into the family [0x78D960, 0x78D9D8) is in
     THIN_RING_FAMILY_REFS with the value its class implies, or is a FlatButton dressing's 0x78D988 / 0x78D9B0 companion
     next to a classified 0x78D960; the no_stroke dressings carry no 0x78D988; no data outside .text points into it.
  2. THE ART (the real image, load_interface): only the state-1 set carries a stroke, E0 on all four sides; every set
     keys its four corner texels.
  3. THE UNIVERSAL MENU (the real image, the engine's build / paint order, g forced 16..40 on one 4K boot): no ring;
     the K x K corner notches; every AE / EE pixel on the stripe law; the hot row inset K from both menu edges, its
     E0 / E1 counted from its own top (menu_hot_row_colour: E0 on the top edge, like vanilla); every row hot in turn
     looks the same; the engine's incremental hot change (Menu_draw) == the full paint; g 16 == the pristine image.
  4. THE POPUP OPTION-ROW HOVER RING (the real Go To popup, popup_listbox_emu, at g 17 / 18 / 20 / 22 / 25 / 30 / 40):
     the engine's own ListBox_set_hover draws row 2 in state 1 through the site; the ring is solid E0, K on all four
     sides; the canvas == ring_solid of the deployed render (the site pointed back at t_rowbox_trim in the same image:
     interior stripes and every other pixel unchanged); the selected and a normal row redrawn by the deployed path are
     byte-identical to this build's; g 16 == the pristine image.
  5. REACH (static + Unicorn): DiploWinIface_item_back is the DiploWin iface's slot +0x48 and nothing else; the only
     dispatcher of an iface's +0x48 is MainWin's vtbl+0x2C forwarder 0x45C8F0 (-> the CURRENT mode's iface); a list
     calls vtbl+0x2C on its PARENT (Win +0xC4) to draw an item's back (ListBox_draw_item 0x60BB58 and the two Dialog
     row loops 0x60DA9A / 0x60F37A); the lists attached with MainWin as the parent are the six HQ report console
     ListBoxes (report modes only); the DiploWin builder / painters attach no list (direct calls + a Unicorn trace from
     two synthetic states).  So no shipped flow draws its 1-px ring, and the bake leaves its site pristine (5b).
COST: two 4K boots (bake + pristine, ~3 s each) + ~0.3 s per Menu paint (24 + 7 x 7); one popup boot per hover g (~4 s; 9 boots,
independent parametrized tests that xdist spreads); the census / reach scans are numpy byte scans (<1 s).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scaling_laws as SL  # noqa: E402

FAMILY = (0x78D960, 0x78D9D8)
FILLS = {0x78D980, 0x78D9A8, 0x78D9D0}                # the three sets' +0x20 fill Buffer*
FLAT = {"btn_ring", "no_stroke"}
G_VA, G_STRIPE_PERIOD = 0x668740, 0x66879C
LOAD_IFACE, GW_CTOR, GW_INIT = 0x455610, 0x5D4CF0, 0x5D4EF0
BG = 0xC6
MAINWIN = 0x7AE820                                    # MainWin_g (the object)
IFACE_TABLE = 0x7AE7F0                                # MainWin's per-mode iface pointers
MW_ITEM_BACK = 0x45C8F0                               # MainWin vtbl+0x2C: -> the current mode's iface +0x48
MW_VTBL_2C = 0x66C5C4
DW_IFACE_VTBL = 0x66B5E0
LIST_ATTACH = {0x60A670: "ListBox_attach", 0x610540: "OptionList_attach", 0x60D1F0: "Dialog_type16_attach",
               0x612970: "Dialog_set_type", 0x611AF0: "Dialog_type4_attach", 0x60E800: "type1_attach"}
REPORTWIN_LIST_SITES = {0x4A7582, 0x4A88D9, 0x4A8F79, 0x4A9AA3, 0x4AC46C, 0x4AC938}   # push MainWin_g -> ListBox_attach
DIPLOWIN_FNS = {"DiploWin_build": (0x443F10, 0x444D8F), "DiploWin_draw": (0x4436C0, 0x443C6F),
                "DiploWin_draw_left": (0x442A10, 0x442DBF), "DiploWin_draw_right": (0x442DC0, 0x44316F),
                "DiploWin_draw_offers": (0x443170, 0x4436BF), "DiploWinIface_on_mode": (0x443C70, 0x443D76)}


# ================================================================ 1. the census
class _Img:
    def __init__(self, data: bytes):
        pe = pefile.PE(data=data, fast_load=True)
        self.ib = pe.OPTIONAL_HEADER.ImageBase
        self.mem = pe.get_memory_mapped_image()
        t = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
        self.text = (self.ib + t.VirtualAddress, self.ib + t.VirtualAddress + t.Misc_VirtualSize)

    def at(self, va, n):
        return self.mem[va - self.ib:va - self.ib + n]

    def dwords(self, lo, hi, vlo, vhi=None):
        """{va: value} for every 4-byte window in [lo, hi) whose value is in [vlo, vhi) (vhi None: == vlo)."""
        vhi = vlo + 1 if vhi is None else vhi
        b = np.frombuffer(self.mem[lo - self.ib:hi - self.ib], dtype=np.uint8).astype(np.uint32)
        v = b[:-3] | (b[1:-2] << 8) | (b[2:-1] << 16) | (b[3:] << 24)
        return {lo + int(i): int(v[i]) for i in np.nonzero((v >= vlo) & (v < vhi))[0]}


@pytest.fixture(scope="module")
def img(bak_bytes):
    return _Img(bak_bytes)


def test_scaling_thin_ring_census_is_complete(img):
    refs = img.dwords(*img.text, *FAMILY)
    census = SL.THIN_RING_FAMILY_REFS
    assert set(census) <= set(refs), sorted(hex(a) for a in set(census) - set(refs))
    for va, (_what, kind) in census.items():
        want = FILLS if kind == "fill_tile" else {0x78D960}
        assert refs[va] in want, (hex(va), hex(refs[va]), kind)
    for va, v in refs.items():
        if va in census:
            continue
        assert v in (0x78D988, 0x78D9B0), (hex(va), hex(v), "an unclassified ref to the family")
        owner = [a for a, (_w, k) in census.items() if k in FLAT and abs(a - va) <= SL.THIN_RING_COMPANION_SPAN]
        assert len(owner) == 1, (hex(va), hex(v), owner)
    for va, (_what, kind) in census.items():                      # a no_stroke dressing has no hover-ring set
        near = {v for a, v in refs.items() if abs(a - va) <= SL.THIN_RING_COMPANION_SPAN and a != va}
        if kind == "no_stroke" and "FlatButton" in _what:
            assert near == {0x78D9B0}, (hex(va), near)
        if kind == "btn_ring":
            assert 0x78D988 in near, (hex(va), near)
    # nothing outside .text holds a pointer into the family either (no data table reaches it)
    lo, hi = img.ib + 0x1000, img.ib + len(img.mem)
    data = {a: v for a, v in img.dwords(lo, hi, *FAMILY).items()
            if not img.text[0] <= a < img.text[1]}
    assert not data, {hex(a): hex(v) for a, v in data.items()}


def test_scaling_thin_ring_twin_sites(img):
    """The two direct item-back draws are twins: the same `lea r, [state*8*5 + 0x78D960]` + Buffer_box_sprite; the
    Menu callbacks pick state 0 / 2 only (`neg; sbb; and eax, 2`) and state 0."""
    assert img.at(SL.DW_ITEM_RING_SITE, 5) == bytes.fromhex("E8DFEE1900")
    assert img.at(0x443EE4, 7) == bytes.fromhex("8D0CC560D97800") and img.at(0x405BEB, 7) == bytes.fromhex("8D14CD60D97800")
    assert img.at(0x403B3C, 15) == bytes.fromhex("F7D81BC081C77404000083E0028D14")   # state = arg ? 2 : 0
    assert img.at(0x403B76, 5) == bytes.fromhex("6860D97800")                         # push the state-0 set


# ================================================================ 5. reach (static + Unicorn)
def _calls_in(img, lo, hi):
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    out = set()
    for ins in md.disasm(img.at(lo, hi - lo), lo):
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            out.add(int(ins.op_str, 16))
    return out


def test_scaling_thin_ring_item_back_reach(img):
    whole = (img.ib + 0x1000, img.ib + len(img.mem))
    # the function is only the DiploWin iface's slot +0x48; that vtable is installed once
    assert set(img.dwords(*whole, SL.DW_ITEM_BACK)) == {DW_IFACE_VTBL + 0x48}
    assert set(img.dwords(*whole, DW_IFACE_VTBL)) == {0x445069}
    # the only `call [reg + 0x48]` behind a load from the iface table is MainWin's vtbl+0x2C forwarder
    disp = [a for a in img.dwords(*img.text, IFACE_TABLE)
            if any(img.at(a + 4 + i, 3)[:1] == b"\xFF" and img.at(a + 4 + i, 3)[2:] == b"\x48"
                   and 0x50 <= img.at(a + 4 + i, 3)[1] <= 0x57 for i in range(0x20))]
    assert len(disp) == 1 and MW_ITEM_BACK < disp[0] < MW_ITEM_BACK + 0x30, [hex(a) for a in disp]
    assert set(img.dwords(*whole, MW_ITEM_BACK)) == {MW_VTBL_2C}
    # a list draws an item back through vtbl+0x2C of its PARENT (Win +0xC4): ListBox_draw_item + the two row loops
    assert img.at(0x60BB17, 7) == bytes.fromhex("8B8C31C4000000") and img.at(0x60BB58, 3) == bytes.fromhex("FF522C")
    for va in (0x60DA9A, 0x60F37A):
        assert img.at(va, 3) == bytes.fromhex("FF532C")
    # the lists attached with MainWin_g as the parent: the six HQ report console ListBoxes (report modes only)
    pushes = {a - 1 for a in img.dwords(*img.text, MAINWIN) if img.at(a - 1, 1) == b"\x68"}
    attached = set()
    for p in pushes:
        for tgt in LIST_ATTACH:
            for i in range(5, 0x30):
                if img.at(p + i, 1) == b"\xE8" and \
                        p + i + 5 + int.from_bytes(img.at(p + i + 1, 4), "little", signed=True) == tgt:
                    attached.add(p)
    assert attached == REPORTWIN_LIST_SITES, sorted(hex(a) for a in attached)
    # the DiploWin builder and painters attach no list (static: every direct call in their bodies)
    for name, (lo, hi) in DIPLOWIN_FNS.items():
        assert not (_calls_in(img, lo, hi) & set(LIST_ATTACH)), name


def test_scaling_thin_ring_diplowin_build_attaches_no_list(bak_path):
    """Unicorn: DiploWin_build run from the g16-identity harness's synthetic states (every out-of-function call
    stubbed and recorded) calls no list attach."""
    import test_strip_g16_identity as H
    if not H.HAVE_EMU:
        pytest.skip("pefile/unicorn not installed")
    secs = H.load_sections(str(bak_path))
    for seed in H.SEEDS:
        run = H.FnRun(secs, DIPLOWIN_FNS["DiploWin_build"], seed, extra_exec=[]).run()
        targets = {e[1] for e in run.trace if e[0] == "call"}
        assert len(targets) >= 5, (seed, len(targets))          # the run got somewhere
        assert not (targets & set(LIST_ATTACH)), (seed, sorted(hex(t) for t in targets & set(LIST_ATTACH)))


# ================================================================ the real-image rig
def _emu():
    from conftest import _missing
    try:
        import image_emu as IE
    except Exception as x:                                  # no game dir / host GDI
        _missing(Path("image_emu"), f"the real-image emulator ({x})")
    if not (Path(IE.GAME) / "interface.pcx").is_file():
        _missing(Path(IE.GAME) / "interface.pcx", "the game's box-sprite art")
    return IE


class Rig:
    def __init__(self, exe, w=3840, h=2160):
        IE = self.IE = _emu()
        e = self.e = IE.boot(str(exe), w, h)
        IE.Files(e)
        e.call(LOAD_IFACE, args=(0,), count=0)
        self.patched = bytes(e.uc.mem_read(0x668760, 4)) != bytes(4)
        self.wins = {}

    def force_g(self, g):
        if self.patched:
            self.e.w32(G_VA, g)
            self.e.w32(G_STRIPE_PERIOD, SL.stripe_period(g))

    WIN_W, WIN_H = ((400 * 40) >> 4) + 3, 3 * ((22 * 40) >> 4) + 3     # every g's rects fit the g = 40 window

    def window(self, key):
        """One GraphicWin per purpose, built once per rig (a window per call exhausts the emulated heap over a g
        sweep), its canvas reset to the background before every use."""
        e = self.e
        if key not in self.wins:
            win = e.alloc(0x1000)
            e.call(GW_CTOR, ecx=win)
            e.call(GW_INIT, ecx=win, args=(0, 0, self.WIN_W, self.WIN_H, e.cstr(""), 0, 0, 0, 0), count=20_000_000)
            self.wins[key] = win
        win = self.wins[key]
        e.uc.mem_write(e.r32(win + 0x498), bytes([BG]) * (((self.WIN_W + 3) & ~3) * self.WIN_H))
        return win

    def sprite(self, p):
        e = self.e
        bits, pitch, w, h = e.r32(p + 4), e.s32(p + 0xC), e.s32(p + 0x10), e.s32(p + 0x14)
        return [list(e.uc.mem_read(bits + y * pitch, w)) for y in range(h)], e.uc.mem_read(p + 8, 1)[0]

    def strips(self, base):
        return [self.sprite(self.e.r32(base + slot))[0] for slot in (0x10, 0x14, 0x18, 0x1C)]

    def corners(self, base):
        out = []
        for slot, (row, col) in zip((0, 4, 8, 0xC), (("0", "0"), ("0", "w"), ("h", "0"), ("h", "w"))):
            rows, key = self.sprite(self.e.r32(base + slot))
            out.append(rows[-1 if row == "h" else 0][-1 if col == "w" else 0] == key)
        return out


_RIGS: dict = {}


def rig(which, images):
    if which not in _RIGS:
        _RIGS[which] = Rig(images[which])
    return _RIGS[which]


@pytest.fixture(scope="module")
def images(bak_path, baked_exe):
    return {"bake": baked_exe, "pristine": bak_path}


# ================================================================ 2. the art
def test_scaling_thin_ring_art_only_state1_strokes(images):
    r = rig("pristine", images)
    got = [SL.box_edge_strokes(r.strips(b)) for b in SL.FACTION_ROW_BOX_SETS]
    assert got == [(None,) * 4, (0xE0,) * 4, (None,) * 4], got
    assert SL.FACTION_ROW_BOX_SETS[1] == SL.THIN_RING_SET_STATE1
    for b in SL.FACTION_ROW_BOX_SETS:
        assert r.corners(b) == [True] * 4, hex(b)


# ================================================================ 3. the universal Menu
MENU_BG = 0x00                                      # the fresh menu buffer under the keyed corners (the rig's)
AE, EE, E0, E1 = 0xAE, 0xEE, 0xE0, 0xE1


def _menu(r, g, hot=1, redraw_to=None):
    """The universal Menu control built and painted in the engine's order (Menu_ctor / Menu_init / items / Menu_show
    with the modal stubbed / Menu vtbl+0x30 Menu_paint), with load_menu's box callbacks and thunk_faction_submenu's
    g/16 font + margins; row `hot` hot.  redraw_to: then the engine's incremental hot change Menu_draw 0x5F9F60
    (new hot, old hot) -- the mouse-over path.  -> the menu canvas."""
    e = r.e
    r.force_g(g)
    cells = (0x9B7B58, 0x9B7B5C, 0x696E1C, 0x696E04, 0x9B7B68)
    saved = [e.r32(a) for a in cells]
    try:
        e.w32(0x9B7B58, 0x403AF0)                          # load_menu's install of the box callbacks
        e.w32(0x9B7B5C, 0x403B70)
        e.w32(0x696E1C, (saved[2] * g) >> 4)               # thunk_faction_submenu: margins x g/16, font fl(16g/16)
        e.w32(0x696E04, (saved[3] * g) >> 4)
        menus = r.__dict__.setdefault("menus", {})          # one menu per g per rig: a build per paint exhausts
        if g not in menus:                                   # the emulated heap over a sweep
            font = e.call(0x5882F0, args=((16 * g) >> 4, 0))
            e.w32(0x9B7B68, font)
            m = e.alloc(0x2000)
            e.call(0x5F8800, ecx=m)                          # Menu_ctor
            e.call(0x5F8920, ecx=m, args=(0,))               # Menu_init
            for i, t in enumerate(("Gaia's Stepdaughters", "Human Hive", "University of Planet", "RANDOM")):
                e.call(0x5F89D0, ecx=m, args=(i + 1, e.cstr(t)))
            if not getattr(r, "modal_stubbed", False):
                e.stub_fn(0x5EE190, lambda e: 0, popbytes=0xC)  # Menu_show's modal: size + place only
                r.modal_stubbed = True
            e.call(0x5F9170, ecx=m, args=(10, 10, 0), count=50_000_000)
            menus[g] = (m, font)
        m, font = menus[g]
        e.w32(0x9B7B68, font)
        e.w32(m + 0xF28, hot)                              # the hot row
        e.call(0x5F98B0, ecx=m, count=50_000_000)          # Menu vtbl+0x30: the paint
        if redraw_to is not None:
            e.w32(m + 0xF28, redraw_to)
            e.call(0x5F9F60, ecx=m, args=(redraw_to, hot), count=50_000_000)
        return r.IE.canvas_of(e, m)
    finally:
        for a, v in zip(cells, saved):
            e.w32(a, v)


def test_scaling_thin_ring_menu_has_no_stroke(images):
    c = _menu(rig("bake", images), 40)
    h, w = c.shape
    assert w > 300 and h > 150                             # scaled (vanilla ~170 x 82)
    for edge in (c[0, 2:-2], c[-1, 2:-2], c[2:-2, 0], c[2:-2, -1]):
        assert not (set(edge.tolist()) & {E0, E1}), sorted(set(edge.tolist()))


@pytest.mark.parametrize("g", range(17, 41))
def test_scaling_thin_ring_menu_fill_notch_inset(images, g):
    c = _menu(rig("bake", images), g)
    H, W = c.shape
    k = SL.stroke_width(g)
    # the K x K corner notches (the background), the fill right next to them
    for y0, x0 in ((0, 0), (0, W - k), (H - k, 0), (H - k, W - k)):
        assert set(c[y0:y0 + k, x0:x0 + k].ravel().tolist()) == {MENU_BG}, (g, "corner", (x0, y0))
    assert c[0, k] in (AE, EE) and c[k, 0] in (AE, EE) and c[H - 1, W - 1 - k] in (AE, EE), g
    # every AE / EE pixel on the stripe law: AE (the band map's top member) on the top rows of each period
    ys, xs = np.nonzero(np.isin(c, (AE, EE)))
    top = np.array([SL.stripe_top(int(y), g) for y in range(H)])
    assert np.array_equal(c[ys, xs] == AE, top[ys]), g
    # the hot row: inset K from both menu edges (vanilla 1 = the notch), its E0 / E1 counted from its own top
    _hot_row_ok(c, g, k)


def _hot_row_ok(c, g, k):
    """The hot row's E0 / E1 band: contiguous, inset K on both sides, every E0 / E1 pixel menu_hot_row_colour of the
    row's own top (E0 on its top edge, like vanilla).  -> (top, bottom)."""
    H, W = c.shape
    hot = np.nonzero(np.isin(c[:, k], (E0, E1)))[0]
    assert len(hot) and np.array_equal(hot, np.arange(hot[0], hot[-1] + 1)), g
    t0, t1 = int(hot[0]), int(hot[-1]) + 1
    band = c[t0:t1]
    ys, xs = np.nonzero(np.isin(band, (E0, E1)))
    want = np.array([SL.menu_hot_row_colour(t0 + int(y), t0, g) for y in range(t1 - t0)], dtype=np.uint8)
    assert np.array_equal(band[ys, xs], want[ys]), g
    assert c[t0, k] == E0, g
    for y in range(t0, t1):
        if k <= y < H - k:                                   # outside the K x K corner notches
            assert c[y, k - 1] in (AE, EE) and c[y, W - k] in (AE, EE), (g, y)
        assert c[y, k] in (E0, E1) and c[y, W - 1 - k] in (E0, E1), (g, y)
    return t0, t1


@pytest.mark.parametrize("g", [17, 18, 20, 22, 25, 30, 40])
def test_scaling_thin_ring_menu_hot_rows_identical(images, g):
    """Every hot row looks the same (vanilla: E0 on each hot row's top edge): the E0 / E1 pattern of each row, hot in
    turn, read from its own top, is one pattern; and the engine's incremental hot change (Menu_draw from the row above
    and from the row below) equals the full paint."""
    r = rig("bake", images)
    k = SL.stroke_width(g)
    pats = []
    for hot in range(4):
        c = _menu(r, g, hot)
        t0, t1 = _hot_row_ok(c, g, k)
        pats.append(c[t0:t1, k].tolist())
    assert all(p == pats[0] for p in pats), (g, pats)
    full = _menu(r, g, 2)
    assert np.array_equal(_menu(r, g, 1, redraw_to=2), full), g
    assert np.array_equal(_menu(r, g, 3, redraw_to=2), full), g


def test_scaling_thin_ring_menu_g16_is_pristine(images):
    a = _menu(rig("pristine", images), 16)
    b = _menu(rig("bake", images), 16)
    assert a.shape == b.shape and (a == b).all()


# ================================================================ 4. the popup option rows' HOVER ring
STATE_RES = {30: (2560, 1440)}                     # popup_listbox_emu.RES lacks 2560x1440; added locally


def _runs(seq):
    runs, s0 = [], 0
    for i in range(1, len(seq) + 1):
        if i == len(seq) or seq[i] != seq[s0]:
            runs.append(i - s0)
            s0 = i
    return runs


class Hover:
    """The real Go To popup (popup_listbox_emu: the engine's own build and draw), then the engine's own hover:
    ListBox_set_hover 0x60CBC0 at a row's centre -> ListBox_draw_item redraws it in state 1 through the site 0x405BF6.
    `deployed()` points the site back at t_rowbox_trim (the deployed bytes) in the emulated image."""

    def __init__(self, exe, g):
        import popup_listbox_emu as L
        from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESP
        for k, v in STATE_RES.items():
            L.RES.setdefault(k, v)
        self.L, self.ESP = L, UC_X86_REG_ESP
        self.rec = []

        def patch(e):
            def cb(e):
                esp = e.reg(UC_X86_REG_ESP)
                self.rec.append((struct.unpack("<4i", bytes(e.uc.mem_read(e.r32(esp), 16))), e.reg(UC_X86_REG_EDI),
                                 e.reg(UC_X86_REG_ECX) - 0x444))
            e.observe(SL.OPTION_ROW_SITE, cb)
        self.run = L.Run(str(exe), g, label="GOTO", patch=patch)
        self.e = e = self.run.e
        self.g = self.run.g
        self.win = self.rec[-1][2]
        self.rows = [r for r, _s, _w in self.rec]
        e._esp_base = self.run.saved[UC_X86_REG_ESP] - 0x8000

    def canvas(self):
        import image_emu as IE
        return IE.canvas_of(self.e, self.win).copy()

    def hover(self, i):
        l, t, r, b = self.rows[i]
        n = len(self.rec)
        self.e.call(0x60CBC0, ecx=self.run.pop + self.L.POPUP_LB + 0x48, args=((l + r) // 2, (t + b) // 2),
                    count=50_000_000)
        return self.rec[n:]

    def deployed(self, trim_va):
        rel = (trim_va - (SL.OPTION_ROW_SITE + 5)) & 0xFFFFFFFF
        self.e.uc.mem_write(SL.OPTION_ROW_SITE, b"\xE8" + rel.to_bytes(4, "little"))
        self.e.uc.ctl_remove_cache(SL.OPTION_ROW_SITE & ~0xFFF, (SL.OPTION_ROW_SITE + 0x1005) & ~0xFFF)


def _trim_va():
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return dict(ap.build_symbol_table(syms, caves))["t_rowbox_trim"]


def _band_ok(c, rect, k):
    l, t, r, b = rect
    for (x0, y0, x1, y1) in SL.ring_band_rects(l, t, r, b, k):
        assert set(c[y0:y1, x0:x1].ravel().tolist()) == {E0}, (rect, (x0, y0, x1, y1))


@pytest.mark.parametrize("g", [17, 18, 20, 22, 25, 30, 40])
def test_scaling_thin_ring_option_row_hover_is_solid(baked_exe, g):
    h = Hover(baked_exe, g)
    assert h.g == g
    c0 = h.canvas()                                          # every row drawn once (row 0 selected: state 2)
    assert {s for _r, s, _w in h.rec} == {0, 2}
    drawn = h.hover(2)                                       # the engine's hover: row 2 in state 1
    assert [(r, s) for r, s, _w in drawn] == [(h.rows[2], 1)]
    new = h.canvas()
    h.deployed(_trim_va())                                   # the deployed site: t_rowbox_trim alone
    h.hover(3)
    h.hover(0)
    drawn = h.hover(2)
    assert [(r, s) for r, s, _w in drawn] == [(h.rows[2], 1)]
    dep = h.canvas()
    k = SL.stroke_width(g)
    rect = h.rows[2]                                         # GOTO = type 2: t_rowbox_trim's R / B - 1, so the
    l, t, r, b = rect                                        # band-map extent is the engine's half-open rect
    _band_ok(new, rect, k)                                   # solid E0, K on all four sides
    ym, xm = (t + b) // 2, (l + r) // 2
    assert _runs(new[ym, l:r].tolist())[0] == k and _runs(new[ym, l:r].tolist())[-1] == k
    assert _runs(new[t:b, xm].tolist())[0] == k and _runs(new[t:b, xm].tolist())[-1] == k
    want = np.array(SL.ring_solid(dep.tolist(), rect, g, (E0,) * 4), dtype=np.uint8)
    assert np.array_equal(new, want), g                      # == the law on the deployed render; nothing else moved
    assert np.array_equal(new[t + k:b - k, l + k:r - k], dep[t + k:b - k, l + k:r - k])   # interior stripes kept
    ring_dep = set()                                         # the deployed ring: restriped E0 / E1 (the defect)
    for (x0, y0, x1, y1) in SL.ring_band_rects(l, t, r, b, k):
        ring_dep |= set(dep[y0:y1, x0:x1].ravel().tolist())
    assert ring_dep == {E0, E1}, (g, ring_dep)
    for i in (0, 3):                                         # non-hover rows (selected / normal): deployed bytes
        rl, rt, rr, rb = h.rows[i]
        assert np.array_equal(dep[rt:rb, rl:rr], c0[rt:rb, rl:rr]), (g, i)


def test_scaling_thin_ring_option_row_g16_is_pristine(bak_path, baked_exe):
    out = []
    for exe in (bak_path, baked_exe):
        h = Hover(exe, 16)
        c0 = h.canvas()
        drawn = h.hover(2)
        assert [s for _r, s, _w in drawn] == [1]
        out.append((c0, h.canvas()))
    (a0, a1), (b0, b1) = out
    assert np.array_equal(a0, b0) and np.array_equal(a1, b1)


# ================================================================ 5b. the DiploWin item back stays native
def test_scaling_thin_ring_item_back_not_patched(bak_bytes, baked_exe):
    """Unreachable (layer 5), so not patched: the bake's site 0x443EEF is the pristine `call Buffer_box_sprite`."""
    a, b = _Img(bak_bytes), _Img(Path(baked_exe).read_bytes())
    assert a.at(SL.DW_ITEM_RING_SITE, 5) == b.at(SL.DW_ITEM_RING_SITE, 5) == bytes.fromhex("E8DFEE1900")
