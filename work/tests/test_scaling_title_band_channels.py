"""In-game rail popups: the title band's RIGHT channel mirrors its left (fix 19, law popup_title_band_lr /
popup_title_band_right).

The baked image's REAL Popup_on_draw_background runs under Unicorn in the engine's own order, from the d690 backdrop
block to the title text: 0x405F04 Win_is_visible(MainWin) + the type test -> 0x405F24 thunk_popup_d690insets -> the backdrop draw through thunk_backdrop_railtrim (the
draw copy's R -> anchor - 1) -> 0x405F7C thunk_untitled_stash -> 0x405F91 the band's fresh rect -> Win_is_visible
(MainWin) -> 0x405FF1 thunk_popup_titleinsets -> the engine's `inc edx` @0x406027 -> thunk_title_height's dec ->
0x40603D the band stash -> 0x406048 the band draw (thunk_popup_bandstash: g_title_left / g_title_right) -> the
inner band (0x406078) -> the title text (0x4060E2).  Stand-ins: only the draw primitives (the two box-sprite draws
record their rect and RET 8), the font setters and the text writer.  The draws band-map their rect INCLUSIVE at
g > 16 (strokes [L, L+K) and (R-K, R]), the convention the three real shots reproduce.

deployed = the shipped bytes (thunk_popup_titleinsets' `inc eax` @0xA0F6EF); fixed = the nop.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
INC_VA = 0xA0F6EF                   # thunk_popup_titleinsets' R-store fold byte (v1 `inc eax`, v2 nop)
BACKDROP_DRAW = 0xA16920            # thunk_backdrop_railtrim's tail target (the d690 backdrop box draw)
BAND_DRAW = 0xA3A840                # thunk_popup_bandstash's / the inner band's tail target (thunk_box_thick_flat)
FONT1, FONT2, STRLEN, WRITE = 0x5DAC70, 0x5DACB0, 0x6453E0, 0x5DD130
MAINWIN = 0x7AE820
G_TITLE_L, G_TITLE_R = 0xA0CF00, 0xA0CF04
TITLEINSETS = 0xA0F6A0
HEAP = 0x20000000
POPUP = HEAP + 0x10000
RECT = HEAP + 0x40
FRAME = HEAP + 0x9000               # the caller's ebp
END = 0x4060E7


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return baked_exe.read_bytes()


class Chrome:
    def __init__(self, image: bytes, deployed: bool):
        pe = pefile.PE(data=image)
        ib = pe.OPTIONAL_HEADER.ImageBase
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(HEAP, 0x100000)
        assert bytes(mu.mem_read(INC_VA - 2, 6)) == bytes.fromhex("29D0") + b"\x90" + bytes.fromhex("8945F4"), \
            "thunk_popup_titleinsets v2 (the R fold is a nop)"
        if deployed:
            mu.mem_write(INC_VA, b"\x40")
        for va, n in ((BACKDROP_DRAW, 8), (BAND_DRAW, 8), (FONT1, 0x10), (FONT2, 0x10), (WRITE, 0xC)):
            mu.mem_write(va, b"\xC2" + struct.pack("<H", n))
        mu.mem_write(STRLEN, b"\xB8\x05\x00\x00\x00\xC3")        # mov eax,5; ret (cdecl)
        mu.mem_write(HEAP + 0x300, b"\xC2\x04\x00")              # the import @[0x66931C] (stdcall, 1 arg): ret 4
        self.w32(0x66931C, HEAP + 0x300)
        self.draws = []
        mu.hook_add(UC_HOOK_CODE, lambda m, a, s, u: self._rec("backdrop"), begin=BACKDROP_DRAW, end=BACKDROP_DRAW)
        mu.hook_add(UC_HOOK_CODE, lambda m, a, s, u: self._rec("band"), begin=BAND_DRAW, end=BAND_DRAW)
        mu.hook_add(UC_HOOK_CODE, lambda m, a, s, u: self._rec("text", 1), begin=WRITE, end=WRITE)
        self.insets_calls = 0
        mu.hook_add(UC_HOOK_CODE, self._count, begin=TITLEINSETS, end=TITLEINSETS)

    def _count(self, *a):
        self.insets_calls += 1

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def _rec(self, kind, argi=0):
        sp = self.mu.reg_read(UC_X86_REG_ESP)
        p = self.r32(sp + 4 + 4 * argi) & 0xFFFFFFFF
        self.draws.append((kind, tuple(self.r32(p + 4 * i) for i in range(4))))

    def run(self, win_r: int, g: int, ptype: int = 0, titled: bool = True, visible: bool = True):
        """Popup_on_draw_background's chrome for a window-local rect [0, win_r) x [0, 400): returns the recorded draws
        (kind, rect) in call order and the stash (g_title_left, g_title_right)."""
        mu = self.mu
        self.draws.clear()
        self.insets_calls = 0
        self.w32(G_VA, g)
        mu.mem_write(MAINWIN + 0x9C, b"\x01" if visible else b"\x00")
        mu.mem_write(POPUP, b"\0" * 0x3400)
        self.w32(POPUP + 0xA48, HEAP + 0x200 if titled else 0)
        self.w32(POPUP + 0x30AC, ptype * 10000)
        for a in (G_TITLE_L, G_TITLE_R, 0xA0E708):
            self.w32(a, 0x7EEEEEEE)
        for i, v in enumerate((0, 0, win_r, 400)):
            self.w32(RECT + 4 * i, v)
            self.w32(FRAME - 0x24 + 4 * i, v)                 # the d690 rect the engine built from the window rect
        self.w32(FRAME - 4, ptype)
        sp = FRAME - 0x400
        for r, v in ((UC_X86_REG_ESP, sp), (UC_X86_REG_EBP, FRAME), (UC_X86_REG_EBX, RECT), (UC_X86_REG_ESI, POPUP),
                     (UC_X86_REG_EDI, HEAP + 0x800), (UC_X86_REG_EAX, RECT)):
            mu.reg_write(r, v)
        mu.emu_start(0x405F04, END, count=200_000)                  # Win_is_visible(MainWin) -> the type test
        assert mu.reg_read(UC_X86_REG_EIP) == END
        assert mu.reg_read(UC_X86_REG_ESP) == sp, "stack balanced across the whole block"
        return list(self.draws), (self.r32(G_TITLE_L), self.r32(G_TITLE_R))


@pytest.fixture(scope="module")
def fixed(baked):
    return Chrome(baked, deployed=False)


@pytest.fixture(scope="module")
def deployed(baked):
    return Chrome(baked, deployed=True)


def _cols(draws, g):
    """Drawn stroke columns: backdrop / band / inner (L stroke first col, R stroke last col) + channels."""
    k = SL.stroke_width(g)
    d = {kind: [] for kind in ("backdrop", "band", "text")}
    for kind, rect in draws:
        d[kind].append(rect)
    (bd,), (band, inner), (text,) = d["backdrop"], d["band"], d["text"]
    return {"bd": (bd[0], bd[2]), "band": (band[0], band[2]), "inner": (inner[0], inner[2]), "text": (text[0], text[2]),
            "chan_L": band[0] - (bd[0] + k), "chan_R": (bd[2] - k + 1) - (band[2] + 1),
            "inner_L": inner[0] - (band[0] + k), "inner_R": (band[2] - k + 1) - (inner[2] + 1)}


WIN_RS = tuple(range(600, 2600, 37))


@pytest.mark.parametrize("g", range(17, 41))
def test_band_channels_mirror_on_every_width(fixed, deployed, g):
    k = SL.stroke_width(g)
    for win_r in WIN_RS:
        for ptype in (0, 5):
            fd, fs = fixed.run(win_r, g, ptype)
            dd, ds = deployed.run(win_r, g, ptype)
            f, d = _cols(fd, g), _cols(dd, g)
            assert f["chan_L"] == f["chan_R"] == (4 * g >> 4) - k, (g, win_r, f)
            assert d["chan_R"] == d["chan_L"] - 1, (g, win_r, d)                  # the shipped defect, every width
            assert f["bd"] == d["bd"] and f["band"][0] == d["band"][0] and f["band"][1] == d["band"][1] - 1
            assert f["band"] == SL.popup_title_band_lr(win_r, g), (g, win_r)
            # every band-derived element moves with R: the inner band, the title text rect, the stash
            assert f["inner_L"] == f["inner_R"] == d["inner_L"], (g, win_r, f)
            assert f["inner"][1] == d["inner"][1] - 1 and f["text"][1] == d["text"][1] - 1
            assert sum(f["text"]) == sum(f["bd"]) == sum(f["band"]), (g, win_r, "title text centred on the backdrop")
            assert fs == f["band"] and ds == d["band"], (g, win_r, fs, f["band"])
            # the stash's consumers mirror their g_title_left twin against the backdrop: the container / list ring
            cl, cr = SL.itemlist_container_edge_l(fs[0], g), SL.itemlist_container_edge_r(fs[1], g)
            assert cl - f["bd"][0] == f["bd"][1] - cr, (g, win_r)
            bl, br = SL.body_inner_edge_l(fs[0], g), SL.body_inner_edge_r(fs[1], g)
            assert bl - f["bd"][0] == f["bd"][1] - br, (g, win_r)
            assert fixed.insets_calls == deployed.insets_calls == 1


def test_g16_is_vanilla(fixed, deployed):
    for win_r in WIN_RS:
        for ptype in (0, 5):
            f, d = fixed.run(win_r, 16, ptype), deployed.run(win_r, 16, ptype)
            assert f == d
            c = _cols(f[0], 16)
            assert c["band"] == SL.popup_title_band_lr(win_r, 16) == (0x1B, win_r - 0x3B)


def test_untitled_stash_follows_the_band(fixed, deployed):
    """thunk_untitled_stash (0x405F7C) runs the same thunk_popup_titleinsets for an untitled popup: its virtual
    g_title_right is the titled band's R, in both builds."""
    for g in (17, 18, 22, 25, 40):
        for win_r in WIN_RS[::5]:
            for chrome in (fixed, deployed):
                _draws, stash_u = chrome.run(win_r, g, 0, titled=False)
                draws_t, stash_t = chrome.run(win_r, g, 0, titled=True)
                assert stash_u == stash_t == _cols(draws_t, g)["band"], (g, win_r)


