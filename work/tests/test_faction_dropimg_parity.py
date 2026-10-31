"""Differential: thunk_faction_dropimg (pcave2 +0x37900, v3) under Unicorn, the REAL patches.yaml bytes.

A Sprite_draw_2 drop-in (the call @0x607F43 that draws the faction row's drop arrow into its own buffer), the same
contract as test_resampler_parity: ecx = src Sprite, (dest Buffer, key, x, y, num, den), callee-clean RET 0x18.

    gate: g_faction_active == 1 and g_popup_scale_num > 16 and srcW <= 32   else `push Sprite_draw_2 / ret` (the
          caller's exact stack and registers)
    render: the whole dest buffer == scaling_laws.drop_arrow_render(src, W, |H|, g)  (v3, 2026-10-25 W2D F40a:
          mirror-symmetric centre NN, AE / EE and -- when the art holds E1 -- E0 / E1 on the dest-row stripe grid,
          K = ceil(g/16) bands of the 1-px source edge strokes, s x s key corners; x / y / key / num / den ignored)

for every g 17..60 (g = 16 is native; no upper clamp: the thunk reads the period cell, which holds stripe_period(g)),
the three measured state arts (idle AE / EE + 41 glyph; hover + an E0 ring and E0 glyph; pressed E1 / E0 + 41 glyph)
in both phases, square (16g/16) and non-square dest buffers.  Its bytes == assemble_dropdither.ASM.

fix 8 (2026-10-18): the gate was ScreenWidth > 1024, so at g = 16 on a screen wider than 1024 (e.g. 1366 x 768) the
render ran and copied the key-9 corners into the buffer; it is g now (the lo-res gate rule), pinned below and by
test_faction_preview_gate.py (the whole @0x607F43 chain).  Skips (does not fail) if unicorn / keystone are absent.
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
keystone = pytest.importorskip("keystone", reason="keystone absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)


def _live():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    for c in caves:
        for e in c.get("contents") or []:
            if e["id"] == "thunk_faction_dropimg":
                va = int(c["virtual_addr"]) + int(e["offset"])
                return va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, sym)), sym
    raise AssertionError("thunk_faction_dropimg not in patches.yaml")


VA, LIVE, S = _live()
G, PER = S["g_popup_scale_num"], S["g_stripe_period"]
ACTIVE, SCREEN_W, SD2 = S["g_faction_active"], S["ScreenWidth"], S["Sprite_draw_2"]
STACK, MARKER = 0x00200000, 0x00300000
SPR, DST, SRCD, DSTD = 0x0082AD14, 0x00610000, 0x00620000, 0x00630000   # SPR: FactionPickWin+0x85FC, the idle
# drop-arrow sprite (thunk_faction_dropimg v3 renders only the three arrow sprites +0x85FC / +0x8628 / +0x8654)
FILL = 0x77
REGS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333,
        UC_X86_REG_EBP: 0x44444444}
ARGS = (DST, 9, 5, 6, 0x123, 16)                 # dest, key, x, y, num, den: everything but dest is ignored


def _w32(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


def arrow(phase: int, w: int = 16, h: int = 16, state: int = 0):
    """The measured layout (hook_drop_geom; the three state sprites read on the real image, W2D 2026-10-25): state 0
    AE / EE 1-row scanline background, a 41 glyph, key-9 corners; state 1 the same with a 1-px E0 ring on all four
    sides and an E0 glyph (hover); state 2 an E1 / E0 background and a 41 glyph (pressed)."""
    top, mate = ((0xAE, 0xEE), (0xAE, 0xEE), (0xE1, 0xE0))[state]
    rows = []
    for y in range(h):
        r = []
        for x in range(w):
            if (x in (0, w - 1)) and (y in (0, h - 1)):
                r.append(9)
            elif state == 1 and (x in (0, w - 1) or y in (0, h - 1)):
                r.append(0xE0)
            elif 4 <= y <= 10 and abs(x - (w - 1) / 2) <= (10 - y) * 0.8:
                r.append(0xE0 if state == 1 else 0x41)
            else:
                r.append(top if (y + phase) % 2 == 0 else mate)
        rows.append(r)
    return rows


def run(code: bytes, g: int, art, out_w: int, out_h: int, *, active: int = 1, screen_w: int = 3840,
        stride: int | None = None, spr: int = SPR):
    """-> dict(native = entered Sprite_draw_2 with the caller's frame, rows = the dest plane, esp delta, kept)."""
    stride = out_w if stride is None else stride
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {VA & ~0xFFF, (VA + len(code)) & ~0xFFF, G & ~0xFFF, PER & ~0xFFF, ACTIVE & ~0xFFF, SCREEN_W & ~0xFFF,
             SD2 & ~0xFFF}
    for p in sorted(pages):
        mu.mem_map(p, 0x1000)
    for p in (SPR & ~0xFFF, DST, SRCD, DSTD):
        mu.mem_map(p, 0x10000)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(MARKER, 0x1000)
    mu.mem_write(VA, code)
    mu.mem_write(SD2, b"\xF4")
    mu.mem_write(G, struct.pack("<i", g))         # conftest pairs the period cell: stripe_period(g)
    _w32(mu, ACTIVE, active)
    _w32(mu, SCREEN_W, screen_w)
    sh, sw = len(art), len(art[0])
    _w32(mu, spr + 4, SRCD)
    _w32(mu, spr + 0x10, sw)
    _w32(mu, spr + 0x18, sw)
    _w32(mu, spr + 0x1C, sh)
    mu.mem_write(SRCD, b"".join(bytes(r) for r in art))
    _w32(mu, DST + 0x54, DSTD)
    _w32(mu, DST + 0x4A8, stride)
    _w32(mu, DST + 0x80, out_w)
    _w32(mu, DST + 0x84, -out_h)
    mu.mem_write(DSTD, bytes([FILL]) * (stride * out_h + 64))
    sp = STACK
    frame = struct.pack("<I6I", MARKER, *ARGS)
    mu.mem_write(sp, frame)
    seen = {}

    def sd2(m, _a, _s, _u):
        esp = m.reg_read(UC_X86_REG_ESP)
        seen.update(esp=esp, frame=bytes(m.mem_read(esp, len(frame))), ecx=m.reg_read(UC_X86_REG_ECX),
                    regs=tuple(m.reg_read(r) for r in REGS))
        m.emu_stop()
    mu.hook_add(UC_HOOK_CODE, sd2, begin=SD2, end=SD2)
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ECX, spr)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.emu_start(VA, MARKER, count=20_000_000)
    rows = [list(mu.mem_read(DSTD + y * stride, out_w)) for y in range(out_h)]
    tail = bytes(mu.mem_read(DSTD + stride * out_h, 64))
    return {"native": seen, "rows": rows, "tail_clean": tail == bytes([FILL]) * 64,
            "esp": mu.reg_read(UC_X86_REG_ESP) - sp, "kept": all(mu.reg_read(r) == v for r, v in REGS.items())}


