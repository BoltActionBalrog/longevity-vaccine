"""MULTIPLAYER SETUP lobby LAUNCH GAME / CANCEL (2026-10-24 wave-1 fix 27): a full face and one width for the pair.

Laws (scaling_laws.py, the source of truth):
  netwin_btn_pair   -- the pair's outer edges and rows on the rect table's floor images, ONE width
                       w = (fl(792g/16) - fl(317g/16) - fl(3g/16)) >> 1 for both, the odd px in the seam;
  flatbutton_nath_pinned / NETWIN_BTN_OBJECTS -- their 2D-zoom source is pinned to vanilla's 0x14 rows: their device
                       height fl(232g/16) - fl(212g/16) (netwin_btn_h) is fl(20g/16) + 1 at some g, where the CEIL
                       inverse recovers 21 and the 20-row art left the bottom row key (1920x1080: 27 of 28 rows,
                       pixel-exact vs the user shot 20261024-124117).
Ports: t_nw_btnpair (assemble_netwin_btnpair.py, CALLed from thunk_nw_rectscale v2) and t_btn_nath_pin's two new
compares (assemble_tutbtn_post.py).

Proof layers, all on the REAL bytes of a module-scoped bake:
  1. law sweeps (g 16..64) incl. the per-edge-floor mutant the law replaces;
  2. UNIT (Unicorn on the baked image, the thunks at their real addresses): t_nw_btnpair == the law on a pre-scaled
     table at every g, registers / stack as the call site needs; the pin admits exactly the two objects (plus the
     tabs + Council it had) and only when armed;
  3. END TO END (netwin_lobby_emu.py on image_emu.py: the real builder and the real FlatButton draw chain): the two
     BaseButton_init windows == the law and equal widths at every g 16..40, the faces fill their windows in all
     three draw states; g = 16 draws exactly the pristine image's buttons; the bake with the two fix-27 edits
     reverted in memory reproduces both defects (1080p 27 of 28 rows; 2560x1440 442 | 443).

COST: one boot per image per worker (~2 s: new, pristine, reverted); each g item re-runs the builder and draws 6
canvases on that boot (~0.3 s).  The module splits across xdist by measured cost.
"""
from __future__ import annotations

import shutil
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

LAUNCH, CANCEL = SL.NETWIN_BTN_OBJECTS
ALL_G = range(16, 41)
NETWIN = 0x80A6F8
G_VA = 0x668740


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def images(tmp_path_factory, bak_path, symtab, baked_exe):
    """{'new': the bake (conftest's shared `baked_exe`), 'before': the bake with fix 27 reverted in memory (the two pin
    compares -> a never-matching object, the rectscale CALL -> 5 NOPs), 'pristine': the .bak}."""
    d = tmp_path_factory.mktemp("netwin_btnpair")
    dst = Path(baked_exe)
    data = bytearray(dst.read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)

    def off(va):
        return pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    pin = symtab["t_btn_nath_pin"]
    for obj in SL.NETWIN_BTN_OBJECTS:
        k = bytes(data[off(pin):off(pin) + 0x70]).index(b"\x81\xFE" + struct.pack("<I", obj))
        data[off(pin) + k + 2:off(pin) + k + 6] = struct.pack("<I", 0xFFFFFFF0)
    rs = symtab["thunk_nw_rectscale"]
    call = off(rs) + 107
    assert data[call] == 0xE8 and bytes(data[call + 5:call + 7]) == b"\x61\x8B", "rectscale v2 tail shape"
    data[call:call + 5] = b"\x90" * 5
    (d / "before.exe").write_bytes(bytes(data))
    shutil.copy2(bak_path, d / "pristine.exe")
    return {"new": str(dst), "before": str(d / "before.exe"), "pristine": str(d / "pristine.exe"),
            "new_bytes": dst.read_bytes()}


# ============================================================================== 1. law
@pytest.mark.parametrize("g", range(16, 65))
def test_law_pair_is_equal_and_on_the_floor_edges(g):
    a, b = SL.netwin_btn_pair(g)
    (l0, t0, r0, b0), (l1, _t1, r1, _b1) = SL.NETWIN_BTN_RECTS[LAUNCH], SL.NETWIN_BTN_RECTS[CANCEL]
    f = SL.popup_scale_floor
    assert a[2] - a[0] == b[2] - b[0], "one width"
    assert (a[0], b[2]) == (f(l0, g), f(r1, g)), "outer edges on the floor images"
    assert a[1] == b[1] == f(t0, g) and a[3] == b[3] == f(b0, g), "rows unchanged"
    seam = b[0] - a[2]
    assert seam in (f(SL.NETWIN_BTN_SEAM, g), f(SL.NETWIN_BTN_SEAM, g) + 1), (g, seam)
    assert abs((a[2] - a[0]) - 236 * g / 16) <= 1, "width within 1 px of vanilla x g/16"
    if g == 16:
        assert (a, b) == (SL.NETWIN_BTN_RECTS[LAUNCH], SL.NETWIN_BTN_RECTS[CANCEL])


