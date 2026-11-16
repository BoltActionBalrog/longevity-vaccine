"""uimod's HD terrain textures (src/uimod/src/terrainhd.cpp), against the pristine and the patched exe.

terrainhd retargets load_terrain's 21 Texture_extract_2 calls (19 TEXTURE.PCX cuts + 2 RAINFALL composites) and the
8 calls of MapWin_gen_terrain_poly, rewrites the two UV tables and eight `mov r32, 0x37`, and moves Texture_draw_2's
first six bytes to a trampoline (PRACX's Alt+T overlays are swapped into that function's calls at 0x464215 /
0x464353). What is pinned here, on both images: each list is the exe's complete census of that call / immediate in
its function (load_terrain's one other cut, 0x4523A6, is the 60x60 texture 0x78DD80, left alone); the tables hold
exactly the values the source restores; the engine functions' entry bytes are the source's; nothing in
patches.yaml writes a byte the hook checks or rewrites; the source's constants are these.
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import pefile  # noqa: E402

import apply_patches as ap  # noqa: E402
import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
HD = (SRC_DIR / "terrainhd.cpp").read_text(encoding="utf-8")
PREFS = (SRC_DIR / "prefs.cpp").read_text(encoding="utf-8")

EXTRACT2, TEX_CTOR, TEX_CLOSE, DRAW2 = 0x619710, 0x619650, 0x619690, 0x6233C0
GEN, MEM_ALLOC, FREE = 0x4632D0, 0x5D4510, 0x644EF2
LOAD_TERRAIN, LOAD_TERRAIN_END = 0x451C50, 0x453710
TERRAIN_PASS, TERRAIN_PASS_END = 0x4632D0, 0x466CA0
DATALINK, DATALINK_END = 0x431180, 0x431800
SHEET_CUTS = [0x451D0B, 0x451D27, 0x451D50, 0x451D8F, 0x451DB6, 0x451DE0, 0x451E24, 0x451E86, 0x451EBF, 0x451EE9,
              0x451F32, 0x451F76, 0x451FBF, 0x452000, 0x452030, 0x452081, 0x4520E1, 0x452128, 0x452171]
RAIN_CUTS = [0x4522CA, 0x4522E5]
CUT_60 = 0x4523A6                                          # mov ecx, 0x78DD80 (the 60x60 texture); not hooked
GEN_SITES = [0x40F35F, 0x468C73, 0x46927C, 0x469308, 0x469E47, 0x47130C, 0x4B6B9C, 0x4BDF5C]
UV_IMMS = [0x46485D, 0x4649BB, 0x464AF8, 0x464FD8, 0x465561, 0x465C81, 0x465D43, 0x4311B2]
UV_TABLES = {0x685CA8: 32, 0x686090: 56}
PRACX_SWAP_SITES = [0x464215, 0x464353]
ENGINE_FNS = ("kVA_Extract2", "kVA_TexCtor", "kVA_TexClose", "kVA_MemAlloc", "kVA_Free", "kVA_GenTerrainPoly")
STOCK_UV = {
    0x685CA8: [27, 27, 27, 55, 0, 55, 0, 0, 27, 27, 27, 0, 55, 0, 55, 55, 27, 27, 55, 27, 55, 55, 27, 55, 27, 27, 0, 27,
               0, 0, 27, 0],
    0x686090: [27, 28, 0, 55, 0, 1, 27, 27, 0, 0, 54, 0, 28, 27, 55, 1, 55, 53, 28, 29, 55, 55, 2, 55, 27, 27, 0, 27, 0,
               0, 27, 0, 28, 27, 28, 0, 55, 0, 55, 27, 28, 28, 55, 28, 55, 55, 28, 55, 27, 28, 27, 55, 0, 55, 0, 28],
}


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


@pytest.fixture(scope="module")
def baked(baked_exe):
    return pefile.PE(str(baked_exe), fast_load=True)


@pytest.fixture(params=["pristine", "patched"])
def img(request, pe):
    return pe if request.param == "pristine" else request.getfixturevalue("baked")


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def calls(pe, lo, hi, tgt):
    d = rd(pe, lo, hi - lo)
    return [lo + i for i in range(len(d) - 4)
            if d[i] == 0xE8 and lo + i + 5 + struct.unpack("<i", d[i + 1:i + 5])[0] == tgt]


def text_range(pe):
    s = [s for s in pe.sections if s.Name.rstrip(b"\0") == b".text"][0]
    lo = pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress
    return lo, lo + s.Misc_VirtualSize


def src_list(name):
    m = re.search(name + r"\[\] = \{([^}]*)\}", HD)
    assert m, name
    return [int(v, 0) for v in re.findall(r"0x[0-9A-Fa-f]+", m.group(1))]


def src_const(name):
    m = re.search(r"\b" + name + r"\s*=\s*(0x[0-9A-Fa-f]+)", HD)
    assert m, name
    return int(m.group(1), 0)


def test_load_terrains_cuts_are_the_hooked_21_and_the_60x60(img):
    assert calls(img, LOAD_TERRAIN, LOAD_TERRAIN_END, EXTRACT2) == SHEET_CUTS + RAIN_CUTS + [CUT_60]
    assert rd(img, CUT_60 - 4, 4) == struct.pack("<I", 0x78DD80)          # mov ecx, 0x78DD80
    assert src_list("kExtractSites") == SHEET_CUTS + RAIN_CUTS


def test_every_terrain_pass_call_is_hooked(img):
    lo, hi = text_range(img)
    assert calls(img, lo, hi, GEN) == GEN_SITES
    assert src_list("kGenSites") == GEN_SITES


def test_every_uv_immediate_is_rewritten(img):
    found = []
    for lo, hi in ((TERRAIN_PASS, TERRAIN_PASS_END), (DATALINK, DATALINK_END)):
        d = rd(img, lo, hi - lo)
        found += [lo + i for i in range(len(d) - 4) if 0xB8 <= d[i] <= 0xBF and d[i + 1:i + 5] == b"\x37\0\0\0"]
    assert sorted(found) == sorted(UV_IMMS)
    assert all(rd(img, s, 1)[0] in (0xB8, 0xB9) for s in UV_IMMS)             # the hook's own check
    assert src_list("kUvImmediates") == UV_IMMS


def test_the_uv_tables_are_stock_and_the_sources(img):
    for va, n in UV_TABLES.items():
        assert list(struct.unpack(f"<{n}i", rd(img, va, 4 * n))) == STOCK_UV[va]
    for name, va in (("kUvStock0", 0x685CA8), ("kUvStock1", 0x686090)):
        body = HD.split("int32_t " + name, 1)[1].split("};", 1)[0].split("{", 1)[1]
        assert [int(t) for t in re.findall(r"\d+", body)] == STOCK_UV[va]


def test_engine_entries_are_the_sources(img):
    body = HD.split("const Entry8 kEntries[] = {", 1)[1].split("};", 1)[0]
    rows = re.findall(r"\{\s*(kVA_\w+),\s*\{([^}]*)\}", body)
    assert {r[0] for r in rows} == set(ENGINE_FNS)
    for name, b in rows:
        assert rd(img, src_const(name), 6) == bytes(int(v, 16) for v in b.split(",")), name
    entry = re.search(r"kDraw2Entry\[\] = \{([^}]*)\}", HD).group(1)
    assert rd(img, DRAW2, 6) == bytes(int(v, 16) for v in entry.split(",")) == bytes.fromhex("558BEC83EC78")


def test_pracx_swaps_its_overlays_into_texture_draw_2(pe):
    """PRACX's PRACXDrawTileDraw is patched over these two calls at run time (pracx.cpp: _cx(.., 0x464216 /
    0x464354), the rel32 of each) and ends in a Texture_draw_2 of its own image: the reason the hook detours
    Texture_draw_2's entry instead of these calls."""
    assert calls(pe, TERRAIN_PASS, TERRAIN_PASS_END, DRAW2) == PRACX_SWAP_SITES + [0x4646AE]


