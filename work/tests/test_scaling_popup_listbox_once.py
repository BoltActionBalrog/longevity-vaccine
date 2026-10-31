"""Type-2 (#listbox) popups: the list window and the box reserve agree at every g, on every pass (fix 29).

Law (scaling_laws.py, the source of truth): popup_listbox_sources -- the popup list's layout sources (stride
[D+0x48], gap [D+0x44], indent [D+0x34]) are scaled ONCE, at their one writer (Popup_calculate_dimensions; port
thunk_lbsrc_scale on its BasePop_calc call @0x404E93), so every ListBox_calculate_dimensions pass reads the same
values; listbox_calc_entry_sources -- the calc-entry detour (thunk_lbcalc_scale v5) keeps only the FileDlg arm.

The defect (user shot 1600x900 20261024-130004, Go To / SELECT DESTINATION, g = 18): thunk_lbcalc_scale v4 scaled at
the calc entry keyed on 0 < stride <= 0x16, which cannot tell native 19 from fl(19 g/16) = 20/21/22 at g 17/18/19.
Pass 1 (BasePop_calc: the box reserve [popup+0x30C4] and the button row) read stride 21 -> 249 px; pass 2
(ListBox_attach: the list window) scaled again to 23 -> 273 px: the 12th row under the buttons.  Every later
re-layout in the modal loop (ListBox_update_changes, a re-attach) compounded once more.

The "before" image is the bake with the two fix-29 edits reverted in memory (the site rel32 -> thunk_scale_box_margin,
thunk_lbcalc_scale v4), checked to differ from the bake in exactly those bytes: the build fix 29 replaced
(c67c3cd1, fix 24, plus the new thunk unreachable in its cave).

Proof layers (all on the REAL bytes of a module-scoped bake):
  1. wiring + the before image's byte diff;
  2. UNIT (Unicorn on the two mapped images, both thunks at their real addresses, ms): thunk_lbsrc_scale == the law
     on every gate state; thunk_lbcalc_scale v5 == v4 whenever g_filedlg_active (the LOAD/SAVE list is unchanged)
     and pass-through otherwise; and the sources every calc pass reads -- new image: 0x404E93 thunk then N calc
     entries, before image: N calc entries -- are IDENTICAL at g <= 16 and g >= 20 (so, with layer 3's "nothing
     reads them between 0x404E93 and the first calc", the engine computes and draws exactly what the before image
     did there) and differ exactly at g 17..19;
  3. END TO END (popup_listbox_emu.py on image_emu.py): the real builders in the engine's own call order; every
     calc pass reads the law, every list window h == [popup+0x30C4], list bottom <= the button row:
       GOTO g 17 LIFECYCLE -- the modal's own re-layouts (full redraw, ListBox_update_changes, a re-attach), exec_3
         run to its end, then the Sort branch's second show on the SAME popup (+ its re-layouts): the passes that
         compound under a calc-entry scale (the before image grows 249 -> 273 there);
       GOTO g 18 -- the 1600x900 shot, on both images: before = 249 reserve / 273 list, after = 249 / 249, same box
         and buttons;
       EDITORUNIT with 20 rows (more than the 12 visible: the scrollbar case) at g 17, 18 and 19 in one item;
       GOTO at g 16 (native) and 40 (4K); with the two items above GOTO spans 16 / 17 / 18 / 40.

COST (~40 s serial standalone, ~63 s under full-suite load; 8 tests, 8 image runs): each run boots the image
(~1 s, the PE parse cached per process by image_emu), loads the interface art (~1 s) and builds + draws its
popup(s) (~1 s at g 16, ~3 s at g 18, ~9 s at g 40, ~9 s for the lifecycle item's two shows and four re-layouts).  There is no cheaper way to read what
the engine lays out; every g the end-to-end items do not visit (and the equality to the before image at g 16 and
g >= 20) is proved at the unit layer in ~1 s instead of by drawing both images.  The heaviest items are the
three EDITORUNIT runs (the defect band through a second builder, ~5 s each) and the 4K run (the user's main
resolution, ~11 s); the module splits cleanly across xdist (independent items, one bake per worker).
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, UC_PROT_ALL, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

SITE = 0x404E93
#: thunk_lbcalc_scale v4 (c67c3cd1 and before) -- the before image's calc-entry detour
V4_LBCALC = ("83 3D {abs32:g_popup_active} 00 75 09 83 3D {abs32:g_filedlg_active} 00 74 42 A1 {abs32:g_popup_scale_num}"
             " 83 F8 10 7E 38 51 52 8B 11 8B 52 08 01 CA 8B 4A 48 85 C9 7E 26 83 F9 16 7F 21 0F AF C8 C1 F9 04 89 4A"
             " 48 8B 4A 44 0F AF C8 C1 F9 04 89 4A 44 8B 4A 34 0F AF C8 C1 F9 04 89 4A 34 5A 59 53 56 89 CE 31 DB 68"
             " E6 A1 60 00 C3")
LAW = (SL.POPUP_LB_STRIDE_NATIVE, SL.POPUP_LB_GAP_NATIVE, SL.POPUP_LB_INDENT_NATIVE)


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


class Image:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        pe = pefile.PE(data=bytes(data), fast_load=True)
        self.ib = pe.OPTIONAL_HEADER.ImageBase
        self.secs = [(self.ib + s.VirtualAddress, s.PointerToRawData, s.SizeOfRawData) for s in pe.sections]

    def off(self, va):
        for v, raw, size in self.secs:
            if v <= va < v + size:
                return raw + va - v
        raise KeyError(hex(va))

    def rd(self, va, n):
        o = self.off(va)
        return bytes(self.data[o:o + n])

    def wr(self, va, b):
        o = self.off(va)
        self.data[o:o + len(b)] = b


@pytest.fixture(scope="module")
def images(tmp_path_factory, symtab, baked_exe):
    """{'after': the bake of patches.yaml (conftest's shared `baked_exe`), 'before': the same bake with fix 29 reverted
    in memory}."""
    d = tmp_path_factory.mktemp("lbsrc_once")
    dst = Path(baked_exe)
    baked = Image(dst.read_bytes())
    before = Image(bytes(baked.data))
    before.wr(SITE + 1, struct.pack("<i", symtab["thunk_scale_box_margin"] - (SITE + 5)))
    lbcalc = symtab["thunk_lbcalc_scale"]
    before.wr(lbcalc, ap.ByteTemplate(V4_LBCALC).resolve(lbcalc, symtab))
    (d / "before.exe").write_bytes(before.data)
    return {"after": str(dst), "before": str(d / "before.exe"), "baked_img": baked, "before_img": before}


def _run(exe, g, label="GOTO", **kw):
    import popup_listbox_emu as P
    return P.Run(exe, g, label, **kw)


# ------------------------------------------------------------------------------------------------ 1. wiring
def test_wiring(images, symtab):
    baked = images["baked_img"]
    site = baked.rd(SITE, 5)
    assert site[0] == 0xE8 and SITE + 5 + struct.unpack("<i", site[1:])[0] == symtab["thunk_lbsrc_scale"]
    code = baked.rd(symtab["thunk_lbcalc_scale"], 0x60)
    assert struct.pack("<I", symtab["g_popup_active"]) not in code            # the popup arm is gone
    assert struct.pack("<I", symtab["g_filedlg_active"]) in code              # the FileDlg arm stays


def test_before_image_is_the_replaced_build(images, symtab):
    """The before image differs from the bake in exactly the site rel32 and thunk_lbcalc_scale's slot (the new
    thunk stays in the cave, unreachable)."""
    a = np.frombuffer(bytes(images["baked_img"].data), np.uint8)
    b = np.frombuffer(bytes(images["before_img"].data), np.uint8)
    diff = np.nonzero(a != b)[0].tolist()
    img = images["baked_img"]
    lb = symtab["thunk_lbcalc_scale"]
    allowed = set(range(img.off(SITE + 1), img.off(SITE + 5))) | set(range(img.off(lb), img.off(lb) + 0x60))
    assert diff and set(diff) <= allowed


# ------------------------------------------------------------------------------------------------ 2. unit
SCRATCH = 0x30000000
POP = SCRATCH + 0x10000
STK = SCRATCH + 0x80000
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX, UC_X86_REG_EDI, UC_X86_REG_EBP)


class Mapped:
    """One image mapped flat (no boot): the thunks and the calc entry run at their real addresses."""

    def __init__(self, path, symtab):
        import image_emu
        ib, img, size, _imports = image_emu._image(path)
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(ib, size, UC_PROT_ALL)
        uc.mem_write(ib, img)
        uc.mem_map(SCRATCH, 0x100000)
        self.st = symtab
        vbt = SCRATCH + 0x100
        uc.mem_write(vbt + 8, struct.pack("<I", 0xBA0))
        uc.mem_write(POP + 0x21D0, struct.pack("<I", vbt))
        self.D = POP + 0x21D0 + 0xBA0

    def w(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def src(self):
        return tuple(struct.unpack("<i", self.uc.mem_read(self.D + o, 4))[0] for o in (0x48, 0x44, 0x34))

    def setup(self, g, gpa, gfd, typ, s):
        self.w(self.st["g_popup_scale_num"], g)
        self.w(self.st["g_popup_active"], gpa)
        self.w(self.st["g_filedlg_active"], gfd)
        self.w(POP + 0x2350, typ)
        for o, v in zip((0x48, 0x44, 0x34), s):
            self.w(self.D + o, v)

    def _go(self, start, stop, ecx, ret, check=REGS):
        uc = self.uc
        self.w(STK, ret)
        vals = (0x11111111, 0x22222222, 0x44444444, 0x66666666, 0x77777777)
        for r, v in zip(REGS, vals):
            uc.reg_write(r, v)
        uc.reg_write(UC_X86_REG_ESP, STK)
        uc.reg_write(UC_X86_REG_ESI, POP)
        uc.reg_write(UC_X86_REG_ECX, ecx)
        uc.emu_start(start, stop, count=500)
        return all(uc.reg_read(r) == v for r, v in zip(REGS, vals) if r in check)

    def site(self):
        """What the image's E8 @0x404E93 does before thunk_scale_box_margin: run its target up to there."""
        tgt = SITE + 5 + struct.unpack("<i", self.uc.mem_read(SITE + 1, 4))[0]
        if tgt == self.st["thunk_scale_box_margin"]:
            return True
        ok = self._go(tgt, self.st["thunk_scale_box_margin"], POP, SITE + 5)
        return ok and struct.unpack("<I", self.uc.mem_read(STK, 4))[0] == SITE + 5 and \
            self.uc.reg_read(UC_X86_REG_ESP) == STK and self.uc.reg_read(UC_X86_REG_ECX) == POP

    def calc(self):
        """The calc entry (detour + displaced prologue) up to the resume 0x60A1E6, ecx = the ListBox (eax/edx are dead
        at the entry, the prologue itself zeroes ebx and loads esi)."""
        ok = self._go(0x60A1E0, 0x60A1E6, POP + 0x21D0, 0xDEAD0000, check=(UC_X86_REG_EDI, UC_X86_REG_EBP))
        return ok and self.uc.reg_read(UC_X86_REG_ECX) == POP + 0x21D0 and self.uc.reg_read(UC_X86_REG_ESP) == STK - 8


