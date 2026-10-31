"""Unicorn parity for the Planetary Monument bake (assemble_mon.py).

Oracle = scaling_laws.mon_* (the laws of hook_monument_proto.js v7d, measured-correct at 4K / 1600x1200 /
1920x1080).  Every thunk is emulated from its REAL assembled bytes at its REAL cave VA (pcave2 0x2B000..);
engine callees are recording stubs.  Covers: the build lever (num/letterbox/content rect/30 rects/both buttons
against the laws at 4:3-and-wider AND narrower-than-4:3 screens -- num through the shipped scale_uniform, the art
and buttons inside the screen over a grid --, native no-op at 1024x768 and in the narrow layout, builder failure
passthrough), the
palette LUT (all 32768 entries vs mon_nearest_lut), the resampler (bit-exact vs mon_resample on random
sources at 3 ratios incl. clipping), the panel scanline synthesis (vs mon_panel_synth on a synthetic monzoom:
striped trapezoid + a solid keyed block that must NOT match), the face restripe (NN-enlarged pair / tiled
idle face / solid face / no pair), the backdrop / picture / sprite wrappers' argument laws, the gate wrapper,
the font detour, and the sites' pristine-byte + instruction-boundary contracts.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import random
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
pytest.importorskip("capstone")
pytest.importorskip("pefile")

from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402
from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_ESP, UC_X86_REG_EBP,
)

import scaling_laws as SL  # noqa: E402
import assemble_se as SE  # noqa: E402
import apply_patches as ap  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_mon as AM  # noqa: E402

LAYOUT, CELLS, _END, NAMES = AM.assemble_all()
VA = dict(NAMES)
C = AM.CELL
REG = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
       "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "esp": UC_X86_REG_ESP, "ebp": UC_X86_REG_EBP, "eip": UC_X86_REG_EIP}
STACK, SP0 = 0x00300000, 0x00310000
STUB, REC = 0x00700000, 0x00720000
OBJ = 0x02000000               # fake MonumentWin / buffers / sprites
SCR = 0x02400000               # crt_malloc's answer (the scratch block)
PLANES = 0x02600000
TRAP = 0x11223344
_ks = Ks(KS_ARCH_X86, KS_MODE_32)
_cs = Cs(CS_ARCH_X86, CS_MODE_32)
RES = ((3840, 2160), (1600, 1200), (1920, 1080), (1024, 768))
# narrower than 4:3 (fix 11): the width term of num -- 1280x1024 = 20 (the user's shot: 21 put BACK off-screen),
# 1152x960 = 18, 2560x2048 = 40; 1024x1024 / 1080x1350 / 768x1024 have num <= 16 -> the native path
NARROW_RES = ((1280, 1024), (1152, 960), (2560, 2048), (1024, 1024), (1080, 1350), (768, 1024))


def _shipped_scale_uniform() -> bytes:
    """scale_uniform's SHIPPED bytes (patches.yaml menu_strip_thunks +0x00): t_mon_build / t_hof_build call it with
    eax = 16 for num (scaling_laws.mon_scale_num = scale_uniform(16, W, H)), so the harness runs the real helper."""
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    for c in caves:
        for ent in c.get("contents") or []:
            if ent["id"] == "scale_uniform":
                va = int(c["virtual_addr"]) + int(ent["offset"])
                assert va == AM.SCALE_UNIFORM == sym["scale_uniform"]
                return bytes(ap.ByteTemplate(" ".join(str(ent["bytes"]).split())).resolve(va, sym))
    raise AssertionError("scale_uniform is not in patches.yaml")


SCALE_UNIFORM_BYTES = _shipped_scale_uniform()


def asm(src, va=0):
    enc, _ = _ks.asm(src, va)
    return bytes(enc)


def r32(uc, a):
    return struct.unpack("<I", bytes(uc.mem_read(a, 4)))[0]


def r32s(uc, a):
    return struct.unpack("<i", bytes(uc.mem_read(a, 4)))[0]


def w32(uc, a, v):
    uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


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
        uc.mem_map(AM.PCAVE2, AM.SECTION_END)
        uc.mem_map(STACK, 0x20000)
        uc.mem_map(0x400000, 0x600000)          # exe image + engine objects + globals + stubs
        uc.mem_map(OBJ, 0x400000)
        uc.mem_map(SCR, 0x200000)
        uc.mem_map(PLANES, 0x400000)
        uc.mem_map(TRAP & 0xFFFFF000, 0x1000)
        self.rec = REC
        self.calls: list = []

    def _reset(self):
        uc = self.uc
        for name, (off, b) in LAYOUT.items():
            uc.mem_write(AM.PCAVE2 + off, b)
        try:
            uc.ctl_remove_cache(AM.PCAVE2 + AM.OFF_CODE, AM.PCAVE2 + AM.SECTION_END)   # a thunk stubbed by an earlier test must not keep its stub's JIT block
        except Exception:  # noqa: BLE001
            pass
        lo = min(C.values())
        uc.mem_write(lo, bytes(0x100))
        for _n, o, sz in AM.PLACED_CELLS:       # the fixed-slot cells outside the block (g_hof_field)
            uc.mem_write(AM.PCAVE2 + o, bytes(sz))
        try:
            uc.ctl_remove_cache(AM.PCAVE2 + AM.OFF_BD_FIELD, AM.PCAVE2 + AM.OFF_PLACED_END)
        except Exception:  # noqa: BLE001
            pass
        uc.mem_write(TRAP, bytes([0xF4]))
        uc.mem_write(AM.SCALE_UNIFORM, SCALE_UNIFORM_BYTES)
        try:
            uc.ctl_remove_cache(AM.SCALE_UNIFORM, AM.SCALE_UNIFORM + 0x40)
        except Exception:  # noqa: BLE001
            pass
        uc.mem_write(REC, bytes(0x1000))
        for r in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp"):
            uc.reg_write(REG[r], 0)
        self.calls = []
        self.hooks = []

    def stub(self, va, src):
        b = asm(src, va)
        self.uc.mem_write(va, b)
        try:
            self.uc.ctl_remove_cache(va, va + max(len(b), 0x40))   # a stub rewritten at the same VA must not keep its old JIT block
        except Exception:  # noqa: BLE001
            pass

    def stub_ret(self, va, retn: int, eax: int = 0, record: int | None = None):
        """A callee that (optionally) records its ecx + first 8 stack args at `record`, returns eax, cleans retn."""
        src = ""
        if record is not None:
            src += f"mov dword ptr [{record:#x}], ecx\n"
            for k in range(8):
                src += f"push eax\nmov eax, dword ptr [esp+{4 + 4 * (k + 1):#x}]\nmov dword ptr [{record + 4 + 4 * k:#x}], eax\npop eax\n"
        src += f"mov eax, {eax:#x}\nret {retn:#x}\n" if retn else f"mov eax, {eax:#x}\nret\n"
        self.stub(va, src)

    def run(self, start, until=TRAP, count=0, esp=SP0, **regs):
        uc = self.uc
        uc.reg_write(REG["esp"], esp)
        for r, v in regs.items():
            uc.reg_write(REG[r], v & 0xFFFFFFFF)
        uc.emu_start(start, until, count=count)

    def reg(self, r):
        return self.uc.reg_read(REG[r])


def set_screen(e, sw, sh, wide=1):
    w32(e.uc, AM.SW, sw)
    w32(e.uc, AM.SH, sh)
    w32(e.uc, AM.WIDE, wide)


def arm(e, sw, sh):
    """Cells as t_mon_build leaves them for a screen."""
    num = SL.mon_scale_num(sw, sh)
    lx, ly = SL.mon_letterbox(sw, sh, num)
    w32(e.uc, C["g_mon_num"], num)
    w32(e.uc, C["g_mon_armed"], 1 if num > 16 else 0)
    w32(e.uc, C["g_mon_lx"], lx)
    w32(e.uc, C["g_mon_ly"], ly)
    w32(e.uc, C["g_mon_ox"], lx + SL.mon_s(112, num))
    w32(e.uc, C["g_mon_oy"], ly + SL.mon_s(84, num))
    return num, lx, ly


def make_buffer(e, at, data, w, h, pitch, pal=None):
    """A Buffer object at `at` with its plane at `data`: data +0x54, w +0x80, h +0x84 (negative), pitch +0x4A8, table +0xA4."""
    uc = e.uc
    uc.mem_write(at, bytes(0x500))
    w32(uc, at + 0x54, data)
    w32(uc, at + 0x80, w)
    w32(uc, at + 0x84, (-h) & 0xFFFFFFFF)
    w32(uc, at + 0x4A8, pitch)
    if pal is not None:
        uc.mem_write(at + 0xA4, bytes(pal))


def rand_pal(seed=1):
    rnd = random.Random(seed)
    pal = bytearray()
    for i in range(256):
        pal += bytes([rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), 0])
    return bytes(pal)


# ---- sites ---------------------------------------------------------------------------------------------------
SITES = AM.site_list(NAMES)


def test_sites_match_the_pristine_base_and_end_on_instruction_boundaries():
    assert AM.verify_live(SITES) == []
    for s in SITES:
        b = SE.base_exe_bytes(s["va"], len(s["orig"]) + 16)
        ends = {i.address + i.size for i in _cs.disasm(b, s["va"])}
        assert s["va"] + len(s["orig"]) in ends, s["id"]
    ids = [s["id"] for s in SITES]
    assert len(ids) == len(set(ids)) == 27           # 16 mon_scale + 10 hof_scale + the retargeted face-blit head


def test_block_fits_the_grown_section_and_reuses_no_live_slot():
    assert AM.OFF_CODE == 0x2B000 and _END <= AM.SECTION_END
    # g_ts_flowcache ends at 0x2B000 (dl bake); nothing of ours may start below it
    placed = {n for n, _o, _fn in AM.PLACED_THUNKS}
    for name, (off, b) in LAYOUT.items():
        if name in placed:                      # the fixed slots outside the block: inside their reserved range
            assert AM.OFF_BD_FIELD <= off and off + len(b) <= AM.OFF_HOF_FIELD, name
            continue
        if name in {n for n, _o, _b in AM.PLACED_DATA}:     # the LUT range cells: reserved pcave2 0xDED6..0xDFFF
            assert 0xDED6 <= off and off + len(b) <= 0xDF00, name
            continue
        assert off >= 0x2B000, name


# ---- build lever --------------------------------------------------------------------------------------------
def _seed_build(e, sw, sh, wide=1, builder_ret=0):
    uc = e.uc
    set_screen(e, sw, sh, wide)
    uc.mem_write(AM.MW, bytes(0x3700))
    # native tables (the wide build's values) -- three of table A + synthetic others
    natA = [(319, 202, 479, 299), (256, 131, 771, 175), (213, 202, 813, 562)] + [(112 + 20 * i, 500 + i, 156 + 20 * i, 542 + i) for i in range(14)]
    natB = [(150 + 30 * i, 600, 200 + 30 * i, 640) for i in range(6)]
    natC = [(200 + 60 * i, 595, 258 + 60 * i, 645) for i in range(6)] + [(476, 195, 547, 259)]
    tables = {0x3134: natA, 0x334C: natB, 0x366C: natC}
    for off, rects in tables.items():
        for i, r in enumerate(rects):
            for k in range(4):
                w32(uc, AM.MW + off + i * 16 + k * 4, r[k])
    for k, v in enumerate((112, 84, 912, 684)):
        w32(uc, AM.MW + 0xA24 + 4 * k, v)
    for btn in (AM.BTN_CLOSE, AM.BTN_BACK):
        w32(uc, btn, STUB + 0x800)            # vtbl
        w32(uc, STUB + 0x800 + 0xF8, STUB + 0x300)   # +0xF8 = redraw stub
        for k, v in enumerate((824, 747, 1024, 768)):
            w32(uc, btn + 0x13C + 4 * k, v)
        for k, v in enumerate((0, 0, 200, 21)):
            w32(uc, btn + 0x474 + 4 * k, v)
    # engine stubs
    e.stub(AM.LOAD_MONICONS, f"mov dword ptr [{REC:#x}], ecx\nmov eax, {builder_ret}\nret\n")
    e.stub(AM.GW_RESIZE, f"""
        mov eax, dword ptr [{REC + 0x100:#x}]
        mov dword ptr [{REC + 0x104:#x}+eax*4], ecx
        push edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [{REC + 0x140:#x}+eax*4], edx
        mov edx, dword ptr [esp+0xC]
        mov dword ptr [{REC + 0x180:#x}+eax*4], edx
        mov edx, dword ptr [esp+0x10]
        mov dword ptr [{REC + 0x1C0:#x}+eax*4], edx
        pop edx
        inc eax
        mov dword ptr [{REC + 0x100:#x}], eax
        xor eax, eax
        ret 0xC
    """)
    e.stub(AM.GW_CLEAR, f"mov dword ptr [{REC + 0x200:#x}], ecx\nmov eax, [esp+4]\nmov dword ptr [{REC + 0x204:#x}], eax\ninc dword ptr [{REC + 0x208:#x}]\nret 4\n")
    # fonts v2: the button label font is t_fdirect_at(slot, 14, 1, num) (Arial 14 bold law on the Monument's
    # own slot; v1 asked the pool = Arial Narrow).  Recorder: count @+0x300, (slot, S, style, num) 16B each.
    e.stub(AM.T_FDIRECT_AT, f"""
        mov eax, dword ptr [{REC + 0x300:#x}]
        shl eax, 4
        push edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [{REC + 0x304:#x}+eax], edx
        mov edx, dword ptr [esp+0xC]
        mov dword ptr [{REC + 0x308:#x}+eax], edx
        mov edx, dword ptr [esp+0x10]
        mov dword ptr [{REC + 0x30C:#x}+eax], edx
        mov edx, dword ptr [esp+0x14]
        mov dword ptr [{REC + 0x310:#x}+eax], edx
        pop edx
        inc dword ptr [{REC + 0x300:#x}]
        mov eax, dword ptr [esp+4]
        ret
    """)
    e.stub(STUB + 0x300, f"mov eax, dword ptr [{REC + 0x400:#x}]\nmov dword ptr [{REC + 0x404:#x}+eax*4], ecx\ninc eax\nmov dword ptr [{REC + 0x400:#x}], eax\nret\n")
    return tables


@pytest.mark.parametrize("sw,sh", RES + NARROW_RES)
def test_build_lever_matches_the_laws(sw, sh):
    e = Emu()
    tables = _seed_build(e, sw, sh)
    uc = e.uc
    uc.mem_write(SP0, struct.pack("<I", TRAP))
    e.run(VA["t_mon_build"], ecx=AM.MW, esi=0x1234, ebx=0x5678, edi=0x9ABC, ebp=0xDEF0)
    assert e.reg("eax") == 0 and e.reg("esi") == 0x1234 and e.reg("ebx") == 0x5678 and e.reg("edi") == 0x9ABC and e.reg("ebp") == 0xDEF0
    assert r32(uc, REC) == AM.MW                                   # the builder ran with this = MonumentWin
    num = SL.mon_scale_num(sw, sh)
    armed = SL.mon_armed(sw, sh, 1)
    assert r32(uc, C["g_mon_num"]) == num
    assert r32(uc, C["g_mon_armed"]) == (1 if armed else 0)
    assert r32(uc, C["g_mon_lut_ok"]) == 0
    if not armed:
        assert r32(uc, REC + 0x100) == 0 and r32(uc, REC + 0x208) == 0 and r32(uc, REC + 0x300) == 0
        for off, rects in tables.items():
            for i, r in enumerate(rects):
                assert tuple(r32(uc, AM.MW + off + i * 16 + k * 4) for k in range(4)) == r
        assert tuple(r32(uc, AM.MW + 0xA24 + 4 * k) for k in range(4)) == (112, 84, 912, 684)
        return
    lx, ly = SL.mon_letterbox(sw, sh, num)
    assert (r32s(uc, C["g_mon_num"]), r32s(uc, C["g_mon_lx"]), r32s(uc, C["g_mon_ly"])) == (num, lx, ly)
    assert r32s(uc, C["g_mon_ox"]) == lx + SL.mon_s(112, num) and r32s(uc, C["g_mon_oy"]) == ly + SL.mon_s(84, num)
    # window: resize(SW, SH, 1) first, rects := screen, cleared to 0
    assert r32(uc, REC + 0x100) == 3
    assert (r32(uc, REC + 0x104), r32(uc, REC + 0x140), r32(uc, REC + 0x180), r32(uc, REC + 0x1C0)) == (AM.MW, sw, sh, 1)
    assert tuple(r32(uc, AM.MW + 0x13C + 4 * k) for k in range(4)) == (0, 0, sw, sh)
    assert tuple(r32(uc, AM.MW + 0x474 + 4 * k) for k in range(4)) == (0, 0, sw, sh)
    assert (r32(uc, REC + 0x200), r32(uc, REC + 0x204), r32(uc, REC + 0x208)) == (AM.MW, 0, 1)
    assert tuple(r32s(uc, AM.MW + 0xA24 + 4 * k) for k in range(4)) == SL.mon_content_rect(num, lx, ly)
    for off, rects in tables.items():
        for i, r in enumerate(rects):
            got = tuple(r32s(uc, AM.MW + off + i * 16 + k * 4) for k in range(4))
            assert got == SL.mon_rect(r, num, lx, ly), (off, i)
    # buttons: resize(s(200), s(21), 1), moved, own rect, label font, redrawn
    bx, by, bw, bh = SL.mon_button_rect(num, lx, ly)
    for n, btn in enumerate((AM.BTN_CLOSE, AM.BTN_BACK)):
        k = 1 + n
        assert (r32(uc, REC + 0x104 + 4 * k), r32(uc, REC + 0x140 + 4 * k), r32(uc, REC + 0x180 + 4 * k), r32(uc, REC + 0x1C0 + 4 * k)) == (btn, bw, bh, 1)
        assert tuple(r32s(uc, btn + 0x13C + 4 * j) for j in range(4)) == (bx, by, bx + bw, by + bh)
        assert tuple(r32s(uc, btn + 0x474 + 4 * j) for j in range(4)) == (0, 0, bw, bh)
        assert tuple(r32(uc, REC + 0x304 + 16 * n + 4 * j) for j in range(4)) == (AM.G_FONT_MON_BTN, SL.MON_FONT_LABEL, 1, num)
        assert SL.font_direct_law(SL.MON_FONT_LABEL, 1, num) == ("Arial", SL.mon_font_size(14, num), 1)
        assert r32(uc, btn + 0x970) == AM.G_FONT_MON_BTN
        assert r32(uc, REC + 0x404 + 4 * n) == btn
    assert r32(uc, REC + 0x300) == 2 and r32(uc, REC + 0x400) == 2
    # fix 11: the art and CLOSE / BACK lie inside the screen (num's width term)
    assert 0 <= lx and 0 <= ly and lx + SL.mon_s(1024, num) <= sw and ly + SL.mon_s(768, num) <= sh
    assert 0 <= bx and 0 <= by and bx + bw <= sw and by + bh <= sh


# a grid of screens (4:3-and-wider AND narrower, portrait included) + the num-step / 4:3 / clamp edges
BUILD_SWEEP = sorted({(w, h) for w in range(640, 7681, 353) for h in range(480, 4321, 251)} | set(RES) | set(NARROW_RES)
                     | {(1087, 816), (1088, 816), (1365, 1024), (1366, 1024), (1279, 960), (4607, 3456), (4608, 3456)})


def test_build_lever_num_is_scale_uniform_16_and_keeps_the_art_on_screen_over_a_sweep():
    """The REAL t_mon_build (calling the shipped scale_uniform): num / armed / letterbox == the law at every screen of
    the grid, and every armed layout keeps the art and both buttons inside the screen."""
    bad = []
    for sw, sh in BUILD_SWEEP:
        e = Emu()
        _seed_build(e, sw, sh)
        uc = e.uc
        uc.mem_write(SP0, struct.pack("<I", TRAP))
        e.run(VA["t_mon_build"], ecx=AM.MW)
        num = SL.mon_scale_num(sw, sh)
        armed = SL.mon_armed(sw, sh, 1)
        got = (r32s(uc, C["g_mon_num"]), r32(uc, C["g_mon_armed"]))
        if got != (num, int(armed)):
            bad.append((sw, sh, "num/armed", got, (num, armed)))
            continue
        if not armed:
            continue
        lx, ly = r32s(uc, C["g_mon_lx"]), r32s(uc, C["g_mon_ly"])
        if (lx, ly) != SL.mon_letterbox(sw, sh, num):
            bad.append((sw, sh, "letterbox", (lx, ly)))
        if lx < 0 or ly < 0 or lx + SL.mon_s(1024, num) > sw or ly + SL.mon_s(768, num) > sh:
            bad.append((sw, sh, "art off-screen", (lx, ly, num)))
        for btn in (AM.BTN_CLOSE, AM.BTN_BACK):
            l, t, r, b = (r32s(uc, btn + 0x13C + 4 * j) for j in range(4))
            if l < 0 or t < 0 or r > sw or b > sh:
                bad.append((sw, sh, "button off-screen", hex(btn), (l, t, r, b)))
    assert not bad, bad[:8]


def test_build_lever_narrow_layout_and_builder_failure_are_native():
    e = Emu()
    _seed_build(e, 3840, 2160, wide=0)
    e.uc.mem_write(SP0, struct.pack("<I", TRAP))
    e.run(VA["t_mon_build"], ecx=AM.MW)
    assert e.reg("eax") == 0 and r32(e.uc, C["g_mon_armed"]) == 0 and r32(e.uc, REC + 0x100) == 0
    e = Emu()
    _seed_build(e, 3840, 2160, builder_ret=1)
    w32(e.uc, C["g_mon_armed"], 1)
    e.uc.mem_write(SP0, struct.pack("<I", TRAP))
    e.run(VA["t_mon_build"], ecx=AM.MW)
    assert e.reg("eax") == 1 and r32(e.uc, C["g_mon_armed"]) == 1 and r32(e.uc, REC + 0x100) == 0   # untouched, result passed through


# ---- palette LUT ----------------------------------------------------------------------------------------------
def test_palette_lut_matches_the_law_for_every_15bit_colour():
    e = Emu()
    pal = rand_pal(7)
    e.uc.mem_write(PLANES, pal)
    e.uc.mem_write(SP0, struct.pack("<III", TRAP, PLANES, SCR))
    e.run(VA["t_mon_lut"], count=0)
    got = bytes(e.uc.mem_read(SCR, 32768))
    want = bytes(SL.mon_nearest_lut(pal))
    assert got == want
    assert SL.MON_KEY not in got
    assert (r32(e.uc, VA["g_mon_lut_lo"]), r32(e.uc, VA["g_mon_lut_hi"])) == (0, 256)   # the baked default range


@pytest.mark.parametrize("lo,hi", [(5, 20), (10, 11), (240, 256)])
def test_palette_lut_honours_the_search_range(lo, hi):
    """[g_mon_lut_lo, g_mon_lut_hi) narrows the search exactly like mon_nearest_lut(pal, lo, hi) (key 9 still
    skipped when inside the range)."""
    e = Emu()
    pal = rand_pal(11)
    w32(e.uc, VA["g_mon_lut_lo"], lo)
    w32(e.uc, VA["g_mon_lut_hi"], hi)
    e.uc.mem_write(PLANES, pal)
    e.uc.mem_write(SP0, struct.pack("<III", TRAP, PLANES, SCR))
    e.run(VA["t_mon_lut"], count=0)
    got = bytes(e.uc.mem_read(SCR, 32768))
    assert got == bytes(SL.mon_nearest_lut(pal, lo, hi))
    assert all(lo <= v < hi for v in set(got)) and SL.MON_KEY not in got


# ---- the splash's logo range (scaling_laws "STARTUP SPLASH": SPLASH_PAL_LO/HI) -------------------------------------
SYS_LO = ((0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0), (0, 0, 128), (128, 0, 128), (0, 128, 128),
          (192, 192, 192), (192, 220, 192), (166, 202, 240))                       # the Windows static colours
SYS_HI = ((255, 251, 240), (160, 160, 164), (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0), (0, 0, 255),
          (255, 0, 255), (0, 255, 255), (255, 255, 255))
LOGO_CROP = (448, 240, 64, 48)          # the dark-red ringing region (the 2026-10-11 4K shot's teal/olive/grey speckle)


def _logo_case():
    """The real logo.pcx loaded the engine's way (Buffer_load_pcx(.., 10, 236): pixels +10, its palette into
    entries 10..245) with the system colours in 0..9 / 246..255; a crop of its darkest-red region."""
    import config
    d = config.game_dir(required=False)
    p = d / "logo.pcx" if d else None
    if not p or not p.exists():
        pytest.skip("logo.pcx not found in the game folder")
    Image = pytest.importorskip("PIL.Image")
    im = Image.open(p)
    assert im.mode == "P" and max(im.tobytes()) < SL.SPLASH_PAL_COUNT
    p3 = im.getpalette()
    pal = bytearray()
    for r, g, b in SYS_LO:
        pal += bytes((b, g, r, 0))
    for i in range(SL.SPLASH_PAL_COUNT):
        r, g, b = p3[3 * i:3 * i + 3]
        pal += bytes((b, g, r, 0))
    for r, g, b in SYS_HI:
        pal += bytes((b, g, r, 0))
    W = im.size[0]
    a = im.tobytes()
    cx, cy, cw, ch = LOGO_CROP
    src = bytearray(cw * ch)
    for r in range(ch):
        src[r * cw:(r + 1) * cw] = bytes(v + SL.SPLASH_PAL_LO for v in a[(cy + r) * W + cx:(cy + r) * W + cx + cw])
    return bytes(pal), src, cw, ch


def test_splash_logo_resample_stays_in_the_logo_entries():
    """t_mon_lut + t_mon_resample at 45/16 with the splash range [10, 246): bit-exact against the law and no
    output index outside the logo's own entries -- while the default [0, 256) search on the same input picks
    the system colours (the bug this range fixes)."""
    pal, src, sw, sh = _logo_case()
    dw, dh = SL.mon_s(sw, 45), SL.mon_s(sh, 45)
    lut_r = SL.mon_nearest_lut(pal, SL.SPLASH_PAL_LO, SL.SPLASH_PAL_HI)
    want = bytearray(dw * dh)
    SL.mon_resample(src, sw, 0, 0, sw, sh, pal, want, dw, dw, dh, 0, 0, dw, dh, lut_r, True)
    assert all(SL.SPLASH_PAL_LO <= v < SL.SPLASH_PAL_HI for v in set(want))
    bug = bytearray(dw * dh)
    SL.mon_resample(src, sw, 0, 0, sw, sh, pal, bug, dw, dw, dh, 0, 0, dw, dh, SL.mon_nearest_lut(pal), True)
    assert sum(1 for v in bug if 0 < v < SL.SPLASH_PAL_LO or v >= SL.SPLASH_PAL_HI) > 0
    e = Emu()
    uc = e.uc
    SDATA, DDATA, DEST = PLANES, PLANES + 0x10000, OBJ
    uc.mem_write(SDATA, bytes(src))
    uc.mem_write(DDATA, bytes(dw * dh))
    make_buffer(e, DEST, DDATA, dw, dh, dw, pal)
    e.stub(AM.CRT_MALLOC, f"mov eax, {SCR:#x}\nret\n")
    w32(uc, C["g_mon_scratch"], 0)
    w32(uc, C["g_mon_lut_ok"], 0)
    w32(uc, VA["g_mon_lut_lo"], SL.SPLASH_PAL_LO)
    w32(uc, VA["g_mon_lut_hi"], SL.SPLASH_PAL_HI)
    uc.mem_write(SP0, struct.pack("<12I", TRAP, SDATA, sw, 0, 0, sw, sh, DEST, 0, 0, dw, dh))
    e.run(VA["t_mon_resample"])
    assert bytes(uc.mem_read(SCR, 32768)) == bytes(lut_r)
    assert bytes(uc.mem_read(DDATA, dw * dh)) == bytes(want)


# ---- resampler ---------------------------------------------------------------------------------------------------
def _resample_case(seed, sw, sh, dw, dh, dW, dH, dx, dy, sx=0, sy=0, spitch=None):
    rnd = random.Random(seed)
    spitch = spitch or sw + sx + 3
    src = bytearray(rnd.randrange(256) for _ in range(spitch * (sh + sy)))
    pal = rand_pal(seed + 100)
    lut = SL.mon_nearest_lut(pal)
    dpitch = dW + 5
    dst0 = bytearray(0xCC for _ in range(dpitch * dH))
    want = bytearray(dst0)
    SL.mon_resample(src, spitch, sx, sy, sw, sh, pal, want, dpitch, dW, dH, dx, dy, dw, dh, lut, True)
    return src, spitch, pal, lut, dpitch, dst0, want


@pytest.mark.parametrize("seed,sw,sh,dw,dh,dW,dH,dx,dy,sx,sy", [
    (1, 16, 12, 45, 34, 64, 48, 3, 2, 0, 0),         # 45/16 (4K)
    (2, 20, 9, 31, 14, 40, 20, 0, 0, 2, 1),          # 25/16 with a source sub-rect
    (3, 7, 5, 9, 7, 8, 6, -2, -1, 0, 0),             # 22/16, clipped on every edge
    (4, 3, 3, 12, 12, 12, 12, 0, 0, 0, 0),           # 4x, taps clamp at both ends
])
def test_resampler_is_bit_exact_against_the_law(seed, sw, sh, dw, dh, dW, dH, dx, dy, sx, sy):
    e = Emu()
    uc = e.uc
    src, spitch, pal, lut, dpitch, dst0, want = _resample_case(seed, sw, sh, dw, dh, dW, dH, dx, dy, sx, sy)
    SDATA, DDATA, DEST = PLANES, PLANES + 0x10000, OBJ
    uc.mem_write(SDATA, bytes(src))
    uc.mem_write(DDATA, bytes(dst0))
    make_buffer(e, DEST, DDATA, dW, dH, dpitch, pal)
    # crt_malloc -> SCR; the LUT is built by t_mon_lut inside (lut_ok == 0)
    e.stub(AM.CRT_MALLOC, f"mov dword ptr [{REC:#x}], 1\nmov eax, {SCR:#x}\nret\n")
    w32(uc, C["g_mon_scratch"], 0)
    w32(uc, C["g_mon_lut_ok"], 0)
    args = struct.pack("<12I", TRAP, SDATA, spitch, sx, sy, sw, sh, DEST, dx & 0xFFFFFFFF, dy & 0xFFFFFFFF, dw, dh)
    uc.mem_write(SP0, args)
    e.run(VA["t_mon_resample"], esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x2C and e.reg("esi") == 0x11 and e.reg("edi") == 0x22 and e.reg("ebx") == 0x33 and e.reg("ebp") == 0x44
    assert r32(uc, REC) == 1 and r32(uc, C["g_mon_scratch"]) == SCR and r32(uc, C["g_mon_lut_ok"]) == 1
    assert bytes(uc.mem_read(SCR, 32768)) == bytes(lut)
    got = bytes(uc.mem_read(DDATA, len(dst0)))
    assert got == bytes(want)
    assert got != bytes(dst0)


def test_resampler_reuses_the_lut_and_rejects_bad_geometry():
    e = Emu()
    uc = e.uc
    src, spitch, pal, lut, dpitch, dst0, want = _resample_case(9, 8, 6, 13, 10, 20, 16, 1, 1)
    SDATA, DDATA, DEST = PLANES, PLANES + 0x10000, OBJ
    uc.mem_write(SDATA, bytes(src))
    uc.mem_write(DDATA, bytes(dst0))
    make_buffer(e, DEST, DDATA, 20, 16, dpitch, pal)
    e.stub(AM.CRT_MALLOC, "hlt\n")                      # must not be called: scratch already set
    w32(uc, C["g_mon_scratch"], SCR)
    w32(uc, C["g_mon_lut_ok"], 1)
    uc.mem_write(SCR, bytes(lut))
    uc.mem_write(SP0, struct.pack("<12I", TRAP, SDATA, spitch, 0, 0, 8, 6, DEST, 1, 1, 13, 10))
    e.run(VA["t_mon_resample"])
    assert bytes(uc.mem_read(DDATA, len(dst0))) == bytes(want)
    for bad in ((0, 6, 13, 10), (8, 0, 13, 10), (8, 6, 0, 10), (8, 6, 13, 0), (8, 6, SL.MON_MAX_DW + 1, 10), (AM.MAX_SRC + 1, 6, 13, 10)):
        uc.mem_write(DDATA, bytes(dst0))
        uc.mem_write(SP0, struct.pack("<12I", TRAP, SDATA, spitch, 0, 0, bad[0], bad[1], DEST, 1, 1, bad[2], bad[3]))
        e.run(VA["t_mon_resample"])
        assert bytes(uc.mem_read(DDATA, len(dst0))) == bytes(dst0), bad


# ---- panel ----------------------------------------------------------------------------------------------------------
def _monzoom_like(seed=5, sw=640, sh=90):
    """A synthetic near backdrop: dithered sky, a striped trapezoid panel (light idx 240 / dark dithered rows), a solid
    keyed block (index 9, every row uniform) that must NOT be taken for the panel."""
    rnd = random.Random(seed)
    src = bytearray(rnd.choice((30, 31, 32, 33)) for _ in range(sw * sh))
    LIGHT = 240
    for k in range(12):                        # light rows 20, 22, ..., 42 ; dark rows in between
        y = 20 + 2 * k
        lo, hi = 60 - k, 480 + k                # trapezoid (>= 300 px of the light index per row)
        for x in range(lo, hi + 1):
            src[y * sw + x] = LIGHT
        for x in range(lo, hi + 1):
            src[(y + 1) * sw + x] = rnd.choice((100, 101, 102))
    for y in range(60, 80):                     # solid block: uniform rows (>= 300 px) but NO alternation
        for x in range(50, 450):
            src[y * sw + x] = 9
    return src, sw, sh, LIGHT


@pytest.mark.parametrize("num", (22, 25, 45))
def test_panel_synthesis_matches_the_law(num):
    e = Emu()
    uc = e.uc
    src, sw, sh, LIGHT = _monzoom_like()
    assert SL.mon_panel_rows(src, sw, sw, sh) == (LIGHT, 20, 12)
    dW = SL.mon_s(sw, num) + 10
    dH = SL.mon_s(sh, num) + 10
    dpitch = dW + 3
    dx, dy = 4, 6
    dst0 = bytearray(0xEE for _ in range(dpitch * dH))
    want = bytearray(dst0)
    res = SL.mon_panel_synth(src, sw, sw, sh, want, dpitch, dW, dH, dx, dy, num)
    assert res is not None and want != dst0
    SDATA, DDATA, SRC, DEST = PLANES, PLANES + 0x20000, OBJ, OBJ + 0x1000
    uc.mem_write(SDATA, bytes(src))
    uc.mem_write(DDATA, bytes(dst0))
    make_buffer(e, SRC, SDATA, sw, sh, sw)
    make_buffer(e, DEST, DDATA, dW, dH, dpitch)
    w32(uc, C["g_mon_num"], num)
    w32(uc, C["g_mon_scratch"], SCR)
    uc.mem_write(SP0, struct.pack("<5I", TRAP, SRC, DEST, dx, dy))
    e.run(VA["t_mon_panel"], esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x10 and e.reg("esi") == 0x11 and e.reg("ebx") == 0x33 and e.reg("ebp") == 0x44
    assert bytes(uc.mem_read(DDATA, len(dst0))) == bytes(want)
    # the law itself: light rows hN of every P device rows from Y0, dark rows never carry the light index
    Y0, Y1, P, hN = res
    assert (P, hN) == SL.mon_stripe(num)
    for y in range(Y0, Y1):
        row = want[y * dpitch:y * dpitch + dW]
        light = row.count(LIGHT)
        assert (light > 0) == (((y - Y0) % P) < hN), y


def test_panel_leaves_a_source_without_a_panel_alone():
    e = Emu()
    uc = e.uc
    rnd = random.Random(3)
    sw, sh = 400, 40
    src = bytearray(rnd.randrange(256) for _ in range(sw * sh))
    for y in range(10, 30):
        for x in range(sw):
            src[y * sw + x] = 9                        # solid block only
    assert SL.mon_panel_rows(src, sw, sw, sh) is None
    dst0 = bytes(0x55 for _ in range(200 * 100))
    SDATA, DDATA, SRC, DEST = PLANES, PLANES + 0x20000, OBJ, OBJ + 0x1000
    uc.mem_write(SDATA, bytes(src))
    uc.mem_write(DDATA, dst0)
    make_buffer(e, SRC, SDATA, sw, sh, sw)
    make_buffer(e, DEST, DDATA, 200, 100, 200)
    w32(uc, C["g_mon_num"], 45)
    w32(uc, C["g_mon_scratch"], SCR)
    uc.mem_write(SP0, struct.pack("<5I", TRAP, SRC, DEST, 0, 0))
    e.run(VA["t_mon_panel"])
    assert bytes(uc.mem_read(DDATA, len(dst0))) == dst0


# ---- face restripe ----------------------------------------------------------------------------------------------
def _face(kind, w, h, num, pal):
    """Canvas planes: 'nn' = the 1-px 201/109 dither NN-enlarged by num/16 (hover/pressed states); 'tiled' = the
    idle bevel fill at native 1-px pitch with a label; 'solid' = no pair; 'short' = alternation but runs > P+1."""
    P, _ = SL.mon_stripe(num)
    buf = bytearray(w * h)
    for y in range(h):
        if kind == "nn":
            ny = (y * 16) // num
            v = 201 if ny % 2 == 0 else 109
        elif kind == "tiled":
            v = 201 if (y + 1) % 2 == 0 else 109
        elif kind == "short":
            v = 201 if (y // (P + 2)) % 2 == 0 else 109
        else:
            v = 109
        for x in range(w):
            buf[y * w + x] = v
    if kind in ("nn", "tiled"):
        for y in range(h // 3, 2 * h // 3):          # a label: index 0 (never a pair member)
            for x in range(w // 4, w // 4 + 3):
                buf[y * w + x] = 0
    return buf


@pytest.mark.parametrize("num", (22, 25, 45))
@pytest.mark.parametrize("kind", ("nn", "tiled", "solid", "short"))
def test_face_restripe_matches_the_law(num, kind):
    e = Emu()
    uc = e.uc
    pal = bytearray(rand_pal(2))
    pal[201 * 4:201 * 4 + 4] = bytes((6, 8, 32, 0))       # (b,g,r): dark
    pal[109 * 4:109 * 4 + 4] = bytes((12, 12, 136, 0))    # red
    bw, bh = SL.mon_s(200, num), SL.mon_s(21, num)
    buf = _face(kind, bw, bh, num, pal)
    want = bytearray(buf)
    res = SL.mon_face_restripe(want, bw, bw, bh, bytes(pal), num)
    if kind in ("nn", "tiled"):
        assert res is not None and res[2] == 109 and want != buf        # v2: the BRIGHTER member (red 109) is the wide/top one
    else:
        assert res is None and want == buf
    DDATA, CANVAS = PLANES, AM.BTN_CLOSE + 0x444
    uc.mem_write(DDATA, bytes(buf))
    make_buffer(e, CANVAS, DDATA, bw, bh, bw, bytes(pal))
    w32(uc, C["g_mon_num"], num)
    w32(uc, C["g_mon_armed"], 1)
    # through the Buffer_draw_2 detour: displaced prologue replayed, resume reached, all registers intact
    e.stub(AM.BUFFER_DRAW2_RESUME, f"mov dword ptr [{REC:#x}], esp\nmov dword ptr [{REC + 4:#x}], ecx\nhlt\n")
    uc.mem_write(SP0 - 0x20, bytes(0x20))
    e.run(VA["t_mon_restripe"], until=AM.BUFFER_DRAW2_RESUME + 12, ecx=CANVAS, eax=1, ebx=2, edx=3, esi=4, edi=5, ebp=6)
    assert r32(uc, REC) == SP0 - 0x18 - 8 and r32(uc, REC + 4) == CANVAS
    assert (e.reg("eax"), e.reg("ebx"), e.reg("edx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (1, 2, 3, 4, 5, 6)
    assert bytes(uc.mem_read(SP0 - 0x18 - 8, 8)) == struct.pack("<II", 6, 2)    # push ebx / push ebp replayed
    assert bytes(uc.mem_read(DDATA, len(buf))) == bytes(want)
    if kind == "nn":
        P, hN = SL.mon_stripe(num)
        for y in range(bh):
            row = want[y * bw:(y + 1) * bw]
            assert set(row) - {0} == ({109} if (y % P) < hN else {201}), y


def test_face_restripe_ignores_other_buffers_and_native_scale():
    e = Emu()
    uc = e.uc
    pal = rand_pal(2)
    bw, bh = 40, 12
    buf = _face("nn", bw, bh, 45, pal)
    DDATA = PLANES
    uc.mem_write(DDATA, bytes(buf))
    make_buffer(e, OBJ, DDATA, bw, bh, bw, pal)
    w32(uc, C["g_mon_num"], 45)
    w32(uc, C["g_mon_armed"], 1)
    e.stub(AM.BUFFER_DRAW2_RESUME, "hlt\n")
    e.run(VA["t_mon_restripe"], until=AM.BUFFER_DRAW2_RESUME + 1, ecx=OBJ)
    assert bytes(uc.mem_read(DDATA, len(buf))) == bytes(buf)
    make_buffer(e, AM.BTN_BACK + 0x444, DDATA, bw, bh, bw, pal)
    w32(uc, C["g_mon_armed"], 0)
    e.run(VA["t_mon_restripe"], until=AM.BUFFER_DRAW2_RESUME + 1, ecx=AM.BTN_BACK + 0x444)
    assert bytes(uc.mem_read(DDATA, len(buf))) == bytes(buf)


# ---- wrappers: backdrops / picture / sprites -------------------------------------------------------------------------
def _rec_resample(e):
    """Replace t_mon_resample / t_mon_panel by recorders (11 / 4 args), keeping their contracts."""
    e.stub(VA["t_mon_resample"], "".join(f"mov eax, dword ptr [esp+{4 + 4 * k}]\nmov dword ptr [{REC + 4 * k:#x}], eax\n" for k in range(11))
           + f"inc dword ptr [{REC + 0x80:#x}]\nret 0x2C\n")
    e.stub(VA["t_mon_panel"], "".join(f"mov eax, dword ptr [esp+{4 + 4 * k}]\nmov dword ptr [{REC + 0x100 + 4 * k:#x}], eax\n" for k in range(4))
           + f"inc dword ptr [{REC + 0x180:#x}]\nret 0x10\n")


@pytest.mark.parametrize("sw,sh", RES[:3])
@pytest.mark.parametrize("thunk", ("t_mon_bd_far", "t_mon_bd_near", "t_mon_pic"))
def test_copy4_wrappers_place_the_resample_by_the_law(sw, sh, thunk):
    e = Emu()
    uc = e.uc
    num, lx, ly = arm(e, sw, sh)
    _rec_resample(e)
    SRC, DEST = OBJ, OBJ + 0x1000
    make_buffer(e, SRC, PLANES, 1024, 768, 1030)
    make_buffer(e, DEST, PLANES + 0x100000, sw, sh, sw)
    if thunk == "t_mon_pic":
        sx, sy, dx, dy, w, h = 341, 11, 700, 560, 600, 360
    else:
        sx, sy, dx, dy, w, h = 0, 0, 0, 0, 1024, 768
    uc.mem_write(SP0, struct.pack("<8I", TRAP, DEST, sx, sy, dx, dy, w, h))
    e.run(VA[thunk], ecx=SRC, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x1C and e.reg("eax") == 0
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    assert r32(uc, REC + 0x80) == 1
    got = [r32s(uc, REC + 4 * k) for k in range(11)]
    if thunk == "t_mon_pic":
        want_xy = (dx, dy)
    else:
        want_xy = (lx + SL.mon_s(dx, num), ly + SL.mon_s(dy, num))
    assert got == [PLANES, 1030, sx, sy, w, h, DEST, want_xy[0], want_xy[1], SL.mon_s(w, num), SL.mon_s(h, num)]
    if thunk == "t_mon_bd_near":
        assert r32(uc, REC + 0x180) == 1
        assert [r32s(uc, REC + 0x100 + 4 * k) for k in range(4)] == [SRC, DEST, want_xy[0], want_xy[1]]
    else:
        assert r32(uc, REC + 0x180) == 0


@pytest.mark.parametrize("thunk", ("t_mon_bd_far", "t_mon_bd_near", "t_mon_pic"))
def test_copy4_wrappers_are_the_native_blit_when_not_armed(thunk):
    e = Emu()
    w32(e.uc, C["g_mon_armed"], 0)
    e.stub(AM.COPY4, f"mov dword ptr [{REC:#x}], ecx\nmov eax, dword ptr [esp+4]\nmov dword ptr [{REC + 4:#x}], eax\nmov eax, 0x77\nret 0x1C\n")
    e.uc.mem_write(SP0, struct.pack("<8I", TRAP, 0xD0, 1, 2, 3, 4, 5, 6))
    e.run(VA[thunk], ecx=0x5A)
    assert (r32(e.uc, REC), r32(e.uc, REC + 4), e.reg("eax"), e.reg("esp")) == (0x5A, 0xD0, 0x77, SP0 + 4 + 0x1C)


def _sprite(e, at, data, pitch, w, h, offx=0, offy=0, key=9):
    uc = e.uc
    uc.mem_write(at, bytes(0x40))
    w32(uc, at + 4, data)
    w32(uc, at + 8, key)
    w32(uc, at + 0xC, pitch)
    w32(uc, at + 0x10, w)
    w32(uc, at + 0x14, h)
    w32(uc, at + 0x20, offx)
    w32(uc, at + 0x24, offy)


@pytest.mark.parametrize("sw,sh", RES[:3])
def test_sprite_wrappers_forward_by_the_law(sw, sh):
    e = Emu()
    uc = e.uc
    num, lx, ly = arm(e, sw, sh)
    _rec_resample(e)
    # scale_nn recorder: Sprite_draw_2 contract (ecx sprite; dest,key,x,y,num,den; ret 0x18)
    e.stub(AM.SCALE_NN, f"mov dword ptr [{REC + 0x200:#x}], ecx\n" + "".join(f"mov eax, dword ptr [esp+{4 + 4 * k}]\nmov dword ptr [{REC + 0x204 + 4 * k:#x}], eax\n" for k in range(6)) + "ret 0x18\n")
    SPR, DEST = OBJ, OBJ + 0x1000
    _sprite(e, SPR, PLANES, 160, 160, 97, offx=0, offy=0)
    uc.mem_write(SP0, struct.pack("<5I", TRAP, DEST, 9, 1377, 568))
    e.run(VA["t_mon_spr_nn"], ecx=SPR, esi=0x11, ebx=0x33)
    assert e.reg("esp") == SP0 + 4 + 0x10 and (e.reg("esi"), e.reg("ebx")) == (0x11, 0x33)
    assert r32(uc, REC + 0x200) == SPR and [r32(uc, REC + 0x204 + 4 * k) for k in range(6)] == [DEST, 9, 1377, 568, num, 16]
    # the picture: resampled at x + off*num/16, s(w) x s(h); pitch from +0xC (fallback +0x10)
    for pitch, offx, offy in ((160, 0, 0), (0, 3, 5), (200, 7, 0)):
        _sprite(e, SPR, PLANES, pitch, 160, 97, offx, offy)
        uc.mem_write(SP0, struct.pack("<5I", TRAP, DEST, 9, 1377, 568))
        e.run(VA["t_mon_spr_pic"], ecx=SPR, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
        assert e.reg("esp") == SP0 + 4 + 0x10 and (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
        got = [r32s(uc, REC + 4 * k) for k in range(11)]
        assert got == [PLANES, pitch or 160, 0, 0, 160, 97, DEST, 1377 + (offx * num) // 16, 568 + (offy * num) // 16, SL.mon_s(160, num), SL.mon_s(97, num)]


def test_sprite_wrappers_native_paths():
    e = Emu()
    uc = e.uc
    e.stub(AM.BLIT_CORE, f"mov dword ptr [{REC:#x}], ecx\nmov eax, dword ptr [esp+4]\nmov dword ptr [{REC + 4:#x}], eax\nmov eax, 0x66\nret 0x10\n")
    for thunk in ("t_mon_spr_nn", "t_mon_spr_pic"):
        w32(uc, C["g_mon_armed"], 0)
        uc.mem_write(SP0, struct.pack("<5I", TRAP, 0xD0, 9, 1, 2))
        e.run(VA[thunk], ecx=0x5A)
        assert (r32(uc, REC), r32(uc, REC + 4), e.reg("eax"), e.reg("esp")) == (0x5A, 0xD0, 0x66, SP0 + 4 + 0x10)
    # armed but a sprite without data -> the engine core, registers restored
    arm(e, 3840, 2160)
    SPR = OBJ
    _sprite(e, SPR, 0, 160, 160, 97)
    uc.mem_write(SP0, struct.pack("<5I", TRAP, 0xD1, 9, 1, 2))
    e.run(VA["t_mon_spr_pic"], ecx=SPR, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert (r32(uc, REC), r32(uc, REC + 4), e.reg("esp")) == (SPR, 0xD1, SP0 + 4 + 0x10)
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)


# ---- gate + font -----------------------------------------------------------------------------------------------------
def test_gate_wrapper_admits_only_the_two_monument_buttons_when_armed():
    e = Emu()
    uc = e.uc
    e.stub(AM.GATE_PRE, f"mov dword ptr [{REC:#x}], esi\nmov eax, 0x42\nret\n")
    for armed, btn, want in ((1, AM.BTN_CLOSE, 1), (1, AM.BTN_BACK, 1), (1, 0x12345, 0x42), (0, AM.BTN_CLOSE, 0x42), (0, AM.BTN_BACK, 0x42)):
        w32(uc, C["g_mon_armed"], armed)
        w32(uc, REC, 0)
        uc.mem_write(SP0, struct.pack("<I", TRAP))
        e.run(VA["t_mon_gate"], esi=btn)
        assert e.reg("eax") == want and e.reg("esp") == SP0 + 4
        assert r32(uc, REC) == (btn if want == 0x42 else 0)


@pytest.mark.parametrize("sw,sh", RES)
def test_font_detour_swaps_the_plaque_font_by_the_law(sw, sh):
    e = Emu()
    uc = e.uc
    num, _, _ = arm(e, sw, sh)
    w32(uc, AM.PLAQUE_FONT, 0x8888)
    # v2: t_ffn_at(g_font_mon_plaque, 12, 0, num) = Arial 12 REGULAR scaled on the Monument's own slot (never fails)
    e.stub(AM.T_FFN_AT, f"mov eax, dword ptr [esp+4]\nmov dword ptr [{REC:#x}], eax\nmov eax, dword ptr [esp+8]\nmov dword ptr [{REC + 4:#x}], eax\n"
                        f"mov eax, dword ptr [esp+0xC]\nmov dword ptr [{REC + 8:#x}], eax\nmov eax, dword ptr [esp+0x10]\nmov dword ptr [{REC + 0xC:#x}], eax\n"
                        f"mov eax, dword ptr [esp+4]\nret\n")
    e.stub(AM.FONT_RESUME, "hlt\n")
    e.run(VA["t_mon_font"], until=AM.FONT_RESUME + 1, ecx=0x11, edx=0x22, esi=0x33, ebx=0x44, edi=0x55)
    assert (e.reg("ecx"), e.reg("edx"), e.reg("esi"), e.reg("ebx"), e.reg("edi"), e.reg("esp")) == (0x11, 0x22, 0x33, 0x44, 0x55, SP0)
    if num > 16:
        assert e.reg("eax") == AM.G_FONT_MON_PLAQUE
        assert tuple(r32(uc, REC + 4 * j) for j in range(4)) == (AM.G_FONT_MON_PLAQUE, SL.MON_FONT_PLAQUE, 0, num)
        assert SL.font_face_law(SL.MON_FONT_PLAQUE, 0, num) == ("init", "Arial", SL.mon_font_size(12, num), 0)
    else:
        assert e.reg("eax") == 0x8888 and r32(uc, REC) == 0
