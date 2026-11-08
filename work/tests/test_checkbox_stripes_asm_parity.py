"""checkbox_stripes (fix 28): t_ck_draw / t_ck_list / t_ck_core, the yaml bytes under Unicorn vs the law.

Law (scaling_laws.py): scanicon_pair_lut / scanicon_top_parity / scanicon_pixels / scanicon_draw (the checkbox X
sprites' scanline law), checkbox_list_phase, checkbox_list_y.  Every case maps the three thunks at their real pcave2
VAs, a Sprite struct + texel plane, a dest Buffer (clip +0x20..+0x2C, data +0x54, W +0x80, H +0x84 NEGATIVE, colour
table +0xA4, stride +0x4A8) inside its GraphicWin (Win +0x140 / +0x150 for the list phase), and records-and-returns
stubs at Sprite_draw_2 (RET 0x18) and Sprite_blit_scaled_core (RET 0x10).  The dest plane starts as noise, so a write
outside the law's pixels (or a missed one) shows.

Arts: the three real checkbox sprites (interface.pcx (227,1) / (227,20) / (227,39), +10 as the engine loads them,
the real palette likewise; skipped without the game files) and seeded synthetic scanline icons that exercise what the
real ones do not: keyed texels, ties, odd sizes, draw offsets, a 32x32 canvas, a non-square ratio.

Cost: one Uc per module, memory rewritten per case; a draw is ~10 ms (emulation + the Python reference); ~1,600 draws,
~25 s serial: every g 17..40 at every phase for each art is the proof the brief asks for.  The heavy items are
parametrised per art / per Win top, so xdist spreads them (no item above ~3 s).
"""
from __future__ import annotations

import pathlib
import random
import re
import sys

import pytest

np = pytest.importorskip("numpy", reason="numpy absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_patches as ap  # noqa: E402
import assemble_checkbox_stripes as AC  # noqa: E402
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

VA = {n: AC.PCAVE2 + AC.SLOTS[n] for n in ("t_ck_draw", "t_ck_list", "t_ck_core", "t_nw_box")}
STACK, SP0 = 0x00300000, 0x0030F000
RET_SITE = 0x00401000
REC = 0x00600000                 # stub record: tag, ecx, 6 args
BOXD = 0x00720000                 # t_nw_box cases: rect, params, four edge sprites, the tile Buffer, the tile texels
SPR, TEX = 0x007794D8, 0x00701000      # a checkbox sprite address: t_ck_draw refuses every other
OTHER_SPR = 0x009B8F60                  # CheckList's default 32x32 sprite: must be refused
ARROW_SPR = 0x00788038                  # the lobby's 7x13 pull-down arrow: accepted since 2026-11-07
#: the arrow as the engine holds it (interface.pcx +10; key 9), read off the emulated lobby (checkbox_emu.lobby, the
#: sprite thunk_nw_blit_left receives) -- test_scaling_checkbox_stripes.py pins it against the real image
ARROW_ART = [[(0xAE if r % 2 == 0 else 0xEE) if c <= min(r, 12 - r) else 9 for c in range(7)] for r in range(13)]
WIN = 0x00710000                 # GraphicWin; the dest Buffer = WIN + 0x444
DST = WIN + 0x444
PIX = 0x00800000                 # dest plane
PW, PH = 160, 120                # dest plane dims (stride PW)
STUB_SD2, STUB_CORE = 0xD2, 0xC0
SENTINELS = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x4444}


