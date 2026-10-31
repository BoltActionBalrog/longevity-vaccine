"""Differential: t_spr_stripes + t_spr_paint (scripts/assemble_stripes_spr.py) under Unicorn, chained to the REAL
engine bytes of Sprite_draw_2 0x5E4B4A / Sprite_blit_scaled_core 0x5E4B9A / the run-table builder 0x5EB20F / the
clip walkers 0x5EAB0F, 0x5EABBF / ftol 0x6458C8, mapped from the pristine base exe (only IntersectRect, an import,
is a Python stub).  For every measured sprite class and g in 16, 18, 21, 22, 25, 32, 40 the dest plane must equal

    the plain engine draw, with every pixel the engine filled from a DITHER texel of the native sprite rewritten to
    spr_stripes_pixel(...): the pair's brighter member where stripe_top(dest row, g), else its mate

and nothing else: non-dither pixels, key texels, pixels outside the rect / the clip are byte-identical to the engine
draw alone; num <= den is the engine alone (tail-jump, stack and registers as the caller left them).

The law is stated here twice over: THE LAW section below (dest-driven, written from the rule) and the module's
source-driven port (assemble_stripes_spr.spr_synth, what the preview renders); both must equal the asm.  The
engine's own mapping (run table, rect, key skip, clip) is not modelled on trust: test_engine_* compare the Python
port with the real bytes.

NOTE: the live exe detours Sprite_draw_2's entry (thunk_hudmenu_sd2 chain) and Sprite_blit_scaled_core's entry
(thunk_hudmenu_sbc); both pass every draw that is not a HUD-menu strip / the faction-box portrait back to these
bytes.  The emulator runs the pristine entry.

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
pefile = pytest.importorskip("pefile", reason="pefile absent")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402
import assemble_stripes_spr as SP  # noqa: E402
import config  # noqa: E402

G_SWEEP = (16, 18, 21, 22, 25, 32, 40)
G_SCALED = tuple(g for g in G_SWEEP if g > 16)
KEY = SP.PCX_KEY
QUAD = 4


# ---- THE LAW (to be moved to scaling_laws.py) -------------------------------------------------------------------
def law_runs(g: int, n: int) -> list[int]:
    """Dest pixels per source index of the engine's g/16 expand blit (its run table 0x9B3AD8, builder 0x5EB20F)."""
    q, rem = divmod(g, 16)
    err = rem - 32 + (g if q & 1 else 0)
    out = []
    for _ in range(n):
        err += 2 * rem
        out.append(q + 1 if err > 0 else q)
        if err > 0:
            err -= 32
    return out


def law_source_index(d: int, runs: list[int]):
    """The source index whose run holds dest offset d, or None past the last run."""
    acc = 0
    for i, n in enumerate(runs):
        acc += n
        if d < acc:
            return i
    return None


def law_is_dither(rows, key: int, r: int, c: int) -> bool:
    """Column rule: (r, c) lies in a vertical window of four rows A,B,A,B (A != B, neither the key)."""
    h = len(rows)
    for r0 in range(max(0, r - QUAD + 1), min(r, h - QUAD) + 1):
        a, b = rows[r0][c], rows[r0 + 1][c]
        if a != b and a != key and b != key and rows[r0 + 2][c] == a and rows[r0 + 3][c] == b:
            return True
    return False


def law_mate(rows, key: int, r: int, c: int):
    """The other member of the LAST window (largest start row <= r) that holds (r, c) -- the chain's owner."""
    h = len(rows)
    for r0 in range(min(r, h - QUAD), max(0, r - QUAD + 1) - 1, -1):
        a, b = rows[r0][c], rows[r0 + 1][c]
        if a != b and a != key and b != key and rows[r0 + 2][c] == a and rows[r0 + 3][c] == b:
            return a ^ b ^ rows[r][c]
    return None


def law_top(a: int, b: int, rgb) -> int:
    """Brighter by r + g + b; ties -> the lower index."""
    sa, sb = sum(rgb(a)), sum(rgb(b))
    return (a if sa > sb else b) if sa != sb else min(a, b)


def spr_stripes_pixel(rows, key: int, r: int, c: int, y_dest: int, g: int, rgb) -> int:
    """The index t_spr_stripes leaves on a dest pixel of row y_dest that the engine filled from texel (r, c):
    a DITHER texel (column rule, and its left or right neighbour texel passes the column rule too) -> the pair's
    top where (y_dest mod P) < T, else the mate (T = stripe_rows(g), P = 2T); anything else -> the texel."""
    v = rows[r][c]
    w = len(rows[0])
    if g <= 16 or not law_is_dither(rows, key, r, c):
        return v
    if not ((c > 0 and law_is_dither(rows, key, r, c - 1)) or (c + 1 < w and law_is_dither(rows, key, r, c + 1))):
        return v
    mate = law_mate(rows, key, r, c)
    top = law_top(v, mate, rgb)
    t = SL.stripe_rows(g)
    return top if (y_dest % (2 * t)) < t else (v ^ mate ^ top)


