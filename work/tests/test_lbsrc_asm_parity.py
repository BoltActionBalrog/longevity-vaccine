"""Differential (Unicorn): thunk_lbsrc_scale (fix 29) -- the type-2 popup ListBox's layout sources scaled ONCE at
their writer, Popup_calculate_dimensions' BasePop_calc call @0x404E93 (group popup_type2_list_scale).

The yaml bytes (resolved with the real symbol table) run on a synthetic popup: esi = ecx = popup, the ListBox
sub-object at popup+0x21D0 whose vbtable [+8] is the Dialog adjustor (0xBA0 in the real image), the type at
popup+0x2350, and the three sources on the Dialog part.  Every outcome must equal
scaling_laws.popup_listbox_sources, the tail must be `push thunk_scale_box_margin; ret` with the E8's return on top
(the old target of the site, so the margin chain runs unchanged), and every register must survive.

Also pinned here (no emulation): the law composes -- every later calc-entry pass (thunk_lbcalc_scale v5,
listbox_calc_entry_sources) reads the same values, so pass 1 (box reserve) and pass 2 (list window) agree at every
g; the retired v4 popup arm did not at g 17..19 (the 1600x900 Go To defect).
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
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402


def _load():
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
    site = next(s for s in doc["sites"] if s["id"] == "Popup_calculate_dimensions.box_margin_scale")
    return symtab, thunks, site


SYMTAB, THUNKS, SITE = _load()
G_VA = SYMTAB["g_popup_scale_num"]
POPUP_ACTIVE = SYMTAB["g_popup_active"]
BOX_MARGIN = SYMTAB["thunk_scale_box_margin"]
CAVE_LO, CAVE_HI = 0xA0C000, 0xA40000
STACK = 0x00200000
POP = 0x00300000
VBT = 0x00380000
ADJ = 0xBA0                      # the real image's [[popup+0x21D0]+8] (Popup_ctor 0x4048A0, vbtable 0x670A78)
D = POP + 0x21D0 + ADJ
RET = 0x00404E98                 # the E8 @0x404E93's return address
GS = (0, 12, 16) + tuple(range(17, 41))


def _run(g, *, active=1, typ=2, stride=0x13, gap=3, indent=3):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(CAVE_LO, CAVE_HI - CAVE_LO)
    uc.mem_map(0x660000, 0x10000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(POP, 0x10000)
    uc.mem_map(VBT, 0x1000)
    va, code = THUNKS["thunk_lbsrc_scale"]
    uc.mem_write(va, code)
    uc.mem_write(BOX_MARGIN, b"\xF4")                       # hlt: the old target is where the tail must land
    uc.mem_write(G_VA, struct.pack("<i", g))
    uc.mem_write(POPUP_ACTIVE, struct.pack("<i", active))
    uc.mem_write(POP + 0x21D0, struct.pack("<I", VBT))
    uc.mem_write(VBT + 8, struct.pack("<I", ADJ))
    uc.mem_write(POP + 0x2350, struct.pack("<i", typ))
    for off, v in ((0x48, stride), (0x44, gap), (0x34, indent)):
        uc.mem_write(D + off, struct.pack("<i", v))
    sentinels = (D + 0x30, D + 0x38, D + 0x3C, D + 0x40, D + 0x4C)  # neighbours must stay untouched
    for a in sentinels:
        uc.mem_write(a, struct.pack("<I", 0x5A5A5A5A))
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<I", RET))
    regs = {UC_X86_REG_ESP: esp, UC_X86_REG_ESI: POP, UC_X86_REG_ECX: POP, UC_X86_REG_EAX: 0x11223344,
            UC_X86_REG_EDX: 0x55667788, UC_X86_REG_EBX: 0x99AABBCC, UC_X86_REG_EDI: 6, UC_X86_REG_EBP: 0x1234}
    for r, v in regs.items():
        uc.reg_write(r, v)
    try:
        uc.emu_start(va, 0, count=200)
    except unicorn.UcError:
        pass
    eip = uc.reg_read(UC_X86_REG_EIP)
    assert eip in (BOX_MARGIN, BOX_MARGIN + 1), hex(eip)
    for r, v in regs.items():
        assert uc.reg_read(r) == v, (r, hex(uc.reg_read(r)))
    assert struct.unpack("<I", uc.mem_read(esp, 4))[0] == RET
    for a in sentinels:
        assert struct.unpack("<I", uc.mem_read(a, 4))[0] == 0x5A5A5A5A
    return tuple(struct.unpack("<i", uc.mem_read(D + off, 4))[0] for off in (0x48, 0x44, 0x34))


@pytest.mark.parametrize("g", GS)
def test_native_list_sources_scale_once_to_the_law(g):
    assert _run(g) == SL.popup_listbox_sources(0x13, 3, 3, g)
    if g > 16:
        assert _run(g) == tuple(SL.popup_scale_floor(v, g) for v in (0x13, 3, 3))


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("stride,gap,indent", (
    (-1, 3, 3),            # PopupDialogState 5: the writer skipped the stride -> the ctor's -1 (font rows)
    (0, 3, 3),
    (0x16, 3, 3),          # a native-looking stride that is not this writer's
))
def test_other_strides_pass_through(g, stride, gap, indent):
    assert _run(g, stride=stride, gap=gap, indent=indent) == (stride, gap, indent)
    assert SL.popup_listbox_sources(stride, gap, indent, g) == (stride, gap, indent)


@pytest.mark.parametrize("g", range(17, 41))
def test_rerun_on_the_same_popup_never_rescales(g):
    """A second Popup_calc pass that did not rewrite the sources (state 5 on a reused popup) finds the scaled
    stride, which is never the native 19 at g > 16 -> identity."""
    once = _run(g)
    assert once[0] != 0x13
    assert _run(g, stride=once[0], gap=once[1], indent=once[2]) == once


@pytest.mark.parametrize("g", (17, 18, 19, 22, 40))
@pytest.mark.parametrize("typ", (0, 1, 4, 6, 8, 16, 0x22))
def test_only_the_listbox_type(g, typ):
    """popup[+0x2350] is the dims-dispatch key (0x6132A0): exactly 2 reaches ListBox_calculate_dimensions."""
    assert _run(g, typ=typ) == (0x13, 3, 3)
    assert SL.popup_listbox_sources(0x13, 3, 3, g, popup_type=typ) == (0x13, 3, 3)


@pytest.mark.parametrize("g", (17, 18, 19, 40))
def test_outside_exec3_is_identity(g):
    assert _run(g, active=0) == (0x13, 3, 3)
    assert SL.popup_listbox_sources(0x13, 3, 3, g, popup_active=False) == (0x13, 3, 3)
    assert _run(g, active=2) == SL.popup_listbox_sources(0x13, 3, 3, g)       # nested exec_3: refcount 2


def test_site_and_tail_keep_the_margin_chain():
    """The site's E8 now enters thunk_lbsrc_scale; the thunk's last instruction pushes the site's OLD target."""
    va, code = THUNKS["thunk_lbsrc_scale"]
    assert int(str(SITE["virtual_addr"]), 0) == 0x404E93
    assert SITE["original_bytes"].replace(" ", "").upper() == "E868E91F00"
    nb = ap.ByteTemplate(SITE["new_bytes"]).resolve(0x404E93, SYMTAB)
    assert nb[0] == 0xE8 and 0x404E98 + struct.unpack("<i", nb[1:5])[0] == va
    assert code[-6:] == b"\x68" + struct.pack("<I", BOX_MARGIN) + b"\xC3"


