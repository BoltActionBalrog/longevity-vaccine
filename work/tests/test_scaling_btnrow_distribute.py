"""Popup bottom button rows: the button-width remainder is distributed, both row ends flush (fix 19, group
popup_btnrow_distribute; laws scaling_laws.popup_button_row_bounds / popup_button_row_slot).

The baked image's REAL code runs under Unicorn in the engine's own order: BasePop_calculate_dimensions' button-width
block 0x603FCB..0x604026 (the idiv, the 0x604012 store through t_btnrow_stash), then BasePop_exec_3 from 0x602C1B
(the row's y / the vcenter thunks, Popup_on_adjust_button_placement through the popup's vtable +0x178, OK (id -1,
0x602D66; flag 0x40 puts it second from the right), the custom #button loop 0x6030DC, Cancel (id -2, 0x60342B,
flag 0x40)) to 0x60367A.  Stand-ins only for
what allocates or paints: operator new, the FlatButton ctor (installs a stub vtable), BaseButton_init (records its
args; RET 0x20), the label-colour / font setters and the list-rotation rand.

A row button's x is right-relative (x < 0: its right edge = parent right + x; measured on the 4K and 1080p Rules
shots against the debugdump popup rects), so the screen cell is [P + x - w, P + x).

deployed = the four sites restored to vanilla in memory (the shipped behaviour).
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
POPUP_VTBL = 0x6695C8
BBI, NEW, CTOR, RAND = 0x607210, 0x64558A, 0x607CF0, 0x644F3A
RET10 = (0x5DAC70, 0x607360, 0x6073A0, 0x6073E0)
CALC_START, CALC_END = 0x603FCB, 0x604026
EXEC_START, EXEC_END = 0x602C1B, 0x60367A
SITES = {0x604012: bytes.fromhex("8986CC300000"), 0x602D66: bytes.fromhex("E8A5440000"),
         0x6030DC: bytes.fromhex("E82F410000"), 0x60342B: bytes.fromhex("E8E03D0000")}
HEAP = 0x20000000
POPUP = HEAP + 0x10000
FAKE_VT = HEAP + 0x100
STUBS = HEAP + 0x200
ARENA = HEAP + 0x40000
STACK = HEAP + 0x30000


@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return baked_exe.read_bytes()


class Row:
    def __init__(self, image: bytes, deployed: bool):
        pe = pefile.PE(data=image)
        ib = pe.OPTIONAL_HEADER.ImageBase
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(HEAP, 0x100000)
        for va, orig in SITES.items():
            assert bytes(mu.mem_read(va, len(orig))) != orig, f"site {va:#x} is not patched in the bake"
            if deployed:
                mu.mem_write(va, orig)
        mu.mem_write(STUBS, b"\xC2\x04\x00\xC3")                  # +0: ret 4 (show), +3: ret (redraw)
        self.w32(FAKE_VT + 4, STUBS)
        self.w32(FAKE_VT + 0xF8, STUBS + 3)
        mu.mem_write(BBI, b"\x31\xC0\xC2\x20\x00")                # xor eax,eax; ret 0x20
        mu.mem_write(RAND, b"\x31\xC0\xC3")
        for va in RET10:
            mu.mem_write(va, b"\xC2\x10\x00")
        mu.mem_write(CTOR, b"\xC7\x01" + struct.pack("<I", FAKE_VT) + b"\x89\xC8\xC3")   # [ecx]=vt; eax=ecx; ret
        mu.mem_write(NEW, b"\xC3")
        mu.hook_add(UC_HOOK_CODE, self._new, begin=NEW, end=NEW)
        mu.hook_add(UC_HOOK_CODE, self._bbi, begin=BBI, end=BBI)
        self.buttons, self.next, self.stop_direct = [], ARENA, False
        mu.hook_add(UC_HOOK_CODE, self._direct_ret, begin=0x6030E1, end=0x6030E1)

    def _direct_ret(self, mu, a, s, u):
        if self.stop_direct:                 # an `until` inside a cached block is not reliable: stop by hook
            mu.emu_stop()

    def r32(self, a):
        return struct.unpack("<i", self.mu.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def _new(self, mu, a, s, u):
        mu.reg_write(UC_X86_REG_EAX, self.next)
        mu.mem_write(self.next, b"\0" * 0xB4C)
        self.next += 0xC00

    def _bbi(self, mu, a, s, u):
        sp = mu.reg_read(UC_X86_REG_ESP)
        label, bid, x, y, w, h, parent, flags = (self.r32(sp + 4 + 4 * i) for i in range(8))
        self.buttons.append({"obj": mu.reg_read(UC_X86_REG_ECX) & 0xFFFFFFFF, "id": bid, "x": x, "y": y, "w": w,
                             "h": h, "parent": parent & 0xFFFFFFFF})

    def calc(self, popup: int, n: int, box_w: int, pad: int, gap: int, font_h: int = 20):
        """BasePop_calculate_dimensions' button block for `popup`."""
        mu = self.mu
        for off, v in ((0x30B0, n), (0x30BC, box_w), (0x30E0, pad), (0x30E4, gap), (0x30D4, 0)):
            self.w32(popup + off, v)
        sp = STACK - 0x100
        self.w32(sp + 0x14, font_h)
        for r, v in ((UC_X86_REG_ESP, sp), (UC_X86_REG_ESI, popup), (UC_X86_REG_EDI, 0), (UC_X86_REG_ECX, 0),
                     (UC_X86_REG_EBX, 0)):
            mu.reg_write(r, v)
        mu.emu_start(CALC_START, CALC_END, count=10_000)
        assert mu.reg_read(UC_X86_REG_EIP) == CALC_END
        return self.r32(popup + 0x30CC)

    def exec_row(self, popup: int, g: int, loop_n: int, margin_r: int, flags: int = 0, anchored: bool = False):
        """BasePop_exec_3's button creation for `popup` (after calc).  Returns the BaseButton_init records in call
        order."""
        mu = self.mu
        self.buttons.clear()
        self.next = ARENA
        self.w32(G_VA, g)
        self.w32(popup, POPUP_VTBL)
        self.w32(popup + 0xA14, 1 if anchored else 0)
        self.w32(popup + 0xA3C, popup)
        self.w32(popup + 0x30A8, flags)
        self.w32(popup + 0x2160, loop_n)
        self.w32(popup + 0x2158, 0)
        self.w32(popup + 0x30F4, margin_r)
        self.w32(popup + 0x30C0, 600)
        self.w32(popup + 0x30EC, 30)
        self.w32(popup + 0x20F4, 0)
        self.w32(popup + 0x3224, HEAP + 0x500)
        self.w32(popup + 0x3228, HEAP + 0x500)
        self.w32(popup + 0xA5C, FAKE_VT)
        self.w32(popup + 0x15A8, FAKE_VT)
        sp = STACK - 0x1000
        mu.mem_write(sp, b"\0" * 0x200)
        for r, v in ((UC_X86_REG_ESP, sp), (UC_X86_REG_ESI, popup), (UC_X86_REG_EDI, 0), (UC_X86_REG_EBX, 0),
                     (UC_X86_REG_EBP, 0), (UC_X86_REG_EAX, 0), (UC_X86_REG_ECX, 0), (UC_X86_REG_EDX, 0)):
            mu.reg_write(r, v)
        mu.emu_start(EXEC_START, EXEC_END, count=2_000_000)
        assert mu.reg_read(UC_X86_REG_EIP) == EXEC_END
        return list(self.buttons)


