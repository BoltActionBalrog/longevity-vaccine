"""Differential: the type-8 OptionList sprite-ratio thunks + tutwin_backdrop v2
must agree with scaling_laws bit-exactly, and be register-identical at g<=16.

thunk_ol8_calc_ratio  (cut 0x610AE1): ecx=num(*g), edi=den(*16), eax=sprW*ecx.
thunk_ol8_draw_ratio  (cut 0x610DF1): ebp=num(*g), ecx=den(*16), eax=sprH*ebp.
thunk_ol8_box_ratio   (cut 0x610FC7): eax = sprW*num(*g) // den(*16); edi/ebx kept.
thunk_ol8_gap         (cut 0x610C84): edx = fl(gap*g/16); ebx = rowW+edx; eax kept.
thunk_ol8_textx       (cut 0x610D98): ecx = edx+ebx+fl(4g/16); ends `test esi,esi`
                                      (flags must reflect esi across the RET).
thunk_tutwin_backdrop v2 (0x405f77 site): ornate arm (params==0x6846B0, g>16) for
ANY dest — devfill then hollow with the original args, ecx restored for hollow;
the synthetic title stash ONLY for ecx==TutWin+0x444; everything else tail-jmps
devfill with the caller's stack untouched.

Emulated with the REAL assembled bytes (sentinel imm32 page at 0xDEADB000; the
yaml resolves the placeholders at apply time).  Skips if keystone/unicorn absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_HOOK_CODE, UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import assemble_optlist8 as AO  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = AO.PCAVE2
CALC_VA = PCAVE2 + AO.CALC_RATIO_OFF
DRAW_VA = PCAVE2 + AO.DRAW_RATIO_OFF
BOX_VA = PCAVE2 + AO.BOX_RATIO_OFF
GAP_VA = PCAVE2 + AO.GAP_OFF
TEXTX_VA = PCAVE2 + AO.TEXTX_OFF
ROWW_VA = PCAVE2 + AO.ROWWIDTH_OFF
SELB_VA = PCAVE2 + AO.SELBOTTOM_OFF
CHILDX_VA = PCAVE2 + AO.CHILDX_OFF
TW_VA = PCAVE2 + AO.TUTWIN_OFF

CODE = {
    CALC_VA: AO.raw(AO.CALC_RATIO_OFF, AO.asm_calc_ratio()),
    DRAW_VA: AO.raw(AO.DRAW_RATIO_OFF, AO.asm_draw_ratio()),
    BOX_VA: AO.raw(AO.BOX_RATIO_OFF, AO.asm_box_ratio()),
    GAP_VA: AO.raw(AO.GAP_OFF, AO.asm_gap()),
    TEXTX_VA: AO.raw(AO.TEXTX_OFF, AO.asm_textx()),
    ROWW_VA: AO.raw(AO.ROWWIDTH_OFF, AO.asm_rowwidth()),
    SELB_VA: AO.raw(AO.SELBOTTOM_OFF, AO.asm_selbottom()),
    CHILDX_VA: AO.raw(AO.CHILDX_OFF, AO.asm_childx()),
    TW_VA: AO.raw(AO.TUTWIN_OFF, AO.asm_tutwin_v3()),
    PCAVE2 + AO.KEYINT_OFF: AO.raw(AO.KEYINT_OFF, AO.asm_hollow_keyint()),
}

G_ADDR = AO.G                       # 0xDEADBE00 sentinel
TW_DEST = AO.TW_DEST
TITLE_L = AO.TITLE_L
TITLE_R = AO.TITLE_R
DEVFILL = AO.DEVFILL
HOLLOW = AO.HOLLOW
KEYINT = AO.KEYINT
TUTWIN_BUF = AO.TUTWIN_BUF
TUTWIN_W = AO.TUTWIN_W
ORNATE = AO.ORNATE

STACK = 0x00200000
ELEM = 0x00300000                  # esi = the OptionList element
SPRITE = 0x00310000                # sprite object (dims at +0x18/+0x1c)
IFACE = 0x00320000                 # ecx in draw_item's gap block (Dialog-adjusted)
SITE_RET = 0x00610AF0              # any mapped stop address in the code page
ZF = 1 << 6


def _w32(uc, addr, v):
    uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(uc, addr):
    return int.from_bytes(uc.mem_read(addr, 4), "little")


def _mk_uc(g):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for page in (PCAVE2 + 0xF000, PCAVE2 + 0xA000, PCAVE2 + 0x4000, 0xDEADB000, 0x00610000,
                 ELEM, SPRITE, IFACE, 0x8C7000):
        uc.mem_map(page, 0x1000)
    uc.mem_map(STACK, 0x10000)
    for va, code in CODE.items():
        uc.mem_write(va, code)
    _w32(uc, G_ADDR, g)
    return uc


def _run(uc, entry, esp0):
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0, SITE_RET)
    uc.emu_start(entry, SITE_RET, count=10000)
    assert uc.reg_read(UC_X86_REG_EIP) == SITE_RET
    return uc


# ---------------------------------------------------------------------------
# the three ratio thunks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("num,den", [(1, 1), (3, 4)])
def test_calc_ratio(g, num, den):
    uc = _mk_uc(g)
    _w32(uc, ELEM + 0x1C, num)
    _w32(uc, ELEM + 0x20, den)
    _w32(uc, SPRITE + 0x18, 37)
    uc.reg_write(UC_X86_REG_ESI, ELEM)
    uc.reg_write(UC_X86_REG_EBX, SPRITE)
    _run(uc, CALC_VA, STACK + 0x8000)
    n2, d2 = SL.optionlist8_sprite_ratio(num, den, g)
    assert uc.reg_read(UC_X86_REG_ECX) == n2, "num register (H div reuses it)"
    assert uc.reg_read(UC_X86_REG_EDI) == d2, "den register (H div reuses it)"
    assert uc.reg_read(UC_X86_REG_EAX) == 37 * n2, "sprW*num product"
    assert uc.reg_read(UC_X86_REG_ESP) == STACK + 0x8004, "bare RET"
    # the resume-site idiv then floors the quotient:
    assert (37 * n2) // d2 == (37 * num * g) // (den * 16) if g > 16 else True


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_draw_ratio(g):
    uc = _mk_uc(g)
    _w32(uc, ELEM + 0x1C, 1)
    _w32(uc, ELEM + 0x20, 1)
    _w32(uc, SPRITE + 0x1C, 37)
    uc.reg_write(UC_X86_REG_ESI, ELEM)
    uc.reg_write(UC_X86_REG_EAX, SPRITE)
    _run(uc, DRAW_VA, STACK + 0x8000)
    n2, d2 = SL.optionlist8_sprite_ratio(1, 1, g)
    assert uc.reg_read(UC_X86_REG_EBP) == n2
    assert uc.reg_read(UC_X86_REG_ECX) == d2
    assert uc.reg_read(UC_X86_REG_EAX) == 37 * n2


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("sprw", [1, 37, 80])
def test_box_ratio(g, sprw):
    uc = _mk_uc(g)
    _w32(uc, ELEM + 0x1C, 1)
    _w32(uc, ELEM + 0x20, 1)
    _w32(uc, SPRITE + 0x18, sprw)
    uc.reg_write(UC_X86_REG_ESI, ELEM)
    uc.reg_write(UC_X86_REG_ECX, SPRITE)
    uc.reg_write(UC_X86_REG_EDI, 0x55555555)
    uc.reg_write(UC_X86_REG_EBX, 0x11111111)
    _run(uc, BOX_VA, STACK + 0x8000)
    n2, d2 = SL.optionlist8_sprite_ratio(1, 1, g)
    assert uc.reg_read(UC_X86_REG_EAX) == (sprw * n2) // d2, "selection box W"
    assert uc.reg_read(UC_X86_REG_EDI) == 0x55555555, "edi (row y) live — kept"
    assert uc.reg_read(UC_X86_REG_EBX) == 0x11111111, "ebx (row x) live — kept"
    assert uc.reg_read(UC_X86_REG_ESP) == STACK + 0x8004


# ---------------------------------------------------------------------------
# gap/stride + label x
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_gap_stride(g):
    uc = _mk_uc(g)
    _w32(uc, IFACE + 0x44, 3)          # native row gap
    _w32(uc, IFACE + 0x64, 500)        # rowW (already scaled upstream)
    uc.reg_write(UC_X86_REG_ECX, IFACE)
    uc.reg_write(UC_X86_REG_EAX, 0x77777777)   # col index — must survive
    _run(uc, GAP_VA, STACK + 0x8000)
    gap_s = SL.optionlist8_row_origin_gap(3, g)
    assert uc.reg_read(UC_X86_REG_EDX) == gap_s, "gap (site sar edx,1 follows)"
    assert uc.reg_read(UC_X86_REG_EBX) == 500 + gap_s, "column stride"
    assert uc.reg_read(UC_X86_REG_EAX) == 0x77777777, "eax (col idx) live — kept"


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("esi", [0, ELEM])
def test_textx_and_flag_contract(g, esi):
    uc = _mk_uc(g)
    uc.reg_write(UC_X86_REG_EDX, 92)         # [esi+0x54] maxSprW (scaled)
    uc.reg_write(UC_X86_REG_EBX, 700)        # row x
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.reg_write(UC_X86_REG_EAX, 0x66666666)  # live vtbl base — must survive
    _run(uc, TEXTX_VA, STACK + 0x8000)
    assert uc.reg_read(UC_X86_REG_ECX) == SL.optionlist8_text_x(700, 92, g)
    assert uc.reg_read(UC_X86_REG_EAX) == 0x66666666
    zf = bool(uc.reg_read(UC_X86_REG_EFLAGS) & ZF)
    assert zf == (esi == 0), "the jne @0x610DA2 consumes `test esi,esi` flags"


# ---------------------------------------------------------------------------
# thunk_ol8_rowwidth — the row width [+0x64] grows with the label pad (2026-10-11)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("g", list(range(12, 41)) + [45, 48, 64])
@pytest.mark.parametrize("max_text,margin,sprw", [(0, 0, 0), (180, 3, 37), (412, 3, 92), (300, 5, 57)])
def test_rowwidth_matches_the_law(g, max_text, margin, sprw):
    """cut @0x610B82 (add edx,ebx; mov [eax+0x64],edx): edx = maxText + 2*[+0x40] on entry, ebx = sprite
    column; [+0x64] == optionlist8_row_width at every g (identity at g <= 19); ebx/esi/edi/ebp kept."""
    uc = _mk_uc(g)
    _w32(uc, IFACE + 0x64, 0xCCCCCCCC)
    uc.reg_write(UC_X86_REG_EAX, IFACE)
    uc.reg_write(UC_X86_REG_EDX, max_text + 2 * margin)
    uc.reg_write(UC_X86_REG_EBX, sprw)
    uc.reg_write(UC_X86_REG_ESI, ELEM)
    uc.reg_write(UC_X86_REG_EDI, 0x55555555)
    uc.reg_write(UC_X86_REG_EBP, 0x44444444)
    _run(uc, ROWW_VA, STACK + 0x8000)
    want = SL.optionlist8_row_width(max_text, margin, sprw, g)
    assert _r32(uc, IFACE + 0x64) == want
    assert uc.reg_read(UC_X86_REG_EDX) == want, "edx = the stored value, as the displaced pair left it"
    if g <= 16:
        assert want == max_text + 2 * margin + sprw, "native: the engine's own sum"
    for reg, v in ((UC_X86_REG_EAX, IFACE), (UC_X86_REG_EBX, sprw), (UC_X86_REG_ESI, ELEM),
                   (UC_X86_REG_EDI, 0x55555555), (UC_X86_REG_EBP, 0x44444444)):
        assert uc.reg_read(reg) == v
    assert uc.reg_read(UC_X86_REG_ESP) == STACK + 0x8004


@pytest.mark.parametrize("g", range(12, 73))
def test_label_room_is_the_vanilla_slack_at_every_g(g):
    """The label draws in [text_x, row_x + [+0x64]): its room = maxText + 2*[+0x40] - 4 at EVERY g, i.e. the
    longest label (= maxText, measured in the draw font) always fits with the vanilla slack -- the pad's
    growth is carried by the row width, never cut from the label."""
    for max_text, margin, sprw in ((180, 3, 37), (412, 3, 92), (1, 2, 0)):
        x0 = SL.optionlist8_text_x(700, sprw, g)
        x1 = 700 + SL.optionlist8_row_width(max_text, margin, sprw, g)
        assert x1 - x0 == max_text + 2 * margin - SL.OPTIONLIST8_LABEL_PAD


# ---------------------------------------------------------------------------
# thunk_ol8_selbottom — the selection-ring bottom (2026-08-01 cutoff fix)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("pitch,y", [(40, 0), (100, 875), (62, 474)])
def test_selbottom_matches_the_law(g, pitch, y):
    """Ring bottom = y+1 + pitch - popup_scale_floor(3, g); 3 dwords pushed
    onto the caller's Buffer_box arg stack (color, color, bottom) with the
    E8 ret addr consumed via g_ol8_ret; exit regs byte-match the displaced
    original (eax=bottom, edx=pitch, edi=y+1; ecx/ebx/esi untouched)."""
    uc = _mk_uc(g)
    _w32(uc, IFACE + 0x68, pitch)
    uc.reg_write(UC_X86_REG_EDX, IFACE)          # dialog adjustor ptr
    uc.reg_write(UC_X86_REG_EDI, y)              # recentered sprite y (pre-inc)
    uc.reg_write(UC_X86_REG_EAX, 0x33)           # ring color
    uc.reg_write(UC_X86_REG_ECX, 0x00C0FFEE)     # elem sprite ptr — LIVE
    uc.reg_write(UC_X86_REG_EBX, 0x11111111)     # row x — LIVE
    _run(uc, SELB_VA, STACK + 0x8000)
    bottom = SL.optionlist8_ring_bottom(y + 1, pitch, g)
    esp = uc.reg_read(UC_X86_REG_ESP)
    assert esp == STACK + 0x8000 + 4 - 12, "ret consumed, 3 args pushed"
    assert _r32(uc, esp) == bottom, "pushed bottom"
    assert _r32(uc, esp + 4) == 0x33 and _r32(uc, esp + 8) == 0x33, "colors"
    assert uc.reg_read(UC_X86_REG_EAX) == bottom
    assert uc.reg_read(UC_X86_REG_EDX) == pitch
    assert uc.reg_read(UC_X86_REG_EDI) == y + 1
    assert uc.reg_read(UC_X86_REG_ECX) == 0x00C0FFEE, "ecx (sprite ptr) live — kept"
    assert uc.reg_read(UC_X86_REG_EBX) == 0x11111111, "ebx (row x) live — kept"
    if g <= 16:
        assert bottom == y + 1 + pitch - 3, "native identity"


@pytest.mark.parametrize("g", [17, 22, 25, 40])
@pytest.mark.parametrize("spr_nat", [60, 75, 100])
def test_selbottom_ring_stays_inside_its_cell(g, spr_nat):
    """The point of the fix: with pitch = gapS + sprHs (sprite-dominated) and
    the ring at the recentered y, the bottom must land before the next
    item's back-erase (cell-relative bottom <= pitch - 1)."""
    gap_s = SL.popup_scale_floor(3, g)
    spr_s = (spr_nat * g) // (2 * 16)            # the 1/2-ratio units
    pitch = gap_s + spr_s
    off = (pitch - spr_s) // 2
    bottom = SL.optionlist8_ring_bottom(off + 1, pitch, g)
    assert bottom <= pitch - 1
    # and the pre-fix engine value did NOT (the defect this pins):
    if gap_s > 3:
        assert off + 1 + pitch - 3 > pitch - 1


