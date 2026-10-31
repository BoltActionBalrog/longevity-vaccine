"""Differential (Unicorn): the in-game LOAD/SAVE list scrollbar (2026-09-26p).

  * thunk_lbcalc_scale v4 -- the ListBox_calculate_dimensions entry detour now
    also scales the Dialog layout sources under g_filedlg_active, so the
    populate's visible-row count uses the SCALED stride (v3: popups only -> the
    file list counted rows with the native 22 px stride, never engaged its bar
    and clipped the last row).  One-shot keyed on the native stride, native
    no-op at g <= 16.
  * thunk_lbcalc_scale v5 (fix 29) -- the g_popup_active arm is RETIRED: its
    0 < stride <= 0x16 key re-scaled the popup list's fl(19 g/16) = 20/21/22 at
    g 17..19 on the second calc pass (thunk_lbsrc_scale now scales the popup
    list once at its writer, tests/test_lbsrc_asm_parity.py).  Under
    g_filedlg_active v5 is v4 byte for byte in effect: the differential below
    runs both on every FileDlg state (law scaling_laws.listbox_calc_entry_sources).
  * thunk_filedlg_slidehide_disarm v2 -- also zeroes g_rail_sb when it is the
    closing FileDlg's bar (+0x3DD8); unrelated stashes survive.

Bytes are resolved from patches.yaml with the real symbol table.
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
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP, UC_X86_REG_EBP,
)

import apply_patches as ap  # noqa: E402
from scaling_laws import listbox_calc_entry_sources, popup_scale_floor  # noqa: E402


def _load():
    import yaml
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    thunks = {}
    for cave in doc["code_caves"]:
        base = cave["virtual_addr"]
        base = int(base, 16) if isinstance(base, str) else base
        for c in cave.get("contents", []) or []:
            off = c["offset"]
            off = int(off, 16) if isinstance(off, str) else off
            thunks[c["id"]] = (base + off, ap.ByteTemplate(c["bytes"]).resolve(base + off, symtab))
    return symtab, thunks


SYMTAB, THUNKS = _load()
G_VA = SYMTAB["g_popup_scale_num"]
POPUP_ACTIVE = SYMTAB["g_popup_active"]
FILEDLG_ACTIVE = SYMTAB["g_filedlg_active"]
FD_WINBUF = SYMTAB["g_fd_winbuf"]
RAIL_SB = SYMTAB["g_rail_sb"]
CAVE_LO, CAVE_HI = 0xA0C000, 0xA40000
STACK = 0x00200000
OBJ = 0x00300000                 # ListBox `this` / a FileDlg window
ADJ = 0xA60                      # FileDlg list: Dialog sub-object at this + [[this]+8]
VTBL = 0x00380000
CALC_RESUME = 0x0060A1E6
DISARM_RESUME = 0x0045DE60


def _uc():
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE_LO, CAVE_HI - CAVE_LO)
    uc.mem_map(0x660000, 0x10000)
    uc.mem_map(0x45D000, 0x1000)
    uc.mem_map(0x60A000, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(OBJ, 0x10000)
    uc.mem_map(VTBL, 0x1000)
    uc.mem_write(CALC_RESUME, b"\xF4")
    uc.mem_write(DISARM_RESUME, b"\xF4")
    return uc


def _run(uc, va, count=300):
    try:
        uc.emu_start(va, 0, count=count)
    except unicorn.UcError:
        pass
    return uc.reg_read(UC_X86_REG_EIP)


# ---------------------------------------------------------------- lbcalc_scale v4
def _calc(g, popup, filedlg, stride, gap=6, indent=25, code=None):
    uc = _uc()
    va, yaml_code = THUNKS["thunk_lbcalc_scale"]
    uc.mem_write(va, code or yaml_code)
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(POPUP_ACTIVE, struct.pack("<i", popup))
    uc.mem_write(FILEDLG_ACTIVE, struct.pack("<i", filedlg))
    uc.mem_write(OBJ, struct.pack("<I", VTBL))
    uc.mem_write(VTBL + 8, struct.pack("<I", ADJ))
    dlg = OBJ + ADJ
    uc.mem_write(dlg + 0x34, struct.pack("<i", indent))
    uc.mem_write(dlg + 0x44, struct.pack("<i", gap))
    uc.mem_write(dlg + 0x48, struct.pack("<i", stride))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I", 0xCAFE0000))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, OBJ)
    uc.reg_write(UC_X86_REG_EBX, 0x1234)
    uc.reg_write(UC_X86_REG_ESI, 0x5678)
    uc.reg_write(UC_X86_REG_EDX, 0x9ABC)
    eip = _run(uc, va)
    assert eip in (CALC_RESUME, CALC_RESUME + 1), hex(eip)
    # displaced prologue replayed: push ebx / push esi / mov esi,ecx / xor ebx,ebx
    assert uc.reg_read(UC_X86_REG_ESP) == esp - 8
    assert struct.unpack("<II", uc.mem_read(esp - 8, 8)) == (0x5678, 0x1234)
    assert uc.reg_read(UC_X86_REG_ESI) == OBJ and uc.reg_read(UC_X86_REG_EBX) == 0
    assert uc.reg_read(UC_X86_REG_ECX) == OBJ
    assert uc.reg_read(UC_X86_REG_EDX) == 0x9ABC
    return struct.unpack("<3i", bytes(uc.mem_read(dlg + 0x44, 8)) + bytes(uc.mem_read(dlg + 0x34, 4)))


@pytest.mark.parametrize("g", (17, 18, 19, 22, 25, 40))
@pytest.mark.parametrize("popup,filedlg", ((0, 1), (1, 1)))
def test_scales_filedlg_sources_once(g, popup, filedlg):
    gap, stride, indent = _calc(g, popup, filedlg, 0x16)
    s = lambda v: popup_scale_floor(v, g)  # noqa: E731
    assert (gap, stride, indent) == (s(6), s(0x16), s(25))
    assert (stride, gap, indent) == listbox_calc_entry_sources(0x16, 6, 25, g, filedlg_active=True)


@pytest.mark.parametrize("g", range(17, 41))
def test_popup_lists_pass_through_the_calc(g):
    """v5: the popup gate alone no longer scales -- neither the writer's native 0x13 (thunk_lbsrc_scale owns it
    now, BEFORE any calc) nor, above all, the once-scaled fl(19 g/16), which at g 17..19 (20/21/22) the retired
    key re-scaled on ListBox_attach's second pass."""
    s19 = popup_scale_floor(0x13, g)
    for stride in (0x13, s19, popup_scale_floor(0x16, g)):
        assert _calc(g, 1, 0, stride, gap=3, indent=3) == (3, stride, 3)
        assert listbox_calc_entry_sources(stride, 3, 3, g, filedlg_active=False) == (stride, 3, 3)


