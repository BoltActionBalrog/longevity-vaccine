"""Guard for group replay_scale (2026-11-15): the end-game REPLAY window (show_replay 0x5ADBF0).

Ports: t_rp_bracket / t_rp_winsize / t_rp_maprect / t_rp_zoom / t_rp_close / t_rp_title / t_rp_btndraw / t_rp_face
(assemble_replay.py), plus the lobby's t_nwf_box / t_nwf_ins3 reused at the painter.  Laws: scaling_laws END-GAME
REPLAY.

Layers:
  1. the laws (no image): identity at g 16 = the measured vanilla, every edge of the s(800) x s(600) window within
     1 px of vanilla x g/16, matched margins, the map (option A, the user's decision) clipping no row in the window
     replay_window grows to (the user's decision) for every world 16..128 and g 17..40;
  2. the thunks under Unicorn against the laws (the yaml bytes as baked): every g 1..64, the face restripe on a
     synthetic canvas, and t_rp_btndraw's pass-through -- every other button reaches thunk_dw_btndraw with every
     register, flag and stack byte unchanged;
  3. the REAL image (image_emu): show_replay run end to end over a synthetic world in memory (tiles, one visible
     vehicle, one base through the replay's own base table), its save / load, timer and modal loop stubbed and
     ReplayWin_draw called where the modal loop would start.  The engine renders the map itself: no map row clipped
     at the child's edges, no unit / base drawing at the deeper zooms; the window, map child, zoom, title box and its
     text rect, the Close bar (both face states: the members on the window grid's stripe_top rows, every row, the
     s x s corner keys) and the label's centred-path draw on the laws; g 16 byte-identical to the pristine exe.

Cost: one emulated replay with its map render is ~5-15 s; layer 3 is one item per configuration, so xdist spreads it.
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

import assemble_replay as RP  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x00668740
G_RANGE = range(16, 41)
SCREENS = {16: (1024, 768), 18: (1600, 900), 21: (1680, 1050), 22: (1920, 1080), 25: (1600, 1200),
           26: (2048, 1280), 30: (2560, 1440), 31: (2560, 1500), 40: (3840, 2160)}
WORLDS = ((48, 48), (64, 64), (80, 80), (88, 90), (128, 128))          # #WORLDSIZE: tiny .. huge
VANILLA = dict(title=(4, 4, 796, 24), text=(7, 7, 793, 21), map=(3, 26, 797, 574), close=(3, 577, 797, 597))
STD = (80, 80)
#: (g, world, face state): 1600x900 (T 1), 1920x1080 (K 1, T 2), 1600x1200 (K 2), the two growth cases (standard
#: world at g 26, tiny at g 31), 1440p, 4K (standard + tiny), a small world at g 21 (growth), hover faces at 1080 / 4K
#: plus a 180-tile custom world at 1920x1080: the fit is -16 there, the engine draws no map (vanilla too) -> no growth
E2E = ((18, STD, 0), (22, STD, 0), (25, STD, 0), (26, STD, 0), (30, STD, 0), (31, (48, 48), 0), (40, STD, 0),
       (40, (48, 48), 0), (21, (64, 64), 0), (22, STD, 2), (40, STD, 2), (22, (360, 180), 0))
#: the faction's view centre the replay map starts from (0x9392C0 / 0x939340): vanilla's top row clamps to -2..+4
#: from it -- top half: the last row lands half a world left; bottom half: the top rows are never drawn
CENTRES = {(22, STD, 0): (41, 79), (40, STD, 0): (10, 60), (31, (48, 48), 0): (7, 41)}
#: Thinker's custom worlds reach 512 x 512 tiles (MapAreaX 1024; game.cpp 547-551), vanilla's 256
BIG_X = list(range(16, 130, 2)) + list(range(130, 1025, 18)) + [1024]


def tight_screen(g):
    """The smallest 4:3 screen running at g (64g x 48g): where a grown window has the least room."""
    return 64 * g, 48 * g


def screen_of(g):
    return SCREENS.get(g, tight_screen(g))


# ============================================================================================ layer 1: the laws
def _laws(g, world=None, screen=None):
    w, h = SL.replay_window_wh(g) if world is None else SL.replay_window(g, *world, *(screen or screen_of(g)))
    return w, h, dict(title=SL.replay_title_box(w, g), text=SL.replay_text_rect(w, g),
                      map=SL.replay_map_rect(w, h, g), close=SL.replay_close_rect(w, h, g))


def test_identity_at_16_is_the_measured_vanilla():
    w, h, r = _laws(16)
    assert (w, h) == SL.REPLAY_WIN and r == VANILLA
    assert all(SL.replay_window(16, x, y, 1024, 768) == (800, 600) for x, y in WORLDS + ((1024, 512),))
    assert SL.replay_fit_z(800, 600, 80, 80) == -13 and SL.map_u_of_zoom(-13) == 2
    assert SL.replay_map_px(2, 80, 80) == (648, 324)          # the 1:1 native render in Problems\Replay.png


@pytest.mark.parametrize("g", G_RANGE)
def test_every_edge_within_a_pixel_of_vanilla(g):
    w, h, r = _laws(g)
    assert abs(w - 800 * g / 16) <= 0.5 and abs(h - 600 * g / 16) <= 0.5
    for name, rect in r.items():
        for v, vv in zip(rect, VANILLA[name]):
            assert abs(v - vv * g / 16) <= 1, (g, name, rect)


@pytest.mark.parametrize("g", G_RANGE)
@pytest.mark.parametrize("world", (None,) + WORLDS)
def test_margins_matched_and_heights(g, world):
    w, h, r = _laws(g, world)
    for name in r:
        l, t, rr, b = r[name]
        assert l == w - rr, (g, name)                                     # left margin == right margin
    ml, mt, mr, mb = r["map"]
    assert mt == h - mb                                                   # map: top == bottom margin
    tl, tt, _, tb = r["title"]
    assert tl == tt                                                       # title box: left == top inset
    assert abs((tb - tt) - 20 * g / 16) <= 1                              # title box height ~ s(20)
    cl, ct, cr, cb = r["close"]
    assert abs((cb - ct) - 20 * g / 16) <= 1 and (cl, cr) == (ml, mr)     # Close: s(20) high, the map's L / R
    assert 0 <= ct - mb and abs((ct - mb) - 3 * g / 16) <= 1              # the channel above the Close bar


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("screen", ("tight", "named"))
def test_the_window_grows_only_where_a_row_would_clip_and_then_just_enough(g, screen):
    """replay_window (the user's "grow the window"), every world up to Thinker's 512 tiles wide (and as tall / half as
    tall): the whole window, its Close bar included, is ALWAYS on the screen (Win_center centres it there); it is
    s(800) x s(600) unless the engine's map would clip a row AND the clip-free window fits the screen, then exactly
    that width, 4:3 kept (H = max(s(600), ceil(3W/4))); a grown window clips no row."""
    sw, sh = tight_screen(g) if screen == "tight" else screen_of(g)
    if screen == "named" and g not in SCREENS:
        pytest.skip("no named screen at this g")
    w0, h0 = SL.replay_window_wh(g)
    s3 = SL.scale_px(3, g)
    for x in BIG_X:
        for y in {x, max(16, x // 2)}:
            w, h = SL.replay_window(g, x, y, sw, sh)
            assert w <= sw and h <= sh, (g, x, y, (w, h), (sw, sh))
            cl, ct, cr, cb = SL.replay_close_rect(w, h, g)
            assert (sh - h) // 2 + cb <= sh and (sw - w) // 2 + cr <= sw
            u = SL.map_u_of_zoom(SL.replay_map_zoom(x, y, g))
            need = SL.replay_clip_free_width(u, x) + 2 * s3
            z0 = SL.replay_fit_z(w0, h0, x, y)
            if (w, h) == (w0, h0):
                assert (need <= w0 or z0 <= SL.REPLAY_BLANK_ZOOM or need > sw
                        or max(h0, (3 * need + 3) // 4) > sh), (g, x, y)
                continue
            assert z0 > SL.REPLAY_BLANK_ZOOM
            assert w == need > w0 and h == max(h0, (3 * w + 3) // 4), (g, x, y)


def test_the_screen_cap_never_binds_on_a_drawn_map():
    """Every window the screen cap refuses is one whose map the engine would not draw (fit -16): on a map it draws,
    the clip-free window always fits even the tightest 4:3 screen of its g (the cap only guards the law)."""
    for g in range(17, 41):
        sw, sh = tight_screen(g)
        w0, h0 = SL.replay_window_wh(g)
        for x in range(16, 1026, 2):
            for y in {x, max(16, x // 2)}:
                z0 = SL.replay_fit_z(w0, h0, x, y)
                if z0 <= SL.REPLAY_BLANK_ZOOM:
                    continue
                need = SL.replay_clip_free_width(SL.map_u_of_zoom(z0), x) + 2 * SL.scale_px(3, g)
                assert need <= sw and max(h0, (3 * need + 3) // 4) <= sh, (g, x, y, need)


def test_growth_on_the_worldsize_worlds_is_what_the_user_was_shown():
    """The five #WORLDSIZE worlds: where the window grows, by how much (the preview: +22 px standard at g 26, +62 px
    tiny at g 31, as the engine centres it; +6 / +30 once t_rp_rows centres the map); and the zoom there is also the fit on the grown window (the pin changes nothing for them)."""
    grown = {}
    for g in range(17, 41):
        w0, _ = SL.replay_window_wh(g)
        for x, y in WORLDS:
            w, h = SL.replay_window(g, x, y, *tight_screen(g))
            assert SL.replay_map_zoom(x, y, g) == SL.replay_fit_z(w, h, x, y), (g, x)
            if w != w0:
                grown[(g, x)] = w - w0
    assert grown == {(26, 80): 6, (31, 48): 30}, grown      # the centred map needs 4u(X+1)


def test_option_a_numbers_the_user_saw():
    """The A column of the static map's table (the preview the user chose from)."""
    u = lambda x, y, g: SL.map_u_of_zoom(SL.replay_map_zoom(x, y, g))  # noqa: E731
    assert [u(80, 80, g) for g in (16, 18, 20, 22, 25, 30, 33, 40)] == [2, 2, 3, 3, 3, 4, 4, 6]
    assert [u(88, 90, g) for g in (16, 22, 40)] == [1, 3, 5]
    assert u(80, 80, 26) == 4 and u(48, 48, 31) == 8                    # the growth cases keep option A's unit


