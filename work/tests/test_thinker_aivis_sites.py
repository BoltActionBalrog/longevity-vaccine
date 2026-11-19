r"""src\uimod\src\thinkeraivis.cpp ports the AI perception filter into thinker.dll 5.5 with a hand-written site table
(image offsets, byte-checked at run time). This module checks that table against the DLL itself, so a Thinker build
change or a stale offset fails here instead of silently disabling the port in game:

  * the PE pin (TimeDateStamp / SizeOfImage) matches the DLL;
  * every listed call site is an E8 to the function the table names, and -- completeness -- every E8 in .text that
    targets a wrapped function (non_ally_in_tile, stack_search, allow_combat) is listed: a site the table misses is a
    leak that would let Thinker's AI plan against units it has not seen;
  * each unit-loop at_war stub site calls at_war and its witness bytes (the unit-faction read through the register the
    stub forwards) are what the table says;
  * every stub that forwards a register (the two at_war stubs, allow_airdrop's has_pact stub) still finds the value
    the witness read there when the call runs: on every control-flow path from the witness to the call nothing writes
    that register, and no path reaches the call without passing the witness (a function entry, an address-taken
    target or an export on the way in);
  * completeness beyond direct calls: a wrapped function is never reached by a jump (a tail call), never has its
    address taken (no relocated pointer to it anywhere in the image) and is not exported;
  * the enemy_move pointer holds the engine's enemy_move and order_veh opens with the six relocatable prologue bytes;
  * the named functions look like themselves (at_war tests DIPLO_VENDETTA, the three planner helpers read *VehCount).

The DLL lives outside the repo (the Thinker workspace, D:\SmacxThinker\game, or SMACX_THINKER_DLL); absent it skips
(a failure under LONGEVITY_REQUIRE_E2E). Cheap: byte scans, plus ONE linear capstone sweep of .text per module
(~0.5 s) for the control-flow checks.
"""
from __future__ import annotations

import bisect
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


def _stub_forwards(src: str, stub: str) -> str:
    """The caller's register a naked stub hands to our code: the one register it pushes (ebx or esi)."""
    m = re.search(rf"__declspec\(naked\)\s+{stub}\(\)\s*\{{\s*__asm\s*\{{([^}}]*)\}}", src)
    assert m, f"{stub}: naked stub body not found"
    pushed = set(re.findall(r"\bpush\s+(ebx|esi|edi|ebp)\b", m.group(1)))
    assert len(pushed) == 1, f"{stub}: expected exactly one forwarded register push, found {sorted(pushed)}"
    return pushed.pop()


@pytest.fixture(scope="module")
def table() -> dict:
    src = CPP.read_text(encoding="utf-8")
    rows = list(re.finditer(r"\{\s*(0x[0-9A-Fa-f]+),\s*\"(\w+)\",\s*&(Stub\w+),\s*(0x[0-9A-Fa-f]+),\s*\{([^}]*)\}\s*\}", src))
    assert len(rows) == 2, "two unit-loop at_war stubs expected (combat_move artillery, move_upkeep census)"
    for m in rows:   # the row's register string must be the register its stub actually forwards
        assert _stub_forwards(src, m.group(3)) == m.group(2), f"kStubs row +{m.group(1)}: \"{m.group(2)}\" but {m.group(3)} forwards another register"
    stubs = [(int(m.group(1), 16), m.group(2), int(m.group(4), 16), bytes(int(b, 16) for b in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(5))))
             for m in rows]
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
    base = p.OPTIONAL_HEADER.ImageBase
    # every absolute pointer the loader relocates (HIGHLOW): code or data that takes an address -- jump tables,
    # function pointers, `push offset fn` -- as the RVA it points at
    reloc_locs = [e.rva for b in getattr(p, "DIRECTORY_ENTRY_BASERELOC", []) for e in b.entries if e.type == 3]
    relocs = {struct.unpack_from("<I", img, r)[0] - base for r in reloc_locs}
    exports = {s.address for s in p.DIRECTORY_ENTRY_EXPORT.symbols} if hasattr(p, "DIRECTORY_ENTRY_EXPORT") else set()
    return {"img": img, "stamp": p.FILE_HEADER.TimeDateStamp, "size": p.OPTIONAL_HEADER.SizeOfImage,
            "text": (text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize),
            "relocs": relocs, "reloc_locs": reloc_locs, "exports": exports}


# instructions after which control never falls through to the next address (matched on the mnemonic's last word,
# so `repz ret` counts)
_NO_FALL = {"jmp", "ljmp", "ret", "retf", "iret", "iretd", "ud2", "int3", "hlt"}
# MinGW's .text ends in a runtime tail (constructor list, exception tables) that a linear sweep cannot decode in
# step; everything before it is code. The tail of the pinned DLL is 0x1654 bytes.
_TAIL_MAX = 0x2000


