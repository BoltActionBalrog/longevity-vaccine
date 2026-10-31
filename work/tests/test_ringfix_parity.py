"""Unicorn parity for thunk_btn_ringfix (assemble_ringfix.py) — the device-density
hover-ring overdraw called from thunk_btn_2dscale's zoomed path.

Locks: ring geometry/colour vs the Python reference of scaling_laws.btn_ring_k at
g 22/25/40 (K-thick strokes all edges, per-edge art-read colours, KxK key-9 corner
notches gated on the keyed corner art alone -- v2 2026-10-24 wave-1 F33, law
scaling_laws.btn_corner_notch: every state, no longer only when a ring edge drew), the
ringless art (no strokes; corners punched iff the corner art is keyed), the no-op cases
(stateSprite path, g<=16), esp-neutrality, esi preservation, and yaml bytes ==
assembled source (sentinels == the {abs32:} placeholders).
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP  # noqa: E402

import assemble_ringfix as AR  # noqa: E402
import scaling_laws as SL  # noqa: E402

code = AR.assemble(0x500000)
BASE, BTN, CANV_DATA, ART, STACK, RET = 0x500000, 0x600000, 0x700000, 0x800000, 0x300000, 0x400000

def setup(g, state_fields, strips_colors, tl_key=9, state_sprite=0):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for a, n in ((BASE,0x1000),(BTN,0x2000),(CANV_DATA,0x20000),(ART,0x2000),(STACK,0x10000),(RET,0x1000),(0x11111000,0x1000),(0x22222000,0x1000)):
        uc.mem_map(a, n)
    uc.mem_write(BASE, code)
    uc.mem_write(0x11111111, struct.pack("<I", g))
    uc.mem_write(0x22222222, b"\xC3")
    W, H, STRIDEC = 40, 20, 48
    cv = BTN + 0x444
    uc.mem_write(cv+0x54, struct.pack("<I", CANV_DATA))
    uc.mem_write(cv+0x4A8, struct.pack("<I", STRIDEC))
    uc.mem_write(cv+0x80, struct.pack("<I", W))
    uc.mem_write(cv+0x84, struct.pack("<I", (-H)&0xFFFFFFFF))
    uc.mem_write(CANV_DATA, bytes([100])*STRIDEC*H)
    for off, v in state_fields.items():
        uc.mem_write(BTN+off, struct.pack("<I", v))
    PAR = BTN + 0x1000
    def strip(idx, w, h, fillcol, strokepos):
        sa = ART + idx*0x100
        da = ART + 0x800 + idx*0x100
        pix = bytearray([7]*(w*h))
        if strokepos == "row0":  pix[0:w] = bytes([fillcol])*w
        if strokepos == "rowl":  pix[w*(h-1):w*h] = bytes([fillcol])*w
        if strokepos == "col0":
            for y in range(h): pix[y*w] = fillcol
        if strokepos == "coll":
            for y in range(h): pix[y*w+w-1] = fillcol
        if strokepos == "corner":
            pix[0] = tl_key
        uc.mem_write(da, bytes(pix))
        for o, v in ((4,da),(0xC,w),(0x10,w),(0x14,h)):
            uc.mem_write(sa+o, struct.pack("<I", v))
        return sa
    cT,cB,cL,cR = strips_colors
    ptrs = [strip(0,6,6,0,"corner"), strip(1,6,6,0,""), strip(2,6,6,0,""), strip(3,6,6,0,""),
            strip(4,24,6,cT,"row0"), strip(5,24,6,cB,"rowl"), strip(6,6,24,cL,"col0"), strip(7,6,24,cR,"coll"), 0]
    for k,v in enumerate(ptrs): uc.mem_write(PAR+k*4, struct.pack("<I", v))
    s = 1
    uc.mem_write(BTN+0xAC8+s*4, struct.pack("<I", PAR))
    uc.mem_write(BTN+0xAD4+s*4, struct.pack("<I", state_sprite))
    uc.reg_write(UC_X86_REG_ESI, BTN)
    sp = STACK+0x8000
    uc.mem_write(sp, struct.pack("<I", RET))
    uc.reg_write(UC_X86_REG_ESP, sp)
    return uc, sp, (W,H,STRIDEC)

def reference(g, colors, tl_key, dims):
    W,H,S = dims
    cvs = bytearray(bytes([100])*S*H)
    if g <= 16: return bytes(cvs)
    K = SL.btn_ring_k(g)
    cT,cB,cL,cR = colors
    live = lambda c: c not in (7,9)
    if live(cT):
        for y in range(K): cvs[y*S:y*S+W] = bytes([cT])*W
    if live(cB):
        for y in range(H-K,H): cvs[y*S:y*S+W] = bytes([cB])*W
    if live(cL):
        for y in range(H):
            for x in range(K): cvs[y*S+x] = cL
    if live(cR):
        for y in range(H):
            for x in range(W-K,W): cvs[y*S+x] = cR
    if tl_key == 9:                     # v2: every state (the idle / pressed faces carry the same keyed corner)
        for y in range(K):
            for x in range(K):
                cvs[y*S+x] = 9; cvs[y*S+W-1-x] = 9
                cvs[(H-1-y)*S+x] = 9; cvs[(H-1-y)*S+W-1-x] = 9
    return bytes(cvs)

def run(g, colors, tl_key=9, hover=1, state_sprite=0):
    uc, sp, dims = setup(g, {0xAB8:0xFFFFFFFF, 0xA9C:0, 0xA18:0, 0xA74:hover}, colors, tl_key, state_sprite)
    uc.emu_start(BASE, RET, timeout=600_000_000)                   # us: a hang bound only -- the end marker decides
    assert uc.reg_read(UC_X86_REG_EIP) == RET, "returned (not cut short)"
    assert uc.reg_read(UC_X86_REG_ESP) == sp+4, "not esp-neutral"
    assert uc.reg_read(UC_X86_REG_ESI) == BTN
    return bytes(uc.mem_read(CANV_DATA, dims[2]*dims[1])), dims



@pytest.mark.parametrize("g", [22, 25, 40])
def test_ring_matches_reference(g):
    out, dims = run(g, (224, 224, 224, 224))
    assert out == reference(g, (224, 224, 224, 224), 9, dims)


def test_ringless_art_gets_only_the_corner_notches():
    """v2 (F33): an idle / pressed box face (edge strips all 7) draws no stroke but its keyed corner art is punched
    K x K -- the NN image of the 1-px notch was 2x2 / 3x2 / 2x3 / 3x3 at 4K (the lit HUD TOOLBAR)."""
    out, dims = run(40, (7, 7, 7, 7))
    assert out == reference(40, (7, 7, 7, 7), 9, dims)
    W, H, S = dims
    K = SL.btn_ring_k(40)
    keyed = {(y, x) for y in range(H) for x in range(W) if out[y * S + x] == 9}
    assert keyed == {(y, x) for y in list(range(K)) + list(range(H - K, H))
                     for x in list(range(K)) + list(range(W - K, W))}


def test_ringless_unkeyed_corner_untouched():
    out, dims = run(40, (7, 7, 7, 7), tl_key=0)
    assert out == bytes([100]) * dims[2] * dims[1]


def test_statesprite_path_untouched():
    out, dims = run(40, (224, 224, 224, 224), state_sprite=0x12345)
    assert out == bytes([100]) * dims[2] * dims[1]


def test_g16_untouched():
    out, dims = run(16, (224, 224, 224, 224))
    assert out == bytes([100]) * dims[2] * dims[1]


def test_mixed_colours_and_unkeyed_corner():
    out, dims = run(25, (224, 225, 224, 226), tl_key=0)
    assert out == reference(25, (224, 225, 224, 226), 0, dims)


def test_yaml_bytes_match_assembled():
    yaml_text = (ROOT / "patches" / "patches.yaml").read_bytes().decode("utf-8")
    m = re.search(r'- id: thunk_btn_ringfix\r?\n\s+offset: 0x1C800\r?\n\s+bytes: "([^"]+)"', yaml_text)
    assert m, "thunk_btn_ringfix entry missing"
    tpl = m.group(1)
    tpl = tpl.replace("{abs32:g_popup_scale_num}", "11 11 11 11")
    tpl = tpl.replace("{abs32:thunk_btn_stripes}", "22 22 22 22")
    assert bytes(int(b, 16) for b in tpl.split()) == AR.assemble(AR.PCAVE2_VA + 0x1C800) or            bytes(int(b, 16) for b in tpl.split()) == code, "yaml bytes != assembled"


def test_2dscale_calls_ringfix():
    yaml_text = (ROOT / "patches" / "patches.yaml").read_bytes().decode("utf-8")
    m = re.search(r'- id: thunk_btn_2dscale\r?\n\s+offset: 0x480\r?\n\s+bytes: "([^"]+)"', yaml_text)
    assert m
    # 2026-09-19: the call goes through t_ntw_nostripe (ntw_scale: the breakthrough window's two pixel-art icon
    # buttons skip the pass); every other button still tail-jumps into thunk_btn_ringfix.
    assert "E8 {rel32:t_ntw_nostripe}" in m.group(1)
    h = re.search(r'- id: t_ntw_nostripe\r?\n\s+offset: 0x[0-9a-fA-F]+\r?\n\s+bytes: "([^"]+)"', yaml_text)
    # 2026-10-25 W2D F39: t_ntw_nostripe tail-jumps t_btn_edgeband, whose first instruction CALLs thunk_btn_ringfix
    #   (then the 9-slice edge-stroke bands); the ringfix pass itself is unchanged.
    assert h and "68 {abs32:t_btn_edgeband} C3" in h.group(1)
    b = re.search(r'- id: t_btn_edgeband\r?\n\s+offset: 0x[0-9a-fA-F]+\r?\n\s+bytes: "([^"]+)"', yaml_text)
    assert b and b.group(1).startswith("E8 {rel32:thunk_btn_ringfix} ")
    assert "E8 {rel32:thunk_btn_stripes}" not in m.group(1)
