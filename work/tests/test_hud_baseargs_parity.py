"""Unicorn parity for thunk_hud_baseargs v3 (assemble_hud_widgets.py; base_draw 0x55AF20 entry detour).
The REAL bytes from patches.yaml run at the real cave VA with base_draw's argument frame:
  * dest == the WorldWin minimap console's canvas, computed at run time the way MapWin_draw_base_tile
    computes it (console 0x8EB48C + [[console]+4] + 0x444, whatever the virtual-base displacement is)
    -> flags := 0x100 exactly (base_draw's box path, square variant, no icon-path bits), size untouched
    -- the 2026-09-12 BASE LOCATOR box-style pin;
  * dest == a HUD strip canvas at g>16 -> the v1 size law s' = ((s+16)g>>4)-16 (scaling_laws.veh_size_scaled),
    flags untouched;
  * any other dest -> every argument untouched.
In every case the displaced prologue (push ebp / mov ebp,esp / sub esp,0x118) is replayed and the thunk
resumes at 0x55AF29 with the entry return address consumed.
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
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: E402

import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000
OFF = 0x13D20                                     # v3 slot (v1/v2 lived at 0x5130)
VA = PCAVE2 + OFF
G = 0x668740
RESUME = 0x55AF29
HUD1, CONSOLE, VBTABLE = 0x7AEC64, 0x8EB48C, 0x2400000     # the WorldWin console + a fake virtual-base table
STACK = 0x2500000
SP0 = STACK + 0x8000


def _yaml_bytes() -> bytes:
    t = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r'- id: thunk_hud_baseargs\r?\n\s*offset: 0x13D20\r?\n\s*bytes: "([^"]+)"', t)
    assert m, "thunk_hud_baseargs content entry missing"
    return bytes(int(x, 16) for x in m.group(1).split())


CODE = _yaml_bytes()


def _run(g: int, buf: int, size: int, flags: int, caller_ret: int = 0x469C55, disp: int = 0x23D94):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(VA & ~0xFFF, 0x1000)
    uc.mem_map(G & ~0xFFF, 0x1000)
    uc.mem_map(RESUME & ~0xFFF, 0x1000)
    uc.mem_map(CONSOLE & ~0xFFF, 0x1000)
    uc.mem_map(VBTABLE, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(VA, CODE)
    uc.mem_write(G, struct.pack("<I", g))
    uc.mem_write(CONSOLE, struct.pack("<I", VBTABLE))                     # the console's vbptr
    uc.mem_write(VBTABLE, struct.pack("<Ii", 0, disp))                    # [0, displacement of the virtual GraphicWin]
    uc.mem_write(RESUME, b"\xf4")
    args = [RESUME, caller_ret, buf, 0x77, 100, 200, size & 0xFFFFFFFF, flags]
    uc.mem_write(SP0, struct.pack("<8I", *args))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_EBP, 0x11111111)
    uc.emu_start(VA, RESUME, count=200)
    assert uc.reg_read(UC_X86_REG_EIP) == RESUME
    esp = uc.reg_read(UC_X86_REG_ESP)
    ebp = uc.reg_read(UC_X86_REG_EBP)
    # replayed prologue: entry ret popped, push ebp (old ebp), ebp = esp, sub esp, 0x118
    assert ebp == SP0 + 4 - 4 and esp == ebp - 0x118
    assert struct.unpack("<I", bytes(uc.mem_read(ebp, 4)))[0] == 0x11111111
    frame = struct.unpack("<7I", bytes(uc.mem_read(SP0 + 4, 28)))     # caller_ret, buf, base, x, y, size, flags
    return frame


def test_fits_its_slot():
    assert OFF + len(CODE) <= 0x14000, len(CODE)                          # g_se_vpdone starts at 0x14000
    assert len(CODE) <= 0x100


@pytest.mark.parametrize("disp", (0x23D94, -0x152C, 0x1C))
@pytest.mark.parametrize("g", (16, 22, 25, 40))
@pytest.mark.parametrize("size", (-14, -8, -6, 0))
def test_minimap_dest_forces_the_box_path_and_nothing_else(g, size, disp):
    canvas = (CONSOLE + disp + 0x444) & 0xFFFFFFFF
    ret, buf, base, x, y, sz, flags = _run(g, canvas, size, 0, disp=disp)
    assert (ret, buf, base, x, y) == (0x469C55, canvas, 0x77, 100, 200)
    assert struct.unpack("<i", struct.pack("<I", sz))[0] == size          # the size sentinel is NOT the HUD law's business here
    assert flags == 0x100
    _r, _b, _ba, _x, _y, _sz, flags2 = _run(g, canvas, size, 0x808, disp=disp)
    assert flags2 == 0x100                                                 # forced: the icon-path bits 3/11 go too
    # the canvas of a DIFFERENT displacement is not the minimap
    other = (CONSOLE + 0x23D94 + 0x444) & 0xFFFFFFFF if disp != 0x23D94 else (CONSOLE + 0x1C + 0x444)
    frame = _run(g, other, size, 0x8, disp=disp)
    assert frame[6] == 0x8


@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_hud_strip_dest_keeps_the_v1_size_law(g):
    for size in (-8, -6, 0, 4):
        _r, _b, _ba, _x, _y, sz, flags = _run(g, HUD1, size, 0)
        want = SL.veh_size_scaled(size, g) if g > 16 else size
        assert struct.unpack("<i", struct.pack("<I", sz))[0] == want
        assert flags == 0


def test_other_dest_is_a_pure_passthrough():
    for g in (16, 40):
        frame = _run(g, 0x2000000, -14, 0x8)
        assert frame == (0x469C55, 0x2000000, 0x77, 100, 200, (-14) & 0xFFFFFFFF, 0x8)
