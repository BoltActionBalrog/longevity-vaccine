"""Differential: thunk_ensure_scale (menu_strip_thunks +0x560) under Unicorn, the REAL patches.yaml bytes.

    raw = scale_uniform(16)  ->  g_popup_scale_num = scaling_laws.popup_scale_num(raw)       (clamp G_MIN..G_MAX)
                                 g_stripe_period   = scaling_laws.stripe_period(g)

for every raw 0..100 (and the extremes), written once: a non-zero g is cached (nothing is written, scale_uniform is
never called).  Guard: the period store is the closed form (g < 22 ? 2 : 4), which is the law only up to g = 47
(stripe_rows(48) = 3); it is right today ONLY because the same thunk clamps g to 40.  Raising the clamp past 47
must fail here, loudly, until the store takes the general form.

Skips (does not fail) if unicorn is absent.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI,
    UC_X86_REG_ESP)


def _live():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    for c in caves:
        for e in c.get("contents") or []:
            if e["id"] == "thunk_ensure_scale":
                va = int(c["virtual_addr"]) + int(e["offset"])
                tpl = " ".join(str(e["bytes"]).split())
                return va, tpl, bytes(ap.ByteTemplate(tpl).resolve(va, sym)), sym
    raise AssertionError("thunk_ensure_scale not in patches.yaml")


VA, TEMPLATE, LIVE, SYM = _live()
G, PER, SCALE_UNIFORM = SYM["g_popup_scale_num"], SYM["g_stripe_period"], SYM["scale_uniform"]
STACK, MARKER = 0x00200000, 0x00300000
REGS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ECX: 0x22222222, UC_X86_REG_EDX: 0x33333333,
        UC_X86_REG_ESI: 0x44444444, UC_X86_REG_EDI: 0x55555555, UC_X86_REG_EBP: 0x66666666}
RAWS = tuple(range(0, 101)) + (-1, -40, 0x7FFFFFFF, -0x80000000)


def _s32(v: int) -> int:
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


def run(code: bytes, raw, *, g0: int = 0, p0: int = 0x77):
    """Enter the thunk with g = g0 and the period cell = p0; scale_uniform returns raw (None: must not be called).
    -> (g, P, scale_uniform's entry eax or None, esp delta, registers kept)."""
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {VA & ~0xFFF, (VA + len(code)) & ~0xFFF, G & ~0xFFF, PER & ~0xFFF, SCALE_UNIFORM & ~0xFFF}
    for p in sorted(pages):
        mu.mem_map(p, 0x1000)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(MARKER, 0x1000)
    mu.mem_write(VA, code)
    mu.mem_write(G, struct.pack("<i", g0))             # (conftest also writes stripe_period(g0) to the cell ...)
    mu.mem_write(PER, struct.pack("<i", p0))           # ... overwritten here with the sentinel
    mu.mem_write(SCALE_UNIFORM, b"\xF4")               # hlt: a call the cached path must never make
    seen = []

    def su(m, _a, _s, _u):
        seen.append(m.reg_read(UC_X86_REG_EAX))
        if raw is None:
            m.emu_stop()
            return
        esp = m.reg_read(UC_X86_REG_ESP)
        ret = struct.unpack("<I", bytes(m.mem_read(esp, 4)))[0]
        m.reg_write(UC_X86_REG_EAX, raw & 0xFFFFFFFF)
        m.reg_write(UC_X86_REG_ESP, esp + 4)
        m.reg_write(unicorn.x86_const.UC_X86_REG_EIP, ret)
    mu.hook_add(UC_HOOK_CODE, su, begin=SCALE_UNIFORM, end=SCALE_UNIFORM)
    sp = STACK
    mu.mem_write(sp, struct.pack("<I", MARKER))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EAX, 0x0BADF00D)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.emu_start(VA, MARKER, count=10_000)
    g = _s32(int.from_bytes(mu.mem_read(G, 4), "little"))
    p = _s32(int.from_bytes(mu.mem_read(PER, 4), "little"))
    kept = all(mu.reg_read(r) == v for r, v in REGS.items())
    return g, p, (seen[0] if seen else None), mu.reg_read(UC_X86_REG_ESP) - sp, kept, mu.reg_read(UC_X86_REG_EAX)


def sweep_problems(code: bytes) -> list:
    out = []
    for raw in RAWS:
        g, p, su_eax, d, kept, _eax = run(code, raw)
        want_g = SL.popup_scale_num(raw)
        if (g, p) != (want_g, SL.stripe_period(want_g)):
            out.append(("law", raw, g, p, want_g, SL.stripe_period(want_g)))
        if su_eax != 16 or d != 4 or not kept:
            out.append(("contract", raw, su_eax, d, kept))
    return out


