"""map_dash_line (proposal): the main map's DASHED order lines through t_pw_line, vanilla x g/16.

MapWin_direct_dest_line 0x4672C0's non-overlay arm (last arg 0) draws one dashed Buffer_line 0x5E09D0 @0x46741E on
the Console's own map canvas ([[esi]+4]+esi+0x444): MapWin_draw_base_dest 0x467970 (dash 3/5 and 2/2) and
Console_group 0x4D92D0 (2/2) reach it through MapWin_dest_line 0x467430; the phase is (on+off-1) & [0x939FD4] (the
line timer's marching counter, shared with PlanWin).  Same 9-arg thiscall / RET 0x24 contract as PlanWin's 0x48B370,
so t_pw_line does the drawing; t_map_dash (2026-10-14 audit) sits in front of it and widens the caller's 1-px slot
separations (slot 1 +1,+1; slot 2 0,-1; mode [ebp+0x18]) to K.  Unicorn runs the PRISTINE body 0x467328..0x46742B
(from the slot switch, so the caller's own shifts run) with the call retargeted to the patches.yaml t_map_dash,
Buffer_line stubbed to log, and checks the logged calls == planwin_line_calls(points + map_dest_slot_shift) with the
slot colour, and that the function's own epilogue (pop ebx/edi/esi, ret 0x20) still balances.
"""
import pathlib
import struct
import sys

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
                               UC_X86_REG_ESI, UC_X86_REG_ESP)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_planwin_line as AL  # noqa: E402
import scaling_laws as SL  # noqa: E402
import test_scaling_planwin_line_asm as TPL  # noqa: E402

SITE, TAIL0, TAIL1 = 0x0046741E, 0x00467328, 0x0046742C
PHASE = 0x00939FD4
FRAME, RET, CON = 0x00308000, 0x0047F000, 0x00500000      # ebp, caller return, Console (canvas = CON+0x40+0x444)


def _pristine_tail() -> bytes:
    import config
    import pefile
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        va = base + s.VirtualAddress
        if va <= TAIL0 < va + s.Misc_VirtualSize:
            return s.get_data()[TAIL0 - va:TAIL1 - va]
    raise AssertionError("tail not in any section")


def _yaml_map_dash() -> bytes:
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    c = {c["id"]: c for cave in caves for c in cave.get("contents", [])}["t_map_dash"]
    assert symtab["t_map_dash"] == AL.PCAVE2 + AL.MAP_DASH_OFF == AL.PCAVE2 + int(c["offset"])
    return ap.ByteTemplate(c["bytes"]).resolve(AL.PCAVE2 + AL.MAP_DASH_OFF, symtab)


MAP_DASH = _yaml_map_dash()


def test_map_dash_yaml_is_the_assembler_output():
    assert MAP_DASH == AL.build_map_dash()


def _tail_to_t_map_dash() -> bytes:
    b = bytearray(_pristine_tail())
    i = SITE - TAIL0
    assert b[i] == 0xE8 and i + 5 + TAIL0 + struct.unpack_from("<i", b, i + 1)[0] == AL.BUFFER_LINE
    struct.pack_into("<i", b, i + 1, (AL.PCAVE2 + AL.MAP_DASH_OFF) - (SITE + 5))
    return bytes(b)


TAIL = _tail_to_t_map_dash()
SLOT_COLOUR = {0: 0xFA, 1: 0xFE, 2: 0xF9}


