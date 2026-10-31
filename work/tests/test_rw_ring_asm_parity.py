"""Unicorn parity for the W6C helpers (scripts/assemble_rw_ring.py), from their REAL assembled bytes at their REAL
cave VAs (2026-10-25 wave 6).

1. t_rw_ring (detour @0x49935D): the research increment inset == scaling_laws.rw_tech_ring_clip at every g 1..64;
   it resumes at the Buffer_set_clip call 0x49937F with the vanilla register / stack state; at g <= 16 its state is
   the PRISTINE bytes' state (the vanilla 0x49935D..0x49937E run under the same emulator).
2. t_dl_snapchk: the plane / bounds contract -- allocation order (4 MB, else 64 KB, size into g_dl_snapcap), a plane
   with cap 0 is t_rw_init_leave's 4 MB, an oversized / empty / 32-bit-overflowing bbox -> ebx 0; ecx / esi / edi
   kept, the stack balanced.
3. t_dl_bmxt + t_dl_snapchk end to end, the FALLBACK proof: t_rw_init_leave's 4 MB VirtualAlloc failed, the 64 KB
   fallback plane sits between write-watched guard bands; an oversized frame draws natively and writes NOTHING
   outside the plane, a fitting one still takes the snapshot path; a mutant without the bound (cap forced huge)
   overruns into the guard (the check is what holds the line).  An empty bbox (frame off the buffer) draws natively.
4. t_rw_br1 (bracket 1's draw): g <= 16 the call reaches t_dl_bmxt untouched; g > 16 t_dl_bmxt(rect, set) then
   t_rw_restripe(buf, &buf->clip, set); RET 8, ebx / esi / edi kept.
5. pins: the shipped yaml bytes == the assembler (helpers, t_dl_bmxt at 599 B, both sites); the thunk VAs the
   helpers call; t_rw_init_leave's only plane is push 0x400000 and only it and t_dl_snapchk write g_dl_snapbuf.
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
capstone = pytest.importorskip("capstone")
pefile = pytest.importorskip("pefile")

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_dl as AD  # noqa: E402
    import assemble_rw_ring as RR  # noqa: E402

PC = RR.PCAVE2
STACK, SP0 = 0x00300000, 0x00310000
RET_SITE = 0x00700100
STUB = 0x00700000
BUF = 0x02000000                  # a Buffer struct (+0x20 clip, +0x54 data, +0x80 w, +0x84 -h, +0x4A8 pitch)
DATA = 0x02100000                 # its pixels
PLANE = 0x03000000                # the 64 KB fallback plane, guards on both sides
GUARD = 0x100000
BMXT_LEN = 599
_ks = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(src, va):
    return bytes(_ks.asm(src, va)[0])


def r32(uc, a):
    return struct.unpack("<I", bytes(uc.mem_read(a, 4)))[0]


def s32(uc, a):
    return struct.unpack("<i", bytes(uc.mem_read(a, 4)))[0]


def w32(uc, a, v):
    uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


class Emu:
    def __init__(self, g):
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(PC, 0x40000)
        uc.mem_map(STACK, 0x20000)
        uc.mem_map(STUB, 0x1000)
        uc.mem_map(0x668000, 0x1000)                       # g_popup_scale_num
        uc.mem_map(0x669000, 0x1000)                       # IAT
        uc.mem_map(0x499000, 0x1000)                       # ReportWin_tech_page's bracket block
        uc.mem_map(0x5E2000, 0x1000)                       # Buffer_box_sprite
        uc.mem_map(BUF, 0x1000)
        uc.mem_map(DATA, 0x40000)
        uc.mem_map(PLANE - GUARD, 0x10000 + 2 * GUARD)
        uc.mem_write(STUB, b"\xC3" * 0x800 + bytes(0x800))     # code stubs below +0x800, zeroed records above
        L, _end, _names = AD.assemble_all()
        for _n, (off, b) in L.items():
            uc.mem_write(PC + off, b)
        for name in RR.HELPERS:
            uc.mem_write(PC + RR.HELPERS[name][0], RR.assemble(name))
        w32(uc, AD.G, g)
        self.va_calls = []
        self.guard_writes = []

    def guard_watch(self):
        def hit(uc, acc, addr, size, val, ud):
            if not (PLANE <= addr and addr + size <= PLANE + 0x10000):
                self.guard_writes.append((addr, size))
        self.uc.hook_add(UC_HOOK_MEM_WRITE, hit, begin=PLANE - GUARD, end=PLANE + 0x10000 + GUARD - 1)

    def virtualalloc(self, results):
        """IAT VirtualAlloc -> a stub returning results[size] (0 = failure) and recording (size)."""
        rec = STUB + 0x800
        code = []
        for i, (size, ret) in enumerate(results.items()):
            code.append(f"cmp dword ptr [esp+8], {size:#x}\n jne n{i}\n mov eax, {ret:#x}\n jmp done\n n{i}:")
        src = (f"mov eax, dword ptr [{rec:#x}]\n inc eax\n mov dword ptr [{rec:#x}], eax\n"
               f"mov eax, dword ptr [esp+8]\n mov dword ptr [{rec + 4:#x}], eax\n" + "\n".join(code) +
               "\n xor eax, eax\n done:\n ret 0x10")
        self.uc.mem_write(STUB + 0x200, asm(src, STUB + 0x200))
        w32(self.uc, AD.IAT_VIRTUALALLOC, STUB + 0x200)
        return rec

    def call(self, entry, args=(), until=RET_SITE, **regs):
        uc = self.uc
        sp = SP0
        for a in reversed(args):
            sp -= 4
            w32(uc, sp, a)
        sp -= 4
        w32(uc, sp, RET_SITE)
        uc.reg_write(UC_X86_REG_ESP, sp)
        for r, v in regs.items():
            uc.reg_write({"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
                          "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP}[r], v)
        uc.emu_start(entry, until, count=50_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == until
        return uc


# ============================================================================== 1. t_rw_ring
FRAME_BASE = STACK + 0x8000        # ebp: the page's frame; the rect at ebp-0x28..-0x1C
RECTS = ((810, 122, 1096, 175), (324, 49, 438, 70), (0, 0, 1, 1), (506, 77, 684, 109), (-5, -3, 2, 4))


def _run_ring(e, rect, code_at, edi=0x0BADF00D):
    uc = e.uc
    for i, v in enumerate(rect):
        w32(uc, FRAME_BASE - 0x28 + 4 * i, v)
    sp = SP0
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_EBP, FRAME_BASE)
    uc.reg_write(UC_X86_REG_EDI, edi)
    uc.reg_write(UC_X86_REG_ESI, 0x5151)
    uc.reg_write(UC_X86_REG_EBX, 0x3333)
    uc.emu_start(code_at, RR.RING_RESUME, count=1000)
    assert uc.reg_read(UC_X86_REG_EIP) == RR.RING_RESUME
    esp = uc.reg_read(UC_X86_REG_ESP)
    return {
        "rect": tuple(s32(uc, FRAME_BASE - 0x28 + 4 * i) for i in range(4)),
        "eax": uc.reg_read(UC_X86_REG_EAX), "ecx": uc.reg_read(UC_X86_REG_ECX),
        "edx": uc.reg_read(UC_X86_REG_EDX) & 0xFFFFFFFF, "esi": uc.reg_read(UC_X86_REG_ESI),
        "ebx": uc.reg_read(UC_X86_REG_EBX), "esp": esp, "pushed": r32(uc, esp),
    }


@pytest.mark.parametrize("g", range(1, 65))
def test_ring_inset_is_the_law(g):
    e = Emu(g)
    e.uc.mem_write(RR.RING_SITE, RR.ring_site_bytes())
    for rect in RECTS:
        st = _run_ring(e, rect, RR.RING_SITE)                      # through the site's E9, as the page runs it
        want = SL.rw_tech_ring_clip(rect, g)
        assert st["rect"] == want
        k = want[0] - rect[0]
        assert want[1] - rect[1] == rect[2] - want[2] == rect[3] - want[3] == k     # one K on all four sides
        assert k == (SL.stroke_width(g) if g > 16 else 1)
        assert st["eax"] == FRAME_BASE - 0x28 == st["pushed"]      # push &rect for Buffer_set_clip
        assert st["esp"] == SP0 - 4 and st["ecx"] == 0x0BADF00D   # ecx = edi (the Buffer)
        assert st["edx"] == want[3] & 0xFFFFFFFF
        assert st["esi"] == 0x5151 and st["ebx"] == 0x3333


@pytest.mark.parametrize("g", (8, 12, 15, 16))
def test_ring_is_vanilla_at_native_g(g, bak_bytes):
    """g <= 16: the thunk leaves EXACTLY the state the pristine 0x49935D..0x49937E leaves (inc / dec 1)."""
    img = pefile.PE(data=bak_bytes, fast_load=True).get_memory_mapped_image()
    vanilla = img[RR.RING_SITE - 0x400000:RR.RING_RESUME - 0x400000]
    assert vanilla[:RR.RING_LEN] == RR.RING_ORIG
    a, b = Emu(g), Emu(g)
    a.uc.mem_write(RR.RING_SITE, vanilla)
    b.uc.mem_write(RR.RING_SITE, RR.ring_site_bytes())
    for rect in RECTS:
        assert _run_ring(a, rect, RR.RING_SITE) == _run_ring(b, rect, RR.RING_SITE)


# ============================================================================== 2. t_dl_snapchk
def _stage_bx(uc, x0, y0, x1, y1):
    for k, v in zip(("X0", "Y0", "X1", "Y1"), (x0, y0, x1, y1)):
        w32(uc, RR.BX[k], v)


def _snapchk(e, ecx=0xC0C0, esi=0x5151, edi=0x7171):
    uc = e.call(RR.VA["t_dl_snapchk"], ecx=ecx, esi=esi, edi=edi, ebx=0xDEAD)
    assert uc.reg_read(UC_X86_REG_ESP) == SP0
    assert (uc.reg_read(UC_X86_REG_ECX), uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI)) == (ecx, esi, edi)
    return uc.reg_read(UC_X86_REG_EBX)


def test_snapchk_allocates_4mb_first():
    e = Emu(40)
    rec = e.virtualalloc({RR.SNAP_BIG: 0x04000000, RR.SNAP_SMALL: PLANE})
    _stage_bx(e.uc, 0, 0, 2000, 2000)                       # 4,000,000 <= 4 MB
    assert _snapchk(e) == 0x04000000
    assert r32(e.uc, RR.SNAPBUF) == 0x04000000 and r32(e.uc, RR.CAP) == RR.SNAP_BIG
    assert r32(e.uc, rec) == 1 and r32(e.uc, rec + 4) == RR.SNAP_BIG
    _stage_bx(e.uc, 0, 0, 2048, 2049)                       # 4,196,352 > 4 MB: no second allocation, skip
    assert _snapchk(e) == 0 and r32(e.uc, rec) == 1


def test_snapchk_falls_back_to_64k_and_bounds_it():
    e = Emu(40)
    rec = e.virtualalloc({RR.SNAP_BIG: 0, RR.SNAP_SMALL: PLANE})
    _stage_bx(e.uc, 10, 10, 266, 266)                       # 65,536: exactly the plane
    assert _snapchk(e) == PLANE
    assert r32(e.uc, RR.SNAPBUF) == PLANE and r32(e.uc, RR.CAP) == RR.SNAP_SMALL and r32(e.uc, rec) == 2
    _stage_bx(e.uc, 10, 10, 267, 266)                       # one column more
    assert _snapchk(e) == 0
    assert r32(e.uc, RR.SNAPBUF) == PLANE and r32(e.uc, rec) == 2      # never re-allocated per draw


def test_snapchk_both_allocations_fail():
    e = Emu(40)
    rec = e.virtualalloc({})
    _stage_bx(e.uc, 0, 0, 8, 8)
    assert _snapchk(e) == 0 and r32(e.uc, RR.SNAPBUF) == 0 and r32(e.uc, RR.CAP) == 0 and r32(e.uc, rec) == 2


def test_snapchk_rw_plane_is_4mb():
    """t_rw_init_leave's plane: g_dl_snapbuf set, g_dl_snapcap 0 -> 4 MB (recorded), no allocation."""
    e = Emu(40)
    rec = e.virtualalloc({RR.SNAP_BIG: 0x05000000})
    w32(e.uc, RR.SNAPBUF, 0x06000000)
    _stage_bx(e.uc, 0, 0, 2000, 2097)                       # 4,194,000 <= 4,194,304
    assert _snapchk(e) == 0x06000000 and r32(e.uc, RR.CAP) == RR.SNAP_BIG and r32(e.uc, rec) == 0
    _stage_bx(e.uc, 0, 0, 2000, 2098)
    assert _snapchk(e) == 0