@pytest.fixture(scope="module")
def mapped(images, symtab):
    return Mapped(images["after"], symtab), Mapped(images["before"], symtab)


def test_unit_thunks_and_pass_equivalence(mapped):
    new, old = mapped
    fl = SL.popup_scale_floor
    n = 0
    for g in (0, 12, 15, 16) + tuple(range(17, 41)) + (48, 63):
        for gpa in (0, 1, 2):
            for typ in (0, 1, 2, 8, 16, 0x22):
                for s in ((0x13, 3, 3), (0x13, 3, 27), (-1, 3, 3), (0, 3, 3), (0x16, 6, 25),
                          (fl(0x13, g), fl(3, g), fl(3, g)), (fl(0x16, g), fl(6, g), fl(25, g))):
                    # thunk_lbsrc_scale == the law (registers, return and stack preserved)
                    new.setup(g, gpa, 0, typ, s)
                    assert new.site()
                    assert new.src() == SL.popup_listbox_sources(*s, g, popup_type=typ, popup_active=gpa != 0)
                    # the calc entry: v5 == v4 under the FileDlg gate, pass-through otherwise
                    for gfd in (0, 1):
                        new.setup(g, gpa, gfd, typ, s)
                        old.setup(g, gpa, gfd, typ, s)
                        assert new.calc() and old.calc()
                        want = SL.listbox_calc_entry_sources(*s, g, filedlg_active=gfd == 1)
                        assert new.src() == want
                        if gfd:
                            assert old.src() == want
                    n += 1
    assert n == 3780            # 36 g x 3 popup states x 6 types x 7 source states (x 2 FileDlg states at the calc)
    # every calc pass of the popup's own list (the writer's native values, inside exec_3, type 2)
    for g in (0, 12, 16) + tuple(range(17, 41)):
        seen = {}
        for name, im in (("new", new), ("old", old)):
            im.setup(g, 1, 0, 2, LAW)
            assert im.site()
            passes = []
            for _ in range(4):                     # BasePop_calc, ListBox_attach, update_changes, re-attach
                assert im.calc()
                passes.append(im.src())
            seen[name] = passes
        law = SL.popup_listbox_sources(*LAW, g)
        assert seen["new"] == [law] * 4
        if 17 <= g <= 19:
            assert seen["old"][0] == law != seen["old"][1]   # v4: pass 2 (ListBox_attach) scaled again
        else:
            assert seen["old"] == seen["new"]      # g <= 16 / >= 20: the calc reads exactly what it read before


