"""Unicorn parity for thunk_pp_scrollblit (ProdPicker one-row scroll, group prodpicker_relayout).

Oracle = scaling_laws.prodpicker_scroll_blit / prodpicker_scroll_redraws.  The thunk is emulated from its SHIPPED
bytes (patches.yaml, resolved with the real symbol table) at its real cave VA, on top of the pristine .text, so the
blit arm runs the REAL Buffer_copy_4 0x5DFF00 (its lock / unlock helpers and the IntersectRect import are stubbed).

  * contract: both call sites' args -> Buffer_copy_4 entry (blit arm) or ProdPicker_draw_visible entry (redraw arm,
    ret + 7 args consumed, ecx = the picker), callee-saved registers untouched, for g 16..40 x colw x vis_rows x
    direction;
  * the Buffer_copy_4 column model the law relies on (exact iff w % 4 == 0) against the real bytes;
  * end-to-end: thunk -> real Buffer_copy_4 on a random canvas moves exactly the law's rect and nothing else.
Skips without unicorn / keystone / the pristine .bak.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import random
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn", reason="unicorn absent -- asm parity unverified")
pytest.importorskip("keystone", reason="keystone absent")

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_prodpicker as A  # noqa: E402

NAME = "thunk_pp_scrollblit"
SITES = {"ProdPicker_scroll_to.blit_up": (0x493D69, 0x493D6E, True),
         "ProdPicker_scroll_to.blit_down": (0x493E23, 0x493E28, False)}
G_VA, P_VA = 0x668740, 0x66879C               # g_popup_scale_num / g_stripe_period
IAT_INTERSECTRECT = 0x669338
LOCK, UNLOCK = 0x5E3373, 0x5E34A3
PICKER = 0x01000000                           # fake picker; its canvas Buffer at +0x444
STACK, SP0 = 0x00300000, 0x00308000
STUB = 0x00700000                             # IntersectRect stub (python does the work)
PIX = 0x02000000                              # canvas pixel plane
SEED = {"ebx": 0x1B1B1B1B, "esi": PICKER, "edi": PICKER + 0x444, "ebp": 0xB9B9B9B9}
REGS = {"ebx": UC_X86_REG_EBX, "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP}


def _load(name: str) -> tuple[int, bytes]:
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == name:
                base = cave["virtual_addr"]; base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]; off = int(off, 16) if isinstance(off, str) else off
                return base + off, ap.ByteTemplate(c["bytes"]).resolve(base + off, symtab)
    raise AssertionError(name + " not in patches.yaml")


def _sites():
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    return {s["id"]: s for s in doc["sites"] if s["id"] in SITES}, symtab


VA, CODE = _load(NAME)


def _bak_text():
    import pefile
    p = config.terranx_bak(required=False)
    if p is None or not p.is_file():
        pytest.skip("pristine .bak absent")
    pe = pefile.PE(str(p), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        if s.Name.startswith(b".text"):
            return base + s.VirtualAddress, s.get_data(), max(s.Misc_VirtualSize, s.SizeOfRawData)
    raise AssertionError("no .text")


# ---- bytes / sites --------------------------------------------------------------------------------------------------

def test_yaml_bytes_match_the_assembler():
    assert VA == A.PCAVE2 + A.SCROLLBLIT_OFF
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(A.asm_scrollblit(), addr=VA)
    blob = bytes(enc)
    for sent, val in ((A.G, G_VA), (A.PERIOD, P_VA)):
        blob = blob.replace(sent.to_bytes(4, "little"), val.to_bytes(4, "little"))
    assert CODE == blob
    assert len(CODE) <= A.SCROLLBLIT_END - A.SCROLLBLIT_OFF


def test_sites_redirect_both_copy4_calls_to_the_thunk():
    text_va, data, _ = _bak_text()
    sites, symtab = _sites()
    assert set(sites) == set(SITES)
    for sid, (va, nxt, _up) in SITES.items():
        s = sites[sid]
        orig = bytes.fromhex(s["original_bytes"].replace(" ", ""))
        assert orig[0] == 0xE8 and va + 5 + int.from_bytes(orig[1:], "little", signed=True) == A.COPY4, sid
        assert data[va - text_va: va - text_va + 5] == orig, sid
        new = ap.ByteTemplate(s["new_bytes"]).resolve(va, symtab)
        assert new[0] == 0xE8 and va + 5 + int.from_bytes(new[1:], "little", signed=True) == VA, sid
        assert s["group"] == "prodpicker_relayout"


# ---- emulator -------------------------------------------------------------------------------------------------------

class Emu:
    def __init__(self):
        text_va, data, vsize = _bak_text()
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc = uc
        uc.mem_map(text_va, (vsize + 0xFFF) & ~0xFFF)
        uc.mem_write(text_va, data)
        uc.mem_map(VA & ~0xFFF, 0x1000)
        uc.mem_write(VA, CODE)
        uc.mem_map(0x668000, 0x2000)                       # g cells + the IAT slot
        uc.mem_map(0x9B3000, 0x1000)                       # Buffer_copy_4's remainder scratch 0x9B39E4
        uc.mem_map(PICKER, 0x10000)
        uc.mem_map(STACK, 0x10000)
        uc.mem_map(STUB, 0x1000)
        uc.mem_map(PIX, 0x400000)
        uc.mem_write(STUB, bytes.fromhex("C20C00"))
        self.w32(IAT_INTERSECTRECT, STUB)
        uc.mem_write(LOCK, bytes.fromhex("B801000000C3"))  # lock: eax = 1, data ptr pre-set at +0x50
        uc.mem_write(UNLOCK, bytes.fromhex("C20400"))
        for site in SITES.values():                        # return sites: hlt
            uc.mem_write(site[1], b"\xF4")
        uc.hook_add(UC_HOOK_CODE, self._intersect, begin=STUB, end=STUB)
        self.stop_at = None
        self.hit = None
        uc.hook_add(UC_HOOK_CODE, self._entry, begin=A.COPY4, end=A.COPY4)
        uc.hook_add(UC_HOOK_CODE, self._entry, begin=A.DRAW_VISIBLE, end=A.DRAW_VISIBLE)

    def w32(self, a, v):
        self.uc.mem_write(a, (v & 0xFFFFFFFF).to_bytes(4, "little"))

    def r32(self, a, signed=False):
        return int.from_bytes(self.uc.mem_read(a, 4), "little", signed=signed)

    def _intersect(self, uc, addr, size, _):
        esp = uc.reg_read(UC_X86_REG_ESP)
        d, a, b = (self.r32(esp + 4 + 4 * i) for i in range(3))
        ra = [self.r32(a + 4 * i, True) for i in range(4)]
        rb = [self.r32(b + 4 * i, True) for i in range(4)]
        r = [max(ra[0], rb[0]), max(ra[1], rb[1]), min(ra[2], rb[2]), min(ra[3], rb[3])]
        ok = r[0] < r[2] and r[1] < r[3]
        for i in range(4):
            self.w32(d + 4 * i, r[i] if ok else 0)
        uc.reg_write(UC_X86_REG_EAX, int(ok))

    def _entry(self, uc, addr, size, _):
        if self.stop_at is None:
            return
        esp = uc.reg_read(UC_X86_REG_ESP)
        self.hit = (addr, esp, uc.reg_read(UC_X86_REG_ECX), [self.r32(esp + 4 * i, True) for i in range(8)],
                    {k: uc.reg_read(r) for k, r in REGS.items()})
        if self.stop_at == "entry":
            uc.emu_stop()

    def setup(self, g, cols, colw, pitch, vis_rows, canvas_w=0, canvas_h=0):
        self.w32(G_VA, g)
        self.w32(P_VA, SL.stripe_period(g) if g > 16 else 2)
        p = PICKER
        self.w32(p + 0xA810, cols)
        self.w32(p + 0xA814, vis_rows)
        self.w32(p + 0xA81C, colw)
        self.w32(p + 0xA820, pitch)
        buf = p + 0x444
        self.w32(buf + 0x54, PIX); self.w32(buf + 0x50, PIX); self.w32(buf + 0x58, 0); self.w32(buf + 0x6C, 0)
        self.w32(buf + 0x80, canvas_w); self.w32(buf + 0x84, -canvas_h); self.w32(buf + 0x4A8, canvas_w)
        for i, v in enumerate((0, 0, canvas_w, canvas_h)):
            self.w32(buf + 0x20 + 4 * i, v)

    def call(self, site_id, args, stop_at="entry"):
        """args = vanilla's 7 pushed Buffer_copy_4 args (src, sx, sy, dx, dy, w, h)."""
        uc = self.uc
        _va, ret, _ = SITES[site_id]
        self.w32(SP0, ret)
        for i, a in enumerate(args):
            self.w32(SP0 + 4 + 4 * i, a)
        uc.reg_write(UC_X86_REG_ESP, SP0)
        uc.reg_write(UC_X86_REG_ECX, PICKER + 0x444)
        for k, v in SEED.items():
            uc.reg_write(REGS[k], v)
        self.stop_at, self.hit = stop_at, None
        if stop_at == "entry":
            uc.emu_start(VA, 0, count=10_000)
        else:
            uc.emu_start(VA, ret, count=50_000_000)
            assert uc.reg_read(UC_X86_REG_EIP) == ret
            assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x1C       # E8 ret + RET 0x1C consumed
            for k, v in SEED.items():
                assert uc.reg_read(REGS[k]) == v, k
        return self.hit


