"""Guard for group netwin_frame_strokes (2026-11-07): the MULTIPLAYER SETUP lobby's frame strokes.

Ports: t_nwf_bm / t_nwf_box / t_nwf_title / t_nwf_lock / t_nwf_ins3 / t_nwf_core (assemble_nw_frames.py).
Laws: scaling_laws.nw_frame_stroke / nw_frame_bands / nw_frame_interior / nw_title_band_inset / nw_title_rect_bottom /
nw_lock_icon_x, plus the panel stripe law panel_fill_pixel (fix 28 v2) they extend.

Layers:
  1. the laws themselves (no image);
  2. the small thunks' arithmetic under Unicorn against the law at every g 1..64 (the yaml bytes as baked);
  3. the REAL image's lobby (checkbox_emu.lobby: NetWin_setup_lobby + NetWin_draw on the baked exe):
     - baked == ORACLE pixel for pixel (the oracle = the band-map thickener path the popup family ships,
       assemble_nw_frames.ORACLE, dropped into the image's memory at boot) -- the strongest check.  It is an
       equivalence UNDER THE LOBBY'S CONDITIONS (g <= 40 so K <= 2, every rect inside the buffer, a backdrop on the
       same stripe phase): on a synthetic background striped off-phase in the fill's own colours, or a rect crossing
       the buffer edge, the oracle's devfill recolours pixels the baked painter leaves (audit 2026-11-07 D2) -- the
       law the baked painter is held to everywhere is nw_frame_bands / nw_frame_interior;
     - every one of the ~50 boxes: the stroke K wide on all four sides at the mid-edges, its corners as the law
       paints them, its interior on the panel stripe law, its rect within 1 px of vanilla x g/16;
     - the roster lock icon right after the K-wide stroke;
     - g = 16 byte-identical to the pristine exe.

Cost: one baked lobby draw is ~3-4 s, the oracle's ~2x that; layer 3 is one item per g (six g) so xdist spreads it.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")

import assemble_nw_frames as NF  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x00668740
STROKE = {0x78D690: 0x1A, 0x78D5A0: 0x1F, 0x78D618: 0x22, 0x78D528: 0x22, 0x78DCA8: 0x1F}
FILLED = {0x78D690, 0x78D618, 0x78D528, 0x78DCA8}
#: K = 1 at 17 / 22 / 24 (T = 1 at 17, 2 from 22), K = 2 at 25 / 30 / 40; 1600x900, 1920x1080, 1600x1200, 1440p, 4K
E2E_G = (17, 18, 22, 24, 25, 30, 40)


# ============================================================================================ layer 1: the laws
@pytest.mark.parametrize("g", range(16, 41))
def test_title_rects_within_a_pixel_of_vanilla(g):
    """The title outline (bottom: nw_title_rect_bottom) and its band (inset: nw_title_band_inset) land within 1 px of
    vanilla x g/16 on every edge; the outline's left / top / right are thunk_nw_rectscale's fl(3g/16) / W - fl(3g/16)."""
    W = (800 * g) // 16                  # thunk_nw_winsize: the 800-wide window at fl(800g/16)
    l = t = (3 * g) // 16
    r = W - (3 * g) // 16
    b = SL.nw_title_rect_bottom(t, g)
    outline = (l, t, r, b)
    for v, vv in zip(outline, SL.NW_TITLE_RECT):
        assert abs(v - vv * g / 16) <= 1, (g, outline)
    k = SL.nw_title_band_inset(g)
    band = (l + k, t + k, r - k, b - k)
    for v, vv in zip(band, (6, 6, 794, 26)):
        assert abs(v - vv * g / 16) <= 1, (g, band)
    # the channel between the two strokes is the same on all four sides (symmetry) and ~ vanilla 2 x g/16
    K = SL.nw_frame_stroke(g)
    assert k - K >= 0 and abs((k - K) - 2 * g / 16) <= 1, (g, k, K)


def test_title_identity_and_the_bug():
    assert SL.nw_title_rect_bottom(3, 16) == 29 and SL.nw_title_band_inset(16) == 3
    # thunk_nw_rectscale's own bottom, T + fl(26g/16), is > 1 px short at g 19 / 25 / 30 / 35 (the double floor)
    for g in (19, 25, 30, 35):
        assert 29 * g / 16 - ((3 * g) // 16 + (26 * g) // 16) > 1
        assert abs(SL.nw_title_rect_bottom((3 * g) // 16, g) - 29 * g / 16) < 1


@pytest.mark.parametrize("g", range(16, 41))
def test_frame_bands_cover_the_stroke_and_leave_the_corners(g):
    K = SL.nw_frame_stroke(g)
    rect = (10, 20, 110, 70)
    for cls in (SL.NW_FRAME_CHAMFER, SL.NW_FRAME_BEVEL):
        cover = set()
        for l, t, r, b in SL.nw_frame_bands(rect, cls, g):
            assert l < r and t < b
            for y in range(t, b):
                for x in range(l, r):
                    assert (x, y) not in cover, "bands never overlap"
                    cover.add((x, y))
        L, T, R, B = rect
        mid_x, mid_y = (L + R) // 2, (T + B) // 2
        assert {(mid_x, y) for y in range(T, T + K)} <= cover and (mid_x, T + K) not in cover
        assert {(mid_x, y) for y in range(B - K, B)} <= cover and (mid_x, B - K - 1) not in cover
        assert {(x, mid_y) for x in range(L, L + K)} <= cover and (L + K, mid_y) not in cover
        assert {(x, mid_y) for x in range(R - K, R)} <= cover and (R - K - 1, mid_y) not in cover
        assert (L, T) not in cover and (R - 1, B - 1) not in cover, "the corner pixel keeps what was under the box"
        # the four quadrants are mirror images (the shape is symmetric)
        for (x, y) in list(cover):
            assert (L + R - 1 - x, y) in cover and (x, T + B - 1 - y) in cover
    if g == 16:   # K = 1: the native shapes exactly
        ch = set()
        for l, t, r, b in SL.nw_frame_bands(rect, SL.NW_FRAME_CHAMFER, 16):
            ch |= {(x, y) for y in range(t, b) for x in range(l, r)}
        assert (11, 20) in ch and (10, 21) in ch and (10, 20) not in ch and (11, 21) not in ch
        bv = set()
        for l, t, r, b in SL.nw_frame_bands(rect, SL.NW_FRAME_BEVEL, 16):
            bv |= {(x, y) for y in range(t, b) for x in range(l, r)}
        assert {(12, 20), (11, 21), (10, 22)} <= bv and not {(10, 20), (11, 20), (10, 21)} & bv


@pytest.mark.parametrize("g", range(16, 41))
def test_chat_log_gap_to_the_stroke(g):
    """The chat log text area's gap to its panel's stroke = inset - K, within 1 px of vanilla's 2 x g/16."""
    gap = SL.nw_chat_log_inset(g) - SL.nw_frame_stroke(g)
    assert gap >= 1 and abs(gap - 2 * g / 16) <= 1, (g, gap)


