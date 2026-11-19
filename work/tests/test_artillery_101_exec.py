r"""The 1.0.1 artillery rules EXECUTED: the compiled C logic of the built uimod.dll, located through uimod.pdb, run under
Unicorn against fake game memory (vehicles, units, map squares, the factions' diplomacy, the network state), with every
engine call it makes faked and recorded. Each case is checked against a model of the rule as the spec states it
(work\briefs\cloak-filter-1.0.1-spec.md), and the memory layout the fakes write is pinned to Thinker's packed engine
headers (refs\thinker\src), an independent source -- as are aivis.cpp's own offset constants.

Entry points are the functions the game itself calls -- the ones LTCG must keep at their declared cdecl convention:
BombardStackCheck (the scan's stack_check), WrapDestroySkip / WrapBombardDuel (the redirect's veh_skip and fight),
CombatReveal (the branch split), AskHastyEngine (the pre-attack stub), WrapArtyFight, WrapUpkeepSend, AiVisOnGameStart,
and Thinker's WrapPillageFight / AskHastyT. The small rules (NewRuleActive, MutualWar, DuelSafe, DuelIneligible,
DuelRun, AskHastyCore) are compiled into them with register conventions or inlined, so they are covered through those.

Cost: ~1,630 cases, a few ms each (one fresh Unicorn machine per case, the DLL image and symbols shared per worker);
~13 s serial, split evenly by xdist. Its value is the executed truth tables: a mutation audit (2026-11-15) showed the
source-shape tests in test_artillery_101.py let a dropped treaty / pact test or a missing record check through.
"""
from __future__ import annotations

import itertools
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "uimod" / "src"
BUILD = ROOT / "src" / "uimod" / "build" / "Release"
DLL, PDB = BUILD / "uimod.dll", BUILD / "uimod.pdb"
THINKER_SRC = ROOT / "refs" / "thinker" / "src"

# ---- engine addresses (terranx.h) ----
MP, SERVER, CURPLAYER = 0x93F660, 0x93E8C0, 0x939284
ATTACK_FLAGS, CUR_VEH, ROAD, SCRIPT_FILE = 0x93E904, 0x9A64DC, 0x949738, 0x691B0C
VEH_COUNT, UNITS, FACTION_STATUS, FACTIONS = 0x9A64C8, 0x9AB868, 0x9A64E8, 0x96C9E0
MAP_TILES, MAP_HALF_X, MAP_AX, MAP_AY, MAP_FLAT = 0x94A30C, 0x68FAF0, 0x949870, 0x949874, 0x94988C
F_VEH_AT, F_CAN_ARTY, F_STACK_CHECK, F_FIGHT = 0x5BFE90, 0x5C0DB0, 0x5B9580, 0x506A60
F_VEH_SKIP, F_VEH_SPEED, F_POPP, F_SAYS, F_NUM, F_MSG = 0x5C1D20, 0x5C1540, 0x48C0A0, 0x625EC0, 0x625E30, 0x592EE0
F_NETMSG_POP, NETMSG = 0x47A890, 0x805338   # NetMsg_pop: thiscall (ecx = the ticker), 4 stack args, RET 0x10;
                                            # reads its label from the DEFAULT script file (its last arg is unused)
F_SET_DEF_FILE, DEF_FILE = 0x6043D0, 0x9B8AA8   # BasePop_set_def_file(name) cdecl -> 0 / 3 (> 12 chars); char[13]
F_ASK_RET = 0x506A70         # the fake fight's return path when it chains into AskHastyEngine

# ---- layouts: Thinker's packed headers are the reference (test_layouts_match_thinker pins every one) ----
VEH_SIZE, FACTION_SIZE, UNIT_SIZE, MAP_SIZE = 0x34, 0x20CC, 0x34, 0x2C
V_X, V_Y, V_STATE, V_FLAGS, V_UNIT, V_FACTION = 0x00, 0x02, 0x04, 0x08, 0x0A, 0x0E
V_VIS, V_MOVES, V_NEXT, V_PREV = 0x27, 0x28, 0x30, 0x32
F_DIPLO, U_ABILITY = 0x18, 0x20
M_ITEMS = 0x08

PACT, TREATY, TRUCE, VENDETTA = 0x1, 0x2, 0x4, 0x10
WAR = VENDETTA
HAS_MOVED, NO_HASTE, NERVE = 0x4, 0x1000, 0x80000
U_CLOAK_ARTY, U_ARTY, U_PLAIN = 1, 2, 3     # cloaked artillery, artillery, a unit that cannot bombard
CAN_ARTY = {U_CLOAK_ARTY: True, U_ARTY: True, U_PLAIN: False}
TABLE_X = (0, 1, 2, 1, 0, -1, -2, -1, 0, 2, 2, -2, -2, 1, 3, 3, 1, -1, -3, -3, -1, 4, -4, 0, 0)
TABLE_Y = (0, -1, 0, 1, 2, 1, 0, -1, -2, -2, 2, 2, -2, -3, -1, 1, 3, 3, 1, -1, -3, 0, 0, 4, -4)

STACK, STACK_TOP = 0x00100000, 0x001F0000
SENT, IMPS = 0x00300000, 0x00301000
GDT, TEB = 0x00304000, 0x00305000
GAME_LO, GAME_HI = 0x00400000, 0x00A00000
TILES, VEHS, STRS = 0x02000000, 0x03000000, 0x04000000
MAP_W, MAP_H = 20, 20
CALLEE_SAVED = {"ebx": 0x0B0B0B0B, "esi": 0x05050505, "edi": 0x0D0D0D0D, "ebp": 0x0E0E0E0E}


# ---- layouts --------------------------------------------------------------------------------------------------------

_SIZES = {"int8_t": 1, "uint8_t": 1, "char": 1, "int16_t": 2, "uint16_t": 2, "int32_t": 4, "uint32_t": 4, "int": 4}


def thinker_offsets(header: str, struct_name: str) -> dict[str, int]:
    """Field offsets of a #pragma pack(1) struct in Thinker's headers (scalar and array members up to the first
    method)."""
    text = (THINKER_SRC / header).read_text(encoding="utf-8", errors="replace")
    body = re.sub(r"/\*.*?\*/", "", text[text.index(f"struct {struct_name} {{"):], flags=re.S)
    out, off = {}, 0
    for line in body.splitlines()[1:]:
        code = line.split("//")[0].strip()
        if not code:
            continue
        if "(" in code or code.startswith("}"):
            break
        m = re.fullmatch(r"(\w+)\s+(\w+)((?:\[\d+\])*);", code)
        assert m, f"{struct_name}: cannot parse {code!r}"
        if m.group(1) not in _SIZES:
            break                       # a nested struct type: later offsets are unknown (a lookup past it fails)
        out[m.group(2)] = off
        count = 1
        for dim in re.findall(r"\[(\d+)\]", m.group(3)):
            count *= int(dim)
        off += _SIZES[m.group(1)] * count
    return out


def test_layouts_match_thinker():
    if not THINKER_SRC.exists():
        pytest.skip("refs\\thinker not cloned")
    veh = thinker_offsets("engine_veh.h", "VEH")
    unit = thinker_offsets("engine_veh.h", "UNIT")
    fac = thinker_offsets("engine_types.h", "Faction")
    sq = thinker_offsets("engine_types.h", "MAP")
    want = [(veh, "x", V_X), (veh, "y", V_Y), (veh, "state", V_STATE), (veh, "flags", V_FLAGS),
            (veh, "unit_id", V_UNIT), (veh, "faction_id", V_FACTION), (veh, "visibility", V_VIS),
            (veh, "moves_spent", V_MOVES), (veh, "next_veh_id_stack", V_NEXT), (veh, "prev_veh_id_stack", V_PREV),
            (fac, "diplo_status", F_DIPLO), (unit, "ability_flags", U_ABILITY), (sq, "items", M_ITEMS)]
    for table, field, off in want:
        assert table[field] == off, f"{field}: Thinker says {table[field]:#x}, the fakes write {off:#x}"
    # aivis.cpp's own constants against the same reference
    src = (SRC / "aivis.cpp").read_text(encoding="utf-8")
    consts = {m.group(1): int(m.group(2), 16) for m in re.finditer(r"\b(k\w+)\s*=\s*(0x[0-9A-Fa-f]+)", src)}
    for name, ref in {"kVehX": veh["x"], "kVehY": veh["y"], "kVehFlags": veh["flags"], "kVehUnit": veh["unit_id"],
                      "kVehFaction": veh["faction_id"], "kVehOrder": veh["order"], "kVehVisibility": veh["visibility"],
                      "kVehNext": veh["next_veh_id_stack"], "kVehPrev": veh["prev_veh_id_stack"],
                      "kVehState": veh["state"], "kVehMoves": veh["moves_spent"], "kVehWaypointX0": veh["waypoint_x"],
                      "kUnitAbility": unit["ability_flags"], "kUnitChassis": unit["chassis_id"],
                      "kUnitCarry": unit["carry_capacity"], "kFactionDiplo": fac["diplo_status"]}.items():
        assert consts[name] == ref, f"aivis.cpp {name} = {consts[name]:#x}, Thinker's layout says {ref:#x}"