def _vanilla_args(cols, colw, pitch, vis_rows, up):
    x, sy, _, dy, w, h = SL.prodpicker_scroll_blit(cols, colw, pitch, vis_rows, 16, up)
    return [PICKER + 0x444, x, sy, x, dy, w, h]


@pytest.fixture(scope="module")
def emu():
    return Emu()


GS = tuple(range(16, 41))


@pytest.mark.parametrize("g", GS)
def test_thunk_args_match_the_law(emu, g):
    win_w = SL.basewin_pt(758, g)
    pitch = SL.prodpicker_row_pitch(g)
    base = SL.prodpicker_col_w(win_w, g)
    for colw in (base, base - 1, base - 2, base - 3, base + 5):
        for vis_rows in (3, 4):
            for sid, (_va, ret, up) in SITES.items():
                emu.setup(g, 5, colw, pitch, vis_rows)
                args = _vanilla_args(5, colw, pitch, vis_rows, up)
                addr, esp, ecx, stack, regs = emu.call(sid, args)
                ctx = (g, colw, vis_rows, sid)
                assert regs == {k: SEED[k] for k in REGS}, ctx
                if SL.prodpicker_scroll_redraws(pitch, g):
                    assert addr == A.DRAW_VISIBLE, ctx
                    assert ecx == PICKER, ctx
                    assert esp == SP0 + 0x1C and stack[0] == ret, ctx        # args consumed, ret re-pushed
                else:
                    assert addr == A.COPY4, ctx
                    assert esp == SP0 and stack[0] == ret and ecx == PICKER + 0x444, ctx
                    law = SL.prodpicker_scroll_blit(5, colw, pitch, vis_rows, g, up)
                    assert tuple(stack[2:8]) == law and stack[1] == PICKER + 0x444, (ctx, stack, law)


