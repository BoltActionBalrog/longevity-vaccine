"""HQ report console chrome chain (2026-10-17): the law (scaling_laws.rw_console_step / rw_console_box_inset /
rw_console_centre_inset, rw_tab_inset v2) and its walker port t_rw_immsum + the CHAIN_ROWS table (assemble_rw).

The defect (shots 20261017-115800 F3 1600x1200, 121433 F2 4K): every console painter's content box sat s(6) from the
panel region while its d5a0 sits at s(3) (K wide), so the d5a0 -> box channel read s6 - s3 - K = 6 at 4K, 2 at
1600x1200 against vanilla's 2 (pristine HQData pages / 2.8125: da50 | 2 | d5a0 | 2 | d528 on all four sides), and the
far edges came from W - s(0xC) (one off the mirror of s(6) at most g) drawn INCLUSIVE.  Law: the box sits one step
U = K + s(2) inside its d5a0, C = s(3) + U; P = C + U for the buttons nested in a box.

Covers: the law (g = 16 identity, every channel s(2) and symmetric at every reachable g); every CHAIN_ROWS row's
g = 16 value == the pristine immediate and its terms == its law; t_rw_immsum from its REAL assembled bytes over the
real table at g = 17..40 (the stored byte / dword == mult x law, sign-extended imm8 range); the rows are not HD rows."""
from __future__ import annotations

import struct

import pytest

import scaling_laws as SL
from test_rw_asm_parity import AR, Emu, SP0, VA, r32  # noqa: F401
import assemble_se as SE

s = SL.scale_px
GALL = list(range(17, SL.G_MAX + 1))


def test_law_identity_at_16():
    for g in (8, 12, 16):
        assert (SL.rw_console_step(g), SL.rw_console_box_inset(g), SL.rw_tab_inset(g), SL.rw_console_centre_inset(g)) == (3, 6, 9, 7)
        assert SL.rw_console_box_w(241, g) == 241 - 0xC


@pytest.mark.parametrize("g", GALL)
def test_law_channels_are_s2_and_symmetric(g):
    K, s2, s3, s4 = SL.stroke_width(g), s(2, g), s(3, g), s(4, g)
    U, C, P, Q = SL.rw_console_step(g), SL.rw_console_box_inset(g), SL.rw_tab_inset(g), SL.rw_console_centre_inset(g)
    for L, R in ((4, 245), (6, 382), (9, 600), (3230, 3830)):
        # half-open boxes: the panel d5a0 strokes [L+s3, L+s3+K) / [R-s3-K, R-s3); the content box [L+C, R-C)
        left = (L + C) - (L + s3 + K)
        right = (R - s3 - K) - (R - C)
        assert left == right == s2
        assert (L + P) - (L + C + K) == (R - C - K) - (R - P) == s2          # buttons nested in the box
    assert Q - s4 - K == s2 and U == K + s2 and P == C + U


@pytest.mark.parametrize("key", sorted(AR.SUM_TERMS))
def test_sum_terms_are_the_laws(key):
    for g in GALL:
        want = SL.scale_px(6, g) if key == "S6" else SL.rw_sum_law(key, g)
        assert SL.rw_sum_value(AR.SUM_TERMS[key], g) == want, (key, g)


def _pristine_imm(site, w):
    b = SE.base_exe_bytes(site, w)
    return struct.unpack("<i", b)[0] if w == 4 else struct.unpack("<b", b)[0]


def _native(key, mult):
    return mult * {"U": 3, "C": 6, "P": 9, "Q": 7, "L28C": 0x2E, "S6": 6, "Y": 0x20}[key]


def test_chain_rows_native_identity():
    """Each row stores mult x law; at g = 16 that is the pristine immediate the instruction already carries (the sign
    per instruction: `sub r,imm` rows are positive, `add r,-imm` / `mov r,-imm` rows negative)."""
    for site, w, key, mult, lbl in AR.CHAIN_ROWS:
        assert _pristine_imm(site, w) == _native(key, mult), (hex(site), lbl)
        assert SL.rw_sum_value(AR.chain_terms(key, mult), 16) == _native(key, mult)


def test_chain_rows_are_not_hd_rows_and_fit():
    hd = {r[0] for r in AR.rw_rows()}
    assert not hd & AR.CHAIN_SITES
    assert len(AR.CHAIN_SITES) == len(AR.CHAIN_ROWS)
    for site, w, key, mult, _l in AR.CHAIN_ROWS:
        for g in GALL:
            v = SL.rw_sum_value(AR.chain_terms(key, mult), g)
            assert w == 4 or -128 <= v <= 127, (hex(site), g, v)
    # the sum table lives inside g_rw_immtab's footprint, after the HD rows' terminator
    tab = AR.RW_TAB
    assert struct.unpack_from("<I", tab, AR.SUM_TAB_OFF - 4)[0] == 0 or tab[AR.SUM_TAB_OFF - 4:AR.SUM_TAB_OFF] == bytes(4)
    assert tab[AR.SUM_TAB_OFF:AR.SUM_TAB_OFF + len(AR.sum_tab_bytes())] == AR.sum_tab_bytes()
    assert len(tab) == AR.RW_TAB_LEN


