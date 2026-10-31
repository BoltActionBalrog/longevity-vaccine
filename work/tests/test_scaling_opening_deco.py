"""The planet-customisation decoration follows the opening backdrop (2026-10-18 fix 15): the REAL BAKED BYTES of
SetupWin_draw_item's decoration block (0x4AE647..0x4AE743), emulated under Unicorn against the law
scaling_laws.opening_deco, with the decoration slots the REAL loader bytes write.

The backdrop: change_opening (0x589A30) stretches the art over the whole screen per axis (Buffer_copy_3 @0x589AE8),
and the art is the caller's choice on ScreenWidth == 800 (0x58E422: (x)openingb.pcx 800x600, else (x)openinga.pcx
1024x768).  The decoration loader (custom_planet) keys on the same test: the planet at (449, -168) on the 800 art,
right-aligned (W - 404, 0) otherwise; the moons (moon{n}_800.pcx / MOON{n}.PCX) at (0, 0).  The deco thunks used to
stretch by W/1024 x H/768 on every screen: at 800x600, where the backdrop is drawn 1:1, the 404x768 planet shrank to
315x600 at (538, -168) (vanilla: 404x768 at (449, -168), registered on the backdrop's planet limb).

1. the engine's art choice and the loader's slots, from the bytes, are the law's (opening_art, the placements);
2. a 1:1 backdrop (800x600, 1024x768): the baked block == pristine, the full engine callee stream (name, ECX, args),
   for the opaque planet and the keyed moons, every slot, hover on;
3. a stretched backdrop (W != 800 or H != the art's): the baked block == the law -- the same per-axis stretch,
   including 800 x H != 600 (the 800 art's H/600 map, y = -168 mapped), 1024 x H != 768 and screens narrower
   than 1024;
4. no stale pixels: every refresh rect covers its draw (the soft_update after either path), on the law and on the
   bytes, over a sweep of screens;
5. the cave entries are assemble_thunks.py's source;
6. mutants (each gate bypassed, the art test removed, scale_y unsigned, the dstY map dropped, the v1 refresh) are
   killed.
"""
from __future__ import annotations

import struct
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn")
pefile = pytest.importorskip("pefile")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI,
    UC_X86_REG_ESP)

import assemble_thunks as AT  # noqa: E402
import scaling_laws as SL  # noqa: E402

SW, SH, BACKBUF, EXPANSION = 0x9B7B1C, 0x9B7B20, 0x945824, 0x9A6488
GET_PIXEL, DRAW2, COPY4, COPY3, SOFT_UPDATE, KSB = 0x5E2210, 0x5D84C0, 0x5DFF00, 0x5D9610, 0x5D5720, 0x668670
DECO_START, DECO_STOP = 0x4AE647, 0x4AE743          # after draw_item's text call .. the closing Buffer_set_clip
STACK, STACK_SZ, HEAP, HEAP_SZ, SENT = 0x10000000, 0x100000, 0x20000000, 0x100000, 0x0DEAD000
EBP = STACK + 0x80000
OWN_BUF = 0x12340000                                # draw_item's [ebp+8] (restored into EDI at 0x4AE740)

STUB_TABLE = {GET_PIXEL: ("Buffer_get_pixel", 8, 2), DRAW2: ("Buffer_draw_2", 0x18, 6),
              COPY4: ("Buffer_copy_4", 0x1C, 7), COPY3: ("Buffer_copy_3", 0x24, 9),
              SOFT_UPDATE: ("GraphicWin_soft_update", 0x10, 4), KSB: ("thunk_keyed_stretch_blit", 0x2C, 11)}

PLANET = (404, 768)                                  # S{1,2,3}L1C1.PCX (every width; the 800 art has no own planet)
MOON = (450, 450)                                    # MOON{1,2,3}.PCX
MOON_800 = (321, 343)                                # moon{1,2,3}_800.pcx
KEY = 9                                              # the engine's transparent index (load_pcx maps 255 -> 9)

NATIVE = [(800, 600), (1024, 768)]
STRETCHED = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (1600, 1200), (2560, 1440), (3840, 2160),
             (1280, 1024), (1680, 1050), (2560, 1080), (3440, 1440), (5120, 2880), (7680, 4320),
             (800, 480), (800, 720), (800, 768), (800, 1200),                   # the 800 art, stretched vertically
             (1024, 600), (1024, 1024), (1024, 640),                             # the 1024 art, stretched vertically
             (640, 480), (960, 720), (1000, 750), (1023, 767), (801, 600), (799, 600), (512, 384)]   # shrinking
