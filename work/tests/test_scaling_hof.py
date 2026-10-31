"""Law sweep for the Hall of Fame screen (scaling_laws "HALL OF FAME" section).

The screen's scale is the Monument's unclamped popup numerator num = min(floor(16*ScreenH/768), floor(16*ScreenW/1024))
over 16 (fix 11; the sweep checks the art, rects, icon buttons and CLOSE stay inside the screen), clamped to
HOF_NUM_MAX = 72 (the painter's imm8 literals); every geometry value is vanilla x num/16 through half_down with the
identity at num == 16 (1024x768); the icon-button cells use floor (the parity-NN face scaler's output).  The asm
ports are checked bit-exactly in test_hof_asm_parity.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

RES = {(3840, 2160): (45, (480, 0)), (1600, 1200): (25, (0, 0)), (1920, 1080): (22, (256, 12)), (1024, 768): (16, (0, 0)),
       (7680, 4320): (72, (1536, 432))}
NUMS = list(range(16, 73))


def test_scale_num_is_the_monument_law_clamped_to_the_imm8_ceiling():
    for (sw, sh), (num, box) in RES.items():
        assert SL.hof_scale_num(sw, sh) == num
        assert SL.hof_letterbox(sw, sh, num) == box
    assert SL.hof_scale_num(4608, 3456) == 72 and SL.hof_scale_num(4608, 3457) == 72 and SL.hof_scale_num(4608, 3455) == 71
    assert SL.hof_scale_num(4607, 3456) == 71                          # the width term (fix 11)
    assert SL.hof_armed(3840, 2160, 1) and not SL.hof_armed(1024, 768, 1) and not SL.hof_armed(3840, 2160, 0)
    assert not SL.hof_armed(800, 600, 1)
    for sw in range(640, 7681, 41):
        for sh in range(480, 4321, 31):
            assert SL.hof_scale_num(sw, sh) == min(SL.mon_scale_num(sw, sh), SL.HOF_NUM_MAX)
            if sw * 768 >= sh * 1024:                                    # 4:3 and wider: the first bake's height law
                assert SL.hof_scale_num(sw, sh) == min((16 * sh) // 768, SL.HOF_NUM_MAX)


# narrower than 4:3 (fix 11; the user's 1280x1024 shot: the height-only num 21 cropped 32 px of stone wall per side)
NARROW = {(1280, 1024): (20, (0, 32)), (1152, 960): (18, (0, 48)), (2560, 2048): (40, (0, 64)), (1600, 1280): (25, (0, 40)),
          (1024, 1024): (16, None), (1080, 1350): (16, None), (768, 1024): (12, None)}


def _hof_elements(num, lx, ly):
    """(name, (l, t, r, b)) of every armed element: the art, the content rect, the 6 rects, the 13 icon buttons, CLOSE."""
    els = [("art", (lx, ly, lx + SL.mon_s(1024, num), ly + SL.mon_s(768, num))),
           ("content", SL.hof_content_rect(num, lx, ly))]
    els += [(f"rect{k}", r) for k, r in enumerate(SL.hof_rects(num, lx, ly))]
    els += [(f"button{k}", (x, y, x + w, y + h))
            for k, (x, y, w, h) in enumerate(SL.hof_button_rects(num, lx, ly) + (SL.hof_close_rect(num, lx, ly),))]
    return els


_BBOX: dict = {}


def _hof_bbox(num):
    """Union of every element relative to the letterbox origin (each law is letterbox + f(num), so one num -> one box)."""
    if num not in _BBOX:
        els = _hof_elements(num, 0, 0)
        _BBOX[num] = (min(r[0] for _n, r in els), min(r[1] for _n, r in els), max(r[2] for _n, r in els), max(r[3] for _n, r in els))
    return _BBOX[num]


def _hof_inside(sw, sh, full=False):
    """[] or the reasons the Hall of Fame's armed layout leaves the screen at sw x sh: the art, the content rect, the
    6 rects, the 13 icon buttons and CLOSE.  full=False tests their union (exact: every element is letterbox + f(num))."""
    if not SL.hof_armed(sw, sh, 1):
        return []
    num = SL.hof_scale_num(sw, sh)
    lx, ly = SL.hof_letterbox(sw, sh, num)
    if full:
        els = _hof_elements(num, lx, ly)
    else:
        l, t, r, b = _hof_bbox(num)
        els = [("union", (lx + l, ly + t, lx + r, ly + b))]
    return [(n, r) for n, r in els if r[0] < 0 or r[1] < 0 or r[2] > sw or r[3] > sh]


@pytest.mark.parametrize("sw,sh", sorted(NARROW))
def test_narrow_screen_takes_the_width_term_and_keeps_the_art_on_screen(sw, sh):
    num, box = NARROW[(sw, sh)]
    assert SL.hof_scale_num(sw, sh) == num
    assert SL.hof_armed(sw, sh, 1) == (box is not None)
    if box is None:
        return
    assert SL.hof_letterbox(sw, sh, num) == box
    assert _hof_inside(sw, sh, full=True) == [] and _hof_inside(sw, sh) == []
    for _n, (l, t, r, b) in _hof_elements(num, *box)[1:]:                # every element inside the art
        assert box[0] <= l and box[1] <= t and r <= box[0] + SL.mon_s(1024, num) and b <= box[1] + SL.mon_s(768, num)
    x, y, w, h = SL.hof_close_rect(num, *box)
    assert x + w <= sw and y + h <= sh


H_BANDS = [(h0, min(h0 + 240, 4321)) for h0 in range(480, 4321, 240)]


@pytest.mark.parametrize("h0,h1", H_BANDS)
def test_sweep_art_and_buttons_inside_the_screen(h0, h1):
    """The 'art inside the screen' invariant (art, rects, 13 icon buttons, CLOSE) over every height and a width grid
    (every 2nd width + the 4:3 boundary +-3 + each width-term num step +-1)."""
    bad = []
    for sh in range(h0, h1):
        ws = set(range(640, 7681, 2))
        q = (sh * 1024 + 767) // 768
        ws |= {q + d for d in range(-3, 4)}
        ws |= {64 * k + d for k in range(10, 121) for d in (-1, 0, 1)}
        for sw in ws:
            if sw < 640:
                continue
            for why in _hof_inside(sw, sh):
                bad.append((sw, sh, why))
                if len(bad) > 5:
                    pytest.fail(f"Hall of Fame leaves the screen: {bad}")
    assert not bad
    # the ceiling IS the largest imm8 literal's byte range: half_down(0x1C*num) <= 127 exactly up to 72
    assert SL.mon_s(0x1C, 72) <= 127 < SL.mon_s(0x1C, 73)


def test_identity_at_native():
    n, lx, ly = 16, 0, 0
    assert SL.hof_origin(n, lx, ly) == (119, 80)
    assert SL.hof_content_rect(n, lx, ly) == SL.HOF_CONTENT_NATIVE == (119, 80, 919, 680)
    assert SL.hof_rects(n, lx, ly) == SL.HOF_RECTS_NATIVE
    assert SL.HOF_RECTS_NATIVE == ((149, 350, 410, 407), (422, 349, 660, 467), (671, 349, 881, 623),
                                   (140, 203, 890, 317), (195, 119, 843, 199), (415, 471, 667, 664))   # the 4K census dump
    assert SL.hof_close_rect(n, lx, ly) == (673, 636, 206, 22)                                      # close=(0,0,206,22) at (a24+0x22A, a28+0x22C)
    b = SL.hof_button_rects(n, lx, ly)
    assert b[0] == (209, 119, 79, 79) and b[6] == (158, 225, 70, 70)                                # A14/A18 = 158,225 in the census dump
    assert [r[0] for r in b[:6]] == [209 + 108 * i for i in range(6)]
    assert [r[0] for r in b[6:]] == [158 + 107 * i for i in range(7)]
    assert SL.HOF_MAP_NATIVE == (238, 118)
    for sz in SL.HOF_FONTS:
        assert SL.hof_font_size(sz, 16) == sz and not SL.hof_font_scratch(sz, 16)
    assert SL.hof_face_origin(79, -79, 79, 79, 16) == (0, 0)


@pytest.mark.parametrize("num", NUMS)
def test_geometry_is_proportionate_and_nested(num):
    sw, sh = SL.mon_s(1024, num) + 100, SL.mon_s(768, num)
    lx, ly = SL.hof_letterbox(sw, sh, num)
    assert (lx, ly) == (50, 0)
    L, T, R, B = SL.hof_content_rect(num, lx, ly)
    assert (L, T) == SL.hof_origin(num, lx, ly)
    assert lx <= L < R <= lx + SL.mon_s(1024, num) and ly <= T < B <= ly + SL.mon_s(768, num)
    rects = SL.hof_rects(num, lx, ly)
    for k, r in enumerate(rects):
        nat = SL.HOF_RECTS_NATIVE[k]
        assert L <= r[0] < r[2] <= R and T <= r[1] < r[3] <= B, (k, r)
        for i in range(4):
            org = (lx if i % 2 == 0 else ly)
            base = (119 if i % 2 == 0 else 80)
            assert r[i] == org + SL.mon_s(base, num) + SL.mon_s(nat[i] - base, num)
    # the three panels keep their vanilla order left to right; the picture sits under the map
    assert rects[0][2] < rects[1][0] < rects[1][2] < rects[2][0]
    assert rects[5][1] >= rects[1][3]
    # buttons: inside their row rects, square, non-overlapping, evenly pitched
    btns = SL.hof_button_rects(num, lx, ly)
    for i, (x, y, w, h) in enumerate(btns):
        row = rects[4] if i < 6 else rects[3]
        cell = 0x4F if i < 6 else 0x46
        assert w == h == SL.hof_button_size(cell, num) == (cell * num) // 16
        assert row[0] <= x and x + w <= row[2] and row[1] <= y and y + h <= row[3], (i, (x, y, w, h), row)
    for grp, n, rect_nat, cell in ((btns[:6], 6, SL.HOF_RECTS_NATIVE[4], 0x4F), (btns[6:], 7, SL.HOF_RECTS_NATIVE[3], 0x46)):
        pitch_nat, x0, y0 = SL.hof_button_offsets(n, rect_nat, cell)
        row_dev = SL.hof_rect(rect_nat, num, lx, ly)
        for i, (a, b) in enumerate(zip(grp, grp[1:])):
            assert a[0] + a[2] <= b[0]
            assert abs((b[0] - a[0]) - SL.mon_s(pitch_nat, num)) <= 1          # each position is s(x0 + i*pitch): the pitch rounds by <= 1 px
        # the spare rows stay BELOW the face as in vanilla: top margin = s(y0), never a split of the scaled slack
        assert grp[0][1] == row_dev[1] + SL.mon_s(y0, num)
        assert grp[0][0] == row_dev[0] + SL.mon_s(x0, num)
    # CLOSE inside the content rect, right of the picture box (vanilla: x 673..879 vs the box's 415..667)
    cx, cy, cw, ch = SL.hof_close_rect(num, lx, ly)
    assert L <= cx and cx + cw <= R and cy + ch <= B and cx >= rects[5][2]


@pytest.mark.parametrize("num", NUMS)
def test_fonts_and_row_pitch(num):
    for sz in SL.HOF_FONTS:
        n = SL.hof_font_size(sz, num)
        assert n == (sz * num) // 16
        assert SL.hof_font_scratch(sz, num) == (n > 40)
    assert SL.hof_font_scratch(22, 45) and SL.hof_font_scratch(16, 45) and not SL.hof_font_scratch(14, 45)
    assert not any(SL.hof_font_scratch(sz, 25) for sz in SL.HOF_FONTS)
    assert SL.hof_line_height(3, 40, 30) == 33 and SL.hof_line_height(-1, 40, 30) == 40 and SL.hof_line_height(0, 40, 30) == 30


@pytest.mark.parametrize("num", (22, 25, 45, 72))
def test_face_origin_centres_the_scaled_face(num):
    for cell in (0x4F, 0x46):
        size = SL.hof_button_size(cell, num)
        assert SL.hof_face_origin(size, -size, cell, cell, num) == (0, 0)
        assert SL.hof_face_origin(size + 10, -(size + 10), cell, cell, num) == (5, 5)


def test_map_and_picture_constants_match_the_rects():
    r = SL.HOF_RECTS_NATIVE[1]
    assert (r[2] - r[0], r[3] - r[1]) == SL.HOF_MAP_NATIVE
    r = SL.HOF_RECTS_NATIVE[5]
    assert (r[2] - r[0], r[3] - r[1]) == (252, 193)       # the 233x124 picture sits at +9/+10 inside it


# ---- v7: the CLOSE slot's channel rows (hof.pcx field pair, scaling_laws.HOF_FIELD_PAIR) -----------------------------
def _hof_pcx_slot():
    """hof.pcx's CLOSE slot (outer + inner red frame, the channels, the field under the button) as runtime indices
    (pcx + 10), 64 x 44 from 12 rows/cols above-left of the CLOSE literal; None when the game dir is absent."""
    try:
        import config
        from PIL import Image
        im = Image.open(Path(config.game_dir()) / "hof.pcx")
    except Exception:  # noqa: BLE001
        return None
    x0, y0 = SL.HOF_CLOSE_NATIVE[0] - 12, SL.HOF_CLOSE_NATIVE[1] - 12
    w, h = 64, 44                                   # rows -12..31: below +31 the pcx starts its next feature (index 64)
    return bytes((im.getpixel((x0 + x, y0 + y)) + 10) & 0xFF for y in range(h) for x in range(w)), w, h


def _synthetic_slot():
    """The same slot drawn from hof.pcx's measured column (2026-10-11): the field on the pcx row parity (197 on the
    CLOSE literal's row), the outer red frame 6 rows above it, the inner one 3 above, mirrored 24/27 rows below."""
    f0, f1 = SL.HOF_FIELD_PAIR
    w, h = 64, 48
    src = bytearray((f0 if y % 2 else f1) for y in range(h) for _x in range(w))
    for y in (12 - 6, 12 - 3, 12 + 24, 12 + 27):
        for x in range(6, w):
            src[y * w + x] = 109
    return bytes(src), w, h