# ============================================================================================ layer 2: the thunks
G_STRIPE_PERIOD = RP.G_STRIPE_PERIOD


def _syms():
    return {"g_popup_scale_num": G_VA, "g_stripe_period": G_STRIPE_PERIOD, "g_rp_btn": RP.G_RP_BTN,
            "g_rp_z": RP.G_RP_Z, "g_rp_map": RP.G_RP_MAP, "ReplayWin_build": RP.REPLAYWIN_BUILD, "MapAreaX": RP.MAP_AREA_X,
            "MapAreaY": RP.MAP_AREA_Y}


def _yaml_text() -> str:
    return (Path(__file__).resolve().parent.parent / "patches" / "patches.yaml").read_bytes().decode("utf-8")


def _yaml_bytes(text: str, name: str) -> bytes:
    import re
    m = re.search(rf"\n\s*- id: {name}\r?\n\s*offset: (0x[0-9a-fA-F]+)\r?\n\s*bytes: \"([^\"]+)\"", text)
    assert m, name
    va = RP.PCAVE2 + int(m.group(1), 16)
    syms, out = _syms(), bytearray()
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
    text = _yaml_text()
    for name, b in RP.build().items():
        assert _yaml_bytes(text, name) == b, name


def test_sites_pinned():
    """Every replay_scale site and dw_scale's item-draw stub, as the yaml writes them."""
    import re
    text = _yaml_text().replace("\r\n", "\n")
    for sid, _fn, va, orig, new, _pat, _note in RP.NEW_SITES:
        i = text.index(f"  - id: {sid}\n")
        blk = text[i:text.index("    pattern:", i)]
        assert f"virtual_addr: 0x{va:08X}" in blk and f'original_bytes: "{orig}"' in blk and f'new_bytes:      "{new}"' in blk
    i = text.index("  - id: FlatButton_itemdraw_stub\n")
    blk = text[i:text.index("    pattern:", i)]
    assert "virtual_addr: 0x00404220" in blk and 'original_bytes: "33 C0 C2 0C 00"' in blk
    want = " ".join(f"{x:02X}" for x in RP.itemdraw_site_bytes())
    assert re.search(rf'new_bytes:\s+"{want}"', blk), blk