REPORT = [(800, 600), (1024, 768), (1280, 720), (1366, 768), (1600, 1200), (1920, 1080), (3840, 2160)]


class Img(bytes):
    def __repr__(self):
        return f"<PE image {len(self)} B>"


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return Img(baked_exe.read_bytes())


@pytest.fixture(scope="module")
def pristine(bak_bytes) -> bytes:
    return Img(bak_bytes)


@lru_cache(maxsize=None)
def _image(data: bytes):
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    img = bytes(pe.get_memory_mapped_image())
    size = (max(len(img), pe.OPTIONAL_HEADER.SizeOfImage) + 0xFFF) & ~0xFFF
    pe.close()
    return ib, size, img


class Machine:
    """A fresh copy of the image on a W x H screen; engine primitives stubbed and recorded."""

    def __init__(self, data: bytes, w: int, h: int, keyed: bool = False):
        ib, size, img = _image(data)
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, size)
        uc.mem_write(ib, img)
        for base, sz in ((STACK, STACK_SZ), (HEAP, HEAP_SZ), (SENT, 0x1000)):
            uc.mem_map(base, sz)
        uc.mem_write(SENT, b"\xF4")
        self.heap = HEAP
        self.w32(SW, w)
        self.w32(SH, h)
        self.keyed = keyed
        self.calls: list = []
        for va in STUB_TABLE:
            uc.hook_add(UC_HOOK_CODE, self._stub, begin=va, end=va)

    def r32(self, a: int) -> int:
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def w32(self, a: int, v: int) -> None:
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def alloc(self, n: int) -> int:
        a = self.heap
        self.heap += (n + 0xF) & ~0xF
        return a

    def cstr(self, a: int) -> str:
        return bytes(self.uc.mem_read(a, 32)).split(b"\0")[0].decode()

    def _stub(self, uc, addr, _size, _ud):
        name, retn, nargs = STUB_TABLE[addr]
        esp = uc.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<%di" % nargs, bytes(uc.mem_read(esp + 4, 4 * nargs)))
        ecx = None if addr == KSB else uc.reg_read(UC_X86_REG_ECX)     # KSB is __cdecl-shaped (callee-clean)
        self.calls.append((name, ecx, args))
        ret = (KEY if self.keyed else 0x41) if addr == GET_PIXEL else 0
        uc.reg_write(UC_X86_REG_EAX, ret)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + retn)
        uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", bytes(uc.mem_read(esp, 4)))[0])

    def window(self, start: int, stop: int, regs: dict) -> None:
        for k, v in regs.items():
            self.uc.reg_write(k, v)
        self.uc.emu_start(start, stop, count=200_000)
        assert self.uc.reg_read(UC_X86_REG_EIP) == stop, hex(self.uc.reg_read(UC_X86_REG_EIP))


# ---- the engine's own choices, from the bytes ----------------------------------------------------------------------
def opening_art_file(data: bytes, w: int, expansion: bool) -> str:
    """The art name change_opening is handed on a w-wide screen (0x58E40B .. the `mov esi, str` pair)."""
    m = Machine(data, w, 600)
    m.w32(EXPANSION, 1 if expansion else 0)
    m.uc.reg_write(UC_X86_REG_EBX, 0)
    stop = 0x58E430 if expansion else 0x58E4DE
    m.window(0x58E40B, stop, {UC_X86_REG_ESP: EBP - 0x2000, UC_X86_REG_EBP: EBP})
    return m.cstr(m.uc.reg_read(UC_X86_REG_ESI))


def loader_planet_slot(data: bytes, w: int, src_w: int = PLANET[0]) -> tuple:
    """custom_planet's planet slot write (0x58C454 .. 0x58C47E): (x, y) for a src_w-wide planet."""
    m = Machine(data, w, 600)
    esi = EBP - 0xCE0
    m.w32(EBP - 0x7AA8, src_w)                  # the loaded Buffer's +0x80 (it lives at ebp-0x7B28)
    m.window(0x58C454, 0x58C47E, {UC_X86_REG_ESP: EBP - 0x8000, UC_X86_REG_EBP: EBP, UC_X86_REG_ESI: esi})
    return m.r32(esi - 0xC), m.r32(esi)


def loader_moon_file(data: bytes, w: int) -> str:
    """custom_planet's erosive-forces art (0x58C4AA .. 0x58C4C2: eax = the first moon's name)."""
    m = Machine(data, w, 600)
    m.window(0x58C4AA, 0x58C4C2, {UC_X86_REG_ESP: EBP - 0x8000, UC_X86_REG_EBP: EBP})
    return m.cstr(m.uc.reg_read(UC_X86_REG_EAX))


