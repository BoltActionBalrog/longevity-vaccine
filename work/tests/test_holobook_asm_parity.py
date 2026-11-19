"""Unicorn parity for the retirement Holobook bake (assemble_holobook.py, group holobook_scale).

Oracle = scaling_laws.hb_* (the HOF's letterbox law with the Holobook's literals; fonts at vanilla's snapped size;
vanilla line breaks).  Every thunk runs from its REAL assembled bytes at its REAL cave VA; the Monument / Hall of
Fame block is loaded too (t_hof_pairnn runs for real in the field-pair test), the engine callees and the other
shared helpers (t_ffn_at, t_fdirect_at, t_dl_immfix, t_mon_resample, t_mon_gate, t_mon_restripe, t_mon_face) are
recording stubs.  Covers: the sites' pristine-byte contracts, the build (num, letterbox, the painter gate held
across the resize, window/client rects, clip + clear, content rect, the 24 rebuilt edges, CLOSE/BACK, the 8 font
calls, the imm walk with g_dl_immg bracketed, native no-op, builder failure passthrough), the paint gate, the 8
font detours, the backdrop / artbox wrappers and their g_hof_* brackets, the field-pair enlarge bit-exact against
the law with the Holobook's pair, the caption rects, the wrap brackets, the line-break gate (fresh line,
continuation, bail, unarmed, other font), the gate / restripe chain heads.
"""
from __future__ import annotations

import contextlib
import io
import struct

import pytest

from test_mon_asm_parity import (  # noqa: E402
    AM, LAYOUT as MON_LAYOUT, PLANES, SCALE_UNIFORM_BYTES, SE, SL, SP0, STUB, TRAP, _cs, asm, make_buffer, r32, r32s,
    rand_pal, w32, REG,
)
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_holobook as HBM  # noqa: E402

LAYOUT, CELLS, END, NAMES = HBM.assemble_all()
VA = dict(NAMES)
STACK = 0x00300000
REC = 0x00780000
OBJ = 0x02000000
HB = HBM.HB
RES = ((3840, 2160), (2560, 1440), (1920, 1080), (1600, 1200), (1280, 1024), (3840, 2400), (7680, 4320))


class Emu:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
            cls._inst._init()
        cls._inst._reset()
        return cls._inst

    def _init(self):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(HBM.PCAVE2, HBM.SECTION_LENGTH)
        uc.mem_map(STACK, 0x20000)
        uc.mem_map(0x400000, 0x600000)
        uc.mem_map(OBJ, 0x400000)
        uc.mem_map(PLANES, 0x400000)
        uc.mem_map(TRAP & 0xFFFFF000, 0x1000)

    def _reset(self):
        uc = self.uc
        uc.mem_write(HBM.PCAVE2, bytes(HBM.SECTION_LENGTH))
        for _n, (off, b) in MON_LAYOUT.items():
            uc.mem_write(AM.PCAVE2 + off, b)
        for _n, (off, b) in LAYOUT.items():
            uc.mem_write(HBM.PCAVE2 + off, b)
        with contextlib.suppress(Exception):
            uc.ctl_remove_cache(HBM.PCAVE2, HBM.PCAVE2 + HBM.SECTION_LENGTH)
        uc.mem_write(TRAP, bytes([0xF4]))
        uc.mem_write(HBM.SCALE_UNIFORM, SCALE_UNIFORM_BYTES)
        with contextlib.suppress(Exception):
            uc.ctl_remove_cache(HBM.SCALE_UNIFORM, HBM.SCALE_UNIFORM + 0x40)
        uc.mem_write(REC, bytes(0x2000))
        for r in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp"):
            uc.reg_write(REG[r], 0)

    def stub(self, va, src):
        b = asm(src, va)
        self.uc.mem_write(va, b)
        with contextlib.suppress(Exception):
            self.uc.ctl_remove_cache(va, va + max(len(b), 0x40))

    def run(self, start, until=TRAP, count=0, esp=SP0, **regs):
        uc = self.uc
        uc.reg_write(REG["esp"], esp)
        for r, v in regs.items():
            uc.reg_write(REG[r], v & 0xFFFFFFFF)
        uc.emu_start(start, until, count=count)

    def reg(self, r):
        return self.uc.reg_read(REG[r])


def cell(name):
    return VA[name]


# ---- sites ------------------------------------------------------------------------------------------------------------
SITES = HBM.site_list(NAMES)


def test_sites_match_the_pristine_base_and_end_on_instruction_boundaries():
    assert HBM.verify_live(SITES) == []
    assert len(SITES) == 23 and len({s["va"] for s in SITES}) == 23
    for s in SITES:
        b = SE.base_exe_bytes(s["va"], len(s["orig"]) + 16)
        ends = {i.address + i.size for i in _cs.disasm(b, s["va"])}
        assert s["va"] + len(s["orig"]) in ends, s["id"]
    for a in SITES:                                       # no two sites overlap
        for b in SITES:
            if a is not b:
                assert not (a["va"] < b["va"] + len(b["orig"]) and b["va"] < a["va"] + len(a["orig"])), (a["id"], b["id"])


