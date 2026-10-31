"""Unicorn parity of the W2A helpers on the SHIPPED bytes (2026-10-25 wave-2 W2A; src scripts/assemble_halfopen_frames.py):

  t_rw_btnw   == scaling_laws.rw_btn_pair (F30) for every g 1..64 and odd / even rows; registers as its two callers
                (t_rw_gap1 / t_rw_gap2 v2) need them;
  t_bm_ho_pp / t_bm_ho_hf == scaling_laws.union_frame_draw_rect (F38): the renderer sees (L, T, R-1, B-1) at g > 16 and
                the caller's rect untouched at g <= 16 (a tail jump: the renderer returns straight to the site); the rect
                is restored, ebx / esi / edi / ebp kept, RET 8;
  t_bm_ho_df (W4C, F42) == scaling_laws.se_frame_draw_rect: the same contract in front of thunk_box_thick_devfill;
  and the yaml bytes (every placeholder resolved by the patcher) == the assembler's output at its pinned offsets,
  inside the W2A region 0x34000..0x34FFF / the W4C region 0x3B000..0x3BFFF (t_se_layout included; its parity is in
  test_scaling_se_halfopen.py); the sites call them (the twelve SocialWin frame sites SE_HALFOPEN_FRAME_SITES
  included: eleven band-map frames and the OK-row union frame).

All on the conftest `baked_exe` bytes (sections mapped into one Unicorn per module), renderers replaced by a recording
stub.  Cheap: no boot.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI,
    UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_halfopen_frames as HO  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
STACK = 0x10000000
SP0 = STACK + 0x80000
TRAP = STACK + 0x100        # return address of the emulated CALL (hlt)
REC = STACK + 0x1000        # what the renderer stub saw
RECT = STACK + 0x2000
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
        UC_X86_REG_EBP)


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def img(baked_exe):
    data = Path(baked_exe).read_bytes()
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for sct in pe.sections:
        va = ib + sct.VirtualAddress
        mu.mem_map(va, (max(sct.Misc_VirtualSize, sct.SizeOfRawData) + 0xFFF) & ~0xFFF)
        mu.mem_write(va, sct.get_data())
    mu.mem_map(STACK, 0x100000)
    mu.mem_write(TRAP, b"\xF4")
    return mu


def r32(mu, a):
    return struct.unpack("<i", bytes(mu.mem_read(a, 4)))[0]


def w32(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


def _stub_recorder(mu, va):
    """At the renderer VA: record ecx, the rect pointer, the params arg, the rect's four dwords and the return address
    as the renderer sees them, then RET 8 (Buffer_box_sprite's contract).  Returns the bytes it overwrote."""
    from keystone import KS_ARCH_X86, KS_MODE_32, Ks
    src = f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+4]
        mov edx, dword ptr [eax]
        mov dword ptr [{REC + 16:#x}], edx
        mov edx, dword ptr [eax+4]
        mov dword ptr [{REC + 20:#x}], edx
        mov edx, dword ptr [eax+8]
        mov dword ptr [{REC + 24:#x}], edx
        mov edx, dword ptr [eax+12]
        mov dword ptr [{REC + 28:#x}], edx
        mov dword ptr [{REC + 32:#x}], 1
        ret 8
    """
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)[0])
    old = bytes(mu.mem_read(va, len(b)))
    mu.mem_write(va, b)
    return old


# ---------------------------------------------------------------- yaml == assembler, placement, sites
@pytest.mark.parametrize("name", list(HO.HELPERS))
def test_yaml_bytes_are_the_assembler(img, symtab, name):
    off, end, sym, _tva = HO.HELPERS[name]
    va = HO.PCAVE2 + off
    assert symtab[name] == va and any(lo <= off < end <= hi for lo, hi in HO.REGIONS), "pinned in its fixer's region"
    want = HO.assemble(name, g=G_VA, target=symtab[sym] if sym else None)
    assert bytes(img.mem_read(va, len(want))) == want
    nxt = min((v for n, v in symtab.items() if va < v < HO.PCAVE2 + end and n != name), default=None)
    assert nxt is None, f"{name}'s slot holds another symbol at {nxt:#x}"


def test_sites_call_the_helpers(img, symtab):
    for _sid, _grp, _fn, va, helper, _note in HO.SITES + HO.se_sites():
        b = bytes(img.mem_read(va, 5))
        assert b[0] == 0xE8 and va + 5 + struct.unpack("<i", b[1:])[0] == symtab[helper], hex(va)
    for gap in ("t_rw_gap1", "t_rw_gap2"):
        code = bytes(img.mem_read(symtab[gap], 18))
        k = code.index(b"\xE8")
        assert symtab[gap] + k + 5 + struct.unpack("<i", code[k + 1:k + 5])[0] == symtab["t_rw_btnw"], gap
    for va in SL.COUNCIL_CONSOLE_FRAME_SITES:
        b = bytes(img.mem_read(va, 5))
        assert b[0] == 0xE8 and va + 5 + struct.unpack("<i", b[1:])[0] == symtab["t_rw_rowframe"], hex(va)


# ---------------------------------------------------------------- t_rw_btnw
@pytest.mark.parametrize("g", range(1, 65))
def test_btnw_is_the_law(img, symtab, g):
    mu, fn = img, symtab["t_rw_btnw"]
    w32(mu, G_VA, g)
    for L, R in ((1301, 2538), (1301, 2537), (101, 595), (400, 1401)):
        mid = (L + R) >> 1
        w32(mu, 0x87E070, L)
        w32(mu, 0x87E078, R)
        for r in REGS:
            mu.reg_write(r, 0x5A5A0000 + r)
        mu.reg_write(UC_X86_REG_EAX, mid)
        mu.reg_write(UC_X86_REG_EDX, L)
        w32(mu, SP0 - 4, TRAP)
        mu.reg_write(UC_X86_REG_ESP, SP0 - 4)
        mu.emu_start(fn, TRAP, count=100)
        w, x = mu.reg_read(UC_X86_REG_EAX), mu.reg_read(UC_X86_REG_EDX)
        (a0, a1), (b0, b1) = SL.rw_btn_pair(L, R, g)
        assert (L, L + w) == (a0, a1) and (x, x + w) == (b0, b1), (g, L, R, w, x)
        assert mu.reg_read(UC_X86_REG_ESP) == SP0
        for r in (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == 0x5A5A0000 + r


# ---------------------------------------------------------------- t_bm_ho_pp / t_bm_ho_hf
@pytest.mark.parametrize("g", (1, 8, 15, 16, 17, 18, 22, 25, 30, 33, 40, 48))
@pytest.mark.parametrize("name", ("t_bm_ho_pp", "t_bm_ho_hf", "t_bm_ho_df"))
def test_union_frame_helper_is_the_law(img, symtab, g, name):
    mu, fn = img, symtab[name]
    renderer = symtab[HO.HELPERS[name][2]]
    old = _stub_recorder(mu, renderer)
    try:
        rect = (567, 600, 1030, 628)
        params = 0x78D5A0
        mu.mem_write(RECT, struct.pack("<4i", *rect))
        mu.mem_write(REC, bytes(64))
        w32(mu, G_VA, g)
        for r in REGS:
            mu.reg_write(r, 0x5A5A0000 + r)
        mu.reg_write(UC_X86_REG_ECX, 0x7AEC64)
        esp = SP0 - 12
        mu.mem_write(esp, struct.pack("<III", TRAP, RECT, params))
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(fn, TRAP, count=200)
        assert r32(mu, REC + 32) == 1, "the renderer ran"
        seen = tuple(r32(mu, REC + 16 + 4 * i) for i in range(4))
        want = SL.union_frame_draw_rect(*rect, g)
        for va, (_sid, ren) in SL.SE_HALFOPEN_FRAME_SITES.items():     # the SE sites that call this helper: their law
            if HO.SE_SITE_HELPER[ren] == name:
                assert SL.se_frame_draw_rect(va, *rect, g) == want
        assert seen == (want if g > 16 else rect), (g, seen)
        assert r32(mu, REC) == 0x7AEC64 and r32(mu, REC + 8) == RECT and r32(mu, REC + 12) == params
        if g <= 16:
            assert r32(mu, REC + 4) == TRAP, "a tail jump: the renderer returns straight to the site"
        assert tuple(r32(mu, RECT + 4 * i) for i in range(4)) == rect, "the caller's rect restored"
        assert mu.reg_read(UC_X86_REG_ESP) == SP0, "RET 8"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == 0x5A5A0000 + r
    finally:
        mu.mem_write(renderer, old)