@pytest.mark.parametrize("bx", ((50, 0, 50, 10), (60, 0, 50, 10), (0, 7, 10, 7), (0, 9, 10, 3),
                                (0, 0, 0x10000, 0x10001), (0, 0, 0x7FFFFFFF, 3)))
def test_snapchk_empty_or_overflowing_bbox_skips(bx):
    e = Emu(40)
    rec = e.virtualalloc({RR.SNAP_BIG: 0x04000000})
    w32(e.uc, RR.SNAPBUF, PLANE)
    w32(e.uc, RR.CAP, 0xFFFFFFFF)                           # even an unbounded plane: the bbox itself is refused
    _stage_bx(e.uc, *bx)
    assert _snapchk(e) == 0 and r32(e.uc, rec) == 0


# ============================================================================== 3. t_dl_bmxt + t_dl_snapchk
def _bmxt_rig(g=40, w=400, h=400, clip=(150, 100, 300, 300)):
    e = Emu(g)
    uc = e.uc
    w32(uc, AD.G_DL_EXEC, 1)
    uc.mem_write(BUF, b"\0" * 0x600)
    w32(uc, BUF + 0x54, DATA)
    w32(uc, BUF + 0x80, w)
    w32(uc, BUF + 0x84, -h)
    w32(uc, BUF + 0x4A8, w)
    for i, v in enumerate(clip):
        w32(uc, BUF + 0x20 + 4 * i, v)
    uc.mem_write(DATA, b"\x55" * (w * h))
    e.virtualalloc({RR.SNAP_BIG: 0, RR.SNAP_SMALL: PLANE})  # t_rw_init_leave's 4 MB failed; so does ours
    rec = STUB + 0x900
    inside = DATA + 150 * w + 160                           # in the clip and the bbox
    outside = DATA + 150 * w + 130                          # in the bbox, left of the clip: restored
    uc.mem_write(AD.HOLLOWFLAT, asm(f"inc dword ptr [{rec:#x}]\n mov byte ptr [{inside:#x}], 0xEE\n"
                                    f"mov byte ptr [{outside:#x}], 0xEE\n ret 8", AD.HOLLOWFLAT))
    uc.mem_write(AD.BOX_SPRITE, asm(f"inc dword ptr [{rec + 4:#x}]\n mov eax, dword ptr [esp+4]\n"
                                    f"mov dword ptr [{rec + 8:#x}], eax\n ret 8", AD.BOX_SPRITE))
    e.guard_watch()
    return e, rec, inside, outside


