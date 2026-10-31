"""Stripe-rule ports for the last parity-keyed producers and the baked-dither icons (2026-10-04).

The rule above native scale: T = scaling_laws.stripe_rows(g) device rows per stripe member, P = 2T (cell
g_stripe_period 0x66879C), top member on dest-buffer rows where (y mod P) < T; pictures count T from their own
first row.  At T == 1 (every g <= 21) each producer must be byte-identical to what it draws today.

  (A1) t_si_chip (scripts/assemble_stripes_icon.py, NEW thunk): the council vote chips.  Unicorn, the assembled
       bytes, against council_chip_law below (the law text to move into scaling_laws.py).
  (A2) t_msg_icon (scripts/assemble_msglog.py, applied): the event-log row icon shades by (j // T) & 1.
       The assembler's own asm text is assembled and run against msglog_icon_pixels_T below.
  (B)  thunk_se_sd2 (scripts/assemble_se.py) and t_dp_sd2_logo (scripts/assemble_diplo.py), PROPOSED edits: the
       Social Engineering sprites and the diplomacy-console faction logo leave through t_rwk_parity_nn (law
       scaling_laws.parity_nn_row; its own pixel parity is tests/test_rw_kinds_parity.py) instead of the engine's
       Sprite_draw_2.  Same proposed / applied pair.

Run:  py -m pytest -p no:cacheprovider -p no:faulthandler -o addopts="" -q test_stripes_icon_asm_parity.py
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import scaling_laws as SL  # noqa: E402

pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("unicorn", reason="unicorn absent")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_stripes_icon as SI  # noqa: E402

G_SWEEP = (16, 18, 21, 22, 25, 32, 40)

PCAVE2, CAVE_LEN = SI.PCAVE2, 0x31000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect)
G_VA, PERIOD_VA = 0x00668740, 0x0066879C
SD2 = 0x005E4B4A
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
BUF = DATA + 0x100
RECT = DATA + 0x800
PARAMS = DATA + 0x900
PLANE = DATA + 0x10000
BW, BH, STRIDE = 120, 72, 128
F_CLIP, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0x4A8
REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9, UC_X86_REG_EAX: 0x0EA0EA0E, UC_X86_REG_EDX: 0x0ED0ED0E}


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


# =====================================================================================================================
# (A1) council vote chips
# =====================================================================================================================
YEL, ORA, MASK_IDX, FILL_PTR = 0xF5, 0x65, 0x7B, DATA + 0x2000      # refs/pristine/Council/Vote.png: bevel F5, fill F5 / 65
BEVEL, PAD = 2, 2                                                   # ring widths of the test chip (device px)
_HOSTILE = (YEL, ORA, MASK_IDX, 0x41, 0xC4, 0x1F, 0xE0)


def _background():
    return bytearray(_HOSTILE[(x * 5 + y * 3) % len(_HOSTILE)] for y in range(BH) for x in range(STRIDE))


def _region(rect, clip):
    l, t, r, b = rect
    cl, ct, cr, cb = clip
    return max(l, cl, 0), max(t, ct, 0), min(r, cr, BW), min(b, cb, BH)


def _ring(x, y, rect):
    l, t, r, b = rect
    return min(x - l, r - 1 - x, y - t, b - 1 - y)


def paint_chip_1row(plane, rect, clip, phase, solid=False):
    """What thunk_cw_chip leaves: bevel ring in the fill's bright index, everything inside it the 1-row tile."""
    x0, y0, x1, y1 = _region(rect, clip)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if _ring(x, y, rect) < BEVEL:
                plane[y * STRIDE + x] = YEL
            else:
                plane[y * STRIDE + x] = YEL if solid or (y + phase) % 2 == 0 else ORA


def paint_frame(plane, rect, clip):
    """What thunk_box_thick_hollow_flat(fill-nulled params) draws: the bevel, and the pieces' padding in the mask colour."""
    x0, y0, x1, y1 = _region(rect, clip)
    for y in range(y0, y1):
        for x in range(x0, x1):
            d = _ring(x, y, rect)
            if d < BEVEL:
                plane[y * STRIDE + x] = YEL
            elif d < BEVEL + PAD:
                plane[y * STRIDE + x] = MASK_IDX