def test_block_inside_its_reserved_region_and_imm_rows_avoid_every_site():
    assert HBM.OFF_CODE == 0x44000 and END <= HBM.OFF_LIMIT == 0x46000
    for site, _a in HBM.IMM_ROWS:
        assert struct.unpack("<b", SE.base_exe_bytes(site, 1))[0] == _a
        for s in SITES:
            assert not (site < s["va"] + len(s["orig"]) and s["va"] <= site), (hex(site), s["id"])
    tab = HBM.immtab()
    assert len(tab) == 3 * 16 + 4 and tab[-4:] == bytes(4)
    import assemble_dl as AD
    for site, a in HBM.IMM_ROWS:
        for num in range(16, SL.HOF_NUM_MAX + 1):
            v = AD.imm_value(a, 0, 0, num)
            assert v == SL.mon_s(a, num) and -128 <= v <= 127


# ---- the build ---------------------------------------------------------------------------------------------------------
FONT_SLOT_REC = REC + 0x400          # t_ffn_at calls: (slot, S, v, num) x 8
BTN_VTBL = STUB + 0x900


def _seed(e, sw, sh, wide=1, builder_ret=0):
    uc = e.uc
    w32(uc, HBM.SW, sw)
    w32(uc, HBM.SH, sh)
    w32(uc, HBM.WIDE, wide)
    uc.mem_write(HB, bytes(0x3800))
    for k, v in enumerate(SL.HB_CONTENT_NATIVE):
        w32(uc, HB + 0xA24 + 4 * k, v)
    for i, r in enumerate(SL.HB_RECTS_NATIVE):
        for k in range(4):
            w32(uc, HB + SL.HB_TABLE_OFF + 16 * i + 4 * k, r[k])
    for btn in (HBM.HB_CLOSE, HBM.HB_BACK):
        w32(uc, btn, BTN_VTBL)
    w32(uc, BTN_VTBL + 0xF8, STUB + 0x300)
    w32(uc, HBM.G_DL_IMMG, 0x1234)
    w32(uc, VA["g_hb_armed"], 1)                                   # a previous open's state
    e.stub(HBM.GWINIT, f"mov dword ptr [{REC:#x}], ecx\nmov eax, dword ptr [{VA['g_hb_armed']:#x}]\nmov dword ptr [{REC + 0x4C:#x}], eax\nmov eax, {builder_ret}\nret\n")
    # GraphicWin_resize: record (self, w, h, client) per call + the paint gate's state at the time
    e.stub(HBM.GW_RESIZE, f"""
        mov eax, dword ptr [{REC + 4:#x}]
        shl eax, 4
        add eax, {REC + 0x100:#x}
        mov dword ptr [eax], ecx
        mov edx, dword ptr [esp+4]
        mov dword ptr [eax+4], edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [eax+8], edx
        mov edx, dword ptr [{cell('g_hb_building'):#x}]
        shl edx, 8
        or edx, dword ptr [esp+12]
        mov dword ptr [eax+12], edx
        inc dword ptr [{REC + 4:#x}]
        ret 0xC
    """)
    e.stub(HBM.SET_CLIP, f"mov dword ptr [{REC + 8:#x}], ecx\nmov eax, [esp+4]\nmov dword ptr [{REC + 0xC:#x}], eax\nret 4\n")
    e.stub(HBM.GW_CLEAR, f"mov dword ptr [{REC + 0x10:#x}], ecx\nmov eax, [esp+4]\nmov dword ptr [{REC + 0x14:#x}], eax\ninc dword ptr [{REC + 0x18:#x}]\nret 4\n")
    e.stub(STUB + 0x300, f"inc dword ptr [{REC + 0x1C:#x}]\nret\n")
    e.stub(HBM.T_FFN_AT, f"""
        mov eax, dword ptr [{REC + 0x20:#x}]
        shl eax, 4
        add eax, {FONT_SLOT_REC:#x}
        mov edx, dword ptr [esp+4]
        mov dword ptr [eax], edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [eax+4], edx
        mov edx, dword ptr [esp+12]
        mov dword ptr [eax+8], edx
        mov edx, dword ptr [esp+16]
        mov dword ptr [eax+12], edx
        inc dword ptr [{REC + 0x20:#x}]
        mov eax, dword ptr [esp+4]
        ret
    """)
    e.stub(HBM.T_FDIRECT_AT, f"""
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 0x30:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 0x34:#x}], eax
        mov eax, dword ptr [esp+12]
        mov dword ptr [{REC + 0x38:#x}], eax
        mov eax, dword ptr [esp+16]
        mov dword ptr [{REC + 0x3C:#x}], eax
        mov eax, 0x5F5F0000
        ret
    """)
    e.stub(HBM.T_DL_IMMFIX, f"mov dword ptr [{REC + 0x40:#x}], esi\nmov eax, dword ptr [{HBM.G_DL_IMMG:#x}]\nmov dword ptr [{REC + 0x44:#x}], eax\ninc dword ptr [{REC + 0x48:#x}]\nret\n")


def _build(e):
    w32(e.uc, SP0, TRAP)
    e.run(VA["t_hb_build"], ecx=HB, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)


