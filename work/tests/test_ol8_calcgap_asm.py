"""t_ol8_calcgap (assemble_ol8_calcgap.py): the type-8 OptionList row window reserves the scaled column gap.

Unicorn runs the ORIGINAL calc tail 0x610C25..0x610C41 with the 5-byte site replaced by `call t_ol8_calcgap`
(the yaml bytes at the real cave VA) and compares [D+0x5c] with scaling_laws.optionlist8_list_width.
"""
import pathlib
import sys

import pytest
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_ESP

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_ol8_calcgap as AG  # noqa: E402
import scaling_laws as SL  # noqa: E402

VA = AG.PCAVE2 + AG.OFF
OBJ = 0x00500000                   # esi = the OptionList object; [esi] -> vtbl-ish ptr whose +8 = the D offset
D_OFF = 0x100
TAIL = 0x00610C25
END = 0x00610C3F                   # the pop edi after the max


def _yaml_bytes() -> bytes:
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    c = next(c for cave in caves for c in cave.get("contents", []) if c["id"] == "t_ol8_calcgap")
    return ap.ByteTemplate(c["bytes"]).resolve(VA, symtab)


def _tail() -> bytes:
    """0x610C25..0x610C3E as in the exe, with the site cut to `call t_ol8_calcgap`."""
    src = f"""
        mov eax, dword ptr [ecx + esi + 0x64]
        add ecx, esi
        call {VA:#x}
        imul eax, dword ptr [ecx + 0x54]
        sub eax, edx
        mov edx, dword ptr [ecx + 0x2c]
        cmp edx, eax
        jle done
        mov eax, edx
    done:
        mov dword ptr [ecx + 0x5c], eax
        hlt
    """
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, TAIL)
    return bytes(enc)


YAML = _yaml_bytes()


def run(g, col_w, gap, cols, xs):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AG.PCAVE2 + 0x30000, 0x1000), (0x00300000, 0x10000), (OBJ, 0x1000), (0x668000, 0x1000),
                       (TAIL & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(VA, YAML)
    uc.mem_write(TAIL, _tail())
    uc.mem_write(AG.G, g.to_bytes(4, "little"))
    D = OBJ + D_OFF
    for off, v in ((0x64, col_w), (0x44, gap), (0x54, cols), (0x2c, xs), (0x5c, 0xEEEE)):
        uc.mem_write(D + off, v.to_bytes(4, "little", signed=True))
    uc.reg_write(UC_X86_REG_ESP, 0x00308000)
    uc.reg_write(UC_X86_REG_ESI, OBJ)
    uc.reg_write(UC_X86_REG_ECX, D_OFF)
    uc.emu_start(TAIL, 0, count=1000)
    assert uc.reg_read(UC_X86_REG_ECX) == D                       # the helper keeps ecx
    return int.from_bytes(uc.mem_read(D + 0x5c, 4), "little", signed=True)


def test_yaml_bytes_are_the_assembler_output():
    assert YAML == AG.build()


@pytest.mark.parametrize("g", [16, 17, 22, 25, 32, 40])
@pytest.mark.parametrize("col_w, gap, cols, xs", [(794, 3, 2, 600), (437, 3, 1, 600), (300, 3, 5, 600),
                                                   (200, 4, 3, 900), (650, 3, 3, 525)])
def test_list_width_is_the_law(g, col_w, gap, cols, xs):
    assert run(g, col_w, gap, cols, xs) == SL.optionlist8_list_width(col_w, gap, cols, xs, g)


def test_stack_picker_golden():
    """16 units, 2 columns at 4K: the window now reserves s(3)=7 between the columns (1595), was the native 3 (1591)."""
    assert run(40, 794, 3, 2, 600) == 1595
    assert run(16, 794, 3, 2, 600) == 1591                        # g<=16: the engine's own native gap
