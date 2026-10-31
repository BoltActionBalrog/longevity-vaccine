"""The rail scrollbar is ONE symmetric assembly, end to end on the real image (W3B, 2026-10-25; the user-approved "rail
scrollbar rework" = fix 20 item D).

Laws (scaling_laws.py, the source of truth): rail_col_map (axis_map_chrome(32, Wc, 4, g, 3, 3): the cyan guide line is
each band's chrome cell, K = stroke_width(g) wide, the three outer cells share the rest, the far band mirrors the near
one; Wc = rail_wall_off), rail_bar_inset / rail_line_spans (the bar is the channel [b, Wc - b) between the lines),
rail_grip_span (the arrow plates and the thumb grip share one span: fl(18g/16), one less when the bar minus it is odd,
centred), rail_layout v4.

The defect (user shots 20261022-204321 / 205616 / 205821, reproduced exactly by this harness on the 0a143acd bake):
4K lines 3 | 2 px, outer offsets 7 | 8, plate 7 | 8 vs grip 8 | 7; 1920x1080 lines 2 | 1, plate 25 wide vs grip 24;
1600x1200 outer offsets 5 | 4.  Four mechanisms rounded on their own: the engine NN run table for the column, the bar
on that table's columns 4 / 28, GDI StretchBlt's centre-NN for the arrow plate, and the grip's own recentre.

END TO END (rail_sym_emu.py on popup_listbox_emu.py on image_emu.py): the GOTO popup with 40 bases (more than fit) on
the bake, so Popup_show runs rail_slide_in -> thunk_rail_bake -> t_rsb_blit, thunk_rail_sbfit, ScrollBar_draw (arrows
through thunk_btn_shrink / thunk_btn_2dscale -> t_btn_edgeprobe -> t_rsb_zoom; the grip through thunk_sb_thumb -> t_rsb_grip) in the
engine's own order, with the game's own rail and scrollbar art loaded by the engine's own loaders.  At g 17 / 18 / 22 /
25 / 40 (1088x816, 1600x900, 1920x1080, 1600x1200, 3840x2160) the DRAWN pixels must show: both lines
K wide and at mirrored offsets; the bar window exactly between them; up plate == down plate == grip == the law span,
equal channels on both sides; the grip centred vertically in its thumb rect; the hovered up arrow's plate on the same
span.  At g = 16 the whole popup composite is byte-identical to the pristine .bak's.  The other rail families (the
ProdPicker, the in-game LOAD/SAVE list, the HQ report) run the same thunks on the same bar class; their geometry and
identities are swept in tests/test_rail_sbstrip_abut_asm.py and tests/test_rail_sym_asm_parity.py.

COST (measured in the full run: ~105 s serial under full-suite load, 6 items of 13..24 s; alone ~60 s): each item
boots the image, loads the interface + rail + scrollbar art and builds and draws the popup (~13 s at g 17..22, ~20 s
at 4K under load); the g = 16 item runs it twice (bake and .bak).  There is no cheaper way to read what the engine
composes, and the defect lived exactly in the composition (the caps' ornament showing through the arrows' key
margins, the plate / grip / line rounding).  Every other g and every canvas width is proved at the unit layer
(test_rail_sym_asm_parity.py, test_scaling_rail_sym_laws.py, test_rail_sbstrip_abut_asm.py; ~20 s together).
2560x1440 (g 30) is left to those: the deployed build was already symmetric there.  Independent items: the module
splits cleanly across xdist (one shared bake), the full run's wall clock does not move.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402
import rail_sym_emu as R  # noqa: E402
import image_emu as E  # noqa: E402

GS = (17, 18, 22, 25, 40)


def _channels(span, outer):
    return span[0] - outer[0], outer[1] - span[1]


@pytest.mark.parametrize("g", GS)
def test_rail_bar_assembly_is_symmetric_on_the_real_image(baked_exe, g):
    run = R.build(str(baked_exe), g)
    m = R.measure(run, g)
    k, wc = SL.stroke_width(g), m["wc"]
    b = SL.rail_bar_inset(m["cw"], g)
    bad = []
    # the two cyan lines: K wide, mirrored about the column, the law's spans
    if m["lines"] != list(SL.rail_line_spans(m["cw"], g)):
        bad.append(("lines", m["lines"], SL.rail_line_spans(m["cw"], g)))
    (l0, l1), (r0, r1) = m["lines"][0], m["lines"][-1]
    if not (l1 - l0 == r1 - r0 == k and l0 == wc - r1):
        bad.append(("line widths / outer offsets", (l0, l1), (r0, r1), wc))
    # the bar window is the channel between them (its hit rect is its window)
    if m["bar"] != (l1, r0) or m["bar"] != (b, wc - b):
        bad.append(("bar", m["bar"], (l1, r0)))
    # plates and grip: one span, the law's, centred
    off, w = SL.rail_grip_span(m["bar"][1] - m["bar"][0], SL.RAIL_GRIP_W, g)
    want = (m["bar"][0] + off, m["bar"][0] + off + w)
    for nm in ("up", "dn", "thumb"):
        if m[nm] != want:
            bad.append((nm, m[nm], want))
        elif _channels(m[nm], m["bar"])[0] != _channels(m[nm], m["bar"])[1]:
            bad.append((nm + " channels", _channels(m[nm], m["bar"])))
    # the grip is square (uniform scale) and centred in its thumb rect vertically too
    tl, tt, tr, tb = m["thumb_rect"]
    rows = m["thumb_rows"]
    if (tl, tr) != m["bar"] or rows[1] - rows[0] != w or rows[0] - tt != tb - rows[1]:
        bad.append(("grip rows", rows, m["thumb_rect"], w))
    # hover: the up arrow's hover state lands its plate on the same span
    e = run.e
    up = run.pop + R.POPUP_SB + R.SB_UP
    e.w32(up + 0xA74, 1)
    e.call(e.r32(e.r32(up) + 0x30), ecx=up, count=50_000_000)
    a = E.canvas_of(e, up)
    sp = R.colspan(a, lambda c: c != R.KEY)
    if (sp[0] + m["bar"][0], sp[1] + m["bar"][0]) != want:
        bad.append(("hover plate", sp, want))
    assert not bad, (g, bad)


def test_rail_bar_native_is_pristine(baked_exe, bak_path):
    """g = 16 (1024x768): every W3B thunk is gated off -- the whole popup composite (rail strip, bar, arrows, grip)
    equals the pristine .bak's, byte for byte."""
    comps = []
    for exe in (baked_exe, bak_path):
        run = R.build(str(exe), 16)
        comps.append(R.composite(run.e, run.pop))
    assert comps[0].shape == comps[1].shape and (comps[0] == comps[1]).all()
