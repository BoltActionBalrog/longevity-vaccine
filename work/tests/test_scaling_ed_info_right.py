"""Scenario-editor info rect: its RIGHT pad (fix 24, law scaling_laws.editor_info_right, port t_ed_info_right).

Vanilla MainWin_build (0x45B480..0x45B4A0) builds the info rect +0xD6C between its two neighbours with one pad of 3 on
each side: l = red_union.r + 3 (@0x45B486), r = I.l - 3 (`sub eax, 3` @0x45B497; I = the HUD M / I / TOOLBAR column,
MainWin +0xA3C).  The left pad is scaled (editor_panel_seeds info_left, re-asserted at draw by thunk_ed_painter); the
right one stayed native, so at every g > 16 the box sat 2 px from the column but s(3) - 1 px from the red-brush frame
(4K 2 vs 6).  Law: r = I.l - s(3) -- both flanking channels equal at every g (editor_info_channel).

Real-image evidence (pinned below; harness = the real MainWin_build + MainWin_draw_center_mode mode 0x3EA on the
deployed 40c1e930 and the fix-24 bake, every write of +0xD74 and every read of +0xD6C..+0xD7B logged, the draw's one
read of +0xD74 @0x45B594 sees the law value; whole-canvas differential: only the info box's right stroke columns
change, the 0x3E8 canvas and every other MainWin table dword are identical): REAL.  The user's editor shots
(work\\screenshots, gitignored; pinned here, the PNG cross-check runs when present) show the deployed geometry: 4K
6 | 2, 1600x1200 4 | 2, 1920x1080 3 | 2, 1024x768 3 | 3.

The guard runs the baked image's own bytes 0x45B480..0x45B4A0 (the left-pad store, the I.l load, the new call and its
thunk) under Unicorn; the deployed bytes (`sub eax, 3`) and a floor-rounding thunk are the mutants it must kill.
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import scaling_laws as SL  # noqa: E402

MAINWIN = 0x7AE820
G_VA = 0x668740
T_ED_INFO_RIGHT = 0xA0C000 + 0x6170          # pcave2 0x6170 (patches.yaml symbol t_ed_info_right)
SLOT = 0x30
SITE = 0x45B497
SLICE = (0x45B480, 0x45B4A0)                 # mov edx,[esi+0xD64]; add edx,3; lea ecx,[esi+0x25040]; mov [eax],edx;
#                                              mov eax,[esi+0xA3C]; <site>; stop at `call 0x6162D0`
DEPLOYED_SITE = bytes.fromhex("83E8038986740D0000")
HEAP = 0x20000000

#: the real-image census (fix 24 harness, 64g x 48g screens): g -> (I.l, +0xD74 deployed, +0xD74 fix 24, K,
#: channel left deployed, right deployed, left fix 24, right fix 24) -- channels in device px on the info box's mid row:
#: red-brush union's right stroke -> info left stroke, info right stroke -> the column.
REAL = {
    16: (734, 731, 731, 1, 3, 3, 3, 3), 17: (780, 777, 777, 1, 2, 2, 2, 2), 18: (826, 823, 823, 1, 2, 2, 2, 2),
    19: (872, 869, 868, 1, 3, 2, 3, 3), 20: (917, 914, 913, 1, 3, 2, 3, 3), 21: (963, 960, 959, 1, 3, 2, 3, 3),
    22: (1009, 1006, 1005, 1, 3, 2, 3, 3), 23: (1055, 1052, 1051, 1, 3, 2, 3, 3), 24: (1101, 1098, 1097, 1, 3, 2, 3, 3),
    25: (1147, 1144, 1142, 2, 4, 2, 4, 4), 26: (1193, 1190, 1188, 2, 4, 2, 4, 4), 27: (1239, 1236, 1234, 2, 4, 2, 4, 4),
    28: (1284, 1281, 1279, 2, 4, 2, 4, 4), 29: (1330, 1327, 1325, 2, 4, 2, 4, 4), 30: (1376, 1373, 1370, 2, 5, 2, 5, 5),
    31: (1422, 1419, 1416, 2, 5, 2, 5, 5), 32: (1468, 1465, 1462, 2, 5, 2, 5, 5), 33: (1514, 1511, 1508, 2, 5, 2, 5, 5),
    34: (1560, 1557, 1554, 2, 5, 2, 5, 5), 35: (1606, 1603, 1599, 2, 6, 2, 6, 6), 36: (1651, 1648, 1644, 2, 6, 2, 6, 6),
    37: (1697, 1694, 1690, 2, 6, 2, 6, 6), 38: (1743, 1740, 1736, 2, 6, 2, 6, 6), 39: (1789, 1786, 1782, 2, 6, 2, 6, 6),
    40: (1835, 1832, 1828, 2, 6, 2, 6, 6)}

#: (shot, g, MainWin canvas -> screen (dx, dy), info mid row (canvas y), the stroke runs the shot shows on it in
#: canvas x [red-union right, info left, info right) and the first column-face x).  All taken on deployed geometry
#: (+0xD74 = I.l - 3; the 1600x1200 shots predate fix 23b's column, I.l = 1146 there).
SHOTS = (
    ("3840x2160_20261022-204501", 40, (640, 1518), 297, ((1371, 1373), (1379, 1381), (1831, 1833)), 1835),
    ("3840x2160_20261017-112756", 40, (640, 1518), 297, ((1371, 1373), (1379, 1381), (1831, 1833)), 1835),
    ("1600x1200_20261017-112821", 25, (0, 799), 185, ((857, 859), (863, 865), (1142, 1144)), 1146),
    ("1600x1200_20261016-000618", 25, (0, 799), 185, ((857, 859), (863, 865), (1142, 1144)), 1146),
    ("1920x1080_20261017-112848", 22, (256, 727), 163, ((755, 756), (759, 760), (1006, 1007)), 1009),
    ("1920x1080_20261016-000739", 22, (256, 727), 163, ((755, 756), (759, 760), (1006, 1007)), 1009),
    ("1024x768_20261016-002526", 16, (0, 511), 119, ((548, 549), (552, 553), (730, 731)), 734),
)
STROKE_RGB = {"314e2c": "red", "233b22": "info"}
FACE_COLOURS = {"78a4d4", "688cc4", "675bb5", "1c5063"}
SHOT_DIR = ROOT / "screenshots"


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return baked_exe.read_bytes()


class Slice:
    """The baked image under Unicorn; runs MainWin_build's info-rect slice SLICE with esi = MainWin."""

    def __init__(self, image: bytes):
        pe = pefile.PE(data=image)
        ib = pe.OPTIONAL_HEADER.ImageBase
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(HEAP, 0x200000)
        self.site = bytes(mu.mem_read(SITE, len(DEPLOYED_SITE)))
        self.thunk = bytes(mu.mem_read(T_ED_INFO_RIGHT, SLOT))

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def set_code(self, site: bytes = None, thunk: bytes = None):
        for va, want in ((SITE, site or self.site), (T_ED_INFO_RIGHT, thunk or self.thunk)):
            if bytes(self.mu.mem_read(va, len(want))) != want:
                self.mu.mem_write(va, want)
                self.mu.ctl_remove_cache(va, va + len(want))

    def run(self, g: int, col_l: int, red_r: int, site: bytes = None, thunk: bytes = None):
        """-> (+0xD6C l, +0xD74 r, eax, ecx, esp delta, the non-stack writes)."""
        mu = self.mu
        self.set_code(site, thunk)
        mu.mem_write(MAINWIN + 0xD60, struct.pack("<5i", 0, red_r, 0, 0, 0))
        mu.mem_write(MAINWIN + 0xA3C, struct.pack("<i", col_l))
        mu.mem_write(MAINWIN + 0xD74, struct.pack("<i", -12345))
        mu.mem_write(G_VA, struct.pack("<i", g))
        sp = HEAP + 0x100000
        regs = {UC_X86_REG_EAX: MAINWIN + 0xD6C, UC_X86_REG_ESI: MAINWIN, UC_X86_REG_ESP: sp,
                UC_X86_REG_EBX: 0x1111, UC_X86_REG_EDI: 0x2222, UC_X86_REG_EBP: 0x3333, UC_X86_REG_EDX: 0x4444}
        for r, v in regs.items():
            mu.reg_write(r, v)
        writes = []
        h = mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, s, v, u: writes.append(addr)
                        if not (sp - 0x100 <= addr < sp + 0x100) else None)
        try:
            mu.emu_start(SLICE[0], SLICE[1], count=200)
        finally:
            mu.hook_del(h)
        assert mu.reg_read(UC_X86_REG_EIP) == SLICE[1]
        for r in (UC_X86_REG_ESI, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == regs[r]
        return (self.r32(MAINWIN + 0xD6C), self.r32(MAINWIN + 0xD74), mu.reg_read(UC_X86_REG_EAX),
                mu.reg_read(UC_X86_REG_ECX), mu.reg_read(UC_X86_REG_ESP) - sp, sorted(set(writes)))


@pytest.fixture(scope="module")
def chain(baked):
    return Slice(baked)


def _red_r(g: int) -> int:
    return SL.editor_panel_seeds(g)["red_union"][2] if g > 16 else 549


@pytest.mark.parametrize("g", list(range(0, 49)) + [-1])
def test_law_editor_info_right(g):
    """editor_info_right: vanilla col - 3 at g <= 16; col - s(3) above, the same s(3) as the left pad -- so the info
    rect's two pads are equal at every g, and its visible channels (editor_info_channel) are too."""
    col = 1000
    if g <= 16:
        assert SL.editor_info_right(col, g) == col - 3 and SL.editor_info_channel(g) == 3
        return
    pad = SL.scale_px(SL.EDITOR_INFO_RIGHT_PAD, g)
    assert SL.editor_info_right(col, g) == col - pad
    assert SL.editor_info_channel(g) == pad - 1
    if g <= 40:
        seeds = SL.editor_panel_seeds(g)
        assert seeds["info_left"] - seeds["red_union"][2] == pad                  # the mirror pad (left)


def test_real_image_census_is_the_law():
    """The pinned real-image census: the fix-24 edge is the law on the live column, both channels equal
    editor_info_channel at every g, the deployed right edge was I.l - 3 (2 px at every g > 16, 3 | 3 at g = 16), the
    left channel and K did not move, and the visible channel is the pad less the K-wide box's inclusive R0 at g > 16."""
    for g, (col, d_dep, d_fix, k, l_dep, r_dep, l_fix, r_fix) in REAL.items():
        assert col == SL.hud_mi_column(g)[0], g
        assert d_fix == SL.editor_info_right(col, g) and d_dep == col - 3, g
        assert l_fix == r_fix == l_dep == SL.editor_info_channel(g), g
        assert r_dep == (3 if g == 16 else 2), g
        assert k == SL.stroke_width(g), g
        assert r_fix == col - d_fix - (g > 16) and r_dep == col - d_dep - (g > 16), g


def test_site_bytes(baked, bak_bytes):
    """The pristine site is vanilla's `sub eax, 3; mov [esi+0xD74], eax` after the I.l load; the bake keeps the load and
    calls the thunk, NOP-padded; the shipped thunk is assemble_ed_info_right.py's output."""
    pe = pefile.PE(data=bak_bytes)
    ib = pe.OPTIONAL_HEADER.ImageBase
    raw = pe.get_memory_mapped_image()
    assert raw[0x45B491 - ib:0x45B497 - ib] == bytes.fromhex("8B863C0A0000")
    assert raw[SITE - ib:SITE - ib + 9] == DEPLOYED_SITE
    s = Slice(baked)
    rel = (T_ED_INFO_RIGHT - (SITE + 5)) & 0xFFFFFFFF
    assert s.site == b"\xE8" + struct.pack("<I", rel) + b"\x90" * 4
    assert bytes(s.mu.mem_read(0x45B491, 6)) == bytes.fromhex("8B863C0A0000")
    pytest.importorskip("keystone", reason="keystone absent")
    import assemble_ed_info_right as asm
    want = asm.assemble().replace(struct.pack("<I", 0xDEADBE00), struct.pack("<I", G_VA))
    assert s.thunk[:len(want)] == want and s.thunk[len(want):] == bytes(SLOT - len(want))


@pytest.mark.parametrize("g", range(16, 41))
def test_info_right_real_order(chain, g):
    """The image's own bytes: +0xD74 = editor_info_right(I.l, g) on the live column, eax returns the same value (as
    vanilla's `mov`), ecx keeps the `this` of the following call, the stack balances, and the only non-stack writes are
    the left pad's +0xD6C and +0xD74.  The rect's pads are then equal (the left one is re-asserted at draw by
    thunk_ed_painter as editor_panel_seeds' info_left)."""
    col = SL.hud_mi_column(g)[0]
    left, right, eax, ecx, desp, writes = chain.run(g, col, _red_r(g))
    assert right == SL.editor_info_right(col, g) == REAL[g][2], g
    assert eax & 0xFFFFFFFF == right & 0xFFFFFFFF and ecx == MAINWIN + 0x25040 and desp == 0
    assert writes == [MAINWIN + 0xD6C, MAINWIN + 0xD74]
    assert left == _red_r(g) + 3                                         # the engine's native left store (unchanged)
    info_left = SL.editor_panel_seeds(g)["info_left"] if g > 16 else left
    assert info_left - _red_r(g) == col - right, g                       # equal pads: the symmetry rule


def test_info_right_mutants_fail(chain):
    """Mutation check: the deployed `sub eax, 3` fails exactly where s(3) != 3 (g >= 19); a floor-rounding thunk
    (lea edx,[edx*2+0] instead of +0xF: fl(3g/16)) fails exactly where half_down and floor disagree."""
    s3 = {g: SL.scale_px(3, g) for g in range(16, 41)}
    dep, flo = set(), set()
    floor_thunk = chain.thunk.replace(bytes.fromhex("8D14550F000000"), bytes.fromhex("8D145500000000"))
    assert floor_thunk != chain.thunk
    for g in range(16, 41):
        col = SL.hud_mi_column(g)[0]
        if chain.run(g, col, _red_r(g), site=DEPLOYED_SITE)[1] != SL.editor_info_right(col, g):
            dep.add(g)
        if chain.run(g, col, _red_r(g), thunk=floor_thunk)[1] != SL.editor_info_right(col, g):
            flo.add(g)
    assert dep == {g for g in s3 if s3[g] != 3} == set(range(19, 41)), sorted(dep)
    assert flo == {g for g in s3 if s3[g] != (3 * g) // 16} and flo, sorted(flo)
    col = SL.hud_mi_column(22)[0]
    assert chain.run(22, col, _red_r(22))[1] == SL.editor_info_right(col, 22)    # the image's own bytes are restored


def test_t_ed_info_right_contract(chain):
    """The thunk alone (entered by the site's E8): eax = eax_in - s(3) with g clamped to >= 16 (so g <= 16 and an
    unset g_popup_scale_num give vanilla's 3), stored at [esi + 0xD74]; every other register preserved; returns to
    the call's next instruction with the stack balanced; nothing else written."""
    rnd = random.Random(24)
    mu = chain.mu
    chain.set_code()
    for case in range(300):
        g = rnd.choice(list(range(-3, 60)) + [0, 16, 17, 40])
        regs = {r: rnd.getrandbits(32) for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                                                    UC_X86_REG_EDI, UC_X86_REG_EBP)}
        regs[UC_X86_REG_ESI] = MAINWIN
        sp = HEAP + 0x180000
        regs[UC_X86_REG_ESP] = sp
        mu.mem_write(G_VA, struct.pack("<i", g))
        mu.mem_write(sp, struct.pack("<I", SITE + 5))
        for r, v in regs.items():
            mu.reg_write(r, v)
        writes = []
        h = mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, s, v, u: writes.append(addr)
                        if not (sp - 0x40 <= addr < sp + 4) else None)
        try:
            mu.emu_start(T_ED_INFO_RIGHT, SITE + 5, count=50)
        finally:
            mu.hook_del(h)
        pad = SL.scale_px(3, max(g, 16))
        want = (regs[UC_X86_REG_EAX] - pad) & 0xFFFFFFFF
        assert mu.reg_read(UC_X86_REG_EIP) == SITE + 5 and mu.reg_read(UC_X86_REG_ESP) == sp + 4, case
        assert mu.reg_read(UC_X86_REG_EAX) == want and chain.r32(MAINWIN + 0xD74) & 0xFFFFFFFF == want, (case, g)
        for r in (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESI):
            assert mu.reg_read(r) == regs[r], (case, r)
        assert writes == [MAINWIN + 0xD74], (case, [hex(w) for w in writes])


