"""Unicorn parity for the diplo_talk_scale thunks (assemble_diplo.py).

Oracle = the user-verified prototype (hook_diplo_proto.js v9d/v10) log values at g=40 (4K, MainWin
seeds / DiploTalkWin rect table / popup fields from frida_diplo_proto.log) and g=25 (1600x1200);
plus register/stack contracts.  Every thunk is emulated from its REAL assembled bytes at its REAL
cave VA; the native callees are landing pads (emulation stops when EIP reaches one).
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
pytest.importorskip("pefile")

from unicorn import UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_diplo as AD  # noqa: E402

LAYOUT, _END = AD.assemble_all()
R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
     "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}
STACK = 0x00300000
SP0 = STACK + 0x8000
POPUP = 0x03000000
D_OBJ = 0x03100000
LANDINGS = [AD.BASEBTN_INIT, AD.BOX_SPRITE, AD.CENT7, AD.SPRITE_DRAW_2, AD.WRAP_CENT_6, AD.WRAP_3, AD.WRITE_L_3,
            AD.GET_PIXEL, AD.HLINE_2, AD.FLIC_INIT, AD.FLIC_DRAW, AD.GWIN_FILL_2, AD.THUNK_BOX_THICK,
            AD.THUNK_DEVFILL, AD.THUNK_SCALE_BOXW, AD.THUNK_GROW_BOX, AD.THUNK_BTN_VCENTER, AD.THUNK_ORN_CHILDX,
            AD.THUNK_Q16_FILL, AD.THUNK_FACTION_WRAPWIDTH, AD.THUNK_POPUP_ARTALIGN, AD.GWIN_INIT, AD.ITEM_BACK_DRAW, AD.ART_DRAW, AD.PARITY_NN, AD.SPR_STRIPES,
            0x603D88, 0x602867, 0x602C51, 0x60393D, 0x6039B1, 0x600100, 0x440AF7, 0x440AE5, 0x440B3A, 0x440B6D, 0x440B83]
RET_SITE = 0x600100

# --- 4K (g=40) world from the proto logs -----------------------------------------------------
SEEDS40 = {"D80": (10, 140, 612, 630), "D90": (1947, 140, 2550, 630), "DB0": (610, 470, 1920, 630),
           "DC0": (655, 165, 1907, 585), "A8C": (2260, 535, 2395, 615), "A9C": (2400, 535, 2535, 615)}
TABLE40_PRE = {0x20C4: (14, 144, 498, 164), 0x20D4: (14, 166, 498, 626), 0x20E4: (501, 144, 608, 626), 0x20F4: (662, 172, 1900, 555),
               0x2114: (1951, 144, 2546, 529), 0x2124: (662, 558, 1279, 578), 0x2134: (1282, 558, 1899, 578), 0x2144: (1962, 535, 2257, 615)}
TABLE40_POST = {0x20C4: (20, 150, 328, 200), 0x20D4: (20, 205, 328, 620), 0x20E4: (335, 150, 602, 620), 0x20F4: (672, 182, 1890, 510),
                0x2114: (1957, 150, 2540, 520), 0x2124: (672, 518, 1277, 568), 0x2134: (1284, 518, 1889, 568), 0x2144: (1962, 535, 2253, 615)}
SEEDS25 = {"D80": (6, 87, 382, 393), "D90": (1217, 87, 1593, 393), "DB0": (381, 293, 1200, 393),
           "DC0": (409, 103, 1192, 365), "A8C": (1412, 334, 1496, 384), "A9C": (1500, 334, 1584, 384)}
TABLE25_PRE = {0x20E4: (271, 91, 378, 389), 0x20F4: (416, 110, 1185, 335)}
TABLE25_POST = {0x20C4: (12, 93, 205, 124), 0x20D4: (12, 127, 205, 387), 0x20E4: (209, 93, 376, 387), 0x20F4: (419, 113, 1182, 319),
                0x2114: (1223, 93, 1587, 325), 0x2124: (419, 324, 798, 355), 0x2134: (802, 324, 1181, 355), 0x2144: (1226, 334, 1408, 384)}
CLIP40 = (0, 0, 1750, 1125)


class Emu:
    def __init__(self, g):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        for base, size in ((0x668000, 0x1000), (0x733000, 0x6000), (0x7AF000, 0x1000), (0x600000, 0x4000), (0x5D4000, 0x1000),
                           (0x5DC000, 0x3000), (0x5E1000, 0x4000), (0x607000, 0x1000), (0x629000, 0x2000), (0x440000, 0x1000),
                           (0x405000, 0x1000), (0xA0C000, 0x31000), (0x645000, 0x1000), (0x5D7000, 0x1000), (0x5D9000, 0x1000),
                           (STACK, 0x10000), (POPUP, 0x4000), (D_OBJ, 0x1000), (0x05000000, 0x1000)):
            uc.mem_map(base, size)
        for name, (off, blob) in LAYOUT.items():
            uc.mem_write(AD.PCAVE2_VA + off, blob)
        uc.mem_write(AD.G, g.to_bytes(4, "little", signed=True))
        mapped = set()
        for a in LANDINGS + [AD.CRT_MALLOC, AD.BUF_CTOR, AD.BUF_RESIZE, AD.BUF_COPY_3]:
            pg = a & ~0xFFF
            if pg not in mapped:
                try:
                    uc.mem_map(pg, 0x1000)
                except Exception:  # noqa: BLE001  (already covered by a bigger map)
                    pass
                mapped.add(pg)
            uc.mem_write(a, b"\xf4")           # hlt (never executed; we stop on arrival)
        self.stopped_at = None
        uc.hook_add(UC_HOOK_CODE, self._hook)
        self.landings = set(LANDINGS)

    def _hook(self, uc, addr, size, ud):
        if addr in self.landings and addr not in (self._start,):
            self.stopped_at = addr
            uc.emu_stop()

    def w32(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "little", signed=True)

    def rect(self, addr):
        return tuple(self.r32(addr + 4 * i) for i in range(4))

    def wrect(self, addr, r):
        for i, v in enumerate(r):
            self.w32(addr + 4 * i, v)

    def seeds(self, S):
        for k, r in S.items():
            self.wrect(AD.SEED[k], r)

    def run(self, thunk, regs=None, stack=None, extra_landing=()):
        """stack: list of dwords, stack[0] lands at [esp] (the return address)."""
        uc = self.uc
        self._start = AD.PCAVE2_VA + LAYOUT[thunk][0]
        for a in extra_landing:
            self.landings.add(a)
        sp = SP0
        stack = list(stack or [RET_SITE])
        sp -= 4 * len(stack)
        for i, v in enumerate(stack):
            self.w32(sp + 4 * i, v)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_EBP, sp + 0x400)
        for k, v in (regs or {}).items():
            uc.reg_write(R[k], v & 0xFFFFFFFF)
        self.sp_in = sp
        uc.emu_start(self._start, 0, count=20000)
        assert self.stopped_at is not None, f"{thunk}: never reached a landing (eip={uc.reg_read(UC_X86_REG_EIP):#x})"
        return self

    def reg(self, k):
        v = self.uc.reg_read(R[k])
        return v - (1 << 32) if v & 0x80000000 else v

    def st(self, off):
        return self.r32(self.reg("esp") + off)


def popup_fields(e, **f):
    for k, v in f.items():
        e.w32(POPUP + int(k[1:], 16), v)


# ============================================================================= STRIP HALF
@pytest.mark.parametrize("g,seeds,pre,post,args_in,args_out", [
    (40, SEEDS40, TABLE40_PRE, TABLE40_POST, (662, 558, 617, 20), (672, 518, 605, 50)),
    (25, SEEDS25, TABLE25_PRE, TABLE25_POST, (416, 338, 383, 20), (419, 324, 379, 31)),
])
def test_rect_table(g, seeds, pre, post, args_in, args_out):
    e = Emu(g)
    e.seeds(seeds)
    for off, r in pre.items():
        e.wrect(AD.TW + off, r)
    x, y, w, h = args_in
    e.run("t_dp_table", regs={"ebx": 0x11111111, "esi": AD.TW, "edi": 0x22222222},
          stack=[RET_SITE, 0xAAAA, 0, x, y, w, h, 0x7AE820, 0])
    assert e.stopped_at == AD.BASEBTN_INIT
    for off, r in post.items():
        assert e.rect(AD.TW + off) == r, f"{off:#x}: {e.rect(AD.TW + off)} != {r}"
    assert (e.st(0xC), e.st(0x10), e.st(0x14), e.st(0x18)) == args_out
    assert e.reg("esp") == e.sp_in and e.reg("ebx") == 0x11111111 and e.reg("esi") == AD.TW and e.reg("edi") == 0x22222222


def test_rect_table_native_at_g16():
    e = Emu(16)
    e.seeds(SEEDS40)
    for off, r in TABLE40_PRE.items():
        e.wrect(AD.TW + off, r)
    e.run("t_dp_table", stack=[RET_SITE, 0, 0, 1, 2, 3, 4, 0, 0])
    assert e.stopped_at == AD.BASEBTN_INIT
    for off, r in TABLE40_PRE.items():
        assert e.rect(AD.TW + off) == r
    assert (e.st(0xC), e.st(0x10), e.st(0x14), e.st(0x18)) == (1, 2, 3, 4)


def _box(e, thunk, rect_in, ecx=AD.MW_CANVAS):
    RECT = STACK + 0x100
    e.wrect(RECT, rect_in)
    e.run(thunk, regs={"ecx": ecx, "ebx": 5, "esi": 6, "edi": 7}, stack=[RET_SITE, RECT, 0x78D528])
    assert e.stopped_at == AD.BOX_SPRITE and e.reg("ecx") == ecx and e.reg("esp") == e.sp_in
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (5, 6, 7)
    return e.rect(RECT)


def test_box_adapters_4k():
    e = Emu(40)
    e.seeds(SEEDS40)
    for off, r in TABLE40_POST.items():
        e.wrect(AD.TW + off, r)
    assert _box(e, "t_dp_box_centre", (659, 169, 1903, 581)) == (665, 175, 1897, 575)
    assert _box(Emu(40) if False else e, "t_dp_box_hqunion", (1959, 532, 2538, 618)) == (1955, 528, 2542, 622)
    assert _box(e, "t_dp_box_panel", (672, 182, 1279, 510)) == (672, 182, 1277, 510)
    assert e.rect(AD.CELL_VA["g_dp_panel"]) == (672, 182, 1277, 510)
    assert _box(e, "t_dp_box_panel", (1282, 182, 1889, 510)) == (1284, 182, 1889, 510)
    assert e.rect(AD.CELL_VA["g_dp_panel"]) == (1284, 182, 1889, 510)
    assert _box(e, "t_dp_box_hq", (1957, 150, 2540, 516)) == (1957, 150, 2540, 510)


def test_box_native_g16_passthrough():
    e = Emu(16)
    e.seeds(SEEDS40)
    for off, r in TABLE40_POST.items():
        e.wrect(AD.TW + off, r)
    assert _box(e, "t_dp_box_centre", (1, 2, 3, 4)) == (1, 2, 3, 4)
    assert _box(e, "t_dp_box_panel", (1, 2, 3, 4)) == (1, 2, 3, 4)


def _c7(e, thunk, rect_in):
    RECT = STACK + 0x100
    e.wrect(RECT, rect_in)
    e.run(thunk, regs={"ecx": AD.MW_CANVAS, "ebx": 5, "esi": 6}, stack=[RET_SITE, 0x700000, RECT, 7])
    assert e.stopped_at == AD.CENT7 and e.reg("ecx") == AD.MW_CANVAS and e.reg("esp") == e.sp_in and e.reg("ebx") == 5 and e.reg("esi") == 6
    return e.rect(RECT)


def test_cent7_adapters_4k():
    e = Emu(40)
    for off, r in TABLE40_POST.items():
        e.wrect(AD.TW + off, r)
    assert _c7(e, "t_dp_c7_bio", (23, 153, 325, 197)) == (27, 157, 321, 193)
    assert _c7(e, "t_dp_c7_hq", (1958, 151, 2539, 171)) == (1959, 152, 2538, 202)


def _sd2(e, thunk, spr_wh, xy, num_den=(1, 1), dest=AD.MW_CANVAS, tail=AD.SPRITE_DRAW_2):
    SPR = STACK + 0x200
    e.w32(SPR + 0x18, spr_wh[0]); e.w32(SPR + 0x1C, spr_wh[1])
    e.run(thunk, regs={"ecx": SPR, "ebx": 5, "esi": 6, "edi": 7}, stack=[RET_SITE, dest, 9, xy[0], xy[1], num_den[0], num_den[1]])
    assert e.stopped_at == tail and e.reg("ecx") == SPR and e.reg("esp") == e.sp_in
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (5, 6, 7)
    return (e.st(0xC), e.st(0x10), e.st(0x14), e.st(0x18))


def test_sprite_adapters_4k():
    e = Emu(40)
    for off, r in TABLE40_POST.items():
        e.wrect(AD.TW + off, r)
    e.wrect(AD.CELL_VA["g_dp_panel"], (672, 182, 1277, 510))
    e.w32(AD.TW + 0xA6C, -1); e.w32(AD.TW + 0xA6C + 0xC, 42)             # font14b: pad -1 -> cell 42
    assert _sd2(e, "t_dp_sd2_bar", (9, 147), (310, 339), tail=AD.ART_DRAW) == (284, 229, 40, 16)   # -> thunk_art_draw (re-blit; 2026-09-21)
    assert _sd2(e, "t_dp_sd2_logo", (65, 50), (675, 230), tail=AD.SPR_STRIPES) == (679, 238, 40, 16)
    assert e.r32(AD.CELL_VA["g_dp_logow"]) == 162
    assert _sd2(e, "t_dp_sd2_hqpic", (233, 124), (2132, 203), tail=AD.ART_DRAW) == (1958, 204, 40, 16)   # -> thunk_art_draw (re-blit)
    assert _sd2(e, "t_dp_sd2_bezel", (600, 200), (1200, 300)) == (1200, 300, 40, 16)
    assert _sd2(e, "t_dp_sd2_bezel", (600, 200), (1200, 300), (3, 4)) == (1200, 300, 3, 4)   # non-1/1 untouched
    # font with positive pad: [f]=2 -> [f+0x10]+2
    e.w32(AD.TW + 0xA6C, 2); e.w32(AD.TW + 0xA6C + 0x10, 40)
    assert _sd2(e, "t_dp_sd2_logo", (65, 50), (675, 230), tail=AD.SPR_STRIPES) == (679, 238, 40, 16)


def test_cent6_and_status_text_4k():
    e = Emu(40)
    e.wrect(AD.CELL_VA["g_dp_panel"], (672, 182, 1277, 510))
    e.w32(AD.CELL_VA["g_dp_logow"], 162)
    e.w32(AD.TW + 0xA6C, -1); e.w32(AD.TW + 0xA6C + 0xC, 42)
    RECT = STACK + 0x100
    e.wrect(RECT, (675, 187, 1274, 227))
    # the native wrap_cent_6 returns 236 (bottom y) and cleans its 2 args
    ks = AD.ks
    enc, _ = ks.asm("mov eax, 236\nret 8", AD.WRAP_CENT_6)
    e.uc.mem_write(AD.WRAP_CENT_6, bytes(enc))
    e.landings.discard(AD.WRAP_CENT_6)
    e.run("t_dp_cent6", regs={"ecx": AD.MW_CANVAS, "ebx": 5, "esi": 6, "edi": 7}, stack=[RET_SITE, 0x700000, RECT])
    assert e.stopped_at == RET_SITE and e.reg("eax") == 240 and e.reg("esp") == e.sp_in + 12   # ret 8 (thiscall) + ret addr
    assert e.rect(RECT) == (679, 194, 1270, 231)
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (5, 6, 7)
    # wrap_3: x, w
    e.run("t_dp_txt_wrap3", regs={"ecx": AD.MW_CANVAS}, stack=[RET_SITE, 0x700000, 745, 239, 999])
    assert e.stopped_at == AD.WRAP_3 and (e.st(8), e.st(0xC), e.st(0x10)) == (853, 239, 410)
    e.run("t_dp_txt_wl3", regs={"ecx": AD.MW_CANVAS}, stack=[RET_SITE, 0x700000, 835, 351, 10])
    assert e.stopped_at == AD.WRITE_L_3 and (e.st(8), e.st(0xC), e.st(0x10)) == (853, 351, 10)


def test_news_chain_4k():
    e = Emu(40)
    for off, r in TABLE40_POST.items():
        e.wrect(AD.TW + off, r)
    SPR = STACK + 0x300
    e.w32(AD.TW + 0x20B4, SPR); e.w32(SPR + 0x1C, 198)
    e.w32(AD.TW + 0xA6C, -1); e.w32(AD.TW + 0xA6C + 0xC, 42)
    e.w32(AD.TW + 0xA44, -1); e.w32(AD.TW + 0xA44 + 0xC, 30)
    e.run("t_dp_news_sep", regs={"ecx": AD.MW_CANVAS}, stack=[RET_SITE, 336, 343])
    assert e.stopped_at == AD.GET_PIXEL and (e.st(4), e.st(8)) == (335, 647)
    e.run("t_dp_news_hline", regs={"ecx": AD.MW_CANVAS}, stack=[RET_SITE, 337, 601, 343, 77])
    assert e.stopped_at == AD.HLINE_2 and (e.st(4), e.st(8), e.st(0xC), e.st(0x10)) == (337, 600, 647, 77)
    e.run("t_dp_news_t1", regs={"ecx": AD.MW_CANVAS}, stack=[RET_SITE, 0x700000, 341, 347, 5])
    assert e.stopped_at == AD.WRITE_L_3 and (e.st(8), e.st(0xC)) == (347, 657)
    e.run("t_dp_news_t2", regs={"ecx": AD.MW_CANVAS}, stack=[RET_SITE, 0x700000, 341, 395, 5])
    assert (e.st(8), e.st(0xC)) == (347, 699)
    e.run("t_dp_news_t3", regs={"ecx": AD.MW_CANVAS}, stack=[RET_SITE, 0x700000, 341, 431, 5])
    assert (e.st(8), e.st(0xC)) == (347, 729)


def test_flic_init_4k():
    e = Emu(40)
    for off, r in TABLE40_POST.items():
        e.wrect(AD.TW + off, r)
    e.run("t_dp_flinit_bio", regs={"ecx": AD.FLIC_BIO}, stack=[RET_SITE, AD.MW_CANVAS, 0x700000, 26, 90, 1])
    assert e.stopped_at == AD.FLIC_INIT and (e.st(0xC), e.st(0x10)) == (65, 225) and e.reg("ecx") == AD.FLIC_BIO
    e.run("t_dp_flinit_news", regs={"ecx": AD.FLIC_NEWS}, stack=[RET_SITE, AD.MW_CANVAS, 0x700000, 336, 268, 0])
    assert (e.st(0xC), e.st(0x10)) == (337, 269)


def test_flic_draw_bounce_4k():
    e = Emu(40)
    ks = AD.ks
    calls = []
    # engine stubs: malloc (cdecl) -> 0x05000000 ; ctor thiscall ret ; resize RET 8 ; draw_frame RET 8 (eax=0) ; copy_3 records + RET 0x24
    for va, asm in ((AD.CRT_MALLOC, "mov eax, 0x05000000\nret"), (AD.BUF_CTOR, "ret"), (AD.BUF_RESIZE, "ret 8"),
                    (AD.FLIC_DRAW, "xor eax, eax\nret 8"), (AD.BUF_COPY_3, "ret 0x24")):
        enc, _ = ks.asm(asm, va)
        e.uc.mem_write(va, bytes(enc))
    e.landings.discard(AD.FLIC_DRAW)

    def rec(uc, addr, size, ud):
        if addr == AD.BUF_COPY_3:
            sp = uc.reg_read(UC_X86_REG_ESP)
            calls.append(("copy3", uc.reg_read(UC_X86_REG_ECX), [int.from_bytes(uc.mem_read(sp + 4 + 4 * i, 4), "little") for i in range(9)]))
        if addr == AD.FLIC_DRAW and uc.reg_read(UC_X86_REG_ECX) == AD.FLIC_NEWS:
            sp = uc.reg_read(UC_X86_REG_ESP)
            calls.append(("draw", uc.reg_read(UC_X86_REG_ECX), int.from_bytes(uc.mem_read(sp + 4, 4), "little"), int.from_bytes(uc.mem_read(sp + 8, 4), "little"),
                          int.from_bytes(uc.mem_read(uc.reg_read(UC_X86_REG_ECX) + 0x5A8, 4), "little")))
    e.uc.hook_add(UC_HOOK_CODE, rec)
    fl = AD.FLIC_NEWS
    e.w32(fl + 0x59C, 105); e.w32(fl + 0x5A0, 87); e.w32(fl + 0x5A8, AD.MW_CANVAS)
    e.run("t_dp_flicdraw", regs={"ecx": fl, "ebx": 5, "esi": 6, "edi": 7}, stack=[RET_SITE, 337, 269])
    assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 12          # RET 8
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi")) == (5, 6, 7)
    assert e.r32(AD.CELL_VA["g_dp_scr_news"]) == 0x05000000
    assert e.r32(fl + 0x5A8) == AD.MW_CANVAS and (e.r32(fl + 0x5AC), e.r32(fl + 0x5B0)) == (337, 269)
    assert (e.r32(fl + 0x58C), e.r32(fl + 0x590), e.r32(fl + 0x594), e.r32(fl + 0x598)) == (337, 269, 337 + 262, 269 + 217)
    draws = [c for c in calls if c[0] == "draw"]
    assert draws == [("draw", fl, 0, 0, 0x05000000)]           # drew into the scratch at 0,0
    c3 = [c for c in calls if c[0] == "copy3"]
    assert c3 == [("copy3", 0x05000000, [AD.MW_CANVAS, 0, 0, 105, 87, 337, 269, 262, 217])]
    # second draw reuses the scratch (no malloc)
    e.run("t_dp_flicdraw", regs={"ecx": fl}, stack=[RET_SITE, 337, 269])
    assert e.r32(AD.CELL_VA["g_dp_scr_news"]) == 0x05000000
    # foreign flic -> native passthrough
    e.run("t_dp_flicdraw", regs={"ecx": 0x7D2D70}, stack=[RET_SITE, 1, 2])
    assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 12 and len(calls) == 4   # native stub ran (RET 8), no bounce


# ============================================================================= POPUP HALF
def _popup40(e):
    e.wrect(AD.TW_CLIP, CLIP40)
    e.w32(POPUP + 0xA14, AD.TW)
    popup_fields(e, x30F0=82, x30D8=337, x21C8=0, x30E0=0, x30E8=95, x30D4=50, x21C4=4, x21B8=38, x21BC=125, x30C0=1125)


def test_fill_title_textblock_4k():
    e = Emu(40)
    _popup40(e)
    RECT = STACK + 0x100
    e.wrect(RECT, (23, 0, 1695, 1130))
    e.run("t_dp_fill", regs={"ecx": AD.TW, "esi": POPUP}, stack=[RET_SITE, RECT])
    assert e.stopped_at == AD.GWIN_FILL_2 and e.rect(RECT) == (57, 0, 1612, 1137) and e.reg("ecx") == AD.TW and e.reg("esi") == POPUP
    e.wrect(RECT, (26, 4, 1692, 28))
    e.run("t_dp_title_outer", regs={"ecx": AD.TW + 0x444, "esi": POPUP, "ebx": 5, "edi": 7}, stack=[RET_SITE, RECT, 0x78D5A0])
    assert e.stopped_at == AD.THUNK_BOX_THICK and e.rect(RECT) == (70, 13, 1599, 66) and (e.reg("ebx"), e.reg("edi"), e.reg("esi")) == (5, 7, POPUP)
    e.run("t_dp_title_inner", regs={"ecx": AD.TW + 0x444, "esi": POPUP}, stack=[RET_SITE, RECT, 0x78D618])
    assert e.stopped_at == AD.THUNK_BOX_THICK and e.rect(RECT) == (77, 20, 1592, 59)
    e.run("t_dp_title_text", regs={"ecx": AD.TW + 0x444, "esi": POPUP}, stack=[RET_SITE, 0x700000, RECT, 20])
    assert e.stopped_at == AD.CENT7 and e.rect(RECT) == (84, 27, 1585, 52)
    e.wrect(RECT, (416, 92, 1685, 145))
    e.run("t_dp_textblock", regs={"ecx": AD.TW + 0x444, "esi": POPUP, "ebx": 5, "edi": 7}, stack=[RET_SITE, RECT, 0x78D528])
    assert e.stopped_at == AD.THUNK_DEVFILL and e.rect(RECT) == (412, 87, 1595, 149) and (e.reg("ebx"), e.reg("edi")) == (5, 7)


def test_knest_4k():
    e = Emu(40)
    e.run("t_dp_knest", regs={"eax": 412, "ecx": 87, "edx": 1595, "ebx": 149, "edi": 0x77}, stack=[RET_SITE])
    ebp = e.reg("ebp")
    assert e.stopped_at == RET_SITE
    assert (e.reg("eax"), e.reg("edx"), e.reg("ebx"), e.reg("ecx"), e.reg("edi")) == (405, 1602, 156, ebp - 0x24, 0x77)
    assert (e.r32(ebp - 0x24), e.r32(ebp - 0x20)) == (412, 80)


def test_knest_identity_g16():
    e = Emu(16)
    e.run("t_dp_knest", regs={"eax": 100, "ecx": 50, "edx": 300, "ebx": 200}, stack=[RET_SITE])
    ebp = e.reg("ebp")
    assert (e.reg("eax"), e.reg("edx"), e.reg("ebx"), e.reg("ecx")) == (97, 303, 203, ebp - 0x24) and e.r32(ebp - 0x20) == 47


def test_calc_cuts_and_oky_4k():
    e = Emu(40)
    _popup40(e)
    e.run("t_dp_calc_e4", regs={"esi": POPUP, "ebp": 0}, stack=[RET_SITE])
    assert e.stopped_at == RET_SITE and e.r32(POPUP + 0x30E0) == 0 and e.r32(POPUP + 0x30E4) == 10
    e.run("t_dp_calc_hdr", regs={"esi": POPUP}, stack=[RET_SITE])
    assert e.r32(POPUP + 0x30E8) == 95 and e.r32(POPUP + 0x30EC) == 125
    e.w32(STACK + 0x100, -30)
    e.run("t_dp_oky", regs={"ecx": STACK + 0x100}, stack=[RET_SITE])
    assert e.r32(STACK + 0x100) == -75
    e2 = Emu(16)
    e2.w32(POPUP + 0x21C4, 4); e2.w32(POPUP + 0x21B8, 38)
    e2.run("t_dp_calc_e4", regs={"esi": POPUP, "ebp": 0}, stack=[RET_SITE]); assert e2.r32(POPUP + 0x30E4) == 4
    e2.run("t_dp_calc_hdr", regs={"esi": POPUP}, stack=[RET_SITE]); assert e2.r32(POPUP + 0x30E8) == 38


def test_q16fixed_gap():
    # Site 0x60D717: eax = D (Dialog base = popup+0x2D70), esi = Dialog_type16_calc this = popup+0x2214
    # whose vtable adjustor [vt+8] = 0xB5C lands the displaced tail's ecx on D. The arm keys on the
    # popup's own [+0xA14] ([esi-0x1800]), NOT on the talk-screen key (2026-09-26 fix).
    CALC = POPUP + 0x2214; D = POPUP + 0x2D70; VT = STACK + 0x900
    e = Emu(40)
    e.w32(POPUP + 0xA14, AD.TW); e.w32(AD.TW_A94, -1)            # anchored: the field decides, not the talk key
    e.w32(D + 0x68, 50); e.w32(D + 0x30, 885); e.w32(CALC, VT); e.w32(VT + 8, 0xB5C)
    e.run("t_dp_q16fixed", regs={"eax": D, "ecx": 885, "esi": CALC, "ebx": 0x33}, stack=[RET_SITE])
    assert e.stopped_at == RET_SITE and e.r32(D + 0x60) == 885 and e.r32(D + 0x44) == 5
    assert (e.reg("eax"), e.reg("ecx"), e.reg("ebx"), e.reg("esi")) == (0xB5C, D, 0x33, CALC)
    e.w32(POPUP + 0xA14, 0); e.w32(AD.TW_A94, 1); e.w32(D + 0x44, 3); e.stopped_at = None
    e.run("t_dp_q16fixed", regs={"eax": D, "ecx": 885, "esi": CALC}, stack=[RET_SITE])   # ordinary popup mid-talk
    assert e.stopped_at == RET_SITE and e.r32(D + 0x44) == 3 and e.r32(D + 0x60) == 885 and e.reg("ecx") == D
    e = Emu(25); e.w32(POPUP + 0xA14, AD.TW); e.w32(D + 0x68, 31); e.w32(CALC, VT); e.w32(VT + 8, 0xB5C)
    e.run("t_dp_q16fixed", regs={"eax": D, "ecx": 500, "esi": CALC}, stack=[RET_SITE])
    assert e.r32(D + 0x44) == 3                      # pitch 34 - 31


@pytest.mark.parametrize("g", (16, 17, 22, 25, 30, 32, 40))
@pytest.mark.parametrize("cols,margin", ((1, 0), (1, 6), (2, 0), (3, 4)))
def test_q16anch_trims_rows_by_the_scaled_native_3(g, cols, margin):
    """Anchored arm of t_dp_q16gate -> t_dp_q16anch: [D+0x64] = (B - 2*[D+0x40]) / [D+0x4C] - ps3
    (law diplo_q16_row_width), whatever the (vertical) gap [D+0x44] holds; [D+0x5C] and the gap
    untouched; ecx (GraphicWin this) and the stack args preserved; lands on GraphicWin_init."""
    from scaling_laws import diplo_q16_row_width, popup_pad
    A = POPUP + 0x2C44; D = A + 0x12C
    B = (600 * g) >> 4                                   # the OK-bar span (4K: 1500)
    e = Emu(g)
    e.w32(POPUP + 0xA14, AD.TW)
    e.w32(D + 0x20, 2); e.w32(D + 0x2C, B); e.w32(D + 0x40, margin); e.w32(D + 0x4C, cols)
    e.w32(D + 0x44, 5); e.w32(D + 0x5C, B); engine = (B - 2 * margin) // cols - 5
    e.w32(D + 0x64, engine)
    e.run("t_dp_q16gate", regs={"esi": A, "ecx": 0x5150}, stack=[RET_SITE, 11, 22, B, 44])
    assert e.stopped_at == AD.GWIN_INIT
    assert e.reg("ecx") == 0x5150 and e.reg("esi") == A
    assert [e.st(4 * i) for i in range(5)] == [RET_SITE, 11, 22, B, 44]
    assert e.r32(D + 0x5C) == B and e.r32(D + 0x44) == 5
    want = diplo_q16_row_width(B, margin, cols, g)
    if g <= 16:
        assert want is None and e.r32(D + 0x64) == engine          # native no-op
    else:
        assert e.r32(D + 0x64) == want == (B - 2 * margin) // cols - popup_pad(3, g)


def test_q16anch_measured_cases_and_gates():
    """4K: OK 1167..2667 (B = 1500) -> rows end 7 short (vanilla x 2.5 = 7.5; was 5).  1600x1200: B = 937 ->
    4 short (4.69; was 3).  Other fixed-width branch states (flag 2 clear / B == 0) pass through untouched."""
    from scaling_laws import diplo_q16_row_width
    assert 1500 - diplo_q16_row_width(1500, 0, 1, 40) == 7
    assert 937 - diplo_q16_row_width(937, 0, 1, 25) == 4
    assert 825 - diplo_q16_row_width(825, 0, 1, 22) == 4
    A = POPUP + 0x2C44; D = A + 0x12C
    for flags, B in ((0, 1500), (1, 1500), (2, 0)):
        e = Emu(40); e.w32(POPUP + 0xA14, AD.TW)
        e.w32(D + 0x20, flags); e.w32(D + 0x2C, B); e.w32(D + 0x4C, 1); e.w32(D + 0x64, 1234)
        e.run("t_dp_q16gate", regs={"esi": A}, stack=[RET_SITE])
        assert e.stopped_at == AD.GWIN_INIT and e.r32(D + 0x64) == 1234
    assert LAYOUT["t_dp_q16anch"][0] == 0x30850 and 0x30700 <= 0x30850 + len(LAYOUT["t_dp_q16anch"][1]) <= 0x30A00


def test_t16_gates_key_on_the_popup_field_not_the_talk_key():
    """One law, both thunks: the anchored test is [+0xA14] via esi; 0x734424 (talkOpen) is gone."""
    gate = LAYOUT["t_dp_q16gate"][1]; fixed = LAYOUT["t_dp_q16fixed"][1]
    assert bytes.fromhex("24447300") not in gate and bytes.fromhex("24447300") not in fixed
    assert bytes.fromhex("83BED0DDFFFF00") in gate           # cmp dword [esi-0x2230], 0  (popup+0x2C44)
    assert bytes.fromhex("83BE00E8FFFF00") in fixed          # cmp dword [esi-0x1800], 0  (popup+0x2214)
    assert (len(gate), len(fixed)) == (19, 63)


def test_gates_and_wrappers():
    e = Emu(40)
    _popup40(e)
    e.run("t_dp_boxw_gate", regs={"esi": POPUP}, stack=[RET_SITE]); assert e.stopped_at == 0x603D88 and e.reg("ebx") == 0
    e.w32(POPUP + 0xA14, 0)
    e.run("t_dp_boxw_gate", regs={"esi": POPUP}, stack=[RET_SITE]); assert e.stopped_at == AD.THUNK_SCALE_BOXW
    e.w32(POPUP + 0xA14, AD.TW)
    e.run("t_dp_growbox_gate", regs={"esi": POPUP}, stack=[RET_SITE]); assert e.stopped_at == 0x602867 and e.reg("ecx") == 1125
    e.run("t_dp_vcenter_gate", regs={"esi": POPUP, "eax": 0x1234}, stack=[RET_SITE, 1, 2, 3, 4, 5, 6, 7])
    assert e.stopped_at == 0x602C51 and e.st(0x14) == 0x1234 and e.reg("eax") == e.reg("esp") + 0x18
    e.w32(POPUP + 0x2350, -1)
    e.run("t_dp_childx_gate", regs={"esi": POPUP}, stack=[RET_SITE]); assert e.stopped_at == RET_SITE and (e.uc.reg_read(UC_X86_REG_EFLAGS) & 0x40)
    e.w32(POPUP + 0x2350, 16)
    e.run("t_dp_childx_gate", regs={"esi": POPUP}, stack=[RET_SITE]); assert not (e.uc.reg_read(UC_X86_REG_EFLAGS) & 0x40)
    e.w32(POPUP + 0xA14, 0)
    e.run("t_dp_childx_gate", regs={"esi": POPUP}, stack=[RET_SITE]); assert e.stopped_at == AD.THUNK_ORN_CHILDX
    # 0x60D299 wrapper: esi = Dialog_type16_attach this = popup+0x2C44; the popup's [+0xA14] decides
    e.w32(POPUP + 0xA14, AD.TW); e.w32(AD.TW_A94, -1); e.stopped_at = None     # anchored speech box
    e.run("t_dp_q16gate", regs={"esi": POPUP + 0x2C44}, stack=[RET_SITE]); assert e.stopped_at == AD.GWIN_INIT
    e.w32(POPUP + 0xA14, 0); e.w32(AD.TW_A94, 1); e.stopped_at = None          # ordinary popup mid-talk (the bug)
    e.run("t_dp_q16gate", regs={"esi": POPUP + 0x2C44}, stack=[RET_SITE]); assert e.stopped_at == AD.THUNK_Q16_FILL


def test_wrapwidth_art_itemrect_4k():
    e = Emu(40)
    _popup40(e)
    e.run("t_dp_wrapwidth", regs={"esi": POPUP, "ecx": 0x123, "ebx": 9}, stack=[RET_SITE, 0x700000, 1164])
    assert e.stopped_at == AD.THUNK_FACTION_WRAPWIDTH and e.st(8) == 1164 and e.reg("ecx") == 0x123 and e.reg("ebx") == 9
    e.run("t_dp_wrapwidth", regs={"esi": POPUP}, stack=[RET_SITE, 0x700000, 2000]); assert e.st(8) == 1164
    e.run("t_dp_artalign", stack=[RET_SITE, 0x700000, POPUP, 0, 82, 95])
    assert e.stopped_at == AD.THUNK_POPUP_ARTALIGN and (e.st(0x10), e.st(0x14)) == (74, 86)
    RECT = STACK + 0x100
    e.wrect(RECT, (0, 167, 1496, 217))
    e.run("t_dp_itemrect", regs={"ecx": POPUP}, stack=[RET_SITE, 0x11, 4, 0, RECT])
    assert e.stopped_at == AD.ITEM_BACK_DRAW and e.rect(RECT) == (0, 167, 1495, 216)
    e = Emu(22); e.wrect(AD.TW_CLIP, CLIP40); e.w32(POPUP + 0xA14, AD.TW)
    e.wrect(RECT, (0, 167, 1496, 217))
    e.run("t_dp_itemrect", regs={"ecx": POPUP}, stack=[RET_SITE, 0x11, 4, 0, RECT])
    assert e.rect(RECT) == (0, 167, 1495, 216)      # v2: 1 at every g > 16 (v1's K-1 left g=22 untrimmed)


# ---- t_dp_itemrect v2 (2026-10-17): law t16_item_draw_rect at every g, both arms, real bytes --------------------
IBD_SCR = 0x05000100          # the stub records (a1, a2, a3, rect*, *rect, ecx) here


def _ibd_stub_emu(g):
    """Emu whose Popup_on_dialog_item_back_draw is a recording stub (thiscall RET 0x10, returns 1), so the
    plain arm's CALL returns into the thunk and the run ends at RET_SITE."""
    e = Emu(g)
    e.landings.discard(AD.ITEM_BACK_DRAW)
    stub = (f"mov eax, dword ptr [esp+4]\nmov dword ptr [{IBD_SCR:#x}], eax\n"
            f"mov eax, dword ptr [esp+8]\nmov dword ptr [{IBD_SCR + 4:#x}], eax\n"
            f"mov eax, dword ptr [esp+0xC]\nmov dword ptr [{IBD_SCR + 8:#x}], eax\n"
            f"mov eax, dword ptr [esp+0x10]\nmov dword ptr [{IBD_SCR + 0xC:#x}], eax\n"
            + "".join(f"mov edx, dword ptr [eax+{4 * i}]\nmov dword ptr [{IBD_SCR + 0x10 + 4 * i:#x}], edx\n" for i in range(4))
            + f"mov dword ptr [{IBD_SCR + 0x20:#x}], ecx\nmov eax, 1\nret 0x10\n")
    enc, _ = AD.ks.asm(stub, AD.ITEM_BACK_DRAW)
    e.uc.mem_write(AD.ITEM_BACK_DRAW, bytes(enc))
    return e