#: thunk_lbcalc_scale v4 (c67c3cd1 and before) as patches.yaml carried it
V4_BYTES = ("83 3D {abs32:g_popup_active} 00 75 09 83 3D {abs32:g_filedlg_active} 00 74 42 A1 {abs32:g_popup_scale_num}"
            " 83 F8 10 7E 38 51 52 8B 11 8B 52 08 01 CA 8B 4A 48 85 C9 7E 26 83 F9 16 7F 21 0F AF C8 C1 F9 04 89 4A"
            " 48 8B 4A 44 0F AF C8 C1 F9 04 89 4A 44 8B 4A 34 0F AF C8 C1 F9 04 89 4A 34 5A 59 53 56 89 CE 31 DB 68"
            " E6 A1 60 00 C3")


@pytest.mark.parametrize("g", (0, 12, 16) + tuple(range(17, 41)))
def test_filedlg_case_unchanged_from_v4(g):
    """The LOAD/SAVE list: v5 == v4 on every FileDlg state (either popup state; native, once-scaled, derived and
    unset strides) -- the arm the FileDlg relies on is byte-for-byte the old one."""
    va, _ = THUNKS["thunk_lbcalc_scale"]
    v4 = ap.ByteTemplate(V4_BYTES).resolve(va, SYMTAB)
    for popup in (0, 1):
        for stride in (0x16, popup_scale_floor(0x16, g), -1, 0, 0x13):
            assert _calc(g, popup, 1, stride) == _calc(g, popup, 1, stride, code=v4)


@pytest.mark.parametrize("g", (17, 25, 40))
def test_already_scaled_or_derived_stride_untouched(g):
    for stride in (popup_scale_floor(0x16, g), -1, 0):     # second pass / derive-from-font / unset
        assert _calc(g, 0, 1, stride) == (6, stride, 25)


@pytest.mark.parametrize("popup,filedlg", ((0, 0), (1, 0), (0, 1)))
def test_native_or_ungated_is_identity(popup, filedlg):
    assert _calc(16, popup, filedlg, 0x16) == (6, 0x16, 25)
    if not (popup or filedlg):
        assert _calc(40, 0, 0, 0x16) == (6, 0x16, 25)


def test_filedlg_rows_engage_the_bar_at_every_g():
    """The defect this fixes, at the law level: 14 items, list box h = s(288).
    The scaled stride counts fewer visible rows than items -> bar engages, as
    vanilla does at 1024 (13 rows); the native stride under-counted."""
    for g in (22, 25, 40):
        h = popup_scale_floor(288, g)
        gap, stride = popup_scale_floor(6, g), popup_scale_floor(0x16, g)
        rows_scaled = (h + gap) // stride
        rows_native = (h + 6) // 0x16
        assert rows_scaled == 13 and rows_scaled < 14 <= rows_native


# ---------------------------------------------------------------- slidehide_disarm v2
def _disarm(win, winbuf, rail_sb):
    uc = _uc()
    va, code = THUNKS["thunk_filedlg_slidehide_disarm"]
    uc.mem_write(va, code)
    uc.mem_write(FD_WINBUF, struct.pack("<I", winbuf))
    uc.mem_write(RAIL_SB, struct.pack("<I", rail_sb))
    esp = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, win)
    uc.reg_write(UC_X86_REG_EBP, STACK + 0x9000)
    eip = _run(uc, va)
    assert eip in (DISARM_RESUME, DISARM_RESUME + 1)
    assert uc.reg_read(UC_X86_REG_ECX) == (STACK + 0x9000 - 0x10F0) & 0xFFFFFFFF   # displaced lea replayed
    assert uc.reg_read(UC_X86_REG_ESP) == esp
    return (struct.unpack("<I", uc.mem_read(FD_WINBUF, 4))[0],
            struct.unpack("<I", uc.mem_read(RAIL_SB, 4))[0])


def test_disarm_clears_the_closing_filedlgs_stashes():
    assert _disarm(OBJ, OBJ + 0x444, OBJ + 0x3DD8) == (0, 0)


def test_disarm_leaves_other_windows_stashes():
    other_sb = 0x6AF164                                     # the picker bar
    assert _disarm(OBJ, OBJ + 0x444, other_sb) == (0, other_sb)
    assert _disarm(OBJ + 0x100, OBJ + 0x444, OBJ + 0x3DD8) == (OBJ + 0x444, OBJ + 0x3DD8)