def law_draw(dest: bytearray, stride: int, rows, key: int, x: int, y: int, g: int, rgb, *, lo=0, to=0, clip, regen=True):
    """Dest-driven statement of the whole draw (g > 16, origin inside the buffer)."""
    h, w = len(rows), len(rows[0])
    x0, y0 = x + (lo * g) // 16, y + (to * g) // 16
    dw, dh = (w * g) // 16, (h * g) // 16
    rx, ry = law_runs(g, w), law_runs(g, h)
    for Y in range(max(y0, clip[1]), min(y0 + dh, clip[3])):
        r = law_source_index(Y - y0, ry)
        if r is None:
            continue
        for X in range(max(x0, clip[0]), min(x0 + dw, clip[2])):
            c = law_source_index(X - x0, rx)
            if c is None or rows[r][c] == key:
                continue
            dest[Y * stride + X] = spr_stripes_pixel(rows, key, r, c, Y, g, rgb) if regen else rows[r][c]


# ---- measured art ------------------------------------------------------------------------------------------------
# The game's sprite art + palette (game dir).  Unreadable -> only the tests that draw with them skip (needs_game).
try:
    CLASSES = SP.measured_sprites()
    PAL = SP.load_palette()
    _GAME_ERR = None
except Exception as e:  # noqa: BLE001
    CLASSES, PAL, _GAME_ERR = {"se_icons": {}, "se_digits": {}, "logos": {}}, None, e
needs_game = pytest.mark.skipif(_GAME_ERR is not None, reason=f"game art / palette not readable: {_GAME_ERR}")


def RGB(i):
    return PAL[i]


ICON_PICK = [f"icon_r{r}c{c}" for r in range(10) for c in ((r * 2) % 9, (r * 2 + 4) % 9)]
SPRITES = ([("se_icons", n) for n in ICON_PICK] + [("se_digits", n) for n in CLASSES["se_digits"]]
           + [("logos", n) for n in CLASSES["logos"]]) if _GAME_ERR is None else []


@needs_game
def test_measured_art_facts():
    """The premises of the per-texel design, counted on the real files."""
    tot = {}
    for cname, sprites in CLASSES.items():
        d = n = art = chk = 0
        for cell in sprites.values():
            f = SP.census(cell)
            d, n, art, chk = d + f["dither"], n + f["nonkey"], art + f["pair_index_as_art"], chk + f["checker"]
        tot[cname] = (d, n, art, chk)
    assert len(CLASSES["se_icons"]) == 90 and len(CLASSES["se_digits"]) == 8 and len(CLASSES["logos"]) >= 7
    for cname, (d, n, art, chk) in tot.items():
        assert d > 0, cname                                   # every class carries row dither
        assert art > d // 4, cname                            # ... and its pair indices ALSO occur as plain art
        assert chk * 50 < n, cname                            # no 2-D checker to speak of (< 2% of the texels)
    assert tot["se_icons"][0] * 100 // tot["se_icons"][1] >= 20          # icons: about a quarter is dither
    assert tot["se_digits"][0] * 100 // tot["se_digits"][1] <= 20        # digits: mostly glyph strokes
    # no sprite is all-dither or pair-pure: an index test or a per-sprite vote cannot stand in for the texel rule
    assert all(SP.census(c)["dither"] < SP.census(c)["nonkey"] for s in CLASSES.values() for c in s.values())


@needs_game
def test_top_rule_vs_pair_top():
    """spr_pair_top (channel sum) against scaling_laws.pair_top (peak channel first) on every measured pair."""
    same = diff = 0
    for sprites in CLASSES.values():
        for cell in sprites.values():
            for (a, b) in SP.census(cell)["pairs"]:
                if SP.spr_pair_top(a, b, RGB) == SL.pair_top(a, b, RGB):
                    same += 1
                else:
                    diff += 1
    assert same > 0 and diff * 20 <= same + diff, (same, diff)   # the two rules agree on >= 95% of the pairs
    for a, b in ((0x98, 0x1A), (0x67, 0x69), (0xE0, 0xE1), (0xC4, 0x41)):   # the four SE colour families
        assert SP.spr_pair_top(a, b, RGB) == SL.pair_top(a, b, RGB) == law_top(a, b, RGB) == a


