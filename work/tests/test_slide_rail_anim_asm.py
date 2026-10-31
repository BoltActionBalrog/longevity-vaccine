"""Slide-window rails: every open/close ANIMATION frame draws the four rail strips exactly where the SETTLED draw puts
them (thunk_filedlg_railslide v3, laws scaling_laws.slide_rail_anim_x / slide_rail_anim_y / slide_rail_anim_rows).

slide_show (0x45D440) / slide_hide (0x45D970) draw the strips twice: every animation frame onto the SCREEN buffer in
screen coordinates (8 sites -> thunk_filedlg_railslide), and once at the settle into the window canvas (4 sites ->
thunk_filedlg_railscale v3 -> thunk_sprite_scale_nn).  v1 of the animation helper ceil-descaled the screen x and let the
shim floor it back, which matches the settled cascade only for some phases of the window's screen left L: mid-slide
the strips sat 1 px off (1920x1080 HQ report: a see-through column between the left strips and the inner strip over
the frame's first stroke; 1600x1200 also between the right strips) and snapped at the settle.

The REAL bytes of the four cave entries (resolved from patches.yaml) run under Unicorn for every slide window the rail
gate serves -- the HQ report window, SocialWin, DiploWin, BaseWin, CouncilWin, the in-game file dialog, DesignWin,
PrefWin and the variable-width popup family (a run of consecutive widths) -- on a 4:3 and a 16:9 screen, at every
g in 17..48, through every slide_show and slide_hide frame row:
  * each strip's columns in every frame == the settled strip's columns + L (and == the law);
  * each strip's top row / row count == the law; on slide_show's last frame (slide row == T) the tops == the settled
    tops + T, so nothing moves at the settle;
  * BOTH pairs are seamless, settled and at every frame (railscale v3 / railslide v3, law rail_right_strip_x: the
    outer right strip abuts the inner one; v2 left a 1-px see-through column between the right strips at odd g --
    SocialWin/BaseWin 17,19,25,27,33,35,41,43, DiploWin 17..23,33..39 odd, CouncilWin 19,23,..,47, file dialog /
    PrefWin 21,23,29,31,37,39,45,47, DesignWin every odd g, ~half the popup widths);
  * the outer right strip ends inside the canvas, and never right of v2's end (it only moved left).
Plus the bottom clamp (never a row at or below the window bottom B), a dense canvas-width sweep of the settled pairs,
railscale's gate (native / arm A / arm B / screen buffer) and the native / unarmed pass-through.
Skips without unicorn.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402

PCAVE2, CAVE_LEN = 0x00A0C000, 0x40000   # through the W5A region (t_bw_railanchor @ +0x3C3A0)
G_VA = 0x00668740
G_FLAG = PCAVE2 + 0x23A0        # g_filedlg_active (railscale arm A; the rail-arm wrappers set it)
G_WINBUF = PCAVE2 + 0x25E0      # g_fd_winbuf
SPRITE_DRAW_2 = 0x005E4B4A
SCREEN_BUF = 0x009B7490         # railscale's arm-B exclusion (the slide frames' dest); the test's screen object
SPRITES = (0x007CFFC4, 0x007CFFF0, 0x007D001C, 0x007D0048)   # outer-left, inner-left, inner-right, outer-right
OUTER = (True, False, False, True)
STACK, MARKER = 0x00200000, 0x00DEAD00
DATA = 0x01000000               # window Buffer object + strip pixels
WB = DATA                       # the window canvas Buffer (g_fd_winbuf); the window = WB - 0x444
SPR_PIX = DATA + 0x1000
WPLANE = DATA + 0x10000         # window canvas plane (<= 2560 x 2600)
SPLANE = 0x02000000             # screen plane (<= 4096 x 2304)
WSTRIDE, SSTRIDE = 2560, 4096
CE = STACK + 0xC000             # the slide function's frame (ebp at the call sites)
SPR_H = 6                       # strip blit rows (the real art is 529; rows only matter for the clamp test)
SENT_EBX, SENT_EDI = 0x13579BDF, 0x2468ACE0
ENTRIES = ("thunk_filedlg_railslide", "thunk_filedlg_railscale", "thunk_sprite_scale_nn",   # v3: no v1shim
           "t_bw_railanchor")   # railslide v4 (W5A v2): the right-strip anchor (these windows: the double floor)


def _w32(mu, a, v):
    mu.mem_write(a, int(v & 0xFFFFFFFF).to_bytes(4, "little"))


@pytest.fixture(scope="module")
def code():
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = ap.build_symbol_table(symbols, caves)
    cave = next(c for c in caves if c["id"] == "pcave2")
    out = {}
    for name in ENTRIES:
        e = next(c for c in cave["contents"] if c["id"] == name)
        va = PCAVE2 + int(e["offset"])
        out[name] = (va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, symtab)))
    return out


class Rig:
    def __init__(self, code, g):
        self.g = g
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)
        mu.mem_map(0x007CF000, 0x2000)
        mu.mem_map(SPRITE_DRAW_2 & ~0xFFF, 0x1000)
        mu.mem_map(SCREEN_BUF & ~0xFFF, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x10000 + WSTRIDE * 2600)
        mu.mem_map(SPLANE, SSTRIDE * 2304)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        for va, b in code.values():
            mu.mem_write(va, b)
        _w32(mu, G_VA, g)
        _w32(mu, G_FLAG, 1)
        _w32(mu, G_WINBUF, WB)
        mu.mem_write(SPRITE_DRAW_2, b"\xC2\x18\x00")
        self.native = []
        mu.hook_add(UC_HOOK_CODE, lambda m, a, s, u: self.native.append(a), begin=SPRITE_DRAW_2, end=SPRITE_DRAW_2)
        _w32(mu, WB + 0x54, WPLANE)
        _w32(mu, WB + 0x4A8, WSTRIDE)
        _w32(mu, SCREEN_BUF + 0x54, SPLANE)
        _w32(mu, SCREEN_BUF + 0x4A8, SSTRIDE)
        for k, spr in enumerate(SPRITES):
            w = SL.SLIDE_RAIL_W[k]
            _w32(mu, spr + 0x04, SPR_PIX + 0x400 * k)
            _w32(mu, spr + 0x0C, w)
            _w32(mu, spr + 0x10, w)
            _w32(mu, spr + 0x14, SPR_H)
            _w32(mu, spr + 0x18, w)
            _w32(mu, spr + 0x1C, 529)
            _w32(mu, spr + 0x20, 0)
            _w32(mu, spr + 0x24, 0)

    def window(self, screen_w, screen_h, buf_w, win_h):
        assert buf_w <= WSTRIDE and win_h <= 2600 and screen_w <= SSTRIDE and screen_h <= 2304
        _w32(self.mu, WB + 0x80, buf_w)
        _w32(self.mu, WB + 0x84, -win_h)
        _w32(self.mu, SCREEN_BUF + 0x80, screen_w)
        _w32(self.mu, SCREEN_BUF + 0x84, -screen_h)

    def _call(self, entry, k, color, args, ebp, esi):
        mu = self.mu
        spr = SPRITES[k]
        mu.mem_write(SPR_PIX + 0x400 * k, bytes([color]) * (SL.SLIDE_RAIL_W[k] * SPR_H))
        sp = STACK + 0x8000
        for i, v in enumerate((MARKER,) + tuple(args)):
            _w32(mu, sp + 4 * i, v)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, spr)
        mu.reg_write(UC_X86_REG_EBP, ebp)
        mu.reg_write(UC_X86_REG_ESI, esi)
        mu.reg_write(UC_X86_REG_EBX, SENT_EBX)
        mu.reg_write(UC_X86_REG_EDI, SENT_EDI)
        mu.emu_start(entry, MARKER, count=3_000_000)
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18                     # RET 0x18 (Sprite_draw_2's contract)
        assert (mu.reg_read(UC_X86_REG_EBX), mu.reg_read(UC_X86_REG_EDI), mu.reg_read(UC_X86_REG_EBP),
                mu.reg_read(UC_X86_REG_ESI)) == (SENT_EBX, SENT_EDI, ebp, esi)   # callee-saved round-trip

    def settled(self, k, x_arg, y_arg, color):
        self._call(self.scale, k, color, (WB, 9, x_arg, y_arg, 1, 1), CE, 0)

    def frame(self, k, x, y, color, show, slide_y, A, rect):
        L, T, R, B = rect
        mu = self.mu
        for off, v in ((-0x1C, L), (-0x18, T), (-0x14, R), (-0x10, B), (-0x24, 0), (-0x38, 0)):
            _w32(mu, CE + off, v)
        window = WB - 0x444
        if show:    # slide_show: the window is [ebp+8], esi the slide row, A at [ebp-0x24]
            _w32(mu, CE + 8, window)
            _w32(mu, CE - 0x24, A)
            esi = slide_y
        else:       # slide_hide: the window is esi, [ebp+8] the step counter, A at [ebp-0x38]
            _w32(mu, CE + 8, 3)
            _w32(mu, CE - 0x38, A)
            esi = window
        self._call(self.slide, k, color, (SCREEN_BUF, 9, x, y, 1, 1), CE, esi)

    def span(self, plane, stride, row, color):
        line = bytes(self.mu.mem_read(plane + row * stride, stride))
        cols = [i for i, p in enumerate(line) if p == color]
        return cols

    def clear(self, plane, stride, top, n, c0, c1):
        for r in range(max(0, top), top + n):
            self.mu.mem_write(plane + r * stride + c0, bytes(c1 - c0 + 1))

    def rows(self, plane, stride, col, top, color, limit):
        """Rows of column `col` holding `color`, scanning [top - 2, top + limit)."""
        out = []
        for r in range(max(0, top - 2), top + limit):
            if self.mu.mem_read(plane + r * stride + col, 1)[0] == color:
                out.append(r)
        return out


def _rig(code, g):
    r = Rig(code, g)
    r.slide, r.scale = code["thunk_filedlg_railslide"][0], code["thunk_filedlg_railscale"][0]
    return r


def _screens(g):
    sh = 48 * g                                    # g = 16 * SH / 768 exactly
    return ((sh * 4 // 3, sh), (sh * 16 // 9, sh))


def _v2_outer_right_end(buf_w, g):
    """v2's outer right strip's last column: fl((fl(buf_w*16/g) - 0x2F)*g/16) + fl(15g/16) - 1."""
    return (((buf_w * 16) // g - 0x2F) * g >> 4) + (15 * g >> 4) - 1


def _windows(sw, sh, g):
    """(name, L, T, canvas w, h) for every slide window the rail gate serves, at this screen."""
    s, fl = SL.scale_px, SL.popup_scale_floor
    strip = s(213, g)
    out = []
    W, H = (650 * g) >> 4, (553 * g) >> 4
    out.append(("report", SL.rw_window_x(sw, W, g)[1], sh - strip - H, SL.rw_canvas_w(W, g), H))
    w, h = SL.se_window_w(g), s(SL.SE_MODAL_H, g)
    out.append(("social", (sw - w) // 2, sh - strip - h, w, h))
    x, y, w, h = SL.dw_window_rect(sw, sh, strip, g)
    out.append(("diplowin", x, y, w, h))
    x, y, w, h = SL.basewin_window_rect(sw, sh, strip, g)
    out.append(("basewin", x, y, w, h))
    x, y, w, h = SL.council_window_rect(sw, sh, strip, g)
    out.append(("council", x, y, w, h))
    x, y, w, h = SL.filedlg_window_origin(sw, sh, strip, *SL.filedlg_native_origin(sw, sh, strip, True), g)
    out.append(("filedlg", x, y, w, h))
    w, h = (623 * g + 15) // 16, s(600, g)
    out.append(("designwin", (sw - w) // 2, max(0, sh - strip - h), w, h))
    (x, y), (w, h) = SL.prefwin_window_pos(sw, sh, g), SL.prefwin_window_wh(g)   # W6A: w = ceil(778g/16)
    out.append(("prefwin", x, y, w, h))
    for i in range(0, 32, 3):                      # the popup family: variable widths (every phase of w*16/g)
        w, h = s(520, g) + i, s(200, g)
        out.append((f"popup+{i}", (sw - w) // 2 + i, sh - strip - h, w, h))
    return out


@pytest.mark.parametrize("g", range(17, 49))
def test_scaling_slide_frames_draw_the_settled_rails(code, g):
    rig = _rig(code, g)
    color = 0x20
    for sw, sh in _screens(g):
        for name, L, T, bw, wh in _windows(sw, sh, g):
            assert L >= 0 and T >= 0 and L + bw <= sw, (name, g, L, T, bw, sw)
            B = T + wh
            rig.window(sw, sh, bw, wh)
            A = SL.slide_rail_outer_a(T, sh, g)
            xargs = SL.slide_rail_local_x_args(bw)
            # the settled draws (window-local, through railscale): x args 0 / 15 / bw-55 / bw-47, y 0 or the outer v'
            set_cols, set_top = [], []
            yv = SL.slide_rail_settled_v(T, A, T, g)
            for k in range(4):
                color += 1
                ya = yv if OUTER[k] else 0
                rig.settled(k, xargs[k], ya, color)
                ytop = SL.slide_rail_outer_y(T, A, T, g) if OUTER[k] else 0
                cols = rig.span(WPLANE, WSTRIDE, ytop, color)
                assert cols and cols == list(range(cols[0], cols[-1] + 1)), (name, g, k)
                assert cols[0] == SL.slide_rail_settled_x(bw, xargs[k], g), (name, g, k)
                assert len(cols) == (SL.SLIDE_RAIL_W[k] * g) >> 4
                assert rig.rows(WPLANE, WSTRIDE, cols[0], ytop, color, 2)[0] == ytop
                rig.clear(WPLANE, WSTRIDE, ytop, (SPR_H * g >> 4) + 1, cols[0], cols[-1])
                set_cols.append([L + c for c in cols])
                set_top.append(T + ytop)
            assert set_cols[1][0] == set_cols[0][-1] + 1, (name, g)               # the settled left pair is seamless
            assert set_cols[3][0] == set_cols[2][-1] + 1, (name, g, sw)          # the settled right pair is seamless
            assert set_cols[3][-1] - L < bw, (name, g)                            # the outer right strip ends inside
            assert set_cols[3][-1] - L <= _v2_outer_right_end(bw, g), (name, g)   # ... and never moved outward
            # every animation frame, open and close
            for show in (True, False):
                frames = SL.slide_frames(T, B, 5, show)
                for slide_y in frames:
                    anim = []
                    for k in range(4):
                        color = color + 1 if color < 0xF0 else 0x20
                        y = max(slide_y, A) if OUTER[k] else slide_y
                        rig.frame(k, L + xargs[k], y, color, show, slide_y, A, (L, T, L + bw, B))
                        ytop = SL.slide_rail_anim_y(y, A, T, OUTER[k], g)
                        nrows = SL.slide_rail_anim_rows(ytop, B, SPR_H, g)
                        if nrows == 0:
                            assert not rig.span(SPLANE, SSTRIDE, min(ytop, sh - 1), color)
                            anim.append(None)
                            continue
                        cols = rig.span(SPLANE, SSTRIDE, ytop, color)
                        assert cols == set_cols[k], (name, g, sw, show, slide_y, k, cols[:1], set_cols[k][:1])
                        assert cols[0] == SL.slide_rail_anim_x(L, L + xargs[k], bw, g)
                        assert rig.rows(SPLANE, SSTRIDE, cols[0], ytop, color, nrows + 2) == \
                            list(range(ytop, ytop + nrows)), (name, g, show, slide_y, k)
                        assert ytop + nrows <= B                                   # never below the window
                        rig.clear(SPLANE, SSTRIDE, ytop, nrows, cols[0], cols[-1])
                        if show and slide_y == T:
                            assert ytop == set_top[k], (name, g, k, ytop, set_top[k])   # the settle moves nothing
                        anim.append(cols)
                    if anim[0] and anim[1]:
                        assert anim[1][0] == anim[0][-1] + 1, (name, g, show, slide_y)
                    if anim[2] and anim[3]:
                        assert anim[3][0] == anim[2][-1] + 1, (name, g, show, slide_y)
    assert not rig.native, "g > 16 with the gate armed must take the scaled paths"


@pytest.mark.parametrize("g", (17, 22, 25, 31, 40, 48))
def test_scaling_slide_frame_bottom_clamp(code, g):
    """A tall strip near the window bottom B: drawn rows == slide_rail_anim_rows = min(fl(H*g/16), B - y) (v3: the
    dest buffer's height is lowered to B for the call -- v2 shrank the sprite and ended 1-3 rows short of B), never at
    or below B; no draw once the strip starts at or below B.  The Sprite and the screen Buffer are left untouched."""
    rig = _rig(code, g)
    sw, sh = _screens(g)[1]
    name, L, T, bw, wh = _windows(sw, sh, g)[0]
    B = T + wh
    rig.window(sw, sh, bw, wh)
    tall = 40
    for spr in SPRITES:
        _w32(rig.mu, spr + 0x14, tall)
    color = 0x20
    xargs = SL.slide_rail_local_x_args(bw)
    for d in range(-2, (tall * g >> 4) + 3):
        y = B - d
        for k in (1, 2):                                              # the inner strips (y = the slide row)
            color = color + 1 if color < 0xF0 else 0x20
            rig.mu.mem_write(SPR_PIX + 0x400 * k, bytes([color]) * (SL.SLIDE_RAIL_W[k] * tall))
            sp = STACK + 0x8000
            for off, v in ((-0x1C, L), (-0x18, T), (-0x14, L + bw), (-0x10, B), (-0x24, 0)):
                _w32(rig.mu, CE + off, v)
            _w32(rig.mu, CE + 8, WB - 0x444)
            for i, v in enumerate((MARKER, SCREEN_BUF, 9, L + xargs[k], y, 1, 1)):
                _w32(rig.mu, sp + 4 * i, v)
            rig.mu.reg_write(UC_X86_REG_ESP, sp)
            rig.mu.reg_write(UC_X86_REG_ECX, SPRITES[k])
            rig.mu.reg_write(UC_X86_REG_EBP, CE)
            rig.mu.reg_write(UC_X86_REG_ESI, y)
            rig.mu.emu_start(rig.slide, MARKER, count=3_000_000)
            assert rig.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x18
            assert int.from_bytes(rig.mu.mem_read(SPRITES[k] + 0x14, 4), "little") == tall
            x0 = SL.slide_rail_anim_x(L, L + xargs[k], bw, g)
            got = [r for r in range(max(0, y - 2), min(sh, y + (tall * g >> 4) + 2))
                   if rig.mu.mem_read(SPLANE + r * SSTRIDE + x0, 1)[0] == color]
            n = SL.slide_rail_anim_rows(y, B, tall, g)
            assert got == list(range(y, y + n)), (g, d, k, got[:2], n)
            assert n == (min(tall * g >> 4, B - y) if y < B else 0)               # v3: vanilla's clip, to the row
            assert all(r < B for r in got)
            if 0 < B - y <= (tall * g >> 4):
                assert got[-1] == B - 1, (g, d, k)                                # a strip reaching B ends AT B
            assert int.from_bytes(rig.mu.mem_read(SCREEN_BUF + 0x84, 4), "little", signed=True) == -sh   # restored


@pytest.mark.parametrize("g", (16, 12))
def test_slide_frames_native_passthrough(code, g):
    """g <= 16: the engine Sprite_draw_2 tail, args untouched (byte-identical vanilla)."""
    rig = _rig(code, g)
    rig.window(1024, 768, 728, 400)
    rig.frame(1, 300 + 15, 500, 0x41, True, 500, 238, (300, 200, 1028, 600))
    assert rig.native == [SPRITE_DRAW_2]
    sp = STACK + 0x8000
    assert [int.from_bytes(rig.mu.mem_read(sp + 4 * i, 4), "little") for i in range(1, 7)] == \
        [SCREEN_BUF, 9, 315, 500, 1, 1]


def test_slide_frames_unarmed_window_is_native(code):
    """A slide window the gate does not serve (g_fd_winbuf points elsewhere): native tail, even at g > 16."""
    rig = _rig(code, 25)
    rig.window(1600, 1200, 1137, 600)
    _w32(rig.mu, G_WINBUF, WB + 0x1000)
    for show in (True, False):
        rig.native.clear()
        rig.frame(0, 300, 500, 0x41, show, 500, 400, (300, 200, 1437, 800))
        assert rig.native == [SPRITE_DRAW_2]


def test_scaling_slide_rail_laws():
    """The pure laws: animation == settled for every L and canvas width; identity at g <= 16; outer top settles."""
    for g in range(17, 49):
        for bw in range(300, 2600, 7):
            xargs = SL.slide_rail_local_x_args(bw)
            for L in range(0, 40, 3):
                for k in range(4):
                    assert SL.slide_rail_anim_x(L, L + xargs[k], bw, g) == L + SL.slide_rail_settled_x(bw, xargs[k], g)
        for T, A in ((100, 90), (100, 100), (100, 337), (3, 238 * g // 16)):
            settled_top = T + SL.slide_rail_outer_y(T, A, T, g)
            assert SL.slide_rail_anim_y(max(T, A), A, T, True, g) == settled_top
            assert SL.slide_rail_anim_y(T, A, T, False, g) == T
            for y in range(T, T + 400, 13):
                assert SL.slide_rail_anim_y(max(y, A), A, T, True, g) == max(y, settled_top)
    for g in (12, 16):
        assert SL.slide_rail_anim_x(300, 347, 728, g) == 347
        assert SL.slide_rail_anim_y(400, 238, 100, True, g) == 400
    assert SL.slide_frames(100, 600, 5, True) == [500, 400, 300, 200, 100]
    assert SL.slide_frames(100, 603, 5, True)[-1] == 100
    assert SL.slide_frames(100, 600, 5, False) == [200, 300, 400, 500, 600]


def test_railslide_yaml_bytes_match_the_assembler():
    """The shipped thunk_filedlg_railslide bytes == assemble_railslide's output (v2, in place at pcave2+0x3280)."""
    import assemble_railslide as AS
    src = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    i = src.index("      - id: thunk_filedlg_railslide\n")
    line = src[i:src.index("\n", src.index("bytes:", i))]
    assert line.split('"')[1] == AS.template()
    assert "offset: 0x3280" in src[i:i + 120]


def _settled_pairs(rig, bw, wh, g, color=0x40):
    """Draw the four settled strips on a bw x wh canvas through railscale; return each strip's columns on row 0."""
    rig.window(4096, 2304, bw, wh)
    xargs = SL.slide_rail_local_x_args(bw)
    out = []
    for k in range(4):
        rig.settled(k, xargs[k], 0, color + k)
        cols = rig.span(WPLANE, WSTRIDE, 0, color + k)
        assert cols and cols == list(range(cols[0], cols[-1] + 1)), (g, bw, k)
        rig.clear(WPLANE, WSTRIDE, 0, (SPR_H * g >> 4) + 1, cols[0], cols[-1])
        out.append(cols)
    return out


@pytest.mark.parametrize("g", range(17, 49))
def test_scaling_settled_rail_pairs_every_canvas_width(code, g):
    """railscale v3 over a run of consecutive canvas widths (every phase of fl(bw*16/g) and of (N - 0x37)*g/16): the
    left pair at 0 / fl(15g/16), the inner right strip at railscale's double floor (rail_right_anchor -- the column
    every abutting frame R reads, unchanged from v2), the outer right strip directly against it, every strip
    fl(w*g/16) wide, the outer right end inside the canvas and never right of v2's.  Both arms (A: the armed rail
    window; B: a generic canvas taller than the art)."""
    rig = _rig(code, g)
    base = SL.scale_px(520, g)
    for arm_a in (True, False):
        _w32(rig.mu, G_FLAG, 1 if arm_a else 0)
        for bw in range(base, base + 2 * g + 18):
            ol, il, ir, orr = _settled_pairs(rig, bw, 600, g)
            assert ol[0] == 0 and il[0] == ol[-1] + 1 == (15 * g >> 4), (g, bw)
            assert ir[0] == SL.popup_scale_floor(SL.rail_right_anchor(bw, bw - 0x37, g), g), (g, bw)
            assert orr[0] == ir[-1] + 1, (g, bw)
            assert [len(c) for c in (ol, il, ir, orr)] == [(w * g) >> 4 for w in SL.SLIDE_RAIL_W]
            assert orr[-1] < bw and orr[-1] <= _v2_outer_right_end(bw, g), (g, bw)
            for k, c in enumerate((ol, il, ir, orr)):
                assert c[0] == SL.slide_rail_settled_x(bw, SL.slide_rail_local_x_args(bw)[k], g)
    assert not rig.native


@pytest.mark.parametrize("g", (17, 25, 40))
def test_railscale_gate(code, g):
    """railscale's gate: arm A (flag && dest == g_fd_winbuf) scales; arm B (dest != the screen buffer && canvas taller
    than the 529-row art) scales; a canvas the art covers, or the screen buffer, takes the native tail with every arg
    untouched; g <= 16 is native even when armed."""
    rig = _rig(code, g)
    sp = STACK + 0x8000

    def args():
        return [int.from_bytes(rig.mu.mem_read(sp + 4 * i, 4), "little") for i in range(1, 7)]

    rig.window(1600, 1200, 900, 529)                       # canvas == the art height: arm B declines
    _w32(rig.mu, G_FLAG, 0)
    rig.native.clear()
    rig.settled(3, 900 - 47, 5, 0x41)
    assert rig.native == [SPRITE_DRAW_2] and args() == [WB, 9, 900 - 47, 5, 1, 1]
    _w32(rig.mu, G_FLAG, 1)                                # armed: arm A scales regardless of the height
    rig.native.clear()
    rig.settled(3, 900 - 47, 5, 0x42)
    assert rig.native == []
    _w32(rig.mu, G_WINBUF, WB + 0x1000)                    # armed for another window, short canvas: native
    rig.native.clear()
    rig.settled(3, 900 - 47, 5, 0x43)
    assert rig.native == [SPRITE_DRAW_2] and args() == [WB, 9, 900 - 47, 5, 1, 1]
    rig.window(1600, 1200, 900, 530)                       # ... taller than the art: arm B scales
    rig.native.clear()
    rig.settled(3, 900 - 47, 5, 0x44)
    assert rig.native == []
    rig.native.clear()                                     # the screen buffer never arms B
    rig._call(rig.scale, 3, 0x45, (SCREEN_BUF, 9, 900 - 47, 5, 1, 1), CE, 0)
    assert rig.native == [SPRITE_DRAW_2] and args() == [SCREEN_BUF, 9, 900 - 47, 5, 1, 1]
    for gn in (16, 12):                                    # native at g <= 16, armed or not
        _w32(rig.mu, G_VA, gn)
        _w32(rig.mu, G_WINBUF, WB)
        rig.native.clear()
        rig.settled(2, 900 - 55, 0, 0x46)
        assert rig.native == [SPRITE_DRAW_2] and args() == [WB, 9, 900 - 55, 0, 1, 1]


def test_scaling_settled_outer_strip_y(code):
    """The settled outer strips' y arg (the ceil-descaled v', >= 0) lands at fl(v'*g/16) on both sides."""
    for g in (17, 22, 25, 33, 40, 48):
        rig = _rig(code, g)
        rig.window(4096, 2304, 1200, 1500)
        xargs = SL.slide_rail_local_x_args(1200)
        for v in (0, 1, 7, 150, 333):
            for k in (0, 3):
                rig.settled(k, xargs[k], v, 0x50 + k)
                x0 = SL.slide_rail_settled_x(1200, xargs[k], g)
                rows = rig.rows(WPLANE, WSTRIDE, x0, (v * g) >> 4, 0x50 + k, (SPR_H * g >> 4) + 2)
                assert rows and rows[0] == (v * g) >> 4, (g, v, k)
                rig.clear(WPLANE, WSTRIDE, rows[0], len(rows), x0, x0 + 30)


def test_railscale_yaml_bytes_match_the_assembler():
    """The shipped thunk_filedlg_railscale bytes == assemble_railscale's output (v3, in place at pcave2+0xC470)."""
    import assemble_railscale as AS
    src = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    i = src.index("      - id: thunk_filedlg_railscale\n")
    line = src[i:src.index("\n", src.index("bytes:", i))]
    assert line.split('"')[1] == AS.template()
    assert "offset: 0xC470" in src[i:i + 120]
    assert len(AS.assemble()) <= 0xC510 - 0xC470


@pytest.mark.parametrize("g", (17, 25, 40, 47))
def test_scaling_last_show_frame_bottom_equals_settled(code, g):
    """slide_show's last animation frame (slide row == T) draws every strip over EXACTLY the settled strip's rows:
    same top and same last row, including the strips that reach the window bottom B (the 529-row art outgrows the
    file dialog and the popups; the report window is taller than it).  v2's sprite-shrinking clamp ended them 1-3 rows above B (13,280 of the verifier's sweep draws)."""
    rig = _rig(code, g)
    sw, sh = _screens(g)[0]
    tall = 529                                                   # the real art: it outgrows the shorter windows
    for spr in SPRITES:
        _w32(rig.mu, spr + 0x14, tall)
    color = 0x60
    for name, L, T, bw, wh in _windows(sw, sh, g):
        if name not in ("report", "filedlg", "popup+0"):
            continue
        B = T + wh
        rig.window(sw, sh, bw, wh)
        A = SL.slide_rail_outer_a(T, sh, g)
        xargs = SL.slide_rail_local_x_args(bw)
        yv = SL.slide_rail_settled_v(T, A, T, g)
        for k in (1, 3):
            color += 1
            pix = SPR_PIX + 0x3000 + 0x2000 * k                  # a tall strip's own pixel block (w x 529)
            rig.mu.mem_write(pix, bytes([color]) * (SL.SLIDE_RAIL_W[k] * tall))
            _w32(rig.mu, SPRITES[k] + 0x04, pix)
            ytop = SL.slide_rail_outer_y(T, A, T, g) if OUTER[k] else 0
            rig._call(rig.scale, k, color, (WB, 9, xargs[k], yv if OUTER[k] else 0, 1, 1), CE, 0)
            x0 = SL.slide_rail_settled_x(bw, xargs[k], g)
            settled = rig.rows(WPLANE, WSTRIDE, x0, ytop, color, wh + 2)
            assert settled == list(range(ytop, min(wh, ytop + (tall * g >> 4)))), (name, k)   # clipped at the canvas
            y = max(T, A) if OUTER[k] else T
            rig.frame(k, L + xargs[k], y, color, True, T, A, (L, T, L + bw, B))
            anim = rig.rows(SPLANE, SSTRIDE, L + x0, T + ytop, color, min(wh + 2, sh - T - ytop))
            assert anim == [T + r for r in settled], (name, g, k, anim[:1], anim[-1:], T + settled[-1])
            rig.clear(WPLANE, WSTRIDE, 0, wh, x0, x0 + 30)
            rig.clear(SPLANE, SSTRIDE, T, wh, L + x0, L + x0 + 30)
