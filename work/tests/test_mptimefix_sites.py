"""uimod's multiplayer time-widget fix (src/uimod/src/mptimefix.cpp) against the pristine exe.

MultiWin_draw_time 0x478BE0 writes its blink local [ebp-0x10] and its "timer was running" local [ebp-0xC] only on
tick paths ([ebp-0xC] not even on the hold tick); the redraw path (tick == 0) reads stack garbage -> "No Time Control" flashed black. The DLL detours
the prologue's `sub esp,0x60; mov edx,[ebp+8]` to a stub that seeds both locals. These tests pin:
  - every byte array the source checks is the pristine one;
  - the two locals are written ONLY at the tick-path sites the source names (so a tick still draws exactly as
    before) and read only where the source says;
  - the hold condition the stub reproduces is exactly the tick path's branch into the hold write;
  - the code after the resume sets EFLAGS before reading them and writes eax before reading it;
  - the DLL installs the fix.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pefile  # noqa: E402
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402

import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
FIX = (SRC_DIR / "mptimefix.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")
PROJ = (ROOT.parent / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")

FN, FN_END = 0x478BE0, 0x479269        # ret 8 at 0x479266


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


@pytest.fixture(scope="module")
def insns(pe):
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    code = pe.get_data(FN - pe.OPTIONAL_HEADER.ImageBase, FN_END - FN)
    return list(md.disasm(code, FN))


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def cpp_va(name):
    return int(re.search(name + r"\s*=\s*0x([0-9A-Fa-f]+);", FIX).group(1), 16)


def cpp_bytes(name):
    m = re.search(name + r"\[\d+\]\s*=\s*\{([^}]*)\}", FIX)
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


PAIRS = {"kExpectEntry": "kVA_DrawTime", "kExpectSkip": "kVA_TickSkip", "kExpectHold": "kVA_HoldTest",
         "kExpectHoldWrite": "kVA_HoldWrite", "kExpectColour": "kVA_ColourRead"}


@pytest.mark.parametrize("arr", sorted(PAIRS))
def test_expected_bytes_are_pristine(pe, arr):
    b = cpp_bytes(arr)
    assert len(b) == int(re.search(arr + r"\[(\d+)\]", FIX).group(1))
    assert rd(pe, cpp_va(PAIRS[arr]), len(b)) == b


def test_site_is_the_prologue_pair(pe, insns):
    site, resume = cpp_va("kVA_Site"), cpp_va("kVA_Resume")
    assert cpp_va("kVA_DrawTime") == FN
    by = {i.address: i for i in insns}
    assert f"{by[site].mnemonic} {by[site].op_str}" == "sub esp, 0x60"
    nxt = by[site + by[site].size]
    assert f"{nxt.mnemonic} {nxt.op_str}" == "mov edx, dword ptr [ebp + 8]"
    assert nxt.address + nxt.size == resume
    assert resume - site == int(re.search(r"kSiteLen\s*=\s*(\d+);", FIX).group(1)) >= 5


def test_locals_written_only_on_the_tick_path(insns):
    """Every write of the two locals is on a tick path, so the stub's seed is overwritten whenever tick != 0."""
    writes = {}
    for i in insns:
        for loc in ("ebp - 0x10", "ebp - 0xc"):
            if i.mnemonic == "mov" and i.op_str.startswith(f"dword ptr [{loc}],"):
                writes.setdefault(loc, []).append(i.address)
    assert writes == {"ebp - 0x10": [0x478C6E, 0x478C97, 0x478CB9], "ebp - 0xc": [0x478C7D, 0x478CA6]}
    # ... and all of them lie between the tick test's fall-through (0x478C3A) and its je target (0x478CC8).
    assert all(0x478C3A <= a < 0x478CC8 for v in writes.values() for a in v)
    reads = sorted(i.address for i in insns if i.mnemonic in ("mov", "cmp", "test")
                   and re.search(r", dword ptr \[ebp - 0x(10|c)\]$", i.op_str))
    assert reads == [0x478E11, 0x479008, 0x479206]


def test_hold_condition_matches_the_tick_branch(insns):
    """The hold write at 0x478CB9 is reached from the three jne's on 0x93F664 / 0x93E8E0 / 0x93F668 (edi = 0)."""
    by = {i.address: i for i in insns}
    assert f"{by[0x478C01].mnemonic} {by[0x478C01].op_str}" == "xor edi, edi"
    jumps = [i for i in insns if i.mnemonic == "jne" and i.op_str == "0x478cb7"]
    assert [j.address for j in jumps] == [0x478C53, 0x478C5B, 0x478C5F]
    for g in ("0x93f664", "0x93e8e0", "0x93f668"):
        assert any(g in i.op_str for i in insns if 0x478C3A <= i.address < 0x478C61)
        assert "0x" + g[2:].upper() in FIX
    assert "0x93F664" in FIX and "0x93E8E0" in FIX and "0x93F668" in FIX


