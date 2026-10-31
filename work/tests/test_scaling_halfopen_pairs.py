"""Three mirrored pairs 1 px uneven (2026-10-25 wave-2 W2A): F30 the HQ report DATALINKS / CLOSE row, F31 the Council
VOTE box, F38 the production picker's button-box frame (and the Design Workshop union frame, the same construct).

Laws (scaling_laws.py, the source of truth):
  rw_btn_pair                 -- ONE width (R - L - s(2)) >> 1 for DATALINKS and CLOSE, outer edges on the row, the odd
                                 px in the seam (4K: 616 | 616 and ring channels 5 | 5; were 616 | 615 and 5 | 6);
  council_console_frame_rect  -- the three console-canvas frames around the VOTE row drawn half-open (R-1 / B-1 into
                                 the band map), council_vote_channels the drawn result: L = R = B = s(3) - K, T = s(3),
                                 vanilla x g/16 each (vanilla 2 / 2 / 2 and 3, measured on the pristine image);
  union_frame_draw_rect       -- the two union frames (button row / UnionRect outset 3) drawn half-open the same way,
                                 union_frame_channels: d - K on all four sides (1600x900: 2 | 2; were 2 | 3).
Ports: t_rw_btnw + t_rw_gap1 / t_rw_gap2 v2 (assemble_rw.py), the three council sites -> t_rw_rowframe
(assemble_council.py), t_bm_ho_pp / t_bm_ho_hf (assemble_halfopen_frames.py).

Proof layers, all on the REAL bytes of the shared bake (conftest `baked_exe`):
  1. law sweeps (g 16..64), incl. the mutants the laws replace (bake v4's s(2) split, the untrimmed footprint);
  2. END TO END (halfopen_frames_emu.py on image_emu.py): the engine's own slices, the cave thunks and the real
     band-map renderers draw on a real Buffer; the channels read off the pixels == the laws at every g 16..40;
     g = 16 draws exactly the pristine image's pixels; the bake with the W2A edits reverted in memory reproduces the
     user's shots (4K council 5 | 6 and 6 / 6; 1920x1080 3 | 4 and 3 / 4; 1600x900 picker 2 | 3 both ways; 4K report
     row 616 | 615, ring 5 | 6).  (Unit parity of the thunks: test_halfopen_frames_asm_parity.py, test_rw_asm_parity.py.)

COST: one boot per image per worker (~3 s); each g item re-runs the four draws on that boot (~1 s).  The e2e items
are per g so the module splits across xdist by measured cost.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")

import scaling_laws as SL  # noqa: E402

ALL_G = range(16, 41)
s = SL.scale_px
CLIPS = {"odd": (114, 1450, 1725, 1600), "even": (114, 1450, 1724, 1600)}   # ReportWin clip L/T/R/B, both parities
CLIP_NATIVE = (26, 1450, 670, 1600)                                         # vanilla's own (26 + 670 even)
DW_UNION = (570, 603, 1027, 625)


# ============================================================================== 1. law
def _v4_split(row_l, row_r, g):
    """bake v4 (the mutant): split at mid = (L + R) >> 1, DATALINKS [L, mid - a), CLOSE [mid + b, 2 mid - L)."""
    mid = (row_l + row_r) >> 1
    gap = s(2, g)
    a = gap >> 1
    return (row_l, mid - a), (mid + gap - a, 2 * mid - row_l)


@pytest.mark.parametrize("g", range(16, 65))
@pytest.mark.parametrize("width", (1236, 1237, 494, 495))
def test_law_rw_btn_pair(g, width):
    row_l = 1301
    row_r = row_l + width
    a, b = SL.rw_btn_pair(row_l, row_r, g)
    if g <= 16:
        mid = (row_l + row_r) >> 1
        assert (a, b) == ((row_l, mid - 1), (mid + 1, 2 * mid - row_l)), "vanilla's split"
        return
    assert a[0] == row_l and b[1] == row_r, "outer edges on the row (the ring channels stay s(3) - K)"
    assert a[1] - a[0] == b[1] - b[0], "one width"
    assert b[0] - a[1] in (s(2, g), s(2, g) + 1), "the odd px in the seam"
    v4 = _v4_split(row_l, row_r, g)
    if width % 2:
        assert v4[1][1] == row_r - 1, "the mutant: an odd row leaves CLOSE one px short of the ring side"
    else:
        assert v4[1][1] == row_r


def test_law_rw_4k_shot():
    """The user's 4K shot 20261025-000504: row [1301, 2538), DATALINKS [1301, 1917), CLOSE [1922, 2537) under v4."""
    assert _v4_split(1301, 2538, 40) == ((1301, 1917), (1922, 2537))
    assert SL.rw_btn_pair(1301, 2538, 40) == ((1301, 1917), (1922, 2538))


