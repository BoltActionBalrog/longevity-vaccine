"""uimod leaderfree.cpp / leaderfree_core.h -- WHERE a freed leader's faction lands (base game, single player).

setup_player 0x5B0E00 looks for a landing tile with 1024 random draws (loop head 0x5B1688) and, when none passes its
site rules, takes a 1025th unjudged: sea, a foreign base's own tile, anything.  For a rescue (probe's own call) the
draws are replaced by one shuffled list of every tile, fed to the game's own rules: the hook supplies x, y and the draw
number and resumes at the loop body (0x5B1757); the rules, the counter and the exit stay the game's code.

Pinned here:
  1. the bytes the DLL checks are the shipped exe's (and our bake's), and each address is what the comment says;
  2. the hook's place in the real code: nothing branches into the replaced bytes, the body reads no register the head
     would have left, the head writes only x and y, and the counter has one writer;
  3. the draw band against the game's own head, run in Unicorn over every random value;
  4. the shuffle (two game random numbers per pick) and the pass order against a Python reference;
  5. the hook in the game's real loop (Unicorn, the stub assembled from the source text): a supplied tile is judged
     exactly as the game judges the same tile drawn at the same draw number, a declined call is the game's own draw,
     and whole searches end where the reference says -- by the rules, by the fallback, by the game's last draw;
  6. the rules only loosen (a tile accepted at some draw is accepted at the last one), which is what pass 2 rests on;
  7. it is a rescue only, base game only, and the last thing the install does.

The emulation runs a few thousand short loop bodies (~4 s serial); one module-scoped pair of machines serves them all.
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
from test_leaderfree import SRC, _array, _body, thinker, thinker_src  # noqa: E402,F401  (fixtures)

CORE = (ROOT.parent / "src" / "uimod" / "src" / "leaderfree_core.h").read_text(encoding="utf-8")

SETUP, SETUP_END = 0x5B0E00, 0x5B337C
HEAD, HEAD_REST, BODY, COUNT, EXIT, UNJUDGED = 0x5B1688, 0x5B1691, 0x5B1757, 0x5B1AE6, 0x5B1EF1, 0x5B1EE4
CALL, RETURN, RAND = 0x5A3C96, 0x5A3CA0, 0x64601D
KD, TILE = 0x400, 0x2C


# ------------------------------------------------------------------------------------------------ the reference
def draw_margin(i: int, size: int) -> int:
    p = (KD - i) * size
    m = p // 8192 if p >= 0 else -(-p // 8192)
    return min(max(m, 0), 9999)


def in_band(i, x, y, w, h, flat) -> bool:
    ym = draw_margin(i, h)
    ry = h - 2 * ym
    if not ym <= y <= ym + (ry - 1 if ry > 1 else 0):
        return False
    xm = draw_margin(i, w) if flat else 0
    rx = w - 2 * xm
    lo, hi, raw = xm, xm + (rx - 1 if rx > 1 else 0), x - (y & 1)
    return lo <= raw <= hi or lo <= raw + 1 <= hi


def crt_rand(seed: int):
    while True:
        seed = (seed * 214013 + 2531011) & 0xFFFFFFFF
        yield (seed >> 16) & 0x7FFF


def shuffled(w, h, rand, picks=None):
    t = [(x, y) for y in range(h) for x in range(y & 1, w, 2)]
    for i in range(len(t) - 1, 0, -1):
        high = next(rand)
        low = next(rand)
        k = ((high << 15) | low) % (i + 1)
        if picks is not None:
            picks.append(k)
        t[i], t[k] = t[k], t[i]
    return t


def fnv(tiles) -> int:
    h = 2166136261
    for x, y in tiles:
        for v in (x, y):
            h = ((h ^ (v & 0xFF)) * 16777619) & 0xFFFFFFFF
            h = ((h ^ ((v >> 8) & 0xFF)) * 16777619) & 0xFFFFFFFF
    return h


class World:
    """A map as the engine holds it: w x h, tiles[(x, y)] = bytearray(0x2C)."""

    def __init__(self, w, h, flat):
        self.w, self.h, self.half, self.flat = w, h, w // 2, flat
        self.tiles = {(x, y): bytearray(TILE) for y in range(h) for x in range(y & 1, w, 2)}

    def blob(self) -> bytes:
        return b"".join(bytes(self.tiles[(x, y)]) for y in range(self.h) for x in range(y & 1, self.w, 2))

    def fallback(self, x, y, aquatic) -> bool:
        t = self.tiles[(x, y)]
        alt = t[0] & 0xE0
        if not 2 <= y < self.h - 2 or (alt > 0x40 if aquatic else alt < 0x60) or t[8] & 1:
            return False
        return not t[8] & 2 or (t[2] & 0xF) >= 8

    def owner(self, x, y) -> int:
        return struct.unpack("<b", bytes(self.tiles[(x, y)][7:8]))[0]


def supplies(world: World, order, aquatic, jailer):
    """What the search hands the loop body, in order: ("give", x, y, draw) ... then one ("none", draw)."""
    n = len(order)
    for j, (x, y) in enumerate(order):
        i = j * KD // n
        if in_band(i, x, y, world.w, world.h, world.flat):
            yield "give", x, y, i
    for x, y in order:
        yield "give", x, y, KD - 1
    for own in (0, 1):
        for x, y in order:
            if world.fallback(x, y, aquatic) and (own or world.owner(x, y) != jailer):
                yield "give", x, y, KD
                return
    yield "none", -1, -1, KD


def ref_search(world, order, aquatic, jailer, accept):
    """(kind, x, y, draw, calls): 1 accepted by the rules, 2 handed over unjudged, 3 left to the game's own draw."""
    for calls, (what, x, y, i) in enumerate(supplies(world, order, aquatic, jailer), 1):
        if what == "none":
            return 3, -1, -1, i, calls
        if i == KD:
            return 2, x, y, i, calls
        if accept(x, y, i):
            return 1, x, y, i, calls
    raise AssertionError("the search always ends")