@pytest.mark.parametrize("sw,sh", RES)
def test_build_armed_matches_the_laws(sw, sh):
    e = Emu()
    uc = e.uc
    _seed(e, sw, sh)
    _build(e)
    num = SL.hb_scale_num(sw, sh)
    lx, ly = SL.hb_letterbox(sw, sh, num)
    ox, oy = SL.hb_origin(num, lx, ly)
    assert e.reg("eax") == 0 and r32(uc, REC) == HB and r32(uc, REC + 0x4C) == 0   # disarmed while gwinit repaints
    assert [r32s(uc, cell(n)) for n in ("g_hb_num", "g_hb_armed", "g_hb_lx", "g_hb_ly", "g_hb_ox", "g_hb_oy")] == [num, 1, lx, ly, ox, oy]
    assert r32(uc, cell("g_hb_building")) == 0
    # resizes: the window (painter gated, client size), then CLOSE and BACK (gate open)
    assert r32(uc, REC + 4) == 3
    win = [r32(uc, REC + 0x100 + k) for k in (0, 4, 8, 12)]
    assert win == [HB, sw, sh, 0x101]
    w, h = SL.mon_s(120, num), SL.mon_s(20, num)
    x, y = SL.hb_button_rect(num, lx, ly)[:2]
    for i, btn in enumerate((HBM.HB_CLOSE, HBM.HB_BACK)):
        assert [r32(uc, REC + 0x110 + 16 * i + k) for k in (0, 4, 8, 12)] == [btn, w, h, 1]
        assert [r32s(uc, btn + 0x13C + 4 * k) for k in range(4)] == [x, y, x + w, y + h]
        assert [r32s(uc, btn + 0x474 + 4 * k) for k in range(4)] == [0, 0, w, h]
        assert r32(uc, btn + 0x970) == 0x5F5F0000
    assert r32(uc, REC + 0x1C) == 2                                    # each button repainted once
    assert [r32(uc, REC + 0x30 + 4 * k) for k in range(4)] == [VA["g_hb_btnfont"], 14, 1, num]
    # window rect / client, clip to the client, clear 0
    assert [r32s(uc, HB + 0x13C + 4 * k) for k in range(4)] == [0, 0, sw, sh]
    assert [r32s(uc, HB + 0x474 + 4 * k) for k in range(4)] == [0, 0, sw, sh]
    assert (r32(uc, REC + 8), r32(uc, REC + 0xC)) == (HB + 0x444, HB + 0x474)
    assert (r32(uc, REC + 0x10), r32(uc, REC + 0x14), r32(uc, REC + 0x18)) == (HB, 0, 1)
    assert tuple(r32s(uc, HB + 0xA24 + 4 * k) for k in range(4)) == SL.hb_content_rect(num, lx, ly)
    got = tuple(tuple(r32s(uc, HB + SL.HB_TABLE_OFF + 16 * i + 4 * k) for k in range(4)) for i in range(6))
    assert got == SL.hb_rects(num, lx, ly)
    # fonts: (slot, snapped S, v, num) then the shadow at 16, per table
    assert r32(uc, REC + 0x20) == 8
    for k, table in enumerate(HBM.FONT_TABLES):
        s, v = SL.hb_font_native(table)
        assert [r32(uc, FONT_SLOT_REC + 32 * k + j) for j in (0, 4, 8, 12)] == [VA["g_hb_fslots"] + k * HBM.SLOT, s, v, num]
        assert [r32(uc, FONT_SLOT_REC + 32 * k + 16 + j) for j in (0, 4, 8, 12)] == [VA["g_hb_sslots"] + k * HBM.SLOT, s, v, 16]
        assert r32(uc, cell("g_hb_fonts") + 4 * k) == VA["g_hb_fslots"] + k * HBM.SLOT
        assert r32(uc, cell("g_hb_shadows") + 4 * k) == VA["g_hb_sslots"] + k * HBM.SLOT
    # the imm walk under g_dl_immg := num, restored
    assert (r32(uc, REC + 0x40), r32(uc, REC + 0x44), r32(uc, REC + 0x48)) == (VA["g_hb_immtab"], num, 1)
    assert r32(uc, HBM.G_DL_IMMG) == 0x1234


@pytest.mark.parametrize("sw,sh,wide,ret", [(1024, 768, 1, 0), (3840, 2160, 0, 0), (1024, 1024, 1, 0), (3840, 2160, 1, 1)])
def test_build_native_and_failure_are_no_ops(sw, sh, wide, ret):
    e = Emu()
    uc = e.uc
    _seed(e, sw, sh, wide, builder_ret=ret)
    _build(e)
    assert e.reg("eax") == ret and r32(uc, cell("g_hb_armed")) == 0
    assert r32(uc, REC + 4) == 0 and r32(uc, REC + 0x18) == 0 and r32(uc, REC + 0x20) == 0 and r32(uc, REC + 0x48) == 0
    assert tuple(tuple(r32s(uc, HB + SL.HB_TABLE_OFF + 16 * i + 4 * k) for k in range(4)) for i in range(6)) == SL.HB_RECTS_NATIVE


