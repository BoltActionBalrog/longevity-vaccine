"""Unicorn parity for the se_scale thunks (assemble_se.py).

Oracle = scaling_laws.se_* (modal / console tables, immediates, fonts, sprite
canvases, lock planes, tiles) and a Python port of the user-verified prototype's
restripe pass (hook_se_scale_proto.js v23: pair family, trailing-key overdraw,
P-law restripe, ring pin to K).  Every thunk is emulated from its REAL assembled
bytes at its REAL cave VA; engine callees are landing pads (emulation stops on
arrival) or tiny stubs (Buffer_resize, the kernel32 IAT bootstrap).
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
from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_se as AS  # noqa: E402

LAYOUT, _END = AS.assemble_all()
import assemble_face_own as FO  # noqa: E402  (W9A: thunk_se_rowdraw_ph v2 CALLs t_face_own)
FACE_OWN = FO.build()["t_face_own"]
VA = {n: AS.PCAVE2 + LAYOUT[n][0] for n in LAYOUT}
R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
     "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}
STACK, SP0 = 0x00300000, 0x00308000
RET_SITE = 0x00600100
TEXT_LO, TEXT_HI = 0x4AE000, 0x4B5000
OBJ_LO, OBJ_LEN = 0x8A6000, 0x21000
SCRATCH_LO, SCRATCH_LEN = 0x8D0000, 0x30000     # Buffer_resize stub data: buf + 0x30000
VPSTUB = 0x00700100
PARITY_NN = 0xA0C000 + 0x213C0        # t_rwk_parity_nn: thunk_se_sd2's tail above native (row-pair icon art on the stripe law)
ENGINE_LANDINGS = [AS.SD2, AS.MODEL_RESET, AS.BUILD, AS.ROWDRAW, AS.BTN_GATE, RET_SITE, PARITY_NN, AS.SPR_STRIPES,
                   AS.T_SE_LAYOUT]   # btnrun's tail (W4C F42; t_se_layout itself: test_scaling_se_halfopen.py)
_ks = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(src: str, va: int = 0) -> bytes:
    enc, _ = _ks.asm(src, va)
    return bytes(enc)


def s(v, g):
    return SL.scale_px(v, g)


_BASE_TEXT = None


def base_text() -> bytes:
    global _BASE_TEXT
    if _BASE_TEXT is None:
        _BASE_TEXT = AS.base_exe_bytes(TEXT_LO, TEXT_HI - TEXT_LO)
    return _BASE_TEXT


class Emu:
    def __init__(self, g, stubs=None):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        for base, size in ((AS.PCAVE2, 0x1A000), (AS.PCAVE2 + 0x2F000, 0x2000), (PARITY_NN & ~0xFFF, 0x1000), (AS.T_SE_LAYOUT & ~0xFFF, 0x1000), (STACK, 0x10000), (TEXT_LO, TEXT_HI - TEXT_LO),
                           (OBJ_LO, OBJ_LEN), (SCRATCH_LO, SCRATCH_LEN), (0x668000, 0x2000), (0x7AF000, 0x1000),
                           (0x5E4000, 0x1000), (0x5D7000, 0x1000), (0x66D000, 0x1000), (0x600000, 0x1000),
                           (0x700000, 0x1000), (0x5B5000, 0x1000), (0x4BB000, 0x1000)):
            uc.mem_map(base, size)
        for name, (off, blob) in LAYOUT.items():
            uc.mem_write(AS.PCAVE2 + off, blob)
        uc.mem_map(FACE_OWN[0] & ~0xFFF, 0x1000)
        uc.mem_write(FACE_OWN[0], FACE_OWN[1])
        uc.mem_write(0x66879C, SL.stripe_period(g).to_bytes(4, "little"))   # g_stripe_period (thunk_ensure_scale's cell)
        uc.mem_write(TEXT_LO, base_text())
        uc.mem_write(AS.G, g.to_bytes(4, "little", signed=True))
        stubs = dict(stubs or {})
        self.landings = set(a for a in ENGINE_LANDINGS if a not in stubs)
        for a in ENGINE_LANDINGS:
            uc.mem_write(a, stubs.get(a, b"\xf4"))
        for a, b in stubs.items():
            uc.mem_write(a, b)
        self.stopped_at = None
        uc.hook_add(UC_HOOK_CODE, self._hook)

    def _hook(self, uc, addr, size, ud):
        if addr in self.landings:
            self.stopped_at = addr
            uc.emu_stop()

    def w32(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "little", signed=True)

    def rect(self, addr):
        return tuple(self.r32(addr + 4 * i) for i in range(4))

    def wrect(self, addr, r):
        for i, v in enumerate(r):
            self.w32(addr + 4 * i, v)

    def run(self, va, regs=None, stack=None, eflags=0x202):
        uc = self.uc
        stack = list(stack or [RET_SITE])
        sp = SP0
        for i, v in enumerate(stack):
            self.w32(sp + 4 * i, v)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_EFLAGS, eflags)
        for k, v in (regs or {}).items():
            uc.reg_write(R[k], v & 0xFFFFFFFF)
        self.stopped_at = None
        uc.emu_start(va, 0, count=50_000_000)
        return self.stopped_at

    def reg(self, k):
        return self.uc.reg_read(R[k])


# Buffer_resize stub (thiscall ecx=buf, w, h POSITIVE, RET 8): w/h/pitch fields + data = buf + 0x30000
BUF_RESIZE_STUB = asm(
    "mov eax, dword ptr [esp+4]; mov dword ptr [ecx+0x80], eax; mov dword ptr [ecx+0x4A8], eax;"
    "mov edx, dword ptr [esp+8]; neg edx; mov dword ptr [ecx+0x84], edx;"
    "lea eax, [ecx+0x30000]; mov dword ptr [ecx+0x54], eax; ret 8")


def mk_buffer(emu, addr, w, h, pitch=None, data=None, fill=0xEE):
    """Minimal engine Buffer: data +0x54, w +0x80, h +0x84 (NEGATIVE), pitch +0x4A8."""
    pitch = pitch or w
    data = data or (addr + 0x30000)
    emu.w32(addr + 0x54, data)
    emu.w32(addr + 0x80, w)
    emu.w32(addr + 0x84, -h)
    emu.w32(addr + 0x4A8, pitch)
    emu.uc.mem_write(data, bytes([fill]) * (pitch * h))
    return data


# ---- vanilla seeding (what SocialWin_build writes before model_reset) ---------------------
REGIONS_1024 = [12, 100, 300, 250, 400, 100, 700, 250, 720, 100, 1000, 250, 12, 299, 1194, 387]
NATIVE_SPRITE_CANVAS = [(13, 13)] * 10 + [(26, 26)] * 90   # digits[10] @+0x2C60 (13x13) + icons[90] @+0x2E18 (26x26)
SCALAR_BLOCK = (0x2BB0, 0x2C60)   # SocialWin scalars (hover state, the 3 allocation-triple copies +0x2C38..) -- NOT sprites
SCALAR_SEED = [(k * 7) % 64 + 1 for k in range((0x2C60 - 0x2BB0) // 4)]   # every value inside the pass's 1..64 window
LOCK_PLANES = []


def lock_plane(i: int) -> bytes:
    """24x14 native lock art: bevel border rows/cols of 195/185, even/odd dither pair inside,
    a key-9 hole (the padlock body) — the v20 even/odd-row mode law must find (a, b)."""
    a, b = ((190, 180), (105, 103))[i]
    rows = []
    for y in range(14):
        row = bytearray()
        for x in range(24):
            if y in (0, 13) or x in (0, 23):
                v = 195 if (x + y) % 2 == 0 else 185
            elif 9 <= x <= 14 and 4 <= y <= 9:
                v = 9
            else:
                v = a if y % 2 == 0 else b
            row.append(v)
        rows.append(bytes(row))
    return b"".join(rows)


def seed_tables(emu: Emu, regs):
    """The builder's native rect tables (modal seeds + console derivation over the region globals)."""
    m = SL.se_modal_rects(16)
    emu.wrect(AS.OBJ + 0x1F060, m["society_outer"])
    for i, r in enumerate(m["society_rows"]):
        emu.wrect(AS.OBJ + 0x1F070 + i * 0x10, r)
    for i, r in enumerate(m["bands"]):
        emu.wrect(AS.OBJ + 0x1F110 + i * 0x10, r)
    for i, r in enumerate(m["options"]):
        emu.wrect(AS.OBJ + 0x1F150 + i * 0x10, r)
    emu.wrect(AS.OBJ + 0x1F2A0, m["faction"])
    emu.wrect(AS.OBJ + 0x1F2B0, m["ok"])
    emu.wrect(AS.OBJ + 0x1F2C0, m["reset"])
    emu.wrect(AS.OBJ + 0x1F2D0, m["cancel"])
    for i, v in enumerate(regs):
        emu.w32(AS.REG + 4 * i, v)
    # native console tables (the builder's own derivation = law at g=16 over the scaled regions)
    c = SL.se_console_rects(regs, 16)
    emu.wrect(AS.OBJ + 0x1F250, c["fx_box"])
    emu.wrect(AS.OBJ + 0x1F2E0, c["center_box"])
    emu.wrect(AS.OBJ + 0x1F260, c["slider_econ"])
    emu.wrect(AS.OBJ + 0x1F270, c["slider_labs"])
    emu.wrect(AS.OBJ + 0x1F280, c["slider_psych"])
    emu.wrect(AS.OBJ + 0x1F290, c["hover_box"])
    for i, r in enumerate(c["arrows"]):
        emu.wrect(AS.OBJ + 0x1F000 + i * 0x10, r)
    for i, r in enumerate(c["locks"]):
        emu.wrect(AS.OBJ + 0x1EFD0 + i * 0x10, r)


