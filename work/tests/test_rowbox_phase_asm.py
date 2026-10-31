"""t_rowbox_ph (assemble_rowbox_phase.py): popup option-row bars on the popup's stripe grid.

Unicorn on the assembled bytes AND the patches.yaml bytes at the real cave VA.  thunk_rowbox_guard is a stub
that records g_rm_yph, ecx and its two stack args at entry, returns a marker in eax and `ret 8` -- the
wrapper must stage the law's phase for exactly that call, clear it after, keep the thiscall/RET 8 contract.
"""
import pathlib
import sys

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_rowbox_phase as AR  # noqa: E402
import scaling_laws as SL  # noqa: E402

VA = AR.PCAVE2 + AR.OFF
STACK, SP0 = 0x00300000, 0x00308000
WIN = 0x00500000                  # the Dialog's child GraphicWin; ecx = WIN + 0x444
RET_SITE = 0x00405BFB             # after the 5-byte call at the site
RECT, PARAMS, GUARD_EAX = 0x11223344, 0x55667788, 0x0BADF00D
REC = 0x00600000                  # stub record: yph, ecx, arg1, arg2


def _guard_stub() -> bytes:
    return AR.assemble(f"""
        mov  eax, dword ptr [{AR.G_RM_YPH:#x}]
        mov  dword ptr [{REC:#x}], eax
        mov  dword ptr [{REC + 4:#x}], ecx
        mov  eax, dword ptr [esp+4]
        mov  dword ptr [{REC + 8:#x}], eax
        mov  eax, dword ptr [esp+8]
        mov  dword ptr [{REC + 12:#x}], eax
        mov  eax, {GUARD_EAX:#x}
        ret  8
    """, AR.ROWBOX_GUARD)


def _yaml_bytes() -> bytes:
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    c = next(c for cave in caves for c in cave.get("contents", []) if c["id"] == "t_rowbox_ph")
    assert int(c["offset"]) == AR.OFF
    return ap.ByteTemplate(c["bytes"]).resolve(VA, symtab)


def run(code: bytes, g: int, top1: int, top2: int, yph0: int = 0):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AR.PCAVE2, 0x20000), (STACK, 0x10000), (WIN, 0x1000), (REC, 0x1000), (0x668000, 0x1000),
                       (RET_SITE & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(VA, code)
    uc.mem_write(AR.ROWBOX_GUARD, _guard_stub())
    uc.mem_write(AR.G, g.to_bytes(4, "little"))                       # conftest also writes g_stripe_period
    uc.mem_write(AR.G_STRIPE_PERIOD, SL.stripe_period(g).to_bytes(4, "little"))
    uc.mem_write(AR.G_RM_YPH, yph0.to_bytes(4, "little"))
    uc.mem_write(REC, b"\xEE" * 16)
    uc.mem_write(WIN + 0x140, (top1 & 0xFFFFFFFF).to_bytes(4, "little"))
    uc.mem_write(WIN + 0x150, (top2 & 0xFFFFFFFF).to_bytes(4, "little"))
    for addr, v in ((SP0, RET_SITE), (SP0 + 4, RECT), (SP0 + 8, PARAMS)):
        uc.mem_write(addr, v.to_bytes(4, "little"))
    regs = {UC_X86_REG_ESP: SP0, UC_X86_REG_ECX: WIN + 0x444, UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222,
            UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x4444, UC_X86_REG_EDX: 0x5555, UC_X86_REG_EAX: 0x6666}
    for r, v in regs.items():
        uc.reg_write(r, v)
    landed = []

    def hook(u, addr, size, _):
        if addr == RET_SITE:
            landed.append(addr)
            u.emu_stop()
    uc.hook_add(UC_HOOK_CODE, hook)
    uc.mem_write(RET_SITE, b"\xF4")
    uc.emu_start(VA, 0, count=10_000)
    assert landed == [RET_SITE]
    r32 = lambda a: int.from_bytes(uc.mem_read(a, 4), "little")  # noqa: E731
    rec = [r32(REC + 4 * i) for i in range(4)]
    return uc, rec, r32(AR.G_RM_YPH)


CODE = AR.build()


def test_yaml_bytes_are_the_assembler_output():
    assert _yaml_bytes() == CODE


@pytest.mark.parametrize("g", [17, 18, 20, 22, 25, 32, 40])
@pytest.mark.parametrize("top1, top2", [(225, 0), (0, 225), (410, 0), (255, 0), (59, 196), (0, 0), (4, 0), (-3, 0),
                                        (-1, -6), (7, 7)])
def test_stages_the_child_top_phase_around_the_guard(g, top1, top2):
    uc, rec, after = run(CODE, g, top1, top2, yph0=0)
    want, P = SL.option_row_stripe_phase(top1, top2, g), SL.stripe_period(g)
    assert 0 <= want < P
    # staged for the guard: a non-negative sum raw (fe_pair_remap v8 reduces row + cell by P itself, the
    # thunk_btn_stripes v13 contract), a negative one reduced here to 1..P; args and ecx intact
    assert rec[0] < 0x80000000 and rec[0] % P == want
    assert rec[0] == (top1 + top2 if top1 + top2 >= 0 else rec[0]) and (top1 + top2 >= 0 or 1 <= rec[0] <= P)
    assert rec[1:] == [WIN + 0x444, RECT, PARAMS]
    assert after == 0                                          # cleared for every other fe caller
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 12             # RET 8 from the call at the site
    assert uc.reg_read(UC_X86_REG_EAX) == GUARD_EAX
    for r, v in ((UC_X86_REG_ECX, WIN + 0x444), (UC_X86_REG_EBX, 0x1111), (UC_X86_REG_ESI, 0x2222),
                 (UC_X86_REG_EDI, 0x3333), (UC_X86_REG_EBP, 0x4444)):
        assert uc.reg_read(r) == v


def test_g_le_16_is_the_plain_guard_call():
    uc, rec, after = run(CODE, 16, 225, 0, yph0=0)
    assert rec == [0, WIN + 0x444, RECT, PARAMS] and after == 0
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 12 and uc.reg_read(UC_X86_REG_EAX) == GUARD_EAX


def test_protocol_director_measured_phases():
    """Measured child tops (1920x1080 shot 200650: 225; 4K shot 125149: 410) -> the bars move by 1 / 2 rows."""
    assert SL.option_row_stripe_phase(225, 0, 22) == 1
    assert SL.option_row_stripe_phase(410, 0, 40) == 2


def test_site_points_at_the_wrapper():
    text = (pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml").read_text(encoding="utf-8")
    i = text.index("  - id: FUN_00405b20.option_frame")
    block = text[i:text.index("pattern:", i)]
    # 2026-10-24 W1A F35: the site calls t_rowbox_trim (law option_row_frame_site_rect), which tail-jumps this wrapper
    # (tests/test_type1_gaps_asm_parity.py::test_wiring_sites_and_tails checks its `push t_rowbox_ph; ret`)
    # 2026-10-25 W7R v2: the site calls t_rowbox_solid, which CALLs t_rowbox_trim first (then t_ring_solid: the hover ring
    # solid; tests/test_thin_rings_asm_parity.py::test_rowbox_solid_flow)
    # 2026-10-27 W9B: the site calls t1c_bar, which CALLs (a marked type-1 bar) or tail-jumps t_rowbox_solid
    # (tests/test_type1_bar_asm_parity.py::test_bar_is_the_law)
    assert '"E8 {rel32:t1c_bar}"' in block
