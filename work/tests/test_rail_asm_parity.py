"""Differential: the console-rail scrollbar asm vs the Python laws, emulated.

Five thunks ship for the ProdPicker scrollbar / console-rail fix:

  thunk_rail_ytop   @0x45E0B7 -- strip origin yTop = y1 + bp(13)  (and, as a
                                 side effect, g_rail_vstep = 0 so the vertical
                                 slide animation takes vanilla's degenerate path)
  thunk_rail_hstep  @0x45E351 -- horizontal unroll frame count -> 0
  thunk_rail_bufh   @0x45E22C -- strip buffer height -> ceil(h*16/g)
  thunk_rail_bake   @0x45E4C1 -- blit num/den -> g/16, x -> rail_strip_x (v3; was clientW - bp(47))
  thunk_rail_sbfit  @0x45E4C6 -- sb rect -> rail_layout's sb_x/y/w/h

Every one must be BYTE-IDENTICAL to vanilla when the window is not the picker
or g <= 16, and must agree with scaling_laws.rail_layout when it is.  Emulated
under Unicorn on the real assembled bytes.  Skips if keystone/unicorn absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone not installed")
unicorn = pytest.importorskip("unicorn", reason="unicorn not installed")

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_rail_scrollbar as A  # noqa: E402
import assemble_rail_sym as RS  # noqa: E402  (W3B: t_rsb_bar / t_rsb_cmap / t_rsb_blit, the bake's column blit + sbfit)

CODE = 0x00A00000            # covers pcave2 (0xA0C000) and the engine callees
ENGINE = 0x00500000
STACK = 0x00B00000
DATA = 0x00C00000
MARKER = 0x00DEAD00          # sentinel return address

G_ADDR = DATA + 0x100        # stands in for g_popup_scale_num
EBX_SRC = A.RAIL_EBX_SRC     # 0x669368, inside the ENGINE mapping
VTABLE = DATA + 0x200
SB_OBJ = DATA + 0x300
WIN_OBJ = A.PICKER           # the real picker VA, mapped in ENGINE


G_RAIL_SB_ADDR = DATA + 0x104   # stands in for g_rail_sb (v2 popup family)
POPUP_VTBL = DATA + 0x800        # a Popup-family vtable: [+4] == Popup_show
POPUP_OBJ = DATA + 0x900         # a heap-like Popup object (vtbl ptr at +0)
OTHER_VTBL = DATA + 0xA00        # some other window class
OTHER_OBJ = 0x6C2FD8             # "other window" static (mapped in ENGINE)
FILEDLG_OBJ = DATA + 0xB00       # a FileDlg (stack object in the game): vtbl ptr == FileDlg_vtbl (v4 family)
_SENT_MAP = {A.G: G_ADDR, A.G_RAIL_SB: G_RAIL_SB_ADDR,
             A.G_RAIL_GATE4: A.PCAVE2 + A.RAIL_GATE4_OFF}   # v4: trampoline target = the real body VA


def _bytes(fn, off):
    """Assemble one thunk and substitute the data sentinels with test addresses."""
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(fn(), addr=A.PCAVE2 + off)
    blob = bytearray(code)
    i = 0
    while i + 4 <= len(blob):
        v = int.from_bytes(blob[i:i + 4], "little")
        if v in _SENT_MAP:
            blob[i:i + 4] = _SENT_MAP[v].to_bytes(4, "little")
            i += 4
        else:
            i += 1
    for sent in _SENT_MAP:
        assert sent.to_bytes(4, "little") not in bytes(blob)
    return bytes(blob)


def _mk(g, win=WIN_OBJ):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x100000), (ENGINE, 0x300000),
                       (STACK, 0x10000), (DATA, 0x100000), (MARKER & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)     # deliberately non-overlapping; overlap = a bug here
    uc.mem_write(G_ADDR, int(g).to_bytes(4, "little"))
    uc.mem_write(0x668740, int(g).to_bytes(4, "little"))    # the real g: conftest pairs g_stripe_period with it
    uc.mem_write(EBX_SRC, (0x11223344).to_bytes(4, "little"))
    # callee-clean stubs
    uc.mem_write(A.BUFFER_INIT, b"\xC2\x10\x00")
    uc.mem_write(A.BUFFER_DRAW_2, b"\xC2\x18\x00")
    uc.mem_write(A.WIN_MOVE, b"\xC2\x08\x00")
    uc.mem_write(ENGINE + 0x1000, b"\xC2\x0C\x00")          # sb vtbl+0xC resize
    uc.mem_write(VTABLE + 0x0C, (ENGINE + 0x1000).to_bytes(4, "little"))
    uc.mem_write(SB_OBJ, VTABLE.to_bytes(4, "little"))
    # v2: the family gate helper at its fixed cave VA + the three window kinds
    uc.mem_write(A.RAIL_GATE_VA, _bytes(A.asm_rail_gate, A.RAIL_GATE_OFF))
    uc.mem_write(A.PCAVE2 + A.RAIL_GATE4_OFF, _bytes(A.asm_rail_gate4, A.RAIL_GATE4_OFF))   # v4 body
    uc.mem_write(A.RAIL_SX_VA, _bytes(A.asm_rail_sx, A.RAIL_SX_OFF))     # fix sbstrip: the strip-x helpers
    # fix rail2: the engine-column helpers + the bake's mark / wall passes (thunk_rail_d retired)
    for va, fn, off in ((A.NNCOL_VA, A.asm_rail_nncol, A.NNCOL_OFF), (A.WALLOFF_VA, A.asm_rail_walloff, A.WALLOFF_OFF),
                        (A.MARK_VA, A.asm_rail_mark, A.MARK_OFF), (A.WALL_VA, A.asm_rail_wall, A.WALL_OFF)):
        uc.mem_write(va, _bytes(fn, off))
    # W3B (2026-10-25): the bake's column blit and sbfit's bar helper, resolved to this rig's g / helpers
    w3b = {"g_popup_scale_num": G_ADDR, "thunk_rail_walloff": A.WALLOFF_VA, "thunk_rail_sx": A.RAIL_SX_VA,
           "Buffer_draw_2": A.BUFFER_DRAW_2, "thunk_sprite_scale_nn": A.SCALE_NN_VA, "restripe_core": MARKER,
           "thunk_btn_bandstripe": MARKER, "t_sbt_grip": MARKER,
           "t_nrs_grip": MARKER, "t_nrs_zoom": MARKER}             # W10S: the non-rail tails (unused by these six)
    for name in ("t_rsb_cmap", "t_rsb_blit", "t_rsb_bar", "t_rsb_mnn", "t_rsb_wspan", "t_rsb_lay"):
        uc.mem_write(RS.va(name), RS.assemble(name, w3b))
    uc.mem_write(FILEDLG_OBJ, A.FILEDLG_VTBL.to_bytes(4, "little"))
    uc.mem_write(POPUP_VTBL + 4, A.POPUP_SHOW.to_bytes(4, "little"))
    uc.mem_write(POPUP_OBJ, POPUP_VTBL.to_bytes(4, "little"))
    uc.mem_write(OTHER_VTBL + 4, (0x5EABCD).to_bytes(4, "little"))
    uc.mem_write(OTHER_OBJ, OTHER_VTBL.to_bytes(4, "little"))
    uc.mem_write(WIN_OBJ, OTHER_VTBL.to_bytes(4, "little"))   # picker keys on identity, not vtbl
    return uc


def _frame(uc, y1=0, clientw=0, win=WIN_OBJ):
    """Lay out the helper's ebp frame: [ebp+8]=win, [ebp+0xC]=&sb, [ebp-0x18]=y1."""
    ebp = STACK + 0x8000
    uc.mem_write(ebp + 8, int(win).to_bytes(4, "little"))
    uc.mem_write(ebp + 0x0C, SB_OBJ.to_bytes(4, "little"))
    uc.mem_write(ebp - 0x18, int(y1).to_bytes(4, "little", signed=False))
    if clientw:
        uc.mem_write(WIN_OBJ + A.F_WINW, int(clientw).to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_EBP, ebp)
    return ebp


def _run(uc, va, code, esp, regs=(), stop=MARKER, count=4000):
    uc.mem_write(va, code)
    uc.reg_write(UC_X86_REG_ESP, esp)
    for r, v in regs:
        uc.reg_write(r, v & 0xFFFFFFFF)
    uc.emu_start(va, stop, count=count)