def test_lock_icon_law():
    assert SL.nw_lock_icon_x(335, 16) == 336            # vanilla: the column after the 1-px stroke
    for g in range(17, 41):
        assert SL.nw_lock_icon_x(100, g) == 100 + SL.nw_frame_stroke(g)


# ============================================================================================ layer 2: the thunks
def _yaml_bytes(name: str) -> bytes:
    """The thunk's bytes as baked: the yaml template with this cave's symbols resolved."""
    import re
    text = (Path(__file__).resolve().parent.parent / "patches" / "patches.yaml").read_bytes().decode("utf-8")
    m = re.search(rf"\n\s*- id: {name}\r?\n\s*offset: (0x[0-9a-fA-F]+)\r?\n\s*bytes: \"([^\"]+)\"", text)
    assert m, name
    va = NF.PCAVE2 + int(m.group(1), 16)
    syms = {"g_popup_scale_num": G_VA, "g_stripe_period": NF.G_STRIPE_PERIOD, "Buffer_box_sprite": NF.BUFFER_BOX_SPRITE,
            "t_nwf_core": NF.CORE, "thunk_nw_toggle": NF.NW_TOGGLE, "g_nwf_rect": NF.RECT,
            "thunk_box_thick_hollow_flat": NF.HOLLOWFLAT, "thunk_box_thick_devfill": NF.DEVFILL, "t_nw_box": NF.T_NW_BOX}
    out = bytearray()
    for tok in m.group(2).split():
        a = re.fullmatch(r"\{abs32:(\w+)\}", tok)
        r = re.fullmatch(r"\{rel32:(\w+)\}", tok)
        if a:
            out += struct.pack("<I", syms[a.group(1)])
        elif r:
            out += struct.pack("<i", syms[r.group(1)] - (va + len(out) + 4))
        else:
            out.append(int(tok, 16))
    return bytes(out)