# ---- the machine ----------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def build():
    pefile = pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    from pdbsyms import Pdb, image_symbols
    if not DLL.exists() or not PDB.exists():
        pytest.skip("uimod.dll / uimod.pdb not built (src\\uimod\\build.bat)")
    newest = max((SRC / n).stat().st_mtime for n in ("aivis.cpp", "aivis.h", "thinkeraivis.cpp"))
    assert DLL.stat().st_mtime >= newest, "uimod.dll is older than its sources: rebuild before trusting these tests"
    pe = pefile.PE(str(DLL))
    cv = [d.struct for d in pe.DIRECTORY_ENTRY_DEBUG if d.struct.Type == 2][0]   # CodeView: 'RSDS' + GUID + age
    rsds = pe.__data__[cv.PointerToRawData:cv.PointerToRawData + 24]
    pdb = Pdb(PDB)
    assert rsds[:4] == b"RSDS" and pdb.guid() == rsds[4:20] and pdb.age() == struct.unpack_from("<I", rsds, 20)[0], \
        "uimod.pdb is not the PDB of this uimod.dll"
    syms = image_symbols(PDB, DLL, "\\aivis.obj")
    tsyms = image_symbols(PDB, DLL, "\\thinkeraivis.obj")
    thinker_state = image_symbols(PDB, DLL, "\\thinkerversion.obj")["g"]   # thinkerversion.cpp's `Detected g`
    imports = {imp.address: imp.name.decode() for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports if imp.name}
    return pe.OPTIONAL_HEADER.ImageBase, bytes(pe.get_memory_mapped_image()), syms, tsyms, imports, thinker_state


_BOOLS = {"g_coreOk", "g_netOk", "g_netValid", "g_hostSentValid", "g_revealOk", "g_bombardOk", "g_duelOk", "g_askOk",
          "g_duelFileOk"}