def test_no_other_chain_head_targets_thunk_dw_btndraw(baked_exe):
    """thunk_dw_btndraw is reached ONLY through t_rp_btndraw: no other E8 / E9 rel32 in the baked image's executable
    sections points at it, and the 0x404220 stub jumps to t_rp_btndraw."""
    data = Path(baked_exe).read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec, opt = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    base = struct.unpack_from("<I", data, pe + 52)[0]
    hits, site = [], None
    for k in range(nsec):
        off = pe + 24 + opt + 40 * k
        vsize, rva, rsize, raw = struct.unpack_from("<IIII", data, off + 8)
        chars = struct.unpack_from("<I", data, off + 36)[0]
        if not chars & 0x20000000:                         # IMAGE_SCN_MEM_EXECUTE
            continue
        blob = np.frombuffer(data[raw:raw + min(vsize, rsize)], np.uint8)
        va0 = base + rva
        idx = np.flatnonzero((blob[:-4] == 0xE8) | (blob[:-4] == 0xE9))
        rel = sum(blob[idx + 1 + k].astype(np.int64) << (8 * k) for k in range(4))   # vectorised rel32 (unsigned)
        tgt = (va0 + idx.astype(np.int64) + 5 + rel) & 0xFFFFFFFF
        hits += [va0 + int(i) for i in idx[tgt == RP.THUNK_DW_BTNDRAW]]
        if va0 <= 0x404220 < va0 + vsize:
            site = blob[0x404220 - va0:0x404225 - va0].tobytes()
    assert hits == [RP.PCAVE2 + RP.SLOTS["t_rp_btndraw"] + _btndraw_pass_off()], [hex(v) for v in hits]
    assert site == RP.itemdraw_site_bytes()


def _btndraw_pass_off() -> int:
    """Offset of t_rp_btndraw's `jmp thunk_dw_btndraw` (the last instruction)."""
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    b = RP.build()["t_rp_btndraw"]
    va = RP.PCAVE2 + RP.SLOTS["t_rp_btndraw"]
    last = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va))[-1]
    assert last.mnemonic == "jmp" and int(last.op_str, 16) == RP.THUNK_DW_BTNDRAW
    return last.address - va


class _Uc:
    STOPS = (RP.REPLAYWIN_BUILD, RP.GRAPHICWIN_INIT_2, RP.MAPWIN_INIT, RP.BASEBUTTON_INIT, RP.T_NWF_BOX,
             RP.THUNK_DW_BTNDRAW, RP.FULLGUARD)

    def __init__(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mapped = set()
        for va in (G_VA, RP.PCAVE2 + 0x46000, RP.PCAVE2 + 0x40000, RP.PCAVE2 + 0x17000, 0x10000000, 0x10010000,
                   0x20000000, RP.MAP_AREA_X, RP.SCREEN_W, 0x30000000, 0x30010000, 0x30020000,
                   0x30030000) + self.STOPS:
            base = va & ~0xFFFF
            if base not in mapped:
                self.mu.mem_map(base, 0x10000)
                mapped.add(base)
        self.reload()

    def reload(self):
        for name, b in RP.build().items():
            self.mu.mem_write(RP.PCAVE2 + RP.SLOTS[name], b)
        for va in self.STOPS:
            self.mu.mem_write(va, b"\xF4")                 # hlt: stop at every target, its own code is not ours

    def run(self, entry, g, stack, regs, cell=0, eflags=0x202, count=400, map_cell=0):
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EFLAGS
        mu = self.mu
        mu.mem_write(G_VA, struct.pack("<I", g))
        mu.mem_write(G_STRIPE_PERIOD, struct.pack("<I", SL.stripe_period(g)))
        mu.mem_write(RP.G_RP_BTN, struct.pack("<I", cell))
        mu.mem_write(RP.G_RP_MAP, struct.pack("<I", map_cell))
        esp = 0x1000F000
        mu.mem_write(esp, b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in stack))
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.reg_write(UC_X86_REG_EFLAGS, eflags)
        for r, v in regs.items():
            mu.reg_write(r, v)
        try:
            mu.emu_start(entry, 0xFFFFFFFF, count=count)
        except Exception:
            pass
        return mu.reg_read(UC_X86_REG_EIP) - 1, mu.reg_read(UC_X86_REG_ESP)

    def stack(self, n, esp=0x1000F000):
        return list(struct.unpack(f"<{n}I", bytes(self.mu.mem_read(esp, 4 * n))))

    def cell(self, va=RP.G_RP_BTN):
        return struct.unpack("<i", bytes(self.mu.mem_read(va, 4)))[0]


@pytest.fixture(scope="module")
def uc():
    return _Uc()


def _regs():
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI,
                                   UC_X86_REG_EDI, UC_X86_REG_EBP)
    return {UC_X86_REG_EAX: 0x1111, UC_X86_REG_EBX: 0x2222, UC_X86_REG_ECX: 0x00777000, UC_X86_REG_EDX: 0x4444,
            UC_X86_REG_ESI: 0x5555, UC_X86_REG_EDI: 0x6666, UC_X86_REG_EBP: 0x7777}


RECT = 0x20000100
STOP = 0x1000E000


def _rect(mu):
    return struct.unpack("<4i", bytes(mu.mem_read(RECT, 16)))


@pytest.mark.parametrize("g", range(1, 65))
@pytest.mark.parametrize("world", WORLDS + ((16, 16), (20, 40), (50, 50), (34, 34), (286, 143), (358, 180), (512, 256),
                                            (1024, 512)))
@pytest.mark.parametrize("screen", ("tight", "named"))
def test_winsize_is_the_law(uc, g, world, screen):
    """The window rect -> replay_window(g, X, Y, ScreenWidth, ScreenHeight) and g_rp_z := replay_map_zoom at g > 16;
    g <= 16 the rect untouched.  Every register kept, the stack as it came (a tail jump into GraphicWin_init_2)."""
    x, y = world
    sw, sh = tight_screen(max(16, min(g, 40))) if screen == "tight" else screen_of(max(16, min(g, 40)))
    uc.mu.mem_write(RP.SCREEN_W, struct.pack("<2i", sw, sh))
    uc.mu.mem_write(RP.MAP_AREA_X, struct.pack("<2i", x, y))
    uc.mu.mem_write(RP.G_RP_Z, struct.pack("<i", 777))
    uc.mu.mem_write(RECT, struct.pack("<4i", 0, 0, 800, 600))
    regs = _regs()
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_winsize"], g, [0x5AD777, RECT, 0, 0x1000000], regs)
    assert eip == RP.GRAPHICWIN_INIT_2 and esp == 0x1000F000
    if g <= 16:
        assert _rect(uc.mu) == (0, 0, 800, 600) and uc.cell(RP.G_RP_Z) == 777
    else:
        assert _rect(uc.mu) == (0, 0) + SL.replay_window(g, x, y, sw, sh), (g, world)
        assert uc.cell(RP.G_RP_Z) == SL.replay_map_zoom(x, y, g)
    for r, v in regs.items():
        assert uc.mu.reg_read(r) == v
    assert uc.stack(4) == [0x5AD777, RECT, 0, 0x1000000]


