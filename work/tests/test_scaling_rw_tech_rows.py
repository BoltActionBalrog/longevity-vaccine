"""HQ report F2 tech page: the leads-to row slots (2026-10-25 F44, law scaling_laws.rw_tech_row_slots).

ReportWin_tech_page lays its side buttons out around y_mid in two layouts: odd (RW+0x595C / 0x5958 / 0x5960, 1 or 3
rows) and even (RW+0x5964..0x5970, 2 or 4 rows), all btn_h + 16 apart.  The page branches on iface mode 8 for the odd
pair, so the gap lives in TWO pairs of immediates: the Datalinks pair 0x4995CC / 0x4995CF (scaled since the DL bake)
and the F2 pair 0x49957F / 0x499582, which no table carried -- F2's 3-row column sat 16 px apart while its 2- and
4-row columns took s(16) (4K 16 vs 40).

1. the law (pure);
2. the tables: both tech tables carry the F2 pair with its Datalinks twin's law; the row block 0x499521..0x499693 has
   no coordinate immediate left outside them (a census of its operands -- what missed the pair);
3. the layout: the grown tables fit their slots, the cells after them keep their literal VAs;
4. end to end on the REAL images (rw_techrows_emu: the engine's own call at 0x496EEF / 0x42C1F2 through
   t_rw_techpage / t_dl_techwrap into the page) at every g 16..40: slots == the law, gap above == below == s(16) ==
   the even gaps, the table applied at the page's ENTRY and reverted after; g = 16 byte- and slot-identical to the
   pristine image; the Datalinks page unchanged; and DatalinkWin_open's return walk leaves every report tech row native.
"""
from __future__ import annotations

import contextlib
import io
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn")
capstone = pytest.importorskip("capstone")
pefile = pytest.importorskip("pefile")

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_rw as AR  # noqa: E402
AD = AR.AD
s = SL.scale_px
GS = tuple(range(16, 41))
F2_PAIR = (0x49957F, 0x499582)
DL_PAIR = (0x4995CC, 0x4995CF)
ROW_BLOCK = (0x499521, 0x499693)


def vanilla_slots(y_mid, btn_h, gap):
    """Direct port of the pristine instructions 0x499572..0x49968D (cdq / sub / sar = trunc toward zero)."""
    def trunc2(v):
        return int(v / 2)
    above, below = y_mid - btn_h - gap, btn_h + y_mid + gap          # sub ecx,edi / sub ecx,0x10 ; lea edx,[edi+eax+0x10]
    p = btn_h + gap                                                  # mov eax,[+0x59A4] / add eax,0x10
    even = [(i - 1) * p - trunc2(p) + y_mid for i in range(3)]       # imul ecx,eax ; sar ; sub ; add [+0x5958]
    even.append(2 * p - trunc2(p) + y_mid)                           # lea ecx,[eax+0x10] / add ecx,ecx / sub / add
    return (above, y_mid, below), tuple(even)


# ============================================================================== 1. the law
@pytest.mark.parametrize("g", GS)
def test_scaling_rw_tech_row_slots_law(g):
    for y_mid in (0, 171, 288, 720, 1001):
        for btn_h in (s(0x28, g), s(0x28, g) + 1, 40, 41):
            odd, even = SL.rw_tech_row_slots(y_mid, btn_h, g)
            gap = s(SL.RW_TECH_ROW_GAP, g)
            assert (odd, even) == vanilla_slots(y_mid, btn_h, gap)
            assert odd[1] - (odd[0] + btn_h) == odd[2] - (odd[1] + btn_h) == gap        # above == below (symmetry)
            assert all(even[i + 1] - (even[i] + btn_h) == gap for i in range(3))       # one gap in both layouts
            assert odd[2] - odd[0] == even[2] - even[0] == 2 * (btn_h + gap)
    if g <= 16:
        assert SL.rw_tech_row_slots(288, 40, g) == vanilla_slots(288, 40, 16)            # identity


# ============================================================================== 2. the tables
def _rowmap(rows):
    return {site: (a, b, bits) for site, a, b, bits in rows}


@pytest.mark.parametrize("table", ("rw", "dl"))
def test_tech_tables_carry_the_f2_pair_with_its_twins_law(table):
    rows = _rowmap(AR.tech_rows() if table == "rw" else AD.imm_rows(True))
    for f2, dl in zip(F2_PAIR, DL_PAIR):
        assert f2 in rows and dl in rows, (hex(f2), hex(dl))
        assert rows[f2] == rows[dl] == (SL.RW_TECH_ROW_GAP, 0, AD.KINDBITS["HD"])
        for g in GS:
            assert AD.imm_value(*rows[f2], g) == s(SL.RW_TECH_ROW_GAP, g)
    assert set(_rowmap(AR.tech_rows())) <= set(_rowmap(AD.imm_rows(True)))      # DL's return walk covers every report row
    assert len(AR.tech_rows()) == 162 + len(AD.TECH_EXTRA_IMMS)


