"""HQ report F2 tech page: the research card's last native coordinate immediates (2026-10-25 F45, law
scaling_laws.rw_tech_card_imms).

ReportWin_tech_page's F2-only branch (iface mode != 8) drew four things with native offsets while everything around
them was device-scaled:
  - the blind-research text box (GameRules 0x200): left inset `lea eax,[edx+3]` 0x498DBF against an s(3) right inset
    (3 vs 7 at 4K) and its text x `add eax,5` 0x498DC5;
  - header line 2's x `add ecx,3` 0x499171 against line 1's s(3) (4 px left of it at 4K);
  - the text-piece gaps `add eax,0xF` 0x498FDD and `add eax,4` 0x49948A;
  - the research brackets' clip-rect outset / inset `mov eax,7` 0x4992C7 / 0x499334 / 0x49938B / 0x4993FB.
Nine HD rows in g_rw_immtab, the once-per-session report table that already carries every F2-branch row (the
Datalinks page never runs this branch, so no Datalinks walk may touch them and none does).

1. the law (pure);
2. the table: the nine rows, their law, their instructions on the pristine image, disjoint from every Datalinks /
   tech table; the card span 0x498C5A..0x499521 has no coordinate immediate left outside the report table (a census:
   what missed these four);
3. end to end on the REAL images (rw_techcard_emu: the report walker, then the engine's own call at 0x496EEF into the
   page, the card run for real) at every g 16..40, blind and not: every relation == the law; g = 16 identical to the
   pristine image; the Datalinks path runs none of the sites and no tech-table walk (open / close / an F2 repaint
   inside a Datalinks session) changes them; a mutant without the rows fails.
"""
from __future__ import annotations

import contextlib
import io
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
CARD = (0x498C5A, 0x499521)          # F2-only: from the card setup to the shared row block
INSN = {                              # imm VA -> the pristine instruction carrying it
    0x498DBF: "lea eax, [edx + 3]", 0x498DC5: "add eax, 5", 0x499171: "add ecx, 3", 0x498FDD: "add eax, 0xf",
    0x49948A: "add eax, 4", 0x4992C7: "mov eax, 7", 0x499334: "mov eax, 7", 0x49938B: "mov eax, 7",
    0x4993FB: "mov eax, 7",
}


# ============================================================================== 1. the law
@pytest.mark.parametrize("g", GS)
def test_scaling_rw_tech_card_law(g):
    imms = SL.rw_tech_card_imms(g)
    assert imms == {va: s(v, g) for va, v in SL.RW_TECH_CARD_IMMS.items()}
    assert len({imms[va] for va in (0x4992C7, 0x499334, 0x49938B, 0x4993FB)}) == 1      # outset == inset: round trip
    for band_l, band_r in ((0, 640), (87, 931), (217, 2327)):
        box_l, box_r, tx = SL.rw_tech_blind_header(band_l, band_r, g)
        assert box_l - band_l == band_r - box_r == s(3, g)                              # symmetric insets
        assert tx - box_l == s(5, g)
        assert SL.rw_tech_line_x(box_l, g) == box_l + s(3, g)
    assert SL.rw_tech_text_gap(100, 0xF, g) - 100 == s(15, g)
    assert SL.rw_tech_text_gap(100, 4, g) - 100 == s(4, g)
    clip = (810, 122, 1096, 175)
    out = SL.rw_tech_bracket_rect(clip, g)
    d = s(7, g)
    assert out == (clip[0] - d, clip[1] - d, clip[2] + d, clip[3] + d)
    if g <= 16:
        assert imms == SL.RW_TECH_CARD_IMMS and out == (803, 115, 1103, 182)              # identity


# ============================================================================== 2. the table
def _rowmap(rows):
    return {site: (a, b, bits) for site, a, b, bits in rows}


def test_card_rows_in_the_report_table(bak_bytes):
    rw = _rowmap(AR.rw_rows())
    img = pefile.PE(data=bak_bytes, fast_load=True).get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    for va, v in SL.RW_TECH_CARD_IMMS.items():
        w = 4 if INSN[va].startswith("mov") else 1           # B8 imm32 / 8D 42 disp8, 83 /0 imm8
        at = va - (1 if w == 4 else 2)
        ins = next(md.disasm(img[at - 0x400000:at - 0x400000 + 16], at))
        assert f"{ins.mnemonic} {ins.op_str}" == INSN[va], hex(va)
        assert int.from_bytes(img[va - 0x400000:va - 0x400000 + w], "little", signed=True) == v
        assert rw[va] == (v, 0, AD.KINDBITS["HD"] | (AD.K_W4 if w == 4 else 0)), hex(va)
        for g in GS:
            val = AD.imm_value(v, 0, rw[va][2], g)
            assert val == s(v, g) and (w == 4 or -128 <= val <= 127)
    # F2-only code: never in a table a Datalinks walk applies or reverts (DL tech open/close, the F2 tech bracket's
    # g / 16 pair, the DL main table)
    for rows in (AR.tech_rows(), AD.imm_rows(True), AD.imm_rows(False)):
        assert not set(_rowmap(rows)) & set(SL.RW_TECH_CARD_IMMS)
    assert len(AR.RW_TAB) == AR.RW_TAB_LEN == 6836 - 32                                   # footprint unchanged


