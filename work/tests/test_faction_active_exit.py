"""g_faction_active is cleared at the faction picker's OWN exit, and no other set/clear of ours hides in engine code
Thinker 5.5 never runs.

THE BUG (2026-11-15, PRACX + Thinker 5.5, 4K): after a game started through Make Random Map / Customize (the faction
picker shown), the HUD MENU button's face banded (4K device-row runs 5,7,5,8,5,5) from its first hover for the rest of
the process.  g_faction_active is SET at the picker's build (thunk_factionwin_graphicwin, inside FactionPickWin_build
0x4887A0) and was CLEARED only by thunk_faction_show at the engine's call site in config_game (0x58A75A).  Thinker
replaces config_game and calls PickWin_init 0x4887A0 / PickWin_show_window 0x48A810 itself, so the clear never ran,
and thunk_faction_portrait (FlatButton's state-sprite Sprite_draw_2 @0x607F43) drew every >32-px state sprite at g/16
from (0,0) before thunk_btn_2dscale's zoom: the face enlarged twice.  t_fpw_exit clears the flag at exec's own exit.

  1. Emulation (baked exe vs the clean PRACX base): FactionPickWin_exec returns the same eax / esi / esp / EFLAGS as
     vanilla, the flag is still set while its modal pump runs, and it is 0 at the exit where the base leaves it 1
     (the bug, kept visible).
  2. Census: every patches.yaml site that lies inside an engine function Thinker 5.5 makes unreachable BY DIRECT
     CALLS (a write_jump target, or a function not taken by address whose every E8 call site Thinker re-points or
     that lies in such a function, and that Thinker's own code does not call back) is listed in DEAD_UNDER_THINKER
     with the reason it is harmless.  A new entry means a site that silently stops running under Thinker -- a set
     without its clear, a scale without its restore -- and needs the same treatment.
     NOT SEEN by the census: functions reached through a pointer Thinker replaces (its write_offset callbacks /
     vtable slots: anything taken by address is treated as live), E9 tail-jump edges, function ends the _extent
     heuristic misjudges, uimod.dll's run-time patches, and a set/clear pair split across LIVE code Thinker merely
     calls in a different order.  It is a tripwire for the config_game class of bug, not proof of the rest.
"""
from __future__ import annotations

import bisect
import re
import struct
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import thinker_overlap as T  # noqa: E402

pefile = pytest.importorskip("pefile")
unicorn = pytest.importorskip("unicorn")
capstone = pytest.importorskip("capstone")
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EFLAGS, UC_X86_REG_ESI,  # noqa: E402
                               UC_X86_REG_ESP)

FPW_EXEC = 0x48A810                 # FactionPickWin_exec (Thinker: PickWin_show_window)
G_FACTION_ACTIVE = 0xA0D2D0         # pcave2 + 0x12D0
RESULT_OFF = 0x5DA8                 # exec's return value [esi+0x5da8]

THIS = 0x00300000
VTBL = 0x00310000
STUBS = 0x00320000
MAGIC = 0x00330000
PUMP_SAW = STUBS + 0x100            # where the pump stub records the flag it saw
STACK_TOP = 0x00F00000