def test_template_is_the_assembler_source():
    import assemble_thunks as AT
    assert TEMPLATE == " ".join(AT.THUNK_ENSURE_SCALE.split())


def test_raw_scale_to_g_and_period_is_the_law():
    """Every raw scale_uniform(16): g = popup_scale_num(raw), P = stripe_period(g); scale_uniform is entered with
    eax = 16; plain `ret` (esp + 4); only eax / flags change."""
    assert sweep_problems(LIVE) == []
    assert [SL.popup_scale_num(r) for r in (0, 16, 22, 25, 40, 41, 100)] == [16, 16, 22, 25, 40, 40, 40]


@pytest.mark.parametrize("g0", [16, 22, 25, 40, 41, 60, -3])
def test_cached_g_writes_nothing(g0):
    """A non-zero g is the cache: no scale_uniform call, g and the period cell untouched, eax untouched."""
    g, p, su_eax, d, kept, eax = run(LIVE, None, g0=g0, p0=0x77)
    assert (g, p, su_eax, d, kept, eax) == (g0, 0x77, None, 4, True, 0x0BADF00D)


# ---- the clamp <-> period-store guard ----------------------------------------------------------------------------
CLAMP_HI = re.compile(rb"\x83\xF8(.)\x7E\x05\xB8(.)\x00\x00\x00", re.S)   # cmp eax,hi ; jle +5 ; mov eax,hi
CLAMP_LO = re.compile(rb"\x83\xF8(.)\x7D\x05\xB8(.)\x00\x00\x00", re.S)   # cmp eax,lo ; jge +5 ; mov eax,lo


def _clamp(code: bytes):
    hi, lo = CLAMP_HI.search(code), CLAMP_LO.search(code)
    assert hi and lo and hi.group(1) == hi.group(2) and lo.group(1) == lo.group(2), "clamp shape changed"
    return lo.group(1)[0], hi.group(1)[0]


def guard_problems(code: bytes) -> list:
    """The stored period equals stripe_period for EVERY g the clamp admits; the clamp is SL's G_MIN..G_MAX."""
    lo, hi = _clamp(code)
    out = []
    if (lo, hi) != (SL.G_MIN, SL.G_MAX):
        out.append(("clamp != popup_scale_num's", lo, hi, SL.G_MIN, SL.G_MAX))
    for g in range(lo, hi + 1):
        got_g, p, *_ = run(code, g)
        if got_g != g or p != SL.stripe_period(g):
            out.append(("store", g, got_g, p, SL.stripe_period(g)))
    return out


def test_clamp_and_period_store_move_together():
    """The store is (g < 22 ? 2 : 4); it equals stripe_period only for g <= 47.  It is right because the clamp
    stops at 40.  Raise the clamp past 47 and this fails (and so does the raw sweep): the store must then take the
    general form 2 * stripe_rows(g) (max(2, g >> 4) above 21)."""
    assert guard_problems(LIVE) == []
    first_off = next(g for g in range(SL.G_MIN, 200) if (2 if g < 22 else 4) != SL.stripe_period(g))
    assert first_off == 48
    assert SL.G_MAX < first_off, "G_MAX past 47: thunk_ensure_scale's closed-form period store is no longer the law"


# ---- mutants: the tests above must kill them -----------------------------------------------------------------------
def _mutate(code: bytes, old: bytes, new: bytes) -> bytes:
    assert code.count(old) == 1, old
    return code.replace(old, new)


MUTANTS = {
    # the clamp raised to 48 (the store's first wrong g): g = 48..100 would store P = 4, the law is 6
    "clamp 40 -> 48": (b"\x83\xF8\x28\x7E\x05\xB8\x28\x00\x00\x00", b"\x83\xF8\x30\x7E\x05\xB8\x30\x00\x00\x00"),
    # the 2-row threshold moved off STRIPE_2ROW_MIN_G (cmp eax,22 -> cmp eax,21)
    "threshold 22 -> 21": (b"\x83\xF8\x16\x19\xC0", b"\x83\xF8\x15\x19\xC0"),
    # the low clamp dropped to 15 (a sub-native g)
    "clamp 16 -> 15": (b"\x83\xF8\x10\x7D\x05\xB8\x10\x00\x00\x00", b"\x83\xF8\x0F\x7D\x05\xB8\x0F\x00\x00\x00"),
}


@pytest.mark.parametrize("name", list(MUTANTS))
def test_mutants_are_killed(name):
    bad = _mutate(LIVE, *MUTANTS[name])
    assert sweep_problems(bad), f"the raw sweep misses mutant {name}"
    assert guard_problems(bad), f"the clamp/store guard misses mutant {name}"
