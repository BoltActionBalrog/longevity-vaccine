"""W7R v2 asm parity (scripts/assemble_thin_rings.py, 2026-10-25 wave 7): t_rowbox_solid + t_ring_solid + t_menu_border +
t_menu_row -- Unicorn on the patches.yaml bytes resolved at their real cave VAs, against the laws scaling_laws.ring_solid /
ring_band_rects / menu_row_clip / menu_box_rect.

1. the yaml bytes are the assembler's, at the VAs the symbol table gives; the option-row site 0x405BF6 is retargeted from
   t_rowbox_trim to t_rowbox_solid, and the Menu sites 0x403B55 / 0x403B88 redirect the pristine `call Buffer_box_sprite`
   to t_menu_row / t_menu_border, in group menu_box_scale; the DiploWin item back 0x443EEF is NOT patched (unreachable);
2. t_ring_solid == ring_solid on random item canvases (every g 16..64, the four strips' strokes / pass-through / key /
   absent sprites / filename-backed sprites, rects partly or wholly off the buffer, under 2K each way, a random Buffer
   clip (inside, across and outside the buffer), a bottom-up and a top-down buffer): every pixel, and nothing outside
   the buffer's pixels or the g_rs_clip cell is written; pushad / RET 0xC (every register and the stack as they came);
3. the three site thunks: g <= 16 reaches the deployed callee with the caller's frame untouched; g > 16 their call
   chains with the law's rects; RET 8, ebx / esi / edi / ebp kept; t_menu_row's hot row (set 2) == menu_hot_row_colour
   from the row clip's top on random canvases, g 17..64.
Pure Unicorn on <1 KB of code: no bake, no boot (~3 s for the module).
"""
from __future__ import annotations

import pathlib
import random
import struct
import sys
from functools import lru_cache

import pytest

pytest.importorskip("keystone")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_patches as ap  # noqa: E402
import assemble_thin_rings as A  # noqa: E402
import scaling_laws as SL  # noqa: E402

YAML = ROOT / "patches" / "patches.yaml"
G_VA = 0x668740
STACK, SP0 = 0x00300000, 0x00308000
RET_VA = 0x00401000
BUF = 0x02000000                  # a Buffer struct (+0x54 data, +0x80 w, +0x84 h, +0x4A8 stride)
DATA = 0x02100000
SET = 0x02200000                  # a BoxSpriteParams (+0x10..+0x1C the strip Sprite*)
SPR = 0x02300000                  # the strip Sprites (+4 bits, +0xC pitch, +0x10 w, +0x14 h) and their pixels
REGS = {UC_X86_REG_EAX: 0x11, UC_X86_REG_EBX: 0x22, UC_X86_REG_ECX: 0x33, UC_X86_REG_EDX: 0x44,
        UC_X86_REG_ESI: 0x55, UC_X86_REG_EDI: 0x66, UC_X86_REG_EBP: 0x77}
STRIP_DIMS = ((24, 6), (24, 6), (6, 24), (6, 24))      # top, bottom, left, right (w, h): the family's art


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


# ================================================================ 1. the bytes and the wiring
def test_yaml_bytes_are_the_assembler_output():
    _s, st, ents = _yaml()
    for name, (off, n, tpl) in A.build().items():
        assert st[name] == A.PCAVE2 + off, name
        assert ents[name]["bytes"] == tpl, name
        assert len(_bytes(name)) == n, name
    for name, off in A.CELLS.items():
        assert st[name] == A.PCAVE2 + off, name
    assert A.REGION[0] <= min(o for o, _e in A.SLOTS.values())
    assert max(A.CELLS.values()) + 16 <= A.REGION[1]
    assert st["g_popup_scale_num"] == G_VA and st["Buffer_box_sprite"] == 0x5E2DD3 and st["Buffer_set_clip"] == 0x5D8000


