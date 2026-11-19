r"""The 1.0.1 cloak-filter + artillery groups (work\briefs\cloak-filter-1.0.1-spec.md): fix 1 combat reveal, fix 2 the
bombard scan skips undetected stacks, fix 3 the repaired counter-battery duel, fix 4 #HASTY before a human's hasty Long
Range Fire duel (DUELHASTY for the bombard's duel on one machine).

Pinned here, without a game launch:
  * every byte check and call check the install code makes (parsed from aivis.cpp / thinkeraivis.cpp) holds on the
    pristine exe and on Thinker 5.5 -- so a check that would self-disable a group on the shipped bytes fails here;
  * the source rules the audits fixed: #HASTY's polarity (0 = "Order the assault."), the cancel writes nothing, the
    DUELHASTY wording, the gates (installed + host latch), DuelSafe's mutual war, WrapPillageFight's order;
  * the COMPILED naked stubs from the built uimod.dll, run under Unicorn with the C callee faked: every branch, the
    replayed instructions, and the registers each site needs preserved.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "uimod" / "src"
UIMOD = ROOT / "src" / "uimod" / "build" / "Release" / "uimod.dll"
THINKER55 = ROOT / "refs" / "thinker-release" / "v5.5" / "thinker.dll"


def _src(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def _body(src: str, signature: str) -> str:
    i = src.index(signature)
    while ";" in src[i:src.index("\n", i)].split("//")[0]:   # skip forward declarations
        i = src.index(signature, i + 1)
    j = src.index("\n{", i)
    depth, k = 0, j + 1
    while True:
        c = src[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
        k += 1


@pytest.fixture(scope="module")
def image(bak_bytes) -> bytes:
    pefile = pytest.importorskip("pefile")
    return bytes(pefile.PE(data=bak_bytes).get_memory_mapped_image())


@pytest.fixture(scope="module")
def t55(need_local) -> bytes:
    pefile = pytest.importorskip("pefile")
    p = need_local(THINKER55, "the Thinker 5.5 release")
    pe = pefile.PE(str(p))
    assert pe.FILE_HEADER.TimeDateStamp == 0x6A821052 and pe.OPTIONAL_HEADER.SizeOfImage == 0x19F000
    return bytes(pe.get_memory_mapped_image())


def _call_target(img: bytes, site: int) -> int | None:
    if img[site] != 0xE8:
        return None
    return site + 5 + struct.unpack_from("<i", img, site + 1)[0]


# ---- every check the install code makes holds on the shipped bytes --------------------------------------------------

def test_engine_install_checks_hold_on_the_pristine_exe(image):
    body = _body(_src("aivis.cpp"), "void InstallArtilleryGroups()")
    checks = re.findall(r'BytesAt\((0x[0-9A-Fa-f]+),\s*"([0-9A-Fa-f ]+)"\)', body)
    assert len(checks) >= 24, "the engine groups byte-check every site and witness"
    for va, hexs in checks:
        o = int(va, 16) - 0x400000
        want = bytes.fromhex(hexs)
        assert image[o:o + len(want)] == want, f"BytesAt({va}) differs from the pristine exe"
    named = {"kVA_StackCheck": 0x5B9580, "kVA_VehSkip": 0x5C1D20, "kVA_BattleFight": 0x506A60, "kVA_Popp": 0x48C0A0}
    calls = re.findall(r"IsCallTo\((0x[0-9A-Fa-f]+),\s*(\w+)\)", body)
    assert len(calls) >= 6
    for site, tgt in calls:
        target = int(tgt, 16) if tgt.startswith("0x") else named[tgt]
        assert _call_target(image, int(site, 16) - 0x400000) == target - 0x400000, f"{site} does not call {tgt}"


def test_thinker_install_checks_hold_on_5_5(t55):
    src = _src("thinkeraivis.cpp")
    body = _body(src, "void InstallThinkerArtilleryGroups()")
    consts = {m.group(1): int(m.group(2), 16) for m in re.finditer(r"\b(k\w+)\s*=\s*(0x[0-9A-Fa-f]+)", src)}
    checks = re.findall(r'BytesAtT\((\w+),\s*"([0-9A-Fa-f ]+)"\)', body)
    assert len(checks) >= 13
    for off, hexs in checks:
        o = int(off, 16) if off.startswith("0x") else consts[off]
        want = bytes.fromhex(hexs)
        assert t55[o:o + len(want)] == want, f"BytesAtT({off}) differs from thinker.dll 5.5"
    tcalls = re.findall(r"IsCallTo\(g_base \+ (\w+),\s*g_base \+ (\w+)\)", body)
    assert len(tcalls) >= 4
    for site, tgt in tcalls:
        assert _call_target(t55, consts[site]) == consts[tgt], f"{site} does not call {tgt} in 5.5"
    # the Thinker half's frame slots: the defender's unit id word is written before the ask point
    assert t55[0xA7520:0xA7527] == bytes.fromhex("668985d8feffff")


def test_thinker_offsets_match_the_spec():
    src = _src("thinkeraivis.cpp")
    want = {"kRevealSite": 0xA8022, "kRevealResume": 0xA8029, "kBombScanCall": 0xA1396, "kModStackCheck": 0x8DC30,
            "kDestroySkipCall": 0xA0AF0, "kThinkerVehSkip": 0x8E490, "kThinkerDestroy": 0xA0AC0, "kNerveSite": 0xA97CF,
            "kNerveResume": 0xA97D5, "kNerveJoin": 0xA981A, "kArtySpCall": 0xA17E7, "kArtyNetCall": 0xA16E4,
            "kAskSite": 0xA7980, "kAskResume": 0xA7987, "kAskCancel": 0xA77E2}
    for name, v in want.items():
        m = re.search(rf"\b{name}\s*=\s*(0x[0-9A-Fa-f]+)", src)
        assert m and int(m.group(1), 16) == v, name


# ---- the rules the audits settled -------------------------------------------------------------------------------------

def test_hasty_polarity_and_the_cancel_writes_nothing():
    core = _body(_src("aivis.cpp"), "int AskHastyCore(")
    # popp returns 0 for "Order the assault." (first answer) -> go on; nonzero -> cancel (order_veh 0x595B8A)
    assert "if (r == 0) return 0;" in core and "return 1;" in core
    assert "0x80000" not in core and "kVehOrder" not in core and "StatusWin" not in core, "the cancel writes nothing"
    assert "saved = Rd<int>(kVA_VehAttackFlags)" in core and "*reinterpret_cast<int*>(At(kVA_VehAttackFlags)) = saved" in core
    assert "g_askHasty = 0;" in core.split("if (!ask)")[0], "one-shot: consumed before any test"
    assert "ctype != 3" in core and "kStateNoHaste" in core and "unit == 0xF" in core and "unit == 0x8" in core


def test_duelhasty_wording_is_the_users():
    body = _body(_src("aivis.cpp"), "bool BuildDuelFile()")
    text = "".join(re.findall(r'"([^"]*)"', body))
    for line in ("#DUELHASTY", "#xs 440", "#caption Operations Director",
                 "Enemy artillery is returning fire! A $UNITTYPE1 near the target has",
                 "opened a counter-battery duel, but our $UNITTYPE0 unit is not ready.",
                 "It would fight at only $NUM0/$NUM1 strength.",
                 "Order the assault.", "Await preparations and lose the turn."):
        assert line in text, line


def test_gates_require_installed_and_follow_the_host_latch():
    src = _src("aivis.cpp")
    nra = _body(src, "bool NewRuleActive(")
    assert "if (!installed) return false;" in nra and "return NetBitInForce(bit);" in nra
    inforce = _body(src, "bool NetBitInForce(")
    assert "if (Rd<int>(kVA_NetIsServer) != 0 && g_hostSentValid) return (g_hostSent & bit) != 0;" in inforce, \
        "the host uses the mask it broadcast"
    assert "return g_netValid && (g_netMask & bit) != 0;" in inforce, \
        "a client -- or a host that has not broadcast yet (became host mid-session) -- the mask it last received"
    mask = _body(src, "uint32_t LocalNetMask()")
    for frag in ("g_revealOk ? kNetBitReveal", "g_local && g_bombardOk && g_revealOk ? kNetBitBombAi",
                 "g_bombardOk ? kNetBitBombHuman", "g_duelOk ? kNetBitDuel"):
        assert frag in mask, frag
    send = _body(src, "void __cdecl WrapUpkeepSend(")
    assert "g_hostSent = mask;" in send and "g_hostSentValid = true;" in send
    bits = {m.group(1): int(m.group(2)) for m in re.finditer(r"(kNetBit\w+)\s*=\s*1u << (\d+)", src)}
    assert sorted(bits.values()) == list(range(len(bits))), "the net bits are distinct and contiguous"
    assert bits["kNetBitReveal"] == 5 and bits["kNetBitDuel"] == 8


def test_duel_safe_is_mutual_war_every_unit_no_base():
    src = _src("aivis.cpp")
    war = _body(src, "bool MutualWar(")
    assert "(a & kDiploVendetta) && (b & kDiploVendetta)" in war and "!(a & peace) && !(b & peace)" in war
    assert "f == 0 || g == 0" in war, "natives are at war with everyone"
    safe = _body(src, "bool DuelSafe(")
    assert "kVA_CanArty" in safe and "& 1) != 0) return false" in safe, "can bombard; not a base"
    assert "if (!MutualWar(f, VehFaction(i))) return false;" in safe, "every unit on the square"


def test_duel_run_sets_and_restores_the_engine_state():
    run = _body(_src("aivis.cpp"), "int DuelRun(")
    for frag in ("= 2;", "v[kVehMoves] = g_duel.moves;", "&= ~kStateUsedNerveGas;", "At(kVA_CurrentVehID)) = veh;",
                 "g_aivisInDuel = 1;", "= savedFlags;", "g_aivisInDuel = savedIn;"):
        assert frag in run, frag
    assert run.index("DuelSafe(") < run.index("= 2;"), "BLOCK before any state change"
    assert "Rd<int>(kVA_MultiplayerActive) == 0" in run, "the redirect asks on one machine only"


def test_wrap_pillage_fight_keeps_the_hidden_test_first():
    body = _body(_src("thinkeraivis.cpp"), "int __cdecl WrapPillageFight(")
    assert body.index("AiVisTileHidden") < body.index("AiVisDuelActive"), "(a) before (b), unconditional on bit 8"


# ---- the compiled stubs under Unicorn -------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dll():
    pefile = pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    if not UIMOD.exists():
        pytest.skip("uimod.dll not built")
    newest = max((SRC / n).stat().st_mtime for n in ("aivis.cpp", "aivis.h", "thinkeraivis.cpp", "prefs.cpp"))
    assert UIMOD.stat().st_mtime >= newest, "uimod.dll is older than its sources: rebuild before trusting the stub tests"
    pe = pefile.PE(str(UIMOD))
    return pe.OPTIONAL_HEADER.ImageBase, bytes(pe.get_memory_mapped_image())


def _find(img: bytes, hexpat: str) -> int:
    i = img.find(bytes.fromhex(hexpat))
    assert i >= 0, f"stub {hexpat} not found in uimod.dll"
    assert img.find(bytes.fromhex(hexpat), i + 1) < 0, f"stub {hexpat} is not unique"
    return i


class Emu:
    """The DLL image at its preferred base, a stack, a fake frame; the stub's C callee replaced by a stub that
    records its arguments and returns `ret`; the run stops at the first jump into a sentinel page."""
    SENT = 0x00700000   # sentinel page: jump targets land here
    STACK = 0x00200000
    FRAME = 0x00300000  # ebp

    def __init__(self, base, img):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EBP
        self.base, self.img = base, img
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        size = (len(img) + 0xFFF) & ~0xFFF
        self.uc.mem_map(base, size)
        self.uc.mem_write(base, img)
        self.uc.mem_map(self.STACK - 0x10000, 0x20000)
        self.uc.mem_map(self.FRAME - 0x1000, 0x2000)
        self.uc.mem_map(self.SENT, 0x1000)
        self.uc.mem_map(0x00900000, 0x200000)        # engine globals 0x93E904 / 0x93F660 ...
        self.uc.reg_write(UC_X86_REG_ESP, self.STACK)
        self.uc.reg_write(UC_X86_REG_EBP, self.FRAME)
        self.callee_args, self.callee = None, None
        self.ret = 0
        self.uc.hook_add(UC_HOOK_CODE, self._hook)

    def _hook(self, uc, addr, size, _):
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ECX, UC_X86_REG_EDX
        if self.callee is not None and addr == self.callee:
            esp = uc.reg_read(UC_X86_REG_ESP)
            ra = struct.unpack("<I", uc.mem_read(esp, 4))[0]
            self.callee_args = struct.unpack("<6I", uc.mem_read(esp + 4, 24))
            uc.reg_write(UC_X86_REG_EAX, self.ret)
            uc.reg_write(UC_X86_REG_ECX, 0xDEAD0001)    # a cdecl callee may clobber ecx / edx
            uc.reg_write(UC_X86_REG_EDX, 0xDEAD0002)
            uc.reg_write(UC_X86_REG_ESP, esp + 4)
            uc.reg_write(UC_X86_REG_EIP, ra)
        elif self.SENT <= addr < self.SENT + 0x1000:
            uc.emu_stop()

    def jmp_ptr(self, stub, nth=0):
        """Address of the nth `jmp dword ptr [X]` operand X inside the stub."""
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        found = [ins for ins in md.disasm(self.img[stub - self.base:stub - self.base + 96], stub)
                 if ins.mnemonic == "jmp" and ins.op_str.startswith("dword ptr [0x")]
        return int(found[nth].op_str[len("dword ptr ["):-1], 16)

    def call_target(self, stub):
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        for ins in md.disasm(self.img[stub - self.base:stub - self.base + 64], stub):
            if ins.mnemonic == "call":
                return int(ins.op_str, 16)
        raise AssertionError("no call in the stub")

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def run(self, start):
        from unicorn.x86_const import UC_X86_REG_EIP
        self.uc.emu_start(start, 0, count=500)
        return self.uc.reg_read(UC_X86_REG_EIP)


def _regs(emu, **vals):
    from unicorn import x86_const as R
    for k, v in vals.items():
        emu.uc.reg_write(getattr(R, f"UC_X86_REG_{k.upper()}"), v)


def _reg(emu, k):
    from unicorn import x86_const as R
    return emu.uc.reg_read(getattr(R, f"UC_X86_REG_{k.upper()}"))


@pytest.mark.parametrize("in_duel,mp,expect", [(0, 0, "single"), (0, 1, "net"), (1, 0, "join"), (1, 1, "join")])
def test_engine_nerve_gate(dll, in_duel, mp, expect):
    base, img = dll
    stub = None
    i = 0
    while True:   # the engine nerve gate: cmp [g_aivisInDuel],0 ; jne ; mov eax,ds:[0x93F660]
        i = img.find(bytes.fromhex("3ea160f69300"), i + 1)
        assert i > 0
        if img[i - 9:i - 7] == bytes.fromhex("833d"):
            stub = base + i - 9
            break
    emu = Emu(base, img)
    flag = struct.unpack_from("<I", img, stub - base + 2)[0]
    emu.w32(flag, in_duel)
    emu.w32(0x93F660, mp)
    targets = {"single": emu.SENT + 0x10, "net": emu.SENT + 0x20, "join": emu.SENT + 0x30}
    emu.w32(emu.jmp_ptr(stub, 0), targets["single"])
    emu.w32(emu.jmp_ptr(stub, 1), targets["net"])
    emu.w32(emu.jmp_ptr(stub, 2), targets["join"])
    assert emu.run(stub) == targets[expect]


@pytest.mark.parametrize("in_duel", [0, 1])
def test_thinker_nerve_gate_keeps_eax_and_edi(dll, in_duel):
    base, img = dll
    stub = base + _find(img, "8bb544ffffff") - 9          # cmp [g_aivisInDuel],0 (7) ; jne (2) ; mov esi,[ebp-0xBC]
    assert img[stub - base:stub - base + 2] == bytes.fromhex("833d")
    emu = Emu(base, img)
    emu.w32(struct.unpack_from("<I", img, stub - base + 2)[0], in_duel)
    emu.w32(emu.FRAME - 0xBC, 0x11223344)
    emu.w32(emu.jmp_ptr(stub, 0), emu.SENT + 0x10)        # +0xA97D5
    emu.w32(emu.jmp_ptr(stub, 1), emu.SENT + 0x20)        # +0xA981A (the join)
    _regs(emu, eax=0xAAAA0000, edi=0xBBBB0000, esi=0)
    end = emu.run(stub)
    assert _reg(emu, "eax") == 0xAAAA0000 and _reg(emu, "edi") == 0xBBBB0000
    if in_duel:
        assert end == emu.SENT + 0x20
    else:
        assert end == emu.SENT + 0x10 and _reg(emu, "esi") == 0x11223344


@pytest.mark.parametrize("cancel", [0, 1])
def test_engine_pre_attack_stub(dll, cancel):
    base, img = dll
    stub = base + _find(img, "5056ff75dcff7518ff75f0ff7508e8")
    emu = Emu(base, img)
    emu.callee = emu.call_target(stub)
    emu.ret = cancel
    for off, v in ((-0x24, 2), (0x18, 3), (-0x10, 5), (0x08, 77)):
        emu.w32(emu.FRAME + off, v)
    emu.w32(emu.jmp_ptr(stub, 0), emu.SENT + 0x10)        # 0x5070CE
    emu.w32(emu.jmp_ptr(stub, 1), emu.SENT + 0x20)        # 0x507E72
    _regs(emu, eax=0x0000A1B2, esi=0x00000C30, edi=0x00001234, ebx=0)
    esp0 = _reg(emu, "esp")
    end = emu.run(stub)
    assert emu.callee_args[:5] == (77, 5, 3, 2, 0xC30), "atk, faction, combat_type, moves left, defender unit*52"
    assert _reg(emu, "esp") == esp0, "the stub leaves esp as it found it (the cancel's epilogue needs it)"
    assert _reg(emu, "eax") == 0xA1B2 and _reg(emu, "esi") == 0xC30 and _reg(emu, "edi") == 0x1234
    if cancel:
        assert end == emu.SENT + 0x20
    else:
        assert end == emu.SENT + 0x10
        assert _reg(emu, "ecx") == 5 and _reg(emu, "edx") == 1, "the replayed mov ecx,[ebp-0x10] ; mov edx,1"


@pytest.mark.parametrize("cancel", [0, 1])
def test_thinker_pre_attack_stub(dll, cancel):
    base, img = dll
    stub = base + _find(img, "60ffb5d8feffffffb52cffffffffb5e0feffff")
    emu = Emu(base, img)
    emu.callee = emu.call_target(stub)
    emu.ret = cancel
    for off, v in ((-0x128, 0x0042), (-0xD4, 3), (-0x120, 2), (-0xF8, 2), (-0xD8, 9)):
        emu.w32(emu.FRAME + off, v)
    emu.uc.mem_write(emu.FRAME - 0x125, bytes([0x07]))
    emu.w32(emu.jmp_ptr(stub, 0), emu.SENT + 0x10)        # +0xA7987
    emu.w32(emu.jmp_ptr(stub, 1), emu.SENT + 0x20)        # +0xA77E2
    _regs(emu, ecx=0x1111, edx=0x2222, ebx=0x3333, esi=0x4444, edi=0x5555)
    esp0 = _reg(emu, "esp")
    end = emu.run(stub)
    a = emu.callee_args
    assert a[:4] == (9, 2, 2, 3) and (a[4] & 0xFFFF) == 0x42, "atk, faction, MapWin owner, combat_type, defender unit (word)"
    assert _reg(emu, "esp") == esp0
    assert (_reg(emu, "ecx"), _reg(emu, "edx"), _reg(emu, "ebx"), _reg(emu, "esi"), _reg(emu, "edi")) == \
        (0x1111, 0x2222, 0x3333, 0x4444, 0x5555), "pushad / popad: every register kept"
    if cancel:
        assert end == emu.SENT + 0x20 and _reg(emu, "eax") == 1, "mov eax,1 before the odds return's epilogue"
    else:
        assert end == emu.SENT + 0x10 and _reg(emu, "eax") == 7, "the replayed movzx eax, byte [ebp-0x125]"


@pytest.mark.parametrize("pattern,frame_slots,replay_check", [
    ("609cff75f4ff7508e8", ((-0x0C, 4), (0x08, 61), (0x18, 1)), "engine"),
    ("609cffb5f8feffffffb528ffffffe8", ((-0x108, 4), (-0xD8, 61), (-0xD4, 1)), "thinker"),
])
def test_combat_reveal_stubs(dll, pattern, frame_slots, replay_check):
    base, img = dll
    stub = base + _find(img, pattern)
    emu = Emu(base, img)
    emu.callee = emu.call_target(stub)
    for off, v in frame_slots:
        emu.w32(emu.FRAME + off, v)
    emu.w32(emu.jmp_ptr(stub, 0), emu.SENT + 0x10)
    _regs(emu, ebx=0x3333, ecx=0x1111, edx=0x2222, esi=0x4444, edi=0x5555)
    end = emu.run(stub)
    assert end == emu.SENT + 0x10
    assert emu.callee_args[:2] == (61, 4), "CombatReveal(attacker id, defending faction)"
    assert (_reg(emu, "ebx"), _reg(emu, "esi"), _reg(emu, "edi")) == (0x3333, 0x4444, 0x5555)
    zf = (_reg(emu, "eflags") >> 6) & 1
    assert zf == 1, "the replayed cmp ...,1 sets the flags the following branch reads (combat_type 1)"
    if replay_check == "engine":
        assert _reg(emu, "eax") == 1, "the replayed mov eax,[ebp+0x18]"


@pytest.mark.parametrize("pattern,actor_slot", [
    ("ff7508ff742418ff742418", "ebp+8"),
    ("ff742464ff742418", "esp+0x60"),
])
def test_bombard_stack_check_stubs_forward_the_arguments(dll, pattern, actor_slot):
    base, img = dll
    stub = base + _find(img, pattern)
    emu = Emu(base, img)
    emu.callee = emu.call_target(stub)
    emu.ret = 0x55
    esp = emu.STACK - 0x100
    # the caller: call stub with stack, 15, owner, -1, -1 at [esp+0..0x10] after the return address push
    ret_addr = emu.SENT + 0x40
    emu.w32(esp, ret_addr)
    for k, v in enumerate((0x31, 15, 3, 0xFFFFFFFF, 0xFFFFFFFF)):
        emu.w32(esp + 4 + 4 * k, v)
    if actor_slot == "ebp+8":
        emu.w32(emu.FRAME + 8, 0x99)
    else:
        emu.w32(esp + 4 + 0x60, 0x99)                     # the caller's [esp+0x60]
    _regs(emu, esp=esp)
    end = emu.run(stub)
    assert end == ret_addr and _reg(emu, "eax") == 0x55
    assert emu.callee_args == (0x31, 15, 3, 0xFFFFFFFF, 0xFFFFFFFF, 0x99), "(stack, type, a3, a4, a5, actor)"
    assert _reg(emu, "esp") == esp + 4, "the stub returns like stack_check (cdecl: the caller cleans)"


# ---- the install code binds every stub to the right engine / Thinker addresses ------------------------------------

def test_engine_stub_pointers_and_detour_lengths():
    body = _body(_src("aivis.cpp"), "void InstallArtilleryGroups()")
    for ptr, va in (("g_revealResume", 0x5084AE), ("g_ngSingle", 0x5071BD), ("g_ngNet", 0x5071B0),
                    ("g_ngJoin", 0x5073BC), ("g_askResume", 0x5070CE), ("g_askCancel", 0x507E72)):
        assert re.search(rf"{ptr} = At\(0x{va:X}\);", body), f"{ptr} must be At(0x{va:X})"
    for site, n, stub in ((0x5084A8, 6, "StubCombatReveal"), (0x5071A7, 9, "StubNerveGate"), (0x5070C6, 8, "StubPreAttack")):
        assert f"DetourSiteN(0x{site:X}, {n}, &{stub})" in body, (site, n, stub)
    for site, fn in ((0x4CACC2, "StubBombardStackCheck"), (0x4CAA7C, "WrapDestroySkip"), (0x4CACFD, "WrapBombardDuel"),
                     (0x4CD272, "WrapArtyFight"), (0x4CD2AD, "WrapArtyFight")):
        assert f"RetargetOk(0x{site:X}, &{fn})" in body, (site, fn)
    assert "g_duelOk = g_bombardOk &&" in body, "the duel needs the scan skip"


def test_thinker_stub_pointers_and_detour_lengths():
    body = _body(_src("thinkeraivis.cpp"), "void InstallThinkerArtilleryGroups()")
    for ptr, c in (("g_tRevealResume", "kRevealResume"), ("g_tNerveResume", "kNerveResume"), ("g_tNerveJoin", "kNerveJoin"),
                   ("g_tAskResume", "kAskResume"), ("g_tAskCancel", "kAskCancel")):
        assert f"{ptr} = g_base + {c};" in body, ptr
    for c, n, stub in (("kRevealSite", 7, "StubCombatRevealT"), ("kNerveSite", 6, "StubNerveGateT"), ("kAskSite", 7, "StubPreAttackT")):
        assert f"siteJmp({c}, {n}, &{stub})" in body, (c, n, stub)
    assert "AiVisSetThinkerGroups(ok1, ok2, ok3 && ok2, ok4)" in body, "the duel needs the scan skip"
    for c, fn in (("kBombScanCall", "StubBombardStackCheckT"), ("kDestroySkipCall", "WrapDestroySkipT"),
                  ("kArtySpCall", "WrapArtyFightT"), ("kArtyNetCall", "WrapArtyFightT")):
        assert f"Retarget(g_base + {c}, &{fn})" in body, (c, fn)


def test_offset_tables_match_the_engine(image):
    src = _src("aivis.cpp")
    xs = [int(v) for v in re.search(r"kTableOffsetX\[25\] = \{([^}]*)\}", src).group(1).split(",")]
    ys = [int(v) for v in re.search(r"kTableOffsetY\[25\] = \{([^}]*)\}", src).group(1).split(",")]
    ex = struct.unpack_from("<25i", image, 0x66EFBC - 0x400000)
    ey = struct.unpack_from("<25i", image, 0x66F440 - 0x400000)
    assert tuple(xs) == ex and tuple(ys) == ey, "battle_fight's table_offset tables"


def test_no_patch_of_ours_touches_the_sites(patches_path):
    sites = [(0x5084A8, 6), (0x4CACC2, 5), (0x4CAA7C, 5), (0x4CACFD, 5), (0x5071A7, 9), (0x5070C6, 8),
             (0x4CD272, 5), (0x4CD2AD, 5)]
    text = Path(patches_path).read_text(encoding="utf-8", errors="replace")
    hits = []
    found = 0
    for m in re.finditer(r"virtual_addr:\s*(0x[0-9A-Fa-f]+)", text):
        found += 1
        va = int(m.group(1), 16)
        for s0, n in sites:
            if s0 - 16 <= va < s0 + n:
                hits.append((hex(va), hex(s0)))
    assert found > 100, "patches.yaml lists its sites as virtual_addr"
    assert not hits, f"a patch of ours sits on a 1.0.1 site: {hits}"


def test_patched_exes_keep_the_site_bytes(baked_exe):
    pefile = pytest.importorskip("pefile")
    img = bytes(pefile.PE(str(baked_exe)).get_memory_mapped_image())
    body = _body(_src("aivis.cpp"), "void InstallArtilleryGroups()")
    for va, hexs in re.findall(r'BytesAt\((0x[0-9A-Fa-f]+),\s*"([0-9A-Fa-f ]+)"\)', body):
        o = int(va, 16) - 0x400000
        want = bytes.fromhex(hexs)
        assert img[o:o + len(want)] == want, f"BytesAt({va}) differs in the baked exe (a patch moved the site)"



def test_baked_exe_keeps_the_call_sites(baked_exe):
    pefile = pytest.importorskip("pefile")
    img = bytes(pefile.PE(str(baked_exe)).get_memory_mapped_image())
    body = _body(_src("aivis.cpp"), "void InstallArtilleryGroups()")
    named = {"kVA_StackCheck": 0x5B9580, "kVA_VehSkip": 0x5C1D20, "kVA_BattleFight": 0x506A60, "kVA_Popp": 0x48C0A0}
    calls = re.findall(r"IsCallTo\((0x[0-9A-Fa-f]+),\s*(\w+)\)", body)
    assert len(calls) >= 7
    for site, tgt in calls:
        target = int(tgt, 16) if tgt.startswith("0x") else named[tgt]
        assert _call_target(img, int(site, 16) - 0x400000) == target - 0x400000, f"{site} moved in the baked exe"


def test_combat_reveal_reads_hidden_before_marking_and_uses_the_latch():
    body = _body(_src("aivis.cpp"), "void __cdecl CombatReveal(")
    assert body.index("HiddenStack(atk, def)") < body.index("|= static_cast<BYTE>(1u << def);   // what the watching"), \
        "HiddenStack must be read before the attacker is marked (it reads that bit)"
    assert "if (net && !(g_coreOk && NetBitInForce(kNetBitAiVis)))" in body, \
        "in a network game the whole-stack rule follows the broadcast cloak setting, not the host's live checkbox"
    assert "Enabled()" not in body


def test_game_start_reset_skips_the_two_non_start_callers(image):
    src = _src("aivis.cpp")
    body = _body(src, "void  __cdecl AiVisOnGameStart(")
    assert "0x0051C5D9" in body and "0x00515441" in body and "NetMasksReset();" in body
    # those are desktop_init's return addresses from the two calls that are not a game start / load
    for ret in (0x51C5D9, 0x515441):
        assert _call_target(image, ret - 5 - 0x400000) == 0x58EE60 - 0x400000
    assert image[0x58EE60 - 0x400000:0x58EE63 - 0x400000] == bytes.fromhex("558bec"), "desktop_init keeps an ebp frame"
    reset = _body(src, "void NetMasksReset()") if "void NetMasksReset()\n{" in src else src[src.index("void NetMasksReset()"):]
    assert "g_netValid = false" in reset and "g_hostSentValid = false" in reset
    thunk = _src("prefs.cpp")
    t = thunk[thunk.index("void __declspec(naked) BuildHookThunk()"):]
    t = t[:t.index("\n}\n")]
    assert "push dword ptr [ebp + 4]" in t and "call AiVisOnGameStart" in t, "desktop_init's caller is passed through"
