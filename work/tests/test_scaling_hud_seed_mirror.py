"""F32 (2026-10-25): the HUD strip's right console panel on the mirror grid.

DEFECT (user shots, 4K): on the map HUD and every HQ report console the right console panel's whole inner chain sat
1 px left of the mirror of the left panel (F2 da50 / d5a0 / d528 at 2587 / 2594 / 2601, mirrors 2588 / 2595 / 2602;
the F6 ORBITAL ATTACK VIEW target buttons 560 vs 561 wide).  thunk_hud_seedscale floored each seed alone:
fl(245g/16) + fl(779g/16) = 64g - 1 at every g that is not a multiple of 16 (the left panel +0xD80 (4, 56, 245, 252)
and the right +0xD90 (779, 56, 1020, 252) are vanilla's exact mirror pair), and where 1020g/16 is fractional the
outer edge too (1920x1080 / 1600x1200: the whole panel 1 px left, stroke sums W - 2).

Laws (scaling_laws.py): hud_seed_x / hud_seed_scaled (the right-panel x fields HUD_SEED_MIRROR_FIELDS on the mirror
grid W' - fl((1024 - x)g/16) == ceil(x*g/16)), hud_map_btn_pair (one width for the WORLD / DETAIL map buttons),
hud_boxframe_rect / hud_boxframe_table_row (the box-9 frames on the same grid).  Ports: thunk_hud_seedscale v2 +
g_hud_seedtable v2 + t_hud_btnpair (assemble_hud_seed_mirror.py), thunk_hud_boxframe v3 + g_hud_nat_table
(assemble_hud_widgets.py; its parity guard is test_scaling_hud_boxframe_parity.py).

F32 v2 (audit-w2C): the console backdrop stretch made mirror-symmetric (hud_backdrop_col_map, port t_hb_mirror: GDI
sends centre-NN ties to the upper texel, so the right panel's art strokes ran one column wider than their left mirrors
at g 24 / 40 ...); the box-9 inner frame's right edge exclusive and the outer frame nested s(3) inside the panel on both
sides (hud_box9_outer_rect, port t_box9_outer); the map-button pair's width (R - L - s(2)) >> 1.

Proof layers, all on the real bytes of conftest's shared `baked_exe`:
  1. law sweeps (g 16..64) incl. the per-edge-floor mutant (the v1 thunk), the backdrop map vs GDI's, box 9;
  2. UNIT: the seedscale -> t_hud_btnpair -> t_hud_mi_square chain from its call-redirect frame on a random native
     table == the law, registers / flags / frame preserved; the bit-15 marks are exactly HUD_SEED_MIRROR_FIELDS;
  3. END TO END on image_emu (the real MainWin_build): (a) the whole seed table at every g 16..40 == the law of the
     pristine image's own natives, g = 16 == the pristine table; the bake with the marks cleared in memory reproduces
     the defect (4K +0xD90 = 1947 -> screen 2587); (b) at g 16 / 19 / 20 / 22 / 24 / 25 / 28 / 36 / 40 the real paint
     chain -- the stretched backdrop, MainWin_tile_panels via its wrapped call site, the box-9 painter
     (thunk_hud_boxframe / t_box9_outer -> hollow_flat) and the report console chrome (ReportIf_ctor,
     init_report_screen, ReportIf_console_chrome): every right-half tie column of the art is its left neighbour, the
     tile edges and the stroke runs (abutting same-colour art columns included) mirror on every panel-body row of the
     HUD and the chrome, box 9's channels to the panel are equal; g = 16 == the pristine canvases; (c) the bake with
     the backdrop site pointed back at t_hud_backdrop differs only on the tie columns (g 24 / 40).

COST: 3a is one boot per image per worker (~1 s, three images) + ~5 ms per g.  3b / 3c re-run MainWin_build with its
pcx art per item (~2-4 s each, 9 + 2 items, split across xdist by g): the strokes are the engine's stretched console art
plus the chrome's own frames -- no lighter path draws them, and the defect lives in exactly that composition.
"""
from __future__ import annotations

import random
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
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

