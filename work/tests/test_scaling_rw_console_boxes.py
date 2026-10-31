"""HQ report consoles, whole-painter emulation on the REAL BAKED BYTES (fix 4g, 2026-10-17).

The console chain (t_rw_immsum + CHAIN_ROWS, laws rw_console_box_inset / rw_tab_inset / rw_console_list_top) was
verified per row: each row's g = 16 value == the pristine immediate and its stored value == its OWN key's law.  A
self-consistent wrong key survived all of that (a console box row keyed S6 instead of C, an energy R w keyed 2*s(6)
instead of 2C: both 6 / 12 at g = 16, both stored exactly what their key says), and so did a builder that was never
put on the chain (the F6 SELECT FACTION TARGET buttons still on s(9) / s(0x12): channels 6/7 at 4K against the
mirror list's 5/5).  This module checks the OUTCOME instead of the rows:

1. the image is the real bake (patches.yaml applied to the pristine .bak by the production CLI);
2. t_rw_init_leave runs its own VirtualProtect bootstrap + walker under REAL page protections (.text R-X until a
   VirtualProtect stub opens the requested range), 3x (idempotent), and with each VP window DENIED (no fault, and no
   .text byte written when the DL window is refused -- fix 4g: the walker stored row 0x49BFCA into that window
   unconditionally and faulted);
3. every console painter (labs / energy / ops / projects / sat attack + survey / units / score / intel) runs on the
   walked image with engine calls stubbed; every content box it draws must sit at region +- C on all four sides
   (C = rw_console_box_inset), half-open, stacked boxes s(2) apart, the d5a0 -> box channels s(2) on L / R / T and
   the left / right panels' channels equal;
4. the three console button lists (F6 faction / satellite target, F7 unit commands; ReportIf_activate builders)
   sit one step inside their body box on L / R / T: channel s(2) on each side, identical across the three lists.

g in {17, 18, 19, 20, 22, 25, 28, 30, 33, 36, 40} over 4 measured + 3 random region pairs.  `sweep(path, gs)` is
importable so a mutated copy of the bake can be checked (the mutation kills are recorded in the fix 4g report).

Pixel moves of the chain against the pre-chain bake (content box, s(6) / W - s(0xC) drawn inclusive -> C half-open):
4K (g40) L/T 1 px OUT, R/B unchanged; 1920x1080 (g22) L/T unchanged, R/B 1 px IN; 1600x1200 (g25) all four 1 px IN.
"""
from __future__ import annotations

import functools
import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn")
pytest.importorskip("capstone")
pefile = pytest.importorskip("pefile")

import capstone  # noqa: E402
from unicorn import (  # noqa: E402
    UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_INTR, UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE_PROT, UC_MODE_32, UC_PROT_ALL,
    UC_PROT_EXEC, UC_PROT_READ, Uc, UcError,
)
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

s = SL.scale_px
G_ADDR = 0x668740
RI, RW = 0x885F38, 0x876478
PCAVE2 = 0xA0C000
BOX = 0x5E2DD3                      # Buffer_box_sprite (-> thunk_hud_boxframe at g > 16: INCLUSIVE)
BOX_BODY = 0x5E2DD8                 # its body past the 5-push prologue: the console bypasses' native (half-open) draw
TEXT_LO, TEXT_HI = 0x401000, 0x668000
IAT_LOADLIB, IAT_GETPROC = 0x669120, 0x669124
VP_STUB = 0x70000000
D528, D5A0 = 0x78D528, 0x78D5A0
R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
     "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}
PAINTERS = {"labs": (0x4A7000, 0x4A842F), "energy": (0x4A84A0, 0x4A9017), "ops": (0x4A9050, 0x4A9F85),
            "projects": (0x4AA0B0, 0x4AA921), "sat": (0x4AA970, 0x4AB54B), "units": (0x4AB600, 0x4ABE24),
            "score": (0x4ABE70, 0x4AC127), "intel": (0x4AC140, 0x4AC9A0)}