# operands of the card span that are not coordinates (instruction VA -> reason)
CARD_NON_COORD = {
    0x498C99: "detour t_rw_hdr1 (0x46 / 3 / 0x43 -> s())", 0x498C9C: "t_rw_hdr1", 0x498C9F: "t_rw_hdr1",
    0x498CCF: "detour t_rw_hdr2 (wide extension 0x62 -> s())", 0x498CD2: "t_rw_hdr2: push 0 (replayed)",
    0x498E43: "detour t_rw_hdr3 (brain icon 0x40 -> s())",
    0x498D06: "imm32 0x2F written by t_rw_init_leave (TXTBOX_IMM)", 0x498D0D: "imm32 0x31 written by t_rw_init_leave (SPACER_IMM)",
    0x498CEB: "sar 1 (centring halve)", 0x498D30: "shl 6 (faction stride)", 0x498D5B: "shl 2 (faction stride)",
    0x49928B: "sar 5 (/100)", 0x499292: "shr 0x1F (sign)",
    0x498D41: "text colour args", 0x498D43: "text colour args", 0x498D45: "text colour args", 0x498D50: "text colour 0xE1",
    0x498FD7: "text colour args", 0x498FD9: "text colour args", 0x498FDE: "text colour args",
    0x499421: "text colour args", 0x499423: "text colour args", 0x499425: "text colour args", 0x499427: "text colour 0xE1",
    0x498D7C: "string clear", 0x498F03: "string clear", 0x498FE4: "string clear",
    0x498DA0: "test omniscient bit", 0x498DAE: "test GameRules 0x200", 0x4990AF: "test omniscient bit",
    0x4990BD: "test GameRules 0x200",
    0x498F15: "arg 0", 0x498F36: "cmp tech id 0x58", 0x498F56: "itoa radix 10", 0x499051: "arg 0",
    0x49905F: "itoa radix 10", 0x499082: "Spot_kill_type 0", 0x49909D: "Spot_add flag 0", 0x49909F: "Spot_add id 0x29A",
    0x499194: "switch index <= 3", 0x49921F: "switch index <= 3", 0x4992F4: "switch index <= 3", 0x4993B8: "switch index <= 3",
    0x49925E: "lea [Buffer + 0x30]: the buffer bounds rect", 0x49934F: "lea [Buffer + 0x30]", 0x49940D: "lea [Buffer + 0x30]",
    0x49943A: "string param index 0", 0x499492: "9999 (no rate)", 0x4994B9: "ceil-division -1", 0x4994C3: "string param 0",
    0x4994D9: "string param 1",
}


def test_card_span_has_no_coordinate_immediate_outside_the_table(bak_bytes):
    """What missed F45: every immediate / displacement in 0x498C5A..0x499521 is a g_rw_immtab row (incl. the console
    chain rows), an RW field / local / global, stack cleanup, or a listed non-coordinate."""
    img = pefile.PE(data=bak_bytes, fast_load=True).get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    from capstone import x86_const as X
    rows = set(_rowmap(AR.rw_rows())) | {r[0] for r in AR.CHAIN_ROWS}
    missing, seen = [], set()
    lo, hi = CARD
    for ins in md.disasm(img[lo - 0x400000:hi - 0x400000], lo):
        if ins.mnemonic == "call" or ins.group(capstone.CS_GRP_JUMP):
            continue
        for op in ins.operands:
            if op.type == X.X86_OP_IMM:
                at, v, base = ins.address + ins.imm_offset, op.imm, None
            elif op.type == X.X86_OP_MEM and op.mem.disp:
                at, v, base = ins.address + ins.disp_offset, op.mem.disp, ins.reg_name(op.mem.base) if op.mem.base else None
            else:
                continue
            if at in rows:
                seen.add(at)
                continue
            if base in ("ebp", "esi") or (base is not None and ins.mnemonic != "lea") or (base is None and v >= 0x400000):
                continue
            if ins.mnemonic == "add" and ins.op_str.startswith("esp,"):
                continue
            if ins.address in CARD_NON_COORD:
                continue
            missing.append(f"{ins.address:#x} {ins.mnemonic} {ins.op_str}")
    assert missing == []
    assert set(SL.RW_TECH_CARD_IMMS) <= seen