@pytest.mark.parametrize("shot", SHOTS, ids=[s[0] for s in SHOTS])
def test_shots(shot):
    """The user's editor shots show the deployed geometry the census pins: red-union / info strokes and the column face
    on the info box's mid row, channels left = editor_info_channel(g) and right = 2 at g > 16 (3 | 3 at g = 16); the fix
    moves only the right stroke, to I.l - s(3) (inclusive R0 at g > 16), making the right channel equal the left."""
    name, g, (dx, dy), y, (red, il, ir), face = shot
    k = SL.stroke_width(g) if g > 16 else 1
    left, right = il[0] - red[1], face - ir[1]
    assert (red[1] - red[0], il[1] - il[0], ir[1] - ir[0]) == (k, k, k)
    assert left == SL.editor_info_channel(g) and right == (2 if g > 16 else 3), name
    assert ir[1] - 1 == face - 3 - (g <= 16)                                          # deployed: +0xD74 = I.l - 3
    new_r0 = SL.editor_info_right(face, g) - (g <= 16)                                # the fix's right stroke (last px)
    assert face - (new_r0 + 1) == left, name
    png = SHOT_DIR / f"terranx_pracx_{name}.png"
    if not png.exists():
        return
    from PIL import Image
    img = Image.open(png).convert("RGB")
    runs = []
    for xx in range(red[0] - 4, face + 2):
        c = "%02x%02x%02x" % img.getpixel((xx + dx, y + dy))
        if c in STROKE_RGB or c in FACE_COLOURS:
            kind = STROKE_RGB.get(c, "face")
            if runs and runs[-1][2] == kind and runs[-1][1] == xx:
                runs[-1][1] = xx + 1
            else:
                runs.append([xx, xx + 1, kind])
    got = [tuple(r) for r in runs]
    assert got == [(red[0], red[1], "red"), (il[0], il[1], "info"), (ir[0], ir[1], "info"), (face, face + 2, "face")], \
        (name, got)
