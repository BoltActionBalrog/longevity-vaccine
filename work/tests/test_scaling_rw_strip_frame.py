"""HQ report kind-icon strip: its outer da50 frame under the strip clip, on the REAL BAKED BYTES (2026-10-17).

ReportIf_console_chrome sets the clip to the strip region and draws the da50 at L - s(7) (0x4A3D85), so the frame
leaves its clip on the left.  thunk_frame_enlarge refuses the band map for any frame outside the dest clip (the band
map writes the plane directly), so before t_rwk_stripframe the strip went through the GDI NN stretch at the
exact-fill size of the R-1/B-1 rect: at 4K strokes 3 / 3 / 3 rows (K = 2) and the bottom / right stroke one px
inside the panels' at every g -- the channel to the strip's d5a0 7/6 at 4K, 4/3 at 1600x1200 and 1920x1080, 3/2 at
1600x900 against vanilla's even 3/3.  Law scaling_laws.rw_strip_frame.

1. the chrome painter (0x4A3D20 .. the strip d528) runs on the walked bake with EVERYTHING real -- t_rwk_boxforce,
   thunk_hud_boxframe, hollow_flat, the engine's Buffer_box_sprite / tile / sprite blits, thunk_frame_enlarge, the
   band map, fe_pair_remap -- on the box sets the image's own loader (load_interface_boxsets) cuts from the game's
   interface.pcx; only Win32 imports are Python stubs (rects, DIB bookkeeping) and CRT malloc is a bump allocator.
   No chrome frame may reach GDI StretchBlt (= fell off the band map); the strip's top / bottom / right strokes sit
   on the law's half-open spans, its channels to the d5a0 are equal on all three sides, and it shares the left
   panel's bottom stroke rows;
2. the strip draw changes nothing outside the strip region (the hidden band keeps its pixels) and inside it equals
   t_rwk_boxforce's own draw of the same frame with no clip;
3. t_rwk_stripframe alone (its baked bytes, t_rwk_boxforce / Buffer_box_sprite hooked): every path, the band save /
   restore, the clip edge, callee-saved registers, RET 8.

2026-10-18 fix 9 (law scaling_laws.rw_strip_anchor): the strip's LEFT junction.  The strip region's L = fl(244g/16) and
the left panel's R = fl(245g/16) floor independently, while vanilla's seeds put the strip on the panel's last column; at
g = 25 / 28 a column of the panel's K-wide right stroke survived at L-1 through the strip rows, and the d5a0 -> d5a0 gap
was off the strip's T / B / R channel by 1 at g = 23 / 25 / 28 / 39.  t_rwk_stripanchor draws the strip from
(panel R - K, T, R, B): 4. the junction on the real bytes at every g 16..40 and at the real screen placements (gap ==
channel == s(4) - K, no residue, the top stroke starts on the panel stroke, ReportIf+0x40 untouched, g = 16 identical
to the pristine .bak); 5. t_rwk_stripanchor alone.
"""
from __future__ import annotations

import functools
import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

pytest.importorskip("unicorn")
pytest.importorskip("capstone")
pefile = pytest.importorskip("pefile")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import config  # noqa: E402
import scaling_laws as SL  # noqa: E402
from test_scaling_rw_console_boxes import Img, walk  # noqa: E402  (t_rw_init_leave's bootstrap + walker, real VP)

G_ADDR = 0x668740
STRIPE_PERIOD = 0x66879C            # g_stripe_period (thunk_ensure_scale writes it with g)
RI, MAIN, PCX_BUF = 0x885F38, 0x7AEC64, 0x798668
CHROME, STRIP_CALL, STRIP_RET, CHROME_STOP = 0x4A3D20, 0x4A3D85, 0x4A3D8A, 0x4A3EB9
BOX_SPRITE = 0x5E2DD3
MALLOC, FREE = 0x64558A, 0x644EF2
BUF_CTOR, BUF_INIT = 0x5D7210, 0x5D7670
LOADER_LO, LOADER_HI = 0x453B3A, 0x453D66          # load_interface_boxsets' 9-slice set loop (sets 0..50)
FILLBUF_LO, FILLBUF_HI = 0x75C218, 0x76DC30        # its static fill Buffers (CRT-constructed in the game)
STUBS, HEAP, STACK = 0x70000000, 0x40000000, 0x20000000
DA50, D5A0 = 0x1A, 0x1F
# the native 1024x768 console regions (MainWin seeds; the bake scales them floor(v*g/16), measured 4K / 1600 census)
NAT = {"L": (4, 56, 245, 252), "R": (779, 56, 1020, 252), "S": (244, 188, 768, 252), "C": (262, 66, 763, 172)}
GS = (16, 17, 18, 19, 20, 22, 25, 28, 30, 33, 36, 40)
TRIVIAL = {"EnterCriticalSection": (0, 1), "LeaveCriticalSection": (0, 1), "InitializeCriticalSection": (0, 1),
           "DeleteCriticalSection": (0, 1), "GetLastError": (0, 0), "SetLastError": (0, 1), "InvalidateRect": (1, 3),
           "ValidateRect": (1, 2), "SetBkMode": (1, 2), "SetTextColor": (0, 2), "SetBkColor": (0, 2),
           "SetTextAlign": (0, 2), "DeleteDC": (1, 1), "DeleteObject": (1, 1), "SetDIBColorTable": (256, 4),
           "GetDIBColorTable": (256, 4), "RealizePalette": (0, 1), "GdiFlush": (1, 0), "VirtualFree": (1, 3),
           "HeapFree": (1, 3), "GetProcessHeap": (0x1234, 0), "SelectClipRgn": (2, 2), "SelectPalette": (0x5000, 3),
           "SetStretchBltMode": (1, 2), "ReleaseDC": (1, 2), "GetDC": (0x5004, 1)}