# ---------------------------------------------------------------------------
# thunk_orn_childx — the ornate dialog child-x correction (2026-08-01d)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("g", [16, 17, 21, 22, 25, 40])
@pytest.mark.parametrize("ptype", [0, 2, 5, 6, 1000])
@pytest.mark.parametrize("dlg", [-1, 8])
def test_childx_matches_the_law(g, ptype, dlg):
    """Child x at caller [esp+0x10]: ornate 2/6 & g>16 -> += ps3-3 (law
    ornate_dialog_child_x); every other type and g<=16 bit-true.  The
    trailing cmp must leave ZF == (dlg == -1) for the 0x602b8f je; edx and
    ecx preserved; ret consumed (stack balanced)."""
    uc = _mk_uc(g)
    for page in (ELEM + 0x2000, ELEM + 0x3000):
        uc.mem_map(page, 0x1000)
    _w32(uc, ELEM + 0x30AC, ptype * 10000)
    uc.mem_write(ELEM + 0x2350, (dlg & 0xFFFFFFFF).to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESI, ELEM)
    uc.reg_write(UC_X86_REG_EDX, 0x5A5A5A5A)     # preserved (push/pop)
    uc.reg_write(UC_X86_REG_ECX, 0x00C0FFEE)     # untouched
    esp0 = STACK + 0x8000
    x0 = 43                                       # the measured 4K engine value
    _w32(uc, esp0 + 0x14, x0)                     # caller [esp+0x10] after ret
    _run(uc, CHILDX_VA, esp0)
    assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 4, "ret consumed, stack balanced"
    expect = SL.ornate_dialog_child_x(x0, g) if ptype in (2, 6) else x0
    assert _r32(uc, esp0 + 0x14) == expect, (g, ptype)
    zf = bool(uc.reg_read(UC_X86_REG_EFLAGS) & ZF)
    assert zf == (dlg == -1), "the 0x602b8f je consumes the trailing cmp"
    assert uc.reg_read(UC_X86_REG_EDX) == 0x5A5A5A5A, "edx must be preserved"
    assert uc.reg_read(UC_X86_REG_ECX) == 0x00C0FFEE, "ecx untouched"
    assert uc.reg_read(UC_X86_REG_ESI) == ELEM
    if g <= 21 or ptype not in (2, 6):
        assert _r32(uc, esp0 + 0x14) == x0, "identity (native / ps3==3 / non-ornate)"


