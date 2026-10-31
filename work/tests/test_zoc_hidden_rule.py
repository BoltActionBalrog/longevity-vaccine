r"""The hidden-unit zone-of-control rule (user, 2026-10-30): a HUMAN faction's unit that is hidden-kind (Cloaking Device,
Deep Pressure Hull, scenario-invisible) and not yet seen by faction X exerts no zone of control on X, human or AI; once
seen it exerts as before. aivis.cpp entry-detours the engine's zoc_any / zoc_veh / zoc_sea (the original answers first,
a nonzero answer is recomputed without the exempt units); thinkeraivis.cpp detours Thinker 5.5's own ports
(path.cpp mod_zoc_any / _veh / _sea) onto the same adjustment.

Pinned here:
  * the engine entries hold the prologues the C++ relocates, no patch of ours sits on them, zoc_move still calls
    zoc_sea, and each function's return shape is what the ports reproduce (owner+1 / max owner+1 / owner+1);
  * the Thinker offsets hold their heads, the NearbyTiles immediates point inside the image, mod_zoc_move calls
    mod_zoc_sea, order_veh's gate calls mod_zoc_move twice in a row, mod_enemy_veh's skip test calls mod_zoc_any;
  * the source shape: the exemption is hidden-kind AND unseen AND human-owned, every hook asks the original first,
    the adjustment keeps a zero and keeps everything while the setting is off, the Thinker half uses kinds 0/1/2.
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "uimod" / "src"
ZOC_ANY, ZOC_VEH, ZOC_SEA, ZOC_MOVE = 0x5C89F0, 0x5C8AC0, 0x5C8BA0, 0x5C8D40
ENGINE_VEH_AT = 0x5BFE90


def _src(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def _bytes_array(src: str, name: str) -> bytes:
    m = re.search(rf"{name}\[\d*\]\s*=\s*\{{([^}}]*)\}}", src)
    assert m, f"{name} not found"
    return bytes(int(b, 16) for b in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def _const(src: str, name: str) -> int:
    m = re.search(rf"\b{name}\s*=\s*(0x[0-9A-Fa-f]+)", src)
    assert m, f"{name} not found"
    return int(m.group(1), 16)


@pytest.fixture(scope="module")
def image(bak_bytes) -> bytes:
    pefile = pytest.importorskip("pefile")
    return bytes(pefile.PE(data=bak_bytes).get_memory_mapped_image())


def _call_target(img: bytes, site: int) -> int | None:
    if img[site] != 0xE8:
        return None
    return site + 5 + struct.unpack_from("<i", img, site + 1)[0]


# ---- the engine ---------------------------------------------------------------------------------------------------

def test_cpp_addresses_and_prologues_match_the_engine(image):
    src = _src("aivis.cpp")
    assert _const(src, "kVA_ZocAny") == ZOC_ANY and _const(src, "kVA_ZocVeh") == ZOC_VEH and _const(src, "kVA_ZocSea") == ZOC_SEA
    for name, va, n in (("kZocAnyPrologue", ZOC_ANY, 10), ("kZocVehPrologue", ZOC_VEH, 6), ("kZocSeaPrologue", ZOC_SEA, 6)):
        pro = _bytes_array(src, name)
        assert len(pro) == n, f"{name}: {n} relocatable bytes"
        o = va - 0x400000
        assert image[o:o + n] == pro, f"{name} differs from the pristine exe at {va:#x}"
    # the relocated bytes are whole instructions with no rel32: push ebp ; mov ebp,esp ; then push ecx + mov ecx,[abs32]
    # (zoc_any) or sub esp,8 (zoc_veh / zoc_sea)
    assert _bytes_array(src, "kZocAnyPrologue") == bytes.fromhex("558bec518b0d8c989400")
    assert _bytes_array(src, "kZocVehPrologue") == bytes.fromhex("558bec83ec08")
    assert _bytes_array(src, "kZocSeaPrologue") == bytes.fromhex("558bec83ec08")


def test_engine_return_shapes_are_what_the_ports_reproduce(image):
    # zoc_any: `inc eax` on the owner nibble (owner+1); zoc_veh: returns its running max from [ebp-4]; zoc_sea: lea eax,[edi+1]
    assert image[0x5C8ABA - 0x400000] == 0x40, "zoc_any returns owner+1"
    assert image[0x5C8B8D - 0x400000:0x5C8B8D - 0x400000 + 3] == bytes.fromhex("8b45fc"), "zoc_veh returns max(owner+1)"
    assert image[0x5C8B7E - 0x400000:0x5C8B7E - 0x400000 + 3] == bytes.fromhex("894dfc"), "zoc_veh stores the running max (mov [ebp-4], ecx)"
    assert image[0x5C8D2C - 0x400000:0x5C8D2C - 0x400000 + 3] == bytes.fromhex("8d4701"), "zoc_sea returns owner+1"
    # zoc_sea's per-unit tests the port repeats: the sight bit, the multiplayer test, VFLAG_INVISIBLE; and its veh_at
    s = 0x5C8CE2 - 0x400000
    assert image[s:s + 6] == bytes.fromhex("84904f289500") and image[s + 8:s + 10] == b"\x85\xf6"
    assert image[s + 19:s + 25] == bytes.fromhex("81e100040000")
    assert _call_target(image, 0x5C8CB8 - 0x400000) == ENGINE_VEH_AT - 0x400000, "zoc_sea walks the stack from veh_at"
    # the tile tests: zoc_any `test cl,3` (units or base), zoc_veh / zoc_sea `test byte [..+8], 2` (units)
    assert image[0x5C8A6E - 0x400000:0x5C8A6E - 0x400000 + 3] == bytes.fromhex("f6c103")
    assert image[0x5C8B40 - 0x400000:0x5C8B40 - 0x400000 + 4] == bytes.fromhex("f6410802")
    assert image[0x5C8C54 - 0x400000:0x5C8C54 - 0x400000 + 5] == bytes.fromhex("f6448708" + "02")
    # same land/sea test in zoc_sea (altitude byte & 0xE0 < 0x60 on both tiles)
    assert image[0x5C8C89 - 0x400000:0x5C8C89 - 0x400000 + 9] == bytes.fromhex("83e2e083fa608b55f8")


def test_baked_exe_keeps_the_entries_and_zoc_move(baked_exe):
    # the bytes a player runs (audit 2026-10-30: the pristine image alone would miss a longer patch that starts earlier)
    pefile = pytest.importorskip("pefile")
    img = bytes(pefile.PE(str(baked_exe)).get_memory_mapped_image())
    src = _src("aivis.cpp")
    for name, va in (("kZocAnyPrologue", ZOC_ANY), ("kZocVehPrologue", ZOC_VEH), ("kZocSeaPrologue", ZOC_SEA)):
        pro = _bytes_array(src, name)
        assert img[va - 0x400000:va - 0x400000 + len(pro)] == pro, f"{name} differs in the baked exe"
    assert _call_target(img, 0x5C8D8C - 0x400000) == ZOC_SEA - 0x400000


def test_zoc_move_still_calls_zoc_sea_and_no_patch_touches_the_entries(image, patches_path):
    assert _call_target(image, 0x5C8D8C - 0x400000) == ZOC_SEA - 0x400000, "zoc_move -> zoc_sea (no detour needed on zoc_move)"
    text = patches_path.read_text(encoding="utf-8", errors="replace")
    hits = []
    for m in re.finditer(r"virtual_addr:\s*(0x[0-9A-Fa-f]+)", text):
        va = int(m.group(1), 16)
        for entry in (ZOC_ANY, ZOC_VEH, ZOC_SEA):
            if entry - 16 <= va < entry + 6:
                hits.append(hex(va))
    assert not hits, f"a patch of ours sits on a zoc_* prologue: {hits}"


# ---- Thinker 5.5 --------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def thinker(need_local) -> dict:
    pefile = pytest.importorskip("pefile")
    dll = Path(os.environ.get("SMACX_THINKER_DLL", r"D:\SmacxThinker\game\thinker.dll"))
    need_local(dll, "thinker.dll 5.5 (the Thinker workspace, or SMACX_THINKER_DLL)")
    p = pefile.PE(str(dll))
    img = bytes(p.get_memory_mapped_image())
    text = next(s for s in p.sections if s.Name.startswith(b".text"))
    return {"img": img, "base": p.OPTIONAL_HEADER.ImageBase, "size": p.OPTIONAL_HEADER.SizeOfImage,
            "text": (text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize)}


def test_thinker_zoc_pins(thinker):
    src = _src("thinkeraivis.cpp")
    img, base, size = thinker["img"], thinker["base"], thinker["size"]
    any_, veh, sea, move = (_const(src, k) for k in ("kModZocAny", "kModZocVeh", "kModZocSea", "kModZocMove"))
    assert img[any_:any_ + 2] == _bytes_array(src, "kZocAnyHead") == b"\x55\xbd"
    assert img[veh:veh + 6] == _bytes_array(src, "kZocVehHead") == bytes.fromhex("55575631f653")
    assert img[sea:sea + 5] == _bytes_array(src, "kZocSeaHead") == bytes.fromhex("55575653bb")
    # the NearbyTiles immediates: the same table, inside the image -- {1,-1},{2,0},{1,1},{0,2},{-1,1},{-2,0},{-1,-1},{0,-2}
    imm_any = struct.unpack_from("<I", img, any_ + 2)[0]
    imm_sea = struct.unpack_from("<I", img, sea + 5)[0]
    assert base <= imm_any < base + size and base <= imm_sea < base + size
    table = struct.pack("<16i", 1, -1, 2, 0, 1, 1, 0, 2, -1, 1, -2, 0, -1, -1, 0, -2)
    assert img[imm_any - base:imm_any - base + 64] == table and img[imm_sea - base:imm_sea - base + 64] == table
    assert img[veh + 7:veh + 11] == struct.pack("<I", imm_any), "mod_zoc_veh loads the same table into ebx"
    # mod_zoc_move: its one direct call besides mapsq is mod_zoc_sea
    sea_calls = [move + i for i in range(0xC0) if _call_target(img, move + i) == sea]
    assert len(sea_calls) == 1, "mod_zoc_move calls mod_zoc_sea once"
    # order_veh's ZOC gate calls mod_zoc_move twice in a row (veh_action.cpp: mod_zoc_move(veh) && mod_zoc_move(tgt))
    gate = _const(src, "kSiteZocMoveGate")
    order_veh = _const(src, "kOrderVeh")
    assert order_veh < gate < order_veh + 0x3000
    assert _call_target(img, gate) == move
    assert any(_call_target(img, gate + i) == move for i in range(5, 0x40)), "the second mod_zoc_move call of the gate"
    # mod_enemy_veh's skip test calls mod_zoc_any (veh_turn.cpp:109)
    enemy_veh = 0xAED10
    assert any(_call_target(img, enemy_veh + i) == any_ for i in range(0x200)), "mod_enemy_veh -> mod_zoc_any"


def test_thinker_zoc_callers_match_the_source(thinker):
    # completeness (audit 2026-10-30): the caller COUNT of each port equals its call sites in Thinker's source, so a
    # compiler clone (.constprop / .isra) or an inlined copy of a mod_zoc_* body that would bypass the detour shows up
    # here as a missing call. Source: mod_zoc_any 7 (gameturn.cpp 1270, path.cpp 86, veh.cpp 1324, veh_action.cpp 3267,
    # veh_turn.cpp 109/275/361), mod_zoc_veh 3 (veh_action.cpp 3114/3322, veh_turn.cpp 394), mod_zoc_sea 1
    # (mod_zoc_move), mod_zoc_move 4 (move.cpp 2364, veh_action.cpp 2124/2125, veh_combat.cpp 1973).
    src = _src("thinkeraivis.cpp")
    img = thinker["img"]
    lo, hi = thinker["text"]
    want = {_const(src, "kModZocAny"): 7, _const(src, "kModZocVeh"): 3, _const(src, "kModZocSea"): 1, _const(src, "kModZocMove"): 4}
    callers = {f: [] for f in want}
    for m in re.finditer(rb"\xe8", img[lo:hi]):
        site = lo + m.start()
        t = _call_target(img, site)
        if t in callers:
            callers[t].append(site)
    got = {hex(f): len(c) for f, c in callers.items()}
    assert {f: len(c) for f, c in callers.items()} == want, f"caller counts {got} != source"


# ---- source shape -------------------------------------------------------------------------------------------------

def test_exemption_is_hidden_kind_and_unseen_and_human_owned():
    src = _src("aivis.cpp")
    body = re.search(r"bool ZocExempt\(const BYTE\* v, int f\)\s*\{(.*?)\}", src, re.S).group(1)
    assert "HiddenKind(v)" in body and "kVehVisibility] >> f) & 1) == 0" in body and "IsHuman(v[kVehFaction])" in body
    # the tile-level ports exempt a stack only when EVERY unit is exempt, never on a base tile, never on an empty answer
    stack = re.search(r"bool StackAllExempt\(int x, int y, int f, const BYTE\* sq\)\s*\{(.*?)\n\}", src, re.S).group(1)
    assert "& 1) != 0) return false" in stack and "if (k < 0) return false" in stack and "if (!ZocExempt(Veh(k), f)) return false" in stack
    assert "if (k >= n || guard++ >= 4096) return false" in stack, "a broken stack link is never exempt"
    assert "kVA_VehAt" in stack, "the engine's own veh_at walks the stack"
    # zoc_sea's port agrees with the tile-level ones on base tiles: a garrison always exerts
    sea = re.search(r"int ZocSeaRule\(int x, int y, int f\)(.*?)\n\}", src, re.S).group(1)
    assert "(baseTile || !ZocExempt(v, f))" in sea and "baseTile = (items & 1) != 0" in sea


def test_every_hook_asks_the_original_first_and_a_zero_stays_zero():
    src = _src("aivis.cpp")
    for kind, tramp in ((0, "g_zocAnyTramp"), (1, "g_zocVehTramp"), (2, "g_zocSeaTramp")):
        assert re.search(rf"return ZocAdjust\({kind}, {tramp}\(x, y, f\), x, y, f\);", src), f"hook kind {kind}"
    adjust = re.search(r"int ZocAdjust\(int kind, int r, int x, int y, int f\)\s*\{(.*?)\n\}", src, re.S).group(1)
    assert "if (r == 0 || f < 0 || f >= 8 || !Enabled()) return r;" in adjust
    # the ports repeat the engine's own tests: owner nibble, pact, units bit (and zoc_sea: same land/sea, sight bit, invisible flag)
    sea = re.search(r"int ZocSeaRule\(int x, int y, int f\)(.*?)\n\}", src, re.S).group(1)
    assert "kVA_MultiplayerActive" in sea and "kVflagInvisible" in sea and "kVehVisibility] >> f) & 1) return owner + 1" in sea
    assert "< 0x60) != ocean) continue" in sea and "PactWith(f, owner)" in sea
    # installed with trampolines over the pinned prologues, gated by the byte check
    assert "DetourEntryBytes(kVA_ZocAny, sizeof kZocAnyPrologue, &HookZocAny)" in src
    assert "DetourEntryBytes(kVA_ZocVeh, sizeof kZocVehPrologue, &HookZocVeh)" in src
    assert "DetourEntryBytes(kVA_ZocSea, sizeof kZocSeaPrologue, &HookZocSea)" in src
    assert "memcmp(At(kVA_ZocSea), kZocSeaPrologue, sizeof kZocSeaPrologue) == 0" in src


def test_thinker_half_uses_the_same_adjustment():
    src = _src("thinkeraivis.cpp")
    hdr = _src("aivis.h")
    assert "int   AiVisZocAdjust(int kind, int r, int x, int y, int f);" in hdr
    for kind, tramp in ((0, "g_zocAnyTramp"), (1, "g_zocVehTramp"), (2, "g_zocSeaTramp")):
        assert re.search(rf"return AiVisZocAdjust\({kind}, {tramp}\(x, y, f\), x, y, f\);", src), f"Thinker hook kind {kind}"
    assert "DetourEntryN(g_base + kModZocAny, 6, &HookThinkerZocAny)" in src
    assert "DetourEntryN(g_base + kModZocVeh, 6, &HookThinkerZocVeh)" in src
    assert "DetourEntryN(g_base + kModZocSea, 9, &HookThinkerZocSea)" in src
    assert "if (ZocPortsLookRight(lo, hi))" in src
    # the residual note no longer lists mod_zoc_sea as left alone (the paragraph runs up to the first FIXED note)
    residual = re.search(r"Left as Thinker has them(.*?)FIXED", src, re.S).group(1)
    assert "mod_zoc_sea" not in residual
