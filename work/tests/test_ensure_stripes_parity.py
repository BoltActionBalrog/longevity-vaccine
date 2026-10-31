"""Differential: thunk_ensure_stripes (pcave2 +0x2DA0) under Unicorn, the REAL patches.yaml bytes.

thunk_ensure_stripes has NO source script: its bytes live only in patches.yaml, so this file PINS them (the template
below) and states their behaviour:

    if g_popup_scale_num == g_stripe_g: return (cache; nothing called, nothing written)
    g_stripe_g = g; P = [g_stripe_period]; hN = (P+1) >> 1
    for (cell, top, mate) in (g_stripe_navy, C4, 41), (g_stripe_sel, E0, E1)      (scaling_laws.STRIPE_TILE_PAIRS):
        lazily crt_malloc(0x588) + Buffer_ctor the tile Buffer; Buffer_resize(0x800, P); Buffer_set_clip(0, 0, 0x800, P)
        Buffer_fill_3((0, 0, 0x800, hN), top); Buffer_fill_3((0, hN, 0x800, P), mate)
    -> every tile row == scaling_laws.stripe_tile_rows(top, mate, g)

for every g 16..60 (the cell holds stripe_period(g): what thunk_ensure_scale stores, and what a raised clamp with a
general store would feed it above 40).  Contract: plain CALL helper, preserves ebx / esi / edi / ebp.

Engine callees are hooked (hlt stubs + Python bodies), as in test_stripes_fdphase_asm_parity / test_se_asm_parity.
Skips (does not fail) if unicorn is absent.
"""
from __future__ import annotations

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
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

# The live entry, verbatim (patches.yaml cave pcave2, id thunk_ensure_stripes, 320 B).  A change to these bytes must
# change this pin in the same commit -- there is no assembler to regenerate them from.
PINNED = (
    "A1 {abs32:g_popup_scale_num} 3B 05 {abs32:g_stripe_g} 75 01 C3 53 56 57 A3 {abs32:g_stripe_g} 8B 1D 9C 87 66 00 "
    "8D 73 01 D1 EE A1 {abs32:g_stripe_navy} 85 C0 75 1B 68 88 05 00 00 E8 {rel32:crt_malloc} 83 C4 04 8B C8 50 "
    "E8 {rel32:Buffer_ctor} 58 A3 {abs32:g_stripe_navy} 8B F8 53 68 00 08 00 00 8B CF E8 {rel32:Buffer_resize} 33 C0 "
    "A3 {abs32:g_stripe_rect_l} A3 {abs32:g_stripe_rect_t} C7 05 {abs32:g_stripe_rect_r} 00 08 00 00 "
    "89 1D {abs32:g_stripe_rect_b} 68 {abs32:g_stripe_rect_l} 8B CF E8 {rel32:Buffer_set_clip} "
    "89 35 {abs32:g_stripe_rect_b} 68 C4 00 00 00 68 {abs32:g_stripe_rect_l} 8B CF E8 {rel32:Buffer_fill_3} "
    "89 35 {abs32:g_stripe_rect_t} 89 1D {abs32:g_stripe_rect_b} 6A 41 68 {abs32:g_stripe_rect_l} 8B CF "
    "E8 {rel32:Buffer_fill_3} A1 {abs32:g_stripe_sel} 85 C0 75 1B 68 88 05 00 00 E8 {rel32:crt_malloc} 83 C4 04 "
    "8B C8 50 E8 {rel32:Buffer_ctor} 58 A3 {abs32:g_stripe_sel} 8B F8 53 68 00 08 00 00 8B CF E8 {rel32:Buffer_resize} "
    "33 C0 A3 {abs32:g_stripe_rect_l} A3 {abs32:g_stripe_rect_t} C7 05 {abs32:g_stripe_rect_r} 00 08 00 00 "
    "89 1D {abs32:g_stripe_rect_b} 68 {abs32:g_stripe_rect_l} 8B CF E8 {rel32:Buffer_set_clip} "
    "89 35 {abs32:g_stripe_rect_b} 68 E0 00 00 00 68 {abs32:g_stripe_rect_l} 8B CF E8 {rel32:Buffer_fill_3} "
    "89 35 {abs32:g_stripe_rect_t} 89 1D {abs32:g_stripe_rect_b} 68 E1 00 00 00 68 {abs32:g_stripe_rect_l} 8B CF "
    "E8 {rel32:Buffer_fill_3} 5F 5E 5B C3")
LEN = 320


def _live():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    for c in caves:
        for e in c.get("contents") or []:
            if e["id"] == "thunk_ensure_stripes":
                va = int(c["virtual_addr"]) + int(e["offset"])
                tpl = " ".join(str(e["bytes"]).split())
                return va, tpl, bytes(ap.ByteTemplate(tpl).resolve(va, sym)), sym
    raise AssertionError("thunk_ensure_stripes not in patches.yaml")


