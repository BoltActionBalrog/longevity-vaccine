"""Unicorn parity for sprite_scale_cap (t_zc_* on the 8 sprite cores' shared reject path).

The whole pristine image is mapped and the ENGINE runs for real -- every capped core (entry, scale table, clipped-table
builders, enlarge / 1:1 paths), Buffer_get_data / Buffer_free_data, _ftol; IntersectRect is the only stub -- with the
SHIPPED bytes (patches.yaml resolved with the real symbol table) of the t_zc_* thunks, thunk_scale_reject_uncache and
the 8 retargeted reject sites:
  - REPLICA == ENGINE: with the qword 4.0 the cores compare against lowered, ratios the native core still draws
    (<= 4.0, exactly 4.0 included) are forced down the reject path; on a NOISY dest (table cores read it), with clips
    cutting blocks mid-run, every dest byte must equal what the native core draws at the real cap.  This is what
    makes crossing 4.0 seamless for unit flags, base icons and the terrain overlay sprites: above the cap the same
    arithmetic keeps going.
  - LAW == ENGINE at <= 4.0 (scaling_laws.engine_enlarge_blit with the keyed / mono / table rules) and THUNK == LAW
    above it, at the map's (zoom+16)/16 up to 4K's / 8K's deepest PRACX zoom.
  - the core returns like a vanilla reject (eax 0, its own RET, callee-saved registers, x87 balanced), the dest lock is
    released, SCALE_NUM_G/DEN_G restored, the ratio cache invalidated; Sprite_draw_dest_unk1 still draws nothing.
"""
from __future__ import annotations

import pathlib
import random
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
unicorn = pytest.importorskip("unicorn", reason="unicorn absent -- asm parity unverified")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP, UC_X86_REG_FPSW,
)
import apply_patches as ap  # noqa: E402
import assemble_zoom_cap as A  # noqa: E402
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

IMAGE = 0x00400000
STACK = 0x00200000
SRC = 0x00300000            # source pixels (with padding columns and rows past the sprite: the engine reads them)
TABLE = 0x00380000          # 64K blend table
DESTPX = 0x01000000         # dest pixels
DEST = 0x01600000           # dest Buffer struct
SPR = 0x01610000            # source Sprite
STUBS = 0x01620000
INTERSECT = STUBS
RET_SENTINEL = STUBS + 0x10
IAT_INTERSECT = 0x669338
SCALE_MAX = 0x66FDC8
CACHE = 0x696D20

MONO, KEYED, DDEST, DUNK1, DSRC, DUNK2, DTABLE, D4 = (c[0] for c in A.CORES)
RET_IMM = {MONO: 0x14, KEYED: 0x10, DDEST: 0x14, DUNK1: 0x10, DSRC: 0x14, DUNK2: 0x14, DTABLE: 0x14, D4: 0x14}
DRAWING = [MONO, KEYED, DDEST, DSRC, DTABLE]
EXCLUDED = [DUNK1, DUNK2, D4]


def _shipped():
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    cave_bytes = {}
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] in A.OFFS or c["id"] == "thunk_scale_reject_uncache":
                base = cave["virtual_addr"]; base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]; off = int(off, 16) if isinstance(off, str) else off
                cave_bytes[c["id"]] = (base + off, ap.ByteTemplate(c["bytes"]).resolve(base + off, symtab))
    sites = {}
    for s in doc["sites"]:
        v = s["virtual_addr"]; v = int(v, 16) if isinstance(v, str) else v
        if v in {c[2] for c in A.CORES}:
            sites[v] = ap.ByteTemplate(s["new_bytes"]).resolve(v, symtab)
    return cave_bytes, sites, symtab


SHIPPED, SITES, SYMTAB = _shipped()


@pytest.fixture(scope="module")
def image():
    import pefile
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
    return [(IMAGE + s.VirtualAddress, s.Misc_VirtualSize, s.get_data()) for s in pe.sections]


def test_yaml_bytes_match_the_assembler():
    for n, _ in A.THUNKS:
        va, b = SHIPPED[n]
        assert va == A.va(n) and SYMTAB[n] == A.va(n)
        assert b == A.assemble(n), n
    assert SYMTAB["thunk_scale_reject_uncache"] == A.UNCACHE
    assert len(SITES) == 8
    for start, _, site, _ in A.CORES:
        assert SITES[site][0] == 0xE8
        assert (site + 5 + struct.unpack("<i", SITES[site][1:5])[0]) & 0xFFFFFFFF == A.va("t_zc_reject")


