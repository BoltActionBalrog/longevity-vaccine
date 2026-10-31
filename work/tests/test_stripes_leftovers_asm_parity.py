"""Differential: the stripe-rule leftovers (scripts/assemble_stripes_leftovers.py) under Unicorn.

(a) t_hud_backdrop + t_hb_col / t_hb_paint / t_hb_setup, chained to a Buffer_copy_3 stand-in (GDI StretchBlt cannot
    be emulated: a `ret 0x24` stub whose Python-side hook paints the MEASURED centre-aligned NN stretch and records
    the frame it was entered with).  For the real console2_A.pcx and synthetic art, every g in 16..60:

        dest == the engine stretch with every pixel mapped from a vertical A,B,A,B texel of the native art rewritten
        to the pair's top (scaling_laws.pair_top) where stripe_top(dest-buffer row, g), else the mate

    and nothing else (unmarked pixels, outside the rect / the clip, the guard bands); g <= 16 and every refusal leave
    the engine stretch alone; the stub is entered with the caller's nine args and ecx = src; stack balance (RET 0x24),
    callee-saved registers, eax = the copy's result.  The law is stated twice: the module's source-driven port
    (hb_synth, what the preview renders) and scaling_laws.vertical_dither_regen (dest-driven); both must equal the
    asm.  The column rule (scaling_laws.column_dither_marks) is checked against a brute-force window oracle below.

(c) thunk_box_thick_devfill with the proposed 50-byte splice (STEP3 staged from the FULL frame rect), run as the
    REAL patches.yaml bytes of thunk_s54_restripe and thunk_fe_pair_remap (ByteTemplate-resolved), STEP1 / STEP2 as
    painting stubs, every g in 17..60: every pair pixel of the frame -- the stroke-to-fill ring included -- ends on hatch_row_color /
    pair_remap_pixel by absolute dest row; strokes and the outside untouched; the LIVE bytes reproduce the measured
    ring (the 1080 shot's banded first fill column and off-law bottom rows).

Skips (does not fail) if keystone/unicorn are absent.  Run with -p no:faulthandler.
"""
from __future__ import annotations

import pathlib
import random
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
capstone = pytest.importorskip("capstone", reason="capstone absent")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402
import assemble_stripes_leftovers as LO  # noqa: E402

G_SWEEP = tuple(range(16, 61))
G_SCALED = tuple(g for g in G_SWEEP if g > 16)
KEY = LO.KEY
QUAD = 4
PCAVE2, CAVE_LEN = LO.PCAVE2, 0x31000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect)
STACK = 0x00200000
DATA = 0x01000000                                     # clear of the engine pages (Buffer_copy_3 0x5D9xxx, g 0x668xxx) and pcave2
MARKER = 0x00DEAD00
SRC, DST = DATA + 0x100, DATA + 0x800                 # the two Buffer objects
PARAMS, RECT = DATA + 0x1000, DATA + 0x1100
SPLANE = DATA + 0x2000                               # src plane (<= 1024 x 257 + pad)
DPLANE = DATA + 0x80000                              # dest plane (<= 2560 x 642 + pads)
PAD = 0x1000
FILL = 0x55
F_CLIP, F_DATA, F_W, F_H, F_CTAB, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0xA4, 0x4A8
REGS_IN = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333,
           UC_X86_REG_EBP: 0x44444444, UC_X86_REG_EAX: 0x55555555, UC_X86_REG_EDX: 0x66666666}
COPY3_FAIL = 0x10                                    # one of the engine's pre-StretchBlt failure codes

# The game's palette + console art (game dir).  Unreadable -> only the tests that draw with them skip (needs_game);
# the law / template / layout tests still run.
try:
    PAL = LO.load_palette()
    CONSOLE = LO.load_console()
    _GAME_ERR = None
except Exception as e:  # noqa: BLE001
    PAL = CONSOLE = None
    _GAME_ERR = e
needs_game = pytest.mark.skipif(_GAME_ERR is not None, reason=f"game art / palette not readable: {_GAME_ERR}")


def RGB(i):
    return PAL[i]


def ctab(pal):
    return b"".join(bytes((p[2], p[1], p[0], 0)) for p in pal)


# ---- brute-force oracle of the column rule (scaling_laws.column_dither_marks; the law itself is SL's) ----------
def law_is_marked(rows, key, r, c, sh):
    """Column rule: (r, c) lies in a vertical window of four rows A,B,A,B (A != B, neither the key) -- no
    neighbour condition (the console separators are single columns)."""
    for r0 in range(max(0, r - QUAD + 1), min(r, sh - QUAD) + 1):
        a, b = rows[r0][c], rows[r0 + 1][c]
        if a != b and a != key and b != key and rows[r0 + 2][c] == a and rows[r0 + 3][c] == b:
            return True
    return False


def law_mate(rows, key, r, c, sh):
    """The other member of the LAST window (largest start row <= r) that holds (r, c)."""
    for r0 in range(min(r, sh - QUAD), max(0, r - QUAD + 1) - 1, -1):
        a, b = rows[r0][c], rows[r0 + 1][c]
        if a != b and a != key and b != key and rows[r0 + 2][c] == a and rows[r0 + 3][c] == b:
            return a ^ b ^ rows[r][c]
    return None