# ReportIf_activate's three console button-list builders: (name, start, stop, panel field, extra regs, body-box site)
BUTTON_LISTS = (("faction", 0x4A574D, 0x4A5776, 0x20, {}, 0x4AABDE),          # F6 SELECT FACTION TARGET (left)
                ("satellite", 0x4AB28E, 0x4AB2AC, 0x30, {"ebx": RI + 0x30}, 0x4AB1B4),   # F6 SELECT SATELLITE TARGET
                ("unit_cmd", 0x4A54FD, 0x4A5522, 0x30, {}, 0x4ABD0A))          # F7 AUTOMATE UNITS
# content boxes (d528 / d5a0, inside the panel regions) each painter draws: a painter that stops drawing (or an
# emulation that silently stops early) must not pass as "no violation"
EXPECTED_BOXES = {("labs", False): 4, ("energy", False): 4, ("ops", False): 3, ("projects", False): 3, ("sat", False): 4,
                  ("units", False): 4, ("score", False): 2, ("intel", False): 4, ("sat", True): 2}
GS = (17, 18, 19, 20, 22, 25, 28, 30, 33, 36, 40)
_rng = random.Random(11)
REGIONS = [((6, 886, 382, 1192), (1217, 886, 1593, 1192)), ((650, 1690, 1252, 2148), (2588, 1690, 3190, 2148)),
           ((5, 800, 343, 1075), (1575, 800, 1915, 1075)), ((4, 520, 245, 764), (778, 520, 1020, 764))]
for _ in range(3):
    _L, _T, _W, _H = _rng.randrange(0, 50), _rng.randrange(300, 1400), _rng.randrange(231, 720), _rng.randrange(231, 520)
    _R0 = _rng.randrange(_L + _W + 300, _L + _W + 2200)
    REGIONS.append(((_L, _T, _L + _W, _T + _H), (_R0, _T, _R0 + _W, _T + _H)))
_md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


# ---- the image --------------------------------------------------------------------------------------------------
class Img:
    def __init__(self, path):
        pe = pefile.PE(str(path))
        self.IB = pe.OPTIONAL_HEADER.ImageBase
        self.size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        self.secs = [(self.IB + sc.VirtualAddress, sc.get_data()[:sc.Misc_VirtualSize or sc.SizeOfRawData])
                     for sc in pe.sections]
        doc = ap._yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
        self.sym = dict(ap.build_symbol_table(doc["symbols"], doc["code_caves"]))
        flat = bytearray(self.size)
        for a, d in self.secs:
            flat[a - self.IB:a - self.IB + len(d)] = d
        self.flat = bytes(flat)

    def read(self, va, n):
        return self.flat[va - self.IB:va - self.IB + n]

    @functools.lru_cache(maxsize=None)
    def retn(self, va):
        """callee cleanup: the imm of the first `ret` on a linear sweep from the entry (tail jumps followed)."""
        if not (self.IB <= va < self.IB + self.size):
            return 0
        for ins in _md.disasm(self.read(va, 0x4000), va):
            if ins.mnemonic == "ret":
                return int(ins.op_str, 16) if ins.op_str else 0
            if ins.mnemonic == "jmp" and ins.op_str.startswith("0x"):
                t = int(ins.op_str, 16)
                if not (va <= t < va + 0x4000):
                    return self.retn(t)
        return 0

    def init_leave_span(self):
        """(entry, address after its `call t_rw_immsum`)."""
        il, walker = self.sym["t_rw_init_leave"], self.sym["t_rw_immsum"]
        code = self.read(il, 0x200)
        hits = [il + i + 5 for i in range(len(code) - 5)
                if code[i] == 0xE8 and (il + i + 5 + struct.unpack_from("<i", code, i + 1)[0]) & 0xFFFFFFFF == walker]
        assert len(hits) == 1, hits
        return il, hits[0]


def _map(img, flat=None):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(img.IB, img.size)
    uc.mem_write(img.IB, flat if flat is not None else img.flat)
    uc.mem_map(0x200000, 0x100000)                      # stack
    return uc