@pytest.mark.parametrize("g", range(16, 41))
@pytest.mark.parametrize("kind", ["anchored", "plain16", "plain1", "plain2", "plain8"])
def test_itemrect_v2_law(g, kind):
    import scaling_laws as SL
    anchored = kind == "anchored"
    dtype = 16 if kind in ("anchored", "plain16") else int(kind[5:])
    e = _ibd_stub_emu(g)
    e.w32(POPUP + 0xA14, AD.TW if anchored else 0)
    e.w32(POPUP + 0x2350, dtype)
    RECT = STACK + 0x100
    rect = (7, 30 * 3, 7 + SL.scale_px(597, g), 30 * 3 + SL.scale_px(20, g))
    e.wrect(RECT, rect)
    e.run("t_dp_itemrect", regs={"ecx": POPUP, "ebx": 0x1B, "esi": 0x2C, "edi": 0x3D, "ebp": 0x4E},
          stack=[RET_SITE, 0x11, 4, 2, RECT])
    want = SL.t16_item_draw_rect(*rect, g, anchored=anchored, dialog_type=dtype)
    assert e.stopped_at == RET_SITE, "never returned to the caller"
    assert e.reg("esp") == e.sp_in + 4 + 0x10, "RET 0x10 contract"
    assert e.reg("eax") == 1 and e.reg("ecx") == POPUP
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0x1B, 0x2C, 0x3D, 0x4E)
    assert tuple(e.r32(IBD_SCR + 4 * i) for i in range(3)) == (0x11, 4, 2)          # a1..a3 passed through
    assert e.r32(IBD_SCR + 0x20) == POPUP                                             # thiscall this
    assert tuple(e.r32(IBD_SCR + 0x10 + 4 * i) for i in range(4)) == want             # what the frame is drawn from
    # anchored: the caller's rect IS trimmed (v1's contract); plain: the caller's rect is untouched
    assert e.rect(RECT) == (want if anchored else rect)
    if g <= 16 or kind not in ("anchored", "plain16"):
        assert want == rect and e.r32(IBD_SCR + 0xC) == RECT
    else:
        # drawn INCLUSIVE footprint [L..R-1] x [T..B-1] == the half-open rect = [D+0x64] x rowH (the OK bar's height)
        assert (want[2] - want[0] + 1, want[3] - want[1] + 1) == (rect[2] - rect[0], rect[3] - rect[1])
        assert (e.r32(IBD_SCR + 0xC) == RECT) == anchored                                # plain: a stack COPY