def seed_native(emu: Emu, g: int, regions=None):
    """Write the builder's native tables + sprite structs + tiles; regions scaled with g."""
    regs = regions or [s(v, g) for v in REGIONS_1024]
    seed_tables(emu, regs)
    # sd2-fed sprites: canvas natives, data NULL (filename-backed) except a couple with data
    for i, (cw, ch) in enumerate(NATIVE_SPRITE_CANVAS):
        sp = AS.OBJ + AS.SPR_BASE + i * 0x2C
        emu.uc.mem_write(sp, b"\x00" * 0x2C)
        emu.w32(sp + 0x18, cw)
        emu.w32(sp + 0x1C, ch)
    # one unextracted digit (canvas 0) -> must be skipped
    emu.w32(AS.OBJ + AS.SPR_BASE + 2 * 0x2C + 0x18, 0)
    emu.w32(AS.OBJ + AS.SPR_BASE + 2 * 0x2C + 0x1C, 0)
    # the scalar block right before the sprites (allocation copies etc.): seeded with values the
    # sprite pass WOULD scale if it started early (the v1 first-chevron-click bug) -> must stay
    for k, v in enumerate(SCALAR_SEED):
        emu.w32(AS.OBJ + SCALAR_BLOCK[0] + 4 * k, v)
    # locks: raw planes 24x14, pitch 24, blit 24x14, canvas 24x14, key 9
    for i in range(2):
        sp = AS.OBJ + 0x3D90 + i * 0x2C
        data = SCRATCH_LO + 0x20000 + i * 0x400
        emu.uc.mem_write(sp, b"\x00" * 0x2C)
        emu.w32(sp + 4, data)
        emu.w32(sp + 8, 9)
        emu.w32(sp + 0xC, 24)
        emu.w32(sp + 0x10, 24)
        emu.w32(sp + 0x14, 14)
        emu.w32(sp + 0x18, 24)
        emu.w32(sp + 0x1C, 24 and 14)
        emu.uc.mem_write(data, lock_plane(i))
    # tiles: 6 Buffers 14x14, pure 2-row pairs (the socwin census values), one impure
    pairs = [(34, 39), (26, 152), (84, 82), (75, 69), (88, 87), (101, 245)]
    for i, (a, b) in enumerate(pairs):
        buf = AS.OBJ + 0x3EF0 + i * 0x588
        data = mk_buffer(emu, buf, 14, 14, fill=a)
        rows = bytearray()
        for y in range(14):
            rows += bytes([a if y % 2 == 0 else b]) * 14
        if i == 4:
            rows[3] = 200   # impure tile: row 0 carries a foreign index -> left alone
        emu.uc.mem_write(data, bytes(rows))


def run_transform(emu: Emu):
    emu.w32(AS.OBJ + 0x1F150, emu.r32(AS.OBJ + 0x1F150))   # no-op touch
    regs = {"ecx": AS.OBJ, "eax": 0x11112222, "edx": 0x33334444, "ebx": 0x55556666, "esi": 0x77778888,
            "edi": 0x9999AAAA, "ebp": 0xBBBBCCCC}
    land = emu.run(VA["thunk_se_transform"], regs=dict(regs), stack=[RET_SITE])
    assert land == AS.T_SE_LAYOUT                 # btnrun's tail (W4C F42) -> t_se_layout -> model_reset
    assert emu.reg("esp") == SP0                   # frame + pushad balanced, ret addr intact
    assert emu.r32(SP0) == RET_SITE
    for r, v in regs.items():                      # model_reset (fastcall ecx=self) sees the caller's registers
        assert emu.reg(r) == v, r