def _yaml_code() -> dict[str, bytes]:
    _s, _g, caves, syms = ap.load_patches(ROOT / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    out = {}
    for c in (c for cave in caves if cave["id"] == "pcave2" for c in cave.get("contents", [])):
        if c["id"] in VA:
            assert int(c["offset"]) == AC.SLOTS[c["id"]]
            out[c["id"]] = ap.ByteTemplate(c["bytes"]).resolve(VA[c["id"]], symtab)
        if c["id"] == "g_ck_ph":
            assert int(c["offset"]) == AC.SLOTS["g_ck_ph"]
    assert set(out) == set(VA)
    return out


CODE = _yaml_code()


STUBS = 0x00610000              # the stub bodies (each engine entry holds a jmp: the two entries are 0x50 apart)


def _stub(ret: int, tag: int) -> bytes:
    return AC.assemble(f"""
        mov  dword ptr [{REC:#x}], {tag:#x}
        mov  dword ptr [{REC + 4:#x}], ecx
        mov  eax, dword ptr [esp+4]
        mov  dword ptr [{REC + 8:#x}], eax
        mov  eax, dword ptr [esp+8]
        mov  dword ptr [{REC + 12:#x}], eax
        mov  eax, dword ptr [esp+12]
        mov  dword ptr [{REC + 16:#x}], eax
        mov  eax, dword ptr [esp+16]
        mov  dword ptr [{REC + 20:#x}], eax
        mov  eax, dword ptr [esp+20]
        mov  dword ptr [{REC + 24:#x}], eax
        mov  eax, dword ptr [esp+24]
        mov  dword ptr [{REC + 28:#x}], eax
        mov  eax, dword ptr [{AC.G_CK_PH:#x}]
        mov  dword ptr [{REC + 32:#x}], eax
        ret  {ret:#x}
    """, STUBS + (0 if tag == STUB_SD2 else 0x100))


class Rig:
    """One Uc with every page mapped once; `draw` rewrites the case's memory and runs one thunk."""

    def __init__(self):
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((AC.PCAVE2 + 0x33000, 0x1000), (0x668000, 0x1000), (0x5E4000, 0x1000), (0x5E2000, 0x1000),
                           (BOXD, 0x4000),
                           (STACK, 0x10000), (REC, 0x1000), (0x700000, 0x2000), (SPR & ~0xFFF, 0x1000),
                           (OTHER_SPR & ~0xFFF, 0x1000), (ARROW_SPR & ~0xFFF, 0x1000), (WIN, 0x1000), (PIX, 0x10000),
                           (RET_SITE & ~0xFFF, 0x1000), (STUBS, 0x1000)):
            uc.mem_map(base, size)
        for n, b in CODE.items():
            uc.mem_write(VA[n], b)
        uc.mem_write(STUBS, _stub(0x18, STUB_SD2))
        uc.mem_write(STUBS + 0x100, _stub(0x10, STUB_CORE))
        uc.mem_write(AC.SPRITE_DRAW_2, AC.assemble(f"jmp {STUBS:#x}", AC.SPRITE_DRAW_2))
        uc.mem_write(AC.SPRITE_BLIT_SCALED_CORE, AC.assemble(f"jmp {STUBS + 0x100:#x}", AC.SPRITE_BLIT_SCALED_CORE))
        uc.mem_write(STUBS + 0x200, AC.assemble(f"""
            mov  dword ptr [{REC:#x}], 0xB0
            mov  dword ptr [{REC + 4:#x}], ecx
            mov  eax, dword ptr [esp+4]
            mov  dword ptr [{REC + 8:#x}], eax
            mov  eax, dword ptr [esp+8]
            mov  dword ptr [{REC + 12:#x}], eax
            ret  8
        """, STUBS + 0x200))
        uc.mem_write(AC.BUFFER_BOX_SPRITE, AC.assemble(f"jmp {STUBS + 0x200:#x}", AC.BUFFER_BOX_SPRITE))
        uc.mem_write(RET_SITE, b"\xF4")

    def w32(self, a, v):
        self.uc.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, a, signed=False):
        return int.from_bytes(self.uc.mem_read(a, 4), "little", signed=signed)

    def run(self, thunk, *, g, rows, key, pal, args, offs=(0, 0), clip=(0, 0, PW, PH), tops=(0, 0), ph0=0,
            seed=0, texel_ptr=TEX, pitch=None, bw=None, bh=None, period=None, ddata=PIX, spr=SPR):
        uc = self.uc
        sh, sw = len(rows), len(rows[0])
        pitch = sw if pitch is None else pitch
        uc.mem_write(TEX, bytes(v for r in rows for v in (list(r) + [0] * (pitch - sw))))
        for off, v in ((4, texel_ptr), (8, key & 0xFF), (0xC, pitch), (0x10, sw if bw is None else bw),
                       (0x14, sh if bh is None else bh), (0x18, sw), (0x1C, sh), (0x20, offs[0]), (0x24, offs[1])):
            self.w32(spr + off, v)
        for off, v in ((0x20, clip[0]), (0x24, clip[1]), (0x28, clip[2]), (0x2C, clip[3]), (0x54, ddata),
                       (0x80, PW), (0x84, -PH), (0x4A8, PW)):
            self.w32(DST + off, v)
        uc.mem_write(DST + 0xA4, bytes(b for c in pal for b in (c[2], c[1], c[0], 0)))
        self.w32(WIN + 0x140, tops[0])
        self.w32(WIN + 0x150, tops[1])
        noise = random.Random(seed).randbytes(PW * PH)
        uc.mem_write(PIX, noise)
        self.w32(0x668740, g)                                   # conftest writes the period cell with it
        if period is not None:
            self.w32(0x66879C, period)
        self.w32(AC.G_CK_PH, ph0)
        uc.mem_write(REC, b"\xEE" * 36)
        sp = SP0
        for v in reversed(args):
            sp -= 4
            self.w32(sp, v)
        sp -= 4
        self.w32(sp, RET_SITE)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_ECX, spr)
        for r, v in SENTINELS.items():
            uc.reg_write(r, v)
        uc.emu_start(VA[thunk], RET_SITE, timeout=600_000_000)        # us: a hang bound only -- the end marker decides
        assert uc.reg_read(UC_X86_REG_EIP) == RET_SITE, "the thunk returned (not cut short)"
        assert uc.reg_read(UC_X86_REG_ESP) == SP0, "callee-cleanup contract"
        for r, v in SENTINELS.items():
            assert uc.reg_read(r) == v, "callee-saved register clobbered"
        rec = [self.r32(REC + 4 * i, signed=True) for i in range(9)]
        return noise, bytes(uc.mem_read(PIX, PW * PH)), rec


