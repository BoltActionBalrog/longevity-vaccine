"""Differential: the BAKED thunk_q16_fill_width v6 + thunk_s54_restripe must
agree with the scaling_laws reference (q16_fill_width / s54_hatch_keyed /
s54_row_color).  Emulates the REAL assembled bytes (scripts/
assemble_editorwho.py, sentinels left in place) under Unicorn.

Ground truth vectors are the live trace values from
frida_scenedit_popupdiag.log (4K g=40 + 1024x768 g=16 runs, 2026-08-14).

Skips (does not fail) if keystone/unicorn are absent.
Run with -p no:faulthandler (unicorn mem_map AV dumps are benign noise).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import (q16_fill_width, s54_hatch_keyed, s54_row_color,  # noqa: E402
                          stripe_period, hatch_pair_for, hatch_row_color)

keystone = pytest.importorskip("keystone", reason="keystone absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

import assemble_editorwho as AE  # noqa: E402

PAGE = 0x1000

# sentinel data addresses (as left in the assembled bytes)
G      = 0x71111111   # g_popup_scale_num
BOXNUM = 0x72111111   # g_boxw_num (== 40 in the shipped build)
FLD_L  = 0x73111111
FLD_R  = 0x73222222
FLD_BW = 0x73333333
GWINIT = 0x74111111   # push target; emulation stop address
PDS    = 0x006A721C
FE_DST = 0x7A111111
FE_X   = 0x7A222222
FE_Y   = 0x7A333333
FE_W   = 0x7A444444
FE_H   = 0x7A555555
RM_XE  = 0x7B111111
RM_YE  = 0x7B222222
FE_CALL = 0x75333333  # fe_pair_remap sentinel — stubbed with RET

ESI_OBJ = 0x00300000  # t16 self (q16) / scratch
STACK   = 0x00200000
BUF_OBJ = 0x00310000  # Buffer object (s54)
PIXELS  = 0x00320000  # pixel data (s54)


def _pages(*addrs):
    return sorted({a & ~(PAGE - 1) for a in addrs})


@pytest.fixture(scope="module")
def uc_q16():
    code = AE.assemble("thunk_q16_fill_width")["thunk_q16_fill_width"]
    off, blob = code
    va = AE.PCAVE2 + off
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in _pages(va, G, BOXNUM, FLD_L, FLD_R, FLD_BW, GWINIT, PDS,
                       ESI_OBJ, STACK):
        mu.mem_map(base, PAGE)
    mu.mem_write(va, blob)
    return mu, va


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _run_q16(uc, g, w, x, box_w, mrg_r, count, y=117, h=385, stash=(0x7777, 0x8888, None), pds=0):
    """Run the thunk as the attach site does.  The fieldpads stash cells, g_boxw_num and
    PopupDialogState are poked with hostile values: v6 must neither read nor write them."""
    mu, va = uc
    L, R, bw = stash
    bw = box_w if bw is None else bw          # a MATCHING stash: the v3..v5 mirror trigger
    _w32(mu, G, g); _w32(mu, BOXNUM, 0x5A5A)
    _w32(mu, FLD_L, L); _w32(mu, FLD_R, R); _w32(mu, FLD_BW, bw)
    _w32(mu, PDS, pds)
    _w32(mu, ESI_OBJ + 0x1f8, count)
    _w32(mu, ESI_OBJ + 0x478, box_w)          # [popup+0x30BC] box width
    _w32(mu, ESI_OBJ + 0x4ac, 0x6666)         # [popup+0x30F0] left margin: not an input
    _w32(mu, ESI_OBJ + 0x4b0, mrg_r)          # [popup+0x30F4] right margin
    _w32(mu, ESI_OBJ + 0x188, w)
    _w32(mu, ESI_OBJ + 0x190, w)
    sp = STACK + PAGE - 0x40
    mu.mem_write(sp, (0x0060D29E).to_bytes(4, "little"))  # site ret
    _w32(mu, sp + 4, x); _w32(mu, sp + 8, y)
    _w32(mu, sp + 12, w); _w32(mu, sp + 16, h)
    regs = {UC_X86_REG_ESP: sp, UC_X86_REG_ESI: ESI_OBJ, UC_X86_REG_ECX: 0x1234ABCD,
            UC_X86_REG_EDX: 0x0BADF00D}
    for r_, v in regs.items():
        mu.reg_write(r_, v)
    mu.emu_start(va, GWINIT, count=200)       # stops when RET lands in GraphicWin_init
    esp = mu.reg_read(UC_X86_REG_ESP)
    assert esp == sp, "the tail's push/ret must leave the site's frame in place"
    assert _r32(mu, esp) == 0x0060D29E
    assert mu.reg_read(UC_X86_REG_ECX) == 0x1234ABCD      # window this
    assert mu.reg_read(UC_X86_REG_EDX) == 0x0BADF00D
    assert mu.reg_read(UC_X86_REG_ESI) == ESI_OBJ
    assert (_r32(mu, esp + 4), _r32(mu, esp + 8), _r32(mu, esp + 16)) == (x, y, h)
    assert (_r32(mu, FLD_L), _r32(mu, FLD_R), _r32(mu, FLD_BW)) == (L, R, bw), "stash untouched"
    return {
        "w_arg": _r32(mu, esp + 12),
        "d5c": _r32(mu, ESI_OBJ + 0x188),
        "d64": _r32(mu, ESI_OBJ + 0x190),
    }


def _all(r):
    assert r["w_arg"] == r["d5c"] == r["d64"]
    return r["w_arg"]


# ---- q16 v6 cases (each mirrors a law vector) -------------------------------

def test_q16_quit_4k_meets_the_ok_bar(uc_q16):
    # trace: box 1886, margins 82 / 167, x 82, attach w 653 -> the OK..CANCEL span 1637
    assert _all(_run_q16(uc_q16, 40, 653, 82, 1886, 167, 2)) == 1637 \
        == q16_fill_width(40, 653, 82, 1886, 167, 2)


def test_q16_single_row_council_picker(uc_q16):
    # the council propose picker with ONE motion at 4K (shot 20260928-235853: bars 1099..2735)
    assert _all(_run_q16(uc_q16, 40, 653, 82, 1886, 167, 1)) == 1637


def test_q16_picker_4k_content_edge(uc_q16):
    # SELECT A FACTION (pds 6, stash L=40 R=1564 boxw=1591 in the trace): neither matters any more
    r = _run_q16(uc_q16, 40, 595, 51, 1591, 52, 7, stash=(40, 1564, 1591), pds=6)
    assert _all(r) == 1488 == q16_fill_width(40, 595, 51, 1591, 52, 7)


def test_q16_mirror_and_box_arms_are_gone(uc_q16):
    # the v5 field mirror (66 + 1298 - 164 = 1200) and box arm (1255 - 50 = 1205) vectors: the
    # width now comes from the right margin alone, whatever the stash / pds say
    for pds in (0, 6):
        assert _all(_run_q16(uc_q16, 40, 400, 82, 1449, 167, 3, stash=(66, 1298, 1449), pds=pds)) \
            == 1449 - 167 - 82
        assert _all(_run_q16(uc_q16, 40, 477, 25, 1255, 30, 3, stash=(66, 1298, 999), pds=pds)) == 1200


def test_q16_native_noop(uc_q16):
    for w, x, box, mr, n in ((597, 19, 637, 21, 7), (655, 33, 755, 67, 2), (100, 33, 755, 67, 2)):
        assert _all(_run_q16(uc_q16, 16, w, x, box, mr, n)) == w
        assert _all(_run_q16(uc_q16, 8, w, x, box, mr, n)) == w


def test_q16_count_gate_and_only_widen(uc_q16):
    assert _all(_run_q16(uc_q16, 40, 595, 51, 1591, 52, 1)) == 1488
    assert _all(_run_q16(uc_q16, 40, 595, 51, 1591, 52, 0)) == 595
    assert _all(_run_q16(uc_q16, 40, 595, 51, 1591, 52, -1)) == 595
    assert _all(_run_q16(uc_q16, 40, 2000, 82, 1886, 167, 7)) == 2000       # span < w: keep w
    assert _all(_run_q16(uc_q16, 40, 1637, 82, 1886, 167, 7)) == 1637       # span == w: keep w
    assert _all(_run_q16(uc_q16, 40, 300, 82, 100, 167, 7)) == 300          # negative span: keep w


@pytest.mark.parametrize("g", list(range(16, 41)) + [45, 50, 60, 64])
@pytest.mark.parametrize("count", [1, 2, 7])
@pytest.mark.parametrize("margins", [(33, 67), (19, 21), (10, 12), (0, 0)])
def test_q16_sweep_matches_law(uc_q16, g, count, margins):
    nl_, nr_ = margins
    ml, mr = (nl_ * g) >> 4, (nr_ * g) >> 4
    content = (655 * g) >> 4
    box = ml + content + mr
    for w in (655, 654, 653, 400):
        for x in (ml, ml + 4):
            got = _all(_run_q16(uc_q16, g, w, x, box, mr, count))
            assert got == q16_fill_width(g, w, x, box, mr, count)
            if g > 16 and x == ml:
                assert got == content and x + got == box - mr


def test_q16_baked_bytes_are_the_assembled_source():
    """The yaml cave content (what the patcher writes) == assemble_editorwho's output with the
    sentinels resolved: the emulated bytes above are the shipped ones."""
    import yaml
    from apply_patches import _yaml_load  # the production loader (libyaml)
    import apply_patches as ap
    doc = _yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    off, blob = AE.assemble("thunk_q16_fill_width")["thunk_q16_fill_width"]
    want = bytes(blob)
    for sent, ph in AE.SENT.items():
        name = ph[len("{abs32:"):-1]
        want = want.replace(sent.to_bytes(4, "little"), symtab[name].to_bytes(4, "little"))
    baked = None
    for cave in doc["code_caves"]:
        base = cave["virtual_addr"]
        base = int(base, 16) if isinstance(base, str) else base
        for c in cave.get("contents", []) or []:
            if c["id"] == "thunk_q16_fill_width":
                o = c["offset"]
                o = int(o, 16) if isinstance(o, str) else o
                assert base + o == AE.PCAVE2 + off
                baked = ap.ByteTemplate(c["bytes"]).resolve(base + o, symtab)
    assert baked == want
    assert len(baked) <= 0x98, "must stay inside the v4 slot (t_bw_wheel_down starts at 0x110A0)"
    # v6 reads the lever and the popup's own fields only
    for sent in (BOXNUM, FLD_L, FLD_R, FLD_BW):
        assert sent.to_bytes(4, "little") not in bytes(blob)
    assert PDS.to_bytes(4, "little") not in bytes(blob)


# ---- s54_restripe -----------------------------------------------------------

@pytest.fixture(scope="module")
def uc_s54():
    code = AE.assemble("thunk_s54_restripe")["thunk_s54_restripe"]
    off, blob = code
    va = AE.PCAVE2 + off
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in _pages(va, G, FE_DST, FE_X, FE_Y, FE_W, FE_H, RM_XE, RM_YE,
                       FE_CALL, BUF_OBJ, STACK):
        mu.mem_map(base, PAGE)
    mu.mem_map(PIXELS, 0x10000)
    mu.mem_write(va, blob)
    mu.mem_write(FE_CALL & ~(PAGE - 1), b"\xC3" * PAGE)  # fe stub: RET anywhere
    return mu, va


W_PIX, H_PIX = 64, 32
STRIDE = 64


def _run_s54(uc, g, *, fill, x=0, y=0, w=W_PIX, h=H_PIX,
             clipL=0, clipT=0, xend=None, yend=None):
    mu, va = uc
    _w32(mu, G, g)
    _w32(mu, FE_DST, BUF_OBJ)
    _w32(mu, FE_X, x); _w32(mu, FE_Y, y)
    _w32(mu, FE_W, w); _w32(mu, FE_H, h)
    _w32(mu, RM_XE, w if xend is None else xend)
    _w32(mu, RM_YE, h if yend is None else yend)
    _w32(mu, BUF_OBJ + 0x54, PIXELS)
    _w32(mu, BUF_OBJ + 0x4a8, STRIDE)
    _w32(mu, BUF_OBJ + 0x80, STRIDE)                     # Buffer W / -H: s54 v3 clamps its prescan to them
    _w32(mu, BUF_OBJ + 0x84, (-H_PIX) & 0xFFFFFFFF)
    _w32(mu, BUF_OBJ + 0x20, clipL)
    _w32(mu, BUF_OBJ + 0x24, clipT)
    mu.mem_write(PIXELS, bytes(fill))
    sp = STACK + PAGE - 8
    mu.mem_write(sp, (0x00A10390).to_bytes(4, "little"))  # fake devfill ret
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.emu_start(va, 0x00A10390, count=2_000_000)
    return bytes(mu.mem_read(PIXELS, STRIDE * H_PIX))


def _hatch(w=W_PIX, h=H_PIX, stride=STRIDE):
    out = bytearray(stride * h)
    for yy in range(h):
        row = 0x54 if (yy % 2 == 0) else 0x41
        for xx in range(w):
            out[yy * stride + xx] = row
    return out


@pytest.mark.parametrize("g", [22, 25, 40])
def test_s54_restripes_hatch(uc_s54, g):
    out = _run_s54(uc_s54, g, fill=_hatch())
    for yy in range(H_PIX):
        want = s54_row_color(yy, g)
        row = out[yy * STRIDE: yy * STRIDE + W_PIX]
        assert row == bytes([want]) * W_PIX, f"g={g} row {yy}"


def test_s54_solid_54_untouched(uc_s54):
    fill = bytes([0x54]) * (STRIDE * H_PIX)
    out = _run_s54(uc_s54, 40, fill=fill)
    assert out[:STRIDE * H_PIX] == fill, "solid 0x54 (art) must never fire (mate key)"
    assert not s54_hatch_keyed(8 * W_PIX, 0, W_PIX)


def test_s54_solid_41_untouched(uc_s54):
    fill = bytes([0x41]) * (STRIDE * H_PIX)
    out = _run_s54(uc_s54, 40, fill=fill)
    assert out[:STRIDE * H_PIX] == fill, "solid black pre-fill must never fire"


def test_s54_native_noop(uc_s54):
    fill = bytes(_hatch())
    out = _run_s54(uc_s54, 16, fill=fill)
    assert out[:STRIDE * H_PIX] == fill


def test_s54_non_pair_bytes_pass_through(uc_s54):
    fill = bytearray(_hatch())
    # a green frame line + text pixels inside the rect
    for xx in range(W_PIX):
        fill[5 * STRIDE + xx] = 0x1F
    fill[8 * STRIDE + 10] = 0xE2
    out = _run_s54(uc_s54, 40, fill=bytes(fill))
    assert out[5 * STRIDE: 5 * STRIDE + W_PIX] == bytes([0x1F]) * W_PIX
    assert out[8 * STRIDE + 10] == 0xE2
    # while its pair neighbors DID restripe
    assert out[8 * STRIDE + 11] == s54_row_color(8, 40)


def test_s54_respects_clamped_bounds(uc_s54):
    # fe's clamps say walk only x<[xend], y<[yend]; clip L/T raise the start.
    out = _run_s54(uc_s54, 40, fill=_hatch(), clipL=8, clipT=4,
                   xend=W_PIX - 8, yend=H_PIX - 4)
    for yy in range(H_PIX):
        for xx in range(W_PIX):
            b = out[yy * STRIDE + xx]
            inside = (4 <= yy < H_PIX - 4) and (8 <= xx < W_PIX - 8)
            if inside:
                assert b == s54_row_color(yy, 40)
            else:
                assert b == (0x54 if yy % 2 == 0 else 0x41), (xx, yy)


def test_s54_period_is_the_one_stripe_law():
    # Same law as every stripe field: 2-row stripes (P = 4) at every popup g
    # (user decision 2026-10-04; the proportional period was 5 at g=40).
    assert stripe_period(40) == 4 == stripe_period(22)


# ---- s54_restripe v2 (2026-09-12): the report row / title-band pair 0xC2/0x41 --------------

def _hatch_c2(w=W_PIX, h=H_PIX, stride=STRIDE):
    out = bytearray(stride * h)
    for yy in range(h):
        row = 0xC2 if (yy % 2 == 0) else 0x41
        for xx in range(w):
            out[yy * stride + xx] = row
    return out


@pytest.mark.parametrize("g", [22, 25, 40])
def test_s54_v2_restripes_the_report_row_hatch_c2(uc_s54, g):
    """The user's 4K/1600/1920 shots (2026-09-12): BASE STATUS rows / list rows / title band tile
    194 (13,28,48) over black 1:1 at every res -> the P-law rows of every other popup interior."""
    out = _run_s54(uc_s54, g, fill=_hatch_c2())
    for yy in range(H_PIX):
        want = hatch_row_color(0xC2, yy, g)
        assert out[yy * STRIDE: yy * STRIDE + W_PIX] == bytes([want]) * W_PIX, f"g={g} row {yy}"
    assert hatch_pair_for({0xC2: 4 * W_PIX, 0x41: 4 * W_PIX}, W_PIX) == 0xC2


def test_s54_v2_arrow_face_c2_c5_untouched(uc_s54):
    """0xC2 is ALSO the scrollbar-arrow face dither's top member (0xC2/0xC5, thunk_btn_stripes' own
    pass): no 0x41 in the rect -> the mate rule keeps every pixel."""
    fill = bytearray(STRIDE * H_PIX)
    for yy in range(H_PIX):
        for xx in range(W_PIX):
            fill[yy * STRIDE + xx] = 0xC2 if yy % 2 == 0 else 0xC5
    out = _run_s54(uc_s54, 40, fill=bytes(fill))
    assert out[:STRIDE * H_PIX] == bytes(fill)
    assert hatch_pair_for({0xC2: 4 * W_PIX, 0xC5: 4 * W_PIX}, W_PIX) is None


def test_s54_v2_solid_c2_untouched(uc_s54):
    fill = bytes([0xC2]) * (STRIDE * H_PIX)
    out = _run_s54(uc_s54, 40, fill=fill)
    assert out[:STRIDE * H_PIX] == fill, "solid 0xC2 must never fire (mate key)"


def test_s54_v2_54_hatch_still_wins_and_c2_passes_through_in_it(uc_s54):
    """A 0x54 hatch with a few stray 0xC2 pixels: the 0x54 pair is keyed (tried first), 0xC2 untouched."""
    fill = bytearray(_hatch())
    fill[2 * STRIDE + 7] = 0xC2
    fill[3 * STRIDE + 9] = 0xC2
    out = _run_s54(uc_s54, 40, fill=bytes(fill))
    for yy in range(H_PIX):
        for xx in range(W_PIX):
            v = fill[yy * STRIDE + xx]
            assert out[yy * STRIDE + xx] == (0xC2 if v == 0xC2 else s54_row_color(yy, 40)), (xx, yy)


def test_s54_v2_pass_through_and_bounds_with_c2(uc_s54):
    fill = bytearray(_hatch_c2())
    for xx in range(W_PIX):
        fill[5 * STRIDE + xx] = 0x1F
    fill[8 * STRIDE + 10] = 0xE2
    out = _run_s54(uc_s54, 40, fill=bytes(fill), clipL=8, clipT=4, xend=W_PIX - 8, yend=H_PIX - 4)
    for yy in range(H_PIX):
        for xx in range(W_PIX):
            b = out[yy * STRIDE + xx]; v = fill[yy * STRIDE + xx]
            inside = (4 <= yy < H_PIX - 4) and (8 <= xx < W_PIX - 8)
            if v in (0xC2, 0x41) and inside:
                assert b == hatch_row_color(0xC2, yy, 40), (xx, yy)
            else:
                assert b == v, (xx, yy)


def test_s54_v2_native_noop_c2(uc_s54):
    fill = bytes(_hatch_c2())
    out = _run_s54(uc_s54, 16, fill=fill)
    assert out[:STRIDE * H_PIX] == fill


def test_s54_v2_slot_and_size():
    """RELOCATED 0x110A0 -> 0x13BA0 (v1 had 38B slack to thunk_rail_gate @0x11200); the new slot is the
    free run after thunk_popup_fieldpads (ends 0x13B94) up to g_se_vpdone @0x14000 (cave_map --fit)."""
    off, blob = AE.assemble("thunk_s54_restripe")["thunk_s54_restripe"]
    assert off == 0x13BA0 and off + len(blob) <= 0x14000
    assert 340 <= len(blob) <= 400