# ------------------------------------------------------------------------------------------------ 3. end to end
def _assert_law(r, g, symtab):
    law = SL.popup_listbox_sources(*LAW, g)
    assert len(r.calcs) >= 2, "pass 1 (BasePop_calc) and pass 2 (ListBox_attach) must both run"
    assert {c[2:] for c in r.calcs} == {law}, f"calc passes read {[c[:1] + c[2:] for c in r.calcs]}, law {law}"
    assert r.final_src == law
    lbsrc = symtab["thunk_lbsrc_scale"]
    thunk = range(lbsrc, lbsrc + 0x6B)             # thunk_lbsrc_scale itself (107 B) reads them, nothing else
    assert [x for x in r.early_reads if int(x[2], 16) not in thunk] == [], "a reader between 0x404E93 and the calc"
    assert r.lists, "no list window"
    for lw in r.lists:
        btn_y = min(b["y"] for b in r.btns if b["phase"] == lw["phase"].split(":")[0])
        assert lw["h"] == lw["reserve"], lw
        assert lw["y"] + lw["h"] <= btn_y, (lw, btn_y)


def test_goto_lifecycle_g17(images, symtab):
    """Modal re-layouts (full redraw, ListBox_update_changes, re-attach), exec_3 to its end, then the Sort
    branch's second show on the same popup: every pass reads s(19)/s(3)/s(3), the list stays the reserve."""
    r = _run(images["after"], 17, lifecycle=True)
    assert r.g == 17 and r.shows == ["show1", "show2"]
    _assert_law(r, 17, symtab)
    phases = {c[0] for c in r.calcs}
    assert {"show1", "show1:modal", "show2", "show2:modal"} <= phases
    assert sum(c[1] == 0x60C9F9 for c in r.calcs) == 2            # ListBox_update_changes' own calc, per show
    assert len(r.lists) >= 4


def test_goto_1600x900_shot(images, symtab):
    """The harness sees the defect: on the replaced build the Go To list window is 273 px for a 249 px reserve,
    its bottom below the button row's top; fix 29: 249 / 249, box and buttons unmoved."""
    old = _run(images["before"], 18)
    new = _run(images["after"], 18)
    _assert_law(new, 18, symtab)
    lw = old.lists[-1]
    assert (lw["h"], old.reserve) == (273, 249)
    assert lw["y"] + lw["h"] > min(b["y"] for b in old.btns)
    assert new.lists[-1]["h"] == new.reserve == 249
    assert new.popwin == old.popwin and new.btns == old.btns


def test_editorunit_scrolling_list_g17_19(images, symtab):
    """More rows than the 12 visible (the list scrolls) through the editor's own builder, across the defect band."""
    for g in (17, 18, 19):
        r = _run(images["after"], g, "EDITORUNIT", nrows=20)
        assert r.g == g
        _assert_law(r, g, symtab)


@pytest.mark.parametrize("g", (16, 40))
def test_goto_list_window_is_the_box_reserve(images, symtab, g):
    r = _run(images["after"], g)
    assert r.g == g
    _assert_law(r, g, symtab)