def _sections(path: Path):
    pe = pefile.PE(str(path), fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    out = []
    for s in pe.sections:
        vsize = max(s.Misc_VirtualSize, s.SizeOfRawData)
        data = s.get_data()[:vsize]
        out.append((ib + s.VirtualAddress, data + b"\x00" * (((vsize + 0xFFF) & ~0xFFF) - len(data))))
    pe.close()
    return out


def _run_exec(path: Path, flag_in: int) -> dict:
    """Run FactionPickWin_exec with its three virtual calls stubbed to their RET-imm contracts."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for va, data in _sections(path):
        base = va & ~0xFFF
        uc.mem_map(base, ((va + len(data) + 0xFFF) & ~0xFFF) - base)
        uc.mem_write(va, data)
    for page in (THIS, VTBL, STUBS, MAGIC):
        uc.mem_map(page, 0x10000)
    if not any(r[0] <= G_FACTION_ACTIVE <= r[1] for r in uc.mem_regions()):   # the clean base has no pcave2
        uc.mem_map(G_FACTION_ACTIVE & ~0xFFF, 0x1000)
    uc.mem_map(STACK_TOP - 0x10000, 0x10000)
    # vtbl[+0xF8] redraw (no args), vtbl[+4] (1 arg), vtbl[+0xE4] the modal pump (3 args): thiscall, callee cleans.
    # The pump stub records the flag it sees (mov eax,[flag]; mov [PUMP_SAW],eax): the hover redraws run in the pump,
    # so the flag must still be set there -- a clear placed before the pump would pass the exit checks alone.
    uc.mem_write(STUBS, bytes.fromhex("C3"))
    uc.mem_write(STUBS + 0x10, bytes.fromhex("C2 04 00"))
    uc.mem_write(STUBS + 0x20, b"\xA1" + struct.pack("<I", G_FACTION_ACTIVE) + b"\xA3" + struct.pack("<I", PUMP_SAW)
                 + bytes.fromhex("C2 0C 00"))
    uc.mem_write(PUMP_SAW, struct.pack("<I", 0xDEADBEEF))
    uc.mem_write(VTBL + 0xF8, struct.pack("<I", STUBS))
    uc.mem_write(VTBL + 0x04, struct.pack("<I", STUBS + 0x10))
    uc.mem_write(VTBL + 0xE4, struct.pack("<I", STUBS + 0x20))
    uc.mem_write(THIS, struct.pack("<I", VTBL))
    uc.mem_write(THIS + RESULT_OFF, struct.pack("<I", 0x1234ABCD))
    uc.mem_write(G_FACTION_ACTIVE, struct.pack("<I", flag_in))
    esp0 = STACK_TOP - 0x1000
    uc.mem_write(esp0, struct.pack("<I", MAGIC))
    uc.reg_write(UC_X86_REG_ESP, esp0)
    uc.reg_write(UC_X86_REG_ECX, THIS)
    uc.reg_write(UC_X86_REG_ESI, 0x5E5E5E5E)
    uc.reg_write(UC_X86_REG_EFLAGS, 0x202)
    uc.emu_start(FPW_EXEC, MAGIC, count=10_000)
    return {"eax": uc.reg_read(UC_X86_REG_EAX), "esi": uc.reg_read(UC_X86_REG_ESI),
            "esp": uc.reg_read(UC_X86_REG_ESP) - esp0, "eflags": uc.reg_read(UC_X86_REG_EFLAGS),
            "flag": struct.unpack("<I", uc.mem_read(G_FACTION_ACTIVE, 4))[0],
            "pump_saw": struct.unpack("<I", uc.mem_read(PUMP_SAW, 4))[0]}


def test_picker_exit_clears_faction_active(bak_path, baked_exe):
    base = _run_exec(bak_path, flag_in=1)
    ours = _run_exec(baked_exe, flag_in=1)
    for k in ("eax", "esi", "esp", "eflags"):
        assert ours[k] == base[k], (k, hex(ours[k]), hex(base[k]))
    assert ours["eax"] == 0x1234ABCD and ours["esi"] == 0x5E5E5E5E and ours["esp"] == 4
    assert base["flag"] == 1, "the clean base never touches the flag (the cave is ours)"
    assert ours["pump_saw"] == 1, "the flag must still be set while the modal pump (the hover redraws) runs"
    assert ours["flag"] == 0, "FactionPickWin_exec must clear g_faction_active at its own exit"


def test_picker_exit_leaves_a_clear_flag_clear(baked_exe):
    assert _run_exec(baked_exe, flag_in=0)["flag"] == 0


# --- census: sites inside engine code Thinker 5.5 never runs -------------------------------------------------------

#: site id -> why it is harmless that it never runs under Thinker.  Add an entry only with the fix that makes it so.
DEAD_UNDER_THINKER = {
    "config_game.faction_show_bracket":
        "set g_faction_active + ensure_scale before the picker, clear after: under Thinker the set happens at the "
        "picker's build (thunk_factionwin_graphicwin, which also ensures the scale) and the clear at the picker's own "
        "exit (FactionPickWin_exec.clear_faction_active)",
    # Thinker replaces save_daemon / load_daemon (mod_save_daemon / mod_load_daemon) with its own save path:
    "game_data.header_init":
        "Thinker's own game_data (savegame.cpp:147) zero-initialises the header with version 12 -- the same hardening",
    **{f"crt_filelock.{f}_{k}":
       "the exe CRT's fgetc/fputc are reached only from the engine's header_check/header_write; Thinker's own "
       "(savegame.cpp:798/814) run on thinker.dll's CRT, so there is nothing for these locks to protect"
       for f in ("fgetc", "fputc") for k in ("lock", "unlock")},
}


def _image(data: bytes):
    pe = pefile.PE(data=data, fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    text = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
    lo = ib + text.VirtualAddress
    code = text.get_data()[: text.Misc_VirtualSize]
    return lo, code


def _extent(lo: int, code: bytes, start: int) -> int:
    """End of the function at `start`: the first ret/jmp at or past the furthest forward branch target."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    o = start - lo
    hi = start
    for ins in md.disasm(code[o:o + 0x8000], start):
        if ins.mnemonic.startswith("j") and ins.op_str.startswith("0x"):
            t = int(ins.op_str, 16)
            if start <= t < start + 0x8000:
                hi = max(hi, t)
        if ins.mnemonic in ("ret", "jmp") and ins.address >= hi:
            return ins.address + ins.size
    return start + 1


UIMOD_COMPAT = T.UIMOD_SRC / "thinkercompat.cpp"


def _thinker_calls_back(src: Path) -> set[int]:
    """Engine functions Thinker's own code still CALLS (through the engine.cpp pointer): its engine.h keeps the
    `extern` live (it comments out the extern of every engine function it overrides with its own) and some other
    source file calls the name.  mod_tech_pick -> tech_pick, mod_calc_dim -> MapWin_calculate_dimensions, ..."""
    names = {int(a, 16): n for n, a in
             re.findall(r"^\w+\s+(\w+)\s*=\s*\(\w+\)\s*0x([0-9A-Fa-f]{6,8})\s*;", (src / "engine.cpp").read_text(
                 encoding="utf-8", errors="replace"), re.M)}
    live_externs = set(re.findall(r"^extern\s+\w+\s+(\w+)\s*;", (src / "engine.h").read_text(
        encoding="utf-8", errors="replace"), re.M))
    others = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in src.glob("*.cpp")
                       if p.name != "engine.cpp")
    called = set(re.findall(r"\b(\w+)\s*\(", others))         # one pass (a per-name search was ~75 s)
    return {a for a, n in names.items() if n in live_externs and n in called}


