"""Unicorn parity for the msglog_scale thunks (assemble_msglog.py) against the laws
scaling_laws.msglog_icon_layout / msglog_icon_pixels.

End to end: the PRISTINE bytes of MessageWin_draw_icon 0x471870 run with the two group sites
redirected to the REAL thunk bytes from patches.yaml (plus the real popup_scale helper) over a
fake Sprite + dest Buffer; the dest pixels are compared with the law.  Sprite_draw_2 is stubbed
with `ret 0x18` (the g<=16 / fallback path) and its entry args are captured.
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn")
pefile = pytest.importorskip("pefile")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: E402

import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000
G, PS = 0x668740, 0x668750
SD2 = 0x5E4B4A
FN, FN_END = 0x471870, 0x4718BF
SPRITE = 0x7F67C8
STACK = 0x2500000
SP0 = STACK + 0x8000
RET_TO = 0x2600000
LISTWIN = 0x2700000
SDATA, SPITCH = 0x2800000, 20
DDATA, DW, DH, DPITCH = 0x2900000, 200, 150, 204
KEY, BLANK = 255, 0xEE
YAML = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
SITES = {0x471887: ("t_msg_h", 6), 0x4718B8: ("t_msg_icon", 5)}

# interface.pcx (615,530) 16x15, raw indices
_A, _a, _B, _b = 142, 16, 187, 55
ICON = [[KEY] + [_A] * 14 + [KEY]]
for _n, _row in enumerate((1, 2, 3, 4, 5)):
    ICON.append([(_b if 8 <= c < 8 + _row else _a) if _n % 2 == 0 else (_B if 8 <= c < 8 + _row else _A) for c in range(16)])
ICON.append([_A, _A] + [_B] * 12 + [_A, _A])
ICON.append([_a, _a] + [_b] * 13 + [_a])
ICON.append([_A, _A] + [_B] * 12 + [_A, _A])
for _n, _row in enumerate((5, 4, 3, 2, 1)):
    ICON.append([(_b if 8 <= c < 8 + _row else _a) if _n % 2 == 0 else (_B if 8 <= c < 8 + _row else _A) for c in range(16)])
ICON.append([KEY] + [_A] * 14 + [KEY])
assert len(ICON) == 15 and ICON[1][8] == 55 and ICON[2][8:10] == [187, 187] and ICON[7][14] == 55


def entry(name: str):
    m = re.search(r"- id: %s\r?\n\s*offset: (0x[0-9a-fA-F]+)\r?\n\s*bytes: \"([^\"]+)\"" % re.escape(name), YAML)
    assert m, name
    return int(m.group(1), 16), bytes(int(x, 16) for x in m.group(2).split())


def pristine(va: int, n: int) -> bytes:
    bak = config.terranx_bak()
    if not pathlib.Path(bak).exists():
        pytest.skip("pristine .bak not present")
    pe = pefile.PE(str(bak), fast_load=True)
    img = pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        a = img + s.VirtualAddress
        if a <= va < a + s.SizeOfRawData:
            return s.get_data()[va - a: va - a + n]
    raise KeyError(hex(va))


def draw(g: int, row_x: int, row_y: int, row_h: int, patched: bool = True, icon=ICON):
    """-> (sd2_args or None, dest rows)"""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in (PCAVE2 + 0x29000, G & ~0xFFF, FN & ~0xFFF, SD2 & ~0xFFF, SPRITE & ~0xFFF, RET_TO, LISTWIN, SDATA):
        uc.mem_map(base, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(DDATA, 0x10000)
    code = bytearray(pristine(FN, FN_END - FN))
    assert code[-1] == 0xC3
    assert struct.unpack("<i", bytes(code[0x4718B9 - FN: 0x4718BD - FN]))[0] + 0x4718BD == SD2
    if patched:
        for va, (name, ln) in SITES.items():
            off, b = entry(name)
            uc.mem_write(PCAVE2 + off, b)
            code[va - FN: va - FN + ln] = b"\xE8" + struct.pack("<i", PCAVE2 + off - (va + 5)) + b"\x90" * (ln - 5)
    uc.mem_write(FN, bytes(code))
    uc.mem_write(SD2, b"\xC2\x18\x00")
    uc.mem_write(G, struct.pack("<I", g))
    uc.mem_write(PS, bytes.fromhex("0FAF05") + struct.pack("<I", G) + bytes.fromhex("C1F804C3"))
    sh, sw = len(icon), len(icon[0])
    uc.mem_write(SPRITE, struct.pack("<10i", 0, SDATA, KEY, SPITCH, sw, sh, sw, sh, 0, 0))
    for y, r in enumerate(icon):
        uc.mem_write(SDATA + y * SPITCH, bytes(r))
    buf = LISTWIN + 0x444
    uc.mem_write(buf + 0x54, struct.pack("<I", DDATA))
    uc.mem_write(buf + 0x80, struct.pack("<2i", DW, -DH))
    uc.mem_write(buf + 0x4A8, struct.pack("<i", DPITCH))
    uc.mem_write(DDATA, bytes([BLANK]) * (DPITCH * DH))
    uc.mem_write(RET_TO, b"\xf4")
    uc.mem_write(SP0, struct.pack("<I3i3i", RET_TO, LISTWIN, 7, 0, row_x, row_y, row_h))   # cdecl frame
    uc.reg_write(UC_X86_REG_ESP, SP0)
    seen = {}

    def hook(u, addr, size, _):
        if addr == SD2:
            sp = u.reg_read(UC_X86_REG_ESP)
            seen["args"] = struct.unpack("<I6i", bytes(u.mem_read(sp, 28))) + (u.reg_read(UC_X86_REG_ECX),)

    uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(FN, RET_TO, count=200000)
    except Exception:
        pass
    assert uc.reg_read(UC_X86_REG_EIP) == RET_TO
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
    raw = bytes(uc.mem_read(DDATA, DPITCH * DH))
    return seen.get("args"), [list(raw[y * DPITCH: y * DPITCH + DW]) for y in range(DH)]


def expect(g, row_x, row_y, row_h, icon=ICON):
    x, y, w, h = SL.msglog_icon_layout(row_x, row_y, row_h, g, (len(icon[0]), len(icon)))
    rows = [[BLANK] * DW for _ in range(DH)]
    for j, r in enumerate(SL.msglog_icon_pixels(icon, g, KEY)):
        for i, c in enumerate(r):
            if c is not None:
                rows[y + j][x + i] = c
    return rows


def test_fit_their_slots():
    prev_end = 0x299F5                                           # t_cmb_snap end
    for name in ("t_msg_h", "t_msg_icon"):
        off, code = entry(name)
        assert off >= prev_end, name
        prev_end = off + len(code)
    assert prev_end <= 0x2A000


def test_scaling_g16_is_the_engine():
    for row_h in (17, 18, 19, 14, 40):
        native, _ = draw(16, 5, 100, row_h, patched=False)
        ours, rows = draw(16, 5, 100, row_h)
        assert ours == native and native[3:5] == SL.msglog_icon_layout(5, 100, row_h, 16)[:2]
        assert native[0] == 0x4718BD and native[1] == LISTWIN + 0x444 and native[5:] == (1, 1, SPRITE)
        assert all(c == BLANK for r in rows for c in r)          # nothing drawn by the thunk itself
    assert SL.msglog_icon_pixels(ICON, 16, KEY) == [[None if c == KEY else c for c in r] for r in ICON]


@pytest.mark.parametrize("g", range(17, 41))
def test_scaling_icon_matches_the_law(g):
    for row_h, row_x, row_y in ((18 * g // 16, 3, 56), (18 * g // 16 + 1, 0, 0), (50, 7, 61)):
        args, rows = draw(g, row_x, row_y, row_h)
        assert args is None                                      # own blit, the engine draw is not called
        assert rows == expect(g, row_x, row_y, row_h)


@pytest.mark.parametrize("g", (22, 25, 40))
def test_scaling_icon_is_t_row_scanlines_with_a_clean_diagonal(g):
    px = SL.msglog_icon_pixels(ICON, g, KEY)
    light, dark = {_A, _B}, {_a, _b}
    for j, r in enumerate(px):
        assert {c for c in r if c is not None} <= (dark if (j // SL.stripe_rows(g)) & 1 else light)
    ext = [max((i for i, c in enumerate(r) if c in (_B, _b)), default=-1) for r in px]   # arrow right extent
    apex = ext.index(max(ext))
    assert all(a <= b for a, b in zip(ext[:apex], ext[1:apex + 1]))      # monotone up to the apex: no comb
    assert all(a >= b for a, b in zip(ext[apex:], ext[apex + 1:]))


def test_scaling_runtime_palette_remap_follows_the_art():
    remap = {_A: 152, _a: 26, _B: 197, _b: 65, KEY: KEY}
    icon = [[remap[c] for c in r] for r in ICON]
    _, rows = draw(25, 3, 56, 28, icon=icon)
    assert rows == expect(25, 3, 56, 28, icon=icon)


def test_scaling_clipped_or_foreign_sprite_falls_back():
    args, rows = draw(25, DW - 10, 56, 28)                       # would overrun the dest: nothing written
    assert args is None and all(c == BLANK for r in rows for c in r)
    args, rows = draw(25, 3, 56, 28, icon=[r[:12] for r in ICON])   # data w != 16 -> engine draw
    assert args is not None and args[5:7] == (1, 1)


def test_font_site_uses_the_direct_init_law():
    m = re.search(r"- id: msgwin_init\.font\r?\n(?:.*\r?\n){1,8}?\s*new_bytes:\s*\"E8 \{rel32:thunk_hud_font\}\"", YAML)
    assert m
    assert SL.MSGLOG_FONT_NATIVE == 12
