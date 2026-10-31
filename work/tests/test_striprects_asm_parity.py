"""Differential: the assembled thunk_bw_striprects must agree with
scaling_laws.basewin_strip_seed_rects bit-exactly, and thunk_hud_vehargs v2
must keep v1 semantics except the new zoom/BaseWin-caller skip gate.

striprects is emulated with the REAL assembled bytes: region globals written at
the live MainWin addresses, g at the sentinel page (the yaml resolves the
placeholder to 0x668740 at apply time; the raw assembly keeps 0xDEADBE00),
BaseWin field stores read back from the static instance addresses. Verified:

  * g=40 / g=25 with the LIVE region vectors from frida_basewin_strip.log ==
    the law's golden outputs, all 13 rects + the 0x40e6c queue-hdr copy;
  * a g sweep 17..40 with vanilla-x-g/16 modeled regions == the law;
  * g=16: gate falls through, every field byte-untouched;
  * registers + esp preserved; exit lands at Font_init.

vehargs v2: sentinel rewrite skipped ONLY for BaseWin-range callers with the
engine zoom armed; garrison-style calls (zoom unset) still rewritten; the
StatusWin x-inset arm and the buf/g gates byte-compatible with v1.

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_strip_rects as ASR  # noqa: E402

STRIP_VA = ASR.PCAVE2_VA + ASR.STRIPRECTS_OFF
VEH_VA = ASR.PCAVE2_VA + ASR.VEHARGS_OFF
STRIP_CODE = ASR.raw("striprects", ASR.STRIPRECTS_OFF, ASR.asm_striprects())
VEH_CODE = ASR.raw("vehargs", ASR.VEHARGS_OFF, ASR.asm_vehargs_v2())

G_SENT = 0xDEADBE00
G_REAL = ASR.S["g_popup_scale_real"]
ZOOM = ASR.S["g_map_zoom_num"]
FONT_INIT = ASR.S["Font_init"]
RESUME = ASR.S["VEH_DRAW_RESUME"]
BW = ASR.S["BaseWin_g"]

FIELD_KEYS = {
    0x40C6C: "production", 0x40C2C: "garrison",
    0x40DEC: "turnsA", 0x40DFC: "turnsB",
    0x40C9C: "queue_outer", 0x40C7C: "queue_hdr", 0x40C8C: "queue_list",
    0x40C5C: "pop", 0x40CAC: "plate", 0x40E2C: "redbtn",
    0x40B7C: "sup_outer", 0x40B5C: "sup_hdr", 0x40B6C: "sup_list",
}

REGIONS_G40 = {"A": (10, 140, 612, 630), "S": (1947, 140, 2550, 630),
               "C": (655, 165, 1907, 430), "G": (610, 470, 1920, 630)}
REGIONS_G25 = {"A": (6, 87, 382, 393), "S": (1217, 87, 1593, 393),
               "C": (409, 103, 1192, 268), "G": (381, 293, 1200, 393)}

STACK = 0x00200000


def _mk_uc():
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0xA19000, 0x1000)                  # cave page (both thunks)
    uc.mem_map(0x6E8000, 0x1000)                  # BaseWin strip fields
    uc.mem_map(0x7AF000, 0x1000)                  # MainWin region globals
    uc.mem_map(0xDEADB000, 0x1000)                # sentinel g page
    uc.mem_map(0x668000, 0x1000)                  # real g page (vehargs)
    uc.mem_map(0x691000, 0x1000)                  # zoom global
    uc.mem_map(0x618000, 0x1000)                  # Font_init landing pad
    uc.mem_map(0x559000, 0x1000)                  # veh_draw resume pad
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(0xA19000 + (STRIP_VA - 0xA19000), STRIP_CODE)
    uc.mem_write(VEH_VA, VEH_CODE)
    uc.mem_write(FONT_INIT, b"\xC3")
    uc.mem_write(RESUME, b"\xC3")
    return uc


def _w32(uc, addr, v):
    uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(uc, addr):
    return int.from_bytes(uc.mem_read(addr, 4), "little")


def _run_striprects(g, regions):
    uc = _mk_uc()
    _w32(uc, G_SENT, g)
    for name, base in (("A", 0x7AF5A0), ("S", 0x7AF5B0),
                       ("C", 0x7AF5C0), ("G", 0x7AF5D0)):
        for i, v in enumerate(regions[name]):
            _w32(uc, base + 4 * i, v)
    for off in FIELD_KEYS:
        for i in range(4):
            _w32(uc, BW + off + 4 * i, 0xAAAAAAAA)
    for i in range(4):
        _w32(uc, BW + 0x40E6C + 4 * i, 0xAAAAAAAA)
    esp0 = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0, 0x0041F2A6)                    # site ret addr
    marks = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ECX: 0x22222222,
             UC_X86_REG_EDX: 0x33333333, UC_X86_REG_ESI: 0x44444444,
             UC_X86_REG_EDI: 0x55555555, UC_X86_REG_EBP: 0x66666666}
    for r, v in marks.items():
        uc.reg_write(r, v)
    uc.emu_start(STRIP_VA, FONT_INIT, count=100000)
    assert uc.reg_read(UC_X86_REG_EIP) == FONT_INIT
    assert uc.reg_read(UC_X86_REG_ESP) == esp0, "esp must be untouched at the tail jmp"
    for r, v in marks.items():
        assert uc.reg_read(r) == v, f"register {r} clobbered"
    out = {}
    for off, key in FIELD_KEYS.items():
        out[key] = tuple(
            int.from_bytes(uc.mem_read(BW + off + 4 * i, 4), "little")
            for i in range(4))
    out["e6c_copy"] = tuple(
        int.from_bytes(uc.mem_read(BW + 0x40E6C + 4 * i, 4), "little")
        for i in range(4))
    return out


def _signed(t):
    return tuple(v - 0x100000000 if v >= 0x80000000 else v for v in t)


@pytest.mark.parametrize("g,regions", [(40, REGIONS_G40), (25, REGIONS_G25)])
def test_striprects_matches_law_live_vectors(g, regions):
    got = _run_striprects(g, regions)
    want = SL.basewin_strip_seed_rects(g=g, **regions)
    for key, rect in want.items():
        assert _signed(got[key]) == rect, (g, key)
    assert got["e6c_copy"] == got["queue_hdr"]


def test_striprects_matches_law_sweep():
    fl = SL.popup_scale_floor
    for g in range(17, 41):
        regions = {k: tuple(fl(v, g) for v in rect)
                   for k, rect in SL.BASEWIN_STRIP_REGIONS_NATIVE.items()}
        got = _run_striprects(g, regions)
        want = SL.basewin_strip_seed_rects(g=g, **regions)
        for key, rect in want.items():
            assert _signed(got[key]) == rect, (g, key)


def test_striprects_native_g_is_a_noop():
    got = _run_striprects(16, {k: v for k, v in
                               SL.BASEWIN_STRIP_REGIONS_NATIVE.items()})
    for key in list(FIELD_KEYS.values()) + ["e6c_copy"]:
        assert got[key] == (0xAAAAAAAA,) * 4, key


# ---------------------------------------------------------------------------
# thunk_hud_vehargs v2
# ---------------------------------------------------------------------------

def _run_vehargs(buf, caller, size, g, zoom, x=100):
    uc = _mk_uc()
    _w32(uc, G_REAL, g)
    _w32(uc, ZOOM, zoom)
    esp0 = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0 + 0x00, 0x5594F5)      # thunk ret (into veh_draw entry+5)
    _w32(uc, esp0 + 0x04, caller)        # caller ret
    _w32(uc, esp0 + 0x08, buf)           # arg1 buf
    _w32(uc, esp0 + 0x0C, 3)             # veh id
    _w32(uc, esp0 + 0x10, x)             # arg3 x
    _w32(uc, esp0 + 0x14, 200)           # arg4 y
    _w32(uc, esp0 + 0x18, size & 0xFFFFFFFF)  # arg5 size
    uc.emu_start(VEH_VA, RESUME, count=10000)
    assert uc.reg_read(UC_X86_REG_EIP) == RESUME
    sz = _r32(uc, esp0 + 0x18)
    if sz >= 0x80000000:
        sz -= 0x100000000
    return sz, _r32(uc, esp0 + 0x10)


STRIP_BUF = ASR.S["STRIP_CANVAS"]


def test_vehargs_rewrites_sentinel_when_zoom_unset():
    # garrison-style: BaseWin caller, zoom -1 -> (16-7)*40/16-16 = 6
    sz, _ = _run_vehargs(STRIP_BUF, 0x004105AA, -7, 40, 0xFFFFFFFF)
    assert sz == SL.veh_size_scaled(-7, 40) == 6


def test_vehargs_skips_sentinel_for_basewin_caller_with_zoom_armed():
    # production-style: zoom armed by the caller -> sentinel untouched
    sz, _ = _run_vehargs(STRIP_BUF, 0x0040E7AF, 1, 40, 245)
    assert sz == 1


def test_vehargs_still_rewrites_outside_basewin_even_with_zoom_armed():
    sz, _ = _run_vehargs(STRIP_BUF, 0x004B9999, 1, 40, 245)
    assert sz == SL.veh_size_scaled(1, 40) == 26


def test_vehargs_v1_gates_unchanged():
    # wrong buf -> untouched
    sz, _ = _run_vehargs(0x123456, 0x004105AA, -7, 40, 0xFFFFFFFF)
    assert sz == -7
    # g native -> untouched
    sz, _ = _run_vehargs(STRIP_BUF, 0x004105AA, -7, 16, 0xFFFFFFFF)
    assert sz == -7
    # real (non-sentinel) size -> untouched (law identity for |s|>16)
    sz, _ = _run_vehargs(STRIP_BUF, 0x004105AA, 100, 40, 0xFFFFFFFF)
    assert sz == SL.veh_size_scaled(100, 40) == 100
    # StatusWin caller x-inset arm: x += 11*40/16 - 11 = 16
    sz, x = _run_vehargs(STRIP_BUF, ASR.S["STATUSWIN_RET_A"], -7, 40,
                         0xFFFFFFFF, x=100)
    assert x == 116 and sz == SL.veh_size_scaled(-7, 40)