def test_law_replaces_the_per_edge_floor_exactly_where_it_was_unequal():
    f = SL.popup_scale_floor
    unequal = [g for g in range(17, 41) if (f(553, g) - f(317, g)) != (f(792, g) - f(556, g))]
    assert unequal == [21, 26, 27, 30, 37], unequal
    for g in range(16, 41):
        a, b = SL.netwin_btn_pair(g)
        if g not in unequal:      # the law moves nothing where the pair already matched
            assert (a[2], b[0]) == (f(553, g), f(556, g)), g


@pytest.mark.parametrize("g", range(17, 41))
def test_law_pin_where_the_ceil_inverse_overshoots(g):
    h = SL.netwin_btn_h(g)
    for obj in SL.NETWIN_BTN_OBJECTS:
        assert SL.flatbutton_nath_pinned(obj)
        assert SL.flatbutton_zoom_src_h(obj, h, g) == SL.BTN_BAR_NATIVE_H
    if SL.btn_native_dim(h, g) > SL.BTN_BAR_NATIVE_H:      # unpinned: the 20-row art falls short of the window
        assert SL.flatbutton_zoom_face_rows(h, SL.btn_native_dim(h, g)) < h
    assert SL.flatbutton_zoom_face_rows(h, SL.BTN_BAR_NATIVE_H) == h


def test_law_1080p_shot_row_count():
    assert SL.netwin_btn_h(22) == 28 and SL.btn_native_dim(28, 22) == 21
    assert SL.flatbutton_zoom_face_rows(28, 21) == 27            # the user shot 20261024-124117: 27 of 28


# ============================================================================== 2. unit
class Img:
    def __init__(self, data: bytes):
        pe = pefile.PE(data=data)
        self.ib = pe.OPTIONAL_HEADER.ImageBase
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = self.ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(0x10000000, 0x200000)

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


@pytest.fixture(scope="module")
def img(images):
    return Img(images["new_bytes"])


REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
        UC_X86_REG_EBP)


def test_rectscale_calls_btnpair_before_the_popad(img, symtab):
    rs, bp = symtab["thunk_nw_rectscale"], symtab["t_nw_btnpair"]
    code = bytes(img.mu.mem_read(rs + 107, 13))
    assert code[0] == 0xE8 and rs + 112 + struct.unpack("<i", code[1:5])[0] == bp
    assert code[5:] == bytes.fromhex("618B4E0C8B5604C3"), "popad; the replayed chat-attach reads; ret"
    assert bytes(img.mu.mem_read(0x4829CE, 6)) == b"\xE8" + struct.pack("<i", rs - 0x4829D3) + b"\x90"


@pytest.mark.parametrize("g", range(1, 65))
def test_btnpair_asm_is_the_law(img, symtab, g):
    mu, bp = img.mu, symtab["t_nw_btnpair"]
    obj = 0x10100000
    f = SL.popup_scale_floor
    table = {}
    for base, rect in ((0xC34, SL.NETWIN_BTN_RECTS[LAUNCH]), (0xC44, SL.NETWIN_BTN_RECTS[CANCEL])):
        for i, v in enumerate(rect):
            table[base + 4 * i] = f(v, g) if g > 16 else v
            img.w32(obj + base + 4 * i, table[base + 4 * i])
    img.w32(G_VA, g)
    esp = 0x10080000
    img.w32(esp, 0x10000000)
    mu.mem_write(0x10000000, b"\xF4")
    for r in REGS:
        mu.reg_write(r, 0x55AA0000 + r)
    mu.reg_write(UC_X86_REG_EBX, obj)
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.emu_start(bp, 0x10000000, count=200)
    assert mu.reg_read(UC_X86_REG_ESP) == esp + 4 and mu.reg_read(UC_X86_REG_EBX) == obj
    assert mu.reg_read(UC_X86_REG_ESI) == 0x55AA0000 + UC_X86_REG_ESI          # esi: rectscale's popad reads it
    got = (tuple(img.r32(obj + 0xC34 + 4 * i) for i in range(4)), tuple(img.r32(obj + 0xC44 + 4 * i) for i in range(4)))
    want = SL.netwin_btn_pair(g) if g > 16 else (SL.NETWIN_BTN_RECTS[LAUNCH], SL.NETWIN_BTN_RECTS[CANCEL])
    assert got == want, (g, got, want)


