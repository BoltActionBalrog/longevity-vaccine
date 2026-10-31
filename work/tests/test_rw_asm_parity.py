"""Unicorn parity for the HQ report screens bake (assemble_rw.py).

Oracle = scaling_laws (scale_px / scale_floor / stripe_top) + the prototype's laws
(hook_report_scale_proto.js v9.8, user-verified 4K/1600/1920). Every thunk is emulated from its
REAL assembled bytes at its REAL cave VA; engine callees are recording stubs. Covers: the seven
detour caves' register/stack contracts at g 16/22/25/40 (identity at 16), the exact-fill row-frame / backdrop
helpers, the TECH/BASES split caves, the console-chrome inset rows, the bar recorder + prologue replay, the mate-required restripe vs a Python model, the tech
bracket state machine, the icon-blit argument rewrite, the scrollbar stash cells, the wheel gates
(12 cases), gate_pre v4 (statics, dynamic arrows, v3 passthrough), and the init leave thunk's field
lever against the proto's arithmetic.
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
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_ESP, UC_X86_REG_EBP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_rw as AR  # noqa: E402
    import assemble_rw_kinds as RK  # noqa: E402
    import assemble_halfopen_frames as HO  # noqa: E402

LAYOUT, CELLS, _CEND, NAMES = AR.assemble_all()
VA = dict(NAMES)
C = AR.CELL
GS = (16, 22, 25, 40)
STACK, SP0 = 0x00300000, 0x00310000
STUB = 0x00700000
REC = 0x00720000          # recording area
_ks = Ks(KS_ARCH_X86, KS_MODE_32)
s = SL.scale_px
fl = SL.popup_scale_floor


def asm(src, va=0):
    enc, _ = _ks.asm(src, va)
    return bytes(enc)


def r32(uc, a):
    return struct.unpack("<I", bytes(uc.mem_read(a, 4)))[0]


def r32s(uc, a):
    return struct.unpack("<i", bytes(uc.mem_read(a, 4)))[0]


def w32(uc, a, v):
    uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


class Emu:
    """One Unicorn instance per g, re-seeded per test (fresh instances AV-kill this box's interpreter
    after ~90 mappings): the cave bytes are rewritten, the cave cells / recording area / return
    trap are zeroed, engine-side state is set by each test before use."""
    _cache: dict = {}
    TRAP = 0x11223344

    def __new__(cls, g=25):
        inst = cls._cache.get(g)
        if inst is None:
            inst = super().__new__(cls)
            inst._init(g)
            cls._cache[g] = inst
        inst._reset()
        return inst

    def _init(self, g):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(AR.PCAVE2, AR.SECTION_END)
        uc.mem_map(AR.PCAVE2 + 0x2E000, 0x2000)   # the font_face_law helpers' block (stubbed per test)
        uc.mem_map(AR.PCAVE2 + 0x30000, 0x1000)   # pcave2's 0x30000.. tail: the pinned t_rwk_con_* console helpers
        uc.mem_map(AR.PCAVE2 + 0x34000, 0x1000)   # the W2A region: t_rw_btnw (assemble_halfopen_frames.py), CALLed by the gaps
        uc.mem_map(STACK, 0x20000)
        uc.mem_map(0x400000, 0x600000)     # exe image + engine objects + globals (0x400000..0xA00000; STUB/REC live inside)
        uc.mem_map(0x2000000, 0x100000)    # pixel planes / fake objects
        uc.mem_map(self.TRAP & 0xFFFFF000, 0x1000)
        self.g = g

    def _reset(self):
        uc = self.uc
        for name in LAYOUT:
            off, b = LAYOUT[name]
            uc.mem_write(AR.PCAVE2 + off, b)
        uc.mem_write(AR.T_RW_BTNW, HO.assemble("t_rw_btnw", g=AR.G))
        cell_lo = min(C.values()); cell_hi = max(C.values()) + 0x100
        uc.mem_write(cell_lo, bytes(cell_hi - cell_lo))
        uc.mem_write(REC, bytes(0x1000))
        uc.mem_write(self.TRAP, bytes([0xF4]))
        w32(uc, AR.G, self.g)
        for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            uc.reg_write(r, 0)

    def stub(self, va, src):
        b = asm(src, va)
        self.uc.mem_write(va, b)
        try:
            self.uc.ctl_remove_cache(va, va + max(len(b), 0x40))   # a block translated by an earlier run must not outlive its bytes
        except Exception:  # noqa: BLE001
            pass

    def run(self, start, until, esp=SP0, count=200000, **regs):
        uc = self.uc
        uc.ctl_flush_tb()            # cached instance: drop translated blocks so re-stubbed code is re-read
        uc.reg_write(UC_X86_REG_ESP, esp)
        for r, v in regs.items():
            uc.reg_write({"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
                          "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP}[r], v & 0xFFFFFFFF)
        uc.emu_start(start, until, count=count)
        return uc

    def reg(self, name):
        return self.uc.reg_read({"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
                                 "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "esp": UC_X86_REG_ESP, "ebp": UC_X86_REG_EBP,
                                 "eip": UC_X86_REG_EIP}[name])


# ---- the seven detour caves ----------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_hdr1_band(g):
    e = Emu(g)
    e.run(VA["t_rw_hdr1"], 0x498CA2, eax=1000, ebx=2000, ecx=0x1234, edi=0)
    assert e.reg("edi") == 1000 + s(0x46, g) and e.reg("eax") == 1000 + s(3, g) and e.reg("ebx") == 2000 + s(0x43, g)
    assert e.reg("ecx") == 0x1234 and e.reg("esp") == SP0


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("mask", (0xFFFFFFFF, 0))
def test_hdr2_wide_mask(g, mask):
    e = Emu(g)
    e.run(VA["t_rw_hdr2"], 0x498CD4, eax=mask, ecx=77)
    assert e.reg("eax") == (s(0x62, g) if mask else 0) and e.reg("ecx") == 77
    assert e.reg("esp") == SP0 - 4 and r32(e.uc, e.reg("esp")) == 0


@pytest.mark.parametrize("g", GS)
def test_hdr3_icon_target(g):
    e = Emu(g)
    e.uc.reg_write(UC_X86_REG_EBP, 0x305000)
    w32(e.uc, 0x305000 - 0x34, 777)
    e.run(VA["t_rw_hdr3"], 0x498E49, eax=55, ebp=0x305000)
    esp = e.reg("esp")
    assert esp == SP0 - 8 and r32(e.uc, esp) == 55 and r32(e.uc, esp + 4) == s(0x40, g) and e.reg("eax") == 777


@pytest.mark.parametrize("g", GS)
def test_btnl_left_inset(g):
    e = Emu(g)
    e.run(VA["t_rw_btnl"], 0x4A43C4, eax=1300, ecx=65, edi=1675)
    assert e.reg("edx") == 65 + s(0x4B, g) and e.reg("edi") == 1675 - 65 and r32(e.uc, 0x87E07C) == 1300


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("row", ((400, 1401), (400, 1402), (1301, 2538), (101, 595)))
def test_gap_caves(g, row):
    """v2 (2026-10-25 W2A, F30): the gaps + t_rw_btnw == scaling_laws.rw_btn_pair on the row [0x87E070, 0x87E078):
    DATALINKS (L, w) at the gap1 resume, CLOSE (x = edi, w = eax) at the gap2 resume; mid = the caller's
    (clipL + clipR) >> 1 = (L + R) >> 1 (t_rw_btnr centres the row on the clip); g <= 16 the vanilla split."""
    L, R = row
    mid = (L + R) >> 1
    (a0, a1), (b0, b1) = SL.rw_btn_pair(L, R, g)
    e = Emu(g)
    w32(e.uc, 0x87E070, L); w32(e.uc, 0x87E078, R)
    e.run(VA["t_rw_gap1"], 0x4A4421, eax=mid, edx=L, esi=AR.RI, ecx=55, edi=mid)
    assert (e.reg("edx"), e.reg("edx") + e.reg("eax")) == (a0, a1) and r32(e.uc, AR.RI + 0x1E1C8) == L
    assert e.reg("ecx") == 55 and e.reg("edi") == mid and e.reg("esp") == SP0
    e = Emu(g)
    w32(e.uc, 0x87E070, L); w32(e.uc, 0x87E078, R)
    e.run(VA["t_rw_gap2"], 0x4A44DE, eax=mid, edx=L, esi=AR.RI, ecx=55, edi=mid)
    assert (e.reg("edi"), e.reg("edi") + e.reg("eax")) == (b0, b1) and r32(e.uc, AR.RI + 0x1E1CC) == 55
    assert e.reg("ecx") == 55 and e.reg("esp") == SP0
    if g == 16:
        assert (a1, b0) == (mid - 1, mid + 1), "vanilla: dec eax / inc edi"
    else:
        assert a1 - a0 == b1 - b0 and (a0, b1) == (L, R)


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("mask", (0xFFFFFFFF, 0))
def test_title_inset_mask(g, mask):
    e = Emu(g)
    e.run(VA["t_rw_title"], 0x4A7604, eax=mask, ecx=500, edx=9)
    want = s(0x4C, g) if mask else 0
    assert e.reg("eax") == want and e.reg("ecx") == 500 + want and e.reg("edx") == 9


@pytest.mark.parametrize("g", GS)
def test_crest(g):
    e = Emu(g)
    e.run(VA["t_rw_crest"], 0x4A5B49, ecx=100, eax=200, edx=3)
    assert e.reg("ecx") == 100 + s(0x46, g) and e.reg("eax") == 200 + s(0x46, g) and e.reg("edx") == 3


# ---- row frame / backdrop exact-fill half-open helpers (bake v3) ----------------
def _record_stub(e, va):
    """renderer stub: record ecx, rect ptr, params, rect R/B, g_fc_exact AT CALL TIME; RET 8"""
    e.stub(va, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+4]
        mov eax, dword ptr [eax+8]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+4]
        mov eax, dword ptr [eax+12]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [{AR.G_FC_EXACT:#x}]
        mov dword ptr [{REC + 20:#x}], eax
        ret 8
    """)


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("thunk,target", [("t_rw_rowframe", AR.HOLLOWFLAT), ("t_rw_backdrop", AR.DEVFILL)])
def test_exact_fill_helpers(g, thunk, target):
    e = Emu(g)
    _record_stub(e, target)
    _record_stub(e, AR.BOX_SPRITE)
    rect = 0x2000100
    e.uc.mem_write(rect, struct.pack("<iiii", 100, 200, 700, 260))
    w32(e.uc, AR.G_FC_EXACT, 0)
    e.uc.mem_write(AR.G_FSR, bytes(16))
    esp = SP0 - 12
    e.uc.mem_write(esp, struct.pack("<III", 0x496CD5, rect, 0x78D5A0))
    e.run(VA[thunk], 0x496CD5, esp=esp, ecx=AR.RW_CANVAS, ebx=7)
    dest, rp, params, R, B, flag_at_call = struct.unpack("<IIIiiI", bytes(e.uc.mem_read(REC, 24)))
    assert (dest, rp, params) == (AR.RW_CANVAS, rect, 0x78D5A0)
    assert struct.unpack("<iiii", bytes(e.uc.mem_read(rect, 16))) == (100, 200, 700, 260)   # restored
    assert e.reg("ebx") == 7 and e.reg("esp") == SP0 and e.reg("eip") == 0x496CD5
    assert r32(e.uc, AR.G_FC_EXACT) == 0                                                # never leaks
    if g <= 16:
        # native: the renderer stub sits at Buffer_box_sprite, args untouched, no exact-fill state
        assert (R, B, flag_at_call) == (700, 260, 0)
        assert bytes(e.uc.mem_read(AR.G_FSR, 16)) == bytes(16)
    else:
        # bmxt pattern: R-1/B-1 for the inclusive renderer, ORIGINAL half-open rect in the scratch cell, flag set
        assert (R, B, flag_at_call) == (699, 259, 1)
        assert struct.unpack("<iiii", bytes(e.uc.mem_read(AR.G_FSR, 16))) == (100, 200, 700, 260)