def test_childx_the_4k_regression_case():
    """The report itself: child x 43 = s(16)+3 @g40 -> 47 = fl(19*40/16); the
    ring then sits ps3 inside the s(16) frame instead of hugging it."""
    assert SL.ornate_dialog_child_x(43, 40) == 47
    assert SL.ornate_dialog_child_x(43, 40) == (19 * 40) >> 4
    assert SL.ornate_dialog_child_x(28, 25) == 29 == (19 * 25) >> 4
    assert SL.ornate_dialog_child_x(19, 16) == 19


# ---------------------------------------------------------------------------
# thunk_tutwin_backdrop v2 — the ornate-frame routing
# ---------------------------------------------------------------------------

STASH_SENTINEL = 0xCAFEBABE


def _run_tw(g, ecx, params, rect=0x00330000):
    uc = _mk_uc(g)
    uc.mem_map(rect & ~0xFFF, 0x1000)
    calls = []
    # RET 8 stubs at the devfill/keyint sentinel targets
    uc.mem_write(DEVFILL, b"\xC2\x08\x00")
    uc.mem_write(KEYINT, b"\xC2\x08\x00")

    def rec(u, addr, size, _):
        esp = u.reg_read(UC_X86_REG_ESP)
        calls.append((addr, _r32(u, esp + 4), _r32(u, esp + 8),
                      u.reg_read(UC_X86_REG_ECX)))

    uc.hook_add(UC_HOOK_CODE, rec, begin=DEVFILL, end=DEVFILL)
    uc.hook_add(UC_HOOK_CODE, rec, begin=KEYINT, end=KEYINT)
    _w32(uc, TITLE_L, STASH_SENTINEL)
    _w32(uc, TITLE_R, STASH_SENTINEL)
    _w32(uc, TUTWIN_W, 1200)
    esp0 = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0 + 0x0, SITE_RET)
    _w32(uc, esp0 + 0x4, rect)
    _w32(uc, esp0 + 0x8, params)
    uc.reg_write(UC_X86_REG_ECX, ecx)
    uc.emu_start(TW_VA, SITE_RET, count=10000)
    assert uc.reg_read(UC_X86_REG_EIP) == SITE_RET
    assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 0xC, "RET 8 contract"
    return uc, calls