# ============================================================================== 3. end to end, real images
@pytest.fixture(scope="module")
def rig(baked_exe):
    import rw_techcard_emu as RC
    return RC.CardRig(str(baked_exe), RC.RT.symtab())


@pytest.fixture(scope="module")
def rig_pristine(bak_path):
    import rw_techcard_emu as RC
    r = RC.CardRig(str(bak_path))
    assert not r.patched
    return r


def _check(rec, g, blind):
    assert rec.get("left") and rec["imms"] == SL.rw_tech_card_imms(g)          # the card READ the law's values
    if blind:
        band, box = rec["band"], rec["blind_box"]
        assert (box[0], box[2], rec["blind_x"]) == SL.rw_tech_blind_header(band[0], band[2], g)
        assert box[0] - band[0] == band[2] - box[2]                              # symmetric
        assert rec["bar"][0] == box[0]                                           # bar under the box (row 0x49911E)
        assert rec["line2_x"] == rec["blind_x"]
        assert "name_end" not in rec
    else:
        box = rec["textbox"]
        assert rec["line1_x"] == rec["line2_x"] == SL.rw_tech_line_x(box[0], g)
        assert rec["name_next"] == SL.rw_tech_text_gap(rec["name_end"], SL.RW_TECH_NAME_GAP, g)
    assert rec["rate_next"] == SL.rw_tech_text_gap(rec["rate_end"], SL.RW_TECH_RATE_GAP, g)
    for clip, box in (("clip1", "bracket1"), ("clip2", "bracket2")):
        assert rec[clip][2] > rec[clip][0]                                       # a non-empty increment
        assert rec[box] == SL.rw_tech_bracket_rect(rec[clip], g)
    assert rec["after2"] == rec["clip2"]                                         # inset back: round trip


@pytest.mark.parametrize("blind", (0, 1))
@pytest.mark.parametrize("g", GS)
def test_card_on_the_real_image(rig, g, blind):
    rec = rig.card(g, blind)
    assert rec.get("entries") == 1
    _check(rec, g, blind)


@pytest.mark.parametrize("blind", (0, 1))
def test_g16_is_pristine(rig, rig_pristine, blind):
    a, b = rig.card(16, blind), rig_pristine.card(16, blind)
    keys = set(b) - {"after_imms", "entry_imms"}
    assert {k: a[k] for k in keys} == {k: b[k] for k in keys}
    assert a["imms"] == SL.RW_TECH_CARD_IMMS


@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_datalinks_never_runs_or_reverts_the_rows(rig, g):
    rec = rig.dl(g)
    assert rec.get("entries") == 1 and "f45_exec" not in rec                     # the DL page skips the F2 branch
    if g > 16:
        # the report walk at game load, then every tech walk a Datalinks session makes in any order (open at g, an F2
        # repaint inside it at g / 16, close at 16): the F45 sites stay s(v)
        rig.reset(g)
        rig._walk("g_rw_immtab", g, immsum=True)
        for t, gg in (("g_dl_immtab_main", g), ("g_dl_immtab_tech", g), ("g_rw_immtab_tech", g), ("g_rw_immtab_tech", 16),
                      ("g_dl_immtab_tech", 16)):
            rig._walk(t, gg)
        assert rig.f45_imms() == SL.rw_tech_card_imms(g)


@pytest.mark.parametrize("g", (18, 22, 25, 40))
def test_mutant_without_the_rows_fails(rig, g):
    """Kill check: the F45 sites native after the report walk (= 6fd3a41e) break every relation the rows own."""
    rig.mutant = True
    try:
        n, b = rig.card(g, 0), rig.card(g, 1)
    finally:
        rig.mutant = False
    assert n["imms"] == SL.RW_TECH_CARD_IMMS
    assert n["line2_x"] - n["textbox"][0] == 3 != s(3, g) or s(3, g) == 3
    assert n["name_next"] - n["name_end"] == 15 != s(15, g)
    assert n["bracket1"] != SL.rw_tech_bracket_rect(n["clip1"], g)
    assert b["blind_x"] - b["blind_box"][0] == 5 != s(5, g)
    if s(3, g) != 3:
        assert b["blind_box"][0] - b["band"][0] != b["band"][2] - b["blind_box"][2]   # lopsided
