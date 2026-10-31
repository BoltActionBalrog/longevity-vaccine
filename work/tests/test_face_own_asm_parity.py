"""W9A asm parity (assemble_face_own.py): t_face_own -- the own-top FlatButton faces (the user's decision 2026-10-27) --
Unicorn on the patches.yaml bytes at its real cave VA, against scaling_laws.py: own_top_face / own_face_stripe_phase /
flatbutton_draw_state.

t_face_own: every g's period cell value (P 2 / 4 / 6), face heights 0..90, every draw-state input class, the gate's
members and near misses (PrefWin's children; the SE society column's first / last row and both neighbours; a PrefWin
slider's arrow; parentless) -- CF and edx as the contract says, every other register preserved, the stack balanced,
nothing written.  The callers' wiring (thunk_btn_stripes v14, thunk_se_rowdraw_ph v2) is checked in
test_scenedit_asm_parity.py / test_rail_asm_parity.py / test_se_asm_parity.py; the yaml bytes == the assembler here.
Pure Unicorn on one small thunk: no bake, no boot (~3 s serial).
"""
from __future__ import annotations

import pathlib
import struct
import sys
from functools import lru_cache

import pytest

pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
from unicorn import UC_ARCH_X86, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
                               UC_X86_REG_ESI, UC_X86_REG_ESP)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_patches as ap  # noqa: E402
import assemble_face_own as FO  # noqa: E402
import scaling_laws as SL  # noqa: E402

YAML = ROOT / "patches" / "patches.yaml"
STACK, SP0 = 0x00300000, 0x00308000
RET = 0x00400000                        # a hlt the thunks return to
PERIOD_G = {2: 20, 4: 25, 6: 48}        # a g whose stripe period is P (the thunk reads only the cell)
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


@lru_cache(maxsize=1)
def _yaml():
    _sites, _g, caves, syms = ap.load_patches(YAML)
    st = dict(ap.build_symbol_table(syms, caves))
    ents = {c["id"]: c for cave in caves for c in cave.get("contents") or []}
    return st, ents


def _bytes(name: str) -> bytes:
    st, ents = _yaml()
    return bytes(ap.ByteTemplate(ents[name]["bytes"]).resolve(st[name], st))


def test_yaml_is_the_assembler():
    st, _e = _yaml()
    for name, (va, code, _t) in FO.build().items():
        assert st[name] == va and _bytes(name) == code, name
    assert list(FO.build()) == ["t_face_own"] and "t_pref_rowy" not in st, "the toggle-pitch thunk was dropped (2026-10-27)"
    assert FO.T_FACE_OWN + len(FO.build()["t_face_own"][1]) <= FO.PCAVE2 + FO.REGION_END


class Rig:
    """One Unicorn: the engine pages the thunk touches (the button objects, the period cell 0x66879C), the cave page,
    a stack."""

    def __init__(self):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((0x00400000, 0x1000), (0x00668000, 0x1000), (0x00686000, 0x1000), (0x00800000, 0x100000),
                           (FO.PCAVE2 + 0x3E000, 0x1000), (STACK, 0x10000), (0x00C00000, 0x10000)):
            uc.mem_map(base, size)
        uc.mem_write(RET, b"\xF4")
        st, _e = _yaml()
        uc.mem_write(st["t_face_own"], _bytes("t_face_own"))
        self.uc, self.writes = uc, []
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, size, v, ud: self.writes.append(a))

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def run(self, va, regs, stack=()):
        uc = self.uc
        esp = SP0 - 4 * (len(stack) + 1)
        uc.mem_write(esp, struct.pack("<I", RET) + b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in stack))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_EFLAGS, 0x202)
        for r, v in regs.items():
            uc.reg_write(r, v & 0xFFFFFFFF)
        self.writes.clear()
        uc.emu_start(va, 0, count=200_000)
        return esp


BTN_PREF = 0x00C00100                   # a heap-like PrefWin child (the DLL's widgets) / any other button
OWN_CASES = [  # (button, parent, own)
    (BTN_PREF, SL.OWN_FACE_PARENT, True),
    (0x0085BBB4, SL.OWN_FACE_PARENT, True),                                     # PrefWin_btn_map (a stock tab)
    (0x0086C6E0, SL.OWN_FACE_PARENT, True),                                     # PrefWin_btn_main_off
    (0x00862064 + 0xAAC, 0x00862064, False),                                    # a PrefWin slider's arrow: parent = slider
    (BTN_PREF, SL.OWN_FACE_PARENT + 0xB4C, False), (BTN_PREF, 0, False),
    (SL.SE_OWN_FACE_LO, 0x008A6270, True), (SL.SE_OWN_FACE_HI - 0xB4C, 0x008A6270, True),
    (SL.SE_OWN_FACE_LO + 4 * 0xB4C, 0, True),
    (SL.SE_OWN_FACE_LO - 0xB4C, 0x008A6270, False), (SL.SE_OWN_FACE_HI, 0x008A6270, False),   # the OK row either side
    (0x008AC290, 0x008A6270, False),                                            # an SE option button
]
STATES = [(-1, 0, 0, 0), (0, 1, 1, 1), (1, 0, 0, 0), (2, 0, 0, 0), (-1, 1, 0, 0), (-1, 0, 1, 0), (-1, 0, 0, 1),
          (-1, 1, 1, 0), (3, 1, 0, 0), (3, 0, 0, 0), (0x7FFFFFFF, 0, 1, 0), (-5, 1, 0, 0)]


@pytest.mark.parametrize("p", sorted(PERIOD_G))
@pytest.mark.parametrize("btn,parent,own", OWN_CASES)
def test_face_own_is_the_law(p, btn, parent, own):
    g = PERIOD_G[p]
    rig = Rig()
    rig.w32(0x0066879C, p)
    for h in range(0, 91):
        for state in STATES:
            rig.w32(btn + 0xC4, parent)
            rig.w32(btn + 0x4C8, -h)
            for off, v in zip((0xAB8, 0xA74, 0xA18, 0xA9C), state):
                rig.w32(btn + off, v)
            regs = {UC_X86_REG_EAX: 0x11110001, UC_X86_REG_EBX: 0x22220002, UC_X86_REG_ECX: 0x33330003,
                    UC_X86_REG_EDX: btn, UC_X86_REG_ESI: 0x44440004, UC_X86_REG_EDI: 0x55550005,
                    UC_X86_REG_EBP: 0x66660006}
            esp = rig.run(FO.T_FACE_OWN, regs)
            uc = rig.uc
            assert uc.reg_read(UC_X86_REG_EIP) == RET + 1 and uc.reg_read(UC_X86_REG_ESP) == esp + 4
            assert [uc.reg_read(r) for r in REGS] == [regs[r] & 0xFFFFFFFF for r in REGS], "registers preserved"
            assert all(STACK <= a < SP0 for a in rig.writes), "only its own stack written"
            cf = uc.reg_read(UC_X86_REG_EFLAGS) & 1
            assert cf == int(own) == int(SL.own_top_face(btn, parent)), (hex(btn), hex(parent))
            st = SL.flatbutton_draw_state(*state)
            if own:
                want = SL.own_face_stripe_phase(h, g, st == 2)
                assert uc.reg_read(UC_X86_REG_EDX) == want == SL.btn_face_phase(btn, parent, 0, 0, h, g, st), \
                    (p, h, state)
                assert 0 <= want < p
            else:
                assert uc.reg_read(UC_X86_REG_EDX) == btn, "edx kept"
