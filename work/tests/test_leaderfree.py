"""uimod leaderfree.cpp / leaderfree_core.h -- an AI probe team "freeing a captured faction leader" reset a LIVING
faction to a colony pod (base-game bug; Thinker's / Scient's fix 27).

The base game's AI pick (probe 0x59F120, loop 0x5A29B9..0x5A2A3E) treats captured slot i as faction i + 1; the engine
fills slots first-free (mon_killed_faction 0x477A60), so the AI frees the wrong faction -- one that is alive, whose
bases and units setup_player then deletes.  The fix replaces the loop with a jump to a stub that asks
leaderfree::Pick (the base game's own preference rule on the faction each slot really holds) and hands back the loop's
exact post-state.  Under Thinker Mod it writes nothing (Thinker replaces probe() and fixes this itself).

Pinned here:
  1. the bytes the DLL checks are the shipped exe's, and our own bake leaves them alone;
  2. Pick (native build of the header) against hand cases with stated reasons and a reference over random cases;
  3. Unicorn on the PRISTINE loop: the bug reproduced (a living faction picked), and the loop equals one rule function
     with the base game's parameters (slot i = faction i + 1, the pick's pact read at pick + 1, 7 rows) on random
     states -- the fix is that function with the corrected parameters, so the preference rule is the base game's own;
  4. Unicorn on the stub (assembled from the source text): every register and loop local at 0x5A2A3E equals the
     pristine loop's, and the pick function gets (prober, jailer);
  5. Thinker: it replaces probe() unconditionally, carries its own fix, no Thinker write touches our site, and the
     pick stands down on thinker.dll before reading or writing any of its code;
  6. the jailer's message: every byte it checks in the exes and in thinker.dll 5.5, the one write after all the checks,
     both call stubs in Unicorn (arguments, rescuer source, the caller's registers), which side gets which text, and the
     text's limits (fixed line buffer, the same image as the rescuer);
  7. the homeless probe: the one byte, base game only, in the real code;
  8. the landing search: the checked bytes, the hook's place (no branch into it, no register carried past it), the
     draw band and the shuffle against the game's own code, the passes against a reference, and whole searches run
     through the game's real loop in Unicorn.
"""
from __future__ import annotations

import pathlib
import random
import re
import struct
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402
import thinker_overlap as T  # noqa: E402

UIMOD = ROOT.parent / "src" / "uimod" / "src"
SRC = (UIMOD / "leaderfree.cpp").read_text(encoding="utf-8")
INIT = (UIMOD / "init.cpp").read_text(encoding="utf-8")

ENTRY, LOOP, RESUME = 0x59F120, 0x5A29B9, 0x5A2A3E
CAPTURED, ALIVE, DIPLO = 0x94CD58, 0x9A64E9, 0x96C9F8
MON, SLOT, FAC = 0x4F4, 0x38, 0x20CC
PACT, TREATY, VENDETTA = 0x1, 0x2, 0x10


def loop_rule(rows, diplo, faction_of, pick_diplo, valid):
    """The AI's choice as one function: for each occupied slot, the candidate faction_of(i, f); skip invalid ones and
    vendetta; take it when nothing is picked yet, on a pact, or on a treaty while the current pick (its diplomacy read
    at pick_diplo(pick)) has no pact."""
    pick = -1
    for i, (f, cap) in enumerate(rows):
        if not cap:
            continue
        g = faction_of(i, f)
        if not valid(g):
            continue
        d = diplo[g]
        if d & VENDETTA:
            continue
        if pick < 0 or d & PACT or (d & TREATY and not diplo[pick_diplo(pick)] & PACT):
            pick = g
    return pick


def vanilla_rule(rows7, diplo9):
    """The base game, as written: slot i is faction i + 1, the current pick's pact is read one faction too far
    (diplo_status[pick + 1]; [8] is the next field), 7 rows, no validity check."""
    return loop_rule(rows7, diplo9, lambda i, f: i + 1, lambda p: p + 1, lambda g: True)


def ref_pick(slots, alive, diplo, prober, jailer):
    """The fix: the same rule with the slot's real faction and the pick's own diplomacy, over the 6 real slots, for a
    faction that can be freed (1..7, eliminated, neither side of the probe)."""
    def valid(g):
        return 1 <= g <= 7 and g not in (prober, jailer) and not alive & (1 << g)
    return loop_rule(slots[:6], diplo, lambda i, f: f, lambda p: p, valid)


def _bytes_at(path: pathlib.Path, va: int, n: int) -> bytes:
    return T.Image(path).rd(va, n)


def _array(name: str) -> bytes:
    m = re.search(rf"const BYTE {name}\[[^\]]*\]\s*=\s*\{{(.*?)\}};", SRC, re.S)
    assert m, name
    return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


# ---------------------------------------------------------------------------------------------- 1. the checked bytes
def test_checked_bytes_are_the_shipped_exes(bak_path):
    assert "kVA_ProbeEntry = 0x59F120" in SRC and "kVA_PickLoop   = 0x5A29B9" in SRC and "kVA_Resume     = 0x5A2A3E" in SRC
    loop = _array("kExpectLoop")
    assert len(loop) == RESUME - LOOP                                    # the whole loop, nothing past its exit
    assert loop == _bytes_at(bak_path, LOOP, RESUME - LOOP)
    assert _array("kExpectEntry") == _bytes_at(bak_path, ENTRY, 8)
    for va, want in [("kVA_Captured   = 0x94CD58", 1), ("kVA_Alive      = 0x9A64E9", 1), ("kVA_Diplo      = 0x96C9F8", 1)]:
        assert SRC.count(va) == want, va


def test_plain_terranx_has_the_same_bytes(bak_path):
    """'Both exes': the un-PRACX'd terranx.exe beside it (when present) carries the identical entry and loop."""
    plain = bak_path.parent / "terranx.exe"
    if not plain.exists():
        pytest.skip("no plain terranx.exe beside the PRACX exe")
    for va, n in [(ENTRY, 8), (LOOP, RESUME - LOOP)]:
        assert _bytes_at(plain, va, n) == _bytes_at(bak_path, va, n)


def test_our_bake_leaves_the_loop_and_entry_alone(bak_path, baked_exe):
    for va, n in [(ENTRY, 8), (LOOP, RESUME - LOOP)]:
        assert _bytes_at(baked_exe, va, n) == _bytes_at(bak_path, va, n)