@needs_game
def test_module_marks_equal_the_law():
    for cname, name in SPRITES:
        rows, _lo, _to = SP.trim(CLASSES[cname][name])
        marks = SP.spr_marks(rows, KEY)
        for r in range(len(rows)):
            for c in range(len(rows[0])):
                w = len(rows[0])
                dith = law_is_dither(rows, KEY, r, c) and (
                    (c > 0 and law_is_dither(rows, KEY, r, c - 1)) or (c + 1 < w and law_is_dither(rows, KEY, r, c + 1)))
                assert ((r, c) in marks) == dith, (name, r, c)
                if dith:
                    assert marks[(r, c)] == law_mate(rows, KEY, r, c), (name, r, c)


# ---- emulator ----------------------------------------------------------------------------------------------------
PE = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)   # image + ImageBase only: skip the 1.5 s reloc walk
IMG = bytes(PE.get_memory_mapped_image())
BASE = PE.OPTIONAL_HEADER.ImageBase
IMG_END = BASE + ((len(IMG) + 0xFFF) & ~0xFFF)
PCAVE2, CAVE_LEN = SP.PCAVE2, 0x30000
assert IMG_END <= PCAVE2
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
BUF, SPRITE, SPIX = DATA + 0x100, DATA + 0x800, DATA + 0x1000
DPIX = DATA + 0x10000
PAD = 0x2000                                   # guard band before / after the dest plane (must stay untouched)
IAT_INTERSECTRECT = 0x00669338
ISECT_STUB = DATA + 0xF0000
STUB_SD2 = PCAVE2 + 0x2FF00                    # `ret 0x18` (isolated-pass tests)
ALT_STRIPES, ALT_PAINT = PCAVE2 + 0x2E000, PCAVE2 + 0x2E800   # the thunk pair assembled against STUB_SD2
SD2 = SP.SPRITE_DRAW_2
FILL = 0x55

SYMS = SP.load_syms()
LAYOUT = SP.assemble_all(SYMS)
T_STRIPES = PCAVE2 + LAYOUT["t_spr_stripes"][0]


def _alt_pair():
    s = dict(SYMS)
    s["Sprite_draw_2"] = STUB_SD2
    return (SE.assemble(SP.asm_spr_stripes(s, ALT_PAINT), ALT_STRIPES), SE.assemble(SP.asm_spr_paint(s), ALT_PAINT))


@pytest.fixture(scope="module")
def uc():
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(BASE, IMG_END - BASE)
    u.mem_write(BASE, IMG)
    u.mem_map(PCAVE2, CAVE_LEN)
    for _name, (off, b) in LAYOUT.items():
        u.mem_write(PCAVE2 + off, b)
    a, b = _alt_pair()
    u.mem_write(ALT_STRIPES, a)
    u.mem_write(ALT_PAINT, b)
    u.mem_write(STUB_SD2, b"\xC2\x18\x00")
    u.mem_map(STACK - 0x10000, 0x20000)
    u.mem_map(DATA, 0x100000)
    u.mem_map(MARKER & ~0xFFF, 0x1000)
    u.mem_write(IAT_INTERSECTRECT, struct.pack("<I", ISECT_STUB))
    u.mem_write(ISECT_STUB, b"\xC2\x0C\x00")
    seen = {}

    def hook(m, addr, _size, _ud):
        if addr == ISECT_STUB:                 # BOOL IntersectRect(dst, a, b)
            esp = m.reg_read(UC_X86_REG_ESP)
            _ret, pd, pa, pb = struct.unpack("<4I", m.mem_read(esp, 16))
            ra, rb = struct.unpack("<4i", m.mem_read(pa, 16)), struct.unpack("<4i", m.mem_read(pb, 16))
            l, t, r, b_ = max(ra[0], rb[0]), max(ra[1], rb[1]), min(ra[2], rb[2]), min(ra[3], rb[3])
            ok = l < r and t < b_
            m.mem_write(pd, struct.pack("<4i", *((l, t, r, b_) if ok else (0, 0, 0, 0))))
            m.reg_write(UC_X86_REG_EAX, 1 if ok else 0)
        elif addr in (SD2, STUB_SD2):          # record the frame Sprite_draw_2 is entered with
            esp = m.reg_read(UC_X86_REG_ESP)
            seen["sd2"] = {"esp": esp, "stack": bytes(m.mem_read(esp, 0x1C)),
                           "regs": tuple(m.reg_read(r) for r in (UC_X86_REG_ECX, UC_X86_REG_EBX, UC_X86_REG_ESI,
                                                                 UC_X86_REG_EDI, UC_X86_REG_EBP))}
            seen["sd2_calls"] = seen.get("sd2_calls", 0) + 1
    u.hook_add(UC_HOOK_CODE, hook, begin=ISECT_STUB, end=ISECT_STUB)
    u.hook_add(UC_HOOK_CODE, hook, begin=SD2, end=SD2)
    u.hook_add(UC_HOOK_CODE, hook, begin=STUB_SD2, end=STUB_SD2)
    u.seen = seen
    return u