@pytest.mark.parametrize("g", range(16, 65))
def test_law_council_vote_channels(g):
    ch = SL.council_vote_channels((1295, 1683, 2547, 1948), g)
    K = SL.stroke_width(g) if g > 16 else 1
    s3 = SL.dp(3, g)
    assert ch["L"] == ch["R"] == ch["B"] == s3 - K
    assert ch["T"] == s3
    if g == 16:
        assert ch == {"L": 2, "R": 2, "B": 2, "T": 3}, "vanilla (pristine image, measured below)"


@pytest.mark.parametrize("g", range(16, 65))
def test_law_union_frame_channels(g):
    d = SL.basewin_pt(3, g)
    ch = SL.union_frame_channels(DW_UNION, d, g)
    K = SL.stroke_width(g) if g > 16 else 1
    assert ch == {"L": d - K, "T": d - K, "R": d - K, "B": d - K}
    if g > 16:   # the mutant (the untrimmed rect band-mapped inclusive): far strokes end on r + d, one px wider
        r = DW_UNION[2]
        assert ((r + d) - K + 1) - r == ch["R"] + 1


# ============================================================================== 2. end to end
@pytest.fixture(scope="module")
def sym():
    import halfopen_frames_emu as HF
    return HF.symtab()


@pytest.fixture(scope="module")
def images(tmp_path_factory, bak_path, sym, baked_exe):
    """{'new': the shared bake, 'before': the bake with the W2A edits reverted in memory (the gap caves' bake-v4 bytes,
    the three council sites back on Buffer_box_sprite, the picker / DW union sites back on their renderers),
    'pristine': the .bak}."""
    import shutil
    d = tmp_path_factory.mktemp("halfopen_pairs")
    data = bytearray(Path(baked_exe).read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)

    def off(va):
        return pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)

    def call(va, target):
        assert data[off(va)] == 0xE8
        data[off(va) + 1:off(va) + 5] = struct.pack("<i", target - (va + 5))
    g = struct.pack("<I", 0x668740).hex(" ").upper()
    v4 = {"t_rw_gap1": f"29 D0 89 96 C8 E1 01 00 51 B9 02 00 00 00 0F AF 0D {g} 8D 0C 4D 0F 00 00 00 C1 F9 05 D1 E9 29 C8 59 E9",
          "t_rw_gap2": f"29 D0 51 52 B9 02 00 00 00 0F AF 0D {g} 8D 0C 4D 0F 00 00 00 C1 F9 05 89 CA D1 EA 29 D1 29 C8 01 CF 5A 59 89 8E CC E1 01 00 E9"}
    back = {"t_rw_gap1": 0x4A4421, "t_rw_gap2": 0x4A44DE}
    for name, hexs in v4.items():
        va = sym[name]
        b = bytes.fromhex(hexs.replace(" ", ""))
        b += struct.pack("<i", back[name] - (va + len(b) + 4))
        data[off(va):off(va) + len(b)] = b
    for va in SL.COUNCIL_CONSOLE_FRAME_SITES:
        call(va, 0x5E2DD3)
    for va, renderer in SL.HALFOPEN_UNION_FRAME_SITES.items():
        call(va, sym[renderer])
    (d / "before.exe").write_bytes(bytes(data))
    shutil.copy2(bak_path, d / "pristine.exe")
    return {"new": str(baked_exe), "before": str(d / "before.exe"), "pristine": str(d / "pristine.exe")}


@pytest.fixture(scope="module")
def rig_new(images, sym):
    import halfopen_frames_emu as HF
    return HF.Rig(images["new"], sym)


@pytest.fixture(scope="module")
def rig_before(images, sym):
    import halfopen_frames_emu as HF
    return HF.Rig(images["before"], sym)


@pytest.fixture(scope="module")
def rig_pristine(images, sym):
    import halfopen_frames_emu as HF
    return HF.Rig(images["pristine"], sym)


def _council_con(g):
    import halfopen_frames_emu as HF
    return HF.COUNCIL_CON_4K if g > 16 else HF.COUNCIL_CON_NATIVE