def walk(img, g, runs=1, deny=()):
    """t_rw_init_leave's bootstrap + walker under real page protections. Returns (image bytes after, VP calls, faults)."""
    uc = _map(img)
    uc.mem_protect(TEXT_LO, TEXT_HI - TEXT_LO, UC_PROT_READ | UC_PROT_EXEC)
    uc.mem_map(VP_STUB, 0x1000)
    uc.mem_write(VP_STUB, b"\xB8\x01\x00\x00\x00\xC2\x04\x00")              # LoadLibraryA -> 1
    uc.mem_write(VP_STUB + 0x10, b"\xB8\x20\x00\x00\x70\xC2\x08\x00")       # GetProcAddress -> VP_STUB+0x20
    uc.mem_write(VP_STUB + 0x20, b"\xB8\x01\x00\x00\x00\xC2\x10\x00")       # VirtualProtect (hooked)
    uc.mem_write(IAT_LOADLIB, struct.pack("<I", VP_STUB))
    uc.mem_write(IAT_GETPROC, struct.pack("<I", VP_STUB + 0x10))
    vps, faults = [], []

    def vp(u, addr, size, _ud):
        if addr != VP_STUB + 0x20:
            return
        esp = u.reg_read(UC_X86_REG_ESP)
        a, n, prot, _old = struct.unpack("<4I", u.mem_read(esp + 4, 16))
        vps.append((a, n, prot))
        if a in deny:                                                         # VirtualProtect fails
            u.reg_write(UC_X86_REG_EAX, 0)
            u.reg_write(UC_X86_REG_ESP, esp + 0x14)
            u.reg_write(UC_X86_REG_EIP, struct.unpack("<I", u.mem_read(esp, 4))[0])
            return
        lo, hi = a & ~0xFFF, (a + n + 0xFFF) & ~0xFFF
        u.mem_protect(lo, hi - lo, UC_PROT_ALL)

    uc.hook_add(UC_HOOK_CODE, vp, begin=VP_STUB, end=VP_STUB + 0x30)
    # the bail path leaves through `jmp [g_rw_ret]` (init_report_screen's swapped return): trap it
    uc.mem_write(VP_STUB + 0x40, b"\xF4")
    uc.mem_write(img.sym["g_rw_ret"], struct.pack("<I", VP_STUB + 0x40))
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s_, d: u.emu_stop(), begin=VP_STUB + 0x40, end=VP_STUB + 0x40)

    def bad(u, access, addr, size, value, _ud):
        faults.append((hex(addr), hex(u.reg_read(UC_X86_REG_EIP))))
        return False

    uc.hook_add(UC_HOOK_MEM_WRITE_PROT | UC_HOOK_MEM_UNMAPPED, bad)
    uc.mem_write(G_ADDR, struct.pack("<i", g))
    il, stop = img.init_leave_span()
    for _ in range(runs):
        uc.reg_write(UC_X86_REG_ESP, 0x2F0000)
        try:
            uc.emu_start(il, stop, count=5_000_000)
        except UcError as ex:
            return None, vps, faults or [str(ex)]
    return bytes(uc.mem_read(img.IB, img.size)), vps, faults


def stored_line_h(img, uc, g):
    """Run t_rw_init_leave's line-height block on `uc` -- from its `mov edx, 15` (RW_LINE_H_NATIVE) through the
    HD scaling to the `mov [RI+0x1C], edx` store -- and return what it stored at RI+0x1C."""
    il = img.sym["t_rw_init_leave"]
    code = img.read(il, 0x800)
    store = bytes.fromhex("89 15") + struct.pack("<I", RI + 0x1C)          # mov dword ptr [RI+0x1C], edx
    st = code.find(store)
    lo = code.rfind(bytes.fromhex("BA") + struct.pack("<I", 15), 0, st)       # mov edx, 15
    assert st > 0 and lo >= 0 and code.count(store) == 1
    uc.mem_write(G_ADDR, struct.pack("<i", g))
    uc.mem_write(RI + 0x1C, struct.pack("<i", -1))
    uc.reg_write(UC_X86_REG_ESP, 0x2F0000)
    uc.emu_start(il + lo, il + st + 6, count=1000)
    return struct.unpack("<i", bytes(uc.mem_read(RI + 0x1C, 4)))[0]