MAINWIN = 0x7AE820
G_VA, SW_VA, SH_VA = 0x668740, 0x9B7B1C, 0x9B7B20
SEEDSCALE_SITE, SEEDSCALE_RET, BUFFER_LOAD_PCX = 0x459E8A, 0x459E8F, 0x5D7DE0
MI_FIELDS = (0xA2C, 0xA30, 0xA3C, 0xA48, 0xA4C)          # t_hud_mi_square's five writes (law hud_mi_btn_rect)
STRIP_RECT = (0xA1C, 0xA20, 0xA24, 0xA28)                 # recomputed by seedscale, not in the table
LEFT_PANEL, RIGHT_PANEL = 0xD80, 0xD90
ALL_G = range(16, 41)
HEAP = 0x30000000


def _res(g):
    return 64 * g, 48 * g                                 # g_popup_scale_num = floor(16 * min(W/1024, H/768)) = g


def _ceil(x, g):
    return -((-x * g) >> 4)


# ============================================================================== 1. laws
@pytest.mark.parametrize("g", range(16, 65))
def test_hud_seed_ceil_equals_mirror(g):
    """The mirror form W' - fl((1024 - x)g/16) is the ceil image (x*g + 15) >> 4 the thunk computes, for every strip x
    (W' = fl(1024g/16) = 64g exactly); off the mirror grid it is the plain floor; g <= 16 the identity."""
    if g > 16:
        assert SL.hud_strip_w(g) == 64 * g
    for x in range(0, SL.HUD_STRIP_NATIVE_W + 1):
        if g <= 16:
            assert SL.hud_seed_x(x, g, True) == SL.hud_seed_x(x, g, False) == x
            continue
        assert SL.hud_seed_x(x, g, True) == _ceil(x, g) == (x * g + 15) >> 4
        assert SL.hud_seed_x(x, g, False) == (x * g) >> 4


@pytest.mark.parametrize("g", range(16, 65))
def test_scaling_right_panel_mirrors_left_panel(g):
    """Every right-panel x seed is the device mirror of its vanilla mirror partner's floor image, so the panel pair
    sums to the strip width on both edges (strokes on Wd - 1) at every g; the v1 per-edge floor (the mutant) does not
    at any g that is not a multiple of 16."""
    W = SL.hud_strip_w(g)
    left, right = (4, 56, 245, 252), (779, 56, 1020, 252)
    assert all(a + b == SL.HUD_STRIP_NATIVE_W for a, b in ((left[0], right[2]), (left[2], right[0])))
    sc = SL.hud_seed_scaled
    assert sc(0xD80, 4, g) + sc(0xD98, 1020, g) == W
    assert sc(0xD88, 245, g) + sc(0xD90, 779, g) == W
    for x in range(0, SL.HUD_STRIP_NATIVE_W + 1):                     # any right-panel x mirrors its partner
        assert sc(0xD90, SL.HUD_STRIP_NATIVE_W - x, g) == W - sc(0xD80, x, g)
    floor_ok = SL.popup_scale_floor(245, g) + SL.popup_scale_floor(779, g) == W
    assert floor_ok == (g <= 16 or g % 16 == 0)
    for f in SL.HUD_SEED_MIRROR_FIELDS:                                # the y / other fields keep the floor
        assert sc(f + 4, 100, g) == SL.popup_scale_floor(100, g)


@pytest.mark.parametrize("g", range(16, 65))
def test_scaling_map_btn_pair(g):
    """WORLD / DETAIL: one width (R - L - s(2)) >> 1 within 1 px of 54g/16, outer edges on the mirror grid, the seam
    s(2) or s(2) + 1."""
    (wl, wr), (dl, dr) = SL.hud_map_btn_pair(g)
    if g <= 16:
        assert (wl, wr, dl, dr) == (904, 958, 960, 1014)
        return
    assert wr - wl == dr - dl and abs(16 * (wr - wl) - 54 * g) < 16
    assert (wl, dr) == (_ceil(904, g), _ceil(1014, g))
    assert SL.popup_scale_floor(2, g) <= dl - wr <= SL.popup_scale_floor(2, g) + 1