def test_itemrect_v2_trim_equals_v1_k_minus_1_only_for_g25_to_g40():
    """ARITHMETIC, not bytes: v1's anchored trim K-1 equals v2's constant 1 only for g = 25..40 (G_MAX: 1600x1200 ..
    4K), so the anchored rows' OUTPUT is unchanged there; 0 at g = 17..24 (the defect band v2 fixes, 1920x1080 = g22)
    and 2 at g >= 41 (beyond G_MAX, where v2 keeps the lawful 1)."""
    import scaling_laws as SL
    for g in range(25, 41):
        assert SL.stroke_width(g) - 1 == 1
    for g in range(17, 25):
        assert SL.stroke_width(g) - 1 == 0
    for g in range(41, 49):
        assert SL.stroke_width(g) - 1 == 2


@pytest.mark.parametrize("g", range(17, 41))
def test_itemrect_v2_diplo_row_trim_is_ps3(g):
    """Diplomacy reply rows end popup_pad(3, g) short of the OK bar in DRAWN pixels (vanilla 3 native):
    row [D+0x64] = OK span - ps3 (diplo_q16_row_width, one column), drawn inclusive right = R - 1 after the
    trim, OK bar drawn inclusive right = its half-open R - 1."""
    import scaling_laws as SL
    ok_w = SL.scale_px(600, g)
    row_w = SL.diplo_q16_row_width(ok_w, 0, 1, g)
    l, t, r, b = SL.t16_item_draw_rect(0, 0, row_w, SL.scale_px(20, g), g, anchored=True)
    assert (ok_w - 1) - r == SL.popup_pad(3, g)


