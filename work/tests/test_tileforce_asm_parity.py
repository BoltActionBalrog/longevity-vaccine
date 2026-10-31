"""Differential: t_tile_force / t_msg_bgforce / t_tf_restripe (scripts/assemble_tileforce.py) run under Unicorn
together with the REAL assembled thunk_fe_pair_remap (scripts/assemble_devfill_stripes.py, sentinels resolved
to the patches.yaml symbol VAs) must leave the dest plane equal to the stripe law:

    every pixel of (drawn rect & dest clip) == scaling_laws.pair_remap_pixel(native idx, y, g, <keyed family>)
    on the DEST-BUFFER row y; every other pixel untouched; g <= 16 == the native callee alone.

Buffer_tile / Buffer_box_sprite are `ret imm` stubs with a Python-side code hook that paints the native 1-row
dither (clip-honouring, like the engine) and records the stack/registers the callee was entered with, so the
stack balance is checked on both paths of both drop-ins (a wrong offset here is a crash at every resolution
above native).

Skips (does not fail) if keystone/unicorn are absent.  Run with -p no:faulthandler.
"""
from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_list_face_phase as LFP  # noqa: E402
import assemble_tileforce as TF  # noqa: E402

G_SWEEP = (16, 18, 21, 22, 25, 32, 40)

PCAVE2, CAVE_LEN = TF.PCAVE2, 0x38000      # >= pcave2 length (W2D 2026-10-25: t_fac_item_pre / t_fac_rowpost)
G_VA, PERIOD_VA = 0x00668740, 0x0066879C
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
BUF = DATA + 0x100                       # the dest Buffer object
RECT = DATA + 0x800                      # caller RECT local (box case)
PARAMS = DATA + 0x900                    # box params pointer (opaque here)
SRC_TILE = DATA + 0xA00                  # Buffer_tile's src arg (opaque here)
PLANE = DATA + 0x10000
BW, BH, STRIDE = 120, 72, 128            # stride > width: a write past the row end lands in a checked gutter
F_CLIP, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0x4A8

REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9, UC_X86_REG_EAX: 0x0EA0EA0E, UC_X86_REG_EDX: 0x0ED0ED0E}
STUB_EAX = 0x00C0FFEE                    # what the "native" callee returns in eax
STROKE = 0x1F                            # a non-pair index (the box's frame line)


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def _symtab():
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


def _real_fe(symtab):
    """thunk_fe_pair_remap exactly as assemble_devfill_stripes.py assembles it, sentinel imm32s -> real VAs."""
    ds = importlib.import_module("assemble_devfill_stripes")
    src = off = None
    for n, o, asm in ds.THUNKS:
        if n == "thunk_fe_pair_remap":
            src, off = "\n".join(ln.split(";")[0] for ln in asm.splitlines()), o
    assert src is not None
    va = ds.PCAVE2 + off
    assert va == symtab["thunk_fe_pair_remap"], "assembler slot != patches.yaml symbol"
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    blob = bytes(enc)
    for sent, ph in ds.SENT.items():
        raw = sent.to_bytes(4, "little")
        if raw in blob:
            assert ph.startswith("{abs32:"), ph
            blob = blob.replace(raw, symtab[ph[7:-1]].to_bytes(4, "little"))
    for fam in (0x71, 0x7A, 0x7B, 0x7C, 0x7F):      # no sentinel family may survive
        assert bytes([0x11, 0x11, 0x11, fam]) not in blob
    return va, blob


def _shipped(name, symtab):
    """(va, bytes) of a pcave2 thunk exactly as patches.yaml ships it."""
    _sites, _groups, caves, _symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    for c in caves:
        for e in c.get("contents") or []:
            if e["id"] == name:
                va = int(c["virtual_addr"]) + int(e["offset"])
                return va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, symtab))
    raise KeyError(name)