def test_scaling_map_btn_per_edge_mutants_unequal():
    """Each edge alone -- floor (v1) or the mirror grid -- leaves the two windows 1 px apart at 6 of 24 g."""
    fl = SL.popup_scale_floor
    assert [g for g in range(17, 41) if fl(958, g) - fl(904, g) != fl(1014, g) - fl(960, g)] == [21, 23, 29, 31, 37, 39]
    assert [g for g in range(17, 41) if _ceil(958, g) - _ceil(904, g) != _ceil(1014, g) - _ceil(960, g)] == \
        [17, 19, 25, 27, 33, 35]


@pytest.mark.parametrize("g", range(16, 65))
def test_scaling_backdrop_col_map_is_mirror_and_gdi_but_right_ties(g):
    """The console backdrop map (F32 v2): mirror-symmetric; equal to GDI's centre-NN (ties to the upper texel,
    nn_center_index) on every column but the right-half ties, where it is GDI's texel of the column before (the copy
    t_hb_mirror makes).  Without the copy the right strokes run one column wider at the ties: 4K art 779 -> 1947..1949
    against 244 -> 610..611."""
    n, src = SL.hud_strip_w(g), SL.HUD_STRIP_NATIVE_W
    m = SL.hud_backdrop_col_map(n, src)
    gdi = [SL.nn_center_index(d, n, src) for d in range(n)]
    ties = set(SL.hud_backdrop_tie_cols(n, src))
    assert all(m[n - 1 - d] == src - 1 - m[d] for d in range(n))
    assert all(m[d] == (gdi[d - 1] if d in ties else gdi[d]) for d in range(n))
    assert all(gdi[d] != gdi[d - 1] for d in ties)                   # every tie copy is a real change
    if g == 40:
        assert [d for d in range(n) if gdi[d] == 779] == [1947, 1948, 1949]
        assert [d for d in range(n) if m[d] == 779] == [1948, 1949] == [n - 1 - d for d in (611, 610)]


@pytest.mark.parametrize("g", range(17, 65))
def test_scaling_box9_outer_nested_symmetric(g):
    """Box-9 outer frame: s(3) inside the right panel on both sides -> both channels to the tiled interior
    (P.l + 1 .. P.r - 2) are s(3) - 1, and the drawn box stays within 2 px of vanilla x g/16."""
    pl, pr = SL.hud_seed_x(779, g, True), SL.hud_seed_x(1020, g, True)
    l, t, r, b = SL.hud_box9_outer_rect(pl, pr, g)
    assert l - (pl + 1) == (pr - 2) - r == SL.popup_scale_floor(3, g) - 1
    assert abs(16 * l - 782 * g) < 32 and abs(16 * (r + 1) - 1017 * g) < 32
    assert (t, b) == ((211 * g) >> 4, (249 * g) >> 4)


# ============================================================================== 2. unit (Unicorn, the baked bytes)
@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def image(baked_exe):
    return Path(baked_exe).read_bytes()