class Emu:
    def __init__(self, image, dw=320, dh=200, clip=None, seed=5):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(IMAGE, 0x60C000)
        for va, vs, data in image:
            uc.mem_write(va, data[:max(vs, 0)] if len(data) > vs else data)
        uc.mem_map(A.PCAVE2, 0x31000)
        for n, (va, b) in SHIPPED.items():
            uc.mem_write(va, b)
        for va, b in SITES.items():
            uc.mem_write(va, b)
        for page, size in ((STACK, 0x10000), (SRC, 0x80000), (TABLE, 0x10000), (DEST, 0x1000), (SPR, 0x1000),
                           (STUBS, 0x1000), (DESTPX, 0x600000)):
            uc.mem_map(page, size)
        uc.mem_write(IAT_INTERSECT, struct.pack("<I", INTERSECT))
        uc.mem_write(INTERSECT, b"\xC2\x0C\x00")
        uc.mem_write(RET_SENTINEL, b"\xF4")
        rnd = random.Random(seed)
        self.table = bytes(rnd.randrange(256) for _ in range(0x10000))
        uc.mem_write(TABLE, self.table)

        def on_intersect(u, addr, size, _):
            esp = u.reg_read(UC_X86_REG_ESP)
            out, a, b = struct.unpack("<3I", u.mem_read(esp + 4, 12))
            ra = struct.unpack("<4i", u.mem_read(a, 16)); rb = struct.unpack("<4i", u.mem_read(b, 16))
            r = (max(ra[0], rb[0]), max(ra[1], rb[1]), min(ra[2], rb[2]), min(ra[3], rb[3]))
            ok = r[0] < r[2] and r[1] < r[3]
            u.mem_write(out, struct.pack("<4i", *(r if ok else (0, 0, 0, 0))))
            u.reg_write(UC_X86_REG_EAX, 1 if ok else 0)
        uc.hook_add(UC_HOOK_CODE, on_intersect, begin=INTERSECT, end=INTERSECT)
        self.set_dest(dw, dh, clip or (0, 0, dw, dh), seed)

    def set_dest(self, w, h, clip, seed=5):
        rnd = random.Random(seed * 7 + 1)
        self.dw, self.dh, self.pitch = w, h, (w + 3) & ~3
        self.dest0 = bytes(rnd.randrange(256) for _ in range(self.pitch * h))   # NOISY background
        self.uc.mem_write(DESTPX, self.dest0)
        self.uc.mem_write(DEST, bytes(0x600))
        self.uc.mem_write(DEST + 0x20, struct.pack("<4i", *clip))
        self.uc.mem_write(DEST + 0x54, struct.pack("<I", DESTPX))
        self.uc.mem_write(DEST + 0x80, struct.pack("<2i", w, -h))
        self.uc.mem_write(DEST + 0x4A8, struct.pack("<i", self.pitch))
        self.clip = clip

    def set_sprite(self, w, h, pitch, off=(0, 0), seed=1, key=0xFF):
        rnd = random.Random(seed)
        px = bytes((key & 0xFF if rnd.random() < 0.3 else rnd.randrange(256)) for _ in range(pitch * (h + 4)))
        self.uc.mem_write(SRC, px)
        self.uc.mem_write(SPR, bytes(0x40))
        self.uc.mem_write(SPR + 4, struct.pack("<I", SRC))
        self.uc.mem_write(SPR + 0xC, struct.pack("<3i", pitch, w, h))
        self.uc.mem_write(SPR + 0x20, struct.pack("<2i", *off))
        self.src, self.spitch, self.sw, self.sh, self.off = px, pitch, w, h, off
        return px

    def dest(self) -> bytes:
        return bytes(self.uc.mem_read(DESTPX, self.pitch * self.dh))

    def run(self, core, num, den, key, x, y, extra, cap=4.0):
        uc = self.uc
        uc.mem_write(DESTPX, self.dest0)
        uc.mem_write(DEST + 0x50, bytes(4)); uc.mem_write(DEST + 0x6C, bytes(4))
        uc.mem_write(SCALE_MAX, struct.pack("<d", cap))
        uc.mem_write(A.SCALE_NUM, struct.pack("<2i", num, den))
        uc.mem_write(CACHE, struct.pack("<2i", -1, -1))
        esp = STACK + 0x8000
        args = [DEST, key, x, y, extra]
        uc.mem_write(esp, struct.pack("<I", RET_SENTINEL) + b"".join(struct.pack("<I", a & 0xFFFFFFFF) for a in args))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_ECX, SPR)
        uc.reg_write(UC_X86_REG_EBX, 0xB0B0B0B0); uc.reg_write(UC_X86_REG_ESI, 0x51515151)
        uc.reg_write(UC_X86_REG_EDI, 0xD1D1D1D1); uc.reg_write(UC_X86_REG_EBP, 0xEBEBEBEB)
        top0 = (uc.reg_read(UC_X86_REG_FPSW) >> 11) & 7
        try:
            uc.emu_start(core, 0, timeout=0, count=200_000_000)
        except unicorn.UcError as e:
            raise AssertionError(f"emulation fault {e} at {uc.reg_read(UC_X86_REG_EIP):#x}")
        assert uc.reg_read(UC_X86_REG_EIP) in (RET_SENTINEL, RET_SENTINEL + 1), hex(uc.reg_read(UC_X86_REG_EIP))
        assert uc.reg_read(UC_X86_REG_ESP) == esp + 4 + RET_IMM[core]
        assert (uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI),
                uc.reg_read(UC_X86_REG_EBP)) == (0xB0B0B0B0, 0x51515151, 0xD1D1D1D1, 0xEBEBEBEB)
        assert (uc.reg_read(UC_X86_REG_FPSW) >> 11) & 7 == top0
        assert struct.unpack("<2i", uc.mem_read(A.SCALE_NUM, 8)) == (num, den)
        assert struct.unpack("<I", uc.mem_read(DEST + 0x6C, 4))[0] == 0          # every lock released
        self.eax = uc.reg_read(UC_X86_REG_EAX)
        return self.dest()