def regions(g, jitter=None):
    regs = {k: tuple(v * g // 16 for v in r) for k, r in NAT.items()}
    if jitter:
        L, T, R, B = regs["S"]
        regs["S"] = (L + jitter[0], T + jitter[1], R + jitter[2], B + jitter[3])
    return regs


def _s32(v):
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


class Chrome:
    """The baked image (walked at g > 16) in Unicorn with Win32 stubbed, the box sets loaded, MAIN constructed."""

    def __init__(self, path, g, flat):
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        ib = pe.OPTIONAL_HEADER.ImageBase
        size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, size)
        uc.mem_write(ib, bytes(flat[:size]))
        uc.mem_map(0, 0x10000)                       # fs:[0] (SEH chain reads; fs base 0)
        uc.mem_map(STACK, 0x400000)
        uc.mem_map(HEAP, 0x8000000)
        uc.mem_map(STUBS, 0x10000)
        self.heap, self.sizes, self.h = HEAP + 0x1000, {}, 0x1000
        self.dcs, self.bms, self.stretch, self.unknown = {}, {}, [], []
        self.END = STUBS + 0xFFF0
        uc.mem_write(self.END, b"\xF4")
        self.imports = {}
        n = 0
        for e in pe.DIRECTORY_ENTRY_IMPORT:
            for i in e.imports:
                stub = STUBS + 0x10 * n
                n += 1
                uc.mem_write(i.address, struct.pack("<I", stub))
                self.imports[stub] = (i.name or b"?").decode()
        uc.hook_add(UC_HOOK_CODE, self._stub, begin=STUBS, end=STUBS + 0xFF00)
        uc.hook_add(UC_HOOK_CODE, self._crt, begin=MALLOC, end=MALLOC)
        uc.hook_add(UC_HOOK_CODE, self._crt, begin=FREE, end=FREE)
        self.w32(G_ADDR, g)
        self.w32(STRIPE_PERIOD, SL.stripe_period(g) if g > 16 else 2)

    # -- memory --
    def rd(self, a, n=1):
        return struct.unpack("<%di" % n, bytes(self.uc.mem_read(a, 4 * n)))

    def w32(self, a, *v):
        self.uc.mem_write(a, struct.pack("<%di" % len(v), *v))

    def alloc(self, n):
        a = self.heap
        self.heap += (n + 0x1F) & ~0xF
        self.uc.mem_write(a, bytes(n))
        self.sizes[a] = n
        return a

    def args(self, k):
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<%dI" % k, bytes(self.uc.mem_read(esp + 4, 4 * k)))

    def _ret(self, eax, nargs):
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        self.uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        self.uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", self.uc.mem_read(esp, 4))[0])
        self.uc.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * nargs)

    def _crt(self, uc, addr, _size, _ud):
        if addr == MALLOC:
            self._ret(self.alloc(max(self.args(1)[0], 4)), 0)
        else:
            self._ret(0, 0)

    # -- Win32 --
    def _stub(self, uc, addr, _size, _ud):
        name = self.imports.get(addr)
        if name is None:
            return
        if name in TRIVIAL:
            self._ret(*TRIVIAL[name])
            return
        f = getattr(self, "i_" + name, None)
        if f is None:
            self.unknown.append(name)
            uc.emu_stop()
            return
        self._ret(*f())

    def _rect(self, p):
        return self.rd(p, 4)

    def newh(self):
        self.h += 4
        return self.h

    def i_IntersectRect(self):
        d, a, b = self.args(3)
        r1, r2 = self._rect(a), self._rect(b)
        r = (max(r1[0], r2[0]), max(r1[1], r2[1]), min(r1[2], r2[2]), min(r1[3], r2[3]))
        ok = int(r[0] < r[2] and r[1] < r[3])
        self.w32(d, *(r if ok else (0, 0, 0, 0)))
        return ok, 3

    def i_SetRect(self):
        d, *v = self.args(5)
        self.w32(d, *map(_s32, v))
        return 1, 5

    def i_EqualRect(self):
        a, b = self.args(2)
        return int(self._rect(a) == self._rect(b)), 2

    def i_UnionRect(self):
        d, a, b = self.args(3)
        rs = [r for r in (self._rect(a), self._rect(b)) if r[0] < r[2] and r[1] < r[3]]
        r = (min(q[0] for q in rs), min(q[1] for q in rs), max(q[2] for q in rs), max(q[3] for q in rs)) if rs else (0, 0, 0, 0)
        self.w32(d, *r)
        return int(bool(rs)), 3

    def i_OffsetRect(self):
        p, dx, dy = self.args(3)
        r = self._rect(p)
        self.w32(p, r[0] + _s32(dx), r[1] + _s32(dy), r[2] + _s32(dx), r[3] + _s32(dy))
        return 1, 3

    def i_IsRectEmpty(self):
        r = self._rect(self.args(1)[0])
        return int(r[0] >= r[2] or r[1] >= r[3]), 1

    def i_HeapAlloc(self):
        return self.alloc(max(self.args(3)[2], 4)), 3

    def i_HeapReAlloc(self):
        _h, _f, p, n = self.args(4)
        a = self.alloc(max(n, 4))
        if p:
            self.uc.mem_write(a, bytes(self.uc.mem_read(p, min(self.sizes.get(p, 0), n))))
        return a, 4

    def i_HeapSize(self):
        return self.sizes.get(self.args(3)[2], 0), 3

    def i_VirtualAlloc(self):
        a, n, _t, _p = self.args(4)
        if a:
            return a, 4
        self.heap = (self.heap + 0xFFFF) & ~0xFFFF
        return self.alloc(n), 4

    def i_CreateCompatibleDC(self):
        return self.newh(), 1

    def i_CreateRectRgnIndirect(self):
        return self.newh(), 1

    def i_CreateDIBSection(self):
        _hdc, pbmi, _u, ppv, _s, _o = self.args(6)
        _sz, w, h = struct.unpack("<Iii", bytes(self.uc.mem_read(pbmi, 12)))
        assert struct.unpack("<H", bytes(self.uc.mem_read(pbmi + 14, 2)))[0] == 8
        bits = self.alloc(((w + 3) & ~3) * abs(h) + 16)
        self.w32(ppv, bits)
        return self.newh(), 6

    def i_SelectObject(self):
        return self.newh(), 2

    def i_StretchBlt(self):                       # a chrome frame fell off the band map: recorded, nothing drawn
        self.stretch.append(tuple(map(_s32, self.args(11))))
        return 1, 11

    # -- engine --
    def call(self, fn, ecx=None, args=()):
        uc = self.uc
        esp = STACK + 0x380000
        for v in reversed(args):
            esp -= 4
            uc.mem_write(esp, struct.pack("<I", v & 0xFFFFFFFF))
        esp -= 4
        uc.mem_write(esp, struct.pack("<I", self.END))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_EBP, STACK + 0x390000)
        if ecx is not None:
            uc.reg_write(UC_X86_REG_ECX, ecx)
        uc.emu_start(fn, self.END, count=200_000_000)
        assert not self.unknown, self.unknown
        assert uc.reg_read(UC_X86_REG_EIP) == self.END
        return uc.reg_read(UC_X86_REG_EAX)

    def buffer_at(self, addr, w, h):
        self.call(BUF_CTOR, ecx=addr)
        self.call(BUF_INIT, ecx=addr, args=(w, h, 0, 0))

    def plane(self, buf):
        data = self.rd(buf + 0x54)[0] & 0xFFFFFFFF
        return data, self.rd(buf + 0x4A8)[0], self.rd(buf + 0x80)[0], -self.rd(buf + 0x84)[0]

    def rows(self, buf=MAIN):
        data, pitch, w, h = self.plane(buf)
        raw = bytes(self.uc.mem_read(data, pitch * h))
        return [raw[y * pitch:y * pitch + w] for y in range(h)]

    def load_boxsets(self, pcx):
        w, h, px = pcx
        self.buffer_at(PCX_BUF, w, h)
        data, pitch, _w, _h = self.plane(PCX_BUF)
        for y in range(h):
            self.uc.mem_write(data + y * pitch, px[y * w:(y + 1) * w])
        for b in range(FILLBUF_LO, FILLBUF_HI, 0x588):
            self.call(BUF_CTOR, ecx=b)
        self.uc.reg_write(UC_X86_REG_ESP, STACK + 0x380000)
        self.uc.reg_write(UC_X86_REG_EBP, STACK + 0x380100)
        self.uc.emu_start(LOADER_LO, LOADER_HI, count=100_000_000)
        assert not self.unknown and self.uc.reg_read(UC_X86_REG_EIP) == LOADER_HI

    def chrome(self, regs, stop, start=CHROME):
        if start == CHROME:                          # (a resumed run keeps the painter's own state: S.L is L - s(7) now)
            for k, off in (("L", 0x20), ("R", 0x30), ("S", 0x40), ("C", 0x50)):
                self.w32(RI + off, *regs[k])
            self.uc.reg_write(UC_X86_REG_ESP, STACK + 0x380000)
            self.uc.reg_write(UC_X86_REG_ECX, RI)
        self.uc.emu_start(start, stop, count=400_000_000)
        assert not self.unknown, self.unknown
        assert self.uc.reg_read(UC_X86_REG_EIP) == stop


