"""Unicorn run of the base game's drone-riot DEFECTION block (drone_riot 0x4F5553..0x4F565C, pristine bytes)
with and without uimod's riotfix (src\\uimod\\src\\riotfix.cpp): weights initialised to -1 by a site detour
on the block's first instruction + `jl` -> `jg` at 0x4F561D.

Vanilla: the seven weight slots [ebp-0x58..-0x40] are stack garbage for every faction without REVOLT, and
with no REVOLT faction the weighted pick divides by zero.  Fixed: no REVOLT faction -> the pick (and its
idiv) is unreachable for every roll; REVOLT 75 -> the pick runs for r >= 25 (75 of 100 rolls).
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pefile  # noqa: E402
pytest.importorskip("unicorn", reason="unicorn absent -- asm parity unverified")
from keystone import Ks, KS_ARCH_X86, KS_MODE_32  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc, UcError  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ESP  # noqa: E402

import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

START, IDIV, JOIN = 0x4F5553, 0x4F5633, 0x4F565C
IAT_TIME, TIME_STUB, STUB = 0x669368, 0x00300000, 0x00310000
COUNT0, ID0, VAL0, STRIDE = 0x9474F8, 0x946F60 + 0x167 * 4, 0x946F80 + 0x167 * 4, 0x59C
STACK = 0x00200000
KS = Ks(KS_ARCH_X86, KS_MODE_32)
SRC = (ROOT.parent / "src" / "uimod" / "src" / "riotfix.cpp").read_text(encoding="utf-8")


def test_port_carries_the_sites_and_bytes():
    assert "kVA_WeightsInit = 0x4F5553" in SRC and "kVA_RollBranch  = 0x4F561B" in SRC
    assert "{ 0xDD, 0x05, 0xD8, 0xD8, 0x66, 0x00 }" in SRC and "{ 0x3B, 0xCA, 0x7C, 0x3D }" in SRC
    assert "b[2] = 0x7F" in SRC
    assert "kVA_ClockCall   = 0x4F55F9" in SRC and "{ 0xFF, 0x15, 0x68, 0x93, 0x66, 0x00 }" in SRC
    assert "kVA_Rand        = 0x64601D" in SRC and "return roll + 100 * rnd();" in SRC
    assert "const int roll = rnd() % 100;" in SRC
    slots = re.findall(r"mov\s+dword ptr \[ebp - (0x[0-9A-Fa-f]+)\], -1", SRC)
    assert [int(s, 16) for s in slots] == [0x58, 0x54, 0x50, 0x4C, 0x48, 0x44, 0x40]


def mk(fixed: bool, revolt: dict, clock: int, garbage: int):
    pe = pefile.PE(str(BAK), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for s in pe.sections:
        va = base + s.VirtualAddress
        size = (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF
        uc.mem_map(va, size)
        uc.mem_write(va, s.get_data())
    for b in (STACK, TIME_STUB, STUB):
        uc.mem_map(b, 0x10000)
    uc.mem_write(IAT_TIME, struct.pack("<I", TIME_STUB))
    uc.mem_write(TIME_STUB, bytes(KS.asm(f"mov eax, {clock}; ret", TIME_STUB)[0]))
    for f in range(7):                                        # faction slots 1..7: one bonus each
        fid = f + 1
        uc.mem_write(COUNT0 + f * STRIDE, struct.pack("<i", 1))
        uc.mem_write(ID0 + f * STRIDE, struct.pack("<i", 13 if fid in revolt else 2))
        uc.mem_write(VAL0 + f * STRIDE, struct.pack("<i", revolt.get(fid, 5)))
    ebp = STACK + 0x8000
    for off in range(0x58, 0x3C, -4):
        uc.mem_write(ebp - off, struct.pack("<i", garbage))   # what earlier calls left behind
    uc.mem_write(ebp - 8, struct.pack("<i", 3))               # default target: nearest foreign faction
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_ESP, ebp - 0x100)
    if fixed:
        stub = "".join(f"mov dword ptr [ebp - {o:#x}], -1;" for o in range(0x58, 0x3C, -4))
        stub += f"fld qword ptr [0x66D8D8]; jmp {START + 6:#x}"
        uc.mem_write(STUB, bytes(KS.asm(stub, STUB)[0]))
        uc.mem_write(START, bytes(KS.asm(f"jmp {STUB:#x}", START)[0]) + b"\x90")
        uc.mem_write(0x4F561D, b"\x7F")
        # RiotRoll() stands in for timeGetTime(): the emulated stand-in returns the same composed value
        uc.mem_write(0x4F55F9, bytes(KS.asm(f"call {TIME_STUB:#x}", 0x4F55F9)[0]) + b"\x90")
    return uc, ebp


def run(uc):
    try:
        uc.emu_start(START, JOIN, count=100_000)
    except UcError as e:
        return "fault", str(e)
    return "ok", None


def test_vanilla_divides_by_zero_on_garbage_weights():
    """No REVOLT faction, garbage weights 0 (P = 100 >= every roll): the pristine block reaches idiv 0."""
    uc, _ = mk(False, {}, clock=123456, garbage=0)
    state, _ = run(uc)
    assert state == "fault"


@pytest.mark.parametrize("garbage", [0, -1, 50, 300, -7777, 0x7FFFFFFF])
@pytest.mark.parametrize("roll", [0, 1, 24, 25, 50, 99])
def test_fixed_no_revolt_faction_never_picks(garbage, roll):
    uc, ebp = mk(True, {}, clock=987600 + roll, garbage=garbage)
    assert run(uc) == ("ok", None)
    assert struct.unpack("<i", uc.mem_read(ebp - 8, 4))[0] == 3          # default target kept


def test_fixed_revolt_75_is_about_75_percent():
    """REVOLT 75: the weighted pick runs for r >= P, P = ftol(100 * (1 - 75 * 0.01)).  0.01 is inexact, so the
    truncating ftol lands on 24 or 25 depending on the x87 precision mode: 75 or 76 rolls of 100."""
    picks = []
    for roll in range(100):
        uc, ebp = mk(True, {6: 75}, clock=555500 + roll, garbage=300)
        assert run(uc) == ("ok", None)
        picks.append(struct.unpack("<i", uc.mem_read(ebp - 8, 4))[0])
    first = picks.index(6)
    assert first in (24, 25)
    assert picks == [3] * first + [6] * (100 - first)          # one threshold, default target below it


def test_vanilla_negative_clock_always_picks():
    """Pristine: timeGetTime() past 0x7FFFFFFF (24.8 days of uptime) is read signed -> roll in -99..0 <= P,
    so the inverted test ALWAYS takes the weighted pick: REVOLT factions always win, and with no REVOLT
    faction every defection divides by zero.  RiotRoll() is >= 0 by construction."""
    uc, ebp = mk(False, {6: 75}, clock=0x90000000 + 50, garbage=-1)
    assert run(uc) == ("ok", None)
    assert struct.unpack("<i", uc.mem_read(ebp - 8, 4))[0] == 6
    uc, _ = mk(False, {}, clock=0x90000000 + 50, garbage=-1)
    assert run(uc)[0] == "fault"


@pytest.mark.parametrize("pick_rand,expect", [(0, 2), (39, 2), (40, 6), (99, 6), (100, 2), (32767, 6)])
def test_fixed_weighted_pick_uses_the_second_draw(pick_rand, expect):
    """Two REVOLT factions (2: 40, 6: 60, sum 100): RiotRoll() = roll + 100 * rand(), so the engine's
    (t / 100) % sum is rand() % sum -> faction 2 for 0..39, faction 6 for 40..99.  Roll 99 always picks."""
    uc, ebp = mk(True, {2: 40, 6: 60}, clock=99 + 100 * pick_rand, garbage=12345)
    assert run(uc) == ("ok", None)
    assert struct.unpack("<i", uc.mem_read(ebp - 8, 4))[0] == expect
