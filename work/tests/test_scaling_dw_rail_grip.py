"""The Design Workshop part picker's rail scrollbar is the SAME symmetric assembly as every other rail-family bar, end
to end on the real image (W9C F53, 2026-10-27).

Law (scaling_laws.py, the source of truth): rail_grip_span -- the arrow plates and the thumb grip share ONE span, the
bar-parity value nearest 18 g/16, centred; scaling_laws.RAIL_FAMILY_VTBL_BARS lists the PartPicker (vtbl 0x66B2B8,
bar +0xA14) as a rail-family member, ported by t_rsb_israil v4 (assemble_rail_sym.py).

The defect (user 4K shot 20261027-133259, reproduced exactly by dw_rail_emu.py on the bb211440 bake): the picker's
rail column and bar were on the law (thunk_dw_pk_enter arms the rail recipe for it) but t_rsb_israil did not admit its
bar, so the arrow plates went through StretchBlt's centre-NN (45 px at 7 | 8 in the 60-px bar) and the grip through
t_sbt_grip (45 px at 8 | 7); the law is 44 at 8 | 8.  The same split showed at g 17 (plate 19 at 3 | 4, grip 19 at
4 | 3; law 20 at 3 | 3), 18 (plate 21 at 3 | 4, grip 20 at 4 | 4), 22 (plate 25 at 4 | 5, grip 24 at 5 | 5) and 25
(plate 27 at 5 | 5, grip 28 at 4 | 5; law 29 at 4 | 4); g 20 and 30 happened to agree.

END TO END (dw_rail_emu.py on image_emu.py): DesignWin_exec up to DesignWin_build, then PartPicker_exec through its
detour to the modal loop -- rail_slide_in, the bar fit, the strip bake, ScrollBar_draw with the arrows through
thunk_btn_2dscale -> t_btn_edgeprobe -> t_rsb_zoom and the grip through thunk_sb_thumb -> t_rsb_grip, in the engine's
order.  At g 17 / 22 / 25 / 40 the DRAWN pixels must show: up plate == down plate == grip == rail_grip_span(bar, 18,
g), equal channels on both sides; the grip square and centred in its thumb rect; the hovered up arrow on the same span.
At g = 16 the picker composite equals the pristine .bak's byte for byte.  Every other g and the admission list itself
are swept at the unit layer (test_rail_sym_asm_parity.py: t_rsb_israil admits the PartPicker bar exactly).

COST: ~11 s per item (boot, the interface / rail / scrollbar art, the DW build, the picker), ~13 s at 4K; the g = 16
item renders the bake, and the .bak only on a cold pytest cache (the .bak composite is cached, keyed on its
bytes and the rig sources).  Five independent items, one shared bake: they split across xdist workers.
"""
from __future__ import annotations

import hashlib
import os
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
import dw_rail_emu as D  # noqa: E402
import rail_sym_emu as R  # noqa: E402
import image_emu as E  # noqa: E402

GS = (17, 22, 25, 40)


def _channels(span, outer):
    return span[0] - outer[0], outer[1] - span[1]


@pytest.mark.parametrize("g", GS)
def test_dw_picker_plates_and_grip_share_the_rail_span(baked_exe, g):
    run = D.Run(str(baked_exe), g)
    assert run.g == g
    m = D.measure(run)
    bad = []
    if m["lines"] != list(SL.rail_line_spans(m["cw"], g)):                  # the column the recipe already laid
        bad.append(("lines", m["lines"], SL.rail_line_spans(m["cw"], g)))
    off, w = SL.rail_grip_span(m["bar"][1] - m["bar"][0], SL.RAIL_GRIP_W, g)
    want = (m["bar"][0] + off, m["bar"][0] + off + w)
    for nm in ("up", "dn", "thumb"):
        if m[nm] != want:
            bad.append((nm, m[nm], want))
        elif _channels(m[nm], m["bar"])[0] != _channels(m[nm], m["bar"])[1]:
            bad.append((nm + " channels", _channels(m[nm], m["bar"])))
    tl, tt, tr, tb = m["thumb_rect"]
    rows = m["thumb_rows"]
    if (tl, tr) != m["bar"] or rows[1] - rows[0] != w or rows[0] - tt != tb - rows[1]:
        bad.append(("grip rows", rows, m["thumb_rect"], w))
    e = run.e
    up = run.sb + R.SB_UP
    e.w32(up + 0xA74, 1)                                                    # hover: the up arrow's lit state
    e.call(e.r32(e.r32(up) + 0x30), ecx=up, count=50_000_000)
    sp = R.colspan(E.canvas_of(e, up), lambda c: c != R.KEY)
    if (sp[0] + m["bar"][0], sp[1] + m["bar"][0]) != want:
        bad.append(("hover plate", sp, want))
    assert not bad, (g, bad)


def _pristine_composite(request, bak_path):
    """The .bak's g = 16 picker composite, cached in pytest's cache dir (keyed on the .bak's bytes and the rig sources
    it runs through), so a warm run renders only the bake."""
    cache = getattr(request.config, "cache", None)                  # absent under -p no:cacheprovider
    if cache is None:
        run = D.Run(str(bak_path), 16)
        return R.composite(run.e, run.pp)
    here = Path(__file__).resolve().parent
    h = hashlib.md5(Path(bak_path).read_bytes())
    for f in ("dw_rail_emu.py", "rail_sym_emu.py", "image_emu.py"):
        h.update((here / f).read_bytes())
    d = Path(cache.mkdir("w9c_dw_rail_pristine"))
    f = d / f"{h.hexdigest()}.npy"
    if f.exists():
        return np.load(f)
    run = D.Run(str(bak_path), 16)
    comp = R.composite(run.e, run.pp)
    tmp = d / f"{h.hexdigest()}.{os.getpid()}.tmp.npy"
    np.save(tmp, comp)
    os.replace(tmp, f)
    return comp


def test_dw_picker_rail_native_is_pristine(request, baked_exe, bak_path):
    """g = 16 (1024x768): the picker composite (rail strip, bar, arrows, grip) equals the pristine .bak's."""
    run = D.Run(str(baked_exe), 16)
    got = R.composite(run.e, run.pp)
    want = _pristine_composite(request, bak_path)
    assert got.shape == want.shape and (got == want).all()