def _row_block_operands(img):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    from capstone import x86_const as X
    lo, hi = ROW_BLOCK
    for ins in md.disasm(img[lo - 0x400000:hi - 0x400000], lo):
        for op in ins.operands:
            if op.type == X.X86_OP_IMM:
                yield ins, ins.address + ins.imm_offset, op.imm, None
            elif op.type == X.X86_OP_MEM and op.mem.disp:
                yield ins, ins.address + ins.disp_offset, op.mem.disp, ins.reg_name(op.mem.base) if op.mem.base else None


# operands of the row block that are not coordinates: (instruction VA, reason)
ROW_BLOCK_NON_COORD = {
    0x49956E: "sar 1 (the centring halve)", 0x4995BB: "sar 1", 0x499614: "sar 1", 0x499645: "sar 1", 0x499684: "sar 1",
    0x499591: "cmp [ScreenW], 800 (the DL SW != 800 branch)", 0x4995E1: "cmp eax, 800",
    0x499608: "lea ecx,[edi-1]: the slot index i - 1", 0x499634: "add ecx, 4: the slot pointer stride",
}


def test_row_block_has_no_coordinate_immediate_outside_the_tables(bak_bytes):
    """What missed F44: every immediate / displacement in 0x499521..0x499693 is a walker row of BOTH tech tables, an
    RW field / local offset, or a listed non-coordinate."""
    img = pefile.PE(data=bak_bytes, fast_load=True).get_memory_mapped_image()
    rw, dl = _rowmap(AR.tech_rows()), _rowmap(AD.imm_rows(True))
    seen_rows, missing = set(), []
    for ins, at, v, base in _row_block_operands(img):
        if at in rw:
            assert at in dl, hex(at)
            seen_rows.add(at)
            continue
        if base in ("ebp", "esi") or (base is not None and ins.mnemonic != "lea") or (base is None and v >= 0x400000):
            continue          # a local / an RW field (esi = this); a slot store through a pointer (only a LEA's disp on a
                              # value register is arithmetic); a global
        if ins.address in ROW_BLOCK_NON_COORD:
            continue
        missing.append(f"{ins.address:#x} {ins.mnemonic} {ins.op_str}")
    assert missing == []
    assert set(F2_PAIR) | set(DL_PAIR) | {0x49960D, 0x49967C} <= seen_rows
    for va, want in ((0x49957C, "lea edx, [edi + eax + 0x10]"), (0x499580, "sub ecx, 0x10")):
        ins = next(capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32).disasm(img[va - 0x400000:va - 0x3FFF00], va))
        assert f"{ins.mnemonic} {ins.op_str}" == want


# ============================================================================== 3. the layout
def test_grown_tables_fit_their_slots(patches_path):
    import apply_patches as ap
    with contextlib.redirect_stdout(io.StringIO()):
        AR.assemble_all()                                        # lays out TAB_TECH / CELL (0 until then)
    _s, _g, caves, symbols = ap.load_patches(Path(patches_path))
    S = ap.build_symbol_table(symbols, caves)
    P = AR.PCAVE2
    # report: the tech table took 32 B of g_rw_immtab's zero tail; same end, the cells after it keep their VAs
    assert AR.RW_TAB_LEN + 32 == 6836 and len(AR.RW_TAB) == AR.RW_TAB_LEN
    assert AR.RW_TAB[AR.SUM_TAB_OFF + len(AR.sum_tab_bytes()):] == bytes(AR.RW_TAB_LEN - AR.SUM_TAB_OFF - len(AR.sum_tab_bytes()))
    assert S["g_rw_immtab_tech"] == AR.TAB_TECH == P + 0x26A30
    assert AR.TAB_TECH + len(AR.TECH_TAB) == P + 0x27474 <= S["g_rw_ret"] == P + 0x27480
    assert S["g_rw_immtab"] + AR.RW_TAB_LEN <= S["g_rw_immtab_tech"]
    assert S["g_rw_inlist"] == P + 0x27488 and S["g_rw_sbs"] == P + 0x27564          # literal VAs elsewhere
    # Datalinks: dword-aligned after the main table, ends before t_cmb_init
    assert S["g_dl_immtab_tech"] == AD.TAB_TECH == S["g_dl_immtab_main"] + len(AD.MAIN_TAB) == P + 0x28CD4
    assert AD.TAB_TECH + len(AD.TECH_TAB) <= S["t_cmb_init"] == P + AD.TECH_TAB_LIMIT
    # the yaml carries the assembler's bytes (a stale table would bake the old rows)
    content = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    for cid, tab in (("g_rw_immtab_tech", AR.TECH_TAB), ("g_dl_immtab_tech", AD.TECH_TAB), ("g_rw_immtab", AR.RW_TAB)):
        assert bytes.fromhex(content[cid]["bytes"].replace(" ", "")) == tab, cid