def council_chip_law(plane, stride, buf_w, buf_h, rect, clip, g, frame, *, fill, mask, min_w=2, min_h=8):
    """LAW (to live in scaling_laws.py): the vote-chip fill at the one stripe rule.  `plane` is the dest after the
    3-pass 1-row chip (fill tile, hollow frame, tile_mask).  T == 1 or a hollow chip: unchanged.  Else, over
    (rect & clip & buffer): the pair (a, b) is read on the dest at the centre column -- a from the even row
    nearest the centre, b below it, and the row below that must be a again (a 1-row field); every a / b pixel
    becomes a if stripe_top(y, g) else b; the frame is drawn again (`frame(plane)`); every mask-colour pixel
    becomes the same stripe colour.  Returns (plane, applied)."""
    out = bytearray(plane)
    if SL.stripe_period(g) <= 2 or g <= 16 or not fill:
        return out, False
    x0, y0 = max(rect[0], clip[0], 0), max(rect[1], clip[1], 0)
    x1, y1 = min(rect[2], clip[2], buf_w), min(rect[3], clip[3], buf_h)
    if x1 - x0 < min_w or y1 - y0 < min_h:
        return out, False
    cx, cy = (x0 + x1) >> 1, ((y0 + y1) >> 1) & ~1
    a, b = out[cy * stride + cx], out[(cy + 1) * stride + cx]
    if a == b or out[(cy + 2) * stride + cx] != a:
        return out, False

    def stripe(y):
        return a if SL.stripe_top(y, g) else b

    for y in range(y0, y1):
        for x in range(x0, x1):
            if out[y * stride + x] in (a, b):
                out[y * stride + x] = stripe(y)
    frame(out)
    if 0 <= mask <= 0xFF:
        for y in range(y0, y1):
            for x in range(x0, x1):
                if out[y * stride + x] == mask:
                    out[y * stride + x] = stripe(y)
    return out, True


