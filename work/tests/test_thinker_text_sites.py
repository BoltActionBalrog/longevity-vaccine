r"""src\uimod\src\thinkertext.cpp re-anchors the lines Thinker 5.5 draws into the base screen by swapping Thinker's two
engine text-writer function pointers for caller-aware wrappers, driven by a hand-written table of call sites. This
module checks that table against thinker.dll itself:

  * the PE pin (TimeDateStamp / SizeOfImage) matches;
  * each pointer variable holds the engine writer the table names;
  * every listed site is `call dword ptr [that pointer]` (FF 15 abs32);
  * COMPLETENESS: every such call in .text through either pointer is listed and classified -- an unlisted caller
    would pass through unplaced (or, worse, be a base-screen line left at its native place);
  * the law: the C++ anchor arithmetic is popup_scale_floor (floor(v * g / 16)) from scaling_laws.py, checked on the
    probe-measured anchors at the baseline resolutions.

The DLL lives outside the repo (the Thinker workspace, or SMACX_THINKER_DLL); absent it skips (a failure under
LONGEVITY_REQUIRE_E2E). Cheap: byte scans only.
"""
from __future__ import annotations

import os
import re
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPP = ROOT / "src" / "uimod" / "src" / "thinkertext.cpp"
DEFAULT_DLL = Path(r"D:\SmacxThinker\game\thinker.dll")
sys.path.insert(0, str(ROOT / "work" / "scripts"))
import scaling_laws as L  # noqa: E402


def _const(src: str, name: str) -> int:
    """A hex literal, or a UIMOD_* macro resolved from version.h (the Thinker pin lives there since 2026-10-30)."""
    m = re.search(rf"\b{name}\s*=\s*(0x[0-9A-Fa-f]+|UIMOD_[A-Z_]+)", src)
    assert m, f"{name} not found in thinkertext.cpp"
    val = m.group(1)
    if val.startswith("UIMOD_"):
        hdr = (ROOT / "src" / "uimod" / "src" / "version.h").read_text(encoding="utf-8")
        d = re.search(rf"^\s*#define\s+{val}\s+(0x[0-9A-Fa-f]+)\s*$", hdr, re.M)
        assert d, f"{val} not defined in version.h"
        val = d.group(1)
    return int(val, 16)


@pytest.fixture(scope="module")
def table() -> dict:
    src = CPP.read_text(encoding="utf-8")
    rows = [(int(m.group(1), 16), m.group(2), m.group(3))
            for m in re.finditer(r"\{\s*(0x[0-9A-Fa-f]+),\s*(kPtr\w+),\s*'([SPLN])',\s*\"", src)]
    assert len(rows) == 9, "nine Thinker call sites through the two writer pointers were measured in 5.5"
    return {"stamp": _const(src, "kStamp"), "size": _const(src, "kSizeOfImage"),
            "ptrs": {"kPtrWriteL3": (_const(src, "kPtrWriteL3"), _const(src, "kVA_WriteL3")),
                     "kPtrWriteRightL5": (_const(src, "kPtrWriteRightL5"), _const(src, "kVA_WriteRightL5"))},
            "rows": rows}


@pytest.fixture(scope="module")
def dll(need_local) -> dict:
    pefile = pytest.importorskip("pefile")
    path = Path(os.environ.get("SMACX_THINKER_DLL", str(DEFAULT_DLL)))
    need_local(path, "thinker.dll 5.5 (the Thinker workspace, or SMACX_THINKER_DLL)")
    p = pefile.PE(str(path))
    text = next(s for s in p.sections if s.Name.startswith(b".text"))
    return {"img": bytes(p.get_memory_mapped_image()), "base": p.OPTIONAL_HEADER.ImageBase,
            "stamp": p.FILE_HEADER.TimeDateStamp, "size": p.OPTIONAL_HEADER.SizeOfImage,
            "text": (text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize)}


def test_pe_pin(table, dll):
    assert (dll["stamp"], dll["size"]) == (table["stamp"], table["size"])


def test_pointers_hold_the_engine_writers(table, dll):
    for name, (off, va) in table["ptrs"].items():
        assert struct.unpack_from("<I", dll["img"], off)[0] == va, f"{name} (+{off:X}) does not hold 0x{va:X}"


def test_listed_sites_call_through_the_named_pointer(table, dll):
    for site, ptr, _mode in table["rows"]:
        off = table["ptrs"][ptr][0]
        assert dll["img"][site:site + 6] == b"\xff\x15" + struct.pack("<I", dll["base"] + off), f"+{site:X} is not call [{ptr}]"


def test_table_lists_every_call_through_either_pointer(table, dll):
    lo, hi = dll["text"]
    found = set()
    for name, (off, _va) in table["ptrs"].items():
        pat = re.escape(b"\xff\x15" + struct.pack("<I", dll["base"] + off))
        found |= {lo + m.start() for m in re.finditer(pat, dll["img"][lo:hi])}
    assert found == {site for site, _p, _m in table["rows"]}, (
        f"calls through the writer pointers in the DLL {sorted(f'+{x:X}' for x in found)} != the table's "
        f"{sorted(f'+{s:X}' for s, _p, _m in table['rows'])} -- an unlisted caller is unplaced")


def test_pop_label_format_is_where_the_table_says(dll):
    src = CPP.read_text(encoding="utf-8")
    label, ref = _const(src, "kLabelPopSize"), _const(src, "kLabelPopSizeRef")
    img = dll["img"]
    assert img[label:label + 23] == b"Pop: %d / %d / %d / %d\x00", "label_pop_size's default text (gui.cpp) at +%X" % label
    assert img[ref:ref + 8] == b"\xc7\x44\x24\x08" + struct.pack("<I", dll["base"] + label), "the painter's mov [esp+8], label_pop_size"
    lo, hi = dll["text"]
    refs = [lo + m.start() - 4 for m in re.finditer(re.escape(struct.pack("<I", dll["base"] + label)), img[lo:hi])
            if img[lo + m.start() - 4:lo + m.start()] == b"\xc7\x44\x24\x08"]
    assert refs == [ref], f"the painter's format reference: {[hex(r) for r in refs]}"


def test_modes_are_the_measured_ones(table):
    modes = {site: mode for site, _p, mode in table["rows"]}
    assert modes[0x1466C] == "P", "the eco-damage line arrives with the engine's scaled x,y (our chain)"
    assert modes[0x3E59A] == "L", "the version label is screen-anchored and decided separately"
    assert modes[0x14C9E] == "N", "the Pop: T/W/D/S line is re-anchored AND renumbered with the would-be totals"
    assert sum(1 for m in modes.values() if m in "SN") == 7


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_anchor_law_is_popup_scale_floor(g):
    # the probe-measured native anchors: satellite lines (171, 193/207/221) and the Pop line (690, 381)
    for v in (171, 193, 207, 221, 690, 381, 402, 423, 20, 32):   # 20 / 32 = the version label's margins
        assert (v * g) >> 4 == L.popup_scale_floor(v, g)
    # the 14-px native line step scales with the same factor as the font and the canvas
    assert L.popup_scale_floor(207, g) - L.popup_scale_floor(193, g) in (L.popup_scale_floor(14, g), L.popup_scale_floor(14, g) + 1)
    if g == 16:
        assert L.popup_scale_floor(171, g) == 171   # native: untouched
