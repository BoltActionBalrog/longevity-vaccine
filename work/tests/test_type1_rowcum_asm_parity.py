"""W8T v3 asm parity (assemble_type1_rowcum.py): t1c_barh / t1c_pn / t1c_calc / t1c_rowtop / t1c_hit / t1c_label /
t1c_pdesc / t1c_ckpos (F46: the type-1 popup rows on ONE uniform pitch P = half_down(22 g, 16), the stripe-symmetric
bar, the label lifted so its ink ends on the bar's last row, the checkbox on the bar's top row -- the user's decisions
2026-10-27) -- Unicorn on the patches.yaml bytes resolved at their real cave VAs (thunk_rowgap's real bytes under
t1c_calc; stubs that record what they are handed for Buffer_text_height, t_ck_list and the five Win32 imports t1c_pdesc
calls through the IAT, plus the GetGlyphOutlineA its GetProcAddress hands back), against scaling_laws.py:
type1_row_h / type1_row_cum_calc / type1_row_cum_marked / type1_row_pitch / type1_row_cell / type1_row_top /
type1_row_at / type1_label_lift / type1_checkbox_y_arg.  Each test sweeps g in 16..64 and both sides of every gate
condition (the marked identity and each field one off it), checks the registers each contract keeps, the stack, and
that nothing else is written; t1c_pdesc's every failure path (no gdi32, no proc, no DC, GDI_ERROR) and its cache.  The
wiring tests check the five sites, that no branch in the CheckList code lands inside a replaced window, and the yaml
bytes == the assembler's.  Law-level properties (g = 16 identity, equal gaps, rows in their cells, the click the exact
inverse) are here too.  Pure Unicorn on a few hundred bytes: no bake, no boot (~14 s serial over 399 items: one Unicorn per g, the
click swept over every y of the marked list).
"""
from __future__ import annotations

import pathlib
import struct
import sys
from functools import lru_cache

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_patches as ap  # noqa: E402
import assemble_type1_rowcum as A  # noqa: E402
import scaling_laws as SL  # noqa: E402

YAML = ROOT / "patches" / "patches.yaml"
GS = range(16, 65)
STACK, SP0 = 0x00300000, 0x00308000
DATA = 0x00500000                 # a Dialog data region (eax / edi / ecx at the sites)
OBJ = 0x00510000                  # the CheckList `this` (esi at the calc / label sites)
FONT = 0x00520000                 # a Font struct (+8 HFONT, +0xC cell, +0x10 cap_h, +0x14 int. leading, +0x1C tmDescent)
POPUP = 0x00530000                # the popup whose painter (FUN_00405b20) draws the checkbox
API = 0x00700000                  # stubs for the IAT imports t1c_pdesc calls
GGO = API + 0x100                 # the "GetGlyphOutlineA" the GetProcAddress stub hands back
HFONT, HDC, HOLD, HMOD = 0x5550, 0x7770, 0x8880, 0x77E10000
RET_SITE = 0x00401000             # the site's return address (hlt)
RET_FN = 0x00401010               # FUN_0060ed10's caller (hlt)
REGS0 = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x00307000,
         UC_X86_REG_EDX: 0x5555, UC_X86_REG_EAX: 0x6666, UC_X86_REG_ECX: 0x7777}
P = SL.TYPE1_POPUP_ROW_PRESET


@lru_cache(maxsize=1)
def _yaml():
    sites, _g, caves, syms = ap.load_patches(YAML)
    st = dict(ap.build_symbol_table(syms, caves))
    ents = {c["id"]: c for cave in caves for c in cave.get("contents") or []}
    return sites, st, ents


def _bytes(name: str) -> bytes:
    _s, st, ents = _yaml()
    return bytes(ap.ByteTemplate(ents[name]["bytes"]).resolve(st[name], st))


def _site(sid: str) -> dict:
    sites, _st, _e = _yaml()
    return next(s for s in sites if s["id"] == sid)