# ---------------------------------------------------------------------------------------------- 2. Pick, native
@pytest.fixture(scope="module")
def core():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    exe = cpp_harness.build(ROOT / "tests" / "leaderfree_selftest.cpp", "leaderfree_selftest_")

    def run(cases):
        if cases and isinstance(cases[0], str):                       # raw "tables ..." lines
            out = subprocess.run([str(exe)], input="\n".join(cases) + "\n", capture_output=True, text=True,
                                 check=True, timeout=60).stdout.split()
            assert len(out) == len(cases) and "bad" not in out, out
            return [int(x) for x in out]
        lines = []
        for slots, alive, diplo, prober, jailer in cases:
            flat = [prober, jailer, alive, *diplo] + [v for s in slots for v in s]
            lines.append(" ".join(map(str, flat)))
        out = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True,
                             check=True, timeout=60).stdout.split()
        assert len(out) == len(cases)
        return [int(x) for x in out]
    return run


def _slots(*pairs):
    s = list(pairs) + [(0, 0)] * (6 - len(pairs))
    return s[:6]


def _d(**kw):
    d = [0] * 8
    for k, v in kw.items():
        d[int(k[1:])] = v
    return d


ALIVE_123 = (1 << 1) | (1 << 2) | (1 << 3)          # player 1, prober 2, jailer 3 alive

