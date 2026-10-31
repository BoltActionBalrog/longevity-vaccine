"""g=16 no-op net for the strip draw functions (pristine exe vs live exe).

Emulates each of the 7 BaseWin strip draw functions in BOTH binaries from an
identical synthetic state with g_popup_scale_num = 16, stubbing every
out-of-function call (recording target + ecx + 8 stack args) and logging
every non-stack memory write.  At g=16 the live exe must produce an
IDENTICAL event trace — this is the executable form of the "1024 must be
byte-identical vanilla" invariant for the strip, and it caught the
draw_queue.listx5 EFLAGS-clobber regression the moment it was written.

Skips if the game exes are not present (same policy as the MD5 tests).
"""
import os
import struct
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)

import config  # noqa: E402

try:
    import pefile
    from unicorn import (Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_BLOCK,
                         UC_HOOK_MEM_WRITE,
                         UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                         UC_HOOK_MEM_FETCH_UNMAPPED)
    from unicorn.x86_const import (
        UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
        UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
        UC_X86_REG_EFLAGS)
    HAVE_EMU = True
except ImportError:  # pragma: no cover
    HAVE_EMU = False

FNS = {
    "draw_production": (0x40E360, 0x40F0E5),
    "draw_flash":      (0x40D250, 0x40E35B),
    "draw_queue":      (0x415080, 0x415724),
    "draw_pop":        (0x414B40, 0x415078),
    "draw_garrison":   (0x4103B0, 0x410868),
    "draw_supported":  (0x40C850, 0x40D24C),
    "draw_info":       (0x415B20, 0x415DCE),
}

G_ADDR = 0x668740
PCAVE2 = (0xA0C000, 0xA0C000 + 0x30000)   # full section (grown 0xE000->0xF000 26b, ->0x10000 26i; the cave is 0x30000 since 2026-09-14 -- t_tile_force @0x27A00 was past the old bound)
MAGIC_RET = 0x0CAFE000
STACK_TOP = 0x00F00000
FRAME_LO = STACK_TOP - 0x20000
THIS_PTR = 0x00300000
BUDGET = 3_000_000
TRACE_CAP = 6000
SEEDS = (0, 1)


def fhash(x):
    return (x * 2654435761) & 0xFFFFFFFF