# ---- speech-box far-edge trim v2 (2026-10-17): h1 = scaling_laws.diplo_far_edge_trim = 1 at every g > 16 ----------
# v1 used h1 = K-1 (K_into + dec), 0 at g = 17..24: the 1080 backdrop / title / speech box drew 1 px too far right and
# the title 1 row too tall.  v2 = `mov reg, 1` NOP-padded to v1's length (layout unchanged).  The v1 bytes are
# reconstructed by swapping that one span back, so the g = 25..40 equivalence below is a BYTE-level proof.
H1_THUNKS = {"t_dp_fill": "eax", "t_dp_title_outer": "ebx", "t_dp_title_inner": "ebx", "t_dp_title_text": "ebx",
             "t_dp_textblock": "eax", "t_dp_wrapwidth": "eax"}
V1_H1 = {"eax": bytes.fromhex("A1 40 87 66 00 01 C0 83 C0 0F C1 F8 05 48"),          # mov eax,[g]; add; add 15; sar 5; dec
         "ebx": bytes.fromhex("8B 1D 40 87 66 00 01 DB 83 C3 0F C1 FB 05 4B")}
V2_H1 = {"eax": bytes.fromhex("B8 01 00 00 00") + b"\x90" * 9, "ebx": bytes.fromhex("BB 01 00 00 00") + b"\x90" * 10}
SPEECH_CASES = (  # (clip offset, popup fields as native values scaled fl(v*g/16))
    ((0, 0), dict(x30F0=33, x30D8=135, x21C8=0, x30E0=0, x30E8=38, x30D4=20)),
    ((5, 9), dict(x30F0=29, x30D8=120, x21C8=4, x30E0=2, x30E8=41, x30D4=57)),
)