def _bmxt(e, rect):
    rp = BUF + 0x800
    for i, v in enumerate(rect):
        w32(e.uc, rp + 4 * i, v)
    uc = e.call(AD.PCAVE2 + 0x22680, args=(rp, 0xD5A0), ecx=BUF, esi=0x1111, edi=0x2222, ebx=0x3333)
    assert uc.reg_read(UC_X86_REG_ESP) == SP0
    assert (uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI), uc.reg_read(UC_X86_REG_EBX)) == (0x1111, 0x2222, 0x3333)
    return rp


def test_fallback_oversized_frame_never_overruns():
    e, rec, _inside, _outside = _bmxt_rig()
    rp = _bmxt(e, (10, 10, 390, 390))                       # bbox (8, 8, 394, 394): 148,996 B > 64 KB
    assert r32(e.uc, RR.SNAPBUF) == PLANE and r32(e.uc, RR.CAP) == RR.SNAP_SMALL      # the fallback plane
    assert e.guard_writes == []                             # nothing outside the 64 KB plane
    assert r32(e.uc, rec) == 0 and r32(e.uc, rec + 4) == 1 and r32(e.uc, rec + 8) == rp   # native draw, rect as given
    assert r32(e.uc, AD.G_FC_EXACT) == 0


def test_fallback_fitting_frame_keeps_the_snapshot_path():
    e, rec, inside, outside = _bmxt_rig()
    _bmxt(e, (120, 120, 200, 200))                          # bbox 86 x 86 = 7,396 B
    assert e.guard_writes == []
    assert r32(e.uc, rec) == 1 and r32(e.uc, rec + 4) == 0
    assert bytes(e.uc.mem_read(inside, 1)) == b"\xEE" and bytes(e.uc.mem_read(outside, 1)) == b"\x55"
    # a later oversized frame, same plane: native, no overrun
    _bmxt(e, (0, 0, 400, 400))
    assert e.guard_writes == [] and r32(e.uc, rec + 4) == 1


