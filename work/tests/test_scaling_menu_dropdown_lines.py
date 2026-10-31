"""The in-game MENU dropdown's side lines are a mirrored pair on the stroke law, end to end on the real image (W9C F55,
2026-10-27).

Law (scaling_laws.py, the source of truth): menu_strip_zones / menu_strip_col_map -- every MENU strip (title and rows)
is W = (139 g + 8) >> 4 wide on ONE column map: the two 0x0E2243 side lines K = stroke_width(g) wide, the fill i
outside each (the right one measured to the brown edge column, b = K wide at [W - b, W)), mirrored; ported by
t_mc_synth / t_mc_dims / t_mc_col (assemble_menu_strip.py; asm parity in test_menu_strip_asm_parity.py).

Vanilla (pristine image at 1024x768, this harness): fill 4 | line 1 | 128 | line 1 | fill 4 | brown 1, the title's
line pixel on its last row at the rows' line column.  The defect (user shot 20261027-133512, reproduced exactly by
menu_dropdown_emu on the bb211440 bake): hm_synth_core's floor NN at (sc(18), 18) drew the lines 1 | 2 px at 1080
(x 6 | 185, fill 6 | 4), 3 | 2 at 4K, the rows 1-2 px narrower than the window at g 17 / 18 / 25 (a key-9 sliver)
or wider at g 20 / 22 / 30 (the brown edge clipped), and the title's line pixel 1 px off the rows' at g 20.

END TO END (menu_dropdown_emu.py): load_menu (the game's menu2.pcx), MenuWidget_layout_show, the painter -- every strip
through Sprite_draw_2 -> thunk_hudmenu_sd2 -> t_mc_synth -> hm_synth_core.  At g 17 / 22 / 25 / 40 every row-strip
row of the canvas shows the same columns: both lines K wide at the law's columns, fill L == fill R == i, the brown edge
K wide at the right end, no key column; the title's last row (where shown) carries its line pixel at the rows' left
line.  At g = 16 the canvas equals the pristine .bak's byte for byte.

COST: ~10 s per item (boot + menu2.pcx + the paint); the g = 16 item renders twice.  Independent items, one shared bake.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402
import menu_dropdown_emu as M  # noqa: E402


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_menu_side_lines_are_a_mirrored_stroke_pair(baked_exe, g):
    r = M.render(str(baked_exe), *M.RES[g])
    assert r["g"] == g
    w, i, k, m, b = SL.menu_strip_zones(g)
    c = r["canvas"]
    assert c.shape[1] == w
    want = (((i, k), (w - b - i - k, k)), ((w - b, b),), ())
    sigs = M.row_signatures(r)
    assert sigs == {want}, (g, sigs, want)
    title = M.runs(c[r["top"] - 1], M.LINE)
    assert title in ([], [(i, k)]), (g, title)                        # the native last row may fall between dest rows


def test_menu_native_is_pristine(baked_exe, bak_path):
    a = M.render(str(baked_exe), 1024, 768)
    b = M.render(str(bak_path), 1024, 768)
    assert a["canvas"].shape == b["canvas"].shape and (a["canvas"] == b["canvas"]).all()
    assert M.row_signatures(b) == {(((4, 1), (133, 1)), ((138, 1),), ())}       # the vanilla relation, measured