def test_no_patch_site_overlaps_what_the_hook_checks_or_writes(pe):
    sites, _g, _c, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    assert len(sites) > 1000
    ours = [(s, 5) for s in SHEET_CUTS + RAIN_CUTS + GEN_SITES + UV_IMMS] + [(DRAW2, 6)]
    ours += [(va, 4 * n) for va, n in UV_TABLES.items()]
    ours += [(src_const(n), 6) for n in ENGINE_FNS]
    span = {s["id"]: s.get("length") or len(s.get("original_bytes", "").split()) or 5 for s in sites}
    hits = [(s["id"], hex(s["virtual_addr"])) for s in sites for o, n in ours
            if s["virtual_addr"] < o + n and o < s["virtual_addr"] + span[s["id"]]]
    assert hits == []


def test_the_hook_gives_bits_the_way_texture_extract_2_does(img):
    """GiveBits stands in for Texture_extract_2 without a Buffer: the engine's own cut allocates a Texture's bits with
    mem_alloc (its only allocation when no TexHeap is passed), frees the old ones with free when +0x6C is 0, and sets
    exactly bits +0, width +4, height +8 and +0x6C; Texture_close frees with the same free. mem_alloc shows a message
    box and exits when malloc returns null, so it never returns null."""
    assert calls(img, EXTRACT2, EXTRACT2 + 0x1C0, MEM_ALLOC) == [0x6197E2]
    assert calls(img, EXTRACT2, EXTRACT2 + 0x1C0, FREE) == [0x61973C]
    assert calls(img, TEX_CLOSE, TEX_CLOSE + 0x3A, FREE) == [0x6196A5]
    import capstone
    from capstone import x86_const as X
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    stores = set()
    for ins in md.disasm(rd(img, EXTRACT2, 0x1C0), EXTRACT2):     # esi = the Texture (mov esi, ecx at 0x61971C)
        if ins.mnemonic == "mov" and ins.operands[0].type == X.X86_OP_MEM and ins.operands[0].mem.base == X.X86_REG_ESI:
            stores.add(ins.operands[0].mem.disp)
        if ins.address >= 0x6198D2 and ins.mnemonic == "ret":
            break
    # bits, width, height, the corner coordinates (+0x0C..+0x68: TexCorners, compared with this code run under
    # emulation in test_terrainhd_cache.py) and the heap flag; nothing else
    assert stores == {0, 4, 8, 0x6C} | set(range(0x0C, 0x6C, 4)), sorted(stores)
    a = rd(img, MEM_ALLOC, 0x2C)
    assert a[0x0F:0x11] == b"\x75\x1A" and a[0x26] == 0xE8                  # jne past the box; exit(4) after it
    assert "GiveBits" in HD and "bufferInit" not in HD and "FillScratch" not in HD


def test_source_constants():
    for name, va in (("kVA_Extract2", EXTRACT2), ("kVA_TexCtor", TEX_CTOR), ("kVA_TexClose", TEX_CLOSE),
                     ("kVA_Draw2", DRAW2), ("kVA_GenTerrainPoly", GEN), ("kVA_MemAlloc", MEM_ALLOC),
                     ("kVA_Free", FREE), ("kVA_LoadingCanvas", 0x798668), ("kVA_ScreenW", 0x9B7B1C),
                     ("kVA_ScreenH", 0x9B7B20)):
        assert src_const(name) == va, name
    assert '"HD Terrain", &TerrainHdAvailable' in PREFS
    assert "texture_x8.pcx" in HD and "texture_x2" not in HD and "texture_x4" not in HD