@pytest.fixture(scope="module")
def fixed(baked):
    return Row(baked, deployed=False)


@pytest.fixture(scope="module")
def deployed(baked):
    return Row(baked, deployed=True)


def cells(buttons, parent_r):
    """Screen cells [l, r) sorted left to right."""
    return sorted((parent_r + b["x"] - b["w"], parent_r + b["x"]) for b in buttons)


def run(row: Row, g: int, n: int, total: int, gap: int, margin_r: int, flags: int = 0, anchored=False, pad=0,
        popup=POPUP):
    """calc then exec for a row whose buttons share `total` px: box_w = total + 2*pad + (n-1)*gap."""
    w = row.calc(popup, n, total + 2 * pad + (n - 1) * gap, pad, gap)
    assert w == total // n
    # the row = the loop's custom buttons + id -1 (0x602D66, always unless flag 0x10000) + id -2 (0x60342B, flag 0x40)
    loop_n = n if flags & 0x10000 else n - (2 if flags & 0x40 else 1)
    return row.exec_row(popup, g, loop_n, margin_r, flags, anchored)


# ==== the law, every g, n, remainder, both row shapes ===================================================================
@pytest.mark.parametrize("g", range(17, 41))
def test_row_is_flush_and_distributed(fixed, deployed, g):
    P = 3000
    for n in range(1, 8):
        for flags in ((0, 0x10000, 0x40) if n >= 2 else (0, 0x10000)):
            for rem in range(n):
                total = n * SL.scale_px(120, g) + rem
                gap, margin = SL.scale_px(6, g), SL.scale_px(12, g)
                f = run(fixed, g, n, total, gap, margin, flags)
                d = run(deployed, g, n, total, gap, margin, flags)
                assert len(f) == len(d) == n, (g, n, flags)
                fc, dc = cells(f, P), cells(d, P)
                row_r = P - margin
                row_l = row_r - total - (n - 1) * gap
                b = SL.popup_button_row_bounds(total, n)
                assert fc == [(row_l + b[i] + i * gap, row_l + b[i + 1] + i * gap) for i in range(n)], (g, n, rem)
                assert dc[0][0] == row_l + rem and dc[-1][1] == row_r, (g, n, rem)        # the shipped defect
                widths = [r - l for l, r in fc]
                assert max(widths) - min(widths) <= (1 if rem else 0)
                if n % 2 or rem % 2 == 0:
                    assert widths == widths[::-1], (g, n, rem, widths)                     # symmetric when possible
                for rec in f:                                                              # the law, per button
                    vb = next(v for v in d if v["obj"] == rec["obj"] or (v["id"] == rec["id"] and v["id"] > 0))
                    assert (rec["x"], rec["w"]) == SL.popup_button_row_slot(vb["x"], vb["w"], n, rem, gap, margin, g)
                    assert (rec["y"], rec["h"], rec["id"]) == (vb["y"], vb["h"], vb["id"])
                if rem == 0:
                    assert f == d