class Emu:
    def __init__(self):
        self.symtab = _symtab()
        self.syms = TF.load_syms()
        self.layout = TF.assemble_all(self.syms)
        self.va = TF.names_of(self.layout)
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, CAVE_LEN)
        mu.mem_map(G_VA & ~0xFFF, 0x1000)
        mu.mem_map(TF.BUFFER_TILE & ~0xFFF, 0x1000)
        mu.mem_map(TF.BOX_SPRITE & ~0xFFF, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA - 0x1000, 0x41000)          # the page below BUF holds its Win's +0x140 / +0x150 (BUF - 0x444)
        mu.mem_map(MARKER & ~0xFFF, 0x1000)
        fe_va, fe = _real_fe(self.symtab)
        mu.mem_write(fe_va, fe)
        for name, (off, b) in self.layout.items():
            assert not (fe_va < PCAVE2 + off + len(b) and PCAVE2 + off < fe_va + len(fe)), name
            mu.mem_write(PCAVE2 + off, b)
        lbi_off, lbi = LFP.build()["t_lbi_restripe_ph"]           # t_lb_item_stripes' restripe call lands here
        assert PCAVE2 + lbi_off == LFP.VA_LBI and LFP.G_RM_YPH == self.symtab["g_rm_yph"]
        assert LFP.T_TF_RESTRIPE == self.va["t_tf_restripe"] and LFP.G_STRIPE_PERIOD == PERIOD_VA
        mu.mem_write(LFP.VA_LBI, lbi)
        for name in ("t_fac_item_pre", "t_fac_rowpost", "t_fac_sqcopy"):   # W2D F40b: t_lb_item_stripes' two callees
            va, b = _shipped(name, self.symtab)
            mu.mem_write(va, b)
        _w32(mu, self.symtab["g_fr_pending"], 0)
        mu.mem_write(TF.BUFFER_TILE, b"\xC2\x1C\x00")     # ret 0x1C (the native contract)
        mu.mem_write(TF.BOX_SPRITE, b"\xC2\x08\x00")      # ret 8
        self.calls, self.errors = [], []
        self.painter = None
        mu.hook_add(UC_HOOK_CODE, self._on_tile, begin=TF.BUFFER_TILE, end=TF.BUFFER_TILE)
        mu.hook_add(UC_HOOK_CODE, self._on_box, begin=TF.BOX_SPRITE, end=TF.BOX_SPRITE)

    # ---- native-callee stand-ins (paint, record, clobber what a real thiscall callee may) ----
    def _enter(self, kind, nargs):
        mu = self.mu
        esp = mu.reg_read(UC_X86_REG_ESP)
        rec = {"kind": kind, "esp": esp, "ret": _r32(mu, esp), "ecx": mu.reg_read(UC_X86_REG_ECX),
               "args": [_r32(mu, esp + 4 + 4 * i) for i in range(nargs)],
               "regs": {r: mu.reg_read(r) for r in REGS}}
        self.calls.append(rec)
        return rec

    def _leave(self):
        mu = self.mu
        mu.reg_write(UC_X86_REG_EAX, STUB_EAX)
        mu.reg_write(UC_X86_REG_ECX, 0xCCCC0001)
        mu.reg_write(UC_X86_REG_EDX, 0xDDDD0002)

    def _on_tile(self, mu, address, size, user):
        try:
            rec = self._enter("tile", 7)
            _src, _px, _py, dx, dy, w, h = (_s32(a) for a in rec["args"])
            if self.painter:
                self.painter(dx, dy, dx + w, dy + h)
            self._leave()
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    def _on_box(self, mu, address, size, user):
        try:
            rec = self._enter("box", 2)
            rp = rec["args"][0]
            l, t, r, b = (_s32(_r32(mu, rp + 4 * i)) for i in range(4))
            rec["rect"] = (l, t, r, b)
            if self.painter:
                self.painter(l, t, r, b)
            for i in range(4):                       # a callee is free to scribble on the caller's RECT
                _w32(mu, rp + 4 * i, 0x7FFF0000 + i)
            self._leave()
        except Exception as e:  # noqa: BLE001
            self.errors.append(repr(e))

    # ---- one call of a drop-in, as its site makes it ----
    def run(self, entry, g, args, ret_imm, *, clip=(0, 0, BW, BH), plane, painter, data_ptr=PLANE):
        mu = self.mu
        mu.mem_write(BUF, b"\x00" * 0x500)
        _w32(mu, BUF + F_DATA, data_ptr)
        _w32(mu, BUF + F_W, BW)
        _w32(mu, BUF + F_H, -BH)
        _w32(mu, BUF + F_STRIDE, STRIDE)
        for i, v in enumerate(clip):
            _w32(mu, BUF + F_CLIP + 4 * i, v)
        mu.mem_write(PLANE, bytes(plane))
        _w32(mu, G_VA, g)                                    # conftest pairs the period cell; set it explicitly too
        _w32(mu, PERIOD_VA, SL.stripe_period(g))
        _w32(mu, self.syms["g_rm_force"], 0)
        for n in ("g_fe_dst", "g_fe_x", "g_fe_y", "g_fe_w", "g_fe_h"):
            _w32(mu, self.syms[n], 0x66660000)               # hostile leftovers: must be overwritten or unused
        self.calls.clear()
        self.errors.clear()
        self.painter = painter
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, MARKER)
        for i, a in enumerate(args):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, BUF)
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.emu_start(entry, MARKER, count=20_000_000)
        assert not self.errors, self.errors
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER, "did not return to the caller"
        # ---- the native contract, whatever the path ----
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + ret_imm, "stack imbalance (ESP delta != 4 + RET imm)"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == REGS[r], "callee-saved register not preserved"
        assert mu.reg_read(UC_X86_REG_EAX) == STUB_EAX, "eax must be the native callee's result"
        assert bytes(mu.mem_read(sp - 0x400, 0x400 - 0x80)) == b"\xA5" * (0x400 - 0x80), "stack use deeper than 0x80"
        assert bytes(mu.mem_read(sp + 4 + 4 * len(args), 0x100)) == b"\xA5" * 0x100, "wrote above its own args"
        assert _r32(mu, self.syms["g_rm_force"]) == 0, "g_rm_force left set (would hijack the next frame_enlarge)"
        # ---- the callee ran exactly once, as the site called it ----
        assert len(self.calls) == 1
        c = self.calls[0]
        assert c["ecx"] == BUF and c["args"] == [a & 0xFFFFFFFF for a in args]
        for r in (UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert c["regs"][r] == REGS[r]
        if g <= 16:                                          # tail-jump: the callee sees the SITE's frame and registers
            assert c["esp"] == sp and c["ret"] == MARKER
            assert c["regs"] == REGS
        else:
            assert c["esp"] < sp and c["ret"] != MARKER
        return bytes(mu.mem_read(PLANE, STRIDE * BH)), c


@pytest.fixture(scope="module")
def emu():
    return Emu()


# ---- planes and the native painters ---------------------------------------------------------------------------
_HOSTILE = (0x41, 0xC6, 0xC4, 0xE0, 0xE1, 0xAE, 0xEE, 0x07, 0x54, 0xC2, 0xC5, 0xBF, 0x53, 0xF0, 0xB9)


def _background():
    """Every pair member the remap knows, everywhere: any write outside (rect & clip) shows."""
    return bytearray(_HOSTILE[(x * 7 + y * 3) % len(_HOSTILE)] for y in range(BH) for x in range(STRIDE))


def _clip_box(l, t, r, b, clip):
    cl, ct, cr, cb = clip
    return max(l, cl, 0), max(t, ct, 0), min(r, cr, BW), min(b, cb, BH)


def _native_tile(plane, top, phase, clip):
    """Buffer_tile: the 1-row dither tile 1:1 over (rect & clip); rows alternate top/0x41 from `phase`."""
    def paint(l, t, r, b):
        x0, y0, x1, y1 = _clip_box(l, t, r, b, clip)
        for y in range(y0, y1):
            for x in range(x0, x1):
                plane[y * STRIDE + x] = top if (y + phase) % 2 == 0 else 0x41
    return paint


def _native_box(plane, top, phase, clip):
    """Buffer_box_sprite(d7f8): a 1-px frame line on the half-open rect's edge + the 1:1 fill cell, clipped."""
    def paint(l, t, r, b):
        x0, y0, x1, y1 = _clip_box(l, t, r, b, clip)
        for y in range(y0, y1):
            for x in range(x0, x1):
                edge = x in (l, r - 1) or y in (t, b - 1)
                plane[y * STRIDE + x] = STROKE if edge else (top if (y + phase) % 2 == 0 else 0x41)
    return paint


def _law(native, rect, clip, g):
    """Expected plane: the native result, then (g > 16) the fe force law over (rect & clip).  Returns
    (plane, keyed top member or None).  The key is fe's own: the colored member whose count over the first
    <= 8 rows of the walked rect exceeds its width // 2 (scaling_laws.dither_force_mate)."""
    out = bytearray(native)
    if g <= 16:
        return bytes(out), None
    x0, y0, x1, y1 = _clip_box(*rect, clip)
    if x1 <= x0 or y1 <= y0:
        return bytes(out), None
    counts: dict[int, int] = {}
    for y in range(y0, min(y1, y0 + 8)):
        for x in range(x0, x1):
            v = native[y * STRIDE + x]
            counts[v] = counts.get(v, 0) + 1
    top = SL.dither_force_mate(counts, x1 - x0)
    for y in range(y0, y1):
        for x in range(x0, x1):
            out[y * STRIDE + x] = SL.pair_remap_pixel(native[y * STRIDE + x], y, g, navy=top == 0xC4, bd=top == 0xC6,
                                                      c5=top == 0xC5, bf=top == 0xBF)
    return bytes(out), top


def _tile_case(emu, g, x, y, w, h, *, clip=(0, 0, BW, BH), phase=0, data_ptr=PLANE):
    bg = _background()
    native = bytearray(bg)
    _native_tile(native, 0xC6, phase, clip)(x, y, x + w, y + h)
    live = bytearray(bg)                                     # the hook paints the same thing into guest memory

    def painter(l, t, r, b):
        if data_ptr:
            _native_tile(live, 0xC6, phase, clip)(l, t, r, b)
            emu.mu.mem_write(PLANE, bytes(live))

    got, call = emu.run(emu.va["t_tile_force"], g, [SRC_TILE, x, y, x, y, w, h], 0x1C, clip=clip, plane=bg,
                        painter=painter, data_ptr=data_ptr)
    if not data_ptr:
        return got, bytes(bg), None, bytes(bg)
    want, top = _law(native, (x, y, x + w, y + h), clip, g)
    return got, want, top, bytes(native)


def _box_case(emu, g, l, t, r, b, *, clip=(0, 0, BW, BH), phase=0):
    bg = _background()
    native = bytearray(bg)
    _native_box(native, 0xC4, phase, clip)(l, t, r, b)
    live = bytearray(bg)

    def painter(pl, pt, pr, pb):
        _native_box(live, 0xC4, phase, clip)(pl, pt, pr, pb)
        emu.mu.mem_write(PLANE, bytes(live))

    for i, v in enumerate((l, t, r, b)):
        _w32(emu.mu, RECT + 4 * i, v)
    got, call = emu.run(emu.va["t_msg_bgforce"], g, [RECT, PARAMS], 8, clip=clip, plane=bg, painter=painter)
    assert call["rect"] == (l, t, r, b), "the native box must get the caller's rect, unmodified"
    want, top = _law(native, (l, t, r, b), clip, g)
    return got, want, top, bytes(native)


def _assert_striped(got, rect, clip, g, top):
    """Direct statement of the law (not via the model): inside (rect & clip) every pair pixel is the stripe
    colour of its DEST-BUFFER row -- T = stripe_rows(g) rows per stripe, top member where (y mod 2T) < T."""
    T = SL.stripe_rows(g)
    assert SL.stripe_period(g) == 2 * T
    x0, y0, x1, y1 = _clip_box(*rect, clip)
    seen = 0
    for y in range(y0, y1):
        want = top if (y % (2 * T)) < T else 0x41
        for x in range(x0, x1):
            v = got[y * STRIDE + x]
            if v != STROKE:
                assert v == want, (g, x, y, hex(v), hex(want))
                seen += 1
    assert seen > 0


# ---- (1) t_tile_force ------------------------------------------------------------------------------------------
TILE_RECTS = [
    ("odd_origin", (11, 7, 61, 33), (0, 0, BW, BH)),
    ("even_origin", (4, 8, 100, 40), (0, 0, BW, BH)),
    ("clipped_all_sides", (11, 7, 61, 33), (20, 13, 50, 30)),
    ("clipped_top_odd", (11, 7, 61, 33), (0, 15, BW, BH)),
    ("three_row_clip", (0, 5, BW, 60), (0, 21, BW, 24)),
    ("past_the_buffer", (-6, -5, 140, 90), (0, 0, BW, BH)),
    ("two_rows", (30, 41, 20, 2), (0, 0, BW, BH)),
]


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("name,rect,clip", TILE_RECTS, ids=[r[0] for r in TILE_RECTS])
def test_tile_force_matches_the_stripe_law(emu, g, phase, name, rect, clip):
    x, y, w, h = rect
    got, want, top, native = _tile_case(emu, g, x, y, w, h, clip=clip, phase=phase)
    assert got == want, f"{name} g={g}"
    if g <= 16:
        assert got == native, "g <= 16 must be the native tile alone"
    else:
        assert top == 0xC6, "the backdrop family must key on the freshly tiled rect"
        _assert_striped(got, (x, y, x + w, y + h), clip, g, 0xC6)


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("name,rect,clip", [
    ("zero_w", (20, 9, 0, 30), (0, 0, BW, BH)),
    ("zero_h", (20, 9, 30, 0), (0, 0, BW, BH)),
    ("negative_w", (20, 9, -4, 30), (0, 0, BW, BH)),
    ("negative_h", (20, 9, 30, -4), (0, 0, BW, BH)),
    ("outside_clip", (10, 7, 20, 10), (40, 30, 80, 60)),
    ("touching_clip", (10, 7, 30, 23), (40, 30, 80, 60)),
    ("empty_clip", (10, 7, 60, 30), (30, 20, 30, 20)),
    ("inverted_clip", (10, 7, 60, 30), (50, 40, 30, 20)),
])
def test_tile_force_empty_rect_writes_nothing(emu, g, name, rect, clip):
    x, y, w, h = rect
    got, want, top, native = _tile_case(emu, g, x, y, w, h, clip=clip)
    assert got == bytes(_background()) == want, f"{name} g={g}: an empty rect & clip must not touch the plane"
    assert _r32(emu.mu, emu.syms["g_fe_dst"]) == 0x66660000, "fe must not be staged/called for an empty rect"


@pytest.mark.parametrize("g", G_SWEEP)
def test_tile_force_buffer_without_pixels(emu, g):
    """Buffer_tile's own early-out (data +0x54 == 0, returns 7): the restripe must not walk a null plane."""
    got, want, _top, _native = _tile_case(emu, g, 11, 7, 61, 33, data_ptr=0)
    assert got == want
    assert _r32(emu.mu, emu.syms["g_fe_dst"]) == 0x66660000


@pytest.mark.parametrize("g", [22, 40])
def test_tile_force_one_row_clip_is_content_keyed(emu, g):
    """Documents fe's content key, not a wish: a ONE-row clip that holds only the pair's 0x41 row carries no
    colored member, so nothing keys and the row stays as tiled; a one-row clip holding the colored row keys."""
    for row, phase in ((20, 0), (20, 1)):
        got, want, top, native = _tile_case(emu, g, 0, 5, BW, 60, clip=(0, row, BW, row + 1), phase=phase)
        assert got == want
        assert top == (0xC6 if (row + phase) % 2 == 0 else None)


@pytest.mark.parametrize("g", [22, 25, 40])
def test_tile_force_foreign_pixels_pass_through(emu, g):
    """Art/text indices drawn by the tile pass through; only the keyed pair is rewritten."""
    bg = _background()
    native = bytearray(bg)
    clip = (0, 0, BW, BH)
    rect = (11, 7, 72, 40)
    _native_tile(native, 0xC6, 0, clip)(*rect)
    for x in range(15, 60, 5):
        native[20 * STRIDE + x] = 0x1F
        native[21 * STRIDE + x] = 0x54           # the s54 hatch member: fe (not s54) is the entry, so it stays
        native[22 * STRIDE + x] = 0xC2

    def painter(l, t, r, b):
        emu.mu.mem_write(PLANE, bytes(native))

    got, _ = emu.run(emu.va["t_tile_force"], g, [SRC_TILE, 11, 7, 11, 7, 61, 33], 0x1C, plane=bg, painter=painter)
    want, top = _law(native, rect, clip, g)
    assert top == 0xC6 and got == want
    for x in range(15, 60, 5):
        assert (got[20 * STRIDE + x], got[21 * STRIDE + x], got[22 * STRIDE + x]) == (0x1F, 0x54, 0xC2)


# ---- (2) t_msg_bgforce -----------------------------------------------------------------------------------------
BOX_RECTS = [
    ("whole_window", (0, 0, BW, BH), (0, 0, BW, BH)),
    ("odd_origin", (9, 5, 97, 58), (0, 0, BW, BH)),
    ("row_clip", (0, 0, BW, BH), (3, 22, BW - 3, 35)),
    ("row_clip_odd", (0, 0, BW, BH), (3, 37, BW - 3, 50)),
    ("clipped_all_sides", (9, 5, 97, 58), (20, 13, 50, 30)),
    ("top_rows_only", (9, 5, 97, 58), (0, 0, BW, 9)),
]


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("name,rect,clip", BOX_RECTS, ids=[r[0] for r in BOX_RECTS])
def test_msg_bgforce_matches_the_stripe_law(emu, g, phase, name, rect, clip):
    got, want, top, native = _box_case(emu, g, *rect, clip=clip, phase=phase)
    assert got == want, f"{name} g={g}"
    if g <= 16:
        assert got == native, "g <= 16 must be the native box alone"
    else:
        assert top == 0xC4, "the navy family must key on the freshly drawn box"
        _assert_striped(got, rect, clip, g, 0xC4)
        l, t, r, b = rect                                   # the frame line is not a pair member: untouched
        x0, y0, x1, y1 = _clip_box(l, t, r, b, clip)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if x in (l, r - 1) or y in (t, b - 1):
                    assert got[y * STRIDE + x] == STROKE


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("name,rect,clip", [
    ("zero_w", (20, 9, 20, 40), (0, 0, BW, BH)),
    ("zero_h", (20, 9, 60, 9), (0, 0, BW, BH)),
    ("inverted", (60, 40, 20, 9), (0, 0, BW, BH)),
    ("outside_clip", (10, 7, 30, 20), (40, 30, 80, 60)),
    ("empty_clip", (10, 7, 60, 30), (30, 20, 30, 20)),
])
def test_msg_bgforce_empty_rect_writes_nothing(emu, g, name, rect, clip):
    got, want, _top, _native = _box_case(emu, g, *rect, clip=clip)
    assert got == bytes(_background()) == want, f"{name} g={g}"
    assert _r32(emu.mu, emu.syms["g_fe_dst"]) == 0x66660000


def test_msg_bgforce_half_open_rect_is_not_widened(emu):
    """No dec/inc of R/B (the t_rwk_boxforce step this dest must NOT take): column r and row b stay untouched."""
    l, t, r, b = 9, 5, 97, 58
    got, want, top, native = _box_case(emu, 40, l, t, r, b)
    bg = _background()
    assert top == 0xC4 and got == want
    for y in range(BH):
        assert got[y * STRIDE + r] == bg[y * STRIDE + r]
    assert got[b * STRIDE: b * STRIDE + STRIDE] == bytes(bg[b * STRIDE: b * STRIDE + STRIDE])


# ---- staging + bytes -------------------------------------------------------------------------------------------
def test_restripe_stages_the_clipped_rect(emu):
    """The fe cells hold rect & clip (so fe's prescan reads only freshly drawn rows) and the dest buffer."""
    _tile_case(emu, 40, 11, 7, 61, 33, clip=(20, 13, 50, 30))
    s, mu = emu.syms, emu.mu
    assert _r32(mu, s["g_fe_dst"]) == BUF
    assert [_r32(mu, s[n]) for n in ("g_fe_x", "g_fe_y", "g_fe_w", "g_fe_h")] == [20, 13, 30, 17]
    _box_case(emu, 40, 9, 5, 97, 58)
    assert [_r32(mu, s[n]) for n in ("g_fe_x", "g_fe_y", "g_fe_w", "g_fe_h")] == [9, 5, 88, 53]


def test_layout_and_templates():
    syms = TF.load_syms()
    layout = TF.assemble_all(syms)
    assert set(layout) == set(TF.THUNK_ORDER)
    spans = sorted((o, o + len(b), n) for n, (o, b) in layout.items())
    for (a0, a1, n), nxt in zip(spans, spans[1:] + [(TF.OFF_LIMIT, 0, "limit")]):
        assert a0 % 16 == 0 and a0 >= TF.OFF_CODE, n
        assert a1 <= nxt[0], f"{n} overlaps {nxt[2]}"
    assert TF.roundtrip_problems(layout, syms) == [], "yaml templates must resolve back to the assembled bytes"
    # the SHIPPED bytes are this assembler's templates (2026-10-25 W2D audit: a hand edit of t_lb_item_stripes that
    # the source of truth did not carry would be undone by the next regeneration)
    _sites, _groups, caves, _symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    shipped = {e["id"]: (int(e["offset"]), " ".join(str(e["bytes"]).split()))
               for c in caves for e in (c.get("contents") or [])}
    names = TF.names_of(layout)
    for name, (off, b) in layout.items():
        assert shipped[name] == (off, TF.templatize(b, PCAVE2 + off, syms, names)), name
    assert "E8 {rel32:t_fac_item_pre}" in shipped["t_lb_item_stripes"][1]
    assert "E8 {rel32:t_fac_rowpost}" in shipped["t_lb_item_stripes"][1]
    for name, (_off, b) in layout.items():                   # contract tails
        tail = {"t_tile_force": b"\xC2\x1C\x00", "t_msg_bgforce": b"\xC2\x08\x00",
                "t_tf_restripe": b"\xC2\x10\x00", "t_lb_item_stripes": b"\xC3"}[name]
        assert b[-len(tail):] == tail
    sites = TF.site_list()
    assert len(sites) == 14 and len({s["va"] for s in sites}) == 14


def test_sites_match_the_pristine_base():
    import config
    if not config.terranx_bak(required=False).exists():
        pytest.skip("pristine .bak absent")
    assert TF.verify_live(TF.site_list()) == []


# ---- t_lb_item_stripes: the faction picker's name-list rows (ListBox items) -----------------------------------
LB_OBJ = DATA + 0x3000                   # the list part `this`
LB_VT = DATA + 0x3800                    # its vtable: [vt+4] = the offset to the Win base
LB_VBASE_OFF = BUF - 0x444 - LB_OBJ      # so that this + [vt+4] + 0x444 == BUF
LB_ITEM = 5


def _row_canvas(pair, phase=0):
    """A list canvas at device density: 1-row dither of `pair` everywhere, a stroke column and a glyph pixel."""
    a, b = pair
    plane = bytearray(STRIDE * BH)
    for y in range(BH):
        for x in range(BW):
            plane[y * STRIDE + x] = a if ((y + phase) & 1) == 0 else b
        plane[y * STRIDE + 3] = STROKE
    plane[5 * STRIDE + 9] = 0x07
    return plane


def _lb_run(emu, g, faction, plane, clip, tops=(0, 0)):
    """Call the drop-in as a ListBox_draw_item site does.  The native stub records its call and leaves the clip
    it was given (draw_item sets the item rect as the canvas clip and leaves it).  tops = the list canvas's
    Win +0x140 / +0x150 (its parent-local top is their sum)."""
    mu = emu.mu
    if not getattr(emu, "_lb_mapped", False):
        mu.mem_map(TF.LB_DRAW_ITEM & ~0xFFF, 0x1000)
        mu.mem_write(TF.LB_DRAW_ITEM, b"\xC2\x04\x00")           # ret 4 (the native contract)
        emu._lb_calls = []

        def on_item(mu_, address, size, user):
            esp = mu_.reg_read(UC_X86_REG_ESP)
            emu._lb_calls.append({"esp": esp, "ret": _r32(mu_, esp), "ecx": mu_.reg_read(UC_X86_REG_ECX),
                                  "item": _r32(mu_, esp + 4)})
            mu_.reg_write(UC_X86_REG_EAX, STUB_EAX)
            mu_.reg_write(UC_X86_REG_ECX, 0xCCCC0001)
            mu_.reg_write(UC_X86_REG_EDX, 0xDDDD0002)
        mu.hook_add(UC_HOOK_CODE, on_item, begin=TF.LB_DRAW_ITEM, end=TF.LB_DRAW_ITEM)
        emu._lb_mapped = True
    emu._lb_calls.clear()
    mu.mem_write(BUF, b"\x00" * 0x500)
    _w32(mu, BUF + F_DATA, PLANE)
    _w32(mu, BUF + F_W, BW)
    _w32(mu, BUF + F_H, -BH)
    _w32(mu, BUF + F_STRIDE, STRIDE)
    for i, v in enumerate(clip):
        _w32(mu, BUF + F_CLIP + 4 * i, v)
    _w32(mu, LB_OBJ, LB_VT)
    _w32(mu, LB_VT + 4, LB_VBASE_OFF)
    mu.mem_write(PLANE, bytes(plane))
    _w32(mu, BUF - 0x444 + 0x140, tops[0])
    _w32(mu, BUF - 0x444 + 0x150, tops[1])
    _w32(mu, emu.symtab["g_rm_yph"], 0)
    _w32(mu, G_VA, g)
    _w32(mu, PERIOD_VA, SL.stripe_period(g))
    _w32(mu, emu.syms["g_rm_force"], 0)
    _w32(mu, emu.syms["g_faction_active"], faction)
    sp = STACK + 0x8000
    mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
    _w32(mu, sp, MARKER)
    _w32(mu, sp + 4, LB_ITEM)
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ECX, LB_OBJ)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.emu_start(emu.va["t_lb_item_stripes"], MARKER, count=20_000_000)
    assert mu.reg_read(UC_X86_REG_EIP) == MARKER, "did not return to the caller"
    assert mu.reg_read(UC_X86_REG_ESP) == sp + 8, "stack imbalance (thiscall with one arg: RET 4)"
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert mu.reg_read(r) == REGS[r], "callee-saved register not preserved"
    assert bytes(mu.mem_read(sp + 8, 0x100)) == b"\xA5" * 0x100, "wrote above its own args"
    assert _r32(mu, emu.syms["g_rm_force"]) == 0
    assert _r32(mu, emu.symtab["g_rm_yph"]) == 0, "the row phase must be cleared for every other fe caller"
    assert len(emu._lb_calls) == 1, "the native ListBox_draw_item must run exactly once"
    c = emu._lb_calls[0]
    assert c["ecx"] == LB_OBJ and c["item"] == LB_ITEM
    armed = bool(faction) and g > 16
    assert (c["esp"] == sp and c["ret"] == MARKER) != armed, "native tail-jump iff not armed"
    return bytes(mu.mem_read(PLANE, STRIDE * BH))


