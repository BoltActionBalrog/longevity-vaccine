"""Unicorn parity of the W2D edge-stroke / notch / FileDlg-pair thunks (2026-10-25 wave 2; src
scripts\\assemble_edge_stroke.py) against their laws in scaling_laws.py, on the REAL bytes of the conftest bake:

  t_btn_edgeprobe     == btn_edge_probe      (the native face's four 1-px strokes; the stretch entered on the caller's
                                              frame, callee-saved registers kept, g_btn_tileH zeroed)
  t_btn_edgeband      == btn_edge_band       (after thunk_btn_ringfix: K bands on rows [0, D), key pixels kept)
  t_fac_rowbox + t_fac_item_pre + t_fac_rowpost == faction_row_face (bands + notches under the row's text ink,
                                              the restripe, the stroke's mate back; the ink survives)
  thunk_filedlg_rects v2 == popup_scale of [1..8] + filedlg_btn_pair on [9..16] ([0] untouched; g <= 16 untouched)

Only the engine primitives the thunks call are stand-ins (hooks): thunk_btn_bandstripe / thunk_btn_ringfix /
Buffer_box_sprite / t_lbi_restripe_ph / ListBox_draw_item / FileDlg_build_widgets.  Every case is swept over g 16..40
(the thunks gate on g; g <= 16 must be the vanilla path).  Plus: the yaml bytes are the assembler's templates.

COST: one image map per module (~1 s); the sweeps are pure Unicorn on small canvases (~10 s serial in all).
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
KEY = 9
BTN, PLANE, SPRITE, STK, RET, ARR, PARAMS = 0x10000000, 0x10100000, 0x10300000, 0x10380000, 0x103F0000, 0x10390000, \
    0x103A0000
STRIDE = 1024
CALLEE = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


@pytest.fixture(scope="module")
def loaded():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = ap.build_symbol_table(symbols, caves)
    contents = {e["id"]: " ".join(str(e["bytes"]).split()) for c in caves for e in (c.get("contents") or [])}
    return sym, contents


class Img:
    """The baked image mapped once; stand-ins are hooks at the callee entries (`stops`)."""

    def __init__(self, path, sym):
        pe = pefile.PE(str(path))
        ib = pe.OPTIONAL_HEADER.ImageBase
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        pe.close()
        mu.mem_map(0x10000000, 0x400000)
        self.sym = sym
        self.stub = {}
        self.calls = []
        mu.hook_add(UC_HOOK_CODE, self._hook)

    def _hook(self, mu, addr, size, _u):
        fn = self.stub.get(addr)
        if fn is not None:
            fn(self)

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def plane(self, h, w):
        import numpy as np
        return np.frombuffer(bytes(self.mu.mem_read(PLANE, STRIDE * h)), np.uint8).reshape(h, STRIDE)[:, :w].copy()

    def put_plane(self, rows, fill=0x77, h=None):
        import numpy as np
        h = h or len(rows)
        full = np.full((h, STRIDE), fill, np.uint8)
        for y, r in enumerate(rows):
            full[y, :len(r)] = r
        self.mu.mem_write(PLANE, full.tobytes())

    def run(self, entry, frame, regs=None, count=5_000_000):
        mu = self.mu
        self.mu.mem_write(STK, b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in frame))
        mu.mem_write(RET, b"\xF4")
        base = {UC_X86_REG_EAX: 0x5A5A0001, UC_X86_REG_EBX: 0x5A5A0002, UC_X86_REG_ECX: 0x5A5A0003,
                UC_X86_REG_EDX: 0x5A5A0004, UC_X86_REG_EDI: 0x5A5A0006, UC_X86_REG_EBP: 0x5A5A0007,
                UC_X86_REG_ESI: 0x5A5A0005}
        base.update(regs or {})
        for r, v in base.items():
            mu.reg_write(r, v)
        mu.reg_write(UC_X86_REG_ESP, STK)
        mu.emu_start(entry, RET, count=count)
        return base


def _ret(img, nbytes, eax=None):
    mu = img.mu
    sp = mu.reg_read(UC_X86_REG_ESP)
    ra = img.r32(sp) & 0xFFFFFFFF
    mu.reg_write(UC_X86_REG_ESP, sp + 4 + nbytes)
    if eax is not None:
        mu.reg_write(UC_X86_REG_EAX, eax)
    mu.reg_write(UC_X86_REG_EIP, ra)


@pytest.fixture(scope="module")
def img(baked_exe, loaded):
    return Img(Path(baked_exe), loaded[0])


# ============================================================================== yaml == assembler
def test_yaml_bytes_are_the_assembler_templates(loaded):
    import assemble_edge_stroke as ES
    _sym, contents = loaded
    for name, (off, _n, tpl) in ES.build().items():
        assert contents[name] == tpl, name
        assert _sym[name] == ES.PCAVE2 + off, name
    for name, off in ES.CELLS.items():
        assert _sym[name] == ES.PCAVE2 + off
        assert contents[name] == " ".join(["00"] * ES.CELL_LEN.get(name, 4)), name


# ============================================================================== t_btn_edgeprobe
def _face(state, w, h=20):
    """The default 9-slice face as measured on the real image at g = 16 (lobby LAUNCH GAME, census in scaling_laws)."""
    rows = []
    for y in range(h):
        if state == 0:
            c = 0xAE if y % 2 == 0 else 0xEE
            r = [c] * w
        elif state == 2:
            c = 0xE1 if y % 2 == 0 else 0xE0
            r = [c] * w
        else:
            c = 0xEE if y % 2 else 0xAE
            r = [0xE0] * w if y in (0, h - 1) else [0xE0] + [c] * (w - 2) + [0xE0]
        if y in (0, h - 1):
            r[0] = r[-1] = KEY
        rows.append(r)
    return rows


def _probe_faces():
    rnd = random.Random(39)
    faces = [(_face(s, w), 20, 20) for s in (0, 1, 2) for w in (6, 61, 236)]
    faces += [(_face(1, 61, 22)[:20] + [[KEY] * 61] * 2, 22, 20)]          # 22-native window, 20-row art on top
    for _ in range(60):
        w, h = rnd.randint(4, 40), rnd.randint(4, 30)
        art_h = rnd.randint(3, 34)
        pal = [rnd.choice((KEY, 0xE0, 0xE1, 0xAE, 0xEE, 0x41)) for _ in range(6)]
        rows = [[rnd.choice(pal) for _ in range(w)] for _ in range(h)]
        faces.append((rows, h, art_h))
    return faces


def _run_probe(img, rows, native_h, art_h, captured=True):
    sym = img.sym
    w = len(rows[0])
    img.put_plane(rows)
    img.w32(sym["g_btn_fill_sprite"], SPRITE if captured else 0)
    img.w32(SPRITE + 0x1C, art_h)
    img.w32(sym["g_btn_nativeW"], w)
    img.w32(sym["g_btn_nativeH"], native_h)
    img.w32(sym["g_btn_tileH"], 0x1234)
    img.w32(sym["g_btn_edge_mask"], 0xFFFFFFFF)
    for i in range(4):
        img.w32(sym[f"g_btn_edge_c{i}"], 0x33)
    img.w32(BTN + 0x498, PLANE)
    img.w32(BTN + 0x8EC, STRIDE)
    seen = {}

    def bandstripe(img):
        mu = img.mu
        sp = mu.reg_read(UC_X86_REG_ESP)
        seen.update(esp=sp, frame=bytes(mu.mem_read(sp, 48)), regs={r: mu.reg_read(r) for r in CALLEE})
        _ret(img, 0x2C)
    img.stub = {sym["thunk_btn_bandstripe"]: bandstripe}
    frame = [RET] + [0x7000 + i for i in range(11)]
    regs = img.run(sym["t_btn_edgeprobe"], frame, {UC_X86_REG_ESI: BTN})
    assert seen, "thunk_btn_bandstripe entered"
    assert seen["esp"] == STK and seen["frame"] == b"".join(struct.pack("<I", v) for v in frame), "the caller's frame"
    assert seen["regs"] == {r: regs[r] for r in CALLEE}, "ebx / esi / edi / ebp kept"
    assert img.r32(sym["g_btn_tileH"]) == 0, "devfill's ran-this-compose signal cleared"
    mask = img.r32(sym["g_btn_edge_mask"]) & 0xFF
    cols = tuple(img.r32(sym[f"g_btn_edge_c{i}"]) & 0xFF if mask >> i & 1 else None for i in range(4))
    return cols


def test_edgeprobe_is_the_law(img):
    for rows, native_h, art_h in _probe_faces():
        got = _run_probe(img, rows, native_h, art_h)
        assert got == SL.btn_edge_probe(rows, art_h), (len(rows[0]), native_h, art_h)


def test_edgeprobe_census_finds_the_hover_ring_only(img):
    """The measured default faces: state 1 has the E0 ring on all four sides, states 0 / 2 none."""
    for s, want in ((0, (None,) * 4), (1, (0xE0,) * 4), (2, (None,) * 4)):
        assert _run_probe(img, _face(s, 236), 20, 20) == want, s
        assert SL.btn_edge_probe(_face(s, 236), 20) == want, s


def test_edgeprobe_without_a_capture_probes_nothing(img):
    assert _run_probe(img, _face(1, 236), 20, 20, captured=False) == (None,) * 4


# ============================================================================== t_btn_edgeband
def _canvas(rnd, w, h, s):
    rows = [[rnd.choice((0xAE, 0xEE, 0xE0, 0xE1, 0x41)) for _ in range(w)] for _ in range(h)]
    for (y0, x0) in ((0, 0), (0, w - s), (h - s, 0), (h - s, w - s)):
        for y in range(y0, y0 + s):
            for x in range(x0, x0 + s):
                rows[y][x] = KEY
    return rows


@pytest.mark.parametrize("g", range(16, 41))
def test_edgeband_is_the_law(img, g):
    sym = img.sym
    rnd = random.Random(g)
    img.stub = {sym["thunk_btn_ringfix"]: lambda img: _ret(img, 0)}
    k = SL.btn_edge_stroke(g)
    for w, h, d in ((SL.popup_scale_floor(236, g), SL.popup_scale_floor(20, g), SL.popup_scale_floor(20, g)),
                    (SL.popup_scale_floor(192, g), SL.popup_scale_floor(22, g), SL.btn_bar_tile_height(
                        SL.popup_scale_floor(22, g), SL.btn_native_dim(SL.popup_scale_floor(22, g), g), 20)),
                    (2 * k, 2 * k, 2 * k), (2 * k - 1, 3 * k, 3 * k), (3 * k, 3 * k, 2 * k - 1)):
        for mask in (0, 1, 2, 4, 8, 15, 5):
            cols = tuple(rnd.choice((0xE0, 0x41, 0xC6)) if mask >> i & 1 else None for i in range(4))
            canvas = _canvas(rnd, w, h, min(k, w // 2, h // 2) or 1)
            img.put_plane(canvas, h=h + 2)
            img.w32(G_VA, g)
            img.w32(sym["g_btn_tileH"], d)
            img.w32(sym["g_btn_edge_mask"], mask)
            for i in range(4):
                img.w32(sym[f"g_btn_edge_c{i}"], cols[i] if cols[i] is not None else 0x55)
            img.w32(BTN + 0x4C4, w)
            img.w32(BTN + 0x498, PLANE)
            img.w32(BTN + 0x8EC, STRIDE)
            img.run(sym["t_btn_edgeband"], [RET], {UC_X86_REG_ESI: BTN})
            assert img.mu.reg_read(UC_X86_REG_ESI) == BTN and img.mu.reg_read(UC_X86_REG_ESP) == STK + 4
            assert img.r32(sym["g_btn_edge_mask"]) == 0, "consumed"
            got = img.plane(h + 2, STRIDE)
            want = SL.btn_edge_band(canvas, d, g, cols) if mask else canvas
            assert [list(r) for r in got[:h, :w]] == want, (g, w, h, d, mask)
            assert (got[:h, w:] == 0x77).all() and (got[h:] == 0x77).all(), "nothing outside the face"


# ============================================================================== faction rows
def _sprite(addr, rows):
    """A memory-backed Sprite at addr (data +4, pitch +0xC, w +0x10, h +0x14), pixels right after the header."""
    h, w = len(rows), len(rows[0])
    return addr, struct.pack("<IIIIII", 0, addr + 0x40, KEY, w, w, h).ljust(0x40, b"\0") + b"".join(bytes(r) for r in
                                                                                                     rows)


def _params(img, keyed, strokes):
    """A BoxSpriteParams set at PARAMS: 4 corner pieces (6 x 6, outer texel key iff keyed[k]), 4 strips (top / bottom
    24 x 6, left / right 6 x 24) whose edge texel is the stroke colour (else the pass-through 7)."""
    P = SL.BOX_PASS_THROUGH
    pieces = []
    for k in range(4):
        r = [[P] * 6 for _ in range(6)]
        if keyed[k]:
            r[0 if k < 2 else 5][0 if k % 2 == 0 else 5] = KEY
        pieces.append(r)
    t = [[strokes[0] or P] * 24] + [[P] * 24 for _ in range(5)]
    b = [[P] * 24 for _ in range(5)] + [[strokes[1] or P] * 24]
    lf = [[strokes[2] or P] + [P] * 5 for _ in range(24)]
    rt = [[P] * 5 + [strokes[3] or P] for _ in range(24)]
    pieces += [t, b, lf, rt]
    ptrs = []
    for i, rows in enumerate(pieces):
        a, blob = _sprite(PARAMS + 0x400 + 0x400 * i, rows)
        img.mu.mem_write(a, blob)
        ptrs.append(a)
    img.mu.mem_write(PARAMS, struct.pack("<10I", *ptrs, 0, P))
    return pieces


def _restripe_model(rows):
    """A stand-in restripe: every pair member onto row parity (any deterministic canvas map does)."""
    out = []
    for y, r in enumerate(rows):
        out.append([((0xAE, 0xEE)[y & 1] if v in (0xAE, 0xEE) else (0xE0, 0xE1)[y & 1] if v in (0xE0, 0xE1)
                     else (0xC6, 0x41)[y & 1] if v in (0xC6, 0x41) else v) for v in r])
    return out


@pytest.mark.parametrize("g", range(16, 41))
def test_faction_row_is_the_law(img, g):
    sym = img.sym
    rnd = random.Random(1000 + g)
    W, H = SL.popup_scale_floor(200, g), SL.popup_scale_floor(60, g)     # a list canvas: rows, gaps, background
    rows_seen = {}

    def box(img):                                     # Buffer_box_sprite: paint the rect, the keyed corner pixels left
        mu = img.mu
        sp = mu.reg_read(UC_X86_REG_ESP)
        rp = img.r32(sp + 4)
        L, T, R, B = (img.r32(rp + 4 * i) for i in range(4))
        plane = img.plane(H, W)
        for y in range(T, B):
            for x in range(L, R):
                corner = (y in (T, B - 1)) and (x in (L, R - 1))
                if corner and rows_seen["keyed"][(0 if y == T else 2) + (0 if x == L else 1)]:
                    continue
                edge = rows_seen["strokes"]
                c = (0xAE, 0xEE)[(y - T) & 1]
                if y == T and edge[0]:
                    c = edge[0]
                elif y == B - 1 and edge[1]:
                    c = edge[1]
                elif x == L and edge[2]:
                    c = edge[2]
                elif x == R - 1 and edge[3]:
                    c = edge[3]
                plane[y, x] = c
        rows_seen["painted"] = plane.copy()
        img.put_plane([list(r) for r in plane], h=H)
        _ret(img, 8)

    def restripe(img):
        sp = img.mu.reg_read(UC_X86_REG_ESP)
        assert [img.r32(sp + 4 + 4 * i) for i in range(4)] == [0, 0, W, H], "the restripe's own args"
        img.put_plane(_restripe_model([list(r) for r in img.plane(H, W)]), h=H)
        _ret(img, 0x10)

    img.stub = {0x5E2DD3: box, sym["t_lbi_restripe_ph"]: restripe}
    img.w32(G_VA, g)
    canvas_buf = BTN + 0x444
    img.w32(canvas_buf + 0x54, PLANE)
    img.w32(canvas_buf + 0x4A8, STRIDE)
    img.w32(canvas_buf + 0x80, W)
    img.w32(canvas_buf + 0x84, -H)
    rect_ptr = ARR + 0x800
    for case in range(6):
        keyed = (True,) * 4 if case < 3 else tuple(rnd.random() < 0.5 for _ in range(4))
        strokes = ((None,) * 4, (0xE0,) * 4, tuple(rnd.choice((None, 0xE0, 0x41)) for _ in range(4)))[case % 3]
        rows_seen.update(keyed=keyed, strokes=strokes)
        _params(img, keyed, strokes)
        rh = SL.popup_scale_floor(16, g)
        T = rnd.randint(0, H - rh)
        rect = (0, T, W, T + rh) if case != 5 else (W // 3, T, W - W // 4, T + rh)
        img.mu.mem_write(rect_ptr, struct.pack("<4i", *rect))
        before = [[rnd.choice((0xC6, 0x41)) for _ in range(W)] for _ in range(H)]
        img.put_plane(before, h=H)
        img.w32(sym["g_fr_pending"], 0x77)
        # t_fac_item_pre's clear, then the painter's box draw, then t_lb_item_stripes' restripe call
        img.stub[0x60B530] = lambda img: _ret(img, 4)
        img.run(sym["t_fac_item_pre"], [RET, 3])
        assert img.r32(sym["g_fr_pending"]) == 0
        regs = img.run(sym["t_fac_rowbox"], [RET, rect_ptr, PARAMS], {UC_X86_REG_ECX: canvas_buf})
        assert img.mu.reg_read(UC_X86_REG_ESP) == STK + 12
        assert all(img.mu.reg_read(r) == regs[r] for r in CALLEE)
        # the item's text, drawn by ListBox_draw_item between the painter and the restripe: ink (non-pair indices)
        # in the band rows / columns -- descenders on the bottom band, a cap on the top, glyph edges at the sides
        L, T, R, B = rect
        s = SL.btn_corner_notch(g)
        ink = {}
        for _ in range(40):
            y = rnd.choice((T, T + s - 1, B - 1, B - s, rnd.randrange(T, B)))
            x = rnd.choice((L + s, R - s - 1, rnd.randrange(L + s, R - s), L, R - 1))
            ink[(y, x)] = rnd.choice((0xFF, 0x10, 0x8A))
        plane = img.plane(H, W)
        for (y, x), v in ink.items():
            plane[y, x] = v
        img.put_plane([list(r) for r in plane], h=H)
        img.run(sym["t_fac_rowpost"], [RET, 0, 0, W, H], {UC_X86_REG_ECX: canvas_buf})
        assert img.mu.reg_read(UC_X86_REG_ESP) == STK + 0x14
        assert img.r32(sym["g_fr_pending"]) == 0
        got = [list(r) for r in img.plane(H, W)]
        want = SL.faction_row_face(before, [list(r) for r in rows_seen["painted"]], rect, g, keyed, strokes,
                                   ink=ink, restripe=_restripe_model)
        assert got == want, (g, case, rect, keyed, strokes)
        for (y, x), v in ink.items():                                 # the text is never overwritten by a band
            assert got[y][x] == v, (g, case, y, x)
        if g > 16:
            for k, (y0, x0) in enumerate(((T, L), (T, R - s), (B - s, L), (B - s, R - s))):
                sq = {got[y][x] for y in range(y0, y0 + s) for x in range(x0, x0 + s) if (y, x) not in ink}
                if keyed[k]:
                    assert sq <= {0xC6, 0x41}, (g, case, k, sq)       # an s x s notch of background


# ============================================================================== thunk_filedlg_rects v2
@pytest.mark.parametrize("g", range(16, 41))
def test_filedlg_rects_is_the_law(img, g):
    sym = img.sym
    rnd = random.Random(2000 + g)
    seen = {}

    def build(img):
        sp = img.mu.reg_read(UC_X86_REG_ESP)
        seen.update(esp=sp, frame=[img.r32(sp + 4 * i) & 0xFFFFFFFF for i in range(4)],
                    ecx=img.mu.reg_read(UC_X86_REG_ECX), regs={r: img.mu.reg_read(r) for r in CALLEE})
        _ret(img, 0xC)
    img.stub = {sym["FileDlg_build_widgets"]: build}
    img.w32(G_VA, g)
    arrays = []
    for path in ("menu", "ingame"):
        ok, ca = SL.FILEDLG_BTN_RECTS[path]
        arrays.append([0x80060 if path == "menu" else 0] + [14, 42, 319, 330, 17, 332, 317, 352] + list(ok) + list(ca))
    for _ in range(6):
        l0 = rnd.randint(0, 60)
        w0 = rnd.randint(40, 200)
        seam = rnd.randint(0, 9)
        w1 = w0 + rnd.choice((0, 1))
        t0 = rnd.randint(200, 400)
        hh = rnd.randint(14, 30)
        arrays.append([rnd.randint(0, 99)] + [rnd.randint(0, 400) for _ in range(8)]
                      + [l0, t0, l0 + w0, t0 + hh, l0 + w0 + seam, t0, l0 + w0 + seam + w1, t0 + hh])
    for arr in arrays:
        img.mu.mem_write(ARR, struct.pack("<17i", *arr))
        frame = [RET, 0x1111, 0x2222, ARR]
        regs = img.run(sym["thunk_filedlg_rects"], frame, {UC_X86_REG_ECX: 0x4444})
        assert seen["esp"] == STK and seen["frame"] == frame and seen["ecx"] == 0x4444
        assert seen["regs"] == {r: regs[r] for r in CALLEE}
        got = list(struct.unpack("<17i", bytes(img.mu.mem_read(ARR, 68))))
        if g <= 16:
            assert got == arr
            continue
        want = [arr[0]] + [SL.popup_scale_floor(v, g) for v in arr[1:9]]
        ok, ca = SL.filedlg_btn_pair(tuple(arr[9:13]), tuple(arr[13:17]), g)
        assert got == want + list(ok) + list(ca), (g, arr)
