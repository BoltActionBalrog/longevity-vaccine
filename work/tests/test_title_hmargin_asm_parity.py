"""thunk_title_hmargin v2 (F36): the shipped bytes == scaling_laws.title_band_hmargin_lr, under Unicorn.

The thunk runs on Popup_on_draw_background's "+3" path (0x40600A: the console hidden -- every main-menu popup -- or a
non-rail family) and from thunk_untitled_stash.  It stores ins = fl(4g/16) - 1 on [ebp-0x14] / [ebp-0xc]; the engine
then adds the last +1 / -1 (0x406027 `inc edx`, thunk_title_height's `dec edx`).  v2: at g > 16 a non-ornate band's R
comes in one more, so the band map's inclusive footprint mirrors L about the half-open axis.

Checked from the yaml bytes (resolved by apply_patches' own ByteTemplate at the symbol's address), for every g in
1..40 and families 0..7 / 10 / 1000, over several frame rects: the final (L, R) after the engine's +1 / -1 ==
the law; ebx == 3 (the 9-slice step downstream); ecx, esi, edi, ebp and the stack preserved; only [ebp-0x14] and
[ebp-0xc] written.  Plus: the yaml template == assemble_title_hmargin's, and both call sites reach the v2 slot.
~1 s (one Unicorn, a few thousand short runs).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_MEM_WRITE, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_title_hmargin as TH  # noqa: E402
import scaling_laws as SL  # noqa: E402

PAGE = 0x1000
STACK = 0x00200000
FRAME = STACK + 0x800
RET = 0x00406010                  # never executed (emu stops there)


@pytest.fixture(scope="module")
def st():
    _s, _g, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    return ap.build_symbol_table(symbols, caves), caves


def _entry(caves, name):
    for cave in caves:
        for ent in cave.get("contents") or []:
            if ent.get("id") == name:
                return cave, ent
    raise KeyError(name)


@pytest.fixture(scope="module")
def mu(st):
    table, caves = st
    va = table["thunk_title_hmargin"]
    _c, ent = _entry(caves, "thunk_title_hmargin")
    code = ap.ByteTemplate(ent["bytes"]).resolve(va, table)
    m = Uc(UC_ARCH_X86, UC_MODE_32)
    m.mem_map(va & ~(PAGE - 1), 2 * PAGE)
    m.mem_map(table["g_popup_scale_num"] & ~(PAGE - 1), PAGE)
    m.mem_map(STACK, PAGE)
    m.mem_map(RET & ~(PAGE - 1), PAGE)
    m.mem_write(va, code)
    writes = []
    m.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, addr, size, val, ud: writes.append(addr))
    yield m, va, table["g_popup_scale_num"], writes
    del m


def _call(mu, g, family, L, R):
    m, va, gva, writes = mu
    m.mem_write(gva, struct.pack("<i", g))
    m.mem_write(STACK, bytes(PAGE))
    for off, v in ((-0x14, L), (-0xC, R), (-4, family), (-0x10, 777), (-8, 888)):
        m.mem_write(FRAME + off, struct.pack("<i", v))
    sp = FRAME - 0x100
    m.mem_write(sp, struct.pack("<I", RET))
    m.reg_write(UC_X86_REG_ESP, sp)
    m.reg_write(UC_X86_REG_EBP, FRAME)
    m.reg_write(UC_X86_REG_EBX, 0x11111111)
    m.reg_write(UC_X86_REG_ECX, 0x22222222)
    m.reg_write(UC_X86_REG_ESI, 0x33333333)
    m.reg_write(UC_X86_REG_EDI, 0x44444444)
    writes.clear()
    m.emu_start(va, RET, count=200)
    rd = lambda off: struct.unpack("<i", m.mem_read(FRAME + off, 4))[0]
    assert m.reg_read(UC_X86_REG_EBX) == 3
    assert (m.reg_read(UC_X86_REG_ECX), m.reg_read(UC_X86_REG_ESI), m.reg_read(UC_X86_REG_EDI)) == \
        (0x22222222, 0x33333333, 0x44444444)
    assert m.reg_read(UC_X86_REG_EBP) == FRAME and m.reg_read(UC_X86_REG_ESP) == sp + 4
    assert set(writes) <= {FRAME - 0x14, FRAME - 0xC}, [hex(a) for a in writes]
    assert (rd(-0x10), rd(-8), rd(-4)) == (777, 888, family)
    return rd(-0x14) + 1, rd(-0xC) - 1          # the engine's +1 / -1 (0x406027, thunk_title_height)


@pytest.mark.parametrize("family", (0, 1, 2, 3, 4, 5, 6, 7, 10, 1000))
def test_hmargin_v2_matches_the_law(mu, family):
    for g in range(1, 41):
        for L, R in ((0, 1697), (0, 763), (35, 1255), (9, 2049)):
            assert _call(mu, g, family, L, R) == SL.title_band_hmargin_lr(L, R, family, g), (g, family, L, R)


def test_hmargin_v2_is_v1_where_v1_was_right(mu):
    """g <= 16 (every family) and the ornate families (every g) are v1 bytes' result: L + fl(4g/16), R - fl(4g/16)."""
    for g in range(1, 41):
        ins = (4 * g) >> 4
        for family in ((0, 1, 2, 3, 4, 5, 6, 7) if g <= 16 else (2, 6)):
            assert _call(mu, g, family, 0, 1000) == (ins, 1000 - ins), (g, family)


def test_hmargin_yaml_is_the_assembler_output_and_both_callers_reach_it(st):
    table, caves = st
    cave, ent = _entry(caves, "thunk_title_hmargin")
    assert cave["id"] == "pcave2" and ent["offset"] == 0x35300
    _blob, tmpl = TH.template()
    assert " ".join(ent["bytes"].split()) == tmpl
    assert table["thunk_title_hmargin"] == TH.VA
    txt =(ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    assert '"E8 {rel32:thunk_title_hmargin} 90 90' in txt                     # the 0x40600A call (21-byte block)
    _cu, un = _entry(caves, "thunk_untitled_stash")
    assert "E8 {rel32:thunk_title_hmargin}" in un["bytes"]                    # the untitled stash's call
