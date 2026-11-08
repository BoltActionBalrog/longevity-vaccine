"""Differential: hm_synth_core (pcave2 +0x65D0) under Unicorn, the REAL patches.yaml bytes.

hm_synth_core(dst, dx, dy, num, den, spr), callee-clean RET 0x18, runs after the engine's MENU / COMMLINK strip blit
and re-synthesises the whole dest rect:

    dest == scaling_laws.strip_synth(dest, ..., num, den, g)
            dims strip_synth_dims (HALF-UP at an exact half), floor NN edge-clamped, the strip_synth_pair members on
            the dest-row stripe grid (light = the even-native-row member on stripe_top rows), key texels skipped,
            cut to the buffer (negative dx / dy included)

for every g 16..60 (the core has no clamp: it reads the period cell, stripe_period(g)) at both (num, den) its callers
pass, (g, 16) and (sc(18), 18); the refusals leave the dest; ebx / esi / edi / ebp kept.  Its bytes == the
assembler's (assemble_hudmenu_scale.ASMS).  The callers (thunk_hudmenu_sd2 / thunk_hudmenu_sbc, the only two) are
emulated up to the call: they pass num > den for every g > 16 and never call at g <= 16 -- the domain where the
core's single-step DDA is the floor map (strip_synth refuses num <= den).

Skips (does not fail) if unicorn / keystone / capstone are absent.
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
capstone = pytest.importorskip("capstone", reason="capstone absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_hudmenu_scale as HM  # noqa: E402


def _live():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    out = {}
    for c in caves:
        for e in c.get("contents") or []:
            va = int(c["virtual_addr"]) + int(e["offset"])
            out[e["id"]] = (va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, sym)))
    return out, sym


LIVE_ALL, S = _live()
VA, LIVE = LIVE_ALL["hm_synth_core"]
# W9C F55 (2026-10-27): two of the core's blocks are CALL helpers in pcave2 0x3F220.. (assemble_menu_strip.py); with
# g_mc_on clear (always, outside t_mc_synth) they compute exactly what the blocks did -- run here with the core.
DIMS_VA, LIVE_DIMS = LIVE_ALL["t_mc_dims"]
COL_VA, LIVE_COL = LIVE_ALL["t_mc_col"]
# 2026-11-07 (commlink_mp_spots): the core's dest-height block is `call t_clmp_synh` (+ the MP strip span while
# g_clmp_son is set, i.e. only under t_clmp_synth); with the cell clear it is the old block -- run here with the core.
SYNH_VA, LIVE_SYNH = LIVE_ALL["t_clmp_synh"]
CLMP_PAGE = SYNH_VA & ~0xFFF
# 2026-11-07 (COMMLINK title strip): the core's source-row block is `call t_clmp_trow` (the title strip's even lines
# while g_clmp_son is set and the sprite is MultiWin +0x10E4); otherwise the old block -- run here with the core.
TROW_VA, LIVE_TROW = LIVE_ALL["t_clmp_trow"]
TITLE = SL.COMMLINK_TITLE_SPRITE
H_PAGE = S["g_clmp_h"] & ~0xFFF                 # t_clmp_synh stashes H there (the header post-pass reads it)
HDR_LO, HDR_HI = H_PAGE, H_PAGE + 0x3000       # pcave2 0x41000..0x43FFF: t_clmp_col / t_clmp_pre / t_clhd_zone + maps


def _load_hdr_region(mu):
    """Map the COMMLINK header region (the core's column call goes through t_clmp_col; t_clmp_synth calls t_clmp_pre)
    and write every live entry in it."""
    for p in range(HDR_LO + 0x1000, HDR_HI, 0x1000):
        mu.mem_map(p, 0x1000)
    for name, (va, b) in LIVE_ALL.items():
        if HDR_LO <= va < HDR_HI:
            mu.mem_write(va, b)


MP_PAGE = 0x0093F000                             # t_clmp_synh reads MultiplayerActive [0x93F660] under g_clmp_son
G, PER = S["g_popup_scale_num"], S["g_stripe_period"]
STACK, MARKER = 0x00200000, 0x00300000
SPR, DBUF, SDATA, DDATA = 0x00700000, 0x00710000, 0x00720000, 0x01000000
FILL = 0x77
KEY = 9
REGS = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333,
        UC_X86_REG_EBP: 0x44444444}


def _w32(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


def sc18(g: int) -> int:
    """hm_sc(18): (18 g + 8) >> 4 (assemble_hudmenu_scale.ASMS['hm_sc'])."""
    return (18 * g + 8) >> 4


def run(code: bytes, g: int, src, *, bw: int, bh: int, dx: int, dy: int, num: int, den: int, key: int = KEY,
        data: bool = True, pitch: int | None = None, ddata: bool = True, stride: int | None = None,
        dims: bytes = LIVE_DIMS, spr: int = SPR, son: int = 0, trow: bytes = LIVE_TROW, rail: bool = False):
    sh, sw = len(src), len(src[0])
    pitch = sw if pitch is None else pitch
    stride = bw if stride is None else stride
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for p in sorted({VA & ~0xFFF, (VA + len(code)) & ~0xFFF, G & ~0xFFF, PER & ~0xFFF, DIMS_VA & ~0xFFF,
                     S["g_mc_on"] & ~0xFFF, CLMP_PAGE}):
        mu.mem_map(p, 0x1000)
    assert S["g_clmp_son"] & ~0xFFF == CLMP_PAGE and TROW_VA & ~0xFFF == CLMP_PAGE
    mu.mem_write(SYNH_VA, LIVE_SYNH)
    mu.mem_write(TROW_VA, trow)
    _w32(mu, S["g_clmp_son"], son)
    mu.mem_map(H_PAGE, 0x1000)
    _load_hdr_region(mu)
    mu.mem_map(MP_PAGE, 0x1000)                   # MultiplayerActive 0: the plain height (the MP span: the e2e guard)
    if rail:                                      # the COMMLINK rail mode as t_clmp_pre leaves it
        w = SL.commlink_strip_width(g)
        _w32(mu, S["g_mc_w"], w)
        _w32(mu, S["g_mc_on"], 2)
        mu.mem_write(S["g_clhd_cmap"], bytes(SL.commlink_strip_cols(g)))
    mu.mem_write(DIMS_VA, dims)
    mu.mem_write(COL_VA, LIVE_COL)
    mu.mem_map(spr & ~0xFFF, 0x1000)
    mu.mem_map(DBUF, 0x1000)
    mu.mem_map(SDATA, 0x40000)
    mu.mem_map(DDATA, 0x400000)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(MARKER, 0x1000)
    mu.mem_write(VA, code)
    mu.mem_write(G, struct.pack("<i", g))         # conftest pairs the period cell: stripe_period(g)
    _w32(mu, spr + 4, SDATA if data else 0)
    mu.mem_write(spr + 8, bytes([key]))
    _w32(mu, spr + 0xC, pitch)
    _w32(mu, spr + 0x10, sw)
    _w32(mu, spr + 0x14, sh)
    if sw <= max(pitch, 1) and pitch > 0:
        mu.mem_write(SDATA, b"".join(bytes(r) + b"\x00" * (pitch - sw) for r in src))
    _w32(mu, DBUF + 0x54, DDATA if ddata else 0)
    _w32(mu, DBUF + 0x4A8, stride)
    _w32(mu, DBUF + 0x80, bw)
    _w32(mu, DBUF + 0x84, -bh)
    total = max(stride, 1) * bh
    mu.mem_write(DDATA, bytes([FILL]) * (total + 0x1000))
    sp = STACK
    mu.mem_write(sp, struct.pack("<I6i", MARKER, DBUF, dx, dy, num, den, spr) + b"\xA5" * 16)
    mu.reg_write(UC_X86_REG_ESP, sp)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.emu_start(VA, MARKER, count=200_000_000)
    plane = bytearray(mu.mem_read(DDATA, total))
    return {"plane": plane, "tail_clean": bytes(mu.mem_read(DDATA + total, 0x1000)) == bytes([FILL]) * 0x1000,
            "esp": mu.reg_read(UC_X86_REG_ESP) - sp, "kept": all(mu.reg_read(r) == v for r, v in REGS.items()),
            "stride": stride}


def strip(W: int, H: int, phase: int, *, key: int = KEY, solid_col=None, pair=(0xC4, 0x41)):
    """A MENU-like strip: 1-px 0x1D border, a key gap (cols 5..8), the interior a 1-row pair dither."""
    rows = []
    for y in range(H):
        r = []
        for x in range(W):
            if x in (0, W - 1) or y in (0, H - 1):
                r.append(0x1D)
            elif 5 <= x <= 8:
                r.append(key)
            elif solid_col is not None and x == solid_col:
                r.append(0x30)
            else:
                r.append(pair[0] if (y + phase) % 2 == 0 else pair[1])
        rows.append(r)
    return rows


def expected(g, src, *, bw, bh, dx, dy, num, den, stride=None, key=KEY):
    stride = bw if stride is None else stride
    out = bytearray([FILL]) * (stride * bh)
    SL.strip_synth(out, stride, bw, bh, src, key, dx, dy, num, den, g)
    return out


# (W, H, phase, dx, dy, buffer pad w / h): in-bounds, origin, negative offsets, cut on the right / bottom, odd heights
CASES = [(40, 12, 0, 3, 5, 8, 6), (33, 9, 1, 0, 0, 8, 6), (21, 14, 0, -2, 7, 8, 6), (40, 12, 1, 30, 2, 8, 6),
         (40, 11, 1, 0, 0, 8, 6), (24, 18, 0, -5, -3, 0, 0), (60, 18, 1, 12, 9, -20, -10), (16, 2, 0, 1, 1, 4, 4)]


def callers_pairs(g: int):
    return [(g, 16), (sc18(g), 18)]


def law_problems(code: bytes, g: int, dims: bytes = LIVE_DIMS) -> list:
    out = []
    for (W, H, ph, dx, dy, pw, ph_) in CASES:
        src = strip(W, H, ph)
        for num, den in callers_pairs(g):
            bw = max(1, (W * num) // den + abs(dx) + pw)
            bh = max(1, (H * num) // den + abs(dy) + ph_)
            res = run(code, g, src, bw=bw, bh=bh, dx=dx, dy=dy, num=num, den=den, dims=dims)
            if g > 16:
                want = expected(g, src, bw=bw, bh=bh, dx=dx, dy=dy, num=num, den=den)
            else:
                want = bytearray([FILL]) * (bw * bh)
            if res["plane"] != want or not res["tail_clean"]:
                out.append(("draw", g, W, H, ph, dx, dy, num, den))
            if res["esp"] != 4 + 0x18 or not res["kept"]:
                out.append(("contract", g, res["esp"], res["kept"]))
    return out


def test_yaml_bytes_are_the_assembler_source():
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    for name in ("hm_synth_core", "hm_sc", "hm_rowY", "thunk_hudmenu_sd2", "thunk_hudmenu_sbc"):
        va, live = LIVE_ALL[name]
        assert HM.V[name] == va, name
        assert bytes(ks.asm(HM.ASMS[name], va)[0]) == live, name


@pytest.mark.parametrize("g", tuple(range(16, 61)))
def test_synthesis_is_strip_synth(g):
    assert law_problems(LIVE, g) == []


def rail_art(pair=(0xC5, 0x41)):
    """A railed COMMLINK strip: e9 edge | 4 field | bf rail | field | bf rail | 4 field, the field a row pair."""
    return [[0xE9 if x == 0 else 0xBF if x in (5, 133) else (pair[0] if y % 2 == 0 else pair[1]) if (x + y) % 17
             else 0x30 + y for x in range(138)] for y in range(18)]


@pytest.mark.parametrize("g", tuple(range(17, 61)))
def test_rail_strips_are_commlink_rail_strip_synth(g):
    """g_mc_on == 2 (t_clmp_pre's COMMLINK rail mode): the core's columns are commlink_strip_cols(g) over the panel
    width hm_sc(138), at both callers' (num, den); rows / pair remap / key as strip_synth."""
    src = rail_art()
    for num, den in callers_pairs(g):
        for dy in (0, 5, -3):
            w = SL.commlink_strip_width(g)
            bw, bh = w + 6, (18 * num) // den + abs(dy) + 4
            res = run(LIVE, g, src, bw=bw, bh=bh, dx=0, dy=dy, num=num, den=den, spr=SPR, son=0, rail=True)
            want = bytearray([FILL]) * (bw * bh)
            SL.commlink_rail_strip_synth(want, bw, bw, bh, src, KEY, 0, dy, num, den, g)
            assert res["plane"] == want and res["tail_clean"], (g, num, den, dy)
            assert res["esp"] == 4 + 0x18 and res["kept"]


def test_rail_columns_line_up_and_are_k_wide():
    """The law's statement: on every railed strip and the header the e9 edge and both bf rails are K = stroke_width
    columns at the same x, at every g 17..60 -- one map, so no seam between strips."""
    for g in range(17, 61):
        cols = SL.commlink_strip_cols(g)
        k = SL.stroke_width(g)
        for c in (0, 5, 133):
            xs = [j for j, v in enumerate(cols) if v == c]
            assert len(xs) == k and xs == list(range(xs[0], xs[0] + k)), (g, c)
        assert len(cols) == SL.strip_synth_dims(138, 28, g, 16)[0]


def title_art(paired: bool):
    """A 138 x 6 COMMLINK-title-like strip: rows 0..2 a plate (two classes per row, key corners on rows 0 / 1), row 3
    a dark line with accents, rows 4 / 5 the fill (two members mixed per column).  paired: rows 2..5 at the middle
    column alternate a, b, a, b (the core's pair probe finds a pair; the remap must then apply on top of the map)."""
    rows = []
    for y in range(6):
        r = []
        for x in range(138):
            if (y == 0 and x < 3) or (y == 1 and x == 0) or (y == 0 and x > 134):
                r.append(KEY)
            elif y < 3:
                r.append((0x50, 0x51, 0x51)[y] if (x * 7 + y) % 5 else (0x4E, 0x18, 0x17)[y])
            elif y == 3:
                r.append(0x29 if x % 11 == 3 else 0xC6)
            else:
                r.append((0x40 if (x + y) % 3 else 0x41) if y == 4 else (0x41 if x % 2 else 0x40))
        rows.append(r)
    if paired:
        for y in range(2, 6):
            rows[y][69] = 0xC5 if y % 2 == 0 else 0x42
    return rows


TITLE_CASES = [(0, 174, 4, 6), (0, 0, 0, 3), (3, 5, 8, 6), (-2, -3, 6, 6), (0, 10, 0, -4), (5, 1, -30, 2)]


def title_problems(g: int, trow: bytes = LIVE_TROW) -> list:
    out = []
    for paired in (False, True):
        src = title_art(paired)
        for dx, dy, pw, ph_ in TITLE_CASES:
            for num, den in callers_pairs(g):
                bw = max(1, (138 * num) // den + abs(dx) + pw)
                bh = max(1, (6 * num) // den + abs(dy) + ph_)
                res = run(LIVE, g, src, bw=bw, bh=bh, dx=dx, dy=dy, num=num, den=den, spr=TITLE, son=1, trow=trow)
                want = bytearray([FILL]) * (bw * bh)
                SL.commlink_title_synth(want, bw, bw, bh, src, KEY, dx, dy, num, den, g)
                if res["plane"] != want or not res["tail_clean"]:
                    out.append(("title", g, paired, dx, dy, num, den))
                if res["esp"] != 4 + 0x18 or not res["kept"]:
                    out.append(("contract", g, res["esp"], res["kept"]))
    return out


@pytest.mark.parametrize("g", tuple(range(17, 61)))
def test_title_strip_is_commlink_title_synth(g):
    """The COMMLINK title strip under g_clmp_son: the core's bytes (with t_clmp_trow) == the law, every g the core can
    see (no clamp), both callers' (num, den), negative / cut offsets, with and without a probe pair."""
    assert title_problems(g) == []


@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_title_map_only_for_the_title_under_son(g):
    """g_clmp_son clear, another sprite, or a sprite of another height: the plain strip_synth (MENU strips, button
    faces, every other COMMLINK strip)."""
    src = title_art(False)
    for spr, son, rows in ((TITLE, 0, src), (SPR, 1, src), (TITLE, 1, src[:5]), (TITLE, 1, src + [src[4], src[5]])):
        bw, bh = (138 * g) // 16 + 4, (len(rows) * g) // 16 + 4
        res = run(LIVE, g, rows, bw=bw, bh=bh, dx=2, dy=1, num=g, den=16, spr=spr, son=son)
        assert res["plane"] == expected(g, rows, bw=bw, bh=bh, dx=2, dy=1, num=g, den=16), (hex(spr), son, len(rows))


def test_title_law_lines_are_even():
    """The law's own statement: the four lines are K = stroke_width(g) rows each at every g 17..40, the fill the rest
    (>= 1 row), every fill row a stripe member on the dest grid."""
    for g in range(17, 41):
        k = SL.stroke_width(g)
        for h in ((6 * g + 8) // 16, (6 * g + 8) // 16 + 1):
            for y0 in (0, 1, 174, 450):
                rows = [SL.commlink_title_src_row(j, y0 + j, h, g, g, 16) for j in range(h)]
                assert [rows.count(r) for r in range(4)] == [k] * 4 and rows[:4 * k] == sorted(rows[:4 * k]), (g, h)
                assert h - 4 * k >= 1
                assert all(r == (4 if SL.stripe_top(y0 + j, g) else 5) for j, r in enumerate(rows) if j >= 4 * k)


def test_title_mutants_are_killed():
    """The sweep catches a K off by one (sar 5 -> sar 4), the fill members swapped, and the gate dropped."""
    muts = {"K": (b"\xC1\xF9\x05", b"\xC1\xF9\x04"), "fill swap": (b"\x7C\x01\x40", b"\x7D\x01\x40")}
    for name, (old, new) in muts.items():
        assert LIVE_TROW.count(old) == 1, name
        bad = LIVE_TROW.replace(old, new)
        assert any(title_problems(g, trow=bad) for g in (22, 25, 40)), name


def test_law_facts():
    """The law's own statements, independent of the bytes: half-up dims, the even-native-row member is light."""
    assert SL.strip_synth_dims(8, 8, 17, 16) == (9, 9)                 # 8.5 -> 9 (half_down would give 8)
    assert SL.half_down(8 * 17, 16) == 8
    for ph in (0, 1):
        s = strip(40, 12, ph)
        light, dark = SL.strip_synth_pair(s, KEY)
        assert light == s[6][20] and dark == s[7][20]                  # even native row = light
    assert SL.strip_synth_pair([[0x30] * 9 for _ in range(9)], KEY) is None
    with pytest.raises(ValueError):
        SL.strip_synth(bytearray(64), 8, 8, 8, strip(8, 8, 0), KEY, 0, 0, 16, 16, 25)


def test_pair_probe_second_row_and_key():
    """The probe tries row sh>>1, then sh>>1 - 1; a key member or a non-alternating column is no pair."""
    g = 25
    src = strip(40, 12, 0)
    for x in range(40):                          # break the window at row 6 only: the probe falls back to row 5
        src[8][x] = 0x30
    assert SL.strip_synth_pair(src, KEY) == (0xC4, 0x41)                # row 5 window; light = the even-row member
    assert SL.strip_synth_pair(strip(40, 12, 1, pair=(0xC4, KEY)), KEY) is None
    for s in (src, strip(40, 12, 1, pair=(0xC4, KEY)), [[0x30] * 40 for _ in range(12)]):
        res = run(LIVE, g, s, bw=72, bh=26, dx=2, dy=3, num=g, den=16)
        assert res["plane"] == expected(g, s, bw=72, bh=26, dx=2, dy=3, num=g, den=16)


REFUSALS = [("sw 2", dict(W=2)), ("sw 2049", dict(W=2049)), ("sh 1", dict(H=1)), ("sh 257", dict(H=257)),
            ("null data", dict(data=False)), ("pitch 0", dict(pitch=0)), ("null dest", dict(ddata=False)),
            ("stride 0", dict(stride=0)), ("den 0", dict(den=0)), ("den -16", dict(den=-16)),
            ("all left of the buffer", dict(dx=-200)), ("all above the buffer", dict(dy=-200))]


@pytest.mark.parametrize("why,kw", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_refusals_leave_the_dest(why, kw):
    g = 25
    W, H = kw.pop("W", 20), kw.pop("H", 10)
    src = [[0xC4 if y % 2 == 0 else 0x41] * W for y in range(H)]
    args = dict(bw=48, bh=30, dx=kw.pop("dx", 2), dy=kw.pop("dy", 2), num=g, den=kw.pop("den", 16))
    args.update(kw)
    res = run(LIVE, g, src, **args)
    assert all(v == FILL for v in res["plane"]) and res["tail_clean"], why
    assert res["esp"] == 4 + 0x18 and res["kept"], why


# ---- the callers: num > den always, nothing at g <= 16 ---------------------------------------------------------------
PCAVE2 = HM.PCAVE2
CORE_CONT = 0x005E4BA0                           # Sprite_blit_scaled_core after the displaced prologue


def _callers_uc():
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(PCAVE2, 0x31000)
    mu.mem_map(LIVE_ALL["t_mc_synth"][0] & ~0xFFF, 0x1000)               # W9C F55: sd2's post-blit call target
    mu.mem_map(CLMP_PAGE, 0x1000)                                         # t_clmp_rowy / _synth / _synh + g_clmp_son
    mu.mem_map(H_PAGE, 0x1000)                                            # g_clmp_h (t_clmp_synth arms it -1)
    _load_hdr_region(mu)                                                  # t_clmp_pre / t_clhd_zone
    for name in ("hm_sc", "hm_rowY", "thunk_hudmenu_sd2", "thunk_hudmenu_sbc", "t_mc_synth",
                 "t_clmp_rowy", "t_clmp_synth", "t_clmp_synh"):
        va, b = LIVE_ALL[name]
        mu.mem_write(va, b)
    mu.mem_write(VA, b"\xF4")                      # hm_synth_core: the hook records its args
    mu.mem_write(HM.PORTRAIT_AVG, b"\xC2\x18\x00")  # the Sprite_draw_2 chain's next owner: stdcall RET 0x18
    for p in sorted({G & ~0xFFF, HM.SCALE_NUM & ~0xFFF, CORE_CONT & ~0xFFF, HM.MENU_BUF & ~0xFFF,
                     HM.BTN1_BUF & ~0xFFF, HM.BTN2_BUF & ~0xFFF, HM.MW_BUF & ~0xFFF, HM.ELSE_RET & ~0xFFF,
                     0x0093F000, 0x007FE000}):            # t_clmp_rowy: MultiplayerActive, MultiWin +0xA24 / +0x1158..
        try:
            mu.mem_map(p, 0x1000)
        except unicorn.UcError:
            pass
    mu.mem_write(CORE_CONT, b"\x8B\xE5\x5D\xC2\x18\x00")   # mov esp,ebp ; pop ebp ; ret 0x18 (the core, drawn)
    mu.mem_map(SPR, 0x1000)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(MARKER, 0x1000)
    return mu


def call_args(entry: str, g: int, *, dest: int, ret: int = MARKER, spr_h: int = 10, y: int = 0, x: int = 4):
    """Run a caller from its entry; -> (num, den) hm_synth_core was called with, or None (not called)."""
    mu = _callers_uc()
    mu.mem_write(G, struct.pack("<i", g))
    _w32(mu, HM.SCALE_NUM, 0x5A5A)
    _w32(mu, HM.SCALE_DEN, 0x6B6B)
    _w32(mu, SPR + 0x14, spr_h)
    _w32(mu, SPR + 0x18, 30)
    _w32(mu, SPR + 0x1C, spr_h)
    for b in (HM.BTN1_BUF, HM.BTN2_BUF):
        _w32(mu, b + 0x80, 200)
        _w32(mu, b + 0x84, -60)
    got = []

    def core(m, _a, _s, _u):
        esp = m.reg_read(UC_X86_REG_ESP)
        got.append(struct.unpack("<6i", bytes(m.mem_read(esp + 4, 24))))
        m.emu_stop()
    mu.hook_add(UC_HOOK_CODE, core, begin=VA, end=VA)
    def chain(m, _a, _s, _u):                    # the chain owner returning to the CALLER: no synthesis follows
        if int.from_bytes(m.mem_read(m.reg_read(UC_X86_REG_ESP), 4), "little") == ret:
            m.emu_stop()
    mu.hook_add(UC_HOOK_CODE, chain, begin=HM.PORTRAIT_AVG, end=HM.PORTRAIT_AVG)
    sp = STACK
    mu.mem_write(sp, struct.pack("<I6i", ret, dest, KEY, x, y, 16, 16))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ECX, SPR)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.emu_start(LIVE_ALL[entry][0], MARKER, count=2_000_000)
    return (got[0][3], got[0][4]) if got else None


def caller_problems(g: int) -> list:
    """Every input class of both callers at g: (num, den) as the callers' own law, num > den; none at g <= 16."""
    s6, s18 = (6 * g + 8) >> 4, sc18(g)
    classes = [
        ("sd2 menu row strip", "thunk_hudmenu_sd2", dict(dest=HM.MENU_BUF, spr_h=18, y=s6 + 3 * s18), (s18, 18)),
        ("sd2 menu other", "thunk_hudmenu_sd2", dict(dest=HM.MENU_BUF, spr_h=12, y=40), (g, 16)),
        ("sd2 menu 18 off-grid", "thunk_hudmenu_sd2", dict(dest=HM.MENU_BUF, spr_h=18, y=s6 + 3 * s18 + 1), (g, 16)),
        ("sd2 council button", "thunk_hudmenu_sd2", dict(dest=HM.BTN1_BUF, ret=HM.ELSE_RET), (g, 16)),
        ("sd2 foreign dest", "thunk_hudmenu_sd2", dict(dest=0x00123000), None),
        ("sbc row strip", "thunk_hudmenu_sbc", dict(dest=HM.MW_BUF, spr_h=18, y=6 + 2 * 18), (s18, 18)),
        ("sbc other", "thunk_hudmenu_sbc", dict(dest=HM.MW_BUF, spr_h=12, y=40), (g, 16)),
        ("sbc foreign dest", "thunk_hudmenu_sbc", dict(dest=0x00123000), None),
    ]
    out = []
    for label, entry, kw, want in classes:
        if g <= 16:
            want = None
        got = call_args(entry, g, **kw)
        if got != want or (got is not None and not got[0] > got[1]):
            out.append((label, g, got, want))
    return out


@pytest.mark.parametrize("g", tuple(range(10, 61)))
def test_callers_pass_num_above_den(g):
    assert caller_problems(g) == []


def test_only_two_callers():
    """No other entry reaches hm_synth_core (rel32 call / jmp, abs32 push / mov): t_clmp_synth (which COMMLINK's
    thunk_hudmenu_sbc calls since 2026-11-07) and t_mc_synth, which thunk_hudmenu_sd2 calls instead since W9C F55 (it passes every non-MENU-strip draw on unchanged)."""
    refs = set()
    for cid, (va, b) in LIVE_ALL.items():
        for i in range(len(b) - 4):
            tgt_rel = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if b[i] in (0xE8, 0xE9) and tgt_rel == VA:
                refs.add(cid)
            if int.from_bytes(b[i:i + 4], "little") == VA and cid != "hm_synth_core":
                refs.add(cid)
    assert refs == {"t_mc_synth", "t_clmp_synth"}, refs
    sbc_va, sbc = LIVE_ALL["thunk_hudmenu_sbc"]          # 2026-11-07: sbc's post-blit call -> t_clmp_synth -> the core
    tc = LIVE_ALL["t_clmp_synth"][0]
    assert any(sbc[i] == 0xE8 and (sbc_va + i + 5 + int.from_bytes(sbc[i + 1:i + 5], "little", signed=True))
               & 0xFFFFFFFF == tc for i in range(len(sbc) - 4))
    sd2_va, sd2 = LIVE_ALL["thunk_hudmenu_sd2"]
    t = LIVE_ALL["t_mc_synth"][0]
    assert any(sd2[i] == 0xE8 and (sd2_va + i + 5 + int.from_bytes(sd2[i + 1:i + 5], "little", signed=True))
               & 0xFFFFFFFF == t for i in range(len(sd2) - 4))


# ---- mutants ---------------------------------------------------------------------------------------------------------
def _patch(code: bytes, old: bytes, new: bytes, nth: int = 0) -> bytes:
    i = -1
    for _ in range(nth + 1):
        i = code.index(old, i + 1)
    return code[:i] + new + code[i + len(old):]


MUTANTS = {                                       # (bytes, old, new, nth); "dims" = t_mc_dims (the core's width block)
    "width dims half-down (drop the +den/2)": ("dims", b"\xD1\xFA\x01\xD0", b"\xD1\xFA\x90\x90", 0),
    "light / dark swapped (jl -> jge)": ("core", b"\x3B\x55\xA0\x7C", b"\x3B\x55\xA0\x7D", 0),
    "light = the odd-row member (jnz -> jz)": ("core", b"\xF7\xC3\x01\x00\x00\x00\x75", b"\xF7\xC3\x01\x00\x00\x00\x74", 0),
}


@pytest.mark.parametrize("name", list(MUTANTS))
def test_mutants_are_killed(name):
    where, old, new, nth = MUTANTS[name]
    live = LIVE_DIMS if where == "dims" else LIVE
    bad = _patch(live, old, new, nth)
    assert len(bad) == len(live) and bad != live
    if where == "dims":
        assert any(law_problems(LIVE, g, dims=bad) for g in (17, 22, 25, 40, 48, 60)), f"the sweep misses {name}"
    else:
        assert any(law_problems(bad, g) for g in (17, 22, 25, 40, 48, 60)), f"the sweep misses mutant {name}"
