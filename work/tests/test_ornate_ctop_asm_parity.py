"""Differential: thunk_tutwin_ctop v2 (yaml bytes) vs scaling_laws.ornate_untitled_content_top.

thunk_tutwin_ctop is thunk_scale_box_margin's tail at Popup_calculate_dimensions'
BasePop_calc call (0x404e93).  The REAL yaml-resolved bytes of the thunk and of
thunk_faction_footer_bump are mapped at their VAs; BasePop_calculate_dimensions
is a stub that returns a sentinel eax and clobbers ecx/edx.  Each case seeds
the popup fields the gate reads ([+0x30e8], [+0xa48], [+0xa14]), esi (the
popup / TutWin / faction-quote singleton), edi (the engine's PopupDialogState
type, live across the calc) and g, then checks [+0x30e8] and boxH [+0x30c0]
against the law, plus register hygiene (eax, esi, edi preserved).

Also pins the bytes against a keystone assembly of the documented source, so
the yaml cannot drift from the asm this file describes.

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import functools
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

import apply_patches as ap  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

PAGE = 0x1000
TUTWIN = 0x008C6E68
FACTION = 0x009403E0
HEAP = 0x00300000                       # a heap Popup (the #COMMERCE tutor popup)
BASEPOP_CALC = 0x00603800
RET_SITE = 0x00404E98
STACK = 0x00200000
SP0 = STACK + 0x800
CALC_EAX = 0x1234ABCD
BOXH0 = 400                             # whatever BasePop_calc computed WITH the 27

F_A14, F_A48, F_30C0, F_30E8 = 0xA14, 0xA48, 0x30C0, 0x30E8

SRC = """
call {footer:#x}
cmp esi, 0x8C6E68
je chk
cmp edi, 6
je orn
cmp edi, 2
jne done
orn:
cmp dword ptr [esi+0xA48], 0
jne done
cmp dword ptr [esi+0xA14], 0
jne done
cmp esi, 0x9403E0
je done
chk:
mov ecx, dword ptr [{g:#x}]
cmp ecx, 0x10
jle done
cmp dword ptr [esi+0x30E8], 0x1B
jne done
imul edx, ecx, 0x36
add edx, 0xF
shr edx, 5
mov dword ptr [esi+0x30E8], edx
sub edx, 0x1B
add dword ptr [esi+0x30C0], edx
done:
ret
"""


@functools.lru_cache(maxsize=None)
def _tables():
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    return caves, ap.build_symbol_table(symbols, caves)


@functools.lru_cache(maxsize=None)
def _yaml_thunk(name: str) -> tuple[int, bytes]:
    caves, st = _tables()
    for cave in caves:
        for ent in cave.get("contents") or []:
            if ent.get("id") == name:
                return st[name], ap.ByteTemplate(ent["bytes"]).resolve(st[name], st)
    raise KeyError(name)


def test_yaml_bytes_are_the_documented_source():
    _, st = _tables()
    va, b = _yaml_thunk("thunk_tutwin_ctop")
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    ref, _ = ks.asm(SRC.format(footer=st["thunk_faction_footer_bump"],
                               g=st["g_popup_scale_num"]), va)
    assert b == bytes(ref)


def test_the_only_entry_is_the_box_margin_tail():
    """No stale entry point: thunk_scale_box_margin's push is the one referrer."""
    caves, st = _tables()
    refs = [ent["id"] for cave in caves for ent in cave.get("contents") or []
            if "thunk_tutwin_ctop}" in (ent.get("bytes") or "")]
    assert refs == ["thunk_scale_box_margin"]
    _, b = _yaml_thunk("thunk_scale_box_margin")
    assert b[-6:] == b"\x68" + st["thunk_tutwin_ctop"].to_bytes(4, "little") + b"\xC3"


class _Machine:
    def __init__(self):
        caves, st = _tables()
        self.g_va = st["g_popup_scale_num"]
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mapped = set()
        for name in ("thunk_tutwin_ctop", "thunk_faction_footer_bump"):
            va, b = _yaml_thunk(name)
            for p in range(va & ~(PAGE - 1), (va + len(b) + PAGE - 1) & ~(PAGE - 1), PAGE):
                if p not in mapped:
                    mu.mem_map(p, PAGE)
                    mapped.add(p)
            mu.mem_write(va, b)
        gp = self.g_va & ~(PAGE - 1)
        if gp not in mapped:
            mu.mem_map(gp, PAGE)
            mapped.add(gp)
        for base in (STACK, HEAP, TUTWIN & ~(PAGE - 1), FACTION & ~(PAGE - 1)):
            mu.mem_map(base, 4 * PAGE)
        mu.mem_map(0x00603000, PAGE)
        mu.mem_map(0x00404000, PAGE)
        ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
        stub, _ = ks.asm(f"mov eax,{CALC_EAX:#x}; mov ecx,0x22222222; mov edx,0x33333333; ret",
                         BASEPOP_CALC)
        mu.mem_write(BASEPOP_CALC, bytes(stub))
        self.entry = st["thunk_tutwin_ctop"]

    def w32(self, a, v): self.mu.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    def r32(self, a): return int.from_bytes(self.mu.mem_read(a, 4), "little")

    def run(self, *, esi, edi, g, ctop, a48, a14, bottom21bc=0):
        for base in (STACK, HEAP, TUTWIN & ~(PAGE - 1), FACTION & ~(PAGE - 1)):
            self.mu.mem_write(base, bytes(4 * PAGE))
        self.w32(self.g_va, g)
        self.w32(esi + F_30E8, ctop)
        self.w32(esi + F_30C0, BOXH0)
        self.w32(esi + F_A48, a48)
        self.w32(esi + F_A14, a14)
        self.w32(esi + 0x21BC, bottom21bc)
        self.w32(SP0, RET_SITE)
        mu = self.mu
        mu.reg_write(UC_X86_REG_ESP, SP0)
        mu.reg_write(UC_X86_REG_ESI, esi)
        mu.reg_write(UC_X86_REG_EDI, edi)
        mu.reg_write(UC_X86_REG_ECX, esi)
        mu.emu_start(self.entry, RET_SITE, count=500)
        assert mu.reg_read(UC_X86_REG_ESP) == SP0 + 4
        assert mu.reg_read(UC_X86_REG_EAX) == CALC_EAX
        assert mu.reg_read(UC_X86_REG_ESI) == esi
        assert mu.reg_read(UC_X86_REG_EDI) == edi
        return self.r32(esi + F_30E8), self.r32(esi + F_30C0)


_M: list = []


@pytest.fixture(scope="module", autouse=True)
def _drop_machine():
    yield
    _M.clear()


def M() -> _Machine:
    if not _M:
        _M.append(_Machine())
    return _M[0]


G_RANGE = range(16, 41)
# (label, esi, edi type, a48 titled, a14 anchored)
CASES = [
    ("tutwin", TUTWIN, 2, 0, 0),
    ("tutwin_anchored_field", TUTWIN, 2, 0, 0x733990),
    ("heap_type6_untitled", HEAP, 6, 0, 0),
    ("heap_type2_untitled", HEAP, 2, 0, 0),
    ("heap_type6_titled", HEAP, 6, 0x7A0000, 0),
    ("heap_type2_titled", HEAP, 2, 0x7A0000, 0),
    ("heap_type6_anchored", HEAP, 6, 0, 0x733990),
    ("faction_quote_type6", FACTION, 6, 0, 0),
    ("faction_quote_type2", FACTION, 2, 0, 0),
    ("flat_type0", HEAP, 0, 0, 0),
    ("slide_type5", HEAP, 5, 0, 0),
    ("type1", HEAP, 1, 0, 0),
    ("type4", HEAP, 4, 0, 0),
    ("hidden_1000", HEAP, 1000, 0, 0),
]


@pytest.mark.parametrize("g", G_RANGE)
@pytest.mark.parametrize("label,esi,edi,a48,a14", CASES)
@pytest.mark.parametrize("ctop", [27, 18, 0x12 + 0x14 + 9])
def test_gate_matches_the_law(label, esi, edi, a48, a14, ctop, g):
    got_top, got_boxh = M().run(esi=esi, edi=edi, g=g, ctop=ctop, a48=a48, a14=a14)
    want = SL.ornate_untitled_content_top(
        ctop, popup_type=edi, titled=a48 != 0, anchored=a14 != 0,
        is_tutwin=esi == TUTWIN, faction_quote=esi == FACTION, g=g)
    assert got_top == want
    assert got_boxh == BOXH0 + (want - ctop)


@pytest.mark.parametrize("g", G_RANGE)
def test_already_scaled_top_is_not_rescaled(g):
    first = SL.ornate_untitled_content_top(27, popup_type=6, titled=False, anchored=False,
                                           is_tutwin=False, faction_quote=False, g=g)
    top, boxh = M().run(esi=HEAP, edi=6, g=g, ctop=first, a48=0, a14=0)
    if g > 16:
        assert first != 27
    assert (top, boxh) == (first, BOXH0)


def test_the_commerce_popup_target_at_4k():
    """Shot 20261011-125749 (g=40): expected content top 67 after the fix."""
    top, boxh = M().run(esi=HEAP, edi=6, g=40, ctop=27, a48=0, a14=0)
    assert (top, boxh) == (67, BOXH0 + 40)


@pytest.mark.parametrize("label,esi,edi,a48,a14", CASES)
def test_native_g_is_identity(label, esi, edi, a48, a14):
    assert M().run(esi=esi, edi=edi, g=16, ctop=27, a48=a48, a14=a14) == (27, BOXH0)


def test_faction_footer_bump_still_runs_through_the_chain():
    """The CALL keeps footer_bump in the chain: faction quote's [0x21bc] grows."""
    m = M()
    m.run(esi=FACTION, edi=6, g=40, ctop=27, a48=0, a14=0, bottom21bc=10)
    assert m.r32(FACTION + 0x21BC) == 10 + ((40 - 16) * 12 >> 4)


# ---------------------------------------------------------------------------
# The ENGINE fact the gate keys on: Popup_calculate_dimensions' real bytes
# (0x404BE8..0x404E93, from the image apply_patches builds on a fresh .bak copy)
# give [+0x21b8] == 27 exactly for an untitled popup whose (converted) type is
# 6 or 2, and the edi that reaches the 0x404e93 call is that same type.
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402

import pefile  # noqa: E402

ENGINE_START, ENGINE_CALL = 0x00404BE8, 0x00404E93   # 0x404be8 = the iface-index load the 0x404bed test needs
WIN_IS_VISIBLE, MAINWIN = 0x005F7E90, 0x007AE820
G_DLG_STATE, G_IFACE_IDX, G_IFACE_MODES = 0x006A721C, 0x007D392C, 0x007AE778
G_9156B0 = 0x009156B0
VIS_CELL = STACK + 0x300                # Win_is_visible stub's return cell (off the code pages)


@pytest.fixture(scope="module")
def engine(baked_exe, target_meta):
    data = baked_exe.read_bytes()
    assert hashlib.md5(data).hexdigest() == target_meta["patched_md5"]
    pe = pefile.PE(data=data)
    base = pe.OPTIONAL_HEADER.ImageBase
    img = pe.get_memory_mapped_image()
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    size = (len(img) + PAGE - 1) & ~(PAGE - 1)
    mu.mem_map(base, size)
    mu.mem_write(base, img)
    for extra in (STACK, HEAP):
        mu.mem_map(extra, 4 * PAGE)
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    stub, _ = ks.asm(f"mov eax,[{VIS_CELL:#x}]; mov ecx,0x22222222; mov edx,0x33333333; ret",
                     WIN_IS_VISIBLE)
    mu.mem_write(WIN_IS_VISIBLE, bytes(stub))
    yield mu
    del mu


def _w(mu, a, v): mu.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))
def _r(mu, a): return int.from_bytes(mu.mem_read(a, 4), "little")


def _engine_type(state, mode, a14):
    """Popup_calc 0x404BED..0x404C19, transcribed: 0/5 -> 6 inside a sub-interface."""
    if mode in (0, 0xA) or (mode == 4 and a14 != 0):
        return state
    return 6 if state in (0, 5) else state


@pytest.mark.parametrize("visible", [0, 1])
@pytest.mark.parametrize("titled", [0, 1])
@pytest.mark.parametrize("a14", [0, 0x733990, 0x123456])
@pytest.mark.parametrize("mode", [0, 1, 4, 0xA])
@pytest.mark.parametrize("state", [0, 1, 2, 3, 4, 5, 6, 7])
def test_engine_header_is_27_exactly_for_untitled_type_6_or_2(engine, state, mode, a14,
                                                              titled, visible):
    mu = engine
    mu.mem_write(HEAP, bytes(4 * PAGE))
    mu.mem_write(STACK, bytes(4 * PAGE))
    _w(mu, VIS_CELL, visible)
    _w(mu, G_DLG_STATE, state)
    _w(mu, G_IFACE_IDX, 0)
    _w(mu, G_IFACE_MODES, mode)
    _w(mu, G_9156B0, STACK + 0x100)        # [[0x9156b0]+4] read on the flat path
    _w(mu, HEAP + 0xA48, titled)
    _w(mu, HEAP + 0xA14, a14)
    _w(mu, HEAP + 0x21D0, STACK + 0x200)   # sub-object: its [+4]/[+8] offsets = 0
    mu.reg_write(UC_X86_REG_ESP, SP0)
    mu.reg_write(UC_X86_REG_ESI, HEAP)
    mu.reg_write(UC_X86_REG_EBX, 0)        # Popup_calc's `xor ebx,ebx` @0x404b14
    mu.reg_write(UC_X86_REG_EDI, 0xDEAD)
    mu.emu_start(ENGINE_START, ENGINE_CALL, count=2000)
    assert mu.reg_read(UC_X86_REG_EIP) == ENGINE_CALL
    typ = _engine_type(state, mode, a14)
    edi = mu.reg_read(UC_X86_REG_EDI)
    hdr = _r(mu, HEAP + 0x21B8)
    assert edi == typ
    assert _r(mu, HEAP + 0x30AC) == typ * 10000        # the raw band encoding (from 0)
    base = 0x26 if titled else 0x12
    assert hdr == base + (9 if edi in (6, 2) else 0)   # the +9 went to exactly this edi
    assert (hdr == 27) == (not titled and edi in (6, 2))