HAND = [
    # (slots, alive, diplo, prober, jailer), want, why
    ((_slots((5, 1)), ALIVE_123, _d(), 2, 3), 5, "the reported bug: first captive is faction 5, never faction 1"),
    ((_slots(), ALIVE_123, _d(), 2, 3), -1, "no captive: the AI does not choose the action"),
    ((_slots((5, 0)), ALIVE_123, _d(), 2, 3), -1, "a cleared slot is no captive"),
    ((_slots((5, 1)), ALIVE_123 | 1 << 5, _d(), 2, 3), -1, "a captive that is alive again is not freed (would be reset)"),
    ((_slots((1, 1)), ALIVE_123, _d(), 2, 3), -1, "the living player is never a captive"),
    ((_slots((2, 1)), 0, _d(), 2, 3), -1, "never the prober itself, even with stale alive bits"),
    ((_slots((3, 1)), 0, _d(), 2, 3), -1, "never the jailer itself"),
    ((_slots((0, 1)), ALIVE_123, _d(), 2, 3), -1, "faction 0 (natives) is not a leader"),
    ((_slots((8, 1)), ALIVE_123, _d(), 2, 3), -1, "out of range"),
    ((_slots((-1, 1)), ALIVE_123, _d(), 2, 3), -1, "out of range (negative)"),
    ((_slots((5, 1)), ALIVE_123, _d(d5=VENDETTA), 2, 3), -1, "vendetta with the captive: base game skips it"),
    ((_slots((5, 1), (6, 1)), ALIVE_123, _d(d6=PACT), 2, 3), 6, "pact partner wins over a stranger"),
    ((_slots((5, 1), (6, 1)), ALIVE_123, _d(d5=PACT), 2, 3), 5, "a later stranger does not displace a pact partner"),
    ((_slots((5, 1), (6, 1)), ALIVE_123, _d(d6=TREATY), 2, 3), 6, "treaty partner wins over a stranger"),
    ((_slots((5, 1), (6, 1)), ALIVE_123, _d(d5=PACT, d6=TREATY), 2, 3), 5, "a treaty does not displace a pact"),
    ((_slots((5, 1), (6, 1)), ALIVE_123, _d(d5=PACT, d6=PACT), 2, 3), 6, "the last pact partner wins (base game order)"),
    ((_slots((5, 1), (6, 1)), ALIVE_123, _d(), 2, 3), 5, "strangers only: the first"),
    ((_slots((0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (7, 1)), ALIVE_123, _d(), 2, 3), 7, "the 6th slot counts"),
]


def test_pick_hand_cases(core):
    got = core([c for c, _, _ in HAND])
    for (c, want, why), g in zip(HAND, got):
        assert g == want, why
        assert ref_pick(*c) == want, why


def _random_case(rnd: random.Random):
    prober, jailer = rnd.sample(range(1, 8), 2)
    slots = [(rnd.choice([-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]), rnd.choice([0, 0, 1, 1, 1, 7])) for _ in range(6)]
    alive = rnd.getrandbits(8) | 1 << prober | 1 << jailer
    diplo = [rnd.choice([0, PACT, TREATY, PACT | TREATY, VENDETTA, VENDETTA | PACT, 0x20, 0x1000, 0x30]) for _ in range(8)]
    return slots, alive, diplo, prober, jailer


def test_pick_matches_the_reference(core):
    rnd = random.Random(0x1EADF)
    cases = [_random_case(rnd) for _ in range(4000)]
    assert core(cases) == [ref_pick(*c) for c in cases]


# ---------------------------------------------------------------------------------------------- 3/4. Unicorn
STACK, STUB, PICKFN, SCR = 0x00200000, 0x00310000, 0x00320000, 0x00330000
EBP = STACK + 0x8000
KILLED, GAME_YEAR, CUR_PLAYER, MONUMENTS, STOP = 0x477A60, 0x5C89A0, 0x939284, 0x94CA08, 0x00340000


def _stub_asm() -> str:
    m = re.search(r"void StubPick\(\)\s*\{\s*__asm \{(.*?)\n    \}\n\}", SRC, re.S)
    assert m
    lines = []
    for raw in m.group(1).split("\n"):
        code = raw.partition("//")[0].strip()
        if not code:
            continue
        code = code.replace("call PickFromEngine", f"call {PICKFN:#x}")
        code = code.replace("jmp  dword ptr [g_resume]", f"jmp {RESUME:#x}")
        assert "g_" not in code and "PickFromEngine" not in code, code
        lines.append(code)
    return "\n".join(lines)


@pytest.fixture(scope="module")
def emu(bak_path):
    pytest.importorskip("unicorn", reason="unicorn absent -- the loop emulation is unverified")
    import pefile
    from keystone import KS_ARCH_X86, KS_MODE_32, Ks
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn import x86_const as X

    pe = pefile.PE(str(bak_path), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    regs = {n: getattr(X, f"UC_X86_REG_{n.upper()}") for n in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp")}

    def machine(fixed: bool):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = base + s.VirtualAddress
            uc.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            uc.mem_write(va, s.get_data())
        for b in (STACK, STUB, PICKFN, SCR, STOP):
            uc.mem_map(b, 0x10000)
        if fixed:                                          # code first, before any run (stale-translation rule)
            uc.mem_write(STUB, bytes(ks.asm(_stub_asm(), STUB)[0]))
            fn = (f"mov eax, [esp + 4]; mov [{SCR:#x}], eax; mov eax, [esp + 8]; mov [{SCR + 4:#x}], eax; "
                  f"mov eax, [{SCR + 8:#x}]; ret")
            uc.mem_write(PICKFN, bytes(ks.asm(fn, PICKFN)[0]))
            jump = bytes(ks.asm(f"jmp {STUB:#x}", LOOP)[0]) + b"\x90\x90"
            assert len(jump) == 7
            uc.mem_write(LOOP, jump)
        return uc

    vanilla, fixed = machine(False), machine(True)
    writer = machine(False)                                # runs the engine's own mon_killed_faction
    writer.mem_write(GAME_YEAR, bytes(ks.asm("xor eax, eax; ret", GAME_YEAR)[0]))   # before any run
    writer.mem_write(CUR_PLAYER, struct.pack("<i", -1))   # never the plaque popup (monument(1))
    for j in range(8):
        writer.mem_write(MONUMENTS + j * MON + 15 * SLOT, b"\0" * (6 * SLOT))

    def kill(killer, victim):
        esp = EBP - 0x400
        writer.mem_write(esp, struct.pack("<III", STOP, killer, victim))
        writer.reg_write(regs["esp"], esp)
        writer.emu_start(KILLED, STOP, count=2000)

    def tables(path: pathlib.Path, alive: int, prober: int, diplo) -> pathlib.Path:
        writer.mem_write(DIPLO + prober * FAC, struct.pack("<8i", *diplo))
        path.write_bytes(bytes(writer.mem_read(CAPTURED, 8 * MON)) + bytes([alive]) + bytes(writer.mem_read(DIPLO, 8 * FAC)))
        return path

    def run(uc, slots, alive, diplo, prober, jailer, row6=(0, 0), ret=None):
        for j in range(8):                                 # every faction's 7 rows / diplo row: clean slate
            for i in range(7):
                uc.mem_write(CAPTURED + j * MON + i * SLOT, struct.pack("<ii", 0, 0) + b"\0" * 4)
            uc.mem_write(DIPLO + j * FAC, b"\0" * 36)          # diplo_status[0..7] + the next field
        for i, (f, cap) in enumerate(slots):
            uc.mem_write(CAPTURED + jailer * MON + i * SLOT, struct.pack("<i", f))
            uc.mem_write(CAPTURED + jailer * MON + i * SLOT + 8, struct.pack("<i", cap))
        uc.mem_write(CAPTURED + jailer * MON + 6 * SLOT, struct.pack("<i", row6[0]))
        uc.mem_write(CAPTURED + jailer * MON + 6 * SLOT + 8, struct.pack("<i", row6[1]))
        uc.mem_write(DIPLO + prober * FAC, struct.pack(f"<{len(diplo)}i", *diplo))
        uc.mem_write(ALIVE, bytes([alive & 0xFF]))
        uc.mem_write(EBP - 0x64, struct.pack("<i", -1))
        uc.mem_write(EBP - 0x1C, struct.pack("<i", 0))
        uc.mem_write(EBP - 0x2C, struct.pack("<i", 0x5EED))
        uc.mem_write(EBP - 0x28, struct.pack("<i", 0x5EED))
        uc.mem_write(SCR, struct.pack("<iii", -99, -99, -1 if ret is None else ret))
        for n, v in (("eax", 0xA1), ("ecx", 0xC1), ("edx", 0xD1), ("edi", 0xE1)):
            uc.reg_write(regs[n], v)
        uc.reg_write(regs["ebx"], prober)
        uc.reg_write(regs["esi"], jailer)
        uc.reg_write(regs["ebp"], EBP)
        uc.reg_write(regs["esp"], EBP - 0x400)
        uc.emu_start(LOOP, RESUME, count=5000)
        assert uc.reg_read(X.UC_X86_REG_EIP) == RESUME
        st = {n: uc.reg_read(r) for n, r in regs.items()}
        for off in (0x64, 0x1C, 0x2C, 0x28):
            st[f"[ebp-{off:#x}]"] = struct.unpack("<i", uc.mem_read(EBP - off, 4))[0]
        st["args"] = struct.unpack("<ii", uc.mem_read(SCR, 8))
        return st

    run.writer, run.kill, run.tables = writer, kill, tables
    return vanilla, fixed, run


def test_reader_finds_what_the_engines_writer_wrote(emu, core, tmp_path):
    """PickFromTables (what the DLL runs) on raw memory filled by the engine's own mon_killed_faction 0x477A60: the
    strides, the payload / flag offsets and the per-jailer base are the engine's, not the test's.  The flag address is
    the one the free's clean-up clears (0x94CD60, read by the base game's loop too)."""
    _, _, run = emu
    for killer, victim in [(3, 5), (3, 6), (3, 1), (7, 4)]:
        run.kill(killer, victim)
    alive = 1 << 2 | 1 << 3 | 1 << 7                                   # 1, 4, 5, 6 eliminated
    cases = [
        (run.tables(tmp_path / "a", alive, 2, _d(d6=PACT)), 2, 3, 6),     # jailer 3 holds 5, 6, 1: the pact partner
        (run.tables(tmp_path / "b", alive, 2, _d(d1=TREATY)), 2, 3, 1),   # ... the treaty partner (3rd slot)
        (run.tables(tmp_path / "c", alive, 2, _d()), 2, 3, 5),            # ... else the first
        (run.tables(tmp_path / "d", alive | 1 << 5, 2, _d()), 2, 3, 6),   # 5 alive again: skipped
        (run.tables(tmp_path / "e", alive, 2, _d(d5=VENDETTA, d6=VENDETTA, d1=VENDETTA)), 2, 3, -1),
        (run.tables(tmp_path / "f", alive, 2, _d()), 2, 7, 4),            # jailer 7 (last stride) holds 4
        (run.tables(tmp_path / "g", alive, 3, _d()), 3, 2, -1),           # jailer 2 holds nobody
    ]
    run.writer.mem_write(CAPTURED + 8 + 3 * MON + 0 * SLOT, struct.pack("<i", 0))   # the free's clean-up of slot 0
    cases.append((run.tables(tmp_path / "h", alive, 2, _d()), 2, 3, 6))             # 5 freed: 6 is first now
    got = core([f"tables {p} {prober} {jailer}" for p, prober, jailer, _ in cases])
    assert got == [want for *_, want in cases]


def test_alive_and_slot_addresses_are_the_engines(bak_path):
    """The free itself sets the alive bit at FactionStatus[1] 0x9A64E9 and clears the captured flag via 0x94CD60."""
    img = T.Image(bak_path)
    assert img.rd(0x5A3C82, 5) == bytes.fromhex("A0E9649A00")           # mov al, [0x9A64E9]
    assert img.rd(0x5A3C91, 5) == bytes.fromhex("A2E9649A00")           # mov [0x9A64E9], al
    assert img.rd(0x5A3CC6, 7) == bytes.fromhex("8D049560CD9400")       # lea eax, [edx*4 + 0x94CD60]
    assert img.rd(0x5A3CD2, 3) == bytes.fromhex("3970F8")               # cmp [eax-8], esi: the id 8 bytes before
    assert "PickFromTables(At(kVA_Captured), *At(kVA_Alive), At(kVA_Diplo), prober, jailer)" in SRC


def _answer(st):
    return st["[ebp-0x64]"] if st["[ebp-0x1c]"] else -1


def test_vanilla_frees_a_living_faction(emu):
    vanilla, _, run = emu
    # Jailer 3 holds faction 5's leader (slot 0); the player (faction 1) is alive. The base game frees faction 1.
    st = run(vanilla, _slots((5, 1)), ALIVE_123, _d(), 2, 3)
    assert _answer(st) == 1
    # A second captive in slot 1 makes it faction 2 -- the probing faction itself (no pact/treaty: first one wins,
    # so give faction 2's "slot" a pact to show the misread diplomacy row decides it).
    st = run(vanilla, _slots((5, 1), (6, 1)), ALIVE_123, _d(d2=PACT), 2, 3)
    assert _answer(st) == 2
    # Nothing captured, but the loop's 7th round reads past the six slots: anything there "frees" faction 7.
    st = run(vanilla, _slots(), ALIVE_123 | 1 << 7, _d(), 2, 3, row6=(0, 1))
    assert _answer(st) == 7
    # Same three states, fixed rule: the real captive, the real captive, nobody.
    assert ref_pick(_slots((5, 1)), ALIVE_123, _d(), 2, 3) == 5
    assert ref_pick(_slots((5, 1), (6, 1)), ALIVE_123, _d(d2=PACT), 2, 3) == 5
    assert ref_pick(_slots(), ALIVE_123 | 1 << 7, _d(), 2, 3) == -1


def _any_state(rnd: random.Random):
    """Anything the tables can hold: 7 rows (the loop reads a 7th), 9 diplomacy words (it can read [8])."""
    prober, jailer = rnd.sample(range(1, 8), 2)
    rows = [(rnd.choice([0, 1, 2, 3, 4, 5, 6, 7]), rnd.choice([0, 1, 1, 5])) for _ in range(7)]
    diplo = [rnd.choice([0, PACT, TREATY, PACT | TREATY, VENDETTA, VENDETTA | TREATY, 0x20, 0x1000]) for _ in range(9)]
    return rows, rnd.getrandbits(8), diplo, prober, jailer


def test_the_base_games_loop_is_exactly_the_rule(emu, core):
    """The emulated pristine loop equals loop_rule with the base game's parameters on every state -- so the fix (the
    same function with the slot's real faction, the pick's own diplomacy, 6 rows, a freeable faction) keeps the base
    game's preference rule and changes only what it is applied to.  The native Pick agrees with the reference."""
    vanilla, _, run = emu
    rnd = random.Random(0xFA1)
    cases = [_any_state(rnd) for _ in range(800)]
    for rows, alive, diplo, prober, jailer in cases:
        st = run(vanilla, rows[:6], alive, diplo, prober, jailer, row6=rows[6])
        assert _answer(st) == vanilla_rule(rows, diplo), (rows, diplo)
    six = [(rows[:6], alive, diplo[:8], prober, jailer) for rows, alive, diplo, prober, jailer in cases]
    assert core(six) == [ref_pick(*c) for c in six]


ANSWER = ("[ebp-0x64]", "[ebp-0x1c]")


def test_stub_hands_back_the_loops_exact_state(emu):
    """The code after 0x5A2A3E cannot tell the stub from the loop but by the answer: every register and both loop
    locals equal the pristine loop's; the answer is the pick function's (none: [ebp-0x64] stays -1, flag 0)."""
    vanilla, fixed, run = emu
    rnd = random.Random(0x5708)
    cases = [(r[:6], a, d[:8], p, j) for r, a, d, p, j in (_any_state(rnd) for _ in range(300))] + [
        (_slots(), ALIVE_123, _d(), 2, 3),
        (_slots((5, 1)), ALIVE_123, _d(), 2, 3),
        (_slots(), 1 << 1 | 1 << 7, _d(), 1, 7),                 # extremes of both strides
        (_slots(), 1 << 7 | 1 << 1, _d(), 7, 1),
    ]
    seen = set()
    for c in cases:
        want = ref_pick(*c)
        seen.add(want >= 0)
        v, f = run(vanilla, *c), run(fixed, *c, ret=want)
        assert f["args"] == (c[3], c[4]), c
        assert (f["[ebp-0x64]"], f["[ebp-0x1c]"]) == ((want, 1) if want >= 0 else (-1, 0)), c
        for k in ("args",) + ANSWER:
            f.pop(k), v.pop(k)
        assert f == v, c
    assert seen == {True, False}


# ---------------------------------------------------------------------------------------------- 5. Thinker
@pytest.fixture(scope="module")
def thinker_src(need_local) -> pathlib.Path:
    return need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)").parent


@pytest.fixture(scope="module")
def thinker(thinker_src) -> dict:
    return T.load_thinker(thinker_src)


def test_thinker_replaces_probe_in_every_mode(thinker):
    """Premise of standing down: under Thinker the base game's probe body (our site) never runs."""
    for reduced in (True, False):
        known = T.forced_options(thinker.get("assigns", []), reduced)
        jumps = [w for w in thinker["writes"] if w.kind == "write_jump" and w.addr == ENTRY]
        assert len(jumps) == 1 and jumps[0].gating(reduced, known)[0] == "always", reduced


def test_thinker_carries_its_own_fix(thinker_src):
    """Premise of 'nothing to add under Thinker': its probe() picks real, eliminated captives (Thinker fix 27)."""
    probe = (thinker_src / "probe.cpp").read_text(encoding="utf-8")
    assert probe.count("captured_leaders(tgt_fc_id)") >= 2                 # the AI's choice and the free itself
    assert "!is_alive(plr_id)" in probe and "Monuments[faction_id].data2[i][7]" in probe
    assert "reset_captured_leader(tgt_fc_id, capture_id)" in probe


def test_the_shipped_thinker_dll_replaces_probe_and_never_names_our_site(need_local):
    """The release binary, not just the v5.5 source: patch_setup's straight-line store of E9 at 0x59F120 (mov byte
    [0x59F120], 0xE9; mov dword [0x59F121], rel32) is present, and no 32-bit constant in the DLL falls in the loop."""
    dll = need_local(ROOT.parent / "refs" / "thinker-release" / "v5.5" / "thinker.dll", "the Thinker 5.5 release").read_bytes()
    assert dll.count(bytes.fromhex("C605 20F15900 E9 C705 21F15900")) == 1
    hits = [i for i in range(len(dll) - 3)
            if LOOP <= struct.unpack_from("<I", dll, i)[0] < RESUME or 0x5A3C74 <= struct.unpack_from("<I", dll, i)[0] < 0x5A3C82]
    assert hits == []


def test_no_thinker_write_or_guard_touches_our_site(thinker, bak_path):
    """Even if both ever ran: no Thinker write lands in, and no Thinker guard reads, the loop we replace."""
    img = T.Image(bak_path)
    hits = [(hex(w.addr), w.kind, w.line) for w in thinker["writes"]
            if w.addr < RESUME and LOOP < w.addr + max(1, T.footprint(w, img))]
    assert hits == []


def test_stands_down_under_thinker_before_any_code_access():
    """Under Thinker the pick is never touched: the only thing that branch may do is the pinned message half."""
    body = SRC[SRC.index("void InstallLeaderFreeFix()"):]
    gate = body.index("if (ThinkerLoaded())")
    assert gate < body.index("memcmp(") and gate < body.index("VirtualProtect(") and gate < body.index("At(")
    assert re.match(r"if \(ThinkerLoaded\(\)\) \{\s*UimodLog\([^;]*;\s*InstallFreedMessageThinker\(\);\s*return;\s*\}", body[gate:]), "must return"
    # ThinkerLoaded() is decided in InstallThinkerCompat(): it must run first.
    assert INIT.index("InstallThinkerCompat();") < INIT.index("InstallLeaderFreeFix();")


# ---------------------------------------------------------------------------------------------- 6. the jailer's message
MSG_GATE, MSG_PUSH, MSG_CALL, NETMSG = 0x5A3CE3, 0x5A3D36, 0x5A3D40, 0x50B9E0
TH_CALL, TH_PUSHES, TH_PTR, TH_LABEL, TH_IMAGE, TH_SET, TH_READ = 0x8122F, 0x81220, 0xE3728, 0xFDE38, 0xFDE26, 0x7A0CE, 0x81007


def _body(name: str) -> str:
    start = SRC.index(name)
    return SRC[start:SRC.index("\n}\n", start)]


def test_message_bytes_are_the_shipped_exes(bak_path, baked_exe):
    img = T.Image(bak_path)
    assert _array("kExpectFreedGate") == img.rd(MSG_GATE, 14)
    assert _array("kExpectFreedPush") == img.rd(MSG_PUSH, 15)
    assert img.rd(0x690984, 18) == b"fac_escape_sm.pcx\0" and img.rd(0x690998, 10) == b"WILLYFREE\0"
    assert MSG_CALL + 5 + struct.unpack("<i", img.rd(MSG_CALL + 1, 4))[0] == NETMSG
    baked = T.Image(baked_exe)
    for va, n in [(MSG_GATE, 14), (MSG_PUSH, 15), (0x690984, 18), (0x690998, 10)]:
        assert baked.rd(va, n) == img.rd(va, n)
    plain = bak_path.parent / "terranx.exe"
    if plain.exists():
        p = T.Image(plain)
        for va, n in [(MSG_GATE, 14), (MSG_PUSH, 15), (0x690984, 18), (0x690998, 10)]:
            assert p.rd(va, n) == img.rd(va, n)
    # the gate says what the module assumes: rescuer in ebx, jailer in [ebp-0x14], either may see it
    assert img.rd(MSG_GATE, 14)[5:7] == bytes.fromhex("3BD8") and img.rd(MSG_GATE, 14)[9:12] == bytes.fromhex("3945EC")
    for name, off in [("kVA_FreedGate    = 0x5A3CE3", 1), ("kVA_FreedPush    = 0x5A3D36", 1), ("kVA_FreedCall    = 0x5A3D40", 1)]:
        assert SRC.count(name) == off, name


@pytest.fixture(scope="module")
def th_dll(need_local):
    import pefile
    p = need_local(ROOT.parent / "refs" / "thinker-release" / "v5.5" / "thinker.dll", "the Thinker 5.5 release")
    pe = pefile.PE(str(p))
    return pe, bytes(pe.get_memory_mapped_image()), pe.OPTIONAL_HEADER.ImageBase


def test_the_pin_is_the_supported_thinker(th_dll):
    pe, _, _ = th_dll
    v = (ROOT.parent / "src" / "uimod" / "src" / "version.h").read_text(encoding="utf-8")
    assert int(re.search(r"THINKER_SUPPORTED_STAMP (0x[0-9A-Fa-f]+)", v).group(1), 16) == pe.FILE_HEADER.TimeDateStamp
    assert int(re.search(r"THINKER_SUPPORTED_IMAGE_SIZE (0x[0-9A-Fa-f]+)", v).group(1), 16) == pe.OPTIONAL_HEADER.SizeOfImage
    for name in ("kThCall     = 0x8122F", "kThPushes   = 0x81220", "kThPointer  = 0xE3728", "kThLabel    = 0xFDE38",
                 "kThImage    = 0xFDE26", "kThSetSlot  = 0x7A0CE", "kThReadSlot = 0x81007"):
        assert SRC.count(name) == 1, name


def test_every_thinker_byte_the_module_checks(th_dll):
    _, img, base = th_dll
    abs32 = lambda off: struct.pack("<I", base + off)
    assert img[TH_CALL:TH_CALL + 6] == b"\xFF\x15" + abs32(TH_PTR)
    assert img[TH_PUSHES:TH_PUSHES + 8] == b"\xC7\x44\x24\x04" + abs32(TH_IMAGE)
    assert img[TH_PUSHES + 8:TH_PUSHES + 15] == b"\xC7\x04\x24" + abs32(TH_LABEL)
    assert img[TH_LABEL:TH_LABEL + 10] == b"WILLYFREE\0" and img[TH_IMAGE:TH_IMAGE + 18] == b"fac_escape_sm.pcx\0"
    assert struct.unpack_from("<I", img, TH_PTR)[0] == NETMSG
    assert _array("kExpectThSetSlot") == img[TH_SET:TH_SET + 6] and _array("kExpectThReadSlot") == img[TH_READ:TH_READ + 6]
    # the message is reached once, and only through the gate that compares the slot with the current player
    assert img.count(abs32(TH_LABEL)) == 1
    gate = img[0x8100D:0x81029]
    assert b"\x8B\x80\xD4\x3B\x02\x00" in gate and b"\x39\xD0\x0F\x84" in gate and b"\x39\xF0\x0F\x84" in gate   # cOwner vs edx (slot), esi (target)


def test_nothing_of_ours_or_thinkers_touches_the_message_sites(thinker, bak_path):
    """No Thinker write or guard lands on the base-game sites; no other uimod table patches the Thinker site."""
    img = T.Image(bak_path)
    for lo, hi in [(MSG_GATE, MSG_GATE + 14), (MSG_PUSH, MSG_PUSH + 15)]:
        hits = [(hex(w.addr), w.kind) for w in thinker["writes"] if w.addr < hi and lo < w.addr + max(1, T.footprint(w, img))]
        assert hits == []
    for f in UIMOD.glob("*.cpp"):
        if f.name != "leaderfree.cpp":
            text = f.read_text(encoding="utf-8", errors="replace")
            for needle in ("0x8122F", "0x81220", "0xE3728"):
                assert needle not in text, (f.name, needle)
            assert "0x5A3D40" not in text and "0x5A3CE3" not in text, f.name


# The Thinker half has five: the startup check's "not the supported build" gate (reduced mode) comes first.
@pytest.mark.parametrize("name,failures", [("void InstallFreedMessageThinker()", 5), ("void InstallFreedMessageBaseGame()", 3)])
def test_every_failure_leaves_without_writing(name, failures):
    """Each failed check logs and RETURNS; the file comes only after the bytes verified; the flag only after the file."""
    body = _body(name)
    assert len(re.findall(r'UimodLog\("[^;]*?\);\s*return;', body, re.S)) == failures
    assert body.count("WriteCode(") == 1 and body.count("BuildFreedScript()") == 1
    assert body.index("BuildFreedScript()") < body.index("g_freedTextReady = true;") < body.index("WriteCode(")
    assert "reinterpret_cast<uintptr_t>(call) + 5" in body       # rel32 is from the end of the 5-byte call, in both


def test_the_thinker_half_checks_everything_before_its_one_write():
    body = _body("void InstallFreedMessageThinker()")
    write = body.index("WriteCode(")
    build = body.index("BuildFreedScript()")
    for must in ("TimeDateStamp != kThStamp", "SizeOfImage != kThImageSize", "if (!ok)", "kExpectThSetSlot", "kExpectThReadSlot"):
        assert body.index(must) < build < write, must
    assert "BYTE e8[6] = { 0xE8, 0, 0, 0, 0, 0x90 }" in body       # the 6-byte FF 15 becomes E8 rel32 + nop


def test_the_engine_functions_we_call_are_where_we_say_and_thinker_leaves_them_alone(thinker, bak_path):
    """The call targets, from the game's own calls on this very path, and no Thinker write inside any of them."""
    img = T.Image(bak_path)
    target = lambda site: site + 5 + struct.unpack("<i", img.rd(site + 1, 4))[0]
    assert img.rd(0x5A3D26, 1) == b"\xE8" and target(0x5A3D26) == 0x50B930 and "kVA_GetNoun      = 0x50B930" in SRC
    assert img.rd(0x5A3D31, 1) == b"\xE8" and target(0x5A3D31) == 0x625EC0 and "kVA_ParseSays    = 0x625EC0" in SRC
    assert "kVA_NetMsgPop2   = 0x50B9E0" in SRC and "kVA_CurrentPlayer = 0x939284" in SRC
    assert struct.unpack("<I", img.rd(MSG_GATE + 1, 4))[0] == 0x939284
    table = (T.THINKER_SRC / "engine.cpp").read_text(encoding="utf-8")
    assert "Fpopp popp = (Fpopp)0x48C0A0;" in table and "kVA_Popp         = 0x48C0A0" in SRC
    assert (UIMOD / "aivis.cpp").read_text(encoding="utf-8").count("kVA_Popp          = 0x0048C0A0") == 1
    assert "kVA_GenderDefault = 0x9BBFEC" in SRC and "kVA_PluralDefault = 0x9BBFF0" in SRC
    for lo, hi in [(0x50B9E0, 0x50B9FD), (0x47A890, 0x47ACE2), (0x48C0A0, 0x48C31E), (0x50B930, 0x50B970), (0x625EC0, 0x625EC8)]:
        hits = [(hex(w.addr), w.kind) for w in thinker["writes"] if w.addr < hi and lo < w.addr + max(1, T.footprint(w, img))]
        assert hits == [], (hex(lo), hits)


def test_the_jailer_path_restores_the_gender_defaults():
    body = _body("int __cdecl ShowFreed")
    get, parse, restore = body.index("savedGender = *gender"), body.index("At(kVA_ParseSays)"), body.index("*gender = savedGender")
    assert get < parse < restore < body.index("At(kVA_Popp)") and "*plural = savedPlural" in body


def test_thinker_site_has_one_way_in_and_no_branch_into_its_bytes(th_dll):
    """Decoded from probe()'s entry: the message block is entered only from its two gate branches."""
    capstone = pytest.importorskip("capstone")
    _, img, base = th_dll
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    ins = list(md.disasm(img[0x7A070:0x82000], base + 0x7A070))
    addrs = {x.address - base for x in ins}
    assert TH_CALL in addrs and TH_CALL + 6 in addrs and not any(TH_CALL < a < TH_CALL + 6 for a in addrs)
    into = [(x.address - base, int(x.op_str, 16) - base) for x in ins if x.mnemonic.startswith(("j", "call")) and x.op_str.startswith("0x")
            and 0x811AA <= int(x.op_str, 16) - base <= TH_CALL + 5]
    assert sorted(into) == [(0x8101B, 0x811AA), (0x81023, 0x811AA)]
    slot_writes = [x.address - base for x in ins if x.bytes[:2] in (b"\x89\x85", b"\x89\x8D", b"\x89\x95", b"\x89\x9D", b"\x89\xB5", b"\x89\xBD") and x.bytes[2:6] == b"\x30\xAB\xFF\xFF"]
    assert sorted(slot_writes) == [TH_SET, 0x810E3]                  # veh_fc_id at entry, and the write-back after the site


def test_message_decision(core):
    # rescuer is the player: the game's own popup. Otherwise (the jailer): ours, unless our text could not be written.
    cases = [(1, 1, 1, 0), (4, 1, 1, 1), (4, 1, 0, 0), (1, 1, 0, 0), (7, 3, 1, 1)]
    assert core([f"view {r} {c} {t}" for r, c, t, _ in cases]) == [w for *_, w in cases]


def test_same_image_as_the_rescuer_and_the_right_text():
    body = _body("int __cdecl ShowFreed")
    assert "(label, image)" in body and "(kFreedFile, kFreedJailerLabel, 0, image, nullptr)" in body   # the image passes through
    assert "(3, reinterpret_cast<FGetNoun>(At(kVA_GetNoun))(rescuer), -1, -1)" in body                 # slot 3 = the rescuer
    script = re.search(r'kFreedScript\[\] =\s*(.*?)";\n', SRC, re.S).group(1) + '"'
    text = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', script)).replace("\\r\\n", "\n")
    assert "#WILLYFREE1\n#xs 440\n#wave 19\n#caption Operations Director\n" in text
    body_lines = text.split("#caption Operations Director\n")[1].split("\n\n")[0].split("\n")
    assert len(body_lines) == 3 and all(len(line) <= 96 for line in body_lines)         # the engine's fixed line buffer
    joined = " ".join(body_lines)
    for token in ("$FACTION3", "$TITLE0", "$NAME1", "$FACTION2", "$<2:has:have>"):
        assert token in joined
    assert "# ; This line must remain at end of file" in text                           # the script terminator the game's files carry
    # the sides are not swapped: anything but the jailer's view runs the game's own popup, straight away
    assert re.search(r"if \(!leaderfree::JailerSeesOwnMessage\(rescuer, current, g_freedTextReady\)\)\s*"
                     r"return reinterpret_cast<FNetMsgPop2>\(At\(kVA_NetMsgPop2\)\)\(label, image\);", body)
    # the file we write is the one the popup opens, and it holds the label the popup asks for
    name = re.search(r'kFreedFile\[\]\s*=\s*"([^"]+)"', SRC).group(1)
    label = re.search(r'kFreedJailerLabel\[\]\s*=\s*"([^"]+)"', SRC).group(1)
    assert f'"%s{name}.txt"' in SRC and f"#{label}\n" in text
    assert "return fclose(fp) == 0 && ok;" in SRC                                       # a full disk is noticed


# ---------------------------------------------------------------------------------------------- 7. the homeless probe
HOMELESS, VEH_KILL, HOME_FIELD = 0x5A3C74, 0x5C08C0, 0x952856
AFTER_HOMELESS = 0x5A3C82


def test_homeless_bytes_are_the_shipped_exes(bak_path, baked_exe):
    img = T.Image(bak_path)
    assert "kVA_HomelessBranch = 0x5A3C74" in SRC and _array("kExpectHomeless") == img.rd(HOMELESS, 14)
    assert T.Image(baked_exe).rd(HOMELESS, 14) == img.rd(HOMELESS, 14)
    assert HOMELESS + 6 + 5 + struct.unpack("<i", img.rd(HOMELESS + 7, 4))[0] == VEH_KILL      # the call really is veh_kill
    assert img.rd(HOMELESS + 1, 1) == bytes([AFTER_HOMELESS - (HOMELESS + 2)])                  # the jump lands on the next stage
    plain = bak_path.parent / "terranx.exe"
    if plain.exists():
        assert T.Image(plain).rd(HOMELESS, 14) == img.rd(HOMELESS, 14)


def test_the_homeless_fix_is_base_game_only_and_one_byte():
    install = _body("void InstallLeaderFreeFix()")
    assert install.index("if (ThinkerLoaded())") < install.index("InstallFreedMessageThinker();") < install.index("return;")
    assert "InstallHomelessProbeFix();" not in install[:install.index("return;")]    # never reached under Thinker
    assert SRC.count("InstallHomelessProbeFix();") == 1
    assert install.index("memcmp(loop") < install.index("InstallHomelessProbeFix();")   # behind the pick's own byte checks too
    # the last thing the base-game path does, so nothing can return before it once the pick is in
    assert re.search(r"InstallFreedMessageBaseGame\(\);\s*InstallHomelessProbeFix\(\);\s*InstallLandingSearch\(\);\s*$", install)
    body = _body("void InstallHomelessProbeFix()")
    assert "BYTE* branch = At(kVA_HomelessBranch);" in body                            # the written byte is the checked one
    assert "memcmp(branch, kExpectHomeless, sizeof kExpectHomeless) != 0" in body       # all 14 bytes, not a prefix
    assert "const BYTE jmp = 0xEB;" in body and "WriteCode(branch, &jmp, 1)" in body
    assert body.index("memcmp(") < body.index("WriteCode(")
    assert len(re.findall(r'UimodLog\("[^;]*?\);\s*return;', body, re.S)) == 2


def test_no_thinker_write_touches_the_homeless_branch(thinker, bak_path):
    img = T.Image(bak_path)
    hits = [(hex(w.addr), w.kind) for w in thinker["writes"]
            if w.addr < HOMELESS + 14 and HOMELESS < w.addr + max(1, T.footprint(w, img))]
    assert hits == []


def test_thinker_port_has_no_early_delete(thinker_src):
    """Why the fix stands down: Thinker's own free never deletes the probe before it is done with it."""
    probe = (thinker_src / "probe.cpp").read_text(encoding="utf-8")
    start = probe.rindex("case PRB_FREE_CAPTURED_FACTION_LEADER:")                     # the execution case, AI branch included
    end = probe.index("case PRB_INTRODUCE_GENETIC_PLAGUE:", start)
    assert "mod_setup_player(capture_id, tgt_fc_id, 1)" in probe[start:end]
    assert "veh_kill" not in probe[start:end] and "kill(veh_id)" not in probe[start:end]


def test_the_shipped_thinker_free_deletes_nothing_before_the_join(th_dll):
    """The DLL itself: the only probe-team deletions in probe() are the known six, and the free's whole straight run,
    from the landing call to the join with the common code, reaches none of them."""
    capstone = pytest.importorskip("capstone")
    _, img, base = th_dll
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    ins = list(md.disasm(img[0x7A070:0x81265], base + 0x7A070))
    by_addr = {x.address - base: n for n, x in enumerate(ins)}
    VEH_KILL_TH, KILL_TH, JOIN, AFTER_LANDING = 0x8AD80, 0x8E240, 0x7B9CA, 0x7C08A
    def calls_to(target):
        return sorted(x.address - base for x in ins if x.mnemonic == "call" and x.op_str == hex(base + target))
    assert calls_to(VEH_KILL_TH) == [0x7BA76, 0x7D94E, 0x7FFA4] and calls_to(KILL_TH) == [0x7A6DC, 0x7C929, 0x7FF15]
    assert AFTER_LANDING in by_addr and img[AFTER_LANDING - 5] == 0xE8                  # right after the mod_setup_player call
    seen, todo, deletions = set(), [AFTER_LANDING], []
    while todo:
        n = by_addr[todo.pop()]
        while True:
            x = ins[n]
            at = x.address - base
            if at == JOIN or at in seen:
                break
            seen.add(at)
            if x.mnemonic == "call" and x.op_str in (hex(base + VEH_KILL_TH), hex(base + KILL_TH)):
                deletions.append(at)
            if x.mnemonic == "ret":
                break
            if x.mnemonic.startswith("j"):
                assert x.op_str.startswith("0x"), (hex(at), x.op_str)            # no indirect jump on this path
                t = int(x.op_str, 16) - base
                if 0x7A070 <= t < 0x81265:
                    todo.append(t)
                if x.mnemonic == "jmp":
                    break
            n += 1
    assert 0x8122F in seen and deletions == []                                        # the walk really covers the free's message


@pytest.mark.parametrize("fixed,home,killed", [(False, -1, True), (False, 5, False), (True, -1, False), (True, 5, False)])
def test_homeless_branch_in_the_real_code(bak_path, fixed, home, killed):
    """Unicorn on the shipped bytes: the base game deletes a homeless probe here; the one-byte fix does not. Either way
    the home base is still recorded for the code after the free, and execution reaches the same next instruction."""
    pytest.importorskip("unicorn", reason="unicorn absent -- the branch emulation is unverified")
    import pefile
    from keystone import KS_ARCH_X86, KS_MODE_32, Ks
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn import x86_const as X

    pe = pefile.PE(str(bak_path), fast_load=True)
    base, ks, uc = pe.OPTIONAL_HEADER.ImageBase, Ks(KS_ARCH_X86, KS_MODE_32), Uc(UC_ARCH_X86, UC_MODE_32)
    for s in pe.sections:
        va = base + s.VirtualAddress
        uc.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
        uc.mem_write(va, s.get_data())
    STACK_A, MARK = 0x200000, 0x330000
    uc.mem_map(STACK_A, 0x10000)
    uc.mem_map(MARK, 0x1000)
    uc.mem_write(VEH_KILL, bytes(ks.asm(f"mov eax, [esp + 4]; mov [{MARK:#x}], eax; ret", VEH_KILL)[0]))
    if fixed:
        uc.mem_write(HOMELESS, b"\xEB")                                  # exactly what InstallHomelessProbeFix writes
    veh, ebp = 7, STACK_A + 0x8000
    uc.mem_write(HOME_FIELD + veh * 0x34, struct.pack("<h", home))
    uc.mem_write(ebp + 8, struct.pack("<i", veh))
    uc.mem_write(MARK, struct.pack("<i", -1))
    uc.reg_write(X.UC_X86_REG_EBP, ebp)
    uc.reg_write(X.UC_X86_REG_ESP, ebp - 0x100)
    uc.emu_start(0x5A3C5E, AFTER_HOMELESS, count=100)
    assert uc.reg_read(X.UC_X86_REG_EIP) == AFTER_HOMELESS and uc.reg_read(X.UC_X86_REG_ESP) == ebp - 0x100
    assert struct.unpack("<i", uc.mem_read(ebp - 0x54, 4))[0] == home
    assert struct.unpack("<i", uc.mem_read(MARK, 4))[0] == (veh if killed else -1)


@pytest.mark.parametrize("stub,reg_rescuer", [("StubFreedBaseGame", True), ("StubFreedThinker", False)])
def test_message_stubs_pass_the_arguments_and_keep_the_callers_registers(stub, reg_rescuer):
    pytest.importorskip("unicorn", reason="unicorn absent -- the stub emulation is unverified")
    from keystone import KS_ARCH_X86, KS_MODE_32, Ks
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn import x86_const as X

    m = re.search(rf"void {stub}\(\)\s*\{{\s*__asm \{{(.*?)\n    \}}\n\}}", SRC, re.S)
    assert m
    STUB_A, FAKE, DATA, STACK_A, RET = 0x310000, 0x320000, 0x330000, 0x200000, 0x340000
    asm = "\n".join(l.partition("//")[0].strip().replace("call ShowFreed", f"call {FAKE:#x}") for l in m.group(1).split("\n") if l.strip())
    assert "ShowFreed" not in asm
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for a in (STUB_A, FAKE, DATA, STACK_A, RET):
        uc.mem_map(a, 0x10000)
    uc.mem_write(STUB_A, bytes(ks.asm(asm, STUB_A)[0]))
    fake = (f"mov eax, [esp + 4]; mov [{DATA:#x}], eax; mov eax, [esp + 8]; mov [{DATA + 4:#x}], eax; "
            f"mov eax, [esp + 12]; mov [{DATA + 8:#x}], eax; mov eax, 0x1234; ret")
    uc.mem_write(FAKE, bytes(ks.asm(fake, FAKE)[0]))
    ebp, esp = STACK_A + 0xF000, STACK_A + 0x8000
    uc.mem_write(esp, struct.pack("<III", RET, 0xAAAA, 0xBBBB))        # return address, label, image
    uc.mem_write(ebp - 0x54D0, struct.pack("<I", 4))
    for r, v in [(X.UC_X86_REG_ESP, esp), (X.UC_X86_REG_EBP, ebp), (X.UC_X86_REG_EBX, 5 if reg_rescuer else 0x77),
                 (X.UC_X86_REG_ESI, 0x66), (X.UC_X86_REG_EDI, 0x55)]:
        uc.reg_write(r, v)
    uc.emu_start(STUB_A, RET, count=100)
    assert struct.unpack("<III", uc.mem_read(DATA, 12)) == (0xAAAA, 0xBBBB, 5 if reg_rescuer else 4)
    assert uc.reg_read(X.UC_X86_REG_EAX) == 0x1234 and uc.reg_read(X.UC_X86_REG_ESP) == esp + 4
    assert (uc.reg_read(X.UC_X86_REG_EBP), uc.reg_read(X.UC_X86_REG_ESI), uc.reg_read(X.UC_X86_REG_EDI)) == (ebp, 0x66, 0x55)
    assert uc.reg_read(X.UC_X86_REG_EBX) == (5 if reg_rescuer else 0x77)
