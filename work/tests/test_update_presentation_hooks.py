"""update.cpp's presentation hooks: the two engine ENTRIES the update prompt keys on (2026-11-10).

The prompt shows at the top of the main menu or at the start of the player's turn. Both moments used to be recognised
from the CALLER's side (three control_turn call sites; the engine top_menu's return address on the stack), and Thinker
5.5 replaces both callers with its own code, so under Thinker the offer was logged and never shown (confirmed live
2026-11-10). update.cpp now entry-detours the two engine functions every caller goes through:

  Console_human_turn 0x514050   6 prologue bytes  -> raises the turn token
  Popup_start        0x406380   9 prologue bytes  -> records each popup's label; the main menu is the "TOPMENU" one

An entry detour copies the prologue into a trampoline, so these tests pin what that needs, against everything that
writes the exe: the prologue update.cpp expects is what the game runs (the baked exe, which the Thinker overlay shares
at these bytes); no patches.yaml site, PRACX hook-table entry or Thinker 5.5 write lands in either span (a Thinker
write_jump AT the entry is the one state update.cpp chains -- none exists in 5.5); no branch anywhere in .text lands
inside a span (the trampoline would be skipped into the middle of our jmp); and the prologue holds no relative operand.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UPDATE_CPP = ROOT / "src" / "uimod" / "src" / "update.cpp"
sys.path.insert(0, str(ROOT / "work" / "scripts"))

import thinker_overlap as T  # noqa: E402

IMAGE_BASE = 0x400000

# (name, VA, prologue array in update.cpp, the two lines of update.cpp that name them)
HOOKS = {
    "Console_human_turn": (0x514050, "kHumanTurnPrologue", "kVA_ConsoleHumanTurn"),
    "Popup_start": (0x406380, "kPopupStartPrologue", "kVA_PopupStart"),
}


def _src() -> str:
    return UPDATE_CPP.read_text(encoding="utf-8", errors="replace")


def _array(name: str) -> bytes:
    m = re.search(r"const BYTE " + name + r"\[(\d+)\] = \{([^}]*)\}", _src())
    assert m, f"{name} not found in update.cpp"
    vals = bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(2)))
    assert len(vals) == int(m.group(1))
    return vals


def _va(name: str) -> int:
    m = re.search(r"constexpr uintptr_t " + name + r"\s*=\s*0x([0-9A-Fa-f]+);", _src())
    assert m, f"{name} not found in update.cpp"
    return int(m.group(1), 16)


def _spans() -> dict:
    return {n: (va, _array(arr)) for n, (va, arr, vname) in HOOKS.items()}


def _image(path: Path):
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    return pe, pe.get_memory_mapped_image()


@pytest.mark.parametrize("name", sorted(HOOKS))
def test_update_cpp_names_the_entry_it_pins(name):
    va, arr, vname = HOOKS[name]
    assert _va(vname) == va
    assert len(_array(arr)) >= 5                           # room for the E9 rel32


@pytest.mark.parametrize("name", sorted(HOOKS))
def test_the_baked_exe_runs_the_prologue_update_cpp_expects(baked_exe, bak_path, name):
    """Every build we ship (pracx; the pracx_thinker overlay differs only at its 4 excluded sites) and the clean base
    it is baked from hold exactly the bytes the detour copies."""
    va, prologue = _spans()[name]
    for path in (baked_exe, bak_path):
        _, img = _image(path)
        assert img[va - IMAGE_BASE: va - IMAGE_BASE + len(prologue)] == prologue, f"{path.name} at {va:#x}"


def test_the_prologues_carry_no_relative_operand():
    """The trampoline runs the copied bytes from another address: only absolute / register operands survive that."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    for name, (va, prologue) in _spans().items():
        insns = list(md.disasm(prologue, va))
        assert sum(i.size for i in insns) == len(prologue), f"{name}: the copy must end on an instruction boundary"
        for i in insns:
            assert not (capstone.CS_GRP_JUMP in i.groups or capstone.CS_GRP_CALL in i.groups
                        or capstone.CS_GRP_BRANCH_RELATIVE in i.groups), f"{name}: {i.mnemonic} {i.op_str}"
            for op in i.operands:
                assert not (op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_EIP), name


def test_no_patches_yaml_site_or_cave_touches_either_entry():
    sites, caves, _ = T.load_sites()
    assert len(sites) > 1000                                 # the live patch set, not an empty parse
    hits = []
    for name, (va, prologue) in _spans().items():
        lo, hi = va, va + len(prologue)
        hits += [(name, s["id"]) for s in sites if s["va"] < hi and lo < s["va"] + s["length"]]
        hits += [(name, cid) for cid, cva, clen in caves if cva < hi and lo < cva + clen]
    assert not hits