REGS_IN = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333,
           UC_X86_REG_EBP: 0x44444444, UC_X86_REG_EAX: 0x55555555, UC_X86_REG_EDX: 0x66666666}


def run(u, entry, rows, *, x, y, num, den, g=None, period=None, bw=260, bh=200, stride=None, clip=None, lo=0, to=0,
        key=KEY, pitch=None, plane=None, pal=True, name_ptr=0, has_plane=True, has_bits=True, pre=None):
    """Enter `entry` as a Sprite_draw_2 call site would.  Returns dict(dest, eax, regs ok, seen...)."""
    h, w = len(rows), len(rows[0])
    pitch = pitch or w
    stride = stride or ((bw + 3) & ~3)
    g = num if g is None else g
    u.mem_write(SP.G, struct.pack("<i", g))
    u.mem_write(SP.PERIOD, struct.pack("<i", SL.stripe_period(g) if period is None else period))
    u.mem_write(SPRITE, b"\0" * 0x2C)
    u.mem_write(SPRITE, struct.pack("<II", name_ptr, SPIX if has_bits else 0))
    u.mem_write(SPRITE + 8, bytes([key]))
    u.mem_write(SPRITE + 0xC, struct.pack("<7i", pitch, w, h, w + 2 * lo, h + 2 * to, lo, to))
    pix = bytearray(b"\xEE" * (pitch * (h + 4) + 16))
    for r in range(h):
        pix[r * pitch:r * pitch + w] = bytes(rows[r])
    u.mem_write(SPIX, bytes(pix))
    u.mem_write(BUF, b"\0" * 0x4B0)
    u.mem_write(BUF + 0x20, struct.pack("<4i", *(clip or (0, 0, bw, bh))))
    u.mem_write(BUF + 0x54, struct.pack("<I", DPIX if has_plane else 0))
    u.mem_write(BUF + 0x80, struct.pack("<2i", bw, -bh))
    if pal:
        u.mem_write(BUF + 0xA4, b"".join(bytes((PAL[i][2], PAL[i][1], PAL[i][0], 0)) for i in range(256)))
    u.mem_write(BUF + 0x4A8, struct.pack("<i", stride))
    total = stride * bh
    init = bytearray([FILL]) * total if plane is None else bytearray(plane)
    u.mem_write(DPIX - PAD, bytes([FILL]) * PAD + bytes(init) + bytes([FILL]) * PAD)
    if pre:
        pre(u)
    esp = STACK
    u.mem_write(esp - 0x2000, b"\xCC" * 0x2000)
    u.mem_write(esp, struct.pack("<I6i", MARKER, BUF, key, x, y, num, den) + b"\xA5" * 16)
    u.reg_write(UC_X86_REG_ESP, esp)
    u.reg_write(UC_X86_REG_ECX, SPRITE)
    for r, v in REGS_IN.items():
        u.reg_write(r, v)
    u.seen.clear()
    u.emu_start(entry, MARKER, count=40_000_000)
    assert u.reg_read(UC_X86_REG_EIP) == MARKER, hex(u.reg_read(UC_X86_REG_EIP))
    assert u.reg_read(UC_X86_REG_ESP) == esp + 0x1C                       # RET 0x18
    assert bytes(u.mem_read(esp + 0x1C, 16)) == b"\xA5" * 16              # the caller's frame above the args
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert u.reg_read(r) == REGS_IN[r]                                # callee-saved
    blob = bytes(u.mem_read(DPIX - PAD, total + 2 * PAD))
    assert blob[:PAD] == bytes([FILL]) * PAD and blob[-PAD:] == bytes([FILL]) * PAD   # nothing outside the plane
    return {"dest": bytearray(blob[PAD:PAD + total]), "eax": u.reg_read(UC_X86_REG_EAX), "stride": stride,
            "seen": dict(u.seen), "esp": esp}


def sprite_of(cname, name):
    return SP.trim(CLASSES[cname][name])