def deco_inputs(w: int, keyed: bool) -> tuple:
    """(x, y, src_w, src_h) the loader hands the draw on a w-wide screen (the slot values are the bytes', test 1)."""
    if keyed:
        return (0, 0) + (MOON_800 if w == SL.OPENING_ART_B_W else MOON)
    if w == SL.OPENING_ART_B_W:
        return (449, -168) + PLANET
    return (w - PLANET[0], 0) + PLANET


# ---- the decoration block, from the bytes --------------------------------------------------------------------------
def run_deco(data: bytes, w: int, h: int, keyed: bool, slot: int = 1) -> list:
    """SetupWin_draw_item's decoration block for item `slot` hovered: every engine callee (name, ECX, args)."""
    m = Machine(data, w, h, keyed)
    bb = m.alloc(0x600)
    m.w32(BACKBUF, bb)
    win = m.alloc(0x1400)
    x, y, sw, sh = deco_inputs(w, keyed)
    decos = []
    for k in range(3):
        d = m.alloc(0x600)
        m.w32(d + 0x80, sw)
        m.w32(d + 0x84, -sh)                       # Buffer heights are stored negative (top-down)
        m.w32(win + 0xA1C + 4 * k, d)
        m.w32(win + 0xA28 + 4 * k, x)
        m.w32(win + 0xA34 + 4 * k, y)
        decos.append(d)
    m.uc.mem_write(EBP + 8, struct.pack("<II", OWN_BUF, 1))         # [ebp+8] own buffer, [ebp+0xC] hover = 1
    esp0 = EBP - 0x100
    m.window(DECO_START, DECO_STOP, {UC_X86_REG_ESP: esp0, UC_X86_REG_EBP: EBP, UC_X86_REG_ESI: win,
                                     UC_X86_REG_EBX: slot, UC_X86_REG_EDI: 0x55555555})
    uc = m.uc
    assert uc.reg_read(UC_X86_REG_ESP) == esp0, "stack imbalance across the decoration block"
    assert (uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_EBP)) == (win, slot, EBP)
    assert uc.reg_read(UC_X86_REG_EDI) == OWN_BUF
    m.deco, m.bb = decos[slot], bb
    m.calls_ = m.calls
    return [(n, "deco" if c == decos[slot] else "bb" if c == bb else c,
             tuple("dest" if a == bb + 0x444 else "deco" if a == decos[slot] else a for a in args))
            for n, c, args in m.calls]


def law_calls(w: int, h: int, keyed: bool) -> list:
    """The law's engine-call stream for the decoration block, in run_deco's vocabulary."""
    x, y, sw, sh = deco_inputs(w, keyed)
    L = SL.opening_deco(x, y, sw, sh, keyed, w, h)
    kind, dx, dy, dw, dh = L["draw"]
    out = [("Buffer_get_pixel", "deco", (0, 0))]
    if kind == "copy4":
        out.append(("Buffer_copy_4", "deco", ("dest", 0, 0, dx, dy, dw, dh)))
    elif kind == "draw2":
        out.append(("Buffer_draw_2", "deco", ("dest", KEY, dx, dy, 1, 1)))
    elif kind == "copy3":
        out.append(("Buffer_copy_3", "deco", ("dest", 0, 0, sw, sh, dx, dy, dw, dh)))
    else:
        out.append(("thunk_keyed_stretch_blit", None, ("deco", "dest", 0, 0, sw, sh, dx, dy, dw, dh, KEY)))
    out.append(("GraphicWin_soft_update", "bb", L["refresh"]))
    return out


# ---- 1. the engine's choices are the law's -------------------------------------------------------------------------
@pytest.mark.parametrize("w", [640, 799, 800, 801, 1024, 1280, 1366, 1600, 1920, 3840])
def test_scaling_opening_art_is_the_engines_choice(pristine, baked, w):
    aw, ah = SL.opening_art(w)
    for data in (pristine, baked):
        assert opening_art_file(data, w, True) == ("xopeningb.pcx" if aw == SL.OPENING_ART_B_W else "xopeninga.pcx")
        assert opening_art_file(data, w, False) == ("openingb.pcx" if aw == SL.OPENING_ART_B_W else "openinga.pcx")
        assert loader_moon_file(data, w) == ("moon1_800.pcx" if aw == SL.OPENING_ART_B_W else "MOON1.PCX")
        assert loader_planet_slot(data, w) == deco_inputs(w, False)[:2]
    assert (aw, ah) == ((800, 600) if w == 800 else (1024, 768))       # the PCX headers (xopeningb / xopeninga)