def _v1_blob(name):
    off, blob = LAYOUT[name]
    reg = H1_THUNKS[name]
    assert blob.count(V2_H1[reg]) == 1, f"{name}: the v2 h1 span must occur exactly once"
    return off, blob.replace(V2_H1[reg], V1_H1[reg])


def _speech_world(g, case, v1=False):
    import scaling_laws as SL
    (ox, oy), fn = case
    e = Emu(g)
    if v1:
        for n in H1_THUNKS:
            off, blob = _v1_blob(n)
            e.uc.mem_write(AD.PCAVE2_VA + off, blob)
    clip = (ox, oy, ox + SL.dp(700, g), oy + SL.dp(450, g))
    e.wrect(AD.TW_CLIP, clip)
    e.w32(POPUP + 0xA14, AD.TW)
    f = {int(k[1:], 16): SL.dp(v, g) for k, v in fn.items()}
    for k, v in f.items():
        e.w32(POPUP + k, v)
    return e, clip, f


def _speech_runs(e):
    """Run every h1 thunk; record (landing, rect/measure, all GPRs, the arg words) per thunk."""
    RECT = STACK + 0x100
    regs = {"ebx": 0x1B1B, "edi": 0x3D3D, "edx": 0x4E4E, "eax": 0x5F5F}
    calls = {"t_dp_fill": ({"ecx": AD.TW, "esi": POPUP}, [RET_SITE, RECT]),
             "t_dp_title_outer": ({"ecx": AD.TW + 0x444, "esi": POPUP}, [RET_SITE, RECT, 0x78D5A0]),
             "t_dp_title_inner": ({"ecx": AD.TW + 0x444, "esi": POPUP}, [RET_SITE, RECT, 0x78D618]),
             "t_dp_title_text": ({"ecx": AD.TW + 0x444, "esi": POPUP}, [RET_SITE, 0x700000, RECT, 20]),
             "t_dp_textblock": ({"ecx": AD.TW + 0x444, "esi": POPUP}, [RET_SITE, RECT, 0x78D528]),
             "t_dp_wrapwidth": ({"esi": POPUP, "ecx": 0x123}, [RET_SITE, 0x700000, 99999])}
    out = {}
    for n, (r, stack) in calls.items():
        e.wrect(RECT, (1, 2, 3, 4)); e.stopped_at = None
        e.run(n, regs={**regs, **r}, stack=stack)
        out[n] = {"land": e.stopped_at, "rect": e.rect(RECT), "args": tuple(e.st(4 * i) for i in range(len(stack))),
                  "regs": {k: e.reg(k) for k in R}}
    return out


