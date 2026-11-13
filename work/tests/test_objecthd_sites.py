"""uimod's HD map objects (src/uimod/src/objecthd.cpp, objecthd_table.h), against the pristine and the patched exe.

objecthd draws HD copies of the 96 sprites load_terrain cuts out of TER1.PCX and TER1WRECK.PCX at fixed addresses and
cells, wherever the game draws them. What is pinned here:

- The TABLE (objecthd_table.h, compiled): every row's sprite, file, x, y, size 100x62 and key 0x109 equal to the cut
  load_terrain itself makes -- an emulation of load_terrain on the pristine exe with every callee stubbed records
  each Sprite_extract_2 call -- and nothing load_terrain cuts from those two files is missing from it.
- The INDEX MAP: load_terrain loads both sheets with Buffer_load_pcx(name, 0, 10, 236) (loaded = file + 10 mod 256)
  and turns the background and the slab into the key, Buffer_change_color(0x107 / 0x106 -> 0x109), before EACH of
  its TER1 / TER1WRECK cuts; objecthd maps its packs the same way and never hands one to the engine's decoder.
- The DRAWS: a census of every reference to a table sprite in the exe's code. Outside load_terrain they are the
  terrain pass (MapWin_gen_terrain_poly: 18 Sprite_blit_scaled_core + 3 Sprite_draw_dest calls, all retargeted),
  the Datalinks terraforming page (13 Sprite_draw_2 calls, all retargeted), the tutorial hand-offs (action_terraform,
  Console_give_hints and tut_win pass a sprite to TutWin_tut_map / tut_win, which shows it as the popup's picture,
  BasePop_on_redraw's draw @0x604C72, or as a SpriteBox item, @0x610E7B -- both retargeted), the static Sprite
  constructors / destructors, and three loop bounds of other loaders. Each site is the call objecthd expects on the
  pristine exe AND on the patched exe the patcher bakes from patches.yaml (where 0x604C72 calls thunk_art_draw).
- Units are not in this module (a later PR covers all units).
"""
from __future__ import annotations

import pathlib
import re
import struct
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import capstone  # noqa: E402
import pefile  # noqa: E402
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: E402

