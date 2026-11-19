"""End to end: the retirement Holobook built and painted by the REAL engine code on the baked image (holobook_emu.py,
image_emu under Unicorn), against the pristine image at 1024x768.

What only a whole-flow run proves: t_hb_build + Holobook_draw run without a fault on the list page and on book
page 8 (artbox + the wrapped caption), the letterbox is black, and every text line the engine writes -- recorded
at the line writers with the host GDI measuring the game's own arialn.ttf -- keeps VANILLA'S line breaks (title,
intro, book list) at the laws' device positions (title / intro rects, the fonts' own line pitch, the rating line,
the page-8 caption rect).  The emulator does not rasterise text, so lines are checked at the writers, not in pixels.

Cost: ~25 s serial (two boots, four paints; the 1920x1080 paint is dominated by the frame's Lanczos resample under
emulation).  It is the only check that the builder and the painter agree inside the real engine; the module splits
into its two Book fixtures across xdist workers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("unicorn")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402
import holobook_emu as HE  # noqa: E402

W, H = 1920, 1080
NUM = SL.hb_scale_num(W, H)
LX, LY = SL.hb_letterbox(W, H, NUM)


def _text(lines, writer="cent"):
    return [(t, x, y, w) for kind, t, x, y, w in lines if kind == writer]


@pytest.fixture(scope="module")
def pristine(bak_path):
    b = HE.Book(str(bak_path), 1024, 768)
    assert not b.patched
    b.open(-1, 2)
    lst = list(b.lines)
    b.open(8, 8)
    return lst, list(b.lines)


@pytest.fixture(scope="module")
def baked(baked_exe):
    b = HE.Book(str(baked_exe), W, H)
    assert b.patched
    canvas = b.open(-1, 2)
    lst = list(b.lines)
    canvas8 = b.open(8, 8)
    p8 = list(b.lines)
    canvas1 = b.open(1, 2)
    return lst, p8, canvas, canvas8, b, list(b.lines), canvas1


def _body(lines):
    """The painter's own text after the buttons' label draws: (text, x, y, w) from the title on."""
    cent = _text(lines)
    k = next(i for i, c in enumerate(cent) if c[0].startswith("Welcome"))
    return cent[k:]


def test_pristine_reference_is_vanilla(pristine):
    lst, _p8 = pristine
    body = _body(lst)
    assert [t for t, *_ in body[:6]] == ["Welcome to the ", "Planetary Archives", "Following your retirement, the ",
                                         "people collect your most ", "memorable writings into a ", "holobook of wisdom entitled:"]
    assert [(x, y, w) for _t, x, y, w in body[:2]] == [(161, 114, 236), (161, 143, 236)]    # title pitch 29 (AN 24 bold)
    assert [y for _t, _x, y, _w in body[2:6]] == [398, 420, 442, 464]                       # intro pitch 22 (AN 18 b+i)


def test_vanilla_breaks_survive_at_scale(pristine, baked):
    van, *_ = pristine
    lst, *_ = baked
    assert [t for t, *_ in _body(lst)] == [t for t, *_ in _body(van)]
    raw = lambda ls: [t for k, t, *_ in ls if k == "raw" and not t.strip() in ("CLOSE", "BACK")]
    assert raw(lst) == raw(van)                                       # the book list + rating lines, same strings


def test_text_lands_at_the_laws_positions(baked):
    lst, *_ = baked
    body = _body(lst)
    title, intro = SL.hb_rects(NUM, LX, LY)[3], SL.hb_rects(NUM, LX, LY)[4]
    _f, size24, _s = SL.hb_font(0x8A40E4, NUM)
    assert [(x, w) for _t, x, _y, w in body[:2]] == [(title[0], title[2] - title[0])] * 2
    assert body[0][2] == title[1]
    pitch_t = body[1][2] - body[0][2]
    assert [(x, w) for _t, x, _y, w in body[2:6]] == [(intro[0], intro[2] - intro[0])] * 4
    assert body[2][2] == intro[1]
    pitch_i = {body[k + 1][2] - body[k][2] for k in range(2, 5)}
    assert len(pitch_i) == 1
    # line pitch = the scaled fonts' own metric (user decision: no override), within 2 px of vanilla x num/16
    assert abs(pitch_t - 29 * NUM / 16) <= 2 and abs(pitch_i.pop() - 22 * NUM / 16) <= 2
    rating = SL.hb_rects(NUM, LX, LY)[5]
    rat = [(x, y) for k, t, x, y, _w in lst if k == "raw" and t.startswith("Alpha Centauri Rating")]
    assert rat and rat[0][0] == rating[0]
    # the book list: entries stack upward from the list rect's bottom, one s(6) gap each
    lb = SL.hb_rects(NUM, LX, LY)[0]
    ys = [y for k, t, x, y, _w in lst if k == "raw" and x == lb[0]]
    assert len(ys) == 3 and ys == sorted(ys, reverse=True)
    step = ys[0] - ys[1]
    assert step == ys[1] - ys[2] and abs(step - 21 * NUM / 16) <= 3


def test_letterbox_black_and_page8_caption(baked):
    _lst, p8, canvas, canvas8, _b, _p1, _c1 = baked
    for c in (canvas, canvas8):
        assert c.shape == (H, W)
        assert not c[:, :LX].any() and not c[:, LX + SL.mon_s(1024, NUM):].any()
        assert not c[:LY].any() and not c[LY + SL.mon_s(768, NUM):].any()
        assert c[LY:LY + SL.mon_s(768, NUM), LX:LX + SL.mon_s(1024, NUM)].any()
    cap = SL.hb_caption_rect(8, NUM, LX, LY)
    lines = [(x, y, w) for _t, x, y, w in _text(p8) if (x, w) == (cap[0], cap[2] - cap[0])]
    assert lines and lines[0][1] == cap[1]


def test_page1_artbox_and_caption(pristine, baked):
    """Book page 1: the artbox is drawn into the art rect (the key texels keep the panel), its caption goes to the
    writer at hb_caption_rect(1), and the page's left column keeps vanilla's lines."""
    _lst, _p8, canvas, _c8, _b, p1, canvas1 = baked
    art = SL.hb_rects(NUM, LX, LY)[1]
    l, t, r, b = art
    changed = (canvas1[t:b, l:r] != canvas[t:b, l:r]).mean()
    assert 0.05 < changed < 0.95                                    # drawn, and keyed (not a filled rect)
    rects = [x for kind, _t, x, _y, _w in p1 if kind == "rect"]
    assert SL.hb_caption_rect(1, NUM, LX, LY) in rects
