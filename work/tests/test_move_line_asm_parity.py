"""Unicorn parity for group map_move_line_scale (assemble_move_line.py) against scaling_laws.move_line_calls /
move_label_shadow.

Two harnesses, both entered through the SITE bytes resolved from patches.yaml (a site/thunk desync fails here):

  TRACE   the engine callees are RET-n stubs that record (ecx, args).  The emitted Buffer_line_2 / Buffer_hline_2
          sequence must equal the law's call list exactly, for g in {16,17,22,24,25,28,32,40} x every slope class,
          both directions, axis-aligned and zero-length lines; the frame (esp after the callee-clean RET 0x14),
          ebx/esi/edi/ebp and the colour arg are preserved.  Same for the label shadow (RET 0x10, dx/dy).

  ENGINE  the PRISTINE exe image (terranx_PRACX.exe.bak) is mapped and the REAL Buffer_line_2 / hline_2 / vline_2
          rasterise into a fake overlay Buffer.  Measured, not modelled (CLAUDE.md): g <= 24 is pixel-identical to
          vanilla; vanilla pixels stay drawn; away from the endpoint plugs every major-axis step carries exactly K
          contiguous pixels; every polyline joint of the 8 map hop directions has its K x K square lit -- and the
          same joints DO notch with the line copies alone (the reason the plug is in the law).
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("keystone", reason="keystone absent -- asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent -- asm parity unverified")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_move_line as AM  # noqa: E402
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000
BUF = 0x0093755C                         # the overlay Buffer the site hands over (ecx)
STACK = 0x00200000
SP0 = STACK + 0x8000
COLOR = 0xFA
SAVED = {UC_X86_REG_EBX: 0xB0B0B0B0, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
         UC_X86_REG_EBP: 0xE0E0E0E0}
G_SWEEP = (16, 17, 22, 24, 25, 28, 32, 40)
VECTORS = [(0, 0), (9, 0), (-9, 0), (0, 9), (0, -9), (7, 7), (-7, 7), (7, -7), (-7, -7),
           (28, 14), (-28, 14), (28, -14), (-28, -14), (56, 0), (-56, 0), (0, 28), (0, -28),
           (3, 11), (-11, 3), (1, 2), (2, 1), (1, 0), (0, 1)]
# the map's hop directions: iso tile half-diagonals, full-width E/W, full-height N/S
HOPS = [(28, 14), (-28, 14), (28, -14), (-28, -14), (56, 0), (-56, 0), (0, 28), (0, -28)]


def _i(v):
    return int(v, 16) if isinstance(v, str) else int(v)


@pytest.fixture(scope="module")
def yaml_world():
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    st = dict(ap.build_symbol_table(symbols, caves))
    ents = {e["id"]: e for c in caves for e in (c.get("contents") or [])}
    code = {n: ap.ByteTemplate(ents[n]["bytes"]).resolve(st[n], st) for n in ("t_ml_line", "t_ml_textcolor")}
    site_by_id = {s["id"]: s for s in sites}
    site = {}
    for sid, va in (("MapWin_direct_dest_line.line", AM.SITE_LINE),
                    ("MapWin_on_mouse_move.label_shadow", AM.SITE_TEXTCOLOR),
                    ("MapWin_on_mouse_move.label_font", AM.SITE_FONT)):
        s = site_by_id[sid]
        assert _i(s["virtual_addr"]) == va and s["group"] == "map_move_line_scale"
        site[sid] = (va, ap.ByteTemplate(s["new_bytes"]).resolve(va, st))
    return st, code, site


def test_assembler_matches_yaml(yaml_world):
    st, code, _ = yaml_world
    lo, line, to, tc = AM.layout()
    assert st["t_ml_line"] == PCAVE2 + lo and st["t_ml_textcolor"] == PCAVE2 + to
    assert code["t_ml_line"] == line and code["t_ml_textcolor"] == tc
    assert st["g_popup_scale_num"] == AM.G


def test_font_site_is_the_face_law(yaml_world):
    """0x46F595 find_font(12,1) -> t_ffn: the cdecl drop-in (the caller's add esp,8 stays)."""
    st, _, site = yaml_world
    va, b = site["MapWin_on_mouse_move.label_font"]
    assert b[0] == 0xE8 and va + 5 + struct.unpack("<i", b[1:5])[0] == st["t_ffn"]


# ---------------------------------------------------------------------------------------------- TRACE
class Trace:
    def __init__(self, yaml_world):
        st, code, site = yaml_world
        self.site = site
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(PCAVE2, 0x30000)
        uc.mem_map(0x668000, 0x1000)
        uc.mem_map(0x5DA000, 0x1000)
        uc.mem_map(0x5E1000, 0x1000)
        uc.mem_map(0x467000, 0x1000)
        uc.mem_map(0x46F000, 0x1000)
        uc.mem_map(STACK, 0x10000)
        for n, b in code.items():
            uc.mem_write(st[n], b)
        uc.mem_write(AM.BUFFER_LINE_2, b"\xC2\x14\x00")
        uc.mem_write(AM.BUFFER_HLINE_2, b"\xC2\x10\x00")
        uc.mem_write(AM.BUFFER_SET_TEXT_COLOR, b"\xC2\x10\x00")
        for sid in ("MapWin_direct_dest_line.line", "MapWin_on_mouse_move.label_shadow"):
            va, b = site[sid]
            uc.mem_write(va, b + b"\xF4")
        self.calls = []
        stubs = {AM.BUFFER_LINE_2: ("line", 5), AM.BUFFER_HLINE_2: ("hline", 4),
                 AM.BUFFER_SET_TEXT_COLOR: ("color", 4)}

        def hook(u, addr, size, _):
            kind, n = stubs[addr]
            esp = u.reg_read(UC_X86_REG_ESP)
            args = struct.unpack(f"<{n}i", u.mem_read(esp + 4, 4 * n))
            self.calls.append((kind, u.reg_read(UC_X86_REG_ECX)) + args)
        for a in stubs:
            uc.hook_add(UC_HOOK_CODE, hook, begin=a, end=a)
        self.uc = uc

    def run(self, sid, g, args):
        uc = self.uc
        uc.mem_write(AM.G, struct.pack("<i", g))
        uc.mem_write(SP0, struct.pack(f"<{len(args)}i", *args))
        uc.reg_write(UC_X86_REG_ESP, SP0)
        uc.reg_write(UC_X86_REG_ECX, BUF)
        uc.reg_write(UC_X86_REG_EAX, 0xAAAA)
        uc.reg_write(UC_X86_REG_EDX, 0xDDDD)
        for r, v in SAVED.items():
            uc.reg_write(r, v)
        self.calls = []
        va, _ = self.site[sid]
        uc.emu_start(va, va + 5, count=20000)
        assert uc.reg_read(UC_X86_REG_EIP) == va + 5
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 * len(args), "callee-clean contract broken"
        for r, v in SAVED.items():
            assert uc.reg_read(r) == v, "callee-saved register clobbered"
        return self.calls


@pytest.fixture(scope="module")
def trace(yaml_world):
    return Trace(yaml_world)


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("dx,dy", VECTORS)
def test_line_trace_equals_law(trace, g, dx, dy):
    x1, y1 = 400, 300
    got = trace.run("MapWin_direct_dest_line.line", g, (x1, y1, x1 + dx, y1 + dy, COLOR))
    want = SL.move_line_calls(x1, y1, x1 + dx, y1 + dy, g)
    assert [c[1] for c in got] == [BUF] * len(got)                 # every draw on the site's Buffer
    assert [c[-1] for c in got] == [COLOR] * len(got)              # colour passed through untouched
    assert [(c[0],) + c[2:-1] for c in got] == want


@pytest.mark.parametrize("g", range(SL.G_MIN, SL.G_MAX + 1))
@pytest.mark.parametrize("dx,dy", [(1, 1), (0, 0), (2, 1), (-1, 1)])
def test_label_shadow_trace_equals_law(trace, g, dx, dy):
    got = trace.run("MapWin_on_mouse_move.label_shadow", g, (0x9F, 0x41, dx, dy))
    assert got == [("color", BUF, 0x9F, 0x41) + SL.move_label_shadow(dx, dy, g)]


# ---------------------------------------------------------------------------------------------- ENGINE
W = H = 256


class Engine:
    """The pristine exe's own line primitives drawing into a fake overlay Buffer (+0x58 = 0: no DirectDraw
    surface -> +0x54 is the pixel pointer; clip +0x20..+0x2C; pitch +0x4A8; w +0x80, h +0x84 (negative))."""
    SURF = 0x10010000
    B = 0x10000000
    HALT = 0x10020000

    def __init__(self, yaml_world, exe):
        import pefile
        st, code, site = yaml_world
        pe = pefile.PE(str(exe))
        ib = pe.OPTIONAL_HEADER.ImageBase
        img = bytearray(pe.get_memory_mapped_image())
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        size = (len(img) + 0xFFF) & ~0xFFF
        uc.mem_map(ib, size)
        img += b"\x00" * (size - len(img))
        va, b = site["MapWin_direct_dest_line.line"]
        img[va - ib:va - ib + 5] = b
        img[va - ib + 5] = 0xF4
        uc.mem_write(ib, bytes(img))
        uc.mem_map(PCAVE2, 0x30000)
        for n, c in code.items():
            uc.mem_write(st[n], c)
        uc.mem_map(STACK, 0x10000)
        uc.mem_map(self.B, 0x30000)
        uc.mem_write(self.HALT, b"\xF4")
        self.uc, self.site_va = uc, va

    def reset(self, g):
        uc = self.uc
        uc.mem_write(AM.G, struct.pack("<i", g))
        uc.mem_write(self.SURF, b"\x00" * (W * H))
        uc.mem_write(self.B, b"\x00" * 0x500)
        uc.mem_write(self.B + 0x20, struct.pack("<4i", 0, 0, W, H))
        uc.mem_write(self.B + 0x54, struct.pack("<I", self.SURF))
        uc.mem_write(self.B + 0x4A8, struct.pack("<i", W))
        uc.mem_write(self.B + 0x80, struct.pack("<2i", W, -H))   # buffer w / h (negative): hline/vline bound

    def _enter(self, start, stop, args, ret):
        uc = self.uc
        frame = (struct.pack("<I", ret) if ret is not None else b"") + struct.pack(f"<{len(args)}i", *args)
        sp = SP0 - (4 if ret is not None else 0)
        uc.mem_write(sp, frame)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_ECX, self.B)
        uc.emu_start(start, stop, count=2_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == stop

    def thunk(self, x1, y1, x2, y2):
        self._enter(self.site_va, self.site_va + 5, (x1, y1, x2, y2, COLOR), None)

    def law(self, calls):
        for c in calls:
            if c[0] == "line":
                self._enter(AM.BUFFER_LINE_2, self.HALT, c[1:] + (COLOR,), self.HALT)
            else:
                self._enter(AM.BUFFER_HLINE_2, self.HALT, c[1:] + (COLOR,), self.HALT)

    def pixels(self):
        raw = bytes(self.uc.mem_read(self.SURF, W * H))
        return {(i % W, i // W) for i, v in enumerate(raw) if v}


@pytest.fixture(scope="module")
def engine(yaml_world):
    exe = config.terranx_bak(required=False)
    if not exe or not pathlib.Path(exe).exists():
        pytest.skip("pristine exe .bak not present -- engine pixel parity unverified")
    pytest.importorskip("pefile")
    return Engine(yaml_world, exe)


def _thunk_px(engine, g, pts):
    engine.reset(g)
    for (a, b), (c, d) in zip(pts, pts[1:]):
        engine.thunk(a, b, c, d)
    return engine.pixels()


def _vanilla_px(engine, pts):
    engine.reset(16)
    engine.law([("line",) + a + c for a, c in zip(pts, pts[1:])])
    return engine.pixels()


@pytest.mark.parametrize("g", G_SWEEP)
@pytest.mark.parametrize("dx,dy", VECTORS)
def test_engine_pixels_equal_the_law(engine, g, dx, dy):
    p0, p1 = (128, 128), (128 + dx, 128 + dy)
    got = _thunk_px(engine, g, [p0, p1])
    engine.reset(g)
    engine.law(SL.move_line_calls(*p0, *p1, g))
    assert got == engine.pixels()
    van = _vanilla_px(engine, [p0, p1])
    assert bool(van) == ((dx, dy) != (0, 0))               # the fake Buffer really rasterises (zero-length: nothing)
    if SL.stroke_width(g) <= 1:
        assert got == van                                  # g <= 24: vanilla, pixel for pixel
    assert van <= got                                      # the vanilla line is always part of the stroke


@pytest.mark.parametrize("g", (25, 28, 40))
@pytest.mark.parametrize("dx,dy", [v for v in VECTORS if v != (0, 0)])
def test_engine_minor_axis_thickness_is_k(engine, g, dx, dy):
    k = SL.stroke_width(g)
    offs = SL.move_line_offsets(g)
    p0, p1 = (128, 128), (128 + dx, 128 + dy)
    px = _thunk_px(engine, g, [p0, p1])
    x_major = abs(dx) >= abs(dy)
    major = 0 if x_major else 1
    ends = (p0[major], p1[major])
    plug = set()
    for e in ends:
        plug |= {e + o for o in offs}
    lo, hi = min(ends), max(ends)
    for m in range(lo, hi + 1):
        if m in plug:
            continue
        run = sorted(p[1 - major] for p in px if p[major] == m)
        assert len(run) == k and run == list(range(run[0], run[0] + k)), (m, run)


def _joint_square(j, offs):
    return {(j[0] + a, j[1] + b) for a in offs for b in offs}


@pytest.mark.parametrize("g", (25, 40))
def test_engine_joints_are_notch_free(engine, g):
    offs = SL.move_line_offsets(g)
    for h1 in HOPS:
        for h2 in HOPS:
            j = (128, 128)
            pts = [(j[0] - h1[0], j[1] - h1[1]), j, (j[0] + h2[0], j[1] + h2[1])]
            px = _thunk_px(engine, g, pts)
            assert _joint_square(j, offs) <= px, (h1, h2)


@pytest.mark.parametrize("g", (25, 40))
def test_engine_joints_notch_without_the_plug(engine, g):
    """The premise of the plug: minor-axis copies alone leave an unlit pixel in some joint's K x K square."""
    offs = SL.move_line_offsets(g)
    notched = 0
    for h1 in HOPS:
        for h2 in HOPS:
            j = (128, 128)
            pts = [(j[0] - h1[0], j[1] - h1[1]), j, (j[0] + h2[0], j[1] + h2[1])]
            engine.reset(g)
            for a, c in zip(pts, pts[1:]):
                engine.law([x for x in SL.move_line_calls(*a, *c, g) if x[0] == "line"])
            if not _joint_square(j, offs) <= engine.pixels():
                notched += 1
    assert notched > 0


@pytest.mark.parametrize("g", (25, 40))
@pytest.mark.parametrize("dx,dy", HOPS)
def test_engine_plug_cap_is_bounded(engine, g, dx, dy):
    """Everything the thunk lights is a line copy or inside an endpoint's K x K square (the cap reaches at most
    K-1 px past the vanilla endpoint)."""
    offs = SL.move_line_offsets(g)
    p0, p1 = (128, 128), (128 + dx, 128 + dy)
    px = _thunk_px(engine, g, [p0, p1])
    engine.reset(g)
    engine.law([c for c in SL.move_line_calls(*p0, *p1, g) if c[0] == "line"])
    allowed = engine.pixels() | _joint_square(p0, offs) | _joint_square(p1, offs)
    assert px <= allowed
