"""Unicorn parity of the W5B helpers on the SHIPPED bytes (2026-10-25 wave-5 W5B; src scripts/assemble_council_mirror.py):

  t_cw_s1        == scaling_laws.council_rail_mirror_sum for every g 17..64 and every council canvas width the image
                   can make (dp(0x32C)) plus a band around it; every register but eax kept;
  t_cw_mirror    (v2: the weighted run, g_cw_wts / g_cw_mstate) the seeds chain E8 @0x427784 -> t_cw_rowsym ->
                   thunk_cw_seeds -> t_cw_mirror -> Font_init, run on the
                   real CouncilWin static: the seven-column sets == scaling_laws.council_column_rects (g 16..64), the
                   banner / params / the rest of the window untouched by the mirror pass, every register and the call's
                   stack as they came, Font_init reached;
  t_cw_backdrop  the repaint's d690 rect (dp(0x17), 0, W - 0x37, H + 1) -> the renderer (thunk_box_thick_devfill, via
                   t_cw_hodf) sees council_drawn(council_backdrop_rect) and the repaint's rect holds
                   council_backdrop_rect afterwards (the d5a0 ring is built from it); g <= 16 a tail jump to
                   Buffer_box_sprite with the rect untouched;
  t_cw_hodf / t_cw_chiphalf  the renderer sees (L, T, R-1, B-1) at g > 16, the caller's rect at g <= 16 (tail jump); the
                   rect restored, ebx / esi / edi / ebp kept, RET 8;
  W7B (2026-10-25 wave-7):
  t_cw_bd2       t_cw_backdrop's rect with B = H + K (council_backdrop_rect v3), then t_cw_clipdraw with t_cw_hodf;
  t_cw_clipdraw  g <= 16, or the rect's B within the canvas: a tail jump to the renderer in eax (the stack as it came);
                 g > 16 and B > |H| (either sign of the Buffer's height): Buffer_ctor / Buffer_resize(W, B) /
                 Buffer_fill_2(9) on ONE stack scratch below the saved registers, the renderer on it with the caller's
                 rect / params, Buffer_draw_2(canvas, 9, 0, 0, 1, 1) from it, Buffer_dtor -- in that order, nothing
                 else; RET 8, rect untouched, ebx / esi / edi / ebp kept (engine calls stubbed: the order and the args
                 are the contract; the pixels are test_scaling_council_mirror's);
  t_cw_ring2     the same with t_bm_ho_hf;
  t_cw_logox     the logo's x arg == council_logo_x minus thunk_cw_logo's own (cw - dp(cw)) >> 1, every column width
                 and logo canvas, then thunk_cw_logo with the call's stack; g <= 16 untouched;
  and the yaml bytes (every placeholder resolved by the patcher) == the assembler's template at its pinned offset inside
  the W5B region 0x3D000..0x3DFFF; the nine sites call the helpers they are meant to.

All on the conftest `baked_exe` bytes (sections mapped into one Unicorn per module), renderers replaced by a recording
stub.  Cheap: no boot.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_council_mirror as CM  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
CWIN = 0x6FEC80
FONT_INIT = 0x618F40
BOX_SPRITE = 0x5E2DD3
STACK = 0x10000000
SP0 = STACK + 0x80000
TRAP = STACK + 0x100        # return address of the emulated CALL (hlt)
REC = STACK + 0x1000        # what the renderer stub saw
RECT = STACK + 0x2000
BUF = STACK + 0x3000        # a stand-in canvas Buffer: only +0x80 (the window canvas width) is read
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
        UC_X86_REG_EBP)
OUTER, INNER = 0xBF4, 0xC04


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def img(baked_exe):
    data = Path(baked_exe).read_bytes()
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for sct in pe.sections:
        va = ib + sct.VirtualAddress
        mu.mem_map(va, (max(sct.Misc_VirtualSize, sct.SizeOfRawData) + 0xFFF) & ~0xFFF)
        mu.mem_write(va, sct.get_data())
    mu.mem_map(STACK, 0x100000)
    mu.mem_write(TRAP, b"\xF4")
    return mu


def r32(mu, a):
    return struct.unpack("<i", bytes(mu.mem_read(a, 4)))[0]


def w32(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


def rect(mu, a):
    return tuple(r32(mu, a + 4 * i) for i in range(4))


def _stub_recorder(mu, va, ret=8):
    """At the renderer VA: record ecx, the return address, the rect pointer, the params arg and the rect's four dwords
    as the renderer sees them, then RET `ret`.  Returns the bytes it overwrote."""
    from keystone import KS_ARCH_X86, KS_MODE_32, Ks
    src = f"""
        mov dword ptr [{REC:#x}], ecx
        mov eax, dword ptr [esp]
        mov dword ptr [{REC + 4:#x}], eax
        mov eax, dword ptr [esp+4]
        mov dword ptr [{REC + 8:#x}], eax
        mov eax, dword ptr [esp+8]
        mov dword ptr [{REC + 12:#x}], eax
        mov eax, dword ptr [esp+4]
        mov edx, dword ptr [eax]
        mov dword ptr [{REC + 16:#x}], edx
        mov edx, dword ptr [eax+4]
        mov dword ptr [{REC + 20:#x}], edx
        mov edx, dword ptr [eax+8]
        mov dword ptr [{REC + 24:#x}], edx
        mov edx, dword ptr [eax+12]
        mov dword ptr [{REC + 28:#x}], edx
        mov dword ptr [{REC + 32:#x}], 1
        ret {ret}
    """
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)[0])
    old = bytes(mu.mem_read(va, len(b)))
    mu.mem_write(va, b)
    return old


# ---------------------------------------------------------------- yaml == assembler, placement, sites
@pytest.mark.parametrize("name", list(CM.HELPERS))
def test_yaml_bytes_are_the_assembler(img, symtab, name):
    off, end = CM.HELPERS[name]
    va = CM.PCAVE2 + off
    assert symtab[name] == va and CM.REGION[0] <= off < end <= CM.REGION[1], "pinned in the W5B region"
    want = ap.ByteTemplate(CM.template(name)).resolve(va, symtab)
    assert bytes(img.mem_read(va, len(want))) == want
    nxt = min((v for n, v in symtab.items() if va < v < CM.PCAVE2 + end and n != name), default=None)
    assert nxt is None, f"{name}'s slot holds another symbol at {nxt:#x}"


def test_weights_cell_is_the_law(img, symtab):
    """g_cw_wts == the cumulative vanilla channel weights (scaling_laws.council_channel_weights), outer then inner."""
    off, size = CM.DATA["g_cw_wts"]
    assert symtab["g_cw_wts"] == CM.PCAVE2 + off and symtab["g_cw_mstate"] == CM.PCAVE2 + CM.DATA["g_cw_mstate"][0]
    assert bytes(img.mem_read(CM.PCAVE2 + off, size)) == CM.wts_bytes()
    words = struct.unpack("<8I", CM.wts_bytes())
    assert words == (2, 4, 6, 8, 4, 9, 14, 19)


def test_sites_call_the_helpers(img, symtab):
    for _sid, va, helper, _was in CM.SITES:
        b = bytes(img.mem_read(va, 5))
        assert b[0] == 0xE8 and va + 5 + struct.unpack("<i", b[1:])[0] == symtab[helper], hex(va)
    # thunk_cw_seeds' tail: push t_cw_mirror; ret (was jmp Font_init); t_cw_mirror's: push Font_init; ret
    seeds = bytes(img.mem_read(symtab["thunk_cw_seeds"], 0x200))
    assert seeds.count(b"\x68" + struct.pack("<I", symtab["t_cw_mirror"]) + b"\xC3") == 1
    assert b"\xE9" + struct.pack("<i", FONT_INIT - (symtab["thunk_cw_seeds"] + seeds.index(b"\x68" + struct.pack(
        "<I", symtab["t_cw_mirror"])) + 5)) not in seeds
    mir = bytes(img.mem_read(symtab["t_cw_mirror"], 0x90))
    assert b"\x68" + struct.pack("<I", FONT_INIT) + b"\xC3" in mir


# ---------------------------------------------------------------- t_cw_s1
@pytest.mark.parametrize("g", range(17, 65))
def test_s1_is_the_law(img, symtab, g):
    mu, fn = img, symtab["t_cw_s1"]
    w32(mu, G_VA, g)
    wd = SL.dp(SL.COUNCIL_W, g)
    for W in range(wd - 40, wd + 41):
        for r in REGS:
            mu.reg_write(r, 0x5A5A0000 + r)
        mu.reg_write(UC_X86_REG_EAX, W)
        w32(mu, SP0 - 4, TRAP)
        mu.reg_write(UC_X86_REG_ESP, SP0 - 4)
        mu.emu_start(fn, TRAP, count=100)
        assert mu.reg_read(UC_X86_REG_EAX) == SL.council_rail_mirror_sum(W, g), (g, W)
        assert mu.reg_read(UC_X86_REG_ESP) == SP0
        for r in REGS[1:]:
            assert mu.reg_read(r) == 0x5A5A0000 + r


# ---------------------------------------------------------------- the seeds chain through t_cw_mirror
def _write_engine_seeds(mu):
    """What CouncilWin_exec writes natively before the E8 @0x427784 (the vanilla table, council_seed_rects(16))."""
    s = SL.council_seed_rects(16)
    for k, base in (("outer", OUTER), ("inner", INNER)):
        for c, rc in enumerate(s[k]):
            mu.mem_write(CWIN + base + 0x20 * c, struct.pack("<4i", *rc))
    mu.mem_write(CWIN + 0xBA4, struct.pack("<4i", *s["banner"]))
    w32(mu, CWIN + 0xBC4, s["params"][0])
    w32(mu, CWIN + 0xBCC, s["params"][1])
    w32(mu, CWIN + 0xBD0, s["params"][2])


@pytest.mark.parametrize("g", range(16, 65))
def test_seed_chain_is_the_law(img, symtab, g):
    mu = img
    old = bytes(mu.mem_read(FONT_INIT, 1))
    mu.mem_write(FONT_INIT, b"\xF4")
    try:
        w32(mu, G_VA, g)
        _write_engine_seeds(mu)
        # t_cw_rowsym reads the button row (VOTE R vs third[2] R): an unscaled row (remainder outside 0..2) is left alone
        w32(mu, CWIN + 0xD0C, 100)
        w32(mu, CWIN + 0xCFC, 0)
        before = bytes(mu.mem_read(CWIN, 0xE00))
        for r in REGS:
            mu.reg_write(r, 0x5A5A0000 + r)
        mu.reg_write(UC_X86_REG_ESI, CWIN)
        esp = SP0 - 12
        mu.mem_write(esp, struct.pack("<III", TRAP, 0x11, 0x22))          # the call's return + Font_init's args
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(symtab["t_cw_rowsym"], FONT_INIT, count=20000)
        assert mu.reg_read(UC_X86_REG_ESP) == esp and bytes(mu.mem_read(esp, 12)) == struct.pack("<III", TRAP, 0x11, 0x22)
        for r in REGS:
            want = CWIN if r == UC_X86_REG_ESI else 0x5A5A0000 + r
            assert mu.reg_read(r) == want, r
        law = SL.council_column_rects(g)
        for k, base in (("outer", OUTER), ("inner", INNER)):
            got = [rect(mu, CWIN + base + 0x20 * c) for c in range(7)]
            assert got == law[k], (g, k, got)
        assert rect(mu, CWIN + 0xBA4) == law["banner"]
        if g <= 16:
            assert bytes(mu.mem_read(CWIN, 0xE00)) == before, "native no-op"
        else:
            s1 = law["s1"]
            for k in ("outer", "inner"):
                cols = law[k]
                for c in range(7):
                    assert cols[c][0] + cols[6 - c][2] == s1, "mirrored about the rails"
    finally:
        mu.mem_write(FONT_INIT, old)


# ---------------------------------------------------------------- t_cw_backdrop (W5B, no site since W7B) / t_cw_bd2
@pytest.mark.parametrize("g", (1, 15, 16) + tuple(range(17, 65)))
@pytest.mark.parametrize("name", ("t_cw_backdrop", "t_cw_bd2"))
def test_backdrop_is_the_law(img, symtab, g, name):
    """t_cw_bd2 on a canvas taller than its rect (t_cw_clipdraw's direct path: its scratch path is test_clipdraw_*):
    the renderer sees council_drawn(council_backdrop_rect v3) and the rect holds the law; t_cw_backdrop (W5B, still
    assembled) the same L / R with the repaint's B = H + 1."""
    mu, fn = img, symtab[name]
    renderer = symtab["thunk_box_thick_devfill"] if g > 16 else BOX_SPRITE
    old = _stub_recorder(mu, renderer)
    try:
        W = SL.dp(SL.COUNCIL_W, g)
        H = min(SL.dp(SL.COUNCIL_H_CAP, g), 2000)
        rc = (SL.dp(SL.COUNCIL_BACKDROP_L, g), 0, W - SL.COUNCIL_BACKDROP_RSUB, H + 1)   # the repaint's rect
        mu.mem_write(RECT, struct.pack("<4i", *rc))
        w32(mu, BUF + 0x80, W)
        w32(mu, BUF + 0x84, -(H + 64))
        mu.mem_write(REC, bytes(64))
        w32(mu, G_VA, g)
        for r in REGS:
            mu.reg_write(r, 0x5A5A0000 + r)
        mu.reg_write(UC_X86_REG_ECX, BUF)
        esp = SP0 - 12
        mu.mem_write(esp, struct.pack("<III", TRAP, RECT, 0x78D690))
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(fn, TRAP, count=400)
        assert r32(mu, REC + 32) == 1 and r32(mu, REC) == BUF and r32(mu, REC + 8) == RECT and r32(mu, REC + 12) == 0x78D690
        seen = tuple(r32(mu, REC + 16 + 4 * i) for i in range(4))
        law = SL.council_backdrop_rect(W, H, g)
        if name == "t_cw_backdrop" and g > 16:
            law = law[:3] + (H + 1,)
        if g > 16:
            assert seen == SL.council_drawn(law, g), (g, seen)
            assert rect(mu, RECT) == law, "the repaint's rect holds the law (the ring is built from it)"
        else:
            assert seen == rc and rect(mu, RECT) == rc and r32(mu, REC + 4) == TRAP, "a tail jump, rect untouched"
        assert mu.reg_read(UC_X86_REG_ESP) == SP0, "RET 8"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == 0x5A5A0000 + r
    finally:
        mu.mem_write(renderer, old)


# ---------------------------------------------------------------- W7B: t_cw_clipdraw / t_cw_ring2 / t_cw_bd2
RENDER = STACK + 0x7000     # a stand-in renderer (hooked; never executed)
PARAMS = 0x78D5A0
ENGINE = (("Buffer_ctor", 0), ("Buffer_resize", 8), ("Buffer_fill_2", 4), ("Buffer_draw_2", 0x18), ("Buffer_dtor", 0))


def _run_stubbed(mu, symtab, fn, renderers, eax=0):
    """Run `fn` (Buffer_box_sprite's contract: ecx = BUF, [esp+4] = RECT, [esp+8] = PARAMS) with the five engine Buffer
    calls and `renderers` ({va: name}, RET 8) hooked: each logs (name, ecx, args, return address, esp at entry, the
    rect's dwords) and returns.  Returns the log."""
    from unicorn import UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_EIP
    stubs = {symtab[n]: (n, k) for n, k in ENGINE}
    stubs.update({va: (n, 8) for va, n in renderers.items()})
    log = []

    def hook(uc, addr, size, ud):
        if addr not in stubs:
            return
        n, k = stubs[addr]
        esp = uc.reg_read(UC_X86_REG_ESP)
        args = tuple(r32(uc, esp + 4 + 4 * i) for i in range(k // 4))
        log.append((n, uc.reg_read(UC_X86_REG_ECX), args, r32(uc, esp) & 0xFFFFFFFF, esp,
                    rect(uc, args[0]) if n in renderers.values() else None))
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + k)
        uc.reg_write(UC_X86_REG_EIP, r32(uc, esp) & 0xFFFFFFFF)
    hs = [mu.hook_add(UC_HOOK_CODE, hook, begin=va, end=va) for va in stubs]
    mu.ctl_flush_tb()           # a renderer an earlier test ran is a cached block: the new hooks would not fire
    try:
        mu.mem_write(RENDER, b"\xF4")
        for r in REGS:
            mu.reg_write(r, 0x5A5A0000 + r)
        mu.reg_write(UC_X86_REG_EAX, eax)
        mu.reg_write(UC_X86_REG_ECX, BUF)
        esp = SP0 - 12
        mu.mem_write(esp, struct.pack("<III", TRAP, RECT, PARAMS))
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(fn, TRAP, count=2000)
    finally:
        for h in hs:
            mu.hook_del(h)
    assert mu.reg_read(UC_X86_REG_ESP) == SP0, "RET 8"
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert mu.reg_read(r) == 0x5A5A0000 + r
    return log


def _check_scratch(log, fn_lo, W, B, rname, rc):
    """The scratch path's contract: the five engine calls around the renderer, on one stack Buffer below the saved
    registers (0x588 bytes, Buffer_ctor's size), the canvas BUF only as Buffer_draw_2's dest."""
    assert [e[0] for e in log] == ["Buffer_ctor", "Buffer_resize", "Buffer_fill_2", rname, "Buffer_draw_2",
                                   "Buffer_dtor"], log
    s = log[0][1]
    assert all(e[1] == s for e in log), "one scratch Buffer"
    assert s + 0x588 <= SP0 - 12 - 4 * 4 and all(e[4] < s for e in log), "on the stack, below the saved registers"
    assert log[1][2] == (W, B) and log[2][2] == (9,)
    assert log[3][2] == (RECT, PARAMS) and log[3][5] == rc, "the renderer sees the caller's rect, unclamped"
    assert log[4][2] == (BUF, 9, 0, 0, 1, 1), "keyed 1:1 at the origin onto the canvas"
    assert all(fn_lo <= e[3] < fn_lo + 0x100 for e in log), "called from the helper"


@pytest.mark.parametrize("g", (1, 15, 16, 17, 18, 22, 25, 30, 40, 48, 64))
@pytest.mark.parametrize("hsign", (-1, 1))
@pytest.mark.parametrize("below", (False, True))
def test_clipdraw_is_the_law(img, symtab, g, hsign, below):
    mu, fn = img, symtab["t_cw_clipdraw"]
    w32(mu, G_VA, g)
    W, H = SL.dp(SL.COUNCIL_W, g), SL.dp(395, g)
    K = SL.stroke_width(g)
    rc = (57, 0, W - 60, H + K if below else H)               # B == |H| still fits (half-open)
    mu.mem_write(RECT, struct.pack("<4i", *rc))
    w32(mu, BUF + 0x80, W)
    w32(mu, BUF + 0x84, hsign * H)
    log = _run_stubbed(mu, symtab, fn, {RENDER: "render"}, eax=RENDER)
    if g > 16 and below:
        _check_scratch(log, fn, W, rc[3], "render", rc)
        assert SL.council_frame_clip(rc, H) == rc[:3] + (H,), "the canvas keeps rows [T, H) of the whole frame"
    else:
        assert [e[0] for e in log] == ["render"] and log[0][1] == BUF and log[0][2] == (RECT, PARAMS), log
        assert log[0][3] == TRAP and log[0][4] == SP0 - 12, "a tail jump: the call's stack as it came"
    assert rect(mu, RECT) == rc


@pytest.mark.parametrize("g", (17, 25, 40, 64))
@pytest.mark.parametrize("name, renderer", (("t_cw_ring2", "t_bm_ho_hf"), ("t_cw_bd2", "t_cw_hodf")))
def test_clip_sites_use_clipdraw(img, symtab, g, name, renderer):
    """The two council sites' helpers reach t_cw_clipdraw with their renderer: below the canvas the scratch path with
    the ring's rect / the backdrop's law rect (B = H + K)."""
    mu, fn = img, symtab[name]
    w32(mu, G_VA, g)
    W, H = SL.dp(SL.COUNCIL_W, g), SL.dp(395, g)
    if name == "t_cw_ring2":
        rc = SL.council_ring_rect(W, H, g)
        want = rc
    else:
        rc = (SL.dp(SL.COUNCIL_BACKDROP_L, g), 0, W - SL.COUNCIL_BACKDROP_RSUB, H + 1)
        want = SL.council_backdrop_rect(W, H, g)
    mu.mem_write(RECT, struct.pack("<4i", *rc))
    w32(mu, BUF + 0x80, W)
    w32(mu, BUF + 0x84, -H)
    log = _run_stubbed(mu, symtab, fn, {symtab[renderer]: renderer})
    _check_scratch(log, symtab["t_cw_clipdraw"], W, want[3], renderer, want)
    assert rect(mu, RECT) == want


# ---------------------------------------------------------------- t_cw_hodf / t_cw_chiphalf
@pytest.mark.parametrize("g", (1, 8, 15, 16, 17, 18, 22, 25, 30, 33, 40, 48))
@pytest.mark.parametrize("name, renderer", (("t_cw_hodf", "thunk_box_thick_devfill"), ("t_cw_chiphalf", "t_si_chip")))
def test_halfopen_helper_is_the_law(img, symtab, g, name, renderer):
    mu, fn = img, symtab[name]
    rva = symtab[renderer]
    old = _stub_recorder(mu, rva)
    try:
        rc = (88, 719, 318, 770)
        mu.mem_write(RECT, struct.pack("<4i", *rc))
        mu.mem_write(REC, bytes(64))
        w32(mu, G_VA, g)
        for r in REGS:
            mu.reg_write(r, 0x5A5A0000 + r)
        mu.reg_write(UC_X86_REG_ECX, CWIN + 0x444)
        esp = SP0 - 12
        mu.mem_write(esp, struct.pack("<III", TRAP, RECT, 0x78DA28))
        mu.reg_write(UC_X86_REG_ESP, esp)
        mu.emu_start(fn, TRAP, count=200)
        assert r32(mu, REC + 32) == 1, "the renderer ran"
        seen = tuple(r32(mu, REC + 16 + 4 * i) for i in range(4))
        assert seen == (SL.council_drawn(rc, g) if g > 16 else rc), (g, seen)
        assert r32(mu, REC) == CWIN + 0x444 and r32(mu, REC + 8) == RECT and r32(mu, REC + 12) == 0x78DA28
        if g <= 16:
            assert r32(mu, REC + 4) == TRAP, "a tail jump: the renderer returns straight to the site"
        assert rect(mu, RECT) == rc, "the caller's rect restored"
        assert mu.reg_read(UC_X86_REG_ESP) == SP0, "RET 8"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == 0x5A5A0000 + r
    finally:
        mu.mem_write(rva, old)


# ---------------------------------------------------------------- W6B: the column painter's inset + the chip fix
FRAME = STACK + 0x4000      # a stand-in for the column painter's ebp frame


def test_w6_block_sites(img, symtab, bak_path):
    """The two W6B block sites: the image holds E8 -> helper (+ the jmp over the dead bytes at 0x425EEE), and the
    original bytes are the pristine base's."""
    pe = pefile.PE(data=Path(bak_path).read_bytes())
    for sid, va, orig, new, _note in CM.W6_BLOCKS:
        n = len(orig.split())
        assert pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n) == bytes.fromhex(orig.replace(" ", "")), sid
        want = ap.ByteTemplate(new).resolve(va, symtab)
        assert len(want) == n and bytes(img.mem_read(va, n)) == want, sid
    b = bytes(img.mem_read(0x425EEE, 7))
    assert b[5:7] == b"\xEB\x12" and 0x425EEE + 7 + 0x12 == 0x425F07, "the jmp lands on 0x425F07"


@pytest.mark.parametrize("g", (1, 15, 16) + tuple(range(17, 65)))
def test_inset_is_the_law(img, symtab, g):
    mu, fn = img, symtab["t_cw_inset"]
    w32(mu, G_VA, g)
    col = (79, 72, 324, 777)
    mu.mem_write(FRAME - 0x18, struct.pack("<4i", *col))
    for r in REGS:
        mu.reg_write(r, 0x5A5A0000 + r)
    mu.reg_write(UC_X86_REG_EBP, FRAME)
    w32(mu, SP0 - 4, TRAP)
    mu.reg_write(UC_X86_REG_ESP, SP0 - 4)
    mu.emu_start(fn, TRAP, count=100)
    fi = SL.council_frame_inset(g)
    L, T, R, B = col
    assert rect(mu, FRAME - 0x18) == (L + fi, T, R - fi, B - fi), "L / R / B stored, T left for the engine's store"
    assert mu.reg_read(UC_X86_REG_ECX) == T + fi and mu.reg_read(UC_X86_REG_EAX) == B - fi
    assert mu.reg_read(UC_X86_REG_EDX) == R - fi
    assert T + fi == SL.council_portrait_xy(col, g)[1], "the portrait abuts the top stroke (its x is t_cw_portx's)"
    assert mu.reg_read(UC_X86_REG_ESP) == SP0
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI):
        assert mu.reg_read(r) == 0x5A5A0000 + r


def _columns(g):
    """Every distinct column of both sets at g: (rect, kind) -- the side columns, the inner set's centre (W5B's parity
    +1 at some g) and the governor's 120 column."""
    out = {}
    for key in ("inner", "outer"):
        for i, c in enumerate(SL.council_column_rects(g)[key]):
            out.setdefault(c[2] - c[0], (c, "gov" if (key == "outer" and i == 3) else ("centre" if i == 3 else "side")))
    return list(out.values())


@pytest.mark.parametrize("g", (1, 15, 16) + tuple(range(17, 65)))
@pytest.mark.parametrize("vote", (0, -3))
def test_chipfix_is_the_law(img, symtab, g, vote):
    """The painter's chip block on the inset rect (fi = council_frame_inset) with its scaled pad dp(3) and band
    dp(0x17), then t_cw_chipfix == council_chip_rects(column) at every g, for every column width the image makes (the
    side columns, the inner centre, the governor's); eax (the vote cell) and the flags of test eax,eax survive."""
    for col0, _kind in _columns(g):
        _chipfix_case(img, symtab, g, vote, (79, 72, 79 + col0[2] - col0[0], 777))


def _chipfix_case(img, symtab, g, vote, col):
    mu, fn = img, symtab["t_cw_chipfix"]
    w32(mu, G_VA, g)
    fi = SL.council_frame_inset(g)
    Li, Ti, Ri, Bi = col[0] + fi, col[1] + fi, col[2] - fi, col[3] - fi
    s3, s17 = SL.dp(3, g), SL.dp(0x17, g)
    mu.mem_write(FRAME - 0x28, struct.pack("<4i", Li + s3, 0, 0, Bi - s3))     # L, T (written later), R, B
    mu.mem_write(FRAME - 0x18, struct.pack("<4i", Li, Ti, Ri, Bi))             # the painter's inset rect
    for r in REGS:
        mu.reg_write(r, 0x5A5A0000 + r)
    mu.reg_write(UC_X86_REG_EBP, FRAME)
    mu.reg_write(UC_X86_REG_ECX, Ri - s3)
    mu.reg_write(UC_X86_REG_EDX, Bi - s17)
    mu.reg_write(UC_X86_REG_EAX, vote & 0xFFFFFFFF)
    w32(mu, SP0 - 4, TRAP)
    mu.reg_write(UC_X86_REG_ESP, SP0 - 4)
    mu.emu_start(fn, TRAP, count=200)
    chip = (r32(mu, FRAME - 0x28), mu.reg_read(UC_X86_REG_EDX) - (1 << 32 if mu.reg_read(UC_X86_REG_EDX) >> 31 else 0),
            r32(mu, FRAME - 0x20), r32(mu, FRAME - 0x1C))
    assert chip == SL.council_chip_rects(col, g)["chip"] if g > 16 else chip == (Li + s3, Bi - s17, Ri - s3, Bi - s3), (g, chip)
    assert mu.reg_read(UC_X86_REG_EAX) == vote & 0xFFFFFFFF
    zf = (mu.reg_read(UC_X86_REG_EFLAGS) >> 6) & 1
    assert zf == (vote == 0), "test eax,eax for the je @0x42613D"
    assert mu.reg_read(UC_X86_REG_ESP) == SP0
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert mu.reg_read(r) == (FRAME if r == UC_X86_REG_EBP else 0x5A5A0000 + r)


@pytest.mark.parametrize("g", (1, 15, 16) + tuple(range(17, 65)))
def test_logox_is_the_law(img, symtab, g):
    """t_cw_logox: x := council_logo_x(column, cw) - ((cw - dp(cw)) >> 1), the amount thunk_cw_logo adds back, for every
    column width and logo canvas (the real 86, and 62 / 72 / 75); the other args, ecx and every register kept; lands
    on thunk_cw_logo (a tail jump).  g <= 16: the engine's x untouched.  (The composition with thunk_cw_logo is
    measured on the real image: test_scaling_council_mirror.)"""
    mu, fn = img, symtab["t_cw_logox"]
    tail = symtab["thunk_cw_logo"]
    old = bytes(mu.mem_read(tail, 1))
    mu.mem_write(tail, b"\xF4")
    try:
        w32(mu, G_VA, g)
        spr = STACK + 0x5000
        for col0, kind in _columns(g):
            col = (79, 72, 79 + col0[2] - col0[0], 777)
            fi = SL.council_frame_inset(g)
            for cw in (86, 62, 72, 75):
                w32(mu, spr + 0x18, cw)
                w32(mu, spr + 0x1C, 72)
                mu.mem_write(FRAME - 0x18, struct.pack("<4i", col[0] + fi, col[1] + fi, col[2] - fi, col[3] - fi))
                for r in REGS:
                    mu.reg_write(r, 0x5A5A0000 + r)
                mu.reg_write(UC_X86_REG_EBP, FRAME)
                mu.reg_write(UC_X86_REG_ECX, spr)
                x0 = col[0] + fi + 5
                args = (0x7AEC64, 9, x0, 300, 1, 1)
                esp = SP0 - 28
                mu.mem_write(esp, struct.pack("<7I", TRAP, *args))
                mu.reg_write(UC_X86_REG_ESP, esp)
                mu.emu_start(fn, tail, count=200)
                got = struct.unpack("<6i", bytes(mu.mem_read(esp + 4, 24)))
                x = SL.council_logo_x(col[0], col[2], cw, g) - ((cw - SL.dp(cw, g)) >> 1) if g > 16 else x0
                assert got == (0x7AEC64, 9, x, 300, 1, 1), (g, kind, cw, got)
                assert mu.reg_read(UC_X86_REG_ESP) == esp and mu.reg_read(UC_X86_REG_ECX) == spr
                for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI):
                    assert mu.reg_read(r) == 0x5A5A0000 + r
    finally:
        mu.mem_write(tail, old)


@pytest.mark.parametrize("g", (1, 15, 16) + tuple(range(17, 65)))
def test_portx_is_the_law(img, symtab, g):
    """t_cw_portx: the x arg += the interior slack / 2 toward zero == council_portrait_xy for both portrait canvases
    in every column width; the other args, ecx and every register kept; lands on thunk_cw_portrait (a tail jump)."""
    mu, fn = img, symtab["t_cw_portx"]
    tail = symtab["thunk_cw_portrait"]
    old = bytes(mu.mem_read(tail, 1))
    mu.mem_write(tail, b"\xF4")
    try:
        w32(mu, G_VA, g)
        spr = STACK + 0x5000
        for col0, kind in _columns(g):
            col = (79, 72, 79 + col0[2] - col0[0], 777)
            fi = SL.council_frame_inset(g)
            for sw, sh in ((96, 115), (118, 144)):
                w32(mu, spr + 0x18, sw)
                w32(mu, spr + 0x1C, sh)
                mu.mem_write(FRAME - 0x18, struct.pack("<4i", col[0] + fi, col[1] + fi, col[2] - fi, col[3] - fi))
                for r in REGS:
                    mu.reg_write(r, 0x5A5A0000 + r)
                mu.reg_write(UC_X86_REG_EBP, FRAME)
                mu.reg_write(UC_X86_REG_ECX, spr)
                args = (0x7AEC64, 9, col[0] + fi, col[1] + fi, 1, 1)
                esp = SP0 - 28
                mu.mem_write(esp, struct.pack("<7I", TRAP, *args))
                mu.reg_write(UC_X86_REG_ESP, esp)
                mu.emu_start(fn, tail, count=200)
                got = struct.unpack("<6i", bytes(mu.mem_read(esp + 4, 24)))
                x, y = SL.council_portrait_xy(col, g, sw)
                assert got == (0x7AEC64, 9, x, y, 1, 1), (g, kind, sw, got)
                assert mu.reg_read(UC_X86_REG_ESP) == esp and mu.reg_read(UC_X86_REG_ECX) == spr
                for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI):
                    assert mu.reg_read(r) == 0x5A5A0000 + r
    finally:
        mu.mem_write(tail, old)
