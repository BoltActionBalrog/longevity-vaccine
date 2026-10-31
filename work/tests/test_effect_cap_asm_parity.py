"""Unicorn parity for the effect_scale_cap thunks (t_pb_draw / t_tb_draw + t_tb_gen / t_tb_skip / t_tb_axis).

The whole pristine image is mapped and the ENGINE runs for real (Sprite_draw_table and its run-table / clipped-table
builders, Buffer_get_data / Buffer_free_data, _ftol; IntersectRect is the only stub), next to the SHIPPED thunk bytes
(patches.yaml, resolved with the real symbol table):
  - REPLICA == ENGINE: with the gate constant lowered (the qword 4.0 the thunk compares against), the over-cap arm is
    forced at ratios the native core still draws (<= 4.0: 3.75, exactly 4.0, ...), on a NOISY dest (the blend reads
    the dest), with clips cutting runs mid-block -- every dest byte must equal the native core's.  This is what makes
    crossing 4.0 seamless: above the cap the same arithmetic simply keeps going (row runs > 4).
  - LAW == ENGINE at <= 4.0, and THUNK == LAW above it (scaling_laws.effect_blit_engine), up to 4K's / 8K's deepest
    PRACX zoom for the Planet Buster cloud and the combat explosions.
  - native arm: at or below 4.0 (ratio exactly 4.0 included), num == den, den <= 0, a null sprite or dest, a surface
    Buffer -> the native entry with the stack, ecx, callee-saved registers and the x87 stack exactly as the site left
    them.
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
import assemble_effect_cap as A  # noqa: E402
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

IMAGE = 0x00400000
STACK = 0x00200000
SRC = 0x00300000            # source pixels
DESTPX = 0x01000000         # dest pixels
TABLE = 0x00380000          # 64K blend table
DEST = 0x01600000           # dest Buffer struct
SPR = 0x01610000            # source Sprite (t_tb) / Buffer (t_pb) struct
STUBS = 0x01620000          # IntersectRect stub + return sentinel
RET_SENTINEL = STUBS + 0x10
INTERSECT = STUBS
IAT_INTERSECT = 0x669338


def _shipped():
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    out = {}
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] in A.OFFS:
                base = cave["virtual_addr"]; base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]; off = int(off, 16) if isinstance(off, str) else off
                out[c["id"]] = (base + off, ap.ByteTemplate(c["bytes"]).resolve(base + off, symtab))
    return out, symtab


SHIPPED, SYMTAB = _shipped()


@pytest.fixture(scope="module")
def image():
    import pefile
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
    return [(IMAGE + s.VirtualAddress, s.Misc_VirtualSize, s.get_data()) for s in pe.sections]


def test_yaml_bytes_match_the_assembler():
    for n, _ in A.THUNKS:
        va, b = SHIPPED[n]
        assert va == A.va(n)
        assert b == A.assemble(n), n
    for n in A.CELLS:
        assert SYMTAB[n] == A.va(n)


class Emu:
    """The pristine process image + the pcave2 thunks; the engine runs for real."""

    def __init__(self, image, dw=320, dh=200, clip=None, cap=4.0, seed=5):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(IMAGE, 0x60C000)
        for va, vs, data in image:
            uc.mem_write(va, data[:max(vs, 0)] if len(data) > vs else data)
        uc.mem_map(A.PCAVE2, 0x31000)
        for n, (va, b) in SHIPPED.items():
            uc.mem_write(va, b)
        for page, size in ((STACK, 0x10000), (SRC, 0x80000), (TABLE, 0x10000), (DEST, 0x1000), (SPR, 0x1000),
                           (STUBS, 0x1000), (DESTPX, 0x400000)):
            uc.mem_map(page, size)
        uc.mem_write(A.SCALE_MAX, struct.pack("<d", cap))
        uc.mem_write(IAT_INTERSECT, struct.pack("<I", INTERSECT))
        uc.mem_write(INTERSECT, b"\xC2\x0C\x00")
        uc.mem_write(RET_SENTINEL, b"\xF4")
        rnd = random.Random(seed)
        self.table = bytes(rnd.randrange(256) for _ in range(0x10000))
        uc.mem_write(TABLE, self.table)
        self.stop_at = set()
        self.stopped = None

        def on_intersect(u, addr, size, _):
            esp = u.reg_read(UC_X86_REG_ESP)
            out, a, b = struct.unpack("<3I", u.mem_read(esp + 4, 12))
            ra = struct.unpack("<4i", u.mem_read(a, 16)); rb = struct.unpack("<4i", u.mem_read(b, 16))
            r = (max(ra[0], rb[0]), max(ra[1], rb[1]), min(ra[2], rb[2]), min(ra[3], rb[3]))
            ok = r[0] < r[2] and r[1] < r[3]
            u.mem_write(out, struct.pack("<4i", *(r if ok else (0, 0, 0, 0))))
            u.reg_write(UC_X86_REG_EAX, 1 if ok else 0)
        uc.hook_add(UC_HOOK_CODE, on_intersect, begin=INTERSECT, end=INTERSECT)

        def on_native(u, addr, size, _):
            if addr in self.stop_at:
                self.stopped = addr
                u.emu_stop()
        uc.hook_add(UC_HOOK_CODE, on_native, begin=A.BUFFER_DRAW_TABLE, end=A.BUFFER_DRAW_TABLE)
        uc.hook_add(UC_HOOK_CODE, on_native, begin=A.SPRITE_DRAW_TABLE, end=A.SPRITE_DRAW_TABLE)
        self.set_dest(dw, dh, clip or (0, 0, dw, dh), seed)

    def set_dest(self, w, h, clip, seed=5, data=DESTPX):
        rnd = random.Random(seed * 7 + 1)
        self.dw, self.dh, self.pitch = w, h, (w + 3) & ~3
        self.dest0 = bytes(rnd.randrange(256) for _ in range(self.pitch * h))   # NOISY background
        self.uc.mem_write(DESTPX, self.dest0)
        self.uc.mem_write(DEST, bytes(0x600))
        self.uc.mem_write(DEST + 0x20, struct.pack("<4i", *clip))
        self.uc.mem_write(DEST + 0x54, struct.pack("<I", data))
        self.uc.mem_write(DEST + 0x80, struct.pack("<2i", w, -h))
        self.uc.mem_write(DEST + 0x4A8, struct.pack("<i", self.pitch))
        self.clip = clip

    def reset_dest(self):
        self.uc.mem_write(DESTPX, self.dest0)

    def dest(self) -> bytes:
        return bytes(self.uc.mem_read(DESTPX, self.pitch * self.dh))

    def scale(self):
        return struct.unpack("<2i", self.uc.mem_read(A.SCALE_NUM, 8))

    def set_scale(self, num, den):
        self.uc.mem_write(A.SCALE_NUM, struct.pack("<2i", num, den))

    def run(self, entry: int, ecx: int, args: list[int]):
        uc = self.uc
        esp = STACK + 0x8000
        uc.mem_write(esp, struct.pack("<I", RET_SENTINEL))
        for i, a in enumerate(args):
            uc.mem_write(esp + 4 + 4 * i, struct.pack("<I", a & 0xFFFFFFFF))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_ECX, ecx)
        uc.reg_write(UC_X86_REG_EBX, 0xB0B0B0B0); uc.reg_write(UC_X86_REG_ESI, 0x51515151)
        uc.reg_write(UC_X86_REG_EDI, 0xD1D1D1D1); uc.reg_write(UC_X86_REG_EBP, 0xEBEBEBEB)
        self.esp0, self.args = esp, list(args)
        self.top0 = (uc.reg_read(UC_X86_REG_FPSW) >> 11) & 7
        self.stopped = None
        try:
            uc.emu_start(entry, RET_SENTINEL, timeout=0, count=500_000_000)
        except unicorn.UcError as e:            # noqa: F841
            pass
        self.eip = uc.reg_read(UC_X86_REG_EIP)

    def returned(self, ret):
        u = self.uc
        return (self.stopped is None and self.eip == RET_SENTINEL and u.reg_read(UC_X86_REG_ESP) == self.esp0 + 4 + ret)

    def regs_preserved(self):
        u = self.uc
        if (u.reg_read(UC_X86_REG_FPSW) >> 11) & 7 != self.top0:      # x87 stack balanced
            return False
        return ((u.reg_read(UC_X86_REG_EBX), u.reg_read(UC_X86_REG_ESI), u.reg_read(UC_X86_REG_EDI),
                 u.reg_read(UC_X86_REG_EBP)) == (0xB0B0B0B0, 0x51515151, 0xD1D1D1D1, 0xEBEBEBEB))

    def stack_untouched(self):
        u = self.uc
        if u.reg_read(UC_X86_REG_ESP) != self.esp0:
            return False
        got = struct.unpack(f"<{1 + len(self.args)}I", u.mem_read(self.esp0, 4 * (1 + len(self.args))))
        return list(got) == [RET_SENTINEL] + [a & 0xFFFFFFFF for a in self.args]

    # sources
    def sprite(self, w, h, pitch, off=(0, 0), seed=1, data=SRC):
        rnd = random.Random(seed)
        px = bytes((0xFF if rnd.random() < 0.3 else rnd.randrange(15)) for _ in range(pitch * (h + 2)))
        self.uc.mem_write(SRC, px)
        self.uc.mem_write(SPR, bytes(0x30))
        self.uc.mem_write(SPR + 4, struct.pack("<I", data))
        self.uc.mem_write(SPR + 0xC, struct.pack("<3i", pitch, w, h))
        self.uc.mem_write(SPR + 0x18, struct.pack("<2i", w, h))
        self.uc.mem_write(SPR + 0x20, struct.pack("<2i", *off))
        return px

    def buffer(self, w, h, pitch, seed=2, surface=0, data=SRC, px=None):
        rnd = random.Random(seed)
        if px is None:
            px = bytes((0xFF if rnd.random() < 0.4 else rnd.randrange(15)) for _ in range(pitch * (h + 2)))
        self.uc.mem_write(SRC, px)
        self.uc.mem_write(SPR, bytes(0x600))
        self.uc.mem_write(SPR + 0x54, struct.pack("<I", data))
        self.uc.mem_write(SPR + 0x58, struct.pack("<I", surface))
        self.uc.mem_write(SPR + 0x80, struct.pack("<2i", w, -h))
        self.uc.mem_write(SPR + 0x4A8, struct.pack("<i", pitch))
        return px

    def law(self, px, pitch, w, h, off, x, y, num, den, key):
        d = bytearray(self.dest0)
        rect = SL.effect_blit_rect(x, y, off[0], off[1], w, h, num, den)
        SL.effect_blit_engine(d, self.pitch, px, pitch, key, self.table, rect, self.clip, num, den)
        return bytes(d)


def pracx_max_zoom(screen_w: int, screen_h: int) -> int:
    """PRACX ZoomInit (refs/pracx/shared/pracx.cpp): the deepest zoom factor = the first even z whose tile
    (i*8 x i*4, i = (50*(z+16)/16 + 1)/4) leaves <= 6 tiles across or <= 3 down the map area (H - 213)."""
    z = 0
    while True:
        z += 2
        i = (50 * (z + 16) // 16 + 1) // 4
        if not (screen_w // max(i * 8, 1) > 6 and (screen_h - 213) // max(i * 4, 1) > 3):
            return z


def test_pracx_max_zoom_reaches_the_cap():
    assert pracx_max_zoom(3840, 2160) == 72 and pracx_max_zoom(1920, 1080) == 30
    assert pracx_max_zoom(1600, 1200) == 22 and pracx_max_zoom(1024, 768) == 8
    for w, h in ((1024, 768), (1600, 1200), (1920, 1080), (3840, 2160)):
        assert SL.engine_scale_rejects(*SL.buster_scale(pracx_max_zoom(w, h), 4)) == (w >= 1280)
    assert not SL.engine_scale_rejects(pracx_max_zoom(2560, 1440) + 16, 16)
    assert SL.engine_scale_rejects(pracx_max_zoom(3440, 1440) + 16, 16)


# ---- REPLICA == ENGINE at <= 4.0 (the seam) ---------------------------------------------------------

SEAM = [(60, 16), (64, 16), (128, 32), (120, 32), (63, 16), (40, 16), (48, 16), (49, 16), (17, 16)]
CLIPS = [(0, 0, 320, 200), (7, 5, 301, 193), (33, 61, 140, 150)]


@pytest.mark.parametrize("num,den", SEAM)
@pytest.mark.parametrize("clip", CLIPS)
def test_replica_equals_the_native_core_sprite(image, num, den, clip):
    """Sprite path (combat explosions): native Sprite_draw_table_scaled vs t_tb_draw's over-cap arm forced at the
    same ratio; noisy dest, blit offsets, clip edges cutting runs.  Also the law against the native output."""
    w, h, pitch, off = 37, 29, 40, (3, 2)
    for x, y in ((-13, -9), (41, 17), (250, 150)):
        e = Emu(image, clip=clip, seed=num + x)
        px = e.sprite(w, h, pitch, off, seed=den + y)
        e.set_scale(16, 16)
        e.run(A.SPRITE_DRAW_TABLE_SCALED, SPR, [DEST, 0xFF, x, y, num, den, TABLE])
        assert e.returned(0x1C), "native core did not return"
        native = e.dest()
        assert native != e.dest0 or SL.effect_blit_clip(SL.effect_blit_rect(x, y, *off, w, h, num, den), clip) is None
        assert e.law(px, pitch, w, h, off, x, y, num, den, 0xFF) == native, "law != engine"
        e.reset_dest()
        e.uc.mem_write(A.SCALE_MAX, struct.pack("<d", 0.5))          # force the over-cap arm
        e.set_scale(num, den)
        e.run(A.va("t_tb_draw"), SPR, [DEST, 0xFF, x, y, TABLE])
        assert e.returned(0x14) and e.regs_preserved()
        assert e.uc.reg_read(UC_X86_REG_EAX) == 0
        assert e.dest() == native, f"replica != engine at {num}/{den} clip {clip} at ({x},{y})"
        assert e.scale() == (num, den)
        assert struct.unpack("<i", e.uc.mem_read(DEST + 0x6C, 4))[0] == 0     # lock refcount balanced


@pytest.mark.parametrize("num,den", [(120, 32), (128, 32), (96, 32)])
def test_replica_equals_the_native_core_buffer(image, num, den):
    """Buffer path (the Planet Buster cloud, 300x248): native Buffer_draw_table vs t_pb_draw forced."""
    e = Emu(image, dw=420, dh=300, clip=(3, 4, 410, 290))
    px = e.buffer(300, 248, 300, seed=num)
    for x, y, key in ((-150, -120, 0xFF), (60, 30, 0xFF), (100, 80, -1)):
        e.reset_dest()
        e.uc.mem_write(A.SCALE_MAX, struct.pack("<d", 4.0))
        e.set_scale(77, 16)
        e.run(A.BUFFER_DRAW_TABLE, SPR, [DEST, key, x, y, num, den, TABLE])
        assert e.returned(0x1C)
        native = e.dest()
        e.reset_dest()
        e.uc.mem_write(A.SCALE_MAX, struct.pack("<d", 0.5))
        e.run(A.va("t_pb_draw"), SPR, [DEST, key, x, y, num, den, TABLE])
        assert e.returned(0x1C) and e.regs_preserved()
        assert e.dest() == native, f"replica != engine at {num}/{den} ({x},{y}) key {key}"
        assert e.scale() == (77, 16)


# ---- native arm: bit-identical to vanilla ----------------------------------------------------------

@pytest.mark.parametrize("num,den", [(16, 16), (40, 16), (64, 16), (1, 1), (128, 32), (3, 4), (88, 0), (-88, -16)])
def test_tb_native_arm_untouched(image, num, den):
    e = Emu(image)
    e.stop_at = {A.SPRITE_DRAW_TABLE}
    e.set_scale(num, den)
    e.sprite(40, 30, 40)
    e.run(A.va("t_tb_draw"), SPR, [DEST, 0xFF, 100, 50, TABLE])
    assert e.stopped == A.SPRITE_DRAW_TABLE and e.stack_untouched() and e.regs_preserved()
    assert e.uc.reg_read(UC_X86_REG_ECX) == SPR and e.scale() == (num, den) and e.dest() == e.dest0


def test_tb_native_arm_null_sprite_and_dest(image):
    e = Emu(image)
    e.stop_at = {A.SPRITE_DRAW_TABLE}
    e.set_scale(88, 16)
    e.sprite(40, 30, 40, data=0)
    e.run(A.va("t_tb_draw"), SPR, [DEST, 0xFF, 0, 0, TABLE])
    assert e.stopped == A.SPRITE_DRAW_TABLE and e.stack_untouched() and e.regs_preserved()
    e.sprite(40, 30, 40)
    e.run(A.va("t_tb_draw"), SPR, [0, 0xFF, 0, 0, TABLE])
    assert e.stopped == A.SPRITE_DRAW_TABLE and e.stack_untouched() and e.regs_preserved()


@pytest.mark.parametrize("num,den", [(128, 32), (96, 32), (64, 32), (32, 32), (130, 33)])
def test_pb_native_arm_untouched(image, num, den):
    """128/32 = the Fusion cloud at zoom 16: ratio EXACTLY 4.0 -> the engine accepts, so native."""
    assert not SL.engine_scale_rejects(num, den)
    e = Emu(image)
    e.stop_at = {A.BUFFER_DRAW_TABLE}
    e.set_scale(17, 16)
    e.buffer(300, 248, 300)
    e.run(A.va("t_pb_draw"), SPR, [DEST, 0xFF, 10, 20, num, den, TABLE])
    assert e.stopped == A.BUFFER_DRAW_TABLE and e.stack_untouched() and e.regs_preserved()
    assert e.scale() == (17, 16) and e.dest() == e.dest0


def test_pb_native_arm_surface_buffer(image):
    e = Emu(image)
    e.stop_at = {A.BUFFER_DRAW_TABLE}
    e.buffer(300, 248, 300, surface=0x1234)
    e.run(A.va("t_pb_draw"), SPR, [DEST, 0xFF, 10, 20, 440, 32, TABLE])
    assert e.stopped == A.BUFFER_DRAW_TABLE and e.stack_untouched()


def test_dest_lock_failure_returns_3(image):
    e = Emu(image)
    e.set_dest(320, 200, (0, 0, 320, 200), data=0)       # Buffer_get_data -> 0
    e.set_scale(88, 16)
    e.sprite(40, 30, 40)
    e.run(A.va("t_tb_draw"), SPR, [DEST, 0xFF, 0, 0, TABLE])
    assert e.returned(0x14) and e.regs_preserved() and e.uc.reg_read(UC_X86_REG_EAX) == 3


# ---- over-cap arm: THUNK == LAW --------------------------------------------------------------------

@pytest.mark.parametrize("zoom", [49, 52, 64, 72, 102, 162])
@pytest.mark.parametrize("clip", CLIPS)
def test_tb_over_cap_explosion(image, zoom, clip):
    num, den = zoom + 16, 16
    assert SL.engine_scale_rejects(num, den)
    e = Emu(image, clip=clip, seed=zoom)
    w, h, pitch, off = 44, 36, 48, (3, 5)
    px = e.sprite(w, h, pitch, off, seed=zoom)
    x, y = 211 - zoom * 3, 97 - zoom * 2
    e.set_scale(num, den)
    e.run(A.va("t_tb_draw"), SPR, [DEST, 0xFF, x, y, TABLE])
    assert e.returned(0x14) and e.regs_preserved() and e.uc.reg_read(UC_X86_REG_EAX) == 0
    assert e.dest() == e.law(px, pitch, w, h, off, x, y, num, den, 0xFF)
    assert e.scale() == (num, den)


@pytest.mark.parametrize("reactor", [1, 2, 3, 4])
@pytest.mark.parametrize("res", [(1280, 1024), (1600, 1200), (1920, 1080), (3840, 2160), (7680, 4320)])
def test_pb_over_cap_cloud_at_pracx_max_zoom(image, reactor, res):
    zoom = pracx_max_zoom(*res)
    num, den = SL.buster_scale(zoom, reactor)
    if not SL.engine_scale_rejects(num, den):
        pytest.skip("native at this zoom")
    e = Emu(image, dw=400, dh=260, seed=reactor)
    px = e.buffer(300, 248, 300, seed=reactor)
    rect = SL.effect_blit_rect(0, 0, 0, 0, 300, 248, num, den)
    x, y = 200 - rect[2] // 2, 130 - rect[3] // 2          # boom centres the cloud on the target tile
    e.set_scale(zoom + 16, 16)
    e.run(A.va("t_pb_draw"), SPR, [DEST, 0xFF, x, y, num, den, TABLE])
    assert e.returned(0x1C) and e.regs_preserved()
    assert e.dest() == e.law(px, 300, 300, 248, (0, 0), x, y, num, den, 0xFF)
    assert e.scale() == (zoom + 16, 16)


@pytest.mark.parametrize("zoom", [11, 12, 20, 30])
def test_pb_just_above_the_cap_and_offscreen(image, zoom):
    num, den = SL.buster_scale(zoom, 4)
    assert SL.engine_scale_rejects(num, den)
    e = Emu(image, dw=300, dh=200, seed=zoom)
    px = e.buffer(300, 248, 304, seed=zoom)
    for x, y in ((-300, -200), (280, 190), (2000, 50), (-5000, 10)):
        e.reset_dest()
        e.run(A.va("t_pb_draw"), SPR, [DEST, -1, x, y, num, den, TABLE])
        assert e.returned(0x1C) and e.regs_preserved()
        assert e.dest() == e.law(px, 304, 300, 248, (0, 0), x, y, num, den, -1)


def test_real_buster_frame_at_4k_deepest_zoom(image):
    """The actual buster.flc mid-explosion frame (if the game is installed) at 4K's deepest Singularity zoom."""
    flc = config.game_dir() / "buster.flc"
    if not flc.exists():
        pytest.skip("buster.flc not present")
    import flc_census as F
    data = flc.read_bytes()
    _, _, frames, w, h = struct.unpack_from("<IHHHH", data, 0)
    pix = bytearray(w * h); p = 128; fr = 0
    while p + 16 <= len(data) and fr <= 10:
        fsize, fmagic, chunks = struct.unpack_from("<IHH", data, p)
        q = p + 16
        for _ in range(chunks if fmagic == 0xF1FA else 0):
            csize, ctype = struct.unpack_from("<IH", data, q)
            if ctype == 15:
                F.decode_byte_run(data, q + 6, csize, w, h, pix)
            elif ctype == 7:
                F.decode_ss2(data, q + 6, csize, w, h, pix)
            q += csize
        p += fsize; fr += 1
    assert (w, h) == (300, 248)
    num, den = SL.buster_scale(72, 4)
    e = Emu(image, dw=480, dh=270)
    px = e.buffer(300, 248, 300, px=bytes(pix) + bytes(600))
    x, y = -1800, -1500
    e.run(A.va("t_pb_draw"), SPR, [DEST, 0xFF, x, y, num, den, TABLE])
    assert e.returned(0x1C) and e.regs_preserved()
    assert e.dest() == e.law(px, 300, 300, 248, (0, 0), x, y, num, den, 0xFF)