def test_tw_ornate_any_dest_draws_devfill_then_keyint():
    """The picker case: ornate params, non-TutWin dest, g>16 — v3 routes the
    ornate over-draw through thunk_hollow_keyint (interior-erased hollow)."""
    dest = 0x00330400
    uc, calls = _run_tw(40, dest, ORNATE, rect=0x00330000)
    assert [c[0] for c in calls] == [DEVFILL, KEYINT], "synth then keyint-over"
    for addr, rect, params, ecx in calls:
        assert rect == 0x00330000 and params == ORNATE, "original args re-pushed"
        assert ecx == dest, "dest restored from g_tw_dest for keyint"
    assert _r32(uc, TITLE_L) == STASH_SENTINEL, "stash is TutWin-ONLY"
    assert _r32(uc, TITLE_R) == STASH_SENTINEL


@pytest.mark.parametrize("g", [22, 25, 40])
def test_tw_tutwin_keeps_the_synthetic_stash(g):
    uc, calls = _run_tw(g, TUTWIN_BUF, ORNATE)
    assert [c[0] for c in calls] == [DEVFILL, KEYINT]
    tl = SL.tutwin_stash_left(g)
    assert _r32(uc, TITLE_L) == tl, "law tutwin_stash_left"
    assert _r32(uc, TITLE_R) == SL.tutwin_stash_right(1200, g)