def load_sections(path):
    pe = pefile.PE(path, fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    out = []
    for s in pe.sections:
        va = ib + s.VirtualAddress
        vsize = max(s.Misc_VirtualSize, s.SizeOfRawData)
        data = s.get_data()[:vsize]
        data = data + b"\x00" * (((vsize + 0xFFF) & ~0xFFF) - len(data))
        out.append((va, data))
    pe.close()
    return out


class FnRun:
    def __init__(self, sections, fn, seed, extra_exec):
        self.lo, self.hi = fn
        self.allowed = [(self.lo, self.hi)] + list(extra_exec)
        self.trace = []
        self.pending = None
        self.done = False
        self.mapped = set()
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc

        def pat_page(page):
            b = bytearray(0x1000)
            for off in range(0, 0x1000, 4):
                v = 1 + ((fhash(page + off + seed * 977) >> 24) & 7)
                b[off:off + 4] = struct.pack("<I", v)
            return bytes(b)

        def map_page(addr):
            page = addr & ~0xFFF
            if page in self.mapped:
                return
            uc.mem_map(page, 0x1000)
            uc.mem_write(page, pat_page(page))
            self.mapped.add(page)

        def on_unmapped(uc_, access, addr, size, value, _u):
            map_page(addr)
            if (addr & ~0xFFF) != ((addr + size - 1) & ~0xFFF):
                map_page(addr + size - 1)
            return True

        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED |
                    UC_HOOK_MEM_FETCH_UNMAPPED, on_unmapped)

        def on_block(uc_, addr, size, _u):
            if any(l <= addr < h for l, h in self.allowed):
                return
            self.pending = addr
            uc_.emu_stop()

        uc.hook_add(UC_HOOK_BLOCK, on_block)

        def on_write(uc_, access, addr, size, value, _u):
            if FRAME_LO <= addr < STACK_TOP:
                return
            if PCAVE2[0] <= addr < PCAVE2[1]:
                return
            if len(self.trace) < TRACE_CAP:
                self.trace.append(
                    ("w", addr, size, value & ((1 << (size * 8)) - 1)))

        uc.hook_add(UC_HOOK_MEM_WRITE, on_write)

        for va, data in sections:
            base = va & ~0xFFF
            end = (va + len(data) + 0xFFF) & ~0xFFF
            uc.mem_map(base, end - base)
            uc.mem_write(va, data)
            for p in range(base, end, 0x1000):
                self.mapped.add(p)

        for p in range(FRAME_LO, STACK_TOP, 0x1000):
            map_page(p)

        uc.mem_write(G_ADDR, struct.pack("<i", 16))

        esp = STACK_TOP - 0x4000
        uc.mem_write(esp, struct.pack("<I", MAGIC_RET))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_EBP, STACK_TOP - 0x3000)
        uc.reg_write(UC_X86_REG_ECX, THIS_PTR)
        uc.reg_write(UC_X86_REG_EAX, 0x1000 + seed)
        uc.reg_write(UC_X86_REG_EBX, 0x2000 + seed)
        uc.reg_write(UC_X86_REG_EDX, 0x3000 + seed)
        uc.reg_write(UC_X86_REG_ESI, 0x4000 + seed)
        uc.reg_write(UC_X86_REG_EDI, 0x5000 + seed)
        uc.reg_write(UC_X86_REG_EFLAGS, 0x202)

    def run(self):
        uc = self.uc
        eip = self.lo
        budget = BUDGET
        while budget > 0 and not self.done and len(self.trace) < TRACE_CAP:
            self.pending = None
            try:
                uc.emu_start(eip, 0, count=budget)
            except Exception as e:
                self.trace.append(("exc", str(e).split("(")[0]))
                break
            if self.pending is None:
                self.trace.append(("stop", "no-pending"))
                break
            tgt = self.pending
            if tgt == MAGIC_RET:
                self.trace.append(("ret", uc.reg_read(UC_X86_REG_EAX)))
                self.done = True
                break
            esp = uc.reg_read(UC_X86_REG_ESP)
            ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
            if not any(l <= ret < h for l, h in self.allowed):
                self.trace.append(("jmpout", tgt))
                break
            args = struct.unpack("<8I", uc.mem_read(esp + 4, 32))
            self.trace.append(
                ("call", tgt, uc.reg_read(UC_X86_REG_ECX), args))
            uc.reg_write(UC_X86_REG_ESP, esp + 4)
            uc.reg_write(UC_X86_REG_EAX, 0x01000000 + (fhash(tgt) & 0xFFFF) * 4)
            uc.reg_write(UC_X86_REG_EDX, fhash(tgt ^ 0x1111) & 0x7FFF)
            uc.reg_write(UC_X86_REG_ECX, fhash(tgt ^ 0x2222) & 0x7FFF)
            eip = ret
            budget -= 1000
        return self


@pytest.fixture(scope="module")
def images():
    if not HAVE_EMU:
        pytest.skip("pefile/unicorn not installed")
    bak = config.terranx_bak()
    live = config.terranx(required=False)
    if bak is None or live is None or not os.path.exists(str(bak)) \
            or not os.path.exists(str(live)):
        pytest.skip("game exe / pristine .bak not present")
    return load_sections(str(bak)), load_sections(str(live))


@pytest.mark.parametrize("name", sorted(FNS))
def test_strip_fn_g16_identity(images, name):
    pristine, live = images
    fn = FNS[name]
    for seed in SEEDS:
        ta = FnRun(pristine, fn, seed, extra_exec=[]).run().trace
        tb = FnRun(live, fn, seed, extra_exec=[PCAVE2]).run().trace
        for i in range(min(len(ta), len(tb))):
            assert ta[i] == tb[i], (
                f"{name} seed={seed} diverges at event {i}:\n"
                f"  pristine: {ta[i]}\n  live:     {tb[i]}")
        assert len(ta) == len(tb), (
            f"{name} seed={seed}: trace length {len(ta)} vs {len(tb)}")