@pytest.mark.parametrize("g", (1, 16, 17, 22, 40, 64))
def test_zoom_store(uc, g):
    """0x5AD85E: g > 16 stores g_rp_z, else edi; every register kept, a CALL site (returns to site + 5)."""
    from unicorn.x86_const import UC_X86_REG_EDI, UC_X86_REG_ESI
    mu = uc.mu
    obj = 0x30000000
    mu.mem_write(obj + RP.ZOOM_FIELD, struct.pack("<i", 12345))
    mu.mem_write(RP.G_RP_Z, struct.pack("<i", -8))
    mu.mem_write(STOP, b"\xF4")
    regs = _regs()
    regs.update({UC_X86_REG_EDI: (-13) & 0xFFFFFFFF, UC_X86_REG_ESI: obj})
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_zoom"], g, [STOP], regs)
    assert eip == STOP and esp == 0x1000F004
    assert struct.unpack("<i", bytes(mu.mem_read(obj + RP.ZOOM_FIELD, 4)))[0] == (-8 if g > 16 else -13)
    for r, v in regs.items():
        assert mu.reg_read(r) == v


@pytest.mark.parametrize("g", range(1, 65))
def test_maprect_is_the_law(uc, g):
    w, h = (800, 600) if g <= 16 else SL.replay_window(g, 80, 80, *tight_screen(min(g, 40)))
    uc.mu.mem_write(RECT, struct.pack("<4i", 3, 26, w - 3, h - 26))       # what the builder's native insets left
    regs = _regs()
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_maprect"], g, [0x5AD83D, RECT, 0, 0x20], regs)
    assert eip == RP.MAPWIN_INIT and esp == 0x1000F000
    assert _rect(uc.mu) == (SL.replay_map_rect(w, h, g) if g > 16 else (3, 26, 797, 574))
    for r, v in regs.items():
        assert uc.mu.reg_read(r) == v


@pytest.mark.parametrize("g", range(1, 65))
def test_close_is_the_law(uc, g):
    w, h = (800, 600) if g <= 16 else SL.replay_window(g, 48, 48, *tight_screen(min(g, 40)))
    ml, mt, mr, mb = SL.replay_map_rect(w, h, g) if g > 16 else VANILLA["map"]
    stack = [0x5AD8E2, 0xABCDEF, 0xFFFFFFFF, ml, mb + 3, mr - ml, 0x14, 0x123000, 0]
    regs = _regs()
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_close"], g, stack, regs)
    assert eip == RP.BASEBUTTON_INIT and esp == 0x1000F000
    cl, ct, cr, cb = SL.replay_close_rect(w, h, g) if g > 16 else VANILLA["close"]
    assert uc.stack(9) == [0x5AD8E2, 0xABCDEF, 0xFFFFFFFF, cl, ct, cr - cl, cb - ct, 0x123000, 0]
    for r, v in regs.items():
        assert uc.mu.reg_read(r) == v


@pytest.mark.parametrize("g", range(1, 65))
def test_title_is_the_law(uc, g):
    w = 800 if g <= 16 else SL.replay_window_wh(g)[0]
    uc.mu.mem_write(RECT, struct.pack("<4i", 4, 4, w - 4, 0x18))
    regs = _regs()
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_title"], g, [0x5AD688, RECT, 0x78D618], regs)
    assert eip == RP.T_NWF_BOX and esp == 0x1000F000
    assert _rect(uc.mu) == (SL.replay_title_box(w, g) if g > 16 else (4, 4, w - 4, 0x18))
    for r, v in regs.items():
        assert uc.mu.reg_read(r) == v


@pytest.mark.parametrize("g", (1, 16, 17, 22, 40, 64))
def test_bracket_sets_calls_and_clears(uc, g):
    """Every g: g_rp_map := ecx + 0x2320 (the row fix is vanilla's bug); g > 16 also g_rp_btn := ecx + 0x247A0; CALL
    ReplayWin_build (a return address pushed), ecx kept; the return path clears both cells and returns to the site."""
    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP
    regs = _regs()
    regs[UC_X86_REG_ECX] = 0x1001000
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_bracket"], g, [0x5ADC98], regs)
    assert eip == RP.REPLAYWIN_BUILD and uc.mu.reg_read(UC_X86_REG_ECX) == 0x1001000
    assert esp == 0x1000F000 - 4 and uc.cell(RP.G_RP_MAP) == 0x1001000 + RP.MAP_OFF
    assert uc.cell() == (0x1001000 + RP.CLOSE_BTN_OFF if g > 16 else 0)
    mu = uc.mu
    ret_into = struct.unpack("<I", bytes(mu.mem_read(esp, 4)))[0]
    mu.reg_write(UC_X86_REG_ESP, esp + 4)
    mu.mem_write(STOP, b"\xF4")
    mu.mem_write(0x1000F000, struct.pack("<I", STOP))
    try:
        mu.emu_start(ret_into, 0xFFFFFFFF, count=50)
    except Exception:
        pass
    assert mu.reg_read(UC_X86_REG_EIP) - 1 == STOP and uc.cell() == 0 and uc.cell(RP.G_RP_MAP) == 0
    assert mu.reg_read(UC_X86_REG_ESP) == 0x1000F004


BTN = 0x1024C7A0
PARENT = BTN - RP.CLOSE_BTN_OFF


@pytest.mark.parametrize("cell,arg,ecx,eflags", [
    (0, 0x00701234, 0x777000, 0x202), (0, 0x00701234, 0x777000, 0x8D7),            # no replay running
    (BTN, 0x00701234, 0x777000, 0x246), (BTN, BTN + 4, PARENT, 0xA93),             # a replay running, another button
    (BTN, BTN, 0x777000, 0x283),                                                    # the cell's button, foreign parent
])
def test_btndraw_passes_every_other_button_untouched(uc, cell, arg, ecx, eflags):
    """(build owner's condition c) a non-Replay button reaches thunk_dw_btndraw exactly as if the stub jumped there
    directly: same eip target, same esp, every register, every flag, every stack dword."""
    from unicorn.x86_const import UC_X86_REG_EFLAGS, UC_X86_REG_ECX
    stack = [0x6083AE, arg, 0x8A0000, 0x1C]
    regs = _regs()
    regs[UC_X86_REG_ECX] = ecx
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_btndraw"], 40, stack, regs, cell=cell, eflags=eflags)
    assert eip == RP.THUNK_DW_BTNDRAW and esp == 0x1000F000
    assert uc.stack(4) == stack
    for r, v in regs.items():
        assert uc.mu.reg_read(r) == v
    assert uc.mu.reg_read(UC_X86_REG_EFLAGS) & 0xFD5 == eflags & 0xFD5


