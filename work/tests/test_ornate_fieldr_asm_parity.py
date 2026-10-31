"""Unicorn parity for t_orn_fieldsub (assemble_ornate_fieldr.py) against scaling_laws.ornate_field_right_sub.

The REAL thunk_popup_fieldpads bytes (resolved from patches.yaml) run behind it, so the assertion is on what the
engine will actually store: field L [ebp-0x34] and field R [ebp-0x2c] of an UNKEYED ornate popup are inset EQUALLY.
Inputs are the live tutorial-window numbers read by uimod debugdump (W 1599 / margin 47 @g40, 998 / 29 @g25).
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn")
pytest.importorskip("keystone")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,  # noqa: E402
                               UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_ornate_fieldr as OF  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000
STACK, SP0, TRAP = 0x2500000, 0x2508000, 0x2600000
POPUP = 0x2700000
FRAME = 0x2504000


@pytest.fixture(scope="module")
def world():
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    st = dict(ap.build_symbol_table(symbols, caves))
    if "t_orn_fieldsub" not in st:
        pytest.skip("ornate_field_right not spliced yet")
    ents = {e["id"]: e for c in caves for e in (c.get("contents") or [])}
    fp = ap.ByteTemplate(ents["thunk_popup_fieldpads"]["bytes"]).resolve(st["thunk_popup_fieldpads"], st)
    mine = ap.ByteTemplate(ents["t_orn_fieldsub"]["bytes"]).resolve(st["t_orn_fieldsub"], st)
    assert st["t_orn_fieldsub"] == PCAVE2 + OF.OFF and st["thunk_popup_fieldpads"] == OF.FIELDPADS and st["g_band_popup"] == OF.G_BAND_POPUP
    assert mine == OF.build().replace((0x7A111111).to_bytes(4, "little"), OF.FIELDPADS.to_bytes(4, "little"))
    site = [s for s in sites if getattr(s, "virtual_addr", None) == OF.SITE or (isinstance(s, dict) and s.get("virtual_addr") == OF.SITE)]
    assert "t_tw_right" not in st                                 # the superseded, ineffective thunk is gone
    return st, fp, mine


def run(world, g, ptype, win_w, margin_l, keyed, title_right=0):
    st, fp, mine = world
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(PCAVE2, 0x30000)
    uc.mem_map(0x600000, 0x100000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(TRAP, 0x1000)
    uc.mem_map(POPUP, 0x4000)
    uc.mem_write(st["t_orn_fieldsub"], mine)
    uc.mem_write(st["thunk_popup_fieldpads"], fp)
    uc.mem_write(OF.G, struct.pack("<I", g))
    uc.mem_write(POPUP + 0x30AC, struct.pack("<i", ptype * 10000))
    uc.mem_write(POPUP + 0x30BC, struct.pack("<i", win_w))
    uc.mem_write(st["g_band_popup"], struct.pack("<I", POPUP if keyed else 0))
    uc.mem_write(st["g_title_right"], struct.pack("<i", title_right))
    uc.mem_write(TRAP, b"\xf4")
    uc.mem_write(SP0, struct.pack("<I", TRAP))
    # the engine state at 0x40612F: edi = field L src (margin sum), ecx = winR - fl(10g/16) [fieldR thunk] - 9 [ornate],
    # ebx = content top, edx = popup type, eax = [+0x30d4] (tested last), esi = popup, ebp = the painter's frame
    base10 = SL.popup_scale_floor(10, g) if g > 16 else 10
    ecx = win_w - base10 - (9 if ptype in (2, 6) else 0)
    for r, v in ((UC_X86_REG_ESP, SP0), (UC_X86_REG_EBP, FRAME), (UC_X86_REG_ESI, POPUP), (UC_X86_REG_EDI, margin_l),
                 (UC_X86_REG_ECX, ecx), (UC_X86_REG_EBX, 67), (UC_X86_REG_EDX, ptype), (UC_X86_REG_EAX, 188)):
        uc.reg_write(r, v & 0xFFFFFFFF)

    def hook(u, addr, size, _):
        if addr == TRAP:
            u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(st["t_orn_fieldsub"], 0, count=100000)
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
    l, = struct.unpack("<i", bytes(uc.mem_read(FRAME - 0x34, 4)))
    r, = struct.unpack("<i", bytes(uc.mem_read(FRAME - 0x2C, 4)))
    return l, r


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_unkeyed_ornate_field_is_inset_equally_on_both_sides(world, g):
    ps3 = (3 * g) >> 4 if g > 16 else 3
    for native_w in (490, 640):
        w = SL.popup_scale_floor(native_w, g) if g > 16 else native_w
        ml = SL.popup_scale_floor(SL.ORNATE_FIELD_LEFT_MARGIN, g) if g > 16 else 19
        for ptype in (2, 6):
            l, r = run(world, g, ptype, w, ml, keyed=False)
            assert l == ml - ps3
            # THE law: right inset == left inset (vanilla 16 == 16) -- on the half-open axis at g > 16 (fix 26 v2:
            # the inclusive-drawn field box mirrors x <-> W - 1 - x)
            assert w - (g > 16) - r == l, (g, ptype, l, w - r)
            assert w - r == SL.popup_scale_floor(10, g) * (g > 16) + 10 * (g <= 16) + SL.ornate_field_right_sub(g) - ps3
    assert SL.ornate_field_right_sub(16) == 9


def test_scaling_live_tutorial_window_numbers():
    # uimod debugdump 2026-09-19: W 1599 margins 47 @g40 ; W 998 margins 29 @g25.  Measured with the native 9: R inset 26 / 20.
    for g, w, ml, was in ((40, 1599, 47, 26), (25, 998, 29, 20)):
        ps3 = (3 * g) >> 4
        assert SL.popup_scale_floor(10, g) + 9 - ps3 + (0 if g == 40 else 0) in (was, was + 1)      # reproduces the defect
        assert SL.popup_scale_floor(10, g) + SL.ornate_field_right_sub(g) - ps3 == ml - ps3 + 1      # and the cure (half-open)


@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_scaling_flat_and_keyed_popups_are_untouched(world, g):
    ps3 = (3 * g) >> 4 if g > 16 else 3
    w, ml = 1500, 47
    base10 = SL.popup_scale_floor(10, g) if g > 16 else 10
    for ptype in (0, 5, 1):                                       # not ornate: fieldpads' own result, bit for bit
        l, r = run(world, g, ptype, w, ml, keyed=False)
        assert (l, r) == (ml - ps3, w - base10 + ps3)
    if g > 16:                                                    # keyed ornate: the titled arm owns the field R
        l, r = run(world, g, 2, w, ml, keyed=True, title_right=1400)
        assert r == 1400 - 2 * ps3 + ps3