def _expected(noise, *, g, rows, key, pal, x, y, num, den, phase, offs=(0, 0), clip=(0, 0, PW, PH)):
    dest = bytearray(noise)
    l, t, r, b = max(clip[0], 0), max(clip[1], 0), min(clip[2], PW), min(clip[3], PH)
    SL.scanicon_draw(dest, PW, (l, t, r, b), rows, key, x, y, num, den, g, phase, lambda i: pal[i], offs)
    return bytes(dest)


# ---------------------------------------------------------------------------------------------- arts
def _real_arts():
    try:
        from PIL import Image
        pcx = Image.open(config.game_dir(required=False) / "interface.pcx")
    except Exception:
        return None
    a = np.array(pcx)
    p = np.array(pcx.getpalette()).reshape(-1, 3)
    pal = [(0, 0, 0)] * 10 + [tuple(int(c) for c in p[i]) for i in range(246)]      # +10 at load
    arts = {f"real{y}": (a[y:y + 18, 227:245].astype(int) + 10).tolist() for y in (1, 20, 39)}
    return arts, pal


REAL = _real_arts()


def _synthetic(seed: int, w: int, h: int, key: int | None):
    """A scanline icon: classes (bg, stroke, edge) each with an even/odd row pair, a diagonal stroke, AA noise,
    optional keyed corners; the dim-art trick (one index shared by two classes at opposite parities) included."""
    rnd = random.Random(seed)
    idx = rnd.sample(range(10, 250), 8)
    bg, st, edge = (idx[0], idx[1]), (idx[2], idx[0] if seed % 3 == 0 else idx[3]), (idx[4], idx[5])
    rows = []
    for r in range(h):
        row = []
        for c in range(w):
            if abs(c - r * w // h) <= max(1, w // 8) or abs((w - 1 - c) - r * w // h) <= max(1, w // 8):
                v = st[r & 1]
            elif c in (0, w - 1):
                v = edge[r & 1]
            else:
                v = bg[r & 1]
            if rnd.random() < 0.06:
                v = rnd.choice(idx[6:])
            if key is not None and (r + c < 3 or (w - 1 - c) + (h - 1 - r) < 2):
                v = key
            row.append(v)
        rows.append(row)
    pal = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(256)]
    if seed % 4 == 1:                                   # a brightness tie in the dominant pair -> lower index
        pal[bg[1]] = pal[bg[0]]
    return rows, pal


SYN = {f"syn{s}_{w}x{h}": _synthetic(s, w, h, 9 if s % 2 else None)
       for s, (w, h) in enumerate([(18, 18), (17, 18), (12, 9), (32, 32), (18, 18), (21, 14), (5, 4), (18, 18)])}


def _arts():
    out = dict(SYN)
    if REAL:
        for k, rows in REAL[0].items():
            out[k] = (rows, REAL[1])
    return out


ARTS = _arts()


# ---------------------------------------------------------------------------------------------- t_ck_draw
@pytest.fixture(scope="module")
def rig():
    return Rig()


def test_yaml_bytes_are_the_assembler_output():
    built = AC.build()
    for n, b in CODE.items():
        assert b == built[n], n


@pytest.mark.parametrize("art", sorted(ARTS))
def test_draw_equals_the_law_every_g_and_phase(rig, art):
    rows, pal = ARTS[art]
    n = 0
    for g in range(17, 41):
        P = SL.stripe_period(g)
        for phase in range(P):
            for x, y in (((3, 2 + (g + phase) % 4),) if g % 2 else ((60, 41),)):
                noise, got, rec = rig.run("t_ck_draw", g=g, rows=rows, key=9, pal=pal, ph0=phase, seed=g * 7 + phase,
                                          args=(DST, 9, x, y, g, 16))
                assert rec[0] != STUB_SD2, "refused a valid draw"
                exp = _expected(noise, g=g, rows=rows, key=9, pal=pal, x=x, y=y, num=g, den=16, phase=phase)
                assert got == exp, (art, g, phase, x, y)
                n += 1
    assert n == sum(SL.stripe_period(g) for g in range(17, 41))