# --------------------------------------------------------------------------
# site A -- strip origin / vertical-animation kill
# --------------------------------------------------------------------------
@pytest.mark.parametrize("win", [WIN_OBJ, POPUP_OBJ], ids=["picker", "popup"])
@pytest.mark.parametrize("g", [16, 22, 25, 32, 40])
@pytest.mark.parametrize("y1", [139, 203, 467])
def test_ytop_matches_the_law_and_is_vanilla_at_native(g, y1, win):
    uc = _mk(g, win=win)
    _frame(uc, y1=y1, win=win)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    # vanilla register contract at 0x45E0B7: edi = max(A,y1), ecx = min(y1+13, edi)
    a = SL.RAIL_INSET_A
    edi = max(a, y1)
    ecx = min(y1 + 13, edi)
    _run(uc, A.PCAVE2 + A.YTOP_OFF, _bytes(A.asm_ytop, A.YTOP_OFF), esp,
         [(UC_X86_REG_EDI, edi), (UC_X86_REG_ECX, ecx), (UC_X86_REG_EAX, 0xBAD)])
    got_ecx = uc.reg_read(UC_X86_REG_ECX)
    got_eax = uc.reg_read(UC_X86_REG_EAX)
    assert uc.reg_read(UC_X86_REG_EBX) == 0x11223344      # the displaced load
    if g <= 16:
        assert got_ecx == ecx and got_eax == edi          # bit-identical vanilla
    else:
        assert got_ecx - y1 == SL.rail_top_inset(y1, g)   # yTop = y1 + bp(13)
        assert got_eax == got_ecx                         # -> vstep 0


def test_ytop_leaves_other_windows_alone():
    uc = _mk(40, win=OTHER_OBJ)
    _frame(uc, y1=139, win=OTHER_OBJ)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.YTOP_OFF, _bytes(A.asm_ytop, A.YTOP_OFF), esp,
         [(UC_X86_REG_EDI, 238), (UC_X86_REG_ECX, 152)])
    assert uc.reg_read(UC_X86_REG_ECX) == 152 and uc.reg_read(UC_X86_REG_EAX) == 238


# --------------------------------------------------------------------------
# site B -- horizontal unroll frame count
# --------------------------------------------------------------------------
@pytest.mark.parametrize("win,gated", [(WIN_OBJ, True), (POPUP_OBJ, True), (FILEDLG_OBJ, True), (OTHER_OBJ, False)],
                         ids=["picker", "popup", "filedlg", "other"])
@pytest.mark.parametrize("g", [16, 22, 40])
@pytest.mark.parametrize("mp,vanilla", [(0, 8), (1, 4)])
def test_hstep_zeroes_only_for_the_gated_window(g, mp, vanilla, win, gated):
    uc = _mk(g, win=win)
    _frame(uc, win=win)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    # caller reaches the site with ecx = 0 (non-MP) or -1 (MP) from `sbb ecx,ecx`
    _run(uc, A.PCAVE2 + A.HSTEP_OFF, _bytes(A.asm_hstep, A.HSTEP_OFF), esp,
         [(UC_X86_REG_ECX, -1 if mp else 0), (UC_X86_REG_EAX, 0x1234),
          (UC_X86_REG_EDI, 0x5678)])
    assert uc.reg_read(UC_X86_REG_ECX) == (0 if (g > 16 and gated) else vanilla)
    assert uc.reg_read(UC_X86_REG_EAX) == 0x1234      # MP-flag copy preserved
    assert uc.reg_read(UC_X86_REG_EDI) == 0x5678


# --------------------------------------------------------------------------
# rail_slide_out @0x45E7C3 -- the HIDE helper's roll-up frame count (v2)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("win,gated", [(WIN_OBJ, True), (POPUP_OBJ, True), (FILEDLG_OBJ, True), (OTHER_OBJ, False)],
                         ids=["picker", "popup", "filedlg", "other"])
@pytest.mark.parametrize("g", [16, 22, 40])
@pytest.mark.parametrize("mp,vanilla", [(0, 8), (1, 4)])
def test_railout_hstep_zeroes_and_clears_the_stash_for_the_family(g, mp, vanilla, win, gated):
    uc = _mk(g, win=win)
    ebp = STACK + 0x8000
    uc.mem_write(ebp + 8, (0xC0FFEE).to_bytes(4, "little"))     # CLOBBERED there (canvas ptr)
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.mem_write(G_RAIL_SB_ADDR, SB_OBJ.to_bytes(4, "little"))
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.RAILOUT_HSTEP_OFF, _bytes(A.asm_railout_hstep, A.RAILOUT_HSTEP_OFF),
         esp, [(UC_X86_REG_ECX, -1 if mp else 0), (UC_X86_REG_EAX, 0x1234),
               (UC_X86_REG_EDI, win), (UC_X86_REG_EDX, 0x77)])
    hit = g > 16 and gated
    assert uc.reg_read(UC_X86_REG_ECX) == (0 if hit else vanilla)
    assert uc.reg_read(UC_X86_REG_EAX) == 0x1234      # LIVE across the site
    assert uc.reg_read(UC_X86_REG_EDI) == win and uc.reg_read(UC_X86_REG_EDX) == 0x77
    stash = int.from_bytes(uc.mem_read(G_RAIL_SB_ADDR, 4), "little")
    assert stash == (0 if hit else SB_OBJ)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4


def test_rail_gate_returns_zf_for_exactly_the_family():
    """ZF=1 for the picker static and any object whose [vtbl+4]==Popup_show; ZF=0
    otherwise; every register preserved."""
    from unicorn.x86_const import UC_X86_REG_EFLAGS
    for win, want in ((WIN_OBJ, True), (POPUP_OBJ, True), (A.REPORTWIN, True), (FILEDLG_OBJ, True),
                      (OTHER_OBJ, False)):   # v3: + ReportWin; v4: + FileDlg (through the 0x11200 trampoline)
        uc = _mk(40, win=win)
        _frame(uc, win=win)
        esp = STACK + 0x4000
        uc.mem_write(esp, MARKER.to_bytes(4, "little"))
        _run(uc, A.RAIL_GATE_VA, _bytes(A.asm_rail_gate, A.RAIL_GATE_OFF), esp,
             [(UC_X86_REG_EAX, 0xA5A5), (UC_X86_REG_ECX, 0x11), (UC_X86_REG_EDX, 0x22)])
        zf = bool(uc.reg_read(UC_X86_REG_EFLAGS) & 0x40)
        assert zf == want, (hex(win), zf)
        assert uc.reg_read(UC_X86_REG_EAX) == 0xA5A5
        assert uc.reg_read(UC_X86_REG_ECX) == 0x11 and uc.reg_read(UC_X86_REG_EDX) == 0x22
        assert uc.reg_read(UC_X86_REG_ESP) == esp + 4


# --------------------------------------------------------------------------
# site C -- strip buffer height
# --------------------------------------------------------------------------
@pytest.mark.parametrize("g", [16, 22, 25, 32, 40])
def test_bufh_passes_the_native_height_to_buffer_init(g):
    win_h = 490 * g // 16
    inset = SL.rail_top_inset(139 if g == 16 else 0, g)
    span = win_h - inset
    uc = _mk(g)
    _frame(uc)
    esp = STACK + 0x4000 - 0x14
    for i, v in enumerate((MARKER, 47, span, 0, 0)):
        uc.mem_write(esp + 4 * i, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.BUFH_OFF, _bytes(A.asm_bufh, A.BUFH_OFF), esp,
         [(UC_X86_REG_ECX, DATA + 0x400)])
    # Buffer_init's `ret 0x10` popped the 4 args; read them back off the stack
    w = int.from_bytes(uc.mem_read(esp + 4, 4), "little")
    h = int.from_bytes(uc.mem_read(esp + 8, 4), "little")
    assert w == 47                                            # width stays native
    assert h == SL.rail_strip_src_h(win_h, inset, g)
    if g <= 16:
        assert h == span                                      # identity
    else:
        assert SL.rail_quantized_h(h) == SL.rail_quantized_h(
            SL.rail_strip_src_h(490, 13, 16))                 # same tile count


# --------------------------------------------------------------------------
# site D -- the enlarging bake (v2: + channel restripe, 2026-08-15)
# --------------------------------------------------------------------------
_RR_SENT = {A.G_RR_RET: DATA + 0x110, A.G_RR_DST: DATA + 0x114, A.G_RR_X: DATA + 0x118,
            A.G_RR_Y: DATA + 0x11C, A.G_RR_W: DATA + 0x120, A.G_RR_H: DATA + 0x124, A.G_RR_SRC: DATA + 0x128}
_SENT_MAP.update(_RR_SENT)

STRIP_BUF, STRIP_PIX = DATA + 0x400, DATA + 0x2000        # native strip bufA
DEST_BUF, DEST_PIX = DATA + 0x600, DATA + 0x8000          # the popup/picker canvas


def _mk_buf(uc, buf, pix, w, h, stride, pixels):
    for off, v in ((0x54, pix), (0x80, w), (0x84, (-h) & 0xFFFFFFFF), (0x4A8, stride)):
        uc.mem_write(buf + off, int(v).to_bytes(4, "little"))
    uc.mem_write(pix, bytes(pixels))


def _strip_pixels(h_nat, art_rows):
    """A native 47-wide strip: rows 3..3+art_rows are console_x-style art
    (row dither 41/C5 with AE guide columns at 3/28 and an F0 bevel column at 0
    in the top cap), the wall column 32..46 solid 0x4F/0x50, everything else key 9."""
    w = 47
    px = bytearray([9] * (w * h_nat))
    for y in range(3, 3 + art_rows):
        base = 0xC5 if (y % 2 == 0) else 0x41
        for x in range(32):
            v = base
            if x in (3, 28):
                v = 0xAE
            if y < 3 + 5 and x == 0:
                v = 0xF0
            px[y * w + x] = v
        for x in range(32, 47):
            px[y * w + x] = 0x4F if (x % 3) else 0x50
    return px