class Painter:
    """One console painter / builder run on a walked image: engine code stubbed with the callee's own cleanup, box
    draws recorded (va, renderer, params, rect)."""

    def __init__(self, img, flat, g):
        self.img, self.g = img, g
        self.uc = uc = _map(img, flat)
        uc.mem_write(G_ADDR, struct.pack("<i", g))
        uc.mem_map(0xDEAD0000, 0x1000)
        uc.mem_write(0xDEAD0000, b"\xF4")
        self.box = {BOX: "hud_boxframe"}
        for n in ("t_rwk_boxforce", "t_rw_rowframe", "t_rwk_boxhalf", "t_rw_backdrop"):
            if n in img.sym:
                self.box[img.sym[n]] = n
        self.draws, self.allow, self.fault = [], (), None

        def unm(u, access, addr, size, value, _ud):
            try:
                u.mem_map(addr & ~0xFFF, 0x1000)
            except UcError:
                return False
            return True

        uc.hook_add(UC_HOOK_MEM_UNMAPPED, unm)

        def intr(u, intno, _ud):                     # #DE: a stubbed engine call returned the 0 a painter divides by
            eip = u.reg_read(UC_X86_REG_EIP)
            ins = next(_md.disasm(bytes(u.mem_read(eip, 16)), eip), None)
            if ins is None or ins.mnemonic not in ("div", "idiv"):     # (unicorn reports a repeated #DE as 8)
                self.fault = (intno, eip)
                u.emu_stop()
                return
            u.reg_write(UC_X86_REG_EAX, 0)
            u.reg_write(UC_X86_REG_EDX, 0)
            u.reg_write(UC_X86_REG_EIP, eip + ins.size)

        uc.hook_add(UC_HOOK_INTR, intr)

    def rd(self, a, n=1):
        return struct.unpack("<%di" % n, bytes(self.uc.mem_read(a, 4 * n)))

    def _ret(self, n):
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        self.uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", self.uc.mem_read(esp, 4))[0])
        self.uc.reg_write(UC_X86_REG_ESP, esp + 4 + n)

    def _code(self, uc, addr, size, _ud):
        if addr == BOX_BODY:                         # a prologue-replay bypass (`push ecx/ebx/ebp/esi/edi; jmp`): native draw
            esp = uc.reg_read(UC_X86_REG_ESP)
            edi, esi, ebp, ebx, ecx = struct.unpack("<5I", uc.mem_read(esp, 20))
            for r_, v in (("edi", edi), ("esi", esi), ("ebp", ebp), ("ebx", ebx), ("ecx", ecx), ("esp", esp + 20)):
                uc.reg_write(R[r_], v)
            ra, rect, params = struct.unpack("<III", uc.mem_read(esp + 20, 12))
            self.draws.append((ra - 5, "native", params, self.rd(rect, 4)))
            uc.reg_write(UC_X86_REG_EAX, 0)
            self._ret(8)
            return
        if addr in self.box:
            esp = uc.reg_read(UC_X86_REG_ESP)
            ra, rect, params = struct.unpack("<III", uc.mem_read(esp, 12))
            self.draws.append((ra - 5, self.box[addr], params, self.rd(rect, 4)))
            uc.reg_write(UC_X86_REG_EAX, 0)
            self._ret(8)
            return
        if addr >= PCAVE2 or addr == 0xDEAD0000 or any(lo <= addr < hi for lo, hi in self.allow):
            return
        uc.reg_write(UC_X86_REG_EAX, 0)
        self._ret(self.img.retn(addr))

    def regions(self, regL, regR):
        self.uc.mem_write(RI + 0x20, struct.pack("<4i", *regL))
        self.uc.mem_write(RI + 0x30, struct.pack("<4i", *regR))
        self.uc.mem_write(RI + 0x40, struct.pack("<4i", 400, regL[1] + 210, 1200, regL[3]))
        self.uc.mem_write(RI + 0x50, struct.pack("<4i", 400, regL[1], 1200, regL[1] + 200))
        # the report line height is what the bake STORES (t_rw_init_leave's own block, run on this image), never
        # injected: a wrong store would move every lineH-derived box, so it is read back and pinned to its law
        lh = stored_line_h(self.img, self.uc, self.g)
        assert lh == SL.rw_line_h(15, self.g), (self.g, lh)

    def paint(self, name, survey=False):
        lo, hi = PAINTERS[name]
        self.allow = ((lo, hi),)
        self.uc.mem_write(RW + 0x9F04, struct.pack("<i", 0xD3C if survey else 0))   # sat: survey vs attack layout
        esp = 0x2F0000 - 4
        self.uc.mem_write(esp, struct.pack("<I", 0xDEAD0000))
        for k, v in dict(esp=esp, ecx=RI, esi=0, edi=0, ebx=0, ebp=0x2F8000).items():
            self.uc.reg_write(R[k], v)
        h = self.uc.hook_add(UC_HOOK_CODE, self._code)
        try:
            self.uc.emu_start(lo, 0xDEAD0000, count=400_000)
        finally:
            self.uc.hook_del(h)

    def build(self, start, stop, extra):
        self.uc.reg_write(UC_X86_REG_ESP, 0x2F0000)
        self.uc.reg_write(UC_X86_REG_ESI, RI)
        self.uc.reg_write(UC_X86_REG_EBP, 0x2F8000)
        for k, v in extra.items():
            self.uc.reg_write(R[k], v)
        self.uc.emu_start(start, stop, count=200)
        return self.rd(RI + 0xC, 3)                                   # x, y, w