def test_yaml_bytes_are_the_assembler_output():
    built = NF.build()
    for name, b in built.items():
        assert _yaml_bytes(name) == b, name


class _Uc:
    def __init__(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for base in (0x00660000, NF.PCAVE2 + 0x30000, NF.PCAVE2 + 0x40000, 0x10000000, 0x20000000, 0x005E0000,
                     0x00A10000, 0x00620000):
            self.mu.mem_map(base, 0x10000)
        for name, b in NF.build().items():
            self.mu.mem_write(NF.PCAVE2 + NF.SLOTS[name], b)
        self.mu.mem_write(NF.BUFFER_BOX_SPRITE, b"\xF4")
        self.mu.mem_write(NF.NW_TOGGLE, b"\xF4")
        self.mu.mem_write(NF.TEXTSCROLL_ATTACH, b"\xF4")
        self.mu.mem_write(NF.CORE, b"\xF4")       # stop at the core's entry (its own pixels are layer 3)

    def run(self, entry, g, stack, regs):
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP
        mu = self.mu
        mu.mem_write(G_VA, struct.pack("<I", g))
        esp = 0x1000F000
        mu.mem_write(esp, b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in stack))
        mu.reg_write(UC_X86_REG_ESP, esp)
        for r, v in regs.items():
            mu.reg_write(r, v)
        try:
            mu.emu_start(entry, 0xFFFFFFFF, count=200)
        except Exception:
            pass
        return mu.reg_read(UC_X86_REG_EIP) - 0, mu.reg_read(UC_X86_REG_ESP)


@pytest.fixture(scope="module")
def uc():
    return _Uc()


@pytest.mark.parametrize("g", range(1, 65))
def test_ins3_is_the_law(uc, g):
    from unicorn.x86_const import UC_X86_REG_EAX
    entry = NF.PCAVE2 + NF.SLOTS["t_nwf_ins3"]
    uc.mu.mem_write(0x1000E000, b"\xF4")
    uc.run(entry, g, [0x1000E000], {})
    want = 3 if g <= 16 else SL.scale_px(3, g)
    assert uc.mu.reg_read(UC_X86_REG_EAX) == want


@pytest.mark.parametrize("g", list(range(1, 41)))
def test_title_and_lock_thunks_are_the_law(uc, g):
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI,
                                   UC_X86_REG_EDI, UC_X86_REG_EBP)
    mu = uc.mu
    # title: the rect copy's bottom := T - fl(3g/16) + fl(29g/16); eax = 1 into the core; ecx untouched
    rect = 0x20000100
    t = (3 * g) // 16 if g > 16 else 3
    mu.mem_write(rect, struct.pack("<4i", t, t, 999, 12345))
    eip, esp = uc.run(NF.PCAVE2 + NF.SLOTS["t_nwf_title"], g, [0x1000E000, rect, 0x78D5A0], {UC_X86_REG_ECX: 0x80AB3C})
    b = struct.unpack("<i", bytes(mu.mem_read(rect + 12, 4)))[0]
    if g <= 16:
        assert eip == NF.BUFFER_BOX_SPRITE + 1 and b == 12345
    else:
        assert eip == NF.CORE + 1 and mu.reg_read(UC_X86_REG_EAX) == 1
        assert b == SL.nw_title_rect_bottom(t, g)
    assert mu.reg_read(UC_X86_REG_ECX) == 0x80AB3C
    # lock: x += K - 1 at g > 16, every register kept, the other args untouched
    regs = {UC_X86_REG_EAX: 0x11, UC_X86_REG_EBX: 0x22, UC_X86_REG_ECX: 0x7AC040, UC_X86_REG_EDX: 0x44,
            UC_X86_REG_ESI: 0x55, UC_X86_REG_EDI: 0x66, UC_X86_REG_EBP: 0x77}
    stack = [0x1000E000, 0x80AB80, 9, 838, 145, 1, 1]
    eip, esp = uc.run(NF.PCAVE2 + NF.SLOTS["t_nwf_lock"], g, stack, regs)
    assert eip == NF.NW_TOGGLE + 1 and esp == 0x1000F000 - 4 + 4 + 0   # the push; ret consumed: same esp as entry
    got = struct.unpack("<7I", bytes(mu.mem_read(0x1000F000, 28)))
    want = list(stack)
    want[3] = 838 + (SL.nw_frame_stroke(g) - 1 if g > 16 else 0)
    assert list(got) == [v & 0xFFFFFFFF for v in want]
    for r, v in regs.items():
        assert mu.reg_read(r) == v


