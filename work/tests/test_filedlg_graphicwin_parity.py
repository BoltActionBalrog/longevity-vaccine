"""Differential (Unicorn): thunk_filedlg_graphicwin v3 -- the file-picker
window origin (call-redirect @0x4074f1, group filedlg_geometry).

The baked bytes (resolved from patches.yaml with the real symbol table) are run
on vanilla's own args (scaling_laws.filedlg_native_origin) and must land on
scaling_laws.filedlg_window_origin; the in-game window's bottom must sit on the
console top at every g (the SaveLoadPos defect: v1 screen-centred it and the
HUD hid OK/CANCEL below 4K).  v3 (fix 19): the main-menu window keeps vanilla's
anchors too -- the console strip height is fl(213g/16) there (MainWin_build +
thunk_hud_seedscale in system_init, before top_menu), not 0; the real-chain tests
replay that writer and FileDlg_layout's own arithmetic on the baked image.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent - asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
from scaling_laws import (  # noqa: E402
    filedlg_native_origin, filedlg_window_origin, popup_g, popup_scale_floor,
)

SW, SH, STRIP = 0x9B7B1C, 0x9B7B20, 0x7AF59C
GWIN_INIT = 0x5D4EF0
SITE_RET = 0x004074F6
STACK = 0x00200000
WINDOW = 0x00A00000 - 0x100
CAVE_LO, CAVE_HI = 0xA0C000, 0xA40000

RESOLUTIONS = [(1024, 768), (1280, 1024), (1600, 1200), (1920, 1080),
               (2560, 1440), (3840, 2160), (1366, 768), (2048, 1536), (1600, 900), (1088, 816)]
# g = 16 on a screen wider than 1024 (scaling_laws.popup_g: 16:9 up to 1366 wide runs at g = 16)
G16_WIDE = [(1280, 720), (1280, 768), (1280, 800), (1360, 768), (1366, 768)]


def _load():
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        base = cave["virtual_addr"]
        base = int(base, 16) if isinstance(base, str) else base
        for c in cave.get("contents", []) or []:
            if c["id"] == "thunk_filedlg_graphicwin":
                off = c["offset"]
                off = int(off, 16) if isinstance(off, str) else off
                va = base + off
                return symtab, va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab)
    raise AssertionError("thunk_filedlg_graphicwin not in patches.yaml")


SYMTAB, VA, CODE = _load()
G_VA = SYMTAB["g_popup_scale_num"]
POPUP_SCALE = SYMTAB["popup_scale"]


def _g(sw, sh):
    """The g a sw x sh screen runs at (the real thunk_ensure_scale: test_scaling_popup_g_parity.py)."""
    return popup_g(sw, sh)


def _run(sw, sh, strip, g, args):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE_LO, CAVE_HI - CAVE_LO)
    uc.mem_map(0x5D4000, 0x1000)
    uc.mem_map(0x660000, 0x10000)
    uc.mem_map(0x7AF000, 0x1000)
    uc.mem_map(0x9B7000, 0x1000)
    uc.mem_map(0x407000, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(POPUP_SCALE, bytes.fromhex("0FAF05") + struct.pack("<I", G_VA) + bytes.fromhex("C1F804C3"))
    uc.mem_write(VA, CODE)
    uc.mem_write(GWIN_INIT, b"\xF4")
    uc.mem_write(SITE_RET, b"\xF4")
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(SW, struct.pack("<i", sw))
    uc.mem_write(SH, struct.pack("<i", sh))
    uc.mem_write(STRIP, struct.pack("<i", strip))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I4i", SITE_RET, *args))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, WINDOW)
    uc.reg_write(UC_X86_REG_EBX, 0x0BADF00D)
    try:
        uc.emu_start(VA, 0, count=200)
    except unicorn.UcError:
        pass
    eip = uc.reg_read(UC_X86_REG_EIP)
    assert eip in (GWIN_INIT, GWIN_INIT + 1)                 # tail-jmp GraphicWin_init
    assert uc.reg_read(UC_X86_REG_ESP) == esp                # site ret + 4 args intact
    assert uc.reg_read(UC_X86_REG_ECX) == WINDOW             # thiscall this preserved
    assert uc.reg_read(UC_X86_REG_EBX) == 0x0BADF00D
    assert struct.unpack("<I", uc.mem_read(esp, 4))[0] == SITE_RET
    return struct.unpack("<4i", uc.mem_read(esp + 4, 16))


def test_popup_scale_stub_matches_yaml():
    """The emulated popup_scale must be the real cave bytes (imul [g]; sar 4; ret)."""
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == "popup_scale":
                base = cave["virtual_addr"]
                base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]
                off = int(off, 16) if isinstance(off, str) else off
                got = ap.ByteTemplate(c["bytes"]).resolve(base + off, SYMTAB)
                assert got == bytes.fromhex("0FAF05") + struct.pack("<I", G_VA) + bytes.fromhex("C1F804C3")
                return
    raise AssertionError("popup_scale not found")


def _strip(g: int) -> int:
    """g_console_strip_height as BOTH paths read it: MainWin_build's literal 0xD5 scaled by thunk_hud_seedscale
    (fl(213g/16); 213 at g <= 16), set in system_init before top_menu (test_main_menu_strip_is_the_scaled_hud below)."""
    return popup_scale_floor(213, g)


@pytest.mark.parametrize("in_game", (True, False))
@pytest.mark.parametrize("sw,sh", RESOLUTIONS)
def test_thunk_matches_law(sw, sh, in_game):
    g = _g(sw, sh)
    strip = _strip(g)
    args = filedlg_native_origin(sw, sh, strip, in_game)
    assert _run(sw, sh, strip, g, args) == filedlg_window_origin(sw, sh, strip, *args, g)


@pytest.mark.parametrize("in_game", (True, False))
@pytest.mark.parametrize("sw,sh", RESOLUTIONS)
def test_both_paths_keep_vanillas_anchors(sw, sh, in_game):
    """v3 (fix 19): in game AND at the main menu the window keeps vanilla's offsets from the console top T and from
    c = SW>>1, scaled -- the main menu's 9-row gap above T and 9-col centre offset scale with it."""
    g = _g(sw, sh)
    strip = _strip(g)
    nx, ny, nw, nh = filedlg_native_origin(sw, sh, strip, in_game)
    x, y, w, h = filedlg_window_origin(sw, sh, strip, nx, ny, nw, nh, g)
    c, top = sw >> 1, sh - strip
    s = lambda v: popup_scale_floor(v, g)   # noqa: E731
    assert (w, h) == (s(nw), s(nh))
    assert (c - x, top - y) == (s(c - nx), s(top - ny))
    if in_game:
        assert y + h == top                                  # vanilla: bottom on the console top
    else:
        assert top - (y + h) == s(0x192) - s(0x189)          # vanilla 9 above it, x g/16 (floor-composed)
    assert y >= 0