@pytest.mark.parametrize("g", ALL_G)
def test_e2e_all_three_pairs_equal_at_every_g(rig_new, g):
    import halfopen_frames_emu as HF
    K = SL.stroke_width(g) if g > 16 else 1
    # F31 council VOTE box
    c = rig_new.council(g, _council_con(g))
    row = SL.council_button_row(_council_con(g), g)
    assert c["vote"] == row["full"], "the engine's exec block == council_button_row"
    ch = HF.channels(c["p"], c["vote"])
    law = SL.council_vote_channels(_council_con(g), g)
    assert {k: ch[k] for k in "LRTB"} == law, (g, ch, law)
    assert ch["L"] == ch["R"], "the mirrored pair"
    assert ch["kL"] == ch["kR"] == ch["kB"] == K, "the box strokes K wide"
    # F38 production picker button box
    union, p = rig_new.prodpicker(g)
    ch = HF.channels(p, union)
    want = SL.union_frame_channels(union, SL.basewin_pt(3, g), g)
    assert {k: ch[k] for k in "LRTB"} == want and ch["L"] == ch["R"] and ch["T"] == ch["B"], (g, ch)
    assert ch["kL"] == ch["kR"] == ch["kT"] == ch["kB"] == K
    # the Design Workshop union frame (the same construct)
    ch = HF.channels(rig_new.dw_union(g, DW_UNION), DW_UNION)
    d = SL.half_down(3 * g, 16) if g > 16 else 3
    assert {k: ch[k] for k in "LRTB"} == SL.union_frame_channels(DW_UNION, d, g), (g, ch)
    assert ch["kL"] == ch["kR"] == ch["kT"] == ch["kB"] == K
    # F30 report row, both clip parities
    for name, clip in CLIPS.items():
        if g == 16 and name == "odd":
            continue                                          # vanilla's clip is even (26 + 670)
        res = rig_new.report_row(g, clip if g > 16 else CLIP_NATIVE)
        rc = HF.report_channels(res)
        (a, b) = SL.rw_btn_pair(res["row"][0], res["row"][2], g)
        assert res["btns"] == [a, b], (g, name, res["btns"], a, b)
        assert rc["wl"] == rc["wr"] and rc["L"] == rc["R"], (g, name, rc)
        if g > 16:
            assert rc["L"] == s(3, g) - K and rc["seam"] in (s(2, g), s(2, g) + 1), (g, name, rc)
            assert res["btns"][0][0] == res["row"][0] and res["btns"][1][1] == res["row"][2], "on the row's edges"


def test_e2e_g16_is_pristine(rig_new, rig_pristine):
    for rig_a, rig_b in ((rig_new, rig_pristine),):
        a, b = rig_a.council(16, _council_con(16)), rig_b.council(16, _council_con(16))
        assert a["vote"] == b["vote"] and a["text"] == b["text"] and np.array_equal(a["p"], b["p"])
        ua, pa = rig_a.prodpicker(16)
        ub, pb = rig_b.prodpicker(16)
        assert ua == ub and np.array_equal(pa, pb)
        assert np.array_equal(rig_a.dw_union(16, DW_UNION), rig_b.dw_union(16, DW_UNION))
        for clip in (CLIP_NATIVE, CLIPS["odd"]):
            ra, rb = rig_a.report_row(16, clip), rig_b.report_row(16, clip)
            assert ra["btns"] == rb["btns"] and ra["row"] == rb["row"] and np.array_equal(ra["p"], rb["p"])


def test_e2e_pristine_vanilla_channels(rig_pristine):
    """Vanilla, measured: council L / R / B = 2, T = 3 (not a mirrored pair: the body box is half-open on text_bottom);
    picker button box 2 on all four sides; report row 2 | 2 with the vanilla clip."""
    import halfopen_frames_emu as HF
    c = rig_pristine.council(16, _council_con(16))
    assert {k: v for k, v in HF.channels(c["p"], c["vote"]).items() if k in "LRTB"} == {"L": 2, "R": 2, "T": 3, "B": 2}
    union, p = rig_pristine.prodpicker(16)
    assert {k: v for k, v in HF.channels(p, union).items() if k in "LRTB"} == {"L": 2, "R": 2, "T": 2, "B": 2}
    rc = HF.report_channels(rig_pristine.report_row(16, CLIP_NATIVE))
    assert (rc["L"], rc["R"], rc["seam"], rc["wl"] == rc["wr"]) == (2, 2, 2, True)


@pytest.mark.parametrize("g", (18, 22, 30, 40))
def test_e2e_reverted_bake_reproduces_the_shots(rig_before, g):
    import halfopen_frames_emu as HF
    c = rig_before.council(g, _council_con(g))
    ch = HF.channels(c["p"], c["vote"])
    assert ch["R"] == ch["L"] + 1, "council: the right channel one px wider (inclusive footprint)"
    if g == 40:
        assert c["vote"] == (1312, 1881, 2530, 1931) and c["text"] == (1305, 1693, 2537, 1874), "the 4K shot 233251"
        assert {k: ch[k] for k in "LRTB"} == {"L": 5, "R": 6, "T": 6, "B": 6}, "measure25: 5 | 6, 6 / 6"
    if g == 22:
        assert (ch["T"], ch["B"]) == (3, 4) and (ch["L"], ch["R"]) == (3, 4), "the 1080 shot 233652"
    if g == 30:
        assert (ch["L"], ch["R"]) == (3, 4), "the 1440 shot 125645"
    union, p = rig_before.prodpicker(g)
    ch = HF.channels(p, union)
    assert ch["R"] == ch["L"] + 1 and ch["B"] == ch["T"] + 1, "picker: 2 | 3 both ways at 1600x900"
    if g == 18:
        assert (ch["L"], ch["R"], ch["T"], ch["B"]) == (2, 3, 2, 3)
    if g == 40:
        res = rig_before.report_row(40, CLIPS["odd"])
        rc = HF.report_channels(res)
        assert (rc["wl"], rc["wr"], rc["seam"], rc["L"], rc["R"]) == (616, 615, 5, 5, 6), "the 4K shot 000504"
