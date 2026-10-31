"""t_pp_selbox (assemble_pp_selbox.py): the production picker's selected-cell outline inside the frame stroke.

Unicorn on the patches.yaml bytes of t_pp_selbox AND the real thunk_bw_box2ring, with Buffer_box_2 stubbed to
log every (rect, colours) it is asked to draw.  The drawn rings must be exactly
scaling_laws.prodpicker_sel_outline_rects; K<=1 must reach Buffer_box_2 with the caller's stack untouched.
"""
import pathlib
import sys

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_pp_selbox as AP  # noqa: E402
import scaling_laws as SL  # noqa: E402

STACK, SP0 = 0x00300000, 0x00308000
RET_SITE = 0x00492F79
BUF = 0x00500444
CALLER_RECT = 0x00400000
LOG = 0x00600000                   # box_2 stub log: count, then (l,t,r,b,ch,cv) per call


def _yaml():
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    contents = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    out = {}
    for name in ("t_pp_selbox", "thunk_bw_box2ring"):
        c = contents[name]
        va = AP.PCAVE2 + int(c["offset"])
        out[name] = (va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab))
    return out


YAML = _yaml()


def _box2_stub() -> bytes:
    # log [rect] fields + colours; ret 0xC (thiscall)
    return AP.assemble(f"""
        push esi
        push edi
        mov  esi, dword ptr [esp+0xC]
        mov  edi, dword ptr [{LOG:#x}]
        imul edi, edi, 24
        add  edi, {LOG + 4:#x}
        mov  eax, dword ptr [esi]
        mov  dword ptr [edi], eax
        mov  eax, dword ptr [esi+4]
        mov  dword ptr [edi+4], eax
        mov  eax, dword ptr [esi+8]
        mov  dword ptr [edi+8], eax
        mov  eax, dword ptr [esi+0xC]
        mov  dword ptr [edi+0xC], eax
        mov  eax, dword ptr [esp+0x10]
        mov  dword ptr [edi+0x10], eax
        mov  eax, dword ptr [esp+0x14]
        mov  dword ptr [edi+0x14], eax
        inc  dword ptr [{LOG:#x}]
        pop  edi
        pop  esi
        ret  0xC
    """, AP.BOX_2)


def run(g: int, rect):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AP.PCAVE2, 0x31000), (STACK, 0x10000), (0x00400000, 0x1000), (0x00500000, 0x1000),
                       (LOG, 0x1000), (0x668000, 0x1000), (AP.BOX_2 & ~0xFFF, 0x1000), (RET_SITE & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    for va, code in YAML.values():
        uc.mem_write(va, code)
    uc.mem_write(AP.BOX_2, _box2_stub())
    uc.mem_write(AP.G, g.to_bytes(4, "little"))
    uc.mem_write(CALLER_RECT, b"".join(v.to_bytes(4, "little", signed=True) for v in rect))
    for addr, v in ((SP0, RET_SITE), (SP0 + 4, CALLER_RECT), (SP0 + 8, 0xFF), (SP0 + 12, 0xFF)):
        uc.mem_write(addr, v.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, BUF)
    for r, v in ((UC_X86_REG_EBX, 0x1111), (UC_X86_REG_ESI, 0x2222), (UC_X86_REG_EDI, 0x3333)):
        uc.reg_write(r, v)
    landed = []

    def hook(u, addr, size, _):
        if addr == RET_SITE:
            landed.append(addr)
            u.emu_stop()
    uc.hook_add(UC_HOOK_CODE, hook)
    uc.mem_write(RET_SITE, b"\xF4")
    uc.emu_start(YAML["t_pp_selbox"][0], 0, count=100_000)
    assert landed == [RET_SITE]
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 16                     # RET 0xC from the call at the site
    for r, v in ((UC_X86_REG_EBX, 0x1111), (UC_X86_REG_ESI, 0x2222), (UC_X86_REG_EDI, 0x3333)):
        assert uc.reg_read(r) == v
    n = int.from_bytes(uc.mem_read(LOG, 4), "little")
    calls = []
    for i in range(n):
        f = [int.from_bytes(uc.mem_read(LOG + 4 + 24 * i + 4 * k, 4), "little", signed=True) for k in range(6)]
        calls.append(tuple(f))
    caller = tuple(int.from_bytes(uc.mem_read(CALLER_RECT + 4 * k, 4), "little", signed=True) for k in range(4))
    return calls, caller


def test_yaml_bytes_are_the_assembler_output():
    assert YAML["t_pp_selbox"][1] == AP.build()


@pytest.mark.parametrize("g", list(range(16, 49)))
@pytest.mark.parametrize("rect", [(43, 7, 245, 93), (887, 7, 1089, 93), (1, 1, 60, 40), (100, 300, 180, 330)])
def test_rings_are_the_law(g, rect):
    calls, caller = run(g, rect)
    assert caller == rect                                               # the caller's rect is never written
    assert [c[:4] for c in calls] == SL.prodpicker_sel_outline_rects(*rect, g)
    assert all(c[4:] == (0xFF, 0xFF) for c in calls)


@pytest.mark.parametrize("g", [25, 32, 40])
@pytest.mark.parametrize("clip_r", [False, True])
def test_rings_butt_every_frame_stroke(g, clip_r):
    """The cell frame (band-map footprint INCLUSIVE of R0/B0) has strokes L0..L0+K-1, T0..T0+K-1,
    R0-K+1..R0, B0-K+1..B0 (with the engine clip on the cell rect the R0/B0 line may be cut: then R0-K+1..R0-1).
    Buffer_box_2 draws half-open (last column r-1, last row b-1).  The K rings must cover exactly the K columns /
    rows just inside each stroke: no overlap with a stroke (or its corner notch), no seam -- on all four sides."""
    k = SL.stroke_width(g)
    L0, T0, R0, B0 = 42, 6, 250, 96
    rings = SL.prodpicker_sel_outline_rects(L0 + 1, T0 + 1, R0 - 1, B0 - 1, g)
    assert len(rings) == k
    left = sorted(r[0] for r in rings)
    top = sorted(r[1] for r in rings)
    right = sorted(r[2] - 1 for r in rings)
    bottom = sorted(r[3] - 1 for r in rings)
    assert left == list(range(L0 + k, L0 + 2 * k)) and top == list(range(T0 + k, T0 + 2 * k))
    r_stroke_lo = R0 - k + 1                          # first column of the right stroke, clipped or not
    b_stroke_lo = B0 - k + 1
    assert right == list(range(r_stroke_lo - k, r_stroke_lo))
    assert bottom == list(range(b_stroke_lo - k, b_stroke_lo))
    assert clip_r in (False, True)                    # the clip only trims the stroke's outer line, never the butt


def test_k1_is_the_vanilla_call():
    for g in (16, 18, 22, 24):
        assert SL.stroke_width(g) <= 1
        calls, _ = run(g, (43, 7, 245, 93))
        assert [c[:4] for c in calls] == [(43, 7, 245, 93)]


def test_site_points_at_the_adapter():
    text = (pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml").read_text(encoding="utf-8")
    i = text.index("  - id: ProdPicker_draw_cell.selbox")
    block = text[i:text.index("pattern:", i)]
    assert "virtual_addr: 0x00492F74" in block and '"E8 {rel32:t_pp_selbox}"' in block
    assert '"E8 8A 02 15 00"' in block
