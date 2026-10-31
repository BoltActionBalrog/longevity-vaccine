"""assemble_rw_rowcum.py: F4 BASE STATUS rows at cum(k) = s(42k), F3 ENERGY ListBox stride s(18).

Unicorn on the assembler's bytes against scaling_laws.bases_row_advance / rw_energy_row_stride, the PRACX base's
original site bytes (g <= 16 = the engine's own result, run side by side), and the F4 layout: the visible-row count is
vanilla's at every g and the last box stays inside the clip.
"""
import pathlib
import re
import sys

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_rw_rowcum as AR  # noqa: E402
import scaling_laws as SL  # noqa: E402

BASES, ENERGY = AR.build()
EBP, ESI = 0x00300800, 0x00876478
GS = list(range(8, 41))


def _uc(g):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AR.PCAVE2 + 0x5000, 0x1000), (AR.PCAVE2 + 0x30000, 0x1000), (0x00300000, 0x2000), (0x668000, 0x1000),
                       (ESI & ~0xFFF, 0x10000), (0x49C000, 0x2000)):
        uc.mem_map(base, size)
    uc.mem_write(AR.G, g.to_bytes(4, "little"))
    return uc


def _run(uc, start, stop, regs):
    for r, v in regs.items():
        uc.reg_write(r, v & 0xFFFFFFFF)
    hit = []
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s, _: (hit.append(a), u.emu_stop()) if a == stop else None)
    uc.emu_start(start, 0, count=200)
    assert hit == [stop]
    return {r: uc.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX,
                                        UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_EBP, UC_X86_REG_ESP)}


def bases(g, i, first, pitch_dev=0x1234):
    uc = _uc(g)
    uc.mem_write(AR.PCAVE2 + AR.BASES_OFF, BASES)
    uc.mem_write(EBP - 0x1C, pitch_dev.to_bytes(4, "little"))
    uc.mem_write(EBP - 0x44, (0x1111).to_bytes(4, "little"))
    uc.mem_write(EBP - 0x3C, (0x2222).to_bytes(4, "little"))
    return _run(uc, AR.PCAVE2 + AR.BASES_OFF, AR.BASES_BACK,
                {UC_X86_REG_EBP: EBP, UC_X86_REG_ESP: EBP - 0x200, UC_X86_REG_ECX: i, UC_X86_REG_EAX: first,
                 UC_X86_REG_EDX: 0x7777, UC_X86_REG_EBX: 0x4444, UC_X86_REG_EDI: 0x5555, UC_X86_REG_ESI: ESI})


def energy(g, code, start, stop, lineh, s3, ecx0):
    uc = _uc(g)
    uc.mem_write(start, code)
    uc.mem_write(ESI + 0xE268, lineh.to_bytes(4, "little"))
    return _run(uc, start, stop,
                {UC_X86_REG_ESI: ESI, UC_X86_REG_EAX: s3, UC_X86_REG_ECX: ecx0, UC_X86_REG_EDX: 0x7777,
                 UC_X86_REG_EBX: 0x4444, UC_X86_REG_EDI: 0x5555, UC_X86_REG_EBP: EBP, UC_X86_REG_ESP: EBP - 0x200})


# ---- the law -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("g", range(17, 41))
def test_bases_rows_sit_at_cum(g):
    y = 0
    for k in range(1, 300):
        y += SL.bases_row_advance(k, g)
        assert y == SL.scale_px(42 * k, g)
        assert abs(32 * y - 2 * 42 * k * g) <= 16          # |cum(k) - 42kg/16| <= 1/2
        assert SL.bases_row_advance(k, g) >= SL.bases_row_cell(g)   # boxes never overlap


