"""Guard for group commlink_mp_spots (2026-11-07): the COMMLINK panel's multiplayer click spots and the collapsed
multiplayer layout's bottom pin.

Ports: t_clmp_hdr / t_clmp_strip / t_clmp_led / t_clmp_clip / t_clmp_rowy (assemble_commlink_mp.py; t_clmp_rowy is
hm_rowY's entry).  Laws: scaling_laws.commlink_sc / commlink_row_y / commlink_panel_y / commlink_pin_shift /
commlink_spot (ports of the panel's hm_sc / hm_rowY, which commlink_menu_scale draws with).

Layers:
  1. commlink_sc / commlink_panel_y equal the baked hm_sc / hm_rowY bytes under Unicorn (every y 0..400, g 16..40), in
     single player, the expanded and the collapsed multiplayer layouts;
  2. the REAL image's panel in multiplayer (commlink_mp_emu.panel), collapsed and expanded:
     - every type-2 / type-0 spot is commlink_spot(...) of the native rect the site built (read from the drawn
       strip / LED sprite's native position: the time widget = the header strip sprite +0x1110, the strip under it =
       +0x113C, the LED = the +0x1060 sprite's row) and covers the device rows / columns that sprite is drawn at;
     - collapsed: the block (title strip, widget, strip) is drawn contiguous from commlink_panel_y(its native top)
       to the canvas bottom, nothing above it; the strip's spot, clip and text rect all end ON the canvas bottom;
     - no transparent row between the multiplayer strips (commlink_strip_rows: the strips off the 18-row grid grow
       to their row-law span), every g 17..40, both layouts;
     - Spot_check at the centre of the drawn widget / strip / each LED returns type 2 / 2 / 0 (the right faction for
       an LED), at the centre of a faction row's name area type 1;
  3. both changes are multiplayer-only: with the pin and the span off, single player renders byte-identical; with
     the pin off the expanded layout is byte-identical and the collapsed block lands commlink_pin_shift higher;
  4. g = 16: the spots and canvas are the pristine exe's.
Cost: ~3 s per panel; one item per (g, layout).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
pytest.importorskip("unicorn", reason="unicorn absent")

import assemble_commlink_mp as M  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x00668740
MW = M.MW
HDR_SPRITE, STRIP_SPRITE, TITLE_SPRITE = MW + 0x1110, MW + 0x113C, MW + 0x10E4
LED_SPRITES = {MW + 0x1060 + 0x2C * i for i in range(3)}
HM_ROWY_ORIGINAL = bytes.fromhex("83F8067C4F53")     # cmp eax, 6 / jl small / push ebx (the pin's displaced bytes)
NATIVE_H = SL.commlink_mp_native_height()            # 222
FIELDS = {0x1158: 18, 0x11B4: 24, 0x1100: 6, 0x112C: 28}   # the built panel's (commlink_mp_emu, every g)


# ============================================================================================ layer 1
@pytest.fixture(scope="module")
def helpers(baked_exe):
    """hm_sc / hm_rowY (-> t_clmp_rowy) as baked, in a bare Unicorn: pcave2, g, MultiplayerActive, the MultiWin."""
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    pe = pefile.PE(str(baked_exe), fast_load=True)
    img = pe.get_memory_mapped_image()
    base = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(M.PCAVE2, 0x41000)
    mu.mem_write(M.PCAVE2, img[M.PCAVE2 - base:M.PCAVE2 - base + 0x41000])
    mu.mem_map(0x00668000, 0x1000)
    mu.mem_map(0x0093F000, 0x1000)
    mu.mem_map(0x007FD000, 0x3000)                   # MultiWin 0x7FD648 .. +0x11B4, its Buffer +0x444
    mu.mem_map(0x10000000, 0x2000)                   # stack + the 0x10001000 hlt marker
    mu.mem_write(0x10001000, b"\xF4")
    for off, v in FIELDS.items():
        mu.mem_write(MW + off, struct.pack("<i", v))
    return mu


def _call(mu, fn, eax, g, mp=0, expanded=1, panel_h=0):
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_EBX, UC_X86_REG_ECX
    mu.mem_write(G_VA, struct.pack("<I", g))
    mu.mem_write(0x0093F660, struct.pack("<I", mp))
    mu.mem_write(MW + 0xA24, struct.pack("<I", expanded))
    mu.mem_write(M.PANEL_H, struct.pack("<i", -panel_h))
    mu.mem_write(0x10000F00, struct.pack("<I", 0x10001000))
    mu.reg_write(UC_X86_REG_ESP, 0x10000F00)
    mu.reg_write(UC_X86_REG_EAX, eax)
    mu.reg_write(UC_X86_REG_EBX, 0x0BB0BB0B)
    mu.reg_write(UC_X86_REG_ECX, 0x0CC0CC0C)
    mu.emu_start(fn, 0x10001000, count=500)
    assert mu.reg_read(UC_X86_REG_ESP) == 0x10000F04, "ret pops exactly the return address"
    assert (mu.reg_read(UC_X86_REG_EBX), mu.reg_read(UC_X86_REG_ECX)) == (0x0BB0BB0B, 0x0CC0CC0C), "ebx / ecx kept"
    return struct.unpack("<i", struct.pack("<I", mu.reg_read(UC_X86_REG_EAX)))[0]


@pytest.mark.parametrize("g", range(16, 41))
def test_the_law_is_the_baked_helpers(helpers, g):
    H = SL.commlink_sc(NATIVE_H, g)
    for y in range(0, 401):
        assert _call(helpers, M.HM_SC, y, g) == SL.commlink_sc(y, g), (g, y)
        sp = SL.commlink_row_y(y, g)
        assert _call(helpers, M.HM_ROWY, y, g, mp=0, expanded=0, panel_h=H) == sp, ("single player", g, y)
        assert _call(helpers, M.HM_ROWY, y, g, mp=1, expanded=1, panel_h=H) == sp, ("expanded", g, y)
        assert _call(helpers, M.HM_ROWY, y, g, mp=1, expanded=0, panel_h=H) == \
            SL.commlink_panel_y(y, g, H, True), ("collapsed", g, y)
        # not the multiplayer box (built for single player; commlink_win_build's 0-tall canvas): no pin (audit #1)
        for other in (0, SL.commlink_sc(156, g), H + 1):
            assert _call(helpers, M.HM_ROWY, y, g, mp=1, expanded=0, panel_h=other) == sp, ("not the MP box", g, y)
            assert SL.commlink_panel_y(y, g, other, True) == sp


def test_rowy_reentry_literals():
    """t_clmp_rowy re-enters hm_rowY at literal addresses (+6 after the displaced `cmp / jl / push ebx`, +0x54 the
    y < 6 path): they must be hm_rowY's own, and the bytes there what the re-entry expects."""
    import assemble_hudmenu_scale as HM
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    va = HM.V["hm_rowY"]
    assert M.HM_ROWY == va and M.HM_ROWY_BODY == va + 6 and M.HM_ROWY_SMALL == va + 0x54
    assert HM.T_CLMP_ROWY == M.PCAVE2 + M.SLOTS["t_clmp_rowy"]
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(HM.ASMS["hm_rowY"], va)[0])
    assert b[:6] == b"\x68" + HM.T_CLMP_ROWY.to_bytes(4, "little") + b"\xC3"
    assert b[6] == 0x51                                        # push ecx: the body after the displaced push ebx
    assert b[0x54:0x57] == b"\x0F\xAF\x05"                      # imul eax, [g]: hm_sc's y < 6 path
    assert b"\x59\x5B\xC3" in b[:0x54]                          # pop ecx / pop ebx / ret ends the body before +0x54


