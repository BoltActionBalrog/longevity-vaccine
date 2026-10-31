"""Unicorn parity + law sweep for the UNFRAMED arm of the shared re-blit body (popup_art_reblit v4, 2026-10-17).

thunk_art_reblit_body (entered from thunk_art_reblit and thunk_parity_reblit) pinned source rows 0 and sh-1 as a 1-px
frame on EVERY sprite.  The diplomacy BIOSCAN colour bar (g_diplo_colour_bar_sprite, interface.pcx 9x147) and the
council portrait slots (g_faction_sprites + 0x478 / 0x4A4) have no frame, so their first / last device rows showed
source row 0 / sh-1 off the panel's stripe grid.  v4: t_art_frame_rows decides framed-ness by IDENTITY (the sprite's
pixel pointer) and the field row reads scaling_laws.art_reblit_row(framed=False) for those sprites.

Oracles: scaling_laws.art_reblit(framed=...) for the asm; a FROZEN copy of the v3 row law for "framed art is
byte-identical to before".  Emulated from the real assembled bytes at their real cave VAs (harness:
test_artreblit_asm_parity.emu on top of the council harness)."""
from __future__ import annotations

import pathlib

import pytest

import test_artreblit_asm_parity as TA
import test_council_asm_parity as TC
from test_council_asm_parity import HEAP, RET_SITE, SL, SP0

AR = TA.AR
VA = TA.VA
COUNCIL_SLOTS = (0x478, 0x4A4)
SLOT_SIZE = {0x478: (96, 115), 0x4A4: (118, 144)}
G = [17, 18, 21, 22, 25, 30, 40]                    # T = 1 (17..21) and 2 (22..47) rows; 4K = 40
G_SHORT = [17, 22, 25, 40]
import config
_GAME = config.game_dir(required=False)
GAME_PCX = (_GAME / "interface.pcx") if _GAME else pathlib.Path("interface.pcx-not-configured")