def test_no_pracx_hook_table_entry_touches_either_entry(need_local):
    """PRACX rewrites exe bytes at startup from three tables (refs/pracx/shared/pracx.cpp; _cx(SMAC, SMACX) -> the
    second address is ours). Hooks write the rel32 FIELD (4 bytes at the address); API swaps 4; changes up to 4 --
    taken as 8 everywhere, conservatively."""
    src = need_local(ROOT / "refs" / "pracx" / "shared" / "pracx.cpp", "the PRACX source clone (refs/pracx)")
    text = src.read_text(encoding="utf-8", errors="replace")
    addrs = [int(m.group(1), 16) for m in re.finditer(r"_cx\(\s*0x[0-9A-Fa-f]+\s*,\s*0x([0-9A-Fa-f]+)\s*\)", text)]
    assert len(addrs) > 40                                   # the three tables, not a parse that found nothing
    for name, (va, prologue) in _spans().items():
        bad = [hex(a) for a in addrs if a < va + len(prologue) and va < a + 8]
        assert not bad, f"{name}: PRACX writes at {bad}"


def test_thinkers_own_game_loop_and_menu_go_through_the_hooked_entries(need_local):
    """THE PREMISE of the 2026-11-10 fix, read from Thinker's source: its replacements of control_turn and top_menu
    reach the engine through the very two functions we hook -- its function pointers name the engine addresses,
    its control_turn calls Console_human_turn, its top_menu starts the "TOPMENU" popup with Popup_start before
    SetupWin_do_menu_2. A Thinker that stops doing any of this fails here, not as a silently missing prompt."""
    src = need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)").parent
    engine = (src / "engine.cpp").read_text(encoding="utf-8", errors="replace")
    assert re.search(r"FPopup_start\s+Popup_start\s*=\s*\(FPopup_start\)\s*0x406380\s*;", engine)
    assert re.search(r"FConsole\s+Console_human_turn\s*=\s*\(FConsole\)\s*0x514050\s*;", engine)
    turn = (src / "gameturn.cpp").read_text(encoding="utf-8", errors="replace")
    body = turn[turn.index("void __cdecl control_turn()"):]
    body = body[:body.index("\n}\n")]                             # control_turn itself, not the rest of the file
    assert body.count("Console_human_turn(MapWin)") >= 2          # the turn loop's calls (and the resume one)
    # and Thinker's control_game, the loop it installs at WinMain, is what calls that control_turn
    game_loop = (src / "game.cpp").read_text(encoding="utf-8", errors="replace")
    assert "control_turn();" in game_loop
    game = (src / "game.cpp").read_text(encoding="utf-8", errors="replace")
    top = game[game.index("int __cdecl top_menu(int flag)"):]
    top = top[:top.index("\n}\n")]
    i = top.index("Popup_start(")
    assert '"TOPMENU"' in top[i:i + 200]                          # the label the gate asks for
    assert top.index("SetupWin_do_menu_2(&cur_setup, &cur_popup", i) > i
    # and nothing in Thinker rebinds either pointer or jumps/calls over the engine entry
    patch = (src / "patch.cpp").read_text(encoding="utf-8", errors="replace")
    assert not re.search(r"write_(jump|call|offset)\(\s*0x(00)?(406380|514050)\b", patch)