import apply_patches as ap  # noqa: E402
import config  # noqa: E402
import cpp_harness  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
HD = (SRC_DIR / "objecthd.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

EXTRACT2, DRAW2, BLIT_CORE, DRAW_DEST = 0x5E39A0, 0x5E4B4A, 0x5E4B9A, 0x5E5833
LOAD_PCX, CHANGE_COLOR = 0x5D7DE0, 0x5DE580
LOAD_TERRAIN, LOAD_TERRAIN_END = 0x451C50, 0x453710        # load_faction_art follows
TERRAIN_PASS, TERRAIN_PASS_END = 0x4632D0, 0x466CA0        # MapWin_gen_terrain_poly
DATALINK, DATALINK_END = 0x431180, 0x431800                # DatalinkWin_draw_terraform
DATALINK_SITES = [0x431321, 0x431355, 0x43138E, 0x4313C2, 0x4313FB, 0x43142F, 0x4314E7, 0x43151B, 0x43154F,
                  0x4315E0, 0x431614, 0x431648, 0x4316A2]
POPUP_ART_SITE, SPRITEBOX_SITE = 0x604C72, 0x610E7B
TUT_MAP, TUT_WIN, SPRITEBOX_SPRITE = 0x4BE650, 0x4BDFE0, 0x6108E0
EXTRACT_SITES = [0x452C07, 0x452D97, 0x453087, 0x453508, 0x453656, 0x4536A8, 0x4524A8, 0x452B8C]
#: where else the code names a table sprite, and why that is not a draw
STATIC_CTORS = (0x44EB00, 0x44F300)                        # the sprites' static constructors / atexit destructors
LOOP_BOUNDS = {0x4519E4, 0x4543D7, 0x4552D8}               # `cmp reg, imm32` ends of other loaders' loops
TUTORIAL = [(0x4BDFE0, 0x4BE650, "tut_win"), (0x4CA500, 0x4CA800, "action_terraform"),
            (0x512F00, 0x513700, "Console_give_hints")]


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


@pytest.fixture(scope="module")
def baked(baked_exe):
    return pefile.PE(str(baked_exe), fast_load=True)


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def target(pe, site):
    b = rd(pe, site, 5)
    return site + 5 + struct.unpack("<i", b[1:])[0] if b[0] == 0xE8 else None


def calls(pe, lo, hi, tgt):
    d = rd(pe, lo, hi - lo)
    return [lo + i for i in range(len(d) - 4)
            if d[i] == 0xE8 and lo + i + 5 + struct.unpack("<i", d[i + 1:i + 5])[0] == tgt]


def const(name):
    m = re.search(r"\b" + name + r"\s*=\s*(0x[0-9A-Fa-f]+|\d+)", HD)
    assert m, name
    return int(m.group(1), 0)


# ---- the table, against load_terrain's own cuts --------------------------------------------------------------------

@pytest.fixture(scope="module")
def table():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    exe = cpp_harness.build(ROOT / "tests" / "objecthd_selftest.cpp", "objecthd_selftest_")
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    rows = [line.split() for line in out.splitlines() if line.strip()]
    return [(int(va, 16), ("TER1.PCX", "TER1WRECK.PCX")[int(s)], int(x), int(y)) for va, s, x, y in rows]


@pytest.fixture(scope="module")
def engine_cuts(pe):
    """Every Sprite_extract_2 load_terrain makes: (sprite, file, x, y, w, h, key), callees stubbed by their own RET."""
    ib = pe.OPTIONAL_HEADER.ImageBase
    img = pe.get_memory_mapped_image()
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for s in pe.sections:
        mu.mem_map(ib + s.VirtualAddress, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
        mu.mem_write(ib + s.VirtualAddress, s.get_data())
    stack, ret_va = 0x0FF00000, 0x0E000000
    mu.mem_map(stack - 0x100000, 0x200000)
    mu.mem_map(ret_va, 0x1000)
    mu.mem_map(0, 0x1000)                                  # a stubbed callee's 0 result read as a pointer
    mu.mem_write(ret_va, b"\xF4")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    callees = {int(i.op_str, 16) for i in md.disasm(img[LOAD_TERRAIN - ib:LOAD_TERRAIN_END - ib], LOAD_TERRAIN)
               if i.mnemonic == "call" and i.op_str.startswith("0x")}

    def ret_imm(fn):
        for i in md.disasm(img[fn - ib:fn - ib + 0x3000], fn):
            if i.mnemonic == "ret":
                return int(i.op_str, 16) if i.op_str else 0
        raise AssertionError(hex(fn))

    stub = {c: ret_imm(c) for c in callees}
    state = {"file": None, "recolour": 0}
    cuts = []

    def hook(uc, addr, _size, _ud):
        if addr not in stub:
            return
        esp = uc.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<8I", uc.mem_read(esp + 4, 32))
        if addr == LOAD_PCX:
            state["file"] = bytes(uc.mem_read(args[0], 32)).split(b"\0")[0].decode("latin-1").upper()
            state["load_args"] = args[1:4]
        elif addr == CHANGE_COLOR:
            state["recolour"] |= {(0x107, 0x109): 1, (0x106, 0x109): 2}.get(args[:2], 0)
        elif addr == EXTRACT2:
            cuts.append((uc.reg_read(UC_X86_REG_ECX), state["file"], *args[2:6], args[1], state["recolour"],
                         state["load_args"]))
        uc.reg_write(UC_X86_REG_EAX, 0)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + stub[addr])
        uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(esp, 4))[0])

    mu.hook_add(UC_HOOK_CODE, hook)
    mu.mem_write(stack, struct.pack("<I", ret_va))
    mu.reg_write(UC_X86_REG_ESP, stack)
    mu.emu_start(LOAD_TERRAIN, ret_va, count=5_000_000)
    return cuts


def test_the_table_is_load_terrains_cuts(table, engine_cuts):
    ours = [c for c in engine_cuts if c[1] in ("TER1.PCX", "TER1WRECK.PCX")]
    assert len(ours) == 96 and len(table) == 96
    assert all((w, h, key, rec, load) == (100, 62, 0x109, 3, (0, 10, 236)) for *_, w, h, key, rec, load in ours), \
        "100x62, key 0x109, loaded with Buffer_load_pcx(name, 0, 10, 236), after both recolours (background, slab)"
    assert sorted(table) == sorted((spr, f, x, y) for spr, f, x, y, *_ in ours)
    assert len({spr for spr, *_ in table}) == 96


