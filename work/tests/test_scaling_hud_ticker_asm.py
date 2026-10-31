"""hud_ticker_rows (assemble_hud_ticker.py): ticker window + row tops at vanilla x g/16.

Unicorn on the patches.yaml bytes of t_ticker_attach / t_ticker_wraph at the real cave VAs:
  * attach: the y / h stack args TextScroll_attach receives == scaling_laws.hud_ticker_window;
  * wraph: TextScroll_draw's bottom-up loop (ebx = h; ebx -= wrap_h per entry) replayed against a
    Buffer_wrap_height stub returning rows * L_scaled -- every entry's top == hud_ticker_row_top.
"""
import pathlib
import sys

import pytest
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_ESI, UC_X86_REG_ESP)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_hud_ticker as AT  # noqa: E402
import scaling_laws as SL  # noqa: E402

SP0 = 0x00308000
RET = 0x00450000
FONT = 0x00600000
OTHER_BUF = 0x007CE000


def _yaml():
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    contents = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    out = {}
    for name in ("t_ticker_attach", "t_ticker_wraph"):
        c = contents[name]
        va = AT.PCAVE2 + int(c["offset"])
        out[name] = (va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab))
    return out


YAML = _yaml()


def _emu(g, d38, font_pad=-1, font_cell=36, font_cap=0):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AT.PCAVE2 + 0x30000, 0x1000), (0x00300000, 0x10000), (0x668000, 0x1000), (0x7AF000, 0x1000),
                       (0x7CD000, 0x2000), (FONT, 0x1000), (RET & ~0xFFF, 0x1000), (AT.TS_ATTACH & ~0xFFF, 0x1000),
                       (AT.WRAP_H & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    for va, code in YAML.values():
        uc.mem_write(va, code)
    uc.mem_write(AT.G, g.to_bytes(4, "little"))
    uc.mem_write(AT.D38, d38.to_bytes(4, "little"))
    for buf in (AT.TICKER_BUF, OTHER_BUF):
        uc.mem_write(buf + 0x52C, FONT.to_bytes(4, "little"))
    for off, v in ((0, font_pad), (0xC, font_cell), (0x10, font_cap)):
        uc.mem_write(FONT + off, v.to_bytes(4, "little", signed=True))
    uc.mem_write(RET, b"\xF4")
    uc.mem_write(AT.TS_ATTACH, b"\xF4")
    return uc


def _run(uc, va, stop, regs, stack):
    for i, v in enumerate(stack):
        uc.mem_write(SP0 + 4 * i, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    for r, v in regs.items():
        uc.reg_write(r, v & 0xFFFFFFFF)
    hit = []

    def hook(u, addr, size, _):
        if addr == stop:
            hit.append(addr)
            u.emu_stop()
    h = uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(va, 0, count=200_000)
    uc.hook_del(h)
    assert hit == [stop]


def test_yaml_bytes_are_the_assembler_output():
    built = AT.build()
    for name, (va, code) in YAML.items():
        assert code == built[name][1]


D38S = {16: 42, 17: 45, 22: 57, 25: 65, 32: 84, 40: 105}


@pytest.mark.parametrize("g", sorted(D38S))
def test_attach_window_is_the_law(g):
    d38 = D38S[g]
    uc = _emu(g, d38)
    native_h = 4 * 36                          # the engine's scaled-font h (anything; g<=16 must pass it through)
    _run(uc, AT.PCAVE2 + AT.ATTACH_OFF, AT.TS_ATTACH,
         {UC_X86_REG_ECX: 0x7CD2EC, UC_X86_REG_EAX: 0x1111, UC_X86_REG_ESI: 0x2222},
         [RET, 160, d38 - native_h, 3520, native_h, 0x939444, 0, 0x1000022])
    rd = lambda o: int.from_bytes(uc.mem_read(SP0 + o, 4), "little", signed=True)  # noqa: E731
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 and rd(0) == RET
    assert uc.reg_read(UC_X86_REG_EAX) == 0x1111 and uc.reg_read(UC_X86_REG_ECX) == 0x7CD2EC
    if g <= 16:                                # v2: the engine's own y lifted by 4 (vanilla-bug fix), h untouched
        assert (rd(8), rd(0x10)) == (SL.hud_ticker_native_y(d38 - native_h), native_h)
        assert rd(8) == d38 - native_h - SL.HUD_TICKER_LIFT_NATIVE
    else:
        assert (rd(8), rd(0x10)) == SL.hud_ticker_window(d38, g, native_h)
    assert (rd(4), rd(0xC), rd(0x14)) == (160, 3520, 0x939444)


def _wrap_stub(uc, line_h, rows_seq):
    """Buffer_wrap_height stub: returns rows_seq[i] * line_h on the i-th call (counter at 0x7CDF00), ret 8."""
    src = f"""
        mov  eax, dword ptr [0x7CDF00]
        inc  dword ptr [0x7CDF00]
        mov  eax, dword ptr [0x7CDF10 + eax*4]
        imul eax, eax, {line_h}
        ret  8
    """
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, AT.WRAP_H)
    uc.mem_write(AT.WRAP_H, bytes(enc))
    uc.mem_write(0x7CDF00, (0).to_bytes(4, "little"))
    for i, r in enumerate(rows_seq):
        uc.mem_write(0x7CDF10 + 4 * i, r.to_bytes(4, "little"))


@pytest.mark.parametrize("g, cell", [(17, 16), (18, 17), (22, 20), (25, 22), (32, 29), (40, 36)])
@pytest.mark.parametrize("rows_seq", [[1, 1, 1, 1], [2, 1, 1], [1, 3], [1, 1, 1, 1, 1]])
@pytest.mark.parametrize("font_pad", [-1, 2])
def test_bottom_up_rows_land_on_the_law(g, cell, rows_seq, font_pad):
    """(18, 17): a scaled line height ABOVE 15g/16 (16.875) -- the window keeps the engine's 4*L (68 > 67) and the
    rows stay anchored at its bottom.  font_pad >= 0: the pad + [+0x10] line-height path."""
    d38 = D38S.get(g, 0) or (42 * g // 16)
    line = font_pad + cell if font_pad >= 0 else cell
    uc = _emu(g, d38, font_pad=font_pad, font_cell=cell, font_cap=cell)
    _wrap_stub(uc, line, rows_seq)
    h = SL.hud_ticker_window(d38, g, 4 * line)[1]
    uc.mem_write(AT.TICKER_BUF + 0x84, (-h).to_bytes(4, "little", signed=True))
    ebx, k = h, 0
    for rows in rows_seq:
        _run(uc, AT.PCAVE2 + AT.WRAPH_OFF, RET,
             {UC_X86_REG_EDI: AT.TICKER_BUF, UC_X86_REG_ECX: AT.TICKER_BUF, UC_X86_REG_EBX: ebx,
              UC_X86_REG_ESI: 0x3333, UC_X86_REG_EBP: 0x4444},
             [RET, 0x12345678, 704])
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 12
        assert (uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EBP), uc.reg_read(UC_X86_REG_EBX)) == (0x3333, 0x4444, ebx)
        ebx -= uc.reg_read(UC_X86_REG_EAX)
        k += rows
        assert ebx == SL.hud_ticker_row_top(k, d38, g, h)


@pytest.mark.parametrize("g", [16, 40])
def test_other_buffers_and_native_keep_the_engine_value(g):
    uc = _emu(g, D38S[g], font_cell=36)
    _wrap_stub(uc, 36, [2])
    buf = OTHER_BUF if g > 16 else AT.TICKER_BUF
    _run(uc, AT.PCAVE2 + AT.WRAPH_OFF, RET, {UC_X86_REG_EDI: buf, UC_X86_REG_ECX: buf, UC_X86_REG_EBX: 150},
         [RET, 0x12345678, 704])
    assert uc.reg_read(UC_X86_REG_EAX) == 72


def test_law_matches_vanilla_and_the_measured_4k_target():
    # pristine 1024 trace: window y -18, h 60, bottom text row at canvas y 45; v2 lifts the window 4 native px
    assert SL.hud_ticker_window(42, 16) == (-18 - SL.HUD_TICKER_LIFT_NATIVE, 60)
    assert SL.hud_ticker_row_top(1, 42, 16) == 45                          # the rows ride the window (canvas-relative)
    assert SL.hud_ticker_native_y(-18) == -22
    assert SL.hud_ticker_window(105, 40) == (-55, 150)
    # 4K bottom row top: (vanilla 1545.5 at x2.5) - the lift fl(4 x 2.5) = 10 -> 1535
    assert 1628 - 55 - 150 + SL.hud_ticker_row_top(1, 105, 40) == 1535


# v2 (2026-10-15): the lift that lets the bottom row's descenders clear the console strip art.  Measured in the
# user's shots at the "y" of "atrocity.": baseline row / first strip-art row under it (or None: the map, no art):
# pristine 1024 235347 530/531 (descender covered), 1600 231143 829/834, 1080 231451 753/None, 4K 230701 1567/1568.
# The strip font's descent is 3 native rows (1024: rows 531..533).
SHOTS = {16: (530, 531), 25: (829, 834), 22: (753, None), 40: (1567, 1568)}


@pytest.mark.parametrize("g", sorted(SHOTS))
def test_lift_clears_the_strip_art_at_every_measured_g(g):
    base, art = SHOTS[g]
    d38 = D38S.get(g) or 57
    if g <= 16:
        lift = SL.HUD_TICKER_LIFT_NATIVE
    else:                                           # the bottom row's top moves with the window's floor-mapped y
        old_yn = SL.hud_ticker_bottom_native(d38, g) + SL.HUD_TICKER_LIFT_NATIVE
        lift = SL.popup_scale_floor(old_yn, g) - SL.popup_scale_floor(SL.hud_ticker_bottom_native(d38, g), g)
    if g > 16:                                      # the difference of two floored edges: fl(4g/16) or one more
        assert lift in (SL.popup_scale_floor(SL.HUD_TICKER_LIFT_NATIVE, g),
                        SL.popup_scale_floor(SL.HUD_TICKER_LIFT_NATIVE, g) + 1), (g, lift)
    else:
        assert lift == 4
    descent = -((-3 * max(g, 16)) // 16)            # 3 native rows, ceil-scaled (worst case)
    new_desc_bottom = base - lift + descent
    if art is not None:
        assert new_desc_bottom < art, (g, new_desc_bottom, art)


def test_v1_bytes_did_not_lift_at_native():
    """The v1 attach passed g <= 16 straight through: its first instruction was the g compare, not the lift."""
    va, code = YAML["t_ticker_attach"]
    assert code[:5] == bytes.fromhex("836C240804")          # sub dword ptr [esp+8], 4
    assert bytes.fromhex("83E840") in code                  # YN: sub eax, 64 (= 4*15 + 4)