@pytest.mark.parametrize("sw,sh", RESOLUTIONS)
def test_ingame_bottom_rests_on_console_top(sw, sh):
    g = _g(sw, sh)
    strip = _strip(g)
    x, y, w, h = filedlg_window_origin(sw, sh, strip, *filedlg_native_origin(sw, sh, strip, True), g)
    assert y + h == sh - strip                               # vanilla: bottom on the console top
    assert y >= 0
    if sw > 1024:
        # visible part (window minus the scaled 32px scrollbar gap) centred on SW/2 within 1 px of rounding
        vis_c2 = 2 * x + w - popup_scale_floor(32, g)
        assert abs(vis_c2 - sw) <= 2


def test_native_passthrough():
    for in_game in (True, False):
        args = filedlg_native_origin(1024, 768, 213, in_game)
        assert _run(1024, 768, 213, 16, args) == args


@pytest.mark.parametrize("in_game", (True, False))
@pytest.mark.parametrize("sw,sh", G16_WIDE)
def test_g16_wide_screen_is_vanilla(sw, sh, in_game):
    """fix 10: g = 16 on a 1280..1366-wide screen passes vanilla's own args through -- in particular the MAIN-MENU
    window keeps vanilla's bottom anchor (the SW > 1024 gate screen-centred it: 1280x768 (473, 187) vs vanilla
    (482, 153); the strip is 213 at the main menu too)."""
    g = _g(sw, sh)
    assert g == 16
    strip = _strip(g)
    args = filedlg_native_origin(sw, sh, strip, in_game)
    assert filedlg_window_origin(sw, sh, strip, *args, g) == args
    assert _run(sw, sh, strip, g, args) == args
    if (sw, sh) == (1280, 768) and not in_game:
        assert args == (482, 153, 334, 393)


def test_gate_reads_g_not_the_screen_width():
    """Synthetic: g > 16 on a 1024-wide screen scales; g = 16 on a 3840-wide one does not (the gate is g)."""
    for in_game in (True, False):
        for sw, sh, g in ((1024, 768, 25), (3840, 2160, 16)):
            strip = _strip(g)
            args = filedlg_native_origin(sw, sh, strip, in_game)
            got = _run(sw, sh, strip, g, args)
            assert got == filedlg_window_origin(sw, sh, strip, *args, g)
            assert (got == args) == (g == 16), (sw, sh, g, in_game)


# ==== the engine's real order on the baked image: system_init's MainWin_build strip, then FileDlg_layout =============
@pytest.fixture(scope="module")
def baked(baked_exe) -> bytes:
    return baked_exe.read_bytes()


