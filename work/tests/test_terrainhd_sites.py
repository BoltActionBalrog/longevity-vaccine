"""uimod's HD terrain textures (src/uimod/src/terrainhd.cpp), against the pristine and the patched exe.

terrainhd retargets load_terrain's 22 Texture_extract_2 calls (19 TEXTURE.PCX cuts, 2 RAINFALL composites and the
60x60 territory border 0x78DD80 at 0x4523A6) and the 8 calls of MapWin_gen_terrain_poly, and turns the 100 span
stores of the rasterizers (u, v, du, dv in each of 25 span setups) into calls of stubs that multiply them by the
level for its own textures. What is pinned here, on both images: each list is the exe's complete census of that
call / store; every texture coordinate the hook used to rewrite is stock and untouched; no branch lands inside a
store's bytes and no store runs while a rasterizer borrows esp; the engine functions' entry bytes are the source's;
nothing in patches.yaml writes a byte the hook checks or rewrites; the source's constants
are these. That the stores scale exactly is test_terrainhd_exact.py.
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
GEN, MEM_GET, MEM_FREE = 0x4632D0, 0x5D4510, 0x644EF2
RASTER_LO, RASTER_HI = 0x6198E0, 0x625200                 # the ten rasterizers and their helpers
SPAN_GLOBALS = {0x9BB4F8: "u", 0x9BB53C: "v", 0x9BB4E4: "du", 0x9BB4C8: "dv"}
TEX_BITS = 0x9BB544
LOAD_TERRAIN, LOAD_TERRAIN_END = 0x451C50, 0x453710
TERRAIN_PASS, TERRAIN_PASS_END = 0x4632D0, 0x466CA0
DATALINK, DATALINK_END = 0x431180, 0x431800
SHEET_CUTS = [0x451D0B, 0x451D27, 0x451D50, 0x451D8F, 0x451DB6, 0x451DE0, 0x451E24, 0x451E86, 0x451EBF, 0x451EE9,
              0x451F32, 0x451F76, 0x451FBF, 0x452000, 0x452030, 0x452081, 0x4520E1, 0x452128, 0x452171]
RAIN_CUTS = [0x4522CA, 0x4522E5]
CUT_60 = 0x4523A6                                          # mov ecx, 0x78DD80: the territory border (60x60)
GEN_SITES = [0x40F35F, 0x468C73, 0x46927C, 0x469308, 0x469E47, 0x47130C, 0x4B6B9C, 0x4BDF5C]
UV_IMMS = [0x46485D, 0x4649BB, 0x464AF8, 0x464FD8, 0x465561, 0x465C81, 0x465D43, 0x4311B2]
UV_TABLES = {0x685CA8: 32, 0x686090: 56}
PRACX_SWAP_SITES = [0x464215, 0x464353]
ENGINE_FNS = ("kVA_Extract2", "kVA_MemGet", "kVA_MemFree", "kVA_GenTerrainPoly")
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


def test_load_terrains_cuts_are_all_22_hooked(img):
    """The 19 TEXTURE.PCX cuts, the 2 coast composites and the 60x60 territory border (mov ecx, 0x78DD80)."""
    assert calls(img, LOAD_TERRAIN, LOAD_TERRAIN_END, EXTRACT2) == SHEET_CUTS + RAIN_CUTS + [CUT_60]
    assert rd(img, CUT_60 - 4, 4) == struct.pack("<I", 0x78DD80)
    assert src_list("kExtractSites") == SHEET_CUTS + RAIN_CUTS + [CUT_60]


def test_the_rainfall_code_maps_colour_lists_are_the_sources(img):
    """load_terrain draws the coast composites through the 53 colours at 0x6846F8 and the border through 9 colours it
    writes with `mov byte [ebp - 0x1C + i], c` at 0x452307; the hook builds its code maps with the same lists (and
    turns the RAINFALL art off if they differ)."""
    comp = re.search(r"kCompColours\[53\] = \{([^}]*)\}", HD).group(1)
    assert rd(img, 0x6846F8, 53) == bytes(int(v) for v in re.findall(r"\d+", comp))
    border = re.search(r"kBorderColours\[9\] = \{([^}]*)\}", HD).group(1)
    cols = [int(v, 16) for v in re.findall(r"0x[0-9A-F]+", border)]
    assert rd(img, 0x452307, 36) == b"".join(bytes([0xC6, 0x45, 0xE4 + i, c]) for i, c in enumerate(cols))


def test_every_terrain_pass_call_is_hooked(img):
    lo, hi = text_range(img)
    assert calls(img, lo, hi, GEN) == GEN_SITES
    assert src_list("kGenSites") == GEN_SITES


def test_the_texture_coordinates_stay_stock(img):
    """The UV tables and the 0x37 immediates the first hook rewrote stay as they are: the hook no longer names them."""
    found = []
    for lo, hi in ((TERRAIN_PASS, TERRAIN_PASS_END), (DATALINK, DATALINK_END)):
        d = rd(img, lo, hi - lo)
        found += [lo + i for i in range(len(d) - 4) if 0xB8 <= d[i] <= 0xBF and d[i + 1:i + 5] == b"\x37\0\0\0"]
    assert sorted(found) == sorted(UV_IMMS)
    for va, n in UV_TABLES.items():
        assert list(struct.unpack(f"<{n}i", rd(img, va, 4 * n))) == STOCK_UV[va]
    for name in ("kUvImmediates", "kUvTables", "kUvStock", "WriteUv", "Draw2Hook", "ForeignFor"):
        assert name not in HD, name


def _sweep(img):
    import capstone
    from capstone import x86_const as X
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    ins, a = [], RASTER_LO
    while a < RASTER_HI:
        got = list(md.disasm(rd(img, a, 16), a, 1))
        if not got:
            a += 1
            continue
        ins.append(got[0])
        a += got[0].size
    return ins, X


def test_the_span_stores_are_the_exes_complete_census(img):
    """Every store of a span coordinate in the rasterizers: the row's u (mov [0x9BB4F8], eax), v (mov [0x9BB53C],
    edx / ecx), du and dv (fistp). The only other writes are the clipping pre-step's (add eax, [u]; mov [u], eax and
    add [v], eax), which add the already-scaled du * clip. 25 setups x 4, in kSpanSites order."""
    ins, X = _sweep(img)
    stores, pre = [], 0
    for k, i in enumerate(ins):
        op = i.operands[0] if i.operands else None
        if not (op is not None and op.type == X.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0
                and op.mem.disp in SPAN_GLOBALS and i.mnemonic in ("mov", "fistp", "add", "sub", "fstp")):
            continue
        prev = ins[k - 1]
        if i.mnemonic == "add" or (i.mnemonic == "mov" and prev.mnemonic == "add" and prev.op_str.endswith(
                f"[{op.mem.disp:#x}]")):
            pre += 1
            continue
        stores.append((i.address, SPAN_GLOBALS[op.mem.disp], bytes(i.bytes)))
    assert pre == 50
    assert [a for a, _, _ in stores] == src_list("kSpanSites")
    kinds = [g for _, g, _ in stores]
    assert all(sorted(kinds[i:i + 2]) == ["u", "v"] and kinds[i + 2:i + 4] == ["du", "dv"] for i in range(0, 100, 4))
    assert [i // 4 for i in range(0, 100, 4) if kinds[i] == "v"] == [15, 18]     # v stored before u in two setups
    for a, g, b in stores:
        assert (b[0] == 0xA3 and len(b) == 5) or (b[:2] in (b"\x89\x15", b"\x89\x0D", b"\xDB\x1D") and len(b) == 6), (hex(a), b)
    # each rasterizer sets the drawn texture's bits first: what the stubs decide by
    sets = [i.address for i in ins if i.mnemonic == "mov" and i.operands[0].type == X.X86_OP_MEM
            and i.operands[0].mem.disp == TEX_BITS]
    assert len(sets) == 26


def test_no_branch_lands_inside_a_span_store_and_no_store_runs_on_a_borrowed_stack(img):
    """A stub is reached by a call: the bytes after a store's first one are never a branch target, and no store lies
    between a rasterizer's `mov [0x9BB4AC], esp` (the inner loop borrows esp as its counter) and the `mov esp,
    [0x9BB4AC]` that gives it back."""
    ins, X = _sweep(img)
    lo, hi = text_range(img)
    d = rd(img, lo, hi - lo)
    inside = set()
    for s in src_list("kSpanSites"):
        n = 5 if rd(img, s, 1)[0] == 0xA3 else 6
        inside |= {s + j for j in range(1, n)}
    hits = []
    for i in range(len(d) - 6):
        b = d[i]
        if b in (0xE8, 0xE9):
            t = lo + i + 5 + struct.unpack("<i", d[i + 1:i + 5])[0]
        elif b == 0x0F and 0x80 <= d[i + 1] <= 0x8F:
            t = lo + i + 6 + struct.unpack("<i", d[i + 2:i + 6])[0]
        elif b == 0xEB or 0x70 <= b <= 0x7F:
            t = lo + i + 2 + struct.unpack("<b", d[i + 1:i + 2])[0]
        else:
            continue
        if t in inside:
            hits.append((lo + i, t))
    real = {i.address for i in ins}
    assert [h for h in hits if h[0] in real] == []
    borrowed, bad = False, []
    sites = set(src_list("kSpanSites"))
    for i in ins:
        if i.mnemonic == "mov" and i.op_str == "dword ptr [0x9bb4ac], esp":
            borrowed = True
        elif i.mnemonic == "mov" and i.op_str == "esp, dword ptr [0x9bb4ac]":
            borrowed = False
        if i.address in sites and borrowed:
            bad.append(hex(i.address))
    assert bad == []


def test_engine_entries_are_the_sources(img):
    body = HD.split("const Entry8 kEntries[] = {", 1)[1].split("};", 1)[0]
    rows = re.findall(r"\{\s*(kVA_\w+),\s*\{([^}]*)\}", body)
    assert {r[0] for r in rows} == set(ENGINE_FNS)
    for name, b in rows:
        assert rd(img, src_const(name), 6) == bytes(int(v, 16) for v in b.split(",")), name


def test_pracx_swaps_its_overlays_into_texture_draw_2(pe):
    """PRACX's PRACXDrawTileDraw is patched over these two calls at run time (pracx.cpp: _cx(.., 0x464216 /
    0x464354), the rel32 of each) and draws its own 56x56 image through Texture_draw_2: not ours, so the span stubs
    multiply its coordinates by 1 and it draws natively. The hook writes neither call."""
    assert calls(pe, TERRAIN_PASS, TERRAIN_PASS_END, DRAW2) == PRACX_SWAP_SITES + [0x4646AE]


def test_no_patch_site_overlaps_what_the_hook_checks_or_writes(pe):
    sites, _g, _c, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    assert len(sites) > 1000
    ours = [(s, 5) for s in SHEET_CUTS + RAIN_CUTS + [CUT_60] + GEN_SITES] + [(s, 6) for s in src_list("kSpanSites")]
    ours += [(0x6846F8, 53), (0x452307, 36)]                       # the RAINFALL colour lists the hook checks
    ours += [(src_const(n), 6) for n in ENGINE_FNS]
    span = {s["id"]: s.get("length") or len(s.get("original_bytes", "").split()) or 5 for s in sites}
    hits = [(s["id"], hex(s["virtual_addr"])) for s in sites for o, n in ours
            if s["virtual_addr"] < o + n and o < s["virtual_addr"] + span[s["id"]]]
    assert hits == []


def test_the_hook_gives_bits_the_way_texture_extract_2_does(img):
    """GiveBits stands in for Texture_extract_2 without a Buffer: the engine's own cut allocates a Texture's bits with
    mem_get (its only allocation when no TexHeap is passed), frees the old ones with mem_free when +0x6C is 0, and sets
    exactly bits +0, width +4, height +8 and +0x6C; Texture_close frees with the same mem_free. mem_get shows a message
    box and exits when malloc returns null, so it never returns null."""
    assert calls(img, EXTRACT2, EXTRACT2 + 0x1C0, MEM_GET) == [0x6197E2]
    assert calls(img, EXTRACT2, EXTRACT2 + 0x1C0, MEM_FREE) == [0x61973C]
    assert calls(img, TEX_CLOSE, TEX_CLOSE + 0x3A, MEM_FREE) == [0x6196A5]
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
    a = rd(img, MEM_GET, 0x2C)
    assert a[0x0F:0x11] == b"\x75\x1A" and a[0x26] == 0xE8                  # jne past the box; exit(4) after it
    assert "GiveBits" in HD and "bufferInit" not in HD and "FillScratch" not in HD


def test_source_constants():
    for name, va in (("kVA_Extract2", EXTRACT2), ("kVA_GenTerrainPoly", GEN), ("kVA_MemGet", MEM_GET),
                     ("kVA_MemFree", MEM_FREE), ("kVA_LoadingCanvas", 0x798668), ("kVA_ScreenW", 0x9B7B1C),
                     ("kVA_ScreenH", 0x9B7B20), ("kVA_TexBits", TEX_BITS)):
        assert src_const(name) == va, name
    assert '"HD Terrain", &TerrainHdAvailable' in PREFS
    assert "texture_x8.pcx" in HD and "texture_x2" not in HD and "texture_x4" not in HD
