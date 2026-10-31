"""uimod's HUD unit-panel sync (src/uimod/src/hudsync.cpp) against the pristine exe.

(a) Console_human_turn's `cmp [MoveMode],edi; je view-block` @0x5140D6 (8 B) is detoured to a stub that sets
MoveMode := 1 for a single-player resumed turn with a pending unit before replaying the test, so the engine's
own Console_set_move(1) path runs (the base game resumed a game saved in view mode half-selected).
(b) Console_veh_turn's entry (0x513B90, 6 B of a plain prologue) syncs StatusWin's info tile to the unit.
The bytes the source expects must be the pristine ones and both sites must be clear of patches.yaml.
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
FIX = (SRC_DIR / "hudsync.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")
WHEEL = (SRC_DIR / "wheel.cpp").read_text(encoding="utf-8")

SET_MOVE = 0x511520
SITES = [(0x513B90, 0x513B96), (0x5140D6, 0x5140DE)]   # (site, end)


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def cpp_bytes(name):
    m = re.search(name + r"\[[^\]]*\]\s*=\s*\{([^}]*)\}", FIX)
    assert m, name
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def call_target(pe, va):
    assert rd(pe, va, 1) == b"\xE8"
    return va + 5 + struct.unpack("<i", rd(pe, va + 1, 4))[0]


def test_veh_turn_entry(pe):
    b = rd(pe, 0x513B90, 21)
    assert b == cpp_bytes("kVehTurnPro")
    assert b[:6] == bytes.fromhex("558BEC" "83EC14")                      # push ebp; mov ebp,esp; sub esp,0x14 (displaced)
    assert b[11:21] == bytes.fromhex("C783E43B0200" "01000000")           # mov [ebx+0x23BE4], 1 (the pump-live flag)
    assert re.search(r"kVA_VehTurnResume\s*=\s*0x513B96\b", FIX) and re.search(r"kVehTurnLen\s*=\s*6\b", FIX)
    assert rd(pe, 0x4B9EA0, 6) == cpp_bytes("kRedrawPro")
    assert rd(pe, 0x4B9F90, 15) == cpp_bytes("kSetLocPro")


def test_human_turn_mode_branch(pe):
    """ControlTurnMove == 0 -> set_move(0); else MoveMode == 0 -> view block @0x5140E8, else set_move(1) @0x5140E1."""
    b = rd(pe, 0x5140B7, 49)
    assert b == cpp_bytes("kHtExpect")
    assert b[:8] == bytes.fromhex("393D70209B00" "7517")                   # cmp [ControlTurnMove 0x9B2070], edi; jne 0x5140D6
    assert 0x5140BD + 2 + 0x17 == 0x5140D6
    assert b[11:21] == bytes.fromhex("C786DC3B0200" "FFFFFFFF")           # CurVeh := -1 on the fresh-turn arm
    assert call_target(pe, 0x5140CC) == SET_MOVE and call_target(pe, 0x5140E1) == SET_MOVE
    assert b[31:39] == bytes.fromhex("393D88929300" "740A")               # the site: cmp [MoveMode 0x939288], edi; je 0x5140E8
    assert 0x5140DC + 2 + 0x0A == 0x5140E8 and 0x5140D6 + 8 == 0x5140DE
    for name, val in [("kVA_HtSite", "0x5140D6"), ("kVA_HtResumeMove", "0x5140DE"), ("kVA_HtResumeView", "0x5140E8"), ("kHtLen", "8")]:
        assert re.search(name + r"\s*=\s*" + val + r"\b", FIX), name
    # the stub's conditions read the engine's cells
    assert "ds:[0x93F660]" in FIX and "ds:[0x9A64C0]" in FIX and "[esi + 0x23BDC]" in FIX and "ds:[0x939288], 1" in FIX
    # game_data stores and restores MoveMode and CurVeh (push 0x939288 / push 0x93928C into its field I/O)
    assert rd(pe, 0x5A8455, 5) == bytes.fromhex("6888929300") and rd(pe, 0x5A84AC, 5) == bytes.fromhex("688C929300")


def test_exe_sites_clear_of_the_patcher(loaded):
    for s in loaded["sites"]:
        va, ln = s.get("virtual_addr"), s.get("length")
        if va is not None and ln:
            lo, hi = int(va), int(va) + int(ln)
            for site, end in SITES:
                assert hi <= site or lo >= end, s.get("id")


def test_sites_clear_of_thinker(need_local):
    """Thinker's in-memory patches (refs/thinker/src/patch.cpp) must not touch either displaced instruction."""
    src = need_local(ROOT.parent / "refs" / "thinker" / "src" / "patch.cpp", "the Thinker clone (refs/thinker)").read_text(
        encoding="utf-8", errors="replace")
    for m in re.finditer(r"0x([0-9A-Fa-f]{6})", src):
        va = int(m.group(1), 16)
        for site, end in SITES:
            assert not (site - 5 < va < end), f"Thinker touches {va:#x} next to site {site:#x}"


def test_wired_in():
    assert "InstallHudSync();" in INIT
    assert "HudSyncPoll" not in WHEEL and "HudSyncPoll" not in FIX     # the PRACX hover gate was withdrawn (audit 2026-10-10)
    assert "ModernCtlVehs()" in FIX and "ModernCtlVehOk(" in FIX         # the unit array comes from modernctl's resolver