@pytest.mark.parametrize("g", list(range(1, 41)))
def test_chat_log_thunk_is_the_law(uc, g):
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX
    stack = [0x1000E000, 795, 605, 1184, 277, 0x80A6F8, 0, 0xFFFFFFFF]
    eip, esp = uc.run(NF.PCAVE2 + NF.SLOTS["t_nwf_ts"], g, stack, {UC_X86_REG_EAX: 0x1234, UC_X86_REG_ECX: 0x80B438})
    assert eip == NF.TEXTSCROLL_ATTACH + 1 and esp == 0x1000F000
    got = list(struct.unpack("<8I", bytes(uc.mu.mem_read(0x1000F000, 32))))
    d = SL.nw_chat_log_inset(g) - 3
    want = [0x1000E000, 795 + d, 605 + d, 1184 - 2 * d, 277 - 2 * d, 0x80A6F8, 0, 0xFFFFFFFF]
    assert got == [v & 0xFFFFFFFF for v in want]
    assert uc.mu.reg_read(UC_X86_REG_EAX) == 0x1234 and uc.mu.reg_read(UC_X86_REG_ECX) == 0x80B438


# ============================================================================================ layer 3: the real image
def _lobby(exe, g, oracle=False, census=None, after=None):
    import checkbox_emu as CE
    import image_emu as E
    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP
    CE.RES.setdefault(g, (64 * g, 48 * g))
    orig = E.boot

    def boot(*a, **k):
        e = orig(*a, **k)
        if oracle:
            ob = NF.build_oracle()
            for name, b in ob.items():
                e.uc.mem_write(NF.PCAVE2 + NF.ORACLE_SLOTS[name], b)
            tgt = NF.PCAVE2 + NF.ORACLE_SLOTS["t_nwf_box"]
            for va in NF.FILLED_SITES:     # the outline / title entries tail into CORE = the outline oracle
                e.uc.mem_write(va, b"\xE8" + struct.pack("<i", tgt - (va + 5)))
        if census is not None:
            def cb(e):
                if e.reg(UC_X86_REG_ECX) != CE.NW + 0x444:
                    return
                esp = e.reg(UC_X86_REG_ESP)
                rp, pp = e.r32(esp + 4), e.r32(esp + 8)
                census.append(dict(params=pp, rect=tuple(e.s32(rp + 4 * i) for i in range(4)), ret=e.r32(esp)))
            for va in ((NF.CORE,) if g > 16 else ()) + ((NF.BUFFER_BOX_SPRITE,) if g <= 16 else ()):
                e.observe(va, cb)
        return e
    CE.E.boot = boot
    try:
        out = CE.lobby(str(exe), g)
    finally:
        CE.E.boot = orig
    return out


@pytest.fixture(scope="module")
def vanilla_boxes(bak_path):
    boxes = []
    _lobby(bak_path, 16, census=boxes)
    assert len(boxes) == 50
    return boxes


@pytest.mark.parametrize("g", E2E_G)
def test_lobby_baked_equals_the_bandmap_oracle(baked_exe, g):
    a = _lobby(baked_exe, g)
    b = _lobby(baked_exe, g, oracle=True)
    assert a["g"] == b["g"] == g
    ca, cb = a["canvases"]["NW"], b["canvases"]["NW"]
    assert ca.shape == cb.shape
    diff = np.argwhere(ca != cb)
    assert not len(diff), f"{len(diff)} px differ, first (y, x) {diff[:5].tolist()}"


@pytest.mark.parametrize("g", E2E_G)
def test_every_lobby_frame_on_the_law(baked_exe, vanilla_boxes, g):
    import checkbox_emu as CE
    boxes = []
    out = _lobby(baked_exe, g, census=boxes)
    c = out["canvases"]["NW"]
    pal = CE.palette()
    rgb = lambda i: tuple(int(v) for v in pal[i])  # noqa: E731
    K = SL.nw_frame_stroke(g)
    assert len(boxes) == len(vanilla_boxes) == 50
    for box, van in zip(boxes, vanilla_boxes):
        assert box["params"] == van["params"]
        l, t, r, b = box["rect"]
        for v, vv in zip(box["rect"], van["rect"]):
            assert abs(v - vv * g / 16) <= 1, (hex(box["params"]), box["rect"], van["rect"])
        s = STROKE[box["params"]]
        mx, my = (l + r) // 2, (t + b) // 2

        def run(cells):
            n = 0
            for x, y in cells:
                if c[y, x] != s:
                    break
                n += 1
            return n
        runs = (run([(mx, y) for y in range(t, t + 8)]), run([(mx, y) for y in range(b - 1, b - 9, -1)]),
                run([(x, my) for x in range(l, l + 8)]), run([(x, my) for x in range(r - 1, r - 9, -1)]))
        assert runs == (K, K, K, K), (hex(box["params"]), box["rect"], runs)