def test_opening_backdrop_native_is_the_art_size():
    assert [wh for wh in NATIVE + STRETCHED if SL.opening_backdrop_native(*wh)] == NATIVE


# ---- 2. a 1:1 backdrop is vanilla, callee for callee ----------------------------------------------------------------
@pytest.mark.parametrize("w,h", NATIVE)
@pytest.mark.parametrize("keyed", [False, True], ids=["planet", "moons"])
def test_scaling_opening_deco_native_backdrop_is_pristine(pristine, baked, w, h, keyed):
    for slot in range(3):
        p = run_deco(pristine, w, h, keyed, slot)
        b = run_deco(baked, w, h, keyed, slot)
        assert b == p, (w, h, keyed, slot)
        assert p == law_calls(w, h, keyed), (w, h, keyed, slot)       # the law's native arm IS vanilla


# ---- 3. a stretched backdrop: the same per-axis stretch --------------------------------------------------------------
@pytest.mark.parametrize("w,h", STRETCHED)
@pytest.mark.parametrize("keyed", [False, True], ids=["planet", "moons"])
def test_scaling_opening_deco_follows_the_stretched_backdrop(baked, w, h, keyed):
    assert not SL.opening_backdrop_native(w, h)
    assert run_deco(baked, w, h, keyed) == law_calls(w, h, keyed), (w, h, keyed)


def test_stretched_planet_is_the_backdrops_slot():
    """Enlarging on the 1024 art, the planet spans the backdrop's own slot [620, 1024) x [0, 768) mapped (the right
    edge exact, the left within the floor); on the 800 art at 800 x H it is (449, -168, 404, 768) mapped by H/600."""
    for w, h in [(1280, 720), (1366, 768), (1920, 1080), (1600, 1200), (3840, 2160), (1024, 1024)]:
        kind, x, y, dw, dh = SL.opening_deco(w - 404, 0, 404, 768, False, w, h)["draw"]
        assert (kind, x + dw, y, dh) == ("copy3", w, 0, h)
        assert x - 620 * w // 1024 in (0, 1)
    for h in (480, 720, 1200):
        kind, x, y, dw, dh = SL.opening_deco(449, -168, 404, 768, False, 800, h)["draw"]
        assert (kind, x, dw) == ("copy3", 449, 404)
        assert y + dh in (h, h + 1) and abs(y * 600 - (-168) * h) < 600 and abs(dh * 600 - 768 * h) < 600


# ---- 4. no stale pixels: the refresh covers the draw ---------------------------------------------------------------
def _covers(refresh, draw, w, h) -> bool:
    rx, ry, rw, rh = refresh
    dx, dy, dw, dh = draw
    l, t, r, b = max(dx, 0), max(dy, 0), min(dx + dw, w), min(dy + dh, h)      # the on-screen part of the draw
    return l >= r or t >= b or (rx <= l and ry <= t and r <= rx + rw and b <= ry + rh)


SWEEP = sorted({(w, h) for w in (512, 640, 720, 799, 800, 801, 900, 960, 1000, 1023, 1024, 1025, 1152, 1280, 1366,
                                 1600, 1920, 2560, 3440, 3840)
                for h in (384, 480, 600, 720, 767, 768, 769, 900, 1024, 1080, 1200, 1440, 2160)})


def test_opening_deco_refresh_covers_the_draw_law():
    bad = []
    for w, h in SWEEP:
        for keyed in (False, True):
            L = SL.opening_deco(*deco_inputs(w, keyed), keyed, w, h)
            if not _covers(L["refresh"], L["draw"][1:], w, h):
                bad.append((w, h, keyed, L))
    assert bad == []


@pytest.mark.parametrize("w,h", NATIVE + STRETCHED)
def test_scaling_opening_deco_refresh_covers_the_draw_bytes(baked, w, h):
    for keyed in (False, True):
        calls = run_deco(baked, w, h, keyed)
        draw = calls[1]
        a = draw[2]
        rect = {"Buffer_copy_4": lambda: (a[3], a[4], a[5], a[6]), "Buffer_draw_2": lambda: (a[2], a[3]) + deco_inputs(
            w, keyed)[2:], "Buffer_copy_3": lambda: a[5:9], "thunk_keyed_stretch_blit": lambda: a[6:10]}[draw[0]]()
        assert calls[2][0] == "GraphicWin_soft_update"
        assert _covers(calls[2][2], rect, w, h), (w, h, keyed, calls)