def _off_grid_field_pixels(src, w, h, num, field, y_abs0):
    """Device field-pair pixels of the slot interior (source cols 14..60) NOT on the dest-grid member of their row
    (the brighter member on stripe_top rows of the dest buffer, the other on the rest)."""
    pal = bytearray(1024)
    for i, rgb in ((65, (0, 0, 0)), (197, (24, 18, 11)), (109, (12, 12, 136))):
        pal[i * 4:i * 4 + 4] = bytes(rgb) + b"\0"
    dw, dh = (w * num) // 16, (h * num) // 16
    dst = bytearray(dw * dh)
    SL.hof_pair_enlarge(src, w, 0, 0, w, h, bytes(pal), num, dst, dw, dw, dh, 0, 0, y_abs0, SL.HOF_BLIT_KEY, field)
    top = SL.hof_pair_top(*SL.HOF_FIELD_PAIR, bytes(pal))
    bot = sum(SL.HOF_FIELD_PAIR) - top
    bad = 0
    for y in range(dh):
        want = top if SL.stripe_top(y_abs0 + y, num) else bot
        for x in range((14 * num) // 16, (60 * num) // 16):
            v = dst[y * dw + x]
            if v in SL.HOF_FIELD_PAIR and v != want:
                bad += 1
    return bad


@pytest.mark.parametrize("num", range(17, 73))
def test_close_slot_channels_are_dest_grid_stripes(num):
    """Every field pixel around the CLOSE button -- both channels of the two-frame slot, top and bottom -- sits on the
    one dest-grid stripe (T = stripe_rows(num) rows per member), at every grid phase; the strokes only occlude it."""
    slots = [_synthetic_slot()]
    real = _hof_pcx_slot()
    if real is not None:
        slots.append(real)
    for src, w, h in slots:
        for y_abs0 in range(SL.stripe_period(num)):
            assert _off_grid_field_pixels(src, w, h, num, SL.HOF_FIELD_PAIR, y_abs0) == 0, (num, y_abs0)


def test_close_slot_channels_were_off_grid_without_the_field_rule():
    """The measured defect (live 1600x900 / 1920x1080 / 1600x1200 / 4K shots, 2026-10-04/05): without the field clause
    the 2-row channels between the slot's frames fell to plain NN -> off-grid field runs."""
    src, w, h = _synthetic_slot()
    for num in (18, 22, 25, 45):
        assert sum(_off_grid_field_pixels(src, w, h, num, None, p) for p in range(SL.stripe_period(num))) > 0, num