def test_mutant_without_the_bound_overruns():
    """Kill check: the same oversized frame with the bound disabled (cap forced huge) writes past the plane -- what
    the shipped 36698ad5 t_dl_bmxt did with its unchecked 64 KB fallback."""
    e, rec, _inside, _outside = _bmxt_rig()
    w32(e.uc, RR.SNAPBUF, PLANE)
    w32(e.uc, RR.CAP, 0x7FFFFFFF)
    _bmxt(e, (10, 10, 390, 390))
    assert r32(e.uc, rec) == 1 and len(e.guard_writes) > 0


@pytest.mark.parametrize("rect", ((500, 10, 600, 100), (-100, 10, -20, 100), (10, 600, 100, 700)))
def test_frame_off_the_buffer_draws_natively(rect):
    """An empty bbox (the frame wholly off the buffer) used to reach `rep movsb` with a negative count."""
    e, rec, _inside, _outside = _bmxt_rig()
    _bmxt(e, rect)
    assert r32(e.uc, rec) == 0 and r32(e.uc, rec + 4) == 1 and e.guard_writes == []


# ============================================================================== 4. t_rw_br1
@pytest.mark.parametrize("g", (16, 17, 22, 25, 40))
def test_br1_wrapper(g):
    e = Emu(g)
    uc = e.uc
    rec = STUB + 0xA00
    uc.mem_write(RR.T_DL_BMXT, asm(
        f"inc dword ptr [{rec:#x}]\n mov eax, dword ptr [esp+4]\n mov dword ptr [{rec + 4:#x}], eax\n"
        f"mov eax, dword ptr [esp+8]\n mov dword ptr [{rec + 8:#x}], eax\n mov dword ptr [{rec + 0xC:#x}], ecx\n"
        "mov ecx, 0x99999\n mov eax, 0x88888\n mov edx, 0x77777\n ret 8", RR.T_DL_BMXT))
    uc.mem_write(RR.T_RW_RESTRIPE, asm(
        f"inc dword ptr [{rec + 0x10:#x}]\n mov eax, dword ptr [esp+4]\n mov dword ptr [{rec + 0x14:#x}], eax\n"
        f"mov eax, dword ptr [esp+8]\n mov dword ptr [{rec + 0x18:#x}], eax\n"
        f"mov eax, dword ptr [esp+0xC]\n mov dword ptr [{rec + 0x1C:#x}], eax\n ret 0xC", RR.T_RW_RESTRIPE))
    uc = e.call(RR.VA["t_rw_br1"], args=(0x4444, 0x78DAC8), ecx=BUF, esi=0x1111, edi=0x2222, ebx=0x3333)
    assert uc.reg_read(UC_X86_REG_ESP) == SP0
    assert (uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI), uc.reg_read(UC_X86_REG_EBX)) == (0x1111, 0x2222, 0x3333)
    assert [r32(uc, rec + o) for o in (0, 4, 8, 0xC)] == [1, 0x4444, 0x78DAC8, BUF]
    if g > 16:
        assert [r32(uc, rec + o) for o in (0x10, 0x14, 0x18, 0x1C)] == [1, BUF, BUF + 0x20, 0x78DAC8]
    else:
        assert r32(uc, rec + 0x10) == 0