def _f4_layout(g):
    s = SL.scale_px
    win_h = 553 * g // 16                                   # ReportWin_win_init: content height 353 + 0xC8 at >= 1024
    clip_b = SL.rw_window_rects(650, win_h, g)[1][3]
    top = s(3, g) + SL.rw_line_h(0, g) + s(0x22, g) + s(2, g)   # [ebp-0x80] = clipT + lineH + 0x22 + 2
    rows = (clip_b - top - s(6, g)) // SL.bases_row_pitch(g)    # the engine's count (idiv @0x49D695), untouched
    return clip_b, top, rows


@pytest.mark.parametrize("g", range(17, 41))
def test_bases_count_is_vanillas_and_last_box_fits(g):
    clip_b, top, rows = _f4_layout(g)
    assert rows == (500 - 54 - 6) // 42 == 10              # vanilla: textB 500, top 3+15+0x22+2 = 54
    last_bottom = top + SL.scale_px(3, g) + SL.scale_px(42 * (rows - 1), g) + SL.bases_row_cell(g)
    assert last_bottom <= clip_b - SL.scale_px(3, g)


@pytest.mark.parametrize("g", GS)
def test_energy_stride_law(g):
    if g <= 16:
        assert SL.rw_energy_row_stride(15 + 3, g) == 18
    else:
        assert SL.rw_energy_row_stride(999, g) == SL.scale_px(18, g)
        assert abs(32 * SL.scale_px(18, g) - 36 * g) <= 16
    assert SL.rw_energy_row_stride(44, 40) == 45


def test_energy_list_h_native_is_pristine():
    assert SL.rw_energy_list_h(553, 16) == 438                # 494 - 56, from the painter's literals


@pytest.mark.parametrize("g", range(17, 41))
def test_energy_visible_rows_never_below_vanilla(g):
    """ListBox_calculate_dimensions count (h + gap 6) / stride: vanilla (438 + 6) // 18 = 24.  The law's stride shows
    exactly vanilla's 24 rows (scrollbar page 23) at every g; never fewer."""
    vanilla = SL.rw_energy_visible_rows(18, 553, 16)
    assert vanilla == 24
    win_h = 553 * g // 16
    stride = SL.rw_energy_row_stride(SL.rw_line_h(15, g) + SL.scale_px(3, g), g)
    n = SL.rw_energy_visible_rows(stride, win_h, g)
    assert n == (vanilla + 1 if g in (18, 20) else vanilla)   # 25 at g=18/20: the device box fits one more
    assert n >= vanilla                                        # so the scrollbar page n - 1 >= vanilla's 23


# ---- the bytes -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("first,k", [(0, 1), (0, 2), (0, 9), (3, 1), (3, 7), (17, 4), (100, 63)])
def test_bases_thunk(g, first, k):
    pitch_dev = SL.bases_row_pitch(g)
    r = bases(g, first + k, first, pitch_dev)
    want = pitch_dev if g <= 16 else SL.bases_row_advance(k, g)
    assert r[UC_X86_REG_EAX] == want
    assert r[UC_X86_REG_EDI] == 0x1111 and r[UC_X86_REG_ECX] == 0x2222
    assert (r[UC_X86_REG_EBX], r[UC_X86_REG_ESI], r[UC_X86_REG_EBP], r[UC_X86_REG_ESP]) == \
           (0x4444, ESI, EBP, EBP - 0x200)


@pytest.mark.parametrize("g", GS)
def test_bases_thunk_loop_total(g):
    y = sum(bases(g, k, 0, SL.bases_row_pitch(g))[UC_X86_REG_EAX] for k in range(1, 12))
    assert y == (11 * SL.bases_row_pitch(g) if g <= 16 else SL.scale_px(42 * 11, g))