@pytest.mark.parametrize("g,ecx,params", [
    (16, 0x00330400, ORNATE),        # ornate but native res
    (16, TUTWIN_BUF, ORNATE),
    (40, 0x00330400, 0x0078D690),    # flat d690 def — devfill's own business
])
def test_tw_tail_paths_forward_untouched(g, ecx, params):
    uc, calls = _run_tw(g, ecx, params)
    assert [c[0] for c in calls] == [DEVFILL], "single tail-jmp, no hollow"
    addr, rect, p, got_ecx = calls[0]
    assert (rect, p, got_ecx) == (0x00330000, params, ecx), \
        "tail path must not touch the caller's stack or ecx"
    assert _r32(uc, TITLE_L) == STASH_SENTINEL


# ---------------------------------------------------------------------------
# thunk_hollow_keyint — the interior-erased hollow clone (banding fix)
# ---------------------------------------------------------------------------

KEYINT_VA = PCAVE2 + AO.KEYINT_OFF
CLAMP = AO.CLAMP
ENSURE = AO.ENSURE
RESIZE = AO.RESIZE
SETCLIP = AO.SETCLIP
FILL3 = AO.FILL3
BOXSPRITE = AO.BOXSPRITE
BANDMAP = AO.BANDMAP

FRAMEBUF = 0x00350000
PARAMS = 0x00340000
EDGE_T = 0x00360000        # params[4] top edge sprite
EDGE_B = 0x00360100        # params[5] bottom
EDGE_L = 0x00360200        # params[6] left
EDGE_R = 0x00360300        # params[7] right
FILLSPR = 0x00360400       # params[8]
RECT = 0x00330000


