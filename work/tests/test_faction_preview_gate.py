"""The faction picker's +0xad4 state-sprite chain under Unicorn, the REAL patches.yaml bytes: the lo-res gate is on g.

The site @0x607F43 (FlatButton_content_draw: `call Sprite_draw_2`, the leader-preview images and the row drop arrows,
both drawn at native (1, 1)) enters t_hof_face -> t_rw_iconblit -> thunk_faction_portrait -> thunk_faction_dropimg ->
Sprite_draw_2.  Law (CLAUDE.md lo-res gate, memory feedback_loores_gate_on_g): g = g_popup_scale_num <= 16 is a native
no-op -- the caller's own Sprite_draw_2 call, byte for byte -- whatever the screen WIDTH.  g > 16:

    preview (srcW > 32): thunk_sprite_scale_nn with num = g, den = 16, x = y = 0 (fills the g/16 buffer)
    arrow   (srcW <= 32): thunk_faction_dropimg's render == scaling_laws.drop_arrow_render

fix 8 (2026-10-18): both thunks gated on ScreenWidth > 1024 instead.  At g = 16 on a 1280..1366-wide screen
(1280x720 / 768 / 800, 1360x768, 1366x768) the preview went through the scaler at 16/16 from (0, 0) -- 1 px up-left of
vanilla's (1, 1) -- and the arrow render copied its key-9 corners into the buffer.  The mutants below put the width
gate back and must be killed.  g > 16 with a width <= 1024 is unreachable in the game (scale_uniform is min(W/1024,
H/768), so g > 16 needs W >= 1088: pinned below on the real scale_uniform / thunk_ensure_scale bytes) but is driven
synthetically to prove the gate reads g.  Skips (does not fail) if unicorn / keystone are absent.
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
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP)

CHAIN = ("t_hof_face", "t_rw_iconblit", "thunk_faction_portrait", "thunk_faction_dropimg")


def _load():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    tmpl = {}
    for c in caves:
        for e in c.get("contents") or []:
            tmpl[e["id"]] = (int(c["virtual_addr"]) + int(e["offset"]), " ".join(str(e["bytes"]).split()))
    return sym, tmpl


S, TMPL = _load()


def _bytes(name: str, template: str | None = None) -> bytes:
    va, t = TMPL[name]
    return bytes(ap.ByteTemplate(template or t).resolve(va, S))


LIVE = {n: _bytes(n) for n in CHAIN}
for _n in ("scale_uniform", "thunk_ensure_scale"):
    LIVE[_n] = _bytes(_n)

G, ACTIVE, ARMED = S["g_popup_scale_num"], S["g_faction_active"], S["g_hof_armed"]
SCREEN_W, SCREEN_H = S["ScreenWidth"], S["ScreenHeight"]
SD2, NN = S["Sprite_draw_2"], S["thunk_sprite_scale_nn"]
STACK, MARKER = 0x00200000, 0x00300000
SPR, DST, SRCD, DSTD = 0x0082AD14, 0x00610000, 0x00620000, 0x00630000   # SPR: FactionPickWin+0x85FC, the idle
# drop-arrow sprite (thunk_faction_dropimg v3 renders only the three arrow sprites +0x85FC / +0x8628 / +0x8654)
FILL = 0x77
REGS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333,
        UC_X86_REG_EBP: 0x44444444}
CALLER = (DST, 9, 1, 1, 1, 1)                    # dest, key, x = 1, y = 1, num = 1, den = 1: vanilla's native blit
PREVIEW, ARROW = (258, 90), (16, 16)

# (g, screen width): the resolutions the gate decides.  g = 16 with W > 1024 is the fix-8 case.
LORES_WIDE = [(16, 1280), (16, 1360), (16, 1366)]
HIRES = [(17, 1088), (18, 1152), (18, 1600), (20, 1280), (22, 1920), (25, 1600), (40, 3840)]   # 1088x816 = g 17
NARROW_SYNTH = [(20, 768), (25, 1024)]           # unreachable in the game; the gate must still read g


def arrow(phase: int = 0, w: int = 16, h: int = 16):
    """The measured drop arrow (hook_drop_geom): AE / EE 1-row scanlines, a 41 glyph, key-9 corners."""
    rows = []
    for y in range(h):
        r = []
        for x in range(w):
            if (x in (0, w - 1)) and (y in (0, h - 1)):
                r.append(9)
            elif 4 <= y <= 10 and abs(x - (w - 1) / 2) <= (10 - y) * 0.8:
                r.append(0x41)
            else:
                r.append(0xAE if (y + phase) % 2 == 0 else 0xEE)
        rows.append(r)
    return rows


def _w32(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


def run(code: dict, g: int, screen_w: int, src_wh, *, entry: str = "t_hof_face", out_wh=(40, 40), active: int = 1):
    """Call the chain at `entry` with vanilla's frame.  -> dict(stop = 'sd2' | 'nn' | 'ret', frame / esp / ecx at the
    stop, rows = the dest plane, esp delta on a return, kept = callee-saved registers intact)."""
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {G & ~0xFFF, ACTIVE & ~0xFFF, ARMED & ~0xFFF, SCREEN_W & ~0xFFF, SD2 & ~0xFFF, NN & ~0xFFF}
    for n in CHAIN:
        va = TMPL[n][0]
        pages |= {va & ~0xFFF, (va + len(code[n])) & ~0xFFF}
    for p in sorted(pages):
        mu.mem_map(p, 0x1000)
    for p in (SPR & ~0xFFF, DST, SRCD, DSTD):
        mu.mem_map(p, 0x10000)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(MARKER, 0x1000)
    for n in CHAIN:
        mu.mem_write(TMPL[n][0], code[n])
    mu.mem_write(SD2, b"\xF4")
    mu.mem_write(NN, b"\xF4")
    mu.mem_write(G, struct.pack("<i", g))          # conftest pairs the period cell: stripe_period(g)
    _w32(mu, ACTIVE, active)
    _w32(mu, ARMED, 0)                             # not the Hall of Fame
    _w32(mu, SCREEN_W, screen_w)
    sw, sh = src_wh
    art = arrow(0, sw, sh)
    _w32(mu, SPR + 4, SRCD)
    _w32(mu, SPR + 0x0C, sw)
    _w32(mu, SPR + 0x10, sw)
    _w32(mu, SPR + 0x14, sh)
    _w32(mu, SPR + 0x18, sw)
    _w32(mu, SPR + 0x1C, sh)
    mu.mem_write(SRCD, b"".join(bytes(r) for r in art))
    ow, oh = out_wh
    _w32(mu, DST + 0x54, DSTD)
    _w32(mu, DST + 0x4A8, ow)
    _w32(mu, DST + 0x80, ow)
    _w32(mu, DST + 0x84, -oh)
    mu.mem_write(DSTD, bytes([FILL]) * (ow * oh))
    frame = struct.pack("<I6I", MARKER, *CALLER)
    mu.mem_write(STACK, frame)
    seen = {}

    def stop(kind):
        def hook(m, _a, _s, _u):
            esp = m.reg_read(UC_X86_REG_ESP)
            seen.update(stop=kind, esp=esp, frame=struct.unpack("<I6I", bytes(m.mem_read(esp, len(frame)))),
                        ecx=m.reg_read(UC_X86_REG_ECX), regs=tuple(m.reg_read(r) for r in REGS))
            m.emu_stop()
        return hook
    mu.hook_add(UC_HOOK_CODE, stop("sd2"), begin=SD2, end=SD2)
    mu.hook_add(UC_HOOK_CODE, stop("nn"), begin=NN, end=NN)
    mu.reg_write(UC_X86_REG_ESP, STACK)
    mu.reg_write(UC_X86_REG_ECX, SPR)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.emu_start(TMPL[entry][0], MARKER, count=5_000_000)
    if not seen:
        seen.update(stop="ret", esp=mu.reg_read(UC_X86_REG_ESP) - STACK,
                    regs=tuple(mu.reg_read(r) for r in REGS))
    seen["rows"] = [list(mu.mem_read(DSTD + y * ow, ow)) for y in range(oh)]
    seen["art"] = art
    return seen


def is_vanilla(res) -> bool:
    """Sprite_draw_2 entered on the caller's own stack with ecx and every argument as the caller left them."""
    return (res["stop"] == "sd2" and res["esp"] == STACK and res["ecx"] == SPR
            and res["frame"] == (MARKER, *CALLER) and res["regs"] == tuple(REGS.values())
            and all(v == FILL for row in res["rows"] for v in row))