@pytest.mark.parametrize("g", GS)
def test_energy_thunk_vs_engine(g, pe_ctx):
    s3 = SL.scale_px(3, g) if g > 16 else 3
    lineh = SL.rw_line_h(15, g)
    off = pe_ctx["resolver"].to_file_offset(AR.ENERGY_SITE)
    orig = pe_ctx["data"][off:off + 10]
    eng = energy(g, orig, AR.ENERGY_SITE, AR.ENERGY_BACK, lineh, s3, 0x500)
    uc_got = energy(g, ENERGY, AR.PCAVE2 + AR.ENERGY_OFF, AR.ENERGY_BACK, lineh, s3, 0x500)
    assert uc_got[UC_X86_REG_ECX] == eng[UC_X86_REG_ECX] == 0x500 - s3
    assert uc_got[UC_X86_REG_EDX] == SL.rw_energy_row_stride(eng[UC_X86_REG_EDX], g)
    for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_EBP, UC_X86_REG_ESP):
        assert uc_got[r] == eng[r]


@pytest.mark.parametrize("g", GS)
def test_bases_thunk_vs_engine_at_native(g, pe_ctx):
    """g <= 16: the thunk's eax/edi/ecx == the original 9 bytes'."""
    if g > 16:
        pytest.skip("scaled path covered by test_bases_thunk")
    off = pe_ctx["resolver"].to_file_offset(AR.BASES_SITE)
    orig = pe_ctx["data"][off:off + 9]
    uc = _uc(g)
    uc.mem_write(AR.BASES_SITE, orig)
    for a, v in ((EBP - 0x1C, 42), (EBP - 0x44, 0x1111), (EBP - 0x3C, 0x2222)):
        uc.mem_write(a, v.to_bytes(4, "little"))
    eng = _run(uc, AR.BASES_SITE, AR.BASES_BACK, {UC_X86_REG_EBP: EBP, UC_X86_REG_ESP: EBP - 0x200,
                                                  UC_X86_REG_ECX: 5, UC_X86_REG_EAX: 2})
    got = bases(g, 5, 2, 42)
    for r in (UC_X86_REG_EAX, UC_X86_REG_EDI, UC_X86_REG_ECX):
        assert got[r] == eng[r]


def test_site_bytes_are_original(pe_ctx):
    for name, (va, orig, _t, n) in AR.SITES.items():
        off = pe_ctx["resolver"].to_file_offset(va)
        assert pe_ctx["data"][off:off + n] == bytes.fromhex(orig), name


def test_yaml_is_the_assembler_output():
    """Baked 2026-10-14: each site appears ONCE in patches.yaml with the original bytes, its jmp resolves to the
    thunk, and the cave contents are byte-identical to the assembler's output."""
    import apply_patches as ap
    sites, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    cs = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    for tid, off, built in (("t_rw_bases_rowstep", AR.BASES_OFF, BASES), ("t_rw_energy_stride", AR.ENERGY_OFF, ENERGY)):
        assert symtab[tid] == AR.PCAVE2 + off == AR.PCAVE2 + int(cs[tid]["offset"])
        assert ap.ByteTemplate(cs[tid]["bytes"]).resolve(AR.PCAVE2 + off, symtab) == built, tid
    by_va = {}
    for s in sites:
        by_va.setdefault(int(str(s["virtual_addr"]), 0), []).append(s)
    for _name, (va, orig, thunk, n) in AR.SITES.items():
        assert len(by_va.get(va, [])) == 1, hex(va)
        s = by_va[va][0]
        assert int(s["length"]) == n and bytes.fromhex(s["original_bytes"].split("#")[0]) == bytes.fromhex(orig)
        nb = ap.ByteTemplate(s["new_bytes"]).resolve(va, symtab)
        assert nb == AR.site_bytes(va, symtab[thunk], n), hex(va)


def test_site_jumps_land_on_thunks():
    for _name, (va, _o, thunk, n) in AR.SITES.items():
        b = AR.site_bytes(va, AR.PCAVE2 + (AR.BASES_OFF if thunk == "t_rw_bases_rowstep" else AR.ENERGY_OFF), n)
        assert len(b) == n and b[0] == 0xE9
        assert (va + 5 + int.from_bytes(b[1:5], "little", signed=True)) & 0xFFFFFFFF in \
               (AR.PCAVE2 + AR.BASES_OFF, AR.PCAVE2 + AR.ENERGY_OFF)