def _mk_params(uc, edges, fill, at=PARAMS):
    """edges = (lw, th, rw, bh) cross dims or None per slice; fill bool."""
    lw, th, rw, bh = edges
    for i in range(10):
        _w32(uc, at + 4 * i, 0)
    if th is not None:
        _w32(uc, at + 0x10, EDGE_T)
        _w32(uc, EDGE_T + 0x1C, th)
    if bh is not None:
        _w32(uc, at + 0x14, EDGE_B)
        _w32(uc, EDGE_B + 0x1C, bh)
    if lw is not None:
        _w32(uc, at + 0x18, EDGE_L)
        _w32(uc, EDGE_L + 0x18, lw)
    if rw is not None:
        _w32(uc, at + 0x1C, EDGE_R)
        _w32(uc, EDGE_R + 0x18, rw)
    if fill:
        _w32(uc, at + 0x20, FILLSPR)


def _run_keyint(g, rect_lrtb, edges, fill, dest=0x00330400, params=PARAMS):
    uc = _mk_uc(g)
    for page in (0x00330000, PARAMS, FRAMEBUF, 0x00360000, ORNATE & ~0xFFF):
        uc.mem_map(page, 0x1000)
    l, t, r, b = rect_lrtb
    _w32(uc, RECT + 0x0, l)
    _w32(uc, RECT + 0x4, t)
    _w32(uc, RECT + 0x8, r)
    _w32(uc, RECT + 0xC, b)
    _mk_params(uc, edges, fill, at=params)
    calls = []
    # stubs: CLAMP plain ret; ENSURE returns FRAMEBUF; RESIZE/FILL3/BOXSPRITE
    # ret 8; SETCLIP ret 4; BANDMAP ret 0x18
    uc.mem_write(CLAMP, b"\xC3")
    uc.mem_write(ENSURE, b"\xB8" + FRAMEBUF.to_bytes(4, "little") + b"\xC3")
    uc.mem_write(RESIZE, b"\xC2\x08\x00")
    uc.mem_write(SETCLIP, b"\xC2\x04\x00")
    uc.mem_write(FILL3, b"\xC2\x08\x00")
    uc.mem_write(BOXSPRITE, b"\xC2\x08\x00")
    uc.mem_write(BANDMAP, b"\xC2\x18\x00")

    def rec(u, addr, size, _):
        esp = u.reg_read(UC_X86_REG_ESP)
        args = [_r32(u, esp + 4 * i) for i in range(1, 7)]
        calls.append((addr, u.reg_read(UC_X86_REG_ECX), args))

    for sent in (CLAMP, ENSURE, RESIZE, SETCLIP, FILL3, BOXSPRITE, BANDMAP):
        uc.hook_add(UC_HOOK_CODE, rec, begin=sent, end=sent)

    uc.reg_write(UC_X86_REG_EBX, 0xB0B0B0B0)
    uc.reg_write(UC_X86_REG_ESI, 0x51515151)
    uc.reg_write(UC_X86_REG_EDI, 0xD1D1D1D1)
    esp0 = STACK + 0x8000
    uc.reg_write(UC_X86_REG_ESP, esp0)
    _w32(uc, esp0 + 0x0, SITE_RET)
    _w32(uc, esp0 + 0x4, RECT)
    _w32(uc, esp0 + 0x8, params)
    uc.reg_write(UC_X86_REG_ECX, dest)
    uc.emu_start(KEYINT_VA, SITE_RET, count=10000)
    assert uc.reg_read(UC_X86_REG_EIP) == SITE_RET
    assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 0xC, "RET 8 contract"
    assert uc.reg_read(UC_X86_REG_EBX) == 0xB0B0B0B0, "ebx restored"
    assert uc.reg_read(UC_X86_REG_ESI) == 0x51515151, "esi restored"
    assert uc.reg_read(UC_X86_REG_EDI) == 0xD1D1D1D1, "edi restored"
    return uc, calls