def is_scaled_preview(res, g: int) -> bool:
    """thunk_sprite_scale_nn entered with num = g, den = 16, x = y = 0, the dest and key untouched."""
    return (res["stop"] == "nn" and res["esp"] == STACK and res["ecx"] == SPR
            and res["frame"] == (MARKER, DST, 9, 0, 0, g, 16) and res["regs"] == tuple(REGS.values()))


def is_rendered_arrow(res, g: int, out_wh) -> bool:
    w, h = out_wh
    return (res["stop"] == "ret" and res["esp"] == 4 + 0x18 and res["regs"] == tuple(REGS.values())
            and res["rows"] == SL.drop_arrow_render(res["art"], w, h, g))


def gate_problems(code: dict, entry: str = "t_hof_face") -> list:
    """Every (g, width) case of the law the chain `code` breaks."""
    bad = []
    for g, w in LORES_WIDE + [(16, 1024), (16, 800)]:
        if not is_vanilla(run(code, g, w, PREVIEW, entry=entry, out_wh=PREVIEW)):
            bad.append(("preview not vanilla", g, w))
        if not is_vanilla(run(code, g, w, ARROW, entry=entry, out_wh=ARROW)):
            bad.append(("arrow not vanilla", g, w))
    for g, w in HIRES + NARROW_SYNTH:
        if not is_scaled_preview(run(code, g, w, PREVIEW, entry=entry, out_wh=(64, 64)), g):   # the scaler is a stub
            bad.append(("preview not scaled", g, w))
        dims = ((16 * g) >> 4, (16 * g) >> 4)
        if not is_rendered_arrow(run(code, g, w, ARROW, entry=entry, out_wh=dims), g, dims):
            bad.append(("arrow not rendered", g, w))
    return bad