@pytest.mark.parametrize("case", ["clip", "offsets", "ratio", "edges", "key"])
def test_draw_clip_offsets_ratio_edges(rig, case):
    rows, pal = ARTS["real39"] if "real39" in ARTS else ARTS["syn0_18x18"]
    kw = dict(rows=rows, pal=pal)
    runs = {
        "clip": [dict(g=g, clip=c, args=(DST, 9, 10, 12, g, 16)) for g in (18, 22, 25, 40)
                 for c in ((14, 15, 30, 31), (0, 0, 21, 20), (25, 30, PW, PH), (-5, -5, 1000, 1000), (40, 40, 30, 30))],
        "offsets": [dict(g=g, offs=o, args=(DST, 9, 20, 20, g, 16)) for g in (19, 22, 40) for o in ((3, 5), (7, 9))],
        "ratio": [dict(g=g, args=(DST, 9, 5, 5, n_, d_)) for g in (22, 40) for n_, d_ in ((3, 2), (5, 2), (7, 4), (33, 16),
                                                                                      (7, 1))],
        "edges": [dict(g=g, args=(DST, 9, x, y, g, 16)) for g in (22, 40) for x, y in ((-10, -7), (PW - 20, PH - 15),
                                                                                       (-50, 10), (10, PH + 3))],
        "key": [dict(g=g, args=(DST, 0x1FF09, 8, 8, g, 16)) for g in (22, 25)],      # only the key's low byte counts
    }[case]
    for r in runs:
        num, den = r["args"][4], r["args"][5]
        noise, got, rec = rig.run("t_ck_draw", key=9, **kw, **{k: v for k, v in r.items()})
        assert rec[0] != STUB_SD2
        exp = _expected(noise, g=r["g"], rows=rows, key=9, pal=pal, x=r["args"][2], y=r["args"][3], num=num, den=den,
                        phase=0, offs=r.get("offs", (0, 0)), clip=r.get("clip", (0, 0, PW, PH)))
        assert got == exp, (case, r)


@pytest.mark.parametrize("why", ["num_le_den", "g16", "g12", "too_many_texels", "wide_overflow", "one_row",
                                 "no_texels", "no_dest_plane", "zero_den", "period_0", "not_a_checkbox", "ratio_over_14"])
def test_draw_refusals_are_the_native_call_untouched(rig, why):
    rows, pal = ARTS["syn0_18x18"]
    g, args = 22, (DST, 9, 4, 5, 22, 16)
    kw = {"num_le_den": {}, "g16": {}, "g12": {}, "too_many_texels": dict(bw=33, bh=32),
          "wide_overflow": dict(bw=0x40000001, bh=4),          # w*h wraps to 4: the w-alone bound catches it
          "one_row": dict(bh=1), "no_texels": dict(texel_ptr=0), "no_dest_plane": dict(ddata=0), "zero_den": {},
          "period_0": dict(period=0), "not_a_checkbox": dict(spr=OTHER_SPR), "ratio_over_14": {}}[why]
    if why == "num_le_den":
        args = (DST, 9, 4, 5, 16, 16)
    elif why in ("g16", "g12"):
        g = int(why[1:])
    elif why == "zero_den":
        args = (DST, 9, 4, 5, 22, 0)
    elif why == "ratio_over_14":
        args = (DST, 9, 4, 5, 14 * 16 + 1, 16)
    noise, got, rec = rig.run("t_ck_draw", g=g, rows=rows, key=9, pal=pal, args=args, **kw)
    assert rec[0] == STUB_SD2 and rec[1] == kw.get("spr", SPR) and rec[2:8] == list(args)
    assert got == noise


# ---------------------------------------------------------------------------------------------- t_ck_list
@pytest.mark.parametrize("tops", [(0, 0), (25, 0), (13, 0), (64, 0), (73, 0), (117, 0), (0, 59), (-3, 0), (-1, -6),
                                  (410, 225)])