def test_resume_tail_sets_flags_and_eax_before_reading_them(insns):
    tail = [i for i in insns if cpp_va("kVA_Resume") <= i.address < 0x478C0C]
    eax_written = False
    for i in tail:
        if i.mnemonic.startswith("j") or i.mnemonic in ("adc", "sbb", "cmovz", "setg", "setl"):
            pytest.fail(f"flag read at {i.address:#x} before a flag write")
        if i.mnemonic in ("sub", "xor", "cmp", "test", "add"):
            break
        if "eax" in i.op_str.split(",", 1)[-1] and not eax_written:
            pytest.fail(f"eax read at {i.address:#x} before it is written")
        if i.op_str.startswith("eax,"):
            eax_written = True
    else:
        pytest.fail("no flag-setting instruction after the resume")


def test_hold_path_leaves_running_unwritten(insns):
    """The hold tick (0x478CB7..0x478CC8) writes the blink only: vanilla read stack garbage for [ebp-0xC] there too,
    so the seed (0: a held tick counts nothing down) is a deliberate change on that path."""
    assert not [i for i in insns if 0x478CB7 <= i.address < 0x478CC8 and "[ebp - 0xc]" in i.op_str]
    for va in ("0x93F664", "0x93E8E0", "0x93F668"):
        assert re.search(r"g_hold\d = reinterpret_cast<const int\*>\(At\(" + va + r"\)\);", FIX), va


DLL = ROOT.parent / "src" / "uimod" / "build" / "Release" / "uimod.dll"


@pytest.fixture(scope="module")
def stub():
    """The built DLL's StubTimeLocals: found by its first 17 bytes; its three hold pointers and resume cell read
    from its own operands (the image at its preferred base, relocations already applied there)."""
    if not DLL.exists():
        pytest.skip("uimod.dll not built")
    dpe = pefile.PE(str(DLL))
    img = dpe.get_memory_mapped_image()
    base = dpe.OPTIONAL_HEADER.ImageBase
    off = img.find(bytes.fromhex("83EC60C745F400000000C745F000000000"))
    assert off > 0 and img.count(bytes.fromhex("83EC60C745F400000000C745F000000000")) == 1
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    cells, jmp = [], None
    for i in md.disasm(img[off:off + 0x80], base + off):
        m = re.fullmatch(r"eax, dword ptr \[(0x[0-9a-f]+)\]", i.op_str)
        if i.mnemonic == "mov" and m:
            cells.append(int(m.group(1), 16))
        if i.mnemonic == "jmp" and i.op_str.startswith("dword ptr ["):
            jmp = int(i.op_str[11:-1], 16)
            break
    assert len(cells) == 3 and jmp
    return img, base, base + off, cells, jmp


@pytest.mark.parametrize("hold", [(a, b, c) for a in (0, 1, 0x80000000) for b in (0, 1, 0x80000000)
                                  for c in (0, 1, 0x80000000)])
def test_stub_seeds_the_locals_and_keeps_the_frame(stub, hold):
    """Under Unicorn: the stub resumes at 0x478BE9 with esp = ebp - 0x60, edx = [ebp+8], every other register kept,
    [ebp-0xC] = 0, [ebp-0x10] = any hold nonzero, the neighbouring locals untouched."""
    import struct
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn import x86_const as X
    img, base, entry, cells, jmp = stub
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(base, (len(img) + 0xFFF) & ~0xFFF)
    mu.mem_write(base, img)
    mu.mem_map(0x400000, 0x600000)
    mu.mem_map(0x100000, 0x10000)
    for cell, va, v in zip(cells, (0x93F664, 0x93E8E0, 0x93F668), hold):
        mu.mem_write(cell, struct.pack("<I", 0x400000 + (va - 0x400000)))
        mu.mem_write(va, struct.pack("<I", v))
    mu.mem_write(jmp, struct.pack("<I", 0x478BE9))
    ebp = 0x108000
    mu.mem_write(ebp - 0x80, b"\xAA" * 0x80)
    mu.mem_write(ebp + 8, struct.pack("<I", 0x12345678))
    regs = {X.UC_X86_REG_EAX: 0x1111, X.UC_X86_REG_EBX: 0x2222, X.UC_X86_REG_ECX: 0x3333, X.UC_X86_REG_EDX: 0x4444,
            X.UC_X86_REG_ESI: 0x5555, X.UC_X86_REG_EDI: 0x6666, X.UC_X86_REG_EBP: ebp, X.UC_X86_REG_ESP: ebp}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.emu_start(entry, 0x478BE9, count=100)
    rd = lambda a: struct.unpack("<I", mu.mem_read(a, 4))[0]  # noqa: E731
    assert mu.reg_read(X.UC_X86_REG_EIP) == 0x478BE9
    assert mu.reg_read(X.UC_X86_REG_ESP) == ebp - 0x60
    assert mu.reg_read(X.UC_X86_REG_EDX) == 0x12345678
    for r in (X.UC_X86_REG_EAX, X.UC_X86_REG_EBX, X.UC_X86_REG_ECX, X.UC_X86_REG_ESI, X.UC_X86_REG_EDI,
              X.UC_X86_REG_EBP):
        assert mu.reg_read(r) == regs[r]
    assert rd(ebp - 0xC) == 0 and rd(ebp - 0x10) == (1 if any(hold) else 0)
    assert rd(ebp - 4) == rd(ebp - 8) == rd(ebp - 0x14) == 0xAAAAAAAA


def test_dll_installs_the_fix():
    assert "InstallMpTimeFix();" in INIT
    assert '#include "mptimefix.h"' in INIT
    assert r'<ClCompile Include="src\mptimefix.cpp" />' in PROJ