def test_anchored_in_game_rows_too(fixed, deployed):
    """The in-game (anchored, [+0xA14] != 0) arm of Popup_on_adjust_button_placement moves y only."""
    for g in (18, 22, 25, 40):
        f = run(fixed, g, 3, 3 * 200 + 2, 8, 16, anchored=True)
        d = run(deployed, g, 3, 3 * 200 + 2, 8, 16, anchored=True)
        assert [b["y"] for b in f] == [b["y"] for b in d]
        assert cells(f, 1000)[0][0] == cells(d, 1000)[0][0] - 2 and cells(f, 1000)[-1][1] == cells(d, 1000)[-1][1]
        assert [r - l for l, r in cells(f, 1000)] == [201, 200, 201]


def test_g16_is_vanilla_even_with_a_remainder(fixed, deployed):
    for n in range(1, 7):
        for rem in range(n):
            for flags in ((0, 0x10000, 0x40) if n >= 2 else (0, 0x10000)):
                assert run(fixed, 16, n, n * 100 + rem, 6, 12, flags) == run(deployed, 16, n, n * 100 + rem, 6, 12,
                                                                                flags)


def test_stale_stash_leaves_the_row_vanilla(fixed, deployed):
    """A different popup's calc between this popup's calc and its buttons: the stash key misses -> vanilla."""
    other = POPUP + 0x8000
    for g in (22, 40):
        fixed.calc(POPUP, 3, 3 * 300 + 2 + 2 * 15, 0, 15)
        fixed.calc(other, 2, 2 * 300 + 1 + 15, 0, 15)
        f = fixed.exec_row(POPUP, g, 3, 30)
        deployed.calc(POPUP, 3, 3 * 300 + 2 + 2 * 15, 0, 15)
        assert f == deployed.exec_row(POPUP, g, 3, 30)


def test_left_anchored_row_is_vanilla(fixed, deployed):
    """margin_r = 0: x = 0, the row runs left-anchored (remainder on the right) -- not this law's shape."""
    for g in (22, 40):
        assert run(fixed, g, 3, 3 * 300 + 2, 15, 0) == run(deployed, g, 3, 3 * 300 + 2, 15, 0)


# ==== the real shots ===================================================================================================
#: (shot, g, parent right (screen), margin_r, n, w, rem, gap, the cells the shot shows [l, r) -- deployed, the list
#: span above the row) -- buttons measured on the face run (b > r+30, b > 90) of the button row, the list span from
#: the rows above; parent right / margin from the debugdump popup rects (4K Rules [2131,3828) margins 25/30, 1080p
#: [982,1914) 13/16, 4K SELECT A FACTION [1124,2715) 47/52, 4K SELECT DESTINATION [935,2984) 82/167).
SHOTS = (
    ("4K Rules 20261022-204738", 40, 3828, 30, 3, 537, 1, 15,
     ((2157, 2694), (2709, 3246), (3261, 3798)), (2156, 3798)),
    ("1080p Rules 20261022-205522", 22, 1914, 16, 3, 295, 2, 8,
     ((997, 1292), (1300, 1595), (1603, 1898)), (995, 1898)),
    ("1600x900 Rules 20261022-210112", 18, 1595, 13, 3, 242, 1, 6,
     ((844, 1086), (1092, 1334), (1340, 1582)), (843, 1582)),
    ("4K editor SELECT A FACTION 20261022-204501", 40, 2715, 52, 2, 738, 1, 15,
     ((1172, 1910), (1925, 2663)), (1171, 2663)),
    ("4K SELECT DESTINATION 20261022-204724", 40, 2984, 167, 5, 348, 0, 15,
     ((1017, 1365), (1380, 1728), (1743, 2091), (2106, 2454), (2469, 2817)), None),
)