def test_list_adapter_is_checkbox_scale_placement_plus_the_phase(rig, tops):
    for art in [a for a in ("real1", "real20", "real39", "syn4_18x18") if a in ARTS]:
        rows, pal = ARTS[art]
        for g in (17, 18, 19, 21, 22, 24, 25, 30, 33, 40):
            y = 37
            noise, got, rec = rig.run("t_ck_list", g=g, rows=rows, key=9, pal=pal, tops=tops, seed=g,
                                      args=(DST, 9, 4, y, 1, 1))
            phase = SL.checkbox_list_phase(tops[0], tops[1], g)
            assert 0 <= phase < SL.stripe_period(g)
            exp = _expected(noise, g=g, rows=rows, key=9, pal=pal, x=4, y=SL.checkbox_list_y(y, g), num=g, den=16,
                            phase=phase)
            assert got == exp, (art, g, tops)
            assert rig.r32(AC.G_CK_PH) == 0, "phase cell left staged"


def test_list_adapter_y_rewrite_is_thunk_checkbox_scales():
    """checkbox_list_y is the deployed thunk_checkbox_scale's arithmetic (y += (16 - g) sar 1), byte for byte."""
    for g in range(16, 41):
        assert SL.checkbox_list_y(100, g) == 100 + ((16 - g) >> 1)
    assert [SL.checkbox_list_y(0, g) for g in (17, 22, 25, 40)] == [-1, -3, -5, -12]


@pytest.mark.parametrize("g", [12, 15, 16])
def test_list_adapter_g_le_16_is_the_vanilla_call(rig, g):
    rows, pal = ARTS["syn0_18x18"]
    args = (DST, 9, 4, 37, 1, 1)
    noise, got, rec = rig.run("t_ck_list", g=g, rows=rows, key=9, pal=pal, tops=(25, 0), args=args)
    assert rec[0] == STUB_SD2 and rec[1] == SPR and rec[2:8] == list(args) and rec[8] == 0
    assert got == noise


def test_list_adapter_with_no_period_cell_is_the_scaled_engine_call(rig):
    """g > 16 with the period cell unset (never in game: thunk_ensure_scale writes both): no idiv, the engine draws
    at g/16 exactly as thunk_checkbox_scale did."""
    rows, pal = ARTS["syn0_18x18"]
    noise, got, rec = rig.run("t_ck_list", g=22, rows=rows, key=9, pal=pal, tops=(25, 0), period=0,
                              args=(DST, 9, 4, 37, 1, 1))
    assert rec[0] == STUB_SD2 and rec[2:8] == [DST, 9, 4, 37 - 3, 22, 16]


# ---------------------------------------------------------------------------------------------- t_ck_core
def test_core_adapter_draws_the_law_at_phase_0(rig):
    for art in sorted(ARTS):
        rows, pal = ARTS[art]
        for g in (17, 18, 19, 21, 22, 25, 27, 30, 33, 40):
            for x, y in ((10, 21), (11, 50)):
                noise, got, rec = rig.run("t_ck_core", g=g, rows=rows, key=9, pal=pal, ph0=0, args=(DST, 9, x, y),
                                          seed=g + x)
                assert rec[0] not in (STUB_SD2, STUB_CORE), "a vanilla call at g > 16"
                exp = _expected(noise, g=g, rows=rows, key=9, pal=pal, x=x, y=y, num=g, den=16, phase=0)
                assert got == exp, (art, g, x, y)


def test_arrow_art_is_a_scanline_pair():
    lut, n = SL.scanicon_pair_lut(ARROW_ART, 9)
    assert lut == {(0xAE, 0): 0xEE, (0xEE, 1): 0xAE} and n == {(0xAE, 0): 25, (0xEE, 1): 24}
    assert SL.LOBBY_ARROW_SPRITE == ARROW_SPR and ARROW_SPR in SL.SCANICON_SPRITES and ARROW_SPR in AC.SPRITES
    assert set(AC.SPRITES) == set(SL.SCANICON_SPRITES)