@pytest.mark.parametrize("building", (0, 1))
def test_paint_gate(building):
    e = Emu()
    uc = e.uc
    w32(uc, cell("g_hb_building"), building)
    e.stub(HBM.DRAW + 5, f"mov dword ptr [{REC:#x}], ebp\nmov eax, [esp]\nmov dword ptr [{REC + 4:#x}], eax\nmov eax, [esp+4]\nmov dword ptr [{REC + 8:#x}], eax\nmov eax, [esp+8]\nmov dword ptr [{REC + 0xC:#x}], eax\nmov dword ptr [{REC + 0x10:#x}], 1\nmov esp, ebp\npop ebp\nret\n")
    w32(uc, SP0, TRAP)
    e.run(VA["t_hb_drawgate"], ecx=HB, ebp=0x4444)
    assert e.reg("esp") == SP0 + 4 and e.reg("ebp") == 0x4444
    if building:
        assert r32(uc, REC + 0x10) == 0                              # the painter never ran
    else:
        assert r32(uc, REC + 0x10) == 1 and r32(uc, REC) == SP0 - 4  # push ebp / mov ebp,esp / push -1 then the body
        assert (r32(uc, REC + 4), r32(uc, REC + 8), r32(uc, REC + 0xC)) == (0xFFFFFFFF, 0x4444, TRAP)


# ---- F: the 8 font detours ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("va,ln,reg,table", HBM.FONT_SITES)
@pytest.mark.parametrize("armed", (0, 1))
def test_font_detours(va, ln, reg, table, armed):
    e = Emu()
    uc = e.uc
    w32(uc, cell("g_hb_armed"), armed)
    w32(uc, table, 0x7777)
    k = HBM.FONT_TABLES.index(table)
    w32(uc, cell("g_hb_fonts") + 4 * k, 0x8000 + k)
    e.stub(va + ln, "pushfd\npop dword ptr [{0:#x}]\nhlt\n".format(REC))
    for flags in (0x202, 0x2C3):
        uc.reg_write(REG["eax"], 0)
        from unicorn.x86_const import UC_X86_REG_EFLAGS
        uc.reg_write(UC_X86_REG_EFLAGS, flags)
        regs = {r: 0x1000 + i for i, r in enumerate(("ecx", "edx", "ebx", "esi", "edi"))}
        regs.pop(reg, None)
        e.run(VA[f"t_hb_font_{va:x}"], until=va + ln + 12, count=200, **regs)
        assert e.reg(reg) == (0x8000 + k if armed else 0x7777)
        assert r32(uc, REC) & 0x8D5 == flags & 0x8D5
        for r, v in regs.items():
            assert e.reg(r) == v


# ---- B / G: backdrops, artbox ----------------------------------------------------------------------------------------------
def _arm(e, sw, sh):
    num = SL.hb_scale_num(sw, sh)
    lx, ly = SL.hb_letterbox(sw, sh, num)
    ox, oy = SL.hb_origin(num, lx, ly)
    for k, v in (("g_hb_num", num), ("g_hb_armed", 1), ("g_hb_lx", lx), ("g_hb_ly", ly), ("g_hb_ox", ox), ("g_hb_oy", oy)):
        w32(e.uc, cell(k), v)
    return num, lx, ly, ox, oy


def _rec_stub(e, va, nargs, retn, extra=""):
    src = f"mov dword ptr [{REC:#x}], ecx\n" + "".join(
        f"mov eax, dword ptr [esp+{4 + 4 * k:#x}]\nmov dword ptr [{REC + 4 + 4 * k:#x}], eax\n" for k in range(nargs))
    e.stub(va, src + extra + f"inc dword ptr [{REC + 0x80:#x}]\nmov eax, 0x5A\nret {retn:#x}\n")


