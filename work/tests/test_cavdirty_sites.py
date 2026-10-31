"""caviar_dirty_rect: the three call sites and the engine facts the thunks rely on, against the pristine exe."""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pefile  # noqa: E402
import yaml  # noqa: E402
from apply_patches import _yaml_load  # the production loader (libyaml)

import assemble_cavdirty as C  # noqa: E402
import config  # noqa: E402


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(config.terranx_bak(required=True)))


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def call_target(pe, va):
    assert rd(pe, va, 1) == b"\xE8"
    return (va + 5 + struct.unpack("<i", rd(pe, va + 1, 4))[0]) & 0xFFFFFFFF


def test_sites_and_targets(pe):
    assert rd(pe, C.SITE_BLIT, 5) == bytes.fromhex(C.ORIG_BLIT) and call_target(pe, C.SITE_BLIT) == C.BUFFER_DRAW_2
    assert rd(pe, C.SITE_TABLE, 5) == bytes.fromhex(C.ORIG_TABLE) and call_target(pe, C.SITE_TABLE) == C.BUFFER_DRAW_DS2
    assert rd(pe, C.SITE_FILL2, 5) == bytes.fromhex(C.ORIG_FILL2) and call_target(pe, C.SITE_FILL2) == C.BUFFER_FILL_2
    assert rd(pe, C.SITE_BLIT - 5, 5) == bytes.fromhex("B9 08 91 9B 00")      # mov ecx, g_caviar_target
    assert rd(pe, C.SITE_TABLE - 5, 5) == bytes.fromhex("B9 B0 96 9B 00")     # mov ecx, g_caviar_target2
    assert rd(pe, C.SITE_FILL2 - 6, 6) == bytes.fromhex("55 B9 B0 96 9B 00")  # push ebp(0); mov ecx, g_caviar_target2


def test_engine_facts_the_thunks_rely_on(pe):
    # the software blit reads the source's +0x54 / +0x4A8 / +0x80 / +0x84 (negated) and nothing else of it
    assert rd(pe, 0x5D8578, 3) == bytes.fromhex("8B 46 54")
    assert rd(pe, 0x5D858A, 6) == bytes.fromhex("8B 86 A8 04 00 00")
    assert rd(pe, 0x5D85A1, 8) == bytes.fromhex("8B 86 84 00 00 00 F7 D8")
    assert rd(pe, 0x5D8F05, 3) == bytes.fromhex("8B 46 54") and rd(pe, 0x5D8F2E, 8) == bytes.fromhex("8B 86 84 00 00 00 F7 D8")
    # the RET sizes
    assert rd(pe, 0x5D855A, 3) == bytes.fromhex("C2 18 00") and rd(pe, 0x5D8FD5, 3) == bytes.fromhex("C2 1C 00")
    assert rd(pe, 0x5DFB90, 3) == bytes.fromhex("C2 04 00")
    # the rects: grown by UnionRect (import 0x669328), zeroed by Caviar_reset AFTER its fills
    pe.parse_data_directories()
    names = {imp.address: imp.name for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports}
    assert names[0x669328] == b"UnionRect"
    assert rd(pe, 0x617558, 6) == bytes.fromhex("FF 15 28 93 66 00")
    assert rd(pe, 0x6184E6, 6) == bytes.fromhex("89 2D 90 96 9B 00")          # mov [0x9B9690], ebp(0)
    assert rd(pe, 0x6184FE, 6) == bytes.fromhex("89 2D 38 B4 9B 00")          # mov [0x9BB438], ebp(0)
    # the map's unit draws: flag = ((state & 0x2000) | 0x1000) >> 12 -> bit 2 clear unless state 0x2000 -> table composite runs
    assert rd(pe, 0x4C1688, 9) == bytes.fromhex("81 E2 00 20 00 00 80 CE 10")
    assert rd(pe, 0x6172AD, 2) == bytes.fromhex("A8 02")                       # test al, 2 -> [this+0xA4]


def test_yaml_wiring():
    doc = _yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    sites = {s["id"]: s for s in doc["sites"]}
    assert sites["Caviar_draw.composite"]["new_bytes"] == "E8 {rel32:t_cav_blit}"
    assert sites["Caviar_draw.table_composite"]["new_bytes"] == "E8 {rel32:t_cav_table}"
    assert sites["Caviar_reset.target2_fill"]["new_bytes"] == "E8 {rel32:t_cav_fill2}"
    cave = next(c for c in doc["code_caves"] if c["id"] == "pcave2")
    assert int(str(cave["length"]), 16) >= 0x31000
    ids = {c["id"]: c for c in cave["contents"]}
    for n, _ in C.THUNKS:
        off = ids[n]["offset"]; off = int(off, 16) if isinstance(off, str) else off
        assert off == C.OFFS[n] and len(bytes.fromhex(ids[n]["bytes"])) == len(C.assemble(n))
    group = next(g for g in doc["groups"] if g["id"] == "caviar_dirty_rect")
    assert set(group["members"]) == {"Caviar_draw.table_composite", "Caviar_reset.target2_fill"}


def test_sites_live_outside_the_design_workshop_splice_block():
    """splice_dw.py cuts the `# ==== dw_bake sites` block by regex and re-inserts assemble_dw's fragment, so a
    foreign site inside that block is silently dropped on the next refresh (audit 2026-10-10)."""
    txt = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    i = txt.index("# ==== dw_bake sites"); j = txt.index("# ==== dw_bake END ==== sites", i)
    assert "group: caviar_dirty_rect" not in txt[i:j]
    assert "id: Caviar_draw.table_composite" not in txt[i:j] and "id: Caviar_reset.target2_fill" not in txt[i:j]
    assert "id: Caviar_draw.composite" in txt[i:j]          # dw_scale's own site stays where its generator puts it


def test_hand_off_addresses_match_the_symbol_table():
    import apply_patches as ap
    doc = _yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    sym = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    assert sym["thunk_dw_shim"] == C.DW_SHIM and sym["g_dw_pickcanvas"] == C.DW_PICKCELL
    assert sym["t_cav_blit"] == C.PCAVE2 + C.OFFS["t_cav_blit"]
    group = next(g for g in doc["groups"] if g["id"] == "caviar_dirty_rect")
    assert group.get("code_caves") == ["pcave2"]
    assert set(group["members"]) == {"Caviar_draw.table_composite", "Caviar_reset.target2_fill"}
