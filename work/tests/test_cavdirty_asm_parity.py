"""Unicorn parity for the caviar_dirty_rect thunks (t_cav_blit / t_cav_table / t_cav_fill2).

Each thunk narrows the Caviar target Buffer (+0x54 data, +0x80 w, +0x84 -h) to its clamped dirty rect around
the engine's own call and restores it. The engine callees are stubbed as `ret N` sentinels that snapshot the
registers and the stack, so the test asserts the exact calling contract: ecx = the target with the rewritten
fields, X+l / Y+t, the other args passed through, the fields restored afterwards, ebx/esi/edi preserved,
RET size right. Bytes come from patches.yaml (the shipped template, resolved with the real symbol table).
Skips if unicorn is absent.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
unicorn = pytest.importorskip("unicorn", reason="unicorn absent -- asm parity unverified")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)
import apply_patches as ap  # noqa: E402
import assemble_cavdirty as C  # noqa: E402

T1, T2 = C.T1, C.T2
STACK = 0x00200000
DATA1, DATA2 = 0x00300000, 0x00700000          # fake pixel planes (1024 x 1024 each), clear of the stubbed engine pages
RET_SENTINEL = 0x00617600                       # any mapped executable address: `hlt`
TN = 1024


def _load(name: str) -> tuple[int, bytes]:
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == name:
                base = cave["virtual_addr"]; base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]; off = int(off, 16) if isinstance(off, str) else off
                return base + off, ap.ByteTemplate(c["bytes"]).resolve(base + off, symtab)
    raise AssertionError(name + " not in patches.yaml")


def test_yaml_bytes_match_the_assembler():
    for n, _ in C.THUNKS:
        va, b = _load(n)
        assert va == C.PCAVE2 + C.OFFS[n]
        assert b == C.assemble(n), n


class Run:
    """One emulation: builds the two targets, the rects, the stack, stubs the callee, runs the thunk."""

    def __init__(self, name: str, callee: int, args: list[int], this: int, bb1=(0, 0, 0, 0), bb2=(0, 0, 0, 0),
                 surf1=0, surf2=0, dw_dst=False, null_data=False, latch=0):
        self.name = name
        va, code = _load(name)
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(va & ~0xFFF, 0x2000)
        uc.mem_map(0x9B9000, 0x3000)            # both Buffers + both rects + the DW picker cell page? (0xA26010 below)
        uc.mem_map(0xA26000, 0x1000)
        uc.mem_map(STACK, 0x10000)
        uc.mem_map(DATA1, 0x100000); uc.mem_map(DATA2, 0x100000)
        uc.mem_map(RET_SENTINEL & ~0xFFF, 0x1000)
        uc.mem_map(callee & ~0xFFF, 0x1000)
        uc.mem_map(C.DW_SHIM & ~0xFFF, 0x1000)
        uc.mem_write(va, code)
        uc.mem_write(RET_SENTINEL, b"\xF4")
        uc.mem_write(C.DW_SHIM, b"\xF4")
        # the callee: snapshot then `ret N` (N = the args the real callee pops)
        nret = {C.BUFFER_DRAW_2: 0x18, C.BUFFER_DRAW_DS2: 0x1C, C.BUFFER_FILL_2: 4}[callee]
        uc.mem_write(callee, b"\xC2" + struct.pack("<H", nret))
        self.callee, self.snap = callee, None

        def on_code(u, addr, size, _):
            if addr == callee and self.snap is None:
                esp = u.reg_read(UC_X86_REG_ESP)
                self.snap = {
                    "ecx": u.reg_read(UC_X86_REG_ECX),
                    "args": [struct.unpack("<I", u.mem_read(esp + 4 + 4 * i, 4))[0] for i in range(8)],
                    "data": struct.unpack("<I", u.mem_read(this + 0x54, 4))[0],
                    "w": struct.unpack("<i", u.mem_read(this + 0x80, 4))[0],
                    "h": struct.unpack("<i", u.mem_read(this + 0x84, 4))[0],
                }
        uc.hook_add(UC_HOOK_CODE, on_code)
        for t, data, surf in ((T1, DATA1, surf1), (T2, DATA2, surf2)):
            uc.mem_write(t + 0x54, struct.pack("<I", 0 if null_data else data))
            uc.mem_write(t + 0x50, struct.pack("<I", latch))
            uc.mem_write(t + 0x58, struct.pack("<I", surf))
            uc.mem_write(t + 0x80, struct.pack("<i", TN))
            uc.mem_write(t + 0x84, struct.pack("<i", -TN))
            uc.mem_write(t + 0x4A8, struct.pack("<i", TN))
        uc.mem_write(C.BB1[0], struct.pack("<4i", *bb1))
        uc.mem_write(C.BB2[0], struct.pack("<4i", *bb2))
        uc.mem_write(C.DW_PICKCELL, struct.pack("<I", 0x12345678))
        esp = STACK + 0x8000
        uc.mem_write(esp, struct.pack("<I", RET_SENTINEL))
        for i, a in enumerate(args):
            uc.mem_write(esp + 4 + 4 * i, struct.pack("<I", a & 0xFFFFFFFF))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_ECX, this)
        uc.reg_write(UC_X86_REG_EBX, 0xB0B0B0B0); uc.reg_write(UC_X86_REG_ESI, 0x51515151); uc.reg_write(UC_X86_REG_EDI, 0xD1D1D1D1)
        self.esp0, self.this, self.nargs = esp, this, len(args)
        try:
            uc.emu_start(va, 0, count=200_000)
        except unicorn.UcError:
            pass
        self.eip = uc.reg_read(UC_X86_REG_EIP)

    def returned(self):                 # hlt at the sentinel leaves EIP on it or one past it
        return self.eip in (RET_SENTINEL, RET_SENTINEL + 1)

    def field(self, off, signed=False):
        return struct.unpack("<i" if signed else "<I", self.uc.mem_read(self.this + off, 4))[0]

    def regs_preserved(self):
        u = self.uc
        return (u.reg_read(UC_X86_REG_EBX), u.reg_read(UC_X86_REG_ESI), u.reg_read(UC_X86_REG_EDI)) == (0xB0B0B0B0, 0x51515151, 0xD1D1D1D1)


# ---- t_cav_blit ------------------------------------------------------------------------------------------

def test_blit_dirty_rect_narrows_the_source_and_restores():
    args = [0x777000, 9, 1000, 2000, 1, 1]        # dst, key, X, Y, num, den
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, args, T1, bb1=(100, 50, 300, 90))
    assert r.snap, "the engine blit was not called"
    assert r.snap["ecx"] == T1
    assert r.snap["data"] == DATA1 + 50 * TN + 100
    assert (r.snap["w"], r.snap["h"]) == (200, -40)
    assert r.snap["args"][:6] == [0x777000, 9, 1100, 2050, 1, 1]
    # restored, stack cleaned (RET 0x18), callee-saved regs intact, returned to the caller
    assert (r.field(0x54), r.field(0x80), r.field(0x84, True)) == (DATA1, TN, -TN)
    assert r.uc.reg_read(UC_X86_REG_ESP) == r.esp0 + 4 + 0x18
    assert r.regs_preserved() and r.returned()


def test_blit_rect_is_clamped_to_the_target():
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, [1, 9, 0, 0, 1, 1], T1, bb1=(-20, -8, 1100, 1030))
    assert r.snap["data"] == DATA1 and (r.snap["w"], r.snap["h"]) == (TN, -TN)
    assert r.snap["args"][2:4] == [0, 0]


def test_blit_empty_rect_draws_nothing():
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, [1, 9, 5, 6, 1, 1], T1, bb1=(0, 0, 0, 0))
    assert r.snap is None and r.returned()
    assert r.uc.reg_read(UC_X86_REG_ESP) == r.esp0 + 4 + 0x18 and r.regs_preserved()
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, [1, 9, 5, 6, 1, 1], T1, bb1=(300, 10, 100, 50))   # inverted
    assert r.snap is None and r.returned()


@pytest.mark.parametrize("args,surf,bb,why", [
    ([1, 9, 5, 6, 1, 2], 0, (10, 10, 50, 50), "scaled (num != den) -> the whole-target blit"),
    ([1, 9, 5, 6, 1, 1], 0x1234, (10, 10, 50, 50), "a DDraw surface -> the engine's own path"),
])
def test_blit_falls_through_to_the_engine_untouched(args, surf, bb, why):
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, args, T1, bb1=bb, surf1=surf)
    assert r.snap and r.snap["ecx"] == T1 and r.snap["data"] == DATA1 and r.snap["w"] == TN, why
    assert r.snap["args"][:6] == args
    assert r.returned() and r.uc.reg_read(UC_X86_REG_ESP) == r.esp0 + 4 + 0x18


def test_blit_other_source_falls_through():
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, [1, 9, 5, 6, 1, 1], T2, bb1=(10, 10, 50, 50))
    assert r.snap and r.snap["ecx"] == T2 and r.snap["args"][:6] == [1, 9, 5, 6, 1, 1]


@pytest.mark.parametrize("dst", [C.DW_CANVAS, 0x12345678])
def test_blit_design_workshop_destinations_hand_off_to_the_shim(dst):
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, [dst, 9, 5, 6, 1, 1], T1, bb1=(10, 10, 50, 50))
    assert r.snap is None and r.eip in (C.DW_SHIM, C.DW_SHIM + 1)
    assert r.uc.reg_read(UC_X86_REG_ESP) == r.esp0 and r.uc.reg_read(UC_X86_REG_ECX) == T1   # a tail jump: the frame untouched


# ---- t_cav_table -----------------------------------------------------------------------------------------

def test_table_dirty_rect_narrows_target2_and_restores():
    args = [0x777000, 0, 1000, 2000, 1, 1, 0x9BB4CC]     # dst, key, x, y, num, den, table
    r = Run("t_cav_table", C.BUFFER_DRAW_DS2, args, T2, bb2=(7, 3, 60, 40))
    assert r.snap and r.snap["ecx"] == T2
    assert r.snap["data"] == DATA2 + 3 * TN + 7 and (r.snap["w"], r.snap["h"]) == (54, -38)   # r/b dilated by one
    assert r.snap["args"][:7] == [0x777000, 0, 1007, 2003, 1, 1, 0x9BB4CC]
    assert (r.field(0x54), r.field(0x80), r.field(0x84, True)) == (DATA2, TN, -TN)
    assert r.uc.reg_read(UC_X86_REG_ESP) == r.esp0 + 4 + 0x1C and r.regs_preserved() and r.returned()


def test_table_empty_rect_and_fallthroughs():
    r = Run("t_cav_table", C.BUFFER_DRAW_DS2, [1, 0, 5, 6, 1, 1, 7], T2, bb2=(0, 0, 0, 0))
    assert r.snap is None and r.returned() and r.uc.reg_read(UC_X86_REG_ESP) == r.esp0 + 4 + 0x1C
    r = Run("t_cav_table", C.BUFFER_DRAW_DS2, [1, 0, 5, 6, 1, 2, 7], T2, bb2=(1, 1, 9, 9))
    assert r.snap and r.snap["data"] == DATA2 and r.snap["args"][:7] == [1, 0, 5, 6, 1, 2, 7]


# ---- t_cav_fill2 -----------------------------------------------------------------------------------------

def _plane(r):
    return bytes(r.uc.mem_read(DATA2, TN * TN))


def test_fill2_clears_only_the_rect():
    r = Run("t_cav_fill2", C.BUFFER_FILL_2, [0], T2, bb2=(100, 20, 180, 23))
    r2 = Run("t_cav_fill2", C.BUFFER_FILL_2, [0], T2, bb2=(100, 20, 180, 23))   # fresh plane to paint 0xAA first
    uc = r2.uc
    uc.mem_write(DATA2, b"\xAA" * (TN * TN))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I", RET_SENTINEL)); uc.mem_write(esp + 4, struct.pack("<I", 0x37))
    uc.reg_write(UC_X86_REG_ESP, esp); uc.reg_write(UC_X86_REG_ECX, T2)
    uc.reg_write(UC_X86_REG_EBX, 0xB0B0B0B0); uc.reg_write(UC_X86_REG_ESI, 0x51515151); uc.reg_write(UC_X86_REG_EDI, 0xD1D1D1D1)
    va, _ = _load("t_cav_fill2")
    try:
        uc.emu_start(va, 0, count=2_000_000)
    except unicorn.UcError:
        pass
    plane = _plane(r2)
    expect = bytearray(b"\xAA" * (TN * TN))
    for y in range(20, 24):                                   # b dilated: rows 20..23
        expect[y * TN + 100:y * TN + 181] = b"\x37" * 81       # r dilated: cols 100..180
    assert plane == bytes(expect)
    assert r2.snap is None and uc.reg_read(UC_X86_REG_EIP) in (RET_SENTINEL, RET_SENTINEL + 1)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4 + 4 and r2.regs_preserved()


def test_fill2_clamps_and_skips_empty():
    r = Run("t_cav_fill2", C.BUFFER_FILL_2, [0x5A], T2, bb2=(-5, 1022, 3, 1030))
    plane = _plane(r)
    assert plane[1022 * TN:1022 * TN + 4] == b"\x5A" * 4 and plane[1023 * TN:1023 * TN + 4] == b"\x5A" * 4   # r 3 -> 4
    assert plane[1022 * TN + 4] == 0 and plane[1021 * TN] == 0
    r = Run("t_cav_fill2", C.BUFFER_FILL_2, [0x5A], T2, bb2=(0, 0, 0, 0))
    assert r.snap is None and r.returned() and _plane(r) == bytes(TN * TN)


def test_fill2_surface_or_other_buffer_falls_through():
    r = Run("t_cav_fill2", C.BUFFER_FILL_2, [0], T2, bb2=(1, 1, 5, 5), surf2=0x1234)
    assert r.snap and r.snap["ecx"] == T2 and r.snap["args"][0] == 0
    r = Run("t_cav_fill2", C.BUFFER_FILL_2, [0], T1, bb2=(1, 1, 5, 5))
    assert r.snap and r.snap["ecx"] == T1


@pytest.mark.parametrize("name,callee,args,this", [
    ("t_cav_blit", C.BUFFER_DRAW_2, [1, 9, 5, 6, 1, 1], T1),
    ("t_cav_table", C.BUFFER_DRAW_DS2, [1, 0, 5, 6, 1, 1, 7], T2),
    ("t_cav_fill2", C.BUFFER_FILL_2, [0], T2),
])
def test_null_data_takes_the_engine_path(name, callee, args, this):
    """A target whose data pointer is 0 (Buffer_init failure / after shutdown): the engine's own call, untouched
    (it skips on data == 0; a narrowed 0 + offset would read garbage)."""
    r = Run(name, callee, args, this, bb1=(1, 1, 9, 9), bb2=(1, 1, 9, 9), null_data=True)
    assert r.snap and r.snap["ecx"] == this and r.snap["data"] == 0 and r.snap["w"] == TN
    assert r.snap["args"][:len(args)] == args and r.returned()


def test_lock_latch_is_restored():
    """+0x50 (the engine's lock latch) is saved with the fields and restored after the call."""
    r = Run("t_cav_blit", C.BUFFER_DRAW_2, [1, 9, 5, 6, 1, 1], T1, bb1=(10, 10, 50, 50), latch=0x77)
    assert r.snap and r.field(0x50) == 0x77 and r.returned()
    r = Run("t_cav_table", C.BUFFER_DRAW_DS2, [1, 0, 5, 6, 1, 1, 7], T2, bb2=(10, 10, 50, 50), latch=0x55)
    assert r.snap and r.field(0x50) == 0x55 and r.returned()