DIMS = lambda g: ((16 * g) >> 4, (16 * g) >> 4)  # noqa: E731  the per-dropdown buffer: 16 native px at g


def render_problems(code: bytes, g: int, states=(0, 1, 2)) -> list:
    out = []
    for state in states:
        for phase in (0, 1):
            art = arrow(phase, state=state)
            for (w, h) in (DIMS(g), (DIMS(g)[0] + 7, max(1, DIMS(g)[1] - 5))):
                res = run(code, g, art, w, h, stride=w + 3)
                want = SL.drop_arrow_render(art, w, h, g)
                if res["native"] or res["rows"] != want or not res["tail_clean"]:
                    out.append(("render", g, state, phase, w, h))
                if res["esp"] != 4 + 0x18 or not res["kept"]:
                    out.append(("contract", g, res["esp"], res["kept"]))
    return out


def test_yaml_bytes_are_the_assembler_source():
    import assemble_dropdither as DD
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    clean = "\n".join(ln.split(";", 1)[0].rstrip() for ln in DD.ASM.splitlines() if ln.split(";", 1)[0].strip())
    assert DD.THUNK_VA == VA
    assert bytes(ks.asm(clean, DD.THUNK_VA)[0]) == LIVE


@pytest.mark.parametrize("g", tuple(range(17, 61)))
def test_render_is_drop_arrow_render(g):
    assert render_problems(LIVE, g) == []


def test_law_puts_ae_on_the_stripe_top_rows():
    """AE / EE land on the dest-row grid (T rows each) whatever the art's phase; glyph and key copied."""
    for g in (17, 22, 25, 40, 48, 60):
        w, h = DIMS(g)
        for phase in (0, 1):
            rows = SL.drop_arrow_render(arrow(phase), w, h, g)
            for y in range(h):
                for v in rows[y]:
                    if v in SL.DROP_ARROW_PAIR:
                        assert v == (0xAE if SL.stripe_top(y, g) else 0xEE), (g, phase, y)
            assert rows[0][0] == rows[0][w - 1] == rows[h - 1][0] == rows[h - 1][w - 1] == 9


GATE = [("inactive", dict(active=0)), ("active = 2", dict(active=2)), ("g 16", dict(g=16)),
        ("g 16 on a 1366 screen", dict(g=16, screen_w=1366)), ("g 16 on a 1280 screen", dict(g=16, screen_w=1280)),
        ("g 0 (before thunk_ensure_scale)", dict(g=0)), ("src 33 wide", dict(src_w=33))]


@pytest.mark.parametrize("why,kw", GATE, ids=[x[0] for x in GATE])
def test_gate_falls_through_to_sprite_draw_2(why, kw):
    """Outside the gate: `push Sprite_draw_2 / ret` -- entered on the caller's own stack with ecx and every argument
    as the caller left them; the dest untouched."""
    src_w = kw.pop("src_w", 16)
    g = kw.pop("g", 40)
    art = [[0xAE] * src_w for _ in range(16)]
    res = run(LIVE, g, art, 40, 40, **kw)
    n = res["native"]
    assert n and n["esp"] == STACK and n["ecx"] == SPR, why
    assert n["frame"] == struct.pack("<I6I", MARKER, *ARGS) and n["regs"] == tuple(REGS.values()), why
    assert all(v == FILL for row in res["rows"] for v in row), why