LB_CLIPS = [("whole", (0, 0, BW, BH)), ("one item", (0, 11, BW, 11 + 9)), ("odd item", (2, 7, BW - 3, 7 + 12))]


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("pair", [(0xAE, 0xEE), (0xE0, 0xE1)])
@pytest.mark.parametrize("phase", [0, 1])
@pytest.mark.parametrize("name,clip", LB_CLIPS)
def test_lb_item_stripes_puts_the_item_rows_on_the_law(emu, g, pair, phase, name, clip):
    plane = _row_canvas(pair, phase)
    got = _lb_run(emu, g, faction=1, plane=plane, clip=clip)
    l, t, r, b = clip
    for y in range(BH):
        for x in range(BW):
            v = plane[y * STRIDE + x]
            inside = g > 16 and l <= x < r and t <= y < b
            assert got[y * STRIDE + x] == (SL.pair_remap_pixel(v, y, g) if inside else v), (x, y)


@pytest.mark.parametrize("g", (16, 22, 40))
def test_lb_item_stripes_leaves_every_other_listbox_alone(emu, g):
    plane = _row_canvas((0xAE, 0xEE))
    assert _lb_run(emu, g, faction=0, plane=plane, clip=(0, 0, BW, BH)) == bytes(plane)


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("tops", [(335, 0), (209, 0), (184, 0), (0, 335), (7, 2), (-3, 0), (-1, -6)])
@pytest.mark.parametrize("name,clip", LB_CLIPS)
def test_lb_item_stripes_rows_sit_on_the_picker_grid(emu, g, tops, name, clip):
    """faction_list_stripe_phase: list-canvas row y carries the stripe of PARENT row y + top (the in-list gaps are
    the FactionPickWin canvas capture), through the real fe."""
    plane = _row_canvas((0xAE, 0xEE))
    got = _lb_run(emu, g, faction=1, plane=plane, clip=clip, tops=tops)
    ph = SL.faction_list_stripe_phase(tops[0], tops[1], g) if g > 16 else 0
    l, t, r, b = clip
    for y in range(BH):
        for x in range(BW):
            v = plane[y * STRIDE + x]
            inside = g > 16 and l <= x < r and t <= y < b
            assert got[y * STRIDE + x] == (SL.pair_remap_pixel(v, y + ph, g) if inside else v), (x, y)