def _nn_blit(src, sw, sh, num, den):
    """The engine's keyed uniform enlarge, modelled as floor NN (the exact
    mapping is irrelevant to the law under test: the thunk keys on the MARK,
    not on geometry).  Returns (pixels, dw, dh)."""
    dw, dh = sw * num // den, sh * num // den
    out = bytearray(dw * dh)
    for y in range(dh):
        sy = y * den // num
        for x in range(dw):
            out[y * dw + x] = src[sy * sw + x * den // num]
    return out, dw, dh


@pytest.mark.parametrize("win", [WIN_OBJ, POPUP_OBJ], ids=["picker", "popup"])
@pytest.mark.parametrize("g", [16, 22, 25, 32, 40])
def test_bake_enlarges_the_strip_moves_it_left_and_restripes_the_channel(g, win):
    clientw = 758 * g // 16
    uc = _mk(g, win=win)
    _frame(uc, clientw=clientw, win=win)
    # native strip (bufA) + a dest canvas prefilled with a C6/41 backdrop dither
    h_nat, art = 60, 40
    strip = _strip_pixels(h_nat, art)
    _mk_buf(uc, STRIP_BUF, STRIP_PIX, 47, h_nat, 47, strip)
    cw, ch = clientw, 400
    backdrop = bytearray((0xC6 if (y % 2) else 0x41) for y in range(ch) for _x in range(cw))
    _mk_buf(uc, DEST_BUF, DEST_PIX, cw, ch, cw, backdrop)
    esp = STACK + 0x4000 - 0x1C
    X0, Y0 = clientw - 47, SL.rail_top_inset(0, g)
    args = (MARKER, DEST_BUF, 9, X0, Y0, 1, 1)
    for i, v in enumerate(args):
        uc.mem_write(esp + 4 * i, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    seen = {}

    def on_blit(u, addr, size, _):
        """Stand-in Buffer_draw_2: perform the keyed NN enlarge into the dest,
        record the args, then behave as `ret 0x18`."""
        sp = u.reg_read(UC_X86_REG_ESP)
        rd = lambda o: int.from_bytes(u.mem_read(sp + o, 4), "little")
        dst, key, x, y, num, den = (rd(o) for o in (4, 8, 0xC, 0x10, 0x14, 0x18))
        seen.update(x=x, y=y, num=num, den=den, dst=dst, this=u.reg_read(UC_X86_REG_ECX))
        src = bytes(u.mem_read(STRIP_PIX, 47 * h_nat))
        out, dw, dh = _nn_blit(src, 47, h_nat, num, den)
        canvas = bytearray(u.mem_read(DEST_PIX, cw * ch))
        for yy in range(dh):
            for xx in range(dw):
                v = out[yy * dw + xx]
                if v != key and 0 <= x + xx < cw and 0 <= y + yy < ch:
                    canvas[(y + yy) * cw + (x + xx)] = v
        u.mem_write(DEST_PIX, bytes(canvas))
        seen["nn"] = (out, dw, dh)
        ret = int.from_bytes(u.mem_read(sp, 4), "little")
        u.reg_write(UC_X86_REG_ESP, sp + 4 + 0x18)
        u.reg_write(unicorn.x86_const.UC_X86_REG_EIP, ret)

    uc.hook_add(UC_HOOK_CODE, on_blit, begin=A.BUFFER_DRAW_2, end=A.BUFFER_DRAW_2)

    def on_rsb(u, addr, size, _):
        """W3B: the bake CALLs t_rsb_blit with Buffer_draw_2's args -- record them (the thunk then runs for real)."""
        sp = u.reg_read(UC_X86_REG_ESP)
        rd = lambda o: int.from_bytes(u.mem_read(sp + o, 4), "little")
        seen.update(x=rd(0xC), y=rd(0x10), num=rd(0x14), den=rd(0x18), dst=rd(4), this=u.reg_read(UC_X86_REG_ECX),
                    rsb=True)
    uc.hook_add(UC_HOOK_CODE, on_rsb, begin=RS.va("t_rsb_blit"), end=RS.va("t_rsb_blit"))
    uc.mem_write(A.SPR_R_OUTER + 8, (0xFE).to_bytes(4, "little"))       # r_outer's key byte

    def on_wall(u, addr, size, _):
        """Stand-in thunk_sprite_scale_nn (RET 0x18): record the wall call + the dest height field it sees."""
        sp = u.reg_read(UC_X86_REG_ESP)
        rd = lambda o: int.from_bytes(u.mem_read(sp + o, 4), "little")
        seen["wall"] = dict(this=u.reg_read(UC_X86_REG_ECX), dst=rd(4), key=rd(8), x=rd(0xC), y=rd(0x10),
                            num=rd(0x14), den=rd(0x18),
                            h=int.from_bytes(u.mem_read(rd(4) + 0x84, 4), "little", signed=True))
        ret = rd(0)
        u.reg_write(UC_X86_REG_ESP, sp + 4 + 0x18)
        u.reg_write(unicorn.x86_const.UC_X86_REG_EIP, ret)

    uc.hook_add(UC_HOOK_CODE, on_wall, begin=A.SCALE_NN_VA, end=A.SCALE_NN_VA)
    _run(uc, A.PCAVE2 + A.BAKE2_OFF, _bytes(A.asm_bake2, A.BAKE2_OFF), esp,
         [(UC_X86_REG_ECX, STRIP_BUF)], count=5_000_000)
    assert int.from_bytes(uc.mem_read(DEST_BUF + 0x84, 4), "little", signed=True) == -ch     # restored
    L = SL.rail_layout(clientw, 490 * g // 16, g, y1=139 if g == 16 else 0)
    assert (seen["num"], seen["den"]) == (L["blit_num"], L["blit_den"])
    assert seen["x"] == L["bake_x"] and seen["y"] == L["bake_y"]
    assert seen["this"] == STRIP_BUF and seen["dst"] == DEST_BUF
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4 + 0x18     # callee-clean, args consumed
    canvas = bytes(uc.mem_read(DEST_PIX, cw * ch))
    if g > 16:
        # W3B: the strip went through t_rsb_blit, never the engine -- the rail column [x0, x0 + Wc) carries the MARKED
        # strip on rail_col_map's columns and the engine's own rows (rail_blit_rows); the wall columns were keyed out
        assert "nn" not in seen
        marked = bytes(uc.mem_read(STRIP_PIX, 47 * h_nat))
        cmap = SL.rail_col_map(cw, g)
        rows = SL.rail_blit_rows(h_nat, g, seen["y"], ch)
        dh, dw = len(rows), len(cmap)
        out = bytearray(dw * dh)
        for yy, r in enumerate(rows):
            for xx, k in enumerate(cmap):
                out[yy * dw + xx] = marked[r * 47 + k]
    else:
        out, dw, dh = seen["nn"]
    if g <= 16:
        assert (seen["x"], seen["num"], seen["den"]) == (clientw - 47, 1, 1)
        # vanilla path: strip untouched, canvas = plain blit of the raw art
        assert bytes(uc.mem_read(STRIP_PIX, 47 * h_nat)) == bytes(strip)
    # every dest pixel: painted region follows the law, the rest is the untouched backdrop
    x0, y0 = seen["x"], seen["y"]
    for yy in range(ch):
        for xx in range(cw):
            got = canvas[yy * cw + xx]
            inside = x0 <= xx < x0 + dw and y0 <= yy < y0 + dh
            src = out[(yy - y0) * dw + (xx - x0)] if inside else None
            if inside and src != 9:
                if g > 16:
                    # src is the MARKED strip: mark -> law colour, else raw art
                    want = SL.rail_channel_pixel(src, yy, g)
                    assert src != 0x41 and src != 0xC5, "pass 1 must have marked every member"
                else:
                    want = src
                assert got == want, (g, xx, yy, hex(got), hex(want))
            else:
                assert got == (0xC6 if (yy % 2) else 0x41), (g, xx, yy, hex(got))
    if g > 16:
        # and the marker never survives into the canvas
        assert SL.RAIL_CHANNEL_MARK not in canvas
        # the AE guide lines / F0 bevel came through the NN untouched; the WALL did not (fix rail2: thunk_rail_mark
        # keys strip columns 32..46 out -- the wall is r_outer through scale_nn, below)
        assert canvas.count(0xAE) > 0 and canvas.count(0xF0) > 0
        assert canvas.count(0x4F) == 0 and canvas.count(0x50) == 0
        sp_ = bytes(uc.mem_read(STRIP_PIX, 47 * h_nat))
        assert all(sp_[y * 47 + x] == 9 for y in range(h_nat) for x in range(32, 47))
        w = seen["wall"]
        assert (w["this"], w["dst"], w["key"], w["num"], w["den"]) == (A.SPR_R_OUTER, DEST_BUF, 0xFE, g, 16)
        assert (w["x"], w["y"]) == (L["wall_x"], L["bake_y"]) and L["wall_x"] == seen["x"] + dw   # flush on the column
        assert w["h"] == -min(L["bake_y"] + (h_nat * g >> 4), ch)        # rows clipped to the engine strip's
    else:
        assert "wall" not in seen and canvas.count(0x4F) > 0              # vanilla: the strip's own wall, 1:1


# --------------------------------------------------------------------------
# site E -- seating the bar in the enlarged rail
# --------------------------------------------------------------------------
@pytest.mark.parametrize("win", [WIN_OBJ, POPUP_OBJ], ids=["picker", "popup"])
@pytest.mark.parametrize("g", [16, 22, 25, 32, 40])
def test_sbfit_produces_the_law_rect(g, win):
    win_w, win_h = 758 * g // 16, 490 * g // 16
    L = SL.rail_layout(win_w, win_h, g, y1=139 if g == 16 else 0)
    uc = _mk(g, win=win)
    _frame(uc, clientw=win_w, win=win)
    uc.mem_write(win + A.F_WINW, int(win_w).to_bytes(4, "little"))
    seen = {}

    def on_code(u, addr, size, _):
        sp = u.reg_read(UC_X86_REG_ESP)
        rd = lambda o: int.from_bytes(u.mem_read(sp + o, 4), "little")
        if addr == ENGINE + 0x1000:
            seen["resize"] = (rd(4), rd(8), rd(0x0C), u.reg_read(UC_X86_REG_ECX))
        elif addr == A.WIN_MOVE:
            seen["move"] = (rd(4), rd(8), u.reg_read(UC_X86_REG_ECX))

    uc.hook_add(UC_HOOK_CODE, on_code, begin=ENGINE, end=ENGINE + 0x300000)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.SBFIT_OFF, _bytes(A.asm_sbfit, A.SBFIT_OFF), esp,
         [(UC_X86_REG_EBX, win), (UC_X86_REG_ESI, L["rail_h"])])
    w, h, zero, this_r = seen["resize"]
    x, y, this_m = seen["move"]
    assert (w, h) == (L["sb_w"], L["sb_h"]) and zero == 0
    assert (x, y) == (L["sb_x"], L["sb_y"])
    assert this_r == SB_OBJ and this_m == SB_OBJ          # thiscall = &sb
    assert uc.reg_read(UC_X86_REG_EDI) == SB_OBJ          # caller's show()
    assert uc.reg_read(UC_X86_REG_EBX) == win             # ebx preserved
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4         # balanced
    stash = int.from_bytes(uc.mem_read(G_RAIL_SB_ADDR, 4), "little")
    if g <= 16:
        assert (w, h, x, y) == (0x18, L["rail_h"] - 10, win_w - 0x2B, 0x15)
        assert stash == 0                                  # vanilla path: no arm
    else:
        assert stash == SB_OBJ                             # the fitted bar is armed


def test_sbfit_leaves_other_windows_alone():
    uc = _mk(40, win=OTHER_OBJ)
    _frame(uc, clientw=0, win=OTHER_OBJ)
    uc.mem_write(OTHER_OBJ + A.F_WINW, (800).to_bytes(4, "little"))
    seen = {}
    uc.hook_add(UC_HOOK_CODE,
                lambda u, a, s, _: seen.update(
                    move=(int.from_bytes(u.mem_read(u.reg_read(UC_X86_REG_ESP) + 4, 4), "little"),
                          int.from_bytes(u.mem_read(u.reg_read(UC_X86_REG_ESP) + 8, 4), "little")))
                if a == A.WIN_MOVE else None,
                begin=A.WIN_MOVE, end=A.WIN_MOVE)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.SBFIT_OFF, _bytes(A.asm_sbfit, A.SBFIT_OFF), esp,
         [(UC_X86_REG_EBX, OTHER_OBJ), (UC_X86_REG_ESI, 425)])
    assert seen["move"] == (800 - 0x2B, 0x15)
    assert int.from_bytes(uc.mem_read(G_RAIL_SB_ADDR, 4), "little") == 0


def test_thunks_fit_their_ledger_allocated_slots():
    """pcave2 ledger says 0x10362-0x10FFF is free; nothing may cross a neighbour."""
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    slots = [(A.YTOP_OFF, A.asm_ytop, A.HSTEP_OFF),
             (A.HSTEP_OFF, A.asm_hstep, A.BUFH_OFF),
             (A.BUFH_OFF, A.asm_bufh, A.BAKE_OFF),
             (A.BAKE2_OFF, A.asm_bake2, A.BAKE2_END),
             (A.SBFIT_OFF, A.asm_sbfit, A.ARROWFIT_OFF),
             (A.ARROWFIT_OFF, A.asm_arrowfit, A.SB_RESTRIPE_OFF),
             (A.SB_RESTRIPE_OFF, A.asm_sb_restripe, A.G_SB_CUR_OFF),
             (A.RAIL_GATE_OFF, A.asm_rail_gate, A.MARK_OFF),
             (A.RAILOUT_HSTEP_OFF, A.asm_railout_hstep, A.RAILOUT_HSTEP_END),
             (A.RAILOUT_CAPW_OFF, A.asm_railout_capw, A.RAILOUT_CAPW_END),
             (A.RAIL_GATE4_OFF, A.asm_rail_gate4, A.RAIL_SBARROWS_OFF),
             (A.RAIL_SBARROWS_OFF, A.asm_rail_sbarrows, A.LIST_GATE_OFF),
             (A.LIST_GATE_OFF, A.asm_list_gate, A.FD_WHEELBAR_OFF),
             (A.FD_WHEELBAR_OFF, A.asm_fd_wheelbar, A.RAIL_V4_END),
             (A.RAIL_SX_OFF, A.asm_rail_sx, A.RAIL_SX_END),
             (A.NNCOL_OFF, A.asm_rail_nncol, A.NNCOL_END),
             (A.MARK_OFF, A.asm_rail_mark, A.MARK_END),
             (A.WALL_OFF, A.asm_rail_wall, A.WALL_END),
             (A.WALLOFF_OFF, A.asm_rail_walloff, A.WALLOFF_END)]
    assert A.G_RR_SRC_OFF >= 0x103AC, "would overwrite thunk_fe_pair_remap v9 (940B, ends 0x103AC)"
    assert A.G_RR_SRC_OFF + 4 <= A.RAIL_SX_OFF
    assert A.NNCOL_OFF >= 0x10493 and A.MARK_OFF >= 0x11206 and A.MARK_END <= A.G_RAIL_SB_OFF
    assert A.WALL_OFF >= 0xC3CB, "would overwrite thunk_pf_union_align (ends 0xC3CB)"
    assert A.WALLOFF_END <= 0xC470, "would overwrite thunk_filedlg_railscale @0xC470"
    assert A.RAIL_SX_END <= 0x103FC, "would overwrite g_rm_yph @0x103FC"
    assert A.RAIL_GATE_OFF >= 0x111DA, "would overwrite thunk_q16_fill_width v4 (ends 0x111DA)"
    assert A.G_RAIL_SB_OFF + 4 <= 0x12000
    assert slots[0][0] >= 0x103A4, "would overwrite thunk_fe_pair_remap v7 (932B, ends 0x103A4)"
    for off, fn, end in slots:
        code, _ = ks.asm(fn(), addr=A.PCAVE2 + off)
        assert off + len(code) <= end, (hex(off), len(code))


# --------------------------------------------------------------------------
# thunk_sb_arrowfit -- ScrollBar_on_resize's missing UP-arrow resize
# --------------------------------------------------------------------------
SCROLL = DATA + 0x500          # a stand-in Scroll object (needs 0x2000 bytes)


def _mk_scroll(uc, b, bordered, up_w):
    """[+0xA60]=b, [+0xA1C]=border colour, both arrow sub-windows with a vtable
    whose +0xC is the recording resize stub."""
    uc.mem_write(SCROLL + 0xA60, int(b).to_bytes(4, "little"))
    uc.mem_write(SCROLL + 0xA1C, (7 if bordered else 0xFFFFFFFF).to_bytes(4, "little"))
    for off in (0xAAC, 0x15F8):
        uc.mem_write(SCROLL + off, VTABLE.to_bytes(4, "little"))
    uc.mem_write(SCROLL + 0xAAC + A.F_WINW, int(up_w).to_bytes(4, "little"))


@pytest.mark.parametrize("g", [16, 22, 25, 32, 40])
@pytest.mark.parametrize("bordered", [False, True])
def test_arrowfit_resizes_both_arrows_to_the_same_square(g, bordered):
    b = SL.basewin_pt(0x18, g)
    want = SL.scrollbar_arrow_square(b, bordered)
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x100000), (ENGINE, 0x300000),
                       (STACK, 0x10000), (DATA, 0x4000), (MARKER & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(ENGINE + 0x1000, b"\xC2\x0C\x00")             # GraphicWin_resize, RET 0xC
    uc.mem_write(VTABLE + 0x0C, (ENGINE + 0x1000).to_bytes(4, "little"))
    # up arrow still at its CREATION size -> the vanilla bug's condition
    _mk_scroll(uc, b, bordered, 0x18 - (2 if bordered else 0))

    calls = []
    def on_code(u, addr, size, _):
        sp = u.reg_read(UC_X86_REG_ESP)
        rd = lambda o: int.from_bytes(u.mem_read(sp + o, 4), "little")
        calls.append((u.reg_read(UC_X86_REG_ECX) - SCROLL, rd(4), rd(8), rd(0x0C)))
    uc.hook_add(UC_HOOK_CODE, on_code, begin=ENGINE + 0x1000, end=ENGINE + 0x1000)

    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.ARROWFIT_OFF, _bytes(A.asm_arrowfit, A.ARROWFIT_OFF), esp,
         [(UC_X86_REG_ESI, SCROLL), (UC_X86_REG_ECX, 0),
          (UC_X86_REG_EBX, 0x1111), (UC_X86_REG_EDI, 0x2222)])

    if g <= 16:
        # bp(0x18) == 0x18, so the up arrow is already correct -> vanilla exactly:
        # ONE resize, the down arrow's, with vanilla's own arguments
        assert calls == [(0x15F8, want, want, 0)], calls
    else:
        assert calls == [(0xAAC, want, want, 0), (0x15F8, want, want, 0)], calls
    # the caller's Win_move needs ebp pointing at the DOWN arrow either way
    assert uc.reg_read(UC_X86_REG_EBP) == SCROLL + 0x15F8
    assert uc.reg_read(UC_X86_REG_EBX) == 0x1111      # callee-saved, live at the site
    assert uc.reg_read(UC_X86_REG_EDI) == 0x2222
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4     # balanced on both paths


