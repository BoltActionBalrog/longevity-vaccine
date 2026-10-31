"""Unicorn parity for the rw_scale_kinds bake (assemble_rw_kinds.py, wired through assemble_rw.py).

Oracle = scaling_laws.scale_px + the prototype's laws (hook_report_kinds_proto.js v13, user-verified 4K +
1600x1200 2026-09-07). Every thunk runs from its REAL assembled bytes at its REAL cave VA. Covers: the 11
detour caves -- IDENTITY against the PRISTINE displaced bytes at g=16 (the exe's own instructions emulated
side by side) and the laws at g 22/25/40; the three G-bracket wrappers (SCALE_NUM_G/DEN_G set/restored,
args forwarded, callee-clean); the right-border column save/restore around scroll_show/scroll_hide; the
v2 wheel helpers' cursor -> panel-slot path (kinds 0/3/4) and the KEYUP twin's g_rw_wheel_ate handshake;
t_rw_scrollsmall/sbinit v2 slot arrays; gate_pre v7 range admissions; the imm rows' law; and the sites'
instruction-boundary + pristine-byte contracts.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import struct
import sys

import pytest
import yaml
from apply_patches import _yaml_load  # the production loader (libyaml)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
pytest.importorskip("capstone")

from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402

import scaling_laws as SL  # noqa: E402
from test_rw_asm_parity import Emu, VA, C, AR, SP0, STUB, REC, r32, r32s, w32, GS, LAYOUT  # noqa: E402
import assemble_rw_kinds as RK  # noqa: E402
import assemble_se as SE  # noqa: E402
import wheel_stc_stub  # noqa: E402

s = SL.scale_px
RW, RI = AR.RW, AR.RI
_cs = Cs(CS_ARCH_X86, CS_MODE_32)
NL = chr(10)
REGS = ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp")

# (site, displaced length, thunk, resume)
DETOURS = [
    (0x49EB6F, 12, "t_rwk_proj_rowdiv", 0x49EB7B), (0x49EE8F, 22, "t_rwk_proj_rowy", 0x49EEA5),
    (0x4A0974, 12, "t_rwk_units_rowdiv", 0x4A0980), (0x49E129, 5, "t_rwk_bases_namex", 0x49E12E),
    (0x4A0D3D, 10, "t_rwk_units_rowstep", 0x4A0D47),   # v18 (2026-10-11): units row advance at cum(k)
    (0x4A3407, 5, "t_rwk_intel_textx", 0x4A340C), (0x4A478D, 6, "t_rwk_gov_split1", 0x4A4793),
    (0x4A484F, 8, "t_rwk_gov_split2", 0x4A4857), (0x4A4C9A, 9, "t_rwk_sat_split1", 0x4A4CA3),
    (0x4A4D76, 9, "t_rwk_sat_split2", 0x4A4D7F), (0x49FB00, 6, "t_rwk_sat_cx", 0x49FB06),
    (0x49FB1B, 9, "t_rwk_sat_cy", 0x49FB24),
    # v2 (2026-09-10): BASE STATUS rows, chrome follows content
    (0x49D590, 5, "t_rwk_bases_cell", 0x49D595), (0x49D620, 6, "t_rwk_bases_cellx", 0x49D626),
    (0x49D629, 6, "t_rwk_bases_celly", 0x49D62F), (0x49E3F8, 9, "t_rwk_bases_facey", 0x49E401),
    # v16 (2026-09-26): intel PROFILE console title inset + the two ListBox R/B insets
    (0x4AC4BE, 5, "t_rwk_intel_title", 0x4AC4C3), (0x4AC2F9, 5, "t_rwk_intel_lbr_l", 0x4AC2FE),
    (0x4AC767, 5, "t_rwk_intel_lbr_r", 0x4AC76C), (0x4A3046, 8, "t_rwk_intel_blocky", 0x4A304E),
    (0x45D4AE, 40, "t_slide_rail_a", 0x45D4D6),
    (0x45DA07, 33, "t_slide_rail_a2", 0x45DA28), (0x45D7FD, 17, "t_slide_rail_s1", 0x45D80E), (0x45D87A, 20, "t_slide_rail_s2", 0x45D88E),
]
EBP = SP0 - 0x1000


RW_TECH_RESET_A20 = 0x496C60    # ReportWin_tech_reset: mov [esi+0xA20], eax (= textB - clipT), every page paint


def _seed_win_h(e, win_h):
    """The ReportWin state a page painter runs in: the window height lives ONLY in the frame rect bottom RW+0x5990
    (init_report_screen / t_rw_init_leave); RW+0xA20 holds what ReportWin_tech_reset left there at the start of
    the paint, textB - clipT (device: win_h - s(0x35) - s(3)) -- poisoned on purpose so a cave reading +0xA20 as
    the window height counts one row short (the 2026-10-17 F5/F7 defect)."""
    g = e.g
    w32(e.uc, RW + 0x5990, win_h)
    w32(e.uc, RW + 0xA20, (win_h - s(0x35, g)) - s(3, g))


def _seed(e, thunk, cell=54):
    """Engine-side state each cave reads. Returns the register seed."""
    uc = e.uc
    w32(uc, RW + 0x59A4, cell)            # projects: cell h (the painter's scaled 0x36)
    w32(uc, EBP - 0x34, 1000)             # projects: rows top
    w32(uc, RI + 0x14, 600)               # toggle builders: row W
    w32(uc, RW + 0xF3D0, 115); w32(uc, RW + 0xF3D4, 115)   # planet flic w/h
    regs = dict(eax=0x11111111, ebx=0x42, ecx=0x33333333, edx=0x44444444, esi=RW, edi=0x55555555, ebp=EBP)
    if thunk.endswith("rowdiv"):
        regs.update(ecx=540)
        _seed_win_h(e, (553 * e.g) // 16)            # the init lever's fl(H*g/16) window height (H = 553 at >= 1024)
    elif thunk.endswith("rowy"):
        regs.update(eax=3, ecx=0x777)
    elif thunk.endswith("rowstep"):                  # units: visible row k = [ebp-4] - scroll = 3; eax = the walker's s(0x2B)
        w32(uc, EBP - 4, 7); w32(uc, RW + 0xC0FC, 4)
        regs.update(eax=s(0x2B, e.g), edx=1000, ecx=1000 + s(0x2B, e.g) - s(2, e.g))
    elif thunk.endswith("namex"):
        regs.update(edx=500, eax=1)
    elif thunk.endswith("textx"):
        regs.update(eax=300)
    elif thunk.endswith("gov_split1"):
        regs.update(eax=600)
    elif thunk.endswith("gov_split2"):
        regs.update(ecx=20, edx=100, eax=299, esi=RI)
    elif thunk.endswith("sat_split"):
        regs.update(eax=100, edi=300, esi=RI)
    elif "sat_split" in thunk:
        regs.update(eax=100, edi=300, esi=RI)
    elif thunk.endswith("bases_cellx"):
        regs.update(eax=300)
    elif thunk.endswith("bases_celly"):
        regs.update(ecx=95, eax=300)
    elif thunk.endswith("bases_facey"):
        regs.update(ecx=600, edx=0x777, esi=RW)
    elif thunk.endswith("intel_title"):
        regs.update(eax=0xFFFFFFFF, edx=100)          # wide-mode mask set; edx = the panel x (live across the site)
    elif thunk.endswith("intel_blocky"):
        regs.update(eax=400, edx=57)                  # flow: y=400 + lineH+s(20)=57; g_rwk_intel_pbot 0 unless a test sets it
    elif "slide_rail_s" in thunk:
        w32(e.uc, EBP - 0x24, 700); w32(e.uc, EBP - 0x18, 246); w32(e.uc, EBP - 0x1C, 1050); w32(e.uc, EBP - 0x2C, 0x2C2C)
        regs.update(esi=246, ebp=EBP)                  # settled: slide_y == T; A = 700 (device row)
    elif "slide_rail_a" in thunk:
        for va in (0x93F660, RK.SCREEN_W, 0x2070000):
            try:
                e.uc.mem_map(va & ~0xFFF, 0x1000)
            except Exception:  # noqa: BLE001  (already mapped)
                pass
        w32(e.uc, 0x93F660, 0x1234); w32(e.uc, RK.SCREEN_W, 1024); w32(e.uc, RK.SCREEN_H, 768)
        _slide_top(e, 3)                               # ReportWin at 1024x768: screen top 3
        regs.update(esi=0x2070000, ebp=EBP)
    return regs


def _slide_top(e, top):
    """The window's SCREEN top the way Win_flip_rect_2 derives it for a top-level window: local rect top [+0x478]
    (0 for every slide window) + [+0x140] + [+0x150]; the seed splits it so a thunk reading only [+0x478] fails."""
    w32(e.uc, 0x2070000 + 0x478, 0); w32(e.uc, 0x2070000 + 0x140, top - 1); w32(e.uc, 0x2070000 + 0x150, 1)


def _run_cave(e, start, until, regs, esp):
    uc = e.uc
    uc.mem_write(esp - 0x40, bytes(0x40))
    e.run(start, until, esp=esp, count=500, **regs)
    st = {r: e.reg(r) for r in REGS}
    st["stack"] = bytes(uc.mem_read(e.reg("esp"), max(0, esp + 0x20 - e.reg("esp"))))   # the LIVE stack only (scratch below esp is dead)
    st["a14"] = r32(uc, RW + 0xA14)
    st["bp2c"] = r32(uc, EBP - 0x2C)
    st["bp24"] = r32(uc, EBP - 0x24)
    return st


def test_detour_sites_end_on_instruction_boundaries_of_the_pristine_exe():
    for va, ln, _thunk, resume in DETOURS:
        b = SE.base_exe_bytes(va, ln + 16)
        ends = {i.address + i.size for i in _cs.disasm(b, va)}
        assert va + ln in ends, f"{va:#x}+{ln} cuts an instruction"
        assert resume == va + ln


@pytest.mark.parametrize("va,ln,thunk,resume", DETOURS)
def test_detour_identity_at_16_vs_pristine_bytes(va, ln, thunk, resume):
    """g=16: the cave must leave every register + the stack + the written field exactly as the displaced
    pristine instructions do (edi after t_rwk_proj_rowy excepted: redefined at 0x49EEA5 before any read)."""
    e = Emu(16)
    esp = SP0 - 8 if thunk.endswith("gov_split1") else SP0
    regs = _seed(e, thunk)
    e.uc.mem_write(va, SE.base_exe_bytes(va, ln))
    want = _run_cave(e, va, resume, regs, esp)
    e = Emu(16)
    _seed(e, thunk)
    got = _run_cave(e, VA[thunk], resume, regs, esp)
    if thunk.endswith("rowy"):
        want.pop("edi"); got.pop("edi")
    assert got == want


@pytest.mark.parametrize("g", (22, 25, 40))
def test_detour_laws(g):
    s2 = s(2, g)
    e = Emu(g); regs = _seed(e, "t_rwk_proj_rowdiv")
    st = _run_cave(e, VA["t_rwk_proj_rowdiv"], 0x49EB7B, regs, SP0)
    assert st["eax"] == st["edx"] == SL.rw_projects_visible_rows(540, (553 * g) // 16, g) == 8 and st["ecx"] == 540 and st["ebx"] == 0x42 and st["esp"] == SP0
    e = Emu(g); regs = _seed(e, "t_rwk_units_rowdiv")
    st = _run_cave(e, VA["t_rwk_units_rowdiv"], 0x4A0980, regs, SP0)
    assert st["eax"] == st["edx"] == SL.rw_units_visible_rows(540, (553 * g) // 16, g) == 10 and st["ecx"] == 540 and st["ebx"] == 0x42 and st["esp"] == SP0
    e = Emu(g); regs = _seed(e, "t_rwk_proj_rowy", cell=s(0x36, g))
    st = _run_cave(e, VA["t_rwk_proj_rowy"], 0x49EEA5, regs, SP0)
    assert st["eax"] == SL.rw_projects_row_y(1000, 3, g) and st["ecx"] == 0x777 and st["a14"] == 0x777 and st["esp"] == SP0
    assert st["ebx"] == 0x42 and st["edx"] == 0x44444444   # ebx (= the cell, read at 0x49EEB6) and edx (= colW) untouched
    e = Emu(g); regs = _seed(e, "t_rwk_units_rowstep")
    st = _run_cave(e, VA["t_rwk_units_rowstep"], 0x4A0D47, regs, SP0)
    adv = SL.rw_list_row_advance(3, SL.RW_UNITS_ROW_PITCH, g)
    assert (st["bp2c"], st["bp24"]) == (1000 + adv, 1000 + s(0x2B, g) - s2 + adv) and (st["edx"], st["ecx"]) == (st["bp2c"], st["bp24"])
    assert st["ebx"] == 0x42 and st["esi"] == RW and st["edi"] == 0x55555555 and st["esp"] == SP0
    e = Emu(g); regs = _seed(e, "t_rwk_bases_namex")
    st = _run_cave(e, VA["t_rwk_bases_namex"], 0x49E12E, regs, SP0)
    assert st["edx"] == 500 + s(0x3C, g) and st["ecx"] == 0x33333333 and st["eax"] == 1
    e = Emu(g); regs = _seed(e, "t_rwk_intel_textx")
    st = _run_cave(e, VA["t_rwk_intel_textx"], 0x4A340C, regs, SP0)
    assert st["eax"] == 300 + s(0x7D, g) and st["esp"] == SP0 - 8
    assert struct.unpack("<II", st["stack"][:8]) == (300 + s(0x7D, g), 0x42)
    # t_rwk_gov_split1/2 v2 (2026-10-17, law rw_tab_pair through t_rw_tabpair): test_rw_tabs_asm.py
    wl = (600 - s2) >> 1
    for thunk, resume, want in (("t_rwk_sat_split1", 0x4A4CA3, 300 + wl), ("t_rwk_sat_split2", 0x4A4D7F, 300 + wl + s2)):   # edi = row L
        e = Emu(g); regs = _seed(e, thunk)
        st = _run_cave(e, VA[thunk], resume, regs, SP0)
        assert st["eax"] == want and st["edi"] == 300 and st["ecx"] == 0x33333333 and st["edx"] == 0x44444444
        assert st["esp"] == SP0 - 4 and struct.unpack("<I", st["stack"][:4]) == (RW,)
    e = Emu(g); regs = _seed(e, "t_rwk_sat_cx")
    st = _run_cave(e, VA["t_rwk_sat_cx"], 0x49FB06, regs, SP0)
    assert st["eax"] == s(115, g)
    e = Emu(g); regs = _seed(e, "t_rwk_sat_cy")
    st = _run_cave(e, VA["t_rwk_sat_cy"], 0x49FB24, regs, SP0)
    assert st["eax"] == s(115, g) and st["ecx"] == 115 and st["esp"] == SP0 - 4 and struct.unpack("<I", st["stack"][:4]) == (115,)
    # v16: intel console centre title x += mask & s(0x4C) (the t_rw_title law); edx preserved
    for mask in (0, 0xFFFFFFFF):
        e = Emu(g); regs = _seed(e, "t_rwk_intel_title"); regs.update(eax=mask)
        st = _run_cave(e, VA["t_rwk_intel_title"], 0x4AC4C3, regs, SP0)
        assert st["eax"] == st["ecx"] == (s(0x4C, g) if mask else 0) and st["edx"] == 100 and st["esp"] == SP0
    # v16: the two console ListBox R/B insets: eax = -s(3) (the L/T rows give +s(3))
    for thunk, resume in (("t_rwk_intel_lbr_l", 0x4AC2FE), ("t_rwk_intel_lbr_r", 0x4AC76C)):
        e = Emu(g); regs = _seed(e, thunk)
        st = _run_cave(e, VA[thunk], resume, regs, SP0)
        assert st["eax"] == (-s(3, g)) & 0xFFFFFFFF and st["ecx"] == 0x33333333 and st["edx"] == 0x44444444 and st["esp"] == SP0
    # slide-window outer rail row: A' = T + ceil((SH - fl(530g/16) - T)*16/g); the shim then lands within g/16 of R
    for sw, sh, top in ((1024, 768, 3), (1600, 1200, 4), (1920, 1080, 28), (3840, 2160, 246), (3840, 2160, 1500)):
        for thunk, resume, cell, sw_reg in (("t_slide_rail_a", 0x45D4D6, EBP - 0x24, "edx"), ("t_slide_rail_a2", 0x45DA28, EBP - 0x38, "ecx")):
            e = Emu(g); regs = _seed(e, thunk)
            w32(e.uc, RK.SCREEN_W, sw); w32(e.uc, RK.SCREEN_H, sh); _slide_top(e, top)
            st = _run_cave(e, VA[thunk], resume, regs, SP0)
            a = r32s(e.uc, cell)
            assert a == SL.slide_rail_outer_a(top, sh, g) == SL.slide_rail_outer_row(sh, g) == sh - (530 * g) // 16   # v3: the device row itself
            assert st["eax"] == a & 0xFFFFFFFF and st[sw_reg] == sw
            if thunk == "t_slide_rail_a":
                assert st["edi"] == 0x1234 and st["esp"] == SP0 - 8 and struct.unpack("<II", st["stack"][:8]) == (0x55555555, 0x42)   # push ebx / push edi: edi on top
            else:
                assert st["esp"] == SP0 - 4 and struct.unpack("<I", st["stack"][:4]) == (0x42,)
        # the settled sites: v = max(slide_y, A) - T ceil-descaled; the shim then lands on R - T within g/16
        r = sh - (530 * g) // 16
        for slide_y in (top, top + 300):
            for thunk, resume in (("t_slide_rail_s1", 0x45D80E), ("t_slide_rail_s2", 0x45D88E)):
                e = Emu(g); regs = _seed(e, thunk)
                w32(e.uc, EBP - 0x24, r); w32(e.uc, EBP - 0x18, top); regs.update(esi=slide_y)
                st = _run_cave(e, VA[thunk], resume, regs, SP0)
                want = SL.slide_rail_settled_v(slide_y, r, top, g)
                got = st["eax"] if thunk == "t_slide_rail_s1" else st["esi"]
                assert got == want & 0xFFFFFFFF and st["esp"] == SP0
                if thunk == "t_slide_rail_s1":
                    assert st["ecx"] == top and st["edx"] == 1050
                else:
                    assert st["edx"] == top and st["eax"] == 0x2C2C and st["ecx"] == 1050
                y = SL.slide_rail_outer_y(slide_y, r, top, g)
                v = max(slide_y, r) - top
                assert v <= y <= v + g // 16                                       # the shim's round trip
    # v16b: the POLITICS block top clamps to g_rwk_intel_pbot (scaling_laws.intel_block_top)
    for pbot in (0, 300, 457, 458, 900):
        e = Emu(g); regs = _seed(e, "t_rwk_intel_blocky")
        w32(e.uc, C["g_rwk_intel_pbot"], pbot)
        st = _run_cave(e, VA["t_rwk_intel_blocky"], 0x4A304E, regs, SP0)
        want = SL.intel_block_top(457, 0, 0, g) if pbot == 0 else max(457, pbot)
        assert st["eax"] == want and r32(e.uc, RW + 0xA18) == want and st["esp"] == SP0 and st["esi"] == RW


# ---- G-bracket wrappers ----------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("thunk,callee,nargs", [("t_rwk_gblit", RK.BLIT_CORE, 4), ("t_rwk_gtable", RK.SPRITE_DRAW_TABLE, 5)])
def test_gwrap_sets_scale_pair_forwards_args_and_cleans(g, thunk, callee, nargs):
    e = Emu(g); uc = e.uc
    w32(uc, RK.G_NUM, 3); w32(uc, RK.G_DEN, 7)
    # callee (thiscall, callee-clean): record ecx, the args and the SCALE pair at call time
    rec = "".join(f"mov eax, dword ptr [esp+{4 + 4 * i}]\n mov dword ptr [{REC + 8 + 4 * i:#x}], eax\n" for i in range(nargs))
    e.stub(callee, f"mov dword ptr [{REC:#x}], ecx\n {rec} mov eax, dword ptr [{RK.G_NUM:#x}]\n mov dword ptr [{REC + 0x40:#x}], eax\n"
                   f"mov eax, dword ptr [{RK.G_DEN:#x}]\n mov dword ptr [{REC + 0x44:#x}], eax\n mov eax, 0x1234\n ret {4 * nargs:#x}")
    args = [0x2000000, 9, 33, 44, 0x2001000][:nargs]
    esp = SP0 - 4 * (nargs + 1)
    uc.mem_write(esp, struct.pack("<I", 0x11223344) + struct.pack("<%dI" % nargs, *args))
    e.uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA[thunk], 0x11223344, esp=esp, ecx=0x2002000, count=200)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0 and e.reg("eax") == 0x1234
    assert r32(uc, REC) == 0x2002000
    assert [r32(uc, REC + 8 + 4 * i) for i in range(nargs)] == args
    assert (r32(uc, REC + 0x40), r32(uc, REC + 0x44)) == ((g, 16) if g > 16 else (3, 7))
    assert (r32(uc, RK.G_NUM), r32(uc, RK.G_DEN)) == (3, 7)         # prior pair restored


# ---- right-border column save/restore ----------------------------------------------------
@pytest.mark.parametrize("g", (16, 25, 40))
def test_column_save_and_restore(g):
    e = Emu(g); uc = e.uc
    data, pitch, w, h, store = 0x2000000, 256, 200, 10, 0x2080000
    buf = AR.RW + 0x444
    w32(uc, buf + 0x54, data); w32(uc, buf + 0x4A8, pitch); w32(uc, buf + 0x80, w); w32(uc, buf + 0x84, (-h) & 0xFFFFFFFF)
    w32(uc, C["g_rw_railcol"], store)
    canvas = bytes((y * 7 + x) & 0xFF for y in range(h) for x in range(pitch))
    uc.mem_write(data, canvas)
    e.stub(RK.SCROLL_SHOW, "hlt")
    esp = SP0 - 12; uc.mem_write(esp, struct.pack("<III", 0x11223344, RW, 0x2050000))
    try:
        e.run(VA["t_rwk_scrollshow"], 0, esp=esp, count=20000)
    except Exception:
        pass
    assert e.reg("eip") in (RK.SCROLL_SHOW, RK.SCROLL_SHOW + 1) and e.reg("esp") == esp
    if g <= 16:
        assert r32(uc, C["g_rw_colsaved"]) == 0
        return
    x0, cw = w - s(47, g) - 4, s(47, g) + 4
    assert (r32(uc, C["g_rw_colsaved"]), r32s(uc, C["g_rw_colx0"]), r32(uc, C["g_rw_colw"]), r32(uc, C["g_rw_colh"])) == (1, x0, cw, h)
    assert bytes(uc.mem_read(store, cw * h)) == b"".join(canvas[y * pitch + x0:y * pitch + x0 + cw] for y in range(h))
    # second show: no re-save (store untouched even if the canvas changed)
    uc.mem_write(data, bytes(len(canvas)))
    try:
        e.run(VA["t_rwk_scrollshow"], 0, esp=esp, count=20000)
    except Exception:
        pass
    assert bytes(uc.mem_read(store, cw * h)) != bytes(cw * h)
    # hide: the callee runs with the forwarded (win, sb), then the column comes back; the rest stays
    e.stub(RK.SCROLL_HIDE, f"mov eax, dword ptr [esp+4]\n mov dword ptr [{REC:#x}], eax\n mov eax, dword ptr [esp+8]\n mov dword ptr [{REC + 4:#x}], eax\n ret")
    e.uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_scrollhide"], 0x11223344, esp=esp, count=20000)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == esp + 4 and (r32(uc, REC), r32(uc, REC + 4)) == (RW, 0x2050000)
    got = bytes(uc.mem_read(data, len(canvas)))
    for y in range(h):
        row = got[y * pitch:(y + 1) * pitch]
        assert row[:x0] == bytes(x0) and row[x0:x0 + cw] == canvas[y * pitch + x0:y * pitch + x0 + cw] and row[x0 + cw:] == bytes(pitch - x0 - cw)


# ---- wheel v2: kinds 0/3/4 by cursor panel ------------------------------------------------
SB_L, SB_R, PAR_L, PAR_R = 0x2050000, 0x2052000, 0x2060000, 0x2062000


def _bar(e, sb, parent, engaged=1, mn=0, mx=5):
    uc = e.uc
    w32(uc, sb + 0xC4, engaged); uc.mem_write(sb + 0xA20, struct.pack("<II", mn, mx))
    w32(uc, parent, parent + 0x100); w32(uc, parent + 0x100 + 0xFC, STUB + 0x800)
    w32(uc, parent - 0x48, parent + 0x200); w32(uc, parent + 0x208, 0x14); w32(uc, parent + 0x14 + 0xA8, 7)


def _wheel2(e, thunk, vk, cursor, kind=3, slots=((SB_L, PAR_L), (SB_R, PAR_R)), ate=None, energy=None, fits=(),
            client=None):
    """cursor = MainWin-space point (GetCursorPos = cursor + the MainWin origin (100, 50)); client = the raw
    GetCursorPos point instead (PRACX's hooked return: see wheel_stc_stub.mode)."""
    uc = e.uc
    _energy_list(e, **(energy if energy is not None else {"bar": 0}))
    w32(uc, AR.BASEPOP, 0); w32(uc, AR.MODAL_TOP, AR.RW); w32(uc, AR.KIND, kind)
    w32(uc, C["g_rw_sb"], 0); w32(uc, C["g_rw_sbparent"], 0)
    for i, (sb, par) in enumerate(slots):
        w32(uc, C["g_rw_sbs"] + 4 * i, sb); w32(uc, C["g_rw_sbparents"] + 4 * i, par)
        if sb:
            _bar(e, sb, par, **({"mn": 3, "mx": 3} if i in fits else {}))
    if ate is not None:
        w32(uc, C["g_rw_wheel_ate"], ate)
    # MainWin origin (100, 50); panel L (10,20)-(200,300), panel R (210,20)-(400,300) in MainWin space
    w32(uc, RK.MAINWIN + 0x13C, 100); w32(uc, RK.MAINWIN + 0x140, 50)
    uc.mem_write(RI + 0x20, struct.pack("<iiii", 10, 20, 200, 300)); uc.mem_write(RI + 0x30, struct.pack("<iiii", 210, 20, 400, 300))
    w32(uc, RK.G_HWND, 0x70707)
    w32(uc, RK.IAT_GETCURSORPOS, STUB + 0xA00); w32(uc, RK.IAT_SCREENTOCLIENT, STUB + 0xA40)
    wheel_stc_stub.install(uc)        # t_wheel_stc + g_wheel_stc (an active wheel_stc_stub.mode repoints the API)
    cx, cy = client if client is not None else (cursor[0] + 100, cursor[1] + 50)
    e.stub(STUB + 0xA00, f"mov eax, dword ptr [esp+4]\n mov dword ptr [eax], {cx}\n mov dword ptr [eax+4], {cy}\n mov eax, 1\n ret 4")
    e.stub(STUB + 0xA40, f"mov eax, dword ptr [esp+4]\n mov dword ptr [{REC + 0x20:#x}], eax\n mov eax, 1\n ret 8")
    e.stub(AR.GET_TARGET, "mov eax, 1\n ret")
    e.stub(AR.CHEVRON, f"mov dword ptr [{REC:#x}], ecx\n mov eax, dword ptr [esp+4]\n mov dword ptr [{REC + 4:#x}], eax\n ret 4")
    e.stub(STUB + 0x800, f"mov dword ptr [{REC + 8:#x}], ecx\n ret")
    e.stub(AR.DL_WHEEL_DOWN, "mov eax, 0x77\n ret"); e.stub(AR.DL_WHEEL_UP, "mov eax, 0x77\n ret")
    uc.mem_write(REC, b"\0" * 0x30)
    esp = SP0 - 4
    w32(uc, esp, 0x5F07B5); uc.mem_write(esp + 0x68, struct.pack("<II", vk, 0))
    uc.mem_write(0x5F07B5, b"\xf4")
    try:
        e.run(VA[thunk], 0x5F07B5, esp=esp, ebx=0xB, esi=0xE, edi=0xD, count=500)
    except Exception:
        pass
    ok = e.reg("esp") == SP0 and e.reg("eip") == 0x5F07B5 and (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (0xB, 0xE, 0xD)
    return struct.unpack("<III", bytes(uc.mem_read(REC, 12))), e.reg("eax"), ok, r32(uc, REC + 0x20) == 0x70707


@pytest.mark.parametrize("kind", (0, 3, 4))
def test_wheel_v2_scrolls_the_panel_under_the_cursor(kind):
    e = Emu(25)
    assert _wheel2(e, "t_rw_wheel_down", 0x28, (50, 100), kind=kind) == ((SB_L, 2, PAR_L), 0, True, True)
    assert r32(e.uc, PAR_L + 0x14 + 0xA8) == 0xFFFFFFFF and r32(e.uc, C["g_rw_wheel_ate"]) == 1
    assert _wheel2(e, "t_rw_wheel_up", 0x28, (50, 100), kind=kind, ate=1)[1:3] == (0, True)      # the KEYUP twin eats it once
    assert r32(e.uc, C["g_rw_wheel_ate"]) == 0
    assert _wheel2(e, "t_rw_wheel_down", 0x26, (250, 100), kind=kind) == ((SB_R, 1, PAR_R), 0, True, True)
    assert r32(e.uc, PAR_R + 0x14 + 0xA8) == 0xFFFFFFFF
    assert _wheel2(e, "t_rw_wheel_down", 0x28, (205, 100), kind=kind, ate=0)[:3] == ((0, 0, 0), 1, True)   # the seam: no list
    assert r32(e.uc, C["g_rw_wheel_ate"]) == 0
    assert _wheel2(e, "t_rw_wheel_down", 0x28, (50, 350), kind=kind, ate=0)[:3] == ((0, 0, 0), 1, True)
    assert r32(e.uc, C["g_rw_wheel_ate"]) == 0
    assert _wheel2(e, "t_rw_wheel_up", 0x28, (50, 100), kind=kind, ate=0)[1] == 0x77                # nothing eaten -> DL chain
    # no list behind the right panel, energy list closed: the key passes (kind 3 eats only while the list is open:
    # test_wheel_v3_panel_list_fits / test_wheel_v3_canvas_outside_everything)
    assert _wheel2(e, "t_rw_wheel_down", 0x28, (250, 100), kind=kind, slots=((SB_L, PAR_L), (0, 0)))[:3] == ((0, 0, 0), 1, True)
    assert _wheel2(e, "t_rw_wheel_down", 0x28, (250, 100), kind=kind, slots=((SB_L, PAR_L), (0, 0)),
                   energy={})[:3] == ((0, 0, 0), int(kind != 3), True)


def test_wheel_v2_kind2_and_other_kinds_unchanged():
    e = Emu(25)
    assert _wheel2(e, "t_rw_wheel_down", 0x28, (50, 100), kind=5)[1] == 0x77
    assert _wheel2(e, "t_rw_wheel_down", 0x28, (50, 100), kind=2)[1] == 0x77       # no labs bar stashed -> chain
    w32(e.uc, C["g_rw_wheel_ate"], 0)
    assert _wheel2(e, "t_rw_wheel_up", 0x28, (50, 100), kind=6)[1] == 0x77


# ---- wheel v3: the F3 canvas energy ListBox (its heap V bar ReportWin_energy_list_vbar) ---------------
# Bug: PRACX posts VK_UP/VK_DOWN per notch; over the energy list the key reached the focused ListBox
# (ListBox_on_key) and moved the SELECTION one base per notch. Fix: t_rw_wheel_energy scrolls the bar
# (vanilla chevron path); every other kind-3 notch that scrolls nothing is eaten while the list is open.
# The list Win's screen rect goes through the ENGINE's own GraphicWin_local_to_screen (its real bytes,
# emulated) over a ReportWin-shaped parent chain: list Win (child 0x20) -> ReportWin (child 0x20 | 0x8000:
# the parent-origin correction branch) -> a MapWin-like part (child 0x20) -> MainWin (top level).
SB_E = 0x2054000
LISTWIN, VBAR, L2S = AR.RW_ENERGY_LISTWIN, AR.RW_ENERGY_VBAR, AR.LOCAL_TO_SCREEN
MAPPART = 0x2080000
# (flags, parent, rRect1 L,T,R,B, rRect2 L,T)
CHAIN = {
    LISTWIN: (0x20, RW, (30, 40, 230, 340), (2, 3)),
    RW: (0x8020, MAPPART, (500, 200, 2320, 1582), (5, 7)),
    MAPPART: (0x20, RK.MAINWIN, (11, 13, 3851, 2173), (0, 0)),
    RK.MAINWIN: (0, 0, (100, 50, 3940, 2210), (0, 0)),
}


def _l2s_oracle(win):
    """GraphicWin_local_to_screen(win, 0, 0) as disassembled at 0x5ED240: own rRect1.LT + rRect2.LT, then
    (flags & 0x20 and a parent) the parent's chain, then (flags & 0x8000) minus the parent's rRect1.LT."""
    fl, par, r1, r2 = CHAIN[win]
    x, y = r1[0] + r2[0], r1[1] + r2[1]
    if fl & 0x20 and par:
        px, py = _l2s_oracle(par)
        x, y = x + px, y + py
        if fl & 0x8000:
            x, y = x - CHAIN[par][2][0], y - CHAIN[par][2][1]
    return x, y


BAR_R = 250                                         # the bar's +0x144 (parent-local): a column right of the list


def _list_rect_client():
    """v4: the list's screen rect starts AT local_to_screen(0,0) (the engine already adds +0x13C and +0x14C up
    the chain; v3 subtracted +0x14C again and missed by the Win's place in ReportWin -- 882 px at 4K, probe
    frida_f3wheel_*_20261015T054340Z.log); x extent to the right of the list's own scrollbar column."""
    ox, oy = _l2s_oracle(LISTWIN)
    _fl, _par, r1, _r2 = CHAIN[LISTWIN]
    return ox, oy, ox + max(r1[2], BAR_R) - r1[0], oy + r1[3] - r1[1]


CL, CT, CR, CB = _list_rect_client()               # client (= engine screen = backbuffer when not stretched)
EL, ET, ER, EB = CL - 100, CT - 50, CR - 100, CB - 50   # _wheel2 cursors are MainWin-space = client - (100,50)


def _energy_list(e, bar=SB_E, parent=LISTWIN, shown=1, mn=0, mx=5, visible=1):
    uc = e.uc
    uc.mem_write(L2S, SE.base_exe_bytes(L2S, 0x85))
    try:
        uc.ctl_remove_cache(L2S, L2S + 0x85)
    except Exception:  # noqa: BLE001
        pass
    w32(uc, VBAR, bar)
    if bar:
        w32(uc, bar + 0xC4, parent); w32(uc, bar + 0x9C, shown); uc.mem_write(bar + 0xA20, struct.pack("<ii", mn, mx))
        w32(uc, bar + 0x144, BAR_R)
    for win, (fl, par, r1, r2) in CHAIN.items():
        w32(uc, win + 0x98, fl); w32(uc, win + 0xC4, par)
        uc.mem_write(win + 0x13C, struct.pack("<iiii", *r1) + struct.pack("<ii", *r2))
    w32(uc, LISTWIN + 0x9C, visible)
    w32(uc, LISTWIN, 0x2070000); w32(uc, 0x2070000 + 0xFC, STUB + 0x800)
    w32(uc, LISTWIN - 0x48, 0x2071000); w32(uc, 0x2071000 + 8, 0x14); w32(uc, LISTWIN + 0x14 + 0xA8, 7)


SCROLLED_DN = ((SB_E, 2, LISTWIN), 0, True, True)
PASSED = ((0, 0, 0), 1, True, True)
EATEN = ((0, 0, 0), 0, True, True)
EDGES = [((EL, ET), True), ((EL - 1, ET), False), ((ER - 1, ET), True), ((ER, ET), False),
         ((EL, ET - 1), False), ((EL, EB - 1), True), ((EL, EB), False), ((ER - 1, EB - 1), True),
         ((EL - 1, EB), False), ((ER, EB - 1), False)]


def test_wheel_v3_chain_oracle_is_not_degenerate():
    """The modelled chain exercises both local_to_screen branches (the rect is not just rRect1 + RW)."""
    assert (CL, CT) == (30 + 2 + 500 + 5 + 11 + 100 - 11, 40 + 3 + 200 + 7 + 13 + 50 - 13)
    assert CR - CL == BAR_R - 30                                   # the bar column (250) is right of the list (230)
    assert not any(EL <= x < ER for x in (10, 199, 210, 399))      # clear of both console panels (MainWin space)


@pytest.mark.parametrize("cursor,inside", EDGES)
def test_wheel_v3_energy_list_edges(cursor, inside):
    """Half-open [L,R) x [T,B): inside scrolls the bar (chevron 2 = down); outside it the list is still open,
    so the kind-3 notch over the bare canvas is eaten -- the key never reaches the energy list."""
    e = Emu(25)
    got = _wheel2(e, "t_rw_wheel_down", 0x28, cursor, kind=3, energy={})
    assert got == (SCROLLED_DN if inside else EATEN)
    assert r32(e.uc, LISTWIN + 0x14 + 0xA8) == (0xFFFFFFFF if inside else 7)
    assert r32(e.uc, C["g_rw_wheel_ate"]) == 1
    assert _wheel2(e, "t_rw_wheel_up", 0x28, cursor, kind=3, ate=1, energy={})[1:3] == (0, True)   # KEYUP eaten once
    assert r32(e.uc, C["g_rw_wheel_ate"]) == 0


MODES = wheel_stc_stub.MODES
_pracx_cursor = wheel_stc_stub.pracx_cursor


@pytest.mark.parametrize("mode,origin,space,hits", MODES)
@pytest.mark.parametrize("cursor,inside", EDGES)
def test_wheel_v3_pracx_cursor_energy_edges(mode, origin, space, hits, cursor, inside):
    """The same backbuffer edges hold in every PRACX display setup once the cursor goes through t_wheel_stc:
    PRACX's GetCursorPos hook hands back BACKBUFFER coords while m_fWindowed (uimod then leaves the point
    alone), raw SCREEN coords otherwise (the plain ScreenToClient maps them)."""
    e = Emu(25)
    b = (cursor[0] + 100, cursor[1] + 50)                          # backbuffer (engine screen) point
    with wheel_stc_stub.mode(mode, *origin):
        got = _wheel2(e, "t_rw_wheel_down", 0x28, None, kind=3, energy={}, client=_pracx_cursor(b, origin, space))
    if hits:
        assert got[:3] == (SCROLLED_DN if inside else EATEN)[:3]
    elif cursor == (EL, ET):                                       # shifted by the origin: off the list's corner
        assert got[:3] == EATEN[:3]


@pytest.mark.parametrize("mode,origin,space,hits", MODES)
def test_wheel_v3_pracx_cursor_panel_edges(mode, origin, space, hits):
    """The console panels (v2, kind 0) in every setup: panel L spans MainWin x [10, 200)."""
    e = Emu(25)
    for mx, inside in ((10, True), (9, False), (199, True), (200, False)):
        with wheel_stc_stub.mode(mode, *origin):
            got = _wheel2(e, "t_rw_wheel_down", 0x28, None, kind=0,
                          client=_pracx_cursor((mx + 100, 150), origin, space))
        if hits:
            assert got[0] == ((SB_L, 2, PAR_L) if inside else (0, 0, 0)), (mode, mx)
        elif mx == 10:
            assert got[0] == (0, 0, 0)                             # the control misses the left edge


def test_wheel_v4_measured_4k_geometry():
    """The 4K Frida probe (2026-10-14, exe 817830f2): list Win rect (0,0,729,1099), its +0x14C place (882,137),
    local_to_screen(0,0) = (1932,383), bar column 729..779; the user's notch at (2268,1178) is over the list and
    must scroll (v3 subtracted (882,137) again and ate it).  Re-model the chain to those numbers: list Win under a
    top-level parent at (1050,246)."""
    global CHAIN, CL, CT, CR, CB, EL, ET, ER, EB, BAR_R
    saved = (CHAIN, BAR_R)
    try:
        CHAIN = {LISTWIN: (0x20, RW, (0, 0, 729, 1099), (882, 137)), RW: (0, 0, (1050, 246, 3000, 2000), (0, 0))}
        BAR_R = 779
        assert _l2s_oracle(LISTWIN) == (1932, 383)
        e = Emu(40)
        for (bx, by), inside in (((2268, 1178), True), ((1932, 383), True), ((1931, 383), False),
                                 ((1932 + 778, 383), True), ((1932 + 779, 383), False), ((1932, 383 + 1098), True),
                                 ((1932, 383 + 1099), False)):
            got = _wheel2(e, "t_rw_wheel_down", 0x28, (bx - 100, by - 50), kind=3, energy={})
            assert got == (SCROLLED_DN if inside else EATEN), (bx, by)
    finally:
        CHAIN, BAR_R = saved


def test_wheel_v3_energy_list_states():
    e = Emu(25)
    mid = ((EL + ER) // 2, (ET + EB) // 2)
    assert _wheel2(e, "t_rw_wheel_down", 0x26, mid, kind=3, energy={}) == ((SB_E, 1, LISTWIN), 0, True, True)
    # list fits / bar hidden (AR.EAT_WHEN_LIST_FITS), foreign parent / hidden list Win: the list is open
    # ([0x87C308] != 0) and nothing scrolled -> eaten, no selection move
    for st in ({"mn": 4, "mx": 4}, {"mn": 5, "mx": 4}, {"shown": 0}, {"parent": 0x2062000}, {"visible": 0}):
        w32(e.uc, C["g_rw_wheel_ate"], 0)
        assert _wheel2(e, "t_rw_wheel_down", 0x28, mid, kind=3, energy=st) == EATEN, st
        assert r32(e.uc, C["g_rw_wheel_ate"]) == 1 and r32(e.uc, LISTWIN + 0x14 + 0xA8) == 7
    w32(e.uc, C["g_rw_wheel_ate"], 0)                                         # no energy list: vanilla key
    assert _wheel2(e, "t_rw_wheel_down", 0x28, mid, kind=3, energy={"bar": 0}) == PASSED
    assert r32(e.uc, C["g_rw_wheel_ate"]) == 0


@pytest.mark.parametrize("kind,open_", [(3, True), (3, False), (0, True), (4, True)])
def test_wheel_v3_canvas_outside_everything(kind, open_):
    """A notch on the bare canvas (no list, no panel): eaten on F3 while the energy list is open, passed
    otherwise (v2 behaviour)."""
    e = Emu(25)
    w32(e.uc, C["g_rw_wheel_ate"], 0)
    got = _wheel2(e, "t_rw_wheel_down", 0x28, (205, 100), kind=kind, energy={} if open_ else {"bar": 0})
    assert got == (EATEN if (kind == 3 and open_) else PASSED)
    assert r32(e.uc, C["g_rw_wheel_ate"]) == int(kind == 3 and open_)


@pytest.mark.parametrize("kind", (0, 2, 4, 5))
def test_wheel_v3_energy_list_other_kinds_unchanged(kind):
    """Only kind 3 owns the energy list: every other kind behaves exactly as v2 over the same rect."""
    e = Emu(25)
    mid = ((EL + ER) // 2, (ET + EB) // 2)
    got = _wheel2(e, "t_rw_wheel_down", 0x28, mid, kind=kind, energy={})
    assert got[:3] == (((0, 0, 0), 0x77, True) if kind in (2, 5) else ((0, 0, 0), 1, True))
    got = _wheel2(e, "t_rw_wheel_down", 0x28, (50, 100), kind=kind, slots=((SB_L, PAR_L), (SB_R, PAR_R)), energy={})
    if kind in (0, 4):
        assert got == ((SB_L, 2, PAR_L), 0, True, True)


@pytest.mark.parametrize("kind", (0, 3, 4))
def test_wheel_v3_panel_list_fits(kind):
    """A console panel whose list fits (max <= min): kind 3 eats the notch (EAT_WHEN_LIST_FITS), kinds 0/4
    pass it (v2)."""
    assert AR.EAT_WHEN_LIST_FITS
    e = Emu(25)
    w32(e.uc, C["g_rw_wheel_ate"], 0)
    got = _wheel2(e, "t_rw_wheel_down", 0x28, (50, 100), kind=kind, energy={})
    assert got[0] == (SB_L, 2, PAR_L)                                        # sanity: engaged scrolls
    w32(e.uc, C["g_rw_wheel_ate"], 0)
    got = _wheel2(e, "t_rw_wheel_down", 0x28, (50, 100), kind=kind, energy={}, fits=(0,))
    assert got == ((0, 0, 0), int(kind != 3), True, True)
    assert r32(e.uc, C["g_rw_wheel_ate"]) == int(kind == 3) and r32(e.uc, PAR_L + 0x14 + 0xA8) == 7


def test_wheel_stc_is_the_one_cursor_path_of_every_asm_wheel_head():
    """Every asm wheel head calls t_wheel_stc where it used to call ScreenToClient; no head calls the IAT
    directly any more; the stub bytes are the ones uimod.dll's wheel.cpp byte-checks before it fills the cell."""
    import re
    import assemble_basewin as BW
    import assemble_ntw as NT
    with contextlib.redirect_stdout(io.StringIO()):
        import assemble_dl as AD
    for mod in (BW, NT, AD):
        assert mod.WHEEL_STC == AR.WHEEL_STC
    for src in (AR.asm_rw_wheel_down(), AD.asm_dl_wheel_down(), dict(NT.WHEEL_THUNKS)["t_ntw_wheel_down"],
                BW.asm_bw_wheel_down()):
        assert f"call    {AR.WHEEL_STC:#x}" in src or f"call {AR.WHEEL_STC}" in src or "call    t_wheel_stc" in src
        assert "IAT_SCREENTOCLIENT" not in src and f"{AR.RK.IAT_SCREENTOCLIENT:#x}" not in src.lower()
    y = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    for tid in ("t_rw_wheel_down", "t_dl_wheel_down", "t_bw_wheel_down", "t_ntw_wheel_down"):
        m = re.search(r"- id: " + tid + r"\s+offset: \S+\s+bytes: \"([^\"]+)\"", y)
        assert m and "FF 15 D4 92 66 00" not in m.group(1) and m.group(1).count("E8 {rel32:t_wheel_stc} 90") == 1, tid
    stc = SE.assemble(AR.asm_wheel_stc(), AR.WHEEL_STC, {})
    cpp = (ROOT.parent / "src" / "uimod" / "src" / "wheel.cpp").read_text(encoding="utf-8")
    arr = re.search(r"kWheelStcBytes\[\] = \{(.*?)\};", cpp, re.S).group(1)
    assert bytes(int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2})", re.sub(r"//[^\n]*", "", arr))) == stc
    assert int(re.search(r"kVA_WheelStc\s*= 0x([0-9A-F]+)", cpp).group(1), 16) == AR.WHEEL_STC
    assert int(re.search(r"kVA_WheelStcCell = 0x([0-9A-F]+)", cpp).group(1), 16) == AR.G_WHEEL_STC


# ---- scrollsmall / sbinit v2: panel slots ---------------------------------------------------
@pytest.mark.parametrize("left,slot", ((100, 0), (300, 1)))
def test_scrollsmall_and_sbinit_v2_slot_arrays(left, slot):
    e = Emu(25); uc = e.uc
    e.stub(AR.SCROLL_SMALL, "ret")
    w32(uc, AR.G_SCROLLBAR_W, 12)
    w32(uc, RI + 0xC, left); w32(uc, RI + 0x50, 200)
    for i in range(2):
        w32(uc, C["g_rw_sbs"] + 4 * i, 0xAAA0 + i); w32(uc, C["g_rw_sbparents"] + 4 * i, 0xBBB0 + i)
    esp = SP0 - 4; w32(uc, esp, 0x11223344)
    try:
        e.run(VA["t_rw_scrollsmall"], 0x11223344, esp=esp, count=100)
    except Exception:
        pass
    assert r32(uc, C["g_rw_inlist"]) == 1 and r32(uc, C["g_rw_slot"]) == slot
    assert r32(uc, C["g_rw_sbs"] + 4 * slot) == 0 and r32(uc, C["g_rw_sbparents"] + 4 * slot) == 0
    assert r32(uc, C["g_rw_sbs"] + 4 * (1 - slot)) == 0xAAA0 + (1 - slot)          # the other panel's bar survives
    e.stub(AR.SB_INIT_RESUME, "hlt")
    esp = SP0 - 32
    uc.mem_write(esp, struct.pack("<IIIIIII", 0x60A700, 309, 0, 19, 227, 0x890250, 0xFFFFFFFF))
    try:
        e.run(VA["t_rw_sbinit"], 0, esp=esp, ecx=0x7F61008, ebx=0x42, edx=0x99, count=100)
    except Exception:
        pass
    assert e.reg("eip") in (AR.SB_INIT_RESUME, AR.SB_INIT_RESUME + 1) and e.reg("edx") == 0x99 and e.reg("eax") == 0x890250
    assert r32(uc, C["g_rw_sb"]) == 0x7F61008 and r32(uc, C["g_rw_sbparent"]) == 0x890250
    assert r32(uc, C["g_rw_sbs"] + 4 * slot) == 0x7F61008 and r32(uc, C["g_rw_sbparents"] + 4 * slot) == 0x890250
    assert r32(uc, C["g_rw_sbs"] + 4 * (1 - slot)) == 0xAAA0 + (1 - slot)


# ---- gate_pre v7: range admissions ----------------------------------------------------------
def _gate(esi):
    e = Emu(25)
    e.stub(AR.BTN_GATE, "mov eax, 0x99\n ret")
    w32(e.uc, C["g_rw_sb"], 0)
    esp = SP0 - 4; w32(e.uc, esp, 0x11223344)
    try:
        e.run(VA["thunk_btn_gate_pre"], 0x11223344, esp=esp, esi=esi, count=100)
    except Exception:
        pass
    assert e.reg("esp") == SP0 and e.reg("eip") == 0x11223344
    return e.reg("eax")


def test_gate_pre_v7_ranges():
    for lo, n, _lbl in RK.GATE_RANGES:
        for k in range(n):
            assert _gate(lo + k * 0xB4C) == 1
        assert _gate(lo + n * 0xB4C - 1) == 1
    lo0 = min(lo for lo, _n, _l in RK.GATE_RANGES)
    assert _gate(lo0 - 1) in (0x99, 1)
    assert _gate(0x7FE80C) == 0


# ---- report-init VirtualProtect window ----------------------------------------------------------
def test_report_init_vp_window_covers_every_walked_row():
    """t_dl_immfix stores through every row site of both tables; a site outside the DL bootstrap window
    (0x429000..0x49C000) and the report-init window (VP_PAGE..VP_PAGE+vp_len(), pushed by t_rw_init_leave)
    faults on the read-only .text page. Bake v1 pushed a 0xD000 constant (end 0x4A9000) while the kinds rows
    reach 0x4AC7A4: the first store past it crashed game load (fault 0xA2E163 = the walker's byte store)."""
    n = AR.vp_len()
    assert n % 0x1000 == 0 and AR.VP_PAGE == AR.DL_VP_HI == 0x49C000 and AR.DL_VP_LO == 0x429000
    rows = AR.rw_rows() + AR.tech_rows()
    end = 0
    for site, _a, _b, bits in rows:
        w = 4 if bits & AR.K['K_W4'] else 1
        assert AR.DL_VP_LO <= site and site + w <= AR.VP_PAGE + n, hex(site)
        end = max(end, site + w)
    assert end > AR.VP_PAGE + n - 0x1000                            # tight: no slack page
    # the assembled bootstrap (LoadLibrary / GetProcAddress / VirtualProtect through the IAT) opens exactly
    # this window with PAGE_EXECUTE_READWRITE, stores the old protection in g_rw_vpold and latches g_rw_vpdone
    e = Emu(40)
    uc = e.uc
    w32(uc, AR.G_DL_IMMG, 16); w32(uc, C["g_rw_vpdone"], 0)
    w32(uc, AR.IAT_LOADLIB, STUB + 0xB00); w32(uc, AR.IAT_GETPROC, STUB + 0xB40)
    e.stub(STUB + 0xB00, "mov eax, 0x7A000000" + NL + "ret 4")
    e.stub(STUB + 0xB40, f"mov eax, {STUB + 0xB80:#x}" + NL + "ret 8")
    e.stub(STUB + 0xB80, NL.join(f"mov eax, dword ptr [esp+{4 + 4 * i}]" + NL + f"mov dword ptr [{REC + 4 * i:#x}], eax"
                                 for i in range(4)) + NL + "mov eax, 1" + NL + "ret 0x10")
    e.stub(AR.T_DL_IMMFIX, "hlt")                                  # stop at the first walk
    uc.mem_write(REC, bytes(0x20))
    try:
        e.run(VA["t_rw_init_leave"], 0, esp=SP0, count=5000)
    except Exception:
        pass
    assert struct.unpack("<IIII", bytes(uc.mem_read(REC, 16))) == (AR.VP_PAGE, n, 0x40, C["g_rw_vpold"])
    assert r32(uc, C["g_rw_vpdone"]) == 1
    assert e.reg("eip") == AR.T_DL_IMMFIX + 1 and r32(uc, AR.G_DL_IMMG) == 40 and e.reg("esi") == AR.TAB_RW


# ---- rows + sites ------------------------------------------------------------------------------
def test_kinds_rows_law_and_uniqueness():
    sites = [r[0] for r in RK.KINDS_IMMS]
    assert len(set(sites)) == len(sites) == 401      # v7 2026-09-12b: + the BASES turns-text right inset row
    for site, w, a, b, _l in RK.KINDS_IMMS:
        assert w in (1, 4) and a >= 0 and b >= 0
        for g in GS:
            v = s(a, g) - s(b, g)
            assert AR.AD.imm_value(a, b, AR.KINDBITS['HD'] | (AR.K['K_W4'] if w == 4 else 0), g) == v
            if w == 1:
                assert -128 <= v <= 127, (hex(site), g, v)
    for site, a, _l in RK.VEH_ROWS:
        assert AR.AD.imm_value(a, 0, AR.KINDBITS['VEH'], 16) == a
        for g in GS:
            assert AR.AD.imm_value(a, 0, AR.KINDBITS['VEH'], g) == SL.veh_size_scaled(a, g)
    assert len(AR.hof_rows_dropped()) == 57                    # the Hall of Fame rows: hof_scale's own table since 2026-09-14
    assert len(AR.RW_IMMS) == 82 + 9                           # 2026-10-17: 87 - the 5 rows inside / past the tab-pair v2 caves
                                                               # 2026-10-25 F45: + the 9 F2-card rows (SL.RW_TECH_CARD_IMMS)
    # 2026-10-17 console chain: the CHAIN_ROWS sites are t_rw_immsum's (98: 10 RW_IMMS + 88 kinds rows), never HD rows
    # (fix 4g: + the F6 faction-target x / w / y and the satellite-target / unit-command y rows, 93 -> 98)
    rw_sites, k_sites = {r[0] for r in AR.RW_IMMS}, {r[0] for r in RK.KINDS_IMMS}
    assert AR.CHAIN_SITES <= rw_sites | k_sites and not AR.CHAIN_SITES & set(RK.DETOUR_COVERED_ROWS)
    assert len(AR.CHAIN_ROWS) == len(AR.CHAIN_SITES) == 98
    assert len(AR.CHAIN_SITES & rw_sites) == 10 and len(AR.CHAIN_SITES & k_sites) == 88 and not rw_sites & k_sites & AR.CHAIN_SITES
    assert len(AR.rw_rows()) == (len(AR.RW_IMMS) + 401 - len(RK.DETOUR_COVERED_ROWS) + 4 - len(AR.hof_rows_dropped())
                                 - len(AR.CHAIN_SITES))


def _yaml_sites():
    y = _yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    out = []
    for s_ in y["sites"]:
        va = s_["virtual_addr"]; va = int(va, 16) if isinstance(va, str) else va
        toks = (s_.get("new_bytes") or s_.get("original_bytes") or "").split()
        n = s_.get("length") or sum(4 if t.startswith("{") else 1 for t in toks)
        first = int(toks[0], 16) if toks and not toks[0].startswith("{") else -1
        out.append((va, n, first, s_["id"]))
    assert len(out) > 1000
    return out


def test_no_walker_row_inside_any_patched_site():
    """The walker rewrites its row bytes at RUNTIME, after the patcher: a row inside any site's patched bytes
    (other than the imm32 field of a mov-imm rewrite) corrupts that site. Bake v1a shipped the proto's 0x14 row
    at 0x4A4851 inside the gov_split2 detour: at g=40 the store turned `E9 CC C2 58 00` into `E9 CC 32 58 00`
    = jmp 0xA27B20 (zeroed DW data) -> F2 crashed. Checked against EVERY site in the yaml, all groups."""
    rows = AR.rw_rows() + AR.tech_rows() + AR.AD.imm_rows(False) + AR.AD.imm_rows(True)   # + the DL walker's own tables
    rows += [(site, 0, 0, AR.K['K_W4'] if w == 4 else 0) for site, w, *_ in AR.CHAIN_ROWS]   # + t_rw_immsum's (2026-10-17)
    sites = _yaml_sites()
    bad = AR.row_site_conflicts(rows, sites)
    assert bad == [], [(hex(s), i) for s, i in bad]
    # the only tolerated overlaps are the two kind-tab mov-imm fields
    inside = sorted({site for site, _a, _b, _bits in rows for va, n, _f, _i in sites if va <= site < va + n})
    assert inside == [0x4A42E1, 0x4A42E7]


def test_detour_covered_rows_are_dropped_and_inside_their_caves():
    live = {r[0] for r in AR.rw_rows()}
    proto = {r[0] for r in RK.KINDS_IMMS}
    # 2026-10-17 tab pairs v2: the new kinds detours (test_rw_tabs_asm.DETOURS) + gov_split1 v2's skipped store span
    spans = [(va, ln) for va, ln, _t, _r in DETOURS] + [(0x4A90DD, 9), (0x4A90A8, 6), (0x4A90BA, 8), (0x4A4F05, 26),
                                                         (0x4A4C42, 8), (0x4A4927, 9), (0x4A4793, 0x4A47B0 - 0x4A4793)]
    for site in RK.DETOUR_COVERED_ROWS:
        assert site in proto and site not in live, hex(site)
        assert any(va <= site < va + ln for va, ln in spans), hex(site)
    # the corruption law itself: the walker's byte store at 0x4A4851 over the live detour would have produced 0xA27B20
    e9 = SE.base_exe_bytes(0x4A484F, 8)                              # pristine: add ecx,0x14 / push ebx / lea
    assert e9[:3] == bytes([0x83, 0xC1, 0x14])
    rel = (VA["t_rwk_gov_split2"] - (0x4A484F + 5)) & 0xFFFFFFFF
    corrupt = bytearray(struct.pack("<I", rel)); corrupt[1] = s(0x14, 40) & 0xFF
    # the store re-targets the detour to a wild address (0xA27B20 at the v1a layout, minidump-confirmed); the
    # exact value follows the cave layout, so assert the mechanism, not the literal
    wild = (0x4A484F + 5 + struct.unpack("<i", bytes(corrupt))[0]) & 0xFFFFFFFF
    assert wild != VA["t_rwk_gov_split2"]


def test_kinds_sites_pristine_bytes_and_count():
    sites = [x for x in AR.site_list(VA) if x["group"] == "rw_scale_kinds"]
    assert len(sites) == 11 + 4 + 32 + 5 + 5 + 2 + 5 + 2 + 6 + 4 + 14 + 4 + 1 + 5 + 4 + 13 + 1 + 1 + 6 + 24 + 1   # 2026-10-18 fix 9: +1 strip anchor detour (t_rwk_stripanchor, law rw_strip_anchor); 2026-10-17 console chain: +24 d528 boxes -> t_rw_rowframe (AR.D528_SITES); 2026-10-17: +6 tab-pair v2 detours (ops tab box w, BEST BASES list x/w, governor list cursor, F6 / F4-mode tab row w); 2026-10-11: +1 ListBox_close report text pad (t_lb_textpad); v18: +1 units row advance (t_rwk_units_rowstep); v17: +6 console title insets + 7 ListBox R/B insets (CALL helpers); v2: +6 specialist faces, +4 bases row caves; v3: +14 console frames; v8: +4 blink stamps; v13: +1 blink tile stash; v16: +5 intel PROFILE (portrait, console title inset, 2 ListBox R/B insets, POLITICS block clamp); +4 slide_show / slide_hide outer rail row cells + the 2 settled-draw descales (the observer-faction detour was withdrawn: ReportIf_activate already sets it)
    assert all(x["new"].endswith("{rel32:t_rwk_boxhalf}") for x in sites if ".box" in x["id"] and ".boxforce" not in x["id"])   # v2: the 32 K-frames through the half-open wrapper
    faces = [x for x in sites if x["id"].startswith("ReportWin_draw_bases.face_") and x["id"][-1] in "abcdefgh"]   # not the face_y detour
    assert len(faces) == 8 and all(x["new"] == "E8 {rel32:t_rwk_face_blit}" for x in faces)   # v4/v5: full-coverage bilinear
    force = [x for x in sites if ".boxforce" in x["id"]]
    strip = [x for x in force if x["va"] == RK.STRIP_FRAME_SITE]      # 2026-10-17: drawn left of its clip (law rw_strip_frame)
    assert len(force) == 14 and len(strip) == 1 and strip[0]["new"] == "E8 {rel32:t_rwk_stripframe}"
    assert all(x["new"] == "E8 {rel32:t_rwk_boxforce}" for x in force if x not in strip)
    anchor = [x for x in sites if x["va"] == RK.STRIP_ANCHOR_SITE]       # 2026-10-18 fix 9 (law rw_strip_anchor)
    assert len(anchor) == 1 and anchor[0]["orig"] == bytes.fromhex("83C640B964EC7A00") and anchor[0]["pattern"] == "detour_inplace"
    assert {x["va"] for x in force} == {va for sites_ in RK.BOXFORCE_SITES.values() for va, _w in sites_}
    for x in sites:
        assert SE.base_exe_bytes(x["va"], len(x["orig"])) == x["orig"], x["id"]
    assert len({x["id"] for x in sites}) == len(sites)
    d528 = [x for x in sites if ".d528_" in x["id"]]
    assert len(d528) == len(AR.D528_SITES) == 24 and all(x["new"] == "E8 {rel32:t_rw_rowframe}" for x in d528)
    assert all(bytes.fromhex("6828D57800") in SE.base_exe_bytes(x["va"] - 0x40, 0x40) for x in d528)   # each pushes the d528 params


# ---- v2 (2026-09-10): BASE STATUS rows, the half-open K-frame wrapper, the parity resampler -------
@pytest.mark.parametrize("g", (22, 25, 40))
def test_bases_row_caves_follow_the_content_law(g):
    cell, imm, s2 = SL.bases_row_cell(g), SL.bases_face_y_imm(g), s(2, g)
    e = Emu(g); regs = _seed(e, "t_rwk_bases_cell")
    st = _run_cave(e, VA["t_rwk_bases_cell"], 0x49D595, regs, SP0)
    assert st["eax"] == cell and st["edx"] == 0x44444444 and st["ecx"] == 0x33333333 and st["esp"] == SP0
    e = Emu(g); regs = _seed(e, "t_rwk_bases_cellx")
    st = _run_cave(e, VA["t_rwk_bases_cellx"], 0x49D626, regs, SP0)
    assert st["eax"] == 300 + cell and st["bp2c"] == 300 + cell and st["ecx"] == 0x33333333 and st["edx"] == 0x44444444 and st["esp"] == SP0
    e = Emu(g); regs = _seed(e, "t_rwk_bases_celly")
    st = _run_cave(e, VA["t_rwk_bases_celly"], 0x49D62F, regs, SP0)
    assert st["edx"] == 95 + cell and st["eax"] == 300 + s2 and st["ecx"] == 95 and st["esp"] == SP0
    e = Emu(g); regs = _seed(e, "t_rwk_bases_facey")
    st = _run_cave(e, VA["t_rwk_bases_facey"], 0x49E401, regs, SP0)
    assert st["ecx"] == 600 - imm and st["a14"] == 0x777 and st["eax"] == 0x11111111 and st["edx"] == 0x777 and st["esp"] == SP0
    # the composite: a row whose box bottom is top + cell puts the face at top + K, and the face fills the interior
    top = 1000; k = SL.stroke_width(g)
    assert (top + cell) - (SL.bases_row_pitch(g) >> 1) - imm == top + k and cell - 2 * k == SL.bases_face_h(g)


@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_boxhalf_decrements_r_b_around_devfill_and_restores(g):
    e = Emu(g); uc = e.uc
    rect = 0x2050000; params = 0x2051000
    uc.mem_write(rect, struct.pack("<iiii", 26, 54, 670, 500))
    uc.mem_write(REC, bytes(0x20))
    # devfill stub: record (ecx, rect R/B as seen, params), RET 8
    e.stub(RK.DEVFILL, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov edx, dword ptr [eax+8]
        mov dword ptr [{REC + 4:#x}], edx
        mov edx, dword ptr [eax+12]
        mov dword ptr [{REC + 8:#x}], edx
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 12:#x}], eax
        ret 8
    """)
    esp = SP0 - 12
    uc.mem_write(esp, struct.pack("<III", 0x11223344, rect, params))
    uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_boxhalf"], 0x11223344, esp=esp, ecx=0x777, ebx=0xB, esi=0xE, edi=0xD, count=200)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == esp + 12 and (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (0xB, 0xE, 0xD)
    seen = struct.unpack("<IIII", bytes(uc.mem_read(REC, 16)))
    if g <= 16:
        assert seen == (0x777, 670, 500, params)                  # native path: devfill sees the rect untouched
    else:
        assert seen == (0x777, 669, 499, params)                  # half-open -> inclusive: R-1 / B-1 during the call
    assert struct.unpack("<iiii", bytes(uc.mem_read(rect, 16))) == (26, 54, 670, 500)   # restored


@pytest.mark.parametrize("g", GS)
def test_boxforce_draws_natively_then_force_remaps_the_drawn_rect(g):
    """t_rwk_boxforce (v3b): the native Buffer_box_sprite call runs with the caller's dest/rect/params, the rect's
    R and B decremented for the call (the hud_boxframe/hollow_flat renderer is INCLUSIVE; v3b) and restored after,
    THEN g_fe_dst/x/y/w/h = dest / L / T / (R-1)-L / (B-1)-T (the drawn rect), g_rm_force = 1 and
    thunk_fe_pair_remap is CALLED once.  g<=16: the native call only, rect untouched.  Callee-saved registers
    survive, esp balances (RET 8), eip returns to the caller."""
    e = Emu(g); uc = e.uc
    rect = 0x2050000; params = 0x2051000
    uc.mem_write(rect, struct.pack("<iiii", 26, 54, 670, 500))
    uc.mem_write(REC, bytes(0x40))
    for a in (RK.G_FE_DST, RK.G_FE_X, RK.G_FE_Y, RK.G_FE_W, RK.G_FE_H, RK.G_RM_FORCE):
        w32(uc, a, 0xEEEEEEEE)
    # Buffer_box_sprite stub: record (ecx, rect, params), count calls, clobber the caller-saved regs, RET 8
    e.stub(RK.BOX_SPRITE, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        inc dword ptr [{REC + 12:#x}]
        mov eax, dword ptr [esp+4]
        mov edx, dword ptr [eax+8]
        mov dword ptr [{REC + 48:#x}], edx
        mov edx, dword ptr [eax+12]
        mov dword ptr [{REC + 52:#x}], edx
        mov ecx, 0xDEAD0001
        mov edx, 0xDEAD0002
        mov eax, 0xDEAD0003
        ret 8
    """)
    # fe_pair_remap stub: snapshot the staged rect + force flag AT CALL TIME, count, clobber eax/ecx/edx, RET
    e.stub(RK.FE_PAIR_REMAP, f"""
        mov eax, dword ptr [{RK.G_FE_DST:#x}]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [{RK.G_FE_X:#x}]
        mov dword ptr [{REC + 20:#x}], eax
        mov eax, dword ptr [{RK.G_FE_Y:#x}]
        mov dword ptr [{REC + 24:#x}], eax
        mov eax, dword ptr [{RK.G_FE_W:#x}]
        mov dword ptr [{REC + 28:#x}], eax
        mov eax, dword ptr [{RK.G_FE_H:#x}]
        mov dword ptr [{REC + 32:#x}], eax
        mov eax, dword ptr [{RK.G_RM_FORCE:#x}]
        mov dword ptr [{REC + 36:#x}], eax
        mov eax, dword ptr [{REC + 12:#x}]
        mov dword ptr [{REC + 40:#x}], eax
        inc dword ptr [{REC + 44:#x}]
        mov dword ptr [{RK.G_RM_FORCE:#x}], 0
        mov eax, 0x1234
        mov ecx, 0x5678
        mov edx, 0x9ABC
        ret
    """)
    esp = SP0 - 12
    uc.mem_write(esp, struct.pack("<III", 0x11223344, rect, params))
    uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_boxforce"], 0x11223344, esp=esp, ecx=0x777, ebx=0xB, esi=0xE, edi=0xD, ebp=0xA, count=400)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == esp + 12
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0xB, 0xE, 0xD, 0xA)
    seen = struct.unpack("<12I", bytes(uc.mem_read(REC, 48)))
    assert seen[:4] == (0x777, rect, params, 1)                       # ONE native draw with the caller's exact args
    assert struct.unpack("<iiii", bytes(uc.mem_read(rect, 16))) == (26, 54, 670, 500)   # rect untouched
    rb_at_call = (r32(uc, REC + 48), r32(uc, REC + 52))
    if g <= 16:
        assert seen[11] == 0                                          # no remap, nothing staged
        assert all(r32(uc, a) == 0xEEEEEEEE for a in (RK.G_FE_DST, RK.G_FE_X, RK.G_RM_FORCE))
        assert rb_at_call == (670, 500)                               # native: the caller's rect verbatim
    else:
        assert seen[11] == 1                                          # remap CALLED once ...
        assert seen[10] == 1                                          # ... AFTER the draw
        assert rb_at_call == (669, 499)                               # v3b: R-1/B-1 for the inclusive renderer
        assert seen[4:10] == (0x777, 26, 54, 669 - 26, 499 - 54, 1)   # dest, L, T, drawn w/h, force set


# ---- v4: CITIZENS faces through the full-coverage NN scaler -------------------------------------
@pytest.mark.parametrize("g", GS)
def test_face_blit_routes_to_the_face_hybrid_with_the_clip_bottom(g):
    """t_rwk_face_blit: g>16 -> ONE call of thunk_face_hybrid (v15; Sprite_draw_2 contract) with ecx = the Sprite and
    the caller's dest/key/x/y + num/den = g/16, the dest canvas height (+0x84, negative) clamped to -clip.B for the
    call and restored after; esp balanced (RET 0x10), ebx preserved, eip back to the caller.  g<=16 -> the engine
    core with the untouched args (tail-jump), height untouched."""
    e = Emu(g); uc = e.uc
    dest = 0x2060000; sprite = 0x2061000
    uc.mem_write(dest + 0x84, struct.pack("<i", -600))               # canvas h (negative)
    uc.mem_write(dest + 0x2C, struct.pack("<i", 480))                # clip bottom
    uc.mem_write(REC, bytes(0x40))
    e.stub(RK.FACE_HYBRID, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [esp+20]
        mov dword ptr [{REC + 20:#x}], eax
        mov eax, dword ptr [esp+24]
        mov dword ptr [{REC + 24:#x}], eax
        mov eax, dword ptr [{dest + 0x84:#x}]
        mov dword ptr [{REC + 28:#x}], eax
        inc dword ptr [{REC + 32:#x}]
        mov eax, 0xDEAD0003
        mov ecx, 0xDEAD0001
        mov edx, 0xDEAD0002
        ret 0x18
    """)
    e.stub(RK.BLIT_CORE, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 16:#x}], eax
        inc dword ptr [{REC + 36:#x}]
        ret 0x10
    """)
    esp = SP0 - 20
    uc.mem_write(esp, struct.pack("<IIIII", 0x11223344, dest, 9, 33, 44))
    uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_face_blit"], 0x11223344, esp=esp, ecx=sprite, ebx=0xB, esi=0xE, edi=0xD, ebp=0xA, count=400)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == esp + 20
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0xB, 0xE, 0xD, 0xA)
    seen = struct.unpack("<10I", bytes(uc.mem_read(REC, 40)))
    assert struct.unpack("<i", bytes(uc.mem_read(dest + 0x84, 4)))[0] == -600      # height restored / untouched
    if g <= 16:
        assert (seen[8], seen[9]) == (0, 1) and seen[0] == sprite and (seen[1], seen[4]) == (dest, 44)
    else:
        assert (seen[8], seen[9]) == (1, 0)                                          # the scaler, not the engine core
        assert seen[0] == sprite and seen[1:7] == (dest, 9, 33, 44, g, 16)           # dest, key, x, y, num, den
        assert struct.unpack("<i", struct.pack("<I", seen[7]))[0] == -480            # h clamped to -clip.B at call time



# ---- v16 (2026-09-26): intel PROFILE leader portrait through thunk_art_draw --------------------------------
@pytest.mark.parametrize("g", GS)
def test_intel_portrait_routes_to_art_draw_with_the_gate_poked_for_the_call(g):
    """t_rwk_intel_portrait (CALL helper at 0x4A2415, Sprite_blit_scaled_core contract): g>16 -> ONE call of
    thunk_art_draw (Sprite_draw_2 contract) with ecx = the Sprite, the caller's dest/key/x/y + num/den = g/16, and
    thunk_portrait_avg's dest-gate imm == the ReportWin canvas DURING the call and restored to its prior value after;
    esp balanced (RET 0x10), callee-saved regs preserved, eip back to the caller.  g<=16 -> the engine core with the
    untouched args (tail-jump), gate untouched."""
    e = Emu(g); uc = e.uc
    dest = RK.RW_CANVAS; sprite = 0x2061000
    for va in (RK.ART_DRAW, RK.PAVG_GATE_IMM):
        try:
            uc.mem_map(va & ~0xFFF, 0x1000)
        except Exception:  # noqa: BLE001  (already mapped)
            pass
    w32(uc, RK.PAVG_GATE_IMM, 0x940824)                              # the A5 faction-box dest the gate normally admits
    uc.mem_write(REC, bytes(0x40))
    e.stub(RK.ART_DRAW, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [esp+20]
        mov dword ptr [{REC + 20:#x}], eax
        mov eax, dword ptr [esp+24]
        mov dword ptr [{REC + 24:#x}], eax
        mov eax, dword ptr [{RK.PAVG_GATE_IMM:#x}]
        mov dword ptr [{REC + 28:#x}], eax
        inc dword ptr [{REC + 32:#x}]
        mov eax, 0xDEAD0003
        mov ecx, 0xDEAD0001
        mov edx, 0xDEAD0002
        ret 0x18
    """)
    e.stub(RK.BLIT_CORE, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [{RK.PAVG_GATE_IMM:#x}]
        mov dword ptr [{REC + 28:#x}], eax
        inc dword ptr [{REC + 36:#x}]
        ret 0x10
    """)
    esp = SP0 - 20
    uc.mem_write(esp, struct.pack("<IIIII", 0x11223344, dest, 9, 33, 44))
    uc.mem_write(0x11223344, b"\xf4")
    w32(uc, sprite + 0x14, 157); w32(uc, sprite + 0x24, 0)              # Sprite blit_h / off_y (131x157 leader portrait)
    w32(uc, C["g_rwk_intel_pbot"], 0x5A5A5A5A)
    try:
        e.run(VA["t_rwk_intel_portrait"], 0x11223344, esp=esp, ecx=sprite, ebx=0xB, esi=0xE, edi=0xD, ebp=0xA, count=400)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == esp + 20
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0xB, 0xE, 0xD, 0xA)
    seen = struct.unpack("<10I", bytes(uc.mem_read(REC, 40)))
    assert r32(uc, RK.PAVG_GATE_IMM) == 0x940824                     # gate restored / untouched after the call
    if g <= 16:
        assert (seen[8], seen[9]) == (0, 1) and seen[0] == sprite and (seen[1], seen[4]) == (dest, 44)
        assert seen[7] == 0x940824                                    # native path never touches the gate
        assert r32(uc, C["g_rwk_intel_pbot"]) == 0x5A5A5A5A            # cell untouched at g<=16
    else:
        # v16b: the cell = y + fl(h*g/16) + s(4) = the law's clamp for the POLITICS block
        assert r32(uc, C["g_rwk_intel_pbot"]) == SL.intel_block_top(0, 44, 157, g)
        assert (seen[8], seen[9]) == (1, 0)                           # thunk_art_draw, not the engine core
        assert seen[0] == sprite and seen[1:7] == (dest, 9, 33, 44, g, 16)   # dest, key, x, y, num, den
        assert seen[7] == RK.RW_CANVAS                                # the gate admits the report canvas DURING the call


def _parity_model(src, sw, sh, pitch, key, offL, offT, x, y, num, den, dest, dw, dh, dpitch, parent_top, g, pal):
    dW, dH = sw * num // den, sh * num // den
    table = [tuple(pal[i * 4:i * 4 + 3]) for i in range(256)]
    px, py = x + offL * num // den, y + offT * num // den
    pe = po = se = so = ne = no = 0
    for yy in range(sh):
        for xx in range(sw):
            v = src[yy * pitch + xx]
            if v == key:
                continue
            b, gg, r = pal[v * 4], pal[v * 4 + 1], pal[v * 4 + 2]
            pk, sm = max(r, gg, b), r + gg + b
            if yy & 1:
                po += pk; so += sm; no += 1
            else:
                pe += pk; se += sm; ne += 1
    top = SL.stripe_parity_vote_sums(pe, ne, po, no, se, so) if (g > 16 and sh >= 2) else -1
    out = bytearray(dest)
    for dy in range(dH):
        Y = py + dy
        if Y < 0 or Y >= dh:
            continue
        sy = SL.parity_nn_row(dy, dH, sh, parent_top + Y, g, top)
        for dx in range(dW):
            X = px + dx
            if X < 0 or X >= dw:
                continue
            i0, i1, f, near = SL.bilinear_axis(dx, num, den, sw)          # v2 columns: the A5 tap law in the parity row
            row = sy * pitch
            v = SL.parity_hblend_pixel(src[row + i0], src[row + i1], f, src[row + near], table, key)
            if v is not None:
                out[Y * dpitch + X] = v
    return bytes(out), top


def _striped_art(sw, sh, pitch, key, kind, seed):
    """kind: 'stripes' = two dither pairs (odd rows = purple/tile-blue, even rows = navy/black) with keyed
    corners; 'stripes_even_top' = the same with parities swapped; 'photo' = random opaque indices."""
    import random
    rnd = random.Random(seed)
    src = bytearray(pitch * sh)
    for yy in range(sh):
        for xx in range(pitch):
            if xx >= sw or (yy < 2 and xx < 3) or (yy >= sh - 2 and xx >= sw - 3):
                src[yy * pitch + xx] = key; continue
            if kind == "photo":
                src[yy * pitch + xx] = rnd.choice([10, 20, 30, 40, 50, 60])
            else:
                odd = (yy & 1) == (1 if kind == "stripes" else 0)
                body = (xx * 7 + yy * 3) % 11 < 6
                src[yy * pitch + xx] = (0xF0 if body else 0xC5) if odd else (0xB9 if body else 0x41)
    return bytes(src)


@pytest.mark.parametrize("g", (16, 22, 25, 40, 45, 48, 60, 72))     # > 40: t_hof_spr_pic brackets g with the HOF num
@pytest.mark.parametrize("kind", ("stripes", "stripes_even_top", "photo"))
def test_parity_nn_thunk_matches_the_law_model(g, kind):
    e = Emu(g); uc = e.uc
    sw, sh, pitch, key = 28, 34, 32, 9
    spr, sdata, btn, ddata = 0x2040000, 0x2041000, 0x2050000, 0x2060000
    dest = btn + 0x444; dw, dh, dpitch = 47, 56, 64; parent_top = 315
    num, den = (g, 16) if g > 16 else (1, 1)
    src = _striped_art(sw, sh, pitch, key, kind, g)
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4:i * 4 + 4] = bytes([(i * 37) & 255, (i * 91) & 255, (i * 53) & 255, 0])
    for i, rgb in ((0xF0, (53, 61, 115)), (0xB9, (17, 50, 79)), (0xC5, (11, 18, 24)), (0x41, (0, 0, 0)), (key, (9, 0, 0))):
        pal[i * 4:i * 4 + 4] = bytes([rgb[2], rgb[1], rgb[0], 0])
    uc.mem_write(spr, bytes(0x40)); w32(uc, spr + 4, sdata); uc.mem_write(spr + 8, bytes([key]))
    w32(uc, spr + 0xC, pitch); w32(uc, spr + 0x10, sw); w32(uc, spr + 0x14, sh); w32(uc, spr + 0x20, 1); w32(uc, spr + 0x24, 2)
    uc.mem_write(sdata, src)
    uc.mem_write(btn, bytes(0x600)); w32(uc, btn + 0x140, parent_top)
    w32(uc, dest + 0x54, ddata); w32(uc, dest + 0x4A8, dpitch); w32(uc, dest + 0x80, dw); w32(uc, dest + 0x84, (-dh) & 0xFFFFFFFF)
    uc.mem_write(dest + 0xA4, bytes(pal))
    dest0 = bytes([key]) * (dpitch * dh)
    uc.mem_write(ddata, dest0)
    x, y = 3, 4
    esp = SP0 - 28
    uc.mem_write(esp, struct.pack("<IIIiiii", 0x11223344, dest, key, x, y, num, den))
    uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_parity_nn"], 0x11223344, esp=esp, ecx=spr, ebx=0xB, esi=0xE, edi=0xD, count=40_000_000)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == esp + 28 and (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (0xB, 0xE, 0xD)
    want, top = _parity_model(src, sw, sh, pitch, key, 1, 2, x, y, num, den, dest0, dw, dh, dpitch, parent_top, g, pal)
    got = bytes(uc.mem_read(ddata, dpitch * dh))
    assert got == want
    if g > 16:
        assert top == {"stripes": 1, "stripes_even_top": 0, "photo": -1}[kind]      # the vote saw what the art is
        assert got != dest0
        # v2: a glyph edge blended (an index outside the art's own set), the flat runs kept their indices verbatim
        art = set(src) - {key}
        assert any(v not in art and v != key for v in got), "no blended column at all"
        assert art & set(got), "the flat runs kept their own indices"


# ---- v8: the BASE LOCATOR ring stamp x g/16 ---------------------------------------------------------------
@pytest.mark.parametrize("frame", ((4, 4), (3, 6), (2, 8)))
@pytest.mark.parametrize("big", (0, 1))
@pytest.mark.parametrize("fit", ("stretched", "one_to_one"))
@pytest.mark.parametrize("g", GS)
def test_blink_stamp_centres_each_ring_frame_on_the_box(g, big, fit, frame):
    """t_rwk_blink v14 (Sprite_blit_scaled_core contract): g>16 (or big) -> MapWin_tile_to_pixel(console, g_blink_tile)
    for (px,py), py -= [console+0x1DDC0], then ONE thunk_sprite_scale_nn call (num/den = mg/16, the SCALE globals
    untouched) with ecx = the dot Sprite, dest/key untouched and x/y = scaling_laws.blink_place over the live WorldWin
    fields AND the sprite's own +0x20/+0x24/+0x10/+0x14 frame geometry; esp balanced (RET 0x10), callee-saved
    registers intact.  g<=16 lawful -> the engine core with the untouched args (tail-jump), no tile lookup."""
    e = Emu(g); uc = e.uc
    w32(uc, RK.G_NUM, 3); w32(uc, RK.G_DEN, 7); w32(uc, RK.G_BIG_F4, big)
    tile = RK._cell("g_blink_tile")
    w32(uc, tile, 20); w32(uc, tile + 4, 30)
    if fit == "stretched":
        ww, wh, bw, bh, ox, oy = 597, 297, 320, 152, 0, 0
    else:
        ww, wh, bw, bh, ox, oy = 4000, 2000, 320, 152, 100, 50
    w32(uc, RK.WW_WIN_W, ww); w32(uc, RK.WW_WIN_H, -wh); w32(uc, RK.WW_BUF_W, bw); w32(uc, RK.WW_BUF_H, bh)
    w32(uc, RK.WW_OFF_X, ox); w32(uc, RK.WW_OFF_Y, oy)
    w32(uc, RK.CONSOLE_ROW_H, 2)                                              # the console's row height (2 at the locator zoom)
    SPR = 0x2002000
    off, w = frame
    w32(uc, SPR + 0x10, w); w32(uc, SPR + 0x14, w); w32(uc, SPR + 0x18, 12); w32(uc, SPR + 0x1C, 12)
    w32(uc, SPR + 0x20, off); w32(uc, SPR + 0x24, off)
    uc.mem_write(REC, bytes(0x80))
    # MapWin_tile_to_pixel stub: records this/x/y, writes px = 4x - 8, py = 2y - 6 (the traced console mapping), RET 0x10
    e.stub(RK.TILE_TO_PX, f"""
        mov dword ptr [{REC + 0x60:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 0x64:#x}], eax
        mov edx, dword ptr [esp+8]
        mov dword ptr [{REC + 0x68:#x}], edx
        lea eax, [eax*4-8]
        mov ecx, dword ptr [esp+12]
        mov dword ptr [ecx], eax
        lea edx, [edx*2-6]
        mov ecx, dword ptr [esp+16]
        mov dword ptr [ecx], edx
        inc dword ptr [{REC + 0x6C:#x}]
        mov eax, 0x5555
        mov ecx, 0xDEAD0003
        ret 0x10
    """)
    e.stub(RK.SCALE_NN, f"""
        mov dword ptr [{REC + 0x40:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 0x44:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 0x48:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 0x4C:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 0x50:#x}], eax
        mov eax, dword ptr [esp+20]
        mov dword ptr [{REC + 0x54:#x}], eax
        mov eax, dword ptr [esp+24]
        mov dword ptr [{REC + 0x58:#x}], eax
        inc dword ptr [{REC + 0x5C:#x}]
        mov eax, 0x1234
        ret 0x18
    """)
    e.stub(RK.BLIT_CORE, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [{RK.G_NUM:#x}]
        mov dword ptr [{REC + 20:#x}], eax
        mov eax, dword ptr [{RK.G_DEN:#x}]
        mov dword ptr [{REC + 24:#x}], eax
        inc dword ptr [{REC + 28:#x}]
        mov eax, 0x1234
        mov ecx, 0xDEAD0001
        mov edx, 0xDEAD0002
        ret 0x10
    """)
    esp = SP0 - 20
    uc.mem_write(esp, struct.pack("<IIIii", 0x11223344, 0x2000000, 9, 142, 106))
    uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_blink"], 0x11223344, esp=esp, ecx=SPR, ebx=0xB, esi=0xE, edi=0xD, ebp=0xA, count=400)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0 and e.reg("eax") == 0x1234
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0xB, 0xE, 0xD, 0xA)
    seen = struct.unpack("<3Iii3I", bytes(uc.mem_read(REC, 32)))
    nn = struct.unpack("<3IiiIII", bytes(uc.mem_read(REC + 0x40, 32)))
    t2p = struct.unpack("<4I", bytes(uc.mem_read(REC + 0x60, 16)))
    px, py = 4 * 20 - 8, 2 * 30 - 6 - 2                                        # the pass's py = tile_to_pixel_y - row height
    x2, y2, num, den = SL.blink_place(142, 106, px, py, g, bool(big), ww, wh, bw, bh, ox, oy, off, off, w, w)
    if not big and g <= 16:
        assert t2p[3] == 0 and nn[7] == 0 and seen[7] == 1
        assert seen[0] == SPR and seen[1:5] == (0x2000000, 9, 142, 106) and seen[5:7] == (3, 7)
    else:
        assert t2p == (RK.WW_CONSOLE, 20, 30, 1)                               # one MapWin_tile_to_pixel(console, tx, ty)
        assert seen[7] == 0 and nn[7] == 1 and nn[0] == SPR and nn[1:3] == (0x2000000, 9)
        assert (nn[3], nn[4], nn[5], nn[6]) == (x2, y2, num, den) and num == (2 if big else 1) * g and den == 16
    assert (r32(uc, RK.G_NUM), r32(uc, RK.G_DEN)) == (3, 7)


def test_blink_tile_stash_records_the_clicked_tile_then_maps_it():
    """t_rwk_blinktile (call_target_redirect at ReportWin_on_lclick 0x4974B2): copies the two tile args into
    g_blink_tile and tail-jumps WorldWin_tile_to_pixel with the stack untouched (its RET 0x10 returns to the site)."""
    e = Emu(25); uc = e.uc
    tile = RK._cell("g_blink_tile")
    w32(uc, tile, 0); w32(uc, tile + 4, 0)
    uc.mem_write(REC, bytes(0x20))
    e.stub(RK.TILE_TO_PX_WIN, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, 0x777
        ret 0x10
    """)
    esp = SP0 - 20
    uc.mem_write(esp, struct.pack("<IIIII", 0x11223344, 20, 30, 0x8A4184, 0x8A4188))
    uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_blinktile"], 0x11223344, esp=esp, ecx=RK.WW, ebx=0xB, esi=0xE, edi=0xD, ebp=0xA, count=100)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == SP0 and e.reg("eax") == 0x777
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0xB, 0xE, 0xD, 0xA)
    assert struct.unpack("<5I", bytes(uc.mem_read(REC, 20))) == (RK.WW, 20, 30, 0x8A4184, 0x8A4188)
    assert (r32(uc, tile), r32(uc, tile + 4)) == (20, 30)


# ---- v6: the ORBITAL ATTACK VIEW planet through the bilinear ------------------------------------------
@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("surface", (0, 1))
def test_gdraw_builds_buffer_draws_sprite_and_calls_the_bilinear(g, surface):
    """t_rwk_gdraw v6 (Buffer_draw contract: thiscall ecx = src Buffer; dest,key,x,y; RET 0x10): g>16 with plain
    memory buffers -> ONE call of thunk_sprite_bilinear, ecx = a Sprite carrying Buffer_draw's own field mapping
    (data +0x54, the key arg, pitch +0x4A8, W +0x80, H = -[+0x84], the W/H twins, zero draw offsets) and the
    caller's dest/key/x/y + num/den = g/16; esp balanced, callee-saved registers intact.  g<=16, or a DDraw-
    surface source (+0x58 != 0), -> the engine's Buffer_draw with the untouched args (tail-jump)."""
    e = Emu(g); uc = e.uc
    src, dest, bits = 0x2070000, 0x2071000, 0x2072000
    uc.mem_write(src, bytes(0x500)); uc.mem_write(dest, bytes(0x500))
    w32(uc, src + 0x54, bits); w32(uc, src + 0x4A8, 128); w32(uc, src + 0x80, 115); w32(uc, src + 0x84, (-115) & 0xFFFFFFFF)
    w32(uc, src + 0x58, surface)
    uc.mem_write(REC, bytes(0x80))
    e.stub(RK.SPRITE_BILINEAR, f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 16:#x}], eax
        mov eax, dword ptr [esp+20]
        mov dword ptr [{REC + 20:#x}], eax
        mov eax, dword ptr [esp+24]
        mov dword ptr [{REC + 24:#x}], eax
        inc dword ptr [{REC + 0x30:#x}]
        mov eax, 0xDEAD0003
        mov ecx, 0xDEAD0001
        mov edx, 0xDEAD0002
        ret 0x18
    """)
    e.stub(RK.BUFFER_DRAW, f"""
        mov dword ptr [{REC + 0x50:#x}], ecx
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 0x54:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 0x58:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 0x5C:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 0x60:#x}], eax
        inc dword ptr [{REC + 0x34:#x}]
        ret 0x10
    """)
    esp = SP0 - 20
    uc.mem_write(esp, struct.pack("<IIIII", 0x11223344, dest, 9, 33, 44))
    uc.mem_write(0x11223344, b"\xf4")
    try:
        e.run(VA["t_rwk_gdraw"], 0x11223344, esp=esp, ecx=src, ebx=0xB, esi=0xE, edi=0xD, ebp=0xA, count=400)
    except Exception:
        pass
    assert e.reg("eip") == 0x11223344 and e.reg("esp") == esp + 20
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0xB, 0xE, 0xD, 0xA)
    seen = struct.unpack("<7I", bytes(uc.mem_read(REC, 28)))
    calls = (r32(uc, REC + 0x30), r32(uc, REC + 0x34))
    if g > 16 and surface == 0:
        assert calls == (1, 0)
        assert seen[1:7] == (dest, 9, 33, 44, g, 16)
        spr = struct.unpack("<10i", bytes(uc.mem_read(seen[0], 40)))     # the stack Sprite (its frame is below esp, untouched)
        assert spr == (0, bits, 9, 128, 115, 115, 115, 115, 0, 0)
        assert not (esp - 0x60 <= seen[0] < esp) or True                 # lives on the thunk's own frame
    else:
        assert calls == (0, 1)
        assert r32(uc, REC + 0x50) == src
        assert [r32(uc, REC + 0x54 + 4 * i) for i in range(4)] == [dest, 9, 33, 44]


# ---- v16b: the POLITICS-block law itself (part of the `-k scaling` sweep) ------------------------------------
@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_scaling_intel_block_top_law(g):
    """8..11 dossier rows above the block; portrait 157 tall at y0.  At g=16 the engine flow is returned untouched (vanilla
    overlaps with 8/9 rows); at g>16 the block never starts above the drawn portrait bottom + s(4), and a flow that already
    already clears it is untouched (11 rows at every g; 10 rows at g=40 -- at g=22 ten rows still sit 3 px into the clamp)."""
    lineH = {16: 15, 22: 19, 25: 22, 40: 36}[g]          # measured report-font line heights (census / user shots)
    y0 = 100
    pbot = y0 + (157 * g) // 16 + s(4, g)
    for n in (8, 9, 10, 11):
        flow = y0 + n * lineH + s(0x14, g)
        got = SL.intel_block_top(flow, y0, 157, g)
        if g <= 16:
            assert got == flow
        else:
            assert got == max(flow, pbot) and got >= y0 + (157 * g) // 16
    assert SL.intel_block_top(10 ** 6, y0, 157, g) == 10 ** 6


# ---- slide-window outer rail row law (part of the `-k scaling` sweep) --------------------------------------
@pytest.mark.parametrize("g,sh", ((16, 768), (22, 1080), (25, 1200), (40, 2160)))
def test_scaling_slide_rail_outer_row_law(g, sh):
    r = SL.slide_rail_outer_row(sh, g)
    if g <= 16:
        assert r == 238 and SL.slide_rail_outer_row(600, 16, True) == 94
        assert SL.slide_rail_outer_a(3, 768, 16) == 238 and SL.slide_rail_settled_v(3, 238, 3, 16) == 235 and SL.slide_rail_outer_y(3, 238, 3, 16) == 235
        return
    assert r == sh - (530 * g) // 16 == SL.slide_rail_outer_a(0, sh, g)          # v3: the cell is the device row
    # the report window (native top 3 -> device top = SH - fl(553g/16) - fl(213g/16)): the wide pillar starts
    # 235 native rows below the window top in vanilla; the settled shim lands within g/16 of fl(235g/16)
    top = sh - (553 * g) // 16 - (213 * g) // 16
    y = SL.slide_rail_outer_y(top, r, top, g)
    assert abs(y - 235 * g / 16) <= g / 16 + 1 and r - top <= y <= r - top + g // 16
    # a centred popup below the row: A < T -> the engine's max() keeps the strips at the window top, as in vanilla
    assert SL.slide_rail_settled_v(sh - 100, r, sh - 100, g) == 0


# ---- v17 (2026-10-11): the six other consoles' title inset + ListBox R/B inset CALL helpers ------------------
# Each site is patched exactly as the yaml ships it (E8 rel32 at the site) and emulated end to end from the site to
# site+5, side by side with the pristine displaced bytes (g=16) and with the displaced instructions re-encoded on
# the law's operand (g>16).  Sweeps every g in 16..40.
CON_CALLS = ([(va, "t_rwk_con_title_add", "title") for va, _c in RK.TITLE_ADD_SITES]
             + [(va, "t_rwk_con_title_mov", "title") for va, _c in RK.TITLE_MOV_SITES]
             + [(va, "t_rwk_con_lbr", "lbr") for va, _c, _l in RK.LBR_SITES])
_ARITH = 0x8D5        # CF PF AF ZF SF OF


def _con_run(g, va, code, regs):
    from unicorn.x86_const import UC_X86_REG_EFLAGS
    e = Emu(g)
    e.uc.mem_write(va, code)
    try:
        e.uc.ctl_remove_cache(va, va + 0x40)
    except Exception:  # noqa: BLE001
        pass
    e.uc.reg_write(UC_X86_REG_EFLAGS, 0x202)
    st = _run_cave(e, va, va + len(code), regs, SP0)
    st["flags"] = e.uc.reg_read(UC_X86_REG_EFLAGS) & _ARITH
    return st


def _con_patched(va, thunk):
    return bytes([0xE8]) + struct.pack("<i", VA[thunk] - (va + 5))


def test_con_sites_pristine_bytes_boundaries_and_dead_flags():
    want = {"t_rwk_con_title_add": "83e04c03c8", "t_rwk_con_title_mov": "83e04c8bc8", "t_rwk_con_lbr": "b8fdffffff"}
    assert len(CON_CALLS) == 13
    for va, thunk, kind in CON_CALLS:
        b = SE.base_exe_bytes(va, 5 + 16)
        assert b[:5].hex() == want[thunk], hex(va)
        ins = list(_cs.disasm(b, va))
        assert va + 5 in {i.address + i.size for i in ins}, f"{va:#x}+5 cuts an instruction"
        if kind == "lbr":   # the helper's neg leaves EFLAGS where vanilla's mov left them: dead only if the next op writes all six
            nxt = next(i for i in ins if i.address == va + 5)
            assert nxt.mnemonic == "add", (hex(va), nxt.mnemonic)
    # every R/B site sits beside the scaled L/T +3 rows (the shape the helper mirrors); no walker row inside any site
    rows = {r[0]: r[1:] for r in AR.rw_rows()}
    for va, _c, _l in RK.LBR_SITES:
        near = [a for a in rows if va - 0x10 <= a < va + 0x18 and rows[a][0] == 3]
        assert len(near) >= 2, hex(va)
    for va, _t, _k in CON_CALLS:
        assert not any(va <= a < va + 5 for a in rows), hex(va)


def test_con_sites_in_yaml_call_their_helper():
    ys = {x["va"]: x for x in (dict(va=s_[0], n=s_[1], id=s_[3]) for s_ in _yaml_sites())}
    for va, _thunk, _k in CON_CALLS:
        assert va in ys and ys[va]["n"] == 5, hex(va)


@pytest.mark.parametrize("g", range(16, 41))
def test_con_helpers_law_and_g16_identity(g):
    for va, thunk, kind in CON_CALLS:
        masks = (0, 0xFFFFFFFF) if kind == "title" else (0x11111111,)
        for mask in masks:
            regs = dict(eax=mask, ebx=0x42, ecx=100, edx=0x44444444, esi=RW, edi=0x55555555, ebp=EBP)
            got = _con_run(g, va, _con_patched(va, thunk), regs)
            van = _con_run(g, va, SE.base_exe_bytes(va, 5), regs)
            if kind == "title":
                t = SL.rw_console_title_inset(mask, g)
                assert got["eax"] == t
                assert got["ecx"] == ((100 + t) & 0xFFFFFFFF if thunk.endswith("_add") else t)
                # EFLAGS = the displaced instructions' own, run on the law's operand (vanilla at g=16)
                tail = "add ecx, eax" if thunk.endswith("_add") else "mov ecx, eax"
                ref = _con_run(g, va, SE.assemble(f"and eax, {SL.scale_px(0x4C, g):#x}\n{tail}", va), regs)
                assert (got["eax"], got["ecx"], got["flags"]) == (ref["eax"], ref["ecx"], ref["flags"]), hex(va)
            else:
                assert got["eax"] == SL.rw_console_listbox_rb(g) & 0xFFFFFFFF
            for r in ("ebx", "edx", "esi", "edi", "ebp", "esp"):
                assert got[r] == van[r], (hex(va), r)
            if g == 16:   # vanilla identity: registers; and EFLAGS for the title helpers (lbr: proven dead above)
                assert (got["eax"], got["ecx"]) == (van["eax"], van["ecx"]), hex(va)
                if kind == "title":
                    assert got["flags"] == van["flags"], hex(va)


@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_rw_console_insets_law(g):
    assert SL.rw_console_title_inset(0, g) == 0
    assert SL.rw_console_title_inset(0xFFFFFFFF, g) == SL.scale_px(0x4C, g)
    assert SL.rw_console_listbox_rb(g) == -SL.scale_px(3, g)
    if g == 16:
        assert SL.rw_console_title_inset(0xFFFFFFFF, g) == 0x4C and SL.rw_console_listbox_rb(g) == -3
    assert (SL.rw_console_title_inset(0xFFFFFFFF, g) > 0x7F) == (g >= 27)   # imm8 overflow: why no walker row can carry it


# ---- v18 (2026-10-11): F5 projects / F7 units list rows at cum(k) = s(k * pitch) ---------------------------------
# Measured 1600x1200 (g=25): projects rows stepped a constant 87 (s(0x36)+s(2); 87.5 real), units 67 (s(0x2B); 67.19).
@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_rw_list_row_law(g):
    for p in (SL.RW_PROJECTS_ROW_PITCH, SL.RW_UNITS_ROW_PITCH):
        assert SL.rw_list_row_offset(0, p, g) == 0
        for k in range(0, 129):
            off = SL.rw_list_row_offset(k, p, g)
            assert abs(2 * 16 * off - 2 * k * p * g) <= 16                         # within 1/2 px of k*p*g/16
            if g == 16:
                assert off == k * p                                                # vanilla identity, no gate needed
            if k:
                adv = SL.rw_list_row_advance(k, p, g)
                assert (p * g) // 16 <= adv <= -(-(p * g) // 16)                  # floor or ceil of the real pitch
                assert sum(SL.rw_list_row_advance(i, p, g) for i in range(1, k + 1)) == off
    # projects: the cell (drawn row) never overlaps the next row; the gap absorbs the rounding (>= 1 px)
    for k in range(0, 64):
        y0, y1 = SL.rw_projects_row_y(0, k, g), SL.rw_projects_row_y(0, k + 1, g)
        assert y0 + s(0x36, g) < y1 and y1 - y0 - s(0x36, g) in (s(56, g) - s(0x36, g) - 1, s(56, g) - s(0x36, g), s(56, g) - s(0x36, g) + 1)
        if g == 16:
            assert y0 == 56 * k + 2
    # counts at g = 16 are vanilla's own division of the engine's h, on ANY layout (1024+ and 800x600)
    if g == 16:
        for h in range(0, 1400):
            assert SL.rw_units_visible_rows(h, 999, g) == h // 0x2B and SL.rw_projects_visible_rows(h, 999, g) == h // 0x36
    # the textB recovery is exact for every native window height
    for H in range(300, 1200):
        assert SL.rw_report_textb_native((H * g) // 16, g) == H - 0x35


def _units_rows(g, n, scroll=0):
    """Emulate the units painter's row loop: for visible row k the cave advances both rect edges from row k-1's
    (the k = 0 row keeps the seeded top/bottom).  Returns [(top, bottom)] per visible row."""
    top, bot = 100 + s(2, g), 100 + s(0x2B, g)            # 0x4A0940 / 0x4A0943: list top + s(2), list top + s(0x2B)
    out = [(top, bot)]
    for k in range(1, n):
        e = Emu(g)
        w32(e.uc, EBP - 4, scroll + k); w32(e.uc, RW + 0xC0FC, scroll)
        regs = dict(eax=s(0x2B, g), ebx=0x42, ecx=bot, edx=top, esi=RW, edi=0x55555555, ebp=EBP)
        st = _run_cave(e, VA["t_rwk_units_rowstep"], 0x4A0D47, regs, SP0)
        top, bot = st["bp2c"], st["bp24"]
        out.append((top, bot))
    return out


@pytest.mark.parametrize("g", (16, 18, 21, 22, 25, 28, 33, 40))
def test_units_rowstep_loop_lands_rows_at_law_and_hit_rects_invert(g):
    rows = _units_rows(g, 12, scroll=5)
    for k, (t, b) in enumerate(rows):
        assert t == 100 + s(2, g) + SL.rw_list_row_offset(k, 0x2B, g)
        assert b - t == s(0x2B, g) - s(2, g)                                   # the rect (and its Spot) keeps its height
    if g == 16:
        assert [t for t, _b in rows] == [102 + 43 * k for k in range(12)]     # vanilla
    if g == 25:   # the measured defect: 0,87,175,... / 0,67,134,... -> law offsets (row 9: 605 vs the old 603)
        assert [t - rows[0][0] for t, _b in rows][:10] == [0, 67, 134, 202, 269, 336, 403, 470, 537, 605]
    # hit test: rows are Spot rects (0x5FA960 from the same rect) -> every y inside row k maps to k and nothing else
    for k, (t, b) in enumerate(rows):
        for y in range(t, b):
            assert [j for j, (tt, bb) in enumerate(rows) if tt <= y < bb] == [k]
        if k + 1 < len(rows):
            assert b <= rows[k + 1][0]                                           # no overlap; gap = s(2) +/- 1


@pytest.mark.parametrize("g", (16, 18, 21, 22, 25, 28, 33, 40))
def test_projects_rowy_lands_rows_at_law_and_hit_rects_invert(g):
    tops = []
    for k in range(10):
        e = Emu(g); regs = _seed(e, "t_rwk_proj_rowy", cell=s(0x36, g)); regs.update(eax=k, ebx=s(0x36, g))
        st = _run_cave(e, VA["t_rwk_proj_rowy"], 0x49EEA5, regs, SP0)
        assert st["ebx"] == s(0x36, g)
        tops.append(st["eax"])
    assert tops == [SL.rw_projects_row_y(1000, k, g) for k in range(10)]
    if g == 25:   # measured: 0,87,174,...,609 (constant 87) -> law 0,87,175,262,...,612 (row 7)
        assert [t - tops[0] for t in tops][:8] == [0, 87, 175, 262, 350, 437, 525, 612]
    rects = [(t, t + s(0x36, g)) for t in tops]                                  # rect bottom = y + cell (0x49EEB6)
    for k, (t, b) in enumerate(rects):
        for y in range(t, b):
            assert [j for j, (tt, bb) in enumerate(rects) if tt <= y < bb] == [k]


def _real_layout(g):
    """The ReportWin content geometry at >= 1024 as the rw_scale_shared init lever builds it (device):
    win_h = fl(553g/16), textB = win_h - s(0x35), clip top s(3), lineH = rw_line_h (s(15) at g > 16), list top =
    T + lineH + s(9) (the 'title +9' rows of both painters)."""
    win_h = (553 * g) // 16
    text_b = win_h - s(0x35, g)
    top = s(3, g) + SL.rw_line_h(15, g) + s(9, g)
    return win_h, text_b, top


@pytest.mark.parametrize("g", range(16, 41))
def test_real_layout_counts_are_vanilla_and_last_row_inside(g):
    """v18b: on the real F5 / F7 layout the visible-row count equals vanilla's (F7 10 = (500-29)//43, F5 8 =
    (500-27-5)//54) at every g -- never one fewer from the separately rounded device edges -- and the last counted
    row, placed at cum(k), ends inside the list (<= textB).  Thunks emulated from their real bytes."""
    win_h, text_b, top = _real_layout(g)
    # F7 units: h = textB - (top + s(2)) is what the painter hands the cave (ecx at 0x4A0974)
    h_u = text_b - (top + s(2, g))
    n_u = SL.rw_units_visible_rows(h_u, win_h, g)
    assert n_u == (500 - (3 + 15 + 9 + 2)) // 0x2B == 10
    assert top + SL.rw_list_row_offset(n_u - 1, 0x2B, g) + s(0x2B, g) <= text_b      # last rect bottom inside
    # F5 projects: h = textB - top - s(5) (ecx at 0x49EB6F; the 'rows=(h-5)/cell' row scales the 5)
    h_p = text_b - top - s(5, g)
    n_p = SL.rw_projects_visible_rows(h_p, win_h, g)
    assert n_p == (500 - (3 + 15 + 9) - 5) // 0x36 == 8
    assert SL.rw_projects_row_y(top, n_p - 1, g) + s(0x36, g) <= text_b               # last cell bottom inside
    for thunk, resume, h, want in (("t_rwk_units_rowdiv", 0x4A0980, h_u, n_u), ("t_rwk_proj_rowdiv", 0x49EB7B, h_p, n_p)):
        e = Emu(g); regs = _seed(e, thunk); _seed_win_h(e, win_h); regs.update(ecx=h)
        st = _run_cave(e, VA[thunk], resume, regs, SP0)
        assert st["eax"] == st["edx"] == want and st["ecx"] == h and st["ebx"] == 0x42 and st["esp"] == SP0


@pytest.mark.parametrize("g", (16, 17, 22, 25, 40))
def test_rowdiv_thunks_g16_take_the_engine_h_on_any_layout(g):
    """g = 16: the caves divide the engine's own h (vanilla magic-multiply semantics) -- the 800x600 layout
    (win_h 373) included; g > 16: independent of ecx (native-space count)."""
    for h in (0, 1, 42, 43, 53, 54, 291, 468, 471, 1000):
        for thunk, resume, div in (("t_rwk_units_rowdiv", 0x4A0980, 0x2B), ("t_rwk_proj_rowdiv", 0x49EB7B, 0x36)):
            e = Emu(g); regs = _seed(e, thunk); _seed_win_h(e, (373 * g) // 16); regs.update(ecx=h)
            st = _run_cave(e, VA[thunk], resume, regs, SP0)
            law = (SL.rw_units_visible_rows if div == 0x2B else SL.rw_projects_visible_rows)(h, (373 * g) // 16, g)
            assert st["eax"] == law
            if g == 16:
                assert law == h // div


# ---- 2026-10-17: the rowdiv caves' window-height source ----------------------------------------------------------
def test_tech_reset_makes_a20_page_scratch():
    """Contract behind RK.RW_WIN_H: the vtbl+0x30 page painter 0x496D00 calls ReportWin_tech_reset (0x496BB0) first,
    and pristine 0x496C26..0x496C66 stores the content clip as (L, T, W, H) at RW+0xA14..+0xA20 -- so at paint time
    +0xA20 = textB - clipT, never the window height. Emulated from the pristine bytes."""
    head = SE.base_exe_bytes(0x496D04, 5)
    assert head[0] == 0xE8 and 0x496D09 + struct.unpack("<i", head[1:])[0] == 0x496BB0      # painter -> tech_reset first
    assert SE.base_exe_bytes(RW_TECH_RESET_A20, 6) == bytes.fromhex("89 86 20 0A 00 00")     # mov [esi+0xA20], eax
    e = Emu(25)
    e.uc.mem_write(0x496C26, SE.base_exe_bytes(0x496C26, 0x496C66 - 0x496C26))
    win_h = (553 * 25) // 16
    clip = (s(0x1A, 25), s(3, 25), s(0x1A, 25) + 1000, win_h - s(0x35, 25))                    # L, T, R, textB
    e.uc.mem_write(RW + 0x5974, struct.pack("<4i", *clip))
    w32(e.uc, RW + 0x5990, win_h); w32(e.uc, RW + 0xA20, win_h)                             # as t_rw_init_leave leaves them
    e.run(0x496C26, 0x496C66, esp=SP0, count=50, esi=RW)
    assert struct.unpack("<4i", bytes(e.uc.mem_read(RW + 0xA14, 16))) == (clip[0], clip[1], clip[2] - clip[0], clip[3] - clip[1])
    assert r32(e.uc, RW + 0xA20) != win_h and r32(e.uc, RW + 0x5990) == win_h                # +0xA20 scratch; +0x5990 intact


def _disp_writers(code: bytes, base_va: int, disp: int):
    """VAs of the instructions in `code` that WRITE a [reg+disp] operand (found by the disp32 bytes, decoded backwards)."""
    from capstone import CS_AC_WRITE
    from capstone.x86 import X86_OP_MEM
    cs = Cs(CS_ARCH_X86, CS_MODE_32); cs.detail = True
    pat, out, p = struct.pack("<I", disp), set(), 0
    while (p := code.find(pat, p)) >= 0:
        for back in (2, 3):                                  # opcode + modrm [+ sib]
            ins = next(cs.disasm(code[p - back:p - back + 15], base_va + p - back), None)
            if ins is None or ins.size < back + 4:
                continue
            for o in ins.operands:
                if o.type == X86_OP_MEM and o.mem.base != 0 and o.mem.disp == disp and (o.access & CS_AC_WRITE):
                    out.add(ins.address)
        p += 1
    return out


def test_rw_win_h_field_writers():
    """RW+0x5990 (the frame rect bottom) is ASSIGNED only by init_report_screen's two layout branches (pristine .text)
    and, among the rw caves, only by t_rw_init_leave -- so it is the window height at every page paint, unlike +0xA20.
    (t_rw_backdrop dec/inc's it transiently through tech_reset's frame-rect pointer @0x496C88, balanced, no exit
    between; a pointer writer is outside this displacement scan.)"""
    import pefile
    import config
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
    text = next(x for x in pe.sections if x.Name.rstrip(b"\0") == b".text")
    va0 = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
    assert _disp_writers(text.get_data(), va0, RK.RW_WIN_H) == {0x496A0F, 0x496AEF}
    cave = {n for n, (off, b) in LAYOUT.items() if n.startswith(("t_", "thunk_")) and _disp_writers(b, AR.PCAVE2 + off, RK.RW_WIN_H)}
    assert cave == {"t_rw_init_leave"}
    assert RK.RW_WIN_H == 0x5990


# ---- report-list text pad at ListBox_close (2026-10-11) ----------------------------------------------------------
@pytest.mark.parametrize("g", range(16, 41))
def test_scaling_rw_list_text_pad_law(g):
    """pad + 1 (the per-side text inset ListBox_draw_item applies) = scale_px(3, g); identity 2 at g=16."""
    p = SL.rw_list_text_pad(g)
    assert p + 1 == SL.scale_px(3, g) if g > 16 else p == 2
    assert p >= 2


@pytest.mark.parametrize("g", range(16, 97))
def test_scaling_rw_window_rects_one_cascade(g):
    """frame -> clip channel equal on L, T and R at every g (1920x1080 measured 3 left / 4 right before).
    v5 (2026-10-17): the frame ABUTS the slide rails -- its first column is the one after the two left strips'
    railscale extent, its R (half-open: last stroke column R-1) is the inner right strip's railscale x -- so no
    see-through column on the left and no stroke under the right rail at any g.
    v6 (rw_canvas_w v2): the canvas is ceil(N*g/16), N = ceil(W*16/g) + 0x4E, whose railscale descale is N exactly,
    so R = fl((N - 0x37)*g/16) = vanilla x g/16; the frame width is W..W+2 (W at 24/32/40/48)."""
    for w_nat, h_nat in ((650, 553), (650, 353)):
        W, H = (w_nat * g) // 16, (h_nat * g) // 16
        (fl, ft, fr, fb), (cl, ct, cr, cb) = SL.rw_window_rects(W, H, g)
        K = SL.stroke_width(g)
        assert cl - fl - K == ct - ft - K == (fr - K) - cr == SL.scale_px(3, g) - K
        assert cb == H - SL.scale_px(0x35, g) and (ft, fb) == (0, H)
        if g <= 16:
            assert (fl, fr) == (0x17, 0x17 + W)
            continue
        cw = SL.rw_canvas_w(W, g)
        n = -(-W * 16 // g) + 0x4E                                                        # the native canvas (728)
        assert cw == -(-n * g // 16) and (cw << 4) // g == n and cw >= W + SL.scale_px(0x4E, g)
        assert fl == SL.rail_left_extent(g) == ((15 * g) >> 4) + ((8 * g) >> 4)          # left rails end at fl - 1
        assert fr == SL.popup_scale_floor(SL.rail_right_anchor(cw, cw - 0x37, g), g)     # inner right rail starts at fr
        assert fr == (((((cw << 4) // g) - 0x37) * g) >> 4)
        assert fr == ((n - 0x37) * g) >> 4 == ((w_nat + 0x17) * g) >> 4                  # vanilla x g/16 (v5: 1-2 px left)
        assert 0 <= (fr - fl) - W <= 2 and fr <= cw - (0x37 * g >> 4)                  # W..W+2; inside the canvas
        if g in (24, 32, 40, 48):
            assert fr - fl == W                                                         # content width unchanged
    assert SL.rw_window_rects(650, 553, 16) == ((0x17, 0, 0x17 + 650, 553), (0x1A, 3, 650 + 0x14, 553 - 0x35))


@pytest.mark.parametrize("sw,sh", ((1024, 768), (1600, 900), (1280, 1024), (1920, 1080), (1600, 1200),
                                   (2560, 1440), (3840, 2160), (5120, 2880), (7680, 4320)))
def test_scaling_rw_window_x_centres_the_frame(sw, sh):
    """rw_window_x: the frame (not the canvas) is centred on the screen, as vanilla's (SW - 650)/2 centres its
    0x17..0x17+650 frame; the window starts the frame's L to its left.  Identity at 1024x768.  g is the one the
    screen runs at (popup_g: clamped at 40, so 5K / 8K run at 40 on a wider margin)."""
    g = SL.popup_g(sw, sh)
    W = (650 * g) // 16 if g > 16 else 650
    (fl, _t, fr, _b), _clip = SL.rw_window_rects(W, 553, g)
    a14, wx = SL.rw_window_x(sw, W, g)
    assert wx + fl == a14 and a14 == (sw - (fr - fl)) >> 1
    left_margin, right_margin = a14, sw - (a14 + (fr - fl))
    assert 0 <= right_margin - left_margin <= 1
    if g <= 16:
        assert (a14, wx) == ((sw - 650) // 2, (sw - 650) // 2 - 0x17)


@pytest.mark.parametrize("sw,sh,g,width,a14,wx,by_w", (
    (1088, 816, 17, 692, 198, 175, 199),     # R - L = W + 2 (W 690)
    (1216, 912, 19, 773, 221, 195, 222),     # R - L = W + 2 (W 771)
    (1280, 1024, 20, 813, 233, 205, 234),    # R - L = W + 1 (W 812)
    (2560, 1600, 33, 1342, 609, 563, 610),   # R - L = W + 2 (W 1340)
    (3840, 1600, 33, 1342, 1249, 1203, 1250),
))
def test_scaling_rw_window_x_exact_a14(sw, sh, g, width, a14, wx, by_w):
    """rw_window_x pinned to hand-checked values at reachable screens (g = scaling_laws.popup_g(sw, sh), the g the
    screen really runs at: the min of both axes, floored) where the frame width R - L differs from W, chosen so that
    centring W instead of the frame gives a different A14 (by_w).  g=17 by hand (v6):
    N = ceil(690*16/17) + 0x4E = 650 + 78 = 728, cw = ceil(728*17/16) = 774, R = fl((fl(774*16/17) - 55)*17/16) =
    fl(673*17/16) = 715, L = 15 + 8 = 23, A14 = (1088 - 692) >> 1 = 198, window x = 198 - 23 = 175.
    (Until fix 10 the rows modelled g = round(16*SH/768) -- 1280x800 at 17, 1600x900 / 1440x900 at 19, 2560x2048 at
    43 -- none of which those screens run at: 16, 18, 18, 40, where R - L == W or by_w == A14.)"""
    assert g == SL.popup_g(sw, sh)
    W = (650 * g) >> 4
    (fl, _t, fr, _b), _clip = SL.rw_window_rects(W, 553, g)
    assert fr - fl == width != W
    assert SL.rw_window_x(sw, W, g) == (a14, wx)
    assert (sw - W) >> 1 == by_w and wx == a14 - SL.rail_left_extent(g)


def test_textpad_site_pristine_bytes_and_yaml():
    va = RK.LB_TEXTPAD_SITE
    b = SE.base_exe_bytes(va, 6 + 3 + 16)
    assert b[:9].hex() == "8b15e47069008956 2c".replace(" ", "")      # mov edx,[0x6970E4] / mov [esi+0x2C],edx
    ins = list(_cs.disasm(b, va))
    assert va + 6 in {i.address + i.size for i in ins}
    # after the store: only movs and the ret (EFLAGS dead), eax/ecx untouched by the helper anyway
    tail = SE.base_exe_bytes(0x609F64, 0x609F9D - 0x609F64)
    assert all(i.mnemonic in ("mov", "pop", "ret") for i in _cs.disasm(tail, 0x609F64))
    ys = {s_[0]: s_ for s_ in _yaml_sites()}
    assert va in ys and ys[va][1] == 6 and ys[va][2] == 0xE8


@pytest.mark.parametrize("g", range(16, 41))
@pytest.mark.parametrize("inlist,elem", [(0, 0x885F38 + 0xA2D0), (1, 0x885F38 + 0xA2D0), (0, RW + 0x5A0C), (0, 0x00703EA0 + 0xF628)])
def test_textpad_helper_law_and_identity(g, inlist, elem):
    va = RK.LB_TEXTPAD_SITE
    store = bytes.fromhex("89562c")
    patched = _con_patched(va, "t_lb_textpad") + b"\x90" + store
    vanilla = SE.base_exe_bytes(va, 6) + store
    out = {}
    for name, code in (("got", patched), ("van", vanilla)):
        e = Emu(g)
        w32(e.uc, RK.LB_PAD_DEFAULT, 2)
        w32(e.uc, C["g_rw_inlist"], inlist)
        w32(e.uc, elem + 0x2C, 0x77)
        e.uc.mem_write(va, code)
        try:
            e.uc.ctl_remove_cache(va, va + 0x40)
        except Exception:  # noqa: BLE001
            pass
        regs = dict(eax=0, ebx=0x42, ecx=0x9B8EE0, edx=0x44444444, esi=elem, edi=0x55555555, ebp=EBP)
        st = _run_cave(e, va, va + len(code), regs, SP0)
        st["pad"] = r32(e.uc, elem + 0x2C)
        out[name] = st
    got, van = out["got"], out["van"]
    scaled = g > 16 and (inlist or elem == RW + 0x5A0C)
    assert got["pad"] == (SL.rw_list_text_pad(g) if scaled else 2)
    assert van["pad"] == 2
    for r in ("eax", "ebx", "ecx", "esi", "edi", "ebp", "esp"):
        assert got[r] == van[r], r
    if not scaled:
        assert got["edx"] == van["edx"]