class Game:
    """One fresh machine: the DLL, fake engine memory, fake engine functions."""

    def __init__(self, build):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        base, img, self.syms, self.tsyms, imports, thinker_state = build
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(base, (len(img) + 0xFFF) & ~0xFFF)
        uc.mem_write(base, img)
        for lo, size in ((STACK, 0x100000), (SENT, 0x2000), (GAME_LO, GAME_HI - GAME_LO), (TILES, 0x100000),
                         (VEHS, 0x100000), (STRS, 0x1000)):
            uc.mem_map(lo, size)
        self.imp_names = {}
        for k, (slot, name) in enumerate(sorted(imports.items())):
            stub = IMPS + 8 * k
            self.imp_names[stub] = name
            uc.mem_write(slot, struct.pack("<I", stub))
        uc.hook_add(UC_HOOK_CODE, self._imp, begin=IMPS, end=IMPS + 0x1000)
        uc.hook_add(UC_HOOK_CODE, self._engine, begin=GAME_LO, end=GAME_HI)
        self.calls: list[tuple] = []
        self.vehs: list[tuple[int, int]] = []
        self.veh_at_pick = "last"        # which stack member the fake veh_at returns (the rules must walk to the top)
        self.fight_ret, self.popp_ret, self.speed = 1, 0, 3
        self.fight_declines = False      # the fake fight sets g_duelDeclined (the DUELHASTY "lose the turn" answer)
        self.fight_asks = None           # (ctype, defUnit): the fake fight reaches the pre-attack point
        self.error = None
        self.w32(MAP_AX, MAP_W)
        self.w32(MAP_AY, MAP_H)
        self.w32(MAP_HALF_X, MAP_W // 2)
        self.w32(MAP_TILES, TILES)
        self.road(3)
        # plain PRACX: thinkerversion.cpp's detection already ran and found no thinker.dll (Detected{decided, found}).
        # Its own run opens a C++ EH frame through fs:[0], which this machine has no thread block for; a loaded
        # Thinker's reduced-mode gates are that file's, tested by its own suite.
        uc.mem_write(thinker_state, b"\x01\x00")
        uc.mem_write(DEF_FILE, b"xscript\0" + b"\xEE" * 5)   # the game's default script name (+ junk after its NUL)
        self._thread_block()
        self.uc.mem_write(STRS, b"SCRIPT\0")
        self.w32(SCRIPT_FILE, STRS)
        for x in range(MAP_W):                     # land everywhere
            for y in range(MAP_H):
                self.uc.mem_write(self.tile(x, y), b"\x60")
        for u, name in ((U_CLOAK_ARTY, b"Cloaked Artillery"), (U_ARTY, b"Artillery"), (U_PLAIN, b"Scout")):
            self.uc.mem_write(UNITS + u * UNIT_SIZE, name + b"\0")
        self.uc.mem_write(UNITS + U_CLOAK_ARTY * UNIT_SIZE + U_ABILITY, struct.pack("<I", 0x04))   # ABL_CLOAKED
        self.w32(self.syms["g_vehs"], VEHS)
        self.w32(self.tsyms["g_vehs"], VEHS)
        self.w32(self.tsyms["g_battleFight"], F_FIGHT)
        # everything installed and in force for single player
        self.dll(g_coreOk=1, g_netOk=1, g_revealOk=1, g_bombardOk=1, g_duelOk=1, g_askOk=1, g_duelFileOk=1, g_local=1)
        self.humans(1)
        self.w32(CURPLAYER, 1)

    # ---- memory ----
    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def road(self, r):
        self.w32(ROAD, r)

    def dll(self, **kv):
        """Set the DLL's own globals (bools are one byte, the rest four)."""
        for k, v in kv.items():
            if k in _BOOLS:
                self.uc.mem_write(self.syms[k], bytes([v & 1]))
            else:
                self.w32(self.syms[k], v)

    def get(self, k):
        return self.r8(self.syms[k]) if k in _BOOLS else self.r32(self.syms[k])

    def humans(self, *factions):
        self.uc.mem_write(FACTION_STATUS, bytes([sum(1 << f for f in factions)]))

    def net(self, n):
        """A network game: n = dict(server, mask (client), sent (host), net_ok)."""
        self.w32(MP, 1)
        self.w32(SERVER, 1 if n["server"] else 0)
        self.dll(g_netOk=int(n.get("net_ok", True)),
                 g_netValid=int(n.get("mask") is not None), g_netMask=n.get("mask") or 0,
                 g_hostSentValid=int(n.get("sent") is not None), g_hostSent=n.get("sent") or 0)

    def diplo(self, f, g, v):
        self.w32(FACTIONS + f * FACTION_SIZE + F_DIPLO + g * 4, v)

    def war(self, f, g):
        self.diplo(f, g, WAR)
        self.diplo(g, f, WAR)

    def tile(self, x, y):
        return TILES + (y * (MAP_W // 2) + (x >> 1)) * MAP_SIZE

    def base_at(self, x, y):
        self.w32(self.tile(x, y) + M_ITEMS, 1)

    def veh(self, x, y, faction, unit, vis=0, moves=0, state=0):
        i = len(self.vehs)
        self.vehs.append((x, y))
        a = VEHS + i * VEH_SIZE
        self.uc.mem_write(a + V_X, struct.pack("<hhI", x, y, state))
        self.uc.mem_write(a + V_UNIT, struct.pack("<h", unit))
        self.uc.mem_write(a + V_FACTION, bytes([faction]))
        self.uc.mem_write(a + V_VIS, bytes([vis, moves]))
        self.w32(VEH_COUNT, len(self.vehs))
        self.relink()
        return i

    def relink(self):
        """Link every square's stack in creation order (the first unit made is the top)."""
        for sq in set(self.vehs):
            stack = [j for j, p in enumerate(self.vehs) if p == sq]
            for k, j in enumerate(stack):
                nxt = stack[k + 1] if k + 1 < len(stack) else -1
                prv = stack[k - 1] if k > 0 else -1
                self.uc.mem_write(VEHS + j * VEH_SIZE + V_NEXT, struct.pack("<hh", nxt, prv))

    def move(self, i, x, y):
        self.vehs[i] = (x, y)
        self.uc.mem_write(VEHS + i * VEH_SIZE + V_X, struct.pack("<hh", x, y))
        self.relink()

    def vset(self, i, off, fmt, v):
        self.uc.mem_write(VEHS + i * VEH_SIZE + off, struct.pack(fmt, v))

    def vfield(self, i, off, fmt="<I"):
        return struct.unpack(fmt, self.uc.mem_read(VEHS + i * VEH_SIZE + off, struct.calcsize(fmt)))[0]

    def vis(self, i):
        return self.r8(VEHS + i * VEH_SIZE + V_VIS)

    def cstr(self, a):
        b = bytes(self.uc.mem_read(a, 64))
        return b[:b.index(b"\0")].decode("latin-1")

    # ---- fakes ----
    def _thread_block(self):
        """fs -> a TEB whose SEH chain is empty (fs:[0] = -1), through a one-entry GDT: the DLL's C++ EH frames
        (thinkerversion.cpp's detection, reached from ThinkerAllows) push and pop fs:[0]."""
        from unicorn.x86_const import (UC_X86_REG_GDTR, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
                                       UC_X86_REG_FS)
        uc = self.uc
        uc.mem_map(GDT, 0x1000)
        uc.mem_map(TEB, 0x1000)
        uc.mem_write(TEB, struct.pack("<I", 0xFFFFFFFF))
        uc.mem_write(TEB + 0x18, struct.pack("<I", TEB))

        def desc(base, limit, access, flags):            # flags 0xC: 4K granular, 32-bit; 0x4: byte granular, 32-bit
            return (limit & 0xFFFF) | ((base & 0xFFFFFF) << 16) | (access << 40) | (((limit >> 16) & 0xF) << 48) | \
                   (flags << 52) | (((base >> 24) & 0xFF) << 56)
        uc.mem_write(GDT + 8, struct.pack("<QQQ", desc(0, 0xFFFFF, 0x9A, 0xC),     # 1: flat code, ring 0
                                          desc(0, 0xFFFFF, 0x92, 0xC),             # 2: flat data
                                          desc(TEB, 0xFFF, 0x92, 0x4)))            # 3: the TEB
        uc.reg_write(UC_X86_REG_GDTR, (0, GDT, 4 * 8 - 1, 0))
        uc.reg_write(UC_X86_REG_CS, 1 << 3)
        for r in (UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS):
            uc.reg_write(r, 2 << 3)
        uc.reg_write(UC_X86_REG_FS, 3 << 3)

    def _ret(self, uc, eax):
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ECX, UC_X86_REG_EDX
        esp = uc.reg_read(UC_X86_REG_ESP)
        ra = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ECX, 0xDEAD0001)      # a cdecl callee may clobber ecx / edx
        uc.reg_write(UC_X86_REG_EDX, 0xDEAD0002)
        uc.reg_write(UC_X86_REG_ESP, esp + 4)
        uc.reg_write(UC_X86_REG_EIP, ra)

    def _args(self, uc, n):
        from unicorn.x86_const import UC_X86_REG_ESP
        esp = uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack(f"<{n}i", uc.mem_read(esp + 4, 4 * n))

    def _imp(self, uc, addr, size, _):
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX, UC_X86_REG_EIP
        name = self.imp_names.get(addr)
        if name in ("GetModuleHandleA", "GetModuleHandleW"):
            esp = uc.reg_read(UC_X86_REG_ESP)
            ra, p = struct.unpack("<II", uc.mem_read(esp, 8))
            wide = name.endswith("W")
            raw = bytes(uc.mem_read(p, 64)) if p else b""
            text = (raw.decode("utf-16-le", "replace") if wide else raw.decode("latin-1")).split("\0")[0] if p else ""
            # the game's own module (null or its name) -> its base; thinker.dll -> not loaded (these tests model plain
            # PRACX: the reduced-mode gates of a loaded Thinker are thinkerversion.cpp's, tested by its own suite)
            uc.reg_write(UC_X86_REG_EAX, 0 if text.lower() == "thinker.dll" else 0x400000)
            uc.reg_write(UC_X86_REG_ESP, esp + 8)     # stdcall, one argument
            uc.reg_write(UC_X86_REG_EIP, ra)
            return
        self.error = f"unexpected import call: {name}"
        uc.emu_stop()

    def _engine(self, uc, addr, size, _):
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EAX
        if addr == F_VEH_AT:
            x, y = self._args(uc, 2)
            ids = [j for j, p in enumerate(self.vehs) if p == (x, y)]
            self.calls.append(("veh_at", x, y))
            return self._ret(uc, (ids[-1] if self.veh_at_pick == "last" else ids[0]) if ids else -1)
        if addr == F_CAN_ARTY:
            unit, sea = self._args(uc, 2)
            self.calls.append(("can_arty", unit, sea))
            return self._ret(uc, 0x7FFFFF00 | int(CAN_ARTY.get(unit, False)))   # junk above al
        if addr == F_STACK_CHECK:
            self.calls.append(("stack_check",) + self._args(uc, 5))
            return self._ret(uc, 7)
        if addr == F_FIGHT:
            args = self._args(uc, 5)
            self.calls.append(("fight", args, dict(
                flags=self.r32(ATTACK_FLAGS), cur=self.r32(CUR_VEH), in_duel=self.r32(self.syms["g_aivisInDuel"]),
                ask=self.get("g_askHasty"), moves=self.vfield(args[0], V_MOVES, "<B"),
                state=self.vfield(args[0], V_STATE))))
            if self.fight_declines:
                self.dll(g_duelDeclined=1)
            if self.fight_asks is not None:          # chain: the fight reaches the pre-attack point
                ctype, def_unit = self.fight_asks
                # the haste block's moves left: speed - moves spent, as the fight sees them (the restore must reach it)
                left = max(0, self.speed - self.vfield(args[0], V_MOVES, "<B"))
                self.calls.append(("left", left))
                esp = uc.reg_read(UC_X86_REG_ESP)
                f = self.vfield(args[0], V_FACTION, "<B")
                uc.mem_write(esp - 24, struct.pack("<6i", F_ASK_RET, args[0], f, ctype, left, def_unit * UNIT_SIZE))
                uc.reg_write(UC_X86_REG_ESP, esp - 24)
                uc.reg_write(UC_X86_REG_EIP, self.syms["AskHastyEngine"])
                return
            return self._ret(uc, self.fight_ret)
        if addr == F_ASK_RET:                         # AskHastyEngine returned into the fake fight
            asked = uc.reg_read(UC_X86_REG_EAX)
            self.calls.append(("ask_returned", asked))
            esp = uc.reg_read(UC_X86_REG_ESP)        # cdecl: its five arguments are still on the stack
            uc.reg_write(UC_X86_REG_ESP, esp + 20)
            return self._ret(uc, 0 if asked else self.fight_ret)
        if addr == F_VEH_SKIP:
            self.calls.append(("veh_skip",) + self._args(uc, 1))
            return self._ret(uc, 0)
        if addr == F_VEH_SPEED:
            self.calls.append(("veh_speed",) + self._args(uc, 2))
            return self._ret(uc, self.speed)
        if addr == F_POPP:
            file, label, a3, pcx, fn = self._args(uc, 5)
            self.calls.append(("popp", self.cstr(file), self.cstr(label), self.cstr(pcx)))
            self.w32(ATTACK_FLAGS, 0x55)             # a modal pumps messages: the flags must be restored after it
            return self._ret(uc, self.popp_ret)
        if addr == F_NETMSG_POP:
            from unicorn.x86_const import UC_X86_REG_ECX
            this = uc.reg_read(UC_X86_REG_ECX)
            label, delay, a4, _unused = self._args(uc, 4)
            self.calls.append(("netmsg", this, self.cstr(label), delay, a4, self.cstr(DEF_FILE)))   # the file it reads
            esp = uc.reg_read(UC_X86_REG_ESP)
            ra = struct.unpack("<I", uc.mem_read(esp, 4))[0]
            uc.reg_write(UC_X86_REG_ESP, esp + 4 + 16)   # callee-cleaned
            uc.reg_write(UC_X86_REG_EAX, 0)
            uc.reg_write(UC_X86_REG_EIP, ra)
            return
        if addr == F_SET_DEF_FILE:
            (p,) = self._args(uc, 1)
            name = self.cstr(p)
            self.calls.append(("set_def_file", name))
            if len(name) > 12:
                return self._ret(uc, 3)
            uc.mem_write(DEF_FILE, name.encode("latin-1") + b"\0")
            return self._ret(uc, 0)
        if addr == F_SAYS:
            slot, text, a3, a4 = self._args(uc, 4)
            self.calls.append(("says", slot, self.cstr(text)))
            return self._ret(uc, 0)
        if addr == F_NUM:
            self.calls.append(("num",) + self._args(uc, 2))
            return self._ret(uc, 0)
        if addr == F_MSG:
            self.calls.append(("message_data",) + tuple(a & 0xFFFFFFFF for a in self._args(uc, 6)))
            return self._ret(uc, 0)
        self.error = f"unexpected engine call {addr:#x}"
        uc.emu_stop()

    # ---- calling ----
    def call(self, fn, *args, thinker=False):
        from unicorn import x86_const as R
        addr = (self.tsyms if thinker else self.syms)[fn]
        esp = STACK_TOP - 4 * (len(args) + 1)
        self.uc.mem_write(esp, struct.pack(f"<I{len(args)}i", SENT, *args))
        self.uc.reg_write(R.UC_X86_REG_ESP, esp)
        for reg, v in CALLEE_SAVED.items():
            self.uc.reg_write(getattr(R, f"UC_X86_REG_{reg.upper()}"), v)
        self.uc.emu_start(addr, SENT, count=200_000)
        assert self.error is None, self.error
        assert self.uc.reg_read(R.UC_X86_REG_EIP) == SENT, f"{fn}: did not return (instruction budget spent)"
        assert self.uc.reg_read(R.UC_X86_REG_ESP) == esp + 4, f"{fn}: unbalanced stack (not cdecl?)"
        for reg, v in CALLEE_SAVED.items():
            assert self.uc.reg_read(getattr(R, f"UC_X86_REG_{reg.upper()}")) == v, f"{fn}: {reg} not preserved"
        return self.uc.reg_read(R.UC_X86_REG_EAX)

    def named(self, kind):
        return [c for c in self.calls if c[0] == kind]


# ---- the rules as the spec states them -----------------------------------------------------------------------------

def mutual_war(dip, f, g):
    """Spec B1: vendetta in both directions and no truce / treaty / pact either way; natives at war with everyone."""
    if f == g:
        return False
    if f == 0 or g == 0:
        return True
    a, b = dip.get((f, g), 0), dip.get((g, f), 0)
    return bool(a & VENDETTA) and bool(b & VENDETTA) and not ((a | b) & (PACT | TREATY | TRUCE))


def rule(bit, local_on, installed, n):
    """Spec common rules: single player = the local value; a host = the mask it last broadcast; a client = the mask it
    received; nothing broadcast / received, no carrier, or the group not installed -> off."""
    if not installed:
        return False
    if n is None:
        return local_on
    if not n.get("net_ok", True):
        return False
    # a host its last broadcast; a client -- or a host that has not broadcast yet (it became host mid-session) -- the
    # mask it last received (review 2026-11-15)
    m = n["sent"] if n["server"] and n.get("sent") is not None else n.get("mask")
    return m is not None and bool(m & (1 << bit))


ALL = 0x1FF
NETS = {
    "single": None,
    "host_sent_all": dict(server=1, sent=ALL),
    "host_cloak_off": dict(server=1, sent=ALL & ~0x41),         # host's cloak setting off: bits 0 and 6 clear
    "host_before_first_broadcast": dict(server=1),
    "host_new_follows_last_received": dict(server=1, mask=ALL & ~0x100),   # became host mid-session: no broadcast yet
    "host_new_sent_overrides": dict(server=1, mask=0x1F, sent=ALL),        # once it broadcasts, its own mask wins
    "host_no_carrier": dict(server=1, sent=ALL, net_ok=False),
    "client_101": dict(server=0, mask=ALL),
    "client_101_cloak_off": dict(server=0, mask=ALL & ~0x41),
    "client_follows_100_host": dict(server=0, mask=0x1F),       # a 1.0.0 host sends bits 0..4 only
    "client_nothing_received": dict(server=0),
    "client_no_carrier": dict(server=0, mask=ALL, net_ok=False),
}

# diplomacy between the firer's faction 1 and faction 2, both directions
DIPLO = {
    "war": {(1, 2): WAR, (2, 1): WAR},
    "war_one_way": {(1, 2): WAR, (2, 1): 0},
    "war_other_way": {(1, 2): 0, (2, 1): WAR},
    "truce": {(1, 2): WAR | TRUCE, (2, 1): WAR | TRUCE},
    "truce_their_side": {(1, 2): WAR, (2, 1): WAR | TRUCE},
    "treaty_over_war": {(1, 2): WAR | TREATY, (2, 1): WAR | TREATY},
    "treaty_our_side": {(1, 2): WAR | TREATY, (2, 1): WAR},
    "pact_over_war": {(1, 2): WAR | PACT, (2, 1): WAR | PACT},
    "pact_their_side": {(1, 2): WAR, (2, 1): WAR | PACT},
    "treaty": {(1, 2): TREATY, (2, 1): TREATY},
    "none": {},
}


def _dip(diplo):
    d = dict(DIPLO[diplo])
    for f, g in ((1, 3), (2, 3), (2, 4), (2, 5), (3, 4)):
        d[(f, g)] = d[(g, f)] = WAR
    d[(1, 4)] = d[(4, 1)] = WAR | PACT          # faction 4: the firer's pact partner (vendetta bit left set on purpose)
    d[(1, 5)] = d[(5, 1)] = WAR | TREATY        # faction 5: a treaty partner
    return d


def _world(g, diplo="war", net=None):
    for (f, h), v in _dip(diplo).items():
        g.diplo(f, h, v)
    if net is not None:
        g.net(net)


# ---- the bombard scan: fix 2's cloak half + the non-war skip (BombardStackCheck) -----------------------------------

SQUARES = {   # units on the scanned square: (faction, unit, seen by the firer's faction 1); the first made is the top
    "foreign_arty": [(2, U_ARTY, False)],
    "foreign_hidden": [(2, U_CLOAK_ARTY, False)],
    "foreign_seen_cloaked": [(2, U_CLOAK_ARTY, True)],
    "own": [(1, U_ARTY, False)],
    "natives": [(0, U_ARTY, False)],
    "arty_beside_scout_of_3": [(2, U_ARTY, False), (3, U_PLAIN, False)],
    "scout_of_3_then_arty": [(3, U_PLAIN, False), (2, U_ARTY, False)],
    "arty_of_2_and_3": [(2, U_ARTY, False), (3, U_ARTY, False)],
    "arty_of_3_then_2": [(3, U_ARTY, False), (2, U_ARTY, False)],
    "only_a_scout_of_3": [(3, U_PLAIN, False)],
    "pact_partner_arty": [(4, U_ARTY, False)],
}


def _scan_expect(units, owner, ff, passed, dip, n, firer, local, bomb_ok=True, duel_ok=True, base=False,
                 reveal_ok=True):
    counted = [fac for fac, unit, _s in units if (owner < 0 or fac == owner) and CAN_ARTY[unit]]
    assert bomb_ok or not duel_ok, "impossible: the duel group requires the scan group"
    # user 2026-11-15: a stack that cannot take a FAIR duel (a friendly unit of any kind on it, a base) is passed by
    fair = not base and all(mutual_war(dip, ff, fac) for fac, _u, _s in units)
    peace = rule(8, True, duel_ok, n) and (not any(mutual_war(dip, ff, fac) for fac in counted) or not fair)
    hidden = (not base) and all(fac != ff and unit == U_CLOAK_ARTY and not seen for fac, unit, seen in units)
    if firer.startswith("ai"):
        on = rule(6, local != 0, bomb_ok and reveal_ok, n)   # needs the reveal group too (review 2026-11-15)
    elif firer == "human":
        on = n is None and rule(7, True, bomb_ok, n)         # single machine only: a human's seen bits are local
    else:
        on = False                                    # natives: the cloak half is vanilla
    return peace or (on and units[passed][0] != ff and hidden)


def _scan(build, units, *, owner, diplo="war", firer="human", net=None, passed=0, local=1, groups=None, base=False):
    g = Game(build)
    _world(g, diplo, NETS[net] if net else None)
    g.dll(g_local=local, **(groups or {}))
    if firer.startswith("ai"):
        g.humans(3)
    ff = 0 if firer == "native" else 1
    actor = g.veh(5, 5, ff, U_ARTY)
    ids = [g.veh(7, 5, fac, unit, vis=(1 << ff) if seen else 0) for fac, unit, seen in units]
    if base:
        g.base_at(7, 5)
    r = g.call("BombardStackCheck", ids[passed], 15, owner, -1, -1, actor)
    skip = _scan_expect(units, owner, ff, passed, _dip(diplo), NETS[net] if net else None, firer, local,
                        bomb_ok=bool((groups or {}).get("g_bombardOk", 1)),
                        duel_ok=bool((groups or {}).get("g_duelOk", 1)), base=base,
                        reveal_ok=bool((groups or {}).get("g_revealOk", 1)))
    if skip:
        assert r == 0 and not g.named("stack_check"), "skipped: the scan sees no stack here"
    else:
        assert r == 7 and g.named("stack_check") == [("stack_check", ids[passed], 15, owner, -1, -1)], \
            "the engine's own answer"
    return g


@pytest.mark.parametrize("passed", [0, -1], ids=["top", "last"])
@pytest.mark.parametrize("owner", [-1, 2, 3])
@pytest.mark.parametrize("diplo", DIPLO)
@pytest.mark.parametrize("square", SQUARES)
def test_scan_war_rules(build, square, diplo, owner, passed):
    """Single player, a human firer: which stacks the scan no longer sees (only units type 15 counts decide)."""
    units = SQUARES[square]
    _scan(build, units, owner=owner, diplo=diplo, passed=passed % len(units))


@pytest.mark.parametrize("groups", [{}, {"g_duelOk": 0}, {"g_bombardOk": 0, "g_duelOk": 0}, {"g_revealOk": 0}],
                         ids=["all", "no_duel_group", "no_scan_group", "no_reveal_group"])   # duel needs the scan group
@pytest.mark.parametrize("net", NETS)
@pytest.mark.parametrize("square", ["foreign_hidden", "foreign_arty", "own", "pact_partner_arty"])
@pytest.mark.parametrize("firer,local", [("human", 1), ("ai", 1), ("ai_local_off", 0), ("native", 1)])
def test_scan_gates(build, firer, local, square, net, groups):
    """Who the rules apply to, and when: the setting, the host's broadcast, a 1.0.0 host, a missing group."""
    _scan(build, SQUARES[square], owner=-1, firer=firer, net=net, local=local, groups=groups)


def test_scan_passes_by_at_war_artillery_in_a_base(build):
    """No silent BLOCK (user 2026-11-15): a base square cannot take a fair duel, so the scan goes on."""
    g = _scan(build, SQUARES["foreign_arty"], owner=-1, base=True)
    assert not g.named("stack_check")


@pytest.mark.parametrize("duel_ok", [1, 0])
def test_scan_firer_that_cannot_bombard_passes_every_stack(build, duel_ok):
    """A firer with no artillery of its own (a terrain strike by any other unit) cannot duel: with the duel repaired
    every at-war artillery stack is passed by and the bombardment lands; without it, vanilla asks stack_check."""
    g = Game(build)
    _world(g, "war", None)
    g.dll(g_local=1, g_duelOk=duel_ok)
    actor = g.veh(5, 5, 1, U_PLAIN)
    stack = g.veh(7, 5, 2, U_ARTY)
    r = g.call("BombardStackCheck", stack, 15, -1, -1, -1, actor)
    assert (r == 0 and not g.named("stack_check")) if duel_ok else r == 7


def test_scan_hidden_stack_in_a_base_is_seen(build):
    _scan(build, SQUARES["foreign_hidden"], owner=-1, base=True)


def test_scan_hidden_stack_passed_by_its_last_unit(build):
    _scan(build, [(2, U_CLOAK_ARTY, False), (2, U_CLOAK_ARTY, True)], owner=-1, passed=1)


# ---- fix 3: the repaired duel (WrapDestroySkip + WrapBombardDuel) ---------------------------------------------------

def _duel(build, *, diplo="war", net=None, target=((2, U_ARTY),), firer_unit=U_ARTY, firer_faction=1, base=False,
          offset=2, at=(5, 5), humans=(1,), local=1, flat=False, state=NERVE, moves=1, mutate=None, groups=None):
    g = Game(build)
    _world(g, diplo, net)
    g.dll(**(groups or {}))
    g.humans(*humans)
    g.w32(CURPLAYER, local)
    g.w32(MAP_FLAT, 1 if flat else 0)
    x, y = at
    actor = g.veh(x, y, firer_faction, firer_unit, moves=moves, state=state)
    g.w32(ATTACK_FLAGS, 0x13)            # the stale value vanilla leaves
    g.w32(CUR_VEH, 0x77)
    g.call("WrapDestroySkip", actor)     # the entry veh_skip: records the firer, then spends its moves
    assert g.named("veh_skip") == [("veh_skip", actor)]
    g.vset(actor, V_MOVES, "<B", g.speed)          # veh_skip spent every move
    if mutate:
        mutate(g, actor)                 # the firer changes between the record and the fight
    x, y = g.vehs[actor]
    tx, ty = x + TABLE_X[offset], y + TABLE_Y[offset]
    if not flat:
        tx %= MAP_W
    for fac, unit in target:
        g.veh(tx, ty, fac, unit)
    if base:
        g.base_at(tx, ty)
    g.calls.clear()
    return g, actor


def _fought(g):
    return [c for c in g.calls if c[0] == "fight"]


def _restored(g):
    assert g.r32(ATTACK_FLAGS) == 0x13, "the flags are restored"
    assert g.r32(g.syms["g_aivisInDuel"]) == 0 and g.get("g_askHasty") == 0
    assert struct.unpack("<i", g.uc.mem_read(g.syms["g_duel"], 4))[0] == -1, "the record is consumed"


@pytest.mark.parametrize("pick", ["first", "last"])
@pytest.mark.parametrize("diplo", DIPLO)
def test_duel_fights_only_at_mutual_war(build, diplo, pick):
    g, actor = _duel(build, diplo=diplo, target=((2, U_ARTY), (2, U_ARTY)))
    g.veh_at_pick = pick
    r = g.call("WrapBombardDuel", actor, 2, 0, 0, 0)
    if mutual_war(_dip(diplo), 1, 2):
        (_, args, at) = _fought(g)[0]
        assert args == (actor, 2, 0, 0, 0) and r == 1
        notice = ("netmsg", NETMSG, "DUELFIRE", 5000, 0, "uimod_duel")
        assert g.named("netmsg") == [notice], "the firer's ticker says the enemy returns fire"
        assert g.calls.index(notice) < g.calls.index(_fought(g)[0]), "before the duel is fought"
        assert at["flags"] == 2, "execute, non-interactive"
        assert at["moves"] == 1, "the firer's moves before the entry veh_skip"
        assert at["state"] & NERVE == 0, "no stale used-nerve-gas"
        assert at["cur"] == actor and at["in_duel"] == 1
        assert at["ask"] == 2, "single player, the local human firer: DUELHASTY may be asked"
    else:
        assert not _fought(g) and r == 0, "BLOCK: no shot"
        assert not g.named("netmsg"), "a BLOCK says nothing"
    _restored(g)
    assert not g.named("veh_skip")


@pytest.mark.parametrize("file_ok", [1, 0])
@pytest.mark.parametrize("net", ["single", "host_sent_all", "client_101"])
@pytest.mark.parametrize("firer", ["local_human", "other_human", "ai"])
def test_duel_notice_only_on_the_firers_machine(build, net, firer, file_ok):
    """The ticker is display only: the local human firer's machine, single player or network, never a peer's or an
    AI's (and nothing without the script file)."""
    humans = {"local_human": (1,), "other_human": (1, 2), "ai": (3,)}[firer]
    local = 2 if firer == "other_human" else 1
    g, actor = _duel(build, net=NETS[net], humans=humans, local=local, groups={"g_duelFileOk": file_ok})
    g.call("WrapBombardDuel", actor, 2, 0, 0, 0)
    assert _fought(g)
    shown = file_ok and firer == "local_human"
    assert g.named("netmsg") == ([("netmsg", NETMSG, "DUELFIRE", 5000, 0, "uimod_duel")] if shown else [])
    assert g.named("set_def_file") == ([("set_def_file", "uimod_duel"), ("set_def_file", "xscript")] if shown else [])
    assert g.cstr(DEF_FILE) == "xscript", "the game's default script file is put back"


def test_duel_notice_text():
    src = (SRC / "aivis.cpp").read_text(encoding="utf-8")
    body = src[src.index("bool BuildDuelFile()"):]
    body = body[:body.index("\n}\n") if "\n}\n" in body else body.index("\r\n}\r\n")]
    assert '"#DUELFIRE\\r\\n#xs 440\\r\\n#caption Operations Director\\r\\n"' in body
    assert '"Enemy artillery is returning fire!\\r\\n\\r\\n";' in body, "the user's wording (2026-11-15)"
    assert "if (g_askOk || g_duelOk) g_duelFileOk = BuildDuelFile();" in src, "the engine half writes it for the duel too"
    assert "if ((ask || duel) && !g_duelFileOk) g_duelFileOk = BuildDuelFile();" in src, "and the Thinker half"


def _moved_x(g, a):
    g.move(a, g.vehs[a][0] + 1, g.vehs[a][1])


def _moved_y(g, a):
    g.move(a, g.vehs[a][0], g.vehs[a][1] + 1)


def _other_unit(g, a):
    g.vset(a, V_UNIT, "<h", U_CLOAK_ARTY)


def _other_faction(g, a):
    g.vset(a, V_FACTION, "<B", 3)


def _record_of_another(g, a):
    other = g.veh(15, 15, 1, U_ARTY, moves=1)
    g.call("WrapDestroySkip", other)


@pytest.mark.parametrize("case,blocks,kw", [
    ("baseline", False, {}),
    ("cannot_bombard", True, dict(firer_unit=U_PLAIN)),
    ("base_square", True, dict(base=True)),
    ("pact_partner_first_on_square", True, dict(target=((4, U_ARTY), (2, U_ARTY)))),
    ("pact_partner_last_on_square", True, dict(target=((2, U_ARTY), (4, U_ARTY)))),
    ("treaty_partner_first_on_square", True, dict(target=((5, U_PLAIN), (2, U_ARTY)))),
    ("own_unit_first_on_square", True, dict(target=((1, U_PLAIN), (2, U_ARTY)))),
    ("natives_on_square", False, dict(target=((0, U_ARTY), (2, U_ARTY)))),
    ("native_firer", False, dict(firer_faction=0)),
    ("firer_moved_x", True, dict(mutate=_moved_x)),
    ("firer_moved_y", True, dict(mutate=_moved_y)),
    ("firer_unit_changed", True, dict(mutate=_other_unit)),
    ("firer_faction_changed", True, dict(mutate=_other_faction)),
    ("record_of_another_vehicle", True, dict(mutate=_record_of_another)),
    ("wraps_west_edge", False, dict(at=(0, 5), offset=6)),          # dx -2 -> x 18
    ("wraps_east_edge", False, dict(at=(19, 5), offset=2)),         # dx +2 -> x 1
    ("flat_map_off_edge", True, dict(at=(0, 5), offset=6, flat=True)),
])
def test_duel_safe_cases(build, case, blocks, kw):
    g, actor = _duel(build, **kw)
    g.veh_at_pick = "last"
    r = g.call("WrapBombardDuel", actor, kw.get("offset", 2), 0, 0, 0)
    assert bool(_fought(g)) is not blocks and (r == 0) is blocks
    if case == "wraps_west_edge":
        assert ("veh_at", MAP_W - 2, 5) in g.calls
    if case == "wraps_east_edge":
        assert ("veh_at", 1, 5) in g.calls
    if case == "cannot_bombard":
        assert ("can_arty", U_PLAIN, 1) in g.calls
    _restored(g)


@pytest.mark.parametrize("offset", [0, 25, -1])
def test_duel_bad_offset_is_never_fought(build, offset):
    g, actor = _duel(build)
    assert g.call("WrapBombardDuel", actor, offset, 0, 0, 0) == 0 and not _fought(g)


@pytest.mark.parametrize("why", ["client_follows_100_host", "client_nothing_received", "host_before_first_broadcast",
                                 "client_no_carrier", "no_duel_group"])
def test_duel_is_vanilla_when_bit_8_is_not_in_force(build, why):
    if why == "no_duel_group":
        g, actor = _duel(build, groups={"g_duelOk": 0})
    else:
        g, actor = _duel(build, net=NETS[why])
    r = g.call("WrapBombardDuel", actor, 2, 0, 0, 0)
    (_, _args, at) = _fought(g)[0]
    assert r == 1 and at["flags"] == 0x13 and at["cur"] == 0x77 and at["moves"] == g.speed and at["in_duel"] == 0, \
        "vanilla: the stale flags, no restored moves, no duel marker"
    assert not g.named("netmsg"), "vanilla's own path: no notice"


@pytest.mark.parametrize("ask_ok", [1, 0])
@pytest.mark.parametrize("net", ["single", "host_sent_all", "client_101"])
@pytest.mark.parametrize("firer", ["local_human", "other_human", "ai"])
def test_duel_asks_only_the_local_human_in_single_player(build, net, firer, ask_ok):
    humans = {"local_human": (1,), "other_human": (1, 2), "ai": (3,)}[firer]
    local = 2 if firer == "other_human" else 1
    g, actor = _duel(build, net=NETS[net], humans=humans, local=local, groups={"g_askOk": ask_ok})
    g.call("WrapBombardDuel", actor, 2, 0, 0, 0)
    (_, _args, at) = _fought(g)[0]
    asks = ask_ok and net == "single" and firer == "local_human"
    assert at["ask"] == (2 if asks else 0)


@pytest.mark.parametrize("thinker", [False, True])
def test_duel_declined_loses_the_turn(build, thinker):
    g, actor = _duel(build, state=0)
    g.fight_declines = True
    r = g.call("WrapPillageFight" if thinker else "WrapBombardDuel", actor, 2, 0, 0, 0, thinker=thinker)
    assert r == 1
    assert g.named("veh_skip") == [("veh_skip", actor)], "the declined firer is skipped after the call"
    assert bool(g.vfield(actor, V_STATE) & HAS_MOVED) is thinker, "Thinker parity: HAS_MOVED"
    assert g.get("g_duelDeclined") == 0


@pytest.mark.parametrize("thinker", [False, True])
def test_duel_block_parity(build, thinker):
    g, actor = _duel(build, diplo="truce", state=0)
    r = g.call("WrapPillageFight" if thinker else "WrapBombardDuel", actor, 2, 0, 0, 0, thinker=thinker)
    assert r == 0 and not _fought(g)
    assert bool(g.vfield(actor, V_STATE) & HAS_MOVED) is thinker


def test_thinker_duel_is_thinkers_own_call_when_inactive(build):
    g, actor = _duel(build, net=NETS["client_follows_100_host"])
    r = g.call("WrapPillageFight", actor, 2, 0, 0, 0, thinker=True)
    (_, _args, at) = _fought(g)[0]
    assert r == 1 and at["flags"] == 0x13 and at["in_duel"] == 0


@pytest.mark.parametrize("at,offset,wraps_to", [((5, 5), 2, (7, 5)), ((19, 5), 2, (1, 5))])
@pytest.mark.parametrize("filter_on", [True, False])
def test_thinker_pillage_keeps_the_hidden_tile_block_first(build, at, offset, wraps_to, filter_on):
    """WrapPillageFight (a): an AI firer never shoots at a tile whose stack it has not seen -- before the duel."""
    g, actor = _duel(build, at=at, offset=offset, humans=(3,), target=((2, U_CLOAK_ARTY),))
    g.dll(g_local=int(filter_on))
    r = g.call("WrapPillageFight", actor, offset, 0, 0, 0, thinker=True)
    assert ("veh_at",) + wraps_to in g.calls
    if filter_on:
        assert r == 0 and not _fought(g)
    else:
        assert r == 1 and _fought(g)[0][2]["flags"] == 2, "the filter off: the repaired duel"


@pytest.mark.parametrize("recorded,popp,asked,fought", [
    (1, 0, True, True),          # one move left of three: hasty -> DUELHASTY; "Order the assault." -> fight
    (1, 1, True, False),         # "Await preparations and lose the turn." -> no fight, firer skipped
    (0, 0, False, True),         # a full turn's moves left: no penalty, no question
])
def test_duel_chain_through_duelhasty(build, recorded, popp, asked, fought):
    """The whole path: the restored moves reach the haste block, which asks DUELHASTY; the answer decides."""
    g, actor = _duel(build, state=0, moves=recorded)
    g.popp_ret = popp
    g.fight_asks = (3, U_ARTY)
    r = g.call("WrapBombardDuel", actor, 2, 0, 0, 0)
    assert g.named("left") == [("left", g.speed - recorded)]
    popps = g.named("popp")
    if asked:
        assert [p[1:3] for p in popps] == [("uimod_duel", "DUELHASTY")]
        assert ("says", 1, "Artillery") in g.calls, "$UNITTYPE1 = the defender"
    else:
        assert not popps
    assert r == (1 if fought else 0)
    assert g.named("veh_skip") == ([] if fought else [("veh_skip", actor)])


# ---- fix 4: the ask (AskHastyEngine -> AskHastyCore) ----------------------------------------------------------------

ASK_CASES = {   # name -> (overrides, asks)
    "long_range_fire": ({}, True),
    "no_mark": ({"mark": 0}, False),
    "not_interactive_pass": ({"flags": 2}, False),
    "network_check_pass": ({"flags": 1, "mp": 1}, True),
    "bombardment_not_duel": ({"ctype": 1}, False),
    "no_haste_state": ({"state": NO_HASTE}, False),
    "unit_0xF": ({"unit": 0xF}, False),
    "unit_0x8": ({"unit": 0x8}, False),
    "not_the_local_player": ({"local": 2, "humans": (1, 2)}, False),
    "ai_firer": ({"humans": ()}, False),
    "native_firer": ({"f": 0}, False),
    "redirect_single_player": ({"mark": 2}, True),
    "redirect_network": ({"mark": 2, "mp": 1}, False),
    "redirect_no_defender": ({"mark": 2, "def_off": -1}, False),
    "redirect_bad_defender_offset": ({"mark": 2, "def_off": 0x35}, False),
}


def _ask(build, o, answer, left=1, road=3):
    g = Game(build)
    f = o.get("f", 1)
    g.humans(*o.get("humans", (1,)))
    g.w32(CURPLAYER, o.get("local", 1))
    g.w32(MP, o.get("mp", 0))
    g.road(road)
    atk = g.veh(5, 5, f, o.get("unit", U_ARTY), state=o.get("state", 0))
    g.dll(g_askHasty=o.get("mark", 1))
    flags = o.get("flags", 3)
    g.w32(ATTACK_FLAGS, flags)
    g.popp_ret = answer
    r = g.call("AskHastyEngine", atk, f, o.get("ctype", 3), left, o.get("def_off", U_ARTY * UNIT_SIZE))
    assert g.get("g_askHasty") == 0, "the mark is one-shot"
    assert g.r32(ATTACK_FLAGS) == flags, "the flags survive the modal"
    return g, r


@pytest.mark.parametrize("answer", [0, 1])
@pytest.mark.parametrize("case", ASK_CASES)
def test_ask_hasty(build, case, answer):
    o, asks = ASK_CASES[case]
    g, r = _ask(build, o, answer)
    popps = g.named("popp")
    if not asks:
        assert r == 0 and not popps and not g.named("says")
        return
    redirect = o.get("mark", 1) == 2
    assert popps == [("popp", "uimod_duel" if redirect else "SCRIPT", "DUELHASTY" if redirect else "HASTY",
                      "bad_sm.pcx")]
    assert ("says", 0, "Artillery") in g.calls and ("num", 0, 1) in g.calls and ("num", 1, 3) in g.calls
    assert r == answer, "0 = Order the assault., anything else cancels"
    assert g.get("g_duelDeclined") == (1 if redirect and answer else 0)


@pytest.mark.parametrize("road,delta", [(r, d) for r in (1, 2, 3, 4) for d in (-2, -1, 0, 1, 996) if r + d >= 0])
def test_ask_only_below_one_full_move(build, road, delta):
    """The haste penalty applies when the moves left are below one full move (the road rate): exactly one full move,
    or more, asks nothing."""
    left = road + delta
    g, r = _ask(build, {}, 1, left=left, road=road)
    assert r == int(left < road) and bool(g.named("popp")) is (left < road)


@pytest.mark.parametrize("mark,speed,moves,asks", [(0, 3, 2, False), (1, 3, 2, True), (1, 6, 3, False),
                                                    (1, 6, 4, True), (1, 3, 5, True), (1, 9, 0, False)])
def test_thinker_ask_computes_moves_left(build, mark, speed, moves, asks):
    g = Game(build)
    g.speed = speed
    atk = g.veh(5, 5, 1, U_ARTY, moves=moves)
    g.dll(g_askHasty=mark)
    g.w32(ATTACK_FLAGS, 3)
    g.popp_ret = 1
    r = g.call("AskHastyT", atk, 1, 1, 3, U_ARTY, thinker=True)
    assert bool(g.named("veh_speed")) is (mark != 0), "no mark, no work"
    assert r == int(asks)
    if asks:
        assert ("num", 0, max(0, speed - moves)) in g.calls


def test_long_range_fire_marks_its_call(build):
    g = Game(build)
    atk = g.veh(5, 5, 1, U_ARTY)
    g.dll(g_askHasty=7)
    r = g.call("WrapArtyFight", atk, 2, 0, 0, 0)
    (_, _args, at) = _fought(g)[0]
    assert r == 1 and at["ask"] == 1 and g.get("g_askHasty") == 7


# ---- fix 1: the combat reveal (CombatReveal) ------------------------------------------------------------------------

@pytest.mark.parametrize("core_ok", [1, 0])
@pytest.mark.parametrize("reveal_ok", [1, 0])
@pytest.mark.parametrize("net", NETS)
@pytest.mark.parametrize("local", [1, 0])
@pytest.mark.parametrize("hidden", ["hidden", "visible_kind", "in_base"])
def test_combat_reveal(build, net, local, hidden, reveal_ok, core_ok):
    g = Game(build)
    n = NETS[net]
    if n is not None:
        g.net(n)
    g.dll(g_local=local, g_revealOk=reveal_ok, g_coreOk=core_ok)
    mate = g.veh(5, 5, 2, U_CLOAK_ARTY)                  # the stack's top
    atk = g.veh(5, 5, 2, U_ARTY if hidden == "visible_kind" else U_CLOAK_ARTY)   # the attacker is not the top
    if hidden == "in_base":
        g.base_at(5, 5)
    g.call("CombatReveal", atk, 1)
    is_hidden = hidden == "hidden"
    if not rule(5, local != 0, bool(reveal_ok), n):
        want = (0, 0)
    elif n is None:
        want = (2, 2) if is_hidden else (0, 0)
    else:
        cloak = core_ok and rule(0, False, True, n)
        want = (2, 2 if is_hidden and cloak else 0)       # every machine marks the attacker; the stack with bit 0
    assert (g.vis(atk), g.vis(mate)) == want


def test_combat_reveal_ignores_own_faction_and_bad_ids(build):
    g = Game(build)
    atk = g.veh(5, 5, 1, U_CLOAK_ARTY)
    g.call("CombatReveal", atk, 1)
    g.call("CombatReveal", atk, 8)
    g.call("CombatReveal", atk, -1)
    g.call("CombatReveal", 99, 2)
    g.call("CombatReveal", -1, 2)
    assert g.vis(atk) == 0


# ---- the carrier and the session reset -----------------------------------------------------------------------------

@pytest.mark.parametrize("local", [1, 0])
@pytest.mark.parametrize("groups", list(itertools.product([0, 1], repeat=4)))
def test_upkeep_send_advertises_installed_groups_and_latches(build, groups, local):
    g = Game(build)
    reveal, bomb, duel, ask = groups
    g.dll(g_revealOk=reveal, g_bombardOk=bomb, g_duelOk=duel, g_askOk=ask, g_local=local)
    g.net(dict(server=1))
    g.call("WrapUpkeepSend", 0x4303, 0, 0, 0, 0, 0)
    (msg,) = g.named("message_data")
    mask = msg[5]
    assert msg[6] == 0x4C4D0001
    assert bool(mask & 1 << 5) == bool(reveal), "bit 5 whenever installed (not parent-gated)"
    assert bool(mask & 1 << 6) == bool(bomb and local and reveal), "bit 6 rides the cloak setting and needs the reveal group"
    assert bool(mask & 1 << 7) == bool(bomb) and bool(mask & 1 << 8) == bool(duel)
    assert bool(mask & 1) == bool(local)
    assert g.get("g_hostSent") == mask and g.get("g_hostSentValid") == 1


def test_upkeep_send_on_a_client_passes_through(build):
    g = Game(build)
    g.net(dict(server=0, mask=0x1F))
    g.call("WrapUpkeepSend", 0x4303, 0, 1, 2, 3, 4)
    assert g.named("message_data") == [("message_data", 0x4303, 0, 1, 2, 3, 4)]
    assert g.get("g_hostSentValid") == 0


def test_other_messages_pass_through_on_the_host(build):
    g = Game(build)
    g.net(dict(server=1))
    g.call("WrapUpkeepSend", 0x4304, 0, 1, 2, 3, 4)
    assert g.named("message_data") == [("message_data", 0x4304, 0, 1, 2, 3, 4)]
    assert g.get("g_hostSentValid") == 0


def test_host_rules_follow_the_broadcast_not_the_checkbox(build):
    g = Game(build)
    g.net(dict(server=1))
    g.humans(3)
    actor = g.veh(5, 5, 1, U_ARTY)
    stack = g.veh(7, 5, 2, U_CLOAK_ARTY)
    g.war(1, 2)
    assert g.call("BombardStackCheck", stack, 15, -1, -1, -1, actor) == 7, "before the first broadcast: vanilla"
    g.call("WrapUpkeepSend", 0x4303, 0, 0, 0, 0, 0)
    assert g.call("BombardStackCheck", stack, 15, -1, -1, -1, actor) == 0, "after it: the AI scan skips"
    g.dll(g_local=0)                  # the host turns the cloak setting off mid-turn
    assert g.call("BombardStackCheck", stack, 15, -1, -1, -1, actor) == 0, "still the broadcast mask"
    g.call("WrapUpkeepSend", 0x4303, 0, 0, 0, 0, 0)
    assert g.call("BombardStackCheck", stack, 15, -1, -1, -1, actor) == 7, "the next broadcast switches it off"


@pytest.mark.parametrize("ret,resets", [(0x51BC14, True), (0x51AD08, True), (0x51C5D9, False), (0x515441, False)])
def test_game_start_resets_the_masks(build, ret, resets):
    g = Game(build)
    g.net(dict(server=0, mask=ALL, sent=ALL))
    g.call("AiVisOnGameStart", ret)
    assert (g.get("g_netValid") == 0) is resets and (g.get("g_hostSentValid") == 0) is resets
    assert (g.get("g_netMask") == 0) is resets


def test_single_player_forgets_a_network_mask(build):
    g = Game(build)
    g.dll(g_netValid=1, g_netMask=ALL, g_hostSentValid=1, g_hostSent=ALL)
    actor = g.veh(5, 5, 1, U_ARTY)
    stack = g.veh(7, 5, 2, U_ARTY)
    g.war(1, 2)
    g.call("BombardStackCheck", stack, 15, -1, -1, -1, actor)
    assert g.get("g_netValid") == 0 and g.get("g_hostSentValid") == 0 and g.get("g_netMask") == 0


# ---- delta audit 2026-11-15: each of these kills a code mutant the cases above let through ---------------------------

def test_scan_walks_a_deep_stack_to_its_top(build):
    """The deciding unit (at-war artillery) is the top of a four-unit stack passed by its last unit."""
    units = [(2, U_ARTY, False), (3, U_PLAIN, False), (3, U_PLAIN, False), (3, U_PLAIN, False)]
    _scan(build, units, owner=2, passed=3)


def test_scan_hidden_rule_walks_to_the_top(build):
    """A seen top makes the stack visible even when an unseen cloaked unit below it is the one passed."""
    _scan(build, [(2, U_CLOAK_ARTY, True), (2, U_CLOAK_ARTY, False)], owner=-1, passed=1)


def test_scan_native_firer_skips_native_artillery(build):
    _scan(build, [(0, U_ARTY, False)], owner=-1, firer="native")


def test_thinker_scan_passes_the_territory_owner(build):
    """BombardStackCheckT hands a3 (the territory owner), not a4, to the skip."""
    g = Game(build)
    _world(g, "war")
    g.w32(g.tsyms["g_modStackCheck"], F_STACK_CHECK)
    actor = g.veh(5, 5, 1, U_ARTY)
    partner = g.veh(7, 5, 5, U_ARTY)          # treaty partner's artillery in its own territory: skipped
    assert g.call("BombardStackCheckT", partner, 15, 5, 2, -1, actor, thinker=True) == 0
    enemy = g.veh(9, 5, 2, U_ARTY)            # at war, owner 2 (a4 names the treaty partner): Thinker's answer
    assert g.call("BombardStackCheckT", enemy, 15, 2, 5, -1, actor, thinker=True) == 7
    assert g.named("stack_check") == [("stack_check", enemy, 15, 2, 5, -1)]


def test_second_duel_without_a_new_record_blocks(build):
    g, actor = _duel(build)
    assert g.call("WrapBombardDuel", actor, 2, 0, 0, 0) == 1 and len(_fought(g)) == 1
    g.calls.clear()
    assert g.call("WrapBombardDuel", actor, 2, 0, 0, 0) == 0 and not _fought(g), "the record is one-shot"


def test_host_ignores_a_stale_mask_until_it_broadcasts(build):
    """After a game start the host's latch is invalid; the old mask's bits must not apply."""
    g = Game(build)
    _world(g, "treaty")
    g.net(dict(server=1))
    g.dll(g_hostSent=ALL)                     # stale bits left by an earlier session
    actor = g.veh(5, 5, 1, U_ARTY)
    peaceful = g.veh(7, 5, 2, U_ARTY)
    assert g.call("BombardStackCheck", peaceful, 15, -1, -1, -1, actor) == 7, "vanilla until the first broadcast"