def test_core_adapter_draws_the_arrow_by_the_law(rig):
    """The arrow sites reach t_ck_core through thunk_nw_blit_left: at every g 17..40 the arrow sprite is drawn by
    the law (phase 0), never refused into the engine's NN."""
    pal = REAL[1] if REAL else [tuple((i * 37 + k * 11) % 256 for k in range(3)) for i in range(256)]
    for g in range(17, 41):
        for x, y in ((10, 21), (11, 50), (-3, 2), (PW - 6, PH - 9)):
            noise, got, rec = rig.run("t_ck_core", g=g, rows=ARROW_ART, key=9, pal=pal, ph0=0, args=(DST, 9, x, y),
                                      seed=g * 3 + x, spr=ARROW_SPR)
            assert rec[0] not in (STUB_SD2, STUB_CORE), ("the arrow fell to an engine draw", g)
            exp = _expected(noise, g=g, rows=ARROW_ART, key=9, pal=pal, x=x, y=y, num=g, den=16, phase=0)
            assert got == exp, (g, x, y)


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_core_adapter_null_dest_is_the_vanilla_core_call(rig, g):
    """The roster arrow sites pass dest = flag ? canvas : NULL (neg / sbb / and): a NULL dest keeps the vanilla core
    (which returns without drawing) with the args untouched -- never t_ck_draw's Sprite_draw_2 fallback chain."""
    for spr, rows in ((ARROW_SPR, ARROW_ART), (SPR, ARTS["syn0_18x18"][0])):
        noise, got, rec = rig.run("t_ck_core", g=g, rows=rows, key=9, pal=ARTS["syn0_18x18"][1], args=(0, 9, 10, 21),
                                  spr=spr)
        assert rec[0] == STUB_CORE and rec[1] == spr and rec[2:6] == [0, 9, 10, 21]
        assert got == noise


@pytest.mark.parametrize("g", [12, 16])
def test_core_adapter_g_le_16_is_the_vanilla_core_call(rig, g):
    rows, pal = ARTS["syn0_18x18"]
    noise, got, rec = rig.run("t_ck_core", g=g, rows=rows, key=9, pal=pal, args=(DST, 9, 10, 21))
    assert rec[0] == STUB_CORE and rec[1] == SPR and rec[2:6] == [DST, 9, 10, 21]
    assert got == noise


# ---------------------------------------------------------------------------------------------- wiring
def test_sites_point_at_the_adapters_and_the_shared_tail_is_untouched():
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")

    def new_bytes(site):
        i = text.index(f"  - id: {site}\n")              # read_text: universal newlines
        j = text.index("new_bytes:", i)
        return text[j:text.index("\n", j)]
    for s in ("FUN_00405b20.checkbox_scale", "FUN_0060f030.checkbox_scale_1", "FUN_0060f030.checkbox_scale_2"):
        assert "{rel32:t_ck_list}" in new_bytes(s), s
    for s in ("NetWin_draw_options.ckbox0", "NetWin_draw_options.ckboxN"):
        assert "{rel32:t_ck_core}" in new_bytes(s), s
    # the lobby arrows: thunk_nw_blit_left's one call is t_ck_core inside the g/16 bracket (2026-11-07)
    i = text.index("      - id: thunk_nw_blit_left")
    j = text.index('bytes: "', i)
    body = text[j:text.index(chr(10), j)]
    assert body.count("{rel32:") == 1 and "E8 {rel32:t_ck_core}" in body
    assert "A3 18 6D 69 00 C7 05 1C 6D 69 00 10 00 00 00 E8 {rel32:t_ck_core} C7 05 18 6D 69 00 01" in body
    # ... and every site that reaches it (3 roster via _right, 8 settings via _gap) draws the arrow sprite: the
    # instruction before each call is `mov ecx, 0x788038` in the pristine exe
    sites = [int(m, 16) for m in re.findall(r"virtual_addr: (0x[0-9A-Fa-f]+)\n(?:.*\n){0,4}?\s+new_bytes:\s+\"E8 "
                                           r"\{rel32:thunk_nw_blit_(?:right|gap|left)\}\"", text)]
    assert len(sites) == 11, sites
    bak = config.terranx_bak(required=False)
    if bak and pathlib.Path(bak).exists():
        import pefile
        pe = pefile.PE(str(bak), fast_load=True)
        for va in sites:
            assert pe.get_data(va - 5 - 0x400000, 5) == bytes.fromhex("B938807800"), hex(va)
    # thunk_checkbox_scale's other users keep it (jackal file icons through t_fdicon_checker)
    for s in ("FUN_00614c50.icon_file", "FUN_00614c50.icon_drive", "FUN_00614c50.icon_folder"):
        assert "{rel32:t_fdicon_checker}" in new_bytes(s), s
    i = text.index("      - id: thunk_checkbox_scale")
    assert ('"50 B8 10 00 00 00 2B 05 {abs32:g_popup_scale_num} D1 F8 01 44 24 14 A1 {abs32:g_popup_scale_num} 89 44 24'
            ' 18 C7 44 24 1C 10 00 00 00 58 68 {abs32:FUN_005e4b4a} C3"') in text[i:i + 400]


def test_region_and_section_length():
    built = AC.build()
    lo, hi = AC.REGION
    for n, b in built.items():
        assert lo <= AC.SLOTS[n] and AC.SLOTS[n] + len(b) <= AC.SLOTS["g_ck_ph"] <= hi - 4
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    i = text.index("  - id: pcave2")
    m = re.search(r"length: (0x[0-9A-Fa-f]+)", text[i:i + 400])
    assert m and int(m.group(1), 16) >= hi      # the section must still cover this region (later regions grow it)


