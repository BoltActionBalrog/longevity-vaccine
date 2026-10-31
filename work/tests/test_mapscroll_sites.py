"""mapscroll.cpp (smooth map scrolling under PRACX): the engine facts and the prax.dll facts it binds to, against
the pristine exe and the stock + live prax.dll."""
from __future__ import annotations

import hashlib
import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pefile  # noqa: E402

import config  # noqa: E402

SRC = (ROOT.parent / "src" / "uimod" / "src" / "mapscroll.cpp").read_text(encoding="utf-8")
PRAX_BASE = 0x10000000


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(config.terranx_bak(required=True)))


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def call_target(pe, va):
    assert rd(pe, va, 1) == b"\xE8"
    return (va + 5 + struct.unpack("<i", rd(pe, va + 1, 4))[0]) & 0xFFFFFFFF


def cpp_bytes(name):
    m = re.search(name + r"\[[^\]]*\]\s*=\s*\{([^}]*)\}", SRC)
    assert m, name
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def test_engine_sites(pe):
    assert rd(pe, 0x46A93B, 5) == cpp_bytes("kSelfBlitBytes") and call_target(pe, 0x46A93B) == 0x5DFF00
    assert rd(pe, 0x46A55D, 8) == cpp_bytes("kGateBytes")
    assert rd(pe, 0x469CA0, 6) == cpp_bytes("kGenMapPrologue")
    assert call_target(pe, 0x46ABD1) == 0x469CA0 and call_target(pe, 0x46A5A9) == 0x462980
    # the functions the step calls (Bind() checks these prologues at runtime too)
    assert rd(pe, 0x5D5440, 4) == cpp_bytes("kFill3Pro") == bytes.fromhex("8B442414")      # GraphicWin_fill_3 reads its 5th arg
    assert rd(pe, 0x5D8000, 3) == cpp_bytes("kSetClipPro") == bytes.fromhex("83EC40")      # Buffer_set_clip
    assert rd(pe, 0x4C3EC0, 5) == cpp_bytes("kWorldWinPro") == bytes.fromhex("A16C1E6900") # WorldWin_on_redraw entry (plain)
    # MapWin_set_center (PRACX's pfncMoveMap, wrapped for the settling draw) skips draw_map when the centre is
    # unchanged: cmp edx,[esi+0x1DD9C]; jne; mov eax,[ebp-4]; mov ecx,[esi+0x1DDA0]; cmp eax,ecx; je +0x24
    assert rd(pe, 0x46B2B2, 0x17) == bytes.fromhex("8B869CDD0100" "3BD0" "750D" "8B45FC" "8B8EA0DD0100" "3BC1" "7424")
    # tile_to_pixel's fold keeps -MapX/2 (FoldX's tie-break): cmp ecx,eax; jge; add ecx,ebx
    assert rd(pe, 0x462FB6, 6) == bytes.fromhex("3BC8" "7D02" "03CB")
    # calculate_dimensions zeroes the sub-tile offsets at entry (so the old offsets must be read BEFORE it)
    assert rd(pe, 0x462985, 14) == bytes.fromhex("33C9" "898EACDD0100" "898EB0DD0100")   # xor ecx,ecx; mov [esi+0x1DDAC],ecx; mov [esi+0x1DDB0],ecx


# every exe byte Bind() reads at runtime: (va, length)
BIND_EXE_SPANS = [(0x46A55D, 8), (0x46A93B, 5), (0x469CA0, 6), (0x46ABD1, 1), (0x46A5A9, 1),
                  (0x5D5440, 4), (0x5D8000, 3), (0x4C3EC0, 5)]


def test_bind_spans_in_source():
    for va, ln in BIND_EXE_SPANS:
        assert re.search(r"\b0x%X\b" % va, SRC) or re.search(r"\b0x%x\b" % va, SRC), hex(va)


def test_bind_exe_spans_stay_clear_of_the_patcher(loaded):
    """The DLL binds to the PATCHED exe: no patches.yaml site or cave may overwrite a byte Bind() compares
    (MapWin_draw_map.force ends at 0x46A556, postcalc_guard starts at 0x46A5AE -- both adjacent to checked bytes)."""
    sites, caves = loaded["sites"], loaded["caves"]
    spans = []
    for s in sites:
        va, ln = s.get("virtual_addr"), s.get("length")
        if va is not None and ln:
            spans.append((int(va), int(va) + int(ln), s.get("id")))
    for c in caves:
        va, ln = c.get("virtual_addr"), c.get("length")
        if va is not None and ln:
            spans.append((int(va), int(va) + int(ln), c.get("id", "cave")))
    assert spans
    for va, ln in BIND_EXE_SPANS:
        for lo, hi, sid in spans:
            assert va + ln <= lo or va >= hi, f"{sid} {lo:#x}-{hi:#x} overlaps Bind span {va:#x}+{ln}"