@pytest.mark.parametrize("entry", ["t_hof_face", "thunk_faction_portrait"])
def test_chain_obeys_the_g_gate(entry):
    """From the site's target (t_hof_face, not armed -> t_rw_iconblit -> portrait) and from the portrait itself."""
    assert gate_problems(LIVE, entry) == []


@pytest.mark.parametrize("g,w", LORES_WIDE)
def test_g16_wide_screen_is_vanillas_own_blit(g, w):
    """1280x720 / 1360x768 / 1366x768 (g = 16): the preview draws at the caller's (1, 1) through the engine, not at
    (0, 0) through the scaler; the arrow is the engine's keyed blit, not the render (no key-9 corner written)."""
    pre = run(LIVE, g, w, PREVIEW, out_wh=PREVIEW)
    assert is_vanilla(pre) and pre["frame"][3:5] == (1, 1)
    arr = run(LIVE, g, w, ARROW, out_wh=ARROW)
    assert is_vanilla(arr)


def test_inactive_faction_flag_is_native_at_every_g():
    for g, w in LORES_WIDE + HIRES:
        for wh in (PREVIEW, ARROW):
            assert is_vanilla(run(LIVE, g, w, wh, out_wh=wh, active=0)), (g, w, wh)


# ---- g > 16 is the old width gate's behaviour, unchanged (the bytes moved 3 B, the outcomes did not) ------------------

OLD_PORTRAIT = TMPL["thunk_faction_portrait"][1].replace(
    "01 75 38 83 3D {abs32:g_popup_scale_num} 10 7E 2F", "01 75 3B 81 3D {abs32:ScreenWidth} 00 04 00 00 7E 2F")


def _old_dropimg() -> bytes:
    import assemble_dropdither as DD
    src = DD.ASM.replace("cmp     dword ptr [0x00668740], 0x10", "cmp     dword ptr [0x009B7B1C], 0x400")
    assert src != DD.ASM
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    clean = "\n".join(ln.split(";", 1)[0].rstrip() for ln in src.splitlines() if ln.split(";", 1)[0].strip())
    return bytes(ks.asm(clean, DD.THUNK_VA)[0])


MUTANTS = {
    "portrait gated on ScreenWidth > 1024": {"thunk_faction_portrait": OLD_PORTRAIT},
    "dropimg gated on ScreenWidth > 1024": {"thunk_faction_dropimg": None},
    "both gated on ScreenWidth > 1024 (the pre-fix-8 bytes)": {"thunk_faction_portrait": OLD_PORTRAIT,
                                                                "thunk_faction_dropimg": None},
}


def _mutant(name: str) -> dict:
    code = dict(LIVE)
    for n, t in MUTANTS[name].items():
        code[n] = _bytes(n, t) if t else _old_dropimg()
    return code