def _fill3_rect(uc, argptr):
    return tuple(_r32(uc, argptr + 4 * i) for i in range(4))


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_keyint_erases_the_fill_region(g):
    """Ornate-like def (all edges + fill): the second Buffer_fill_3 must key
    out exactly scaling_laws.hollow_interior_erase of the small render."""
    rect = (100, 200, 500, 440)
    uc, calls = _run_keyint(g, rect, (8, 6, 8, 6), fill=True)
    order = [c[0] for c in calls]
    assert order == [CLAMP, ENSURE, RESIZE, SETCLIP, FILL3, BOXSPRITE,
                     FILL3, BANDMAP], order
    small_w = ((rect[2] - rect[0]) << 4) // g
    small_h = ((rect[3] - rect[1]) << 4) // g
    # RESIZE(w, h)
    assert calls[2][2][:2] == [small_w, small_h]
    # pre-fill: whole small rect, key 9
    pre_rect, pre_key = calls[4][2][0], calls[4][2][1]
    assert _fill3_rect(uc, pre_rect) == (0, 0, small_w, small_h)
    assert pre_key == 9
    # small render with the ORIGINAL params (fill + edge masks intact)
    assert calls[5][2][1] == PARAMS  # generic case runs with the PARAMS block
    # the erase: law rect, key 9, into the frame buf
    er_ptr, er_key = calls[6][2][0], calls[6][2][1]
    assert er_key == 9 and calls[6][1] == FRAMEBUF
    law = SL.hollow_interior_erase(small_w, small_h, 8, 6, 8, 6)
    assert law is not None and _fill3_rect(uc, er_ptr) == law
    # band-map blit: dest, key 9, x, y, num=g, den=16
    bm_ecx, bm_args = calls[7][1], calls[7][2]
    assert bm_ecx == FRAMEBUF
    assert bm_args == [0x00330400, 9, rect[0], rect[1], g, 0x10]