@pytest.mark.parametrize("g", range(16, 41))
@pytest.mark.parametrize("case", range(len(SPEECH_CASES)))
def test_speech_far_edge_v2_law(g, case):
    """Real v2 bytes == scaling_laws.diplo_speech_rects (h1 = diplo_far_edge_trim) at every g; g = 16: the caller's
    rect / width reach the native callee untouched."""
    import scaling_laws as SL
    e, clip, f = _speech_world(g, SPEECH_CASES[case])
    o = _speech_runs(e)
    law = SL.diplo_speech_rects(clip, f, g)
    native = {"t_dp_fill": AD.GWIN_FILL_2, "t_dp_title_outer": AD.THUNK_BOX_THICK, "t_dp_title_inner": AD.THUNK_BOX_THICK,
              "t_dp_title_text": AD.CENT7, "t_dp_textblock": AD.THUNK_DEVFILL, "t_dp_wrapwidth": AD.THUNK_FACTION_WRAPWIDTH}
    if g <= 16:
        for n in H1_THUNKS:
            assert o[n]["land"] == native[n], n
            if n != "t_dp_wrapwidth":
                assert o[n]["rect"] == (1, 2, 3, 4), n
        assert o["t_dp_wrapwidth"]["args"][2] == 99999
        return
    fill = o["t_dp_fill"]["rect"]
    assert (fill[0], fill[2], fill[3]) == (law["fill"][0], law["fill"][2], law["fill"][3]) and fill[1] == 2   # T: caller's
    assert o["t_dp_title_outer"]["rect"] == law["outer"]
    assert o["t_dp_title_inner"]["rect"] == law["inner"]
    assert o["t_dp_title_text"]["rect"] == law["text"]
    assert o["t_dp_textblock"]["rect"] == law["d528"]
    assert o["t_dp_wrapwidth"]["args"][2] == law["measure"]
    for n in ("t_dp_title_outer", "t_dp_title_inner", "t_dp_title_text", "t_dp_textblock"):
        assert (o[n]["regs"]["ebx"], o[n]["regs"]["edi"], o[n]["regs"]["esi"]) == (0x1B1B, 0x3D3D, POPUP), n   # callee-saved
    assert (o["t_dp_fill"]["regs"]["esi"], o["t_dp_wrapwidth"]["regs"]["ebx"], o["t_dp_wrapwidth"]["regs"]["ecx"]) == (POPUP, 0x1B1B, 0x123)
    # the defect, in drawn pixels: inclusive far edge == scaled half-open vanilla edge - 1
    R = clip[2]
    assert fill[2] == R - SL.dp(0x37, g) - 1
    assert law["final"][2] == R - SL.dp(0x3B, g) - 1
    assert o["t_dp_title_outer"]["rect"][3] + SL.frame_grow_delta(g) == clip[1] + SL.dp(0x1C, g) - 1


@pytest.mark.parametrize("g", range(16, 41))
@pytest.mark.parametrize("case", range(len(SPEECH_CASES)))
def test_speech_far_edge_v2_vs_v1_bytes(g, case):
    """g = 16 and g = 25..40 (1024x768, 1600x1200 .. 4K): v2's bytes leave EXACTLY v1's state (landing, rect, arg
    words, every GPR).  g = 17..24: v2 moves each far edge (fill R, title R/B, d528 R) and the measure in by exactly
    1 and leaves h1 = 1 where v1 left 0 in the scratch register; nothing else differs."""
    import scaling_laws as SL
    a = _speech_runs(_speech_world(g, SPEECH_CASES[case], v1=True)[0])
    b = _speech_runs(_speech_world(g, SPEECH_CASES[case], v1=False)[0])
    if g <= 16 or g >= 25:
        assert a == b
        return
    assert SL.stroke_width(g) - 1 == 0
    for n in H1_THUNKS:
        reg = H1_THUNKS[n]
        assert a[n]["land"] == b[n]["land"], n
        ra, rb = a[n]["rect"], b[n]["rect"]
        if n == "t_dp_wrapwidth":
            assert ra == rb and b[n]["args"][2] == a[n]["args"][2] - 1
        else:
            assert a[n]["args"] == b[n]["args"]
            want = (ra[0], ra[1], ra[2] - 1, ra[3] - (1 if n.startswith("t_dp_title") else 0))
            assert rb == want, n
        # GPR deltas (v2 - v1): only scratch registers the callee may clobber anyway -- edx = the R edge just computed
        # (one less), t_dp_title_outer's eax = its B edge (one less; the inner/text arms overwrite eax with the inset),
        # t_dp_wrapwidth's eax = h1 itself (1 vs 0); ebx (the title's h1) is popped, callee-saved regs equal.
        delta = {k: b[n]["regs"][k] - v for k, v in a[n]["regs"].items() if v != b[n]["regs"][k]}
        want_delta = {"t_dp_wrapwidth": {"eax": 1}, "t_dp_title_outer": {"eax": -1, "edx": -1}}.get(n, {"edx": -1})
        assert delta == want_delta, (n, reg, delta)


def test_speech_far_edge_v2_layout_unchanged():
    """Same-length in place: every h1 thunk keeps v1's size, so the sequential layout (and every later thunk) did not move."""
    sizes = {"t_dp_fill": 114, "t_dp_title_outer": 165, "t_dp_title_inner": 194, "t_dp_title_text": 194,
             "t_dp_textblock": 174, "t_dp_wrapwidth": 117}
    offs = {"t_dp_fill": 0x1228C, "t_dp_title_outer": 0x12300, "t_dp_title_inner": 0x123A8, "t_dp_title_text": 0x1246C,
            "t_dp_textblock": 0x12530, "t_dp_wrapwidth": 0x12670}
    for n in H1_THUNKS:
        assert (LAYOUT[n][0], len(LAYOUT[n][1])) == (offs[n], sizes[n]), n
        assert LAYOUT[n][1].count(V1_H1[H1_THUNKS[n]]) == 0, f"{n}: v1's K-1 sequence is gone"


def test_init_literals_4k():
    e = Emu(40)
    e.run("t_dp_pushw", regs={"esi": AD.TW}, stack=[0x440AF7, 0x99])
    assert e.stopped_at == 0x440AF7 and e.st(0) == 1750 and e.st(4) == 0x99
    e.run("t_dp_movh", stack=[RET_SITE]); assert e.reg("ecx") == 1125
    e.run("t_dp_movex", regs={"eax": 3840 - 1750}, stack=[RET_SITE]); assert e.reg("eax") == 1085
    RC = STACK + 0x100
    e.wrect(RC, (0, 0, 1750, 1125))
    e.run("t_dp_frameL", regs={"edx": RC}, stack=[RET_SITE]); assert e.reg("eax") == 57
    e.run("t_dp_frameR", regs={"edx": RC, "ecx": 1750, "eax": 0x55}, stack=[RET_SITE])
    assert e.reg("ecx") == 1613 and e.reg("edx") == 1125 and e.reg("eax") == 0x55
    e = Emu(16)
    e.run("t_dp_pushw", stack=[0x440AF7]); assert e.st(0) == 700
    e.run("t_dp_movh", stack=[RET_SITE]); assert e.reg("ecx") == 450
    e.run("t_dp_movex", regs={"eax": 324}, stack=[RET_SITE]); assert e.reg("eax") == (324 + 32) // 2


def test_btn_gate_prefix_bytes():
    pre = AD.btn_gate_prefix()
    assert pre.startswith(bytes.fromhex("81FE") + (AD.TW + 0x2158).to_bytes(4, "little"))
    assert len(pre) == 32


# ============================================================================= CONSOLE SAVE-UNDER
CV_DATA = 0x06000000       # fake canvas pixel plane
CV_BUF = 0x07000000        # what the VirtualAlloc stub hands out
VA_STUB = 0x08000000       # VirtualAlloc stub: mov eax, CV_BUF ; ret 0x10
CR_STRIDE = 64             # tiny synthetic canvas