def test_old_gate_template_is_the_pre_fix_bytes():
    assert OLD_PORTRAIT != TMPL["thunk_faction_portrait"][1]
    assert len(_bytes("thunk_faction_portrait", OLD_PORTRAIT)) == 74 and len(LIVE["thunk_faction_portrait"]) == 71
    # v3 (2026-10-25 W2D F40a, 797 B): the width gate is 3 B longer than the g gate (cmp imm32 vs imm8), as in v2
    assert len(_old_dropimg()) == len(LIVE["thunk_faction_dropimg"]) + 3


@pytest.mark.parametrize("g,w", HIRES)
def test_hires_outcome_equals_the_pre_fix_bytes(g, w):
    """Every reachable g > 16 (W > 1024): the old and the new chain stop at the same place with the same frame /
    render -- the fix moves only g = 16 on a wide screen."""
    old = _mutant("both gated on ScreenWidth > 1024 (the pre-fix-8 bytes)")
    dims = ((16 * g) >> 4, (16 * g) >> 4)
    for wh, out in ((PREVIEW, (64, 64)), (ARROW, dims)):
        a, b = run(LIVE, g, w, wh, out_wh=out), run(old, g, w, wh, out_wh=out)
        for k in ("stop", "esp", "frame", "ecx", "regs", "rows"):
            assert a.get(k) == b.get(k), (g, w, wh, k)


@pytest.mark.parametrize("name", list(MUTANTS))
def test_width_gate_mutants_are_killed(name):
    bad = gate_problems(_mutant(name))
    assert bad, f"the gate sweep misses mutant {name}"
    assert any(g == 16 and w > 1024 for _why, g, w in bad), (name, bad)
    assert any(g > 16 and w <= 1024 for _why, g, w in bad), (name, bad)


# ---- reachability: g > 16 implies ScreenWidth > 1024 (so the old gate differed only at g = 16 on a wide screen) ------

_ES = {}


def ensure_scale(w: int, h: int) -> int:
    """g_popup_scale_num as the real thunk_ensure_scale (+ scale_uniform) bytes compute it on a w x h screen (one
    machine, g zeroed per call: the thunk computes only while the cell is 0)."""
    mu = _ES.get("mu")
    if mu is None:
        mu = _ES["mu"] = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(G & ~0xFFF, 0x1000)             # the menu_strip_thunks page: code + g + period, zero-filled
        mu.mem_map(SCREEN_W & ~0xFFF, 0x1000)
        mu.mem_map(STACK - 0x10000, 0x20000)
        mu.mem_map(MARKER, 0x1000)
        for n in ("scale_uniform", "thunk_ensure_scale"):
            mu.mem_write(TMPL[n][0], LIVE[n])
    mu.mem_write(G, bytes(8))                      # g (and the cell after it) = 0; an 8-byte write skips the pairing
    _w32(mu, SCREEN_W, w)
    _w32(mu, SCREEN_H, h)
    mu.mem_write(STACK, struct.pack("<I", MARKER))
    mu.reg_write(UC_X86_REG_ESP, STACK)
    mu.emu_start(TMPL["thunk_ensure_scale"][0], MARKER, count=10_000)
    return struct.unpack("<i", bytes(mu.mem_read(G, 4)))[0]


@pytest.mark.parametrize("w,h,g", [(1024, 768, 16), (1280, 720, 16), (1280, 768, 16), (1280, 800, 16),
                                   (1360, 768, 16), (1366, 768, 16), (768, 1024, 16), (800, 600, 16),
                                   (1152, 864, 18), (1280, 1024, 20), (1920, 1080, 22), (1600, 900, 18),
                                   (1600, 1200, 25), (3840, 2160, 40)])
def test_ensure_scale_g_per_resolution(w, h, g):
    assert ensure_scale(w, h) == g


def test_g_above_16_needs_a_screen_wider_than_1024():
    """Over every width 640..1024 (step 8) and height 480..4320 (step 24): g == 16.  So the width-gated bytes and
    the g-gated bytes differed only where g == 16 and W > 1024, which is what the fix changes."""
    for w in range(640, 1025, 8):
        for h in range(480, 4321, 24):
            assert ensure_scale(w, h) == 16, (w, h)
    assert ensure_scale(1088, 1088) == 17