# ---- the engine port against the real bytes ----------------------------------------------------------------------
@pytest.mark.parametrize("g", range(17, 41))
@needs_game
def test_engine_run_table_and_rect(uc, g):
    """sd2_runs / law_runs == the table the engine builds (0x9B3AD8, all 0x320 entries); the cache pair is set;
    and a keyed draw with draw offsets equals the port, pixel for pixel."""
    rnd = random.Random(g)
    w, h = rnd.randint(1, 40), rnd.randint(1, 40)
    rows = [[rnd.choice((KEY, 0x20, 0x21, 0x22, 0x23)) for _ in range(w)] for _ in range(h)]
    lo, to = rnd.randint(0, 9), rnd.randint(0, 9)
    x, y = rnd.randint(0, 60), rnd.randint(0, 40)
    clip = (rnd.randint(0, 30), rnd.randint(0, 20), rnd.randint(100, 260), rnd.randint(80, 200))
    out = run(uc, SD2, rows, x=x, y=y, num=g, den=16, lo=lo, to=to, clip=clip)
    table = list(struct.unpack("<800i", uc.mem_read(SP.RUNS, 3200)))
    assert table == SP.sd2_runs(g) == law_runs(g, 800)
    assert struct.unpack("<2i", uc.mem_read(SP.CACHE_NUM, 8)) == (g, 16)
    exp = bytearray([FILL]) * len(out["dest"])
    SP.sd2_draw(exp, out["stride"], rows, KEY, x, y, g, lo=lo, to=to, clip=clip)
    assert out["dest"] == exp
    exp2 = bytearray([FILL]) * len(out["dest"])
    law_draw(exp2, out["stride"], rows, KEY, x, y, g, RGB, lo=lo, to=to, clip=clip, regen=False)
    assert exp2 == exp


@pytest.mark.parametrize("g", G_SCALED)
@needs_game
def test_engine_every_size(uc, g):
    """Rows and columns are separable in the engine blit: every length 1..66 on each axis, at an origin with a
    fractional offset product, equals the port (the dropped last texel at fractional ratios included)."""
    for n in range(1, 67):
        col = [[0x20 + (i % 7)] for i in range(n)]
        out = run(uc, SD2, col, x=3, y=2, num=g, den=16, lo=1, to=3, bw=40, bh=200)
        exp = bytearray([FILL]) * len(out["dest"])
        SP.sd2_draw(exp, out["stride"], col, KEY, 3, 2, g, lo=1, to=3, clip=(0, 0, 40, 200))
        assert out["dest"] == exp, ("col", n)
        row = [[0x20 + (i % 7) for i in range(n)]]
        out = run(uc, SD2, row, x=3, y=2, num=g, den=16, lo=3, to=1, bw=200, bh=40)
        exp = bytearray([FILL]) * len(out["dest"])
        SP.sd2_draw(exp, out["stride"], row, KEY, 3, 2, g, lo=3, to=1, clip=(0, 0, 200, 40))
        assert out["dest"] == exp, ("row", n)


# ---- the thunk ---------------------------------------------------------------------------------------------------
def expect(rows, lo, to, x, y, g, stride, total, clip, plane=None):
    """(plain engine draw, the law's result, the module port's result) as bytearrays."""
    base = bytearray([FILL]) * total if plane is None else bytearray(plane)
    plain = bytearray(base)
    law_draw(plain, stride, rows, KEY, x, y, g, RGB, lo=lo, to=to, clip=clip, regen=False)
    law = bytearray(base)
    law_draw(law, stride, rows, KEY, x, y, g, RGB, lo=lo, to=to, clip=clip, regen=True)
    mod = bytearray(base)
    SP.spr_synth(mod, stride, rows, KEY, x, y, g, RGB, lo=lo, to=to, clip=clip)
    return plain, law, mod