def test_the_index_map_is_load_terrains():
    assert const("kLoadShift") == 10 and const("kKeyIndex") == 9
    assert const("kBgIndex") == 0x107 - 0x100 and const("kSlabIndex") == 0x106 - 0x100 and const("kKey") == 0x109
    assert "g_map[i] = v == kBgIndex || v == kSlabIndex ? static_cast<uint8_t>(kKeyIndex) : v;" in HD
    assert "kVA_LoadPcx" not in HD and "0x5D7DE0" not in HD.upper().replace("0X", "0x")   # packs never meet it
    assert "hdpack::Load(&g_pack[sheet], path, kSheetW * kMaster, kSheetH * kMaster, pal)" in HD
    assert "hdpack::ReadPalette(stock, pal)" in HD                       # against the stock sheet's own palette


def test_extract_sites_prove_the_table(pe):
    assert [s for s in EXTRACT_SITES if target(pe, s) != EXTRACT2] == []
    assert re.search(r"kExtractSites\[\] = \{([^}]*)\}", HD).group(1).replace(" ", "").replace("\n", "") == \
        ",".join(f"0x{s:X}" for s in EXTRACT_SITES)


# ---- the draws -------------------------------------------------------------------------------------------------------

def test_census_every_reference_is_a_cut_a_hooked_draw_or_a_hand_off(pe, table):
    """Every imm32 in the code that names a table sprite (or a field of one) lies in load_terrain, the terrain pass,
    the Datalinks page, a tutorial hand-off, the static constructors, or is a known loop bound."""
    text = next(s for s in pe.sections if s.Name.startswith(b".text"))
    ib = pe.OPTIONAL_HEADER.ImageBase
    lo, data = ib + text.VirtualAddress, text.get_data()
    where = {}
    for spr, *_ in table:
        for k in range(0, 0x2C, 4):
            pat, o = struct.pack("<I", spr + k), -1
            while (o := data.find(pat, o + 1)) >= 0:
                where[lo + o] = spr
    regions = [(LOAD_TERRAIN, LOAD_TERRAIN_END), (TERRAIN_PASS, TERRAIN_PASS_END), (DATALINK, DATALINK_END),
               STATIC_CTORS] + [(a, b) for a, b, _ in TUTORIAL]
    stray = [hex(a) for a in where if not any(a0 <= a < a1 for a0, a1 in regions) and a not in LOOP_BOUNDS]
    assert stray == [], "a table sprite referenced outside every known cut / draw / hand-off"
    for a, b, name in TUTORIAL:
        assert any(a <= r < b for r in where), name


def test_tutorial_hand_offs_reach_the_two_hooked_draws(pe):
    """action_terraform / Console_give_hints pass their sprite to TutWin_tut_map, which calls tut_win; tut_win shows
    it as the popup's picture ([popup+0x2144], drawn by BasePop_on_redraw @0x604C72 from that field) or adds it to
    the popup's SpriteBox (SpriteBox_sprite; its items are drawn @0x610E7B)."""
    for a, b, name in TUTORIAL[1:]:
        assert calls(pe, a, b, TUT_MAP), name
    assert calls(pe, TUT_MAP, TUT_MAP + 0x180, TUT_WIN)
    assert bytes.fromhex("8986442100") in rd(pe, TUT_WIN, 0x2C0)           # mov [esi+0x2144], eax
    assert calls(pe, TUT_WIN, TUT_MAP, SPRITEBOX_SPRITE)
    assert rd(pe, POPUP_ART_SITE - 0x17, 6) == bytes.fromhex("8B8E44210000")   # mov ecx, [esi+0x2144]
    assert target(pe, POPUP_ART_SITE) == DRAW2 and target(pe, SPRITEBOX_SITE) == DRAW2


@pytest.mark.parametrize("which", ["pristine", "patched"])
def test_every_draw_site_is_the_call_objecthd_expects(pe, baked, symtab, which):
    img = pe if which == "pristine" else baked
    assert len(calls(img, TERRAIN_PASS, TERRAIN_PASS_END, BLIT_CORE)) == const("kBlitCoreCalls") == 18
    assert len(calls(img, TERRAIN_PASS, TERRAIN_PASS_END, DRAW_DEST)) == const("kDrawDestCalls") == 3
    assert calls(img, DATALINK, DATALINK_END, DRAW2) == DATALINK_SITES
    assert target(img, SPRITEBOX_SITE) == DRAW2
    art = symtab["thunk_art_draw"]
    assert art == const("kVA_ArtDraw")
    assert target(img, POPUP_ART_SITE) == (DRAW2 if which == "pristine" else art)