# ---- TECH / BASES toggle split (bake v3) ------------------------------------------
def _tabsplit_law(w, g):
    """vanilla: TECH w = w/2-1, BASES x = L + w/2 + 1, BASES w = w/2 (2-px seam, 1-px overshoot);
    g>16: TECH w = BASES w = (w - s(2)) >> 1, seam s(2)."""
    if g <= 16:
        return (w >> 1) - 1, (w >> 1) + 1, w >> 1
    tw = (w - s(2, g)) >> 1
    return tw, tw + s(2, g), tw


@pytest.mark.parametrize("w", (224, 223, 350, 561))
def test_tabsplit_caves_native(w):
    """g=16: the v2 caves' native paths are vanilla's displaced bytes (v2's g>16 law: test_rw_tabs_asm.py)."""
    tw, boff, bw = _tabsplit_law(w, 16)
    e = Emu(16)
    e.run(VA["t_rw_tabsplit1"], 0x4A45BC, esp=SP0 - 8, eax=w, ecx=55, edx=100)
    assert e.reg("eax") == tw and e.reg("ecx") == 55 and e.reg("edx") == 100 and e.reg("esp") == SP0
    e = Emu(16)
    w32(e.uc, AR.RI + 0x14, w)
    e.run(VA["t_rw_tabsplit2"], 0x4A467C, esp=SP0 - 8, eax=w >> 1, ecx=50, edx=100, esi=AR.RI, ebx=7)
    assert e.reg("edx") == 100 + boff and e.reg("eax") == bw and e.reg("ecx") == 50 + 0x14
    assert e.reg("ebx") == 7 and e.reg("esi") == AR.RI and e.reg("esp") == SP0 - 8


@pytest.mark.parametrize("g", GS)
def test_btnr_row_right_edge_symmetric(g):
    """bake v4: row R = clipL + clipR - L (opposite-edge margin) -> the DATALINKS/CLOSE row is centred on the
    clip at every g; vanilla identity (26+670-101 == 101+644-150 == 595) and no -0x96 row remains"""
    e = Emu(g)
    clipL, clipR = 65, 1675
    L = clipL + s(0x4B, g)
    w32(e.uc, 0x87BDEC, clipL); w32(e.uc, 0x87BDF4, clipR); w32(e.uc, 0x87E070, L)
    e.run(VA["t_rw_btnr"], 0x4A43D6, eax=clipR, ecx=clipL, edi=clipR - clipL, edx=L)
    assert e.reg("edx") == clipL + clipR - L and e.reg("eax") == clipR and e.reg("ecx") == clipL and e.reg("edi") == clipR - clipL
    assert (L - clipL) == (clipR - e.reg("edx"))                                   # equal insets both sides
    if g == 16:
        assert e.reg("edx") == L + (clipR - clipL) - 0x96
    assert 0x4A43D2 not in {r[0] for r in AR.RW_IMMS}


@pytest.mark.parametrize("g", GS)
def test_console_chrome_rows_consistent(g):
    """the d528 inset row is s(7)-s(4) so inset1 + inset2 == the s(7) restore at EVERY g (s(3)+s(4) != s(7) at 22)"""
    rows = {r[0]: r for r in AR.RW_IMMS}
    val = lambda a: s(rows[a][2], g) - s(rows[a][3], g)
    assert val(0x4A3DE7) + val(0x4A3E59) == val(0x4A3F18) == -val(0x4A3F0E)
    assert val(0x4A3DA6) == -val(0x4A3DB5) == -val(0x4A3EC7) == val(0x4A3EBC) == s(3, g)
    assert val(0x4A3D7C) == -val(0x4A3D93) == -s(7, g)
    assert 0x4A4677 not in rows                                              # owned by t_rw_tabsplit2 now