def _saveunder_world(g, big=0, seeds=None):
    e = Emu(g)
    for base, size in ((0x7AE000, 0x1000), (0x7D3000, 0x1000), (0x669000, 0x1000),
                       (0x45C000, 0x1000), (0x5D5000, 0x1000),
                       (CV_DATA, 0x10000), (CV_BUF, 0x10000), (VA_STUB, 0x1000)):
        try:
            e.uc.mem_map(base, size)
        except Exception:  # noqa: BLE001
            pass
    # tiny seed world: gap column x [16..36), rows [0..12)
    e.seeds(seeds or {"D80": (2, 4, 16, 60), "D90": (36, 4, 58, 60), "DB0": (16, 10, 36, 60),
                      "DC0": (14, 2, 40, 44), "A8C": (40, 40, 50, 50), "A9C": (50, 40, 58, 50)})
    e.w32(AD.CANVAS_DATA, CV_DATA)
    e.w32(AD.CANVAS_STRIDE, CR_STRIDE)
    e.w32(AD.G_BIG, big)
    e.w32(AD.IAT_VIRTUALALLOC, VA_STUB)
    e.uc.mem_write(VA_STUB, b"\xb8" + CV_BUF.to_bytes(4, "little") + b"\xc2\x10\x00")
    # native tile_panels stub: clobbers the volatile regs like the real thiscall (mov ecx,0xDEAD0000;
    # mov eax,ecx; mov edx,ecx), then RET 4 -- a stub that preserved ecx hid a garbage-`this` crash
    e.uc.mem_write(AD.TILE_PANELS, b"\xb9\x00\x00\xad\xde\x8b\xc1\x8b\xd1\xc2\x04\x00")
    e.uc.mem_write(AD.SOFT_UPDATE, b"\xc2\x10\x00")   # soft_update stub: RET 0x10
    # canvas pattern: byte = (y*7 + x) & 0xFF over rows 0..12
    for y in range(14):
        e.uc.mem_write(CV_DATA + y * CR_STRIDE, bytes(((y * 7 + x) & 0xFF) for x in range(CR_STRIDE)))
    return e


def _cells(e):
    return (e.r32(AD.CRBUF), e.r32(AD.CRL), e.r32(AD.CRR), e.r32(AD.CRB), e.r32(AD.CRARM))


def test_saveunder_snapshot():
    e = _saveunder_world(40)
    e.run("t_cr_snap", regs={"ecx": AD.TW + 0xA14}, stack=[RET_SITE, 1], extra_landing=(AD.ONMODE,))
    assert e.stopped_at == AD.ONMODE and e.reg("esp") == e.sp_in
    buf, L, Rr, B, armed = _cells(e)
    # v4: L = D80.right - 1 (the D80 right frame column the 1:1 centre sprite overwrites)
    assert (buf, L, Rr, B, armed) == (CV_BUF, 15, 36, 12, 1)
    for y in range(12):     # buffer holds canvas rows [L..R) x [0..B)
        row = bytes(e.uc.mem_read(CV_BUF + y * 21, 21))
        assert row == bytes(((y * 7 + x) & 0xFF) for x in range(15, 36)), f"row {y}"


def test_saveunder_snapshot_gates():
    e = _saveunder_world(16)    # g<=16: pure passthrough, cells untouched
    e.run("t_cr_snap", regs={"ecx": AD.TW + 0xA14}, stack=[RET_SITE, 1], extra_landing=(AD.ONMODE,))
    assert e.stopped_at == AD.ONMODE and _cells(e) == (0, 0, 0, 0, 0)
    e = _saveunder_world(40)    # LEAVE (enter=0): passthrough, no snapshot
    e.run("t_cr_snap", regs={"ecx": AD.TW + 0xA14}, stack=[RET_SITE, 0], extra_landing=(AD.ONMODE,))
    assert e.stopped_at == AD.ONMODE and _cells(e) == (0, 0, 0, 0, 0)


def test_saveunder_restore():
    e = _saveunder_world(40, big=0)
    # arm: saved buffer holds an inverted pattern; canvas holds the plain one
    e.w32(AD.CRBUF, CV_BUF); e.w32(AD.CRL, 16); e.w32(AD.CRR, 36); e.w32(AD.CRB, 12); e.w32(AD.CRARM, 1)
    for y in range(12):
        e.uc.mem_write(CV_BUF + y * 20, bytes((0xFF ^ ((y * 7 + x) & 0xFF)) for x in range(16, 36)))
    # soft_update stub records its `this`: mov [CV_BUF+0x8000], ecx ; ret 0x10
    e.uc.mem_write(AD.SOFT_UPDATE, bytes([0x89, 0x0D]) + (CV_BUF + 0x8000).to_bytes(4, "little") + bytes([0xC2, 0x10, 0x00]))
    e.run("t_cr_tile", regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77])
    assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 8    # ret 4 after our own ret consumed
    assert e.r32(CV_BUF + 0x8000) == AD.MW                             # soft_update(this=MainWin) from the pushad frame
    for y in range(12):
        row = bytes(e.uc.mem_read(CV_DATA + y * CR_STRIDE + 16, 20))
        assert row == bytes((0xFF ^ ((y * 7 + x) & 0xFF)) for x in range(16, 36)), f"row {y}"
        # outside the column untouched
        assert bytes(e.uc.mem_read(CV_DATA + y * CR_STRIDE, 16)) == bytes(((y * 7 + x) & 0xFF) for x in range(16))


def test_saveunder_restore_gates():
    for kwargs, regs in (
        (dict(big=0), {"ecx": 0x123456}),          # not MainWin
        (dict(big=1), {"ecx": AD.MW}),             # big centre up
        (dict(big=0, g16=True, disarm=True), {"ecx": AD.MW}),   # native res: t_cr_snap never arms at g<=16
        (dict(big=0, disarm=True), {"ecx": AD.MW}),
        (dict(big=0, mode=3), {"ecx": AD.MW}),     # base screen up: this==MainWin too, the HUD snapshot must NOT stamp
        (dict(big=0, mode=8), {"ecx": AD.MW}),     # any other console-skinning iface
        (dict(big=0, mode=1), {"ecx": AD.MW}),
    ):
        e = _saveunder_world(16 if kwargs.get("g16") else 40, big=kwargs.get("big", 0))
        e.w32(AD.IFACE_MODE_IDX, 1); e.w32(AD.IFACE_MODE_TAB + 4, kwargs.get("mode", 0))
        if not kwargs.get("disarm"):
            e.w32(AD.CRARM, 1); e.w32(AD.CRBUF, CV_BUF); e.w32(AD.CRL, 16); e.w32(AD.CRR, 36); e.w32(AD.CRB, 12)
        e.run("t_cr_tile", regs=regs, stack=[RET_SITE, 0x77], extra_landing=(AD.TILE_PANELS,))
        assert e.stopped_at == AD.TILE_PANELS and e.reg("esp") == e.sp_in   # pure jmp passthrough


def test_saveunder_restore_modes():
    # the restore runs in the HUD (mode 0) and inside the diplomacy flow (mode 4) only
    for mode in (0, 4):
        e = _saveunder_world(40, big=0)
        e.w32(AD.IFACE_MODE_IDX, 1); e.w32(AD.IFACE_MODE_TAB + 4, mode)
        e.w32(AD.CRBUF, CV_BUF); e.w32(AD.CRL, 16); e.w32(AD.CRR, 36); e.w32(AD.CRB, 12); e.w32(AD.CRARM, 1)
        e.uc.mem_write(CV_BUF, bytes([0xEE]) * (12 * 20))
        e.run("t_cr_tile", regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77])
        assert e.stopped_at == RET_SITE, mode
        assert bytes(e.uc.mem_read(CV_DATA + 5 * CR_STRIDE + 16, 20)) == bytes([0xEE]) * 20, mode


# ---- RETURN-MODE save-under (2026-09-23): Datalinks entered from the base screen -------------------
# t_cr_mark: g_cr_mode = the mode the exit returns to; armed = 1 (HUD snapshot, t_cr_tile's contract)
# or 2 (any other source -- t_cr_tile never restores it). t_cr_tile_exit (site 0x45DE3C = the leaving
# iface's OWN hide) v2 (2026-09-26): restores any armed, unconsumed snapshot whatever mode is on the
# stack top (a screen opened FROM the talk pushes its mode BEFORE the diplo hide), one-shot for armed==2.
def _armed_world(stack_modes, crmode, armed=2, big=0):
    e = _saveunder_world(40, big=big)
    e.w32(AD.IFACE_MODE_IDX, len(stack_modes) - 1)
    for i, m in enumerate(stack_modes):
        e.w32(AD.IFACE_MODE_TAB + 4 * i, m)
    e.w32(AD.CRBUF, CV_BUF); e.w32(AD.CRL, 16); e.w32(AD.CRR, 36); e.w32(AD.CRB, 12); e.w32(AD.CRARM, armed)
    e.w32(AD.CRMODE, crmode)
    e.uc.mem_write(CV_BUF, bytes([0xEE]) * (12 * 20))
    return e


def _restored(e):
    return bytes(e.uc.mem_read(CV_DATA + 5 * CR_STRIDE + 16, 20)) == bytes([0xEE]) * 20