def extra_for(core, colour=0x37):
    return colour if core == MONO else TABLE


def law(e: Emu, core, num, den, key, x, y, colour=0x37):
    d = bytearray(e.dest0)
    rule = {MONO: lambda s, b: colour, KEYED: lambda s, b: s, DTABLE: lambda s, b: e.table[(s << 8) | b]}[core]
    rect = SL.effect_blit_rect(x, y, e.off[0], e.off[1], e.sw, e.sh, num, den)
    SL.engine_enlarge_blit(d, e.pitch, e.src, e.spitch, key, rule, rect, e.clip, num, den)
    return bytes(d)


AT_OR_BELOW = [(64, 16), (61, 16), (50, 16), (35, 9), (17, 16), (33, 16), (63, 32), (7, 2)]
CLIPS = [None, (13, 7, 301, 190), (40, 33, 97, 61)]


@pytest.mark.parametrize("core", DRAWING)
@pytest.mark.parametrize("num,den", AT_OR_BELOW)
@pytest.mark.parametrize("ci", range(len(CLIPS)))
def test_replica_equals_the_native_core_at_or_below_the_cap(image, core, num, den, ci):
    assert not SL.engine_scale_rejects(num, den)
    e = Emu(image, clip=CLIPS[ci], seed=num + ci)
    w, h, pitch = 23 + (num % 5), 19 + (den % 7), 32
    e.set_sprite(w, h, pitch, off=(num % 4, -(den % 3)), seed=num * 31 + den, key=0xFF)
    x, y = 31 - ci * 9, 22 - ci * 13
    native = e.run(core, num, den, 0xFF, x, y, extra_for(core), cap=4.0)
    assert native != e.dest0 or ci == 2, "the native core drew nothing (test setup)"
    forced = e.run(core, num, den, 0xFF, x, y, extra_for(core), cap=0.5)
    assert e.eax == 0
    assert forced == native


@pytest.mark.parametrize("core", [MONO, KEYED, DTABLE])
@pytest.mark.parametrize("num,den", AT_OR_BELOW[:5])
def test_law_equals_the_native_core_at_or_below_the_cap(image, core, num, den):
    e = Emu(image, clip=(9, 5, 290, 180), seed=num)
    e.set_sprite(29, 21, 36, off=(2, 1), seed=num + den, key=0x55)
    native = e.run(core, num, den, 0x55, 17, 11, extra_for(core), cap=4.0)
    assert native == law(e, core, num, den, 0x55, 17, 11)


def map_zooms():
    zs = {49, 50, 57, 64, SL.pracx_max_zoom(3440, 1440), SL.pracx_max_zoom(3840, 2160), SL.pracx_max_zoom(7680, 4320)}
    return sorted(zs)


