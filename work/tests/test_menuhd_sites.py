"""uimod's HD main menu (src/uimod/src/menuhd.cpp), against the pristine exe.

menuhd retargets change_opening's Buffer_load_pcx (@0x589AA1) and Buffer_copy_3 stretch (@0x589AE8), the 6
Buffer_load_pcx calls of custom_planet's previews and the 5 calls of SetupWin_draw_item. Its DrawItemHook empties
deco[clamp(item, 0, 2)] (SetupWin +0xA1C) for the stock draw and draws the HD preview into the TopMenuWin canvas
(+0x444) itself, presented with GraphicWin_soft_update. Every one of those facts is pinned here.
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
HD = (SRC_DIR / "menuhd.cpp").read_text(encoding="utf-8")
PREFS = (SRC_DIR / "prefs.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

LOAD_PCX, COPY3, DRAW2, DRAW_ITEM, SOFT_UPDATE = 0x5D7DE0, 0x5D9610, 0x5D84C0, 0x4AE4D0, 0x5D5720
CHANGE_OPENING, CHANGE_OPENING_END = 0x589A30, 0x589B20
CUSTOM_PLANET, CUSTOM_PLANET_END = 0x58C2A0, 0x58D6B0      # map_menu follows
TOPMENUWIN = 0x945824
SITE_LOAD, SITE_COPY = 0x589AA1, 0x589AE8
DRAW_ITEM_SITES = [0x4AE0D7, 0x4AE3B6, 0x4AE3C9, 0x4AE43A, 0x4AE44A]
PLANET_LOAD_SITES = [0x58C44F, 0x58C4D1, 0x58C4F8, 0x58C51F, 0x58C5DB, 0x58C6B7]


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def calls(pe, lo, hi, target):
    """Every E8 call to target in [lo, hi), searched over the whole image's executable sections."""
    out = []
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:          # IMAGE_SCN_MEM_EXECUTE
            continue
        va0 = pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress
        d = s.get_data()
        for va in range(max(lo, va0), min(hi, va0 + len(d)) - 4):
            o = va - va0
            if d[o] == 0xE8 and va + 5 + struct.unpack("<i", d[o + 1:o + 5])[0] == target:
                out.append(va)
    return out


def const(name):
    m = re.search(r"\b" + name + r"\s*=\s*(0x[0-9A-Fa-f]+|\d+)", HD)
    assert m, name
    return int(m.group(1), 0)


def table(name):
    m = re.search(name + r"\[\]\s*=\s*\{(.*?)\};", HD, re.S)
    assert m, name
    return [int(v, 16) for v in re.findall(r"0x[0-9A-Fa-f]+", m.group(1))]


def test_source_constants_are_the_pinned_ones():
    assert const("kVA_LoadPcx") == LOAD_PCX and const("kVA_Copy3") == COPY3 and const("kVA_Draw2") == DRAW2
    assert const("kVA_DrawItem") == DRAW_ITEM and const("kVA_SoftUpdate") == SOFT_UPDATE
    assert const("kVA_TopMenuWin") == TOPMENUWIN and const("kDecoOfs") == 0xA1C and const("kCanvasOfs") == 0x444
    assert const("kSiteLoad") == SITE_LOAD and const("kSiteCopy") == SITE_COPY
    assert table("kDrawItemSites") == DRAW_ITEM_SITES and table("kPlanetLoadSites") == PLANET_LOAD_SITES
    assert "InstallMenuHd();" in INIT
    assert re.search(r'"HD Main Menu", &MenuHdAvailable', PREFS)


def test_change_opening_has_exactly_one_load_and_one_stretch(pe):
    assert calls(pe, CHANGE_OPENING, CHANGE_OPENING_END, LOAD_PCX) == [SITE_LOAD]
    assert calls(pe, CHANGE_OPENING, CHANGE_OPENING_END, COPY3) == [SITE_COPY]
    # the stretch goes to the TopMenuWin canvas: mov ecx/eax, [0x945824] in the function
    assert struct.pack("<I", TOPMENUWIN) in rd(pe, CHANGE_OPENING, CHANGE_OPENING_END - CHANGE_OPENING)


def test_every_draw_item_call_and_every_preview_load_is_retargeted(pe):
    assert calls(pe, 0x401000, 0x700000, DRAW_ITEM) == DRAW_ITEM_SITES
    assert calls(pe, CUSTOM_PLANET, CUSTOM_PLANET_END, LOAD_PCX) == PLANET_LOAD_SITES


def test_draw_item_draws_deco_clamped_0_2_into_the_topmenuwin_canvas(pe):
    body = rd(pe, DRAW_ITEM, 0x290)
    assert body.startswith(bytes.fromhex("558BEC83EC10538B5D08568BF1"))           # ebx = item, esi = self
    assert bytes.fromhex("85DB7C0C83FB027E09BB02000000EB0233DB") in body        # clamp item to 0..2 (<0 -> 0)
    assert bytes.fromhex("8BBC9E1C0A0000") in body                              # mov edi, [esi + ebx*4 + 0xA1C]
    assert bytes.fromhex("85FF0F84") in body                                    # test edi, edi; je (no deco -> skip)
    assert bytes.fromhex("8B45" "0C" "85C0") in body                            # the highlighted flag [ebp+0xC] gates it
    assert bytes.fromhex("05" "44040000") in body                               # TopMenuWin + 0x444 (the canvas)
    assert calls(pe, DRAW_ITEM, DRAW_ITEM + 0x290, SOFT_UPDATE)
    assert rd(pe, DRAW_ITEM + 0x284, 3) == bytes.fromhex("C20800")              # ret 8


def test_soft_update_and_draw2_are_the_engine_functions_menuhd_calls(pe):
    # GraphicWin_soft_update(win, x, y, w, h) RET 0x10; Buffer_draw_2(src, dst, key, x, y, num, den) RET 0x18 --
    # the draw_item deco block calls the latter exactly so (push 1; push 1; push y; push x; push 9; push dst)
    body = rd(pe, DRAW_ITEM, 0x290)
    assert bytes.fromhex("6A016A01") in body and calls(pe, DRAW_ITEM, DRAW_ITEM + 0x290, DRAW2)
    assert rd(pe, SOFT_UPDATE, 3) == bytes.fromhex("83EC20")


def test_previews_are_loaded_like_the_opening(pe):
    """custom_planet loads its previews with Buffer_load_pcx(name, 0, 10, 236), the opening's own index map."""
    body = rd(pe, CUSTOM_PLANET, CUSTOM_PLANET_END - CUSTOM_PLANET)
    assert body.count(bytes.fromhex("68EC000000" "6A0A")) >= 4
    assert re.search(r"kRemapBase = 10, kRemapCount = 236", HD)


def test_no_engine_loader_for_the_pack_and_no_buffer_destroyed():
    upper = HD.upper()
    assert "0X5D7410" not in upper                                              # Buffer_dtor
    assert "pcx::Decode(" in HD
