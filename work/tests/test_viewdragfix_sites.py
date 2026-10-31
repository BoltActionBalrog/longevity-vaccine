"""uimod's view-mode drag fix (src/uimod/src/viewdragfix.cpp) against the pristine exe.

go_timer's view-mode plain-drag branch @0x50F21C searches for a unit to arm the line on; the DLL turns its first
instruction into a jmp to the branch's own cancel exit @0x50F3B8 (call go_reset + epilogue). The bytes the source
expects must be the pristine ones, the jump must land on the go_reset call, modernctl's go_timer anchors must stay
intact, and nothing else may patch the function.
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
FIX = (SRC_DIR / "viewdragfix.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

GO_TIMER, GO_RESET, SITE, CANCEL = 0x50F170, 0x50EF50, 0x50F21C, 0x50F3B8


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def cpp_bytes(name):
    m = re.search(name + r"\[[^\]]*\]\s*=\s*\{([^}]*)\}", FIX)
    assert m, name
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def test_view_mode_branch_and_cancel_exit(pe):
    b = rd(pe, 0x50F203, 34)
    assert b == cpp_bytes("kExpect")
    assert b[:3] == bytes.fromhex("83FF01") and b[9:11] == bytes.fromhex("85C0") and b[17:19] == bytes.fromhex("85C9")
    assert 0x50F206 + 6 + 0xE5 == 0x50F2F1 and 0x50F20E + 6 + 0xDD == 0x50F2F1 and 0x50F216 + 6 + 0xD5 == 0x50F2F1   # the three "arm" skips
    assert b[25:30] == bytes.fromhex("A18C929300")                                 # mov eax, [CurVeh] -- the site
    c = rd(pe, CANCEL, 12)
    assert c == cpp_bytes("kCancelBytes")
    assert CANCEL + 5 + struct.unpack("<i", c[1:5])[0] == GO_RESET                  # call go_reset
    assert re.search(r"kVA_Site\s*=\s*0x50F21C\b", FIX) and re.search(r"kVA_Cancel\s*=\s*0x50F3B8\b", FIX)
    # the eax/MoveMode test right before the site is `test eax,eax` on [0x939288] loaded earlier
    assert rd(pe, 0x50F1F4 - 0x14, 1)  # function body exists (sanity)


def test_modernctl_anchors_untouched():
    """modernctl byte-checks go_timer's veh_find / veh_selectable calls at 0x50F296 / 0x50F2A9: the patched site ends well before."""
    assert SITE + 5 <= 0x50F296


def test_nothing_else_patches_go_timer(loaded, need_local):
    for s in loaded["sites"]:
        va, ln = s.get("virtual_addr"), s.get("length")
        if va is not None and ln:
            lo, hi = int(va), int(va) + int(ln)
            assert hi <= GO_TIMER or lo >= 0x50F3C4, s.get("id")
    src = need_local(ROOT.parent / "refs" / "thinker" / "src" / "patch.cpp", "the Thinker clone (refs/thinker)").read_text(
        encoding="utf-8", errors="replace")
    for m in re.finditer(r"0x([0-9A-Fa-f]{6})", src):
        va = int(m.group(1), 16)
        assert not (GO_TIMER <= va < 0x50F3C4), f"Thinker patches inside go_timer: {va:#x}"


def test_wired_in():
    assert "InstallViewDragFix();" in INIT
