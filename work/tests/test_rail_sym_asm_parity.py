"""W3B rail scrollbar rework: the t_rsb_* thunks (scripts/assemble_rail_sym.py) run from the BAKED bytes under Unicorn
and equal the laws in scaling_laws.py, at every g and canvas width (2026-10-25; the user-approved "rail scrollbar
rework" = fix 20 item D).

  t_rsb_cmap     == rail_col_map (axis_map_chrome's bands, the channel / plate zones on the grip span, the right half
                 the mirror of the left): every column, every register kept
  t_rsb_bar      == (rail_strip_x + b, Wc - 2b) (rail_layout v4)
  t_rsb_israil   ZF = 1 for exactly the five rail-family bars (ProdPicker / ReportWin statics, FileDlg+0x3DD8,
                 the DW PartPicker+0xA14 (v4, W9C F53), Popup+0x3230 of their own parent), each RAIL-FITTED; 0 for a
                 popup's other (heap) bar, a wrong offset, another vtable, an unfitted bar, a null parent
  t_rsb_grip     a rail bar's grip: w = rail_grip_span(R - L, 18, g), centred in the thumb rect on both axes, drawn
                 w x w by mirror_nn_src on both axes (t_rsb_gripdraw: mirror-exact rows) and its pair restriped on
                 the stripe law over exactly the drawn rect; any other bar, or an unusual grip sprite: t_sbt_grip
                 with the stack untouched, the canvas byte-identical to calling t_sbt_grip directly
  t_rsb_mnn      == mirror_nn_src, every register but eax kept
  t_rsb_zoom     a rail bar's arrow: the native plate columns land on rail_grip_span(aw, F, g) by the centre-NN of
                 rail_arrow_col_map (mirror_nn_src), rows centre-NN (StretchBlt's), margins key; any other button /
                 g <= 16: the
                 KSB wrapper thunk_btn_bandstripe with the stack untouched
  t_rsb_blit     Wc outside 1..256 -> the engine Buffer_draw_2 with the stack untouched (its column / row law is
                 tests/test_rail_sbstrip_abut_asm.py's, against the real engine blit)
plus the yaml pin: the t_rsb_* entries ARE the assembler's templates, inside the W3B region, and the three retargets
(thunk_rail_bake -> t_rsb_blit, t_btn_edgeprobe's tail -> t_rsb_zoom, thunk_sb_thumb -> t_rsb_grip) are in place; and
the zoom CHAIN (2dscale -> W2D's t_btn_edgeprobe -> t_rsb_zoom -> thunk_btn_bandstripe) run from the probe's entry: the
probe resets its per-compose state for every button, a rail arrow is zoomed by W3B and never reaches the stretch, any
other button reaches thunk_btn_bandstripe with the caller's frame and ebx / esi / edi / ebp untouched.
~ms per case; one Unicorn per test function, the image mapped once per module.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
pytest.importorskip("keystone", reason="keystone absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_rail_sym as RS  # noqa: E402
import assemble_stripes_btn as SB  # noqa: E402

PCAVE2 = 0x00A0C000
G_VA, PERIOD_VA = 0x00668740, 0x0066879C
STACK, HEAP, MARKER = 0x30000000, 0x40000000, 0x30000000
REGS = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x4444}
KEY = 9


@pytest.fixture(scope="module")
def image(baked_exe):
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = ap.build_symbol_table(symbols, caves)
    pe = pefile.PE(str(baked_exe), fast_load=True)
    img = bytes(pe.get_memory_mapped_image())
    pe.close()
    return img, symtab


class Rig:
    def __init__(self, image, g):
        img, self.sym = image
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(0x400000, (len(img) + 0xFFF) & ~0xFFF)
        mu.mem_write(0x400000, img)
        mu.mem_map(STACK, 0x100000)
        mu.mem_map(HEAP, 0x800000)
        mu.mem_write(MARKER, b"\xF4")
        self.bump = HEAP + 0x1000
        self.set_g(g)
        self.hits = []

    def set_g(self, g):
        self.g = g
        self.w32(G_VA, g)
        self.w32(PERIOD_VA, SL.stripe_period(g) if g > 16 else 2)

    def w32(self, a, v):
        self.mu.mem_write(a, int(v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, a):
        return int.from_bytes(self.mu.mem_read(a, 4), "little")

    def alloc(self, n):
        a = self.bump
        self.bump += (n + 0xFFF) & ~0xFFF
        return a

    def stub(self, va, ret_imm):
        """Park a recorder at va: logs (va, esp, the stack's first 14 dwords), returns like `ret ret_imm`."""
        def hook(m, a, s, u):
            sp = m.reg_read(UC_X86_REG_ESP)
            self.hits.append((a, sp, [int.from_bytes(m.mem_read(sp + 4 * i, 4), "little") for i in range(14)]))
            ret = int.from_bytes(m.mem_read(sp, 4), "little")
            m.reg_write(UC_X86_REG_ESP, sp + 4 + ret_imm)
            m.reg_write(UC_X86_REG_EIP, ret)
        self.mu.hook_add(UC_HOOK_CODE, hook, begin=va, end=va)

    def run(self, entry, stack, regs):
        mu = self.mu
        sp = STACK + 0x80000
        for i, v in enumerate(stack):
            self.w32(sp + 4 * i, v)
        mu.reg_write(UC_X86_REG_ESP, sp)
        for r, v in {**REGS, **regs}.items():
            mu.reg_write(r, v & 0xFFFFFFFF)
        mu.emu_start(entry, MARKER, count=20_000_000)
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER
        return sp

    def zf(self):
        return bool(self.mu.reg_read(UC_X86_REG_EFLAGS) & 0x40)

    def buffer(self, w, h, stride, fill):
        buf, data = self.alloc(0x600), self.alloc(stride * h + 64)
        self.mu.mem_write(data, bytes([fill]) * (stride * h))
        for off, v in ((0x54, data), (0x80, w), (0x84, -h), (0x4A8, stride), (0x20, 0), (0x24, 0), (0x28, w),
                       (0x2C, h), (0x30, 0), (0x34, 0), (0x38, w), (0x3C, h)):
            self.w32(buf + off, v)
        return buf, data

    def plane(self, data, w, h, stride):
        raw = bytes(self.mu.mem_read(data, stride * h))
        return [raw[y * stride:y * stride + w] for y in range(h)]


def _widths(g):
    out = {SL.scale_px(520, g) + i for i in range(0, 12)} | set(range(max(200, 18 * g), 70 * g, 61))
    out |= {SL.rw_canvas_w((650 * g) >> 4, g)}
    return sorted(out)


# ---- t_rsb_cmap / t_rsb_bar ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", list(range(17, 97)))
def test_cmap_and_bar_equal_the_laws(image, g):
    rig = Rig(image, g)
    cm = RS.va("g_rsb_cmap")
    for cw in _widths(g):
        rig.run(RS.va("t_rsb_cmap"), [MARKER], {UC_X86_REG_EAX: cw, UC_X86_REG_ECX: 0x55, UC_X86_REG_EDX: 0x66})
        wc = rig.mu.reg_read(UC_X86_REG_EAX)
        law = SL.rail_col_map(cw, g)
        assert wc == len(law) == SL.rail_col_w(cw, g), (g, cw)
        assert list(rig.mu.mem_read(cm, wc)) == law, (g, cw)
        assert [rig.mu.reg_read(r) for r in (UC_X86_REG_ECX, UC_X86_REG_EDX, *REGS)] == [0x55, 0x66, *REGS.values()]
        rig.run(RS.va("t_rsb_bar"), [MARKER], {UC_X86_REG_EAX: cw, UC_X86_REG_EDX: 0x77})
        b = SL.rail_bar_inset(cw, g)
        assert (rig.mu.reg_read(UC_X86_REG_EAX), rig.mu.reg_read(UC_X86_REG_ECX)) == \
            (SL.rail_strip_x(cw, g) + b, wc - 2 * b), (g, cw)
        assert rig.mu.reg_read(UC_X86_REG_EDX) == 0x77
        lay = SL.rail_layout(cw, 490 * g // 16, g)
        assert (lay["sb_x"], lay["sb_w"]) == (SL.rail_strip_x(cw, g) + b, wc - 2 * b)


# ---- t_rsb_israil ----------------------------------------------------------------------------------------------------
def _family(rig):
    """{name: (bar ptr, expected ZF)} with real parents laid out (the statics' parents are the ProdPicker 0x6A8044 /
    ReportWin 0x876478).  Every family bar is FITTED: its client width [+0x4C4] is the law's bar width for its
    parent's canvas width [+0x4C4] (v3, audit LOW 3); the *_unfitted bars carry the vanilla 24 instead."""
    g = rig.g
    cw = SL.scale_px(560, g)
    bw = SL.rail_col_w(cw, g) - 2 * SL.rail_bar_inset(cw, g)

    def bar_of(parent, bar, fitted=True):
        rig.w32(bar + 0xC4, parent)
        rig.w32(parent + 0x4C4, cw)
        rig.w32(bar + 0x4C4, bw if fitted else 24)
        return bar
    out = {"picker": (bar_of(0x6A8044, RS.PICKER_SB), True), "report": (bar_of(0x876478, RS.REPORT_SB), True)}
    fd = rig.alloc(0x8000)
    rig.w32(fd, RS.FILEDLG_VTBL)
    out["filedlg"] = (bar_of(fd, fd + 0x3DD8), True)
    out["filedlg_wrong_offset"] = (bar_of(fd, fd + 0x3230), False)
    fd2 = rig.alloc(0x8000)
    rig.w32(fd2, RS.FILEDLG_VTBL)
    out["filedlg_unfitted"] = (bar_of(fd2, fd2 + 0x3DD8, fitted=False), False)
    pp = rig.alloc(0x5000)                                               # the DW PartPicker (W9C F53): vtbl-keyed
    rig.w32(pp, RS.PARTPICKER_VTBL)
    out["partpicker"] = (bar_of(pp, pp + RS.PARTPICKER_SB), True)
    out["partpicker_wrong_offset"] = (bar_of(pp, pp + 0x3230), False)
    pp2 = rig.alloc(0x5000)
    rig.w32(pp2, RS.PARTPICKER_VTBL)
    out["partpicker_unfitted"] = (bar_of(pp2, pp2 + RS.PARTPICKER_SB, fitted=False), False)
    ppo = rig.alloc(0x5000)
    rig.w32(ppo, 0x66B2BC)                                               # another vtable: not the picker
    out["partpicker_other_vtbl"] = (bar_of(ppo, ppo + RS.PARTPICKER_SB), False)
    pv, pop = rig.alloc(0x100), rig.alloc(0x8000)
    rig.w32(pv + 4, RS.POPUP_SHOW)
    rig.w32(pop, pv)
    out["popup"] = (bar_of(pop, pop + 0x3230), True)
    out["popup_heap_bar"] = (bar_of(pop, rig.alloc(0x3000)), False)   # the ability-list heap bar: parent = the popup
    out["popup_wrong_offset"] = (bar_of(pop, pop + 0x3DD8), False)
    pop2 = rig.alloc(0x8000)
    rig.w32(pop2, pv)
    out["popup_unfitted"] = (bar_of(pop2, pop2 + 0x3230, fitted=False), False)
    ov, other = rig.alloc(0x100), rig.alloc(0x8000)
    rig.w32(ov + 4, 0x5EABCD)
    rig.w32(other, ov)
    out["other_window"] = (bar_of(other, other + 0x3230), False)
    orphan = rig.alloc(0x3000)
    rig.w32(orphan + 0xC4, 0)
    out["no_parent"] = (orphan, False)
    return out


def test_rail_family_law_is_the_assemblers_list():
    """scaling_laws.RAIL_FAMILY_VTBL_BARS (the law's vtable-keyed members) == the (vtable, bar offset) pairs
    t_rsb_israil is assembled from, and both vtable constants appear in its bytes as `cmp dword ptr [ecx], imm32`."""
    assert set(SL.RAIL_FAMILY_VTBL_BARS) == {(RS.FILEDLG_VTBL, 0x3DD8), (RS.PARTPICKER_VTBL, RS.PARTPICKER_SB)}
    code = RS.assemble("t_rsb_israil")
    for vt, off in SL.RAIL_FAMILY_VTBL_BARS:
        assert b"\x81\x39" + vt.to_bytes(4, "little") in code, hex(vt)              # cmp dword ptr [ecx], vtbl
        assert b"\x8D\x91" + off.to_bytes(4, "little") in code, hex(off)            # lea edx, [ecx + bar offset]


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_israil_admits_exactly_the_fitted_rail_family(image, g):
    rig = Rig(image, g)
    for name, (bar, want) in _family(rig).items():
        rig.run(RS.va("t_rsb_israil"), [MARKER], {UC_X86_REG_EAX: bar, UC_X86_REG_ECX: 0x55, UC_X86_REG_EDX: 0x66})
        assert rig.zf() == want, name
        assert [rig.mu.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX)] == [bar, 0x55, 0x66]


# ---- t_rsb_grip / t_rsb_gripdraw -------------------------------------------------------------------------------------
GRIP_W = 18


def _grip_sprite(rig):
    """An 18x18 grip: key corners, F0 / B9 row dither inside (the real grip's pair), a solid 0xBD border column."""
    rows = []
    for y in range(GRIP_W):
        row = []
        for x in range(GRIP_W):
            if (x, y) in ((0, 0), (17, 0), (0, 17), (17, 17)):
                row.append(0xFE)
            elif x in (0, 17):
                row.append(0xBD)
            else:
                row.append(0xF0 if y % 2 == 0 else 0xB9)
        rows.append(row)
    spr, data = rig.alloc(0x100), rig.alloc(GRIP_W * GRIP_W)
    rig.mu.mem_write(data, bytes(v for r in rows for v in r))
    rig.mu.mem_write(spr, bytes(0x40))
    rig.w32(spr + 4, data)
    rig.mu.mem_write(spr + 8, bytes([0xFE]))
    for off, v in ((0xC, GRIP_W), (0x10, GRIP_W), (0x14, GRIP_W), (0x18, GRIP_W), (0x1C, GRIP_W)):
        rig.w32(spr + off, v)
    return spr, rows


def _enter_grip(rig, entry, bar, spr, dest, rect, x, y, num, den):
    """ScrollBar_draw's frame at the grip site after thunk_sb_thumb: [ret][dest, key, x, y, num, den][...] with the
    thumb rect L/T/R/B at [esp+0x28..0x34]; esi = the ScrollBar, ecx = the grip sprite."""
    stack = [MARKER, dest, 0xFE, x, y, num, den, 0, 0, 0] + list(rect)
    sp = rig.run(entry, stack, {UC_X86_REG_ECX: spr, UC_X86_REG_ESI: bar})
    assert rig.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18
    return sp


@pytest.mark.parametrize("g", [17, 18, 19, 20, 22, 24, 25, 27, 30, 33, 36, 40, 48])
def test_grip_is_relaid_for_rail_bars_only(image, g):
    rig = Rig(image, g)
    fam = _family(rig)
    spr, art = _grip_sprite(rig)
    bad = []
    for bw in sorted({SL.rail_col_w(cw, g) - 2 * SL.rail_bar_inset(cw, g) for cw in _widths(g)} | {g + 7, 2 * g}):
        T = 3 * g
        rect = (0, T, bw, T + bw)
        # vanilla's centring + thunk_sb_thumb's recentre: what reaches the tail today
        vx = (bw - GRIP_W) // 2 - (GRIP_W * (g - 16) >> 5)
        vy = T + (bw - GRIP_W) // 2 - (GRIP_W * (g - 16) >> 5)
        for name, (bar, rail) in fam.items():
            planes = []
            for entry in (RS.va("t_rsb_grip"), rig.sym["t_sbt_grip"]):
                dest, data = rig.buffer(bw, T + bw + 8, bw + 8, 0x41)
                _enter_grip(rig, entry, bar, spr, dest, rect, vx, vy, g, 16)
                planes.append(rig.plane(data, bw, T + bw + 8, bw + 8))
            ours, old = planes
            if not rail:
                if ours != old:
                    bad.append(("non-rail bar changed", name, bw))
                continue
            off, w = SL.rail_grip_span(bw, GRIP_W, g)
            x, y = off, T + (bw - w) // 2
            pair = SB.sb_grip_pair(art)
            for yy in range(T + bw + 8):
                for xx in range(bw):
                    inside = x <= xx < x + w and y <= yy < y + w
                    if inside:
                        s = art[SL.mirror_nn_src(yy - y, GRIP_W, w)][SL.mirror_nn_src(xx - x, GRIP_W, w)]
                        want = 0x41 if s == 0xFE else SB.sb_grip_pixel(s, yy, g, pair)
                    else:
                        want = 0x41
                    if ours[yy][xx] != want:
                        bad.append(("grip pixel", name, bw, xx, yy, hex(ours[yy][xx]), hex(want)))
                        break
                else:
                    continue
                break
            if not (off == bw - off - w and (bw - w) % 2 == 0):
                bad.append(("grip not centred", bw, off, w))
            # mirror-exact: every drawn row reads the same from both ends (the grip art is symmetric)
            if any(ours[yy][x:x + w] != ours[yy][x:x + w][::-1] for yy in range(y, y + w)):
                bad.append(("grip row not mirror-symmetric", name, bw, w))
    assert not bad, bad[:6]


def _odd_sprites(rig):
    """Grip sprites t_rsb_grip must NOT re-lay (they keep today's t_sbt_grip path): draw offsets, blit != canvas dims,
    no pixel plane (a filename-backed sprite)."""
    out = {}
    for name, patch in (("offsets", {0x20: 2, 0x24: 1}), ("blit_narrower", {0x10: 16}), ("no_bits", {4: 0})):
        spr, _art = _grip_sprite(rig)
        for off, v in patch.items():
            rig.w32(spr + off, v)
        out[name] = spr
    return out


@pytest.mark.parametrize("g", [22, 25, 40])
def test_grip_refuses_unusual_sprites(image, g):
    rig = Rig(image, g)
    bar = _family(rig)["popup"][0]
    rig.stub(rig.sym["thunk_sprite_scale_nn"], 0x18)        # both paths end in scale_nn: compare what reaches it
    for name, spr in _odd_sprites(rig).items():
        seen = []
        for entry in (RS.va("t_rsb_grip"), rig.sym["t_sbt_grip"]):
            dest, _data = rig.buffer(60, 200, 64, 0x41)
            rig.hits.clear()
            _enter_grip(rig, entry, bar, spr, dest, (0, 40, 52, 92), 9, 50, g, 16)
            seen.append([[h[2][1] == dest] + h[2][2:7] for h in rig.hits])
        assert seen[0] == seen[1] and seen[0], (name, seen)


@pytest.mark.parametrize("g", [17, 22, 25, 40, 64])
def test_mnn_equals_the_law(image, g):
    rig = Rig(image, g)
    for src in (18, 7, 24, 33):
        for dst in range(1, 3 * src):
            for k in range(dst):
                rig.run(RS.va("t_rsb_mnn"), [MARKER], {UC_X86_REG_EAX: k, UC_X86_REG_EBX: src, UC_X86_REG_ECX: dst,
                                                       UC_X86_REG_EDX: 0x66, UC_X86_REG_ESI: 0x77})
                assert rig.mu.reg_read(UC_X86_REG_EAX) == SL.mirror_nn_src(k, src, dst), (src, dst, k)
                assert [rig.mu.reg_read(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                                                     UC_X86_REG_ESI)] == [src, dst, 0x66, 0x77]


# ---- t_rsb_zoom ------------------------------------------------------------------------------------------------------
def _native_arrow(wn, hn, stride, art_w=18, kind="plate"):
    """A native-rendered arrow in the top-left [0, wn) x [0, hn): key margins, an art_w-wide plate centred the way
    FlatButton_content_draw centres its face ((wn - art_w) / 2), every column a distinct index (so the column each
    dest pixel shows is readable), rows tagged by parity."""
    f0 = (wn - art_w) // 2
    rows = []
    for y in range(hn):
        row = bytearray([KEY]) * stride
        if 2 <= y < hn - 2:
            for x in range(f0, f0 + art_w):
                row[x] = 0x20 + (x - f0) + (0x80 if y % 2 else 0)
        rows.append(bytes(row))
    return rows, f0


@pytest.mark.parametrize("g", [17, 18, 20, 22, 25, 28, 30, 33, 40, 48])
def test_zoom_places_a_rail_arrows_plate_on_the_grip_span(image, g):
    rig = Rig(image, g)
    fam = _family(rig)
    rig.stub(rig.sym["thunk_btn_bandstripe"], 0x2C)
    bad = []
    for aw in sorted({SL.rail_col_w(cw, g) - 2 * SL.rail_bar_inset(cw, g) for cw in _widths(g)} | {g + 7}):
        ah = aw
        wn, hn = -(-aw * 16 // g), -(-ah * 16 // g)                       # thunk_tutbtn_post's ceil native dims
        stride = aw + 4
        for name, (bar, rail) in fam.items():
            for arrow_off in (RS.SB_UP, RS.SB_DN, 0x2000):
                btn = bar + arrow_off
                rig.w32(btn + 0xC4, bar)
                buf, data = rig.buffer(wn, hn, stride, 0x77)
                native, f0 = _native_arrow(wn, hn, stride)
                for y, r in enumerate(native):
                    rig.mu.mem_write(data + y * stride, r)
                rig.hits.clear()
                sp = rig.run(RS.va("t_rsb_zoom"), [MARKER, buf, buf, 0, 0, wn, hn, 0, 0, aw, ah, 0xFFFFFFFF],
                             {UC_X86_REG_ESI: btn})
                assert rig.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C
                ours = rig.plane(data, aw, ah, stride)
                arrow = rail and arrow_off != 0x2000
                if not arrow:
                    if len(rig.hits) != 1 or rig.hits[0][1] != sp or rig.hits[0][2][1:12] != \
                            [buf, buf, 0, 0, wn, hn, 0, 0, aw, ah, 0xFFFFFFFF]:
                        bad.append(("not forwarded intact", name, hex(arrow_off), aw))
                    continue
                if rig.hits:
                    bad.append(("rail arrow forwarded", name, aw))
                    continue
                cmap = SL.rail_arrow_col_map(aw, wn, f0, f0 + 18, g)
                for yy in range(ah):
                    sy = min(((2 * yy + 1) * hn) // (2 * ah), hn - 1)
                    want = bytes(KEY if c is None else native[sy][c] for c in cmap)
                    if ours[yy] != want:
                        bad.append(("zoom row", name, aw, yy))
                        break
                off, w = SL.rail_grip_span(aw, 18, g)
                drawn = [x for x in range(aw) if any(ours[y][x] != KEY for y in range(ah))]
                if (drawn[0], drawn[-1] + 1) != (off, off + w) or off != aw - off - w:
                    bad.append(("plate span", name, aw, drawn[0], drawn[-1] + 1, off, w))
    # g <= 16: never re-laid (thunk_btn_shrink does not arm the zoom there anyway)
    rig.set_g(16)
    bar = fam["popup"][0]
    rig.w32(bar + RS.SB_UP + 0xC4, bar)
    buf, _data = rig.buffer(24, 24, 28, KEY)
    rig.hits.clear()
    rig.run(RS.va("t_rsb_zoom"), [MARKER, buf, buf, 0, 0, 24, 24, 0, 0, 24, 24, 0xFFFFFFFF],
            {UC_X86_REG_ESI: bar + RS.SB_UP})
    assert len(rig.hits) == 1
    assert not bad, bad[:6]


def test_blit_hands_an_oversized_column_to_the_engine(image):
    """Wc > 256 (g ~ 130+): the g_rsb_cmap table would overflow -> the engine Buffer_draw_2, stack and ecx intact."""
    rig = Rig(image, 136)
    rig.stub(rig.sym["Buffer_draw_2"], 0x18)
    cw = 5000
    assert SL.rail_col_w(cw, 136) > 256
    dest, _ = rig.buffer(cw, 8, cw, KEY)
    src, _ = rig.buffer(47, 4, 47, 0x41)
    rig.hits.clear()
    sp = rig.run(RS.va("t_rsb_blit"), [MARKER, dest, KEY, 10, 2, 136, 16], {UC_X86_REG_ECX: src})
    assert rig.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18
    assert len(rig.hits) == 1 and rig.hits[0][1] == sp and rig.hits[0][2][1:7] == [dest, KEY, 10, 2, 136, 16]


# ---- the yaml pin + the retargets ------------------------------------------------------------------------------------
def test_yaml_is_the_assembler_and_the_retargets_are_wired():
    _s, _g, caves, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["length"]) >= RS.REGION[1]
    ent = {e["id"]: e for e in cave["contents"]}
    for name in RS.ORDER:
        off, end = RS.LAYOUT[name]
        assert int(ent[name]["offset"]) == off and RS.REGION[0] <= off < end <= RS.REGION[1]
        assert str(ent[name]["bytes"]).split() == RS.template(name).split(), name
    # nothing else inside the W3B region
    for e in cave["contents"]:
        if e["id"] not in RS.ORDER:
            assert not RS.REGION[0] <= int(e["offset"]) < RS.REGION[1], e["id"]
    toks = lambda n: " ".join(str(ent[n]["bytes"]).split())                            # noqa: E731
    # the zoom call is a CHAIN on master e577031 (W2D F39 + W3B): 2dscale -> t_btn_edgeprobe (reads the native face of
    # every button) -> t_rsb_zoom (a rail bar's arrows) -> thunk_btn_bandstripe (every other button)
    assert "57 57 E8 {rel32:t_btn_edgeprobe} A1" in toks("thunk_btn_2dscale")
    assert toks("t_btn_edgeprobe").count("68 {abs32:t_rsb_zoom} C3") == 1
    assert "thunk_btn_bandstripe" not in toks("t_btn_edgeprobe")
    assert "68 {abs32:t_rsb_grip} C3 68 {abs32:Sprite_draw_2} C3" in toks("thunk_sb_thumb")
    bake = ent["thunk_rail_bake"]
    blob = bytes(ap.ByteTemplate(toks("thunk_rail_bake")).resolve(PCAVE2 + int(bake["offset"]), {
        **ap.build_symbol_table(_sym, caves)}))
    calls = [PCAVE2 + int(bake["offset"]) + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)
             for i in range(len(blob) - 4) if blob[i] == 0xE8]
    assert RS.va("t_rsb_blit") in calls and 0x5D84C0 not in calls


@pytest.mark.parametrize("g", [22, 25, 40])
def test_zoom_chain_from_the_edge_probe(image, g):
    """2dscale's zoom call enters W2D's t_btn_edgeprobe (master e577031), whose tail is t_rsb_zoom."""
    rig = Rig(image, g)
    sym = rig.sym
    fam = _family(rig)
    rig.stub(sym["thunk_btn_bandstripe"], 0x2C)
    aw = SL.rail_col_w(SL.scale_px(560, g), g) - 2 * SL.rail_bar_inset(SL.scale_px(560, g), g)
    wn = -(-aw * 16 // g)
    stride = aw + 4
    for name, (bar, rail) in fam.items():
        for arrow_off in (RS.SB_UP, 0x2000):
            btn = bar + arrow_off
            rig.w32(btn + 0xC4, bar)
            buf, data = rig.buffer(wn, wn, stride, 0x77)
            native, f0 = _native_arrow(wn, wn, stride)
            for y, r in enumerate(native):
                rig.mu.mem_write(data + y * stride, r)
            rig.w32(btn + 0x498, data)                         # the probe reads the button's own plane (+0x498 / +0x8EC)
            rig.w32(btn + 0x8EC, stride)
            rig.w32(sym["g_btn_fill_sprite"], 0)               # no 9-slice body captured (the rail arrows on master)
            rig.w32(sym["g_btn_tileH"], 0x1234)
            rig.w32(sym["g_btn_edge_mask"], 0xFF)
            rig.hits.clear()
            frame = [MARKER, buf, buf, 0, 0, wn, wn, 0, 0, aw, aw, 0xFFFFFFFF]
            sp = rig.run(sym["t_btn_edgeprobe"], frame, {UC_X86_REG_ESI: btn})
            assert rig.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C
            assert rig.r32(sym["g_btn_tileH"]) == 0 and rig.r32(sym["g_btn_edge_mask"]) == 0, name
            assert [rig.mu.reg_read(r) for r in REGS] == list({**REGS, UC_X86_REG_ESI: btn}.values())
            if rail and arrow_off == RS.SB_UP:
                assert not rig.hits, name                       # W3B zoomed it; the stretch never ran
                ours = rig.plane(data, aw, aw, stride)
                off, w = SL.rail_grip_span(aw, 18, g)
                drawn = [x for x in range(aw) if any(ours[y][x] != KEY for y in range(aw))]
                assert (drawn[0], drawn[-1] + 1) == (off, off + w), name
            else:
                assert len(rig.hits) == 1 and rig.hits[0][1] == sp and rig.hits[0][2][:12] == frame, name


@pytest.mark.parametrize("g", list(range(17, 97)))
def test_wspan_and_lay_equal_the_laws(image, g):
    rig = Rig(image, g)
    for spr in (18, 16, 19):
        for inner in range(0, 4 * g):
            rig.run(RS.va("t_rsb_wspan"), [MARKER], {UC_X86_REG_EAX: spr, UC_X86_REG_ECX: inner, UC_X86_REG_EDX: 0x66})
            off, w = SL.rail_grip_span(inner, spr, g)
            got_off = rig.mu.reg_read(UC_X86_REG_ECX)
            got_off = got_off - (1 << 32) if got_off & 0x80000000 else got_off
            assert (rig.mu.reg_read(UC_X86_REG_EAX), got_off) == (w, off), (spr, inner)
            assert rig.mu.reg_read(UC_X86_REG_EDX) == 0x66
    for wc in sorted({SL.rail_col_w(cw, g) for cw in _widths(g)} | {2 * g, 2 * g + 1, 2 * g + 2}):
        rig.run(RS.va("t_rsb_lay"), [MARKER], {UC_X86_REG_EAX: wc})
        got = tuple(rig.mu.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX))
        assert got == SL.rail_layout_zones(wc, g), (wc, got)
        assert [rig.mu.reg_read(r) for r in REGS] == list(REGS.values())