def test_uimod_longevity_rows_reach_the_same_law():
    """The Longevity Mod Preferences rows are painted by uimod.dll (prefs.cpp CheckContentDraw), not by the CheckList:
    above g = 16 they must call the same t_ck_draw with the row's parent-local top floor-mod P staged in g_ck_ph (the
    law t_ck_list stages), gated on t_ck_draw's presence (inside .pcave2 + its entry bytes): the DLL also runs on the
    pristine exe and on builds without fix 28."""
    import re
    src = (ROOT.parent / "src" / "uimod" / "src" / "prefs.cpp").read_text(encoding="utf-8")

    def const(name):
        m = re.search(r"constexpr uintptr_t " + name + r"\s*=\s*0x([0-9A-Fa-f]+);", src)
        assert m, name
        return int(m.group(1), 16)
    assert const("kVA_CkDraw") == VA["t_ck_draw"]
    assert const("kVA_CkPhase") == AC.PCAVE2 + AC.SLOTS["g_ck_ph"]
    assert const("kVA_StripePeriod") == AC.G_STRIPE_PERIOD
    m = re.search(r"kCkDrawEntry\[\]\s*=\s*\{([^}]*)\}", src)
    entry = bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))
    assert len(entry) >= 8 and CODE["t_ck_draw"].startswith(entry)
    body = src[src.index("void __fastcall CheckContentDraw("):src.index("// The label's y inside our row canvas")]
    assert "if (sc && CkLawPresent())" in body
    assert "((top % P) + P) % P" in body and "+ 0x140)" in body and "+ 0x150)" in body
    assert "(At(kVA_CkDraw))(At(spr), nullptr, buf, key, 0, 0, g, 16)" in body and "*ph = 0;" in body
    for top in range(-9, 60):                       # the C++ expression IS the law's floor modulus
        for g in (17, 22, 40):
            P = SL.stripe_period(g)
            assert ((top % P if top >= 0 else -((-top) % P)) + P) % P == SL.checkbox_list_phase(top, 0, g)


# ---------------------------------------------------------------------------------------------- t_nw_box (F37)
RECT_VA, PRM, EDGE, TILE, TILEPIX = BOXD, BOXD + 0x40, BOXD + 0x100, BOXD + 0x400, BOXD + 0x1000


def _box_run(rig, *, g, pal, rect, edges, tile_rows, clip=(0, 0, PW, PH), seed=0, period=None, have_tile=True):
    """t_nw_box with a recording Buffer_box_sprite stub that draws nothing: the dest starts as noise over a, b and two
    other indices, so the post-pass is checked on every pixel -- the law inside the fill rect and the clip, untouched
    elsewhere -- and the engine box must have been called with the site's own args."""
    uc = rig.uc
    for i, v in enumerate(rect):
        rig.w32(RECT_VA + 4 * i, v)
    for k, off in enumerate((0x10, 0x14, 0x18, 0x1C)):          # top, bottom, left, right edge sprites
        if edges[k] is None:
            rig.w32(PRM + off, 0)
        else:
            sp = EDGE + 0x40 * k
            rig.w32(PRM + off, sp)
            rig.w32(sp + 0x18, edges[k][0])
            rig.w32(sp + 0x1C, edges[k][1])
    th, tw = len(tile_rows), len(tile_rows[0])
    rig.w32(PRM + 0x20, TILE if have_tile else 0)
    uc.mem_write(TILEPIX, bytes(v for r in tile_rows for v in r))
    for off, v in ((0x54, TILEPIX), (0x80, tw), (0x84, -th), (0x4A8, tw)):
        rig.w32(TILE + off, v)
    for off, v in ((0x20, clip[0]), (0x24, clip[1]), (0x28, clip[2]), (0x2C, clip[3]), (0x54, PIX),
                   (0x80, PW), (0x84, -PH), (0x4A8, PW)):
        rig.w32(DST + off, v)
    uc.mem_write(DST + 0xA4, bytes(b for c in pal for b in (c[2], c[1], c[0], 0)))
    rnd = random.Random(seed)
    vals = [tile_rows[0][0], tile_rows[1][0], 7, 200]
    noise = bytes(rnd.choice(vals) for _ in range(PW * PH))
    uc.mem_write(PIX, noise)
    rig.w32(0x668740, g)
    if period is not None:
        rig.w32(0x66879C, period)
    uc.mem_write(REC, b"\xEE" * 36)
    sp = SP0 - 8
    rig.w32(sp, RECT_VA)
    rig.w32(sp + 4, PRM)
    sp -= 4
    rig.w32(sp, RET_SITE)
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_ECX, DST)
    for r, v in SENTINELS.items():
        uc.reg_write(r, v)
    uc.emu_start(VA["t_nw_box"], RET_SITE, timeout=600_000_000)      # us: a hang bound only -- the end marker decides
    assert uc.reg_read(UC_X86_REG_EIP) == RET_SITE, "t_nw_box returned (not cut short)"
    assert uc.reg_read(UC_X86_REG_ESP) == SP0, "RET 8"
    for r, v in SENTINELS.items():
        assert uc.reg_read(r) == v
    rec = [rig.r32(REC + 4 * i) for i in range(4)]
    assert rec == [0xB0, DST, RECT_VA, PRM], "the engine box with the site's own args"
    return noise, bytes(uc.mem_read(PIX, PW * PH))


