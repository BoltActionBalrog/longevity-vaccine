"""uimod's HUD moves-readout fix (src/uimod/src/hudmovesfix.cpp) against the pristine exe.

Two order-clearing stores leave the unit panel stale: action_go_to's Path_move < 0 branch @0x4CB550 (the
traced case: the greedy fallback runs out of neighbours) and Console_veh_turn's 100-refused-steps cancel
@0x513E27. The DLL detours both to stubs that also call StatusWin_redraw. The bytes the source expects must
be the pristine ones, each store must be the order byte of the Veh array, each resume address must be the
instruction after the store, and the DLL must install the fix.
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
FIX = (SRC_DIR / "hudmovesfix.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

STATUSWIN, REDRAW = 0x8C5568, 0x4B9EA0
VEHS, VEH_ORDER = 0x952828, 0x11
CHECK_A, SITE_A, RESUME_A = 0x4CB548, 0x4CB550, 0x4CB558
CHECK_B, SITE_B, RESUME_B = 0x513E22, 0x513E27, 0x513E39


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def cpp_bytes(name):
    m = re.search(name + r"\[[^\]]*\]\s*=\s*\{([^}]*)\}", FIX)
    assert m, name
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def test_site_a_is_action_go_to_order_clear(pe):
    b = rd(pe, CHECK_A, 22)
    assert b == cpp_bytes("kExpectA")
    assert b[:8] == bytes.fromhex("8D0449" "85F6" "8D1481")              # lea eax,[ecx+ecx*2]; test esi,esi; lea edx,[ecx+eax*4]  (edx*4 = veh*0x34)
    assert b[8:16] == bytes.fromhex("C60495" "39289500" "00")           # mov byte [edx*4+Vehs.order], 0
    assert struct.unpack("<I", b[11:15])[0] == VEHS + VEH_ORDER
    assert SITE_A + 8 == RESUME_A and b[16:18] == bytes.fromhex("7421")   # je: reads the flags of the test BEFORE the store
    # the branch is the Path_move < 0 arm: test eax,eax; jl 0x4CB548 right after the Path_move call
    assert rd(pe, 0x4CB36C, 1) == b"\xE8" and 0x4CB36C + 5 + struct.unpack("<i", rd(pe, 0x4CB36D, 4))[0] == 0x59BC10
    assert rd(pe, 0x4CB380, 8) == bytes.fromhex("85C0" "0F8CC0010000") and 0x4CB388 + 0x1C0 == CHECK_A


def test_site_b_is_the_retry_cancel_store(pe):
    b = rd(pe, CHECK_B, 14)
    assert b == cpp_bytes("kExpectB")
    assert b[:3] == bytes.fromhex("80FA18")                               # cmp dl, ORDER_MOVE_TO (0x18)
    assert b[5:12] == bytes.fromhex("C680" "39289500" "00")               # mov byte [eax+Vehs.order], 0
    assert struct.unpack("<I", b[7:11])[0] == VEHS + VEH_ORDER
    assert b[12:14] == bytes.fromhex("EB09") and SITE_B + 7 + 2 + 9 == RESUME_B
    assert rd(pe, RESUME_B, 5) == bytes.fromhex("A160F69300")             # mov eax, [MultiplayerActive]


def test_repaint_is_the_engines_own(pe):
    assert rd(pe, REDRAW, 6) == cpp_bytes("kRedrawPro")
    # StatusWin_set_loc stores the panel's info tile at +0x15B4/+0x15B8 (the unit box shows only while the active
    # unit stands on it); Console_set_move calls it right before its own StatusWin_redraw
    assert rd(pe, 0x4B9F90, 15) == cpp_bytes("kSetLocPro")
    assert rd(pe, 0x4B9FA2, 6) == bytes.fromhex("8991B8150000")            # mov [ecx+0x15B8], edx
    assert rd(pe, 0x5117CC, 1) == b"\xE8" and 0x5117CC + 5 + struct.unpack("<i", rd(pe, 0x5117CD, 4))[0] == 0x4B9F90
    # the loop's own redraw block calls the same repaint with this = StatusWin (mov ecx, 0x8C5568; call StatusWin_redraw)
    assert rd(pe, 0x513D26, 10) == bytes.fromhex("B968558C00" "E8" + struct.pack("<i", REDRAW - 0x513D30).hex())


def test_sources_carry_the_sites():
    for name, val in [("kVA_SiteA", "0x4CB550"), ("kVA_CheckA", "0x4CB548"), ("kVA_ResumeA", "0x4CB558"),
                      ("kVA_SiteB", "0x513E27"), ("kVA_CheckB", "0x513E22"), ("kVA_ResumeB", "0x513E39"),
                      ("kVA_StatusWin", "0x8C5568"), ("kVA_StatusWinRedraw", "0x4B9EA0"),
                      ("kVA_CurVeh", "0x93928C"), ("kVA_MoveMode", "0x939288"),
                      ("kVA_StatusWinSetLoc", "0x4B9F90")]:
        assert re.search(name + r"\s*=\s*" + val + r"\b", FIX), name
    assert "InstallHudMovesFix();" in INIT