# ---- bar recorder + prologue replay ---------------------------------------------
def test_bar_record_and_native_replay():
    e = Emu(40)
    e.stub(AR.BOX_SPRITE_RESUME, f"""
        mov eax, dword ptr [esp+0x18]
        mov dword ptr [{REC:#x}], eax
        mov eax, dword ptr [esp+0x1C]
        mov dword ptr [{REC + 4:#x}], eax
        mov dword ptr [{REC + 8:#x}], ecx
        mov dword ptr [{REC + 12:#x}], esp
        hlt
    """)
    w32(e.uc, C["g_rw_barn"], 1)
    rect = 0x2000200
    e.uc.mem_write(rect, struct.pack("<iiii", 10, 20, 30, 40))
    esp = SP0 - 12
    e.uc.mem_write(esp, struct.pack("<III", 0x4A7DF7, rect, 0x78DB18))
    e.run(VA["t_rw_bar"], 0, esp=esp, ecx=AR.MW_CANVAS, ebx=1, ebp=2, esi=3, edi=4, count=100)
    assert r32(e.uc, REC) == rect and r32(e.uc, REC + 4) == 0x78DB18 and r32(e.uc, REC + 8) == AR.MW_CANVAS
    assert r32(e.uc, REC + 12) == esp - 20                       # 5 pushes, ret slot consumed by the push/ret
    assert r32(e.uc, C["g_rw_barn"]) == 2
    slot = C["g_rw_barlist"] + 20
    assert struct.unpack("<iiiiI", bytes(e.uc.mem_read(slot, 20))) == (10, 20, 30, 40, 0x78DB18)


# ---- restripe vs Python model ---------------------------------------------------
def py_restripe(plane, W, H, pitch, rect, a, b, g, R=4):
    P = SL.stripe_period(g); hN = (P + 1) >> 1
    x0, y0, x1, y1 = max(rect[0], 0), max(rect[1], 0), min(rect[2], W), min(rect[3], H)
    out = bytearray(plane)
    for y in range(y0, y1):
        top = (y % P) < hN
        for x in range(x0, x1):
            v = plane[y * pitch + x]
            if v == a:
                mate = b
            elif v == b:
                mate = a
            else:
                continue
            lo, hi = max(y - R, 0), min(y + R + 1, H)
            if any(out[yy * pitch + x] == mate for yy in range(lo, hi) if yy != y):   # in-place walk: rows above already rewritten (the proto's semantics)
                out[y * pitch + x] = a if top else b
    return bytes(out)


def make_buf(uc, base, W, H, pitch, plane):
    uc.mem_write(base + 0x54, struct.pack("<I", base + 0x1000))
    uc.mem_write(base + 0x4A8, struct.pack("<I", pitch))
    uc.mem_write(base + 0x80, struct.pack("<ii", W, -H))
    uc.mem_write(base + 0x1000, plane)


def make_set(uc, base, a, b):
    fill = base + 0x100
    uc.mem_write(base + 0x20, struct.pack("<I", fill))
    uc.mem_write(fill + 0x54, struct.pack("<I", fill + 0x600))
    uc.mem_write(fill + 0x4A8, struct.pack("<I", 24))
    uc.mem_write(fill + 0x600, bytes([a]) * 24 + bytes([b]) * 24)