def _box_expected(noise, *, g, pal, rect, edges, tile_rows, clip=(0, 0, PW, PH)):
    pair = SL.tile_scan_pair(tile_rows)
    if g <= 16 or pair is None:
        return noise
    dims = [(e or (0, 0)) for e in edges]
    x0, y0, x1, y1 = SL.box_fill_rect(rect, dims[2][0], dims[0][1], dims[3][0], dims[1][1])
    x0, y0 = max(x0, clip[0], 0), max(y0, clip[1], 0)
    x1, y1 = min(x1, clip[2], PW), min(y1, clip[3], PH)
    out = bytearray(noise)
    for y in range(y0, y1):
        for x in range(x0, x1):
            out[y * PW + x] = SL.panel_fill_pixel(noise[y * PW + x], y, g, pair[0], pair[1], lambda i: pal[i])
    return bytes(out)


def _tile(a, b, n=24):
    return [[a if r % 2 == 0 else b] * n for r in range(n)]


#: the four lobby fill tiles' pairs (measured: d690 backdrop C6/41, d528 / d618 C4/41, dca8 toggle cells 0x27/0x22)
#: plus a tile whose first row is the dark member
LOBBY_TILES = {"backdrop_c6_41": (0xC6, 0x41), "panel_c4_41": (0xC4, 0x41), "toggle_27_22": (0x27, 0x22),
               "dark_first_41_c4": (0x41, 0xC4)}
PAL_SYN = [((i * 37) % 256, (i * 91) % 256, (i * 53) % 256) for i in range(256)]


@pytest.mark.parametrize("tile", sorted(LOBBY_TILES))
def test_panel_fill_equals_the_law_every_g(rig, tile):
    a, b = LOBBY_TILES[tile]
    for g in range(16, 41):
        for rect in ((9, 49, 120, 77), (4, 3, 40, 37)):
            kw = dict(g=g, pal=PAL_SYN, rect=rect, edges=((6, 6),) * 4, tile_rows=_tile(a, b))
            noise, got = _box_run(rig, seed=g, **kw)
            assert got == _box_expected(noise, **kw), (tile, g, rect)
            if g <= 16:
                assert got == noise


@pytest.mark.parametrize("case", ["clip", "no_edges", "mixed_edges", "no_tile", "solid_tile", "checker_tile",
                                  "short_tile", "period_0", "brightness_tie"])
def test_panel_fill_edges_and_refusals(rig, case):
    pal = list(PAL_SYN)
    kw = dict(g=22, pal=pal, rect=(9, 49, 120, 77), edges=((6, 6),) * 4, tile_rows=_tile(0xC4, 0x41))
    if case == "clip":
        kw["clip"] = (20, 55, 60, 70)
    elif case == "no_edges":
        kw["edges"] = (None, None, None, None)
    elif case == "mixed_edges":
        kw["edges"] = ((3, 5), None, (4, 7), (2, 9))
    elif case == "solid_tile":
        kw["tile_rows"] = [[0xC4] * 24 for _ in range(24)]
    elif case == "checker_tile":
        kw["tile_rows"] = [[(0xC4 if (r + c) % 2 else 0x41) for c in range(24)] for r in range(24)]
    elif case == "short_tile":
        kw["tile_rows"] = _tile(0xC4, 0x41)[:3]
    elif case == "brightness_tie":
        pal[0xC4] = pal[0x41]
    noise, got = _box_run(rig, have_tile=case != "no_tile", period=0 if case == "period_0" else None, **kw)
    if case in ("no_tile", "period_0", "solid_tile", "checker_tile", "short_tile"):
        assert got == noise
    else:
        assert got == _box_expected(noise, **kw) != noise, case