def test_spot_law_identity_and_shape():
    assert SL.commlink_spot(7, 138, 18, 18, 16, True) == (7, 138, 18, 18)
    assert SL.commlink_spot(0, 180, 345, 28, 40, False, 555) == (0, 450, 345, 70)
    assert SL.commlink_bottom(222, 25, 347) == 347 and SL.commlink_row_y(222, 25) == 345   # the panel bottom rule
    assert SL.commlink_spot(7, 120, 18, 18, 40, True)[0] == 18
    assert NATIVE_H == 7 * 18 + 2 * 24 + 6 + 28 + 0xE == 222


@pytest.mark.parametrize("g", range(16, 81))
def test_pin_law(g):
    """The pin lands the collapsed block's bottom ON the box bottom at every g; the block keeps its own row law
    (a rigid shift); 0 at g 16 and wherever hm_rowY already ends on the box (g 24 / 32 / 40)."""
    H = SL.commlink_sc(NATIVE_H, g)
    d = SL.commlink_pin_shift(g, H)
    assert SL.commlink_panel_y(NATIVE_H, g, H, True) == H
    assert SL.commlink_bottom(NATIVE_H, g, H, True) == H
    for y in range(174, NATIVE_H + 1):
        assert SL.commlink_panel_y(y, g, H, True) - SL.commlink_row_y(y, g) == d
    assert abs(d) <= 6
    assert SL.commlink_panel_y(174, g, H, True) >= 0
    if g in (16, 24, 32, 40):
        assert d == 0
    # the pinned edges (title / widget / strip tops, the bottom) vs vanilla x g/16: within 1.5 px at every g (unpinned:
    # up to 6.5); > 1 px only at the edges ACTION_ITEMS (c) lists for the user (audit #2)
    for y in (174, 180, 208, NATIVE_H):
        assert abs(SL.commlink_panel_y(y, g, H, True) - y * g / 16) <= 1.5, (g, y)
    assert SL.commlink_pin_shift(g, 0) == 0 and SL.commlink_pin_shift(g, SL.commlink_sc(156, g)) == 0