# ------------------------------------------------------------------------------------------------ 1. checked bytes
def test_checked_bytes_are_the_shipped_exes(bak_path, baked_exe):
    img = T.Image(bak_path)
    for name, va, size in [("kExpectLandHead", HEAD, 0xD8), ("kExpectLandCount", COUNT, 0x26),
                           ("kExpectLandCall", CALL, 10), ("kExpectLandEntry", SETUP, 12)]:
        want = _array(name)
        assert len(want) == size and want == img.rd(va, size), name
        assert T.Image(baked_exe).rd(va, size) == want, name
        plain = bak_path.parent / "terranx.exe"
        if plain.exists():
            assert T.Image(plain).rd(va, size) == want, name
    for text in ("kVA_LandHead     = 0x5B1688", "kVA_LandHeadRest = 0x5B1691", "kVA_LandBody     = 0x5B1757",
                 "kVA_LandCount    = 0x5B1AE6", "kVA_LandCall     = 0x5A3C96", "kVA_LandReturn   = 0x5A3CA0",
                 "kVA_LandEntry    = 0x5B0E00", "kVA_GameRand     = 0x64601D", "kLandJumpLen = 9"):
        assert SRC.count(text) == 1, text
    assert HEAD + 0xD8 == BODY + 9                       # the checked head runs through the body's first two instructions
    # the checked call is probe's setup_player call, and a rescue is recognised by where it returns
    assert CALL + 10 == RETURN and CALL + 10 + struct.unpack("<i", img.rd(CALL + 6, 4))[0] == SETUP
    # both draws call the game's rand
    for at in (0x5B16DC, 0x5B1735):
        assert img.rd(at, 1) == b"\xE8" and at + 5 + struct.unpack("<i", img.rd(at + 1, 4))[0] == RAND


def test_probe_is_the_only_caller_that_returns_there(bak_path):
    """Every call of setup_player in the exe: five, and only probe's returns at kVA_LandReturn."""
    img = T.Image(bak_path)
    code = img.rd(0x401000, 0x669000 - 0x401000)
    sites = [0x401000 + i for i in range(len(code) - 5)
             if code[i] == 0xE8 and 0x401000 + i + 5 + struct.unpack_from("<i", code, i + 1)[0] == SETUP]
    assert sites == [0x525CC7, 0x5A3C9B, 0x5B341C, 0x5B3C03, 0x5B3C4C]
    assert [s + 5 for s in sites].count(RETURN) == 1


# ------------------------------------------------------------------------------------------------ 2. the hook's place
@pytest.fixture(scope="module")
def listing(bak_path):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return capstone, {x.address: x for x in md.disasm(T.Image(bak_path).rd(SETUP, SETUP_END - SETUP), SETUP)}


def test_nothing_branches_into_the_replaced_bytes(listing):
    _, ins = listing
    assert HEAD in ins and HEAD_REST in ins and BODY in ins and ins[HEAD].size + ins[HEAD + 3].size == 9
    targets = {int(x.op_str, 16) for x in ins.values() if x.mnemonic.startswith("j") and x.op_str.startswith("0x")}
    assert all(x.op_str.startswith("0x") for x in ins.values() if x.mnemonic.startswith("j"))     # no indirect jump
    assert not [hex(t) for t in targets if HEAD < t < HEAD_REST]
    assert HEAD in targets                               # the loop's back edges land on the jump itself
    # the body is entered from the head only: one branch (the parity fix's own) and the fall-through
    assert [hex(a) for a, x in ins.items() if x.mnemonic.startswith("j") and x.op_str == hex(BODY)] == ["0x5b1751"]


def test_the_body_reads_no_register_the_head_would_have_left(listing):
    """Walk every path from the body's first instruction to the next draw or the exit: no general register (or the
    flags) is read before it is written.  So the body does not care what the skipped head would have left."""
    capstone, ins = listing
    X = capstone.x86_const
    name = {}
    for full, parts in {"eax": "EAX AX AL AH", "ecx": "ECX CX CL CH", "edx": "EDX DX DL DH", "ebx": "EBX BX BL BH",
                        "esi": "ESI SI", "edi": "EDI DI", "fl": "EFLAGS"}.items():
        for p in parts.split():
            name[getattr(X, f"X86_REG_{p}")] = full
    whole = {getattr(X, f"X86_REG_{p}") for p in "EAX ECX EDX EBX ESI EDI EFLAGS".split()}
    seen, todo, bad = {}, [(BODY, frozenset())], []
    while todo:
        at, known = todo.pop()
        while at not in (HEAD, EXIT):
            if at in seen and seen[at] <= known:
                break
            known = known & seen[at] if at in seen else known
            seen[at] = known
            x = ins[at]
            reads, writes = x.regs_access()
            if x.mnemonic == "xor" and x.op_str.split(", ")[0] == x.op_str.split(", ")[1]:
                reads = []
            bad += [(hex(at), x.mnemonic, x.op_str) for r in reads if r in name and name[r] not in known]
            known = set(known)
            if x.mnemonic == "call":
                known |= {"eax", "ecx", "edx", "fl"}             # cdecl: the callee's to clobber, arguments on the stack
            known |= {name[r] for r in writes if r in whole}
            known = frozenset(known)
            assert x.mnemonic != "ret", hex(at)
            if x.mnemonic.startswith("j"):
                todo.append((int(x.op_str, 16), known))
                if x.mnemonic == "jmp":
                    break
            at += x.size
    assert bad == []
    assert COUNT in seen and UNJUDGED in seen and len(seen) > 500                    # the walk covers the whole body