# ---- premises ------------------------------------------------------------------------------------------------------
@needs_game
def test_measured_art_facts():
    """The console separators are single-column 1-row dither (so the neighbour rule of t_spr would miss them)."""
    marks = SL.column_dither_marks(CONSOLE, KEY)
    per_col = {}
    for (r, c), _m in marks.items():
        per_col[c] = per_col.get(c, 0) + 1
    for c, pair in ((3, (0x0F, 0x8B)), (245, (0x0F, 0x8B)), (260, (0x0F, 0x8B)), (763, (0x0F, 0x8B)),
                    (778, (0x0F, 0x8B)), (1019, (0x0F, 0x8B)), (2, (0x1A, 0x4F))):
        assert per_col[c] >= 90, c
        members = {CONSOLE[r][c] for (r, cc) in marks if cc == c} | {m for (r, cc), m in marks.items() if cc == c}
        assert set(pair) <= members, (c, members)
    # with the neighbour rule the lone separators lose most of their marks
    lone = sum(1 for (r, c) in marks if (r, c - 1) not in marks and (r, c + 1) not in marks and c in (245, 778, 1019))
    assert lone >= 300
    assert len(marks) < 0.2 * sum(v != KEY for row in CONSOLE for v in row)   # most of the art is not dither


@needs_game
def test_module_marks_equal_the_law():
    sh, sw = len(CONSOLE), len(CONSOLE[0])
    marks = SL.column_dither_marks(CONSOLE, KEY)
    for c in (0, 1, 2, 3, 4, 245, 246, 260, 500, 763, 778, 1019, 1023):
        for r in range(sh):
            assert ((r, c) in marks) == law_is_marked(CONSOLE, KEY, r, c, sh), (r, c)
            if (r, c) in marks:
                assert marks[(r, c)] == law_mate(CONSOLE, KEY, r, c, sh), (r, c)


@needs_game
def test_top_rule_is_pair_top():
    """The asm's key order (peak, sum, lower index) == scaling_laws.pair_top on every console pair and on the
    DITHER_FORCE_PAIRS (the table the generic order must agree with, since the asm has no table)."""
    marks = SL.column_dither_marks(CONSOLE, KEY)
    pairs = {tuple(sorted((CONSOLE[r][c], m))) for (r, c), m in marks.items()}
    assert len(pairs) > 30
    for a, b in pairs:
        assert SL.pair_top_by_colour(a, b, RGB) == SL.pair_top_by_colour(b, a, RGB) == SL.pair_top(a, b, RGB), (a, b)
    for top, mate in SL.DITHER_FORCE_PAIRS.items():
        assert SL.pair_top_by_colour(top, mate, RGB) == top
    assert SL.pair_top_by_colour(0x0F, 0x8B, RGB) == 0x0F and SL.pair_top_by_colour(0x1A, 0x4F, RGB) == 0x1A


SHOTS = ((ROOT / "screenshots/scanlines_after6/3840x2160/terranx_pracx_3840x2160_20261005-010926.png", 3840, 2160, 40),
         (ROOT / "screenshots/scanlines_after6/1920x1080/terranx_pracx_1920x1080_20261005-011207.png", 1920, 1080, 22))


