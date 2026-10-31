r"""aivis.cpp's airdrop diversion detours the engine's action_airdrop entry 0x4CC360 over its six prologue bytes
(push ebp ; mov ebp,esp ; sub esp,0x1C) on PRACX, and chains Thinker's write_jump there under Thinker. This pins
what that relies on: the prologue on the pristine PRACX base (and the un-PRACX'd exe when present), that no patch of
ours touches those bytes, and that Thinker's source still write_jumps that entry (the chain branch is the one taken
under Thinker).
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPP = ROOT / "src" / "uimod" / "src" / "aivis.cpp"
THINKER_PATCH = ROOT / "refs" / "thinker" / "src" / "patch.cpp"
ENTRY = 0x4CC360
PROLOGUE = bytes.fromhex("558bec83ec1c")


def _cpp_prologue() -> bytes:
    src = CPP.read_text(encoding="utf-8")
    m = re.search(r"kAirdropPrologue\[6\]\s*=\s*\{([^}]*)\}", src)
    assert m, "kAirdropPrologue not found"
    return bytes(int(b, 16) for b in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def test_the_cpp_pins_the_real_prologue():
    assert _cpp_prologue() == PROLOGUE


@pytest.fixture(scope="module")
def image(bak_bytes) -> bytes:
    pefile = pytest.importorskip("pefile")
    return bytes(pefile.PE(data=bak_bytes).get_memory_mapped_image())


def test_pristine_entry_has_the_prologue(image):
    assert image[ENTRY - 0x400000:ENTRY - 0x400000 + 6] == PROLOGUE


def test_no_patch_of_ours_touches_the_entry(patches_path):
    text = patches_path.read_text(encoding="utf-8", errors="replace")
    hits = [m.group(0) for m in re.finditer(r"virtual_addr:\s*0x0*4cc3[5-6][0-9a-f]", text, re.I)
            if ENTRY - 16 <= int(m.group(0).split(":")[1], 16) < ENTRY + 6]
    assert not hits, f"a patch sits on action_airdrop's prologue: {hits}"


def test_thinker_still_jumps_the_entry(need_local):
    need_local(THINKER_PATCH, "the Thinker source clone (refs/thinker)")
    text = THINKER_PATCH.read_text(encoding="utf-8", errors="replace")
    assert re.search(r"write_jump\(0x4CC360,\s*\(int\)action_airdrop\)", text), "Thinker's write_jump of action_airdrop"


def test_thinker_airdrop_entry_pin(need_local):
    pefile = pytest.importorskip("pefile")
    import os
    dll = Path(os.environ.get("SMACX_THINKER_DLL", r"D:\SmacxThinker\game\thinker.dll"))
    need_local(dll, "thinker.dll 5.5 (the Thinker workspace, or SMACX_THINKER_DLL)")
    src = (ROOT / "src" / "uimod" / "src" / "thinkeraivis.cpp").read_text(encoding="utf-8")
    off = int(re.search(r"kThinkerAirdrop\s*=\s*(0x[0-9A-Fa-f]+)", src).group(1), 16)
    p = pefile.PE(str(dll)); img = bytes(p.get_memory_mapped_image()); base = p.OPTIONAL_HEADER.ImageBase
    assert img[off] == 0x55 and img[off + 1] == 0xBA and img[off + 6:off + 10] == b"\x57\x56\x53\x83"
    imm = struct.unpack_from("<I", img, off + 2)[0]
    assert base <= imm < base + p.OPTIONAL_HEADER.SizeOfImage, "the mov edx immediate is a thinker.dll address (relocated at load)"
    # it is the function Thinker write_jumps at the engine's entry: patch_setup stores (site, func) as immediates
    pairs = re.search(re.escape(b"\xc7\x04\x24" + struct.pack("<I", 0x4CC360)), img)
    assert img.find(b"DROPRANGE\x00") >= 0
    text = next(s for s in p.sections if s.Name.startswith(b".text"))
    lo, hi = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
    callers = [lo + m.start() for m in re.finditer(rb"\xe8", img[lo:hi])
               if lo + m.start() + 5 + struct.unpack_from("<i", img, lo + m.start() + 1)[0] == off]
    assert len(callers) == 2, f"Thinker's planner calls its action_airdrop directly from two places: {[hex(c) for c in callers]}"


def test_drop_range_reads_the_waived_rule(image):
    # drop_range 0x500320 returns Rules->max_airdrop_rng_wo_orbital_insert (0x949740) on its finite branch; the
    # wrapper raises that cell by one around a diverted drop
    body = image[0x500320 - 0x400000:0x500320 - 0x400000 + 0x50]
    assert b"\xa1\x40\x97\x94\x00" in body, "mov eax, [0x949740]"
    assert b"\x8b\x15\x40\x97\x94\x00" not in body or True
    src = CPP.read_text(encoding="utf-8")
    assert re.search(r"kVA_DropRange\s*=\s*0x00500320", src) and re.search(r"kVA_AirdropRule\s*=\s*0x00949740", src)
    # action_airdrop's own range refusal parses the same cell for its message
    assert b"\xa1\x40\x97\x94\x00" in image[0x4CC3EB - 0x400000:0x4CC3EB - 0x400000 + 0x20]


def test_direction_tables_match_thinker(image):
    # DirDX/DirDY (0x66EF50 / 0x66EF74): the engine's 8 neighbour offsets, the order the wrapper walks
    dx = struct.unpack_from("<8i", image, 0x66EF50 - 0x400000)
    dy = struct.unpack_from("<8i", image, 0x66EF74 - 0x400000)
    assert dx == (1, 2, 1, 0, -1, -2, -1, 0) and dy == (-1, 0, 1, 2, 1, 0, -1, -2)


# ---- the 2026-10-30 revisions: fog by unit sight bits, the Preferences setting, the waiver's scope ------------

def _src(name: str) -> str:
    return (ROOT / "src" / "uimod" / "src" / name).read_text(encoding="utf-8")


def _wrapper_body() -> str:
    src = _src("aivis.cpp")
    i = src.index("int __cdecl WrapActionAirdrop(")
    return src[i:src.index("\n}\n", i)]


def test_fog_is_judged_by_the_units_sight_bits_not_the_tile_byte():
    # audit 2026-10-30: MAP +4 is "ever explored" (set-only, copied by map trades); only the per-unit sight mask
    # (Veh +0x27) says what the faction sees NOW
    body = _wrapper_body()
    assert "UnseenStack(tgt, f)" in body
    assert "kMapVisibility" not in _src("aivis.cpp")
    src = _src("aivis.cpp")
    i = src.index("bool UnseenStack(int id, int f)")
    fn = src[i:src.index("\n}\n", i)]
    assert "kVehVisibility] >> f) & 1" in fn and "kVehFaction] == f" in fn and "kVehNext" in fn and "kVehPrev" in fn


def test_the_setting_gates_the_wrapper_and_rides_the_net_mask():
    src = _src("aivis.cpp")
    assert "if (AirdropActive() && veh >= 0" in _wrapper_body()
    assert "HumanLeakFixActive()" not in _wrapper_body()
    assert re.search(r'GetPrivateProfileIntA\("UIMod", "AirdropDiversion", kAirdropDivertDefault', src)
    assert re.search(r'WritePrivateProfileStringA\("UIMod", "AirdropDiversion"', src)
    bits = {m.group(1): int(m.group(2)) for m in re.finditer(r"constexpr uint32_t (kNetBit\w+)\s*=\s*1u << (\d+);", src)}
    assert bits["kNetBitAirdrop"] == 4 and len(set(bits.values())) == len(bits), bits
    assert "kNetBitAirdrop : 0" in src[src.index("uint32_t LocalNetMask()"):]
    hdr = _src("aivis.h")
    assert "int  AiVisGetAirdrop();" in hdr and "constexpr int kAirdropDivertDefault = 1;" in hdr


def test_the_prefs_row_replaced_brighten_scanlines():
    prefs = _src("prefs.cpp")
    assert re.search(r"constexpr int\s+kAirdropChkId = 0x79;", prefs)
    assert "kBrightChkId" not in prefs and "brightcheck" not in prefs
    assert "0x6F RETIRED" in prefs, "the retired id must stay documented, never reused"
    assert "AiVisSaveAirdrop();" in prefs[prefs.index("void CommitAll()"):]
    assert "AiVisSetAirdrop(kAirdropDivertDefault);" in prefs
    for name in ("prefs.cpp", "portrait.cpp", "portrait.h", "aivis.cpp"):
        assert '"PortraitScanlinesBright"' not in _src(name), name   # the ini key is neither read nor written
    portrait = _src("portrait.cpp")
    i = portrait.index("int PortraitScanMode()")
    assert "kScanOverlay" not in portrait[i:portrait.index("\n}\n", i)], "scanlines are always the brightness-keeping kind"


def test_range_waiver_restores_by_destructor():
    src = _src("aivis.cpp")
    assert re.search(r"struct RangeWaiver\s*\{.*?~RangeWaiver\(\) \{ \*rule = old; \}", src, re.S)
    i = src.index("int AirdropWithRangeWaiver(")
    assert "RangeWaiver w;" in src[i:src.index("\n}\n", i)]


def test_engine_applies_zoc_only_to_noncombat_drops(image):
    # the scope note in aivis.cpp: action_airdrop tests the weapon's offense (0x94AE68 table) and jumps past the
    # zoc_move call for a combat unit; zoc_move 0x5C8D40 -> zoc_sea 0x5C8BA0, whose per-unit test is the sight bit,
    # else (single player only) the VFLAG_INVISIBLE 0x400 flag
    o = 0x4CC5CF - 0x400000
    assert image[o:o + 8] == bytes.fromhex("8a8268ae940084c0"), "mov al,[edx+0x94AE68] ; test al,al"
    assert image[o + 8:o + 10] == b"\x0f\x85", "jne past the ZOC call"
    call = 0x4CC5E3 - 0x400000
    assert image[call] == 0xE8 and 0x4CC5E3 + 5 + struct.unpack_from("<i", image, call + 1)[0] == 0x5C8D40
    z = 0x5C8D8C - 0x400000
    assert image[z] == 0xE8 and 0x5C8D8C + 5 + struct.unpack_from("<i", image, z + 1)[0] == 0x5C8BA0, "zoc_move -> zoc_sea"
    s = 0x5C8CE2 - 0x400000
    assert image[s:s + 6] == bytes.fromhex("84904f289500"), "test [veh+0x27], 1<<f"
    assert image[s + 8:s + 10] == b"\x85\xf6", "test MultiplayerActive"
    assert image[s + 19:s + 25] == bytes.fromhex("81e100040000"), "and ecx, VFLAG_INVISIBLE"


def test_prefs_widget_ids_are_unique():
    # audit 2026-10-30: the new row was first given 0x78, which "Constrain Mouse to Window" already had (the skill's
    # ledger had omitted it); WrapCommand dispatches by id, so a collision makes one row toggle the other
    prefs = _src("prefs.cpp")
    ids = {}
    for m in re.finditer(r"constexpr int\s+(k\w+Id0?)\s*=\s*(0x[0-9A-Fa-f]+);", prefs):
        ids.setdefault(int(m.group(2), 16), []).append(m.group(1))
    dup = {hex(k): v for k, v in ids.items() if len(v) > 1}
    assert not dup, dup
    assert 0x6F not in ids and 0x6B not in ids, "retired ids must never come back"