class ChipEmu:
    def __init__(self):
        self.syms = SI.load_syms()
        self.layout = SI.assemble_all(self.syms)
        self.entry = SI.names_of(self.layout)["t_si_chip"]
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        off, code = self.layout["t_si_chip"]
        mu.mem_write(PCAVE2 + off, code)
        self.cw, self.hf = self.syms["thunk_cw_chip"], self.syms["thunk_box_thick_hollow_flat"]
        for va in (self.cw, self.hf):
            assert not (PCAVE2 + off <= va < PCAVE2 + off + len(code))
            mu.mem_write(va, b"\xC2\x08\x00")                      # both: thiscall, 2 stack args, RET 8
        self.calls, self.errors = [], []
        self.on_chip = self.on_frame = None
        mu.hook_add(UC_HOOK_CODE, self._hook, begin=self.cw, end=self.cw, user_data="chip")
        mu.hook_add(UC_HOOK_CODE, self._hook, begin=self.hf, end=self.hf, user_data="frame")

    def _hook(self, mu, address, size, kind):
        try:
            esp = mu.reg_read(UC_X86_REG_ESP)
            self.calls.append({"kind": kind, "esp": esp, "ret": _r32(mu, esp), "ecx": mu.reg_read(UC_X86_REG_ECX),
                               "args": [_r32(mu, esp + 4), _r32(mu, esp + 8)],
                               "regs": {r: mu.reg_read(r) for r in REGS}})
            live = bytearray(mu.mem_read(PLANE, STRIDE * BH))
            (self.on_chip if kind == "chip" else self.on_frame)(live)
            mu.mem_write(PLANE, bytes(live))
            mu.reg_write(UC_X86_REG_EAX, 0x00C0FFEE)                # a callee may clobber eax / ecx / edx
            mu.reg_write(UC_X86_REG_ECX, 0xCCCC0001)
            mu.reg_write(UC_X86_REG_EDX, 0xDDDD0002)
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    def run(self, g, rect, clip, plane, *, fill=FILL_PTR, mask=MASK_IDX, data_ptr=PLANE, period=None):
        mu = self.mu
        mu.mem_write(BUF, b"\x00" * 0x500)
        _w32(mu, BUF + F_DATA, data_ptr)
        _w32(mu, BUF + F_W, BW)
        _w32(mu, BUF + F_H, -BH)
        _w32(mu, BUF + F_STRIDE, STRIDE)
        for i, v in enumerate(clip):
            _w32(mu, BUF + F_CLIP + 4 * i, v)
        for i, v in enumerate(rect):
            _w32(mu, RECT + 4 * i, v)
        for i in range(10):
            _w32(mu, PARAMS + 4 * i, 0x100 + i)
        _w32(mu, PARAMS + 0x20, fill)
        _w32(mu, PARAMS + 0x24, mask)
        mu.mem_write(PLANE, bytes(plane))
        _w32(mu, G_VA, g)
        _w32(mu, PERIOD_VA, SL.stripe_period(g) if period is None else period)
        self.calls.clear()
        self.errors.clear()
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, MARKER)
        _w32(mu, sp + 4, RECT)
        _w32(mu, sp + 8, PARAMS)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, BUF)
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.emu_start(self.entry, MARKER, count=30_000_000)
        assert not self.errors, self.errors
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER, "did not return to the caller"
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 12, "stack imbalance (thiscall, 2 args: RET 8)"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == REGS[r], "callee-saved register not preserved"
        assert bytes(mu.mem_read(sp - 0x400, 0x400 - 0x60)) == b"\xA5" * (0x400 - 0x60), "stack use deeper than 0x60"
        assert bytes(mu.mem_read(sp + 12, 0x100)) == b"\xA5" * 0x100, "wrote above its own args"
        assert [_r32(mu, RECT + 4 * i) for i in range(4)] == [v & 0xFFFFFFFF for v in rect], "the caller's RECT changed"
        chip = [c for c in self.calls if c["kind"] == "chip"]
        assert len(chip) == 1 and self.calls[0] is chip[0], "thunk_cw_chip must run exactly once, first"
        assert chip[0]["ecx"] == BUF and chip[0]["args"] == [RECT, PARAMS]
        native = chip[0]["esp"] == sp and chip[0]["ret"] == MARKER
        if native:
            assert chip[0]["regs"] == REGS, "the tail-jump must hand thunk_cw_chip the site's registers"
        for c in self.calls[1:]:
            assert c["kind"] == "frame" and c["ecx"] == BUF
            assert c["args"] == [RECT, self.syms["g_cw_chipscr"] + SI.SCR_B_OFF], "frame redraw = pass 2's own call"
        return bytes(mu.mem_read(PLANE, STRIDE * BH)), native, len(self.calls) - 1


@pytest.fixture(scope="module")
def chip():
    return ChipEmu()


def _chip_case(emu, g, rect, clip, phase, **kw):
    bg = _background()
    one_row = bytearray(bg)
    paint_chip_1row(one_row, rect, clip, phase, solid=kw.pop("solid", False))
    emu.on_chip = lambda live: live.__setitem__(slice(None), one_row)      # the stand-in thunk_cw_chip paints it
    emu.on_frame = lambda live: paint_frame(live, rect, clip)
    fill, mask = kw.get("fill", FILL_PTR), kw.get("mask", MASK_IDX)
    got, native, frames = emu.run(g, rect, clip, bg, **kw)
    want, applied = council_chip_law(one_row, STRIDE, BW, BH, rect, clip, g, lambda p: paint_frame(p, rect, clip),
                                     fill=fill, mask=mask)
    return got, bytes(want), bytes(one_row), native, frames, applied