@functools.lru_cache(maxsize=None)
def _walked(path, g):
    img = _img(path)
    flat, _vps, faults = walk(img, g)
    assert flat is not None and not faults, faults
    return flat


@functools.lru_cache(maxsize=None)
def _img(path):
    return Img(path)


def sweep_g(path, g, regions=REGIONS):
    """Every content-box / channel / pair / button-list violation at g on the bake at `path` (a list of strings)."""
    img, flat = _img(path), _walked(path, g)
    K, C, s2, s3 = SL.stroke_width(g), SL.rw_console_box_inset(g), s(2, g), s(3, g)
    bad = []
    for regL, regR in regions:
        for name, survey in [(n, False) for n in PAINTERS] + [("sat", True)]:
            p = Painter(img, flat, g)
            p.regions(regL, regR)
            try:
                p.paint(name, survey)
            except UcError as ex:
                bad.append(f"{name} g{g}: emulation {ex}")
                continue
            if p.fault:
                bad.append(f"{name} g{g}: emulation interrupt {p.fault}")
                continue
            chans, nbox = {}, 0
            for side, reg in (("L", regL), ("R", regR)):
                bx = [d for d in p.draws if reg[0] <= d[3][0] < reg[2] and d[2] in (D528, D5A0) and d[3][0] - reg[0] >= C]
                nbox += len(bx)
                if not bx:
                    continue
                for va, rn, _par, (l, t, r, b) in bx:
                    if rn == "hud_boxframe":
                        bad.append(f"{name}/{side} g{g} {va:#x}: drawn INCLUSIVE")
                    if l - reg[0] != C or reg[2] - r != C:
                        bad.append(f"{name}{'/survey' if survey else ''}/{side} g{g} {va:#x}: L/R inset "
                                   f"{l - reg[0]}/{reg[2] - r} != C {C} ({(l, t, r, b)} in {reg})")
                tops = sorted(bx, key=lambda d: d[3][1])
                if tops[0][3][1] - reg[1] != C:
                    bad.append(f"{name}/{side} g{g}: top inset {tops[0][3][1] - reg[1]} != C {C}")
                if not (name in ("ops", "projects") and side == "R") and reg[3] - tops[-1][3][3] != C:   # R: locator map below
                    bad.append(f"{name}/{side} g{g}: bottom inset {reg[3] - tops[-1][3][3]} != C {C}")
                if name != "ops":
                    for a, b2 in zip(tops, tops[1:]):
                        if b2[3][1] - a[3][3] != s2:
                            bad.append(f"{name}/{side} g{g}: stacked gap {b2[3][1] - a[3][3]} != s2 {s2}")
                ch = (bx[0][3][0] - (reg[0] + s3 + K), (reg[2] - s3 - K) - bx[0][3][2], tops[0][3][1] - (reg[1] + s3 + K))
                chans[side] = ch
                if set(ch) != {s2}:
                    bad.append(f"{name}/{side} g{g}: d5a0 -> box channels L/R/T {ch} != s2 {s2}")
            if nbox != EXPECTED_BOXES[(name, survey)]:
                bad.append(f"{name}{'/survey' if survey else ''} g{g}: {nbox} content boxes drawn, expected "
                           f"{EXPECTED_BOXES[(name, survey)]}")
            if "L" in chans and "R" in chans and chans["L"] != chans["R"]:
                bad.append(f"{name} g{g}: left / right panel channels differ {chans}")
        # the button lists: one step inside their body box (half-open, stroke K) on L / R / T, the same in every list
        p = Painter(img, flat, g)
        p.regions(regL, regR)
        p.paint("sat")
        bodies = {d[0]: d[3] for d in p.draws}
        p.paint("units")
        bodies.update({d[0]: d[3] for d in p.draws})
        seen = {}
        for lname, start, stop, field, extra, body_site in BUTTON_LISTS:
            q = Painter(img, flat, g)
            q.regions(regL, regR)
            x, y, w = q.build(start, stop, extra)
            bl, bt, br, _bb = bodies[body_site]
            ch = (x - (bl + K), (br - K) - (x + w), y - (bt + K))
            seen[lname] = ch
            if ch != (s2, s2, s2):
                bad.append(f"{lname} buttons g{g}: channels L/R/T {ch} != s2 {s2} (body {bodies[body_site]}, x {x} y {y} w {w})")
        if len(set(seen.values())) != 1:
            bad.append(f"button lists g{g}: channels differ between lists {seen}")
    return bad