def _no_fall(mn: str) -> bool:
    return mn.split()[-1] in _NO_FALL


def _is_branch(mn: str) -> bool:
    return mn == "call" or mn.startswith("j") or mn.startswith("loop")


@pytest.fixture(scope="module")
def sweep(dll) -> dict:
    """One linear disassembly of .text: instruction starts, each one's size / mnemonic / direct branch target, and
    the incoming direct branches of every target. MinGW keeps .text code-only up to its runtime tail, so a linear
    sweep is in step there; test_sweep_is_in_step_where_it_is_read checks that."""
    capstone = pytest.importorskip("capstone")
    lo, hi = dll["text"]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.skipdata = True
    ins: dict[int, tuple[int, str, int | None]] = {}
    incoming: dict[int, list[int]] = {}
    for a, sz, mn, op in md.disasm_lite(dll["img"][lo:hi], lo):
        tg = int(op, 16) if _is_branch(mn) and op.startswith("0x") else None
        ins[a] = (sz, mn, tg)
        if tg is not None:
            incoming.setdefault(tg, []).append(a)
    detail = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    detail.detail = True
    return {"ins": ins, "starts": sorted(ins), "incoming": incoming, "detail": detail, "capstone": capstone}


def _insn(sw: dict, dll: dict, a: int):
    return next(sw["detail"].disasm(dll["img"][a:a + 16], a, 1))


def _is_padding(sw: dict, dll: dict, a: int) -> bool:
    """An alignment filler that changes nothing: nop, int3, or `lea r,[r]` / `mov r,r` / `xchg r,r` (MinGW pads with
    `lea esi,[esi+eiz]` and friends, any segment prefix)."""
    i = _insn(sw, dll, a)
    if i.mnemonic in ("nop", "int3"):
        return True
    x86 = sw["capstone"].x86
    ops = i.operands
    if len(ops) != 2 or ops[0].type != x86.X86_OP_REG:
        return False
    if i.mnemonic == "lea" and ops[1].type == x86.X86_OP_MEM:
        mem = ops[1].mem
        return mem.base == ops[0].reg and mem.disp == 0 and i.reg_name(mem.index) in (None, "eiz")
    return i.mnemonic in ("mov", "xchg") and ops[1].type == x86.X86_OP_REG and ops[1].reg == ops[0].reg


def _fallthrough_pred(sw: dict, n: int) -> int | None:
    i = bisect.bisect_left(sw["starts"], n) - 1
    if i < 0:
        return None
    a = sw["starts"][i]
    sz, mn, _ = sw["ins"][a]
    return a if a + sz == n and not _no_fall(mn) else None


def _dead_padding(sw: dict, dll: dict, a: int) -> bool:
    """True when the padding run ending at `a` is unreachable: walking back over padding meets no incoming jump and
    begins right after an instruction that never falls through."""
    while _is_padding(sw, dll, a):
        if sw["incoming"].get(a):
            return False
        p = _fallthrough_pred(sw, a)
        if p is None:
            return True
        a = p
    return False   # live code falls into the run


def _witness_to_call_path(sw: dict, dll: dict, witness: int, site: int) -> tuple[set[int], list[int]]:
    """The instructions that can run after the witness and before the call: walk back from the call over every
    predecessor (fall-through and incoming jumps), stopping at the witness, then keep what the witness reaches going
    forward. Returns that set and the walk's entries from outside -- a path to the call that does not pass the
    witness: an instruction a call, a relocated pointer or an export can enter, or REAL code that nothing visible
    enters (no incoming jump, and no fall-through except off dead padding) -- an exception landing pad or a computed
    jump lands there. Only a padding instruction with no predecessor (MinGW's `lea esi,[esi]` after a jmp) is dead
    code that ends its branch of the walk."""
    ins, incoming = sw["ins"], sw["incoming"]
    back: set[int] = set()
    outside: list[int] = []
    todo = [site]
    while todo:
        n = todo.pop()
        if n in back:
            continue
        back.add(n)
        assert len(back) < 20000, f"+{site:X}: the walk back from the call does not close on the witness +{witness:X}"
        if n == witness:
            continue
        srcs = incoming.get(n, [])
        jumps = [s for s in srcs if ins[s][1] != "call"]
        pf = _fallthrough_pred(sw, n)
        if any(ins[s][1] == "call" for s in srcs) or n in dll["relocs"] or n in dll["exports"]:
            outside.append(n)
        elif not jumps and not _is_padding(sw, dll, n) and (pf is None or _dead_padding(sw, dll, pf)):
            outside.append(n)
        todo += jumps
        if pf is not None:
            todo.append(pf)
    path: set[int] = set()
    todo = [witness]
    while todo:
        n = todo.pop()
        if n in path or n not in back:
            continue
        path.add(n)
        if n == site:
            continue
        sz, mn, tg = ins[n]
        if not _no_fall(mn):
            todo.append(n + sz)
        if tg is not None and mn != "call":
            todo.append(tg)
    return path, outside