@pytest.mark.parametrize("shot", SHOTS, ids=[s[0] for s in SHOTS])
def test_real_shots(fixed, deployed, shot):
    name, g, parent_r, margin, n, w, rem, gap, measured, span = shot
    total = n * w + rem
    # every shot's row reads [custom #buttons ...][OK][CANCEL]: the loop + ids -1 / -2 (flag 0x40)
    d = cells(run(deployed, g, n, total, gap, margin, 0x40), parent_r)
    assert tuple(d) == measured, (name, d)
    f = cells(run(fixed, g, n, total, gap, margin, 0x40), parent_r)
    if span is None:                                   # rem 0: nothing to distribute
        assert f == d
        return
    assert f[0][0] == span[0] and f[-1][1] == span[1], (name, f)
    assert [b[0] - a[1] for a, b in zip(f, f[1:])] == [gap] * (n - 1)
    assert d[0][0] - span[0] == rem                    # the shots' left offset (+1 / +2 / +1 / +1)


def test_g16_shots_have_no_remainder():
    """1024x768 rows (g = 16, vanilla): every measured row divides exactly -- Rules 3 x 215 + 2 x 6 = 657 on
    [350, 1007), SELECT DESTINATION 5 x 139 + 4 x 6 on [152, 871), Governor 2 x 325 + 6 on [183, 839)."""
    for cells_, gap in ((((350, 565), (571, 786), (792, 1007)), 6),
                        (((152, 291), (297, 436), (442, 581), (587, 726), (732, 871)), 6),
                        (((183, 508), (514, 839)), 6)):
        n = len(cells_)
        total = cells_[-1][1] - cells_[0][0] - (n - 1) * gap
        assert total % n == 0 and all(r - l == total // n for l, r in cells_)


# ==== t_btnrow_init in isolation: its guards ============================================================================
def _direct(row: Row, g: int, x: int, w: int, popup: int = POPUP):
    """Call the redirected BaseButton_init site's target with (label, id, x, y, w, h, parent, flags); returns the
    args BaseButton_init receives (or None when the stand-in was not reached)."""
    mu = row.mu
    row.buttons.clear()
    row.w32(G_VA, g)
    tgt = 0x6030E1 + struct.unpack("<i", mu.mem_read(0x6030DD, 4))[0]
    sp = STACK - 0x2000
    args = (0, 1, x, 500, w, 50, popup, 0)
    mu.mem_write(sp, struct.pack("<I", 0x6030E1) + struct.pack("<8i", *args))
    for r, v in ((UC_X86_REG_ESP, sp), (UC_X86_REG_ESI, popup), (UC_X86_REG_ECX, HEAP + 0x700)):
        mu.reg_write(r, v)
    row.stop_direct = True
    try:
        mu.emu_start(tgt, 0, count=5000)
    finally:
        row.stop_direct = False
    assert mu.reg_read(UC_X86_REG_EIP) == 0x6030E1 and mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x20
    assert mu.reg_read(UC_X86_REG_ESI) == popup
    return (row.buttons[0]["x"], row.buttons[0]["w"]) if row.buttons else None


def test_init_guards(fixed):
    """Only an on-grid, right-anchored button of the stashed popup whose w is the calc's moves; everything else
    reaches BaseButton_init with its own args."""
    w = fixed.calc(POPUP, 3, 3 * 300 + 2 + 2 * 15, 0, 15)
    assert w == 300
    fixed.w32(POPUP + 0x30F4, 30)
    for xs in (-30, -30 - 315, -30 - 630):
        assert _direct(fixed, 40, xs, 300) == SL.popup_button_row_slot(xs, 300, 3, 2, 15, 30, 40) != (xs, 300)
        assert _direct(fixed, 40, xs, 299) == (xs, 299)                    # w is not the calc's: untouched
        assert _direct(fixed, 16, xs, 300) == (xs, 300)                    # g = 16
        assert _direct(fixed, 40, xs, 300, POPUP + 0x8000) == (xs, 300)    # another popup
    for xs in (-31, -30 - 945, 0, 25):                                     # off the grid / past the row / left-anchored
        assert _direct(fixed, 40, xs, 300) == (xs, 300)
