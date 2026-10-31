"""Differential: the chrome-pipeline CLIP fix asm vs the Python laws, emulated.

Three thunks ship for the ENERGY-band eraser fix (2026-07-19):
  * thunk_draw2_clipkey     -- KSB's out-blit: passthru when the dest clip
                               contains the blit / num!=den; keyed partial copy
                               of exactly blit_clip_visible() otherwise.
  * thunk_frame_enlarge v2  -- disarm gate: g_band_* zeroed iff NOT
                               blit_clip_contains(X, Y, dstW, dstH, clip).
  * thunk_fe_pair_remap v5  -- raw walk bounds intersected with the clip:
                               v5(full clip) must be BIT-IDENTICAL to the
                               shipped v4 bytes (popup family regression), and
                               v5(partial) == v4 masked to remap_clip_bounds.

Emulated under Unicorn on the real assembled bytes; sentinel imm32 addresses
are mapped as real pages so no byte-patching is needed.
Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scaling_laws import (  # noqa: E402
    blit_clip_contains, blit_clip_visible, remap_clip_bounds)

keystone = pytest.importorskip("keystone", reason="keystone not installed")
unicorn = pytest.importorskip("unicorn", reason="unicorn not installed")

from keystone import Ks, KS_ARCH_X86, KS_MODE_32  # noqa: E402
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP)

PCAVE2 = 0xA0C000
CODE = 0x00A00000
STACK = 0x00B00000
DATA = 0x00C00000
MARKER = 0x00DEAD00          # fake return address page

CLIPKEY_VA = PCAVE2 + 0xC0A0
ENLARGE_VA = PCAVE2 + 0xBF80
REMAP_VA = PCAVE2 + 0x10000      # v6 slot (pass 5c; 0xE380 was g_staple_scratch BSS — crashed)
REMAP_V4_VA = PCAVE2 + 0x4000    # the shipped v4 slot (same CODE mapping)

# sentinel imm32s (must match the assembler scripts)
S_BUFFER_DRAW_2 = 0x74444444
S_BILINEAR = 0x74111111
S_BANDMAP = 0x74222222
S_REMAP_CALL = 0x74333333
CF_SENT = {   # assemble_clipfix.py
    "g_fc_exact": 0x7D111111, "g_faction_scratch_rect": 0x7D222222,
    "g_fe_w": 0x7D333333, "g_fe_h": 0x7D444444, "g_fe_src": 0x7D555555,
    "g_fe_dst": 0x7D666666, "g_fe_x": 0x7D777777, "g_fe_y": 0x7D888888,
    "g_fd_bilinear": 0x7D999999, "g_band_nx": 0x7DAAAAAA,
    "g_band_ny": 0x7DBBBBBB, "g_bm_dstw": 0x7DCCCCCC, "g_bm_dsth": 0x7DDDDDDD,
}
DS_SENT = {   # assemble_devfill_stripes.py (fe_pair_remap)
    "g_popup_scale_num": 0x71111111,
    "g_fe_dst": 0x7A111111, "g_fe_x": 0x7A222222, "g_fe_y": 0x7A333333,
    "g_fe_w": 0x7A444444, "g_fe_h": 0x7A555555,
    "g_rm_xend": 0x7B111111, "g_rm_yend": 0x7B222222, "g_rm_hn": 0x7B333333,
    "g_rm_col": 0x7B444444, "g_fe_src": 0x7B555555, "g_rm_navy": 0x7B666666,
    "g_rm_povr": 0x7B777777, "g_rm_force": 0x7C111111, "g_rm_bd": 0x7C222222,
    "g_rm_bdcol": 0x7C333333,
    # v6 (pass 5c) — 0x7F family, deliberately clear of CF_SENT's 0x7D family
    "g_rm_c5": 0x7F111111, "g_rm_bf": 0x7F222222,
    "g_rm_c5col": 0x7F333333, "g_rm_bfcol": 0x7F444444,
    # v7 (sb banding fix) — F0/B9 one-shot family; the fixture's zero-filled
    # sentinel pages leave g_rm_f0ovr=0, so v7 behaves bit-identically to v6
    # in every comparison here (the pattern plane carries no 0xF0/0xB9).
    "g_rm_f0ovr": 0x7F555555, "g_rm_f0": 0x7F666666, "g_rm_f0col": 0x7F777777,
    # v8 (button faces on the parent grid) — row-phase add; the zero-filled page
    # leaves it 0, so v8 is bit-identical to v7 here.
    "g_rm_yph": 0x7F888888,
}

# Buffer struct field offsets
F_CLIP, F_BOUNDS, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x30, 0x54, 0x80, 0x84, 0x4A8


def _asm_thunk(module, name):
    src = None
    for n, off, asm in module.THUNKS:
        if n == name:
            src = "\n".join(l.split(";")[0] for l in asm.splitlines())
            va = PCAVE2 + off
    assert src is not None, f"{name} not in {module.__name__}"
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(src, va)
    return va, bytes(enc)


# The SHIPPED fe_pair_remap v4 byte template (patches.yaml @0x4000 as of commit
# 24ce958, extracted verbatim before the v5 relocation replaced it). Frozen here
# as the regression reference: v5 under a full clip must be bit-identical to it.
# 2026-10-04: its stripe period (add eax,4 / shr eax,3) carries the same in-place
# edit as the live thunk (mov eax,[g_stripe_period] / nop, law stripe_period);
# nothing else changed.
V4_REMAP_TEMPLATE = Path(__file__).with_name("clipfix_v4_remap_reference.txt")


def _v4_remap_bytes():
    """The shipped v4 bytes, sentinel-resolved."""
    out = bytearray()
    for tok in V4_REMAP_TEMPLATE.read_text(encoding="utf-8").split():
        if tok.startswith("{abs32:"):
            nm = tok[7:-1]
            assert nm in DS_SENT, f"unknown placeholder {nm}"
            out += DS_SENT[nm].to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


@pytest.fixture(scope="module")
def emu():
    import importlib
    cf = importlib.import_module("assemble_clipfix")
    ds = importlib.import_module("assemble_devfill_stripes")
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for b in (CODE, STACK, DATA, MARKER & ~0xFFFFF):
        mu.mem_map(b, 0x100000)
    pages = set()
    for v in list(CF_SENT.values()) + list(DS_SENT.values()) + [
            S_BUFFER_DRAW_2, S_BILINEAR, S_BANDMAP, S_REMAP_CALL]:
        pages.add(v & ~0xFFF)
    for p in sorted(pages):
        mu.mem_map(p, 0x1000)
    # call/jmp target stubs
    mu.mem_write(S_BUFFER_DRAW_2, b"\xC2\x18\x00")   # ret 0x18 (native contract)
    mu.mem_write(S_BILINEAR, b"\xC2\x2C\x00")
    mu.mem_write(S_BANDMAP, b"\xC2\x2C\x00")
    mu.mem_write(S_REMAP_CALL, b"\xC3")
    va, code = _asm_thunk(cf, "thunk_draw2_clipkey")
    assert va == CLIPKEY_VA
    mu.mem_write(va, code)
    va, code = _asm_thunk(cf, "thunk_frame_enlarge")
    assert va == ENLARGE_VA
    mu.mem_write(va, code)
    va, code = _asm_thunk(ds, "thunk_fe_pair_remap")
    assert va == REMAP_VA
    mu.mem_write(va, code)
    mu.mem_write(REMAP_V4_VA, _v4_remap_bytes())
    return mu


def _mk_buffer(mu, at, w, h, stride, plane_at, clip=None):
    mu.mem_write(at, b"\x00" * 0x500)
    mu.mem_write(at + F_DATA, plane_at.to_bytes(4, "little"))
    mu.mem_write(at + F_W, w.to_bytes(4, "little"))
    mu.mem_write(at + F_H, (-h) & 0xFFFFFFFF.to_bytes(4, "little")
                 if False else ((-h) & 0xFFFFFFFF).to_bytes(4, "little"))
    mu.mem_write(at + F_STRIDE, stride.to_bytes(4, "little"))
    l, t, r, b = clip if clip else (0, 0, w, h)
    for i, v in enumerate((l, t, r, b)):
        mu.mem_write(at + F_CLIP + 4 * i, (v & 0xFFFFFFFF).to_bytes(4, "little"))
    for i, v in enumerate((0, 0, w, h)):
        mu.mem_write(at + F_BOUNDS + 4 * i, v.to_bytes(4, "little"))


def _run(mu, entry, ecx, args, timeout_insns=8_000_000):
    esp = STACK + 0x8000
    frame = MARKER.to_bytes(4, "little") + b"".join(
        (a & 0xFFFFFFFF).to_bytes(4, "little") for a in args)
    esp -= len(frame)
    mu.mem_write(esp, frame)
    mu.reg_write(UC_X86_REG_ESP, esp)
    mu.reg_write(UC_X86_REG_ECX, ecx)
    mu.emu_start(entry, MARKER, count=timeout_insns)
    assert mu.reg_read(UC_X86_REG_EIP) == MARKER
    return mu.reg_read(UC_X86_REG_ESP) - esp   # stack delta distinguishes paths


# --------------------------- thunk_draw2_clipkey ---------------------------

SRC_OBJ, DST_OBJ = DATA + 0x100, DATA + 0x700
SRC_PLANE, DST_PLANE = DATA + 0x4000, DATA + 0x10000
KEY = 9


def _clipkey_case(mu, sw, sh, X, Y, clip, dw, dh, num=1, den=1):
    src_px = bytes(((x * 7 + y * 13) % 251) if (x + y) % 5 else KEY
                   for y in range(sh) for x in range(sw))
    dst_px = bytes(0xEE for _ in range(dw * dh))
    _mk_buffer(mu, SRC_OBJ, sw, sh, sw, SRC_PLANE)
    _mk_buffer(mu, DST_OBJ, dw, dh, dw, DST_PLANE, clip=clip)
    mu.mem_write(SRC_PLANE, src_px)
    mu.mem_write(DST_PLANE, dst_px)
    delta = _run(mu, CLIPKEY_VA, SRC_OBJ, [DST_OBJ, KEY, X, Y, num, den])
    got = mu.mem_read(DST_PLANE, dw * dh)
    return delta, bytes(got), src_px, dst_px


def _model_keyed(dst_px, src_px, sw, sh, X, Y, dw, dh, region):
    out = bytearray(dst_px)
    vx0, vy0, vx1, vy1 = region
    for y in range(vy0, vy1):
        for x in range(vx0, vx1):
            p = src_px[(y - Y) * sw + (x - X)]
            if p != KEY:
                out[y * dw + x] = p
    return bytes(out)


def test_clipkey_passthru_when_contained(emu):
    """clip contains the blit -> the native Buffer_draw_2 stub runs (its
    ret 0x18 leaves the same stack delta as the thunk's own ret) and, because
    the stub does not copy, the dest plane is untouched by the thunk itself."""
    delta, got, _, dst0 = _clipkey_case(emu, 20, 10, 5, 5, (0, 0, 64, 32), 64, 32)
    assert delta == 4 + 0x18
    assert got == dst0            # stub did nothing => thunk itself wrote nothing


def test_clipkey_passthru_when_not_1to1(emu):
    delta, got, _, dst0 = _clipkey_case(emu, 20, 10, 0, 0, (0, 0, 8, 8), 64, 32,
                                        num=40, den=16)
    assert delta == 4 + 0x18
    assert got == dst0


def test_clipkey_empty_intersection_writes_nothing(emu):
    delta, got, _, dst0 = _clipkey_case(emu, 20, 10, 40, 20, (0, 0, 30, 15), 64, 32)
    assert delta == 4 + 0x18
    assert got == dst0


@pytest.mark.parametrize("case", [
    # (sw, sh, X, Y, clip, dw, dh) — partial overlaps in each direction
    (20, 10, 5, 5, (10, 8, 60, 30), 64, 32),     # clipped left+top
    (20, 10, 5, 5, (0, 0, 15, 9), 64, 32),       # clipped right+bottom
    (30, 20, 0, 0, (4, 3, 26, 17), 64, 32),      # clipped all four sides
    (57, 3, 2, 28, (5, 29, 40, 30), 64, 32),     # 1px visible sliver
    (16, 16, 10, 10, (10, 10, 26, 20), 64, 32),  # flush left/top, clipped bottom
])
def test_clipkey_partial_matches_the_law(emu, case):
    sw, sh, X, Y, clip, dw, dh = case
    vis = blit_clip_visible(X, Y, sw, sh, clip)
    assert vis is not None and not blit_clip_contains(X, Y, sw, sh, clip)
    delta, got, src_px, dst0 = _clipkey_case(emu, sw, sh, X, Y, clip, dw, dh)
    assert delta == 4 + 0x18      # thunk's own ret 0x18
    want = _model_keyed(dst0, src_px, sw, sh, X, Y, dw, dh, vis)
    assert got == want


# ------------------------- thunk_frame_enlarge gate -------------------------

def _enlarge_case(mu, sw, sh, X, Y, clip, g_num=40, g_den=16,
                  arm=(6, 6, 111, 222)):
    _mk_buffer(mu, SRC_OBJ, sw, sh, sw, SRC_PLANE)
    _mk_buffer(mu, DST_OBJ, 2048, 1280, 2048, DST_PLANE, clip=clip)
    for name, v in (("g_fc_exact", 0), ("g_fd_bilinear", 0)):
        mu.mem_write(CF_SENT[name], v.to_bytes(4, "little"))
    for name, v in zip(("g_band_nx", "g_band_ny", "g_bm_dstw", "g_bm_dsth"), arm):
        mu.mem_write(CF_SENT[name], v.to_bytes(4, "little"))
    delta = _run(mu, ENLARGE_VA, SRC_OBJ, [DST_OBJ, KEY, X, Y, g_num, g_den])
    assert delta == 4 + 0x18
    return {n: int.from_bytes(mu.mem_read(CF_SENT[n], 4), "little")
            for n in ("g_band_nx", "g_band_ny", "g_bm_dstw", "g_bm_dsth",
                      "g_fe_x", "g_fe_y", "g_fe_w", "g_fe_h")}


@pytest.mark.parametrize("case", [
    # (sw, sh, X, Y, clip) with dstW=sw*40/16, dstH=sh*40/16
    (680, 404, 57, 0, (415, 650, 1747, 872)),    # THE eraser: must disarm
    (128, 20, 422, 992, (415, 880, 1747, 1102)), # LABS label: contained -> armed
    (527, 20, 422, 887, (415, 880, 1747, 1102)), # header: contained -> armed
    (100, 10, 0, 0, (0, 0, 4096, 2048)),         # huge clip: armed
    (100, 10, 50, 40, (50, 40, 300, 65)),        # flush fit exactly: armed
    (100, 10, 50, 40, (51, 40, 300, 66)),        # 1px out on the left: disarm
])
def test_enlarge_gate_follows_the_containment_law(emu, case):
    sw, sh, X, Y, clip = case
    dw, dh = sw * 40 // 16, sh * 40 // 16
    got = _enlarge_case(emu, sw, sh, X, Y, clip)
    contained = blit_clip_contains(X, Y, dw, dh, clip)
    if contained:
        assert (got["g_band_nx"], got["g_band_ny"]) == (6, 6)
        assert (got["g_bm_dstw"], got["g_bm_dsth"]) == (111, 222)
    else:
        assert (got["g_band_nx"], got["g_band_ny"]) == (0, 0)
        assert (got["g_bm_dstw"], got["g_bm_dsth"]) == (0, 0)
    # v1 staging semantics preserved regardless of the gate
    assert (got["g_fe_x"], got["g_fe_y"]) == (X, Y)
    assert (got["g_fe_w"], got["g_fe_h"]) == (dw, dh)


# ------------------------- thunk_fe_pair_remap v5 -------------------------

def _remap_case(mu, entry, plane, w, h, gx, gy, gw, gh, clip, force=0, g=40):
    """Run a remap build over a synthetic plane; returns the resulting plane."""
    _mk_buffer(mu, DST_OBJ, w, h, w, DST_PLANE, clip=clip)
    mu.mem_write(DST_PLANE, plane)
    wr = lambda name, v: mu.mem_write(DS_SENT[name], (v & 0xFFFFFFFF).to_bytes(4, "little"))
    wr("g_popup_scale_num", g)
    wr("g_fe_dst", DST_OBJ)
    wr("g_fe_x", gx); wr("g_fe_y", gy); wr("g_fe_w", gw); wr("g_fe_h", gh)
    wr("g_fe_src", 0)
    wr("g_rm_force", force)
    wr("g_rm_povr", 0)
    _run(mu, entry, 0, [])
    return bytes(mu.mem_read(DST_PLANE, w * h))


def _pattern_plane(w, h):
    fam = [0xE0, 0xE1, 0xAE, 0xEE, 0x41, 0xC4, 0xC6, 0x22, 0x63, 0x10]
    return bytes(fam[(x * 3 + y * 7) % len(fam)] for y in range(h) for x in range(w))


@pytest.mark.parametrize("case", [
    # (w, h, gx, gy, gw, gh) with FULL clip: v5 must equal shipped v4 exactly
    (48, 40, 4, 3, 40, 30),
    (48, 40, -6, -4, 30, 20),      # negative staging (v4's zero-clamp arm)
    (48, 40, 20, 25, 60, 40),      # overruns the buffer (v4's dims clamp)
])
def test_remap_v5_fullclip_is_bit_identical_to_shipped_v4(emu, case):
    w, h, gx, gy, gw, gh = case
    plane = _pattern_plane(w, h)
    for force in (0, 1):
        v4 = _remap_case(emu, REMAP_V4_VA, plane, w, h, gx, gy, gw, gh,
                         (0, 0, w, h), force=force)
        v5 = _remap_case(emu, REMAP_VA, plane, w, h, gx, gy, gw, gh,
                         (0, 0, w, h), force=force)
        assert v5 == v4, f"force={force}: v5 diverges from shipped v4 under a full clip"


@pytest.mark.parametrize("clip", [
    (10, 8, 30, 25),
    (0, 15, 48, 22),
    (25, 0, 40, 40),
    (46, 38, 48, 40),   # tiny corner
])
def test_remap_v5_partial_clip_masks_v4(emu, clip):
    """v5(partial clip) == v4 output inside remap_clip_bounds, untouched outside."""
    w, h, gx, gy, gw, gh = 48, 40, 2, 1, 44, 37
    plane = _pattern_plane(w, h)
    for force in (0, 1):
        v4 = _remap_case(emu, REMAP_V4_VA, plane, w, h, gx, gy, gw, gh,
                         (0, 0, w, h), force=force)
        v5 = _remap_case(emu, REMAP_VA, plane, w, h, gx, gy, gw, gh,
                         clip, force=force)
        x0, x1, y0, y1 = remap_clip_bounds(gx, gy, gw, gh, w, h, clip)
        want = bytearray(plane)
        for y in range(max(y0, 0), max(y1, 0)):
            for x in range(max(x0, 0), max(x1, 0)):
                want[y * w + x] = v4[y * w + x]
        assert v5 == bytes(want), f"force={force} clip={clip}"


def test_remap_v5_g16_is_a_no_op(emu):
    w, h = 48, 40
    plane = _pattern_plane(w, h)
    out = _remap_case(emu, REMAP_VA, plane, w, h, 2, 1, 44, 37,
                      (5, 5, 20, 20), force=0, g=16)
    assert out == plane