def test_the_head_writes_only_x_and_y_and_the_counter_has_one_writer(listing):
    capstone, ins = listing
    X = capstone.x86_const

    def stores(lo, hi):
        out = []
        for a in sorted(ins):
            x = ins[a]
            if lo <= a < hi and x.operands and x.operands[0].type == X.X86_OP_MEM and x.operands[0].access & capstone.CS_AC_WRITE:
                out.append((hex(a), x.op_str.split(",")[0]))
        return out

    assert stores(HEAD, BODY) == [("0x5b1707", "dword ptr [ebp - 4]"), ("0x5b1745", "dword ptr [ebp - 8]"),
                                  ("0x5b174b", "dword ptr [ebp - 4]"), ("0x5b1754", "dword ptr [ebp - 4]")]
    assert [a for a, d in stores(BODY, EXIT) if d == "dword ptr [ebp - 0x14]"] == ["0x5b1aef"]
    # ... and it is `counter + 1`, compared with the draw count: what makes 0 mean "first draw" at the head
    assert [(ins[a].mnemonic, ins[a].op_str) for a in (0x5B1AE6, 0x5B1AE9, 0x5B1AEA, 0x5B1AEF, 0x5B1AF2)] == [
        ("mov", "eax, dword ptr [ebp - 0x14]"), ("inc", "eax"), ("cmp", "eax, 0x400"),
        ("mov", "dword ptr [ebp - 0x14], eax"), ("jle", "0x5b1b0c")]
    assert f"constexpr int kDraws = {KD:#x};" in CORE
    # every way back to the head comes after that step, so the head sees 0 on a call's first draw only
    back = sorted(a for a, x in ins.items() if x.mnemonic.startswith("j") and x.op_str == hex(HEAD))
    assert len(back) == 19 and back[0] > 0x5B1AEF and back[-1] < EXIT
    early = [(hex(a), x.op_str) for a, x in ins.items()
             if BODY <= a < 0x5B1AE6 and x.mnemonic.startswith("j") and int(x.op_str, 16) > 0x5B1AE6]
    assert early == []                                              # nothing in the body skips the step
    assert ins[0x5B1685].mnemonic == "mov" and ins[0x5B1685].op_str == "dword ptr [ebp - 0x14], edx"   # the loop's entry


# ------------------------------------------------------------------------------------------------ the native build
@pytest.fixture(scope="module")
def native():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    exe = cpp_harness.build(ROOT / "tests" / "leaderfree_selftest.cpp", "leaderfree_selftest_")

    def run(lines):
        out = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True,
                             timeout=120).stdout.splitlines()
        assert len(out) == len(lines) and "bad" not in out, out[:5]
        return [tuple(int(v) for v in line.split()) for line in out]
    return run


# ------------------------------------------------------------------------------------------------ the machines
STACK, STUB, FAKE, SCR, MAPMEM = 0x00200000, 0x00310000, 0x00320000, 0x00330000, 0x10000000
EBP = STACK + 0x8000
G = dict(w=0x949870, h=0x949874, half=0x68FAF0, flat=0x94988C, tiles=0x94A30C, root=0x949888, turn=0x9A64D4,
         vehs=0x9A64C8, bases=0x9A64CC, status=0x9A64E8, difficulty=0x9A64C4, rules=0x9A649C, ocean=0x94A2A4,
         dist=0x90EA04)
CONTINENTS, PRESENCE, BASES, MFACTION_FLAGS = 0x9AA730, 0x96FC28, 0x97D040, 0x946F58
REGS = ("eax", "ecx", "edx", "ebx", "esi", "edi")


def _stub_asm() -> str:
    m = re.search(r"void StubLand\(\)\s*\{\s*__asm \{(.*?)\n    \}\n\}", SRC, re.S)
    assert m
    lines = []
    for raw in m.group(1).split("\n"):
        code = raw.partition("//")[0].strip()
        if not code:
            continue
        code = code.replace("call LandNext", f"call {FAKE:#x}")
        code = code.replace("jmp  dword ptr [g_landHeadRest]", f"jmp {HEAD_REST:#x}")
        code = code.replace("jmp  dword ptr [g_landBody]", f"jmp {BODY:#x}")
        code = code.replace("dword ptr ds:[0x949870]", "dword ptr [0x949870]")
        assert "g_land" not in code and "LandNext" not in code, code
        lines.append(code)
    return "\n".join(lines)


def test_the_stub_reloads_what_the_replaced_instructions_loaded(bak_path):
    """The declined path re-runs the two instructions the jump replaced, with the game's own operands."""
    from keystone import KS_ARCH_X86, KS_MODE_32, Ks
    asm = _stub_asm()
    replaced = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm("mov edx, dword ptr [ebp - 0x14]; mov esi, dword ptr [0x949870]", 0)[0])
    assert replaced == T.Image(bak_path).rd(HEAD, 9)
    assert "mov  edx, dword ptr [ebp - 0x14]\nmov  esi, dword ptr [0x949870]\njmp 0x5b1691" in asm
    assert asm.index("pushad") < asm.index("call") < asm.index("popad") < asm.index("jnz")      # popad keeps the flags