# ============================================================================== 5. pins
@pytest.fixture(scope="module")
def shipped():
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    symtab = ap.build_symbol_table(syms, caves)
    sites = {s["id"]: s for s in _s}
    out = {}
    for c in cave["contents"]:
        va = PC + int(c["offset"])
        out[c["id"]] = (va, bytes(ap.ByteTemplate(" ".join(str(c["bytes"]).split())).resolve(va, symtab)))
    return out, symtab, sites, ap


def test_yaml_is_the_assembler(shipped):
    contents, symtab, sites, ap = shipped
    for name, (off, _end) in RR.HELPERS.items():
        assert contents[name] == (PC + off, RR.assemble(name)), name
        assert symtab[name] == PC + off
    assert symtab["g_dl_snapcap"] == RR.CAP and symtab["t_dl_bmxt"] == RR.T_DL_BMXT
    assert symtab["t_rw_restripe"] == RR.T_RW_RESTRIPE and symtab["t_dl_snapchk"] == AD.T_DL_SNAPCHK
    L, _end, _names = AD.assemble_all()
    off, b = L["t_dl_bmxt"]
    assert PC + off == RR.T_DL_BMXT and len(b) == BMXT_LEN == AD.BMXT_LEN and contents["t_dl_bmxt"] == (PC + off, b)
    assert L["t_dl_tile_bg"][0] == 0x228E0                  # the layout after t_dl_bmxt did not move
    ring = sites["tech_page.research_ring"]
    assert int(ring["virtual_addr"]) == RR.RING_SITE
    assert bytes.fromhex(ring["original_bytes"].replace(" ", "")) == RR.RING_ORIG
    assert bytes(ap.ByteTemplate(ring["new_bytes"]).resolve(RR.RING_SITE, symtab)) == RR.ring_site_bytes()
    br1 = sites["frame_499328"]
    assert bytes(ap.ByteTemplate(br1["new_bytes"]).resolve(RR.BR1_SITE, symtab)) == (
        b"\xE8" + struct.pack("<i", RR.VA["t_rw_br1"] - (RR.BR1_SITE + 5)))


def test_only_two_writers_of_the_plane_pointer(shipped):
    """g_dl_snapcap = 0 means 't_rw_init_leave's 4 MB plane' -- sound only while t_rw_init_leave allocates exactly
    0x400000 and it and t_dl_snapchk are the only code that stores g_dl_snapbuf."""
    contents, symtab, _sites, _ap = shipped
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    from capstone import x86_const as X
    snap = symtab["g_dl_snapbuf"]
    writers = {}
    for name, (va, b) in contents.items():
        prev = []
        for ins in md.disasm(b, va):
            if (ins.mnemonic == "mov" and ins.operands and ins.operands[0].type == X.X86_OP_MEM
                    and ins.operands[0].mem.base == 0 and ins.operands[0].mem.index == 0
                    and ins.operands[0].mem.disp & 0xFFFFFFFF == snap):
                writers.setdefault(name, []).append(prev[-8:])
            prev.append(ins)
    assert set(writers) == {"t_rw_init_leave", "t_dl_snapchk"}
    (before,) = writers["t_rw_init_leave"]
    pushes = [i.op_str for i in before if i.mnemonic == "push"]
    assert pushes[-4:] == ["4", "0x3000", "0x400000", "0"] and RR.SNAP_BIG == 0x400000