# ---- the v3 row law, frozen (popup_art_reblit v3, 2026-10-06) -----------------------------------------------------
def _v3_frame_rows(sh, num, den):
    dh = (sh * num) // den
    if sh < 2 or dh <= 0:
        return 0, 0
    jt = min(max((2 * dh + sh - 1) // (2 * sh), 0), dh)
    jb = min(max(((2 * dh * (sh - 1) - 1) // sh + 1) // 2, 0), dh)
    return jt, jb


def _v3_row(j, sh, num, den=16, y0=0):
    c = SL.nn_center_index(j, (sh * num) // den, sh)
    jt, jb = _v3_frame_rows(sh, num, den)
    if sh < 4 or not jt <= j < jb:
        return max(c, 0)
    y, h0, h1, phase = j - jt, sh - 2, jb - jt, y0 + jt
    k = SL.art_scan_field(y + phase, num, den)
    m = ((2 * y + 1) * h0 + (1 - 2 * k) * h1) // (4 * h1)
    m = min(max(m, 0), (h0 - k + 1) // 2 - 1)
    return 2 * m + k + 1


def _v3_reblit(dest, d_w, d_h, px, sw, sh, key, x, y, offx, offy, num, den=16):
    """v3 art_reblit (frozen): the same clip / offset / column rules around _v3_row."""
    out = bytearray(dest)
    x0, y0 = x + SL._idiv(offx * num, den), y + SL._idiv(offy * num, den)
    dw, dh = (sw * num) // den, (sh * num) // den
    if num <= den or x0 < 0 or y0 < 0:
        return bytes(out)
    iw = min(dw, d_w - x0)
    for j in range(dh if iw > 0 else 0):
        if y0 + j >= d_h:
            break
        r = _v3_row(j, sh, num, den, y0)
        for i in range(iw):
            v = px[r * sw + SL.art_reblit_col(i, sw, num, den)]
            if v != key:
                out[(y0 + j) * d_w + x0 + i] = v
    return bytes(out)


# ---- art --------------------------------------------------------------------------------------------------------------
def bar_sprite(sw=9, sh=147):
    """An unframed 1-row scanline gradient (the colour bar's structure): dark even rows, bright odd rows, no ring."""
    return [(0x30 + (r // 2) % 0x40 + (r & 1) * 0x80 + c) & 0xFF for r in range(sh) for c in range(sw)]


def portrait_sprite(sw, sh):
    return [(0x20 + (r * 7 + c * 3) % 0x80 + (r & 1) * 0x80) & 0xFF for r in range(sh) for c in range(sw)]


def real_colour_bar():
    np = pytest.importorskip("numpy")
    image = pytest.importorskip("PIL.Image")
    if not GAME_PCX.exists():
        pytest.skip("game install not present")
    a = np.asarray(image.open(GAME_PCX))
    return [int(v) for v in a[1:148, 212:221].ravel()]


BAR_DATA_VA = 0x7D161C + 4                         # g_diplo_colour_bar_sprite + Sprite +4 (its pixel pointer)


def arm(e, ident, data):
    """Point an identity slot at `data`: 'bar' = the colour bar, (f, slot) = council portrait slot."""
    if ident == "bar":
        e.w32(BAR_DATA_VA, data)                     # the literal VA, not the module's constant: a wrong address is caught
    elif ident is not None:
        f, slot = ident
        e.w32(0x78E978 + f * 0x65C + slot + 4, data)


def run(e, px, sw, sh, g, y, ident=None, key=9, offx=0, offy=0, entry="thunk_art_reblit", x=3, W=520, H=440):
    """key = the stack key (> 0xFF = opaque); the sprite's own key byte stays 9."""
    spr = HEAP + 0x10000
    data = TC.mk_sprite(e, spr, px, sw, sh, key=key & 0xFF if key <= 0xFF else 9, offx=offx, offy=offy)
    arm(e, ident, data)
    dest = HEAP + 0x30000
    dd = TC.mk_buffer(e, dest, W, H, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(dd, W * H))
    va = VA[entry] if entry in VA else TC.VA[entry]
    land = e.run(va, regs={"ecx": spr, "ebx": 0x11, "esi": 0x22, "edi": 0x33, "ebp": 0x44},
                 stack=[RET_SITE, dest, key, x, y, g, 16])
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18
    for k, v in (("ebx", 0x11), ("esi", 0x22), ("edi", 0x33), ("ebp", 0x44)):
        assert e.reg(k) == v, k
    return before, bytes(e.uc.mem_read(dd, W * H)), W, H


def law(before, W, H, px, sw, sh, g, y, framed, key=9, x=3, offx=0, offy=0):
    return SL.art_reblit(before, W, H, W, bytes(px), sw, sh, sw, key, x, y, offx, offy, g, 16, framed=framed)


# ---- law ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", list(range(16, 65)))
def test_scaling_art_framed_law_unchanged(g):
    """framed=True (the default) is the v3 law exactly, for every size, ratio and grid phase."""
    for sh in list(range(1, 41)) + [96, 115, 118, 119, 120, 124, 144, 147, 157, 158, 198]:
        dh = sh * g // 16
        for y0 in range(8):
            want = [_v3_row(j, sh, g, 16, y0) for j in range(dh)]
            assert [SL.art_reblit_row(j, sh, g, 16, y0) for j in range(dh)] == want, (sh, y0)
            assert [SL.art_reblit_row(j, sh, g, 16, y0, True) for j in range(dh)] == want, (sh, y0)
        if sh >= 2 and dh > 0:
            assert SL.art_frame_rows(sh, g) == _v3_frame_rows(sh, g, 16)
            assert SL.art_frame_rows(sh, g, 16, False) == (0, dh)


@pytest.mark.parametrize("g", list(range(17, 65)))
@pytest.mark.parametrize("y0", [0, 1, 2, 3, 5, 6])
def test_scaling_art_unframed_law(g, y0):
    """Unframed art: EVERY device row (first and last included) shows a source row of its own field on the dest
    buffer's stripe grid (field k -> source parity k ^ 1, as framed), within 2 rows of the centre map, never stepping
    back more than a pair, every field a whole T-row stripe; both ends reach the art's first / last row pair."""
    t = SL.art_scan_rows(g)
    for sh in (4, 5, 9, 10, 96, 115, 118, 144, 147):
        dh = sh * g // 16
        rows = [SL.art_reblit_row(j, sh, g, 16, y0, False) for j in range(dh)]
        last = -9
        for j, r in enumerate(rows):
            assert 0 <= r < sh and (r - 1) & 1 == SL.art_scan_field(y0 + j, g), (sh, j, r)
            assert abs(r - SL.nn_center_index(j, dh, sh)) <= 2, (sh, j, r)
            assert r >= last - 2
            last = max(last, r)
        assert rows[0] in (0, 1) and rows[-1] in (sh - 2, sh - 1), (sh, rows[:3], rows[-3:])
        j0 = (-y0) % t
        fields = [(r - 1) & 1 for r in rows[j0:]]
        assert all(len(set(fields[s:s + t])) == 1 for s in range(0, len(fields) - t + 1, t)), sh
        assert all(fields[s] != fields[s + t] for s in range(0, len(fields) - 2 * t + 1, t)), sh


def test_scaling_art_unframed_native_identity():
    px = bytes(bar_sprite())
    assert SL.art_reblit(bytes(400 * 200), 200, 400, 200, px, 9, 147, 9, 9, 3, 5, 0, 0, 16, 16, framed=False) \
        == bytes(400 * 200)


# ---- asm: framed art unchanged ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", G_SHORT)
@pytest.mark.parametrize("sw,sh,offx,offy", [(7, 10, 0, 0), (12, 9, 1, 2), (200, 120, 0, 0), (131, 157, 0, 0),
                                            (5, 3, 0, 0), (12, 9, -1, -1), (96, 115, 0, 0), (9, 147, 0, 0)])
@pytest.mark.parametrize("y", [5, 6])
@pytest.mark.parametrize("entry", ["thunk_art_reblit", "thunk_parity_reblit"])
def test_framed_unchanged(g, sw, sh, offx, offy, y, entry):
    """No identity armed (incl. a 9x147 and a 96x115 sprite: shape is NOT the test): the v3 law, byte for byte."""
    e = TA.emu(g)
    px = TA.framed_sprite(sw, sh)
    before, got, W, H = run(e, px, sw, sh, g, y, offx=offx, offy=offy, entry=entry)
    want = _v3_reblit(before, W, H, px, sw, sh, 9, 3, y, offx, offy, g)
    assert got == want == law(before, W, H, px, sw, sh, g, y, True, offx=offx, offy=offy)


@pytest.mark.parametrize("g", [22, 25, 40])
def test_framed_with_identities_elsewhere(g):
    """Identity slots armed with OTHER pointers (a live game: the bar and all 16 council slots loaded): a framed
    picture still takes the framed law."""
    e = TA.emu(g)
    arm(e, "bar", HEAP + 0x90000)
    for f in range(8):
        for slot in COUNCIL_SLOTS:
            arm(e, (f, slot), HEAP + 0x91000 + f * 0x100 + slot)
    px = TA.framed_sprite(200, 120)
    before, got, W, H = run(e, px, 200, 120, g, 6)
    assert got == law(before, W, H, px, 200, 120, g, 6, True)


# ---- asm: unframed art -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", G)
@pytest.mark.parametrize("y", [0, 1, 3, 6])
@pytest.mark.parametrize("entry", ["thunk_art_reblit", "thunk_parity_reblit"])
def test_colour_bar_unframed(g, y, entry):
    e = TA.emu(g)
    px = bar_sprite()
    before, got, W, H = run(e, px, 9, 147, g, y, ident="bar", entry=entry)
    assert got == law(before, W, H, px, 9, 147, g, y, False)


@pytest.mark.parametrize("g", [18, 22, 25, 40])
@pytest.mark.parametrize("y", [0, 1])
def test_colour_bar_real_asset(g, y):
    """The real interface.pcx bar (skipped without a game install), opaque key and key 9."""
    px = real_colour_bar()
    for key in (9, 0x100):
        e = TA.emu(g)
        before, got, W, H = run(e, px, 9, 147, g, y, ident="bar", key=key)
        assert got == law(before, W, H, px, 9, 147, g, y, False, key=key)


SD2_STUB = b"\xB8\x66\x00\x00\x00\xC2\x18\x00"           # mov eax,0x66 ; ret 0x18


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_colour_bar_via_art_draw(g):
    """The bar's real path: t_dp_sd2_bar tails into thunk_art_draw (Sprite_draw_2, then thunk_art_reblit)."""
    e = TC.Emu(g, stubs={TC.AC.SD2: SD2_STUB})
    e.uc.mem_map(AR.PCAVE2 + 0x1C000, 0x1000)
    e.uc.mem_map(AR.PCAVE2 + 0x2D000, 0x1000)
    for _n, (off, b) in TA.LAY.items():
        e.uc.mem_write(AR.PCAVE2 + off, b)
    px = bar_sprite()
    spr = HEAP + 0x10000
    arm(e, "bar", TC.mk_sprite(e, spr, px, 9, 147))
    dest = HEAP + 0x30000
    W, H = 300, 400
    data = TC.mk_buffer(e, dest, W, H, data=HEAP + 0x40000)
    before = bytes(e.uc.mem_read(data, W * H))
    land = e.run(VA["thunk_art_draw"], regs={"ecx": spr, "esi": 0x5151, "ebx": 0x61, "edi": 0x62},
                 stack=[RET_SITE, dest, 9, 31, 13, g, 16])
    got = bytes(e.uc.mem_read(data, W * H))
    if g <= 16:
        assert got == before
        return
    assert land == RET_SITE and e.reg("esp") == SP0 + 4 + 0x18 and e.reg("eax") == 0x66
    assert e.reg("esi") == 0x5151 and e.reg("ebx") == 0x61 and e.reg("edi") == 0x62
    assert got == SL.art_reblit(before, W, H, W, bytes(px), 9, 147, 9, 9, 31, 13, 0, 0, g, 16, framed=False)


@pytest.mark.parametrize("g", G_SHORT)
@pytest.mark.parametrize("ident", [(0, 0x478), (7, 0x478), (3, 0x4A4), (7, 0x4A4)])
@pytest.mark.parametrize("y", [4, 7])
def test_council_unframed(g, ident, y):
    sw, sh = SLOT_SIZE[ident[1]]
    e = TA.emu(g)
    px = portrait_sprite(sw, sh)
    before, got, W, H = run(e, px, sw, sh, g, y, ident=ident, entry="thunk_parity_reblit")
    assert got == law(before, W, H, px, sw, sh, g, y, False)


@pytest.mark.parametrize("g", [22, 25, 40])
def test_no_state_carried_between_draws(g):
    """unframed -> framed -> unframed in one emulator, identities re-pointed between draws: each draw is its own law
    (the unframed flag is rewritten by every call, never inherited)."""
    e = TA.emu(g)
    bar = bar_sprite()
    before, got, W, H = run(e, bar, 9, 147, g, 3, ident="bar")
    assert got == law(before, W, H, bar, 9, 147, g, 3, False)
    e.w32(BAR_DATA_VA, 0)
    px = TA.framed_sprite(200, 120)
    before, got, W, H = run(e, px, 200, 120, g, 5)
    assert got == law(before, W, H, px, 200, 120, g, 5, True)
    before, got, W, H = run(e, bar, 9, 147, g, 3)                     # same pixels, identity gone: framed
    assert got == law(before, W, H, bar, 9, 147, g, 3, True)
    before, got, W, H = run(e, bar, 9, 147, g, 2, ident=(5, 0x4A4), entry="thunk_parity_reblit")
    assert got == law(before, W, H, bar, 9, 147, g, 2, False)


@pytest.mark.parametrize("entry", ["thunk_art_reblit", "thunk_parity_reblit"])
@pytest.mark.parametrize("ident", ["bar", (2, 0x478)])
def test_native_noop(entry, ident):
    e = TA.emu(16)
    before, got, _W, _H = run(e, bar_sprite(), 9, 147, 16, 3, ident=ident, entry=entry)
    assert got == before


def test_helper_layout():
    """t_art_frame_rows sits in the vacated slot between thunk_art_draw's reserve and g_art_spr; the body shrank
    and still ends before t_pw_enlarge; the stub entry bytes uimod.dll checks are unchanged."""
    assert AR.COLOUR_BAR_DATA == BAR_DATA_VA == 0x7D1620          # the identity the thunk compares against
    off_fr, fr = TA.LAY["t_art_frame_rows"]
    off_b, body = TA.LAY["thunk_art_reblit_body"]
    assert off_fr == 0x29F20 and off_fr + len(fr) <= AR.OFF_G_ART_SPR and fr[-1] == 0xC3
    assert off_b + len(body) <= AR.REBLIT_BODY_END == 0x27900
    assert TA.LAY["thunk_art_reblit"][1][:6] == bytes.fromhex("5589E583EC50")