# --------------------------------------------------------------------------
# fe_pair_remap v7 (F0/B9 one-shot family) + the sb-restripe / btn-stripes
# arming chain -- the REAL assembled bytes at their REAL cave VAs, differential
# against scaling_laws.pair_remap_pixel.
# --------------------------------------------------------------------------
PC = 0xA0C000
REAL_SYMS = {
    "g_popup_scale_num": 0x668740,
    "g_fe_dst": PC + 0x2FA0, "g_fe_x": PC + 0x2FA4, "g_fe_y": PC + 0x2FA8,
    "g_fe_w": PC + 0x2FAC, "g_fe_h": PC + 0x2FB0,
    "g_rm_xend": PC + 0x2FB4, "g_rm_yend": PC + 0x2FB8, "g_rm_hn": PC + 0x2FBC,
    "g_rm_col": PC + 0x2FC0, "g_fe_src": PC + 0x2FC4, "g_rm_navy": PC + 0x2FC8,
    "g_rm_povr": PC + 0x2FCC,
    "g_rm_force": PC + 0x44B0, "g_rm_bd": PC + 0x44B4, "g_rm_bdcol": PC + 0x44B8,
    "g_rm_c5": PC + 0x39E0, "g_rm_bf": PC + 0x39E4,
    "g_rm_c5col": PC + 0x39E8, "g_rm_bfcol": PC + 0x39EC,
    "g_rm_f0ovr": PC + 0x10634, "g_rm_f0": PC + 0x10638, "g_rm_f0col": PC + 0x1063C,
    "g_rm_yph": PC + 0x103FC,      # fe v8 row-phase add (btn_stripes v13 plain path)
    "g_netwin_active": PC + 0x4800, "g_sb_cur": PC + 0x10630,
    "t_rw_sbarrows": PC + 0xC980,   # v11: both-console-bar arrow admission helper (stubbed `xor eax,eax / ret` in these tests)
    "g_faction_active": PC + 0x12D0,
    "g_btn_origW": PC + 0x538, "g_btn_origH": PC + 0x53C,
    "thunk_btn_devfill": PC + 0x1660,
    "thunk_fe_pair_remap": PC + 0x10000,
    "thunk_ed_remap": PC + 0x10E00,       # stubbed RET in the machine (editor range not exercised)
    "thunk_sbarrow_bg": PC + 0x11400,     # stubbed RET here (its own law is tested in test_scenedit_asm_parity)
    "g_rail_sb": PC + 0x11260,
    "g_ab_w": PC + 0x114C0, "g_ab_h": PC + 0x114C4,
    "t_face_own": PC + 0x3E640,         # v14 (W9A): the REAL helper (assemble_face_own), written by _mk_remap_machine
}
REMAP_VA = PC + 0x10000
RESTRIPE_VA = PC + 0x105B0
BTNSTRIPES_VA = PC + 0x2FD0
BUF = DATA + 0x2000            # fake Buffer struct (spans +0x4A8)
PIX = DATA + 0x4000            # its pixel data