def test_sites_are_wired():
    sites, _st, ents = _yaml()
    by_va = {s["virtual_addr"]: s for s in sites}
    for va, (orig, tgt) in A.SITES.items():
        s = by_va[va]
        if va == SL.OPTION_ROW_SITE:      # W9B wraps t_rowbox_solid there: t1c_bar CALLs it (marked type-1 bars) or tail-jumps it
            assert s["new_bytes"] == "E8 {rel32:t1c_bar}", hex(va)
            assert {"{rel32:%s}" % tgt, "{abs32:%s}" % tgt} <= set(ents["t1c_bar"]["bytes"].split())
            continue
        assert s["new_bytes"] == "E8 {rel32:%s}" % tgt, hex(va)
    opt = by_va[SL.OPTION_ROW_SITE]
    assert opt["id"] == "FUN_00405b20.option_frame" and opt["original_bytes"] == "E8 D8 D1 1D 00"
    for va in (SL.MENU_ROW_SITE, SL.MENU_BORDER_SITE):
        s = by_va[va]
        assert s["group"] == "menu_box_scale" and s["original_bytes"] == A.SITES[va][0]
        rel = struct.unpack("<i", bytes.fromhex(A.SITES[va][0].replace(" ", ""))[1:])[0]
        assert va + 5 + rel == 0x5E2DD3                                     # the pristine call is Buffer_box_sprite
    _g = ap.load_patches(YAML)[1]
    grp = next(g for g in _g if g["id"] == "menu_box_scale")
    assert sorted(grp["members"]) == ["g_menu_border_draw.box", "g_menu_hilite_draw.box"]
    assert SL.DW_ITEM_RING_SITE not in by_va                               # unreachable: not patched
    assert not any(g["id"] == "thin_ring_scale" for g in _g)


