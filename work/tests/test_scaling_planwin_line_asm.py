"""planwin_line_scale (assemble_planwin_line.py): the Go To map panel's dashed route line at vanilla x g/16.

Unicorn on the patches.yaml bytes of t_pw_line with Buffer_line 0x5E09D0 stubbed to log its 9 args (RET 0x24);
the logged calls must be exactly scaling_laws.planwin_line_calls (dashes scaled at every g > 16, copies only at
K > 1); g <= 16 reaches Buffer_line once with
the caller's stack untouched.
"""
import pathlib
import sys

import pytest
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_planwin_line as AL  # noqa: E402
import scaling_laws as SL  # noqa: E402

SP0, RET, BUF, LOG = 0x00308000, 0x0048B375, 0x00500444, 0x00600000


def _yaml() -> bytes:
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    c = next(c for cave in caves for c in cave.get("contents", []) if c["id"] == "t_pw_line")
    return ap.ByteTemplate(c["bytes"]).resolve(AL.PCAVE2 + int(c["offset"]), symtab)


YAML = _yaml()


def _stub() -> bytes:
    src = f"""
        push esi
        push edi
        mov  edi, dword ptr [{LOG:#x}]
        imul edi, edi, 40
        add  edi, {LOG + 4:#x}
        mov  dword ptr [edi + 36], ecx
        lea  esi, [esp + 12]
        mov  ecx, 9
    cp:
        mov  eax, dword ptr [esi]
        mov  dword ptr [edi], eax
        add  esi, 4
        add  edi, 4
        dec  ecx
        jnz  cp
        inc  dword ptr [{LOG:#x}]
        pop  edi
        pop  esi
        ret  0x24
    """
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, AL.BUFFER_LINE)
    return bytes(enc)


def run(g, args):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AL.PCAVE2 + 0xF000, 0x1000), (0x00300000, 0x10000), (0x00500000, 0x1000), (LOG, 0x1000),
                       (0x668000, 0x1000), (AL.BUFFER_LINE & ~0xFFF, 0x1000), (RET & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(AL.PCAVE2 + AL.OFF, YAML)
    uc.mem_write(AL.BUFFER_LINE, _stub())
    uc.mem_write(AL.G, g.to_bytes(4, "little"))
    uc.mem_write(RET, b"\xF4")
    for i, v in enumerate([RET] + list(args)):
        uc.mem_write(SP0 + 4 * i, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    regs = {UC_X86_REG_ESP: SP0, UC_X86_REG_ECX: BUF, UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222,
            UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x4444}
    for r, v in regs.items():
        uc.reg_write(r, v)
    hit = []
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s, _: (hit.append(a), u.emu_stop()) if a == RET else None)
    uc.emu_start(AL.PCAVE2 + AL.OFF, 0, count=100_000)
    assert hit == [RET] and uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x24
    for r, v in list(regs.items())[2:]:
        assert uc.reg_read(r) == v
    n = int.from_bytes(uc.mem_read(LOG, 4), "little")
    calls = []
    for i in range(n):
        f = [int.from_bytes(uc.mem_read(LOG + 4 + 40 * i + 4 * k, 4), "little", signed=True) for k in range(10)]
        assert f[9] == BUF and f[4] == 0 and f[5] == 65                    # same Buffer, a5 and colour every copy
        calls.append((f[0], f[1], f[2], f[3], f[6], f[7], f[8]))
    return calls


def test_yaml_bytes_are_the_assembler_output():
    assert YAML == AL.build()


@pytest.mark.parametrize("g", [16, 17, 22, 24, 25, 32, 40])
@pytest.mark.parametrize("pts", [(9, 29, 300, 60), (100, 20, 120, 250), (50, 50, 10, 10), (200, 100, 40, 260),
                                 (30, 30, 30, 30)])
@pytest.mark.parametrize("phase", [0, 3, 7, -1, -13, -1000003])
def test_calls_are_the_law(g, pts, phase):
    x1, y1, x2, y2 = pts
    calls = run(g, [x1, y1, x2, y2, 0, 65, 4, 4, phase])
    assert calls == SL.planwin_line_calls(x1, y1, x2, y2, 4, 4, phase, g)


def test_4k_route_line_is_two_px_with_scaled_dashes():
    calls = run(40, [9, 29, 300, 60, 0, 65, 4, 4, 2])
    assert [c[1] for c in calls] == [29, 30] and all(c[4:] == (10, 10, 5) for c in calls)


def test_1080_dashes_scale_with_one_copy():
    """Audit 2026-10-12: at g=22 (K=1) the dashes must still be vanilla x g/16 = 5/5, in one copy."""
    calls = run(22, [9, 29, 300, 60, 0, 65, 4, 4, 2])
    assert calls == [(9, 29, 300, 60, 5, 5, 3)]
