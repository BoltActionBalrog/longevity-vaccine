"""Unicorn parity for the tech_scale thunks (assemble_tech.py).

Oracle = scaling_laws.tech_* (immediates, inset, strip, font-cell law).  Every thunk is
emulated from its REAL assembled bytes at its REAL cave VA over the REAL base-exe text of
the cluster; Font_init / find_font / the kernel32 IAT are tiny stubs that record their calls
(Font_init cell model: cell = size + 2; pool cell model: S + 4), TechWin_exec /
Buffer_box_sprite / devfill are landing pads (emulation stops on arrival).
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
pytest.importorskip("pefile")

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_tech as AT  # noqa: E402

LAYOUT, _END = AT.assemble_all()
VA = {n: AT.PCAVE2 + LAYOUT[n][0] for n in LAYOUT}
R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
     "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}
STACK, SP0 = 0x00300000, 0x00308000
RET_SITE = 0x00600100
TEXT_LO, TEXT_HI = 0x484000, 0x488000
LOG = 0x00700000          # Font_init call log: name, size, flags, this, count
LL_STUB, GP_STUB, VP_STUB = 0x00700100, 0x00700120, 0x00700140
POOL = 0x00710000         # find_font fake pool: entry S*0x40
NAME_A, NAME_N = 0x00720000, 0x00720100
VARIANT_FLAGS = [0, 1, 2, 4]
_ks = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(src, va=0):
    enc, _ = _ks.asm(src, va)
    return bytes(enc)


FONT_INIT_STUB = asm(
    f"mov eax, dword ptr [esp+8]; add eax, 2; mov dword ptr [ecx+0xC], eax;"
    f"mov eax, dword ptr [esp+4]; mov dword ptr [{LOG:#x}], eax;"
    f"mov eax, dword ptr [esp+8]; mov dword ptr [{LOG + 4:#x}], eax;"
    f"mov eax, dword ptr [esp+0xC]; mov dword ptr [{LOG + 8:#x}], eax;"
    f"mov dword ptr [{LOG + 12:#x}], ecx; inc dword ptr [{LOG + 16:#x}]; ret 0xC")
FIND_FONT_STUB = asm(f"mov eax, dword ptr [esp+4]; shl eax, 6; add eax, {POOL:#x}; ret")
IAT_STUBS = {LL_STUB: asm("mov eax, 1; ret 4"), GP_STUB: asm(f"mov eax, {VP_STUB:#x}; ret 8"),
             VP_STUB: asm("mov eax, 1; ret 0x10")}
LANDINGS = [AT.EXEC, AT.BOX_SPRITE, AT.DEVFILL, RET_SITE]

_BASE_TEXT = None


def base_text():
    global _BASE_TEXT
    if _BASE_TEXT is None:
        _BASE_TEXT = AT.SE.base_exe_bytes(TEXT_LO, TEXT_HI - TEXT_LO)
    return _BASE_TEXT


class Emu:
    def __init__(self, g):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        for base, size in ((AT.PCAVE2, 0x1A000), (STACK, 0x10000), (TEXT_LO, TEXT_HI - TEXT_LO),
                           (0x668000, 0x2000), (0x68F000, 0x1000), (0x691000, 0x1000), (0x5BE000, 0x1000),
                           (0x618000, 0x1000), (0x588000, 0x1000), (0x5E2000, 0x1000), (0x600000, 0x1000),
                           (0x700000, 0x1000), (POOL, 0x1000), (0x720000, 0x1000)):
            uc.mem_map(base, size)
        for name, (off, blob) in LAYOUT.items():
            uc.mem_write(AT.PCAVE2 + off, blob)
        uc.mem_write(TEXT_LO, base_text())
        self.set_g(g)
        uc.mem_write(AT.FONT_INIT, FONT_INIT_STUB)
        uc.mem_write(AT.FIND_FONT, FIND_FONT_STUB)
        for a, b in IAT_STUBS.items():
            uc.mem_write(a, b)
        self.w32(AT.IAT_LOADLIB, LL_STUB)
        self.w32(AT.IAT_GETPROC, GP_STUB)
        for i, f in enumerate(VARIANT_FLAGS):
            self.w32(AT.VARIANT_FLAGS + 4 * i, f)
        self.w32(AT.FONT_NAME, NAME_A)
        self.w32(AT.FONT_NAME_NR, NAME_N)
        for S in (10, 12, 14, 18, 20):
            self.w32(POOL + S * 0x40 + 0xC, S + 4)       # pool cell model
        for a in LANDINGS:
            uc.mem_write(a, b"\xf4")
        self.stopped_at = None
        uc.hook_add(UC_HOOK_CODE, self._hook)

    def set_g(self, g):
        self.uc.mem_write(AT.G, g.to_bytes(4, "little", signed=True))

    def _hook(self, uc, addr, size, ud):
        if addr in LANDINGS:
            self.stopped_at = addr
            uc.emu_stop()

    def w32(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "little", signed=True)

    def r8(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 1), "little", signed=True)

    def run(self, va, regs=None, stack=None, eflags=0x202):
        uc = self.uc
        stack = list(stack or [RET_SITE])
        for i, v in enumerate(stack):
            self.w32(SP0 + 4 * i, v)
        uc.reg_write(UC_X86_REG_ESP, SP0)
        uc.reg_write(UC_X86_REG_EFLAGS, eflags)
        for k, v in (regs or {}).items():
            uc.reg_write(R[k], v & 0xFFFFFFFF)
        self.stopped_at = None
        uc.emu_start(va, 0, count=5_000_000)
        return self.stopped_at

    def reg(self, k):
        return self.uc.reg_read(R[k])

    def log(self):
        return {"name": self.r32(LOG), "size": self.r32(LOG + 4), "flags": self.r32(LOG + 8),
                "this": self.r32(LOG + 12) & 0xFFFFFFFF, "count": self.r32(LOG + 16)}

    def clear_log(self):
        self.uc.mem_write(LOG, b"\x00" * 20)


GS = [16, 17, 20, 22, 25, 30, 40]


# ---- immfix -------------------------------------------------------------------------------

def imm_read(emu, site_off, kind):
    return emu.r32(site_off) if kind & AT.KIND_DWORD else emu.r8(site_off)


@pytest.mark.parametrize("g", GS)
def test_enter_immfix_writes_every_law_value_and_lands_at_exec(g):
    emu = Emu(g)
    for site, _a, _b, kind in AT.immtab_entries():
        assert imm_read(emu, site, kind) == AT.imm_native(site)          # base exe = native
    where = emu.run(VA["thunk_tech_enter"], regs={"ecx": 0x1A824C, "edx": 0x77}, stack=[RET_SITE, 5, 0])
    assert where == AT.EXEC
    assert emu.reg("ecx") == 0x1A824C and emu.reg("edx") == 0x77            # thiscall this + args untouched
    assert emu.r32(SP0) == RET_SITE and emu.r32(SP0 + 4) == 5                # stack as the caller left it
    assert emu.r32(AT.G_VPDONE) == 1
    for site, _a, _b, kind in AT.immtab_entries():
        assert imm_read(emu, site, kind) == AT.imm_value(site, g), f"imm @{site:#x} g={g}"
    # the laws the table encodes
    assert AT.imm_value(0x487DBD + 2, g) == SL.tech_strip_h_imm(g)
    assert AT.imm_value(0x487358 + 1, g) == SL.tech_imm(10, g)
    im = SL.tech_icon_imms(g)
    assert AT.imm_value(0x4850E4 + 1, g) == im["s10"] and AT.imm_value(0x485140 + 6, g) == im["den"]
    assert AT.imm_value(0x4850F6 + 2, g) == im["mask"] and AT.imm_value(0x4850F9 + 2, g) == im["add"]
    assert AT.imm_value(0x485183 + 2, g) == im["shift"]
    for site, _a, _b, kind in AT.immtab_entries():
        if not kind & AT.KIND_DWORD:
            assert -128 <= AT.imm_value(site, g) <= 127


def test_immfix_is_idempotent_and_restores_native_on_a_g_downgrade():
    emu = Emu(40)
    emu.run(VA["thunk_tech_enter"], regs={"ecx": 1}, stack=[RET_SITE])
    emu.run(VA["thunk_tech_enter"], regs={"ecx": 1}, stack=[RET_SITE])
    for site, _a, _b, kind in AT.immtab_entries():
        assert imm_read(emu, site, kind) == AT.imm_value(site, 40)
    emu.set_g(16)
    emu.run(VA["thunk_tech_enter"], regs={"ecx": 1}, stack=[RET_SITE])
    for site, _a, _b, kind in AT.immtab_entries():
        assert imm_read(emu, site, kind) == AT.imm_native(site), f"native not restored @{site:#x}"


def test_immfix_bails_when_virtualprotect_fails():
    emu = Emu(40)
    emu.uc.mem_write(VP_STUB, asm("xor eax, eax; ret 0x10"))
    where = emu.run(VA["thunk_tech_enter"], regs={"ecx": 1}, stack=[RET_SITE])
    assert where == AT.EXEC and emu.r32(AT.G_VPDONE) == 0
    for site, _a, _b, kind in AT.immtab_entries():
        assert imm_read(emu, site, kind) == AT.imm_native(site)


# ---- cuts -----------------------------------------------------------------------------------

@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("L", [1, 3, 7, 9, 100])
def test_inset_cut(g, L):
    emu = Emu(g)
    R0, B0 = 913 + 910, 75 + 980
    where = emu.run(VA["thunk_tech_inset"], regs={"ebx": R0, "edx": B0, "ecx": L}, stack=[RET_SITE])
    assert where == RET_SITE
    c_rb, c_l = SL.tech_cell_inset_rb(g), SL.scale_px(3, g)
    assert emu.reg("ebx") == R0 - c_rb and emu.reg("edx") == B0 - c_rb and emu.reg("eax") == c_l
    fl = emu.uc.reg_read(UC_X86_REG_EFLAGS)
    zf, sf, of = (fl >> 6) & 1, (fl >> 7) & 1, (fl >> 11) & 1
    assert (zf == 0 and sf == of) == (L > c_l)                              # the caller's jg
    if g == 16:
        assert c_rb == 3 and c_l == 3                                       # vanilla verbatim


def test_n8_cut():
    emu = Emu(40)
    emu.w32(SP0 + 0x100 + 8, 0)
    where = emu.run(VA["thunk_tech_n8"], regs={"ebp": SP0 + 0x100, "edi": 25, "esi": 0}, stack=[RET_SITE])
    assert where == RET_SITE and emu.reg("esi") == 10 and emu.r32(SP0 + 0x100 + 8) == 12


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("sh,rows", [(768, 2), (1200, 3), (2160, 2), (1080, 4)])
def test_n8_overflow_cut(g, sh, rows):
    emu = Emu(g)
    where = emu.run(VA["thunk_tech_n8ch"], regs={"eax": sh, "ecx": rows, "ebx": 0x55}, stack=[RET_SITE])
    assert where == RET_SITE
    assert emu.reg("eax") == (sh - SL.scale_px(0x45, g)) // rows
    assert emu.reg("ecx") == rows and emu.reg("ebx") == 0x55


# ---- rb1 ------------------------------------------------------------------------------------

@pytest.mark.parametrize("g", GS)
def test_rb1(g):
    emu = Emu(g)
    rect = SP0 + 0x200
    for i, v in enumerate((912, 75, 1813, 1046)):
        emu.w32(rect + 4 * i, v)
    where = emu.run(VA["thunk_tech_rb1"], regs={"ecx": 0x1A8690, "eax": 0xAA, "edx": 0xBB}, stack=[RET_SITE, rect, 0x78D528])
    assert emu.reg("ecx") == 0x1A8690 and emu.reg("eax") == 0xAA and emu.reg("edx") == 0xBB
    assert emu.r32(SP0) == RET_SITE and emu.r32(SP0 + 8) == 0x78D528
    assert [emu.r32(rect + 4 * i) for i in range(4)] == [912, 75, 1813, 1046]     # caller's rect untouched
    if g <= 16:
        assert where == AT.BOX_SPRITE and emu.r32(SP0 + 4) == rect
    else:
        assert where == AT.DEVFILL and emu.r32(SP0 + 4) == AT.G_RBRECT
        assert [emu.r32(AT.G_RBRECT + 4 * i) for i in range(4)] == [912, 75, 1812, 1045]


# ---- fonts ------------------------------------------------------------------------------------

def expect_n(c0, S, g):
    """The calibration law with the stub's cell model cell(n) = n + 2."""
    target = SL.tech_font_cell(c0, g)
    start, stop = max(S, SL.scale_px(S, g) - 8), SL.scale_px(S, g) + 16
    for n in range(start, stop + 1):
        if n + 2 >= target:
            return n
    return SL.scale_px(S, g)


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("S,flags", [(14, 0), (14, 1), (14, 2), (18, 1), (10, 0), (12, 1)])
def test_fi_rewrites_the_size_to_the_cell_calibrated_nominal(g, S, flags):
    emu = Emu(g)
    this = 0x720800
    emu.clear_log()
    where = emu.run(VA["thunk_tech_fi"], regs={"ecx": this, "ebx": 0x11, "esi": 0x22, "edi": 0x33},
                    stack=[RET_SITE, NAME_A, S, flags])
    assert where == RET_SITE
    assert emu.reg("ebx") == 0x11 and emu.reg("esi") == 0x22 and emu.reg("edi") == 0x33
    lg = emu.log()
    assert lg["this"] == this and lg["name"] == NAME_A and lg["flags"] == flags
    if g <= 16:
        assert lg["size"] == S and lg["count"] == 1                      # untouched native call
        return
    n = expect_n(S + 2, S, g)                                              # native cell of the stub model = S + 2
    assert lg["size"] == n and emu.r32(this + 0xC) == n + 2
    assert emu.r32(AT.G_SCRATCH + 0xC) >= SL.tech_font_cell(S + 2, g) or n == SL.scale_px(S, g)
    assert emu.reg("esp") == SP0 + 16                                      # RET 0xC consumed the 3 args
    # cached: the second call costs exactly one Font_init (the real one)
    emu.clear_log()
    emu.run(VA["thunk_tech_fi"], regs={"ecx": this}, stack=[RET_SITE, NAME_A, S, flags])
    assert emu.log()["count"] == 1 and emu.log()["size"] == n


