"""Unicorn parity for the combat_console_scale thunks (assemble_combat.py) against the laws
scaling_laws.battlewin_rects / battle_portrait_layout / battle_slot / battle_stats_y.

The REAL bytes from patches.yaml run at their real cave VAs, together with the real popup_scale
helper bytes (menu_strip cave).  BattleWin_init / thunk_ensure_scale are stubbed with `ret`.
Ground truth for g=16 = the PRISTINE probe run work\\_cmb_probe\\combat_geom_20260918T222427.log.
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
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
                               UC_X86_REG_ESI, UC_X86_REG_ESP)

import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000
G, PS, ENSURE = 0x668740, 0x668750, 0x668760
BW_INIT = 0x4219E0
SEED_D80, SEED_DC0 = 0x7AF5A0, 0x7AF5E0
BW = 0x6EEED8
STACK = 0x2500000
SP0 = STACK + 0x8000
SPRITE = STACK + 0xA000
FRAME = STACK + 0xC000
RET_TO = 0x2600000
YAML = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")


def entry(name: str):
    m = re.search(r"- id: %s\r?\n\s*offset: (0x[0-9a-fA-F]+)\r?\n\s*bytes: \"([^\"]+)\"" % re.escape(name), YAML)
    assert m, name
    return int(m.group(1), 16), bytes(int(x, 16) for x in m.group(2).split())


def mk(g: int) -> Uc:
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(PCAVE2 + 0x29000, 0x1000)
    uc.mem_map(G & ~0xFFF, 0x1000)
    uc.mem_map(BW_INIT & ~0xFFF, 0x1000)
    uc.mem_map(SEED_D80 & ~0xFFF, 0x1000)
    uc.mem_map(BW & ~0xFFF, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(RET_TO, 0x1000)
    for name in ("t_cmb_init", "t_cmb_slot", "t_cmb_ins3a", "t_cmb_ins3b", "t_cmb_stat5",
                 "t_cmb_wL", "t_cmb_wR", "t_cmb_hL", "t_cmb_hR"):
        off, code = entry(name)
        uc.mem_write(PCAVE2 + off, code)
    uc.mem_write(G, struct.pack("<I", g))
    uc.mem_write(PS, bytes.fromhex("0FAF05") + struct.pack("<I", G) + bytes.fromhex("C1F804C3"))
    uc.mem_write(ENSURE, b"\xc3")
    uc.mem_write(BW_INIT, b"\xc3")
    uc.mem_write(RET_TO, b"\xf4")
    uc.mem_write(SP0, struct.pack("<I", RET_TO))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    return uc


def run(uc: Uc, name: str):
    off, _ = entry(name)
    try:
        uc.emu_start(PCAVE2 + off, RET_TO, count=2000)
    except Exception:
        pass
    assert uc.reg_read(UC_X86_REG_EIP) == RET_TO, name
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4, name           # E8-entered thunk consumed its ret only


def test_fit_their_slots():
    prev_end = 0x29764
    for name in ("t_cmb_init", "t_cmb_slot", "t_cmb_ins3a", "t_cmb_ins3b", "t_cmb_stat5",
                 "t_cmb_wL", "t_cmb_wR", "t_cmb_hL", "t_cmb_hR", "t_cmb_snap"):
        off, code = entry(name)
        assert off >= prev_end, name
        prev_end = off + len(code)
    assert prev_end <= 0x2A000


PRISTINE_D80, PRISTINE_DC0 = (4, 56, 245, 252), (262, 66, 763, 234)


def test_scaling_law_is_the_pristine_trace_at_g16():
    assert SL.battlewin_rects(PRISTINE_D80, PRISTINE_DC0, 16) == (
        (266, 70, 511, 230), (514, 70, 759, 230), (8, 60, 123, 248), (126, 60, 241, 248))
    x, y, w, h, top = SL.battle_portrait_layout((8, 60, 123, 248), 16)
    assert (x, y, w, h, top) == (17, 69, 96, 115, 187)             # wrap_cent_6 rect top 187
    assert SL.battle_unit_name_y(70, 16) == 148 and SL.battle_stats_y(70, 16) == 78


# the seeds the patched runs logged (4K g=40, 1600 g=25) + a floor sweep of the pristine seeds
SEEDS = {40: ((10, 140, 612, 630), (655, 165, 1907, 585))}


@pytest.mark.parametrize("g", range(17, 41))
def test_scaling_init_matches_the_law(g):
    d80, dc0 = SEEDS.get(g, (tuple(v * g // 16 for v in PRISTINE_D80), tuple(v * g // 16 for v in PRISTINE_DC0)))
    uc = mk(g)
    uc.mem_write(SEED_D80, struct.pack("<4i", *d80))
    uc.mem_write(SEED_DC0, struct.pack("<4i", *dc0))
    regs = {UC_X86_REG_ECX: BW, UC_X86_REG_EBX: 0x11, UC_X86_REG_ESI: 0x22, UC_X86_REG_EDI: 0x33,
            UC_X86_REG_EBP: 0x44, UC_X86_REG_EDX: 0x55}
    for r, v in regs.items():
        uc.reg_write(r, v)
    run(uc, "t_cmb_init")
    got = tuple(struct.unpack("<4i", bytes(uc.mem_read(BW + o, 16))) for o in (0x30, 0x40, 0x50, 0x60))
    assert got == SL.battlewin_rects(d80, dc0, g)
    for r, v in regs.items():
        assert uc.reg_read(r) == v                                # pushad-transparent, ecx preserved


def test_scaling_init_is_native_at_g16():
    uc = mk(16)
    uc.mem_write(BW + 0x30, struct.pack("<4i", 1, 2, 3, 4))
    uc.reg_write(UC_X86_REG_ECX, BW)
    run(uc, "t_cmb_init")
    assert struct.unpack("<4i", bytes(uc.mem_read(BW + 0x30, 16))) == (1, 2, 3, 4)   # engine values untouched


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_slot_insets_stats(g):
    for sw800, nat in ((0, 75), (1, 50)):
        uc = mk(g)
        uc.reg_write(UC_X86_REG_EBX, 0 if sw800 else 0xFFFFFFFF)  # the engine's sbb mask
        uc.reg_write(UC_X86_REG_EAX, 0x1234)
        run(uc, "t_cmb_slot")
        assert uc.reg_read(UC_X86_REG_EBX) == nat * g // 16
        assert uc.reg_read(UC_X86_REG_EAX) == 0x1234
    assert SL.battle_slot(g) == 75 * g // 16

    uc = mk(g)
    uc.reg_write(UC_X86_REG_EAX, 1000)
    uc.reg_write(UC_X86_REG_EDX, 0x77)
    uc.reg_write(UC_X86_REG_EBP, FRAME)
    run(uc, "t_cmb_ins3a")
    s3 = 3 * g // 16
    assert uc.reg_read(UC_X86_REG_EAX) == 1000 + s3 and uc.reg_read(UC_X86_REG_EDX) == 0x77
    assert struct.unpack("<i", bytes(uc.mem_read(FRAME - 0x70, 4)))[0] == 1000 + s3

    uc = mk(g)
    uc.reg_write(UC_X86_REG_EFLAGS, 0x246 | 1)
    run(uc, "t_cmb_ins3b")
    assert uc.reg_read(UC_X86_REG_EAX) == s3
    assert uc.reg_read(UC_X86_REG_EFLAGS) & 0x8D5 == (0x246 | 1) & 0x8D5      # flag-transparent

    uc = mk(g)
    uc.reg_write(UC_X86_REG_EAX, 0xABCD)
    uc.reg_write(UC_X86_REG_EDX, 500)
    uc.reg_write(UC_X86_REG_EBP, FRAME)
    uc.reg_write(UC_X86_REG_EFLAGS, 0x202 | 0x40)
    run(uc, "t_cmb_stat5")
    assert uc.reg_read(UC_X86_REG_EBX) == 500 + 5 * g // 16 and uc.reg_read(UC_X86_REG_EAX) == 0xABCD
    assert struct.unpack("<I", bytes(uc.mem_read(FRAME - 0x10, 4)))[0] == 0xABCD
    assert uc.reg_read(UC_X86_REG_EFLAGS) & 0x8D5 == (0x202 | 0x40) & 0x8D5
    assert SL.battle_stats_y(70 * g // 16, g) == 70 * g // 16 + s3 + 5 * g // 16


@pytest.mark.parametrize("g", range(16, 41))
@pytest.mark.parametrize("side", ["L", "R"])
def test_scaling_portrait_reads_feed_the_engine_formulas(g, side):
    box = SL.battlewin_rects(tuple(v * g // 16 for v in PRISTINE_D80), tuple(v * g // 16 for v in PRISTINE_DC0), g)[2 if side == "L" else 3]
    want_x, want_y, want_w, want_h, want_top = SL.battle_portrait_layout(box, g)
    off = 0x50 if side == "L" else 0x60

    uc = mk(g)
    uc.mem_write(SPRITE + 0x18, struct.pack("<2i", 96, 115))
    uc.mem_write(BW + off, struct.pack("<4i", *box))
    uc.reg_write(UC_X86_REG_EAX, SPRITE)
    uc.reg_write(UC_X86_REG_ESI, BW)
    uc.reg_write(UC_X86_REG_EFLAGS, 0x202 | 0x80)
    run(uc, "t_cmb_w" + side)
    w, left = uc.reg_read(UC_X86_REG_EDX), uc.reg_read(UC_X86_REG_ECX)
    assert (w, left) == (want_w, box[0]) and uc.reg_read(UC_X86_REG_EAX) == SPRITE
    assert uc.reg_read(UC_X86_REG_EFLAGS) & 0x8D5 == (0x202 | 0x80) & 0x8D5
    # the engine's own centring (cdq/sub/sar) and y = (T - L) + x
    x = left + int(((box[2] - left) - w) / 2)
    y = (box[1] - left) + x
    assert (x, y) == (want_x, want_y)

    uc = mk(g)
    uc.mem_write(SPRITE + 0x18, struct.pack("<2i", 96, 115))
    uc.mem_write(BW + off, struct.pack("<4i", *box))
    uc.reg_write(UC_X86_REG_EAX, SPRITE)
    uc.reg_write(UC_X86_REG_EDI, BW + off)
    uc.reg_write(UC_X86_REG_ESI, y)
    run(uc, "t_cmb_h" + side)
    if side == "L":
        top = uc.reg_read(UC_X86_REG_EAX) + y + 3                  # engine: lea eax,[eax+esi+3]
        assert uc.reg_read(UC_X86_REG_EDX) == box[1]               # displaced mov edx,[edi+4]
    else:
        top = uc.reg_read(UC_X86_REG_ESI)                          # thunk folds the lea
    assert top == want_top