def _run_immsum(g, vpdone):
    e = Emu(g)
    e.uc.mem_write(AR.T_DL_IMMFIX, b"\xC3")
    e.uc.mem_write(AR.TAB_RW, AR.RW_TAB)
    w32 = lambda a, v: e.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))  # noqa: E731
    w32(AR.G_DL_IMMG, g)
    w32(AR.AD.VPDONE, vpdone)
    for site, w, *_ in AR.CHAIN_ROWS:
        e.uc.mem_write(site, b"\xEE" * (w + 1))
    esp = SP0 - 4
    w32(esp, Emu.TRAP)
    e.run(VA["t_rw_immsum"], Emu.TRAP, esp=esp, ebx=0xB, esi=AR.TAB_RW, edi=0xF, ebp=0xA, count=20000)
    assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp"), e.reg("esp")) == (0xB, AR.TAB_RW, 0xF, 0xA, SP0)
    return e


@pytest.mark.parametrize("g", GALL)
def test_immsum_stores_the_law(g):
    """t_rw_immsum (real bytes, real table): t_dl_immfix stubbed to `ret` with its VP done; every chain site gets
    mult x law(g) (the 5-term "Y" rows through a continuation row), ebx / esi / edi / ebp preserved, the stack
    balanced."""
    e = _run_immsum(g, 1)
    for site, w, key, mult, lbl in AR.CHAIN_ROWS:
        want = mult * (s(6, g) if key == "S6" else SL.rw_sum_law(key, g))
        got = struct.unpack("<i", bytes(e.uc.mem_read(site, 4)))[0] if w == 4 else struct.unpack("<b", bytes(e.uc.mem_read(site, 1)))[0]
        assert got == want, (hex(site), lbl, got, want)
        if w == 1 and site + 1 not in AR.CHAIN_SITES:
            assert e.uc.mem_read(site + 1, 1)[0] == 0xEE                       # a byte store only


@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_immsum_stores_nothing_when_the_dl_vp_failed(g):
    """fix 4g: t_dl_immfix's own VirtualProtect (0x429000..0x49C000) failed -> it wrote no HD row and g_dl_vpdone is
    still 0; t_rw_immsum must store no chain row either (0x49BFCA lies in that window only: the unconditional store
    faulted), registers / stack as on the normal path."""
    e = _run_immsum(g, 0)
    for site, w, *_ in AR.CHAIN_ROWS:
        assert bytes(e.uc.mem_read(site, w + 1)) == b"\xEE" * (w + 1), hex(site)


def test_sum_table_continuation_rows():
    """A law with > 4 terms ("Y", 5) spans two table rows: the first flagged SUM_CONT (stores nothing), the site in
    both; every other law one row; the table's row count = sum(ceil(terms / 4))."""
    tab = AR.sum_tab_bytes()
    rows = [struct.unpack_from("<I", tab, i)[0] for i in range(0, len(tab) - 4, 12)]
    assert struct.unpack_from("<I", tab, len(tab) - 4)[0] == 0
    want = []
    for site, w, key, mult, _l in AR.CHAIN_ROWS:
        n = (len(AR.chain_terms(key, mult)) + 3) // 4
        want += [site | AR.SUM_CONT] * (n - 1) + [site | (0x80000000 if w == 4 else 0)]
    assert rows == want
    assert sum(1 for r in rows if r & AR.SUM_CONT) == sum(1 for r in AR.CHAIN_ROWS if r[2] == "Y") == 3


def test_init_leave_calls_immsum_and_vp_window_covers_the_rows():
    layout, _c, _e, names = AR.assemble_all()
    off, b = layout["t_rw_init_leave"]
    va = AR.PCAVE2 + off
    tgt = names["t_rw_immsum"]
    calls = [va + i for i in range(len(b) - 4) if b[i] == 0xE8 and va + i + 5 + struct.unpack_from("<i", b, i + 1)[0] == tgt]
    assert len(calls) == 1
    assert off + len(b) <= AR.DL_TILE_PH_OFF                      # t_rw_init_leave did not grow (ends 0x23ABD)
    n = AR.vp_len()
    for site, w, *_ in AR.CHAIN_ROWS:
        assert AR.VP_PAGE <= site and site + w <= AR.VP_PAGE + n or AR.DL_VP_LO <= site < AR.DL_VP_HI, hex(site)