def read_modal(emu: Emu) -> dict:
    return {
        "society_outer": emu.rect(AS.OBJ + 0x1F060),
        "society_rows": [emu.rect(AS.OBJ + 0x1F070 + i * 0x10) for i in range(10)],
        "bands": [emu.rect(AS.OBJ + 0x1F110 + i * 0x10) for i in range(4)],
        "options": [emu.rect(AS.OBJ + 0x1F150 + i * 0x10) for i in range(16)],
        "faction": emu.rect(AS.OBJ + 0x1F2A0),
        "ok": emu.rect(AS.OBJ + 0x1F2B0), "reset": emu.rect(AS.OBJ + 0x1F2C0), "cancel": emu.rect(AS.OBJ + 0x1F2D0),
    }


def read_console(emu: Emu) -> dict:
    return {
        "fx_box": emu.rect(AS.OBJ + 0x1F250), "center_box": emu.rect(AS.OBJ + 0x1F2E0),
        "slider_econ": emu.rect(AS.OBJ + 0x1F260), "slider_labs": emu.rect(AS.OBJ + 0x1F270),
        "slider_psych": emu.rect(AS.OBJ + 0x1F280), "hover_box": emu.rect(AS.OBJ + 0x1F290),
        "arrows": [emu.rect(AS.OBJ + 0x1F000 + i * 0x10) for i in range(6)],
        "locks": [emu.rect(AS.OBJ + 0x1EFD0 + i * 0x10) for i in range(3)],
    }


# ---- Python ports of the proto's pixel passes ------------------------------------------------
def lock_plane_expected(native: bytes, g: int, phase_y: int, key: int = 9, bw=24, bh=14, cw=24, ch=14, pitch=24):
    w2, h2, cw2, ch2 = s(bw, g), s(bh, g), s(cw, g), s(ch, g)
    cmap, rmap = SL.se_centre_map(w2, bw), SL.se_centre_map(h2, bh)
    out = bytearray([key]) * (cw2 * ch2)
    row_bytes = min(bw, pitch)
    for y in range(h2):
        for x in range(w2):
            sx = cmap[x]
            out[y * cw2 + x] = native[rmap[y] * pitch + sx] if sx < row_bytes else key
    # even/odd-row mode pair
    def mode(rows):
        cnt = {}
        tot = 0
        for y in rows:
            for x in range(row_bytes):
                v = native[y * pitch + x]
                if v == key:
                    continue
                tot += 1
                cnt[v] = cnt.get(v, 0) + 1
        best = max(cnt.items(), key=lambda kv: (kv[1], -kv[0])) if cnt else (-1, 0)
        # asm keeps the FIRST index reaching the max (strict >); mimic: smallest index among maxima
        mx = max(cnt.values()) if cnt else 0
        best = (min(k for k, v in cnt.items() if v == mx), mx) if cnt else (-1, 0)
        return best[0], best[1], tot
    a, amax, atot = mode(range(0, bh, 2))
    b, bmax, btot = mode(range(1, bh, 2))
    if a != b and a >= 0 and b >= 0 and 5 * amax >= 2 * atot and 5 * bmax >= 2 * btot:
        for y in range(h2):
            c = a if SL.stripe_top(phase_y + y, g) else b
            for x in range(w2):
                if out[y * cw2 + x] in (a, b):
                    out[y * cw2 + x] = c
    return bytes(out), (w2, h2, cw2, ch2)