def test_field_offsets_in_source():
    for name, val in [("kConCX", "0x1DD9C"), ("kConCY", "0x1DDA0"),
                      ("kConLeft", "0x1DDA4"), ("kConTop", "0x1DDA8"), ("kConOffX", "0x1DDAC"), ("kConOffY", "0x1DDB0"),
                      ("kConStepX", "0x1DDBC"), ("kConStepY", "0x1DDC0"), ("kConZ", "0x1DDC8"), ("kConScrollFlag", "0x21A44"),
                      ("kConXRect", "0x21A48"), ("kConYRect", "0x21A58"), ("kConGWin", "0x23D94"), ("kGWCanvas", "0x444"),
                      ("kPx_fScrolling", "0x4809F"), ("kPx_ScrollOffY", "0x480C8"), ("kPx_ScrollingSet", "0x514F"),
                      ("kPx_OffYRead", "0x4930"), ("kTab_MoveMap", "0x38"), ("kTab_RedrawMap", "0x3C")]:
        assert re.search(name + r"\s*=\s*" + val + r"\b", SRC), name


def _prax_checks(path):
    pe = pefile.PE(str(path))
    def rva(r, n): return pe.get_data(r, n)
    assert rva(0x5E50, 8) == cpp_bytes("kThunkDrawMap")
    assert rva(0x9930, 8) == cpp_bytes("kThunkZoom")
    assert rva(0x5BA0, 6) == cpp_bytes("kDrawMapFnPro")
    # the thunks' jmp targets: PRACXDrawMap +0x5BA0 and PRACXZoomProcessing +0x9600
    assert 0x5E50 + 8 + struct.unpack("<i", rva(0x5E54, 4))[0] == 0x5BA0
    assert 0x9930 + 8 + struct.unpack("<i", rva(0x9934, 4))[0] == 0x9600
    t = rva(0x47000, 0x48)
    assert struct.unpack_from("<I", t, 0x18)[0] == 0x462980 and struct.unpack_from("<I", t, 0x1C)[0] == 0x9156B0
    assert struct.unpack_from("<I", t, 0x38)[0] == 0x46B1F0 and struct.unpack_from("<I", t, 0x3C)[0] == 0x46A550
    assert struct.unpack_from("<I", t, 0x40)[0] == 0x469CA0
    assert struct.unpack("<I", rva(0x470E4, 4))[0] == PRAX_BASE + 0x47000     # m_pAC -> the table (on-disk base)
    # the two PRACX globals the step reads, through DoScroll's own instructions (Bind() compares the operands
    # against the live module base; on disk they carry the preferred base)
    assert rva(0x514F, 7) == cpp_bytes("kScrollingSetOp") + struct.pack("<I", PRAX_BASE + 0x4809F) + b"\x01"   # mov byte [m_fScrolling], 1
    assert rva(0x5734, 7) == cpp_bytes("kScrollingSetOp") + struct.pack("<I", PRAX_BASE + 0x4809F) + b"\x00"   # ... , 0 at the scroll's end
    assert rva(0x4930, 8) == cpp_bytes("kOffYReadOp") + struct.pack("<I", PRAX_BASE + 0x480C8)                 # cvttsd2si edx, [m_dScrollOffsetY]


def test_prax_stock(prax_bak_path):
    _prax_checks(prax_bak_path)


def test_prax_live():
    live = config.game_dir() / "prax.dll"
    if not live.exists():
        pytest.skip("no live prax.dll")
    _prax_checks(live)


def test_table_slot_is_not_touched_by_the_patcher():
    """patches_prax.yaml must not write prax.dll's address table or the two wrapper thunks."""
    import yaml
    from apply_patches import _yaml_load  # the production loader (libyaml)
    doc = _yaml_load((ROOT / "patches" / "patches_prax.yaml").read_text(encoding="utf-8"))
    spans = []
    for sect in ("code_caves", "sites"):
        for item in doc.get(sect, []) or []:
            va, ln = item.get("virtual_addr"), item.get("length")
            if va is not None and ln:
                spans.append((int(va) - PRAX_BASE, int(va) - PRAX_BASE + int(ln)))
    for lo, hi in spans:
        for a, b in ((0x47000, 0x47048), (0x470E4, 0x470E8), (0x5E50, 0x5E58), (0x9930, 0x9938), (0x5BA0, 0x5BA6)):
            assert hi <= a or lo >= b, f"patcher span {lo:#x}-{hi:#x} overlaps {a:#x}"