def _canvas(emu, W, H, seed):
    img = random.Random(seed).randbytes(W * H)
    emu.uc.mem_write(PIX, img)
    return img


def _apply_model(img, W, sx, sy, dx, dy, w, h, cols=None):
    out = bytearray(img)
    src = [img[(sy + r) * W: (sy + r + 1) * W] for r in range(h)]
    xs = sorted(cols) if cols is not None else list(range(dx, dx + w))
    runs, a = [], 0                                    # contiguous column runs -> slice copies
    for i in range(1, len(xs) + 1):
        if i == len(xs) or xs[i] != xs[i - 1] + 1:
            runs.append((xs[a], xs[i - 1] + 1))
            a = i
    for r in range(h):
        row = (dy + r) * W
        for x0, x1 in runs:
            out[row + x0: row + x1] = src[r][x0 - dx + sx: x1 - dx + sx]
    return bytes(out)


@pytest.mark.parametrize("w", list(range(8, 24)) + [679, 1076, 1077, 1078, 1079])
@pytest.mark.parametrize("up", (True, False))
def test_copy4_selfblit_column_model(emu, w, up):
    """The law module's buffer_copy4_selfblit_columns against the REAL 0x5DFF00 bytes: every written column takes its
    own source column, the set is exact iff w % 4 == 0, and the stray columns sit <= 3 px past either end."""
    W, H, x, h = 1200, 60, 21, 20
    sy, dy = (4, 30) if up else (30, 4)
    emu.setup(16, 0, 0, 0, 0, W, H)
    img = _canvas(emu, W, H, w)
    uc = emu.uc
    ret = 0x493D6E
    emu.w32(SP0, ret)
    for i, a in enumerate((PICKER + 0x444, x, sy, x, dy, w, h)):
        emu.w32(SP0 + 4 + 4 * i, a)
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, PICKER + 0x444)
    emu.stop_at = None
    uc.emu_start(A.COPY4, ret, count=10_000_000)
    got = bytes(uc.mem_read(PIX, W * H))
    cols = SL.buffer_copy4_selfblit_columns(x, w)
    assert got == _apply_model(img, W, x, sy, x, dy, w, h, cols), w
    assert (cols == set(range(x, x + w))) == (w % 4 == 0)