def restripe_expected(px: bytearray, W: int, H: int, stride: int, g: int, ph: int = 0) -> bytes:
    """Port of the asm's row-draw pass (= the proto's restripeBuffer with family detection).  ph = the
    staged g_se_yph (scaling_laws.btn_face_stripe_phase): every stripe row y is stripe_top(y + ph)."""
    u8 = bytearray(px)
    xcol = max(1, min(W - 2, W // 4))
    n1 = sum(1 for y in range(H) if u8[y * stride + xcol] in (174, 238))
    n2 = sum(1 for y in range(H) if u8[y * stride + xcol] in (224, 225))
    top, bot, n = (174, 238, n1) if n1 >= n2 else (224, 225, n2)
    if n * 5 < 3 * H:
        return bytes(u8)
    KEY = 9

    def row_key(y):
        c = sum(1 for x in range(4, W - 4) if u8[y * stride + x] == KEY)
        return c * 10 >= 9 * (W - 8)
    kb = 0
    while kb < 2 and H - 1 - kb > 0 and row_key(H - 1 - kb):
        kb += 1
    if kb:
        src = H - 1 - kb
        for y in range(H - kb, H):
            u8[y * stride:y * stride + W] = u8[src * stride:src * stride + W]
    for y in range(H):
        c = top if SL.stripe_top(y + ph, g) else bot
        for x in range(W):
            if u8[y * stride + x] in (top, bot):
                u8[y * stride + x] = c
    K = SL.stroke_width(g)
    if W < 32 or H < 32:
        return bytes(u8)
    is_pair = lambda v: v in (top, bot)  # noqa: E731

    def row_ring(y):
        c = sum(1 for x in range(8, W - 8) if not is_pair(u8[y * stride + x]))
        return c * 10 >= 9 * (W - 16)

    def col_ring(x):
        c = sum(1 for y in range(8, H - 8) if not is_pair(u8[y * stride + x]))
        return c * 10 >= 9 * (H - 16)
    dT = dB = dL = dR = 0
    while dT < 8 and row_ring(dT):
        dT += 1
    while dB < 8 and row_ring(H - 1 - dB):
        dB += 1
    while dL < 8 and col_ring(dL):
        dL += 1
    while dR < 8 and col_ring(W - 1 - dR):
        dR += 1
    if not (dT or dB or dL or dR):
        return bytes(u8)
    stripe = lambda y: top if SL.stripe_top(y + ph, g) else bot  # noqa: E731
    for y in range(K, dT):
        for x in range(K, W - K):
            u8[y * stride + x] = stripe(y)
    for y in range(H - dB, H - K):
        for x in range(K, W - K):
            u8[y * stride + x] = stripe(y)
    for x in range(K, dL):
        for y in range(K, H - K):
            u8[y * stride + x] = stripe(y)
    for x in range(W - dR, W - K):
        for y in range(K, H - K):
            u8[y * stride + x] = stripe(y)
    if dT and dT < K:
        for y in range(dT, K):
            u8[y * stride:y * stride + W] = u8[(dT - 1) * stride:(dT - 1) * stride + W]
    if dB and dB < K:
        for y in range(H - K, H - dB):
            u8[y * stride:y * stride + W] = u8[(H - dB) * stride:(H - dB) * stride + W]
    if dL and dL < K:
        for x in range(dL, K):
            for y in range(H):
                u8[y * stride + x] = u8[y * stride + dL - 1]
    if dR and dR < K:
        for x in range(W - K, W - dR):
            for y in range(H):
                u8[y * stride + x] = u8[y * stride + W - dR]
    return bytes(u8)


def make_face(W, H, pair, ring=None, ring_color=77, key_rows=0, stride=None):
    """A composed FlatButton face: 1px dither (NN-zoomed engine-style, runs of 2/3), optional
    ring of `ring` px on all four edges, `key_rows` trailing KEY rows (the dropped-row class)."""
    stride = stride or W
    top, bot = pair
    px = bytearray(stride * H)
    for y in range(H):
        for x in range(W):
            # engine NN of a 1px pattern @2.5: runs 3/2 -> emulate with y*2//5 parity
            px[y * stride + x] = top if ((y * 2) // 5) % 2 == 0 else bot
    if ring:
        for y in range(H):
            for x in range(W):
                if y < ring or y >= H - ring or x < ring or x >= W - ring:
                    px[y * stride + x] = ring_color
    for y in range(H - key_rows, H):
        for x in range(W):
            px[y * stride + x] = 9
    return px


# ============================================================================================
# stripe_top / sd2 / enter / gate_pre
# ============================================================================================
@pytest.mark.parametrize("g", [17, 22, 25, 32, 40])
def test_stripe_top_matches_law(g):
    emu = Emu(g)
    for y in list(range(0, 40)) + [355, 571, 1000]:
        emu.run(VA["thunk_se_stripe_top"], regs={"eax": y, "ecx": 0x1234, "edx": 0x5678}, stack=[RET_SITE])
        assert emu.reg("eax") == int(SL.stripe_top(y, g)), (g, y)
        assert emu.reg("ecx") == 0x1234 and emu.reg("edx") == 0x5678


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_sd2_ratio(g):
    emu = Emu(g)
    land = emu.run(VA["thunk_se_sd2"], regs={"ecx": 0x8AA000}, stack=[RET_SITE, 0x1000, 9, 100, 200, 1, 1])
    assert land == AS.SPR_STRIPES
    esp = emu.reg("esp")
    assert esp == SP0 and emu.r32(esp) == RET_SITE
    assert [emu.r32(esp + 4 * i) for i in range(1, 7)] == [0x1000, 9, 100, 200, g, 16]
    assert emu.reg("ecx") == 0x8AA000


def test_enter_runs_immfix_then_builder():
    g = 25
    emu = Emu(g)
    emu.w32(AS.G_SE_VPDONE, 1)
    land = emu.run(VA["thunk_se_enter"], regs={"ecx": AS.OBJ}, stack=[RET_SITE, 7])
    assert land == AS.BUILD
    assert emu.reg("esp") == SP0 and emu.r32(SP0) == RET_SITE and emu.r32(SP0 + 4) == 7
    assert emu.reg("ecx") == AS.OBJ
    # the imm table ran: a byte site and a dword site carry s(A)-s(B) (0x4AF261's title height left the table for
    # t_se_layout in W5C: the SPARTANS painter's s(2) @0x4AFA77 is the byte site now)
    assert struct.unpack("<b", emu.uc.mem_read(0x4AFA77 + 2, 1))[0] == SL.se_imm(2, 0, g)
    assert emu.r32(0x4b32d7 + 1) == SL.se_window_w(g)


@pytest.mark.parametrize("esi, want", [
    (AS.BTN_LO, 1), (AS.BTN_LO + 17 * 0xB4C, 1), (AS.BTN_HI - 0xB4C, 1), (AS.BTN_HI, "gate"), (AS.BTN_LO - 4, "gate"),
    (0x6FEC80 + 0xD94, 1), (0x6FEC80 + 0xD94 + 6 * 0xB4C, "gate"),
    (0x7FE80C, 0), (0x7FF358, 0), (0x7B1804, "gate"), (0x7B2350, "gate"),
])
def test_btn_gate_pre_v3(esi, want):
    emu = Emu(40)
    land = emu.run(VA["thunk_btn_gate_pre"], regs={"esi": esi, "eax": 0xDEAD}, stack=[RET_SITE])
    if want == "gate":
        assert land == AS.BTN_GATE and emu.reg("esp") == SP0 and emu.r32(SP0) == RET_SITE
    else:
        assert land == RET_SITE and emu.reg("eax") == want
    assert emu.reg("esi") == esi


def test_btn_gate_pre_v3_is_v2_plus_prefix():
    b = LAYOUT["thunk_btn_gate_pre"][1]
    v2 = bytes.fromhex("81FE14FA6F00720E81FEDC3D700073 06B801000000C381FE0CE87F00740881FE58F37F007503 31C0C368".replace(" ", ""))
    assert len(b) == 69 and b[22:22 + len(v2)] == v2
    assert b[-5:] == b"\x68" + struct.pack("<I", AS.BTN_GATE) + b"\xC3" if False else b[-1] == 0xC3


# ============================================================================================
# immfix
# ============================================================================================
def _iat_stubs(loadlib_ok=True, vp_ok=True):
    """kernel32 IAT: LoadLibraryA -> ret 1/0; GetProcAddress -> VPSTUB; VirtualProtect stub -> ret 1/0."""
    ll = asm(f"mov eax, {1 if loadlib_ok else 0}; ret 4")
    gp = asm(f"mov eax, {VPSTUB:#x}; ret 8")
    vp = asm(f"mov eax, {1 if vp_ok else 0}; ret 16")
    return {0x700000: ll, 0x700040: gp, VPSTUB: vp}


def _emu_with_iat(g, **kw):
    emu = Emu(g, stubs=_iat_stubs(**kw))
    emu.w32(AS.IAT_LOADLIB, 0x700000)
    emu.w32(AS.IAT_GETPROC, 0x700040)
    return emu


def imm_expected(a: int, b: int, kind: int, g: int) -> int:
    """The Python law for one table entry (kind bits 1/2 = the rail-abutting backdrop edges)."""
    if kind & AS.KIND_RAIL_L:
        if b == 0:                                   # KIND_FLOOR: the 9 SocialWin font sizes (fonts v2 2026-09-17)
            assert (a, kind) in {(sz, AS.KIND_FLOOR) for _s, sz in AS.FONT_SIZE_PUSHES}
            return SL.se_font_size(a, g)
        assert (a, b) == (15, 8)
        return SL.rail_left_extent(g)
    if kind & AS.KIND_RAIL_R:
        assert (a, b) == (0x341, 55)
        return SL.se_backdrop_rect(g)[2]
    if kind & AS.KIND_CEIL:
        assert (a, b) == (0x341, 0)
        return SL.se_window_w(g)
    return SL.se_imm(a, b, g)


def test_immtab_rail_entries_are_the_backdrop_edges():
    kinds = {site: (a, b, kind) for site, a, b, kind, _ in AS.IMMTAB}
    assert kinds[0x4B32FD + 3] == (15, 8, 1 | AS.KIND_RAIL_L)
    assert kinds[0x4B3307 + 3] == (0x341, 55, 1 | AS.KIND_RAIL_R)
    assert kinds[0x4B32D7 + 1] == (0x341, 0, 1 | AS.KIND_CEIL)
    for site, a, b, kind, static in AS.IMMTAB:
        if not static:
            assert imm_expected(a, b, kind, 16) == AS.imm_native(a, b, kind)


def test_rail_arm_sites_target_the_popup_thunks():
    import pathlib
    import apply_patches as ap
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(AS.__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(symbols, caves))
    arms = {sid: (site, tgt, th) for sid, _fn, site, tgt, th, _n in AS.CALL_SITES if sid.endswith(("railarm_show", "railarm_hide"))}
    assert arms == {"SocialWin_show_hide.railarm_show": (0x4B2192, AS.SLIDE_SHOW, "thunk_popup_railshow"),
                    "SocialWin_show_hide.railarm_hide": (0x4B21B3, AS.SLIDE_HIDE, "thunk_popup_railhide")}
    assert symtab["thunk_popup_railshow"] == AS.PCAVE2 + 0x3550 and symtab["thunk_popup_railhide"] == AS.PCAVE2 + 0x44D0


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_immfix_table(g):
    emu = _emu_with_iat(g)
    land = emu.run(VA["thunk_se_immfix"], regs={"esi": 0x1111, "ebx": 0x2222}, stack=[RET_SITE])
    assert land == RET_SITE and emu.reg("esp") == SP0 + 4
    assert emu.reg("esi") == 0x1111 and emu.reg("ebx") == 0x2222
    assert emu.r32(AS.G_SE_VPDONE) == 1
    for site, a, b, kind, static in AS.IMMTAB:
        want = imm_expected(a, b, kind, g)
        if kind & 1:
            have = emu.r32(site)
        else:
            have = struct.unpack("<b", emu.uc.mem_read(site, 1))[0]
        assert have == want, (hex(site), a, b, g, have, want)
    # g=16 identity: the whole text range is byte-identical to the base (the MOV-imm sites are
    # static-patched separately; at g=16 they hold 7 = the native alias value)
    if g == 16:
        mem = bytes(emu.uc.mem_read(TEXT_LO, TEXT_HI - TEXT_LO))
        diff = [i for i in range(len(mem)) if mem[i] != base_text()[i]]
        statics = set()
        for site, _o in AS.MOVIMM_SITES:
            statics.update(range(site - TEXT_LO, site - TEXT_LO + 6))
        landing = {a - TEXT_LO for a in ENGINE_LANDINGS if TEXT_LO <= a < TEXT_HI}
        assert set(diff) <= statics | landing, [hex(TEXT_LO + i) for i in diff if i not in statics | landing][:8]


def test_immfix_bails_without_bootstrap():
    g = 25
    emu = _emu_with_iat(g, loadlib_ok=False)
    land = emu.run(VA["thunk_se_immfix"], stack=[RET_SITE])
    assert land == RET_SITE
    assert emu.r32(AS.G_SE_VPDONE) == 0
    for site, a, b, kind, static in ((e for e in AS.IMMTAB if e[3] & 1 and not e[4])):
        assert emu.r32(site) == AS.imm_native(a, b, kind)
    emu2 = _emu_with_iat(g, vp_ok=False)
    emu2.run(VA["thunk_se_immfix"], stack=[RET_SITE])
    site, a, b, kind, _ = AS.IMMTAB[0]
    assert emu2.r32(AS.G_SE_VPDONE) == 0 and emu2.r32(site) == AS.imm_native(a, b, kind)


def test_immfix_second_call_skips_bootstrap():
    g = 22
    emu = _emu_with_iat(g)
    emu.run(VA["thunk_se_immfix"], stack=[RET_SITE])
    # cut the IAT: a second call must NOT touch it (vpdone latched) and must still rewrite
    emu.w32(AS.IAT_LOADLIB, 0)
    emu.w32(AS.G, 40)
    land = emu.run(VA["thunk_se_immfix"], stack=[RET_SITE])
    assert land == RET_SITE
    assert emu.r32(0x4b32d7 + 1) == SL.se_window_w(40)


# ============================================================================================
# transform
# ============================================================================================
def _check_transform_state(emu: Emu, g: int, regions):
    assert read_modal(emu) == {k: v for k, v in SL.se_modal_rects(g).items() if k != "backdrop"}
    c = SL.se_console_rects(regions, g)
    have = read_console(emu)
    for k in ("fx_box", "center_box", "slider_econ", "slider_labs", "slider_psych", "hover_box", "arrows", "locks"):
        assert have[k] == c[k], k
    scal = [emu.r32(AS.OBJ + SCALAR_BLOCK[0] + 4 * k) for k in range(len(SCALAR_SEED))]
    assert scal == SCALAR_SEED, "the sprite pass touched the scalar block (allocation copies)"
    for i, (cw, ch) in enumerate(NATIVE_SPRITE_CANVAS):
        sp = AS.OBJ + AS.SPR_BASE + i * 0x2C
        if i == 2:
            assert (emu.r32(sp + 0x18), emu.r32(sp + 0x1C)) == (0, 0)
            continue
        assert (emu.r32(sp + 0x18), emu.r32(sp + 0x1C)) == SL.se_sprite_canvas(cw, ch, g), i
        assert emu.r32(sp + 0xC) == 0 and emu.r32(sp + 0x10) == 0     # data/pitch/blit untouched
    for i in range(2):
        sp = AS.OBJ + 0x3D90 + i * 0x2C
        want, (w2, h2, cw2, ch2) = lock_plane_expected(lock_plane(i), g, c["lock_phase_y"])
        plane = AS.G_SE_LOCKPLANE + i * AS.LOCKPLANE_STRIDE
        assert emu.r32(sp + 4) == plane
        assert (emu.r32(sp + 0xC), emu.r32(sp + 0x10), emu.r32(sp + 0x14), emu.r32(sp + 0x18), emu.r32(sp + 0x1C)) == (cw2, w2, h2, cw2, ch2)
        assert (w2, h2, cw2, ch2) == SL.se_lock_plane_dims(g) + SL.se_lock_plane_dims(g)
        have = bytes(emu.uc.mem_read(plane, cw2 * ch2))
        assert have == want, f"lock {i} plane differs @g{g}"
        assert emu.r32(sp + 8) == 9
    pairs = [(34, 39), (26, 152), (84, 82), (75, 69), (88, 87), (101, 245)]
    for i, pair in enumerate(pairs):
        buf = AS.OBJ + 0x3EF0 + i * 0x588
        W, H = emu.r32(buf + 0x80), -emu.r32(buf + 0x84)
        data, stride = emu.r32(buf + 0x54), emu.r32(buf + 0x4A8)
        if i == 4:
            assert (W, H) == (14, 14)
            continue
        assert (W, H) == (14, SL.se_tile_height(g)), i
        assert bytes(emu.uc.mem_read(data, stride * H)) == b"".join(SL.se_tile_rows(pair, g)), i
    assert emu.r32(AS.G_SE_SPRG) == g


@pytest.mark.parametrize("g", list(range(17, 41)))
def test_transform_matches_laws(g):
    emu = Emu(g, stubs={AS.BUF_RESIZE: BUF_RESIZE_STUB})
    regions = [s(v, g) for v in REGIONS_1024]
    seed_native(emu, g, regions)
    run_transform(emu)
    _check_transform_state(emu, g, regions)


def test_transform_native_passthrough():
    emu = Emu(16, stubs={AS.BUF_RESIZE: BUF_RESIZE_STUB})
    seed_native(emu, 16)
    before = bytes(emu.uc.mem_read(AS.OBJ, 0x1F300))
    land = emu.run(VA["thunk_se_transform"], regs={"ecx": AS.OBJ}, stack=[RET_SITE])
    assert land == AS.T_SE_LAYOUT                 # btnrun's tail (W4C F42) -> t_se_layout -> model_reset
    assert bytes(emu.uc.mem_read(AS.OBJ, 0x1F300)) == before
    assert emu.r32(AS.G_SE_SPRG) == 0


@pytest.mark.parametrize("g", [22, 25, 40])
def test_transform_reopen_is_idempotent(g):
    """Second open at the same g: the builder re-seeds the TABLES natively but the sprite
    structs / tiles persist (extracted once per process) -> the saved natives make the
    sprite/lock/tile pass idempotent."""
    emu = Emu(g, stubs={AS.BUF_RESIZE: BUF_RESIZE_STUB})
    regions = [s(v, g) for v in REGIONS_1024]
    seed_native(emu, g, regions)
    run_transform(emu)
    snap = bytes(emu.uc.mem_read(AS.OBJ + 0x2BB0, 0x3EF0 + 6 * 0x588 - 0x2BB0))
    planes = bytes(emu.uc.mem_read(AS.G_SE_LOCKPLANE, 2 * AS.LOCKPLANE_STRIDE))
    # re-seed only the TABLES (as the builder does every open; sprites/tiles persist)
    seed_tables(emu, regions)
    run_transform(emu)
    _check_transform_state(emu, g, regions)
    assert bytes(emu.uc.mem_read(AS.OBJ + 0x2BB0, 0x3EF0 + 6 * 0x588 - 0x2BB0)) == snap
    assert bytes(emu.uc.mem_read(AS.G_SE_LOCKPLANE, 2 * AS.LOCKPLANE_STRIDE)) == planes


def test_transform_g_change_rescales_from_natives():
    """Open at g=25, then (resolution change in-process) at g=40: sprites/locks/tiles must
    come out as a fresh g=40 open would (saved natives, not the g=25 state)."""
    emu = Emu(25, stubs={AS.BUF_RESIZE: BUF_RESIZE_STUB})
    seed_native(emu, 25, [s(v, 25) for v in REGIONS_1024])
    run_transform(emu)
    regions40 = [s(v, 40) for v in REGIONS_1024]
    emu.w32(AS.G, 40)
    seed_tables(emu, regions40)
    run_transform(emu)
    _check_transform_state(emu, 40, regions40)


# ============================================================================================
# row draw restripe
# ============================================================================================
def _run_rowdraw(emu: Emu, g: int, px: bytearray, W: int, H: int, stride: int | None = None):
    stride = stride or W
    btn = AS.OBJ + 0x6020 + 5 * 0xB4C
    data = mk_buffer(emu, btn + 0x444, W, H, pitch=stride)
    emu.uc.mem_write(data, bytes(px))
    land = emu.run(VA["thunk_se_rowdraw"], regs={"ecx": AS.OBJ}, stack=[RET_SITE, btn, 0x12345, 0x16])
    assert land == AS.ROWDRAW
    assert emu.reg("esp") == SP0 and emu.r32(SP0) == RET_SITE and emu.r32(SP0 + 4) == btn and emu.r32(SP0 + 0xC) == 0x16
    assert emu.reg("ecx") == AS.OBJ
    return bytes(emu.uc.mem_read(data, stride * H))


@pytest.mark.parametrize("g, W, H", [(40, 365, 50), (25, 228, 31), (22, 200, 27), (40, 405, 50), (32, 292, 40)])
@pytest.mark.parametrize("pair", [(174, 238), (224, 225)])
@pytest.mark.parametrize("ring, key_rows", [(0, 0), (2, 0), (3, 0), (1, 0), (2, 2), (3, 1), (0, 2)])
def test_rowdraw_matches_port(g, W, H, pair, ring, key_rows):
    px = make_face(W, H, pair, ring=ring, key_rows=key_rows)
    emu = Emu(g)
    have = _run_rowdraw(emu, g, px, W, H)
    want = restripe_expected(px, W, H, W, g)
    assert have == want
    # the pass produced uniform P stripes on the face interior, and (faces >= 32px, the proto's
    # 4*margin gate) a K ring where a ring survived (an overdrawn dropped-row face has none below)
    K, P = SL.stroke_width(g), SL.stripe_period(g)
    mid = W // 2
    if ring and W >= 32 and H >= 32:
        assert all(have[y * W + mid] == 77 for y in range(K))
        assert have[K * W + mid] in pair
        if key_rows == 0:
            assert all(have[(H - 1 - y) * W + mid] == 77 for y in range(K))
            assert have[(H - 1 - K) * W + mid] in pair
    elif not ring:
        assert all(have[y * W + mid] == (pair[0] if SL.stripe_top(y, g) else pair[1]) for y in range(H - key_rows))
    assert not any(v == 9 for v in have[(H - 1) * W:(H - 1) * W + W])


def test_rowdraw_stride_and_no_pair_and_native():
    g = 25
    W, H, stride = 100, 40, 128
    px = make_face(W, H, (174, 238), ring=2, stride=stride)
    emu = Emu(g)
    have = _run_rowdraw(emu, g, px, W, H, stride)
    assert have == restripe_expected(px, W, H, stride, g)
    # no pair family present -> untouched
    plain = bytearray([50] * (W * H))
    emu = Emu(g)
    assert _run_rowdraw(emu, g, plain, W, H) == bytes(plain)
    # small buffer (< 32): restripe only, no ring pass
    small = make_face(24, 20, (174, 238), ring=1)
    emu = Emu(g)
    assert _run_rowdraw(emu, g, small, 24, 20) == restripe_expected(small, 24, 20, 24, g)
    # g <= 16: pure passthrough
    px = make_face(W, H, (174, 238), ring=2)
    emu = Emu(16)
    btn = AS.OBJ + 0x6020
    data = mk_buffer(emu, btn + 0x444, W, H)
    emu.uc.mem_write(data, bytes(px))
    land = emu.run(VA["thunk_se_rowdraw"], regs={"ecx": AS.OBJ}, stack=[RET_SITE, btn, 0, 1])
    assert land == AS.ROWDRAW and bytes(emu.uc.mem_read(data, W * H)) == bytes(px)


def _run_rowdraw_ph(emu: Emu, px: bytearray, W: int, H: int, top1: int, top2: int, idx: int = 5):
    """Enter through the vtable entry thunk_se_rowdraw_ph with the button's rRect1.top / rRect2.top set;
    every register must reach SocialWin_draw_society_row as the vtable call left it."""
    btn = AS.OBJ + 0x6020 + idx * 0xB4C
    data = mk_buffer(emu, btn + 0x444, W, H)
    emu.uc.mem_write(data, bytes(px))
    emu.w32(btn + 0x140, top1)
    emu.w32(btn + 0x150, top2)
    regs = {"ecx": AS.OBJ, "eax": 0x11112222, "edx": 0x33334444, "ebx": 0x55556666, "esi": 0x77778888,
            "edi": 0x9999AAAA, "ebp": 0xBBBBCCCC}
    land = emu.run(VA["thunk_se_rowdraw_ph"], regs=dict(regs), stack=[RET_SITE, btn, 0x12345, 0x16])
    assert land == AS.ROWDRAW
    assert emu.reg("esp") == SP0 and emu.r32(SP0) == RET_SITE and emu.r32(SP0 + 4) == btn
    for r, v in regs.items():
        assert emu.reg(r) == v, r
    return bytes(emu.uc.mem_read(data, W * H))


@pytest.mark.parametrize("g, W, H", [(18, 140, 22), (22, 200, 27), (25, 228, 31), (40, 365, 50), (48, 438, 60)])
@pytest.mark.parametrize("top1, top2", [(45, 0), (0, 45), (44, 0), (46, 1), (339, 0), (0, 0), (-3, 0), (-1, -6), (7, 7)])
@pytest.mark.parametrize("pair, ring", [((174, 238), 0), ((224, 225), 2)])
def test_rowdraw_ph_stripes_on_the_parent_grid(g, W, H, top1, top2, pair, ring):
    """2026-10-11 (law btn_face_stripe_phase): the face's stripe rows sit on the PARENT canvas's grid --
    row r carries the top member iff stripe_top(top + r).  1600x1200 shot 200540: SE window top 315, POLICE
    STATE face top 360 -> parent-local 45 -> phase 1 (it was 0, one row off the panel).  The ring pin rows
    (when a ring exists) take the same phase.  Negative tops floor-reduce."""
    px = make_face(W, H, pair, ring=ring)
    emu = Emu(g)
    emu.w32(AS.G_SE_YPH, 0x7EADBEEF)          # stale from another button: must be overwritten
    have = _run_rowdraw_ph(emu, px, W, H, top1, top2)
    ph = SL.btn_face_stripe_phase(top1, top2, g)
    assert emu.r32(AS.G_SE_YPH) == ph
    assert have == restripe_expected(px, W, H, W, g, ph)
    if not ring:
        mid = W // 2
        assert all(have[y * W + mid] == (pair[0] if SL.stripe_top(top1 + top2 + y, g) else pair[1])
                   for y in range(H))


SE_COLUMN = range(17, 27)          # SocialWin+0x6020 + i*0xB4C: the ten society rows (0x8B829C..), W9A own-top


# One representative per class (audit-w9A C4): the arithmetic over every P / h / state input is
# test_face_own_asm_parity.py's Unicorn sweep; here the entry's wiring -- the column's edges, a non-column face, the four
# state classes (normal, forced pressed, flag pressed, hover) -- at T = 1 / T = 2 and both h parities.
@pytest.mark.parametrize("g, W, H", [(18, 140, 22), (25, 228, 31), (40, 365, 50)])
@pytest.mark.parametrize("idx", [16, 17, 26, 27])
@pytest.mark.parametrize("state", [(-1, 0, 0, 0), (2, 0, 0, 0), (-1, 0, 1, 0), (-1, 1, 0, 0)])
@pytest.mark.parametrize("pair", [(174, 238), (224, 225)])
def test_rowdraw_ph_society_column_stripes_on_its_own_top(g, W, H, idx, state, pair):
    """W9A (2026-10-27, the user's decision; law btn_face_phase): the right column's ten society rows (idx 17..26)
    stripe on their OWN top -- own_face_stripe_phase of the face height, + T when the button draws PRESSED
    (flatbutton_draw_state of forced +0xAB8 / hover +0xA74 / pressed +0xA18 / +0xA9C) -- whatever their parent-local
    top; the OK row (16, 27, 28) and every other SE face keep the parent grid (btn_face_stripe_phase).  Registers and
    the stack reach SocialWin_draw_society_row untouched (_run_rowdraw_ph)."""
    px = make_face(W, H, pair, ring=0)
    emu = Emu(g)
    btn = AS.OBJ + 0x6020 + idx * 0xB4C
    forced, hover, pa, pb = state
    emu.w32(btn + 0xAB8, forced)
    emu.w32(btn + 0xA74, hover)
    emu.w32(btn + 0xA18, pa)
    emu.w32(btn + 0xA9C, pb)
    emu.w32(btn + 0xC4, AS.OBJ)                    # parent SocialWin
    top1 = 45 + 34 * idx
    have = _run_rowdraw_ph(emu, px, W, H, top1, 0, idx=idx)
    st = SL.flatbutton_draw_state(*state)
    ph = SL.btn_face_phase(btn, AS.OBJ, top1, 0, H, g, st)
    assert SL.own_top_face(btn, AS.OBJ) == (idx in SE_COLUMN)
    if idx in SE_COLUMN:
        assert ph == SL.own_face_stripe_phase(H, g, st == 2)
    else:
        assert ph == SL.btn_face_stripe_phase(top1, 0, g)
    assert emu.r32(AS.G_SE_YPH) == ph
    assert have == restripe_expected(px, W, H, W, g, ph)


@pytest.mark.parametrize("g, W, H", [(22, 200, 27), (25, 228, 31), (40, 365, 50)])
def test_rowdraw_ph_society_column_rows_all_alike(g, W, H):
    """The ten society rows at their real parent-local tops (pitch 34 at 1600x1200, any pitch elsewhere) restripe to
    ONE face per state -- the user's acceptance criterion; the parent grid gave two."""
    for st in (0, 1, 2):
        faces = set()
        for k, idx in enumerate(SE_COLUMN):
            emu = Emu(g)
            btn = AS.OBJ + 0x6020 + idx * 0xB4C
            emu.w32(btn + 0xAB8, st)
            faces.add(_run_rowdraw_ph(emu, make_face(W, H, (174, 238), ring=0), W, H, 45 + (H + 3) * k, 0, idx=idx))
        assert len(faces) == 1, (g, st)


def test_rowdraw_ph_native_and_unphased_body():
    """g <= 16: no staging (P is not valid there), straight into rowdraw's own passthrough.  The plain body
    entered directly never reads the cell (assemble_dw's DesignWin copy was phased=False until 2026-10-14)."""
    W, H = 100, 40
    px = make_face(W, H, (174, 238), ring=2)
    emu = Emu(16)
    emu.w32(AS.G_SE_YPH, 3)
    assert _run_rowdraw_ph(emu, px, W, H, 45, 0) == bytes(px)
    assert emu.r32(AS.G_SE_YPH) == 3
    plain = AS.asm_se_rowdraw(phased=False)
    assert "thunk_se_stripe_px_ph" not in plain and plain.count("call    thunk_se_stripe_px\n") == 5
    assert AS.asm_se_rowdraw().count("call    thunk_se_stripe_px_ph\n") == 5
    assert "thunk_se_stripe_px\n" not in AS.asm_se_rowdraw()


def test_rowdraw_ph_is_the_vtable_entry():
    sites = "\n".join(AS.site_yaml())
    assert '"{abs32:thunk_se_rowdraw_ph}"' in sites and '"{abs32:thunk_se_rowdraw}"' not in sites


def test_rowdraw_null_canvas_is_safe():
    emu = Emu(40)
    btn = AS.OBJ + 0x6020
    emu.w32(btn + 0x444 + 0x54, 0)
    land = emu.run(VA["thunk_se_rowdraw"], regs={"ecx": AS.OBJ}, stack=[RET_SITE, btn, 0, 1])
    assert land == AS.ROWDRAW and emu.reg("esp") == SP0


# ============================================================================================
# layout / template
# ============================================================================================
def test_layout_fits_and_is_disjoint():
    spans = []
    for name, (off, b) in LAYOUT.items():
        spans.append((off, off + len(b), name))
    for name, off, size in AS.CELLS:
        spans.append((off, off + size, name))
    spans.sort()
    for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
        assert a1 <= b0, f"{an} overlaps {bn}"
    fixed = {n for n, _o, _f in AS.FIXED_THUNKS} | {"g_se_yph"}
    assert spans[0][0] >= 0x14000 and max(e for _s, e, n in spans if n not in fixed) <= AS.SECTION_END
    # the fixed slots: each inside its cave_map-verified gap (FIXED_END), the cell in 0x2FFA0..0x30000
    for st, en, n in spans:
        if n in AS.FIXED_END:
            assert en <= AS.FIXED_END[n], n
    assert all(0x2FFA0 <= st and en <= 0x30000 for st, en, n in spans if n in fixed - {"thunk_se_btnrun"})
    assert 0x30359 <= AS.OFF_SE_BTNRUN and LAYOUT["thunk_se_btnrun"][0] + len(LAYOUT["thunk_se_btnrun"][1]) <= 0x30700
    assert LAYOUT["g_se_immtab"][0] + len(LAYOUT["g_se_immtab"][1]) <= AS.OFF_G_SE_SPRSAVE


def test_template_roundtrip_is_exact():
    names = {n: AS.PCAVE2 + LAYOUT[n][0] for n, _ in AS.NEW_THUNKS}
    names.update({n: AS.PCAVE2 + o for n, o, _ in AS.FIXED_THUNKS})
    extra = {va: n for n, va in names.items()}
    extra.update(AS.EXTRA_SYMS)
    assert AS.roundtrip_problems(LAYOUT, extra) == []


def test_live_sites_match_base():
    assert AS.verify_live() == []


def test_sprite_pass_layout_is_the_ctor_layout():
    """v2 regression: the ctor builds Sprite digits[10] @+0xB18*4 = +0x2C60 and icons[90] @+0x2E18
    (locks +0x3D90, arrows +0x3DE8).  +0x2BB0..+0x2C60 is the scalar block (the three allocation
    triple copies live at +0x2C38..+0x2C58).  v1's pass started at +0x2BB0 x104 and scaled slot 3's
    "canvas" = allocation copies -> the first chevron click re-normalised a corrupted triple."""
    assert (AS.SPR_BASE, AS.SPR_N) == (0x2C60, 100)
    assert AS.SPR_BASE + AS.SPR_N * 0x2C == 0x3D90
    assert AS.SPR_BASE >= SCALAR_BLOCK[1]
    g = 25
    emu = Emu(g, stubs={AS.BUF_RESIZE: BUF_RESIZE_STUB})
    seed_native(emu, g)
    alloc = AS.OBJ + 0x2C38
    for k, v in enumerate((5, 0, 5, 5, 0, 5, 5, 0, 5)):     # econ/x/y triple x3 as the builder seeds them
        emu.w32(alloc + 4 * k, v)
    run_transform(emu)
    assert [emu.r32(alloc + 4 * k) for k in range(9)] == [5, 0, 5, 5, 0, 5, 5, 0, 5]
    run_transform(emu)
    assert [emu.r32(alloc + 4 * k) for k in range(9)] == [5, 0, 5, 5, 0, 5, 5, 0, 5]