# ---- 5. the cave entries are the assembler's source ----------------------------------------------------------------
def test_scaling_opening_deco_cave_is_the_assembler_source(loaded):
    cave = {}
    for c in loaded["caves"]:
        for e in c.get("contents") or []:
            cave[e["id"]] = (c["id"], int(e["offset"]), " ".join(str(e["bytes"]).split()))
    for name, off, body in AT.DECO_BACKDROP_ENTRIES:
        assert cave[name] == ("pcave2", off, AT.normalize(body)), name
    for name, off, body in (("thunk_deco_blit_stretched", 0x300, AT.THUNK_DECO_BLIT_STRETCHED),
                            ("scale_x", 0x370, AT.SCALE_X), ("scale_y", 0x390, AT.SCALE_Y),
                            ("thunk_deco_soft_update", 0x3B0, AT.THUNK_DECO_SOFT_UPDATE),
                            ("thunk_deco_keyed_scaled", 0x410, AT.THUNK_DECO_KEYED_SCALED)):
        assert cave[name] == ("menu_strip_thunks", off, AT.normalize(body)), name
    sites = {s["virtual_addr"]: " ".join(str(s["new_bytes"]).split()) for s in loaded["sites"] if "new_bytes" in s}
    assert sites[0x4AE710] == "E8 {rel32:t_deco_blit_gate}"
    assert sites[0x4AE6BC].startswith("E8 {rel32:t_deco_keyed_gate} ")


# ---- 6. mutants ------------------------------------------------------------------------------------------------------
def _patch(data: bytes, va: int, new: bytes) -> bytes:
    pe = pefile.PE(data=data, fast_load=True)
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    pe.close()
    b = bytearray(data)
    b[off:off + len(new)] = new
    return Img(b)


def _call(at: int, target: int) -> bytes:
    return b"\xE8" + struct.pack("<i", target - (at + 5))


MUTANT_SCREENS = [(800, 600), (1024, 768), (800, 480), (960, 720), (1366, 768), (3840, 2160)]


def behaviour_failures(data: bytes, pristine: bytes) -> list:
    bad = []
    for w, h in MUTANT_SCREENS:
        for keyed in (False, True):
            want = law_calls(w, h, keyed)
            if SL.opening_backdrop_native(w, h):
                assert run_deco(pristine, w, h, keyed) == want
            got = run_deco(data, w, h, keyed)
            if got != want:
                bad.append((w, h, keyed))
    return bad


def _mutants(loaded) -> dict:
    s = loaded["s2v"]
    art, blit, su, sy = s["deco_art"], s["thunk_deco_blit_stretched"], s["thunk_deco_soft_update"], s["scale_y"]
    return {
        "blit gate bypassed (v1 site)": (0x4AE710, _call(0x4AE710, blit)),
        "keyed gate bypassed (v1 site)": (0x4AE6BC, _call(0x4AE6BC, s["thunk_deco_keyed_scaled"])),
        "art test removed (1024 art everywhere)": (art + 0x14, b"\xEB"),             # jne .r -> jmp .r
        "scale_y unsigned (mul/div)": (sy + 0x09, b"\xF7\x25\x20\x7B\x9B\x00\xF7\xF1"),
        "blit dstY unmapped": (blit + 0x34, b"\xFF\x75\x18" + b"\x90" * 6),            # push [ebp+0x18]; nops
        "refresh W' = scale_x only (v1)": (su + 0x1F, b"\xEB\x06"),                   # jge -> jmp: skip the max
        "refresh Y' unmapped": (su + 0x2F, b"\x90" * 5),                               # drop the call scale_y
    }


def test_opening_deco_mutants_baseline_is_clean(baked, pristine):
    assert behaviour_failures(baked, pristine) == []


@pytest.mark.parametrize("name", ["blit gate bypassed (v1 site)", "keyed gate bypassed (v1 site)",
                                  "art test removed (1024 art everywhere)", "scale_y unsigned (mul/div)",
                                  "blit dstY unmapped", "refresh W' = scale_x only (v1)", "refresh Y' unmapped"])
def test_opening_deco_mutant_is_killed(baked, pristine, loaded, name):
    va, new = _mutants(loaded)[name]
    assert behaviour_failures(_patch(baked, va, new), pristine), name


# ---- the before/after table (run with -s to print; asserts nothing beyond the law above) ---------------------------
def test_scaling_opening_deco_report_table(baked, capsys):
    rows = []
    for w, h in REPORT:
        for keyed in (False, True):
            c = run_deco(baked, w, h, keyed)
            rows.append(f"{w}x{h} {'moons ' if keyed else 'planet'}: {c[1][0]} {c[1][2]}  refresh {c[2][2]}")
            assert c == law_calls(w, h, keyed)
    with capsys.disabled():
        print("\n" + "\n".join(rows))