def _uimod_undone_sites() -> set[int]:
    """Thinker call sites uimod.dll puts back to the engine's callee at run time (thinkercompat.cpp kUndo)."""
    text = UIMOD_COMPAT.read_text(encoding="utf-8", errors="replace")
    block = text[text.index("kUndo[]"):]
    block = block[: block.index("};")]
    return {int(a, 16) for a in re.findall(r"\{\s*0x([0-9A-Fa-f]+)\s*,\s*0x[0-9A-Fa-f]+\s*,", block)}


def _dead_functions(bak: bytes, writes, src: Path) -> dict[int, tuple[int, str]]:
    """Engine functions that never run under PRACX + Thinker 5.5 (any Thinker option on): a write_jump target, or a
    function not taken by address whose every E8 caller Thinker re-points (and uimod.dll does not undo) or lies in a
    dead function, and that Thinker's code does not call back itself.  To a fixpoint."""
    lo, code = _image(bak)
    hi_text = lo + len(code)
    live = [w for w in writes if w.gating(reduced_mode=True)[0] != "never"]
    dead: dict[int, tuple[int, str]] = {}
    for w in live:
        if w.kind == "write_jump" and lo <= w.addr < hi_text:
            dead[w.addr] = (_extent(lo, code, w.addr), f"write_jump -> {w.target}")
    repointed = {w.addr for w in live if w.kind in ("write_call", "remove_call", "write_jump")} - _uimod_undone_sites()
    called_back = _thinker_calls_back(src)
    callers: dict[int, list[int]] = {}
    callee_of: dict[int, int] = {}
    for m in re.finditer(rb"\xE8", code):
        site = lo + m.start()
        if m.start() + 5 > len(code):
            continue
        tgt = (site + 5 + struct.unpack_from("<i", code, m.start() + 1)[0]) & 0xFFFFFFFF
        if lo <= tgt < hi_text:
            callers.setdefault(tgt, []).append(site)
            callee_of[site] = tgt
    starts: list[int] = []
    max_end: list[int] = []                                    # max_end[i] = max end over dead intervals 0..i

    def index_dead():
        starts[:] = sorted(dead)
        run = 0
        max_end[:] = [run := max(run, dead[a][0]) for a in starts]

    def in_dead(s: int) -> bool:                               # bisect, not a scan of ~340 intervals per site
        i = bisect.bisect_right(starts, s) - 1
        return i >= 0 and max_end[i] > s

    while True:
        index_dead()
        candidates = {callee_of[s] for s in callee_of if s in repointed or in_dead(s)}
        grew = False
        for f in sorted(candidates - set(dead)):
            if f in called_back or struct.pack("<I", f) in bak:   # Thinker calls it / taken by address
                continue
            if all(s in repointed or in_dead(s) for s in callers[f]):
                dead[f] = (_extent(lo, code, f), "every caller re-pointed or dead")
                grew = True
        if not grew:
            return dead


@pytest.fixture(scope="module")
def census(need_local, bak_bytes):
    need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)")
    need_local(UIMOD_COMPAT, "the uimod.dll source (src/uimod)")
    dead = _dead_functions(bak_bytes, T.load_thinker()["writes"], T.THINKER_SRC)
    sites, _, _ = T.load_sites()
    inside = {}
    for s in sites:
        for a, (e, why) in dead.items():
            if a <= s["va"] < e:
                inside[s["id"]] = (a, why)
    return dead, inside


def test_the_new_game_flow_is_dead_under_thinker(census):
    dead, _ = census
    for name, va in (("config_game", 0x589D30), ("map_menu", 0x58D6B0), ("top_menu", 0x58E360)):
        assert va in dead, f"{name} {va:#x} no longer measured as unreachable under Thinker -- the census is blind"


def test_no_unaccounted_site_in_code_thinker_never_runs(census):
    _, inside = census
    unaccounted = {k: f"{a:#x} ({why})" for k, (a, why) in inside.items() if k not in DEAD_UNDER_THINKER}
    assert not unaccounted, ("sites that never run under Thinker 5.5 -- give each its Thinker-path twin (like "
                             "t_fpw_exit), then record it in DEAD_UNDER_THINKER: " + repr(unaccounted))
    stale = set(DEAD_UNDER_THINKER) - set(inside)
    assert not stale, f"DEAD_UNDER_THINKER entries no longer inside dead code (drop them): {sorted(stale)}"