@pytest.mark.parametrize("g", (22, 25, 40))
def test_panel_interiors_on_the_stripe_law_right_after_each_box(baked_exe, g):
    """Snapshot the canvas right after every filled site returns (before text / checkboxes / icons overdraw it): the
    interior inside the K band holds only the fill tile's two members, row-uniform, on panel_fill_pixel -- no
    1-row ring inside the stroke."""
    import checkbox_emu as CE
    import image_emu as E
    pal = CE.palette()
    rgb = lambda i: tuple(int(v) for v in pal[i])  # noqa: E731
    pr = CE.PanelRecorder(pal, NF.FILLED_SITES)
    CE.RES.setdefault(g, (64 * g, 48 * g))
    CE.lobby(str(baked_exe), g, None, pr)
    assert len(pr.boxes) >= 40
    for bx in pr.boxes:
        pair = SL.tile_scan_pair(bx["tile_rows"])
        assert pair
        cnv = bx["canvas"]
        il, it, ir, ib = SL.nw_frame_interior(tuple(bx["rect"]), g)
        il, it, ir, ib = max(il, 0), max(it, 0), min(ir, cnv.shape[1]), min(ib, cnv.shape[0])
        for y in range(it, ib):
            row = set(cnv[y, il:ir].tolist())
            assert len(row) == 1 and row <= set(pair), (hex(bx["site"]), bx["rect"], y, row)
            v = row.pop()
            assert SL.panel_fill_pixel(v, y, g, *pair, rgb) == v, (hex(bx["site"]), y)


@pytest.mark.parametrize("g", (25, 40))
def test_lock_icon_clears_the_stroke(baked_exe, g):
    """The roster lock icon (Sprite_draw_2 at 0x480599) starts at the lock cell's L + K: the K stroke columns of
    every lock cell stay stroke-coloured over the whole cell height."""
    boxes = []
    out = _lobby(baked_exe, g, census=boxes)
    c = out["canvases"]["NW"]
    K = SL.nw_frame_stroke(g)
    locks = [b for b in boxes if b["params"] == 0x78D528 and b["ret"] in (0x4804B5,)]
    assert len(locks) == 7
    for b in locks:
        l, t, r, bb = b["rect"]
        for x in range(l, l + K):
            col = c[t + K:bb - K, x]
            assert (col == 0x22).all(), (b["rect"], x)


@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_chat_log_text_area_inside_its_panel(baked_exe, g):
    """The real builder's TextScroll_attach(chat log): the chat log panel rect (the d528 box at 0x481C22, the rect
    table's +0xCC4) inset by nw_chat_log_inset on every side."""
    import checkbox_emu as CE
    import image_emu as E
    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP
    seen = []
    orig = E.boot

    def boot(*a, **k):
        e = orig(*a, **k)

        def cb(e):
            if e.reg(UC_X86_REG_ECX) == CE.NW + 0xD40:
                esp = e.reg(UC_X86_REG_ESP)
                seen.append(([e.s32(esp + 4 + 4 * i) for i in range(4)],
                             [e.s32(CE.NW + 0xCC4 + 4 * i) for i in range(4)]))
        e.observe(NF.TEXTSCROLL_ATTACH, cb)
        return e
    CE.E.boot = boot
    CE.RES.setdefault(g, (64 * g, 48 * g))
    try:
        CE.lobby(str(baked_exe), g)
    finally:
        CE.E.boot = orig
    assert len(seen) == 1
    (x, y, w, h), (l, t, r, b) = seen[0]
    k = SL.nw_chat_log_inset(g)
    assert (x, y, x + w, y + h) == (l + k, t + k, r - k, b - k)


def test_g16_lobby_equals_the_pristine_exe(baked_exe, bak_path):
    a = _lobby(baked_exe, 16)["canvases"]["NW"]
    b = _lobby(bak_path, 16)["canvases"]["NW"]
    assert a.shape == b.shape and (a == b).all()