def test_pin_admits_the_lobby_pair(img, symtab):
    """t_btn_nath_pin on the baked bytes: g_btn_nativeH / [esi+0x4C8] := 0x14 / -0x14 for exactly the pinned objects
    (law flatbutton_nath_pinned) and only when armed (g_btn_pending == 1 && g > 16); flags and registers kept."""
    mu, pin = img.mu, symtab["t_btn_nath_pin"]
    pend, nath = symtab["g_btn_pending"], symtab["g_btn_nativeH"]
    resume = 0x607E85
    probes = set(SL.NETWIN_BTN_OBJECTS) | {o + d for o in SL.NETWIN_BTN_OBJECTS for d in (-4, -1, 1, 4, 0xB4C)}
    probes |= set(SL.RW_TAB_BTN_OBJECTS) | {SL.COUNCIL_BTN_RANGE[0], SL.COUNCIL_BTN_RANGE[1], 0x7AF620, 0x7B016C}
    saved = bytes(mu.mem_read(resume, 1))
    mu.mem_write(resume, b"\xF4")
    try:
        for esi in sorted(probes):
            for g, armed in ((22, 1), (40, 1), (16, 1), (22, 0)):
                img.w32(G_VA, g)
                img.w32(pend, armed)
                img.w32(nath, 21)
                img.w32(esi + 0x4C8, -21)
                esp = 0x10080000
                for r in REGS:
                    mu.reg_write(r, 0x66000000 + r)
                mu.reg_write(UC_X86_REG_ESI, esi)
                mu.reg_write(UC_X86_REG_ESP, esp)
                mu.reg_write(UC_X86_REG_EFLAGS, 0x2D7 & ~0x10)
                mu.emu_start(pin, resume, count=100)
                assert mu.reg_read(UC_X86_REG_ESP) == esp
                assert mu.reg_read(UC_X86_REG_EFLAGS) & 0xCD5 == (0x2D7 & ~0x10) & 0xCD5
                hit = armed == 1 and g > 16 and SL.flatbutton_nath_pinned(esi)
                assert (img.r32(nath), img.r32(esi + 0x4C8)) == ((20, -20) if hit else (21, -21)), (hex(esi), g, armed)
    finally:
        mu.mem_write(resume, saved)


# ============================================================================== 3. end to end
@pytest.fixture(scope="module")
def lobby_new(images):
    import netwin_lobby_emu as NL
    return NL.Lobby(images["new"])


@pytest.fixture(scope="module")
def lobby_before(images):
    import netwin_lobby_emu as NL
    return NL.Lobby(images["before"])


def _measure(lobby, g):
    import netwin_lobby_emu as NL
    wins = lobby.build(g)
    faces = {}
    for obj in SL.NETWIN_BTN_OBJECTS:
        for st in (0, 1, 2):
            p = lobby.draw(obj, st)
            assert p.shape == (wins[obj][3], wins[obj][2])
            faces[obj, st] = len(NL.face_rows(p))
    return wins, faces


@pytest.mark.parametrize("g", ALL_G)
def test_e2e_windows_are_the_law_and_faces_fill(lobby_new, g):
    wins, faces = _measure(lobby_new, g)
    a, b = SL.netwin_btn_pair(g)
    assert wins[LAUNCH] == (a[0], a[1], a[2] - a[0], a[3] - a[1])
    assert wins[CANCEL] == (b[0], b[1], b[2] - b[0], b[3] - b[1])
    assert wins[LAUNCH][2:] == wins[CANCEL][2:], "one size for the pair"
    for (obj, st), rows in faces.items():
        assert rows == wins[obj][3], (hex(obj), st, rows, wins[obj][3])


@pytest.mark.parametrize("g", (21, 22, 26, 30, 37))
def test_e2e_reverted_bake_reproduces_both_defects(lobby_before, g):
    wins, faces = _measure(lobby_before, g)
    f = SL.popup_scale_floor
    assert wins[LAUNCH][2] == f(553, g) - f(317, g) and wins[CANCEL][2] == f(792, g) - f(556, g)
    if g != 22:
        assert wins[LAUNCH][2] != wins[CANCEL][2], "the per-edge floor: widths 1 px apart"
    h = SL.netwin_btn_h(g)
    short = SL.flatbutton_zoom_face_rows(h, SL.btn_native_dim(h, g))
    assert faces[LAUNCH, 0] == short
    if g == 22:
        assert (faces[LAUNCH, 0], h) == (27, 28), "the user's 1920x1080 shot"


def test_e2e_g16_is_pristine(images):
    import netwin_lobby_emu as NL
    new, pri = NL.Lobby(images["new"], 1024, 768), NL.Lobby(images["pristine"], 1024, 768)
    wn, wp = new.build(16), pri.build(16)
    assert {o: wn[o] for o in SL.NETWIN_BTN_OBJECTS} == {o: wp[o] for o in SL.NETWIN_BTN_OBJECTS}
    for obj in SL.NETWIN_BTN_OBJECTS:
        for st in (0, 1, 2):
            for box in (False, True):
                assert np.array_equal(new.draw(obj, st, box), pri.draw(obj, st, box)), (hex(obj), st, box)