def sweep(path, gs=GS):
    return [m for g in gs for m in sweep_g(path, g)]


# ---- fixtures / tests -------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def baked(baked_exe):
    return str(baked_exe)


@pytest.mark.parametrize("g", GS)
def test_console_boxes_channels_and_pairs(baked, g):
    bad = sweep_g(baked, g)
    assert not bad, "\n".join(bad[:40])


@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_walker_vp_denied_and_idempotent(baked, g):
    """Each VirtualProtect window refused in turn: no fault and no .text byte written (the DL window refused =
    t_dl_immfix wrote no HD row, so t_rw_immsum must not store either; the rw window refused = t_rw_init_leave bails
    before the walker).  Both granted: the walk is idempotent over 3 runs and touches every chain site."""
    img = _img(baked)
    baked_text = img.read(TEXT_LO, TEXT_HI - TEXT_LO)
    for deny in ((0x429000,), (0x49C000,), (0x429000, 0x49C000)):
        flat, vps, faults = walk(img, g, deny=deny)
        assert flat is not None and not faults, (deny, faults)
        assert flat[TEXT_LO - img.IB:TEXT_HI - img.IB] == baked_text, deny
    once, vps, faults = walk(img, g)
    assert once is not None and not faults
    assert sorted({a for a, _n, _p in vps}) == [0x429000, 0x49C000]
    thrice, _v, faults = walk(img, g, runs=3)
    assert thrice is not None and not faults
    assert once[TEXT_LO - img.IB:TEXT_HI - img.IB] == thrice[TEXT_LO - img.IB:TEXT_HI - img.IB]
    import assemble_rw as AR                                         # noqa: E402  (the table the bake carries)
    for site, w, key, mult, lbl in AR.CHAIN_ROWS:
        got = struct.unpack("<b" if w == 1 else "<i", once[site - img.IB:site - img.IB + w])[0]
        want = mult * (s(6, g) if key == "S6" else SL.rw_sum_law(key, g))
        assert got == want, (hex(site), lbl, got, want)


def test_s6_key_is_the_energy_canvas_only():
    """S6 (plain s(6)) is not a chain law: only the two ReportWin_draw_energy canvas rects may carry it -- a console
    box keyed S6 equals C at g = 16 and slips past every per-row test (the content-box sweep above catches it)."""
    import assemble_rw as AR                                         # noqa: E402
    assert {site for site, _w, key, *_ in AR.CHAIN_ROWS if key == "S6"} == AR.S6_SITES == {0x49BFCA, 0x49CC25}
    assert AR.DL_VP_LO <= 0x49BFCA < AR.DL_VP_HI == AR.VP_PAGE <= 0x49CC25   # one in the DL walker's window (fix 4g)