def _image(baked: bytes):
    pefile = pytest.importorskip("pefile")
    pe = pefile.PE(data=baked)
    ib = pe.OPTIONAL_HEADER.ImageBase
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for s in pe.sections:
        va = ib + s.VirtualAddress
        uc.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
        uc.mem_write(va, s.get_data())
    uc.mem_map(0x10000000, 0x200000)
    return uc


MAIN_MENU_GOLDEN = {   # (sw, sh) -> the window args at the main menu: vanilla x g/16 from vanilla's own anchors
    (3840, 2160): (1525, 623, 835, 982),       # v2 drew (1502, 589): screen-centred
    (1920, 1080): (743, 236, 459, 540),        # v2 (730, 270)
    (1600, 1200): (554, 240, 521, 614),        # v2 (539, 293)
    (1600, 900): (623, 209, 375, 442),         # v2 (612, 229)
    (1366, 768): (525, 153, 334, 393),         # g = 16: the shot 20261022-210249 (frame 528..854 x 157..545 inside)
}


def _strip_after_mainwin_build(uc, sw, sh):
    """MainWin_build's strip writer (0x459726, literal 0xD5) then its seed-scale call-redirect @0x459E8A
    (thunk_hud_seedscale: ensure_scale first -- g is 0 this early -- then the seed table incl. +0xD7C)."""
    for a, v in ((SW, sw), (SH, sh), (G_VA, 0)):
        uc.mem_write(a, struct.pack("<i", v))
    assert bytes(uc.mem_read(0x459726, 10)) == bytes.fromhex("C7867C0D0000D5000000")
    uc.mem_write(STRIP, struct.pack("<i", 0xD5))                  # [esi+0xd7c] = 0xD5, esi = MainWin 0x7AE820
    tgt = 0x459E8F + struct.unpack("<i", uc.mem_read(0x459E8B, 4))[0]
    assert uc.mem_read(0x459E8A, 1) == b"\xE8" and tgt == SYMTAB["thunk_hud_seedscale"]
    sp = 0x10100000
    uc.mem_write(sp, struct.pack("<I", 0x459E8F))
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.emu_start(tgt, 0x5D7DE0, count=100_000)                   # tail-jumps Buffer_load_pcx
    return struct.unpack("<i", uc.mem_read(STRIP, 4))[0], struct.unpack("<i", uc.mem_read(G_VA, 4))[0]


def _layout(uc, console_visible: bool):
    """FileDlg_layout 0x40743E..0x4074F1 (console visibility through Win_is_visible @0x407453) and the call at
    0x4074F1 into the thunk: GraphicWin_init's (x, y, w, h)."""
    from unicorn import UC_HOOK_CODE
    uc.mem_write(0x10180000, struct.pack("<2I", 0, 0))
    uc.mem_write(0x9156B0, struct.pack("<I", 0x10180000))        # console vbtable stub (only +4 is read)
    uc.reg_write(UC_X86_REG_ESP, 0x100F0000)
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ESI
    uc.reg_write(UC_X86_REG_EBP, 0x10100000)
    uc.reg_write(UC_X86_REG_ESI, 0x10150000)
    out = {}

    def hook(u, addr, size, user):
        if addr == 0x407453:
            u.reg_write(UC_X86_REG_EAX, 1 if console_visible else 0)
            u.reg_write(UC_X86_REG_EIP, 0x407458)
        elif addr == GWIN_INIT:
            sp = u.reg_read(UC_X86_REG_ESP)
            out["args"] = struct.unpack("<4i", u.mem_read(sp + 4, 16))
            u.emu_stop()
    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(0x40743E, 0, count=4000)
    finally:
        uc.hook_del(h)
    return out["args"]


@pytest.mark.parametrize("sw,sh", sorted(MAIN_MENU_GOLDEN))
def test_main_menu_strip_is_the_scaled_hud(baked, sw, sh):
    uc = _image(baked)
    strip, g = _strip_after_mainwin_build(uc, sw, sh)
    assert g == _g(sw, sh) and strip == _strip(g), (sw, sh, strip, g)


@pytest.mark.parametrize("sw,sh", sorted(MAIN_MENU_GOLDEN))
def test_main_menu_window_real_chain(baked, sw, sh):
    """system_init (strip) -> top_menu -> FileDlg_layout -> the thunk, at the main menu (console hidden)."""
    uc = _image(baked)
    strip, g = _strip_after_mainwin_build(uc, sw, sh)
    got = _layout(uc, console_visible=False)
    assert got == MAIN_MENU_GOLDEN[(sw, sh)], (sw, sh, got)
    assert got == filedlg_window_origin(sw, sh, strip, *filedlg_native_origin(sw, sh, strip, False), g)
    ingame = _layout(uc, console_visible=True)
    assert ingame == filedlg_window_origin(sw, sh, strip, *filedlg_native_origin(sw, sh, strip, True), g)
    assert ingame[1] + ingame[3] == sh - strip