CHIP_RECTS = [
    ("whole", (20, 12, 100, 44), (0, 0, BW, BH)),
    ("odd_origin", (21, 13, 99, 47), (0, 0, BW, BH)),
    ("clip_all_sides", (20, 12, 100, 44), (30, 16, 90, 40)),
    ("clip_cuts_left_top", (20, 12, 100, 44), (25, 15, BW, BH)),
    ("past_the_buffer", (60, 40, 140, 90), (0, 0, 400, 400)),
    ("negative_origin", (-6, -4, 60, 30), (-50, -50, BW, BH)),
]


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("name,rect,clip", CHIP_RECTS, ids=[c[0] for c in CHIP_RECTS])
def test_chip_follows_the_stripe_law(chip, g, phase, name, rect, clip):
    got, want, one_row, native, frames, applied = _chip_case(chip, g, rect, clip, phase)
    assert got == want, f"{name} g={g}"
    T = SL.stripe_rows(g)
    if T == 1:
        assert native and frames == 0 and got == one_row, "T == 1: thunk_cw_chip alone, by tail-jump (byte-identical)"
        return
    assert not native and applied and frames == 1
    # the law stated directly: bevel untouched, every other chip pixel on the dest-buffer stripe grid, T rows each
    a, b = (YEL, ORA) if phase == 0 else (ORA, YEL)            # top = the member the 1-row chip had on EVEN rows
    x0, y0, x1, y1 = _region(rect, clip)
    for y in range(y0, y1):
        for x in range(x0, x1):
            v = got[y * STRIDE + x]
            if _ring(x, y, rect) < BEVEL:
                assert v == YEL, (x, y)
            else:
                assert v == (a if (y % (2 * T)) < T else b), (g, x, y, hex(v))
    bg = bytes(_background())
    for y in range(BH):
        for x in range(STRIDE):
            if not (x0 <= x < x1 and y0 <= y < y1):
                assert got[y * STRIDE + x] == bg[y * STRIDE + x], "wrote outside rect & clip"


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("why,kw,rect,clip", [
    ("hollow_chip", {"fill": 0}, (20, 12, 100, 44), (0, 0, BW, BH)),
    ("solid_fill", {"solid": True}, (20, 12, 100, 44), (0, 0, BW, BH)),
    ("seven_rows_visible", {}, (20, 12, 100, 44), (0, 20, BW, 27)),
    ("one_column_visible", {}, (20, 12, 100, 44), (50, 0, 51, BH)),
    ("outside_clip", {}, (20, 12, 100, 44), (0, 50, BW, BH)),
    ("empty_rect", {}, (40, 30, 40, 30), (0, 0, BW, BH)),
    ("no_pixel_data", {"data_ptr": 0}, (20, 12, 100, 44), (0, 0, BW, BH)),
], ids=lambda v: v if isinstance(v, str) else None)
def test_chip_guards_leave_the_one_row_chip(chip, g, why, kw, rect, clip):
    got, want, one_row, native, frames, applied = _chip_case(chip, g, rect, clip, 0, **dict(kw))
    if kw.get("data_ptr", 1) == 0:
        return                                                    # nothing may be walked: reaching here is the test
    assert got == want == one_row, f"{why} g={g}"
    assert frames == 0 and not applied


@pytest.mark.parametrize("g", [22, 25, 40])
def test_chip_without_a_mask_colour_skips_the_mask_pass(chip, g):
    rect, clip = (20, 12, 100, 44), (0, 0, BW, BH)
    got, want, _one, native, frames, applied = _chip_case(chip, g, rect, clip, 0, mask=0xFFFFFFFF)
    assert got == want and applied and frames == 1
    assert got[(12 + BEVEL) * STRIDE + 20 + BEVEL] == MASK_IDX, "padding stays as the frame drew it"


@pytest.mark.parametrize("g,period", [(16, 4), (10, 4), (40, 2), (40, 0)])
def test_chip_inconsistent_cells_take_the_native_path(chip, g, period):
    """P <= 2 or g <= 16, whatever the other cell says: thunk_cw_chip alone (no stale-SCR_B frame call, no div by 0)."""
    rect, clip = (20, 12, 100, 44), (0, 0, BW, BH)
    bg = _background()
    one_row = bytearray(bg)
    paint_chip_1row(one_row, rect, clip, 0)
    chip.on_chip = lambda live: live.__setitem__(slice(None), one_row)
    chip.on_frame = lambda live: pytest.fail("frame redraw on the native path")
    got, native, frames = chip.run(g, rect, clip, bg, period=period)
    assert native and frames == 0 and got == bytes(one_row)


def test_chip_layout_template_and_sites():
    syms = SI.load_syms()
    layout = SI.assemble_all(syms)
    off, code = layout["t_si_chip"]
    assert off == SI.OFF_CODE and off % 16 == 0 and off + len(code) <= SI.OFF_LIMIT
    assert code[-1:] == b"\xC3" and b"\xC2\x08\x00" in code, "RET 8 exit + the local subroutine's ret"
    assert SI.roundtrip_problems(layout, syms) == []
    sites = SI.site_list()
    assert len(sites) == 5 and len({s["va"] for s in sites}) == 5