VA, TEMPLATE, LIVE, S = _live()
G, PER = S["g_popup_scale_num"], S["g_stripe_period"]
CALLEES = ("crt_malloc", "Buffer_ctor", "Buffer_resize", "Buffer_set_clip", "Buffer_fill_3")
CELLS = ("g_stripe_navy", "g_stripe_sel")
PAIR_OF = dict(zip(CELLS, SL.STRIPE_TILE_PAIRS))
STACK, MARKER, HEAP = 0x00200000, 0x00300000, 0x00500000
F_DATA, F_W, F_H, F_STRIDE = 0x54, 0x80, 0x84, 0x4A8
REGS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333,
        UC_X86_REG_EBP: 0x44444444}


def _r32(mu, a):
    return struct.unpack("<i", bytes(mu.mem_read(a, 4)))[0]


def _w32(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


def run(code: bytes, g: int, *, pre_g: int = 0, prebuilt: bool = False):
    """One call with g_popup_scale_num = g (the conftest pairing writes the cell stripe_period(g)).
    -> dict(log=[(callee, ecx, args)], tiles={cell: (W, H, rows)}, stripe_g, esp_delta, kept)."""
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {VA & ~0xFFF, (VA + len(code)) & ~0xFFF, G & ~0xFFF, PER & ~0xFFF, S["g_stripe_g"] & ~0xFFF}
    pages |= {S[n] & ~0xFFF for n in CALLEES}
    for p in sorted(pages):
        mu.mem_map(p, 0x1000)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(MARKER, 0x1000)
    mu.mem_map(HEAP, 0x40000)
    mu.mem_write(VA, code)
    mu.mem_write(G, struct.pack("<i", g))
    _w32(mu, S["g_stripe_g"], pre_g)
    bufs = [HEAP, HEAP + 0x20000]
    for cell, buf in zip(CELLS, bufs):
        _w32(mu, S[cell], buf if prebuilt else 0)
        mu.mem_write(buf, b"\xEE" * 0x588)
    pool = list(bufs)
    log = []
    for n in CALLEES:
        mu.mem_write(S[n], b"\xF4")

    def hook(m, _addr, _size, name):
        esp = m.reg_read(UC_X86_REG_ESP)
        ret = _r32(m, esp) & 0xFFFFFFFF
        ecx = m.reg_read(UC_X86_REG_ECX)
        a = [_r32(m, esp + 4 + 4 * i) for i in range(3)]
        if name == "crt_malloc":                  # cdecl (size)
            log.append((name, None, (a[0],)))
            m.reg_write(UC_X86_REG_EAX, pool.pop(0))
            pop = 0
        elif name == "Buffer_ctor":               # thiscall, no args, returns this
            log.append((name, ecx, ()))
            m.reg_write(UC_X86_REG_EAX, ecx)
            pop = 0
        elif name == "Buffer_resize":             # thiscall (w, h) RET 8: a top-down plane at this + 0x1000
            w, h = a[0], a[1]
            log.append((name, ecx, (w, h)))
            _w32(m, ecx + F_W, w)
            _w32(m, ecx + F_H, -h)
            _w32(m, ecx + F_STRIDE, w)
            _w32(m, ecx + F_DATA, ecx + 0x1000)
            m.mem_write(ecx + 0x1000, b"\x55" * (w * h))
            pop = 8
        elif name == "Buffer_set_clip":           # thiscall (rect*) RET 4
            log.append((name, ecx, tuple(_r32(m, a[0] + 4 * i) for i in range(4))))
            pop = 4
        else:                                     # Buffer_fill_3 thiscall (rect*, colour) RET 8, half-open rect
            l, t, r, b = (_r32(m, a[0] + 4 * i) for i in range(4))
            col = a[1] & 0xFF
            log.append((name, ecx, ((l, t, r, b), col)))
            data, pitch = _r32(m, ecx + F_DATA), _r32(m, ecx + F_STRIDE)
            for y in range(t, b):
                m.mem_write(data + y * pitch + l, bytes([col]) * (r - l))
            pop = 8
        m.reg_write(UC_X86_REG_ECX, 0xC1C1C1C1)    # a real callee clobbers the caller-saved registers
        m.reg_write(UC_X86_REG_EDX, 0xD1D1D1D1)
        m.reg_write(UC_X86_REG_ESP, esp + 4 + pop)
        m.reg_write(UC_X86_REG_EIP, ret)
    for n in CALLEES:
        mu.hook_add(UC_HOOK_CODE, hook, user_data=n, begin=S[n], end=S[n])
    sp = STACK
    _w32(mu, sp, MARKER)
    mu.reg_write(UC_X86_REG_ESP, sp)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.emu_start(VA, MARKER, count=5_000_000)
    tiles = {}
    for cell in CELLS:
        buf = _r32(mu, S[cell]) & 0xFFFFFFFF
        if buf and (_r32(mu, buf + F_DATA) & 0xFFFFFFFF) not in (0, 0xEEEEEEEE):   # 0xEE..: never resized
            W, H = _r32(mu, buf + F_W), -_r32(mu, buf + F_H)
            data = _r32(mu, buf + F_DATA)
            tiles[cell] = (W, H, [bytes(mu.mem_read(data + y * W, W)) for y in range(H)])
    return {"log": log, "tiles": tiles, "stripe_g": _r32(mu, S["g_stripe_g"]), "esp": mu.reg_read(UC_X86_REG_ESP) - sp,
            "kept": all(mu.reg_read(r) == v for r, v in REGS.items()), "bufs": bufs}


def law_problems(code: bytes, g: int) -> list:
    """A fresh build at g: the call sequence, the args and both tiles against stripe_tile_rows."""
    res = run(code, g)
    out = []
    p = SL.stripe_period(g)
    hn = (p + 1) >> 1
    want_log = []
    for cell, buf in zip(CELLS, res["bufs"]):
        top, mate = PAIR_OF[cell]
        want_log += [("crt_malloc", None, (0x588,)), ("Buffer_ctor", buf, ()), ("Buffer_resize", buf, (SL.STRIPE_TILE_W, p)),
                     ("Buffer_set_clip", buf, (0, 0, SL.STRIPE_TILE_W, p)),
                     ("Buffer_fill_3", buf, ((0, 0, SL.STRIPE_TILE_W, hn), top)),
                     ("Buffer_fill_3", buf, ((0, hn, SL.STRIPE_TILE_W, p), mate))]
        W, H, rows = res["tiles"].get(cell, (0, 0, []))
        want = [bytes([v]) * SL.STRIPE_TILE_W for v in SL.stripe_tile_rows(top, mate, g)]
        if (W, H) != (SL.STRIPE_TILE_W, p) or rows != want:
            out.append(("tile", g, cell, W, H))
        if [rows[y][0] == top for y in range(H)] != [SL.stripe_top(y, g) for y in range(H)]:
            out.append(("grid", g, cell))
    if res["log"] != want_log:
        out.append(("calls", g, res["log"]))
    if res["stripe_g"] != g or res["esp"] != 4 or not res["kept"]:
        out.append(("contract", g, res["stripe_g"], res["esp"], res["kept"]))
    return out


def test_yaml_bytes_are_pinned():
    assert TEMPLATE == " ".join(PINNED.split()), "thunk_ensure_stripes changed: update PINNED and this test's law"
    assert len(LIVE) == LEN


@pytest.mark.parametrize("g", tuple(range(16, 61)))
def test_tiles_are_stripe_tile_rows(g):
    assert law_problems(LIVE, g) == []


@pytest.mark.parametrize("g", (22, 25, 40, 48))
def test_cached_g_calls_nothing(g):
    """g == g_stripe_g: plain `ret`, no callee, the cache and the tile cells untouched."""
    res = run(LIVE, g, pre_g=g, prebuilt=True)
    assert res["log"] == [] and res["stripe_g"] == g and res["esp"] == 4 and res["kept"]
    assert res["tiles"] == {}                    # the prebuilt Buffers were never resized


@pytest.mark.parametrize("g,pre", [(40, 25), (22, 40), (25, 22), (60, 40)])
def test_g_change_rebuilds_in_place(g, pre):
    """A new g with both tiles already built: no allocation, both Buffers resized and refilled on the law."""
    res = run(LIVE, g, pre_g=pre, prebuilt=True)
    names = [c[0] for c in res["log"]]
    assert "crt_malloc" not in names and "Buffer_ctor" not in names
    assert names == ["Buffer_resize", "Buffer_set_clip", "Buffer_fill_3", "Buffer_fill_3"] * 2
    assert [c[1] for c in res["log"]] == [res["bufs"][0]] * 4 + [res["bufs"][1]] * 4
    for cell in CELLS:
        top, mate = PAIR_OF[cell]
        W, H, rows = res["tiles"][cell]
        assert rows == [bytes([v]) * SL.STRIPE_TILE_W for v in SL.stripe_tile_rows(top, mate, g)]
    assert res["stripe_g"] == g and res["esp"] == 4 and res["kept"]


# ---- mutants: the law sweep must kill them --------------------------------------------------------------------------
MUTANTS = {
    "hN = P >> 1 + 1 (lea esi,[ebx+2])": (b"\x8D\x73\x01\xD1\xEE", b"\x8D\x73\x02\xD1\xEE"),
    "navy top C4 -> C5": (b"\x68\xC4\x00\x00\x00", b"\x68\xC5\x00\x00\x00"),
    "sel members swapped": (b"\x68\xE0\x00\x00\x00", b"\x68\xE1\x00\x00\x00"),
    "tile height = hN (push esi for push ebx at the navy resize)": (b"\x8B\xF8\x53\x68\x00\x08", b"\x8B\xF8\x56\x68\x00\x08"),
}


@pytest.mark.parametrize("name", list(MUTANTS))
def test_mutants_are_killed(name):
    old, new = MUTANTS[name]
    assert LIVE.count(old) >= 1
    bad = LIVE.replace(old, new, 1)
    assert any(law_problems(bad, g) for g in (17, 22, 25, 40, 48, 60)), f"the sweep misses mutant {name}"
