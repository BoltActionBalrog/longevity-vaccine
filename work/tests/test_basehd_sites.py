"""uimod's HD base sprites (src/uimod/src/basehd.cpp) and their Preferences page, against the pristine exe.

basehd retargets two E8 calls: load_faction_art's base-sprite Sprite_extract_2 (@0x453836) and base_draw's
Sprite_draw_dest (@0x55B32B). It names a faction's pack from MFactions[f].filename (the field load_faction_art itself
reads), loads it with load_faction_art's own Buffer_load_pcx arguments (10, 236), and draws an exact-size sprite with
SCALE_NUM_G = SCALE_DEN_G, Sprite_draw_dest's unscaled branch. The "HD art" Preferences page sits behind the stock More
button (id 0x5E), whose own command case flips tab 2 <-> 6. Every one of those facts is pinned here, and the constants
in the source must be the ones pinned.
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
HD = (SRC_DIR / "basehd.cpp").read_text(encoding="utf-8")
PREFS = (SRC_DIR / "prefs.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

LOAD_FACTION_ART = 0x453710
SITE_EXTRACT, EXTRACT2 = 0x453836, 0x5E39A0
SITE_DRAW, DRAW_DEST = 0x55B32B, 0x5E5833
LOAD_PCX = 0x5D7DE0
MFACTIONS, MFACTION_STRIDE, FILENAME = 0x946A50, 0x59C, 0x04
SCALE_NUM, SCALE_DEN = 0x696D18, 0x696D1C
PREFWIN, MORE_OFS, MORE_ID = 0x8578D8, 0x1A868, 0x5E
PREFWIN_COMMAND, MORE_CASE = 0x491400, 0x4914B0


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def call_target(pe, va):
    b = rd(pe, va, 5)
    assert b[0] == 0xE8, hex(va)
    return va + 5 + struct.unpack("<i", b[1:])[0]


def const(src, name):
    m = re.search(r"\b" + name + r"\s*=\s*(0x[0-9A-Fa-f]+|\d+)", src)
    assert m, name
    return int(m.group(1), 0)


def test_source_constants_are_the_pinned_ones():
    assert const(HD, "kSiteExtract") == SITE_EXTRACT and const(HD, "kVA_Extract2") == EXTRACT2
    assert const(HD, "kSiteDraw") == SITE_DRAW and const(HD, "kVA_DrawDest") == DRAW_DEST
    assert const(HD, "kVA_LoadPcx") == LOAD_PCX
    assert const(HD, "kVA_MFactions") == MFACTIONS and const(HD, "kMFactionStride") == MFACTION_STRIDE
    assert const(HD, "kMFactionFilename") == FILENAME
    assert const(HD, "kVA_ScaleNum") == SCALE_NUM and const(HD, "kVA_ScaleDen") == SCALE_DEN
    assert "0x9B86A0" not in HD.upper().replace("0X", "0x")       # never the shared scratch string
    assert const(PREFS, "kMoreBtnId") == MORE_ID and const(PREFS, "kVA_MoreBtn") == PREFWIN + MORE_OFS
    assert "InstallBaseHd();" in INIT


def test_both_sites_are_the_calls_basehd_expects(pe):
    assert call_target(pe, SITE_EXTRACT) == EXTRACT2
    assert call_target(pe, SITE_DRAW) == DRAW_DEST
    assert LOAD_FACTION_ART < SITE_EXTRACT < LOAD_FACTION_ART + 0x200


def test_load_faction_art_reads_the_filename_field_and_loads_with_10_236(pe):
    body = rd(pe, LOAD_FACTION_ART, SITE_EXTRACT - LOAD_FACTION_ART)
    assert struct.pack("<I", MFACTIONS + FILENAME) in body           # MFactions[f].filename
    # Buffer_load_pcx(name, 0, 10, 236): push 0xEC; push 0x0A; push 0; push name; ... call Buffer_load_pcx
    i = body.find(bytes.fromhex("68EC000000" "6A0A" "6A00"))
    assert i >= 0
    calls = [LOAD_FACTION_ART + k for k in range(i, i + 24)
             if body[k] == 0xE8 and LOAD_FACTION_ART + k + 5 + struct.unpack("<i", body[k + 1:k + 5])[0] == LOAD_PCX]
    assert calls
    assert re.search(r"kVA_LoadPcx\)\)\(master, path, nullptr, 10, 236\)", HD)


def test_draw_dest_takes_the_unscaled_branch_when_num_equals_den(pe):
    """basehd draws its exact-size sprite with SCALE_NUM_G = SCALE_DEN_G (SCALE_DEN_G untouched): Sprite_draw_dest's
    first test is `cmp num, den; je` past every scaling step."""
    want = bytes.fromhex("8B0D") + struct.pack("<I", SCALE_NUM) + bytes.fromhex("3B0D") + struct.pack("<I", SCALE_DEN) + b"\x74"
    assert rd(pe, 0x5E5864, len(want)) == want
    assert re.search(r"\*num = d;", HD) and not re.search(r"\*den\s*=", HD)


def test_more_button_is_id_0x5E_and_its_own_case_flips_tab_2_and_6(pe):
    # PrefWin_build: lea edi, [esi + 0x1A868] ... push 0x5E ... mov ecx, edi; call BaseButton_init
    assert rd(pe, 0x48F9A8, 6) == bytes.fromhex("8DBE") + struct.pack("<I", MORE_OFS)
    assert rd(pe, 0x48F9C5, 2) == bytes([0x6A, MORE_ID])
    assert call_target(pe, 0x48F9D5) == 0x607210
    # PrefWin_on_command: ids 6..0x5E through the byte table 0x4917AC -> the dword table 0x491794
    idx = rd(pe, 0x4917AC + MORE_ID - 6, 1)[0]
    assert struct.unpack("<I", rd(pe, 0x491794 + 4 * idx, 4))[0] == MORE_CASE
    case = rd(pe, MORE_CASE, 0x34)
    assert case.startswith(bytes.fromhex("8B8E140A0000" "B802000000" "3BC8"))   # tab == 2 ?
    assert bytes.fromhex("C786140A000006000000") in case                      # -> tab 6 (else -> 2)
    # our tab takes the click before the engine's case could jump to tab 2 / 6
    assert re.search(r"id == kMoreBtnId && g_anyArtRow && OurTabActive\(\)", PREFS)


def test_art_row_ids_are_unique_and_free():
    ids = [int(v, 16) for v in re.findall(r"constexpr int\s+k\w+Id\w*\s*=\s*0x([0-9A-Fa-f]+)", PREFS)]
    art0, n = const(PREFS, "kArtChkId0"), const(PREFS, "kArtRowMax")
    art = set(range(art0, art0 + n))
    others = [i for i in ids if i != art0]
    assert not art & set(others)
    assert len(set(others)) == len(others)