def _register_stubs(table) -> list[tuple[int, str, int]]:
    """(call site, forwarded register, witness) of every stub that hands a caller's register to our code."""
    src = CPP.read_text(encoding="utf-8")
    m = re.search(r"Retarget\(g_base \+ kSiteAirdropPact, &(Stub\w+)\)", src)
    assert m, "allow_airdrop's has_pact site is no longer retargeted to a register stub -- update this test"
    airdrop = (_const(src, "kSiteAirdropPact"), _stub_forwards(src, m.group(1)), _const(src, "kAirdropPactWitness"))
    return [(site, reg, witness) for site, reg, witness, _ in table["stubs"]] + [airdrop]


_REG_PARTS = {"ebx": {"ebx", "bx", "bl", "bh"}, "esi": {"esi", "si"}}


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


def test_sweep_is_in_step_where_it_is_read(table, dll, sweep):
    """A desynced sweep could hide a jump into a checked path or to a wrapped function, and those checks read all of
    .text. Evidence of a desync -- a direct-branch or relocated target that is not an instruction start, or a
    relocated dword that is not wholly inside one instruction's operand bytes -- may appear only in the runtime tail
    (the last _TAIL_MAX bytes), never in the code before it."""
    lo, hi = dll["text"]
    ins, starts = sweep["ins"], sweep["starts"]
    evidence = [t for t in list(sweep["incoming"]) + list(dll["relocs"]) if lo <= t < hi and t not in ins]
    for r in dll["reloc_locs"]:
        if lo <= r < hi:
            a = starts[bisect.bisect_right(starts, r) - 1]
            if not (a < r and r + 4 <= a + ins[a][0]):
                evidence.append(r)
    first = min(evidence, default=hi)
    assert first >= hi - _TAIL_MAX, (
        f"the sweep is out of step at +{first:X}, {hi - first:#x} bytes before the end of .text -- past the runtime "
        f"tail ({_TAIL_MAX:#x}); every control-flow check here may have missed a branch")
    read = [table[k] for k in ("non_ally", "stack_search", "allow_combat")] + \
           [a for s in _register_stubs(table) for a in (s[0], s[2])]
    assert max(read) < first, "a checked address lies in the undecodable tail"


def test_forwarded_register_survives_from_witness_to_call(table, dll, sweep):
    for site, reg, witness in _register_stubs(table):
        assert witness in sweep["ins"] and site in sweep["ins"], f"+{site:X}: witness or call is not an instruction start"
        path, outside = _witness_to_call_path(sweep, dll, witness, site)
        assert site in path, f"+{site:X}: the call is not reachable from the witness +{witness:X}"
        assert not outside, (f"+{site:X}: the call can be reached without passing the witness +{witness:X} -- entered "
                             f"at {[f'+{x:X}' for x in outside]}; {reg} may not hold the unit there")
        calls = [f"+{a:X}" for a in sorted(path) if a != site and sweep["ins"][a][1] == "call"]
        assert not calls, (f"+{site:X}: a call at {calls} between the witness and the call -- capstone cannot see "
                           f"whether the callee preserves {reg}; check it by hand and extend this test")
        writes = []
        for a in sorted(path):
            if _is_padding(sweep, dll, a):
                continue   # `lea esi,[esi]` writes esi with its own value
            i = _insn(sweep, dll, a)
            if _REG_PARTS[reg] & {i.reg_name(r) for r in i.regs_access()[1]}:
                writes.append(f"+{a:X} {i.mnemonic} {i.op_str}")
        assert not writes, f"+{site:X}: {reg} is written between the witness +{witness:X} and the call: {writes}"


@pytest.mark.parametrize("fn", ["non_ally", "stack_search", "allow_combat"])
def test_wrapped_function_has_no_indirect_or_jump_entry(table, dll, sweep, fn):
    """The call-site table re-points E8 calls only; any other way in would bypass the wrapper unseen."""
    target = table[fn]
    jumps = [a for a in sweep["incoming"].get(target, []) if sweep["ins"][a][1] != "call"]
    assert not jumps, f"{fn}: reached by a jump (tail call) at {[f'+{a:X}' for a in jumps]} -- not wrapped"
    assert target not in dll["relocs"], f"{fn}: its address is taken (a relocated pointer to +{target:X}) -- an indirect call is not wrapped"
    assert target not in dll["exports"], f"{fn}: exported -- a caller outside the DLL is not wrapped"


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