def run(g, pts, on, off, ctr, mode=0, colour=0x5A, flag=0):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AL.PCAVE2 + 0xF000, 0x1000), (0x00300000, 0x10000), (CON, 0x20000), (TPL.LOG, 0x1000),
                       (0x668000, 0x1000), (AL.BUFFER_LINE & ~0xFFF, 0x1000), (RET & ~0xFFF, 0x1000),
                       (TAIL0 & ~0xFFF, 0x1000), (PHASE & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(AL.PCAVE2 + AL.OFF, TPL.YAML)
    uc.mem_write(AL.PCAVE2 + AL.MAP_DASH_OFF, MAP_DASH)
    uc.mem_write(AL.BUFFER_LINE, TPL._stub())
    uc.mem_write(AL.G, g.to_bytes(4, "little"))
    uc.mem_write(PHASE, ctr.to_bytes(4, "little", signed=True))
    uc.mem_write(TAIL0, TAIL)
    uc.mem_write(RET, b"\xF4")
    w = lambda a, v: uc.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    x1, y1, x2, y2 = pts
    w(CON, CON + 0x100)                        # [esi] = vtable-ish block whose +4 = 0x40
    w(CON + 0x104, 0x40)
    w(CON + 0x1DD84, flag)                      # non-zero -> colour 0xFB
    for off_, v in ((-0x10, x1), (-0x8, y1), (-0xC, x2), (-0x4, y2), (0, 0x7777), (4, RET),
                    (0xC, colour), (0x18, mode), (0x1C, on), (0x20, off), (0x24, 0)):
        w(FRAME + off_, v)
    w(FRAME - 0x14, 0xE51)                      # saved esi
    w(FRAME - 0x18, 0xED1)                      # saved edi
    for r, v in ((UC_X86_REG_ESP, FRAME - 0x18), (UC_X86_REG_EBP, FRAME), (UC_X86_REG_ESI, CON),
                 (UC_X86_REG_EDI, x2), (UC_X86_REG_EDX, y2), (UC_X86_REG_ECX, 0),
                 (UC_X86_REG_EBX, 0xB0B)):   # 0x467328..36 store edi -> x2, edx + ecx ([+0x1DDC0]) -> y2
        uc.reg_write(r, v)
    hit = []
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s, _: (hit.append(a), u.emu_stop()) if a == RET else None)
    uc.emu_start(TAIL0, 0, count=200_000)
    assert hit == [RET] and uc.reg_read(UC_X86_REG_ESP) == FRAME + 8 + 0x20
    assert (uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI),
            uc.reg_read(UC_X86_REG_EBP)) == (0xB0B, 0xE51, 0xED1, 0x7777)
    n = int.from_bytes(uc.mem_read(TPL.LOG, 4), "little")
    calls = []
    for i in range(n):
        f = [int.from_bytes(uc.mem_read(TPL.LOG + 4 + 40 * i + 4 * k, 4), "little", signed=True) for k in range(10)]
        want = 0xFB if flag else SLOT_COLOUR.get(mode, colour)
        assert f[9] == CON + 0x40 + 0x444 and f[4] == 0 and f[5] == want
        calls.append((f[0], f[1], f[2], f[3], f[6], f[7], f[8]))
    return calls


@pytest.mark.parametrize("g", [16, 17, 22, 24, 25, 32, 40])
@pytest.mark.parametrize("dash", [(3, 5), (2, 2)])
@pytest.mark.parametrize("pts", [(9, 29, 300, 60), (100, 20, 120, 250), (50, 50, 10, 10), (30, 30, 30, 30)])
@pytest.mark.parametrize("ctr", [0, 5, 7, 0x12345])
@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_site_calls_are_the_law(g, dash, pts, ctr, mode):
    on, off = dash
    phase = (on + off - 1) & ctr
    dx, dy = SL.map_dest_slot_shift(mode, g)
    x1, y1, x2, y2 = pts
    assert run(g, pts, on, off, ctr, mode) == SL.planwin_line_calls(x1 + dx, y1 + dy, x2 + dx, y2 + dy,
                                                                     on, off, phase, g)


@pytest.mark.parametrize("flag", [0, 1])
def test_colour_unchanged(flag):
    for mode in (0, 1, 2, 5):
        run(40, (9, 29, 300, 60), 3, 5, 2, mode, 0x33, flag)


@pytest.mark.parametrize("g", list(range(16, 72)))
def test_slot_lines_never_overlap(g):
    """Slots 0/1/2 on one x-major leg: each slot's K rows are disjoint (the audit's covered-slot-0 defect)."""
    rows = []
    for mode in (0, 1, 2):
        rows.append({c[1] for c in run(g, (9, 29, 300, 29), 3, 5, 0, mode)})
    assert not (rows[0] & rows[1]) and not (rows[0] & rows[2]) and not (rows[1] & rows[2])
    assert all(len(r) == SL.stroke_width(g) or (g <= 24 and len(r) == 1) for r in rows)


def test_shift_law_is_vanilla_at_native_and_k_above():
    assert SL.map_dest_slot_shift(1, 16) == (1, 1) and SL.map_dest_slot_shift(2, 16) == (0, -1)
    assert SL.map_dest_slot_shift(1, 40) == (2, 2) and SL.map_dest_slot_shift(2, 40) == (0, -2)
    assert SL.map_dest_slot_shift(0, 40) == (0, 0) and SL.map_dest_slot_shift(3, 40) == (0, 0)


def test_4k_goto_dash_is_two_px_7_on_12_off():
    calls = run(40, (9, 29, 300, 60), 3, 5, 2)
    assert [c[1] for c in calls] == [29, 30] and all(c[4:] == (7, 12, 5) for c in calls)