@pytest.mark.parametrize("g", [g for g in GS if g > 16
                               and not SL.prodpicker_scroll_redraws(SL.prodpicker_row_pitch(g), g)])
@pytest.mark.parametrize("sid", list(SITES))
def test_end_to_end_blit_moves_exactly_the_law_rect(emu, g, sid):
    """thunk -> real Buffer_copy_4 on a random canvas of the picker's device size: the result equals the law's rect
    moved by exactly one pitch, every other pixel untouched (no stray column past the stroke-safe right edge)."""
    win_w, win_h = SL.basewin_pt(758, g), SL.basewin_pt(490, g)
    pitch = SL.prodpicker_row_pitch(g)
    colw = SL.prodpicker_col_w(win_w, g)
    up = SITES[sid][2]
    emu.setup(g, 5, colw, pitch, 4, win_w, win_h)
    img = _canvas(emu, win_w, win_h, g)
    emu.call(sid, _vanilla_args(5, colw, pitch, 4, up), stop_at=None)
    got = bytes(emu.uc.mem_read(PIX, win_w * win_h))
    law = SL.prodpicker_scroll_blit(5, colw, pitch, 4, g, up)
    assert got == _apply_model(img, win_w, *law), (g, sid)


@pytest.mark.parametrize("sid", list(SITES))
def test_native_passes_vanilla_through(emu, sid):
    """g = 16: Buffer_copy_4 gets vanilla's args verbatim (and the real copy runs to the return site)."""
    emu.setup(16, 5, 135, 108, 4, 758, 490)
    up = SITES[sid][2]
    args = _vanilla_args(5, 135, 108, 4, up)
    _addr, _esp, _ecx, stack, _regs = emu.call(sid, args)
    assert stack[1:8] == args
    img = _canvas(emu, 758, 490, 16)
    emu.call(sid, args, stop_at=None)
    got = bytes(emu.uc.mem_read(PIX, 758 * 490))
    x, sy, _, dy, w, h = args[1:]
    assert got == _apply_model(img, 758, x, sy, x, dy, w, h, SL.buffer_copy4_selfblit_columns(x, w))
