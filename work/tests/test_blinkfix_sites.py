"""uimod's unit-blink fix (src/uimod/src/blinkfix.cpp) against the pristine exe.

The selected unit's blink redraws its tile with MapWin_draw_radius(x, y, 0, 2) from draw_cursor 0x46AE00
(blink_timer's callee) and MapWin_draw_cursor 0x46AD60; a sprite wider than the tile box leaves a sliver
standing on the off tick (vanilla). The DLL turns both radius operands into 1. The bytes the source
expects must be the pristine ones, both pushes must be the radius argument of a call to MapWin_draw_radius,
and the DLL must install the fix.
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
FIX = (SRC_DIR / "blinkfix.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

DRAW_RADIUS = 0x46A2A0
SITES = {0x46AEBC: "50", 0x46ADE2: "52"}   # push eax / push edx before the call


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def cpp_sites():
    out = {}
    for m in re.finditer(r"\{\s*0x([0-9A-Fa-f]+),\s*\{([^}]*)\}", FIX):
        va = int(m.group(1), 16)
        out[va] = bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(2)))
    return out


def test_sites_are_the_radius_0_draw_radius_calls(pe):
    sites = cpp_sites()
    assert set(sites) == set(SITES)
    for va, reg in SITES.items():
        b = rd(pe, va, 11)
        assert b == sites[va], hex(va)
        assert b[:6] == bytes.fromhex("6A02" "6A00" "57" + reg)            # push 2; push 0 (radius); push edi; push reg
        assert b[6] == 0xE8 and va + 6 + 5 + struct.unpack("<i", b[7:11])[0] == DRAW_RADIUS
    assert re.search(r"kRadiusOff\s*=\s*3\b", FIX) and re.search(r"kRadius\s*=\s*1\b", FIX)
    assert "InstallBlinkFix();" in INIT


def test_draw_radius_2_is_the_engine_precedent_for_radius_1(pe):
    """MapWin_draw_radius_2 0x46A530 calls MapWin_draw_radius(x, y, 1, mode): radius 1 is a value the engine
    itself draws with."""
    assert rd(pe, 0x46A530, 0x1A).find(bytes.fromhex("6A01")) >= 0
