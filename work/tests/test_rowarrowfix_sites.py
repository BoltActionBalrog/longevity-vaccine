"""uimod's unit-row arrow fix (src/uimod/src/rowarrowfix.cpp) against the pristine exe.

The console's unit-row scroll arrows are MainWin FlatButtons [8] 0x7B5080 / [9] 0x7B5BCC / [10] 0x7B6718, shown only
by BaseWin_draw_garrison and StatusWin_draw_status. The HUD's leave handler hides every console button; the base
screen's leave handler BaseWin_on_status(0) does not, so [9]/[10] stayed up over the Design Workshop (vanilla). The
DLL wraps the base interface's vtable slot and hides the three arrows on leave. Every address and byte the source
relies on must be the pristine ones, and the DLL must install the fix.
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
FIX = (SRC_DIR / "rowarrowfix.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")
VCXPROJ = (ROOT.parent / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")

SLOT = 0x66A3B8
ON_STATUS = 0x41DAD0
FLAT_VTBL = 0x669754
FLAT_HIDE = 0x406860
WIN_HIDE = 0x5EDCD0
ARROWS = (0x7B5080, 0x7B5BCC, 0x7B6718)


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def u32(pe, va):
    return struct.unpack("<I", rd(pe, va, 4))[0]


def cpp_const(name):
    m = re.search(name + r"\s*=\s*0x([0-9A-Fa-f]+)", FIX)
    assert m, name
    return int(m.group(1), 16)


def test_source_addresses_match():
    assert cpp_const("kVA_BaseIfaceOnStatusSlot") == SLOT
    assert cpp_const("kVA_BaseWinOnStatus") == ON_STATUS
    assert cpp_const("kVA_FlatButtonVtbl") == FLAT_VTBL
    assert cpp_const("kVA_FlatButtonHide") == FLAT_HIDE
    m = re.search(r"kVA_RowArrows\[3\]\s*=\s*\{([^}]*)\}", FIX)
    assert m and tuple(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]+)", m.group(1))) == ARROWS
    assert re.search(r"kWinVisibleOff\s*=\s*0x9C\b", FIX)


def test_slot_is_the_base_on_status_and_prologue_matches(pe):
    assert u32(pe, SLOT) == ON_STATUS
    m = re.search(r"kOnStatusPrologue\[14\]\s*=\s*\{([^}]*)\}", FIX)
    expect = bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))
    assert rd(pe, ON_STATUS, 14) == expect
    # je rel32 to the leave branch (enter == 0); RET 4 at both exits = thiscall(iface, enter)
    leave = ON_STATUS + 0x12 + struct.unpack("<i", rd(pe, ON_STATUS + 0x0E, 4))[0]
    assert leave == 0x41DBFA
    assert rd(pe, 0x41DBF7, 3) == bytes.fromhex("C20400") and rd(pe, 0x41DC7C, 3) == bytes.fromhex("C20400")


def test_leave_branch_never_touches_the_row_arrows(pe):
    """The bug: BaseWin_on_status's whole body never names [8]/[9]/[10]."""
    body = rd(pe, ON_STATUS, 0x41DC7E - ON_STATUS)
    for va in ARROWS:
        assert struct.pack("<I", va) not in body


def test_garrison_painter_shows_these_buttons(pe):
    # BaseWin_draw_garrison: mov ecx,[8]; call [edx+8] (hide); mov ecx,[9]/[10]; call [eax/edx+4] (show)
    assert rd(pe, 0x410579, 5) == b"\xB9" + struct.pack("<I", ARROWS[0])
    assert rd(pe, 0x4105C5, 5) == b"\xB9" + struct.pack("<I", ARROWS[1])
    assert rd(pe, 0x4105E0, 5) == b"\xB9" + struct.pack("<I", ARROWS[2])
    assert rd(pe, 0x4105D5, 3) == bytes.fromhex("FF5004") and rd(pe, 0x4105E5, 3) == bytes.fromhex("FF5204")


def test_hud_leave_is_the_engine_precedent(pe):
    """The HUD's leave hides all 0x2A console buttons from MainWin+0x3EC through vtbl+8 (the loop @0x45CAAF)."""
    assert rd(pe, 0x45CAAF, 0x1B) == bytes.fromhex("8DB7EC030000" "BB2A000000" "8B16" "8BCE" "FF5208"
                                                   "81C64C0B0000" "4B" "75F0")


def test_flatbutton_hide_is_win_hide(pe):
    assert u32(pe, FLAT_VTBL + 8) == FLAT_HIDE
    b = rd(pe, FLAT_HIDE, 25)
    assert b[20] == 0xE9 and FLAT_HIDE + 25 + struct.unpack("<i", b[21:25])[0] == WIN_HIDE


def test_installed():
    assert "InstallRowArrowFix();" in INIT
    assert r'<ClCompile Include="src\rowarrowfix.cpp" />' in VCXPROJ
    assert "void __fastcall BaseOnStatus(void* iface, void* /*edx*/, int enter)" in FIX