@pytest.mark.parametrize("sw,sh", RES)
def test_frame_backdrop_resamples_into_the_letterbox(sw, sh):
    e = Emu()
    uc = e.uc
    num, lx, ly, _ox, _oy = _arm(e, sw, sh)
    SRC = OBJ + 0x1000
    make_buffer(e, SRC, PLANES, 1024, 768, 1024)
    _rec_stub(e, HBM.T_MON_RESAMPLE, 11, 0x2C)
    uc.mem_write(SP0, struct.pack("<8I", TRAP, 0xDE57, 0, 0, 0, 0, 1024, 768))
    e.run(VA["t_hb_bd_frame"], ecx=SRC, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x1C and e.reg("eax") == 0
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    got = [r32s(uc, REC + 4 + 4 * k) for k in range(11)]
    assert got == [PLANES, 1024, 0, 0, 1024, 768, 0xDE57, lx, ly, SL.mon_s(1024, num), SL.mon_s(768, num)]


def test_backdrops_and_artbox_pass_through_unarmed():
    e = Emu()
    uc = e.uc
    for thunk, target, nargs in (("t_hb_bd_frame", HBM.COPY4, 7), ("t_hb_bd_art", HBM.COPY4, 7), ("t_hb_artbox", HBM.BUFFER_DRAW, 4)):
        _rec_stub(e, target, nargs, 4 * nargs)
        uc.mem_write(REC, bytes(0x100))
        uc.mem_write(SP0, struct.pack("<8I", TRAP, *range(11, 11 + 7)))
        e.run(VA[thunk], ecx=0x777)
        assert e.reg("esp") == SP0 + 4 + 4 * nargs and r32(uc, REC) == 0x777
        assert [r32(uc, REC + 4 + 4 * k) for k in range(nargs)] == list(range(11, 11 + nargs))


@pytest.mark.parametrize("which", ("art", "artbox"))
def test_pair_wrappers_bracket_the_hof_cells(which):
    e = Emu()
    uc = e.uc
    num, *_ = _arm(e, 3840, 2160)
    w32(uc, AM.CELL["g_hof_num"], 0x1D)
    w32(uc, HBM.G_HOF_FIELD, 0xABCD)
    SRC = OBJ + 0x1000
    make_buffer(e, SRC, PLANES, 420, 520, 424)
    extra = (f"mov eax, dword ptr [{AM.CELL['g_hof_num']:#x}]\nmov dword ptr [{REC + 0x40:#x}], eax\n"
             f"mov eax, dword ptr [{HBM.G_HOF_FIELD:#x}]\nmov dword ptr [{REC + 0x44:#x}], eax\n")
    _rec_stub(e, HBM.T_HOF_PAIRNN, 10, 0x28, extra)
    if which == "art":
        uc.mem_write(SP0, struct.pack("<8I", TRAP, 0xDE57, 3, 4, 500, 600, 800, 600))
        e.run(VA["t_hb_bd_art"], ecx=SRC, esi=0x11, ebp=0x44)
        assert e.reg("esp") == SP0 + 4 + 0x1C
        want = [PLANES, 424, 3, 4, 800, 600, 0xDE57, 500, 600, 9]
        field = SL.hof_field_cell(SL.HB_FIELD_PAIR)
    else:
        uc.mem_write(SP0, struct.pack("<5I", TRAP, 0xDE57, 9, 700, 333))
        e.run(VA["t_hb_artbox"], ecx=SRC, esi=0x11, ebp=0x44)
        assert e.reg("esp") == SP0 + 4 + 0x10
        want = [PLANES, 424, 0, 0, 420, 520, 0xDE57, 700, 333, 9]
        field = 0
    assert [r32(uc, REC + 4 + 4 * k) for k in range(10)] == want
    assert (r32(uc, REC + 0x40), r32(uc, REC + 0x44)) == (num, field)
    assert (r32(uc, AM.CELL["g_hof_num"]), r32(uc, HBM.G_HOF_FIELD)) == (0x1D, 0xABCD)
    assert (e.reg("esi"), e.reg("ebp"), e.reg("eax")) == (0x11, 0x44, 0)


def _hb_field_source():
    """A Holobook-like source: the 64/197 scanline field with a 1-px stroke, a 2-row channel and a shape."""
    sw, sh = 40, 48
    f0, f1 = SL.HB_FIELD_PAIR
    src = bytearray(f0 if y % 2 == 0 else f1 for y in range(sh) for _x in range(sw))
    for x in range(sw):
        src[20 * sw + x] = 230                             # a stroke row
        src[23 * sw + x] = 230                             # a second stroke: rows 21/22 = a 2-row channel
    for y in range(30, 40):
        for x in range(8, 20):
            src[y * sw + x] = 175 if (y + x) % 3 else 230  # a shape
    return src, sw, sh


@pytest.mark.parametrize("num", (17, 20, 22, 25, 30, 45, 72))
def test_holobook_field_pair_enlarge_is_bit_exact_against_the_law(num):
    """The generalized t_hof_pairfld with g_hof_field = the Holobook's pair = hof_pair_enlarge(field=HB_FIELD_PAIR)."""
    e = Emu()
    uc = e.uc
    w32(uc, AM.CELL["g_hof_num"], num)
    pal = bytearray(rand_pal(7))
    for i, rgb in ((64, (4, 4, 4)), (197, (24, 18, 11)), (230, (115, 61, 53)), (175, (79, 50, 17))):
        pal[i * 4:i * 4 + 4] = bytes(rgb) + b"\0"
    src, sw, sh = _hb_field_source()
    dW, dH = (sw * num) // 16 + 6, (sh * num) // 16 + 6
    SDATA, DDATA, DEST = PLANES, PLANES + 0x40000, OBJ + 0x1000
    uc.mem_write(SDATA, bytes(src))
    dst0 = bytes(0xEE for _ in range(dW * dH))
    make_buffer(e, DEST, DDATA, dW, dH, dW, bytes(pal))
    for field in (SL.HB_FIELD_PAIR, None):
        for y0 in range(SL.stripe_period(num)):
            w32(uc, HBM.G_HOF_FIELD, SL.hof_field_cell(field))
            w32(uc, DEST - 0x304, y0)
            uc.mem_write(DDATA, dst0)
            want = bytearray(dst0)
            SL.hof_pair_enlarge(src, sw, 0, 0, sw, sh, bytes(pal), num, want, dW, dW, dH, 2, 3, y0, 9, field)
            uc.mem_write(SP0, struct.pack("<11I", TRAP, SDATA, sw, 0, 0, sw, sh, DEST, 2, 3, 9))
            e.run(HBM.T_HOF_PAIRNN, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
            assert e.reg("esp") == SP0 + 4 + 0x28
            assert bytes(uc.mem_read(DDATA, dW * dH)) == bytes(want), (field, y0)


# ---- C: captions ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("page", (1, 2, 8, 0, 3, -1))
def test_caption_rects(page):
    e = Emu()
    uc = e.uc
    num, lx, ly, _ox, _oy = _arm(e, 1920, 1080)
    uc.mem_write(HB, bytes(0x3000))
    w32(uc, HB + 0x2144, page)
    for k in range(4):
        w32(uc, HB + 0xA94 + 4 * k, 0x900 + k)
    _rec_stub(e, HBM.WRITE_CENT_L_7, 3, 0xC)
    uc.mem_write(SP0, struct.pack("<4I", TRAP, 0x9B86A0, HB + 0xA94, 17))
    e.run(VA["t_hb_cap"], esi=HB, ecx=0x5555, edi=0x22, ebx=0x33, ebp=0x44, edx=0x66)
    assert e.reg("esp") == SP0 + 4 + 0xC and r32(uc, REC) == 0x5555
    assert [r32(uc, REC + 4 + 4 * k) for k in range(3)] == [0x9B86A0, HB + 0xA94, 17]
    got = tuple(r32s(uc, HB + 0xA94 + 4 * k) for k in range(4))
    if page in SL.HB_CAPTIONS:
        assert got == SL.hb_caption_rect(page, num, lx, ly)
    else:
        assert got == tuple(0x900 + k for k in range(4))
    assert (e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x22, 0x33, 0x44)


# ---- W: wrap brackets and the line-break gate -----------------------------------------------------------------------------
@pytest.mark.parametrize("name,target,nargs,kind,table,nat", [
    ("t_hb_w_title", HBM.WRAP_CENT_4, 4, "arg4", 0x8A40E4, 236), ("t_hb_w_intro", HBM.WRAP_CENT_4, 4, "arg4", 0x8A40E8, 256),
    ("t_hb_w_measure", HBM.WRAP_HEIGHT, 2, "arg2", 0x8A40E0, 455), ("t_hb_w_entry", HBM.WRAP_2, 2, "rect2", 0x8A40E0, 455),
    ("t_hb_w_cap8", HBM.WRAP_CENT_6, 2, "rect2", 0x8A40F0, 0x1C1)])
@pytest.mark.parametrize("armed", (0, 1))
def test_wrap_brackets(name, target, nargs, kind, table, nat, armed):
    e = Emu()
    uc = e.uc
    w32(uc, cell("g_hb_armed"), armed)
    k = HBM.FONT_TABLES.index(table)
    w32(uc, cell("g_hb_fonts") + 4 * k, 0x8100 + k)
    w32(uc, cell("g_hb_shadows") + 4 * k, 0x8200 + k)
    extra = "".join(f"mov eax, dword ptr [{cell(c):#x}]\nmov dword ptr [{REC + 0x40 + 4 * i:#x}], eax\n"
                    for i, c in enumerate(("g_hb_wrap_on", "g_hb_wrap_font", "g_hb_wrap_shadow", "g_hb_wrap_dev",
                                           "g_hb_wrap_nat", "g_hb_last_dev")))
    _rec_stub(e, target, nargs, 4 * nargs, extra)
    RECT = OBJ + 0x2000
    for kk, v in enumerate((100, 50, 100 + 333, 90)):
        w32(uc, RECT + 4 * kk, v)
    args = {"arg4": (0x9B86A0, 10, 20, 333), "arg2": (0x9B86A0, 333), "rect2": (0x9B86A0, RECT)}[kind]
    uc.mem_write(SP0, struct.pack(f"<{1 + nargs}I", TRAP, *args))
    e.run(VA[name], ecx=0x6060, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 4 * nargs and e.reg("eax") == 0x5A and r32(uc, REC) == 0x6060
    assert [r32(uc, REC + 4 + 4 * i) for i in range(nargs)] == list(args)
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    seen = [r32(uc, REC + 0x40 + 4 * i) for i in range(6)]
    if armed:
        assert seen == [1, 0x8100 + k, 0x8200 + k, 333, nat, 0xFFFFFFFF]
    else:
        assert seen[0] == 0
    assert r32(uc, cell("g_hb_wrap_on")) == 0


FLB_REC = REC + 0x600
FLB_CFG = REC + 0x700
SHADOW, FONT = 0x8200, 0x8100


def _flb_stub(e):
    """The native body after the displaced prologue (sub esp,0x10 / mov eax,[esp+0x18]).  Per call it records (ecx,
    *budget, g_wrap_width_used) in order, checks eax is the budget pointer, then behaves per font from FLB_CFG: ecx ==
    SHADOW -> spend [CFG+4], return [CFG+8]; else spend [CFG+0xC], return [CFG+0x10] (a return != 0 = a break, *budget
    := 0).  It adds what it spent to g_wrap_width_used like the original, and RET 0xC."""
    e.stub(HBM.FLB + HBM.FLB_LEN, f"""
        mov edx, dword ptr [{FLB_REC + 0xF0:#x}]
        shl edx, 4
        add edx, {FLB_REC:#x}
        mov dword ptr [edx], ecx
        mov ecx, dword ptr [eax]
        mov dword ptr [edx+4], ecx
        mov ecx, dword ptr [{HBM.G_WRAP_USED:#x}]
        mov dword ptr [edx+8], ecx
        mov dword ptr [edx+12], 0
        cmp eax, dword ptr [esp+0x18]
        jne bad
        mov dword ptr [edx+12], 1
    bad:
        inc dword ptr [{FLB_REC + 0xF0:#x}]
        mov ecx, {FLB_CFG + 0xC:#x}
        mov edx, dword ptr [edx]
        cmp edx, dword ptr [{FLB_CFG:#x}]
        jne useb
        mov ecx, {FLB_CFG + 4:#x}
    useb:
        mov edx, dword ptr [ecx]
        add dword ptr [{HBM.G_WRAP_USED:#x}], edx
        sub dword ptr [eax], edx
        jns okb
        mov dword ptr [eax], 0
    okb:
        mov ecx, dword ptr [ecx+4]
        test ecx, ecx
        jz fits
        mov dword ptr [eax], 0
    fits:
        mov eax, ecx
        add esp, 0x10
        ret 0xC
    """)


def _flb_run(e, ecx, budget, cfg):
    uc = e.uc
    BUD = OBJ + 0x3000
    w32(uc, BUD, budget)
    uc.mem_write(FLB_REC, bytes(0x100))
    for k, v in enumerate((SHADOW,) + cfg):
        w32(uc, FLB_CFG + 4 * k, v)
    w32(uc, HBM.G_WRAP_USED, 50)
    uc.mem_write(SP0, struct.pack("<4I", TRAP, 0x9B86A0, BUD, 31))
    e.run(VA["t_hb_flb"], ecx=ecx, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0xC
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    n = r32(uc, FLB_REC + 0xF0)
    calls = [(r32(uc, FLB_REC + 16 * k), r32s(uc, FLB_REC + 16 * k + 4), r32(uc, FLB_REC + 16 * k + 8),
              r32(uc, FLB_REC + 16 * k + 12)) for k in range(n)]
    assert all(c[3] == 1 for c in calls)                     # eax == the budget pointer at every native entry
    return e.reg("eax"), r32s(uc, BUD), r32(uc, HBM.G_WRAP_USED), calls


@pytest.mark.parametrize("num", (19, 22, 25, 45))
def test_line_break_gate(num):
    """t_hb_flb v2: two measurements from the same g_wrap_width_used (the vanilla shadow at the vanilla budget, then the
    scaled font at the device budget); the EARLIER break wins (hb_line_breaks with scaled_fn); g_wrap_width_used is
    left as the vanilla measurement left it; the device remainder carries to a continuation segment."""
    e = Emu()
    uc = e.uc
    _arm(e, 3840, 2160)
    w32(uc, cell("g_hb_num"), num)
    DEV, NAT = SL.mon_s(256, num), 256
    for c, v in (("g_hb_wrap_on", 1), ("g_hb_wrap_font", FONT), ("g_hb_wrap_shadow", SHADOW), ("g_hb_wrap_dev", DEV),
                 ("g_hb_wrap_nat", NAT), ("g_hb_last_dev", 0xFFFFFFFF)):
        w32(uc, cell(c), v)
    _flb_stub(e)
    P1, P2 = 0x9B86B0, 0x9B86C0
    # both fit: no break; A's g_wrap_width_used; the device remainder is B's
    r, bud, used, calls = _flb_run(e, FONT, DEV, (100, 0, 130, 0))
    assert r == 0 and bud == DEV - 130 and used == 50 + 100
    assert [(c[0], c[1], c[2]) for c in calls] == [(SHADOW, NAT, 50), (FONT, DEV, 50)]
    assert (r32(uc, cell("g_hb_last_nat")), r32s(uc, cell("g_hb_last_dev"))) == (NAT - 100, DEV - 130)
    # a continuation resumes BOTH remainders
    r, bud, used, calls = _flb_run(e, FONT, DEV - 130, (40, 0, 50, 0))
    assert [(c[0], c[1]) for c in calls] == [(SHADOW, NAT - 100), (FONT, DEV - 130)]
    assert r == 0 and bud == DEV - 180 and r32(uc, cell("g_hb_last_nat")) == NAT - 140
    # vanilla breaks, scaled fits -> vanilla's break; scaled breaks, vanilla fits -> the scaled break; both -> earlier
    for cfg, want in (((100, P2, 130, 0), P2), ((100, 0, 130, P1), P1), ((100, P2, 130, P1), P1), ((100, P1, 130, P2), P1)):
        w32(uc, cell("g_hb_last_dev"), 0xFFFFFFFF)
        r, _bud, used, calls = _flb_run(e, FONT, DEV, cfg)
        assert r == want and used == 150 and len(calls) == 2, cfg
    # an unknown budget, another font, or the bracket off -> ONE native call with ecx and the budget untouched
    for ecx, budget, on in ((FONT, DEV - 7, 1), (0x9999, DEV, 1), (FONT, DEV, 0)):
        w32(uc, cell("g_hb_wrap_on"), on)
        w32(uc, cell("g_hb_last_dev"), 0xFFFFFFFF)
        r, bud, used, calls = _flb_run(e, ecx, budget, (100, 0, 130, 0))
        assert [(c[0], c[1]) for c in calls] == [(ecx, budget)] and bud == budget - 130 and r == 0


# ---- N: gate / restripe chain heads -------------------------------------------------------------------------------------
@pytest.mark.parametrize("armed", (0, 1))
def test_gate_admits_the_two_buttons_and_chains_the_rest(armed):
    e = Emu()
    uc = e.uc
    w32(uc, cell("g_hb_armed"), armed)
    e.stub(HBM.T_MON_GATE, f"mov dword ptr [{REC:#x}], esi\ninc dword ptr [{REC + 4:#x}]\nmov eax, 0x33\nret\n")
    for esi in (HBM.HB_CLOSE, HBM.HB_BACK, 0x123456):
        uc.mem_write(REC, bytes(8))
        w32(uc, SP0, TRAP)
        e.run(VA["t_hb_gate"], esi=esi)
        hit = armed and esi != 0x123456
        assert e.reg("eax") == (1 if hit else 0x33) and r32(uc, REC + 4) == (0 if hit else 1)


@pytest.mark.parametrize("armed", (0, 1))
def test_restripe_faces_the_two_canvases_and_chains_every_draw(armed):
    e = Emu()
    uc = e.uc
    w32(uc, cell("g_hb_armed"), armed)
    w32(uc, cell("g_hb_num"), 45)
    e.stub(HBM.T_MON_FACE, f"mov eax, [esp+4]\nmov dword ptr [{REC:#x}], eax\nmov eax, [esp+8]\nmov dword ptr [{REC + 4:#x}], eax\ninc dword ptr [{REC + 8:#x}]\nmov ecx, 0xBAD\nmov edx, 0xBAD\nret 8\n")
    e.stub(HBM.T_MON_RESTRIPE, f"mov dword ptr [{REC + 0xC:#x}], ecx\nmov dword ptr [{REC + 0x10:#x}], edx\ninc dword ptr [{REC + 0x14:#x}]\nret\n")
    for ecx in (HBM.HB_CLOSE + 0x444, HBM.HB_BACK + 0x444, 0x123456):
        uc.mem_write(REC, bytes(0x20))
        w32(uc, SP0, TRAP)
        e.run(VA["t_hb_restripe"], ecx=ecx, edx=0x66)
        hit = armed and ecx != 0x123456
        assert r32(uc, REC + 8) == (1 if hit else 0) and r32(uc, REC + 0x14) == 1
        assert (r32(uc, REC + 0xC), r32(uc, REC + 0x10)) == (ecx, 0x66)
        if hit:
            assert (r32(uc, REC), r32(uc, REC + 4)) == (ecx, 45)


# ---- the shipped yaml carries exactly this assembler's bytes -------------------------------------------------------------
def _yaml():
    import pathlib
    import apply_patches as ap
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    contents = {c["id"]: c for c in cave.get("contents") or []}
    return cave, contents, symbols


def test_shipped_yaml_carries_these_exact_bytes_and_offsets():
    cave, contents, symbols = _yaml()
    assert int(cave["length"]) >= HBM.OFF_LIMIT >= HBM.SECTION_LENGTH - 0x2000   # later groups grow the section
    for name, (off, b) in LAYOUT.items():
        assert int(contents[name]["offset"]) == off, name
        want = HBM.templatize(b, HBM.PCAVE2 + off, NAMES) if not name.startswith("g_") else HBM.hx(b)
        assert " ".join(str(contents[name]["bytes"]).split()) == want, name
        assert int(symbols[name]["offset"]) == off, name
    for name, (off, size) in CELLS.items():
        assert int(symbols[name]["offset"]) == off and int(symbols[name].get("size", 4)) == size, name


def test_chain_heads_point_into_this_block():
    import assemble_ntw as AN
    assert AN.T_HB_GATE == VA["t_hb_gate"] and AM.T_HB_RESTRIPE == VA["t_hb_restripe"]
    _cave, contents, _symbols = _yaml()
    assert "{abs32:t_hb_gate}" in str(contents["t_ntw_gate"]["bytes"]) and "t_mon_gate" not in str(contents["t_ntw_gate"]["bytes"])
    import pathlib
    import apply_patches as ap
    sites = {s["id"]: s for s in ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))[0]}
    rs = sites["Buffer_draw_2.mon_button_restripe"]
    assert int(rs["virtual_addr"]) == 0x5D84C0
    nb = bytes.fromhex(" ".join(str(rs["new_bytes"]).split()))
    assert nb[0] == 0xE9 and 0x5D84C5 + struct.unpack("<i", nb[1:5])[0] == VA["t_hb_restripe"]
    for s in SITES:
        y = sites[s["id"]]
        assert y["group"] == "holobook_scale" and int(y["virtual_addr"]) == s["va"]
        assert bytes.fromhex(" ".join(str(y["original_bytes"]).split())) == s["orig"]
        assert " ".join(str(y["new_bytes"]).split()) == s["new"], s["id"]