# ------------------------------------------------------------------------------------- the law composes
def _v4_popup_arm(stride, gap, indent, g):
    """The retired calc-entry arm (thunk_lbcalc_scale v4 under g_popup_active), for the counter-example."""
    if g <= 16 or not 0 < stride <= 0x16:
        return stride, gap, indent
    return tuple(SL.popup_scale_floor(v, g) for v in (stride, gap, indent))


@pytest.mark.parametrize("g", range(16, 41))
def test_every_calc_pass_reads_the_same_sources(g):
    src = SL.popup_listbox_sources(0x13, 3, 3, g)
    passes = [src]
    for _ in range(3):                                   # BasePop_calc, ListBox_attach, a re-attach
        passes.append(SL.listbox_calc_entry_sources(*passes[-1], g, filedlg_active=False))
    assert len(set(passes)) == 1
    rows = 12
    assert SL.popup_listbox_rows_h(rows, src[0], src[1]) == rows * SL.popup_scale_floor(0x13, g) - src[1]


@pytest.mark.parametrize("g", range(16, 41))
def test_the_retired_arm_split_the_passes_exactly_at_g17_19(g):
    p1 = _v4_popup_arm(0x13, 3, 3, g)                    # pass 1 (BasePop_calc: the reserve)
    p2 = _v4_popup_arm(*p1, g)                           # pass 2 (ListBox_attach: the list window)
    split = SL.popup_listbox_rows_h(12, p1[0], p1[1]) != SL.popup_listbox_rows_h(12, p2[0], p2[1])
    assert split == (17 <= g <= 19)
    if g == 18:                                          # the 1600x900 Go To shot: reserve 249, window 273
        assert (SL.popup_listbox_rows_h(12, p1[0], p1[1]), SL.popup_listbox_rows_h(12, p2[0], p2[1])) == (249, 273)