@pytest.mark.parametrize("core", [MONO, KEYED, DTABLE])
@pytest.mark.parametrize("zoom", map_zooms())
@pytest.mark.parametrize("ci", range(len(CLIPS)))
def test_over_cap_map_sprites_follow_the_law(image, core, zoom, ci):
    num, den = SL.map_sprite_scale(zoom)
    assert SL.engine_scale_rejects(num, den)
    e = Emu(image, dw=640, dh=400, clip=CLIPS[ci] and (CLIPS[ci][0], CLIPS[ci][1], CLIPS[ci][2] * 2, CLIPS[ci][3] * 2),
            seed=zoom)
    e.set_sprite(23, 30, 24, off=(-3, 2), seed=zoom * 3 + ci, key=0)        # a unit flag: 23x30
    x, y = 41 - 30 * ci, 17 - 20 * ci
    got = e.run(core, num, den, 0, x, y, extra_for(core), cap=4.0)
    assert e.eax == 0
    assert got == law(e, core, num, den, 0, x, y)
    assert got != e.dest0 or ci == 2


def test_over_cap_crosses_4_seamlessly(image):
    """zoom 48 (ratio exactly 4.0, native) and zoom 49 (4.0625, replica) of the same flag differ only by the one
    extra dest column/row the larger ratio covers -- the replica is the same arithmetic one step further."""
    e = Emu(image, dw=200, dh=200, seed=3)
    e.set_sprite(23, 30, 24, seed=9, key=0)
    a = e.run(KEYED, 64, 16, 0, 10, 10, 0)
    b = e.run(KEYED, 65, 16, 0, 10, 10, 0)
    assert a == law(e, KEYED, 64, 16, 0, 10, 10) and b == law(e, KEYED, 65, 16, 0, 10, 10)
    assert b != e.dest0


def test_excluded_cores_keep_the_vanilla_reject(image):
    e = Emu(image, seed=4)
    e.set_sprite(20, 20, 20, seed=4)
    # Sprite_draw_dest_unk1 (dest, x, y, table): no key arg
    assert e.run(DUNK1, 88, 16, 10, 10, TABLE, 0) == e.dest0 and e.eax == 0
    for core in (DUNK2, D4):
        assert e.run(core, 88, 16, 0xFF, 10, 10, TABLE) == e.dest0 and e.eax == 0


@pytest.mark.parametrize("core", [DUNK2, D4])
def test_excluded_cores_differ_from_their_1to1_path(image, core):
    """Why Sprite_draw_dest_unk2_2 / Sprite_draw_4 are excluded: their enlarge path's block value is NOT their 1:1
    rule applied at the block's top-left (replica != native at <= 4.0).  Measured with the replica forced on them by
    patching the exclusion compares out of a copy of t_zc_reject."""
    e = Emu(image, seed=12)
    e.set_sprite(24, 21, 32, seed=12 * 31, key=0xFF)
    native = e.run(core, 64, 16, 0xFF, 31, 22, TABLE, cap=4.0)
    b = bytearray(SHIPPED["t_zc_reject"][1])
    for ex in A.EXCLUDED:
        i = bytes(b).find(b"=" + struct.pack("<I", ex))
        assert i > 0
        b[i + 1:i + 5] = struct.pack("<I", 0x12345678)
    e.uc.mem_write(A.va("t_zc_reject"), bytes(b))
    forced = e.run(core, 64, 16, 0xFF, 31, 22, TABLE, cap=0.5)
    assert forced != native


def test_cache_invalidated_and_nothing_left_locked(image):
    e = Emu(image, seed=6)
    e.set_sprite(20, 20, 20, seed=6)
    e.run(DTABLE, 88, 16, 0xFF, 5, 5, TABLE)
    assert struct.unpack("<i", e.uc.mem_read(CACHE, 4))[0] == -1
    assert struct.unpack("<I", e.uc.mem_read(DEST + 0x50, 4))[0] == 0


def test_offscreen_and_negative_den_draw_nothing(image):
    e = Emu(image, seed=8)
    e.set_sprite(20, 20, 20, seed=8)
    for x, y in ((-500, 10), (10, -500), (900, 10), (10, 900)):
        assert e.run(KEYED, 88, 16, 0xFF, x, y, 0) == e.dest0
    assert e.run(KEYED, -88, -16, 0xFF, 10, 10, 0) == e.dest0          # f = 5.5 but den < 0: vanilla reject


def test_wide_clip_row_buffer_crosses_pages(image):
    """A crop wider than a 4K page (8K map strip): the stack row buffer is pushed a dword at a time."""
    e = Emu(image, dw=7680, dh=40, seed=10)
    e.set_sprite(400, 4, 400, seed=10, key=0xFF)
    num, den = SL.map_sprite_scale(SL.pracx_max_zoom(7680, 4320))
    got = e.run(KEYED, num, den, 0xFF, 0, 0, 0)
    assert got == law(e, KEYED, num, den, 0xFF, 0, 0)