# ============================================================================== 4. end to end, real images
@pytest.fixture(scope="module")
def rig(baked_exe):
    import rw_techrows_emu as RT
    return RT.Rig(str(baked_exe), RT.symtab())


@pytest.fixture(scope="module")
def rig_pristine(bak_path):
    import rw_techrows_emu as RT
    r = RT.Rig(str(bak_path))
    assert not r.patched
    return r


def _gaps(rec):
    sl, h = rec["slots"], rec["btn_h"]
    return (sl["y_mid"] - (sl["above"] + h), sl["below"] - (sl["y_mid"] + h),
            [sl[f"e{i + 1}"] - (sl[f"e{i}"] + h) for i in range(3)])


def _check(rec, g, dl=False):
    sl = rec["slots"]
    odd, even = SL.rw_tech_row_slots(sl["y_mid"], rec["btn_h"], g)
    assert (sl["above"], sl["y_mid"], sl["below"]) == odd
    assert (sl["e0"], sl["e1"], sl["e2"], sl["e3"]) == even
    up, dn, ev = _gaps(rec)
    assert up == dn == s(16, g) and ev == [s(16, g)] * 3
    assert rec["btn_h"] == s(0x28, g)
    # the column the rows centre in: F2 = RW+0xA20; Datalinks with ScreenW != 800 (0x499591; image_emu boots 3840)
    # centres in it minus s(200) and restores it after (0x49959D / 0x4995E8, DL rows)
    col = rec["col_h"] - (s(0xC8, g) if dl else 0)
    assert sl["y_mid"] == int((col - rec["btn_h"]) / 2) + rec["y0"]


@pytest.mark.parametrize("g", GS)
def test_f2_rows_on_the_real_image(rig, g):
    rec = rig.f2(g)
    assert rec.get("entries") == 1 and rec["dl_flag"] == 0
    assert set(rec["entry_imms"].values()) == {s(16, g)}            # the table is applied BEFORE the page runs
    _check(rec, g)
    assert set(rec["after_imms"].values()) == {0x10}                # and reverted after (DL-shared code)


@pytest.fixture(scope="module")
def pristine_img(bak_bytes):
    return pefile.PE(data=bak_bytes, fast_load=True).get_memory_mapped_image()


@pytest.mark.parametrize("g", GS)
def test_datalinks_rows_unchanged_and_closed(rig, pristine_img, g):
    import rw_techrows_emu as RT
    assert (RT.GAP_IMMS["f2_below"], RT.GAP_IMMS["f2_above"]) == F2_PAIR
    rec = rig.dl(g)
    assert rec.get("entries") == 1 and rec["dl_flag"] == 1
    assert rec["entry_imms"]["dl_below"] == rec["entry_imms"]["dl_above"] == s(16, g)
    _check(rec, g, dl=True)
    # DatalinkWin_open's return walk (t_dl_exec_leave: TECH at 16) after a report-table walk at g (t_rw_techhover
    # restores the PRIOR immg, g inside a Datalinks session): every report tech row is native again
    if g > 16:
        rig._walk("g_rw_immtab_tech", g)
    rig._walk("g_dl_immtab_tech", 16)
    for site, _a, _b, bits in AR.tech_rows():
        n = 4 if bits & AD.K_W4 else 1
        assert bytes(rig.e.uc.mem_read(site, n)) == pristine_img[site - 0x400000:site - 0x400000 + n], hex(site)
    assert set(rig.imms().values()) == {0x10}


@pytest.mark.parametrize("path", ("f2", "dl"))
def test_g16_is_pristine(rig, rig_pristine, path):
    a, b = getattr(rig, path)(16), getattr(rig_pristine, path)(16)
    for k in ("slots", "btn_h", "col_h", "y0", "entry_imms", "after_imms"):
        assert a[k] == b[k], k
    assert set(a["entry_imms"].values()) == {0x10}


@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_mutant_without_the_pair_fails(rig, g):
    """Kill check: the bake without the two rows (the g_rw_immtab_tech walker stopped before them = 297f930b's F2
    behaviour) puts the outer rows of the 3-row column 16 px from y_mid while the even layout keeps s(16)."""
    S = rig.sym
    first = S["g_rw_immtab_tech"] + 16 * (len(AR.tech_rows()) - len(AD.TECH_EXTRA_IMMS))
    assert struct.unpack("<I", bytes(rig.e.uc.mem_read(first, 4)))[0] == F2_PAIR[0]
    rig.e.w32(first, 0)                                               # terminator before the pair
    try:
        rec = rig.f2(g)
    finally:
        rig.e.w32(first, F2_PAIR[0])
    up, dn, ev = _gaps(rec)
    assert up == dn == 16 and ev == [s(16, g)] * 3 and s(16, g) != 16
