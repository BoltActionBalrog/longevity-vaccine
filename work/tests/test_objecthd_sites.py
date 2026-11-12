"""uimod's HD map objects (src/uimod/src/objecthd.cpp), against the pristine exe.

objecthd retargets every Sprite_blit_scaled_core / Sprite_draw_dest call in MapWin_gen_terrain_poly (18 + 3) and the
native-unit Sprite_draw_dest @0x5598F9, and draws HD copies of the sprites load_terrain / load_units cut at fixed
addresses and rects. It decodes its packs itself with load_terrain's index map: Buffer_load_pcx(name, 0, 10, 236)
(loaded = file + 10 mod 256) then Buffer_change_color(0x107 / 0x106 -> 0x109). Every one of those facts is pinned
here, and the source must use the pinned values and never load a master through the engine (a pcx-loaded Buffer must
never be destroyed: see test_basehd_sites.py).
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pefile  # noqa: E402

import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
HD = (SRC_DIR / "objecthd.cpp").read_text(encoding="utf-8")
PREFS = (SRC_DIR / "prefs.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

EXTRACT2, BLIT_SCALED, DRAW_DEST = 0x5E39A0, 0x5E4B9A, 0x5E5833
LOAD_PCX, CHANGE_COLOR = 0x5D7DE0, 0x5DE580
LOAD_TERRAIN, LOAD_TERRAIN_END = 0x451C50, 0x453710        # load_faction_art follows
LOAD_UNITS, LOAD_UNITS_END = 0x454270, 0x4547E0            # load_icons follows
GEN_POLY, GEN_POLY_END = 0x4632D0, 0x466CA0
UNIT_DRAW_SITE = 0x5598F9
EXTRACT_SITES = [0x452C07, 0x452D97, 0x453087, 0x453508, 0x453656, 0x4536A8, 0x4524A8, 0x452B8C, 0x454568]


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def calls(pe, lo, hi, target):
    d = rd(pe, lo, hi - lo)
    return [lo + i for i in range(len(d) - 4)
            if d[i] == 0xE8 and lo + i + 5 + struct.unpack("<i", d[i + 1:i + 5])[0] == target]


def const(name):
    m = re.search(r"\b" + name + r"\s*=\s*(0x[0-9A-Fa-f]+|\d+)", HD)
    assert m, name
    return int(m.group(1), 0)


def table_literals(name):
    """The {va, x, y} rows of the named literal table in BuildTable."""
    m = re.search(r"\b" + name + r"\[\]\s*=\s*\{(.*?)\};", HD, re.S)
    assert m, name
    return [tuple(int(v, 16) for v in row) for row in re.findall(r"\{(0x[0-9A-F]+), (0x[0-9A-F]+), (0x[0-9A-F]+)\}", m.group(1))]


def test_source_constants_are_the_pinned_ones():
    assert const("kVA_Extract2") == EXTRACT2 and const("kVA_Draw3") == BLIT_SCALED and const("kVA_DrawDest") == DRAW_DEST
    assert const("kFnLo") == GEN_POLY and const("kFnHi") == GEN_POLY_END
    assert const("kUnitDrawSite") == UNIT_DRAW_SITE
    assert const("kDraw3Calls") == 18 and const("kDrawDestCalls") == 3
    sites = [int(v, 16) for v in re.findall(r"0x[0-9A-F]+", re.search(r"kExtractSites\[\]\s*=\s*\{(.*?)\};", HD, re.S).group(1))]
    assert sites == EXTRACT_SITES
    assert "InstallObjectHd();" in INIT
    assert re.search(r'"HD Map Objects", &ObjectHdAvailable', PREFS)


def test_every_cut_site_is_a_sprite_extract(pe):
    for va in EXTRACT_SITES:
        assert calls(pe, va, va + 5, EXTRACT2) == [va], hex(va)


def test_the_terrain_pass_has_exactly_the_draw_calls_objecthd_retargets(pe):
    assert len(calls(pe, GEN_POLY, GEN_POLY_END, BLIT_SCALED)) == 18
    assert len(calls(pe, GEN_POLY, GEN_POLY_END, DRAW_DEST)) == 3
    assert calls(pe, UNIT_DRAW_SITE, UNIT_DRAW_SITE + 5, DRAW_DEST) == [UNIT_DRAW_SITE]


@pytest.mark.parametrize("lo,hi", [(LOAD_TERRAIN, LOAD_TERRAIN_END), (LOAD_UNITS, LOAD_UNITS_END)])
def test_the_loaders_use_the_index_map_objecthd_ports(pe, lo, hi):
    body = rd(pe, lo, hi - lo)
    assert body.count(bytes.fromhex("68EC000000" "6A0A" "6A00")) >= 1          # Buffer_load_pcx(name, 0, 10, 236)
    assert calls(pe, lo, hi, LOAD_PCX)
    # Buffer_change_color(0x107 -> 0x109) and (0x106 -> 0x109): push 0x109; push 0x107 / 0x106
    assert bytes.fromhex("6809010000" "6807010000") in body
    assert bytes.fromhex("6809010000" "6806010000") in body
    assert calls(pe, lo, hi, CHANGE_COLOR)
    assert const("kLoadShift") == 10 and const("kKeyIndex") == 9 and const("kBgIndex") == 7 and const("kSlabIndex") == 6


def test_every_single_cut_in_the_table_is_load_terrains(pe):
    """The literal rows of BuildTable (the singles and the wreck) are load_terrain's own `mov ecx, <sprite>` targets."""
    body = rd(pe, LOAD_TERRAIN, LOAD_TERRAIN_END - LOAD_TERRAIN)
    rows = table_literals("singles") + table_literals("wreck")
    assert len(rows) == 23 + 25
    for va, _x, _y in rows:
        assert b"\xB9" + struct.pack("<I", va) in body, hex(va)


def test_masters_never_go_through_the_engine_loader():
    """A pcx-loaded Buffer must never be destroyed (Buffer_close DeleteObject's what it holds); objecthd decodes its packs
    itself and frees them, so it calls neither Buffer_load_pcx nor Buffer_dtor."""
    upper = HD.upper()
    assert "0X5D7DE0" not in upper and "0X5D7410" not in upper
    assert "pcx::Decode(" in HD and "free(m);" in HD


def test_draws_unscaled_with_den_untouched():
    assert re.search(r"\*num = \*reinterpret_cast<int32_t\*>\(At\(kVA_ScaleDen\)\);", HD)
    assert not re.search(r"\*den\s*=", HD)