# ============================================================================================ layer 2
CASES = [(g, x) for g in (17, 19, 20, 22, 25, 26, 40) for x in (0, 1)]
HDR_H, STRIP_H = 0x1C, 0x0E          # the header strip [+0x112C] and the strip rect {.., y + 0xE} (commlink_redraw)
CLIP_RET = 0x00479474                # right after commlink_redraw's Buffer_set_clip(the strip rect) at 0x47946F


def _native_y(blits, sprite, first=True):
    """The native y of `sprite`'s first (or only) blit in the repaint -- its args at the entry, before the
    commlink_menu_scale hook maps them.  +0x113C (the normal row sprite) is the strip under the widget first, then
    the faction rows; +0x1110 (the header strip) is blitted once."""
    ys = [a[3] for fn, s, a in blits if s == sprite]
    assert ys, hex(sprite)
    return ys[0] if first else ys[-1]


def _pin_off(e):
    e.uc.mem_write(M.HM_ROWY, HM_ROWY_ORIGINAL)


def _span_off(e):
    """t_clmp_synth's `mov [g_clmp_son], 1` -> 0: hm_synth_core's height block is then the original formula."""
    va = M.PCAVE2 + M.SLOTS["t_clmp_synth"]
    assert bytes(e.uc.mem_read(va, 2)) == b"\xC7\x05" and bytes(e.uc.mem_read(va + 6, 4)) == b"\x01\x00\x00\x00"
    e.uc.mem_write(va + 6, b"\x00")


def _title_off(e):
    """t_clmp_trow's `cmp [g_clmp_son], 0 / je out` -> jmp out: the core's source row is the plain DDA row again."""
    va = M.PCAVE2 + M.SLOTS["t_clmp_trow"]
    assert bytes(e.uc.mem_read(va + 12, 2)) == b"\x83\x3D" and bytes(e.uc.mem_read(va + 19, 1)) == b"\x74"
    e.uc.mem_write(va + 19, b"\xEB")


def _all_off(e):
    _pin_off(e)
    _span_off(e)
    _title_off(e)


HM_SYNTH = M.HM_SYNTH
TITLE = SL.COMMLINK_TITLE_SPRITE


def _title_draws(baked_exe, g, expanded, mp=1, pre=None):
    """Every hm_synth_core call on the title strip in the last repaint: its args, the panel canvas right before and
    right after it, the art, and the dest height H the core used ([ebp-0x30] at t_clmp_trow's first call)."""
    import commlink_mp_emu as C
    import image_emu as E
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ESP
    synth = M.PCAVE2 + M.SLOTS["t_clmp_synth"]
    code = M.build()["t_clmp_synth"]
    after = [i.address + i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(code, synth)
             if i.mnemonic == "call" and int(i.op_str, 16) == M.HM_SYNTH]
    assert len(after) == 1
    draws, cur = [], {}

    def entry(e):
        esp = e.reg(UC_X86_REG_ESP)
        a = [e.s32(esp + 4 + 4 * i) for i in range(6)]
        if a[5] & 0xFFFFFFFF != TITLE:
            return
        f = [e.s32(TITLE + 4 * i) for i in range(6)]
        import numpy as np
        art = np.frombuffer(bytes(e.uc.mem_read(f[1] & 0xFFFFFFFF, f[3] * f[5])), np.uint8).reshape(f[5], f[3])
        cur.update(args=a, pre=E.canvas_of(e, C.MW).copy(), art=art[:, :f[4]].tolist(), key=e.r32(TITLE + 8) & 0xFF,
                   h=None)

    def trow(e):
        if cur and cur["h"] is None:
            cur["h"] = e.s32(e.reg(UC_X86_REG_EBP) - 0x30)

    def done(e):
        if cur:
            cur["post"] = E.canvas_of(e, C.MW).copy()
            draws.append(dict(cur))
            cur.clear()
    out = C.panel(baked_exe, g, expanded, mp=mp, pre=pre,
                  hooks=[(HM_SYNTH, entry), (M.PCAVE2 + M.SLOTS["t_clmp_trow"], trow), (after[0], done)])
    return out, draws