def _resolve_sentinels(blob, sent_map):
    blob = bytearray(blob)
    i = 0
    while i + 4 <= len(blob):
        ph = sent_map.get(int.from_bytes(blob[i:i + 4], "little"))
        if ph:
            blob[i:i + 4] = REAL_SYMS[ph[7:-1]].to_bytes(4, "little")
            i += 4
        else:
            i += 1
    return bytes(blob)


def _remap_v7_bytes():
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        import assemble_devfill_stripes as D
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    _, off, asm = next(t for t in D.THUNKS if t[0] == "thunk_fe_pair_remap")
    src = "\n".join(l.split(";")[0] for l in asm.splitlines())
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, D.PCAVE2 + off)
    return _resolve_sentinels(bytes(code), D.SENT)


def _sbrestripe_bytes():
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(
        A.asm_sb_restripe(), addr=RESTRIPE_VA)
    return _resolve_sentinels(bytes(code), A.SENT)


def _btnstripes_bytes():
    """thunk_btn_stripes v6 (assemble_popup_sb.py) at its real VA, sentinels resolved."""
    import assemble_popup_sb as P
    blob = bytearray(P.assemble(P.asm_btn_stripes(True), BTNSTRIPES_VA))
    absmap = {k: v[7:-1] for k, v in P.SENT.items()}
    i = 0
    while i + 4 <= len(blob):
        v = int.from_bytes(blob[i:i + 4], "little")
        if v in absmap:
            blob[i:i + 4] = REAL_SYMS[absmap[v]].to_bytes(4, "little"); i += 4
        elif blob[i] == 0xE8 and i + 5 <= len(blob):
            rel = int.from_bytes(blob[i + 1:i + 5], "little", signed=True)
            tgt = (BTNSTRIPES_VA + i + 5 + rel) & 0xFFFFFFFF
            if tgt in P.REL:
                real = REAL_SYMS[P.REL[tgt][7:-1]]
                blob[i + 1:i + 5] = ((real - (BTNSTRIPES_VA + i + 5)) & 0xFFFFFFFF).to_bytes(4, "little")
                i += 5
            else:
                i += 1
        else:
            i += 1
    return bytes(blob)