class Chain:
    """The baked image under Unicorn; runs thunk_hud_seedscale from its call-redirect frame to Buffer_load_pcx."""

    def __init__(self, data: bytes, symtab):
        pe = pefile.PE(data=data)
        ib = pe.OPTIONAL_HEADER.ImageBase
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(HEAP, 0x100000)
        self.seedscale = SEEDSCALE_SITE + 5 + struct.unpack("<i", bytes(mu.mem_read(SEEDSCALE_SITE + 1, 4)))[0]
        assert self.seedscale == symtab["thunk_hud_seedscale"]
        tb = symtab["g_hud_seedtable"]
        words = []
        while True:
            w = struct.unpack("<H", bytes(mu.mem_read(tb + 2 * len(words), 2)))[0]
            if w == 0xFFFF:
                break
            words.append(w)
        self.words = words

    def run(self, g: int, natives: dict, regs: dict = None):
        mu = self.mu
        W, H = _res(g)
        for a, v in ((SW_VA, W), (SH_VA, H), (G_VA, 0)):
            mu.mem_write(a, struct.pack("<i", v))
        mu.mem_write(MAINWIN + 0xA00, b"\0" * 0x400)
        for f, v in natives.items():
            mu.mem_write(MAINWIN + f, struct.pack("<i", v))
        sp = HEAP + 0x80000
        mu.mem_write(sp, struct.pack("<I", SEEDSCALE_RET))
        regs = dict(regs or {})
        regs[UC_X86_REG_ESP] = sp
        for r, v in regs.items():
            mu.reg_write(r, v)
        mu.emu_start(self.seedscale, BUFFER_LOAD_PCX, count=100_000)
        assert mu.reg_read(UC_X86_REG_EIP) == BUFFER_LOAD_PCX
        assert mu.reg_read(UC_X86_REG_ESP) == sp and struct.unpack("<I", bytes(mu.mem_read(sp, 4)))[0] == SEEDSCALE_RET
        got_g = struct.unpack("<i", bytes(mu.mem_read(G_VA, 4)))[0]
        return got_g, {o: struct.unpack("<i", bytes(mu.mem_read(MAINWIN + o, 4)))[0] for o in range(0xA1C, 0xE00, 4)}


@pytest.fixture(scope="module")
def chain(image, symtab):
    return Chain(image, symtab)


def test_seedtable_marks_are_the_mirror_fields(chain):
    """97 words, the v1 order and offsets; bit 15 on exactly HUD_SEED_MIRROR_FIELDS."""
    assert len(chain.words) == 97
    assert {w & 0x7FFF for w in chain.words if w & 0x8000} == set(SL.HUD_SEED_MIRROR_FIELDS)
    assert all(w & 0x7FFF < 0x1000 and not w & 0x7000 for w in chain.words)


def _want(g, natives, words):
    """The law for the chain's output table (seedscale, then t_hud_btnpair, then t_hud_mi_square) on `natives`."""
    want = {}
    for w in words:
        f = w & 0x7FFF
        want[f] = SL.hud_seed_scaled(f, natives[f], g)
    if g > 16:
        w = (want[0xAA4] - want[0xA8C] - SL.popup_scale_floor(2, g)) >> 1   # t_hud_btnpair on whatever the seeds were
        want[0xA94] = want[0xA8C] + w
        want[0xA9C] = want[0xAA4] - w
        s20 = SL.popup_scale_floor(20, g)                     # t_hud_mi_square (its own guard pins it fully)
        for f in (0xA2C, 0xA3C, 0xA4C):
            want[f] = want[f + 8] - s20
        want[0xA30] = want[0xA38] - s20
        want[0xA48] = want[0xA40] + s20
        W, H = _res(g)
        sw, sh = SL.hud_strip_w(g), (257 * g) >> 4
        want[0xA1C] = (W - sw) >> 1
        want[0xA24] = want[0xA1C] + sw
        want[0xA28] = H
        want[0xA20] = H - sh
    return want


@pytest.mark.parametrize("g", ALL_G)                         # ensure_scale clamps g to 16..40
def test_chain_matches_the_law_on_random_natives(chain, g):
    """The real bytes on random natives (0..1100) == the law, every register and the arithmetic flags preserved."""
    rnd = random.Random(g)
    for _ in range(6):
        natives = {w & 0x7FFF: rnd.randint(0, 1100) for w in chain.words}
        regs = {r: rnd.getrandbits(32) for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                                                    UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESI)}
        regs[UC_X86_REG_EFLAGS] = 0x202 | (rnd.getrandbits(12) & 0x8D5)
        got_g, out = chain.run(g, natives, regs)
        assert got_g == g
        for r, v in regs.items():
            got = chain.mu.reg_read(r)
            assert (got & 0x8D5 == v & 0x8D5) if r == UC_X86_REG_EFLAGS else got == v, r
        want = _want(g, natives, chain.words) if g > 16 else {f: natives[f] for f in natives}
        for f, v in want.items():
            if g <= 16 and f in STRIP_RECT:
                continue
            assert out[f] == v, (g, hex(f), out[f], v)