@pytest.mark.parametrize("cname,name", SPRITES)
@pytest.mark.parametrize("g", G_SCALED)
@needs_game
def test_thunk_equals_law(uc, cname, name, g):
    rows, lo, to = sprite_of(cname, name)
    x, y = 7 + (g % 3), 5 + (g % 4)                       # both stripe phases get exercised across the sweep
    bw, bh = 260, 200
    clip = (0, 0, bw, bh)
    engine = run(uc, SD2, rows, x=x, y=y, num=g, den=16, lo=lo, to=to, bw=bw, bh=bh)
    out = run(uc, T_STRIPES, rows, x=x, y=y, num=g, den=16, lo=lo, to=to, bw=bw, bh=bh)
    plain, law, mod = expect(rows, lo, to, x, y, g, out["stride"], len(out["dest"]), clip)
    assert engine["dest"] == plain                        # the port of the engine draw is the real draw
    assert out["dest"] == law == mod
    assert out["eax"] == engine["eax"]                    # the draw's result reaches the caller
    assert out["seen"]["sd2_calls"] == 1
    # every pixel that differs from the plain engine draw came from a dither texel and holds a pair member
    marks = SP.spr_marks(rows, KEY)
    owner = {(X, Y): (r, c) for X, Y, r, c in SP.sd2_cells(x, y, g, w=len(rows[0]), h=len(rows), lo=lo, to=to, clip=clip)}
    st = out["stride"]
    changed = 0
    for i, (a, b) in enumerate(zip(plain, out["dest"])):
        if a != b:
            r, c = owner[(i % st, i // st)]
            assert (r, c) in marks and b == marks[(r, c)] and a == rows[r][c]
            changed += 1
    # ... and the regenerated field is exactly T rows of each member on the dest-buffer row grid
    t = SL.stripe_rows(g)
    for (X, Y), (r, c) in owner.items():
        if (r, c) in marks:
            top = law_top(rows[r][c], marks[(r, c)], RGB)
            assert out["dest"][Y * st + X] == (top if (Y // t) % 2 == 0 else rows[r][c] ^ marks[(r, c)] ^ top)
    assert changed <= len(owner)


@pytest.mark.parametrize("cname,name", [("se_icons", "icon_r1c2"), ("se_digits", "digit2_green"), ("logos", "logo_Spartans")])
@needs_game
def test_native_tail(uc, cname, name):
    """num <= den: Sprite_draw_2 is entered with the caller's stack and registers, and draws alone."""
    rows, lo, to = sprite_of(cname, name)
    for num, den in ((16, 16), (1, 1), (8, 16)):
        engine = run(uc, SD2, rows, x=9, y=6, num=num, den=den, lo=lo, to=to, g=16)
        out = run(uc, T_STRIPES, rows, x=9, y=6, num=num, den=den, lo=lo, to=to, g=16)
        assert out["dest"] == engine["dest"] and out["eax"] == engine["eax"]
        s = out["seen"]["sd2"]
        assert s["esp"] == out["esp"]
        assert s["stack"] == struct.pack("<I6i", MARKER, BUF, KEY, 9, 6, num, den)
        assert s["regs"] == (SPRITE, REGS_IN[UC_X86_REG_EBX], REGS_IN[UC_X86_REG_ESI], REGS_IN[UC_X86_REG_EDI],
                             REGS_IN[UC_X86_REG_EBP])
    assert bytes(LAYOUT["t_spr_stripes"][1][:16]) == bytes.fromhex("8B4424143B4424187F0668") + struct.pack("<I", SD2) + b"\xC3"


@pytest.mark.parametrize("g", G_SCALED)
@needs_game
def test_clip_and_background(uc, g):
    """A clip that cuts the icon on all four sides, over a background that already holds the pair's own indices:
    pixels outside the clip are untouched; inside, the law."""
    rows, lo, to = sprite_of("se_icons", "icon_r3c2")
    bw, bh = 120, 110
    stride = 120
    rnd = random.Random(g)
    plane = bytes(rnd.choice((0x98, 0x1A, 0xC4, 0x41, FILL)) for _ in range(stride * bh))
    x, y = 20, 14
    dw, dh = (26 * g) // 16, (26 * g) // 16
    clip = (x + dw // 4, y + dh // 5, x + (3 * dw) // 4, y + (4 * dh) // 5)
    out = run(uc, T_STRIPES, rows, x=x, y=y, num=g, den=16, lo=lo, to=to, bw=bw, bh=bh, stride=stride, clip=clip, plane=plane)
    plain, law, mod = expect(rows, lo, to, x, y, g, stride, stride * bh, clip, plane)
    assert out["dest"] == law == mod
    for Y in range(bh):
        for X in range(bw):
            if not (clip[0] <= X < clip[2] and clip[1] <= Y < clip[3]):
                assert out["dest"][Y * stride + X] == plane[Y * stride + X]
    assert g == 32 or out["dest"] != plain      # 2.0x with T = 2: the lawful field can coincide with plain NN


@needs_game
def test_sprite_pitch_wider_than_blit(uc):
    """pcBits pitch (+0xC) > blit width (+0x10): rows are stepped by the pitch (the faction-preview layout)."""
    rows, lo, to = sprite_of("se_icons", "icon_r4c2")
    for g in (22, 40):
        out = run(uc, T_STRIPES, rows, x=4, y=4, num=g, den=16, lo=lo, to=to, pitch=len(rows[0]) + 13)
        _plain, law, mod = expect(rows, lo, to, 4, 4, g, out["stride"], len(out["dest"]), (0, 0, 260, 200))
        assert out["dest"] == law == mod


def test_tie_takes_lower_index(uc):
    """A dest colour table without contrast (all zero): the lower index is the stripe top; still T-row stripes."""
    rows = [[0x30, 0x30, 0x30], [0x21, 0x21, 0x21]] * 4
    out = run(uc, T_STRIPES, rows, x=2, y=2, num=40, den=16, pal=False, bw=40, bh=40)
    st = out["stride"]
    for Y in range(2, 2 + 20):
        assert out["dest"][Y * st + 3] == (0x21 if (Y % 4) < 2 else 0x30), Y


# ---- the pass in isolation (Sprite_draw_2 := `ret 0x18`), refusals ------------------------------------------------
def _preload(g):
    def pre(u):
        u.mem_write(SP.RUNS, struct.pack("<800i", *SP.sd2_runs(g)))
        u.mem_write(SP.CACHE_NUM, struct.pack("<2i", g, 16))
    return pre


ICON = ("se_icons", "icon_r6c1")


def _painted(rows, lo, to, x, y, g, stride, bh):
    plane = bytearray([FILL]) * (stride * bh)
    SP.sd2_draw(plane, stride, rows, KEY, x, y, g, lo=lo, to=to, clip=(0, 0, 260, bh))
    return plane


@pytest.mark.parametrize("g", G_SCALED)
@needs_game
def test_pass_alone_on_a_prepainted_plane(uc, g):
    rows, lo, to = sprite_of(*ICON)
    plane = _painted(rows, lo, to, 6, 9, g, 260, 200)
    out = run(uc, ALT_STRIPES, rows, x=6, y=9, num=g, den=16, lo=lo, to=to, plane=plane, pre=_preload(g))
    _plain, law, _mod = expect(rows, lo, to, 6, 9, g, 260, 260 * 200, (0, 0, 260, 200))
    assert out["dest"] == law and out["dest"] != plane


@needs_game
def test_nothing_drawn_nothing_written(uc):
    """The engine drew nothing (a foreign drawer, a bailed blit): no dest pixel holds its texel -> no write, even
    with a valid run table.  And a plane that holds OTHER art in the pair's indices is not touched either."""
    rows, lo, to = sprite_of(*ICON)
    for fill in (FILL, 0x67, 0x69):
        plane = bytearray([fill]) * (260 * 200)
        out = run(uc, ALT_STRIPES, rows, x=6, y=9, num=22, den=16, lo=lo, to=to, plane=plane, pre=_preload(22))
        changed = sum(a != b for a, b in zip(plane, out["dest"]))
        if fill == FILL:
            assert changed == 0
        else:                                   # only pixels whose texel IS that index may flip to its mate
            marks = SP.spr_marks(rows, KEY)
            owner = {(X, Y): (r, c) for X, Y, r, c in SP.sd2_cells(6, 9, 22, w=len(rows[0]), h=len(rows), lo=lo, to=to)}
            for i, (a, b) in enumerate(zip(plane, out["dest"])):
                if a != b:
                    r, c = owner[(i % 260, i // 260)]
                    assert rows[r][c] == fill and (r, c) in marks and b == marks[(r, c)]


REFUSALS = {
    "cache_num_stale": dict(pre=lambda u: (u.mem_write(SP.RUNS, struct.pack("<800i", *SP.sd2_runs(22))),
                                           u.mem_write(SP.CACHE_NUM, struct.pack("<2i", 25, 16)))),
    "cache_rejected": dict(pre=lambda u: (u.mem_write(SP.RUNS, struct.pack("<800i", *SP.sd2_runs(22))),
                                          u.mem_write(SP.CACHE_NUM, struct.pack("<2i", -1, 16)))),
    "cache_den": dict(pre=lambda u: (u.mem_write(SP.RUNS, struct.pack("<800i", *SP.sd2_runs(22))),
                                     u.mem_write(SP.CACHE_NUM, struct.pack("<2i", 22, 8)))),
    "filename_backed": dict(name_ptr=0x00687000),
    "no_pcbits": dict(has_bits=False),
    "no_plane": dict(has_plane=False),
    "period_unset": dict(period=0),
    "period_one": dict(period=1),
    "origin_left": dict(x=-3),
    "origin_above": dict(y=-2),
}


@pytest.mark.parametrize("why", sorted(REFUSALS))
@needs_game
def test_refusals_leave_the_engine_draw(uc, why):
    rows, lo, to = sprite_of(*ICON)
    kw = dict(x=6, y=9, pre=_preload(22))
    kw.update(REFUSALS[why])
    if why.startswith("origin"):
        lo = to = 0                             # the engine origin itself is left of / above the buffer
    plane = _painted(rows, lo, to, kw["x"], kw["y"], 22, 260, 200)
    assert plane != bytearray([FILL]) * len(plane)
    out = run(uc, ALT_STRIPES, rows, num=22, den=16, lo=lo, to=to, plane=plane, **kw)
    assert out["dest"] == plane, why
    assert out["seen"]["sd2_calls"] == 1


@needs_game
def test_refusals_by_size(uc):
    """Lower than 4 rows (no window fits), more texels than the stack plane, longer than the engine table."""
    for rows in ([[0x30] * 6, [0x21] * 6, [0x30] * 6],
                 [[0x30 if r & 1 else 0x21] * 60 for r in range(56)],          # 3360 > 0xD00
                 [[0x30 if r & 1 else 0x21] * 3 for r in range(0x321)]):
        h = len(rows)
        bh = 200 if h < 100 else 1300
        plane = bytearray([FILL]) * (260 * bh)
        SP.sd2_draw(plane, 260, rows, KEY, 2, 2, 22, clip=(0, 0, 260, bh))
        out = run(uc, ALT_STRIPES, rows, x=2, y=2, num=22, den=16, plane=plane, bh=bh, pre=_preload(22))
        assert out["dest"] == plane, h
        mod = bytearray(plane)
        SP.spr_synth(mod, 260, rows, KEY, 2, 2, 22, RGB, clip=(0, 0, 260, bh))
        assert mod == plane


@needs_game
def test_largest_logo_cell_fits(uc):
    """A full 65 x 50 cell (an untrimmed custom-faction logo) is inside the stack plane and the frame < one page."""
    assert 65 * 50 <= SP.MAX_TEXELS and SP.FRAME < 0x1000
    rows = [[(0x47 if r & 1 else 0x5A) for _ in range(65)] for r in range(50)]
    out = run(uc, T_STRIPES, rows, x=1, y=1, num=40, den=16, bw=200, bh=160)
    _plain, law, mod = expect(rows, 0, 0, 1, 1, 40, out["stride"], len(out["dest"]), (0, 0, 200, 160))
    assert out["dest"] == law == mod


# ---- placement, templates, the two retargets ----------------------------------------------------------------------
def test_slots_templates_retargets():
    assert SP.slot_problems(LAYOUT) == []
    assert SP.roundtrip_problems(LAYOUT, SYMS) == []
    for name, (off, b) in LAYOUT.items():
        assert off + len(b) <= SP.SLOTS[name][1]
    rts = SP.retargets()
    assert [r["entry"] for r in rts] == ["thunk_se_sd2", "t_dp_sd2_logo"]
    for r in rts:
        # LIVE since exe ce129ccf (2026-10-06): a tail that still reads `jmp Sprite_draw_2` means the feature is off
        assert r["state"] == "already retargeted", r
        assert len(r["old"].split()) == len(r["new"].split()) == 5


@needs_game
def test_se_sd2_retargeted_control_flow(uc):
    """The REAL thunk_se_sd2 bytes (patches.yaml) with its jmp tail retargeted in memory: g > 16 -> the law with
    num = g, den = 16 whatever the site pushed (1, 1); g = 16 -> the engine alone at 16/16."""
    _sites, _groups, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = dict(ap.build_symbol_table(symbols, caves))
    cave = next(c for c in caves if c["id"] == "pcave2")
    e = next(c for c in cave["contents"] if c["id"] == "thunk_se_sd2")
    off = int(e["offset"])
    b = bytearray(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(PCAVE2 + off, symtab))
    r = next(r for r in SP.retargets() if r["entry"] == "thunk_se_sd2")
    if r["state"] == "ok":
        assert bytes(b[-5:]) == bytes.fromhex(r["old"].replace(" ", ""))
        b[-5:] = bytes.fromhex(r["new"].replace(" ", ""))
    uc.mem_write(PCAVE2 + off, bytes(b))
    rows, lo, to = sprite_of("se_icons", "icon_r1c2")
    for g in (22, 40):
        out = run(uc, PCAVE2 + off, rows, x=5, y=5, num=1, den=1, g=g, lo=lo, to=to)
        _plain, law, _mod = expect(rows, lo, to, 5, 5, g, out["stride"], len(out["dest"]), (0, 0, 260, 200))
        assert out["dest"] == law
    engine = run(uc, SD2, rows, x=5, y=5, num=16, den=16, g=16, lo=lo, to=to)
    out = run(uc, PCAVE2 + off, rows, x=5, y=5, num=1, den=1, g=16, lo=lo, to=to)
    assert out["dest"] == engine["dest"] and out["seen"]["sd2"]["esp"] == out["esp"]