def _mk_remap_machine(g):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x100000), (ENGINE, 0x300000),
                       (STACK, 0x10000), (DATA, 0x10000), (MARKER & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(REAL_SYMS["g_popup_scale_num"], int(g).to_bytes(4, "little"))
    uc.mem_write(REMAP_VA, _remap_v7_bytes())
    import assemble_face_own as FO
    va, code, _t = FO.build()["t_face_own"]
    assert va == REAL_SYMS["t_face_own"]
    uc.mem_write(va, code)
    return uc


def _mk_buffer(uc, at, pix_at, w, h, pixels, clip=None):
    l, t, r, b = clip or (0, 0, w, h)
    for off, v in ((0x54, pix_at), (0x4A8, w), (0x80, w),
                   (0x84, (-h) & 0xFFFFFFFF),
                   (0x20, l), (0x24, t), (0x28, r), (0x2C, b)):
        uc.mem_write(at + off, int(v).to_bytes(4, "little"))
    uc.mem_write(pix_at, bytes(pixels))


def _g32(uc, name):
    return int.from_bytes(uc.mem_read(REAL_SYMS[name], 4), "little")


def _set32(uc, name, v):
    uc.mem_write(REAL_SYMS[name], int(v).to_bytes(4, "little"))


def _sb_canvas_pixels(w, h):
    """A sb-canvas-like grid: rows 0..15 trough C5/41 1px dither, rows 16..27
    thumb F0/B9, the rest art/blue rows; col 0 = art stroke, last col = key."""
    px = bytearray()
    for y in range(h):
        if y < 16:
            row = bytearray([0xC5 if y % 2 == 0 else 0x41] * w)
        elif y < 28:
            row = bytearray([0xF0 if y % 2 == 0 else 0xB9] * w)
        elif y < 32:
            row = bytearray([0xE0 if y % 2 == 0 else 0xE1] * w)
        else:
            row = bytearray([(0x22, 0xC1, 0x4F, 0x77)[y % 4]] * w)
        row[0] = 0x22
        row[-1] = 0x09
        px += row
    return bytes(px)


def _force_flags(pixels, w, h, x, y, rw, rh):
    """Replicate the v7 force prescan: count C4/C6/C5/BF over the rect's first
    min(8, rh) rows; each family keys on count > rw/2."""
    counts = {}
    for yy in range(max(y, 0), max(y, 0) + min(rh, 8)):
        for xx in range(max(x, 0), max(x, 0) + rw):
            v = pixels[yy * w + xx]
            counts[v] = counts.get(v, 0) + 1
    thr = rw // 2
    return dict(navy=counts.get(0xC4, 0) > thr, bd=counts.get(0xC6, 0) > thr,
                c5=counts.get(0xC5, 0) > thr, bf=counts.get(0xBF, 0) > thr)


def _expect(pixels, w, h, g, flags, f0, clip=None):
    l, t, r, b = clip or (0, 0, w, h)
    out = bytearray(pixels)
    for y in range(max(0, t), min(h, b)):
        for x in range(max(0, l), min(w, r)):
            out[y * w + x] = SL.pair_remap_pixel(
                pixels[y * w + x], y, g, f0=f0, **flags)
    return bytes(out)


def _run_remap(uc, entry=REMAP_VA):
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.emu_start(entry, MARKER, count=2_000_000)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4


@pytest.mark.parametrize("g", [22, 25, 40])
def test_remap_v7_force_path_stripes_trough_and_oneshot_thumb(g):
    """The sb_restripe scenario: force + f0ovr over the whole canvas."""
    w, h = 24, 40
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(g)
    _mk_buffer(uc, BUF, PIX, w, h, pixels)
    _set32(uc, "g_fe_dst", BUF)
    for nm in ("g_fe_x", "g_fe_y", "g_fe_src"):
        _set32(uc, nm, 0)
    _set32(uc, "g_fe_w", w)
    _set32(uc, "g_fe_h", h)
    _set32(uc, "g_rm_force", 1)
    _set32(uc, "g_rm_f0ovr", 1)
    _run_remap(uc)
    flags = _force_flags(pixels, w, h, 0, 0, w, h)
    assert flags["c5"] and not flags["navy"]
    got = bytes(uc.mem_read(PIX, w * h))
    assert got == _expect(pixels, w, h, g, flags, f0=True)
    # one-shots consumed; a SECOND run (fresh force, ovr left 0) must leave
    # the now-lawful F0/B9 stripes exactly as they are
    assert _g32(uc, "g_rm_f0ovr") == 0 and _g32(uc, "g_rm_force") == 0
    _set32(uc, "g_rm_force", 1)
    _run_remap(uc)
    got2 = bytes(uc.mem_read(PIX, w * h))
    assert got2 == _expect(got, w, h, g, _force_flags(got, w, h, 0, 0, w, h),
                           f0=False)
    assert got2[16 * w + 1] == got[16 * w + 1]          # thumb rows untouched


def test_remap_v7_without_the_oneshot_leaves_the_face_pair_alone():
    g, w, h = 25, 24, 40
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(g)
    _mk_buffer(uc, BUF, PIX, w, h, pixels)
    _set32(uc, "g_fe_dst", BUF)
    for nm in ("g_fe_x", "g_fe_y", "g_fe_src", "g_rm_f0ovr"):
        _set32(uc, nm, 0)
    _set32(uc, "g_fe_w", w)
    _set32(uc, "g_fe_h", h)
    _set32(uc, "g_rm_force", 1)
    _run_remap(uc)
    flags = _force_flags(pixels, w, h, 0, 0, w, h)
    got = bytes(uc.mem_read(PIX, w * h))
    assert got == _expect(pixels, w, h, g, flags, f0=False)
    for y in range(16, 28):                              # F0/B9 rows untouched
        assert got[y * w + 2] == pixels[y * w + 2]


def test_remap_v7_enlarge_path_honours_the_oneshot_but_not_force_pairs():
    """The btn_stripes arrow scenario: NON-force call (src=0), f0ovr set —
    F0/B9 and the unconditional pairs stripe, C5/41 must NOT (no prescan)."""
    g, w, h = 25, 24, 40
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(g)
    _mk_buffer(uc, BUF, PIX, w, h, pixels)
    _set32(uc, "g_fe_dst", BUF)
    for nm in ("g_fe_x", "g_fe_y", "g_fe_src", "g_rm_force"):
        _set32(uc, nm, 0)
    _set32(uc, "g_fe_w", w)
    _set32(uc, "g_fe_h", h)
    _set32(uc, "g_rm_f0ovr", 1)
    _run_remap(uc)
    got = bytes(uc.mem_read(PIX, w * h))
    noflags = dict(navy=False, bd=False, c5=False, bf=False)
    assert got == _expect(pixels, w, h, g, noflags, f0=True)
    assert got[0 * w + 2] == 0xC5 and got[1 * w + 2] == 0x41   # trough alone


@pytest.mark.parametrize("g", [18, 22, 25, 40, 48])
@pytest.mark.parametrize("top", [0, 1, 2, 3, 5, 37, 361])
def test_remap_v8_button_face_takes_the_parent_grid(g, top):
    """fe_pair_remap v8: with g_rm_yph = the button's parent-local top (btn_stripes v13 plain path) a face
    row y carries the stripe of PARENT row top + y (law btn_face_stripe_phase); the raw top is staged, the
    asm's `div P` reduces it.  0 is the v7 behaviour."""
    w, h = 20, 30
    face = bytearray()
    for y in range(h):
        row = bytearray([(0xAE, 0xEE)[y % 2] if y < 18 else (0xE0, 0xE1)[y % 2]] * w)
        row[0] = 0x22                                       # bevel stroke: passes through
        face += row
    uc = _mk_remap_machine(g)
    _mk_buffer(uc, BUF, PIX, w, h, bytes(face))
    _set32(uc, "g_fe_dst", BUF)
    for nm in ("g_fe_x", "g_fe_y", "g_fe_src", "g_rm_force", "g_rm_f0ovr"):
        _set32(uc, nm, 0)
    _set32(uc, "g_fe_w", w)
    _set32(uc, "g_fe_h", h)
    _set32(uc, "g_rm_yph", top)
    _run_remap(uc)
    got = bytes(uc.mem_read(PIX, w * h))
    ph = SL.btn_face_stripe_phase(top, 0, g)
    want = bytes(SL.pair_remap_pixel(face[y * w + x], y + ph, g) for y in range(h) for x in range(w))
    assert got == want
    assert _g32(uc, "g_rm_yph") == top                      # a plain cell: btn_stripes clears it, not fe
    for y in range(h):                                      # the face row sits on the parent row's stripe
        assert (got[y * w + 5] in (0xAE, 0xE0)) == SL.stripe_top(top + y, g)


def test_remap_v7_below_native_writes_nothing_and_keeps_the_oneshot():
    w, h = 24, 40
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(16)
    _mk_buffer(uc, BUF, PIX, w, h, pixels)
    _set32(uc, "g_fe_dst", BUF)
    _set32(uc, "g_fe_w", w)
    _set32(uc, "g_fe_h", h)
    _set32(uc, "g_rm_force", 1)
    _set32(uc, "g_rm_f0ovr", 1)
    _run_remap(uc)
    assert bytes(uc.mem_read(PIX, w * h)) == pixels
    assert _g32(uc, "g_rm_f0ovr") == 1                   # NOT consumed at g<=16


def test_remap_v7_respects_the_dest_clip():
    g, w, h = 40, 24, 40
    clip = (2, 4, w - 4, h - 6)
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(g)
    _mk_buffer(uc, BUF, PIX, w, h, pixels, clip=clip)
    _set32(uc, "g_fe_dst", BUF)
    for nm in ("g_fe_x", "g_fe_y", "g_fe_src"):
        _set32(uc, nm, 0)
    _set32(uc, "g_fe_w", w)
    _set32(uc, "g_fe_h", h)
    _set32(uc, "g_rm_force", 1)
    _set32(uc, "g_rm_f0ovr", 1)
    _run_remap(uc)
    flags = _force_flags(pixels, w, h, 0, 0, w, h)
    got = bytes(uc.mem_read(PIX, w * h))
    assert got == _expect(pixels, w, h, g, flags, f0=True, clip=clip)
    l, t, r, b = clip
    for y in range(h):                                   # outside stays put
        for x in (0, 1, w - 4, w - 1):
            if not (l <= x < r and t <= y < b):
                assert got[y * w + x] == pixels[y * w + x], (x, y)


def test_sb_restripe_closes_the_bracket_and_restripes_the_canvas():
    g, w, h = 25, 37, 100
    sbw = DATA + 0x8000
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(g)
    uc.mem_write(RESTRIPE_VA, _sbrestripe_bytes())
    _mk_buffer(uc, sbw + 0x444, DATA + 0xC000, w, h, pixels)
    _set32(uc, "g_sb_cur", sbw)
    _set32(uc, "g_netwin_active", 1)
    for nm in ("g_fe_src", "g_rm_force", "g_rm_f0ovr"):
        _set32(uc, nm, 0)
    _run_remap(uc, entry=RESTRIPE_VA)
    assert _g32(uc, "g_netwin_active") == 0              # bracket closed
    assert _g32(uc, "g_sb_cur") == 0                     # stash consumed
    assert _g32(uc, "g_rm_force") == 0 and _g32(uc, "g_rm_f0ovr") == 0
    assert _g32(uc, "g_fe_dst") == sbw + 0x444
    assert _g32(uc, "g_fe_w") == w and _g32(uc, "g_fe_h") == h
    flags = _force_flags(pixels, w, h, 0, 0, w, h)
    got = bytes(uc.mem_read(DATA + 0xC000, w * h))
    assert got == _expect(pixels, w, h, g, flags, f0=True)


def test_sb_restripe_at_native_only_closes_the_bracket():
    w, h = 37, 100
    sbw = DATA + 0x8000
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(16)
    uc.mem_write(RESTRIPE_VA, _sbrestripe_bytes())
    _mk_buffer(uc, sbw + 0x444, DATA + 0xC000, w, h, pixels)
    _set32(uc, "g_sb_cur", sbw)
    _set32(uc, "g_netwin_active", 1)
    _set32(uc, "g_rm_f0ovr", 0)
    _run_remap(uc, entry=RESTRIPE_VA)
    assert _g32(uc, "g_netwin_active") == 0
    assert _g32(uc, "g_rm_f0ovr") == 0                   # never armed at g<=16
    assert bytes(uc.mem_read(DATA + 0xC000, w * h)) == pixels


@pytest.mark.parametrize("g", (16, 25))
@pytest.mark.parametrize("n0,n1", ((2, 1), (1, 0), (0, 0), (3, 2)),
                         ids=("nested-holder-kept", "own-bracket-closed", "clamped-at-zero", "double-nest"))
def test_sb_restripe_bracket_close_is_a_clamped_decrement(g, n0, n1):
    """fix 7: g_netwin_active is a COUNT (sbzoom v11 incs it); the restripe head decrements it, clamped at 0.
    A holder already inside its own bracket (Datalinks 1, the tech-breakthrough modal 1) keeps its flag across an
    armed bar draw (2 -> 1); a stray close never goes negative (a negative count reads armed forever)."""
    w, h = 37, 100
    sbw = DATA + 0x8000
    pixels = _sb_canvas_pixels(w, h)
    uc = _mk_remap_machine(g)
    uc.mem_write(RESTRIPE_VA, _sbrestripe_bytes())
    _mk_buffer(uc, sbw + 0x444, DATA + 0xC000, w, h, pixels)
    _set32(uc, "g_sb_cur", sbw)
    _set32(uc, "g_netwin_active", n0)
    for nm in ("g_fe_src", "g_rm_force", "g_rm_f0ovr"):
        _set32(uc, nm, 0)
    _run_remap(uc, entry=RESTRIPE_VA)
    assert _g32(uc, "g_netwin_active") == n1


# the absolute-store g_netwin_active brackets left as they are in fix 7 (the investigator's survey: nesting-safe in
# practice -- techhover saves/restores; the others are paired and synchronous); converting them is a separate change
NETWIN_ABS_WRITERS = {"thunk_netwin_bracket", "t_dl_build_enter", "t_dl_build_leave", "t_dl_exec_enter",
                      "t_dl_exec_leave", "t_rw_techpage", "t_rw_techhover", "t_ntw_build", "t_ntw_modal"}
# the counted (inc / dec / add / sub) writers: the sbzoom -> sb_restripe pair and t_dw_ts3's TextScroll_attach bracket
NETWIN_COUNTED_WRITERS = {"thunk_pref_sbzoom", "thunk_sb_restripe", "t_dw_ts3"}

_NETWIN_CELL = r"(?:\{abs32:g_netwin_active\}|00 08 A1 00)"    # symbol token or the raw VA 0xA10800
# absolute stores to [abs32]: mov dword imm32 (C7 05), mov from eax (A3), mov from any reg (89 /r, mod 00 rm 101),
# mov byte imm8 (C6 05)
NETWIN_ABS_STORE = (r"(?:C7 05 " + _NETWIN_CELL + r" \S\S \S\S \S\S \S\S|A3 " + _NETWIN_CELL
                    + r"|89 (?:05|0D|15|1D|25|2D|35|3D) " + _NETWIN_CELL + r"|C6 05 " + _NETWIN_CELL + r" \S\S)")
# counted read-modify-writes: inc / dec (FF 05 / FF 0D), add / sub imm8 (83 05 / 83 2D)
NETWIN_COUNTED_STORE = r"(?:FF (?:05|0D) " + _NETWIN_CELL + r"|83 (?:05|2D) " + _NETWIN_CELL + r" \S\S)"


def _netwin_census(ents):
    import re
    absw, cntw = re.compile(NETWIN_ABS_STORE), re.compile(NETWIN_COUNTED_STORE)
    return ({n for n, b in ents.items() if absw.search(b)}, {n for n, b in ents.items() if cntw.search(b)})


def test_netwin_bracket_writers_census():
    """The yaml writers of g_netwin_active: sbzoom / sb_restripe are the counted pair (FF 05 inc / clamped FF 0D dec)
    and carry no absolute store; the remaining absolute-store brackets are pinned so a new one is a decision.  The
    census is a byte-template regex over the disp32-absolute store forms (C7 05 / A3 / 89 /r mod-00-rm-101 / C6 05
    absolute; FF 05 / FF 0D / 83 05 / 83 2D counted) -- more than the two the brackets use today, NOT every x86
    store: a register-indirect or SIB address, a 16-bit (66-prefixed) store, xchg / string / other RMW opcodes
    (or / and / xor / add r/m32,r32) are not seen.  test_netwin_census_sees_every_store_form pins what is."""
    import apply_patches as ap
    _s, _g, caves, _sym = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    ents = {e["id"]: " ".join(str(e.get("bytes", "")).split()) for c in caves for e in c["contents"]}
    writers, counted = _netwin_census(ents)
    assert "thunk_pref_sbzoom" not in writers and "thunk_sb_restripe" not in writers
    assert ents["thunk_pref_sbzoom"].count("FF 05 {abs32:g_netwin_active}") == 1
    assert ents["thunk_sb_restripe"].startswith(
        "83 3D {abs32:g_netwin_active} 00 7E 06 FF 0D {abs32:g_netwin_active} ")
    assert writers == NETWIN_ABS_WRITERS, writers ^ NETWIN_ABS_WRITERS
    assert counted == NETWIN_COUNTED_WRITERS, counted ^ NETWIN_COUNTED_WRITERS


@pytest.mark.parametrize("form", ["89 05 {c}", "89 1D {c}", "89 3D {c}", "C6 05 {c} 01", "FF 05 {c}", "FF 0D {c}",
                                  "83 05 {c} 01", "83 2D {c} 01", "89 0D 00 08 A1 00", "C7 05 {c} 01 00 00 00",
                                  "A3 {c}"])
def test_netwin_census_sees_every_store_form(form):
    """A new writer in any of the store forms is caught (the census regex is not limited to C7 05 / A3); a read
    (cmp 83 3D / mov eax,[] A1 / mov r,[] 8B 0D) is not a writer."""
    probe = {"probe": "90 " + form.format(c="{abs32:g_netwin_active}") + " C3"}
    writers, counted = _netwin_census(probe)
    assert writers | counted == {"probe"}, form
    for read in ("83 3D {abs32:g_netwin_active} 00", "A1 {abs32:g_netwin_active}", "8B 0D {abs32:g_netwin_active}"):
        assert _netwin_census({"r": read}) == (set(), set()), read


ARROW_UP, ARROW_DN = 0x6AFC10, 0x6B075C


POPUP_SB = 0x7A0000 + 0x3230          # a heap-like Popup (mapped in ENGINE) + embedded ScrollBar


@pytest.mark.parametrize("esi,rail_sb,expect_stripe", [
    (ARROW_UP, 0, True), (ARROW_DN, 0, True), (0x700000, 0, False),
    (POPUP_SB + 0xAAC, POPUP_SB, True), (POPUP_SB + 0x15F8, POPUP_SB, True),
    (POPUP_SB + 0xAAC, 0, False), (POPUP_SB + 0x15F8, 0, False),
    (0x700000, POPUP_SB, False), (POPUP_SB, POPUP_SB, False),
    (0x74652C, 0, True), (0x747078, 0, True), (0x74652C + 4, 0, False)],
    ids=["up", "dn", "other", "pop-up", "pop-dn", "pop-up-unarmed", "pop-dn-unarmed",
         "other-armed", "sb-itself", "dw-chat-up", "dw-chat-dn", "dw-chat-near"])
def test_btn_stripes_arms_the_oneshot_for_picker_and_fitted_popup_arrows(esi, rail_sb, expect_stripe):
    g, w, h = 25, 24, 24
    pixels = _sb_canvas_pixels(w, h)[:w * h]
    uc = _mk_remap_machine(g)
    uc.mem_write(BTNSTRIPES_VA, _btnstripes_bytes())
    uc.mem_write(REAL_SYMS["thunk_btn_devfill"], b"\xC3")
    uc.mem_write(REAL_SYMS["thunk_ed_remap"], b"\xC3")
    uc.mem_write(REAL_SYMS["thunk_sbarrow_bg"], b"\xC3")
    uc.mem_write(REAL_SYMS["t_rw_sbarrows"], b"\x31\xC0\xC3")
    _set32(uc, "g_rail_sb", rail_sb)
    _mk_buffer(uc, esi + 0x444, DATA + 0xC000, w, h, pixels)
    _set32(uc, "g_btn_origW", w)
    _set32(uc, "g_btn_origH", (-h) & 0xFFFFFFFF)         # stored NEGATIVE
    for nm in ("g_faction_active", "g_rm_f0ovr", "g_rm_force"):
        _set32(uc, nm, 0)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.emu_start(BTNSTRIPES_VA, MARKER, count=2_000_000)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4
    assert _g32(uc, "g_rm_f0ovr") == 0                   # consumed either way
    noflags = dict(navy=False, bd=False, c5=False, bf=False)
    got = bytes(uc.mem_read(DATA + 0xC000, w * h))
    assert got == _expect(pixels, w, h, g, noflags, f0=expect_stripe)


def test_btn_stripes_v4_basewin_range_still_early_outs():
    g, w, h = 25, 24, 24
    pixels = _sb_canvas_pixels(w, h)[:w * h]
    uc = _mk_remap_machine(g)
    uc.mem_write(BTNSTRIPES_VA, _btnstripes_bytes())
    uc.mem_write(REAL_SYMS["thunk_btn_devfill"], b"\xC3")
    uc.mem_write(REAL_SYMS["thunk_ed_remap"], b"\xC3")
    uc.mem_write(REAL_SYMS["thunk_sbarrow_bg"], b"\xC3")
    uc.mem_write(REAL_SYMS["t_rw_sbarrows"], b"\x31\xC0\xC3")
    _set32(uc, "g_rail_sb", 0)
    esi = 0x6B5000                                       # inside [LO, HI)
    _mk_buffer(uc, esi + 0x444, DATA + 0xC000, w, h, pixels)
    _set32(uc, "g_fe_dst", 0x12345678)
    _set32(uc, "g_rm_f0ovr", 0)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.emu_start(BTNSTRIPES_VA, MARKER, count=1000)
    assert bytes(uc.mem_read(DATA + 0xC000, w * h)) == pixels
    assert _g32(uc, "g_fe_dst") == 0x12345678            # untouched
    assert _g32(uc, "g_rm_f0ovr") == 0


@pytest.mark.parametrize("bordered", [False, True])
def test_arrowfit_is_a_no_op_when_the_arrows_already_match(bordered):
    """Every OTHER scrollbar in the game: b never changed, so the up-arrow
    resize must not be emitted at all and the function stays vanilla."""
    b = 40
    want = SL.scrollbar_arrow_square(b, bordered)
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((CODE, 0x100000), (ENGINE, 0x300000),
                       (STACK, 0x10000), (DATA, 0x4000), (MARKER & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    uc.mem_write(ENGINE + 0x1000, b"\xC2\x0C\x00")
    uc.mem_write(VTABLE + 0x0C, (ENGINE + 0x1000).to_bytes(4, "little"))
    _mk_scroll(uc, b, bordered, want)                  # already in sync
    calls = []
    uc.hook_add(UC_HOOK_CODE,
                lambda u, a, s, _: calls.append(u.reg_read(UC_X86_REG_ECX) - SCROLL),
                begin=ENGINE + 0x1000, end=ENGINE + 0x1000)
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.ARROWFIT_OFF, _bytes(A.asm_arrowfit, A.ARROWFIT_OFF), esp,
         [(UC_X86_REG_ESI, SCROLL), (UC_X86_REG_ECX, 0)])
    assert calls == [0x15F8], calls                    # down arrow only == vanilla


# --------------------------------------------------------------------------
# thunk_rail_sbarrows -- thunk_btn_gate's NO exit (v4, 2026-09-26p)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stash", [0, SB_OBJ])
@pytest.mark.parametrize("off", [0xAAC, 0x15F8, 0xAAC - 1, 0x15F8 + 1, 0, 0x214C])
def test_rail_sbarrows_admits_exactly_the_stashed_bars_arrows(stash, off):
    """eax = 1 iff esi is [g_rail_sb]+0xAAC / +0x15F8 (the rail-fitted bar's up/down
    FlatButtons); anything else -- including every esi while the stash is 0 -- is
    btn_gate's old NO (eax = 0).  Only eax + flags change."""
    uc = _mk(40)
    uc.mem_write(G_RAIL_SB_ADDR, stash.to_bytes(4, "little"))
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    esi = SB_OBJ + off
    _run(uc, A.PCAVE2 + A.RAIL_SBARROWS_OFF, _bytes(A.asm_rail_sbarrows, A.RAIL_SBARROWS_OFF), esp,
         [(UC_X86_REG_ESI, esi), (UC_X86_REG_EAX, 0xDEAD), (UC_X86_REG_ECX, 0x11), (UC_X86_REG_EDX, 0x22)])
    want = 1 if (stash and off in (0xAAC, 0x15F8)) else 0
    assert uc.reg_read(UC_X86_REG_EAX) == want
    assert uc.reg_read(UC_X86_REG_ESI) == esi
    assert uc.reg_read(UC_X86_REG_ECX) == 0x11 and uc.reg_read(UC_X86_REG_EDX) == 0x22
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4


# --------------------------------------------------------------------------
# rail_slide_out tail end state (v4, 2026-09-26r) -- law rail_out_tail
# --------------------------------------------------------------------------
@pytest.mark.parametrize("win,gated", [(WIN_OBJ, True), (POPUP_OBJ, True), (FILEDLG_OBJ, True), (OTHER_OBJ, False)],
                         ids=["picker", "popup", "filedlg", "other"])
@pytest.mark.parametrize("g", [16, 22, 25, 40])
@pytest.mark.parametrize("pref,mp", [(0x80000, 0), (0, 0), (0x80000, 1)], ids=["anim", "prefoff", "mp"])
def test_railout_hstep_applies_the_rollup_shift_only_when_vanilla_animates(win, gated, g, pref, mp):
    uc = _mk(g, win=win)
    uc.mem_write(G_RAIL_SB_ADDR, SB_OBJ.to_bytes(4, "little"))
    cw = SL.scale_px(520, g) + 3                     # v5 (fix rail2): the shift is rail_wall_off of the canvas width
    uc.mem_write(win + A.F_WINW, cw.to_bytes(4, "little"))
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    L = 1234
    _run(uc, A.PCAVE2 + A.RAILOUT_HSTEP_OFF, _bytes(A.asm_railout_hstep, A.RAILOUT_HSTEP_OFF), esp,
         [(UC_X86_REG_ECX, -1 if mp else 0), (UC_X86_REG_EAX, 0x1234), (UC_X86_REG_EDI, win),
          (UC_X86_REG_EDX, mp), (UC_X86_REG_EBX, pref), (UC_X86_REG_ESI, L)], count=20000)
    hit = g > 16 and gated
    want_shift = SL.rail_out_tail(g, bool(pref) and not mp, cw)[1] if hit else 0
    assert uc.reg_read(UC_X86_REG_ESI) == (L + want_shift) & 0xFFFFFFFF
    assert uc.reg_read(UC_X86_REG_ECX) == (0 if hit else (4 if mp else 8))
    assert uc.reg_read(UC_X86_REG_EAX) == 0x1234
    assert uc.reg_read(UC_X86_REG_EBX) == pref and uc.reg_read(UC_X86_REG_EDX) == mp
    assert int.from_bytes(uc.mem_read(G_RAIL_SB_ADDR, 4), "little") == (0 if hit else SB_OBJ)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4


@pytest.mark.parametrize("win,gated", [(WIN_OBJ, True), (POPUP_OBJ, True), (FILEDLG_OBJ, True), (OTHER_OBJ, False)],
                         ids=["picker", "popup", "filedlg", "other"])
@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_railout_capw_covers_the_scaled_strip(win, gated, g):
    """edx = capture width - 0x20: the caller forms L = R - edx - 0x20.  v2 (fix sbstrip): the capture starts where
    the strip was baked (rail_strip_x, the outer right rail's x) and runs to the window's right edge R."""
    uc = _mk(g, win=win)
    uc.mem_write(A.STRIP_WALL_SPRITE_W, (15).to_bytes(4, "little"))
    cw, left = 758 * g // 16, 731                    # canvas width; the window's screen left (R = left + cw)
    uc.mem_write(win + A.F_WINW, cw.to_bytes(4, "little"))
    esp = STACK + 0x4000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.RAILOUT_CAPW_OFF, _bytes(A.asm_railout_capw, A.RAILOUT_CAPW_OFF), esp,
         [(UC_X86_REG_ECX, left + cw), (UC_X86_REG_EAX, 0x1234), (UC_X86_REG_EDI, win)])
    capw = SL.rail_out_tail(g, True, cw)[0] if (gated and g > 16) else 47
    assert uc.reg_read(UC_X86_REG_EDX) + 0x20 == capw
    if gated:
        assert (left + cw) - capw == left + SL.rail_layout(cw, 490 * g // 16, g)["bake_x"]   # L == the bake x
    assert uc.reg_read(UC_X86_REG_ECX) == left + cw and uc.reg_read(UC_X86_REG_EAX) == 0x1234
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4