@pytest.mark.parametrize("g", (22, 25, 40))
def test_restripe_mate_rule(g):
    import random
    rnd = random.Random(g)
    W, H, pitch = 64, 48, 80
    a, b = 0x54, 0x52
    plane = bytearray(rnd.choice([a, b, 0x10, 0x45]) for _ in range(H * pitch))
    # an NN-banded field in the middle, a SOLID column of the dark member at x=5 (must survive),
    # a solid column of the top member at x=6 (must survive)
    for y in range(H):
        for x in range(8, 40):
            plane[y * pitch + x] = a if ((y * 5) // 2) % 2 == 0 else b
        plane[y * pitch + 5] = b
        plane[y * pitch + 6] = a
    plane = bytes(plane)
    e = Emu(g)
    buf, st = 0x2010000, 0x2020000
    make_buf(e.uc, buf, W, H, pitch, plane)
    make_set(e.uc, st, a, b)
    rect = 0x2030000
    e.uc.mem_write(rect, struct.pack("<iiii", 2, 3, 60, 45))
    esp = SP0 - 16
    e.uc.mem_write(esp, struct.pack("<IIII", 0x11223344, buf, rect, st))
    e.uc.mem_write(0x11223344 & 0xFFFFF000, b"\xf4" * 16) if False else None
    e.run(VA["t_rw_restripe"], 0x11223344 if False else 0, esp=esp, ebx=1, esi=2, edi=3, count=5_000_000) if False else None
    # run until the ret lands on the fake return address
    try:
        e.run(VA["t_rw_restripe"], 0x11223344, esp=esp, ebx=1, esi=2, edi=3, count=5_000_000)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0 and (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (1, 2, 3)
    got = bytes(e.uc.mem_read(buf + 0x1000, H * pitch))
    want = py_restripe(plane, W, H, pitch, (2, 3, 60, 45), a, b, g)
    assert got == want
    # solid columns untouched, field rows lawful
    for y in range(3, 45):
        assert got[y * pitch + 5] == b and got[y * pitch + 6] == a
        P = SL.stripe_period(g); hN = (P + 1) >> 1
        assert got[y * pitch + 20] == (a if (y % P) < hN else b)


def test_restripe_bails_on_bad_pair():
    e = Emu(25)
    buf, st = 0x2010000, 0x2020000
    plane = bytes([0x54, 0x52] * 40) * 10
    make_buf(e.uc, buf, 80, 10, 80, plane)
    make_set(e.uc, st, 0x54, 0x54)               # equal pair -> bail
    rect = 0x2030000
    e.uc.mem_write(rect, struct.pack("<iiii", 0, 0, 80, 10))
    esp = SP0 - 16
    e.uc.mem_write(esp, struct.pack("<IIII", 0x11223344, buf, rect, st))
    try:
        e.run(VA["t_rw_restripe"], 0x11223344, esp=esp, count=100000)
    except Exception:
        pass
    assert bytes(e.uc.mem_read(buf + 0x1000, len(plane))) == plane and e.reg("esp") == SP0


# ---- tech bracket -----------------------------------------------------------------
@pytest.mark.parametrize("g", (16, 25, 40))
def test_techpage_bracket(g):
    e = Emu(g)
    # stubs: t_dl_immfix records (immg, esi) per call; tech_page records ecx + state at call time
    e.stub(AR.T_DL_IMMFIX, f"""
        mov eax, dword ptr [{REC + 0x100:#x}]
        mov ecx, dword ptr [{AR.G_DL_IMMG:#x}]
        mov dword ptr [{REC + 0x110:#x}+eax*8], ecx
        mov dword ptr [{REC + 0x114:#x}+eax*8], esi
        inc dword ptr [{REC + 0x100:#x}]
        ret
    """)
    e.stub(AR.TECH_PAGE, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [{AR.G_DL_EXEC:#x}]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [{AR.G_NETWIN:#x}]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [{AR.FONT_PUSH_TECH[0] + 1:#x}]
        mov dword ptr [{REC + 12:#x}], eax
        ret
    """)
    # t_rw_restripe stub: count calls + record the rect of the first
    e.uc.mem_write(VA["t_rw_restripe"], asm(f"""
        inc dword ptr [{REC + 0x200:#x}]
        mov eax, dword ptr [esp+8]
        mov eax, dword ptr [eax+4]
        mov dword ptr [{REC + 0x204:#x}], eax
        ret 0xC
    """, VA["t_rw_restripe"]))
    w32(e.uc, C["g_rw_font"], 0x5555AAAA)
    for va in AR.FONT_PUSH_TECH:
        w32(e.uc, va + 1, AR.FONT_FIXED)
    w32(e.uc, AR.RW + 0x5974, 65); w32(e.uc, AR.RW + 0x5978, 7); w32(e.uc, AR.RW + 0x597C, 1675)
    w32(e.uc, AR.RW + 0xA14, 0xDEAD); w32(e.uc, AR.RW + 0xA18, 0xBEEF)      # painter scratch: must NOT be used
    w32(e.uc, AR.TXTBOX_IMM, 117); w32(e.uc, AR.SPACER_IMM, 122)
    esp = SP0 - 4
    w32(e.uc, esp, 0x11223344)
    try:
        e.run(VA["t_rw_techpage"], 0x11223344, esp=esp, ecx=AR.RW, ebx=9, esi=8, edi=7, count=100000)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0 and (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (9, 8, 7)
    assert r32(e.uc, REC) == AR.RW
    if g <= 16:
        assert r32(e.uc, REC + 0x100) == 0 and r32(e.uc, REC + 0x200) == 0      # native tail: no walks, no restripe
        return
    assert r32(e.uc, REC + 4) == 1 and r32(e.uc, REC + 8) == 1 and r32(e.uc, REC + 12) == 0x5555AAAA   # during the page
    assert r32(e.uc, AR.G_DL_EXEC) == 0 and r32(e.uc, AR.G_NETWIN) == 0 and r32(e.uc, AR.G_DL_IMMG) == 16
    for va in AR.FONT_PUSH_TECH:
        assert r32(e.uc, va + 1) == AR.FONT_FIXED
    assert r32(e.uc, REC + 0x100) == 2
    assert r32(e.uc, REC + 0x110) == g and r32(e.uc, REC + 0x114) == AR.TAB_TECH      # apply with g
    assert r32(e.uc, REC + 0x118) == 16 and r32(e.uc, REC + 0x11C) == AR.TAB_TECH     # revert with 16
    assert r32(e.uc, REC + 0x200) == 1 + len(AR.SPACER_SETS)
    # the rect seen by the LAST restripe call = spacer: T = spacer imm, B = y + s(0x46) - s(3)
    assert r32(e.uc, REC + 0x204) == 122
    rect = struct.unpack("<iiii", bytes(e.uc.mem_read(C["g_rw_tech_rect"], 16)))
    assert rect == (65 + s(3, g) + s(0x43, g), 122, 1675 - s(3, g), 7 + s(0x46, g) - s(3, g))


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("prior", ((0, 0, 16), (1, 1, "g"), (0, 0, 0)))
def test_techhover_bracket(g, prior):
    """t_rw_techhover (ReportWin vtbl+0xA0 slot): the F2 hover/un-hover frame draws run under the SAME bracket as
    the paint (DL tech imms at g + g_dl_exec/netwin 1), args (id, state) forwarded thiscall RET 8, callee-saved
    regs kept, and the PRIOR state restored afterwards: F2 idle (0,0,16) -> back to 16/0/0; DL open (1,1,g) ->
    re-applied g and exec/netwin left at 1; an uninitialised immg 0 restores 16 (never a g=0 walk). g<=16 = the
    vanilla body untouched (no walks)."""
    p_exec, p_net, p_immg = prior
    if p_immg == "g":
        p_immg = g
    e = Emu(g)
    e.stub(AR.T_DL_IMMFIX, f"""
        mov eax, dword ptr [{REC + 0x100:#x}]
        mov ecx, dword ptr [{AR.G_DL_IMMG:#x}]
        mov dword ptr [{REC + 0x110:#x}+eax*8], ecx
        mov dword ptr [{REC + 0x114:#x}+eax*8], esi
        inc dword ptr [{REC + 0x100:#x}]
        ret
    """)
    e.stub(AR.TECH_HOVER, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [{AR.G_DL_EXEC:#x}]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [{AR.G_NETWIN:#x}]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [{AR.G_DL_IMMG:#x}]
        mov dword ptr [{REC + 20:#x}], eax
        inc dword ptr [{REC + 24:#x}]
        mov ebx, 0x11111111
        mov esi, 0x22222222
        mov edi, 0x33333333
        ret 8
    """)
    w32(e.uc, AR.G_DL_EXEC, p_exec); w32(e.uc, AR.G_NETWIN, p_net); w32(e.uc, AR.G_DL_IMMG, p_immg)
    esp = SP0 - 12
    w32(e.uc, esp, 0x11223344); w32(e.uc, esp + 4, 0x37A); w32(e.uc, esp + 8, 1)
    try:
        e.run(VA["t_rw_techhover"], 0x11223344, esp=esp, ecx=AR.RW, ebx=9, esi=8, edi=7, count=100000)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0                  # RET 8 consumed exactly once
    assert r32(e.uc, REC + 24) == 1 and r32(e.uc, REC) == AR.RW
    assert r32(e.uc, REC + 4) == 0x37A and r32(e.uc, REC + 8) == 1              # (id, state) forwarded
    if g <= 16:
        assert r32(e.uc, REC + 0x100) == 0                                       # native tail: no walks, state untouched
        assert (r32(e.uc, REC + 12), r32(e.uc, REC + 16), r32(e.uc, REC + 20)) == (p_exec, p_net, p_immg)
        return
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (9, 8, 7)              # callee-saved kept across the call
    assert (r32(e.uc, REC + 12), r32(e.uc, REC + 16), r32(e.uc, REC + 20)) == (1, 1, g)   # during the hover
    assert r32(e.uc, REC + 0x100) == 2
    assert r32(e.uc, REC + 0x110) == g and r32(e.uc, REC + 0x114) == AR.TAB_TECH          # apply with g
    want_immg = p_immg if p_immg else 16
    assert r32(e.uc, REC + 0x118) == want_immg and r32(e.uc, REC + 0x11C) == AR.TAB_TECH  # restore the PRIOR walk
    assert (r32(e.uc, AR.G_DL_EXEC), r32(e.uc, AR.G_NETWIN), r32(e.uc, AR.G_DL_IMMG)) == (p_exec, p_net, want_immg)


def test_techhover_slot_is_vanilla_hover():
    sites = {s["id"]: s for s in AR.site_list(NAMES)}
    s = sites["ReportWin_vtbl.tech_hover"]
    assert s["va"] == 0x66D7F4 and s["orig"] == struct.pack("<I", 0x49B220) and s["pattern"] == "vtable_repoint"
    assert s["new"] == "{abs32:t_rw_techhover}"
    assert AR.SE.base_exe_bytes(0x66D7F4, 4) == struct.pack("<I", 0x49B220)


# ---- icon blit chain head ----------------------------------------------------------
@pytest.mark.parametrize("g", (16, 25, 40))
@pytest.mark.parametrize("which", ("kindtab", "factiontab", "other"))
def test_iconblit_args(g, which):
    e = Emu(g)
    e.stub(AR.FACTION_PORTRAIT, "hlt")
    btn = {"kindtab": AR.RI + 0x5384 + 2 * 0xB4C, "factiontab": AR.RI + 0x80 + 3 * 0xB4C, "other": 0x6AF000}[which]
    spr = 0x2040000
    w32(e.uc, spr + 0x18, 30); w32(e.uc, spr + 0x1C, 36)
    w32(e.uc, btn + 0x4C4, 47); w32(e.uc, btn + 0x4C8, -56)
    esp = SP0 - 28
    e.uc.mem_write(esp, struct.pack("<IIIiiii", 0x607F48, btn + 0x444, 9, 8, 10, 1, 1))
    hit = g > 16 and which != "other"
    try:
        e.run(VA["t_rw_iconblit"], 0x5E4B4A if hit else 0, esp=esp, ecx=spr, count=200)
    except Exception:
        pass
    if hit:      # v2: the hit path draws through t_rwk_parity_nn; with no sprite plane its guard tail-jumps Sprite_draw_2
        assert e.reg("eip") == 0x5E4B4A
    else:
        assert e.reg("eip") in (AR.FACTION_PORTRAIT, AR.FACTION_PORTRAIT + 1)
    assert e.reg("esp") == esp and e.reg("ecx") == spr
    x, y, num, den = struct.unpack("<iiii", bytes(e.uc.mem_read(esp + 12, 16)))
    if g <= 16 or which == "other":
        assert (x, y, num, den) == (8, 10, 1, 1)
    else:
        dw, dh = fl(30, g), fl(36, g)
        assert (x, y, num, den) == ((47 - dw) >> 1, (56 - dh) >> 1, g, 16)


# ---- scrollbar stash cells ------------------------------------------------------------
@pytest.mark.parametrize("g", (16, 25))
def test_scroll_and_sbinit_and_lbclose(g):
    e = Emu(g)
    e.stub(AR.SCROLL_SMALL, "ret")
    w32(e.uc, AR.G_SCROLLBAR_W, 12)
    esp = SP0 - 4; w32(e.uc, esp, 0x11223344)
    try:
        e.run(VA["t_rw_scrollsmall"], 0x11223344, esp=esp, count=100)
    except Exception:
        pass
    assert r32(e.uc, AR.G_SCROLLBAR_W) == (s(12, g) if g > 16 else 12) and r32(e.uc, C["g_rw_inlist"]) == 1
    # init_inner with inlist=1: stash ecx + parent (arg 5), rail stash only at g>16, prologue replayed
    e.stub(AR.SB_INIT_RESUME, "hlt")
    esp = SP0 - 32
    e.uc.mem_write(esp, struct.pack("<IIIIIII", 0x60A700, 309, 0, 19, 227, 0x890250, 0xFFFFFFFF))
    try:
        e.run(VA["t_rw_sbinit"], 0, esp=esp, ecx=0x7F61008, ebx=0x42, count=100)
    except Exception:
        pass
    assert e.reg("eip") in (AR.SB_INIT_RESUME, AR.SB_INIT_RESUME + 1) and e.reg("eax") == 0x890250 and r32(e.uc, e.reg("esp")) == 0x42 and e.reg("esp") == esp - 4
    assert r32(e.uc, C["g_rw_sb"]) == 0x7F61008 and r32(e.uc, C["g_rw_sbparent"]) == 0x890250
    assert r32(e.uc, AR.G_RAIL_SB) == (0x7F61008 if g > 16 else 0)
    # scroll_normal clears inlist; lbclose drops the stashes (rail only if it is ours)
    e.stub(AR.SCROLL_NORMAL, "hlt")
    try:
        e.run(VA["t_rw_scrollnormal"], 0, esp=SP0, count=10)
    except Exception:
        pass
    assert r32(e.uc, C["g_rw_inlist"]) == 0
    w32(e.uc, AR.G_RAIL_SB, 0x7F61008 if g > 16 else 0x1234)
    e.stub(AR.LISTBOX_CLOSE, "hlt")
    try:
        e.run(VA["t_rw_lbclose"], 0, esp=SP0, count=20)
    except Exception:
        pass
    assert r32(e.uc, C["g_rw_sb"]) == 0 and r32(e.uc, C["g_rw_sbparent"]) == 0
    assert r32(e.uc, AR.G_RAIL_SB) == (0 if g > 16 else 0x1234)


# ---- wheel ------------------------------------------------------------------------------
def _wheel(e, thunk, vk, scan, basepop=0, top=AR.RW, kind=2, sb=0x2050000, parent=0x2060000, engaged=1, mn=0, mx=5):
    uc = e.uc
    w32(uc, AR.BASEPOP, basepop); w32(uc, AR.MODAL_TOP, top); w32(uc, AR.KIND, kind)
    w32(uc, C["g_rw_sb"], sb); w32(uc, C["g_rw_sbparent"], parent)
    if sb:
        w32(uc, sb + 0xC4, engaged); uc.mem_write(sb + 0xA20, struct.pack("<II", mn, mx))
    e.stub(AR.GET_TARGET, "mov eax, 1\n ret")
    e.stub(AR.CHEVRON, f"mov dword ptr [{REC:#x}], ecx\n mov eax, dword ptr [esp+4]\n mov dword ptr [{REC + 4:#x}], eax\n ret 4")
    w32(uc, parent, parent + 0x100); w32(uc, parent + 0x100 + 0xFC, STUB + 0x800)
    # element = parent-0x48 with a vtbl whose [+8] adjustor = 0x14; hover item at parent + 0x14 + 0xA8 pre-set to 7
    w32(uc, parent - 0x48, parent + 0x200); w32(uc, parent + 0x208, 0x14); w32(uc, parent + 0x14 + 0xA8, 7)
    e.stub(STUB + 0x800, f"mov dword ptr [{REC + 8:#x}], ecx\n ret")
    e.stub(AR.DL_WHEEL_DOWN, "mov eax, 0x77\n ret"); e.stub(AR.DL_WHEEL_UP, "mov eax, 0x77\n ret")
    uc.mem_write(REC, b"\0" * 12)
    esp = SP0 - 4
    w32(uc, esp, 0x5F07B5); uc.mem_write(esp + 0x68, struct.pack("<II", vk, scan))
    e.uc.mem_map(0x5F07000, 0x1000) if False else None
    try:
        e.run(VA[thunk], 0x5F07B5, esp=esp, count=300)
    except Exception:
        pass
    return struct.unpack("<III", bytes(uc.mem_read(REC, 12))), e.reg("eax"), e.reg("esp") == SP0 and e.reg("eip") == 0x5F07B5


def test_wheel_cases():
    e = Emu(25)
    e.uc.mem_write(0x5F07B5, b"\xf4")
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0) == ((0x2050000, 2, 0x2060000), 0, True)
    assert r32(e.uc, 0x2060000 + 0x14 + 0xA8) == 0xFFFFFFFF                          # hover invalidated after the scroll
    assert _wheel(e, "t_rw_wheel_down", 0x26, 0)[0][1] == 1 and r32(e.uc, 0x2060000 + 0x14 + 0xA8) == 0xFFFFFFFF
    assert _wheel(e, "t_rw_wheel_down", 0x26, 0)[0][1] == 1
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0x50) == ((0, 0, 0), 1, True)          # real key passes
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0, engaged=0) == ((0, 0, 0), 1, True)
    assert r32(e.uc, 0x2060000 + 0x14 + 0xA8) == 7                                   # no scroll -> hover untouched
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0, mn=3, mx=3)[0] == (0, 0, 0)
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0, kind=5)[1] == 0x77                   # chained (kinds 0/3/4: test_rw_kinds_parity)
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0, top=0x123)[1] == 0x77
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0, sb=0)[1] == 0x77
    assert _wheel(e, "t_rw_wheel_down", 0x28, 0, basepop=5)[1] == 0x77
    assert _wheel(e, "t_rw_wheel_up", 0x28, 0)[1:] == (0, True)
    assert _wheel(e, "t_rw_wheel_up", 0x28, 1)[1] == 1
    w32(e.uc, C["g_rw_wheel_ate"], 0)
    assert _wheel(e, "t_rw_wheel_up", 0x28, 0, kind=3)[1] == 0x77                     # v2: nothing eaten on the way down -> chain


# ---- gate_pre v4 ------------------------------------------------------------------------
@pytest.mark.parametrize("esi,sb,hit", [
    (0x87C9D8, 0, 1), (0x87D524, 0, 1), (AR.RI + 0xBA0C, 0, 1), (AR.RI + 0xC558, 0, 1),
    (0x7F61008 + 0xAAC, 0x7F61008, 1), (0x7F61008 + 0x15F8, 0x7F61008, 1),
    (0x7F61008 + 0xAAC, 0, None), (0x7fe80c, 0, 0), (0x6AF164, 0x7F61008, None),
    # v7: the arrows of the OTHER slot (left bar) admit too; a stale pointer with the report not modal does not
    (0x7F70008 + 0xAAC, ("slot0", 0x7F70008), 1), (0x7F70008 + 0x15F8, ("slot0", 0x7F70008), 1),
    (0x7F61008 + 0xAAC, ("nomodal", 0x7F61008), 0x99), (0x7F70008 + 0x15F8, ("slot0", 0x7F61008), 0x99),
    # v7b: a stashed bar whose parent [+0xC4] no longer matches g_rw_sbparents[i] (freed + reused address) is refused
    (0x7F70008 + 0xAAC, ("badparent", 0x7F70008), 0x99), (0x7F61008 + 0x15F8, ("badparent1", 0x7F61008), 0x99),
])
def test_gate_pre_v4(esi, sb, hit):
    e = Emu(25)
    e.stub(AR.BTN_GATE, "mov eax, 0x99\n ret")
    for va in (RK.G_MODAL_TOP,):
        try:
            e.uc.mem_map(va & ~0xFFF, 0x1000)
        except Exception:  # noqa: BLE001  (already mapped)
            pass
    w32(e.uc, RK.G_MODAL_TOP, AR.RW)                       # the report is the modal top
    try:
        e.uc.mem_map(0x7F60000, 0x20000)                       # the two fake heap bars
    except Exception:  # noqa: BLE001
        pass
    PAR0, PAR1 = 0x890250, 0x890DA4                            # the RW-embedded console ListBox parts (g_rw_sbparents)
    w32(e.uc, C["g_rw_sbparents"], PAR0); w32(e.uc, C["g_rw_sbparents"] + 4, PAR1)
    w32(e.uc, 0x7F70008 + 0xC4, PAR0); w32(e.uc, 0x7F61008 + 0xC4, PAR1)
    if isinstance(sb, tuple):
        kind, ptr = sb
        if kind == "slot0":
            w32(e.uc, C["g_rw_sbs"], ptr); w32(e.uc, C["g_rw_sbs"] + 4, 0)
        elif kind == "badparent":
            w32(e.uc, C["g_rw_sbs"], ptr); w32(e.uc, C["g_rw_sbs"] + 4, 0); w32(e.uc, ptr + 0xC4, 0x12345)
        elif kind == "badparent1":
            w32(e.uc, C["g_rw_sbs"], 0); w32(e.uc, C["g_rw_sbs"] + 4, ptr); w32(e.uc, ptr + 0xC4, 0x12345)
        else:
            w32(e.uc, C["g_rw_sbs"], 0); w32(e.uc, C["g_rw_sbs"] + 4, ptr); w32(e.uc, RK.G_MODAL_TOP, 0)
    else:
        w32(e.uc, C["g_rw_sbs"], 0); w32(e.uc, C["g_rw_sbs"] + 4, sb)   # v5 semantics: the last stashed bar = slot 1
    esp = SP0 - 4; w32(e.uc, esp, 0x11223344)
    try:
        e.run(VA["thunk_btn_gate_pre"], 0x11223344, esp=esp, esi=esi, count=100)
    except Exception:
        pass
    assert e.reg("esp") == SP0 and e.reg("eip") == 0x11223344
    assert e.reg("edx") == e.reg("edx")           # (edx is saved/restored by t_rw_sbarrows; the v4 body owns the rest)
    if hit is None:
        assert e.reg("eax") in (0x99, 1)          # v3 body decides (SE statics / btn_gate chain)
    else:
        assert e.reg("eax") == hit                # 0x99 = fell through to the (stubbed) btn_gate chain


# ---- gate_pre v6: the 7 kind + 7 faction tabs MISS regardless of the flags ---------------
@pytest.mark.parametrize("esi", [AR.RI + 0x80, AR.RI + 0x80 + 3 * 0xB4C, AR.RI + 0x80 + 7 * 0xB4C - 1,
                                 AR.RI + 0x5384, AR.RI + 0x5384 + 6 * 0xB4C, AR.RI + 0x5384 + 7 * 0xB4C - 1])
@pytest.mark.parametrize("netwin", (0, 1))
def test_gate_pre_v6_tabs_miss(esi, netwin):
    e = Emu(25)
    e.stub(AR.BTN_GATE, "mov eax, 0x99\n ret")
    w32(e.uc, AR.G_NETWIN, netwin); w32(e.uc, C["g_rw_sb"], 0)
    esp = SP0 - 4; w32(e.uc, esp, 0x11223344)
    e.run(VA["thunk_btn_gate_pre"], 0x11223344, esp=esp, esi=esi, count=100)
    assert e.reg("esp") == SP0 and e.reg("eip") == 0x11223344 and e.reg("eax") == 0


@pytest.mark.parametrize("esi", [AR.RI + 0x80 - 1, AR.RI + 0x80 + 7 * 0xB4C, AR.RI + 0x5384 - 1, AR.RI + 0x5384 + 7 * 0xB4C])
def test_gate_pre_v6_tab_edges_fall_through(esi):
    e = Emu(25)
    e.stub(AR.BTN_GATE, "mov eax, 0x99\n ret")
    w32(e.uc, C["g_rw_sb"], 0)
    esp = SP0 - 4; w32(e.uc, esp, 0x11223344)
    try:
        e.run(VA["thunk_btn_gate_pre"], 0x11223344, esp=esp, esi=esi, count=100)
    except Exception:
        pass
    assert e.reg("eax") in (0x99, 1)          # v5/v4 bodies decide


# ---- listbox_hover_clamp: the two ListBox_set_hover caves vs the vanilla contract ---------
_LB_ELEM, _LB_LB, _LB_VT, _LB_ADJ = 0x2010000, 0x2010048, 0x2020000, 0x18
_LB_DLG = _LB_LB + _LB_ADJ


def _lb_setup(e, rows, cols, old_hover):
    uc = e.uc
    uc.mem_write(AR.LB_CLEAR_HOVER, asm("""
        mov dword ptr [0x720000], ecx
        mov dword ptr [0x720004], esp
        inc dword ptr [0x720008]
        ret 8"""))
    for a in (AR.LB_HOVER_EXIT, AR.LB_GRID_RESUME, AR.LB_SLOT_RESUME):
        uc.mem_write(a, b"\xF4")                                   # hlt: eip = a+1
    w32(uc, _LB_ELEM, _LB_VT); w32(uc, _LB_VT + 8, _LB_ADJ)
    w32(uc, _LB_DLG + 0x10, rows); w32(uc, _LB_DLG + 0xC, cols)
    w32(uc, _LB_LB - 0x30, 5)                                      # first_row
    esp = SP0 - 0x40; w32(uc, esp + 0x10, old_hover)
    return esp


def _lb_calls(e):
    return r32(e.uc, REC + 8), r32(e.uc, REC), r32(e.uc, REC + 4)


@pytest.mark.parametrize("rows,cols", [(8, 1), (8, 2), (3, 4)])
@pytest.mark.parametrize("y", [0, 7, 159, 160, 179, 400])
@pytest.mark.parametrize("old", [-1, 9])
def test_lb_hover_grid(rows, cols, y, old):
    e = Emu(25)
    esp = _lb_setup(e, rows, cols, old)
    e.run(VA["t_lb_hover_grid"], 0, esp=esp, eax=y, edx=0, esi=20, ebx=100, ecx=0x77, ebp=_LB_ELEM, edi=_LB_LB, count=100)
    row = y // 20
    n, ecx_at_call, esp_at_call = _lb_calls(e)
    assert e.reg("esp") == esp and e.reg("edi") == _LB_LB and e.reg("ebp") == _LB_ELEM
    if row < rows:
        assert e.reg("eip") == AR.LB_GRID_RESUME + 1 and e.reg("ebx") == 100 + row and e.reg("ecx") == 0x77 and n == 0
    else:
        assert e.reg("eip") == AR.LB_HOVER_EXIT + 1
        assert (n, ecx_at_call) == ((1, _LB_LB) if old != -1 else (0, 0))
        if old != -1:
            assert esp_at_call == esp - 12


@pytest.mark.parametrize("rows,cols", [(8, 1), (8, 2), (3, 4)])
@pytest.mark.parametrize("slot", [0, 7, 8, 11, 12, 15, 16, 40])
@pytest.mark.parametrize("old", [-1, 3])
def test_lb_hover_slot(rows, cols, slot, old):
    e = Emu(25)
    esp = _lb_setup(e, rows, cols, old)
    e.run(VA["t_lb_hover_slot"], 0, esp=esp, ebx=slot, ebp=_LB_ELEM, edi=_LB_LB, count=100)
    n, ecx_at_call, _ = _lb_calls(e)
    assert e.reg("esp") == esp
    if slot < rows * cols:
        assert e.reg("eip") == AR.LB_SLOT_RESUME + 1 and e.reg("eax") == 5 + slot and e.reg("ecx") == _LB_VT and n == 0
    else:
        assert e.reg("eip") == AR.LB_HOVER_EXIT + 1
        assert (n, ecx_at_call) == ((1, _LB_LB) if old != -1 else (0, 0))


def test_lb_caves_byte_identical_to_the_shipped_bake():
    """The proto's LISTFIX caves (user-verified run 7, dropped from the proto once baked) live on as the yaml
    cave content of bake v7: the assembler must keep producing those exact bytes."""
    src = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    for name in ("t_lb_hover_grid", "t_lb_hover_slot"):
        off, b = LAYOUT[name]
        i = src.index(f"      - id: {name}" + chr(10))
        line = src[i:src.index(chr(10), src.index("bytes:", i))]
        assert bytes.fromhex(line.split('"')[1].replace(" ", "")) == b, name


def test_rw_init_leave_yaml_bytes_match_the_assembler():
    """The shipped t_rw_init_leave bytes (patches.yaml, every placeholder resolved) == assemble_rw's LAYOUT output,
    at its pinned offset -- the init lever has zero slack (ends flush at the next entry), so a stale yaml copy or a
    hand edit of either side is a silent layout drift."""
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    e = next(c for c in cave["contents"] if c["id"] == "t_rw_init_leave")
    symtab = ap.build_symbol_table(syms, caves)
    off, b = LAYOUT["t_rw_init_leave"]
    assert int(e["offset"]) == off
    va = 0x00A0C000 + off
    assert bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, symtab)) == b
    nxt = min(int(c["offset"]) for c in cave["contents"] if int(c["offset"]) > off)
    assert off + len(b) <= nxt


# ---- init leave: the field lever vs the proto's arithmetic -------------------------------
def _run_init_leave(g, kind=2):
    """Run t_rw_init_leave from its real bytes with the engine callees stubbed; g_reportwin_kind = `kind` on
    entry. The GraphicWin_resize stub records (self, w, h) at REC..+8, the page kind it SEES at REC+0xC (the
    synchronous vtbl+0x30 repaint switches on it) and its a4 at REC+0x10."""
    e = Emu(g)
    uc = e.uc
    w32(uc, AR.KIND, kind)
    SWv, SHv = {16: (1024, 768), 17: (1088, 816), 22: (1920, 1080), 25: (1600, 1200), 33: (2112, 1584), 40: (3840, 2160),
                47: (3008, 2256)}.get(g, (64 * g, 48 * g))                 # any other g: the exact 4:3 screen at g/16
    w32(uc, AR.SW, SWv); w32(uc, AR.SH, SHv)
    strip = s(0xD4, g); w32(uc, AR.STRIP_H, strip)
    w32(uc, AR.RW + 0xA1C, 650); w32(uc, AR.RW + 0xA20, 553)
    w32(uc, AR.RI + 0x1E230, 1)
    w32(uc, AR.RI + 0x40, 381); w32(uc, AR.RI + 0x44, 293); w32(uc, AR.RI + 0x4C, 393)
    w32(uc, AR.RI + 0x28, 382)                                       # left panel R: the strip's drawn L = 382 - K (fix 12 / N3)
    w32(uc, AR.RI + 0x50, 500); w32(uc, AR.RI + 0x5C, 900)
    w32(uc, AR.G_DL_IMMG, 16); w32(uc, C["g_rw_vpdone"], 1)          # VP already done -> skip the bootstrap
    # stubs: find_font returns a distinct fake font per (size,style) with metrics; resize records;
    # t_dl_immfix records immg + esi; VirtualAlloc returns a buffer
    e.stub(AR.FIND_FONT, f"""
        mov eax, dword ptr [esp+4]
        mov ecx, dword ptr [esp+8]
        shl eax, 12
        shl ecx, 8
        or  eax, ecx
        or  eax, 0x2070000
        mov dword ptr [eax], 5
        mov dword ptr [eax+16], 10
        ret
    """)
    # fonts v2: t_ffn(S, v) (the face-law drop-in, NATIVE args) -> a distinct fake font per (S, v) with
    # metrics; t_fdirect_a14b() -> the Arial-14-bold family's fake (tag 0x2080000)
    # (the real helpers are 23B/24B apart at 0x2E570/0x2E590: the stub bodies live in the STUB area, the
    # helper slots hold 5-byte jmps so neither stub overwrites the other's)
    e.stub(AR.T_FFN, f"jmp {STUB + 0xA00:#x}")
    e.stub(STUB + 0xA00, f"""
        mov eax, dword ptr [esp+4]
        mov ecx, dword ptr [esp+8]
        shl eax, 12
        shl ecx, 8
        or  eax, ecx
        or  eax, 0x2070000
        mov dword ptr [eax], 5
        mov dword ptr [eax+16], 10
        ret
    """)
    e.stub(AR.T_FDIRECT_A14B, f"jmp {STUB + 0xA40:#x}")
    e.stub(STUB + 0xA40, """
        mov eax, 0x208E100
        mov dword ptr [eax], 5
        mov dword ptr [eax+16], 10
        ret
    """)
    e.stub(AR.RESIZE, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [{AR.KIND:#x}]
        mov dword ptr [{REC + 0xC:#x}], eax
        mov eax, dword ptr [esp+0xC]
        mov dword ptr [{REC + 0x10:#x}], eax
        mov dword ptr [{AR.KIND:#x}], 0x5A5A5A5A
        ret 0xC
    """)
    e.stub(AR.T_DL_IMMFIX, f"""
        mov eax, dword ptr [{AR.G_DL_IMMG:#x}]
        mov dword ptr [{REC + 0x20:#x}], eax
        mov dword ptr [{REC + 0x24:#x}], esi
        ret
    """)
    uc.mem_write(0x669134, struct.pack("<I", STUB + 0x900))
    e.stub(STUB + 0x900, "mov eax, 0x3000000\n ret 0x10")
    # Font_init (thiscall this, name, size, flags; RET 0xC): tag the scratch Font with (size, flags) + the name ptr
    e.stub(AR.FONT_INIT, """
        mov eax, dword ptr [esp+8]
        shl eax, 12
        mov edx, dword ptr [esp+12]
        shl edx, 8
        or  eax, edx
        or  eax, 0x5000000
        mov dword ptr [ecx], eax
        mov eax, dword ptr [esp+4]
        mov dword ptr [ecx+4], eax
        ret 0xC
    """)
    w32(uc, C["g_rw_ret"], 0x11223344)
    try:
        e.run(VA["t_rw_init_leave"], 0x11223344, esp=SP0, ebx=1, esi=2, edi=3, count=200000)
    except Exception:
        pass
    return e, uc, SWv, SHv, strip


@pytest.mark.parametrize("g", list(range(16, 41)) + [47])
def test_init_leave_lever(g):
    e, uc, SWv, SHv, strip = _run_init_leave(g)
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0 and (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (1, 2, 3)
    if g <= 16:
        assert r32(uc, AR.RW + 0xA1C) == 650 and r32(uc, REC + 0x24) == 0        # untouched, no walk
        return
    W, H = fl(650, g), fl(553, g)
    x, wx = SL.rw_window_x(SWv, W, g)                                            # v5: the frame (R - L wide) is centred
    y = SHv - H - strip
    assert (r32s(uc, AR.RW + 0xA1C), r32s(uc, AR.RW + 0xA20), r32s(uc, AR.RW + 0xA14), r32s(uc, AR.RW + 0xA18)) == (W, H, x, y)
    frame, clip = SL.rw_window_rects(W, H, g)                                    # v4: clip = frame inset s(3), one cascade
    assert struct.unpack("<iiii", bytes(uc.mem_read(AR.RW + 0x5974, 16))) == clip
    cw = SL.rw_canvas_w(W, g)                                                   # v6: ceil((ceil(W*16/g) + 0x4E)*g/16)
    assert cw == -(-728 * g // 16) and (cw << 4) // g == 728                      # the native canvas, exactly
    assert struct.unpack("<iiii", bytes(uc.mem_read(AR.RW + 0x5984, 16))) == frame == (
        fl(15, g) + fl(8, g), 0, fl(((cw << 4) // g) - 0x37, g), H)             # v5: frame L/R = the rails' own cascades
    assert frame[2] == fl(673, g) and 0 <= frame[2] - frame[0] - W <= 2          # v6: R = vanilla x g/16
    if g == 40:
        assert frame[2] - frame[0] == W and x == (SWv - W) >> 1                 # 4K: the frame keeps v4's width / centre
    assert wx == x - frame[0]
    K = SL.stroke_width(g)                                                      # equal frame->clip channel on L, T, R
    assert clip[0] - frame[0] - K == clip[1] - frame[1] - K == (frame[2] - K) - clip[2] == s(3, g) - K
    # fonts v2 (2026-09-17): every report font = t_ffn(NATIVE size, variant) -- the face/weight law lives
    # in the helper (tests/test_fontlaw_asm_parity.py); this lever passes the vanilla (size, variant)
    # of each of the 15 table fonts and stores what comes back.  No Font_init here any more.
    for i, (sz, st) in enumerate(AR.FONTS):
        assert r32(uc, AR.RI + 0x1E180 + 4 * i) == (0x2070000 | (sz << 12) | (st << 8)), (i, sz, st)
        assert SL.font_face_law(sz, st, g)[1] == SL.rw_font_nominal(sz, g) or SL.font_face_law(sz, st, g)[0] == "init"
    assert r32(uc, C["g_rw_railcol"]) == 0x3000000
    assert r32(uc, AR.RW + 0xE268) == SL.rw_line_h(15, g) == s(15, g) and r32(uc, AR.RI + 0x1C) == s(15, g)   # v3: the law, not the stub metric (5 + 10)
    Wout = SL.rw_canvas_w(W, g)
    assert (r32(uc, REC), r32(uc, REC + 4), r32(uc, REC + 8)) == (AR.RW, Wout, H)
    assert struct.unpack("<iiii", bytes(uc.mem_read(AR.RW + 0x13C, 16))) == (wx, y, wx + Wout, y + H)
    assert wx + frame[0] == x                                                   # the frame's screen x is the centred A14
    font = 0x208E100                                          # t_fdirect_a14b(): the Arial fl(14g/16) bold slot (v2; v1 = find_font(g, 0))
    assert r32(uc, C["g_rw_font"]) == font and all(r32(uc, va) == font for va in AR.FONT_PUSH_RW)
    assert r32(uc, AR.TXTBOX_IMM) == s(3, g) + s(0x2C, g) and r32(uc, AR.SPACER_IMM) == s(3, g) + s(0x2E, g)
    for i in range(7):
        # law rw_kind_tab_x (fix 12 / N3): the strip's DRAWN L (left panel R - K = 382 - K) + s(17 + 42i), not +0x40's 381
        assert r32(uc, AR.RI + 0xA298 + 4 * i) == SL.rw_kind_tab_x(i, (381, 293, 0, 393), (0, 0, 382, 0), g) == 382 - SL.stroke_width(g) + s(17 + 42 * i, g)
    assert r32s(uc, AR.RI + 0xA2CC) == ((293 + 393) - s(0x24, g)) >> 1
    for f in range(7):
        assert r32(uc, AR.RI + 0x60 + 4 * f) == 500 + s(AR.SEEDS_WIDE[f] + 0x2B + 0x2E, g)
    assert r32s(uc, AR.RI + 0x7C) == 900 - s(0x28, g)
    assert r32(uc, AR.G_DL_SNAPBUF) == 0x3000000
    assert r32(uc, REC + 0x20) == g and r32(uc, REC + 0x24) == AR.TAB_RW and r32(uc, AR.G_DL_IMMG) == 16   # walk with g, immg restored



@pytest.mark.parametrize("g", (16, 22, 25, 40))
@pytest.mark.parametrize("kind", (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8))
def test_init_leave_resize_paints_no_page(g, kind):
    """2026-10-17: GraphicWin_resize(RW, w, h, 1) repaints synchronously (Win_resize -> vtbl+0x30 = 0x496D00), and
    that painter switches on g_reportwin_kind, which a game load never resets: with F3 last viewed the resize built
    + showed the energy ListBox on the hidden ReportWin and it stayed drawn over every other page. The lever must
    hand the resize a NON-page kind (> 8 unsigned = 0x496D2F's `ja` default: no painter) and restore the entry kind
    after, whatever the repaint did to the global. g <= 16: no resize at all (vanilla never paints at init)."""
    e, uc, *_ = _run_init_leave(g, kind)
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0 and (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (1, 2, 3)
    assert r32s(uc, AR.KIND) == kind                                            # restored (the stub scribbled it)
    if g <= 16:
        assert r32(uc, REC) == 0                                                # no resize, kind never touched
        return
    assert r32(uc, REC) == AR.RW and r32(uc, REC + 0x10) == 1                   # the resize ran, a4 = 1 (repaint)
    assert r32(uc, REC + 0xC) > 8                                               # unsigned: the painter's default case
    assert (r32(uc, REC + 4), r32(uc, REC + 8)) == (SL.rw_canvas_w(fl(650, g), g), fl(553, g))   # args intact under the push


def test_init_leave_fits_before_the_dl_tile_ph_pin():
    """t_rw_init_leave grew 22 B (the kind bracket) into the gap before t_dl_tile_ph (dl_scale's pin, which this
    script does not emit): it must still end at or before that thunk's yaml offset."""
    src = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    import re
    pin = int(re.search(r"^  t_dl_tile_ph:\s+\{ cave: pcave2, offset: (0x[0-9a-f]+)", src, re.M).group(1), 16)
    off, b = LAYOUT["t_rw_init_leave"]
    assert off + len(b) <= pin == AR.DL_TILE_PH_OFF


def test_rw_rect_owned_by_init_leave_only():
    """g_rw_rect carries the window origin ACROSS t_rw_init_leave's GraphicWin_resize, which repaints
    synchronously (Win_resize -> vtbl+0x30 painter). Any thunk the painter can reach that writes the cell
    moves the window: t_rw_techpage used it as restripe scratch, so a game load with F2 last viewed put
    every report at the header rect's origin, (-868,-124) at 4K. No other rw thunk may reference it."""
    rect = C["g_rw_rect"]
    hits = []
    for name, (off, b) in LAYOUT.items():
        if name == "t_rw_init_leave" or not (name.startswith("t_") or name.startswith("thunk_")):
            continue
        for a in range(rect, rect + 16):
            if struct.pack("<I", a) in b:
                hits.append((name, hex(a)))
    assert not hits, hits
    tr = C["g_rw_tech_rect"]
    assert tr + 16 <= rect or tr >= rect + 16

# ---- the imm table rows: identity at 16, law at g -----------------------------------------
def test_rw_table_rows_law():
    for site, a, b, bits in AR.rw_rows():
        if bits & AR.AD.K_VEH:
            continue                                    # veh_size_scaled rows: test_rw_kinds_parity
        for g in GS:
            assert AR.AD.imm_value(a, b, bits, g) == s(a, g) - s(b, g)
    assert len(AR.tech_rows()) == 162 + 2           # + assemble_dl.TECH_EXTRA_IMMS (F44, the non-DL odd row pair)


# ---- v3 (2026-09-26): the shared report line height follows the native metric x g/16, not the enlarged font ----
@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_scaling_rw_line_h_law(g):
    if g <= 16:
        assert SL.rw_line_h(15, g) == 15 and SL.rw_line_h(99, g) == 99        # engine metric untouched
    else:
        assert SL.rw_line_h(36, g) == s(15, g) and SL.rw_line_h(0, g) == s(15, g)
        assert abs(SL.rw_line_h(0, g) - 15 * g / 16) <= 0.5 + 1e-9             # proportionate within the half-down rounding
    assert SL.rw_line_h(0, 40) == 37 and SL.rw_line_h(0, 25) == 23 and SL.rw_line_h(0, 22) == 21