class Machines:
    """The shipped exe twice: `vanilla` untouched, `hooked` with the 9-byte jump and the stub the DLL installs (the
    stub's call goes to a fake LandNext that a Python handler answers).  rand is scripted on both."""

    def __init__(self, bak_path):
        import pefile
        from keystone import KS_ARCH_X86, KS_MODE_32, Ks
        from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
        from unicorn import x86_const as X

        self.X = X
        self.reg = {n: getattr(X, f"UC_X86_REG_{n.upper()}") for n in REGS + ("ebp", "esp")}
        pe = pefile.PE(str(bak_path), fast_load=True)
        base = pe.OPTIONAL_HEADER.ImageBase
        ks = Ks(KS_ARCH_X86, KS_MODE_32)
        rand = (f"mov eax, [{SCR + 0x10:#x}]; push ecx; mov ecx, [{SCR + 0x14:#x}]; mov [{SCR + 0x10:#x}], ecx; pop ecx; "
                f"inc dword ptr [{SCR + 0x18:#x}]; ret")
        self.handler = None
        self.state = {}
        self.uc = {}
        for kind in ("vanilla", "hooked"):
            uc = Uc(UC_ARCH_X86, UC_MODE_32)
            for s in pe.sections:
                va = base + s.VirtualAddress
                uc.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
                uc.mem_write(va, s.get_data())
            for b in (STACK, STUB, FAKE, SCR):
                uc.mem_map(b, 0x10000)
            uc.mem_map(MAPMEM, 0x100000)
            uc.mem_write(RAND, bytes(ks.asm(rand, RAND)[0]))            # all code before any run (stale-translation rule)
            if kind == "hooked":
                uc.mem_write(STUB, bytes(ks.asm(_stub_asm(), STUB)[0]))
                uc.mem_write(FAKE, bytes(ks.asm(f"mov eax, [{SCR:#x}]; ret", FAKE)[0]))
                jump = bytes(ks.asm(f"jmp {STUB:#x}", HEAD)[0]) + b"\x90" * 4
                assert len(jump) == 9
                uc.mem_write(HEAD, jump)
                uc.hook_add(UC_HOOK_CODE, self._fake, begin=FAKE, end=FAKE)
            for at in (HEAD, BODY, EXIT):
                uc.hook_add(UC_HOOK_CODE, self._stop, user_data=at, begin=at, end=at)
            self.uc[kind] = uc

    def _fake(self, uc, address, size, user):
        frame = struct.unpack("<I", uc.mem_read(uc.reg_read(self.X.UC_X86_REG_ESP) + 4, 4))[0]
        uc.mem_write(SCR, struct.pack("<i", self.handler(uc, frame)))

    def _stop(self, uc, address, size, at):
        st = self.state
        if at == HEAD:
            st["heads"] += 1
            if st["heads"] > st["max_heads"]:
                uc.emu_stop()
        elif at == BODY:
            st["bodies"] += 1
            if st["stop_at_body"]:
                uc.emu_stop()
        else:
            uc.emu_stop()

    def load(self, world: World, *, faction=5, jailer=3, aquatic=False, turn=120, bases=(), continents=None,
             presence=(), root=None, ocean=1):
        self.world, self.faction, self.jailer = world, faction, jailer
        blob = world.blob()
        self.map_len = len(blob)
        for uc in self.uc.values():
            uc.mem_write(MAPMEM, blob)
            vals = dict(w=world.w, h=world.h, half=world.half, flat=int(world.flat), tiles=MAPMEM, turn=turn, vehs=0,
                        bases=len(bases), status=0, difficulty=3, rules=0, ocean=ocean,
                        root=int((world.half * world.h) ** 0.5) if root is None else root)
            for k, v in vals.items():
                uc.mem_write(G[k], struct.pack("<i", v))
            uc.mem_write(MFACTION_FLAGS + faction * 0x59C, struct.pack("<I", 0x100 if aquatic else 0))
            for r in range(128):
                count, open_ = (continents or {}).get(r, (0, 0))
                uc.mem_write(CONTINENTS + r * 0x1C, struct.pack("<ii", count, open_))
                for f in range(1, 8):
                    uc.mem_write(PRESENCE + r + (f - 1) * 0x20CC, bytes([1 if (f, r) in presence else 0]))
            for n, (x, y, owner) in enumerate(bases):
                uc.mem_write(BASES + n * 0x134, struct.pack("<hhB", x, y, owner))

    def run(self, kind, *, counter, rands=(), regs=None, max_heads=1, stop_at_body=False, limit=4_000_000):
        """From the loop head with the counter set, to the next draw, the body (stop_at_body) or the exit."""
        uc, X = self.uc[kind], self.X
        f = self.faction
        uc.mem_write(EBP - 0x100, b"\0" * 0x100)
        uc.mem_write(EBP, struct.pack("<IIiii", 0, RETURN, f, self.jailer, 1))
        for off, v in ((0x14, counter), (0xC, f * 0x59C), (0x3C, 1 << f), (0x28, f * 0x20CC), (0x38, 0)):
            uc.mem_write(EBP - off, struct.pack("<i", v))
        uc.mem_write(G["dist"], struct.pack("<i", 0x7777))
        r = list(rands) + [0x5A5A, 0x5A5A]
        uc.mem_write(SCR + 0x10, struct.pack("<iii", r[0], r[1], 0))
        for n, v in zip(REGS, regs or (0xA1, 0xC1, 0xD1, 0xB1, 0x51, 0xD1)):
            uc.reg_write(self.reg[n], v)
        uc.reg_write(self.reg["ebp"], EBP)
        uc.reg_write(self.reg["esp"], EBP - 0x200)
        self.state = dict(heads=0, bodies=0, max_heads=max_heads, stop_at_body=stop_at_body)
        uc.emu_start(HEAD, 0, count=limit)
        eip = uc.reg_read(X.UC_X86_REG_EIP)
        assert eip in (HEAD, BODY, EXIT), hex(eip)
        assert uc.reg_read(self.reg["esp"]) == EBP - 0x200 and uc.reg_read(self.reg["ebp"]) == EBP
        local = lambda off: struct.unpack("<i", uc.mem_read(EBP - off, 4))[0]
        return dict(at=eip, x=local(4), y=local(8), counter=local(0x14), unjudged=local(0x38),
                    dist=struct.unpack("<i", uc.mem_read(G["dist"], 4))[0],
                    rands=struct.unpack("<i", uc.mem_read(SCR + 0x18, 4))[0],
                    regs=tuple(uc.reg_read(self.reg[n]) for n in REGS),
                    map=bytes(uc.mem_read(MAPMEM, self.map_len)), bodies=self.state["bodies"])

    def draw_rands(self, x, y, i):
        """The random values that make the game's own head draw tile (x, y) at draw i (the tile must be in the band)."""
        w = self.world
        xm = draw_margin(i, w.w) if w.flat else 0
        ym = draw_margin(i, w.h)
        out = []
        if w.w - 2 * xm > 1:
            out.append(x - (y & 1) - xm)
        if w.h - 2 * ym > 1:
            out.append(y - ym)
        return out

    def judge(self, x, y, i, regs=None):
        """The game's own verdict on tile (x, y) drawn at draw i, on the untouched exe."""
        return self.run("vanilla", counter=i, rands=self.draw_rands(x, y, i), regs=regs)


@pytest.fixture(scope="module")
def machines(bak_path):
    pytest.importorskip("unicorn", reason="unicorn absent -- the landing search is unverified in the real loop")
    return Machines(bak_path)