def test_fi_cache_rebuilds_on_a_g_change():
    emu = Emu(40)
    emu.run(VA["thunk_tech_fi"], regs={"ecx": 0x720800}, stack=[RET_SITE, NAME_A, 14, 0])
    n40 = emu.log()["size"]
    emu.set_g(22)
    emu.clear_log()
    emu.run(VA["thunk_tech_fi"], regs={"ecx": 0x720800}, stack=[RET_SITE, NAME_A, 14, 0])
    assert emu.log()["size"] == expect_n(16, 14, 22) != n40
    emu.set_g(40)
    emu.clear_log()
    emu.run(VA["thunk_tech_fi"], regs={"ecx": 0x720800}, stack=[RET_SITE, NAME_A, 14, 0])
    assert emu.log()["size"] == n40


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("S,v", [(20, 1), (20, 2), (18, 1), (18, 2), (12, 1), (12, 2)])
def test_ff_returns_a_dedicated_font_built_with_the_pool_law(g, S, v):
    emu = Emu(g)
    emu.clear_log()
    where = emu.run(VA["thunk_tech_ff"], regs={"ebx": 0x11, "esi": 0x22, "edi": 0x33}, stack=[RET_SITE, S, v])
    assert where == RET_SITE
    assert emu.reg("ebx") == 0x11 and emu.reg("esi") == 0x22 and emu.reg("edi") == 0x33
    assert emu.reg("esp") == SP0 + 4                                        # cdecl: caller cleans
    if g <= 16:
        assert emu.reg("eax") == POOL + S * 0x40 and emu.log()["count"] == 0
        return
    font = emu.reg("eax")
    assert AT.G_FFCACHE <= font < AT.G_FFCACHE + AT.FF_SLOTS * AT.FF_STRIDE and (font - AT.G_FFCACHE) % AT.FF_STRIDE == 0x10
    lg = emu.log()
    n = expect_n(S + 4, S, g)                                              # pool cell model = S + 4
    assert lg["this"] == font and lg["size"] == n
    assert lg["name"] == (NAME_N if S > 12 else NAME_A)
    assert lg["flags"] == (VARIANT_FLAGS[v] | (1 if S > 12 else 0))
    assert emu.r32(font + 0xC) == n + 2
    slot = font - 0x10
    assert emu.r32(slot) == S and emu.r32(slot + 4) == v and emu.r32(slot + 8) == g
    emu.clear_log()
    emu.run(VA["thunk_tech_ff"], stack=[RET_SITE, S, v])
    assert emu.reg("eax") == font and emu.log()["count"] == 0             # cached


def test_ff_six_combos_share_six_slots_and_a_g_change_rebuilds_in_place():
    emu = Emu(40)
    combos = [(20, 1), (20, 2), (18, 1), (18, 2), (12, 1), (12, 2)]
    fonts = {}
    for S, v in combos:
        emu.run(VA["thunk_tech_ff"], stack=[RET_SITE, S, v])
        fonts[(S, v)] = emu.reg("eax")
    assert len(set(fonts.values())) == 6
    emu.set_g(25)
    emu.clear_log()
    emu.run(VA["thunk_tech_ff"], stack=[RET_SITE, 20, 1])
    assert emu.reg("eax") == fonts[(20, 1)] and emu.log()["count"] >= 1 and emu.log()["size"] == expect_n(24, 20, 25)


def test_calib_law_reproduces_the_proto_measurements():
    """The proto's own calibration runs (v3b, real GDI cells) as recorded in frida_tech_proto.log."""
    assert SL.tech_font_cell(24, 40) == 60 and SL.tech_font_cell(22, 40) == 55 and SL.tech_font_cell(16, 40) == 40
    assert SL.tech_font_cell(24, 25) == 37 and SL.tech_font_cell(24, 22) == 33