# ================================================================ the rig
class Rig:
    def __init__(self, g: int):
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((0x00400000, 0x2000), (0x00668000, 0x1000), (0x005E2000, 0x1000), (0x005D8000, 0x1000), (A.PCAVE2, 0x40000),
                           (STACK, 0x10000), (BUF, 0x1000), (DATA, 0x40000), (SET, 0x1000), (SPR, 0x4000)):
            uc.mem_map(base, size)
        uc.mem_write(RET_VA, b"\xF4")
        uc.mem_write(G_VA, struct.pack("<i", g))
        _s, st, _e = _yaml()
        for name in A.SLOTS:
            uc.mem_write(st[name], _bytes(name))
        self.st = st
        self.writes = []
        self.calls = []

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def run(self, va: int, stack: list, regs: dict = None, watch=False):
        uc = self.uc
        for i, v in enumerate([RET_VA] + stack):
            self.w32(SP0 + 4 * i, v)
        for r, v in {**REGS, **(regs or {})}.items():
            uc.reg_write(r, v & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, SP0)
        if watch:
            uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size, val, _: self.writes.append((addr, size)))
        uc.emu_start(va, RET_VA, count=2_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == RET_VA
        return uc

    def stub(self, va: int, ret_n: int, nargs: int, rect_arg: int = 0, effect=None):
        def cb(u, addr, size, _):
            esp = u.reg_read(UC_X86_REG_ESP)
            args = [self.r32(esp + 4 + 4 * i) & 0xFFFFFFFF for i in range(nargs)]
            rect = struct.unpack("<4i", bytes(u.mem_read(args[rect_arg], 16)))
            self.calls.append(dict(va=va, ecx=u.reg_read(UC_X86_REG_ECX), args=args, rect=rect,
                                   regs={r: u.reg_read(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EBP)}))
            if effect:
                effect(u, args)
            ret = self.r32(esp)
            u.reg_write(UC_X86_REG_ESP, esp + 4 + ret_n)
            u.reg_write(UC_X86_REG_EAX, 0x7A7A)
            u.reg_write(UC_X86_REG_ECX, 0x7B7B)
            u.reg_write(UC_X86_REG_EDX, 0x7C7C)
            u.reg_write(UC_X86_REG_EIP, ret & 0xFFFFFFFF)
        self.uc.hook_add(UC_HOOK_CODE, cb, begin=va, end=va)


# ================================================================ 2. t_ring_solid == the law
PALETTE = (0xE0, 0xE1, 0xAE, 0xEE, 0xC6, 0x41, 0x09, 0x07)


def _strips(rng, kinds):
    """The four strips' row lists with the probed texel set per kind: a stroke colour, 7, 9 or None (absent)."""
    out = []
    for (w, h), kind in zip(STRIP_DIMS, kinds):
        rows = [[SL.BOX_PASS_THROUGH] * w for _ in range(h)]
        if kind is not None:
            for r in rows:
                for x in range(w):
                    r[x] = rng.choice(PALETTE)          # junk away from the probed texel
        out.append(rows)
    t, b, l, r = out
    for rows, kind, (y, x) in zip(out, kinds, ((0, 12), (5, 12), (12, 0), (12, 5))):
        if kind is not None:
            rows[y][x] = kind
    return out


def _case(rng, g):
    W, H = rng.randint(1, 90), rng.randint(1, 60)
    canvas = [[rng.choice(PALETTE) for _ in range(W)] for _ in range(H)]
    l, t = rng.randint(-3, W), rng.randint(-3, H)
    r, b = l + rng.randint(-2, W + 8), t + rng.randint(-2, H + 8)
    kinds = [rng.choice((0xE0, 0xE1, 0xAE, 0xEE, 0xC6, 7, 9, None)) for _ in range(4)]
    absent = [k is None for k in kinds]
    filename_backed = [rng.random() < 0.1 for _ in range(4)]
    if rng.random() < 0.4:                                  # GraphicWin_init's clip: the whole buffer, half-open
        clip = (0, 0, W, H)
    else:
        cl, ct = rng.randint(-5, W), rng.randint(-5, H)
        clip = (cl, ct, cl + rng.randint(-2, W + 6), ct + rng.randint(-2, H + 6))
    return canvas, (l, t, r, b), kinds, absent, filename_backed, rng.random() < 0.5, clip


def _law(canvas, rect, g, kinds, absent, filename_backed, clip):
    strokes = []
    strips = _strips(random.Random(0), kinds)
    for k, ab, fb, st in zip(kinds, absent, filename_backed, SL.box_edge_strokes(strips)):
        strokes.append(None if (ab or fb) else st)
    return SL.ring_solid(canvas, rect, g, strokes, clip), strips


@pytest.mark.parametrize("g", range(16, 65))
def test_ring_solid_is_the_law(g):
    rng = random.Random(0x7E0 + g)
    acted = 0
    for _ in range(40):
        canvas, rect, kinds, absent, fb, topdown, clip = _case(rng, g)
        want, strips = _law(canvas, rect, g, kinds, absent, fb, clip)
        acted += want != canvas
        rig = Rig(g)
        uc = rig.uc
        H, W = len(canvas), len(canvas[0])
        stride = (W + 3) & ~3
        uc.mem_write(DATA, bytes(v for row in canvas for v in row + [0x5A] * (stride - W)))
        rig.w32(BUF + 0x54, DATA)
        rig.w32(BUF + 0x4A8, stride)
        rig.w32(BUF + 0x80, W)
        rig.w32(BUF + 0x84, -H if topdown else H)
        uc.mem_write(BUF + 0x20, struct.pack("<4i", *clip))
        rect_va = STACK + 0x9000
        uc.mem_write(rect_va, struct.pack("<4i", *rect))
        for i, (rows, ab, fbk) in enumerate(zip(strips, absent, fb)):
            sp = SPR + 0x400 * i
            rig.w32(SET + 0x10 + 4 * i, 0 if ab else sp)
            w, h = STRIP_DIMS[i]
            uc.mem_write(sp + 0x100, bytes(v for row in rows for v in row))
            rig.w32(sp + 4, 0 if fbk else sp + 0x100)
            rig.w32(sp + 0xC, w)
            rig.w32(sp + 0x10, w)
            rig.w32(sp + 0x14, h)
        rig.run(rig.st["t_ring_solid"], [BUF, rect_va, SET, 0xDEAD], watch=True)
        got = bytes(uc.mem_read(DATA, stride * H))
        got_rows = [list(got[y * stride:y * stride + W]) for y in range(H)]
        assert got_rows == want, (g, rect, kinds, absent, fb, clip)
        assert got[W:stride] == bytes([0x5A] * (stride - W)) or stride == W
        cell = rig.st["g_rs_clip"]
        for addr, size in rig.writes:
            assert (DATA <= addr and addr + size <= DATA + stride * H) or (cell <= addr and addr + size <= cell + 16) \
                or (STACK <= addr < SP0), hex(addr)
        for r, v in REGS.items():
            assert uc.reg_read(r) == v, (g, r)
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0xC
    assert acted >= (0 if g <= 16 else 3), (g, acted)      # the sweep exercised the solidify, not only its gates


def test_ring_solid_makes_the_restriped_ring_solid():
    """The case it exists for: a band-map ring restriped E0 / E1 comes back solid E0, the K x K corners and the
    interior untouched."""
    g, W, H = 40, 60, 30
    k = SL.stroke_width(g)
    canvas = [[0xAE if (y // 2) % 2 else 0xEE for _ in range(W)] for y in range(H)]
    for y in range(H):
        for x in range(W):
            if x < k or x >= W - k or y < k or y >= H - k:
                canvas[y][x] = 0xE0 if (y // 2) % 2 else 0xE1
    for y0, x0 in ((0, 0), (0, W - k), (H - k, 0), (H - k, W - k)):
        for y in range(y0, y0 + k):
            for x in range(x0, x0 + k):
                canvas[y][x] = 0xC6
    out = SL.ring_solid(canvas, (0, 0, W, H), g, (0xE0,) * 4)
    for y in range(H):
        for x in range(W):
            corner = (x < k or x >= W - k) and (y < k or y >= H - k)
            band = (x < k or x >= W - k or y < k or y >= H - k) and not corner
            want = 0xC6 if corner else 0xE0 if band else canvas[y][x]
            assert out[y][x] == want, (x, y)


# ================================================================ 3. the site thunks
RECT = (7, 55, 993, 102)
REGS3 = {UC_X86_REG_ECX: BUF, UC_X86_REG_EBX: 0x1B1B, UC_X86_REG_ESI: 0x5151, UC_X86_REG_EDI: 0xD1D1,
         UC_X86_REG_EBP: 0xB0B0}


def _site_run(g, entry, stubs, set_va=SL.THIN_RING_SET_STATE1):
    rig = Rig(g)
    for va, ret_n, nargs, rect_arg, effect in stubs(rig.st):
        rig.stub(va, ret_n, nargs, rect_arg, effect)
    rect_va = STACK + 0x9000
    rig.uc.mem_write(rect_va, struct.pack("<4i", *RECT))
    rig.uc.mem_write(BUF + 0x20, struct.pack("<4i", 1, 40, 900, 80))           # the row clip the callback set
    uc = rig.run(rig.st[entry], [rect_va, set_va, 0xDEAD], REGS3)
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert uc.reg_read(r) == REGS3[r], (entry, g, r)
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 8
    return rig, rect_va


def _trim(rig):
    """t_rowbox_trim's contract as the stub: the local rect's R / B - 1 (F35), the frame drawn on it."""
    def eff(u, args):
        r = struct.unpack("<4i", bytes(u.mem_read(args[0], 16)))
        u.mem_write(args[0], struct.pack("<4i", r[0], r[1], r[2] - 1, r[3] - 1))
    return eff


@pytest.mark.parametrize("g", [1, 8, 16, 17, 22, 25, 30, 40, 64])
def test_rowbox_solid_flow(g):
    rig, rect_va = _site_run(g, "t_rowbox_solid", lambda st: [
        (st["t_rowbox_trim"], 8, 2, 0, _trim(None)), (st["t_ring_solid"], 0xC, 3, 1, None)])
    st = rig.st
    if g <= 16:
        assert [c["va"] for c in rig.calls] == [st["t_rowbox_trim"]]        # the deployed path, frame untouched
        c = rig.calls[0]
        assert c["ecx"] == BUF and c["args"] == [rect_va, SL.THIN_RING_SET_STATE1] and c["rect"] == RECT
        assert c["regs"][UC_X86_REG_EBP] == 0xB0B0                           # t_rowbox_trim reads [ebp-4]
        return
    assert [c["va"] for c in rig.calls] == [st["t_rowbox_trim"], st["t_ring_solid"]]
    tr, so = rig.calls
    assert tr["ecx"] == BUF and tr["args"] == [rect_va, SL.THIN_RING_SET_STATE1] and tr["rect"] == RECT
    assert tr["regs"][UC_X86_REG_EBP] == 0xB0B0
    assert so["args"] == [BUF, rig.st["g_rs_row"], SL.THIN_RING_SET_STATE1] and so["rect"] == RECT


@pytest.mark.parametrize("g", [1, 8, 16, 17, 22, 25, 30, 40, 64])
def test_rowbox_solid_extent_follows_the_trim(g):
    """The half-open extent t_ring_solid gets is the rect t_rowbox_trim left + 1 on R / B: the right extent for a row
    t_rowbox_trim trimmed AND for one t_dp_itemrect trimmed upstream (passed through)."""
    if g <= 16:
        return
    rig, rect_va = _site_run(g, "t_rowbox_solid", lambda st: [
        (st["t_rowbox_trim"], 8, 2, 0, _trim(None)), (st["t_ring_solid"], 0xC, 3, 1, None)])
    so = rig.calls[1]
    assert so["rect"] == (RECT[0], RECT[1], RECT[2], RECT[3])                # (R - 1) + 1


@pytest.mark.parametrize("g", [1, 8, 16, 17, 22, 25, 30, 40, 64])
def test_menu_border_flow(g):
    rig, rect_va = _site_run(g, "t_menu_border", lambda st: [
        (0x5E2DD3, 8, 2, 0, None), (st["thunk_rowbox_guard"], 8, 2, 0, None)], set_va=0x78D960)
    if g <= 16:
        assert [c["va"] for c in rig.calls] == [0x5E2DD3]
        c = rig.calls[0]
        assert c["ecx"] == BUF and c["args"] == [rect_va, 0x78D960] and c["rect"] == RECT
        return
    assert [c["va"] for c in rig.calls] == [rig.st["thunk_rowbox_guard"]]
    c = rig.calls[0]
    assert c["ecx"] == BUF and c["args"] == [rig.st["g_mb_rect"], 0x78D960]
    assert c["rect"] == SL.menu_box_rect(*RECT, g)
    assert struct.unpack("<4i", bytes(rig.uc.mem_read(rect_va, 16))) == RECT   # the menu's own field untouched


@pytest.mark.parametrize("g", [1, 8, 16, 17, 22, 25, 30, 40, 64])
@pytest.mark.parametrize("set_va", [0x78D960, SL.MENU_HOT_SET])
def test_menu_row_flow(g, set_va):
    rig, rect_va = _site_run(g, "t_menu_row", lambda st: [
        (0x5D8000, 4, 1, 0, None), (0x5E2DD3, 8, 2, 0, None), (st["t_rw_restripe"], 0xC, 3, 1, None)],
        set_va=set_va)
    st = rig.st
    if g <= 16:
        assert [c["va"] for c in rig.calls] == [0x5E2DD3]
        c = rig.calls[0]
        assert c["ecx"] == BUF and c["args"] == [rect_va, set_va] and c["rect"] == RECT
        return
    hot = set_va == SL.MENU_HOT_SET                     # the hot row: restriped from its own top, no t_rw_restripe
    assert [c["va"] for c in rig.calls] == [0x5D8000, 0x5E2DD3] + ([] if hot else [st["t_rw_restripe"]])
    clip, box = rig.calls[:2]
    assert clip["ecx"] == BUF and clip["args"] == [st["g_mr_clip"]]
    assert clip["rect"] == SL.menu_row_clip(1, 40, 900, 80, g)
    assert box["ecx"] == BUF and box["args"] == [rect_va, set_va] and box["rect"] == RECT
    if not hot:
        assert rig.calls[2]["args"] == [BUF, BUF + 0x20, set_va]


def _set_clip(u, args):
    """Buffer_set_clip's effect as the stub (the rect, already inside the buffer in these cases)."""
    u.mem_write(BUF + 0x20, bytes(u.mem_read(args[0], 16)))


@pytest.mark.parametrize("g", range(17, 65))
def test_menu_hot_row_is_the_law(g):
    """t_menu_row on a set-2 row == menu_hot_row_colour from the clip's top on every E0 / E1 pixel of the clip (cut to
    the buffer), every other pixel and everything outside untouched; random canvases / row clips / buffer shapes."""
    rng = random.Random(0x3E0 + g)
    for _ in range(12):
        W, H = rng.randint(8, 70), rng.randint(8, 60)
        canvas = [[rng.choice(PALETTE) for _ in range(W)] for _ in range(H)]
        t = rng.randint(0, H - 1)
        clip0 = (1, t, W - 1, min(H, t + rng.randint(1, H)))
        rig = Rig(g)
        rig.stub(0x5D8000, 4, 1, 0, _set_clip)
        rig.stub(0x5E2DD3, 8, 2, 0, None)
        uc = rig.uc
        stride = (W + 3) & ~3
        uc.mem_write(DATA, bytes(v for row in canvas for v in row + [0x5A] * (stride - W)))
        rig.w32(BUF + 0x54, DATA)
        rig.w32(BUF + 0x4A8, stride)
        rig.w32(BUF + 0x80, W)
        rig.w32(BUF + 0x84, -H if rng.random() < 0.5 else H)
        uc.mem_write(BUF + 0x20, struct.pack("<4i", *clip0))
        rect_va = STACK + 0x9000
        uc.mem_write(rect_va, struct.pack("<4i", 0, 0, W, H))
        rig.run(rig.st["t_menu_row"], [rect_va, SL.MENU_HOT_SET, 0xDEAD], {UC_X86_REG_ECX: BUF})
        l, t, r, b = SL.menu_row_clip(*clip0, g)
        want = [list(row) for row in canvas]
        for y in range(max(t, 0), min(b, H)):
            for x in range(max(l, 0), min(r, W)):
                if want[y][x] in (SL.MENU_HOT_TOP, SL.MENU_HOT_MATE):
                    want[y][x] = SL.menu_hot_row_colour(y, t, g)
        got = bytes(uc.mem_read(DATA, stride * H))
        assert [list(got[y * stride:y * stride + W]) for y in range(H)] == want, (g, clip0, W, H)
        assert all(got[y * stride + W:(y + 1) * stride] == bytes([0x5A] * (stride - W)) for y in range(H))