def random_world(rnd: random.Random, w, h, flat, *, sea=0.3, owned=0.15, jailer=3):
    """Land and sea, regions, rockiness, fungus, landmarks, territory, the odd unit; every tile has a site value so
    the rules never call world_site."""
    world = World(w, h, flat)
    for (x, y), t in world.tiles.items():
        land = rnd.random() > sea
        t[0] = (rnd.choice([3, 3, 3, 4, 5]) if land else rnd.choice([0, 1, 2, 2])) << 5 | rnd.choice([0, 8, 16])
        t[2] = rnd.randrange(1, 16) << 4 | 0xF
        t[3] = (1 + (x * 3 // w)) if land else 65
        t[5] = rnd.choice([0, 0, 0, 0x40, 0x80])
        t[7] = rnd.choice([jailer, 1, 2]) if rnd.random() < owned else 0
        flags = (0x20 if rnd.random() < 0.1 else 0)
        if rnd.random() < 0.04:
            flags |= 2
            t[2] = t[2] & 0xF0 | rnd.randrange(8)
        t[8:12] = struct.pack("<I", flags)
        if rnd.random() < 0.02:
            t[12:16] = struct.pack("<I", 0x01000000 | 1 << rnd.randrange(8))
    return world


def place_bases(rnd, world, owners):
    bases = []
    spots = [p for p, t in world.tiles.items() if (t[0] & 0xE0) >= 0x60 and not t[8] & 3]
    for owner in owners:
        x, y = spots.pop(rnd.randrange(len(spots)))
        t = world.tiles[(x, y)]
        t[8] |= 1
        t[2] = t[2] & 0xF0 | owner
        t[7] = owner
        bases.append((x, y, owner))
    return bases


def scenario(seed, w, h, flat, *, aquatic=False, turn=120, n_bases=2, **kw):
    rnd = random.Random(seed)
    world = random_world(rnd, w, h, flat, **kw)
    bases = place_bases(rnd, world, [3, 2][:n_bases])
    continents = {r: (rnd.choice([40, 100, 200, 400]), rnd.choice([10, 60, 200])) for r in (1, 2, 3, 65)}
    presence = {(f, r) for f in (2, 3) for r in (1, 2, 3) if rnd.random() < 0.5}
    return world, dict(aquatic=aquatic, turn=turn, bases=bases, continents=continents, presence=presence,
                       root=rnd.choice([20, 40, 56]))


# ------------------------------------------------------------------------------------------------ 3. the draw band
@pytest.mark.parametrize("w,h,flat", [(16, 16, True), (16, 16, False), (12, 24, True), (24, 10, False)])
def test_draw_band_is_the_games_own(machines, native, w, h, flat):
    """Run the game's head for every pair of random values at draw i and collect the tiles it can produce: that set is
    InDrawBand, tile for tile (native build and the reference)."""
    world = World(w, h, flat)
    machines.load(world)
    lines, want = [], []
    for i in (0, 1, 340, 511, 512, 513, 700, 1023):
        xm = draw_margin(i, w) if flat else 0
        ym = draw_margin(i, h)
        reach = set()
        for r1 in range(max(w - 2 * xm, 1)):
            for r2 in range(max(h - 2 * ym, 1)):
                rands = ([r1] if w - 2 * xm > 1 else []) + ([r2] if h - 2 * ym > 1 else [])
                out = machines.run("vanilla", counter=i, rands=rands, stop_at_body=True)
                assert out["at"] == BODY and out["rands"] == len(rands)
                reach.add((out["x"], out["y"]))
        assert reach <= set(world.tiles)                                 # the head only ever lands on real tiles
        for (x, y) in world.tiles:
            lines.append(f"band {i} {x} {y} {w} {h} {int(flat)}")
            want.append((int((x, y) in reach),))
            assert in_band(i, x, y, w, h, flat) == ((x, y) in reach), (i, x, y)
        if i == 1023:
            assert reach == set(world.tiles)                             # the last draw can be any tile: pass 2 is whole
    assert native(lines) == want


def test_the_last_draws_band_is_the_whole_map_on_every_usable_size(native):
    assert "constexpr int kMaxLandSide = 4096;" in CORE and "m.w <= kMaxLandSide && m.h <= kMaxLandSide" in CORE
    assert draw_margin(KD - 1, 4096) == 0 and draw_margin(KD - 1, 8192) == 1
    rnd = random.Random(7)
    lines = []
    for _ in range(400):
        w, h = rnd.choice([16, 80, 128, 512, 4096]), rnd.choice([16, 80, 128, 256, 4096])
        y = rnd.randrange(h)
        x = rnd.choice([y & 1, w - 2 + (y & 1), rnd.randrange(w // 2) * 2 + (y & 1)])
        lines.append(f"band {KD - 1} {x} {y} {w} {h} {rnd.randrange(2)}")
    assert native(lines) == [(1,)] * len(lines)


# ------------------------------------------------------------------------------------------------ 4. shuffle, passes
def test_virtual_draw_stays_in_the_games_range(native):
    """Place j of n is judged at draw index j * 1024 / n: 0 first, never past 1023, never decreasing -- so the body's
    counter (index + 1) is 1..1024 on any map size, the range the game's own draws cover."""
    lines, want = [], []
    for n in (1, 2, 96, 576, 1023, 1024, 1025, 3200, 8192, 32768, 131072):
        js = sorted({0, 1, n // 3, n // 2, n - 2, n - 1} & set(range(n)))
        for j in js:
            lines.append(f"vdraw {j} {n}")
            want.append((j * KD // n,))
        assert 0 == 0 * KD // n and (n - 1) * KD // n <= KD - 1
    assert native(lines) == want
    assert "return static_cast<int>(static_cast<int64_t>(j) * kDraws / n);" in CORE


@pytest.mark.parametrize("w,h,seed", [(2, 2, 1), (16, 12, 5), (80, 80, 0xBEEF), (128, 128, 99), (512, 256, 2026)])
def test_shuffle_is_the_reference_and_uses_two_numbers_a_pick(native, w, h, seed):
    picks = []
    order = shuffled(w, h, crt_rand(seed), picks)
    assert sorted(order) == sorted((x, y) for y in range(h) for x in range(y & 1, w, 2))        # a permutation
    assert native([f"shuffle {w} {h} {seed}"]) == [(len(order), fnv(order), 2 * (len(order) - 1))]
    if len(order) > 0x8000:
        assert max(picks) > 0x7FFF                    # a single 15-bit number could never name these places


def _oracle_world(rnd: random.Random):
    w, h = rnd.choice([8, 12, 20, 40]), rnd.choice([6, 10, 16, 30])
    world = random_world(rnd, w, h, rnd.random() < 0.5, sea=rnd.choice([0.0, 0.3, 1.0]), owned=rnd.choice([0.0, 0.3, 1.0]))
    mode = rnd.choice(["never", "late", "mixed", "mixed", "early"])
    for t in world.tiles.values():
        first = {"never": 0xFFFF, "late": rnd.choice([0xFFFF, 0xFFFF, 1023]), "early": rnd.choice([0, 5, 0xFFFF]),
                 "mixed": rnd.choice([0xFFFF, 0xFFFF, 0xFFFF, rnd.randrange(1024)])}[mode]
        t[0x28:0x2A] = struct.pack("<H", first)
        if rnd.random() < 0.1:
            t[8] |= 1                                                    # a base
    if rnd.random() < 0.15:
        for t in world.tiles.values():
            t[8] |= 1                                                    # nowhere to fall back to
    return world


def test_search_passes_match_the_reference(native, tmp_path):
    """LandSearch (what the DLL runs) against the reference on random maps whose "game" accepts each tile from a
    stated draw on: the same tile, the same draw, after the same number of calls and random numbers."""
    rnd = random.Random(0x1A2D)
    lines, want, kinds = [], [], set()
    for n in range(300):
        world = _oracle_world(rnd)
        aquatic, jailer, seed = rnd.randrange(2), rnd.choice([1, 2, 3]), rnd.getrandbits(31)
        path = tmp_path / f"m{n}.bin"
        path.write_bytes(struct.pack("<iiii", world.w, world.h, world.half, int(world.flat)) + world.blob())
        order = shuffled(world.w, world.h, crt_rand(seed))

        def accept(x, y, i, world=world):
            return i >= struct.unpack("<H", bytes(world.tiles[(x, y)][0x28:0x2A]))[0]
        kind, x, y, draw, calls = ref_search(world, order, bool(aquatic), jailer, accept)
        kinds.add((kind, draw == KD - 1))
        lines.append(f"search {path} {aquatic} {jailer} {seed}")
        want.append((kind, x, y, draw, calls, 2 * (len(order) - 1)))
        lines.append(f"loop {path} {aquatic} {jailer} {seed} 0")           # the same search through LandDriver::Step
        want.append((kind, x, y, draw, calls, 2 * (len(order) - 1)))
    assert kinds >= {(1, False), (1, True), (2, False), (3, False)}        # every way a search can end
    assert native(lines) == want


def test_fallback_order_hand_cases(native, tmp_path):
    """Pass 3 by hand: the faction's kind, no base, no unit, off the pole rows, outside the jailer's territory first."""
    def run(world, aquatic=0, jailer=3):
        path = tmp_path / "hand.bin"
        path.write_bytes(struct.pack("<iiii", world.w, world.h, world.half, 0) + world.blob())
        return native([f"search {path} {aquatic} {jailer} 11"])[0][:4], shuffled(world.w, world.h, crt_rand(11))

    def blank(alt=3):
        world = World(8, 8, False)
        for t in world.tiles.values():
            t[0] = alt << 5
            t[2] = 0xF
            t[0x28:0x2A] = b"\xFF\xFF"
        return world

    world = blank()
    got, order = run(world)
    first = next(p for p in order if 2 <= p[1] < 6)
    assert got == (2, *first, KD)                                       # any land tile off the pole rows
    for t in world.tiles.values():
        t[7] = 3
    assert run(world)[0] == (2, *first, KD)                             # all the jailer's: still lands, second sweep
    inside = [p for p in order if 2 <= p[1] < 6]
    world.tiles[inside[5]][7] = 2
    assert run(world)[0] == (2, *inside[5], KD)                         # one tile outside it wins over earlier ones
    world.tiles[inside[5]][8] |= 2
    world.tiles[inside[5]][2] = 0xF0 | 1
    assert run(world)[0] == (2, *first, KD)                             # ... unless a unit stands on it
    world.tiles[inside[5]][2] = 0xFF
    assert run(world)[0] == (2, *inside[5], KD)                         # a stale unit flag with no owner is no unit
    world.tiles[inside[5]][7] = 0xFF
    assert run(world)[0] == (2, *inside[5], KD)                         # owner -1 is not the jailer either
    for t in world.tiles.values():
        t[7] = 0xFF
    assert run(world, jailer=7)[0] == (2, *first, KD) and run(world, jailer=0)[0] == (2, *first, KD)
    world = blank()
    for (x, y), t in world.tiles.items():
        if y not in (1, 6):
            t[8] |= 1
    assert run(world)[0] == (3, -1, -1, KD)                             # rows 1 and h-2 are pole rows
    for (x, y), t in world.tiles.items():
        if y == 5:
            t[8] &= ~1
    assert run(world)[0][2] == 5                                        # ... and h-3 is not
    assert run(blank(alt=2))[0] == (3, -1, -1, KD)                      # all sea: nothing for a land faction
    assert run(blank(alt=2), aquatic=1)[0] == (2, *first, KD)           # ... and any of it for an aquatic one
    assert run(blank(alt=3), aquatic=1)[0] == (3, -1, -1, KD)
    world = blank()
    for (x, y), t in world.tiles.items():
        if 2 <= y < 6:
            t[8] |= 1
    assert run(world)[0] == (3, -1, -1, KD)                             # only pole rows free: the game's own draw


# ------------------------------------------------------------------------------------------------ 5. the real loop
SCENARIOS = [(1, 16, 12, False, {}), (2, 16, 12, True, {}), (3, 24, 16, False, dict(aquatic=True, sea=0.85)),
             (4, 12, 10, True, dict(turn=300, n_bases=1)), (5, 20, 14, False, dict(owned=0.0, n_bases=0))]


@pytest.mark.parametrize("seed,w,h,flat,kw", SCENARIOS)
def test_a_supplied_tile_is_judged_as_the_same_tile_drawn(machines, seed, w, h, flat, kw):
    """The heart of it: for a tile and a draw number, the hooked exe (stub supplies x, y, counter; registers full of
    other junk) and the untouched exe (the head draws that tile at that counter) leave the loop body in the SAME state:
    accepted or rejected, the frame, the registers, the map."""
    world, setup = scenario(seed, w, h, flat, **kw)
    machines.load(world, **setup)
    rnd = random.Random(seed * 977)
    verdicts = set()
    for _ in range(70):
        i = rnd.choice([0, 1, 63, 64, 255, 256, 400, 800, 959, 960, 1022, 1023, rnd.randrange(1024)])
        x, y = rnd.choice([p for p in world.tiles if in_band(i, *p, w, h, flat)])
        want = machines.judge(x, y, i)
        assert (want["x"], want["y"], want["counter"]) == (x, y, i + 1)

        def give(uc, frame, x=x, y=y, i=i):
            uc.mem_write(frame - 0x14, struct.pack("<i", i))
            uc.mem_write(frame - 4, struct.pack("<i", x))
            uc.mem_write(frame - 8, struct.pack("<i", y))
            return 1
        machines.handler = give
        got = machines.run("hooked", counter=0, regs=(0x1111, 0x2222, 0x3333, 0x4444, 0x5555, 0x6666))
        assert got["rands"] == 0
        for key in ("at", "x", "y", "counter", "unjudged", "dist", "regs", "map"):
            assert got[key] == want[key], (key, x, y, i)
        verdicts.add(want["at"])
    assert verdicts == {HEAD, EXIT}                                     # both verdicts were really exercised


@pytest.mark.parametrize("seed,w,h,flat,kw", SCENARIOS[:3])
def test_a_declined_call_is_the_games_own_draw(machines, seed, w, h, flat, kw):
    """LandNext returning 0 (not a rescue): the stub runs the two replaced instructions and the game draws for itself.
    Same random numbers in, same state out as the untouched exe -- including at the unjudged last draw."""
    world, setup = scenario(seed, w, h, flat, **kw)
    machines.load(world, **setup)
    machines.handler = lambda uc, frame: 0
    rnd = random.Random(seed)
    for _ in range(40):
        counter = rnd.choice([0, 5, 500, 1023, 1024])
        rands = [rnd.randrange(0x8000), rnd.randrange(0x8000)]
        regs = tuple(rnd.getrandbits(32) for _ in REGS)
        want = machines.run("vanilla", counter=counter, rands=rands, regs=regs)
        got = machines.run("hooked", counter=counter, rands=rands, regs=regs)
        assert got == want
        if counter == 1024:
            assert want["at"] == EXIT and want["unjudged"] == 1


def _whole_search(machines, world, setup, seed, *, last_rands=(3, 4)):
    """Run the hooked loop from its first draw to its exit, the stub's calls answered by the reference search."""
    order = shuffled(world.w, world.h, crt_rand(seed))
    gen = supplies(world, order, setup["aquatic"], machines.jailer)
    given = []

    def land_next(uc, frame):
        what, x, y, draw = next(gen)
        given.append((what, x, y, draw))
        uc.mem_write(frame - 0x14, struct.pack("<i", draw))
        if what == "none":
            return 0
        uc.mem_write(frame - 4, struct.pack("<i", x))
        uc.mem_write(frame - 8, struct.pack("<i", y))
        return 1
    machines.handler = land_next
    got = machines.run("hooked", counter=0, rands=last_rands, max_heads=10 ** 9, limit=400_000_000)
    assert got["at"] == EXIT
    return order, given, got


@pytest.mark.parametrize("seed,w,h,flat,kw", SCENARIOS)
def test_whole_searches_end_where_the_reference_says(machines, seed, w, h, flat, kw):
    """A complete search through the game's real loop: it lands on the tile the reference names when each supplied
    tile's verdict is the untouched game's own (judged one at a time on the other machine)."""
    world, setup = scenario(seed, w, h, flat, **kw)
    machines.load(world, **setup)
    order, given, got = _whole_search(machines, world, setup, seed)
    kind, x, y, draw, calls = ref_search(world, order, setup["aquatic"], machines.jailer,
                                         lambda x, y, i: machines.judge(x, y, i)["at"] == EXIT)
    assert kind == 1 and (got["x"], got["y"]) == (x, y) and len(given) == calls == got["bodies"]
    assert got["unjudged"] == (1 if kind == 2 else 0) and got["rands"] == 0
    assert got["counter"] == draw + 1


def test_a_full_map_falls_back_to_an_empty_tile_outside_the_jailers_borders(machines):
    """Every tile is someone's territory, so the rules pass nothing (the base game would take a random unjudged tile):
    both passes run in full, then the first empty land tile off the poles that is not the jailer's."""
    world, setup = scenario(11, 16, 12, False, owned=1.0)
    machines.load(world, **setup)
    order, given, got = _whole_search(machines, world, setup, 42)
    n = len(order)
    in1 = sum(in_band(j * KD // n, *order[j], world.w, world.h, world.flat) for j in range(n))
    assert len(given) == in1 + n + 1 == got["bodies"] and given[-1][3] == KD
    assert [g[3] for g in given[in1:in1 + n]] == [KD - 1] * n and [g[1:3] for g in given[in1:in1 + n]] == order
    want = next(p for p in order if world.fallback(*p, False) and world.owner(*p) != machines.jailer)
    assert (got["x"], got["y"]) == want and got["unjudged"] == 1 and got["counter"] == KD + 1 and got["rands"] == 0
    t = world.tiles[want]
    assert (t[0] & 0xE0) >= 0x60 and not t[8] & 1 and 2 <= want[1] < world.h - 2


def test_with_nowhere_to_fall_back_the_games_last_draw_runs(machines):
    """No empty tile of the faction's kind at all: the search hands back, and the game makes its own unjudged draw
    (draw index 1024, band = the whole map), exactly as it does after 1024 failures."""
    world, setup = scenario(12, 16, 12, False, owned=1.0)
    for t in world.tiles.values():
        t[8] |= 1
    setup["bases"] = []
    machines.load(world, **setup)
    order, given, got = _whole_search(machines, world, setup, 43, last_rands=(6, 5))
    assert given[-1] == ("none", -1, -1, KD) and got["rands"] == 2
    assert (got["x"], got["y"]) == (7, 5) and got["unjudged"] == 1 and got["counter"] == KD + 1
    want = machines.run("vanilla", counter=KD, rands=(6, 5))
    assert (want["x"], want["y"], want["unjudged"], want["at"]) == (7, 5, 1, EXIT)


# ------------------------------------------------------------------------------------------------ 6. rules only loosen
@pytest.mark.parametrize("seed,w,h,flat,kw", SCENARIOS)
def test_a_tile_accepted_at_some_draw_is_accepted_at_the_last(machines, seed, w, h, flat, kw):
    """What pass 2 rests on: judging every tile at the last draw number misses nothing an earlier draw would take."""
    world, setup = scenario(seed, w, h, flat, **kw)
    machines.load(world, **setup)
    rnd = random.Random(seed + 500)
    accepted = 0
    for _ in range(60):
        i = rnd.randrange(1023)
        x, y = rnd.choice([p for p in world.tiles if in_band(i, *p, w, h, flat)])
        if machines.judge(x, y, i)["at"] == EXIT:
            accepted += 1
            later = rnd.randrange(i, 1024)
            assert machines.judge(x, y, later)["at"] == EXIT and machines.judge(x, y, 1023)["at"] == EXIT
    assert accepted > 0


# ------------------------------------------------------------------------------------------------ 7. scope, install
@pytest.mark.parametrize("mode,why", [(1, "another caller of setup_player"), (2, "multiplayer"), (3, "turn 0: game start"),
                                      (4, "faction 0"), (5, "a jailer out of range"), (6, "no memory for the list")])
def test_anything_but_a_single_player_rescue_is_left_to_the_game(native, tmp_path, mode, why):
    """LandDriver::Step (what the hook calls) declines, draws no random number and writes nothing to the frame."""
    world = random_world(random.Random(3), 16, 12, False)
    path = tmp_path / "m.bin"
    path.write_bytes(struct.pack("<iiii", world.w, world.h, world.half, 0) + world.blob())
    assert native([f"loop {path} 0 3 77 {mode}"]) == [(0, 1, 0, 1)], why


def test_a_stale_search_never_reaches_another_call(native, tmp_path):
    """A rescue's search is dropped at the next call's first draw (counter 0): that call, on the very same frame
    address but not a rescue, gets the game's draws from its first to its later ones, with nothing written."""
    world = random_world(random.Random(4), 16, 12, False)
    for t in world.tiles.values():
        t[0x28:0x2A] = b"\xFF\xFF"
    path = tmp_path / "m.bin"
    path.write_bytes(struct.pack("<iiii", world.w, world.h, world.half, 0) + world.blob())
    assert native([f"loop {path} 0 3 77 7"]) == [(0, 5, 0, 1)]


def test_map_limits(native):
    cases = [((80, 80, 40, 1), 1), ((80, 80, 40, 0), 0), ((80, 81, 40, 1), 0), ((81, 80, 40, 1), 0), ((80, 80, 41, 1), 0),
             ((80, 4, 40, 1), 0), ((80, 6, 40, 1), 1), ((0, 80, 0, 1), 0), ((4096, 64, 2048, 1), 1), ((4098, 64, 2049, 1), 0),
             ((512, 512, 256, 1), 1), ((1024, 512, 512, 1), 0)]
    assert native([f"usable {w} {h} {half} {has}" for (w, h, half, has), _ in cases]) == [(v,) for _, v in cases]
    assert "constexpr int kMaxLandTiles = 1 << 17;" in CORE
    assert "malloc(leaderfree::kMaxLandTiles * sizeof(leaderfree::Tile))" in SRC          # the list always fits its memory


def test_the_hook_hands_the_engines_own_values_to_the_driver():
    nxt = _body("int __cdecl LandNext(")
    env = nxt[nxt.index("const leaderfree::LandEnv env{"):nxt.index("};")]
    assert [l.strip() for l in env.split("\n")[1:] if l.strip()] == [
        "static_cast<uint32_t>(reinterpret_cast<uintptr_t>(At(kVA_LandReturn))),",
        "Game<int>(kVA_Multiplayer) != 0,",
        "Game<int>(kVA_CurrentTurn),",
        "leaderfree::LandMap{ Game<int>(kVA_MapAreaX), Game<int>(kVA_MapAreaY), Game<int>(kVA_MapHalfX),",
        "(Game<int>(kVA_MapFlat) & 1) != 0, Game<const uint8_t*>(kVA_MapTiles) },",
        "At(kVA_FactionRules),"]
    assert "return g_landDriver.Step(frame, env, g_landTiles, reinterpret_cast<FRand>(At(kVA_GameRand)));" in nxt
    for text in ("kVA_MapAreaX     = 0x949870", "kVA_MapAreaY     = 0x949874", "kVA_MapHalfX     = 0x68FAF0",
                 "kVA_MapFlat      = 0x94988C", "kVA_MapTiles     = 0x94A30C", "kVA_CurrentTurn  = 0x9A64D4",
                 "kVA_Multiplayer  = 0x93F660", "kVA_FactionRules = 0x946F58"):
        assert SRC.count(text) == 1, text
    assert "constexpr int kFactionRulesStride = 0x59C;" in CORE and "constexpr uint32_t kRuleAquatic = 0x100;" in CORE
    stub = _body("__declspec(naked) void StubLand()")
    assert "push ebp\n        call LandNext" in stub                    # the frame the driver reads is setup_player's ebp


def test_the_search_is_base_game_only_and_installed_last():
    install = _body("void InstallLeaderFreeFix()")
    assert "InstallLandingSearch();" not in install[:install.index("return;")]       # never reached under Thinker
    assert SRC.count("InstallLandingSearch();") == 1 and install.rstrip().endswith("InstallLandingSearch();")
    body = _body("void InstallLandingSearch()")
    assert body.count("memcmp(") == 4 and body.index("memcmp(At(kVA_LandEntry)") < body.index("WriteCode(")
    assert "memcmp(head, kExpectLandHead, sizeof kExpectLandHead) != 0" in body and "BYTE* head = At(kVA_LandHead);" in body
    assert "WriteCode(head, jump, sizeof jump)" in body and body.count("WriteCode(") == 1
    assert "BYTE jump[kLandJumpLen] = { 0xE9, 0, 0, 0, 0, 0x90, 0x90, 0x90, 0x90 };" in body
    assert body.index("g_landHeadRest = At(kVA_LandHeadRest);") < body.index("WriteCode(")     # targets set before the jump exists
    assert body.index("g_landBody = At(kVA_LandBody);") < body.index("WriteCode(")
    assert len(re.findall(r'UimodLog\("[^;]*?\);\s*return;', body, re.S)) == 2


def test_no_thinker_write_touches_the_landing_sites(thinker, bak_path, need_local):
    img = T.Image(bak_path)
    hits = [(hex(w.addr), w.kind) for w in thinker["writes"] for lo, hi in ((HEAD, BODY + 9), (COUNT, COUNT + 0x26))
            if w.addr < hi and lo < w.addr + max(1, T.footprint(w, img))]
    assert hits == []
    dll = need_local(ROOT.parent / "refs" / "thinker-release" / "v5.5" / "thinker.dll", "the Thinker 5.5 release").read_bytes()
    assert [i for i in range(len(dll) - 3) if HEAD <= struct.unpack_from("<I", dll, i)[0] < BODY + 9] == []