class Rig:
    """One Unicorn per g (cached: _rig), every thunk at its VA, the hooks installed once; reset() per case."""

    def __init__(self, g: int):
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((0x00400000, 0x2000), (0x005DC000, 0x1000), (0x00668000, 0x2000),
                           (A.PCAVE2 + 0x33000, 0x1000), (A.PCAVE2 + 0x3D000, 0x1000), (STACK, 0x10000),
                           (DATA, 0x1000), (OBJ, 0x2000), (FONT, 0x1000), (POPUP, 0x3000), (API, 0x1000)):
            uc.mem_map(base, size)
        uc.mem_write(RET_SITE, bytes([0xF4]))
        uc.mem_write(RET_FN, bytes([0xF4]))
        uc.mem_write(A.G, struct.pack("<i", g))
        _s, st, _e = _yaml()
        for name, _f, _va, _end in A.THUNKS:
            uc.mem_write(st[name], _bytes(name))
        uc.mem_write(st["thunk_rowgap"], _bytes("thunk_rowgap"))
        self.writes, self.calls, self.th = [], [], 0
        self.api = dict(hmod=HMOD, proc=GGO, dc=HDC, ggo=1, desc=(10, 3))   # GGO: eax, (gmBlackBoxY, origin.y)
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size, val, _: self.writes.append(addr))
        for a in (RET_SITE, RET_FN):
            uc.hook_add(UC_HOOK_CODE, lambda u, addr, size, _: u.emu_stop(), begin=a, end=a)
        self._stub(A.BUFFER_TEXT_HEIGHT, 0, rect=False)          # eax = self.th
        self._stub(A.T_CK_LIST, 0x18, rect=False)                # the tail of t1c_ckpos (the y it sees: [esp+0x10])
        for iat, k, nb, ret in ((A.IAT_GETMODULEHANDLEA, 0, 4, "hmod"), (A.IAT_GETPROCADDRESS, 1, 8, "proc"),
                                (A.IAT_CREATECOMPATIBLEDC, 2, 4, "dc"), (A.IAT_SELECTOBJECT, 3, 8, "old"),
                                (A.IAT_DELETEDC, 4, 4, "one")):
            self.w32(iat, API + 0x10 * k)
            self._api(API + 0x10 * k, iat, nb, ret)
        self._api(GGO, "GetGlyphOutlineA", 0x1C, "ggo")
        self.reset_data()

    def reset_data(self):
        for _n, (o, b) in A.DATA.items():
            self.uc.mem_write(A.G_T1C_DATA + o, b)

    def _api(self, va, name, nb, ret):
        def cb(u, addr, size, _):
            esp = u.reg_read(UC_X86_REG_ESP)
            args = [self.r32(esp + 4 + 4 * k) & 0xFFFFFFFF for k in range(nb // 4)]
            self.calls.append(dict(va=va, name=name, args=args))
            if name == "GetGlyphOutlineA":
                by, oy = self.api["desc"]
                self.uc.mem_write(args[3], struct.pack("<IIiihh", 7, by, 0, oy, 9, 0))
            eax = {"old": HOLD, "one": 1}.get(ret, self.api.get(ret, 0))
            u.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
            u.reg_write(UC_X86_REG_ESP, esp + 4 + nb)
            u.reg_write(UC_X86_REG_EIP, self.r32(esp) & 0xFFFFFFFF)
        self.uc.hook_add(UC_HOOK_CODE, cb, begin=va, end=va)

    def reset(self):
        self.writes.clear()
        self.calls.clear()
        return self

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def _stub(self, va: int, ret_n: int, rect=False):
        def cb(u, addr, size, _):
            esp = u.reg_read(UC_X86_REG_ESP)
            a1 = self.r32(esp + 4) & 0xFFFFFFFF
            self.calls.append(dict(va=va, ecx=u.reg_read(UC_X86_REG_ECX), a1=a1, a2=self.r32(esp + 8) & 0xFFFFFFFF,
                                   rect=struct.unpack("<4i", bytes(u.mem_read(a1, 16))) if rect else None, esp=esp))
            u.reg_write(UC_X86_REG_ESP, esp + 4 + ret_n)
            u.reg_write(UC_X86_REG_EAX, self.th & 0xFFFFFFFF)
            u.reg_write(UC_X86_REG_EIP, self.r32(esp) & 0xFFFFFFFF)
        self.uc.hook_add(UC_HOOK_CODE, cb, begin=va, end=va)

    def run_to_either(self, va: int, regs: dict, stack: list):
        """Run until either hlt (the site's return or the function's caller); -> (uc, eip)."""
        uc = self.uc
        for i, v in enumerate(stack):
            self.w32(SP0 + 4 * i, v)
        for r, v in {**REGS0, **regs}.items():
            uc.reg_write(r, v & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, SP0)
        self.writes.clear()
        uc.emu_start(va, 0xFFFFFFF0, count=20_000)
        return uc, uc.reg_read(UC_X86_REG_EIP)

    def run(self, va: int, regs: dict, stack: list):
        uc, eip = self.run_to_either(va, regs, stack)
        assert eip == RET_SITE, hex(eip)
        return uc


_RIGS: dict = {}


def _rig(g: int) -> Rig:
    if g not in _RIGS:
        _RIGS[g] = Rig(g)
    return _RIGS[g].reset()


def fields(g, rows=19, preset=P, gap=None, row_h=None, list_h=None):
    gap = (3 * g) >> 4 if gap is None else gap
    row_h = SL.type1_row_h(preset, g) if row_h is None else row_h
    list_h = SL.type1_row_cell(rows, preset, g) if list_h is None else list_h
    return dict(rows=rows, preset=preset, gap=gap, row_h=row_h, list_h=list_h)


def put(rig, f):
    for off, k in ((0x58, "rows"), (0x48, "preset"), (0x44, "gap"), (0x68, "row_h"), (0x60, "list_h")):
        rig.w32(DATA + off, f[k])


def variants(g):
    """The marked identity and each condition one off it (plus the PrefWin / editor shape: preset -1)."""
    base = fields(g)
    yield base
    for k, d in (("rows", -18), ("rows", -19), ("preset", -20), ("preset", 0x100 - P), ("gap", 1), ("gap", -1),
                 ("row_h", 1), ("row_h", -1), ("list_h", 1), ("list_h", -1)):
        v = dict(base)
        v[k] += d
        yield v
    yield fields(g, rows=6, preset=-1, gap=6, row_h=50, list_h=339)
    yield fields(g, row_h=SL.scale_px(P, g)) if SL.scale_px(P, g) != SL.type1_row_h(P, g) else fields(g, rows=3)
    yield fields(g, rows=2)
    yield fields(g, rows=40, preset=12)


# ================================================================ wiring
def test_yaml_bytes_are_the_assembler_output():
    _s, st, _e = _yaml()
    for name, (va, blob, _t) in A.build().items():
        assert st[name] == va, (name, hex(st[name]), hex(va))
        assert _bytes(name) == blob, name
    assert st["thunk_rowgap"] == A.THUNK_ROWGAP and st["t_ck_list"] == A.T_CK_LIST
    assert st["g_popup_scale_num"] == A.G and st["Buffer_text_height"] == A.BUFFER_TEXT_HEIGHT


def test_wiring_sites():
    for sid, (va, orig, new) in A.site_bytes().items():
        s = _site(sid)
        assert s["virtual_addr"] == va and s["original_bytes"] == orig and s["new_bytes"] == new, sid
        grp = "popup_list_checkbox_scale" if sid == "FUN_00405b20.checkbox_scale" else "popup_list_rowgap"
        assert s["group"] == grp and s["length"] == len(orig.split())
    _s, st, _e = _yaml()
    assert "t_title_inner" not in st                     # F51 dropped (user decision): the title band is master's


def test_no_branch_lands_inside_a_replaced_window(pristine_or_bak):
    """Every branch / call in the CheckList code (0x60E670..0x610970) and FUN_0060ed10 lands outside the interiors
    of the two replaced windows (their first byte is the CALL)."""
    data, ib, secs = pristine_or_bak
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    lo, hi = 0x0060E670, 0x00610970
    off = next(raw + lo - v for v, raw, size in secs if v <= lo < v + size)
    windows = [(A.SITE_ROWTOP, A.SITE_ROWTOP + 18), (A.SITE_HIT, A.SITE_HIT + 20), (A.SITE_CALC, A.SITE_CALC + 8),
               (A.SITE_LABEL, A.SITE_LABEL + 5)]
    n = 0
    for i in md.disasm(bytes(data[off:off + hi - lo]), lo):
        if i.mnemonic.startswith("j") or i.mnemonic == "call":
            try:
                tgt = int(i.op_str, 16)
            except ValueError:
                continue
            n += 1
            for a, b in windows:
                assert not (a < tgt < b), (hex(i.address), i.mnemonic, hex(tgt))
    assert n > 100


@pytest.fixture(scope="module")
def pristine_or_bak(bak_path):
    import pefile
    data = pathlib.Path(bak_path).read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    secs = [(ib + s.VirtualAddress, s.PointerToRawData, s.SizeOfRawData) for s in pe.sections]
    for sid, (va, orig, _n) in A.site_bytes().items():
        if sid == "FUN_00405b20.checkbox_scale":
            continue                                   # a retargeted rel32 (its original is the vanilla call)
        o = next(raw + va - v for v, raw, size in secs if v <= va < v + size)
        assert data[o:o + len(orig.split())] == bytes.fromhex(orig.replace(" ", "")), hex(va)
    return data, ib, secs


# ================================================================ t1c_pn
@pytest.mark.parametrize("g", GS)
def test_pn_is_the_marker_law(g):
    for f in variants(g):
        rig = _rig(g)
        put(rig, f)
        uc = rig.run(A.T1C_PN, {UC_X86_REG_EAX: DATA}, [RET_SITE])
        want = SL.type1_row_cum_marked(g, f["rows"], f["preset"], f["gap"], f["row_h"], f["list_h"])
        assert uc.reg_read(UC_X86_REG_EAX) == want, (g, f)
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
        for r in (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert uc.reg_read(r) == REGS0[r]
        assert all(SP0 - 0x60 <= a < SP0 for a in rig.writes)
        if g == 16:
            assert want == 0


# ================================================================ t1c_calc
@pytest.mark.parametrize("g", GS)
def test_calc_is_the_law(g):
    for rows in (1, 2, 18, 19):
        for preset in (P, -1, 0, 12):
            for gap_native in (3, 6, 0):
                for th in (12, 30, SL.type1_row_h(max(preset, 1), g), SL.type1_row_h(max(preset, 1), g) + 1):
                    row_h_engine = max(preset, (20 * g) >> 4)
                    rig = _rig(g)
                    rig.w32(DATA + 0x58, rows)
                    rig.w32(DATA + 0x48, preset)
                    rig.w32(DATA + 0x44, gap_native)
                    rig.w32(DATA + 0x68, row_h_engine)
                    rig.w32(DATA + 0x60, 0x0BAD)
                    vt = OBJ + 0x1000
                    rig.w32(OBJ, vt)
                    rig.w32(vt + 4, 0x130)
                    rig.th = th
                    uc, eip = rig.run_to_either(A.T1C_CALC, {UC_X86_REG_EAX: DATA, UC_X86_REG_ESI: OBJ},
                                                [RET_SITE, 0x4444, RET_FN])
                    gap = SL.dialog_row_margin(gap_native, g) if rows > 1 else gap_native     # thunk_rowgap
                    assert rig.r32(DATA + 0x44) == gap
                    on = SL.type1_row_cum_calc(g, rows, preset, gap, th)
                    called = [c for c in rig.calls if c["va"] == A.BUFFER_TEXT_HEIGHT]
                    assert eip == RET_SITE and uc.reg_read(UC_X86_REG_ESP) == SP0 + 4, (g, rows, preset, th)
                    assert uc.reg_read(UC_X86_REG_EAX) == DATA and uc.reg_read(UC_X86_REG_ESI) == OBJ
                    assert rig.r32(DATA + 0x60) == 0x0BAD                       # the caller's 0x60F021 stores it
                    if on:
                        assert rig.r32(DATA + 0x68) == SL.type1_row_h(preset, g)
                        assert uc.reg_read(UC_X86_REG_ECX) == SL.type1_row_pitch(preset, g)
                        list_h = uc.reg_read(UC_X86_REG_ECX) * rows              # 0x60F021: imul ecx, [+0x58]
                        assert list_h == SL.type1_row_cell(rows, preset, g)
                        assert SL.type1_row_cum_marked(g, rows, preset, gap, rig.r32(DATA + 0x68),
                                                       list_h) == SL.type1_row_pitch(preset, g)
                    else:
                        assert uc.reg_read(UC_X86_REG_ECX) == row_h_engine + gap
                        assert rig.r32(DATA + 0x68) == row_h_engine
                    for c in called:                                  # the window buffer the calc measured
                        assert c["ecx"] == OBJ + 0x130 + 0x444
                    if g <= 16 or rows <= 1 or preset <= 0:
                        assert not called
                    for r in (UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EBP):
                        assert uc.reg_read(r) == REGS0[r]
                    allowed = {DATA + o + k for o in (0x44, 0x68) for k in range(4)}
                    assert all(a in allowed or SP0 - 0x60 <= a < SP0 for a in rig.writes), \
                        [hex(a) for a in rig.writes]


# ================================================================ t1c_rowtop
@pytest.mark.parametrize("g", GS)
def test_rowtop_is_the_law(g):
    for f in variants(g):
        for r in (0, 1, 7, 18):
            for extra in (0, 13):
                rig = _rig(g)
                put(rig, f)
                rig.w32(SP0 + 0x14, extra)
                uc = rig.run(A.T1C_ROWTOP, {UC_X86_REG_EDI: DATA, UC_X86_REG_ECX: f["gap"], UC_X86_REG_EBX: r},
                             [RET_SITE])
                pn = SL.type1_row_cum_marked(g, f["rows"], f["preset"], f["gap"], f["row_h"], f["list_h"])
                if pn:
                    want = extra + SL.type1_row_top(r, f["preset"], g)
                else:
                    want = extra + r * (f["row_h"] + f["gap"]) + (f["gap"] >> 1)
                assert uc.reg_read(UC_X86_REG_ECX) == want & 0xFFFFFFFF, (g, f, r)
                assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
                for reg in (UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
                    assert uc.reg_read(reg) == {**REGS0, UC_X86_REG_EDI: DATA}[reg]
                assert all(SP0 - 0x60 <= a < SP0 for a in rig.writes)


# ================================================================ t1c_hit
@pytest.mark.parametrize("g", GS)
def test_hit_is_the_law(g):
    for k, f in enumerate(variants(g)):
        dense = k == 0 and g > 16                  # the marked list: every y of the window (+ the row past it)
        for col in ((0,) if dense else (0, 1)):
            for y in (range(f["list_h"] + 2) if dense else (0, 1, 21, 22, 23, 54, 55, 56, 300, 1044, 1045)):
                rig = _rig(g)
                put(rig, f)
                rig.w32(SP0 + 0x1C, y)
                uc = rig.run(A.T1C_HIT, {UC_X86_REG_ECX: DATA, UC_X86_REG_EAX: col, UC_X86_REG_EBP: f["gap"]},
                             [RET_SITE])
                pn = SL.type1_row_cum_marked(g, f["rows"], f["preset"], f["gap"], f["row_h"], f["list_h"])
                row = SL.type1_row_at(y, f["preset"], g) if pn else y // (f["row_h"] + f["gap"])
                assert uc.reg_read(UC_X86_REG_EAX) == row, (g, f, y)
                if dense and y < f["list_h"]:
                    assert SL.type1_row_cell(row, P, g) <= y < SL.type1_row_cell(row + 1, P, g)
                assert uc.reg_read(UC_X86_REG_EBX) == col * f["rows"]
                assert uc.reg_read(UC_X86_REG_EBP) == f["row_h"] + f["gap"]
                assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
                for reg in (UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_EDI):
                    assert uc.reg_read(reg) == {**REGS0, UC_X86_REG_ECX: DATA}[reg]
                assert all(SP0 - 0x60 <= a < SP0 for a in rig.writes)


# ================================================================ t1c_barh
@pytest.mark.parametrize("g", GS)
def test_barh_is_the_law(g):
    rig = _rig(g)
    for preset in (P, 12, 30, 7, 1):
        uc = rig.reset().run(A.T1C_BARH, {UC_X86_REG_EAX: preset}, [RET_SITE])
        assert uc.reg_read(UC_X86_REG_EAX) == SL.type1_row_h(preset, g), (g, preset)
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
        for r in (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert uc.reg_read(r) == REGS0[r]
        assert all(SP0 - 64 <= a < SP0 for a in rig.writes)


# ================================================================ t1c_label + t1c_pdesc
def _label_case(rig, g, f, font, bar, desc, mode="ok"):
    put(rig, f)
    rig.reset_data()
    vt = OBJ + 0x1000
    rig.w32(OBJ, vt)
    rig.w32(vt + 8, DATA - OBJ)
    off, asc, ileading, hgt = font                  # +0x1C tmDescent: the rect offset AND the fallback
    for o, v in ((8, HFONT), (0xC, hgt), (0x10, asc), (0x14, ileading), (0x1C, off)):
        rig.w32(FONT + o, v)
    rig.api.update(hmod=HMOD, proc=GGO, dc=HDC, ggo=1, desc=(desc + 4, 4))
    if mode == "nomod":
        rig.api["hmod"] = 0
    elif mode == "noproc":
        rig.api["proc"] = 0
    elif mode == "nodc":
        rig.api["dc"] = 0
    elif mode == "gfail":
        rig.api["ggo"] = -1
    stack = [RET_SITE, 0, 0, 0, 0, 0, bar]               # the caller's [esp+0x14] = the bar height
    return rig.run(A.T1C_LABEL, {UC_X86_REG_ESI: OBJ, UC_X86_REG_EDX: FONT, UC_X86_REG_EDI: 1000}, stack)


@pytest.mark.parametrize("g", GS)
def test_label_is_the_law(g):
    rig = _rig(g)
    fonts = ((10, 31, 8, 50), (6, 17, 4, 27), (4, 12, 4, 20), (8, 25, 7, 40))
    for k, f in enumerate(variants(g)):
        for font in fonts:
            for desc in (3, 5, 8):
                for single in (True, False):
                    bar = f["row_h"] if single else f["row_h"] + 9
                    rig.reset()
                    uc = _label_case(rig, g, f, font, bar, desc)
                    pn = SL.type1_row_cum_marked(g, f["rows"], f["preset"], f["gap"], f["row_h"], f["list_h"])
                    off, asc = font[0], font[1]
                    lift = SL.type1_label_lift(off, asc, desc, bar) if pn and single else 0
                    assert uc.reg_read(UC_X86_REG_EDI) == 1000 + off - lift, (g, k, font, desc, single)
                    assert uc.reg_read(UC_X86_REG_ECX) == off
                    for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EBP):
                        assert uc.reg_read(r) == REGS0[r]
                    assert uc.reg_read(UC_X86_REG_EDX) == FONT and uc.reg_read(UC_X86_REG_ESI) == OBJ
                    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
                    ggo = [c for c in rig.calls if c["name"] == "GetGlyphOutlineA"]
                    if pn and single:
                        assert len(ggo) == 1 and ggo[0]["args"][:3] == [HDC, 0x70, 0]
                        assert ggo[0]["args"][4:6] == [0, 0] and ggo[0]["args"][6] == A.DV["g_t1c_mat2"]
                        assert bytes(rig.uc.mem_read(A.DV["g_t1c_mat2"], 16)) == A.DATA["g_t1c_mat2"][1]
                        sel = [c["args"] for c in rig.calls if c["name"] == A.IAT_SELECTOBJECT]
                        assert sel == [[HDC, HFONT], [HDC, HOLD]]
                        assert [c["args"] for c in rig.calls if c["name"] == A.IAT_DELETEDC] == [[HDC]]
                    else:
                        assert not ggo
                    data = set(range(A.G_T1C_DATA, A.G_T1C_DATA + 0x20))
                    assert all(SP0 - 0x80 <= a < SP0 or a in data for a in rig.writes), [hex(a) for a in rig.writes]


@pytest.mark.parametrize("g", (20, 22, 25, 40))
def test_pdesc_fallbacks_and_cache(g):
    rig = _rig(g)
    f = fields(g)
    bar = f["row_h"]
    for mode, used in (("ok", 8), ("nomod", 10), ("noproc", 10), ("nodc", 10), ("gfail", 10)):
        rig.reset()
        uc = _label_case(rig, g, f, (10, 31, 6, 50), bar, 8, mode)
        assert uc.reg_read(UC_X86_REG_EDI) == 1000 + 10 - SL.type1_label_lift(10, 31, used, bar), mode
        assert rig.r32(A.DV["g_t1c_ggo"]) == (1 if mode in ("nomod", "noproc") else GGO), mode
        if mode == "gfail":
            assert [c["args"] for c in rig.calls if c["name"] == A.IAT_DELETEDC] == [[HDC]]
        assert rig.r32(A.DV["g_t1c_desc"]) == used and rig.r32(A.DV["g_t1c_font"]) == HFONT
        stack = [RET_SITE, 0, 0, 0, 0, 0, bar]
        rig.reset()                                   # the cache: the same font again calls nothing
        uc = rig.run(A.T1C_LABEL, {UC_X86_REG_ESI: OBJ, UC_X86_REG_EDX: FONT, UC_X86_REG_EDI: 1000}, stack)
        assert not rig.calls and uc.reg_read(UC_X86_REG_EDI) == 1000 + 10 - SL.type1_label_lift(10, 31, used, bar)
        rig.reset()                                   # another font (its height differs): measured again
        rig.w32(FONT + 0xC, 51)
        rig.run(A.T1C_LABEL, {UC_X86_REG_ESI: OBJ, UC_X86_REG_EDX: FONT, UC_X86_REG_EDI: 1000}, stack)
        names = {c["name"] for c in rig.calls}
        assert (A.IAT_CREATECOMPATIBLEDC in names) == (mode not in ("nomod", "noproc")), mode
        assert rig.r32(A.DV["g_t1c_hgt"]) == 51


# ================================================================ t1c_ckpos
@pytest.mark.parametrize("g", GS)
def test_ckpos_is_the_law(g):
    rig = _rig(g)
    vt2 = POPUP + 0x2000
    for f in variants(g):
        for top in (0, 7, 33):
            for single in (True, False):
                rig.reset()
                put(rig, f)
                ebp = 0x00307000
                rig.w32(ebp - 4, POPUP)
                rig.w32(POPUP + 0x21D0, vt2)
                rig.w32(vt2 + 8, (DATA - 0x21D0 - POPUP) & 0xFFFFFFFF)
                rig.w32(ebp - 0x10, top)
                rig.w32(ebp - 8, top + f["row_h"] + (0 if single else 9))
                y0 = 4444
                uc, eip = rig.run_to_either(A.T1C_CKPOS, {UC_X86_REG_EBP: ebp, UC_X86_REG_ECX: 0x00779504},
                                            [RET_SITE, 0x11, 0x22, 0x33, y0, 1, 1])
                assert eip == RET_SITE and uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x18
                c = [c for c in rig.calls if c["va"] == A.T_CK_LIST]
                assert len(c) == 1 and c[0]["ecx"] == 0x00779504 and c[0]["esp"] == SP0
                pn = SL.type1_row_cum_marked(g, f["rows"], f["preset"], f["gap"], f["row_h"], f["list_h"])
                want = SL.type1_checkbox_y_arg(top, g) if pn and single else y0
                assert rig.r32(SP0 + 0x10) == want, (g, f, top, single)
                for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI):
                    assert uc.reg_read(r) == REGS0[r]
                assert all(SP0 - 0x60 <= a < SP0 or a == SP0 + 0x10 for a in rig.writes), [hex(a) for a in rig.writes]


# ================================================================ the laws themselves
def test_g16_is_vanilla():
    assert SL.type1_row_layout(19, P, 16) == [(22 * r + 1, 22 * r + 20) for r in range(19)]
    assert SL.type1_row_cell(19, P, 16) == 418 and all(SL.type1_row_at(y, P, 16) == y // 22 for y in range(418))
    assert not SL.type1_row_cum_calc(16, 19, P, 3, 12)
    assert SL.type1_row_cum_marked(16, 19, P, 3, 19, 418) == 0


@pytest.mark.parametrize("g", range(17, 65))
def test_rows_on_one_pitch(g):
    """One pitch P = half_down(22 g, 16) (within 0.5 of vanilla x g/16), every gap equal (P - h), the first top s(1)
    (within 0.5), the bar h = type1_row_h: s(19) or a neighbour, h and the gap each within 1 px, a multiple of the
    stripe thickness whenever such a neighbour exists (4K: 48 for 47.5), every bar inside its click cell, the list
    rows x P, the click map the exact inverse of the cells.  The list drifts from rows x 22 g/16 by rows x (P - 22
    g/16) -- the user's accepted trade (1280x1024: -9.5 px for 19 rows).  4K: 55 exactly."""
    pp = SL.type1_row_pitch(P, g)
    h = SL.type1_row_h(P, g)
    assert abs(16 * pp - 22 * g) <= 8 and abs(16 * SL.type1_row_top(0, P, g) - g) <= 8
    assert abs(16 * h - 19 * g) <= 16 and abs(h - SL.scale_px(P, g)) <= 1
    t = SL.stripe_rows(g)
    sym = [x for x in (h - 1, h, h + 1)
           if x % t == 0 and abs(16 * x - 19 * g) <= 16 and abs(16 * (pp - x) - 3 * g) <= 16]
    assert (h % t == 0) == bool(sym) and (h == SL.scale_px(P, g) or h % t == 0)
    for n in range(2, 31):
        lay = SL.type1_row_layout(n, P, g)
        cells = [SL.type1_row_cell(r, P, g) for r in range(n + 1)]
        assert cells[-1] == n * pp and all(b - a == pp for a, b in zip(cells, cells[1:]))
        assert {b0 - a1 for (_a0, a1), (b0, _b1) in zip(lay, lay[1:])} == {pp - SL.type1_row_h(P, g)}
        for r, (t, b) in enumerate(lay):
            assert cells[r] <= t and b <= cells[r + 1], (g, n, r)
        for y in range(cells[-1]):
            r = SL.type1_row_at(y, P, g)
            assert cells[r] <= y < cells[r + 1], (g, y)
    if g == 40:
        assert pp == 55 and SL.type1_row_cell(19, P, 40) == 1045 and h == 48
