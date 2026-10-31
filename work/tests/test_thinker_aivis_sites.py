r"""src\uimod\src\thinkeraivis.cpp ports the AI perception filter into thinker.dll 5.5 with a hand-written site table
(image offsets, byte-checked at run time). This module checks that table against the DLL itself, so a Thinker build
change or a stale offset fails here instead of silently disabling the port in game:

  * the PE pin (TimeDateStamp / SizeOfImage) matches the DLL;
  * every listed call site is an E8 to the function the table names, and -- completeness -- every E8 in .text that
    targets a wrapped function (non_ally_in_tile, stack_search, allow_combat) is listed: a site the table misses is a
    leak that would let Thinker's AI plan against units it has not seen;
  * each unit-loop at_war stub site calls at_war and its witness bytes (the unit-faction read through the register the
    stub forwards) are what the table says;
  * the enemy_move pointer holds the engine's enemy_move and order_veh opens with the six relocatable prologue bytes;
  * the named functions look like themselves (at_war tests DIPLO_VENDETTA, the three planner helpers read *VehCount).

The DLL lives outside the repo (the Thinker workspace, D:\SmacxThinker\game, or SMACX_THINKER_DLL); absent it skips
(a failure under LONGEVITY_REQUIRE_E2E). Cheap: byte scans only, no disassembler.
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPP = ROOT / "src" / "uimod" / "src" / "thinkeraivis.cpp"
DEFAULT_DLL = Path(r"D:\SmacxThinker\game\thinker.dll")
ENGINE_ENEMY_MOVE = 0x56B5B0


def _const(src: str, name: str) -> int:
    """A hex literal, or a UIMOD_* macro resolved from version.h (the Thinker pin lives there since 2026-10-30)."""
    m = re.search(rf"\b{name}\s*=\s*(0x[0-9A-Fa-f]+|UIMOD_[A-Z_]+)", src)
    assert m, f"{name} not found in thinkeraivis.cpp"
    val = m.group(1)
    if val.startswith("UIMOD_"):
        hdr = (ROOT / "src" / "uimod" / "src" / "version.h").read_text(encoding="utf-8")
        d = re.search(rf"^\s*#define\s+{val}\s+(0x[0-9A-Fa-f]+)\s*$", hdr, re.M)
        assert d, f"{val} not defined in version.h"
        val = d.group(1)
    return int(val, 16)


def _array(src: str, name: str) -> list[int]:
    m = re.search(rf"{name}\[\d*\]\s*=\s*\{{([^}}]*)\}}", src)
    assert m, f"{name}[] not found in thinkeraivis.cpp"
    return [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]+", m.group(1))]


@pytest.fixture(scope="module")
def table() -> dict:
    src = CPP.read_text(encoding="utf-8")
    stubs = [(int(m.group(1), 16), m.group(2), int(m.group(3), 16), bytes(int(b, 16) for b in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(4))))
             for m in re.finditer(r"\{\s*(0x[0-9A-Fa-f]+),\s*\"(\w+)\",\s*&Stub\w+,\s*(0x[0-9A-Fa-f]+),\s*\{([^}]*)\}\s*\}", src)]
    assert len(stubs) == 2, "two unit-loop at_war stubs expected (combat_move artillery, move_upkeep census)"
    return {
        "stamp": _const(src, "kStamp"), "size": _const(src, "kSizeOfImage"),
        "at_war": _const(src, "kAtWar"), "non_ally": _const(src, "kNonAllyInTile"), "stack_search": _const(src, "kStackSearch"),
        "allow_combat": _const(src, "kAllowCombat"), "order_veh": _const(src, "kOrderVeh"), "enemy_move_ptr": _const(src, "kEnemyMovePtr"),
        "sites_non_ally": _array(src, "kSitesNonAlly"), "sites_stack_search": _array(src, "kSitesStackSearch"),
        "sites_allow_combat": _array(src, "kSitesAllowCombat"), "stubs": stubs,
        "prologue": bytes(_array(src, "kOrderVehPrologue")),
    }


@pytest.fixture(scope="module")
def dll(need_local) -> dict:
    pefile = pytest.importorskip("pefile")
    path = Path(os.environ.get("SMACX_THINKER_DLL", str(DEFAULT_DLL)))
    need_local(path, "thinker.dll 5.5 (the Thinker workspace, or SMACX_THINKER_DLL)")
    p = pefile.PE(str(path))
    img = bytes(p.get_memory_mapped_image())
    text = next(s for s in p.sections if s.Name.startswith(b".text"))
    return {"img": img, "stamp": p.FILE_HEADER.TimeDateStamp, "size": p.OPTIONAL_HEADER.SizeOfImage,
            "text": (text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize)}


def _call_target(img: bytes, site: int) -> int | None:
    if img[site] != 0xE8:
        return None
    rel = struct.unpack_from("<i", img, site + 1)[0]
    return site + 5 + rel


def _all_calls_to(img: bytes, lo: int, hi: int, target: int) -> set[int]:
    want = {site for site in (m.start() for m in re.finditer(rb"\xe8", img[lo:hi]))
            if _call_target(img, lo + site) == target for site in [site]}
    return {lo + s for s in want}


def test_pe_pin(table, dll):
    assert (dll["stamp"], dll["size"]) == (table["stamp"], table["size"]), (
        f"thinker.dll is stamp 0x{dll['stamp']:08X} / image 0x{dll['size']:X}; the table pins "
        f"0x{table['stamp']:08X} / 0x{table['size']:X} -- re-measure every offset before moving the pin")


@pytest.mark.parametrize("sites,fn", [("sites_non_ally", "non_ally"), ("sites_stack_search", "stack_search"), ("sites_allow_combat", "allow_combat")])
def test_listed_sites_call_the_named_function(table, dll, sites, fn):
    for s in table[sites]:
        assert _call_target(dll["img"], s) == table[fn], f"+{s:X} does not call {fn} (+{table[fn]:X})"


@pytest.mark.parametrize("sites,fn", [("sites_non_ally", "non_ally"), ("sites_stack_search", "stack_search"), ("sites_allow_combat", "allow_combat")])
def test_table_lists_every_call_site_of_the_wrapped_function(table, dll, sites, fn):
    lo, hi = dll["text"]
    found = _all_calls_to(dll["img"], lo, hi, table[fn])
    assert found == set(table[sites]), (
        f"{fn}: the DLL's call sites {sorted(f'+{x:X}' for x in found)} != the table's "
        f"{sorted(f'+{x:X}' for x in table[sites])} -- an unlisted site is a leak")


def test_stub_sites_call_at_war_and_their_witness_bytes_hold(table, dll):
    for site, reg, witness, wbytes in table["stubs"]:
        assert _call_target(dll["img"], site) == table["at_war"], f"+{site:X} does not call at_war"
        assert dll["img"][witness:witness + 4] == wbytes, f"+{site:X} ({reg}): witness bytes at +{witness:X} differ"
        # the witness is `movzx eax, byte ptr [reg+0xE]`: 0F B6 /r with disp8 0x0E; the ModRM's r/m names the register
        assert wbytes[:2] == b"\x0f\xb6" and wbytes[3] == 0x0E
        assert {"ebx": 0x43, "esi": 0x46}[reg] == wbytes[2], f"+{site:X}: witness reads through another register than {reg}"


def test_pillage_bombardment_site(table, dll):
    src = CPP.read_text(encoding="utf-8")
    site, fight, witness = _const(src, "kSitePillageFight"), _const(src, "kModBattleFight"), _const(src, "kPillageWitness")
    assert _call_target(dll["img"], site) == fight, "the pillage loop's combat call must call mod_battle_fight"
    assert dll["img"][witness:witness + 4] == b"\x8b\x44\x24\x60", "the veh-id load that feeds that call"
    # the loop's stack check right before it: mod_stack_check(stack, 15, owner, -1, -1)
    assert b"\xc7\x44\x24\x04\x0f\x00\x00\x00" in dll["img"][site - 0x40:site], "type 15 stack check precedes the combat call"


def test_airdrop_pact_site(table, dll):
    src = CPP.read_text(encoding="utf-8")
    site, pact, witness = _const(src, "kSiteAirdropPact"), _const(src, "kHasPact"), _const(src, "kAirdropPactWitness")
    assert _call_target(dll["img"], site) == pact, "allow_airdrop's loop must call has_pact there"
    assert dll["img"][witness:witness + 3] == b"\x6b\xc3\x34", "imul eax, ebx, 0x34: the unit index is in ebx"
    has_pact = dll["img"][pact:pact + 0x30]
    assert b"\x83\xe0\x01" in has_pact, "has_pact: `and eax,1` = DIPLO_PACT"


def test_enemy_move_pointer_and_order_veh_prologue(table, dll):
    assert struct.unpack_from("<I", dll["img"], table["enemy_move_ptr"])[0] == ENGINE_ENEMY_MOVE
    assert dll["img"][table["order_veh"]:table["order_veh"] + 6] == table["prologue"]
    assert table["prologue"][:2] == b"\x55\xb8", "push ebp ; mov eax, imm32 -- six position-independent bytes"


def test_named_functions_look_like_themselves(table, dll):
    img = dll["img"]
    at_war = img[table["at_war"]:table["at_war"] + 0x40]
    assert b"\xc0\xe8\x04" in at_war and b"\x83\xe0\x01" in at_war, "at_war: `shr al,4 ; and eax,1` = DIPLO_VENDETTA (0x10)"
    assert struct.pack("<I", 0x20CC)[:2] in at_war, "at_war: Factions stride 0x20CC"
    vehcount_ptr_read = re.compile(rb"\xa1....|\x8b\x05....")
    for fn in ("non_ally", "stack_search", "allow_combat"):
        head = img[table[fn]:table[fn] + 0x20]
        assert vehcount_ptr_read.search(head), f"{fn}: no `mov eax, [VehCount ptr]` in its prologue"
        assert head[0] == 0x55, f"{fn}: does not start with push ebp"