def test_saveunder_snapshot_records_return_mode():
    # set_iface_mode pushes the new mode BEFORE the new iface's on_mode(1): the snapshot records table[idx-1]
    for stack_modes, want, armed in (([0, 3, 8], 3, 2), ([0, 8], 0, 1), ([0, 3, 4], 3, 2), ([0, 4], 0, 1)):
        e = _saveunder_world(40)
        e.w32(AD.IFACE_MODE_IDX, len(stack_modes) - 1)
        for i, m in enumerate(stack_modes):
            e.w32(AD.IFACE_MODE_TAB + 4 * i, m)
        e.run("t_cr_snap", regs={"ecx": AD.TW + 0xA14}, stack=[RET_SITE, 1], extra_landing=(AD.ONMODE,))
        assert e.stopped_at == AD.ONMODE and e.reg("esp") == e.sp_in
        assert _cells(e) == (CV_BUF, 15, 36, 12, armed) and e.r32(AD.CRMODE) == want, stack_modes
        for y in range(12):     # the snapshot itself is unchanged by the arm call
            assert bytes(e.uc.mem_read(CV_BUF + y * 21, 21)) == bytes(((y * 7 + x) & 0xFF) for x in range(15, 36))


def test_tile_exit_restores_at_return_mode_once():
    # DL from the base: at the slide_hide exit the stack is already popped to [0,3]; g_cr_mode == 3
    e = _armed_world([0, 3], 3)
    e.run("t_cr_tile_exit", regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77])
    assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 8
    assert _restored(e)
    assert bytes(e.uc.mem_read(CV_DATA + 5 * CR_STRIDE, 16)) == bytes(((5 * 7 + x) & 0xFF) for x in range(16))
    assert e.r32(AD.CRMODE) == -1 and e.r32(AD.CRARM) == 2
    # one-shot: a second exit-site pass at mode 3 no longer matches -> t_cr_tile -> native only
    e.uc.mem_write(CV_BUF, bytes([0x11]) * (12 * 20))
    e.run("t_cr_tile_exit", regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77], extra_landing=(AD.TILE_PANELS,))
    assert e.stopped_at == AD.TILE_PANELS and e.reg("esp") == e.sp_in


def test_base_snapshot_never_stamps_the_hud():
    # after DL-from-base the snapshot holds BASE pixels (armed 2): closing the base re-tiles at mode 0
    # through t_cr_tile (site 0x45BC73) -- it must NOT restore (user 4K shot 20260923-221742); the
    # exit site only passes a CONSUMED (g_cr_mode == -1) base snapshot through (it is always consumed
    # at the DL's own hide, which is the only way back to the base)
    for crmode in (3, -1):
        for thunk in ("t_cr_tile", "t_cr_tile_exit"):
            if thunk == "t_cr_tile_exit" and crmode != -1:
                continue
            e = _armed_world([0], crmode, armed=2)
            e.run(thunk, regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77], extra_landing=(AD.TILE_PANELS,))
            assert e.stopped_at == AD.TILE_PANELS and e.reg("esp") == e.sp_in and not _restored(e), (crmode, thunk)


def test_tile_exit_hud_snapshot_unchanged():
    # HUD -> DL -> exit: armed 1 -> the exit site restores (as t_cr_tile would at mode 0 / 4) and
    # keeps the HUD arm (armed 1, g_cr_mode 0 -- never consumed, t_cr_tile's contract)
    for mode in (0, 4):
        e = _armed_world([0, mode] if mode else [0], 0, armed=1)
        e.run("t_cr_tile_exit", regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77])
        assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 8 and _restored(e), mode
        assert e.r32(AD.CRMODE) == 0 and e.r32(AD.CRARM) == 1


def test_tile_exit_restores_under_a_nested_push():
    # v2 (2026-09-26, user shot _Problems/CenterConsole.png, probe-confirmed): DATALINKS / PROFILE
    # opened FROM the talk push mode 8 / 5 BEFORE the diplo's on_mode(0) -> slide_hide -> exit site,
    # so the stack top is the NEW mode. The leaving iface's own hide restores its snapshot anyway:
    # HUD arm (armed 1) restores and stays armed; a base-sourced arm (armed 2) restores once.
    for stack_modes, crmode, armed, want_mode in (
        ([0, 4, 8], 0, 1, 0),      # talk -> DATALINKS
        ([0, 4, 5], 0, 1, 0),      # talk -> PROFILE
        ([0, 3], 0, 1, 0),         # HUD arm with the base on top: the exit site trusts the leaving iface
        ([0, 3, 8], 3, 2, -1),     # base -> DL, nested push on top of the DL: one-shot
    ):
        e = _armed_world(stack_modes, crmode, armed=armed)
        e.run("t_cr_tile_exit", regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77])
        assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 8 and _restored(e), stack_modes
        assert e.r32(AD.CRMODE) == want_mode and e.r32(AD.CRARM) == armed, stack_modes


def test_tile_exit_gates():
    for stack_modes, crmode, big, ecx, armed in (
        ([0, 3], -1, 0, AD.MW, 2),      # already consumed
        ([0, 4, 8], -1, 0, AD.MW, 1),   # consumed marker wins for either arm
        ([0, 3], 3, 1, AD.MW, 2),       # big centre still up
        ([0, 3], 3, 0, 0x123456, 2),    # not MainWin
        ([0, 3], 3, 0, AD.MW, 0),       # never armed (g<=16)
        ([0, 4, 8], 0, 1, AD.MW, 1),    # big centre still up, HUD arm
    ):
        e = _armed_world(stack_modes, crmode, armed=armed, big=big)
        e.run("t_cr_tile_exit", regs={"ecx": ecx}, stack=[RET_SITE, 0x77], extra_landing=(AD.TILE_PANELS,))
        assert e.stopped_at == AD.TILE_PANELS and e.reg("esp") == e.sp_in, (stack_modes, crmode, big, hex(ecx), armed)
        assert not _restored(e) and e.r32(AD.CRMODE) == crmode


def test_snapshot_clones_call_t_cr_mark():
    # the DL + combat snapshot clones arm through the same helper (same-length swap of the 10-byte mov)
    import assemble_dl as ADL
    import assemble_combat as ACB
    layout, _end, _names = ADL.assemble_all()
    blobs = {"t_cr_snap": (AD.PCAVE2_VA + LAYOUT["t_cr_snap"][0], LAYOUT["t_cr_snap"][1]),
             "t_cr_snap_dl": (ADL.PCAVE2 + layout["t_cr_snap_dl"][0], layout["t_cr_snap_dl"][1]),
             "t_cmb_snap": (ACB.PCAVE2 + ACB.OUT["t_cmb_snap"][0], ACB.OUT["t_cmb_snap"][1])}
    old_arm = bytes.fromhex("C705") + AD.CRARM.to_bytes(4, "little") + (1).to_bytes(4, "little")
    for n, (va, b) in blobs.items():
        assert len(b) == 181 and old_arm not in b, n
        i = b.index(bytes.fromhex("0F1F4000")) - 5      # v4: 4-byte arm NOP (the 5th byte pays for `dec eax`)
        assert b[i] == 0xE8 and (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF == AD.T_CR_MARK, n
    assert AD.T_CR_MARK == ADL.T_CR_MARK == ACB.T_CR_MARK


def test_exit_site_targets_tile_exit():
    sites = {va: t for sid, va, t in AD.REDIRECTS if sid.startswith("tile_panels_wrap.")}
    assert sites.pop(0x45DE3C) == "t_cr_tile_exit" and set(sites.values()) == {"t_cr_tile"} and len(sites) == 11
    # ct_go = pushad / mov edi,[canvas data] (v3: copy back FIRST, then the native tile_panels)
    assert bytes(LAYOUT["t_cr_tile"][1][AD.CT_GO - AD.T_CR_TILE:][:7]) == bytes.fromhex("608B3D") + AD.CANVAS_DATA.to_bytes(4, "little")


def test_native_fill_wins_over_the_snapshot():
    # v3 (2026-09-26, user 4K shot 20260926-160047): the copy-back runs BEFORE the native tile_panels,
    # so its flat fill of the panel interiors stands and only the region the engine never re-tiles
    # (the gap band / column) comes from the snapshot. v2 pasted the snapshot over the fill, and a
    # snapshot holding a nested screen's title re-dirtied the channel between the two HUD readout
    # panels, which the readout repaint never covers. Stub tile_panels writes a marker into the
    # column AFTER the copy: it must survive on both restore entries.
    marker = CV_DATA + 5 * CR_STRIDE + 20
    # mov ecx,0xDEAD0000 / mov eax,ecx / mov edx,ecx (clobber like the real thiscall) /
    # mov byte [marker],0xAA / ret 4
    stub = bytes.fromhex("b90000adde8bc18bd1c605") + marker.to_bytes(4, "little") + bytes.fromhex("aac20400")
    for thunk, world in (("t_cr_tile", lambda: _armed_world([0], 0, armed=1)),
                         ("t_cr_tile_exit", lambda: _armed_world([0, 4, 8], 0, armed=1))):
        e = world()
        e.uc.mem_write(AD.TILE_PANELS, stub)
        e.run(thunk, regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77])
        assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 8, thunk
        row = bytes(e.uc.mem_read(CV_DATA + 5 * CR_STRIDE + 16, 20))
        assert row == bytes([0xEE]) * 4 + bytes([0xAA]) + bytes([0xEE]) * 15, (thunk, row.hex())
        # a NULL canvas skips the copy but still runs the native call and returns cleanly
        e = world()
        e.uc.mem_write(AD.TILE_PANELS, stub)
        e.w32(AD.CANVAS_DATA, 0)
        e.run(thunk, regs={"ecx": AD.MW}, stack=[RET_SITE, 0x77])
        assert e.stopped_at == RET_SITE and e.reg("esp") == e.sp_in + 8 and bytes(e.uc.mem_read(marker, 1)) == bytes([0xAA]), thunk