def test_keyint_null_slices_use_zero_inset():
    """d528-style def: null edge slices contribute 0 inset (engine mirror)."""
    rect = (0, 0, 400, 320)
    g = 40
    uc, calls = _run_keyint(g, rect, (8, None, None, 6), fill=True)
    small_w, small_h = (400 << 4) // g, (320 << 4) // g
    er = [c for c in calls if c[0] == FILL3][1]
    law = SL.hollow_interior_erase(small_w, small_h, 8, 0, 0, 6)
    assert _fill3_rect(uc, er[2][0]) == law


@pytest.mark.parametrize("edges,fill,reason", [
    ((8, 6, 8, 6), False, "no fill sprite -> nothing to erase"),
    ((90, 6, 90, 6), True, "degenerate span -> erase skipped (law None)"),
])
def test_keyint_skips_erase(edges, fill, reason):
    rect = (0, 0, 400, 100)   # small at g=40: 160x40; lw=rw=90 -> inverted
    uc, calls = _run_keyint(40, rect, edges, fill)
    order = [c[0] for c in calls]
    assert order == [CLAMP, ENSURE, RESIZE, SETCLIP, FILL3, BOXSPRITE,
                     BANDMAP], reason
    if fill:
        small_w, small_h = (400 << 4) // 40, (100 << 4) // 40
        assert SL.hollow_interior_erase(small_w, small_h, 90, 6, 90, 6) is None


def test_keyint_g16_native_tail():
    """g<=16: single native Buffer_box_sprite tail with the caller's stack
    and ecx untouched — exact no-op vs vanilla."""
    dest = 0x00330400
    uc, calls = _run_keyint(16, (0, 0, 400, 320), (8, 6, 8, 6), fill=True,
                            dest=dest)
    assert [c[0] for c in calls] == [BOXSPRITE]
    addr, ecx, args = calls[0]
    assert ecx == dest and args[0] == RECT and args[1] == PARAMS


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_keyint_ornate_erases_to_the_metal_core(g):
    """params == &0x6846B0: the erase must inset by the art-measured METAL
    core (8,8,9,6 — law ornate_interior_erase), NOT the 61/44 fill-region
    insets, so the edge cells' mask-pass stripes get keyed out too (the
    'banding on the sides', 1600x1200 2026-08-01)."""
    rect = (100, 200, 1098, 602)      # the g=25 picker window is 998x402
    uc, calls = _run_keyint(g, rect, (61, 44, 61, 44), fill=True,
                            params=ORNATE)
    order = [c[0] for c in calls]
    assert order == [CLAMP, ENSURE, RESIZE, SETCLIP, FILL3, BOXSPRITE,
                     FILL3, BANDMAP], order
    small_w = ((rect[2] - rect[0]) << 4) // g
    small_h = ((rect[3] - rect[1]) << 4) // g
    er = calls[6]
    assert er[2][1] == 9 and er[1] == FRAMEBUF
    law = SL.ornate_interior_erase(small_w, small_h)
    assert law is not None and _fill3_rect(uc, er[2][0]) == law
    # NOT the generic fill-region law (61/44 would leave the side stripes)
    assert law != SL.hollow_interior_erase(small_w, small_h, 61, 44, 61, 44)


def test_keyint_ornate_vs_generic_disagree_only_in_insets():
    """The generic path must be untouched by the ornate arm: same def shape
    via the PARAMS block erases at sprite-dim insets."""
    rect = (0, 0, 998, 402)
    g = 25
    uc, calls = _run_keyint(g, rect, (61, 44, 61, 44), fill=True)
    small_w, small_h = (998 << 4) // g, (402 << 4) // g
    er = [c for c in calls if c[0] == FILL3][1]
    assert _fill3_rect(uc, er[2][0]) == SL.hollow_interior_erase(
        small_w, small_h, 61, 44, 61, 44)