@pytest.mark.parametrize("shot,sw_,sh_,g", SHOTS, ids=["4K", "1080"])
def test_stretchblt_is_centre_nn(shot, sw_, sh_, g):
    """Measure the engine, do not model it: the strip's top 40 rows in the user's shots equal the centre-NN
    stretch of console2_A.pcx (+10) far better than the floor model."""
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    if not shot.exists():
        pytest.skip("shot absent")
    img = np.asarray(Image.open(shot).convert("RGB")).astype(np.int64)
    lut = {}
    for i, p in enumerate(PAL):
        lut.setdefault(p, i)
    dw, dh = 1024 * g // 16, 257 * g // 16
    x0, y0 = (sw_ - dw) // 2, sh_ - dh
    src = np.array(CONSOLE)
    cm = np.array([SL.nn_center_index(d, dw, 1024) for d in range(dw)])
    fm = np.array([min((d * 1024) // dw, 1023) for d in range(dw)])
    rmc = np.array([SL.nn_center_index(d, dh, 257) for d in range(40)])
    rmf = np.array([min((d * 257) // dh, 256) for d in range(40)])
    # the strip's left 12 columns x top 40 rows: backdrop the later chrome does not cover (the wings and the
    # panel interiors are overdrawn, so the full strip cannot be scored)
    sub = img[y0:y0 + 40, x0:x0 + 12]
    idx = np.full((40, 12), -1)
    packed = (sub[..., 0] << 16) | (sub[..., 1] << 8) | sub[..., 2]
    for (r, gg, b), i in lut.items():
        idx[packed == ((r << 16) | (gg << 8) | b)] = i
    centre = (src[rmc][:, cm[:12]] == idx).mean()
    floor = (src[rmf][:, fm[:12]] == idx).mean()
    assert centre > 0.95 and floor < 0.85, (centre, floor)


# ---- emulator (a) ----------------------------------------------------------------------------------------------------
SYMS = LO.load_syms()
LAYOUT = LO.assemble_all(SYMS)
T_BACKDROP = PCAVE2 + LAYOUT["t_hud_backdrop"][0]
COPY3 = LO.BUFFER_COPY_3


@pytest.fixture(scope="module")
def uc():
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(PCAVE2, CAVE_LEN)
    for _name, (off, b) in LAYOUT.items():
        u.mem_write(PCAVE2 + off, b)
    u.mem_map(LO.G & ~0xFFF, 0x1000)
    u.mem_map(COPY3 & ~0xFFF, 0x1000)
    u.mem_write(COPY3, b"\xC2\x24\x00")                 # ret 0x24: the engine's own callee-clean contract
    u.mem_map(STACK - 0x10000, 0x20000)
    u.mem_map(DATA, 0x480000)                         # > 3 MB: the full strip at g >= 53 (g = 60: 3840 x 963 + pads)
    u.mem_map(MARKER & ~0xFFF, 0x1000)
    st = {"ret": 0, "painter": None, "seen": None, "errors": []}

    def hook(m, addr, _size, _ud):
        try:
            esp = m.reg_read(UC_X86_REG_ESP)
            st["seen"] = {"esp": esp, "stack": bytes(m.mem_read(esp, 0x28)), "ecx": m.reg_read(UC_X86_REG_ECX),
                          "regs": tuple(m.reg_read(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)),
                          "n": (st["seen"]["n"] + 1) if st["seen"] else 1}
            args = struct.unpack("<9i", bytes(m.mem_read(esp + 4, 36)))
            if st["painter"]:
                st["painter"](m, m.reg_read(UC_X86_REG_ECX), *args)
            m.reg_write(UC_X86_REG_EAX, st["ret"])
            m.reg_write(UC_X86_REG_ECX, 0xCCCC0001)      # a real callee clobbers the caller-saved registers
            m.reg_write(UC_X86_REG_EDX, 0xDDDD0002)
        except Exception as e:  # noqa: BLE001
            st["errors"].append(repr(e))
    u.hook_add(UC_HOOK_CODE, hook, begin=COPY3, end=COPY3)
    u.st = st
    return u


def _r32(m, a):
    return int.from_bytes(m.mem_read(a, 4), "little")


def stretch_painter(m, src_buf, dst_buf, sx, sy, sw, sh, dx, dy, dw, dh):
    """The stand-in for GDI StretchBlt: centre-NN from the src Buffer's plane into the dest Buffer's plane."""
    sdata, sstride = _r32(m, src_buf + F_DATA), _r32(m, src_buf + F_STRIDE)
    ddata, dstride = _r32(m, dst_buf + F_DATA), _r32(m, dst_buf + F_STRIDE)
    if not sdata or not ddata:
        return
    cm = [sx + SL.nn_center_index(x, dw, sw) for x in range(dw)]
    for y in range(dh):
        r = sy + SL.nn_center_index(y, dh, sh)
        row = bytes(m.mem_read(sdata + r * sstride, sx + sw))
        m.mem_write(ddata + (dy + y) * dstride + dx, bytes(row[c] for c in cm))


def run(u, rows, *, g, sx=0, sy=0, sw=None, sh=None, dx=0, dy=0, dw=None, dh=None, bw=None, bh=None, dstride=None,
        clip=None, period=None, copy_ret=0, src_plane=True, dst_plane=True, dst_null=False, painter=stretch_painter,
        pal=PAL, src_bw=None, src_bh=None, entry=T_BACKDROP):
    """Enter t_hud_backdrop as the MainWin_build site does (ecx = src Buffer, nine stack args)."""
    H, W = len(rows), len(rows[0])
    sw = W - sx if sw is None else sw
    sh = H - sy if sh is None else sh
    dw = (sw * g) // 16 if dw is None else dw
    dh = (sh * g) // 16 if dh is None else dh
    bw = dx + dw if bw is None else bw
    bh = dy + dh if bh is None else bh
    dstride = (bw + 3) & ~3 if dstride is None else dstride
    src_bw = W if src_bw is None else src_bw
    src_bh = H if src_bh is None else src_bh
    u.mem_write(LO.G, struct.pack("<i", g))
    u.mem_write(LO.PERIOD, struct.pack("<i", SL.stripe_period(g) if period is None else period))
    sstride = (W + 3) & ~3
    u.mem_write(SRC, b"\0" * 0x4B0)
    u.mem_write(SRC + F_DATA, struct.pack("<I", SPLANE if src_plane else 0))
    u.mem_write(SRC + F_W, struct.pack("<2i", src_bw, -src_bh))
    u.mem_write(SRC + F_STRIDE, struct.pack("<i", sstride))
    u.mem_write(SPLANE, b"".join(bytes(r) + b"\xEE" * (sstride - W) for r in rows))
    u.mem_write(DST, b"\0" * 0x4B0)
    u.mem_write(DST + F_CLIP, struct.pack("<4i", *(clip or (0, 0, bw, bh))))
    u.mem_write(DST + F_DATA, struct.pack("<I", DPLANE if dst_plane else 0))
    u.mem_write(DST + F_W, struct.pack("<2i", bw, -bh))
    u.mem_write(DST + F_CTAB, ctab(pal))
    u.mem_write(DST + F_STRIDE, struct.pack("<i", dstride))
    total = dstride * bh
    u.mem_write(DPLANE - PAD, bytes([FILL]) * (total + 2 * PAD))
    st = u.st
    st["ret"], st["painter"], st["seen"], st["errors"] = copy_ret, painter, None, []
    esp = STACK
    u.mem_write(esp - 0x2000, b"\xCC" * 0x2000)
    args = (0 if dst_null else DST, sx, sy, sw, sh, dx, dy, dw, dh)
    u.mem_write(esp, struct.pack("<I9i", MARKER, *args) + b"\xA5" * 16)
    u.reg_write(UC_X86_REG_ESP, esp)
    u.reg_write(UC_X86_REG_ECX, SRC)
    for r, v in REGS_IN.items():
        u.reg_write(r, v)
    u.emu_start(entry, MARKER, count=600_000_000)
    assert not st["errors"], st["errors"]
    assert u.reg_read(UC_X86_REG_EIP) == MARKER, hex(u.reg_read(UC_X86_REG_EIP))
    assert u.reg_read(UC_X86_REG_ESP) == esp + 0x28                       # RET 0x24
    assert bytes(u.mem_read(esp + 0x28, 16)) == b"\xA5" * 16              # the caller's frame above the args
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert u.reg_read(r) == REGS_IN[r]                                # callee-saved
    blob = bytes(u.mem_read(DPLANE - PAD, total + 2 * PAD))
    assert blob[:PAD] == bytes([FILL]) * PAD and blob[-PAD:] == bytes([FILL]) * PAD   # nothing outside the plane
    seen = st["seen"]
    assert seen and seen["n"] == 1, "Buffer_copy_3 must run exactly once"
    assert seen["ecx"] == SRC and struct.unpack("<9i", seen["stack"][4:]) == args    # the engine's own call
    assert seen["regs"] == tuple(REGS_IN[r] for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP))
    assert u.reg_read(UC_X86_REG_EAX) == copy_ret                         # the copy's result survives
    return {"dest": bytearray(blob[PAD:PAD + total]), "stride": dstride, "seen": seen, "esp": esp,
            "geo": (sx, sy, sw, sh, dx, dy, dw, dh, bw, bh)}


def expected(rows, g, *, sx, sy, sw, sh, dx, dy, dw, dh, bw, bh, stride, clip=None, regen=True, pal=PAL):
    clip = clip or (0, 0, bw, bh)
    rgb = (lambda i: pal[i])
    a = bytearray([FILL]) * (stride * bh)
    SL.vertical_dither_regen(a, stride, rows, KEY, g, rgb, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh,
                             clip=clip, regen=regen)
    b = bytearray([FILL]) * (stride * bh)
    if regen:
        LO.hb_synth(b, stride, rows, g, rgb, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, clip=clip)
    else:
        SL.stretchblt_centre_nn(b, stride, rows, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh)
    assert a == b, "module port != the dest-driven law"
    return a


def _diff(a, b, stride, limit=5):
    out = [(i % stride, i // stride, a[i], b[i]) for i in range(len(a)) if a[i] != b[i]]
    return len(out), out[:limit]


# ---- (a) differential ---------------------------------------------------------------------------------------------
CONSOLE_WINDOWS = [dict(sx=0, sy=0, sw=24, sh=257), dict(sx=236, sy=0, sw=32, sh=257), dict(sx=756, sy=0, sw=30, sh=257),
                   dict(sx=1000, sy=0, sw=24, sh=257), dict(sx=120, sy=30, sw=40, sh=60)]


@pytest.mark.parametrize("g", G_SWEEP)
@needs_game
def test_console_windows_sweep(uc, g):
    """Sub-rects of the real console art (srcX / srcY offsets) at every g: dest == the law."""
    for win in CONSOLE_WINDOWS:
        res = run(uc, CONSOLE, g=g, dx=3, dy=5, **win)
        sx, sy, sw, sh, dx, dy, dw, dh, bw, bh = res["geo"]
        exp = expected(CONSOLE, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"])
        n, sample = _diff(res["dest"], exp, res["stride"])
        assert n == 0, (g, win, n, sample)
        if g > 16:                                   # the pass really changed something on the separators
            plain = expected(CONSOLE, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh,
                             stride=res["stride"], regen=False)
            assert (res["dest"] != plain) == (win["sw"] > 30 or win["sx"] < 10 or win["sx"] >= 1000 or SL.stripe_rows(g) > 0)


@pytest.mark.parametrize("g", (17, 22, 25, 29, 40, 41, 47, 48, 53, 60))
@needs_game
def test_console_full_strip(uc, g):
    """The whole 1024 x 257 strip at the window dims MainWin_build passes (1408 x 353 at g = 22 .. 3840 x 963 at
    g = 60)."""
    res = run(uc, CONSOLE, g=g)
    sx, sy, sw, sh, dx, dy, dw, dh, bw, bh = res["geo"]
    exp = expected(CONSOLE, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"])
    n, sample = _diff(res["dest"], exp, res["stride"])
    assert n == 0, (g, n, sample)
    # the measured defect columns are now T-row runs: native column 3 (0F/8B) through the strip's middle rows
    t = SL.stripe_rows(g)
    x = next(d for d in range(dw) if SL.nn_center_index(d, dw, sw) == 3)
    col = [res["dest"][y * res["stride"] + x] for y in range(dh)]
    y0, y1 = (120 * g) // 16, (180 * g) // 16
    runs = []
    for y in range(y0, y1):
        if runs and runs[-1][0] == col[y]:
            runs[-1][1] += 1
        else:
            runs.append([col[y], 1])
    assert {v for v, _n in runs} <= {0x0F, 0x8B} and all(n == t for _v, n in runs[1:-1]), runs[:12]
    assert col[(y0 // (2 * t)) * 2 * t] == 0x0F                          # the brighter member opens the grid


@needs_game
def test_native_g16_is_the_engine_alone(uc):
    """g <= 16: `push Buffer_copy_3 / ret` -- the stub sees the caller's exact frame; nothing else happens."""
    for g in (16, 10):
        res = run(uc, CONSOLE, g=g, sx=236, sw=32, sh=257, dw=44, dh=353)   # even an enlarge: untouched
        assert res["seen"]["esp"] == res["esp"]                            # entered on the caller's own stack
        sx, sy, sw, sh, dx, dy, dw, dh, bw, bh = res["geo"]
        exp = expected(CONSOLE, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh,
                       stride=res["stride"], regen=False)
        assert res["dest"] == exp


def _synthetic(w=12, h=16, seed=1):
    """Art with a few dither columns, a solid column, a 2-D checker, key texels and a 3-colour column."""
    rnd = random.Random(seed)
    rows = [[0x30] * w for _ in range(h)]
    for r in range(h):
        rows[r][2] = 0x0F if r % 2 == 0 else 0x8B          # pair column
        rows[r][3] = 0x1A if r % 2 == 1 else 0x4F          # pair column, other phase
        rows[r][5] = (0xC6, 0x41)[r % 2]                   # force-table pair
        rows[r][7] = (0x10, 0x20, 0x30)[r % 3]             # 3-cycle: never A,B,A,B
        rows[r][9] = 0x0F if (r + (r // 2)) % 2 == 0 else 0x8B   # A,A,B,B: never A,B,A,B
        rows[r][10] = (KEY, 0x50)[r % 2]                   # key member: excluded
    for r in range(h):
        for c in range(w):
            if c == 6 and rnd.random() < 0.3:
                rows[r][c] = rnd.choice((0x60, 0x61))
    rows[8][2] = 0x77                                      # a break in the pair column
    return rows


@pytest.mark.parametrize("g", G_SCALED)
@needs_game
def test_synthetic_rules(uc, g):
    rows = _synthetic()
    res = run(uc, rows, g=g, dx=7, dy=9, bw=60, bh=70)
    sx, sy, sw, sh, dx, dy, dw, dh, bw, bh = res["geo"]
    exp = expected(rows, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"])
    assert res["dest"] == exp
    plain = expected(rows, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"], regen=False)
    changed = {SL.nn_center_index(i % res["stride"] - dx, dw, sw) for i in range(len(exp)) if exp[i] != plain[i]}
    assert changed <= {2, 3, 5}                            # only the pair columns move
    # every pair column moves, unless the stripes are 1 row (g < 22) or the stretch's own runs are already T rows
    # (g = 48: 3x NN, T = 3) and a column's phase happens to sit on the dy = 9 grid (column 3 at g = 48)
    exact = g % 16 == 0 and SL.stripe_rows(g) == g // 16
    assert {2, 3, 5} <= changed or SL.stripe_rows(g) == 1 and g < 22 or exact and {2, 5} <= changed


@pytest.mark.parametrize("g", (22, 25, 40))
def test_pair_top_port_random_palettes(uc, g):
    """Random palettes and random pairs: the member the asm puts on the stripe-top rows == scaling_laws.pair_top."""
    rnd = random.Random(g)
    for _ in range(12):
        pal = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(256)]
        a, b = rnd.sample(range(10, 250), 2)
        if rnd.random() < 0.3:
            pal[b] = pal[a]                                # equal colours: the lower index must win
        elif rnd.random() < 0.3:
            pal[b] = (max(pal[a]), 0, 0) if max(pal[a]) else (1, 0, 0)   # equal peaks: the sum decides
        rows = [[a if r % 2 == 0 else b] * 6 for r in range(10)]
        res = run(uc, rows, g=g, pal=pal)
        sx, sy, sw, sh, dx, dy, dw, dh, bw, bh = res["geo"]
        exp = expected(rows, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"], pal=pal)
        assert res["dest"] == exp, (a, b, pal[a], pal[b])
        top = SL.pair_top(a, b, lambda i: pal[i])
        assert res["dest"][0] == top and res["dest"][SL.stripe_rows(g) * res["stride"]] == (a ^ b ^ top)


@needs_game
def test_clip_cuts_the_regeneration(uc):
    g = 25
    clip = (12, 100, 40, 200)
    res = run(uc, CONSOLE, g=g, sx=236, sw=32, sh=257, dx=4, dy=6, bw=80, bh=420, clip=clip)
    sx, sy, sw, sh, dx, dy, dw, dh, bw, bh = res["geo"]
    exp = expected(CONSOLE, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"], clip=clip)
    assert res["dest"] == exp
    plain = expected(CONSOLE, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"], regen=False)
    for i in range(len(exp)):
        x, y = i % res["stride"], i // res["stride"]
        if not (clip[0] <= x < clip[2] and clip[1] <= y < clip[3]):
            assert res["dest"][i] == plain[i], (x, y)
    assert res["dest"] != plain


@needs_game
def test_equality_guard_skips_foreign_pixels(uc):
    """A pixel the engine did not leave holding the texel's index (here: a later drawer) is never rewritten."""
    g = 22

    def painter(m, src_buf, dst_buf, *args):
        stretch_painter(m, src_buf, dst_buf, *args)
        ddata, dstride = _r32(m, dst_buf + F_DATA), _r32(m, dst_buf + F_STRIDE)
        for y in range(10, 30):
            m.mem_write(ddata + y * dstride + 5, b"\x99")
    res = run(uc, CONSOLE, g=g, sx=0, sw=24, sh=257, painter=painter)
    for y in range(10, 30):
        assert res["dest"][y * res["stride"] + 5] == 0x99
    sx, sy, sw, sh, dx, dy, dw, dh, bw, bh = res["geo"]
    exp = expected(CONSOLE, g, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh, bw=bw, bh=bh, stride=res["stride"])
    for y in range(10, 30):
        exp[y * res["stride"] + 5] = 0x99
    assert res["dest"] == exp


REFUSALS = [
    ("copy failed", dict(copy_ret=COPY3_FAIL)),
    ("dst null", dict(dst_null=True)),
    ("src plane null", dict(src_plane=False)),
    ("dst plane null", dict(dst_plane=False)),
    ("period < 2", dict(period=1)),
    ("negative srcX", dict(sx=-1, sw=25)),
    ("negative dstY", dict(dy=-1)),
    ("srcH < 4", dict(sh=3)),
    ("srcH > 0x200", dict(sh=0x201, src_bh=0x300)),
    ("dstW == srcW", dict(dw=24)),
    ("dstH == srcH", dict(dh=257)),
    ("src rect past its buffer", dict(sx=1010, sw=24)),
    ("dst rect past its buffer (w)", dict(bw=30)),
    ("dst rect past its buffer (h)", dict(bh=300)),
    ("empty clip", dict(clip=(0, 0, 0, 0))),
]


def clipped_stretch(rows, *, sx, sy, sw, sh, dx, dy, dw, dh, bw, bh, stride):
    """GDI clips to the dest bitmap (and reads nothing outside the source bitmap): the stand-in for the
    out-of-range refusal cases."""
    plane = bytearray([FILL]) * (stride * bh)
    for y in range(dh):
        Y, r = dy + y, sy + SL.nn_center_index(y, dh, sh)
        if not (0 <= Y < bh and 0 <= r < len(rows)):
            continue
        for x in range(dw):
            X, c = dx + x, sx + SL.nn_center_index(x, dw, sw)
            if 0 <= X < bw and 0 <= c < len(rows[0]):
                plane[Y * stride + X] = rows[r][c]
    return plane


@pytest.mark.parametrize("why,kw", REFUSALS, ids=[r[0] for r in REFUSALS])
@needs_game
def test_refusals_leave_the_engine_draw(uc, why, kw):
    g = 25
    base = dict(sx=0, sy=0, sw=24, sh=257, dx=2, dy=2, bw=60, bh=420)
    base.update(kw)
    rows = [r[:] for r in CONSOLE] + [[0x30] * 1024 for _ in range(0x300 - 257)]
    sw, sh = base["sw"], base["sh"]
    dw, dh = base.get("dw", (sw * g) // 16), base.get("dh", (sh * g) // 16)
    stride = (base["bw"] + 3) & ~3
    painted = base.get("src_plane", True) and base.get("dst_plane", True) and not base.get("dst_null")
    plain = clipped_stretch(rows, sx=base["sx"], sy=base["sy"], sw=sw, sh=sh, dx=base["dx"], dy=base["dy"], dw=dw, dh=dh,
                            bw=base["bw"], bh=base["bh"], stride=stride) if painted else bytearray([FILL]) * (stride * base["bh"])

    def painter(m, _src_buf, _dst_buf, *_args):          # the clipped stretch, whatever the thunk re-pushed
        m.mem_write(DPLANE, bytes(plain))
    res = run(uc, rows, g=g, painter=painter, **base)
    assert res["dest"] == plain, why


def test_stack_frame_under_a_page_and_slots():
    assert LO.FRAME + 0x60 < 0x1000
    assert LO.slot_problems(LAYOUT) == []
    assert LO.roundtrip_problems(LAYOUT, SYMS) == []
    assert LO.verify_live(LO.site_list()) == []
    for name, (off, b) in LAYOUT.items():
        lo, hi = LO.SLOTS[name]
        assert lo <= off and off + len(b) <= hi, name
    # no `;` in any asm text (keystone hangs) and every thunk disassembles end to end
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    for name, (off, b) in LAYOUT.items():
        assert sum(i.size for i in md.disasm(b, PCAVE2 + off)) == len(b), name


# ---- (c) devfill STEP3: the full frame rect -------------------------------------------------------------------------
def _live(name):
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = dict(ap.build_symbol_table(symbols, caves))
    cave = next(c for c in caves if c["id"] == "pcave2")
    e = next(c for c in cave["contents"] if c["id"] == name)
    off = int(e["offset"])
    return PCAVE2 + off, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(PCAVE2 + off, symtab)), symtab


DF_VA, DF_LIVE, SYMTAB = _live("thunk_box_thick_devfill")
S54_VA, S54_LIVE, _ = _live("thunk_s54_restripe")
FE_VA, FE_LIVE, _ = _live("thunk_fe_pair_remap")
PROPOSAL = LO.devfill_proposal()
DF_PATCHED = bytes(ap.ByteTemplate(" ".join(PROPOSAL["patched_tokens"])).resolve(DF_VA, SYMTAB))
DFSTEP1 = SYMTAB["thunk_dfstep1_dispatch"]
BOX_SPRITE = SYMTAB["Buffer_box_sprite"]
G_DEVFILL_RECT = SYMTAB["g_devfill_rect"]
DF_ALT = PCAVE2 + 0x2F000                              # the patched variant, assembled beside the live one


def test_devfill_proposal_is_a_pure_splice():
    assert PROPOSAL["found"] and PROPOSAL["byte_off"] == 0xB0 and PROPOSAL["entry_len"] == 250
    assert len(DF_LIVE) == len(DF_PATCHED) == 250
    diff = [i for i in range(250) if DF_LIVE[i] != DF_PATCHED[i]]
    if PROPOSAL["applied"]:                       # live entry == the splice since 2026-10-06
        assert diff == []
    else:
        assert diff and min(diff) >= 0xB0 and max(diff) < 0xB0 + 50
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    ins = list(md.disasm(DF_PATCHED, DF_VA))
    assert sum(i.size for i in ins) == 250 and ins[-1].mnemonic == "ret" and ins[-1].op_str == "8"
    calls = [i for i in ins if i.mnemonic == "call"]
    assert [int(i.op_str, 16) for i in calls] == [DFSTEP1, BOX_SPRITE, S54_VA]      # the three calls, same targets
    text = " ".join(f"{i.mnemonic} {i.op_str}" for i in ins)
    assert "mov edi, dword ptr [ebp - 8]" in text and "mov eax, dword ptr [edi]" in text
    assert f"dword ptr [{G_DEVFILL_RECT:#x}]" not in text.split("call")[-2]      # STEP3 no longer reads the inset rect


@pytest.fixture(scope="module")
def uc2():
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(PCAVE2, CAVE_LEN)
    u.mem_write(DF_VA, DF_LIVE)
    u.mem_write(S54_VA, S54_LIVE)
    u.mem_write(FE_VA, FE_LIVE)
    # the patched variant at DF_ALT: same bytes, the two rel32 calls into the cave re-resolved for the new base
    toks = PROPOSAL["patched_tokens"]
    u.mem_write(DF_ALT, bytes(ap.ByteTemplate(" ".join(toks)).resolve(DF_ALT, SYMTAB)))
    u.mem_write(DFSTEP1, b"\xC2\x08\x00")               # ret 8 (the STEP1 renderer's contract)
    u.mem_map(LO.G & ~0xFFF, 0x1000)
    u.mem_map(BOX_SPRITE & ~0xFFF, 0x1000)
    u.mem_write(BOX_SPRITE, b"\xC2\x08\x00")
    u.mem_map(STACK - 0x10000, 0x20000)
    u.mem_map(DATA, 0x100000)
    u.mem_map(MARKER & ~0xFFF, 0x1000)
    st = {"step1": None, "step2": None, "calls": [], "errors": []}

    def hook(m, addr, _size, _ud):
        try:
            esp = m.reg_read(UC_X86_REG_ESP)
            rp = _r32(m, esp + 4)
            rect = struct.unpack("<4i", bytes(m.mem_read(rp, 16)))
            st["calls"].append((addr, esp, m.reg_read(UC_X86_REG_ECX), rect))
            fn = st["step1"] if addr == DFSTEP1 else st["step2"]
            if fn:
                fn(m, m.reg_read(UC_X86_REG_ECX), rect)
            m.reg_write(UC_X86_REG_EAX, 0x00C0FFEE)
            m.reg_write(UC_X86_REG_ECX, 0xCCCC0001)
            m.reg_write(UC_X86_REG_EDX, 0xDDDD0002)
        except Exception as e:  # noqa: BLE001
            st["errors"].append(repr(e))
    u.hook_add(UC_HOOK_CODE, hook, begin=DFSTEP1, end=DFSTEP1)
    u.hook_add(UC_HOOK_CODE, hook, begin=BOX_SPRITE, end=BOX_SPRITE)
    u.st = st
    return u


def step1_painter(top, mate, stroke, g, k_right=None):
    """hollow_flat as measured: strokes K = stroke_width(g) on the left / top (k_right on the right / bottom, one
    less at fractional g where the StretchBlt drops the last column / row), the fill = the native 1-row dither
    centre-NN enlarged; rows / cols of the INCLUSIVE rect."""
    def paint(m, buf, rect):
        rows, w, h = LO.devfill_frame_model(rect, g, top, mate, stroke, proposed=False, k_right=k_right)
        # devfill_frame_model also applies STEP2 + STEP3; STEP1 alone = strokes + NN fill, re-derived here
        l, t, r, b = rect
        k = SL.stroke_width(g)
        kr = k if k_right is None else k_right
        nh = max(2, round(h * 16 / g))
        data, stride = _r32(m, buf + F_DATA), _r32(m, buf + F_STRIDE)
        for y in range(h):
            line = bytearray(w)
            for x in range(w):
                if y < k or x < k or y > h - 1 - kr or x > w - 1 - kr:
                    line[x] = stroke
                else:
                    line[x] = top if (SL.nn_center_index(y, h, nh) & 1) == 0 else mate
            m.mem_write(data + (t + y) * stride + l, bytes(line))
    return paint


def step2_painter(top, mate):
    """Buffer_box_sprite with the border slices nulled: the fill tile at 1:1 over the half-open rect, dest-anchored
    phase (even dest row = the tile's first row = top)."""
    def paint(m, buf, rect):
        l, t, r, b = rect
        data, stride = _r32(m, buf + F_DATA), _r32(m, buf + F_STRIDE)
        for y in range(t, b):
            m.mem_write(data + y * stride + l, bytes([top if y % 2 == 0 else mate]) * max(0, r - l))
    return paint


def run_devfill(u, entry, g, rect, *, top, mate, stroke, bw=200, bh=120, k_right=None):
    stride = (bw + 3) & ~3
    u.mem_write(LO.G, struct.pack("<i", g))
    u.mem_write(LO.PERIOD, struct.pack("<i", SL.stripe_period(g)))
    for n in ("g_rm_force", "g_fe_dst", "g_fe_x", "g_fe_y", "g_fe_w", "g_fe_h"):
        u.mem_write(SYMTAB[n], struct.pack("<I", 0))
    u.mem_write(DST, b"\0" * 0x4B0)
    u.mem_write(DST + F_CLIP, struct.pack("<4i", 0, 0, bw, bh))
    u.mem_write(DST + F_DATA, struct.pack("<I", DPLANE))
    u.mem_write(DST + F_W, struct.pack("<2i", bw, -bh))
    u.mem_write(DST + F_CTAB, ctab(PAL))
    u.mem_write(DST + F_STRIDE, struct.pack("<i", stride))
    u.mem_write(DPLANE - PAD, bytes([FILL]) * (stride * bh + 2 * PAD))
    u.mem_write(RECT, struct.pack("<4i", *rect))
    u.mem_write(PARAMS, bytes(range(40)))
    st = u.st
    st["step1"], st["step2"], st["calls"], st["errors"] = step1_painter(top, mate, stroke, g, k_right), step2_painter(top, mate), [], []
    esp = STACK
    u.mem_write(esp - 0x2000, b"\xCC" * 0x2000)
    u.mem_write(esp, struct.pack("<I2I", MARKER, RECT, PARAMS) + b"\xA5" * 16)
    u.reg_write(UC_X86_REG_ESP, esp)
    u.reg_write(UC_X86_REG_ECX, DST)
    for r, v in REGS_IN.items():
        u.reg_write(r, v)
    u.emu_start(entry, MARKER, count=200_000_000)
    assert not st["errors"], st["errors"]
    assert u.reg_read(UC_X86_REG_EIP) == MARKER
    assert u.reg_read(UC_X86_REG_ESP) == esp + 0xC                        # RET 8
    assert bytes(u.mem_read(esp + 0xC, 16)) == b"\xA5" * 16
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert u.reg_read(r) == REGS_IN[r]
    blob = bytes(u.mem_read(DPLANE - PAD, stride * bh + 2 * PAD))
    assert blob[:PAD] == bytes([FILL]) * PAD and blob[-PAD:] == bytes([FILL]) * PAD
    assert struct.unpack("<4i", bytes(u.mem_read(RECT, 16))) == rect        # the caller's RECT comes back intact
    return bytearray(blob[PAD:PAD + stride * bh]), stride, list(st["calls"])


def devfill_expected(canvas_after_step2, stride, rect, g, *, top, mate, proposed):
    """THE LAW for (c): over the staged rect, fe's force families (dither_force_mate on the first <= 8 rows) then
    the s54 hatch pairs (hatch_pair_for) rewrite their members to the row colour on the dest-buffer grid."""
    out = bytearray(canvas_after_step2)
    x0, y0, w, h = LO.devfill_stage_rect(rect, g, proposed=proposed)
    counts = {}
    for y in range(y0, y0 + min(8, h)):
        for x in range(x0, x0 + w):
            v = out[y * stride + x]
            counts[v] = counts.get(v, 0) + 1
    fam = SL.dither_force_mate(counts, w)
    hatch = SL.hatch_pair_for(counts, w)
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            v = out[y * stride + x]
            if fam is not None and (v == fam or v == SL.DITHER_FORCE_PAIRS[fam]):
                out[y * stride + x] = SL.stripe_color(fam, y, g)
            elif v in (0xE0, 0xE1, 0xAE, 0xEE):
                out[y * stride + x] = SL.pair_remap_pixel(v, y, g)
            elif hatch is not None and v in (hatch, SL.HATCH_MATE_PAIRS[hatch]):
                out[y * stride + x] = SL.hatch_row_color(hatch, y, g)
    return out


def _after_step2(rect, g, top, mate, stroke, stride, bh, k_right):
    canvas = bytearray([FILL]) * (stride * bh)
    l, t, r, b = rect
    w, h = r - l + 1, b - t + 1
    k = SL.stroke_width(g)
    kr = k if k_right is None else k_right
    nh = max(2, round(h * 16 / g))
    for y in range(h):
        for x in range(w):
            if y < k or x < k or y > h - 1 - kr or x > w - 1 - kr:
                canvas[(t + y) * stride + l + x] = stroke
            else:
                canvas[(t + y) * stride + l + x] = top if (SL.nn_center_index(y, h, nh) & 1) == 0 else mate
    n = SL.devfill_inset(g)
    for y in range(t + n, b - (n + 1)):
        for x in range(l + n, r - (n + 1)):
            canvas[y * stride + x] = top if y % 2 == 0 else mate
    return canvas


FRAMES = [((5, 4), (300, 20), 0xC2, 0x41, 0x1D, "report title band C2/41 (s54 hatch)"),
          ((3, 7), (120, 60), 0xC6, 0x41, 0x1A, "window edge C6/41 (fe backdrop family)"),
          ((9, 2), (80, 30), 0xC4, 0x41, 0x1F, "navy field C4/41"),
          ((1, 1), (40, 12), 0x54, 0x41, 0x1D, "picker hatch 54/41"),
          ((2, 2), (16, 6), 0xC2, 0x41, 0x1D, "tiny band")]


@pytest.mark.parametrize("g", tuple(range(17, 61)))
@needs_game
def test_proposed_devfill_whole_interior_on_the_law(uc2, g):
    k = SL.stroke_width(g)
    for (l, t), (nw, nh), top, mate, stroke, label in FRAMES:
        for kr in sorted({k, max(0, k - 1)}):
            w, h = (nw * g) // 16, (nh * g) // 16
            rect = (l, t, l + w - 1, t + h - 1)
            bw, bh = l + w + 6, t + h + 6
            dest, stride, calls = run_devfill(uc2, DF_ALT, g, rect, top=top, mate=mate, stroke=stroke, bw=bw, bh=bh, k_right=kr)
            assert [c[0] for c in calls] == [DFSTEP1, BOX_SPRITE] and calls[0][3] == rect and calls[0][2] == DST
            l2, t2, r2, b2 = calls[1][3]
            n = SL.devfill_inset(g)
            assert (l2, t2, r2, b2) == (l + n, t + n, rect[2] - (n + 1), rect[3] - (n + 1))     # STEP2 unchanged
            after2 = _after_step2(rect, g, top, mate, stroke, stride, bh, kr)
            exp = devfill_expected(after2, stride, rect, g, top=top, mate=mate, proposed=True)
            assert dest == exp, (g, label, kr, _diff(dest, exp, stride))
            # every pair pixel of the WHOLE frame is on the law; strokes and the outside are untouched
            for y in range(t, t + h):
                for x in range(l, l + w):
                    v, a = dest[y * stride + x], after2[y * stride + x]
                    if a in (top, mate):
                        assert v == (top if SL.stripe_top(y, g) else mate), (g, label, x, y)
                    else:
                        assert v == a
            for i in range(len(dest)):
                x, y = i % stride, i // stride
                if not (l <= x < l + w and t <= y < t + h):
                    assert dest[i] == FILL


def test_devfill_native_g16_untouched(uc2):
    for entry in (DF_VA, DF_ALT):
        u = uc2
        st = u.st
        st["step1"], st["step2"], st["calls"], st["errors"] = None, None, [], []
        u.mem_write(LO.G, struct.pack("<i", 16))
        u.mem_write(RECT, struct.pack("<4i", 1, 2, 30, 40))
        esp = STACK
        u.mem_write(esp, struct.pack("<I2I", MARKER, RECT, PARAMS) + b"\xA5" * 16)
        u.reg_write(UC_X86_REG_ESP, esp)
        u.reg_write(UC_X86_REG_ECX, DST)
        for r, v in REGS_IN.items():
            u.reg_write(r, v)
        u.emu_start(entry, MARKER, count=1_000_000)
        assert u.reg_read(UC_X86_REG_EIP) == MARKER and u.reg_read(UC_X86_REG_ESP) == esp + 0xC
        assert [c[0] for c in st["calls"]] == [BOX_SPRITE] and st["calls"][0][1] == esp     # the caller's own frame
