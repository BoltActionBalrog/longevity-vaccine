"""Differential: every basewin_strip_content thunk (assemble_strip_content.py)
must agree bit-exactly with scaling_laws.basewin_strip_content /
basewin_strip_pop_citizen_y at g = 16 (identity), 22, 25 and 40, and honor its
register/stack/landing contract (derived from _tmp_disasm_strip_fns.txt).

Emulates the REAL assembled bytes with the sentinel g page mapped at
0xDEADB000 (the yaml resolves {abs32:g_popup_scale_num} at apply time).
Landing pads: Font_init = `RET 0xC` (callee-clean, deletes-and-reinits
semantics irrelevant here), redirect targets = plain mapped bytes the
emulation halts on.  Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_strip_content as ASC  # noqa: E402

LAYOUT, _END = ASC.assemble_all()
STACK = 0x00200000
FRAME = STACK + 0x8000          # EBP inside the stack map
RET_PAD = 0x00400100            # halt address for RET-style exits
GS = (16, 22, 25, 40)

R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX,
     "edx": UC_X86_REG_EDX, "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI}


def s(k, g):
    return SL.basewin_pt(k, g)


def mk(g, regs=None, mem=None, stack=None):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((0xA19000, 0x1000), (0xA17000, 0x1000), (0xA3A000, 0x1000),
                       (0xDEADB000, 0x1000), (0x618000, 0x1000),
                       (0x5DA000, 0x1000), (0x588000, 0x1000),
                       (0x5E4000, 0x1000), (0x696000, 0x1000),
                       (0x691000, 0x1000), (0x7AF000, 0x1000),
                       (0x400000, 0x1000), (STACK, 0x10000)):
        uc.mem_map(base, size)
    for name, (off, blob) in LAYOUT.items():
        uc.mem_write(ASC.PCAVE2_VA + off, blob)
    uc.mem_write(0xDEADBE00 & 0xFFFFF000 | 0xE00, (g).to_bytes(4, "little"))
    uc.mem_write(ASC.FONT_INIT, b"\xC2\x0C\x00")      # RET 0xC
    # t_ffn_at(slot, S, v, num) recorder (fonts v2): args -> 0x400800.., returns the slot
    from keystone import Ks as _Ks, KS_ARCH_X86 as _A, KS_MODE_32 as _M
    _stub, _ = _Ks(_A, _M).asm("mov eax, [esp+4]; mov [0x400800], eax; mov eax, [esp+8]; mov [0x400804], eax;"
                               "mov eax, [esp+0xC]; mov [0x400808], eax; mov eax, [esp+0x10]; mov [0x40080C], eax;"
                               "mov eax, [esp+4]; ret", ASC.T_FFN_AT)
    uc.mem_write(ASC.T_FFN_AT, bytes(_stub))
    uc.reg_write(UC_X86_REG_EBP, FRAME)
    esp = FRAME - 0x200
    for v in reversed(stack or []):
        esp -= 4
        uc.mem_write(esp, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, esp)
    for reg, v in (regs or {}).items():
        uc.reg_write(R[reg], v & 0xFFFFFFFF)
    for addr, v in (mem or {}).items():
        uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    return uc


def run(uc, thunk, until=RET_PAD, push_ret=True):
    va = ASC.PCAVE2_VA + LAYOUT[thunk][0]
    if push_ret:
        esp = uc.reg_read(UC_X86_REG_ESP) - 4
        uc.mem_write(esp, RET_PAD.to_bytes(4, "little"))
        uc.reg_write(UC_X86_REG_ESP, esp)
    uc.emu_start(va, until, count=10_000)


def rd(uc, reg):
    return uc.reg_read(R[reg])


def rm(uc, addr):
    return int.from_bytes(uc.mem_read(addr, 4), "little")


def rms(uc, addr):
    v = rm(uc, addr)
    return v - 0x100000000 if v >= 0x80000000 else v


# ---- tiny MOV-imm thunks ---------------------------------------------------
@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("reg,k", [("eax", 3), ("eax", 5), ("eax", 2),
                                   ("ebx", 3), ("edx", 2), ("ecx", 2)])
def test_mov_imm(g, reg, k):
    uc = mk(g)
    run(uc, f"t_mov_{reg}_s{k}")
    assert rd(uc, reg) == s(k, g)


# ---- production ------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_prod_ghost5(g):
    rect = 0x7AF200
    l, t, r, b = 351, 150, 602, 491
    uc = mk(g, regs={"edx": rect},
            mem={rect: l, rect + 4: t, rect + 8: r, rect + 12: b})
    run(uc, "t_prod_ghost5")
    assert rm(uc, FRAME - 0x1C) == l - s(5, g)
    assert rm(uc, FRAME - 0x18) == t + s(5, g)
    assert rm(uc, FRAME - 0x10) == b + s(5, g)
    assert rd(uc, "ecx") == r - s(5, g)


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("thunk,ld", [("t_prod_inner3", 0x1C),
                                      ("t_pop_inner3", 0x48)])
def test_inner3(g, thunk, ld):
    rect = 0x7AF300
    l, t, r, b = 140, 60, 241, 196
    uc = mk(g, regs={"esi": rect},
            mem={rect: l, rect + 4: t, rect + 8: r, rect + 12: b})
    run(uc, thunk)          # pop-ret: consumes our pushed RET_PAD, jmps to it
    assert rm(uc, FRAME - ld) == l + s(3, g)
    assert rm(uc, FRAME - ld + 4) == t + s(3, g)
    assert rm(uc, FRAME - ld + 8) == r - s(3, g)
    assert rm(uc, FRAME - ld + 12) == b - s(3, g)
    assert rd(uc, "esi") == b - s(3, g)
    assert rd(uc, "edx") == r - s(3, g)
    assert rd(uc, "ecx") == ASC.STRIP_CANVAS
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert rm(uc, esp) == FRAME - ld          # &rect-local pushed for box_sprite


@pytest.mark.parametrize("g", GS)
def test_union6(g):
    # prod: EAX carries s3 in, ESI accumulates; two s(6) pushed
    uc = mk(g, regs={"eax": s(3, g), "esi": 100})
    run(uc, "t_prod_union6")
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert rm(uc, esp) == s(6, g) and rm(uc, esp + 4) == s(6, g)
    assert rd(uc, "esi") == 100 + s(3, g)
    # flash: EAX is LIVE and must survive
    uc = mk(g, regs={"eax": 0x1234, "ebx": s(3, g), "edi": 200})
    run(uc, "t_flash_union6")
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert rm(uc, esp) == s(6, g) and rm(uc, esp + 4) == s(6, g)
    assert rd(uc, "edi") == 200 + s(3, g)
    assert rd(uc, "eax") == 0x1234


@pytest.mark.parametrize("g", GS)
def test_pic28(g):
    uc = mk(g, regs={"eax": 646}, mem={FRAME - 0x18: 150})
    run(uc, "t_prod_pic28")
    assert rd(uc, "edx") == 150 + s(0x28, g)
    assert rd(uc, "ebx") == 646 >> 1
    uc = mk(g, regs={"ecx": 7, "edx": 150})
    run(uc, "t_flash_pic28")
    assert rd(uc, "ebx") == 150 + s(0x28, g)
    assert rd(uc, "eax") == 7 * 3


@pytest.mark.parametrize("g", GS)
def test_name41(g):
    uc = mk(g, regs={"esi": 5}, mem={FRAME - 0x18: 213})
    run(uc, "t_prod_name41c")
    assert rd(uc, "ecx") == 213 + s(0x41, g)
    assert rd(uc, "edx") == 15
    uc = mk(g, regs={"edi": 5}, mem={FRAME - 0x18: 213})
    run(uc, "t_prod_name41b")
    assert rd(uc, "ebx") == 213 + s(0x41, g)
    assert rd(uc, "esi") == 5 * 48
    uc = mk(g, regs={"edi": 9, "ecx": 4}, mem={FRAME - 0x1C: 213})
    run(uc, "t_flash_name41")
    assert rd(uc, "eax") == 213 + s(0x41, g)
    assert rd(uc, "esi") == 9 + 4 * 4


@pytest.mark.parametrize("g", GS)
def test_icon(g):
    uc = mk(g, regs={"eax": 400, "ebx": 300, "ecx": 0x777, "edx": 0x888})
    run(uc, "t_prod_iconxy")
    assert rd(uc, "eax") == 400 - s(0x14, g)
    assert rd(uc, "ebx") == 300 - s(0x14, g)
    assert rd(uc, "ecx") == 0x777 and rd(uc, "edx") == 0x888
    uc = mk(g, regs={"eax": 0x55}, mem={FRAME - 0x20: 190})
    run(uc, "t_prod_iconsz")
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert rm(uc, esp) == 0x55                # color re-pushed on top
    assert rm(uc, esp + 4) == s(0x28, g)      # scaled size under it
    assert rd(uc, "eax") == 190


@pytest.mark.parametrize("g", GS)
def test_bars(g):
    uc = mk(g, regs={"edi": 9, "ebx": 321, "eax": 0x11})
    run(uc, "t_bar2a")
    assert rd(uc, "edx") == 9 * s(2, g) and rd(uc, "eax") == 0x11
    uc = mk(g, regs={"edi": 7, "eax": 13, "esi": 470, "ecx": 0x22})
    run(uc, "t_bar2b")
    assert rd(uc, "eax") == 13 * s(2, g) and rm(uc, FRAME - 0x28) == 7
    assert rd(uc, "ecx") == 0x22
    uc = mk(g, regs={"eax": 91, "edi": 7, "esi": 470, "ecx": 0x33})
    run(uc, "t_bar2c")
    assert rd(uc, "eax") == (91 // 7) * s(2, g)
    assert rd(uc, "ecx") == 0x33


@pytest.mark.parametrize("g", GS)
def test_barthresh(g):
    for cell_h in (s(8, g) - 1, s(8, g), s(8, g) + 5):
        uc = mk(g, regs={"ebx": cell_h, "eax": 100, "ecx": 200, "esi": 300,
                         "edi": 0x99})
        run(uc, "t_barthresh")
        if cell_h < s(8, g):
            assert rm(uc, FRAME - 0x40) == 200 - s(1, g)
        else:
            assert rm(uc, FRAME - 0x48) == 100 + s(1, g)
            assert rm(uc, FRAME - 0x40) == 200 - s(1, g)
            assert rm(uc, FRAME - 0x44) == 300 + s(1, g)
        assert rd(uc, "edi") == 0x99


@pytest.mark.parametrize("g", GS)
def test_bardec(g):
    uc = mk(g, regs={"edx": 500, "eax": 0x44}, mem={FRAME - 0x60: 3})
    run(uc, "t_bardec")
    assert rd(uc, "edx") == 500 - s(1, g)
    assert rd(uc, "ebx") == 3 and rd(uc, "eax") == 0x44


@pytest.mark.parametrize("g", GS)
def test_flash_ghost5(g):
    rect = 0x7AF400
    l, t, r, b = 351, 150, 602, 491
    uc = mk(g, regs={"edi": rect},
            mem={rect: l, rect + 4: t, rect + 8: r, rect + 12: b})
    run(uc, "t_flash_ghost5")
    assert rm(uc, FRAME - 0x20) == l - s(5, g)
    assert rm(uc, FRAME - 0x1C) == t + s(5, g)
    assert rm(uc, FRAME - 0x18) == r - s(5, g)
    assert rm(uc, FRAME - 0x14) == b + s(5, g)
    assert rd(uc, "edi") == b + s(5, g)
    assert rd(uc, "ecx") == ASC.STRIP_CANVAS
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert rm(uc, esp) == FRAME - 0x20        # &[ebp-0x20] on top
    assert rm(uc, esp + 4) == FRAME - 0x5C    # &[ebp-0x5c] under it


# ---- pop (citizens) --------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_pop_c30(g):
    cell_h = {16: 48, 22: 66, 25: 75, 40: 129}[g]
    uc = mk(g, regs={"eax": cell_h, "ecx": 0xCAFE})
    run(uc, "t_pop_c30")
    assert rm(uc, FRAME - 0x18) == cell_h
    assert rms(uc, FRAME - 0x18) - s(0x30, g) == cell_h - s(0x30, g)
    assert rd(uc, "eax") & 0xFFFFFFFF == (cell_h - s(0x30, g)) & 0xFFFFFFFF
    assert rd(uc, "ecx") == 0xCAFE
    # composed with the site's /2 + top, this IS the law:
    top = 292
    y = top + ((cell_h - s(0x30, g)) // 2 if cell_h >= s(0x30, g) else
               -((s(0x30, g) - cell_h) // 2))
    if cell_h >= s(0x30, g):
        assert y == SL.basewin_strip_pop_citizen_y(top, cell_h, g)


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("dest,num,den,expect_scaled", [
    (0x7AEC64, 1, 1, True),     # strip canvas, native ratio -> (g,16)
    (0x123456, 1, 1, False),    # other dest -> untouched
    (0x7AEC64, 2, 1, False),    # non-native ratio -> untouched (shared-field law)
])
def test_pop_ratio(g, dest, num, den, expect_scaled):
    args = [dest, 9, 100, 200, num, den]
    uc = mk(g, stack=args)
    # v3: the tail is thunk_face_hybrid on every path (its g<=16 / num>den guards hand the untouched
    # native ratio to the engine's Sprite_draw_2: test_face_hybrid_parity guard cases).
    run(uc, "t_pop_ratio", until=ASC.FACE_HYBRID, push_ret=True)
    esp = uc.reg_read(UC_X86_REG_ESP)
    got_num, got_den = rm(uc, esp + 0x14), rm(uc, esp + 0x18)
    assert [rm(uc, esp + 4 + 4 * i) for i in range(4)] == args[:4]      # dest,key,x,y untouched
    if expect_scaled and g > 16:
        assert (got_num, got_den) == (g, 16) == SL.basewin_sprite_ratio(1, 1, g)
        assert SL.basewin_pop_face_enlarge(g) == "hybrid"
    else:
        assert (got_num, got_den) == (num, den)
        if num <= den:                       # the hybrid's (= the bilinear's) guard -> the engine draw
            assert num <= den and (g > 16 or SL.basewin_pop_face_enlarge(g) == "engine")


def test_pop_ratio_tail_is_the_pinned_face_hybrid():
    import assemble_rw_kinds as RK
    assert ASC.SPRITE_BILINEAR == RK.SPRITE_BILINEAR == ASC.PCAVE2_VA + RK.PINNED["thunk_sprite_bilinear"]
    assert ASC.FACE_HYBRID == RK.FACE_HYBRID == ASC.PCAVE2_VA + RK.PINNED["thunk_face_hybrid"]


# ---- garrison --------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_garrison(g):
    uc = mk(g, regs={"eax": 0x77})
    run(uc, "t_garr_cell38")
    assert rm(uc, FRAME - 0x20) == s(0x38, g) and rd(uc, "eax") == 0x77
    uc = mk(g, regs={"eax": 0x77})
    run(uc, "t_garr_stats38")
    assert rm(uc, FRAME - 0x34) == s(0x38, g)
    # fit divisor: eax = W / (cell + s5)
    W, cell = 1310, s(0x38, g)
    uc = mk(g, regs={"eax": W, "ecx": cell})
    run(uc, "t_garr_fitdiv")
    assert rd(uc, "eax") == W // (cell + s(5, g))
    # squeeze edges
    uc = mk(g, regs={"eax": 610, "edx": 1920})
    run(uc, "t_garr_sq1")
    assert rd(uc, "ecx") == 610 + s(1, g)
    assert rd(uc, "eax") == 1920 - s(1, g)
    # squeeze cell
    uc = mk(g, regs={"eax": 163, "ecx": 0xBEEF})
    run(uc, "t_garr_sq5")
    assert rd(uc, "eax") == 163 - s(5, g) and rm(uc, FRAME - 0x20) == 163 - s(5, g)
    assert rd(uc, "ecx") == 0xBEEF
    # stats y (v3 07-25e: scaled path uses the scaled NATIVE metric 18, not
    # the engine's sublinear scaled-font metric in EDX)
    uc = mk(g, regs={"ecx": 627, "edx": 30, "eax": 0x66})
    run(uc, "t_garr_statsy")
    expect_y = (627 - 30 + 6 if g <= 16
                else SL.basewin_strip_garrison_stats_y(627, g))
    assert rd(uc, "ecx") == expect_y and rd(uc, "eax") == 0x66
    # advance
    uc = mk(g, regs={"eax": 611, "edx": 100, "edi": 650})
    run(uc, "t_garr_adv5")
    assert rd(uc, "ecx") == 611
    assert rd(uc, "eax") == 100 + 650 + s(5, g)


# ---- queue row pitch (07-25e) ----------------------------------------------
@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("thunk,out_reg", [("t_qrow_h_ecx", "ecx"),
                                           ("t_qrow_h_eax", "eax")])
def test_qrow_pitch(g, thunk, out_reg):
    """Both row-height cuts: g<=16 re-runs the vanilla metric read (both the
    >=0 and the negative metric branch); g>16 returns the remainder-
    distributed advance cum(i)-cum(i-1) of the vanilla pitch 13, and the
    cumulative sum telescopes to fl(13*i*g/16) exactly."""
    blk = {FRAME - 0x74: 4, FRAME - 0x64: 14, FRAME - 0x68: 99}
    total = 0
    for i in range(1, 9):
        uc = mk(g, regs={"edi": i, "ebx": 0x1111}, mem=blk)
        run(uc, thunk)
        h = rd(uc, out_reg)
        if g <= 16:
            assert h == 4 + 14, (thunk, i)          # vanilla metric path
        else:
            assert h == SL.basewin_strip_queue_row_advance(i, g), (thunk, i)
        assert rd(uc, "ebx") == 0x1111, (thunk, i)  # EBX (row y) untouched
        assert rd(uc, "edi") == i, (thunk, i)       # loop counter untouched
        total += h
    if g > 16:
        assert total == SL.basewin_strip_queue_row_y(8, g), thunk
    # negative metric branch (native only reachable form)
    uc = mk(g, regs={"edi": 1}, mem={FRAME - 0x74: 0xFFFFFFFF,
                                     FRAME - 0x68: 21, FRAME - 0x64: 7})
    run(uc, thunk)
    if g <= 16:
        assert rd(uc, out_reg) == 21, thunk


# ---- supported -------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_sup_scale(g):
    uc = mk(g, regs={"eax": 0x31})
    run(uc, "t_sup_scale")
    num, den = rm(uc, ASC.SCALE_NUM_G), rm(uc, ASC.SCALE_DEN_G)
    assert (num, den) == SL.basewin_strip_content(g)["sup_scale_pair"]
    assert rd(uc, "eax") == 0x31


@pytest.mark.parametrize("g", GS)
def test_sup_literals(g):
    c = SL.basewin_strip_content(g)
    for thunk, disp, key in (("t_sup_cell", 0x38, "sup_cell"),
                             ("t_sup_row", 0x4C, "sup_row"),
                             ("t_sup_icon1", 0x5C, "sup_icon"),
                             ("t_sup_icon2", 0x64, "sup_icon")):
        uc = mk(g, regs={"eax": 0x88})
        run(uc, thunk)
        assert rm(uc, FRAME - disp) == c[key], thunk
        assert rd(uc, "eax") == 0x88
    uc = mk(g, regs={"eax": 500, "ecx": 60})
    run(uc, "t_sup_fit1")
    assert rd(uc, "eax") == 500 - 60 - s(0xC, g) and rd(uc, "ecx") == 60
    uc = mk(g, regs={"eax": 500, "edi": 700, "ecx": 0x11})
    run(uc, "t_sup_fit2")
    assert rd(uc, "eax") == 500 - s(0xC, g)
    assert rd(uc, "edi") == 700 - s(0xC, g) and rd(uc, "ecx") == 0x11


# ---- info ------------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_info_pad(g):
    uc = mk(g, regs={"ecx": 20})              # native chevron width from +0xcaec
    run(uc, "t_info_pad")
    assert rds(uc) == -s(26, g)


def rds(uc):
    v = rd(uc, "eax")
    return v - 0x100000000 if v >= 0x80000000 else v


# ---- font adapters ---------------------------------------------------------
@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("size", (9, 10, 12))
def test_fontinit(g, size):
    uc = mk(g, stack=[0x691B2C, size, 0])     # name, size, style
    run(uc, "t_fontinit", until=ASC.FONT_INIT)
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert rm(uc, esp + 8) == SL.basewin_font_size(size, g)


@pytest.mark.parametrize("g", GS)
def test_sf_strip(g):
    # gated: shared header font on the strip canvas -> swapped to the cave Font
    uc = mk(g, regs={"ecx": ASC.STRIP_CANVAS},
            stack=[ASC.SHARED_FONT, 0, 0, 0])
    run(uc, "t_sf_strip", until=ASC.SET_FONT)
    esp = uc.reg_read(UC_X86_REG_ESP)
    want = ASC.G_BW_FONT if g > 16 else ASC.SHARED_FONT
    assert rm(uc, esp + 4) == want
    assert uc.reg_read(UC_X86_REG_ECX) == ASC.STRIP_CANVAS
    # gate miss: a local font arg passes through untouched
    uc = mk(g, regs={"ecx": ASC.STRIP_CANVAS}, stack=[0x1234, 0, 0, 0])
    run(uc, "t_sf_strip", until=ASC.SET_FONT)
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert rm(uc, esp + 4) == 0x1234


@pytest.mark.parametrize("g", GS)
def test_findfont(g):
    uc = mk(g, regs={"ecx": 0x77}, stack=[32, 1])
    if g > 16:
        run(uc, "t_findfont")                 # RETs back to RET_PAD
        # v2: t_ffn_at(g_font_bwname, S, v, g) -- the pool's face for the NATIVE S on the name's own slot
        assert rd(uc, "eax") == ASC.G_FONT_BWNAME
        assert tuple(rm(uc, 0x400800 + 4 * j) for j in range(4)) == (ASC.G_FONT_BWNAME, 32, 1, g)
        assert SL.font_face_law(32, 1, g) == ("init", "Arial Narrow", SL.font_scaled_size(32, g), 1) or SL.font_face_law(32, 1, g)[0] == "pool"
        assert rd(uc, "ecx") == 0x77
        esp = uc.reg_read(UC_X86_REG_ESP)
        assert rm(uc, esp) == 32              # cdecl args intact for the caller
    else:
        run(uc, "t_findfont", until=ASC.FIND_FONT)   # native tail-jmp


# ---- slice 2b: plate chevron window rects (BaseWin_init cuts) --------------
# fake BaseWin_g base chosen so +0xcaec/+0xcaf0 (chevron sprite w/h fields)
# land inside the mapped 0x7AF000 page
CHEV_ESI = 0x7AF100 - 0xCAEC


@pytest.mark.parametrize("g", GS)
def test_chev_btn2(g):
    plate = tuple(s(v, g) for v in (266, 70, 759, 111))
    uc = mk(g, regs={"ecx": plate[0], "edx": plate[1], "esi": CHEV_ESI,
                     "ebx": 0x2222, "edi": 0x3333},
            mem={CHEV_ESI + 0xCAEC: 20, CHEV_ESI + 0xCAF0: 35})
    run(uc, "t_chev_btn2")
    want = SL.basewin_strip_chevron_rects(plate, 20, 35, g)["btn2"]
    # exit contract: ecx=l, edx=t, eax=b, ebp locals -24/-1c/-20/-18 = l/r/t/b
    assert rd(uc, "ecx") == want[0], g
    assert rd(uc, "edx") == want[1], g
    assert rd(uc, "eax") == want[3], g
    assert rms(uc, FRAME - 0x24) == want[0], g
    assert rms(uc, FRAME - 0x1C) == want[2], g
    assert rms(uc, FRAME - 0x20) == want[1], g
    assert rms(uc, FRAME - 0x18) == want[3], g
    assert rd(uc, "ebx") == 0x2222 and rd(uc, "edi") == 0x3333, g


@pytest.mark.parametrize("g", GS)
def test_chev_btn3(g):
    plate = tuple(s(v, g) for v in (266, 70, 759, 111))
    uc = mk(g, regs={"ecx": plate[2], "esi": CHEV_ESI, "ebx": 0x2222},
            mem={CHEV_ESI + 0xCAEC: 20})
    run(uc, "t_chev_btn3")
    want = SL.basewin_strip_chevron_rects(plate, 20, 35, g)["btn3"]
    # vanilla continues: edx=ecx; [ebp-0x1c]=ecx; edx-=eax (=l)
    assert rd(uc, "ecx") == want[2], g
    assert rd(uc, "ecx") - rd(uc, "eax") == want[0], g
    assert rd(uc, "ebx") == 0x2222, g


# ---- slice 2c: title-box flush + native-space hit path ---------------------
@pytest.mark.parametrize("g", GS)
def test_info_titleb(g):
    plate = tuple(s(v, g) for v in (266, 70, 759, 111))
    # entry: esi=plate.t, edx=plate.b, ebx=s(3) (pre-scaled by t_mov_ebx_s3)
    uc = mk(g, regs={"esi": plate[1], "edx": plate[3], "ebx": s(3, g),
                     "edi": 0x3333})
    run(uc, "t_info_titleb")
    want = SL.basewin_title_box(plate, 20, 35, g)
    assert rd(uc, "esi") == want[1], g            # title.t = plate.t + s3
    assert rms(uc, FRAME - 0x4) == want[3], g     # title.b stored [ebp-0x4]
    assert rd(uc, "ebx") == s(3, g), g
    assert rd(uc, "edi") == 0x3333, g


@pytest.mark.parametrize("g", GS)
def test_info_btnframe(g):
    # entry (cut 0x415b4f): edx = redbtn.r (raw field), edi = &redbtn,
    # ebx = s(3) (pre-scaled by t_mov_ebx_s3); thunk loads b from [edi+0xc],
    # sets ecx = 0x7aec64 and stores the inflated frame r/b to [ebp-8/-4]
    rb = tuple(s(v, g) for v in (708, 117)) + \
        (s(708, g) + s(48, g), s(117, g) + s(48, g))
    rect = 0x7AF200
    uc = mk(g, regs={"edx": rb[2], "edi": rect, "ebx": s(3, g),
                     "esi": 0x6666},
            mem={rect: rb[0], rect + 4: rb[1], rect + 8: rb[2],
                 rect + 12: rb[3]})
    run(uc, "t_info_btnframe")
    want = SL.basewin_redbtn_frame(rb, g)
    assert rm(uc, FRAME - 0x8) == want[2], g       # frame.r
    assert rm(uc, FRAME - 0x4) == want[3], g       # frame.b
    assert rd(uc, "ecx") == 0x7AEC64, g            # replayed mov ecx, imm
    assert rd(uc, "edx") == want[2], g
    assert rd(uc, "edi") == want[3], g             # edi = b + s3 (- one)
    assert rd(uc, "ebx") == s(3, g), g
    assert rd(uc, "esi") == 0x6666, g


@pytest.mark.parametrize("g", GS)
def test_spotck_nat(g):
    x, y = s(400, g) + 1, s(150, g) + 1          # arbitrary device coords
    uc = mk(g, regs={"ecx": 0x11223344}, stack=[x, y, 0x7AF900, 0x7AF904])
    uc.mem_map(0x5FA000, 0x1000)
    uc.mem_write(0x5FAB00, b"\xC2\x10\x00")      # RET 0x10 stub = Spot_check
    esp0 = uc.reg_read(R["esi"])                 # placeholder; recompute below
    import unicorn.x86_const as XC
    esp0 = uc.reg_read(XC.UC_X86_REG_ESP)
    run(uc, "t_spotck_nat")                      # tail-jmps the stub -> RET_PAD
    # args were descaled IN PLACE before the tail-jmp (slots at entry esp)
    assert rm(uc, esp0) == SL.descale_point(x, g), g
    assert rm(uc, esp0 + 4) == SL.descale_point(y, g), g
    assert rd(uc, "ecx") == 0x11223344, g        # this preserved
    esp1 = uc.reg_read(XC.UC_X86_REG_ESP)
    assert esp1 == esp0 + 0x10, g                # stub RET 0x10 unwound the args


@pytest.mark.parametrize("g", GS)
def test_tilepick_nat(g):
    import unicorn.x86_const as XC
    x, y = s(300, g) + 2, s(100, g) + 2
    THIS = 0x7AF800 - 0x40B94                    # +0x40b94 lands in mapped page
    uc = mk(g, regs={"ecx": THIS, "ebx": 0x2222, "esi": 0x4444, "edi": 0x5555},
            stack=[0x00400180, x, y],            # [ret_caller][x][y]
            mem={0x7AF800: 0x1234})
    esp0 = uc.reg_read(XC.UC_X86_REG_ESP)
    run(uc, "t_tilepick_nat")                    # push_ret = the cut's E8 ret
    # frame exactly as after the vanilla prologue: ebp = entry esp, args live
    assert uc.reg_read(XC.UC_X86_REG_EBP) == esp0 - 4, g
    assert uc.reg_read(XC.UC_X86_REG_ESP) == esp0 - 4, g
    assert rm(uc, esp0 + 4) == SL.descale_point(x, g), g   # [ebp+8]
    assert rm(uc, esp0 + 8) == SL.descale_point(y, g), g   # [ebp+0xc]
    assert rd(uc, "eax") == 0x1234, g            # replayed field load
    assert rd(uc, "ecx") == THIS, g
    assert rd(uc, "ebx") == 0x2222 and rd(uc, "esi") == 0x4444, g
    assert rd(uc, "edi") == 0x5555, g
