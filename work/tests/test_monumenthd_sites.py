"""uimod's HD Monument (src/uimod/src/monumenthd.cpp) and movie frame (movieframe.cpp).

monumenthd retargets load_monicons' Buffer_load_pcx (@0x47244B) and MonumentWin_draw's near / far backdrop draws
(@0x4737E9 / @0x4760E2: Buffer_copy_4 in the pristine exe, a call into the mod's .pcave2 resampler in the patched
one). It places its picture by the mod's own Monument laws (scaling_laws.mon_scale_num / mon_s / mon_letterbox /
mon_rect), ported in the source -- never by reading the mod's private state. Those facts and the port are pinned here.
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
import scaling_laws as SL  # noqa: E402

BAK = config.terranx_bak(required=False)
SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
HD = (SRC_DIR / "monumenthd.cpp").read_text(encoding="utf-8")
FRAME = (SRC_DIR / "movieframe.cpp").read_text(encoding="utf-8")
PREFS = (SRC_DIR / "prefs.cpp").read_text(encoding="utf-8")

LOAD_PCX, COPY4 = 0x5D7DE0, 0x5DFF00
SITE_LOAD, SITE_NEAR, SITE_FAR = 0x47244B, 0x4737E9, 0x4760E2
LOAD_MONICONS, MONUMENTWIN_DRAW = 0x472230, 0x4736E0
SCREENS = [(1024, 768), (1280, 1024), (1600, 1200), (1920, 1080), (2560, 1080), (2560, 1440), (3440, 1440),
           (3840, 1080), (3840, 2160)]


def const(name):
    m = re.search(r"\b" + name + r"\s*=\s*(0x[0-9A-Fa-f]+|\d+)", HD)
    assert m, name
    return int(m.group(1), 0)


def call_target(pe, va):
    b = pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, 5)
    assert b[0] == 0xE8, hex(va)
    return va + 5 + struct.unpack("<i", b[1:])[0]


@pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")
def test_sites_in_the_pristine_exe():
    pe = pefile.PE(str(BAK), fast_load=True)
    assert call_target(pe, SITE_LOAD) == LOAD_PCX
    assert call_target(pe, SITE_NEAR) == COPY4 and call_target(pe, SITE_FAR) == COPY4
    assert LOAD_MONICONS < SITE_LOAD < LOAD_MONICONS + 0x300
    assert MONUMENTWIN_DRAW < SITE_NEAR < SITE_FAR < MONUMENTWIN_DRAW + 0x3000
    assert const("kSiteLoad") == SITE_LOAD and const("kSiteNear") == SITE_NEAR and const("kSiteFar") == SITE_FAR
    assert const("kVA_LoadPcx") == LOAD_PCX and const("kVA_Copy4") == COPY4


def test_patched_exe_draws_go_into_the_mods_section():
    """In the patched exe the two backdrop draws call into .pcave2 (the mod's resampler): monumenthd accepts any target
    there and names no cave address of its own."""
    exe = config.terranx(required=False)
    if not exe or not pathlib.Path(exe).exists():
        pytest.skip("patched exe not available")
    pe = pefile.PE(str(exe), fast_load=True)
    cave = [s for s in pe.sections if s.Name.rstrip(b"\0") == b".pcave2"]
    if not cave:
        pytest.skip("this exe has no .pcave2 section")
    lo = pe.OPTIONAL_HEADER.ImageBase + cave[0].VirtualAddress
    hi = lo + cave[0].Misc_VirtualSize
    for site in (SITE_NEAR, SITE_FAR):
        assert lo <= call_target(pe, site) < hi
    assert not re.search(r"0x[Aa]3[0-9A-Fa-f]{4}\b", HD)                         # no .pcave2 address in the source


def test_the_law_constants_are_the_references():
    assert const("kNativeW") == SL.MON_NATIVE_W and const("kNativeH") == SL.MON_NATIVE_H
    assert (const("kOrgX"), const("kOrgY")) == (SL.MON_ORG_X, SL.MON_ORG_Y)
    assert const("kDen") == SL.NATIVE_G
    # the port's formulas, as written in the source
    assert "(2 * v * num + kDen - 1) / (2 * kDen)" in HD                           # half_down(v*num, 16)
    assert "(cw - MonS(kNativeW, num)) >> 1, ly = (ch - MonS(kNativeH, num)) >> 1" in HD


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_port_matches_the_laws(w, h):
    """The C++ port of mon_scale_num / mon_letterbox / mon_rect, re-evaluated here in its own integer form."""
    num = 16 * h // 768 if w * 768 > h * 1024 else 16 * w // 1024
    assert num == SL.mon_scale_num(w, h)
    s = lambda v: (2 * v * num + 16 - 1) // (2 * 16)                              # noqa: E731
    assert all(s(v) == SL.mon_s(v, num) for v in (0, 1, 84, 112, 213, 432, 768, 1024))
    lx, ly = (w - s(1024)) >> 1, (h - s(768)) >> 1
    assert (lx, ly) == SL.mon_letterbox(w, h, num)
    for r in ((213, 202, 813, 562), (432, 287, 591, 380)):
        ox, oy = lx + s(112), ly + s(84)
        port = (ox + s(r[0] - 112), oy + s(r[1] - 84), ox + s(r[2] - 112), oy + s(r[3] - 84))
        assert port == SL.mon_rect(r, num, lx, ly)


def test_native_scale_and_vanilla_are_left_alone():
    assert re.search(r"if \(num <= kDen\) return;", HD)                           # 1024x768: the stock Monument
    assert "the Monument is not scaled in this exe" in HD                        # vanilla exe: not installed
    assert "0x5D7410" not in HD.upper().replace("0X", "0x")                      # no engine Buffer destroyed
    assert "pcx::Decode(" in HD and "photo::Resample(" in HD


def test_movie_frame_safeguards():
    assert "CLSID_WICImagingFactory1" in FRAME                                    # Windows 7 SP1 fallback
    assert re.search(r"kMaxCrop = 0\.12", FRAME) and "cropShare <= kMaxCrop" in FRAME
    assert "catch (const std::bad_alloc&)" in FRAME
    assert "return &g_frame;" in FRAME                                            # decoded once, kept
    assert re.search(r'"HD Monument", &MonumentHdAvailable', PREFS) and re.search(r'"Movie Frame", &MovieFrameAvailable', PREFS)
