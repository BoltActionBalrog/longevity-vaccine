"""Unicorn parity for the font face/weight law helpers (assemble_fontlaw.py).

Oracle = scaling_laws.font_face_law / font_direct_law / font_law_slot_key.  Every helper is emulated
from its REAL assembled bytes at its REAL cave VA; find_font / Font_init are recording stubs
(find_font hands out a fake Font per (size, v); Font_init tags the slot with (name, size, style)).
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

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_fontlaw as AF  # noqa: E402

LAYOUT, _END = AF.assemble_all()
VA = {n: AF.PCAVE2 + LAYOUT[n][0] for n in LAYOUT}
R = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
     "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}
STACK, SP0 = 0x00300000, 0x00308000
RET_SITE = 0x00600100
POOL = 0x00710000               # fake pool: find_font(size, v) -> POOL + size*0x100 + v*0x28
REC = 0x00700000                # recorders
NAME_A, NAME_N = 0x00720000, 0x00720100
_ks = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(src, va=0):
    enc, _ = _ks.asm(src, va)
    return bytes(enc)


# find_font: count @REC, last (size, v) @REC+4/+8, returns the fake pool Font
FIND_FONT_STUB = asm(
    f"inc dword ptr [{REC:#x}]; mov eax, dword ptr [esp+4]; mov dword ptr [{REC + 4:#x}], eax;"
    f"mov ecx, dword ptr [esp+8]; mov dword ptr [{REC + 8:#x}], ecx;"
    f"shl eax, 8; imul ecx, ecx, 0x28; add eax, ecx; add eax, {POOL:#x}; ret")
# Font_init: count @REC+0x10, (this, name, size, style) @REC+0x14..; marks the Font (+8 = fake HFONT); RET 0xC
FONT_INIT_STUB = asm(
    f"inc dword ptr [{REC + 0x10:#x}]; mov dword ptr [{REC + 0x14:#x}], ecx;"
    f"mov eax, dword ptr [esp+4]; mov dword ptr [{REC + 0x18:#x}], eax;"
    f"mov eax, dword ptr [esp+8]; mov dword ptr [{REC + 0x1C:#x}], eax;"
    f"mov eax, dword ptr [esp+0xC]; mov dword ptr [{REC + 0x20:#x}], eax;"
    f"mov dword ptr [ecx+8], 0x1234; mov eax, 0; ret 0xC")


class Emu:
    def __init__(self, g=25):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        for base, size in ((AF.PCAVE2 + 0x2E000, 0x2000), (STACK, 0x10000), (0x668000, 0x1000),
                           (0x68F000, 0x1000), (0x691000, 0x1000), (0x618000, 0x1000), (0x588000, 0x1000),
                           (0x600000, 0x1000), (REC, 0x1000), (POOL, 0x10000), (NAME_A, 0x1000)):
            uc.mem_map(base, size)
        for name, (off, blob) in LAYOUT.items():
            uc.mem_write(AF.PCAVE2 + off, blob)
        uc.mem_write(AF.FONT_INIT, FONT_INIT_STUB)
        uc.mem_write(AF.FIND_FONT, FIND_FONT_STUB)
        uc.mem_write(RET_SITE, b"\xf4")
        for i, f in enumerate(SL.FONT_VARIANT_FLAGS):
            self.w32(AF.VFLAGS + 4 * i, f)
        self.w32(AF.NAME_A, NAME_A)
        self.w32(AF.NAME_N, NAME_N)
        self.set_g(g)

    def set_g(self, g):
        self.w32(AF.G, g)

    def w32(self, addr, v):
        self.uc.mem_write(addr, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, addr):
        return int.from_bytes(self.uc.mem_read(addr, 4), "little")

    def clear_rec(self):
        self.uc.mem_write(REC, bytes(0x40))

    def call(self, name, *args, regs=None):
        """cdecl call: push args right-to-left, return trap; -> eax.  Asserts esp balance + callee-saved regs."""
        uc = self.uc
        seed = {"ebx": 0x1B1B1B1B, "esi": 0x51515151, "edi": 0xD1D1D1D1, "ebp": 0xB9B9B9B9}
        seed.update(regs or {})
        self.w32(SP0, RET_SITE)
        for i, a in enumerate(args):
            self.w32(SP0 + 4 * (i + 1), a)
        uc.reg_write(UC_X86_REG_ESP, SP0)
        for k, v in seed.items():
            uc.reg_write(R[k], v)
        uc.emu_start(VA[name], 0, count=200_000)
        assert uc.reg_read(UC_X86_REG_EIP) == RET_SITE + 1, name
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4, f"{name}: esp not balanced (cdecl ret)"
        for k, v in seed.items():
            assert uc.reg_read(R[k]) == v, f"{name}: {k} clobbered"
        return uc.reg_read(UC_X86_REG_EAX)

    def find_fonts(self):
        return self.r32(REC), (self.r32(REC + 4), self.r32(REC + 8))

    def font_inits(self):
        return self.r32(REC + 0x10), (self.r32(REC + 0x14), self.r32(REC + 0x18), self.r32(REC + 0x1C), self.r32(REC + 0x20))


GS = (16, 18, 22, 25, 30, 40)
NAMES = {SL.FONT_NAME_ARIAL: NAME_A, SL.FONT_NAME_NARROW: NAME_N}
NON_SLOT_KEYS = ((20, 0), (13, 1), (24, 2), (36, 0))


def pool_font(size, v):
    return POOL + size * 0x100 + v * 0x28


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("S,v", SL.FONT_LAW_SLOT_KEYS + NON_SLOT_KEYS)
def test_t_ffn_matches_font_face_law(S, v, g):
    e = Emu(g)
    e.clear_rec()
    got = e.call("t_ffn", S, v)
    law = SL.font_face_law(S, v, g)
    nff, ff = e.find_fonts()
    nfi, fi = e.font_inits()
    idx = SL.font_law_slot_index(S, v)
    if law[0] == "pool" or idx is None:
        # the pool: (S, v) at g<=16, else (fl(S*g/16), v); no slot without a key entry
        want = (S, v) if g <= 16 else (SL.font_scaled_size(S, g), v)
        assert (nff, ff, nfi) == (1, want, 0), (S, v, g, law)
        assert got == pool_font(*want)
    else:
        _tag, name, n, style = law
        slot = AF.G_SLOTS + idx * AF.STRIDE
        assert (nff, nfi) == (0, 1), (S, v, g)
        assert fi == (slot, NAMES[name], n, style), (S, v, g, fi, law)
        assert got == slot
        assert e.r32(slot + 0x28) == g and e.r32(slot + 0x2C) == SL.font_law_slot_key(S, style, name == SL.FONT_NAME_NARROW)
        # idempotent at the same g: no second Font_init; a new g re-inits
        e.clear_rec()
        assert e.call("t_ffn", S, v) == slot and e.font_inits()[0] == 0 and e.find_fonts()[0] == 0
        g2 = 40 if g != 40 else 30
        e.set_g(g2)
        e.clear_rec()
        law2 = SL.font_face_law(S, v, g2)
        r = e.call("t_ffn", S, v)
        if law2[0] == "init":
            assert r == slot and e.font_inits() == (1, (slot, NAMES[law2[1]], law2[2], law2[3]))
        else:
            assert r == pool_font(law2[1], law2[2]) and e.font_inits()[0] == 0


@pytest.mark.parametrize("num", (16, 22, 25, 30, 45, 72))
def test_t_ffn_num_and_t_ffn_at_take_an_explicit_num(num):
    e = Emu(99)                      # g_popup_scale_num deliberately wrong: must not be read
    e.clear_rec()
    got = e.call("t_ffn_num", 12, 0, num)
    law = SL.font_face_law(12, 0, num)
    if num <= 16:
        assert law == ("pool", 12, 0) and got == pool_font(12, 0) and e.find_fonts() == (1, (12, 0))
    else:
        slot = AF.G_SLOTS + SL.font_law_slot_index(12, 0) * AF.STRIDE
        assert got == slot and e.font_inits() == (1, (slot, NAME_A, SL.font_scaled_size(12, num), 0))
    # the Monument plaque: its private slot, its own num, Arial regular at fl(12*num/16)
    e.clear_rec()
    got = e.call("t_ffn_at", AF.G_MONPLQ, 12, 0, num)
    assert got == AF.G_MONPLQ
    assert e.font_inits() == (1, (AF.G_MONPLQ, NAME_A, SL.font_scaled_size(12, num), 0))
    assert e.r32(AF.G_MONPLQ + 0x28) == num and e.r32(AF.G_MONPLQ + 0x2C) == SL.font_law_slot_key(12, 0, False)
    # a > 12 native on a private slot: Narrow + bold|variant, exact size (no pool snapping)
    e.clear_rec()
    got = e.call("t_ffn_at", AF.G_BWNAME, 32, 1, num)
    name, style = SL.font_pool_face(32, 1)
    assert got == AF.G_BWNAME and e.font_inits() == (1, (AF.G_BWNAME, NAMES[name], SL.font_scaled_size(32, num), style))
    assert e.r32(AF.G_BWNAME + 0x2C) == SL.font_law_slot_key(32, style, True)


@pytest.mark.parametrize("g", GS)
def test_t_fdirect_a14b_is_arial_14_bold_scaled(g):
    e = Emu(g)
    e.clear_rec()
    got = e.call("t_fdirect_a14b")
    name, size, style = SL.font_direct_law(14, 1, g)
    assert got == AF.G_A14B and e.font_inits() == (1, (AF.G_A14B, NAMES[name], size, style)) and e.find_fonts()[0] == 0
    assert e.r32(AF.G_A14B + 0x28) == g and e.r32(AF.G_A14B + 0x2C) == SL.font_law_slot_key(14, 1, False)
    e.clear_rec()
    assert e.call("t_fdirect_a14b") == AF.G_A14B and e.font_inits()[0] == 0        # idempotent
    # t_fdirect_at with an explicit num on the HOF/Monument button slots
    for slot, num in ((AF.G_HOFBTN, 45), (AF.G_MONBTN, 22)):
        e.clear_rec()
        assert e.call("t_fdirect_at", slot, 14, 1, num) == slot
        assert e.font_inits() == (1, (slot, NAME_A, SL.font_scaled_size(14, num), 1))


def test_slot_key_table_matches_the_law():
    for i, (S, v) in enumerate(SL.FONT_LAW_SLOT_KEYS):
        assert AF.keys_bytes()[4 * i:4 * i + 4] == (S | (v << 8)).to_bytes(4, "little")
    assert AF.NSLOT == len(SL.FONT_LAW_SLOT_KEYS) and AF.STRIDE == SL.FONT_LAW_SLOT_STRIDE
    # every <=12 key the patch set scales has a slot; every >12 key that leaves the 40-px pool at 4K has one
    for S, v in ((10, 0), (11, 0), (12, 0), (12, 1), (12, 2), (26, 0), (18, 2), (22, 0), (32, 0), (14, 0), (14, 1), (14, 2)):
        assert SL.font_law_slot_index(S, v) is not None, (S, v)


# ---- SocialWin label fit (t_se_labelfit @ SocialWin_build.set_modal) ------------------------------
# v3: SocialWin_build is MODAL (its tail `call [vtbl+0xE4]` = Win_set_modal returns only when the screen
# closes), so the fit hooks that call: E8-entered with ecx = SocialWin, eax = its vtbl and Win_set_modal's
# 3 args on the stack; fits + repaints; tail-jumps into [vtbl+0xE4] (RET 0xC pops the args).
SE_TEXT = 0x00730000          # fake label strings + stubs
SE_REC = REC + 0x100          # Win_set_modal recorder: count, this, arg0, arg1, arg2
SE_VTBL = 0x0066DAA4          # SocialWin vtable (real VA; [+0xE4] = Win_set_modal, [+0xF8] = GraphicWin_redraw)
SE_MODAL_ARGS = (0, 0x5398E0, 0x7AE820)     # what the build pushes (push MainWin / push pop_wait / push 0)
SE_SEED = {"ebx": 0x1B1B1B1B, "esi": 0x51515151, "edi": 0xD1D1D1D1, "ebp": 0xB9B9B9B9}


class SeEmu(Emu):
    def __init__(self, g=22):
        super().__init__(g)
        uc = self.uc
        for base, size in ((AF.SOCIALWIN & ~0xFFF, 0x30000), (AF.BUFFER_TEXT_WIDTH & ~0xFFF, 0x1000),
                           (SE_VTBL & ~0xFFF, 0x1000), (SE_TEXT, 0x2000)):
            try:
                uc.mem_map(base, size)
            except Exception:  # noqa: BLE001
                pass
        # Buffer_text_width stub (this = the button canvas): width = [[canvas+0x52C] + 0xC] * 10 (one "worst label"
        # width per size), clobbers ecx/edx like the real one; the Font_init stub stores the size at +0xC so the
        # measure follows the re-init.  vtbl+0xF8 (redraw) = a recorder at SE_TEXT+0x800 counting per button.
        uc.mem_write(AF.BUFFER_TEXT_WIDTH, asm("mov eax, dword ptr [ecx+0x52C]; mov eax, dword ptr [eax+0xC]; imul eax, eax, 10; mov ecx, 0xBAD; mov edx, 0xBAD; ret 4"))
        uc.mem_write(SE_TEXT + 0x800, asm(f"inc dword ptr [{SE_TEXT + 0x900:#x}]; mov eax, dword ptr [{SE_TEXT + 0x900:#x}]; mov dword ptr [{SE_TEXT + 0x904:#x}+eax*4], ecx; mov ecx, 0xBAD; ret"))
        self.w32(SE_TEXT + 0x400 + 0xF8, SE_TEXT + 0x800)      # the buttons' fake vtbl @SE_TEXT+0x400
        # Win_set_modal stub (thiscall RET 0xC): records this + its 3 args, clobbers eax/ecx/edx, returns 0x55
        uc.mem_write(SE_TEXT + 0xC00, asm(
            f"inc dword ptr [{SE_REC:#x}]; mov dword ptr [{SE_REC + 4:#x}], ecx;"
            f"mov eax, dword ptr [esp+4]; mov dword ptr [{SE_REC + 8:#x}], eax;"
            f"mov eax, dword ptr [esp+8]; mov dword ptr [{SE_REC + 0xC:#x}], eax;"
            f"mov eax, dword ptr [esp+0xC]; mov dword ptr [{SE_REC + 0x10:#x}], eax;"
            f"mov ecx, 0xBAD; mov edx, 0xBAD; mov eax, 0x55; ret 0xC"))
        self.w32(SE_VTBL + 0xE4, SE_TEXT + 0xC00)
        self.w32(AF.SOCIALWIN, SE_VTBL)
        uc.mem_write(AF.FONT_INIT, asm(
            f"inc dword ptr [{REC + 0x10:#x}]; mov dword ptr [{REC + 0x14:#x}], ecx;"
            f"mov eax, dword ptr [esp+4]; mov dword ptr [{REC + 0x18:#x}], eax;"
            f"mov eax, dword ptr [esp+8]; mov dword ptr [{REC + 0x1C:#x}], eax; mov dword ptr [ecx+0xC], eax;"
            f"mov eax, dword ptr [esp+0xC]; mov dword ptr [{REC + 0x20:#x}], eax;"
            f"mov dword ptr [ecx+8], 0x1234; mov eax, 0; ret 0xC"))
        uc.mem_write(SE_TEXT, b"THOUGHT CONTROL\0")

    def seed_buttons(self, start_size, widths):
        """widths: per-button available widths (R-L); every button gets the label Font + a label."""
        uc = self.uc
        self.w32(AF.SE_FONT1 + 0xC, start_size)
        uc.mem_write(AF.SE_BTN0, bytes(AF.SE_BTN_N * AF.SE_BTN_STRIDE))
        uc.mem_write(SE_TEXT + 0x900, bytes(0x200))
        uc.mem_write(SE_REC, bytes(0x20))
        for i in range(AF.SE_BTN_N):
            b = AF.SE_BTN0 + i * AF.SE_BTN_STRIDE
            self.w32(b, SE_TEXT + 0x400)                        # vtbl
            if i < len(widths):
                self.w32(b + 0x970, AF.SE_FONT1)
                self.w32(b + 0xA7C, SE_TEXT)
                self.w32(b + 0x474, 5)
                self.w32(b + 0x47C, 5 + widths[i])
            else:                                   # other font / no label: never measured
                self.w32(b + 0x970, 0x7D3948)
                self.w32(b + 0xA7C, SE_TEXT if i % 2 else 0)
                self.w32(b + 0x474, 0)
                self.w32(b + 0x47C, 20)             # tiny: would force a shrink if it were measured

    def run_site(self):
        """Enter t_se_labelfit exactly as the patched `call` at SocialWin_build.set_modal does; assert the
        Win_set_modal contract held (entered once, this + args intact, RET 0xC balance, callee-saved regs)."""
        uc = self.uc
        self.w32(SP0, RET_SITE)
        for i, a in enumerate(SE_MODAL_ARGS):
            self.w32(SP0 + 4 + 4 * i, a)
        uc.reg_write(UC_X86_REG_ESP, SP0)
        uc.reg_write(UC_X86_REG_ECX, AF.SOCIALWIN)
        uc.reg_write(UC_X86_REG_EAX, SE_VTBL)
        for k, v in SE_SEED.items():
            uc.reg_write(R[k], v)
        uc.emu_start(VA["t_se_labelfit"], 0, count=2_000_000)
        assert uc.reg_read(UC_X86_REG_EIP) == RET_SITE + 1
        assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 4 * len(SE_MODAL_ARGS)   # Win_set_modal's RET 0xC
        assert uc.reg_read(UC_X86_REG_EAX) == 0x55                                # its return, untouched
        for k, v in SE_SEED.items():
            assert uc.reg_read(R[k]) == v, k
        assert [self.r32(SE_REC + 4 * k) for k in range(5)] == [1, AF.SOCIALWIN, *SE_MODAL_ARGS]


@pytest.mark.parametrize("g", (16, 22, 25, 40))
@pytest.mark.parametrize("over", (0, 1, 2, 5))
def test_se_labelfit_steps_the_label_font_down_until_every_label_fits(g, over):
    e = SeEmu(g)
    e.clear_rec()
    start = SL.se_font_size(14, g)
    # button widths: the worst button allows (start - over) * 10 px + slack -> the law shrinks by `over`
    fits_w = (start - over) * 10 + AF.SE_LABEL_SLACK
    e.seed_buttons(start, [fits_w + 40, fits_w, fits_w + 3])
    e.run_site()
    want = SL.se_label_fit(g, lambda s: s * 10 <= fits_w - AF.SE_LABEL_SLACK)
    n_fi, fi = e.font_inits()
    redraws = e.r32(SE_TEXT + 0x900)
    if g <= 16:
        assert n_fi == 0 and want == 14 and redraws == 0
    else:
        assert want == start - over
        assert n_fi == over and e.r32(AF.SE_FONT1 + 0xC) == want
        if over:
            assert fi == (AF.SE_FONT1, NAME_A, want, 1)              # the last re-init: Arial, bold, the fitted size
            # every measured button (label font + label) repainted once, in order, BEFORE the modal; the others never
            assert redraws == 3 and [e.r32(SE_TEXT + 0x904 + 4 * k) for k in (1, 2, 3)] == [AF.SE_BTN0 + i * AF.SE_BTN_STRIDE for i in range(3)]
        else:
            assert redraws == 0


def test_se_labelfit_stops_at_the_minimum_size():
    e = SeEmu(40)
    e.clear_rec()
    e.seed_buttons(SL.se_font_size(14, 40), [AF.SE_LABEL_SLACK + 1])   # nothing fits
    e.run_site()
    assert e.r32(AF.SE_FONT1 + 0xC) == AF.SE_LABEL_MIN == SL.SE_LABEL_FONT_MIN
    assert SL.se_label_fit(40, lambda s: False) == AF.SE_LABEL_MIN


def test_se_labelfit_site_is_the_builds_win_set_modal_call():
    """The site sits on the build's own `call [vtbl+0xE4]` (pristine bytes), the vtable slots the thunk
    tail-jumps / repaints through are Win_set_modal / GraphicWin_redraw, and the two SocialWin_build
    callers are back on thunk_se_enter (the v1/v2 ret-swap wrapper is gone)."""
    import pefile
    import config
    import assemble_se as SE
    assert AF.SE_SET_MODAL_SITE == SE.SET_MODAL_SITE == 0x4B3C4A and AF.SE_VT_MODAL == 0xE4 and AF.SE_VT_REDRAW == 0xF8
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    assert pe.get_data(AF.SE_SET_MODAL_SITE - base, 6) == bytes.fromhex("FF90E4000000")
    assert int.from_bytes(pe.get_data(SE_VTBL + 0xE4 - base, 4), "little") == 0x5EE190     # Win_set_modal
    assert int.from_bytes(pe.get_data(SE_VTBL + 0xF8 - base, 4), "little") == 0x5D5A70     # GraphicWin_redraw
    yaml = (pathlib.Path(__file__).resolve().parents[1] / "patches" / "patches.yaml").read_text(encoding="utf-8")
    yaml = yaml.replace("\r\n", "\n")
    blk = yaml[yaml.index("  - id: SocialWin_build.set_modal"):]
    blk = blk[:blk.index("\n  - id: ")]
    assert "virtual_addr: 0x004b3c4a" in blk and "length: 6" in blk
    assert 'original_bytes: "FF 90 E4 00 00 00"' in blk and 'new_bytes:      "E8 {rel32:t_se_labelfit} 90"' in blk
    for cid in ("caller_a", "caller_b"):
        b = yaml[yaml.index(f"  - id: SocialWin_build.{cid}"):]
        b = b[:b.index("\n  - id: ")]
        assert 'new_bytes:      "E8 {rel32:thunk_se_enter}"' in b, cid
    for gone in ("  t_se_enter2:", "  g_se_ret2:", "- id: t_se_enter2", "{rel32:t_se_enter2}", "{abs32:g_se_ret2}"):
        assert gone not in yaml, gone                       # symbol / content / placeholder: only the MD5 history may name them
    assert "      - SocialWin_build.set_modal\n" in yaml