def test_chip_sites_match_the_pristine_base():
    import config
    if not config.terranx_bak(required=False).exists():
        pytest.skip("pristine .bak absent")
    assert SI.verify_live(SI.site_list()) == []


def test_chip_sites_are_wired():
    with contextlib.redirect_stdout(io.StringIO()):
        import assemble_council as AC
    import assemble_council_mirror as CM
    chips = [s for s in AC.SITES if "chip_d" in s[0]]
    assert len(chips) == 5
    # 2026-10-25 W5B: the chips reach t_si_chip through t_cw_chiphalf (R-1 / B-1 around it at g > 16, a tail jump at 16)
    assert all(s[4] == "t_cw_chiphalf" for s in chips), "assemble_council.SITES must send the 5 vote chips to t_cw_chiphalf"
    asm = CM.asm_chiphalf()
    assert asm.count(f"{CM.SYM['t_si_chip']:#x}") == 2, "t_cw_chiphalf calls / tails t_si_chip"


# =====================================================================================================================
# (A2) event-log row icon: shade = (j // T) & 1
# =====================================================================================================================
MSG_OLD_TEST = "    test byte ptr [ebp-0x28], 1\n"    # the retired 1-row shade (row index parity)
MSG_SLOT_END = 0x29C00                       # thunk_art_wrap (cave_map.py --at 0x29BF0)


