"""Differential: the BAKED popup screen-edge thunks must agree with the Python laws.

`scaling_laws.py::popup_edge_anchor_offset / popup_edge_anchor_shift /
faction_picker_origin / faction_quote_x` are the source of truth; the x86 that
ships (scripts/assemble_popup_edge.py, resolved the way apply_patches resolves
it) runs under Unicorn.

  * thunk_popup_edge_anchor, isolated: per g in [16,40] x the CENSUS requests
    (every negative literal the game passes: -5 script, -10 Console_go_to,
    -20 BATTLE*; the sentinels 0x1000 / 0x2000; positive literals; the
    (-0x1000, 0) bounds), the placed fields move by exactly the shift law, the
    request fields are never written, edx/ebx/edi/ebp survive, and control
    tail-jumps [vtbl+0x30] with ecx == this and the site's return address
    still on the stack (the vtbl call returns into the site's NOPs).
  * the REAL vanilla placement block (0x60295A..0x602B49 from the pristine
    .bak) runs first, then the patched join: the main / flag-2 / child-popup
    arms all end at law placement. Pins the 4K Customize repro
    ([2130,1561,3835,2155] -> 12 px gap).
  * thunk_fac_origin / thunk_fac_quote_x: the picker's (5,5) and the quote box
    x reach the chained faction thunks as fl(5g/16), everything else intact.

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import (  # noqa: E402
    NATIVE_G, POPUP_LOC_CENTRE, POPUP_LOC_KEEP, faction_picker_origin, faction_quote_x,
    popup_edge_anchor_offset, popup_edge_anchor_shift, popup_place_axis,
)
import assemble_popup_edge as ASM  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

PAGE = 0x1000
PCAVE2 = ASM.PCAVE2_VA
EDGE_VA = PCAVE2 + ASM.EDGE_OFFSET
ORIGIN_VA = PCAVE2 + ASM.ORIGIN_OFFSET
QUOTE_VA = PCAVE2 + ASM.QUOTE_OFFSET
G_ADDR = 0x00668740                      # g_popup_scale_num (real VA)
ENSURE = 0x00668760                      # thunk_ensure_scale (real VA) -- stubbed
FAC_GWIN = 0x00A0D560                    # thunk_factionwin_graphicwin (chain target, stop)
FAC_QUOTE = 0x00A0D160                   # thunk_factionwin_quoteloc   (chain target, stop)
SCREEN_W = 0x009B7B1C
SCREEN_H = 0x009B7B20
SITE = ASM.SITE_EDGE                     # 0x602B49
SITE_RET = SITE + 5                      # the E8's return address (the NOPs)
VTBL_FN = 0x00700000                     # stand-in for [vtbl+0x30] (stop)
VTBL = 0x00701000
POPUP = 0x00800000                       # the BasePop (this)
PARENT = 0x00810000                      # a parent window for the child arm
STACK = 0x00200000

SYMS = {"g_popup_scale_num": G_ADDR, "thunk_ensure_scale": ENSURE,
        "thunk_factionwin_graphicwin": FAC_GWIN, "thunk_factionwin_quoteloc": FAC_QUOTE}

# Every negative request in the census, the sentinels, positive literals, and the bounds.
REQS = (-5, -10, -20, -1, -0xFFF, -0x1000, -0x1001, -0x80000000,
        0, 2, 5, 8, 40, 0x136, 0x7FF, POPUP_LOC_CENTRE, POPUP_LOC_KEEP)


def _i32(v: int) -> bytes:
    return int(v & 0xFFFFFFFF).to_bytes(4, "little")


def _rd(mu, va: int) -> int:
    return int.from_bytes(mu.mem_read(va, 4), "little", signed=True)


def _blob(off: int, tpl: str) -> bytes:
    return ASM.resolve(tpl, PCAVE2 + off, SYMS)


def _ensure_stub() -> bytes:
    """thunk_ensure_scale stand-in: if g == 0 -> g = 16 (the real one clamps to
    [16,40]); trashes eax/ecx/edx like a cdecl helper may."""
    return bytes.fromhex(
        "83 3D 40 87 66 00 00"        # cmp dword [g],0
        "75 0A"                       # jne +10
        "C7 05 40 87 66 00 10 00 00 00"  # mov dword [g],16
        "B8 11 11 11 11"              # mov eax,0x11111111
        "B9 22 22 22 22"              # mov ecx,0x22222222
        "BA 33 33 33 33"              # mov edx,0x33333333
        "C3")


@pytest.fixture(scope="module")
def uc():
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in (
        (PCAVE2 + 0x1000, 0x5000),                 # quoteloc/gwin stop VAs + the slots
        (G_ADDR & ~(PAGE - 1), PAGE),              # g + ensure stub
        (SCREEN_W & ~(PAGE - 1), PAGE),
        (SITE & ~(PAGE - 1), 2 * PAGE),            # the placement block + the site
        (VTBL_FN, 2 * PAGE),
        (POPUP, 0x10000), (PARENT, 0x10000),
        (STACK, PAGE),
    ):
        mu.mem_map(base, size)
    for name, off, tpl, size in ASM.THUNKS:
        blob = _blob(off, tpl)
        assert len(blob) == size
        mu.mem_write(PCAVE2 + off, blob)
    mu.mem_write(ENSURE, _ensure_stub())
    mu.mem_write(VTBL + 0x30, _i32(VTBL_FN))
    return mu


def _edge(mu, g: int, rx: int, ry: int, px: int = 1234, py: int = 567):
    mu.mem_write(G_ADDR, _i32(g))
    mu.mem_write(POPUP, _i32(VTBL))
    mu.mem_write(POPUP + 0x30F8, _i32(rx))
    mu.mem_write(POPUP + 0x30FC, _i32(ry))
    mu.mem_write(POPUP + 0x30B4, _i32(px))
    mu.mem_write(POPUP + 0x30B8, _i32(py))
    sp = STACK + PAGE - 0x40
    mu.mem_write(sp, _i32(SITE_RET))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ESI, POPUP)
    mu.reg_write(UC_X86_REG_EDX, 0x0D0D0D0D)
    mu.reg_write(UC_X86_REG_EBX, 0x0B0B0B0B)
    mu.reg_write(UC_X86_REG_EDI, 0x0E0E0E0E)
    mu.reg_write(UC_X86_REG_EBP, 0x0F0F0F0F)
    mu.reg_write(UC_X86_REG_EAX, 0x12345678)
    mu.reg_write(UC_X86_REG_ECX, 0x9ABCDEF0)
    mu.emu_start(EDGE_VA, VTBL_FN, count=100)
    return sp


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("rx", REQS)
@pytest.mark.parametrize("ry", (-5, -20, 0x1000, 40))
def test_edge_thunk_matches_the_shift_law(uc, g: int, rx: int, ry: int):
    sp = _edge(uc, g, rx, ry)
    assert uc.reg_read(UC_X86_REG_EIP) == VTBL_FN, "must tail-jump [vtbl+0x30]"
    assert uc.reg_read(UC_X86_REG_ESP) == sp, "stack shape: only the site's return address"
    assert _rd(uc, sp) == SITE_RET, "the vtbl call must return into the site's NOPs"
    assert uc.reg_read(UC_X86_REG_EAX) == VTBL, "replayed mov eax,[esi]"
    assert uc.reg_read(UC_X86_REG_ECX) == POPUP, "replayed mov ecx,esi"
    for reg, v in ((UC_X86_REG_EDX, 0x0D0D0D0D), (UC_X86_REG_EBX, 0x0B0B0B0B),
                   (UC_X86_REG_EDI, 0x0E0E0E0E), (UC_X86_REG_EBP, 0x0F0F0F0F),
                   (UC_X86_REG_ESI, POPUP)):
        assert uc.reg_read(reg) == v, "callee-visible register clobbered"
    assert _rd(uc, POPUP + 0x30F8) == rx
    assert _rd(uc, POPUP + 0x30FC) == ry, "request fields must never be written (exec_3 re-runs)"
    assert _rd(uc, POPUP + 0x30B4) == 1234 + popup_edge_anchor_shift(rx, g)
    assert _rd(uc, POPUP + 0x30B8) == 567 + popup_edge_anchor_shift(ry, g)
    if g <= NATIVE_G:
        assert _rd(uc, POPUP + 0x30B4) == 1234 and _rd(uc, POPUP + 0x30B8) == 567


@pytest.mark.parametrize("g,gap", ((16, 5), (22, 6), (25, 7), (40, 12)))
def test_edge_gap_pins(g: int, gap: int):
    """The shipped resolutions: 1024x768 / 1920x1080 / 1600x1200 / 4K."""
    assert popup_edge_anchor_offset(-5, g) == -gap
    assert faction_picker_origin(g) == gap == faction_quote_x(g)


# --- the REAL vanilla placement block, then the patched join -------------------------

BLOCK_START = 0x0060295A                 # mov ecx,[esi+0xa3c] (the arm dispatch)


def _run_block(mu, bak: bytes, g: int, rx: int, ry: int, *, sw: int, sh: int,
               box_w: int, box_h: int, arm: str):
    code = bak[BLOCK_START - 0x400000:SITE - 0x400000]
    mu.mem_write(BLOCK_START, code)
    patched = b"\xE8" + _i32(EDGE_VA - (SITE + 5)) + b"\x90\x90"
    mu.mem_write(SITE, patched)
    mu.mem_write(SCREEN_W, _i32(sw))
    mu.mem_write(SCREEN_H, _i32(sh))
    mu.mem_write(G_ADDR, _i32(g))
    for obj in (POPUP, PARENT):
        mu.mem_write(obj + 0x9C, _i32(0))
    mu.mem_write(POPUP, _i32(VTBL))
    mu.mem_write(POPUP + 0x30F8, _i32(rx))
    mu.mem_write(POPUP + 0x30FC, _i32(ry))
    mu.mem_write(POPUP + 0x30BC, _i32(box_w))          # child arm: box w / h
    mu.mem_write(POPUP + 0x30C0, _i32(box_h))
    if arm == "main":
        mu.mem_write(POPUP + 0xA3C, _i32(POPUP))
        mu.mem_write(POPUP + 0x4C4, _i32(box_w))       # the popup window's own extent
        mu.mem_write(POPUP + 0x4C8, _i32(-box_h))      # Buffer h is negative (top-down)
    elif arm == "flag2":                               # [win+0x9c] & 2: extents from the rect fields
        mu.mem_write(POPUP + 0xA3C, _i32(POPUP))
        mu.mem_write(POPUP + 0x9C, _i32(2))
        for off, v in ((0x14C, 0), (0x154, box_w), (0x150, 0), (0x158, box_h)):
            mu.mem_write(POPUP + off, _i32(v))
    else:                                               # child: placed inside PARENT
        mu.mem_write(POPUP + 0xA3C, _i32(PARENT))
        mu.mem_write(PARENT + 0x4C4, _i32(sw))
        mu.mem_write(PARENT + 0x4C8, _i32(-sh))
    sp = STACK + PAGE - 0x40
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ESI, POPUP)
    mu.emu_start(BLOCK_START, VTBL_FN, count=400)
    assert mu.reg_read(UC_X86_REG_EIP) == VTBL_FN
    assert _rd(mu, mu.reg_read(UC_X86_REG_ESP)) == SITE_RET
    return _rd(mu, POPUP + 0x30B4), _rd(mu, POPUP + 0x30B8)


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("req", (-5, -10, -20, POPUP_LOC_CENTRE, 5, 40))
@pytest.mark.parametrize("arm", ("main", "flag2"))
def test_real_placement_block_screen_arms(uc, bak_bytes, g: int, req: int, arm: str):
    x, y = _run_block(uc, bak_bytes, g, req, req, sw=3840, sh=2160,
                      box_w=1705, box_h=594, arm=arm)
    assert x == popup_place_axis(req, 3840, 1705, g)
    want_y = popup_place_axis(req, 2160, 594, g)
    if req == POPUP_LOC_CENTRE:          # vanilla centres y as (SH + [+0x4c8]) >> 1
        want_y = (2160 - 594) >> 1
    assert y == want_y


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("req", (-5, -20))
def test_real_placement_block_child_arm(uc, bak_bytes, g: int, req: int):
    """A child popup anchors against its parent: x = parentW - boxW + req,
    y = req - boxH - [parent+0x4c8]. Same shift law."""
    x, y = _run_block(uc, bak_bytes, g, req, req, sw=2000, sh=1000,
                      box_w=600, box_h=300, arm="child")
    off = popup_edge_anchor_offset(req, g)
    assert x == 2000 - 600 + off
    assert y == off - 300 + 1000


def test_customize_4k_repro(uc, bak_bytes):
    """Pause dump 2026-10-11 uimod.log.old:5393: [2130,1561,3835,2155] at g=40
    (5 px gap) -> the box keeps its size and sits 12 px off both edges."""
    x, y = _run_block(uc, bak_bytes, 16, -5, -5, sw=3840, sh=2160,
                      box_w=1705, box_h=594, arm="main")
    assert (x, y) == (2130, 1561), "vanilla arithmetic (g=16 path) reproduces the dump"
    x, y = _run_block(uc, bak_bytes, 40, -5, -5, sw=3840, sh=2160,
                      box_w=1705, box_h=594, arm="main")
    assert (x, y, x + 1705, y + 594) == (2123, 1554, 3828, 2148)


# --- faction picker origin + quote box x ---------------------------------------------

def _call(mu, entry: int, stop: int, args: list[int], g: int):
    mu.mem_write(G_ADDR, _i32(g))
    sp = STACK + PAGE - 0x40
    frame = [0x00488BE4] + args          # return address of the site's E8, then the args
    for i, v in enumerate(frame):
        mu.mem_write(sp + 4 * i, _i32(v))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ECX, 0x00822B00)
    mu.reg_write(UC_X86_REG_ESI, 0x00822B00)
    mu.emu_start(entry, stop, count=200)
    assert mu.reg_read(UC_X86_REG_EIP) == stop
    assert mu.reg_read(UC_X86_REG_ESP) == sp, "stack shape must be the site's call frame"
    assert mu.reg_read(UC_X86_REG_ECX) == 0x00822B00, "thiscall ecx lost"
    assert _rd(mu, sp) == 0x00488BE4
    return [_rd(mu, sp + 4 * (i + 1)) for i in range(len(args))]


@pytest.mark.parametrize("g", [0] + list(range(NATIVE_G, 41)))
def test_fac_origin(uc, g: int):
    args = [5, 5, 0x316, 0x12C, 0x834D6C, 0x1000000, 0, 0, 0]
    out = _call(uc, ORIGIN_VA, FAC_GWIN, args, g)
    g_eff = g if g else 16                # ensure_scale fills an unset g
    assert out[0] == out[1] == faction_picker_origin(g_eff)
    assert out[2:] == args[2:], "w/h/flags are the chained thunk's business"


@pytest.mark.parametrize("g", [0] + list(range(NATIVE_G, 41)))
def test_fac_quote_x(uc, g: int):
    out = _call(uc, QUOTE_VA, FAC_QUOTE, [5, 0x136], g)
    assert out[0] == (5 if g <= NATIVE_G else faction_quote_x(g))
    assert out[1] == 0x136, "y is thunk_factionwin_quoteloc's"


# --- the yaml carries exactly these templates at these slots -------------------------

def test_yaml_ledger_and_content_agree_with_the_assembler():
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    for name, off, tpl, _ in ASM.THUNKS:
        m = re.search(rf"\n  {name}:\s*\{{ cave: pcave2, offset: (0x[0-9A-Fa-f]+) \}}", text)
        assert m and int(m.group(1), 16) == off, f"{name}: ledger slot != assembler slot"
        m = re.search(rf"- id: {name}\s+offset: (0x[0-9A-Fa-f]+)\s+bytes: \"([^\"]+)\"", text)
        assert m, f"no cave content entry for {name}"
        assert int(m.group(1), 16) == off
        assert m.group(2).split() == tpl.split(), f"{name}: yaml bytes != assembler template"
    for site, thunk in ((ASM.SITE_ORIGIN, "thunk_fac_origin"), (ASM.SITE_QUOTE, "thunk_fac_quote_x"),
                        (ASM.SITE_EDGE, "thunk_popup_edge_anchor")):
        m = re.search(rf"virtual_addr: 0x{site:08X}\s+length: \d+\s+original_bytes: \"[^\"]+\"[^\n]*\n"
                      rf"\s+new_bytes:\s+\"E8 \{{rel32:{thunk}\}}", text)
        assert m, f"site 0x{site:X} must redirect to {thunk}"