TITLE_CASES = [(g, x, mp) for g in (17, 20, 22, 25, 30, 40) for x, mp in ((0, 1), (1, 1), (0, 0))]


@pytest.mark.parametrize("g, expanded, mp", TITLE_CASES)
def test_title_strip_lines_are_even(baked_exe, g, expanded, mp):
    """The real panel's title strip (MultiWin +0x10E4) as the core leaves it == scaling_laws.commlink_title_synth of the
    canvas before it (the real art, the core's own H: the multiplayer span included): its four 1-row lines K =
    stroke_width(g) rows each, the fill the rest on the stripe grid -- both layouts, single player too."""
    out, draws = _title_draws(baked_exe, g, expanded, mp)
    assert out["g"] == g and draws, "the title strip is synthesized"
    k = SL.stroke_width(g)
    for d in draws:
        dst, dx, dy, num, den, _spr = d["args"]
        assert d["h"] is not None and d["h"] >= 4 * k + 1
        c = d["pre"]
        want = bytearray(c.tobytes())
        SL.commlink_title_synth(want, c.shape[1], c.shape[1], c.shape[0], d["art"], d["key"], dx, dy, num, den, g,
                                h=d["h"])
        assert bytes(want) == d["post"].tobytes(), (g, expanded, mp)
        x = dx + (len(d["art"][0]) // 2 * num) // den
        sx = ((x - dx) * den) // num                         # the column the core samples there
        col = [int(d["post"][dy + j, x]) for j in range(4 * k)]
        assert col == [d["art"][j // k][sx] for j in range(4 * k)]


@pytest.mark.parametrize("g", (22, 40))
def test_title_off_is_the_old_nn(baked_exe, g):
    """Mutation guard: with t_clmp_trow's gate forced off the same draw is strip_synth's floor NN -- the 3,2,3,2 lines
    the user reported at 4K -- so the e2e law check above is not vacuous."""
    out, draws = _title_draws(baked_exe, g, 1, 1, pre=_title_off)
    assert draws
    d = draws[0]
    dst, dx, dy, num, den, _spr = d["args"]
    c = d["pre"]
    law = bytearray(c.tobytes())
    SL.commlink_title_synth(law, c.shape[1], c.shape[1], c.shape[0], d["art"], d["key"], dx, dy, num, den, g, h=d["h"])
    assert d["post"].tobytes() != bytes(law)
    k = SL.stroke_width(g)
    x = dx + (len(d["art"][0]) // 2 * num) // den
    sx = ((x - dx) * den) // num
    col = [int(d["post"][dy + j, x]) for j in range(4 * k)]
    assert col != [d["art"][j // k][sx] for j in range(4 * k)], "the old NN already had even lines"


def _drawn_rows(c):
    return [y for y in range(c.shape[0]) if (c[y] != 9).any()]


@pytest.mark.parametrize("g, expanded", CASES)
def test_mp_spots_cover_what_is_drawn(baked_exe, g, expanded):
    import commlink_mp_emu as C
    from unicorn.x86_const import UC_X86_REG_EBP
    clips, texts = [], []

    def clip(e):                     # the strip text's clip, as the text write will see it
        clips.append(tuple(e.s32(C.BUF + 0x20 + 4 * i) for i in range(4)))

    def text(e):                     # the caller's strip rect after the text write (thunk_comm_cent7 maps it in place)
        ebp = e.reg(UC_X86_REG_EBP)
        texts.append(tuple(e.s32(ebp - 0x1C + 4 * i) for i in range(4)))
    first = C.panel(baked_exe, g, expanded, hooks=[(CLIP_RET, clip), (C.TEXT_RET, text)])
    assert first["g"] == g
    spots = first["spots"]
    t2 = [a for r, a in spots if a[1] == 2]
    t0 = [a for r, a in spots if a[1] == 0]
    t1 = [a for r, a in spots if a[1] == 1]
    assert len(t2) == 2, spots
    hdr = [a for a in t2 if a[0] == 0][0]
    strip = [a for a in t2 if a[0] == 3][0]
    c = first["canvas"]
    H, W = c.shape
    assert H == SL.commlink_sc(NATIVE_H, g)
    pinned = not expanded
    # the header / strip sprites' native y -> the device rows they are drawn on (the panel's own law)
    hy = _native_y(first["blits"], HDR_SPRITE, first=False)
    sy = _native_y(first["blits"], STRIP_SPRITE)
    py_ = lambda y: SL.commlink_panel_y(y, g, H, pinned)                  # noqa: E731
    assert hdr[2] == 0 and hdr[4] == W and strip[2] == 0 and strip[4] == W
    assert hdr[3] == py_(hy), (hdr, hy)
    assert hdr[3] + hdr[5] == SL.commlink_bottom(hy + HDR_H, g, H, pinned), (hdr, hy)
    assert strip[3] == py_(sy), (strip, sy)
    assert strip[3] + strip[5] == SL.commlink_bottom(sy + STRIP_H, g, H, pinned), (strip, sy)
    assert hdr[3] + hdr[5] == strip[3], "the widget's spot ends where the strip's begins (no gap, no overlap)"
    # the strip text's clip = the strip's own device rows; its text rect (thunk_comm_cent7 maps it in place through
    # the same pinned hm_rowY) = the same rows: the text is centred in the strip as drawn
    assert clips and clips[-1] == (0, strip[3], W, strip[3] + strip[5]), (clips, strip)
    assert texts, "the strip text path ran"
    assert texts[-1] == (0, strip[3], W, strip[3] + strip[5]), (texts, strip)
    assert strip[3] + strip[5] <= H
    if pinned:
        # collapsed: title strip, widget and strip are one block from the title's pinned top to the canvas bottom --
        # every row in it drawn, nothing drawn above it, the strip (and its spot) ending ON the box bottom
        ty = _native_y(first["blits"], TITLE_SPRITE)
        assert (ty, hy, sy) == (7 * 18 + 2 * 24, 7 * 18 + 2 * 24 + 6, 7 * 18 + 2 * 24 + 6 + 28)
        drawn = _drawn_rows(c)
        assert drawn == list(range(py_(ty), H)), (drawn[:3], drawn[-3:], py_(ty), H)
        assert strip[3] + strip[5] == H, (strip, H)
    clicks = [(W // 2, hdr[3] + hdr[5] // 2), (W // 2, strip[3] + strip[5] // 2),
              (W // 2, hdr[3]), (W // 2, strip[3] + strip[5] - 1)]
    if expanded:
        assert len(t0) == 6 and len(t1) == 6
        for led, row in zip(t0, t1):
            assert led[0] == row[0]
            assert led[2] + led[4] <= row[2], ("the LED's spot stops before the row's name spot", led, row)
            assert led[3] == row[3] and led[5] == row[5], ("the LED's spot spans the row's height", led, row)
            assert (led[2], led[4]) == (SL.commlink_sc(7, g), SL.commlink_sc(25, g) - SL.commlink_sc(7, g))
            clicks += [(led[2] + led[4] // 2, led[3] + led[5] // 2), (row[2] + row[4] // 2, row[3] + row[5] // 2)]
    again = C.panel(baked_exe, g, expanded, clicks=clicks)
    hits = again["hits"]
    assert [hits[p][0] for p in clicks[:4]] == [2, 2, 2, 2], hits
    if expanded:
        for k, (led, row) in enumerate(zip(t0, t1)):
            hl, hr = hits[clicks[4 + 2 * k]], hits[clicks[5 + 2 * k]]
            assert hl[0] == 0 and hl[1] == led[0], (led, hl)
            assert hr[0] == 1 and hr[1] == row[0], (row, hr)


# ============================================================================================ layer 3
@pytest.mark.parametrize("g", (17, 20, 22, 25, 30, 40))
def test_single_player_is_unchanged(baked_exe, g):
    """Pin and span both off (hm_rowY's original entry, g_clmp_son never set): the single-player panel is
    byte-identical -- both changes are multiplayer-only.  The title strip's even lines are NOT (the single-player
    panel draws the same strip: test_title_strip_lines_are_even covers it), so both sides run with that map off."""
    import commlink_mp_emu as C
    on = C.panel(baked_exe, g, 0, mp=0, pre=_title_off)
    off = C.panel(baked_exe, g, 0, mp=0, pre=_all_off)
    assert [s for r, s in on["spots"]] == [s for r, s in off["spots"]]
    assert (on["canvas"] == off["canvas"]).all()


@pytest.mark.parametrize("g", (20, 25, 40))
def test_sp_built_box_is_not_pinned(baked_exe, g):
    """A box built for single player (156 native rows) repainted with multiplayer on, collapsed: the pin stays off
    -- the canvas is not the multiplayer box -- so the repaint is exactly the pin-off one (audit #1)."""
    import commlink_mp_emu as C

    def mp_on(e):
        e.w32(0x0093F660, 1)
    on = C.panel(baked_exe, g, 0, mp=0, hooks=[(C.REDRAW, mp_on)])
    off = C.panel(baked_exe, g, 0, mp=0, hooks=[(C.REDRAW, mp_on)], pre=_pin_off)
    assert on["canvas"].shape[0] == SL.commlink_sc(156, g)
    assert [s for r, s in on["spots"]] == [s for r, s in off["spots"]]
    assert (on["canvas"] == off["canvas"]).all()


@pytest.mark.parametrize("g, expanded", [(g, x) for g in range(17, 41) for x in (0, 1)])
def test_mp_strips_leave_no_see_through_row(baked_exe, g, expanded):
    """Every row from the panel's first drawn row to its last has a drawn pixel: the title / widget / strip / rows /
    footers meet with no transparent (key 9) row between them -- the map never shows through the panel."""
    import commlink_mp_emu as C
    c = C.panel(baked_exe, g, expanded)["canvas"]
    d = _drawn_rows(c)
    assert d == list(range(d[0], d[-1] + 1)), [y for y in range(d[0], d[-1]) if y not in set(d)]


@pytest.mark.parametrize("g, expanded", [(20, 0), (20, 1), (22, 1), (25, 0)])
def test_span_off_shows_the_hairline(baked_exe, g, expanded):
    """The guard above can see the defect: with the span off (the old height block) these panels have a transparent
    row inside the strips."""
    import commlink_mp_emu as C
    c = C.panel(baked_exe, g, expanded, pre=_span_off)["canvas"]
    d = _drawn_rows(c)
    assert d != list(range(d[0], d[-1] + 1))


@pytest.mark.parametrize("g, expanded", [(g, x) for g in (19, 20, 22, 25, 40) for x in (1, 0)])
def test_the_pin_is_the_only_change(baked_exe, g, expanded):
    """Pin off = hm_rowY's original 6 entry bytes.  The expanded layout: identical canvases and spots.  Collapsed:
    the drawn block starts commlink_pin_shift lower (higher when negative); the spots move with it."""
    import commlink_mp_emu as C
    mp = 1
    on = C.panel(baked_exe, g, expanded, mp=mp)
    off = C.panel(baked_exe, g, expanded, mp=mp, pre=_pin_off)
    if expanded:
        assert [s for r, s in on["spots"]] == [s for r, s in off["spots"]]
        assert (on["canvas"] == off["canvas"]).all()
        return
    H = on["canvas"].shape[0]
    d = SL.commlink_pin_shift(g, H)
    a, b = _drawn_rows(on["canvas"]), _drawn_rows(off["canvas"])
    assert a[0] == b[0] + d, (a[0], b[0], d)
    assert a[-1] == H - 1
    sa = {s[0]: s for r, s in on["spots"] if s[1] == 2}
    sb = {s[0]: s for r, s in off["spots"] if s[1] == 2}
    assert sa[0][3] == sb[0][3] + d and sa[3][3] == sb[3][3] + d
    assert sa[3][3] + sa[3][5] == H


# ============================================================================================ layer 4
@pytest.mark.parametrize("expanded", (0, 1))
def test_g16_spots_are_the_pristine_exe(baked_exe, bak_path, expanded):
    import commlink_mp_emu as C
    a = C.panel(baked_exe, 16, expanded)
    b = C.panel(bak_path, 16, expanded)
    assert [s for r, s in a["spots"]] == [s for r, s in b["spots"]]
    assert a["canvas"].shape == b["canvas"].shape and (a["canvas"] == b["canvas"]).all()


# ============================================================================================ the strip-span law
#: the panel's sbc blits (native y, sprite rows, sprite) -- commlink_redraw at g 40 (the native list is the same at every g)
COLLAPSED_BLITS = [(174, 6), (180, 28), (208, 18)]
EXPANDED_BLITS = [(0, 6), (6, 28), (34, 18)] + [(48 + 18 * k, 18) for k in range(8)] + [(192, 24), (216, 24)]


@pytest.mark.parametrize("g", range(16, 81))
def test_strip_span_law(g):
    """commlink_strip_rows: grow only, at most 1 row, every strip within 1 px of vanilla x g/16; each strip reaches
    the next one's row-law top; single player and x != 0 (the LEDs) are the plain formula."""
    H = SL.commlink_sc(NATIVE_H, g)
    for blits, collapsed in ((COLLAPSED_BLITS, True), (EXPANDED_BLITS, False)):
        for i, (y, sh) in enumerate(blits):
            grid = sh == 18 and y >= 6 and (y - 6) % 18 == 0
            num, den = (SL.commlink_sc(18, g), 18) if grid else (g, 16)
            plain = (sh * num + den // 2) // den
            rows = SL.commlink_strip_rows(0, y, sh, num, den, g, True, H, collapsed)
            assert plain <= rows <= plain + 1, (g, y, sh)
            assert abs(rows - sh * g / 16) <= 1, (g, y, sh, rows)
            assert SL.commlink_strip_rows(0, y, sh, num, den, g, False, H, collapsed) == plain
            assert SL.commlink_strip_rows(7, y, sh, num, den, g, True, H, collapsed) == plain
            if i + 1 < len(blits) and blits[i + 1][0] <= y + sh:
                top = SL.commlink_panel_y(y, g, H, collapsed)
                assert top + rows >= SL.commlink_panel_y(blits[i + 1][0], g, H, collapsed), ("gap", g, y)


HDR = SL.COMMLINK_HEADER_SPRITE


def _header_draws(baked_exe, g, expanded):
    """Every t_clhd_draw in the last repaint: its args, the canvas right before (the core's draw) and right after."""
    import assemble_commlink_hdr as HD
    import commlink_mp_emu as C
    import image_emu as E
    import numpy as np
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    from unicorn.x86_const import UC_X86_REG_ESP
    post = HD.VA["t_clmp_post"]
    code = HD.build()["t_clmp_post"]
    after = [i.address + i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(code, post) if i.mnemonic == "call"]
    assert len(after) == 1
    draws, cur = [], {}

    def entry(e):
        esp = e.reg(UC_X86_REG_ESP)
        a = [e.s32(esp + 4 + 4 * i) for i in range(7)]
        f = [e.s32(HDR + 4 * i) for i in range(6)]
        art = np.frombuffer(bytes(e.uc.mem_read(f[1] & 0xFFFFFFFF, f[3] * f[5])), np.uint8).reshape(f[5], f[3])
        cur.update(args=a, pre=E.canvas_of(e, C.MW).copy(), art=art[:, :f[4]].tolist(), key=e.r32(HDR + 8) & 0xFF)

    def done(e):
        if cur:
            cur["post"] = E.canvas_of(e, C.MW).copy()
            draws.append(dict(cur))
            cur.clear()
    out = C.panel(baked_exe, g, expanded, hooks=[(HD.VA["t_clhd_draw"], entry), (after[0], done)])
    return out, draws


@pytest.mark.parametrize("g, expanded", [(g, x) for g in (17, 20, 22, 25, 30, 40) for x in (0, 1)])
def test_header_strip_is_the_zone_law(baked_exe, g, expanded):
    """The real multiplayer header strip (MultiWin +0x1110) as the post-pass leaves it == scaling_laws.
    commlink_header_synth of the core's draw (the real art, the core's H); its margin column is uniform T-row stripes
    on the canvas grid (the 3-colour 1/2/3-row beat of the user's 4K shot gone) and its e4 top border K rows."""
    out, draws = _header_draws(baked_exe, g, expanded)
    assert out["g"] == g and len(draws) == 1, "the header strip is redrawn once per repaint"
    d = draws[0]
    dst, dx, dy, num, den, spr, h = d["args"]
    assert spr == HDR and (num, den) == (g, 16) and h >= SL.strip_synth_dims(138, 28, g, 16)[1]
    c = d["pre"]
    want = bytearray(c.tobytes())
    assert SL.commlink_header_synth(want, c.shape[1], c.shape[1], c.shape[0], d["art"], d["key"], dx, dy, num, den, g,
                                    h=h)
    assert bytes(want) == d["post"].tobytes(), (g, expanded)
    k = SL.stroke_width(g)
    cmap = SL.commlink_zone_map(SL.COMMLINK_HEADER_COL_SEGS, SL.strip_synth_dims(138, 28, g, 16)[0], k)
    rmap = SL.commlink_zone_map(SL.COMMLINK_HEADER_ROW_SEGS, h, k)
    x = dx + cmap.index(2)                                   # a margin column (native col 2: c5 / 41 all the way)
    col = [int(d["post"][dy + j, x]) for j in range(h) if 0 <= dy + j < d["post"].shape[0]]
    for j, v in enumerate(col):
        if rmap[j] in (0, 1) or 5 <= rmap[j] <= 22 or rmap[j] in (26, 27):
            assert v == (0xC5 if SL.stripe_top(dy + j, g) else 0x41), (g, j, hex(v))
    xi = dx + cmap.index(60)                                 # an interior column: the e4 border rows are K rows
    border = [j for j in range(h) if int(d["post"][dy + j, xi]) == 0xE4]
    assert len(border) == 2 * k, (g, border)
    # the inner c2 / c5 box opens on a stripe-top row and closes on a period end (audit 2026-11-07: a 1-row sliver or
    # a doubled band at most g), and no c2 lands outside the box columns (the shared c5's corner AA texel)
    T, P = SL.stripe_rows(g), SL.stripe_period(g)
    inner = [j for j in range(h) if int(d["post"][dy + j, xi]) == 0xC2]
    assert inner and (dy + inner[0]) % P == 0 and (dy + inner[-1] + 1 + T) % P == 0, (g, expanded, inner[:3])
    lo, hi = dx + cmap.index(10), dx + len(cmap) - cmap[::-1].index(128)
    strip = d["post"][max(dy, 0):dy + h]
    assert not (strip[:, max(dx, 0):lo] == 0xC2).any() and not (strip[:, hi:dx + len(cmap)] == 0xC2).any()


@pytest.mark.parametrize("g", (22, 40))
def test_header_banded_without_the_post_pass(baked_exe, g):
    """Mutation guard: the core's own draw (the canvas before t_clhd_draw) is NOT the law -- the e2e check above is
    not vacuous, and the core alone shows the reported beat."""
    out, draws = _header_draws(baked_exe, g, 1)
    d = draws[0]
    assert d["pre"].tobytes() != d["post"].tobytes()
    dst, dx, dy, num, den, spr, h = d["args"]
    x = dx + SL.commlink_zone_map(SL.COMMLINK_HEADER_COL_SEGS, SL.strip_synth_dims(138, 28, g, 16)[0],
                                  SL.stroke_width(g)).index(2)
    col = [int(v) for v in d["pre"][dy + 4 * SL.stroke_width(g) + 4:dy + h - 8, x]]
    assert 0xC2 in col, "the core alone recolours the outside margin (the reported 3-colour beat)"


@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_header_post_pass_never_runs_in_single_player(baked_exe, g):
    """Single player never blits the multiplayer header: no t_clhd_draw at all."""
    import assemble_commlink_hdr as HD
    import commlink_mp_emu as C
    calls = []
    C.panel(baked_exe, g, 0, mp=0, hooks=[(HD.VA["t_clhd_draw"], lambda e: calls.append(1))])
    assert calls == []


@pytest.mark.parametrize("g, expanded, mp, hl", [(g, x, m, 0) for g in (17, 20, 22, 25, 30, 40)
                                                for x, m in ((0, 1), (1, 1), (0, 0))] +
                         [(g, 1, m, 1) for g in (17, 25, 40) for m in (0, 1)])
def test_rails_line_up_on_every_strip(baked_exe, g, expanded, mp, hl):
    """One column map for every railed COMMLINK strip (scaling_laws.commlink_rail_strip_synth; user 2026-11-08: the
    time widget's rails uneven and seamed with the rail below): on every panel row under the title the e9 edge and
    both bf rails are exactly the K = stroke_width(g) columns commlink_strip_cols(g) gives them -- the header, the
    faction rows, the footer, both multiplayer layouts and single player."""
    import commlink_mp_emu as C
    cols = SL.commlink_strip_cols(g)
    rails = {c: [j for j, v in enumerate(cols) if v == c] for c in (0, 5, 133)}
    assert all(len(xs) == SL.stroke_width(g) for xs in rails.values())
    hooks = [(C.REDRAW, lambda e: e.w32(C.MW + 0x1168, 3))] if hl else []      # hl: faction 3's row highlighted (+0x116C)
    r = C.panel(baked_exe, g, expanded, mp=mp, hooks=hooks)
    cv = r["canvas"]
    if hl:
        assert any(s_ == C.MW + 0x116C for fn, s_, a in r["blits"]), "the highlight strip is drawn"
    drawn = [y for y in range(cv.shape[0]) if (cv[y] != 9).any()]
    top = drawn[0] + (6 * g + 8) // 16 + 1
    # no see-through pixel anywhere inside the panel below the title (the old SP panel's last column was key 9 at
    # g 17-19 / 25-27 / 33-35: its 18-row strips were narrower than the canvas)
    assert int((cv[top:drawn[-1] + 1] == 9).sum()) == 0
    bad = []
    for y in range(top, drawn[-1] + 1):
        for c, xs in rails.items():
            want = 0xE9 if c == 0 else 0xBF
            ok = all(cv[y, x] == want for x in xs) and cv[y, xs[-1] + 1] != want
            if xs[0] > 0:
                ok = ok and cv[y, xs[0] - 1] != want
            if not ok:
                bad.append((y, c))
    assert drawn[-1] - top > 30 and bad == [], bad[:8]