# ---- fixtures ----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def baked(baked_exe):
    return str(baked_exe)


@pytest.fixture(scope="module")
def pcx():
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("PIL not installed")
    p = config.game_dir(required=False) / "interface.pcx"
    if not p.is_file():
        pytest.skip(f"interface.pcx not found at {p}")
    im = Image.open(p)
    w, h = im.size
    return w, h, bytes((b + 10) & 0xFF for b in im.tobytes())     # the canvas manager's +10 index remap


@functools.lru_cache(maxsize=None)
def _flat(path, g):
    if g <= 16:
        pe = pefile.PE(path, fast_load=True)
        size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        return bytes(pe.get_memory_mapped_image()[:size]).ljust(size, b"\0")
    flat, _vps, faults = walk(Img(path), g)
    assert flat is not None and not faults, faults
    return flat


def _ready(path, g, pcx):
    c = Chrome(path, g, _flat(path, g))
    c.load_boxsets(pcx)
    c.buffer_at(MAIN, 1024 * g // 16, 262 * g // 16)
    data, pitch, _w, h = c.plane(MAIN)
    c.uc.mem_write(data, b"\xFE" * (pitch * h))
    return c


def _runs(seq, c):
    out, y = [], 0
    while y < len(seq):
        if seq[y] == c:
            y0 = y
            while y < len(seq) and seq[y] == c:
                y += 1
            out.append((y0, y))
        else:
            y += 1
    return out


# ---- 1. the whole chrome: strokes, channels, no GDI -------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_strip_frame_strokes_follow_the_law(baked, pcx, g):
    rnd = random.Random(g)
    for jitter in (None, (rnd.randrange(-3, 4), rnd.randrange(-3, 4), rnd.randrange(-5, 6), rnd.randrange(-3, 4))):
        regs = regions(g, jitter)
        c = _ready(baked, g, pcx)
        c.chrome(regs, CHROME_STOP)
        assert not c.stretch, f"g{g}: a console frame fell off the band map onto GDI StretchBlt {c.stretch}"
        rows = c.rows()
        law = SL.rw_strip_frame(regs["S"], g)
        L, T, R, B = regs["S"]
        bad = []
        for x in (L + (R - L) // 5, (L + R) // 2, R - (R - L) // 5):
            col = [r[x] for r in rows]
            da = [rn for rn in _runs(col, DA50) if T - 4 <= rn[0] <= B + 4]
            d5 = [rn for rn in _runs(col, D5A0) if T <= rn[0] < B]
            if da != [law["top"], law["bottom"]]:
                bad.append(f"x{x}: da50 rows {da} != top {law['top']} / bottom {law['bottom']}")
            elif d5 and (d5[0][0] - law["top"][1], law["bottom"][0] - d5[-1][1]) != (law["channel_top"], law["channel_bottom"]):
                bad.append(f"x{x}: channels T/B {d5[0][0] - law['top'][1]}/{law['bottom'][0] - d5[-1][1]} != law")
        for y in (T + (B - T) // 3, (T + B) // 2, B - (B - T) // 3):
            row = rows[y]
            da = [rn for rn in _runs(row, DA50) if R - 40 <= rn[0] <= R + 4]
            d5 = [rn for rn in _runs(row, D5A0) if R - 40 <= rn[0] < R]
            if da != [law["right"]]:
                bad.append(f"y{y}: da50 right cols {da} != {law['right']}")
            elif not d5 or law["right"][0] - d5[-1][1] != law["channel_right"]:
                bad.append(f"y{y}: right channel {law['right'][0] - d5[-1][1] if d5 else None} != {law['channel_right']}")
        # symmetric, and the strip's bottom stroke is the left panel's (both end on the console's bottom row)
        assert law["channel_top"] == law["channel_bottom"] == law["channel_right"]
        if regs["S"][3] == regs["L"][3]:
            xl = (regs["L"][0] + regs["L"][2]) // 2
            pan = [rn for rn in _runs([r[xl] for r in rows], DA50) if rn[0] > regs["L"][1] + 4]
            if pan[-1:] != [law["bottom"]]:
                bad.append(f"left panel bottom stroke {pan[-1:]} != strip bottom {law['bottom']}")
        assert not bad, f"g{g} S={regs['S']}: " + "; ".join(bad)


# ---- 2. nothing outside the strip changes; inside == the panels' own (unclipped) path ----------------------------
@pytest.mark.parametrize("g", (17, 22, 23, 25, 28, 39, 40))
def test_strip_frame_keeps_the_hidden_band_and_matches_boxforce(baked, pcx, g):
    regs = regions(g)
    strip = SL.rw_strip_anchor(regs["S"], regs["L"], g)       # fix 9: the strip draws from the panel's stroke
    c = _ready(baked, g, pcx)
    c.chrome(regs, STRIP_CALL)
    before = c.rows()
    esp = c.uc.reg_read(UC_X86_REG_ESP)
    rect, params = struct.unpack("<II", bytes(c.uc.mem_read(esp, 8)))
    frame = c.rd(rect, 4)
    assert frame == SL.rw_strip_frame(strip, g)["frame"]
    c.chrome(regs, STRIP_RET, start=STRIP_CALL)
    after = c.rows()
    assert c.rd(MAIN + 0x20, 4) == strip, "the strip clip must survive the draw"
    # the ideal: t_rwk_boxforce on the same frame with the clip opened to the whole canvas
    d = _ready(baked, g, pcx)
    d.chrome(regs, STRIP_CALL)
    d.w32(MAIN + 0x20, *d.rd(MAIN + 0x30, 4))
    d.call(Img(baked).sym["t_rwk_boxforce"], ecx=MAIN, args=(rect, params))
    ideal = d.rows()
    L, T, R, B = strip
    out_changed = [(x, y) for y in range(len(after)) for x in range(len(after[0]))
                   if not (L <= x < R and T <= y < B) and after[y][x] != before[y][x]]
    in_diff = [(x, y) for y in range(T, B) for x in range(L, R) if after[y][x] != ideal[y][x]]
    assert not out_changed, f"g{g}: pixels outside the strip changed: {out_changed[:8]} (of {len(out_changed)})"
    assert not in_diff, f"g{g}: strip interior differs from t_rwk_boxforce's draw: {in_diff[:8]} (of {len(in_diff)})"
    assert not c.stretch and not d.stretch


# ---- 3. t_rwk_stripframe alone ------------------------------------------------------------------------------------
class Thunk:
    """The baked image; t_rwk_boxforce and Buffer_box_sprite hooked: record (ecx, clip L at call time, rect, params)
    and paint the WHOLE rect (unclipped) with 0xAB, RET 8."""

    def __init__(self, path, g):
        img = Img(path)
        self.va = img.sym["t_rwk_stripframe"]
        self.bf = img.sym["t_rwk_boxforce"]
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(img.IB, img.size)
        uc.mem_write(img.IB, img.flat)
        uc.mem_map(STACK, 0x100000)
        uc.mem_map(HEAP, 0x400000)
        uc.mem_map(0x11223000, 0x1000)                 # the caller's return address (hlt)
        uc.mem_write(G_ADDR, struct.pack("<i", g))
        self.calls = []
        for tgt, tag in ((self.bf, "boxforce"), (BOX_SPRITE, "native")):
            uc.hook_add(UC_HOOK_CODE, self._hook, begin=tgt, end=tgt, user_data=tag)

    def _hook(self, uc, addr, _size, tag):
        esp = uc.reg_read(UC_X86_REG_ESP)
        ra, rect, params = struct.unpack("<III", bytes(uc.mem_read(esp, 12)))
        dest = uc.reg_read(UC_X86_REG_ECX)
        r = struct.unpack("<4i", bytes(uc.mem_read(rect, 16)))
        self.calls.append((tag, dest, struct.unpack("<i", bytes(uc.mem_read(dest + 0x20, 4)))[0], rect, params, ra))
        data = struct.unpack("<I", bytes(uc.mem_read(dest + 0x54, 4)))[0]
        pitch = struct.unpack("<i", bytes(uc.mem_read(dest + 0x4A8, 4)))[0]
        if data:
            for y in range(max(r[1], 0), r[3]):
                uc.mem_write(data + y * pitch + max(r[0], 0), b"\xAB" * (r[2] - max(r[0], 0)))
        for reg in (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX):
            uc.reg_write(reg, 0xDEAD0000 | reg)
        uc.reg_write(UC_X86_REG_EIP, ra)
        uc.reg_write(UC_X86_REG_ESP, esp + 12)

    def run(self, rect, clip, w=800, h=300, plane=True):
        uc = self.uc
        dest, data, rp = HEAP, HEAP + 0x1000, HEAP + 0x800
        uc.mem_write(dest, bytes(0x600))
        self.pattern = bytes((x * 7 + y * 13) & 0xFF or 1 for y in range(h) for x in range(w))
        uc.mem_write(data, self.pattern)
        for off, v in ((0x20, clip[0]), (0x24, clip[1]), (0x28, clip[2]), (0x2C, clip[3]),
                       (0x54, data if plane else 0), (0x4A8, w), (0x80, w), (0x84, -h)):
            uc.mem_write(dest + off, struct.pack("<i", v))
        uc.mem_write(rp, struct.pack("<4i", *rect))
        sp = STACK + 0x80000
        uc.mem_write(sp, struct.pack("<III", 0x11223344, rp, 0x78DA50))
        uc.mem_write(0x11223344, b"\xF4")
        regs = {UC_X86_REG_ECX: dest, UC_X86_REG_EBX: 0xB0B0B0B0, UC_X86_REG_ESI: 0x51515151,
                UC_X86_REG_EDI: 0xD1D1D1D1, UC_X86_REG_EBP: 0xBEBEBEBE, UC_X86_REG_ESP: sp}
        for k, v in regs.items():
            uc.reg_write(k, v)
        self.calls = []
        uc.emu_start(self.va, 0x11223344, count=2_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == 0x11223344
        assert uc.reg_read(UC_X86_REG_ESP) == sp + 12, "RET 8"
        for k in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert uc.reg_read(k) == regs[k]
        assert struct.unpack("<4i", bytes(uc.mem_read(rp, 16))) == tuple(rect), "the caller's rect is not touched"
        out = bytes(uc.mem_read(data, w * h))
        return dest, [out[y * w:(y + 1) * w] for y in range(h)], struct.unpack("<4i", bytes(uc.mem_read(dest + 0x20, 16)))


@pytest.fixture(scope="module")
def thunk40(baked):
    return Thunk(baked, 40)


def test_stripframe_native_at_g16(baked):
    t = Thunk(baked, 16)
    clip = (100, 50, 700, 210)
    dest, rows, clip_after = t.run((83, 50, 700, 210), clip)
    assert [c[0] for c in t.calls] == ["native"] and t.calls[0][2] == 100 and t.calls[0][1] == dest
    assert t.calls[0][4] == 0x78DA50 and clip_after == clip


def test_stripframe_saves_widens_and_restores(thunk40):
    clip = (100, 50, 700, 210)
    rect = (83, 50, 700, 210)
    dest, rows, clip_after = thunk40.run(rect, clip)
    assert len(thunk40.calls) == 1
    tag, d, clip_l_seen, _rect, params, _ra = thunk40.calls[0]
    assert (tag, d, clip_l_seen, params) == ("boxforce", dest, 83, 0x78DA50), thunk40.calls
    assert clip_after == clip, "clip edge restored"
    w = 800
    for y in range(300):
        for x in range(w):
            p = thunk40.pattern[y * w + x]
            if 50 <= y < 210 and 83 <= x < 100:
                assert rows[y][x] == p, (x, y, "hidden band not restored")
            elif 50 <= y < 210 and 100 <= x < 700:
                assert rows[y][x] == 0xAB, (x, y, "the draw itself was undone")
            else:
                assert rows[y][x] == p, (x, y, "outside the frame")


def test_stripframe_band_flush_with_the_plane_bottom(thunk40):
    """B == |H| (the strip ends on the canvas's last row) is in bounds: saved, widened, restored -- not the fall-back.
    Kills `jg` -> `jge` on the bottom check (B + [dest+0x84] = B - |H| > 0 is the only off-plane case)."""
    clip, rect, w, h = (100, 250, 700, 300), (83, 250, 700, 300), 800, 300
    dest, rows, clip_after = thunk40.run(rect, clip, w=w, h=h)
    assert len(thunk40.calls) == 1
    tag, d, clip_l_seen, _rect, params, _ra = thunk40.calls[0]
    assert (tag, d, clip_l_seen, params) == ("boxforce", dest, 83, 0x78DA50), thunk40.calls
    assert clip_after == clip, "clip edge restored"
    for y in range(h):
        for x in range(w):
            p = thunk40.pattern[y * w + x]
            if 250 <= y < 300 and 83 <= x < 100:
                assert rows[y][x] == p, (x, y, "hidden band not restored")
            elif 250 <= y < 300 and 100 <= x < 700:
                assert rows[y][x] == 0xAB, (x, y, "the draw itself was undone")
            else:
                assert rows[y][x] == p, (x, y, "outside the frame")


@pytest.mark.parametrize("why, rect, clip, kw", [
    ("no hidden band", (100, 50, 700, 210), (100, 50, 700, 210), {}),
    ("frame right of its clip", (110, 50, 700, 210), (100, 50, 700, 210), {}),
    ("frame left of the plane", (-5, 50, 700, 210), (12, 50, 700, 210), {}),
    ("frame above the plane", (83, -1, 700, 100), (100, 0, 700, 100), {}),          # (each band under the cap:
    ("frame below the plane", (83, 250, 700, 301), (100, 250, 700, 300), {}),       #  the case's own check decides)
    ("empty height", (83, 50, 700, 50), (100, 50, 700, 210), {}),
    ("band over the save area", (83, 0, 700, SL.RW_STRIP_SAVE_CAP // 17 + 1), (100, 0, 700, 300), {}),
    ("no plane", (83, 50, 700, 210), (100, 50, 700, 210), {"plane": False}),
])
def test_stripframe_falls_back_to_boxforce_under_the_clip(thunk40, why, rect, clip, kw):
    dest, rows, clip_after = thunk40.run(rect, clip, **kw)
    assert len(thunk40.calls) == 1, why
    tag, d, clip_l_seen, _r, params, _ra = thunk40.calls[0]
    assert (tag, d, clip_l_seen, params) == ("boxforce", dest, clip[0], 0x78DA50), (why, thunk40.calls)
    assert clip_after == clip, why
    if kw.get("plane", True):
        # nothing restored: the (unclipped) draw stands wherever it painted
        y = max(rect[1], 0)
        if rect[3] > rect[1] and rect[1] >= 0:
            assert rows[y][max(rect[0], 0)] == 0xAB, why


def test_stripframe_save_area_boundary(thunk40):
    """w * h == RW_STRIP_SAVE_CAP is saved and restored; one more row is the fall-back."""
    w = 16
    h = SL.RW_STRIP_SAVE_CAP // w
    assert w * h == SL.RW_STRIP_SAVE_CAP
    _d, rows, _c = thunk40.run((100 - w, 10, 700, 10 + h), (100, 10, 700, 10 + h))
    assert thunk40.calls[0][2] == 100 - w
    assert all(rows[y][x] == thunk40.pattern[y * 800 + x] for y in range(10, 10 + h) for x in range(100 - w, 100))
    _d, rows, _c = thunk40.run((100 - w, 10, 700, 11 + h), (100, 10, 700, 11 + h))
    assert thunk40.calls[0][2] == 100
    assert SL.RW_STRIP_SAVE_CAP + 1 == 7 * 439                       # one byte over: 7 x 439 falls back
    _d, rows, _c = thunk40.run((93, 10, 700, 449), (100, 10, 700, 449), h=460)
    assert thunk40.calls[0][2] == 100


# ---- 4. the law alone ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", range(12, 49))
def test_rw_strip_frame_law(g):
    region = (244 * g // 16, 188 * g // 16, 768 * g // 16, 252 * g // 16)
    law = SL.rw_strip_frame(region, g)
    L, T, R, B = region
    k = SL.stroke_width(g) if g > 16 else 1
    if g <= 16:                                               # vanilla: L - 7, 1-px strokes, channels 3
        assert law["frame"] == (L - 7, T, R, B) and law["channel_top"] == 3
    else:
        assert law["frame"] == (L - SL.scale_px(7, g), T, R, B)
    assert law["hidden"] == (law["frame"][0], T, L, B)
    assert (law["top"], law["bottom"], law["right"]) == ((T, T + k), (B - k, B), (R - k, R))
    assert law["channel_top"] == law["channel_bottom"] == law["channel_right"] >= 1
    # the hidden band always fits t_rwk_stripframe's save area on the supported range (g clamps to 40)
    if g <= 40:
        assert (L - law["frame"][0]) * (B - T) <= SL.RW_STRIP_SAVE_CAP


# ---- 4. fix 9: the strip's left junction = the left panel's right stroke (law rw_strip_anchor) -------------------------
CHROME_RESTORED = 0x4A3F54          # the painter's region restores done (strip, centre, panels)
# the real screens (g, canvas W x H, console offset): the console window sits at ((W - fl(1024g/16)) / 2,
# H - fl(257g/16)) on MainWin's W x H canvas (fix 12 / N1: the fix-9 list carried offsets measured off the wrong
# rows -- 789/790, 731/732, 288/586, 950, 733 -- that no screen produces)
REAL = [(25, 1600, 1200, 0, 799), (22, 1920, 1080, 256, 727), (40, 3840, 2160, 640, 1518), (18, 1600, 900, 224, 611),
        (30, 3440, 1440, 760, 959), (22, 2560, 1080, 576, 727)]
LOCAL_GS = (16, 18, 22, 23, 25, 28, 30, 39, 40)      # the window-local canvas: fl(1024g/16) x fl(257g/16) at (0, 0)


def console_origin(g, w, h):
    return (w - 1024 * g // 16) // 2, h - 257 * g // 16


def test_real_placements_are_the_console_origin():
    for g, w, h, ox, oy in REAL:
        assert SL.popup_g(w, h) == g and console_origin(g, w, h) == (ox, oy), (g, w, h, ox, oy)


def _ready_at(path, g, pcx, canvas):
    c = Chrome(path, g, _flat(path, g))
    c.load_boxsets(pcx)
    c.buffer_at(MAIN, *canvas)
    data, pitch, _w, h = c.plane(MAIN)
    c.uc.mem_write(data, b"\xFE" * (pitch * h))
    return c


def _placed(g, off):
    return {k: (r[0] * g // 16 + off[0], r[1] * g // 16 + off[1], r[2] * g // 16 + off[0], r[3] * g // 16 + off[1])
            for k, r in NAT.items()}


def _junction(rows, regs, g):
    """(left gap, T channel, B channel, R channel, residue pixels) measured on the canvas."""
    L, T, R, B = regs["S"]
    Lp = regs["L"]
    K = SL.stroke_width(g) if g > 16 else 1
    gaps, chans, residue = set(), set(), []
    for x in (L + (R - L) // 3, (L + R) // 2):
        col = [r[x] for r in rows]
        da = [rn for rn in _runs(col, DA50) if T - 4 <= rn[0] <= B + 4]
        d5 = [rn for rn in _runs(col, D5A0) if T <= rn[0] < B]
        chans.add(("T", d5[0][0] - da[0][1]))
        chans.add(("B", da[-1][0] - d5[-1][1]))
    for y in range(T + K, B - K):
        row = rows[y]
        d5 = [rn for rn in _runs(row, D5A0) if Lp[0] < rn[0] < R]
        pan = [rn for rn in d5 if rn[1] <= Lp[2]]
        nxt = [rn for rn in d5 if pan and rn[0] >= pan[-1][1]]
        # no da50 from the panel's d5a0 (R - s3) to the strip's interior (the strip's own left stroke is in its hidden
        # band; in vanilla the strip covers the panel's right stroke on every row between its top and bottom strokes)
        s3, s4 = (SL.scale_px(3, g), SL.scale_px(4, g)) if g > 16 else (3, 4)
        residue += [(x, y) for x in range(Lp[2] - s3, max(L, Lp[2]) + s4) if row[x] == DA50]
        if T + (B - T) // 4 <= y < B - (B - T) // 4:
            assert pan and nxt, f"g{g} row {y}: no panel / strip d5a0 ({d5[:4]})"
            gaps.add(nxt[0][0] - pan[-1][1])
            da = [rn for rn in _runs(row, DA50) if R - 40 <= rn[0] <= R + 4]
            chans.add(("R", da[-1][0] - d5[-1][1]))
    return gaps, chans, residue


def _check_junction(baked, pcx, g, canvas, off):
    regs = _placed(g, off)
    c = _ready_at(baked, g, pcx, canvas)
    c.chrome(regs, CHROME_STOP)
    assert not c.stretch, f"g{g}: a console frame fell off the band map onto GDI StretchBlt {c.stretch}"
    rows = c.rows()
    K = SL.stroke_width(g) if g > 16 else 1
    law = SL.scale_px(4, g) - K if g > 16 else 3
    A, T, R, B = SL.rw_strip_anchor(regs["S"], regs["L"], g)
    assert A == regs["L"][2] - K, "the strip's left edge is the panel stroke's first column"
    gaps, chans, residue = _junction(rows, regs, g)
    assert gaps == {law}, f"g{g} {canvas}+{off}: d5a0 -> d5a0 gap {sorted(gaps)} != s(4) - K = {law}"
    assert {v for _k, v in chans} == {law}, f"g{g}: T/B/R channels {sorted(chans)} != {law}"
    assert not residue, f"g{g}: {len(residue)} da50 px between the d5a0s, cols {sorted({x for x, _ in residue})}"
    # the strip's top stroke starts ON the panel stroke (a T junction, no spur left of it); the bottom stroke is whole
    for y in range(T, T + K):
        assert rows[y][A - 1] != DA50 and rows[y][A:A + K] == bytes([DA50]) * K, (g, y, rows[y][A - 2:A + K + 1].hex())
    for y in range(B - K, B):
        assert rows[y][A - 1:A + K + 1] == bytes([DA50]) * (K + 2), (g, y, rows[y][A - 2:A + K + 2].hex())
    # and the region the kind tabs read is the region again once the painter's restores ran
    c.chrome(regs, CHROME_RESTORED, start=CHROME_STOP)
    assert {k: c.rd(RI + o, 4) for k, o in (("L", 0x20), ("R", 0x30), ("S", 0x40), ("C", 0x50))} == regs
    return rows


@pytest.mark.parametrize("g", range(16, 41))
def test_strip_left_junction_scaling_follows_the_panel_stroke(baked, pcx, g):
    _check_junction(baked, pcx, g, (1024 * g // 16, 262 * g // 16), (0, 0))


@pytest.mark.parametrize("g, w, h, ox, oy", REAL)
def test_strip_left_junction_scaling_real_screens(baked, pcx, g, w, h, ox, oy):
    _check_junction(baked, pcx, g, (w, h), (ox, oy))


@pytest.mark.parametrize("g", LOCAL_GS)
def test_strip_left_junction_scaling_window_local(baked, pcx, g):
    """The console window's own canvas, fl(1024g/16) x fl(257g/16), regions at (0, 0)."""
    _check_junction(baked, pcx, g, (1024 * g // 16, 257 * g // 16), (0, 0))


def test_strip_left_junction_g16_is_the_pristine_chrome(baked, bak_path, pcx):
    rows = _check_junction(baked, pcx, 16, (1024, 262), (0, 0))
    p = _ready(str(bak_path), 16, pcx)
    p.chrome(regions(16), CHROME_STOP)
    assert p.rows() == rows, "g=16 must be vanilla's chrome, byte for byte"


# ---- 5. t_rwk_stripanchor alone -----------------------------------------------------------------------------------
ANCHOR_SITE, ANCHOR_RESUME = 0x4A3D65, 0x4A3D6D


@pytest.fixture(scope="module")
def anchor_img(baked):
    return Img(baked)


@pytest.mark.parametrize("g", (12, 16, 17, 22, 23, 24, 25, 28, 39, 40, 41, 48))
def test_stripanchor_thunk(anchor_img, g):
    img = anchor_img
    scr = img.sym["g_rw_strip_rect"]
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(img.IB, img.size)
    uc.mem_write(img.IB, img.flat)
    uc.mem_map(STACK, 0x100000)
    uc.mem_write(G_ADDR, struct.pack("<i", g))
    panel, strip = (11, 101, 383 + g, 401), (380 + g, 301, 1211, 402)        # arbitrary: the law reads panel R only
    uc.mem_write(RI + 0x20, struct.pack("<4i", *panel))
    uc.mem_write(RI + 0x40, struct.pack("<4i", *strip))
    uc.mem_write(scr, struct.pack("<4I", *[0x5C5C5C5C] * 4))
    sp = STACK + 0x80000
    regs = {UC_X86_REG_ESI: RI, UC_X86_REG_EDI: RI + 0x50, UC_X86_REG_EBX: RI + 0x20, UC_X86_REG_EBP: 0xBEBEBEBE,
            UC_X86_REG_ECX: 0x12345678, UC_X86_REG_ESP: sp}
    for k, v in regs.items():
        uc.reg_write(k, v)
    uc.emu_start(ANCHOR_SITE, ANCHOR_RESUME, count=10_000)
    assert uc.reg_read(UC_X86_REG_EIP) == ANCHOR_RESUME
    assert uc.reg_read(UC_X86_REG_ECX) == MAIN, "the displaced mov ecx, MAIN"
    for k in (UC_X86_REG_EDI, UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ESP):
        assert uc.reg_read(k) == regs[k]
    assert struct.unpack("<4i", bytes(uc.mem_read(RI + 0x40, 16))) == strip, "ReportIf+0x40 is never written"
    got = struct.unpack("<4i", bytes(uc.mem_read(scr, 16)))
    if g <= 16:
        assert uc.reg_read(UC_X86_REG_ESI) == RI + 0x40, "native: esi = the region itself"
        assert got == (0x5C5C5C5C,) * 4, "native: the cell is not touched"
    else:
        assert uc.reg_read(UC_X86_REG_ESI) == scr
        assert got == SL.rw_strip_anchor(strip, panel, g) == (panel[2] - SL.stroke_width(g),) + strip[1:]


@pytest.mark.parametrize("g", range(12, 49))
def test_rw_strip_anchor_law(g):
    """the junction on the law alone: gap == the strip's T/B/R channel, the panel stroke inside the strip, vanilla at 16."""
    panel = tuple(v * g // 16 for v in NAT["L"])
    region = tuple(v * g // 16 for v in NAT["S"])
    A, T, R, B = SL.rw_strip_anchor(region, panel, g)
    assert (T, R, B) == region[1:]
    if g <= 16:
        assert (A, T, R, B) == region                          # native: the region itself
        if g == 16:
            assert region[0] == panel[2] - 1                   # vanilla's seeds: the strip starts on the panel's last column
        return
    K = SL.stroke_width(g)
    assert A == panel[2] - K                                   # the panel stroke [Rp-K, Rp) = the strip's first K cols
    s3, s4 = SL.scale_px(3, g), SL.scale_px(4, g)
    gap = (A + s4 - s3) - (panel[2] - s3)                      # strip d5a0 L (chrome L + s4 - s3) - panel d5a0 R (Rp - s3)
    assert gap == SL.rw_strip_frame((A, T, R, B), g)["channel_right"] == s4 - K
    assert abs(A - region[0]) <= 1                             # within one px of the seed's own floor


# ---- 6. fix 12 / N3: the kind tabs anchor on the strip's DRAWN left edge (law rw_kind_tab_x) ---------------------------
D528 = 0x22


@pytest.mark.parametrize("g", range(16, 41))
def test_kind_tab_to_d528_margin_is_vanilla_x_g16(baked, pcx, g):
    """The first kind tab's margin to the strip's d528 (its first column, measured on the baked chrome) is vanilla's 13
    (tab L + 17 vs the d528 at L + 4) x g/16 to within 1 px at every g.  With the tabs on the region's L (fix 9) the
    drawn edge moved under them by 1 at g = 23 / 25 / 28 / 39 and the margin missed by 1.7 / 1.7 / 1.25 / 1.7."""
    regs = _placed(g, (0, 0))
    c = _ready_at(baked, g, pcx, (1024 * g // 16, 262 * g // 16))
    c.chrome(regs, CHROME_STOP)
    rows = c.rows()
    _L, T, _R, B = regs["S"]
    A = SL.rw_strip_anchor(regs["S"], regs["L"], g)[0]
    cols = {next(x for x in range(A, A + 40) if rows[y][x] == D528) for y in range(T + (B - T) // 4, B - (B - T) // 4)}
    assert len(cols) == 1, f"g{g}: the d528's first column is not one x: {sorted(cols)}"
    tabs = [SL.rw_kind_tab_x(i, regs["S"], regs["L"], g) for i in range(7)]
    margin = tabs[0] - cols.pop()
    assert abs(margin - 13 * g / 16) < 1, f"g{g}: tab -> d528 margin {margin} vs vanilla x g/16 = {13 * g / 16}"
    if g <= 16:
        assert margin == 13 and tabs == [regs["S"][0] + 17 + 42 * i for i in range(7)]
    else:
        assert [t - tabs[0] for t in tabs] == [SL.scale_px(17 + 42 * i, g) - SL.scale_px(17, g) for i in range(7)]
