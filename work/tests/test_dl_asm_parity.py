"""Unicorn parity for the Datalinks bake (assemble_dl.py).

Oracle = scaling_laws (scale_px / stripe_top) + assemble_dl.imm_value (the walker's Python law).
Every thunk is emulated from its REAL assembled bytes at its REAL cave VA; engine callees are tiny
recording stubs.  Covers: the immfix walker over BOTH real tables at g 16/22/25/40 (incl. the FLOAT
bit-identity at g=16 and the PTR font swaps), the restripe core vs the P-law for all three pair
families (+ the no-pair and dominance bails), the hover s(3) stub, the arrowzoom globals bracket,
the techwrap RW/mode bracket, the bmxt clip-restore + exact-fill contract, and the tile wrapper's
argument passthrough + staged rect.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
pytest.importorskip("pefile")

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_ESP, UC_X86_REG_EBP,
)

import scaling_laws as SL  # noqa: E402
import wheel_stc_stub  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_dl as AD  # noqa: E402
    import dl_imms_gen as GEN  # noqa: E402
    import assemble_rw_ring as RR  # noqa: E402

LAYOUT, _END, NAMES = AD.assemble_all()
VA = dict(NAMES)
GS = (16, 22, 25, 40)
STACK, SP0 = 0x00300000, 0x00310000
RET_SITE = 0x00700100
STUB = 0x00700000
SCRATCH = 0x00720000
BUF = 0x02000000
_ks = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(src, va=0):
    enc, _ = _ks.asm(src, va)
    return bytes(enc)


def rd(uc, a, n):
    return bytes(uc.mem_read(a, n))


def r32(uc, a):
    return struct.unpack("<I", rd(uc, a, 4))[0]


def w32(uc, a, v):
    uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


class Emu:
    def __init__(self, g=25):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(AD.PCAVE2, 0x40000)    # the whole pcave2: t_dl_bmxt calls t_dl_snapchk (W6C, 0x3F080)
        uc.mem_map(STACK, 0x20000)
        uc.mem_map(STUB, 0x1000)
        uc.mem_map(SCRATCH, 0x1000)
        uc.mem_map(BUF, 0x40000)
        uc.mem_map(0x668000, 0x1000)      # g_popup_scale_num
        uc.mem_map(0x669000, 0x1000)      # IAT
        uc.mem_map(0x94C000, 0x1000)      # palette
        uc.mem_map(0x5E2000, 0x3000)      # BOX_SPRITE / BLIT_CORE / MONO_FN stubs
        uc.mem_map(0x5DA000, 0x1000)      # BUFFER_TILE stub
        uc.mem_map(0x696000, 0x1000)      # SCALE_NUM/DEN
        uc.mem_map(0x876000, 0x10000)     # ReportWin (RW+0x5980, +0xE268)
        uc.mem_map(0x7AE000, 0x2000)      # MODETAB / MW seeds
        uc.mem_map(0x7D3000, 0x1000)      # MODEIDX
        for name in LAYOUT:
            off, b = LAYOUT[name]
            uc.mem_write(AD.PCAVE2 + off, b)
        for name, (off, _end) in RR.HELPERS.items():
            uc.mem_write(AD.PCAVE2 + off, RR.assemble(name))
        w32(uc, AD.G, g)
        self.g = g

    def call(self, entry, args=(), ecx=0, edx=0, esi=0, ebx=0, ebp=0, edi=0, eax=0):
        uc = self.uc
        sp = SP0
        for a in reversed(args):
            sp -= 4
            w32(uc, sp, a)
        sp -= 4
        w32(uc, sp, RET_SITE)
        uc.reg_write(UC_X86_REG_ESP, sp)
        uc.reg_write(UC_X86_REG_ECX, ecx)
        uc.reg_write(UC_X86_REG_EDX, edx)
        uc.reg_write(UC_X86_REG_ESI, esi)
        uc.reg_write(UC_X86_REG_EBX, ebx)
        uc.reg_write(UC_X86_REG_EBP, ebp)
        uc.reg_write(UC_X86_REG_EDI, edi)
        uc.reg_write(UC_X86_REG_EAX, eax)
        uc.emu_start(entry, RET_SITE, count=50_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == RET_SITE
        return uc


# ---- walker --------------------------------------------------------------------
def imm_pages():
    sites = [s + o for s, o, _w, _k, _a, _b, _t, _l in GEN.IMMS] + [s + o for s, o, _w, _a, _n, _l in AD.PTR_ROWS]
    lo = min(sites) & ~0xFFF
    hi = (max(sites) + 4 + 0xFFF) & ~0xFFF
    return lo, hi


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("tech", (False, True))
def test_immfix_walker(g, tech):
    e = Emu(g)
    lo, hi = imm_pages()
    e.uc.mem_map(lo, hi - lo)
    w32(e.uc, AD.VPDONE, 1)               # skip the VirtualProtect bootstrap
    w32(e.uc, AD.IMMG, g)
    e.call(VA["t_dl_immfix_tech" if tech else "t_dl_immfix_main"], esi=0x51515151, ebx=0x61616161, edi=0x71717171, ebp=0x41414141)
    # callee-saved registers survive (2026-09-20: the entries returned esi = the table VA -> the secret-project flow
    # stored it as a Monument record param -> AV @0x4742BB drawing the plaque)
    from unicorn.x86_const import UC_X86_REG_EBP as _BP, UC_X86_REG_EBX as _BX, UC_X86_REG_EDI as _DI, UC_X86_REG_ESI as _SI
    assert [e.uc.reg_read(r) for r in (_SI, _BX, _DI, _BP)] == [0x51515151, 0x61616161, 0x71717171, 0x41414141]
    rows = AD.imm_rows(tech)
    assert rows
    for site, a, b, bits in rows:
        want = AD.imm_value(a, b, bits, g)
        if bits & AD.K_W4:
            have = struct.unpack("<i", rd(e.uc, site, 4))[0]
            wantv = struct.unpack("<i", struct.pack("<I", want & 0xFFFFFFFF))[0]
        else:
            have = rd(e.uc, site, 1)[0]
            wantv = want & 0xFF
        assert have == wantv, (hex(site), hex(bits), g, have, wantv)


def test_immfix_native_is_identity_for_floats():
    for site, off, w, kind, a, b, _t, lbl in GEN.IMMS:
        if kind != 'FLOAT':
            continue
        bits = AD.KINDBITS[kind] | AD.K_W4
        assert AD.imm_value(a, b, bits, 16) == a & 0xFFFFFFFF, lbl


# ---- restripe ------------------------------------------------------------------
def stripe_top_formula(y, g):
    p = SL.stripe_period(g)
    return (y % p) < ((p + 1) >> 1)


@pytest.mark.parametrize("g", (22, 25, 40))
def test_stripe_top_matches_law(g):
    for y in range(200):
        assert stripe_top_formula(y, g) == SL.stripe_top(y, g, 0), (y, g)


def make_buffer(uc, w, h, pitch, fill=0x00):
    data = BUF + 0x1000
    uc.mem_write(BUF, b"\x00" * 0x600)
    w32(uc, BUF + 0x54, data)
    w32(uc, BUF + 0x80, w)
    w32(uc, BUF + 0x84, (-h) & 0xFFFFFFFF)
    w32(uc, BUF + 0x4A8, pitch)
    uc.mem_write(data, bytes([fill]) * (pitch * h))
    return data


@pytest.mark.parametrize("g", (22, 25, 40))
@pytest.mark.parametrize("pair", ((0xC4, 0x41), (0xAE, 0xEE), (0x41, 0xC6)))
def test_restripe_pairs(g, pair):
    e = Emu(g)
    top, bot = pair
    w, h, pitch = 40, 32, 44
    data = make_buffer(e.uc, w, h, pitch)
    plane = bytearray(pitch * h)
    for y in range(h):
        for x in range(w):
            v = top if (x + y) % 3 == 0 else (bot if (x + y) % 3 == 1 else 0x77)
            plane[y * pitch + x] = v
    e.uc.mem_write(data, bytes(plane))
    w32(e.uc, AD.RS["BUF"], BUF)
    w32(e.uc, AD.RS["X0"], 2)
    w32(e.uc, AD.RS["Y0"], 1)
    w32(e.uc, AD.RS["X1"], w - 3)
    w32(e.uc, AD.RS["Y1"], h - 2)
    e.call(VA["t_dl_restripe"])
    out = rd(e.uc, data, pitch * h)
    for y in range(h):
        for x in range(w):
            o = plane[y * pitch + x]
            n = out[y * pitch + x]
            if 2 <= x < w - 3 and 1 <= y < h - 2 and o in (top, bot):
                want = top if stripe_top_formula(y, g) else bot
                assert n == want, (x, y, hex(o), hex(n), hex(want))
            else:
                assert n == o, (x, y, hex(o), hex(n))


def test_restripe_no_pair_bails():
    e = Emu(25)
    w, h, pitch = 32, 24, 32
    data = make_buffer(e.uc, w, h, pitch, fill=0x77)
    before = rd(e.uc, data, pitch * h)
    w32(e.uc, AD.RS["BUF"], BUF)
    w32(e.uc, AD.RS["X0"], 0)
    w32(e.uc, AD.RS["Y0"], 0)
    w32(e.uc, AD.RS["X1"], w)
    w32(e.uc, AD.RS["Y1"], h)
    e.call(VA["t_dl_restripe"])
    assert rd(e.uc, data, pitch * h) == before


def test_restripe_dominance_bail():
    e = Emu(25)
    w, h, pitch = 40, 32, 40
    data = make_buffer(e.uc, w, h, pitch, fill=0x77)
    # a few stray pair pixels only (< area/4) -> untouched
    e.uc.mem_write(data + 5, bytes([0xC4, 0x41]))
    before = rd(e.uc, data, pitch * h)
    w32(e.uc, AD.RS["BUF"], BUF)
    w32(e.uc, AD.RS["X0"], 0)
    w32(e.uc, AD.RS["Y0"], 0)
    w32(e.uc, AD.RS["X1"], w)
    w32(e.uc, AD.RS["Y1"], h)
    e.call(VA["t_dl_restripe"])
    assert rd(e.uc, data, pitch * h) == before


# ---- hover ---------------------------------------------------------------------
@pytest.mark.parametrize("g,active", ((25, 1), (40, 1), (25, 0), (16, 1)))
def test_hover_stub(g, active):
    e = Emu(g)
    w32(e.uc, AD.G_DL_EXEC, active)
    uc = e.call(VA["t_dl_hover"], ecx=1000, edx=2000, ebx=3000, eax=3)
    d = SL.scale_px(3, g) if (active and g > 16) else 3
    assert uc.reg_read(UC_X86_REG_EDX) == 2000 + d
    assert uc.reg_read(UC_X86_REG_ECX) == 1000 - d
    assert uc.reg_read(UC_X86_REG_EBX) == 3000 + d
    assert uc.reg_read(UC_X86_REG_EAX) == 3


# ---- arrowzoom -----------------------------------------------------------------
@pytest.mark.parametrize("g,active", ((25, 1), (40, 1), (25, 0)))
def test_arrowzoom(g, active):
    e = Emu(g)
    w32(e.uc, AD.G_DL_EXEC, active)
    w32(e.uc, AD.SCALE_NUM, 1)
    w32(e.uc, AD.SCALE_DEN, 1)
    # stub: record num/den + the 4 args, ret 0x10
    rec = SCRATCH
    stub = asm(
        f"mov eax, dword ptr [{AD.SCALE_NUM:#x}]\n mov dword ptr [{rec:#x}], eax\n"
        f"mov eax, dword ptr [{AD.SCALE_DEN:#x}]\n mov dword ptr [{rec + 4:#x}], eax\n"
        f"mov eax, dword ptr [esp+4]\n mov dword ptr [{rec + 8:#x}], eax\n"
        f"mov eax, dword ptr [esp+8]\n mov dword ptr [{rec + 12:#x}], eax\n"
        f"mov eax, dword ptr [esp+12]\n mov dword ptr [{rec + 16:#x}], eax\n"
        f"mov eax, dword ptr [esp+16]\n mov dword ptr [{rec + 20:#x}], eax\n"
        "xor eax, eax\n ret 0x10", AD.BLIT_CORE)
    e.uc.mem_write(AD.BLIT_CORE, stub)
    uc = e.call(VA["t_dl_arrowzoom"], args=(0x11, 0x22, 0x33, 0x44), ecx=0xBEEF)
    assert r32(uc, rec + 8) == 0x11 and r32(uc, rec + 20) == 0x44
    if active and g > 16:
        assert r32(uc, rec) == g and r32(uc, rec + 4) == 16
        assert r32(uc, AD.SCALE_NUM) == 1 and r32(uc, AD.SCALE_DEN) == 1   # restored
    else:
        assert r32(uc, rec) == 1 and r32(uc, rec + 4) == 1
    assert uc.reg_read(UC_X86_REG_ESP) == SP0                              # ret 0x10 consumed all


# ---- techwrap ------------------------------------------------------------------
@pytest.mark.parametrize("g", (16, 22, 25, 40))
@pytest.mark.parametrize("device", (False, True))
def test_techwrap(g, device):
    # device=True: the rw_scale_shared init lever already rewrote textB/lineH/win_h (one owner).
    # win_h is RW+0x5990 (frame rect bottom); RW+0xA20 is POISONED with what ReportWin_tech_reset leaves there on
    # every page paint (textB - clipT), so a wrapper testing the identity against +0xA20 misses the native state.
    win_h = 473 + SL.RW_TEXTB_INSET
    if device and g > 16:
        tb, lh, wh = (win_h * g) // 16 - SL.scale_px(SL.RW_TEXTB_INSET, g), SL.scale_px(13, g) + 1, (win_h * g) // 16
    else:
        tb, lh, wh = 473, 13, win_h
    want_tb, want_lh = SL.dl_tech_inputs(tb, lh, wh, g)
    if device and g > 16:
        assert (want_tb, want_lh) == (tb, lh)
    e = Emu(g)
    e.uc.mem_map(0x498000, 0x1000)
    rec = SCRATCH
    stub = asm(
        f"mov eax, dword ptr [{AD.RW + 0x5980:#x}]\n mov dword ptr [{rec:#x}], eax\n"
        f"mov eax, dword ptr [{AD.RW + 0xE268:#x}]\n mov dword ptr [{rec + 4:#x}], eax\n"
        f"mov eax, dword ptr [{AD.MODETAB + 8:#x}]\n mov dword ptr [{rec + 8:#x}], eax\n"
        "ret", AD.TECH_PAGE)
    e.uc.mem_write(AD.TECH_PAGE, stub)
    w32(e.uc, AD.RW + 0x5980, tb)
    w32(e.uc, AD.RW + 0xE268, lh)
    w32(e.uc, AD.RW + 0x5990, wh)
    w32(e.uc, AD.RW + 0xA20, tb - (SL.scale_px(3, g) if device else 3))     # textB - clipT (tech_reset scratch)
    w32(e.uc, AD.MODEIDX, 2)
    w32(e.uc, AD.MODETAB + 8, 3)
    uc = e.call(VA["t_dl_techwrap"], ecx=AD.RW)
    assert r32(uc, rec) == want_tb and r32(uc, rec + 4) == want_lh
    assert r32(uc, rec + 8) == (8 if g > 16 else 3)
    assert r32(uc, AD.RW + 0x5980) == tb
    assert r32(uc, AD.RW + 0xE268) == lh
    assert r32(uc, AD.MODETAB + 8) == 3


# ---- bmxt ----------------------------------------------------------------------
def bmxt_setup(e, rect, clip, w=80, h=120, pitch=84):
    data = make_buffer(e.uc, w, h, pitch, fill=0x55)
    for i, v in enumerate(clip):
        w32(e.uc, BUF + 0x20 + i * 4, v)
    rp = BUF + 0x800
    for i, v in enumerate(rect):
        w32(e.uc, rp + i * 4, v)
    return data, rp


@pytest.mark.parametrize("g", (25, 40))
def test_bmxt_contract(g):
    e = Emu(g)
    w32(e.uc, AD.G_DL_EXEC, 1)
    rect = (20, 30, 46, 100)     # half-open
    clip = (20, 50, 36, 90)
    data, rp = bmxt_setup(e, rect, clip)
    # fake VirtualAlloc: IAT slot -> stub returning a scratch plane
    va_stub = asm(f"mov eax, {BUF + 0x20000:#x}\n ret 0x10", STUB + 0x200)   # NOT +0x100 = RET_SITE
    e.uc.mem_write(STUB + 0x200, va_stub)
    w32(e.uc, AD.IAT_VIRTUALALLOC, STUB + 0x200)
    # hollow_flat stub: scribble one inside-clip and one outside-clip pixel, record args, ret 8
    inside = data + 60 * 84 + 25      # y=60 in [50,90), x=25 in [20,36)
    outside = data + 40 * 84 + 25     # y=40 < ct
    rec = SCRATCH
    hf = asm(
        f"mov al, 0xEE\n mov byte ptr [{inside:#x}], al\n mov byte ptr [{outside:#x}], al\n"
        f"mov eax, dword ptr [esp+4]\n mov dword ptr [{rec:#x}], eax\n"
        f"mov eax, dword ptr [{AD.G_FC_EXACT:#x}]\n mov dword ptr [{rec + 4:#x}], eax\n"
        "ret 8", AD.HOLLOWFLAT)
    e.uc.mem_write(AD.HOLLOWFLAT, hf)
    uc = e.call(VA["t_dl_bmxt"], args=(rp, 0xD5A0), ecx=BUF, esi=0x1111, edi=0x2222, ebx=0x3333)
    # arg was repointed at the R-1/B-1 copy; flag was set during the call and cleared after
    assert r32(uc, rec) == AD.G_DW_BMRECT
    assert r32(uc, rec + 4) == 1
    assert r32(uc, AD.G_FC_EXACT) == 0
    assert [r32(uc, AD.G_DW_BMRECT + i * 4) for i in range(4)] == [20, 30, 45, 99]
    assert [r32(uc, AD.G_FSR + i * 4) for i in range(4)] == [20, 30, 46, 100]
    # the inside-clip scribble survives; the outside-clip one was restored
    assert rd(uc, inside, 1)[0] == 0xEE
    assert rd(uc, outside, 1)[0] == 0x55
    # callee-clean + saved regs
    assert uc.reg_read(UC_X86_REG_ESP) == SP0
    assert uc.reg_read(UC_X86_REG_ESI) == 0x1111
    assert uc.reg_read(UC_X86_REG_EDI) == 0x2222
    assert uc.reg_read(UC_X86_REG_EBX) == 0x3333


def test_bmxt_native_when_inactive():
    e = Emu(25)
    w32(e.uc, AD.G_DL_EXEC, 0)
    rec = SCRATCH
    bs = asm(f"mov eax, dword ptr [esp+4]\n mov dword ptr [{rec:#x}], eax\n ret 8", AD.BOX_SPRITE)
    e.uc.mem_write(AD.BOX_SPRITE, bs)
    rp = BUF + 0x800
    uc = e.call(VA["t_dl_bmxt"], args=(rp, 0xD5A0), ecx=BUF)
    assert r32(uc, rec) == rp                      # untouched rect passthrough
    assert uc.reg_read(UC_X86_REG_ESP) == SP0


# ---- tile wrapper --------------------------------------------------------------
@pytest.mark.parametrize("g", (16, 25))
def test_tile_wrapper(g):
    e = Emu(g)
    rec = SCRATCH
    parts = "\n".join(
        f"mov eax, dword ptr [esp+{4 + i * 4}]\n mov dword ptr [{rec + i * 4:#x}], eax" for i in range(7))
    tile = asm(parts + "\n ret 0x1C", AD.BUFFER_TILE)
    e.uc.mem_write(AD.BUFFER_TILE, tile)
    make_buffer(e.uc, 60, 40, 60, fill=0x77)      # no pair -> restripe bails
    args = (0x100, 0, 0, 5, 7, 30, 20)
    uc = e.call(VA["t_dl_tile_row"], args=args, ecx=BUF)
    assert tuple(r32(uc, rec + i * 4) for i in range(7)) == args
    assert uc.reg_read(UC_X86_REG_ESP) == SP0
    if g > 16:
        assert r32(uc, AD.RS["X0"]) == 5 and r32(uc, AD.RS["X1"]) == 35
        assert r32(uc, AD.RS["Y0"]) == 7 and r32(uc, AD.RS["Y1"]) == 27
        assert r32(uc, AD.RS["BUF"]) == BUF


# ---- faction portrait (bilinear gate wrapper + width lever) ---------------------
@pytest.mark.parametrize("g", (16, 22, 25, 40))
def test_portrait_scale(g):
    e = Emu(g)
    uc = e.uc
    w32(uc, AD.PAVG_GATE_IMM, AD.FACTION_BOX)
    rec = SCRATCH
    # Sprite_draw_2 stub: record the 6 args + ecx + the gate imm AS SEEN DURING THE CALL; ret 0x18
    stub = (
        "\n".join(f"mov eax, dword ptr [esp+{4 + i * 4}]\n mov dword ptr [{rec + i * 4:#x}], eax"
                  for i in range(6))
        + f"\n mov dword ptr [{rec + 24:#x}], ecx"
        + f"\n mov eax, dword ptr [{AD.PAVG_GATE_IMM:#x}]\n mov dword ptr [{rec + 28:#x}], eax"
        + "\n xor eax, eax\n ret 0x18")
    uc.mem_write(AD.SPRITE_DRAW2, asm(stub, AD.SPRITE_DRAW2))
    # g > 16 calls thunk_art_draw (assemble_artreblit.py: Sprite_draw_2 with the same args, then the scanline re-blit;
    # its own parity lives in test_artreblit_asm_parity) -- the same recording stub stands in for it here
    try:
        uc.mem_map(AD.ART_DRAW & ~0xFFF, 0x1000)
    except Exception:  # noqa: BLE001  (already mapped)
        pass
    uc.mem_write(AD.ART_DRAW, asm(stub, AD.ART_DRAW))
    args = (BUF, 9, 55, 66, 1, 1)   # dest, key, x, y, num, den
    uc = e.call(VA["t_dl_portrait"], args=args, ecx=0xCAFE)
    got = tuple(r32(uc, rec + i * 4) for i in range(6))
    if g > 16:
        assert got == (BUF, 9, 55, 66, g, 16)
        assert r32(uc, rec + 28) == AD.CANVAS            # gate poked to the DL canvas for the call
        assert r32(uc, AD.PAVG_GATE_IMM) == AD.FACTION_BOX   # restored after
    else:
        assert got == args                                # native 1:1 passthrough
        assert r32(uc, rec + 28) == AD.FACTION_BOX        # gate untouched on the native path
    assert r32(uc, rec + 24) == 0xCAFE                    # ecx = Sprite* passthrough
    assert uc.reg_read(UC_X86_REG_ESP) == SP0             # ret 0x18 consumed the args


@pytest.mark.parametrize("g", GS)
def test_portrait_width(g):
    e = Emu(g)
    uc = e.uc
    uc.mem_map(0x78E000, 0x1000)
    w32(uc, AD.PORTRAIT_W_FIELD, 131)
    uc.mem_map(0x430000, 0x1000)
    uc.mem_write(AD.PORTW_RESUME, b"\xC3")
    uc = e.call(VA["t_dl_portw"], ebx=0)
    # oracle = the resampler's OWN dest-width law: dstW = floor(srcW*num/den) (idiv truncation,
    # assemble_resampler.py) - NOT scale_px (which rounds half-up and would over-advance by 1px)
    want = (131 * g) >> 4 if g > 16 else 131
    assert uc.reg_read(UC_X86_REG_EBX) == want
    assert (131 * 16) >> 4 == 131                            # identity at native


# ---- DL wheel cascade -----------------------------------------------------------
def wargs(vk, lp):
    # the thunk reads wParam at [esp+0x68] and lParam at [esp+0x6C] (WinProc frame depth)
    return (0,) * 25 + (vk, lp)


DL_ORG = (100, 50)                 # DatalinkWin +0x13C/+0x140 (client space)
MW_ORG = (0, 1500)                 # MainWin_g origin (console strip)
RC_ART = (200, 10, 700, 400)       # right_container +0x103B4, DL-local device rect
RC_CON = (300, 20, 900, 200)       # console text box +0x10374, MainWin-local device rect
CUR_FAR = (-5000, -5000)           # cursor nowhere near either box (the pre-v2 order applies)
CUR_ART = (DL_ORG[0] + 450, DL_ORG[1] + 200)   # inside the article panel
CUR_LIST = (DL_ORG[0] + 50, DL_ORG[1] + 100)   # over the category list (off both boxes)
CUR_CON = (MW_ORG[0] + 600, MW_ORG[1] + 100)   # inside the console text box


def wheel_env(g=25, cursor=CUR_FAR):
    e = Emu(g)
    uc = e.uc
    uc.mem_map(0x9B7000, 0x2000)     # MODAL_TOP / BASEPOP / G_HWND
    uc.mem_map(0x5F6000, 0x1000)     # GET_TARGET stub + the cursor IAT stubs
    uc.mem_map(0x606000, 0x1000)     # CHEVRON stub
    uc.mem_map(0x703000, 0x1000)     # DatalinkWin +0x13C origin
    uc.mem_map(0x713000, 0x1000)     # LISTWIN
    uc.mem_map(0x714000, 0x2000)     # TS_FULL (embedded bar's range fields at ~win+0x1A44) + the DL rect tables
    uc.mem_map(0x716000, 0x3000)     # TS_CONSOLE
    uc.mem_map(0x719000, 0x3000)     # TS_LOWER
    uc.mem_map(0x71C000, 0x3000)     # TS_LOWER800
    rec = SCRATCH
    # v2 cursor routing: GetCursorPos(p) writes the test cursor; ScreenToClient(hwnd, p) is identity
    gcp, s2c = 0x5F6000, 0x5F6040
    w32(uc, AD.IAT_GETCURSORPOS, gcp)
    w32(uc, AD.IAT_SCREENTOCLIENT, s2c)
    uc.mem_write(gcp, asm(f"mov eax, dword ptr [esp+4]\n mov dword ptr [eax], {cursor[0]}\n"
                          f" mov dword ptr [eax+4], {cursor[1]}\n ret 4", gcp))
    uc.mem_write(s2c, asm("ret 8", s2c))
    wheel_stc_stub.install(uc)        # the head calls t_wheel_stc (cell 0 = no uimod.dll -> the IAT stub above)
    w32(uc, AD.G_HWND, 0xBEEF)
    uc.mem_write(AD.OBJ + 0x13C, struct.pack("<2i", *DL_ORG))
    uc.mem_write(AD.MW + 0x13C, struct.pack("<2i", *MW_ORG))
    uc.mem_write(AD.RC_ARTICLE, struct.pack("<4i", *RC_ART))
    uc.mem_write(AD.RC_CONSOLE, struct.pack("<4i", *RC_CON))
    uc.mem_write(AD.GET_TARGET, asm("mov eax, 0x1234\n ret", AD.GET_TARGET))
    uc.mem_write(AD.CHEVRON, asm(
        f"mov dword ptr [{rec:#x}], ecx\n mov eax, dword ptr [esp+4]\n"
        f" mov dword ptr [{rec + 4:#x}], eax\n ret 4", AD.CHEVRON))
    present = STUB + 0x200
    uc.mem_write(present, asm(f"mov dword ptr [{rec + 8:#x}], ecx\n ret", present))
    vt = STUB + 0x300
    w32(uc, vt + 0xFC, present)
    # chain markers over the dw wheel thunks (their real bytes are not in LAYOUT)
    uc.mem_write(AD.DW_WHEEL_DOWN, asm(f"mov dword ptr [{rec + 12:#x}], 0x77\n ret", AD.DW_WHEEL_DOWN))
    uc.mem_write(AD.DW_WHEEL_UP, asm(f"mov dword ptr [{rec + 12:#x}], 0x78\n ret", AD.DW_WHEEL_UP))
    w32(uc, AD.BASEPOP, 0)
    w32(uc, AD.MODAL_TOP, AD.OBJ)
    return e, rec, vt


def engage(uc, sb, on=True):
    w32(uc, sb + 0x9C, 1 if on else 0)
    w32(uc, sb + 0xC4, 1 if on else 0)
    w32(uc, sb + 0xA20, 0)
    w32(uc, sb + 0xA24, 5 if on else 0)


@pytest.mark.parametrize("vk,btn", ((0x28, 2), (0x26, 1)))
def test_wheel_list_scroll(vk, btn):
    e, rec, vt = wheel_env()
    uc = e.uc
    bar = BUF + 0x8000
    w32(uc, AD.LISTWIN, vt)
    w32(uc, AD.LISTWIN + 0x43C, bar)
    engage(uc, bar)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(vk, 0))
    assert r32(uc, rec) == bar and r32(uc, rec + 4) == btn   # chevron(bar, dir)
    assert r32(uc, rec + 8) == AD.LISTWIN                    # present on the list window
    assert uc.reg_read(UC_X86_REG_EAX) == 0                  # notch swallowed
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI):
        assert uc.reg_read(r) == 0                           # callee-saved restored


def test_wheel_ts_fallback():
    e, rec, vt = wheel_env()
    uc = e.uc
    # list bar absent; full-page TextScroll visible + engaged
    w32(uc, AD.TS_FULL, vt)
    engage(uc, AD.TS_FULL + 0xA20)
    w32(uc, AD.TS_FULL + 0x9C, 1)                            # TS window visible
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == AD.TS_FULL + 0xA20
    assert r32(uc, rec + 8) == AD.TS_FULL
    assert uc.reg_read(UC_X86_REG_EAX) == 0


def test_wheel_hidden_ts_swallows():
    e, rec, vt = wheel_env()
    uc = e.uc
    # engaged bar on a HIDDEN TextScroll must be skipped; nothing else engaged -> eat the notch
    w32(uc, AD.TS_LOWER, vt)
    engage(uc, AD.TS_LOWER + 0xA20)
    w32(uc, AD.TS_LOWER + 0x9C, 0)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == 0                                 # no chevron press
    assert uc.reg_read(UC_X86_REG_EAX) == 0                  # still swallowed (never selects)


def test_wheel_non_dl_chains():
    for basepop, modal in ((1, 0), (0, 0x123456)):
        e, rec, _vt = wheel_env()
        uc = e.uc
        w32(uc, AD.BASEPOP, basepop)
        w32(uc, AD.MODAL_TOP, modal)
        uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
        assert r32(uc, rec + 12) == 0x77                     # chained to the dw thunk
        assert r32(uc, rec) == 0
        # keyup chain too
        e2, rec2, _ = wheel_env()
        w32(e2.uc, AD.BASEPOP, basepop)
        w32(e2.uc, AD.MODAL_TOP, modal)
        u = e2.call(VA["t_dl_wheel_up"], args=wargs(0x28, 0))
        assert r32(u, rec2 + 12) == 0x78


def test_wheel_non_wheel_key_passes():
    e, rec, _vt = wheel_env()
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x41, 0))
    assert uc.reg_read(UC_X86_REG_EAX) == 0x1234             # GET_TARGET result untouched
    assert r32(uc, rec) == 0
    # real arrow key (scan code in lParam) passes through untouched
    e2, rec2, _ = wheel_env()
    uc2 = e2.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0x50001))
    assert uc2.reg_read(UC_X86_REG_EAX) == 0x1234
    assert r32(uc2, rec2) == 0


def test_wheel_up_swallows():
    for vk in (0x26, 0x28):
        e, rec, _vt = wheel_env()
        uc = e.call(VA["t_dl_wheel_up"], args=wargs(vk, 0))
        assert uc.reg_read(UC_X86_REG_EAX) == 0
        assert r32(uc, rec + 12) == 0                        # no chain


# ---- v2 (2026-09-22): the cursor over an article's own scroll box takes the notch ---------
def _both_engaged(uc, vt, ts=None, ts_visible=True):
    bar = BUF + 0x8000
    w32(uc, AD.LISTWIN, vt)
    w32(uc, AD.LISTWIN + 0x43C, bar)
    engage(uc, bar)
    if ts is not None:
        w32(uc, ts, vt)
        engage(uc, ts + 0xA20)
        w32(uc, ts + 0x9C, 1 if ts_visible else 0)
    return bar


@pytest.mark.parametrize("vk,btn", ((0x28, 2), (0x26, 1)))
@pytest.mark.parametrize("ts", ("TS_FULL", "TS_LOWER", "TS_LOWER800"))
def test_wheel_article_cursor_scrolls_the_text(vk, btn, ts):
    # list AND page text engaged, cursor inside the article panel -> the text's bar, its window presented
    e, rec, vt = wheel_env(cursor=CUR_ART)
    tsa = getattr(AD, ts)
    _both_engaged(e.uc, vt, tsa)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(vk, 0))
    assert r32(uc, rec) == tsa + 0xA20 and r32(uc, rec + 4) == btn
    assert r32(uc, rec + 8) == tsa
    assert uc.reg_read(UC_X86_REG_EAX) == 0
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI):
        assert uc.reg_read(r) == 0                           # callee-saved restored across try_ts


def test_wheel_article_cursor_without_engaged_text_keeps_the_list():
    # the picker "captures everywhere" rule survives: no text engaged under the cursor -> list
    e, rec, vt = wheel_env(cursor=CUR_ART)
    bar = _both_engaged(e.uc, vt)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == bar and r32(uc, rec + 8) == AD.LISTWIN


def test_wheel_article_cursor_hidden_text_keeps_the_list():
    e, rec, vt = wheel_env(cursor=CUR_ART)
    bar = _both_engaged(e.uc, vt, AD.TS_LOWER, ts_visible=False)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == bar and r32(uc, rec + 8) == AD.LISTWIN


@pytest.mark.parametrize("cursor", (CUR_LIST, CUR_FAR))
def test_wheel_cursor_off_the_article_keeps_the_list(cursor):
    # text engaged but the cursor is elsewhere (over the list / off-window) -> the list, as before
    e, rec, vt = wheel_env(cursor=cursor)
    bar = _both_engaged(e.uc, vt, AD.TS_LOWER)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == bar and r32(uc, rec + 8) == AD.LISTWIN


def test_wheel_console_box_cursor_scrolls_the_console_text():
    e, rec, vt = wheel_env(cursor=CUR_CON)
    _both_engaged(e.uc, vt, AD.TS_CONSOLE)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == AD.TS_CONSOLE + 0xA20 and r32(uc, rec + 8) == AD.TS_CONSOLE


def test_wheel_article_cursor_ignores_the_console_text():
    # the console text is NOT in the article panel: over the article it does not pre-empt the list
    e, rec, vt = wheel_env(cursor=CUR_ART)
    bar = _both_engaged(e.uc, vt, AD.TS_CONSOLE)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == bar and r32(uc, rec + 8) == AD.LISTWIN


@pytest.mark.parametrize("dx,dy,text", (
    (RC_ART[0] - 1, 100, False), (RC_ART[0], 100, True),
    (RC_ART[2] - 1, 100, True), (RC_ART[2], 100, False),
    (400, RC_ART[1] - 1, False), (400, RC_ART[1], True),
    (400, RC_ART[3] - 1, True), (400, RC_ART[3], False),
))
def test_wheel_article_panel_edges_are_half_open(dx, dy, text):
    # inside = L <= x < R and T <= y < B in DL-local space (cursor - DL origin)
    e, rec, vt = wheel_env(cursor=(DL_ORG[0] + dx, DL_ORG[1] + dy))
    bar = _both_engaged(e.uc, vt, AD.TS_FULL)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == (AD.TS_FULL + 0xA20 if text else bar)


def test_wheel_article_cursor_nothing_engaged_still_swallows():
    e, rec, _vt = wheel_env(cursor=CUR_ART)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert r32(uc, rec) == 0 and uc.reg_read(UC_X86_REG_EAX) == 0


# ---- article flow-scroll (vanilla line-break-jump fix) --------------------------
LIST = BUF + 0x1000
NODE = [BUF + 0x1100 + i * 0x20 for i in range(5)]
PAYL = [BUF + 0x1400 + i * 0x10 for i in range(5)]
H0, H_P1, LINEH, CANVH = 200, 80, 20, 100     # paragraphs: P0 = nodes 0-2 (cum 0), P1 = nodes 3-4 (cum 120)


def flow_env(k, canvh=CANVH):
    e = Emu(25)
    uc = e.uc
    uc.mem_map(0x714000, 0x2000)     # TS_FULL (+0x1444/+0x1460 bar range fields)
    uc.mem_map(0x5DB000, 0x2000)     # WRITE_STRINGS + LINEH_FN stubs
    rec = SCRATCH
    # list: +8 head +C cursor +10 count +14 idx
    w32(uc, LIST + 8, NODE[0]); w32(uc, LIST + 0xC, NODE[0])
    w32(uc, LIST + 0x10, 5); w32(uc, LIST + 0x14, 0)
    flags = (1, 0, 0, 1, 0)
    for i in range(5):
        w32(uc, NODE[i] + 8, PAYL[i])
        w32(uc, NODE[i] + 0xC, NODE[(i + 1) % 5])           # circular
        w32(uc, PAYL[i] + 8, flags[i])
    ts = AD.TS_FULL
    w32(uc, ts + 0xA1C, k & 0xFFFFFFFF)
    w32(uc, ts + 0x4C8, (-canvh) & 0xFFFFFFFF)              # negative canvas height
    # measurer stub: flags==0 -> H0; else by cursor (call count at rec+0x40)
    wsh = (
        f"inc dword ptr [{rec + 0x40:#x}]\n"
        "mov eax, dword ptr [esp+0xC]\n test eax, eax\n jnz bycur\n"
        f"mov eax, {H0}\n ret 0xC\n"
        "bycur:\n mov eax, dword ptr [esp+4]\n mov eax, dword ptr [eax+0xC]\n"
        f"cmp eax, {NODE[0]:#x}\n jne n3\n mov eax, {H0}\n ret 0xC\n"
        f"n3:\n cmp eax, {NODE[3]:#x}\n jne bad\n mov eax, {H_P1}\n ret 0xC\n"
        "bad:\n mov eax, 999\n ret 0xC")
    uc.mem_write(AD.WSH, asm(wsh, AD.WSH))
    uc.mem_write(AD.LINEH_FN, asm(f"mov eax, {LINEH}\n ret", AD.LINEH_FN))
    # write_strings stub: record 5 args + cursor/idx + ecx; ret 0x14
    ws = ("\n".join(f"mov eax, dword ptr [esp+{4 + i * 4}]\n mov dword ptr [{rec + i * 4:#x}], eax"
                    for i in range(5))
          + f"\n mov eax, dword ptr [esp+4]\n mov eax, dword ptr [eax+0xC]\n mov dword ptr [{rec + 0x14:#x}], eax"
          + f"\n mov eax, dword ptr [esp+4]\n mov eax, dword ptr [eax+0x14]\n mov dword ptr [{rec + 0x18:#x}], eax"
          + f"\n mov dword ptr [{rec + 0x1C:#x}], ecx"
          + "\n xor eax, eax\n ret 0x14")
    uc.mem_write(AD.WRITE_STRINGS, asm(ws, AD.WRITE_STRINGS))
    return e, rec


def run_flow(e, canvas=None):
    return e.call(VA["t_ts_flowdraw"], args=(LIST, 0, 7, 600, 2),
                  ecx=(AD.TS_FULL + 0x444) if canvas is None else canvas)


def test_flow_cache_and_offsets():
    e, rec = flow_env(k=3)                                   # t = 60 -> P0, y = -60
    uc = run_flow(e)
    assert r32(uc, rec + 0x14) == NODE[0] and r32(uc, rec + 0x18) == 0
    assert r32(uc, rec + 8) == (-60) & 0xFFFFFFFF            # y arg rewritten
    assert r32(uc, rec + 0x10) == 2                          # flags passthrough
    assert r32(uc, rec + 0x1C) == AD.TS_FULL + 0x444         # ecx restored
    F = AD.FLOW
    assert r32(uc, F + 0x10) == LINEH and r32(uc, F + 0x14) == H0 // LINEH
    assert r32(uc, F + 0x1C) == CANVH // LINEH and r32(uc, F + 0x18) == 2
    assert r32(uc, F + 0x24) == NODE[0] and r32(uc, F + 0x24 + 8) == 0
    assert r32(uc, F + 0x30) == NODE[3] and r32(uc, F + 0x30 + 4) == 3
    assert r32(uc, F + 0x30 + 8) == H0 - H_P1                # cum_px(P1) = 120
    ts = AD.TS_FULL
    assert r32(uc, ts + 0x1440) == 0                          # bar min
    assert r32(uc, ts + 0x1444) == H0 // LINEH - CANVH // LINEH   # max = total - visible = 5
    assert r32(uc, ts + 0x1460) == CANVH // LINEH - 1        # page = visible - 1
    assert r32(uc, rec + 0x40) == 3                          # H0 + 2 paragraph measures


def test_flow_second_paragraph_and_reuse():
    # canvh 40 -> visible 2, max = 10-2 = 8; k=7 -> t=140 >= cum(P1)=120 -> P1, y = 120-140 = -20
    e, rec = flow_env(k=7, canvh=40)
    uc = run_flow(e)
    assert r32(uc, rec + 0x14) == NODE[3] and r32(uc, rec + 0x18) == 3
    assert r32(uc, rec + 8) == (-20) & 0xFFFFFFFF
    n = r32(uc, rec + 0x40)
    assert n == 3
    uc = run_flow(e)                                         # same key -> no re-measure
    assert r32(uc, rec + 0x40) == n
    w32(uc, LIST + 0x10, 4)                                  # content key changed -> rebuild
    uc = run_flow(e)
    assert r32(uc, rec + 0x40) > n


def test_flow_clamp_and_zero():
    e, rec = flow_env(k=9)                                   # clamp to total-visible = 5 -> t=100 -> P0, y=-100
    uc = run_flow(e)
    assert r32(uc, AD.TS_FULL + 0xA1C) == 5
    assert r32(uc, rec + 8) == (-100) & 0xFFFFFFFF
    e, rec = flow_env(k=0)
    uc = run_flow(e)
    assert r32(uc, rec + 8) == 0 and r32(uc, rec + 0x14) == NODE[0]


def test_flow_passthrough():
    e, rec = flow_env(k=-1)                                  # negative first-line: vanilla path
    w32(e.uc, LIST + 0xC, NODE[2])                           # pre-positioned cursor must survive
    uc = run_flow(e)
    assert r32(uc, rec + 8) == 7                             # y arg untouched
    assert r32(uc, rec + 0x14) == NODE[2]
    assert r32(uc, rec + 0x40) == 0                          # no measuring
    e, rec = flow_env(k=3)                                   # non-DL canvas: untouched
    other = BUF + 0x3000
    w32(e.uc, LIST + 0xC, NODE[1])
    uc = run_flow(e, canvas=other)
    assert r32(uc, rec + 8) == 7 and r32(uc, rec + 0x1C) == other
    assert r32(uc, rec + 0x40) == 0


@pytest.mark.parametrize("mode,origin,space,hits", wheel_stc_stub.MODES)
def test_wheel_pracx_cursor_modes_console_box_corner(mode, origin, space, hits):
    """t_dl_wheel_down reads the cursor through PRACX's hooked GetCursorPos + t_wheel_stc: the console text box's
    top-left corner (half-open edge) is hit in every display setup; the no-DLL control misses it by the origin."""
    b = (MW_ORG[0] + RC_CON[0], MW_ORG[1] + RC_CON[1])
    with wheel_stc_stub.mode(mode, *origin):
        e, rec, vt = wheel_env(cursor=wheel_stc_stub.pracx_cursor(b, origin, space))
    _both_engaged(e.uc, vt, AD.TS_CONSOLE)
    uc = e.call(VA["t_dl_wheel_down"], args=wargs(0x28, 0))
    assert (r32(uc, rec) == AD.TS_CONSOLE + 0xA20) == hits