def test_update_cpp_gates_on_the_label_and_hooks_both_entries():
    s = _src()
    gate = s[s.index("bool MainMenuIdle()"):]
    gate = gate[:gate.index("\n}\n")]
    assert 'const int topmenu = g_popupLabels.Is(popup, "TOPMENU");' in gate
    assert "if (topmenu >= 0) return topmenu == 1;" in gate          # a recorded label DECIDES, before the scan
    assert gate.index("return topmenu == 1;") < gate.index("StackFindReturn(kVA_TopMenuRet")
    arm = s[s.index("void ArmPresentationHooks()"):]
    arm = arm[:arm.index("\n}\n")]
    assert "DetourEntry(kVA_PopupStart, kPopupStartPrologue" in arm
    assert "DetourEntry(kVA_ConsoleHumanTurn, kHumanTurnPrologue" in arm
    # armed exactly when something may be shown: a startup notice (queued before or after), or a check that started
    inst = s[s.index("void InstallUpdateCheck()"):]
    inst = inst[:inst.index("\n}\n")]
    assert inst.index('GetModuleHandleA("prax.dll")') < inst.index("g_hooksAllowed = true;")
    assert "if (g_noticePending) ArmPresentationHooks();" in inst
    assert inst.rindex("ArmPresentationHooks();") > inst.index("g_phase = kPhaseWaiting;")
    queue = s[s.index("void UpdateQueueStartupNotice("):]
    queue = queue[:queue.index("\n}\n")]
    assert queue.index("g_noticePending = true;") < queue.index("ArmPresentationHooks();")
    # the turn gate refuses the live scenario editor bit only (0x8000000 outlives the editor in saves)
    turn = s[s.index("bool TurnBegan()"):]
    turn = turn[:turn.index("\n}\n")]
    assert "Rd<uint32_t>(kVA_GameState) & kStateScenarioEditor" in turn
    assert re.search(r"constexpr uint32_t\s+kStateScenarioEditor\s*=\s*0x40;", s)
    assert "0x8000000u" not in turn
    # the stub reads the label where Popup_start's caller put it: [esp+8] at entry, +0x20 after pushad
    stub = s[s.index("void StubPopupStart()"):]
    stub = stub[:stub.index("\n}\n")]
    assert stub.index("pushad") < stub.index("[esp + 0x28]") < stub.index("popad") < stub.index("jmp  dword ptr [g_popupStartNext]")


def test_thinker_55_writes_nothing_inside_either_entry(need_local):
    src = need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)").parent
    th = T.load_thinker(src)
    assert len(th["writes"]) > 8000                          # the whole 5.5 surface (test_thinker_overlap pins counts)
    for name, (va, prologue) in _spans().items():
        lo, hi = va, va + len(prologue)
        # conservative footprint: a write_call may be 6 bytes (FF15 site), a read_check its operand width
        bad = [(w.kind, hex(w.addr), w.text[:80]) for w in th["writes"]
               if w.addr < hi and lo < w.addr + max(w.length, w.width, 6)]
        assert not bad, f"{name}: Thinker 5.5 writes {bad}"


def test_no_branch_in_the_exe_lands_inside_either_span(baked_exe):
    """A jump into the middle of a detoured span would run half of our E9. Every byte of every executable section is
    read as the start of an E8 / E9 / Jcc rel32 / EB / Jcc rel8 (over-approximating: bytes inside other instructions
    count too) and none may target entry+1 .. entry+n-1. Measured 2026-11-10: zero such bytes in the whole image,
    so no disassembly is needed to tell real branches from look-alikes."""
    import numpy as np
    pe, img = _image(baked_exe)
    inner = {}
    for name, (va, prologue) in _spans().items():
        for a in range(va + 1, va + len(prologue)):
            inner[a] = name
    want = np.array(sorted(inner), dtype=np.int64)
    hits = []
    for sec in pe.sections:
        if not sec.Characteristics & 0x20000000:            # IMAGE_SCN_MEM_EXECUTE
            continue
        base = sec.VirtualAddress
        d = np.frombuffer(img[base: base + sec.Misc_VirtualSize] + b"\0" * 8, dtype=np.uint8)
        n = len(d) - 8
        va = (IMAGE_BASE + base) + np.arange(n, dtype=np.int64)
        def rel32(k):                                        # little-endian signed dword at byte offset +k
            w = (d[k:k + n].astype(np.int64) | d[k + 1:k + 1 + n].astype(np.int64) << 8 |
                 d[k + 2:k + 2 + n].astype(np.int64) << 16 | d[k + 3:k + 3 + n].astype(np.int64) << 24)
            return np.where(w >= 1 << 31, w - (1 << 32), w)
        op = d[:n]
        r8 = d[1:1 + n].astype(np.int8).astype(np.int64)
        cases = [
            ("rel32", (op == 0xE8) | (op == 0xE9), va + 5 + rel32(1)),
            ("jcc32", (op == 0x0F) & (d[1:1 + n] >= 0x80) & (d[1:1 + n] <= 0x8F), va + 6 + rel32(2)),
            ("rel8", (op == 0xEB) | ((op >= 0x70) & (op <= 0x7F)), va + 2 + r8),
        ]
        for kind, mask, target in cases:
            sel = mask & np.isin(target, want)
            hits += [(kind, hex(int(a)), inner[int(t)]) for a, t in zip(va[sel], target[sel])]
    assert not hits, hits