def test_gate_is_g_not_screen_width():
    """g = 16 on a screen wider than 1024 (1280x720 / 1360x768 / 1366x768) is native, whatever the art's phase; g > 16
    renders on a screen of any width (g > 16 with W <= 1024 does not occur in the game -- scale_uniform -- but the gate
    must read g, not the width)."""
    for w in (1280, 1360, 1366, 3840):
        for phase in (0, 1):
            res = run(LIVE, 16, arrow(phase), 16, 16, screen_w=w)
            assert res["native"] and all(v == FILL for row in res["rows"] for v in row), (w, phase)
    for g, w in ((20, 768), (25, 1024), (18, 1152), (40, 3840)):
        art = arrow(0)
        dims = DIMS(g)
        res = run(LIVE, g, art, *dims, screen_w=w)
        assert not res["native"] and res["rows"] == SL.drop_arrow_render(art, *dims, g), (g, w)


ARROW_SPRITES = (0x0082AD14, 0x0082AD40, 0x0082AD6C)    # FactionPickWin+0x85FC / +0x8628 / +0x8654 (idle / hover / pressed)


@pytest.mark.parametrize("g", (17, 25, 40))
def test_only_the_drop_arrow_sprites_render(g):
    """v3 gate (2026-10-25 audit): any other <= 32 px state sprite drawn while the picker runs -- a ScrollBar arrow of a
    popup opened from it -- is the engine's own Sprite_draw_2, untouched; the three arrow sprites render."""
    art = arrow(0, state=1)
    for spr in ARROW_SPRITES:
        res = run(LIVE, g, art, *DIMS(g), spr=spr)
        assert not res["native"] and res["rows"] == SL.drop_arrow_render(art, *DIMS(g), g), (g, hex(spr))
    for spr in (0x0082AD15, 0x0082AD10, 0x0082AD84, 0x0082A000):
        res = run(LIVE, g, art, *DIMS(g), spr=spr)
        assert res["native"] and res["native"]["ecx"] == spr and all(v == FILL for r in res["rows"] for v in r), hex(spr)


# ---- mutants: the render sweep must kill them -----------------------------------------------------------------------
# (v3: source-level mutants of assemble_dropdither.ASM, assembled at the live VA)
MUTANTS = {
    "AE / EE swapped on the stripe rows": ("    mov     al, 0xae\n    cmp     dword ptr [ebp-0x30], 0\n    jne     write\n"
                                           "    mov     al, 0xee",
                                           "    mov     al, 0xee\n    cmp     dword ptr [ebp-0x30], 0\n    jne     write\n"
                                           "    mov     al, 0xae"),
    "setb -> setbe (hN + 1 top rows)": ("    setb    cl", "    setbe   cl"),
    "EE no longer recognised as background": ("    cmp     al, 0xee\n    je      pair_a",
                                              "    cmp     al, 0xed\n    je      pair_a"),
    "plain centre NN (no mirror half)": ("    jle     m_first", "    jmp     m_first"),
    "E0 regenerated without the E1 key": ("    cmp     dword ptr [ebp-0x2c], 0\n    je      write\n",
                                          "    cmp     dword ptr [ebp-0x2c], 0\n    nop\n"),
    "no E1 / E0 regeneration (v2)": ("    cmp     al, 0xe1\n    je      pair_e", "    cmp     al, 0x55\n    je      pair_e"),
    "TL corner left as the NN notch": ("    mov     al, 9\n    cmp     byte ptr [esi], 9\n    jne     nc0",
                                       "    mov     al, 9\n    cmp     byte ptr [esi], 0x55\n    jne     nc0"),
    "no top band": ("    mov     ebx, [ebp-0x04]\n    call    chk\n    jc      nb0",
                    "    mov     ebx, [ebp-0x04]\n    stc\n    jc      nb0"),
    "band / notch K = g >> 4 (floor)": ("    add     eax, 15\n    sar     eax, 4\n    mov     [ebp-0x34], eax",
                                        "    sar     eax, 4\n    mov     [ebp-0x34], eax"),
}


def _mutant_bytes(old: str, new: str) -> bytes:
    import assemble_dropdither as DD
    assert DD.ASM.count(old) == 1, old
    src = DD.ASM.replace(old, new)
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    clean = "\n".join(ln.split(";", 1)[0].rstrip() for ln in src.splitlines() if ln.split(";", 1)[0].strip())
    return bytes(ks.asm(clean, DD.THUNK_VA)[0])


@pytest.mark.parametrize("name", list(MUTANTS))
def test_mutants_are_killed(name):
    bad = _mutant_bytes(*MUTANTS[name])
    assert bad != LIVE, name
    assert any(render_problems(bad, g) for g in (17, 22, 24, 25, 40, 48, 60)), f"the sweep misses mutant {name}"