def msglog_icon_pixels_T(src, g, key):
    """scaling_laws.msglog_icon_pixels, restated independently: `lut = to_dark if (j // stripe_rows(g)) & 1 else
    to_light` (was `j & 1`).  T counted from the icon's own first row; T == 1 below g = 22 -> today's pixels."""
    sh, sw = len(src), len(src[0])
    dw, dh = SL.popup_scale_floor(sw, g), SL.popup_scale_floor(sh, g)
    bg_l, bg_d, ar_l, ar_d = src[0][1], src[1][0], src[2][8], src[1][8]
    to_light, to_dark = {bg_d: bg_l, ar_d: ar_l}, {bg_l: bg_d, ar_l: ar_d}
    T = SL.stripe_rows(g)
    out = []
    for j in range(dh):
        sy = min(((2 * j + 1) * 16) // (2 * g), sh - 1)
        lut = to_dark if (j // T) & 1 else to_light
        row = []
        for i in range(dw):
            c = src[sy][min(((2 * i + 1) * 16) // (2 * g), sw - 1)]
            row.append(None if c == key else lut.get(c, c))
        out.append(row)
    return out


def _msglog():
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            import assemble_msglog as ML
            import test_scaling_msglog_parity as TM
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"assemble_msglog / its parity harness not importable here: {e!r}")
    return ML, TM


def _msg_bytes():
    """t_msg_icon exactly as assemble_msglog.py assembles it (the stripe-rule edit, findings A2, is applied)."""
    ML, TM = _msglog()
    asm = dict(ML.THUNKS)["t_msg_icon"]
    assert "[ebp-0x3C]" in asm and MSG_OLD_TEST not in asm, \
        "assemble_msglog.t_msg_icon must shade by the stripe-row index [ebp-0x3C], not `test byte ptr [ebp-0x28], 1`"
    off = ML.OUT["t_msg_icon"][0]
    enc, _ = ML.ks.asm(asm, ML.PCAVE2 + off)
    return ML, TM, off, bytes(enc)


def test_msg_icon_fits_its_slot():
    _ML, _TM, off, code = _msg_bytes()
    assert off + len(code) <= MSG_SLOT_END, f"{len(code)} B from {off:#x} overruns thunk_art_wrap at {MSG_SLOT_END:#x}"


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("row_h", [17, 18, 19, 40])
def test_msg_icon_shades_by_the_stripe_rule(g, row_h, monkeypatch):
    ML, TM, off, code = _msg_bytes()
    real_entry = TM.entry
    monkeypatch.setattr(TM, "entry", lambda name: (off, code) if name == "t_msg_icon" else real_entry(name))
    row_x, row_y = 5, 60
    rh = SL.popup_scale_floor(row_h, g)
    sd2, rows = TM.draw(g, row_x, row_y, rh)
    if g <= 16:
        assert sd2 is not None and sd2[5:7] == (1, 1), "g <= 16: the engine's Sprite_draw_2, 1/1"
        assert all(c == TM.BLANK for r in rows for c in r)
        return
    assert sd2 is None, "g > 16: the thunk's own blit, the engine is not entered"
    x, y, _w, _h = SL.msglog_icon_layout(row_x, row_y, rh, g, (16, 15))
    want = [[TM.BLANK] * TM.DW for _ in range(TM.DH)]
    for j, r in enumerate(msglog_icon_pixels_T(TM.ICON, g, TM.KEY)):
        for i, c in enumerate(r):
            if c is not None:
                want[y + j][x + i] = c
    assert rows == want
    if SL.stripe_rows(g) == 1:                                   # T == 1: byte-identical to the shipped 1-row law
        old = [[TM.BLANK] * TM.DW for _ in range(TM.DH)]
        for j, r in enumerate(_msglog_icon_pixels_1row(TM.ICON, g, TM.KEY)):
            for i, c in enumerate(r):
                if c is not None:
                    old[y + j][x + i] = c
        assert rows == old
    else:                                                        # the rule, read off the pixels: T rows per member
        T = SL.stripe_rows(g)
        light = {TM.ICON[0][1], TM.ICON[2][8]}
        for j in range(SL.popup_scale_floor(15, g)):
            drawn = [c for c in rows[y + j] if c != TM.BLANK]
            assert drawn and all((c in light) == (((j // T) & 1) == 0) for c in drawn), (g, j)


def _msglog_icon_pixels_1row(src, g, key):
    """The shipped law's shade (`j & 1`), kept here so the T == 1 identity does not depend on which version of
    scaling_laws.msglog_icon_pixels is checked in."""
    sh, sw = len(src), len(src[0])
    dw, dh = SL.popup_scale_floor(sw, g), SL.popup_scale_floor(sh, g)
    bg_l, bg_d, ar_l, ar_d = src[0][1], src[1][0], src[2][8], src[1][8]
    to_light, to_dark = {bg_d: bg_l, ar_d: ar_l}, {bg_l: bg_d, ar_l: ar_d}
    out = []
    for j in range(dh):
        sy = min(((2 * j + 1) * 16) // (2 * g), sh - 1)
        lut = to_dark if j & 1 else to_light
        out.append([None if (c := src[sy][min(((2 * i + 1) * 16) // (2 * g), sw - 1)]) == key else lut.get(c, c)
                    for i in range(dw)])
    return out


def test_msg_icon_law_in_scaling_laws_is_updated():
    ML, TM = _msglog()
    for g in G_SWEEP:
        assert SL.msglog_icon_pixels(TM.ICON, g, TM.KEY) == msglog_icon_pixels_T(TM.ICON, g, TM.KEY), \
            f"scaling_laws.msglog_icon_pixels must shade by (j // stripe_rows(g)) & 1 (g={g})"


# =====================================================================================================================
# (B) law level: why a parity-NN enlarger puts row-pair art on the rule (t_rwk_parity_nn, used by the Hall of Fame
#     rows; the SE icons / diplomacy logo now go through t_spr_stripes instead -- test_stripes_spr_asm_parity.py)
# =====================================================================================================================

@pytest.mark.parametrize("g", [22, 25, 32, 40])
@pytest.mark.parametrize("top_parity", [0, 1])
def test_parity_enlarge_puts_row_pair_art_on_the_rule(g, top_parity):
    """Why t_rwk_parity_nn is the lawful enlarger for these icons (law level, no emulation): for art whose rows
    alternate light / dark through and through, every device row shows a native row of the parity its stripe
    phase asks for -- T rows per member on the parent grid -- and never moves more than one native row."""
    sh, y0 = 15, 7
    dh = sh * g // 16
    T = SL.stripe_rows(g)
    rows = SL.parity_nn_row_map(dh, sh, y0, g, top_parity)
    for dy, sy in enumerate(rows):
        top = ((y0 + dy) % (2 * T)) < T
        assert (sy % 2 == top_parity) == top, (g, dy, sy)
        assert abs(sy - SL.nn_center_index(dy, dh, sh)) <= 1