def test_each_datalinks_draw_is_of_a_table_sprite(pe, table):
    sprites = {spr for spr, *_ in table}
    for site in DATALINK_SITES:
        b = rd(pe, site - 5, 5)
        assert b[0] == 0xB9 and struct.unpack("<I", b[1:])[0] in sprites, hex(site)   # mov ecx, <sprite>
    assert re.search(r"kDatalinkSites\[\] = \{([^}]*)\}", HD).group(1).replace(" ", "").replace("\n", "") == \
        ",".join(f"0x{s:X}" for s in DATALINK_SITES)


def test_no_patch_site_overlaps_a_hooked_call():
    """patches.yaml writes none of the 36 E8s objecthd retargets (0x604C72 is re-pointed by the patcher, at thunk_art_draw,
    which objecthd chains to: only its rel32 changes, never its opcode)."""
    sites, _g, _c, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    assert len(sites) > 1000
    ours = DATALINK_SITES + [SPRITEBOX_SITE] + EXTRACT_SITES
    span = {s["id"]: s.get("length") or len(s.get("original_bytes", "").split()) or 5 for s in sites}
    hits = [(s["id"], hex(s["virtual_addr"])) for s in sites for o in ours
            if s["virtual_addr"] < o + 5 and o < s["virtual_addr"] + span[s["id"]]]
    assert hits == []
    # the popup picture's E8 is the patcher's: re-pointed only (opcode kept), so objecthd's byte check sees a call
    art = [s for s in sites if s["virtual_addr"] <= POPUP_ART_SITE < s["virtual_addr"] + span[s["id"]]]
    assert len(art) == 1 and art[0]["virtual_addr"] == POPUP_ART_SITE and art[0]["new_bytes"].startswith("E8")


def test_source_draw_sites_and_units():
    assert const("kVA_Draw2") == DRAW2 and const("kVA_BlitCore") == BLIT_CORE and const("kVA_DrawDest") == DRAW_DEST
    assert const("kPopupArtSite") == POPUP_ART_SITE and const("kSpriteBoxSite") == SPRITEBOX_SITE
    assert const("kTerrainLo") == TERRAIN_PASS and const("kTerrainHi") == TERRAIN_PASS_END
    assert "units_x8" not in HD and "UNITS" not in HD                   # native life left for the units PR
    assert "0x5598F9" not in HD.upper().replace("0X", "0x") and "load_units" not in HD
    assert "PrefsTabInstalled()" in HD and "InstallObjectHd();" in INIT


def test_engine_addresses_are_the_ones_basehd_pins():
    """objecthd uses the engine functions, globals and Buffer fields basehd uses; test_basehd_sites.py pins each of
    them against the exe, so here they must be the same values."""
    bh = (SRC_DIR / "basehd.cpp").read_text(encoding="utf-8")
    for name in ("kVA_Extract2", "kVA_DrawDest", "kVA_SpriteClose", "kVA_BufferCtor", "kVA_BufferInit",
                 "kVA_ScaleNum", "kVA_ScaleDen", "kVA_MainPalette", "kVA_DrawMap", "kVA_StatusWinRedraw",
                 "kVA_StatusWin", "kVA_GraphicWinRedraw", "kVA_BaseWin", "kBufData", "kBufBits", "kBufW",
                 "kBufColors", "kBufPitch", "kBufSize"):
        m = re.search(r"\b" + name + r"\s*=\s*(0x[0-9A-Fa-f]+|\d+)", bh)
        assert m and const(name) == int(m.group(1), 0), name


def test_draw_dest_takes_the_unscaled_branch_when_num_equals_den(pe):
    want = (bytes.fromhex("8B0D") + struct.pack("<I", 0x696D18) + bytes.fromhex("3B0D") + struct.pack("<I", 0x696D1C)
            + b"\x74")
    assert rd(pe, 0x5E5864, len(want)) == want
    assert "*num = ScaleDen();" in HD and not re.search(r"\*den\s*=", HD)