def test_btndraw_routes_this_windows_close_button():
    from unicorn.x86_const import UC_X86_REG_EFLAGS, UC_X86_REG_ECX
    own = _Uc()                                  # its own emulator: a hlt written over code Unicorn already ran sticks
    face = RP.PCAVE2 + RP.SLOTS["t_rp_face"]
    own.mu.mem_write(face, b"\xF4")
    stack = [0x6083AE, BTN, 0x8A0000, 0x1C]
    regs = _regs()
    regs[UC_X86_REG_ECX] = PARENT
    eip, esp = own.run(RP.PCAVE2 + RP.SLOTS["t_rp_btndraw"], 40, stack, regs, cell=BTN, eflags=0x893)
    assert eip == face and esp == 0x1000F000 and own.stack(4) == stack
    for r, v in regs.items():
        assert own.mu.reg_read(r) == v
    assert own.mu.reg_read(UC_X86_REG_EFLAGS) & 0xFD5 == 0x893 & 0xFD5


MW = 0x30000000                  # a fake MapWin (Console): fields to +0x1DDD8; its vtable at MW_VT, GraphicWin at +MW_VB
MW_VT, MW_VB = 0x30020000, 0x21000
ROWS = RP.PCAVE2 + 0x46500


def _mapwin(mu, top, u, x, y, cw, ch, pxl=77, pxt=114, oddx=None, oddy=None):
    mu.mem_write(MW, struct.pack("<I", MW_VT))
    mu.mem_write(MW_VT, struct.pack("<II", 0, MW_VB))
    mu.mem_write(MW + MW_VB + 0x4C4, struct.pack("<ii", cw, -ch))
    for off, v in ((0x1DDA8, top), (0x1DDAC, pxl), (0x1DDB0, pxt), (0x1DDC8, u),
                   (0x1DDCC, x // 2 if oddx is None else oddx), (0x1DDD0, y // 2 if oddy is None else oddy)):
        mu.mem_write(MW + off, struct.pack("<i", v))
    mu.mem_write(RP.MAP_AREA_X, struct.pack("<2i", x, y))


def _mw(mu, off):
    return struct.unpack("<i", bytes(mu.mem_read(MW + off, 4)))[0]


@pytest.mark.parametrize("cell", (0, 0x9156B0, MW + 0x10))
@pytest.mark.parametrize("eflags", (0x202, 0x8D7))
def test_rows_passes_every_other_mapwin_untouched(uc, cell, eflags):
    """(build owner's condition c) the main map (esi = MapWin_g 0x9156B0) or any MapWin that is not the live replay's
    reaches thunk_drawmap_fullguard exactly as the site left it: same esp, every register, every flag, nothing
    written to the MapWin."""
    from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EFLAGS
    _mapwin(uc.mu, -2, 2, 80, 80, 794, 548)
    before = bytes(uc.mu.mem_read(MW + 0x1DD00, 0x100))
    regs = _regs()
    regs.update({UC_X86_REG_ESI: MW, UC_X86_REG_EDI: 0})
    eip, esp = uc.run(ROWS, 40, [0x46A5B4], regs, eflags=eflags, map_cell=cell)
    assert eip == RP.FULLGUARD and esp == 0x1000F000 and uc.stack(1) == [0x46A5B4]
    for r, v in regs.items():
        assert uc.mu.reg_read(r) == v
    assert uc.mu.reg_read(UC_X86_REG_EFLAGS) & 0xFD5 == eflags & 0xFD5
    assert bytes(uc.mu.mem_read(MW + 0x1DD00, 0x100)) == before


@pytest.mark.parametrize("g", (16, 17, 22, 25, 40))
@pytest.mark.parametrize("top", (-2, -1, 0, 1, 3, 4))
@pytest.mark.parametrize("u,x,y,cw,ch", ((2, 80, 80, 794, 548), (6, 80, 80, 1986, 1370), (8, 48, 48, 1580, 1110),
                                         (3, 64, 64, 1092, 753)))
def test_rows_is_the_law(uc, g, top, u, x, y, cw, ch):
    """The live replay's MapWin, whole world shown: top -> -(top & 1), pixel_top shifted 2u(top' - top) (every placed
    row stays put) at every g; at g > 16 pixel_left / pixel_top centred (replay_map_origin).  Registers / flags /
    stack as they came, then thunk_drawmap_fullguard."""
    from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EFLAGS
    _mapwin(uc.mu, top, u, x, y, cw, ch)
    regs = _regs()
    regs.update({UC_X86_REG_ESI: MW, UC_X86_REG_EDI: 0})
    eip, esp = uc.run(ROWS, g, [0x46A5B4], regs, eflags=0x246, map_cell=MW, count=2000)
    assert eip == RP.FULLGUARD and esp == 0x1000F000
    for r, v in regs.items():
        assert uc.mu.reg_read(r) == v
    assert uc.mu.reg_read(UC_X86_REG_EFLAGS) & 0xFD5 == 0x246 & 0xFD5
    top2, left, ty = SL.replay_map_origin(cw, ch, u, x, y, top, g)
    assert _mw(uc.mu, 0x1DDA8) == top2
    if g <= 16:
        assert _mw(uc.mu, 0x1DDAC) == 77 and _mw(uc.mu, 0x1DDB0) == 114 + ty
    else:
        assert (_mw(uc.mu, 0x1DDAC), _mw(uc.mu, 0x1DDB0)) == (left, ty)


def test_rows_leaves_a_partial_view_alone(uc):
    """Not the whole world (oddX < X/2: e.g. a huge custom world at the fit's floor): nothing touched."""
    from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EDI
    _mapwin(uc.mu, -2, 1, 400, 200, 794, 548, oddx=50)
    before = bytes(uc.mu.mem_read(MW + 0x1DD00, 0x100))
    regs = _regs()
    regs.update({UC_X86_REG_ESI: MW, UC_X86_REG_EDI: 0})
    eip, _ = uc.run(ROWS, 40, [0x46A5B4], regs, map_cell=MW)
    assert eip == RP.FULLGUARD and bytes(uc.mu.mem_read(MW + 0x1DD00, 0x100)) == before


FACE_BTN, FACE_BITS = 0x30000000, 0x30010000


def _bright(a, b):
    return a if a in (238, 224) else b


@pytest.mark.parametrize("g", (17, 18, 22, 25, 33, 40))
@pytest.mark.parametrize("ytop", (577, 578, 1443, 0))
@pytest.mark.parametrize("state", (0, 2))
def test_face_restripe_and_notch(uc, g, ytop, state):
    """t_rp_face on a synthetic canvas laid as the engine draws a box face (the art's 1-row dither from its own row 0,
    a 1 x 1 corner key, a label colour inside): every face pixel -> the bright member on stripe_top(parent row),
    the dark one elsewhere, nothing else touched but the four s x s corners (key 9); ret 0xC, eax 0, ebx / esi / edi /
    ebp kept."""
    from unicorn.x86_const import UC_X86_REG_EAX
    bright, dark = RP.FACE_PAIRS[0 if state == 0 else 1]
    w, h = 37, 11
    stride = (w + 3) & ~3
    art = np.zeros((h, stride), np.uint8)
    for y in range(h):
        art[y, :w] = dark if y % 2 == 0 else bright                     # vanilla's art: row 0 dark
    art[3:6, 10:15] = 0x41                                               # label-coloured pixels: never touched
    art[0, 0] = art[0, w - 1] = art[h - 1, 0] = art[h - 1, w - 1] = RP.KEY
    mu = uc.mu
    mu.mem_write(FACE_BITS, art.tobytes())
    btn = bytearray(0x4A0)
    struct.pack_into("<i", btn, 0x140, ytop - 7)
    struct.pack_into("<i", btn, 0x150, 7)
    struct.pack_into("<i", btn, 0x47C, w)
    struct.pack_into("<i", btn, 0x480, -h)
    struct.pack_into("<I", btn, 0x498, FACE_BITS)
    mu.mem_write(FACE_BTN, bytes(btn))
    mu.mem_write(STOP, b"\xF4")
    regs = _regs()
    eip, esp = uc.run(RP.PCAVE2 + RP.SLOTS["t_rp_face"], g, [STOP, FACE_BTN, 0x8A0000, 0x1C], regs, count=200000)
    assert eip == STOP and esp == 0x1000F010 and uc.mu.reg_read(UC_X86_REG_EAX) == 0
    for r, v in regs.items():
        if r != UC_X86_REG_EAX and r not in _clobbered():
            assert mu.reg_read(r) == v
    got = np.frombuffer(bytes(mu.mem_read(FACE_BITS, stride * h)), np.uint8).reshape(h, stride)[:, :w]
    s = SL.btn_corner_notch(g)
    want = art[:, :w].copy()
    for y in range(h):
        row = want[y]
        face = (row == bright) | (row == dark)
        row[face] = bright if SL.stripe_top(ytop + y, g) else dark
    for yy in list(range(s)) + list(range(h - s, h)):
        for xx in list(range(s)) + list(range(w - s, w)):
            want[yy, xx] = RP.KEY
    assert (got == want).all(), np.argwhere(got != want)[:6].tolist()


def _clobbered():
    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EDX
    return (UC_X86_REG_ECX, UC_X86_REG_EDX)


# ============================================================================================ layer 3: the real image
STROKE_D690, STROKE_D618 = 0x1A, 0x22
VEH_DRAW, BASE_DRAW = 0x5594F0, 0x55AF20
LABEL_CENTRED, LABEL_FALLBACK = 0x608441, 0x60844E


def _world(e, x, y):
    """A world in memory: an ocean frame around a land block owned by factions 1..4, one visible vehicle on land."""
    n = x * y // 2
    tiles = e.alloc(n * 44)
    raw = bytearray(n * 44)
    for k in range(n):
        tx, ty = k % (x // 2), k // (x // 2)
        land = x // 16 <= tx < x // 2 - x // 16 and y // 8 <= ty < y - y // 8
        owner = (1 + (4 * tx) // (x // 2)) if land else -1
        raw[44 * k:44 * k + 8] = bytes([(4 if land else 1) << 5, 0, 0x0F, 1, 0xFF, 0, 0, owner & 0xFF])
    vx, vy = 2 * (x // 4) + ((y // 2) % 2), y // 2
    raw[44 * (vy * (x // 2) + vx // 2) + 2] = 0x01
    e.uc.mem_write(tiles, bytes(raw))
    e.w32(0x94A30C, tiles)
    e.w32(0x949884, n)
    e.w32(0x949870, x)
    e.w32(0x949874, y)
    e.uc.mem_write(0x952828, struct.pack("<hhIHh", vx, vy, 0, 0, 0) + bytes([0, 1]))     # Vehs[0]
    e.w32(0x9A64C8, 1)                                                                     # VehCount
    return vx, vy


def replay_run(exe, g, world=STD, state=0, centre=(0, 0)):
    """show_replay on the real image over a world in memory: the window / button / map-child canvases, what the
    builder handed the engine, the text draws, the label's path, the unit / base drawer calls."""
    import image_emu as E
    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_ESI, UC_X86_REG_EDI
    W, H = SCREENS[g]
    x, y = world
    e = E.boot(str(exe), W, H)
    E.Files(e)
    e.call(0x455610, count=0)                                   # load_interface (the box sprite params)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))             # the label table ("Close")
    e.call(0x616A00, count=50_000_000)
    # g_popup_title_font (0x7CFE8C, the title and Close label font) is the HUD strip's fontA14 that MainWin's build
    # Font_inits (not run here): seed it as the game has it -- Arial 14 bold at g 16, the shipped HUD font thunk's
    # size above (font_direct_law) -- so the label's metrics, and so its centring path, are the engine's
    size = 14 if g <= 16 else SL.font_direct_law(14, 1, g)[1]
    e.call(0x618F40, ecx=0x7CFE8C, args=(e.cstr("Arial"), size, 1))
    # code edits right after boot (Unicorn ignores writes to code it already ran)
    e.uc.mem_write(0x5AD981, b"\x8B\xCE\xE8" + struct.pack("<i", 0x5AD610 - 0x5AD988) + b"\x90" * 6)  # modal -> draw
    e.uc.mem_write(0x5AD942, b"\x83\xC4\x04")                   # MapWin vtbl+4 (the map window's show): skip
    _world(e, x, y)
    e.w32(0x9392C0, centre[0])                                  # the faction's view centre (DAT_009392b8 = 0)
    e.w32(0x939340, centre[1])
    for va in (0x5A94F0, 0x5A9760, 0x616860, 0x616870):        # save / load daemon, Time_set / release_modal
        e.stub_fn(va, lambda e: 0)
    e.stub_fn(0x616350, lambda e: 0, popbytes=16)               # Time_start(fn, self, 100, 5)
    rec = dict(texts=[], label=[], calls={VEH_DRAW: 0, BASE_DRAW: 0}, tiles=[])
    sp = lambda e, k: e.r32(e.reg(UC_X86_REG_ESP) + k)  # noqa: E731

    def at(name, f):
        def cb(e):
            rec[name] = f(e)
        return cb

    def seed_base(e):                                           # one base in the replay's own table -> apply_bases
        w = e.reg(UC_X86_REG_ESI)
        e.w32(w + 0xA20, 2 * (x // 4))
        e.w32(w + 0xA24, y // 4 * 2)
        e.w32(w + 0xA28, 2)
    e.observe(0x5ADC93, at("win", lambda e: e.reg(UC_X86_REG_ECX)))
    e.observe(0x5AD859, at("maprect", lambda e: tuple(e.s32(sp(e, 0) + 4 * i) for i in range(4))))
    e.observe(0x5AD981, seed_base)
    if state:
        e.observe(0x5AD922, lambda e: e.w32(e.reg(UC_X86_REG_EDI) + 0xAB8, state))   # forced face state, then repaint
    e.observe(0x5ADC98, lambda e: e.uc.emu_stop())              # back in show_replay, before GraphicWin_close
    e.observe(0x5DCAE0, lambda e: rec["texts"].append((e.reg(UC_X86_REG_ECX), e.rstr(sp(e, 4), 40))))
    e.observe(0x5DD130, lambda e: rec.__setitem__("title_rect", (e.reg(UC_X86_REG_ECX),
                                                                 tuple(e.s32(sp(e, 8) + 4 * i) for i in range(4)))))
    e.observe(LABEL_CENTRED, lambda e: rec["label"].append(("centred", e.reg(UC_X86_REG_ESI),
                                                            tuple(e.s32(e.reg(UC_X86_REG_ESP) + 4 * i)
                                                                  for i in (1, 2, 3)))))
    e.observe(LABEL_FALLBACK, lambda e: rec["label"].append(("fallback", e.reg(UC_X86_REG_ESI), ())))
    def tile(e):                                                # MapWin_gen_terrain_poly(buf, console, ..., x, y, px, py)
        esp = e.reg(UC_X86_REG_ESP)
        if "win" in rec and e.r32(esp + 8) == rec["win"] + RP.MAP_OFF:      # the replay's map, not the HUD minimap
            rec["tiles"].append(tuple(e.s32(esp + 4 + 4 * i) for i in (6, 7, 8, 9)))
    e.observe(0x4632D0, tile)
    for va in (VEH_DRAW, BASE_DRAW):
        e.observe(va, (lambda va: lambda e: rec["calls"].__setitem__(va, rec["calls"][va] + 1))(va))
    try:
        e.call(0x5ADBF0, count=4_000_000_000)
    except RuntimeError as err:
        if "stopped" not in str(err):
            raise
    win = rec["win"]
    btn = win + RP.CLOSE_BTN_OFF
    mw = win + 0x2320
    child = mw + e.r32(e.r32(mw) + 4)                           # the MapWin's GraphicWin (its virtual base)
    out = dict(g=e.r32(E.GSCALE), win=E.canvas_of(e, win), btn=E.canvas_of(e, btn), child=E.canvas_of(e, child),
               maprect=rec["maprect"], zoom=e.s32(win + RP.ZOOM_FIELD), u=e.s32(mw + 4 * 0x7772),
               btn_y=e.s32(btn + 0x140) + e.s32(btn + 0x150), base_count=e.s32(0x9A64CC),
               texts=[("win" if c == win + 0x444 else "btn" if c == btn + 0x444 else hex(c), s) for c, s in rec["texts"]],
               title_rect=rec.get("title_rect"), win_buf=win + 0x444,
               label=[(k, a) for k, b, a in rec["label"] if b == btn], calls=rec["calls"], tiles=rec["tiles"])
    import checkbox_emu as CE
    CE._free(e)
    return out


@pytest.fixture(scope="module")
def pristine16(bak_path):
    return replay_run(bak_path, 16)


def _rows_placed(tiles, x, y, u, cw):
    """Every world row drawn exactly once per tile, every tile on the map's span [left, left + 4u(X+1))."""
    import collections
    per = collections.Counter(ty for _, ty, _, _ in tiles)
    assert sorted(per) == list(range(y)) and set(per.values()) == {x // 2}, (sorted(set(range(y)) - set(per)), per)
    pxs = [px for _, _, px, _ in tiles]
    return min(pxs), max(pxs)


def test_g16_equals_the_pristine_exe_but_the_fixed_last_row(baked_exe, pristine16):
    """1024 x 768: the window, the Close bar and the map are vanilla's pixel for pixel, except the world's last row,
    which vanilla draws half a world to the left (MapWin_tile_to_pixel's row window ends one row short of
    MapWin_gen_map's loop when the top row clamps to -2) and t_rp_rows puts in its place."""
    a = replay_run(baked_exe, 16)
    assert a["g"] == 16
    for k in ("win", "btn"):
        assert a[k].shape == pristine16[k].shape and (a[k] == pristine16[k]).all(), k
    assert a["maprect"] == pristine16["maprect"] == VANILLA["map"] and a["zoom"] == pristine16["zoom"] == -13
    assert a["title_rect"][1] == VANILLA["text"]
    old = {(tx, ty): (px, py) for tx, ty, px, py in pristine16["tiles"]}
    new = {(tx, ty): (px, py) for tx, ty, px, py in a["tiles"]}
    assert old.keys() == new.keys()
    moved = {k for k in old if old[k] != new[k]}
    assert moved and {ty for _, ty in moved} == {79}, sorted({ty for _, ty in moved})
    assert {new[k][0] for k in moved} == {old[(tx, 77)][0] for tx, _ in moved}      # row 79 = row 77's columns
    diff = np.argwhere(a["child"] != pristine16["child"])
    ink = np.argwhere(pristine16["child"] != 0)
    assert len(diff) and diff[:, 0].min() >= ink[:, 0].max() - 4 * 2 - 4 * 2, diff[:, 0].min()   # bottom rows only
    lo, hi = _rows_placed(a["tiles"], 80, 80, 2, 794)
    assert (lo, hi) == (77 - 8, 77 + 16 * 39)
    assert not _clipped_rows(a["child"], 2, stray=False)


def _member_law(col, y0, g, bright):
    """Every pixel of col (row y0 first) is one of two members, the BRIGHT one exactly on stripe_top rows."""
    vals = sorted(set(col.tolist()))
    assert len(vals) == 2 and bright in vals, vals
    dark = vals[0] if vals[1] == bright else vals[1]
    for i, v in enumerate(col.tolist()):
        assert v == (bright if SL.stripe_top(y0 + i, g) else dark), (y0 + i, v, bright, dark)


def _palette_bright(a, b):
    import checkbox_emu as CE
    p = CE.palette()
    return a if sum(int(v) for v in p[a]) >= sum(int(v) for v in p[b]) else b   # uint8 components: cast first


def _clipped_rows(child, u, stray=True):
    """Rows of the map cut at the child's left / right edge.  A diamond whose widest row just reaches the edge puts
    ink on ONE row there (its tip, every 4u rows); a cut diamond puts it on consecutive rows.  The engine's stray last
    half-row (vanilla's: it starts at the child's left edge, in the bottom 4u rows of the ink) is not counted."""
    ink = np.argwhere(child != 0)
    assert len(ink), "no map drawn"
    band = ink[:, 0].max() - 4 * u + 1 if stray else ink[:, 0].max() + 1
    out = []
    for col in (0, child.shape[1] - 1):
        rows = np.unique(ink[(ink[:, 1] == col) & (ink[:, 0] < band)][:, 0])
        out += rows[np.flatnonzero(np.diff(rows) == 1)].tolist()
    return out


def _unclipped(child, u):
    clipped = _clipped_rows(child, u)
    assert not clipped, f"map rows clipped at the child's side: {clipped[:6]}"
    assert not (child[0] != 0).any() and not (child[-1] != 0).any(), "map clipped at the child's top / bottom"


def test_the_clip_check_sees_vanillas_own_clip(bak_path):
    """Control for _clipped_rows on the engine's own render: the pristine exe at 1024 x 768 cuts ~3 px off the tiny
    world's alternate rows (MapWin_calculate_dimensions' centring); the check must see it, and see none on the
    standard world."""
    tiny = replay_run(bak_path, 16, (48, 48))
    assert tiny["u"] == 4 and len(_clipped_rows(tiny["child"], tiny["u"])) > 10
    std = replay_run(bak_path, 16)
    assert not _clipped_rows(std["child"], std["u"])


@pytest.mark.parametrize("g,world,state", E2E, ids=[f"g{g}-{w[0]}x{w[1]}-s{s}" for g, w, s in E2E])
def test_replay_on_the_laws(baked_exe, g, world, state):
    centre = CENTRES.get((g, world, state), (0, 0))
    o = replay_run(baked_exe, g, world, state, centre)
    assert o["g"] == g
    w, h, r = _laws(g, world, SCREENS[g])
    sw, sh = SCREENS[g]
    assert w <= sw and h <= sh
    # --- window, map child, zoom (option A: the fit on the un-grown window; the window grown where a row would clip)
    c = o["win"]
    assert c.shape == (h, w)
    assert o["maprect"] == r["map"]
    assert o["zoom"] == SL.replay_map_zoom(*world, g) and o["u"] == SL.map_u_of_zoom(o["zoom"])
    # --- the engine's own map render: no row clipped; no unit / base drawing at these zooms (z >= -8 included)
    ml, mt, mr, mb = r["map"]
    assert o["child"].shape == (mb - mt, mr - ml)
    if o["zoom"] <= SL.REPLAY_BLANK_ZOOM:      # the engine draws no map (vanilla's replay is blank there too)
        assert (w, h) == SL.replay_window_wh(g) and not (o["child"] != 0).any()
    else:
        u, cw, chh = o["u"], mr - ml, mb - mt
        lo, hi = _rows_placed(o["tiles"], *world, u, cw)           # every row once, none half a world away
        assert hi + 8 * u - lo == 4 * u * (world[0] + 1)           # the span: 4u(X+1)
        assert not _clipped_rows(o["child"], u, stray=False)       # no stray row, no row cut
        assert not (o["child"][0] != 0).any() and not (o["child"][-1] != 0).any()
        ink = np.argwhere(o["child"] != 0)
        L, R = ink[:, 1].min(), cw - 1 - ink[:, 1].max()
        T, B = ink[:, 0].min(), chh - 1 - ink[:, 0].max()
        assert abs(L - R) <= 1 and abs(T - B) <= 1, (L, R, T, B)   # centred (the user's decision)
    assert o["base_count"] == 1 and o["calls"] == {VEH_DRAW: 0, BASE_DRAW: 0}, o["calls"]
    # --- strokes K, fills with the BRIGHT member on stripe_top rows (vanilla: bright on the window's even rows)
    K = SL.stroke_width(g)
    xx = w // 8                                                               # clear of the centred title text
    assert (c[:K, xx] == STROKE_D690).all() and c[K, xx] != STROKE_D690
    assert (c[h - K:, xx] == STROKE_D690).all() and (c[h // 2, :K] == STROKE_D690).all()
    tl, tt, tr, tb = r["title"]
    assert (c[tt:tt + K, xx] == STROKE_D618).all() and (c[tb - K:tb, xx] == STROKE_D618).all()
    assert (c[(tt + tb) // 2, tl:tl + K] == STROKE_D618).all() and (c[(tt + tb) // 2, tr - K:tr] == STROKE_D618).all()
    tcol = c[tt + K:tb - K, xx]
    _member_law(tcol, tt + K, g, _palette_bright(*sorted(set(tcol.tolist()))[:2]))
    wcol = c[K:tt, xx]
    _member_law(wcol, K, g, _palette_bright(*sorted(set(wcol.tolist()))[:2]))
    # --- the title: drawn in the window, into the law's text rect (glyphs are not emulated: centring in game)
    assert ("win", b"Replay") in o["texts"]
    assert o["title_rect"] == (o["win_buf"], r["text"])
    # --- the Close bar: geometry, every face row on the member law on the WINDOW grid, the s x s corner keys
    cl, ct, cr, cb = r["close"]
    b = o["btn"]
    bh, bw = b.shape
    assert (bh, bw) == (cb - ct, cr - cl) and o["btn_y"] == ct
    bright, dark = RP.FACE_PAIRS[0 if state == 0 else 1]
    s = SL.btn_corner_notch(g)
    for col in (s, bw // 8, bw - 1 - s):
        _member_law(b[:, col], ct, g, bright)
    for yy in (0, bh - 1):
        assert (b[yy, s:bw - s] != RP.KEY).all()
    for y0, x0 in ((0, 0), (0, bw - s), (bh - s, 0), (bh - s, bw - s)):
        assert (b[y0:y0 + s, x0:x0 + s] == RP.KEY).all(), (y0, x0)
    assert b[s, s] != RP.KEY and b[0, s] != RP.KEY and b[s, 0] != RP.KEY
    assert set(np.unique(b).tolist()) <= {bright, dark, RP.KEY}
    # --- the label: drawn on the centred path (not the fallback that left-aligned / ellipsised it at 4K), at x = 3,
    #     width w - 6, a non-negative top (the engine centres it on its own measured height)
    assert ("btn", b"Close") in o["texts"]
    assert o["label"] and all(k == "centred" for k, _ in o["label"]), o["label"]
    lx, ly, lw = o["label"][-1][1]
    assert lx == 3 and lw == bw - 6 and 0 <= ly <= bh // 2, o["label"]