# ============================================================================== 3. end to end (image_emu)
def _emu():
    import image_emu as E
    for k, n in (("LoadLibraryA", 1), ("GetProcAddress", 2), ("FreeLibrary", 1)):
        E.NARGS.setdefault(k, n)        # thunk_ed_immfix probes a DLL in MainWin_build; served as "absent" (0)
    return E


class Seeds:
    """One boot of an image; MainWin_build from its entry to the Buffer_load_pcx the seed chain tail-jumps (the seed
    stores, the derivation, seedscale -> btnpair -> mi_square), at any screen."""

    def __init__(self, exe):
        E = self.E = _emu()
        self.e = E.boot(str(exe), 1024, 768, popups=False)

    def table(self, W, H, pre=None):
        E, e = self.E, self.e
        e.w32(E.SW, W)
        e.w32(E.SH, H)
        e.w32(E.GSCALE, 0)
        uc = e.uc
        esp = E.STACK + E.STACK_SZ - 0x1000 - 4
        e.w32(esp, E.SENT)
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_ECX, MAINWIN)
        uc.reg_write(UC_X86_REG_EBP, 0)
        uc.emu_start(0x459680, BUFFER_LOAD_PCX, count=5_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == BUFFER_LOAD_PCX
        return e.s32(G_VA), {o: e.s32(MAINWIN + o) for o in range(0xA1C, 0xE00, 4)}


@pytest.fixture(scope="module")
def natives(bak_path):
    """The pristine image's own table (no seedscale: its values at the detour are the final ones)."""
    g, t = Seeds(bak_path).table(1024, 768)
    assert t[0xD80] == 4 and t[0xD88] == 245 and t[0xD90] == 779 and t[0xD98] == 1020
    return t


@pytest.fixture(scope="module")
def seeds_new(baked_exe):
    return Seeds(baked_exe)


@pytest.fixture(scope="module")
def seeds_unmarked(baked_exe, tmp_path_factory, symtab):
    """The bake with the bit-15 marks cleared in memory (the seedtable v1 = the per-edge floor of the v1 thunk)."""
    data = bytearray(Path(baked_exe).read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)
    off = pe.get_offset_from_rva(symtab["g_hud_seedtable"] - pe.OPTIONAL_HEADER.ImageBase)
    for i in range(97):
        w = struct.unpack_from("<H", data, off + 2 * i)[0]
        struct.pack_into("<H", data, off + 2 * i, w & 0x7FFF)
    p = tmp_path_factory.mktemp("hud_seed_unmarked") / "unmarked.exe"
    p.write_bytes(bytes(data))
    return Seeds(p)


@pytest.mark.parametrize("g", ALL_G)
def test_real_build_table_is_the_law(seeds_new, natives, chain, g):
    """The real MainWin_build on the bake: every table dword == the law of the pristine natives (the right-panel x on
    the mirror grid, the map buttons one width, the M / I column, the strip rect), the panels mirror on both edges,
    the two map buttons equally wide; g = 16 == the pristine table, dword for dword."""
    got_g, t = seeds_new.table(*_res(g))
    assert got_g == g
    if g == 16:
        assert t == natives
        return
    want = _want(g, natives, chain.words)
    for f in list(want) + [LEFT_PANEL, RIGHT_PANEL]:
        if f in MI_FIELDS:
            continue
        assert t[f] == want[f], (g, hex(f), t[f], want[f])
    for obj, f in SL.HUD_MI_SEED_FIELDS.items():
        assert tuple(t[f + 4 * k] for k in range(4)) == SL.hud_mi_btn_rect(obj, g)
    W = t[0xA24] - t[0xA1C]
    assert W == SL.hud_strip_w(g)
    assert t[0xD80] + t[0xD98] == W and t[0xD88] + t[0xD90] == W
    (wl, wr), (dl, dr) = SL.hud_map_btn_pair(g)
    assert (t[0xA8C], t[0xA94], t[0xA9C], t[0xAA4]) == (wl, wr, dl, dr)


@pytest.mark.parametrize("g", ALL_G)
def test_unmarked_bake_reproduces_the_defect(seeds_unmarked, natives, g):
    """Marks cleared (= v1): the right panel's left edge is the floor, one px left of the mirror at every g that is not
    a multiple of 16 -- 4K: 1947, the shot's da50 at 640 + 1947 = 2587 (mirror 2588)."""
    _g, t = seeds_unmarked.table(*_res(g))
    W = t[0xA24] - t[0xA1C]
    assert t[0xD90] == (779 * g) >> 4
    assert (t[0xD88] + t[0xD90] == W) == (g % 16 == 0)
    if g == 40:
        assert 640 + t[0xD90] == 2587 and 640 + (W - t[0xD88]) == 2588


#: Colour classes for stroke-run measurement: the console art's stroke pixels (canvas index 9) and the chrome's da50
#: K stroke (index 26) render the same green in the game (0x496c3d).  Pinned EMPIRICALLY from the user's shots, not from palette.pcx (whose index 9 is purple): the 4K F2 shot shows the
#: art column next to the right da50 stroke as part of it, audit-w2C gditie.py).  Every other index is its own class.
COLOUR_CLASS = {9: 26}
TIE_GS = [16, 19, 20, 22, 24, 25, 28, 36, 40]


def _cls(img):
    out = img.astype(np.int32)
    for a, b in COLOUR_CLASS.items():
        out[out == a] = b
    return out


def _paint(exe, g, retarget=None, art_only=False):
    """The real MainWin_build + MainWin_tile_panels (via its wrapped call site 0x45BC73, the engine's arg 1) + the box-9
    painter + the report console chrome, on one boot.  -> dict: art (canvas right after MainWin_build: the stretched,
    restriped, mirror-copied backdrop), tile (after tile_panels), hud (after box 9), rep (after the chrome), the
    hollow_flat rects keyed by the Buffer_box_sprite site, the 0x45BF39 engine rect, the ReportIf panel rects, seeds.
    retarget: (site VA, new call target) written over a call rel32 before anything runs (an in-memory variant)."""
    E = _emu()
    e = E.boot(str(exe), *_res(g))
    E.Files(e)
    if retarget:
        va, tgt = retarget
        assert bytes(e.uc.mem_read(va, 1)) == b"\xE8"
        e.uc.mem_write(va + 1, struct.pack("<i", tgt - (va + 5)))
    sites, hf, outer = [], [], []       # observers go in before any code runs: unicorn does not re-hook a cached block

    def on_box(e):
        esp = e.reg(UC_X86_REG_ESP)
        if e.reg(UC_X86_REG_ECX) == MAINWIN + 0x444:
            sites.append(e.r32(esp))
            if e.r32(esp) == 0x45BF3E:
                r = e.r32(esp + 4)
                outer.append(tuple(e.s32(r + 4 * k) for k in range(4)))

    def on_hf(e):
        r = e.r32(e.reg(UC_X86_REG_ESP) + 4)
        hf.append(tuple(e.s32(r + 4 * k) for k in range(4)))
    e.observe(0x5E2DD3, on_box)
    e.observe(0xA0C140, on_hf)                                # thunk_box_thick_hollow_flat (absent in the pristine)
    e.call(0x455610, count=0)                                 # load_interface (the console pcx art)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))           # Strings_init
    e.call(0x616A00, count=50_000_000)                        # labels_init
    e.call(0x459680, ecx=MAINWIN, count=0)                    # MainWin_build
    assert e.reg(UC_X86_REG_EIP) == E.SENT
    out = {"art": E.canvas_of(e, MAINWIN).copy()}
    if art_only:
        return out
    site = 0x45BC73
    e.call(site + 5 + e.s32(site + 1), ecx=MAINWIN, args=(1,), count=0)
    assert e.reg(UC_X86_REG_EIP) == E.SENT
    out["tile"] = E.canvas_of(e, MAINWIN).copy()
    del sites[:], hf[:], outer[:]
    e.call(0x45BE80, ecx=MAINWIN, count=0)                    # MainWin_draw_box9
    assert e.reg(UC_X86_REG_EIP) == E.SENT
    out["hud"] = E.canvas_of(e, MAINWIN).copy()
    out["box9"] = dict(zip(sites, hf)) if hf else {}
    out["outer"] = outer[0] if outer else None
    out["seeds"] = {o: e.s32(MAINWIN + o) for o in (0xD80, 0xD84, 0xD88, 0xD8C, 0xD90, 0xD94, 0xD98, 0xD9C)}
    ri = 0x885F38
    e.call(0x4AD170, ecx=ri, count=20_000_000)                # ReportIf_ctor
    e.call(0x4A3460, ecx=ri, count=0)                         # init_report_screen (panel copies +0x20 / +0x30)
    e.call(0x4A3D20, ecx=ri, count=0)                         # ReportIf_console_chrome (da50 panel frames)
    assert e.reg(UC_X86_REG_EIP) == E.SENT
    out["rep"] = E.canvas_of(e, MAINWIN).copy()
    out["rects"] = {k: tuple(e.s32(ri + k + 4 * i) for i in range(4)) for k in (0x20, 0x30)}
    return out


@pytest.fixture(scope="module")
def native_art(baked_exe):
    """Per native column c of the console art (the g = 16 canvas, == the pristine one: test_real_paint_mirrors[16]):
    whether it carries the stroke green on the panel-body rows while its mirror column 1023 - c does not (or the other
    way round) -- the art's own (vanilla) stroke-colour asymmetries, e.g. the left outer dotted separator (native 2,
    a 1A / 4F dither) that has no counterpart at 1021."""
    art = _cls(_paint(baked_exe, 16, art_only=True)["art"])[60:186]
    green = [bool((art[:, c] == COLOUR_CLASS[9]).any()) for c in range(1024)]
    return [green[c] != green[1023 - c] for c in range(1024)]


def _run_at(row, x):
    v, a, b = row[x], x, x
    while a > 0 and row[a - 1] == v:
        a -= 1
    while b < len(row) - 1 and row[b + 1] == v:
        b += 1
    return a, b


def _edge_runs_mirror(img, seeds, g, cmap, nat_differs, outer=True):
    """Every panel-body row: the stroke run (same colour class, abutting art columns included) through the left
    panel's last column vs the right panel's first (inner) -- and the outer pair -- mirror exactly about the strip
    centre, except where an extra column's native art column differs from its own mirror (vanilla's art).
    -> list of (row, left run, right run) that fail."""
    img = _cls(img)
    W = img.shape[1]
    bad = []
    pairs = [(seeds[0xD88] - 1, seeds[0xD90])] + ([(seeds[0xD80], seeds[0xD98] - 1)] if outer else [])
    for y in range((60 * g) >> 4, (186 * g) >> 4):
        row = img[y]
        for xl, xr in pairs:
            a, b = _run_at(row, xl)
            c, d = _run_at(row, xr)
            left, right = set(range(a, b + 1)), {W - 1 - x for x in range(c, d + 1)}
            if any(not nat_differs[cmap[x]] for x in left ^ right):
                bad.append((y, (a, b), (c, d)))
    return bad


@pytest.mark.parametrize("g", TIE_GS)
def test_real_paint_mirrors(baked_exe, bak_path, native_art, g):
    """The real paint chain at strips 1024 / 1216 / 1280 / 1408 / 1536 / 1600 / 1792 / 2304 / 2560 wide: the console
    backdrop is the mirror-symmetric stretch (every right-half tie column == its left neighbour), the panels' tiled
    interiors mirror about the strip centre, the inner and outer stroke runs -- abutting same-colour art columns
    included -- mirror on every panel-body row of the HUD and of the report chrome (exceptions only where vanilla's
    own art is asymmetric: native_art), the box-9 frames are the law and their channels to the panel art equal, the
    two report panels equally wide; g = 16 == the pristine image, canvas for canvas.  No whitelist."""
    p = _paint(baked_exe, g)
    if g == 16:
        q = _paint(bak_path, g)
        for k in ("art", "tile", "hud", "rep"):
            assert np.array_equal(p[k], q[k]), k
        assert p["rects"] == q["rects"]
        return
    art, tile, hud, rep, seeds = p["art"], p["tile"], p["hud"], p["rep"], p["seeds"]
    W = hud.shape[1]
    assert W == SL.hud_strip_w(g)
    cmap = SL.hud_backdrop_col_map(W, SL.HUD_STRIP_NATIVE_W)
    # (1) the backdrop: every right-half tie column is its left neighbour (the mirror map)
    for d in SL.hud_backdrop_tie_cols(W, SL.HUD_STRIP_NATIVE_W):
        assert np.array_equal(art[:, d], art[:, d - 1]), d
    # (2) tile interiors mirror
    y = (seeds[0xD84] + seeds[0xD8C]) // 2
    la, lb = _run_at(tile[y], (seeds[0xD80] + seeds[0xD88]) // 2)
    ra, rb = _run_at(tile[y], (seeds[0xD90] + seeds[0xD98]) // 2)
    assert (la + rb, lb + ra) == (W - 1, W - 1), (la, lb, ra, rb)
    # (3) stroke runs incl. abutting art: HUD (tiled panels) and report chrome, every panel-body row
    assert _edge_runs_mirror(tile, seeds, g, cmap, native_art) == []
    assert _edge_runs_mirror(rep, seeds, g, cmap, native_art) == []
    # (4) box 9: inner frame = the law, outer = hud_box9_outer_rect, channels to the panel art equal
    inner = SL.HUD_BOXFRAME_NAT[0x45BF66]
    assert p["box9"][0x45BF66] == SL.hud_boxframe_rect(0x45BF66, inner, g)
    assert p["outer"] == p["box9"][0x45BF3E] == SL.hud_box9_outer_rect(seeds[0xD90], seeds[0xD98], g)
    yb = (230 * g) >> 4
    cols = np.where(hud[yb] != tile[yb])[0]
    cols = cols[(cols >= seeds[0xD90]) & (cols < seeds[0xD98])]
    fill = {65, 198, 196, 34, 31}                             # the panel tile / box fill indices (audit box9x.py)
    x = seeds[0xD90]
    while tile[yb, x] not in fill:
        x += 1
    art_l = x - 1
    x = seeds[0xD98] - 1
    while tile[yb, x] not in fill:
        x -= 1
    art_r = x + 1
    assert cols.min() - art_l - 1 == art_r - cols.max() - 1, (cols.min(), cols.max(), art_l, art_r)
    # (5) report panels
    L, R = p["rects"][0x20], p["rects"][0x30]
    assert L[2] - L[0] == R[2] - R[0] and L[0] + R[2] == W and L[2] + R[0] == W
    if g == 40:                                               # the F2 shot's columns (strip at x = 640)
        row = _cls(rep)[(160 * g) >> 4]
        assert _run_at(row, seeds[0xD90]) == (2588 - 640, 2589 - 640)          # was 2587..2589 (3 px)
        assert _run_at(row, seeds[0xD88] - 1) == (1250 - 640, 1251 - 640)


@pytest.mark.parametrize("g", [24, 40])
def test_backdrop_mirror_copy_touches_only_the_ties(baked_exe, symtab, g):
    """The bake with the backdrop site pointed back at t_hud_backdrop (in memory): the stretched art differs exactly
    on right-half tie columns, and there the bake shows the unmirrored art's left neighbour.  The unmirrored stretch
    is the audit's C1: at g = 24 / 40 the right inner art stroke one column wider than the left."""
    new = _paint(baked_exe, g, art_only=True)["art"]
    old = _paint(baked_exe, g, retarget=(0x459F65, symtab["t_hud_backdrop"]), art_only=True)["art"]
    W = new.shape[1]
    ties = SL.hud_backdrop_tie_cols(W, SL.HUD_STRIP_NATIVE_W)
    diff = set(np.where((new != old).any(axis=0))[0].tolist())
    assert diff and diff <= set(ties)
    for d in ties:
        assert np.array_equal(new[:, d], old[:, d - 1])
