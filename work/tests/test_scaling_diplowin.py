"""The multiplayer negotiation window (DiploWin 0x73ACD8) layout law, scaling_laws.dw_*.

  * VANILLA ORACLE: the PRISTINE builder cascade 0x443F4C..0x444617 (DiploWin_build, pure rect arithmetic + four
    UnionRect imports) runs under Unicorn on the mapped .bak image; every stored rect and the GraphicWin_init
    x/y/w/h args must equal the law at g=16 -- the g=16 identity is vanilla's own bytes, not a transcription.
  * SWEEP: g 16..40 over real resolutions -- no collapsed / negative / off-window rect, one pinned bar height,
    panels pinned to the art, rings = unions +/- dp(3), frame abutting the rails, chat boxes mixed-space.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

NATIVE_DC0 = (262, 66, 763, 234)       # MainWin seed +0xDC0 at 1024x768 (the console centre box)
NATIVE_STRIP = 213
RES = [(1024, 768), (1366, 768), (1152, 864), (1600, 900), (1280, 1024), (1600, 1200), (1920, 1080), (2560, 1440),
       (3840, 2160)]
BARS = (0xF4C, 0xF7C, 0xF8C, 0xF9C, 0xFBC, 0xFFC, 0x100C, 0x101C, 0x102C, 0x103C, 0x104C, 0x105C,
        0x106C, 0x107C, 0x108C, 0x109C)


def world(sw: int, sh: int, g: int):
    strip = (NATIVE_STRIP * g) >> 4 if g > 16 else NATIVE_STRIP
    dc0 = tuple(SL.dp(v, g) for v in NATIVE_DC0)
    x, y, w, h = SL.dw_window_rect(sw, sh, strip, g)
    return strip, dc0, (x, y, w, h), SL.dw_layout(w, h, dc0, g)


# ---- vanilla oracle --------------------------------------------------------------------------------------------
unicorn = pytest.importorskip("unicorn")
pefile = pytest.importorskip("pefile")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP  # noqa: E402

import config  # noqa: E402

THIS = 0x03000000
STACK, SP0 = 0x02500000, 0x02508000
UNION_STUB = 0x02600000
IAT_UNIONRECT = 0x669328
MAPWIN = 0x9156B0                      # the window's parent (read through its vptr at 0x4445EB)
START, STOP = 0x443F4C, 0x444617
SW_VA, SH_VA, STRIP_VA, DC0_VA, D80_VA, D90_VA = 0x9B7B1C, 0x9B7B20, 0x7AF59C, 0x7AF5E0, 0x7AF5A0, 0x7AF5B0


@pytest.fixture(scope="module")
def image():
    bak = pathlib.Path(config.terranx_bak())
    if not bak.exists():
        pytest.skip("pristine .bak not present")
    pe = pefile.PE(str(bak))
    return [(0x400000 + s.VirtualAddress, max(s.Misc_VirtualSize, s.SizeOfRawData), s.get_data())
            for s in pe.sections]


def run_prefix(image, sw: int, sh: int):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    lo = 0x400000
    hi = max(va + size for va, size, _ in image)
    uc.mem_map(lo, (hi - lo + 0xFFF) & ~0xFFF)
    for va, _, data in image:
        uc.mem_write(va, data)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(THIS, 0x10000)
    uc.mem_map(UNION_STUB, 0x1000)
    uc.mem_write(UNION_STUB, b"\xC2\x0C\x00")                       # ret 0xC (stdcall; body done by the hook)
    uc.mem_write(IAT_UNIONRECT, struct.pack("<I", UNION_STUB))
    uc.mem_write(MAPWIN, struct.pack("<I", UNION_STUB + 0x100))      # MapWin vptr -> a fake vtbl whose +4 (this-adj) = 0
    uc.mem_write(UNION_STUB + 0x104, struct.pack("<I", 0))
    for va, v in ((SW_VA, sw), (SH_VA, sh), (STRIP_VA, NATIVE_STRIP)):
        uc.mem_write(va, struct.pack("<i", v))
    uc.mem_write(DC0_VA, struct.pack("<4i", *NATIVE_DC0))
    uc.mem_write(D80_VA, struct.pack("<4i", 4, 56, 245, 252))
    uc.mem_write(D90_VA, struct.pack("<4i", 779, 56, 1020, 252))
    uc.reg_write(UC_X86_REG_ESI, THIS)
    uc.reg_write(UC_X86_REG_EBP, SP0 + 0x100)
    uc.reg_write(UC_X86_REG_ESP, SP0)

    def rect(va):
        return list(struct.unpack("<4i", bytes(uc.mem_read(va, 16))))

    def hook(u, addr, size, _):
        if addr == UNION_STUB:                                      # UnionRect(dst, a, b) -> TRUE
            sp = u.reg_read(UC_X86_REG_ESP)
            _, dst, a, b = struct.unpack("<4I", bytes(u.mem_read(sp, 16)))
            ra, rb = rect(a), rect(b)
            if ra[0] >= ra[2] or ra[1] >= ra[3]:
                out = rb
            elif rb[0] >= rb[2] or rb[1] >= rb[3]:
                out = ra
            else:
                out = [min(ra[0], rb[0]), min(ra[1], rb[1]), max(ra[2], rb[2]), max(ra[3], rb[3])]
            u.mem_write(dst, struct.pack("<4i", *out))
        elif addr == STOP:
            u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(START, 0, count=200000)
    assert uc.reg_read(UC_X86_REG_EIP) == STOP
    sp = uc.reg_read(UC_X86_REG_ESP)
    x, y, w, h, _, _, parent = struct.unpack("<4i3I", bytes(uc.mem_read(sp, 28)))
    fields = {off: tuple(rect(THIS + off)) for off in SL.dw_layout(w, h, NATIVE_DC0, 16)}
    return (x, y, w, h), fields, parent


@pytest.mark.parametrize("sw,sh", [(1024, 768), (800, 600), (1280, 1024), (1600, 1200), (3840, 2160)])
def test_scaling_pristine_builder_is_the_g16_law(image, sw, sh):
    win, fields, parent = run_prefix(image, sw, sh)
    assert win == SL.dw_window_rect(sw, sh, NATIVE_STRIP, 16)
    assert parent == MAPWIN
    assert fields == SL.dw_layout(win[2], win[3], NATIVE_DC0, 16)


def test_scaling_g16_is_the_decompiled_vanilla():
    x, y, w, h = SL.dw_window_rect(1024, 768, NATIVE_STRIP, 16)
    assert (x, y, w, h) == (112, 172, 832, 383)
    lay = SL.dw_layout(w, h, NATIVE_DC0, 16)
    assert lay[0xEDC] == (23, 0, 777, 383) and lay[0xF5C] == (30, 53, 399, 253)
    assert lay[0xFAC] == (27, 260, 399, 330) and lay[0xFCC] == (401, 260, 773, 330)
    assert [lay[o][0] for o in (0xFFC, 0x100C, 0x101C)] == [130, 310, 490]
    assert [lay[o][0] for o in (0x104C, 0x105C, 0x108C, 0x109C)] == [30, 214, 404, 588]
    assert lay[0xF3C] == (266, 70, 759, 207) and lay[0xF2C] == (266, 210, 759, 230)


# ---- sweep -----------------------------------------------------------------------------------------------------
CASES = [(sw, sh, g) for sw, sh in RES for g in sorted({SL.popup_g(sw, sh), 16})]   # the g each resolution really runs at


@pytest.mark.parametrize("sw,sh,g", CASES)
def test_scaling_window_does_not_collapse(sw, sh, g):
    strip, _, (x, y, w, h), _ = world(sw, sh, g)
    assert w == SL.dp(SL.DW_W, g)
    assert h == SL.dp(SL.DW_HBASE, g) - strip and h > SL.dp(300, g)     # vanilla 383 x g/16, never the 64-px sliver
    assert y >= 0 and y + h == sh - strip                              # sits on the console strip


@pytest.mark.parametrize("sw,sh,g", CASES)
def test_scaling_every_rect_is_inside_the_window(sw, sh, g):
    _, _, (_, _, w, h), lay = world(sw, sh, g)
    for off, (l, t, r, b) in lay.items():
        assert l < r and t < b, hex(off)
        if off not in (0xF3C, 0xF2C):
            assert 0 <= l and r <= w and 0 <= t and b <= h, hex(off)


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_bars_share_one_height(g):
    _, _, (_, _, w, h), lay = world(3840, 2160, g)
    for off in BARS:
        assert lay[off][3] - lay[off][1] == SL.dp(SL.DW_BAR_H, g), hex(off)


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_panels_frame_the_art_and_rings_are_unions(g):
    _, _, (_, _, w, h), lay = world(3840, 2160, g)
    k, d = SL.stroke_width(g), (lambda v: SL.dp(v, g))
    for p in (0xF5C, 0xF6C):
        assert lay[p][3] - lay[p][1] == 2 * k + d(SL.DW_ART[1])
        assert lay[p][2] - lay[p][0] >= 2 * k + d(SL.DW_ART[0])
    gap = lay[0xFAC][1] - lay[0xF5C][3]
    assert d(SL.DW_IN) <= gap <= d(SL.DW_IN) + 6                      # the remainder lands here, never negative
    for ring, members in ((0xFAC, (0xF9C, 0x102C, 0x103C, 0x104C, 0x105C)),
                          (0xFCC, (0xFBC, 0x106C, 0x107C, 0x108C, 0x109C))):
        u = (min(lay[m][0] for m in members), min(lay[m][1] for m in members),
             max(lay[m][2] for m in members), max(lay[m][3] for m in members))
        p3 = d(SL.DW_PAD)
        assert lay[ring] == (u[0] - p3, u[1] - p3, u[2] + p3, u[3] + p3)
    assert lay[0xFBC][2] == lay[0x109C][2] and lay[0xF9C][2] == lay[0x105C][2]


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_frame_abuts_the_rails(g):
    _, _, (_, _, w, h), lay = world(3840, 2160, g)
    left, right = SL.dw_frame_lr(w, g)
    assert lay[0xEDC] == (left, 0, right, h)
    if g > 16:
        assert right == ((((w << 4) // g) - 0x37) * g) >> 4             # railscale's double-floor right anchor
        assert left == ((15 * g) >> 4) + ((8 * g) >> 4)                # the two left strips' drawn extent


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_chat_boxes_are_mixed_space(g):
    dc0 = tuple(SL.dp(v, g) for v in NATIVE_DC0)
    chat, edit = SL.dw_chat_rects(dc0, g)[0xF3C], SL.dw_chat_rects(dc0, g)[0xF2C]
    d = lambda v: SL.dp(v, g)                                         # noqa: E731
    assert chat == (dc0[0] + d(4), dc0[1] + d(4), dc0[2] - d(4), dc0[3] - d(0x1B))
    assert edit == (chat[0], dc0[3] - d(0x18), chat[2], dc0[3] - d(4))


@pytest.mark.parametrize("sw,sh,g", CASES)
def test_scaling_proportionate_to_vanilla(sw, sh, g):
    """Every rect edge within 3 device px of vanilla x g/16 (the window-local origin and h scale uniformly)."""
    _, _, (_, _, w, h), lay = world(sw, sh, g)
    nx, ny, nw, nh = SL.dw_window_rect(1024, 768, NATIVE_STRIP, 16)
    nat = SL.dw_layout(nw, nh, NATIVE_DC0, 16)
    for off, rect in lay.items():
        if off in (0xF3C, 0xF2C):
            continue
        for v, n in zip(rect, nat[off]):
            assert abs(v - n * g / 16) <= 3, (hex(off), rect, nat[off])


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_right_column_is_flush(g):
    """Vanilla right-aligns the right panel, the name box and the last button column on the inner column (770 at
    g=16): the cumulative cells keep that at every g, and each 4-cell row keeps its 2 | 8 | 2 gaps."""
    _, _, (_, _, w, h), lay = world(3840, 2160, g)
    fl, fr = SL.dw_frame_lr(w, g)
    ir = fr - SL.dp(SL.DW_IN, g)
    assert lay[0xF6C][2] == lay[0xF8C][2] == lay[0x109C][2] == lay[0x107C][2] == lay[0xFBC][2] == ir
    ga, gb = SL.dp(SL.DW_GAP, g), SL.dp(SL.DW_GAP_MID, g)
    for row in ((0x104C, 0x105C, 0x108C, 0x109C), (0x102C, 0x103C, 0x106C, 0x107C)):
        assert [lay[b][0] - lay[a][2] for a, b in zip(row, row[1:])] == [ga, gb, ga]
        widths = [lay[o][2] - lay[o][0] for o in row]
        assert max(widths) - min(widths) <= 1