def test_ornate_and_menu_popups_never_reach_titleinsets(fixed, deployed):
    """Types 2/6 (SELECT A FACTION in the editor: [+0x30AC] 60000 in the 4K dump) and MainWin-hidden popups take
    thunk_title_hmargin: the fix cannot move them."""
    for g in (16, 18, 22, 25, 40):
        for win_r in (848, 1037, 1038, 2049):
            for ptype, visible in ((2, True), (6, True), (0, False), (5, False), (6, False)):
                f = fixed.run(win_r, g, ptype, visible=visible)
                assert fixed.insets_calls == 0, (g, win_r, ptype, visible)
                assert f == deployed.run(win_r, g, ptype, visible=visible), (g, win_r, ptype, visible)


# ==== the real shots (SELECT DESTINATION, in game) ======================================================================
#: (shot, g, window screen x, window-local R (the 4K dump: local [0,0,2049,857]; 1080p / 1600x900: the widths the
#: deployed chain reproduces), measured: backdrop L stroke first col, backdrop R stroke last col, band L first col,
#: band R last col -- runs of 496c3d (backdrop) / 314e2c (band) on the band row (findband))
SHOTS = (
    ("3840x2160_20261022-204724", 40, 935, (2049,), (992, 2844, 1002, 2835)),
    ("1920x1080_20261022-205605", 22, 463, (1037, 1038), (494, 1423, 499, 1419)),
    ("1600x900_20261022-210127", 18, 394, (848,), (419, 1178, 423, 1175)),
)
#: the fixed band's right stroke last column per shot (1 px left; channels L/R)
FIXED = {"3840x2160_20261022-204724": (2834, 8, 8), "1920x1080_20261022-205605": (1418, 4, 4),
         "1600x900_20261022-210127": (1174, 3, 3)}


@pytest.mark.parametrize("shot", SHOTS, ids=[s[0] for s in SHOTS])
def test_real_shots(fixed, deployed, shot):
    name, g, x0, win_rs, (bl, br, tl, tr) = shot
    for win_r in win_rs:
        d = _cols(deployed.run(win_r, g)[0], g)
        assert (x0 + d["bd"][0], x0 + d["bd"][1], x0 + d["band"][0], x0 + d["band"][1]) == (bl, br, tl, tr), \
            (name, win_r, d)
        f = _cols(fixed.run(win_r, g)[0], g)
        assert (x0 + f["band"][1], f["chan_L"], f["chan_R"]) == FIXED[name]
        assert (d["chan_L"], d["chan_R"]) == (FIXED[name][1], FIXED[name][1] - 1)
